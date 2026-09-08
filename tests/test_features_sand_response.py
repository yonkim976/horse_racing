from datetime import date, timedelta

import polars as pl

from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.features.sand_response import (
    FEATURES,
    add_features,
    sand_reaction_severity,
    sand_recovery_observation,
)


def test_sand_reaction_parser_requires_adverse_horse_specific_language() -> None:
    text = (
        '● ①“민감마”는 앞 말로부터 모래를 맞자 예민하게 반응하며 탄력이 급격히 떨어졌음. '
        '● ②“정상마”는 앞말로부터 모래를 거의 맞지 않고 좋은 성적을 거두었음.'
    )
    assert sand_reaction_severity(text, "민감마") == 1.0
    assert sand_reaction_severity(text, "정상마") == 0.0


def test_current_reduced_reaction_is_recovery_not_a_new_incident() -> None:
    text = (
        '● 경주 결과 ⑥“호전마”는 모래에 예민하게 반응하며 탄력이 떨어지는 습성이 '
        '있는데, 금일은 예상보다 모래 반응이 크지 않았으며 탄력이 유지되었음.'
    )

    assert sand_reaction_severity(text, "호전마") == 0.0
    assert sand_recovery_observation(text, "호전마") == 1.0


def _recovery_sources() -> SourceFrames:
    start = date(2025, 1, 1)
    past = []
    sections = []
    for index in range(8):
        race_id = index + 1
        race_date = start + timedelta(days=28 * index)
        past.append(
            {
                "race_id": race_id,
                "horse_id": 10,
                "horse_name": "회복마",
                "race_date": race_date,
                "starters": 10,
                "gate_number": 1,
                "finish_position": 5,
            }
        )
        sections.append(
            {
                "race_id": race_id,
                "horse_id": 10,
                "race_date": race_date,
                "section_code": "S1F",
                "position": 7,
            }
        )
    reports = pl.DataFrame(
        {
            "race_id": [1],
            "race_date": [start],
            "judgement": [
                '①“회복마”는 모래를 맞자 예민하게 반응하며 탄력이 급격히 떨어졌음.'
            ],
            "additional_judgement": [None],
        }
    )
    return SourceFrames(
        past_results=pl.DataFrame(past),
        sections=pl.DataFrame(sections),
        steward_reports=reports,
    )


def test_sand_state_can_recover_after_normal_high_exposure_runs() -> None:
    start = date(2025, 1, 1)
    target_dates = [start, start + timedelta(days=28), start + timedelta(days=28 * 8)]
    frame = pl.DataFrame(
        {
            "race_entry_id": [100, 101, 102],
            "horse_id": [10, 10, 10],
            "race_date": target_dates,
            "starters": [10, 10, 10],
            "early_pos_pct_avg5": [0.7, 0.7, 0.7],
            "horse_number_pct": [0.1, 0.1, 0.1],
        }
    )
    result = add_features(frame, _recovery_sources()).sort("race_date")

    assert result["sand_incident_count_prior"].to_list() == [0, 1, 1]
    assert result["sand_sensitivity_state"][1] > result["sand_sensitivity_state"][2]
    assert result["sand_recovery_evidence"][2] > 1.5
    assert result["sand_recovered_flag"][2] == 1
    assert result["sand_expected_penalty"][2] < result["sand_expected_penalty"][1]


def test_sand_feature_schema_is_stable_without_reports() -> None:
    frame = pl.DataFrame(
        {
            "race_entry_id": [1],
            "horse_id": [1],
            "race_date": [date(2026, 1, 1)],
            "starters": [10],
        }
    )
    result = add_features(frame, SourceFrames())
    assert {spec.name for spec in FEATURES} <= set(result.columns)
    assert result["sand_sensitivity_state"].item() == 0.0


def test_unsettled_entries_do_not_update_historical_sand_state() -> None:
    race_date = date(2026, 1, 1)
    sources = SourceFrames(
        past_results=pl.DataFrame(
            {
                "race_id": [1],
                "horse_id": [10],
                "horse_name": ["예정마"],
                "race_date": [race_date],
                "starters": [10],
                "gate_number": [None],
                "finish_position": [None],
            }
        )
    )
    frame = pl.DataFrame(
        {
            "race_entry_id": [100],
            "horse_id": [10],
            "race_date": [race_date],
            "starters": [10],
        }
    )

    result = add_features(frame, sources)

    assert result["sand_incident_count_prior"].item() == 0
    assert result["sand_sensitivity_state"].item() == 0.0
