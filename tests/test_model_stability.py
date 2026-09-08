from __future__ import annotations

import polars as pl
import pytest

from horse_racing.analysis.model_ensemble import average_predictions
from horse_racing.analysis.model_stability import (
    evaluate_win_segments,
    registered_feature_groups,
    seed_summary,
)


def test_registered_feature_groups_keeps_requested_features() -> None:
    names = ["distance_m", "rating", "trial_n_180d", "custom_feature"]
    groups = registered_feature_groups(names)

    flattened = [name for features in groups.values() for name in features]
    assert sorted(flattened) == sorted(names)
    assert groups["기타 미등록"] == ["custom_feature"]


def test_seed_summary() -> None:
    summary = seed_summary([0.27, 0.28, 0.29])
    assert summary["mean"] == pytest.approx(0.28)
    assert summary["min"] == pytest.approx(0.27)
    assert summary["max"] == pytest.approx(0.29)
    assert summary["std"] > 0


def test_evaluate_win_segments_preserves_whole_races() -> None:
    rows = []
    predictions = []
    for race_id, meet in ((1, 1), (2, 3)):
        for horse in range(5):
            entry_id = race_id * 10 + horse
            rows.append(
                {
                    "race_id": race_id,
                    "race_entry_id": entry_id,
                    "race_date_local": "2026-04-01",
                    "distance_m": 1200 if race_id == 1 else 1800,
                    "starters": 5,
                    "grade_mix": "국산",
                    "grade_tier": 5,
                    "meet_code": meet,
                    "win": int(horse == 0),
                }
            )
            predictions.append(
                {
                    "race_id": race_id,
                    "race_entry_id": entry_id,
                    "prob_win": 0.6 if horse == 0 else 0.1,
                }
            )
    segments = evaluate_win_segments(
        pl.DataFrame(rows), pl.DataFrame(predictions), split="valid"
    )

    assert len(segments["경마장"]) == 2
    assert sum(row["n_races"] for row in segments["경마장"]) == 2
    assert all(row["top1_hit_rate"] == pytest.approx(1.0) for row in segments["경마장"])


def test_average_predictions_preserves_race_totals() -> None:
    first = pl.DataFrame(
        {
            "race_id": [1, 1],
            "race_entry_id": [10, 11],
            "horse_number": [1, 2],
            "prob_win": [0.7, 0.3],
        }
    )
    second = first.with_columns(pl.Series("prob_win", [0.5, 0.5]))

    averaged = average_predictions([first, second], targets=["win"])

    assert averaged["prob_win"].to_list() == pytest.approx([0.6, 0.4])
    assert averaged["prob_win"].sum() == pytest.approx(1.0)
