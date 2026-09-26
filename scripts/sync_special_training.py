"""Backfill or refresh official KRA swimming and hill-track training histories."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("swim", "hill", "both"), default="both")
    parser.add_argument("--swim-start-year", type=int, default=2000)
    parser.add_argument("--swim-end-year", type=int, default=datetime.now().year)
    parser.add_argument("--hill-start-date", default="20000101")
    parser.add_argument("--hill-end-date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--page-size", type=int, default=20_000)
    parser.add_argument("--confirm-write", action="store_true")
    args = parser.parse_args()

    if not args.confirm_write:
        parser.error("DB 기록에는 --confirm-write가 필요합니다")
    if not 1 <= args.page_size <= 20_000:
        parser.error("--page-size는 1~20000이어야 합니다")
    datetime.strptime(args.hill_start_date, "%Y%m%d")
    datetime.strptime(args.hill_end_date, "%Y%m%d")

    from horse_racing.collectors.special_training import KraXmlApiClient
    from horse_racing.config import get_settings
    from horse_racing.db.session import SessionLocal
    from horse_racing.services.special_training import (
        ingest_hill_training,
        ingest_swim_training,
    )

    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        raise RuntimeError("공공데이터포털 서비스키가 설정되지 않았습니다")

    with KraXmlApiClient(
        settings.data_go_kr_service_key.get_secret_value(),
        base_url=settings.kra_api_base_url,
        timeout_seconds=max(settings.http_timeout_seconds, 60.0),
    ) as client:
        if args.dataset in {"swim", "both"}:
            with SessionLocal() as session:
                summary = ingest_swim_training(
                    session,
                    client,
                    start_year=args.swim_start_year,
                    end_year=args.swim_end_year,
                    raw_data_dir=Path(settings.raw_data_dir),
                    page_size=args.page_size,
                )
            print(
                "수영조교 동기화 완료: "
                f"run={summary.run_id}, pages={summary.pages}, "
                f"fetched={summary.records_fetched}, written={summary.records_written}"
            )

        if args.dataset in {"hill", "both"}:
            with SessionLocal() as session:
                summary = ingest_hill_training(
                    session,
                    client,
                    start_date=args.hill_start_date,
                    end_date=args.hill_end_date,
                    raw_data_dir=Path(settings.raw_data_dir),
                    page_size=args.page_size,
                )
            print(
                "언덕주로 동기화 완료: "
                f"run={summary.run_id}, pages={summary.pages}, "
                f"fetched={summary.records_fetched}, written={summary.records_written}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
