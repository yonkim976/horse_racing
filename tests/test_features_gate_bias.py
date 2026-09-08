from datetime import date

import polars as pl

from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.features.gate_bias import add_features


def _past_race() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_entry_id": list(range(1, 7)),
            "race_id": [10] * 6,
            "horse_id": list(range(101, 107)),
            "race_date": [date(2025, 1, 5)] * 6,
            "meet_code": [1] * 6,
            "distance_m": [1200] * 6,
            "track_condition": ["건조"] * 6,
            "gate_number": [1, 2, 3, 4, 5, 6],
            "starters": [6] * 6,
            "finish_position": [1, 2, 3, 4, 5, 6],
            "finish_time_ms": [72_000] * 6,
        }
    )


def _target(day: date, entry_offset: int = 0) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_entry_id": [entry_offset + index for index in range(1, 7)],
            "race_date": [day] * 6,
            "meet_code": [1] * 6,
            "distance_m": [1200] * 6,
            "starters": [6] * 6,
            "horse_number": [1, 2, 3, 4, 5, 6],
            "track_condition_planned": ["건조"] * 6,
        }
    )


def test_gate_bias_excludes_same_day_and_uses_prior_day() -> None:
    past = _past_race()
    same_day = add_features(_target(date(2025, 1, 5)), SourceFrames(past_results=past))
    next_day = add_features(
        _target(date(2025, 1, 6), entry_offset=100),
        SourceFrames(past_results=past),
    )

    assert same_day["gate_top3_index_context"].to_list() == [100.0] * 6
    assert same_day["gate_context_expected_slots"].to_list() == [0.0] * 6
    assert next_day["gate_context_expected_slots"].to_list() == [1.0] * 6
    assert next_day["gate_context_reliability"][0] == 1 / 11
    assert next_day["gate_top3_index_context"][0] > 100.0
    assert next_day["gate_top3_index_context"][-1] < 100.0


def test_gate_bias_same_day_outcomes_cannot_change_features() -> None:
    past = _past_race()
    reversed_outcomes = past.with_columns(pl.Series("finish_position", [6, 5, 4, 3, 2, 1]))
    target = _target(date(2025, 1, 5))

    original = add_features(target, SourceFrames(past_results=past))
    reversed_result = add_features(target, SourceFrames(past_results=reversed_outcomes))

    for name in (
        "gate_top3_index_course_distance",
        "gate_top3_index_season",
        "gate_top3_index_going",
        "gate_top3_index_context",
    ):
        assert original[name].to_list() == reversed_result[name].to_list()


def test_gate_bias_unknown_distance_falls_back_without_nulls() -> None:
    target = _target(date(2025, 1, 6), entry_offset=100).with_columns(
        pl.lit(2300).alias("distance_m"),
        pl.lit(None, dtype=pl.Utf8).alias("track_condition_planned"),
    )
    result = add_features(target, SourceFrames(past_results=_past_race()))

    assert result["gate_top3_index_context"].null_count() == 0
    assert result["gate_context_expected_slots"].to_list() == [0.0] * 6


def test_gate_bias_drops_results_older_than_three_years() -> None:
    old = _past_race().with_columns(pl.lit(date(2021, 1, 1)).alias("race_date"))
    result = add_features(
        _target(date(2025, 1, 6), entry_offset=100),
        SourceFrames(past_results=old),
    )

    assert result["gate_top3_index_context"].to_list() == [100.0] * 6
    assert result["gate_context_expected_slots"].to_list() == [0.0] * 6
