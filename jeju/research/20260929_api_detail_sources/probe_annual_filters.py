"""Positive-control probes for annual filtering on API6_1 and API303."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

from horse_racing.collectors.kra_api import (
    RACE_DETAIL_SECTION_RECORD_ENDPOINT,
    RACE_DETAIL_SECTION_RECORD_OPERATION,
    RACE_PASSING_SUMMARY_ENDPOINT,
    RACE_PASSING_SUMMARY_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parent
PROBES = [
    ("detail_section", RACE_DETAIL_SECTION_RECORD_ENDPOINT, RACE_DETAIL_SECTION_RECORD_OPERATION, "serviceKey"),
    ("passing_corner", RACE_PASSING_SUMMARY_ENDPOINT, RACE_PASSING_SUMMARY_OPERATION, "serviceKey"),
]


def extract_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    values = (response_body(payload).get("items") or {}).get("item")
    if isinstance(values, dict):
        return [values]
    if isinstance(values, list):
        return [value for value in values if isinstance(value, dict)]
    return []


def main() -> int:
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None or not secret.get_secret_value().strip():
        print(json.dumps({"status": "credential_unavailable"}))
        return 2
    key = secret.get_secret_value()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    output_dir = ROOT / "raw/scope_probes" / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    results: list[dict[str, Any]] = []
    with KraApiClient(key, base_url=settings.kra_api_base_url, timeout_seconds=20.0) as client:
        for label, endpoint, operation, key_parameter in PROBES:
            for year in (2016, 2026):
                params = {"meet": 2, "rc_year": str(year), "_type": "json"}
                summary: dict[str, Any] = {
                    "dataset": label,
                    "endpoint": endpoint,
                    "operation": operation,
                    "public_params": params,
                    "page_no": 1,
                    "num_of_rows": 1000,
                }
                try:
                    page = client._fetch_json(
                        endpoint,
                        operation,
                        {**params, "pageNo": 1, "numOfRows": 1000},
                        service_key_parameter=key_parameter,
                    )
                    encoded = (
                        key.encode(),
                        quote(key, safe="").encode(),
                        quote_plus(key, safe="").encode(),
                    )
                    if any(value and value in page.body for value in encoded):
                        raise ValueError("credential echo rejected")
                    rows = extract_rows(page.payload)
                    body = response_body(page.payload)
                    dates = sorted({str(row.get("rcDate") or "") for row in rows})
                    matches = sum(str(row.get("rcDate") or "").startswith(str(year)) for row in rows)
                    file_path = output_dir / label / str(year) / "page_0001.json"
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_bytes(page.body)
                    summary.update({
                        "response_status": page.status_code,
                        "content_type": page.content_type,
                        "source_url_without_key": page.source_url,
                        "response_file": str(file_path.relative_to(output_dir)),
                        "response_bytes": len(page.body),
                        "response_sha256": hashlib.sha256(page.body).hexdigest(),
                        "api_total_count": int(body.get("totalCount") or 0),
                        "api_page_size": int(body.get("numOfRows") or 1000),
                        "actual_page_rows": len(rows),
                        "page_date_examples": dates[:5],
                        "records_in_requested_year": matches,
                        "period_validation": (
                            "all_returned_rows_match_year" if rows and matches == len(dates)
                            else "no_positive_scope_evidence" if not rows
                            else "year_filter_mismatch"
                        ),
                    })
                except Exception as exc:
                    summary.update({"response_status": "request_failed", "exception_type": type(exc).__name__})
                results.append(summary)
    manifest = {
        "run_id": run_id,
        "source": "KRA official API",
        "scope": "Filter probes only; no annual full backfill",
        "credential_recorded": False,
        "requests": results,
    }
    manifest_path = output_dir / "scope_probe_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    matched = sum(item.get("period_validation") == "all_returned_rows_match_year" for item in results)
    print(json.dumps({"run_id": run_id, "scope_matched": matched, "manifest": str(manifest_path)}, ensure_ascii=False))
    return 0 if matched == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
