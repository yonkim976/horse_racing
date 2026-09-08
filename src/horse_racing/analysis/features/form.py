"""C그룹. 말 Form feature (원천: 과거 race_results + races).

past_results를 (horse_id, race_date, race_id)로 정렬한 뒤 horse_id 그룹 내
shift(1)·rolling·cum_sum으로 **직전까지**의 값을 만들고 race_entry_id로
데이터셋에 join한다. 현재 경주 결과(라벨)는 쓰지 않는다.
"""

from __future__ import annotations

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames

GROUP = "C. 말 Form"

_SOURCE = "past_results (race_results + races, 정상 착순 1~89)"
_DIST_BAND_M = 200
_LONG_LAYOFF_DAYS = 90
_SEOUL_BUSAN_MEETS = [1, 3]
_JEJU_MEET = 2
_SEOUL_BUSAN_MPS = (12.0, 18.0)
_JEJU_MPS = (10.0, 13.5)

_SEQUENTIAL = [
    "career_starts",
    "finish_pos_last",
    "form_recent3_pct",
    "form_recent5_pct",
    "form_recent5_median_pct",
    "form_recent5_best_pct",
    "top3_rate_recent5",
    "win_rate_career",
    "top3_rate_career",
    "days_since_last_race",
    "long_layoff",
    "speed_avg_mps_3",
    "speed_avg_mps_5",
    "speed_best_mps_5",
    "speed_rel_avg5",
    "speed_rel_median5",
    "speed_rel_best5",
    "distance_change_m",
]

