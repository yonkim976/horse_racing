"""G1 group. Observable proxies for the horse's latent current condition."""

from __future__ import annotations

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames

GROUP = "G1. 잠재 컨디션 상태"

FEATURES = [
    FeatureSpec(
        name="condition_speed_delta",
        group=GROUP,
        description="최근 3경주 보정속도 평균−최근 5경주 중앙값",
        source="speed_figure_avg3 - speed_figure_median5",
        lookback="최근 최대 5경주",
        leakage_note="두 입력 모두 현재 경주 이전 기록만 사용",
    ),
    FeatureSpec(
        name="condition_form_delta",
        group=GROUP,
        description="최근 5경주 착순백분위−최근 3경주 평균(양수=최근 상승)",
        source="form_recent5_pct - form_recent3_pct",
        lookback="최근 최대 5경주",
        leakage_note="현재 경주 이전 착순만 사용",
    ),
    FeatureSpec(
        name="condition_weight_z",
        group=GROUP,
        description="현재 체중의 말별 최근 정상범위 이탈 z-score",
        source="body_weight_dev / body_weight_std5",
        lookback="과거 최대 5경주",
        null_policy="당일 체중 또는 과거 표준편차가 없으면 null",
        leakage_note="start_minus_30m에서 공개된 현재 체중만 사용",
    ),
    FeatureSpec(
        name="condition_state",
        group=GROUP,
        description="최근 보정속도와 착순 추세를 결합한 [-1,1] 컨디션 상태",
        source="condition_speed_delta + condition_form_delta",
        lookback="최근 최대 5경주",
        leakage_note="현재 경주 이전 성적만 사용",
    ),
    FeatureSpec(
        name="condition_evidence",
        group=GROUP,
        description="컨디션 상태의 유효 보정속도 근거량(0~1)",
        source="speed_figure_count5 / 5",
        lookback="최근 5경주",
        null_policy="이력 없으면 0",
        leakage_note="현재 경주 이전 기록만 사용",
    ),
    FeatureSpec(
        name="condition_uncertainty",
        group=GROUP,
        description="기초능력·최근기록 부족과 신마·장기휴양을 결합한 불확실성(0~1)",
        source="ability_elo_uncertainty + speed_figure_count5 + debut/layoff",
        lookback="경주 전 전체 이력",
        leakage_note="현재 경주 이전 표본수와 출전간격만 사용",
    ),
]


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    del sources
    columns = set(frame.columns)
    speed_delta = (
        pl.col("speed_figure_avg3") - pl.col("speed_figure_median5")
        if {"speed_figure_avg3", "speed_figure_median5"} <= columns
        else pl.lit(None, dtype=pl.Float64)
    )
    form_delta = (
        pl.col("form_recent5_pct") - pl.col("form_recent3_pct")
        if {"form_recent5_pct", "form_recent3_pct"} <= columns
        else pl.lit(None, dtype=pl.Float64)
    )
    frame = frame.with_columns(
        speed_delta.alias("condition_speed_delta"),
        form_delta.alias("condition_form_delta"),
    )
    if {"body_weight_dev", "body_weight_std5"} <= columns:
        frame = frame.with_columns(
            pl.when(pl.col("body_weight_std5") > 0)
            .then(pl.col("body_weight_dev") / pl.col("body_weight_std5"))
            .otherwise(None)
            .clip(-5.0, 5.0)
            .alias("condition_weight_z")
        )

    speed_component = pl.col("condition_speed_delta").fill_null(0.0).truediv(2.0).tanh()
    form_component = pl.col("condition_form_delta").fill_null(0.0).mul(3.0).tanh()
    evidence = (
        pl.col("speed_figure_count5").fill_null(0).cast(pl.Float64).truediv(5.0)
        if "speed_figure_count5" in columns
        else pl.lit(0.0)
    )
    elo_uncertainty = (
        pl.col("ability_elo_uncertainty").fill_null(1.0)
        if "ability_elo_uncertainty" in columns
        else pl.lit(1.0)
    )
    is_debut = (
        pl.col("is_debut").fill_null(1).cast(pl.Float64) if "is_debut" in columns else pl.lit(1.0)
    )
    long_layoff = (
        pl.col("long_layoff").fill_null(0).cast(pl.Float64)
        if "long_layoff" in columns
        else pl.lit(0.0)
    )
    return frame.with_columns(
        ((0.65 * speed_component + 0.35 * form_component) * evidence.sqrt()).alias(
            "condition_state"
        ),
        evidence.clip(0.0, 1.0).alias("condition_evidence"),
        (0.45 * elo_uncertainty + 0.35 * (1.0 - evidence) + 0.15 * is_debut + 0.05 * long_layoff)
        .clip(0.0, 1.0)
        .alias("condition_uncertainty"),
    )
