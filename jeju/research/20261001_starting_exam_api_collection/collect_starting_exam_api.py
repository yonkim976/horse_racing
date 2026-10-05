"""Collect one official KRA starting-exam API21_1 year/month/date partition.

Each run creates an immutable attempt folder. HTTP bodies are archived unchanged
only when they do not contain the configured service key. The program uses a
fixed HTTPS endpoint, reads credentials from the project's secret settings, and
never writes to the local database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from typing import Any
from zoneinfo import ZoneInfo

from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parent
PARTITIONS = ROOT / "raw" / "api21_1" / "partitions"
PORTAL_URL = "https://www.data.go.kr/data/15057405/openapi.do"
ENDPOINT = "https://apis.data.go.kr/B551015/API21_1/startingTestResult_1"
OPERATION = "startingTestResult_1"
MEET = 2
PAGE_SIZE = 1000
SUCCESS_CODES = {"00", "0000"}
FAILURE_CODES = {"SERVICE_KEY_IS_NOT_REGISTERED_ERROR", "SERVICE_ACCESS_DENIED_ERROR", "SERVICE_KEY_IS_NULL"}


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def atomic_replace(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def response_parts(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    wrapped = payload.get("response", payload)
    header = wrapped.get("header", {}) if isinstance(wrapped, dict) else {}
    body = wrapped.get("body", {}) if isinstance(wrapped, dict) else {}
    items_obj = body.get("items", {}) if isinstance(body, dict) else {}
    item_value = items_obj.get("item") if isinstance(items_obj, dict) else None
    if item_value is None:
        rows: list[dict[str, Any]] = []
    elif isinstance(item_value, dict):
        rows = [item_value]
    elif isinstance(item_value, list) and all(isinstance(item, dict) for item in item_value):
        rows = item_value
    else:
        raise ValueError("Unexpected API21 item structure")
    return header, body, rows


def error_details(body: bytes) -> tuple[str | None, str | None, str | None]:
    """Extract gateway error fields without ever exposing request URLs."""
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None, None, None
    current: Any = payload
    if isinstance(current, dict) and isinstance(current.get("OpenAPI_ServiceResponse"), dict):
        current = current["OpenAPI_ServiceResponse"].get("cmmMsgHeader", {})
    elif isinstance(current, dict):
        response = current.get("response", current)
        current = response.get("header", {}) if isinstance(response, dict) else {}
    if not isinstance(current, dict):
        return None, None, None
    return (
        str(current.get("errMsg") or current.get("resultCode") or "") or None,
        str(current.get("returnReasonCode") or "") or None,
        str(current.get("returnAuthMsg") or current.get("resultMsg") or "") or None,
    )


def query_for(year: int, month: str | None, date: str | None, end_date: str) -> tuple[str, dict[str, str | int]]:
    if year > int(end_date[:4]):
        raise ValueError("--year cannot be after --end-date")
    if (month is None) == (date is None):
        public: dict[str, str | int] = {"meet": MEET, "tr_year": str(year), "_type": "json"}
        return f"year_{year}", public
    if month is not None:
        if not re.fullmatch(r"\d{6}", month) or int(month[:4]) != year or not 1 <= int(month[4:]) <= 12:
            raise ValueError("--month must be YYYYMM within --year")
        if month > end_date[:6]:
            raise ValueError("--month cannot be after --end-date")
        return f"month_{month}", {"meet": MEET, "tr_month": month, "_type": "json"}
    assert date is not None
    if not re.fullmatch(r"\d{8}", date) or int(date[:4]) != year:
        raise ValueError("--date must be YYYYMMDD within --year")
    datetime.strptime(date, "%Y%m%d")
    if date > end_date:
        raise ValueError("--date cannot be after --end-date")
    return f"date_{date}", {"meet": MEET, "tr_date": date, "_type": "json"}


def existing_completed_attempt(partition_dir: Path) -> Path | None:
    for manifest_path in sorted(partition_dir.glob("attempts/*/attempt_manifest.json"), reverse=True):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("status") == "completed_api_response":
            return manifest_path
    return None


def immutable_attempt_dir(partition_dir: Path) -> tuple[str, Path]:
    attempts = partition_dir / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    base = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    attempt_id = base
    suffix = 1
    while True:
        path = attempts / attempt_id
        try:
            path.mkdir()
            return attempt_id, path
        except FileExistsError:
            suffix += 1
            attempt_id = f"{base}-{suffix}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True, choices=range(2000, 2027))
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--month", help="Fallback partition YYYYMM")
    scope.add_argument("--date", help="Fallback partition YYYYMMDD")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--end-date", help="Inclusive reporting cutoff YYYYMMDD; defaults to the current Asia/Seoul date.")
    parser.add_argument("--retry-complete", action="store_true", help="Create a new attempt even if this partition has a completed capture.")
    args = parser.parse_args()
    end_date = args.end_date or datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    if not re.fullmatch(r"\d{8}", end_date):
        raise SystemExit("--end-date must be YYYYMMDD")
    try:
        datetime.strptime(end_date, "%Y%m%d")
    except ValueError as exc:
        raise SystemExit("--end-date must be a valid calendar date") from exc
    partition_key, public_params = query_for(args.year, args.month, args.date, end_date)
    partition_dir = PARTITIONS / partition_key
    if not args.retry_complete:
        completed = existing_completed_attempt(partition_dir)
        if completed:
            print(json.dumps({"partition": partition_key, "status": "already_complete", "manifest": str(completed.relative_to(ROOT))}))
            return

    settings = get_settings()
    configured = settings.data_go_kr_service_key
    if configured is None:
        raise SystemExit("KRA service key unavailable; no request was made")
    secret = configured.get_secret_value()
    attempt_id, attempt_dir = immutable_attempt_dir(partition_dir)
    manifest_path = attempt_dir / "attempt_manifest.json"
    started = now_utc()
    requested_params = {**public_params, "pageNo": 1, "numOfRows": PAGE_SIZE}
    base_manifest: dict[str, Any] = {
        "attempt_id": attempt_id,
        "partition": partition_key,
        "started_at_utc": started,
        "source": "KRA OpenAPI 15057405 한국마사회 출발심사 결과",
        "portal_metadata_url": PORTAL_URL,
        "endpoint": "/API21_1/startingTestResult_1",
        "operation": OPERATION,
        "source_host": "apis.data.go.kr",
        "requested_scope": {**public_params, "page_size": PAGE_SIZE},
        "inclusive_reporting_cutoff": end_date,
        "cutoff_default_basis": "current Asia/Seoul date" if args.end_date is None else "explicit --end-date",
        "raw_response_cutoff_note": "Year-filtered API pages contain the entire requested year, and month-filtered pages may contain dates after the inclusive cutoff. Raw pages are preserved byte-for-byte; downstream candidate rows must filter trainDate to the requested cutoff.",
        "authentication_parameter_name": "ServiceKey",
        "service_key_recorded": False,
        "api21_output_schema_fields": ["meet", "trainDate", "daySerial", "trainNo", "chulNo", "hrName", "hrNo", "name", "sex", "age", "rider", "trName", "trNo", "owName", "owNo", "passFlag", "reason", "nopassReason"],
        "source_page_storage": "source_pages/page_NNNN.json (successful response body bytes unchanged)",
        "api21_zero_or_blank_judgement_note": "Only explicit passFlag labels are summarized. A zero or blank value is unknown, not a failure.",
        "existing_attempt_artifacts_overwritten": False,
        "database_write_performed": False,
    }
    atomic_replace(manifest_path, json_bytes({**base_manifest, "status": "in_progress", "source_pages": []}))

    page_records: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    total_values: set[int] = set()
    failed_status: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    page_no = 1

    while True:
        requested_at = now_utc()
        params = {**public_params, "pageNo": page_no, "numOfRows": PAGE_SIZE, "ServiceKey": secret}
        request = Request(
            f"{ENDPOINT}?{urlencode(params)}",
            headers={"User-Agent": "horse_racing_jeju_research/1.0", "Accept": "application/json"},
        )
        status: int | None = None
        content_type: str | None = None
        raw_body = b""
        transport_error: str | None = None
        try:
            with urlopen(request, timeout=args.timeout) as response:
                status = response.status
                content_type = response.headers.get("Content-Type")
                raw_body = response.read()
        except HTTPError as exc:
            status = exc.code
            content_type = exc.headers.get("Content-Type")
            raw_body = exc.read()
        except (URLError, TimeoutError) as exc:
            transport_error = type(exc).__name__

        retrieved_at = now_utc()
        if secret.encode() in raw_body or quote(secret, safe="").encode() in raw_body:
            failed_status = "credential_echo_refused"
            failure_message = "Response body contained the configured credential; body was not saved."
            break
        if transport_error:
            failed_status = "transport_error"
            failure_message = transport_error
            break

        body_path = attempt_dir / "source_pages" / f"page_{page_no:04d}.json"
        response_record: dict[str, Any] = {
            "page_no": page_no,
            "requested_at_utc": requested_at,
            "retrieved_at_utc": retrieved_at,
            "status_code": status,
            "content_type": content_type,
            "response_bytes": len(raw_body),
            "response_sha256": hashlib.sha256(raw_body).hexdigest(),
            "source_url_without_key": ENDPOINT + "?" + urlencode({**public_params, "pageNo": page_no, "numOfRows": PAGE_SIZE}),
        }
        if status != 200:
            body_path.parent.mkdir(parents=True, exist_ok=True)
            body_path.write_bytes(raw_body)
            code, reason, message = error_details(raw_body)
            response_record.update({
                "status": "http_error_body",
                "response_file": body_path.relative_to(attempt_dir).as_posix(),
                "api_error_code": code,
                "api_error_reason_code": reason,
                "api_error_message": message,
            })
            page_records.append(response_record)
            failure_code, failure_message = code, message
            failed_status = "failed_authorization" if code in FAILURE_CODES or reason == "30" else "http_error"
            break

        try:
            payload = json.loads(raw_body)
            header, response_body, rows = response_parts(payload)
        except (ValueError, TypeError, json.JSONDecodeError):
            body_path.parent.mkdir(parents=True, exist_ok=True)
            body_path.write_bytes(raw_body)
            response_record.update({"status": "invalid_api_response", "response_file": body_path.relative_to(attempt_dir).as_posix()})
            page_records.append(response_record)
            failed_status = "invalid_api_response"
            failure_message = "Response was not the documented JSON structure."
            break

        result_code = str(header.get("resultCode") or "")
        if result_code not in SUCCESS_CODES:
            body_path.parent.mkdir(parents=True, exist_ok=True)
            body_path.write_bytes(raw_body)
            code, reason, message = error_details(raw_body)
            response_record.update({
                "status": "api_error_body",
                "response_file": body_path.relative_to(attempt_dir).as_posix(),
                "api_result_code": result_code,
                "api_error_code": code,
                "api_error_reason_code": reason,
                "api_error_message": message or str(header.get("resultMsg") or ""),
            })
            page_records.append(response_record)
            failure_code = code or result_code
            failure_message = message or str(header.get("resultMsg") or "")
            failed_status = "failed_authorization" if failure_code in FAILURE_CODES or reason == "30" else "api_error"
            break

        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_bytes(raw_body)
        total = int(response_body.get("totalCount") or 0)
        actual_num_rows = int(response_body.get("numOfRows") or PAGE_SIZE)
        total_values.add(total)
        all_rows.extend(rows)
        response_record.update({
            "status": "completed",
            "response_file": body_path.relative_to(attempt_dir).as_posix(),
            "api_result_code": result_code,
            "api_total_count": total,
            "api_num_of_rows": actual_num_rows,
            "api_page_no": int(response_body.get("pageNo") or page_no),
            "actual_rows": len(rows),
        })
        page_records.append(response_record)
        atomic_replace(manifest_path, json_bytes({
            **base_manifest,
            "status": "in_progress",
            "updated_at_utc": now_utc(),
            "source_pages": page_records,
            "rows_seen_so_far": len(all_rows),
        }))
        total_pages = max(1, (total + max(actual_num_rows, 1) - 1) // max(actual_num_rows, 1))
        if page_no >= total_pages:
            break
        page_no += 1
        time.sleep(0.2)

    if failed_status is None:
        expected = max(total_values) if total_values else 0
        totals_consistent = len(total_values) <= 1
        count_matches = len(all_rows) == expected
        manifest_status = "completed_api_response" if totals_consistent and count_matches else "incomplete_api_response"
        page_rows = Counter(str(row.get("passFlag") or "<blank>").strip() for row in all_rows)
        after_cutoff_rows = [
            row for row in all_rows
            if re.fullmatch(r"\d{8}", str(row.get("trainDate") or "").strip())
            and str(row.get("trainDate")).strip() > end_date
        ]
        unparseable_date_rows = sum(
            not re.fullmatch(r"\d{8}", str(row.get("trainDate") or "").strip())
            for row in all_rows
        )
        manifest = {
            **base_manifest,
            "status": manifest_status,
            "completed_at_utc": now_utc(),
            "response_page_count": len(page_records),
            "upstream_total_count": expected,
            "upstream_total_count_values_across_pages": sorted(total_values),
            "upstream_rows_seen": len(all_rows),
            "upstream_total_count_consistent": totals_consistent,
            "upstream_row_count_matches_total": count_matches,
            "passFlag_raw_counts": dict(sorted(page_rows.items())),
            "rows_after_inclusive_cutoff_in_preserved_raw": len(after_cutoff_rows),
            "rows_without_parseable_trainDate": unparseable_date_rows,
            "annual_partition_scope_note": "A successful tr_year request is complete for that entire year as returned by the API. Apply inclusive_reporting_cutoff when deriving candidate rows.",
            "source_pages": page_records,
            "fallback_note": "This run covered one requested partition. Use explicit --month or --date calls only after an annual query returns a discrepancy and API access is available.",
        }
    else:
        manifest = {
            **base_manifest,
            "status": failed_status,
            "completed_at_utc": now_utc(),
            "rows_seen_before_failure": len(all_rows),
            "api_error_code": failure_code,
            "failure_detail": failure_message,
            "source_pages": page_records,
            "retry_note": "After the API21 service key is registered or authorized in data.go.kr, rerun the same --year/--month/--date command. Failed attempts are kept and never replaced.",
        }
    atomic_replace(manifest_path, json_bytes(manifest))
    print(json.dumps({
        "partition": partition_key,
        "attempt_id": attempt_id,
        "status": manifest["status"],
        "api_error_code": manifest.get("api_error_code"),
        "rows": manifest.get("upstream_rows_seen", manifest.get("rows_seen_before_failure", 0)),
        "manifest": manifest_path.relative_to(ROOT).as_posix(),
    }, ensure_ascii=False))
    if manifest["status"] != "completed_api_response":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
