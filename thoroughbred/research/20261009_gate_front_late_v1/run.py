"""Directional gate and role-conditioned G3F/G1F research, using local inputs only."""

import argparse
import importlib.util
import itertools
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
OLD = HERE.parent / "20261009_section_style_finish_v1"
ROOT = HERE.parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


S = module("section_fixed", OLD / "run.py")
T = module("hypothesis_fixed", HERE.parent / "20261009_race_hypothesis_v1/run.py")
save, sha = S.save, S.sha
CONFIG = dict(
    variants=["gate_front67", "role_late89", "full103"],
    venues=[1, 3],
    years=[2024, 2025, 2026],
    close_seconds=0.15,
    front_threshold=0.4,
    bootstrap_seed=20261009,
)
BASE = json.loads((OLD / "outputs/feature_contract.json").read_text())["style_history"]
EVENTS = [
    "front_g3f",
    "front_g1f",
    "front_g3f_adv",
    "front_g1f_adv",
    "front_top3",
    "front_fade",
    "nonfront_g3f",
    "nonfront_g1f",
    "nonfront_g3f_adv",
    "nonfront_g1f_adv",
    "nonfront_g3f_pass",
    "nonfront_g1f_pass",
]


def freeze():
    OUT.mkdir(exist_ok=True)
    paths = [
        HERE / "PLAN.md",
        HERE / "run.py",
        OLD / "run.py",
        OLD / "config.json",
        T.HERE / "run.py",
        S.P / "observations.parquet",
        ROOT / "config/prediction_model_registry.json",
        S.W / "research_baseline_selection.json",
    ]
    paths += [
        OLD / "outputs" / n
        for n in [
            "features.parquet",
            "history_observations.parquet",
            "history_slots.npy",
            "feature_contract.json",
            "runner_predictions.parquet",
            "race_metrics.csv",
            "verification.json",
        ]
    ]
    paths += sorted((OLD / "outputs/finish_models").glob("3_style_history_*/*"))
    manifest = {str(p.relative_to(ROOT)): sha(p) for p in paths if p.is_file()}
    path = OUT / "input_manifest.json"
    if path.exists():
        assert json.loads(path.read_text()) == manifest
    else:
        save(path, manifest)
    save(
        HERE / "config.json",
        CONFIG | {"training": S.config()["training"], "seed": S.config()["seed"]},
    )


def check_inputs():
    for path, expected in json.loads((OUT / "input_manifest.json").read_text()).items():
        assert sha(ROOT / path) == expected, path


def history_events(h, observed):
    a = observed.copy()
    a["race_key"] = a.source_key.str.replace("서울:", "1:", regex=False).str.replace(
        "부산:", "3:", regex=False
    )
    a["program_no"] = a.gate.astype(int)
    cols = ["raw_finish_rank", "normal_outcome", "g3f", "g1f", "g3f_complete", "g1f_complete"]
    out = h.merge(a[S.KEY + cols], on=S.KEY, how="left", validate="one_to_one")
    for part in ["last600", "late"]:
        out[part + "_used"] = out[part + "_adjusted"].where(
            out[part + "_adjusted"].notna(), out[part]
        )
    for name in EVENTS:
        out[name] = np.nan
    for ix in out.groupby("race_key", sort=False).indices.values():
        g = out.iloc[ix]
        role = g.role.to_numpy(float)
        if not np.isfinite(role).any():
            continue
        normal = g.normal_outcome.fillna(False).to_numpy(bool)
        finish = g.raw_finish_rank.to_numpy(float)
        front = np.isfinite(role) & (role == 0)
        nonfront = np.isfinite(role) & (role > 0)
        for section, part in [("g3f", "last600"), ("g1f", "late")]:
            v = g[part + "_used"].to_numpy(float)
            passage = g[section].to_numpy(float)
            complete = g[section + "_complete"].fillna(False).to_numpy(bool)
            for j, idx in enumerate(ix):
                other = np.arange(len(ix)) != j
                valid = other & np.isfinite(v)
                if front[j]:
                    out.at[idx, "front_" + section] = v[j]
                    if valid.any() and np.isfinite(v[j]):
                        out.at[idx, "front_" + section + "_adv"] = v[valid].mean() - v[j]
                elif nonfront[j]:
                    out.at[idx, "nonfront_" + section] = v[j]
                    leaders = valid & front
                    if leaders.any() and np.isfinite(v[j]):
                        out.at[idx, "nonfront_" + section + "_adv"] = v[leaders].mean() - v[j]
                    ahead = (
                        other
                        & front
                        & normal
                        & complete
                        & np.isfinite(passage)
                        & (passage < passage[j])
                    )
                    if normal[j] and complete[j] and np.isfinite(passage[j]) and ahead.any():
                        out.at[idx, "nonfront_" + section + "_pass"] = float(
                            (finish[j] < finish[ahead]).any()
                        )
        eligible = front & normal
        out.loc[ix[eligible], "front_top3"] = (finish[eligible] <= 3).astype(float)
        out.loc[ix[front], "front_fade"] = g.fade.to_numpy(float)[front]
    return out


