from __future__ import annotations

import math

import polars as pl
import pytest

from horse_racing.analysis.confirmed_starter_e6a import (
    E6AContractError,
    PreparedCandidate,
    build_carried_weight_features,
    execute_two_candidate_gate,
)


def _prepared(name: str, status: str = "interior_optimum", temperature: float = 1.1):
    return PreparedCandidate(name, status, temperature, payload=name.lower())


@pytest.mark.parametrize("order", [("BINARY", "RACE_SOFTMAX"), ("RACE_SOFTMAX", "BINARY")])
def test_gate_evaluates_both_once_only_after_common_approval(order: tuple[str, str]) -> None:
    events: list[str] = []

    def prepare(name: str) -> PreparedCandidate:
        events.append(f"prepare:{name}")
        return _prepared(name, "flat_use_T1" if name == "BINARY" else "interior_optimum")

    def evaluate(candidate: PreparedCandidate) -> str:
        assert events[:2] == [f"prepare:{name}" for name in order]
        events.append(f"evaluate:{candidate.name}")
        return candidate.name

    result = execute_two_candidate_gate(order, prepare, evaluate)
    assert result.approved
    assert result.validation_call_count == 2
    assert set(result.validation_results) == {"BINARY", "RACE_SOFTMAX"}


def test_second_candidate_boundary_leaves_zero_validation_artifacts() -> None:
    calls: list[str] = []

    def prepare(name: str) -> PreparedCandidate:
        return _prepared(
            name, "boundary_logT_lower" if name == "RACE_SOFTMAX" else "interior_optimum"
        )

    result = execute_two_candidate_gate(
        ("BINARY", "RACE_SOFTMAX"), prepare, lambda candidate: calls.append(candidate.name)
    )
    assert not result.approved
    assert result.validation_call_count == 0
    assert result.validation_results == {}
    assert calls == []
    assert result.failure_reason == "temperature_status_invalid:RACE_SOFTMAX:boundary_logT_lower"


def test_first_candidate_failure_preserves_reason_and_skips_validation() -> None:
    def prepare(name: str) -> PreparedCandidate:
        if name == "BINARY":
            raise RuntimeError("selector failed")
        return _prepared(name)

    result = execute_two_candidate_gate(("BINARY", "RACE_SOFTMAX"), prepare, pytest.fail)
    assert not result.approved
    assert result.validation_call_count == 0
    assert result.failure_reason == "prepare_failed:RuntimeError:selector failed"


@pytest.mark.parametrize(
    "items,reason",
    [
        (("BINARY",), "candidate_set_invalid"),
        (("BINARY", "BINARY"), "candidate_set_invalid"),
    ],
)
def test_missing_or_duplicate_candidate_fails_closed(items: tuple[str, ...], reason: str) -> None:
    result = execute_two_candidate_gate(items, _prepared, pytest.fail)
    assert not result.approved and result.validation_call_count == 0
    assert result.failure_reason and result.failure_reason.startswith(reason)


@pytest.mark.parametrize("temperature", [math.nan, math.inf, 0.0, -1.0])
def test_nonfinite_or_nonpositive_temperature_fails_closed(temperature: float) -> None:
    result = execute_two_candidate_gate(
        ("BINARY", "RACE_SOFTMAX"),
        lambda name: _prepared(name, temperature=temperature if name == "RACE_SOFTMAX" else 1.0),
        pytest.fail,
    )
    assert not result.approved and result.validation_call_count == 0
    assert result.failure_reason and result.failure_reason.startswith("temperature_invalid")


def _target() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": [10, 10, 10],
            "race_entry_id": [100, 101, 102],
            "race_date_local": ["2026-05-01"] * 3,
            "horse_id": [1, 2, 3],
            "carried_weight_kg": [55.0, 57.0, None],
            "is_debut": [0, 1, 0],
            "win": [1, 0, 0],
            "outcome_state": ["normal_finish", "normal_finish", "started_dnf"],
        }
    )


