from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from horse_racing.collectors.kra_api import KraApiClient
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import (
    Horse,
    IngestionRun,
    Race,
    Racecourse,
    RaceEntry,
    SourceDocument,
)
from horse_racing.parsers.gate_entry_sheet import parse_gate_entry_sheet_page
from horse_racing.services.gate_entry_sheet import ingest_gate_numbers


def gate_payload(*, second_gate: int = 2) -> dict[str, object]:
    items = [
        {
            "raceDt": "2026년08월29일(토)",
            "raceNo": "제1경주",
            "gtno": "1",
            "hrnm": "테스트원",
        },
        {
            "raceDt": "2026년08월29일(토)",
            "raceNo": "제1경주",
            "gtno": str(second_gate),
            "hrnm": "테스트투",
        },
    ]
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "items": {"item": items},
                "pageNo": 1,
                "numOfRows": 1000,
                "totalCount": len(items),
            },
        }
    }


def migrated_session(tmp_path: Path) -> sessionmaker[Session]:
    database_url = f"sqlite:///{tmp_path / 'gate_entry_sheet.sqlite3'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
    engine = create_engine_for_url(database_url)
    return sessionmaker(bind=engine, expire_on_commit=False)


def seed_entries(session: Session) -> None:
    course = Racecourse(kra_meet_code=1, code="seoul", name_ko="서울")
    race = Race(
        racecourse=course,
        race_date_local=date(2026, 8, 29),
        race_number=1,
        distance_m=1200,
        status="scheduled",
    )
    first = Horse(kra_horse_id="005001", name_ko="테스트원")
    second = Horse(kra_horse_id="005002", name_ko="테스트투")
    session.add_all(
        [
            course,
            race,
            first,
            second,
            RaceEntry(race=race, horse=first, horse_number=1),
            RaceEntry(race=race, horse=second, horse_number=2),
        ]
    )
    session.commit()


def test_parse_gate_entry_sheet_page() -> None:
    page = parse_gate_entry_sheet_page(gate_payload())

    assert page.total_count == 2
    assert page.items[0].race_date == date(2026, 8, 29)
    assert page.items[0].race_number == 1
    assert page.items[0].gate_number == 1
    assert page.items[0].horse_name == "테스트원"


def test_ingest_gate_numbers_preserves_raw_and_updates_entries(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/B551015/API78/chulmainfo"
        assert request.url.params["serviceKey"] == "secret-test-key"
        assert request.url.params["rccrs_cd"] == "1"
        assert request.url.params["race_dt"] == "20260829"
        return httpx.Response(200, json=gate_payload(), request=request)

    session_factory = migrated_session(tmp_path)
    with (
        KraApiClient("secret-test-key", transport=httpx.MockTransport(handler)) as client,
        session_factory() as session,
    ):
        seed_entries(session)
        summary = ingest_gate_numbers(
            session,
            client,
            race_date="20260829",
            meet=1,
            raw_data_dir=tmp_path / "raw",
        )

        assert summary.pages == 1
        assert summary.records_fetched == 2
        assert summary.records_written == 2
        entries = list(session.scalars(select(RaceEntry).order_by(RaceEntry.horse_number)))
        assert [entry.gate_number for entry in entries] == [1, 2]

        run = session.scalar(select(IngestionRun))
        assert run is not None
        assert run.status == "completed"
        assert run.data_type == "gate_entry_sheet"
        document = session.scalar(select(SourceDocument))
        assert document is not None
        assert document.endpoint == "/API78/chulmainfo"
        assert "serviceKey" not in document.source_url
        assert Path(document.local_path).read_bytes()


def test_ingest_gate_numbers_ignores_home_region_label_difference(
    tmp_path: Path,
) -> None:
    payload = gate_payload()
    items = payload["response"]["body"]["items"]["item"]
    items[0]["hrnm"] = "[부]테스트원"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    session_factory = migrated_session(tmp_path)
    with (
        KraApiClient("secret-test-key", transport=httpx.MockTransport(handler)) as client,
        session_factory() as session,
    ):
        seed_entries(session)
        first = session.scalar(select(Horse).where(Horse.name_ko == "테스트원"))
        assert first is not None
        first.name_ko = "[영남]테스트원"
        session.commit()

        summary = ingest_gate_numbers(
            session,
            client,
            race_date="20260829",
            meet=1,
            raw_data_dir=tmp_path / "raw",
        )

        assert summary.records_written == 2


def test_ingest_gate_numbers_rejects_number_name_mismatch(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=gate_payload(second_gate=3), request=request)

    session_factory = migrated_session(tmp_path)
    with (
        KraApiClient("secret-test-key", transport=httpx.MockTransport(handler)) as client,
        session_factory() as session,
    ):
        seed_entries(session)
        with pytest.raises(ValueError, match="출주번호가 다릅니다"):
            ingest_gate_numbers(
                session,
                client,
                race_date="20260829",
                meet=1,
                raw_data_dir=tmp_path / "raw",
            )
        run = session.scalar(select(IngestionRun))
        assert run is not None
        assert run.status == "failed"
