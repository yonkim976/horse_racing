"""Dense moisture strength search with chronological selection, finish only."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / "20261002_moisture_robust_grade"
RETRAIN = HERE.parent / "20261002_moisture_distance_retrain"
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("robust", PREVIOUS / "analyze.py")
ROBUST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ROBUST)
BASE = ROBUST.BASE
FAMILIES = {name: (name, "distance") for name in ROBUST.SCENARIOS}
FAMILIES["horse_mad4_pooled"] = ("horse_mad4", "pooled")
PRIMARY = "horse_mad4"
RATES = np.round(np.arange(0, 3.01, 0.1), 1)
TOLERANCE = 0.002


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate(family, rate):
    return "raw" if rate == 0 else f"{family}_{int(round(rate * 100)):03}"


def choose(frame, family):
    scores = np.array([frame[f"err_{candidate(family, r)}"].mean() for r in RATES])
    best = int(scores.argmin())
    small = int(np.flatnonzero(scores <= scores[best] + TOLERANCE)[0])
    return {"best": float(RATES[best]), "conservative": float(RATES[small]),
            "minimum_mae": float(scores[best]), "conservative_mae": float(scores[small]),
            "boundary_best": best == len(RATES) - 1}


def main():
    if OUT.exists():
        raise FileExistsError("Refusing to overwrite outputs")
    paths = [HERE / "PLAN.md", HERE / "analyze.py", PREVIOUS / "analyze.py",
             RETRAIN / "analyze.py", BASE.HERE / "analyze.py",
             RETRAIN / "outputs/quality_filtered/historical_features.parquet",
             PREVIOUS / "outputs/prediction_evaluation.parquet"]
    paths += [PREVIOUS / f"outputs/{s}/frozen_effects.parquet" for s in ROBUST.SCENARIOS]
    hashes = {str(p): sha(p) for p in paths}
    OUT.mkdir()
    frame = pd.read_parquet(paths[5])
    frame = frame[frame.part.eq("finish")].reset_index(drop=True)
    effects = {s: pd.read_parquet(PREVIOUS / f"outputs/{s}/frozen_effects.parquet")
               for s in ROBUST.SCENARIOS}
    for family, (scenario, variant) in FAMILIES.items():
        effect = effects[scenario]
        effect = effect[effect.part.eq("finish")]
        assert (effect.environment_trained_through < effect.year).all()
        mapping = effect.set_index("race_key")[f"effect_{variant}"]
        for ordinal in ["prev", "prev2"]:
            frame[f"{ordinal}_{family}"] = frame[f"{ordinal}_key"].map(mapping)
            assert frame[f"{ordinal}_{family}"].notna().all()
    assert (frame.prev_environment_trained_through < frame.prev_source_year).all()
    assert (frame.prev2_environment_trained_through < frame.prev2_source_year).all()
    rows, fits = [], []
    names = ["raw"] + [candidate(f, r) for f in FAMILIES for r in RATES[1:]]
    allowed = BASE.EXPECT_CAT + BASE.EXPECT_NUM
    for meet, one in frame.groupby("meet"):
        for year in range(2022, 2027):
            train, test = one[one.year.lt(year)], one[one.year.eq(year)]
            predictions = {}
            for name in names:
                xtrain, xtest = train[allowed].copy(), test[allowed].copy()
                if name != "raw":
                    family, suffix = name.rsplit("_", 1)
                    rate = int(suffix) / 100
                    for ordinal in ["prev", "prev2"]:
                        xtrain[f"{ordinal}_time"] -= rate * train[f"{ordinal}_{family}"]
                        xtest[f"{ordinal}_time"] -= rate * test[f"{ordinal}_{family}"]
                model = BASE.ridge_model(BASE.EXPECT_CAT, BASE.EXPECT_NUM, 20)
                model.fit(xtrain, train.target)
                predictions[f"prediction_{name}"] = model.predict(xtest)
                predictions[f"err_{name}"] = np.abs(test.target.to_numpy(float) - predictions[f"prediction_{name}"])
            keep = BASE.KEY + ["part", "year", "distance_m", "band", "day_key", "target"]
            result = pd.concat([test[keep].reset_index(drop=True), pd.DataFrame(predictions)], axis=1)
            result["prediction_trained_through"] = int(train.year.max())
            fits.append({"meet": int(meet), "year": year, "train_n": len(train), "test_n": len(test)})
            rows.append(result)
            print(f"meet={meet} year={year} completed {len(names)} candidates", flush=True)
    evaluation = pd.concat(rows, ignore_index=True)
    assert not evaluation.duplicated(BASE.KEY + ["part"]).any()
    assert (evaluation.prediction_trained_through < evaluation.year).all()
    selections, curves = [], []
    for meet, one in evaluation.groupby("meet"):
        for family in FAMILIES:
            for year in range(2024, 2027):
                prior = one[one.year.lt(year)]
                decision = choose(prior, family)
                selections.append({"meet": int(meet), "family": family, "apply_year": year,
                                   "selection_start": 2022, "selection_end": int(prior.year.max()),
                                   "selection_n": len(prior), **decision})
                for rate in RATES:
                    curves.append({"meet": int(meet), "family": family, "apply_year": year,
                                   "rate": float(rate),
                                   "validation_mae": float(prior[f"err_{candidate(family, rate)}"].mean())})
    outer = evaluation[evaluation.year.ge(2024)].copy()
    for rule in ["best", "conservative"]:
        outer[f"selected_rate_{rule}"] = np.nan
        outer[f"prediction_selected_{rule}"] = np.nan
        for selection in selections:
            if selection["family"] != PRIMARY:
                continue
            mask = outer.meet.eq(selection["meet"]) & outer.year.eq(selection["apply_year"])
            outer.loc[mask, f"selected_rate_{rule}"] = selection[rule]
            outer.loc[mask, f"prediction_selected_{rule}"] = outer.loc[
                mask, f"prediction_{candidate(PRIMARY, selection[rule])}"]
        outer[f"err_selected_{rule}"] = np.abs(outer.target - outer[f"prediction_selected_{rule}"])
        assert outer[f"err_selected_{rule}"].notna().all()
    summaries = []
    for meet, one in outer.groupby("meet"):
        for period in ["all", "2024", "2025", "2026"]:
            period_frame = one if period == "all" else one[one.year.eq(int(period))]
            for distance in [None] + sorted(period_frame.distance_m.unique()):
                sample = period_frame if distance is None else period_frame[period_frame.distance_m.eq(distance)]
                row = {"meet": int(meet), "year": period, "distance_m": None if distance is None else int(distance),
                       "n": len(sample), "days": int(sample.day_key.nunique()), "raw_mae": float(sample.err_raw.mean())}
                for rule in ["best", "conservative"]:
                    delta = sample[f"err_selected_{rule}"] - sample.err_raw
                    row[rule] = {"mae": float(sample[f"err_selected_{rule}"].mean()),
                                 "delta": float(delta.mean()), "ci95": BASE.bootstrap(sample, delta)}
                summaries.append(row)
    coefficients = []
    effect = effects[PRIMARY]
    reference = effect[effect.part.eq("finish") & effect.year.eq(2026)]
    for (meet, distance, band), cell in reference.groupby(["meet", "distance_m", "band"]):
        values = cell.effect_distance.to_numpy(float)
        assert np.ptp(values) < 1e-8
        selection = next(s for s in selections if s["meet"] == meet and s["family"] == PRIMARY and s["apply_year"] == 2026)
        support = int(cell.distance_band_training_days.min())
        dry = int(cell.distance_dry_training_days.min())
        coefficients.append({"meet": int(meet), "distance_m": int(distance), "band": band,
                             "environment_trained_through": int(cell.environment_trained_through.max()),
                             "band_days": support, "dry_days": dry, "supported": support >= 20 and dry >= 20,
                             "effect": float(values.mean()),
                             "add_seconds_best": -selection["best"] * float(values.mean()),
                             "add_seconds_conservative": -selection["conservative"] * float(values.mean())})
    old = pd.read_parquet(paths[6])
    old = old[old.part.eq("finish")]
    merged = outer.merge(old[BASE.KEY + ["target", "prediction_raw", "prediction_horse_mad4_100"]],
                         on=BASE.KEY, suffixes=("", "_old"), validate="one_to_one")
    assert len(merged) == len(outer) == len(old)
    for col in ["target", "prediction_raw", "prediction_horse_mad4_100"]:
        assert np.allclose(merged[col], merged[f"{col}_old"], rtol=0, atol=1e-8)
    assert hashes == {str(p): sha(p) for p in paths}
    evaluation.to_parquet(OUT / "candidate_predictions.parquet", index=False)
    outer.to_parquet(OUT / "selected_predictions.parquet", index=False)
    pd.DataFrame(curves).to_csv(OUT / "validation_curves.csv", index=False)
    pd.DataFrame(coefficients).to_csv(OUT / "reference_seconds.csv", index=False)
    summary = {"primary": PRIMARY, "tolerance_seconds": TOLERANCE, "rates": RATES.tolist(),
               "inputs_sha256": hashes, "fits": fits, "selections": selections,
               "evaluation": summaries, "reference_seconds": coefficients,
               "validation": {"inputs_unchanged": True, "prior_year_only": True,
                              "unchanged_targets_and_rows": True, "old_predictions_reproduced": True}}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps([s for s in selections if s["family"] == PRIMARY], ensure_ascii=False), flush=True)
    print(json.dumps([s for s in summaries if s["distance_m"] is None], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
