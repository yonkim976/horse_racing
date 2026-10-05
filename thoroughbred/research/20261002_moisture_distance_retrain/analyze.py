"""Chronological moisture correction of historical features, then retraining."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREVIOUS = HERE.parent / "20261002_moisture_only"
AUDIT = HERE.parent / "20261002_track_source_reconciliation/results"
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("moisture_previous", PREVIOUS / "analyze.py")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)
VARIANTS = ["raw", "pooled", "distance"]
KEY = BASE.KEY
PARTS = BASE.PARTS


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def interaction(frame):
    frame = frame.copy()
    frame["distance_band"] = frame.distance_m.astype(str) + ":" + frame.band.astype(str)
    return frame


def environment_model(train, variant):
    cats = ["distance_m", "month"]
    if variant in ("pooled", "distance"):
        cats.append("band")
    if variant == "distance":
        cats.append("distance_band")
    model = BASE.ridge_model(cats, ["year", "race_no"], 25)
    model.fit(train, train.residual)
    return model


def frozen_effects(rec, race):
    sources = rec.drop_duplicates("race_key").copy()
    effects, evaluations = [], []
    for (meet, part), one in race.groupby(["meet", "part"]):
        for year in range(2021, 2027):
            train = interaction(one[one.year.lt(year)])
            test = sources[sources.meet.eq(meet) & sources.year.eq(year)].copy()
            if len(train) < 100 or test.empty:
                continue
            assert train.year.max() < year
            test["part"] = part
            test["environment_trained_through"] = int(train.year.max())
            actual = interaction(test)
            reference = test.copy()
            reference["band"] = "건조"
            reference = interaction(reference)
            support = train.groupby("band").day_key.nunique()
            cells = train.groupby(["distance_m", "band"]).day_key.nunique()
            test["band_training_days"] = test.band.map(support).fillna(0).astype(int)
            test["distance_band_training_days"] = [
                int(cells.get((d, b), 0)) for d, b in zip(test.distance_m, test.band, strict=True)
            ]
            test["dry_training_days"] = int(support.get("건조", 0))
            test["distance_dry_training_days"] = [
                int(cells.get((d, "건조"), 0)) for d in test.distance_m
            ]
            for variant in VARIANTS:
                model = environment_model(train, variant)
                test[f"env_prediction_{variant}"] = model.predict(actual)
                test[f"effect_{variant}"] = (
                    model.predict(actual) - model.predict(reference) if variant != "raw" else 0
                )
            evaluations.append(
                one[one.year.eq(year)].merge(
                    test[["race_key"] + [f"env_prediction_{v}" for v in VARIANTS]],
                    on="race_key",
                    validate="one_to_one",
                )
            )
            effects.append(test)
    effect = pd.concat(effects, ignore_index=True)
    evaluation = pd.concat(evaluations, ignore_index=True)
    assert not effect.duplicated(["meet", "part", "race_key"]).any()
    assert (effect.environment_trained_through < effect.year).all()
    for variant in VARIANTS:
        evaluation[f"err_{variant}"] = np.abs(
            evaluation.residual - evaluation[f"env_prediction_{variant}"]
        )
    return effect, evaluation[evaluation.year.ge(2024)].copy()


def historical_features(rec, effects):
    rows, coverage = [], []
    keep = [
        "race_key",
        "year",
        "environment_trained_through",
        "band_training_days",
        "distance_band_training_days",
        "dry_training_days",
        "distance_dry_training_days",
    ]
    keep += [f"effect_{v}" for v in VARIANTS]
    for part in PARTS:
        hist = (
            rec[rec[part].notna()]
            .sort_values(["meet", "horse_id", "distance_m", "date", "race_no"])
            .copy()
        )
        src = effects[effects.part.eq(part)][keep].rename(columns={"year": "source_year"})
        hist = hist.merge(src, on="race_key", how="left", validate="many_to_one")
        group = hist.groupby(["meet", "horse_id", "distance_m"], sort=False)
        hist["prev_time"] = group[part].shift(1)
        hist["prev2_time"] = group[part].shift(2).fillna(hist.prev_time)
        hist["prev_date"] = group.dt.shift(1)
        hist["prev2_date"] = group.dt.shift(2).fillna(hist.prev_date)
        hist["prev_key"] = group.race_key.shift(1)
        hist["prev2_key"] = group.race_key.shift(2).fillna(hist.prev_key)
        hist["prev_band"] = group.band.shift(1)
        hist["prev_source_year"] = group.source_year.shift(1)
        hist["prev2_source_year"] = group.source_year.shift(2).fillna(hist.prev_source_year)
        # Do not fill a missing coefficient of an existing second record with the first.
        no_second = group.race_key.shift(2).isna()
        fields = [
            "environment_trained_through",
            "band_training_days",
            "distance_band_training_days",
            "dry_training_days",
            "distance_dry_training_days",
        ] + [f"effect_{v}" for v in VARIANTS]
        for field in fields:
            hist[f"prev_{field}"] = group[field].shift(1)
            second = group[field].shift(2)
            hist[f"prev2_{field}"] = second.where(~no_second, hist[f"prev_{field}"])
        hist["gap_days"] = (hist.dt - hist.prev_date).dt.days
        eligible = hist.gap_days.between(1, 365)
        available = hist.prev_effect_pooled.notna() & hist.prev2_effect_pooled.notna()
        for (meet, year, distance), cell in hist[eligible & hist.year.ge(2024)].groupby(
            ["meet", "year", "distance_m"]
        ):
            coverage.append(
                {
                    "meet": int(meet),
                    "year": int(year),
                    "distance_m": int(distance),
                    "part": part,
                    "raw_eligible": len(cell),
                    "paired_eligible": int(available.loc[cell.index].sum()),
                }
            )
        hist = hist[eligible & available].copy()
        hist["gap_days"] = np.log1p(hist.gap_days)
        hist["target"], hist["part"] = hist[part], part
        assert (hist.prev_date < hist.dt).all() and (hist.prev2_date < hist.dt).all()
        assert (hist.prev_environment_trained_through < hist.prev_date.dt.year).all()
        assert (hist.prev2_environment_trained_through < hist.prev2_date.dt.year).all()
        for ordinal in ("prev", "prev2"):
            check = hist.merge(
                rec[KEY + ["race_key", "distance_m", part]].rename(
                    columns={
                        "race_key": f"{ordinal}_key",
                        "distance_m": "check_distance",
                        part: "check_time",
                    }
                ),
                on=["meet", "horse_id", f"{ordinal}_key"],
                suffixes=("", "_check"),
                how="left",
                validate="many_to_one",
            )
            assert check.check_time.notna().all()
            assert np.allclose(check.check_time, check[f"{ordinal}_time"])
            assert check.check_distance.eq(check.distance_m).all()
        rows.append(hist)
    frame = pd.concat(rows, ignore_index=True)
    assert not frame.duplicated(KEY + ["part"]).any()
    return frame, pd.DataFrame(coverage)


def retrain(features):
    rows, fits = [], []
    allowed = BASE.EXPECT_CAT + BASE.EXPECT_NUM
    assert set(allowed) == {
        "distance_m",
        "grade",
        "month",
        "prev_time",
        "prev2_time",
        "gap_days",
        "weight",
        "gate",
    }
    for (meet, part), one in features.groupby(["meet", "part"]):
        for year in range(2024, 2027):
            train, test = one[one.year.lt(year)].copy(), one[one.year.eq(year)].copy()
            assert len(train) >= 100 and train.year.max() < year
            test["prediction_trained_through"] = int(train.year.max())
            fits.append(
                {
                    "meet": int(meet),
                    "part": part,
                    "year": year,
                    "train_n": len(train),
                    "test_n": len(test),
                    "train_first_date": train.date.min(),
                    "train_last_date": train.date.max(),
                }
            )
            for variant in VARIANTS:
                xtrain, xtest = train[allowed].copy(), test[allowed].copy()
                for ordinal in ("prev", "prev2"):
                    if variant != "raw":
                        xtrain[f"{ordinal}_time"] -= train[f"{ordinal}_effect_{variant}"]
                        xtest[f"{ordinal}_time"] -= test[f"{ordinal}_effect_{variant}"]
                model = BASE.ridge_model(BASE.EXPECT_CAT, BASE.EXPECT_NUM, 20)
                model.fit(xtrain, train.target)
                test[f"prediction_{variant}"] = model.predict(xtest)
                test[f"err_{variant}"] = np.abs(test.target - test[f"prediction_{variant}"])
            rows.append(test)
    evaluation = pd.concat(rows, ignore_index=True)
    assert (evaluation.prediction_trained_through < evaluation.year).all()
    assert not evaluation.duplicated(KEY + ["part"]).any()
    assert np.isfinite(evaluation[[f"err_{v}" for v in VARIANTS]]).all().all()
    return evaluation, fits


def summarize(frame, by_distance=False, by_band=False):
    keys = ["meet", "part"] + (["distance_m"] if by_distance else [])
    keys += ["prev_band"] if by_band else []
    rows = []
    for key, one in frame.groupby(keys):
        for period in ["all", "2024", "2025", "2026"]:
            sample = one if period == "all" else one[one.year.eq(int(period))]
            if sample.empty:
                continue
            row = dict(zip(keys, key, strict=True))
            row = {k: int(v) if isinstance(v, (int, np.integer)) else v for k, v in row.items()}
            row.update(
                year=period,
                n=len(sample),
                races=sample.race_key.nunique(),
                days=sample.day_key.nunique(),
                support="supported"
                if len(sample) >= 100 and sample.day_key.nunique() >= 20
                else "insufficient",
            )
            row["mae"] = {v: float(sample[f"err_{v}"].mean()) for v in VARIANTS}
            row["delta_vs_raw"] = {}
            for variant in VARIANTS[1:]:
                delta = sample[f"err_{variant}"] - sample.err_raw
                row["delta_vs_raw"][variant] = {
                    "seconds": float(delta.mean()),
                    "ci95": BASE.bootstrap(sample, delta)
                    if row["support"] == "supported"
                    else None,
                }
            delta = sample.err_distance - sample.err_pooled
            row["distance_minus_pooled"] = {
                "seconds": float(delta.mean()),
                "ci95": BASE.bootstrap(sample, delta) if row["support"] == "supported" else None,
            }
            if "prev_distance_band_training_days" in sample:
                low = (
                    sample.prev_distance_band_training_days.lt(20)
                    | sample.prev_distance_dry_training_days.lt(20)
                    | sample.prev2_distance_band_training_days.lt(20)
                    | sample.prev2_distance_dry_training_days.lt(20)
                )
                row["low_support_historical_rows"] = int(low.sum())
            rows.append(row)
    return rows


def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite study outputs")
    paths = [
        AUDIT / "api_study_population.parquet",
        AUDIT / "api_band_percent_conflicts.csv",
        AUDIT / "runner_clean_differences.csv",
        HERE / "PLAN.md",
        HERE / "analyze.py",
        PREVIOUS / "analyze.py",
    ]
    paths += [
        PREVIOUS / "outputs" / scenario / "race_residuals.parquet"
        for scenario in ("quality_filtered", "all_api")
    ]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    OUT.mkdir()
    api = pd.read_parquet(paths[0])
    conflicts = pd.read_csv(paths[1])[KEY[:3]].drop_duplicates()
    differences = pd.read_csv(paths[2], dtype={"horse_id": str})
    bad = pd.concat([conflicts, differences[differences.status.eq("different")][KEY[:3]]])
    bad = bad.drop_duplicates()
    quality = api.merge(bad.assign(excluded=True), on=KEY[:3], how="left", validate="many_to_one")
    quality = quality[quality.excluded.isna()].drop(columns="excluded")
    summary = {
        "inputs_sha256": hashes,
        "excluded_races": len(bad),
        "excluded_runners": len(api) - len(quality),
        "scenarios": {},
    }
    for scenario, population in (("quality_filtered", quality), ("all_api", api)):
        print(f"Starting {scenario}", flush=True)
        directory = OUT / scenario
        directory.mkdir()
        rec = BASE.prepare(population)
        race = pd.read_parquet(PREVIOUS / "outputs" / scenario / "race_residuals.parquet")
        effects, race_eval = frozen_effects(rec, race)
        features, coverage = historical_features(rec, effects)
        evaluation, fits = retrain(features)
        effects.to_parquet(directory / "frozen_effects.parquet", index=False)
        features.to_parquet(directory / "historical_features.parquet", index=False)
        evaluation.to_parquet(directory / "prediction_evaluation.parquet", index=False)
        race_eval.to_parquet(directory / "race_evaluation.parquet", index=False)
        coverage.to_csv(directory / "coverage.csv", index=False)
        result = {
            "runners": len(rec),
            "feature_rows": len(features),
            "fits": fits,
            "overall": summarize(evaluation),
            "distances": summarize(evaluation, True),
            "previous_bands": summarize(evaluation, True, True),
            "race_overall": summarize(race_eval),
            "race_distances": summarize(race_eval, True),
        }
        summary["scenarios"][scenario] = result
        (directory / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(
            json.dumps(
                [r for r in result["overall"] if r["part"] == "finish" and r["year"] == "all"],
                ensure_ascii=False,
            ),
            flush=True,
        )
    assert hashes == {str(p.relative_to(ROOT)): sha(p) for p in paths}
    summary["validation"] = {
        "inputs_unchanged": True,
        "no_track_speed": True,
        "source_models_prior_year_only": True,
        "prediction_models_prior_year_only": True,
        "historical_time_distance_identity_matches": True,
        "historical_dates_prior_to_current": True,
        "unique_evaluation_keys": True,
        "finite_predictions": True,
        "same_train_test_rows_all_variants": True,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
