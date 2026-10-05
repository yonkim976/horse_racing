"""Collect the failed 2015-06 API18_1 month by all 30 exact tr_date partitions.

The failed tr_month calls stay in ledger.json. This fallback is labeled
separately and sums the exact-date totalCount values rather than fabricating a
monthly-endpoint totalCount.
"""

from __future__ import annotations

import calendar
import json
import math
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from horse_racing.collectors.kra_api import (
    DAILY_TRAINING_ENDPOINT,
    DAILY_TRAINING_OPERATION,
    KraApiClient,
    KraApiTransientError,
    response_body,
)
from horse_racing.config import get_settings

from collect_monthly_history import (
    BACKOFF_BASE_SECONDS,
    MAX_TRANSIENT_RETRIES,
    MAX_NEW_REQUESTS_DEFAULT,
    PACE_SECONDS,
    ROOT,
    atomic_immutable_write,
    atomic_json_write,
    contains_secret,
    digest,
    error_metadata,
    response_rows,
    quota_signal,
    write_coverage,
)


LEDGER_PATH = ROOT / "ledger.json"
MONTH = "201506"
PAGE_SIZE = 1000


def persist(ledger: dict[str, Any], run_path: Path, run: dict[str, Any]) -> None:
    ledger["updated_at_utc"] = datetime.now(UTC).isoformat()
    atomic_json_write(LEDGER_PATH, ledger)
    atomic_json_write(run_path, run)


def exact_date_rows(payload: dict[str, Any], requested_date: str) -> tuple[list[dict[str, Any]], list[str]]:
    rows = response_rows(payload)
    dates = [str(row.get("trDate") or "").replace("-", "")[:8] for row in rows]
    errors = []
    if any(value != requested_date for value in dates):
        errors.append("trDate_not_exactly_requested_date")
    return rows, errors


def prior_probe_dates() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted((ROOT / "runs").glob("*_tr_date_probe.json")):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for date_value, record in run.get("dates", {}).items():
            if date_value[:6] == MONTH and record.get("status") in {"validated_exact_date", "empty_or_unverified"}:
                result[date_value] = {
                    "source_probe_run_id": run.get("run_id"),
                    "pages": record.get("pages", []),
                    "api_total_count": record.get("api_total_count"),
                    "expected_page_count": record.get("expected_page_count"),
                    "actual_page_count": record.get("actual_page_count"),
                    "actual_total_rows": record.get("actual_total_rows"),
                    "request_errors": record.get("request_errors", []),
                }
    return result


