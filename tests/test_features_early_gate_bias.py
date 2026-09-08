from datetime import date

import polars as pl

from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.features.early_gate_bias import FEATURES, add_features


def _sources(*, include_target_day: bool) -> SourceFrames:
    rows = []
    sections = []
    for race_id, race_date, reverse in [
        (1, date(2026, 1, 1), False),
        *([(2, date(2026, 1, 2), True)] if include_target_day else []),
    ]:
        times = [11_000, 11_100, 12_000, 12_100, 13_000, 13_100]
        if reverse:
            times = list(reversed(times))
        for index, elapsed in enumerate(times, start=1):
            rows.append(
                {
                    "race_id": race_id,
                    "horse_id": race_id * 100 + index,
                    "race_date": race_date,
                    "meet_code": 1,
                    "distance_m": 1200,
                    "gate_number": index,
                    "starters": 6,
                }
            )
            sections.append(
                {
                    "race_id": race_id,
                    "horse_id": race_id * 100 + index,
                    "race_date": race_date,
                    "section_code": "S1F",
                    "elapsed_time_ms": elapsed,
                }
            )
    return SourceFrames(past_results=pl.DataFrame(rows), sections=pl.DataFrame(sections))


def _target() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_entry_id": [10, 11],
            "race_date": [date(2026, 1, 2)] * 2,
            "meet_code": [1, 1],
            "distance_m": [1200, 1200],
            "starters": [6, 6],
            "horse_number": [1, 6],
            "early_pos_pct_avg5": [0.2, 0.2],
            "section_coverage5": [5, 5],
        }
    )


def test_gate_early_speed_prior_is_directional_and_excludes_same_day() -> None:
    without_same_day = add_features(_target(), _sources(include_target_day=False))
    with_same_day = add_features(_target(), _sources(include_target_day=True))

    assert without_same_day["gate_early_speed_context"][0] > 0
    assert without_same_day["gate_early_speed_context"][1] < 0
    assert without_same_day["gate_early_speed_evidence"].to_list() == [2.0, 2.0]
    assert with_same_day.select([spec.name for spec in FEATURES]).equals(
        without_same_day.select([spec.name for spec in FEATURES])
    )


def test_gate_early_speed_empty_source_has_stable_schema() -> None:
    result = add_features(_target(), SourceFrames())
    assert {spec.name for spec in FEATURES} <= set(result.columns)
    assert result["gate_early_speed_context"].to_list() == [0.0, 0.0]
