"""B그룹. 출전 정적 feature (원천: race_entries, horses 불변 속성)."""

from __future__ import annotations

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames

GROUP = "B. 출전 정적"

FEATURES = [
    FeatureSpec(
        name="horse_number",
        group=GROUP,
        description="공식 출발번호/게이트 번호 (기존 특성명 호환 유지)",
        source="race_entries.gate_number (결측 시 horse_number)",
    ),
    FeatureSpec(
        name="horse_number_pct",
        group=GROUP,
        description="출발번호 / 출주 두수 (경주 내 상대 위치)",
        source="파생",
    ),
    FeatureSpec(
        name="carried_weight_kg",
        group=GROUP,
        description="부담중량(kg)",
        source="race_entries.carried_weight_kg",
    ),
    FeatureSpec(
        name="carried_weight_rel",
        group=GROUP,
        description="부담중량 − 경주 평균",
        source="파생",
    ),
    FeatureSpec(
        name="load_ratio_pct",
        group=GROUP,
        description="부담중량/마체중 비율(%)",
        source="race_entries.carried_weight_kg / body_weight_kg",
        null_policy="마체중 결측·0이면 null",
        leakage_note="당일 마체중 사용. day_before_18 정책에서는 자동 제외",
    ),
    FeatureSpec(
        name="rating",
        group=GROUP,
        description="출전표 레이팅 (경주 전 공개)",
        source="race_entries.rating",
        null_policy="null 유지 (결측 12행)",
    ),
    FeatureSpec(
        name="body_weight_kg",
        group=GROUP,
        description="당일 마체중(kg) — start_minus_30m 정책 전용",
        source="race_entries.body_weight_kg",
        leakage_note="당일 공개. day_before_18 정책에서는 컬럼 자체가 제거됨",
    ),
    FeatureSpec(
        name="body_weight_change_kg",
        group=GROUP,
        description="공식 체중 증감(kg) — start_minus_30m 정책 전용",
        source="race_entries.body_weight_change_kg",
        leakage_note="당일 공개",
    ),
    FeatureSpec(
        name="horse_age_months",
        group=GROUP,
        description="경주일 기준 말 나이(월)",
        source="horses.birth_date (불변 속성)",
    ),
    FeatureSpec(
        name="horse_sex",
        group=GROUP,
        description="성별 (수/암/거세)",
        source="horses.sex",
        leakage_note="med — 현재 스냅샷 값. 거세 전 과거 경주에 소급될 수 있음",
    ),
    FeatureSpec(
        name="horse_origin",
        group=GROUP,
        description="산지 (범주)",
        source="horses.origin_country (불변 속성)",
    ),
]


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    static = sources.horse_static
    if static.height > 0:
        frame = frame.join(
            static.rename({"sex": "horse_sex", "origin_country": "horse_origin"}),
            on="horse_id",
            how="left",
        )
        frame = frame.with_columns(
            ((pl.col("race_date") - pl.col("birth_date")).dt.total_days() / 30.44)
            .round(1)
            .alias("horse_age_months")
        ).drop("birth_date")
    else:
        frame = frame.with_columns(
            pl.lit(None).cast(pl.Float64).alias("horse_age_months"),
            pl.lit(None).cast(pl.Utf8).alias("horse_sex"),
            pl.lit(None).cast(pl.Utf8).alias("horse_origin"),
        )

    if "gate_number" in frame.columns:
        frame = frame.with_columns(
            pl.coalesce("gate_number", "horse_number").alias("horse_number")
        )

    expressions = [
        (pl.col("horse_number") / pl.col("starters")).alias("horse_number_pct"),
        (pl.col("carried_weight_kg") - pl.col("carried_weight_kg").mean().over("race_id")).alias(
            "carried_weight_rel"
        ),
    ]
    if "body_weight_kg" in frame.columns:
        expressions.append(
            pl.when(pl.col("body_weight_kg") > 0)
            .then(100 * pl.col("carried_weight_kg") / pl.col("body_weight_kg"))
            .otherwise(None)
            .alias("load_ratio_pct")
        )
    return frame.with_columns(expressions)
