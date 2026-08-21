import argparse
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect, text

from horse_racing.collectors.kra_api import KraApiClient, KraApiError
from horse_racing.config import get_settings
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.session import SessionLocal
from horse_racing.services.entry_sheet import MEET_METADATA, ingest_entry_sheet


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


def valid_race_date(value: str) -> str:
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("날짜는 YYYYMMDD 형식이어야 합니다.") from exc
    return value


def collect_entry_sheet(race_date: str, meet: int, page_size: int) -> int:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        print(
            "HORSE_RACING_DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다. "
            ".env에 공공데이터포털 일반 인증키(Decoding)를 입력하세요.",
            file=sys.stderr,
        )
        return 2

    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        summary = ingest_entry_sheet(
            session,
            client,
            race_date=race_date,
            meet=meet,
            raw_data_dir=settings.raw_data_dir,
            page_size=page_size,
        )

    meet_name = MEET_METADATA[meet][1]
    print(
        f"수집 완료: run={summary.run_id}, 경마장={meet_name}, 날짜={race_date}, "
        f"pages={summary.pages}, fetched={summary.records_fetched}, "
        f"written={summary.records_written}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="horse-racing")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("db-info", help="Show local SQLite database information")
    entry_sheet_parser = subparsers.add_parser(
        "collect-entry-sheet",
        help="Collect a KRA entry sheet from data.go.kr",
    )
    entry_sheet_parser.add_argument("--date", required=True, type=valid_race_date)
    entry_sheet_parser.add_argument(
        "--meet", required=True, type=int, choices=sorted(MEET_METADATA)
    )
    entry_sheet_parser.add_argument("--page-size", type=int, default=100)
    args = parser.parse_args()

    if args.command == "db-info":
        return db_info()
    if args.command == "collect-entry-sheet":
        try:
            return collect_entry_sheet(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"수집 실패: {exc}", file=sys.stderr)
            return 1
    parser.error(f"unknown command: {args.command}")
    return 2
