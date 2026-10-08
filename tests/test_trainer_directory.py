from datetime import date

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from horse_racing.db.base import Base
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import (
    Horse,
    HorseProfileSnapshot,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    Trainer,
    TrainerAffiliationSnapshot,
    TrainerHistoricalRegion,
    TrainerIdentityResolution,
)
from horse_racing.web import entities


@pytest.fixture
def trainer_session(monkeypatch):
    monkeypatch.setattr(entities, "today_seoul", lambda: date(2026, 10, 8))
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        trainers = [Trainer(kra_trainer_id=f"T{i}", name_ko=name) for i, name in enumerate(
            ["서울현역", "부산현역", "은퇴조교사", "미연결", "확정별칭", "후보별칭"],
        )]
        session.add_all(trainers)
        session.flush()
        for trainer, day, meet, part in [(trainers[0], 7, 1, 53),
                                         (trainers[1], 7, 3, 1), (trainers[2], 6, 1, 5)]:
            session.add(TrainerAffiliationSnapshot(
                trainer=trainer, observed_on=date(2026, 10, day), meet_code=meet,
                stable_part=part, official_name_ko=trainer.name_ko, observed_at_ms=1,
                source_url="https://race.kra.co.kr/trainer/profileTrainerList.do",
                source_sha256="a" * 64,
            ))
        session.add(TrainerHistoricalRegion(
            trainer=trainers[2], region_code="SEOUL", observed_on=date(2026, 10, 7),
            source_end_date=date(2025, 1, 1), retired_list_confirmed=True,
            observed_at_ms=1, source_url="https://race.kra.co.kr/", source_sha256="a" * 64,
        ))
        for trainer, status in [(trainers[4], "confirmed"),
                                (trainers[5], "official_id_candidate")]:
            session.add(TrainerIdentityResolution(
                temporary_trainer_ref=trainer.kra_trainer_id, official_tr_no="T0",
                source_name_ko=trainer.name_ko, canonical_name_ko="서울현역",
                resolution_status=status, matched_race_rows=1, source_reference="test",
                reviewed_on=date(2026, 10, 7),
            ))
        session.commit()
        yield session, trainers
    engine.dispose()


def test_browse_is_active_only_but_search_includes_former_and_unclassified(trainer_session):
    session, _ = trainer_session
    browse = entities.load_entity_list(session, kind_slug="trainers")
    assert {item.name_ko for item in browse.items} == {"서울현역", "부산현역"}
    assert entities.load_entity_list(session, kind_slug="trainers", query="  ").total_count == 2
    seoul = entities.load_entity_list(session, kind_slug="trainers", meet=1)
    assert [item.name_ko for item in seoul.items] == ["서울현역"]
    assert seoul.items[0].trainer_stats.stable == "53조"
    former = entities.load_entity_list(session, kind_slug="trainers", query="은퇴", meet=1)
    assert [item.name_ko for item in former.items] == ["은퇴조교사"]
    assert former.items[0].trainer_stats.stable == "—"
    assert entities.load_entity_list(
        session, kind_slug="trainers", query="은퇴", meet=3,
    ).total_count == 0
    unknown = entities.load_entity_list(session, kind_slug="trainers", query="T3")
    assert [item.name_ko for item in unknown.items] == ["미연결"]


def test_stats_use_latest_active_horses_rolling_periods_and_confirmed_ids(trainer_session):
    session, trainers = trainer_session
    course = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
    horses = [Horse(kra_horse_id=f"H{i}", name_ko=f"말{i}", is_active=active,
                    active_status_observed_at_ms=1, active_status_source="test")
              for i, active in enumerate([True, True, False])]
    session.add_all([course, *horses])
    session.flush()
    for horse, old, current in [(horses[0], "T1", "T0"),
                                (horses[1], "T0", "T1"), (horses[2], "T1", "T0")]:
        for observed, ref in [(1, old), (2, current)]:
            session.add(HorseProfileSnapshot(horse=horse, observed_at_ms=observed,
                                            trainer_kra_id=ref))
    for index, (day, trainer_index, position, scratched) in enumerate([
        (date(2026, 10, 8), 0, 3, False), (date(2026, 9, 8), 0, 1, False),
        (date(2026, 9, 7), 0, 2, False), (date(2025, 10, 8), 0, 4, False),
        (date(2025, 10, 7), 0, 1, False), (date(2026, 9, 9), 4, 1, False),
        (date(2026, 10, 1), 5, 1, False), (date(2026, 10, 9), 0, 1, False),
        (date(2026, 10, 2), 0, 1, True), (date(2026, 10, 3), 0, 91, False),
    ], 1):
        entry = RaceEntry(
            trainer=trainers[trainer_index], horse=horses[0], horse_number=1,
            scratched=scratched,
            race=Race(racecourse=course, race_date_local=day, race_number=index,
                      distance_m=1200, status="completed"),
        )
        session.add(RaceResult(race_entry=entry, finish_position=position))
    session.commit()
    stats = entities._load_trainer_directory_stats(
        session, trainers, date(2026, 10, 7), None,
    )
    assert stats[trainers[0].id].stable == "서울 53조"
    assert stats[trainers[0].id].managed_count == 1
    assert stats[trainers[1].id].managed_count == 1
    assert stats[trainers[0].id].month_record == "3전 2/0/1"
    assert stats[trainers[0].id].year_record == "5전 2/1/1"
    assert stats[trainers[0].id].career_record == "6전 3/1/1"
    assert stats[trainers[0].id].performance == entities.DirectoryPerformanceStats(
        6, 3, 1, 1, "50.0%", "66.7%", "83.3%",
    )
    month = entities.load_entity_list(session, kind_slug="trainers", meet=1, period="month")
    assert month.period_start == date(2026, 9, 8)
    assert month.items[0].entry_count == 3
    assert month.items[0].trainer_stats.performance == entities.DirectoryPerformanceStats(
        3, 2, 0, 1, "66.7%", "66.7%", "100.0%",
    )
    year = entities.load_entity_list(session, kind_slug="trainers", meet=1, period="year")
    assert year.items[0].trainer_stats.performance.starts == 5
    assert stats[trainers[3].id].career_record == "0전 0/0/0"


