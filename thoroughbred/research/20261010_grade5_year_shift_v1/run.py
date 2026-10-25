"""Year/cohort diagnosis; do not infer a causal regime change from 56 races."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit, logit

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = R.parent.parent
OUT = HERE / "outputs"
PREV = R / "20261010_axis_single_signal_ablation_v1"
spec = importlib.util.spec_from_file_location("frozen_ablation40", PREV / "run.py")
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
e = a.e
sha, save = a.sha, a.save
B, SEED = 2000, 411010
NUMERIC = [
    "axis_probability",
    "axis_distance_m",
    "field_size",
    "axis_history_count",
    "axis_days_since_last",
    "axis_previous_age",
    "axis_current_carried_weight",
    "axis_current_vs_previous_carried_weight",
    "axis_moist_last_record_index",
    "axis_moist_last3_record_index_mean",
    "axis_moist_last5_record_index_best",
    "axis_profile_trend",
    "axis_profile_std5",
    "axis_gap_moist_last3_record_index_mean",
    "axis_gap_section_early_mean3",
    "axis_gap_section_last600_mean3",
    "axis_gap_section_late_mean3",
    "axis_section_same_distance_n5",
    "gap12",
    "axis_section_early_n5",
    "axis_profile_count3",
]
CAT = [
    "meet_band",
    "prob_band",
    "distance_band",
    "field_band",
    "season",
    "age_band",
    "sex",
    "history_band",
    "rest_band",
    "score_gap_band",
    "relative_record_band",
    "form_down",
    "early_slow",
    "distance_up",
    "new_distance",
    "weight_up",
    "front_axis",
    "fade",
]


def check():
    a.check()
    for name, value in json.loads((OUT / "source_lock.json").read_text()).items():
        assert sha(ROOT / name) == value, name


def category(s, bins, labels):
    return pd.cut(s, bins, labels=labels, include_lowest=True).astype("string").fillna("unknown")


def load():
    d = pd.read_parquet(a.PRIOR / "outputs/race_inputs.parquet").query("year>=2024").copy()
    p = pd.read_parquet(PREV / "outputs/risk_predictions.parquet").query(
        "variant=='grade5_local_raw'"
    )
    d = d.merge(
        p[["race_key", "risk"]].rename(columns={"risk": "corrected_risk"}),
        on="race_key",
        validate="one_to_one",
    )
    d["axis_probability"] = 1 - d.base_risk
    d["residual"] = d.collapsed - d.base_risk
    d["correction"] = d.corrected_risk - d.base_risk
    d["brier_delta"] = (d.corrected_risk - d.collapsed) ** 2 - (d.base_risk - d.collapsed) ** 2
    d["time"] = np.where(d.year.eq(2026), "2026", "2024_25")
    d["calendar_matched"] = d.race_date.dt.month * 100 + d.race_date.dt.day <= 920
    d["target"] = d.high_probability_grade5.eq(1)
    d["high_other"] = d.axis_probability.ge(0.7) & ~d.axis_grade.eq(5) & d.axis_grade.notna()
    d["meet_band"] = d.meet.astype(str)
    d["prob_band"] = category(d.axis_probability, [0.7, 0.75, 0.8, 1], ["70_75", "75_80", "80plus"])
    d["distance_band"] = category(
        d.axis_distance_m, [0, 1300, 1600, 10000], ["short", "middle", "long"]
    )
    d["field_band"] = category(d.field_size, [0, 9, 11, 100], ["<=9", "10_11", ">=12"])
    d["season"] = ((d.race_date.dt.month - 1) // 3 + 1).astype(str)
    d["age_band"] = category(d.axis_previous_age, [0, 3, 4, 100], ["<=3", "4", ">=5"])
    d["sex"] = d.axis_previous_sex.astype("string").fillna("unknown")
    d["history_band"] = category(d.axis_history_count, [-1, 3, 6, 1000], ["<=3", "4_6", ">=7"])
    d["rest_band"] = category(d.axis_days_since_last, [0, 35, 55, 10000], ["<=35", "36_55", ">=56"])
    d["score_gap_band"] = category(d.gap12, [-1, 0.3, 0.6, 100], ["<=.3", ".3_.6", ">.6"])
    d["relative_record_band"] = category(
        d.axis_gap_moist_last3_record_index_mean, [-np.inf, 0, 0.5, np.inf], ["<=0", "0_.5", ">.5"]
    )

    def binary(s, mask, support=None):
        valid = s.notna() if support is None else s.notna() & support
        return pd.Series(np.where(valid, np.where(mask, "yes", "no"), "unknown"), index=d.index)

    d["form_down"] = binary(d.axis_profile_trend, d.axis_profile_trend.le(-0.5))
    d["early_slow"] = binary(d.axis_gap_section_early_mean3, d.axis_gap_section_early_mean3.ge(0))
    delta = d.axis_distance_m - d.axis_section_previous_distance
    d["distance_up"] = binary(delta, delta.ge(200))
    d["new_distance"] = binary(
        d.axis_section_same_distance_n5,
        d.axis_section_same_distance_n5.eq(0),
        d.axis_section_early_n5.ge(3),
    )
    d["weight_up"] = binary(
        d.axis_current_vs_previous_carried_weight, d.axis_current_vs_previous_carried_weight.ge(2)
    )
    d["front_axis"] = binary(
        d.axis_style_role0_rate5, d.axis_style_role0_rate5.ge(0.6), d.axis_style_role_n5.ge(3)
    )
    d["fade"] = binary(
        d.axis_style_fade_mean5, d.axis_style_fade_mean5.ge(0.4), d.axis_style_fade_n5.ge(3)
    )
    return d


def scopes(d):
    yield "full", d
    yield "calendar_matched", d[d.calendar_matched]


def draws(d, columns):
    dates = sorted(d.race_date.unique())
    rng = np.random.default_rng(SEED)
    w = rng.multinomial(len(dates), np.full(len(dates), 1 / len(dates)), B)
    result = {}
    for col in columns:
        g = d.groupby("race_date")[col].agg(["sum", "count"]).reindex(dates, fill_value=0)
        den = w @ g["count"].to_numpy(dtype=float)
        result[col] = np.divide(
            w @ g["sum"].to_numpy(dtype=float), den, out=np.full(B, np.nan), where=den > 0
        )
    return result


def bounds(v):
    v = v[np.isfinite(v)]
    return [float(x) for x in np.quantile(v, [0.025, 0.975])] if len(v) >= 1900 else [None, None]


def describe(g):
    boot = draws(g, ["collapsed", "residual", "brier_delta"])
    row = dict(
        n=len(g),
        failures=int(g.collapsed.sum()),
        unique_horses=g.axis_horse_id.nunique(),
        dates=g.race_date.nunique(),
        mean_axis_probability=float(g.axis_probability.mean()),
        observed_axis_top3=float(1 - g.collapsed.mean()),
        mean_raw_risk=float(g.base_risk.mean()),
        mean_corrected_risk=float(g.corrected_risk.mean()),
        mean_correction=float(g.correction.mean()),
        residual=float(g.residual.mean()),
        brier_delta=float(g.brier_delta.mean()),
    )
    for name, values in boot.items():
        row[name + "_low"], row[name + "_high"] = bounds(values)
    return row


def standardize(d, keys, minold, minnew):
    old, new = d[d.time.eq("2024_25")], d[d.time.eq("2026")]
    cells = []
    for key, g in d.groupby(keys, observed=True, dropna=False):
        o, n = g[g.time.eq("2024_25")], g[g.time.eq("2026")]
        if len(o) >= minold and len(n) >= minnew:
            cells.append(
                dict(
                    cell=str(key),
                    old_n=len(o),
                    new_n=len(n),
                    old_risk=float(o.collapsed.mean()),
                    new_risk=float(n.collapsed.mean()),
                    old_residual=float(o.residual.mean()),
                    new_residual=float(n.residual.mean()),
                )
            )
    if not cells:
        return dict(cells=0, old_n=0, new_n=0, old_coverage=0, new_coverage=0), cells
    c = pd.DataFrame(cells)
    row = dict(
        cells=len(c),
        old_n=int(c.old_n.sum()),
        new_n=int(c.new_n.sum()),
        old_coverage=float(c.old_n.sum() / len(old)),
        new_coverage=float(c.new_n.sum() / len(new)),
    )
    for metric in ["risk", "residual"]:
        old_mean = float(np.average(c["old_" + metric], weights=c.old_n))
        new_mean = float(np.average(c["new_" + metric], weights=c.new_n))
        standardized = float(np.average(c["old_" + metric], weights=c.new_n))
        row.update(
            {
                "old_" + metric: old_mean,
                "new_" + metric: new_mean,
                "standardized_old_" + metric: standardized,
                "composition_" + metric: standardized - old_mean,
                "within_" + metric: new_mean - standardized,
                "total_" + metric: new_mean - old_mean,
            }
        )
    return row, cells


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    assert not (OUT / "source_lock.json").exists()
    meta = [
        R
        / "20261008_profile_carried_weight_v1/outputs/models"
        / f"{m}_{y}_month_gate_weight22/metadata.json"
        for m in [1, 3]
        for y in [2024, 2025, 2026]
    ]
    paths = [
        HERE / "PLAN.md",
        HERE / "run.py",
        HERE / "verify.py",
        PREV / "run.py",
        PREV / "outputs/risk_predictions.parquet",
        PREV / "outputs/verification.json",
        PREV / "outputs/models/grade5_local_raw_2025.json",
        PREV / "outputs/models/grade5_local_raw_2026.json",
        a.PRIOR / "outputs/race_inputs.parquet",
        e.REGISTRY,
        e.BASE,
    ] + meta
    save(OUT / "source_lock.json", {str(p.relative_to(ROOT)): sha(p) for p in paths})
    d = load()
    d.to_parquet(OUT / "races.parquet", index=False)
    summaries, comparisons, numeric, categorical, standardized, cellrows, controls = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )
    for scope, frame in scopes(d):
        target = frame[frame.target]
        for tag, g in [(str(y), target[target.year.eq(y)]) for y in [2024, 2025, 2026]] + [
            ("2024_25", target[target.time.eq("2024_25")])
        ]:
            summaries.append(dict(scope=scope, period=tag, **describe(g)))
        old, new = target[target.time.eq("2024_25")], target[target.time.eq("2026")]
        bo, bn = (
            draws(old, ["collapsed", "residual", *NUMERIC]),
            draws(new, ["collapsed", "residual", *NUMERIC]),
        )
        for metric in ["collapsed", "residual"]:
            lo, hi = bounds(bn[metric] - bo[metric])
            comparisons.append(
                dict(
                    scope=scope,
                    metric=metric,
                    old_n=len(old),
                    new_n=len(new),
                    difference=float(new[metric].mean() - old[metric].mean()),
                    low=lo,
                    high=hi,
                )
            )
        for col in NUMERIC:
            o, n = old[col].dropna(), new[col].dropna()
            denom = np.sqrt((o.var() + n.var()) / 2)
            lo, hi = bounds(bn[col] - bo[col])
            numeric.append(
                dict(
                    scope=scope,
                    feature=col,
                    old_n=len(o),
                    new_n=len(n),
                    old_missing=int(old[col].isna().sum()),
                    new_missing=int(new[col].isna().sum()),
                    old_mean=float(o.mean()),
                    new_mean=float(n.mean()),
                    old_median=float(o.median()),
                    new_median=float(n.median()),
                    difference=float(n.mean() - o.mean()),
                    smd=float((n.mean() - o.mean()) / denom) if denom > 0 else None,
                    low=lo,
                    high=hi,
                )
            )
        for col in CAT:
            for level, g in target.groupby(col, observed=True, dropna=False):
                o, n = g[g.time.eq("2024_25")], g[g.time.eq("2026")]
                categorical.append(
                    dict(
                        scope=scope,
                        feature=col,
                        level=str(level),
                        old_n=len(o),
                        new_n=len(n),
                        old_share=float(len(o) / len(old)),
                        new_share=float(len(n) / len(new)),
                        share_difference=float(len(n) / len(new) - len(o) / len(old)),
                        old_failure_rate=float(o.collapsed.mean()) if len(o) else None,
                        new_failure_rate=float(n.collapsed.mean()) if len(n) else None,
                        old_residual=float(o.residual.mean()) if len(o) else None,
                        new_residual=float(n.residual.mean()) if len(n) else None,
                    )
                )
        schemes = [(col, [col], 5, 3) for col in CAT] + [
            ("region_probability", ["meet_band", "prob_band"], 5, 3),
            ("region_season", ["meet_band", "season"], 5, 3),
            ("joint_context", ["meet_band", "prob_band", "distance_band", "field_band"], 3, 2),
        ]
        for name, keys, mo, mn in schemes:
            row, cells = standardize(target, keys, mo, mn)
            standardized.append(dict(scope=scope, scheme=name, **row))
            cellrows.extend(dict(scope=scope, scheme=name, **row) for row in cells)
        for group, mask in [
            ("target", frame.target),
            ("high_other", frame.high_other),
            ("all_axes", pd.Series(True, index=frame.index)),
        ]:
            g = frame[mask]
            for time, h in g.groupby("time"):
                controls.append(dict(scope=scope, group=group, time=time, **describe(h)))
        # Date-cluster DID: retain target/control contemporaneous covariance.
        periods_boot = []
        for time in ["2024_25", "2026"]:
            f = frame[frame.time.eq(time)]
            dates = sorted(f.race_date.unique())
            rng = np.random.default_rng(SEED)
            w = rng.multinomial(len(dates), np.full(len(dates), 1 / len(dates)), B)
            vals = []
            for mask in [f.target, f.high_other]:
                g = (
                    f[mask]
                    .groupby("race_date")
                    .residual.agg(["sum", "count"])
                    .reindex(dates, fill_value=0)
                )
                den = w @ g["count"].to_numpy(dtype=float)
                vals.append(
                    np.divide(w @ g["sum"].to_numpy(), den, out=np.full(B, np.nan), where=den > 0)
                )
            periods_boot.append(vals[0] - vals[1])
        lookup = {(r["group"], r["time"]): r for r in controls if r["scope"] == scope}
        point = (
            lookup["target", "2026"]["residual"] - lookup["high_other", "2026"]["residual"]
        ) - (lookup["target", "2024_25"]["residual"] - lookup["high_other", "2024_25"]["residual"])
        lo, hi = bounds(periods_boot[1] - periods_boot[0])
        comparisons.append(
            dict(
                scope=scope,
                metric="target_minus_high_other_residual_DID",
                old_n=len(old),
                new_n=len(new),
                difference=float(point),
                low=lo,
                high=hi,
            )
        )
    # Quantify whether the new coefficient, versus an older coefficient, caused the overshoot.
    new = d[d.target & d.year.eq(2026)].copy()
    cf = []
    for version in ["raw", "2025_coefficient", "2026_coefficient"]:
        beta = (
            0
            if version == "raw"
            else json.loads(
                (PREV / f"outputs/models/grade5_local_raw_{version[:4]}.json").read_text()
            )["coefficients"][0]
        )
        q = new.base_risk.to_numpy() if beta == 0 else expit(logit(new.base_risk.to_numpy()) + beta)
        cf.append(
            dict(
                version=version,
                beta=float(beta),
                n=len(new),
                mean_risk=float(q.mean()),
                observed_risk=float(new.collapsed.mean()),
                overshoot=float(q.mean() - new.collapsed.mean()),
                brier=float(np.mean((q - new.collapsed.to_numpy()) ** 2)),
            )
        )
    # Sensitivity, not an alteration of any actual outcome.
    y, delta = new.collapsed.to_numpy(), new.correction.to_numpy()
    total = float(new.brier_delta.sum())
    influence = np.sort((2 * delta)[y == 0])[::-1]
    needed = int(np.searchsorted(np.cumsum(influence), total) + 1)
    save(
        OUT / "sensitivity.json",
        dict(
            status="illustrative_not_modified_outcomes",
            new_races=len(new),
            actual_failures=int(y.sum()),
            expected_failures_raw=float(new.base_risk.sum()),
            expected_failures_corrected=float(new.corrected_risk.sum()),
            minimum_additional_failure_outcomes_to_reverse_brier_delta=needed,
            actual_results_unchanged=True,
        ),
    )
    modelmeta = []
    for path in meta:
        v = json.loads(path.read_text())
        modelmeta.append(
            dict(
                meet=int(path.parent.name.split("_")[0]),
                year=v["evaluation_year"],
                training_min=v["training_min"],
                train_end=v["train_end"],
                calibration_year=v["calibration_year"],
                temperature=v["temperature"],
                trees=v["trees"],
                source_path=str(path.relative_to(ROOT)),
            )
        )
    for name, data in [
        ("summary", summaries),
        ("year_differences", comparisons),
        ("numeric_shift", numeric),
        ("categorical_shift", categorical),
        ("standardized", standardized),
        ("standardization_cells", cellrows),
        ("controls", controls),
        ("coefficient_counterfactual", cf),
        ("base_model_metadata", modelmeta),
    ]:
        pd.DataFrame(data).to_csv(OUT / f"{name}.csv", index=False)
    save(
        OUT / "cohort.json",
        dict(
            target_races=int(d.target.sum()),
            by_year={str(y): int(n) for y, n in d[d.target].groupby("year").size().items()},
            all_axes=len(d),
            numeric_features=len(NUMERIC),
            categorical_features=len(CAT),
            bootstrap=B,
            seed=SEED,
            new_models=0,
        ),
    )
    check()
    print(pd.DataFrame(summaries).to_string(index=False), flush=True)
    print(pd.DataFrame(comparisons).to_string(index=False), flush=True)
    print(
        pd.DataFrame(numeric)
        .query("scope=='calendar_matched'")
        .sort_values("smd", key=lambda s: s.abs(), ascending=False)
        .head(10)
        .to_string(index=False),
        flush=True,
    )
    print(
        pd.DataFrame(standardized)
        .query(
            "scope=='calendar_matched' and scheme in "
            "['meet_band','region_probability','region_season','joint_context']"
        )
        .to_string(index=False),
        flush=True,
    )


if __name__ == "__main__":
    main()
