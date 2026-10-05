"""Prior-year section-specific moisture strength search."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
PREVIOUS = HERE.parent / "20261002_moisture_strength_selection"
SPEC = importlib.util.spec_from_file_location("strength", PREVIOUS / "analyze.py")
STRENGTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STRENGTH)
BASE = STRENGTH.BASE
PARTS = ["start_200", "last_200", "last_600"]
RATES = STRENGTH.RATES
RULES = ["best", "retain80", "absolute002", "fulltime_rate"]


def name(rate):
    return f"r{int(round(rate * 100)):03}"


def choose(sample):
    errors = np.array([sample[f"err_{name(r)}"].mean() for r in RATES])
    best = int(errors.argmin())
    gain = float(errors[0] - errors[best])
    threshold = errors[0] - 0.8 * gain
    small = int(np.flatnonzero(errors <= threshold + 1e-12)[0])
    absolute = int(np.flatnonzero(errors <= errors[best] + 0.002)[0])
    return {
        "best": float(RATES[best]),
        "retain80": float(RATES[small]),
        "absolute002": float(RATES[absolute]),
        "fulltime_rate": 0.8 if sample.meet.iloc[0] == 1 else 0.9,
        "raw_validation_mae": float(errors[0]),
        "minimum_validation_mae": float(errors[best]),
        "maximum_validation_gain": gain,
        "retain80_validation_mae": float(errors[small]),
        "boundary_best": best == len(RATES) - 1,
    }


def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite outputs")
    paths = [
        HERE / "PLAN.md",
        HERE / "analyze.py",
        PREVIOUS / "analyze.py",
        STRENGTH.RETRAIN / "analyze.py",
        BASE.HERE / "analyze.py",
        STRENGTH.RETRAIN / "outputs/quality_filtered/historical_features.parquet",
        STRENGTH.PREVIOUS / "outputs/horse_mad4/frozen_effects.parquet",
        STRENGTH.PREVIOUS / "outputs/prediction_evaluation.parquet",
        HERE.parents[1] / "docs/TRACK_MOISTURE_CORRECTION_DECISION_2026-10-02.md",
    ]
    hashes = {str(p): STRENGTH.sha(p) for p in paths}
    OUT.mkdir()
    frame = pd.read_parquet(paths[5])
    frame = frame[frame.part.isin(PARTS)].reset_index(drop=True)
    effects = pd.read_parquet(paths[6])
    effects = effects[effects.part.isin(PARTS)]
    assert (effects.environment_trained_through < effects.year).all()
    mapping = effects.set_index(["part", "race_key"]).effect_distance
    for ordinal in ["prev", "prev2"]:
        index = pd.MultiIndex.from_arrays([frame.part, frame[f"{ordinal}_key"]])
        frame[f"{ordinal}_section_effect"] = mapping.reindex(index).to_numpy()
        assert frame[f"{ordinal}_section_effect"].notna().all()
        assert (
            frame[f"{ordinal}_environment_trained_through"] < frame[f"{ordinal}_source_year"]
        ).all()
    rows, fits = [], []
    allowed = BASE.EXPECT_CAT + BASE.EXPECT_NUM
    for (meet, part), one in frame.groupby(["meet", "part"]):
        for year in range(2022, 2027):
            train, test = one[one.year.lt(year)], one[one.year.eq(year)]
            columns = {}
            for rate in RATES:
                xtrain, xtest = train[allowed].copy(), test[allowed].copy()
                for ordinal in ["prev", "prev2"]:
                    xtrain[f"{ordinal}_time"] -= rate * train[f"{ordinal}_section_effect"]
                    xtest[f"{ordinal}_time"] -= rate * test[f"{ordinal}_section_effect"]
                model = BASE.ridge_model(BASE.EXPECT_CAT, BASE.EXPECT_NUM, 20)
                model.fit(xtrain, train.target)
                prediction = model.predict(xtest)
                columns[f"prediction_{name(rate)}"] = prediction
                columns[f"err_{name(rate)}"] = np.abs(test.target.to_numpy(float) - prediction)
            keep = BASE.KEY + ["part", "year", "distance_m", "day_key", "band", "target"]
            result = pd.concat([test[keep].reset_index(drop=True), pd.DataFrame(columns)], axis=1)
            result["prediction_trained_through"] = int(train.year.max())
            assert train.year.max() < year
            rows.append(result)
            fits.append(
                {
                    "meet": int(meet),
                    "part": part,
                    "year": year,
                    "train_n": len(train),
                    "test_n": len(test),
                }
            )
            print(f"meet={meet} part={part} year={year} done", flush=True)
    candidates = pd.concat(rows, ignore_index=True)
    assert not candidates.duplicated(BASE.KEY + ["part"]).any()
    decisions, curves = [], []
    outer = candidates[candidates.year.ge(2024)].copy()
    for rule in RULES:
        outer[f"rate_{rule}"] = np.nan
        outer[f"prediction_{rule}"] = np.nan
    for (meet, part), one in candidates.groupby(["meet", "part"]):
        for year in range(2024, 2027):
            prior = one[one.year.lt(year)]
            choice = {
                "meet": int(meet),
                "part": part,
                "apply_year": year,
                "selection_start": 2022,
                "selection_end": int(prior.year.max()),
                "selection_n": len(prior),
                **choose(prior),
            }
            assert choice["selection_end"] < year
            decisions.append(choice)
            mask = outer.meet.eq(meet) & outer.part.eq(part) & outer.year.eq(year)
            for rule in RULES:
                outer.loc[mask, f"rate_{rule}"] = choice[rule]
                outer.loc[mask, f"prediction_{rule}"] = outer.loc[
                    mask, f"prediction_{name(choice[rule])}"
                ]
            curves += [
                {
                    "meet": int(meet),
                    "part": part,
                    "apply_year": year,
                    "rate": float(r),
                    "mae": float(prior[f"err_{name(r)}"].mean()),
                }
                for r in RATES
            ]
    for rule in RULES:
        outer[f"err_{rule}"] = np.abs(outer.target - outer[f"prediction_{rule}"])
        assert outer[f"err_{rule}"].notna().all()
    summary = []
    for (meet, part), one in outer.groupby(["meet", "part"]):
        for period in ["all", "2024", "2025", "2026"]:
            period_sample = one if period == "all" else one[one.year.eq(int(period))]
            for distance in [None] + sorted(period_sample.distance_m.unique()):
                sample = (
                    period_sample
                    if distance is None
                    else period_sample[period_sample.distance_m.eq(distance)]
                )
                row = {
                    "meet": int(meet),
                    "part": part,
                    "year": period,
                    "distance_m": None if distance is None else int(distance),
                    "n": len(sample),
                    "days": int(sample.day_key.nunique()),
                    "raw_mae": float(sample.err_r000.mean()),
                }
                for rule in RULES:
                    delta = sample[f"err_{rule}"] - sample.err_r000
                    row[rule] = {
                        "mae": float(sample[f"err_{rule}"].mean()),
                        "delta": float(delta.mean()),
                        "ci95": BASE.bootstrap(sample, delta),
                    }
                summary.append(row)
    coefficients = []
    reference = effects[effects.year.eq(2026)]
    for (meet, part, distance, band), cell in reference.groupby(
        ["meet", "part", "distance_m", "band"]
    ):
        choice = next(
            c
            for c in decisions
            if c["meet"] == meet and c["part"] == part and c["apply_year"] == 2026
        )
        values = cell.effect_distance.to_numpy(float)
        assert np.ptp(values) < 1e-8
        support, dry = (
            int(cell.distance_band_training_days.min()),
            int(cell.distance_dry_training_days.min()),
        )
        coefficients.append(
            {
                "meet": int(meet),
                "part": part,
                "distance_m": int(distance),
                "band": band,
                "effect": float(values.mean()),
                "rate_retain80": choice["retain80"],
                "add_seconds_retain80": -choice["retain80"] * float(values.mean()),
                "add_seconds_best": -choice["best"] * float(values.mean()),
                "band_days": support,
                "dry_days": dry,
                "supported": support >= 20 and dry >= 20,
                "environment_trained_through": 2025,
            }
        )
    old = pd.read_parquet(paths[7])
    old = old[old.part.isin(PARTS)]
    merged = outer.merge(
        old[BASE.KEY + ["part", "target", "prediction_raw", "prediction_horse_mad4_100"]],
        on=BASE.KEY + ["part"],
        suffixes=("", "_old"),
        validate="one_to_one",
    )
    assert len(merged) == len(outer) == len(old)
    np.testing.assert_array_equal(merged.target, merged.target_old)
    np.testing.assert_allclose(merged.prediction_r000, merged.prediction_raw, rtol=0, atol=1e-8)
    np.testing.assert_allclose(
        merged.prediction_r100, merged.prediction_horse_mad4_100, rtol=0, atol=1e-8
    )
    assert hashes == {str(p): STRENGTH.sha(p) for p in paths}
    candidates.to_parquet(OUT / "candidate_predictions.parquet", index=False)
    outer.to_parquet(OUT / "selected_predictions.parquet", index=False)
    pd.DataFrame(curves).to_csv(OUT / "validation_curves.csv", index=False)
    pd.DataFrame(coefficients).to_csv(OUT / "reference_seconds.csv", index=False)
    saved = {
        "rates": RATES.tolist(),
        "rules": RULES,
        "parts": PARTS,
        "primary_rule": "retain80",
        "inputs_sha256": hashes,
        "fits": fits,
        "decisions": decisions,
        "evaluation": summary,
        "reference_seconds": coefficients,
        "validation": {
            "inputs_unchanged": True,
            "same_untrimmed_targets": True,
            "raw_and_100_percent_predictions_reproduced": True,
            "prior_year_only_for_models_and_selection": True,
        },
    }
    (OUT / "summary.json").write_text(json.dumps(saved, ensure_ascii=False, indent=2))
    print(json.dumps([c for c in decisions if c["apply_year"] == 2026], ensure_ascii=False))
    print(
        json.dumps(
            [r for r in summary if r["year"] == "all" and r["distance_m"] is None],
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
