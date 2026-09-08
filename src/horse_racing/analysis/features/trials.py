"""G+그룹. 주행심사 point-in-time feature.

모든 집계는 예측 대상 경주일보다 엄격히 이전인 심사만 사용한다. 같은 날 심사는
공개 시점이 불확실하므로 제외한다.
"""

from __future__ import annotations

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames

GROUP = "G+. 주행심사"
WINDOW_DAYS = 180

FEATURES = [
    FeatureSpec(
        name="trial_n_180d",
        group=GROUP,
        description="경주 전 180일 주행심사 참가 횟수",
        source="running_trial_results + running_trials",
        lookback="180일",
        null_policy="이력 없으면 0",
        leakage_note="trial_date < race_date, 당일 심사 제외",
    ),
    FeatureSpec(
        name="trial_pass_n_180d",
        group=GROUP,
        description="경주 전 180일 주행심사 합격 횟수",
        source="running_trial_results.judgement='합'",
        lookback="180일",
        null_policy="이력 없으면 0",
        leakage_note="trial_date < race_date",
    ),
    FeatureSpec(
        name="trial_fail_n_180d",
        group=GROUP,
        description="경주 전 180일 주행심사 불합격 횟수",
        source="running_trial_results.judgement='불'",
        lookback="180일",
        null_policy="이력 없으면 0",
        leakage_note="trial_date < race_date",
    ),
    FeatureSpec(
        name="days_since_trial",
        group=GROUP,
        description="가장 최근 주행심사 후 경과일",
        source="running_trials.trial_date_local",
        lookback="직전 1회",
        null_policy="이력 없으면 null",
        leakage_note="trial_date < race_date",
    ),
    FeatureSpec(
        name="last_trial_passed",
        group=GROUP,
        description="최근 심사 판정: 합격 1, 불합격 0, 기타 null",
        source="running_trial_results.judgement",
        lookback="직전 1회",
        null_policy="합·불 외 판정 또는 이력 없으면 null",
        leakage_note="엄격히 이전인 마지막 심사",
    ),
    FeatureSpec(
        name="last_trial_time_per_100m",
        group=GROUP,
        description="최근 심사 100m당 기록(초)",
        source="finish_time_ms / distance_m",
        lookback="직전 1회",
        null_policy="완주 기록 없으면 null",
        leakage_note="엄격히 이전인 마지막 심사",
    ),
    FeatureSpec(
        name="last_trial_finish_percentile",
        group=GROUP,
        description="최근 심사 순위/참가두수 비율(낮을수록 우수)",
        source="finish_position / field_size",
        lookback="직전 1회",
        null_policy="정상 순위 없으면 null",
        leakage_note="엄격히 이전인 마지막 심사",
    ),
    FeatureSpec(
        name="last_trial_s1f_sec",
        group=GROUP,
        description="최근 심사 S1F 기록(초)",
        source="running_trial_results.s1f_ms",
        lookback="직전 1회",
        null_policy="구간 기록 없으면 null",
        leakage_note="엄격히 이전인 마지막 심사",
    ),
    FeatureSpec(
        name="last_trial_g3f_sec",
        group=GROUP,
        description="최근 심사 G3F 기록(초)",
        source="running_trial_results.g3f_ms",
        lookback="직전 1회",
        null_policy="구간 기록 없으면 null",
        leakage_note="엄격히 이전인 마지막 심사",
    ),
    FeatureSpec(
        name="last_trial_g1f_sec",
        group=GROUP,
        description="최근 심사 G1F 기록(초)",
        source="running_trial_results.g1f_ms",
        lookback="직전 1회",
        null_policy="구간 기록 없으면 null",
        leakage_note="엄격히 이전인 마지막 심사",
    ),
    FeatureSpec(
        name="last_trial_body_weight_kg",
        group=GROUP,
        description="최근 심사 당시 마체중",
        source="running_trial_results.body_weight_kg",
        lookback="직전 1회",
        null_policy="취소·미계량이면 null",
        leakage_note="엄격히 이전인 마지막 심사",
    ),
    FeatureSpec(
        name="last_trial_newcomer_exam",
        group=GROUP,
        description="최근 심사가 신마 주행심사이면 1",
        source="running_trial_results.inspection_reason",
        lookback="직전 1회",
        null_policy="이력 없으면 null",
        leakage_note="엄격히 이전인 마지막 심사",
    ),
]

