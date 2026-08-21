from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import (
    Horse,
    Jockey,
    OddsSnapshot,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    Trainer,
)
from horse_racing.web.app import create_app


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
        horse = Horse(kra_horse_id="003001", name_ko="바람의별", sex="거", origin_country="한국")
        jockey = Jockey(kra_jockey_id="080101", name_ko="한기수")
        trainer = Trainer(kra_trainer_id="070101", name_ko="김조교")
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
        session.add_all(
            [
                racecourse,
                horse,
                jockey,
                trainer,
                race,
                entry,
                result,
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
            ]
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
    assert "1:15.2" in response.text
    assert "2.1배" in response.text
    assert "15,000,000원" in response.text


def test_dashboard_health_check(tmp_path: Path) -> None:
    app = create_app(seeded_session(tmp_path))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
