from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from horse_racing.db.engine import create_engine_for_url

EXPECTED_TABLES = {
    "alembic_version",
    "horses",
    "ingestion_runs",
    "jockeys",
    "odds_snapshots",
    "owners",
    "race_entries",
    "race_results",
    "race_section_results",
    "racecourses",
    "races",
    "source_documents",
    "trainers",
}


def test_initial_migration_creates_expected_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "test.sqlite3"
    database_url = f"sqlite:///{database_path}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")

    engine = create_engine_for_url(database_url)
    assert set(inspect(engine).get_table_names()) == EXPECTED_TABLES
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == "20260821_0002"


def test_sqlite_pragmas_are_enabled(tmp_path: Path) -> None:
    engine = create_engine_for_url(f"sqlite:///{tmp_path / 'pragma.sqlite3'}")
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert connection.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
        assert connection.execute(text("PRAGMA busy_timeout")).scalar_one() == 5000
