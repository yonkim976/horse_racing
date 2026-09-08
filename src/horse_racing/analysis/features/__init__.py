"""Feature v1 파이프라인.

그룹 모듈을 순서대로 적용한다. I그룹(경주 내 상대값)은 다른 그룹의 출력을
표준화하므로 반드시 마지막에 둔다. 새 그룹 모듈은 GROUP_MODULES에 등록한다.
"""

from __future__ import annotations

import polars as pl

from horse_racing.analysis.features import (
    ability,
    competition,
    condition,
    context,
    dynamic_state,
    early_gate_bias,
    energy,
    entry,
    form,
    gate_bias,
    lifecycle,
    people,
    relative,
    remediation,
    same_day_bias,
    sand_response,
    speed_figure,
    state,
    style,
    training_state,
    trials,
)
from horse_racing.analysis.features.base import (
    FeatureSpec,
    SourceFrames,
    as_date,
    load_source_frames,
)

GROUP_MODULES = [
    context,
    entry,
    form,
    lifecycle,
    speed_figure,
    ability,
    style,
    competition,
    gate_bias,
    early_gate_bias,
    sand_response,
    condition,
    training_state,
    trials,
    remediation,
    people,
    relative,  # 반드시 마지막
]

# 장기 백필에는 2025년부터만 존재하는 훈련·진료·장구·주행심사 원천을 넣지 않는다.
# 기수·조교사 rolling은 key별 정렬 이력과 이진 탐색으로 계산해 장기 구간에도 포함한다.
# 2015년 이력은 SourceFrames에 남아 2016년 타깃의 burn-in으로만 쓰인다.
HISTORY_CORE_MODULES = [
    context,
    entry,
    form,
    lifecycle,
    speed_figure,
    ability,
    style,
    competition,
    gate_bias,
    early_gate_bias,
    people,
    relative,
]

FEATURE_SETS = {
    "rich": GROUP_MODULES,
    "history_core": HISTORY_CORE_MODULES,
    "racefit_rich": [
        context,
        entry,
        form,
        lifecycle,
        speed_figure,
        energy,
        ability,
        style,
        competition,
        gate_bias,
        early_gate_bias,
        sand_response,
        condition,
        training_state,
        state,
        trials,
        remediation,
        people,
        relative,
    ],
    "racefit_history": [
        context,
        entry,
        form,
        lifecycle,
        speed_figure,
        energy,
        ability,
        style,
        competition,
        gate_bias,
        early_gate_bias,
        state,
        people,
        relative,
    ],
    "racefit_v2_rich": [
        context,
        entry,
        form,
        lifecycle,
        speed_figure,
        energy,
        dynamic_state,
        ability,
        style,
        competition,
        same_day_bias,
        gate_bias,
        early_gate_bias,
        sand_response,
        condition,
        training_state,
        state,
        trials,
        remediation,
        people,
        relative,
    ],
    "racefit_v2_history": [
        context,
        entry,
        form,
        lifecycle,
        speed_figure,
        energy,
        dynamic_state,
        ability,
        style,
        competition,
        gate_bias,
        early_gate_bias,
        state,
        people,
        relative,
    ],
}

__all__ = [
    "FeatureSpec",
    "SourceFrames",
    "apply_features",
    "all_feature_specs",
    "feature_names",
    "FEATURE_SETS",
    "load_source_frames",
]


def apply_features(
    frame: pl.DataFrame,
    sources: SourceFrames,
    *,
    feature_set: str = "rich",
) -> pl.DataFrame:
    """모든 그룹 feature를 데이터셋에 추가한다."""
    if "race_date" not in frame.columns:
        frame = frame.with_columns(pl.col("race_date_local").alias("race_date"))
        frame = as_date(frame, "race_date")
    try:
        modules = FEATURE_SETS[feature_set]
    except KeyError as exc:
        raise ValueError(f"알 수 없는 feature_set: {feature_set}") from exc
    for module in modules:
        frame = module.add_features(frame, sources)
    return frame


def all_feature_specs(*, feature_set: str = "rich") -> list[FeatureSpec]:
    try:
        modules = FEATURE_SETS[feature_set]
    except KeyError as exc:
        raise ValueError(f"알 수 없는 feature_set: {feature_set}") from exc
    return [spec for module in modules for spec in module.FEATURES]


def feature_names(
    frame: pl.DataFrame | None = None,
    *,
    feature_set: str = "rich",
) -> list[str]:
    """등록된 feature 이름. frame을 주면 실제 존재하는 컬럼만 반환한다."""
    names = [spec.name for spec in all_feature_specs(feature_set=feature_set)]
    if frame is None:
        return names
    return [name for name in names if name in frame.columns]
