import csv
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

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
    assert 'id="racecourse-map"' not in response.text


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
    assert "경주 일정과 결과" in response.text
    assert "제주 1R" in response.text
    assert "바람의별" in response.text
    assert response.text.index("제주 1R") < response.text.index("출전마 및 결과")
    assert "4세" in response.text
    assert "1:15.2" in response.text
    assert "2.1배" in response.text
    assert ">착차<" in response.text
    assert ">상금<" not in response.text
    assert 'href="/horses/1"' in response.text
    assert 'href="/jockeys/1"' in response.text
    assert 'href="/trainers/1"' in response.text
    assert 'href="/owners/1"' in response.text
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
    assert 'href="/horses/1"' in response.text
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

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
    assert "dashboard.css?v=14" in page.text


def test_dashboard_accepts_empty_racecourse_filter(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        response = client.get("/?date=2026-08-21&meet=")

    assert response.status_code == 200
    assert "전체 경마장" in response.text


def test_entity_list_and_detail_pages(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        horses = client.get("/horses?q=바람")
        horse_list = client.get("/horses")
        horse_by_name = client.get("/horses?sort=name")
        horse_detail = client.get("/horses/1")
        owners = client.get("/owners")
        owner_detail = client.get("/owners/1")
        missing = client.get("/ponies")

    assert horses.status_code == 200
    assert "바람의별" in horses.text
    assert "003001" in horses.text
    assert "적재 레이팅" in horses.text
    assert "출전 많은 순" in horses.text
    assert horse_list.text.index("바람의별") < horse_list.text.index("가가나")
    assert horse_by_name.text.index("가가나") < horse_by_name.text.index("바람의별")
    assert "체중" in horses.text
    assert "훈련" in horses.text

    assert horse_detail.status_code == 200
    assert "기본 정보" in horse_detail.text
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

    assert owners.status_code == 200
    assert "이마주" in owners.text
    assert owner_detail.status_code == 200
    assert "바람의별" in owner_detail.text
    assert missing.status_code == 404
