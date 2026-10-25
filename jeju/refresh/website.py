#!/usr/bin/env python3
"""Bounded collector for the official Jeju starting-training webpage.

This module is deliberately separate from the API collector: the KRA site is
used only when a small probe confirms that it returns the expected dated
training table. It writes raw HTML and a standalone website_manifest.json; it
never writes to a database.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import ssl
import threading
import time
from datetime import date as Date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener


BASE_URL = "https://race.kra.co.kr/startingData/getStartingTrainListAll.do"
EXPECTED_HEADER = ["소속조", "조번", "마명", "기승자", "조교장소", "비고"]
FIELD_NAMES = ["affiliation", "trainer_no", "horse_name", "rider", "location", "note"]
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_CONCURRENT_REQUESTS = 2
MAX_REQUEST_ATTEMPTS = 300
MAX_ATTEMPTS_PER_DATE = 3  # initial request plus at most two retries


class TrainingTableParser(HTMLParser):
    """Extract the known table and the official horse IDs attached to rows."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[list[str], list[str]]] = []
        self.inputs: dict[str, str] = {}
        self._table_depth = 0
        self._current_row: list[str] | None = None
        self._cell: list[str] | None = None
        self._horse_ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if tag == "input" and attrs_map.get("name"):
            self.inputs[str(attrs_map["name"])] = str(attrs_map.get("value") or "")
        if tag == "table":
            self._table_depth += 1
        if self._table_depth and tag == "tr":
            self._current_row = []
            self._horse_ids = []
        if self._current_row is not None and tag in {"td", "th"}:
            self._cell = []
        if self._current_row is not None and tag == "a":
            match = re.search(r"goPage1\(\s*['\"]([0-9]+)['\"]\s*\)", attrs_map.get("onclick") or "")
            if match:
                self._horse_ids.append(match.group(1))
        if self._cell is not None and tag == "br":
            self._cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._current_row is not None:
            self._current_row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        if tag == "tr" and self._current_row is not None:
            self.rows.append((self._current_row, self._horse_ids))
            self._current_row = None
            self._cell = None
        if tag == "table":
            self._table_depth = max(0, self._table_depth - 1)


def parse_training_html(raw: bytes, requested_date: str) -> list[dict]:
    """Validate date and table shape, then return rows with official horse IDs."""
    _validate_date_compact(requested_date)
    text = raw.decode("euc-kr", errors="strict")
    parser = TrainingTableParser()
    parser.feed(text)
    observed_date = parser.inputs.get("trDateReplace")
    if observed_date != requested_date:
        raise ValueError(f"wrong or missing hidden date: {observed_date!r}")
    if not any(cells == EXPECTED_HEADER for cells, _ in parser.rows):
        raise ValueError("expected starting-training table header missing")

    out: list[dict] = []
    for cells, horse_ids in parser.rows:
        if cells == EXPECTED_HEADER:
            continue
        if len(cells) != len(FIELD_NAMES):
            raise ValueError(f"unexpected starting-training table width: {len(cells)}")
        if len(horse_ids) != 1 or not re.fullmatch(r"[0-9]{6,7}", horse_ids[0]):
            raise ValueError("missing or ambiguous official horse ID")
        row = dict(zip(FIELD_NAMES, cells))
        row["horse_id_raw"] = horse_ids[0]
        row["source_row_no"] = len(out) + 1
        row["raw_row_json"] = dict(zip(EXPECTED_HEADER, cells)) | {"horse_id_raw": horse_ids[0]}
        out.append(row)
    return out


def _validate_date_compact(value: str) -> Date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError("date must be YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError(f"invalid date: {value}") from exc


def _date_range(start: str, end: str) -> list[str]:
    first = _validate_date_compact(start)
    last = _validate_date_compact(end)
    if last < first:
        raise ValueError("end date must be on or after start date")
    count = (last - first).days + 1
    if count > 60:
        raise ValueError("website collection range is limited to 60 calendar dates")
    return [(first + timedelta(days=offset)).strftime("%Y%m%d") for offset in range(count)]


def _params(date_compact: str) -> dict[str, str]:
    _validate_date_compact(date_compact)
    return {
        "trDateReplace": date_compact,
        "meet": "2",
        "trDate": f"{date_compact[:4]}/{date_compact[4:6]}/{date_compact[6:]}",
        "hrNo": "",
        "trNo": "",
        "trName": "",
        "Sub": "2",
        "Act": "07",
    }


def _request_url(date_compact: str) -> str:
    # The current official page submits the selected date as a form to this
    # endpoint. Keep parameters out of the URL and preserve the form contract.
    _validate_date_compact(date_compact)
    return BASE_URL


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class _RequestBudget:
    def __init__(self, maximum: int) -> None:
        if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= MAX_REQUEST_ATTEMPTS:
            raise ValueError(f"max_requests must be an integer from 1 to {MAX_REQUEST_ATTEMPTS}")
        self.maximum = maximum
        self.used = 0
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            if self.used >= self.maximum:
                return False
            self.used += 1
            return True


class _Throttle:
    def __init__(self, interval_seconds: float) -> None:
        if interval_seconds < 0:
            raise ValueError("interval_seconds must be non-negative")
        self.interval = interval_seconds
        self._next_at = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_at)
            self._next_at = slot + self.interval
        time.sleep(max(0.0, slot - now))


