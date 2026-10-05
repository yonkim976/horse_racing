"""Outlier sensitivity, grade heterogeneity and partial moisture correction."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
PREVIOUS = HERE.parent / "20261002_moisture_only"
RETRAIN_PATH = HERE.parent / "20261002_moisture_distance_retrain"
AUDIT = HERE.parent / "20261002_track_source_reconciliation/results"
SPEC = importlib.util.spec_from_file_location("moisture_retrain", RETRAIN_PATH / "analyze.py")
RETRAIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RETRAIN)
BASE = RETRAIN.BASE
SCENARIOS = ["baseline", "horse_mad4", "horse_trim1", "horse_trim5", "race_mad4"]
DISTANCES = [1200, 1300, 1400, 1600, 1700, 1800]
FLOORS = {"finish": 0.5, "last_600": 0.2, "last_200": 0.1, "start_200": 0.05}
KEY = BASE.KEY


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def thresholds(frame, minimum, tail=None):
    lower = pd.Series(np.nan, index=frame.index)
    upper = lower.copy()
    context = pd.Series("", index=frame.index)
    for names, label in [
        (["meet", "part", "distance_m", "grade", "year"], "distance_grade_year"),
        (["meet", "part", "distance_m", "year"], "distance_year"),
        (["meet", "part", "year"], "venue_year"),
    ]:
        grouped = frame.groupby(names, observed=True)
        count = grouped.residual.transform("size")
        use = lower.isna() & count.ge(minimum)
        if tail is not None:
            lo = grouped.residual.transform(lambda s: s.quantile(tail))
            hi = grouped.residual.transform(lambda s: s.quantile(1 - tail))
        else:
            center = grouped.residual.transform("median")
            deviation = (frame.residual - center).abs()
            scale = (
                deviation.groupby([frame[name] for name in names], observed=True).transform(
                    "median"
                )
                * 1.4826
            )
            floor = frame.part.map(FLOORS) * (0.5 if minimum == 30 else 1)
            scale = pd.Series(np.maximum(scale, floor), index=frame.index)
            lo, hi = center - 4 * scale, center + 4 * scale
        lower.loc[use], upper.loc[use], context.loc[use] = lo.loc[use], hi.loc[use], label
    assert lower.notna().all() and upper.notna().all()
    assert lower.le(upper).all()
    return lower, upper, context


def filtered_races(horse, original_race, scenario):
    level = "race" if scenario == "race_mad4" else "horse"
    source = original_race if level == "race" else horse
    if scenario == "baseline":
        keep = pd.Series(True, index=source.index)
        lower, upper, context = (
            source.residual * 0 - np.inf,
            source.residual * 0 + np.inf,
            pd.Series("none", index=source.index),
        )
    else:
        tail = {"horse_trim1": 0.01, "horse_trim5": 0.05}.get(scenario)
        lower, upper, context = thresholds(source, 30 if level == "race" else 100, tail)
        keep = source.residual.between(lower, upper)
    ledger = source[
        ["meet", "part", "race_key", "date", "distance_m", "grade", "year", "band", "residual"]
    ].copy()
    if level == "horse":
        ledger["horse_id"] = source.horse_id
    ledger["lower"], ledger["upper"], ledger["context"], ledger["retained"] = (
        lower,
        upper,
        context,
        keep,
    )
    ledger["side"] = np.where(
        source.residual.lt(lower), "fast", np.where(source.residual.gt(upper), "slow", "retained")
    )
    if level == "race":
        race = source[keep].copy()
    else:
        race = BASE.races_from_horses(horse[keep])
        race = race.merge(
            original_race[["meet", "part", "race_key", "grade"]],
            on=["meet", "part", "race_key"],
            validate="one_to_one",
        )
    coverage = []
    for (meet, part, band), group in ledger.groupby(["meet", "part", "band"]):
        coverage.append(
            {
                "meet": int(meet),
                "part": part,
                "band": band,
                "level": level,
                "input_rows": len(group),
                "retained": int(group.retained.sum()),
                "fast_removed": int(group.side.eq("fast").sum()),
                "slow_removed": int(group.side.eq("slow").sum()),
            }
        )
    return race, ledger, coverage


def descriptions(race):
    rows = []
    for _, one in race.groupby(["meet", "part"]):
        for grade in [None] + sorted(one.grade.unique()):
            grade_sample = one if grade is None else one[one.grade.eq(grade)]
            for distance in [None] + DISTANCES:
                sample = (
                    grade_sample
                    if distance is None
                    else grade_sample[grade_sample.distance_m.eq(distance)]
                )
                if len(sample) < 100:
                    continue
                for row in BASE.ols_contrasts(sample, "band", "건조", distance):
                    row["grade"] = grade
                    rows.append(row)
    return rows


def support(one, grade, band):
    cell = one[one.grade.eq(grade) & one.band.eq(band)]
    return {
        "races": len(cell),
        "days": cell.day_key.nunique(),
        "supported": bool(len(cell) >= 30 and cell.day_key.nunique() >= 20),
    }


def joint_grade(one):
    one = one[one.grade.str.contains(r"[1-6]등급$", regex=True)].copy()
    reference = "국6등급"
    if reference not in set(one.grade):
        return []
    grades = [reference] + sorted(g for g in one.grade.unique() if g != reference)
    distances = sorted(one.distance_m.unique())
    x = pd.DataFrame({"intercept": 1.0, "race_no": one.race_no.to_numpy(float)}, index=one.index)
    for name, levels in [
        ("grade", grades),
        ("band", BASE.BANDS),
        ("distance_m", distances),
        ("year", sorted(one.year.unique())),
        ("month", sorted(one.month.unique())),
    ]:
        for value in levels[1:]:
            x[f"{name}:{value}"] = one[name].eq(value).astype(float)
    for band in BASE.BANDS[1:]:
        for grade in grades[1:]:
            x[f"grade_band:{grade}:{band}"] = (one.grade.eq(grade) & one.band.eq(band)).astype(
                float
            )
        for distance in distances[1:]:
            x[f"distance_band:{distance}:{band}"] = (
                one.distance_m.eq(distance) & one.band.eq(band)
            ).astype(float)
    design, y = x.to_numpy(float), one.residual.to_numpy(float)
    gram = design.T @ design
    inverse = np.linalg.pinv(gram, rcond=1e-10)
    projection = inverse @ gram
    beta = inverse @ design.T @ y
    errors = y - design @ beta
    scores = pd.DataFrame(design * errors[:, None]).groupby(one.day_key.to_numpy()).sum().to_numpy()
    g, rank = len(scores), np.linalg.matrix_rank(gram, tol=1e-8)
    cov = inverse @ (scores.T @ scores) @ inverse * g / (g - 1) * (len(one) - 1) / (len(one) - rank)
    rows = []
    for grade in grades[1:]:
        for band in ["포화", "불량"]:
            vector = np.zeros(len(x.columns))
            vector[x.columns.get_loc(f"grade_band:{grade}:{band}")] = 1
            error = float(np.max(np.abs(vector - vector @ projection)))
            supports = [support(one, gg, bb) for gg in [grade, reference] for bb in [band, "건조"]]
            row = {
                "meet": int(one.meet.iloc[0]),
                "grade": grade,
                "reference_grade": reference,
                "band": band,
                "support": supports,
                "supported": all(s["supported"] for s in supports),
                "estimable": error < 1e-6,
                "projection_error": error,
            }
            if row["estimable"]:
                value = float(vector @ beta)
                se = float(np.sqrt(max(0, vector @ cov @ vector)))
                cutoff = float(t.ppf(0.975, g - 1))
                row.update(
                    seconds=value,
                    ci95=[value - cutoff * se, value + cutoff * se],
                    p=float(2 * t.sf(abs(value / se), g - 1)) if se > 1e-14 else 1.0,
                )
            rows.append(row)
    return rows


def bh(values):
    values = np.asarray(values, float)
    order = np.argsort(values)
    adjusted = np.minimum.accumulate(
        (values[order] * len(values) / np.arange(1, len(values) + 1))[::-1]
    )[::-1]
    result = np.empty(len(values))
    result[order] = np.clip(adjusted, 0, 1)
    return result


def predictions(features, effect_maps):
    variants = {
        "raw": ("baseline", 0),
        "baseline_025": ("baseline", 0.25),
        "baseline_050": ("baseline", 0.5),
        "baseline_100": ("baseline", 1),
    }
    variants.update(
        {
            f"{scenario}_{int(rate * 100):03}": (scenario, rate)
            for scenario in SCENARIOS[1:]
            for rate in (0.5, 1)
        }
    )
    frame = features.copy()
    for scenario, effect in effect_maps.items():
        mapping = effect.set_index(["part", "race_key"]).effect_distance
        for ordinal in ["prev", "prev2"]:
            index = pd.MultiIndex.from_frame(
                frame[["part", f"{ordinal}_key"]].rename(columns={f"{ordinal}_key": "race_key"})
            )
            frame[f"{ordinal}_{scenario}_effect"] = mapping.reindex(index).to_numpy()
            assert frame[f"{ordinal}_{scenario}_effect"].notna().all()
    allowed = BASE.EXPECT_CAT + BASE.EXPECT_NUM
    rows, fits = [], []
    for (meet, part), one in frame.groupby(["meet", "part"]):
        for year in range(2024, 2027):
            train, test = one[one.year.lt(year)].copy(), one[one.year.eq(year)].copy()
            assert train.year.max() < year
            test["prediction_trained_through"] = int(train.year.max())
            fits.append(
                {
                    "meet": int(meet),
                    "part": part,
                    "year": year,
                    "train_n": len(train),
                    "test_n": len(test),
                }
            )
            for name, (scenario, rate) in variants.items():
                xtrain, xtest = train[allowed].copy(), test[allowed].copy()
                for ordinal in ["prev", "prev2"]:
                    xtrain[f"{ordinal}_time"] -= rate * train[f"{ordinal}_{scenario}_effect"]
                    xtest[f"{ordinal}_time"] -= rate * test[f"{ordinal}_{scenario}_effect"]
                model = BASE.ridge_model(BASE.EXPECT_CAT, BASE.EXPECT_NUM, 20)
                model.fit(xtrain, train.target)
                test[f"prediction_{name}"] = model.predict(xtest)
                test[f"err_{name}"] = np.abs(test.target - test[f"prediction_{name}"])
            rows.append(test)
    evaluation = pd.concat(rows, ignore_index=True)
    assert not evaluation.duplicated(KEY + ["part"]).any()
    assert (evaluation.prediction_trained_through < evaluation.year).all()
    summary = []
    for (meet, part), one in evaluation.groupby(["meet", "part"]):
        for period in ["all", "2024", "2025", "2026"]:
            sample = one if period == "all" else one[one.year.eq(int(period))]
            row = {
                "meet": int(meet),
                "part": part,
                "year": period,
                "n": len(sample),
                "mae": {v: float(sample[f"err_{v}"].mean()) for v in variants},
                "deltas": {},
            }
            for name in variants:
                if name != "raw":
                    delta = sample[f"err_{name}"] - sample.err_raw
                    row["deltas"][name] = {
                        "seconds": float(delta.mean()),
                        "ci95": BASE.bootstrap(sample, delta),
                    }
            summary.append(row)
    return evaluation, summary, fits


def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite outputs")
    paths = [
        HERE / "PLAN.md",
        HERE / "analyze.py",
        PREVIOUS / "analyze.py",
        RETRAIN_PATH / "analyze.py",
        PREVIOUS / "outputs/quality_filtered/horse_residuals.parquet",
        PREVIOUS / "outputs/quality_filtered/race_residuals.parquet",
        RETRAIN_PATH / "outputs/quality_filtered/historical_features.parquet",
        RETRAIN_PATH / "outputs/quality_filtered/prediction_evaluation.parquet",
        AUDIT / "api_study_population.parquet",
        AUDIT / "api_band_percent_conflicts.csv",
        AUDIT / "runner_clean_differences.csv",
    ]
    hashes = {str(path.relative_to(ROOT)): sha(path) for path in paths}
    OUT.mkdir()
    horse = pd.read_parquet(paths[4])
    race = pd.read_parquet(paths[5])
    metadata = horse[["meet", "part", "race_key", "grade"]].drop_duplicates()
    assert not metadata.duplicated(["meet", "part", "race_key"]).any()
    race = race.merge(metadata, on=["meet", "part", "race_key"], validate="one_to_one")
    features = pd.read_parquet(paths[6])
    api = pd.read_parquet(paths[8])
    bad = pd.read_csv(paths[9])[KEY[:3]]
    differences = pd.read_csv(paths[10], dtype={"horse_id": str})
    bad = pd.concat(
        [bad, differences[differences.status.eq("different")][KEY[:3]]]
    ).drop_duplicates()
    rec = api.merge(bad.assign(excluded=True), on=KEY[:3], how="left", validate="many_to_one")
    rec = BASE.prepare(rec[rec.excluded.isna()].drop(columns="excluded"))
    summary = {"inputs_sha256": hashes, "scenarios": {}}
    effects = {}
    for scenario in SCENARIOS:
        print(f"Analyzing {scenario}", flush=True)
        directory = OUT / scenario
        directory.mkdir()
        filtered, ledger, coverage = filtered_races(horse, race, scenario)
        desc = descriptions(filtered)
        grade_tests = [
            r
            for _, one in filtered[filtered.part.eq("finish")].groupby("meet")
            for r in joint_grade(one)
        ]
        family = [r for r in grade_tests if r["supported"] and r["estimable"]]
        for row, q in zip(family, bh([r["p"] for r in family]), strict=True):
            row["q"] = float(q)
        effect, _ = RETRAIN.frozen_effects(rec, filtered)
        assert (effect.environment_trained_through < effect.year).all()
        effects[scenario] = effect
        filtered.to_parquet(directory / "race_residuals.parquet", index=False)
        ledger.to_parquet(directory / "filter_ledger.parquet", index=False)
        effect.to_parquet(directory / "frozen_effects.parquet", index=False)
        result = {
            "filter_level": "race" if scenario == "race_mad4" else "horse",
            "input_rows": len(ledger),
            "retained_rows": int(ledger.retained.sum()),
            "removed": int((~ledger.retained).sum()),
            "race_goal_rows": len(filtered),
            "coverage": coverage,
            "descriptive": desc,
            "grade_tests": grade_tests,
        }
        summary["scenarios"][scenario] = result
        (directory / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(
            json.dumps(
                [
                    r
                    for r in desc
                    if r["part"] == "finish"
                    and r["distance_m"] == 1200
                    and r["grade"] is None
                    and r["level"] in ["포화", "불량"]
                ],
                ensure_ascii=False,
            ),
            flush=True,
        )
    print("Retraining all correction strengths on the same rows", flush=True)
    evaluation, pred_summary, fits = predictions(features, effects)
    evaluation.to_parquet(OUT / "prediction_evaluation.parquet", index=False)
    old_eval = pd.read_parquet(paths[7])
    merged = evaluation.merge(
        old_eval[KEY + ["part", "prediction_raw", "prediction_distance"]],
        on=KEY + ["part"],
        suffixes=("", "_old"),
        validate="one_to_one",
    )
    assert len(merged) == len(evaluation) == len(old_eval)
    assert np.allclose(merged.prediction_raw, merged.prediction_raw_old, atol=1e-8)
    assert np.allclose(merged.prediction_baseline_100, merged.prediction_distance, atol=1e-8)
    proposals = []
    for meet in [1, 3]:
        for band in ["포화", "불량"]:
            rows = [
                next(
                    r
                    for r in summary["scenarios"][scenario]["descriptive"]
                    if r["meet"] == meet
                    and r["part"] == "finish"
                    and r["distance_m"] == 1200
                    and r["grade"] is None
                    and r["level"] == band
                )
                for scenario in SCENARIOS
            ]
            supported = all(r["ci95"] is not None and r["ci95"][1] < 0 for r in rows)
            row = {
                "meet": meet,
                "distance_m": 1200,
                "band": band,
                "all_filters_supported_fast": supported,
            }
            if supported:
                minimum = min(abs(r["seconds"]) for r in rows)
                cap = min(abs(r["ci95"][1]) for r in rows)
                row["add_seconds_025_050"] = [min(minimum * 0.25, cap), min(minimum * 0.5, cap)]
                row["observed_effect_range"] = [
                    min(r["seconds"] for r in rows),
                    max(r["seconds"] for r in rows),
                ]
                row["upper_ci_cap_seconds"] = cap
            proposals.append(row)
    assert hashes == {str(path.relative_to(ROOT)): sha(path) for path in paths}
    summary.update(
        prediction_summary=pred_summary,
        prediction_fits=fits,
        retrospective_reference_proposals=proposals,
        validation={
            "inputs_unchanged": True,
            "same_training_and_evaluation_rows": True,
            "prior_year_environment_models": True,
            "prior_year_prediction_models": True,
            "raw_and_full_baseline_predictions_reproduced": True,
            "current_target_not_trimmed_in_prediction_evaluation": True,
            "no_track_speed": True,
        },
    )
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            [r for r in pred_summary if r["part"] == "finish" and r["year"] == "all"],
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
