import csv
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import (
    Horse,
    HorseMedical,
    HorseProfileSnapshot,
    HorseRatingSnapshot,
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
)
from horse_racing.web.app import create_app
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

    assert robots.status_code == 200
    assert robots.headers["content-type"].startswith("text/plain")
    assert "User-agent: ClaudeBot\nDisallow: /" in robots.text
    assert "User-agent: Claude-SearchBot\nDisallow: /" in robots.text
    assert "User-agent: Claude-User\nDisallow: /" in robots.text
    assert "User-agent: *\nAllow: /" in robots.text
    assert "Sitemap: https://mapilog.xyz/sitemap.xml" in robots.text
    assert sitemap.status_code == 200
    assert sitemap.headers["content-type"].startswith("application/xml")
    root = ElementTree.fromstring(sitemap.content)
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [item.text for item in root.findall("s:url/s:loc", namespace)]
    assert "https://mapilog.xyz/" in urls
    assert "https://mapilog.xyz/forecast" in urls
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


def test_generic_crawlers_are_rate_limited_without_blocking_search(tmp_path: Path) -> None:
    client = TestClient(create_app())
    headers = {"user-agent": "ExampleCrawler/1.0", "x-forwarded-for": "203.0.113.10"}

    for _ in range(10):
        assert client.get("/robots.txt", headers=headers).status_code == 200
    limited = client.get("/robots.txt", headers=headers)

    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"


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
    assert 'href="https://mapilog.xyz/static/css/dashboard.css?v=15"' in apex_response.text
    assert (
        'href="https://mapilog-example.run.app/static/css/dashboard.css?v=15"'
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
    assert "YEONGCHEON · COURSE EXPLORER" in response.text


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
    assert f"distance={distance}" in response.text
    assert "출발점과 주행 경로를 확인합니다" in response.text
    assert "선택 거리" in response.text
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
    assert response.text.count('data-seoul-route="') == (0 if meet_code == 2 else 1)
    assert response.text.count("data-jeju-route/>") == (1 if meet_code == 2 else 0)
    assert f"href=\"/racecourses/{course}/course?distance={distance}\"" in response.text
    assert "현재 경주" in response.text
    assert "다른 거리의 경주로도 보기 ↗" in response.text


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
    assert "제주 1R" in response.text
    assert "바람의별" in response.text
    assert response.text.index("제주 1R") < response.text.index("출전마 및 결과")
    assert "4세" in response.text
    assert "1:15.2" in response.text
    assert "2.1배" in response.text
    assert ">착차<" in response.text
    assert ">상금<" not in response.text
    assert 'href="/horses/003001"' in response.text
    assert 'href="/jockeys/080101"' in response.text
    assert 'href="/trainers/070101"' in response.text
    assert 'href="/owners/050101"' in response.text
    assert "이마주" in response.text
    assert 'href="/races/1"' in response.text
    assert "구간 · 배당 · 심판" in response.text
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


def test_race_detail_page_shows_results_and_sections(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        response = client.get("/races/1")
        missing = client.get("/races/999")

    assert response.status_code == 200
    assert "제주 1R" in response.text
    assert 'data-racecourse-map="jeju"' in response.text
    assert 'data-course-explorer data-distance="900"' in response.text
    assert 'data-course-focus' in response.text
    assert 'data-course-select="0"' in response.text
    assert 'data-course-detail="0" hidden' in response.text
    assert "제주 경주로 · 900m 주행 경로" in response.text
    assert "직선 493.7m" in response.text
    assert "곡선 R 97.5m" in response.text
    assert "2×493.7m + 2π×97.5m" in response.text
    assert "고저차는 표시하지 않습니다" in response.text
    assert "출전마 및 결과" in response.text
    assert "구간기록 · 전개" in response.text
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
    assert "8.4배" in response.text
    assert 'href="/races/2"' in response.text
    assert missing.status_code == 404


def test_running_trial_appears_in_calendar_and_has_race_like_detail_page(
    tmp_path: Path,
) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        dashboard = client.get("/?date=2026-08-13&meet=2")
        detail = client.get("/running-trials/1")
        missing = client.get("/running-trials/999")

    assert dashboard.status_code == 200
    assert "공식 경주와 주행심사" in dashboard.text
    assert "제주 2R" in dashboard.text
    assert "예측 대상 제외" in dashboard.text
    assert 'href="/running-trials/1"' in dashboard.text
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


def test_data_status_page_integrates_refresh_coverage(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        response = client.get("/data-status")

    assert response.status_code == 200
    assert "데이터 최신화 현황" in response.text
    assert "sync-latest" in response.text
    assert "공식 경주" in response.text
    assert "주행심사 결과" in response.text
    assert "2026-08-13" in response.text


def test_prediction_ledger_page_and_api_separate_prospective_metrics(
    tmp_path: Path,
) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        page = client.get("/predictions")
        api = client.get("/api/predictions")

    assert page.status_code == 200
    assert "공개 예측 검증 원장" in page.text
    assert "사전 공개" in page.text
    assert "정산 완료" in page.text
    assert "cccccccccccc" in page.text
    assert api.status_code == 200
    payload = api.json()
    assert payload["prospective"]["publications"] == 1
    assert payload["prospective"]["settlements"] == 1
    assert payload["prospective"]["scored_races"] == 1
    assert payload["runs"][0]["mode"] == "live"


def test_forecast_page_uses_only_published_probabilities(tmp_path: Path) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        race = session.get(Race, 1)
        assert race is not None
        race.status = "scheduled"
        session.commit()
    app = create_app(factory)

    with TestClient(app) as client:
        response = client.get("/forecast?date=2026-08-21&race_id=1")

    assert response.status_code == 200
    assert "미래 경주 예측" in response.text
    assert "probability_ensemble" in response.text
    assert "100.0%" in response.text
    assert "SCENARIO, NOT OBSERVATION" in response.text
    assert "공식 GPS가 아닌" in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_jeju_distance_page_uses_portable_year_extraction(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        response = client.get("/racecourses/jeju/distances")

    assert response.status_code == 200
    assert "제주" in response.text


def test_validation_page_reports_sample_and_keeps_mode_visible(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        response = client.get("/validation")

    assert response.status_code == 200
    assert "예측 검증" in response.text
    assert "1경주 · 1두" in response.text
    assert "사전 공개" in response.text
    assert "확률 지표는 불변 원장" in response.text
    assert "1위" in response.text


def test_analysis_workspace_filters_exports_and_rejects_invalid_range(
    tmp_path: Path,
) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        page = client.get("/analysis?start=2026-08-01&end=2026-08-31&horse=1")
        exported = client.get("/api/analysis/export.csv?start=2026-08-01&end=2026-08-31&horse=1")
        invalid = client.get("/analysis?start=2026-09-01&end=2026-08-01")

    assert page.status_code == 200
    assert "경주 분석" in page.text
    assert "내 분석" not in page.text
    assert "바람의별" in page.text
    assert "이 브라우저에 저장" in page.text
    assert "말별 기록과 영상" in page.text
    assert "현재 출전마" in page.text
    assert "수집된 과거 경주 기록이 없습니다" in page.text
    assert 'data-selected-race-id="1"' in page.text
    assert "미래 경주 예측" in page.text
    assert "예상 전개 탐색" in page.text
    assert "SCENARIO, NOT OBSERVATION" in page.text
    assert "probability_ensemble" in page.text
    assert "100.0%" in page.text
    assert "모델 예측 ↗" not in page.text
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert "track_condition" in exported.text
    assert "S1F" in exported.text
    assert invalid.status_code == 422


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
    assert "날씨·주로·함수율" in default_page.text
    assert "S1F" in default_page.text
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
    assert "dashboard.css?v=15" in page.text


def test_dashboard_accepts_empty_racecourse_filter(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        response = client.get("/?date=2026-08-21&meet=")

    assert response.status_code == 200
    assert "전체 경마장" in response.text


def test_layout_cookie_overrides_user_agent(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        mobile = client.get("/", headers={"cookie": "hr-layout=mobile"})
        desktop = client.get("/", headers={**PHONE_HEADERS, "cookie": "hr-layout=desktop"})

    assert 'data-layout="mobile"' in mobile.text
    assert 'class="mobile-app mobile-home"' in mobile.text
    assert 'data-layout="desktop"' in desktop.text
    assert "mobile-app" not in desktop.text
    assert "hr-layout" in mobile.text


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
    assert "mobile.css?v=81" in page.text
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
            assert {part.strip().lower() for part in response.headers["vary"].split(",")} == {
                "user-agent", "accept-encoding"
            }

        for path in (
            "/forecast?date=2026-08-21",
            "/running-trials/1",
            "/validation",
            "/racecourses/jeju/distances",
            "/predictions",
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
        assert client.get("/forecast", follow_redirects=False).status_code == 200


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
        desktop = client.get("/analysis?race_id=1")
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
    assert "00%" in page.text
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
    assert "말별 기록과 영상" not in page.text
    assert desktop.status_code == 200
    assert "RACE STUDY" in desktop.text
    assert "말별 기록과 영상" in desktop.text
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
        page = client.get("/?date=2026-08-21", headers=PHONE_HEADERS)
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
    monkeypatch.setattr("horse_racing.web.dashboard.now_seoul_ms", lambda: _seoul_ms(13, 40))
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
        page = client.get("/?date=2026-08-21", headers=PHONE_HEADERS)

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
        desktop = client.get("/analysis?race_id=1")

    assert "심사 1합" in home.text
    assert "송당퍼스트" in home.text
    assert "심사 1합" in analysis.text
    assert "첫 출전마는 주행심사 착순입니다" not in analysis.text
    assert "송당퍼스트" in desktop.text
    assert ">1합<" in desktop.text


def test_entity_list_and_detail_pages(tmp_path: Path, paced_requests) -> None:
    factory = seeded_session(tmp_path)
    with factory() as session:
        active = next(horse for horse in session.query(Horse).all() if horse.name_ko == "바람의별")
        retired = next(horse for horse in session.query(Horse).all() if horse.name_ko == "가가나")
        active.is_active = True
        active.active_status_observed_at_ms = 1_795_190_400_000
        active.active_status_source = "test"
        retired.is_active = False
        retired.active_status_observed_at_ms = 1_795_190_400_000
        retired.active_status_source = "test"
        session.commit()
    app = create_app(factory)

    with TestClient(app) as client:
        horses = client.get("/horses?q=바람")
        horse_list = client.get("/horses")
        horse_by_name = client.get("/horses?sort=name")
        active_horses = client.get("/horses?status=active")
        retired_horses = client.get("/horses?status=retired")
        horse_detail = client.get("/horses/003001")
        legacy_horse_detail = client.get("/horses/1", follow_redirects=False)
        jockey_detail = client.get("/jockeys/080101")
        legacy_jockey_detail = client.get("/jockeys/1", follow_redirects=False)
        trainer_detail = client.get("/trainers/070101")
        legacy_trainer_detail = client.get("/trainers/1", follow_redirects=False)
        owners = client.get("/owners")
        owner_detail = client.get("/owners/050101")
        legacy_owner_detail = client.get("/owners/1", follow_redirects=False)
        unknown_horse = client.get("/horses/not-a-kra-id")
        missing = client.get("/ponies")

    assert horses.status_code == 200
    assert "바람의별" in horses.text
    assert "003001" in horses.text
    assert "적재 레이팅" in horses.text
    assert "출전 많은 순" in horses.text
    assert 'href="/horses/003001"' in horses.text
    assert 'href="/horses/1"' not in horses.text
    assert horse_list.text.index("바람의별") < horse_list.text.index("가가나")
    assert horse_by_name.text.index("가가나") < horse_by_name.text.index("바람의별")
    assert 'data-status="active">현역<' in active_horses.text
    assert "바람의별" in active_horses.text
    assert "가가나" not in active_horses.text
    assert 'data-status="retired">은퇴<' in retired_horses.text
    assert "가가나" in retired_horses.text
    assert "바람의별" not in retired_horses.text
    assert "체중" in horses.text
    assert "훈련" in horses.text

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
    assert "출전 이력" in horse_detail.text
    assert "제주 1R" in horse_detail.text
    assert "1위" in horse_detail.text
    assert "<th>착차</th>" in horse_detail.text
    assert "<th>상금</th>" not in horse_detail.text
    assert 'class="numeric margin">-</td>' in horse_detail.text
    assert "레이팅" in horse_detail.text
    assert "체중" in horse_detail.text
    assert "훈련" in horse_detail.text
    assert "진료" in horse_detail.text
    assert "280kg" in horse_detail.text
    assert "근막염" in horse_detail.text
    assert 'id="horse-history"' in horse_detail.text
    assert 'id="horse-profile"' in horse_detail.text
    assert "기본 정보" in horse_detail.text
    assert "12전 3/2/1" in horse_detail.text
    assert "TEST SIRE" in horse_detail.text
    assert "최신 레이팅" not in horse_detail.text or "현재 레이팅" in horse_detail.text
    assert "현재 레이팅" in horse_detail.text
    assert "주행심사" in horse_detail.text
    assert "합격" in horse_detail.text
    assert "1:07.1" in horse_detail.text
    assert "S1F 18.1" in horse_detail.text
    assert "주행미합(신)" in horse_detail.text

    assert jockey_detail.status_code == 200
    assert legacy_jockey_detail.status_code == 301
    assert legacy_jockey_detail.headers["location"] == "/jockeys/080101"
    assert trainer_detail.status_code == 200
    assert legacy_trainer_detail.status_code == 301
    assert legacy_trainer_detail.headers["location"] == "/trainers/070101"

    assert owners.status_code == 200
    assert "이마주" in owners.text
    assert owner_detail.status_code == 200
    assert legacy_owner_detail.status_code == 301
    assert legacy_owner_detail.headers["location"] == "/owners/050101"
    assert "바람의별" in owner_detail.text
    assert unknown_horse.status_code == 404
    assert missing.status_code == 404