def _fetch_once(date_compact: str, timeout_seconds: float, throttle: _Throttle) -> dict:
    """Fetch one date; redirects are recorded and never followed."""
    url = _request_url(date_compact)
    params = _params(date_compact)
    requested_at = datetime.now(timezone.utc).isoformat()
    record = {
        "date": f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:]}",
        "url": url,
        "method": "POST",
        "form_params": params,
        "requested_at": requested_at,
        "status": "fetch_failed",
        "attempts": [],
    }
    throttle.wait()
    request = Request(
        url,
        data=urlencode(params).encode("ascii"),
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; JejuHorseResearch/1.0)",
            "Accept": "text/html,application/xhtml+xml",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://race.kra.co.kr",
            "Referer": "https://race.kra.co.kr/startingData/startingTrainList.do?Act=07&Sub=2&meet=2",
        },
        method="POST",
    )
    opener = build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != "race.kra.co.kr" or final.username or final.password:
                raise ValueError("unexpected response host or scheme")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("response exceeds 4 MiB limit")
            record["http_status"] = int(response.status)
            record["content_type"] = response.headers.get("Content-Type")
            record["_raw"] = raw
            try:
                rows = parse_training_html(raw, date_compact)
            except Exception as exc:  # malformed site responses remain raw evidence
                record["status"] = "parse_failed"
                record["error"] = f"{type(exc).__name__}: {exc}"
            else:
                record["rows"] = rows
                record["status"] = "complete" if rows else "empty"
    except HTTPError as exc:
        record["http_status"] = int(exc.code)
        record["status"] = "redirect_blocked" if 300 <= exc.code < 400 else "fetch_failed"
        record["error"] = "redirect not followed" if 300 <= exc.code < 400 else f"HTTP {exc.code}"
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["attempts"].append({"attempt": 1, "status": record["status"]})
    return record


def _save_raw(record: dict, output_dir: Path, run_id: str) -> dict:
    raw = record.pop("_raw", None)
    if raw is None:
        return record
    date_compact = record["date"].replace("-", "")
    rel = Path("website_starting_training") / run_id / "html" / f"{date_compact}.html"
    target = output_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    record["html_path"] = rel.as_posix()
    record["html_sha256"] = hashlib.sha256(raw).hexdigest()
    record["response_bytes"] = len(raw)
    record["rows_count"] = len(record.get("rows", []))
    record["received_at"] = datetime.now(timezone.utc).isoformat()
    return record


def _save_probe_raw(record: dict, output_dir: Path, run_id: str) -> dict:
    raw = record.get("_raw")
    if raw is None:
        return {}
    date_compact = record["date"].replace("-", "")
    rel = Path("website_starting_training") / run_id / "probe" / f"{date_compact}.html"
    target = output_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return {"html_path": rel.as_posix(), "html_sha256": hashlib.sha256(raw).hexdigest(), "response_bytes": len(raw)}


def _attempt_date(
    date_compact: str,
    budget: _RequestBudget,
    throttle: _Throttle,
    timeout_seconds: float,
    *,
    prior_attempts: list[dict] | None = None,
    max_attempts: int = MAX_ATTEMPTS_PER_DATE,
) -> dict:
    attempts: list[dict] = list(prior_attempts or [])
    last: dict | None = None
    for attempt_no in range(len(attempts) + 1, max_attempts + 1):
        if not budget.take():
            if last is None:
                last = {
                    "date": f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:]}",
                    "url": _request_url(date_compact),
                    "requested_at": datetime.now(timezone.utc).isoformat(),
                    "status": "budget_exhausted",
                    "attempts": attempts.copy(),
                }
            else:
                last["budget_exhausted"] = True
            break
        current = _fetch_once(date_compact, timeout_seconds, throttle)
        attempt_info = current["attempts"][0]
        attempt_info["attempt"] = attempt_no
        attempts.append(attempt_info)
        current["attempts"] = attempts.copy()
        last = current
        if current["status"] in {"complete", "empty"}:
            break
        if current["status"] == "parse_failed":
            break
        # A 302 is the known site failure mode. Repeated redirects add no value.
        if current["status"] == "redirect_blocked":
            break
        if attempt_no < MAX_ATTEMPTS_PER_DATE:
            time.sleep(float(attempt_no))
    assert last is not None
    last["attempts"] = attempts.copy()
    return last