def _history() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": [1, 2, 3, 10, 20],
            "race_entry_id": [11, 12, 13, 100, 200],
            "race_date_local": [
                "2026-03-01",
                "2026-04-01",
                "2026-04-15",
                "2026-05-01",
                "2026-06-01",
            ],
            "horse_id": [1, 1, 3, 1, 1],
            "carried_weight_kg": [54.0, None, 53.0, 55.0, 60.0],
            "start_state": [
                "normal_finish",
                "started_dnf",
                "unresolved",
                "normal_finish",
                "normal_finish",
            ],
            "finish_position": [2, 92, None, 1, 1],
        }
    )


def _build(target: pl.DataFrame, history: pl.DataFrame) -> pl.DataFrame:
    return build_carried_weight_features(target, history, history_start_date="2015-01-03").sort(
        "race_entry_id"
    )


def test_feature_contract_uses_A_mean_and_immediate_previous_actual_start() -> None:
    result = _build(_target(), _history())
    assert result["condition_carried_weight_rel_A"].to_list() == [-1.0, 1.0, None]
    assert result["valid_weight_count"].to_list() == [2, 2, 2]
    first = result.row(0, named=True)
    assert first["previous_start_history_status"] == "previous_actual_start_weight_missing"
    assert first["previous_actual_start_entry_id"] == 12
    assert first["condition_carried_weight_delta_prev_start"] is None
    assert result.row(1, named=True)["previous_start_history_status"].startswith(
        "actual_first_start"
    )
    assert result.row(2, named=True)["previous_start_history_status"] == (
        "prior_start_status_unresolved"
    )


def test_target_result_deletion_or_change_and_same_day_result_do_not_change_features() -> None:
    target = _target()
    history = _history()
    baseline = _build(target, history)
    changed_target = target.with_columns(
        (1 - pl.col("win")).alias("win"), pl.lit("disqualified").alias("outcome_state")
    )
    without_target_history = history.filter(pl.col("race_entry_id") != 100)
    same_day_changed = history.with_columns(
        pl.when(pl.col("race_entry_id") == 100)
        .then(92)
        .otherwise(pl.col("finish_position"))
        .alias("finish_position")
    )
    assert baseline.equals(_build(changed_target, history))
    assert baseline.equals(_build(target, without_target_history))
    assert baseline.equals(_build(target, same_day_changed))


def test_synthetic_future_row_and_input_order_do_not_change_features() -> None:
    baseline = _build(_target(), _history())
    future_changed = _history().with_columns(
        pl.when(pl.col("race_entry_id") == 200)
        .then(10.0)
        .otherwise(pl.col("carried_weight_kg"))
        .alias("carried_weight_kg")
    )
    assert baseline.equals(_build(_target().reverse(), future_changed.reverse()))


def test_feature_contract_rejects_duplicate_keys() -> None:
    target = pl.concat([_target(), _target().head(1)])
    with pytest.raises(E6AContractError, match="duplicate keys"):
        _build(target, _history())


@pytest.mark.parametrize("invalid_weight", [math.nan, math.inf, 44.9, 80.1])
def test_feature_contract_rejects_nonfinite_or_out_of_range_weights(
    invalid_weight: float,
) -> None:
    target = _target().with_columns(
        pl.when(pl.col("race_entry_id") == 100)
        .then(invalid_weight)
        .otherwise(pl.col("carried_weight_kg"))
        .alias("carried_weight_kg")
    )
    with pytest.raises(E6AContractError, match="finite and within"):
        _build(target, _history())

    history = _history().with_columns(
        pl.when(pl.col("race_entry_id") == 11)
        .then(invalid_weight)
        .otherwise(pl.col("carried_weight_kg"))
        .alias("carried_weight_kg")
    )
    with pytest.raises(E6AContractError, match="finite and within"):
        _build(_target(), history)
