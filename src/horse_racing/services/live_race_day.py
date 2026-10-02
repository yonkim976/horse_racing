"""Apply validated race-day observations to existing cards, without predictions/schema changes."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from horse_racing.db.models import (
    HorseWeightHistory,
    Jockey,
    JockeyChange,
    Race,
    RaceEntry,
    RaceResult,
    RaceScratch,
)
from horse_racing.parsers.horse_history import parse_meet_code
from horse_racing.parsers.race_day import parse_body_weight, parse_track_status
from horse_racing.services.race_day import _is_date_echo_time, _local_datetime_ms


class LiveSourceMismatch(ValueError):
    """Safe error type; callers must never log the original payload or exception text."""


def load_races(session: Session, day: date) -> list[Race]:
    return list(
        session.scalars(
            select(Race)
            .where(Race.race_date_local == day)
            .options(
                joinedload(Race.racecourse),
                joinedload(Race.entries).joinedload(RaceEntry.horse),
                joinedload(Race.entries).joinedload(RaceEntry.jockey),
                joinedload(Race.entries).joinedload(RaceEntry.result),
            )
            .order_by(Race.racecourse_id, Race.race_number)
        ).unique()
    )


def entry_index(races: list[Race]) -> dict:
    return {
        (race.racecourse.kra_meet_code, race.race_number, entry.horse.kra_horse_id): entry
        for race in races
        for entry in race.entries
    }


def validate_items(items: list, *, kind: str, day: date, meet: int, entries: dict) -> None:
    seen = set()
    for item in items:
        region = getattr(item, "meet_code", None)
        if region is None:
            region = parse_meet_code(item.meet_name)
        key = (meet, item.race_number, item.horse_id)
        entry = entries.get(key)
        if (
            item.race_date != day
            or region != meet
            or entry is None
            or (item.horse_number is not None and item.horse_number != entry.horse_number)
            or (hasattr(item, "distance_m") and item.distance_m != entry.race.distance_m)
        ):
            raise LiveSourceMismatch("date_venue_runner_mismatch")
        identity = key
        if kind == "jockeys":
            identity += (item.jockey_before_id, item.jockey_after_id)
        if identity in seen:
            raise LiveSourceMismatch("duplicate_source_runner")
        seen.add(identity)
        if kind == "weights" and item.body_weight_kg not in (None, 0):
            if not 100 <= item.body_weight_kg <= 800:
                raise LiveSourceMismatch("invalid_weight")


def _non_null(row, **values) -> None:
    for name, value in values.items():
        if value is not None:
            setattr(row, name, value)


def apply_items(
    session: Session, *, kind: str, items: list, entries: dict, observed_ms: int
) -> None:
    if kind == "weights":
        _weights(session, items, entries, observed_ms)
    elif kind == "jockeys":
        _jockeys(session, items, entries, observed_ms)
    elif kind == "scratches":
        _scratches(session, items, entries, observed_ms)
    elif kind in {"results", "details"}:
        _results(session, items, entries, detailed=kind == "details")
    else:
        raise ValueError("unknown_live_stage")
    session.flush()


def _weights(session, items, entries, observed_ms):
    if not items:
        return
    day, meet = items[0].race_date, items[0].meet_code
    existing = {
        (row.horse_id, row.race_number, row.horse_number): row
        for row in session.scalars(
            select(HorseWeightHistory).where(
                HorseWeightHistory.race_date_local == day,
                HorseWeightHistory.meet_code == meet,
            )
        )
    }
    for item in items:
        entry = entries[(meet, item.race_number, item.horse_id)]
        key = (entry.horse_id, item.race_number, entry.horse_number)
        row = existing.get(key)
        if item.body_weight_kg in (None, 0):
            # API25 returns 0 before publication. Only repair an invalid legacy zero.
            if entry.body_weight_kg == 0:
                entry.body_weight_kg = None
                entry.body_weight_change_kg = None
            if row is not None and row.body_weight_kg == 0:
                row.body_weight_kg = None
                row.body_weight_change_kg = None
            continue
        if row is None:
            row = HorseWeightHistory(
                horse_id=entry.horse_id,
                meet_code=meet,
                race_date_local=day,
                race_number=item.race_number,
                horse_number=entry.horse_number,
                observed_at_ms=observed_ms,
            )
            session.add(row)
            existing[key] = row
        _non_null(
            row,
            body_weight_kg=item.body_weight_kg,
            body_weight_change_kg=item.body_weight_change_kg,
        )
        row.observed_at_ms = observed_ms
        _non_null(
            entry,
            body_weight_kg=item.body_weight_kg,
            body_weight_change_kg=item.body_weight_change_kg,
        )


def _jockeys(session, items, entries, observed_ms):
    groups = defaultdict(list)
    for item in items:
        groups[(item.meet_code, item.race_number, item.horse_id)].append(item)
    if not items:
        return
    rows = list(
        session.scalars(
            select(JockeyChange).where(
                JockeyChange.race_date_local == items[0].race_date,
                JockeyChange.meet_code == items[0].meet_code,
            )
        )
    )
    known = {
        (r.race_number, r.horse_number, r.jockey_before_id, r.jockey_after_id): r for r in rows
    }
    ids = {i.jockey_after_id for i in items if i.jockey_after_id}
    jockeys = {
        j.kra_jockey_id: j
        for j in session.scalars(select(Jockey).where(Jockey.kra_jockey_id.in_(ids)))
    }
    for key, changes in groups.items():
        entry = entries[key]
        before_ids = {i.jockey_before_id for i in changes if i.jockey_before_id}
        terminal = [i for i in changes if i.jockey_after_id not in before_ids]
        if len(terminal) != 1 or not terminal[0].jockey_after_id:
            raise LiveSourceMismatch("ambiguous_jockey_change_chain")
        selected = terminal[0]
        # A branching/cyclic chain is not resolved by response order.
        if len({i.jockey_before_id for i in changes}) != len(changes):
            raise LiveSourceMismatch("branching_jockey_change_chain")
        cursor = selected
        connected = {id(cursor)}
        while True:
            previous = [i for i in changes if i.jockey_after_id == cursor.jockey_before_id]
            if not previous:
                break
            if len(previous) != 1 or id(previous[0]) in connected:
                raise LiveSourceMismatch("cyclic_jockey_change_chain")
            cursor = previous[0]
            connected.add(id(cursor))
        if len(connected) != len(changes):
            raise LiveSourceMismatch("disconnected_jockey_change_chain")
        for item in changes:
            identity = (
                item.race_number,
                item.horse_number,
                item.jockey_before_id,
                item.jockey_after_id,
            )
            row = known.get(identity)
            if row is None:
                row = JockeyChange(
                    horse_id=entry.horse_id,
                    meet_code=item.meet_code,
                    race_date_local=item.race_date,
                    race_number=item.race_number,
                    horse_number=item.horse_number,
                    jockey_before_id=item.jockey_before_id,
                    jockey_after_id=item.jockey_after_id,
                    observed_at_ms=observed_ms,
                )
                session.add(row)
                known[identity] = row
            row.horse_id = entry.horse_id
            _non_null(
                row,
                jockey_before_name=item.jockey_before_name,
                jockey_after_name=item.jockey_after_name,
                carried_weight_before_kg=item.carried_weight_before_kg,
                carried_weight_after_kg=item.carried_weight_after_kg,
                reason=item.reason,
            )
            row.observed_at_ms = observed_ms
        jockey = jockeys.get(selected.jockey_after_id)
        if jockey is None:
            if not selected.jockey_after_name:
                raise LiveSourceMismatch("new_jockey_without_name")
            jockey = Jockey(
                kra_jockey_id=selected.jockey_after_id, name_ko=selected.jockey_after_name
            )
            session.add(jockey)
            jockeys[selected.jockey_after_id] = jockey
        entry.jockey = jockey
        _non_null(entry, carried_weight_kg=selected.carried_weight_after_kg)


def _scratches(session, items, entries, observed_ms):
    if not items:
        return
    known = {
        (r.race_number, r.horse_id): r
        for r in session.scalars(
            select(RaceScratch).where(
                RaceScratch.race_date_local == items[0].race_date,
                RaceScratch.meet_code == items[0].meet_code,
            )
        )
    }
    for item in items:
        entry = entries[(item.meet_code, item.race_number, item.horse_id)]
        key = (item.race_number, entry.horse_id)
        row = known.get(key)
        if row is None:
            row = RaceScratch(
                horse_id=entry.horse_id,
                meet_code=item.meet_code,
                race_date_local=item.race_date,
                race_number=item.race_number,
                observed_at_ms=observed_ms,
            )
            session.add(row)
            known[key] = row
        row.horse_number = entry.horse_number
        _non_null(row, reason=item.reason)
        row.observed_at_ms = observed_ms
        entry.scratched = True  # An empty later response is not a cancellation reversal.


def _results(session, items, entries, *, detailed):
    for item in items:
        meet = parse_meet_code(item.meet_name)
        entry = entries[(meet, item.race_number, item.horse_id)]
        race = entry.race
        if detailed:
            _non_null(
                race, weather=item.weather, start_time_change_reason=item.start_time_change_reason
            )
            condition, moisture = parse_track_status(item.track_status)
            _non_null(race, track_condition=condition, track_moisture_percent=moisture)
            if not _is_date_echo_time(item.race_date, item.actual_start_time):
                _non_null(
                    race,
                    actual_start_at_ms=_local_datetime_ms(item.race_date, item.actual_start_time),
                )
        if item.finish_position is None:
            continue  # API155/156 also publish pre-race placeholders.
        result = entry.result
        if not detailed and result is not None and result.finish_position is not None:
            continue  # API155 fills gaps; API156 is authoritative for corrections.
        if result is None:
            result = RaceResult(race_entry=entry)
            session.add(result)
        _non_null(
            result,
            finish_position=item.finish_position,
            finish_time_ms=item.finish_time_ms,
            margin_text=item.margin_text,
        )
        if detailed:
            _non_null(
                result,
                prize_money_krw=item.prize_money_krw,
                bonus_prize_money_krw=item.bonus_prize_money_krw,
                rank_remark=item.rank_remark,
            )
        _non_null(entry, rating=item.rating)
        # API25 is preferred. Results may fill an absent weight, never erase/replace one.
        if entry.body_weight_kg is None:
            weight, change = parse_body_weight(item.body_weight_text)
            if weight is not None and 100 <= weight <= 800:
                _non_null(entry, body_weight_kg=weight, body_weight_change_kg=change)


def race_has_complete_results(race: Race) -> bool:
    starters = [entry for entry in race.entries if not entry.scratched]
    return (
        bool(starters)
        and (race.field_size is None or len(race.entries) >= race.field_size)
        and all(
            entry.result is not None and entry.result.finish_position is not None
            for entry in starters
        )
    )


def refresh_completion(races: list[Race]) -> None:
    for race in races:
        if race_has_complete_results(race):
            race.status = "completed"
        elif race.status == "completed":
            race.status = "scheduled"  # Repair premature legacy completion, not results.


def snapshot(races: list[Race]) -> dict:
    result = {}
    for race in races:
        for entry in race.entries:
            finish = entry.result
            result[entry.id] = {
                "meet": race.racecourse.kra_meet_code,
                "race": race.race_number,
                "number": entry.horse_number,
                "horse": entry.horse.name_ko,
                "weight": entry.body_weight_kg,
                "weight_delta": entry.body_weight_change_kg,
                "jockey": entry.jockey.kra_jockey_id if entry.jockey else None,
                "jockey_name": entry.jockey.name_ko if entry.jockey else None,
                "carried_weight": entry.carried_weight_kg,
                "scratched": entry.scratched,
                "finish": finish.finish_position if finish else None,
                "time_ms": finish.finish_time_ms if finish else None,
            }
    return result
