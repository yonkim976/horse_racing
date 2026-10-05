"""Recalculate filter rules, paired MAE, chronology and grade-test q values."""

from __future__ import annotations

import json

import analyze as study
import numpy as np
import pandas as pd


def main():
    saved = json.loads((study.OUT / "summary.json").read_text())
    assert all(
        study.sha(study.ROOT / path) == digest for path, digest in saved["inputs_sha256"].items()
    )
    original_horse = pd.read_parquet(study.OUT / "baseline/filter_ledger.parquet")
    original_race = pd.read_parquet(study.OUT / "baseline/race_residuals.parquet")
    sample_checks = 0
    for scenario in study.SCENARIOS:
        directory = study.OUT / scenario
        ledger = pd.read_parquet(directory / "filter_ledger.parquet")
        expected = ledger.residual.between(ledger.lower, ledger.upper)
        assert expected.eq(ledger.retained).all()
        assert int((~expected).sum()) == saved["scenarios"][scenario]["removed"]
        effect = pd.read_parquet(directory / "frozen_effects.parquet")
        assert not effect.duplicated(["part", "race_key"]).any()
        assert (effect.environment_trained_through < effect.year).all()
        if scenario != "baseline":
            source = original_race if scenario == "race_mad4" else original_horse
            for row in ledger.sample(12, random_state=20261002).itertuples():
                names = {
                    "distance_grade_year": ["meet", "part", "distance_m", "grade", "year"],
                    "distance_year": ["meet", "part", "distance_m", "year"],
                    "venue_year": ["meet", "part", "year"],
                }[row.context]
                mask = pd.Series(True, index=source.index)
                for name in names:
                    mask &= source[name].eq(getattr(row, name))
                values = source.loc[mask, "residual"].to_numpy(float)
                if scenario.startswith("horse_trim"):
                    tail = 0.01 if scenario == "horse_trim1" else 0.05
                    lo, hi = np.quantile(values, [tail, 1 - tail])
                else:
                    center = np.median(values)
                    sd = np.median(np.abs(values - center)) * 1.4826
                    floor = study.FLOORS[row.part] * (0.5 if scenario == "race_mad4" else 1)
                    lo, hi = center - 4 * max(sd, floor), center + 4 * max(sd, floor)
                assert np.allclose([lo, hi], [row.lower, row.upper], atol=1e-10)
                sample_checks += 1
        family = [r for r in saved["scenarios"][scenario]["grade_tests"] if "q" in r]
        assert np.allclose(study.bh([r["p"] for r in family]), [r["q"] for r in family])
    evaluation = pd.read_parquet(study.OUT / "prediction_evaluation.parquet")
    old = pd.read_parquet(
        study.RETRAIN_PATH / "outputs/quality_filtered/prediction_evaluation.parquet"
    )
    joined = evaluation.merge(
        old[study.KEY + ["part", "target", "prediction_raw", "prediction_distance"]],
        on=study.KEY + ["part"],
        validate="one_to_one",
        suffixes=("", "_old"),
    )
    assert len(joined) == len(evaluation) == len(old)
    assert np.array_equal(joined.target, joined.target_old)
    assert np.max(np.abs(joined.prediction_raw - joined.prediction_raw_old)) < 1e-8
    assert np.max(np.abs(joined.prediction_baseline_100 - joined.prediction_distance)) < 1e-8
    assert (evaluation.prediction_trained_through < evaluation.year).all()
    assert (evaluation.prev_date < evaluation.dt).all()
    assert (evaluation.prev2_date < evaluation.dt).all()
    for row in saved["prediction_summary"]:
        sample = evaluation[evaluation.meet.eq(row["meet"]) & evaluation.part.eq(row["part"])]
        if row["year"] != "all":
            sample = sample[sample.year.eq(int(row["year"]))]
        assert len(sample) == row["n"]
        for variant, mae in row["mae"].items():
            error = np.abs(sample.target - sample[f"prediction_{variant}"])
            assert np.isclose(error.mean(), mae)
            assert np.allclose(error, sample[f"err_{variant}"])
    for proposal in saved["retrospective_reference_proposals"]:
        if proposal["all_filters_supported_fast"]:
            low, high = proposal["add_seconds_025_050"]
            assert 0 <= low <= high <= proposal["upper_ci_cap_seconds"]
    result = {
        "passed": True,
        "input_hashes_match": True,
        "independently_recomputed_filter_thresholds": sample_checks,
        "retention_and_grade_q_reproduced": True,
        "source_and_prediction_models_prior_year_only": True,
        "same_evaluation_keys_and_untrimmed_targets": True,
        "raw_and_full_baseline_reproduced_within_1e_minus_8": True,
        "all_prediction_mae_recalculated": True,
        "reference_ranges_positive_and_capped": True,
        "finish_evaluation_rows": int(evaluation.part.eq("finish").sum()),
    }
    (study.OUT / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
