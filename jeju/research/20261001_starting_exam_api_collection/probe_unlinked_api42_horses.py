"""Fetch current API42 profiles for IDs in the starting-exam website cross-check.

This read-only, bounded follow-up does not modify the Jeju database. It archives
each successful API response byte-for-byte and never writes the service key.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parent
OBSERVATIONS = ROOT / "website_validation" / "website_observations.json"
DATABASE = ROOT.parents[1] / "data" / "jeju_native_core.sqlite3"
ENDPOINT = "https://apis.data.go.kr/B551015/API42_1/totalHorseInfo_1"
SUCCESS_CODES = {"00", "0000"}


def read_items(payload: dict) -> tuple[dict, dict, list[dict]]:
    response = payload.get("response", payload)
    header = response.get("header", {}) if isinstance(response, dict) else {}
    body = response.get("body", {}) if isinstance(response, dict) else {}
    wrapped = body.get("items", {}) if isinstance(body, dict) else {}
    value = wrapped.get("item") if isinstance(wrapped, dict) else None
    if value is None:
        rows: list[dict] = []
    elif isinstance(value, dict):
        rows = [value]
    elif isinstance(value, list) and all(isinstance(row, dict) for row in value):
        rows = value
    else:
        raise ValueError("Unexpected API42 item structure")
    return header, body, rows


def collect() -> dict:
    website = json.loads(OBSERVATIONS.read_text(encoding="utf-8"))
    rows = website["rows"]
    con = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True, timeout=60)
    try:
        con.execute("PRAGMA query_only=ON")
        known = {
            str(horse_id).strip()
            for horse_id, breed in con.execute(
                "SELECT horse_id, breed_label_raw FROM horse_profile_latest "
                "WHERE breed_label_raw='제주마'"
            )
        }
    finally:
        con.close()

    candidate_ids = sorted(
        {
            str(row.get("horse_id") or "").strip()
            for row in rows
            if str(row.get("horse_id") or "").strip() not in known
        }
    )
    invalid = [horse_id for horse_id in candidate_ids if not re.fullmatch(r"\d{7}", horse_id)]
    candidate_ids = [horse_id for horse_id in candidate_ids if re.fullmatch(r"\d{7}", horse_id)]

    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise SystemExit("KRA service key unavailable; no API42 requests were made")
    key = secret.get_secret_value()
    attempt_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    attempt_dir = ROOT / "raw" / "api42_followup" / "attempts" / attempt_id
    page_dir = attempt_dir / "source_pages"
    page_dir.mkdir(parents=True, exist_ok=False)
    records: list[dict] = []

    for horse_id in candidate_ids:
        public = {"_type": "json", "pageNo": 1, "numOfRows": 1000, "hr_no": horse_id}
        request_url = f"{ENDPOINT}?{urlencode({**public, 'ServiceKey': key})}"
        request = Request(
            request_url,
            headers={"User-Agent": "horse_racing_jeju_research/1.0", "Accept": "application/json"},
        )
        status: int | None = None
        content_type: str | None = None
        body_bytes = b""
        error_type: str | None = None
        try:
            with urlopen(request, timeout=60) as response:
                status = response.status
                content_type = response.headers.get("Content-Type")
                body_bytes = response.read()
        except HTTPError as exc:
            status = exc.code
            content_type = exc.headers.get("Content-Type")
            body_bytes = exc.read()
        except (URLError, TimeoutError) as exc:
            error_type = type(exc).__name__

        if key.encode() in body_bytes or quote(key, safe="").encode() in body_bytes:
            records.append({"queried_hr_no": horse_id, "status": "credential_echo_refused", "http_status": status})
            continue

        record: dict = {
            "queried_hr_no": horse_id,
            "public_params": public,
            "http_status": status,
            "content_type": content_type,
            "response_bytes": len(body_bytes),
            "response_sha256": hashlib.sha256(body_bytes).hexdigest() if body_bytes else None,
            "service_key_recorded": False,
        }
        if error_type:
            record.update({"status": "transport_error", "error_type": error_type})
        elif status == 200:
            try:
                payload = json.loads(body_bytes)
                header, response_body, items = read_items(payload)
                code = str(header.get("resultCode") or "")
                if code not in SUCCESS_CODES:
                    record.update({"status": "api_error", "api_result_code": code, "api_result_message": str(header.get("resultMsg") or "")})
                else:
                    raw_path = page_dir / f"hr_no_{horse_id}.json"
                    raw_path.write_bytes(body_bytes)
                    matching = [item for item in items if str(item.get("hrNo") or "").strip() == horse_id]
                    record.update({
                        "status": "completed",
                        "api_result_code": code,
                        "api_result_message": str(header.get("resultMsg") or ""),
                        "api_total_count": int(response_body.get("totalCount") or 0),
                        "returned_rows": len(items),
                        "exact_hr_no_matches": len(matching),
                        "breed_raw_values": [item.get("breed") for item in matching],
                        "horse_name_raw_values": [item.get("hrNm") for item in matching],
                        "response_file": raw_path.relative_to(attempt_dir).as_posix(),
                    })
            except (ValueError, TypeError, json.JSONDecodeError):
                record.update({"status": "invalid_api_response", "error_type": "ResponseValidationError"})
        else:
            record.update({"status": "http_error", "error_type": "HTTPError"})
        records.append(record)
        time.sleep(0.2)

    manifest = {
        "attempt_id": attempt_id,
        "started_at_utc": attempt_id,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "source": "KRA API42_1 totalHorseInfo_1",
        "portal_dataset_id": "15057985",
        "endpoint": ENDPOINT,
        "operation": "totalHorseInfo_1",
        "official_metadata_url": "https://www.data.go.kr/data/15057985/openapi.do",
        "purpose": "Resolve current API42 breed evidence for official horse IDs in the starting-exam website rows that are absent from the frozen latest API42 Jeju-ma profile set.",
        "database_access": "SQLite read-only; no writes or imports",
        "meet2_is_breed_filter": False,
        "profile_timing_note": "API42 profile breed is a current retrieval-time observation and is not asserted historically for an exam date.",
        "candidate_unique_hr_no_count": len(candidate_ids),
        "invalid_id_count_not_requested": len(invalid),
        "invalid_ids_not_requested": invalid,
        "service_key_recorded": False,
        "probes": records,
    }
    manifest_path = attempt_dir / "attempt_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "attempt_id": attempt_id,
        "candidate_unique_ids": len(candidate_ids),
        "invalid_ids_not_requested": len(invalid),
        "completed": sum(item.get("status") == "completed" for item in records),
        "failed_or_invalid": sum(item.get("status") != "completed" for item in records),
        "exact_profile_match": sum(item.get("exact_hr_no_matches", 0) == 1 for item in records),
        "no_profile_returned": sum(item.get("status") == "completed" and item.get("exact_hr_no_matches") == 0 for item in records),
        "breed_counts": {},
        "manifest": manifest_path.relative_to(ROOT).as_posix(),
    }
    from collections import Counter

    summary["breed_counts"] = dict(sorted(Counter(
        str(breed).strip() if breed is not None else "<missing>"
        for item in records
        for breed in item.get("breed_raw_values", [])
    ).items()))
    (ROOT / "api42_followup_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    collect()
