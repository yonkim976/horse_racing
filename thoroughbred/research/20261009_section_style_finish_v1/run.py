"""Frozen retrospective section/style ablations; no DB/network/production writes."""

import argparse
import importlib.util
import itertools
import json
from functools import lru_cache
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
W = R / "20261008_profile_carried_weight_v1/outputs"
P = R / "20261008_field_pace_prediction/outputs"
PARTS = ["early", "last600", "late"]
KEY = ["race_key", "program_no", "horse_id"]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


B = module("frozen_profile", R / "20261008_horse_profile_model_v1/run.py")
E = module("annual_environment", R / "20261008_profile_environment_ablation_v1/run.py")
S = module("section_effects", R / "20261008_section_normalization_candidate_v1/analyze.py")
sha, save = B.sha, B.save
BASE = json.loads((W / "research_baseline_selection.json").read_text())["features"]


def config():
    return json.loads((HERE / "config.json").read_text())


def freeze():
    OUT.mkdir(exist_ok=True)
    paths = [
        HERE / "run.py",
        HERE / "PLAN.md",
        HERE / "config.json",
        W / "features_month_gate_weight22.parquet",
        W / "research_baseline_selection.json",
        W / "runner_predictions.parquet",
        W / "race_metrics.csv",
        B.RECORDS,
        P / "observations.parquet",
        E.N.POP,
        E.N.GATES,
        B.HERE / "run.py",
        E.HERE / "run.py",
        S.HERE / "analyze.py",
        S.B.HERE / "build.py",
        S.A.HERE / "analyze.py",
        S.L.HERE / "analyze.py",
        E.N.HERE / "analyze.py",
        ROOT / "config/prediction_model_registry.json",
        R / "20261004_close_contenders_v1/outputs/operating_runner_predictions.parquet",
    ]
    paths += list((W / "models").glob("*_month_gate_weight22/*.txt"))
    paths += list((W / "models").glob("*_month_gate_weight22/metadata.json"))
    paths += list((E.OUT / "coefficients").glob("*/outlier_masks.parquet"))
    registry = json.loads((ROOT / "config/prediction_model_registry.json").read_text())
    # The registry itself and fixed operating predictions are immutable references.
    assert registry
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    target = OUT / "input_manifest.json"
    if target.exists():
        assert json.loads(target.read_text()) == hashes, "Frozen input changed"
    else:
        save(target, hashes)


def check_inputs():
    for path, expected in json.loads((OUT / "input_manifest.json").read_text()).items():
        assert sha(ROOT / path) == expected, path


def population():
    d = E.population()
    sec = pd.read_parquet(P / "observations.parquet", columns=["row_key", *PARTS])
    d = d.merge(sec, on="row_key", validate="one_to_one")
    assert d[PARTS].notna().all().all()
    return d


def moisture_specs(original):
    """Extend the same horse-FE monthly fit with identifiable dry-state contrasts."""

    def specs(d, kind):
        x, labels, values = original(d, kind)
        if kind != "month":
            return x, labels, values
        dry = d[d.moisture.between(1, 5)]
        if dry.empty:
            return x, labels, values

        def vector(g):
            out = np.zeros(len(labels))
            mix = g.moisture.value_counts(normalize=True)
            for moisture, fraction in mix.items():
                name = "control:moisture:" + str(moisture)
                if name in labels:
                    out[labels.index(name)] = fraction
            return out

        reference = vector(dry)
        for band, g in d.groupby("band", observed=True):
            support = dict(
                rows=len(g),
                races=int(g.race_key.nunique()),
                days=int(g.date.nunique()),
                years=int(g.year.nunique()),
            )
            supported = len(g) >= 100 and support["races"] >= 20 and support["years"] >= 2
            values.append(
                (
                    vector(g) - reference,
                    dict(
                        family="moisture",
                        block="annual",
                        level=band,
                        support=[support],
                        supported=bool(supported),
                    ),
                )
            )
        return x, labels, values

    return specs


