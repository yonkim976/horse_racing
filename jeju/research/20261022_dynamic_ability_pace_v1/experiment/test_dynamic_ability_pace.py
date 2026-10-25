"""Synthetic numerical and fail-closed checks for dynamic_ability_pace.py."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def _must_fail(function, *args, **kwargs) -> None:
    try:
        function(*args, **kwargs)
    except (RuntimeError, ValueError, TypeError):
        return
    raise AssertionError(f"expected a fail-closed error from {getattr(function, '__name__', function)}")


def _finite_difference(function, point: np.ndarray, step: float = 1e-5) -> np.ndarray:
    result = np.empty_like(point, dtype=np.float64)
    for index in range(len(point)):
        plus, minus = point.copy(), point.copy()
        plus[index] += step
        minus[index] -= step
        result[index] = (function(plus) - function(minus)) / (2 * step)
    return result


def run_tests(engine: Any) -> dict[str, Any]:
    checks: list[str] = []

    # Full-field, sequential PL objective: gradient and diagonal Hessian.
    ranks = np.asarray([1, 4, 2, 3, 3, 1, 5, 2, 4], dtype=np.int64)
    groups = np.asarray([4, 5], dtype=np.int32)
    scores = np.asarray([0.3, -0.7, 0.15, 0.02, -0.1, 0.24, -0.35, 0.05, 0.12], dtype=np.float64)
    loss, gradient, hessian = engine.ordered_top3_pl_nll_grad_hess(scores, ranks, groups)
    fd_gradient = _finite_difference(lambda value: engine.ordered_top3_pl_nll(value, ranks, groups), scores)
    np.testing.assert_allclose(gradient, fd_gradient, rtol=2e-6, atol=2e-7)
    fd_hessian_diagonal = np.empty_like(scores)
    step = 1e-5
    for index in range(len(scores)):
        plus, minus = scores.copy(), scores.copy()
        plus[index] += step
        minus[index] -= step
        grad_plus = engine.ordered_top3_pl_nll_grad_hess(plus, ranks, groups)[1]
        grad_minus = engine.ordered_top3_pl_nll_grad_hess(minus, ranks, groups)[1]
        fd_hessian_diagonal[index] = (grad_plus[index] - grad_minus[index]) / (2 * step)
    np.testing.assert_allclose(hessian, fd_hessian_diagonal, rtol=2e-5, atol=2e-6)
    assert math.isfinite(loss)
    checks.append("ordered_top3_gradient_and_diagonal_hessian_finite_difference")

    # The callback supplies sum-of-race derivatives, then floors Hessian.
    class Dataset:
        def get_label(self):
            return ranks.astype(np.float64)

        def get_group(self):
            return groups

    callback_grad, callback_hess = engine.lightgbm_ordered_top3_objective(scores.copy(), Dataset())
    np.testing.assert_allclose(callback_grad, len(groups) * gradient, rtol=0, atol=1e-14)
    np.testing.assert_allclose(callback_hess, np.maximum(len(groups) * hessian, engine.HESSIAN_FLOOR),
                               rtol=0, atol=1e-14)
    closed = engine.make_lightgbm_ordered_top3_objective(ranks, groups)
    closure_grad, closure_hess = closed(scores.copy(), Dataset())
    np.testing.assert_allclose(closure_grad, callback_grad, rtol=0, atol=1e-14)
    np.testing.assert_allclose(closure_hess, callback_hess, rtol=0, atol=1e-14)
    checks.append("lightgbm_callback_sums_race_derivatives_before_hessian_floor")

    # Fractional rank, binary labels, race keys and temporal records fail closed.
    bad_ranks = ranks.astype(np.float64)
    bad_ranks[0] = 1.5
    _must_fail(engine.ordered_top3_pl_nll_grad_hess, scores, bad_ranks, groups)
    _must_fail(engine.observed_order_logprob, scores[:4], [1, 2.5, 3, 4])
    _must_fail(engine.scenario_design, [0.3, 0.5, 0.2], [0.1, 0.6, 0.4], 1.5)
    _must_fail(engine._exact_binary, 1.5, "synthetic binary")
    _must_fail(engine.validate_temporal_record,
               {"target_year": 2024, "train_max_year": 2023, "calibration_year": 2023,
                "prediction_year": 2024, "in_sample": False}, 2024)
    _must_fail(engine._string_key_series, pd.Series(["same", 3], dtype=object), "mixed race key")
    checks.append("fractional_labels_mixed_keys_and_temporal_leakage_rejected")

    # Gamma's exact 4x4 Hessian matches finite differences of its gradient.
    gamma_races = [
        {"ranks": np.asarray([1, 3, 2, 4]), "a": np.asarray([0.2, 0.0, -0.1, -0.3]),
         "p_early": np.asarray([0.8, 0.4, 0.3, 0.1]),
         "p_recovery": np.asarray([0.2, 0.5, 0.8, 0.3]), "z": 1},
        {"ranks": np.asarray([2, 1, 4, 3]), "a": np.asarray([0.0, 0.3, -0.2, 0.1]),
         "p_early": np.asarray([0.1, 0.7, 0.2, 0.4]),
         "p_recovery": np.asarray([0.6, 0.2, 0.5, 0.7]), "z": 0},
    ]
    gamma = np.asarray([0.07, -0.03, 0.05, -0.02], dtype=np.float64)
    gamma_loss, gamma_gradient, gamma_hessian = engine.conditional_gamma_objective_grad_hess(gamma, gamma_races)
    fd_gamma_grad = _finite_difference(
        lambda value: engine.conditional_gamma_objective_grad_hess(value, gamma_races)[0], gamma)
    np.testing.assert_allclose(gamma_gradient, fd_gamma_grad, rtol=3e-6, atol=2e-7)
    fd_gamma_hess = np.column_stack([
        _finite_difference(lambda value: engine.conditional_gamma_objective_grad_hess(value, gamma_races)[1][column],
                           gamma)
        for column in range(4)
    ])
    np.testing.assert_allclose(gamma_hessian, fd_gamma_hess, rtol=2e-5, atol=2e-6)
    assert math.isfinite(gamma_loss)
    _must_fail(engine.conditional_gamma_objective_grad_hess, gamma,
               [{**gamma_races[0], "ranks": [1, 2.5, 3, 4]}])
    checks.append("gamma_gradient_and_exact_hessian_finite_difference")

    # OOS provenance schema is checked as it will be in the B fit/calibration path.
    runner_oos = pd.DataFrame([
        {"race_id": "SYN-2019-A", "race_date": "2019-01-01", "year": 2019,
         "model_train_max_year": 2017, "calibration_year": 2018, "prediction_year": 2019,
         "in_sample": False, "api_record_id": ix, "horse_number": ix, "finish_position": rank,
         "a_utility": 0.1 * ix, "p_early": 0.2 + 0.1 * ix, "p_recovery": 0.7 - 0.1 * ix,
         "label_early": float(ix == 1), "label_recovery": float(ix == 2)}
        for ix, rank in enumerate((1, 2, 3), start=1)
    ])
    race_oos = pd.DataFrame([{
        "race_id": "SYN-2019-A", "race_date": "2019-01-01", "year": 2019,
        "model_train_max_year": 2017, "calibration_year": 2018, "prediction_year": 2019,
        "in_sample": False, "q_z": 0.4, engine.RACE_LABEL: 1,
    }])
    records, excluded = engine._oos_race_records(runner_oos, race_oos, require_observed_z=True)
    assert len(records) == 1 and excluded == 0 and records[0]["z"] == 1
    phase_diagnostics = engine._phase_prediction_diagnostics(runner_oos, race_oos)
    assert len(phase_diagnostics) == 6
    assert set(phase_diagnostics["head"]) == {"early", "recovery", "Z"}
    assert phase_diagnostics["mae_event_count_error"].ge(0).all()
    arm_runner = runner_oos.assign(temperature_a=1.0)
    arm_race = race_oos.iloc[0]
    scenarios, weights = engine._arm_scenarios(
        "B", arm_runner, arm_race, reference_scores=np.asarray([0.1, 0.2, 0.3]),
        reference_temperature=1.0,
        b_fit={"gamma": {"gamma": [0.2, -0.1, 0.1, 0.05]},
               "temperature_calibration": {"temperature": 1.2}},
    )
    assert len(scenarios) == 2 and len(weights) == 2 and abs(sum(weights) - 1.0) < 1e-15
    checks.append("annual_oos_provenance_phase_diagnostics_and_shared_scenario_arm")

    # Two-scenario mixture identities: complete Q masses and runner marginals.
    horse_numbers = np.arange(1, 9, dtype=np.int64)
    early = np.asarray([0.8, 0.6, 0.1, 0.3, 0.2, 0.5, 0.4, 0.2])
    recovery = np.asarray([0.1, 0.2, 0.7, 0.5, 0.8, 0.4, 0.3, 0.6])
    z0, z1 = engine.scenario_design(early, recovery, 0), engine.scenario_design(early, recovery, 1)
    base = np.linspace(0.3, -0.4, 8)
    gamma = np.asarray([0.2, -0.1, 2.0, -0.7])
    utilities = [base + z0 @ gamma, base + z1 @ gamma]
    maps, marginal, mass = engine.probability_maps_from_scenarios(utilities, [0.6, 0.4], horse_numbers, 3)
    assert abs(mass - 1.0) < 3e-11
    assert abs(sum(maps["TRI"].values()) - 1.0) < 5e-11
    assert abs(sum(maps["QPL"].values()) - 3.0) < 5e-11
    assert abs(sum(maps["PLC"].values()) - 3.0) < 5e-11
    assert abs(float(marginal["p_top3"].sum()) - 3.0) < 3e-11
    _must_fail(engine.truth_ticket_keys, "TRI", [1, 2, 3], [1, 2, 3], None)
    checks.append("shared_scenario_mixture_all_event_and_marginal_identities")

    # The 1e-12 selection tie is diagnostic only and returns chosen ticket p.
    chosen, chosen_probability = engine._selected_ticket({(2,): 0.5, (1,): 0.5 - 5e-13})
    assert chosen == (1,) and chosen_probability == 0.5 - 5e-13
    contract, quarantine = engine._race_contract_rows(pd.DataFrame([
        {"race_id": "SYN-N7", "race_date": "2024-01-01", "year": 2024, "field_n": 7},
        {"race_id": "SYN-N8", "race_date": "2024-01-02", "year": 2024, "field_n": 8},
        {"race_id": "SYN-N3", "race_date": "2024-01-03", "year": 2024, "field_n": 3},
    ]))
    assert len(quarantine) == 1 and quarantine.iloc[0]["race_id"] == "SYN-N7"
    assert contract.loc[contract["race_id"].eq("SYN-N3") & contract["pool"].eq("TRI"),
                        "event_label_status"].iloc[0] == "below_statutory_minimum"
    checks.append("selection_tie_and_legal_minimum_quarantine_contract")

    # Output confinement is checked without creating a file.
    _must_fail(engine.confined_output_path, "../../../../outside.json", allow_existing=True)
    checks.append("experiment_write_confinement")
    return {"status": "PASS_SYNTHETIC", "checks": checks, "check_count": len(checks)}
