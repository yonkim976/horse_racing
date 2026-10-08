from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from horse_racing.db.base import Base
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import (
    Horse,
    IngestionRun,
    Owner,
    OwnerCatalogSnapshot,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    SourceDocument,
)
from horse_racing.web.app import create_app
from horse_racing.web.entities import load_entity_list


def add_catalog(session, owners, totals, started, status="completed"):
    run = IngestionRun(source="test", data_type="owner_catalog_full",
                       started_at_ms=started, status=status)
    session.add(run)
    session.flush()
    doc = SourceDocument(ingestion_run_id=run.id, source_url="https://apis.data.go.kr/",
                         requested_at_ms=started, retrieved_at_ms=started,
                         local_path="test.json", sha256="a" * 64)
    session.add(doc)
    session.flush()
    for item in totals:
        owner_no, meet, total = item[:3]
        current = item[3] if len(item) == 4 else total
        owner = owners[owner_no]
        session.add(OwnerCatalogSnapshot(
            ingestion_run_id=run.id, owner_id=owner.id, kra_owner_id=owner.kra_owner_id,
            official_name_ko=owner.name_ko, meet_code=meet,
            registration_date=date(2020, 1, 1), total_registered_horses=total,
            current_owned_horses=current,
            observed_at_ms=started, source_document_id=doc.id,
        ))
    session.flush()


def test_latest_complete_catalog_sort_pagination_and_missing_totals():
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        owners = [Owner(kra_owner_id=f"{n:06d}", name_ko=name) for n, name in enumerate(
            ["다수등록", "소수등록", "등록없음", "과거마주", "다지역마주"], 1,
        )]
        session.add_all(owners)
        session.flush()
        add_catalog(session, owners, [(3, 1, 999), (0, 1, 500)], 1)
        add_catalog(session, owners, [(0, 1, 131, 5), (1, 1, 23, 8), (2, 1, 0, 0),
                                      (4, 1, 10, 3), (4, 3, 20, 4)], 2)
        add_catalog(session, owners, [(0, 1, 9999)], 3, "partial")
        session.commit()
        page = load_entity_list(session, kind_slug="owners", meet=1, page_size=2)
        assert page.sort == "owned"
        assert page.total_count == 3
        assert [(item.name_ko, item.owner_current_count) for item in page.items] == [
            ("소수등록", 8), ("다수등록", 5),
        ]
        page2 = load_entity_list(session, kind_slug="owners", meet=1, page=2, page_size=2)
        assert [item.owner_current_count for item in page2.items] == [3]
        full = load_entity_list(session, kind_slug="owners", sort="registered")
        assert full.sort == "owned" and full.total_count == 3
        rows = full.items
        assert [item.owner_current_count for item in rows] == [8, 7, 5]
        historical = load_entity_list(session, kind_slug="owners", query="과거마주").items[0]
        assert historical.owner_current_count is None
        multiple = next(item for item in rows if item.name_ko == "다지역마주")
        assert multiple.owner_current_count == 7
        assert multiple.owner_regional_counts == (("서울", 3), ("부산", 4))
        busan = load_entity_list(session, kind_slug="owners", meet=3)
        assert [(item.name_ko, item.owner_current_count) for item in busan.items] == [
            ("다지역마주", 4),
        ]
        searched = load_entity_list(session, kind_slug="owners", query="000002")
        assert searched.items[0].name_ko == "소수등록"
        assert load_entity_list(session, kind_slug="owners", query="과거마주").total_count == 1
        for query in ("등록없음", "000003"):
            found = load_entity_list(session, kind_slug="owners", query=query, meet=1)
            assert found.total_count == 1 and found.items[0].owner_current_count == 0
        assert load_entity_list(session, kind_slug="owners", query="   ").total_count == 3
        for sort, expected in [("owned", [8, 7, 5]), ("owned_asc", [5, 7, 8])]:
            for position, count in enumerate(expected, 1):
                ordered = load_entity_list(session, kind_slug="owners", sort=sort,
                                           page_size=1, page=position)
                assert ordered.total_count == 3 and ordered.items[0].owner_current_count == count
    engine.dispose()