def environment():
    if (OUT / "section_corrections.parquet").exists():
        return
    d = population()
    original = S.specs_for
    S.specs_for = moisture_specs(original)
    folders = OUT / "environment"
    folders.mkdir(exist_ok=True)
    for year in range(2020, 2027):
        folder = folders / str(year)
        if (folder / "complete.json").exists():
            continue
        folder.mkdir(exist_ok=True)
        prior = d[d.year.lt(year)].copy()
        masks = pd.read_parquet(E.OUT / "coefficients" / str(year) / "outlier_masks.parquet")
        prior = prior.merge(masks, on="row_key", how="left", validate="one_to_one")
        rows, models = [], []
        for (meet, dist), all_prior in prior.groupby(["meet", "distance_m"], observed=True):
            g = all_prior[all_prior.mad4_keep.eq(True)].reset_index(drop=True)
            if not S.L.minimum(g, False):
                continue
            for kind in ["base", "state", "month"]:
                matrices = {}
                meta = dict(meet=meet, distance_m=int(dist), period="all_mad4", model_type=kind)
                rr, model = S.fit(g, meta, matrices)
                rows.extend(rr)
                models.append(
                    model | dict(coefficient_year=year, source_max=str(g.date.max().date()))
                )
            print("Environment", year, meet, dist, len(g), flush=True)
        effects = pd.DataFrame(rows)
        effects["q"] = 1.0
        effects["support"] = effects.support.map(json.dumps)
        gate_tables, months, moist = [], [], []
        for part in PARTS:
            S.B.POLICY["base_cap_seconds"] = S.CAPS[part][0]
            S.B.POLICY["state_cap_seconds"] = S.CAPS[part][1]
            table = S.B.build_table(
                prior,
                effects[effects.model_type.eq("base") & effects.section.eq(part)],
                effects[effects.model_type.eq("state") & effects.section.eq(part)],
            )
            gate_tables.append(table[table.period.eq("all_mad4")].assign(section=part))
        for (meet, dist, part), g in effects[
            effects.model_type.eq("month") & effects.family.eq("month")
        ].groupby(["meet", "distance_m", "section"], observed=True):
            g = g.assign(month=g.level.astype(int)).sort_values("month")
            available = len(g) == 12 and g.estimable.all()
            count = np.array([json.loads(v)[0]["rows"] for v in g.support])
            raw = (
                0.30 * count / (count + 100) * g.effect_seconds.to_numpy()
                if available
                else np.zeros(len(g))
            )
            centered = raw - raw.mean()
            scale = min(1.0, S.CAPS[part][2] / max(abs(centered).max(), 1e-15))
            for r, add in zip(g.itertuples(), -centered * scale, strict=True):
                months.append(
                    dict(
                        meet=meet,
                        distance_m=int(dist),
                        section=part,
                        month=r.month,
                        month_add=float(add),
                        available=bool(available),
                    )
                )
        for r in effects[
            effects.model_type.eq("month") & effects.family.eq("moisture")
        ].itertuples():
            fraction = (
                (0.4 if r.section == "last600" else 0.6)
                if r.meet == "서울"
                else (0.3 if r.section == "last600" else 0.4)
            )
            moist.append(
                dict(
                    meet=r.meet,
                    distance_m=int(r.distance_m),
                    section=r.section,
                    band=r.level,
                    moisture_add=float(-fraction * r.effect_seconds) if r.supported else None,
                    supported=bool(r.supported),
                )
            )
        effects.to_parquet(folder / "effects.parquet", index=False)
        pd.concat(gate_tables, ignore_index=True).to_parquet(folder / "gates.parquet", index=False)
        pd.DataFrame(months).to_parquet(folder / "months.parquet", index=False)
        pd.DataFrame(moist).to_parquet(folder / "moisture.parquet", index=False)
        save(folder / "models.json", models)
        save(
            folder / "complete.json",
            dict(
                year=year,
                trained_through=year - 1,
                source_max=str(prior.date.max().date()),
                models=len(models),
                hashes={p.name: sha(p) for p in folder.iterdir() if p.is_file()},
            ),
        )
    S.specs_for = original
    out = d[["row_key", "year"]].copy()
    for part in PARTS:
        out[part + "_adjusted"] = d[part].to_numpy()
        out[part + "_correction"] = 0.0
        out[part + "_correction_supported"] = False
    for year in range(2020, 2027):
        folder = folders / str(year)
        gate = pd.read_parquet(folder / "gates.parquet").rename(columns={"field_size": "n"})
        month = pd.read_parquet(folder / "months.parquet")
        moist = pd.read_parquet(folder / "moisture.parquet")
        for part in PARTS:
            target = d[d.year.eq(year)].copy()
            target["_row"] = target.index
            m = month[month.section.eq(part)].drop(columns="section")
            k = moist[moist.section.eq(part)].drop(columns="section")
            target = target.merge(
                m, on=["meet", "distance_m", "month"], how="left", validate="many_to_one"
            )
            target = target.merge(
                k, on=["meet", "distance_m", "band"], how="left", validate="many_to_one"
            )
            target["mode"] = np.where(target.gate_block.str.startswith("exact"), "number", "group")
            target["level"] = np.where(
                target["mode"].eq("number"),
                target.horse_number.astype(int).astype(str),
                target.gate_side,
            )
            gt = gate[gate.section.eq(part)][
                ["meet", "distance_m", "n", "mode", "band", "level", "gate_add_seconds"]
            ]
            target = target.merge(
                gt,
                on=["meet", "distance_m", "n", "mode", "band", "level"],
                how="left",
                validate="many_to_one",
            )
            ok = target.supported.eq(True)
            add = (
                target.moisture_add + target.month_add.fillna(0) + target.gate_add_seconds.fillna(0)
            ).where(ok, 0.0)
            ix = target._row.to_numpy()
            out.loc[ix, part + "_adjusted"] = target[part].to_numpy() + add.to_numpy()
            out.loc[ix, part + "_correction"] = add.to_numpy()
            out.loc[ix, part + "_correction_supported"] = ok.to_numpy()
    out.to_parquet(OUT / "section_corrections.parquet", index=False)
    check_inputs()


