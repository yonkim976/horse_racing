"""Archive official KRA monthly training responses without changing model tables."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import time
from datetime import date
from pathlib import Path

from horse_racing.collectors.kra_api import (
    DAILY_TRAINING_ENDPOINT,
    DAILY_TRAINING_OPERATION,
    START_TRAINING_ENDPOINT,
    START_TRAINING_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings

DATASETS = {
    "horse_training": (DAILY_TRAINING_ENDPOINT, DAILY_TRAINING_OPERATION),
    "start_training": (START_TRAINING_ENDPOINT, START_TRAINING_OPERATION),
}


def months_between(start: str, end: str) -> list[str]:
    start_date = date(int(start[:4]), int(start[4:]), 1)
    end_date = date(int(end[:4]), int(end[4:]), 1)
    if end_date < start_date:
        raise ValueError("end must not precede start")
    months: list[str] = []
    year, month = start_date.year, start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        months.append(f"{year:04d}{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def _items(payload: dict) -> list[dict]:
    container = response_body(payload).get("items")
    if not isinstance(container, dict):
        return []
    value = container.get("item")
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _read_page(path: Path) -> dict:
    body = path.read_bytes()
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid cached page: {path}")
    return payload


def _atomic_write(path: Path, body: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".partial-", delete=False) as stream:
        temp_path = Path(stream.name)
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
    return hashlib.sha256(body).hexdigest()


def _append_event(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def collect(
    *,
    dataset: str,
    start: str,
    end: str,
    meets: list[int],
    page_size: int,
    max_new_requests: int,
    delay_seconds: float,
) -> None:
    settings = get_settings()
    key = settings.data_go_kr_service_key
    if key is None:
        raise RuntimeError("DATA_GO_KR_SERVICE_KEY is unavailable")
    endpoint, operation = DATASETS[dataset]
    root = settings.raw_data_dir / "kra_api_monthly" / dataset
    ledger = root / "manifest.jsonl"
    new_requests = 0
    with KraApiClient(key.get_secret_value()) as client:
        for month in months_between(start, end):
            for meet in meets:
                page_no = 1
                month_rows = 0
                month_pages = 0
                while True:
                    path = root / f"meet_{meet}" / month / f"page_{page_no:04d}.json"
                    if path.is_file():
                        body_bytes = path.read_bytes()
                        payload = _read_page(path)
                        status = "cached"
                        source_url = None
                    else:
                        if new_requests >= max_new_requests:
                            print(
                                json.dumps(
                                    {
                                        "status": "request_budget_reached",
                                        "new_requests": new_requests,
                                        "next_month": month,
                                        "next_meet": meet,
                                        "next_page": page_no,
                                    }
                                ),
                                flush=True,
                            )
                            return
                        fetched = client._fetch_json(
                            endpoint,
                            operation,
                            {
                                "meet": meet,
                                "tr_month": month,
                                "_type": "json",
                                "pageNo": page_no,
                                "numOfRows": page_size,
                            },
                            service_key_parameter="ServiceKey",
                        )
                        payload = fetched.payload
                        body_bytes = fetched.body
                        _atomic_write(path, body_bytes)
                        new_requests += 1
                        status = "downloaded"
                        source_url = fetched.source_url
                        if delay_seconds:
                            time.sleep(delay_seconds)

                    body = response_body(payload)
                    total_count = int(body.get("totalCount") or 0)
                    actual_page_size = int(body.get("numOfRows") or page_size)
                    items = _items(payload)
                    bad_dates = sum(
                        not str(item.get("trDate", "")).startswith(month) for item in items
                    )
                    missing_ids = sum(not str(item.get("hrNo", "")).strip() for item in items)
                    if bad_dates or missing_ids:
                        raise ValueError(
                            f"{month} meet={meet} page={page_no}: "
                            f"bad_dates={bad_dates}, missing_ids={missing_ids}"
                        )
                    month_rows += len(items)
                    month_pages += 1
                    _append_event(
                        ledger,
                        {
                            "status": status,
                            "month": month,
                            "meet": meet,
                            "page": page_no,
                            "total_count": total_count,
                            "item_count": len(items),
                            "path": str(path),
                            "sha256": hashlib.sha256(body_bytes).hexdigest(),
                            "source_url": source_url,
                            "recorded_at_ms": time.time_ns() // 1_000_000,
                        },
                    )
                    total_pages = max(1, math.ceil(total_count / max(actual_page_size, 1)))
                    if page_no >= total_pages:
                        if month_rows != total_count:
                            raise ValueError(
                                f"{month} meet={meet}: "
                                f"item_count={month_rows}, total_count={total_count}"
                            )
                        print(
                            json.dumps(
                                {
                                    "status": "complete",
                                    "month": month,
                                    "meet": meet,
                                    "rows": month_rows,
                                    "pages": month_pages,
                                    "new_requests": new_requests,
                                }
                            ),
                            flush=True,
                        )
                        break
                    page_no += 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=sorted(DATASETS), default="horse_training")
    parser.add_argument("--start", required=True, help="YYYYMM")
    parser.add_argument("--end", required=True, help="YYYYMM")
    parser.add_argument("--meets", nargs="+", type=int, default=[1, 2, 3], choices=[1, 2, 3])
    parser.add_argument("--page-size", type=int, default=20000)
    parser.add_argument("--max-new-requests", type=int, default=2500)
    parser.add_argument("--delay-ms", type=int, default=200)
    args = parser.parse_args()
    collect(
        dataset=args.dataset,
        start=args.start,
        end=args.end,
        meets=args.meets,
        page_size=args.page_size,
        max_new_requests=args.max_new_requests,
        delay_seconds=args.delay_ms / 1000,
    )


if __name__ == "__main__":
    main()
