"""Synthetic counterexamples through the E7-A production audit functions."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from horse_racing.analysis.confirmed_starter_e7a import (
    E7AContractError,
    build_sequence,
    canonical_relative_observations,
    exact_target_keys,
    independent_relative_check,
)
from horse_racing.analysis.features.speed_figure import performance_observations


def _targets(*days: str) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": list(range(100, 100 + len(days))),
            "race_entry_id": list(range(1000, 1000 + len(days))),
            "horse_id": [7] * len(days),
            "race_date_local": list(days),
        }
    )


def _history(rows: list[tuple[int, str, str, int]]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": [entry // 10 for entry, _, _, _ in rows],
            "race_entry_id": [entry for entry, _, _, _ in rows],
            "horse_id": [7] * len(rows),
            "race_date_local": [day for _, day, _, _ in rows],
            "start_state": [status for _, _, status, _ in rows],
            "meet_code": [meet for _, _, _, meet in rows],
            "distance_m": [1200] * len(rows),
            "finish_time_ms": [80000] * len(rows),
        }
    )


def _observations(*entry_ids: int) -> tuple[pl.DataFrame, pl.DataFrame]:
    relative = pl.DataFrame(
        {
            "race_entry_id": list(entry_ids),
            "early_rel": [1.5] * len(entry_ids),
            "last200_rel": [-0.5] * len(entry_ids),
        }
    )
    figures = pl.DataFrame(
        {"race_entry_id": list(entry_ids), "speed_figure": [2.5] * len(entry_ids)}
    )
    return relative, figures


def test_target_and_future_result_changes_do_not_change_single_target_predictors():
    target = _targets("2025-05-01")
    history = _history([(91, "2025-04-01", "normal_finish", 1)])
    relative, figures = _observations(91)
    base, _ = build_sequence(target, history, relative, figures)
    changed = pl.concat(
        [
            history,
            _history(
                [
                    (1000, "2025-05-01", "started_dnf", 1),
                    (1010, "2025-06-01", "normal_finish", 1),
                ]
            ),
        ]
    )
    changed_relative, changed_figures = _observations(91, 1000, 1010)
    again, _ = build_sequence(target, changed, changed_relative, changed_figures)
    assert base.equals(again)
    normal_target = changed.with_columns(
        pl.when(pl.col("race_entry_id") == 1000)
        .then(pl.lit("normal_finish"))
        .otherwise(pl.col("start_state"))
        .alias("start_state")
    )
    changed_status, _ = build_sequence(target, normal_target, changed_relative, changed_figures)
    assert base.equals(changed_status)


def test_order_reversal_and_dnf_slot_do_not_backfill_old_values():
    target = _targets("2025-05-01")
    history = _history(
        [(91, "2025-03-01", "normal_finish", 1), (92, "2025-04-20", "started_dnf", 3)]
    )
    relative, figures = _observations(91)
    base, evidence = build_sequence(target, history, relative, figures)
    reversed_result, _ = build_sequence(target.reverse(), history.reverse(), relative, figures)
    assert base.equals(reversed_result)
    assert base["sequence_start1_early_rel"][0] is None
    assert base["sequence_start1_speed_figure"][0] is None
    assert base["sequence_start1_days_ago"][0] == 11
    assert base["sequence_start2_early_rel"][0] == 1.5
    assert evidence["prior_meet_code"][0] == 3


def test_multiple_target_order_and_history_order_do_not_change_keyed_output():
    targets = _targets("2025-05-01", "2025-06-01")
    history = _history(
        [(91, "2025-03-01", "normal_finish", 1), (92, "2025-04-20", "started_dnf", 3)]
    )
    relative, figures = _observations(91)
    base, _ = build_sequence(targets, history, relative, figures)
    reversed_result, _ = build_sequence(
        targets.reverse(), history.reverse(), relative.reverse(), figures.reverse()
    )
    assert base.equals(reversed_result)


def test_newest_busan_unverified_provenance_and_older_seoul_slot():
    target = _targets("2025-05-01")
    history = _history(
        [(91, "2025-03-01", "normal_finish", 1), (92, "2025-04-20", "normal_finish", 3)]
    )
    relative, figures = _observations(91)
    features, evidence = build_sequence(target, history, relative, figures)
    assert evidence["prior_race_entry_id"][0] == 92
    assert evidence["early_rel_reason"][0] == "section_measurement_absent_in_db"
    assert features["sequence_start1_early_rel"][0] is None
    assert features["sequence_start2_early_rel"][0] == 1.5


@pytest.mark.parametrize(
    "history",
    [
        [(91, "2025-03-01", "normal_finish", 1), (92, "2025-04-20", "unknown_special", 3)],
        [
            (91, "2025-03-01", "normal_finish", 1),
            (92, "2025-04-20", "normal_finish", 3),
            (93, "2025-04-20", "normal_finish", 1),
        ],
    ],
)
def test_unresolved_or_same_day_ambiguity_blocks_older_slots(history):
    target = _targets("2025-05-01")
    features, evidence = build_sequence(target, _history(history), *_observations(91))
    assert evidence["prior_race_entry_id"].null_count() == 3
    assert features["sequence_start2_early_rel"][0] is None
    assert evidence["slot_status"][0] in {
        "prior_start_unresolved",
        "same_day_start_order_ambiguous",
    }


def test_past_observation_change_only_affects_later_target():
    targets = _targets("2025-03-01", "2025-05-01")
    history = _history([(91, "2025-04-01", "normal_finish", 1)])
    relative, figures = _observations(91)
    base, _ = build_sequence(targets, history, relative, figures)
    altered = relative.with_columns(pl.lit(8.0).alias("early_rel"))
    changed, _ = build_sequence(targets, history, altered, figures)
    assert base["sequence_start1_early_rel"][0] is None
    assert changed["sequence_start1_early_rel"][0] is None
    assert base["sequence_start1_early_rel"][1] == 1.5
    assert changed["sequence_start1_early_rel"][1] == 8.0


def test_exact_target_key_contract_rejects_missing_and_duplicate():
    targets = _targets("2025-05-01", "2025-06-01")
    with pytest.raises(E7AContractError, match="missing=1"):
        exact_target_keys(targets, targets.head(1))
    with pytest.raises(E7AContractError, match="duplicate"):
        exact_target_keys(targets, pl.concat([targets, targets.head(1)]))


def test_canonical_relative_uses_prior_race_population_and_independent_formula():
    normal = pl.DataFrame({"race_id": [9, 9, 9], "race_entry_id": [91, 92, 93]})
    rows = []
    for entry, s1, g1 in ((91, 15000, 70000), (92, 16000, 71000), (93, 17000, 72000)):
        for code, value in (("S1F", s1), ("G1F", g1)):
            rows.append(
                {
                    "horse_id": entry,
                    "race_entry_id": entry,
                    "race_id": 9,
                    "meet_code": 1,
                    "race_date": "2025-04-01",
                    "distance_m": 1200,
                    "section_code": code,
                    "elapsed_time_ms": value,
                    "time_basis": "cumulative",
                    "source_kind": "race_result",
                    "finish_position": entry - 90,
                    "finish_time_ms": 85000,
                }
            )
    relative = canonical_relative_observations(pl.DataFrame(rows), normal)
    assert independent_relative_check(relative, normal)["mismatch_cells"] == 0
    assert relative.filter(pl.col("race_entry_id") == 91)["early_rel"][0] > 0

    unknown_basis = pl.DataFrame(rows).with_columns(
        pl.when((pl.col("race_entry_id") == 91) & (pl.col("section_code") == "G1F"))
        .then(None)
        .otherwise(pl.col("time_basis"))
        .alias("time_basis")
    )
    relative_unknown = canonical_relative_observations(unknown_basis, normal)
    target = _targets("2025-05-01")
    history = _history([(91, "2025-04-01", "normal_finish", 1)])
    _, evidence = build_sequence(target, history, relative_unknown, _observations(91)[1])
    assert evidence["last200_rel_reason"][0] == "section_time_basis_unconfirmed"

    impossible = pl.DataFrame(rows).with_columns(
        pl.when((pl.col("race_entry_id") == 91) & (pl.col("section_code") == "S1F"))
        .then(80000)
        .otherwise(pl.col("elapsed_time_ms"))
        .alias("elapsed_time_ms")
    )
    relative_impossible = canonical_relative_observations(impossible, normal)
    _, evidence = build_sequence(target, history, relative_impossible, _observations(91)[1])
    assert evidence["early_rel_reason"][0] == "physical_conversion_unavailable"


def test_speed_par_ignores_future_race_even_when_figure_changes():
    rows = []
    start = date(2024, 1, 1)
    for index in range(24):
        race_day = start + timedelta(days=index if index < 20 else 20 if index < 23 else 21)
        rows.append(
            {
                "race_entry_id": 100 + index,
                "horse_id": 7,
                "race_id": 100 + index,
                "race_date": race_day,
                "meet_code": 1,
                "distance_m": 1200,
                "track_condition": "건조",
                "finish_position": 1,
                "finish_time_ms": (
                    78000
                    if index <= 20
                    else 79000
                    if index == 21
                    else 81000
                    if index == 22
                    else 90000
                ),
                "starters": 1,
            }
        )
    source = pl.DataFrame(rows)
    original = performance_observations(source)[120].figure
    assert original != 0.0  # Three prior-day races yield a nonzero day variant.
    mutated = source.with_columns(
        pl.when(pl.col("race_entry_id") == 123)
        .then(68000)
        .otherwise(pl.col("finish_time_ms"))
        .alias("finish_time_ms")
    )
    assert performance_observations(mutated)[120].figure == original
