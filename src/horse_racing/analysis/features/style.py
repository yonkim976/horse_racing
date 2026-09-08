"""D그룹. 주행 스타일 feature (원천: 과거 race_section_results).

구간 position을 past_results에 붙인 뒤 (horse_id, race_date) 정렬 → shift(1)
롤링으로 **직전 5경주**만 집계한다. 데이터셋 행은 past_results에 같은
race_entry_id로 존재하므로, 현재 경주 구간은 창에 포함되지 않는다.
"""

from __future__ import annotations

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames, as_date

GROUP = "D. 주행 스타일"
LOOKBACK = 5
_SECTION_CODES = ("S1F", "4C", "G1F", "G3F")

_NULL_REASON = "구간 원천 공백일·신마·해당 코드 결측 시 null 유지"
_LEAKAGE = "low — 현재 경주 제외(shift 1). 라벨(finish_position 등)은 past_results의 과거 행만 사용"

FEATURES = [
    FeatureSpec(
        name="early_pos_pct_avg5",
        group=GROUP,
        description="최근 5경주 S1F 통과순위/출주두수 평균 (작을수록 선행 성향)",
        source="race_section_results.S1F + past_results.starters",
        lookback="최근 5경주",
        null_policy=_NULL_REASON,
        leakage_note=_LEAKAGE,
    ),
    FeatureSpec(
        name="late_gain_avg5",
        group=GROUP,
        description="최근 5경주 (S1F position − finish_position) 평균 (클수록 막판 추입)",
        source="race_section_results.S1F + past_results.finish_position",
        lookback="최근 5경주",
        null_policy=_NULL_REASON,
        leakage_note=_LEAKAGE,
    ),
    FeatureSpec(
        name="late_gain_pct_avg5",
        group=GROUP,
        description="최근 5경주 (S1F position − 착순)/출주두수 평균",
        source="race_section_results.S1F + past_results.finish_position/starters",
        lookback="최근 5경주",
        null_policy=_NULL_REASON,
        leakage_note=_LEAKAGE,
    ),
    FeatureSpec(
        name="early_pos_pct_std5",
        group=GROUP,
        description="최근 5경주 초반 위치 백분위 표준편차 (전개 성향 안정성)",
        source="race_section_results.S1F + past_results.starters",
        lookback="최근 5경주",
        null_policy="S1F 이력 2회 미만이면 null",
        leakage_note=_LEAKAGE,
    ),
    FeatureSpec(
        name="corner4_pos_pct_avg5",
        group=GROUP,
        description="최근 5경주 4C 통과순위/출주두수 평균 (거리 의존 결측 많음)",
        source="race_section_results.4C + past_results.starters",
        lookback="최근 5경주",
        null_policy="4C 미존재(거리 의존)·원천 공백일은 null 유지. 0으로 채우지 않음",
        leakage_note=_LEAKAGE,
    ),
    FeatureSpec(
        name="pace_fade_avg5",
        group=GROUP,
        description="최근 5경주 (G1F position − G3F position) 평균 (막판 1펄롱 순위 변화)",
        source="race_section_results.G1F, G3F",
        lookback="최근 5경주",
        null_policy="G1F 또는 G3F position 결측 시 해당 경주는 창에서 제외, 전부 없으면 null",
        leakage_note=_LEAKAGE,
    ),
    FeatureSpec(
        name="style_category",
        group=GROUP,
        description="early_pos_pct_avg5 규칙 분류 (선행/선입/중위/추입)",
        source="파생 (early_pos_pct_avg5)",
        lookback="최근 5경주",
        null_policy="early_pos_pct_avg5 없으면 null",
        leakage_note=_LEAKAGE,
    ),
    FeatureSpec(
        name="section_coverage5",
        group=GROUP,
        description="최근 5경주 중 S1F position이 존재한 경주 수 (0~5)",
        source="race_section_results.S1F",
        lookback="최근 5경주",
        null_policy="이력 없으면 0 (null 아님). 구간 원천 공백일은 해당 경주가 미커버",
        leakage_note=_LEAKAGE,
    ),
]


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    past = as_date(sources.past_results, "race_date")
    sections = as_date(sources.sections, "race_date")
    if past.height == 0:
        return _with_empty_features(frame)

    history = _attach_section_positions(past, sections)
    history = history.with_columns(
        (pl.col("S1F") / pl.col("starters")).alias("_s1f_pct"),
        (pl.col("S1F") - pl.col("finish_position")).alias("_late_gain"),
        ((pl.col("S1F") - pl.col("finish_position")) / pl.col("starters")).alias(
            "_late_gain_pct"
        ),
        (pl.col("4C") / pl.col("starters")).alias("_c4_pct"),
        (pl.col("G1F") - pl.col("G3F")).alias("_pace_fade"),
        pl.col("S1F").is_not_null().cast(pl.Int64).alias("_has_s1f"),
    )
    history = history.sort(["horse_id", "race_date", "race_entry_id"])
    history = history.with_columns(
        _shifted_rolling_mean("_s1f_pct").alias("early_pos_pct_avg5"),
        _shifted_rolling_mean("_late_gain").alias("late_gain_avg5"),
        _shifted_rolling_mean("_late_gain_pct").alias("late_gain_pct_avg5"),
        pl.col("_s1f_pct")
        .shift(1)
        .rolling_std(window_size=LOOKBACK, min_samples=2)
        .over("horse_id")
        .alias("early_pos_pct_std5"),
        _shifted_rolling_mean("_c4_pct").alias("corner4_pos_pct_avg5"),
        _shifted_rolling_mean("_pace_fade").alias("pace_fade_avg5"),
        pl.col("_has_s1f")
        .shift(1)
        .fill_null(0)
        .rolling_sum(window_size=LOOKBACK, min_samples=1)
        .over("horse_id")
        .cast(pl.Int64)
        .alias("section_coverage5"),
    ).with_columns(_style_category_expr())

    features = history.select(
        "race_entry_id",
        "early_pos_pct_avg5",
        "late_gain_avg5",
        "late_gain_pct_avg5",
        "early_pos_pct_std5",
        "corner4_pos_pct_avg5",
        "pace_fade_avg5",
        "style_category",
        "section_coverage5",
    )
    result = frame.join(features, on="race_entry_id", how="left")
    return result.with_columns(pl.col("section_coverage5").fill_null(0).cast(pl.Int64))


