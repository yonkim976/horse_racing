"""Finish only the 2016/2026 representative KRA partitions with >1k rows."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

from horse_racing.collectors.kra_api import KraApiClient, response_body
from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parent
SAMPLE_RUN = ROOT / "raw/samples/20260929T142137.341471Z"
SAMPLE_MANIFEST = SAMPLE_RUN / "sample_manifest.json"
PAGE_SIZE = 1000
TARGETS = {
    "clinic_2026": {"date_field": "clinicDate", "date_prefix": "2026"},
    "daily_training_202609": {"date_field": "trDate", "date_prefix": "202609"},
    "daily_training_201609": {"date_field": "trDate", "date_prefix": "201609"},
    "starting_training_2026": {"date_field": "trDate", "date_prefix": "2026"},
    "starting_training_2016": {"date_field": "trDate", "date_prefix": "2016"},
}


def rows_in(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = response_body(payload).get("items") or {}
    values = items.get("item") if isinstance(items, dict) else None
    if values is None:
        return []
    if isinstance(values, dict):
        return [values]
    if isinstance(values, list):
        return [value for value in values if isinstance(value, dict)]
    return []


def atomic_immutable_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def contains_key(body: bytes, key: str) -> bool:
    needles = (
        key.encode("utf-8"),
        quote(key, safe="").encode("utf-8"),
        quote_plus(key, safe="").encode("utf-8"),
    )
    return any(needle and needle in body for needle in needles)


def main() -> int:
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None or not secret.get_secret_value().strip():
        print(json.dumps({"status": "credential_unavailable"}))
        return 2
    service_key = secret.get_secret_value()
    source_manifest = json.loads(SAMPLE_MANIFEST.read_text(encoding="utf-8"))
    source_requests = {row["request_id"]: row for row in source_manifest["requests"]}
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    results: list[dict[str, Any]] = []
    result_path = SAMPLE_RUN / "representative_partition_completion.json"

    with KraApiClient(
        service_key,
        base_url=settings.kra_api_base_url,
        timeout_seconds=min(settings.http_timeout_seconds, 20.0),
    ) as client:
        for request_id, spec in TARGETS.items():
            source = source_requests[request_id]
            summary: dict[str, Any] = {
                "request_id": request_id,
                "endpoint": source["endpoint"],
                "operation": source["operation"],
                "public_params": source["public_params"],
                "page_size_requested": PAGE_SIZE,
                "status": "running",
                "pages": [],
            }
            try:
                expected_total = int(source["api_total_count"])
                expected_pages = max(1, math.ceil(expected_total / PAGE_SIZE))
                first_path = SAMPLE_RUN / source["response_file"]
                first_body = first_path.read_bytes()
                first_sha = hashlib.sha256(first_body).hexdigest()
                if first_sha != source["response_sha256"]:
                    raise ValueError("page 1 hash mismatch")
                if contains_key(first_body, service_key):
                    raise ValueError("page 1 contains credential")
                first_payload = json.loads(first_body)
                pages_to_fetch = range(2, expected_pages + 1)
                all_pages: list[tuple[int, bytes, list[dict[str, Any]], dict[str, Any]]] = [
                    (1, first_body, rows_in(first_payload), {
                        "status_code": source["status_code"],
                        "content_type": source["content_type"],
                        "requested_at_ms": source["requested_at_ms"],
                        "retrieved_at_ms": source["retrieved_at_ms"],
                        "source_url_without_key": source["source_url_without_key"],
                    })
                ]
                for page_no in pages_to_fetch:
                    fetched = client._fetch_json(
                        source["endpoint"],
                        source["operation"],
                        {
                            **source["public_params"],
                            "pageNo": page_no,
                            "numOfRows": PAGE_SIZE,
                        },
                        service_key_parameter=source["key_parameter_name"],
                    )
                    if contains_key(fetched.body, service_key):
                        raise ValueError(f"page {page_no} contains credential")
                    all_pages.append((page_no, fetched.body, rows_in(fetched.payload), {
                        "status_code": fetched.status_code,
                        "content_type": fetched.content_type,
                        "requested_at_ms": fetched.requested_at_ms,
                        "retrieved_at_ms": fetched.retrieved_at_ms,
                        "source_url_without_key": fetched.source_url,
                        "api_total_count": int(response_body(fetched.payload).get("totalCount") or 0),
                        "api_page_size": int(response_body(fetched.payload).get("numOfRows") or PAGE_SIZE),
                        "api_page_no": int(response_body(fetched.payload).get("pageNo") or page_no),
                    }))
                    time.sleep(0.35)

                total_actual_rows = 0
                scope_match_rows = 0
                page_metadata: list[dict[str, Any]] = []
                for page_no, body, page_rows, http_meta in all_pages:
                    digest = hashlib.sha256(body).hexdigest()
                    row_matches = sum(
                        str(row.get(spec["date_field"]) or "").startswith(spec["date_prefix"])
                        for row in page_rows
                    )
                    total_actual_rows += len(page_rows)
                    scope_match_rows += row_matches
                    if page_no > 1:
                        target = SAMPLE_RUN / "source_pages" / request_id / f"page_{page_no:04d}.json"
                        atomic_immutable_write(target, body)
                        page_file = str(target.relative_to(SAMPLE_RUN))
                    else:
                        page_file = source["response_file"]
                    page_metadata.append({
                        "page_no": page_no,
                        **http_meta,
                        "response_bytes": len(body),
                        "response_sha256": digest,
                        "response_file": page_file,
                        "actual_page_rows": len(page_rows),
                        "records_matching_requested_period": row_matches,
                        "sample_date_examples": sorted({
                            str(row.get(spec["date_field"]) or "")
                            for row in page_rows if row.get(spec["date_field"]) is not None
                        })[:5],
                    })
                summary["pages"] = page_metadata
                summary["api_total_count"] = expected_total
                summary["actual_page_count"] = len(all_pages)
                summary["expected_page_count"] = expected_pages
                summary["actual_total_rows"] = total_actual_rows
                summary["rows_matching_requested_period"] = scope_match_rows
                summary["row_date_field"] = spec["date_field"]
                summary["requested_period_prefix"] = spec["date_prefix"]
                complete = (
                    len(all_pages) == expected_pages
                    and total_actual_rows == expected_total
                    and scope_match_rows == total_actual_rows
                    and all(
                        int((json.loads(body).get("response") or json.loads(body)).get("body", {}).get("totalCount") or 0)
                        == expected_total
                        for _page_no, body, _rows, _meta in all_pages[:1]
                    )
                    and all(page["records_matching_requested_period"] == page["actual_page_rows"] for page in page_metadata)
                )
                # The original first-page manifest supplies page-1 totalCount;
                # every fetched follow-up page is checked separately here.
                for page in page_metadata[1:]:
                    if page.get("api_total_count") != expected_total or page.get("api_page_size") != PAGE_SIZE:
                        complete = False
                summary["status"] = "complete_representative_partition" if complete else "incomplete_or_scope_mismatch"
            except Exception as exc:
                summary["status"] = "failed"
                summary["exception_type"] = type(exc).__name__
            results.append(summary)
            result_path.write_text(
                json.dumps({
                    "run_id": run_id,
                    "source": "KRA official API response pages",
                    "credential_recorded": False,
                    "scope": "Only representative 2016/2026 partitions requested; not a full 2002-2026 backfill",
                    "partitions": results,
                }, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    print(json.dumps({
        "run_id": run_id,
        "complete_partitions": sum(p["status"] == "complete_representative_partition" for p in results),
        "failed_partitions": sum(p["status"] == "failed" for p in results),
        "manifest": str(result_path),
    }, ensure_ascii=False))
    return 0 if results and all(p["status"] == "complete_representative_partition" for p in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
