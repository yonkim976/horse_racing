"""Archive official KRA running-trial API responses by year, meet=3.

The source endpoint is documented by the public data portal dataset 15056974.
Never serialize the service key or an authenticated request URL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from horse_racing.collectors.kra_api import KraApiClient, response_body
from horse_racing.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/busan_trial_linkage_20260915/api_raw"
ENDPOINT = "/API20_1/ridingTestResult_1"
OPERATION = "ridingTestResult_1"


def items(payload: dict) -> list[dict]:
    item = (response_body(payload).get("items") or {}).get("item") or []
    return [item] if isinstance(item, dict) else item


def atomic_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def collect(start_year: int, end_year: int, *, page_size: int = 20000) -> None:
    key = get_settings().data_go_kr_service_key
    if key is None:
        raise RuntimeError("KRA API service key is unavailable")
    OUT.mkdir(parents=True, exist_ok=True)
    ledger = OUT / "request_ledger.jsonl"
    with KraApiClient(key.get_secret_value(), timeout_seconds=90) as client:
        for year in range(start_year, end_year + 1):
            page = 1
            seen = 0
            while True:
                path = OUT / str(year) / f"page_{page:04d}.json"
                params = {"meet": 3, "tr_year": str(year), "pageNo": page,
                          "numOfRows": page_size, "_type": "json"}
                if path.exists():
                    body = path.read_bytes()
                    payload = json.loads(body)
                    url = None
                    fetched_ms = None
                    status = "reused"
                else:
                    try:
                        fetched = client._fetch_json(
                            ENDPOINT, OPERATION, params,
                            service_key_parameter="ServiceKey")
                    except Exception as exc:
                        # httpx's chained exception may contain the authenticated
                        # URL. Never emit that traceback or persist the key.
                        response = getattr(exc.__cause__, "response", None)
                        http_status = getattr(response, "status_code", None)
                        error_path = None
                        error_sha = None
                        if response is not None and key.get_secret_value().encode() not in response.content:
                            error_path = OUT / "errors" / f"{year}_page_{page:04d}_http_{http_status}.body"
                            atomic_write(error_path, response.content)
                            error_sha = hashlib.sha256(response.content).hexdigest()
                        try:
                            error_payload = response.json() if response else {}
                            error_code = ((error_payload.get("response") or {}).get("header", {}).get("resultCode")
                                          or (error_payload.get("OpenAPI_ServiceResponse") or {}).get("cmmMsgHeader", {}).get("returnReasonCode"))
                        except (ValueError, AttributeError, TypeError):
                            error_code = None
                        with ledger.open("a", encoding="utf-8") as stream:
                            stream.write(json.dumps({
                                "status": "request_failed", "source": "KRA ridingTestResult_1",
                                "scope": {"meet": 3, "tr_year": year}, "page": page,
                                "endpoint": ENDPOINT, "http_status": http_status,
                                "result_code": error_code,
                                "response_path": str(error_path) if error_path else None,
                                "response_sha256": error_sha,
                                "collected_at_utc": datetime.now(timezone.utc).isoformat(),
                            }, ensure_ascii=False, sort_keys=True) + "\n")
                        raise SystemExit(f"Trial API request failed for year={year} page={page} HTTP={http_status} code={error_code}; see request ledger") from None
                    body = fetched.body
                    payload = fetched.payload
                    url = fetched.source_url
                    fetched_ms = fetched.retrieved_at_ms
                    status = "downloaded"
                    atomic_write(path, body)
                batch = items(payload)
                body_meta = response_body(payload)
                total = int(body_meta.get("totalCount") or 0)
                actual_page_size = int(body_meta.get("numOfRows") or page_size)
                if not isinstance(batch, list) or not all(isinstance(row, dict) for row in batch):
                    raise ValueError(f"Invalid trial API page shape: {year}:{page}")
                bad_years = [row.get("trainDate") for row in batch
                             if str(row.get("trainDate") or "")[:4] != str(year)]
                if bad_years:
                    raise ValueError(f"Out-of-year API rows: {year}:{page}:{bad_years[:3]}")
                event = {
                    "status": status, "source": "KRA ridingTestResult_1",
                    "source_catalog": "https://www.data.go.kr/data/15056974/openapi.do",
                    "scope": {"meet": 3, "tr_year": year}, "page": page,
                    "requested_page_size": page_size, "actual_page_size": actual_page_size,
                    "total_count": total, "response_rows": len(batch),
                    "collected_at_utc": datetime.now(timezone.utc).isoformat(),
                    "source_retrieved_at_ms": fetched_ms,
                    "source_url_without_key": url,
                    "path": str(path), "sha256": hashlib.sha256(body).hexdigest(),
                    "zero_count_requires_review": total == 0,
                }
                with ledger.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
                seen += len(batch)
                if page >= max(1, math.ceil(total / max(actual_page_size, 1))):
                    if seen != total:
                        raise ValueError(f"Incomplete trial API pages: {year}: {seen}/{total}")
                    print(year, "pages", page, "rows", seen)
                    break
                page += 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    args = parser.parse_args()
    collect(args.start_year, args.end_year)
