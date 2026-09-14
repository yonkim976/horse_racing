from __future__ import annotations

import json
import math
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl
import pytest

from horse_racing.analysis.confirmed_starter_e5 import (
    CallbackEvidence,
    E5ContractError,
    NativeRaceSoftmaxObjective,
    fit_temperature,
    grouped_soft_label_ce,
    grouped_softmax,
    normalize_soft_labels,
    race_softmax_derivatives,
    race_softmax_objective_arrays,
    soft_labels_from_winners,
)


def test_shifted_ce_fixes_large_common_shift_counterexample() -> None:
    q = np.array([0.5, 0.5])
    baseline = race_softmax_derivatives(np.array([0.0, 0.0]), q)
    shifted = race_softmax_derivatives(np.array([1e16, 1e16]), q)
    assert baseline.loss == pytest.approx(math.log(2.0))
    assert shifted.loss == pytest.approx(math.log(2.0))
    assert shifted.gradient == pytest.approx(baseline.gradient)
    assert shifted.full_hessian == pytest.approx(baseline.full_hessian)


def test_q_sum_uses_absolute_only_tolerance_and_normalizes_accepted_rounding() -> None:
    with pytest.raises(E5ContractError, match="outside absolute tolerance"):
        normalize_soft_labels(np.array([0.5, 0.500001]))
    accepted = normalize_soft_labels(np.array([0.5, 0.5 + 5e-13]))
    assert accepted.sum() == 1.0
    derivatives = race_softmax_derivatives(np.array([0.2, -0.1]), accepted)
    assert derivatives.gradient.sum() == pytest.approx(0.0, abs=1e-15)


def test_gradient_and_full_hessian_match_independent_central_differences() -> None:
    logits = np.array([0.8, -0.4, 0.2])
    q = np.array([0.5, 0.5, 0.0])
    result = race_softmax_derivatives(logits, q)
    step = 1e-5
    numerical_gradient = np.empty(3)
    numerical_hessian = np.empty((3, 3))
    for index in range(3):
        plus = logits.copy()
        minus = logits.copy()
        plus[index] += step
        minus[index] -= step
        plus_result = race_softmax_derivatives(plus, q)
        minus_result = race_softmax_derivatives(minus, q)
        numerical_gradient[index] = (plus_result.loss - minus_result.loss) / (2 * step)
        numerical_hessian[:, index] = (plus_result.gradient - minus_result.gradient) / (2 * step)
    assert numerical_gradient == pytest.approx(result.gradient, abs=1e-9)
    assert numerical_hessian == pytest.approx(result.full_hessian, abs=1e-9)
    assert result.exact_hessian_diagonal == pytest.approx(np.diag(result.full_hessian))


def test_multigroup_permutations_and_distinct_group_shifts_are_invariant() -> None:
    logits = np.array([0.4, -0.1, 1.2, 0.3, -0.7])
    winners = np.array([1, 0, 0, 1, 1])
    groups = np.array([2, 3])
    baseline_loss = grouped_soft_label_ce(logits, winners, groups)
    baseline_probabilities = grouped_softmax(logits, groups)
    shifted = logits + np.array([1e8, 1e8, -1e8, -1e8, -1e8])
    assert grouped_soft_label_ce(shifted, winners, groups) == pytest.approx(baseline_loss)
    assert grouped_softmax(shifted, groups) == pytest.approx(baseline_probabilities)

    within_permutation = np.array([1, 0, 4, 2, 3])
    assert grouped_soft_label_ce(
        logits[within_permutation], winners[within_permutation], groups
    ) == pytest.approx(baseline_loss)
    race_permutation = np.array([2, 3, 4, 0, 1])
    assert grouped_soft_label_ce(
        logits[race_permutation], winners[race_permutation], np.array([3, 2])
    ) == pytest.approx(baseline_loss)


def test_single_dead_heat_extremes_and_hessian_floor_are_explicit() -> None:
    winners = np.array([1, 0, 0, 1, 1, 1])
    groups = np.array([3, 3])
    q = soft_labels_from_winners(winners, groups)
    assert q[:3].tolist() == [1.0, 0.0, 0.0]
    assert q[3:].tolist() == pytest.approx([1 / 3, 1 / 3, 1 / 3])
    logits = np.array([1000.0, 0.0, -1000.0, 1000.0, 1000.0, 1000.0])
    gradient, hessian, evidence = race_softmax_objective_arrays(
        logits, winners, groups, weights=np.ones(6)
    )
    assert np.isfinite([*gradient, *hessian]).all()
    assert (hessian >= 1e-6).all()
    assert evidence["hessian_floor_count"] >= 2
    assert evidence["q_group_sums"] == [1.0, 1.0]


