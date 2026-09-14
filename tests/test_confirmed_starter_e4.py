from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from horse_racing.analysis.confirmed_starter_e3 import validate_pre_normalization
from horse_racing.analysis.confirmed_starter_e4 import (
    E4ContractError,
    boundary_state,
    decompose_race_nll,
    race_softmax_loss_grad_hess_diag,
    tie_and_rank_diagnostics,
    validate_win_output,
)


def _expected() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": [1, 1, 1, 1],
            "race_entry_id": [11, 12, 13, 14],
            "race_date_local": ["2026-03-01"] * 4,
            "horse_number": [1, 2, 3, 4],
            "outcome_state": ["normal_finish"] * 4,
            "win": [0, 1, 0, 0],
        }
    )


def _output(probabilities: list[float]) -> pl.DataFrame:
    return (
        _expected()
        .select("race_id", "race_entry_id", "horse_number")
        .with_columns(pl.Series("prob_win", probabilities))
    )


def test_pre_normalization_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        validate_pre_normalization(
            np.array([0.2, np.inf]), np.array([0.2, 0.8]), arm="N", target="win/raw"
        )


def test_exact_key_contract_rejects_a_deleted_prediction() -> None:
    with pytest.raises(E4ContractError, match="missing=1"):
        validate_win_output(_expected(), _output([0.4, 0.3, 0.2, 0.1]).head(3), name="N/raw")


def test_boundary_state_distinguishes_crossing_from_tie_group_end() -> None:
    crossing = boundary_state([0.5, 0.2, 0.2, 0.1], 2)
    ending = boundary_state([0.5, 0.5, 0.1, 0.0], 2)
    assert crossing["crosses_boundary"] is True
    assert crossing["tie_group_ends_at_boundary"] is False
    assert ending["crosses_boundary"] is False
    assert ending["tie_group_ends_at_boundary"] is True


def test_tie_diagnostic_separates_new_ties_from_strict_inversions() -> None:
    raw = _output([0.4, 0.3, 0.2, 0.1])
    calibrated = _output([0.35, 0.35, 0.2, 0.1])
    summary, per_race = tie_and_rank_diagnostics(_expected(), raw, calibrated)
    assert summary["strict_inversion_pairs"] == 0
    assert summary["raw_tie_pairs"] == 0
    assert summary["new_tie_pairs"] == 1
    assert per_race["top1_delta"].item() == pytest.approx(0.5)
    assert summary["top1_unexplained_changed_races"] == 0


def test_arithmetic_decomposition_is_an_exact_identity() -> None:
    def frame(value: float) -> pl.DataFrame:
        return pl.DataFrame({"race_id": [1], "winner_nll": [value], "contains_special_state": [0]})

    result, summary = decompose_race_nll(frame(2.0), frame(2.1), frame(1.9), frame(2.2))
    assert result["final_a_minus_final_n"].item() == pytest.approx(0.3)
    assert result["decomposed_delta"].item() == pytest.approx(0.3)
    assert summary["max_absolute_identity_error"] < 1e-15


def test_race_softmax_math_is_stable_invariant_and_matches_finite_difference() -> None:
    logits = np.array([1000.0, 999.0, -1000.0])
    labels = np.array([0.5, 0.5, 0.0])
    loss, gradient, hessian_diagonal = race_softmax_loss_grad_hess_diag(logits, labels)
    shifted_loss, shifted_gradient, shifted_hessian = race_softmax_loss_grad_hess_diag(
        logits + 12345.0, labels
    )
    assert np.isfinite([loss, *gradient, *hessian_diagonal]).all()
    assert shifted_loss == pytest.approx(loss)
    assert shifted_gradient == pytest.approx(gradient)
    assert shifted_hessian == pytest.approx(hessian_diagonal)
    assert gradient.sum() == pytest.approx(0.0, abs=1e-12)
    step = 1e-5
    for index in range(len(logits)):
        plus = logits.copy()
        minus = logits.copy()
        plus[index] += step
        minus[index] -= step
        plus_loss = race_softmax_loss_grad_hess_diag(plus, labels)[0]
        minus_loss = race_softmax_loss_grad_hess_diag(minus, labels)[0]
        numerical_gradient = (plus_loss - minus_loss) / (2 * step)
        assert numerical_gradient == pytest.approx(gradient[index], abs=1e-7)


def test_generated_e4_artifacts_reproduce_e3_and_preserve_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "data/experiments/confirmed_starter_e4_diagnostic_20260911"
    protocol = json.loads((output / "protocol.json").read_text(encoding="utf-8"))
    diagnostic = json.loads((output / "diagnostic.json").read_text(encoding="utf-8"))
    assert protocol["protocol_status"] == "written before diagnostic predictions or metrics"
    assert diagnostic["tree_training_performed"] is False
    assert diagnostic["candidate_reselection_performed"] is False
    assert diagnostic["input_hashes_unchanged"] is True
    assert diagnostic["validation_key_sha256"] == (
        "3021b9208fd99bb7c4bf70d014dd88875faf180a57dd660ef0cd53baa09413ba"
    )
    assert diagnostic["e3_reproduction"]["candidate_binary_nll_max_abs_error"] < 1e-12
    assert diagnostic["e3_reproduction"]["selected_prediction_max_abs_error"] < 1e-12
    assert diagnostic["arithmetic_decomposition"]["max_absolute_identity_error"] < 1e-12
    for arm in ("N", "A"):
        for method in ("raw", "sigmoid", "isotonic"):
            prediction = pl.read_parquet(output / "outputs" / f"{arm}_{method}.parquet")
            assert prediction.height == 3051
            assert prediction.select("race_id", "race_entry_id").n_unique() == 3051
            assert diagnostic["coverage"][arm][method]["max_race_sum_error"] < 1e-8
    decomposition = pl.read_parquet(output / "per_race_nll_decomposition.parquet")
    assert decomposition.height == 288
    assert decomposition.filter(pl.col("contains_special_state") == 1).height == 12
