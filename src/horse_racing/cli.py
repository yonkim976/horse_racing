import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import inspect, text

from horse_racing.collectors.kra_api import KraApiClient, KraApiError, KraApiRateLimitError
from horse_racing.config import get_settings
from horse_racing.db.engine import create_engine_for_url
from horse_racing.db.session import SessionLocal
from horse_racing.services.entry_sheet import MEET_METADATA, ingest_entry_sheet
from horse_racing.services.race_day import (
    final_dividend_is_complete,
    ingest_final_dividends,
    ingest_race_day,
    ingest_race_schedule,
    race_day_is_complete,
    repair_missing_entry_people,
    result_data_exists,
    result_day_is_stored,
)


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


def collect_race_day(race_date: str, meet: int, page_size: int) -> int:
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
        summary = ingest_race_day(
            session,
            client,
            race_date=race_date,
            meet=meet,
            raw_data_dir=settings.raw_data_dir,
            page_size=page_size,
        )

    meet_name = MEET_METADATA[meet][1]
    print(f"하루치 수집 완료: 경마장={meet_name}, 날짜={race_date}")
    for stage_name, stage in summary.stages.items():
        print(
            f"  {stage_name}: run={stage.run_id}, pages={stage.pages}, "
            f"fetched={stage.records_fetched}, written={stage.records_written}"
        )
    print(f"합계: fetched={summary.records_fetched}, written={summary.records_written}")
    return 0


