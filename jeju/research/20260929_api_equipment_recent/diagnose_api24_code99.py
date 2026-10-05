"""One-retry/one-following-date diagnostic for a generic API24 resultCode 99."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

import collect_api24_history as collector
from horse_racing.collectors.kra_api import HORSE_EQUIPMENT_ENDPOINT
from horse_racing.config import get_settings

PAGE_SIZE = collector.PAGE_SIZE
MEET = collector.MEET
SUCCESS_CODES = collector.SUCCESS_CODES
STOP_CODES = {"20", "21", "22", "23", "29", "30", "31", "32", "33", "97"}


def error_body_shape(body: bytes) -> str:
    try:
        payload = json.loads(body)
        root = payload.get("response", payload) if isinstance(payload, dict) else {}
        return type(root.get("body")).__name__ if isinstance(root, dict) else type(root).__name__
    except Exception:
        return "invalid_json"


def raw_attempt_path(rc_date: str, attempt_no: int, page_no: int) -> Path:
    if attempt_no <= 1:
        return collector.raw_path(rc_date, page_no)
    return collector.RAW_ROOT / rc_date / f"attempt_{attempt_no:04d}" / f"page_{page_no:04d}.json"


def request_partition(
    *,
    client: httpx.Client,
    rc_date: str,
    attempt_no: int,
    request_budget: int,
    secret: str,
    secret_candidates: set[bytes],
    base_url: str,
    last_request_started: list[float],
    ledger: dict[str, Any],
) -> dict[str, Any]:
    """Fetch and validate one date partition; return only sanitized status fields."""
    record = ledger["dates"][rc_date]
    attempt: dict[str, Any] = {
        "attempt_no": attempt_no,
        "status": "running",
        "started_at_utc": collector.utc_now(),
        "diagnostic_attempt": True,
        "pages": [],
    }
    record.setdefault("attempts", []).append(attempt)
    record["status"] = "running"
    record["last_attempt_started_at_utc"] = attempt["started_at_utc"]
    collector.json_atomic_write(collector.LEDGER, ledger)

    page_no = 1
    expected_pages: int | None = None
    expected_total: int | None = None
    expected_page_size: int | None = None
    page_metadata: list[dict[str, Any]] = []
    total_rows = 0
    matched_rows = 0
    returned_dates: Counter[str] = Counter()

    while expected_pages is None or page_no <= expected_pages:
        active_day = collector.kst_date_now()
        used_today = int(ledger.setdefault("network_request_count_by_kst_date", {}).get(active_day, 0))
        if used_today >= request_budget:
            attempt["status"] = "interrupted"
            attempt["exception_type"] = "RequestBudgetCheckpoint"
            attempt["finished_at_utc"] = collector.utc_now()
            record["status"] = "interrupted"
            ledger["stop_reason"] = "per_kst_day_request_budget_checkpoint"
            collector.json_atomic_write(collector.LEDGER, ledger)
            return {"status": "interrupted", "stop_reason": ledger["stop_reason"]}

        delay = collector.REQUEST_INTERVAL_SECONDS - (time.monotonic() - last_request_started[0])
        if last_request_started[0] and delay > 0:
            time.sleep(delay)
        active_day = collector.kst_date_now()
        used_today = int(ledger["network_request_count_by_kst_date"].get(active_day, 0))
        if used_today >= request_budget:
            attempt["status"] = "interrupted"
            attempt["exception_type"] = "RequestBudgetCheckpoint"
            attempt["finished_at_utc"] = collector.utc_now()
            record["status"] = "interrupted"
            ledger["stop_reason"] = "per_kst_day_request_budget_checkpoint"
            collector.json_atomic_write(collector.LEDGER, ledger)
            return {"status": "interrupted", "stop_reason": ledger["stop_reason"]}

        last_request_started[0] = time.monotonic()
        requested_at = collector.utc_now()
        ledger["network_request_count"] = int(ledger.get("network_request_count", 0)) + 1
        ledger["network_request_count_by_kst_date"][active_day] = used_today + 1
        ledger["api_error_diagnostic"] = ledger.get("api_error_diagnostic", {})
        ledger["api_error_diagnostic"]["diagnostic_requests_started"] = int(
            ledger["api_error_diagnostic"].get("diagnostic_requests_started", 0)
        ) + 1
        ledger["last_run_requests_started"] = int(ledger.get("last_run_requests_started", 0)) + 1
        collector.json_atomic_write(collector.LEDGER, ledger)

        public_params: dict[str, str | int] = {
            "meet": MEET,
            "rc_date": rc_date,
            "_type": "json",
            "pageNo": page_no,
            "numOfRows": PAGE_SIZE,
        }
        try:
            response = client.get(
                f"{base_url}{HORSE_EQUIPMENT_ENDPOINT}",
                params={**public_params, "serviceKey": secret},
            )
        except KeyboardInterrupt:
            attempt["status"] = "interrupted"
            attempt["exception_type"] = "KeyboardInterrupt"
            attempt["finished_at_utc"] = collector.utc_now()
            record["status"] = "interrupted"
            ledger["stop_reason"] = "collector_interrupted"
            collector.json_atomic_write(collector.LEDGER, ledger)
            return {"status": "interrupted", "stop_reason": ledger["stop_reason"]}
        except Exception as exc:
            attempt["status"] = "failed"
            attempt["exception_type"] = type(exc).__name__
            attempt["finished_at_utc"] = collector.utc_now()
            record["status"] = "failed"
            ledger["stop_reason"] = "request_exception"
            collector.json_atomic_write(collector.LEDGER, ledger)
            return {"status": "failed", "stop_reason": ledger["stop_reason"]}

        retrieved_at = collector.utc_now()
        target = raw_attempt_path(rc_date, attempt_no, page_no)
        page: dict[str, Any] = {
            "page_no": page_no,
            "public_params": public_params,
            "requested_at_utc": requested_at,
            "retrieved_at_utc": retrieved_at,
            "http_status_code": response.status_code,
        }
        if response.status_code != 200:
            page.update({"status": "http_error", "exception_type": "HTTPStatusError"})
            attempt["pages"].append(page)
            attempt["status"] = "failed"
            attempt["exception_type"] = "HTTPStatusError"
            attempt["finished_at_utc"] = retrieved_at
            record["status"] = "failed"
            ledger["stop_reason"] = "http_429_rate_limit" if response.status_code == 429 else "http_error"
            collector.json_atomic_write(collector.LEDGER, ledger)
            return {"status": "failed", "stop_reason": ledger["stop_reason"]}

        body_bytes = response.content
        if collector.contains_credential(body_bytes, secret_candidates):
            page.update({"status": "credential_echo_rejected", "exception_type": "CredentialEchoRejected"})
            attempt["pages"].append(page)
            attempt["status"] = "failed"
            attempt["exception_type"] = "CredentialEchoRejected"
            attempt["finished_at_utc"] = retrieved_at
            record["status"] = "failed"
            ledger["stop_reason"] = "credential_echo_rejected"
            collector.json_atomic_write(collector.LEDGER, ledger)
            return {"status": "failed", "stop_reason": ledger["stop_reason"]}

        collector.immutable_write(target, body_bytes)
        page.update({
            "content_type": response.headers.get("content-type"),
            "response_bytes": len(body_bytes),
            "response_sha256": hashlib.sha256(body_bytes).hexdigest(),
            "response_file": str(target.relative_to(collector.ROOT)),
        })
        try:
            header, api_body, rows = collector.parse_response(body_bytes)
        except Exception as exc:
            page.update({"status": "invalid_json_or_schema", "exception_type": type(exc).__name__})
            attempt["pages"].append(page)
            attempt["status"] = "failed"
            attempt["exception_type"] = type(exc).__name__
            attempt["finished_at_utc"] = retrieved_at
            record["status"] = "failed"
            ledger["stop_reason"] = "invalid_json_or_schema"
            collector.json_atomic_write(collector.LEDGER, ledger)
            return {"status": "failed", "stop_reason": ledger["stop_reason"]}

        result_code = str(header.get("resultCode") or "")
        if result_code not in SUCCESS_CODES:
            page.update({"status": "api_error", "api_result_code": result_code,
                         "response_body_shape": error_body_shape(body_bytes)})
            attempt["pages"].append(page)
            attempt["status"] = "api_error"
            attempt["exception_type"] = "KraApiError"
            attempt["finished_at_utc"] = retrieved_at
            record["status"] = "api_error"
            record["last_api_error_code"] = result_code
            record["last_attempt_finished_at_utc"] = retrieved_at
            ledger["stop_reason"] = "api_error"
            collector.json_atomic_write(collector.LEDGER, ledger)
            return {"status": "api_error", "api_result_code": result_code}

        if any(k not in api_body for k in ("totalCount", "numOfRows", "pageNo")):
            page["status"] = "pagination_metadata_missing"
            attempt["pages"].append(page)
            attempt["status"] = "failed"
            attempt["exception_type"] = "PaginationMetadataError"
            attempt["finished_at_utc"] = retrieved_at
            record["status"] = "failed"
            ledger["stop_reason"] = "pagination_metadata_missing"
            collector.json_atomic_write(collector.LEDGER, ledger)
            return {"status": "failed", "stop_reason": ledger["stop_reason"]}

        total_count = int(api_body["totalCount"])
        api_page_size = int(api_body["numOfRows"])
        api_page_no = int(api_body["pageNo"])
        if api_page_no != page_no or api_page_size <= 0 or total_count < 0:
            page["status"] = "pagination_metadata_mismatch"
            attempt["pages"].append(page)
            attempt["status"] = "failed"
            attempt["exception_type"] = "PaginationMetadataError"
            attempt["finished_at_utc"] = retrieved_at
            record["status"] = "failed"
            ledger["stop_reason"] = "pagination_metadata_mismatch"
            collector.json_atomic_write(collector.LEDGER, ledger)
            return {"status": "failed", "stop_reason": ledger["stop_reason"]}
        if expected_total is None:
            expected_total = total_count
            expected_page_size = api_page_size
            expected_pages = max(1, math.ceil(expected_total / expected_page_size))
            if expected_pages > collector.MAX_PAGE_COUNT_PER_DATE:
                page["status"] = "page_count_safety_limit"
                attempt["pages"].append(page)
                attempt["status"] = "failed"
                attempt["exception_type"] = "PaginationSafetyLimit"
                attempt["finished_at_utc"] = retrieved_at
                record["status"] = "failed"
                ledger["stop_reason"] = "page_count_safety_limit"
                collector.json_atomic_write(collector.LEDGER, ledger)
                return {"status": "failed", "stop_reason": ledger["stop_reason"]}
        elif total_count != expected_total or api_page_size != expected_page_size:
            page["status"] = "pagination_total_changed"
            attempt["pages"].append(page)
            attempt["status"] = "failed"
            attempt["exception_type"] = "PaginationMetadataError"
            attempt["finished_at_utc"] = retrieved_at
            record["status"] = "failed"
            ledger["stop_reason"] = "pagination_total_changed"
            collector.json_atomic_write(collector.LEDGER, ledger)
            return {"status": "failed", "stop_reason": ledger["stop_reason"]}

        matches = sum(str(row.get("rcDate") or "") == rc_date for row in rows)
        date_counts = Counter(str(row.get("rcDate") or "") for row in rows)
        returned_dates.update(date_counts)
        page.update({"api_result_code": result_code, "api_total_count": total_count,
                     "api_page_size": api_page_size, "api_page_no": api_page_no,
                     "actual_page_rows": len(rows), "row_date_field": "rcDate",
                     "records_matching_requested_date": matches,
                     "response_rcdate_value_counts": dict(sorted(date_counts.items())),
                     "period_validation": "all_page_rows_exact_date_match" if matches == len(rows) else "row_date_mismatch",
                     "status": "http_success"})
        page_metadata.append(page)
        attempt["pages"].append(page)
        total_rows += len(rows)
        matched_rows += matches
        attempt.update({"api_total_count": expected_total, "expected_page_count": expected_pages,
                        "actual_page_count_so_far": len(page_metadata), "actual_rows_so_far": total_rows,
                        "matching_date_rows_so_far": matched_rows})
        collector.json_atomic_write(collector.LEDGER, ledger)
        page_no += 1

    pagination_complete = (
        expected_pages is not None and len(page_metadata) == expected_pages
        and total_rows == expected_total
        and all(p["api_total_count"] == expected_total for p in page_metadata)
        and all(p["api_page_size"] == expected_page_size for p in page_metadata)
        and all(p["api_page_no"] == p["page_no"] for p in page_metadata)
    )
    exact_date = matched_rows == total_rows
    attempt.update({"actual_page_count": len(page_metadata), "actual_total_rows": total_rows,
                    "rows_matching_requested_date": matched_rows,
                    "row_date_mismatch_rows": total_rows - matched_rows,
                    "returned_rcdate_value_counts": dict(sorted(returned_dates.items())),
                    "requested_rc_date": rc_date, "row_date_field": "rcDate",
                    "pagination_validation": "complete" if pagination_complete else "count_or_page_mismatch",
                    "period_validation": "all_rows_match_requested_date" if exact_date else "row_date_mismatch",
                    "finished_at_utc": collector.utc_now()})
    record["last_attempt_finished_at_utc"] = attempt["finished_at_utc"]
    if not pagination_complete:
        attempt["status"] = "failed"
        attempt["exception_type"] = "PaginationValidationError"
        record["status"] = "failed"
        ledger["stop_reason"] = "pagination_validation_failure"
        result = {"status": "failed", "stop_reason": ledger["stop_reason"]}
    elif not exact_date:
        attempt["status"] = "validation_failed"
        attempt["exception_type"] = "RowDateMismatch"
        record["status"] = "validation_failed"
        result = {"status": "validation_failed"}
    elif expected_total == 0:
        attempt["status"] = "zero_rows"
        record["status"] = "zero_rows"
        result = {"status": "zero_rows"}
    else:
        attempt["status"] = "complete"
        record["status"] = "complete"
        result = {"status": "complete"}
    attempt["exception_type"] = attempt.get("exception_type")
    collector.refresh_coverage(ledger, ledger["dates_expected"])
    collector.json_atomic_write(collector.LEDGER, ledger)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Retry a generic API24 resultCode 99 once, then probe the next official race date once only if 99 repeats.")
    parser.add_argument("--date", required=True, help="The already quarantined API24 date whose resultCode 99 may be retried once.")
    parser.add_argument("--request-budget", type=int, required=True,
                        help="Maximum API24 request starts this collector may use on the current KST date.")
    args = parser.parse_args()
    source = collector.verify_source_dates()
    dates = source["dates"]
    if args.date not in dates:
        parser.error("--date is not in the frozen historical source date set")
    if not collector.LEDGER.exists():
        parser.error("history ledger does not exist")
    ledger = json.loads(collector.LEDGER.read_text(encoding="utf-8"))
    if ledger.get("dates_expected") != dates:
        raise ValueError("ledger_date_set_mismatch")
    record = ledger["dates"][args.date]
    last_codes = [
        str(page.get("api_result_code"))
        for attempt in record.get("attempts", [])
        for page in attempt.get("pages", [])
        if page.get("api_result_code") is not None
    ]
    if record.get("status") != "api_error" or not last_codes or last_codes[-1] != "99":
        parser.error("target date is not currently quarantined with resultCode 99")
    if int(record.get("api_error_retry_attempts") or 0) >= 1:
        parser.error("the single same-date retry was already used")
    if args.request_budget < 0:
        parser.error("--request-budget must be non-negative")

    date_index = dates.index(args.date)
    next_date = dates[date_index + 1] if date_index + 1 < len(dates) else None
    if next_date is None:
        parser.error("no subsequent source race date is available for the diagnostic probe")
    ledger["last_run_started_at_utc"] = collector.utc_now()
    ledger["last_run_kst_date"] = collector.kst_date_now()
    ledger["last_run_request_budget_kst"] = args.request_budget
    ledger["last_run_requests_started"] = 0
    ledger["api_error_diagnostic"] = {
        "initial_date": args.date,
        "initial_result_code": "99",
        "official_code_meaning": "UNKNOWN_ERROR / 기타에러; no specific cause implied",
        "official_code_reference": "https://www.data.go.kr/en/data/15021104/standard.do",
        "quota_code_22_no_retry": True,
        "permission_and_key_errors_no_retry": ["20", "21", "29", "30", "31", "32", "33", "97"],
        "same_date_retry_limit": 1,
        "following_date_probe_limit": 1,
        "following_date": next_date,
        "status": "same_date_retry_pending",
        "diagnostic_requests_started": 0,
    }
    record["api_error_retry_attempts"] = 1
    ledger["stop_reason"] = None
    collector.json_atomic_write(collector.LEDGER, ledger)

    settings = get_settings()
    secret_setting = settings.data_go_kr_service_key
    if secret_setting is None or not secret_setting.get_secret_value().strip():
        ledger["stop_reason"] = "credential_unavailable"
        ledger["api_error_diagnostic"]["status"] = "credential_unavailable"
        collector.json_atomic_write(collector.LEDGER, ledger)
        print(json.dumps({"status": "credential_unavailable"}, ensure_ascii=False))
        return 2
    secret = secret_setting.get_secret_value()
    timeout = max(float(settings.http_timeout_seconds), 60.0)
    last_request_started = [0.0]
    api_error_date = args.date
    result: dict[str, Any]
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        result = request_partition(
            client=client, rc_date=api_error_date, attempt_no=len(record.get("attempts", [])) + 1,
            request_budget=args.request_budget, secret=secret,
            secret_candidates=collector.credential_candidates(secret),
            base_url=settings.kra_api_base_url.rstrip("/"), last_request_started=last_request_started,
            ledger=ledger,
        )
        code = str(result.get("api_result_code") or "")
        if result.get("status") in {"failed", "interrupted", "validation_failed"}:
            ledger["api_error_diagnostic"].update({"status": "stopped_after_same_date_retry", "retry_result": result})
            ledger["stop_reason"] = result.get("stop_reason") or "same_date_retry_not_validated"
        elif result.get("status") == "api_error" and code in STOP_CODES:
            ledger["api_error_diagnostic"].update({"status": "stopped_immediate_quota_or_permission_signal",
                                                    "retry_result_code": code})
            ledger["stop_reason"] = "api_quota_or_permission_error"
        elif result.get("status") == "api_error" and code != "99":
            ledger["api_error_diagnostic"].update({"status": "stopped_after_non99_retry_error",
                                                    "retry_result_code": code})
            ledger["stop_reason"] = "api_error_on_same_date_retry"
        elif result.get("status") in {"complete", "zero_rows"}:
            ledger["api_error_diagnostic"].update({"status": "same_date_retry_recovered",
                                                    "retry_status": result.get("status"),
                                                    "next_date_probe": "not_needed"})
            ledger["stop_reason"] = "api_error_retry_recovered_checkpoint"
        elif result.get("status") == "api_error" and code == "99":
            record["api_error_repeated_code_99"] = True
            ledger["api_error_diagnostic"].update({"status": "same_date_retry_repeated_code_99",
                                                    "retry_result_code": "99",
                                                    "next_date_probe_status": "pending"})
            collector.json_atomic_write(collector.LEDGER, ledger)
            next_record = ledger["dates"][next_date]
            if next_record.get("status") != "pending" or next_record.get("attempts"):
                ledger["api_error_diagnostic"]["status"] = "stopped_next_date_not_pending"
                ledger["stop_reason"] = "next_probe_date_not_pending"
                collector.json_atomic_write(collector.LEDGER, ledger)
            else:
                result = request_partition(
                    client=client, rc_date=next_date, attempt_no=1,
                    request_budget=args.request_budget, secret=secret,
                    secret_candidates=collector.credential_candidates(secret),
                    base_url=settings.kra_api_base_url.rstrip("/"), last_request_started=last_request_started,
                    ledger=ledger,
                )
                code = str(result.get("api_result_code") or "")
                if result.get("status") == "api_error" and code == "99":
                    ledger["api_error_diagnostic"].update({"status": "stopped_following_date_also_code_99",
                                                            "following_date_result_code": "99"})
                    ledger["stop_reason"] = "following_date_probe_result_code_99"
                elif result.get("status") in {"complete", "zero_rows"}:
                    record["api_error_recovery_probe_date"] = next_date
                    record["api_error_recovery_probe_status"] = "normal_exact_date"
                    ledger["api_error_diagnostic"].update({"status": "following_date_probe_passed",
                                                            "following_date_result": result.get("status"),
                                                            "failed_date_remains_excluded": True})
                    ledger["stop_reason"] = "api_error_date_isolated_following_date_probe_passed"
                else:
                    ledger["api_error_diagnostic"].update({"status": "stopped_following_date_probe_not_normal",
                                                            "following_date_result": result})
                    ledger["stop_reason"] = result.get("stop_reason") or "following_date_probe_not_normal"

    ledger["network_request_count"] = int(ledger.get("network_request_count") or 0)
    ledger["last_run_finished_at_utc"] = collector.utc_now()
    ledger["updated_at_utc"] = collector.utc_now()
    ledger["last_run_requests_started"] = int(ledger.get("api_error_diagnostic", {}).get("diagnostic_requests_started", 0))
    collector.refresh_coverage(ledger, dates)
    collector.json_atomic_write(collector.LEDGER, ledger)
    print(json.dumps({"diagnostic_status": ledger["api_error_diagnostic"]["status"],
                      "diagnostic_requests_started": ledger["api_error_diagnostic"].get("diagnostic_requests_started"),
                      "network_request_count": ledger.get("network_request_count"),
                      "today_kst_request_count": ledger.get("network_request_count_by_kst_date", {}).get(collector.kst_date_now()),
                      "initial_date": args.date, "following_date": next_date,
                      "same_date_status": ledger["dates"][args.date].get("status"),
                      "following_date_status": ledger["dates"][next_date].get("status"),
                      "stop_reason": ledger.get("stop_reason")}, ensure_ascii=False))
    return 0 if ledger["api_error_diagnostic"]["status"] in {"same_date_retry_recovered", "following_date_probe_passed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
