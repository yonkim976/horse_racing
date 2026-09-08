"""D1+ group. Gate effects on S1F speed, estimated strictly pre-race.

The target is a within-race log S1F speed figure, so weather and the absolute
section-time scale mostly cancel.  Gate cells are hierarchically shrunk from
field context to exact distance and then to course, with a rolling three-year
window.  No result from the target date is visible to its features.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames, as_date

GROUP = "D1+. 게이트별 초반속도 보정"
_LOOKBACK_DAYS = 1_095
_COURSE_PRIOR_N = 80.0
_DISTANCE_PRIOR_N = 40.0
_CONTEXT_PRIOR_N = 20.0

FEATURES = [
    FeatureSpec(
        name="gate_early_speed_course",
        group=GROUP,
        description="경마장×게이트구역의 과거 S1F 상대속도 효과",
        source="과거 S1F 시간 + 상대 게이트",
        lookback="대상 경주일 이전 3년",
        null_policy="표본 없으면 중립 0",
        leakage_note="같은 날짜 결과를 대상 feature 출력 후 반영",
    ),
    FeatureSpec(
        name="gate_early_speed_distance",
        group=GROUP,
        description="경마장×정확거리×게이트구역의 계층 수축 S1F 효과",
        source="과거 경주내 S1F 상대속도",
        lookback="대상 경주일 이전 3년",
        null_policy="희소하면 경마장×게이트 효과로 수축",
        leakage_note="현재·같은 날 경주 결과 제외",
    ),
    FeatureSpec(
        name="gate_early_speed_context",
        group=GROUP,
        description="경마장×거리×출전두수군×게이트구역의 최종 S1F 효과",
        source="과거 경주내 S1F 상대속도",
        lookback="대상 경주일 이전 3년",
        null_policy="희소하면 정확거리 효과로 수축",
        leakage_note="현재·같은 날 경주 결과 제외",
    ),
    FeatureSpec(
        name="gate_early_speed_evidence",
        group=GROUP,
        description="최종 게이트 초반속도 셀의 과거 유효 S1F 표본 수",
        source="과거 S1F 유효 관측 수",
        lookback="대상 경주일 이전 3년",
        null_policy="표본 없으면 0",
        leakage_note="현재·같은 날 경주 결과 제외",
    ),
    FeatureSpec(
        name="gate_early_speed_reliability",
        group=GROUP,
        description="게이트 초반속도 세부효과 신뢰도 n/(n+20)",
        source="gate_early_speed_evidence",
        lookback="대상 경주일 이전 3년",
        null_policy="표본 없으면 0",
        leakage_note="현재·같은 날 경주 결과 제외",
    ),
    FeatureSpec(
        name="gate_early_speed_front_fit",
        group=GROUP,
        description="게이트 초반속도 효과×과거 선행성향×스타일 신뢰도",
        source="gate_early_speed_context + early_pos_pct_avg5",
        lookback="게이트 3년, 말 최근 5경주",
        null_policy="스타일 이력 없으면 0",
        leakage_note="모든 입력은 경주 전 정보",
    ),
]

FEATURE_NAMES = tuple(spec.name for spec in FEATURES)


@dataclass
class _MeanStat:
    total: float = 0.0
    count: float = 0.0


def _gate_band(gate_number: object, starters: object) -> str | None:
    if gate_number is None or starters is None:
        return None
    field = int(starters)
    gate = int(gate_number)
    if field <= 0 or gate <= 0:
        return None
    pct = gate / field
    if pct <= 1.0 / 3.0:
        return "inner"
    if pct <= 2.0 / 3.0:
        return "middle"
    return "outer"


def _field_band(starters: object) -> str | None:
    if starters is None:
        return None
    field = int(starters)
    if field <= 0:
        return None
    if field <= 8:
        return "small"
    if field <= 12:
        return "medium"
    return "large"


def _posterior(stat: _MeanStat | None, parent: float, prior_n: float) -> float:
    if stat is None or stat.count <= 0:
        return parent
    return (stat.total + prior_n * parent) / (stat.count + prior_n)


def _early_speed_observations(
    past: pl.DataFrame,
    sections: pl.DataFrame,
) -> pl.DataFrame:
    required_past = {
        "race_id",
        "horse_id",
        "race_date",
        "meet_code",
        "distance_m",
        "gate_number",
        "starters",
    }
    required_sections = {"race_id", "horse_id", "section_code", "elapsed_time_ms"}
    if (
        past.height == 0
        or sections.height == 0
        or not required_past <= set(past.columns)
        or not required_sections <= set(sections.columns)
    ):
        return pl.DataFrame()
    s1f = (
        sections.filter(
            (pl.col("section_code") == "S1F")
            & pl.col("elapsed_time_ms").is_not_null()
            & (pl.col("elapsed_time_ms") > 0)
        )
        .group_by("race_id", "horse_id")
        .agg(pl.col("elapsed_time_ms").first().cast(pl.Float64).alias("_s1f_ms"))
        .with_columns(
            pl.col("_s1f_ms").median().over("race_id").alias("_race_median"),
            pl.len().over("race_id").alias("_race_count"),
        )
        .with_columns(
            pl.when(pl.col("_race_count") >= 3)
            .then((pl.col("_race_median") / pl.col("_s1f_ms")).log() * 100.0)
            .otherwise(None)
            .clip(-20.0, 20.0)
            .alias("early_speed_figure")
        )
        .select("race_id", "horse_id", "early_speed_figure")
    )
    return (
        past.select(
            "race_id",
            "horse_id",
            "race_date",
            "meet_code",
            "distance_m",
            "gate_number",
            "starters",
        )
        .join(s1f, on=["race_id", "horse_id"], how="inner")
        .filter(pl.col("early_speed_figure").is_not_null())
    )


def _empty(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.lit(0.0).alias("gate_early_speed_course"),
        pl.lit(0.0).alias("gate_early_speed_distance"),
        pl.lit(0.0).alias("gate_early_speed_context"),
        pl.lit(0.0).alias("gate_early_speed_evidence"),
        pl.lit(0.0).alias("gate_early_speed_reliability"),
        pl.lit(0.0).alias("gate_early_speed_front_fit"),
    )


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    past = as_date(sources.past_results, "race_date")
    sections = as_date(sources.sections, "race_date")
    observations = _early_speed_observations(past, sections)
    required_target = {
        "race_entry_id",
        "race_date",
        "meet_code",
        "distance_m",
        "starters",
        "horse_number",
    }
    if observations.height == 0 or not required_target <= set(frame.columns):
        return _empty(frame)

    by_day: dict[date, list[dict[str, object]]] = defaultdict(list)
    for row in observations.iter_rows(named=True):
        if row["race_date"] is not None:
            by_day[row["race_date"]].append(row)

    course: dict[tuple[int, str], _MeanStat] = defaultdict(_MeanStat)
    distance: dict[tuple[int, int, str], _MeanStat] = defaultdict(_MeanStat)
    context: dict[tuple[int, int, str, str], _MeanStat] = defaultdict(_MeanStat)

    def update(row: dict[str, object], direction: float = 1.0) -> None:
        gate = _gate_band(row.get("gate_number"), row.get("starters"))
        field = _field_band(row.get("starters"))
        value = row.get("early_speed_figure")
        if gate is None or field is None or value is None:
            return
        meet = int(row["meet_code"])
        dist = int(row["distance_m"])
        for bucket, key in (
            (course, (meet, gate)),
            (distance, (meet, dist, gate)),
            (context, (meet, dist, field, gate)),
        ):
            stat = bucket[key]
            stat.total += direction * float(value)
            stat.count += direction

    history_days = sorted(by_day)
    add_index = 0
    remove_index = 0
    output: list[dict[str, object]] = []
    targets = frame.select(*sorted(required_target)).sort("race_date", "race_entry_id")
    for target_day in targets.partition_by("race_date", maintain_order=True):
        day = target_day["race_date"][0]
        while add_index < len(history_days) and history_days[add_index] < day:
            for row in by_day[history_days[add_index]]:
                update(row)
            add_index += 1
        cutoff = day - timedelta(days=_LOOKBACK_DAYS)
        while remove_index < add_index and history_days[remove_index] < cutoff:
            for row in by_day[history_days[remove_index]]:
                update(row, -1.0)
            remove_index += 1

        for row in target_day.iter_rows(named=True):
            gate = _gate_band(row.get("horse_number"), row.get("starters"))
            field = _field_band(row.get("starters"))
            if gate is None or field is None:
                output.append(
                    {
                        "race_entry_id": row["race_entry_id"],
                        **{name: 0.0 for name in FEATURE_NAMES},
                    }
                )
                continue
            meet = int(row["meet_code"])
            dist = int(row["distance_m"])
            course_effect = _posterior(course.get((meet, gate)), 0.0, _COURSE_PRIOR_N)
            distance_effect = _posterior(
                distance.get((meet, dist, gate)),
                course_effect,
                _DISTANCE_PRIOR_N,
            )
            context_stat = context.get((meet, dist, field, gate))
            context_effect = _posterior(
                context_stat,
                distance_effect,
                _CONTEXT_PRIOR_N,
            )
            evidence = context_stat.count if context_stat is not None else 0.0
            output.append(
                {
                    "race_entry_id": row["race_entry_id"],
                    "gate_early_speed_course": course_effect,
                    "gate_early_speed_distance": distance_effect,
                    "gate_early_speed_context": context_effect,
                    "gate_early_speed_evidence": evidence,
                    "gate_early_speed_reliability": evidence / (evidence + _CONTEXT_PRIOR_N),
                }
            )

    features = pl.DataFrame(output, infer_schema_length=None)
    result = frame.join(features, on="race_entry_id", how="left").with_columns(
        *[
            pl.col(name).fill_null(0.0)
            for name in FEATURE_NAMES
            if name != "gate_early_speed_front_fit"
        ]
    )
    historical_frontness = (
        (1.0 - pl.col("early_pos_pct_avg5").fill_null(0.5))
        if "early_pos_pct_avg5" in result.columns
        else pl.lit(0.5)
    )
    reliability = (
        (pl.col("section_coverage5").cast(pl.Float64) / 5.0).clip(0.0, 1.0)
        if "section_coverage5" in result.columns
        else pl.lit(0.0)
    )
    return result.with_columns(
        (pl.col("gate_early_speed_context") * historical_frontness * reliability).alias(
            "gate_early_speed_front_fit"
        )
    )
