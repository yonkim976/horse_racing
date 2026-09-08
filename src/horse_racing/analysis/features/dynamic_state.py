"""Leakage-safe two-state Kalman filter for ability and temporary condition.

The adjusted speed figure is treated as the sum of a slowly moving ability
state and a mean-reverting condition state.  Target rows are emitted before
observations from the same date are applied, so no current-race result enters
its own feature vector.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

import numpy as np
import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames, as_date
from horse_racing.analysis.features.speed_figure import performance_observations

GROUP = "G2. 동적 능력·컨디션 상태"
_CONDITION_HALF_LIFE_DAYS = 60.0
_MEASUREMENT_VARIANCE = 2.25
_ABILITY_PROCESS_VARIANCE_30D = 0.04
_CONDITION_STATIONARY_VARIANCE = 2.0

FEATURES = [
    FeatureSpec(
        name="dynamic_ability_state",
        group=GROUP,
        description="보정 속도관측을 완만히 갱신한 말별 장기 능력 Kalman 상태",
        source="과거 speed figure의 2상태 Kalman filter",
        lookback="전 기간",
        leakage_note="같은 날짜 관측은 대상 feature 출력 후 갱신",
    ),
    FeatureSpec(
        name="dynamic_condition_state",
        group=GROUP,
        description="60일 반감기로 평균회귀하는 말별 단기 컨디션 Kalman 상태",
        source="과거 speed figure의 ability 잔차",
        lookback="전 기간, 60일 반감기",
        leakage_note="현재 경주와 같은 날짜 결과 제외",
    ),
    FeatureSpec(
        name="dynamic_condition_sd",
        group=GROUP,
        description="단기 컨디션 상태의 사전 표준편차",
        source="Kalman covariance",
        lookback="전 기간",
        null_policy="신마도 초기 불확실성 제공",
        leakage_note="경주 전 covariance만 사용",
    ),
    FeatureSpec(
        name="dynamic_condition_z",
        group=GROUP,
        description="동적 컨디션 평균을 사전 표준편차로 나눈 값",
        source="dynamic_condition_state / dynamic_condition_sd",
        lookback="전 기간",
        leakage_note="경주 전 상태만 사용",
    ),
    FeatureSpec(
        name="dynamic_total_state",
        group=GROUP,
        description="동적 장기능력과 단기 컨디션의 합",
        source="Kalman latent ability + condition",
        lookback="전 기간",
        leakage_note="경주 전 상태만 사용",
    ),
    FeatureSpec(
        name="dynamic_state_observations",
        group=GROUP,
        description="동적 상태 갱신에 사용된 유효 과거 보정속도 관측 수",
        source="유효 과거 speed figure count",
        lookback="전 기간",
        null_policy="신마는 0",
        leakage_note="현재 경주 미포함",
    ),
    FeatureSpec(
        name="dynamic_days_since_observation",
        group=GROUP,
        description="마지막 유효 보정속도 관측 후 경과일",
        source="과거 speed figure 날짜",
        lookback="직전 유효 1경주",
        null_policy="신마는 null",
        leakage_note="현재 경주 미포함",
    ),
]


@dataclass
class _State:
    mean: np.ndarray
    covariance: np.ndarray
    state_date: date
    last_observation_date: date | None = None
    observations: int = 0


def _initial(current_date: date) -> _State:
    return _State(
        mean=np.zeros(2, dtype=float),
        covariance=np.diag([4.0, _CONDITION_STATIONARY_VARIANCE]),
        state_date=current_date,
    )


def _predict(state: _State, current_date: date) -> None:
    days = max(0, (current_date - state.state_date).days)
    if days == 0:
        return
    retention = 0.5 ** (days / _CONDITION_HALF_LIFE_DAYS)
    transition = np.diag([1.0, retention])
    process = np.diag(
        [
            _ABILITY_PROCESS_VARIANCE_30D * days / 30.0,
            _CONDITION_STATIONARY_VARIANCE * (1.0 - retention**2),
        ]
    )
    state.mean = transition @ state.mean
    state.covariance = transition @ state.covariance @ transition.T + process
    state.state_date = current_date


def _update(state: _State, observation: float, *, censored: int) -> None:
    design = np.asarray([1.0, 1.0])
    measurement_variance = _MEASUREMENT_VARIANCE * (1.8 if censored else 1.0)
    residual = float(observation - design @ state.mean)
    residual_variance = float(design @ state.covariance @ design + measurement_variance)
    gain = state.covariance @ design / residual_variance
    state.mean = state.mean + gain * residual
    identity = np.eye(2)
    # Joseph form keeps the covariance positive semidefinite over long histories.
    correction = identity - np.outer(gain, design)
    state.covariance = (
        correction @ state.covariance @ correction.T
        + np.outer(gain, gain) * measurement_variance
    )
    state.observations += 1
    state.last_observation_date = state.state_date


def _empty(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.lit(0.0).alias("dynamic_ability_state"),
        pl.lit(0.0).alias("dynamic_condition_state"),
        pl.lit(_CONDITION_STATIONARY_VARIANCE**0.5).alias("dynamic_condition_sd"),
        pl.lit(0.0).alias("dynamic_condition_z"),
        pl.lit(0.0).alias("dynamic_total_state"),
        pl.lit(0, dtype=pl.Int64).alias("dynamic_state_observations"),
        pl.lit(None, dtype=pl.Int64).alias("dynamic_days_since_observation"),
    )


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    past = as_date(sources.past_results, "race_date")
    if past.height == 0 or not {"horse_id", "race_entry_id", "race_date"} <= set(past.columns):
        return _empty(frame)

    observations = performance_observations(past)
    observations_by_day: dict[date, list[tuple[int, float, int]]] = defaultdict(list)
    for row in past.select("horse_id", "race_entry_id", "race_date").iter_rows(named=True):
        observation = observations.get(int(row["race_entry_id"]))
        if observation is not None:
            observations_by_day[row["race_date"]].append(
                (int(row["horse_id"]), observation.figure, observation.censored)
            )

    targets_by_day: dict[date, list[tuple[int, int]]] = defaultdict(list)
    for row in frame.select("horse_id", "race_entry_id", "race_date").iter_rows(named=True):
        targets_by_day[row["race_date"]].append(
            (int(row["horse_id"]), int(row["race_entry_id"]))
        )

    states: dict[int, _State] = {}
    output: list[dict[str, float | int | None]] = []
    for current_date in sorted(set(observations_by_day) | set(targets_by_day)):
        for horse_id, race_entry_id in targets_by_day.get(current_date, []):
            state = states.setdefault(horse_id, _initial(current_date))
            _predict(state, current_date)
            condition_sd = float(max(state.covariance[1, 1], 1e-12) ** 0.5)
            output.append(
                {
                    "race_entry_id": race_entry_id,
                    "dynamic_ability_state": float(state.mean[0]),
                    "dynamic_condition_state": float(state.mean[1]),
                    "dynamic_condition_sd": condition_sd,
                    "dynamic_condition_z": float(state.mean[1] / condition_sd),
                    "dynamic_total_state": float(state.mean.sum()),
                    "dynamic_state_observations": state.observations,
                    "dynamic_days_since_observation": (
                        (current_date - state.last_observation_date).days
                        if state.last_observation_date is not None
                        else None
                    ),
                }
            )
        # Every target on the date is emitted before any same-date result update.
        for horse_id, figure, censored in observations_by_day.get(current_date, []):
            state = states.setdefault(horse_id, _initial(current_date))
            _predict(state, current_date)
            _update(state, figure, censored=censored)

    if not output:
        return _empty(frame)
    features = pl.DataFrame(output, infer_schema_length=None)
    return frame.join(features, on="race_entry_id", how="left").with_columns(
        pl.col("dynamic_ability_state").fill_null(0.0),
        pl.col("dynamic_condition_state").fill_null(0.0),
        pl.col("dynamic_condition_sd").fill_null(_CONDITION_STATIONARY_VARIANCE**0.5),
        pl.col("dynamic_condition_z").fill_null(0.0),
        pl.col("dynamic_total_state").fill_null(0.0),
        pl.col("dynamic_state_observations").fill_null(0).cast(pl.Int64),
    )