_COUNT_FEATURES = ("trial_n_180d", "trial_pass_n_180d", "trial_fail_n_180d")
_FLOAT_FEATURES = (
    "last_trial_time_per_100m",
    "last_trial_finish_percentile",
    "last_trial_s1f_sec",
    "last_trial_g3f_sec",
    "last_trial_g1f_sec",
    "last_trial_body_weight_kg",
)


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    events = sources.running_trials
    if events.height == 0:
        return _empty_features(frame)

    joined = frame.select("horse_id", "race_date").unique().join(
        events, on="horse_id", how="inner"
    )
    joined = joined.filter(pl.col("event_date") < pl.col("race_date"))
    if joined.height == 0:
        return _empty_features(frame)

    joined = joined.with_columns(
        (pl.col("race_date") - pl.col("event_date")).dt.total_days().alias("_days_before"),
        pl.when(pl.col("judgement") == "합")
        .then(1)
        .when(pl.col("judgement") == "불")
        .then(0)
        .otherwise(None)
        .cast(pl.Int8)
        .alias("_passed"),
        (pl.col("finish_time_ms") / (pl.col("distance_m") * 10)).alias("_time_per_100m"),
        (pl.col("finish_position") / pl.col("field_size")).alias("_finish_percentile"),
        (pl.col("s1f_ms") / 1000).alias("_s1f_sec"),
        (pl.col("g3f_ms") / 1000).alias("_g3f_sec"),
        (pl.col("g1f_ms") / 1000).alias("_g1f_sec"),
        pl.col("inspection_reason")
        .str.contains("(신)", literal=True)
        .cast(pl.Int8)
        .alias("_newcomer_exam"),
    )

    in_window = pl.col("_days_before") <= WINDOW_DAYS
    counts = joined.group_by("horse_id", "race_date").agg(
        in_window.sum().cast(pl.Int64).alias("trial_n_180d"),
        (in_window & (pl.col("judgement") == "합"))
        .sum()
        .cast(pl.Int64)
        .alias("trial_pass_n_180d"),
        (in_window & (pl.col("judgement") == "불"))
        .sum()
        .cast(pl.Int64)
        .alias("trial_fail_n_180d"),
    )

    latest = (
        joined.sort(
            "horse_id",
            "race_date",
            "event_date",
            "trial_race_number",
            "trial_id",
        )
        .group_by("horse_id", "race_date")
        .agg(
            pl.col("event_date").last().alias("_last_trial_date"),
            pl.col("_passed").last().alias("last_trial_passed"),
            pl.col("_time_per_100m").last().alias("last_trial_time_per_100m"),
            pl.col("_finish_percentile").last().alias("last_trial_finish_percentile"),
            pl.col("_s1f_sec").last().alias("last_trial_s1f_sec"),
            pl.col("_g3f_sec").last().alias("last_trial_g3f_sec"),
            pl.col("_g1f_sec").last().alias("last_trial_g1f_sec"),
            pl.col("body_weight_kg")
            .last()
            .cast(pl.Float64)
            .alias("last_trial_body_weight_kg"),
            pl.col("_newcomer_exam").last().alias("last_trial_newcomer_exam"),
        )
        .with_columns(
            (pl.col("race_date") - pl.col("_last_trial_date"))
            .dt.total_days()
            .cast(pl.Int64)
            .alias("days_since_trial")
        )
        .drop("_last_trial_date")
    )
    return (
        frame.join(counts, on=["horse_id", "race_date"], how="left")
        .join(latest, on=["horse_id", "race_date"], how="left")
        .with_columns(pl.col(*_COUNT_FEATURES).fill_null(0))
    )


def _empty_features(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        *(pl.lit(0).cast(pl.Int64).alias(name) for name in _COUNT_FEATURES),
        pl.lit(None).cast(pl.Int64).alias("days_since_trial"),
        pl.lit(None).cast(pl.Int8).alias("last_trial_passed"),
        *(pl.lit(None).cast(pl.Float64).alias(name) for name in _FLOAT_FEATURES),
        pl.lit(None).cast(pl.Int8).alias("last_trial_newcomer_exam"),
    )