def observed_history():
    h = pd.read_parquet(B.RECORDS).sort_values(["horse_id", "race_date"]).reset_index(drop=True)
    a = pd.read_parquet(P / "observations.parquet")
    a["race_key"] = a.source_key.str.replace("서울:", "1:", regex=False).str.replace(
        "부산:", "3:", regex=False
    )
    a["program_no"] = a.gate
    a["role"] = a.role4.where(a.group_observed & a.role4.ge(0))
    a["solo"] = a.role5.eq(0).astype(float).where(a.role.notna())
    for name, start, end, ok in [
        ("middle_gain", "s1f", "g3f", a.s1f_complete & a.g3f_complete),
        ("gain400", "g3f", "g1f", a.g3f_complete & a.g1f_complete),
    ]:
        a[name] = ((a[start] - a[end]) / (a.field_size - 1)).where(ok)
    a["gain200"] = (a.g1f_p - a.finish_p).where(a.g1f_complete & a.normal_outcome)
    for j in range(4):
        a["role" + str(j)] = a.role.eq(j).astype(float).where(a.role.notna())
    keep = [
        *PARTS,
        "role",
        "solo",
        "group_mean_relative",
        "middle_gain",
        "gain400",
        "gain200",
        "recovery",
        "fade",
        *["role" + str(j) for j in range(4)],
    ]
    corrections = pd.read_parquet(OUT / "section_corrections.parquet")
    a = a.merge(corrections.drop(columns="year"), on="row_key", how="left", validate="one_to_one")
    corrected = [c for c in a if c.endswith(("_adjusted", "_correction", "_correction_supported"))]
    h = h.merge(a[KEY + keep + corrected], on=KEY, how="left", validate="one_to_one")
    assert not h.duplicated(["horse_id", "race_date"]).any()
    return h, a


def slots(f, h):
    out = np.full((len(f), 5), -1, dtype=np.int32)
    dates = h.race_date.to_numpy("datetime64[D]")
    cutoff = f.cutoff_date.to_numpy("datetime64[D]")
    current = f.race_date.to_numpy("datetime64[D]")
    groups = h.groupby("horse_id", sort=False).indices
    for horse, ix in f.groupby("horse_id", sort=False).indices.items():
        history = groups.get(horse)
        if history is None:
            continue
        at = np.searchsorted(dates[history], cutoff[ix], side="right") - 1
        for lag in range(5):
            pos = at - lag
            valid = pos >= 0
            source = history[np.maximum(pos, 0)]
            valid &= (current[ix] - dates[source]).astype(int) <= 730
            out[ix[valid], lag] = source[valid]
    return out


