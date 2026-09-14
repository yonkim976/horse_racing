"""Canonical section-energy research features (separate from legacy energy)."""

from __future__ import annotations

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames, as_date
from horse_racing.analysis.features.canonical_sections import canonicalize_sections

GROUP = "C3C. canonical 구간 에너지 배분"
LOOKBACK = 5
_LEAKAGE = "대상 경주 제외; 명시적 time_basis의 정상 과거 완주만 사용"

def _spec(
    name: str,
    description: str,
    source: str = "canonical sections",
    lookback: str = "최근 5경주",
    null_policy: str = "null 유지",
) -> FeatureSpec:
    return FeatureSpec(name, GROUP, description, source, lookback, null_policy, _LEAKAGE)


FEATURES = [
    _spec("canonical_energy_early_rel_avg5", "최근 5경주 확정 S1F 상대시간", "canonical S1F"),
    _spec("canonical_energy_last600_rel_avg5", "최근 5경주 마지막 600m 상대시간"),
    _spec("canonical_energy_last200_rel_avg5", "최근 5경주 마지막 200m 상대시간"),
    _spec(
        "canonical_energy_middle400_rel_avg5",
        "최근 5경주 마지막 600m 중 앞 400m 상대시간",
        "last_600-last_200",
    ),
    _spec("canonical_energy_finish_change_avg5", "마지막 200m 상대지수-600m 상대지수"),
    _spec("canonical_energy_early_late_balance_avg5", "마지막 200m 상대지수-S1F 상대지수"),
    _spec("canonical_energy_resilience_avg5", "S1F와 마지막 200m 상대지수 합"),
    _spec(
        "canonical_energy_finish_change_trend",
        "최근 종반 상대개선 추세",
        null_policy="유효 4경주 미만이면 null",
    ),
    _spec(
        "canonical_energy_exact_distance_balance_avg5",
        "동일거리 canonical 초후반 균형",
        lookback="동일거리 최근 5경주",
    ),
    _spec(
        "canonical_energy_profile_count5",
        "최근 5경주 canonical profile 수",
        null_policy="이력 없으면 0",
    ),
]


def _empty(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(*[
        pl.lit(0, dtype=pl.Int64).alias(spec.name)
        if spec.name == "canonical_energy_profile_count5"
        else pl.lit(None, dtype=pl.Float64).alias(spec.name)
        for spec in FEATURES
    ])


def _relative(column: str) -> pl.Expr:
    value = pl.col(column).cast(pl.Float64)
    count = value.count().over("race_id")
    return pl.when(value.is_not_null() & (value > 0) & (count >= 3)).then(
        (value.median().over("race_id") / value).log() * 100.0
    ).otherwise(None).clip(-20.0, 20.0)


def _rolling(column: str, groups: str | list[str] = "horse_id") -> pl.Expr:
    return pl.col(column).shift(1).rolling_mean(LOOKBACK, min_samples=1).over(groups)


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    past = as_date(sources.past_results, "race_date")
    canonical = canonicalize_sections(as_date(sources.sections, "race_date"))
    if past.height == 0 or canonical.height == 0:
        return _empty(frame)
    history = (
        past.select("horse_id", "race_id", "race_entry_id", "race_date", "distance_m")
        .join(canonical.select(
            "race_entry_id", "canonical_s1f_ms", "canonical_last_600_ms",
            "canonical_last_200_ms", "canonical_middle_400_ms",
            "canonical_profile_available",
        ), on="race_entry_id", how="left")
        .with_columns(
            _relative("canonical_s1f_ms").alias("_early"),
            _relative("canonical_last_600_ms").alias("_last600"),
            _relative("canonical_last_200_ms").alias("_last200"),
            _relative("canonical_middle_400_ms").alias("_middle400"),
        )
        .with_columns(
            (pl.col("_last200") - pl.col("_last600")).alias("_change"),
            (pl.col("_last200") - pl.col("_early")).alias("_balance"),
            (pl.col("_early") + pl.col("_last200")).alias("_resilience"),
        )
        .sort("horse_id", "race_date", "race_entry_id")
        .with_columns(
            _rolling("_early").alias("canonical_energy_early_rel_avg5"),
            _rolling("_last600").alias("canonical_energy_last600_rel_avg5"),
            _rolling("_last200").alias("canonical_energy_last200_rel_avg5"),
            _rolling("_middle400").alias("canonical_energy_middle400_rel_avg5"),
            _rolling("_change").alias("canonical_energy_finish_change_avg5"),
            _rolling("_balance").alias("canonical_energy_early_late_balance_avg5"),
            _rolling("_resilience").alias("canonical_energy_resilience_avg5"),
            (pl.col("_change").shift(1).rolling_mean(2, min_samples=2).over("horse_id")
             - pl.col("_change").shift(3).rolling_mean(3, min_samples=2).over("horse_id"))
            .alias("canonical_energy_finish_change_trend"),
            _rolling("_balance", ["horse_id", "distance_m"]).alias(
                "canonical_energy_exact_distance_balance_avg5"
            ),
            pl.col("canonical_profile_available").fill_null(0).shift(1).fill_null(0)
            .rolling_sum(LOOKBACK, min_samples=1).over("horse_id").cast(pl.Int64)
            .alias("canonical_energy_profile_count5"),
        )
    )
    names = [spec.name for spec in FEATURES]
    features = history.select("race_entry_id", *names).unique("race_entry_id")
    return frame.join(features, on="race_entry_id", how="left").with_columns(
        pl.col("canonical_energy_profile_count5").fill_null(0).cast(pl.Int64)
    )
