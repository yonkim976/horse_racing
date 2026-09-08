from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.features.dynamic_state import add_features


def _history() -> pl.DataFrame:
    rows = []
    start = date(2025, 1, 1)
    for race_index in range(28):
        race_id = race_index + 1
        for horse_id in range(1, 6):
            # Horse 1 improves late; the other horses form a stable daily par.
            base_ms = 72_000 + horse_id * 250
            if horse_id == 1 and race_index >= 22:
                base_ms -= 1_000
            rows.append(
                {
                    "race_entry_id": race_id * 10 + horse_id,
                    "race_id": race_id,
                    "horse_id": horse_id,
                    "race_date": start + timedelta(days=race_index * 7),
                    "meet_code": 1,
                    "distance_m": 1200,
                    "track_condition": "건조",
                    "finish_position": horse_id,
                    "finish_time_ms": base_ms,
                    "starters": 5,
                }
            )
    return pl.DataFrame(rows)


def _target(past: pl.DataFrame, race_id: int) -> pl.DataFrame:
    return past.filter((pl.col("race_id") == race_id) & (pl.col("horse_id") == 1)).select(
        "race_entry_id", "horse_id", "race_date"
    )


def test_dynamic_state_excludes_current_race_observation() -> None:
    past = _history()
    target = _target(past, 28)
    baseline = add_features(target, SourceFrames(past_results=past))
    mutated_past = past.with_columns(
        pl.when((pl.col("race_id") == 28) & (pl.col("horse_id") == 1))
        .then(pl.lit(55_000))
        .otherwise(pl.col("finish_time_ms"))
        .alias("finish_time_ms")
    )
    mutated = add_features(target, SourceFrames(past_results=mutated_past))

    for name in (
        "dynamic_ability_state",
        "dynamic_condition_state",
        "dynamic_condition_sd",
        "dynamic_total_state",
        "dynamic_state_observations",
    ):
        assert mutated[name][0] == pytest.approx(baseline[name][0])
    assert baseline["dynamic_state_observations"][0] > 0


def test_dynamic_condition_mean_reverts_during_layoff() -> None:
    past = _history()
    last_day = past["race_date"].max()
    targets = pl.DataFrame(
        {
            "race_entry_id": [9_001, 9_002],
            "horse_id": [1, 1],
            "race_date": [last_day + timedelta(days=1), last_day + timedelta(days=121)],
        }
    )

    result = add_features(targets, SourceFrames(past_results=past)).sort("race_date")

    assert abs(result["dynamic_condition_state"][1]) < abs(
        result["dynamic_condition_state"][0]
    )
    assert result["dynamic_days_since_observation"].to_list() == [1, 121]
