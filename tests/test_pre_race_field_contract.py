from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

import pytest

from horse_racing.analysis.pre_race_field_contract import (
    FieldContractError,
    FieldEvidence,
    FieldMembership,
    OutcomeState,
    RunnerOutcome,
    SealedFieldManifest,
    classify_outcome,
    labels_for_outcome,
    official_topk_event,
    pre_race_field_features,
    race_winner_nll,
    resolve_field_membership,
    select_pre_race_field,
    validate_exact_keyset,
)

CUTOFF = 1_000
RACE_ID = 10
SNAPSHOT_ID = "sealed-race-10-t1000"


def _field(entry_id: int, horse_number: int, **kwargs) -> FieldEvidence:
    return FieldEvidence(
        race_id=RACE_ID,
        race_entry_id=entry_id,
        horse_number=horse_number,
        snapshot_id=SNAPSHOT_ID,
        entry_observed_at_ms=900,
        **kwargs,
    )


def _manifest(*entry_ids: int) -> SealedFieldManifest:
    return SealedFieldManifest(
        snapshot_id=SNAPSHOT_ID,
        source_id="source-sha256:abc",
        race_id=RACE_ID,
        cutoff_at_ms=CUTOFF,
        sealed_at_ms=CUTOFF,
        expected_keys=tuple((RACE_ID, entry_id) for entry_id in entry_ids),
        complete=True,
        completeness_basis="source totalCount and unique runner keys matched",
    )


def _outcomes(*positions: int | None) -> list[RunnerOutcome]:
    return [
        RunnerOutcome(RACE_ID, entry_id, position)
        for entry_id, position in enumerate(positions, start=1)
    ]


def test_result_changes_cannot_change_sealed_field_or_features() -> None:
    manifest = _manifest(1, 2, 3)
    evidence = [_field(1, 1), _field(2, 2), _field(3, 3)]
    before = select_pre_race_field(manifest, evidence)
    features = pre_race_field_features(manifest, before, strong_front_entry_ids=[1, 3])

    first_results = _outcomes(1, 2, 3)
    changed_results = [
        RunnerOutcome(RACE_ID, 1, 92, "주행중지"),
        RunnerOutcome(RACE_ID, 2, 1),
        RunnerOutcome(RACE_ID, 3, 2),
    ]
    assert [classify_outcome(row) for row in first_results] != [
        classify_outcome(row) for row in changed_results
    ]
    assert select_pre_race_field(manifest, evidence) == before
    assert pre_race_field_features(manifest, before, strong_front_entry_ids=[1, 3]) == features
    assert features[1] == {
        "starters_at_prediction": 3,
        "horse_number_pct": 1 / 3,
        "front_runner_count": 2,
        "front_rival_count": 1,
    }


def test_effective_time_never_substitutes_for_information_availability() -> None:
    effective_only = _field(1, 1, withdrawal_effective_at_ms=950)
    late_known_past_event = _field(
        2,
        2,
        withdrawal_observed_at_ms=1_100,
        withdrawal_effective_at_ms=950,
    )
    assert resolve_field_membership(effective_only, cutoff_at_ms=CUTOFF) is FieldMembership.UNKNOWN
    assert (
        resolve_field_membership(late_known_past_event, cutoff_at_ms=CUTOFF)
        is FieldMembership.INCLUDED
    )


def test_pre_cutoff_observation_post_cutoff_withdrawal_and_time_conflict() -> None:
    known_pre = _field(
        1,
        1,
        withdrawal_observed_at_ms=950,
        withdrawal_effective_at_ms=940,
    )
    post = _field(
        2,
        2,
        withdrawal_observed_at_ms=1_100,
        withdrawal_effective_at_ms=1_050,
    )
    conflict = _field(
        3,
        3,
        withdrawal_observed_at_ms=850,
        withdrawal_published_at_ms=875,
        withdrawal_effective_at_ms=840,
    )
    assert (
        resolve_field_membership(known_pre, cutoff_at_ms=CUTOFF)
        is FieldMembership.EXCLUDED_PRE_CUTOFF
    )
    assert (
        resolve_field_membership(post, cutoff_at_ms=CUTOFF)
        is FieldMembership.INCLUDED_POST_CUTOFF_WITHDRAWAL
    )
    assert resolve_field_membership(conflict, cutoff_at_ms=CUTOFF) is FieldMembership.UNKNOWN

    published_pre_observed_later = _field(
        4,
        4,
        withdrawal_observed_at_ms=1_050,
        withdrawal_published_at_ms=975,
        withdrawal_effective_at_ms=970,
    )
    assert (
        resolve_field_membership(published_pre_observed_later, cutoff_at_ms=CUTOFF)
        is FieldMembership.EXCLUDED_PRE_CUTOFF
    )