FEATURES = [
    FeatureSpec(
        name="career_starts",
        group=GROUP,
        description="과거 정상 완주 횟수 (0이면 신마)",
        source=_SOURCE,
        lookback="career",
        null_policy="0 (신마)",
        leakage_note="low — 그룹 내 행 인덱스(현재 경주 미포함)",
    ),
    FeatureSpec(
        name="is_debut",
        group=GROUP,
        description="신마 여부 (career_starts==0, 0/1)",
        source=_SOURCE,
        lookback="career",
        null_policy="career_starts에서 파생 (결측 없음)",
        leakage_note="low",
    ),
    FeatureSpec(
        name="finish_pos_last",
        group=GROUP,
        description="직전 경주 착순",
        source=_SOURCE,
        lookback="직전 1경주",
        null_policy="과거 경주 없으면 null",
        leakage_note="low — shift(1)로 현재 경주 제외",
    ),
    FeatureSpec(
        name="form_recent3_pct",
        group=GROUP,
        description="최근 3경주 착순 백분위 평균. (pos−1)/(starters−1), 0=1착",
        source=_SOURCE,
        lookback="최근 3경주",
        null_policy="과거 없으면 null. 1~2경주면 있는 것만 평균. starters=1은 0",
        leakage_note="low — rolling 후 shift(1)",
    ),
    FeatureSpec(
        name="form_recent5_pct",
        group=GROUP,
        description="최근 5경주 착순 백분위 평균. (pos−1)/(starters−1), 0=1착",
        source=_SOURCE,
        lookback="최근 5경주",
        null_policy="과거 없으면 null. 1~4경주면 있는 것만 평균. starters=1은 0",
        leakage_note="low — rolling 후 shift(1)",
    ),
    FeatureSpec(
        name="form_recent5_median_pct",
        group=GROUP,
        description="최근 5경주 착순 백분위 중앙값 (극단적 하위 착순 영향 완화)",
        source=_SOURCE,
        lookback="최근 5경주",
        null_policy="과거 없으면 null",
        leakage_note="low — rolling 후 shift(1)",
    ),
    FeatureSpec(
        name="form_recent5_best_pct",
        group=GROUP,
        description="최근 5경주 최고 착순 백분위 (작을수록 좋음)",
        source=_SOURCE,
        lookback="최근 5경주",
        null_policy="과거 없으면 null",
        leakage_note="low — rolling 후 shift(1)",
    ),
    FeatureSpec(
        name="top3_rate_recent5",
        group=GROUP,
        description="최근 5경주 3위 내 비율",
        source=_SOURCE,
        lookback="최근 5경주",
        null_policy="과거 없으면 null",
        leakage_note="low — rolling 후 shift(1)",
    ),
    FeatureSpec(
        name="win_rate_career",
        group=GROUP,
        description="과거 전체 승률 (finish_position==1)",
        source=_SOURCE,
        lookback="career",
        null_policy="과거 0경주면 null",
        leakage_note="low — cum_sum 후 shift(1)",
    ),
    FeatureSpec(
        name="top3_rate_career",
        group=GROUP,
        description="과거 전체 복승률 (finish_position<=3)",
        source=_SOURCE,
        lookback="career",
        null_policy="과거 0경주면 null",
        leakage_note="low — cum_sum 후 shift(1)",
    ),
    FeatureSpec(
        name="days_since_last_race",
        group=GROUP,
        description="직전 경주 후 경과일",
        source=_SOURCE,
        lookback="직전 1경주",
        null_policy="과거 경주 없으면 null",
        leakage_note="low — race_date shift(1)",
    ),
    FeatureSpec(
        name="long_layoff",
        group=GROUP,
        description="장기 휴양 복귀 (직전 경주 후 90일 초과, 0/1)",
        source=_SOURCE,
        lookback="직전 1경주",
        null_policy="과거 경주 없으면 null",
        leakage_note="low",
    ),
    FeatureSpec(
        name="speed_avg_mps_3",
        group=GROUP,
        description="최근 3경주 평균 속도(m/s). 경마장별 대역 밖은 null",
        source=_SOURCE,
        lookback="최근 3경주",
        null_policy="유효 속도 없으면 null. 서울·부산 12~18, 제주 10~13.5 m/s 밖 제외",
        leakage_note="low — rolling 후 shift(1)",
    ),
    FeatureSpec(
        name="speed_avg_mps_5",
        group=GROUP,
        description="최근 5경주 평균 속도(m/s). 경마장별 대역 밖은 null",
        source=_SOURCE,
        lookback="최근 5경주",
        null_policy="유효 속도 없으면 null. 서울·부산 12~18, 제주 10~13.5 m/s 밖 제외",
        leakage_note="low — rolling 후 shift(1)",
    ),
    FeatureSpec(
        name="speed_best_mps_5",
        group=GROUP,
        description="최근 5경주 최고 속도(m/s). 경마장별 대역 밖은 null",
        source=_SOURCE,
        lookback="최근 5경주",
        null_policy="유효 속도 없으면 null. 서울·부산 12~18, 제주 10~13.5 m/s 밖 제외",
        leakage_note="low — rolling 후 shift(1)",
    ),
    FeatureSpec(
        name="speed_rel_avg5",
        group=GROUP,
        description="최근 5경주의 해당 경주 중앙속도 대비 상대속도 평균",
        source=_SOURCE,
        lookback="최근 5경주",
        null_policy="유효 기록 없으면 null",
        leakage_note="low — 완료된 과거 경주 내부 비교 후 shift(1)",
    ),
    FeatureSpec(
        name="speed_rel_median5",
        group=GROUP,
        description="최근 5경주 상대속도 중앙값 (비경쟁 종료의 느린 기록 영향 완화)",
        source=_SOURCE,
        lookback="최근 5경주",
        null_policy="유효 기록 없으면 null",
        leakage_note="low — rolling 후 shift(1)",
    ),
    FeatureSpec(
        name="speed_rel_best5",
        group=GROUP,
        description="최근 5경주 최고 경주 내 상대속도",
        source=_SOURCE,
        lookback="최근 5경주",
        null_policy="유효 기록 없으면 null",
        leakage_note="low — rolling 후 shift(1)",
    ),
    FeatureSpec(
        name="distance_change_m",
        group=GROUP,
        description="현재 거리 − 직전 출전 거리(m)",
        source=_SOURCE,
        lookback="직전 1경주",
        null_policy="과거 경주 없으면 null",
        leakage_note="low — 현재 출전표 거리와 직전 과거 거리만 사용",
    ),
    FeatureSpec(
        name="dist_band_starts",
        group=GROUP,
        description="현재 경주 거리 ±200m 이내 과거 출주 수",
        source=_SOURCE,
        lookback="career, 현재 거리 ±200m",
        null_policy="0",
        leakage_note="low — horse_id join 후 race_date < 현재만 집계",
    ),
    FeatureSpec(
        name="dist_band_top3_rate",
        group=GROUP,
        description="현재 경주 거리 ±200m 이내 과거 복승률",
        source=_SOURCE,
        lookback="career, 현재 거리 ±200m",
        null_policy="해당 거리대 0경주면 null",
        leakage_note="low — horse_id join 후 race_date < 현재만 집계",
    ),
    FeatureSpec(
        name="exact_distance_starts",
        group=GROUP,
        description="현재와 정확히 같은 거리의 과거 출주 수",
        source=_SOURCE,
        lookback="career, 동일 거리",
        null_policy="0",
        leakage_note="low — horse_id join 후 race_date < 현재만 집계",
    ),
    FeatureSpec(
        name="exact_distance_top3_rate",
        group=GROUP,
        description="현재와 정확히 같은 거리의 과거 3위 내 비율",
        source=_SOURCE,
        lookback="career, 동일 거리",
        null_policy="동일 거리 0경주면 null",
        leakage_note="low — horse_id join 후 race_date < 현재만 집계",
    ),
    FeatureSpec(
        name="meet_starts",
        group=GROUP,
        description="현재 경마장 과거 출주 수",
        source=_SOURCE,
        lookback="career, 동일 meet_code",
        null_policy="0",
        leakage_note="low — horse_id join 후 race_date < 현재만 집계",
    ),
    FeatureSpec(
        name="meet_win_rate",
        group=GROUP,
        description="현재 경마장 과거 승률",
        source=_SOURCE,
        lookback="career, 동일 meet_code",
        null_policy="해당 경마장 0경주면 null",
        leakage_note="low — horse_id join 후 race_date < 현재만 집계",
    ),
]


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    past = sources.past_results
    if past.height == 0:
        return _with_empty_form(frame)

    history = _sequential_history(past)
    frame = frame.join(
        history.select(["race_entry_id", *_SEQUENTIAL]),
        on="race_entry_id",
        how="left",
    )
    frame = frame.with_columns(pl.col("career_starts").fill_null(0))
    frame = frame.with_columns((pl.col("career_starts") == 0).cast(pl.Int8).alias("is_debut"))
    return _add_distance_and_meet(frame, past)


