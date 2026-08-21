import argparse
from pathlib import Path

from sqlalchemy import inspect, text

from horse_racing.config import get_settings
from horse_racing.db.engine import create_engine_for_url


def database_path(database_url: str) -> Path | None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url == "sqlite:///:memory:":
        return None
    return Path(database_url.removeprefix(prefix)).resolve()


def db_info() -> int:
    settings = get_settings()
    engine = create_engine_for_url(settings.database_url)
    inspector = inspect(engine)

    with engine.connect() as connection:
        sqlite_version = connection.execute(text("select sqlite_version()")).scalar_one()
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
        foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()

    path = database_path(settings.database_url)
    print(f"database: {path or settings.database_url}")
    print(f"sqlite_version: {sqlite_version}")
    print(f"journal_mode: {journal_mode}")
    print(f"foreign_keys: {'on' if foreign_keys else 'off'}")
    print(f"tables: {', '.join(sorted(inspector.get_table_names())) or '(none)'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="horse-racing")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("db-info", help="Show local SQLite database information")
    args = parser.parse_args()

    if args.command == "db-info":
        return db_info()
    parser.error(f"unknown command: {args.command}")
    return 2
