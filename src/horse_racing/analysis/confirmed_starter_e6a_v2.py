"""Research-only E6-A v2 history and common-evaluation contracts."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from horse_racing.analysis.confirmed_starter_e5_r3r4 import (
    BETA_BOUNDS,
    TemperatureDiagnostic,
    diagnose_temperature,
)
from horse_racing.analysis.pre_race_field_contract import (
    OutcomeState,
    RunnerOutcome,
    classify_outcome,
)

KEY = ["race_id", "race_entry_id"]
ACTUAL = {"normal_finish", "started_dnf", "disqualified"}
UNRESOLVED = {"result_missing_or_unconfirmed", "unknown_special", "race_cancelled_or_void"}
MIN_WEIGHT, MAX_WEIGHT = 45.0, 80.0
LOG_T_BOUND = 4.0


class E6AV2ContractError(ValueError):
    """A sealed research boundary failed."""


@dataclass(frozen=True)
class PreparedArm:
    name: str
    temperature_diagnostic: TemperatureDiagnostic
    payload: Any = None


@dataclass(frozen=True)
class GateResult:
    approved: bool
    prepared_names: tuple[str, ...]
    validation_results: dict[str, Any]
    failure_reason: str | None
    validation_call_count: int


def load_sealed_protocol_candidates(path: Path, expected_sha256: str) -> tuple[str, str]:
    """Read the two arm identities only from a hash-verified protocol contract."""
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise E6AV2ContractError("E6-B protocol hash mismatch")
    document = json.loads(raw)
    names = tuple(document["candidate_names"])
    if (
        document.get("status") != "draft_not_executable"
        or len(names) != 2
        or len(set(names)) != 2
        or document.get("planned_fit_calls") != 12
    ):
        raise E6AV2ContractError("E6-B protocol candidate/budget contract invalid")
    return names


def prepare_diagnosed_arm(
    name: str, diagnostic: TemperatureDiagnostic, *, payload: Any = None
) -> PreparedArm:
    """Carry the existing calibration diagnosis intact into the common gate."""
    if not isinstance(diagnostic, TemperatureDiagnostic):
        raise E6AV2ContractError("validated temperature diagnosis required")
    return PreparedArm(name=name, temperature_diagnostic=diagnostic, payload=payload)


def prepare_calibrated_arm(
    name: str,
    calibration_logits: np.ndarray,
    calibration_winners: np.ndarray,
    calibration_groups: np.ndarray,
    *,
    payload: Any = None,
) -> PreparedArm:
    """Use the sealed temperature diagnosis and pass its exact result to the fold gate."""
    diagnostic = diagnose_temperature(calibration_logits, calibration_winners, calibration_groups)
    return prepare_diagnosed_arm(name, diagnostic, payload=payload)


def _failure(names: Sequence[str], reason: str) -> GateResult:
    return GateResult(False, tuple(names), {}, reason, 0)


def _temperature_failure(item: PreparedArm) -> str | None:
    diagnostic = item.temperature_diagnostic
    if not isinstance(diagnostic, TemperatureDiagnostic):
        return f"temperature_diagnostic_missing:{item.name}"
    solution = diagnostic.solution
    for label, point in (
        ("lower", diagnostic.lower_beta_endpoint),
        ("upper", diagnostic.upper_beta_endpoint),
        ("solution", solution),
    ):
        values = (
            point.beta,
            point.log_temperature,
            point.temperature,
            point.objective,
            point.derivative,
            point.second_derivative,
        )
        if not all(math.isfinite(value) for value in values):
            return f"temperature_nonfinite:{item.name}:{label}"
        if point.temperature <= 0 or point.beta <= 0:
            return f"temperature_nonpositive:{item.name}:{label}"
        if not math.isclose(point.beta * point.temperature, 1.0, rel_tol=1e-10):
            return f"temperature_beta_inconsistent:{item.name}:{label}"
        if not math.isclose(
            point.log_temperature, math.log(point.temperature), rel_tol=1e-10, abs_tol=1e-10
        ):
            return f"temperature_log_inconsistent:{item.name}:{label}"
    if not math.isclose(diagnostic.lower_beta_endpoint.beta, BETA_BOUNDS[0], rel_tol=1e-12):
        return f"temperature_lower_endpoint_invalid:{item.name}"
    if not math.isclose(diagnostic.upper_beta_endpoint.beta, BETA_BOUNDS[1], rel_tol=1e-12):
        return f"temperature_upper_endpoint_invalid:{item.name}"
    if diagnostic.status == "flat_use_T1":
        if (
            not diagnostic.structural_flat
            or diagnostic.approximate_flat_allowed
            or diagnostic.optimizer != "structural"
            or solution.temperature != 1.0
            or solution.beta != 1.0
        ):
            return f"flat_contract_invalid:{item.name}"
    elif diagnostic.status == "interior_optimum":
        if (
            diagnostic.structural_flat
            or not -LOG_T_BOUND < solution.log_temperature < LOG_T_BOUND
            or not diagnostic.lower_beta_endpoint.derivative < 0
            or not diagnostic.upper_beta_endpoint.derivative > 0
        ):
            return f"interior_contract_invalid:{item.name}"
    else:
        return f"temperature_status_invalid:{item.name}:{diagnostic.status}"
    return None


def execute_common_gate(
    expected_candidates: Sequence[str],
    candidate_order: Sequence[str],
    prepare: Callable[[str], PreparedArm],
    evaluate_validation: Callable[[PreparedArm], Any],
) -> GateResult:
    """Validate the sealed request before preparation and both diagnostics before evaluation."""
    expected = tuple(expected_candidates)
    requested = tuple(candidate_order)
    if len(expected) != 2 or len(set(expected)) != 2:
        return _failure((), "protocol_candidates_invalid")
    if len(requested) != 2 or Counter(requested) != Counter(expected):
        return _failure((), f"requested_candidates_invalid:{requested}")
    prepared: list[PreparedArm] = []
    for name in requested:
        try:
            item = prepare(name)
        except Exception as exc:  # noqa: BLE001 - preserve the rejected stage and reason
            return _failure([part.name for part in prepared], f"prepare_failed:{name}:{exc}")
        if not isinstance(item, PreparedArm) or item.name != name:
            returned_name = getattr(item, "name", None)
            return _failure(
                [part.name for part in prepared],
                f"prepared_identity_mismatch:requested={name},returned={returned_name}",
            )
        prepared.append(item)
    for item in prepared:
        if reason := _temperature_failure(item):
            return _failure([part.name for part in prepared], reason)
    results = {item.name: evaluate_validation(item) for item in prepared}
    return GateResult(True, tuple(requested), results, None, len(results))


def run_e6b_fold(
    protocol_candidates: Sequence[str],
    candidate_order: Sequence[str],
    prepare_selector_refit_calibration: Callable[[str], PreparedArm],
    evaluate_fold: Callable[[PreparedArm], Any],
) -> GateResult:
    """The sole E6-B fold evaluation boundary; no tree fits are implemented here."""
    return execute_common_gate(
        protocol_candidates, candidate_order, prepare_selector_refit_calibration, evaluate_fold
    )


def adapt_history_outcomes(frame: pl.DataFrame) -> pl.DataFrame:
    """Apply the sealed E1 classifier to dated DB history including conflicting evidence."""
    required = {
        *KEY,
        "finish_position",
        "rank_remark",
        "scratched",
        "disqualified",
        "race_status",
    }
    if missing := sorted(required - set(frame.columns)):
        raise E6AV2ContractError(f"history state source columns missing: {missing}")
    states = []
    for row in frame.select(*sorted(required)).iter_rows(named=True):
        state = classify_outcome(
            RunnerOutcome(
                race_id=int(row["race_id"]),
                race_entry_id=int(row["race_entry_id"]),
                finish_position=row["finish_position"],
                rank_remark=row["rank_remark"],
                scratched=bool(row["scratched"]),
                disqualified=bool(row["disqualified"]),
                race_void=row["race_status"] in {"cancelled", "void"},
            )
        )
        if row["race_status"] in {"cancelled", "void"}:
            if state is not OutcomeState.RACE_VOID:
                state = OutcomeState.UNKNOWN_SPECIAL
        elif row["race_status"] != "completed":
            state = (
                OutcomeState.RESULT_MISSING
                if state is OutcomeState.RESULT_MISSING
                else OutcomeState.UNKNOWN_SPECIAL
            )
        states.append(state.value)
    return frame.with_columns(pl.Series("start_state", states, dtype=pl.String))


def _check_keys(frame: pl.DataFrame, name: str) -> None:
    if frame.select(KEY).n_unique() != frame.height:
        raise E6AV2ContractError(f"{name}: duplicate key")


def _check_weight(frame: pl.DataFrame, name: str) -> None:
    invalid = frame.filter(
        pl.col("carried_weight_kg").is_not_null()
        & (
            ~pl.col("carried_weight_kg").is_finite()
            | ~pl.col("carried_weight_kg").is_between(MIN_WEIGHT, MAX_WEIGHT)
        )
    )
    if invalid.height:
        raise E6AV2ContractError(f"{name}: invalid carried weight")


def build_carried_weight_features_v2(
    targets: pl.DataFrame,
    history: pl.DataFrame,
    *,
    history_start_date: str,
) -> pl.DataFrame:
    """Use all-track, strictly earlier actual starts; unresolved newer evidence blocks fallback."""
    _check_keys(targets, "targets")
    _check_keys(history, "history")
    if targets.is_empty():
        raise E6AV2ContractError("empty targets")
    _check_weight(targets, "targets")
    history = history.filter(pl.col("race_date_local") < targets["race_date_local"].max())
    _check_weight(history, "relevant history")
    if history.filter(~pl.col("start_state").is_in(ACTUAL | UNRESOLVED | {"did_not_start"})).height:
        raise E6AV2ContractError("unsupported history state")
    race_stats = targets.group_by("race_id").agg(
        pl.col("carried_weight_kg").is_not_null().sum().alias("valid_weight_count"),
        pl.col("carried_weight_kg").mean().alias("valid_weight_mean_kg"),
    )
    base = targets.select(
        *KEY, "horse_id", "race_date_local", "carried_weight_kg", "is_debut"
    ).join(race_stats, on="race_id", validate="m:1")
    indexed: dict[int, list[dict[str, Any]]] = {}
    for row in history.sort("horse_id", "race_date_local", "race_id", "race_entry_id").iter_rows(
        named=True
    ):
        indexed.setdefault(int(row["horse_id"]), []).append(row)
    out = []
    for target in base.iter_rows(named=True):
        earlier = [
            row
            for row in indexed.get(int(target["horse_id"]), [])
            if row["race_date_local"] < target["race_date_local"]
        ]
        candidates = [row for row in earlier if row["start_state"] in ACTUAL | UNRESOLVED]
        latest_date = max((row["race_date_local"] for row in candidates), default=None)
        latest = [row for row in candidates if row["race_date_local"] == latest_date]
        confirmed = [row for row in earlier if row["start_state"] in ACTUAL]
        confirmed_date = max((row["race_date_local"] for row in confirmed), default=None)
        confirmed_latest = [row for row in confirmed if row["race_date_local"] == confirmed_date]
        reference = confirmed_latest[0] if len(confirmed_latest) == 1 else None
        selected = latest[0] if len(latest) == 1 and latest[0]["start_state"] in ACTUAL else None
        if len(latest) > 1:
            status = "same_day_previous_start_ambiguous"
        elif latest and latest[0]["start_state"] in UNRESOLVED:
            status = "newer_previous_start_unresolved"
        elif selected is not None and selected["carried_weight_kg"] is None:
            status = (
                "previous_actual_start_weight_unverified"
                if selected.get("weight_provenance_status") == "unverified"
                else "previous_actual_start_weight_missing"
            )
        elif selected is not None:
            status = "previous_actual_start_weight_observed"
        elif not earlier:
            status = "no_prior_db_entry_observed_range"
        else:
            status = "prior_db_entries_no_confirmed_actual"
        weight = target["carried_weight_kg"]
        prior_weight = None if selected is None else selected["carried_weight_kg"]
        count = target["valid_weight_count"]
        relative_status = (
            "all_missing"
            if count == 0
            else "insufficient_valid_count"
            if count < 2
            else "target_weight_missing"
            if weight is None
            else "computed_from_A_valid_weights"
        )
        out.append(
            {
                "race_id": target["race_id"],
                "race_entry_id": target["race_entry_id"],
                "condition_carried_weight_kg": weight,
                "condition_carried_weight_rel_A": (
                    weight - target["valid_weight_mean_kg"]
                    if relative_status == "computed_from_A_valid_weights"
                    else None
                ),
                "condition_carried_weight_delta_prev_start": (
                    weight - prior_weight
                    if weight is not None and prior_weight is not None
                    else None
                ),
                "valid_weight_count": count,
                "valid_weight_mean_kg": target["valid_weight_mean_kg"],
                "relative_weight_status": relative_status,
                "previous_actual_start_weight_kg": prior_weight,
                "previous_actual_start_date": None
                if selected is None
                else selected["race_date_local"],
                "previous_actual_start_entry_id": None
                if selected is None
                else selected["race_entry_id"],
                "previous_actual_start_state": None
                if selected is None
                else selected["start_state"],
                "previous_weight_provenance_status": None
                if selected is None
                else selected.get("weight_provenance_status"),
                "previous_start_history_status": status,
                "prior_db_row_count": len(earlier),
                "prior_normal_finish_count": sum(
                    row["start_state"] == "normal_finish" for row in earlier
                ),
                "is_debut_snapshot_flag": target["is_debut"],
                "reference_confirmed_prior_entry_id": None
                if reference is None
                else reference["race_entry_id"],
                "blocking_entry_id": latest[0]["race_entry_id"]
                if status == "newer_previous_start_unresolved"
                else None,
                "history_observed_start_date": history_start_date,
                "availability_status": "retrospective_only / availability_unverified",
            }
        )
    return pl.DataFrame(out).sort(KEY)
