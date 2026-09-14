from __future__ import annotations

import json
import math
from pathlib import Path

import polars as pl
import pytest

from horse_racing.analysis.confirmed_starter_e3 import (
    E3ContractError,
    evaluate_validation,
    paired_bootstrap,
    paired_date_cluster_bootstrap,
    sha256_file,
    validate_predictions,
)
from horse_racing.analysis.experiments import get_run, load_runs
from horse_racing.analysis.metrics import expected_topk_inclusion


def _expected() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": [1, 1, 1, 1],
            "race_entry_id": [11, 12, 13, 14],
            "race_date_local": ["2026-03-01"] * 4,
            "horse_number": [1, 2, 3, 4],
            "outcome_state": ["normal_finish"] * 4,
            "win": [1, 0, 0, 0],
            "top2": [1, 1, 0, 0],
            "top3": [1, 1, 1, 0],
        }
    )


def _predictions() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": [1, 1, 1, 1],
            "race_entry_id": [11, 12, 13, 14],
            "horse_number": [1, 2, 3, 4],
            "prob_win": [0.4, 0.3, 0.2, 0.1],
            "prob_top2": [0.7, 0.6, 0.4, 0.3],
            "prob_top3": [0.9, 0.8, 0.7, 0.6],
        }
    )


def test_expected_topk_complete_and_boundary_ties_are_hand_calculable() -> None:
    assert expected_topk_inclusion([0.25] * 4, [1, 0, 0, 0], k=1) == pytest.approx(0.25)
    assert expected_topk_inclusion([0.25] * 4, [1, 0, 0, 0], k=3) == pytest.approx(0.75)
    probabilities = [0.9, 0.8, 0.8, 0.8]
    labels = [0, 1, 0, 0]
    assert expected_topk_inclusion(probabilities, labels, k=2) == pytest.approx(1 / 3)
    assert expected_topk_inclusion(probabilities, labels, k=3) == pytest.approx(2 / 3)


def test_official_dead_heat_uses_summed_winner_event_probability() -> None:
    expected = _expected().with_columns(pl.Series("win", [0, 1, 1, 0]))
    joined, _ = validate_predictions(expected, _predictions(), name="dead-heat")
    metrics, races = evaluate_validation(joined)
    assert metrics["official_dead_heat_races"] == 1
    assert races["winner_probability"].item() == pytest.approx(0.5)
    assert metrics["race_equal_weight_winner_set_nll"] == pytest.approx(-math.log(0.5))


def test_topk_metrics_ignore_input_order() -> None:
    joined, _ = validate_predictions(_expected(), _predictions(), name="ordered")
    original = evaluate_validation(joined)[0]
    for reordered in (joined.reverse(), joined.sample(fraction=1.0, shuffle=True, seed=17)):
        result = evaluate_validation(reordered)[0]
        for name in (
            "top1_winner_inclusion",
            "top3_winner_inclusion",
            "top5_winner_inclusion",
        ):
            assert result[name] == pytest.approx(original[name])


def test_prediction_validation_rejects_missing_and_bad_probability_sum() -> None:
    with pytest.raises(E3ContractError, match="missing=1"):
        validate_predictions(_expected(), _predictions().head(3), name="missing")
    bad = _predictions().with_columns((pl.col("prob_win") * 0.9).alias("prob_win"))
    with pytest.raises(E3ContractError, match="race-sum error"):
        validate_predictions(_expected(), bad, name="bad-sum")


def test_paired_bootstraps_are_reproducible_and_keep_date_blocks() -> None:
    paired = pl.DataFrame(
        {
            "race_date": ["2026-03-01", "2026-03-01", "2026-03-02"],
            "delta_a_minus_n": [-0.1, 0.2, -0.3],
        }
    )
    assert paired_bootstrap(paired, iterations=50, seed=7) == paired_bootstrap(
        paired, iterations=50, seed=7
    )
    clustered = paired_date_cluster_bootstrap(paired, iterations=50, seed=7)
    assert clustered == paired_date_cluster_bootstrap(paired, iterations=50, seed=7)
    assert clustered["blocks"] == 2


def test_generated_e3_artifacts_preserve_denominator_and_isolated_registry() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "data/experiments/confirmed_starter_e3_20260911"
    protocol = json.loads((output / "protocol.json").read_text())
    comparison = json.loads((output / "comparison.json").read_text())
    assert protocol["input"]["dataset_sha256"] == (
        "9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7"
    )
    assert protocol["common_validation"]["rows"] == 3051
    assert protocol["common_validation"]["races"] == 288
    assert protocol["created_before_training"] is True

    paired = pl.read_parquet(output / "paired_race_winner_nll.parquet")
    assert paired.height == 288
    assert paired.filter(pl.col("contains_special_state") == 1).height == 12
    for arm in ("N", "A"):
        run_id = comparison["run_ids"][arm]
        run_dir = output / run_id
        predictions = pl.read_parquet(run_dir / "predictions_valid.parquet")
        assert predictions.height == 3051
        assert predictions.select("race_id", "race_entry_id").n_unique() == 3051
        assert comparison["coverage"][arm]["coverage"] == 1.0
        assert comparison["reload_prediction"][arm]["exactly_equal"] is True
        for target in ("win", "top2", "top3"):
            assert (run_dir / f"{target}_estimator.pkl").is_file()
            assert (run_dir / f"{target}_calibrator.pkl").is_file()
        component_manifest = json.loads((run_dir / "artifact_manifest.json").read_text())
        for relative_path, expected_hash in component_manifest.items():
            assert sha256_file(root / relative_path) == expected_hash
        assert get_run(run_id) is None

    for bootstrap in comparison["bootstrap"].values():
        lower, upper = bootstrap["percentile_95_ci"]
        assert lower < 0 < upper
    research_runs = load_runs(ledger_path=output / "model_runs.jsonl")
    assert {run.run_id for run in research_runs} == set(comparison["run_ids"].values())
    artifact_manifest = json.loads((output / "artifact_manifest.json").read_text())
    for relative_path, expected_hash in artifact_manifest.items():
        assert sha256_file(root / relative_path) == expected_hash
