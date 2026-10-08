from datetime import date

from sqlalchemy.orm import Session

from horse_racing.db.base import Base
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import (
    Horse,
    Jockey,
    JockeyAffiliationSnapshot,
    Race,
    Racecourse,
    RaceEntry,
)
from horse_racing.web.entities import load_entity_list


def test_latest_base_affiliation_ignores_exchange_and_yeongcheon_races():
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        jockeys = [Jockey(kra_jockey_id=f"{i:06d}", name_ko=name) for i, name in enumerate(
            ["서울현역", "(-2)부산현역", "제주현역", "이전명단", "미연결"], 1,
        )]
        session.add_all(jockeys)
        session.flush()
        for index, meet in [(0, 1), (1, 3), (2, 2), (3, 1)]:
            session.add(JockeyAffiliationSnapshot(
                jockey_id=jockeys[index].id, meet_code=meet,
                observed_on=date(2026, 10, 7 if index == 3 else 8),
                official_name_ko=jockeys[index].name_ko.replace("(-2)", ""),
                observed_at_ms=1, source_url="https://race.kra.co.kr/",
                source_sha256="a" * 64, api_source_url="https://apis.data.go.kr/",
                api_sha256="b" * 64,
            ))
        horse = Horse(kra_horse_id="001", name_ko="테스트말")
        for meet in [1, 4]:
            course = Racecourse(kra_meet_code=meet, code=f"M{meet}", name_ko=f"경마장{meet}")
            race = Race(racecourse=course,
                        race_date_local=date(2026, 10, 8), race_number=1, distance_m=1200)
            session.add(RaceEntry(jockey=jockeys[1], horse=horse, horse_number=1, race=race))
        session.commit()
        all_rows = load_entity_list(session, kind_slug="jockeys")
        assert all_rows.total_count == 3
        assert all_rows.affiliation_observed_on == date(2026, 10, 8)
        busan = load_entity_list(session, kind_slug="jockeys", meet=3)
        assert [(item.name_ko, item.subtitle) for item in busan.items] == [("부산현역", "부산")]
        assert load_entity_list(session, kind_slug="jockeys", meet=1).total_count == 1
        assert load_entity_list(session, kind_slug="jockeys", meet=2).total_count == 1
        assert load_entity_list(session, kind_slug="jockeys", query="이전명단").total_count == 0
        assert load_entity_list(session, kind_slug="jockeys", query="미연결").total_count == 0
        searched = load_entity_list(session, kind_slug="jockeys", query="부산현역", meet=3)
        assert searched.total_count == 1
    engine.dispose()



def test_missing_roster_does_not_fall_back_to_historical_jockeys():
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Jockey(kra_jockey_id="000001", name_ko="과거기수"))
        session.commit()
        assert load_entity_list(session, kind_slug="jockeys").total_count == 0
    engine.dispose()



def test_jockey_records_period_boundaries_exclusions_and_rates(monkeypatch):
    from sqlalchemy import event

    from horse_racing.db.models import RaceResult
    from horse_racing.web import entities

    monkeypatch.setattr(entities, "today_seoul", lambda: date(2026, 10, 8))
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        jockey = Jockey(kra_jockey_id="080001", name_ko="테스트기수")
        no_starts = Jockey(kra_jockey_id="080002", name_ko="신규기수")
        horse = Horse(kra_horse_id="000001", name_ko="테스트말")
        course = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        session.add_all([jockey, no_starts, horse, course])
        session.flush()
        fixtures = [
            (date(2026, 10, 8), 1, False, False, "completed"),
            (date(2026, 9, 8), 2, False, False, "completed"),
            (date(2026, 9, 7), 3, False, False, "completed"),
            (date(2025, 10, 8), 4, False, False, "completed"),
            (date(2025, 10, 7), 1, False, False, "completed"),
            (date(2026, 10, 1), 1, True, False, "completed"),
            (date(2026, 10, 2), 93, False, False, "completed"),
            (date(2026, 10, 3), 1, False, False, "scheduled"),
            (date(2026, 10, 9), 1, False, False, "completed"),
            (date(2026, 10, 4), 1, False, True, "completed"),
            (date(2026, 10, 5), 91, False, False, "completed"),
            (date(2026, 10, 6), None, False, False, "completed"),
        ]
        for number, (day, position, disqualified, scratched, status) in enumerate(fixtures, 1):
            entry = RaceEntry(jockey=jockey, horse=horse, horse_number=1, scratched=scratched,
                              race=Race(racecourse=course, race_date_local=day,
                                        race_number=number, distance_m=1200, status=status))
            session.add(RaceResult(race_entry=entry, finish_position=position,
                                   disqualified=disqualified))
        session.commit()
        ids = [jockey.id, no_starts.id]
        queries = []

        def record(_connection, _cursor, sql, _params, _context, _many):
            queries.append(sql)

        event.listen(engine, "before_cursor_execute", record)
        try:
            stats = entities._load_jockey_directory_stats(session, ids)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert len(queries) == 1
        assert stats[jockey.id][:4] == (7, 2, 1, 1)
        assert stats[jockey.id].quinella_rate == "42.9%"
        month = entities._load_jockey_directory_stats(session, ids, "month")[jockey.id]
        year = entities._load_jockey_directory_stats(session, ids, "year")[jockey.id]
        assert month[:4] == (4, 1, 1, 0)
        assert (month.win_rate, month.quinella_rate, month.place_rate) == (
            "25.0%", "50.0%", "50.0%",
        )
        assert year[:4] == (6, 1, 1, 1)
        assert (year.win_rate, year.quinella_rate, year.place_rate) == ("16.7%", "33.3%", "50.0%")
        assert stats[jockey.id].win_rate == "28.6%"
        assert stats[jockey.id].place_rate == "57.1%"
        assert stats[no_starts.id] == entities.JockeyDirectoryStats()
    engine.dispose()



