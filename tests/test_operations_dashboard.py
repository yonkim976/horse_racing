"""Offline tests: loopback boundary, read guards, bounded reads and gap semantics."""

import re
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from horse_racing.db.base import Base
from horse_racing.db.models import (
    Horse,
    HorseMedical,
    HorseStartTraining,
    HorseTraining,
    IngestionRun,
    Race,
    Racecourse,
    RaceEntry,
    RacePassingGroup,
    RacePointSourceBatch,
    RaceResult,
    RaceStewardReport,
    SourceDocument,
)
from horse_racing.operations import database
from horse_racing.operations import read_model as read
from horse_racing.operations.app import create_app

NOW = datetime(2026, 10, 19, 12, tzinfo=read.KST)


@pytest.fixture
def sessions():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        session.add_all(
            [
                Horse(
                    id=1,
                    kra_horse_id="001001",
                    name_ko="테스트말",
                    is_active=True,
                    active_status_observed_at_ms=1,
                    active_status_source="test",
                ),
                Horse(id=2, kra_horse_id="001002", name_ko="다른말"),
                Racecourse(id=1, kra_meet_code=1, code="seoul", name_ko="서울"),
                Racecourse(id=2, kra_meet_code=2, code="jeju", name_ko="제주"),
            ]
        )
        session.flush()
        for i, day in enumerate(
            [date(2026, 10, 16), date(2026, 10, 17), date(2026, 10, 18), date(2026, 10, 19)], 1
        ):
            session.add(
                Race(
                    id=i,
                    racecourse_id=1,
                    race_date_local=day,
                    race_number=1,
                    distance_m=1200,
                    field_size=2,
                    status="completed",
                )
            )
        session.flush()
        session.add_all(
            [
                RaceEntry(id=1, race_id=1, horse_id=1, horse_number=1, scratched=False),
                RaceEntry(id=2, race_id=1, horse_id=2, horse_number=2, scratched=True),
                RaceEntry(id=3, race_id=2, horse_id=1, horse_number=1, scratched=False),
            ]
        )
        session.flush()
        session.add(RaceResult(race_entry_id=3, finish_position=1, finish_time_ms=70000))
        session.add(
            RacePointSourceBatch(
                id=1,
                source_file="test.txt",
                source_sha256="a" * 64,
                meet_code=1,
                race_year=2026,
                section_row_count=0,
                passing_group_row_count=1,
                loaded_at_ms=1,
            )
        )
        session.flush()
        session.add(
            RacePassingGroup(race_id=1, point_code="S1F", notation_raw="1-2", source_batch_id=1)
        )
        session.add(
            RaceStewardReport(
                meet_code=1,
                race_date_local=date(2026, 10, 16),
                race_number=1,
                judgement="공식 원문",
                observed_at_ms=1,
            )
        )
        ms = int(NOW.timestamp() * 1000)
        session.add_all(
            [
                IngestionRun(
                    id=1,
                    source="kra",
                    data_type="horse_medical",
                    started_at_ms=ms - 3600000,
                    completed_at_ms=ms - 3500000,
                    status="failed",
                    error_message="postgresql://user:SECRET@host/db",
                ),
                IngestionRun(
                    id=2,
                    source="kra",
                    data_type="horse_medical",
                    started_at_ms=ms,
                    completed_at_ms=ms + 1000,
                    status="completed",
                    records_fetched=0,
                ),
                IngestionRun(
                    id=3,
                    source="kra",
                    data_type="horse_training",
                    started_at_ms=ms,
                    completed_at_ms=ms + 1000,
                    status="completed",
                    records_fetched=3,
                ),
            ]
        )
        session.flush()
        session.add(
            SourceDocument(
                ingestion_run_id=1,
                source_url="https://host?serviceKey=SECRET",
                endpoint="/API33",
                operation="medical",
                request_params_json='{"key":"SECRET"}',
                requested_at_ms=1,
                retrieved_at_ms=2,
                local_path="/private/SECRET",
                sha256="a" * 64,
            )
        )
        session.add(
            HorseMedical(
                horse_id=1,
                meet_code=1,
                clinic_date_local=date(2026, 10, 16),
                hospital_name="병원",
                diagnosis_1="<script>alert(1)</script>",
                diagnosis_2="진단2",
                observed_at_ms=1,
            )
        )
        session.add(
            HorseTraining(
                horse_id=1,
                meet_code=1,
                training_date_local=date(2026, 10, 16),
                rider_type="조교사",
                rider_id="secretname",
                duration_seconds=150,
                started_at_raw="06:00",
                ended_at_raw="06:03",
                observed_at_ms=1,
            )
        )
        session.add_all(
            [
                HorseStartTraining(
                    horse_id=1,
                    meet_code=2,
                    training_date_local=date(2026, 10, 16),
                    occurrence_no=n,
                    rider_name="조",
                    observed_at_ms=1,
                    source_kind="api",
                )
                for n in (1, 2)
            ]
        )
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA query_only = ON")
    yield factory
    engine.dispose()


