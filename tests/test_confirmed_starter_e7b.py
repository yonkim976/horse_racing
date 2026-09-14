"""E7-B production preflight, gate and failure-boundary counterexamples."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from horse_racing.analysis.confirmed_starter_e5_r3r4 import diagnose_temperature
from horse_racing.analysis.confirmed_starter_e5b import E5BContractError
from horse_racing.analysis.confirmed_starter_e6a_v2 import prepare_diagnosed_arm
from horse_racing.analysis.confirmed_starter_e7a import FEATURES
from horse_racing.analysis.confirmed_starter_e7b import (
    ARMS,
    E7BContractError,
    evaluate_arm,
    orchestrate_fold,
    pooled_metrics,
    verify_sequence_contract,
    verify_shared_base_matrices,
)
from scripts import run_confirmed_starter_e7b as runner


def _flat():
    return diagnose_temperature(
        np.array([1.0, 1.0, 1.0, 1.0]),
        np.array([1.0, 0.0, 1.0, 0.0]),
        np.array([2, 2]),
    )


@pytest.mark.parametrize("failed_arm", ARMS)
def test_common_gate_rejects_either_prepare_failure_before_evaluation(failed_arm):
    events = []

    def prepare(arm):
        events.append(("prepare", arm))
        if arm == failed_arm:
            raise RuntimeError("temperature boundary")
        return prepare_diagnosed_arm(arm, _flat())

    with pytest.raises(E7BContractError, match="temperature boundary"):
        orchestrate_fold(ARMS, ARMS, prepare, lambda item: events.append(("evaluate", item.name)))
    assert all(stage != "evaluate" for stage, _ in events)


def test_gate_prepares_both_and_rejects_wrong_candidate_identity():
    events = []

    def prepare(arm):
        events.append(("prepare", arm))
        return prepare_diagnosed_arm(arm, _flat())

    def evaluate(item):
        assert events[:2] == [("prepare", arm) for arm in ARMS]
        events.append(("evaluate", item.name))
        return item.name

    assert orchestrate_fold(ARMS, ARMS, prepare, evaluate) == dict(zip(ARMS, ARMS, strict=True))
    with pytest.raises(E7BContractError, match="arm identities"):
        orchestrate_fold((ARMS[0], "CURRENT_WEIGHT_A_PREV"), ARMS, prepare, evaluate)


def test_148_column_matrix_rejects_changed_old_cell():
    base = {
        stage: np.ones((2, 136), dtype=np.float32)
        for stage in ("fit", "tune", "calibration", "evaluation")
    }
    added = {stage: np.ones((2, 148), dtype=np.float32) for stage in base}
    added["fit"][0, 0] = 3.0
    with pytest.raises(E7BContractError, match="existing 136"):
        verify_shared_base_matrices(base, added)


def test_sequence_contract_rejects_missing_key_and_filled_absent_slot():
    h1 = pl.read_parquet(runner.H1)
    sequence = pl.read_parquet(runner.SEQUENCE)
    evidence = pl.read_parquet(runner.EVIDENCE)
    with pytest.raises(E7BContractError, match="denominator"):
        verify_sequence_contract(h1, sequence.head(sequence.height - 1), evidence)
    absent_id = evidence.filter((pl.col("slot") == 1) & pl.col("prior_race_entry_id").is_null())[
        "race_entry_id"
    ][0]
    altered = sequence.with_columns(
        pl.when(pl.col("race_entry_id") == absent_id)
        .then(0.0)
        .otherwise(pl.col("sequence_start1_early_rel"))
        .alias("sequence_start1_early_rel")
    )
    with pytest.raises(E7BContractError, match="null isolation"):
        verify_sequence_contract(h1, altered, evidence)


def test_prediction_deletion_and_dead_heat_loss_are_distinct():
    expected = pl.DataFrame(
        {
            "race_id": [1, 1, 1],
            "race_entry_id": [10, 11, 12],
            "horse_number": [1, 2, 3],
            "race_date_local": ["2026-02-28"] * 3,
            "win": [1, 1, 0],
            "outcome_state": ["normal_finish"] * 3,
        }
    )
    predictions = pl.DataFrame(
        {
            "race_id": [1, 1, 1],
            "race_entry_id": [10, 11, 12],
            "horse_number": [1, 2, 3],
            "raw_margin": [1.0, 0.0, -1.0],
            "prob_win": [0.6652409557748218, 0.24472847105479764, 0.09003057317038045],
        }
    )
    with pytest.raises(E5BContractError, match="missing=1"):
        evaluate_arm(expected, predictions.head(2), temperature=1.0, name="deleted")
    result = evaluate_arm(expected, predictions, temperature=1.0, name="dead_heat")
    assert result["metrics"]["official_dead_heat_races"] == 1
    assert (
        result["metrics"]["race_equal_winner_set_nll"]
        < result["metrics"]["race_equal_soft_label_ce"]
    )


def test_pooled_comparison_cannot_use_success_only_fold():
    joined = pl.DataFrame({"race_id": [1], "prob_win": [1.0], "win": [1]})
    per_race = pl.DataFrame({"race_id": [1]})
    with pytest.raises(ValueError, match="denominator"):
        pooled_metrics(joined, per_race)


def test_runner_stops_current_fold_on_selector_failure(tmp_path, monkeypatch):
    part = pl.DataFrame({"race_id": [1, 1], "win": [1, 0]})
    parts = {stage: part for stage in ("fit", "tune", "calibration", "evaluation")}
    matrices = {
        ARMS[0]: {stage: np.zeros((2, 136), dtype=np.float32) for stage in parts},
        ARMS[1]: {stage: np.zeros((2, 148), dtype=np.float32) for stage in parts},
    }
    ledger = {"fit_calls_started": 0, "fit_calls_completed": 0, "events": []}

    def fail_selector(*args, **kwargs):
        raise RuntimeError("synthetic selector failure")

    monkeypatch.setattr(runner, "train_selector", fail_selector)
    with pytest.raises(E7BContractError, match="synthetic selector failure"):
        runner.run_fold(
            "F1",
            parts,
            matrices,
            [f"feature_{i}" for i in range(136)],
            {"categorical_features": []},
            tmp_path,
            ledger,
        )
    assert ledger["fit_calls_started"] == 1
    assert ledger["fit_calls_completed"] == 0
    assert not (tmp_path / "F1" / "comparison.json").exists()


def test_real_sealed_preflight_and_fold_inputs_without_fitting():
    runner.verify_sealed()
    frame, features, audit = runner.preflight_input()
    assert audit["evidence_rows"] == 46737
    assert len(FEATURES) == 12
    for fold, rows in (("F1", 1693), ("F2", 834), ("F3", 1691)):
        parts, matrices, contract = runner.fold_input(frame, features, fold)
        assert parts["evaluation"].height == rows
        assert matrices[ARMS[0]]["fit"].shape[1] == 136
        assert matrices[ARMS[1]]["fit"].shape[1] == 148
        assert contract["partitions"]["evaluation"]["dates"][1] <= "2026-02-28"


def test_baseline_reproduction_rejects_modified_saved_margin():
    fold = "F1"
    path = runner.OUTPUT_BASE / fold / ARMS[0]
    run = runner.json.loads((path / "run.json").read_text())
    result = {
        "best_iteration": run["best_iteration"],
        "calibration_predictions": pl.read_parquet(path / "calibration_predictions.parquet"),
        "evaluation_predictions": pl.read_parquet(path / "evaluation_predictions.parquet"),
        "evaluation": {"metrics": run["evaluation_metrics"]},
    }
    temperature = run["temperature"]["solution"]["temperature"]
    assert runner.baseline_reproduction(fold, result, temperature)["metric_max_abs_error"] == 0
    altered = dict(result)
    altered["evaluation_predictions"] = result["evaluation_predictions"].with_columns(
        pl.when(pl.int_range(pl.len()) == 0)
        .then(pl.col("raw_margin") + 1e-4)
        .otherwise(pl.col("raw_margin"))
        .alias("raw_margin")
    )
    with pytest.raises(E7BContractError, match="baseline evaluation predictions changed"):
        runner.baseline_reproduction(fold, altered, temperature)
