"""E6-A evaluation gate and retrospective carried-weight feature contract."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import polars as pl

KEY_COLUMNS = ["race_id", "race_entry_id"]
EXPECTED_CANDIDATES = frozenset({"BINARY", "RACE_SOFTMAX"})
APPROVED_TEMPERATURE_STATES = frozenset({"interior_optimum", "flat_use_T1"})
ACTUAL_START_STATES = frozenset({"normal_finish", "started_dnf", "disqualified"})
MIN_RELATIVE_WEIGHT_OBSERVATIONS = 2
MIN_VALID_WEIGHT_KG = 45.0
MAX_VALID_WEIGHT_KG = 80.0


class E6AContractError(ValueError):
    """Raised when an E6-A execution or feature contract fails."""


@dataclass(frozen=True)
class PreparedCandidate:
    name: str
    temperature_status: str
    temperature: float
    payload: Any = None


@dataclass(frozen=True)
class EvaluationGateResult:
    approved: bool
    prepared_names: tuple[str, ...]
    validation_results: dict[str, Any]
    failure_reason: str | None
    validation_call_count: int


def execute_two_candidate_gate(
    candidate_order: Sequence[str],
    prepare: Callable[[str], PreparedCandidate],
    evaluate_validation: Callable[[PreparedCandidate], Any],
) -> EvaluationGateResult:
    """Prepare both candidates, then cross the validation boundary exactly once each."""
    prepared: list[PreparedCandidate] = []
    try:
        for requested_name in candidate_order:
            prepared.append(prepare(requested_name))
    except Exception as exc:  # noqa: BLE001 - failure reason is part of the sealed contract
        return EvaluationGateResult(
            False,
            tuple(item.name for item in prepared),
            {},
            f"prepare_failed:{type(exc).__name__}:{exc}",
            0,
        )
    names = [item.name for item in prepared]
    if len(names) != len(EXPECTED_CANDIDATES) or set(names) != EXPECTED_CANDIDATES:
        return EvaluationGateResult(
            False,
            tuple(names),
            {},
            f"candidate_set_invalid:expected={sorted(EXPECTED_CANDIDATES)},observed={names}",
            0,
        )
    for item in prepared:
        if item.temperature_status not in APPROVED_TEMPERATURE_STATES:
            return EvaluationGateResult(
                False,
                tuple(names),
                {},
                f"temperature_status_invalid:{item.name}:{item.temperature_status}",
                0,
            )
        if not math.isfinite(item.temperature) or item.temperature <= 0.0:
            return EvaluationGateResult(
                False,
                tuple(names),
                {},
                f"temperature_invalid:{item.name}:{item.temperature}",
                0,
            )
    results = {item.name: evaluate_validation(item) for item in prepared}
    return EvaluationGateResult(True, tuple(names), results, None, len(results))


def _validate_unique_keys(frame: pl.DataFrame, *, name: str) -> None:
    missing = [column for column in KEY_COLUMNS if column not in frame.columns]
    if missing:
        raise E6AContractError(f"{name}: missing key columns={missing}")
    duplicates = frame.group_by(KEY_COLUMNS).len().filter(pl.col("len") != 1)
    if duplicates.height:
        raise E6AContractError(f"{name}: duplicate keys={duplicates.height}")


def _validate_weight_values(frame: pl.DataFrame, *, name: str) -> None:
    invalid = frame.filter(
        pl.col("carried_weight_kg").is_not_null()
        & (
            ~pl.col("carried_weight_kg").is_finite()
            | ~pl.col("carried_weight_kg").is_between(
                MIN_VALID_WEIGHT_KG, MAX_VALID_WEIGHT_KG, closed="both"
            )
        )
    )
    if invalid.height:
        raise E6AContractError(
            f"{name}: non-null carried_weight_kg must be finite and within "
            f"[{MIN_VALID_WEIGHT_KG}, {MAX_VALID_WEIGHT_KG}]"
        )


def build_carried_weight_features(
    targets: pl.DataFrame,
    history: pl.DataFrame,
    *,
    history_start_date: str,
    availability_status: str = "retrospective_only / availability_unverified",
) -> pl.DataFrame:
    """Build the three frozen E6-A candidates without reading target outcomes."""
    target_required = {
        *KEY_COLUMNS,
        "race_date_local",
        "horse_id",
        "carried_weight_kg",
        "is_debut",
    }
    history_required = {
        *KEY_COLUMNS,
        "race_date_local",
        "horse_id",
        "carried_weight_kg",
        "start_state",
    }
    if missing := sorted(target_required - set(targets.columns)):
        raise E6AContractError(f"targets: missing columns={missing}")
    if missing := sorted(history_required - set(history.columns)):
        raise E6AContractError(f"history: missing columns={missing}")
    _validate_unique_keys(targets, name="targets")
    _validate_unique_keys(history, name="history")
    _validate_weight_values(targets, name="targets")
    max_target_date = targets["race_date_local"].max()
    relevant_history = history.filter(pl.col("race_date_local") < max_target_date)
    _validate_weight_values(relevant_history, name="history")
    valid_history_states = ACTUAL_START_STATES | {"not_started", "unresolved"}
    invalid_states = history.filter(~pl.col("start_state").is_in(valid_history_states))
    if invalid_states.height:
        raise E6AContractError("history contains unsupported start_state")

    target_core = targets.select(
        *KEY_COLUMNS,
        "race_date_local",
        "horse_id",
        "carried_weight_kg",
        "is_debut",
    ).sort("race_date_local", "race_id", "race_entry_id", maintain_order=True)
    race_summary = target_core.group_by("race_id").agg(
        pl.col("carried_weight_kg").is_not_null().sum().alias("valid_weight_count"),
        pl.col("carried_weight_kg").mean().alias("valid_weight_mean_kg"),
    )
    target_core = target_core.join(race_summary, on="race_id", validate="m:1")
    target_core = target_core.with_columns(
        pl.when(
            pl.col("carried_weight_kg").is_not_null()
            & (pl.col("valid_weight_count") >= MIN_RELATIVE_WEIGHT_OBSERVATIONS)
        )
        .then(pl.col("carried_weight_kg") - pl.col("valid_weight_mean_kg"))
        .otherwise(None)
        .alias("condition_carried_weight_rel_A"),
        pl.when(pl.col("valid_weight_count") == 0)
        .then(pl.lit("all_missing"))
        .when(pl.col("valid_weight_count") < MIN_RELATIVE_WEIGHT_OBSERVATIONS)
        .then(pl.lit("insufficient_valid_count"))
        .when(pl.col("carried_weight_kg").is_null())
        .then(pl.lit("target_weight_missing"))
        .otherwise(pl.lit("computed_from_A_valid_weights"))
        .alias("relative_weight_status"),
    )

    history_rows = relevant_history.select(
        *KEY_COLUMNS,
        "race_date_local",
        "horse_id",
        "carried_weight_kg",
        "start_state",
    ).sort("horse_id", "race_date_local", "race_id", "race_entry_id", maintain_order=True)
    by_horse: dict[int, list[dict[str, Any]]] = {}
    for row in history_rows.iter_rows(named=True):
        by_horse.setdefault(int(row["horse_id"]), []).append(row)

    previous_weights: list[float | None] = []
    previous_dates: list[str | None] = []
    previous_entry_ids: list[int | None] = []
    previous_states: list[str | None] = []
    history_statuses: list[str] = []
    for target in target_core.iter_rows(named=True):
        earlier = [
            row
            for row in by_horse.get(int(target["horse_id"]), [])
            if row["race_date_local"] < target["race_date_local"]
        ]
        actual = [row for row in earlier if row["start_state"] in ACTUAL_START_STATES]
        prior = actual[-1] if actual else None
        if prior is not None:
            status = (
                "previous_actual_start_weight_observed"
                if prior["carried_weight_kg"] is not None
                else "previous_actual_start_weight_missing"
            )
        elif any(row["start_state"] == "unresolved" for row in earlier):
            status = "prior_start_status_unresolved"
        elif target["is_debut"] == 1:
            status = "actual_first_start_retrospective_observed_range"
        else:
            status = "history_left_truncated_or_unobserved"
        previous_weights.append(None if prior is None else prior["carried_weight_kg"])
        previous_dates.append(None if prior is None else prior["race_date_local"])
        previous_entry_ids.append(None if prior is None else int(prior["race_entry_id"]))
        previous_states.append(None if prior is None else str(prior["start_state"]))
        history_statuses.append(status)

    result = target_core.with_columns(
        pl.col("carried_weight_kg").alias("condition_carried_weight_kg"),
        pl.Series("previous_actual_start_weight_kg", previous_weights, dtype=pl.Float64),
        pl.Series("previous_actual_start_date", previous_dates, dtype=pl.String),
        pl.Series("previous_actual_start_entry_id", previous_entry_ids, dtype=pl.Int64),
        pl.Series("previous_actual_start_state", previous_states, dtype=pl.String),
        pl.Series("previous_start_history_status", history_statuses, dtype=pl.String),
    ).with_columns(
        pl.when(
            pl.col("carried_weight_kg").is_not_null()
            & pl.col("previous_actual_start_weight_kg").is_not_null()
        )
        .then(pl.col("carried_weight_kg") - pl.col("previous_actual_start_weight_kg"))
        .otherwise(None)
        .alias("condition_carried_weight_delta_prev_start"),
        pl.lit(history_start_date).alias("history_observed_start_date"),
        pl.lit(availability_status).alias("availability_status"),
    )
    return result.select(
        *KEY_COLUMNS,
        "condition_carried_weight_kg",
        "condition_carried_weight_rel_A",
        "condition_carried_weight_delta_prev_start",
        "valid_weight_count",
        "valid_weight_mean_kg",
        "relative_weight_status",
        "previous_actual_start_weight_kg",
        "previous_actual_start_date",
        "previous_actual_start_entry_id",
        "previous_actual_start_state",
        "previous_start_history_status",
        "history_observed_start_date",
        "availability_status",
    )
