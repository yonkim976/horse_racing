"""Archive full 2002-2026 annual KRA API partitions for three detail sources.

Every response page is written once under a fresh run directory. The JSONL
ledger records page and failure events; --resume-run can continue an existing
run without replacing a saved response page. Credentials are loaded in memory
and never written to a manifest, ledger, path, or console output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

from horse_racing.collectors.kra_api import (
    JUDGE_REPORT_ENDPOINT,
    JUDGE_REPORT_OPERATION,
    RACE_HORSE_CLINIC_ENDPOINT,
    RACE_HORSE_CLINIC_OPERATION,
    START_TRAINING_ENDPOINT,
    START_TRAINING_OPERATION,
    KraApiClient,
    KraApiRateLimitError,
    KraApiTransientError,
    response_body,
)
from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parent
RUNS_ROOT = ROOT / "raw" / "full_year_clinic_judgement_start_training"
START_YEAR = 2002
END_YEAR = 2026
CUTOFF_DATE = "20260919"
MEET = 2
PAGE_SIZE = 1000
MIN_REQUEST_INTERVAL_SECONDS = 0.4
MAX_PAGE_ATTEMPTS = 3
RETRY_BACKOFF_BASE_SECONDS = 1.0

DATASETS: list[dict[str, str]] = [
    {
        "name": "clinic",
        "endpoint": RACE_HORSE_CLINIC_ENDPOINT,
        "operation": RACE_HORSE_CLINIC_OPERATION,
        "filter_field": "clinic_year",
        "date_field": "clinicDate",
    },
    {
        "name": "judge_report",
        "endpoint": JUDGE_REPORT_ENDPOINT,
        "operation": JUDGE_REPORT_OPERATION,
        "filter_field": "rc_year",
        "date_field": "rcDate",
    },
    {
        "name": "starting_training",
        "endpoint": START_TRAINING_ENDPOINT,
        "operation": START_TRAINING_OPERATION,
        "filter_field": "tr_year",
        "date_field": "trDate",
    },
]


def extract_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    values = response_body(payload).get("items") or {}
    items = values.get("item") if isinstance(values, dict) else None
    if items is None:
        return []
    if isinstance(items, dict):
        return [items]
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []


def as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def response_header(payload: dict[str, Any]) -> dict[str, Any]:
    root = payload.get("response", payload)
    if not isinstance(root, dict):
        return {}
    header = root.get("header") or {}
    return header if isinstance(header, dict) else {}


def fetch_once_without_client_retries(
    client: KraApiClient,
    endpoint: str,
    operation: str,
    params: dict[str, str | int],
) -> Any:
    """Call the request implementation once; this collector owns retry bounds."""
    method = client._fetch_json
    unwrapped = getattr(method, "__wrapped__", None)
    if unwrapped is None:
        raise RuntimeError("KRA client retry wrapper cannot be safely bounded")
    return unwrapped(
        client,
        endpoint,
        operation,
        params,
        service_key_parameter="serviceKey",
    )


def safe_exception_diagnostics(exc: BaseException) -> dict[str, Any]:
    """Return transport/status metadata only; never serialize exception text or URL query."""
    import errno as errno_module

    chain: list[dict[str, Any]] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        node: dict[str, Any] = {"exception_type": type(current).__name__}
        if isinstance(current, OSError):
            node["errno"] = current.errno
            if isinstance(current, getattr(__import__("socket"), "gaierror")):
                node["failure_category"] = "dns_resolution_failure"
            elif current.errno in {errno_module.ETIMEDOUT}:
                node["failure_category"] = "transport_timeout"
        response = getattr(current, "response", None)
        if response is not None:
            node["http_status"] = getattr(response, "status_code", None)
        request = getattr(current, "request", None)
        if request is not None:
            node["host"] = getattr(getattr(request, "url", None), "host", None)
        chain.append(node)
        current = current.__cause__ or current.__context__
    return {"exception_type": type(exc).__name__, "cause_chain": chain}


def contains_key(body: bytes, service_key: str) -> bool:
    values = (
        service_key.encode("utf-8"),
        quote(service_key, safe="").encode("utf-8"),
        quote_plus(service_key, safe="").encode("utf-8"),
    )
    return any(value and value in body for value in values)


def immutable_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != body:
            raise FileExistsError("immutable response path already contains different bytes")
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != body:
                raise
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def append_event(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def row_date(row: dict[str, Any], field: str) -> str:
    value = str(row.get(field) or "").strip()
    digits = "".join(char for char in value if char.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def page_record(
    *,
    dataset: dict[str, str],
    year: int,
    page_no: int,
    body_bytes: bytes,
    payload: dict[str, Any],
    fetched_meta: dict[str, Any],
    run_root: Path,
    params: dict[str, str | int],
    recovered_existing_file: bool = False,
) -> dict[str, Any]:
    response = response_body(payload)
    rows = extract_rows(payload)
    requested_year = str(year)
    dates = [row_date(row, dataset["date_field"]) for row in rows]
    valid_dates = [value for value in dates if value]
    matching_year = sum(value.startswith(requested_year) for value in valid_dates)
    after_cutoff = sum(value > CUTOFF_DATE for value in valid_dates)
    result_code = str(response_header(payload).get("resultCode") or "")
    relative_path = Path(dataset["name"]) / str(year) / "source_pages" / f"page_{page_no:04d}.json"
    absolute_path = run_root / relative_path
    immutable_write(absolute_path, body_bytes)
    record: dict[str, Any] = {
        "page_no": page_no,
        "reported_page_no": as_int(response.get("pageNo"), page_no),
        "status_code": fetched_meta.get("status_code"),
        "content_type": fetched_meta.get("content_type"),
        "requested_at_ms": fetched_meta.get("requested_at_ms"),
        "retrieved_at_ms": fetched_meta.get("retrieved_at_ms"),
        "source_url_without_key": fetched_meta.get("source_url_without_key"),
        "api_result_code": result_code,
        "api_total_count": as_int(response.get("totalCount"), 0),
        "api_page_size": as_int(response.get("numOfRows"), PAGE_SIZE),
        "api_reported_page_no": as_int(response.get("pageNo"), page_no),
        "actual_page_rows": len(rows),
        "rows_matching_requested_year": matching_year,
        "rows_with_unparseable_date": sum(not value for value in dates),
        "rows_after_cutoff": after_cutoff,
        "date_min": min(valid_dates) if valid_dates else None,
        "date_max": max(valid_dates) if valid_dates else None,
        "response_bytes": len(body_bytes),
        "response_sha256": hashlib.sha256(body_bytes).hexdigest(),
        "response_file": str(relative_path),
    }
    if recovered_existing_file:
        record["recovered_existing_file"] = True
    return record


def setup_run(run_id: str | None, resume_run: str | None) -> tuple[str, Path, dict[str, Any]]:
    if resume_run:
        run_root = RUNS_ROOT / resume_run
        manifest_path = run_root / "run_manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError("resume manifest not found")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("run_id") != resume_run:
            raise ValueError("resume run id does not match manifest")
        return resume_run, run_root, manifest

    new_run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_root = RUNS_ROOT / new_run_id
    run_root.mkdir(parents=True, exist_ok=False)
    datasets: dict[str, Any] = {}
    for item in DATASETS:
        datasets[item["name"]] = {
            "endpoint": item["endpoint"],
            "operation": item["operation"],
            "filter_field": item["filter_field"],
            "row_date_field": item["date_field"],
            "years": {
                str(year): {
                    "year": year,
                    "public_params": {
                        "meet": MEET,
                        item["filter_field"]: str(year),
                        "_type": "json",
                    },
                    "status": "pending",
                    "pages": [],
                }
                for year in range(START_YEAR, END_YEAR + 1)
            },
        }
    manifest = {
        "run_id": new_run_id,
        "source": "KRA official OpenAPI via data.go.kr/B551015",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "meet": MEET,
        "requested_year_range": [START_YEAR, END_YEAR],
        "cutoff_date_inclusive": CUTOFF_DATE,
        "cutoff_policy": "Archive all returned pages; report rows after cutoff separately, without discarding them.",
        "page_size_requested": PAGE_SIZE,
        "credential_recorded": False,
        "datasets": datasets,
        "summary": {"status": "running"},
    }
    atomic_json_write(run_root / "run_manifest.json", manifest)
    return new_run_id, run_root, manifest


def recover_page_if_present(
    *,
    dataset: dict[str, str],
    year: int,
    page_no: int,
    run_root: Path,
    params: dict[str, str | int],
) -> dict[str, Any] | None:
    relative = Path(dataset["name"]) / str(year) / "source_pages" / f"page_{page_no:04d}.json"
    path = run_root / relative
    if not path.is_file():
        return None
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
        response = response_body(payload)
        if as_int(response.get("pageNo"), page_no) != page_no:
            return None
        expected = {"meet": MEET, dataset["filter_field"]: str(year)}
        # The body does not echo request filters consistently. Its rows below
        # remain the authoritative year-scope check.
        record = page_record(
            dataset=dataset,
            year=year,
            page_no=page_no,
            body_bytes=raw,
            payload=payload,
            fetched_meta={
                "status_code": None,
                "content_type": None,
                "source_url_without_key": (
                    f"https://apis.data.go.kr/B551015{dataset['endpoint']}?"
                    + "&".join(f"{key}={value}" for key, value in [*params.items(), ("pageNo", page_no), ("numOfRows", PAGE_SIZE)])
                ),
            },
            run_root=run_root,
            params=params,
            recovered_existing_file=True,
        )
        record["recovery_request_scope"] = expected
        return record
    except Exception:
        return None


def valid_saved_page(
    record: dict[str, Any], *, dataset: dict[str, str], year: int, run_root: Path
) -> bool:
    try:
        path = run_root / record["response_file"]
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != record["response_sha256"]:
            return False
        payload = json.loads(body)
        response = response_body(payload)
        rows = extract_rows(payload)
        return (
            as_int(response.get("totalCount"), -1) == int(record["api_total_count"])
            and as_int(response.get("numOfRows"), PAGE_SIZE) == int(record["api_page_size"])
            and as_int(response.get("pageNo"), int(record["page_no"])) == int(record["page_no"])
            and len(rows) == int(record["actual_page_rows"])
            and all(row_date(row, dataset["date_field"]).startswith(str(year)) for row in rows)
        )
    except Exception:
        return False


def year_summary(
    *,
    year_entry: dict[str, Any],
    dataset: dict[str, str],
    year: int,
    run_root: Path,
) -> dict[str, Any]:
    pages = sorted(year_entry.get("pages", []), key=lambda item: int(item["page_no"]))
    total_count = pages[0].get("api_total_count") if pages else None
    page_size = pages[0].get("api_page_size") if pages else None
    expected_pages = max(1, math.ceil(int(total_count or 0) / max(int(page_size or PAGE_SIZE), 1))) if pages else None
    actual_rows = sum(int(page.get("actual_page_rows") or 0) for page in pages)
    matching_rows = sum(int(page.get("rows_matching_requested_year") or 0) for page in pages)
    after_cutoff = sum(int(page.get("rows_after_cutoff") or 0) for page in pages)
    invalid_dates = sum(int(page.get("rows_with_unparseable_date") or 0) for page in pages)
    all_saved_valid = bool(pages) and all(
        valid_saved_page(page, dataset=dataset, year=year, run_root=run_root)
        for page in pages
    )
    total_count_for_validation = int(total_count) if total_count is not None else -2
    page_size_for_validation = int(page_size) if page_size is not None else -2
    metadata_consistent = bool(pages) and all(
        int(page.get("api_total_count", -1)) == total_count_for_validation
        and int(page.get("api_page_size", -1)) == page_size_for_validation
        and int(page.get("api_reported_page_no", page.get("page_no", -1))) == int(page["page_no"])
        and int(page.get("actual_page_rows", -1)) == (
            min(int(page_size or PAGE_SIZE), max(0, int(total_count or 0) - (int(page["page_no"]) - 1) * int(page_size or PAGE_SIZE)))
        )
        for page in pages
    )
    expected_ids = list(range(1, int(expected_pages or 0) + 1))
    actual_ids = [int(page["page_no"]) for page in pages]
    complete = (
        bool(pages)
        and expected_pages is not None
        and actual_ids == expected_ids
        and actual_rows == int(total_count or 0)
        and matching_rows == actual_rows
        and all_saved_valid
        and metadata_consistent
        and invalid_dates == 0
    )
    if not pages:
        status = "pending_or_failed"
    elif complete and int(total_count or 0) == 0:
        status = "query_complete_zero_rows"
    elif complete:
        status = "complete_year_partition"
    elif actual_ids != expected_ids:
        status = "incomplete_pages"
    else:
        status = "incomplete_or_year_scope_mismatch"
    dates_min = min((page.get("date_min") for page in pages if page.get("date_min")), default=None)
    dates_max = max((page.get("date_max") for page in pages if page.get("date_max")), default=None)
    return {
        **year_entry,
        "status": status,
        "api_total_count": total_count,
        "api_page_size": page_size,
        "expected_page_count": expected_pages,
        "actual_page_count": len(pages),
        "actual_total_rows": actual_rows,
        "rows_matching_requested_year": matching_rows,
        "rows_after_cutoff": after_cutoff,
        "rows_with_unparseable_date": invalid_dates,
        "date_min": dates_min,
        "date_max": dates_max,
        "positive_data_evidence": bool(actual_rows and matching_rows),
        "pages": pages,
    }


def write_snapshots(
    run_root: Path,
    manifest: dict[str, Any],
    *,
    only_year: tuple[str, str] | None = None,
) -> None:
    atomic_json_write(run_root / "run_manifest.json", manifest)
    if only_year:
        dataset_name, year = only_year
        entry = manifest["datasets"][dataset_name]["years"][year]
        atomic_json_write(run_root / dataset_name / year / "year_manifest.json", entry)
        return
    for dataset_name, dataset in manifest["datasets"].items():
        for year, entry in dataset["years"].items():
            atomic_json_write(run_root / dataset_name / year / "year_manifest.json", entry)


def run_collection(run_id: str | None, resume_run: str | None) -> int:
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None or not secret.get_secret_value().strip():
        print(json.dumps({"status": "credential_unavailable"}))
        return 2
    service_key = secret.get_secret_value()
    try:
        active_run_id, run_root, manifest = setup_run(run_id, resume_run)
    except Exception as exc:
        print(json.dumps({"status": "run_setup_failed", "exception_type": type(exc).__name__}))
        return 2
    ledger_path = run_root / "attempt_ledger.jsonl"
    last_request_at = 0.0
    request_sequence = sum(1 for _ in ledger_path.open("r", encoding="utf-8")) if ledger_path.exists() else 0

    try:
        with KraApiClient(
            service_key,
            base_url=settings.kra_api_base_url,
            timeout_seconds=min(settings.http_timeout_seconds, 25.0),
        ) as client:
            for dataset in DATASETS:
                data_manifest = manifest["datasets"][dataset["name"]]
                for year in range(START_YEAR, END_YEAR + 1):
                    year_text = str(year)
                    year_entry = data_manifest["years"][year_text]
                    existing_records = {
                        int(row["page_no"]): row
                        for row in year_entry.get("pages", [])
                        if isinstance(row, dict) and row.get("page_no") is not None
                    }
                    for page_no in list(existing_records):
                        if not valid_saved_page(existing_records[page_no], dataset=dataset, year=year, run_root=run_root):
                            year_entry["status"] = "saved_page_integrity_error"
                            year_entry.setdefault("integrity_errors", []).append({"page_no": page_no, "detected_at_utc": datetime.now(UTC).isoformat()})
                            append_event(ledger_path, {
                                "event": "saved_page_integrity_error",
                                "dataset": dataset["name"],
                                "year": year,
                                "page_no": page_no,
                                "at_utc": datetime.now(UTC).isoformat(),
                            })
                            write_snapshots(run_root, manifest, only_year=(dataset["name"], year_text))
                            print(json.dumps({"run_id": active_run_id, "status": "saved_page_integrity_error", "dataset": dataset["name"], "year": year, "page_no": page_no}))
                            return 1

                    if year_entry.get("status") in {"complete_year_partition", "query_complete_zero_rows"}:
                        continue

                    params: dict[str, str | int] = {
                        "meet": MEET,
                        dataset["filter_field"]: year_text,
                        "_type": "json",
                    }
                    first_page = existing_records.get(1)
                    if first_page is None:
                        recovered = recover_page_if_present(
                            dataset=dataset,
                            year=year,
                            page_no=1,
                            run_root=run_root,
                            params=params,
                        )
                        if recovered:
                            existing_records[1] = recovered
                            year_entry["pages"] = sorted(existing_records.values(), key=lambda row: int(row["page_no"]))
                            append_event(ledger_path, {
                                "event": "orphan_page_recovered",
                                "dataset": dataset["name"],
                                "year": year,
                                "page_no": 1,
                                "response_sha256": recovered["response_sha256"],
                                "at_utc": datetime.now(UTC).isoformat(),
                            })
                            first_page = recovered

                    if first_page is None:
                        expected_pages = None
                    else:
                        expected_pages = max(1, math.ceil(int(first_page["api_total_count"]) / max(int(first_page["api_page_size"]), 1)))

                    pages_to_process = [1] if expected_pages is None else list(range(1, expected_pages + 1))
                    page_queue_index = 0
                    page_loop_failed = False
                    while page_queue_index < len(pages_to_process):
                        page_no = pages_to_process[page_queue_index]
                        page_queue_index += 1
                        if page_no in existing_records:
                            continue
                        request_sequence += 1
                        fetched = None
                        request_error: BaseException | None = None
                        request_started_at: str | None = None
                        attempts_used = 0
                        for attempt_no in range(1, MAX_PAGE_ATTEMPTS + 1):
                            elapsed = time.monotonic() - last_request_at if last_request_at else None
                            if elapsed is not None and elapsed < MIN_REQUEST_INTERVAL_SECONDS:
                                time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)
                            request_started_at = datetime.now(UTC).isoformat()
                            attempts_used = attempt_no
                            try:
                                fetched = fetch_once_without_client_retries(
                                    client,
                                    dataset["endpoint"],
                                    dataset["operation"],
                                    {**params, "pageNo": page_no, "numOfRows": PAGE_SIZE},
                                )
                                last_request_at = time.monotonic()
                                request_error = None
                                break
                            except KraApiRateLimitError as exc:
                                last_request_at = time.monotonic()
                                rate_event = {
                                    "event": "rate_limit_stop",
                                    "sequence": request_sequence,
                                    "dataset": dataset["name"],
                                    "year": year,
                                    "page_no": page_no,
                                    "attempt_no": attempt_no,
                                    "http_status": 429,
                                    "exception_type": type(exc).__name__,
                                    "diagnostics": safe_exception_diagnostics(exc),
                                    "at_utc": datetime.now(UTC).isoformat(),
                                }
                                append_event(ledger_path, rate_event)
                                year_entry["last_failure"] = rate_event
                                year_entry["status"] = "rate_limit_stopped"
                                year_entry["pages"] = sorted(existing_records.values(), key=lambda row: int(row["page_no"]))
                                write_snapshots(run_root, manifest, only_year=(dataset["name"], year_text))
                                manifest["summary"] = {
                                    "status": "quota_stopped",
                                    "stop_reason": "HTTP 429; no retry or further endpoint calls",
                                    "stopped_at": {"dataset": dataset["name"], "year": year, "page_no": page_no},
                                    "attempts": request_sequence,
                                }
                                write_snapshots(run_root, manifest)
                                print(json.dumps({"run_id": active_run_id, "event": "rate_limit_stop", "dataset": dataset["name"], "year": year, "page_no": page_no, "http_status": 429}))
                                return 3
                            except KraApiTransientError as exc:
                                last_request_at = time.monotonic()
                                request_error = exc
                                retry_event = {
                                    "event": "request_retry_scheduled" if attempt_no < MAX_PAGE_ATTEMPTS else "request_attempt_failed",
                                    "sequence": request_sequence,
                                    "dataset": dataset["name"],
                                    "year": year,
                                    "page_no": page_no,
                                    "attempt_no": attempt_no,
                                    "max_attempts": MAX_PAGE_ATTEMPTS,
                                    "exception_type": type(exc).__name__,
                                    "diagnostics": safe_exception_diagnostics(exc),
                                    "backoff_seconds": RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt_no - 1)) if attempt_no < MAX_PAGE_ATTEMPTS else 0,
                                    "at_utc": datetime.now(UTC).isoformat(),
                                }
                                append_event(ledger_path, retry_event)
                                if attempt_no < MAX_PAGE_ATTEMPTS:
                                    time.sleep(RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt_no - 1)))
                                    continue
                                break
                            except Exception as exc:
                                last_request_at = time.monotonic()
                                request_error = exc
                                break

                        if request_error is not None or fetched is None:
                            failure = {
                                "event": "request_failed_after_bounded_attempts",
                                "sequence": request_sequence,
                                "dataset": dataset["name"],
                                "year": year,
                                "page_no": page_no,
                                "attempts_used": attempts_used,
                                "exception_type": type(request_error).__name__ if request_error else "UnknownError",
                                "diagnostics": safe_exception_diagnostics(request_error) if request_error else {},
                                "requested_at_utc": request_started_at,
                                "at_utc": datetime.now(UTC).isoformat(),
                            }
                            append_event(ledger_path, failure)
                            year_entry.update(year_summary(year_entry=year_entry, dataset=dataset, year=year, run_root=run_root))
                            year_entry["status"] = "request_failed_resumable"
                            year_entry["last_failure"] = failure
                            year_entry["pages"] = sorted(existing_records.values(), key=lambda row: int(row["page_no"]))
                            write_snapshots(run_root, manifest, only_year=(dataset["name"], year_text))
                            print(json.dumps({"run_id": active_run_id, "event": "request_failed_after_bounded_attempts", "dataset": dataset["name"], "year": year, "page_no": page_no, "attempts_used": attempts_used, "exception_type": failure["exception_type"]}))
                            page_loop_failed = True
                            break

                        try:
                            if contains_key(fetched.body, service_key):
                                raise ValueError("response contained credential; body rejected")
                            parsed = response_body(fetched.payload)
                            returned_page = as_int(parsed.get("pageNo"), page_no)
                            if returned_page != page_no:
                                raise ValueError("API response page number did not match request")
                            record = page_record(
                                dataset=dataset,
                                year=year,
                                page_no=page_no,
                                body_bytes=fetched.body,
                                payload=fetched.payload,
                                fetched_meta={
                                    "status_code": fetched.status_code,
                                    "content_type": fetched.content_type,
                                    "requested_at_ms": fetched.requested_at_ms,
                                    "retrieved_at_ms": fetched.retrieved_at_ms,
                                    "source_url_without_key": fetched.source_url,
                                },
                                run_root=run_root,
                                params=params,
                            )
                            record["request_attempts"] = attempts_used
                            if page_no == 1 and expected_pages is None:
                                expected_pages = max(
                                    1,
                                    math.ceil(
                                        int(record["api_total_count"])
                                        / max(int(record["api_page_size"]), 1)
                                    ),
                                )
                                pages_to_process = list(range(1, expected_pages + 1))
                            existing_records[page_no] = record
                            year_entry["pages"] = sorted(existing_records.values(), key=lambda row: int(row["page_no"]))
                            year_entry.update(year_summary(year_entry=year_entry, dataset=dataset, year=year, run_root=run_root))
                            append_event(ledger_path, {
                                "event": "page_archived",
                                "sequence": request_sequence,
                                "dataset": dataset["name"],
                                "year": year,
                                "page_no": page_no,
                                "request_attempts": attempts_used,
                                "api_total_count": record["api_total_count"],
                                "actual_page_rows": record["actual_page_rows"],
                                "rows_matching_requested_year": record["rows_matching_requested_year"],
                                "rows_after_cutoff": record["rows_after_cutoff"],
                                "response_bytes": record["response_bytes"],
                                "response_sha256": record["response_sha256"],
                                "response_file": record["response_file"],
                                "requested_at_utc": request_started_at,
                                "at_utc": datetime.now(UTC).isoformat(),
                            })
                            write_snapshots(run_root, manifest, only_year=(dataset["name"], year_text))
                            print(json.dumps({
                                "run_id": active_run_id,
                                "event": "page_archived",
                                "dataset": dataset["name"],
                                "year": year,
                                "page_no": page_no,
                                "request_attempts": attempts_used,
                                "actual_page_rows": record["actual_page_rows"],
                                "api_total_count": record["api_total_count"],
                                "sha256": record["response_sha256"],
                            }))
                            time.sleep(MIN_REQUEST_INTERVAL_SECONDS)
                        except Exception as exc:
                            failure = {
                                "event": "page_validation_failed",
                                "sequence": request_sequence,
                                "dataset": dataset["name"],
                                "year": year,
                                "page_no": page_no,
                                "exception_type": type(exc).__name__,
                                "at_utc": datetime.now(UTC).isoformat(),
                            }
                            append_event(ledger_path, failure)
                            year_entry.update(year_summary(year_entry=year_entry, dataset=dataset, year=year, run_root=run_root))
                            year_entry["status"] = "validation_failed_resumable"
                            year_entry["last_failure"] = failure
                            write_snapshots(run_root, manifest, only_year=(dataset["name"], year_text))
                            print(json.dumps({"run_id": active_run_id, "event": "page_validation_failed", "dataset": dataset["name"], "year": year, "page_no": page_no, "exception_type": type(exc).__name__}))
                            page_loop_failed = True
                            break

                    if page_loop_failed:
                        year_entry["finished_at_utc"] = datetime.now(UTC).isoformat()
                        write_snapshots(run_root, manifest, only_year=(dataset["name"], year_text))
                        continue

                    year_entry.update(year_summary(year_entry=year_entry, dataset=dataset, year=year, run_root=run_root))
                    year_entry["finished_at_utc"] = datetime.now(UTC).isoformat()
                    write_snapshots(run_root, manifest, only_year=(dataset["name"], year_text))
                    if year_entry["status"] not in {"complete_year_partition", "query_complete_zero_rows"}:
                        append_event(ledger_path, {
                            "event": "year_incomplete",
                            "dataset": dataset["name"],
                            "year": year,
                            "status": year_entry["status"],
                            "at_utc": datetime.now(UTC).isoformat(),
                        })

        summary: dict[str, Any] = {}
        for dataset_name, dataset_manifest in manifest["datasets"].items():
            years = list(dataset_manifest["years"].values())
            complete_statuses = {"complete_year_partition", "query_complete_zero_rows"}
            summary[dataset_name] = {
                "years_complete": sum(entry.get("status") in complete_statuses for entry in years),
                "years_positive": sum(bool(entry.get("positive_data_evidence")) for entry in years),
                "rows": sum(int(entry.get("actual_total_rows") or 0) for entry in years),
                "pages": sum(int(entry.get("actual_page_count") or 0) for entry in years),
                "rows_after_cutoff": sum(int(entry.get("rows_after_cutoff") or 0) for entry in years),
                "failed_or_incomplete_years": [
                    int(entry["year"]) for entry in years if entry.get("status") not in complete_statuses
                ],
            }
        all_complete = all(value["years_complete"] == END_YEAR - START_YEAR + 1 for value in summary.values())
        manifest["summary"] = {
            "status": "complete" if all_complete else "incomplete",
            "datasets": summary,
            "finished_at_utc": datetime.now(UTC).isoformat(),
        }
        write_snapshots(run_root, manifest)
        print(json.dumps({"run_id": active_run_id, "summary": manifest["summary"], "manifest": str(run_root / "run_manifest.json")}, ensure_ascii=False))
        return 0 if all_complete else 1
    except Exception as exc:
        manifest["summary"] = {
            "status": "interrupted_resumable",
            "exception_type": type(exc).__name__,
            "at_utc": datetime.now(UTC).isoformat(),
        }
        write_snapshots(run_root, manifest)
        append_event(ledger_path, {"event": "run_interrupted", "exception_type": type(exc).__name__, "at_utc": datetime.now(UTC).isoformat()})
        print(json.dumps({"run_id": active_run_id, "status": "interrupted_resumable", "exception_type": type(exc).__name__}))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", help="Set the identifier for a new immutable run.")
    parser.add_argument("--resume-run", help="Resume the run id already present under the raw archive.")
    args = parser.parse_args()
    if args.run_id and args.resume_run:
        parser.error("--run-id and --resume-run cannot be combined")
    return run_collection(args.run_id, args.resume_run)


if __name__ == "__main__":
    raise SystemExit(main())