def collect_schedule(race_dates: list[str], meets: list[int], page_size: int) -> int:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        print(
            "HORSE_RACING_DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.",
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
        for race_date in race_dates:
            for meet in meets:
                summary = ingest_race_schedule(
                    session,
                    client,
                    race_date=race_date,
                    meet=meet,
                    raw_data_dir=settings.raw_data_dir,
                    page_size=page_size,
                )
                fetched = summary.records_fetched
                if fetched:
                    print(
                        f"일정 수집: 날짜={race_date}, 경마장={MEET_METADATA[meet][1]}, "
                        f"fetched={fetched}",
                        flush=True,
                    )
                session.expunge_all()
    return 0


def backfill_results(
    start_date: str,
    end_date: str,
    meets: list[int],
    page_size: int,
    include_dividends: bool,
) -> int:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        print(
            "HORSE_RACING_DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.",
            file=sys.stderr,
        )
        return 2

    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()
    if start > end:
        raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")

    checked = 0
    found = 0
    collected = 0
    skipped = 0
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        current = start
        while current <= end:
            race_date = current.strftime("%Y%m%d")
            for meet in meets:
                checked += 1
                day_is_complete = (
                    race_day_is_complete(session, race_date=current, meet=meet)
                    if include_dividends
                    else result_day_is_stored(session, race_date=current, meet=meet)
                )
                if day_is_complete:
                    found += 1
                    skipped += 1
                    print(
                        f"기존 완료 데이터 유지: {race_date} {MEET_METADATA[meet][1]}",
                        flush=True,
                    )
                    continue
                if not result_data_exists(client, race_date=race_date, meet=meet):
                    if checked % 21 == 0:
                        print(
                            f"결과일 탐색 중: {race_date} / 확인 {checked}건",
                            flush=True,
                        )
                    continue

                found += 1
                summary = ingest_race_day(
                    session,
                    client,
                    race_date=race_date,
                    meet=meet,
                    raw_data_dir=settings.raw_data_dir,
                    page_size=page_size,
                    include_dividends=include_dividends,
                )
                collected += 1
                print(
                    f"결과 수집 완료: {race_date} {MEET_METADATA[meet][1]} / "
                    f"fetched={summary.records_fetched}",
                    flush=True,
                )
                session.expunge_all()
            current += timedelta(days=1)

    print(
        f"백필 완료: 기간={start_date}~{end_date}, 확인={checked}, "
        f"경주일={found}, 신규수집={collected}, 기존완료={skipped}",
        flush=True,
    )
    return 0


def backfill_dividends(
    start_date: str,
    end_date: str,
    meets: list[int],
    page_size: int,
) -> int:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        print(
            "HORSE_RACING_DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.",
            file=sys.stderr,
        )
        return 2

    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date()
    if start > end:
        raise ValueError("시작일은 종료일보다 늦을 수 없습니다.")

    stored_days = 0
    collected = 0
    skipped = 0
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        current = start
        while current <= end:
            race_date = current.strftime("%Y%m%d")
            for meet in meets:
                if not result_day_is_stored(session, race_date=current, meet=meet):
                    continue
                stored_days += 1
                if final_dividend_is_complete(session, race_date=current, meet=meet):
                    skipped += 1
                    continue
                while True:
                    try:
                        summary = ingest_final_dividends(
                            session,
                            client,
                            race_date=race_date,
                            meet=meet,
                            raw_data_dir=settings.raw_data_dir,
                            page_size=page_size,
                        )
                    except KraApiRateLimitError as exc:
                        print(f"확정배당 호출 제한 대기: {exc}", flush=True)
                        time.sleep(55)
                        continue
                    break
                collected += 1
                print(
                    f"확정배당 수집 완료: {race_date} {MEET_METADATA[meet][1]} / "
                    f"pages={summary.pages}, fetched={summary.records_fetched}, "
                    f"written={summary.records_written}",
                    flush=True,
                )
                session.expunge_all()
            current += timedelta(days=1)

    print(
        f"확정배당 백필 완료: 저장된 경주일={stored_days}, 신규수집={collected}, "
        f"기존완료={skipped}",
        flush=True,
    )
    return 0


def serve_dashboard(host: str, port: int, reload: bool) -> int:
    import uvicorn

    uvicorn.run(
        "horse_racing.web.app:app",
        host=host,
        port=port,
        reload=reload,
    )
    return 0


def repair_entry_links() -> int:
    with SessionLocal() as session:
        summary = repair_missing_entry_people(session)
    print(
        f"관계자 연결 복구: 확인={summary.examined}, 복구={summary.repaired}, "
        f"미해결={summary.unresolved}"
    )
    return 0 if summary.unresolved == 0 else 1


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
    race_day_parser = subparsers.add_parser(
        "collect-race-day",
        help="Collect plans, entries, results, details, and final dividends",
    )
    race_day_parser.add_argument("--date", required=True, type=valid_race_date)
    race_day_parser.add_argument("--meet", required=True, type=int, choices=sorted(MEET_METADATA))
    race_day_parser.add_argument("--page-size", type=int, default=1000)
    schedule_parser = subparsers.add_parser(
        "collect-schedule",
        help="Collect race plans and entry sheets for one or more dates",
    )
    schedule_parser.add_argument("--dates", required=True, nargs="+", type=valid_race_date)
    schedule_parser.add_argument(
        "--meets", nargs="+", type=int, choices=sorted(MEET_METADATA), default=[1, 2, 3]
    )
    schedule_parser.add_argument("--page-size", type=int, default=1000)
    backfill_parser = subparsers.add_parser(
        "backfill-results",
        help="Discover and collect every completed race day in a date range",
    )
    backfill_parser.add_argument("--start", required=True, type=valid_race_date)
    backfill_parser.add_argument("--end", required=True, type=valid_race_date)
    backfill_parser.add_argument(
        "--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3]
    )
    backfill_parser.add_argument("--page-size", type=int, default=1000)
    backfill_parser.add_argument("--skip-dividends", action="store_true")
    dividend_parser = subparsers.add_parser(
        "backfill-dividends",
        help="Collect final dividends for stored result days missing them",
    )
    dividend_parser.add_argument("--start", required=True, type=valid_race_date)
    dividend_parser.add_argument("--end", required=True, type=valid_race_date)
    dividend_parser.add_argument(
        "--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3]
    )
    dividend_parser.add_argument("--page-size", type=int, default=20_000)
    dashboard_parser = subparsers.add_parser(
        "serve-dashboard",
        help="Run the local race schedule and result dashboard",
    )
    dashboard_parser.add_argument("--host", default="127.0.0.1")
    dashboard_parser.add_argument("--port", type=int, default=8000)
    dashboard_parser.add_argument("--reload", action="store_true")
    subparsers.add_parser(
        "repair-entry-links",
        help="Repair missing trainer and owner links from stable horse history",
    )
    args = parser.parse_args()

    if args.command == "db-info":
        return db_info()
    if args.command == "collect-entry-sheet":
        try:
            return collect_entry_sheet(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-race-day":
        try:
            return collect_race_day(args.date, args.meet, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "collect-schedule":
        try:
            return collect_schedule(args.dates, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"일정 수집 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-results":
        try:
            return backfill_results(
                args.start,
                args.end,
                args.meets,
                args.page_size,
                not args.skip_dividends,
            )
        except (KraApiError, ValueError) as exc:
            print(f"백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "backfill-dividends":
        try:
            return backfill_dividends(args.start, args.end, args.meets, args.page_size)
        except (KraApiError, ValueError) as exc:
            print(f"확정배당 백필 실패: {exc}", file=sys.stderr)
            return 1
    if args.command == "serve-dashboard":
        return serve_dashboard(args.host, args.port, args.reload)
    if args.command == "repair-entry-links":
        return repair_entry_links()
    parser.error(f"unknown command: {args.command}")
    return 2
