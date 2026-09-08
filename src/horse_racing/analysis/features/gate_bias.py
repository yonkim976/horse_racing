"""D1 group. Leakage-safe hierarchical course/distance gate-bias priors.

The observed number of top-three finishes is compared with the field-size
adjusted expectation for each gate band.  Every target row only sees races on
strictly earlier dates.  Sparse season/going cells are shrunk toward their
course-distance parent instead of being exposed as high-cardinality strings.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames

GROUP = "D1. 거리·계절·주로 게이트 보정"
_DISTANCE_PRIOR_SLOTS = 30.0
_CONTEXT_PRIOR_SLOTS = 15.0
_COMBINED_PRIOR_SLOTS = 10.0
_LOOKBACK_DAYS = 1_095

_FEATURE_NAMES = (
    "gate_top3_index_course_distance",
    "gate_top3_index_season",
    "gate_top3_index_going",
    "gate_top3_index_context",
    "gate_context_expected_slots",
    "gate_context_reliability",
)

FEATURES = [
    FeatureSpec(
        name="gate_top3_index_course_distance",
        group=GROUP,
        description="경마장×정확거리×게이트구역의 과거 3위내 기대대비 지수(100=기대)",
        source="과거 착순 + 출전두수 + 게이트; 경마장 게이트 효과로 수축",
        lookback="대상 경주일 이전 3년",
        null_policy="표본이 없으면 경마장·게이트 또는 중립 100",
        leakage_note="같은 날을 포함하지 않는 날짜 단위 누적",
    ),
    FeatureSpec(
        name="gate_top3_index_season",
        group=GROUP,
        description="경마장×정확거리×계절×게이트구역 보정 지수",
        source="과거 착순 + 계절; 정확거리 지수로 계층 수축",
        lookback="대상 경주일 이전 3년",
        null_policy="희소하면 정확거리 지수로 수축",
        leakage_note="같은 날을 포함하지 않는 날짜 단위 누적",
    ),
    FeatureSpec(
        name="gate_top3_index_going",
        group=GROUP,
        description="경마장×정확거리×주로군×게이트구역 보정 지수",
        source="과거 실제 주로상태; 정확거리 지수로 계층 수축",
        lookback="대상 경주일 이전 3년",
        null_policy="희소·미상 주로는 정확거리 지수로 수축",
        leakage_note="현재는 경주 전 계획 주로상태만 사용",
    ),
    FeatureSpec(
        name="gate_top3_index_context",
        group=GROUP,
        description="거리·계절·주로를 결합한 최종 게이트 보정 지수",
        source="계절/주로 부모 + 과거 동일 세부조건",
        lookback="대상 경주일 이전 3년",
        null_policy="희소하면 계절·주로 부모 평균으로 수축",
        leakage_note="현재 경주의 결과·실제 사후 주로를 사용하지 않음",
    ),
    FeatureSpec(
        name="gate_context_expected_slots",
        group=GROUP,
        description="동일 거리·계절·주로·게이트 과거 기대 입상 슬롯 합",
        source="각 과거 경주의 min(3, 출전두수)/출전두수 합",
        lookback="대상 경주일 이전 3년",
        null_policy="표본이 없으면 0",
        leakage_note="모델이 보정지수의 표본량을 함께 판단하도록 제공",
    ),
    FeatureSpec(
        name="gate_context_reliability",
        group=GROUP,
        description="세부조건 게이트 보정의 표본 신뢰도(0~1)",
        source="expected_slots / (expected_slots + prior_slots)",
        lookback="대상 경주일 이전 3년",
        null_policy="표본이 없으면 0",
        leakage_note="과거 표본량만 사용",
    ),
]


@dataclass
class _Stat:
    observed: float = 0.0
    expected: float = 0.0


def _season(value: date) -> str:
    month = value.month
    if month in (12, 1, 2):
        return "winter"
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    return "autumn"


def _going_group(value: object) -> str:
    if value is None:
        return "unknown"
    cleaned = str(value).strip()
    if cleaned in {"건조", "양호"}:
        return "dry_good"
    if cleaned == "다습":
        return "damp"
    if cleaned in {"포화", "불량"}:
        return "wet"
    return "unknown"


def _gate_band(gate_number: object, starters: object) -> str | None:
    if gate_number is None or starters is None:
        return None
    field = int(starters)
    gate = int(gate_number)
    if field <= 0 or gate <= 0:
        return None
    percentile = gate / field
    if percentile <= 1 / 3:
        return "inner"
    if percentile <= 2 / 3:
        return "middle"
    return "outer"


def _posterior(stat: _Stat | None, parent: float, prior_slots: float) -> float:
    if stat is None or stat.expected <= 0:
        return parent
    return (stat.observed + prior_slots * parent) / (stat.expected + prior_slots)


def _empty(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.lit(100.0).alias("gate_top3_index_course_distance"),
        pl.lit(100.0).alias("gate_top3_index_season"),
        pl.lit(100.0).alias("gate_top3_index_going"),
        pl.lit(100.0).alias("gate_top3_index_context"),
        pl.lit(0.0).alias("gate_context_expected_slots"),
        pl.lit(0.0).alias("gate_context_reliability"),
    )


def _pre_race_features(frame: pl.DataFrame, past: pl.DataFrame) -> pl.DataFrame:
    required_past = {
        "race_date",
        "meet_code",
        "distance_m",
        "gate_number",
        "starters",
        "finish_position",
    }
    if past.height == 0 or not required_past <= set(past.columns):
        return pl.DataFrame()

    historical_by_day: dict[date, list[dict[str, object]]] = defaultdict(list)
    for row in past.select(
        "race_date",
        "meet_code",
        "distance_m",
        "track_condition",
        "gate_number",
        "starters",
        "finish_position",
    ).iter_rows(named=True):
        if row["race_date"] is not None:
            historical_by_day[row["race_date"]].append(row)

    course: dict[tuple[int, str], _Stat] = defaultdict(_Stat)
    distance: dict[tuple[int, int, str], _Stat] = defaultdict(_Stat)
    seasonal: dict[tuple[int, int, str, str], _Stat] = defaultdict(_Stat)
    going: dict[tuple[int, int, str, str], _Stat] = defaultdict(_Stat)
    combined: dict[tuple[int, int, str, str, str], _Stat] = defaultdict(_Stat)

    def update(row: dict[str, object], direction: float = 1.0) -> None:
        band = _gate_band(row.get("gate_number"), row.get("starters"))
        if band is None or row.get("distance_m") is None or row.get("meet_code") is None:
            return
        field = int(row["starters"])
        if field <= 0 or row.get("finish_position") is None:
            return
        expected = min(3, field) / field
        observed = float(int(row["finish_position"]) <= 3)
        meet = int(row["meet_code"])
        dist = int(row["distance_m"])
        day = row["race_date"]
        season = _season(day)  # type: ignore[arg-type]
        going_key = _going_group(row.get("track_condition"))
        keys = (
            (course, (meet, band)),
            (distance, (meet, dist, band)),
            (seasonal, (meet, dist, season, band)),
            (going, (meet, dist, going_key, band)),
            (combined, (meet, dist, season, going_key, band)),
        )
        for bucket, key in keys:
            bucket[key].observed += direction * observed
            bucket[key].expected += direction * expected

    history_days = sorted(historical_by_day)
    history_index = 0
    prune_index = 0
    output: list[dict[str, object]] = []
    target = frame.select(
        "race_entry_id",
        "race_date",
        "meet_code",
        "distance_m",
        "starters",
        "horse_number",
        "track_condition_planned",
    ).sort("race_date", "race_entry_id")
    for target_day in target.partition_by("race_date", maintain_order=True):
        day = target_day["race_date"][0]
        while history_index < len(history_days) and history_days[history_index] < day:
            for historical_row in historical_by_day[history_days[history_index]]:
                update(historical_row)
            history_index += 1
        cutoff = day - timedelta(days=_LOOKBACK_DAYS)
        while prune_index < history_index and history_days[prune_index] < cutoff:
            for historical_row in historical_by_day[history_days[prune_index]]:
                update(historical_row, -1.0)
            prune_index += 1

        for row in target_day.iter_rows(named=True):
            band = _gate_band(row.get("horse_number"), row.get("starters"))
            if band is None or row.get("meet_code") is None or row.get("distance_m") is None:
                output.append(
                    {"race_entry_id": row["race_entry_id"], **{n: None for n in _FEATURE_NAMES}}
                )
                continue
            meet = int(row["meet_code"])
            dist = int(row["distance_m"])
            season = _season(day)
            going_key = _going_group(row.get("track_condition_planned"))

            course_stat = course.get((meet, band))
            course_index = _posterior(course_stat, 1.0, _DISTANCE_PRIOR_SLOTS)
            distance_index = _posterior(
                distance.get((meet, dist, band)), course_index, _DISTANCE_PRIOR_SLOTS
            )
            season_index = _posterior(
                seasonal.get((meet, dist, season, band)),
                distance_index,
                _CONTEXT_PRIOR_SLOTS,
            )
            going_index = _posterior(
                going.get((meet, dist, going_key, band)),
                distance_index,
                _CONTEXT_PRIOR_SLOTS,
            )
            parent_index = (season_index + going_index) / 2.0
            context_stat = combined.get((meet, dist, season, going_key, band))
            context_index = _posterior(context_stat, parent_index, _COMBINED_PRIOR_SLOTS)
            evidence = context_stat.expected if context_stat is not None else 0.0
            output.append(
                {
                    "race_entry_id": row["race_entry_id"],
                    "gate_top3_index_course_distance": 100.0 * distance_index,
                    "gate_top3_index_season": 100.0 * season_index,
                    "gate_top3_index_going": 100.0 * going_index,
                    "gate_top3_index_context": 100.0 * context_index,
                    "gate_context_expected_slots": evidence,
                    "gate_context_reliability": evidence / (evidence + _COMBINED_PRIOR_SLOTS),
                }
            )
    return pl.DataFrame(output, infer_schema_length=None)


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    features = _pre_race_features(frame, sources.past_results)
    if features.height == 0:
        return _empty(frame)
    return frame.join(features, on="race_entry_id", how="left").with_columns(
        pl.col("gate_top3_index_course_distance").fill_null(100.0),
        pl.col("gate_top3_index_season").fill_null(100.0),
        pl.col("gate_top3_index_going").fill_null(100.0),
        pl.col("gate_top3_index_context").fill_null(100.0),
        pl.col("gate_context_expected_slots").fill_null(0.0),
        pl.col("gate_context_reliability").fill_null(0.0),
    )
