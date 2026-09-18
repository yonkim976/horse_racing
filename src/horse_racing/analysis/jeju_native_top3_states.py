"""Past-only state features for the Jeju native top-three study.

This module intentionally contains no estimator or outcome labels.  It builds a
snapshot of each horse immediately before a target race.  Historical dates are
treated conservatively: a date-only event is available only through ``T-2``
for a target on date ``T``.  The extra day is the fixed lag used by the V1
research contract; it is not evidence that the source was published then.

The Elo and speed quantities below are deterministic heuristics.  They are
state summaries, not fitted probabilities or physical performance intervals.
"""

from __future__ import annotations

import sqlite3
from bisect import bisect_left, bisect_right
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from math import sqrt
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any

import polars as pl

STATE_VERSION = "jeju_native_top3_states_v1_r2"
HISTORY_LAG_DAYS = 2
ELO_INITIAL = 1500.0
ELO_K = 20.0
SEPARATE_DISTANCE_M = 400
NORMAL_MAX_POSITION = 89


def _era_regime(event_date: date) -> str:
    if event_date < date(2018, 8, 31):
        return "pre_2018_08_31"
    if event_date < date(2023, 1, 1):
        return "2018_08_31_2022_12_31"
    if event_date < date(2025, 12, 28):
        return "2023_01_01_2025_12_27"
    return "post_2025_12_28"


_ENTRY_KEYS = ("entry_id", "race_id", "horse_id", "event_date", "distance_m")
_HISTORY_KEYS = ("entry_id", "race_id", "horse_id", "event_date", "distance_m")


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() and len(text) == 8:
        return datetime.strptime(text, "%Y%m%d").date()
    return date.fromisoformat(text[:10])


def _horse_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text.zfill(7) if text.isdigit() else text


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def _normal_position(value: Any) -> bool:
    position = _integer(value)
    return position is not None and 1 <= position <= NORMAL_MAX_POSITION


def _started_position(value: Any) -> bool:
    position = _integer(value)
    return (position is not None and 1 <= position <= NORMAL_MAX_POSITION) or position in (91, 92)


def _valid_time(value: Any) -> bool:
    number = _number(value)
    return number is not None and number > 0


def _as_float(value: float | int | None) -> float | None:
    return None if value is None else float(value)


