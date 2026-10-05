"""Collect complete monthly API18_1/API25_1 response histories for Jeju."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus
from zoneinfo import ZoneInfo

from horse_racing.collectors.kra_api import (
    DAILY_TRAINING_ENDPOINT,
    DAILY_TRAINING_OPERATION,
    ENTRY_HORSE_WEIGHT_ENDPOINT,
    ENTRY_HORSE_WEIGHT_OPERATION,
    KraApiClient,
    KraApiError,
    KraApiRateLimitError,
    KraApiTransientError,
    response_body,
)
from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parent
LEDGER_PATH = ROOT / "ledger.json"
PAGE_SIZE = 1000
FIRST_MONTH = "200201"
LAST_MONTH = "202609"
CUTOFF_DATE = "20260919"
MAX_NEW_REQUESTS_DEFAULT = 1800
MAX_TRANSIENT_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0
PACE_SECONDS = 0.35

DATASETS: dict[str, dict[str, str]] = {
    "daily_training": {
        "endpoint": DAILY_TRAINING_ENDPOINT,
        "operation": DAILY_TRAINING_OPERATION,
        "month_param": "tr_month",
        "date_field": "trDate",
        "key_parameter": "serviceKey",
    },
    "entry_weight": {
        "endpoint": ENTRY_HORSE_WEIGHT_ENDPOINT,
        "operation": ENTRY_HORSE_WEIGHT_OPERATION,
        "month_param": "rc_month",
        "date_field": "rcDate",
        "key_parameter": "serviceKey",
    },
}


class RequestBudgetReached(RuntimeError):
    pass


def month_range(first: str = FIRST_MONTH, last: str = LAST_MONTH) -> list[str]:
    year, month = int(first[:4]), int(first[4:])
    last_year, last_month = int(last[:4]), int(last[4:])
    result: list[str] = []
    while (year, month) <= (last_year, last_month):
        result.append(f"{year:04d}{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return result


def response_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = response_body(payload).get("items") or {}
    values = items.get("item") if isinstance(items, dict) else None
    if values is None:
        return []
    if isinstance(values, dict):
        return [values]
    if isinstance(values, list):
        return [value for value in values if isinstance(value, dict)]
    return []


def normalized_date(value: Any) -> str:
    return str(value or "").replace("-", "").replace("/", "")[:8]


def date_values(rows: list[dict[str, Any]], field: str) -> list[str]:
    return sorted({str(row.get(field)) for row in rows if row.get(field) is not None})


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_immutable_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        try:
            os.link(tmp, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise RuntimeError("immutable output path already exists with different content")
    finally:
        tmp.unlink(missing_ok=True)


def contains_secret(data: bytes, secret: str) -> bool:
    variants = (
        secret.encode("utf-8"),
        quote(secret, safe="").encode("utf-8"),
        quote_plus(secret, safe="").encode("utf-8"),
    )
    return any(variant and variant in data for variant in variants)


def empty_ledger() -> dict[str, Any]:
    partitions: dict[str, dict[str, Any]] = {}
    for dataset in DATASETS:
        for month in month_range():
            partitions[f"{dataset}:{month}"] = {
                "dataset": dataset,
                "month": month,
                "status": "pending",
                "pages": [],
            }
    return {
        "schema_version": 1,
        "source": "KRA official public API JSON response pages; meet=2",
        "credential_recorded": False,
        "page_size": PAGE_SIZE,
        "requested_months": {"first": FIRST_MONTH, "last": LAST_MONTH},
        "cutoff_date_exclusive": CUTOFF_DATE,
        "shared_daily_quota": 3000,
        "default_page_size_by_dataset": {name: PAGE_SIZE for name in DATASETS},
        "request_attempts_by_this_collector": 0,
        "request_attempts_by_kst_date": {},
        "partitions": partitions,
        "runs": [],
    }


def load_ledger() -> dict[str, Any]:
    if not LEDGER_PATH.exists():
        return empty_ledger()
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    for key, initial in empty_ledger()["partitions"].items():
        ledger["partitions"].setdefault(key, initial)
    ledger.setdefault("default_page_size_by_dataset", {name: PAGE_SIZE for name in DATASETS})
    for name in DATASETS:
        ledger["default_page_size_by_dataset"].setdefault(name, PAGE_SIZE)
    for partition in ledger["partitions"].values():
        if partition.get("pages") and not partition.get("page_size"):
            partition["page_size"] = int(partition["pages"][0].get("api_page_size") or PAGE_SIZE)
    return ledger


def persist(ledger: dict[str, Any], run_path: Path, run: dict[str, Any]) -> None:
    ledger["updated_at_utc"] = datetime.now(UTC).isoformat()
    atomic_json_write(LEDGER_PATH, ledger)
    atomic_json_write(run_path, run)


def quota_signal(exc: BaseException) -> bool:
    if isinstance(exc, KraApiRateLimitError):
        return True
    message = str(exc).lower()
    signals = ("quota", "rate limit", "일일", "초과", "사용량", "호출 제한", "요청 횟수")
    return any(value in message for value in signals)


def error_metadata(exc: BaseException, secret: str) -> dict[str, str]:
    # Never persist exception text, which may contain a request URL.
    chain: list[BaseException] = []
    cause = exc.__cause__
    while cause is not None and len(chain) < 4:
        chain.append(cause)
        cause = cause.__cause__
    text = str(exc)
    status = re.search(r"HTTP\s+(\d{3})", text, flags=re.IGNORECASE)
    if any("connect" in type(item).__name__.lower() for item in chain):
        classification = "network_connect_error"
    elif any("timeout" in type(item).__name__.lower() for item in chain):
        classification = "network_timeout"
    elif status:
        classification = f"http_{status.group(1)}"
    else:
        classification = "api_or_transport_error"
    return {
        "type": type(exc).__name__,
        "cause_type": type(chain[0]).__name__ if chain else "none",
        "classification": classification,
        "quota_signal": "true" if quota_signal(exc) else "false",
        "credential_echo_in_exception": "true" if contains_secret(text.encode(), secret) else "false",
    }


def load_saved_pages(partition: dict[str, Any]) -> list[tuple[dict[str, Any], bytes, dict[str, Any]]]:
    result = []
    for metadata in partition.get("pages", []):
        path = ROOT / metadata["response_file"]
        body = path.read_bytes()
        if digest(body) != metadata["response_sha256"]:
            raise RuntimeError(f"saved raw SHA mismatch for {partition['dataset']}:{partition['month']}")
        payload = json.loads(body)
        result.append((metadata, body, payload))
    return result


def partition_stats(
    partition: dict[str, Any],
    dataset_spec: dict[str, str],
) -> dict[str, Any]:
    all_rows: list[dict[str, Any]] = []
    all_dates: list[str] = []
    page_row_counts: list[int] = []
    for metadata, _body, payload in load_saved_pages(partition):
        rows = response_rows(payload)
        all_rows.extend(rows)
        page_row_counts.append(len(rows))
        all_dates.extend(date_values(rows, dataset_spec["date_field"]))
    month = partition["month"]
    matching_rows = sum(normalized_date(row.get(dataset_spec["date_field"])).startswith(month) for row in all_rows)
    cutoff_rows = [
        row for row in all_rows
        if normalized_date(row.get(dataset_spec["date_field"])) > CUTOFF_DATE
        and normalized_date(row.get(dataset_spec["date_field"]))[:8].isdigit()
    ]
    return {
        "actual_total_rows": len(all_rows),
        "rows_matching_requested_month": matching_rows,
        "date_min": min(all_dates) if all_dates else None,
        "date_max": max(all_dates) if all_dates else None,
        "page_actual_row_counts": page_row_counts,
        "cutoff_exceeding_rows": cutoff_rows,
    }


def write_cutoff_rows(partition: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    if not rows:
        partition["cutoff_exceeding_rows_file"] = None
        partition["cutoff_exceeding_rows_sha256"] = None
        partition["cutoff_exceeding_rows_count"] = 0
        return
    data = (json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    sha = digest(data)
    relative = Path("cutoff_exceeding") / partition["dataset"] / partition["month"] / f"rows_{sha}.json"
    atomic_immutable_write(ROOT / relative, data)
    partition["cutoff_exceeding_rows_file"] = str(relative)
    partition["cutoff_exceeding_rows_sha256"] = sha
    partition["cutoff_exceeding_rows_count"] = len(rows)


def set_partition_status(partition: dict[str, Any], dataset_spec: dict[str, str]) -> None:
    pages = partition.get("pages", [])
    if not pages:
        return
    stats = partition_stats(partition, dataset_spec)
    expected_total = partition.get("api_total_count")
    expected_pages = partition.get("expected_page_count")
    partition_page_size = int(partition.get("page_size") or PAGE_SIZE)
    page_nos = [item.get("page_no") for item in pages]
    page_numbers_contiguous = page_nos == list(range(1, len(page_nos) + 1))
    validation_errors: list[str] = []
    for meta in pages:
        page_no = int(meta.get("page_no") or 0)
        expected_page_rows = min(partition_page_size, max(0, int(expected_total or 0) - (page_no - 1) * partition_page_size))
        if meta.get("actual_page_rows") != expected_page_rows:
            validation_errors.append("page_row_count_mismatch")
        if meta.get("records_matching_requested_month") != meta.get("actual_page_rows"):
            validation_errors.append("row_date_outside_requested_month_or_missing")
        if meta.get("api_total_count") != expected_total:
            validation_errors.append("totalCount_changed_between_pages")
        if meta.get("api_page_no") not in (None, meta.get("page_no")):
            validation_errors.append("pageNo_mismatch")
        if meta.get("api_page_size") not in (None, partition_page_size):
            validation_errors.append("numOfRows_mismatch")
    if stats["rows_matching_requested_month"] != stats["actual_total_rows"]:
        validation_errors.append("row_date_outside_requested_month_or_missing")
    if expected_total is not None:
        if stats["actual_total_rows"] > expected_total:
            validation_errors.append("actual_rows_exceed_totalCount")
        if len(pages) == expected_pages and stats["actual_total_rows"] != expected_total:
            validation_errors.append("actual_rows_do_not_match_totalCount")
    partition.update({key: value for key, value in stats.items() if key != "cutoff_exceeding_rows"})
    write_cutoff_rows(partition, stats["cutoff_exceeding_rows"])
    partition["validation_errors"] = sorted(set(validation_errors))
    if expected_total == 0 and len(pages) == 1 and stats["actual_total_rows"] == 0:
        partition["status"] = "empty_response"
        partition["coverage_positive"] = False
    elif (
        expected_total is not None
        and expected_total > 0
        and expected_pages is not None
        and len(pages) == expected_pages
        and page_numbers_contiguous
        and stats["actual_total_rows"] == expected_total
        and not validation_errors
    ):
        partition["status"] = "complete_positive_coverage"
        partition["coverage_positive"] = True
    elif validation_errors:
        partition["status"] = "validation_mismatch"
        partition["coverage_positive"] = False
    else:
        partition["status"] = "incomplete"
        partition["coverage_positive"] = False


def coverage_summaries(ledger: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    months: list[dict[str, Any]] = []
    annual: dict[str, dict[str, dict[str, Any]]] = {
        dataset: defaultdict(lambda: {
            "partition_count": 0,
            "positive_coverage_months": 0,
            "empty_response_months": 0,
            "incomplete_months": 0,
            "api_total_count_sum_for_positive_partitions": 0,
            "date_partition_fallback_months": 0,
            "date_partition_total_count_sum": 0,
            "covered_rows_including_date_fallback": 0,
            "cutoff_exceeding_rows": 0,
        })
        for dataset in DATASETS
    }
    by_dataset: dict[str, Any] = {}
    for dataset in DATASETS:
        records = [
            entry for entry in ledger["partitions"].values()
            if entry["dataset"] == dataset
        ]
        for entry in records:
            year = entry["month"][:4]
            item = annual[dataset][year]
            item["partition_count"] += 1
            item["cutoff_exceeding_rows"] += int(entry.get("cutoff_exceeding_rows_count", 0))
            if entry.get("status") == "complete_positive_coverage":
                item["positive_coverage_months"] += 1
                item["api_total_count_sum_for_positive_partitions"] += int(entry.get("api_total_count", 0))
                item["covered_rows_including_date_fallback"] += int(entry.get("api_total_count", 0))
            elif entry.get("status") == "complete_positive_coverage_via_daily_tr_date":
                item["positive_coverage_months"] += 1
                item["date_partition_fallback_months"] = item.get("date_partition_fallback_months", 0) + 1
                item["date_partition_total_count_sum"] = item.get("date_partition_total_count_sum", 0) + int(entry.get("date_partition_total_count_sum", 0))
                item["covered_rows_including_date_fallback"] += int(entry.get("actual_total_rows", 0))
            elif entry.get("status") == "empty_response":
                item["empty_response_months"] += 1
            else:
                item["incomplete_months"] += 1
            months.append({
                "dataset": dataset,
                "month": entry["month"],
                "status": entry.get("status", "pending"),
                "coverage_positive": bool(entry.get("coverage_positive", False)),
                "api_total_count": entry.get("api_total_count"),
                "actual_total_rows": entry.get("actual_total_rows"),
                "actual_page_count": len(entry.get("pages", [])),
                "expected_page_count": entry.get("expected_page_count"),
                "requested_page_size": entry.get("page_size", PAGE_SIZE),
                "date_min": entry.get("date_min"),
                "date_max": entry.get("date_max"),
                "cutoff_exceeding_rows_count": entry.get("cutoff_exceeding_rows_count", 0),
                "coverage_method": entry.get("coverage_method", "monthly_partition"),
                "date_partition_count": entry.get("date_fallback", {}).get("date_count"),
                "date_partition_page_count": entry.get("date_fallback", {}).get("page_count"),
                "date_partition_total_count_sum": entry.get("date_partition_total_count_sum"),
            })
        by_dataset[dataset] = {
            "partition_count": len(records),
            "positive_coverage_months": sum(r.get("status") in {"complete_positive_coverage", "complete_positive_coverage_via_daily_tr_date"} for r in records),
            "monthly_filter_positive_coverage_months": sum(r.get("status") == "complete_positive_coverage" for r in records),
            "date_partition_fallback_months": sum(r.get("status") == "complete_positive_coverage_via_daily_tr_date" for r in records),
            "empty_response_months": sum(r.get("status") == "empty_response" for r in records),
            "incomplete_or_pending_months": sum(r.get("status") not in {"complete_positive_coverage", "complete_positive_coverage_via_daily_tr_date", "empty_response"} for r in records),
            "monthly_filter_positive_coverage_rows": sum(int(r.get("api_total_count", 0)) for r in records if r.get("status") == "complete_positive_coverage"),
            "date_partition_fallback_rows": sum(int(r.get("actual_total_rows", 0)) for r in records if r.get("status") == "complete_positive_coverage_via_daily_tr_date"),
            "date_partition_total_count_sum": sum(int(r.get("date_partition_total_count_sum", 0)) for r in records if r.get("status") == "complete_positive_coverage_via_daily_tr_date"),
            "positive_coverage_rows": sum(int(r.get("api_total_count", 0)) for r in records if r.get("status") == "complete_positive_coverage") + sum(int(r.get("actual_total_rows", 0)) for r in records if r.get("status") == "complete_positive_coverage_via_daily_tr_date"),
            "official_raw_page_count": sum(len(r.get("pages", [])) for r in records) + sum(int(r.get("date_fallback", {}).get("page_count", 0)) for r in records),
            "cutoff_exceeding_rows": sum(int(r.get("cutoff_exceeding_rows_count", 0)) for r in records),
        }
    total_partitions = sum(item["partition_count"] for item in by_dataset.values())
    positive_partitions = sum(item["positive_coverage_months"] for item in by_dataset.values())
    empty_partitions = sum(item["empty_response_months"] for item in by_dataset.values())
    incomplete_partitions = sum(item["incomplete_or_pending_months"] for item in by_dataset.values())
    quota_signal_count = sum(
        error.get("quota_signal") == "true"
        for partition in ledger["partitions"].values()
        for error in partition.get("request_errors", [])
    )
    return {
        "source": "Derived from the monthly ledger, including verified prior official API archive links and the exact-date tr_date fallback; empty responses are not positive coverage.",
        "collection_status": {
            "status": ledger.get("overall_collection_status", {}).get("status", "api_first_month_range_complete_with_provenance_recovery" if total_partitions == 594 and incomplete_partitions == 0 else "partial_or_incomplete"),
            "initial_full_month_pass_status": ledger.get("overall_collection_status", {}).get("initial_full_month_pass_status", "complete_with_partition_failures"),
            "final_status_note": ledger.get("overall_collection_status", {}).get("final_status_note"),
            "requested_month_partitions": total_partitions,
            "positive_coverage_partitions": positive_partitions,
            "empty_response_partitions": empty_partitions,
            "incomplete_or_pending_partitions": incomplete_partitions,
            "request_attempts_by_this_collector": ledger.get("request_attempts_by_this_collector", 0),
            "quota_signal_count_in_month_partition_attempts": quota_signal_count,
            "shared_daily_quota": 3000,
            "shared_request_total_known": False,
            "official_raw_page_count": sum(item["official_raw_page_count"] for item in by_dataset.values()),
            "official_raw_row_count": sum(item["positive_coverage_rows"] for item in by_dataset.values()),
            "resolutions": {
                "daily_training:201506": "monthly tr_month failed after eight ReadTimeout attempts; 30 exact tr_date daily partitions completed, monthly totalCount unavailable",
                "daily_training:202609": "four monthly ReadTimeout attempts preserved; complete official six-page prior archive linked",
                "entry_weight:202609": "four monthly ReadTimeout attempts preserved; complete official one-page prior archive linked",
            },
        },
        "annual_coverage_by_dataset": {
            dataset: {year: values for year, values in sorted(annual[dataset].items())}
            for dataset in DATASETS
        },
        "dataset_totals": by_dataset,
        "request_attempts_by_this_collector": ledger.get("request_attempts_by_this_collector", 0),
        "shared_daily_quota": 3000,
        "shared_request_total_unknown": True,
    }, sorted(months, key=lambda row: (row["dataset"], row["month"]))


def write_coverage(ledger: dict[str, Any]) -> None:
    summary, months = coverage_summaries(ledger)
    atomic_json_write(ROOT / "coverage_summary.json", summary)
    lines = ["dataset,month,status,coverage_positive,api_total_count,actual_total_rows,actual_page_count,expected_page_count,requested_page_size,date_min,date_max,cutoff_exceeding_rows_count,coverage_method,date_partition_count,date_partition_page_count,date_partition_total_count_sum"]
    for row in months:
        values = [
            row["dataset"], row["month"], row["status"], str(row["coverage_positive"]).lower(),
            row["api_total_count"] if row["api_total_count"] is not None else "",
            row["actual_total_rows"] if row["actual_total_rows"] is not None else "",
            row["actual_page_count"], row["expected_page_count"] if row["expected_page_count"] is not None else "",
            row["requested_page_size"], row["date_min"] or "", row["date_max"] or "", row["cutoff_exceeding_rows_count"],
            row["coverage_method"],
            row["date_partition_count"] if row["date_partition_count"] is not None else "",
            row["date_partition_page_count"] if row["date_partition_page_count"] is not None else "",
            row["date_partition_total_count_sum"] if row["date_partition_total_count_sum"] is not None else "",
        ]
        lines.append(",".join(str(value) for value in values))
    (ROOT / "monthly_coverage.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def collect(
    max_new_requests: int,
    max_partitions: int,
    retry_empty: bool = False,
    stop_after_first_training_positive: bool = False,
) -> int:
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None or not secret.get_secret_value().strip():
        print(json.dumps({"status": "credential_unavailable", "credential_recorded": False}))
        return 2
    service_key = secret.get_secret_value()
    ledger = load_ledger()
    started = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = ROOT / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_path = run_dir / f"{started}.json"
    kst_date = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    run: dict[str, Any] = {
        "run_id": started,
        "kst_date": kst_date,
        "status": "running",
        "credential_recorded": False,
        "source": "KRA official API response pages",
        "request_attempts": 0,
        "request_attempt_limit_this_run": max_new_requests,
        "max_new_partitions_this_run": max_partitions,
        "stop_after_first_training_positive": stop_after_first_training_positive,
        "transient_retry_limit_per_page": MAX_TRANSIENT_RETRIES,
        "transient_backoff_seconds": [1, 2, 4],
        "initial_page_size": PAGE_SIZE,
        "default_page_size_by_dataset": dict(ledger["default_page_size_by_dataset"]),
        "pace_seconds_between_successful_pages": PACE_SECONDS,
        "shared_daily_quota": 3000,
        "shared_other_agents_request_count_known": False,
        "partitions_touched": [],
        "failed_partitions": [],
        "successful_pages": 0,
        "failed_request_attempts": 0,
        "quota_or_error": None,
    }
    ledger["runs"].append({"run_id": started, "status": "running", "manifest": str(run_path.relative_to(ROOT))})
    persist(ledger, run_path, run)

    stopping_status = "complete"
    touched: set[str] = set()
    try:
        with KraApiClient(
            service_key,
            base_url=settings.kra_api_base_url,
            timeout_seconds=min(settings.http_timeout_seconds, 20.0),
        ) as client:
            # Interleave both APIs month by month for a balanced stability check and backfill.
            ordering = [(name, month) for name in DATASETS for month in month_range()]
            dataset_order = {"entry_weight": 0, "daily_training": 1}
            ordering.sort(key=lambda pair: (pair[1], dataset_order[pair[0]]))
            for dataset, month in ordering:
                partition_key = f"{dataset}:{month}"
                partition = ledger["partitions"][partition_key]
                if partition.get("status") in {
                    "complete_positive_coverage",
                    "complete_positive_coverage_via_daily_tr_date",
                }:
                    continue
                if partition.get("status") == "empty_response" and not retry_empty:
                    continue
                spec = DATASETS[dataset]
                if partition.get("status") == "empty_response" and retry_empty:
                    partition.update({"status": "pending", "pages": []})
                    partition.pop("api_total_count", None)
                    partition.pop("expected_page_count", None)
                    partition.pop("page_size", None)
                if partition_key not in touched and len(touched) >= max_partitions:
                    stopping_status = "partition_limit_checkpoint"
                    break
                touched.add(partition_key)
                page_entries = partition.get("pages", [])
                requested_page_size = int(
                    partition.get("page_size")
                    or ledger["default_page_size_by_dataset"].get(dataset, PAGE_SIZE)
                )
                partition["page_size"] = requested_page_size
                next_page_no = len(page_entries) + 1
                if page_entries and not partition.get("expected_page_count"):
                    partition["status"] = "failed_resume_state"
                    partition["resume_error"] = "page data lacks expected_page_count"
                    persist(ledger, run_path, run)
                    stopping_status = "interrupted_error"
                    break
                if partition.get("expected_page_count") is not None and next_page_no > partition["expected_page_count"]:
                    set_partition_status(partition, spec)
                    persist(ledger, run_path, run)
                    continue
                page_retry_count = 0
                while True:
                    daily_requests = int(ledger["request_attempts_by_kst_date"].get(kst_date, 0))
                    if daily_requests >= max_new_requests:
                        partition["status"] = "request_budget_checkpoint"
                        partition["coverage_positive"] = False
                        persist(ledger, run_path, run)
                        raise RequestBudgetReached
                    params = {
                        "meet": 2,
                        spec["month_param"]: month,
                        "_type": "json",
                    }
                    request_params = {**params, "pageNo": next_page_no, "numOfRows": requested_page_size}
                    run["request_attempts"] += 1
                    ledger["request_attempts_by_this_collector"] = int(ledger.get("request_attempts_by_this_collector", 0)) + 1
                    ledger["request_attempts_by_kst_date"][kst_date] = daily_requests + 1
                    request_started_ms = int(time.time() * 1000)
                    page_attempt_number = 1 + sum(
                        int(error.get("attempt_number", 1)) > 0
                        for error in partition.get("request_errors", [])
                        if int(error.get("page_no", -1)) == next_page_no
                    )
                    persist(ledger, run_path, run)
                    try:
                        # Bypass the client's retry decorator so quota responses stop immediately.
                        fetched = client._fetch_json.__wrapped__(
                            client,
                            spec["endpoint"],
                            spec["operation"],
                            request_params,
                            service_key_parameter=spec["key_parameter"],
                        )
                    except Exception as exc:
                        is_quota = quota_signal(exc)
                        error = error_metadata(exc, service_key)
                        run["failed_request_attempts"] += 1
                        partition.setdefault("request_errors", []).append({
                            "page_no": next_page_no,
                            "attempt_number": page_attempt_number,
                            "request_started_at_ms": request_started_ms,
                            **error,
                        })
                        run["quota_or_error"] = error
                        if is_quota:
                            partition["status"] = "quota_stopped"
                            partition["coverage_positive"] = False
                            stopping_status = "quota_stopped"
                            persist(ledger, run_path, run)
                            break
                        if isinstance(exc, KraApiTransientError) and page_retry_count < MAX_TRANSIENT_RETRIES:
                            delay = BACKOFF_BASE_SECONDS * (2 ** page_retry_count)
                            page_retry_count += 1
                            partition["status"] = "retrying_transient"
                            partition["coverage_positive"] = False
                            partition.setdefault("transient_retry_events", []).append({
                                "page_no": next_page_no,
                                "attempt_number": page_attempt_number,
                                "retry_number": page_retry_count,
                                "backoff_seconds": delay,
                                "classification": error["classification"],
                            })
                            persist(ledger, run_path, run)
                            time.sleep(delay)
                            continue
                        partition["status"] = "request_failed"
                        partition["coverage_positive"] = False
                        run["failed_partitions"].append(partition_key)
                        persist(ledger, run_path, run)
                        break
                    run["successful_pages"] += 1
                    if contains_secret(fetched.body, service_key):
                        partition["status"] = "credential_echo_rejected"
                        partition["coverage_positive"] = False
                        stopping_status = "credential_echo_rejected"
                        persist(ledger, run_path, run)
                        raise RuntimeError("response credential echo rejected")
                    body_info = response_body(fetched.payload)
                    try:
                        total_count = int(body_info.get("totalCount") or 0)
                    except (TypeError, ValueError):
                        total_count = -1
                    try:
                        api_page_no = int(body_info.get("pageNo")) if body_info.get("pageNo") is not None else None
                    except (TypeError, ValueError):
                        api_page_no = None
                    try:
                        api_page_size = int(body_info.get("numOfRows")) if body_info.get("numOfRows") is not None else None
                    except (TypeError, ValueError):
                        api_page_size = None
                    if total_count < 0:
                        partition["status"] = "invalid_totalCount"
                        partition["coverage_positive"] = False
                        stopping_status = "interrupted_error"
                        persist(ledger, run_path, run)
                        raise ValueError("API response totalCount is not an integer")
                    if next_page_no == 1:
                        partition["api_total_count"] = total_count
                        partition["expected_page_count"] = max(1, math.ceil(total_count / requested_page_size))
                        partition["public_params"] = params
                        partition["endpoint"] = spec["endpoint"]
                        partition["operation"] = spec["operation"]
                        partition["date_field"] = spec["date_field"]
                    expected_pages = int(partition["expected_page_count"])
                    if total_count != partition["api_total_count"]:
                        partition.setdefault("validation_errors", []).append("totalCount_changed_between_pages")
                    rows = response_rows(fetched.payload)
                    requested_rows = min(requested_page_size, max(0, partition["api_total_count"] - (next_page_no - 1) * requested_page_size))
                    if len(rows) != requested_rows:
                        partition.setdefault("validation_errors", []).append("page_row_count_mismatch")
                    if api_page_no is not None and api_page_no != next_page_no:
                        partition.setdefault("validation_errors", []).append("pageNo_mismatch")
                    if api_page_size is not None and api_page_size != requested_page_size:
                        partition.setdefault("validation_errors", []).append("numOfRows_mismatch")
                    row_dates = date_values(rows, spec["date_field"])
                    month_matches = sum(normalized_date(row.get(spec["date_field"])).startswith(month) for row in rows)
                    if month_matches != len(rows):
                        partition.setdefault("validation_errors", []).append("row_date_outside_requested_month_or_missing")
                    run_page_dir = Path("raw") / dataset / month / started
                    relative = run_page_dir / f"page_{next_page_no:04d}.json"
                    atomic_immutable_write(ROOT / relative, fetched.body)
                    page_record = {
                        "page_no": next_page_no,
                        "status_code": fetched.status_code,
                        "content_type": fetched.content_type,
                        "requested_at_ms": fetched.requested_at_ms,
                        "retrieved_at_ms": fetched.retrieved_at_ms,
                        "request_started_at_ms": request_started_ms,
                        "request_attempt_number": page_attempt_number,
                        "source_url_without_key": fetched.source_url,
                        "public_params": params,
                        "api_total_count": total_count,
                        "api_page_no": api_page_no,
                        "api_page_size": api_page_size,
                        "requested_page_size": requested_page_size,
                        "response_bytes": len(fetched.body),
                        "response_sha256": digest(fetched.body),
                        "response_file": str(relative),
                        "actual_page_rows": len(rows),
                        "row_date_field": spec["date_field"],
                        "row_date_min": min(row_dates) if row_dates else None,
                        "row_date_max": max(row_dates) if row_dates else None,
                        "records_matching_requested_month": month_matches,
                    }
                    page_entries.append(page_record)
                    partition["pages"] = page_entries
                    set_partition_status(partition, spec)
                    run["partitions_touched"] = sorted(touched)
                    persist(ledger, run_path, run)
                    if partition.get("validation_errors"):
                        stopping_status = "interrupted_validation_mismatch"
                        break
                    if next_page_no >= expected_pages:
                        break
                    next_page_no += 1
                    time.sleep(PACE_SECONDS)
                if stopping_status != "complete":
                    break
                if partition.get("status") == "request_failed":
                    run["partitions_touched"] = sorted(touched)
                    persist(ledger, run_path, run)
                    continue
                if partition.get("status") not in {"complete_positive_coverage", "empty_response"}:
                    stopping_status = "interrupted_validation_mismatch"
                    break
                if partition.get("status") == "complete_positive_coverage":
                    run["last_completed_partition"] = partition_key
                    if dataset == "daily_training" and stop_after_first_training_positive:
                        run["first_positive_training_month"] = month
                        stopping_status = "first_positive_training_checkpoint"
                        persist(ledger, run_path, run)
                        break
                persist(ledger, run_path, run)
                time.sleep(PACE_SECONDS)
    except RequestBudgetReached:
        stopping_status = "request_budget_checkpoint"
    except Exception:
        if stopping_status == "complete":
            stopping_status = "interrupted_error"

    if stopping_status == "complete" and run["failed_partitions"]:
        stopping_status = "complete_with_partition_failures"
    run["status"] = stopping_status
    run["partitions_touched"] = sorted(touched)
    run["finished_at_utc"] = datetime.now(UTC).isoformat()
    ledger_run = next(item for item in reversed(ledger["runs"]) if item["run_id"] == started)
    ledger_run["status"] = stopping_status
    ledger_run["request_attempts"] = run["request_attempts"]
    write_coverage(ledger)
    persist(ledger, run_path, run)
    print(json.dumps({
        "run_id": started,
        "status": stopping_status,
        "request_attempts_this_run": run["request_attempts"],
        "request_attempts_by_this_collector_total": ledger["request_attempts_by_this_collector"],
        "last_completed_partition": run.get("last_completed_partition"),
        "ledger": str(LEDGER_PATH),
        "run_manifest": str(run_path),
        "credential_recorded": False,
    }, ensure_ascii=False))
    return 0 if stopping_status == "complete" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-new-requests", type=int, default=MAX_NEW_REQUESTS_DEFAULT)
    parser.add_argument("--max-partitions", type=int, default=594, help="Maximum new dataset-month partitions to enter in this run")
    parser.add_argument("--stop-after-first-training-positive", action="store_true", help="Stop after the first complete non-empty API18_1 month")
    parser.add_argument("--retry-empty", action="store_true", help="Retry months that previously returned zero rows")
    args = parser.parse_args()
    if args.max_new_requests < 1:
        parser.error("--max-new-requests must be positive")
    if args.max_partitions < 1:
        parser.error("--max-partitions must be positive")
    return collect(
        args.max_new_requests,
        args.max_partitions,
        retry_empty=args.retry_empty,
        stop_after_first_training_positive=args.stop_after_first_training_positive,
    )


if __name__ == "__main__":
    raise SystemExit(main())
