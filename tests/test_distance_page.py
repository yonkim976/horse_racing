from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from horse_racing.db.base import Base
from horse_racing.db.models import Horse, Race, Racecourse, RaceEntry, RaceResult
from horse_racing.web.app import create_app
from horse_racing.web.distance_page import load_distance_page


@pytest.fixture
def factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    with factory() as session:
        jeju = Racecourse(kra_meet_code=2, code="JEJU", name_ko="제주")
        seoul = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        session.add_all([jeju, seoul])
        for number in range(1, 33):
            race = Race(
                racecourse=jeju,
                race_date_local=date(2026, 8, 1),
                race_number=number,
                distance_m=1000,
                grade="제5등급핸디캡",
                status="completed",
            )
            session.add(race)
            if number == 1:
                for i, (position, time, scratched, disqualified) in enumerate(
                    [
                        (1, 70000, False, False),
                        (2, 80000, False, False),
                        (90, 1000, False, False),
                        (3, 1000, True, False),
                        (4, 1000, False, True),
                        (5, None, False, False),
                    ],
                    1,
                ):
                    entry = RaceEntry(
                        race=race,
                        horse=Horse(kra_horse_id=str(i), name_ko=f"말{i}"),
                        horse_number=i,
                        scratched=scratched,
                    )
                    session.add(
                        RaceResult(
                            race_entry=entry,
                            finish_position=position,
                            finish_time_ms=time,
                            disqualified=disqualified,
                        )
                    )
        for number, course, year, distance, grade, status in [
            (33, jeju, 2026, 900, "3상", "completed"),
            (34, jeju, 2025, 400, "한오픈 핸디캡", "completed"),
            (35, jeju, 2027, 1000, "제5등급", "scheduled"),
            (36, seoul, 2027, 1000, "제5등급", "completed"),
        ]:
            session.add(
                Race(
                    racecourse=course,
                    race_date_local=date(year, 8, 1),
                    race_number=number,
                    distance_m=distance,
                    grade=grade,
                    status=status,
                )
            )
        session.commit()
    yield factory
    engine.dispose()


def test_filters_statistics_and_pagination(factory):
    with factory() as session:
        all_data = load_distance_page(session, year=None, distance=0, grade="", page=1)
        assert all_data["year"] == 2026
        assert all_data["total"] == 33
        assert all_data["average"] == "—"
        data = load_distance_page(session, year=2026, distance=1000, grade="제5등급", page=1)
        assert (data["total"], data["entries"], data["timed"]) == (32, 6, 2)
        assert data["average"] == "1:15.0"
        assert data["best"] == "1:10.0"
        assert len(data["items"]) == 30
        assert parse_qs(urlparse(data["next"]).query) == {
            "year": ["2026"],
            "distance": ["1000"],
            "grade": ["제5등급"],
            "page": ["2"],
        }
        last = load_distance_page(session, year=2026, distance=1000, grade="제5등급", page=99)
        assert last["page"] == 2
        assert len(last["items"]) == 2
        assert last["items"][-1]["winner_time"] == "1:10.0"
        historic = load_distance_page(session, year=0, distance=400, grade="한OPEN", page=1)
        assert historic["total"] == 1
        unknown = load_distance_page(session, year=0, distance=0, grade="미분류", page=1)
        assert unknown["total"] == 1


def test_render_empty_and_validation(factory):
    client = TestClient(create_app(session_factory=factory))
    response = client.get("/racecourses/jeju/distances")
    assert response.status_code == 200
    assert "제주 거리별 분석" in response.text
    assert "/races/" in response.text
    empty = client.get("/racecourses/jeju/distances?year=2026&distance=400")
    assert empty.status_code == 200
    assert "선택한 조건의 경주 기록이 없습니다" in empty.text
    for query in ("grade=invalid", "year=-1", "distance=-1", "page=0"):
        assert client.get(f"/racecourses/jeju/distances?{query}").status_code == 422
