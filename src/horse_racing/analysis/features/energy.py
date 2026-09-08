"""C3 group. Leakage-safe section-time energy allocation features.

Section sources changed representation across eras, so raw S1F/G3F/G1F times
are never compared across races.  Each observation is converted to a robust
within-race log-time figure first; only those relative figures are rolled into
future races.
"""

from __future__ import annotations

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames, as_date

GROUP = "C3. 구간 에너지 배분"
LOOKBACK = 5
_SECTION_CODES = ("S1F", "G3F", "G1F")
_LEAKAGE = "대상 경주의 구간시간 제외; horse별 shift(1) 후 과거 최대 5경주만 사용"

FEATURES = [
    FeatureSpec(
        name="energy_early_rel_avg5",
        group=GROUP,
        description="최근 5경주 S1F 경주내 상대시간 지수 평균(양수=동일 경주보다 빠름)",
        source="race_section_results.S1F.elapsed_time_ms",
        lookback="최근 5경주",
        leakage_note=_LEAKAGE,
    ),
    FeatureSpec(
        name="energy_g3f_rel_avg5",
        group=GROUP,
        description="최근 5경주 G3F 경주내 상대시간 지수 평균",
        source="race_section_results.G3F.elapsed_time_ms",
        lookback="최근 5경주",
        leakage_note=_LEAKAGE,
    ),
    FeatureSpec(
        name="energy_finish_rel_avg5",
        group=GROUP,
        description="최근 5경주 G1F 경주내 상대시간 지수 평균",
        source="race_section_results.G1F.elapsed_time_ms",
        lookback="최근 5경주",
        leakage_note=_LEAKAGE,
    ),
    FeatureSpec(
        name="energy_finish_change_avg5",
        group=GROUP,
        description="G1F 상대지수−G3F 상대지수 평균(양수=막판 상대 개선)",
        source="G1F/G3F 경주내 상대시간",
        lookback="최근 5경주",
        leakage_note=_LEAKAGE,
    ),
    FeatureSpec(
        name="energy_early_late_balance_avg5",
        group=GROUP,
        description="G1F 상대지수−S1F 상대지수 평균(양수=후반형)",
        source="S1F/G1F 경주내 상대시간",
        lookback="최근 5경주",
        leakage_note=_LEAKAGE,
    ),
    FeatureSpec(
        name="energy_resilience_avg5",
        group=GROUP,
        description="S1F와 G1F 상대지수 합 평균(초반 사용 후 종반 유지 능력)",
        source="S1F/G1F 경주내 상대시간",
        lookback="최근 5경주",
        leakage_note=_LEAKAGE,
    ),
    FeatureSpec(
        name="energy_finish_change_trend",
        group=GROUP,
        description="최근 2경주 막판 상대개선과 그 이전 최대 3경주의 차이",
        source="energy_finish_change",
        lookback="최근 5경주",
        null_policy="유효 4경주 미만이면 null",
        leakage_note=_LEAKAGE,
    ),
    FeatureSpec(
        name="energy_exact_distance_balance_avg5",
        group=GROUP,
        description="현재와 정확히 같은 거리에서의 최근 5경주 초후반 균형 평균",
        source="S1F/G1F + distance_m",
        lookback="동일거리 최근 5경주",
        leakage_note=_LEAKAGE,
    ),
    FeatureSpec(
        name="energy_profile_count5",
        group=GROUP,
        description="최근 5경주 중 S1F·G3F·G1F 상대시간이 모두 유효한 경주 수",
        source="race_section_results",
        lookback="최근 5경주",
        null_policy="이력 없으면 0",
        leakage_note=_LEAKAGE,
    ),
]


def _empty(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        *[
            pl.lit(0, dtype=pl.Int64).alias(spec.name)
            if spec.name == "energy_profile_count5"
            else pl.lit(None, dtype=pl.Float64).alias(spec.name)
            for spec in FEATURES
        ]
    )