def _with_empty_form(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.lit(0).cast(pl.Int64).alias("career_starts"),
        pl.lit(1).cast(pl.Int8).alias("is_debut"),
        pl.lit(None).cast(pl.Int64).alias("finish_pos_last"),
        pl.lit(None).cast(pl.Float64).alias("form_recent3_pct"),
        pl.lit(None).cast(pl.Float64).alias("form_recent5_pct"),
        pl.lit(None).cast(pl.Float64).alias("form_recent5_median_pct"),
        pl.lit(None).cast(pl.Float64).alias("form_recent5_best_pct"),
        pl.lit(None).cast(pl.Float64).alias("top3_rate_recent5"),
        pl.lit(None).cast(pl.Float64).alias("win_rate_career"),
        pl.lit(None).cast(pl.Float64).alias("top3_rate_career"),
        pl.lit(None).cast(pl.Int64).alias("days_since_last_race"),
        pl.lit(None).cast(pl.Int8).alias("long_layoff"),
        pl.lit(None).cast(pl.Float64).alias("speed_avg_mps_3"),
        pl.lit(None).cast(pl.Float64).alias("speed_avg_mps_5"),
        pl.lit(None).cast(pl.Float64).alias("speed_best_mps_5"),
        pl.lit(None).cast(pl.Float64).alias("speed_rel_avg5"),
        pl.lit(None).cast(pl.Float64).alias("speed_rel_median5"),
        pl.lit(None).cast(pl.Float64).alias("speed_rel_best5"),
        pl.lit(None).cast(pl.Int64).alias("distance_change_m"),
        pl.lit(0).cast(pl.Int64).alias("dist_band_starts"),
        pl.lit(None).cast(pl.Float64).alias("dist_band_top3_rate"),
        pl.lit(0).cast(pl.Int64).alias("exact_distance_starts"),
        pl.lit(None).cast(pl.Float64).alias("exact_distance_top3_rate"),
        pl.lit(0).cast(pl.Int64).alias("meet_starts"),
        pl.lit(None).cast(pl.Float64).alias("meet_win_rate"),
    )


def _finish_percentile() -> pl.Expr:
    return (
        pl.when(pl.col("starters") <= 1)
        .then(0.0)
        .otherwise((pl.col("finish_position") - 1) / (pl.col("starters") - 1))
    )


