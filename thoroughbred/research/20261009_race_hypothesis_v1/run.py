"""Past-only race hypothesis ablations using fixed local research inputs."""

import argparse
import hashlib
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
spec = importlib.util.spec_from_file_location("section_frozen", OLD / "run.py")
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)
CONFIG = dict(
    variants=["hypothesis_trend", "hypothesis_distance", "hypothesis_pace", "hypothesis_all"],
    baseline="style_history",
    target=3,
    years=[2024, 2025, 2026],
    venues=[1, 3],
    front_threshold=0.4,
    close_seconds=0.15,
    bootstrap_draws=2000,
    bootstrap_seed=20261009,
)
METRICS = [
    "axis_top3",
    "top5_all",
    "axis_top2",
    "top6_all",
    "top3_all",
    "quinella_one",
    "axis_next3",
    "target_brier",
    "set_logloss",
]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze():
    OUT.mkdir(exist_ok=True)
    paths = [HERE / "PLAN.md", HERE / "run.py", OLD / "run.py", OLD / "config.json"]
    paths += [
        OLD / "outputs" / n
        for n in [
            "features.parquet",
            "history_observations.parquet",
            "history_slots.npy",
            "feature_contract.json",
            "runner_predictions.parquet",
            "race_metrics.csv",
            "input_manifest.json",
            "verification.json",
        ]
    ]
    paths += sorted((OLD / "outputs/finish_models").glob("3_style_history_*/*"))
    paths += [
        ROOT / "config/prediction_model_registry.json",
        S.W / "research_baseline_selection.json",
    ]
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
    for name, digest in json.loads((OUT / "input_manifest.json").read_text()).items():
        assert sha(ROOT / name) == digest, name


def band(v):
    return np.where(np.isfinite(v), np.where(v <= 1300, 0.0, np.where(v <= 1600, 1.0, 2.0)), np.nan)


def arrays(h, ix, col):
    v = S.values(h, ix, col)
    if col.endswith("_adjusted"):
        v = np.where(np.isfinite(v), v, S.values(h, ix, col.removesuffix("_adjusted")))
    return v


def build(f, h, ix):
    trend = {}
    for part in S.PARTS:
        v = arrays(h, ix, part + "_adjusted")
        trend[f"hyp_trend_{part}_last_gain"] = S.average(v[:, 1:3], 2) - v[:, 0]
        trend[f"hyp_trend_{part}_recent_gain"] = S.average(v[:, 3:5], 2) - S.average(v, 3)
        trend[f"hyp_trend_{part}_recent_n"] = np.isfinite(v[:, :3]).sum(axis=1).astype(float)
        trend[f"hyp_trend_{part}_older_n"] = np.isfinite(v[:, 3:5]).sum(axis=1).astype(float)
    d = arrays(h, ix, "result_distance")
    current = f.distance_m.to_numpy(float)
    same = (band(d) == band(current)[:, None]) & (ix >= 0)
    distance = {
        "hyp_distance_change": current - d[:, 0],
        "hyp_distance_change_abs": np.abs(current - d[:, 0]),
        "hyp_distance_band_changed": np.where(
            np.isfinite(d[:, 0]), (band(current) != band(d[:, 0])).astype(float), np.nan
        ),
        "hyp_distance_same_band_n": same.sum(axis=1).astype(float),
    }
    for col in ["role0", "middle_gain", "gain400", "recovery", "fade", "last600_adjusted"]:
        v = np.where(same, arrays(h, ix, col), np.nan)
        distance["hyp_distance_" + col + "_mean"] = S.average(v)
        distance["hyp_distance_" + col + "_n"] = np.isfinite(v).sum(axis=1).astype(float)
    names = [
        "other_front_mass",
        "other_front_n",
        "other_front_ge40_n",
        "other_fast_close_n",
        "other_early_n",
        "early_fastest_gap",
        "last600_advantage",
        "late_advantage",
        "last600_other_n",
        "late_other_n",
        "front_x_mass",
        "fade_x_mass",
        "recovery_x_mass",
        "gain400_x_mass",
        "last600_advantage_x_mass",
        "late_advantage_x_mass",
    ]
    pace = pd.DataFrame(np.nan, index=f.index, columns=["hyp_pace_" + n for n in names])
    cols = [
        "style_role0_rate5",
        "section_early_mean3",
        "section_last600_mean3",
        "section_late_mean3",
    ]
    for ix_race in f.groupby("race_key", sort=False).indices.values():
        front, early, last600, late = [f[c].to_numpy(float)[ix_race] for c in cols]
        for j, idx in enumerate(ix_race):
            other = np.arange(len(ix_race)) != j
            fk = other & np.isfinite(front)
            ek = other & np.isfinite(early)
            mass = float(front[fk].sum()) if fk.any() else np.nan
            close_ok = other & np.isfinite(front) & np.isfinite(early)
            close = np.nan
            if close_ok.any() and np.isfinite(front[j]) and np.isfinite(early[j]):
                close = float(
                    (
                        (front[close_ok] >= CONFIG["front_threshold"])
                        & (np.abs(early[close_ok] - early[j]) <= CONFIG["close_seconds"])
                        & (front[j] >= CONFIG["front_threshold"])
                    ).sum()
                )
            adv = []
            support = []
            for v in [last600, late]:
                known = other & np.isfinite(v)
                adv.append(
                    float(v[known].mean() - v[j]) if known.any() and np.isfinite(v[j]) else np.nan
                )
                support.append(float(known.sum()))
            values = [
                mass,
                float(fk.sum()),
                float((front[fk] >= CONFIG["front_threshold"]).sum()) if fk.any() else np.nan,
                close,
                float(ek.sum()),
                float(early[j] - early[ek].min()) if ek.any() and np.isfinite(early[j]) else np.nan,
                *adv,
                *support,
                front[j] * mass,
                f.at[idx, "style_fade_mean5"] * mass,
                f.at[idx, "style_recovery_mean5"] * mass,
                f.at[idx, "style_gain400_mean5"] * mass,
                adv[0] * mass,
                adv[1] * mass,
            ]
            pace.loc[idx] = values
    groups = {
        "trend": pd.DataFrame(trend, index=f.index),
        "distance": pd.DataFrame(distance, index=f.index),
        "pace": pace,
    }
    assert [len(groups[k].columns) for k in groups] == [12, 16, 16]
    return groups