def _shifted_rolling_mean(column: str) -> pl.Expr:
    return (
        pl.col(column)
        .shift(1)
        .rolling_mean(window_size=LOOKBACK, min_samples=1)
        .over("horse_id")
    )


def _style_category_expr() -> pl.Expr:
    value = pl.col("early_pos_pct_avg5")
    return (
        pl.when(value.is_null())
        .then(pl.lit(None, dtype=pl.Utf8))
        .when(value < 0.35)
        .then(pl.lit("선행"))
        .when(value < 0.55)
        .then(pl.lit("선입"))
        .when(value < 0.75)
        .then(pl.lit("중위"))
        .otherwise(pl.lit("추입"))
        .alias("style_category")
    )


def _attach_section_positions(past: pl.DataFrame, sections: pl.DataFrame) -> pl.DataFrame:
    if sections.height == 0:
        return past.with_columns(
            *[pl.lit(None).cast(pl.Float64).alias(code) for code in _SECTION_CODES]
        )
    usable = sections.filter(pl.col("section_code").is_in(list(_SECTION_CODES)))
    if "race_id" in usable.columns and "elapsed_time_ms" in usable.columns:
        reconstructed_s1f = (
            (pl.col("section_code") == "S1F")
            & pl.col("position").is_null()
            & pl.col("elapsed_time_ms").is_not_null()
        )
        usable = usable.with_columns(
            pl.when(reconstructed_s1f)
            .then(
                pl.col("elapsed_time_ms")
                .rank("average")
                .over(["race_id", "section_code"])
            )
            .otherwise(pl.col("position"))
            .alias("_effective_position")
        )
        value_column = "_effective_position"
    else:
        value_column = "position"
    pivoted = (
        usable
        .pivot(
            on="section_code",
            index=["horse_id", "race_date"],
            values=value_column,
            aggregate_function="first",
        )
    )
    if pivoted.height == 0:
        return past.with_columns(
            *[pl.lit(None).cast(pl.Float64).alias(code) for code in _SECTION_CODES]
        )
    missing = [
        pl.lit(None).cast(pl.Float64).alias(code)
        for code in _SECTION_CODES
        if code not in pivoted.columns
    ]
    if missing:
        pivoted = pivoted.with_columns(missing)
    pivoted = pivoted.with_columns(
        [pl.col(code).cast(pl.Float64) for code in _SECTION_CODES]
    ).select("horse_id", "race_date", *_SECTION_CODES)
    return past.join(pivoted, on=["horse_id", "race_date"], how="left")


def attach_early_position_target(
    frame: pl.DataFrame,
    sources: SourceFrames,
) -> pl.DataFrame:
    """Attach the current-race S1F percentile as a training-only target."""
    past = as_date(sources.past_results, "race_date")
    sections = as_date(sources.sections, "race_date")
    if past.height == 0:
        return frame.with_columns(
            pl.lit(None).cast(pl.Float64).alias("early_position_pct_target")
        )
    history = _attach_section_positions(past, sections)
    target = history.select(
        "race_entry_id",
        pl.when(
            pl.col("S1F").is_not_null()
            & pl.col("starters").is_not_null()
            & (pl.col("starters") > 1)
        )
        .then((pl.col("S1F") - 1.0) / (pl.col("starters") - 1.0))
        .otherwise(None)
        .clip(0.0, 1.0)
        .alias("early_position_pct_target"),
    ).unique("race_entry_id")
    return frame.join(target, on="race_entry_id", how="left")


def _with_empty_features(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.lit(None).cast(pl.Float64).alias("early_pos_pct_avg5"),
        pl.lit(None).cast(pl.Float64).alias("late_gain_avg5"),
        pl.lit(None).cast(pl.Float64).alias("late_gain_pct_avg5"),
        pl.lit(None).cast(pl.Float64).alias("early_pos_pct_std5"),
        pl.lit(None).cast(pl.Float64).alias("corner4_pos_pct_avg5"),
        pl.lit(None).cast(pl.Float64).alias("pace_fade_avg5"),
        pl.lit(None).cast(pl.Utf8).alias("style_category"),
        pl.lit(0).cast(pl.Int64).alias("section_coverage5"),
    )