def conditional_profiles(h, ix):
    values = {}
    for name in EVENTS:
        v = S.values(h, ix, name)
        values["rolelate_" + name + "_mean5"] = S.average(v)
        values["rolelate_" + name + "_n5"] = np.isfinite(v).sum(axis=1).astype(float)
    return pd.DataFrame(values)


def gate_features(f):
    names = [
        "number",
        "inner_n",
        "outer_n",
        "inner_faster_n",
        "outer_faster_n",
        "inner_front_mass",
        "outer_front_mass",
        "inner_close_front_n",
        "outer_close_front_n",
        "inner_early_n",
        "outer_early_n",
        "early_rank_fraction",
    ]
    out = pd.DataFrame(np.nan, index=f.index, columns=["dirgate_" + n for n in names])
    for ix in f.groupby("race_key", sort=False).indices.values():
        gate = f.program_no.to_numpy(float)[ix]
        early = f.section_early_mean3.to_numpy(float)[ix]
        front = f.style_role0_rate5.to_numpy(float)[ix]
        for j, idx in enumerate(ix):
            values = {"number": gate[j]}
            for side, mask in [("inner", gate < gate[j]), ("outer", gate > gate[j])]:
                ek = mask & np.isfinite(early)
                fk = mask & np.isfinite(front)
                ck = ek & fk
                values[side + "_n"] = float(mask.sum())
                values[side + "_faster_n"] = (
                    float((early[ek] < early[j]).sum())
                    if np.isfinite(early[j]) and (ek.any() or not mask.any())
                    else np.nan
                )
                values[side + "_front_mass"] = (
                    float(front[fk].sum()) if fk.any() or not mask.any() else np.nan
                )
                values[side + "_close_front_n"] = (
                    float(
                        (
                            (np.abs(early[ck] - early[j]) <= CONFIG["close_seconds"])
                            & (front[ck] >= CONFIG["front_threshold"])
                        ).sum()
                    )
                    if np.isfinite(early[j]) and (ck.any() or not mask.any())
                    else np.nan
                )
                values[side + "_early_n"] = float(ek.sum())
            known = np.isfinite(early) & (np.arange(len(ix)) != j)
            values["early_rank_fraction"] = (
                float((early[known] < early[j]).mean())
                if known.any() and np.isfinite(early[j])
                else np.nan
            )
            out.loc[idx] = [values[n] for n in names]
    return out


def prepare():
    freeze()
    if (OUT / "prepared_features.parquet").exists():
        check_inputs()
        return
    f = pd.read_parquet(OLD / "outputs/features.parquet")
    h = pd.read_parquet(OLD / "outputs/history_observations.parquet")
    observed = pd.read_parquet(S.P / "observations.parquet")
    events = history_events(h, observed)
    events.to_parquet(OUT / "history_events.parquet", index=False)
    ix = np.load(OLD / "outputs/history_slots.npy")
    profile = conditional_profiles(events, ix)
    gate = gate_features(f)
    assert len(profile.columns) == 24 and len(gate.columns) == 12
    features = pd.concat([f, profile, gate], axis=1)
    assert len(features) == 178497 and features[BASE].equals(f[BASE])
    features.to_parquet(OUT / "prepared_features.parquet", index=False)
    save(OUT / "prepared_contract.json", dict(base=BASE, gate=list(gate), profile=list(profile)))
    check_inputs()
    print("Prepared", len(features), flush=True)