def prepare():
    freeze()
    if (OUT / "features.parquet").exists():
        check_inputs()
        return
    f = pd.read_parquet(OLD / "outputs/features.parquet")
    h = pd.read_parquet(OLD / "outputs/history_observations.parquet")
    ix = np.load(OLD / "outputs/history_slots.npy")
    groups = build(f, h, ix)
    base = json.loads((OLD / "outputs/feature_contract.json").read_text())["style_history"]
    contracts = {"style_history": base}
    for name, frame in groups.items():
        contracts["hypothesis_" + name] = base + list(frame)
    extra = pd.concat(groups.values(), axis=1)
    contracts["hypothesis_all"] = base + list(extra)
    features = pd.concat([f, extra], axis=1)
    assert len(f) == 178497 and features[base].equals(f[base])
    assert all(
        not any(s in c for s in ["jockey", "trainer", "aux_"])
        for cols in contracts.values()
        for c in cols
    )
    features.to_parquet(OUT / "features.parquet", index=False)
    save(OUT / "feature_contract.json", contracts)
    coverage = []
    for (meet, year), g in features.groupby(["meet", "year"]):
        for group, frame in groups.items():
            coverage.append(
                dict(
                    meet=int(meet),
                    year=int(year),
                    group=group,
                    rows=len(g),
                    any_nonmissing=int(frame.loc[g.index].notna().any(axis=1).sum()),
                )
            )
    pd.DataFrame(coverage).to_csv(OUT / "coverage.csv", index=False)
    check_inputs()
    print("Prepared", {k: len(v) for k, v in contracts.items()}, flush=True)


def train():
    check_inputs()
    f = pd.read_parquet(OUT / "features.parquet")
    contracts = json.loads((OUT / "feature_contract.json").read_text())
    all_races = []
    all_runners = []
    for variant in CONFIG["variants"]:
        for meet in CONFIG["venues"]:
            one = f[f.meet.eq(meet)].reset_index(drop=True)
            for year in CONFIG["years"]:
                folder = OUT / "models" / f"{variant}_{meet}_{year}"
                folder.mkdir(parents=True, exist_ok=True)
                if (folder / "races.csv").exists():
                    races = pd.read_csv(folder / "races.csv")
                    runners = pd.read_parquet(folder / "runners.parquet")
                else:
                    races, runners = S.fit(one, contracts[variant], year, 3, variant, folder)
                    races.to_csv(folder / "races.csv", index=False)
                    runners.to_parquet(folder / "runners.parquet", index=False)
                all_races.append(races)
                all_runners.append(runners)
                print(
                    "Trained", variant, meet, year, "axis3", int(races.axis_top3.sum()), flush=True
                )
    old_r = pd.read_csv(OLD / "outputs/race_metrics.csv")
    old_p = pd.read_parquet(OLD / "outputs/runner_predictions.parquet")
    all_races.append(old_r[old_r.target.eq(3) & old_r.variant.eq("style_history")])
    all_runners.append(old_p[old_p.target.eq(3) & old_p.variant.eq("style_history")])
    pd.concat(all_races, ignore_index=True).to_csv(OUT / "race_metrics.csv", index=False)
    pd.concat(all_runners, ignore_index=True).to_parquet(
        OUT / "runner_predictions.parquet", index=False
    )
    check_inputs()


