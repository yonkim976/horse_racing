"""Collect immutable Jeju-wide official KRA API pages for a research refresh.

This module never writes to either production or research databases. Cached
official pages are reused only after their stored SHA-256 and pagination
metadata are checked. Raw responses remain venue-wide; cohort filtering belongs
to the downstream loader.
"""

from __future__ import annotations

import concurrent.futures
import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, quote, quote_plus, urlsplit
from zoneinfo import ZoneInfo

import httpx


REPO_ROOT = Path(__file__).resolve().parents[2]
JEJU_ROOT = REPO_ROOT / "jeju"
DEFAULT_OUTPUT_DIR = JEJU_ROOT / "research/20261017_core_refresh/collection"
PROFILE_DB_PATH = JEJU_ROOT / "data/jeju_native_core.sqlite3"
PROFILE_MANIFEST_ROOT = JEJU_ROOT / "research/20261017_core_refresh"
MAX_CALLS = 300  # Includes retries and API42 profile lookups.
MAX_RETRIES = 2
MAX_WORKERS = 2
PAGE_SIZE = 1000
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
DEFAULT_FAMILIES = (
    "race_result",
    "running_trial",
    "section_records",
    "corner_rank",
    "daily_training",
    "medical",
    "starting_exam",
    "starting_training_api",
    "horse_profile",
)
ALL_FAMILIES = frozenset(DEFAULT_FAMILIES)

if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from horse_racing.collectors import kra_api as api  # noqa: E402
from horse_racing.config import get_settings  # noqa: E402


_CALL_LOCK = threading.Lock()
_WRITE_LOCK = threading.Lock()


def _iso_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if re.fullmatch(r"\d{8}", raw):
        return datetime.strptime(raw, "%Y%m%d").date()
    return date.fromisoformat(raw)


def _kst_today() -> date:
    """Return the current calendar date in Korea Standard Time."""
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _validate_end_not_future(end: date, *, today: date | None = None) -> None:
    current_day = today if today is not None else _kst_today()
    if end > current_day:
        raise ValueError("requested end date cannot be after the current Asia/Seoul date")


def _month_partitions(start: date, end: date) -> list[str]:
    """Return every YYYYMM partition intersecting an inclusive date range."""
    if start > end:
        raise ValueError("start must be on or before end")
    cursor = date(start.year, start.month, 1)
    final = date(end.year, end.month, 1)
    months: list[str] = []
    while cursor <= final:
        months.append(cursor.strftime("%Y%m"))
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return months


def _date_digits(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = api.response_body(payload)
    items = body.get("items") or {}
    value = items.get("item") if isinstance(items, dict) else None
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(row, dict) for row in value):
        return value
    raise ValueError("Unexpected official API item structure")


def _safe_output_dir(output_dir: str | Path) -> Path:
    root = JEJU_ROOT.resolve(strict=True)
    candidate = Path(output_dir).expanduser().resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("output_dir must resolve inside jeju/") from exc
    return candidate


def _atomic_immutable_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_file() and path.read_bytes() == body:
            return
        raise FileExistsError("immutable raw page path already contains different bytes")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        try:
            os.link(temporary, path)
        except FileExistsError:
            if not path.is_file() or path.read_bytes() != body:
                raise
    finally:
        temporary.unlink(missing_ok=True)


