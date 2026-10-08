from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from horse_racing.db.base import Base
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import (
    Horse,
    HorseProfileSnapshot,
    Owner,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    Trainer,
)
from horse_racing.web import entities
from horse_racing.web.entities import load_entity_list
from horse_racing.web.horse_directory import load_horse_directory_summary


@pytest.fixture
def directory_session():
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        profiles = [
            (1, "국6", "한국", True),
            (1, "외4", "미국", True),
            (1, "외4등급", "USA", True),
            (1, "국미검", "한국", True),
            (1, "외미검", "호주", True),
            (1, "국6", "한국", False),
            (1, "국6", "한국", None),
            (1, None, None, True),
            (2, "제6", "한국", True),
            (2, "미", "한국", True),
            (3, "국5", "한국", True),
            (None, "국미", None, True),
        ]
        for index, (meet, grade, origin, active) in enumerate(profiles):
            session.add(Horse(
                kra_horse_id=str(index), name_ko=f"말{index}", meet_code=meet,
                grade=grade, origin_country=origin, is_active=active,
                active_status_observed_at_ms=1 if active is not None else None,
                active_status_source="test" if active is not None else None,
            ))
        session.commit()
        yield session
    engine.dispose()


def test_summary_counts_profiles_once_and_keeps_retired_separate(directory_session):
    statements = []

    def record(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    engine = directory_session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        summary = load_horse_directory_summary(directory_session, None, "starts")
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(statements) == 1
    assert summary["columns"] == ["서울", "부산", "제주", "기타·미분류", "계"]
    assert [cell["count"] for cell in summary["totals"]] == [6, 1, 2, 1, 10]
    assert sum(row["cells"][-1]["count"] for row in summary["rows"]) == 10


def test_regional_counts_and_links_match_filtered_lists(directory_session):
    summary = load_horse_directory_summary(directory_session, 1, "name")
    assert summary["columns"] == ["국산마", "외산마", "산지 미확인", "계"]
    rows = {row["label"]: row["cells"] for row in summary["rows"]}
    assert [cell["count"] for cell in rows["4등급"]] == [0, 2, 0, 2]
    assert [cell["count"] for cell in rows["미검마"]] == [1, 1, 0, 2]
    assert [cell["count"] for cell in rows["등급 미확인"]] == [0, 0, 1, 1]
    for row in summary["rows"]:
        for cell in row["cells"]:
            assert urlsplit(cell["href"]).path == "/horses/list"
            assert not urlsplit(cell["href"]).fragment
            query = {key: values[0] for key, values in
                     parse_qs(urlsplit(cell["href"]).query).items()}
            query["meet"] = int(query["meet"])
            page = load_entity_list(directory_session, kind_slug="horses", **query)
            assert page.total_count == cell["count"]
            assert all(item.status_key == "active" for item in page.items)
    retired = load_entity_list(directory_session, kind_slug="horses", meet=1, status="retired")
    assert [item.official_id for item in retired.items] == ["5"]


def test_jeju_uses_same_grade_rows_without_inventing_origin_or_stabling(directory_session):
    summary = load_horse_directory_summary(directory_session, 2, "starts")
    assert summary["is_jeju"]
    assert summary["columns"] == ["두수"]
    rows = {row["label"]: row["cells"][0]["count"] for row in summary["rows"]}
    assert rows["6등급"] == 1
    assert rows["미등급"] == 1
    assert summary["totals"][0]["count"] == 2


def test_rating_order_is_numeric_before_pagination_and_keeps_missing_last(
    directory_session, monkeypatch,
):
    monkeypatch.setattr(entities, "today_seoul", lambda: date(2026, 10, 8))
    session = directory_session
    horses = {horse.kra_horse_id: horse for horse in session.scalars(select(Horse))}
    course = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
    session.add(course)
    for index, (horse_id, rating) in enumerate([
        ("0", 150), ("0", 9), ("1", 95), ("2", 120), ("2", None), ("3", 0),
    ], 1):
        entry = RaceEntry(
            horse=horses[horse_id], horse_number=1, rating=rating,
            race=Race(racecourse=course, race_date_local=date(2026, 9, index),
                      race_number=1, distance_m=1200, status="completed"),
        )
        session.add(RaceResult(race_entry=entry, finish_position=5))
    session.commit()
    first = load_entity_list(session, kind_slug="horses", meet=1, status="active", page_size=1)
    second = load_entity_list(
        session, kind_slug="horses", meet=1, status="active", page_size=1, page=2,
    )
    assert first.sort == "rating"
    assert [(item.official_id, item.last_race_rating) for item in first.items] == [("1", "95")]
    assert [(item.official_id, item.last_race_rating) for item in second.items] == [("0", "9")]
    all_rows = load_entity_list(session, kind_slug="horses", meet=1, status="active")
    assert all(item.last_race_rating == "—" for item in all_rows.items[2:])


def test_recent_five_and_career_use_actual_starts_and_a_complete_official_source(
    directory_session, monkeypatch,
):
    monkeypatch.setattr(entities, "today_seoul", lambda: date(2026, 10, 8))
    session = directory_session
    horse = session.scalar(select(Horse).where(Horse.kra_horse_id == "0"))
    course = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
    session.add(course)
    finishes = [(1, False, False), (2, False, False), (3, False, False),
                (4, False, False), (1, False, True), (93, False, False), (91, True, False)]
    for day, (position, scratched, disqualified) in enumerate(finishes, 1):
        entry = RaceEntry(
            horse=horse, horse_number=1, rating=80, scratched=scratched,
            race=Race(racecourse=course, race_date_local=date(2026, 9, day),
                      race_number=1, distance_m=1200, status="completed"),
        )
        session.add(RaceResult(
            race_entry=entry, finish_position=position, disqualified=disqualified,
        ))
    session.commit()
    stats = entities._load_horse_list_history(session, [horse.id])[horse.id]
    assert stats.recent_five == "주행중지 · 실격 · 4 · 3 · 2"
    assert stats.career_record == "6전 1/1/1"
    assert stats.win_rate == "16.7%"
    assert stats.place_rate == "50.0%"
    assert [start.finish for start in stats.recent_starts] == ["주행중지", "실격", "4", "3", "2"]
    assert [start.race_id for start in stats.recent_starts] == list(session.scalars(
        select(Race.id).where(Race.race_date_local.between(date(2026, 9, 2), date(2026, 9, 6)))
        .order_by(Race.race_date_local.desc()),
    ))
    assert stats.recent_starts[0].title == "2026.09.06 · 서울 1R · 주행중지"

    session.add_all([
        HorseProfileSnapshot(horse=horse, observed_at_ms=1, race_count_total=8,
                             win_count_total=2, second_count_total=2, third_count_total=1),
        HorseProfileSnapshot(horse=horse, observed_at_ms=2, race_count_total=10,
                             win_count_total=3, second_count_total=2, third_count_total=1),
    ])
    session.commit()
    stats = entities._load_horse_list_history(session, [horse.id])[horse.id]
    assert stats.career_record == "10전 3/2/1"
    assert stats.win_rate == "30.0%"
    assert stats.place_rate == "60.0%"
    # A partial snapshot cannot supply the denominator for locally collected wins.
    session.add(HorseProfileSnapshot(horse=horse, observed_at_ms=3, race_count_total=20))
    session.commit()
    stats = entities._load_horse_list_history(session, [horse.id])[horse.id]
    assert stats.career_record == "6전 1/1/1"
    assert stats.place_rate == "50.0%"


def test_affiliations_prefer_latest_profile_then_last_actual_start(directory_session):
    session = directory_session
    horses = {horse.kra_horse_id: horse for horse in session.scalars(select(Horse))}
    course = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
    trainer = Trainer(kra_trainer_id="T1", name_ko="직전조교사")
    owner = Owner(kra_owner_id="O1", name_ko="직전마주")
    session.add_all([
        course, trainer, owner,
        Trainer(kra_trainer_id="T2", name_ko="현재조교사"),
        Trainer(kra_trainer_id="T3", name_ko="현재조교사"),
        Trainer(kra_trainer_id="T4", name_ko="신마조교사"),
        Owner(kra_owner_id="O2", name_ko="현재마주"),
    ])
    for day, status, trainer_name in [(1, "completed", trainer), (2, "scheduled", None)]:
        entry = RaceEntry(
            horse=horses["0"], horse_number=1, trainer=trainer_name,
            owner=owner if status == "completed" else None,
            race=Race(racecourse=course, race_date_local=date(2026, 9, day),
                      race_number=1, distance_m=1200, status=status),
        )
        if status == "completed":
            session.add(RaceResult(race_entry=entry, finish_position=1))
        else:
            session.add(entry)
    session.add_all([
        HorseProfileSnapshot(horse=horses["0"], observed_at_ms=1,
                             trainer_name="오래된조교사", owner_name="오래된마주"),
        HorseProfileSnapshot(horse=horses["0"], observed_at_ms=2,
                             trainer_kra_id="T2", trainer_name="현재조교사",
                             owner_kra_id="O2", owner_name="현재마주"),
        HorseProfileSnapshot(horse=horses["1"], observed_at_ms=2,
                             trainer_name="신마조교사", owner_name="신마마주"),
    ])
    session.commit()
    page = load_entity_list(session, kind_slug="horses", status="active", include_summary=False)
    items = {item.official_id: item for item in page.items}
    assert (items["0"].trainer_name, items["0"].owner_name) == ("현재조교사", "현재마주")
    assert (items["1"].trainer_name, items["1"].owner_name) == ("신마조교사", "신마마주")
    assert (items["2"].trainer_name, items["2"].owner_name) == ("—", "—")
    assert (items["0"].trainer_href, items["0"].owner_href) == ("/trainers/T2", "/owners/O2")
    assert items["1"].trainer_href == "/trainers/T4"
    assert parse_qs(urlsplit(items["1"].owner_href).query) == {"q": ["신마마주"]}
    assert items["2"].trainer_href is None
    assert items["2"].owner_href is None
    # Missing fields fall back independently; a scheduled card is never the last actual start.
    session.add(HorseProfileSnapshot(horse=horses["0"], observed_at_ms=3,
                                    trainer_name=" — ", owner_name="변경마주"))
    session.commit()
    stats = entities._load_horse_list_history(session, [horses["0"].id])[horses["0"].id]
    assert (stats.trainer_name, stats.owner_name) == ("직전조교사", "변경마주")
    assert stats.trainer_href == "/trainers/T1"
    assert parse_qs(urlsplit(stats.owner_href).query) == {"q": ["변경마주"]}
