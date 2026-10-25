#!/usr/bin/env python3
"""Collect official KRA Jeju training pages and exact row-level evidence.

The SQLite database is opened read-only. This script only writes artifacts below
this collection directory and reads fixed local KRA source files.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
JEJU = REPO / "jeju"
DB = JEJU / "data/jeju_native_core.sqlite3"
WINDOW_START = "2026-04-17"
WINDOW_END = "2026-10-17"
EXPECTED_ROWS = 20_408
EXPECTED_HORSES = 913
HOST = "race.kra.co.kr"
PAGE_PATH = "/racehorse/profileTrainState.do"
TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_WORKERS = 2
MAX_REQUEST_ATTEMPTS = 2
PROGRESS_EVERY = 50

PRIOR_DIR = JEJU / "research/20261017_training_rider_unclassified"
PRIOR_MANIFEST = PRIOR_DIR / "website_check.json"
ROSTER_DIR = REPO / "data/research/jockey_roster_20261008"
ROSTER_MANIFEST = ROSTER_DIR / "manifest.json"

SNAPSHOT_PATH = HERE / "target_snapshot.jsonl"
SNAPSHOT_SHA_PATH = HERE / "target_snapshot.sha256"
CHECKPOINT_PATH = HERE / "checkpoint.json"
PAGES_DIR = HERE / "pages"
PAGE_RESULTS_DIR = HERE / "page_results"
PAGE_MANIFEST_PATH = HERE / "pages_manifest.jsonl"
OUTCOMES_PATH = HERE / "outcomes.jsonl"
CANDIDATES_PATH = HERE / "candidates.jsonl"
MANIFEST_PATH = HERE / "manifest.json"

ID_RE = re.compile(r"^[0-9]{1,12}$")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load local helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fetcher = load_module(
    "kra_training_html_reader",
    JEJU / "research/20261015_training_rider_identity/source_review/collect_kra_training_html.py",
)
classifier = load_module(
    "training_rider_type_parser",
    JEJU / "research/20261015_training_rider_types/classify_riders.py",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def jsonl_bytes(rows) -> bytes:
    return b"".join((canonical(row) + "\n").encode("utf-8") for row in rows)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    values = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                values.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}") from exc
    return values


def open_db_read_only() -> sqlite3.Connection:
    if not DB.is_file():
        raise FileNotFoundError(f"Missing local source database: {DB}")
    connection = sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def database_target_rows() -> list[dict]:
    connection = open_db_read_only()
    try:
        assignments = [
            dict(row)
            for row in connection.execute(
                """SELECT * FROM daily_training_rider_type_assignments
                     WHERE rider_type=? AND training_date>=? AND training_date<=?
                     ORDER BY daily_training_api_row_id""",
                ("미분류", WINDOW_START, WINDOW_END),
            )
        ]
        row_ids = [int(row["daily_training_api_row_id"]) for row in assignments]
        sources: dict[int, dict] = {}
        for offset in range(0, len(row_ids), 800):
            batch = row_ids[offset : offset + 800]
            placeholders = ",".join("?" for _ in batch)
            query = (
                "SELECT * FROM daily_training_api_rows "
                f"WHERE daily_training_api_row_id IN ({placeholders}) "
                "ORDER BY daily_training_api_row_id"
            )
            for source in connection.execute(query, batch):
                sources[int(source["daily_training_api_row_id"])] = dict(source)
        if set(row_ids) != set(sources):
            missing = sorted(set(row_ids) - set(sources))[:10]
            raise ValueError(f"Assignment/source row mismatch; missing source IDs: {missing}")
        return [
            {
                "row_id": row_id,
                "assignment": assignment,
                "source": sources[row_id],
            }
            for row_id, assignment in zip(row_ids, assignments)
        ]
    finally:
        connection.close()


def validate_snapshot_file() -> tuple[list[dict], str]:
    if not SNAPSHOT_PATH.is_file() or not SNAPSHOT_SHA_PATH.is_file():
        raise FileNotFoundError("Initial target snapshot is missing; run --snapshot-only first")
    raw = SNAPSHOT_PATH.read_bytes()
    actual_sha = sha256_bytes(raw)
    expected_sha = SNAPSHOT_SHA_PATH.read_text(encoding="ascii").strip()
    if actual_sha != expected_sha:
        raise ValueError("Target snapshot SHA-256 does not match its sidecar")
    snapshot = read_jsonl(SNAPSHOT_PATH)
    if len(snapshot) != EXPECTED_ROWS:
        raise ValueError(f"Target snapshot row count changed: {len(snapshot)}")
    current = database_target_rows()
    current_sha = sha256_bytes(jsonl_bytes(current))
    if current_sha != actual_sha:
        raise ValueError(
            "Current read-only DB target assignments/source rows differ from initial snapshot; "
            "stop before collecting against changed rows"
        )
    return snapshot, actual_sha


def prepare_snapshot() -> tuple[list[dict], str]:
    current = database_target_rows()
    horse_ids = {str(row["assignment"].get("horse_id") or "") for row in current}
    if len(current) != EXPECTED_ROWS or len(horse_ids) != EXPECTED_HORSES:
        raise ValueError(
            f"Expected {EXPECTED_ROWS} target rows / {EXPECTED_HORSES} horses; "
            f"found {len(current)} / {len(horse_ids)}"
        )
    if any(not ID_RE.fullmatch(horse_id) for horse_id in horse_ids):
        raise ValueError("Target contains a horse ID outside the numeric KRA ID format")
    new_bytes = jsonl_bytes(current)
    new_sha = sha256_bytes(new_bytes)
    if SNAPSHOT_PATH.exists() or SNAPSHOT_SHA_PATH.exists():
        if not SNAPSHOT_PATH.is_file() or not SNAPSHOT_SHA_PATH.is_file():
            raise ValueError("Only one of the initial target snapshot and SHA sidecar exists")
        existing = SNAPSHOT_PATH.read_bytes()
        recorded = SNAPSHOT_SHA_PATH.read_text(encoding="ascii").strip()
        if sha256_bytes(existing) != recorded or recorded != new_sha:
            raise ValueError("Existing target snapshot differs; refusing to overwrite it")
    else:
        atomic_write(SNAPSHOT_PATH, new_bytes)
        atomic_write(SNAPSHOT_SHA_PATH, (new_sha + "\n").encode("ascii"))
    return current, new_sha


def load_roster() -> tuple[set[str], str]:
    manifest = read_json(ROSTER_MANIFEST)
    names: set[str] = set()
    for meet in (1, 2, 3):
        path = ROSTER_DIR / f"api_{meet}.json"
        expected_shas = {
            row["api_sha256"]
            for row in manifest.get("rows", [])
            if row.get("meet_code") == meet
        }
        if len(expected_shas) != 1 or sha256_file(path) not in expected_shas:
            raise ValueError(f"Archived API307 jockey roster SHA mismatch for meet {meet}")
        body = read_json(path).get("response", {}).get("body", {})
        items = body.get("items", {}).get("item", [])
        items = [items] if isinstance(items, dict) else items
        if len(items) != int(body.get("totalCount", -1)):
            raise ValueError(f"Archived API307 roster is incomplete for meet {meet}")
        names.update(
            str(item["jkName"])
            for item in items
            if item.get("jkName") not in (None, "", "-")
        )
    return names, sha256_file(ROSTER_MANIFEST)


def expected_url(horse_id: str) -> str:
    if not ID_RE.fullmatch(horse_id):
        raise ValueError(f"Invalid numeric KRA horse ID: {horse_id!r}")
    return fetcher.profile_url(horse_id)


def validate_official_url(url: str, horse_id: str) -> None:
    parsed = urlparse(url)
    expected_query = {"Act": ["02"], "Sub": ["1"], "hrNo": [horse_id], "meet": ["2"]}
    if (
        parsed.scheme != "https"
        or parsed.hostname != HOST
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != PAGE_PATH
        or parsed.fragment
        or parse_qs(parsed.query, keep_blank_values=True) != expected_query
    ):
        raise ValueError("URL failed the fixed KRA HTTPS host/path/query allowlist")


class FixedKraRedirect(HTTPRedirectHandler):
    def __init__(self, horse_id: str):
        super().__init__()
        self.horse_id = horse_id

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_official_url(newurl, self.horse_id)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def is_environment_network_block(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, socket.gaierror):
            return True
        if isinstance(current, PermissionError) or getattr(current, "errno", None) in (1, 13):
            return True
        text = str(current).lower()
        if any(
            marker in text
            for marker in (
                "name or service not known",
                "temporary failure in name resolution",
                "nodename nor servname provided",
                "failed to resolve",
                "name resolution",
                "operation not permitted",
            )
        ):
            return True
        current = current.__cause__ or current.__context__
    if isinstance(exc, URLError) and isinstance(exc.reason, BaseException):
        return is_environment_network_block(exc.reason)
    return False


def safe_error(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    return (text[:300] or type(exc).__name__)


def remote_fetch(horse_id: str, request_budget: int = MAX_REQUEST_ATTEMPTS) -> dict:
    url = expected_url(horse_id)
    validate_official_url(url, horse_id)
    attempts = 0
    errors = []
    started = time.monotonic()
    while attempts < request_budget:
        attempts += 1
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; KRA-training-evidence/1.0)",
                    "Accept": "text/html",
                },
            )
            opener = build_opener(FixedKraRedirect(horse_id))
            with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                status = int(response.status)
                final_url = response.geturl()
                content_type = response.headers.get("Content-Type", "")
                body = response.read(MAX_RESPONSE_BYTES + 1)
            validate_official_url(final_url, horse_id)
            if status != 200:
                raise ValueError(f"Unexpected HTTP status {status}")
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError(f"HTML response exceeded {MAX_RESPONSE_BYTES} bytes")
            if "text/html" not in content_type.lower():
                raise ValueError("Official profile response was not text/html")
            if not body:
                raise ValueError("Official profile response was empty")
            return {
                "horse_id": horse_id,
                "url": url,
                "final_url": final_url,
                "http_status": status,
                "content_type": content_type,
                "bytes": len(body),
                "sha256": sha256_bytes(body),
                "retrieved_at_utc": utc_now(),
                "fetch_seconds": round(time.monotonic() - started, 3),
                "attempts": attempts,
                "fetch_status": "http_200",
                "body": body,
            }
        except Exception as exc:
            errors.append({"attempt": attempts, "error_type": type(exc).__name__, "error": safe_error(exc)})
            if is_environment_network_block(exc):
                return {
                    "horse_id": horse_id,
                    "url": url,
                    "http_status": getattr(exc, "code", None),
                    "retrieved_at_utc": utc_now(),
                    "fetch_seconds": round(time.monotonic() - started, 3),
                    "attempts": attempts,
                    "fetch_status": "environment_network_block",
                    "errors": errors,
                    "environment_blocked": True,
                }
            if attempts >= request_budget:
                break
    return {
        "horse_id": horse_id,
        "url": url,
        "retrieved_at_utc": utc_now(),
        "fetch_seconds": round(time.monotonic() - started, 3),
        "attempts": attempts,
        "fetch_status": "request_failed",
        "errors": errors,
        "environment_blocked": False,
    }


def validate_page_body(body: bytes, content_type: str, horse_id: str) -> tuple[dict, dict]:
    parsed = fetcher.parse_page(body, content_type, horse_id)
    decoded = fetcher.decode_html(body, content_type)
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(decoded, "html.parser")
    page_text = " ".join(soup.stripped_strings)
    checks = {
        "profile_id_matches_url": bool(parsed.get("profile_id_matches_url")),
        "training_table_found": bool(parsed.get("training_table_found")),
        "profile_name_present": bool(parsed.get("profile_name_raw")),
        "rider_legend_present": "기승자범례" in page_text,
    }
    parsed["rider_legend_present"] = checks["rider_legend_present"]
    parsed["validation_checks"] = checks
    parsed["page_valid"] = all(checks.values())
    return parsed, checks


def known_reused_pages(horses: set[str]) -> dict[str, dict]:
    if not PRIOR_MANIFEST.is_file():
        raise FileNotFoundError("Prior eight-page evidence manifest is missing")
    prior = read_json(PRIOR_MANIFEST)
    prior_pages = {str(page.get("horse_id")): page for page in prior.get("pages", [])}
    reusable: dict[str, dict] = {}
    prior_root = PRIOR_DIR / "html"
    for horse_id in sorted(horses):
        if horse_id not in prior_pages:
            continue
        old = prior_pages[horse_id]
        source = prior_root / f"{horse_id}.html"
        expected = expected_url(horse_id)
        if (
            old.get("http_status") != 200
            or old.get("url") != expected
            or not source.is_file()
            or sha256_file(source) != old.get("sha256")
        ):
            continue
        body = source.read_bytes()
        if len(body) > MAX_RESPONSE_BYTES:
            continue
        content_type = old.get("content_type") or "text/html; charset=EUC-KR"
        parsed, checks = validate_page_body(body, content_type, horse_id)
        if not parsed.get("page_valid"):
            continue
        relative = source.relative_to(REPO).as_posix()
        reusable[horse_id] = {
            "horse_id": horse_id,
            "url": expected,
            "final_url": old.get("final_url") or expected,
            "http_status": 200,
            "content_type": content_type,
            "bytes": len(body),
            "sha256": old["sha256"],
            "source_path": relative,
            "retrieved_at_utc": old.get("retrieved_at_utc") or prior.get("checked_at_utc"),
            "attempts": 0,
            "fetch_status": "ok",
            "page_valid": True,
            "validation_checks": checks,
            "profile_name_raw": parsed.get("profile_name_raw"),
            "training_row_count": len(parsed.get("training_rows", [])),
            "reused_existing_source": True,
            "reused_from": relative,
        }
    return reusable


def load_checkpoint(snapshot_sha: str, roster_sha: str, horses: set[str]) -> dict:
    if not CHECKPOINT_PATH.exists():
        return {
            "schema_version": 1,
            "target_snapshot_sha256": snapshot_sha,
            "api307_roster_manifest_sha256": roster_sha,
            "updated_at_utc": utc_now(),
            "pages": {},
        }
    checkpoint = read_json(CHECKPOINT_PATH)
    if checkpoint.get("target_snapshot_sha256") != snapshot_sha:
        raise ValueError("Checkpoint target snapshot SHA changed")
    if checkpoint.get("api307_roster_manifest_sha256") != roster_sha:
        raise ValueError("Checkpoint API307 roster manifest SHA changed")
    if set(checkpoint.get("pages", {})) - horses:
        raise ValueError("Checkpoint contains horse IDs outside the current target")
    return checkpoint


def write_checkpoint(checkpoint: dict) -> None:
    checkpoint["updated_at_utc"] = utc_now()
    atomic_write(CHECKPOINT_PATH, (json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def page_source_path(record: dict, horse_id: str) -> Path | None:
    relative = record.get("source_path")
    if not relative:
        return None
    allowed_new = f"jeju/research/20261017_training_rider_website_completion/collection/pages/{horse_id}.html"
    allowed_old = f"jeju/research/20261017_training_rider_unclassified/html/{horse_id}.html"
    if relative not in (allowed_new, allowed_old):
        raise ValueError(f"Unexpected page source path for horse {horse_id}")
    path = REPO / relative
    if not path.is_file() or sha256_file(path) != record.get("sha256"):
        raise ValueError(f"Stored page source SHA mismatch for horse {horse_id}")
    validate_official_url(record.get("url", ""), horse_id)
    if record.get("http_status") != 200:
        return None
    return path


def all_source_event_key_counts(target_rows: list[dict], horse_ids: list[str]) -> Counter:
    connection = open_db_read_only()
    try:
        counts: Counter = Counter()
        for offset in range(0, len(horse_ids), 800):
            batch = horse_ids[offset : offset + 800]
            placeholders = ",".join("?" for _ in batch)
            query = (
                "SELECT daily_training_api_row_id,horse_id,training_date,start_time_local,"
                "end_time_local,duration_seconds FROM daily_training_api_rows "
                f"WHERE training_date>=? AND training_date<=? AND horse_id IN ({placeholders})"
            )
            for row in connection.execute(query, [WINDOW_START, WINDOW_END, *batch]):
                start = exact_api_clock_minutes(row["start_time_local"])
                end = exact_api_clock_minutes(row["end_time_local"])
                duration = row["duration_seconds"]
                if start is None or end is None or duration is None or int(duration) <= 0:
                    continue
                key = (str(row["horse_id"]), str(row["training_date"]), start, end, int(duration))
                counts[key] += 1
        return counts
    finally:
        connection.close()


def snapshot_fields(snapshot_row: dict) -> dict:
    assignment = snapshot_row["assignment"]
    source = snapshot_row["source"]
    return {
        "daily_training_api_row_id": int(snapshot_row["row_id"]),
        "daily_training_api_artifact_id": assignment.get("daily_training_api_artifact_id"),
        "source_row_index": source.get("source_row_index"),
        "prGubun_raw": assignment.get("prGubun_raw"),
        "prNo_raw": assignment.get("prNo_raw"),
        "horse_id": assignment.get("horse_id"),
        "training_date": assignment.get("training_date"),
        "start_time_local": assignment.get("start_time_local"),
        "end_time_local": assignment.get("end_time_local"),
        "duration_seconds": assignment.get("duration_seconds"),
        "rider_type": assignment.get("rider_type"),
        "type_status": assignment.get("type_status"),
        "website_type": assignment.get("website_type"),
        "website_label_raw": assignment.get("website_label_raw"),
        "website_jockey_name": assignment.get("website_jockey_name"),
        "website_source_path": assignment.get("website_source_path"),
        "website_sha256": assignment.get("website_sha256"),
        "raw_row_json": source.get("raw_row_json"),
    }


def exact_api_clock_minutes(value) -> int | None:
    """Return a minute value only when normalized API seconds are exactly zero."""
    if value is None:
        return None
    token = str(value).strip().split()[-1]
    match = re.fullmatch(r"(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d+))?(?:Z|[+-]\d{2}:\d{2})?", token)
    if not match or int(match.group(3)) != 0 or (match.group(4) and set(match.group(4)) != {"0"}):
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def base_outcome(snapshot_row: dict, page: dict | None, roster_sha: str) -> dict:
    fields = snapshot_fields(snapshot_row)
    horse_id = str(fields["horse_id"])
    page = page or {
        "horse_id": horse_id,
        "url": expected_url(horse_id),
        "fetch_status": "pending",
        "attempts": 0,
    }
    return {
        "row_id": fields["daily_training_api_row_id"],
        "original_fields": fields,
        "observed": None,
        "observed_type": "미분류",
        "candidate_type": "미분류",
        "candidate_jockey_name": None,
        "source_path": page.get("source_path"),
        "source_sha256": page.get("sha256"),
        "sha256": page.get("sha256"),
        "url": page.get("url") or expected_url(horse_id),
        "http_status": page.get("http_status"),
        "page_status": page.get("fetch_status"),
        "page_attempts": page.get("attempts", 0),
        "method": "exact_horse_date_start_end_duration_seconds",
        "match_status": "no_exact_match",
        "nomatchreason": "page_not_fetched",
        "roster_manifest_sha256": roster_sha,
    }


def rows_for_horse(
    horse_id: str,
    target_rows: list[dict],
    page: dict | None,
    roster_names: set[str],
    roster_sha: str,
    all_key_counts: Counter,
) -> list[dict]:
    page = page or {"horse_id": horse_id, "url": expected_url(horse_id), "fetch_status": "pending", "attempts": 0}
    source_path = page_source_path(page, horse_id) if page.get("sha256") else None
    parsed = None
    web_by_key: dict[tuple, list[dict]] = defaultdict(list)
    validation_checks = page.get("validation_checks")
    if source_path is not None and page.get("fetch_status") == "ok":
        body = source_path.read_bytes()
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError(f"Page exceeds byte bound after cache validation: {horse_id}")
        parsed, checks = validate_page_body(body, page.get("content_type", ""), horse_id)
        if not parsed.get("page_valid"):
            page["fetch_status"] = "validation_failed"
            page["validation_checks"] = checks
            page["validation_error"] = "horse/profile name, legend, or training table did not validate"
            parsed = None
        else:
            page["validation_checks"] = checks
            page["profile_name_raw"] = parsed.get("profile_name_raw")
            page["training_row_count"] = len(parsed.get("training_rows", []))
            for webrow in parsed.get("training_rows", []):
                start = fetcher.clock_minutes(webrow.get("start"))
                end = fetcher.clock_minutes(webrow.get("end"))
                minutes = webrow.get("duration_minutes")
                if start is None or end is None or minutes is None:
                    continue
                if end - start != int(minutes):
                    continue
                key = (horse_id, webrow["date"], start, end, int(minutes) * 60)
                web_by_key[key].append(webrow)

    results = []
    for snapshot_row in target_rows:
        out = base_outcome(snapshot_row, page, roster_sha)
        out["page_validation_checks"] = validation_checks
        if page.get("fetch_status") != "ok" or parsed is None:
            if page.get("fetch_status") == "pending":
                out["nomatchreason"] = "page_not_fetched"
            elif page.get("fetch_status") == "environment_network_block":
                out["nomatchreason"] = "official_site_dns_or_network_blocked"
            elif page.get("fetch_status") == "request_failed":
                out["nomatchreason"] = "official_site_request_failed_after_retry"
            elif page.get("fetch_status") == "validation_failed":
                out["nomatchreason"] = "official_page_validation_failed"
            else:
                out["nomatchreason"] = "official_page_unavailable"
            results.append(out)
            continue

        fields = out["original_fields"]
        start = exact_api_clock_minutes(fields.get("start_time_local"))
        end = exact_api_clock_minutes(fields.get("end_time_local"))
        duration = fields.get("duration_seconds")
        if start is None or end is None or duration is None or int(duration) <= 0:
            out["nomatchreason"] = "api_event_time_or_duration_missing_or_seconds_not_zero"
            results.append(out)
            continue
        event_key = (horse_id, fields["training_date"], start, end, int(duration))
        if all_key_counts[event_key] > 1:
            out["nomatchreason"] = "ambiguous_duplicate_source_event_key"
            out["source_key_collision_count"] = all_key_counts[event_key]
            results.append(out)
            continue
        web_matches = web_by_key.get(event_key, [])
        if not web_matches:
            out["nomatchreason"] = "no_exact_horse_date_start_end_minutes_duration_match"
            results.append(out)
            continue
        if len(web_matches) != 1:
            out["nomatchreason"] = "ambiguous_multiple_website_rows_for_exact_event_key"
            out["website_match_count"] = len(web_matches)
            results.append(out)
            continue

        webrow = web_matches[0]
        label = " ".join((webrow.get("website_name_raw") or "").split())
        observed_type, jockey_name = classifier.parse_label(label, roster_names)
        out["observed"] = {
            "website_label_raw": label,
            "website_type": observed_type,
            "website_profile_horse_id": horse_id,
            "website_profile_name_raw": parsed.get("profile_name_raw"),
            "website_date": webrow["date"],
            "website_start": webrow["start"],
            "website_end": webrow["end"],
            "website_duration_minutes": int(webrow["duration_minutes"]),
        }
        out["observed_type"] = observed_type
        out["candidate_type"] = observed_type
        out["candidate_jockey_name"] = jockey_name
        out["method"] = "exact_horse_date_start_end_minutes_duration"
        out["match_status"] = "exact_observation"
        out["nomatchreason"] = None
        if observed_type == "미분류":
            if label == "외":
                out["nomatchreason"] = "website_label_external"
            elif label in ("", "-", "경주일"):
                out["nomatchreason"] = "website_label_empty_or_placeholder"
            elif label in ("조", "관", "생"):
                out["nomatchreason"] = "website_role_marker_without_person_name"
            elif "(" not in label and label not in roster_names:
                out["nomatchreason"] = "bare_name_not_in_verified_api307_roster"
            else:
                out["nomatchreason"] = "website_label_unrecognized_or_ambiguous"
        elif observed_type == "기수":
            out["classification_method"] = "exact_name_in_sha_verified_api307_roster"
        else:
            out["classification_method"] = "explicit_website_role_marker"
        results.append(out)
    return results


def result_file(horse_id: str) -> Path:
    if not ID_RE.fullmatch(horse_id):
        raise ValueError("Unsafe horse ID for result file")
    return PAGE_RESULTS_DIR / f"{horse_id}.jsonl"


def write_page_results(horse_id: str, rows: list[dict]) -> None:
    atomic_write(result_file(horse_id), jsonl_bytes(rows))


def default_page_record(horse_id: str) -> dict:
    return {
        "horse_id": horse_id,
        "url": expected_url(horse_id),
        "fetch_status": "pending",
        "http_status": None,
        "attempts": 0,
        "retrieved_at_utc": None,
        "source_path": None,
        "sha256": None,
    }


def page_records_for_manifest(horses: list[str], pages: dict) -> list[dict]:
    result = []
    for horse_id in horses:
        page = dict(pages.get(horse_id) or default_page_record(horse_id))
        page["horse_id"] = horse_id
        page["url"] = expected_url(horse_id)
        result.append(page)
    return result


def refresh_outputs(
    snapshot: list[dict],
    horses: list[str],
    pages: dict,
    roster_names: set[str],
    roster_sha: str,
    snapshot_sha: str,
    all_key_counts: Counter,
    run_started: str,
    network_blocked: bool,
) -> dict:
    by_horse: dict[str, list[dict]] = defaultdict(list)
    for row in snapshot:
        by_horse[str(row["assignment"]["horse_id"])].append(row)

    outcomes_by_id: dict[int, dict] = {}
    for horse_id in horses:
        result_path = result_file(horse_id)
        page = pages.get(horse_id) or default_page_record(horse_id)
        if result_path.is_file():
            page_rows = read_jsonl(result_path)
            expected_ids = {int(row["row_id"]) for row in by_horse[horse_id]}
            page_ids = {int(row["row_id"]) for row in page_rows}
            if page_ids != expected_ids:
                raise ValueError(f"Cached page outcomes differ from target rows for {horse_id}")
        else:
            page_rows = rows_for_horse(
                horse_id,
                by_horse[horse_id],
                page,
                roster_names=roster_names,
                roster_sha=roster_sha,
                all_key_counts=all_key_counts,
            )
        for row in page_rows:
            row_id = int(row["row_id"])
            if row_id in outcomes_by_id:
                raise ValueError(f"Duplicate row outcome for {row_id}")
            outcomes_by_id[row_id] = row

    if len(outcomes_by_id) != EXPECTED_ROWS:
        raise ValueError(f"Outcome row count is {len(outcomes_by_id)}, expected {EXPECTED_ROWS}")
    outcomes = [outcomes_by_id[row_id] for row_id in sorted(outcomes_by_id)]
    candidates = [row for row in outcomes if row.get("match_status") == "exact_observation" and row.get("candidate_type") != "미분류"]
    atomic_write(OUTCOMES_PATH, jsonl_bytes(outcomes))
    atomic_write(CANDIDATES_PATH, jsonl_bytes(candidates))

    pages_manifest = page_records_for_manifest(horses, pages)
    atomic_write(PAGE_MANIFEST_PATH, jsonl_bytes(pages_manifest))
    page_counts = Counter(page.get("fetch_status", "pending") for page in pages_manifest)
    candidate_counts = Counter(row["candidate_type"] for row in candidates)
    outcome_status_counts = Counter(row.get("match_status", "") for row in outcomes)
    nomatch_counts = Counter(row["nomatchreason"] for row in outcomes if row.get("nomatchreason"))
    manifest = {
        "schema_version": 1,
        "generated_at_utc": utc_now(),
        "run_started_at_utc": run_started,
        "window_start_inclusive": WINDOW_START,
        "window_end_inclusive": WINDOW_END,
        "source_database": "jeju/data/jeju_native_core.sqlite3",
        "database_open_mode": "read_only",
        "database_modified": False,
        "target_snapshot_path": SNAPSHOT_PATH.relative_to(REPO).as_posix(),
        "target_snapshot_sha256": snapshot_sha,
        "target_assignment_row_count": len(snapshot),
        "target_horse_count": len(horses),
        "page_count": len(horses),
        "page_status_counts": dict(sorted(page_counts.items())),
        "outcome_row_count": len(outcomes),
        "outcome_status_counts": dict(sorted(outcome_status_counts.items())),
        "candidate_row_count": len(candidates),
        "candidate_type_counts": dict(sorted(candidate_counts.items())),
        "nomatch_reason_counts": dict(sorted(nomatch_counts.items())),
        "api307_roster_manifest_path": "data/research/jockey_roster_20261008/manifest.json",
        "api307_roster_manifest_sha256": roster_sha,
        "official_source": {
            "host_allowlist": [HOST],
            "path_allowlist": [PAGE_PATH],
            "query_template": "Act=02&Sub=1&hrNo=<numeric horse ID>&meet=2",
            "https_only": True,
            "certificate_verification": "default urllib TLS validation",
            "timeout_seconds": TIMEOUT_SECONDS,
            "response_byte_limit_per_page": MAX_RESPONSE_BYTES,
            "max_parallel_requests": MAX_WORKERS,
            "max_request_attempts": MAX_REQUEST_ATTEMPTS,
            "retry_policy": "one retry after ordinary request failure; stop early on environment DNS/permission block",
            "redirect_policy": "same fixed HTTPS host, path, and exact query only",
        },
        "matching_rule": "exact horse_id, training_date, start, end, website minutes, and API duration_seconds; source key and website duplicate keys remain ambiguous",
        "classification_rule": "explicit website role marker; bare name is jockey only by exact match in SHA-verified API307 rosters",
        "reuse_policy": "reuse only the prior eight current-window pages after recorded SHA, URL, HTTP status, horse ID, legend, and table validation",
        "environment_network_blocked": network_blocked,
        "collection_complete": all(page.get("fetch_status") == "ok" for page in pages_manifest),
        "artifacts": {
            "target_snapshot": SNAPSHOT_PATH.relative_to(REPO).as_posix(),
            "target_snapshot_sha256_sidecar": SNAPSHOT_SHA_PATH.relative_to(REPO).as_posix(),
            "page_manifest_jsonl": PAGE_MANIFEST_PATH.relative_to(REPO).as_posix(),
            "outcomes_jsonl": OUTCOMES_PATH.relative_to(REPO).as_posix(),
            "candidates_jsonl": CANDIDATES_PATH.relative_to(REPO).as_posix(),
            "checkpoint_json": CHECKPOINT_PATH.relative_to(REPO).as_posix(),
            "pages_directory": PAGES_DIR.relative_to(REPO).as_posix(),
            "page_results_directory": PAGE_RESULTS_DIR.relative_to(REPO).as_posix(),
        },
    }
    atomic_write(MANIFEST_PATH, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return manifest


def existing_page_is_valid(record: dict, horse_id: str) -> bool:
    if record.get("fetch_status") != "ok":
        return False
    path = page_source_path(record, horse_id)
    if path is None:
        return False
    body = path.read_bytes()
    parsed, checks = validate_page_body(body, record.get("content_type", ""), horse_id)
    if not parsed.get("page_valid"):
        raise ValueError(f"Cached HTTP 200 page no longer validates for horse {horse_id}: {checks}")
    return True


def save_remote_result(result: dict) -> dict:
    horse_id = result["horse_id"]
    record = {key: value for key, value in result.items() if key != "body"}
    record["page_valid"] = False
    if "body" in result:
        body = result["body"]
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("HTTP response byte bound exceeded before writing")
        path = PAGES_DIR / f"{horse_id}.html"
        atomic_write(path, body)
        parsed, checks = validate_page_body(body, result["content_type"], horse_id)
        record["source_path"] = path.relative_to(REPO).as_posix()
        record["page_valid"] = parsed.get("page_valid", False)
        record["validation_checks"] = checks
        record["profile_name_raw"] = parsed.get("profile_name_raw")
        record["training_row_count"] = len(parsed.get("training_rows", []))
        if not record["page_valid"]:
            record["fetch_status"] = "validation_failed"
            record["validation_error"] = "horse/profile name, legend, or training table did not validate"
        else:
            record["fetch_status"] = "ok"
    return record


def run_collection(snapshot: list[dict], snapshot_sha: str, snapshot_only: bool) -> dict:
    roster_names, roster_sha = load_roster()
    by_horse: dict[str, list[dict]] = defaultdict(list)
    for row in snapshot:
        by_horse[str(row["assignment"]["horse_id"])].append(row)
    horses = sorted(by_horse, key=lambda item: int(item))
    all_key_counts = all_source_event_key_counts(snapshot, horses)
    if snapshot_only:
        return {
            "target_snapshot_sha256": snapshot_sha,
            "target_rows": len(snapshot),
            "target_horses": len(horses),
            "verified_api307_name_count": len(roster_names),
            "api307_roster_manifest_sha256": roster_sha,
            "all_source_event_key_count": len(all_key_counts),
        }

    checkpoint = load_checkpoint(snapshot_sha, roster_sha, set(horses))
    pages: dict[str, dict] = checkpoint.setdefault("pages", {})
    # Import only the prior eight already-audited pages; every reuse is SHA and parser guarded.
    reusable = known_reused_pages(set(horses))
    for horse_id, record in reusable.items():
        if horse_id not in pages:
            pages[horse_id] = record
            page_rows = rows_for_horse(
                horse_id, by_horse[horse_id], record, roster_names, roster_sha, all_key_counts
            )
            write_page_results(horse_id, page_rows)
    write_checkpoint(checkpoint)

    cached_horses = set()
    pending = []
    for horse_id in horses:
        record = pages.get(horse_id)
        if record and existing_page_is_valid(record, horse_id):
            cached_horses.add(horse_id)
            if not result_file(horse_id).is_file():
                write_page_results(
                    horse_id,
                    rows_for_horse(horse_id, by_horse[horse_id], record, roster_names, roster_sha, all_key_counts),
                )
            continue
        prior_attempts = int((record or {}).get("attempts", 0))
        if prior_attempts >= MAX_REQUEST_ATTEMPTS:
            continue
        pending.append(horse_id)

    run_started = utc_now()
    completed_before = len(cached_horses)
    processed_this_run = 0
    environment_blocked = False
    pending_queue = list(pending)
    pending_index = 0
    in_flight = {}

    def submit_one(executor):
        nonlocal pending_index
        if pending_index >= len(pending_queue):
            return False
        horse = pending_queue[pending_index]
        pending_index += 1
        prior = pages.get(horse) or {}
        attempts_already = int(prior.get("attempts", 0))
        remaining_attempts = MAX_REQUEST_ATTEMPTS - attempts_already
        future = executor.submit(remote_fetch_with_attempt_budget, horse, remaining_attempts, attempts_already)
        in_flight[future] = horse
        return True

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        while len(in_flight) < MAX_WORKERS and submit_one(executor):
            pass
        while in_flight:
            done, _ = wait(tuple(in_flight), return_when=FIRST_COMPLETED)
            for future in done:
                horse_id = in_flight.pop(future)
                result = future.result()
                page = save_remote_result(result)
                page["attempts"] = int(result.get("attempts", 0))
                page["url"] = expected_url(horse_id)
                pages[horse_id] = page
                page_rows = rows_for_horse(
                    horse_id, by_horse[horse_id], page, roster_names, roster_sha, all_key_counts
                )
                write_page_results(horse_id, page_rows)
                write_checkpoint(checkpoint)
                processed_this_run += 1
                if page.get("fetch_status") == "validation_failed" and int(page.get("attempts", 0)) < MAX_REQUEST_ATTEMPTS:
                    pending_queue.append(horse_id)
                if result.get("environment_blocked"):
                    environment_blocked = True
                if processed_this_run % PROGRESS_EVERY == 0 or environment_blocked:
                    manifest = refresh_outputs(
                        snapshot, horses, pages, roster_names, roster_sha, snapshot_sha, all_key_counts, run_started, environment_blocked
                    )
                    print(
                        json.dumps(
                            {
                                "progress_pages_terminal": sum(
                                    page.get("fetch_status") != "pending"
                                    for page in page_records_for_manifest(horses, pages)
                                ),
                                "total_pages": len(horses),
                                "success_pages": manifest["page_status_counts"].get("ok", 0),
                                "failed_pages": sum(
                                    count for status, count in manifest["page_status_counts"].items()
                                    if status not in ("pending", "ok")
                                ),
                                "candidate_rows": manifest["candidate_row_count"],
                                "environment_network_blocked": environment_blocked,
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                if environment_blocked:
                    break
            if environment_blocked:
                # Do not spend requests on the rest of the set while DNS/permission blocks the host.
                for future in tuple(in_flight):
                    future.cancel()
                break
            while len(in_flight) < MAX_WORKERS and submit_one(executor):
                pass

    manifest = refresh_outputs(
        snapshot, horses, pages, roster_names, roster_sha, snapshot_sha, all_key_counts, run_started, environment_blocked
    )
    terminal = len([page for page in page_records_for_manifest(horses, pages) if page.get("fetch_status") != "pending"])
    manifest["pages_terminal_count"] = terminal
    manifest["pages_cached_before_run"] = completed_before
    manifest["pages_processed_this_run"] = processed_this_run
    manifest["unattempted_pages"] = len(horses) - terminal
    manifest["collection_complete"] = all(
        page.get("fetch_status") == "ok" for page in page_records_for_manifest(horses, pages)
    )
    atomic_write(MANIFEST_PATH, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    write_checkpoint(checkpoint)
    return manifest


def remote_fetch_with_attempt_budget(horse_id: str, remaining_attempts: int, attempts_already: int) -> dict:
    if remaining_attempts <= 0:
        return {
            "horse_id": horse_id,
            "url": expected_url(horse_id),
            "attempts": 0,
            "fetch_status": "request_failed",
            "errors": [{"error": "No request attempts remain"}],
        }
    result = remote_fetch(horse_id, remaining_attempts)
    result["attempts_this_run"] = int(result.get("attempts", 0))
    result["attempts"] = attempts_already + result["attempts_this_run"]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-only", action="store_true", help="Create/verify the immutable target snapshot only")
    args = parser.parse_args()
    HERE.mkdir(parents=True, exist_ok=True)
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    PAGE_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot, snapshot_sha = prepare_snapshot()
    result = run_collection(snapshot, snapshot_sha, args.snapshot_only)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
