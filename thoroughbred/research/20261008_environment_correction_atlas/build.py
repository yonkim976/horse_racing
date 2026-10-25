"""Compose reviewed correction factors without lateral terms or production changes."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
SECTION = HERE.parent / "20261008_section_normalization_candidate_v1"
WHOLE = HERE.parent / "20261008_gate_model_candidate_v1"
SPEC = importlib.util.spec_from_file_location("atlas_analysis", HERE / "analyze.py")
E = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E)
KEYS = ["meet", "distance_m", "field_size", "mode", "block", "band", "period", "level", "month"]
PARTS = ["finish", "early", "last600", "late", "middle1", "middle2"]
THRESHOLDS = {
    "finish": (0.05, 0.20),
    "early": (0.01, 0.04),
    "last600": (0.02, 0.08),
    "late": (0.01, 0.04),
}


def symbols(values, part):
    values = np.asarray(values, float)
    if part not in THRESHOLDS:
        return np.where(
            np.isfinite(values), np.where(values > 0, "+", np.where(values < 0, "-", "0")), "?"
        )
    small, large = THRESHOLDS.get(part, (0, np.inf))
    result = np.where(
        values >= large,
        "++",
        np.where(
            values <= -large,
            "--",
            np.where(values >= small, "+", np.where(values <= -small, "-", "0")),
        ),
    )
    return np.where(np.isfinite(values), result, "?")


def factors():
    sec = pd.read_csv(SECTION / "outputs/section_moisture_reference.csv")
    moist = sec[
        ["meet", "distance_m", "section", "band", "supported", "effect", "moisture_add_seconds"]
    ].rename(columns={"section": "target", "effect": "observed_reference_effect"})
    moist["adopted_moisture"] = False
    whole = pd.read_csv(WHOLE / "outputs/moisture_reference.csv")
    whole["target"] = "finish"
    whole["moisture_add_seconds"] = whole.add_seconds_conservative.where(whole.supported)
    whole["observed_reference_effect"] = whole.effect
    whole["adopted_moisture"] = whole.adopted_supported
    moist = pd.concat([moist, whole[moist.columns]], ignore_index=True)
    moist = moist.rename(columns={"supported": "moisture_available"})
    moist.to_csv(OUT / "moisture_components.csv", index=False)
    gates = pd.read_csv(SECTION / "outputs/section_gate_lookup.csv", dtype={"level": str}).rename(
        columns={"section": "target"}
    )
    other = pd.read_csv(WHOLE / "outputs/gate_correction_lookup.csv", dtype={"level": str})
    other["target"] = "finish"
    gates = pd.concat([gates, other], ignore_index=True)
    keep = KEYS[:-1] + [
        "target",
        "base_available",
        "state_available",
        "status",
        "base_n",
        "state_n",
        "base_add_seconds",
        "state_add_seconds",
        "gate_add_seconds",
    ]
    gates = gates[keep].rename(
        columns={"status": "gate_status", "base_available": "gate_available"}
    )
    gates.to_parquet(OUT / "gate_components.parquet", index=False)
    month = pd.read_csv(SECTION / "outputs/section_month_lookup.csv").rename(
        columns={"section": "target", "available": "month_available"}
    )
    month["source"] = "section_v1_preserved"
    month = month[
        [
            "meet",
            "distance_m",
            "target",
            "period",
            "month",
            "month_add_seconds",
            "month_available",
            "source",
        ]
    ]
    existing = pd.read_csv(WHOLE / "outputs/month_candidate_reference.csv")
    joint = pd.read_csv(OUT / "joint_sensitivity_profiles.csv", dtype={"level": str})
    extra = []
    for (meet, dist, period), g in joint[
        joint.family.eq("month") & joint.section.eq("finish") & joint.variant.eq("baseline")
    ].groupby(["meet", "distance_m", "period"], observed=True):
        g = g.assign(month=g.level.astype(int)).sort_values("month")
        available = len(g) == 12 and g.estimable.all()
        counts = np.array([json.loads(s)[0]["rows"] for s in g.support])
        raw = (
            0.30 * counts / (counts + 100) * g.effect_seconds.to_numpy()
            if available
            else np.zeros(len(g))
        )
        centered = raw - raw.mean()
        add = -centered * min(1, 0.12 / max(abs(centered).max(), 1e-15))
        for i, row in enumerate(g.itertuples()):
            old = existing[
                existing.meet.eq(meet) & existing.distance_m.eq(dist) & existing.month.eq(row.month)
            ]
            preserve = period == "all_mad4" and len(old) == 1
            extra.append(
                dict(
                    meet=meet,
                    distance_m=int(dist),
                    target="finish",
                    period=period,
                    month=row.month,
                    month_add_seconds=float(old.iloc[0].month_candidate_add)
                    if preserve
                    else float(add[i]),
                    month_available=bool(preserve or available),
                    source="whole_v1_preserved" if preserve else "joint_curve_exploratory_fill",
                )
            )
    month = pd.concat([month, pd.DataFrame(extra)], ignore_index=True)
    month.to_csv(OUT / "month_components.csv", index=False)
    return moist, gates, month


def compose(moist, gates, month):
    cube = gates.merge(pd.DataFrame(dict(month=range(1, 13))), how="cross")
    cube = cube.merge(
        moist, on=["meet", "distance_m", "target", "band"], how="left", validate="many_to_one"
    )
    cube = cube.merge(
        month,
        on=["meet", "distance_m", "target", "period", "month"],
        how="left",
        validate="many_to_one",
    )
    for name in ["moisture_available", "month_available", "gate_available"]:
        cube[name] = cube[name].fillna(False).astype(bool)
    cube["complete"] = cube.moisture_available & cube.month_available & cube.gate_available
    components = ["moisture_add_seconds", "month_add_seconds", "gate_add_seconds"]
    cube["partial_add_seconds"] = cube[components].fillna(0).sum(axis=1)
    cube["total_add_seconds"] = cube.partial_add_seconds.where(cube.complete)
    cube["method"] = "direct_target"
    cube["source"] = cube.source.fillna("month_unavailable")
    indexed = cube.set_index(KEYS + ["target"], verify_integrity=True)
    derived = []
    for target, operands in [
        ("middle1", ["finish", "early", "last600"]),
        ("middle2", ["last600", "late"]),
    ]:
        parts = [indexed.xs(p, level="target") for p in operands]
        z = parts[0].copy()
        for name in components + ["total_add_seconds", "partial_add_seconds"]:
            z[name] = parts[0][name] - sum(p[name] for p in parts[1:])
        for name in ["complete", "moisture_available", "month_available", "gate_available"]:
            z[name] = np.logical_and.reduce([p[name] for p in parts])
        z["adopted_moisture"] = False
        z["observed_reference_effect"] = np.nan
        z["source"] = "identity_residual"
        z["method"] = "identity_residual"
        z["target"] = target
        derived.append(z.reset_index())
    cube = pd.concat([cube, *derived], ignore_index=True)
    cube["symbol"] = "?"
    for target, ix in cube.groupby("target", observed=True).groups.items():
        cube.loc[ix, "symbol"] = symbols(cube.loc[ix, "total_add_seconds"], target)
    cube.to_parquet(OUT / "combined_correction_lookup.parquet", index=False)
    return cube


def ledger(cube):
    population, _ = E.A.load()
    flags = pd.read_parquet(
        E.TAIL / "outputs/runner_tail_flags.parquet", columns=["row_key", "tail25"]
    )
    mask = pd.read_parquet(E.L.LEDGER, columns=["row_key", "mad4_keep"])
    population = population.merge(flags, on="row_key", validate="one_to_one").merge(
        mask, on="row_key", how="left", validate="one_to_one"
    )
    population["mad4_keep"] = population.mad4_keep.fillna(False).astype(bool)
    base = population[
        [
            "row_key",
            "race_key",
            "date",
            "year",
            "meet",
            "distance_m",
            "n",
            "horse_number",
            "gate_side",
            "gate_block",
            "band",
            "month",
            "mad4_keep",
            "tail25",
            *PARTS,
        ]
    ].copy()
    base["field_size"] = base.n
    base["mode"] = np.where(base.gate_block.str.startswith("exact"), "number", "group")
    base["block"] = base.gate_block
    base["level"] = np.where(
        base["mode"].eq("number"), base.horse_number.astype(str), base.gate_side
    )
    frames = []
    for period in E.PERIODS:
        d = base.copy() if period == "all_mad4" else base[base.year.ge(2024)].copy()
        d["period"] = period
        for part in PARTS:
            slim = cube[cube.target.eq(part)][
                KEYS
                + [
                    "moisture_add_seconds",
                    "month_add_seconds",
                    "gate_add_seconds",
                    "total_add_seconds",
                    "symbol",
                    "complete",
                ]
            ].rename(
                columns={
                    name: f"{part}_{name}"
                    for name in [
                        "moisture_add_seconds",
                        "month_add_seconds",
                        "gate_add_seconds",
                        "total_add_seconds",
                        "symbol",
                        "complete",
                    ]
                }
            )
            d = d.merge(slim, on=KEYS, how="left", validate="many_to_one")
            d[f"{part}_candidate"] = d[part] + d[f"{part}_total_add_seconds"]
            d[f"{part}_symbol"] = d[f"{part}_symbol"].fillna("?")
            d[f"{part}_complete"] = d[f"{part}_complete"].fillna(False).astype(bool)
        frames.append(d)
    result = pd.concat(frames, ignore_index=True)
    result.to_parquet(OUT / "runner_combined_candidates.parquet", index=False)
    return result


def wquantile(values, weights, quantile):
    order = np.argsort(values)
    return float(np.interp(quantile, np.cumsum(weights[order]) / weights.sum(), values[order]))


def summarize(ledger_frame, grain):
    results = []
    for cohort in ["baseline", "tail25"]:
        d = ledger_frame[
            ledger_frame.mad4_keep & (~ledger_frame.tail25 if cohort == "tail25" else True)
        ].copy()
        keys = ["meet", "distance_m", "period", "band"]
        if grain == "overall":
            keys.remove("band")
        elif grain != "condition":
            d = d[d.period.eq("all_mad4")].copy()
            d["quarter"] = d.date.dt.to_period("Q").astype(str)
            keys.append(grain)
        for key, g in d.groupby(keys, observed=True):
            for part in PARTS:
                s = g[g[f"{part}_complete"]]
                item = dict(zip(keys, key, strict=True)) | dict(
                    cohort=cohort,
                    target=part,
                    rows=len(g),
                    available_rows=len(s),
                    races=int(g.race_key.nunique()),
                    available_races=int(s.race_key.nunique()),
                    method="fixed_lookup_exposure_summary",
                )
                if len(s):
                    values = s[f"{part}_total_add_seconds"].to_numpy()
                    weights = 1 / s.groupby("race_key").row_key.transform("size").to_numpy()
                    item.update(
                        mean_add=float(np.average(values, weights=weights)),
                        median_add=wquantile(values, weights, 0.5),
                        p10=wquantile(values, weights, 0.1),
                        p90=wquantile(values, weights, 0.9),
                        minimum=float(values.min()),
                        maximum=float(values.max()),
                        mean_moisture=float(
                            np.average(s[f"{part}_moisture_add_seconds"], weights=weights)
                        ),
                        mean_month=float(
                            np.average(s[f"{part}_month_add_seconds"], weights=weights)
                        ),
                        mean_gate=float(np.average(s[f"{part}_gate_add_seconds"], weights=weights)),
                    )
                    item["symbol"] = str(symbols([item["mean_add"]], part)[0])
                else:
                    item["symbol"] = "?"
                results.append(item)
    return pd.DataFrame(results)


def main():
    sources = [
        SECTION / "outputs/section_gate_lookup.csv",
        SECTION / "outputs/section_month_lookup.csv",
        SECTION / "outputs/section_moisture_reference.csv",
        WHOLE / "outputs/gate_correction_lookup.csv",
        WHOLE / "outputs/moisture_reference.csv",
        WHOLE / "outputs/month_candidate_reference.csv",
        HERE / "build.py",
        HERE / "PLAN.md",
        OUT / "joint_sensitivity_profiles.csv",
    ]
    hashes = {str(p.relative_to(ROOT)): E.A.sha(p) for p in sources}
    moist, gates, month = factors()
    cube = compose(moist, gates, month)
    print("combined lookup", len(cube), flush=True)
    d = ledger(cube)
    for grain, name in [
        ("condition", "condition_correction_summary.csv"),
        ("overall", "distance_correction_summary.csv"),
        ("year", "year_correction_exposure.csv"),
        ("quarter", "quarter_correction_exposure.csv"),
    ]:
        result = summarize(d, grain)
        result.to_csv(OUT / name, index=False)
        print(name, len(result), flush=True)
    extent = (
        cube.groupby(["meet", "distance_m", "period", "band", "target"], observed=True)
        .total_add_seconds.agg(["count", "min", "max"])
        .reset_index()
    )
    extent.to_csv(OUT / "condition_grid_extent.csv", index=False)
    coverage = (
        d.groupby(["meet", "distance_m", "period"], observed=True)
        .agg(
            rows=("row_key", "size"),
            races=("race_key", "nunique"),
            finish_available=("finish_complete", "sum"),
            early_available=("early_complete", "sum"),
            late_available=("late_complete", "sum"),
        )
        .reset_index()
    )
    coverage.to_csv(OUT / "correction_coverage.csv", index=False)
    E.dump(
        OUT / "config.json",
        dict(
            version="environment_atlas_20261008",
            status="trial_only",
            available_from="2026-10-08",
            rule="corrected_time = raw_time + moisture + month + gate",
            lateral_included=False,
            thresholds=THRESHOLDS,
            periods=E.PERIODS,
            targets=PARTS,
            original_moisture_adoption_preserved=True,
            extrapolate_missing=False,
            input_sha256=hashes,
        ),
    )
    E.dump(
        OUT / "build_summary.json",
        dict(
            input_sha256=hashes,
            lookup_rows=len(cube),
            lookup_complete=int(cube.complete.sum()),
            ledger_rows=len(d),
            unique_source_records=int(d.row_key.nunique()),
            complete_by_target={part: int(d[f"{part}_complete"].sum()) for part in PARTS},
            production_changed=False,
            prediction_validation=False,
        ),
    )


if __name__ == "__main__":
    main()