def values(h, ix, col):
    v = h[col].to_numpy(float)
    result = v[np.maximum(ix, 0)]
    return np.where(ix >= 0, result, np.nan)


def average(v, window=5):
    v = v[:, :window]
    count = np.isfinite(v).sum(axis=1)
    return np.divide(np.nansum(v, axis=1), count, out=np.full(len(v), np.nan), where=count > 0)


def historical_features(f, h, ix, adjusted):
    out = {}
    for part in PARTS:
        col = part + "_adjusted" if adjusted else part
        # No correction or missing supporting model means original seconds retained.
        v = values(h, ix, col)
        if adjusted:
            raw = values(h, ix, part)
            v = np.where(np.isfinite(v), v, raw)
        out["section_" + part + "_last"] = v[:, 0]
        out["section_" + part + "_mean3"] = average(v, 3)
        count = np.isfinite(v).sum(axis=1)
        best = np.where(np.isfinite(v), v, np.inf).min(axis=1)
        out["section_" + part + "_best5"] = np.where(count > 0, best, np.nan)
        out["section_" + part + "_n5"] = count.astype(float)
    distance = values(h, ix, "result_distance")
    out["section_previous_distance"] = distance[:, 0]
    out["section_same_distance_n5"] = (
        (distance == f.distance_m.to_numpy()[:, None]).sum(axis=1).astype(float)
    )
    for j in range(4):
        out["style_role" + str(j) + "_rate5"] = average(values(h, ix, "role" + str(j)))
    out["style_role_n5"] = np.isfinite(values(h, ix, "role")).sum(axis=1).astype(float)
    for col in [
        "solo",
        "group_mean_relative",
        "middle_gain",
        "gain400",
        "gain200",
        "recovery",
        "fade",
    ]:
        v = values(h, ix, col)
        out["style_" + col + "_mean5"] = average(v)
        if col not in ["solo", "group_mean_relative"]:
            out["style_" + col + "_n5"] = np.isfinite(v).sum(axis=1).astype(float)
    return pd.DataFrame(out, index=f.index)


def field_features(f):
    out = pd.DataFrame(index=f.index)
    out["field_gate"] = f.program_no.astype(float)
    out["field_gate_relative"] = (f.program_no - 1) / (f.field_size - 1)
    cols = [
        "section_early_mean3",
        "section_last600_mean3",
        "section_late_mean3",
        "style_role0_rate5",
        "style_recovery_mean5",
    ]
    for c in cols:
        g = f.groupby("race_key")[c]
        count = g.transform("count") - f[c].notna().astype(int)
        total = g.transform("sum") - f[c].fillna(0)
        out["field_other_" + c] = total / count.replace(0, np.nan)
        out["field_support_" + c] = count / (f.field_size - 1)
        if c.startswith("section_"):
            out["field_gap_" + c] = f[c] - out["field_other_" + c]
    out["field_faster_early_n"] = np.nan
    out["field_early_pair_n"] = np.nan
    for ix in f.groupby("race_key", sort=False).indices.values():
        v = f.section_early_mean3.to_numpy()[ix]
        known = np.isfinite(v)
        faster = (v[None, :] < v[:, None]).sum(axis=1)
        out.loc[ix, "field_faster_early_n"] = np.where(known, faster, np.nan)
        out.loc[ix, "field_early_pair_n"] = np.where(known, known.sum() - 1, np.nan)
    return out


