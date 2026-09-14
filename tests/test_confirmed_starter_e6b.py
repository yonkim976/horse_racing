"""E6-B execution-boundary and sealed-input regression checks."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from horse_racing.analysis.confirmed_starter_e5_r3r4 import diagnose_temperature
from horse_racing.analysis.confirmed_starter_e5b import E5BContractError
from horse_racing.analysis.confirmed_starter_e6a_v2 import prepare_diagnosed_arm
from horse_racing.analysis.confirmed_starter_e6b import (
    ARMS,
    PARTITIONS,
    E6BContractError,
    evaluate_arm,
    orchestrate_fold,
    partition_frame,
    pooled_metrics,
    verify_shared_base_matrices,
)
from scripts import run_confirmed_starter_e6b as runner
from scripts.run_confirmed_starter_e6b import fold_input, preflight_input, verify_sealed_files


def _flat_diagnosis():
    return diagnose_temperature(
        np.array([1.0, 1.0, 1.0, 1.0]),
        np.array([1.0, 0.0, 1.0, 0.0]),
        np.array([2, 2]),
    )


@pytest.mark.parametrize("failed_arm", ARMS)
def test_production_gate_never_evaluates_on_prepare_failure(failed_arm):
    events = []

    def prepare(arm):
        events.append(("prepare", arm))
        if arm == failed_arm:
            raise RuntimeError("sealed temperature failure")
        return prepare_diagnosed_arm(arm, _flat_diagnosis())

    with pytest.raises(E6BContractError, match="sealed temperature failure"):
        orchestrate_fold(ARMS, ARMS, prepare, lambda item: events.append(("evaluate", item.name)))
    assert not any(stage == "evaluate" for stage, _ in events)


def test_production_gate_prepares_both_before_evaluation():
    events = []

    def prepare(arm):
        events.append(("prepare", arm))
        return prepare_diagnosed_arm(arm, _flat_diagnosis())

    def evaluate(item):
        assert events[:2] == [("prepare", arm) for arm in ARMS]
        events.append(("evaluate", item.name))
        return item.name

    assert orchestrate_fold(ARMS, ARMS, prepare, evaluate) == dict(zip(ARMS, ARMS, strict=True))


def test_partition_rejects_missing_row_and_date_spill():
    frame = pl.DataFrame(
        {
            "race_date_local": ["2025-01-04", "2025-04-05", "2026-03-01"],
            "race_id": [1, 2, 3],
            "race_entry_id": [10, 20, 30],
        }
    )
    with pytest.raises(E6BContractError, match="count"):
        partition_frame(frame, "F1", "fit")
    assert PARTITIONS["F3"]["evaluation"][1] == "2026-02-28"


def test_shared_matrix_rejects_changed_old_predictor():
    base = {"fit": np.array([[1.0, np.nan]], dtype=np.float32)}
    added = {"fit": np.array([[2.0, np.nan, 4.0, 5.0, 6.0]], dtype=np.float32)}
    with pytest.raises(E6BContractError, match="136 matrix"):
        verify_shared_base_matrices(base, added)


def test_pooled_denominator_rejects_success_only_fold():
    joined = pl.DataFrame({"race_id": [1], "prob_win": [1.0], "win": [1]})
    race = pl.DataFrame({"race_id": [1]})
    with pytest.raises(E6BContractError, match="denominator"):
        pooled_metrics(joined, race)


def test_e6b_evaluation_rejects_deleted_prediction_row():
    expected = pl.DataFrame(
        {
            "race_id": [1, 1],
            "race_entry_id": [10, 11],
            "horse_number": [1, 2],
            "race_date_local": ["2025-06-01", "2025-06-01"],
            "win": [1, 0],
            "outcome_state": ["normal_finish", "normal_finish"],
        }
    )
    prediction = pl.DataFrame(
        {
            "race_id": [1, 1],
            "race_entry_id": [10, 11],
            "horse_number": [1, 2],
            "raw_margin": [0.0, 0.0],
            "prob_win": [0.5, 0.5],
        }
    )
    with pytest.raises(E5BContractError, match="missing=1"):
        evaluate_arm(expected, prediction.head(1), temperature=1.0, name="F1/deleted")


def test_runner_stops_fold_and_pooled_comparison_on_fit_failure(tmp_path, monkeypatch):
    part = pl.DataFrame({"race_id": [1, 1], "win": [1, 0]})
    parts = {stage: part for stage in PARTITIONS["F1"]}
    matrix = np.zeros((2, 136), dtype=np.float32)
    matrices = {arm: {stage: matrix for stage in parts} for arm in ARMS}
    ledger = {"fit_calls_started": 0, "fit_calls_completed": 0, "events": []}

    def fail_selector(*args, **kwargs):
        raise RuntimeError("synthetic selector failure")

    monkeypatch.setattr(runner, "train_selector", fail_selector)
    with pytest.raises(E6BContractError, match="synthetic selector failure"):
        runner.run_fold(
            "F1",
            parts,
            matrices,
            [f"feature_{index}" for index in range(136)],
            {"categorical_features": []},
            tmp_path,
            ARMS,
            ledger,
        )
    assert ledger["fit_calls_started"] == 1
    assert ledger["fit_calls_completed"] == 0
    assert not (tmp_path / "F1" / "comparison.json").exists()


def test_sealed_real_input_and_fold_encoding_contract():
    verify_sealed_files()
    frame, features, audit = preflight_input()
    assert audit["H1_rows"] == 15579
    parts, matrices, contracts = fold_input(frame, features, "F1")
    assert parts["evaluation"].height == 1693
    assert parts["evaluation"]["race_date_local"].max() == "2025-07-27"
    assert contracts["partitions"]["fit"]["rows"] == 2767
    assert matrices[ARMS[0]]["fit"].shape == (2767, 136)
    assert matrices[ARMS[1]]["fit"].shape == (2767, 139)
