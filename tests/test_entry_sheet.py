import json
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from horse_racing.collectors.kra_api import KraApiClient
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.models import Horse, IngestionRun, Race, RaceEntry, SourceDocument
from horse_racing.parsers.entry_sheet import parse_entry_sheet_page
from horse_racing.services.entry_sheet import ingest_entry_sheet

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "entry_sheet_page.json"


def load_fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def migrated_session(tmp_path: Path) -> sessionmaker[Session]:
    database_url = f"sqlite:///{tmp_path / 'entry_sheet.sqlite3'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")
    engine = create_engine_for_url(database_url)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_parse_entry_sheet_page() -> None:
    page = parse_entry_sheet_page(load_fixture())

    assert page.total_count == 2
    assert len(page.items) == 2
    assert page.items[0].horse_id == "5001"
    assert page.items[0].carried_weight_kg == 55.5
    assert page.items[0].race_date.isoformat() == "2026-08-22"


def test_ingest_entry_sheet_preserves_raw_and_upserts_database(tmp_path: Path) -> None:
    payload = load_fixture()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/B551015/API26_2/entrySheet_2"
        assert request.url.params["ServiceKey"] == "secret-test-key"
        assert request.url.params["rc_date"] == "20260822"
        return httpx.Response(200, json=payload, request=request)

    session_factory = migrated_session(tmp_path)
    with (
        KraApiClient(
            "secret-test-key",
            transport=httpx.MockTransport(handler),
        ) as client,
        session_factory() as session,
    ):
        summary = ingest_entry_sheet(
            session,
            client,
            race_date="20260822",
            meet=1,
            raw_data_dir=tmp_path / "raw",
        )

        assert summary.pages == 1
        assert summary.records_fetched == 2
        assert summary.records_written == 2
        assert len(session.scalars(select(Horse)).all()) == 2
        assert len(session.scalars(select(Race)).all()) == 1
        assert len(session.scalars(select(RaceEntry)).all()) == 2

        run = session.scalar(select(IngestionRun))
        assert run is not None
        assert run.status == "completed"

        document = session.scalar(select(SourceDocument))
        assert document is not None
        assert "ServiceKey" not in document.source_url
        assert "ServiceKey" not in document.request_params_json
        assert document.endpoint == "/API26_2/entrySheet_2"
        assert Path(document.local_path).read_bytes()