def validate_saved_date(date_value: str, pages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for expected_page_no, metadata in enumerate(pages, 1):
        path = ROOT / metadata["response_file"]
        raw = path.read_bytes()
        if digest(raw) != metadata["response_sha256"]:
            errors.append("saved_raw_sha256_mismatch")
            continue
        payload = json.loads(raw)
        body = response_body(payload)
        page_rows, row_errors = exact_date_rows(payload, date_value)
        rows.extend(page_rows)
        errors.extend(row_errors)
        if int(body.get("pageNo") or 0) != expected_page_no:
            errors.append("pageNo_mismatch")
        if int(body.get("numOfRows") or 0) != PAGE_SIZE:
            errors.append("numOfRows_mismatch")
        if int(body.get("totalCount") or 0) != int(metadata.get("api_total_count", -1)):
            errors.append("totalCount_mismatch")
        expected_rows = min(PAGE_SIZE, max(0, int(body.get("totalCount") or 0) - (expected_page_no - 1) * PAGE_SIZE))
        if len(page_rows) != expected_rows or len(page_rows) != metadata.get("actual_page_rows"):
            errors.append("page_row_count_mismatch")
    if pages:
        total = int(pages[0].get("api_total_count", -1))
        expected_pages = max(1, math.ceil(total / PAGE_SIZE))
        if len(pages) != expected_pages or len(rows) != total:
            errors.append("partition_count_or_pages_mismatch")
    return rows, sorted(set(errors))


def main() -> int:
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None or not secret.get_secret_value().strip():
        print(json.dumps({"status": "credential_unavailable", "credential_recorded": False}))
        return 2
    service_key = secret.get_secret_value()
    started = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_path = ROOT / "runs" / f"{started}_tr_date_month_fallback.json"
    run: dict[str, Any] = {
        "run_id": started,
        "dataset": "daily_training",
        "month": MONTH,
        "method": "official API18_1 tr_date exact-date partition fallback",
        "source": "KRA official API response pages",
        "credential_recorded": False,
        "page_size": PAGE_SIZE,
        "transient_retry_limit_per_page": MAX_TRANSIENT_RETRIES,
        "transient_backoff_seconds": [1, 2, 4],
        "request_attempts": 0,
        "date_count": calendar.monthrange(int(MONTH[:4]), int(MONTH[4:]))[1],
        "dates": {},
        "quota_or_error": None,
        "status": "running",
    }
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    partition = ledger["partitions"][f"daily_training:{MONTH}"]
    if partition.get("status") not in {"request_failed", "incomplete", "pending", "retrying_transient"}:
        raise RuntimeError(f"monthly partition is already {partition.get('status')}; refusing to replace it")
    ledger.setdefault("date_partition_fallback_runs", []).append({
        "run_id": started,
        "status": "running",
        "manifest": str(run_path.relative_to(ROOT)),
        "dataset": "daily_training",
        "month": MONTH,
        "parameter": "tr_date",
        "page_size": PAGE_SIZE,
    })
    run_ledger_record = ledger["date_partition_fallback_runs"][-1]
    prior = prior_probe_dates()
    month_dates = [f"{MONTH}{day:02d}" for day in range(1, run["date_count"] + 1)]
    kst_date = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    stop_all = False
    aggregate_rows: list[dict[str, Any]] = []
    failed_dates: list[str] = []
    with KraApiClient(
        service_key,
        base_url=settings.kra_api_base_url,
        timeout_seconds=min(settings.http_timeout_seconds, 20.0),
    ) as client:
        for date_value in month_dates:
            day_record: dict[str, Any] = {
                "date": date_value,
                "public_params": {"meet": 2, "tr_date": date_value, "_type": "json"},
                "page_size": PAGE_SIZE,
                "pages": [],
                "request_errors": [],
                "transient_retry_events": [],
                "validation_errors": [],
                "status": "running",
            }
            run["dates"][date_value] = day_record
            persist(ledger, run_path, run)

            cached = prior.get(date_value)
            if cached:
                cached_pages = cached["pages"]
                cached_rows, cached_errors = validate_saved_date(date_value, cached_pages)
                if not cached_errors and len(cached_rows) == int(cached.get("api_total_count") or 0):
                    day_record["pages"] = cached_pages
                    day_record["api_total_count"] = int(cached.get("api_total_count") or 0)
                    day_record["expected_page_count"] = int(cached.get("expected_page_count") or 1)
                    day_record["actual_page_count"] = len(cached_pages)
                    day_record["actual_total_rows"] = len(cached_rows)
                    day_record["source_probe_run_id"] = cached["source_probe_run_id"]
                    day_record["request_errors"] = cached["request_errors"]
                    day_record["validation_errors"] = []
                    day_record["status"] = "complete_exact_date" if cached_rows else "empty_response_exact_date"
                    aggregate_rows.extend(cached_rows)
                    persist(ledger, run_path, run)
                    continue

            total_count: int | None = None
            expected_page_count: int | None = None
            page_no = 1
            while expected_page_count is None or page_no <= expected_page_count:
                retry_count = 0
                while True:
                    attempts_today = int(ledger["request_attempts_by_kst_date"].get(kst_date, 0))
                    if attempts_today >= MAX_NEW_REQUESTS_DEFAULT:
                        day_record["status"] = "request_budget_checkpoint"
                        run["status"] = "request_budget_checkpoint"
                        stop_all = True
                        break
                    params = {"meet": 2, "tr_date": date_value, "_type": "json", "pageNo": page_no, "numOfRows": PAGE_SIZE}
                    run["request_attempts"] += 1
                    ledger["request_attempts_by_this_collector"] = int(ledger.get("request_attempts_by_this_collector", 0)) + 1
                    ledger["request_attempts_by_kst_date"][kst_date] = attempts_today + 1
                    request_started_ms = int(time.time() * 1000)
                    persist(ledger, run_path, run)
                    try:
                        fetched = client._fetch_json.__wrapped__(
                            client,
                            DAILY_TRAINING_ENDPOINT,
                            DAILY_TRAINING_OPERATION,
                            params,
                            service_key_parameter="serviceKey",
                        )
                    except Exception as exc:
                        error = error_metadata(exc, service_key)
                        attempt = {
                            "page_no": page_no,
                            "attempt_number": len([item for item in day_record["request_errors"] if item["page_no"] == page_no]) + 1,
                            "request_started_at_ms": request_started_ms,
                            **error,
                        }
                        day_record["request_errors"].append(attempt)
                        run["quota_or_error"] = error
                        if quota_signal(exc):
                            day_record["status"] = "quota_stopped"
                            run["status"] = "quota_stopped"
                            stop_all = True
                            persist(ledger, run_path, run)
                            break
                        if isinstance(exc, KraApiTransientError) and retry_count < MAX_TRANSIENT_RETRIES:
                            delay = BACKOFF_BASE_SECONDS * (2**retry_count)
                            retry_count += 1
                            day_record["transient_retry_events"].append({
                                "page_no": page_no,
                                "attempt_number": attempt["attempt_number"],
                                "retry_number": retry_count,
                                "backoff_seconds": delay,
                                "classification": error["classification"],
                            })
                            persist(ledger, run_path, run)
                            time.sleep(delay)
                            continue
                        day_record["status"] = "request_failed"
                        failed_dates.append(date_value)
                        persist(ledger, run_path, run)
                        break
                    if contains_secret(fetched.body, service_key):
                        day_record["status"] = "credential_echo_rejected"
                        run["status"] = "credential_echo_rejected"
                        stop_all = True
                        persist(ledger, run_path, run)
                        break
                    body = response_body(fetched.payload)
                    try:
                        page_total = int(body.get("totalCount") or 0)
                        response_page = int(body.get("pageNo")) if body.get("pageNo") is not None else None
                        response_size = int(body.get("numOfRows")) if body.get("numOfRows") is not None else None
                    except (TypeError, ValueError):
                        day_record["validation_errors"].append("invalid_pagination_metadata")
                        day_record["status"] = "validation_mismatch"
                        run["status"] = "validation_mismatch"
                        stop_all = True
                        persist(ledger, run_path, run)
                        break
                    rows, date_errors = exact_date_rows(fetched.payload, date_value)
                    if total_count is None:
                        total_count = page_total
                        expected_page_count = max(1, math.ceil(total_count / PAGE_SIZE))
                    elif page_total != total_count:
                        day_record["validation_errors"].append("totalCount_changed_between_pages")
                    expected_rows = min(PAGE_SIZE, max(0, (total_count or 0) - (page_no - 1) * PAGE_SIZE))
                    if len(rows) != expected_rows:
                        day_record["validation_errors"].append("page_row_count_mismatch")
                    if response_page not in (None, page_no):
                        day_record["validation_errors"].append("pageNo_mismatch")
                    if response_size not in (None, PAGE_SIZE):
                        day_record["validation_errors"].append("numOfRows_mismatch")
                    day_record["validation_errors"].extend(date_errors)
                    if day_record["validation_errors"]:
                        day_record["status"] = "validation_mismatch"
                        run["status"] = "validation_mismatch"
                        stop_all = True
                        persist(ledger, run_path, run)
                        break
                    relative = Path("raw") / "tr_date_fallback" / MONTH / started / date_value / f"page_{page_no:04d}.json"
                    atomic_immutable_write(ROOT / relative, fetched.body)
                    date_strings = [str(row.get("trDate") or "").replace("-", "")[:8] for row in rows]
                    day_record["pages"].append({
                        "page_no": page_no,
                        "status_code": fetched.status_code,
                        "content_type": fetched.content_type,
                        "request_started_at_ms": request_started_ms,
                        "requested_at_ms": fetched.requested_at_ms,
                        "retrieved_at_ms": fetched.retrieved_at_ms,
                        "source_url_without_key": fetched.source_url,
                        "public_params": {"meet": 2, "tr_date": date_value, "_type": "json"},
                        "requested_page_size": PAGE_SIZE,
                        "api_total_count": page_total,
                        "api_page_no": response_page,
                        "api_page_size": response_size,
                        "response_bytes": len(fetched.body),
                        "response_sha256": digest(fetched.body),
                        "response_file": str(relative),
                        "actual_page_rows": len(rows),
                        "row_date_field": "trDate",
                        "row_date_min": min(date_strings) if date_strings else None,
                        "row_date_max": max(date_strings) if date_strings else None,
                        "records_matching_requested_date": len(rows),
                    })
                    aggregate_rows.extend(rows)
                    persist(ledger, run_path, run)
                    break
                if stop_all or day_record["status"] in {"request_failed", "validation_mismatch", "credential_echo_rejected", "quota_stopped"}:
                    break
                if expected_page_count is not None and page_no >= expected_page_count:
                    break
                page_no += 1
                time.sleep(PACE_SECONDS)
            if stop_all:
                break
            if day_record["status"] == "running":
                day_record.update({
                    "api_total_count": total_count,
                    "expected_page_count": expected_page_count,
                    "actual_page_count": len(day_record["pages"]),
                    "actual_total_rows": sum(int(page["actual_page_rows"]) for page in day_record["pages"]),
                    "status": "complete_exact_date" if total_count and total_count > 0 else "empty_response_exact_date",
                })
                if day_record["actual_total_rows"] != int(total_count or 0):
                    day_record["status"] = "incomplete"
                    failed_dates.append(date_value)
                persist(ledger, run_path, run)
            time.sleep(PACE_SECONDS)

    completed = [d for d in month_dates if run["dates"].get(d, {}).get("status") in {"complete_exact_date", "empty_response_exact_date"}]
    status_map = {date_value: record.get("status") for date_value, record in run["dates"].items()}
    exact_unique_dates = sorted({str(row.get("trDate") or "").replace("-", "")[:8] for row in aggregate_rows})
    full_rows = Counter(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for row in aggregate_rows)
    horse_days = Counter((str(row.get("trDate") or "").replace("-", "")[:8], str(row.get("hrNo") or "")) for row in aggregate_rows)
    exact_duplicate_excess = sum(count - 1 for count in full_rows.values() if count > 1)
    horse_day_duplicate_excess = sum(count - 1 for count in horse_days.values() if count > 1)
    date_total_sum = sum(int(record.get("api_total_count", 0)) for record in run["dates"].values() if record.get("status") in {"complete_exact_date", "empty_response_exact_date"})
    page_count = sum(int(record.get("actual_page_count", len(record.get("pages", [])))) for record in run["dates"].values() if record.get("status") in {"complete_exact_date", "empty_response_exact_date"})
    all_days_complete = len(completed) == len(month_dates) and not failed_dates and not stop_all
    fallback = {
        "method": "official API18_1 exact-date tr_date monthly fallback",
        "month": MONTH,
        "date_count": len(month_dates),
        "completed_date_count": len(completed),
        "empty_date_count": sum(status == "empty_response_exact_date" for status in status_map.values()),
        "failed_dates": sorted(set(failed_dates)),
        "date_sequence_complete": all_days_complete,
        "date_range_requested": [month_dates[0], month_dates[-1]],
        "observed_date_range": [min(exact_unique_dates), max(exact_unique_dates)] if exact_unique_dates else [None, None],
        "page_count": page_count,
        "total_count_sum": date_total_sum,
        "actual_total_rows": len(aggregate_rows),
        "all_rows_match_requested_exact_date": all(
            record.get("status") in {"complete_exact_date", "empty_response_exact_date"}
            and not record.get("validation_errors")
            for record in run["dates"].values()
        ) and len(exact_unique_dates) > 0,
        "exact_duplicate_row_excess": exact_duplicate_excess,
        "duplicate_horse_day_excess": horse_day_duplicate_excess,
        "dates": run["dates"],
    }
    run["fallback_summary"] = {key: value for key, value in fallback.items() if key != "dates"}
    if all_days_complete:
        run["status"] = "complete_via_daily_tr_date_partition"
    elif run.get("status") == "running":
        run["status"] = "partial_date_partition_fallback"
    run["finished_at_utc"] = datetime.now(UTC).isoformat()
    run_ledger_record["status"] = run["status"]
    run_ledger_record["request_attempts"] = run["request_attempts"]
    partition["date_fallback"] = fallback
    partition["monthly_api_attempt_status"] = "request_failed_after_eight_read_timeouts"
    partition["coverage_method"] = "tr_date_daily_partition_fallback" if all_days_complete else "tr_date_daily_partition_incomplete"
    partition["api_total_count"] = None
    partition["expected_page_count"] = None
    partition["pages"] = []
    partition["actual_total_rows"] = len(aggregate_rows)
    partition["rows_matching_requested_month"] = sum(str(row.get("trDate") or "").replace("-", "")[:6] == MONTH for row in aggregate_rows)
    row_dates = sorted(str(row.get("trDate") or "").replace("-", "")[:8] for row in aggregate_rows)
    partition["date_min"] = min(row_dates) if row_dates else None
    partition["date_max"] = max(row_dates) if row_dates else None
    partition["date_partition_total_count_sum"] = date_total_sum
    partition["date_partition_page_count"] = page_count
    partition["exact_duplicate_row_excess"] = exact_duplicate_excess
    partition["duplicate_horse_day_excess"] = horse_day_duplicate_excess
    partition["cutoff_exceeding_rows_file"] = None
    partition["cutoff_exceeding_rows_sha256"] = None
    partition["cutoff_exceeding_rows_count"] = 0
    partition["validation_errors"] = [] if all_days_complete and fallback["all_rows_match_requested_exact_date"] else ["daily_date_partition_incomplete_or_invalid"]
    partition["status"] = "complete_positive_coverage_via_daily_tr_date" if all_days_complete and aggregate_rows else "incomplete_daily_tr_date_fallback"
    partition["coverage_positive"] = partition["status"] == "complete_positive_coverage_via_daily_tr_date"
    write_coverage(ledger)
    persist(ledger, run_path, run)
    print(json.dumps({
        "run_id": started,
        "status": run["status"],
        "request_attempts": run["request_attempts"],
        "completed_dates": len(completed),
        "date_count": len(month_dates),
        "total_count_sum": date_total_sum,
        "actual_total_rows": len(aggregate_rows),
        "page_count": page_count,
        "failed_dates": sorted(set(failed_dates)),
        "exact_duplicate_row_excess": exact_duplicate_excess,
        "duplicate_horse_day_excess": horse_day_duplicate_excess,
        "ledger": str(LEDGER_PATH),
        "run_manifest": str(run_path),
        "credential_recorded": False,
    }, ensure_ascii=False))
    return 0 if all_days_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
