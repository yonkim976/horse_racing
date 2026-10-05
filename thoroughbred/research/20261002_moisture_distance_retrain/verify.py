"""Independently check saved chronology, identity, paired errors and one fold."""

from __future__ import annotations

import json

import analyze as study
import numpy as np
import pandas as pd


def main():
    summary = json.loads((study.OUT / "summary.json").read_text())
    for path, digest in summary["inputs_sha256"].items():
        assert study.sha(study.ROOT / path) == digest
    results = {}
    for scenario in summary["scenarios"]:
        directory = study.OUT / scenario
        features = pd.read_parquet(directory / "historical_features.parquet")
        evaluation = pd.read_parquet(directory / "prediction_evaluation.parquet")
        effects = pd.read_parquet(directory / "frozen_effects.parquet")
        assert not evaluation.duplicated(study.KEY + ["part"]).any()
        assert (evaluation.prediction_trained_through < evaluation.year).all()
        assert (features.prev_date < features.dt).all()
        assert (features.prev2_date < features.dt).all()
        assert (effects.environment_trained_through < effects.year).all()
        for ordinal in ("prev", "prev2"):
            assert (
                features[f"{ordinal}_environment_trained_through"]
                < features[f"{ordinal}_date"].dt.year
            ).all()
        for variant in study.VARIANTS:
            assert np.allclose(
                evaluation[f"err_{variant}"],
                np.abs(evaluation.target - evaluation[f"prediction_{variant}"]),
            )
        for row in summary["scenarios"][scenario]["overall"]:
            mask = evaluation.meet.eq(row["meet"]) & evaluation.part.eq(row["part"])
            if row["year"] != "all":
                mask &= evaluation.year.eq(int(row["year"]))
            sample = evaluation[mask]
            assert len(sample) == row["n"]
            for variant in study.VARIANTS:
                assert np.isclose(sample[f"err_{variant}"].mean(), row["mae"][variant])
        # Reconstruct the 2024 finish fold. Current results and moisture metadata
        # are deliberately changed to prove that they cannot affect predictions.
        largest_difference = 0.0
        for meet in (1, 3):
            one = features[features.meet.eq(meet) & features.part.eq("finish")]
            train, test = one[one.year.lt(2024)], one[one.year.eq(2024)].copy()
            mutated = test.copy()
            mutated["target"], mutated["finish"], mutated["rank"] = -9999, 9999, 99
            mutated["moisture"], mutated["band"] = 99, "unobserved"
            expected = evaluation[
                evaluation.meet.eq(meet) & evaluation.part.eq("finish") & evaluation.year.eq(2024)
            ].set_index(study.KEY)
            for variant in study.VARIANTS:
                inputs = []
                for frame in (train, test, mutated):
                    x = frame[study.BASE.EXPECT_CAT + study.BASE.EXPECT_NUM].copy()
                    if variant != "raw":
                        for ordinal in ("prev", "prev2"):
                            x[f"{ordinal}_time"] -= frame[f"{ordinal}_effect_{variant}"]
                    inputs.append(x)
                model = study.BASE.ridge_model(study.BASE.EXPECT_CAT, study.BASE.EXPECT_NUM, 20)
                model.fit(inputs[0], train.target)
                predictions, perturbed = model.predict(inputs[1]), model.predict(inputs[2])
                assert np.array_equal(predictions, perturbed)
                recorded = expected.loc[
                    pd.MultiIndex.from_frame(test[study.KEY]), f"prediction_{variant}"
                ].to_numpy()
                difference = float(np.max(np.abs(predictions - recorded)))
                assert difference < 1e-8
                largest_difference = max(largest_difference, difference)
        results[scenario] = {
            "prediction_rows": len(evaluation),
            "finish_rows": int(evaluation.part.eq("finish").sum()),
            "current_outcome_and_moisture_perturbation_invariant": True,
            "reconstructed_2024_finish_max_prediction_difference": largest_difference,
            "chronology_identity_uniqueness_and_saved_mae": "passed",
        }
    output = {"input_hashes_match": True, "scenarios": results}
    (study.OUT / "independent_verification.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2)
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