def add_coverage(races, runners):
    rows = []
    for (variant, rid), g in runners.groupby(["variant", "race_key"]):
        g = g.sort_values(["raw_score", "program_no"], ascending=[False, True])
        positions = np.flatnonzero(g.outcome.between(1, 3)) + 1
        assert len(positions) == 3
        rows.append(
            dict(
                variant=variant,
                race_key=rid,
                **{f"top{k}_all": int((positions <= k).all()) for k in [3, 5, 6]},
            )
        )
    return races.merge(pd.DataFrame(rows), on=["variant", "race_key"], validate="one_to_one")


def paired(a, b, seed):
    g = a.merge(b, on="race_key", suffixes=("_new", "_base"), validate="one_to_one")
    assert len(g) == len(a) == len(b)
    result = []
    rng = np.random.default_rng(seed)
    for metric in METRICS:
        delta = g[metric + "_new"] - g[metric + "_base"]
        d = (
            pd.DataFrame(dict(date=g.race_date_new, delta=delta))
            .groupby("date")
            .delta.agg(["sum", "size"])
            .to_numpy()
        )
        draws = d[rng.integers(0, len(d), size=(CONFIG["bootstrap_draws"], len(d)))].sum(axis=1)
        factor = 1 if metric in ["target_brier", "set_logloss"] else 100
        result.append(
            dict(
                metric=metric,
                races=len(g),
                new_mean=float(g[metric + "_new"].mean()),
                base_mean=float(g[metric + "_base"].mean()),
                difference=float(delta.mean() * factor),
                interval95=(
                    np.quantile(draws[:, 0] / draws[:, 1], [0.025, 0.975]) * factor
                ).tolist(),
                units="loss" if factor == 1 else "percentage_points",
            )
        )
    return result


