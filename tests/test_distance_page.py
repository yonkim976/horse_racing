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
        yeongcheon = Racecourse(kra_meet_code=4, code="YEONGCHEON", name_ko="영천")
        session.add_all([jeju, seoul, yeongcheon])
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
        historic = load_distance_page(session, year=0, distance=400, grade="", page=1)
        assert historic["total"] == 0
        assert all(not grade.startswith("한") for grade in all_data["grade_labels"])
        unknown = load_distance_page(session, year=0, distance=0, grade="미분류", page=1)
        assert unknown["total"] == 1


def test_render_empty_and_validation(factory):
    client = TestClient(create_app(session_factory=factory))
    response = client.get("/racecourses/jeju/distances")
    assert response.status_code == 200
    assert "제주 거리별 분석" in response.text
    assert response.text.count('<option value="2026"') == 1
    assert "/races/" in response.text
    empty = client.get("/racecourses/jeju/distances?year=2026&distance=400")
    assert empty.status_code == 200
    assert "선택한 조건의 경주 기록이 없습니다" in empty.text
    for query in ("grade=invalid", "grade=한OPEN", "year=-1", "distance=-1", "page=0"):
        assert client.get(f"/racecourses/jeju/distances?{query}").status_code == 422
    with factory() as session:
        retired_race_id = session.query(Race.id).filter(Race.grade.like("한%")).scalar()
    assert client.get(f"/races/{retired_race_id}").status_code == 404


def test_seoul_distance_page_is_separate_and_validates_course(factory):
    with factory() as session:
        course = session.query(Racecourse).filter_by(kra_meet_code=1).one()
        session.add(Race(racecourse=course, race_date_local=date(2026, 9, 6), race_number=99,
                         distance_m=1700, grade="혼4", status="completed"))
        session.commit()
    client = TestClient(create_app(session_factory=factory))
    response = client.get("/racecourses/seoul/distances?year=2026&grade=혼4등급&distance=1700")
    assert response.status_code == 200
    assert "서울 거리별 분석" in response.text
    assert "course-view.js?v=11" in response.text
    assert 'action="/racecourses/seoul/distances"' in response.text
    assert '1,700' in response.text
    assert client.get("/racecourses/unknown/distances").status_code == 404
    with factory() as session:
        data = load_distance_page(session, year=2026, distance=1700, grade="혼4등급",
                                  page=1, meet_code=1)
        assert data["total"] == 1
        assert data["items"][0]["display_grade"] == "혼4등급"


def test_yeongcheon_distance_page_supports_general_grade_labels(factory):
    client = TestClient(create_app(session_factory=factory))
    response = client.get(
        "/racecourses/yeongcheon/distances?year=2026&distance=1200&grade=1%EB%93%B1%EA%B8%89"
    )
    assert response.status_code == 200
    assert "영천 거리별 분석" in response.text
    assert "주행심사" in response.text
    assert "/racecourses/yeongcheon/course" in response.text



def test_course_view_shell_preserves_trial_year_in_meet_links(factory):
    client = TestClient(create_app(session_factory=factory))
    response = client.get("/racecourses/seoul/distances?view=trials&year=2026")
    assert response.status_code == 200
    assert (
        '<div class="course-view-content" data-course-view-content '
        'data-course="seoul" data-view="distances">'
    ) in response.text
    for slug in ("seoul", "busan", "yeongcheon", "jeju"):
        assert (
            f'href="/racecourses/{slug}/distances?view=trials&amp;year=2026" '
            f'data-course-meet="{slug}"'
        ) in response.text

def test_seoul_1200_benchmark_routes_validate_band_and_render_grade_views(factory):
    client = TestClient(create_app(session_factory=factory))
    all_grades = client.get(
        "/racecourses/seoul/distances?year=2026&distance=1200&band=다습"
    )
    assert all_grades.status_code == 200
    assert "1200m 기록 기준" in all_grades.text
    assert "다습 · 10–14%" in all_grades.text
    assert "연구용 추정 기준" in all_grades.text
    assert "관측 출전기록/경주/일" in all_grades.text
    assert "전체 등급을 합친 기록" not in all_grades.text
    assert "band=%EB%8B%A4%EC%8A%B5" in all_grades.text

    selected = client.get(
        "/racecourses/seoul/distances?year=2026&distance=1200&grade=%EA%B5%AD5%EB%93%B1%EA%B8%89&band=%EB%B6%88%EB%9F%89"
    )
    assert selected.status_code == 200
    assert "5개 함수율별 전체시간 기준" not in selected.text
    assert "불량 함수율 · 구간별 기준" in selected.text
    assert "1:15.09" in selected.text
    assert "마지막 400m" not in selected.text

    unsupported = client.get(
        "/racecourses/seoul/distances?year=2026&distance=1200&grade=%EA%B5%AD2%EB%93%B1%EA%B8%89"
    )
    assert unsupported.status_code == 200
    assert "국2등급 연구 기준 자료가 없습니다" in unsupported.text
    for path in (
        "/racecourses/seoul/distances?distance=1200&band=invalid",
        "/racecourses/seoul/distances?distance=1200&band=",
        "/racecourses/seoul/distances?distance=1000&band=건조",
        "/racecourses/jeju/distances?distance=1200&band=건조",
        "/racecourses/seoul/distances?view=trials&band=건조",
    ):
        assert client.get(path).status_code == 422


def test_links_to_1200m_from_distance_and_trial_views_get_a_valid_default_band(factory):
    target_urls = []
    with factory() as session:
        seoul = session.query(Racecourse).filter_by(kra_meet_code=1).one()
        session.add(
            Race(
                racecourse=seoul,
                race_date_local=date(2026, 9, 6),
                race_number=100,
                distance_m=1200,
                grade="국5",
                status="completed",
            )
        )
        session.commit()

        for distance, view in ((0, "regular"), (1700, "regular"), (0, "trials")):
            data = load_distance_page(
                session,
                year=2026 if view == "regular" else None,
                distance=distance,
                grade="",
                page=1,
                meet_code=1,
                view=view,
            )
            target = next(item for item in data["distances"] if item["distance"] == 1200)
            query = parse_qs(urlparse(target["url"]).query)
            assert query.get("band") in (None, ["건조"])
            target_urls.append(target["url"])

    client = TestClient(create_app(session_factory=factory))
    for url in target_urls:
        response = client.get(url)
        assert response.status_code == 200
        assert 'option value="건조" selected' in response.text
