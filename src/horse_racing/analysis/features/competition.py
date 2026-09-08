"""D+그룹. 경주 전 예상 전개와 코스·게이트 상호작용.

각 말의 과거 S1F 성향만 사용해 같은 경주의 강선행형 수와 자기 자신을 제외한
선행 경쟁자 수를 계산한다. 현재 경주의 구간기록이나 결과는 사용하지 않는다.
"""

from __future__ import annotations

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames

GROUP = "D+. 예상 전개·코스 상호작용"
MIN_STYLE_COVERAGE = 2
MIN_KNOWN_SHARE = 0.70
STRONG_FRONT_THRESHOLD = 0.25

FEATURES = [
    FeatureSpec(
        name="course_distance_key",
        group=GROUP,
        description="경마장×정확한 거리 범주",
        source="meet_code + distance_m",
    ),
    FeatureSpec(
        name="gate_band",
        group=GROUP,
        description="출전두수 대비 안쪽/중간/바깥쪽 게이트",
        source="horse_number_pct",
    ),
    FeatureSpec(
        name="course_distance_gate_band",
        group=GROUP,
        description="경마장×정확한 거리×게이트 구역 범주",
        source="파생",
    ),
    FeatureSpec(
        name="known_style_share",
        group=GROUP,
        description="출전마 중 과거 S1F 2회 이상인 말의 비율",
        source="early_pos_pct_avg5 + section_coverage5",
        lookback="출전마별 최근 5경주",
        leakage_note="low — 과거 구간기록만 사용",
    ),
    FeatureSpec(
        name="front_runner_count",
        group=GROUP,
        description="경주 내 강선행형(과거 평균 S1F 상위 25%) 출전마 수",
        source="early_pos_pct_avg5",
        lookback="출전마별 최근 5경주",
        leakage_note="low — 과거 구간기록만 사용",
    ),
    FeatureSpec(
        name="front_rival_count",
        group=GROUP,
        description="자기 자신을 제외한 강선행 경쟁자 수",
        source="front_runner_count",
        lookback="출전마별 최근 5경주",
        leakage_note="low — 과거 구간기록만 사용",
    ),
    FeatureSpec(
        name="pace_pressure",
        group=GROUP,
        description="선행 경쟁자 수 범주(없음/1두/2두이상), 성향 확인률 70% 미만은 null",
        source="front_rival_count + known_style_share",
        lookback="출전마별 최근 5경주",
        null_policy="성향 확인률 70% 미만이면 null",
        leakage_note="low — 과거 구간기록만 사용",
    ),
    FeatureSpec(
        name="style_pace_key",
        group=GROUP,
        description="자기 주행 성향×예상 선행 경합 범주",
        source="style_category + pace_pressure",
        lookback="출전마별 최근 5경주",
        null_policy="둘 중 하나가 없으면 null",
        leakage_note="low — 과거 구간기록만 사용",
    ),
    FeatureSpec(
        name="style_gate_key",
        group=GROUP,
        description="자기 주행 성향×게이트 구역 범주",
        source="style_category + gate_band",
        lookback="출전마별 최근 5경주",
        null_policy="주행 성향이 없으면 null",
        leakage_note="low — 과거 구간기록과 현재 출전표만 사용",
    ),
]


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    known = (
        pl.col("early_pos_pct_avg5").is_not_null()
        & (pl.col("section_coverage5") >= MIN_STYLE_COVERAGE)
    )
    strong_front = known & (pl.col("early_pos_pct_avg5") <= STRONG_FRONT_THRESHOLD)
    frame = frame.with_columns(
        pl.concat_str(
            [pl.col("meet_code").cast(pl.Utf8), pl.col("distance_m").cast(pl.Utf8)],
            separator="_",
        ).alias("course_distance_key"),
        pl.when(pl.col("horse_number_pct") <= 1 / 3)
        .then(pl.lit("안쪽"))
        .when(pl.col("horse_number_pct") <= 2 / 3)
        .then(pl.lit("중간"))
        .otherwise(pl.lit("바깥쪽"))
        .alias("gate_band"),
        (known.cast(pl.Int64).sum().over("race_id") / pl.col("starters")).alias(
            "known_style_share"
        ),
        strong_front.cast(pl.Int64).sum().over("race_id").alias("front_runner_count"),
        strong_front.cast(pl.Int64).alias("_is_strong_front"),
    ).with_columns(
        (pl.col("front_runner_count") - pl.col("_is_strong_front")).alias(
            "front_rival_count"
        ),
        pl.concat_str(["course_distance_key", "gate_band"], separator="_").alias(
            "course_distance_gate_band"
        ),
    )
    frame = frame.with_columns(
        pl.when(pl.col("known_style_share") < MIN_KNOWN_SHARE)
        .then(pl.lit(None, dtype=pl.Utf8))
        .when(pl.col("front_rival_count") == 0)
        .then(pl.lit("경합없음"))
        .when(pl.col("front_rival_count") == 1)
        .then(pl.lit("1두경합"))
        .otherwise(pl.lit("2두이상경합"))
        .alias("pace_pressure")
    ).with_columns(
        pl.when(pl.col("style_category").is_not_null() & pl.col("pace_pressure").is_not_null())
        .then(pl.concat_str(["style_category", "pace_pressure"], separator="_"))
        .otherwise(None)
        .alias("style_pace_key"),
        pl.when(pl.col("style_category").is_not_null())
        .then(pl.concat_str(["style_category", "gate_band"], separator="_"))
        .otherwise(None)
        .alias("style_gate_key"),
    )
    return frame.drop("_is_strong_front")

