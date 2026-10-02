"""Refresh one KRA race day in the explicitly selected production database.

The entry-sheet importer preserves scratch flags; apply fresh scratches last.
This script deliberately omits dividends and prediction publication.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo


def _database_url(project_ref: str, secret: str, gcp_project: str) -> str:
    result = subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            f"--secret={secret}",
            f"--project={gcp_project}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("운영 DB 비밀값을 읽지 못했습니다")
    url = result.stdout.strip()
    parsed = urlparse(url)
    if not parsed.scheme.startswith("postgres"):
        raise ValueError("PostgreSQL 연결만 허용합니다")
    if project_ref not in unquote(parsed.username or "") and project_ref not in (
        parsed.hostname or ""
    ):
        raise ValueError("연결 대상이 지정한 Supabase 프로젝트와 다릅니다")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="KST race date, YYYYMMDD")
    parser.add_argument("--meets", nargs="+", type=int, default=[1, 2], choices=[1, 2, 3, 4])
    parser.add_argument("--project-ref", required=True)
    parser.add_argument("--gcp-secret", required=True)
    parser.add_argument("--gcp-project", required=True)
    parser.add_argument("--page-size", type=int, default=100, help="KRA API page size")
    parser.add_argument("--confirm-write", action="store_true")
    args = parser.parse_args()
    datetime.strptime(args.date, "%Y%m%d")
    if not 1 <= args.page_size <= 1000:
        parser.error("--page-size는 1~1000이어야 합니다")
    if not args.confirm_write:
        parser.error("운영 DB 기록에는 --confirm-write가 필요합니다")
    os.environ["HORSE_RACING_DATABASE_URL"] = _database_url(
        args.project_ref, args.gcp_secret, args.gcp_project
    )

    # Imports must follow database selection: SessionLocal binds at import time.
    from horse_racing.collectors.kra_api import KraApiClient
    from horse_racing.config import get_settings
    from horse_racing.db.session import SessionLocal
    from horse_racing.services.horse_history import ingest_weights
    from horse_racing.services.race_day import ingest_race_day
    from horse_racing.services.race_supplemental import ingest_jockey_changes, ingest_scratches

    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        raise RuntimeError("공공데이터포털 서비스키가 설정되지 않았습니다")
    raw_dir = Path(settings.raw_data_dir)
    print(
        f"동기화 시작: {args.date} meets={args.meets} "
        f"{datetime.now(ZoneInfo('Asia/Seoul')).isoformat()}",
        flush=True,
    )
    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        # Capture errors by stage while continuing other independent endpoints.
        failures: list[str] = []
        for meet in args.meets:
            for name, operation in (
                (
                    "schedule_and_results",
                    lambda meet=meet: ingest_race_day(
                        session,
                        client,
                        race_date=args.date,
                        meet=meet,
                        raw_data_dir=raw_dir,
                        page_size=args.page_size,
                        include_dividends=False,
                    ),
                ),
                (
                    "jockey_changes",
                    lambda meet=meet: ingest_jockey_changes(
                        session,
                        client,
                        race_date=args.date,
                        meet=meet,
                        raw_data_dir=raw_dir,
                        page_size=args.page_size,
                    ),
                ),
                (
                    "weights",
                    lambda meet=meet: ingest_weights(
                        session,
                        client,
                        race_date=args.date,
                        meet=meet,
                        raw_data_dir=raw_dir,
                        page_size=args.page_size,
                    ),
                ),
                (
                    "scratches",
                    lambda meet=meet: ingest_scratches(
                        session,
                        client,
                        race_date=args.date,
                        meet=meet,
                        raw_data_dir=raw_dir,
                        page_size=args.page_size,
                    ),
                ),
            ):
                try:
                    summary = operation()
                    print(
                        f"meet={meet} {name}: fetched={summary.records_fetched} "
                        f"written={summary.records_written}",
                        flush=True,
                    )
                except Exception as exc:
                    session.rollback()
                    failures.append(f"meet={meet} {name}: {type(exc).__name__}: {exc}")
                    print(f"실패: meet={meet} {name}: {type(exc).__name__}: {exc}", flush=True)
        if failures:
            print(f"부분 실패 {len(failures)}건", flush=True)
            return 1
    print("동기화 완료", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