def _speed_mps() -> pl.Expr:
    raw = pl.col("distance_m") / (pl.col("finish_time_ms") / 1000.0)
    usable = (
        pl.col("finish_time_ms").is_not_null()
        & (pl.col("finish_time_ms") > 0)
        & pl.col("distance_m").is_not_null()
        & (pl.col("distance_m") > 0)
    )
    seoul_busan_lo, seoul_busan_hi = _SEOUL_BUSAN_MPS
    jeju_lo, jeju_hi = _JEJU_MPS
    in_band = (
        pl.when(pl.col("meet_code").is_in(_SEOUL_BUSAN_MEETS))
        .then((raw >= seoul_busan_lo) & (raw <= seoul_busan_hi))
        .when(pl.col("meet_code") == _JEJU_MEET)
        .then((raw >= jeju_lo) & (raw <= jeju_hi))
        .otherwise(False)
    )
    return pl.when(usable & in_band.fill_null(False)).then(raw).otherwise(None)


def _raw_speed_mps() -> pl.Expr:
    """경주 내 상대속도용 원시값.

    과거 제주의 마종 구성 변화 때문에 현행 고정 속도 대역을 적용하지 않는다.
    명백한 파싱 오류만 넓은 물리 범위로 제외하고 같은 경주 중앙값으로 정규화한다.
    """
    raw = pl.col("distance_m") / (pl.col("finish_time_ms") / 1000.0)
    usable = (
        pl.col("finish_time_ms").is_not_null()
        & (pl.col("finish_time_ms") > 0)
        & pl.col("distance_m").is_not_null()
        & (pl.col("distance_m") > 0)
        & raw.is_between(5.0, 25.0)
    )
    return pl.when(usable).then(raw).otherwise(None)


def _sequential_history(past: pl.DataFrame) -> pl.DataFrame:
    """각 past_results 행에 '직전까지' form을 붙인다. 현재 행은 shift(1)로 빠진다."""
    ordered = past.sort("horse_id", "race_date", "race_id").with_columns(
        _finish_percentile().alias("_pct"),
        (pl.col("finish_position") == 1).cast(pl.Int8).alias("_win"),
        (pl.col("finish_position") <= 3).cast(pl.Int8).alias("_top3"),
        _speed_mps().alias("_mps"),
        _raw_speed_mps().alias("_raw_mps"),
        pl.int_range(pl.len()).over("horse_id").alias("career_starts"),
    )
    ordered = ordered.with_columns(
        (pl.col("_raw_mps") / pl.col("_raw_mps").median().over("race_id")).alias(
            "_speed_rel"
        )
    )
    included = ordered.with_columns(
        pl.col("_pct").rolling_mean(window_size=3, min_samples=1).over("horse_id").alias("_form3"),
        pl.col("_pct").rolling_mean(window_size=5, min_samples=1).over("horse_id").alias("_form5"),
        pl.col("_pct")
        .rolling_median(window_size=5, min_samples=1)
        .over("horse_id")
        .alias("_form5_median"),
        pl.col("_pct").rolling_min(window_size=5, min_samples=1).over("horse_id").alias(
            "_form5_best"
        ),
        pl.col("_top3")
        .rolling_mean(window_size=5, min_samples=1)
        .over("horse_id")
        .alias("_top3_recent5"),
        pl.col("_win").cast(pl.Int64).cum_sum().over("horse_id").alias("_wins"),
        pl.col("_top3").cast(pl.Int64).cum_sum().over("horse_id").alias("_top3s"),
        pl.col("_mps").rolling_mean(window_size=3, min_samples=1).over("horse_id").alias("_spd3"),
        pl.col("_mps").rolling_mean(window_size=5, min_samples=1).over("horse_id").alias("_spd5"),
        pl.col("_mps")
        .rolling_max(window_size=5, min_samples=1)
        .over("horse_id")
        .alias("_spd_best5"),
        pl.col("_speed_rel")
        .rolling_mean(window_size=5, min_samples=1)
        .over("horse_id")
        .alias("_speed_rel_avg5"),
        pl.col("_speed_rel")
        .rolling_median(window_size=5, min_samples=1)
        .over("horse_id")
        .alias("_speed_rel_median5"),
        pl.col("_speed_rel")
        .rolling_max(window_size=5, min_samples=1)
        .over("horse_id")
        .alias("_speed_rel_best5"),
    )
    shifted = included.with_columns(
        pl.col("finish_position").shift(1).over("horse_id").cast(pl.Int64).alias("finish_pos_last"),
        pl.col("_form3").shift(1).over("horse_id").alias("form_recent3_pct"),
        pl.col("_form5").shift(1).over("horse_id").alias("form_recent5_pct"),
        pl.col("_form5_median")
        .shift(1)
        .over("horse_id")
        .alias("form_recent5_median_pct"),
        pl.col("_form5_best").shift(1).over("horse_id").alias("form_recent5_best_pct"),
        pl.col("_top3_recent5").shift(1).over("horse_id").alias("top3_rate_recent5"),
        (pl.col("_wins").shift(1).over("horse_id") / pl.col("career_starts")).alias(
            "win_rate_career"
        ),
        (pl.col("_top3s").shift(1).over("horse_id") / pl.col("career_starts")).alias(
            "top3_rate_career"
        ),
        (pl.col("race_date") - pl.col("race_date").shift(1).over("horse_id"))
        .dt.total_days()
        .alias("days_since_last_race"),
        pl.col("_spd3").shift(1).over("horse_id").alias("speed_avg_mps_3"),
        pl.col("_spd5").shift(1).over("horse_id").alias("speed_avg_mps_5"),
        pl.col("_spd_best5").shift(1).over("horse_id").alias("speed_best_mps_5"),
        pl.col("_speed_rel_avg5").shift(1).over("horse_id").alias("speed_rel_avg5"),
        pl.col("_speed_rel_median5")
        .shift(1)
        .over("horse_id")
        .alias("speed_rel_median5"),
        pl.col("_speed_rel_best5").shift(1).over("horse_id").alias("speed_rel_best5"),
        (pl.col("distance_m") - pl.col("distance_m").shift(1).over("horse_id"))
        .cast(pl.Int64)
        .alias("distance_change_m"),
    )
    return shifted.with_columns(
        pl.when(pl.col("days_since_last_race").is_null())
        .then(None)
        .otherwise((pl.col("days_since_last_race") > _LONG_LAYOFF_DAYS).cast(pl.Int8))
        .alias("long_layoff")
    )