def test_period_sorting_precedes_pagination_and_web_state_is_preserved(tmp_path, monkeypatch):
    from bs4 import BeautifulSoup
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    from horse_racing.db.models import RaceResult
    from horse_racing.web import entities
    from horse_racing.web.app import create_app

    monkeypatch.setattr(entities, "today_seoul", lambda: date(2026, 10, 8))
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'periods.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        jockeys = [Jockey(kra_jockey_id=f"08000{i}", name_ko=f"기수{i}") for i in range(1, 5)]
        horse = Horse(kra_horse_id="000001", name_ko="말")
        course = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        session.add_all([*jockeys, horse, course])
        session.flush()
        for index, jockey in enumerate(jockeys):
            session.add(JockeyAffiliationSnapshot(
                jockey_id=jockey.id, observed_on=date(2026, 10, 8),
                meet_code=3 if index == 2 else 1, official_name_ko=jockey.name_ko,
                observed_at_ms=1, source_url="https://race.kra.co.kr/",
                source_sha256="a" * 64, api_source_url="https://apis.data.go.kr/",
                api_sha256="b" * 64,
            ))
        for number, (index, day, rank) in enumerate([
            (0, date(2020, 1, 1), 1), (0, date(2025, 11, 9), 2),
            (0, date(2026, 6, 1), 3), (1, date(2026, 10, 1), 2),
            (1, date(2026, 10, 2), 1), (2, date(2026, 10, 3), 3),
        ], 1):
            entry = RaceEntry(horse=horse, jockey=jockeys[index], horse_number=1,
                              race=Race(racecourse=course, race_date_local=day,
                                        race_number=number, distance_m=1200, status="completed"))
            session.add(RaceResult(race_entry=entry, finish_position=rank))
        session.commit()
        career = load_entity_list(session, kind_slug="jockeys")
        month = load_entity_list(session, kind_slug="jockeys", period="month")
        year = load_entity_list(session, kind_slug="jockeys", period="year")
        assert [item.name_ko for item in career.items] == ["기수1", "기수2", "기수3", "기수4"]
        assert [item.name_ko for item in month.items] == ["기수2", "기수3", "기수1", "기수4"]
        assert [item.jockey_stats.starts for item in year.items] == [2, 2, 1, 0]
        second = load_entity_list(session, kind_slug="jockeys", period="month", page_size=1, page=2)
        assert second.items[0].name_ko == "기수3"
        assert second.items[0].jockey_stats.place_rate == "100.0%"
        seoul = load_entity_list(session, kind_slug="jockeys", period="month", meet=1)
        assert [item.name_ko for item in seoul.items] == ["기수2", "기수1", "기수4"]
        assert load_entity_list(session, kind_slug="jockeys", period="invalid").period == "career"
        named = load_entity_list(session, kind_slug="jockeys", period="month", sort="name")
        assert [item.name_ko for item in named.items] == ["기수1", "기수2", "기수3", "기수4"]

    with TestClient(create_app(session_factory=factory)) as client:
        default = BeautifulSoup(client.get("/jockeys").text, "html.parser")
        assert default.select_one('.jockey-period-tabs [aria-current="page"]').text == "통산"
        month_page = BeautifulSoup(client.get("/jockeys?period=month").text, "html.parser")
        first_row = month_page.select_one(".jockey-list-table tbody tr").find_all("td")
        assert first_row[1].text.strip() == "기수2"
        response = client.get("/jockeys?period=month&meet=1&q=기수2&sort=name&page=2")
        assert response.status_code == 200
        soup = BeautifulSoup(response.text, "html.parser")
        assert [th.text.strip() for th in soup.select(".jockey-list-table th")] == [
            "번호", "이름", "지역", "출전", "1위", "2위", "3위", "승률", "복승률", "입상률",
        ]
        assert [td.text.strip() for td in soup.select(".jockey-list-table tbody td")][2:] == [
            "서울", "2", "1", "1", "0", "50.0%", "100.0%", "100.0%",
        ]
        assert soup.select_one('input[name="period"]')["value"] == "month"
        for link in soup.select(".jockey-period-tabs a"):
            assert "meet=1" in link["href"] and "sort=name" in link["href"]
            assert "page=" not in link["href"] and "q=" in link["href"]
        for link in soup.select(".entity-region-tabs a"):
            assert "period=month" in link["href"]
    engine.dispose()
