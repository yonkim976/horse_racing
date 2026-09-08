"""E~G그룹. 체중·훈련·건강 feature.

체중은 과거 완료 경주(`past_results`)만 쓰고, 훈련·진료는 당일 이벤트를 제외한다.
장구·폐출혈은 경주 전 공개되는 현재 경주 `entry_equipment` 행을 사용한다.
"""

from __future__ import annotations

import polars as pl

from horse_racing.analysis.features.base import (
    FeatureSpec,
    SourceFrames,
    days_since_last_event,
    rolling_event_counts,
)

GROUP = "E~G. 체중·훈련·건강"

_TRAIN_WINDOWS = (3, 7, 14, 28)
_MEDICAL_WINDOWS = (14, 30, 60)

_TRAIN_EXTRA_COLUMNS = (
    "train_dur_3d",
    "train_dur_7d",
    "train_dur_14d",
    "train_gallop_n_3d",
    "train_gallop_n_7d",
    "train_gallop_n_14d",
    "train_canter_n_3d",
    "train_canter_n_7d",
    "train_canter_n_14d",
)

FEATURES = [
    FeatureSpec(
        name="body_weight_prev_avg5",
        group=GROUP,
        description="과거 5경주 체중 평균 (현재 경주 제외)",
        source="past_results.body_weight_kg",
        lookback="직전 최대 5경주",
        null_policy="과거 경주 없으면 null",
        leakage_note="horse_id·race_date 정렬 후 shift(1) rolling — 현재 경주 체중 제외",
    ),
    FeatureSpec(
        name="body_weight_std5",
        group=GROUP,
        description="과거 5경주 체중 표준편차 (현재 경주 제외)",
        source="past_results.body_weight_kg",
        lookback="직전 최대 5경주",
        null_policy="과거 2경주 미만이면 null",
        leakage_note="shift(1) rolling — 현재 경주 체중 제외",
    ),
    FeatureSpec(
        name="body_weight_dev",
        group=GROUP,
        description="현재 체중 − 과거 5경주 체중 평균",
        source="frame.body_weight_kg − body_weight_prev_avg5",
        lookback="직전 최대 5경주",
        null_policy="현재 체중 또는 과거 평균이 없으면 null. day_before_18이면 컬럼 스킵",
        leakage_note="당일 체중은 계량 후 공개. frame에 body_weight_kg 없으면 이 feature만 스킵",
    ),
    *[
        FeatureSpec(
            name=f"train_n_{window}d",
            group=GROUP,
            description=f"경주 직전 {window}일 훈련 횟수 (당일 제외)",
            source="horse_training",
            lookback=f"{window}일",
            null_policy="이력 없으면 0",
            leakage_note="event_date < race_date (당일 제외)",
        )
        for window in _TRAIN_WINDOWS
    ],
    FeatureSpec(
        name="train_dur_28d",
        group=GROUP,
        description="경주 직전 28일 훈련 시간 합(초)",
        source="horse_training.duration_seconds",
        lookback="28일",
        null_policy="해당 말 훈련 이력이 없으면 null",
        leakage_note="event_date < race_date (당일 제외)",
    ),
    FeatureSpec(
        name="gallop_n_28d",
        group=GROUP,
        description="경주 직전 28일 습보(gallop) 횟수 합",
        source="horse_training.gallop_count",
        lookback="28일",
        null_policy="해당 말 훈련 이력이 없으면 null",
        leakage_note="event_date < race_date (당일 제외)",
    ),
    FeatureSpec(
        name="canter_n_28d",
        group=GROUP,
        description="경주 직전 28일 구보(canter) 횟수 합",
        source="horse_training.canter_count",
        lookback="28일",
        null_policy="해당 말 훈련 이력이 없으면 null",
        leakage_note="event_date < race_date (당일 제외)",
    ),
    FeatureSpec(
        name="days_since_training",
        group=GROUP,
        description="마지막 훈련 후 경과일",
        source="horse_training",
        lookback="직전 1회",
        null_policy="이전 훈련 없으면 null",
        leakage_note="event_date < race_date (당일 제외)",
    ),
    FeatureSpec(
        name="start_train_n_28d",
        group=GROUP,
        description="경주 직전 28일 출발대 훈련 횟수",
        source="horse_start_training",
        lookback="28일",
        null_policy="이력 없으면 0",
        leakage_note="event_date < race_date (당일 제외)",
    ),
    *[
        FeatureSpec(
            name=f"medical_n_{window}d",
            group=GROUP,
            description=f"경주 직전 {window}일 진료 횟수 (당일 제외)",
            source="horse_medical",
            lookback=f"{window}일",
            null_policy="이력 없으면 0",
            leakage_note="event_date < race_date (당일 제외)",
        )
        for window in _MEDICAL_WINDOWS
    ],
    FeatureSpec(
        name="days_since_medical",
        group=GROUP,
        description="마지막 진료 후 경과일",
        source="horse_medical",
        lookback="직전 1회",
        null_policy="이전 진료 없으면 null",
        leakage_note="event_date < race_date (당일 제외)",
    ),
    FeatureSpec(
        name="bleeding_count_prior",
        group=GROUP,
        description="현재 경주 출전마 누적 폐출혈 횟수",
        source="entry_equipment.bleeding_count",
        lookback="현재 경주 행",
        null_policy="해당 경주 equipment 행 없으면 null",
        leakage_note="현재 경주 equipment 행은 경주 전 공개 (horse_id+race_date+race_number 매칭)",
    ),
    FeatureSpec(
        name="equipment_present",
        group=GROUP,
        description="현재 경주 장구 착용 여부 (equipment_raw 비어있지 않으면 1)",
        source="entry_equipment.equipment_raw",
        lookback="현재 경주 행",
        null_policy="행 없거나 공백이면 0",
        leakage_note="현재 경주 equipment 행은 경주 전 공개 정보로 사용",
    ),
    FeatureSpec(
        name="equipment_changed",
        group=GROUP,
        description="직전 경주 대비 장구 변경 여부",
        source="entry_equipment.equipment_raw",
        lookback="직전 경주 (race_date 엄격 이전 마지막 행)",
        null_policy="현재 또는 직전 equipment_raw가 없으면 null",
        leakage_note=(
            "현재 행은 경주 전 공개. 직전 행은 race_date < 현재 경주일인 마지막 equipment 이력"
        ),
    ),
]


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    frame = _add_weight_features(frame, sources.past_results)
    frame = _add_training_features(frame, sources)
    frame = _add_medical_features(frame, sources.medical)
    return _add_equipment_features(frame, sources.equipment)


