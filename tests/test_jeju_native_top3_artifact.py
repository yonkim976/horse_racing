"""Integration boundaries independent of the data/state implementation."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from scripts.build_jeju_native_top3_dataset import build, fold_assignments


def test_temporal_roles_keep_selection_calibration_and_future_separate() -> None:
    entries = pl.DataFrame(
        {
            "race_id": list(range(1, 9)),
            "event_date": [
                date(2018, 8, 30),
                date(2018, 8, 31),
                date(2024, 6, 30),
                date(2024, 7, 1),
                date(2024, 10, 1),
                date(2024, 12, 31),
                date(2025, 1, 3),
                date(2026, 1, 3),
            ],
            "target_eligible": [True] * 8,
        }
    )
    folds = fold_assignments(entries)
    q1 = folds.filter(pl.col("fold_id") == "dev_2025_q1")
    assert dict(q1.select("race_id", "role").iter_rows()) == {
        1: "state_history",
        2: "fit",
        3: "fit",
        4: "tune",
        5: "calibration",
        6: "label_pending_at_cutoff",
        7: "evaluation",
    }
    future = folds.filter(pl.col("race_id") == 8)
    assert future.select("fold_id", "role").rows() == [("frozen_2026", "evaluation")]
    assert folds.select("fold_id", "race_id").unique().height == folds.height


def test_sealed_output_is_not_overwritten(tmp_path: Path) -> None:
    output = tmp_path / "sealed"
    output.mkdir()
    sentinel = output / "manifest.json"
    sentinel.write_text('{"sentinel": true}')
    with pytest.raises(FileExistsError, match="Immutable"):
        build(tmp_path / "not_even_a_database", output)
    assert sentinel.read_text() == '{"sentinel": true}'
