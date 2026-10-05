"""Small, read-only availability probe for three official KRA APIs.

Only API response bodies and key-free metadata are written. Never prints the
service key, exception text, or a request URL containing query parameters.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, quote_plus

import httpx

from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parent
RAW_ROOT = ROOT / "raw"
YEARS = (2010, 2017, 2025, 2026)
MEETS = (1, 3, 4)
PAGE_SIZE = 1000
MIN_INTERVAL_SECONDS = 0.45

DATASETS = {
    "judge_report": ("/API215/JudgeReport", "JudgeReport", "rcDate"),
    "sanction_history": ("/API180_1/sanctionHistory_1", "sanctionHistory_1", ""),
    "passing_groups": ("/API303/corner_rank", "corner_rank", "rcDate"),
}


def safe_body_shape(body: bytes, key: str) -> dict:
    """Summarize only response status/count/date/field metadata."""
    variants = {key.encode(), quote(key, safe="").encode(), quote_plus(key, safe="").encode()}
    if any(v and v in body for v in variants):
        raise RuntimeError("credential_echo_detected")
    payload = json.loads(body.decode("utf-8-sig"))
    root = payload.get("response", payload)
    header = root.get("header") or {}
    response_body = root.get("body") or {}
    items_node = response_body.get("items") or {}
    items = items_node.get("item") if isinstance(items_node, dict) else None
    if items is None:
        rows = []
    elif isinstance(items, dict):
        rows = [items]
    elif isinstance(items, list):
        rows = [r for r in items if isinstance(r, dict)]
    else:
        rows = []
    all_keys = sorted({key for row in rows for key in row})
    date_fields = ("rcDate", "rc_date", "sancDate", "sanctionDate", "sancStartDate", "startDate")
    date_stats = {}
    for field in date_fields:
        values = [str(row.get(field, "")).strip() for row in rows if row.get(field) not in (None, "")]
        if values:
            date_stats[field] = {"min": min(values), "max": max(values), "n": len(values)}
    meet_counts = {}
    for row in rows:
        for field in ("meet", "meetNm", "meetName", "meet_name"):
            if row.get(field) not in (None, ""):
                value = str(row[field])
                meet_counts[value] = meet_counts.get(value, 0) + 1
                break
    return {
        "api_result_code": str(header.get("resultCode", "")),
        "api_result_message": str(header.get("resultMsg", ""))[:120],
        "total_count": int(response_body.get("totalCount") or 0),
        "reported_page_no": response_body.get("pageNo"),
        "reported_page_size": response_body.get("numOfRows"),
        "first_page_rows": len(rows),
        "first_page_fields": all_keys,
        "sample_dates": date_stats,
        "meet_value_counts_first_page": meet_counts,
        "sample_rows": rows[:3],
    }


def main() -> int:
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None or not secret.get_secret_value().strip():
        print(json.dumps({"status": "credential_unavailable"}))
        return 2
    key = secret.get_secret_value()
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    manifest = {
        "run_id": run_id,
        "source": "KRA official OpenAPI; read-only small availability probe",
        "credential_recorded": False,
        "requested_years": list(YEARS),
        "requested_meets": list(MEETS),
        "page_size": PAGE_SIZE,
        "min_interval_seconds": MIN_INTERVAL_SECONDS,
        "records": [],
    }
    previous = 0.0
    with httpx.Client(base_url=settings.kra_api_base_url.rstrip("/"), timeout=25.0) as client:
        for dataset, (endpoint, operation, date_field) in DATASETS.items():
            for meet in MEETS:
                for year in YEARS:
                    if previous:
                        elapsed = time.monotonic() - previous
                        if elapsed < MIN_INTERVAL_SECONDS:
                            time.sleep(MIN_INTERVAL_SECONDS - elapsed)
                    params = {
                        "serviceKey": key,
                        "meet": meet,
                        "rc_year": str(year),
                        "_type": "json",
                        "pageNo": 1,
                        "numOfRows": PAGE_SIZE,
                    }
                    request_time = datetime.now(UTC).isoformat()
                    record = {
                        "dataset": dataset,
                        "endpoint": endpoint,
                        "operation": operation,
                        "requested_meet": meet,
                        "requested_year": year,
                        "request_parameters_public": {k: v for k, v in params.items() if k != "serviceKey"},
                        "request_time_utc": request_time,
                    }
                    try:
                        response = client.get(endpoint, params=params)
                        previous = time.monotonic()
                        body = response.content
                        record["http_status"] = response.status_code
                        record["content_type"] = response.headers.get("content-type", "")
                        record["response_bytes"] = len(body)
                        record["response_sha256"] = hashlib.sha256(body).hexdigest()
                        if response.status_code == 200:
                            parsed = safe_body_shape(body, key)
                            record.update({k: v for k, v in parsed.items() if k != "sample_rows"})
                            # Small, raw excerpts are kept separately for direct row review.
                            record["sample_rows"] = parsed["sample_rows"]
                        else:
                            record["parse_status"] = "non_200_response"
                        raw_path = RAW_ROOT / dataset / str(year) / f"meet_{meet}.json"
                        raw_path.parent.mkdir(parents=True, exist_ok=True)
                        raw_path.write_bytes(body)
                        record["raw_response_path"] = raw_path.relative_to(ROOT).as_posix()
                    except Exception as exc:  # deliberately omit exception text/URL
                        record["failure_type"] = type(exc).__name__
                        record["failure_category"] = "credential_echo_detected" if str(exc) == "credential_echo_detected" else "request_or_parse_failure"
                    manifest["records"].append(record)
    out = ROOT / "api_availability_probe_manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    safe_summary = [
        {k: r.get(k) for k in ("dataset", "requested_meet", "requested_year", "http_status", "api_result_code", "total_count", "first_page_rows", "sample_dates", "failure_category") if k in r}
        for r in manifest["records"]
    ]
    print(json.dumps({"manifest": out.relative_to(ROOT).as_posix(), "calls": len(manifest["records"]), "summary": safe_summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
