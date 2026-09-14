from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from horse_racing.analysis.confirmed_starter_e5_r3r4 import (
    BETA_BOUNDS,
    E5R3R4ContractError,
    binary_loss_gradient_hessian,
    diagnose_temperature,
    fit_temperature,
    grouped_soft_label_ce,
)


def test_temperature_true_flat_uses_t1() -> None:
    diagnostic = diagnose_temperature(
        np.array([7.0, 7.0, -3.0, -3.0]), np.array([1, 0, 0, 1]), np.array([2, 2])
    )
    assert diagnostic.status == "flat_use_T1"
    assert diagnostic.structural_flat is True
    assert diagnostic.approximate_flat_allowed is False
    assert diagnostic.solution.temperature == 1.0


@pytest.mark.parametrize(
    ("logits", "winners", "expected_status"),
    [
        ([0.0, 0.01], [1, 0], "boundary_logT_upper"),
        ([0.0, 1.0], [0, 1], "boundary_logT_lower"),
        ([0.0, 1000.0], [0, 1], "boundary_logT_lower"),
    ],
)
def test_temperature_boundary_counterexamples_are_rejected(
    logits: list[float], winners: list[int], expected_status: str
) -> None:
    diagnostic = diagnose_temperature(np.array(logits), np.array(winners), np.array([2]))
    assert diagnostic.status == expected_status
    assert diagnostic.structural_flat is False
    with pytest.raises(E5R3R4ContractError, match="boundary"):
        fit_temperature(np.array(logits), np.array(winners), np.array([2]))


def test_temperature_known_interior_solution_is_one_over_log_two() -> None:
    logits = np.tile(np.array([1.0, 0.0]), 3)
    winners = np.array([1, 0, 1, 0, 0, 1])
    diagnostic = diagnose_temperature(logits, winners, np.array([2, 2, 2]))
    assert diagnostic.status == "interior_optimum"
    assert diagnostic.solution.temperature == pytest.approx(1.0 / math.log(2.0), abs=1e-10)
    assert diagnostic.solution.derivative == pytest.approx(0.0, abs=1e-12)


def test_temperature_distinguishes_near_boundary_interior_from_boundary() -> None:
    beta_low, beta_high = BETA_BOUNDS
    for target_beta in (beta_low * 1.01, beta_high * 0.99):
        difference = math.log(2.0) / target_beta
        logits = np.tile(np.array([difference, 0.0]), 3)
        winners = np.array([1, 0, 1, 0, 0, 1])
        diagnostic = diagnose_temperature(logits, winners, np.array([2, 2, 2]))
        assert diagnostic.status == "interior_optimum"
        assert diagnostic.solution.beta == pytest.approx(target_beta, rel=1e-9)

    boundary_difference = math.log(2.0) / (beta_high * 1.01)
    boundary_logits = np.tile(np.array([boundary_difference, 0.0]), 3)
    boundary = diagnose_temperature(boundary_logits, winners, np.array([2, 2, 2]))
    assert boundary.status == "boundary_logT_lower"


def test_temperature_dead_heat_small_difference_and_large_common_shift() -> None:
    logits = np.array([0.01, 0.0, -0.01, 0.2, 0.2, -0.4])
    winners = np.array([1, 1, 0, 1, 1, 0])
    groups = np.array([3, 3])
    baseline = diagnose_temperature(logits, winners, groups)
    moved = diagnose_temperature(
        logits + np.array([1e12, 1e12, 1e12, -1e12, -1e12, -1e12]),
        winners,
        groups,
    )
    assert moved.status == baseline.status
    assert moved.lower_beta_endpoint.objective == pytest.approx(
        baseline.lower_beta_endpoint.objective, abs=1e-6
    )


def test_binary_weighted_derivatives_match_finite_difference_and_extremes() -> None:
    logits = np.array([-40.0, -0.3, 0.7, 41.0])
    labels = np.array([1.0, 0.0, 1.0, 0.0])
    weights = np.array([0.5, 0.5, 0.25, 0.25])
    loss, gradient, hessian = binary_loss_gradient_hessian(logits, labels, weights)
    assert np.isfinite([loss, *gradient, *hessian]).all()
    step = 1e-5
    numerical_gradient = np.empty(4)
    numerical_hessian = np.empty(4)
    for index in range(4):
        plus = logits.copy()
        minus = logits.copy()
        plus[index] += step
        minus[index] -= step
        plus_loss, plus_gradient, _ = binary_loss_gradient_hessian(plus, labels, weights)
        minus_loss, minus_gradient, _ = binary_loss_gradient_hessian(minus, labels, weights)
        numerical_gradient[index] = (plus_loss - minus_loss) / (2 * step)
        numerical_hessian[index] = (plus_gradient[index] - minus_gradient[index]) / (2 * step)
    assert numerical_gradient == pytest.approx(gradient, abs=1e-9)
    assert numerical_hessian == pytest.approx(hessian, abs=1e-9)


def test_raw_margin_metric_preserves_positive_and_negative_saturation_counterexamples() -> None:
    labels = np.array([1, 0])
    groups = np.array([2])
    assert grouped_soft_label_ce(np.array([40.0, 41.0]), labels, groups) == pytest.approx(
        1.3132616875182228
    )
    assert grouped_soft_label_ce(np.array([-40.0, -41.0]), labels, groups) == pytest.approx(
        0.31326168751822286
    )


def test_generated_r3r4_spike_uses_raw_callbacks_and_real_weight_policy() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "data/experiments/confirmed_starter_e5a_r3_r4_20260912"
    callback = json.loads((output / "callback_evidence.json").read_text(encoding="utf-8"))
    temperature = json.loads((output / "temperature_evidence.json").read_text(encoding="utf-8"))
    assert callback["actual_horse_data_used"] is False
    assert callback["extreme_raw_margin_checks"]["positive_40_41"]["matches"] is True
    assert callback["extreme_raw_margin_checks"]["negative_40_41"]["matches"] is True
    assert callback["candidates"]["BINARY"]["weight_policy"] == "1/field_size"
    assert callback["candidates"]["RACE_SOFTMAX"]["weight_policy"] == "weight=None"
    for candidate in ("BINARY", "RACE_SOFTMAX"):
        item = callback["candidates"][candidate]
        assert item["callback_matches_raw_margin"] is True
        assert item["only_primary_metric"] is True
        assert item["reload_raw_max_abs_error"] == 0.0
        assert item["reload_probability_max_abs_error"] == 0.0
    assert temperature["after"]["upper_counterexample"]["status"] == "boundary_logT_upper"
    assert temperature["after"]["lower_counterexample"]["status"] == "boundary_logT_lower"
    assert temperature["after"]["known_interior"]["status"] == "interior_optimum"
