"""A그룹. 경주 컨텍스트 feature (원천: races, 경주계획 시점 값)."""

from __future__ import annotations

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames
from horse_racing.analysis.grades import parse_race_grade

GROUP = "A. 경주 컨텍스트"

_PASSTHROUGH = [
    ("distance_m", "경주 거리(m)", "races.distance_m"),
    ("starters", "출주 두수(정상 완주 기준)", "라벨 정책에서 계산"),
    ("race_number", "당일 경주 번호", "races.race_number"),
    ("meet_code", "경마장 코드 (1 서울 / 2 제주 / 3 부산경남)", "racecourses"),
    ("burden_type", "부담구별 (범주)", "races.burden_type"),
    ("age_condition", "연령 조건 (범주)", "races.age_condition"),
    ("sex_condition", "성별 조건 (범주)", "races.sex_condition"),
    ("weather_planned", "경주 전 계획 날씨 (범주)", "races.weather_planned (T1)"),
    ("track_condition_planned", "경주 전 계획 주로상태 (범주)", "races.track_condition_planned"),
    ("track_moisture_percent_planned", "경주 전 계획 주로 함수율", "races (T1)"),
]

FEATURES = [
    FeatureSpec(name=name, group=GROUP, description=desc, source=source)
    for name, desc, source in _PASSTHROUGH
] + [
    FeatureSpec(
        name="race_month",
        group=GROUP,
        description="경주 월 (계절성)",
        source="races.race_date_local",
    ),
    FeatureSpec(
        name="race_weekday",
        group=GROUP,
        description="경주 요일 (월=1 ~ 일=7)",
        source="races.race_date_local",
    ),
    FeatureSpec(
        name="grade_mix",
        group=GROUP,
        description="등급 혼합구분 (국산/혼합/제주/None)",
        source="races.grade → analysis.grades.parse_race_grade",
    ),
    FeatureSpec(
        name="grade_tier",
        group=GROUP,
        description="등급 숫자 (1~6, OPEN은 null)",
        source="races.grade → parse_race_grade",
    ),
    FeatureSpec(
        name="grade_is_open",
        group=GROUP,
        description="OPEN 경주 여부",
        source="races.grade → parse_race_grade",
    ),
    FeatureSpec(
        name="burden_type_clean",
        group=GROUP,
        description="허용 사전으로 정규화한 부담구별",
        source="races.burden_type, grade_raw 접미사",
        null_policy="복원 불가 시 기타/미상",
    ),
    FeatureSpec(
        name="operation_era",
        group=GROUP,
        description="운영 시기(pre_covid/covid/post_covid)",
        source="race_date_local",
    ),
    FeatureSpec(
        name="source_era",
        group=GROUP,
        description="데이터 원천 시기(text_backfill/api_full)",
        source="race_date_local",
    ),
    FeatureSpec(
        name="jeju_breed_regime",
        group=GROUP,
        description="더러브렛/제주마/한라마/미상 구분",
        source="meet_code + grade_raw + race_date_local",
    ),
    FeatureSpec(
        name="grade_system",
        group=GROUP,
        description="더러브렛·제주 구형·제주 레이팅 등급체계 구분",
        source="meet_code + grade_raw + race_date_local",
    ),
]

_BURDEN_PATTERN = r"(핸디캡|마령|별정[A-D]?)"


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    unique_grades = [
        value for value in frame.get_column("grade_raw").unique().to_list()
    ]
    parsed = [parse_race_grade(value) for value in unique_grades]
    grade_map = pl.DataFrame(
        {
            "grade_raw": unique_grades,
            "grade_mix": [item.mix for item in parsed],
            "grade_tier": pl.Series([item.tier for item in parsed], dtype=pl.Int64),
            "grade_is_open": [item.is_open for item in parsed],
        }
    )
    frame = frame.join(grade_map, on="grade_raw", how="left")
    date = pl.col("race_date")
    year = date.dt.year()
    grade = pl.col("grade_raw").fill_null("")
    burden = pl.col("burden_type").fill_null("")
    burden_direct = burden.str.extract(_BURDEN_PATTERN, 1)
    burden_from_grade = grade.str.extract(_BURDEN_PATTERN, 1)
    legacy_jeju = grade.str.contains(r"^\d+[상하세]$")
    is_jeju = pl.col("meet_code") == 2
    frame = frame.with_columns(
        pl.col("race_date").dt.month().cast(pl.Int64).alias("race_month"),
        pl.col("race_date").dt.weekday().cast(pl.Int64).alias("race_weekday"),
        pl.coalesce(burden_direct, burden_from_grade)
        .fill_null("기타/미상")
        .alias("burden_type_clean"),
        pl.when(year.is_between(2020, 2021))
        .then(pl.lit("covid"))
        .when(year < 2020)
        .then(pl.lit("pre_covid"))
        .otherwise(pl.lit("post_covid"))
        .alias("operation_era"),
        pl.when(year >= 2025)
        .then(pl.lit("api_full"))
        .otherwise(pl.lit("text_backfill"))
        .alias("source_era"),
        pl.when(~is_jeju)
        .then(pl.lit("thoroughbred"))
        .when(grade.str.starts_with("한"))
        .then(pl.lit("halla"))
        .when(grade.str.starts_with("제") | legacy_jeju | (date >= pl.date(2023, 1, 1)))
        .then(pl.lit("native_jeju"))
        .otherwise(pl.lit("unknown"))
        .alias("jeju_breed_regime"),
        pl.when(~is_jeju)
        .then(pl.lit("thoroughbred"))
        .when(legacy_jeju | (date <= pl.date(2018, 8, 25)))
        .then(pl.lit("jeju_legacy"))
        .when(grade.str.starts_with("한"))
        .then(pl.lit("jeju_rating_halla"))
        .otherwise(pl.lit("jeju_rating_native"))
        .alias("grade_system"),
    )
    return frame
