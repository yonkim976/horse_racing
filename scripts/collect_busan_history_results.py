"""Archive annual official Busan race results, independently of the operating DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from horse_racing.collectors.kra_api import (
    RACE_RESULT_WITH_SECTIONS_ENDPOINT,
    RACE_RESULT_WITH_SECTIONS_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings


def items(payload: dict) -> list[dict]:
    wrapped = response_body(payload).get("items") or {}
    value = wrapped.get("item") if isinstance(wrapped, dict) else None
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return value
    raise ValueError("Unexpected API item structure")


def atomic_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def collect(start: int, end: int, root: Path) -> None:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        raise RuntimeError("KRA service key unavailable")
    ledger = root / "request_ledger.jsonl"
    with KraApiClient(
        settings.data_go_kr_service_key.get_secret_value(),
        base_url=settings.kra_api_base_url,
        timeout_seconds=90,
    ) as client:
        for year in range(start, end + 1):
            total_rows = 0
            page_no = 1
            while True:
                path = root / "raw" / str(year) / f"page_{page_no:04d}.json"
                if path.exists():
                    body = path.read_bytes()
                    payload = json.loads(body)
                    url = None
                    fetched_at = None
                    status = "reused"
                else:
                    fetched = client._fetch_json(
                        RACE_RESULT_WITH_SECTIONS_ENDPOINT,
                        RACE_RESULT_WITH_SECTIONS_OPERATION,
                        {"meet": 3, "rc_year": str(year), "_type": "json",
                         "pageNo": page_no, "numOfRows": 20000},
                        service_key_parameter="ServiceKey",
                    )
                    body, payload = fetched.body, fetched.payload
                    url, fetched_at = fetched.source_url, fetched.retrieved_at_ms
                    status = "downloaded"
                    atomic_write(path, body)
                batch = items(payload)
                api_body = response_body(payload)
                count = int(api_body.get("totalCount") or 0)
                actual_size = int(api_body.get("numOfRows") or 20000)
                if count == 0 and year >= 2005:
                    raise ValueError(f"Unexpected zero annual result: {year}")
                if any(row.get("meet") != "부산경남" or int(row["rcDate"]) // 10000 != year
                       for row in batch):
                    raise ValueError(f"Out-of-scope result row: {year} page {page_no}")
                total_rows += len(batch)
                event = {
                    "status": status, "source": "KRA API4_3/raceResult_3",
                    "scope": {"meet": 3, "rc_year": year}, "page": page_no,
                    "requested_page_size": 20000, "actual_page_size": actual_size,
                    "total_count": count, "response_rows": len(batch),
                    "collected_at_utc": datetime.now(timezone.utc).isoformat(),
                    "source_retrieved_at_ms": fetched_at, "source_url_without_key": url,
                    "path": str(path), "sha256": hashlib.sha256(body).hexdigest(),
                }
                ledger.parent.mkdir(parents=True, exist_ok=True)
                with ledger.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
                if page_no >= max(1, math.ceil(count / max(actual_size, 1))):
                    if total_rows != count:
                        raise ValueError(f"Incomplete year {year}: {total_rows} != {count}")
                    print(json.dumps({"year": year, "rows": count, "pages": page_no}), flush=True)
                    break
                page_no += 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2005)
    parser.add_argument("--end-year", type=int, default=datetime.now().year)
    parser.add_argument("--output", type=Path,
                        default=Path("data/research/busan_history_20260915"))
    args = parser.parse_args()
    collect(args.start_year, args.end_year, args.output)