def front_stack():
    check_inputs()
    if (OUT / "front_features.parquet").exists():
        return
    f = pd.read_parquet(OUT / "prepared_features.parquet")
    contract = json.loads((OUT / "prepared_contract.json").read_text())
    f["front_label"] = f.aux_early.eq(0).astype(float).where(f.aux_early.notna())
    for task, cols in [("baseline", BASE), ("gate", BASE + contract["gate"])]:
        prediction = np.full(len(f), np.nan)
        for year in range(2020, 2027):
            train = f.year.between(2017, year - 1) & f.front_label.notna()
            x, vocab = S.encode(f, cols, train)
            params = S.config()["training"].copy()
            params.pop("max_rounds")
            params.pop("early_stopping_rounds")
            params.update(seed=42, lambda_l2=10.0)
            model = lgb.train(
                params,
                lgb.Dataset(
                    x[train],
                    label=f.loc[train, "front_label"],
                    weight=1 / f.loc[train, "field_size"],
                ),
                num_boost_round=180,
            )
            folder = OUT / "front_models" / f"{task}_{year}"
            folder.mkdir(parents=True, exist_ok=True)
            model.save_model(str(folder / "model.txt"))
            save(
                folder / "metadata.json",
                dict(
                    task=task,
                    year=year,
                    features=cols,
                    category_vocabulary=vocab,
                    train_end=str(f.loc[train, "race_date"].max().date()),
                    model_sha256=sha(folder / "model.txt"),
                ),
            )
            test = f.year.eq(year)
            prediction[test] = model.predict(x[test], num_threads=4)
            print("Front", task, year, flush=True)
        f["front_" + task + "_probability"] = prediction
    f["front_prediction_supported"] = f.front_gate_probability.notna().astype(float)
    f.to_parquet(OUT / "front_features.parquet", index=False)
    check_inputs()


def weighted_mean(v, weights, mask):
    known = mask & np.isfinite(v) & np.isfinite(weights)
    return (
        float(np.sum(v[known] * weights[known]) / weights[known].sum())
        if known.any() and weights[known].sum() > 0
        else np.nan
    )


def late_relations(f):
    names = [
        "other_front_g3f",
        "other_front_g1f",
        "own_front_g3f_adv",
        "own_front_g1f_adv",
        "own_nonfront_g3f_adv",
        "own_nonfront_g1f_adv",
        "nonfront_threat_both_mass",
        "own_catch_both_mass",
        "other_front_joint_n",
        "other_nonfront_joint_n",
        "front_mass_x_g3f_adv",
        "front_mass_x_g1f_adv",
    ]
    out = pd.DataFrame(np.nan, index=f.index, columns=["relate_" + n for n in names])
    for ix in f.groupby("race_key", sort=False).indices.values():
        p = f.front_gate_probability.to_numpy(float)[ix]
        if not np.isfinite(p).all():
            continue
        sections = []
        for section, general in [("g3f", "section_last600_mean3"), ("g1f", "section_late_mean3")]:
            raw = f[general].to_numpy(float)[ix]
            front = f["rolelate_front_" + section + "_mean5"].to_numpy(float)[ix]
            nonfront = f["rolelate_nonfront_" + section + "_mean5"].to_numpy(float)[ix]
            front = np.where(np.isfinite(front), front, raw)
            nonfront = np.where(np.isfinite(nonfront), nonfront, raw)
            projected = p * front + (1 - p) * nonfront
            sections.append((front, nonfront, projected))
        for j, idx in enumerate(ix):
            other = np.arange(len(ix)) != j
            leader_mean = []
            front_adv = []
            nonfront_adv = []
            for front, nonfront, projected in sections:
                mean_lead = weighted_mean(front, p, other)
                mean_other = weighted_mean(projected, np.ones(len(p)), other)
                leader_mean.append(mean_lead)
                front_adv.append(mean_other - front[j])
                nonfront_adv.append(mean_lead - nonfront[j])
            fg3, ng3, _ = sections[0]
            fg1, ng1, _ = sections[1]
            known_front = other & np.isfinite(fg3) & np.isfinite(fg1)
            known_nonfront = other & np.isfinite(ng3) & np.isfinite(ng1)
            threat = (
                float(
                    np.sum(
                        (1 - p[known_nonfront])
                        * ((ng3[known_nonfront] < fg3[j]) & (ng1[known_nonfront] < fg1[j]))
                    )
                )
                if known_nonfront.any() and np.isfinite(fg3[j]) and np.isfinite(fg1[j])
                else np.nan
            )
            catch = (
                float(
                    np.sum(
                        p[known_front] * ((ng3[j] < fg3[known_front]) & (ng1[j] < fg1[known_front]))
                    )
                )
                if known_front.any() and np.isfinite(ng3[j]) and np.isfinite(ng1[j])
                else np.nan
            )
            mass = float(p[other].sum())
            out.loc[idx] = [
                *leader_mean,
                *front_adv,
                *nonfront_adv,
                threat,
                catch,
                float(known_front.sum()),
                float(known_nonfront.sum()),
                mass * front_adv[0],
                mass * front_adv[1],
            ]
    return out


