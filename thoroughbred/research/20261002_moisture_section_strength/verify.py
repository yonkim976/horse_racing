"""Recompute prior-only decisions, errors, and six 2026 fits."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SPEC = importlib.util.spec_from_file_location("sections", HERE / "analyze.py")
STUDY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STUDY)


def main():
    saved = json.loads((OUT / "summary.json").read_text())
    candidates = pd.read_parquet(OUT / "candidate_predictions.parquet")
    selected = pd.read_parquet(OUT / "selected_predictions.parquet")
    for path, digest in saved["inputs_sha256"].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
    assert len(selected) == 110790
    assert not selected.duplicated(STUDY.BASE.KEY + ["part"]).any()
    assert (candidates.prediction_trained_through < candidates.year).all()
    for rate in saved["rates"]:
        prediction = candidates[f"prediction_{STUDY.name(rate)}"]
        np.testing.assert_allclose(
            candidates[f"err_{STUDY.name(rate)}"],
            np.abs(candidates.target - prediction),
            rtol=0,
            atol=1e-10,
        )
    for choice in saved["decisions"]:
        prior = candidates[
            candidates.meet.eq(choice["meet"])
            & candidates.part.eq(choice["part"])
            & candidates.year.lt(choice["apply_year"])
        ]
        assert prior.year.max() == choice["selection_end"] < choice["apply_year"]
        errors = np.array([prior[f"err_{STUDY.name(r)}"].mean() for r in saved["rates"]])
        best = int(errors.argmin())
        threshold = errors[0] - 0.8 * (errors[0] - errors[best])
        small = next(i for i, error in enumerate(errors) if error <= threshold + 1e-12)
        absolute = next(i for i, error in enumerate(errors) if error <= errors[best] + 0.002)
        assert choice["best"] == saved["rates"][best]
        assert choice["retain80"] == saved["rates"][small]
        assert choice["absolute002"] == saved["rates"][absolute]
        one = selected[
            selected.meet.eq(choice["meet"])
            & selected.part.eq(choice["part"])
            & selected.year.eq(choice["apply_year"])
        ]
        for rule in saved["rules"]:
            np.testing.assert_allclose(
                one[f"prediction_{rule}"],
                one[f"prediction_{STUDY.name(choice[rule])}"],
                rtol=0,
                atol=1e-10,
            )
    features = pd.read_parquet(
        STUDY.STRENGTH.RETRAIN / "outputs/quality_filtered/historical_features.parquet"
    )
    effects = pd.read_parquet(STUDY.STRENGTH.PREVIOUS / "outputs/horse_mad4/frozen_effects.parquet")
    reconstructed = []
    for choice in saved["decisions"]:
        if choice["apply_year"] != 2026:
            continue
        one = features[features.meet.eq(choice["meet"]) & features.part.eq(choice["part"])].copy()
        mapping = effects[effects.part.eq(choice["part"])].set_index("race_key").effect_distance
        for ordinal in ["prev", "prev2"]:
            one[f"{ordinal}_checked"] = one[f"{ordinal}_key"].map(mapping)
            assert one[f"{ordinal}_checked"].notna().all()
        train, test = one[one.year.lt(2026)], one[one.year.eq(2026)]
        columns = STUDY.BASE.EXPECT_CAT + STUDY.BASE.EXPECT_NUM
        xtrain, xtest = train[columns].copy(), test[columns].copy()
        for ordinal in ["prev", "prev2"]:
            xtrain[f"{ordinal}_time"] -= choice["retain80"] * train[f"{ordinal}_checked"]
            xtest[f"{ordinal}_time"] -= choice["retain80"] * test[f"{ordinal}_checked"]
        model = STUDY.BASE.ridge_model(STUDY.BASE.EXPECT_CAT, STUDY.BASE.EXPECT_NUM, 20)
        model.fit(xtrain, train.target)
        actual = test[STUDY.BASE.KEY + ["target"]].copy()
        actual["reconstructed"] = model.predict(xtest)
        expected = selected[
            selected.meet.eq(choice["meet"])
            & selected.part.eq(choice["part"])
            & selected.year.eq(2026)
        ]
        merged = actual.merge(
            expected, on=STUDY.BASE.KEY, validate="one_to_one", suffixes=("_input", "")
        )
        assert len(merged) == len(actual) == len(expected)
        np.testing.assert_array_equal(merged.target, merged.target_input)
        difference = float(np.abs(merged.reconstructed - merged.prediction_retain80).max())
        assert difference < 1e-8
        reconstructed.append(
            {
                "meet": choice["meet"],
                "part": choice["part"],
                "year": 2026,
                "rate": choice["retain80"],
                "maximum_prediction_difference": difference,
            }
        )
    for row in saved["evaluation"]:
        one = selected[selected.meet.eq(row["meet"]) & selected.part.eq(row["part"])]
        if row["year"] != "all":
            one = one[one.year.eq(int(row["year"]))]
        if row["distance_m"] is not None:
            one = one[one.distance_m.eq(row["distance_m"])]
        assert len(one) == row["n"]
        for rule in saved["rules"]:
            assert abs(float(one[f"err_{rule}"].mean()) - row[rule]["mae"]) < 1e-10
            assert (
                abs(float((one[f"err_{rule}"] - one.err_r000).mean()) - row[rule]["delta"]) < 1e-10
            )
    for cell in saved["reference_seconds"]:
        assert cell["supported"] == (cell["band_days"] >= 20 and cell["dry_days"] >= 20)
        assert abs(cell["add_seconds_retain80"] + cell["effect"] * cell["rate_retain80"]) < 1e-12
    result = {
        "inputs_and_fulltime_decision_unchanged": True,
        "evaluation_rows": len(selected),
        "all_candidate_errors_and_summary_maes_recomputed": True,
        "all_prior_only_choices_recomputed": True,
        "reference_sign_and_support_checked": True,
        "six_2026_models_reconstructed": reconstructed,
    }
    (OUT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
