from datetime import date

import polars as pl

from horse_racing.analysis.features import apply_features, feature_names
from horse_racing.analysis.features.base import (
    SourceFrames,
    days_since_last_event,
    rolling_event_counts,
)
from horse_racing.analysis.features.relative import add_features as add_relative


def base_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": [1, 1, 1],
            "race_entry_id": [100, 101, 102],
            "race_date_local": ["2026-08-22"] * 3,
            "grade_raw": ["국6등급", "국6등급", "국6등급"],
            "horse_id": [10, 11, 12],
            "jockey_id": [20, 21, None],
            "trainer_id": [30, 31, None],
            "horse_number": [1, 2, 3],
            "gate_number": [1, 2, 3],
            "starters": [3, 3, 3],
            "carried_weight_kg": [54.0, 56.0, 58.0],
            "rating": [40.0, 50.0, 60.0],
            "body_weight_kg": [480, 500, 520],
            "race_number": [1, 1, 1],
            "meet_code": [1, 1, 1],
            "distance_m": [1200, 1200, 1200],
            "burden_type": ["핸디캡"] * 3,
            "age_condition": ["연령오픈"] * 3,
            "sex_condition": ["암수"] * 3,
            "weather_planned": ["맑음"] * 3,
            "track_condition_planned": ["건조"] * 3,
            "track_moisture_percent_planned": [8.0] * 3,
        }
    )


def sources_with_static() -> SourceFrames:
    return SourceFrames(
        horse_static=pl.DataFrame(
            {
                "horse_id": [10, 11, 12],
                "birth_date": [date(2022, 8, 22), date(2023, 8, 22), None],
                "sex": ["수", "암", "거"],
                "origin_country": ["한국", "한국", "미국"],
            }
        )
    )


def test_apply_features_context_and_entry() -> None:
    result = apply_features(base_frame(), sources_with_static())

    assert result.get_column("grade_mix").to_list() == ["국산"] * 3
    assert result.get_column("grade_tier").to_list() == [6] * 3
    assert result.get_column("grade_is_open").to_list() == [False] * 3
    assert result.get_column("race_month").to_list() == [8] * 3
    # 2026-08-22는 토요일 (월=1 … 토=6)
    assert result.get_column("race_weekday").to_list() == [6] * 3

    ages = result.get_column("horse_age_months").to_list()
    assert 47.5 < ages[0] < 48.5  # 만 4년 ≈ 48개월
    assert 35.5 < ages[1] < 36.5
    assert ages[2] is None
    assert result.get_column("horse_sex").to_list() == ["수", "암", "거"]

    # 부담중량 평균 56 → 상대값 [-2, 0, 2]
    assert result.get_column("carried_weight_rel").to_list() == [-2.0, 0.0, 2.0]
    assert result.get_column("horse_number_pct").to_list() == [
        1 / 3,
        2 / 3,
        1.0,
    ]


def test_entry_features_prefer_official_gate_number() -> None:
    frame = base_frame().with_columns(pl.Series("gate_number", [3, 2, 1]))
    result = apply_features(frame, sources_with_static())

    assert result.get_column("horse_number").to_list() == [3, 2, 1]
    assert result.get_column("horse_number_pct").to_list() == [1.0, 2 / 3, 1 / 3]


def test_relative_features_z_and_rank() -> None:
    frame = base_frame().with_columns(pl.lit(None).alias("race_date"))
    result = add_relative(frame, SourceFrames())

    z_scores = result.get_column("rating_race_z").to_list()
    assert abs(z_scores[0] + 1.0) < 1e-9
    assert abs(z_scores[1]) < 1e-9
    assert abs(z_scores[2] - 1.0) < 1e-9
    # 내림차순 rank: rating 60이 1위
    assert result.get_column("rating_race_rank").to_list() == [3.0, 2.0, 1.0]
    # 등록됐지만 없는 컬럼(form_recent5_pct 등)은 건너뜀
    assert "form_recent5_pct_race_z" not in result.columns


def test_rolling_event_counts_excludes_same_day() -> None:
    base = pl.DataFrame(
        {"horse_id": [1], "race_date": [date(2026, 8, 22)]}
    )
    events = pl.DataFrame(
        {
            "horse_id": [1, 1, 1, 1],
            "event_date": [
                date(2026, 8, 22),  # 당일 → 제외
                date(2026, 8, 21),  # 1일 전
                date(2026, 8, 16),  # 6일 전
                date(2026, 7, 1),  # 52일 전
            ],
            "duration_seconds": [100.0, 200.0, 300.0, 400.0],
        }
    )
    result = rolling_event_counts(
        base,
        events,
        key="horse_id",
        base_date_col="race_date",
        windows_days=(3, 7, 28),
        prefix="train",
        value_columns={"duration_seconds": "dur"},
    )
    row = result.row(0, named=True)
    assert row["train_n_3d"] == 1
    assert row["train_n_7d"] == 2
    assert row["train_n_28d"] == 2
    assert row["train_dur_3d"] == 200.0
    assert row["train_dur_7d"] == 500.0


def test_rolling_event_counts_empty_events() -> None:
    base = pl.DataFrame({"horse_id": [1], "race_date": [date(2026, 8, 22)]})
    result = rolling_event_counts(
        base,
        pl.DataFrame(),
        key="horse_id",
        base_date_col="race_date",
        windows_days=(7,),
        prefix="train",
    )
    assert result.row(0, named=True)["train_n_7d"] == 0


def test_days_since_last_event_strictly_before() -> None:
    base = pl.DataFrame(
        {"horse_id": [1, 2], "race_date": [date(2026, 8, 22)] * 2}
    )
    events = pl.DataFrame(
        {
            "horse_id": [1, 1, 2],
            "event_date": [date(2026, 8, 22), date(2026, 8, 10), date(2026, 9, 1)],
        }
    )
    result = days_since_last_event(
        base,
        events,
        key="horse_id",
        base_date_col="race_date",
        alias="days_since",
    ).sort("horse_id")
    values = result.get_column("days_since").to_list()
    assert values[0] == 12  # 당일 이벤트 제외, 08-10이 마지막
    assert values[1] is None  # 미래 이벤트만 존재


def test_feature_names_filters_to_existing_columns() -> None:
    result = apply_features(base_frame(), sources_with_static())
    names = feature_names(result)
    assert "grade_tier" in names
    assert "rating_race_z" in names
    assert all(name in result.columns for name in names)


def test_racefit_feature_sets_preserve_v1_and_separate_intraday_features() -> None:
    v1 = set(feature_names(feature_set="racefit_rich"))
    v2_history = set(feature_names(feature_set="racefit_v2_history"))
    v2_rich = set(feature_names(feature_set="racefit_v2_rich"))

    assert "dynamic_condition_state" not in v1
    assert "live_style_fit" not in v1
    assert "dynamic_condition_state" in v2_history
    assert "live_style_fit" not in v2_history
    assert {"dynamic_condition_state", "live_style_fit"} <= v2_rich
