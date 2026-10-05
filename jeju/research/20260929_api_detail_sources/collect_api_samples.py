"""Safely archive small recent and historical KRA API response samples.

Service credentials are loaded in memory from the project settings and never
written to output. Each request captures only its first page so totalCount can
be used to plan a later complete history backfill.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

from horse_racing.collectors.kra_api import (
    DAILY_TRAINING_ENDPOINT,
    DAILY_TRAINING_OPERATION,
    ENTRY_HORSE_WEIGHT_ENDPOINT,
    ENTRY_HORSE_WEIGHT_OPERATION,
    JUDGE_REPORT_ENDPOINT,
    JUDGE_REPORT_OPERATION,
    HORSE_EQUIPMENT_ENDPOINT,
    HORSE_EQUIPMENT_OPERATION,
    RACE_DETAIL_SECTION_RECORD_ENDPOINT,
    RACE_DETAIL_SECTION_RECORD_OPERATION,
    RACE_HORSE_CLINIC_ENDPOINT,
    RACE_HORSE_CLINIC_OPERATION,
    RACE_PASSING_SUMMARY_ENDPOINT,
    RACE_PASSING_SUMMARY_OPERATION,
    RACE_RESULT_WITH_SECTIONS_ENDPOINT,
    RACE_RESULT_WITH_SECTIONS_OPERATION,
    START_TRAINING_ENDPOINT,
    START_TRAINING_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parent
PAGE_SIZE = 1000

# Query shape follows the endpoint's public parameter convention. Historic
# requests are a representative mid-history sample, not an asserted start date.
SAMPLES: list[dict[str, Any]] = [
    {"name": "race_result", "endpoint": RACE_RESULT_WITH_SECTIONS_ENDPOINT, "operation": RACE_RESULT_WITH_SECTIONS_OPERATION, "key_parameter": "ServiceKey", "date_key": "rc_date", "date_values": ["20260919", "20160108"]},
    {"name": "detail_section", "endpoint": RACE_DETAIL_SECTION_RECORD_ENDPOINT, "operation": RACE_DETAIL_SECTION_RECORD_OPERATION, "key_parameter": "serviceKey", "date_key": "rc_date", "date_values": ["20260919", "20160108"]},
    {"name": "passing_corner", "endpoint": RACE_PASSING_SUMMARY_ENDPOINT, "operation": RACE_PASSING_SUMMARY_OPERATION, "key_parameter": "serviceKey", "date_key": "rc_date", "date_values": ["20260919", "20160108"]},
    {"name": "judge_report", "endpoint": JUDGE_REPORT_ENDPOINT, "operation": JUDGE_REPORT_OPERATION, "key_parameter": "serviceKey", "date_key": "rc_year", "date_values": ["2026", "2020"]},
    {"name": "clinic", "endpoint": RACE_HORSE_CLINIC_ENDPOINT, "operation": RACE_HORSE_CLINIC_OPERATION, "key_parameter": "serviceKey", "date_key": "clinic_year", "date_values": ["2026", "2016"]},
    {"name": "daily_training", "endpoint": DAILY_TRAINING_ENDPOINT, "operation": DAILY_TRAINING_OPERATION, "key_parameter": "serviceKey", "date_key": "tr_month", "date_values": ["202609", "201609"]},
    {"name": "starting_training", "endpoint": START_TRAINING_ENDPOINT, "operation": START_TRAINING_OPERATION, "key_parameter": "serviceKey", "date_key": "tr_year", "date_values": ["2026", "2016"]},
    {"name": "weight", "endpoint": ENTRY_HORSE_WEIGHT_ENDPOINT, "operation": ENTRY_HORSE_WEIGHT_OPERATION, "key_parameter": "serviceKey", "date_key": "rc_month", "date_values": ["202609", "201609"]},
    {"name": "equipment", "endpoint": HORSE_EQUIPMENT_ENDPOINT, "operation": HORSE_EQUIPMENT_OPERATION, "key_parameter": "serviceKey", "date_key": "rc_date", "date_values": ["20260919", "20160108"]},
]


def response_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = response_body(payload)
    items = body.get("items") or {}
    rows = items.get("item") if isinstance(items, dict) else None
    if rows is None:
        return []
    if isinstance(rows, dict):
        return [rows]
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def matching_record_dates(name: str, rows: list[dict[str, Any]], date_value: str) -> tuple[int, list[str]]:
    date_fields = {
        "race_result": "rcDate",
        "detail_section": "rcDate",
        "passing_corner": "rcDate",
        "judge_report": "rcDate",
        "clinic": "clinicDate",
        "daily_training": "trDate",
        "starting_training": "trDate",
        "weight": "rcDate",
        "equipment": "rcDate",
    }
    field = date_fields[name]
    values = sorted({str(row.get(field) or "") for row in rows if row.get(field) is not None})
    # Month/year filters are prefix checks; exact date filters require exact equality.
    matches = sum(str(row.get(field) or "").startswith(date_value) for row in rows)
    return matches, values[:5]


def error_kind(exc: BaseException, service_key: str) -> dict[str, str]:
    # Deliberately avoid exception messages: HTTP clients may include request
    # URLs, which can contain the authentication parameter.
    return {"type": type(exc).__name__}


def safe_bytes(body: bytes, service_key: str) -> bool:
    candidates = {
        service_key.encode("utf-8"),
        quote(service_key, safe="").encode("utf-8"),
        quote_plus(service_key, safe="").encode("utf-8"),
    }
    return not any(candidate and candidate in body for candidate in candidates)


def main() -> int:
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None or not secret.get_secret_value().strip():
        print(json.dumps({"status": "credential_unavailable"}))
        return 2
    service_key = secret.get_secret_value()
    started = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = ROOT / "raw" / "samples" / started
    manifest: dict[str, Any] = {
        "run_id": started,
        "source": "KRA OpenAPI; first page samples only",
        "credential_recorded": False,
        "meet": 2,
        "page_size": PAGE_SIZE,
        "requests": [],
    }
    run_dir.mkdir(parents=True, exist_ok=False)

    with KraApiClient(
        service_key,
        base_url=settings.kra_api_base_url,
        timeout_seconds=min(settings.http_timeout_seconds, 20.0),
    ) as client:
        for source in SAMPLES:
            for date_value in source["date_values"]:
                request_id = f"{source['name']}_{date_value}"
                params = {"meet": 2, source["date_key"]: date_value, "_type": "json"}
                started_ms = int(time.time() * 1000)
                item: dict[str, Any] = {
                    "request_id": request_id,
                    "source": "data.go.kr/B551015",
                    "endpoint": source["endpoint"],
                    "operation": source["operation"],
                    "public_params": params,
                    "page_no": 1,
                    "num_of_rows": PAGE_SIZE,
                    "key_parameter_name": source["key_parameter"],
                    "response_status": "pending",
                    "period_validation": "pending",
                }
                try:
                    fetched = client._fetch_json(
                        source["endpoint"],
                        source["operation"],
                        {**params, "pageNo": 1, "numOfRows": PAGE_SIZE},
                        service_key_parameter=source["key_parameter"],
                    )
                    body = fetched.body
                    if not safe_bytes(body, service_key):
                        item.update({"response_status": "credential_echo_rejected", "response_archived": False})
                    else:
                        payload_body = response_body(fetched.payload)
                        rows = response_rows(fetched.payload)
                        matching_rows, response_date_examples = matching_record_dates(
                            source["name"], rows, date_value
                        )
                        path = Path("source_pages") / request_id / "page_0001.json"
                        target = run_dir / path
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(body)
                        item.update(
                            {
                                "response_status": "http_success",
                                "status_code": fetched.status_code,
                                "content_type": fetched.content_type,
                                "requested_at_ms": fetched.requested_at_ms,
                                "retrieved_at_ms": fetched.retrieved_at_ms,
                                "response_bytes": len(body),
                                "response_sha256": hashlib.sha256(body).hexdigest(),
                                "response_file": str(path),
                                "source_url_without_key": fetched.source_url,
                                "api_result_code": str((fetched.payload.get("response") or fetched.payload).get("header", {}).get("resultCode", "")),
                                "api_total_count": int(payload_body.get("totalCount") or 0),
                                "api_page_size": int(payload_body.get("numOfRows") or PAGE_SIZE),
                                "actual_page_rows": len(rows),
                                "response_complete": len(rows) == int(payload_body.get("totalCount") or 0),
                                "row_date_field": {
                                    "race_result": "rcDate",
                                    "detail_section": "rcDate",
                                    "passing_corner": "rcDate",
                                    "judge_report": "rcDate",
                                    "clinic": "clinicDate",
                                    "daily_training": "trDate",
                                    "starting_training": "trDate",
                                    "weight": "rcDate",
                                    "equipment": "rcDate",
                                }[source["name"]],
                                "records_matching_requested_date_prefix": matching_rows,
                                "response_date_examples": response_date_examples,
                                "sample_fields": sorted(rows[0].keys()) if rows else [],
                            }
                        )
                        if not rows:
                            item["period_validation"] = "no_rows_no_positive_coverage_evidence"
                        elif matching_rows == len(rows):
                            item["period_validation"] = "all_page_rows_match_requested_period"
                        elif matching_rows == 0:
                            item["period_validation"] = "no_page_rows_match_requested_period"
                        else:
                            item["period_validation"] = "partial_page_period_mismatch"
                        item["coverage_complete"] = bool(item["response_complete"] and rows and matching_rows == len(rows))
                except Exception as exc:
                    item["response_status"] = "request_failed"
                    item["exception"] = error_kind(exc, service_key)
                finally:
                    item["finished_at_ms"] = int(time.time() * 1000)
                    item["elapsed_ms"] = item["finished_at_ms"] - started_ms
                    manifest["requests"].append(item)
                # Stay under portal per-second quotas when a batch is rerun.
                time.sleep(0.35)

    manifest["successful_responses"] = sum(row["response_status"] == "http_success" for row in manifest["requests"])
    manifest["failed_requests"] = sum(row["response_status"] == "request_failed" for row in manifest["requests"])
    manifest["scope_matched_samples"] = sum(
        row.get("period_validation") == "all_page_rows_match_requested_period" for row in manifest["requests"]
    )
    manifest["complete_partitions"] = sum(bool(row.get("coverage_complete")) for row in manifest["requests"])
    manifest_path = run_dir / "sample_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"run_id": started, "successful_responses": manifest["successful_responses"], "scope_matched": manifest["scope_matched_samples"], "complete_partitions": manifest["complete_partitions"], "failed": manifest["failed_requests"], "manifest": str(manifest_path)}, ensure_ascii=False))
    return 0 if manifest["successful_responses"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
