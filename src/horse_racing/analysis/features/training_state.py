"""G+ group. Training load and within-horse baseline features.

All windows exclude events on the race date.  The 29--180 day portion acts as
the horse's recent personal baseline, avoiding direct comparisons between
horses whose stables use different training routines.
"""

from __future__ import annotations

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames, rolling_event_counts

GROUP = "G+. 조교 부하·개인기준"

FEATURES = [
    FeatureSpec(
        name="train_prior_n_29_180d",
        group=GROUP,
        description="직전 29~180일 훈련일 수(개인 기준의 증거량)",
        source="horse_training",
        lookback="29~180일",
        null_policy="이력 없으면 0",
        leakage_note="event_date < race_date, 최근 28일과 분리",
    ),
    FeatureSpec(
        name="train_frequency_ratio_7_28",
        group=GROUP,
        description="최근 7일 일평균 훈련빈도 / 최근 28일 일평균(평활)",
        source="train_n_7d + train_n_28d",
        lookback="7일 / 28일",
        null_policy="평활값 사용",
    ),
    FeatureSpec(
        name="train_frequency_dev_28_prior",
        group=GROUP,
        description="최근 28일 훈련일 수 − 이전 152일에서 환산한 28일 기대치",
        source="horse_training",
        lookback="최근 28일 vs 이전 152일",
        null_policy="이전 구간 이력 없으면 null",
    ),
    FeatureSpec(
        name="train_frequency_ratio_28_prior",
        group=GROUP,
        description="최근 28일 훈련빈도 / 이전 152일 개인 기준(평활)",
        source="horse_training",
        lookback="최근 28일 vs 이전 152일",
        null_policy="이전 구간 이력 없으면 null",
    ),
    FeatureSpec(
        name="train_avg_duration_28d",
        group=GROUP,
        description="최근 28일 훈련 1회당 평균 시간(초)",
        source="train_dur_28d / train_n_28d",
        lookback="28일",
        null_policy="훈련 0회면 null",
    ),
    FeatureSpec(
        name="train_gallop_per_day_28d",
        group=GROUP,
        description="최근 28일 훈련일당 습보 횟수",
        source="gallop_n_28d / train_n_28d",
        lookback="28일",
        null_policy="훈련 0회면 null",
    ),
    FeatureSpec(
        name="train_canter_per_day_28d",
        group=GROUP,
        description="최근 28일 훈련일당 구보 횟수",
        source="canter_n_28d / train_n_28d",
        lookback="28일",
        null_policy="훈련 0회면 null",
    ),
]


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    required = {
        "train_n_7d",
        "train_n_28d",
        "train_dur_28d",
        "gallop_n_28d",
        "canter_n_28d",
    }
    if not required <= set(frame.columns):
        return _empty(frame)

    augmented = rolling_event_counts(
        frame,
        sources.training,
        key="horse_id",
        base_date_col="race_date",
        windows_days=(180,),
        prefix="_train_history",
    )
    prior = (
        pl.col("_train_history_n_180d") - pl.col("train_n_28d")
    ).clip(lower_bound=0)
    expected_28 = prior.cast(pl.Float64) * (28.0 / 152.0)
    train_28 = pl.col("train_n_28d").cast(pl.Float64)
    has_prior = prior > 0
    has_recent = train_28 > 0
    return augmented.with_columns(
        prior.cast(pl.Int64).alias("train_prior_n_29_180d"),
        (4.0 * (pl.col("train_n_7d") + 1.0) / (train_28 + 4.0)).alias(
            "train_frequency_ratio_7_28"
        ),
        pl.when(has_prior)
        .then(train_28 - expected_28)
        .otherwise(None)
        .alias("train_frequency_dev_28_prior"),
        pl.when(has_prior)
        .then((train_28 + 1.0) / (expected_28 + 1.0))
        .otherwise(None)
        .alias("train_frequency_ratio_28_prior"),
        pl.when(has_recent)
        .then(pl.col("train_dur_28d") / train_28)
        .otherwise(None)
        .alias("train_avg_duration_28d"),
        pl.when(has_recent)
        .then(pl.col("gallop_n_28d") / train_28)
        .otherwise(None)
        .alias("train_gallop_per_day_28d"),
        pl.when(has_recent)
        .then(pl.col("canter_n_28d") / train_28)
        .otherwise(None)
        .alias("train_canter_per_day_28d"),
    ).drop("_train_history_n_180d")


def _empty(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.lit(0).cast(pl.Int64).alias("train_prior_n_29_180d"),
        pl.lit(None).cast(pl.Float64).alias("train_frequency_ratio_7_28"),
        pl.lit(None).cast(pl.Float64).alias("train_frequency_dev_28_prior"),
        pl.lit(None).cast(pl.Float64).alias("train_frequency_ratio_28_prior"),
        pl.lit(None).cast(pl.Float64).alias("train_avg_duration_28d"),
        pl.lit(None).cast(pl.Float64).alias("train_gallop_per_day_28d"),
        pl.lit(None).cast(pl.Float64).alias("train_canter_per_day_28d"),
    )