def _required(frame: pl.DataFrame, columns: Iterable[str], name: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{name} is missing required columns: {missing}")


def _check_duplicate_keys(frame: pl.DataFrame, keys: tuple[str, ...], name: str) -> int:
    if frame.height == 0:
        return 0
    duplicate = frame.group_by(list(keys)).len().filter(pl.col("len") > 1)
    if duplicate.height == 0:
        return 0
    # Identical source repeats are safely collapsed.  Conflicting rows are
    # ambiguous and must not silently choose a result.
    non_key = [column for column in frame.columns if column not in keys]
    conflicts = (
        (
            frame.group_by(list(keys))
            .agg([pl.col(column).n_unique().alias(f"n_{column}") for column in non_key])
            .filter(pl.any_horizontal([pl.col(f"n_{column}") > 1 for column in non_key]))
        )
        if non_key
        else pl.DataFrame()
    )
    if conflicts.height:
        raise ValueError(f"conflicting duplicate {name} keys: {conflicts.height}")
    return int(duplicate.select(pl.col("len").sum()).item()) - int(duplicate.height)


def _deduplicate_history(frame: pl.DataFrame) -> tuple[pl.DataFrame, int]:
    duplicate_rows = _check_duplicate_keys(frame, _HISTORY_KEYS, "history_results")
    if duplicate_rows:
        frame = frame.unique(subset=list(_HISTORY_KEYS), keep="first", maintain_order=False)
    return frame, duplicate_rows


@dataclass
class _DistanceState:
    elo: dict[str, float] = field(default_factory=dict)
    starts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    completed: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    wins: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    top3: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    usable: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    times: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    residuals: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    sections: dict[str, dict[str, deque[float]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(lambda: deque(maxlen=10)))
    )


@dataclass
class _HorseState:
    global_elo: float = ELO_INITIAL
    starts: int = 0
    completed: int = 0
    wins: int = 0
    top3: int = 0
    usable: int = 0
    last_start: date | None = None
    last_normal: date | None = None
    ranks: deque[float] = field(default_factory=lambda: deque(maxlen=5))
    recent_positions: deque[int] = field(default_factory=lambda: deque(maxlen=5))
    residuals: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    times: deque[float] = field(default_factory=lambda: deque(maxlen=10))
    by_distance: dict[int, _DistanceState] = field(default_factory=dict)

    def distance(self, distance_m: int) -> _DistanceState:
        if distance_m not in self.by_distance:
            self.by_distance[distance_m] = _DistanceState()
        return self.by_distance[distance_m]


@dataclass
class _EventRow:
    entry_id: int
    race_id: int
    horse_id: str
    event_date: date
    distance_m: int
    finish_position: int | None
    finish_time_ms: float | None
    segment_quality: str
    field_size: int
    sections: dict[str, float]


def _frame_rows(history: pl.DataFrame) -> list[_EventRow]:
    fields = set(history.columns)
    section_candidates = {
        "s1f_ms": "s1f_ms",
        "g1f_ms": "g1f_ms",
        "g3f_ms": "g3f_ms",
        "section_s1f_ms": "s1f_ms",
        "section_s1f210_ms": "s1f210_ms",
        "section_g1f_ms": "g1f_ms",
        "section_g3f_ms": "g3f_ms",
    }
    raw = history.to_dicts()
    result: list[_EventRow] = []
    for row in raw:
        position = _integer(row.get("finish_position"))
        result.append(
            _EventRow(
                entry_id=int(row["entry_id"]),
                race_id=int(row["race_id"]),
                horse_id=_horse_id(row["horse_id"]),
                event_date=_to_date(row["event_date"]) or date.min,
                distance_m=int(row["distance_m"]),
                finish_position=position,
                finish_time_ms=_number(row.get("finish_time_ms")),
                segment_quality=str(row.get("segment_quality") or ""),
                field_size=int(row.get("field_size") or 0),
                sections={
                    canonical: float(row[key])
                    for key, canonical in section_candidates.items()
                    if key in fields and _valid_time(row.get(key))
                },
            )
        )
    # Source event IDs are the race ordering key.  Entry IDs break ties in a
    # deterministic way and do not affect a pre-state because updates happen
    # only after the complete event has been observed.
    result.sort(key=lambda item: (item.event_date, item.race_id, item.entry_id))
    by_race: dict[tuple[date, int], list[_EventRow]] = defaultdict(list)
    for item in result:
        by_race[(item.event_date, item.race_id)].append(item)
    for rows in by_race.values():
        observed_size = len(rows)
        for item in rows:
            if item.field_size <= 0:
                item.field_size = observed_size
    return result


def _new_history_values() -> dict[str, Any]:
    return {
        "global_elo_pre": ELO_INITIAL,
        "distance_elo_pre": ELO_INITIAL,
        "ability_mean_pre": ELO_INITIAL,
        "distance_state_pre": ELO_INITIAL,
        "elo_uncertainty_pre": 1.0,
        "ability_uncertainty_pre": 1.0,
        "starts_pre": 0,
        "normal_completed_pre": 0,
        "wins_pre": 0,
        "top3_pre": 0,
        "normal_usable_count_pre": 0,
        "normal_history_count": 0,
        "usable_time_count": 0,
        "days_since_previous_start": None,
        "days_since_previous_normal_finish": None,
        "distance_starts_pre": 0,
        "distance_normal_completed_pre": 0,
        "distance_wins_pre": 0,
        "distance_top3_pre": 0,
        "distance_normal_usable_count_pre": 0,
        "recent_finish_score_5_mean": None,
        "recent_top3_rate_5": None,
        "performance_variability_pre": None,
        "speed_time_per_100m_mean_pre": None,
        "speed_residual_mean_pre": None,
        "speed_residual_std_pre": None,
        "speed_observation_count_pre": 0,
        "distance_speed_time_per_100m_mean_pre": None,
        "distance_speed_residual_mean_pre": None,
        "distance_speed_observation_count_pre": 0,
    }


def _snapshot(state: _HorseState, target_date: date, distance_m: int) -> dict[str, Any]:
    distance = state.distance(distance_m)
    rank_values = list(state.ranks)
    values = _new_history_values()
    values.update(
        {
            "global_elo_pre": state.global_elo,
            "distance_elo_pre": distance.elo.get("__horse__", ELO_INITIAL),
            "ability_mean_pre": state.global_elo,
            "distance_state_pre": distance.elo.get("__horse__", ELO_INITIAL),
            "elo_uncertainty_pre": 1.0 / sqrt(1.0 + state.starts),
            "ability_uncertainty_pre": 1.0 / sqrt(1.0 + state.starts),
            "starts_pre": state.starts,
            "normal_completed_pre": state.completed,
            "wins_pre": state.wins,
            "top3_pre": state.top3,
            "normal_usable_count_pre": state.usable,
            "normal_history_count": state.completed,
            "usable_time_count": state.usable,
            "days_since_previous_start": (
                (target_date - state.last_start).days if state.last_start is not None else None
            ),
            "days_since_previous_normal_finish": (
                (target_date - state.last_normal).days if state.last_normal is not None else None
            ),
            "distance_starts_pre": distance.starts.get("__horse__", 0),
            "distance_normal_completed_pre": distance.completed.get("__horse__", 0),
            "distance_wins_pre": distance.wins.get("__horse__", 0),
            "distance_top3_pre": distance.top3.get("__horse__", 0),
            "distance_normal_usable_count_pre": distance.usable.get("__horse__", 0),
            "recent_finish_score_5_mean": mean(rank_values) if rank_values else None,
            "recent_top3_rate_5": (
                sum(1 for value in state.recent_positions if value <= 3)
                / len(state.recent_positions)
                if state.recent_positions
                else None
            ),
            "performance_variability_pre": pstdev(rank_values) if len(rank_values) > 1 else None,
            # H1 time summaries are always target-distance specific.  A raw
            # all-distance time average would silently mix incomparable 400m
            # records into the global state.
            "speed_time_per_100m_mean_pre": (
                mean(distance.times.get("__horse__", []))
                if distance.times.get("__horse__")
                else None
            ),
            "speed_residual_mean_pre": (
                mean(distance.residuals.get("__horse__", []))
                if distance.residuals.get("__horse__")
                else None
            ),
            "speed_residual_std_pre": (
                pstdev(distance.residuals.get("__horse__", []))
                if len(distance.residuals.get("__horse__", [])) > 1
                else None
            ),
            "speed_observation_count_pre": len(distance.times.get("__horse__", [])),
            "distance_speed_time_per_100m_mean_pre": (
                mean(distance.times.get("__horse__", []))
                if distance.times.get("__horse__")
                else None
            ),
            "distance_speed_residual_mean_pre": (
                mean(distance.residuals.get("__horse__", []))
                if distance.residuals.get("__horse__")
                else None
            ),
            "distance_speed_observation_count_pre": len(distance.times.get("__horse__", [])),
        }
    )
    for name, values_seen in distance.sections.get("__horse__", {}).items():
        values[f"section_{name}_mean_pre"] = mean(values_seen) if values_seen else None
    return values


def _state_snapshot(
    state: _HorseState, horse_id: str, target_date: date, distance_m: int
) -> dict[str, Any]:
    """Snapshot with horse-specific distance maps materialized temporarily."""
    distance = state.distance(distance_m)
    # The distance state stores values by horse ID so the race updater can use
    # one compact structure for every horse.  _snapshot's sentinel aliases are
    # replaced for this horse only.
    distance.elo["__horse__"] = distance.elo.get(horse_id, ELO_INITIAL)
    distance.starts["__horse__"] = distance.starts.get(horse_id, 0)
    distance.completed["__horse__"] = distance.completed.get(horse_id, 0)
    distance.wins["__horse__"] = distance.wins.get(horse_id, 0)
    distance.top3["__horse__"] = distance.top3.get(horse_id, 0)
    distance.usable["__horse__"] = distance.usable.get(horse_id, 0)
    distance.times["__horse__"] = distance.times.get(horse_id, [])
    distance.residuals["__horse__"] = distance.residuals.get(horse_id, [])
    distance.sections["__horse__"] = distance.sections.get(horse_id, {})
    values = _snapshot(state, target_date, distance_m)
    for key in ("__horse__",):
        distance.elo.pop(key, None)
        distance.starts.pop(key, None)
        distance.completed.pop(key, None)
        distance.wins.pop(key, None)
        distance.top3.pop(key, None)
        distance.usable.pop(key, None)
        distance.times.pop(key, None)
        distance.residuals.pop(key, None)
        distance.sections.pop(key, None)
    return values


def _update_event(
    rows: list[_EventRow],
    states: dict[str, _HorseState],
    global_times: dict[tuple[int, str], list[float]],
    baseline_by_distance: dict[tuple[int, str], float | None] | None = None,
) -> None:
    """Apply one complete race after all its pre-state values are available."""
    if not rows:
        return
    distance_m = rows[0].distance_m
    normal = [row for row in rows if _normal_position(row.finish_position)]
    field_size = max((row.field_size for row in rows), default=len(rows)) or len(rows)
    pre_global = {row.horse_id: states[row.horse_id].global_elo for row in normal}
    distance_states = {row.horse_id: states[row.horse_id].distance(distance_m) for row in normal}

    def apply_pairwise(ratings: dict[str, float], update: bool = True) -> dict[str, float]:
        deltas = defaultdict(float)
        if len(normal) > 1:
            scale = 1.0 / (len(normal) - 1)
            for index, left in enumerate(normal):
                for right in normal[index + 1 :]:
                    left_rating = ratings[left.horse_id]
                    right_rating = ratings[right.horse_id]
                    expected_left = 1.0 / (1.0 + 10.0 ** ((right_rating - left_rating) / 400.0))
                    if left.finish_position < right.finish_position:
                        left_score = 1.0
                    elif left.finish_position > right.finish_position:
                        left_score = 0.0
                    else:
                        left_score = 0.5
                    deltas[left.horse_id] += ELO_K * scale * (left_score - expected_left)
                    deltas[right.horse_id] += (
                        ELO_K * scale * ((1 - left_score) - (1 - expected_left))
                    )
        if update:
            return {horse: ratings[horse] + deltas[horse] for horse in ratings}
        return dict(ratings)

    if distance_m != SEPARATE_DISTANCE_M:
        after_global = apply_pairwise(pre_global)
        for horse_id, value in after_global.items():
            states[horse_id].global_elo = value
    pre_distance = {
        row.horse_id: distance_states[row.horse_id].elo.get(row.horse_id, ELO_INITIAL)
        for row in normal
    }
    after_distance = apply_pairwise(pre_distance)
    for horse_id, value in after_distance.items():
        distance_states[horse_id].elo[horse_id] = value

    if baseline_by_distance is None:
        baseline = (
            median(global_times[(distance_m, _era_regime(rows[0].event_date))])
            if global_times[(distance_m, _era_regime(rows[0].event_date))]
            else None
        )
    else:
        baseline = baseline_by_distance.get((distance_m, _era_regime(rows[0].event_date)))
    for row in rows:
        state = states[row.horse_id]
        distance = state.distance(distance_m)
        if not _started_position(row.finish_position):
            continue
        distance.starts[row.horse_id] += 1
        # 400m remains a distance-only state.  It must not alter global
        # starts, recency, ranks, times, or global Elo used by other races.
        is_global_distance = distance_m != SEPARATE_DISTANCE_M
        if is_global_distance:
            state.starts += 1
            state.last_start = row.event_date
        if not _normal_position(row.finish_position):
            # DQ/DNF remain starts but never update normal ability, speed, or
            # rank summaries.
            continue
        distance.completed[row.horse_id] += 1
        distance.wins[row.horse_id] += int(row.finish_position == 1)
        distance.top3[row.horse_id] += int(row.finish_position <= 3)
        if is_global_distance:
            state.completed += 1
            state.last_normal = row.event_date
            state.wins += int(row.finish_position == 1)
            state.top3 += int(row.finish_position <= 3)
            state.recent_positions.append(row.finish_position)
            rank_score = (
                1.0 if field_size <= 1 else (field_size - row.finish_position) / (field_size - 1)
            )
            state.ranks.append(rank_score)
        usable_time = row.segment_quality == "usable" and _valid_time(row.finish_time_ms)
        if usable_time:
            distance.usable[row.horse_id] += 1
            time_per_100 = float(row.finish_time_ms) / float(max(row.distance_m, 1)) * 100.0
            distance.times.setdefault(row.horse_id, []).append(time_per_100)
            global_times[(distance_m, _era_regime(row.event_date))].append(time_per_100)
            if baseline is not None:
                residual = time_per_100 - baseline
                distance.residuals.setdefault(row.horse_id, []).append(residual)
            if is_global_distance:
                state.usable += 1
            for section_name, section_value in row.sections.items():
                distance.sections[row.horse_id][section_name].append(section_value)


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        )
    }


