"""Collect API24_1 by official 2026 Jeju race day, with resumable raw pages.

This script intentionally issues one HTTP request at a time and does not retry
HTTP failures. Raw response bodies and a sanitized ledger live only beside this
script. Credentials are read in memory from project settings and never written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus, urlencode, urlsplit, urlunsplit


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


CORE_DB = PROJECT_ROOT / "jeju/data/jeju_native_core.sqlite3"
SOURCE_DATES = ROOT / "source_dates_2026.json"
LEDGER = ROOT / "collection_ledger.json"
RAW_ROOT = ROOT / "raw/api24_1"
PAGE_SIZE = 1000
START_DATE = "20260101"
CUTOFF_DATE = "20260919"
MEET = 2
REQUEST_INTERVAL_SECONDS = 1.0
SOURCE_ENDPOINT = "https://apis.data.go.kr/B551015/API4_3/raceResult_3"
SUCCESS_CODES = {"00", "0000"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


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


def read_source_dates() -> dict[str, Any]:
    """Derive, hash-check, and cross-check dates using the validated API4_3 raw page."""
    with sqlite3.connect(f"file:{CORE_DB}?mode=ro", uri=True) as conn:
        artifact_rows = conn.execute(
            """
            SELECT DISTINCT sa.endpoint, sa.operation, sa.attempt_id,
                   sa.request_params_json, sa.raw_relative_path, sa.sha256,
                   c.api_total_count, c.page_count, c.response_row_count,
                   c.status
            FROM source_artifacts AS sa
            JOIN api_records AS ar ON ar.source_artifact_id = sa.source_artifact_id
            JOIN race_result_rows AS rr ON rr.api_record_id = ar.api_record_id
            JOIN collection_coverage AS c ON c.attempt_id = sa.attempt_id
                                         AND c.operation = sa.operation
                                         AND c.year = 2026
            WHERE sa.operation = 'raceResult_3'
              AND rr.meet_code = 2
              AND rr.race_date BETWEEN '2026-01-01' AND '2026-09-19'
            """
        ).fetchall()
        db_dates = [
            row[0]
            for row in conn.execute(
                """
                SELECT DISTINCT replace(rr.race_date, '-', '')
                FROM race_result_rows AS rr
                JOIN api_records AS ar ON ar.api_record_id = rr.api_record_id
                JOIN source_artifacts AS sa ON sa.source_artifact_id = ar.source_artifact_id
                WHERE sa.operation = 'raceResult_3'
                  AND rr.meet_code = 2
                  AND rr.race_date BETWEEN '2026-01-01' AND '2026-09-19'
                ORDER BY 1
                """
            ).fetchall()
        ]

    if len(artifact_rows) != 1:
        raise ValueError("api4_3_source_artifact_not_unique")
    (
        endpoint,
        operation,
        attempt_id,
        request_params_json,
        raw_relative_path,
        expected_sha256,
        api_total_count,
        page_count,
        response_row_count,
        coverage_status,
    ) = artifact_rows[0]
    params = json.loads(request_params_json)
    if (
        endpoint != SOURCE_ENDPOINT
        or operation != "raceResult_3"
        or str(params.get("meet")) != "2"
        or str(params.get("rc_year")) != "2026"
        or int(api_total_count or 0) != int(response_row_count or 0)
        or int(page_count or 0) != 1
        or coverage_status != "completed_api_result_rows"
    ):
        raise ValueError("api4_3_source_coverage_not_validated")

    raw_path = PROJECT_ROOT / raw_relative_path
    raw_bytes = raw_path.read_bytes()
    source_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if source_sha256 != expected_sha256:
        raise ValueError("api4_3_source_sha256_mismatch")
    source_payload = json.loads(raw_bytes)
    source_header = (source_payload.get("response") or source_payload).get("header") or {}
    if str(source_header.get("resultCode") or "") not in SUCCESS_CODES:
        raise ValueError("api4_3_source_result_code_not_success")
    source_body = response_body(source_payload)
    if int(source_body.get("totalCount") or 0) != int(api_total_count or 0):
        raise ValueError("api4_3_raw_total_count_mismatch")
    api_rows = response_rows(source_payload)
    if len(api_rows) != int(api_total_count or 0):
        raise ValueError("api4_3_raw_row_count_mismatch")

    dates: set[str] = set()
    for row in api_rows:
        if str(row.get("meet") or "") != "제주":
            continue
        rc_date = str(row.get("rcDate") or "")
        if len(rc_date) != 8 or not rc_date.isdigit():
            raise ValueError("api4_3_invalid_rc_date")
        if START_DATE <= rc_date <= CUTOFF_DATE:
            dates.add(rc_date)
    sorted_dates = sorted(dates)
    if sorted_dates != sorted(db_dates):
        raise ValueError("api4_3_raw_database_date_set_mismatch")
    if len(sorted_dates) != 79:
        raise ValueError("api4_3_race_day_count_unexpected")

    result = {
        "source": "validated KRA OpenAPI API4_3/raceResult_3 raw response; read-only core DB cross-check",
        "source_endpoint": endpoint,
        "source_operation": operation,
        "source_attempt_id": attempt_id,
        "source_request_params": params,
        "source_raw_path": raw_relative_path,
        "source_raw_sha256": source_sha256,
        "source_api_total_count": int(api_total_count),
        "source_actual_row_count": len(api_rows),
        "date_rule": "unique rcDate where API4_3 meet is 제주, 2026-01-01 through 2026-09-19 inclusive",
        "cutoff_date": CUTOFF_DATE,
        "cross_check": "exact date-set equality with meet_code=2 race_result_rows for the same API4_3 source artifact",
        "date_count": len(sorted_dates),
        "dates": sorted_dates,
    }
    if SOURCE_DATES.exists():
        existing = json.loads(SOURCE_DATES.read_text(encoding="utf-8"))
        if existing != result:
            raise ValueError("frozen_source_date_set_changed")
    else:
        json_atomic_write(SOURCE_DATES, result)
    return result


def credential_candidates(secret: str) -> set[bytes]:
    return {
        secret.encode("utf-8"),
        quote(secret, safe="").encode("utf-8"),
        quote_plus(secret, safe="").encode("utf-8"),
    }


def contains_credential(body: bytes, candidates: set[bytes]) -> bool:
    return any(candidate and candidate in body for candidate in candidates)


def public_url(base_url: str, params: dict[str, str | int]) -> str:
    split = urlsplit(base_url.rstrip("/") + HORSE_EQUIPMENT_ENDPOINT)
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(params), ""))


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
    body = response_body(payload)
    if not isinstance(body, dict):
        raise ValueError("body_not_object")
    rows = response_rows(payload)
    return header, body, rows


def previous_page_metadata(record: dict[str, Any], page_no: int) -> dict[str, Any] | None:
    for attempt in reversed(record.get("attempts", [])):
        for page in attempt.get("pages", []):
            if int(page.get("page_no", -1)) == page_no:
                return page
    return None


def has_row_date_mismatch(record: dict[str, Any]) -> bool:
    return any(
        page.get("period_validation") == "row_date_mismatch"
        for attempt in record.get("attempts", [])
        for page in attempt.get("pages", [])
    )


def scope_mismatch_counts(dates: list[str], date_records: dict[str, Any]) -> tuple[int, int]:
    """Return distinct mismatched dates and the trailing observed consecutive run."""
    mismatch_dates = sum(has_row_date_mismatch(date_records[date]) for date in dates)
    trailing = 0
    for date in reversed(dates):
        record = date_records[date]
        if record.get("status") == "pending":
            continue
        if has_row_date_mismatch(record):
            trailing += 1
            continue
        if record.get("status") in {"complete", "zero_rows"}:
            break
        break
    return mismatch_dates, trailing


def safe_exception_type(exc: BaseException) -> str:
    # Never persist exception text: HTTP clients may include a credential URL.
    return type(exc).__name__


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect official API24_1 Jeju date partitions.")
    parser.add_argument(
        "--skip-validation-failed",
        action="store_true",
        help="Leave existing validation_failed dates excluded and continue to later dates.",
    )
    args = parser.parse_args()
    dates_source = read_source_dates()
    dates = dates_source["dates"]
    secret_setting = get_settings().data_go_kr_service_key
    if secret_setting is None or not secret_setting.get_secret_value().strip():
        print(json.dumps({"status": "credential_unavailable"}, ensure_ascii=False))
        return 2
    secret = secret_setting.get_secret_value()
    secrets = credential_candidates(secret)
    settings = get_settings()
    base_url = settings.kra_api_base_url.rstrip("/")
    timeout = max(float(settings.http_timeout_seconds), 60.0)

    if LEDGER.exists():
        ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        if ledger.get("source_dates_sha256") != hashlib.sha256(
            SOURCE_DATES.read_bytes()
        ).hexdigest():
            raise ValueError("ledger_source_date_set_mismatch")
        if ledger.get("dates_expected") != dates:
            raise ValueError("ledger_date_sequence_mismatch")
        ledger["resume_count"] = int(ledger.get("resume_count") or 0) + 1
        ledger["last_run_started_at_utc"] = utc_now()
        ledger["stop_reason"] = None
    else:
        started = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        ledger = {
            "run_id": started,
            "source": "KRA official OpenAPI JSON; service credential not recorded",
            "credential_recorded": False,
            "endpoint": HORSE_EQUIPMENT_ENDPOINT,
            "operation": HORSE_EQUIPMENT_OPERATION,
            "meet": MEET,
            "date_filter": "rc_date",
            "page_size_requested": PAGE_SIZE,
            "request_interval_seconds_minimum": REQUEST_INTERVAL_SECONDS,
            "date_range": {"from": START_DATE, "through": CUTOFF_DATE},
            "source_dates_file": str(SOURCE_DATES.relative_to(ROOT)),
            "source_dates_sha256": hashlib.sha256(SOURCE_DATES.read_bytes()).hexdigest(),
            "dates_expected": dates,
            "network_request_count": 0,
            "stop_reason": None,
            "dates": {date: {"rc_date": date, "status": "pending", "attempts": []} for date in dates},
        }
        json_atomic_write(LEDGER, ledger)

    mismatch_count, consecutive_mismatch_count = scope_mismatch_counts(dates, ledger["dates"])
    ledger["scope_mismatch_policy"] = {
        "counting_unit": "distinct requested race dates with any rcDate mismatch",
        "stop_threshold": 5,
        "stop_when": "cumulative or consecutive mismatch count reaches threshold",
    }
    ledger["scope_mismatch_count"] = mismatch_count
    ledger["consecutive_scope_mismatch_count"] = consecutive_mismatch_count
    ledger["scope_mismatch_dates"] = [
        date for date in dates if has_row_date_mismatch(ledger["dates"][date])
    ]
    ledger["last_run_skip_validation_failed"] = bool(args.skip_validation_failed)
    json_atomic_write(LEDGER, ledger)

    last_request_started = 0.0
    stop_collection = False
    request_count = int(ledger.get("network_request_count") or 0)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for date_index, rc_date in enumerate(dates, start=1):
            record = ledger["dates"][rc_date]
            if record.get("status") in {"complete", "zero_rows"}:
                continue
            if record.get("status") == "validation_failed":
                if not args.skip_validation_failed:
                    ledger["stop_reason"] = "validation_failed_requires_explicit_skip_option"
                    json_atomic_write(LEDGER, ledger)
                    stop_collection = True
                    break
                skipped_at = utc_now()
                record.setdefault("skip_events", []).append(
                    {
                        "at_utc": skipped_at,
                        "option": "--skip-validation-failed",
                        "status_remains": "validation_failed",
                        "re_requested": False,
                        "counts_as_complete": False,
                    }
                )
                ledger.setdefault("validation_failed_dates_skipped", []).append(rc_date)
                json_atomic_write(LEDGER, ledger)
                print(
                    json.dumps(
                        {
                            "date": rc_date,
                            "status": "validation_failed_skipped_unconfirmed",
                            "date_progress": f"{date_index}/{len(dates)}",
                            "network_request_count": request_count,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                continue

            attempt = {
                "attempt_no": len(record.get("attempts", [])) + 1,
                "status": "running",
                "started_at_utc": utc_now(),
                "pages": [],
            }
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
                total_matching = 0
                date_scope_mismatch = False
                returned_rcdate_counts: Counter[str] = Counter()
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
                    was_archived = target.exists()
                    if was_archived:
                        body_bytes = target.read_bytes()
                        if contains_credential(body_bytes, secrets):
                            raise ValueError("archived_response_contains_credential")
                        fetched_meta = dict(prior or {})
                        fetched_meta["recovered_from_existing_raw"] = prior is None
                    else:
                        delay = REQUEST_INTERVAL_SECONDS - (time.monotonic() - last_request_started)
                        if last_request_started and delay > 0:
                            time.sleep(delay)
                        last_request_started = time.monotonic()
                        request_count += 1
                        ledger["network_request_count"] = request_count
                        requested_at = utc_now()
                        json_atomic_write(LEDGER, ledger)
                        request_params = {**public_params, "serviceKey": secret}
                        try:
                            response = client.get(
                                f"{base_url}{HORSE_EQUIPMENT_ENDPOINT}",
                                params=request_params,
                            )
                        except KeyboardInterrupt:
                            fetched_meta = {
                                "page_no": page_no,
                                "public_params": public_params,
                                "source_url_without_key": public_url(base_url, public_params),
                                "requested_at_utc": requested_at,
                                "exception_type": "KeyboardInterrupt",
                                "status": "request_interrupted",
                            }
                            attempt["pages"].append(fetched_meta)
                            attempt["status"] = "interrupted"
                            attempt["exception_type"] = "KeyboardInterrupt"
                            attempt["finished_at_utc"] = utc_now()
                            record["status"] = "interrupted"
                            record["last_attempt_finished_at_utc"] = attempt["finished_at_utc"]
                            ledger["stop_reason"] = "collector_interrupted"
                            json_atomic_write(LEDGER, ledger)
                            stop_collection = True
                            break
                        except Exception as exc:
                            fetched_meta = {
                                "page_no": page_no,
                                "public_params": public_params,
                                "source_url_without_key": public_url(base_url, public_params),
                                "requested_at_utc": requested_at,
                                "exception_type": safe_exception_type(exc),
                                "status": "request_failed",
                            }
                            attempt["pages"].append(fetched_meta)
                            attempt["status"] = "failed"
                            attempt["exception_type"] = safe_exception_type(exc)
                            record["status"] = "failed"
                            ledger["stop_reason"] = "request_exception"
                            json_atomic_write(LEDGER, ledger)
                            stop_collection = True
                            break

                        retrieved_at = utc_now()
                        if response.status_code != 200:
                            fetched_meta = {
                                "page_no": page_no,
                                "public_params": public_params,
                                "source_url_without_key": public_url(base_url, public_params),
                                "requested_at_utc": requested_at,
                                "retrieved_at_utc": retrieved_at,
                                "http_status_code": response.status_code,
                                "exception_type": "HTTPStatusError",
                                "status": "http_error",
                            }
                            attempt["pages"].append(fetched_meta)
                            attempt["status"] = "failed"
                            attempt["exception_type"] = "HTTPStatusError"
                            record["status"] = "failed"
                            ledger["stop_reason"] = "http_429_rate_limit" if response.status_code == 429 else "http_error"
                            json_atomic_write(LEDGER, ledger)
                            stop_collection = True
                            break

                        body_bytes = response.content
                        if contains_credential(body_bytes, secrets):
                            fetched_meta = {
                                "page_no": page_no,
                                "public_params": public_params,
                                "source_url_without_key": public_url(base_url, public_params),
                                "requested_at_utc": requested_at,
                                "retrieved_at_utc": retrieved_at,
                                "http_status_code": response.status_code,
                                "exception_type": "CredentialEchoRejected",
                                "status": "credential_echo_rejected",
                            }
                            attempt["pages"].append(fetched_meta)
                            attempt["status"] = "failed"
                            attempt["exception_type"] = "CredentialEchoRejected"
                            record["status"] = "failed"
                            ledger["stop_reason"] = "credential_echo_rejected"
                            json_atomic_write(LEDGER, ledger)
                            stop_collection = True
                            break
                        immutable_write(target, body_bytes)
                        fetched_meta = {
                            "page_no": page_no,
                            "public_params": public_params,
                            "source_url_without_key": public_url(base_url, public_params),
                            "requested_at_utc": requested_at,
                            "retrieved_at_utc": retrieved_at,
                            "http_status_code": response.status_code,
                            "content_type": response.headers.get("content-type"),
                            "recovered_from_existing_raw": False,
                        }

                    fetched_meta["response_bytes"] = len(body_bytes)
                    fetched_meta["response_sha256"] = hashlib.sha256(body_bytes).hexdigest()
                    fetched_meta["response_file"] = str(target.relative_to(ROOT))
                    try:
                        header, api_body, rows = parse_response(body_bytes)
                    except Exception as exc:
                        fetched_meta["exception_type"] = safe_exception_type(exc)
                        fetched_meta["status"] = "invalid_json_or_schema"
                        attempt["pages"].append(fetched_meta)
                        attempt["status"] = "failed"
                        attempt["exception_type"] = safe_exception_type(exc)
                        record["status"] = "failed"
                        ledger["stop_reason"] = "invalid_json_or_schema"
                        json_atomic_write(LEDGER, ledger)
                        stop_collection = True
                        break

                    result_code = str(header.get("resultCode") or "")
                    if "totalCount" not in api_body or "numOfRows" not in api_body or "pageNo" not in api_body:
                        fetched_meta["status"] = "pagination_metadata_missing"
                        attempt["pages"].append(fetched_meta)
                        attempt["status"] = "validation_failed"
                        record["status"] = "validation_failed"
                        ledger["stop_reason"] = "pagination_metadata_missing"
                        json_atomic_write(LEDGER, ledger)
                        stop_collection = True
                        break
                    total_count = int(api_body["totalCount"])
                    api_page_size = int(api_body["numOfRows"])
                    api_page_no = int(api_body["pageNo"])
                    matching_rows = sum(str(row.get("rcDate") or "") == rc_date for row in rows)
                    dates_in_page = sorted({str(row.get("rcDate") or "") for row in rows})
                    for row in rows:
                        returned_rcdate_counts[str(row.get("rcDate") or "")] += 1
                    fetched_meta.update(
                        {
                            "api_result_code": result_code,
                            "api_total_count": total_count,
                            "api_page_size": api_page_size,
                            "api_page_no": api_page_no,
                            "actual_page_rows": len(rows),
                            "row_date_field": "rcDate",
                            "records_matching_requested_date": matching_rows,
                            "response_date_examples": dates_in_page[:5],
                            "response_rcdate_value_counts": dict(
                                sorted(Counter(str(row.get("rcDate") or "") for row in rows).items())
                            ),
                            "status": "http_success",
                        }
                    )
                    if result_code not in SUCCESS_CODES:
                        fetched_meta["status"] = "api_error"
                        fetched_meta["api_error_code"] = result_code
                        attempt["pages"].append(fetched_meta)
                        attempt["status"] = "failed"
                        attempt["exception_type"] = "KraApiError"
                        record["status"] = "failed"
                        ledger["stop_reason"] = "api_error"
                        json_atomic_write(LEDGER, ledger)
                        stop_collection = True
                        break

                    if api_page_no != page_no or api_page_size <= 0:
                        fetched_meta["status"] = "pagination_metadata_mismatch"
                        attempt["pages"].append(fetched_meta)
                        attempt["status"] = "validation_failed"
                        record["status"] = "validation_failed"
                        ledger["stop_reason"] = "pagination_metadata_mismatch"
                        json_atomic_write(LEDGER, ledger)
                        stop_collection = True
                        break
                    if expected_total is None:
                        expected_total = total_count
                        expected_page_size = api_page_size
                        expected_pages = max(1, math.ceil(expected_total / expected_page_size))
                    elif total_count != expected_total or api_page_size != expected_page_size:
                        fetched_meta["status"] = "pagination_total_changed"
                        attempt["pages"].append(fetched_meta)
                        attempt["status"] = "validation_failed"
                        record["status"] = "validation_failed"
                        ledger["stop_reason"] = "pagination_total_changed"
                        json_atomic_write(LEDGER, ledger)
                        stop_collection = True
                        break

                    fetched_meta["period_validation"] = (
                        "all_page_rows_exact_date_match" if matching_rows == len(rows) else "row_date_mismatch"
                    )
                    page_metadata.append(fetched_meta)
                    attempt["pages"].append(fetched_meta)
                    total_rows += len(rows)
                    total_matching += matching_rows
                    attempt.update(
                        {
                            "api_total_count": expected_total,
                            "expected_page_count": expected_pages,
                            "actual_page_count_so_far": len(page_metadata),
                            "actual_rows_so_far": total_rows,
                            "matching_date_rows_so_far": total_matching,
                        }
                    )
                    json_atomic_write(LEDGER, ledger)
                    if matching_rows != len(rows):
                        date_scope_mismatch = True
                    page_no += 1

                if stop_collection:
                    break
                assert expected_pages is not None and expected_total is not None
                actual_pages = len(page_metadata)
                pagination_complete = (
                    actual_pages == expected_pages
                    and total_rows == expected_total
                    and all(page["api_total_count"] == expected_total for page in page_metadata)
                    and all(page["api_page_size"] == expected_page_size for page in page_metadata)
                    and all(page["api_page_no"] == page["page_no"] for page in page_metadata)
                )
                date_scope_match = not date_scope_mismatch and total_matching == total_rows
                attempt.update(
                    {
                        "actual_page_count": actual_pages,
                        "actual_total_rows": total_rows,
                        "rows_matching_requested_date": total_matching,
                        "row_date_mismatch_rows": total_rows - total_matching,
                        "returned_rcdate_value_counts": dict(sorted(returned_rcdate_counts.items())),
                        "row_date_field": "rcDate",
                        "requested_rc_date": rc_date,
                        "pagination_validation": "complete" if pagination_complete else "count_or_page_mismatch",
                        "period_validation": "all_rows_match_requested_date" if date_scope_match else "row_date_mismatch",
                        "finished_at_utc": utc_now(),
                    }
                )
                if not pagination_complete:
                    attempt["status"] = "validation_failed"
                    attempt["exception_type"] = "PaginationValidationError"
                    record["status"] = "validation_failed"
                    ledger["stop_reason"] = "pagination_validation_failure"
                    stop_collection = True
                elif not date_scope_match:
                    attempt["status"] = "validation_failed"
                    attempt["exception_type"] = "RowDateMismatch"
                    record["status"] = "validation_failed"
                    mismatch_count += 1
                    consecutive_mismatch_count += 1
                    ledger["scope_mismatch_count"] = mismatch_count
                    ledger["consecutive_scope_mismatch_count"] = consecutive_mismatch_count
                    mismatch_dates = set(ledger.get("scope_mismatch_dates", []))
                    mismatch_dates.add(rc_date)
                    ledger["scope_mismatch_dates"] = sorted(mismatch_dates)
                    attempt["scope_mismatch_count_after_partition"] = mismatch_count
                    attempt["consecutive_scope_mismatch_count_after_partition"] = consecutive_mismatch_count
                    record["last_attempt_finished_at_utc"] = attempt["finished_at_utc"]
                    if mismatch_count >= 5 or consecutive_mismatch_count >= 5:
                        ledger["stop_reason"] = "five_scope_date_mismatches"
                        stop_collection = True
                    else:
                        ledger["stop_reason"] = None
                elif expected_total == 0:
                    attempt["status"] = "zero_rows"
                    record["status"] = "zero_rows"
                    consecutive_mismatch_count = 0
                    ledger["consecutive_scope_mismatch_count"] = 0
                elif pagination_complete and date_scope_match:
                    attempt["status"] = "complete"
                    record["status"] = "complete"
                    consecutive_mismatch_count = 0
                    ledger["consecutive_scope_mismatch_count"] = 0
                else:
                    # This branch is defensive: page count and scope checks
                    # above define the only accepted complete partition.
                    attempt["status"] = "validation_failed"
                    record["status"] = "validation_failed"
                record["last_attempt_finished_at_utc"] = attempt["finished_at_utc"]
                json_atomic_write(LEDGER, ledger)
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
                attempt["exception_type"] = safe_exception_type(exc)
                attempt["finished_at_utc"] = utc_now()
                record["status"] = "failed"
                record["last_attempt_finished_at_utc"] = attempt["finished_at_utc"]
                ledger["stop_reason"] = "collector_exception"
                json_atomic_write(LEDGER, ledger)
                stop_collection = True

            complete_count = sum(row["status"] in {"complete", "zero_rows"} for row in ledger["dates"].values())
            print(
                json.dumps(
                    {
                        "date": rc_date,
                        "status": record["status"],
                        "date_progress": f"{date_index}/{len(dates)}",
                        "completed_requests": complete_count,
                        "network_request_count": request_count,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if stop_collection:
                break

    ledger["network_request_count"] = request_count
    ledger["updated_at_utc"] = utc_now()
    all_dates_examined = all(
        row.get("status") in {"complete", "zero_rows", "validation_failed"}
        for row in ledger["dates"].values()
    )
    if not stop_collection and all_dates_examined:
        has_unconfirmed = any(row.get("status") == "validation_failed" for row in ledger["dates"].values())
        ledger["stop_reason"] = (
            "all_target_dates_examined_with_validation_exclusions"
            if has_unconfirmed
            else "all_target_dates_processed"
        )
    json_atomic_write(LEDGER, ledger)
    status_counts: dict[str, int] = {}
    for row in ledger["dates"].values():
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    print(
        json.dumps(
            {
                "ledger": str(LEDGER),
                "target_dates": len(dates),
                "status_counts": status_counts,
                "network_request_count": request_count,
                "scope_mismatch_count": ledger.get("scope_mismatch_count", 0),
                "scope_mismatch_dates": ledger.get("scope_mismatch_dates", []),
                "stop_reason": ledger.get("stop_reason"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if all_dates_examined else 1


if __name__ == "__main__":
    raise SystemExit(main())