@pytest.mark.parametrize(
    ("logits", "winners", "groups", "message"),
    [
        (np.array([]), np.array([]), np.array([]), "groups must be"),
        (np.array([0.0, 1.0]), np.array([1, 0]), np.array([1]), "does not match"),
        (np.array([0.0, 1.0]), np.array([0, 0]), np.array([2]), "at least one"),
        (np.array([0.0, 1.0]), np.array([1, -1]), np.array([2]), "zero or one"),
        (np.array([0.0, np.inf]), np.array([1, 0]), np.array([2]), "finite"),
    ],
)
def test_invalid_math_and_group_inputs_are_rejected(
    logits: np.ndarray, winners: np.ndarray, groups: np.ndarray, message: str
) -> None:
    with pytest.raises(E5ContractError, match=message):
        race_softmax_objective_arrays(logits, winners, groups, weights=np.ones(logits.size))


def test_native_objective_rejects_dataset_without_explicit_group() -> None:
    dataset = lgb.Dataset(np.array([[0.0], [1.0]]), label=np.array([1, 0]))
    dataset.construct()
    objective = NativeRaceSoftmaxObjective(CallbackEvidence())
    with pytest.raises(E5ContractError, match="explicit Dataset group"):
        objective(np.zeros(2), dataset)


def test_float64_representation_loss_is_not_claimed_recoverable() -> None:
    lost = np.array([1e16, 1e16 + 1.0])
    assert lost[0] == lost[1]
    result = race_softmax_derivatives(lost, np.array([1.0, 0.0]))
    assert result.loss == pytest.approx(math.log(2.0))
    representable = np.array([1e16, np.nextafter(1e16, np.inf)])
    assert representable[0] != representable[1]
    assert race_softmax_derivatives(representable, np.array([1.0, 0.0])).loss > math.log(2.0)


def test_temperature_policy_uses_t1_for_flat_scores_and_interior_for_signal() -> None:
    groups = np.array([3, 3])
    winners = np.array([1, 0, 0, 0, 1, 0])
    flat = fit_temperature(np.zeros(6), winners, groups)
    assert flat.status == "flat_use_T1"
    assert flat.temperature == 1.0
    signal = fit_temperature(np.array([1.0, 0.2, -0.2, 0.1, 1.2, -0.4]), winners, groups)
    assert signal.status == "interior_optimum"
    assert math.exp(-4) < signal.temperature < math.exp(4)


def test_generated_e5a_spike_uses_public_api_and_reload_is_exact() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "data/experiments/confirmed_starter_e5a_20260912"
    evidence = json.loads((output / "callback_evidence.json").read_text(encoding="utf-8"))
    bundle = json.loads((output / "synthetic_bundle.json").read_text(encoding="utf-8"))
    assert evidence["actual_horse_data_used"] is False
    assert evidence["synthetic"]["races"] == 40
    assert evidence["synthetic"]["winner_counts"] == [1, 2, 3]
    assert evidence["frozen_hashes_unchanged"] is True
    assert bundle["reload_exact"] is True
    for candidate in ("BINARY", "RACE_SOFTMAX"):
        item = evidence["candidates"][candidate]
        assert item["public_training_api"] == "lightgbm.train"
        assert item["default_metric_disabled"] is True
        assert list(item["best_score"]["tune"]) == ["race_equal_soft_label_ce"]
        assert item["reload"]["raw_margin_max_abs_error"] == 0.0
        assert item["reload"]["probability_max_abs_error"] == 0.0
        assert item["probability_max_race_sum_error"] < 1e-12
    assert evidence["candidates"]["BINARY"]["callback_evidence"]["objective_call_count"] == 0
    assert evidence["candidates"]["RACE_SOFTMAX"]["callback_evidence"]["objective_call_count"] > 0
    assert evidence["candidates"]["BINARY"]["round_one_callback_matches_normal_prediction_hash"]
    assert evidence["candidates"]["RACE_SOFTMAX"]["round_one_callback_matches_raw_prediction_hash"]
    predictions = pl.read_parquet(output / "synthetic_predictions.parquet")
    assert predictions.height == 2 * evidence["synthetic"]["tune_rows"]
    assert {
        type(lgb.Booster(model_file=str(output / value["path"])))
        for value in bundle["candidate_models"].values()
    } == {lgb.Booster}