def finish_features():
    check_inputs()
    f = pd.read_parquet(OUT / "front_features.parquet")
    relation = late_relations(f)
    f = pd.concat([f, relation], axis=1)
    contract = json.loads((OUT / "prepared_contract.json").read_text())
    probs = ["front_gate_probability", "front_prediction_supported"]
    contracts = dict(
        style_history=BASE,
        gate_front67=BASE + contract["gate"] + probs,
        role_late89=BASE + contract["profile"] + list(relation),
        full103=BASE + contract["gate"] + contract["profile"] + list(relation) + probs,
    )
    assert [len(contracts[v]) for v in contracts] == [53, 67, 89, 103]
    assert all(
        not any(x in c for x in ["jockey", "trainer", "aux_", "front_label"])
        for cols in contracts.values()
        for c in cols
    )
    f.to_parquet(OUT / "features.parquet", index=False)
    save(OUT / "feature_contract.json", contracts)
    coverage = []
    for (meet, year), g in f.groupby(["meet", "year"]):
        coverage.append(
            dict(
                meet=int(meet),
                year=int(year),
                rows=len(g),
                front_history=int(g.rolelate_front_g3f_n5.gt(0).sum()),
                nonfront_history=int(g.rolelate_nonfront_g3f_n5.gt(0).sum()),
                g3f_pass_history=int(g.rolelate_nonfront_g3f_pass_n5.gt(0).sum()),
                g1f_pass_history=int(g.rolelate_nonfront_g1f_pass_n5.gt(0).sum()),
            )
        )
    pd.DataFrame(coverage).to_csv(OUT / "coverage.csv", index=False)
    check_inputs()


def train():
    check_inputs()
    f = pd.read_parquet(OUT / "features.parquet")
    contracts = json.loads((OUT / "feature_contract.json").read_text())
    races, runners = [], []
    for variant in CONFIG["variants"]:
        for meet in CONFIG["venues"]:
            one = f[f.meet.eq(meet)].reset_index(drop=True)
            for year in CONFIG["years"]:
                folder = OUT / "models" / f"{variant}_{meet}_{year}"
                folder.mkdir(parents=True, exist_ok=True)
                if (folder / "races.csv").exists():
                    r = pd.read_csv(folder / "races.csv")
                    p = pd.read_parquet(folder / "runners.parquet")
                else:
                    r, p = S.fit(one, contracts[variant], year, 3, variant, folder)
                    r.to_csv(folder / "races.csv", index=False)
                    p.to_parquet(folder / "runners.parquet", index=False)
                races.append(r)
                runners.append(p)
                print("Finish", variant, meet, year, flush=True)
    r = pd.read_csv(OLD / "outputs/race_metrics.csv")
    p = pd.read_parquet(OLD / "outputs/runner_predictions.parquet")
    races.append(r[r.target.eq(3) & r.variant.eq("style_history")])
    runners.append(p[p.target.eq(3) & p.variant.eq("style_history")])
    pd.concat(races, ignore_index=True).to_csv(OUT / "race_metrics.csv", index=False)
    pd.concat(runners, ignore_index=True).to_parquet(
        OUT / "runner_predictions.parquet", index=False
    )
    check_inputs()


