"""B+ group. Non-linear age and race-cycle features.

Raw age in months and days since the previous race are already available, but
their observed effects are non-linear and differ between Jeju and the
Seoul/Busan regime.  These features encode those shapes without using any race
result from the target event.
"""

from __future__ import annotations

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames

GROUP = "B+. 생애주기·출전주기"

FEATURES = [
    FeatureSpec(
        name="age_regime_stage",
        group=GROUP,
        description="경마장 체계별 연령 단계(서울·부산 2~7+, 제주 2~8+)",
        source="horse_age_months + meet_code",
        null_policy="나이 또는 경마장 결측 시 unknown",
    ),
    FeatureSpec(
        name="age_pre_peak_months",
        group=GROUP,
        description="체계별 기준 전성기까지 남은 월수(서울·부산 42개월, 제주 54개월)",
        source="horse_age_months + meet_code",
        null_policy="나이 또는 경마장 결측 시 null",
    ),
    FeatureSpec(
        name="age_post_peak_months",
        group=GROUP,
        description="체계별 기준 전성기 이후 경과 월수",
        source="horse_age_months + meet_code",
        null_policy="나이 또는 경마장 결측 시 null",
    ),
    FeatureSpec(
        name="rest_cycle_bin",
        group=GROUP,
        description="직전 출전 후 경과일의 비선형 구간",
        source="days_since_last_race",
        null_policy="신마는 debut",
    ),
    FeatureSpec(
        name="rest_log_days",
        group=GROUP,
        description="log(1 + 직전 출전 후 경과일)",
        source="days_since_last_race",
        null_policy="신마는 null",
    ),
    FeatureSpec(
        name="rest_excess_41d",
        group=GROUP,
        description="41일을 초과한 휴양 일수",
        source="days_since_last_race",
        null_policy="신마는 null",
    ),
    FeatureSpec(
        name="senior_long_layoff",
        group=GROUP,
        description="체계별 고령마이면서 60일 초과 휴양이면 1",
        source="horse_age_months + meet_code + days_since_last_race",
        null_policy="필수 입력 결측 시 null",
    ),
    FeatureSpec(
        name="young_short_cycle",
        group=GROUP,
        description="체계별 성장기 말이면서 20일 이내 재출전이면 1",
        source="horse_age_months + meet_code + days_since_last_race",
        null_policy="필수 입력 결측 시 null",
    ),
]


def _peak_months() -> pl.Expr:
    return (
        pl.when(pl.col("meet_code").is_in([1, 3]))
        .then(pl.lit(42.0))
        .when(pl.col("meet_code") == 2)
        .then(pl.lit(54.0))
        .otherwise(None)
    )


def _age_stage() -> pl.Expr:
    years = (pl.col("horse_age_months") / 12.0).floor().cast(pl.Int64)
    seoul_busan = (
        pl.when(years >= 7)
        .then(pl.lit("seoul_busan_7plus"))
        .otherwise(pl.concat_str([pl.lit("seoul_busan_"), years.cast(pl.Utf8)]))
    )
    jeju = (
        pl.when(years >= 8)
        .then(pl.lit("jeju_8plus"))
        .otherwise(pl.concat_str([pl.lit("jeju_"), years.cast(pl.Utf8)]))
    )
    return (
        pl.when(pl.col("horse_age_months").is_null())
        .then(pl.lit("unknown"))
        .when(pl.col("meet_code").is_in([1, 3]))
        .then(seoul_busan)
        .when(pl.col("meet_code") == 2)
        .then(jeju)
        .otherwise(pl.lit("unknown"))
    )


def _rest_bin() -> pl.Expr:
    rest = pl.col("days_since_last_race")
    return (
        pl.when(rest.is_null())
        .then(pl.lit("debut"))
        .when(rest <= 7)
        .then(pl.lit("le_7"))
        .when(rest <= 13)
        .then(pl.lit("d08_13"))
        .when(rest <= 20)
        .then(pl.lit("d14_20"))
        .when(rest <= 27)
        .then(pl.lit("d21_27"))
        .when(rest <= 41)
        .then(pl.lit("d28_41"))
        .when(rest <= 60)
        .then(pl.lit("d42_60"))
        .when(rest <= 90)
        .then(pl.lit("d61_90"))
        .when(rest <= 180)
        .then(pl.lit("d91_180"))
        .otherwise(pl.lit("d181_plus"))
    )


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    required = {"horse_age_months", "meet_code", "days_since_last_race"}
    if not required <= set(frame.columns):
        return frame.with_columns(
            pl.lit("unknown").alias("age_regime_stage"),
            pl.lit(None).cast(pl.Float64).alias("age_pre_peak_months"),
            pl.lit(None).cast(pl.Float64).alias("age_post_peak_months"),
            pl.lit("debut").alias("rest_cycle_bin"),
            pl.lit(None).cast(pl.Float64).alias("rest_log_days"),
            pl.lit(None).cast(pl.Float64).alias("rest_excess_41d"),
            pl.lit(None).cast(pl.Int8).alias("senior_long_layoff"),
            pl.lit(None).cast(pl.Int8).alias("young_short_cycle"),
        )

    peak = _peak_months()
    rest = pl.col("days_since_last_race").cast(pl.Float64)
    age = pl.col("horse_age_months")
    senior = (
        pl.when(pl.col("meet_code").is_in([1, 3]))
        .then(age >= 72)
        .when(pl.col("meet_code") == 2)
        .then(age >= 96)
        .otherwise(None)
    )
    young = (
        pl.when(pl.col("meet_code").is_in([1, 3]))
        .then(age < 48)
        .when(pl.col("meet_code") == 2)
        .then(age < 60)
        .otherwise(None)
    )
    return frame.with_columns(
        _age_stage().alias("age_regime_stage"),
        (peak - age).clip(lower_bound=0).alias("age_pre_peak_months"),
        (age - peak).clip(lower_bound=0).alias("age_post_peak_months"),
        _rest_bin().alias("rest_cycle_bin"),
        rest.log1p().alias("rest_log_days"),
        (rest - 41.0).clip(lower_bound=0).alias("rest_excess_41d"),
        pl.when(age.is_null() | rest.is_null() | senior.is_null())
        .then(None)
        .otherwise((senior & (rest > 60)).cast(pl.Int8))
        .alias("senior_long_layoff"),
        pl.when(age.is_null() | rest.is_null() | young.is_null())
        .then(None)
        .otherwise((young & (rest <= 20)).cast(pl.Int8))
        .alias("young_short_cycle"),
    )