def analyze():
    check_inputs()
    r = add_coverage(
        pd.read_csv(OUT / "race_metrics.csv"), pd.read_parquet(OUT / "runner_predictions.parquet")
    )
    r.to_csv(OUT / "race_diagnostics.csv", index=False)
    r["distance_band"] = band(r.distance_m.to_numpy())
    summaries = []
    for variant, g in r.groupby("variant"):
        for scope, col in [
            ("all", None),
            ("meet", "meet"),
            ("year", "year"),
            ("distance", "distance_band"),
            ("grade", "grade"),
        ]:
            groups = [("all", g)] if col is None else g.groupby(col, dropna=False)
            for label, sub in groups:
                summaries.append(
                    dict(
                        variant=variant,
                        scope=scope,
                        label=str(label),
                        races=len(sub),
                        **{m: float(sub[m].mean()) for m in METRICS},
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
            rows = paired(
                r[mask & r.variant.eq(variant)],
                r[mask & r.variant.eq("style_history")],
                CONFIG["bootstrap_seed"] + i,
            )
            comparisons += [dict(variant=variant, period=period) | row for row in rows]
    save(OUT / "paired_differences.json", comparisons)
    check_inputs()
    print(pd.DataFrame(summaries).query("scope == 'all'").to_string(index=False), flush=True)


def verify():
    check_inputs()
    f = pd.read_parquet(OUT / "features.parquet")
    original = pd.read_parquet(OLD / "outputs/features.parquet")
    h = pd.read_parquet(OLD / "outputs/history_observations.parquet")
    ix = np.load(OLD / "outputs/history_slots.npy")
    contracts = json.loads((OUT / "feature_contract.json").read_text())
    assert f[contracts["style_history"]].equals(original[contracts["style_history"]])
    # Every slot is a prior actual start of this horse and inside the fixed cutoff.
    for lag in range(5):
        known = ix[:, lag] >= 0
        src = h.iloc[ix[known, lag]]
        dst = f.loc[known]
        assert np.array_equal(src.horse_id.to_numpy(), dst.horse_id.to_numpy())
        assert (src.race_date.to_numpy() <= dst.cutoff_date.to_numpy()).all()
        assert (
            (dst.race_date.to_numpy() - src.race_date.to_numpy()) / np.timedelta64(1, "D") <= 730
        ).all()
    # Rebuild on sampled *whole* fields after poisoning present outcomes and labels.
    keys = original.race_key.drop_duplicates().sample(100, random_state=42)
    mask = original.race_key.isin(keys)
    sub = original[mask].copy().reset_index(drop=True)
    six = ix[mask]
    expected = build(sub, h, six)
    for c in [c for c in sub if c.startswith("aux_") or c == "outcome"]:
        sub[c] = -9999
    poisoned = build(sub, h, six)
    for name in expected:
        pd.testing.assert_frame_equal(expected[name], poisoned[name])
        pd.testing.assert_frame_equal(
            expected[name].reset_index(drop=True),
            f.loc[mask, expected[name].columns].reset_index(drop=True),
        )
    # Independent scalar checks of sampled hypotheses, including self exclusion.
    sample = f.sample(300, random_state=43)
    for idx, row in sample.iterrows():
        slots = ix[idx]
        for part in S.PARTS:
            v = []
            for loc in slots:
                if loc < 0:
                    v.append(np.nan)
                else:
                    v.append(
                        h.iloc[loc][part + "_adjusted"]
                        if pd.notna(h.iloc[loc][part + "_adjusted"])
                        else h.iloc[loc][part]
                    )
            prev = [x for x in v[1:3] if np.isfinite(x)]
            actual = np.mean(prev) - v[0] if prev else np.nan
            assert np.isclose(actual, row[f"hyp_trend_{part}_last_gain"], equal_nan=True)
        same = [
            loc
            for loc in slots
            if loc >= 0
            and band(np.array([h.iloc[loc].result_distance]))[0]
            == band(np.array([row.distance_m]))[0]
        ]
        assert len(same) == row.hyp_distance_same_band_n
        others = f[f.race_key.eq(row.race_key) & f.program_no.ne(row.program_no)]
        vals = others.style_role0_rate5.dropna()
        assert np.isclose(
            vals.sum() if len(vals) else np.nan, row.hyp_pace_other_front_mass, equal_nan=True
        )
    predictions = pd.read_parquet(OUT / "runner_predictions.parquet")
    diagnostics = pd.read_csv(OUT / "race_diagnostics.csv")
    models = 0
    max_error = 0.0
    for folder in sorted((OUT / "models").iterdir()):
        meta = json.loads((folder / "metadata.json").read_text())
        p = pd.read_parquet(folder / "runners.parquet")
        one = f[f.meet.eq(p.meet.iloc[0])].reset_index(drop=True)
        train = one.year.between(2017, meta["evaluation_year"] - 3)
        x, vocab = S.encode(one, meta["features"], train)
        assert (
            vocab == meta["category_vocabulary"]
            and meta["train_end"] < f"{meta['calibration_year']}-01-01"
        )
        assert sha(folder / "model.txt") == meta["model_sha256"]
        test = one.year.eq(meta["evaluation_year"])
        model = lgb.Booster(model_file=str(folder / "model.txt"))
        score = model.predict(x[test], raw_score=True, num_threads=4)
        check = one[test][["race_key", "program_no", "horse_id", "outcome"]].copy()
        check["score"] = score
        merged = check.merge(p, on=["race_key", "program_no", "horse_id"], validate="one_to_one")
        error = float(np.max(np.abs(merged.score - merged.raw_score)))
        max_error = max(max_error, error)
        assert error <= 1e-12
        for rid, g in merged.groupby("race_key"):
            z = g.sort_values(["score", "program_no"], ascending=[False, True])
            outcomes = z.outcome_x.to_numpy()
            pos = np.flatnonzero((outcomes >= 1) & (outcomes <= 3)) + 1
            row = diagnostics[
                diagnostics.variant.eq(meta["variant"]) & diagnostics.race_key.eq(rid)
            ].iloc[0]
            assert int(1 <= outcomes[0] <= 3) == row.axis_top3
            for k in [3, 5, 6]:
                assert int((pos <= k).all()) == row[f"top{k}_all"]
            sets = np.array(list(itertools.combinations(range(len(g)), 3)))
            energy = g.score.to_numpy()[sets].sum(axis=1) / meta["temperature"]
            q = np.exp(energy - logsumexp(energy))
            marginal = np.zeros(len(g))
            for k, combo in enumerate(sets):
                marginal[combo] += q[k]
            assert np.allclose(marginal, g.target_probability.to_numpy(), atol=1e-12, rtol=0)
            assert abs(marginal.sum() - 3) < 1e-12
        models += 1
    assert models == 24
    for _variant, g in predictions.groupby("variant"):
        assert g.race_key.nunique() == 4799 and len(g) == 50754
    check_inputs()
    save(
        OUT / "verification.json",
        dict(
            passed=True,
            new_models_replayed=models,
            max_raw_score_error=max_error,
            original53_unchanged=True,
            current_target_poisoning_unchanged=True,
            history_slots_verified=True,
            independent_sample_rows=300,
            baseline_retained=True,
            input_hashes_unchanged=True,
            production_changed=False,
        ),
    )
    print("Verification passed", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "train", "analyze", "verify"])
    args = parser.parse_args()
    globals()[args.stage]()