def _add_distance_and_meet(frame: pl.DataFrame, past: pl.DataFrame) -> pl.DataFrame:
    """말당 과거 경주만 join한 뒤 거리대·경마장 필터 집계 (전역 cartesian 금지)."""
    current = frame.select("race_entry_id", "horse_id", "race_date", "distance_m", "meet_code")
    history = past.select(
        "horse_id",
        pl.col("race_date").alias("hist_date"),
        pl.col("distance_m").alias("hist_distance_m"),
        pl.col("meet_code").alias("hist_meet_code"),
        "finish_position",
    )
    joined = current.join(history, on="horse_id", how="inner").filter(
        pl.col("hist_date") < pl.col("race_date")
    )

    dist = (
        joined.filter((pl.col("hist_distance_m") - pl.col("distance_m")).abs() <= _DIST_BAND_M)
        .group_by("race_entry_id")
        .agg(
            pl.len().cast(pl.Int64).alias("dist_band_starts"),
            (pl.col("finish_position") <= 3).mean().alias("dist_band_top3_rate"),
        )
    )
    exact = (
        joined.filter(pl.col("hist_distance_m") == pl.col("distance_m"))
        .group_by("race_entry_id")
        .agg(
            pl.len().cast(pl.Int64).alias("exact_distance_starts"),
            (pl.col("finish_position") <= 3).mean().alias("exact_distance_top3_rate"),
        )
    )
    meet = (
        joined.filter(pl.col("hist_meet_code") == pl.col("meet_code"))
        .group_by("race_entry_id")
        .agg(
            pl.len().cast(pl.Int64).alias("meet_starts"),
            (pl.col("finish_position") == 1).mean().alias("meet_win_rate"),
        )
    )
    result = (
        frame.join(dist, on="race_entry_id", how="left")
        .join(exact, on="race_entry_id", how="left")
        .join(meet, on="race_entry_id", how="left")
    )
    return result.with_columns(
        pl.col("dist_band_starts").fill_null(0),
        pl.col("exact_distance_starts").fill_null(0),
        pl.col("meet_starts").fill_null(0),
    )