def prepare():
    if (OUT / "features_complete.json").exists():
        return
    environment()
    f = pd.read_parquet(W / "features_month_gate_weight22.parquet")
    h, observed = observed_history()
    ix = slots(f, h)
    raw = historical_features(f, h, ix, False)
    adjusted = historical_features(f, h, ix, True)
    sec = [c for c in raw if c.startswith("section_")]
    style = [c for c in raw if c.startswith("style_")]
    features = pd.concat([f, adjusted], axis=1)
    field = field_features(features)
    features = pd.concat([features, field], axis=1)
    for c in sec:
        features["raw_" + c] = raw[c]
    targets = observed[KEY + ["role", "recovery", "fade"]].rename(
        columns={"role": "aux_early", "recovery": "aux_recovery", "fade": "aux_fade"}
    )
    features = features.merge(targets, on=KEY, how="left", validate="one_to_one")
    assert len(features) == len(f) == 178497 and features[BASE].equals(f[BASE])
    contracts = dict(
        baseline22=BASE,
        raw_sections=BASE + ["raw_" + c for c in sec],
        adjusted_sections=BASE + sec,
        style_history=BASE + sec + style,
        field_context=BASE + sec + style + list(field),
    )
    for cols in contracts.values():
        assert len(cols) == len(set(cols)) and not any(
            "jockey" in c or "trainer" in c or c.startswith("aux_") for c in cols
        )
    h.to_parquet(OUT / "history_observations.parquet", index=False)
    np.save(OUT / "history_slots.npy", ix)
    features.to_parquet(OUT / "features.parquet", index=False)
    save(OUT / "feature_contract.json", contracts)
    coverage = []
    for (meet, year), g in features.groupby(["meet", "year"]):
        coverage.append(
            dict(
                meet=int(meet),
                year=int(year),
                rows=len(g),
                any_section=int(g.section_early_n5.gt(0).sum()),
                any_style=int(g.style_role_n5.gt(0).sum()),
                full_style5=int(g.style_role_n5.eq(5).sum()),
                any_recovery=int(g.style_recovery_n5.gt(0).sum()),
            )
        )
    pd.DataFrame(coverage).to_csv(OUT / "coverage.csv", index=False)
    save(
        OUT / "features_complete.json",
        dict(
            rows=len(f),
            history_rows=len(h),
            history_start=str(h.race_date.min().date()),
            source_sections_start=str(observed.date.min().date()),
            input_counts={k: len(v) for k, v in contracts.items()},
            hashes={
                p.name: sha(p)
                for p in [
                    OUT / "features.parquet",
                    OUT / "history_slots.npy",
                    OUT / "history_observations.parquet",
                ]
            },
        ),
    )
    print("Prepared", len(f), {k: len(v) for k, v in contracts.items()}, flush=True)


def encode(f, cols, mask):
    x = f[cols].copy()
    vocab = {}
    for col in cols:
        if not pd.api.types.is_numeric_dtype(x[col]):
            vocab[col] = sorted(f.loc[mask, col].dropna().unique().tolist())
            x[col] = pd.Categorical(x[col], categories=vocab[col])
    return x, vocab


def stack():
    if (OUT / "stack_complete.json").exists():
        return
    f = pd.read_parquet(OUT / "features.parquet")
    contracts = json.loads((OUT / "feature_contract.json").read_text())
    cols = contracts["field_context"]
    pcols = ["pace_p" + str(j) for j in range(4)] + ["pace_recovery", "pace_fade"]
    pred = pd.DataFrame(np.nan, index=f.index, columns=pcols)
    folder = OUT / "pace_models"
    folder.mkdir(exist_ok=True)
    for year in range(2020, 2027):
        train = f.year.between(2017, year - 1)
        x, vocab = encode(f, cols, train)
        for task in ["early", "recovery", "fade"]:
            path = folder / f"{year}_{task}.txt"
            mask = train & f["aux_" + task].notna()
            if path.exists():
                model = lgb.Booster(model_file=str(path))
            else:
                params = config()["training"].copy()
                params.pop("max_rounds")
                params.pop("early_stopping_rounds")
                params.update(
                    seed=42,
                    lambda_l2=10.0,
                    objective="multiclass" if task == "early" else "binary",
                    metric="multi_logloss" if task == "early" else "binary_logloss",
                )
                if task == "early":
                    params["num_class"] = 4
                model = lgb.train(
                    params,
                    lgb.Dataset(
                        x[mask],
                        label=f.loc[mask, "aux_" + task],
                        weight=1 / f.loc[mask, "field_size"],
                    ),
                    num_boost_round=180,
                )
                model.save_model(str(path))
                save(
                    path.with_suffix(".json"),
                    dict(
                        year=year,
                        task=task,
                        features=cols,
                        category_vocabulary=vocab,
                        train_end=str(f.loc[mask, "race_date"].max().date()),
                        training_rows=int(mask.sum()),
                        model_sha256=sha(path),
                    ),
                )
            test = f.year.eq(year)
            probability = model.predict(x[test], num_threads=4)
            pred.loc[
                test, ["pace_p" + str(j) for j in range(4)] if task == "early" else ["pace_" + task]
            ] = probability if task == "early" else probability[:, None]
            print("Pace OOF", year, task, int(mask.sum()), flush=True)
    pred["pace_supported"] = pred.pace_p0.notna().astype(float)
    contracts["pace_stack"] = cols + list(pred)
    pd.concat([f, pred], axis=1).to_parquet(OUT / "stack_features.parquet", index=False)
    save(OUT / "stack_feature_contract.json", contracts)
    save(
        OUT / "stack_complete.json",
        dict(
            rows=len(f),
            first_predicted_year=2020,
            annual_prior_only=True,
            features_sha256=sha(OUT / "stack_features.parquet"),
        ),
    )


