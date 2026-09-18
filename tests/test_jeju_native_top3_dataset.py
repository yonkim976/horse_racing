from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from horse_racing.analysis.jeju_native_top3_dataset import (
    DatasetContractError,
    build_top3_labels,
    extract_dataset,
)

DB = Path("data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3")


def _entries(positions: list[int | None], *, race_id: int = 1) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": [race_id] * len(positions),
            "entry_id": list(range(1, len(positions) + 1)),
            "horse_id": [f"300000{i}" for i in range(1, len(positions) + 1)],
            "horse_number": list(range(1, len(positions) + 1)),
            "finish_position": positions,
            "finish_time_ms": [70000 + i * 100 for i in range(len(positions))],
        }
    )


def test_boundary_dead_heat_generates_all_compatible_orders_and_two_sets() -> None:
    result = build_top3_labels(_entries([1, 2, 3, 3, 5]))
    labels = result["labels"]
    assert result["accepted_orders"].height == 2
    assert result["accepted_sets"].height == 2
    assert labels["top3_candidate_tie"].all()
    assert labels["accepted_order_count"].unique().to_list() == [2]
    assert labels["accepted_set_count"].unique().to_list() == [2]


def test_rank_one_tie_keeps_top_three_set_and_all_orders() -> None:
    result = build_top3_labels(_entries([1, 1, 3, 4, 5]))
    assert result["accepted_orders"].height == 2
    assert result["accepted_sets"].height == 1
    assert result["accepted_sets"]["tie_case"].to_list() == [True]


def test_gap_before_third_is_not_renumbered() -> None:
    result = build_top3_labels(_entries([1, 2, 4, 5]))
    labels = result["labels"]
    assert result["accepted_orders"].is_empty()
    assert result["accepted_sets"].is_empty()
    assert not labels["top3_target_eligible"].any()
    assert labels["accepted_order_count"].unique().to_list() == [0]


def test_dq_and_dnf_are_started_but_rank_and_time_are_masked() -> None:
    result = build_top3_labels(_entries([1, 2, 3, 91, 92]))
    labels = result["labels"].sort("entry_id")
    assert labels.filter(pl.col("outcome_status") == "disqualified")["rank_mask"].to_list() == [
        False
    ]
    assert labels.filter(pl.col("outcome_status") == "dnf")["time_mask"].to_list() == [False]
    assert (
        labels.filter(pl.col("outcome_status").is_in(["disqualified", "dnf"]))["label_top3"].sum()
        == 0
    )


def test_snapshot_counts_splits_and_400m_history() -> None:
    data = extract_dataset(DB)
    assert data["entries"].height == 84_583
    assert data["history_results"].height == 90_122
    assert data["races"].height == 9_280
    assert data["races"].filter(pl.col("target_eligible")).height == 8_682
    assert data["accepted_orders"].height == 8_721
    assert data["accepted_sets"].height == 8_699
    assert data["races"].filter(~pl.col("full_rank_valid")).select(
        "race_id"
    ).to_series().to_list() == [6867]
    assert data["races"].filter(~pl.col("full_rank_valid"))["top3_rank_valid"].to_list() == [True]
    assert data["labels"].filter(pl.col("race_id") == 6867)[
        "full_rank_target_mask"
    ].unique().to_list() == [False]
    assert data["exclusions"].filter(pl.col("reason_code") == "full_rank_quality_warning")[
        "action"
    ].to_list() == ["retained_warning"]
    assert (
        data["exclusions"].filter(pl.col("reason_code") == "no_positive_result_race").height == 135
    )
    assert data["entries"].filter(pl.col("distance_m") == 400).is_empty()
    assert data["history_results"].filter(pl.col("distance_m") == 400).height == 5_539
    split_counts = (
        data["entries"]
        .group_by("split")
        .agg(pl.len().alias("rows"), pl.col("race_id").n_unique().alias("races"))
    )
    assert split_counts.sort("split")["rows"].to_list() == [6_953, 4_852, 36_523, 36_255]


def test_non_snapshot_database_is_rejected(tmp_path: Path) -> None:
    copied = tmp_path / "db.sqlite3"
    copied.write_bytes(b"not the reviewed snapshot")
    with pytest.raises(DatasetContractError, match="SHA-256 mismatch"):
        extract_dataset(copied)


def test_singleton_metadata_refers_to_number_of_accepted_answers() -> None:
    ordinary = build_top3_labels(_entries([1, 2, 3, 4]))
    tied = build_top3_labels(_entries([1, 1, 3, 4]))
    assert ordinary["accepted_orders"]["singleton"].to_list() == [True]
    assert tied["accepted_orders"]["singleton"].to_list() == [False, False]
    assert tied["accepted_sets"]["singleton"].to_list() == [True]


def test_gap_below_podium_keeps_top3_but_masks_full_rank() -> None:
    result = build_top3_labels(_entries([1, 2, 3, 4, 5, 6, 7, 9, 91, 92]))
    assert result["accepted_orders"].height == 1
    assert not result["labels"]["full_rank_target_mask"].any()