@pytest.fixture
def client(sessions):
    # TestClient defaults to 'testclient', which is intentionally NOT loopback.
    app = create_app(session_factory=sessions)
    with TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 12345)) as c:
        html = c.get("/").text
        token = re.search(r'name="ops-token" content="([^"]+)"', html)[1]
        c.headers["X-Operations-Token"] = token
        yield c


def test_local_security_and_fixed_assets(client):
    assert client.get("/").status_code == 200
    assert client.get("/assets/dashboard.css").status_code == 200
    assert client.get("/assets/dashboard.js").status_code == 200
    assert client.get("/assets/.env").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/api/overview", headers={"Host": "attacker.example"}).status_code == 403
    assert (
        client.get("/api/overview", headers={"Origin": "https://attacker.example"}).status_code
        == 403
    )
    assert client.get("/api/overview", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.get("/api/overview", headers={"X-Operations-Token": "wrong"}).status_code == 403
    assert (
        client.get(
            "/api/overview", headers={"X-Operations-Token": "한글".encode().hex()}
        ).status_code
        == 403
    )
    assert client.post("/api/runs").status_code == 405
    assert client.delete("/api/runs/1").status_code == 405
    assert client.get("/").headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in client.get("/").headers["Content-Security-Policy"]


def test_nonloopback_client_is_rejected(sessions):
    with TestClient(
        create_app(session_factory=sessions),
        base_url="http://127.0.0.1:8765",
        client=("192.168.1.25", 12345),
    ) as client:
        assert client.get("/").status_code == 403


def test_missing_token(client):
    del client.headers["X-Operations-Token"]
    assert client.get("/api/overview").status_code == 403


def test_actual_readonly_connection_rejects_mutation(sessions):
    with sessions() as session, pytest.raises(OperationalError, match="readonly"):
        session.execute(text("DELETE FROM horses"))


def test_postgres_guards_set_before_query():
    class Fake:
        def __init__(self):
            self.calls = []

        def exec_driver_sql(self, sql):
            self.calls.append(sql)

    conn = Fake()
    database.guard_transaction(conn)
    assert conn.calls[0] == "SET TRANSACTION READ ONLY"
    assert any("statement_timeout" in sql for sql in conn.calls)
    assert all(sql.startswith("SET ") for sql in conn.calls)


def test_latest_success_and_empty_response_not_false_failure(sessions):
    with sessions() as session:
        data = read.overview(session, NOW)
    medical = next(c for c in data["categories"] if c["key"] == "medical")
    assert medical["state"] == "completed"
    assert medical["latest"]["id"] == medical["latest_success"]["id"] == 2
    assert medical["empty_response"] is True
    assert "SECRET" not in str(data)


def test_latest_uses_timestamp_not_import_id(sessions):
    # Read-only fixture: exercise ordering through a separate tiny writable DB.
    engine = create_engine("sqlite://")
    IngestionRun.__table__.create(engine)
    ms = int(NOW.timestamp() * 1000)
    with engine.begin() as c:
        c.execute(
            IngestionRun.__table__.insert(),
            [
                dict(
                    id=1,
                    source="x",
                    data_type="horse_medical",
                    status="completed",
                    started_at_ms=ms,
                ),
                dict(
                    id=2,
                    source="x",
                    data_type="horse_medical",
                    status="failed",
                    started_at_ms=ms - 1000,
                ),
            ],
        )
    with sessionmaker(bind=engine)() as s:
        assert (
            next(x for x in read.overview(s, NOW)["categories"] if x["key"] == "medical")["latest"][
                "id"
            ]
            == 1
        )
    engine.dispose()


def test_history_boundaries_and_secret_redaction(client):
    response = client.get("/api/runs", params={"start": "2026-10-19", "end": "2026-10-19"})
    assert response.status_code == 200
    assert len(response.json()["rows"]) == 3
    assert "SECRET" not in response.text
    detail = client.get("/api/runs/1")
    assert detail.status_code == 200
    assert detail.json()["run"]["has_error"]
    assert detail.json()["documents"][0]["endpoint"] == "/API33"
    assert "SECRET" not in detail.text
    assert "local_path" not in detail.text and "source_url" not in detail.text
    assert client.get("/api/runs/999").status_code == 404
    assert (
        client.get("/api/runs", params={"start": "2026-10-01", "end": "2026-12-01"}).status_code
        == 422
    )
    assert (
        client.get("/api/runs", params={"start": "2026-10-20", "end": "2026-10-19"}).status_code
        == 422
    )


def test_history_pagination_no_duplicate_ids():
    engine = create_engine("sqlite://")
    IngestionRun.__table__.create(engine)
    ms = int(NOW.timestamp() * 1000)
    with engine.begin() as c:
        c.execute(
            IngestionRun.__table__.insert(),
            [
                dict(id=i, source="x", data_type="x", status="completed", started_at_ms=ms)
                for i in range(1, 104)
            ],
        )
    with sessionmaker(bind=engine)() as session:
        first = read.history(session, NOW.date(), NOW.date())
        second = read.history(session, NOW.date(), NOW.date(), before_id=first["next_cursor"])
        assert len(first["rows"]) == len(second["rows"]) == 50
        assert not {r["id"] for r in first["rows"]} & {r["id"] for r in second["rows"]}
    engine.dispose()


@pytest.mark.parametrize("kind", ["entries", "sections", "groups", "stewards", "trials"])
def test_race_search_routes(client, kind):
    response = client.get(
        "/api/data", params={"kind": kind, "start": "2026-10-16", "end": "2026-10-19", "meet": 1}
    )
    assert response.status_code == 200, response.text
    assert "rows" in response.json()


@pytest.mark.parametrize("kind", ["training", "medical", "start", "swim"])
def test_care_search_requires_horse_and_works(client, kind):
    params = {"kind": kind, "start": "2026-10-16", "end": "2026-10-19"}
    empty = client.get("/api/data", params=params).json()
    assert empty["rows"] == [] and "말을 먼저" in empty["notes"][0]
    response = client.get("/api/data", params=params | {"horse_id": 1})
    assert response.status_code == 200, response.text
    if kind == "training":
        assert response.json()["rows"][0]["rider"] == "조교사"
    if kind == "medical":
        assert response.json()["rows"][0]["diagnosis_2"] == "진단2"
    if kind == "start":
        assert len(response.json()["rows"]) == 2  # preserve same-day multiplicity
        assert {r["occurrence"] for r in response.json()["rows"]} == {1, 2}


def test_search_allowlist_and_horse_wildcards(client):
    assert (
        client.get("/api/horses", params={"q": "테스트"}).json()["rows"][0]["kra_horse_id"]
        == "001001"
    )
    for query in ["%%", "__", "'; DROP TABLE horses;--"]:
        assert client.get("/api/horses", params={"q": query}).json()["rows"] == []
    assert (
        client.get(
            "/api/data",
            params={"kind": "source_documents", "start": "2026-10-16", "end": "2026-10-19"},
        ).status_code
        == 422
    )


def test_gaps_wait_for_publication_and_ignore_scratches(sessions):
    with sessions() as session:
        data = read.suspected_gaps(session, NOW)
    assert data["checked_races"] == 2  # today's and yesterday's unfinished publication excluded
    issues = data["issues"]
    assert any(i["kind"] == "results" and i["horse"] == "테스트말" for i in issues)
    assert not any(i["horse"] == "다른말" for i in issues)
    assert any(i["kind"] == "sections" and i["race_id"] == 2 for i in issues)
    assert not any(i["kind"] in {"groups", "stewards"} and i["race_id"] == 1 for i in issues)
    assert not any(i["kind"] in {"medical", "training"} for i in issues)


def test_dashboard_never_calls_collector_or_write_paths(client, sessions):
    statements = []
    engine = sessions.kw["bind"]

    def record(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.strip().upper())

    event.listen(engine, "before_cursor_execute", record)
    try:
        client.get("/api/overview")
        client.get("/api/issues")
        client.get("/api/runs/1")
        client.get(
            "/api/data",
            params={"kind": "medical", "horse_id": 1, "start": "2026-10-16", "end": "2026-10-19"},
        )
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert statements and all(sql.startswith("SELECT") for sql in statements)


def test_hill_queries_only_current_view(sessions):
    # A minimal stand-in for the production view, never modify an operational DB.
    engine = create_engine("sqlite://")
    Horse.__table__.create(engine)
    with engine.begin() as c:
        c.execute(Horse.__table__.insert(), dict(id=1, kra_horse_id="001001", name_ko="말"))
        c.exec_driver_sql("""CREATE VIEW horse_hill_training_current AS
          SELECT 1 id, 1 horse_id, '2026-10-16' training_date_local, '목장' farm_name,
          '06:00' training_time_local, 1 f1_seconds, 2 f2_seconds, 3 f3_seconds,
          6 total_seconds, 'valid' quality_status, 2 metadata_version_count""")
    with sessionmaker(bind=engine)() as s:
        data = read.search_data(s, "hill", date(2026, 10, 16), date(2026, 10, 16), horse_id=1)
    assert len(data["rows"]) == 1
    assert data["rows"][0]["metadata_version_count"] == 2
    engine.dispose()


def test_database_failure_is_safe(client, monkeypatch):
    def fail(*args, **kwargs):
        raise OperationalError("postgresql://SECRET", {}, Exception("SECRET"))

    monkeypatch.setattr(read, "overview", fail)
    response = client.get("/api/overview")
    assert response.status_code == 503
    assert "SECRET" not in response.text


def test_postgres_target_guard(monkeypatch):
    monkeypatch.setenv(
        "HORSE_RACING_OPERATIONS_DATABASE_URL", "postgresql://x:fake@attacker.invalid/postgres"
    )
    with pytest.raises(ValueError, match="target"):
        database.resolve_url()
    monkeypatch.setenv(
        "HORSE_RACING_OPERATIONS_DATABASE_URL", "sqlite:///data/horse_racing.sqlite3"
    )
    with pytest.raises(ValueError, match="requires_postgres"):
        database.resolve_url()


def test_database_url_keeps_credentials_server_side_and_tls(monkeypatch):
    monkeypatch.setenv(
        "HORSE_RACING_OPERATIONS_DATABASE_URL",
        "postgresql://reader.xkykmhhkjtosptoibduo:fake@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres?sslmode=disable",
    )
    url = database.resolve_url()
    assert url.query["sslmode"] == "require"
    assert url.drivername == "postgresql+psycopg"