def _write_manifest(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _payload_has_secret(body: bytes, secret: str) -> bool:
    for token in (secret, quote(secret, safe=""), quote_plus(secret, safe="")):
        encoded = token.encode("utf-8")
        if encoded and encoded in body:
            return True
    return False


def _public_url_is_safe(value: str) -> bool:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "apis.data.go.kr":
        return False
    if parsed.username or parsed.password or parsed.fragment:
        return False
    return not any("key" in key.lower() for key, _ in parse_qsl(parsed.query))


def _event_date_field(family: str) -> str | None:
    return {
        "race_result": "rcDate",
        "running_trial": "trainDate",
        "section_records": "rcDate",
        "corner_rank": "rcDate",
        "daily_training": "trDate",
        "medical": "clinicDate",
        "starting_exam": "trainDate",
        "starting_training_api": "trDate",
    }.get(family)


def _validate_scope_rows(
    family: str,
    rows: list[dict[str, Any]],
    start: date,
    end: date,
    *,
    exact_date: str | None = None,
) -> tuple[int, int]:
    field = _event_date_field(family)
    in_scope = 0
    out_of_scope = 0
    for row in rows:
        if "meet" in row and str(row.get("meet") or "").strip() not in {"제주", "2"}:
            raise ValueError("Official response included a non-Jeju venue row")
        if field is None:
            continue
        event = _date_digits(row.get(field))
        if not event:
            out_of_scope += 1
            continue
        if exact_date is not None and event != exact_date:
            raise ValueError("Date-filtered official response included a different event date")
        event_day = datetime.strptime(event, "%Y%m%d").date()
        if start <= event_day <= end:
            in_scope += 1
        else:
            out_of_scope += 1
        if event_day > end:
            raise ValueError("Official response contains an event after the requested cutoff")
    return in_scope, out_of_scope


class _RequestBudget:
    def __init__(self, limit: int = MAX_CALLS) -> None:
        self.limit = limit
        self.calls = 0
        self._lock = threading.Lock()

    def take(self) -> None:
        with self._lock:
            if self.calls >= self.limit:
                raise RuntimeError("request_call_limit_reached")
            self.calls += 1


def _fetch_one(
    client: Any,
    budget: _RequestBudget,
    *,
    endpoint: str,
    operation: str,
    params: dict[str, str | int],
    key_parameter: str = "serviceKey",
) -> Any:
    """Use the shared KRA client with this collector's explicit retry bound."""
    method = client._fetch_json
    single_attempt = getattr(method, "__wrapped__", None)
    if single_attempt is None:
        raise RuntimeError("KRA client retry wrapper cannot be safely bounded")
    for retry_no in range(MAX_RETRIES + 1):
        budget.take()
        try:
            fetched = single_attempt(
                client,
                endpoint,
                operation,
                params,
                service_key_parameter=key_parameter,
            )
            if fetched.status_code < 200 or fetched.status_code >= 300:
                raise RuntimeError("unexpected_http_status")
            if not _public_url_is_safe(fetched.source_url):
                raise RuntimeError("unsafe_or_unredacted_source_url")
            return fetched
        except api.KraApiRateLimitError:
            raise
        except (api.KraApiTransientError, api.KraApiError) as exc:
            retryable = isinstance(exc, api.KraApiTransientError)
            if not retryable or retry_no >= MAX_RETRIES:
                raise
            time.sleep(1.0 * (2**retry_no))
    raise RuntimeError("request_failed_after_bounded_retries")


def _load_manifest(root: Path) -> dict[str, Any] | None:
    path = root / "manifest.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _manifest_dataset(root: Path, name: str) -> tuple[dict[str, Any], list[tuple[Path, dict[str, Any]]]] | None:
    manifest = _load_manifest(root)
    if not manifest:
        return None
    dataset = next(
        (item for item in manifest.get("datasets", []) if isinstance(item, dict) and item.get("name") == name),
        None,
    )
    if dataset is None:
        return None
    pages: list[tuple[Path, dict[str, Any]]] = []
    for page in dataset.get("pages", []):
        if not isinstance(page, dict) or not isinstance(page.get("path"), str):
            return None
        candidate = (root / page["path"]).resolve()
        if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
            return None
        raw = candidate.read_bytes()
        if hashlib.sha256(raw).hexdigest() != page.get("sha256"):
            return None
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        rows = _rows(payload)
        if len(rows) != int(page.get("rows", -1)):
            return None
        body = api.response_body(payload)
        total = int(body.get("totalCount") or 0)
        page_size = int(body.get("numOfRows") or PAGE_SIZE)
        reported_page = int(body.get("pageNo") or 1)
        page_no = len(pages) + 1
        if total != int(page.get("totalCount", total)) or reported_page != page_no:
            return None
        if math.ceil(total / max(1, page_size)) > 1 and page_no > math.ceil(total / page_size):
            return None
        pages.append((candidate, page))
    if not pages:
        return None
    totals = {int(api.response_body(json.loads(path.read_bytes())).get("totalCount") or 0) for path, _ in pages}
    page_sizes = {int(api.response_body(json.loads(path.read_bytes())).get("numOfRows") or PAGE_SIZE) for path, _ in pages}
    if len(totals) != 1 or len(page_sizes) != 1:
        return None
    expected = max(1, math.ceil(next(iter(totals)) / max(1, next(iter(page_sizes)))))
    if len(pages) != expected:
        return None
    return dataset, pages


def _dataset_specs(start: date, end: date) -> dict[str, list[dict[str, Any]]]:
    specs: dict[str, list[dict[str, Any]]] = {}
    day = start
    while day <= end:
        compact = day.strftime("%Y%m%d")
        specs.setdefault("race_result", []).append({
            "partition": compact,
            "endpoint": api.RACE_RESULT_WITH_SECTIONS_ENDPOINT,
            "operation": api.RACE_RESULT_WITH_SECTIONS_OPERATION,
            "params": {"meet": 2, "rc_date": compact, "_type": "json"},
            "key_parameter": "ServiceKey",
            "exact_date": compact,
        })
        day += timedelta(days=1)
    return specs


def _page_metadata(
    *,
    family: str,
    path: Path | None,
    sha256: str | None,
    collected_at_utc: str,
    params: dict[str, Any],
    total_count: int | None,
    page_no: int | None,
    status: str,
    operation: str,
    row_count: int | None,
    http_status: int | None = None,
    source_path: str | None = None,
    in_scope_rows: int | None = None,
    out_of_scope_rows: int | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "family": family,
        "path": path.resolve().relative_to(REPO_ROOT).as_posix() if path else None,
        "sha256": sha256,
        "collected_at_utc": collected_at_utc,
        "params": params,
        "total_count": total_count,
        "page_no": page_no,
        "status": status,
        "operation": operation,
        "row_count": row_count,
        "pagination_complete": bool(path),
        "partition_status": "complete" if path else "failed",
    }
    if http_status is not None:
        record["http_status"] = http_status
    if source_path is not None:
        record["reused_from"] = source_path
    if in_scope_rows is not None:
        record["in_scope_rows"] = in_scope_rows
    if out_of_scope_rows is not None:
        record["out_of_scope_rows"] = out_of_scope_rows
    return record


def _prior_sources() -> tuple[Path, Path]:
    return (
        JEJU_ROOT / "predictions/refresh_20261017_history_20261016/official",
        JEJU_ROOT / "predictions/refresh_20261017_full_20261016/official",
    )


def _reuse_partition(
    *,
    family: str,
    prior_root: Path,
    dataset_name: str,
    expected_params: dict[str, Any] | None,
    output_dir: Path,
    start: date,
    end: date,
    secret: str,
    exact_date: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    cached = _manifest_dataset(prior_root, dataset_name)
    if cached is None:
        return None
    dataset, pages = cached
    source_params = dataset.get("params") or expected_params or {}
    if expected_params is not None and source_params != expected_params:
        return None
    metadata: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    output_partition = str(dataset_name).replace("/", "_")
    totals: set[int] = set()
    for index, (source, page) in enumerate(pages, start=1):
        raw = source.read_bytes()
        if _payload_has_secret(raw, secret):
            raise ValueError("credential_echo_in_cached_response")
        payload = json.loads(raw)
        rows = _rows(payload)
        body = api.response_body(payload)
        total = int(body.get("totalCount") or 0)
        totals.add(total)
        in_scope, out_scope = _validate_scope_rows(
            family, rows, start, end, exact_date=exact_date
        )
        target = output_dir / "raw" / family / output_partition / f"page_{index:04d}.json"
        _atomic_immutable_write(target, raw)
        retrieved_ms = page.get("retrieved_at_ms")
        retrieved = (
            datetime.fromtimestamp(int(retrieved_ms) / 1000, UTC).isoformat()
            if retrieved_ms else datetime.now(UTC).isoformat()
        )
        rel_source = source.resolve().relative_to(REPO_ROOT).as_posix()
        page_params = dict(source_params)
        page_params.update({"pageNo": index, "numOfRows": int(body.get("numOfRows") or PAGE_SIZE)})
        metadata.append(_page_metadata(
            family=family,
            path=target,
            sha256=hashlib.sha256(raw).hexdigest(),
            collected_at_utc=retrieved,
            params=page_params,
            total_count=total,
            page_no=index,
            status="reused_validated",
            operation=str(dataset.get("operation") or _operation_for(family)),
            row_count=len(rows),
            http_status=int(page.get("http_status") or 200),
            source_path=rel_source,
            in_scope_rows=in_scope,
            out_of_scope_rows=out_scope,
        ))
        all_rows.extend(rows)
    if len(totals) != 1 or sum(int(row["row_count"] or 0) for row in metadata) != next(iter(totals)):
        return None
    return metadata, all_rows


def _operation_for(family: str) -> str:
    return {
        "race_result": api.RACE_RESULT_WITH_SECTIONS_OPERATION,
        "running_trial": "ridingTestResult_1",
        "section_records": api.RACE_DETAIL_SECTION_RECORD_OPERATION,
        "corner_rank": api.RACE_PASSING_SUMMARY_OPERATION,
        "daily_training": api.DAILY_TRAINING_OPERATION,
        "medical": api.RACE_HORSE_CLINIC_OPERATION,
        "starting_exam": "startingTestResult_1",
        "starting_training_api": api.START_TRAINING_OPERATION,
        "horse_profile": "totalHorseInfo_1",
    }[family]


def _spec_for_cache(family: str, partition: str) -> tuple[str, dict[str, Any], str]:
    if family == "running_trial":
        return "trials", {"meet": 2, "tr_year": partition}, partition
    if family == "medical":
        return "medical", {"meet": 2, "clinic_year": partition}, partition
    if family == "starting_exam":
        return "starting_exams", {"meet": 2, "tr_year": partition}, partition
    if family == "starting_training_api":
        return "start_training", {"meet": 2, "tr_year": partition}, partition
    if family == "daily_training":
        return f"training_{partition[4:6]}", {"meet": 2, "tr_month": partition[:6]}, partition[:6]
    raise KeyError(family)


def _fresh_partition(
    *,
    client: Any,
    budget: _RequestBudget,
    family: str,
    partition: str,
    endpoint: str,
    operation: str,
    params: dict[str, str | int],
    key_parameter: str,
    exact_date: str | None,
    output_dir: Path,
    start: date,
    end: date,
    secret: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    page_no = 1
    pages: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    expected_total: int | None = None
    expected_page_count: int | None = None
    expected_page_size: int | None = None
    while True:
        request_params = {**params, "pageNo": page_no, "numOfRows": PAGE_SIZE}
        fetched = _fetch_one(
            client, budget, endpoint=endpoint, operation=operation,
            params=request_params, key_parameter=key_parameter,
        )
        raw = fetched.body
        if len(raw) > MAX_RESPONSE_BYTES:
            raise RuntimeError("response_size_limit_exceeded")
        if _payload_has_secret(raw, secret):
            raise RuntimeError("credential_echo_in_response")
        body = api.response_body(fetched.payload)
        total = int(body.get("totalCount") or 0)
        page_size = int(body.get("numOfRows") or PAGE_SIZE)
        reported_page = int(body.get("pageNo") or page_no)
        if reported_page != page_no:
            raise RuntimeError("pagination_page_number_mismatch")
        if expected_total is None:
            expected_total = total
            expected_page_size = page_size
            expected_page_count = max(1, math.ceil(total / max(1, page_size)))
        elif total != expected_total or page_size != expected_page_size:
            raise RuntimeError("pagination_metadata_mismatch")
        rows = _rows(fetched.payload)
        in_scope, out_scope = _validate_scope_rows(
            family, rows, start, end, exact_date=exact_date
        )
        target = output_dir / "raw" / family / partition / f"page_{page_no:04d}.json"
        _atomic_immutable_write(target, raw)
        fetched_at = datetime.fromtimestamp(fetched.retrieved_at_ms / 1000, UTC).isoformat()
        digest = hashlib.sha256(raw).hexdigest()
        page_params = dict(request_params)
        record = _page_metadata(
            family=family,
            path=target,
            sha256=digest,
            collected_at_utc=fetched_at,
            params=page_params,
            total_count=total,
            page_no=page_no,
            status="collected",
            operation=operation,
            row_count=len(rows),
            http_status=fetched.status_code,
            in_scope_rows=in_scope,
            out_of_scope_rows=out_scope,
        )
        pages.append(record)
        all_rows.extend(rows)
        if page_no >= (expected_page_count or 1):
            break
        page_no += 1
    actual_total = sum(int(page["row_count"] or 0) for page in pages)
    complete = actual_total == (expected_total or 0) and len(pages) == (expected_page_count or 1)
    if not complete:
        raise RuntimeError("pagination_incomplete")
    state = {
        "family": family,
        "partition": partition,
        "operation": operation,
        "params": params,
        "status": "complete" if actual_total else "empty_success",
        "api_total_count": expected_total,
        "actual_rows": actual_total,
        "expected_page_count": expected_page_count,
        "actual_page_count": len(pages),
        "in_scope_rows": sum(int(page.get("in_scope_rows") or 0) for page in pages),
        "out_of_scope_rows": sum(int(page.get("out_of_scope_rows") or 0) for page in pages),
    }
    return pages, all_rows, state


def _cache_roster_ids() -> set[str]:
    path = JEJU_ROOT / "research/20260930_api42_horse_breed_collection/target_ids.jsonl"
    found: set[str] = set()
    if not path.is_file():
        return found
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        horse_id = str(value.get("hrNo") or "")
        if re.fullmatch(r"\d{7}", horse_id):
            found.add(horse_id)
    return found


def _manifest_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _successful_profile_manifest_history(
    manifest_root: Path = PROFILE_MANIFEST_ROOT,
) -> dict[str, Any]:
    """Read prior successful collection manifests to persist profile rotation.

    This only reads manifests under the refresh research directory. Failed
    profile requests are not treated as completed lookups, so they remain
    eligible for an early retry.
    """
    refresh_root = manifest_root.resolve()
    candidates: list[tuple[datetime, Path, dict[str, Any], dict[str, Any]]] = []
    if not refresh_root.is_dir():
        return {
            "manifest_count": 0,
            "visited_ids": set(),
            "last_selected_ids": [],
            "last_selected_at_by_id": {},
            "last_manifest_path": None,
            "last_completed_at_utc": None,
        }

    for path in refresh_root.rglob("source_manifest.json"):
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(refresh_root)
            manifest = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict) or manifest.get("collection_status") != "completed":
            continue
        completed_at = manifest.get("completed_at_utc")
        completed_dt = _manifest_timestamp(completed_at)
        profile_selection = manifest.get("profile_selection")
        if completed_dt is None or not isinstance(profile_selection, dict):
            continue
        candidates.append((completed_dt, resolved, manifest, profile_selection))

    candidates.sort(key=lambda item: (item[0], item[1].as_posix()))
    visited_ids: set[str] = set()
    selected_at_by_id: dict[str, str] = {}
    last_selected_ids: list[str] = []
    last_manifest_path: str | None = None
    last_completed_at_utc: str | None = None
    for completed_dt, path, manifest, profile_selection in candidates:
        completed_at = str(manifest.get("completed_at_utc"))
        previous_selected = [
            str(value) for value in profile_selection.get("selected_ids", [])
            if re.fullmatch(r"\d{7}", str(value))
        ] if isinstance(profile_selection.get("selected_ids", []), list) else []
        failed_ids = {
            str(value) for value in profile_selection.get("failed_profile_ids", [])
            if re.fullmatch(r"\d{7}", str(value))
        } if isinstance(profile_selection.get("failed_profile_ids", []), list) else set()
        selected_set = set(previous_selected)
        if "requested_ids" in profile_selection:
            requested = profile_selection.get("requested_ids")
            visited_this_run = {
                str(value) for value in requested
                if re.fullmatch(r"\d{7}", str(value))
            } if isinstance(requested, list) else set()
            reused = profile_selection.get("reused_same_day_profile_ids", [])
            if isinstance(reused, list):
                visited_this_run.update(
                    str(value) for value in reused if re.fullmatch(r"\d{7}", str(value))
                )
            visited_this_run.intersection_update(selected_set)
        else:
            visited_this_run = selected_set
        visited_this_run.difference_update(failed_ids)

        profile_observed_at = completed_at
        for operation in manifest.get("operations", []):
            if isinstance(operation, dict) and operation.get("family") == "horse_profile":
                value = _manifest_timestamp(operation.get("profile_observation_time_utc"))
                if value is not None:
                    profile_observed_at = value.isoformat()
                    break
        for horse_id in visited_this_run:
            old_time = _manifest_timestamp(selected_at_by_id.get(horse_id))
            new_time = _manifest_timestamp(profile_observed_at)
            if new_time is not None and (old_time is None or new_time > old_time):
                selected_at_by_id[horse_id] = new_time.isoformat()

        last_selected_ids = previous_selected
        try:
            last_manifest_path = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            last_manifest_path = "external_profile_manifest_fixture"
        last_completed_at_utc = completed_dt.isoformat()

    return {
        "manifest_count": len(candidates),
        "visited_ids": visited_ids | set(selected_at_by_id),
        "last_selected_ids": last_selected_ids,
        "last_selected_at_by_id": selected_at_by_id,
        "last_manifest_path": last_manifest_path,
        "last_completed_at_utc": last_completed_at_utc,
    }


def _read_profile_latest_observed_at(
    horse_ids: Iterable[str],
    database_path: Path = PROFILE_DB_PATH,
) -> tuple[dict[str, str], str]:
    """Read latest profile timestamps through a read-only SQLite connection."""
    ids = sorted({str(value) for value in horse_ids if re.fullmatch(r"\d{7}", str(value))})
    if not ids:
        return {}, "not_needed"
    path = database_path.expanduser().resolve()
    if not path.is_file():
        return {}, "database_unavailable"
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5.0)
        try:
            connection.execute("PRAGMA query_only = ON")
            observations: dict[str, str] = {}
            for offset in range(0, len(ids), 400):
                chunk = ids[offset:offset + 400]
                placeholders = ",".join("?" for _ in chunk)
                query = (
                    "SELECT horse_id, observed_at_utc FROM horse_profile_latest "
                    f"WHERE horse_id IN ({placeholders})"
                )
                for row in connection.execute(query, chunk):
                    horse_id, observed_at = str(row[0]), str(row[1])
                    if re.fullmatch(r"\d{7}", horse_id) and observed_at:
                        observations[horse_id] = observed_at
            return observations, "read_only_query_succeeded"
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return {}, f"query_failed_{type(exc).__name__}"


def _order_profile_candidates(
    activity_by_id: dict[str, str],
    profile_observed_at_by_id: dict[str, str],
    history: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    """Prioritize never-profiled IDs, then rotate through the stalest profiles."""
    prior_selected = [
        str(value) for value in history.get("last_selected_ids", [])
        if str(value) in activity_by_id
    ]
    visited_ids = set(history.get("visited_ids", set()))
    last_selected_at = history.get("last_selected_at_by_id", {})
    if not isinstance(last_selected_at, dict):
        last_selected_at = {}

    def activity_key(horse_id: str) -> tuple[int, str]:
        return (-int(activity_by_id.get(horse_id) or "0"), horse_id)

    never_profiled_and_unvisited = [
        horse_id for horse_id in activity_by_id
        if horse_id not in profile_observed_at_by_id and horse_id not in visited_ids
    ]
    never_profiled_and_unvisited.sort(key=activity_key)

    rotation_pool = [horse_id for horse_id in activity_by_id if horse_id not in never_profiled_and_unvisited]

    def effective_observation_time(horse_id: str) -> str:
        values = [
            value for value in (
                profile_observed_at_by_id.get(horse_id),
                last_selected_at.get(horse_id),
            ) if _manifest_timestamp(value) is not None
        ]
        # A previously selected but not yet persisted profile is treated as
        # recently looked up using its collection time, preventing starvation
        # or repeated selection when unchanged profiles do not advance DB age.
        return max(values, key=lambda value: _manifest_timestamp(value) or datetime.min.replace(tzinfo=UTC)) if values else "9999-12-31T23:59:59+00:00"

    rotation_pool.sort(key=lambda horse_id: (effective_observation_time(horse_id), *activity_key(horse_id)))
    anchor = next((horse_id for horse_id in reversed(prior_selected) if horse_id in rotation_pool), None)
    start_index = 0
    if anchor is not None and rotation_pool:
        start_index = (rotation_pool.index(anchor) + 1) % len(rotation_pool)
        rotation_pool = rotation_pool[start_index:] + rotation_pool[:start_index]

    # Keep the immediately previous successful slice at the back of this
    # cyclic pool. The database age order can shift after imports, so rotating
    # by a single anchor alone could otherwise bring some of that slice around
    # the front on the next run.
    recent_successful_selection = set(prior_selected) & visited_ids
    recently_selected = [horse_id for horse_id in rotation_pool if horse_id in recent_successful_selection]
    rotation_pool = [horse_id for horse_id in rotation_pool if horse_id not in recent_successful_selection]
    rotation_pool.extend(recently_selected)

    ordered = never_profiled_and_unvisited + rotation_pool
    details = {
        "new_unprofiled_unvisited_count": len(never_profiled_and_unvisited),
        "profiled_or_previously_visited_rotation_count": len(rotation_pool),
        "rotation_anchor_horse_id": anchor,
        "rotation_start_index": start_index,
        "previous_successful_manifest_path": history.get("last_manifest_path"),
        "previous_successful_manifest_completed_at_utc": history.get("last_completed_at_utc"),
        "previous_selected_id_count": len(prior_selected),
        "previous_successful_selected_deferred_count": len(recently_selected),
        "successful_manifest_history_count": int(history.get("manifest_count") or 0),
        "visited_candidate_count": len(visited_ids & set(activity_by_id)),
        "profile_database_observation_count": len(profile_observed_at_by_id),
    }
    return ordered, details


def _candidate_profile_ids(
    page_metadata: list[dict[str, Any]],
    start: date,
    end: date,
    *,
    profile_database_path: Path = PROFILE_DB_PATH,
    profile_manifest_root: Path = PROFILE_MANIFEST_ROOT,
) -> tuple[list[str], dict[str, str], dict[str, Any]]:
    candidates: dict[str, str] = {}
    for meta in page_metadata:
        family = meta.get("family")
        if family == "horse_profile" or family not in ALL_FAMILIES:
            continue
        path = meta.get("path")
        if not isinstance(path, str):
            continue
        full = REPO_ROOT / path
        try:
            full.resolve(strict=True).relative_to(JEJU_ROOT.resolve(strict=True))
            payload = json.loads(full.read_bytes())
            rows = _rows(payload)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        event_field = _event_date_field(str(family))
        for row in rows:
            horse_id = str(row.get("hrNo") or "").strip()
            if not re.fullmatch(r"\d{7}", horse_id):
                continue
            event = _date_digits(row.get(event_field)) if event_field else ""
            if event:
                event_day = datetime.strptime(event, "%Y%m%d").date()
                if not start <= event_day <= end:
                    continue
                previous = candidates.get(horse_id)
                if previous is None or event > previous:
                    candidates[horse_id] = event
    profile_observed_at, database_status = _read_profile_latest_observed_at(
        candidates, profile_database_path
    )
    history = _successful_profile_manifest_history(profile_manifest_root)
    ordered, ordering_details = _order_profile_candidates(
        candidates, profile_observed_at, history
    )
    ordering_details["profile_database_status"] = database_status
    try:
        ordering_details["profile_database_path"] = profile_database_path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        ordering_details["profile_database_path"] = "external_read_only_fixture"
    return ordered, candidates, ordering_details


def fetch_profiles(
    horse_ids: Iterable[str | int],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    *,
    client: Any | None = None,
    budget: _RequestBudget | None = None,
    max_profiles: int = 100,
) -> list[dict[str, Any]]:
    """Fetch API42 current profiles for selected official IDs.

    The caller chooses new and recent IDs; this function never scans the full
    4,718-horse research cohort. Profiles describe the query-time state.
    """
    output = _safe_output_dir(output_dir)
    ids = list(dict.fromkeys(
        str(value).strip() for value in horse_ids
        if re.fullmatch(r"\d{7}", str(value).strip())
    ))
    if max_profiles < 0:
        raise ValueError("max_profiles cannot be negative")
    ids = ids[:max_profiles]
    owns_client = client is None
    if owns_client:
        settings = get_settings()
        secret_obj = settings.data_go_kr_service_key
        if secret_obj is None:
            raise RuntimeError("official_api_credential_unavailable")
        secret = secret_obj.get_secret_value()
        client = _new_client(settings, secret)
    else:
        settings = None
        secret = client._service_key
    call_budget = budget or _RequestBudget()
    results: list[dict[str, Any]] = []
    try:
        for horse_id in ids:
            try:
                pages, profile_rows, state = _fresh_partition(
                    client=client,
                    budget=call_budget,
                    family="horse_profile",
                    partition=f"hr_no_{horse_id}",
                    endpoint="/API42_1/totalHorseInfo_1",
                    operation="totalHorseInfo_1",
                    params={"hr_no": horse_id, "_type": "json"},
                    key_parameter="ServiceKey",
                    exact_date=None,
                    output_dir=output,
                    start=date.min,
                    end=date.max,
                    secret=secret,
                )
                if len(profile_rows) != 1 or str(profile_rows[0].get("hrNo") or "") != horse_id:
                    raise RuntimeError("api42_profile_id_mismatch_or_missing")
                for page in pages:
                    page["status"] = "collected_profile_current"
                state["horse_id"] = horse_id
                state["observation_scope"] = "current_profile_at_collected_at_utc"
                results.extend(pages)
            except api.KraApiError as exc:
                results.append(_page_metadata(
                    family="horse_profile", path=None, sha256=None,
                    collected_at_utc=datetime.now(UTC).isoformat(),
                    params={"hr_no": horse_id}, total_count=None, page_no=None,
                    status=(exc.safe_details().get("error_reason") or "failed"),
                    operation="totalHorseInfo_1", row_count=None,
                ))
            except RuntimeError as exc:
                results.append(_page_metadata(
                    family="horse_profile", path=None, sha256=None,
                    collected_at_utc=datetime.now(UTC).isoformat(),
                    params={"hr_no": horse_id}, total_count=None, page_no=None,
                    status="failed_call_limit" if "limit" in str(exc) else "failed",
                    operation="totalHorseInfo_1", row_count=None,
                ))
    finally:
        if owns_client and client is not None:
            client.close()
    return results


def probe_starting_training_website(
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    dates: Iterable[str] = ("20260918", "20261016"),
) -> list[dict[str, Any]]:
    """Probe the website-only API22 replacement page on at most three dates.

    Redirects are recorded without following them; this is deliberately
    separate from the official API22 `starting_training_api` family.
    """
    output = _safe_output_dir(output_dir)
    date_values = list(dict.fromkeys(str(value) for value in dates))
    if not date_values or len(date_values) > 3:
        raise ValueError("website probe accepts one to three dates")
    for value in date_values:
        if not re.fullmatch(r"\d{8}", value):
            raise ValueError("website probe dates must use YYYYMMDD")
        probe_date = datetime.strptime(value, "%Y%m%d").date()
        _validate_end_not_future(probe_date)

    probe_root = output / "website_start_training_probe"
    probe_root.mkdir(parents=True, exist_ok=True)
    base_url = "https://race.kra.co.kr/startingData/getStartingTrainListAll.do"
    variants = (
        ("baseline", {"User-Agent": "JejuHorseResearch/1.0", "Accept": "text/html,*/*"}),
        ("referer", {"User-Agent": "Mozilla/5.0", "Accept": "text/html,*/*", "Referer": "https://race.kra.co.kr/"}),
    )
    records: list[dict[str, Any]] = []
    for value in date_values:
        iso = f"{value[:4]}/{value[4:6]}/{value[6:8]}"
        params = {"Act": "07", "Sub": "2", "meet": "2", "trDate": iso, "trDateReplace": value, "trNo": "", "trName": ""}
        for variant, headers in variants:
            record: dict[str, Any] = {
                "date": f"{value[:4]}-{value[4:6]}-{value[6:]}",
                "variant": variant,
                "endpoint_without_query": base_url,
                "params": params,
                "collected_at_utc": datetime.now(UTC).isoformat(),
            }
            try:
                with httpx.Client(timeout=20.0, follow_redirects=False) as web_client:
                    response = web_client.get(base_url, params=params, headers=headers)
                body = response.content
                record["http_status"] = response.status_code
                record["content_type"] = response.headers.get("content-type")
                record["response_bytes"] = len(body)
                if len(body) > 1024 * 1024:
                    record["status"] = "response_size_limit_exceeded"
                    records.append(record)
                    continue
                location = response.headers.get("location")
                if location:
                    target = urlsplit(httpx.URL(base_url).join(location).__str__())
                    if target.scheme != "https" or target.hostname != "race.kra.co.kr":
                        record["status"] = "redirect_target_outside_allowlist"
                    else:
                        record["redirect_host"] = target.hostname
                        record["redirect_path"] = target.path
                        record["status"] = "redirect_not_followed"
                elif response.status_code == 200:
                    record["status"] = "http_200_probe"
                else:
                    record["status"] = "http_response_probe"
                filename = f"{value}_{variant}.response"
                target_path = probe_root / "raw" / filename
                _atomic_immutable_write(target_path, body)
                record["path"] = target_path.resolve().relative_to(REPO_ROOT).as_posix()
                record["sha256"] = hashlib.sha256(body).hexdigest()
            except Exception as exc:
                record["status"] = "network_error"
                record["error_type"] = type(exc).__name__
            records.append(record)
    probe_manifest = {
        "schema_version": 1,
        "source": "KRA official starting-training website, separate from API22",
        "redirects_followed": False,
        "max_dates": 3,
        "max_probe_requests": 6,
        "response_byte_limit": 1024 * 1024,
        "tls_certificate_verification": "httpx default verification enabled",
        "records": records,
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }
    _write_manifest(probe_root / "manifest.json", probe_manifest)
    source_manifest = output / "source_manifest.json"
    if source_manifest.is_file():
        current = json.loads(source_manifest.read_text(encoding="utf-8"))
        current["website_start_training_probe"] = {
            "manifest_path": (probe_root / "manifest.json").resolve().relative_to(REPO_ROOT).as_posix(),
            "request_count": len(records),
            "status_counts": dict(__import__("collections").Counter(row.get("status") for row in records)),
            "separate_from_api22": True,
        }
        current["total_external_request_attempts_including_website_probe"] = int(current.get("request_attempts_used", 0)) + len(records)
        _write_manifest(source_manifest, current)
    return records


def _new_client(settings: Any, secret: str) -> Any:
    parts = urlsplit(settings.kra_api_base_url)
    if (
        parts.scheme != "https"
        or parts.hostname != "apis.data.go.kr"
        or parts.path.rstrip("/") != "/B551015"
        or parts.query
        or parts.fragment
        or parts.username
        or parts.password
    ):
        raise RuntimeError("configured_official_api_base_url_not_allowlisted")
    client = api.KraApiClient(
        secret,
        base_url=settings.kra_api_base_url,
        timeout_seconds=min(float(settings.http_timeout_seconds), 45.0),
    )
    # Keep the API key on the allowlisted HTTPS origin. Do not follow redirects.
    client._client.follow_redirects = False
    return client


def _collect_parallel_partitions(
    *,
    client: Any,
    budget: _RequestBudget,
    tasks: list[dict[str, Any]],
    output_dir: Path,
    start: date,
    end: date,
    secret: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    page_records: list[dict[str, Any]] = []
    row_sets: list[dict[str, Any]] = []
    operation_records: list[dict[str, Any]] = []
    lock = threading.Lock()

    def run(task: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        return _fresh_partition(
            client=client, budget=budget,
            family=task["family"], partition=task["partition"],
            endpoint=task["endpoint"], operation=task["operation"],
            params=task["params"], key_parameter=task["key_parameter"],
            exact_date=task.get("exact_date"), output_dir=output_dir,
            start=start, end=end, secret=secret,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_map = {pool.submit(run, task): task for task in tasks}
        for future in concurrent.futures.as_completed(future_map):
            task = future_map[future]
            try:
                pages, rows, operation = future.result()
            except api.KraApiError as exc:
                operation = {
                    "family": task["family"], "partition": task["partition"],
                    "operation": task["operation"], "params": task["params"],
                    "status": exc.safe_details().get("error_reason", "failed"),
                    "api_result_code": exc.safe_details().get("api_result_code"),
                    "http_status": exc.safe_details().get("http_status"),
                }
                pages = [_page_metadata(
                    family=task["family"], path=None, sha256=None,
                    collected_at_utc=datetime.now(UTC).isoformat(),
                    params=task["params"], total_count=None, page_no=None,
                    status=operation["status"], operation=task["operation"], row_count=None,
                )]
                rows = []
            except Exception as exc:
                operation = {
                    "family": task["family"], "partition": task["partition"],
                    "operation": task["operation"], "params": task["params"],
                    "status": "failed", "error_type": type(exc).__name__,
                }
                pages = [_page_metadata(
                    family=task["family"], path=None, sha256=None,
                    collected_at_utc=datetime.now(UTC).isoformat(),
                    params=task["params"], total_count=None, page_no=None,
                    status="failed", operation=task["operation"], row_count=None,
                )]
                rows = []
            with lock:
                page_records.extend(pages)
                row_sets.append({"family": task["family"], "partition": task["partition"], "rows": rows})
                operation_records.append(operation)
    return page_records, row_sets, operation_records


def collect_range(
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    start: date | str = "2026-09-13",
    end: date | str = "2026-10-16",
    families: Iterable[str] | None = None,
    *,
    reuse_snapshot: bool = False,
) -> list[dict[str, Any]]:
    """Collect inclusive official-source date coverage to an immutable folder.

    API42 profile requests are selected from horse IDs observed in the returned
    range-wide source pages. API22 remains a separate `starting_training_api`
    family and is not mixed with homepage starting-training rows.
    """
    first, last = _iso_date(start), _iso_date(end)
    if first > last:
        raise ValueError("start must be on or before end")
    _validate_end_not_future(last)
    output = _safe_output_dir(output_dir)
    selected = tuple(DEFAULT_FAMILIES if families is None else dict.fromkeys(families))
    unknown = set(selected) - ALL_FAMILIES
    if unknown:
        raise ValueError(f"unknown source families: {sorted(unknown)}")
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "source_manifest.json"
    if manifest_path.exists():
        raise FileExistsError("source_manifest.json already exists; choose a new collection directory")

    settings = get_settings()
    secret_obj = settings.data_go_kr_service_key
    if secret_obj is None:
        raise RuntimeError("official_api_credential_unavailable")
    secret = secret_obj.get_secret_value()
    budget = _RequestBudget(MAX_CALLS)
    client = _new_client(settings, secret)
    prior_results_root, prior_official_root = _prior_sources()
    page_metadata: list[dict[str, Any]] = []
    operation_metadata: list[dict[str, Any]] = []
    row_sets: list[dict[str, Any]] = []
    family_errors: list[dict[str, Any]] = []
    profile_selection_metadata: dict[str, Any] | None = None
    try:
        # Snapshot mode reuses older API4 dates and rechecks the latest 14 days
        # for corrections. Scheduled refreshes default to fresh date queries.
        if "race_result" in selected:
            tasks: list[dict[str, Any]] = []
            fresh_since = max(first, last - timedelta(days=13))
            for day in (first + timedelta(days=n) for n in range((last - first).days + 1)):
                compact = day.strftime("%Y%m%d")
                reused = _reuse_partition(
                    family="race_result", prior_root=prior_results_root,
                    dataset_name=f"results_{compact}",
                    expected_params=None, output_dir=output, start=first, end=last,
                    secret=secret, exact_date=compact,
                ) if reuse_snapshot and day < fresh_since else None
                if reused is not None:
                    pages, rows = reused
                    page_metadata.extend(pages)
                    row_sets.append({"family": "race_result", "partition": compact, "rows": rows})
                    operation_metadata.append({
                        "family": "race_result", "partition": compact,
                        "operation": api.RACE_RESULT_WITH_SECTIONS_OPERATION,
                        "params": {"meet": 2, "rc_date": compact, "_type": "json"},
                        "status": "complete_reused_validated" if pages[0]["row_count"] else "empty_success_reused_validated",
                        "api_total_count": pages[0]["total_count"],
                        "actual_rows": sum(int(p["row_count"] or 0) for p in pages),
                        "expected_page_count": len(pages), "actual_page_count": len(pages),
                        "in_scope_rows": sum(int(p.get("in_scope_rows") or 0) for p in pages),
                    })
                else:
                    tasks.append({
                        "family": "race_result", "partition": compact,
                        "endpoint": api.RACE_RESULT_WITH_SECTIONS_ENDPOINT,
                        "operation": api.RACE_RESULT_WITH_SECTIONS_OPERATION,
                        "params": {"meet": 2, "rc_date": compact, "_type": "json"},
                        "key_parameter": "ServiceKey", "exact_date": compact,
                    })
            if tasks:
                pages, rows, operations = _collect_parallel_partitions(
                    client=client, budget=budget, tasks=tasks, output_dir=output,
                    start=first, end=last, secret=secret,
                )
                page_metadata.extend(pages); row_sets.extend(rows); operation_metadata.extend(operations)

        # Existing whole-year/month official pages are copied only after SHA,
        # response row count, and all-page pagination checks pass.
        cache_families = ("running_trial", "daily_training", "medical", "starting_exam", "starting_training_api")
        for family in cache_families:
            if family not in selected:
                continue
            if family == "daily_training":
                partitions = _month_partitions(first, last)
            else:
                partitions = [str(year) for year in range(first.year,last.year+1)]
            family_complete = True
            fallback_specs: list[dict[str, Any]] = []
            for partition in partitions:
                name, params, _ = _spec_for_cache(family, partition)
                reused = _reuse_partition(
                    family=family, prior_root=prior_official_root,
                    dataset_name=name, expected_params=params,
                    output_dir=output, start=first, end=last, secret=secret,
                ) if reuse_snapshot else None
                if reused is None:
                    if reuse_snapshot:
                        family_complete = False
                        family_errors.append({"family": family, "partition": partition, "status": "validated_cache_unavailable"})
                    if family == "running_trial":
                        fallback_specs.append({"partition": partition, "endpoint": "/API20_1/ridingTestResult_1", "operation": "ridingTestResult_1", "params": {"meet": 2, "tr_year": partition, "_type": "json"}, "key_parameter": "ServiceKey"})
                    elif family == "daily_training":
                        fallback_specs.append({"partition": partition, "endpoint": api.DAILY_TRAINING_ENDPOINT, "operation": api.DAILY_TRAINING_OPERATION, "params": {"meet": 2, "tr_month": partition, "_type": "json"}, "key_parameter": "serviceKey"})
                    elif family == "medical":
                        fallback_specs.append({"partition": partition, "endpoint": api.RACE_HORSE_CLINIC_ENDPOINT, "operation": api.RACE_HORSE_CLINIC_OPERATION, "params": {"meet": 2, "clinic_year": partition, "_type": "json"}, "key_parameter": "serviceKey"})
                    elif family == "starting_exam":
                        fallback_specs.append({"partition": partition, "endpoint": "/API21_1/startingTestResult_1", "operation": "startingTestResult_1", "params": {"meet": 2, "tr_year": partition, "_type": "json"}, "key_parameter": "ServiceKey"})
                    elif family == "starting_training_api":
                        fallback_specs.append({"partition": partition, "endpoint": api.START_TRAINING_ENDPOINT, "operation": api.START_TRAINING_OPERATION, "params": {"meet": 2, "tr_year": partition, "_type": "json"}, "key_parameter": "serviceKey"})
                    continue
                pages, rows = reused
                page_metadata.extend(pages)
                row_sets.append({"family": family, "partition": partition, "rows": rows})
                operation_metadata.append({
                    "family": family, "partition": partition,
                    "operation": _operation_for(family), "params": params,
                    "status": "complete_reused_validated" if sum(int(p["row_count"] or 0) for p in pages) else "empty_success_reused_validated",
                    "api_total_count": sum(int(p["total_count"] or 0) for p in pages),
                    "actual_rows": sum(int(p["row_count"] or 0) for p in pages),
                    "expected_page_count": len(pages), "actual_page_count": len(pages),
                    "in_scope_rows": sum(int(p.get("in_scope_rows") or 0) for p in pages),
                    "cache_validated": True,
                })
            if fallback_specs:
                tasks = [{
                    "family": family,
                    "partition": spec["partition"],
                    "endpoint": spec["endpoint"],
                    "operation": spec["operation"],
                    "params": spec["params"],
                    "key_parameter": spec["key_parameter"],
                    "exact_date": None,
                } for spec in fallback_specs]
                pages, rows, operations = _collect_parallel_partitions(
                    client=client, budget=budget, tasks=tasks, output_dir=output,
                    start=first, end=last, secret=secret,
                )
                page_metadata.extend(pages); row_sets.extend(rows); operation_metadata.extend(operations)

        # API6/API303 pages are refreshed against each actual race date. Their
        # published zero-row responses are marked explicitly as missing data.
        result_dates = sorted({
            _date_digits(row.get("rcDate"))
            for group in row_sets if group["family"] == "race_result"
            for row in group["rows"] if _date_digits(row.get("rcDate"))
        })
        section_families = {
            "section_records": (api.RACE_DETAIL_SECTION_RECORD_ENDPOINT, api.RACE_DETAIL_SECTION_RECORD_OPERATION),
            "corner_rank": (api.RACE_PASSING_SUMMARY_ENDPOINT, api.RACE_PASSING_SUMMARY_OPERATION),
        }
        for family, (endpoint, operation) in section_families.items():
            if family not in selected:
                continue
            tasks = [{
                "family": family, "partition": day,
                "endpoint": endpoint, "operation": operation,
                "params": {"meet": 2, "rc_date": day, "_type": "json"},
                "key_parameter": "serviceKey", "exact_date": day,
            } for day in result_dates]
            if tasks:
                pages, rows, operations = _collect_parallel_partitions(
                    client=client, budget=budget, tasks=tasks, output_dir=output,
                    start=first, end=last, secret=secret,
                )
                for page in pages:
                    if page.get("row_count") == 0 and page.get("status") == "collected":
                        page["status"] = "missing_zero_rows"
                        page["partition_status"] = "missing_zero_rows"
                for item in operations:
                    if item.get("actual_rows") == 0 and item.get("status") == "empty_success":
                        item["status"] = "missing_zero_rows"
                page_metadata.extend(pages); row_sets.extend(rows); operation_metadata.extend(operations)
            else:
                family_errors.append({"family": family, "status": "no_race_dates_available_from_api4"})

        # API42 selection rotates across all raw family candidates. IDs without
        # a current profile and without a prior successful lookup run first;
        # remaining IDs follow profile age and the previous collection cursor.
        if "horse_profile" in selected:
            profile_candidates, latest_activity, profile_ordering = _candidate_profile_ids(
                page_metadata, first, last
            )
            cached_ids: set[str] = set()
            profile_cache: dict[str, tuple[Path, dict[str, Any]]] = {}
            manifest = _load_manifest(prior_official_root) if reuse_snapshot else None
            if manifest:
                for dataset in manifest.get("datasets", []):
                    name = str(dataset.get("name") or "") if isinstance(dataset, dict) else ""
                    match = re.fullmatch(r"profile_(\d{7})", name)
                    if not match:
                        continue
                    cached = _manifest_dataset(prior_official_root, name)
                    if cached is None:
                        continue
                    cached_dataset, pages = cached
                    if len(pages) != 1:
                        continue
                    source, page = pages[0]
                    payload = json.loads(source.read_bytes())
                    rows = _rows(payload)
                    if len(rows) != 1 or str(rows[0].get("hrNo") or "") != match.group(1):
                        continue
                    cached_ids.add(match.group(1)); profile_cache[match.group(1)] = (source, page)
            selected_profile_ids = profile_candidates[:100]
            for horse_id in selected_profile_ids:
                cached = profile_cache.get(horse_id)
                if cached is None:
                    continue
                source, page = cached
                raw = source.read_bytes()
                if _payload_has_secret(raw, secret):
                    raise ValueError("credential_echo_in_cached_profile")
                target = output / "raw" / "horse_profile" / f"hr_no_{horse_id}" / "page_0001.json"
                _atomic_immutable_write(target, raw)
                retrieved_ms = page.get("retrieved_at_ms")
                collected_at = datetime.fromtimestamp(int(retrieved_ms) / 1000, UTC).isoformat() if retrieved_ms else datetime.now(UTC).isoformat()
                page_metadata.append(_page_metadata(
                    family="horse_profile", path=target,
                    sha256=hashlib.sha256(raw).hexdigest(), collected_at_utc=collected_at,
                    params={"hr_no": horse_id, "_type": "json", "pageNo": 1, "numOfRows": PAGE_SIZE},
                    total_count=int(page.get("totalCount") or 1), page_no=1,
                    status="reused_validated_current_profile", operation="totalHorseInfo_1",
                    row_count=1, http_status=int(page.get("http_status") or 200),
                    source_path=source.resolve().relative_to(REPO_ROOT).as_posix(),
                ))
                row_sets.append({"family": "horse_profile", "partition": horse_id, "rows": _rows(json.loads(raw))})
            need_ids = [horse_id for horse_id in selected_profile_ids if horse_id not in cached_ids]
            # Reserve calls for any remaining source pagination/retries. The
            # recent horse-profile slice is capped at 100 lookups by design.
            room = max(0, min(100, MAX_CALLS - budget.calls - 20))
            fetched_profiles = fetch_profiles(
                need_ids[:room], output,
                client=client, budget=budget, max_profiles=room,
            )
            page_metadata.extend(fetched_profiles)
            known_profile_roster = _cache_roster_ids()
            requested_ids = need_ids[:room]
            profile_selection_metadata = {
                "eligible_activity_ids": profile_candidates,
                "new_ids_not_in_existing_profile_candidate_roster": [
                    horse_id for horse_id in profile_candidates if horse_id not in known_profile_roster
                ],
                "existing_candidate_roster_ids": [
                    horse_id for horse_id in profile_candidates if horse_id in known_profile_roster
                ],
                "selected_ids": selected_profile_ids,
                "requested_ids": requested_ids,
                "reused_same_day_profile_ids": sorted(set(selected_profile_ids) & cached_ids),
                "deferred_by_100_profile_slice_ids": profile_candidates[100:],
                "deferred_by_call_budget_ids": need_ids[room:],
                "failed_profile_ids": sorted({
                    str(page.get("params", {}).get("hr_no"))
                    for page in fetched_profiles
                    if not page.get("path") and page.get("params", {}).get("hr_no")
                }),
                "activity_date_by_horse_id": latest_activity,
                "candidate_ordering": profile_ordering,
            }
            operation_metadata.append({
                "family": "horse_profile", "partition": "selected_recent_ids",
                "operation": "totalHorseInfo_1",
                "status": "complete_selected_slice" if len(fetched_profiles) == len(need_ids[:room]) else "partial_selected_slice",
                "candidate_id_count": len(profile_candidates),
                "selected_id_count": len(selected_profile_ids),
                "cache_reused_id_count": len(set(selected_profile_ids) & cached_ids),
                "requested_id_count": len(need_ids[:room]),
                "not_requested_due_selection_or_budget": max(0, len(profile_candidates) - len(selected_profile_ids)) + max(0, len(need_ids) - room),
                "candidate_selection": (
                    "never-profiled and never-successfully-looked-up IDs first; remaining candidates ordered by "
                    "oldest horse_profile_latest.observed_at_utc, then cyclically rotated after the last selected ID"
                ),
                "profile_observation_time_utc": datetime.now(UTC).isoformat(),
            })
    finally:
        client.close()

    # A successful HTTP response with zero API6/API303 items is still an
    # observed source gap, distinct from a transport/API failure.
    operations_by_family: dict[str, dict[str, int]] = {}
    for operation in operation_metadata:
        family = str(operation.get("family"))
        info = operations_by_family.setdefault(family, {
            "partitions": 0,
            "complete": 0,
            "empty_or_missing": 0,
            "pagination_complete": 0,
            "failed": 0,
        })
        info["partitions"] += 1
        status = str(operation.get("status") or "")
        if status.startswith("complete"):
            info["complete"] += 1
            info["pagination_complete"] += 1
        elif status in {"empty_success", "empty_success_reused_validated", "missing_zero_rows"}:
            info["empty_or_missing"] += 1
            info["pagination_complete"] += 1
        else:
            info["failed"] += 1
    manifest_value = {
        "schema_version": 1,
        "source": "KRA official OpenAPI via apis.data.go.kr/B551015",
        "requested_range": {"start": first.isoformat(), "end": last.isoformat(), "meet": 2},
        "raw_scope": "all rows returned for Jeju meet; no active-cohort filter is applied",
        "target_date_results_queried": False,
        "api22_separate_family": True,
        "max_concurrent_requests": MAX_WORKERS,
        "max_request_attempts": MAX_CALLS,
        "request_attempts_used": budget.calls,
        "retry_policy": {"max_retries": MAX_RETRIES, "max_attempts_per_page": MAX_RETRIES + 1},
        "response_byte_limit_per_page": MAX_RESPONSE_BYTES,
        "tls_certificate_verification": "httpx default verification enabled; HTTPS host allowlisted",
        "database_write": False,
        "credential_recorded": False,
        "families_requested": list(selected),
        "reuse_snapshot": reuse_snapshot,
        "profile_selection": profile_selection_metadata,
        "family_coverage": operations_by_family,
        "operations": sorted(operation_metadata, key=lambda x: (str(x.get("family")), str(x.get("partition")))),
        "pages": sorted(page_metadata, key=lambda x: (str(x.get("family")), str(x.get("params", {}).get("rc_date") or x.get("params", {}).get("tr_date") or x.get("params", {}).get("clinic_year") or x.get("params", {}).get("tr_year") or x.get("params", {}).get("tr_month") or x.get("params", {}).get("hr_no") or ""), int(x.get("page_no") or 0))),
        "scope_notes": {
            "date_window": "The requested end date is limited to the current Asia/Seoul calendar date; no fixed 2026-10-16 global cutoff applies. This flag means the collector does not accept a future requested end date.",
            "monthly_or_yearly_reused_pages": "Pages can contain earlier dates in their month/year query; loader must filter to requested_range. Out-of-range rows are counted on each page.",
            "section_records_and_corner_rank": "Requeried for every event date with API4_3 race rows. Zero-row responses are marked missing_zero_rows.",
            "horse_profile": "API42 is current profile state. Up to 100 candidates are selected per run: IDs without a stored profile and prior successful lookup are prioritized, while remaining candidates rotate from the oldest horse_profile_latest.observed_at_utc and the last successful collection cursor. This is not a full-cohort refresh.",
            "api4_recent_recheck": "When reuse_snapshot=True, the latest 14 days are requeried and earlier requested days are reused only after page SHA/pagination validation. The default automatic mode requeried every requested date.",
        },
        "unavailable_cache_or_failures": family_errors,
        "completed_at_utc": datetime.now(UTC).isoformat(),
    }
    _write_manifest(manifest_path, manifest_value)
    return page_metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--start", default="2026-09-13")
    parser.add_argument("--end", default="2026-10-16")
    parser.add_argument("--reuse-snapshot", action="store_true")
    parser.add_argument("--family", action="append", dest="families")
    parser.add_argument("--probe-website-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.probe_website_only:
            records = probe_starting_training_website(args.output_dir)
            print(json.dumps({"status": "website_probe_complete", "records": len(records)}, ensure_ascii=False))
            raise SystemExit(0)
        pages = collect_range(
            args.output_dir, args.start, args.end,
            families=args.families, reuse_snapshot=args.reuse_snapshot,
        )
        print(json.dumps({
            "status": "collection_completed_with_manifested_coverage",
            "page_records": len(pages),
            "source_manifest": str(manifest_path) if (manifest_path := Path(args.output_dir) / "source_manifest.json").is_file() else None,
        }, ensure_ascii=False))
    except Exception as exc:
        # Do not serialize exception text, which may contain a request URL.
        print(json.dumps({"status": "collection_failed", "error_type": type(exc).__name__}, ensure_ascii=False))
        raise SystemExit(1)