def test_owner_table_displays_records_and_preserves_period_state(tmp_path, monkeypatch):
    from bs4 import BeautifulSoup

    from horse_racing.web import entities

    monkeypatch.setattr(entities, "today_seoul", lambda: date(2026, 10, 8))
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'owners.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        owner = Owner(kra_owner_id="110034", name_ko="(주)나스카")
        session.add(owner)
        session.flush()
        add_catalog(session, [owner], [(0, 1, 131, 28), (0, 3, 15, 7)], 1)
        session.commit()
    with TestClient(create_app(session_factory=factory)) as client:
        response = client.get("/owners")
        monthly = client.get("/owners?meet=1&q=나스카&sort=starts&period=month")
        annual = client.get("/owners?meet=1&q=나스카&sort=starts&period=year")
        invalid = client.get("/owners?period=invalid")
        descending = client.get("/owners?q=나스카&sort=owned&period=month&page=2")
        descending_soup = BeautifulSoup(descending.text, "html.parser")
        header = descending_soup.select_one('th[data-server-sort]')
        assert header["aria-sort"] == "descending"
        sort_link = header.select_one("a")["href"]
        assert "sort=owned_asc" in sort_link and "period=month" in sort_link
        assert "q=" in sort_link and "page=" not in sort_link
        ascending = client.get(sort_link)
    assert response.status_code == 200
    table = response.text.split('class="owner-list-table"', 1)[1].split("</table>", 1)[0]
    assert table.count("<th") == 11  # thead plus ten column headers
    assert "<th>번호</th>" in table and "<th>마주명</th>" in table
    assert ">총소유두수</a>" in table and "35두" in table
    assert 'title="서울 28두 · 부산 7두"' in table
    asc_header = BeautifulSoup(ascending.text, "html.parser").select_one('th[data-server-sort]')
    assert asc_header["aria-sort"] == "ascending"
    assert "sort=owned&" in asc_header.select_one("a")["href"]
    regional_header = BeautifulSoup(monthly.text, "html.parser").select_one('th[data-server-sort]')
    assert regional_header.text == "현소유두수"
    assert "meet=1" in regional_header.select_one("a")["href"]
    assert 'href="/owners/110034"' in table
    assert "상금" not in table and "등록일" not in table and "등록지역" not in table
    assert "<th>마주번호</th>" not in table
    assert "출전</th>" in table and "복승률</th>" in table and "입상률</th>" in table
    for html, selected, start in [(monthly.text, "최근 1개월", "2026.09.08"),
                                  (annual.text, "최근 1년", "2025.10.08"),
                                  (invalid.text, "통산", None)]:
        soup = BeautifulSoup(html, "html.parser")
        tabs = soup.select_one('[aria-label="마주 전적 기간"]')
        assert tabs.select_one('[aria-current="page"]').text.strip() == selected
        if start:
            assert start in soup.select_one(".jockey-period-range").text
            for link in tabs.select("a"):
                assert "meet=1" in link["href"] and "sort=starts" in link["href"]
            assert soup.select_one('input[name="period"]')["value"] in {"month", "year"}
            assert "period=" in soup.select_one('.entity-region-tabs a')["href"]
            assert soup.select_one('input[name="meet"]')["value"] == "1"
    engine.dispose()


def test_old_snapshot_with_unknown_current_count_never_uses_lifetime_total():
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        owner = Owner(kra_owner_id="110034", name_ko="과거 관측")
        session.add(owner)
        session.flush()
        add_catalog(session, [owner], [(0, 1, 131, None)], 1)
        session.commit()
        page = load_entity_list(session, kind_slug="owners", meet=1, sort="registered")
        assert page.sort == "owned"  # Legacy sort URLs use the new count definition.
        assert page.total_count == 0 and page.items == []
        page = load_entity_list(session, kind_slug="owners", meet=1, query="과거 관측")
        assert page.items[0].owner_current_count is None
        assert page.items[0].owner_regional_counts == ()
    engine.dispose()


