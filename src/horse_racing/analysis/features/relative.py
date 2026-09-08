"""I그룹. 경주 내 상대값 feature (z-score, rank).

다른 그룹이 만든 절대값 feature를 같은 경주 출전마들 사이에서 표준화한다.
대상 컬럼이 데이터셋에 없으면(정책·버전 차이) 자동으로 건너뛴다.
반드시 **마지막**에 적용한다.
"""

from __future__ import annotations

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames

GROUP = "I. 경주 내 상대값"

# 상대화 대상 절대값 컬럼. C~H 그룹 feature가 추가되면 여기에 등록한다.
RELATIVE_TARGETS = [
    "rating",
    "carried_weight_kg",
    "body_weight_kg",
    "horse_age_months",
    "form_recent5_pct",
    "form_recent5_median_pct",
    "speed_avg_mps_5",
    "speed_rel_median5",
    "speed_figure_median5",
    "speed_figure_exact_distance_avg5",
    "early_pos_pct_avg5",
    "late_gain_pct_avg5",
    "exact_distance_top3_rate",
    "ability_elo_global",
    "ability_elo_context",
    "jockey_win_rate_90d",
    "trainer_win_rate_90d",
]

FEATURES = [
    spec
    for target in RELATIVE_TARGETS
    for spec in (
        FeatureSpec(
            name=f"{target}_race_z",
            group=GROUP,
            description=f"{target}의 경주 내 z-score",
            source="파생",
            null_policy="경주 내 표준편차 0이면 null",
        ),
        FeatureSpec(
            name=f"{target}_race_rank",
            group=GROUP,
            description=f"{target}의 경주 내 순위 (내림차순, 동률 평균)",
            source="파생",
        ),
    )
]


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    exprs = []
    for target in RELATIVE_TARGETS:
        if target not in frame.columns:
            continue
        mean = pl.col(target).mean().over("race_id")
        std = pl.col(target).std().over("race_id")
        exprs.append(
            pl.when(std > 0)
            .then((pl.col(target) - mean) / std)
            .otherwise(None)
            .alias(f"{target}_race_z")
        )
        exprs.append(
            pl.col(target)
            .rank("average", descending=True)
            .over("race_id")
            .cast(pl.Float64)
            .alias(f"{target}_race_rank")
        )
    return frame.with_columns(exprs) if exprs else frame
