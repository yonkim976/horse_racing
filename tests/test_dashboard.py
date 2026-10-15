import csv
import json
import re
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import (
    Horse,
    HorseMedical,
    HorseProfileSnapshot,
    HorseRatingSnapshot,
    HorseStartTraining,
    HorseTraining,
    HorseWeightHistory,
    Jockey,
    ModelPrediction,
    OddsSnapshot,
    Owner,
    PredictionOutcome,
    PredictionRun,
    PredictionSettlement,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    RaceSectionResult,
    RunningTrial,
    RunningTrialResult,
    Trainer,
    TrainerAffiliationSnapshot,
)
from horse_racing.web.app import create_app
from horse_racing.web.dashboard import (
    _recent_form_by_horse,
    _recent_trial_form_by_horse,
    load_calendar_index,
)
from horse_racing.web.request_policy import RequestPolicy

PHONE_HEADERS = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"}


@pytest.fixture
def paced_requests(monkeypatch):
    """Let multi-page rendering tests model human pacing without real sleeps.

    Separate security tests exercise the default burst and minute quotas.
    """
    check_request = RequestPolicy.check_request
    clock = 0.0

    def check_with_pacing(self, request, *, client_key, now=None):
        nonlocal clock
        clock += 3.0
        return check_request(self, request, client_key=client_key, now=clock)

    monkeypatch.setattr(RequestPolicy, "check_request", check_with_pacing)


def test_search_engine_files_are_public_and_use_canonical_urls(tmp_path: Path) -> None:
    client = TestClient(create_app(session_factory=seeded_session(tmp_path)))
    phone = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"}

    robots = client.get("/robots.txt", headers=phone, follow_redirects=False)
    sitemap = client.get("/sitemap.xml", headers=phone, follow_redirects=False)
    home = client.get("/")
    sample = client.get("/race-sample")

    assert robots.status_code == 200
    assert robots.headers["content-type"].startswith("text/plain")
    assert "User-agent: ClaudeBot\nDisallow: /" in robots.text
    assert "User-agent: Claude-SearchBot\nAllow: /" in robots.text
    assert "User-agent: Claude-User\nAllow: /" in robots.text
    assert "User-agent: *\nAllow: /" in robots.text
    assert "Sitemap: https://mapilog.xyz/sitemap.xml" in robots.text
    assert sitemap.status_code == 200
    assert home.status_code == 200
    assert 'href="/forecast"' not in home.text
    assert 'href="/validation"' not in home.text
    assert 'href="/predictions"' not in home.text
    assert 'href="/data-status"' not in home.text
    assert 'href="/race-sample"' not in home.text
    assert sample.status_code == 404
    assert sitemap.headers["content-type"].startswith("application/xml")
    root = ElementTree.fromstring(sitemap.content)
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [item.text for item in root.findall("s:url/s:loc", namespace)]
    assert "https://mapilog.xyz/" in urls
    assert "https://mapilog.xyz/forecast" not in urls
    assert "https://mapilog.xyz/validation" not in urls
    assert "https://mapilog.xyz/predictions" not in urls
    assert "https://mapilog.xyz/racecourses/jeju/distances" in urls
    assert all(url is not None and url.startswith("https://mapilog.xyz/") for url in urls)
    assert not any("/m/" in url for url in urls if url is not None)


def test_anthropic_crawlers_can_read_robots_but_cannot_fetch_pages(tmp_path: Path) -> None:
    client = TestClient(create_app())
    headers = {
        "user-agent": (
            "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; "
            "compatible; ClaudeBot/1.0; +claudebot@anthropic.com)"
        )
    }

    robots = client.get("/robots.txt", headers=headers)
    page = client.get("/", headers=headers)

    assert robots.status_code == 200
    assert "User-agent: ClaudeBot\nDisallow: /" in robots.text
    assert page.status_code == 403
    assert page.content == b""
    assert page.headers["x-robots-tag"] == "noindex, nofollow"


@pytest.mark.parametrize("agent", ["SerpstatBot", "AhrefsBot"])
def test_bulk_harvesters_are_denied_before_database_access(agent: str) -> None:
    def unavailable_session():
        raise AssertionError("blocked requests must not open the database")

    with TestClient(create_app(session_factory=unavailable_session)) as client:
        robots = client.get("/robots.txt", headers={"user-agent": agent})
        page = client.get("/", headers={"user-agent": agent})

    assert robots.status_code == 200
    assert f"User-agent: {agent}\nDisallow: /" in robots.text
    assert page.status_code == 403


def test_wordpress_rest_route_probe_is_rejected_before_database_access() -> None:
    def unavailable_session():
        raise AssertionError("scanner probes must not open the database")

    with TestClient(create_app(session_factory=unavailable_session)) as client:
        response = client.get("/?rest_route=/wp/v2/users")

    assert response.status_code == 404
    assert response.content == b""


def test_generic_crawlers_are_rate_limited_without_blocking_search(tmp_path: Path) -> None:
    client = TestClient(create_app())
    headers = {"user-agent": "ExampleCrawler/1.0", "x-forwarded-for": "203.0.113.10"}

    for _ in range(10):
        assert client.get("/robots.txt", headers=headers).status_code == 200
    limited = client.get("/robots.txt", headers=headers)

    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"


