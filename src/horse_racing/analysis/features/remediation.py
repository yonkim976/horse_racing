"""G++그룹. 기수 조교와 교정 주행심사 신호.

현재 출전 기수가 최근 실제 조교에 참여했는지와 직전 공식 출전 이후 실시된
교정 주행심사(`주행지정(재)`)를 연결한다. 모든 이벤트는 경주일보다 엄격히
이전이어야 하며, 교정 심사는 직전 공식 출전보다 뒤인 것만 사용한다.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from datetime import date, timedelta

import polars as pl

from horse_racing.analysis.features.base import FeatureSpec, SourceFrames

GROUP = "G++. 기수 조교·교정심사"

FEATURES = [
    FeatureSpec(
        "current_jockey_train_n_28d",
        GROUP,
        "이번 기수가 해당 말에 직접 참여한 최근 28일 조교 일수",
        "horse_training.rider_id + jockeys.kra_jockey_id",
        "28일",
        "없으면 0",
        "training_date < race_date; 당일 제외",
    ),
    FeatureSpec(
        "current_jockey_train_duration_28d",
        GROUP,
        "이번 기수가 참여한 최근 28일 조교 시간 합(초)",
        "horse_training.duration_seconds",
        "28일",
        "없으면 0",
        "training_date < race_date; 당일 제외",
    ),
    FeatureSpec(
        "current_jockey_train_gallop_28d",
        GROUP,
        "이번 기수가 참여한 최근 28일 습보 횟수 합",
        "horse_training.gallop_count",
        "28일",
        "없으면 0",
        "training_date < race_date; 당일 제외",
    ),
    FeatureSpec(
        "current_jockey_train_2plus_28d",
        GROUP,
        "이번 기수의 최근 28일 직접 조교가 2일 이상이면 1",
        "current_jockey_train_n_28d",
        "28일",
        "없으면 0",
        "strict prior 집계의 파생값",
    ),
    FeatureSpec(
        "jockey_changed_from_last_start",
        GROUP,
        "직전 공식 출전 기수와 이번 기수가 다르면 1",
        "race_entries.jockey_id",
        "직전 공식 출전",
        "직전 출전 또는 기수 미상이면 null",
        "race_date보다 엄격히 이전인 공식 결과만 사용",
    ),
    FeatureSpec(
        "remedial_trial_passed_since_start",
        GROUP,
        "직전 출전 뒤 주행지정(재) 심사 합격이 있으면 1",
        "running_trial_results",
        "직전 출전 이후",
        "없으면 0",
        "last_start < trial_date < race_date",
    ),
    FeatureSpec(
        "remedial_trial_winner_since_start",
        GROUP,
        "최근 교정 심사에 합격하면서 1착이면 1",
        "running_trial_results.finish_position",
        "직전 출전 이후 최근 합격 심사",
        "없으면 0",
        "last_start < trial_date < race_date",
    ),
    FeatureSpec(
        "remedial_trial_current_jockey",
        GROUP,
        "최근 교정 심사를 이번 출전 기수가 탔으면 1",
        "running_trial_results.jockey_id",
        "직전 출전 이후 최근 합격 심사",
        "없거나 기수 미상이면 0",
        "last_start < trial_date < race_date",
    ),
    FeatureSpec(
        "remedial_trial_current_jockey_winner",
        GROUP,
        "이번 기수가 탄 최근 교정 심사에서 합격·1착이면 1",
        "running_trial_results",
        "직전 출전 이후 최근 합격 심사",
        "없으면 0",
        "strict prior 교정 심사 파생값",
    ),
    FeatureSpec(
        "remedial_trial_new_jockey_winner",
        GROUP,
        "직전과 다른 이번 기수가 교정 심사 합격·1착을 만들었으면 1",
        "running_trial_results + race_entries",
        "직전 출전 이후 최근 합격 심사",
        "없으면 0",
        "strict prior 공식 결과와 교정 심사만 사용",
    ),
    FeatureSpec(
        "remedial_trial_finish_percentile",
        GROUP,
        "최근 교정 합격 심사의 순위/참가두수(낮을수록 우수)",
        "running_trial_results",
        "직전 출전 이후 최근 합격 심사",
        "없으면 null",
        "last_start < trial_date < race_date",
    ),
    FeatureSpec(
        "bit_changed_from_last_start",
        GROUP,
        "직전 공식 출전 대비 재갈 종류가 바뀌면 1",
        "entry_equipment.equipment_raw",
        "직전 공식 출전",
        "양쪽 장구 정보가 없으면 null",
        "현재 출전표 장구와 strict prior 출전 장구만 비교",
    ),
    FeatureSpec(
        "remedial_trial_bit_changed",
        GROUP,
        "교정 심사 합격과 직전 출전 대비 재갈 변경이 함께 있으면 1",
        "running_trial_results + entry_equipment",
        "직전 공식 출전 이후",
        "판단 불가면 0",
        "두 point-in-time 신호의 상호작용",
    ),
]

FEATURE_NAMES = frozenset(spec.name for spec in FEATURES)
_BIT_SPLIT = re.compile(r"[,/+|;·]+")


def _day(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _bit(value: object) -> str | None:
    if value is None:
        return None
    parts = [part.strip() for part in _BIT_SPLIT.split(str(value))]
    bits = sorted(part for part in parts if "재갈" in part)
    return "+".join(bits) if bits else None


def _training_index(events: pl.DataFrame) -> dict[tuple[int, int], list[tuple[date, float, float]]]:
    histories: dict[tuple[int, int], list[tuple[date, float, float]]] = {}
    required = {"horse_id", "rider_jockey_id", "event_date"}
    if events.height == 0 or not required.issubset(events.columns):
        return histories
    for row in events.iter_rows(named=True):
        event_day = _day(row["event_date"])
        horse_id = row["horse_id"]
        jockey_id = row["rider_jockey_id"]
        if event_day is None or horse_id is None or jockey_id is None:
            continue
        histories.setdefault((int(horse_id), int(jockey_id)), []).append(
            (
                event_day,
                float(row.get("duration_seconds") or 0),
                float(row.get("gallop_count") or 0),
            )
        )
    for rows in histories.values():
        rows.sort(key=lambda item: item[0])
    return histories


def _past_index(results: pl.DataFrame) -> dict[int, list[tuple[date, int | None, int | None]]]:
    histories: dict[int, list[tuple[date, int | None, int | None]]] = {}
    required = {"horse_id", "race_date", "jockey_id", "race_number"}
    if results.height == 0 or not required.issubset(results.columns):
        return histories
    for row in results.iter_rows(named=True):
        event_day = _day(row["race_date"])
        if event_day is None or row["horse_id"] is None:
            continue
        histories.setdefault(int(row["horse_id"]), []).append(
            (event_day, row["jockey_id"], row["race_number"])
        )
    for rows in histories.values():
        rows.sort(key=lambda item: (item[0], item[2] or 0))
    return histories


def _trial_index(events: pl.DataFrame) -> dict[int, list[dict[str, object]]]:
    histories: dict[int, list[dict[str, object]]] = {}
    if events.height == 0 or not {"horse_id", "event_date"}.issubset(events.columns):
        return histories
    for row in events.iter_rows(named=True):
        event_day = _day(row["event_date"])
        reason = str(row.get("inspection_reason") or "")
        if (
            event_day is None
            or row["horse_id"] is None
            or "주행지정(재)" not in reason
            or row.get("judgement") != "합"
        ):
            continue
        item = dict(row)
        item["event_date"] = event_day
        histories.setdefault(int(row["horse_id"]), []).append(item)
    for rows in histories.values():
        rows.sort(
            key=lambda item: (
                item["event_date"],
                int(item.get("trial_race_number") or 0),
                int(item.get("trial_id") or 0),
            )
        )
    return histories


def _equipment_index(events: pl.DataFrame) -> dict[tuple[int, date, int], str | None]:
    index: dict[tuple[int, date, int], str | None] = {}
    required = {"horse_id", "race_date", "race_number", "equipment_raw"}
    if events.height == 0 or not required.issubset(events.columns):
        return index
    for row in events.iter_rows(named=True):
        event_day = _day(row["race_date"])
        if event_day is None or row["horse_id"] is None or row["race_number"] is None:
            continue
        index[(int(row["horse_id"]), event_day, int(row["race_number"]))] = _bit(
            row["equipment_raw"]
        )
    return index


def add_features(frame: pl.DataFrame, sources: SourceFrames) -> pl.DataFrame:
    training = _training_index(sources.training)
    past = _past_index(sources.past_results)
    trials = _trial_index(sources.running_trials)
    equipment = _equipment_index(sources.equipment)

    values: dict[str, list[object]] = {name: [] for name in FEATURE_NAMES}
    for row in frame.iter_rows(named=True):
        horse_id = int(row["horse_id"])
        race_day = _day(row["race_date"])
        jockey_id = row.get("jockey_id")
        race_number = row.get("race_number")

        train_rows = []
        if race_day is not None and jockey_id is not None:
            history = training.get((horse_id, int(jockey_id)), [])
            days = [item[0] for item in history]
            lo = bisect_left(days, race_day - timedelta(days=28))
            hi = bisect_left(days, race_day)
            train_rows = history[lo:hi]
        train_n = len(train_rows)
        values["current_jockey_train_n_28d"].append(train_n)
        values["current_jockey_train_duration_28d"].append(sum(item[1] for item in train_rows))
        values["current_jockey_train_gallop_28d"].append(sum(item[2] for item in train_rows))
        values["current_jockey_train_2plus_28d"].append(int(train_n >= 2))

        previous = None
        if race_day is not None:
            history = past.get(horse_id, [])
            past_days = [item[0] for item in history]
            pos = bisect_left(past_days, race_day) - 1
            if pos >= 0:
                previous = history[pos]
        changed = None
        if previous is not None and previous[1] is not None and jockey_id is not None:
            changed = int(int(previous[1]) != int(jockey_id))
        values["jockey_changed_from_last_start"].append(changed)

        remedial = None
        if previous is not None and race_day is not None:
            history = trials.get(horse_id, [])
            trial_days = [item["event_date"] for item in history]
            lo = bisect_right(trial_days, previous[0])
            hi = bisect_left(trial_days, race_day)
            if lo < hi:
                remedial = history[hi - 1]
        passed = int(remedial is not None)
        winner = int(remedial is not None and remedial.get("finish_position") == 1)
        current_jockey = int(
            remedial is not None
            and jockey_id is not None
            and remedial.get("jockey_id") is not None
            and int(remedial["jockey_id"]) == int(jockey_id)
        )
        current_winner = winner * current_jockey
        new_winner = int(current_winner == 1 and changed == 1)
        finish_pct = None
        if (
            remedial is not None
            and remedial.get("finish_position") is not None
            and remedial.get("field_size")
        ):
            finish_pct = float(remedial["finish_position"]) / float(remedial["field_size"])
        values["remedial_trial_passed_since_start"].append(passed)
        values["remedial_trial_winner_since_start"].append(winner)
        values["remedial_trial_current_jockey"].append(current_jockey)
        values["remedial_trial_current_jockey_winner"].append(current_winner)
        values["remedial_trial_new_jockey_winner"].append(new_winner)
        values["remedial_trial_finish_percentile"].append(finish_pct)

        bit_changed = None
        if previous is not None and race_day is not None and race_number is not None:
            prior_bit = equipment.get((horse_id, previous[0], int(previous[2] or 0)))
            current_bit = equipment.get((horse_id, race_day, int(race_number)))
            if prior_bit is not None or current_bit is not None:
                bit_changed = int(prior_bit != current_bit)
        values["bit_changed_from_last_start"].append(bit_changed)
        values["remedial_trial_bit_changed"].append(int(passed == 1 and bit_changed == 1))

    integer_features = FEATURE_NAMES - {
        "current_jockey_train_duration_28d",
        "current_jockey_train_gallop_28d",
        "remedial_trial_finish_percentile",
    }
    expressions = []
    for name in FEATURE_NAMES:
        dtype = pl.Int64 if name in integer_features else pl.Float64
        expressions.append(pl.Series(name, values[name], dtype=dtype))
    return frame.with_columns(expressions)