def front_metrics(f):
    valid = f.year.ge(2024) & f.front_label.notna()
    keys = f[valid].groupby("race_key").front_label.size()
    size = f[f.year.ge(2024)].groupby("race_key").size()
    eligible = keys[keys.eq(size.reindex(keys.index))].index
    rows = []
    for rid, g in f[f.race_key.isin(eligible)].groupby("race_key"):
        for task in ["baseline", "gate"]:
            p = g["front_" + task + "_probability"].to_numpy(float)
            y = g.front_label.to_numpy(float)
            first = g.sort_values(
                ["front_" + task + "_probability", "program_no"], ascending=[False, True]
            ).iloc[0]
            rows.append(
                dict(
                    race_key=rid,
                    race_date=str(g.race_date.iloc[0].date()),
                    year=int(g.year.iloc[0]),
                    task=task,
                    runners=len(g),
                    first_front=int(first.front_label == 1),
                    front_brier=float(np.mean((p - y) ** 2)),
                )
            )
    result = pd.DataFrame(rows)
    result.to_csv(OUT / "front_race_metrics.csv", index=False)
    rng = np.random.default_rng(20261009)
    new = result[result.task.eq("gate")]
    base = result[result.task.eq("baseline")]
    g = new.merge(base, on="race_key", suffixes=("_new", "_base"), validate="one_to_one")
    comparison = []
    for metric in ["first_front", "front_brier"]:
        delta = g[metric + "_new"] - g[metric + "_base"]
        d = (
            pd.DataFrame(dict(date=g.race_date_new, delta=delta))
            .groupby("date")
            .delta.agg(["sum", "size"])
            .to_numpy()
        )
        draw = d[rng.integers(0, len(d), size=(2000, len(d)))].sum(axis=1)
        factor = 100 if metric == "first_front" else 1
        comparison.append(
            dict(
                metric=metric,
                races=len(g),
                baseline=float(g[metric + "_base"].mean()),
                gate=float(g[metric + "_new"].mean()),
                difference=float(delta.mean() * factor),
                interval95=(np.quantile(draw[:, 0] / draw[:, 1], [0.025, 0.975]) * factor).tolist(),
            )
        )
    save(OUT / "front_comparison.json", comparison)


def analyze():
    check_inputs()
    runners = pd.read_parquet(OUT / "runner_predictions.parquet")
    r = T.add_coverage(pd.read_csv(OUT / "race_metrics.csv"), runners)
    r.to_csv(OUT / "race_diagnostics.csv", index=False)
    r["distance_band"] = T.band(r.distance_m.to_numpy())
    summaries = []
    for variant, g in r.groupby("variant"):
        for scope, col in [
            ("all", None),
            ("year", "year"),
            ("meet", "meet"),
            ("distance", "distance_band"),
            ("grade", "grade"),
        ]:
            subsets = [("all", g)] if col is None else g.groupby(col, dropna=False)
            for label, sub in subsets:
                summaries.append(
                    dict(
                        variant=variant,
                        scope=scope,
                        label=str(label),
                        races=len(sub),
                        **{m: float(sub[m].mean()) for m in T.METRICS},
                    )
                )
    pd.DataFrame(summaries).to_csv(OUT / "metrics.csv", index=False)
    comparisons = []
    for i, variant in enumerate(CONFIG["variants"]):
        for period, mask in [
            ("all", r.year.ge(2024)),
            ("2024_2025", r.year.le(2025)),
            ("2026_partial", r.year.eq(2026)),
        ]:
            comparisons += [
                dict(variant=variant, period=period) | row
                for row in T.paired(
                    r[mask & r.variant.eq(variant)],
                    r[mask & r.variant.eq("style_history")],
                    20261009 + i,
                )
            ]
    save(OUT / "paired_differences.json", comparisons)
    f = pd.read_parquet(OUT / "features.parquet")
    front_metrics(f)
    example = f[f.year.ge(2024)].sort_values(["race_date", "meet", "race_no"]).iloc[-1].race_key
    contract = json.loads((OUT / "prepared_contract.json").read_text())
    cols = [
        "race_key",
        "race_date",
        "program_no",
        "horse_id",
        "horse_name",
        "distance_m",
        "front_gate_probability",
        "section_early_mean3",
        *contract["profile"],
        *[c for c in f if c.startswith("relate_")],
    ]
    f[f.race_key.eq(example)][cols].sort_values("program_no").to_csv(
        OUT / "example_card.csv", index=False
    )
    f[f.year.ge(2024)][cols].to_parquet(OUT / "runner_profiles.parquet", index=False)
    check_inputs()
    print(pd.DataFrame(summaries).query("scope == 'all'").to_string(index=False), flush=True)


