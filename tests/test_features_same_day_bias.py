from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.features.same_day_bias import add_features


def _sources() -> SourceFrames:
    rows = []
    sections = []
    race_day = date(2026, 8, 1)
    # Races are scheduled 40 minutes apart. Race 1 and 2 are available at the
    # race-3 prediction time after the conservative 20-minute result buffer.
    schedule = {1: 10_000_000, 2: 12_400_000, 3: 14_800_000}
    for race_id in (1, 2, 3):
        for horse_id in range(1, 6):
            rows.append(
                {
                    "race_entry_id": race_id * 10 + horse_id,
                    "race_id": race_id,
                    "race_number": race_id,
                    "horse_id": horse_id,
                    "race_date": race_day,
                    "meet_code": 1,
                    "scheduled_at_ms": schedule[race_id],
                    "distance_m": 1200,
                    "track_condition": "건조",
                    "track_moisture_percent": 3.0,
                    "gate_number": horse_id,
                    "starters": 5,
                    "finish_position": horse_id,
                    "finish_time_ms": 72_000 + horse_id * 200,
                }
            )
            sections.append(
                {
                    "race_id": race_id,
                    "horse_id": horse_id,
                    "race_date": race_day,
                    "section_code": "S1F",
                    "position": horse_id,
                    "elapsed_time_ms": 13_000 + horse_id * 100,
                }
            )
    return SourceFrames(past_results=pl.DataFrame(rows), sections=pl.DataFrame(sections))


def _target(prediction_at_ms: int) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_entry_id": [35],
            "horse_id": [5],
            "race_date": [date(2026, 8, 1)],
            "meet_code": [1],
            "prediction_at_ms": [prediction_at_ms],
            "early_pos_pct_avg5": [0.2],
            "horse_number_pct": [1.0],
            "energy_early_late_balance_avg5": [0.5],
        }
    )


def test_same_day_bias_uses_only_results_available_before_prediction() -> None:
    sources = _sources()
    # Race 3 prediction at 14.2m: R1 available 11.2m, R2 available 13.6m.
    result = add_features(_target(14_200_000), sources)

    assert result["live_bias_races"][0] == 2
    assert result["live_bias_reliability"][0] == pytest.approx(0.4)
    assert result["live_front_bias"][0] > 0
    assert result["live_inner_bias"][0] > 0
    assert result["live_style_fit"][0] > 0


def test_same_day_bias_excludes_current_race_and_is_zero_day_before() -> None:
    sources = _sources()
    baseline = add_features(_target(14_200_000), sources)
    mutated = sources.past_results.with_columns(
        pl.when(pl.col("race_id") == 3)
        .then(6 - pl.col("finish_position"))
        .otherwise(pl.col("finish_position"))
        .alias("finish_position")
    )
    changed = add_features(
        _target(14_200_000),
        SourceFrames(past_results=mutated, sections=sources.sections),
    )
    assert changed["live_front_bias"][0] == pytest.approx(baseline["live_front_bias"][0])
    assert changed["live_inner_bias"][0] == pytest.approx(baseline["live_inner_bias"][0])

    day_before = add_features(_target(1_000_000), sources)
    assert day_before["live_bias_races"][0] == 0
    assert day_before["live_style_fit"][0] == 0.0