def test_late_posthoc_event_does_not_rewrite_sealed_snapshot() -> None:
    manifest = _manifest(1)
    original = _field(1, 1)
    later_enriched = _field(
        1,
        1,
        withdrawal_observed_at_ms=1_100,
        withdrawal_effective_at_ms=950,
    )
    assert select_pre_race_field(manifest, [original])[0].race_entry_id == 1
    assert select_pre_race_field(manifest, [later_enriched])[0].race_entry_id == 1


def test_sealed_manifest_detects_symmetric_deletion_and_wrong_addition() -> None:
    manifest = _manifest(1, 2, 3)
    predictions = {1: 0.6, 2: 0.3}
    outcomes = _outcomes(1, 2)
    with pytest.raises(FieldContractError, match="missing"):
        race_winner_nll(manifest, predictions, outcomes)

    wrong_predictions = {1: 0.5, 2: 0.3, 4: 0.2}
    wrong_outcomes = [
        RunnerOutcome(RACE_ID, 1, 1),
        RunnerOutcome(RACE_ID, 2, 2),
        RunnerOutcome(RACE_ID, 4, 3),
    ]
    with pytest.raises(FieldContractError, match="missing=.*extra"):
        race_winner_nll(manifest, wrong_predictions, wrong_outcomes)


def test_selection_detects_snapshot_deletion_duplicates_and_other_race() -> None:
    manifest = _manifest(1, 2, 3)
    with pytest.raises(FieldContractError, match="missing"):
        select_pre_race_field(manifest, [_field(1, 1), _field(2, 2)])
    with pytest.raises(FieldContractError, match="duplicate"):
        select_pre_race_field(manifest, [_field(1, 1), _field(2, 2), _field(2, 3)])
    mixed = [_field(1, 1), _field(2, 2), FieldEvidence(11, 3, 3, SNAPSHOT_ID, 900)]
    with pytest.raises(FieldContractError, match="missing=.*extra"):
        select_pre_race_field(manifest, mixed)


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (RunnerOutcome(RACE_ID, 1, 95, "출전취소", True, True), OutcomeState.UNKNOWN_SPECIAL),
        (RunnerOutcome(RACE_ID, 1, 92, "주행중지", True), OutcomeState.UNKNOWN_SPECIAL),
        (RunnerOutcome(RACE_ID, 1, 1, "주행중지"), OutcomeState.UNKNOWN_SPECIAL),
        (RunnerOutcome(RACE_ID, 1, 91, "실격"), OutcomeState.DISQUALIFIED),
        (RunnerOutcome(RACE_ID, 1, 92, "주행중지"), OutcomeState.STARTED_DNF),
        (RunnerOutcome(RACE_ID, 1, 95, "출전취소", True), OutcomeState.DID_NOT_START),
    ],
)
def test_state_compatibility_matrix(outcome: RunnerOutcome, expected: OutcomeState) -> None:
    assert classify_outcome(outcome) is expected
    labels = labels_for_outcome(outcome)
    if expected is OutcomeState.UNKNOWN_SPECIAL:
        assert not labels.is_scored
        assert labels.win is None


def test_dnf_has_no_invented_rank_or_finish_time_target() -> None:
    labels = labels_for_outcome(RunnerOutcome(RACE_ID, 1, 92, "주행중지"))
    assert labels.is_scored and labels.win is False
    assert labels.auxiliary_rank_is_observed is False


@pytest.mark.parametrize("positions", [(2, 2, 3), (1, 3, 3)])
def test_invalid_official_rank_sequences_are_rejected(positions: tuple[int, ...]) -> None:
    with pytest.raises(FieldContractError, match="official ranks|rank progression"):
        official_topk_event(_manifest(1, 2, 3), _outcomes(*positions), k=3)
    with pytest.raises(FieldContractError, match="official ranks|rank progression"):
        race_winner_nll(
            _manifest(1, 2, 3),
            {1: 0.5, 2: 0.3, 3: 0.2},
            _outcomes(*positions),
        )


