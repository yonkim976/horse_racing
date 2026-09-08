from datetime import date

import polars as pl

from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.features.competition import add_features


def test_pace_competition_excludes_self_and_builds_interactions() -> None:
    frame = pl.DataFrame(
        {
            "race_id": [1, 1, 1, 1],
            "meet_code": [1, 1, 1, 1],
            "distance_m": [1200, 1200, 1200, 1200],
            "starters": [4, 4, 4, 4],
            "horse_number_pct": [0.25, 0.50, 0.75, 1.0],
            "early_pos_pct_avg5": [0.20, 0.24, 0.50, 0.80],
            "section_coverage5": [5, 3, 4, 2],
            "style_category": ["선행", "선행", "선입", "추입"],
            "race_date": [date(2026, 1, 1)] * 4,
        }
    )
    result = add_features(frame, SourceFrames())
    assert result["front_runner_count"].to_list() == [2, 2, 2, 2]
    assert result["front_rival_count"].to_list() == [1, 1, 2, 2]
    assert result["pace_pressure"].to_list() == [
        "1두경합",
        "1두경합",
        "2두이상경합",
        "2두이상경합",
    ]
    assert result["course_distance_key"].to_list() == ["1_1200"] * 4
    assert result["gate_band"].to_list() == ["안쪽", "중간", "바깥쪽", "바깥쪽"]
    assert result["style_pace_key"][0] == "선행_1두경합"


def test_low_style_coverage_hides_pressure_category() -> None:
    frame = pl.DataFrame(
        {
            "race_id": [1] * 5,
            "meet_code": [3] * 5,
            "distance_m": [1800] * 5,
            "starters": [5] * 5,
            "horse_number_pct": [0.2, 0.4, 0.6, 0.8, 1.0],
            "early_pos_pct_avg5": [0.2, 0.3, None, None, None],
            "section_coverage5": [2, 2, 0, 0, 0],
            "style_category": ["선행", "선행", None, None, None],
        }
    )
    result = add_features(frame, SourceFrames())
    assert result["known_style_share"].to_list() == [0.4] * 5
    assert result["pace_pressure"].null_count() == 5
    assert result["style_pace_key"].null_count() == 5

