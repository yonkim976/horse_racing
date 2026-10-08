from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from horse_racing.db.base import Base
from horse_racing.db.models import (
    EntryEquipment,
    Horse,
    HorseTraining,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
)
from horse_racing.web.dashboard import _entry_row
from horse_racing.web.entry_preview import EntryPreview, load_entry_previews, month_before


@pytest.mark.parametrize(("day", "expected"), [
    (date(2026, 10, 9), date(2026, 9, 9)),
    (date(2026, 3, 31), date(2026, 2, 28)),
    (date(2024, 3, 31), date(2024, 2, 29)),
    (date(2026, 1, 31), date(2025, 12, 31)),
])
def test_month_window_uses_calendar_month(day, expected):
    assert month_before(day) == expected


@pytest.mark.parametrize(("days", "expected"), [(20, "3주"), (22, "3주"), (76, "11주")])
def test_rest_weeks_rounds_to_whole_weeks(days, expected):
    from datetime import timedelta

    day = date(2026, 10, 9)
    race = Race(race_date_local=day, race_number=1, distance_m=900, status="scheduled")
    horse = Horse(kra_horse_id="rounding-test", name_ko="주기 확인")
    entry = RaceEntry(race=race, horse=horse, horse_number=1)
    preview = EntryPreview(previous_date=day - timedelta(days=days))
    assert _entry_row(entry, {}, preview).rest_weeks == expected


def test_preview_batches_history_equipment_and_monthly_training_without_future_data():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        course = Racecourse(kra_meet_code=2, code="JEJU", name_ko="제주")
        horses = [Horse(kra_horse_id=str(n), name_ko=f"말{n}") for n in range(1, 4)]
        race = Race(racecourse=course, race_date_local=date(2026, 10, 9),
                    race_number=1, distance_m=900, status="scheduled")
        current = [RaceEntry(race=race, horse=horse, horse_number=n,
                             carried_weight_kg=55 if n < 3 else None)
                   for n, horse in enumerate(horses, 1)]
        session.add(race)
        for horse, day, weight, position in [
            (horses[0], 2, 54, 1), (horses[0], 8, 60, 94),
            (horses[0], 10, 60, 1), (horses[1], 1, 55, 93),
        ]:
            prior = Race(racecourse=course, race_date_local=date(2026, 10, day),
                         race_number=1, distance_m=900, status="completed")
            entry = RaceEntry(race=prior, horse=horse, horse_number=1,
                              carried_weight_kg=weight)
            session.add(RaceResult(race_entry=entry, finish_position=position))
        session.flush()
        for day, start in [(date(2026, 9, 8), "0600"), (date(2026, 9, 9), "0600"),
                           (date(2026, 9, 9), "0700"), (date(2026, 10, 8), "0600"),
                           (date(2026, 10, 9), "0600"), (date(2026, 10, 10), "0600")]:
            session.add(HorseTraining(horse_id=horses[0].id, meet_code=2,
                                      training_date_local=day, started_at_raw=start,
                                      ended_at_raw="0800", observed_at_ms=1))
        for horse_id, number, equipment in [(horses[0].id, 1, "망사가면,재갈"),
                                             (None, 2, "")]:
            session.add(EntryEquipment(horse_id=horse_id, meet_code=2,
                                       race_date_local=race.race_date_local, race_number=1,
                                       horse_number=number, equipment_raw=equipment,
                                       observed_at_ms=1))
        session.flush()
        statements = []
        def listener(*args):
            statements.append(args[2])
        event.listen(engine, "before_cursor_execute", listener)
        previews = load_entry_previews(session, race)
        event.remove(engine, "before_cursor_execute", listener)
        assert len(statements) == 3
        first, second, third = (previews[horse.id] for horse in horses)
        assert first.previous_date == date(2026, 10, 2)
        assert first.weight_delta == 1
        assert first.training_count == 3  # Two sessions on one day count twice.
        assert first.equipment == "망사가면,재갈"
        assert second.weight_delta == 0
        assert second.previous_date == date(2026, 10, 1)  # A stopped runner did start.
        assert second.equipment == "없음"
        assert third.previous_date is None
        assert third.weight_delta is None
        assert third.equipment == "—"
        assert third.training_count is None  # No records does not prove zero training.
        first_row = _entry_row(current[0], {}, first)
        assert first_row.carried_weight == "55kg (+1)"
        assert first_row.rest_weeks == "1주"
        assert _entry_row(current[1], {}, second).carried_weight == "55kg (0)"
        assert _entry_row(current[2], {}, third).rest_weeks == "—"
        current[0].equipment_card_raw = "망사눈가면+,계란형큰고리재갈-"
        current[1].equipment_card_raw = ""
        current[2].equipment = "재갈"
        refreshed = load_entry_previews(session, race)
        assert refreshed[horses[0].id].equipment == "망사눈가면+,계란형큰고리재갈-"
        assert refreshed[horses[1].id].equipment == "없음"
        assert refreshed[horses[2].id].equipment == "재갈"
        race.status = "completed"
        assert load_entry_previews(session, race) == {}
    engine.dispose()