def _source_rows(db_path: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Read optional H2 source events once; never issue a query per target."""
    sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
    metadata: dict[str, Any] = {"available": False, "missing_tables": []}
    if not db_path or not Path(db_path).exists():
        metadata["missing_tables"] = ["database"]
        return sources, metadata
    try:
        connection = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    except sqlite3.Error:
        metadata["missing_tables"] = ["database"]
        return sources, metadata
    try:
        tables = _table_names(connection)
        queries = {
            "training": (
                "daily_training_record",
                "SELECT id,source_row_id,hr_no,event_date,training_duration_seconds,"
                "canter_count,gallop_count "
                "FROM daily_training_record WHERE meet=2",
            ),
            "start_training": (
                "analysis_start_training_distinct",
                "SELECT id,source_row_id,hr_no,event_date "
                "FROM analysis_start_training_distinct WHERE meet=2",
            ),
            "medical": (
                "analysis_medical_distinct",
                "SELECT id,source_row_id,hr_no,event_date "
                "FROM analysis_medical_distinct WHERE meet=2",
            ),
            "weight": (
                "analysis_measured_weight",
                "SELECT id,source_row_id,hr_no,event_date,event_number,body_weight_kg "
                "FROM analysis_measured_weight WHERE meet=2",
            ),
            "trial": (
                "entry+event",
                "SELECT e.id AS entry_id,v.id AS event_id,e.hr_no,v.event_date,v.event_number, "
                "e.finish_position,e.finish_time_ms,e.segment_quality "
                "FROM entry AS e JOIN event AS v ON v.id=e.event_id "
                "WHERE v.event_type='trial' AND e.identity_status='official_trial_hr_tr_linked'",
            ),
        }
        for name, (required, query) in queries.items():
            trial_tables_missing = name == "trial" and not {"entry", "event"}.issubset(tables)
            if (required not in tables and name != "trial") or trial_tables_missing:
                metadata["missing_tables"].append(required)
                continue
            try:
                columns = [
                    description[0] for description in connection.execute(query).description or []
                ]
                sources[name] = [
                    dict(zip(columns, row, strict=True))
                    for row in connection.execute(query).fetchall()
                ]
            except sqlite3.Error:
                metadata["missing_tables"].append(required)
        metadata["available"] = any(sources.values())
    finally:
        connection.close()
    return sources, metadata


def _index_source_rows(
    source_rows: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, tuple[list[dict[str, Any]], list[date]]]]:
    """Index optional source events once by horse, then sort each horse slice."""
    indexed: dict[str, dict[str, tuple[list[dict[str, Any]], list[date]]]] = {}
    for name, rows in source_rows.items():
        by_horse: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in rows:
            normalized = dict(item)
            normalized["_event_day"] = _to_date(item.get("event_date"))
            by_horse[_horse_id(item.get("hr_no"))].append(normalized)
        source_index: dict[str, tuple[list[dict[str, Any]], list[date]]] = {}
        for values in by_horse.values():
            values.sort(
                key=lambda item: (
                    item["_event_day"] or date.min,
                    int(item.get("id") or item.get("event_id") or 0),
                )
            )
            horse = _horse_id(values[0].get("hr_no"))
            source_index[horse] = (
                values,
                [item["_event_day"] or date.min for item in values],
            )
        indexed[name] = source_index
    return indexed


def _h2_features(
    horse_id: str,
    target_date: date,
    source_rows: dict[str, dict[str, tuple[list[dict[str, Any]], list[date]]]],
) -> dict[str, Any]:
    windows = {
        "training": (target_date - timedelta(days=29), target_date - timedelta(days=2)),
        "start_training": (target_date - timedelta(days=29), target_date - timedelta(days=2)),
        "medical": (target_date - timedelta(days=91), target_date - timedelta(days=2)),
        "weight": (date.min, target_date - timedelta(days=2)),
        "trial": (date.min, target_date - timedelta(days=2)),
    }
    result: dict[str, Any] = {
        "training_28d_count": 0,
        "training_28d_duration_seconds": 0,
        "training_28d_canter_count": 0,
        "training_28d_gallop_count": 0,
        "training_28d_coverage_unknown": 1,
        "training_28d_observed_any": 0,
        "start_training_28d_count": 0,
        "start_training_28d_coverage_unknown": 1,
        "start_training_28d_observed_any": 0,
        "medical_90d_count": 0,
        "medical_90d_coverage_unknown": 1,
        "medical_90d_observed_any": 0,
        "trial_count_pre": 0,
        "trial_last_valid_time_ms_pre": None,
        "trial_coverage_unknown": 1,
        "trial_observed_any": 0,
        "weight_last_kg_pre": None,
        "weight_count_pre": 0,
        "weight_coverage_unknown": 1,
        "weight_observed_any": 0,
    }
    for name in ("training", "start_training", "medical", "weight", "trial"):
        events = []
        lo, hi = windows[name]
        indexed = source_rows.get(name, {}).get(horse_id)
        if indexed is not None:
            items, dates = indexed
            first = bisect_left(dates, lo)
            last = bisect_right(dates, hi)
            events = [(dates[index], items[index]) for index in range(first, last)]
        if events:
            events.sort(key=lambda value: value[0])
            # Native/API sources can repeat a payload in a backfill.  Distinct
            # source rows/events remain distinct; only exact repeated IDs are
            # collapsed.  API and text sources are deliberately never combined.
            seen: set[tuple[Any, ...]] = set()
            unique_events: list[tuple[date, dict[str, Any]]] = []
            for event_day, item in events:
                key = (item.get("id"), item.get("source_row_id"), item.get("event_id"))
                if key == (None, None, None):
                    key = (
                        event_day,
                        item.get("event_number"),
                        item.get("finish_position"),
                        item.get("finish_time_ms"),
                    )
                if key in seen:
                    continue
                seen.add(key)
                unique_events.append((event_day, item))
            events = unique_events
            observed_name = {
                "training": "training_28d_observed_any",
                "start_training": "start_training_28d_observed_any",
                "medical": "medical_90d_observed_any",
                "trial": "trial_observed_any",
                "weight": "weight_observed_any",
            }[name]
            result[observed_name] = 1
        if name == "training":
            result["training_28d_count"] = len(events)
            result["training_28d_duration_seconds"] = sum(
                int(item.get("training_duration_seconds") or 0) for _, item in events
            )
            result["training_28d_canter_count"] = sum(
                int(item.get("canter_count") or 0) for _, item in events
            )
            result["training_28d_gallop_count"] = sum(
                int(item.get("gallop_count") or 0) for _, item in events
            )
        elif name == "start_training":
            result["start_training_28d_count"] = len(events)
        elif name == "medical":
            result["medical_90d_count"] = len(events)
        elif name == "weight":
            result["weight_count_pre"] = len(events)
            result["weight_last_kg_pre"] = (
                _number(events[-1][1].get("body_weight_kg")) if events else None
            )
        elif name == "trial":
            result["trial_count_pre"] = len(
                {item.get("event_id") or (day, item.get("event_number")) for day, item in events}
            )
            valid = [
                (day, item)
                for day, item in events
                if _valid_time(item.get("finish_time_ms"))
                and str(item.get("segment_quality") or "") == "usable"
            ]
            if valid:
                result["trial_last_valid_time_ms_pre"] = valid[-1][1].get("finish_time_ms")
    return result


def _feature_registry() -> list[dict[str, Any]]:
    h0_names = [
        "global_elo_pre",
        "distance_elo_pre",
        "ability_mean_pre",
        "distance_state_pre",
        "elo_uncertainty_pre",
        "ability_uncertainty_pre",
        "starts_pre",
        "normal_completed_pre",
        "wins_pre",
        "top3_pre",
        "normal_history_count",
        "days_since_previous_start",
        "days_since_previous_normal_finish",
        "distance_starts_pre",
        "distance_normal_completed_pre",
        "distance_wins_pre",
        "distance_top3_pre",
        "recent_finish_score_5_mean",
        "recent_top3_rate_5",
        "performance_variability_pre",
    ]
    h1_names = [
        "speed_time_per_100m_mean_pre",
        "speed_residual_mean_pre",
        "speed_residual_std_pre",
        "speed_observation_count_pre",
        "distance_speed_time_per_100m_mean_pre",
        "distance_speed_residual_mean_pre",
        "distance_speed_observation_count_pre",
        "normal_usable_count_pre",
        "usable_time_count",
        "distance_normal_usable_count_pre",
        "section_s1f_ms_mean_pre",
        "section_s1f210_ms_mean_pre",
        "section_g1f_ms_mean_pre",
        "section_g3f_ms_mean_pre",
    ]
    h2_names = [
        "training_28d_count",
        "training_28d_duration_seconds",
        "training_28d_canter_count",
        "training_28d_gallop_count",
        "training_28d_coverage_unknown",
        "training_28d_observed_any",
        "start_training_28d_count",
        "start_training_28d_coverage_unknown",
        "start_training_28d_observed_any",
        "medical_90d_count",
        "medical_90d_coverage_unknown",
        "medical_90d_observed_any",
        "trial_count_pre",
        "trial_last_valid_time_ms_pre",
        "trial_coverage_unknown",
        "trial_observed_any",
        "weight_last_kg_pre",
        "weight_count_pre",
        "weight_coverage_unknown",
        "weight_observed_any",
    ]
    registry: list[dict[str, Any]] = []
    for name in h0_names:
        if "days_since" in name:
            source_columns = ["event_date"]
            unit = "days"
        elif "uncertainty" in name or "variability" in name:
            source_columns = ["finish_position"]
            unit = "heuristic_index"
        elif "elo" in name or "ability" in name or "state" in name:
            source_columns = ["finish_position"]
            unit = "elo_points"
        else:
            source_columns = ["finish_position"]
            unit = "count_or_rate"
        registry.append(
            {
                "feature_name": name,
                "source_table": "history_results",
                "source_columns": source_columns,
                "unit": unit,
                "entity_key": "horse_id",
                "event_at": "event_date",
                "available_at": "assumed",
                "ingested_at": "snapshot",
                "availability": "assumed_day_before_plus_1d_lag",
                "availability_class": "assumed",
                "lag_policy": "event_date<=target_date-2d",
                "aggregation_window": "all_or_recent_5",
                "missing_policy": "prior_or_null",
                "dedup_key": "race_id,entry_id,horse_id",
                "quality_rule": "DQ/DNF excluded from normal ability",
                "arm": "H0_RESULT",
            }
        )
    for name in h1_names:
        is_residual = "residual" in name
        is_raw_time = "time_per_100m" in name and not is_residual
        aggregation_window = (
            "past_same_distance_and_era; horse_residual_pool_all_eras"
            if is_residual
            else "all_past_same_distance"
            if is_raw_time
            else "past_same_distance"
        )
        section_feature = name.startswith("section_")
        source_columns = (
            [name.removesuffix("_mean_pre")]
            if section_feature
            else ["finish_time_ms", "segment_quality", "distance_m", "event_date"]
        )
        unit = (
            "ms"
            if section_feature
            else "count"
            if "observation_count" in name or name.endswith("usable_count_pre")
            else "ms_per_100m_or_residual"
        )
        aggregation_window = "last_10_same_distance" if section_feature else aggregation_window
        registry.append(
            {
                "feature_name": name,
                "source_table": "history_results",
                "source_columns": source_columns,
                "unit": unit,
                "entity_key": "horse_id",
                "event_at": "event_date",
                "available_at": "assumed",
                "ingested_at": "snapshot",
                "availability": "assumed_day_before_plus_1d_lag",
                "availability_class": "assumed",
                "lag_policy": "event_date<=target_date-2d",
                "aggregation_window": aggregation_window,
                "missing_policy": "null_with_count; sparse_baseline_no_fit",
                "dedup_key": "race_id,entry_id,horse_id",
                "quality_rule": "usable positive time only; normal finish only",
                "arm": "H1_TIME_SECTION",
            }
        )
    for name, unit in (
        ("distance_m", "m"),
        ("field_size", "horses"),
        ("regime", "era_label"),
    ):
        registry.append(
            {
                "feature_name": name,
                "source_table": "derived_target_condition",
                "source_columns": ["event_date"] if name == "regime" else [name],
                "unit": unit,
                "entity_key": "race_id",
                "event_at": "event_date",
                "available_at": "assumed_entry_snapshot",
                "ingested_at": "snapshot",
                "availability": "assumed_day_before_plus_1d_lag",
                "availability_class": "assumed",
                "lag_policy": "target_entry_snapshot",
                "aggregation_window": "current_race",
                "missing_policy": "required_input",
                "dedup_key": "race_id,entry_id",
                "quality_rule": "common target condition; no result columns",
                "arm": "H0_COMMON_CONDITION",
            }
        )
    for name in h2_names:
        table = (
            "daily_training_record/start_training_record/medical_record/"
            "entry + event/measured_weight_record"
        )
        registry.append(
            {
                "feature_name": name,
                "source_table": table,
                "source_columns": ["hr_no", "event_date"],
                "unit": "count/seconds/ms/kg/flag",
                "entity_key": "hr_no",
                "event_at": "event_date",
                "available_at": "assumed",
                "ingested_at": "snapshot",
                "availability": "ASSUMED_AVAILABILITY",
                "availability_class": "assumed",
                "lag_policy": "event_date<=target_date-2d",
                "aggregation_window": "28d/90d/past",
                "missing_policy": "count_zero_plus_coverage_unknown",
                "dedup_key": "source_row_or_event",
                "quality_rule": "API/native source only; text not added",
                "arm": "H2_STATE_ASSUMED_AVAILABILITY",
            }
        )
    return registry


def build_states(
    db_path: Path,
    entries: pl.DataFrame,
    history_results: pl.DataFrame,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Build deterministic past-only state rows for target entries.

    Target 400m entries are excluded by contract.  Historical 400m rows are
    retained in their own distance state and never update the global Elo or
    speed state.  The returned frame contains no finish labels.
    """
    _required(entries, _ENTRY_KEYS, "entries")
    _required(
        history_results,
        _HISTORY_KEYS + ("finish_position", "finish_time_ms", "segment_quality"),
        "history_results",
    )
    if entries.height:
        duplicate_entries = _check_duplicate_keys(entries, _ENTRY_KEYS, "entries")
        if duplicate_entries:
            raise ValueError("duplicate target entry keys are not allowed")
    history_results, duplicate_history = _deduplicate_history(history_results)
    target_rows = []
    excluded_400 = 0
    for ordinal, row in enumerate(entries.to_dicts()):
        distance_m = int(row["distance_m"])
        if distance_m == SEPARATE_DISTANCE_M:
            excluded_400 += 1
            continue
        target_rows.append(
            {
                "_ordinal": ordinal,
                "entry_id": int(row["entry_id"]),
                "race_id": int(row["race_id"]),
                "horse_id": _horse_id(row["horse_id"]),
                "event_date": _to_date(row["event_date"]),
                "cutoff_at": row.get("cutoff_at"),
                "distance_m": distance_m,
                "field_size": int(row.get("field_size") or 0),
            }
        )
    source_rows, source_meta = _source_rows(Path(db_path))
    source_index = _index_source_rows(source_rows)
    history_rows = _frame_rows(history_results)
    grouped: dict[tuple[date, int], list[_EventRow]] = defaultdict(list)
    for row in history_rows:
        grouped[(row.event_date, row.race_id)].append(row)
    history_events = sorted(grouped.items(), key=lambda item: item[0])
    target_sorted = sorted(
        target_rows,
        key=lambda row: (row["event_date"] or date.max, row["race_id"], row["entry_id"]),
    )
    states: dict[str, _HorseState] = {}
    global_times: dict[tuple[int, str], list[float]] = defaultdict(list)
    output: list[dict[str, Any]] = []
    event_index = 0
    for target in target_sorted:
        target_date = target["event_date"] or date.max
        eligible_date = target_date - timedelta(days=HISTORY_LAG_DAYS)
        while (
            event_index < len(history_events) and history_events[event_index][0][0] <= eligible_date
        ):
            event_day = history_events[event_index][0][0]
            day_events: list[list[_EventRow]] = []
            while (
                event_index < len(history_events) and history_events[event_index][0][0] == event_day
            ):
                _, rows = history_events[event_index]
                day_events.append(rows)
                event_index += 1
            # A date-only result has no within-day publication order.  Freeze
            # the distance baseline at the beginning of the day so the first
            # race cannot alter another race's pre-state normalization.
            day_baselines = {
                distance: (median(values) if values else None)
                for distance, values in global_times.items()
            }
            for rows in day_events:
                for row in rows:
                    states.setdefault(row.horse_id, _HorseState())
                _update_event(rows, states, global_times, day_baselines)
        state = states.setdefault(target["horse_id"], _HorseState())
        values = _state_snapshot(state, target["horse_id"], target_date, target["distance_m"])
        values.update(_h2_features(target["horse_id"], target_date, source_index))
        values.update(target)
        values["history_policy"] = "past_only_event_date_le_target_minus_2d"
        values["availability_class"] = "assumed_day_before_plus_1d_lag"
        values["source_quality"] = "heuristic_state"
        values["regime"] = _era_regime(target_date)
        output.append(values)
    output.sort(key=lambda row: row["_ordinal"])
    for row in output:
        row.pop("_ordinal", None)
    if output:
        states_frame = pl.DataFrame(output, infer_schema_length=None)
        section_columns = (
            "section_s1f_ms_mean_pre",
            "section_s1f210_ms_mean_pre",
            "section_g1f_ms_mean_pre",
            "section_g3f_ms_mean_pre",
        )
        for column in section_columns:
            if column not in states_frame.columns:
                states_frame = states_frame.with_columns(
                    pl.lit(None, dtype=pl.Float64).alias(column)
                )
        # Keep the target schema stable while allowing a caller to pass a
        # datetime cutoff.  Polars infers null-only columns as Null otherwise.
        for column in (
            "cutoff_at",
            "days_since_previous_start",
            "days_since_previous_normal_finish",
            "trial_last_valid_time_ms_pre",
            "weight_last_kg_pre",
        ):
            if column in states_frame.columns and states_frame[column].dtype == pl.Null:
                states_frame = states_frame.with_columns(
                    pl.lit(None, dtype=pl.Float64).alias(column)
                )
    else:
        empty_columns = {
            "entry_id",
            "race_id",
            "horse_id",
            "event_date",
            "cutoff_at",
            "distance_m",
            "field_size",
            "history_policy",
            "availability_class",
            "source_quality",
            "regime",
            "section_s1f_ms_mean_pre",
            "section_s1f210_ms_mean_pre",
            "section_g1f_ms_mean_pre",
            "section_g3f_ms_mean_pre",
            *_new_history_values().keys(),
            "training_28d_count",
            "training_28d_duration_seconds",
            "training_28d_canter_count",
            "training_28d_gallop_count",
            "training_28d_coverage_unknown",
            "start_training_28d_count",
            "training_28d_observed_any",
            "start_training_28d_coverage_unknown",
            "start_training_28d_observed_any",
            "medical_90d_count",
            "medical_90d_coverage_unknown",
            "medical_90d_observed_any",
            "trial_count_pre",
            "trial_last_valid_time_ms_pre",
            "trial_coverage_unknown",
            "trial_observed_any",
            "weight_last_kg_pre",
            "weight_count_pre",
            "weight_coverage_unknown",
            "weight_observed_any",
        }
        states_frame = pl.DataFrame({column: [] for column in sorted(empty_columns)})
    metadata = {
        "state_version": STATE_VERSION,
        "history_policy": "past_only_event_date_le_target_minus_2d",
        "cutoff_policy": "target_event_date_minus_2_days_for_date_only_sources",
        "target_rows_input": entries.height,
        "target_rows_output": states_frame.height,
        "target_400m_excluded": excluded_400,
        "history_rows_input": history_results.height + duplicate_history,
        "history_rows_deduplicated": history_results.height,
        "history_duplicate_rows_collapsed": duplicate_history,
        "history_400m_retained_separate": any(
            row.distance_m == SEPARATE_DISTANCE_M for row in history_rows
        ),
        "h2": source_meta,
        "speed_baseline_policy": "past_same_distance_and_era_median; sparse_cells_remain_null",
        "speed_residual_policy": "horse_history_residuals_pool_across_past_eras",
        "day_variant_track_correction": "excluded_not_available_in_this_builder",
        "feature_registry": _feature_registry(),
        "labels_separate": True,
        "model_status": (
            "heuristic_state_summary_not_fitted_probability_or_performance_distribution"
        ),
    }
    return states_frame, metadata


__all__ = ["build_states", "STATE_VERSION"]
