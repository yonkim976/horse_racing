"""C1 group. Course, distance, and going-adjusted historical speed figures.

Each completed race is first compared with a robust top-three par for the same
course and exact distance.  When enough observations exist, the par is also
conditioned on the official going.  A meeting-day variant then removes the
common fast/slow track effect visible across that day's distances.

Only the resulting figures from dates strictly before the target race are
aggregated.  Very slow tail finishes are lower-censored so that a horse which
was eased after losing contention cannot destroy its recent ability estimate.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames

GROUP = "C1. 보정 속도지수"
_SOURCE = "과거 finish_time + 경기장·정확거리·실제 주로상태"
_PAR_LOOKBACK_DAYS = 730
_MIN_GOING_PAR_RACES = 12
_MIN_DISTANCE_PAR_RACES = 20
_MIN_DAY_VARIANT_RACES = 3
_TAIL_FINISH_PERCENTILE = 0.60
_TAIL_FLOOR = -4.0
_MAX_DAY_VARIANT_LOG = 0.06
_FIGURE_MIN = -10.0
_FIGURE_MAX = 10.0

_FEATURE_NAMES = [
    "speed_figure_last",
    "speed_figure_avg3",
    "speed_figure_median5",
    "speed_figure_best5",
    "speed_figure_trend",
    "speed_figure_count5",
    "speed_figure_censored_rate5",
    "speed_figure_exact_distance_avg5",
    "speed_figure_exact_distance_count5",
]

FEATURES = [
    FeatureSpec(
        name="speed_figure_last",
        group=GROUP,
        description="직전 유효 경주의 경기장·거리·주로·당일 variant 보정 속도지수",
        source=_SOURCE,
        lookback="직전 유효 1경주",
        null_policy="기준속도 표본이 없으면 null",
        leakage_note="대상 경주일 이전 결과만 사용",
    ),
    FeatureSpec(
        name="speed_figure_avg3",
        group=GROUP,
        description="최근 유효 3경주 보정 속도지수 평균",
        source=_SOURCE,
        lookback="최근 유효 3경주",
        null_policy="유효 기록이 없으면 null",
        leakage_note="날짜 단위 갱신으로 같은 날 결과도 제외",
    ),
    FeatureSpec(
        name="speed_figure_median5",
        group=GROUP,
        description="최근 유효 5경주 보정 속도지수 중앙값",
        source=_SOURCE,
        lookback="최근 유효 5경주",
        null_policy="유효 기록이 없으면 null",
        leakage_note="과거 경주만 사용",
    ),
    FeatureSpec(
        name="speed_figure_best5",
        group=GROUP,
        description="최근 유효 5경주 최고 보정 속도지수",
        source=_SOURCE,
        lookback="최근 유효 5경주",
        null_policy="유효 기록이 없으면 null",
        leakage_note="과거 경주만 사용",
    ),
    FeatureSpec(
        name="speed_figure_trend",
        group=GROUP,
        description="최근 2경주 평균과 그 이전 최대 3경주 평균의 차이",
        source=_SOURCE,
        lookback="최근 유효 5경주",
        null_policy="유효 기록 4회 미만이면 null",
        leakage_note="과거 경주만 사용",
    ),
    FeatureSpec(
        name="speed_figure_count5",
        group=GROUP,
        description="최근 5경주 창의 유효 보정 속도지수 수",
        source=_SOURCE,
        lookback="최근 5경주",
        null_policy="이력 없으면 0",
        leakage_note="과거 경주만 사용",
    ),
    FeatureSpec(
        name="speed_figure_censored_rate5",
        group=GROUP,
        description="최근 유효 5경주 중 큰 착차 하위권으로 하한 절단된 비율",
        source=_SOURCE,
        lookback="최근 유효 5경주",
        null_policy="유효 기록이 없으면 null",
        leakage_note="완료된 과거 경주의 착순만 사용",
    ),
    FeatureSpec(
        name="speed_figure_exact_distance_avg5",
        group=GROUP,
        description="현재와 정확히 같은 거리의 최근 유효 5경주 보정지수 평균",
        source=_SOURCE,
        lookback="동일 거리 최근 유효 5경주",
        null_policy="동일 거리 이력이 없으면 null",
        leakage_note="현재 거리와 과거 결과만 사용",
    ),
    FeatureSpec(
        name="speed_figure_exact_distance_count5",
        group=GROUP,
        description="현재와 정확히 같은 거리의 최근 유효 보정지수 수(최대 5)",
        source=_SOURCE,
        lookback="동일 거리 최근 유효 5경주",
        null_policy="동일 거리 이력이 없으면 0",
        leakage_note="현재 거리와 과거 결과만 사용",
    ),
]


@dataclass(frozen=True)
class _RaceSummary:
    race_id: int
    race_date: date
    meet_code: int
    distance_m: int
    going: str
    top3_speed: float


@dataclass(frozen=True)
class PerformanceObservation:
    """Leakage-safe, course/going-adjusted observation from one completed race."""

    figure: float
    distance_m: int
    censored: int


def _going_key(value: object) -> str:
    if value is None:
        return "unknown"
    cleaned = str(value).strip()
    return cleaned if cleaned in {"건조", "양호", "다습", "포화", "불량"} else "unknown"


def _valid_speed(meet_code: object, distance_m: object, finish_time_ms: object) -> float | None:
    if distance_m is None or finish_time_ms is None:
        return None
    distance = float(distance_m)
    elapsed = float(finish_time_ms)
    if distance <= 0 or elapsed <= 0:
        return None
    speed = distance / (elapsed / 1000.0)
    meet = int(meet_code) if meet_code is not None else 0
    lower, upper = (8.0, 16.0) if meet == 2 else (10.0, 20.0)
    return speed if lower <= speed <= upper else None


def _race_summaries(past: pl.DataFrame) -> list[_RaceSummary]:
    summaries: list[_RaceSummary] = []
    for race in past.filter(pl.col("finish_position").is_not_null()).partition_by(
        "race_id", maintain_order=False
    ):
        first = race.row(0, named=True)
        top_speeds = [
            speed
            for row in race.filter(pl.col("finish_position") <= 3).iter_rows(named=True)
            if (
                speed := _valid_speed(
                    row.get("meet_code"), row.get("distance_m"), row.get("finish_time_ms")
                )
            )
            is not None
        ]
        if not top_speeds:
            continue
        summaries.append(
            _RaceSummary(
                race_id=int(first["race_id"]),
                race_date=first["race_date"],
                meet_code=int(first["meet_code"]),
                distance_m=int(first["distance_m"]),
                going=_going_key(first.get("track_condition")),
                top3_speed=float(median(top_speeds)),
            )
        )
    return sorted(summaries, key=lambda item: (item.race_date, item.race_id))


def _pruned_values(history: deque[tuple[date, float]], current_date: date) -> list[float]:
    cutoff = current_date - timedelta(days=_PAR_LOOKBACK_DAYS)
    while history and history[0][0] < cutoff:
        history.popleft()
    return [value for _, value in history]


def _race_pars_and_variants(
    summaries: list[_RaceSummary],
) -> tuple[dict[int, float], dict[int, float]]:
    exact_history: dict[tuple[int, int, str], deque[tuple[date, float]]] = defaultdict(deque)
    distance_history: dict[tuple[int, int], deque[tuple[date, float]]] = defaultdict(deque)
    pars: dict[int, float] = {}
    sample_sizes: dict[int, float] = {}

    by_date: dict[date, list[_RaceSummary]] = defaultdict(list)
    for summary in summaries:
        by_date[summary.race_date].append(summary)

    for race_date in sorted(by_date):
        day = by_date[race_date]
        for summary in day:
            exact = _pruned_values(
                exact_history[(summary.meet_code, summary.distance_m, summary.going)],
                race_date,
            )
            fallback = _pruned_values(
                distance_history[(summary.meet_code, summary.distance_m)], race_date
            )
            values: list[float] = []
            if len(exact) >= _MIN_GOING_PAR_RACES:
                values = exact
            elif len(fallback) >= _MIN_DISTANCE_PAR_RACES:
                values = fallback
            if values:
                pars[summary.race_id] = float(median(values))
                sample_sizes[summary.race_id] = float(len(values))
        # Same-day races cannot influence one another's baseline par.
        for summary in day:
            exact_history[(summary.meet_code, summary.distance_m, summary.going)].append(
                (race_date, summary.top3_speed)
            )
            distance_history[(summary.meet_code, summary.distance_m)].append(
                (race_date, summary.top3_speed)
            )

    variants: dict[tuple[date, int], float] = {}
    grouped_residuals: dict[tuple[date, int], list[float]] = defaultdict(list)
    for summary in summaries:
        par = pars.get(summary.race_id)
        if par and par > 0:
            grouped_residuals[(summary.race_date, summary.meet_code)].append(
                math.log(summary.top3_speed / par)
            )
    for key, residuals in grouped_residuals.items():
        variant = float(median(residuals)) if len(residuals) >= _MIN_DAY_VARIANT_RACES else 0.0
        variants[key] = max(-_MAX_DAY_VARIANT_LOG, min(_MAX_DAY_VARIANT_LOG, variant))

    adjusted_pars: dict[int, float] = {}
    for summary in summaries:
        par = pars.get(summary.race_id)
        if par is None:
            continue
        adjusted_pars[summary.race_id] = par * math.exp(
            variants.get((summary.race_date, summary.meet_code), 0.0)
        )
    return adjusted_pars, sample_sizes


def performance_observations(past: pl.DataFrame) -> dict[int, PerformanceObservation]:
    """Return adjusted historical observations keyed by race-entry id."""
    summaries = _race_summaries(past)
    adjusted_pars, _ = _race_pars_and_variants(summaries)
    observations: dict[int, PerformanceObservation] = {}
    for row in past.iter_rows(named=True):
        if row.get("finish_position") is None:
            continue
        par = adjusted_pars.get(int(row["race_id"]))
        speed = _valid_speed(
            row.get("meet_code"), row.get("distance_m"), row.get("finish_time_ms")
        )
        if par is None or speed is None or par <= 0:
            continue
        raw_figure = 100.0 * math.log(speed / par)
        raw_figure = max(_FIGURE_MIN, min(_FIGURE_MAX, raw_figure))
        starters = max(1, int(row.get("starters") or 1))
        percentile = (
            0.0
            if starters <= 1
            else (int(row["finish_position"]) - 1) / (starters - 1)
        )
        censored = int(percentile >= _TAIL_FINISH_PERCENTILE and raw_figure < _TAIL_FLOOR)
        figure = max(raw_figure, _TAIL_FLOOR) if censored else raw_figure
        observations[int(row["race_entry_id"])] = PerformanceObservation(
            figure=float(figure),
            distance_m=int(row["distance_m"]),
            censored=censored,
        )
    return observations


def _summarize(
    history: list[PerformanceObservation], current_distance: int | None
) -> dict[str, float | int | None]:
    recent = history[-5:]
    figures = [item.figure for item in recent]
    last3 = figures[-3:]
    trend = None
    if len(figures) >= 4:
        trend = sum(figures[-2:]) / 2.0 - sum(figures[:-2]) / len(figures[:-2])
    exact = (
        [item.figure for item in history if item.distance_m == current_distance][-5:]
        if current_distance is not None
        else []
    )
    return {
        "speed_figure_last": figures[-1] if figures else None,
        "speed_figure_avg3": sum(last3) / len(last3) if last3 else None,
        "speed_figure_median5": float(median(figures)) if figures else None,
        "speed_figure_best5": max(figures) if figures else None,
        "speed_figure_trend": trend,
        "speed_figure_count5": len(figures),
        "speed_figure_censored_rate5": (
            sum(item.censored for item in recent) / len(recent) if recent else None
        ),
        "speed_figure_exact_distance_avg5": sum(exact) / len(exact) if exact else None,
        "speed_figure_exact_distance_count5": len(exact),
    }


def _pre_race_features(past: pl.DataFrame) -> pl.DataFrame:
    required = {
        "race_entry_id",
        "race_id",
        "horse_id",
        "race_date",
        "meet_code",
        "distance_m",
        "finish_position",
        "finish_time_ms",
        "starters",
    }
    if past.height == 0 or not required <= set(past.columns):
        return pl.DataFrame()
    observations = performance_observations(past)
    ordered = past.sort("race_date", "race_id", "race_entry_id")
    histories: dict[int, list[PerformanceObservation]] = defaultdict(list)
    output: list[dict[str, object]] = []
    for day in ordered.partition_by("race_date", maintain_order=True):
        pending: list[tuple[int, PerformanceObservation]] = []
        for row in day.iter_rows(named=True):
            horse_id = int(row["horse_id"])
            output.append(
                {
                    "race_entry_id": int(row["race_entry_id"]),
                    **_summarize(histories[horse_id], row.get("distance_m")),
                }
            )
            observation = observations.get(int(row["race_entry_id"]))
            if observation is not None:
                pending.append((horse_id, observation))
        for horse_id, observation in pending:
            histories[horse_id].append(observation)
    return pl.DataFrame(output, infer_schema_length=None)


def _empty(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        *[
            pl.lit(0).cast(pl.Int64).alias(name)
            if name in {"speed_figure_count5", "speed_figure_exact_distance_count5"}
            else pl.lit(None).cast(pl.Float64).alias(name)
            for name in _FEATURE_NAMES
        ]
    )


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    features = _pre_race_features(sources.past_results)
    if features.height == 0:
        return _empty(frame)
    result = frame.join(features, on="race_entry_id", how="left")
    return result.with_columns(
        pl.col("speed_figure_count5").fill_null(0).cast(pl.Int64),
        pl.col("speed_figure_exact_distance_count5").fill_null(0).cast(pl.Int64),
    )