@lru_cache(maxsize=32)
def support(n, target):
    sets = np.array(list(itertools.combinations(range(n), target)), int)
    incidence = np.zeros((len(sets), n))
    incidence[np.repeat(np.arange(len(sets)), target), sets.ravel()] = 1
    return sets, incidence


def energies(f, score, target):
    rows = []
    for rid, ix in f.groupby("race_key", sort=False).indices.items():
        g = f.iloc[ix]
        sets, inc = support(len(g), target)
        truth = tuple(np.flatnonzero(g.outcome.between(1, target).to_numpy()))
        assert len(truth) == target
        index = next(j for j, s in enumerate(sets) if tuple(s) == truth)
        rows.append(
            dict(
                race_key=rid,
                idx=ix,
                energy=np.sort(score[ix][sets], axis=1).sum(axis=1),
                truth=index,
            )
        )
    return rows


def temperature(f, score, target):
    r = energies(f, score, target)
    width = max(len(x["energy"]) for x in r)
    matrix = np.full((len(r), width), -np.inf)
    truth = np.empty(len(r))
    for i, x in enumerate(r):
        matrix[i, : len(x["energy"])] = x["energy"]
        truth[i] = x["energy"][x["truth"]]
    result = minimize_scalar(
        lambda t: float(np.mean(logsumexp(matrix / t, axis=1) - truth / t)),
        bounds=config()["temperature_bounds"],
        method="bounded",
    )
    assert result.success
    return float(result.x)


def rank_metrics(outcomes):
    winner2 = set(np.flatnonzero((outcomes >= 1) & (outcomes <= 2)))
    assert len(winner2) == 2
    return dict(
        quinella_one=int(winner2 == {0, 1}),
        axis_top2=int(1 <= outcomes[0] <= 2),
        axis_top3=int(1 <= outcomes[0] <= 3),
        axis_win=int(outcomes[0] == 1),
        axis_next3=int(0 in winner2 and winner2 <= set(range(4))),
        quinella_box4=int(winner2 <= set(range(4))),
    )


def evaluate(f, score, temp, target, variant):
    races = []
    runners = []
    for p in energies(f, score, target):
        g = f.iloc[p["idx"]]
        sets, incidence = support(len(g), target)
        q = np.exp(p["energy"] / temp - logsumexp(p["energy"] / temp))
        marginal = q @ incidence
        order = np.argsort(-score[p["idx"]], kind="stable")
        assert g.program_no.is_monotonic_increasing
        actual = g.outcome.between(1, target).to_numpy(float)
        row = dict(
            race_key=p["race_key"],
            race_date=str(g.race_date.iloc[0].date()),
            meet=int(g.meet.iloc[0]),
            year=int(g.year.iloc[0]),
            target=target,
            variant=variant,
            field_size=len(g),
            distance_m=float(g.distance_m.iloc[0]),
            grade=float(g.grade.iloc[0]) if pd.notna(g.grade.iloc[0]) else None,
            minimum_history=float(g.history_count.min()),
            style_supported_fraction=float(g.style_role_n5.gt(0).mean()),
            target_brier=float(np.mean((marginal - actual) ** 2)),
            set_logloss=float(-np.log(q[p["truth"]])),
            probability_sum_error=float(abs(marginal.sum() - target)),
        )
        row.update(rank_metrics(g.outcome.to_numpy()[order]))
        races.append(row)
        for j, r in enumerate(g.itertuples()):
            runners.append(
                dict(
                    race_key=r.race_key,
                    program_no=int(r.program_no),
                    horse_id=r.horse_id,
                    meet=int(r.meet),
                    race_date=str(r.race_date.date()),
                    year=int(r.year),
                    target=target,
                    variant=variant,
                    outcome=int(r.outcome),
                    raw_score=float(score[p["idx"][j]]),
                    target_probability=float(marginal[j]),
                )
            )
    return pd.DataFrame(races), pd.DataFrame(runners)