def test_owner_zero_region_and_partially_unknown_total():
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        owners = [Owner(kra_owner_id=f"{n:06d}", name_ko=name) for n, name in enumerate(
            ["부산만소유", "부분미확인"], 1,
        )]
        session.add_all(owners)
        session.flush()
        add_catalog(session, owners, [
            (0, 1, 10, 0), (0, 3, 10, 5), (1, 1, 10, 3), (1, 3, 10, None),
        ], 1)
        session.commit()
        full = load_entity_list(session, kind_slug="owners")
        assert [(item.name_ko, item.owner_current_count) for item in full.items] == [
            ("부산만소유", 5),
        ]
        seoul = load_entity_list(session, kind_slug="owners", meet=1)
        assert [item.name_ko for item in seoul.items] == ["부분미확인"]
        searched = load_entity_list(session, kind_slug="owners", query="부산만소유", meet=1)
        assert searched.items[0].owner_current_count == 0
        unknown = load_entity_list(session, kind_slug="owners", query="부분미확인")
        assert unknown.items[0].owner_current_count is None
    engine.dispose()


def test_owner_records_period_region_exclusions_rates_and_sorting(monkeypatch):
    from sqlalchemy import event

    from horse_racing.web import entities

    monkeypatch.setattr(entities, "today_seoul", lambda: date(2026, 10, 8))
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        owners = [Owner(kra_owner_id=f"{n:06d}", name_ko=name) for n, name in enumerate(
            ["성과마주", "다른마주", "신규마주"], 1,
        )]
        horse = Horse(kra_horse_id="000001", name_ko="같은말")
        seoul = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        busan = Racecourse(kra_meet_code=3, code="BUSAN", name_ko="부산")
        session.add_all([*owners, horse, seoul, busan])
        session.flush()
        add_catalog(session, owners, [
            (0, 1, 131, 28), (0, 3, 15, 5), (1, 1, 23, 2), (2, 1, 0, 0),
        ], 1)
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
        for number, (day, finish, disqualified, scratched, status) in enumerate(fixtures, 1):
            entry = RaceEntry(owner=owners[0], horse=horse, horse_number=1, scratched=scratched,
                              race=Race(racecourse=seoul, race_date_local=day,
                                        race_number=number, distance_m=1200, status=status))
            session.add(RaceResult(race_entry=entry, finish_position=finish,
                                   disqualified=disqualified))
        for owner, course, finish in [(owners[0], busan, 1), (owners[1], seoul, 2)]:
            entry = RaceEntry(owner=owner, horse=horse, horse_number=1,
                              race=Race(racecourse=course, race_date_local=date(2026, 10, 8),
                                        race_number=20 + finish, distance_m=1200,
                                        status="completed"))
            session.add(RaceResult(race_entry=entry, finish_position=finish))
        session.commit()
        ids = [owner.id for owner in owners]
        queries = []

        def record(_connection, _cursor, sql, _params, _context, _many):
            queries.append(sql)

        event.listen(engine, "before_cursor_execute", record)
        try:
            career = entities._load_owner_directory_stats(session, ids, "career", 1)
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert len(queries) == 1
        assert career[ids[0]][:4] == (7, 2, 1, 1)
        assert career[ids[0]][4:] == ("28.6%", "42.9%", "57.1%")
        assert career[ids[2]] == entities.DirectoryPerformanceStats()
        month = entities._load_owner_directory_stats(session, ids, "month", 1)[ids[0]]
        assert month[:4] == (4, 1, 1, 0)
        assert month[4:] == ("25.0%", "50.0%", "50.0%")
        year = entities._load_owner_directory_stats(session, ids, "year", 1)[ids[0]]
        assert year[:4] == (6, 1, 1, 1)
        all_regions = entities._load_owner_directory_stats(session, ids, "month", None)[ids[0]]
        assert all_regions[:4] == (5, 2, 1, 0)
        page = load_entity_list(session, kind_slug="owners", sort="starts",
                                period="month", meet=1, page_size=1)
        assert page.items[0].name_ko == "성과마주"
        assert page.items[0].owner_stats == month
        assert page.items[0].owner_current_count == 28
        assert page.period_start == date(2026, 9, 8)
        page2 = load_entity_list(session, kind_slug="owners", sort="starts",
                                 period="month", meet=1, page_size=1, page=2)
        assert page2.items[0].name_ko == "다른마주"
        assert page2.items[0].owner_stats.starts == 1
        all_page = load_entity_list(session, kind_slug="owners", sort="starts", period="month")
        assert all_page.items[0].owner_stats == all_regions
    engine.dispose()