def _add_weight_features(frame: pl.DataFrame, past: pl.DataFrame) -> pl.DataFrame:
    if past.height == 0 or "body_weight_kg" not in past.columns:
        frame = frame.with_columns(
            pl.lit(None).cast(pl.Float64).alias("body_weight_prev_avg5"),
            pl.lit(None).cast(pl.Float64).alias("body_weight_std5"),
        )
    else:
        ranked = past.sort("horse_id", "race_date", "race_entry_id").with_columns(
            pl.col("body_weight_kg").shift(1).over("horse_id").alias("_bw_lag")
        )
        ranked = ranked.with_columns(
            pl.col("_bw_lag")
            .rolling_mean(window_size=5, min_samples=1)
            .over("horse_id")
            .alias("body_weight_prev_avg5"),
            pl.col("_bw_lag")
            .rolling_std(window_size=5, min_samples=2)
            .over("horse_id")
            .alias("body_weight_std5"),
        )
        stats = ranked.select("race_entry_id", "body_weight_prev_avg5", "body_weight_std5")
        frame = frame.join(stats, on="race_entry_id", how="left")

    if "body_weight_kg" in frame.columns:
        frame = frame.with_columns(
            (pl.col("body_weight_kg") - pl.col("body_weight_prev_avg5")).alias("body_weight_dev")
        )
    return frame


