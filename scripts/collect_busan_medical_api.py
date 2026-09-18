"""Archive Busan annual medical API pages with verified year and page counts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from collect_busan_history_results import atomic_write, items
from horse_racing.collectors.kra_api import (
    RACE_HORSE_CLINIC_ENDPOINT,
    RACE_HORSE_CLINIC_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings


def collect(root: Path, start: int, end: int) -> None:
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        raise RuntimeError("KRA service key unavailable")
    ledger = root / "medical_request_ledger.jsonl"
    with KraApiClient(settings.data_go_kr_service_key.get_secret_value(),
                      base_url=settings.kra_api_base_url, timeout_seconds=90) as client:
        for year in range(start, end + 1):
            page_no = 1
            total_rows = 0
            while True:
                path = root / "raw_medical" / str(year) / f"page_{page_no:04d}.json"
                if path.exists():
                    body = path.read_bytes()
                    payload = json.loads(body)
                    url, retrieved = None, None
                    status = "reused"
                else:
                    fetched = client._fetch_json(
                        RACE_HORSE_CLINIC_ENDPOINT, RACE_HORSE_CLINIC_OPERATION,
                        {"meet": 3, "clinic_year": str(year), "_type": "json",
                         "pageNo": page_no, "numOfRows": 20000},
                        service_key_parameter="ServiceKey")
                    body, payload = fetched.body, fetched.payload
                    url, retrieved = fetched.source_url, fetched.retrieved_at_ms
                    status = "downloaded"
                    atomic_write(path, body)
                api_body = response_body(payload)
                rows = items(payload)
                total = int(api_body.get("totalCount") or 0)
                page_size = int(api_body.get("numOfRows") or 20000)
                if any(row.get("meet") not in {"부산경남", "영남"} or
                       str(row.get("clinicDate") or "")[:4] != str(year) for row in rows):
                    raise ValueError(f"Medical API ignored scope {year}:{page_no}")
                total_rows += len(rows)
                event = {"status": status, "source": "KRA API16_1/raceHorseClinic_1",
                         "scope": {"meet": 3, "clinic_year": year}, "page": page_no,
                         "requested_page_size": 20000, "total_count": total,
                         "response_rows": len(rows),
                         "collected_at_utc": datetime.now(UTC).isoformat(),
                         "source_retrieved_at_ms": retrieved, "source_url_without_key": url,
                         "path": str(path), "sha256": hashlib.sha256(body).hexdigest()}
                with ledger.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
                if page_no >= max(1, math.ceil(total / max(page_size, 1))):
                    if total_rows != total:
                        raise ValueError(f"Incomplete year {year}: {total_rows}!={total}")
                    print(json.dumps({"year": year, "rows": total, "pages": page_no}),
                          flush=True)
                    break
                page_no += 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2019)
    parser.add_argument("--end-year", type=int, default=datetime.now().year)
    parser.add_argument("--output", type=Path,
                        default=Path("data/research/busan_history_20260915"))
    args = parser.parse_args()
    collect(args.output, args.start_year, args.end_year)