def _probe_dates(dates: list[str]) -> list[str]:
    # The first and last dates exercise both ends of the requested period.
    return list(dict.fromkeys((dates[0], dates[-1])))


def collect_starting_training_website(
    output_dir: str | Path,
    start: str,
    end: str,
    *,
    max_requests: int = MAX_REQUEST_ATTEMPTS,
    max_workers: int = MAX_CONCURRENT_REQUESTS,
    interval_seconds: float = 0.25,
    timeout_seconds: float = 25.0,
) -> Path:
    """Probe the KRA page, then collect all calendar dates only if the page parses.

    A 200 response alone is not enough to start the full range: at least one
    probe must contain the expected header and the requested hidden date.
    The output is a self-contained `website_manifest.json` with raw HTML hashes.
    """
    dates = _date_range(start, end)
    if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
        raise ValueError("max_workers must be a positive integer")
    worker_count = min(max_workers, MAX_CONCURRENT_REQUESTS)
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    budget = _RequestBudget(max_requests)
    throttle = _Throttle(interval_seconds)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    probe_dates = _probe_dates(dates)
    probes: dict[str, dict] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(worker_count, len(probe_dates))) as pool:
        futures = {
            pool.submit(_attempt_date, d, budget, throttle, timeout_seconds, max_attempts=1): d
            for d in probe_dates
        }
        for future in concurrent.futures.as_completed(futures):
            probes[futures[future]] = future.result()

    probe_raw = {
        d: _save_probe_raw(entry, output, run_id)
        for d, entry in probes.items()
        if entry.get("status") not in {"complete", "empty"} and entry.get("_raw") is not None
    }
    successful_probe = any(entry.get("status") in {"complete", "empty"} for entry in probes.values())
    by_date: dict[str, dict] = {d: probes[d] for d in probes if d in dates}
    if successful_probe:
        remaining = [d for d in dates if d not in by_date or by_date[d].get("status") not in {"complete", "empty"}]
        # A failed probe counts as attempt one for that date.
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {
                pool.submit(
                    _attempt_date,
                    d,
                    budget,
                    throttle,
                    timeout_seconds,
                    prior_attempts=probes.get(d, {}).get("attempts", []),
                ): d
                for d in remaining
            }
            for future in concurrent.futures.as_completed(futures):
                by_date[futures[future]] = future.result()
    else:
        by_date = {}

    date_entries = [_save_raw(by_date[d], output, run_id) for d in dates if d in by_date]
    probe_entries = []
    for compact in probe_dates:
        entry = by_date.get(compact) or probes[compact]
        probe_entries.append({
            "date": entry.get("date"),
            "status": entry.get("status"),
            "http_status": entry.get("http_status"),
            "rows_count": entry.get("rows_count", len(entry.get("rows", []))),
            "attempt_count": len(entry.get("attempts", [])),
            "attempts": entry.get("attempts", []),
            **probe_raw.get(compact, {}),
        })

    statuses = sorted({str(entry.get("status")) for entry in date_entries})
    every_date_succeeded = len(date_entries) == len(dates) and all(
        entry.get("status") in {"complete", "empty"} for entry in date_entries
    )
    manifest = {
        "schema_version": 1,
        "source": "jeju_starting_training_homepage",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "requested_range": {"start": start, "end": end, "calendar_dates": len(dates)},
        "collection_status": (
            "probe_unavailable" if not successful_probe else "complete" if every_date_succeeded else "partial"
        ),
        "probe_gate": {
            "passed": successful_probe,
            "probe_dates": [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in probe_dates],
            "results": probe_entries,
        },
        "limits": {
            "max_concurrent_requests": worker_count,
            "max_request_attempts": budget.maximum,
            "request_attempts_used": budget.used,
            "max_attempts_per_date": MAX_ATTEMPTS_PER_DATE,
            "response_byte_limit": MAX_RESPONSE_BYTES,
            "tls_certificate_verification": True,
            "redirects_followed": False,
        },
        "status_counts": {status: sum(entry.get("status") == status for entry in date_entries) for status in statuses},
        "dates": date_entries,
    }
    manifest_path = output / "website_manifest.json"
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest_path


__all__ = ["collect_starting_training_website", "parse_training_html"]