def test_trainer_selected_period_sorting_before_pagination(trainer_session):
    session, trainers = trainer_session
    course = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
    horse = Horse(kra_horse_id="H1", name_ko="말")
    session.add_all([course, horse])
    for number, (trainer_index, day, status, disqualified) in enumerate([
        (0, date(2025, 1, 1), "completed", False),
        (0, date(2025, 1, 2), "completed", False),
        (0, date(2025, 1, 3), "completed", False),
        (1, date(2026, 10, 1), "completed", False),
        (1, date(2026, 10, 2), "completed", True),
        (0, date(2026, 10, 3), "scheduled", False),
        (0, date(2026, 10, 9), "completed", False),
    ], 1):
        entry = RaceEntry(trainer=trainers[trainer_index], horse=horse, horse_number=1,
                          race=Race(racecourse=course, race_date_local=day,
                                    race_number=number, distance_m=1200, status=status))
        session.add(RaceResult(race_entry=entry, finish_position=1, disqualified=disqualified))
    session.commit()
    career = entities.load_entity_list(session, kind_slug="trainers", page_size=1)
    assert career.items[0].name_ko == "서울현역"
    for period in ("month", "year"):
        page = entities.load_entity_list(session, kind_slug="trainers", period=period, page_size=1)
        assert page.items[0].name_ko == "부산현역"
        assert page.items[0].trainer_stats.performance == entities.DirectoryPerformanceStats(
            2, 1, 0, 0, "50.0%", "50.0%", "50.0%",
        )
        page2 = entities.load_entity_list(session, kind_slug="trainers", period=period,
                                          page_size=1, page=2)
        assert page2.items[0].name_ko == "서울현역"
        assert page2.items[0].trainer_stats.performance.win_rate == "—"


def test_performance_controls_are_in_heading_for_all_three_lists(tmp_path):
    from bs4 import BeautifulSoup
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    from horse_racing.web.app import create_app

    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'directory.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        trainer = Trainer(kra_trainer_id="070001", name_ko="현역조교사")
        session.add(TrainerAffiliationSnapshot(
            trainer=trainer, observed_on=date(2026, 10, 7), meet_code=1, stable_part=1,
            official_name_ko=trainer.name_ko, observed_at_ms=1,
            source_url="https://race.kra.co.kr/", source_sha256="a" * 64,
        ))
        session.commit()
    with TestClient(create_app(session_factory=factory)) as client:
        for kind in ("trainers", "jockeys", "owners"):
            for period, label in entities.PERFORMANCE_PERIOD_LABELS.items():
                response = client.get(f"/{kind}?meet=1&period={period}&q=현역&sort=name")
                assert response.status_code == 200
                soup = BeautifulSoup(response.text, "html.parser")
                heading = soup.select_one("#horse-directory-list > .panel-heading")
                tabs = heading.select_one(".jockey-period-tabs")
                assert tabs.select_one('[aria-current="page"]').text == label
                assert heading.select_one(".jockey-period-range")
                for link in tabs.select("a"):
                    assert "meet=1" in link["href"] and "sort=name" in link["href"]
                    assert "q=" in link["href"] and "page=" not in link["href"]
                if kind == "trainers":
                    headers = [th.text.strip() for th in soup.select("table thead th")]
                    assert headers == [
                        "번호", "이름", "조", "관리두수", "출전", "1위", "2위", "3위",
                        "승률", "복승률", "입상률",
                    ]
                    assert soup.select_one('input[name="period"]')["value"] == period
                    assert all(f"period={period}" in a["href"]
                               for a in soup.select(".entity-region-tabs a"))
    engine.dispose()


def test_stats_batch_queries_do_not_grow_per_trainer(trainer_session):
    session, trainers = trainer_session
    statements = []

    def record(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        entities._load_trainer_directory_stats(session, trainers, date(2026, 10, 7), None)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(statements) == 3