def test_duplicate_results_and_mixed_races_are_rejected() -> None:
    duplicate = [
        RunnerOutcome(RACE_ID, 1, 1),
        RunnerOutcome(RACE_ID, 1, 1),
        RunnerOutcome(RACE_ID, 1, 1),
    ]
    with pytest.raises(FieldContractError, match="duplicate"):
        official_topk_event(_manifest(1, 2, 3), duplicate, k=3)
    mixed = [
        RunnerOutcome(RACE_ID, 1, 1),
        RunnerOutcome(11, 2, 2),
        RunnerOutcome(RACE_ID, 3, 3),
    ]
    with pytest.raises(FieldContractError, match="missing=.*extra"):
        official_topk_event(_manifest(1, 2, 3), mixed, k=3)


def test_valid_dead_heats_are_official_membership_but_not_unique_order() -> None:
    one_one_three = official_topk_event(_manifest(1, 2, 3), _outcomes(1, 1, 3), k=3)
    assert one_one_three.official_entry_ids == (1, 2, 3)
    assert one_one_three.official_membership_complete
    assert one_one_three.unique_ordered_entry_ids is None
    assert not one_one_three.ordered_loss_scoreable

    one_two_two = official_topk_event(_manifest(1, 2, 3), _outcomes(1, 2, 2), k=3)
    assert one_two_two.official_entry_ids == (1, 2, 3)
    assert one_two_two.has_dead_heat_at_or_before_k
    assert not one_two_two.ordered_loss_scoreable


def test_unique_order_and_too_few_finishers_are_distinct() -> None:
    unique = official_topk_event(_manifest(1, 2, 3), _outcomes(1, 2, 3), k=3)
    assert unique.unique_ordered_entry_ids == (1, 2, 3)
    assert unique.ordered_loss_scoreable

    too_few = [RunnerOutcome(RACE_ID, 1, 1), RunnerOutcome(RACE_ID, 2, 92, "주행중지")]
    incomplete = official_topk_event(_manifest(1, 2), too_few, k=3)
    assert not incomplete.official_membership_complete
    assert not incomplete.ordered_loss_scoreable


def test_nonstarter_and_missing_result_block_winner_and_topk_events() -> None:
    nonstarter = RunnerOutcome(RACE_ID, 2, 95, "출전취소", True)
    missing = RunnerOutcome(RACE_ID, 2, None)
    for unresolved in (nonstarter, missing):
        outcomes = [RunnerOutcome(RACE_ID, 1, 1), unresolved]
        with pytest.raises(FieldContractError, match="not scoreable"):
            race_winner_nll(_manifest(1, 2), {1: 0.6, 2: 0.4}, outcomes)
        with pytest.raises(FieldContractError, match="not scoreable"):
            official_topk_event(_manifest(1, 2), outcomes, k=1)


def test_winner_nll_uses_sealed_field_and_sums_dead_heat_probability() -> None:
    outcomes = _outcomes(1, 1, 3)
    value = race_winner_nll(_manifest(1, 2, 3), {1: 0.2, 2: 0.3, 3: 0.5}, outcomes)
    assert value == pytest.approx(-math.log(0.5))


def test_standalone_key_validator_still_rejects_all_mismatch_types() -> None:
    with pytest.raises(FieldContractError, match="duplicate"):
        validate_exact_keyset([(1, 1), (1, 1)], [(1, 1)])
    with pytest.raises(FieldContractError, match="missing"):
        validate_exact_keyset([(1, 1), (1, 2)], [(1, 1)])
    with pytest.raises(FieldContractError, match="extra"):
        validate_exact_keyset([(1, 1)], [(1, 1), (1, 2)])


@pytest.mark.parametrize(
    "scope_args",
    [
        ["--start-date", "2025-01-05"],
        ["--end-date", "2026-06-01"],
        ["--meet", "2"],
    ],
)
def test_auditor_rejects_any_scope_other_than_frozen_e1(
    tmp_path: Path, scope_args: list[str]
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts/audit_pre_race_field_dnf_e1.py"),
            "--db",
            str(tmp_path / "does-not-exist.sqlite3"),
            *scope_args,
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "fixed E1 scope" in completed.stderr
