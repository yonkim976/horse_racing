"""Collect API24_1 by validated 2002-2025 Jeju race day with checkpoints.

This collector is deliberately sequential, keeps raw response bytes immutable,
uses a caller-supplied per-KST-day API24 request budget, and never records the
service credential or exception text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import httpx  # noqa: E402

from horse_racing.collectors.kra_api import (  # noqa: E402
    HORSE_EQUIPMENT_ENDPOINT,
    HORSE_EQUIPMENT_OPERATION,
    response_body,
)
from horse_racing.config import get_settings  # noqa: E402

SOURCE_DATES = ROOT / "source_dates_2002_2025.json"
LEDGER = ROOT / "history_collection_ledger.json"
RAW_ROOT = ROOT / "raw/api24_1_history"
CORE_DB = PROJECT_ROOT / "jeju/data/jeju_native_core.sqlite3"
PAGE_SIZE = 1000
MEET = 2
REQUEST_INTERVAL_SECONDS = 1.0
TRANSIENT_REQUEST_MAX_ATTEMPTS = 3
TRANSIENT_RETRY_BACKOFF_SECONDS = (2.0, 4.0)
RETRYABLE_TIMEOUT_TYPES = {"ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout"}
SUCCESS_CODES = {"00", "0000"}
MAX_PAGE_COUNT_PER_DATE = 100
SEOUL = ZoneInfo("Asia/Seoul")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def kst_date_now() -> str:
    return datetime.now(SEOUL).date().isoformat()


def json_atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


def immutable_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        try:
            os.link(tmp, path)
        except FileExistsError:
            if path.read_bytes() != body:
                raise ValueError("immutable_response_conflict")
    finally:
        tmp.unlink(missing_ok=True)


def response_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = response_body(payload)
    items = body.get("items") or {}
    values = items.get("item") if isinstance(items, dict) else None
    if values is None:
        return []
    if isinstance(values, dict):
        return [values]
    if isinstance(values, list) and all(isinstance(row, dict) for row in values):
        return values
    raise ValueError("unexpected_item_structure")


def verify_source_dates() -> dict[str, Any]:
    """Revalidate annual API4_3 page hashes, dates and read-only DB date set."""
    source = json.loads(SOURCE_DATES.read_text(encoding="utf-8"))
    if source.get("date_count") != 2225 or len(source.get("dates", [])) != 2225:
        raise ValueError("history_source_date_count_invalid")
    if source.get("dates") != sorted(set(source.get("dates", []))):
        raise ValueError("history_source_dates_not_unique_sorted")
    observed_dates: set[str] = set()
    observed_page_count = 0
    for year_source in source.get("annual_sources", []):
        year = int(year_source["year"])
        if year_source.get("manifest_status") != "completed":
            raise ValueError("history_source_year_not_completed")
        year_dates: set[str] = set()
        row_count = 0
        for page in year_source.get("pages", []):
            path = PROJECT_ROOT / page["path"]
            body_bytes = path.read_bytes()
            if len(body_bytes) != int(page["bytes"]):
                raise ValueError("history_source_page_size_mismatch")
            if hashlib.sha256(body_bytes).hexdigest() != page["sha256"]:
                raise ValueError("history_source_page_sha256_mismatch")
            payload = json.loads(body_bytes)
            root = payload.get("response", payload)
            body = root.get("body") or {}
            if int(body.get("totalCount") or 0) != int(page["total_count"]):
                raise ValueError("history_source_total_count_mismatch")
            rows = response_rows(payload)
            if len(rows) != int(page["actual_rows"]):
                raise ValueError("history_source_row_count_mismatch")
            row_count += len(rows)
            for row in rows:
                if row.get("meet") != "제주":
                    continue
                rc_date = str(row.get("rcDate") or "")
                if not re.fullmatch(rf"{year}\d{{4}}", rc_date):
                    raise ValueError("history_source_invalid_rc_date")
                year_dates.add(rc_date)
            observed_page_count += 1
        if row_count != int(year_source["api_total_count"]):
            raise ValueError("history_source_year_row_count_mismatch")
        observed_dates |= year_dates
    frozen_dates = source["dates"]
    if sorted(observed_dates) != frozen_dates:
        raise ValueError("history_source_raw_date_set_mismatch")
    if source.get("annual_page_verification", {}).get("pages_sha256_and_bytes_verified") != observed_page_count:
        raise ValueError("history_source_page_inventory_mismatch")

    with sqlite3.connect(f"file:{CORE_DB}?mode=ro", uri=True) as conn:
        db_dates = sorted(
            {
                str(row[0]).replace("-", "")
                for row in conn.execute(
                    """SELECT DISTINCT race_date FROM race_result_rows
                       WHERE meet_code=2 AND race_date BETWEEN '2002-01-01' AND '2025-12-31'"""
                )
            }
        )
    if db_dates != frozen_dates:
        raise ValueError("history_source_core_db_date_set_mismatch")
    return source


def credential_candidates(secret: str) -> set[bytes]:
    return {
        secret.encode("utf-8"),
        quote(secret, safe="").encode("utf-8"),
        quote_plus(secret, safe="").encode("utf-8"),
    }


def contains_credential(body: bytes, candidates: set[bytes]) -> bool:
    return any(candidate and candidate in body for candidate in candidates)


def raw_path(rc_date: str, page_no: int) -> Path:
    return RAW_ROOT / rc_date / f"page_{page_no:04d}.json"


def parse_response(body_bytes: bytes) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(body_bytes)
    if not isinstance(payload, dict):
        raise ValueError("top_level_json_not_object")
    root = payload.get("response", payload)
    if not isinstance(root, dict):
        raise ValueError("response_not_object")
    header = root.get("header") or {}
    if not isinstance(header, dict):
        raise ValueError("header_not_object")
    # OpenAPI error responses may be JSON while `body` is a string. Classify
    # those from the header before asking the shared success-body parser to run.
    if str(header.get("resultCode") or "") not in SUCCESS_CODES:
        return header, {}, []
    body = response_body(payload)
    if not isinstance(body, dict):
        raise ValueError("body_not_object")
    return header, body, response_rows(payload)


def previous_page_metadata(record: dict[str, Any], page_no: int) -> dict[str, Any] | None:
    for attempt in reversed(record.get("attempts", [])):
        for page in attempt.get("pages", []):
            if int(page.get("page_no", -1)) == page_no:
                return page
    return None


def append_page_metadata_once(attempt: dict[str, Any], page: dict[str, Any]) -> None:
    if not any(existing is page for existing in attempt.get("pages", [])):
        attempt.setdefault("pages", []).append(page)


def page_request_attempt_count(record: dict[str, Any], page_no: int) -> int:
    """Count unique network starts already recorded for one page across resumes."""
    seen: set[tuple[Any, ...]] = set()
    for index, attempt in enumerate(record.get("attempts", []), start=1):
        date_attempt_no = int(attempt.get("attempt_no") or index)
        for page in attempt.get("pages", []):
            if int(page.get("page_no", -1)) != page_no:
                continue
            events = page.get("request_attempts")
            if isinstance(events, list) and events:
                for event in events:
                    if event.get("request_attempt_no") is not None:
                        seen.add(("request", event.get("request_attempt_no")))
                    elif event.get("requested_at_utc"):
                        seen.add(("legacy-event", event.get("requested_at_utc")))
                continue
            requested_at = page.get("requested_at_utc")
            if requested_at:
                # Legacy ledger entries have one network start per page metadata.
                # Deduplicate copies of recovered raw pages by their request time.
                seen.add(("legacy", requested_at))
            elif page.get("status") in {"request_failed", "request_interrupted", "http_error"}:
                seen.add(("legacy-no-time", date_attempt_no, page_no))
    return len(seen)


def page_has_retryable_timeout(record: dict[str, Any], page_no: int) -> bool:
    page = previous_page_metadata(record, page_no)
    if not page:
        return False
    events = page.get("request_attempts")
    if isinstance(events, list) and events:
        last = events[-1]
        return (last.get("status") == "request_failed"
                and last.get("exception_type") in RETRYABLE_TIMEOUT_TYPES)
    return (page.get("status") == "request_failed"
            and page.get("exception_type") in RETRYABLE_TIMEOUT_TYPES)


def row_date_mismatch(record: dict[str, Any]) -> bool:
    return any(
        page.get("period_validation") == "row_date_mismatch"
        for attempt in record.get("attempts", [])
        for page in attempt.get("pages", [])
    )


def mismatch_counts(dates: list[str], records: dict[str, Any]) -> tuple[int, int]:
    distinct = sum(row_date_mismatch(records[date]) for date in dates)
    trailing = 0
    for date in dates:
        status = records[date].get("status")
        if status == "pending":
            break
        if status == "validation_failed" and row_date_mismatch(records[date]):
            trailing += 1
        elif status in {"complete", "zero_rows"}:
            trailing = 0
        else:
            break
    return distinct, trailing


def year_coverage(dates: list[str], records: dict[str, Any]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for date in dates:
        year = date[:4]
        row = result.setdefault(year, Counter())
        status = records[date].get("status", "pending")
        row[status] += 1
        row["target_dates"] += 1
    return {year: dict(counts) for year, counts in sorted(result.items())}


def refresh_coverage(ledger: dict[str, Any], dates: list[str]) -> None:
    records = ledger["dates"]
    ledger["year_coverage"] = year_coverage(dates, records)
    mismatch_total, trailing = mismatch_counts(dates, records)
    ledger["scope_mismatch_count"] = mismatch_total
    ledger["consecutive_scope_mismatch_count"] = trailing
    ledger["scope_mismatch_dates"] = [
        date for date in dates if row_date_mismatch(records[date])
    ]


def make_ledger(source: dict[str, Any], source_sha: str) -> dict[str, Any]:
    dates = source["dates"]
    return {
        "run_id": datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ"),
        "source": "KRA official OpenAPI JSON; service credential not recorded",
        "credential_recorded": False,
        "endpoint": HORSE_EQUIPMENT_ENDPOINT,
        "operation": HORSE_EQUIPMENT_OPERATION,
        "meet": MEET,
        "date_filter": "rc_date",
        "page_size_requested": PAGE_SIZE,
        "request_interval_seconds_minimum": REQUEST_INTERVAL_SECONDS,
        "date_range": {"from": dates[0], "through": dates[-1]},
        "source_dates_file": SOURCE_DATES.name,
        "source_dates_sha256": source_sha,
        "source_date_count": len(dates),
        "dates_expected": dates,
        "network_request_count": 0,
        "network_request_count_by_kst_date": {},
        "stop_reason": None,
        "scope_mismatch_policy": {
            "counting_unit": "distinct requested race dates with any rcDate mismatch",
            "stop_threshold": 5,
            "stop_when": "cumulative or consecutive mismatch count reaches threshold",
        },
        "dates": {date: {"rc_date": date, "status": "pending", "attempts": []} for date in dates},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect API24_1 history over validated 2002-2025 Jeju race dates.")
    parser.add_argument("--request-budget", type=int, required=True,
                        help="Maximum API24 network request starts allocated to this collector for the current KST date.")
    parser.add_argument("--dry-run", action="store_true", help="Validate sources/ledger and show pending scope without requesting API data.")
    args = parser.parse_args()
    if args.request_budget < 0:
        parser.error("--request-budget must be non-negative")

    source = verify_source_dates()
    dates = source["dates"]
    source_sha = hashlib.sha256(SOURCE_DATES.read_bytes()).hexdigest()
    if LEDGER.exists():
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        if ledger.get("source_dates_sha256") != source_sha or ledger.get("dates_expected") != dates:
            raise ValueError("ledger_source_date_set_mismatch")
        ledger["resume_count"] = int(ledger.get("resume_count") or 0) + 1
        for rc_date, record in ledger["dates"].items():
            if record.get("status") == "running":
                record["status"] = "interrupted"
                record["last_attempt_finished_at_utc"] = utc_now()
                for attempt in record.get("attempts", []):
                    if attempt.get("status") == "running":
                        attempt["status"] = "interrupted"
                        attempt["exception_type"] = "InterruptedBeforeResume"
                        attempt["finished_at_utc"] = utc_now()
        ledger["stop_reason"] = None
    else:
        ledger = make_ledger(source, source_sha)

    if args.dry_run:
        pending = sum(ledger["dates"][d].get("status") in {"pending", "interrupted", "failed"} for d in dates)
        already_today = int(ledger.get("network_request_count_by_kst_date", {}).get(kst_date_now(), 0))
        print(json.dumps({
            "status": "dry_run_validated",
            "target_dates": len(dates),
            "pending_or_resumable_dates": pending,
            "source_dates_sha256": source_sha,
            "history_dates_verified_against_api4_3_and_core_read_only_db": True,
            "api24_requests_recorded_today_kst": already_today,
            "request_budget_today_kst": args.request_budget,
            "remaining_api24_budget_today_kst": max(0, args.request_budget - already_today),
        }, ensure_ascii=False))
        return 0

    if not LEDGER.exists():
        json_atomic_write(LEDGER, ledger)
    request_count = int(ledger.get("network_request_count") or 0)
    request_count_by_day = ledger.setdefault("network_request_count_by_kst_date", {})
    current_kst = kst_date_now()
    already_today = int(request_count_by_day.get(current_kst, 0))
    request_budget_remaining = max(0, args.request_budget - already_today)
    ledger["last_run_started_at_utc"] = utc_now()
    ledger["last_run_kst_date"] = current_kst
    ledger["last_run_request_budget_kst"] = args.request_budget
    ledger["last_run_request_count_start_kst"] = already_today
    ledger["last_run_requests_started"] = 0
    ledger["stop_reason"] = None
    refresh_coverage(ledger, dates)
    json_atomic_write(LEDGER, ledger)

    if request_budget_remaining == 0:
        ledger["stop_reason"] = "per_kst_day_request_budget_exhausted"
        ledger["updated_at_utc"] = utc_now()
        json_atomic_write(LEDGER, ledger)
        print(json.dumps({"status": "budget_exhausted", "request_count": request_count,
                          "today_kst": current_kst, "request_budget": args.request_budget}, ensure_ascii=False))
        return 1

    settings = get_settings()
    secret_setting = settings.data_go_kr_service_key
    if secret_setting is None or not secret_setting.get_secret_value().strip():
        ledger["stop_reason"] = "credential_unavailable"
        json_atomic_write(LEDGER, ledger)
        print(json.dumps({"status": "credential_unavailable"}, ensure_ascii=False))
        return 2
    secret = secret_setting.get_secret_value()
    secrets = credential_candidates(secret)
    base_url = settings.kra_api_base_url.rstrip("/")
    timeout = max(float(settings.http_timeout_seconds), 60.0)
    last_request_started = 0.0
    stop_collection = False
    today_requests_started = 0

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for date_index, rc_date in enumerate(dates, start=1):
            record = ledger["dates"][rc_date]
            if record.get("status") in {"complete", "zero_rows", "validation_failed"}:
                continue
            if record.get("status") == "api_error":
                if record.get("api_error_recovery_probe_status") == "normal_exact_date":
                    continue
                ledger["stop_reason"] = "existing_unresolved_api_error_requires_review"
                json_atomic_write(LEDGER, ledger)
                stop_collection = True
                break
            if record.get("status") == "failed":
                latest_page = next(
                    (page for prior_attempt in reversed(record.get("attempts", []))
                     for page in reversed(prior_attempt.get("pages", []))),
                    None,
                )
                failed_page_no = int(latest_page.get("page_no", -1)) if latest_page else -1
                retryable_failure = (
                    latest_page is not None
                    and latest_page.get("status") == "request_failed"
                    and page_has_retryable_timeout(record, failed_page_no)
                    and page_request_attempt_count(record, failed_page_no) < TRANSIENT_REQUEST_MAX_ATTEMPTS
                )
                if not retryable_failure:
                    ledger["stop_reason"] = "existing_failed_date_requires_review"
                    json_atomic_write(LEDGER, ledger)
                    stop_collection = True
                    break

            if ledger.get("scope_mismatch_count", 0) >= 5 or ledger.get("consecutive_scope_mismatch_count", 0) >= 5:
                ledger["stop_reason"] = "five_scope_date_mismatches"
                json_atomic_write(LEDGER, ledger)
                stop_collection = True
                break

            attempt = {"attempt_no": len(record.get("attempts", [])) + 1,
                       "status": "running", "started_at_utc": utc_now(), "pages": []}
            record.setdefault("attempts", []).append(attempt)
            record["status"] = "running"
            record["last_attempt_started_at_utc"] = attempt["started_at_utc"]
            json_atomic_write(LEDGER, ledger)

            try:
                page_no = 1
                expected_pages: int | None = None
                expected_total: int | None = None
                expected_page_size: int | None = None
                total_rows = 0
                matching_rows_total = 0
                returned_dates: Counter[str] = Counter()
                page_metadata: list[dict[str, Any]] = []
                while expected_pages is None or page_no <= expected_pages:
                    target = raw_path(rc_date, page_no)
                    public_params: dict[str, str | int] = {
                        "meet": MEET,
                        "rc_date": rc_date,
                        "_type": "json",
                        "pageNo": page_no,
                        "numOfRows": PAGE_SIZE,
                    }
                    prior = previous_page_metadata(record, page_no)
                    current_page = next(
                        (page for page in reversed(attempt.get("pages", []))
                         if int(page.get("page_no", -1)) == page_no),
                        None,
                    )
                    if target.exists():
                        body_bytes = target.read_bytes()
                        if contains_credential(body_bytes, secrets):
                            raise ValueError("archived_response_contains_credential")
                        fetched = dict(prior or {})
                        fetched["recovered_from_existing_raw"] = prior is None
                    else:
                        fetched = current_page or {
                            "page_no": page_no,
                            "public_params": public_params,
                            "request_attempts": [],
                        }
                        if current_page is None:
                            append_page_metadata_once(attempt, fetched)
                        fetched.setdefault("request_attempts", [])
                        active_day = kst_date_now()
                        used_today = int(request_count_by_day.get(active_day, 0))
                        if used_today >= args.request_budget:
                            ledger["stop_reason"] = "per_kst_day_request_budget_checkpoint"
                            record["status"] = "pending" if not attempt["pages"] else "interrupted"
                            attempt["status"] = "interrupted" if attempt["pages"] else "not_started_due_to_budget"
                            attempt["finished_at_utc"] = utc_now()
                            json_atomic_write(LEDGER, ledger)
                            stop_collection = True
                            break
                        delay = REQUEST_INTERVAL_SECONDS - (time.monotonic() - last_request_started)
                        if last_request_started and delay > 0:
                            time.sleep(delay)
                        # Recheck the budget after pacing in case another collector
                        # used the account quota while this process waited.
                        active_day = kst_date_now()
                        used_today = int(request_count_by_day.get(active_day, 0))
                        if used_today >= args.request_budget:
                            ledger["stop_reason"] = "per_kst_day_request_budget_checkpoint"
                            record["status"] = "pending" if not attempt["pages"] else "interrupted"
                            attempt["status"] = "interrupted" if attempt["pages"] else "not_started_due_to_budget"
                            attempt["finished_at_utc"] = utc_now()
                            json_atomic_write(LEDGER, ledger)
                            stop_collection = True
                            break
                        last_request_started = time.monotonic()
                        request_count += 1
                        today_requests_started += 1
                        request_count_by_day[active_day] = used_today + 1
                        ledger["network_request_count"] = request_count
                        ledger["last_run_requests_started"] = today_requests_started
                        requested_at = utc_now()
                        request_attempt_no = page_request_attempt_count(record, page_no) + 1
                        request_event = {
                            "request_attempt_no": request_attempt_no,
                            "date_attempt_no": attempt["attempt_no"],
                            "requested_at_utc": requested_at,
                            "status": "running",
                        }
                        fetched.setdefault("requested_at_utc", requested_at)
                        fetched["request_attempts"].append(request_event)
                        fetched["status"] = "request_in_progress"
                        json_atomic_write(LEDGER, ledger)
                        try:
                            response = client.get(
                                f"{base_url}{HORSE_EQUIPMENT_ENDPOINT}",
                                params={**public_params, "serviceKey": secret},
                            )
                        except KeyboardInterrupt:
                            request_event.update({"finished_at_utc": utc_now(),
                                                  "exception_type": "KeyboardInterrupt",
                                                  "status": "request_interrupted"})
                            fetched.update({"exception_type": "KeyboardInterrupt",
                                            "status": "request_interrupted"})
                            attempt["status"] = "interrupted"
                            attempt["exception_type"] = "KeyboardInterrupt"
                            attempt["finished_at_utc"] = utc_now()
                            record["status"] = "interrupted"
                            ledger["stop_reason"] = "collector_interrupted"
                            json_atomic_write(LEDGER, ledger)
                            stop_collection = True
                            break
                        except Exception as exc:
                            exception_type = type(exc).__name__
                            failed_at = utc_now()
                            request_event.update({"finished_at_utc": failed_at,
                                                  "exception_type": exception_type,
                                                  "status": "request_failed"})
                            fetched.update({"exception_type": exception_type,
                                            "status": "request_failed"})
                            if (isinstance(exc, httpx.TimeoutException)
                                    and exception_type in RETRYABLE_TIMEOUT_TYPES
                                    and request_attempt_no < TRANSIENT_REQUEST_MAX_ATTEMPTS):
                                json_atomic_write(LEDGER, ledger)
                                backoff_index = min(request_attempt_no - 1,
                                                    len(TRANSIENT_RETRY_BACKOFF_SECONDS) - 1)
                                time.sleep(TRANSIENT_RETRY_BACKOFF_SECONDS[backoff_index])
                                continue
                            attempt["status"] = "failed"
                            attempt["exception_type"] = exception_type
                            attempt["finished_at_utc"] = failed_at
                            record["status"] = "failed"
                            ledger["stop_reason"] = (
                                "transient_timeout_retry_limit_reached"
                                if isinstance(exc, httpx.TimeoutException)
                                and exception_type in RETRYABLE_TIMEOUT_TYPES
                                else "request_exception"
                            )
                            json_atomic_write(LEDGER, ledger)
                            stop_collection = True
                            break

                        retrieved_at = utc_now()
                        request_event.update({"retrieved_at_utc": retrieved_at,
                                              "http_status_code": response.status_code})
                        fetched["retrieved_at_utc"] = retrieved_at
                        fetched["http_status_code"] = response.status_code
                        if response.status_code != 200:
                            request_event.update({"exception_type": "HTTPStatusError", "status": "http_error"})
                            fetched.update({"exception_type": "HTTPStatusError", "status": "http_error"})
                            attempt["status"] = "failed"
                            attempt["exception_type"] = "HTTPStatusError"
                            attempt["finished_at_utc"] = retrieved_at
                            record["status"] = "failed"
                            ledger["stop_reason"] = "http_429_rate_limit" if response.status_code == 429 else "http_error"
                            json_atomic_write(LEDGER, ledger)
                            stop_collection = True
                            break
                        fetched.pop("exception_type", None)
                        body_bytes = response.content
                        request_event.update({"response_bytes": len(body_bytes),
                                              "response_sha256": hashlib.sha256(body_bytes).hexdigest()})
                        if contains_credential(body_bytes, secrets):
                            request_event.update({"exception_type": "CredentialEchoRejected",
                                                  "status": "credential_echo_rejected"})
                            fetched.update({"exception_type": "CredentialEchoRejected",
                                            "status": "credential_echo_rejected"})
                            attempt["status"] = "failed"
                            attempt["exception_type"] = "CredentialEchoRejected"
                            attempt["finished_at_utc"] = retrieved_at
                            record["status"] = "failed"
                            ledger["stop_reason"] = "credential_echo_rejected"
                            json_atomic_write(LEDGER, ledger)
                            stop_collection = True
                            break
                        immutable_write(target, body_bytes)
                        request_event["status"] = "http_200"
                        fetched.update({"content_type": response.headers.get("content-type"),
                                        "recovered_from_existing_raw": False})

                    fetched.update({"response_bytes": len(body_bytes),
                                    "response_sha256": hashlib.sha256(body_bytes).hexdigest(),
                                    "response_file": str(target.relative_to(ROOT))})
                    try:
                        header, api_body, rows = parse_response(body_bytes)
                    except Exception as exc:
                        fetched.update({"exception_type": type(exc).__name__, "status": "invalid_json_or_schema"})
                        append_page_metadata_once(attempt, fetched)
                        attempt["status"] = "failed"
                        attempt["exception_type"] = type(exc).__name__
                        attempt["finished_at_utc"] = utc_now()
                        record["status"] = "failed"
                        ledger["stop_reason"] = "invalid_json_or_schema"
                        json_atomic_write(LEDGER, ledger)
                        stop_collection = True
                        break

                    result_code = str(header.get("resultCode") or "")
                    if result_code not in SUCCESS_CODES:
                        fetched.update({"api_result_code": result_code,
                                        "response_body_shape": "non_object_or_error_payload",
                                        "status": "api_error"})
                        append_page_metadata_once(attempt, fetched)
                        attempt["status"] = "api_error"
                        attempt["exception_type"] = "KraApiError"
                        attempt["finished_at_utc"] = utc_now()
                        record["status"] = "api_error"
                        record["last_api_error_code"] = result_code
                        ledger["stop_reason"] = "api_error"
                        json_atomic_write(LEDGER, ledger)
                        stop_collection = True
                        break
                    if any(name not in api_body for name in ("totalCount", "numOfRows", "pageNo")):
                        fetched["status"] = "pagination_metadata_missing"
                        append_page_metadata_once(attempt, fetched)
                        attempt["status"] = "failed"
                        attempt["exception_type"] = "PaginationMetadataError"
                        attempt["finished_at_utc"] = utc_now()
                        record["status"] = "failed"
                        ledger["stop_reason"] = "pagination_metadata_missing"
                        json_atomic_write(LEDGER, ledger)
                        stop_collection = True
                        break

                    total_count = int(api_body["totalCount"])
                    api_page_size = int(api_body["numOfRows"])
                    api_page_no = int(api_body["pageNo"])
                    matching = sum(str(row.get("rcDate") or "") == rc_date for row in rows)
                    value_counts = Counter(str(row.get("rcDate") or "") for row in rows)
                    returned_dates.update(value_counts)
                    fetched.update({
                        "api_result_code": result_code,
                        "api_total_count": total_count,
                        "api_page_size": api_page_size,
                        "api_page_no": api_page_no,
                        "actual_page_rows": len(rows),
                        "row_date_field": "rcDate",
                        "records_matching_requested_date": matching,
                        "response_rcdate_value_counts": dict(sorted(value_counts.items())),
                        "status": "http_success",
                    })
                    if api_page_no != page_no or api_page_size <= 0 or total_count < 0:
                        fetched["status"] = "pagination_metadata_mismatch"
                        append_page_metadata_once(attempt, fetched)
                        attempt["status"] = "failed"
                        attempt["exception_type"] = "PaginationMetadataError"
                        attempt["finished_at_utc"] = utc_now()
                        record["status"] = "failed"
                        ledger["stop_reason"] = "pagination_metadata_mismatch"
                        json_atomic_write(LEDGER, ledger)
                        stop_collection = True
                        break
                    if expected_total is None:
                        expected_total = total_count
                        expected_page_size = api_page_size
                        expected_pages = max(1, math.ceil(expected_total / expected_page_size))
                        if expected_pages > MAX_PAGE_COUNT_PER_DATE:
                            fetched["status"] = "page_count_safety_limit"
                            append_page_metadata_once(attempt, fetched)
                            attempt["status"] = "failed"
                            attempt["exception_type"] = "PaginationSafetyLimit"
                            attempt["finished_at_utc"] = utc_now()
                            record["status"] = "failed"
                            ledger["stop_reason"] = "page_count_safety_limit"
                            json_atomic_write(LEDGER, ledger)
                            stop_collection = True
                            break
                    elif total_count != expected_total or api_page_size != expected_page_size:
                        fetched["status"] = "pagination_total_changed"
                        append_page_metadata_once(attempt, fetched)
                        attempt["status"] = "failed"
                        attempt["exception_type"] = "PaginationMetadataError"
                        attempt["finished_at_utc"] = utc_now()
                        record["status"] = "failed"
                        ledger["stop_reason"] = "pagination_total_changed"
                        json_atomic_write(LEDGER, ledger)
                        stop_collection = True
                        break
                    fetched["period_validation"] = "all_page_rows_exact_date_match" if matching == len(rows) else "row_date_mismatch"
                    page_metadata.append(fetched)
                    append_page_metadata_once(attempt, fetched)
                    total_rows += len(rows)
                    matching_rows_total += matching
                    attempt.update({"api_total_count": expected_total,
                                    "expected_page_count": expected_pages,
                                    "actual_page_count_so_far": len(page_metadata),
                                    "actual_rows_so_far": total_rows,
                                    "matching_date_rows_so_far": matching_rows_total})
                    json_atomic_write(LEDGER, ledger)
                    page_no += 1

                if stop_collection:
                    break
                assert expected_pages is not None and expected_total is not None
                actual_pages = len(page_metadata)
                pagination_complete = (
                    actual_pages == expected_pages and total_rows == expected_total
                    and all(p["api_total_count"] == expected_total for p in page_metadata)
                    and all(p["api_page_size"] == expected_page_size for p in page_metadata)
                    and all(p["api_page_no"] == p["page_no"] for p in page_metadata)
                )
                exact_date_scope = total_rows == matching_rows_total
                attempt.update({
                    "actual_page_count": actual_pages,
                    "actual_total_rows": total_rows,
                    "rows_matching_requested_date": matching_rows_total,
                    "row_date_mismatch_rows": total_rows - matching_rows_total,
                    "returned_rcdate_value_counts": dict(sorted(returned_dates.items())),
                    "requested_rc_date": rc_date,
                    "row_date_field": "rcDate",
                    "pagination_validation": "complete" if pagination_complete else "count_or_page_mismatch",
                    "period_validation": "all_rows_match_requested_date" if exact_date_scope else "row_date_mismatch",
                    "finished_at_utc": utc_now(),
                })
                record["last_attempt_finished_at_utc"] = attempt["finished_at_utc"]
                if not pagination_complete:
                    attempt["status"] = "failed"
                    attempt["exception_type"] = "PaginationValidationError"
                    record["status"] = "failed"
                    ledger["stop_reason"] = "pagination_validation_failure"
                    stop_collection = True
                elif not exact_date_scope:
                    attempt["status"] = "validation_failed"
                    attempt["exception_type"] = "RowDateMismatch"
                    record["status"] = "validation_failed"
                elif expected_total == 0:
                    attempt["status"] = "zero_rows"
                    record["status"] = "zero_rows"
                else:
                    attempt["status"] = "complete"
                    record["status"] = "complete"
                refresh_coverage(ledger, dates)
                mismatch_total = ledger["scope_mismatch_count"]
                trailing_mismatches = ledger["consecutive_scope_mismatch_count"]
                if mismatch_total >= 5 or trailing_mismatches >= 5:
                    ledger["stop_reason"] = "five_scope_date_mismatches"
                    stop_collection = True
                json_atomic_write(LEDGER, ledger)
                print(json.dumps({"date": rc_date, "status": record["status"],
                                  "date_progress": f"{date_index}/{len(dates)}",
                                  "network_request_count": request_count,
                                  "requests_started_today_kst": request_count_by_day.get(kst_date_now(), 0),
                                  "mismatch_count": mismatch_total,
                                  "consecutive_mismatches": trailing_mismatches}, ensure_ascii=False), flush=True)
                if stop_collection:
                    break
            except KeyboardInterrupt:
                attempt["status"] = "interrupted"
                attempt["exception_type"] = "KeyboardInterrupt"
                attempt["finished_at_utc"] = utc_now()
                record["status"] = "interrupted"
                record["last_attempt_finished_at_utc"] = attempt["finished_at_utc"]
                ledger["stop_reason"] = "collector_interrupted"
                json_atomic_write(LEDGER, ledger)
                stop_collection = True
            except Exception as exc:
                attempt["status"] = "failed"
                attempt["exception_type"] = type(exc).__name__
                attempt["finished_at_utc"] = utc_now()
                record["status"] = "failed"
                record["last_attempt_finished_at_utc"] = attempt["finished_at_utc"]
                ledger["stop_reason"] = "collector_exception"
                json_atomic_write(LEDGER, ledger)
                stop_collection = True
            if stop_collection:
                break

    ledger["network_request_count"] = request_count
    ledger["last_run_requests_started"] = today_requests_started
    ledger["updated_at_utc"] = utc_now()
    ledger["last_run_finished_at_utc"] = utc_now()
    refresh_coverage(ledger, dates)
    if not stop_collection and all(ledger["dates"][d].get("status") in {"complete", "zero_rows", "validation_failed"} for d in dates):
        ledger["stop_reason"] = "all_history_dates_examined_with_validation_exclusions" if ledger["scope_mismatch_count"] else "all_history_dates_processed"
    elif not stop_collection:
        ledger["stop_reason"] = "per_kst_day_request_budget_checkpoint"
    json_atomic_write(LEDGER, ledger)
    counts = Counter(row.get("status", "pending") for row in ledger["dates"].values())
    print(json.dumps({"ledger": str(LEDGER), "target_dates": len(dates),
                      "status_counts": dict(sorted(counts.items())),
                      "network_request_count": request_count,
                      "requests_started_today_kst": request_count_by_day.get(kst_date_now(), 0),
                      "request_budget_today_kst": args.request_budget,
                      "scope_mismatch_count": ledger.get("scope_mismatch_count", 0),
                      "scope_mismatch_dates": ledger.get("scope_mismatch_dates", []),
                      "stop_reason": ledger.get("stop_reason")}, ensure_ascii=False))
    return 0 if all(row.get("status") in {"complete", "zero_rows", "validation_failed"} for row in ledger["dates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
