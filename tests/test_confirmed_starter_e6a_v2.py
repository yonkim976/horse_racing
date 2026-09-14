from __future__ import annotations

import hashlib
import math
from dataclasses import replace

import numpy as np
import polars as pl
import pytest

from horse_racing.analysis.confirmed_starter_e5_r3r4 import diagnose_temperature
from horse_racing.analysis.confirmed_starter_e6a_v2 import (
    adapt_history_outcomes,
    build_carried_weight_features_v2,
    load_sealed_protocol_candidates,
    prepare_calibrated_arm,
    prepare_diagnosed_arm,
    run_e6b_fold,
)

ARMS = ("BASE_136", "CURRENT_WEIGHT_A_PREV")


def _diagnosis(flat: bool = False):
    if flat:
        return diagnose_temperature(
            np.array([1.0, 1.0, 1.0, 1.0]),
            np.array([1.0, 0.0, 1.0, 0.0]),
            np.array([2, 2]),
        )
    return diagnose_temperature(
        np.array([1.0, 0.0] * 3),
        np.array([1.0, 0.0, 1.0, 0.0, 0.0, 1.0]),
        np.array([2, 2, 2]),
    )


def test_real_calibration_prepare_preserves_diagnostic():
    scores = np.array([1.0, 1.0, 1.0, 1.0])
    winners = np.array([1.0, 0.0, 1.0, 0.0])
    groups = np.array([2, 2])
    item = prepare_calibrated_arm(ARMS[0], scores, winners, groups)
    assert item.temperature_diagnostic == diagnose_temperature(scores, winners, groups)
    assert item.temperature_diagnostic.status == "flat_use_T1"
    assert item.temperature_diagnostic.solution.temperature == 1.0


def test_hash_sealed_protocol_supplies_arm_names(tmp_path):
    content = (
        b'{"status":"draft_not_executable","candidate_names":'
        b'["BASE_136","CURRENT_WEIGHT_A_PREV"],"planned_fit_calls":12}'
    )
    path = tmp_path / "protocol.json"
    path.write_bytes(content)
    names = load_sealed_protocol_candidates(path, hashlib.sha256(content).hexdigest())
    assert names == ARMS
    with pytest.raises(ValueError, match="hash mismatch"):
        load_sealed_protocol_candidates(path, "0" * 64)


@pytest.mark.parametrize("order", [ARMS, ARMS[::-1]])
def test_fold_gate_prepares_both_before_any_evaluation(order):
    events = []
    interior = _diagnosis()
    flat = _diagnosis(flat=True)

    def prepare(name):
        events.append(("prepare", name))
        return prepare_diagnosed_arm(name, flat if name == ARMS[0] else interior)

    def evaluate(item):
        assert events[:2] == [("prepare", name) for name in order]
        events.append(("evaluate", item.name))
        return item.name

    result = run_e6b_fold(ARMS, order, prepare, evaluate)
    assert result.approved and result.validation_call_count == 2
    assert {name for phase, name in events if phase == "evaluate"} == set(ARMS)


@pytest.mark.parametrize("order", [ARMS, ARMS[::-1]])
def test_fold_gate_first_or_second_prepare_failure_evaluates_zero(order):
    calls = []

    def prepare(name):
        if name == ARMS[1]:
            raise RuntimeError("calibration boundary")
        return prepare_diagnosed_arm(name, _diagnosis())

    result = run_e6b_fold(ARMS, order, prepare, lambda item: calls.append(item.name))
    assert not result.approved and result.validation_call_count == 0 and calls == []
    assert "calibration boundary" in result.failure_reason


@pytest.mark.parametrize("order", [(ARMS[0],), (ARMS[0], ARMS[0]), (*ARMS, "EXTRA")])
def test_invalid_request_never_prepares(order):
    calls = []
    result = run_e6b_fold(ARMS, order, lambda name: calls.append(name), lambda item: pytest.fail())
    assert not result.approved and calls == []


def test_returned_candidate_name_swap_is_rejected():
    evaluations = []
    result = run_e6b_fold(
        ARMS,
        ARMS,
        lambda name: prepare_diagnosed_arm(ARMS[1] if name == ARMS[0] else name, _diagnosis()),
        lambda item: evaluations.append(item.name),
    )
    assert not result.approved and evaluations == []
    assert "identity_mismatch" in result.failure_reason


@pytest.mark.parametrize(
    "bad_solution",
    [
        {"temperature": 1.1},
        {"temperature": math.nan},
        {"temperature": math.inf},
        {"temperature": 0.0},
        {"temperature": -1.0},
    ],
)
def test_flat_temperature_must_be_exact_T1_and_diagnosed(bad_solution):
    flat = _diagnosis(flat=True)
    bad = replace(flat, solution=replace(flat.solution, **bad_solution))
    calls = []
    result = run_e6b_fold(
        ARMS,
        ARMS,
        lambda name: prepare_diagnosed_arm(name, bad if name == ARMS[1] else flat),
        lambda item: calls.append(item.name),
    )
    assert not result.approved and calls == []


