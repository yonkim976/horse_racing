from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from test_race_day import api_payload, migrated_session
from test_race_supplemental import start_training_payload

from horse_racing.collectors.kra_api import KraApiClient
from horse_racing.db.models import HorseStartTraining
from horse_racing.parsers.race_supplemental import StartTrainingItem
from horse_racing.services.race_supplemental import _write_start_training, ingest_start_training


def test_repeated_items_across_pages_are_preserved_and_replay_is_idempotent(tmp_path: Path):
    sessions = migrated_session(tmp_path)
    item = start_training_payload()["response"]["body"]["items"]["item"][0]

    def response(request):
        page = int(request.url.params["pageNo"])
        p = api_payload([deepcopy(item)])
        p["response"]["body"].update(totalCount=2, numOfRows=1, pageNo=page)
        return httpx.Response(200, json=p)

    with (
        sessions() as session,
        KraApiClient("test-key", transport=httpx.MockTransport(response)) as client,
    ):
        for _ in range(2):
            result = ingest_start_training(
                session,
                client,
                training_date="20260823",
                meet=2,
                raw_data_dir=tmp_path / "raw",
                page_size=1,
            )
            assert result.records_written == 2
            rows = session.scalars(
                select(HorseStartTraining).order_by(HorseStartTraining.occurrence_no)
            ).all()
            assert [r.occurrence_no for r in rows] == [1, 2]
            assert rows[0].remark == rows[1].remark == "양호"
            assert all(r.source_document_id is not None and r.source_row_no == 1 for r in rows)
            assert rows[0].source_document_id != rows[1].source_document_id


def test_different_remark_survives_and_website_is_not_overwritten(tmp_path: Path):
    sessions = migrated_session(tmp_path)
    item = start_training_payload()["response"]["body"]["items"]["item"][0]
    other = {**item, "remark": "출발자세불량"}
    with sessions() as session:
        _write_start_training(
            session, [StartTrainingItem.model_validate(r) for r in [item, other]], 100
        )
        session.commit()
        rows = session.scalars(
            select(HorseStartTraining).order_by(HorseStartTraining.occurrence_no)
        ).all()
        assert [r.remark for r in rows] == ["양호", "출발자세불량"]
        for r in rows:
            r.source_kind = "kra_website"
            r.location_raw = "400M 출발지점" if r.occurrence_no == 1 else "800M 출발지점"
        session.commit()
        assert _write_start_training(session, [StartTrainingItem.model_validate(item)], 200) == 0
        session.commit()
        assert len(session.scalars(select(HorseStartTraining)).all()) == 2


def test_empty_and_older_snapshot_leave_newer_rows_intact(tmp_path: Path):
    sessions = migrated_session(tmp_path)
    item = StartTrainingItem.model_validate(
        start_training_payload()["response"]["body"]["items"]["item"][0]
    )
    with sessions() as session:
        _write_start_training(session, [item, item], 200)
        session.commit()
        assert _write_start_training(session, [], 300) == 0
        assert _write_start_training(session, [item], 100) == 0
        session.commit()
        assert len(session.scalars(select(HorseStartTraining)).all()) == 2
        assert _write_start_training(session, [item], 400) == 1
        session.commit()
        assert len(session.scalars(select(HorseStartTraining)).all()) == 1


def test_existing_legacy_rows_survive_migration(tmp_path: Path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    config = Config("alembic.ini")
    url = "sqlite:///" + str(tmp_path / "legacy.sqlite3")
    config.attributes["database_url"] = url
    command.upgrade(config, "20260930_0025")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO horses(id,kra_horse_id,name_ko) VALUES(1,'3107491','백두명성')")
        )
        conn.execute(
            text("""INSERT INTO horse_start_training(
                id,horse_id,meet_code,training_date_local,stable_part,
                stable_number,rider_name,remark,observed_at_ms)
        VALUES(1,1,2,'2026-08-26',8,13,'이동준','양호',1),(2,1,2,'2026-08-26',8,13,'문성호','양호',1)""")
        )
    command.upgrade(config, "head")
    with engine.connect() as conn:
        assert conn.execute(
            text(
                "SELECT id,rider_name,occurrence_no,source_kind "
                "FROM horse_start_training ORDER BY id"
            )
        ).all() == [(1, "이동준", 1, "legacy_api22"), (2, "문성호", 2, "legacy_api22")]




def test_failed_second_page_never_replaces_current_snapshot(tmp_path: Path):
    sessions = migrated_session(tmp_path)
    raw = start_training_payload()["response"]["body"]["items"]["item"][0]
    item = StartTrainingItem.model_validate(raw)

    def response(request):
        if request.url.params["pageNo"] == "2":
            return httpx.Response(
                200, json={"response": {"header": {"resultCode": "10", "resultMsg": "INVALID"}}}
            )
        payload = api_payload([raw])
        payload["response"]["body"].update(totalCount=2, numOfRows=1, pageNo=1)
        return httpx.Response(200, json=payload)

    with (
        sessions() as session,
        KraApiClient("test-key", transport=httpx.MockTransport(response)) as client,
    ):
        _write_start_training(session, [item, item], 1)
        session.commit()
        with pytest.raises(Exception, match="INVALID"):
            ingest_start_training(
                session,
                client,
                training_date="20260823",
                meet=2,
                raw_data_dir=tmp_path / "raw",
                page_size=1,
            )
        assert len(session.scalars(select(HorseStartTraining)).all()) == 2


def test_wrong_date_cannot_replace_snapshot(tmp_path: Path):
    sessions = migrated_session(tmp_path)
    item = StartTrainingItem.model_validate(
        start_training_payload()["response"]["body"]["items"]["item"][0]
    )
    with sessions() as session, pytest.raises(ValueError, match="요청 범위"):
        _write_start_training(session, [item], 1, expected_meet=2, expected_date="20260824")