def verify():
    check_inputs()
    f = pd.read_parquet(OUT / "features.parquet")
    original = pd.read_parquet(OLD / "outputs/features.parquet")
    h = pd.read_parquet(OUT / "history_events.parquet")
    ix = np.load(OLD / "outputs/history_slots.npy")
    pd.testing.assert_frame_equal(f[BASE], original[BASE])
    for lag in range(5):
        known = ix[:, lag] >= 0
        src, dst = h.iloc[ix[known, lag]], f.loc[known]
        assert np.array_equal(src.horse_id.to_numpy(), dst.horse_id.to_numpy())
        assert (src.race_date.to_numpy() <= dst.cutoff_date.to_numpy()).all()
        assert (
            (dst.race_date.to_numpy() - src.race_date.to_numpy()) / np.timedelta64(1, "D") <= 730
        ).all()
    keys = f.race_key.drop_duplicates().sample(100, random_state=42)
    mask = f.race_key.isin(keys)
    sub = f[mask].copy().reset_index(drop=True)
    for c in [c for c in sub if c.startswith("aux_") or c in ["outcome", "front_label"]]:
        sub[c] = -9999
    pd.testing.assert_frame_equal(
        gate_features(sub),
        f.loc[mask, [c for c in f if c.startswith("dirgate_")]].reset_index(drop=True),
    )
    pd.testing.assert_frame_equal(
        late_relations(sub),
        f.loc[mask, [c for c in f if c.startswith("relate_")]].reset_index(drop=True),
    )
    pd.testing.assert_frame_equal(
        conditional_profiles(h, ix[mask]),
        f.loc[mask, [c for c in f if c.startswith("rolelate_")]].reset_index(drop=True),
    )
    # Independently check historical passes and directional opponents on sampled rows.
    for idx in h[h.role.gt(0) & h.normal_outcome.eq(True)].sample(300, random_state=44).index:
        own = h.loc[idx]
        peers = h[h.race_key.eq(own.race_key)]
        for phase in ["g3f", "g1f"]:
            ahead = peers[
                peers.role.eq(0)
                & peers.normal_outcome.eq(True)
                & peers[phase + "_complete"].eq(True)
                & peers[phase].lt(own[phase])
            ]
            expected = (
                float(ahead.raw_finish_rank.gt(own.raw_finish_rank).any())
                if pd.notna(own[phase + "_complete"])
                and bool(own[phase + "_complete"])
                and pd.notna(own[phase])
                and len(ahead)
                else np.nan
            )
            assert np.isclose(expected, own["nonfront_" + phase + "_pass"], equal_nan=True)
    for idx in sub.sample(100, random_state=45).index:
        own = sub.loc[idx]
        peers = sub[sub.race_key.eq(own.race_key)]
        inside = peers[peers.program_no.lt(own.program_no)]
        assert len(inside) == own.dirgate_inner_n
        known = inside.section_early_mean3.dropna()
        expected = (
            float(known.lt(own.section_early_mean3).sum())
            if pd.notna(own.section_early_mean3) and (len(known) or not len(inside))
            else np.nan
        )
        assert np.isclose(expected, own.dirgate_inner_faster_n, equal_nan=True)
    auxiliary = 0
    for folder in sorted((OUT / "front_models").iterdir()):
        meta = json.loads((folder / "metadata.json").read_text())
        assert (
            meta["train_end"] < f"{meta['year']}-01-01"
            and sha(folder / "model.txt") == meta["model_sha256"]
        )
        train = f.year.between(2017, meta["year"] - 1) & f.front_label.notna()
        x, vocab = S.encode(f, meta["features"], train)
        assert vocab == meta["category_vocabulary"]
        test = f.year.eq(meta["year"])
        model = lgb.Booster(model_file=str(folder / "model.txt"))
        p = model.predict(x[test], num_threads=4)
        assert np.allclose(
            p, f.loc[test, "front_" + meta["task"] + "_probability"], atol=1e-12, rtol=0
        )
        auxiliary += 1
    diagnostics = pd.read_csv(OUT / "race_diagnostics.csv").set_index(["variant", "race_key"])
    count, max_error = 0, 0.0
    for folder in sorted((OUT / "models").iterdir()):
        meta = json.loads((folder / "metadata.json").read_text())
        p = pd.read_parquet(folder / "runners.parquet")
        one = f[f.meet.eq(p.meet.iloc[0])].reset_index(drop=True)
        train = one.year.between(2017, meta["evaluation_year"] - 3)
        x, vocab = S.encode(one, meta["features"], train)
        assert vocab == meta["category_vocabulary"]
        assert meta["train_end"] < f"{meta['calibration_year']}-01-01"
        assert sha(folder / "model.txt") == meta["model_sha256"]
        test = one.year.eq(meta["evaluation_year"])
        model = lgb.Booster(model_file=str(folder / "model.txt"))
        z = one[test][["race_key", "program_no", "horse_id"]].copy()
        z["score"] = model.predict(x[test], raw_score=True, num_threads=4)
        merged = z.merge(p, on=S.KEY, validate="one_to_one")
        error = float(np.max(np.abs(merged.score - merged.raw_score)))
        max_error = max(error, max_error)
        assert error <= 1e-12
        for rid, g in merged.groupby("race_key"):
            ordered = g.sort_values(["score", "program_no"], ascending=[False, True])
            outcomes = ordered.outcome.to_numpy()
            pos = np.flatnonzero((outcomes >= 1) & (outcomes <= 3)) + 1
            row = diagnostics.loc[(meta["variant"], rid)]
            for k in [3, 5, 6]:
                assert int((pos <= k).all()) == row[f"top{k}_all"]
            actual_two = set(np.flatnonzero((outcomes >= 1) & (outcomes <= 2)))
            assert int(actual_two == {0, 1}) == row.quinella_one
            assert int(0 in actual_two and actual_two <= {0, 1, 2, 3}) == row.axis_next3
            assert int(1 <= outcomes[0] <= 3) == row.axis_top3
            assert int(1 <= outcomes[0] <= 2) == row.axis_top2
            sets = np.array(list(itertools.combinations(range(len(g)), 3)))
            energy = g.score.to_numpy()[sets].sum(axis=1) / meta["temperature"]
            q = np.exp(energy - logsumexp(energy))
            marginal = np.zeros(len(g))
            for j, combo in enumerate(sets):
                marginal[combo] += q[j]
            assert np.allclose(marginal, g.target_probability, atol=1e-12, rtol=0)
        count += 1
    assert count == 18 and auxiliary == 14
    predictions = pd.read_parquet(OUT / "runner_predictions.parquet")
    for _variant, g in predictions.groupby("variant"):
        assert len(g) == 50754 and g.race_key.nunique() == 4799
    check_inputs()
    save(
        OUT / "verification.json",
        dict(
            passed=True,
            finish_models_replayed=count,
            front_models_replayed=auxiliary,
            max_score_error=max_error,
            original53_unchanged=True,
            target_poisoning_unchanged=True,
            independent_historical_pass_rows=300,
            independent_gate_rows=100,
            prior_only_front_predictions=True,
            input_hashes_unchanged=True,
            production_changed=False,
        ),
    )
    print("Verification passed", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage", choices=["prepare", "front_stack", "finish_features", "train", "analyze", "verify"]
    )
    args = parser.parse_args()
    globals()[args.stage]()