def test_interior_temperature_out_of_range_rejected():
    interior = _diagnosis()
    bad = replace(
        interior,
        solution=replace(
            interior.solution,
            beta=1e-10,
            log_temperature=math.log(1e10),
            temperature=1e10,
        ),
    )
    calls = []
    result = run_e6b_fold(
        ARMS,
        ARMS,
        lambda name: prepare_diagnosed_arm(name, bad if name == ARMS[1] else interior),
        lambda item: calls.append(item.name),
    )
    assert not result.approved and calls == []


def _targets():
    return pl.DataFrame(
        {
            "race_id": [30, 30],
            "race_entry_id": [300, 301],
            "race_date_local": ["2026-05-01"] * 2,
            "horse_id": [1, 2],
            "carried_weight_kg": [55.0, 56.0],
            "is_debut": [0, 1],
        }
    )


def _raw_history(states, weights=None):
    weights = weights or [52.0] * len(states)
    dates = ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"]
    ranks = {
        "normal": (2, None, False, False, "completed"),
        "dnf": (92, "주행중지", False, False, "completed"),
        "dq": (91, "실격", False, True, "completed"),
        "not_started": (95, "출전취소", True, False, "completed"),
        "unresolved": (None, None, False, False, "completed"),
        "conflict": (92, "주행중지", True, False, "completed"),
        "void": (99, "경주취소", False, False, "cancelled"),
    }
    rows = []
    for i, state in enumerate(states):
        position, remark, scratched, disqualified, race_status = ranks[state]
        rows.append(
            {
                "race_id": 10 + i,
                "race_entry_id": 100 + i,
                "race_date_local": dates[i],
                "horse_id": 1,
                "carried_weight_kg": weights[i],
                "finish_position": position,
                "rank_remark": remark,
                "scratched": scratched,
                "disqualified": disqualified,
                "race_status": race_status,
            }
        )
    return adapt_history_outcomes(pl.DataFrame(rows))


@pytest.mark.parametrize(
    "states,status,delta",
    [
        (["normal", "unresolved"], "newer_previous_start_unresolved", None),
        (["unresolved", "normal"], "previous_actual_start_weight_observed", 3.0),
        (["normal", "not_started"], "previous_actual_start_weight_observed", 3.0),
        (["normal", "conflict"], "newer_previous_start_unresolved", None),
        (["normal", "void"], "newer_previous_start_unresolved", None),
        (["normal", "dnf"], "previous_actual_start_weight_observed", 3.0),
        (["normal", "dq"], "previous_actual_start_weight_observed", 3.0),
    ],
)
def test_actual_source_adapter_and_history_state_counterexamples(states, status, delta):
    history = _raw_history(states)
    row = (
        build_carried_weight_features_v2(_targets(), history, history_start_date="2015-01-02")
        .filter(pl.col("race_entry_id") == 300)
        .row(0, named=True)
    )
    assert row["previous_start_history_status"] == status
    assert row["condition_carried_weight_delta_prev_start"] == delta


def test_immediate_previous_null_weight_and_same_day_ambiguity():
    history = _raw_history(["normal", "normal"], [51.0, None])
    row = (
        build_carried_weight_features_v2(_targets(), history, history_start_date="2015-01-02")
        .filter(pl.col("race_entry_id") == 300)
        .row(0, named=True)
    )
    assert row["previous_start_history_status"] == "previous_actual_start_weight_missing"
    assert row["condition_carried_weight_delta_prev_start"] is None
    duplicate_day = history.with_columns(
        pl.when(pl.col("race_entry_id") == 101)
        .then(pl.lit("2026-01-01"))
        .otherwise(pl.col("race_date_local"))
        .alias("race_date_local")
    )
    row = (
        build_carried_weight_features_v2(_targets(), duplicate_day, history_start_date="2015-01-02")
        .filter(pl.col("race_entry_id") == 300)
        .row(0, named=True)
    )
    assert row["previous_start_history_status"] == "same_day_previous_start_ambiguous"
    assert row["condition_carried_weight_delta_prev_start"] is None


def test_target_results_future_rows_and_input_order_cannot_change_features():
    targets = _targets().with_columns(pl.lit(1).alias("win"))
    history = _raw_history(["normal", "not_started"])
    baseline = build_carried_weight_features_v2(targets, history, history_start_date="2015-01-02")
    future = history.head(1).with_columns(
        pl.lit(999).alias("race_id"),
        pl.lit(999).alias("race_entry_id"),
        pl.lit("2026-06-01").alias("race_date_local"),
        pl.lit(80.0).alias("carried_weight_kg"),
    )
    changed = build_carried_weight_features_v2(
        targets.drop("win").reverse(),
        pl.concat([history.reverse(), future], how="vertical_relaxed"),
        history_start_date="2015-01-02",
    )
    assert baseline.equals(changed)