def test_calendar_metadata_is_shared_and_html_contains_only_selected_month(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        session.add(RunningTrial(
            meet_code=2,
            trial_date_local=date(2026, 7, 4),
            trial_race_number=1,
            distance_m=800,
            observed_at_ms=1,
        ))
        session.commit()

    calls = 0

    def tracked_calendar_index(session: Session):
        nonlocal calls
        calls += 1
        return load_calendar_index(session)

    monkeypatch.setattr("horse_racing.web.app.load_calendar_index", tracked_calendar_index)
    with TestClient(create_app(factory)) as client:
        august = client.get("/?date=2026-08-21")
        another_day = client.get("/?date=2026-08-13")
        july = client.get("/api/calendar?month=2026-07")
        invalid = client.get("/api/calendar?month=2026-13")

    assert august.status_code == another_day.status_code == july.status_code == 200
    calendar_data = re.search(
        r'<script id="race-calendar-data"[^>]*>(.*?)</script>', august.text, re.S
    )
    assert calendar_data is not None
    assert "2026-08-13" in calendar_data.group(1)
    assert "2026-07-04" not in calendar_data.group(1)
    assert july.json() == [{
        "date": "2026-07-04", "status": "trial-only", "hasRace": False, "hasTrial": True,
    }]
    assert invalid.status_code == 422
    assert calls == 1


def test_recent_form_returns_five_eligible_rows_per_horse_from_sql(tmp_path: Path) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        horse = session.query(Horse).filter_by(kra_horse_id="003001").one()
        course = session.query(Racecourse).filter_by(kra_meet_code=2).one()
        for number in range(1, 8):
            day = date(2026, 8, 1) + timedelta(days=number - 1)
            race = Race(
                racecourse=course, race_date_local=day, race_number=1,
                distance_m=900, status="completed",
            )
            entry = RaceEntry(race=race, horse=horse, horse_number=1)
            session.add(RaceResult(race_entry=entry, finish_position=number))
            trial = RunningTrial(
                meet_code=2, trial_date_local=day, trial_race_number=1,
                distance_m=800, observed_at_ms=1,
            )
            session.add(RunningTrialResult(
                trial=trial, horse=horse, horse_number=1,
                horse_name_raw=horse.name_ko, finish_position=number,
                judgement="주" if number == 7 else "합", observed_at_ms=1,
            ))
        session.commit()

        ranked_queries: list[str] = []

        def capture_query(_connection, _cursor, statement, _parameters, _context, _many):
            if "row_number" in statement.lower():
                ranked_queries.append(statement.lower())

        event.listen(session.bind, "before_cursor_execute", capture_query)
        try:
            race_form = _recent_form_by_horse(session, [horse.id], date(2026, 8, 13))
            trial_form = _recent_trial_form_by_horse(session, [horse.id], date(2026, 8, 13))
        finally:
            event.remove(session.bind, "before_cursor_execute", capture_query)

    assert race_form[horse.id] == "7-6-5-4-3"
    assert trial_form[horse.id] == "심 6합-5합-4합-3합-2합"
    assert len(ranked_queries) == 2
    assert all("recency <= " in statement for statement in ranked_queries)


def test_www_redirects_to_apex_without_leaking_cached_asset_urls(tmp_path: Path) -> None:
    app = create_app(session_factory=seeded_session(tmp_path))
    client = TestClient(app)

    www_response = client.get("https://www.mapilog.xyz/", follow_redirects=False)
    apex_response = client.get("https://mapilog.xyz/")
    run_response = client.get("https://mapilog-example.run.app/")

    assert www_response.status_code == 301
    assert www_response.headers["location"] == "https://mapilog.xyz/"
    assert apex_response.status_code == 200
    assert run_response.status_code == 200
    assert (
        '<meta name="naver-site-verification" '
        'content="a71202c329d9767a2c3589e8637e278720be227f">'
    ) in apex_response.text
    assert '<link rel="canonical" href="https://mapilog.xyz/">' in apex_response.text
    assert '<meta name="robots" content="index,follow">' in apex_response.text
    assert 'rel="alternate"' not in apex_response.text
    assert 'href="https://mapilog.xyz/static/css/dashboard.css?v=78"' in apex_response.text
    assert (
        'href="https://mapilog-example.run.app/static/css/dashboard.css?v=78"'
    ) in run_response.text
    assert '<link rel="canonical" href="https://mapilog.xyz/">' in run_response.text
    assert 'aria-label="마필로그 홈"' in apex_response.text
    assert "mapilog-symbol-color.svg" in apex_response.text
    assert "mapilog-symbol-white.svg" in apex_response.text
    assert "mapilog-wordmark-color.svg" in apex_response.text
    assert "mapilog-wordmark-white.svg" in apex_response.text
    assert "mapilog-favicon-final.svg" in apex_response.text
    assert "mapilog-favicon.png" in apex_response.text
    assert 'class="brand-mark"' not in apex_response.text

    favicon = client.get("https://mapilog.xyz/favicon.ico")
    png = client.get("https://mapilog.xyz/static/images/brand/mapilog-favicon.png")
    assert favicon.status_code == 200
    assert favicon.headers["content-type"].startswith("image/x-icon")
    assert favicon.content[:4] == b"\x00\x00\x01\x00"
    assert png.status_code == 200
    assert png.headers["content-type"].startswith("image/png")


def test_www_redirect_preserves_path_query_and_mobile_rendering(tmp_path: Path) -> None:
    client = TestClient(create_app(session_factory=seeded_session(tmp_path)))
    phone = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"}

    redirected = client.get(
        "https://www.mapilog.xyz/analysis?race_id=1&meet=2",
        headers=phone,
        follow_redirects=False,
    )
    assert redirected.status_code == 301
    assert redirected.headers["location"] == "https://mapilog.xyz/analysis?race_id=1&meet=2"
    mobile = client.get(redirected.headers["location"], headers=phone, follow_redirects=False)
    assert mobile.status_code == 200
    assert 'class="mobile-app mobile-analysis"' in mobile.text
    assert {part.strip().lower() for part in mobile.headers["vary"].split(",")} == {
        "user-agent", "accept-encoding"
    }
    assert client.get("https://www.mapilog.xyz/sitemap.xml", follow_redirects=False).headers[
        "location"
    ] == "https://mapilog.xyz/sitemap.xml"


def test_yeongcheon_schedule_and_detail(tmp_path: Path) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        course = Racecourse(kra_meet_code=4, code="YEONGCHEON", name_ko="영천")
        race = Race(
            racecourse=course, race_date_local=date(2026, 9, 13), race_number=1,
            distance_m=1800, grade="혼OPEN", race_name="렛츠런파크 영천 개장기념",
            status="scheduled",
        )
        session.add(race)
        session.commit()
        race_id = race.id
    client = TestClient(create_app(session_factory=factory))
    response = client.get("/?date=2026-09-13&meet=4")
    assert response.status_code == 200
    assert 'value="4"' in response.text
    assert "영천 개장기념" in response.text
    response = client.get(f"/races/{race_id}")
    assert response.status_code == 200
    assert "영천" in response.text
    assert "서울은 3C" not in response.text
    assert 'data-racecourse-map="yeongcheon"' in response.text
    assert "COURSE EXPLORER" not in response.text
    assert "공식 도면 비교" not in response.text
    assert "확대 보기" not in response.text
    assert 'class="course-method"' not in response.text


@pytest.mark.parametrize(
    ("course", "meet_code", "name", "distance", "alternate_distance", "default_distance"),
    [
        ("seoul", 1, "서울", 1400, 1600, 1400),
        ("jeju", 2, "제주", 1200, 1300, 1200),
        ("busan", 3, "부경", 1600, 1800, 1600),
        ("yeongcheon", 4, "영천", 1400, 1800, 1400),
    ],
)
def test_course_map_page_loads_one_selected_route_for_each_meet(
    tmp_path: Path, course: str, meet_code: int, name: str, distance: int,
    alternate_distance: int, default_distance: int,
) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        response = client.get(f"/racecourses/{course}/course?distance={distance}")
        default_response = client.get(f"/racecourses/{course}/course")

    assert response.status_code == 200
    assert len(response.content) < 2 * 1024 * 1024
    assert f"{name} 경주로" in response.text
    display_name = "부산" if name == "부경" else name
    assert f"<h1>{display_name} 경주로·거리 분석</h1>" in response.text
    assert "course-view.js?v=13" in response.text
    assert f"distance={distance}" in response.text
    assert "COURSE EXPLORER" not in response.text
    assert "공식 도면 비교" not in response.text
    assert "확대 보기" not in response.text
    assert "거리별 기록과 경주로의 출발점·주행 경로를 확인하세요." in response.text
    assert 'data-course-view-tabs data-course="' + course + '"' in response.text
    assert (
        f'href="/racecourses/{course}/course" data-course-view-link '
        f'data-course="{course}" data-course-view="course" aria-current="page">지도 보기</a>'
    ) in response.text
    assert '<nav class="distance-options course-map-meets" aria-label="경마장 선택" data-course-meet-nav>' in response.text
    for meet in ("seoul", "busan", "yeongcheon", "jeju"):
        assert f'href="/racecourses/{meet}/course" data-course-meet="{meet}"' in response.text
    assert (
        f'href="/racecourses/{course}/distances" data-course-view-link '
        f'data-course="{course}" data-course-view="distances"'
    ) in response.text
    assert (
        f'<div class="course-view-content" data-course-view-content '
        f'data-course="{course}" data-view="course">'
    ) in response.text
    assert 'data-course-view-status role="status" aria-live="polite"' in response.text
    if meet_code == 1:
        assert f"서울 경주로 <span>{distance:,}m</span>" in response.text
        assert 'data-seoul-view-label' not in response.text
        assert 'aria-label="지도 구간 색상 안내"' in response.text
        assert response.text.index('aria-label="지도 구간 색상 안내"') < response.text.index('class="seoul-viewport"')
        assert "4C는 G3F 이후 70m, 결승 전 530m" in response.text
        assert 'class="course-method"' not in response.text
        assert "선택한 거리의 출발점과 주행 경로를 확인합니다" not in response.text
        assert "2023년 이전의 예외 경로는 반영하지 않습니다" not in response.text
    else:
        assert 'class="course-method"' in response.text
        assert "선택 거리 ·" not in response.text
    assert "현재 경주" not in response.text
    assert "전체 거리 보기 ↗" not in response.text
    assert "지점을 선택하면 구간 기록을 확인할 수 있습니다." not in response.text
    assert "구간 순서도" not in response.text
    assert "최종 착순 상위" not in response.text
    assert f'href="/racecourses/{course}/course?distance={alternate_distance}"' in response.text
    assert response.text.index('class="course-distance-picker"') < response.text.index(
        'class="seoul-viewport"'
    )
    assert default_response.status_code == 200
    assert f'data-distance="{default_distance}"' in default_response.text
    if meet_code == 2:
        assert response.text.count("data-jeju-route/>") == 1
    else:
        assert response.text.count('data-seoul-route="') == 1
    assert f"data-distance=\"{distance}\"" in response.text


def test_course_map_page_rejects_unknown_course_and_distance(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        unknown_course = client.get("/racecourses/not-a-meet/course")
        unknown_distance = client.get("/racecourses/seoul/course?distance=1111")

    assert unknown_course.status_code == 404
    assert unknown_distance.status_code == 404


@pytest.mark.parametrize(
    ("course", "meet_code", "name", "distance"),
    [
        ("seoul", 1, "서울", 1400),
        ("jeju", 2, "제주", 1200),
        ("busan", 3, "부경", 1600),
        ("yeongcheon", 4, "영천", 1400),
    ],
)
def test_race_detail_embeds_only_its_distance_route(
    tmp_path: Path, course: str, meet_code: int, name: str, distance: int,
) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        racecourse = session.query(Racecourse).filter_by(kra_meet_code=meet_code).one_or_none()
        if racecourse is None:
            racecourse = Racecourse(
                kra_meet_code=meet_code, code=course.upper(), name_ko=name,
            )
        race = Race(
            racecourse=racecourse,
            race_date_local=date(2026, 9, 13),
            race_number=2,
            distance_m=distance,
            grade="혼OPEN",
            race_name="지도 전송량 확인",
            status="scheduled",
        )
        session.add(race)
        session.commit()
        race_id = race.id

    with TestClient(create_app(factory)) as client:
        response = client.get(f"/races/{race_id}")

    assert response.status_code == 200
    assert len(response.content) < 2 * 1024 * 1024
    assert f'<div class="race-hero" data-racecourse="{name}">' in response.text
    assert response.text.count('data-seoul-route="') == (0 if meet_code == 2 else 1)
    assert response.text.count("data-jeju-route/>") == (1 if meet_code == 2 else 0)
    map_script = "course-explorer.js?v=17" if meet_code == 2 else "seoul-map.js?v=17"
    assert map_script in response.text
    assert f"href=\"/racecourses/{course}/course?distance={distance}\"" in response.text
    assert "COURSE EXPLORER" not in response.text
    assert "공식 도면 비교" not in response.text
    assert "확대 보기" not in response.text
    assert 'data-course-view-label>현재 경주 ·' not in response.text
    assert 'data-seoul-view-label>현재 경주 ·' not in response.text
    assert 'class="course-detail-kicker">현재 경주 ·' not in response.text
    assert 'class="course-record-layout"' not in response.text
    assert 'class="course-record-nav"' not in response.text
    assert 'class="course-inspector"' not in response.text
    assert 'class="course-method"' not in response.text
    assert 'class="course-detail-kicker">구간 순서도</p>' not in response.text
    assert "현재 경주" in response.text
    assert "전체 거리 보기 ↗" in response.text
    from bs4 import BeautifulSoup
    map_section = BeautifulSoup(response.text, "html.parser").select_one("#racecourse-map")
    assert map_section.select_one(".course-heading .course-color-key") is None
    assert map_section.select_one('.seoul-viewport .course-map-legend [aria-label="지도 구간 색상 안내"]') is not None
    if meet_code != 2:
        assert "다른 거리의 경주로도 보기 ↗" not in response.text
        assert "지도 지점은 거리 기준 개략 위치" not in response.text
        assert "현재 출발점과 표준 주로를 표시합니다" not in response.text
    if meet_code == 1:
        assert "4C는 G3F 이후 70m, 결승 전 530m" in response.text


def seeded_session(tmp_path: Path) -> sessionmaker[Session]:
    database_url = f"sqlite:///{tmp_path / 'dashboard.sqlite3'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
    engine = create_engine_for_url(database_url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    scheduled_at = int(
        datetime(2026, 8, 21, 13, 10, tzinfo=ZoneInfo("Asia/Seoul")).timestamp() * 1000
    )
    with factory() as session:
        racecourse = Racecourse(kra_meet_code=2, code="JEJU", name_ko="제주")
        horse = Horse(
            kra_horse_id="003001",
            name_ko="바람의별",
            sex="거",
            origin_country="한국",
            birth_date=date(2022, 3, 15),
            grade="제6등급",
            meet_code=2,
            sire_name="TEST SIRE",
            dam_name="TEST DAM",
        )
        jockey = Jockey(kra_jockey_id="080101", name_ko="한기수")
        trainer = Trainer(kra_trainer_id="070101", name_ko="김조교")
        owner = Owner(kra_owner_id="050101", name_ko="이마주")
        race = Race(
            racecourse=racecourse,
            race_date_local=date(2026, 8, 21),
            race_number=1,
            distance_m=900,
            grade="제6등급",
            race_name="일반",
            scheduled_at_ms=scheduled_at,
            weather="맑음",
            track_condition="건조",
            track_moisture_percent=3,
            status="completed",
        )
        entry = RaceEntry(
            race=race,
            horse=horse,
            horse_number=1,
            jockey=jockey,
            trainer=trainer,
            owner=owner,
            carried_weight_kg=55,
            body_weight_kg=280,
            body_weight_change_kg=2,
            rating=45,
        )
        result = RaceResult(
            race_entry=entry,
            finish_position=1,
            finish_time_ms=75_200,
            prize_money_krw=15_000_000,
        )
        running_trial = RunningTrial(
            meet_code=2,
            trial_date_local=date(2026, 8, 13),
            trial_round=31,
            trial_race_number=2,
            distance_m=800,
            weather="맑음",
            track_condition="건조",
            track_moisture_percent=3,
            observed_at_ms=scheduled_at,
        )
        running_trial_result = RunningTrialResult(
            trial=running_trial,
            horse=horse,
            jockey=jockey,
            trainer=trainer,
            horse_number=4,
            horse_name_raw="바람의별",
            carried_weight_base_kg=54,
            carried_weight_extra_kg=1,
            finish_position=1,
            finish_rank_raw="01",
            body_weight_kg=278,
            finish_time_ms=67_100,
            judgement="합",
            inspection_reason="주행미합(신)",
            s1f_ms=18_100,
            g3f_ms=49_000,
            g1f_ms=17_100,
            jockey_name_raw="한기수",
            trainer_name_raw="김조교",
            observed_at_ms=scheduled_at,
        )
        excluded = Horse(
            kra_horse_id="003099",
            name_ko="제외마",
            sex="수",
            origin_country="한국",
            birth_date=date(2022, 4, 1),
        )
        idle = Horse(kra_horse_id="009999", name_ko="가가나")
        race_two = Race(
            racecourse=racecourse,
            race_date_local=date(2026, 8, 21),
            race_number=2,
            distance_m=1000,
            grade="제5등급",
            race_name="일반",
            scheduled_at_ms=scheduled_at + 3_600_000,
            status="completed",
        )
        excluded_entry = RaceEntry(
            race=race,
            horse=excluded,
            horse_number=7,
            jockey=jockey,
            trainer=trainer,
            owner=owner,
            scratched=True,
        )
        excluded_result = RaceResult(race_entry=excluded_entry, finish_position=94)
        session.add_all(
            [
                racecourse,
                horse,
                jockey,
                trainer,
                owner,
                race,
                race_two,
                entry,
                excluded_entry,
                result,
                running_trial,
                running_trial_result,
                excluded_result,
                idle,
                excluded,
                RaceSectionResult(
                    race_entry=entry,
                    section_code="S1F",
                    elapsed_time_ms=13_500,
                    position=1,
                ),
                RaceSectionResult(
                    race_entry=entry,
                    section_code="3C",
                    elapsed_time_ms=13_500,
                    position=1,
                ),
                RaceSectionResult(
                    race_entry=entry,
                    section_code="G1F",
                    elapsed_time_ms=17_200,
                    position=None,
                ),
                OddsSnapshot(
                    race=race,
                    bet_type="WIN",
                    selection_key="1",
                    odds=2.1,
                    observed_at_ms=scheduled_at,
                ),
                OddsSnapshot(
                    race=race,
                    bet_type="PLC",
                    selection_key="1",
                    odds=1.2,
                    observed_at_ms=scheduled_at,
                ),
                OddsSnapshot(
                    race=race,
                    bet_type="QNL",
                    selection_key="1-7",
                    odds=8.4,
                    observed_at_ms=scheduled_at,
                ),
                HorseRatingSnapshot(
                    horse=horse,
                    meet_code=2,
                    rating_1=40,
                    rating_2=41,
                    rating_3=42,
                    rating_4=45,
                    observed_at_ms=scheduled_at,
                ),
                HorseWeightHistory(
                    horse=horse,
                    meet_code=2,
                    race_date_local=date(2026, 8, 21),
                    race_number=1,
                    horse_number=1,
                    body_weight_kg=280,
                    body_weight_change_kg=2,
                    observed_at_ms=scheduled_at,
                ),
                HorseTraining(
                    horse=horse,
                    meet_code=2,
                    training_date_local=date(2026, 8, 19),
                    trainer_name="김조교",
                    duration_seconds=900,
                    canter_count=2,
                    gallop_count=1,
                    entry_plan="금주출전예정",
                    started_at_raw="20260819070000",
                    ended_at_raw="20260819071500",
                    observed_at_ms=scheduled_at,
                ),
                HorseMedical(
                    horse=horse,
                    meet_code=2,
                    clinic_date_local=date(2026, 8, 10),
                    hospital_name="제주동물병원",
                    diagnosis_1="근막염",
                    diagnosis_2=None,
                    observed_at_ms=scheduled_at,
                ),
                HorseProfileSnapshot(
                    horse=horse,
                    meet_code=2,
                    grade="제6등급",
                    rating=45,
                    race_count_total=12,
                    race_count_year=5,
                    win_count_total=3,
                    win_count_year=1,
                    second_count_total=2,
                    second_count_year=1,
                    third_count_total=1,
                    third_count_year=0,
                    prize_money_total_krw=45_000_000,
                    last_sale_amount_raw="12,000천원",
                    trainer_kra_id="070101",
                    trainer_name="김조교",
                    owner_kra_id="050101",
                    owner_name="이마주",
                    observed_at_ms=scheduled_at,
                ),
            ]
        )
        session.commit()
        prediction_run = PredictionRun(
            public_id="11111111-1111-1111-1111-111111111111",
            experiment_run_id="61336314-3615-4a87-bc3c-93a90f448c18",
            model_type="probability_ensemble",
            dataset_version="v2_trials",
            as_of_policy="start_minus_30m",
            race_date_local=date(2026, 8, 21),
            feature_cutoff_at_ms=scheduled_at - 3_600_000,
            published_at_ms=scheduled_at - 1_800_000,
            publication_mode="live",
            model_artifact_sha256="a" * 64,
            feature_hash="b" * 64,
            predictions_sha256="c" * 64,
        )
        session.add(prediction_run)
        session.flush()
        model_prediction = ModelPrediction(
            prediction_run_id=prediction_run.id,
            race_id=race.id,
            race_entry_id=entry.id,
            horse_number=1,
            prob_win=1.0,
            prob_top2=1.0,
            prob_top3=1.0,
        )
        session.add(model_prediction)
        session.flush()
        settlement = PredictionSettlement(
            public_id="22222222-2222-2222-2222-222222222222",
            prediction_run_id=prediction_run.id,
            settled_at_ms=scheduled_at + 3_600_000,
            outcomes_sha256="d" * 64,
            n_races=1,
            n_entries=1,
            n_excluded_races=0,
            win_log_loss=0.0,
            win_brier=0.0,
            win_ece=0.0,
            win_top1_hit_rate=1.0,
            win_top3_inclusion_rate=1.0,
            top2_log_loss=0.0,
            top3_log_loss=0.0,
        )
        session.add(settlement)
        session.flush()
        session.add(
            PredictionOutcome(
                settlement_id=settlement.id,
                model_prediction_id=model_prediction.id,
                finish_position=1,
                is_scored=True,
                win=True,
                top2=True,
                top3=True,
                win_log_loss=0.0,
            )
        )
        session.commit()
    return factory


def test_dashboard_renders_schedule_and_result(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        response = client.get("/?date=2026-08-21&meet=2")

    assert response.status_code == 200
    assert "<title>마필로그 | Mapilog 경마 분석 및 예측</title>" in response.text
    assert 'property="og:title" content="마필로그 | Mapilog 경마 분석 및 예측"' in response.text
    assert 'property="og:site_name" content="마필로그 Mapilog"' in response.text
    assert (
        'property="og:description" content="한국 경마 일정과 결과를 확인하고 '
        '출전마 기록과 예측 확률을 분석하는 마필로그 Mapilog"'
    ) in response.text
    assert 'name="twitter:card" content="summary"' in response.text
    assert "경주 일정과 결과" in response.text
    assert 'aria-label="선택일 요약"' not in response.text
    assert "제주 1R" in response.text
    assert "바람의별" in response.text
    assert response.text.index("제주 1R") < response.text.index('class="entry-table"')
    assert "출전마 및 결과" not in response.text
    assert "4세" in response.text
    assert "1:15.2" in response.text
    assert "2.1" in response.text
    assert ">착차<" in response.text
    assert ">상금<" not in response.text
    assert 'href="/horses/003001"' in response.text
    assert 'href="/jockeys/080101"' in response.text
    assert 'href="/trainers/070101"' in response.text
    assert 'href="/owners/050101"' in response.text
    assert "이마주" in response.text
    assert 'href="/races/1"' in response.text
    assert "경주 상세 보기" in response.text
    assert 'data-calendar-modal' in response.text
    assert 'data-calendar-open' in response.text
    assert 'data-calendar-value' in response.text
    assert '"date": "2026-08-21", "status": "completed"' in response.text
    assert (
        '"date": "2026-08-13", "status": "trial-only", '
        '"hasRace": false, "hasTrial": true'
    ) in response.text
    assert '<select name="date"' not in response.text
    assert 'href="/horses/003001"' in response.text
    assert "출전제외" in response.text
    assert "제6등급" in response.text
    assert "silk-1" in response.text


def test_scheduled_entry_table_has_preview_columns_and_completed_table_keeps_results(
    tmp_path: Path,
) -> None:
    factory = seeded_session(tmp_path)
    with TestClient(create_app(factory)) as client:
        completed = client.get("/?date=2026-08-21&race_id=1&meet=2")
    completed_head = completed.text.split('<table class="entry-table"', 1)[1].split(
        "</thead>", 1
    )[0]
    assert ">마체중<" in completed_head
    assert ">착차<" in completed_head
    with factory() as session:
        race = session.get(Race, 1)
        race.status = "scheduled"
        race.entries[0].equipment_card_raw = "망사눈가면+, 혀보정끈- <장구&>"
        session.commit()
    with TestClient(create_app(factory)) as client:
        home = client.get("/?date=2026-08-21&race_id=1&meet=2")
        detail = client.get("/races/1")
    for response in (home, detail):
        assert response.status_code == 200
        table = response.text.split('<table class="entry-table scheduled-entry-table"', 1)[1]
        table = table.split("</table>", 1)[0]
        head = table.split("</thead>", 1)[0]
        names = ["부담중량", "출전주기", "장구현황", "조교횟수", "레이팅"]
        assert [head.index(name) for name in names] == sorted(head.index(n) for n in names)
        assert all(f">{name}<" not in head for name in ["마체중", "기록", "착차", "단승", "연승"])
        assert '<span class="equipment-added">망사눈가면+</span>' in table
        assert '<span class="equipment-removed">혀보정끈-</span>' in table
        assert '&lt;장구&amp;&gt;' in table
        assert 'title="최근 1개월 · 경주일 기준, 경주 당일 제외 · 수집된 조교 세션 수"' in head
        assert '<small>최근 1개월</small>' not in head
        assert "<장구&>" not in table


def test_entry_table_truncates_owner_names_with_escaped_full_label(tmp_path: Path) -> None:
    factory = seeded_session(tmp_path)
    full_name = "베스트샤인조합 <대표&>"
    escaped_name = "베스트샤인조합 &lt;대표&amp;&gt;"
    with factory() as session:
        owner = session.query(Owner).filter_by(kra_owner_id="050101").one()
        owner.name_ko = full_name
        race = session.get(Race, 1)
        assert race is not None
        unowned_horse = Horse(kra_horse_id="ui-ownerless-test", name_ko="마주 없음")
        session.add(unowned_horse)
        session.flush()
        session.add(RaceEntry(race=race, horse=unowned_horse, horse_number=2))
        session.commit()

    with TestClient(create_app(factory)) as client:
        home = client.get("/?date=2026-08-21&meet=2")
        detail = client.get("/races/1")

    assert home.status_code == detail.status_code == 200
    for page in (home, detail):
        cell_start = page.text.index(f'<td data-sort-value="{escaped_name}">')
        cell_end = page.text.index("</td>", cell_start)
        owner_cell = " ".join(page.text[cell_start:cell_end].split())
        assert (
            f'href="/owners/050101" aria-label="{escaped_name}"'
        ) in owner_cell
        assert f'class="owner-name-full" aria-hidden="true">{escaped_name}</span>' in owner_cell
        assert "베스트샤인…" in owner_cell
        assert 'title=' not in owner_cell
        missing_owner_start = page.text.index('<td data-sort-value="—">')
        missing_owner_end = page.text.index("</td>", missing_owner_start)
        missing_owner_cell = page.text[missing_owner_start:missing_owner_end]
        assert 'class="owner-name owner-name-static" role="group" tabindex="0"' in missing_owner_cell
        assert 'aria-label="—"' in missing_owner_cell
        assert 'class="owner-name-full" aria-hidden="true">—</span>' in missing_owner_cell


def test_dashboard_condition_uses_grade_and_preserves_special_race_name(
    tmp_path: Path,
) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        seoul = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        special = Race(
            racecourse=seoul,
            race_date_local=date(2026, 8, 21),
            race_number=1,
            distance_m=1200,
            grade="국OPEN",
            race_name="대상경주 특별명",
            scheduled_at_ms=_seoul_ms(10, 35),
            status="scheduled",
        )
        regular = Race(
            racecourse=seoul,
            race_date_local=date(2026, 8, 21),
            race_number=2,
            distance_m=1400,
            grade="5등급",
            race_name="일반",
            scheduled_at_ms=_seoul_ms(11, 0),
            status="scheduled",
        )
        ungraded = Race(
            racecourse=seoul,
            race_date_local=date(2026, 8, 21),
            race_number=3,
            distance_m=1600,
            grade=None,
            race_name="일반",
            scheduled_at_ms=_seoul_ms(11, 25),
            status="scheduled",
        )
        session.add_all([seoul, special, regular, ungraded])
        session.flush()
        special_race_id = special.id
        session.commit()

    with TestClient(create_app(factory)) as client:
        desktop = client.get("/?date=2026-08-21&meet=1")
        detail = client.get(f"/races/{special_race_id}")
        mobile = client.get("/?date=2026-08-21&meet=1", headers=PHONE_HEADERS)

    assert desktop.status_code == detail.status_code == mobile.status_code == 200
    official_table = desktop.text.split('<table class="race-table">', 1)[1].split(
        "</tbody>", 1
    )[0]

    def condition_for(race_label: str) -> str:
        row = next(row for row in official_table.split("<tr") if race_label in row)
        cells = [
            cell.split(">", 1)[1].split("</td>", 1)[0]
            for cell in row.split("<td")[1:]
        ]
        assert len(cells) == 5
        return cells[2].strip()

    assert condition_for("서울 1R") == "국OPEN"
    assert condition_for("서울 2R") == "5등급"
    assert condition_for("서울 3R") == "등급 미제공"
    assert "대상경주 특별명" in detail.text
    assert "국OPEN" in detail.text
    assert "대상경주 특별명" in mobile.text
    special_row = next(
        row for row in official_table.split("<tr")
        if f'data-dashboard-race-id="{special_race_id}"' in row
    )
    assert f'data-href="/?date=2026-08-21&amp;meet=1&amp;race_id={special_race_id}"' in special_row
    assert f'href="/?date=2026-08-21&amp;meet=1&amp;race_id={special_race_id}" data-dashboard-race-select' in special_row
    assert f'data-race-detail-href="/races/{special_race_id}"' in special_row
    assert f'data-dashboard-detail data-race-id="{special_race_id}"' in desktop.text
    assert f'href="/races/{special_race_id}"' in desktop.text
    assert 'class="entry-table scheduled-entry-table" data-sortable' in desktop.text


def test_race_detail_page_shows_results_and_sections(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        response = client.get("/races/1")
        missing = client.get("/races/999")

    assert response.status_code == 200
    assert "제주 1R" in response.text
    assert 'data-racecourse-map="jeju"' in response.text
    assert 'data-course-explorer data-distance="900"' in response.text
    assert 'class="course-record-layout"' not in response.text
    assert 'class="course-method"' not in response.text
    assert "제주 경주로 · 900m 주행 경로" in response.text
    assert "출전마 및 결과" in response.text
    assert "구간기록 · 전개" in response.text
    assert 'aria-label="전개 구간 경주로 위치"' in response.text
    assert 'data-passing-map-codes="FIN"' in response.text
    assert 'data-passing-map-title' in response.text
    assert "이전 경주" in response.text
    assert "다음 경주" in response.text
    assert 'id="section-chart-data"' in response.text
    assert "data-section-chart" in response.text
    assert "바람의별" in response.text
    assert "S1F" in response.text
    assert "G1F" in response.text
    assert "FIN" in response.text
    assert ">구간<" in response.text
    assert "출발부터 누적" in response.text
    assert "말별 구간 주파기록" in response.text
    assert "마지막 600m" in response.text
    assert "마지막 200m" in response.text
    assert "13.5초" in response.text
    assert "동일 지점" in response.text
    assert "1위" in response.text
    assert "원자료 통과순위 미제공 · 누적시간 기준 보완" in response.text
    assert "<sup>*</sup>" in response.text
    assert "출전제외" in response.text
    assert "94위" not in response.text
    assert "복승" in response.text
    assert "8.4" in response.text
    assert 'href="/races/2"' in response.text
    assert missing.status_code == 404


@pytest.mark.parametrize(("tab", "expected"), [
    ("result", "result"), ("course", "course"), ("sections", "sections"),
    ("not-a-tab", "result"),
])
def test_race_detail_tabs_render_one_visible_pane_and_keep_legacy_anchors(
    tmp_path: Path, tab: str, expected: str,
) -> None:
    from bs4 import BeautifulSoup

    with TestClient(create_app(seeded_session(tmp_path))) as client:
        response = client.get("/races/1", params={"tab": tab, "layout": "desktop"})
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")
    panes = soup.select("[data-race-detail-pane]")
    assert [p["data-race-detail-pane"] for p in panes if not p.has_attr("hidden")] == [expected]
    current = soup.select_one('[data-race-detail-tab][aria-current="page"]')
    assert current["data-race-detail-tab"] == expected
    assert soup.select_one("#racecourse-map") is not None
    assert soup.select_one("#race-sections") is not None
    assert soup.select_one(".race-detail-hero .page-toc") is None
    assert soup.select_one('[data-race-detail-tab="training"]') is None
    assert soup.select_one('[data-race-detail-tab="medical"]') is None


@pytest.mark.parametrize("tab", ["training", "medical"])
def test_scheduled_race_care_tabs_show_only_pre_race_records(tmp_path: Path, tab: str) -> None:
    from bs4 import BeautifulSoup

    factory = seeded_session(tmp_path)
    with factory() as session:
        session.get(Race, 1).status = "scheduled"
        for day, label in (
            (date(2026, 7, 24), "경계조교"),
            (date(2026, 7, 23), "기간밖조교"),
            (date(2026, 8, 21), "경주당일조교"),
            (date(2026, 8, 22), "경주이후조교"),
        ):
            session.add(HorseTraining(
                horse_id=1, meet_code=2, training_date_local=day,
                trainer_name=label, duration_seconds=0, canter_count=0,
                observed_at_ms=1,
            ))
        session.add(HorseStartTraining(
            horse_id=1, meet_code=2, training_date_local=date(2026, 8, 20),
            rider_name="출발기수", remark="양호", location_raw="출발대", observed_at_ms=1,
        ))
        for day, diagnosis in (
            (date(2026, 5, 23), '경계진료<script>alert("test")</script>'),
            (date(2026, 5, 22), "기간밖진료"),
            (date(2026, 8, 21), "경주당일진료"),
            (date(2026, 8, 22), "경주이후진료"),
        ):
            session.add(HorseMedical(
                horse_id=1, meet_code=2, clinic_date_local=day,
                diagnosis_1=diagnosis, observed_at_ms=1,
            ))
        session.commit()
    with TestClient(create_app(factory)) as client:
        response = client.get(f"/races/1?layout=desktop&tab={tab}")
        mobile = client.get(f"/races/1?layout=mobile&tab={tab}")
    assert response.status_code == 200
    doc = BeautifulSoup(response.text, "html.parser")
    assert doc.select_one('[data-race-detail-tab][aria-current="page"]')["data-race-detail-tab"] == tab
    assert [p["data-race-detail-pane"] for p in doc.select('[data-race-detail-pane]') if not p.has_attr("hidden")] == [tab]
    training = doc.select_one('#race-detail-pane-training')
    medical = doc.select_one('#race-detail-pane-medical')
    assert [int(row["data-care-horse"]) for row in training.select('[data-care-horse]')] == [1, 7]
    assert "경계조교" in training.get_text()
    assert "15분" in training.get_text()
    assert "출발기수" in training.get_text()
    assert "출발대" in training.get_text()
    assert "근막염" in medical.get_text()
    assert "경계진료" in medical.get_text()
    assert not medical.select('script')
    for excluded in ("기간밖조교", "경주당일조교", "경주이후조교", "기간밖진료", "경주당일진료", "경주이후진료"):
        assert excluded not in response.text
    empty_horse = medical.select_one('[data-care-horse="7"]')
    assert "이 기간에 수집된 진료 기록이 없습니다." in empty_horse.get_text()
    assert 'href="/horses/003001"' in str(training)
    assert mobile.status_code == 200
    assert 'class="mobile-app ' in mobile.text
    assert 'data-race-detail-tab="training"' not in mobile.text


def test_scheduled_race_care_excludes_not_yet_occurred_days(tmp_path: Path, monkeypatch) -> None:
    from horse_racing.web.race_care import load_race_care

    monkeypatch.setattr("horse_racing.web.race_care.today_seoul", lambda: date(2026, 8, 18))
    factory = seeded_session(tmp_path)
    with factory() as session:
        race = session.get(Race, 1)
        race.status = "scheduled"
        care = load_race_care(session, race)
    assert care["through"] == "2026-08-18"
    assert not care["horses"][0]["training"]  # Existing session is August 19.
    assert care["horses"][0]["medical"][0]["date"] == "2026-08-10"


@pytest.mark.parametrize(("meet", "name", "distance"), [
    (1, "서울", 1000), (2, "제주", 1200), (3, "부경", 1600),
])
def test_passing_course_map_uses_each_regions_existing_geometry(
    tmp_path: Path, meet: int, name: str, distance: int,
) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        race = session.get(Race, 1)
        race.racecourse.kra_meet_code = meet
        race.racecourse.name_ko = name
        race.distance_m = distance
        session.commit()
    with TestClient(create_app(factory)) as client:
        response = client.get("/races/1")
    assert response.status_code == 200
    mini = response.text.split('<aside class="passing-course-panel"', 1)[1].split("</aside>", 1)[0]
    assert f'aria-label="{name} 경주로의 선택 구간 위치"' in mini
    assert 'data-passing-map-codes="FIN"' in mini
    assert re.search(r'data-passing-map-codes="[^"]*S1F', mini)
    assert 'class="passing-map-route" d="M' in mini
    assert 'data-passing-map-title' in mini


def test_running_trial_appears_in_calendar_and_has_race_like_detail_page(
    tmp_path: Path,
) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        dashboard = client.get("/?date=2026-08-13&meet=2")
        detail = client.get("/running-trials/1")
        missing = client.get("/running-trials/999")

    assert dashboard.status_code == 200
    assert 'aria-label="경주 일정"' in dashboard.text
    assert "제주 2R" in dashboard.text
    assert "예측 대상 제외" in dashboard.text
    assert 'href="/running-trials/1"' in dashboard.text
    trial_header = dashboard.text.split(
        '<table class="race-table trial-card-table">', 1
    )[1].split("</thead>", 1)[0]
    assert trial_header.count("<th>") == 6
    assert detail.status_code == 200
    assert "주행심사 결과" in detail.text
    assert "예측 대상 아님 · 과거 변수로만 사용" in detail.text
    assert "바람의별" in detail.text
    assert "합격" in detail.text
    assert "1:07.1" in detail.text
    assert "S1F" in detail.text
    assert "18.1초" in detail.text
    assert "주행미합(신)" in detail.text
    assert missing.status_code == 404


def test_data_status_page_is_unavailable(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        response = client.get("/data-status")

    assert response.status_code == 404


def test_prediction_ledger_page_removed_api_preserved(
    tmp_path: Path,
) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        page = client.get("/predictions")
        api = client.get("/api/predictions")

    assert page.status_code == 404
    assert api.status_code == 200
    payload = api.json()
    assert payload["prospective"]["publications"] == 1
    assert payload["prospective"]["settlements"] == 1
    assert payload["prospective"]["scored_races"] == 1
    assert payload["runs"][0]["mode"] == "live"


def test_forecast_and_validation_pages_are_unavailable(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        forecast = client.get("/forecast?date=2026-08-21&race_id=1")
        validation = client.get("/validation")

    assert forecast.status_code == 404
    assert validation.status_code == 404


def test_jeju_distance_page_uses_portable_year_extraction(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        response = client.get("/racecourses/jeju/distances")

    assert response.status_code == 200
    assert "제주" in response.text
    assert 'data-course-view-tabs data-course="jeju"' in response.text
    assert 'href="/racecourses/jeju/course" data-course-view-link data-course="jeju" data-course-view="course"' in response.text


def test_analysis_workspace_filters_exports_and_rejects_invalid_range(
    tmp_path: Path,
) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        page = client.get("/analysis?start=2026-08-01&end=2026-08-31&horse=1")
        exported = client.get("/api/analysis/export.csv?start=2026-08-01&end=2026-08-31&horse=1")
        invalid = client.get("/analysis?start=2026-09-01&end=2026-08-01")
        race_analysis_css = client.get("/static/css/race-analysis.css")
        empty_meet = client.get("/analysis?date=2026-08-21&meet=1")

    assert page.status_code == 200
    assert "경주 분석" in page.text
    assert "내 분석" not in page.text
    assert "바람의별" in page.text
    assert "경주 메모" not in page.text
    assert "말별 기록과 영상" not in page.text
    assert "출전마 비교" in page.text
    assert "수집된 과거 경주 기록이 없습니다" not in page.text
    assert 'data-selected-race-id="1"' in page.text
    assert "ra-selection-note" not in page.text
    assert "가장 가까운 공개 경주일" not in page.text
    assert "이전 기록 기준" not in page.text
    assert "공식 출전표와 불변 원장에 발행된 예측만 표시합니다." not in page.text
    assert re.search(r"/static/css/race-analysis\.css\?v=\d+", page.text)
    assert 'data-calendar-open' in page.text
    assert 'data-calendar-modal' in page.text
    assert 'data-calendar-value' in page.text
    assert 'class="schedule-date-nav"' in page.text
    assert 'class="ra-date-form filters schedule-toolbar" data-filter-form' in page.text
    assert 'id="analysis-date"' not in page.text
    meet_nav_start = page.text.index('<nav class="ra-meets schedule-venue-filter"')
    meet_nav_end = page.text.index("</nav>", meet_nav_start)
    meet_nav = page.text[meet_nav_start:meet_nav_end]
    meet_order = [
        name for name in ("서울", "부산", "영천", "제주") if f">{name}</a>" in meet_nav
    ]
    assert meet_order == ["제주"]
    assert 'class="schedule-venue-button"' in meet_nav
    assert "부산경남" not in meet_nav
    assert 'aria-current="page"' in meet_nav
    assert race_analysis_css.status_code == 200
    active_round_rule = race_analysis_css.text.split(
        ".ra-rounds a.active {", maxsplit=1
    )[1].split("}", maxsplit=1)[0]
    assert "box-shadow" not in active_round_rule
    assert "background:var(--accent-soft)" in active_round_rule
    assert "border-color:var(--accent-line)" in active_round_rule
    assert "미래 경주 예측" not in page.text
    assert "예상 전개 탐색" not in page.text
    assert "SCENARIO, NOT OBSERVATION" not in page.text
    assert 'data-pace-root' not in page.text
    assert 'data-pace-data' not in page.text
    assert 'data-highlight="' not in page.text
    assert "전개 그리기" in page.text
    assert "출전마 비교" in page.text
    assert 'class="model-receipt"' not in page.text
    assert "100.0%" in page.text
    assert "모델 예측 ↗" not in page.text
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert "track_condition" in exported.text
    assert "S1F" in exported.text
    assert invalid.status_code == 422
    assert empty_meet.status_code == 200
    assert 'href="/analysis?date=2026-08-21&meet=1"' not in empty_meet.text
    assert 'name="meet" value="1"' in empty_meet.text
    assert "선택한 날짜·경기장의 출전표가 없습니다." in empty_meet.text
    assert 'class="ra-rounds"' not in empty_meet.text
    assert 'data-selected-race-id="1"' not in empty_meet.text


def test_analysis_tabs_support_direct_links_and_preserve_race_navigation(
    tmp_path: Path, paced_requests,
) -> None:
    from bs4 import BeautifulSoup

    tabs = {"forecast", "wagers", "field", "records", "overview", "pace", "memo"}
    with TestClient(create_app(seeded_session(tmp_path))) as client:
        for requested in [*sorted(tabs), "unknown"]:
            response = client.get(f"/analysis?race_id=1&history_limit=60&tab={requested}")
            assert response.status_code == 200
            document = BeautifulSoup(response.text, "html.parser")
            selected = requested if requested in tabs else "forecast"
            panes = document.select("[data-analysis-pane]")
            assert {pane["data-analysis-pane"] for pane in panes} == tabs
            visible = [pane["data-analysis-pane"] for pane in panes if not pane.has_attr("hidden")]
            assert visible == [selected]
            active = document.select_one('.ra-section-nav [aria-current="page"]')
            assert active["data-analysis-tab"] == selected
            for link in document.select("[data-analysis-tab]"):
                assert "race_id=1" in link["href"]
                assert "history_limit=60" in link["href"]
                assert f'tab={link["data-analysis-tab"]}' in link["href"]
                assert document.find(id=link["aria-controls"]) is not None
            assert document.select_one('.ra-date-form input[name="tab"]')["value"] == selected
            for link in document.select(".ra-browser a[href]"):
                assert f"tab={selected}" in link["href"]
            for pane in panes:
                if pane.has_attr("hidden"):
                    assert not pane.get_text(strip=True)
                    assert not pane.find("table")
            if selected == "records":
                assert document.select_one('.ra-history-filter input[name="tab"]')["value"] == "records"
            if selected == "field":
                rail = document.select_one('[data-field-list]')
                choices = rail.select('[data-field-select]')
                assert choices
                assert len(choices) == len(rail.select('[data-compare-entry]'))
                numbers = [int(row['data-number']) for row in rail.select('[data-field-entry]')]
                assert numbers == sorted(numbers)
                assert all(button['aria-controls'] == 'field-runner-summary' for button in choices)
                assert document.find(id='field-runner-summary') is not None
                assert document.select_one('[data-field-mode="single"]')['aria-pressed'] == 'true'
                assert document.select_one('[data-field-mode="compare"]').has_attr('disabled')
                assert document.select_one('[data-field-table]') is None


def test_analysis_all_records_uses_one_table_with_section_columns_and_inline_video(
    tmp_path: Path,
) -> None:
    from bs4 import BeautifulSoup

    factory = seeded_session(tmp_path)
    with factory() as session:
        busan = Racecourse(kra_meet_code=3, code="BUSAN", name_ko="부산")
        session.add(busan)
        for day in [date(2026, 7, 14), date(2026, 8, 14)]:
            past = Race(
                racecourse=busan, race_date_local=day, race_number=3,
                distance_m=1400, grade="국6등급", status="completed", field_size=10,
                weather="맑음", track_condition="건조",
            )
            past_entry = RaceEntry(race=past, horse_id=1, horse_number=4)
            session.add_all([
                past, past_entry,
                RaceResult(race_entry=past_entry, finish_position=2, finish_time_ms=90_000),
                RaceSectionResult(
                    race_entry=past_entry, section_code="G6F", elapsed_time_ms=28_000,
                    position=4, time_basis="cumulative",
                ),
                RaceSectionResult(
                    race_entry=past_entry, section_code="G3F", elapsed_time_ms=55_000,
                    position=3, time_basis="cumulative",
                ),
                RaceSectionResult(
                    race_entry=past_entry, section_code="G1F", elapsed_time_ms=16_000,
                    position=2, time_basis="closing",
                ),
                RaceSectionResult(
                    race_entry=past_entry, section_code="S1F", elapsed_time_ms=15_000,
                    position=5, time_basis=None,
                ),
            ])
        session.get(RunningTrialResult, 1).passing_order_raw = "2-1-1"
        session.commit()

    with TestClient(create_app(factory)) as client:
        response = client.get("/analysis?race_id=1&tab=overview")
        field_response = client.get("/analysis?race_id=1&tab=field")
    assert field_response.status_code == 200
    field_document = BeautifulSoup(field_response.text, "html.parser")
    field_payload = json.loads(field_document.find(id="race-study-data").string)
    recent = field_payload["runners"][0]["history"][0]
    assert recent["horse_number"] == 4
    assert recent["condition"] == "맑음 · 건조"
    assert {"meet", "race_number", "jockey", "carried_weight", "body_weight", "field_size"} <= recent.keys()
    assert set(recent["section_details"]) == {"S1F", "G3F", "G1F"}
    assert recent["section_details"]["G3F"]["time_ms"] == 35_000
    assert recent["section_details"]["S1F"]["raw_time_ms"] == 15_000
    assert response.status_code == 200
    document = BeautifulSoup(response.text, "html.parser")
    pane = document.select_one('[data-analysis-pane="overview"]')
    assert not pane.has_attr("hidden")
    horses = pane.select("[data-all-records-horse]")
    assert [card["data-all-records-horse"] for card in horses] == ["1", "7"]
    horse_link = horses[0].select_one(".ra-all-records-identity a")
    assert horse_link["href"] == "/horses/003001?tab=records"
    assert len(pane.select("table")) == 1
    headers = [cell.get_text(strip=True) for cell in pane.select("thead th")]
    assert headers[:9] == ["마명", "경주일 · 영상", "조건", "거리", "기수", "부중", "순위", "체중", "기록"]
    assert horses[0].select_one('th[scope="rowgroup"]')["rowspan"] == "3"
    assert len(horses[0].select('th[scope="rowgroup"]')) == 1
    assert headers[-1] == "구간착순"
    assert "영상" not in headers
    combined_dates = [
        row.select_one(".ra-all-records-date-line").get_text(strip=True)[:10]
        for row in horses[0].select("tr[data-all-records-kind]")
    ]
    assert combined_dates == [
        "2026-08-14", "2026-08-13", "2026-07-14",
    ]
    races = horses[0].select('tr[data-all-records-kind="race"]')
    assert [row.select_one("td a").get_text(strip=True) for row in races] == [
        "2026-08-14", "2026-07-14",
    ]
    cells = races[0].find_all("td", recursive=False)
    assert "국6등급" in cells[1].get_text()
    assert cells[2].get_text(strip=True) == "1400m"
    assert "2위" in races[0].select_one('.ra-all-records-finish').get_text()
    assert "당시 4번" in cells[1].get_text()
    assert cells[0].select_one(".ra-video-link") is not None
    times = {cell["data-section"]: cell.get_text(strip=True)
             for cell in races[0].select("[data-section]")}
    assert times["G6F"] == "28.0"
    assert times["G3F"] == "35.0"  # Closing time, not the cumulative source value.
    assert times["G1F"] == "16.0"
    assert times["S1F"] == "15.0*"
    assert all("초" not in value for value in times.values())
    assert cells[-1].get_text(strip=True) == "5- -4- -3- -2"
    assert "S1F - G8F - G6F" in cells[-1].span["title"]
    trial = horses[0].select_one('tr[data-all-records-kind="trial"]')
    assert "2026-08-13" in trial.get_text()
    assert "합격" in trial.get_text()
    assert trial.select_one('[data-section="G6F"]').get_text(strip=True) == "—"
    assert trial.find_all("td", recursive=False)[-1].get_text(strip=True) == "2-1-1"
    assert horses[1].select("tr[data-all-records-kind]") == []
    assert "연결된 경주·주행심사 기록이 없습니다" in horses[1].get_text()
    column_count = len(headers)
    assert all(int(cell["colspan"]) + 1 == column_count for cell in pane.select("[colspan]"))


def test_analysis_field_keeps_multiple_trials_for_combined_recent_history(tmp_path: Path) -> None:
    from bs4 import BeautifulSoup

    factory = seeded_session(tmp_path)
    with factory() as session:
        session.add(RunningTrialResult(
            trial=RunningTrial(
                meet_code=2, trial_date_local=date(2026, 7, 9), trial_round=22,
                trial_race_number=1, distance_m=800, observed_at_ms=1,
            ),
            horse_id=1, horse_number=3, horse_name_raw="바람의별", finish_position=2, judgement="합",
            s1f_ms=18_000, g3f_ms=48_000, g1f_ms=16_000, observed_at_ms=1,
        ))
        session.commit()
    with TestClient(create_app(factory)) as client:
        response = client.get("/analysis?race_id=1&tab=field")
    assert response.status_code == 200
    document = BeautifulSoup(response.text, "html.parser")
    payload = json.loads(document.find(id="race-study-data").string)
    trials = payload["runners"][0]["trials"]
    assert [trial["date"] for trial in trials] == ["2026-08-13", "2026-07-09"]
    assert trials[0]["carried_weight"] == "55kg"
    assert trials[0]["judgement"] == "합격"
    assert trials[0]["section_details"]["G3F"]["time_ms"] == 49_000
    assert all("video_url" in trial for trial in trials)


def test_analysis_busan_csv_uses_course_sections_and_preserves_unverified_raw_time(
    tmp_path: Path,
) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        course = Racecourse(kra_meet_code=3, code="BUSAN", name_ko="부경")
        horse = Horse(kra_horse_id="BUSAN-CSV-1", name_ko="부경검증마", meet_code=3)
        past = Race(
            racecourse=course,
            race_date_local=date(2026, 9, 11),
            race_number=1,
            distance_m=1400,
            field_size=10,
            status="completed",
        )
        upcoming = Race(
            racecourse=course,
            race_date_local=date(2026, 9, 19),
            race_number=1,
            distance_m=1400,
            status="scheduled",
        )
        prior_entry = RaceEntry(race=past, horse=horse, horse_number=1)
        session.add_all(
            [
                RaceEntry(race=upcoming, horse=horse, horse_number=1),
                RaceResult(
                    race_entry=prior_entry, finish_position=2, finish_time_ms=87_200
                ),
                RaceSectionResult(
                    race_entry=prior_entry,
                    section_code="G6F",
                    elapsed_time_ms=19_400,
                    position=3,
                    time_basis=None,
                ),
                RaceSectionResult(
                    race_entry=prior_entry,
                    section_code="G3F",
                    elapsed_time_ms=36_400,
                    position=2,
                    time_basis="closing",
                ),
            ]
        )
        session.commit()
        race_id = upcoming.id

    with TestClient(create_app(factory)) as client:
        response = client.get(f"/api/analysis/export.csv?race_id={race_id}")

    assert response.status_code == 200
    reader = csv.DictReader(StringIO(response.text))
    assert reader.fieldnames is not None
    assert reader.fieldnames[-7:] == ["S1F", "G8F", "G6F", "G4F", "G3F", "G2F", "G1F"]
    assert not {"1C", "2C", "3C", "4C"}.intersection(reader.fieldnames)
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["horse"] == "부경검증마"
    assert rows[0]["G8F"] == "—"
    assert rows[0]["G6F"].startswith("원문 ")
    assert "19.4" in rows[0]["G6F"]
    assert "기준 미확인" in rows[0]["G6F"]
    assert "36.4" in rows[0]["G3F"]
    assert "기준 미확인" not in rows[0]["G3F"]


def test_analysis_defaults_to_nearest_upcoming_race_and_allows_explicit_selection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "horse_racing.web.race_analysis.today_seoul", lambda: date(2099, 9, 18)
    )
    factory = seeded_session(tmp_path)
    early_start = int(
        datetime(2099, 9, 18, 10, 50, tzinfo=ZoneInfo("Asia/Seoul")).timestamp() * 1000
    )
    late_start = int(
        datetime(2099, 9, 18, 11, 40, tzinfo=ZoneInfo("Asia/Seoul")).timestamp() * 1000
    )
    with factory() as session:
        course = session.query(Racecourse).filter_by(kra_meet_code=2).one()
        horse = session.query(Horse).filter_by(name_ko="바람의별").one()
        jockey = session.query(Jockey).filter_by(name_ko="한기수").one()
        trainer = session.query(Trainer).filter_by(name_ko="김조교").one()
        first = Race(
            racecourse=course,
            race_date_local=date(2099, 9, 18),
            race_number=1,
            distance_m=900,
            grade="제6등급",
            scheduled_at_ms=early_start,
            status="scheduled",
        )
        second = Race(
            racecourse=course,
            race_date_local=date(2099, 9, 18),
            race_number=2,
            distance_m=1000,
            grade="제5등급",
            scheduled_at_ms=late_start,
            status="scheduled",
        )
        session.add_all(
            [
                RaceEntry(
                    race=first,
                    horse=horse,
                    jockey=jockey,
                    trainer=trainer,
                    horse_number=1,
                    gate_number=1,
                    carried_weight_kg=55,
                ),
                RaceEntry(
                    race=second,
                    horse=horse,
                    jockey=jockey,
                    trainer=trainer,
                    horse_number=2,
                    gate_number=2,
                    carried_weight_kg=55,
                ),
            ]
        )
        session.commit()
        first_id = first.id
        second_id = second.id

    app = create_app(session_factory=factory)
    with TestClient(app) as client:
        default_page = client.get("/analysis")
        explicit_page = client.get(f"/analysis?race_id={second_id}")

    assert default_page.status_code == 200
    assert f'data-selected-race-id="{first_id}"' in default_page.text
    assert "2099-09-18 · 10:50 · 제주" in default_page.text
    assert "날씨·주로·함수율" not in default_page.text
    assert "S1F" not in default_page.text
    assert f'data-selected-race-id="{second_id}"' in explicit_page.text


def test_section_chart_data_includes_finish_checkpoint() -> None:
    from horse_racing.web.race_page import (
        SectionCell,
        SectionColumn,
        SectionEntryRow,
        build_section_chart_data,
        derive_section_cumulative_times,
    )

    columns = [
        SectionColumn(code="S1F", label="S1F"),
        SectionColumn(code="G1F", label="G1F"),
        SectionColumn(code="FIN", label="FIN"),
    ]
    rows = [
        SectionEntryRow(
            horse_id=1,
            horse_number=4,
            horse_name="테스트마",
            finish_position="2위",
            finish_sort=2,
            cells=[
                SectionCell(
                    position="3위",
                    segment_time="13.0초",
                    cumulative_time="13.0초",
                    sort_position=3,
                    position_inferred=False,
                ),
                SectionCell(
                    position="2위",
                    segment_time="47.0초",
                    cumulative_time="1:00.0",
                    sort_position=2,
                    position_inferred=False,
                ),
                SectionCell(
                    position="2위",
                    segment_time="13.0초",
                    cumulative_time="1:13.0",
                    sort_position=2,
                    position_inferred=False,
                ),
            ],
        )
    ]
    chart = build_section_chart_data(columns, rows)
    assert chart["labels"] == ["S1F", "G1F", "FIN"]
    assert chart["series"][0]["positions"] == [3, 2, 2]
    assert chart["maxPosition"] == 3

    assert derive_section_cumulative_times(
        {"S1F": 13_900, "G3F": 24_600, "G1F": 48_400},
        finish_time_ms=60_800,
        meet_code=1,
    ) == {"S1F": 13_900, "G3F": 24_600, "G1F": 48_400}
    assert derive_section_cumulative_times(
        {"S1F": 17_700, "G3F": 49_800, "G1F": 17_300},
        finish_time_ms=75_700,
        meet_code=2,
    ) == {"S1F": 17_700, "G3F": 25_900, "G1F": 58_400}
    assert derive_section_cumulative_times(
        {"S1F": 13_000, "G1F": 12_500},
        finish_time_ms=70_000,
        meet_code=1,
    ) == {"S1F": 13_000, "G1F": 57_500}


def test_dashboard_health_check(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        response = client.get("/health")
        readiness = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert readiness.status_code == 200
    assert readiness.json() == {"status": "ready"}


def test_public_guide_and_privacy_pages_render_without_database(monkeypatch) -> None:
    monkeypatch.delenv("MAPILOG_OPERATOR_NAME", raising=False)
    monkeypatch.delenv("MAPILOG_CONTACT_EMAIL", raising=False)

    def unexpected_database_access():
        raise AssertionError("public information pages must not open a database session")

    with TestClient(create_app(session_factory=unexpected_database_access)) as client:
        guide = client.get("/guide")
        mobile_guide = client.get("/guide", headers=PHONE_HEADERS)
        privacy = client.get("/privacy")
        layout_mobile = client.get("/guide?layout=mobile")
        layout_desktop = client.get("/privacy?layout=desktop", headers=PHONE_HEADERS)
        invalid_layout = client.get("/guide?layout=tablet")

    assert all(
        response.status_code == 200
        for response in (guide, mobile_guide, privacy, layout_mobile, layout_desktop)
    )
    assert invalid_layout.status_code == 422
    for response in (guide, mobile_guide, privacy):
        assert response.headers["cache-control"] == "private, no-store"
        assert {"cookie", "user-agent"} <= {
            value.strip().lower() for value in response.headers["vary"].split(",")
        }
    assert 'data-layout="mobile"' in layout_mobile.text
    assert "hr-layout=mobile" in layout_mobile.headers["set-cookie"]
    assert 'data-layout="desktop"' in layout_desktop.text
    assert "hr-layout=desktop" in layout_desktop.headers["set-cookie"]
    assert 'href="/guide"' in guide.text and 'href="/privacy"' in guide.text
    assert "3위 안에 들 확률" in guide.text
    assert "약 300%" in guide.text
    assert "정확히 2·3위에 들 확률" in guide.text
    assert "후착후보" in guide.text
    assert "즐겨찾기" in guide.text and "홈 화면" in guide.text
    assert "생성 시점" in guide.text and "보장하지 않습니다" in guide.text
    assert 'class="mobile-app public-info-page"' in mobile_guide.text
    assert "김용진" in privacy.text
    assert 'href="mailto:mapilog@mapilog.xyz"' in privacy.text
    assert 'content="noindex,follow"' in privacy.text
    assert "개인정보처리방침" in privacy.text
    assert "일반 접속 기록:</strong> 30일 보관한 뒤" in privacy.text
    assert "관리자·시스템 보안 기록:</strong> 400일 보관" in privacy.text
    assert "수신일부터 7일간 보관한 뒤 파기합니다" in privacy.text
    assert "담당자가 보유 기간에 맞춰 삭제합니다" in privacy.text
    assert "개인정보 열람·정정·삭제·처리정지 요청" in privacy.text
    assert "게시 전 검토본" not in privacy.text


def test_public_contact_email_validation_and_draft_noindex(monkeypatch) -> None:
    monkeypatch.setenv("MAPILOG_OPERATOR_NAME", "김용진")
    monkeypatch.setenv("MAPILOG_CONTACT_EMAIL", "owner@example.com?subject=<script>")

    with TestClient(create_app()) as client:
        privacy = client.get("/privacy")

    assert privacy.status_code == 200
    assert 'content="noindex,follow"' in privacy.text
    assert "이메일 문의처는 현재 준비 중입니다" in privacy.text
    assert "owner@example.com" not in privacy.text
    assert 'href="mailto:' not in privacy.text


def test_public_operator_name_is_html_escaped(monkeypatch) -> None:
    monkeypatch.setenv("MAPILOG_OPERATOR_NAME", "<img src=x onerror=alert(1)>")
    monkeypatch.setenv("MAPILOG_CONTACT_EMAIL", "owner@example.com")

    with TestClient(create_app()) as client:
        privacy = client.get("/privacy")

    assert privacy.status_code == 200
    assert '<img src=x onerror=alert(1)>' not in privacy.text
    assert "&lt;img src=x onerror=alert(1)&gt;" in privacy.text


def test_official_cap_colors_are_used_for_horse_number_badges(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        css = client.get("/static/css/dashboard.css")
        page = client.get("/races/1")

    assert css.status_code == 200
    assert ".silk-2 { background: #f4c430" in css.text
    assert ".silk-4 { background: #1a1a1a" in css.text
    assert ".silk-5 { background: #1f5fbf" in css.text
    assert ".silk-7 { background: #7c2d26" in css.text
    assert ".silk-8 { background: #ef7eb2" in css.text
    assert ".silk-11 {" in css.text
    assert "repeating-linear-gradient" in css.text
    assert '.race-hero[data-racecourse="서울"]' in css.text
    assert '.race-hero[data-racecourse="제주"]' in css.text
    assert '.race-hero[data-racecourse="부경"]' in css.text
    assert '.race-hero[data-racecourse="영천"]' in css.text
    assert "background: linear-gradient(125deg," in css.text
    assert "#2d234b 0%, #47366f 58%, #55417c 100%);" in css.text
    assert "dashboard.css?v=78" in page.text


def test_dashboard_accepts_empty_racecourse_filter(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        response = client.get("/?date=2026-08-21&meet=")

    assert response.status_code == 200
    assert 'aria-label="당일 경마장 선택"' in response.text
    assert '<select name="meet"' not in response.text


def test_dashboard_venue_buttons_keep_all_day_options_when_filtered(tmp_path: Path) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        session.add_all([
            Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울"),
            Racecourse(kra_meet_code=3, code="BUSAN", name_ko="부산경남"),
            RunningTrial(
                meet_code=1,
                trial_date_local=date(2026, 8, 21),
                trial_round=1,
                trial_race_number=1,
                distance_m=1000,
                observed_at_ms=1,
            ),
        ])
        session.commit()

    with TestClient(create_app(factory)) as client:
        filtered = client.get("/?date=2026-08-21&meet=2")
        trial_only = client.get("/?date=2026-08-13")

    assert filtered.status_code == trial_only.status_code == 200
    buttons = filtered.text.split('aria-label="당일 경마장 선택">', 1)[1].split("</nav>", 1)[0]
    assert ">전체</a>" in buttons
    assert ">서울</a>" in buttons
    assert 'aria-current="page">제주</a>' in buttons
    assert "부산" not in buttons
    assert "영천" not in buttons
    assert 'href="/?date=2026-08-21&amp;meet=1"' in buttons
    assert 'type="hidden" name="meet" value="2"' in filtered.text
    trial_buttons = trial_only.text.split('aria-label="당일 경마장 선택">', 1)[1].split("</nav>", 1)[0]
    assert ">제주</a>" in trial_buttons
    assert "서울" not in trial_buttons


def test_layout_cookie_overrides_user_agent(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        mobile = client.get("/", headers={"cookie": "hr-layout=mobile"})
        desktop = client.get("/", headers={**PHONE_HEADERS, "cookie": "hr-layout=desktop"})

    assert 'data-layout="mobile"' in mobile.text
    assert 'class="mobile-app mobile-home"' in mobile.text
    assert 'data-layout="desktop"' in desktop.text
    assert "mobile-app" not in desktop.text
    assert mobile.headers["cache-control"] == "private, no-store"
    assert "cookie" in {part.strip().lower() for part in mobile.headers["vary"].split(",")}
    assert "_layout_switch" not in mobile.text


def test_layout_query_overrides_cookie_persists_and_auto_resets(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))
    desktop_ua = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/130.0"}

    with TestClient(app) as client:
        desktop = client.get("/?layout=desktop", headers=PHONE_HEADERS)
        persisted = client.get("/races/1", headers=PHONE_HEADERS)
        mobile_override = client.get("/analysis?layout=mobile", headers=desktop_ua)
        desktop_again = client.get("/?layout=desktop", headers=PHONE_HEADERS)
        automatic = client.get("/?layout=auto", headers=PHONE_HEADERS)
        restored = client.get("/races/1", headers=PHONE_HEADERS)
        invalid = client.get("/?layout=tablet", headers=PHONE_HEADERS)
        repeated = client.get("/?layout=mobile&layout=desktop", headers=PHONE_HEADERS)

    assert desktop.status_code == 200
    assert 'data-layout="desktop"' in desktop.text
    assert "hr-layout=desktop" in desktop.headers["set-cookie"]
    assert desktop.headers["cache-control"] == "private, no-store"
    assert "cookie" in {part.strip().lower() for part in desktop.headers["vary"].split(",")}
    assert 'data-layout="desktop"' in persisted.text
    assert persisted.headers["cache-control"] == "private, no-store"
    assert 'data-layout="mobile"' in mobile_override.text
    assert "hr-layout=mobile" in mobile_override.headers["set-cookie"]
    assert 'data-layout="desktop"' in desktop_again.text
    assert 'data-layout="mobile"' in automatic.text
    assert "Max-Age=0" in automatic.headers["set-cookie"]
    assert 'data-layout="mobile"' in restored.text
    assert invalid.status_code == 422
    assert repeated.status_code == 422


def test_desktop_user_agent_has_no_viewport_layout_switch(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))
    desktop_ua = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/130.0"}

    with TestClient(app) as client:
        response = client.get("/", headers=desktop_ua)

    assert response.status_code == 200
    assert 'data-layout="desktop"' in response.text
    assert "max-width: 1100px" not in response.text
    assert "location.reload()" not in response.text
    assert "_layout_switch" not in response.text


def test_mobile_home_lists_races_without_desktop_chrome_copy(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        page = client.get("/?date=2026-08-21&meet=2", headers=PHONE_HEADERS)
        desktop = client.get("/?date=2026-08-21&meet=2")
        css = client.get("/static/css/mobile.css")
        trials = client.get("/?date=2026-08-13&meet=2", headers=PHONE_HEADERS)
        mobile = client.get(
            "/?date=2026-08-21&meet=2",
            headers=PHONE_HEADERS,
            follow_redirects=False,
        )

    assert page.status_code == 200
    assert css.status_code == 200
    assert (
        '<meta name="naver-site-verification" '
        'content="a71202c329d9767a2c3589e8637e278720be227f">'
    ) in page.text
    assert '<link rel="canonical" href="https://mapilog.xyz/">' in page.text
    assert "mobile.css?v=84" in page.text
    assert 'data-easy-toggle' in page.text
    assert "큰글씨 모드" in page.text
    assert "mapilog-favicon-final.svg" in page.text
    assert "mapilog-favicon.png" in page.text
    assert "<title>마필로그 | Mapilog 경마 분석 및 예측</title>" in page.text
    assert 'property="og:title" content="마필로그 | Mapilog 경마 분석 및 예측"' in page.text
    assert 'aria-label="Mapilog 경주 목록 홈"' in page.text
    assert 'class="mobile-beta-badge">BETA<' in page.text
    assert "mapilog-wordmark-color.svg" in page.text
    assert "mapilog-wordmark-white.svg" in page.text
    assert 'class="mobile-app mobile-home"' in page.text
    assert 'class="mobile-race-card"' in page.text
    assert "mobile-poster" in page.text
    assert "silk-1" in page.text
    assert "mobile-poster-num" in page.text
    assert "mobile-poster-pct" in page.text
    assert "mobile-poster-role" in page.text
    assert "mobile-poster-result" in page.text
    assert ">1위<" in page.text
    assert ">1:15.2<" in page.text
    assert "100%" in page.text
    assert "강축" in page.text
    assert "입상 후보 1두" not in page.text
    assert "모델 선정 입상 후보 1두" not in page.text
    assert "mobile-poster-rank" not in page.text
    assert ">00%<" not in page.text
    assert "입상확률 높은 순" not in page.text
    assert "바람의별" in page.text
    assert 'class="mobile-race-no">제주<' in page.text
    assert 'class="mobile-round-race">1R<' in page.text
    assert 'class="mobile-round-field">1두</span>' in page.text
    assert 'aria-label="제주 1R 경주 분석 열기"' in page.text
    assert 'href="/races/1"' in page.text
    assert 'class="mobile-round-jump"' in page.text
    assert 'href="#round-1"' in page.text
    assert 'id="round-1"' in page.text
    assert 'href="/races/1#entry-' in page.text
    assert "?entry=" not in page.text
    assert "mobile-tabbar" in page.text
    assert "mobile-weekend-bar" in page.text
    assert "mobile-meet-bar" in page.text
    assert "8월 21일" in page.text
    assert "금요일" in page.text
    assert "토요일" in page.text
    assert "일요일" in page.text
    assert ">제주<" in page.text
    assert "position: sticky" in css.text
    assert 'data-mobile-menu' not in page.text
    assert "경주 분석" in page.text
    tabbar = page.text.split('class="mobile-tabbar"', 1)[1].split("</nav>", 1)[0]
    assert 'href="/"' in tabbar
    assert 'href="/analysis"' in tabbar
    assert "더비온" in tabbar
    assert "data-open-derbyon" in tabbar
    assert "m.kra.co.kr/comp/view/kraAppList.do" in tabbar
    assert 'href="/forecast"' not in tabbar
    assert 'href="/validation"' not in tabbar
    assert "주행심사 · 예측 대상 제외" in trials.text
    assert 'class="mobile-trial-summary"' in trials.text
    assert 'href="/running-trials/1"' not in trials.text
    assert desktop.status_code == 200
    assert "mobile-poster" not in desktop.text
    assert "mobile-tabbar" not in desktop.text
    assert "RACE CALENDAR" in desktop.text
    assert mobile.status_code == 200
    assert {part.strip().lower() for part in mobile.headers["vary"].split(",")} == {
        "user-agent", "accept-encoding"
    }


def test_mobile_probability_displays_zero_and_missing_values_distinctly(
    tmp_path: Path,
) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        race = session.get(Race, 1)
        run = session.get(PredictionRun, 1)
        assert race is not None and run is not None
        for number, name, probability in (
            (2, "정확한0퍼센트", 0.0),
            (3, "누락확률", None),
        ):
            horse = Horse(kra_horse_id=f"ui-probability-{number}", name_ko=name)
            entry = RaceEntry(race=race, horse=horse, horse_number=number)
            session.add_all([horse, entry])
            session.flush()
            if probability is not None:
                session.add(
                    ModelPrediction(
                        prediction_run_id=run.id,
                        race_id=race.id,
                        race_entry_id=entry.id,
                        horse_number=number,
                        prob_win=0.0,
                        prob_top2=0.0,
                        prob_top3=probability,
                    )
                )
        session.commit()

    with TestClient(create_app(factory)) as client:
        home = client.get("/?date=2026-08-21&meet=2", headers=PHONE_HEADERS)
        analysis = client.get("/races/1", headers=PHONE_HEADERS)

    assert 'mobile-poster-pct" title="3위 안 입상 확률">0%</span>' in home.text
    assert 'mobile-poster-pct" title="3위 안 입상 확률">—</span>' in home.text
    assert 'ma-win-pct" title="3위 안 입상 확률">0%</span>' in analysis.text
    assert 'ma-win-pct" title="3위 안 입상 확률">—</span>' in analysis.text
    assert ">00%<" not in home.text
    assert ">00%<" not in analysis.text


def test_phones_render_equivalent_mobile_pages_on_canonical_urls(
    tmp_path: Path, paced_requests,
) -> None:
    app = create_app(seeded_session(tmp_path))
    headers = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"}

    with TestClient(app) as client:
        for path in (
            "/?date=2026-08-21&meet=2",
            "/analysis?race_id=1",
            "/races/1",
        ):
            response = client.get(path, headers=headers, follow_redirects=False)
            assert response.status_code == 200, path
            assert 'class="mobile-app ' in response.text
            assert "dashboard.css?v=78" in response.text
            assert "mobile.css?v=84" in response.text
            assert {part.strip().lower() for part in response.headers["vary"].split(",")} == {
                "user-agent", "accept-encoding"
            }

        mobile_css = client.get("/static/css/mobile.css", headers=headers).text
        arrow_rule = mobile_css.split(".mobile-round-analysis {", maxsplit=1)[1].split(
            "}", maxsplit=1
        )[0]
        assert "background:" not in arrow_rule
        assert ".mobile-round-title > :not(.mobile-round-analysis)" not in mobile_css

        for path in (
            "/running-trials/1",
            "/racecourses/jeju/distances",
            "/horses",
            "/horses/003001",
            "/docs",
        ):
            response = client.get(path, headers=headers, follow_redirects=False)
            assert response.status_code == 200, path
            assert "location" not in response.headers, path

        legacy_home = client.get("/m?date=2026-08-21", headers=headers, follow_redirects=False)
        legacy_analysis = client.get(
            "/m/analysis?race_id=1&entry=1", headers=headers, follow_redirects=False
        )
        assert legacy_home.status_code == 301
        assert legacy_home.headers["location"] == "/?date=2026-08-21"
        assert legacy_analysis.status_code == 301
        assert legacy_analysis.headers["location"] == "/races/1#entry-1"
        assert legacy_analysis.headers["cache-control"] == "public, max-age=3600"
        assert client.get("/static/css/mobile.css", headers=headers).status_code == 200
        assert client.get("/health/ready", headers=headers).status_code == 200
        assert client.get("/openapi.json", headers=headers).status_code == 200
        assert client.get("/api/predictions", headers=headers).status_code == 200
        assert client.get("/forecast", follow_redirects=False).status_code == 404
        assert client.get("/validation", follow_redirects=False).status_code == 404
        assert client.get("/predictions", follow_redirects=False).status_code == 404


def test_tablets_keep_desktop_pages_while_android_phones_use_mobile(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))
    user_agents = (
        "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
        "Mozilla/5.0 (Linux; Android 14; Pixel Tablet) AppleWebKit/537.36 "
        "Chrome/120.0 Safari/537.36",
    )

    with TestClient(app) as client:
        for user_agent in user_agents:
            response = client.get("/", headers={"user-agent": user_agent}, follow_redirects=False)
            assert response.status_code == 200
            assert "RACE CALENDAR" in response.text

        phone = client.get(
            "/",
            headers={
                "user-agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) Mobile Safari/537.36"
            },
            follow_redirects=False,
        )
        assert phone.status_code == 200
        assert 'class="mobile-app mobile-home"' in phone.text
        assert {part.strip().lower() for part in phone.headers["vary"].split(",")} == {
            "user-agent", "accept-encoding"
        }


def test_mobile_analysis_uses_senior_layout_instead_of_desktop_workspace(
    tmp_path: Path,
) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        page = client.get("/races/1", headers=PHONE_HEADERS)
        desktop = client.get("/analysis?race_id=1&tab=field")
        mobile = client.get(
            "/analysis?race_id=1",
            headers=PHONE_HEADERS,
            follow_redirects=False,
        )

    assert page.status_code == 200
    assert '<link rel="canonical" href="https://mapilog.xyz/races/1">' in page.text
    assert '<meta name="robots" content="index,follow">' in page.text
    assert '<link rel="canonical" href="https://mapilog.xyz/analysis">' in desktop.text
    assert '<meta name="robots" content="noindex,follow">' in desktop.text
    assert 'rel="alternate"' not in desktop.text
    assert "mobile-analysis.js?v=11" in page.text
    assert "경주 목록" in page.text
    assert 'aria-label="실제 착순별 출전마"' in page.text
    assert "과거 전개 성향" in page.text
    assert "선행권" in page.text
    assert "선입권" in page.text
    assert "중위권" in page.text
    assert "추입권" in page.text
    assert "최근 최대 6회 정상 완주의 실제 통과순위" in page.text
    assert "ma-horse-silk" in page.text
    assert "ma-win-pct" in page.text
    assert "ma-win-role" in page.text
    assert 'data-role="강축"' in page.text
    assert "100%" in page.text
    assert "강축" in page.text
    assert ">00%<" not in page.text
    assert "각 말이 1~3위 안에 들 입상확률" not in page.text
    assert "같은 경주의 합계는 약 300%" not in page.text
    assert "모델 선정 입상 후보 1두" not in page.text
    assert 'class="ma-race-summary"' in page.text
    assert "전력 구도" in page.text
    assert 'aria-label="강축 마번"' in page.text
    assert 'class="ma-field"' in page.text
    assert "ma-role-group" not in page.text
    assert "ma-prediction-rank" not in page.text
    assert 'class="ma-race-status">종료<' in page.text
    assert "ma-result-block" in page.text
    assert ">1위<" in page.text
    assert ">1:15.2<" in page.text
    assert "예상 순위" not in page.text
    assert 'data-runner-card aria-expanded="false"' in page.text
    assert 'class="ma-record-store" data-record-store hidden' in page.text
    assert 'id="runner-details-1"' in page.text
    assert "최근 기록 1" in page.text
    assert "동일 거리 경주 0" in page.text
    assert "주행심사 2차" in page.text
    assert 'data-record-tab="trials"' not in page.text
    assert "바람의별" in page.text
    assert "S1F" in page.text
    assert "G3F" in page.text
    assert "G1F" in page.text
    assert "맑음" in page.text
    assert "건조" in page.text
    assert "함수율" in page.text
    assert "26.8.13" in page.text
    assert 'class="ma-record-head"' in page.text
    assert 'class="ma-record-meta"' in page.text
    assert 'class="ma-record-condition"' in page.text
    assert 'class="ma-record-video"' in page.text
    assert ">영상</a>" in page.text
    assert "<strong>한기수</strong>" in page.text
    assert 'aria-label="부담중량">55kg</span>' in page.text
    assert "마번 4번 · 1위 · 합격" in page.text
    assert "800m · 1두</p>" in page.text
    assert "<strong>한기수 기수</strong>" not in page.text
    assert 'aria-label="구간별 통과순위"' in page.text
    assert 'aria-label="구간별 기록"' in page.text
    assert "출발~200m" not in page.text
    assert "마지막 600m" not in page.text
    assert "마지막 200m" not in page.text
    assert "/races/" in page.text
    assert "RACE STUDY" not in page.text
    assert "PRE-RACE EXPLORER" not in page.text
    assert "SCENARIO, NOT OBSERVATION" not in page.text
    assert 'data-pace-root' not in page.text
    assert 'data-pace-data' not in page.text
    assert "말별 기록과 영상" not in page.text
    assert desktop.status_code == 200
    assert "RACE STUDY" in desktop.text
    assert "말별 기록·영상" in desktop.text
    assert mobile.status_code == 200
    assert 'class="mobile-app mobile-analysis"' in mobile.text


def test_completed_mobile_analysis_cards_follow_actual_finish_order(tmp_path: Path) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        race = session.get(Race, 1)
        run = session.get(PredictionRun, 1)
        assert race is not None and run is not None
        original = next(entry for entry in race.entries if entry.horse_number == 1)
        assert original.result is not None
        original.result.finish_position = 3
        entry_ids = {}
        for name, number, finish, probability in (
            ("실제우승마", 2, 1, 0.25),
            ("실제준우승마", 3, 2, 0.50),
        ):
            horse = Horse(kra_horse_id=f"result-order-{number}", name_ko=name)
            entry = RaceEntry(race=race, horse=horse, horse_number=number)
            session.add_all([horse, entry])
            session.flush()
            entry_ids[name] = entry.id
            session.add_all(
                [
                    RaceResult(race_entry=entry, finish_position=finish),
                    ModelPrediction(
                        prediction_run_id=run.id,
                        race_id=race.id,
                        race_entry_id=entry.id,
                        horse_number=number,
                        prob_win=probability / 3,
                        prob_top2=probability * 2 / 3,
                        prob_top3=probability,
                    ),
                ]
            )
        session.commit()

    with TestClient(create_app(factory)) as client:
        completed = client.get("/races/1", headers=PHONE_HEADERS)

    assert completed.status_code == 200
    assert 'aria-label="실제 착순별 출전마"' in completed.text
    assert (
        completed.text.index(f'data-runner-shell="{entry_ids["실제우승마"]}"')
        < completed.text.index(f'data-runner-shell="{entry_ids["실제준우승마"]}"')
        < completed.text.index(f'data-runner-shell="{original.id}"')
    )
    assert "예측 100%" in completed.text
    assert completed.text.index('title="예측 1 · 바람의별"') < completed.text.index(
        'title="예측 3 · 실제우승마"'
    )

    with factory() as session:
        race = session.get(Race, 1)
        assert race is not None
        race.status = "scheduled"
        session.commit()

    with TestClient(create_app(factory)) as client:
        scheduled = client.get("/races/1", headers=PHONE_HEADERS)

    assert scheduled.status_code == 200
    assert 'aria-label="예측 순위별 출전마"' in scheduled.text
    assert (
        scheduled.text.index(f'data-runner-shell="{original.id}"')
        < scheduled.text.index(f'data-runner-shell="{entry_ids["실제준우승마"]}"')
        < scheduled.text.index(f'data-runner-shell="{entry_ids["실제우승마"]}"')
    )


def test_mobile_analysis_keeps_other_meet_switchable(tmp_path: Path) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        seoul = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        race = Race(
            racecourse=seoul,
            race_date_local=date(2026, 8, 21),
            race_number=1,
            distance_m=1200,
            grade="국6등급",
            race_name="일반",
            status="scheduled",
        )
        session.add_all([seoul, race])
        session.flush()
        horse = Horse(kra_horse_id="001001", name_ko="서울말", sex="수")
        session.add(horse)
        session.flush()
        session.add(RaceEntry(race=race, horse=horse, horse_number=1))
        session.commit()

    app = create_app(factory)
    with TestClient(app) as client:
        jeju = client.get("/analysis?date=2026-08-21&meet=2", headers=PHONE_HEADERS)
        seoul_page = client.get("/analysis?date=2026-08-21&meet=1", headers=PHONE_HEADERS)

    jeju_bar = jeju.text.split('aria-label="경마장"', 1)[1].split('aria-label="경주 선택"', 1)[0]
    seoul_bar = seoul_page.text.split('aria-label="경마장"', 1)[1].split(
        'aria-label="경주 선택"', 1
    )[0]
    assert ">제주<" in jeju_bar and ">서울<" in jeju_bar
    assert ">제주<" in seoul_bar and ">서울<" in seoul_bar
    assert 'href="/analysis?date=2026-08-21&amp;meet=1"' in jeju_bar
    assert 'href="/analysis?date=2026-08-21&amp;meet=2"' in seoul_bar
    assert "제주 1R" in jeju.text
    assert "서울 1R" in seoul_page.text


def _seoul_ms(hour: int, minute: int = 0, day: int = 21) -> int:
    return int(
        datetime(2026, 8, day, hour, minute, tzinfo=ZoneInfo("Asia/Seoul")).timestamp() * 1000
    )


def test_mobile_all_meets_lists_races_in_start_time_order(tmp_path: Path) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        seoul = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        first = Race(
            racecourse=seoul,
            race_date_local=date(2026, 8, 21),
            race_number=1,
            distance_m=1200,
            grade="국6등급",
            race_name="일반",
            scheduled_at_ms=_seoul_ms(10, 35),
            status="scheduled",
        )
        second = Race(
            racecourse=seoul,
            race_date_local=date(2026, 8, 21),
            race_number=2,
            distance_m=1400,
            grade="국6등급",
            race_name="일반",
            scheduled_at_ms=_seoul_ms(11, 25),
            status="scheduled",
        )
        session.add_all([seoul, first, second])
        session.flush()
        horse = Horse(kra_horse_id="001001", name_ko="서울말", sex="수")
        later = Horse(kra_horse_id="001002", name_ko="서울이착", sex="암")
        session.add_all([horse, later])
        session.flush()
        session.add_all(
            [
                RaceEntry(race=first, horse=horse, horse_number=1),
                RaceEntry(race=second, horse=later, horse_number=1),
            ]
        )
        session.commit()

    app = create_app(factory)
    with TestClient(app) as client:
        page = client.get("/?date=2026-08-21&meet=", headers=PHONE_HEADERS)
        seoul_only = client.get("/?date=2026-08-21&meet=1", headers=PHONE_HEADERS)

    text = page.text
    meet_bar = text.split('aria-label="경마장"', 1)[1].split("</div>", 1)[0]
    assert ">전체<" in meet_bar
    assert ">서울<" in meet_bar
    assert ">제주<" in meet_bar
    assert 'href="/?date=2026-08-21"' in meet_bar
    chrome = text.split('aria-label="경주일과 경마장"', 1)[1].split(
        'aria-label="선택일 경주 목록"', 1
    )[0]
    assert 'aria-label="시간순 경주"' in chrome
    assert "서울 1R" in chrome
    assert "제주 1R" in chrome
    assert "서울 2R" in chrome
    assert 'class="mobile-race-no">서울<' in text
    assert 'class="mobile-round-race">1R<' in text
    assert 'aria-label="서울 1R 경주 분석 열기"' in text
    assert 'aria-label="제주 1R 경주 분석 열기"' in text
    assert 'aria-label="서울 2R 경주 분석 열기"' in text
    assert "서울말" in text
    assert "바람의별" in text
    assert "서울이착" in text
    assert text.index("서울말") < text.index("서울이착") < text.index("바람의별")
    assert 'class="mobile-race-no">서울<' in seoul_only.text
    assert 'class="mobile-round-race">1R<' in seoul_only.text
    assert "바람의별" not in seoul_only.text
    assert seoul_only.text.index("서울말") < seoul_only.text.index("서울이착")


def test_desktop_all_meets_lists_races_in_start_time_order(tmp_path: Path) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        seoul = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        busan = Racecourse(kra_meet_code=3, code="BUSAN", name_ko="부경")
        jeju = session.query(Racecourse).filter_by(kra_meet_code=2).one()
        races = [
            Race(
                racecourse=seoul,
                race_date_local=date(2026, 8, 21),
                race_number=1,
                distance_m=1200,
                grade="국6등급",
                race_name="일반",
                scheduled_at_ms=_seoul_ms(10, 35),
                status="scheduled",
            ),
            Race(
                racecourse=busan,
                race_date_local=date(2026, 8, 21),
                race_number=1,
                distance_m=1200,
                grade="국6등급",
                race_name="일반",
                scheduled_at_ms=_seoul_ms(10, 35),
                status="scheduled",
            ),
            Race(
                racecourse=busan,
                race_date_local=date(2026, 8, 21),
                race_number=2,
                distance_m=1200,
                grade="국6등급",
                race_name="일반",
                scheduled_at_ms=_seoul_ms(10, 35),
                status="scheduled",
            ),
            Race(
                racecourse=jeju,
                race_date_local=date(2026, 8, 21),
                race_number=3,
                distance_m=900,
                grade="제6등급",
                race_name="일반",
                scheduled_at_ms=_seoul_ms(10, 35),
                status="scheduled",
            ),
            Race(
                racecourse=seoul,
                race_date_local=date(2026, 8, 21),
                race_number=2,
                distance_m=1400,
                grade="국6등급",
                race_name="일반",
                scheduled_at_ms=_seoul_ms(11, 25),
                status="scheduled",
            ),
            Race(
                racecourse=busan,
                race_date_local=date(2026, 8, 21),
                race_number=3,
                distance_m=1400,
                grade="국6등급",
                race_name="일반",
                scheduled_at_ms=_seoul_ms(12, 30),
                status="scheduled",
            ),
            Race(
                racecourse=busan,
                race_date_local=date(2026, 8, 21),
                race_number=4,
                distance_m=1400,
                grade="국6등급",
                race_name="일반",
                scheduled_at_ms=None,
                status="scheduled",
            ),
        ]
        session.add_all([seoul, busan, *races])
        session.commit()

    with TestClient(create_app(factory)) as client:
        page = client.get("/?date=2026-08-21")

    assert page.status_code == 200
    official_table = page.text.split('<table class="race-table">', 1)[1].split(
        "</tbody>", 1
    )[0]
    official_header = official_table.split("</thead>", 1)[0]
    assert official_header.count("<th>") == 5
    assert "<th>상태</th>" not in official_header
    first_race_row = official_table.split("<tbody>", 1)[1].split("</tr>", 1)[0]
    first_race_cell = first_race_row.split("<td>", 1)[1].split("</td>", 1)[0]
    assert 'class="race-status-badge status scheduled">예정</span>' in first_race_cell
    expected_order = [
        "서울 1R",
        "부경 1R",
        "부경 2R",
        "제주 3R",
        "서울 2R",
        "부경 3R",
        "제주 1R",
        "제주 2R",
        "부경 4R",
    ]
    positions = [official_table.index(label) for label in expected_order]
    assert positions == sorted(positions)
    assert 'class="group-row"' not in official_table
    unknown_time_row = official_table.rsplit("<tr", 1)[1].split("</tr>", 1)[0]
    unknown_time_cells = [
        cell.split(">", 1)[1].split("</td>", 1)[0]
        for cell in unknown_time_row.split("<td")[1:]
    ]
    assert len(unknown_time_cells) == 5
    assert "미정" in unknown_time_cells[1]


def test_mobile_puts_current_race_first_on_today(tmp_path: Path, monkeypatch) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        seoul = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        session.add(
            Race(
                racecourse=seoul,
                race_date_local=date(2026, 8, 21),
                race_number=1,
                distance_m=1200,
                grade="국6등급",
                race_name="일반",
                scheduled_at_ms=_seoul_ms(10, 35),
                status="scheduled",
            )
        )
        session.commit()

    monkeypatch.setattr("horse_racing.web.dashboard.today_seoul", lambda: date(2026, 8, 21))
    monkeypatch.setattr("horse_racing.web.dashboard.now_seoul_ms", lambda: _seoul_ms(10, 36))
    app = create_app(factory)
    with TestClient(app) as client:
        page = client.get("/?date=2026-08-21", headers=PHONE_HEADERS)
        default_home = client.get("/", headers=PHONE_HEADERS)

    first_round = page.text.split('class="mobile-round is-current"', 1)[1]
    current_round = first_round.split('class="mobile-round"', 1)[0]
    assert "서울" in current_round
    assert "바람의별" not in current_round
    assert 'class="mobile-live-tag">예정<' in current_round
    assert "is-next" in page.text
    assert "예정 ·" in page.text
    assert 'class="mobile-complete-tag">종료<' in page.text
    assert "종료 ·" in page.text
    assert "8월 21일" in default_home.text
    assert "바람의별" in default_home.text
    assert 'class="mobile-round is-current"' in default_home.text


def test_default_race_focus_advances_five_minutes_after_start_regardless_of_status(
    tmp_path: Path, monkeypatch
) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        seoul = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        first = Race(
            racecourse=seoul,
            race_date_local=date(2026, 8, 22),
            race_number=1,
            distance_m=1200,
            grade="국6등급",
            race_name="일반",
            scheduled_at_ms=_seoul_ms(10, 35, day=22),
            status="completed",
        )
        second = Race(
            racecourse=seoul,
            race_date_local=date(2026, 8, 22),
            race_number=2,
            distance_m=1400,
            grade="국6등급",
            race_name="일반",
            scheduled_at_ms=_seoul_ms(11, 25, day=22),
            status="scheduled",
        )
        session.add_all([seoul, first, second])
        session.flush()
        first_id = first.id
        second_id = second.id
        session.commit()

    monkeypatch.setattr("horse_racing.web.dashboard.today_seoul", lambda: date(2026, 8, 22))
    now_ms = _seoul_ms(10, 39, day=22) + 59_000
    monkeypatch.setattr("horse_racing.web.dashboard.now_seoul_ms", lambda: now_ms)
    with TestClient(create_app(factory)) as client:
        before_cutoff = client.get("/?date=2026-08-22&meet=1", headers=PHONE_HEADERS)
    now_ms = _seoul_ms(10, 40, day=22)
    with TestClient(create_app(factory)) as client:
        after_cutoff = client.get("/?date=2026-08-22&meet=1", headers=PHONE_HEADERS)

    current_before = before_cutoff.text.split('class="mobile-round is-current"', 1)[1]
    current_after = after_cutoff.text.split('class="mobile-round is-current"', 1)[1]
    assert f'id="round-{first_id}"' in current_before.split(">", 1)[0]
    assert f'id="round-{second_id}"' in current_after.split(">", 1)[0]


def test_mobile_home_flags_stakes_and_overdue_results(tmp_path: Path, monkeypatch) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        seoul = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        session.add_all(
            [
                Race(
                    racecourse=seoul,
                    race_date_local=date(2026, 8, 21),
                    race_number=1,
                    distance_m=1800,
                    grade="혼OPEN",
                    race_name="코리아컵(G1)",
                    scheduled_at_ms=_seoul_ms(10, 35),
                    status="scheduled",
                ),
                Race(
                    racecourse=seoul,
                    race_date_local=date(2026, 8, 21),
                    race_number=2,
                    distance_m=1200,
                    grade="국6등급",
                    race_name="일반",
                    scheduled_at_ms=_seoul_ms(11, 30),
                    status="scheduled",
                ),
            ]
        )
        session.commit()

    monkeypatch.setattr("horse_racing.web.dashboard.today_seoul", lambda: date(2026, 8, 21))
    monkeypatch.setattr("horse_racing.web.dashboard.now_seoul_ms", lambda: _seoul_ms(13, 40))
    app = create_app(factory)
    with TestClient(app) as client:
        page = client.get("/?date=2026-08-21&meet=1", headers=PHONE_HEADERS)

    def round_block(marker: str) -> str:
        return page.text.split(marker, 1)[1].split('<section class="mobile-round', 1)[0]

    stakes = round_block('class="mobile-round is-stakes"')
    assert 'class="mobile-stakes-tag">G1 대상경주<' in stakes
    assert 'class="mobile-awaiting-tag">결과 대기<' in stakes
    current = round_block('class="mobile-round is-current"')
    assert "mobile-awaiting-tag" not in current
    assert 'class="mobile-live-tag">예정<' in current
    assert "예측 보는 법" in page.text
    assert "data-mobile-chrome" in page.text
    assert "data-chrome-filters" in page.text


def test_mobile_analysis_marks_upcoming_race(tmp_path: Path, monkeypatch) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        seoul = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
        first = Race(
            racecourse=seoul,
            race_date_local=date(2026, 8, 21),
            race_number=1,
            distance_m=1200,
            grade="국6등급",
            race_name="일반",
            scheduled_at_ms=_seoul_ms(10, 35),
            status="scheduled",
        )
        later = Race(
            racecourse=seoul,
            race_date_local=date(2026, 8, 21),
            race_number=3,
            distance_m=1300,
            grade="국6등급",
            race_name="일반",
            scheduled_at_ms=_seoul_ms(12, 45),
            status="scheduled",
        )
        session.add_all([seoul, first, later])
        session.flush()
        later_id = later.id
        horse = Horse(kra_horse_id="001088", name_ko="분석말", sex="수")
        session.add(horse)
        session.flush()
        session.add_all(
            [
                RaceEntry(race=first, horse=horse, horse_number=1),
                RaceEntry(race=later, horse=horse, horse_number=1),
            ]
        )
        session.commit()

    monkeypatch.setattr("horse_racing.web.race_analysis.today_seoul", lambda: date(2026, 8, 21))
    monkeypatch.setattr("horse_racing.web.race_analysis.now_seoul_ms", lambda: _seoul_ms(13, 40))
    app = create_app(factory)
    with TestClient(app) as client:
        first_page = client.get(
            "/analysis?date=2026-08-21&meet=1", headers=PHONE_HEADERS
        )
        later_page = client.get(f"/races/{later_id}", headers=PHONE_HEADERS)

    first_chips = first_page.text.split('aria-label="경주 선택"', 1)[1].split("</div>", 1)[0]
    later_chips = later_page.text.split('aria-label="경주 선택"', 1)[1].split("</div>", 1)[0]
    assert first_chips.index("1R") < first_chips.index("3R")
    assert "예정 ·" in first_chips
    assert "is-next" in first_chips
    assert later_chips.count("is-next") == 1
    assert "active is-next" in later_chips or "is-next" in later_chips
    assert "예정 ·" in later_chips


def test_mobile_defaults_to_today_not_latest_card(tmp_path: Path, monkeypatch) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        course = session.get(Racecourse, 1)
        later_horse = Horse(kra_horse_id="003088", name_ko="다음날말", sex="수")
        later_race = Race(
            racecourse=course,
            race_date_local=date(2026, 8, 28),
            race_number=1,
            distance_m=900,
            grade="제6등급",
            race_name="일반",
            scheduled_at_ms=_seoul_ms(10, 35, day=28),
            status="scheduled",
        )
        session.add_all(
            [
                later_horse,
                later_race,
                RaceEntry(race=later_race, horse=later_horse, horse_number=1),
            ]
        )
        session.commit()

    monkeypatch.setattr("horse_racing.web.dashboard.today_seoul", lambda: date(2026, 8, 21))
    monkeypatch.setattr("horse_racing.web.dashboard.now_seoul_ms", lambda: _seoul_ms(9, 0))
    app = create_app(factory)
    with TestClient(app) as client:
        page = client.get("/", headers=PHONE_HEADERS)

    assert "8월 21일" in page.text
    assert "바람의별" in page.text
    assert "다음날말" not in page.text


def test_mobile_lists_horses_highest_win_probability_first(tmp_path: Path) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        race = session.get(Race, 1)
        run = session.get(PredictionRun, 1)
        jockey = session.get(Jockey, 1)
        trainer = session.get(Trainer, 1)
        owner = session.get(Owner, 1)
        assert race is not None and run is not None
        additions = (
            ("낮은확률", 2, 0.60),
            ("세번째후보", 3, 0.50),
            ("네번째후보", 4, 0.40),
            ("다섯번째후보", 5, 0.30),
            ("후순위하나", 6, 0.20),
            ("후순위둘", 8, 0.10),
        )
        for name, number, probability in additions:
            other = Horse(
                kra_horse_id=f"00300{number}",
                name_ko=name,
                sex="수",
                origin_country="한국",
                birth_date=date(2022, 5, 1),
            )
            entry = RaceEntry(
                race=race,
                horse=other,
                horse_number=number,
                jockey=jockey,
                trainer=trainer,
                owner=owner,
                carried_weight_kg=55,
            )
            session.add_all([other, entry])
            session.flush()
            session.add(
                ModelPrediction(
                    prediction_run_id=run.id,
                    race_id=race.id,
                    race_entry_id=entry.id,
                    horse_number=number,
                    prob_win=probability / 3,
                    prob_top2=probability * 2 / 3,
                    prob_top3=probability,
                )
            )
        session.commit()

    app = create_app(factory)
    with TestClient(app) as client:
        home = client.get("/?date=2026-08-21&meet=2", headers=PHONE_HEADERS)
        analysis = client.get("/races/1", headers=PHONE_HEADERS)

    assert home.text.index("바람의별") < home.text.index("낮은확률")
    assert home.text.index("예측 100%") < home.text.index("예측 60%")
    assert analysis.text.index("바람의별") < analysis.text.index("낮은확률")
    assert analysis.text.index("예측 100%") < analysis.text.index("예측 60%")
    assert "모델 선정 입상 후보 5두" not in home.text
    assert "전체 7두 분석" not in home.text
    assert "그 외 출전마 2두와 전체 입상확률 보기" not in home.text
    assert "모델 선정 입상 후보 5두" not in home.text
    assert "mobile-poster-rank" not in home.text
    assert "후순위하나" not in home.text
    assert "후순위둘" not in home.text
    assert "모델 선정 입상 후보 5두" not in analysis.text
    assert "그 외 출전마" not in analysis.text
    assert 'class="ma-field"' in analysis.text
    assert "ma-role-group" not in analysis.text
    assert analysis.text.index('aria-label="강축 마번"') < analysis.text.index(
        'aria-label="상대 마번"'
    )
    assert "후순위하나" in analysis.text
    assert "후순위둘" in analysis.text
    assert "ma-prediction-rank" not in analysis.text
    assert home.text.count("강축") >= 1
    assert home.text.count("축") >= 1
    assert analysis.text.count("강축") >= 1


def test_mobile_shows_trial_form_for_debut_horses(tmp_path: Path) -> None:
    from bs4 import BeautifulSoup

    factory = seeded_session(tmp_path)
    with factory() as session:
        race = session.get(Race, 1)
        jockey = session.get(Jockey, 1)
        trainer = session.get(Trainer, 1)
        owner = session.get(Owner, 1)
        assert race is not None
        debut = Horse(
            kra_horse_id="003010",
            name_ko="송당퍼스트",
            sex="수",
            origin_country="한국",
            birth_date=date(2023, 3, 1),
        )
        session.add(debut)
        session.flush()
        session.add(
            RaceEntry(
                race=race,
                horse=debut,
                horse_number=2,
                jockey=jockey,
                trainer=trainer,
                owner=owner,
                carried_weight_kg=55,
            )
        )
        trial = RunningTrial(
            meet_code=2,
            trial_date_local=date(2026, 8, 10),
            trial_round=30,
            trial_race_number=1,
            distance_m=800,
            observed_at_ms=1,
        )
        session.add(trial)
        session.flush()
        session.add(
            RunningTrialResult(
                trial=trial,
                horse=debut,
                jockey=jockey,
                trainer=trainer,
                horse_number=3,
                horse_name_raw="송당퍼스트",
                finish_position=1,
                finish_rank_raw="01",
                finish_time_ms=66_800,
                judgement="합",
                observed_at_ms=1,
            )
        )
        session.commit()

    app = create_app(factory)
    with TestClient(app) as client:
        home = client.get("/?date=2026-08-21&meet=2", headers=PHONE_HEADERS)
        analysis = client.get("/races/1", headers=PHONE_HEADERS)
        desktop = client.get("/analysis?race_id=1&tab=field")

    assert "심사 1합" in home.text
    assert "송당퍼스트" in home.text
    assert "심사 1합" in analysis.text
    assert "첫 출전마는 주행심사 착순입니다" not in analysis.text
    assert "송당퍼스트" in desktop.text
    document = BeautifulSoup(desktop.text, "html.parser")
    payload = json.loads(document.find(id="race-study-data").string)
    debut_runner = next(row for row in payload["runners"] if row["horse"] == "송당퍼스트")
    assert debut_runner["form_kind"] == "trial"
    assert debut_runner["form_tokens"] == ["1합"]


def test_entity_list_and_detail_pages(tmp_path: Path, paced_requests) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        active = next(horse for horse in session.query(Horse).all() if horse.name_ko == "바람의별")
        retired = next(horse for horse in session.query(Horse).all() if horse.name_ko == "가가나")
        excluded = next(horse for horse in session.query(Horse).all() if horse.name_ko == "제외마")
        active.is_active = True
        active.meet_code = 2
        active.active_status_observed_at_ms = 1_795_190_400_000
        active.active_status_source = "test"
        retired.is_active = False
        excluded.is_active = False
        retired.meet_code = 1
        retired.active_status_observed_at_ms = 1_795_190_400_000
        retired.active_status_source = "test"
        excluded.meet_code = 3
        session.add(
            HorseProfileSnapshot(
                horse=excluded,
                meet_code=3,
                trainer_kra_id="070101",
                trainer_name="김조교",
                observed_at_ms=1_795_190_400_000,
            )
        )
        current_jeju_trainer = session.query(Trainer).filter_by(kra_trainer_id="070101").one()
        current_seoul_trainer = Trainer(kra_trainer_id="070102", name_ko="서울조교사")
        current_bukyeong_trainer = Trainer(kra_trainer_id="070103", name_ko="부경조교사")
        unconfirmed_trainer = Trainer(kra_trainer_id="070199", name_ko="미확인조교사")
        session.add_all([current_seoul_trainer, current_bukyeong_trainer, unconfirmed_trainer])
        session.flush()
        roster_date = date(2026, 9, 29)
        source = "https://race.kra.co.kr/trainer/profileTrainerList.do"
        for trainer, meet_code, stable_part in (
            (current_jeju_trainer, 2, 1),
            (current_seoul_trainer, 1, 1),
            (current_bukyeong_trainer, 3, 1),
        ):
            session.add(
                TrainerAffiliationSnapshot(
                    trainer_id=trainer.id,
                    observed_on=roster_date,
                    meet_code=meet_code,
                    stable_part=stable_part,
                    official_name_ko=trainer.name_ko,
                    observed_at_ms=1_795_190_400_000,
                    source_url=source,
                    source_sha256="a" * 64,
                )
            )
        session.commit()
    app = create_app(factory)

    with TestClient(app) as client:
        horses = client.get("/horses?q=바람")
        directory = client.get("/horses?meet=1")
        horse_list = client.get("/horses/list?status=all")
        horse_by_name = client.get("/horses/list?sort=name&q=가가나")
        active_horses = client.get("/horses/list?status=active")
        retired_horses = client.get("/horses/list?q=가가나")
        retired_browse = client.get("/horses/list?status=retired")
        seoul_horses = client.get("/horses/list?meet=1")
        jeju_horses = client.get("/horses/list?meet=2")
        bukyeong_horses = client.get("/horses/list?meet=3&q=제외마")
        filtered_search = client.get("/horses?meet=2&q=바람")
        trainers = client.get("/trainers")
        unclassified_trainer_search = client.get("/trainers?q=미확인조교사")
        seoul_trainers = client.get("/trainers?meet=1")
        jeju_trainers = client.get("/trainers?meet=2")
        bukyeong_trainers = client.get("/trainers?meet=3")
        filtered_trainer_search = client.get("/trainers?meet=2&q=070101")
        horse_detail = client.get("/horses/003001")
        horse_records = client.get("/horses/003001?tab=records")
        horse_history = client.get("/horses/003001?tab=history")
        legacy_horse_detail = client.get("/horses/1", follow_redirects=False)
        jockey_detail = client.get("/jockeys/080101")
        legacy_jockey_detail = client.get("/jockeys/1", follow_redirects=False)
        trainer_detail = client.get("/trainers/070101")
        legacy_trainer_detail = client.get("/trainers/1", follow_redirects=False)
        owners = client.get("/owners?q=050101")
        owner_detail = client.get("/owners/050101")
        legacy_owner_detail = client.get("/owners/1", follow_redirects=False)
        unknown_horse = client.get("/horses/not-a-kra-id")
        missing = client.get("/ponies")

    assert horses.status_code == 200
    assert "바람의별" in horses.text
    assert "003001" in horses.text
    assert 'class="coverage-line"' not in horses.text
    assert "출전 많은 순" in horses.text
    assert 'href="/horses/003001"' in horses.text
    assert 'href="/horses/1"' not in horses.text
    assert directory.status_code == 200
    assert 'class="horse-grade-table"' in directory.text
    assert 'id="horse-directory-list"' not in directory.text
    assert 'horse-directory-statuses' not in directory.text
    assert 'name="status"' not in directory.text
    assert 'action="/horses/list"' in directory.text
    assert 'href="/horses/list?' in directory.text
    assert '#horse-directory-list' not in directory.text
    assert "바람의별" in horse_list.text
    assert "가가나" not in horse_list.text
    assert "가가나" in horse_by_name.text
    assert 'class="horse-grade-table"' not in horse_list.text
    assert 'class="horse-directory-back"' in horse_list.text
    assert "가가나" not in retired_browse.text
    assert 'data-status="active">현역<' in active_horses.text
    assert "바람의별" in active_horses.text
    assert "가가나" not in active_horses.text
    assert 'data-status="retired">은퇴<' in retired_horses.text
    assert "가가나" in retired_horses.text
    assert "바람의별" not in retired_horses.text
    assert "가가나" not in seoul_horses.text
    assert "바람의별" not in seoul_horses.text
    assert "바람의별" in jeju_horses.text
    assert "가가나" not in jeju_horses.text
    assert "제외마" in bukyeong_horses.text
    assert "바람의별" not in bukyeong_horses.text
    assert "바람의별" in filtered_search.text
    assert 'name="meet" value="2"' in filtered_search.text
    assert trainers.status_code == 200
    assert "2026-09-29 기준 현역 조교사" in trainers.text
    assert "미확인조교사" not in trainers.text
    assert "미확인조교사" in unclassified_trainer_search.text
    trainer_table = re.search(
        r'<table class="trainer-list-table".*?</table>', trainers.text, re.DOTALL,
    ).group(0)
    trainer_head = re.search(r"<thead>(.*?)</thead>", trainer_table, re.DOTALL).group(1)
    assert re.findall(r"<th(?:\s[^>]*)?>(.*?)</th>", trainer_head, re.DOTALL) == [
        "번호", "이름", "조", "관리두수", "출전", "1위", "2위", "3위", "승률", "복승률", "입상률",
    ]
    trainer_row = re.search(r"<tbody>\s*<tr[^>]*>(.*?)</tr>", trainer_table, re.DOTALL).group(1)
    assert len(re.findall(r"<td(?:\s[^>]*)?>", trainer_row)) == 11
    assert 'href="/trainers?meet=1' in trainers.text
    assert "서울조교사" in seoul_trainers.text
    assert "김조교" not in seoul_trainers.text
    assert "김조교" in jeju_trainers.text
    assert "서울조교사" not in jeju_trainers.text
    assert "부경조교사" in bukyeong_trainers.text
    assert "서울조교사" not in bukyeong_trainers.text
    assert "김조교" in filtered_trainer_search.text
    assert 'name="meet" value="2"' in filtered_trainer_search.text
    assert "최근 5전" in horses.text
    assert "통산 전적" in horses.text
    assert "입상률" in horses.text
    assert "레이팅 높은 순" in horses.text
    assert "<th>번호</th>" in horses.text
    assert "<th>마번</th>" not in horses.text
    assert "<th>체중</th>" not in horses.text
    assert "<th>훈련</th>" not in horses.text
    assert "<th>진료</th>" not in horses.text

    assert horse_detail.status_code == 200
    assert legacy_horse_detail.status_code == 301
    assert legacy_horse_detail.headers["location"] == "/horses/003001"
    assert '<link rel="canonical" href="https://mapilog.xyz/horses/003001">' in horse_detail.text
    assert "기본 정보" in horse_detail.text
    assert 'data-status="active">현역<' in horse_detail.text
    assert "현역 상태" in horse_detail.text
    assert "상태 확인" in horse_detail.text
    assert "나이" in horse_detail.text
    assert "4세" in horse_detail.text
    assert 'class="summary-grid"' not in horse_detail.text
    assert 'id="start-history"' in horse_records.text
    assert "제주 1R" in horse_records.text
    assert "1위" in horse_records.text
    assert "<th>착차</th>" in horse_records.text
    assert "<th>상금</th>" not in horse_records.text
    assert 'class="numeric margin">-</td>' in horse_records.text
    assert "레이팅" in horse_history.text
    assert "체중" in horse_history.text
    assert "훈련" in horse_history.text
    assert "진료" in horse_history.text
    assert "280kg" in horse_history.text
    assert "근막염" in horse_history.text
    assert 'id="horse-history"' in horse_history.text
    assert 'id="horse-profile"' in horse_detail.text
    assert "기본 정보" in horse_detail.text
    assert "12전 3/2/1" in horse_detail.text
    assert "TEST SIRE" in horse_detail.text
    assert "최신 레이팅" not in horse_detail.text
    assert "현재 레이팅" not in horse_detail.text
    assert "마지막 경주 레이팅" in horse_detail.text
    assert "경주 당시 레이팅" in horse_history.text
    assert "주행심사" in horse_history.text
    assert "합격" in horse_history.text
    assert "1:07.1" in horse_history.text
    assert "S1F 18.1" in horse_history.text
    assert "주행미합(신)" in horse_history.text

    assert jockey_detail.status_code == 200
    assert legacy_jockey_detail.status_code == 301
    assert legacy_jockey_detail.headers["location"] == "/jockeys/080101"
    assert trainer_detail.status_code == 200
    assert 'class="summary-grid"' in trainer_detail.text
    assert legacy_trainer_detail.status_code == 301
    assert legacy_trainer_detail.headers["location"] == "/trainers/070101"
    managed_section = trainer_detail.text.split('id="trainer-managed-horses"', 1)[1].split(
        '<section class="board-layout', 1
    )[0]
    assert "위탁관리 말" in managed_section
    assert "1두" in managed_section
    assert 'href="/horses/003001"' in managed_section
    assert "바람의별" in managed_section
    assert "<th>순번</th>" in managed_section
    assert ">1</td>" in managed_section
    assert "<th>마번</th>" not in managed_section
    assert "<th>프로필 확인</th>" not in managed_section
    assert "<th>나이</th>" in managed_section
    assert "<th>마지막 경주 레이팅</th>" in managed_section
    assert "4세" in managed_section
    assert ">45</td>" in managed_section
    assert "제외마" not in managed_section

    assert owners.status_code == 200
    assert "이마주" in owners.text
    assert owner_detail.status_code == 200
    assert legacy_owner_detail.status_code == 301
    assert legacy_owner_detail.headers["location"] == "/owners/050101"
    assert "바람의별" in owner_detail.text
    assert unknown_horse.status_code == 404
    assert missing.status_code == 404


def test_entity_detail_tab_switch_reuses_data_without_more_sql(tmp_path):
    factory = seeded_session(tmp_path)
    statements = []

    def count_sql(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(factory.kw["bind"], "before_cursor_execute", count_sql)
    with TestClient(create_app(factory)) as client:
        profile = client.get("/horses/003001?tab=profile")
        cold_queries = len(statements)
        assert profile.status_code == 200 and cold_queries > 0
        records = client.get("/horses/003001?tab=records")
        assert records.status_code == 200
        assert 'id="start-history"' in records.text
        assert len(statements) == cold_queries
        repeat = client.get("/horses/003001?tab=records")
        assert repeat.text == records.text
        assert len(statements) == cold_queries
        redirect = client.get("/horses/1?tab=records", follow_redirects=False)
        assert redirect.status_code == 301
        assert redirect.headers["location"] == "/horses/003001?tab=records"


def test_horse_list_rejects_unbounded_pages_before_sql():
    def forbidden_session():
        raise AssertionError("Invalid pages must never open the DB")

    with TestClient(create_app(forbidden_session)) as client:
        for page in ("201", "9223372036854775807", "9" * 100):
            assert client.get(f"/horses/list?page={page}").status_code == 422