def fit(f, cols, year, target, variant, folder):
    train = f.year.between(2017, year - 3)
    valid = f.year.eq(year - 2)
    cal = f.year.eq(year - 1)
    test = f.year.eq(year)
    x, vocab = encode(f, cols, train)
    params = config()["training"].copy()
    rounds = params.pop("max_rounds")
    early = params.pop("early_stopping_rounds")
    params["seed"] = config()["seed"]
    y = f.outcome.between(1, target).astype(int)

    def dataset(mask):
        return lgb.Dataset(
            x[mask], label=y[mask], weight=1 / f.loc[mask, "field_size"], free_raw_data=False
        )

    if variant == "baseline22" and target == 3:
        old = W / "models" / f"{int(f.meet.iloc[0])}_{year}_month_gate_weight22"
        model = lgb.Booster(model_file=str(old / "top3.txt"))
        meta = json.loads((old / "metadata.json").read_text())
        assert meta["features"] == cols and meta["category_vocabulary"] == vocab
        meta = meta | dict(reused_frozen_model=True)
    else:
        initial = lgb.train(
            params,
            dataset(train),
            num_boost_round=rounds,
            valid_sets=[dataset(valid)],
            callbacks=[lgb.early_stopping(early, verbose=False)],
        )
        model = lgb.train(params, dataset(train | valid), num_boost_round=initial.best_iteration)
        model.save_model(str(folder / "model.txt"))
        meta = dict(
            features=cols,
            category_vocabulary=vocab,
            trees=int(initial.best_iteration),
            train_end=str(f.loc[train | valid, "race_date"].max().date()),
            model_sha256=sha(folder / "model.txt"),
            gain=dict(
                zip(
                    cols,
                    model.feature_importance(importance_type="gain").astype(float),
                    strict=True,
                )
            ),
        )
    cs = model.predict(x[cal], raw_score=True, num_threads=4)
    score = model.predict(x[test], raw_score=True, num_threads=4)
    temp = temperature(f[cal].reset_index(drop=True), cs, target)
    meta.update(
        target=target,
        variant=variant,
        evaluation_year=year,
        validation_year=year - 2,
        calibration_year=year - 1,
        temperature=temp,
        training_min="2017-01-01",
    )
    save(folder / "metadata.json", meta)
    return evaluate(f[test].reset_index(drop=True), score, temp, target, variant)


def train():
    f = pd.read_parquet(OUT / "stack_features.parquet")
    contracts = json.loads((OUT / "stack_feature_contract.json").read_text())
    for target in config()["targets"]:
        for variant in config()["variants"]:
            for meet in config()["venues"]:
                one = f[f.meet.eq(meet)].reset_index(drop=True)
                for year in config()["evaluation_years"]:
                    folder = OUT / "finish_models" / f"{target}_{variant}_{meet}_{year}"
                    if (folder / "races.csv").exists():
                        continue
                    folder.mkdir(parents=True, exist_ok=True)
                    races, runners = fit(one, contracts[variant], year, target, variant, folder)
                    runners.to_parquet(folder / "runners.parquet", index=False)
                    races.to_csv(folder / "races.csv", index=False)
                    print(
                        "Finish",
                        target,
                        variant,
                        meet,
                        year,
                        "axis2",
                        int(races.axis_top2.sum()),
                        "quinella",
                        int(races.quinella_one.sum()),
                        flush=True,
                    )
    folders = sorted((OUT / "finish_models").iterdir())
    pd.concat([pd.read_csv(p / "races.csv") for p in folders], ignore_index=True).to_csv(
        OUT / "race_metrics.csv", index=False
    )
    pd.concat(
        [pd.read_parquet(p / "runners.parquet") for p in folders], ignore_index=True
    ).to_parquet(OUT / "runner_predictions.parquet", index=False)
    check_inputs()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "stack", "train"])
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        freeze()
        {"prepare": prepare, "stack": stack, "train": train}[args.stage]()


if __name__ == "__main__":
    main()