def _relative_time(code: str) -> pl.Expr:
    time = pl.col(code)
    race_median = time.median().over("race_id")
    race_count = time.count().over("race_id")
    return (
        pl.when(time.is_not_null() & (time > 0) & (race_count >= 3))
        .then((race_median / time).log() * 100.0)
        .otherwise(None)
        .clip(-20.0, 20.0)
    )


def _rolling_mean(column: str, *, groups: str | list[str] = "horse_id") -> pl.Expr:
    return pl.col(column).shift(1).rolling_mean(window_size=LOOKBACK, min_samples=1).over(groups)


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    past = as_date(sources.past_results, "race_date")
    sections = as_date(sources.sections, "race_date")
    required = {"horse_id", "race_id", "section_code", "elapsed_time_ms"}
    if past.height == 0 or sections.height == 0 or not required <= set(sections.columns):
        return _empty(frame)

    pivoted = sections.filter(pl.col("section_code").is_in(_SECTION_CODES)).pivot(
        on="section_code",
        index=["horse_id", "race_id"],
        values="elapsed_time_ms",
        aggregate_function="first",
    )
    if pivoted.height == 0:
        return _empty(frame)
    for code in _SECTION_CODES:
        if code not in pivoted.columns:
            pivoted = pivoted.with_columns(pl.lit(None, dtype=pl.Float64).alias(code))
    pivoted = pivoted.select(
        "horse_id",
        "race_id",
        *(pl.col(code).cast(pl.Float64) for code in _SECTION_CODES),
    )
    history = (
        past.select("horse_id", "race_id", "race_entry_id", "race_date", "distance_m")
        .join(pivoted, on=["horse_id", "race_id"], how="left")
        .with_columns(
            _relative_time("S1F").alias("_early_rel"),
            _relative_time("G3F").alias("_g3f_rel"),
            _relative_time("G1F").alias("_finish_rel"),
        )
        .with_columns(
            (pl.col("_finish_rel") - pl.col("_g3f_rel")).alias("_finish_change"),
            (pl.col("_finish_rel") - pl.col("_early_rel")).alias("_balance"),
            (pl.col("_early_rel") + pl.col("_finish_rel")).alias("_resilience"),
            pl.all_horizontal(
                pl.col("_early_rel").is_not_null(),
                pl.col("_g3f_rel").is_not_null(),
                pl.col("_finish_rel").is_not_null(),
            )
            .cast(pl.Int64)
            .alias("_has_profile"),
        )
        .sort("horse_id", "race_date", "race_entry_id")
    )
    history = history.with_columns(
        _rolling_mean("_early_rel").alias("energy_early_rel_avg5"),
        _rolling_mean("_g3f_rel").alias("energy_g3f_rel_avg5"),
        _rolling_mean("_finish_rel").alias("energy_finish_rel_avg5"),
        _rolling_mean("_finish_change").alias("energy_finish_change_avg5"),
        _rolling_mean("_balance").alias("energy_early_late_balance_avg5"),
        _rolling_mean("_resilience").alias("energy_resilience_avg5"),
        (
            pl.col("_finish_change")
            .shift(1)
            .rolling_mean(window_size=2, min_samples=2)
            .over("horse_id")
            - pl.col("_finish_change")
            .shift(3)
            .rolling_mean(window_size=3, min_samples=2)
            .over("horse_id")
        ).alias("energy_finish_change_trend"),
        _rolling_mean("_balance", groups=["horse_id", "distance_m"]).alias(
            "energy_exact_distance_balance_avg5"
        ),
        pl.col("_has_profile")
        .shift(1)
        .fill_null(0)
        .rolling_sum(window_size=LOOKBACK, min_samples=1)
        .over("horse_id")
        .cast(pl.Int64)
        .alias("energy_profile_count5"),
    )
    feature_names = [spec.name for spec in FEATURES]
    features = history.select("race_entry_id", *feature_names).unique("race_entry_id")
    return frame.join(features, on="race_entry_id", how="left").with_columns(
        pl.col("energy_profile_count5").fill_null(0).cast(pl.Int64)
    )
