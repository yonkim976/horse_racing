"""Refresh official KRA active/inactive horse status in the selected production DB."""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

from sync_live_race_day import _database_url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="KST snapshot date, YYYYMMDD")
    parser.add_argument("--meets", nargs="+", type=int, choices=(1, 2, 3), default=[1, 2, 3])
    parser.add_argument("--project-ref", required=True)
    parser.add_argument("--gcp-secret", required=True)
    parser.add_argument("--gcp-project", required=True)
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--confirm-write", action="store_true")
    args = parser.parse_args()

    datetime.strptime(args.date, "%Y%m%d")
    if not 1 <= args.page_size <= 1000:
        parser.error("--page-size는 1~1000이어야 합니다")
    if not args.confirm_write:
        parser.error("운영 DB 기록에는 --confirm-write가 필요합니다")

    os.environ["HORSE_RACING_DATABASE_URL"] = _database_url(
        args.project_ref,
        args.gcp_secret,
        args.gcp_project,
    )

    # Database-bound imports must follow explicit production URL selection.
    from horse_racing.collectors.kra_api import KraApiClient
    from horse_racing.config import get_settings
    from horse_racing.db.session import SessionLocal
    from horse_racing.services.horse_history import ingest_horse_active_statuses

    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        raise RuntimeError("공공데이터포털 서비스키가 설정되지 않았습니다")

    with (
        KraApiClient(
            settings.data_go_kr_service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=settings.http_timeout_seconds,
        ) as client,
        SessionLocal() as session,
    ):
        summary = ingest_horse_active_statuses(
            session,
            client,
            meets=args.meets,
            snapshot_date=args.date,
            raw_data_dir=Path(settings.raw_data_dir),
            page_size=args.page_size,
        )

    print(
        "말 현역 상태 동기화 완료: "
        f"run={summary.run_id}, pages={summary.pages}, "
        f"fetched={summary.records_fetched}, written={summary.records_written}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
