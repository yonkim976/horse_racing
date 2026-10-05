"""Independently reconstruct selection and one model per venue/year."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("study", HERE / "analyze.py")
STUDY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STUDY)


def main():
    saved = json.loads((OUT / "summary.json").read_text())
    candidates = pd.read_parquet(OUT / "candidate_predictions.parquet")
    selected = pd.read_parquet(OUT / "selected_predictions.parquet")
    checks = []
    for path, digest in saved["inputs_sha256"].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
    assert not candidates.duplicated(STUDY.BASE.KEY + ["part"]).any()
    assert len(selected) == 36931
    for col in [c for c in candidates if c.startswith("prediction_") and c != "prediction_trained_through"]:
        np.testing.assert_allclose(candidates[col.replace("prediction_", "err_")],
                                   np.abs(candidates.target - candidates[col]), rtol=0, atol=1e-10)
    for choice in saved["selections"]:
        prior = candidates[candidates.meet.eq(choice["meet"]) & candidates.year.lt(choice["apply_year"])]
        scores = [float(prior[f"err_{STUDY.candidate(choice['family'], r)}"].mean()) for r in saved["rates"]]
        best = int(np.argmin(scores))
        conservative = next(i for i, v in enumerate(scores) if v <= min(scores) + 0.002)
        assert choice["best"] == saved["rates"][best]
        assert choice["conservative"] == saved["rates"][conservative]
        assert prior.year.max() == choice["selection_end"] < choice["apply_year"]
        if choice["family"] == saved["primary"]:
            outer = selected[selected.meet.eq(choice["meet"]) & selected.year.eq(choice["apply_year"])]
            for rule in ["best", "conservative"]:
                np.testing.assert_allclose(outer[f"prediction_selected_{rule}"],
                                           outer[f"prediction_{STUDY.candidate(choice['family'], choice[rule])}"],
                                           rtol=0, atol=1e-10)
    features = pd.read_parquet(STUDY.RETRAIN / "outputs/quality_filtered/historical_features.parquet")
    features = features[features.part.eq("finish")].copy()
    effects = pd.read_parquet(STUDY.PREVIOUS / "outputs/horse_mad4/frozen_effects.parquet")
    effects = effects[effects.part.eq("finish")]
    mapping = effects.set_index("race_key").effect_distance
    for ordinal in ["prev", "prev2"]:
        features[f"{ordinal}_effect_check"] = features[f"{ordinal}_key"].map(mapping)
        assert features[f"{ordinal}_effect_check"].notna().all()
    for choice in saved["selections"]:
        if choice["family"] != saved["primary"]:
            continue
        one = features[features.meet.eq(choice["meet"])]
        train, test = one[one.year.lt(choice["apply_year"])], one[one.year.eq(choice["apply_year"])]
        allowed = STUDY.BASE.EXPECT_CAT + STUDY.BASE.EXPECT_NUM
        xtrain, xtest = train[allowed].copy(), test[allowed].copy()
        for ordinal in ["prev", "prev2"]:
            xtrain[f"{ordinal}_time"] -= choice["conservative"] * train[f"{ordinal}_effect_check"]
            xtest[f"{ordinal}_time"] -= choice["conservative"] * test[f"{ordinal}_effect_check"]
        model = STUDY.BASE.ridge_model(STUDY.BASE.EXPECT_CAT, STUDY.BASE.EXPECT_NUM, 20)
        model.fit(xtrain, train.target)
        direct = test[STUDY.BASE.KEY + ["target"]].copy()
        direct["reconstructed"] = model.predict(xtest)
        outer = selected[selected.meet.eq(choice["meet"]) & selected.year.eq(choice["apply_year"])]
        merged = direct.merge(outer, on=STUDY.BASE.KEY, validate="one_to_one", suffixes=("_input", ""))
        assert len(merged) == len(direct) == len(outer)
        np.testing.assert_array_equal(merged.target_input, merged.target)
        difference = float(np.abs(merged.reconstructed - merged.prediction_selected_conservative).max())
        assert difference < 1e-8
        checks.append({"meet": choice["meet"], "year": choice["apply_year"], "n": len(merged),
                       "rate": choice["conservative"], "maximum_prediction_difference": difference})
    for row in saved["evaluation"]:
        one = selected[selected.meet.eq(row["meet"])]
        if row["year"] != "all":
            one = one[one.year.eq(int(row["year"]))]
        if row["distance_m"] is not None:
            one = one[one.distance_m.eq(row["distance_m"])]
        assert len(one) == row["n"]
        for rule in ["best", "conservative"]:
            assert abs(float(one[f"err_selected_{rule}"].mean()) - row[rule]["mae"]) < 1e-10
    report = {"input_hashes_unchanged": True, "all_candidate_errors_recomputed": True,
              "all_selections_recomputed_from_prior_years": True,
              "untrimmed_targets_and_identical_outer_rows": True,
              "all_summary_maes_recomputed": True, "six_reconstructed_folds": checks}
    (OUT / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