def _add_training_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    frame = rolling_event_counts(
        frame,
        sources.training,
        key="horse_id",
        base_date_col="race_date",
        windows_days=_TRAIN_WINDOWS,
        prefix="train",
        value_columns={
            "duration_seconds": "dur",
            "gallop_count": "gallop_n",
            "canter_count": "canter_n",
        },
    )
    rename = {}
    if "train_gallop_n_28d" in frame.columns:
        rename["train_gallop_n_28d"] = "gallop_n_28d"
    if "train_canter_n_28d" in frame.columns:
        rename["train_canter_n_28d"] = "canter_n_28d"
    if rename:
        frame = frame.rename(rename)
    extras = [column for column in _TRAIN_EXTRA_COLUMNS if column in frame.columns]
    if extras:
        frame = frame.drop(extras)

    frame = days_since_last_event(
        frame,
        sources.training,
        key="horse_id",
        base_date_col="race_date",
        alias="days_since_training",
    )
    return rolling_event_counts(
        frame,
        sources.start_training,
        key="horse_id",
        base_date_col="race_date",
        windows_days=(28,),
        prefix="start_train",
    )


def _add_medical_features(frame: pl.DataFrame, medical: pl.DataFrame) -> pl.DataFrame:
    frame = rolling_event_counts(
        frame,
        medical,
        key="horse_id",
        base_date_col="race_date",
        windows_days=_MEDICAL_WINDOWS,
        prefix="medical",
    )
    return days_since_last_event(
        frame,
        medical,
        key="horse_id",
        base_date_col="race_date",
        alias="days_since_medical",
    )


def _add_equipment_features(frame: pl.DataFrame, equipment: pl.DataFrame) -> pl.DataFrame:
    if equipment.height == 0:
        return frame.with_columns(
            pl.lit(None).cast(pl.Int64).alias("bleeding_count_prior"),
            pl.lit(0).cast(pl.Int64).alias("equipment_present"),
            pl.lit(None).cast(pl.Int64).alias("equipment_changed"),
        )

    current = equipment.select(
        "horse_id",
        "race_date",
        "race_number",
        pl.col("equipment_raw").alias("_eq_raw"),
        pl.col("bleeding_count").alias("bleeding_count_prior"),
    )
    frame = frame.join(current, on=["horse_id", "race_date", "race_number"], how="left")

    keys = frame.select("horse_id", "race_date", "race_number").unique()
    history = equipment.select(
        "horse_id",
        pl.col("race_date").alias("_hist_date"),
        pl.col("race_number").alias("_hist_number"),
        pl.col("equipment_raw").alias("_prev_eq_raw"),
    )
    previous = keys.join(history, on="horse_id", how="inner").filter(
        pl.col("_hist_date") < pl.col("race_date")
    )
    if previous.height == 0:
        frame = frame.with_columns(pl.lit(None).cast(pl.Utf8).alias("_prev_eq_raw"))
    else:
        last = previous.group_by("horse_id", "race_date", "race_number").agg(
            pl.col("_prev_eq_raw").sort_by(["_hist_date", "_hist_number"]).last()
        )
        frame = frame.join(last, on=["horse_id", "race_date", "race_number"], how="left")

    frame = frame.with_columns(
        pl.when(pl.col("_eq_raw").is_not_null() & (pl.col("_eq_raw").str.strip_chars() != ""))
        .then(pl.lit(1).cast(pl.Int64))
        .otherwise(pl.lit(0).cast(pl.Int64))
        .alias("equipment_present"),
        pl.when(pl.col("_eq_raw").is_null() | pl.col("_prev_eq_raw").is_null())
        .then(pl.lit(None).cast(pl.Int64))
        .otherwise((pl.col("_eq_raw") != pl.col("_prev_eq_raw")).cast(pl.Int64))
        .alias("equipment_changed"),
    )
    return frame.drop(["_eq_raw", "_prev_eq_raw"])
