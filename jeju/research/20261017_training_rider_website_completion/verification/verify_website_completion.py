#!/usr/bin/env python3
"""Independent, read-only verification for the 2026-10-17 rider completion."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import hashlib
from itertools import zip_longest
import json
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
TASK = HERE.parent
PROJECT = TASK.parents[2]
DEFAULT_DB = PROJECT / "jeju/data/jeju_native_core.sqlite3"
DEFAULT_PLAN = TASK / "plan.jsonl"
DEFAULT_COLLECTION = TASK / "collection"
DEFAULT_COLLECTION_MANIFEST = DEFAULT_COLLECTION / "manifest.json"
DEFAULT_MANIFESTS = (
    PROJECT / "jeju/research/20261015_training_rider_unclassified_review/website/retry_website_event_evidence.json",
    PROJECT / "jeju/research/20261017_training_rider_unclassified/website_check.json",
    PROJECT / "data/research/jockey_roster_20261008/manifest.json",
)
ROSTER_DIR = PROJECT / "data/research/jockey_roster_20261008"
OLD_EVIDENCE = PROJECT / "jeju/research/20261015_training_rider_unclassified_review/website/retry_website_event_evidence.json"
SAMPLE_EVIDENCE = PROJECT / "jeju/research/20261017_training_rider_unclassified/website_check.json"
OLD_RETRY_MANIFEST = PROJECT / "jeju/research/20261015_training_rider_unclassified_review/website/retry_collection_manifest.json"
TYPES_DIR = PROJECT / "jeju/research/20261015_training_rider_types"
START_DATE = "2026-04-17"
END_DATE = "2026-10-15"
EXPECTED_TARGET_ROWS = 20_408
EXPECTED_TARGET_HORSES = 913
EXPECTED_KNOWN_UNION = 784
EXPECTED_OVERLAP = 337

ASSIGNMENT_TABLE = "daily_training_rider_type_assignments"
SOURCE_TABLE = "daily_training_api_rows"
CHANGED_FIELDS = (
    "rider_type", "type_status", "website_type", "website_label_raw",
    "website_jockey_name", "website_source_path", "website_sha256",
)
SOURCE_SNAPSHOT_FIELDS = (
    "daily_training_api_artifact_id", "prGubun_raw", "prNo_raw", "horse_id",
    "training_date", "start_time_local", "end_time_local", "duration_seconds",
)
VIEW_FIELDS = (
    "rider_type", "rider_type_status", "rider_type_on_website",
    "rider_label_on_website_raw", "website_jockey_name",
    "rider_type_website_source_path", "rider_type_website_sha256",
)
TYPE_VIEW_FIELDS = VIEW_FIELDS + ("jockey_name", "jockey_name_status")
EXPLICIT_LABELS = {
    "조": "조교사", "관": "주로조교", "생": "교육생", "트": "기수트랙라이더",
}
KNOWN_TYPES = {"기수", "조교사", "조교보", "조교승인", "기수후보생"}


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      default=lambda item: {"$bytes_hex": item.hex()} if isinstance(item, bytes) else str(item))


def rows_fingerprint(cursor) -> dict:
    """Order-independent row multiset digest, preserving duplicate sensitivity."""
    total = 0
    xor = 0
    count = 0
    for row in cursor:
        value = int.from_bytes(hashlib.sha256(canonical(list(row)).encode("utf-8")).digest(), "big")
        total = (total + value) % (1 << 256)
        xor ^= value
        count += 1
    payload = f"rows={count};sum={total:064x};xor={xor:064x}".encode("ascii")
    return {"rows": count, "sha256": hashlib.sha256(payload).hexdigest()}


def open_readonly(path: Path) -> tuple[sqlite3.Connection, Path]:
    resolved = path.resolve(strict=True)
    connection = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA foreign_keys=ON")
    require(connection.execute("PRAGMA query_only").fetchone()[0] == 1, "SQLite query_only did not enable")
    require(connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1, "SQLite foreign_keys did not enable")
    return connection, resolved


def db_file_state(path: Path) -> dict:
    result = {"database": sha256_file(path)}
    for suffix in ("-wal", "-shm"):
        side = Path(str(path) + suffix)
        result[suffix[1:]] = sha256_file(side) if side.exists() else None
    return result


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise VerificationError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
            require(isinstance(row, dict), f"JSONL record at line {line_number} is not an object")
            rows.append(row)
    return rows


def table_rows(connection: sqlite3.Connection, table: str, where: str = "", params=()):
    # All identifiers passed here come from fixed constants or sqlite_master and are quoted.
    quoted = '"' + table.replace('"', '""') + '"'
    query = f"SELECT * FROM {quoted}" + (f" WHERE {where}" if where else "")
    return connection.execute(query, params)


def official_page_url(url: str, horse_id: str) -> bool:
    try:
        parsed = urlsplit(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
    except ValueError:
        return False
    return (
        parsed.scheme == "https" and parsed.hostname == "race.kra.co.kr" and
        parsed.username is None and parsed.password is None and parsed.port is None and
        parsed.path == "/racehorse/profileTrainState.do" and
        query.get("meet") == ["2"] and query.get("hrNo") == [str(horse_id)] and
        query.get("Act") == ["02"] and query.get("Sub") == ["1"]
    )


def decode_soup(raw: bytes, content_type: str | None = None) -> tuple[BeautifulSoup, str]:
    preferred = []
    if content_type:
        match = re.search(r"charset\s*=\s*['\"]?([^;\s'\"]+)", content_type, re.I)
        if match:
            preferred.append(match.group(1).lower())
    preferred.extend(["euc-kr", "cp949", "utf-8-sig", "utf-8"])
    encodings = list(dict.fromkeys(preferred))
    last_error = None
    for encoding in encodings:
        try:
            decoded = raw.decode(encoding, errors="strict")
        except (UnicodeDecodeError, LookupError) as exc:
            last_error = exc
            continue
        soup = BeautifulSoup(decoded, "html.parser")
        text = " ".join(soup.stripped_strings)
        if "[기승자범례]" in text and "조교일자" in text:
            return soup, encoding
    if last_error:
        raise VerificationError(f"Could not strictly decode HTML: {last_error}")
    raise VerificationError("HTML did not contain the expected Korean legend and training table")


def normalized_text(cell) -> str:
    return " ".join(cell.stripped_strings)


def parse_page_rows(soup: BeautifulSoup) -> tuple[list[dict], list[str]]:
    required_headers = ("조교일자", "기승자", "입장시간", "퇴장시간", "조교시간")
    tables = []
    errors = []
    for table_index, table in enumerate(soup.find_all("table")):
        rows = table.find_all("tr")
        header_at = None
        header = None
        for index, row in enumerate(rows):
            cells = [normalized_text(cell) for cell in row.find_all(["th", "td"], recursive=False)]
            if set(required_headers).issubset(cells):
                header_at, header = index, cells
                break
        if header_at is None:
            continue
        positions = {name: header.index(name) for name in required_headers}
        parsed = []
        for index, row in enumerate(rows[header_at + 1:], start=header_at + 2):
            cells = [normalized_text(cell) for cell in row.find_all(["th", "td"], recursive=False)]
            if not cells or not any(cells):
                continue
            if len(cells) <= max(positions.values()):
                # Non-training summary rows, such as an empty-result notice.
                if any(text in " ".join(cells) for text in ("자료가 없습니다", "조회된", "없습니다")):
                    continue
                errors.append(f"table {table_index} row {index}: too few cells")
                continue
            date_text = cells[positions["조교일자"]]
            match_date = re.match(r"^\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})", date_text)
            start = cells[positions["입장시간"]]
            end = cells[positions["퇴장시간"]]
            label = cells[positions["기승자"]]
            duration_match = re.fullmatch(r"\s*(\d+)\s*분\s*", cells[positions["조교시간"]])
            time_pattern = re.compile(r"^\d{1,2}:\d{2}$")
            if not match_date or not time_pattern.fullmatch(start) or not time_pattern.fullmatch(end) or not duration_match:
                # KRA pages interleave race-day markers in the training table.
                # They are not training events and intentionally have no times.
                if label == "경주일":
                    continue
                # Data rows have a date in the first relevant cell; other footers are ignored.
                if match_date or start or end or duration_match:
                    errors.append(f"table {table_index} row {index}: malformed training row {cells}")
                continue
            year, month, day = map(int, match_date.groups())
            try:
                day_value = date(year, month, day)
            except ValueError:
                errors.append(f"table {table_index} row {index}: invalid calendar date {date_text}")
                continue
            start_hour, start_minute = map(int, start.split(":"))
            end_hour, end_minute = map(int, end.split(":"))
            if start_hour > 23 or end_hour > 23 or start_minute > 59 or end_minute > 59:
                errors.append(f"table {table_index} row {index}: invalid clock time")
                continue
            duration = int(duration_match.group(1)) * 60
            actual = ((end_hour * 60 + end_minute) - (start_hour * 60 + start_minute)) * 60
            if actual != duration:
                errors.append(f"table {table_index} row {index}: duration does not match clock interval")
                continue
            parsed.append({
                "date": day_value.isoformat(),
                "start": f"{start_hour:02d}:{start_minute:02d}",
                "end": f"{end_hour:02d}:{end_minute:02d}",
                "duration_seconds": duration,
                "label": label,
                "table_index": table_index,
                "row_index": index,
            })
        tables.append(parsed)
    require(len(tables) == 1, f"Expected one official training table; found {len(tables)}")
    require(not errors, f"Malformed training-table rows: {errors[:5]}")
    return tables[0], errors


def boundary_from_manifest(page: dict, parsed_dates: list[str]) -> dict:
    first = min(parsed_dates) if parsed_dates else None
    last = max(parsed_dates) if parsed_dates else None
    expected = page.get("page_training_dates") or page.get("training_date_boundary") or {}
    expected_first = expected.get("first", expected.get("min")) if isinstance(expected, dict) else None
    expected_last = expected.get("last", expected.get("max")) if isinstance(expected, dict) else None
    if "training_date_min" in page:
        expected_first = page["training_date_min"]
    if "training_date_max" in page:
        expected_last = page["training_date_max"]
    if "date_min" in page:
        expected_first = page["date_min"]
    if "date_max" in page:
        expected_last = page["date_max"]
    require(expected_first in (None, first), f"HTML minimum date {first} differs from manifest {expected_first}")
    require(expected_last in (None, last), f"HTML maximum date {last} differs from manifest {expected_last}")
    return {"first": first, "last": last, "manifest_first": expected_first, "manifest_last": expected_last}


def parse_official_page(path: Path, page: dict, expected_horse_id: str) -> dict:
    raw = path.read_bytes()
    expected_sha = page.get("sha256") or page.get("source_sha256")
    expected_bytes = page.get("bytes", page.get("content_length"))
    status = page.get("http_status", page.get("status"))
    url = page.get("final_url") or page.get("url") or page.get("website_page_url")
    require(str(page.get("horse_id", expected_horse_id)) == str(expected_horse_id), "Manifest horse ID mismatch")
    require(status in (200, "200"), f"Official page status is not HTTP 200: {status}")
    require(isinstance(url, str) and official_page_url(url, expected_horse_id), f"Non-official or mismatched page URL: {url}")
    original_url = page.get("url") or page.get("website_page_url")
    if original_url:
        require(official_page_url(original_url, expected_horse_id), f"Original URL identity mismatch: {original_url}")
    require(isinstance(expected_sha, str) and re.fullmatch(r"[0-9a-f]{64}", expected_sha), "Manifest SHA-256 missing or malformed")
    actual_sha = hashlib.sha256(raw).hexdigest()
    require(actual_sha == expected_sha, f"HTML SHA mismatch for horse {expected_horse_id}")
    require(expected_bytes in (None, len(raw)), f"HTML byte length mismatch for horse {expected_horse_id}")
    content_type = page.get("content_type")
    soup, encoding = decode_soup(raw, content_type)
    hidden = {x.get("name"): x.get("value") for x in soup.select("input[name]")}
    require(hidden.get("hrNo") == str(expected_horse_id), f"Hidden official horse ID does not match {expected_horse_id}")
    require(hidden.get("meet") == "2", f"Hidden page meet is not Jeju for horse {expected_horse_id}")
    text = " ".join(soup.stripped_strings)
    require("최근 6개월간 조교자료입니다." in text, f"Six-month notice missing for horse {expected_horse_id}")
    require(all(token in text for token in (
        "[기승자범례]", "이름:기수명", "조:조교사", "관:주로조교", "생:교육생", "이름(트):기수트랙라이더"
    )), f"Explicit official rider legend incomplete for horse {expected_horse_id}")
    rows, _ = parse_page_rows(soup)
    expected_row_count = page.get("training_row_count", page.get("website_training_row_count"))
    require(expected_row_count in (None, len(rows)),
            f"Parsed training-row count {len(rows)} differs from manifest {expected_row_count} for horse {expected_horse_id}")
    boundary = boundary_from_manifest(page, [row["date"] for row in rows])
    return {"horse_id": str(expected_horse_id), "path": str(path), "sha256": actual_sha,
            "bytes": len(raw), "url": url, "encoding": encoding, "rows": rows,
            "boundary": boundary, "legend_verified": True, "notice_verified": True}


def resolve_project_path(raw_path: str, allowed_roots: tuple[Path, ...]) -> Path:
    require(isinstance(raw_path, str) and raw_path, "Evidence source path missing")
    candidate = (PROJECT / raw_path).resolve(strict=True)
    require(any(candidate.is_relative_to(root.resolve()) for root in allowed_roots),
            f"Evidence HTML path is outside approved source folders: {raw_path}")
    return candidate


def load_roster() -> tuple[set[str], dict]:
    manifest_path = ROSTER_DIR / "manifest.json"
    manifest = read_json(manifest_path)
    names = set()
    meets = {}
    for meet in (1, 2, 3):
        path = ROSTER_DIR / f"api_{meet}.json"
        expected_hashes = {x["api_sha256"] for x in manifest.get("rows", [])
                           if int(x["meet_code"]) == meet}
        require(expected_hashes == {sha256_file(path)}, f"API307 roster SHA mismatch for meet {meet}")
        doc = read_json(path)
        response = doc.get("response", {})
        body = response.get("body", {})
        require(response.get("header", {}).get("resultCode") == "00", f"API307 roster meet {meet} did not return success")
        raw_items = body.get("items", {}).get("item", [])
        items = [raw_items] if isinstance(raw_items, dict) else raw_items
        require(isinstance(items, list), f"API307 roster meet {meet} items are malformed")
        require(len(items) == int(body.get("totalCount", -1)), f"API307 roster meet {meet} is incomplete")
        expected_meet_label = {1: "서울", 2: "제주", 3: "영남"}[meet]
        require(all(item.get("meet") == expected_meet_label for item in items),
                f"API307 roster meet {meet} contains labels outside the archived API response meeting")
        meet_names = {item.get("jkName") for item in items if item.get("jkName") not in (None, "", "-")}
        names.update(meet_names)
        meets[str(meet)] = {"api_file": str(path.relative_to(PROJECT)), "sha256": sha256_file(path),
                            "rows": len(items), "distinct_names": len(meet_names)}
    return names, {"manifest": str(manifest_path.relative_to(PROJECT)),
                   "manifest_sha256": sha256_file(manifest_path), "name_union_count": len(names), "meets": meets}


def classify_label(label: str, roster_names: set[str]) -> tuple[str, str | None, str]:
    value = " ".join((label or "").split())
    if value in ("", "-", "외", "경주일"):
        return "미분류", None, "unclassified_website_label"
    if value in ("조", "관", "생"):
        return EXPLICIT_LABELS[value], None, "explicit_legend_marker"
    match = re.fullmatch(r"(.+?)\((관|조|생|트)\)", value)
    if match:
        name, marker = match.groups()
        return EXPLICIT_LABELS[marker], None, "explicit_legend_marker"
    if value in roster_names:
        return "기수", value, "bare_name_api307_roster"
    return "미분류", None, "unclassified_bare_name_not_in_api307_roster"


def minute_key(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*\d{4}-\d{2}-\d{2}[ T](\d{1,2}):(\d{2}):(\d{2})\s*", value)
    if not match:
        return None
    hour, minute, second = map(int, match.groups())
    if hour > 23 or minute > 59 or second != 0:
        return None
    return f"{hour:02d}:{minute:02d}"


def html_key(horse_id: str, row: dict) -> tuple:
    return (str(horse_id), row["date"], row["start"], row["end"], int(row["duration_seconds"]))


def source_key(row: sqlite3.Row) -> tuple | None:
    start = minute_key(row["start_time_local"])
    end = minute_key(row["end_time_local"])
    if not start or not end or row["duration_seconds"] is None:
        return None
    return (str(row["horse_id"]), str(row["training_date"]), start, end, int(row["duration_seconds"]))


def ensure_target_pages(connection: sqlite3.Connection, pages: list[dict], snapshot_rows: list[dict]) -> tuple[set[str], dict]:
    rows = connection.execute("""SELECT DISTINCT d.horse_id
        FROM daily_training_api_rows d
        JOIN daily_training_rider_type_values v USING(daily_training_api_row_id)
        WHERE d.training_date BETWEEN ? AND ? AND d.prGubun_raw='-' AND v.rider_type='미분류'
        ORDER BY d.horse_id""", (START_DATE, END_DATE)).fetchall()
    expected_ids = {str(row[0]) for row in rows}
    page_ids = [str(page.get("horse_id")) for page in pages]
    require(len(page_ids) == len(set(page_ids)), "Collection manifest repeats horse IDs")
    require(len(expected_ids) == EXPECTED_TARGET_HORSES,
            f"Target unknown horses changed: expected {EXPECTED_TARGET_HORSES}, found {len(expected_ids)}")
    require(set(page_ids) == expected_ids,
            f"Collection horse coverage differs: missing={len(expected_ids-set(page_ids))}, extra={len(set(page_ids)-expected_ids)}")
    source_count = connection.execute("""SELECT COUNT(*)
        FROM daily_training_api_rows d
        JOIN daily_training_rider_type_values v USING(daily_training_api_row_id)
        WHERE d.training_date BETWEEN ? AND ? AND d.prGubun_raw='-' AND v.rider_type='미분류'""",
        (START_DATE, END_DATE)).fetchone()[0]
    require(source_count == EXPECTED_TARGET_ROWS,
            f"Target unknown row count changed: expected {EXPECTED_TARGET_ROWS}, found {source_count}")
    if snapshot_rows:
        snapshot_ids = [int(row.get("row_id", -1)) for row in snapshot_rows]
        require(len(snapshot_ids) == len(set(snapshot_ids)), "Target snapshot repeats source row IDs")
        live_targets = {}
        raw_assignments = connection.execute("""SELECT * FROM daily_training_rider_type_assignments
            WHERE rider_type='미분류' AND training_date BETWEEN ? AND ?
            ORDER BY daily_training_api_row_id""", (START_DATE, END_DATE)).fetchall()
        for assignment in raw_assignments:
            row_id = int(assignment["daily_training_api_row_id"])
            source = connection.execute("SELECT * FROM daily_training_api_rows WHERE daily_training_api_row_id=?",
                                       (row_id,)).fetchone()
            require(source is not None, f"Target assignment {row_id} has no source row")
            live_targets[row_id] = {"row_id": row_id, "assignment": dict(assignment), "source": dict(source)}
        require(set(snapshot_ids) == set(live_targets), "Target snapshot IDs differ from current source DB")
        snapshot_by_id = {int(row["row_id"]): row for row in snapshot_rows}
        for row_id, live_row in live_targets.items():
            require(snapshot_by_id[row_id] == live_row, f"Target snapshot content differs from source DB at row {row_id}")
        require(len(live_targets) == EXPECTED_TARGET_ROWS,
                f"Raw assignment target rows changed: expected {EXPECTED_TARGET_ROWS}, found {len(live_targets)}")
    return expected_ids, {"target_start": START_DATE, "target_end": END_DATE,
                          "unclassified_rows": source_count, "distinct_horses": len(expected_ids),
                          "manifest_horses": len(page_ids), "complete_page_coverage": True,
                          "snapshot_rows_verified": len(snapshot_rows)}


def load_collection_manifest(path: Path) -> tuple[list[dict], dict, dict, list[dict]]:
    document = read_json(path)
    if isinstance(document.get("artifacts"), dict) and document["artifacts"].get("page_manifest_jsonl"):
        require(document.get("collection_complete") is True, "Official page collection is not complete")
        require(document.get("target_horse_count") == EXPECTED_TARGET_HORSES,
                "Collection manifest target horse count differs from 913")
        require(document.get("target_assignment_row_count") == EXPECTED_TARGET_ROWS,
                "Collection manifest target row count differs from 20,408")
        page_manifest_path = (PROJECT / document["artifacts"]["page_manifest_jsonl"]).resolve(strict=True)
        require(page_manifest_path.is_relative_to(DEFAULT_COLLECTION.resolve()),
                "Page manifest JSONL is outside the task collection directory")
        pages = read_jsonl(page_manifest_path)
        snapshot_path = (PROJECT / document["target_snapshot_path"]).resolve(strict=True)
        require(snapshot_path.is_relative_to(DEFAULT_COLLECTION.resolve()),
                "Target snapshot is outside the task collection directory")
        snapshot_raw = snapshot_path.read_bytes()
        snapshot_sha = hashlib.sha256(snapshot_raw).hexdigest()
        require(snapshot_sha == document.get("target_snapshot_sha256"), "Target snapshot SHA mismatch")
        snapshot_rows = read_jsonl(snapshot_path)
        require(len(snapshot_rows) == EXPECTED_TARGET_ROWS,
                f"Target snapshot has {len(snapshot_rows)} rows, expected {EXPECTED_TARGET_ROWS}")
        page_status_counts = document.get("page_status_counts", {})
        require(page_status_counts == {"ok": EXPECTED_TARGET_HORSES},
                f"Not all official pages succeeded: {page_status_counts}")
        require(document.get("page_count") == EXPECTED_TARGET_HORSES and len(pages) == EXPECTED_TARGET_HORSES,
                "Collection page count differs from 913")
        summary = {"manifest_path": str(path), "manifest_sha256": sha256_file(path),
                   "page_manifest_path": str(page_manifest_path),
                   "page_manifest_sha256": sha256_file(page_manifest_path),
                   "collection_complete": True, "page_status_counts": page_status_counts,
                   "candidate_row_count": document.get("candidate_row_count"),
                   "candidate_type_counts": document.get("candidate_type_counts"),
                   "target_snapshot_path": str(snapshot_path), "target_snapshot_sha256": snapshot_sha,
                   "target_snapshot_row_count": len(snapshot_rows)}
    else:
        pages = document.get("pages", document.get("results", document.get("horses")))
        snapshot_rows = []
        summary = {"manifest_path": str(path), "manifest_sha256": sha256_file(path)}
    require(isinstance(pages, list), f"Collection manifest has no pages list: {path}")
    normalized = []
    for page in pages:
        require(isinstance(page, dict), "Collection manifest page is not an object")
        require(page.get("fetch_status", "ok") == "ok", f"Page fetch did not succeed: {page.get('horse_id')}")
        require(page.get("page_valid", True) is True, f"Page failed collector validation: {page.get('horse_id')}")
        normalized.append(page)
    return normalized, document, summary, snapshot_rows


def normalize_plan(row: dict) -> dict:
    require("daily_training_api_row_id" in row, "Plan row missing daily_training_api_row_id")
    row_id = int(row["daily_training_api_row_id"])
    require(row_id > 0, "Plan row ID must be positive")
    old = row.get("old")
    new = row.get("new")
    require(isinstance(old, dict) and isinstance(new, dict), f"Plan row {row_id} missing full old/new assignments")
    result = {"id": row_id, "old": old, "new": new,
              "old_type": row.get("old_type"), "new_type": row.get("new_type"),
              "old_status": row.get("old_status"), "new_status": row.get("new_status"),
              "evidence_status": row.get("evidence_status"), "url": row.get("url")}
    for field in SOURCE_SNAPSHOT_FIELDS:
        result[field] = row.get(field)
    for field in CHANGED_FIELDS[2:]:
        result[field] = row.get(field)
    return result


def validate_plan_flat_fields(entry: dict) -> None:
    row_id = entry["id"]
    old, new = entry["old"], entry["new"]
    require(entry["old_type"] == old.get("rider_type") and entry["old_status"] == old.get("type_status"),
            f"Plan row {row_id}: flat old classification differs from nested snapshot")
    require(entry["new_type"] == new.get("rider_type") and entry["new_status"] == new.get("type_status"),
            f"Plan row {row_id}: flat new classification differs from nested assignment")
    for field in SOURCE_SNAPSHOT_FIELDS:
        require(entry[field] == old.get(field) == new.get(field),
                f"Plan row {row_id}: source snapshot changed in {field}")
    for field in CHANGED_FIELDS[2:]:
        require(entry[field] == new.get(field), f"Plan row {row_id}: flat website field differs for {field}")
    require(entry["evidence_status"] == "exact_event_official_website",
            f"Plan row {row_id}: evidence status is not exact event")
    require(entry["new_status"] == "website_same_event_type", f"Plan row {row_id}: unexpected type status")
    require(entry["old_type"] == "미분류" and entry["new_type"] != "미분류",
            f"Plan row {row_id}: only unclassified rows can receive a new website type")
    require(entry["prGubun_raw"] == "-", f"Plan row {row_id}: explicit API category cannot be overwritten")
    require(START_DATE <= str(entry["training_date"]) <= END_DATE,
            f"Plan row {row_id}: event date outside the approved window")


def plan_evidence_path(row: dict) -> str:
    return row.get("website_source_path") or row.get("source_path") or ""


def page_record_for_plan(entry: dict, page_index: dict, allowed_roots: tuple[Path, ...]) -> dict:
    raw_path = plan_evidence_path(entry["new"])
    if not raw_path:
        raw_path = entry.get("website_source_path") or ""
    path = resolve_project_path(raw_path, allowed_roots)
    digest = entry["new"].get("website_sha256") or entry.get("website_sha256")
    url = entry["url"]
    horse_id = str(entry["horse_id"])
    key = (str(path), str(digest), horse_id)
    if key in page_index:
        return page_index[key]
    record = {"horse_id": horse_id, "source_path": raw_path, "sha256": digest,
              "http_status": 200, "url": url, "final_url": url}
    parsed = parse_official_page(path, record, horse_id)
    page_index[key] = parsed
    return parsed


def roster_page_classes(pages: list[dict], roster_names: set[str]) -> tuple[dict, Counter]:
    parsed_pages = {}
    label_counts = Counter()
    for page in pages:
        horse_id = str(page["horse_id"])
        raw_path = page.get("source_path") or page.get("path")
        require(raw_path, f"Page {horse_id} has no saved source path")
        path = resolve_project_path(raw_path, (
            DEFAULT_COLLECTION, TASK / "collection", OLD_EVIDENCE.parent / "retry_raw_html",
            SAMPLE_EVIDENCE.parent / "html",
        ))
        p = parse_official_page(path, page, horse_id)
        p["source_path"] = raw_path
        p["row_index"] = defaultdict(list)
        for event in p["rows"]:
            kind, jockey, reason = classify_label(event["label"], roster_names)
            event.update({"kind": kind, "jockey_name": jockey, "label_reason": reason})
            key = html_key(horse_id, event)
            p["row_index"][key].append(event)
            label_counts[kind] += 1
        parsed_pages[horse_id] = p
    return parsed_pages, label_counts


def known_prior_union() -> dict:
    old = read_json(OLD_EVIDENCE)
    recent = read_json(SAMPLE_EVIDENCE)
    old_manifest = read_json(OLD_RETRY_MANIFEST)
    old_rows = old.get("evidence_rows", [])
    recent_rows = recent.get("observations", [])
    old_ids = {int(row.get("row_id", row.get("daily_training_api_row_id", 0))) for row in old_rows}
    recent_ids = {int(row.get("row_id", row.get("daily_training_api_row_id", 0))) for row in recent_rows}
    require(len(old_ids) == 534, f"Prior October 15 evidence count changed: {len(old_ids)}")
    require(len(recent_ids) == 587, f"Prior October 17 sample evidence count changed: {len(recent_ids)}")
    overlap = old_ids & recent_ids
    union = old_ids | recent_ids
    require(len(overlap) == EXPECTED_OVERLAP, f"Prior sample overlap changed: {len(overlap)}")
    require(len(union) == EXPECTED_KNOWN_UNION, f"Prior sample union changed: {len(union)}")
    labels = {}
    for row in old_rows:
        labels[int(row.get("row_id", row.get("daily_training_api_row_id", 0)))] = row.get("website_name_raw", row.get("website_label_raw"))
    for row in recent_rows:
        rid = int(row.get("row_id", row.get("daily_training_api_row_id", 0)))
        label = row.get("website_label", row.get("website_name_raw"))
        if rid in labels:
            require(labels[rid] == label, f"Prior website evidence conflicts for row {rid}")
        labels[rid] = label
    old_pages = old_manifest.get("pages", [])
    recent_pages = recent.get("pages", [])
    require(len(old_pages) == 8 and len(recent_pages) == 8,
            "Prior evidence page manifests changed from the two independently sampled sets of eight")
    return {"old_rows": old_ids, "recent_rows": recent_ids, "overlap": overlap,
            "union": union, "labels": labels, "old_evidence_rows": old_rows,
            "recent_evidence_rows": recent_rows, "old_pages": old_pages,
            "recent_pages": recent_pages}


def prior_event_key(row: dict, source_kind: str) -> tuple:
    if source_kind == "oct15":
        horse_id = str(row["horse_id"])
        event_date = str(row["training_date"])
        start, end = str(row["website_start_time"]), str(row["website_end_time"])
        duration = int(row["website_duration_minutes"]) * 60
    else:
        horse_id = str(row["horse_id"])
        event_date = str(row["date"])
        start, end = str(row["start"]), str(row["end"])
        duration = int(row["minutes"]) * 60
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_date) is not None,
            f"Prior {source_kind} evidence has malformed event date")
    require(re.fullmatch(r"\d{2}:\d{2}", start) is not None and
            re.fullmatch(r"\d{2}:\d{2}", end) is not None,
            f"Prior {source_kind} evidence has malformed event time")
    return (horse_id, event_date, start, end, duration)


def parse_prior_evidence(prior: dict, source_by_key: dict, target_by_id: dict,
                         roster_names: set[str]) -> tuple[dict, set[int], dict]:
    """Reparse the original 534 + 587 row evidence from its saved official HTML."""
    page_sets = {
        "oct15": (prior["old_pages"], prior["old_evidence_rows"],
                  OLD_EVIDENCE.parent / "retry_raw_html"),
        "oct17": (prior["recent_pages"], prior["recent_evidence_rows"],
                  SAMPLE_EVIDENCE.parent / "html"),
    }
    parsed_by_source_horse = {}
    page_records = 0
    for source_kind, (records, _, allowed_root) in page_sets.items():
        horse_records = {}
        for record in records:
            horse_id = str(record["horse_id"])
            require(horse_id not in horse_records,
                    f"Prior {source_kind} page manifest repeats horse {horse_id}")
            raw_path = record.get("source_path") or record.get("path")
            require(raw_path, f"Prior {source_kind} page missing source path for horse {horse_id}")
            path = resolve_project_path(raw_path, (allowed_root,))
            parsed = parse_official_page(path, record, horse_id)
            parsed["source_path"] = raw_path
            parsed["row_index"] = defaultdict(list)
            for event in parsed["rows"]:
                kind, jockey, reason = classify_label(event["label"], roster_names)
                event.update({"kind": kind, "jockey_name": jockey, "label_reason": reason})
                parsed["row_index"][html_key(horse_id, event)].append(event)
            horse_records[horse_id] = parsed
            page_records += 1
        parsed_by_source_horse[source_kind] = horse_records

    support_by_id = defaultdict(list)
    ambiguous_ids = set()
    status_counts = Counter()
    for source_kind, (_, evidence_rows, _) in page_sets.items():
        pages = parsed_by_source_horse[source_kind]
        for evidence in evidence_rows:
            row_id = int(evidence.get("row_id", evidence.get("daily_training_api_row_id", 0)))
            horse_id = str(evidence["horse_id"])
            key = prior_event_key(evidence, source_kind)
            source_rows = source_by_key.get(key, [])
            target = target_by_id.get(row_id)
            if target is None or source_key(target) != key:
                status_counts["not_current_target_or_source_key_changed"] += 1
                continue
            if len(source_rows) != 1 or int(source_rows[0]["daily_training_api_row_id"]) != row_id:
                ambiguous_ids.add(row_id)
                status_counts["ambiguous_source_key"] += 1
                continue
            page = pages.get(horse_id)
            require(page is not None, f"Prior {source_kind} evidence has no official page for horse {horse_id}")
            require(evidence.get("source_path") == page["source_path"],
                    f"Prior {source_kind} row {row_id} source path differs from its page manifest")
            evidence_sha = evidence.get("source_sha256")
            if not evidence_sha:
                evidence_sha = evidence.get("source_sha256", evidence.get("website_sha256"))
            require(evidence_sha == page["sha256"],
                    f"Prior {source_kind} row {row_id} SHA differs from its official page")
            evidence_url = evidence.get("website_page_url") or page["url"]
            require(evidence_url == page["url"],
                    f"Prior {source_kind} row {row_id} URL differs from its official page")
            events = page["row_index"].get(key, [])
            if len(events) > 1:
                ambiguous_ids.add(row_id)
                status_counts["ambiguous_html_key"] += 1
                continue
            if not events:
                status_counts["missing_html_key"] += 1
                continue
            event = events[0]
            saved_label = evidence.get("website_name_raw", evidence.get("website_label"))
            require(saved_label == event["label"],
                    f"Prior {source_kind} row {row_id} saved label differs from independently parsed HTML")
            saved_type = evidence.get("website_type_candidate", evidence.get("candidate_type"))
            require(saved_type == event["kind"],
                    f"Prior {source_kind} row {row_id} saved type differs from independently parsed legend/API roster")
            if event["kind"] == "미분류":
                status_counts["direct_but_unclassified_label"] += 1
                continue
            support_by_id[row_id].append({
                "horse_id": horse_id, "type": event["kind"], "label": event["label"],
                "jockey_name": event["jockey_name"], "website_type": event["kind"],
                "website_sha256": page["sha256"], "website_source_path": page["source_path"],
                "url": page["url"], "date": key[1], "start": key[2], "end": key[3],
                "duration_seconds": key[4], "reason": event["label_reason"],
                "evidence_source_kind": source_kind,
            })
            status_counts[f"unique_{source_kind}"] += 1

    expected = {}
    for row_id, evidence_items in support_by_id.items():
        classifications = {(item["type"], item["label"], item["jockey_name"]) for item in evidence_items}
        if len(classifications) != 1:
            ambiguous_ids.add(row_id)
            status_counts["conflicting_prior_snapshots"] += 1
            continue
        primary = dict(evidence_items[0])
        primary["evidence_sources"] = [
            {"website_sha256": item["website_sha256"],
             "website_source_path": item["website_source_path"], "url": item["url"],
             "label": item["label"], "type": item["type"],
             "jockey_name": item["jockey_name"]}
            for item in evidence_items
        ]
        expected[row_id] = primary
    for row_id in ambiguous_ids:
        expected.pop(row_id, None)
    return expected, ambiguous_ids, {"prior_html_pages_reparsed": page_records,
                                    "row_evidence_status_counts": dict(status_counts),
                                    "direct_prior_candidates": len(expected),
                                    "ambiguous_prior_row_ids": sorted(ambiguous_ids)}


def merge_expected_updates(current: dict, prior: dict, ambiguous_ids: set[int]) -> dict:
    merged = {row_id: dict(value) for row_id, value in current.items()}
    for row_id, prior_value in prior.items():
        if row_id not in merged:
            merged[row_id] = dict(prior_value)
            continue
        current_value = merged[row_id]
        if (current_value["type"], current_value["label"], current_value["jockey_name"]) != (
                prior_value["type"], prior_value["label"], prior_value["jockey_name"]):
            ambiguous_ids.add(row_id)
            continue
        current_value["evidence_sources"] = current_value.get("evidence_sources", []) + prior_value.get("evidence_sources", [])
    for row_id in ambiguous_ids:
        merged.pop(row_id, None)
    return merged


def load_source_index(connection: sqlite3.Connection, horse_ids: set[str]) -> tuple[dict, dict, int]:
    all_by_key = defaultdict(list)
    target_by_id = {}
    unknown_records = 0
    horse_list = sorted(horse_ids)
    # Keep each IN clause under SQLite's traditional 999-parameter limit.
    for start in range(0, len(horse_list), 700):
        chunk = horse_list[start:start + 700]
        placeholders = ",".join("?" for _ in chunk)
        rows = connection.execute(f"""SELECT d.daily_training_api_row_id,d.daily_training_api_artifact_id,
                d.prGubun_raw,d.prNo_raw,d.horse_id,d.training_date,d.start_time_local,d.end_time_local,d.duration_seconds,
                a.rider_type AS stored_type,a.type_status AS stored_status,
                a.website_type,a.website_label_raw,a.website_jockey_name,a.website_source_path,a.website_sha256,
                v.rider_type AS guarded_type, v.rider_type_status AS guarded_status
            FROM daily_training_api_rows d
            JOIN daily_training_rider_type_assignments a USING(daily_training_api_row_id)
            JOIN daily_training_rider_type_values v USING(daily_training_api_row_id)
            WHERE d.training_date BETWEEN ? AND ? AND d.horse_id IN ({placeholders})""",
            (START_DATE, END_DATE, *chunk)).fetchall()
        for row in rows:
            key = source_key(row)
            if key:
                all_by_key[key].append(row)
            if row["prGubun_raw"] == "-" and row["guarded_type"] == "미분류":
                unknown_records += 1
                target_by_id[int(row["daily_training_api_row_id"])] = row
    return all_by_key, target_by_id, unknown_records


def derive_expected_updates(pages_by_id: dict, source_by_key: dict, target_by_id: dict,
                           roster_names: set[str]) -> tuple[dict, list[dict], Counter]:
    expected = {}
    ambiguities = []
    unclassified_labels = Counter()
    for horse_id, page in pages_by_id.items():
        for key, events in page["row_index"].items():
            if not (START_DATE <= key[1] <= END_DATE):
                continue
            source_rows = source_by_key.get(key, [])
            if len(events) > 1 or len(source_rows) > 1:
                ambiguities.append({"key": list(key), "html_rows": len(events),
                                    "source_row_ids": [int(r["daily_training_api_row_id"]) for r in source_rows]})
                continue
            if len(events) != 1 or len(source_rows) != 1:
                continue
            source = source_rows[0]
            row_id = int(source["daily_training_api_row_id"])
            if row_id not in target_by_id:
                continue
            event = events[0]
            if event["kind"] == "미분류":
                unclassified_labels[event["label_reason"]] += 1
                continue
            expected[row_id] = {"horse_id": horse_id, "type": event["kind"], "label": event["label"],
                                "jockey_name": event["jockey_name"], "website_type": event["kind"],
                                "website_sha256": page["sha256"], "website_source_path": page["source_path"],
                                "url": page["url"], "date": key[1], "start": key[2], "end": key[3],
                                "duration_seconds": key[4], "reason": event["label_reason"],
                                "evidence_sources": [{"website_sha256": page["sha256"],
                                                      "website_source_path": page["source_path"],
                                                      "url": page["url"], "label": event["label"],
                                                      "type": event["kind"],
                                                      "jockey_name": event["jockey_name"]}]}
    return expected, ambiguities, unclassified_labels


def read_plan_context(plan_path: Path) -> tuple[list[dict], dict, str]:
    plan_path = plan_path.resolve(strict=True)
    require(plan_path.is_relative_to(TASK.resolve()), "Plan file must remain inside the task folder")
    plan_sha = sha256_file(plan_path)
    summary_path = plan_path.with_suffix(".summary.json")
    require(summary_path.is_file(), f"Plan summary missing: {summary_path}")
    summary = read_json(summary_path)
    require(summary.get("plan_sha256") == plan_sha, "Plan summary SHA does not match JSONL")
    rows = [normalize_plan(row) for row in read_jsonl(plan_path)]
    ids = [row["id"] for row in rows]
    require(len(ids) == len(set(ids)), "Plan repeats assignment row IDs")
    for row in rows:
        validate_plan_flat_fields(row)
    return rows, summary, plan_sha


def verify_roster_labels(expected: dict, rows: list[dict], roster_names: set[str]) -> None:
    by_id = {row["id"]: row for row in rows}
    for row_id, assignment in expected.items():
        row = by_id.get(row_id)
        if not row:
            continue
        kind, jockey, reason = classify_label(assignment["label"], roster_names)
        require((row["new_type"], row["new"].get("website_jockey_name")) == (kind, jockey),
                f"Plan row {row_id}: label does not independently support type/name")
        require(row["new"].get("website_type") == kind and row["new"].get("website_label_raw") == assignment["label"],
                f"Plan row {row_id}: website assignment differs from exact HTML row")
        sources = assignment.get("evidence_sources", [])
        require(any(source.get("website_sha256") == row["new"].get("website_sha256") and
                    source.get("website_source_path") == row["new"].get("website_source_path") and
                    source.get("url") == row["url"] and source.get("label") == assignment["label"] and
                    source.get("type") == kind and source.get("jockey_name") == jockey
                    for source in sources),
                f"Plan row {row_id}: provenance does not match any independently verified HTML page")
        require(reason in ("explicit_legend_marker", "bare_name_api307_roster"),
                f"Plan row {row_id}: unsupported label classification")


def verify_preapply(args) -> dict:
    require(args.collection_manifest is not None, "--collection-manifest is required for preapply")
    plan_rows, summary, plan_sha = read_plan_context(args.plan)
    connection, db_path = open_readonly(args.db)
    before = db_file_state(db_path)
    pages, collection_manifest, collection_summary, snapshot_rows = load_collection_manifest(
        args.collection_manifest.resolve(strict=True))
    expected_horse_ids, target_summary = ensure_target_pages(connection, pages, snapshot_rows)
    roster_names, roster_summary = load_roster()
    pages_by_id, page_type_counts = roster_page_classes(pages, roster_names)
    source_by_key, target_by_id, matched_window_unknown_count = load_source_index(connection, expected_horse_ids)
    current_expected, ambiguities, unclassified_labels = derive_expected_updates(
        pages_by_id, source_by_key, target_by_id, roster_names)
    if collection_manifest.get("candidate_row_count") is not None:
        require(collection_manifest["candidate_row_count"] == len(current_expected),
                "Independent candidate count differs from collection manifest")
    if collection_manifest.get("candidate_type_counts") is not None:
        expected_type_counts = dict(Counter(row["type"] for row in current_expected.values()))
        require(collection_manifest["candidate_type_counts"] == expected_type_counts,
                "Independent candidate type counts differ from collection manifest")
    prior = known_prior_union()
    prior_expected, prior_ambiguous_ids, prior_parse_summary = parse_prior_evidence(
        prior, source_by_key, target_by_id, roster_names)
    ambiguous_ids = set(prior_ambiguous_ids)
    for item in ambiguities:
        ambiguous_ids.update(int(row_id) for row_id in item["source_row_ids"] if int(row_id) in target_by_id)
    expected = merge_expected_updates(current_expected, prior_expected, ambiguous_ids)
    ambiguity_summary = {"ambiguous_exact_event_keys": len(ambiguities),
                         "ambiguous_target_row_ids": sorted(ambiguous_ids),
                         "current_collection_examples": ambiguities[:5],
                         "prior_evidence": prior_parse_summary}

    boundary_coverage = {}
    exact_updates_by_horse = Counter(str(value["horse_id"]) for value in expected.values())
    target_counts_by_horse = Counter(str(row["horse_id"]) for row in target_by_id.values())
    target_rows_by_horse = defaultdict(list)
    for row in target_by_id.values():
        target_rows_by_horse[str(row["horse_id"])].append(row)
    for horse_id, page in pages_by_id.items():
        first = page["boundary"]["first"]
        last = page["boundary"]["last"]
        source_rows = target_rows_by_horse[horse_id]
        before_visible = sum(1 for row in source_rows if first and row["training_date"] < first)
        after_visible = sum(1 for row in source_rows if last and row["training_date"] > last)
        boundary_coverage[horse_id] = {
            "displayed_first_date": first,
            "displayed_last_date": last,
            "target_unclassified_rows_in_window": target_counts_by_horse[horse_id],
            "direct_updates": exact_updates_by_horse[horse_id],
            "target_rows_before_first_displayed_date": before_visible,
            "target_rows_after_last_displayed_date": after_visible,
        }

    plan_by_id = {row["id"]: row for row in plan_rows}
    require(set(plan_by_id) == set(expected),
            f"Plan candidate set differs from independently derived set: missing={len(set(expected)-set(plan_by_id))}, extra={len(set(plan_by_id)-set(expected))}")
    verify_roster_labels(expected, plan_rows, roster_names)

    # Independently check every plan snapshot against the read-only source DB and guarded view.
    source_snapshot_mismatches = []
    for row in plan_rows:
        source = connection.execute("SELECT * FROM daily_training_api_rows WHERE daily_training_api_row_id=?",
                                    (row["id"],)).fetchone()
        assignment = connection.execute(
            "SELECT * FROM daily_training_rider_type_assignments WHERE daily_training_api_row_id=?",
            (row["id"],)).fetchone()
        guarded = connection.execute(
            "SELECT rider_type,rider_type_status FROM daily_training_rider_type_values WHERE daily_training_api_row_id=?",
            (row["id"],)).fetchone()
        require(source is not None and assignment is not None and guarded is not None,
                f"Plan row {row['id']} absent from source database")
        source_dict = dict(source)
        assignment_dict = dict(assignment)
        if assignment_dict != row["old"]:
            source_snapshot_mismatches.append(row["id"])
        for field in SOURCE_SNAPSHOT_FIELDS:
            if row[field] != source_dict[field] or assignment_dict[field] != source_dict[field]:
                source_snapshot_mismatches.append(row["id"])
        require(guarded["rider_type"] == "미분류", f"Plan row {row['id']} is no longer guarded-unclassified")
        require(source["prGubun_raw"] == "-", f"Plan row {row['id']} has a known raw API category")
    require(not source_snapshot_mismatches,
            f"Source/assignment snapshots differ from plan for rows {len(set(source_snapshot_mismatches))}")

    actual_target = connection.execute("""SELECT COUNT(*) FROM daily_training_api_rows d
        JOIN daily_training_rider_type_values v USING(daily_training_api_row_id)
        WHERE d.training_date BETWEEN ? AND ? AND d.prGubun_raw='-' AND v.rider_type='미분류'""",
        (START_DATE, END_DATE)).fetchone()[0]
    db_sha = before["database"]
    require(summary.get("database_sha256") == db_sha, "Plan database SHA does not match current database")
    require(len(plan_rows) == int(summary.get("candidate_rows", -1)), "Plan row count differs from loader summary")
    connection.close()
    after = db_file_state(db_path)
    require(before == after, "Database/WAL/SHM changed during read-only preapply verification")
    return {
        "verification": "independent_beautifulsoup_website_completion_preapply",
        "passed": True,
        "phase": "preapply",
        "read_only": True,
        "query_only": True,
        "database": str(db_path),
        "database_sha256": db_sha,
        "plan": str(args.plan.resolve()),
        "plan_sha256": plan_sha,
        "plan_summary_sha256": sha256_file(args.plan.resolve().with_suffix(".summary.json")),
        "database_file_sha256_before_after": {"before": before, "after": after},
        "target_population": target_summary,
        "source_unknown_rows_for_collected_horses_in_window": matched_window_unknown_count,
        "collection_pages": {"count": len(pages), "distinct_horse_ids": len(pages_by_id),
                             "manifest": collection_summary,
                             "page_type_counts": dict(page_type_counts),
                             "six_month_notice_pages": len(pages_by_id),
                             "explicit_complete_legend_pages": len(pages_by_id),
                             "boundaries": {hid: page["boundary"] for hid, page in pages_by_id.items()},
                             "per_horse_coverage": boundary_coverage},
        "api307_roster": roster_summary,
        "bare_name_classification": {"planned_jockey_names": sum(1 for row in plan_rows if row["new_type"] == "기수"),
                                     "roster_verified": True},
        "prior_evidence_union": {"oct15_rows": 534, "oct17_rows": 587,
                                 "overlap": len(prior["overlap"]), "union": len(prior["union"]),
                                 "union_rows_with_unique_original_html_support": len(prior_expected),
                                 "union_rows_retained_after_ambiguity_exclusion": len(prior_expected)},
        "independently_derived_candidates": len(expected),
        "current_collection_candidates": len(current_expected),
        "plan_candidates": len(plan_rows),
        "plan_new_type_counts": dict(Counter(row["new_type"] for row in plan_rows)),
        "unclassified_website_labels": dict(unclassified_labels),
        "ambiguity_review": ambiguity_summary,
        "source_snapshot_mismatches": 0,
        "remaining_unclassified_rows_in_window": actual_target - len(plan_rows),
        "candidate_ids": sorted(plan_by_id),
        "failures": [],
    }


def schema_snapshot(connection: sqlite3.Connection) -> dict:
    return {(row["type"], row["name"]): row["sql"] for row in connection.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name")}


def table_names(connection: sqlite3.Connection) -> list[str]:
    return [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def view_names(connection: sqlite3.Connection) -> list[str]:
    return [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")]


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def table_column_names(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in connection.execute(f"PRAGMA table_info({quote_identifier(table)})")]


def compare_table_rows(baseline: sqlite3.Connection, live: sqlite3.Connection,
                       table: str) -> dict:
    """Exact streaming equality without JSON serialization or table-sized memory."""
    schema_row = baseline.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    require(schema_row is not None, f"Table definition is missing: {table}")
    table_sql = schema_row["sql"] or ""
    if re.search(r"\bWITHOUT\s+ROWID\b", table_sql, re.I):
        info = baseline.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall()
        primary = [row["name"] for row in sorted(info, key=lambda item: int(item["pk"]) or 10**9)
                   if int(row["pk"]) > 0]
        require(primary, f"WITHOUT ROWID table has no primary key: {table}")
        ordering = ",".join(quote_identifier(name) for name in primary)
    else:
        ordering = "rowid"
    query = f"SELECT * FROM {quote_identifier(table)} ORDER BY {ordering}"
    before_cursor = baseline.execute(query)
    after_cursor = live.execute(query)
    before_cursor.row_factory = None
    after_cursor.row_factory = None
    count = 0
    for before_row, after_row in zip_longest(before_cursor, after_cursor):
        require(before_row is not None and after_row is not None,
                f"Non-assignment table row count changed: {table}")
        require(before_row == after_row, f"Non-assignment table row changed: {table} at ordered row {count}")
        count += 1
    return {"rows": count, "unchanged": True, "comparison": "ordered_streaming_row_equality"}


def verify_assignment_stream(baseline: sqlite3.Connection, live: sqlite3.Connection,
                             plan_by_id: dict[int, dict]) -> dict:
    query = f"SELECT * FROM {quote_identifier(ASSIGNMENT_TABLE)} ORDER BY daily_training_api_row_id"
    before_cursor = baseline.execute(query)
    after_cursor = live.execute(query)
    before_cursor.row_factory = None
    after_cursor.row_factory = None
    columns = table_column_names(baseline, ASSIGNMENT_TABLE)
    column_index = {name: index for index, name in enumerate(columns)}
    patterns = Counter()
    candidate_count = 0
    changed_count = 0
    for before_row, after_row in zip_longest(before_cursor, after_cursor):
        require(before_row is not None and after_row is not None,
                "Assignment row count changed from before-apply backup")
        row_id = int(before_row[column_index["daily_training_api_row_id"]])
        require(row_id == int(after_row[column_index["daily_training_api_row_id"]]),
                f"Assignment row order/key changed at {row_id}")
        plan = plan_by_id.get(row_id)
        if plan is None:
            require(before_row == after_row, f"Unplanned assignment row changed: {row_id}")
            continue
        candidate_count += 1
        before = dict(zip(columns, before_row))
        after = dict(zip(columns, after_row))
        require(before == plan["old"], f"Pre-apply assignment differs from reviewed plan for row {row_id}")
        require(after == plan["new"], f"Applied assignment differs from reviewed plan for row {row_id}")
        changed = {key for key, index in column_index.items() if before_row[index] != after_row[index]}
        require(changed and changed.issubset(set(CHANGED_FIELDS)),
                f"Candidate row {row_id} changed fields outside the seven approved website/type fields: {sorted(changed)}")
        require("rider_type" in changed, f"Candidate assignment row {row_id} did not change rider_type")
        require(all(before_row[column_index[field]] == after_row[column_index[field]]
                    for field in SOURCE_SNAPSHOT_FIELDS),
                f"Source snapshot fields changed in assignment row {row_id}")
        changed_count += 1
        patterns[tuple(sorted(changed))] += 1
    require(candidate_count == len(plan_by_id),
            f"Plan candidate IDs missing from assignment table: found {candidate_count}, expected {len(plan_by_id)}")
    require(changed_count == len(plan_by_id), "Assignment changes are not exactly the reviewed candidate ID set")
    return {"changed_rows": changed_count, "candidate_rows": len(plan_by_id),
            "changed_field_patterns": {"|".join(fields): count for fields, count in sorted(patterns.items())},
            "source_snapshot_fields_unchanged": True}


def view_target_values(connection: sqlite3.Connection, view: str, ids: list[int]) -> dict[int, dict]:
    output = {}
    # SQLite in this environment supports 32,766 bind variables. One batch keeps
    # expensive nested views from being re-evaluated once per 700 candidate IDs.
    for start in range(0, len(ids), 30_000):
        chunk = ids[start:start + 30_000]
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        cursor = connection.execute(f"SELECT * FROM {quote_identifier(view)} WHERE daily_training_api_row_id IN ({placeholders})",
                                    chunk)
        for row in cursor:
            output[int(row["daily_training_api_row_id"])] = dict(row)
    return output


def verify_postapply_views(args) -> dict:
    """Read-only, candidate-scoped checks for the affected rider-type projections."""
    plan_rows, _, plan_sha = read_plan_context(args.plan)
    baseline_path = args.baseline.resolve(strict=True)
    live, db_path = open_readonly(args.db)
    baseline, baseline_path = open_readonly(baseline_path)
    live_before = db_file_state(db_path)
    baseline_before = db_file_state(baseline_path)
    plan_by_id = {row["id"]: row for row in plan_rows}
    ids = sorted(plan_by_id)

    schema_before = schema_snapshot(baseline)
    schema_after = schema_snapshot(live)
    require(schema_before == schema_after, "SQLite schema objects changed from before-apply backup")
    before_views = view_names(baseline)
    after_views = view_names(live)
    require(before_views == after_views, "View set changed")
    required_views = {"daily_training_rider_type_values", "daily_training_rider_types",
                      "daily_training_rider_types_analysis_2026", "training_current",
                      "daily_training_api_rows_analysis_2026"}
    require(required_views.issubset(set(before_views)), "Required rider-type views are missing")
    analysis_sql = schema_before.get(("view", "daily_training_api_rows_analysis_2026"), "")
    require(re.search(r"WHERE\s+r\.training_date\s*<=\s*'2026-09-19'", analysis_sql, re.I) is not None,
            "The analysis source view no longer enforces its 2026-09-19 date cutoff")

    prior = known_prior_union()
    require(prior["union"].issubset(set(ids)), "Applied plan omits the prior 784-row evidence union")
    checked_views = {}
    for view in ("daily_training_rider_type_values", "training_current"):
        before_targets = view_target_values(baseline, view, ids)
        after_targets = view_target_values(live, view, ids)
        require(before_targets.keys() == after_targets.keys(), f"Candidate view visibility changed in {view}")
        if view == "daily_training_rider_type_values":
            require(before_targets.keys() == set(ids), f"Planned candidate rows missing from view {view}")
        for row_id in sorted(before_targets):
            old_view = before_targets[row_id]
            new_view = after_targets[row_id]
            plan = plan_by_id[row_id]
            expected_type = plan["new_type"]
            expected_jockey = plan["new"].get("website_jockey_name")
            require(old_view["rider_type"] == plan["old_type"] and
                    old_view["rider_type_status"] == plan["old_status"],
                    f"Baseline type view disagrees with reviewed old assignment for row {row_id} in {view}")
            require(new_view["rider_type"] == expected_type and
                    new_view["rider_type_status"] == plan["new_status"],
                    f"Rider-type view disagrees with plan for row {row_id} in {view}")
            if view == "daily_training_rider_type_values":
                require(new_view["rider_type_on_website"] == expected_type and
                        new_view["rider_label_on_website_raw"] == plan["new"].get("website_label_raw") and
                        new_view["website_jockey_name"] == expected_jockey and
                        new_view["rider_type_website_source_path"] == plan["new"].get("website_source_path") and
                        new_view["rider_type_website_sha256"] == plan["new"].get("website_sha256"),
                        f"Guarded website evidence view disagrees with plan for row {row_id}")
                if expected_type != "기수":
                    require(new_view["website_jockey_name"] is None,
                            f"Non-jockey website name is not NULL for row {row_id}")
            else:
                expected_view_jockey = expected_jockey if expected_type == "기수" else None
                require(new_view["jockey_name"] == expected_view_jockey,
                        f"Jockey-name policy failed in {view} for row {row_id}")
                expected_status = ("jockey_name_available" if expected_type == "기수" and expected_view_jockey
                                   else "jockey_name_unresolved" if expected_type == "기수"
                                   else "not_applicable")
                require(new_view["jockey_name_status"] == expected_status,
                        f"Jockey-name status failed in {view} for row {row_id}")
            for key in old_view:
                if key in VIEW_FIELDS or key in ("jockey_name", "jockey_name_status"):
                    continue
                require(old_view[key] == new_view[key], f"View source field {key} changed for row {row_id}")
        checked_views[view] = {"candidate_ids_expected": len(ids),
                               "candidate_ids_visible": len(before_targets),
                               "row_population_basis": "source tables and assignment key set verified separately; view SQL unchanged"}

    eligible_analysis_ids = [row_id for row_id in ids
                             if plan_by_id[row_id]["training_date"] <= "2026-09-19"]
    live.close()
    baseline.close()
    live_after = db_file_state(db_path)
    baseline_after = db_file_state(baseline_path)
    require(live_before == live_after, "Live database files changed during read-only view verification")
    require(baseline_before == baseline_after, "Backup database files changed during read-only view verification")
    return {
        "verification": "independent_website_completion_postapply_views",
        "passed": True,
        "phase": "postapply_views",
        "read_only": True,
        "query_only": True,
        "database": str(db_path),
        "baseline": str(baseline_path),
        "plan_sha256": plan_sha,
        "database_file_sha256_before_after": {"live_before": live_before, "live_after": live_after,
                                               "backup_before": baseline_before, "backup_after": baseline_after},
        "schema_and_all_view_sql_unchanged": True,
        "candidate_view_checks": checked_views,
        "analysis_view_cutoff": {"source_view": "daily_training_api_rows_analysis_2026",
                                  "through_date": "2026-09-19",
                                  "plan_ids_through_cutoff": len(eligible_analysis_ids),
                                  "plan_ids_after_cutoff": len(ids) - len(eligible_analysis_ids),
                                  "checked_by_unchanged_view_sql": True,
                                  "analysis_view_materialization_skipped": True},
        "jockey_name_policy": "planned non-jockey rows have NULL website_jockey_name and NULL jockey_name in the current view",
        "prior_evidence_union": {"oct15_rows": 534, "oct17_rows": 587,
                                 "overlap": len(prior["overlap"]), "union": len(prior["union"])},
        "failures": [],
    }


def postapply_checkpoint_digest(payload: dict) -> str:
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def write_postapply_checkpoint(path: Path, payload: dict) -> dict:
    record = dict(payload)
    record["checkpoint_sha256"] = postapply_checkpoint_digest(payload)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return record


def read_postapply_checkpoint(path: Path, plan_sha: str, db_path: Path, baseline_path: Path,
                              live_state: dict, baseline_state: dict, plan_count: int,
                              expected_tables: list[str]) -> dict:
    record = read_json(path)
    supplied_digest = record.pop("checkpoint_sha256", None)
    require(supplied_digest == postapply_checkpoint_digest(record),
            "Postapply core checkpoint digest is invalid")
    require(record.get("plan_sha256") == plan_sha, "Postapply checkpoint plan SHA differs")
    require(record.get("database") == str(db_path) and record.get("baseline") == str(baseline_path),
            "Postapply checkpoint database paths differ")
    require(record.get("live_file_state") == live_state and record.get("baseline_file_state") == baseline_state,
            "Database files changed since the postapply core checkpoint")
    require(record.get("schema_objects_unchanged") is True, "Checkpoint did not verify schema equality")
    table_results = record.get("table_results")
    require(isinstance(table_results, dict) and set(table_results) == set(expected_tables) and
            all(value.get("unchanged") is True for value in table_results.values()),
            "Checkpoint does not prove every non-assignment table unchanged")
    assignment_results = record.get("assignment_changes", {})
    require(assignment_results.get("candidate_rows") == plan_count and
            assignment_results.get("changed_rows") == plan_count and
            assignment_results.get("source_snapshot_fields_unchanged") is True,
            "Checkpoint does not prove the complete assignment stream matched the plan")
    return {**record, "checkpoint_sha256": supplied_digest}


def verify_postapply(args) -> dict:
    plan_rows, summary, plan_sha = read_plan_context(args.plan)
    baseline_path = args.baseline.resolve(strict=True)
    live, db_path = open_readonly(args.db)
    baseline, baseline_path = open_readonly(baseline_path)
    live_before = db_file_state(db_path)
    baseline_before = db_file_state(baseline_path)
    plan_by_id = {row["id"]: row for row in plan_rows}
    ids = sorted(plan_by_id)
    checkpoint_path = args.output.resolve().parent / "postapply_core_checkpoint.json"

    schema_before = schema_snapshot(baseline)
    schema_after = schema_snapshot(live)
    require(schema_before == schema_after, "SQLite schema objects changed from before-apply backup")
    old_tables = table_names(baseline)
    current_tables = table_names(live)
    require(old_tables == current_tables, "Table set changed from before-apply backup")
    require(ASSIGNMENT_TABLE in old_tables, "Assignment table missing from backup/current DB")
    expected_tables = [table for table in old_tables if table != ASSIGNMENT_TABLE]
    if checkpoint_path.exists():
        checkpoint = read_postapply_checkpoint(
            checkpoint_path, plan_sha, db_path, baseline_path, live_before, baseline_before,
            len(plan_by_id), expected_tables)
        table_results = checkpoint["table_results"]
        assignment_results = checkpoint["assignment_changes"]
    else:
        table_results = {}
        for table in expected_tables:
            comparison = compare_table_rows(baseline, live, table)
            table_results[table] = comparison
            require(comparison["unchanged"], f"Non-assignment table changed: {table}")
        assignment_results = verify_assignment_stream(baseline, live, plan_by_id)
        checkpoint = write_postapply_checkpoint(checkpoint_path, {
            "verification": "independent_website_completion_postapply_core",
            "plan_sha256": plan_sha,
            "database": str(db_path),
            "baseline": str(baseline_path),
            "live_file_state": live_before,
            "baseline_file_state": baseline_before,
            "schema_objects_unchanged": True,
            "table_results": table_results,
            "assignment_changes": assignment_results,
        })

    prior = known_prior_union()
    require(prior["union"].issubset(set(ids)), "Applied plan omits the prior 784-row evidence union")

    before_views = view_names(baseline)
    after_views = view_names(live)
    require(before_views == after_views, "View set changed")
    relevant_views = {"daily_training_rider_type_values", "training_current",
                      "daily_training_rider_types", "daily_training_rider_types_analysis_2026",
                      "daily_training_api_rows_analysis_2026"}
    require(relevant_views.issubset(set(before_views)), "Required rider-type views are missing")
    analysis_sql = schema_before.get(("view", "daily_training_api_rows_analysis_2026"), "")
    require(re.search(r"WHERE\s+r\.training_date\s*<=\s*'2026-09-19'", analysis_sql, re.I) is not None,
            "The analysis source view no longer enforces its 2026-09-19 date cutoff")

    # Unchanged source tables, schema SQL, and assignment keys preserve all noncandidate
    # projections. Check the direct guarded type view and current consumer for plan IDs.
    changed_view_rows = {}
    for view in ("daily_training_rider_type_values", "training_current"):
        visible_ids = ids
        before_targets = view_target_values(baseline, view, visible_ids)
        after_targets = view_target_values(live, view, visible_ids)
        require(before_targets.keys() == after_targets.keys(), f"Candidate view visibility changed in {view}")
        if view == "daily_training_rider_type_values":
            require(before_targets.keys() == set(visible_ids), f"Planned candidate rows missing from view {view}")
        for row_id in sorted(before_targets):
            old_view = before_targets[row_id]
            new_view = after_targets[row_id]
            plan = plan_by_id[row_id]
            expected_type = plan["new_type"]
            expected_jockey = plan["new"].get("website_jockey_name")
            require(old_view["rider_type"] == plan["old_type"] and
                    old_view["rider_type_status"] == plan["old_status"],
                    f"Baseline type view disagrees with reviewed old assignment for row {row_id} in {view}")
            if view == "daily_training_rider_type_values":
                require(new_view["rider_type"] == expected_type and new_view["rider_type_status"] == plan["new_status"],
                        f"Guarded type view disagrees with plan for row {row_id}")
                require(new_view["rider_type_on_website"] == expected_type and
                        new_view["rider_label_on_website_raw"] == plan["new"].get("website_label_raw") and
                        new_view["website_jockey_name"] == expected_jockey and
                        new_view["rider_type_website_source_path"] == plan["new"].get("website_source_path") and
                        new_view["rider_type_website_sha256"] == plan["new"].get("website_sha256"),
                        f"Guarded website evidence view disagrees with plan for row {row_id}")
            else:
                require(new_view["rider_type"] == expected_type and new_view["rider_type_status"] == plan["new_status"],
                        f"Rider-type view disagrees with plan for row {row_id}")
                require(new_view["jockey_name"] == (expected_jockey if expected_type == "기수" else None),
                        f"Jockey-name policy failed in {view} for row {row_id}")
                require(new_view["jockey_name_status"] == ("jockey_name_available" if expected_type == "기수" and expected_jockey
                                                             else "jockey_name_unresolved" if expected_type == "기수"
                                                             else "not_applicable"),
                        f"Jockey-name status failed in {view} for row {row_id}")
            # Source columns and event identity are invariant across the two versions of each view.
            for key in old_view:
                if key in VIEW_FIELDS or key in ("jockey_name", "jockey_name_status"):
                    continue
                require(old_view[key] == new_view[key], f"View source field {key} changed for row {row_id}")
        changed_view_rows[view] = {"candidate_rows_checked": len(before_targets),
                                   "candidate_ids_expected": len(visible_ids),
                                   "population_basis": "unchanged source tables, view SQL, and assignment ID set"}

    analysis_candidate_ids = [row_id for row_id in ids
                              if plan_by_id[row_id]["training_date"] <= "2026-09-19"]

    integrity = live.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = live.execute("PRAGMA foreign_key_check").fetchall()
    require(integrity == "ok", f"SQLite integrity_check failed: {integrity}")
    require(not foreign_keys, f"SQLite foreign_key_check found {len(foreign_keys)} violations")

    live.close()
    baseline.close()
    live_after = db_file_state(db_path)
    baseline_after = db_file_state(baseline_path)
    require(live_before == live_after, "Live database files changed during read-only postapply verification")
    require(baseline_before == baseline_after, "Backup database files changed during read-only postapply verification")
    return {
        "verification": "independent_website_completion_postapply",
        "passed": True,
        "phase": "postapply",
        "read_only": True,
        "query_only": True,
        "database": str(db_path),
        "baseline": str(baseline_path),
        "plan_sha256": plan_sha,
        "database_file_sha256_before_after": {"live_before": live_before, "live_after": live_after,
                                               "backup_before": baseline_before, "backup_after": baseline_after},
        "schema_objects_unchanged": True,
        "postapply_core_checkpoint": str(checkpoint_path),
        "table_results": table_results,
        "assignment_changes": assignment_results,
        "rider_type_views": changed_view_rows,
        "analysis_view_cutoff": {"source_view": "daily_training_api_rows_analysis_2026",
                                  "through_date": "2026-09-19",
                                  "plan_ids_through_cutoff": len(analysis_candidate_ids),
                                  "plan_ids_after_cutoff": len(ids) - len(analysis_candidate_ids),
                                  "checked_by_unchanged_view_sql": True},
        "jockey_name_policy": "candidate jockey-name projection is NULL for non-jockey types; noncandidate assignments were unchanged",
        "integrity_check": integrity,
        "foreign_key_violations": len(foreign_keys),
        "idempotency": {"second_run_changes": 0, "verified_against_reviewed_plan_new": True,
                        "basis": "all current candidate assignments equal plan.new during streaming comparison"},
        "prior_evidence_union": {"oct15_rows": 534, "oct17_rows": 587,
                                 "overlap": len(prior["overlap"]), "union": len(prior["union"])},
        "failures": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("preapply", "postapply", "postapply_views"), required=True)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--baseline", type=Path, default=TASK / "before_website_completion.sqlite3")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--collection-manifest", type=Path,
                        default=DEFAULT_COLLECTION_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    require(output.is_relative_to(HERE.resolve()), "Report output must stay inside the verification directory")
    require(not output.exists(), f"Refusing to overwrite report: {output}")
    if args.phase == "preapply":
        report = verify_preapply(args)
    elif args.phase == "postapply_views":
        report = verify_postapply_views(args)
    else:
        report = verify_postapply(args)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "phase": report["phase"],
                      "plan_sha256": report["plan_sha256"], "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({"passed": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        raise
