from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from horse_racing.db.engine import create_engine_for_url
from horse_racing.web import database


@pytest.fixture
def guarded_database(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'web.sqlite3'}"
    collector_engine = create_engine_for_url(url)
    with collector_engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT)")
        connection.exec_driver_sql("INSERT INTO sample VALUES (1, 'original')")
    factory = database.create_web_session_factory(url)
    yield factory, collector_engine
    factory.kw["bind"].dispose()
    collector_engine.dispose()


@pytest.mark.parametrize("statement", [
    "INSERT INTO sample VALUES (2, 'blocked')",
    "UPDATE sample SET name = 'blocked' WHERE id = 1",
    "DELETE FROM sample WHERE id = 1",
    "CREATE TABLE blocked (id INTEGER)",
])
def test_web_sessions_reject_writes_but_collectors_stay_writable(guarded_database, statement):
    factory, collector_engine = guarded_database
    with factory() as session:
        assert session.execute(text("SELECT name FROM sample")).scalar_one() == "original"
        with pytest.raises(DBAPIError, match="readonly"):
            session.execute(text(statement))
        session.rollback()
        assert session.execute(text("SELECT name FROM sample")).scalar_one() == "original"
    # Only the web engine is guarded, not the shared database or collector pool.
    with collector_engine.begin() as connection:
        connection.exec_driver_sql("UPDATE sample SET name = 'collected' WHERE id = 1")
    with factory() as session:
        assert session.execute(text("SELECT name FROM sample")).scalar_one() == "collected"


def test_web_guard_survives_commit_rollback_and_new_pool_connection(guarded_database):
    factory, _ = guarded_database
    for dispose in (False, True):
        if dispose:
            factory.kw["bind"].dispose()
        with factory() as session:
            assert session.autoflush is False
            for end_transaction in (session.commit, session.rollback):
                assert session.execute(text("PRAGMA query_only")).scalar_one() == 1
                end_transaction()
                with pytest.raises(DBAPIError, match="readonly"):
                    session.execute(text("UPDATE sample SET name = 'blocked'"))
                session.rollback()


def test_postgres_guard_uses_fixed_transaction_local_settings():
    connection = Mock()
    database._guard_postgres_transaction(connection)
    assert [call.args[0] for call in connection.exec_driver_sql.call_args_list] == [
        "SET TRANSACTION READ ONLY",
        "SET LOCAL statement_timeout = '15s'",
        "SET LOCAL lock_timeout = '3s'",
        "SET LOCAL idle_in_transaction_session_timeout = '20s'",
    ]


def test_postgres_guard_is_registered_on_every_engine_transaction():
    # Engine construction is lazy: no server/credential is needed to verify wiring.
    factory = database.create_web_session_factory("postgresql+psycopg://localhost/unused")
    engine = factory.kw["bind"]
    try:
        assert event.contains(engine, "begin", database._guard_postgres_transaction)
        assert engine.pool.size() == 2
    finally:
        engine.dispose()


@pytest.mark.parametrize("dedicated", [None, "sqlite:///:memory:"])
def test_default_web_factory_selects_optional_dedicated_credential(monkeypatch, dedicated):
    settings = SimpleNamespace(database_url="sqlite://", web_database_url=dedicated)
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    creator = Mock(return_value=Mock())
    monkeypatch.setattr(database, "create_web_session_factory", creator)
    database.get_web_session_factory.cache_clear()
    try:
        assert database.get_web_session_factory() is database.get_web_session_factory()
        creator.assert_called_once_with(dedicated or settings.database_url)
    finally:
        database.get_web_session_factory.cache_clear()


def test_app_default_uses_guarded_web_factory(monkeypatch, guarded_database):
    import importlib

    from fastapi.testclient import TestClient

    module = importlib.import_module("horse_racing.web.app")
    factory, _ = guarded_database
    spy = Mock(return_value=factory)
    monkeypatch.setattr(module, "get_web_session_factory", spy)
    with TestClient(module.create_app()) as client:
        assert client.get("/health/ready").status_code == 200
    spy.assert_called_once_with()
