"""Research-only contracts for sealed pre-race fields and official outcomes.

The sealed field is independent of predictions and results. This module is not
wired into the operating dataset or prediction paths.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite, log


class FieldContractError(ValueError):
    """Raised when a field or outcome event cannot be validated."""


class FieldMembership(StrEnum):
    INCLUDED = "included_at_prediction"
    EXCLUDED_PRE_CUTOFF = "excluded_before_prediction"
    INCLUDED_POST_CUTOFF_WITHDRAWAL = "included_then_withdrawn"
    UNKNOWN = "unknown"


class OutcomeState(StrEnum):
    NORMAL_FINISH = "normal_finish"
    STARTED_DNF = "started_dnf"
    DISQUALIFIED = "disqualified"
    DID_NOT_START = "did_not_start"
    RESULT_MISSING = "result_missing_or_unconfirmed"
    RACE_VOID = "race_cancelled_or_void"
    UNKNOWN_SPECIAL = "unknown_special"


@dataclass(frozen=True, slots=True)
class SealedFieldManifest:
    """Independent, immutable statement of the complete field at one cutoff."""

    snapshot_id: str
    source_id: str
    race_id: int
    cutoff_at_ms: int
    sealed_at_ms: int
    expected_keys: tuple[tuple[int, int], ...]
    complete: bool
    completeness_basis: str


@dataclass(frozen=True, slots=True)
class FieldEvidence:
    race_id: int
    race_entry_id: int
    horse_number: int
    snapshot_id: str
    entry_observed_at_ms: int | None
    withdrawal_observed_at_ms: int | None = None
    withdrawal_published_at_ms: int | None = None
    withdrawal_effective_at_ms: int | None = None


@dataclass(frozen=True, slots=True)
class RunnerOutcome:
    race_id: int
    race_entry_id: int
    finish_position: int | None
    rank_remark: str | None = None
    scratched: bool = False
    disqualified: bool = False
    race_void: bool = False


@dataclass(frozen=True, slots=True)
class RunnerLabels:
    is_scored: bool
    win: bool | None
    top2: bool | None
    top3: bool | None
    auxiliary_rank_is_observed: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class TopKEvent:
    """Validated official TopK membership and ordered-loss availability."""

    official_entry_ids: tuple[int, ...]
    official_membership_complete: bool
    unique_ordered_entry_ids: tuple[int, ...] | None
    ordered_loss_scoreable: bool
    has_dead_heat_at_or_before_k: bool


SPECIAL_OUTCOMES = {
    (91, "실격"): OutcomeState.DISQUALIFIED,
    (92, "주행중지"): OutcomeState.STARTED_DNF,
    (93, "출발제외"): OutcomeState.DID_NOT_START,
    (94, "경주제외"): OutcomeState.DID_NOT_START,
    (95, "출전취소"): OutcomeState.DID_NOT_START,
    (99, "경주취소"): OutcomeState.RACE_VOID,
}


def validate_exact_keyset(
    expected: Iterable[tuple[int, int]], observed: Iterable[tuple[int, int]]
) -> None:
    """Reject duplicates, missing keys, and extras before any join."""
    expected_list = list(expected)
    observed_list = list(observed)
    if len(expected_list) != len(set(expected_list)):
        raise FieldContractError("expected field contains duplicate race/entry keys")
    if len(observed_list) != len(set(observed_list)):
        raise FieldContractError("observed field contains duplicate race/entry keys")
    missing = sorted(set(expected_list) - set(observed_list))
    extra = sorted(set(observed_list) - set(expected_list))
    if missing or extra:
        raise FieldContractError(f"field key mismatch: missing={missing[:10]}, extra={extra[:10]}")


def validate_sealed_field(field: SealedFieldManifest) -> None:
    """Validate an independent field manifest before selecting or scoring."""
    if not field.snapshot_id or not field.source_id or not field.completeness_basis:
        raise FieldContractError("sealed field requires snapshot/source/completeness evidence")
    if not field.complete:
        raise FieldContractError("sealed field is not marked complete")
    if field.sealed_at_ms != field.cutoff_at_ms:
        raise FieldContractError("field must be sealed at its declared cutoff")
    if not field.expected_keys:
        raise FieldContractError("sealed field has no expected keys")
    validate_exact_keyset(field.expected_keys, field.expected_keys)
    wrong_races = sorted(
        {race_id for race_id, _ in field.expected_keys if race_id != field.race_id}
    )
    if wrong_races:
        raise FieldContractError(f"sealed field contains other race IDs: {wrong_races}")


def resolve_field_membership(evidence: FieldEvidence, *, cutoff_at_ms: int) -> FieldMembership:
    """Resolve membership from information availability, never effective time alone."""
    if evidence.entry_observed_at_ms is None or evidence.entry_observed_at_ms > cutoff_at_ms:
        return FieldMembership.UNKNOWN

    observed = evidence.withdrawal_observed_at_ms
    published = evidence.withdrawal_published_at_ms
    effective = evidence.withdrawal_effective_at_ms
    if observed is None and published is None and effective is None:
        return FieldMembership.INCLUDED
    if observed is None and published is None:
        return FieldMembership.UNKNOWN
    if observed is not None and published is not None and observed < published:
        return FieldMembership.UNKNOWN

    known_at = published if published is not None else observed
    if known_at is None:
        return FieldMembership.UNKNOWN
    if known_at <= evidence.entry_observed_at_ms:
        return FieldMembership.UNKNOWN
    if known_at <= cutoff_at_ms:
        if effective is None or effective <= cutoff_at_ms:
            return FieldMembership.EXCLUDED_PRE_CUTOFF
        return FieldMembership.INCLUDED_POST_CUTOFF_WITHDRAWAL
    if effective is not None and effective > cutoff_at_ms:
        return FieldMembership.INCLUDED_POST_CUTOFF_WITHDRAWAL
    if effective is not None and effective <= cutoff_at_ms:
        return FieldMembership.INCLUDED
    return FieldMembership.UNKNOWN


def select_pre_race_field(
    sealed_field: SealedFieldManifest,
    evidence_rows: Iterable[FieldEvidence],
) -> tuple[FieldEvidence, ...]:
    """Validate actual snapshot rows against an independent sealed F_t manifest."""
    validate_sealed_field(sealed_field)
    rows = tuple(evidence_rows)
    observed_keys = [(row.race_id, row.race_entry_id) for row in rows]
    validate_exact_keyset(sealed_field.expected_keys, observed_keys)
    invalid_snapshot = [
        row.race_entry_id
        for row in rows
        if row.snapshot_id != sealed_field.snapshot_id or row.race_id != sealed_field.race_id
    ]
    if invalid_snapshot:
        raise FieldContractError(f"rows do not belong to sealed snapshot: {invalid_snapshot[:10]}")
    memberships = [
        resolve_field_membership(row, cutoff_at_ms=sealed_field.cutoff_at_ms) for row in rows
    ]
    invalid_membership = [
        row.race_entry_id
        for row, membership in zip(rows, memberships, strict=True)
        if membership
        not in {FieldMembership.INCLUDED, FieldMembership.INCLUDED_POST_CUTOFF_WITHDRAWAL}
    ]
    if invalid_membership:
        raise FieldContractError(
            f"sealed F_t has excluded or unknown membership: {invalid_membership[:10]}"
        )
    return rows


def pre_race_field_features(
    sealed_field: SealedFieldManifest,
    field_rows: Iterable[FieldEvidence],
    *,
    strong_front_entry_ids: Iterable[int] = (),
) -> dict[int, dict[str, float | int]]:
    """Compute field-dependent examples strictly from a validated sealed F_t."""
    rows = select_pre_race_field(sealed_field, field_rows)
    starters = len(rows)
    front = set(strong_front_entry_ids)
    unknown_front = front - {row.race_entry_id for row in rows}
    if unknown_front:
        raise FieldContractError(f"front-runner keys are outside F_t: {sorted(unknown_front)}")
    front_count = len(front)
    return {
        row.race_entry_id: {
            "starters_at_prediction": starters,
            "horse_number_pct": row.horse_number / starters,
            "front_runner_count": front_count,
            "front_rival_count": front_count - int(row.race_entry_id in front),
        }
        for row in rows
    }


def classify_outcome(outcome: RunnerOutcome) -> OutcomeState:
    """Classify only compatible code/remark/flag combinations."""
    position = outcome.finish_position
    remark = (outcome.rank_remark or "").strip() or None
    if position is None:
        if remark is not None or outcome.scratched or outcome.disqualified or outcome.race_void:
            return OutcomeState.UNKNOWN_SPECIAL
        return OutcomeState.RESULT_MISSING
    if 1 <= position <= 89:
        if remark is not None or outcome.scratched or outcome.disqualified or outcome.race_void:
            return OutcomeState.UNKNOWN_SPECIAL
        return OutcomeState.NORMAL_FINISH

    mapped = SPECIAL_OUTCOMES.get((position, remark))
    if mapped is None:
        return OutcomeState.UNKNOWN_SPECIAL
    if mapped is OutcomeState.DISQUALIFIED:
        clean = not outcome.scratched and not outcome.race_void
    elif mapped is OutcomeState.STARTED_DNF:
        clean = not outcome.scratched and not outcome.disqualified and not outcome.race_void
    elif mapped is OutcomeState.DID_NOT_START:
        clean = outcome.scratched and not outcome.disqualified and not outcome.race_void
    else:
        clean = not outcome.scratched and not outcome.disqualified
    return mapped if clean else OutcomeState.UNKNOWN_SPECIAL


def labels_for_outcome(outcome: RunnerOutcome) -> RunnerLabels:
    """Return labels only for confirmed finishes, DNF, and disqualification."""
    state = classify_outcome(outcome)
    if state is OutcomeState.NORMAL_FINISH:
        position = int(outcome.finish_position)
        return RunnerLabels(True, position == 1, position <= 2, position <= 3, True, None)
    if state in {OutcomeState.STARTED_DNF, OutcomeState.DISQUALIFIED}:
        return RunnerLabels(True, False, False, False, False, state.value)
    return RunnerLabels(False, None, None, None, False, state.value)


def _validated_race_outcomes(
    sealed_field: SealedFieldManifest, outcomes: Iterable[RunnerOutcome]
) -> tuple[tuple[RunnerOutcome, ...], tuple[OutcomeState, ...]]:
    validate_sealed_field(sealed_field)
    rows = tuple(outcomes)
    validate_exact_keyset(
        sealed_field.expected_keys,
        [(row.race_id, row.race_entry_id) for row in rows],
    )
    states = tuple(classify_outcome(row) for row in rows)
    unresolved = {
        OutcomeState.DID_NOT_START,
        OutcomeState.RESULT_MISSING,
        OutcomeState.RACE_VOID,
        OutcomeState.UNKNOWN_SPECIAL,
    }
    blocked = sorted({state.value for state in states if state in unresolved})
    if blocked:
        raise FieldContractError(f"race event is not scoreable: {blocked}")
    return rows, states


def _normal_rank_groups(
    rows: tuple[RunnerOutcome, ...], states: tuple[OutcomeState, ...]
) -> dict[int, list[int]]:
    groups: dict[int, list[int]] = {}
    for row, state in zip(rows, states, strict=True):
        if state is OutcomeState.NORMAL_FINISH:
            groups.setdefault(int(row.finish_position), []).append(row.race_entry_id)
    if not groups or min(groups) != 1:
        raise FieldContractError("official ranks must start at position 1")
    ordered = sorted(groups)
    previous = ordered[0]
    for position in ordered[1:]:
        expected = previous + len(groups[previous])
        if position != expected:
            raise FieldContractError(
                f"invalid official rank progression: expected={expected}, observed={position}"
            )
        previous = position
    return groups


def official_topk_event(
    sealed_field: SealedFieldManifest,
    outcomes: Iterable[RunnerOutcome],
    *,
    k: int,
) -> TopKEvent:
    """Validate official TopK membership and distinguish unique ordered TopK."""
    if k < 1:
        raise ValueError("k must be positive")
    rows, states = _validated_race_outcomes(sealed_field, outcomes)
    groups = _normal_rank_groups(rows, states)
    official = tuple(
        entry_id
        for position in sorted(groups)
        if position <= k
        for entry_id in sorted(groups[position])
    )
    complete = len(official) >= k
    dead_heat = any(len(entries) > 1 for position, entries in groups.items() if position <= k)
    ordered: tuple[int, ...] | None = None
    if complete and not dead_heat and all(position in groups for position in range(1, k + 1)):
        ordered = tuple(groups[position][0] for position in range(1, k + 1))
    return TopKEvent(
        official_entry_ids=official,
        official_membership_complete=complete,
        unique_ordered_entry_ids=ordered,
        ordered_loss_scoreable=ordered is not None,
        has_dead_heat_at_or_before_k=dead_heat,
    )


def race_winner_nll(
    sealed_field: SealedFieldManifest,
    probabilities: Mapping[int, float],
    outcomes: Iterable[RunnerOutcome],
) -> float:
    """Score the sealed-field winner event, summing official tied winners."""
    rows, states = _validated_race_outcomes(sealed_field, outcomes)
    validate_exact_keyset(
        sealed_field.expected_keys,
        [(sealed_field.race_id, entry_id) for entry_id in probabilities],
    )
    _normal_rank_groups(rows, states)
    winners = [
        row.race_entry_id
        for row, state in zip(rows, states, strict=True)
        if state is OutcomeState.NORMAL_FINISH and row.finish_position == 1
    ]
    values = list(probabilities.values())
    if (
        any(not isfinite(value) or value < 0 or value > 1 for value in values)
        or abs(sum(values) - 1.0) > 1e-9
    ):
        raise FieldContractError("winner probabilities must be finite values summing to one")
    return -log(max(sum(probabilities[key] for key in winners), 1e-15))


def outcome_state_counts(outcomes: Iterable[RunnerOutcome]) -> dict[str, int]:
    """Return deterministic counts for an audited, non-mutating outcome frame."""
    return dict(sorted(Counter(classify_outcome(row).value for row in outcomes).items()))
