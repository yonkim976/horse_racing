"""Verified section summaries for exact-distance race and trial selections."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from statistics import median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from horse_racing.db.models import (
    RaceEntry,
    RaceResult,
    RunningTrial,
    RunningTrialResult,
    SourceDocument,
)
from horse_racing.services.section_read import SectionObservation, load_section_observations
from horse_racing.web.formatting import format_distance_seconds

_SQLITE_BATCH_SIZE = 500
_POSTGRES_BATCH_SIZE = 2000
_NORMAL_FINISH_POSITIONS = (1, 89)
_EXCLUDED_TRIAL_JUDGEMENTS = frozenset({"출", "심", "주"})
_CORE_CODES = ("S1F", "G3F", "G1F")
AnalysisCache = Callable[[tuple[object, ...], Callable[[], Any]], Any]


@dataclass
class _Values:
    times: list[float] = field(default_factory=list)
    ratios: list[float] = field(default_factory=list)

    def add(self, time_ms: float, *, distance_m: int, race_distance_m: int, finish_ms: int) -> None:
        if time_ms <= 0 or time_ms >= finish_ms or distance_m <= 0 or race_distance_m <= 0:
            return
        self.times.append(float(time_ms))
        self.ratios.append(100.0 * distance_m * finish_ms / (time_ms * race_distance_m))


@dataclass
class _Metric:
    values: _Values = field(default_factory=_Values)
    positive: int = 0
    basis_known: int = 0
    shorter_than_finish: int = 0


def _formatted(values: _Values, normal_count: int) -> dict[str, Any]:
    if not values.times:
        mean_time = median_time = relative_speed = "—"
    else:
        mean_time = format_distance_seconds(sum(values.times) / len(values.times) / 1000)
        median_time = format_distance_seconds(median(values.times) / 1000)
        relative_speed = f"{sum(values.ratios) / len(values.ratios):.2f}%"
    return {
        "mean_time": mean_time,
        "median_time": median_time,
        "relative_speed": relative_speed,
        "sample_count": len(values.times),
        "normal_count": normal_count,
    }


def _race_point_positions(meet_code: int, distance_m: int) -> dict[str, int]:
    if meet_code in {1, 2}:
        s1f_distance = 210 if meet_code == 2 and distance_m == 1110 else 200
        return {
            "S1F": s1f_distance,
            "G3F": distance_m - 600,
            "G1F": distance_m - 200,
        }
    return {
        "S1F": 200,
        "G4F": distance_m - 800,
        "G3F": distance_m - 600,
        "G2F": distance_m - 400,
        "G1F": distance_m - 200,
    }


def _trial_point_positions(meet_code: int, distance_m: int) -> dict[str, int]:
    if meet_code in {1, 2}:
        return {
            "S1F": 200,
            "G3F": distance_m - 600,
            "G1F": distance_m - 200,
        }
    if meet_code == 3:
        # The Busan trial sheet defines S1F, final 400m, and G1F; its printed
        # G3F field has no verified interval basis and is intentionally omitted.
        return {
            "S1F": 200,
            "FINAL400": distance_m - 400,
            "G1F": distance_m - 200,
        }
    return {}


def _valid_positions(points: dict[str, int], distance_m: int) -> dict[str, int]:
    return {
        code: position
        for code, position in points.items()
        if 0 < position < distance_m
    }


def _intervals(points: dict[str, int], distance_m: int) -> list[tuple[int, int]]:
    positions = sorted({0, distance_m, *_valid_positions(points, distance_m).values()})
    intervals = {
        (start, end)
        for index, start in enumerate(positions)
        for end in positions[index + 1 :]
        if end - start == 200
    }
    for start, end in zip(positions, positions[1:], strict=False):
        if (end - start) % 200 == 0:
            intervals.update((point, point + 200) for point in range(start, end, 200))
    return sorted(intervals)


def _interval_label(start: int, end: int, distance_m: int) -> str:
    if start == 0:
        return "출발 0–200m"
    if end == distance_m:
        return "마지막 200m"
    return f"{start:,}–{end:,}m"


def _query_batch_size(session: Session) -> int:
    if session.get_bind().dialect.name == "postgresql":
        return _POSTGRES_BATCH_SIZE
    return _SQLITE_BATCH_SIZE


def _drop_non_monotonic_endpoints(
    endpoints: dict[int, float], distance_m: int
) -> set[int]:
    """Drop every internal point participating in any cumulative-time reversal."""
    invalid: set[int] = set()
    positions = sorted(endpoints)
    for index, start in enumerate(positions):
        for end in positions[index + 1 :]:
            if endpoints[end] <= endpoints[start]:
                if start not in {0, distance_m}:
                    invalid.add(start)
                if end not in {0, distance_m}:
                    invalid.add(end)
    for position in invalid:
        endpoints.pop(position, None)
    return invalid


def _explicit_endpoint(
    observation: SectionObservation,
    finish_ms: int,
) -> tuple[float | None, bool, bool]:
    """Return cumulative endpoint time and positive/basis validity indicators."""
    cumulative = observation.cumulative_time_ms
    closing = observation.closing_time_ms
    raw = observation.elapsed_time_ms
    positive = any(value is not None and value > 0 for value in (cumulative, closing, raw))
    known_basis = observation.time_basis in {"cumulative", "closing"}
    if cumulative is not None and closing is not None:
        if cumulative <= 0 or closing <= 0 or abs(cumulative + closing - finish_ms) > 100:
            return None, positive, known_basis
        endpoint = float(cumulative)
    elif observation.time_basis == "cumulative" and raw is not None:
        endpoint = float(raw)
    elif observation.time_basis == "closing" and raw is not None:
        endpoint = float(finish_ms - raw)
    else:
        return None, positive, known_basis
    if endpoint <= 0 or endpoint >= finish_ms:
        return None, positive, known_basis
    return endpoint, positive, known_basis


def _resolve_endpoints(
    observations: list[SectionObservation],
    positions: dict[str, int],
    distance_m: int,
    finish_ms: int,
) -> tuple[dict[int, float], dict[str, tuple[float | None, bool, bool]]]:
    candidates: dict[int, list[float]] = defaultdict(list)
    metric_points: dict[str, tuple[float | None, bool, bool]] = {}
    by_code = {row.section_code: row for row in observations}
    for code, position in _valid_positions(positions, distance_m).items():
        observation = by_code.get(code)
        if observation is None:
            metric_points[code] = (None, False, False)
            continue
        endpoint, positive, basis_known = _explicit_endpoint(observation, finish_ms)
        metric_points[code] = (endpoint, positive, basis_known)
        if endpoint is not None:
            candidates[position].append(endpoint)
    endpoints: dict[int, float] = {0: 0.0, distance_m: float(finish_ms)}
    for position, values in candidates.items():
        if max(values) - min(values) <= 100:
            endpoints[position] = sum(values) / len(values)
        else:
            for code, point in _valid_positions(positions, distance_m).items():
                if point == position and code in metric_points:
                    _, positive, basis_known = metric_points[code]
                    metric_points[code] = (None, positive, basis_known)
    return endpoints, metric_points


def _add_core_metrics(
    metrics: dict[str, _Metric],
    *,
    positions: dict[str, int],
    metric_points: dict[str, tuple[float | None, bool, bool]],
    distance_m: int,
    finish_ms: int,
) -> None:
    for code in _CORE_CODES:
        position = _valid_positions(positions, distance_m).get(code)
        if position is None:
            continue
        metric = metrics[code]
        endpoint, positive, basis_known = metric_points.get(code, (None, False, False))
        if positive:
            metric.positive += 1
        if basis_known:
            metric.basis_known += 1
        if endpoint is not None:
            metric.shorter_than_finish += 1
            section_distance = position if code == "S1F" else (
                600 if code == "G3F" else 200
            )
            duration = endpoint if code == "S1F" else finish_ms - endpoint
            metric.values.add(
                duration,
                distance_m=section_distance,
                race_distance_m=distance_m,
                finish_ms=finish_ms,
            )


def _empty_metrics() -> dict[str, _Metric]:
    return {code: _Metric() for code in _CORE_CODES}


def _core_rows(
    metrics: dict[str, _Metric],
    *,
    meet_code: int,
    distance_m: int,
    normal_count: int,
    s1f_distance_override: int | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for code, label, section_distance in (
        ("S1F", "출발 200m", 200),
        ("G3F", "마지막 600m", 600),
        ("G1F", "마지막 200m", 200),
    ):
        metric = metrics[code]
        if code == "S1F" and s1f_distance_override is not None:
            actual_distance = s1f_distance_override
        elif code == "S1F" and meet_code == 2 and distance_m == 1110:
            actual_distance = 210
        else:
            actual_distance = section_distance
        applicable = (code == "S1F" and actual_distance < distance_m) or (
            code != "S1F" and distance_m > section_distance
        )
        row = {
            "code": code,
            "label": f"출발 {actual_distance}m" if code == "S1F" else label,
            "section_distance": actual_distance,
            "applicable": applicable,
            **_formatted(metric.values, normal_count),
            "positive_count": metric.positive,
            "basis_count": metric.basis_known,
            "shorter_count": metric.shorter_than_finish,
        }
        rows.append(row)
    return rows


def _interval_rows(
    values_by_interval: dict[tuple[int, int], _Values],
    *,
    positions: dict[str, int],
    distance_m: int,
    normal_count: int,
) -> list[dict[str, Any]]:
    return [
        {
            "label": _interval_label(start, end, distance_m),
            "start_m": start,
            "end_m": end,
            **_formatted(values_by_interval[(start, end)], normal_count),
        }
        for start, end in _intervals(positions, distance_m)
    ]


def _date_conditions(year: int):
    if year == 0:
        return ()
    return (
        RunningTrial.trial_date_local >= date(year, 1, 1),
        RunningTrial.trial_date_local <= date(year, 12, 31),
    )


def _trial_result_is_normal(
    position: int | None,
    finish_ms: int | None,
    judgement: str | None,
    field_size: int,
) -> bool:
    return (
        position is not None
        and 1 <= position <= field_size
        and finish_ms is not None
        and finish_ms > 0
        and (judgement is None or judgement.strip() not in _EXCLUDED_TRIAL_JUDGEMENTS)
    )


def _trial_group_counts(
    session: Session, *, meet_code: int, year: int
) -> tuple[dict[int, int], dict[int, int]]:
    conditions = [RunningTrial.meet_code == meet_code, RunningTrial.distance_m <= 1200]
    conditions.extend(_date_conditions(year))
    all_rows = session.execute(
        select(RunningTrial.distance_m, func.count(RunningTrial.id))
        .where(*conditions)
        .group_by(RunningTrial.distance_m)
    ).all()
    verified_rows = session.execute(
        select(RunningTrial.distance_m, func.count(RunningTrial.id))
        .join(SourceDocument, SourceDocument.id == RunningTrial.source_document_id)
        .where(*conditions, SourceDocument.operation == "dacom23")
        .group_by(RunningTrial.distance_m)
    ).all()
    return dict(all_rows), dict(verified_rows)


def _trial_metrics(
    session: Session,
    *,
    meet_code: int,
    year: int,
    all_trial_counts: dict[int, int],
    verified_trial_counts: dict[int, int],
) -> list[dict[str, Any]]:
    buckets: dict[int, dict[str, Any]] = {}
    for distance_m in sorted(all_trial_counts):
        positions = _trial_point_positions(meet_code, distance_m)
        buckets[distance_m] = {
            "distance": distance_m,
            "trial_count": all_trial_counts[distance_m],
            "verified_trial_count": verified_trial_counts.get(distance_m, 0),
            "unverified_trial_count": (
                all_trial_counts[distance_m] - verified_trial_counts.get(distance_m, 0)
            ),
            "normal_count": 0,
            "metrics": _empty_metrics(),
            "intervals": defaultdict(_Values),
            "positions": positions,
        }

    conditions = [
        RunningTrial.meet_code == meet_code,
        RunningTrial.distance_m <= 1200,
        SourceDocument.operation == "dacom23",
    ]
    conditions.extend(_date_conditions(year))
    field_sizes = dict(
        session.execute(
            select(
                RunningTrialResult.running_trial_id,
                func.count(RunningTrialResult.id),
            )
            .join(RunningTrial, RunningTrial.id == RunningTrialResult.running_trial_id)
            .join(SourceDocument, SourceDocument.id == RunningTrial.source_document_id)
            .where(*conditions)
            .group_by(RunningTrialResult.running_trial_id)
        ).all()
    )
    batch_size = _query_batch_size(session)
    last_id = 0
    while True:
        rows = session.execute(
            select(
                RunningTrialResult.id,
                RunningTrialResult.running_trial_id,
                RunningTrial.distance_m,
                RunningTrialResult.finish_position,
                RunningTrialResult.finish_time_ms,
                RunningTrialResult.judgement,
                RunningTrialResult.s1f_ms,
                RunningTrialResult.g3f_ms,
                RunningTrialResult.g1f_ms,
                RunningTrialResult.final_400_ms,
            )
            .join(RunningTrial, RunningTrial.id == RunningTrialResult.running_trial_id)
            .join(SourceDocument, SourceDocument.id == RunningTrial.source_document_id)
            .where(*conditions, RunningTrialResult.id > last_id)
            .order_by(RunningTrialResult.id)
            .limit(batch_size)
        ).all()
        if not rows:
            break
        last_id = rows[-1].id
        for row in rows:
            bucket = buckets[row.distance_m]
            finish_ms = row.finish_time_ms
            if not _trial_result_is_normal(
                row.finish_position,
                finish_ms,
                row.judgement,
                field_sizes.get(row.running_trial_id, 0),
            ):
                continue
            bucket["normal_count"] += 1
            positions = bucket["positions"]
            point_values: dict[str, tuple[float | None, bool, bool]] = {}
            endpoint_candidates: dict[int, list[float]] = defaultdict(list)
            for code, position in _valid_positions(positions, row.distance_m).items():
                value = getattr(row, {
                    "S1F": "s1f_ms",
                    "G3F": "g3f_ms",
                    "G1F": "g1f_ms",
                    "FINAL400": "final_400_ms",
                }[code])
                if code == "G3F" and meet_code == 3:
                    point_values[code] = (None, value is not None and value > 0, False)
                    continue
                positive = value is not None and value > 0
                if not positive:
                    point_values[code] = (None, False, False)
                    continue
                if code == "S1F":
                    endpoint = float(value)
                elif code in {"G3F", "G1F", "FINAL400"}:
                    endpoint = float(finish_ms - value)
                else:
                    endpoint = None
                endpoint = endpoint if endpoint is not None and 0 < endpoint < finish_ms else None
                point_values[code] = (endpoint, True, True)
                if endpoint is not None:
                    endpoint_candidates[position].append(endpoint)
            endpoints: dict[int, float] = {0: 0.0, row.distance_m: float(finish_ms)}
            for position, values in endpoint_candidates.items():
                if max(values) - min(values) <= 100:
                    endpoints[position] = sum(values) / len(values)
                else:
                    for code, point in _valid_positions(positions, row.distance_m).items():
                        if point == position and code in point_values:
                            _, positive, basis_known = point_values[code]
                            point_values[code] = (None, positive, basis_known)
            invalid_positions = _drop_non_monotonic_endpoints(endpoints, row.distance_m)
            for code, position in _valid_positions(positions, row.distance_m).items():
                if position in invalid_positions and code in point_values:
                    _, positive, basis_known = point_values[code]
                    point_values[code] = (None, positive, basis_known)
            _add_core_metrics(
                bucket["metrics"],
                positions=positions,
                metric_points=point_values,
                distance_m=row.distance_m,
                finish_ms=finish_ms,
            )
            for start, end in _intervals(positions, row.distance_m):
                if start not in endpoints or end not in endpoints:
                    continue
                duration = endpoints[end] - endpoints[start]
                bucket["intervals"][(start, end)].add(
                    duration,
                    distance_m=end - start,
                    race_distance_m=row.distance_m,
                    finish_ms=finish_ms,
                )

    output = []
    for distance_m, bucket in sorted(buckets.items()):
        positions = bucket["positions"]
        metrics = bucket["metrics"]
        core_rows = _core_rows(
            metrics,
            meet_code=meet_code,
            distance_m=distance_m,
            normal_count=bucket["normal_count"],
            s1f_distance_override=200,
        )
        if meet_code == 3:
            for row in core_rows:
                if row["code"] == "G3F":
                    row["label"] = "G3F · 기준 미확인"
                    row["basis_note"] = (
                        "부경 주행심사의 G3F 원기록은 계측 기준 미확인으로 집계 제외"
                    )
        output.append(
            {
                "distance": distance_m,
                "trial_count": bucket["trial_count"],
                "verified_trial_count": bucket["verified_trial_count"],
                "unverified_trial_count": bucket["unverified_trial_count"],
                "normal_count": bucket["normal_count"],
                "core": core_rows,
                "intervals": _interval_rows(
                    bucket["intervals"],
                    positions=positions,
                    distance_m=distance_m,
                    normal_count=bucket["normal_count"],
                ),
            }
        )
    return output


def _load_race_section_analysis(
    session: Session,
    *,
    selected_race_ids,
    meet_code: int,
    distance_m: int,
) -> dict[str, Any]:
    """Aggregate explicit section timings for the selected course and year."""
    enabled = 0 < distance_m <= 1200
    metrics = _empty_metrics()
    interval_values: dict[tuple[int, int], _Values] = defaultdict(_Values)
    positions = _race_point_positions(meet_code, distance_m)
    normal_count = 0
    if enabled:
        interval_positions = _intervals(positions, distance_m)
        normal = (
            RaceResult.finish_position.between(*_NORMAL_FINISH_POSITIONS)
            & (RaceResult.finish_time_ms > 0)
            & RaceResult.disqualified.is_(False)
            & RaceEntry.scratched.is_(False)
        )
        query = (
            select(RaceEntry.id, RaceResult.finish_time_ms)
            .join(RaceResult, RaceResult.race_entry_id == RaceEntry.id)
            .where(RaceEntry.race_id.in_(selected_race_ids), normal)
        )
        batch_size = _query_batch_size(session)
        last_id = 0
        while True:
            rows = session.execute(
                query.where(RaceEntry.id > last_id)
                .order_by(RaceEntry.id)
                .limit(batch_size)
            ).all()
            if not rows:
                break
            last_id = rows[-1].id
            observations = load_section_observations(
                session,
                [row.id for row in rows],
                batch_size=batch_size,
            )
            for row in rows:
                normal_count += 1
                finish_ms = row.finish_time_ms
                entry_observations = observations.get(row.id, [])
                endpoints, metric_points = _resolve_endpoints(
                    entry_observations, positions, distance_m, finish_ms
                )
                invalid_positions = _drop_non_monotonic_endpoints(endpoints, distance_m)
                for code, position in _valid_positions(positions, distance_m).items():
                    if position in invalid_positions and code in metric_points:
                        _, positive, basis_known = metric_points[code]
                        metric_points[code] = (None, positive, basis_known)
                _add_core_metrics(
                    metrics,
                    positions=positions,
                    metric_points=metric_points,
                    distance_m=distance_m,
                    finish_ms=finish_ms,
                )
                for start, end in interval_positions:
                    if start not in endpoints or end not in endpoints:
                        continue
                    interval_values[(start, end)].add(
                        endpoints[end] - endpoints[start],
                        distance_m=end - start,
                        race_distance_m=distance_m,
                        finish_ms=finish_ms,
                    )

    core_rows = (
        _core_rows(
            metrics,
            meet_code=meet_code,
            distance_m=distance_m,
            normal_count=normal_count,
        )
        if enabled
        else []
    )
    interval_rows = (
        _interval_rows(
            interval_values,
            positions=positions,
            distance_m=distance_m,
            normal_count=normal_count,
        )
        if enabled
        else []
    )
    return {
        "visible": True,
        "enabled": enabled,
        "reason": (
            "select" if distance_m <= 0 else "over_limit" if distance_m > 1200 else None
        ),
        "normal_count": normal_count,
        "core": core_rows,
        "intervals": interval_rows,
    }


def load_distance_section_analysis(
    session: Session,
    *,
    selected_race_ids,
    meet_code: int,
    year: int,
    distance_m: int,
    grade: str = "",
    cache: AnalysisCache | None = None,
) -> dict[str, Any]:
    """Reuse exact aggregates independently of pagination and benchmark bands.

    The optional cache owns retention and single-flight behavior. It receives
    result loaders, never stores sessions, and must invoke a miss loader before
    this call returns. Race selection must match the supplied meet, resolved
    year, distance and normalized grade; year zero keeps the complete history.
    """
    def load_races() -> dict[str, Any]:
        return _load_race_section_analysis(
            session,
            selected_race_ids=selected_race_ids,
            meet_code=meet_code,
            distance_m=distance_m,
        )

    def load_trials() -> list[dict[str, Any]]:
        all_counts, verified_counts = _trial_group_counts(
            session, meet_code=meet_code, year=year,
        )
        return _trial_metrics(
            session,
            meet_code=meet_code,
            year=year,
            all_trial_counts=all_counts,
            verified_trial_counts=verified_counts,
        )

    races = (load_races() if cache is None else cache(
        ("distance-race-sections", meet_code, year, distance_m, grade), load_races,
    ))
    trials = (load_trials() if cache is None else cache(
        ("distance-trials", meet_code, year), load_trials,
    ))
    return {**races, "trials": trials}
