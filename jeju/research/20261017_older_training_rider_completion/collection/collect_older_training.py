#!/usr/bin/env python3
"""Read-only KRA daily-detail collection and exact-event classification."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import socket
import sqlite3
import sys
import tempfile
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
COLLECTION = HERE.resolve()
DB_DEFAULT = ROOT / "jeju/data/jeju_native_core.sqlite3"
SOURCE_RESEARCH = ROOT / "jeju/research/20261017_older_training_rider_sources"
CLASSIFIER = ROOT / "jeju/research/20261015_training_rider_types/classify_riders.py"
ROSTER_DIR = ROOT / "data/research/jockey_roster_20261008"
ENDPOINT = "https://race.kra.co.kr/trainer/dailyAllTrainDetail.do"
HOST = "race.kra.co.kr"
PATH = "/trainer/dailyAllTrainDetail.do"
START_DATE = "2007-10-01"
END_DATE = "2026-04-16"
EXPECTED_ROWS_AFTER_609 = 280351
EXPECTED_DATES_AFTER_609 = 4122
MAX_BYTES = 4 * 1024 * 1024
TIMEOUT_SECONDS = 20
WORKERS = 2
RETRIES = 1
CHECKPOINT_EVERY = 50

SOURCE_COLUMNS = (
    "daily_training_api_artifact_id",
    "prGubun_raw",
    "prNo_raw",
    "horse_id",
    "training_date",
    "start_time_local",
    "end_time_local",
    "duration_seconds",
)
ASSIGNMENT_COLUMNS = (
    "daily_training_api_row_id",
    "daily_training_api_artifact_id",
    "prGubun_raw",
    "prNo_raw",
    "horse_id",
    "training_date",
    "start_time_local",
    "end_time_local",
    "duration_seconds",
    "rider_type",
    "type_status",
    "website_type",
    "website_label_raw",
    "website_jockey_name",
    "website_source_path",
    "website_sha256",
)
API_TYPES = {"기수", "조교사", "조교보", "조교승인", "기수후보생"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sqlite_source_hashes(path: Path) -> dict[str, str | None]:
    """Hash the authoritative SQLite file and WAL, if present."""
    wal = Path(str(path) + "-wal")
    return {
        "database": sha256_file(path),
        "wal": sha256_file(wal) if wal.exists() else None,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_child(parent: Path, child: Path) -> Path:
    parent = parent.resolve()
    target = child.resolve()
    require(target.is_relative_to(parent), f"Path escapes collection root: {child}")
    return target


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_child(COLLECTION, path)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            raise


def write_json_atomic(path: Path, value: object) -> None:
    write_atomic(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def jsonl_line(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def date_key(value: str) -> str:
    parsed = date.fromisoformat(value)
    require(START_DATE <= parsed.isoformat() <= END_DATE, f"Date outside approved range: {value}")
    return parsed.strftime("%Y%m%d")


def output_run_dir(path_value: str) -> Path:
    raw = Path(path_value)
    path = raw if raw.is_absolute() else COLLECTION / raw
    path = path.resolve()
    require(path.is_relative_to(COLLECTION), "Run directory must stay inside collection/")
    return path


class FixedEndpointRedirect(HTTPRedirectHandler):
    """Only permit TLS redirects back to the exact official endpoint host/path."""

    def redirect_request(self, request, fp, code, message, headers, new_url):
        parts = urlsplit(new_url)
        require(
            parts.scheme == "https"
            and parts.hostname == HOST
            and parts.path == PATH
            and parts.username is None
            and parts.password is None
            and parts.port in (None, 443),
            "Redirect outside fixed official HTTPS host/path",
        )
        return super().redirect_request(request, fp, code, message, headers, new_url)


def make_form(training_date: str) -> dict[str, str]:
    d = date.fromisoformat(training_date)
    return {
        "meet": "2",
        "Act": "10",
        "Sub": "3",
        "trDate": d.strftime("%Y/%m/%d"),
        "trDateReplace": d.strftime("%Y%m%d"),
        "trYo": "",
        "trNo": "",
        "trName": "",
    }


class PageHTML(HTMLParser):
    """Small standard-library parser for forms and the 9-cell detail table."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, object]]] = []
        self.hidden_inputs: list[dict[str, str]] = []
        self.text_parts: list[str] = []
        self._row: list[dict[str, object]] | None = None
        self._cell: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = {str(k).lower(): (v or "") for k, v in attrs}
        if tag.lower() == "input" and attributes.get("name"):
            self.hidden_inputs.append(
                {"name": attributes["name"], "value": attributes.get("value", ""),
                 "type": attributes.get("type", "").lower()}
            )
        if tag.lower() == "tr" and self._row is None:
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None and self._cell is None:
            self._cell = {"tag": tag.lower(), "text": [], "horse_ids": []}
        elif tag.lower() == "a" and self._cell is not None:
            onclick = attributes.get("onclick", "")
            href = attributes.get("href", "")
            for candidate in (onclick, href):
                match = re.search(r"goPage4\s*\(\s*['\"]?(\d+)['\"]?\s*\)", candidate)
                if match:
                    ids = self._cell["horse_ids"]
                    assert isinstance(ids, list)
                    ids.append(match.group(1))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._cell is not None:
            text = "".join(self._cell["text"])
            self._cell["text"] = re.sub(r"\s+", " ", text).strip()
            assert self._row is not None
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._cell is not None:
                text = "".join(self._cell["text"])
                self._cell["text"] = re.sub(r"\s+", " ", text).strip()
                self._row.append(self._cell)
                self._cell = None
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)
        if self._cell is not None:
            text = self._cell["text"]
            assert isinstance(text, list)
            text.append(data)


def decode_html(raw: bytes) -> str:
    for encoding in ("cp949", "euc-kr", "utf-8"):
        try:
            return raw.decode(encoding, errors="strict")
        except UnicodeDecodeError:
            continue
    raise ValueError("Official page is not strict UTF-8/CP949/EUC-KR HTML")


def cell_text(cell: dict[str, object]) -> str:
    value = cell.get("text", "")
    return str(value)


def parse_clock(value: str) -> int | None:
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value)
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def parse_official_page(raw: bytes, training_date: str) -> dict[str, object]:
    parser = PageHTML()
    parser.feed(decode_html(raw))
    parser.close()
    text = re.sub(r"\s+", " ", " ".join(parser.text_parts))
    require("전체 일별상세조교현황" in text, "Expected official daily-detail title missing")
    require("기승자범례" in text and "관:주로조교" in text, "Official rider legend missing")

    expected_fields = make_form(training_date)
    values_by_name: dict[str, list[str]] = defaultdict(list)
    for field in parser.hidden_inputs:
        values_by_name[field["name"]].append(field["value"])
    require(set(values_by_name.get("meet", [])) == {"2"}, "Hidden meet field mismatch")
    require(
        set(values_by_name.get("trDate", [])) == {expected_fields["trDate"]},
        "Hidden date field mismatch",
    )

    wanted_header = ["순", "조", "조번", "마명", "기승자", "비고", "입장시각", "퇴장시각", "조교시간"]
    headers = []
    for row in parser.rows:
        if len(row) == 9 and all(str(cell.get("tag")) in {"td", "th"} for cell in row):
            compact = [re.sub(r"\s+", "", cell_text(cell)) for cell in row]
            if compact == wanted_header:
                headers.append(row)
    require(len(headers) == 1, "Expected one exact 9-column detail-table header")

    page_rows: list[dict[str, object]] = []
    malformed: list[dict[str, object]] = []
    for row_number, row in enumerate(parser.rows, 1):
        if len(row) != 9:
            continue
        values = [cell_text(cell) for cell in row]
        if not values[0].isdigit():
            continue
        ids = row[3].get("horse_ids", [])
        if not isinstance(ids, list) or len(ids) != 1:
            raise ValueError(f"Data row {row_number} lacks one official goPage4 horse ID")
        horse_id = str(ids[0])
        label = values[4]
        start = values[6]
        end = values[7]
        duration_match = re.fullmatch(r"(\d+)분", values[8])
        start_minute = parse_clock(start)
        end_minute = parse_clock(end)
        duration = int(duration_match.group(1)) * 60 if duration_match else None
        valid_timing = (
            start_minute is not None
            and end_minute is not None
            and duration is not None
            and duration > 0
            and end_minute >= start_minute
            and (end_minute - start_minute) * 60 == duration
        )
        page_row = {
            "horse_id": horse_id,
            "date": training_date,
            "label": label,
            "start": start if valid_timing else None,
            "end": end if valid_timing else None,
            "duration_seconds": duration if valid_timing else None,
            "row_number": row_number,
        }
        page_rows.append(page_row)
        if not valid_timing:
            malformed.append({"row_number": row_number, "horse_id": horse_id, "label": label})

    return {
        "date": training_date,
        "row_count": len(page_rows),
        "rows": page_rows,
        "invalid_timing_rows": malformed,
        "hidden_fields": {"meet": "2", "trDate": expected_fields["trDate"]},
    }


def roster_names() -> tuple[set[str], dict[str, object]]:
    manifest_path = safe_child(ROOT, ROSTER_DIR / "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    artifacts: list[dict[str, object]] = []
    for meet in (1, 2, 3):
        path = safe_child(ROOT, ROSTER_DIR / f"api_{meet}.json")
        digest = sha256_file(path)
        rows = [r for r in manifest["rows"] if r.get("meet_code") == meet]
        require({r.get("api_sha256") for r in rows} == {digest}, f"API307 meet {meet} SHA mismatch")
        payload = json.loads(path.read_text(encoding="utf-8"))
        body = payload["response"]["body"]
        items = body["items"]["item"]
        items = [items] if isinstance(items, dict) else items
        require(len(items) == int(body["totalCount"]), f"API307 meet {meet} roster incomplete")
        names.update(
            row["jkName"] for row in items if row.get("jkName") not in (None, "", "-")
        )
        artifacts.append({"meet": meet, "path": str(path.relative_to(ROOT)), "sha256": digest,
                          "rows": len(items)})
    return names, {"manifest_path": str(manifest_path.relative_to(ROOT)),
                   "manifest_sha256": sha256_file(manifest_path), "artifacts": artifacts}


def load_classifier():
    spec = importlib.util.spec_from_file_location("existing_rider_classifier", CLASSIFIER)
    require(spec is not None and spec.loader is not None, "Could not load existing parse_label classifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(callable(getattr(module, "parse_label", None)), "Existing parse_label missing")
    return module.parse_label


def open_readonly_database(path: Path) -> sqlite3.Connection:
    path = path.resolve(strict=True)
    require(path == DB_DEFAULT.resolve(), "Only the configured local Jeju database may be read")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA foreign_keys=ON")
    require(connection.execute("PRAGMA query_only").fetchone()[0] == 1, "SQLite query_only is off")
    return connection


def effective_unknown_sql() -> str:
    return """CASE
      WHEN a.daily_training_api_row_id IS NULL THEN '미분류'
      WHEN a.daily_training_api_artifact_id IS NOT d.daily_training_api_artifact_id
        OR a.prGubun_raw IS NOT d.prGubun_raw OR a.prNo_raw IS NOT d.prNo_raw
        OR a.horse_id IS NOT d.horse_id OR a.training_date IS NOT d.training_date
        OR a.start_time_local IS NOT d.start_time_local OR a.end_time_local IS NOT d.end_time_local
        OR a.duration_seconds IS NOT d.duration_seconds THEN '미분류'
      ELSE a.rider_type END"""


def snapshot(db_path: Path, output_dir: Path) -> None:
    output_dir = output_dir.resolve()
    require(output_dir.is_relative_to(COLLECTION), "Snapshot output must stay inside collection/")
    require(not output_dir.exists(), "Snapshot directory already exists; refusing overwrite")
    output_dir.mkdir(parents=True)
    db_path = db_path.resolve(strict=True)
    db_before = sqlite_source_hashes(db_path)
    connection = open_readonly_database(db_path)
    connection.execute("BEGIN")
    row_path = output_dir / "target_rows.jsonl"
    temp_path = output_dir / ".target_rows.jsonl.tmp"
    query_columns = [f"d.{column} AS source_{column}" for column in SOURCE_COLUMNS]
    assignment_columns = [f"a.{column} AS assignment_{column}" for column in ASSIGNMENT_COLUMNS]
    sql = f"""SELECT d.daily_training_api_row_id AS row_id,
        {', '.join(query_columns)}, {', '.join(assignment_columns)}
        FROM daily_training_api_rows d
        LEFT JOIN daily_training_rider_type_assignments a
          ON a.daily_training_api_row_id=d.daily_training_api_row_id
        WHERE d.training_date BETWEEN ? AND ? AND ({effective_unknown_sql()})='미분류'
        ORDER BY d.training_date,d.daily_training_api_row_id"""
    date_counts: Counter[str] = Counter()
    row_count = 0
    with temp_path.open("wb") as stream:
        for record in connection.execute(sql, (START_DATE, END_DATE)):
            row_id = int(record["row_id"])
            source = {column: record[f"source_{column}"] for column in SOURCE_COLUMNS}
            assignment_values = {column: record[f"assignment_{column}"] for column in ASSIGNMENT_COLUMNS}
            has_assignment = assignment_values["daily_training_api_row_id"] is not None
            value = {
                "row_id": row_id,
                "date": source["training_date"],
                "source": source,
                "assignment": assignment_values if has_assignment else None,
            }
            stream.write(jsonl_line(value))
            row_count += 1
            date_counts[str(source["training_date"])] += 1
        stream.flush()
        os.fsync(stream.fileno())
    dates = sorted(date_counts)
    require(row_count == EXPECTED_ROWS_AFTER_609,
            f"Post-609 target row count changed: expected {EXPECTED_ROWS_AFTER_609}, got {row_count}")
    require(len(dates) == EXPECTED_DATES_AFTER_609,
            f"Post-609 date count changed: expected {EXPECTED_DATES_AFTER_609}, got {len(dates)}")
    require(dates[0] == START_DATE and dates[-1] <= END_DATE, "Snapshot date range changed")
    os.replace(temp_path, row_path)

    duplicate_dir = output_dir / "api_duplicate_keys"
    duplicate_dir.mkdir()
    date_set = set(dates)
    duplicate_key_count = 0
    duplicate_sql = """SELECT training_date,horse_id,start_time_local,end_time_local,duration_seconds,
              COUNT(*) AS row_count
        FROM daily_training_api_rows
        WHERE training_date BETWEEN ? AND ? AND horse_id IS NOT NULL
          AND start_time_local IS NOT NULL AND end_time_local IS NOT NULL
          AND duration_seconds IS NOT NULL AND duration_seconds>0
        GROUP BY training_date,horse_id,start_time_local,end_time_local,duration_seconds
        HAVING COUNT(*)>1
        ORDER BY training_date,horse_id,start_time_local,end_time_local,duration_seconds"""
    current_date: str | None = None
    current_stream = None
    for record in connection.execute(duplicate_sql, (START_DATE, END_DATE)):
        training_date = str(record["training_date"])
        if training_date not in date_set:
            continue
        if training_date != current_date:
            if current_stream is not None:
                current_stream.flush()
                os.fsync(current_stream.fileno())
                current_stream.close()
            current_date = training_date
            target = duplicate_dir / f"{date_key(training_date)}.jsonl"
            current_stream = target.open("wb")
        item = {
            "date": training_date,
            "horse_id": record["horse_id"],
            "start_time_local": record["start_time_local"],
            "end_time_local": record["end_time_local"],
            "duration_seconds": record["duration_seconds"],
            "api_row_count": record["row_count"],
        }
        assert current_stream is not None
        current_stream.write(jsonl_line(item))
        duplicate_key_count += 1
    if current_stream is not None:
        current_stream.flush()
        os.fsync(current_stream.fileno())
        current_stream.close()

    connection.commit()
    connection.close()
    db_after = sqlite_source_hashes(db_path)
    require(db_before == db_after, "Database file changed during read-only snapshot")
    snapshot_hash = sha256_file(row_path)
    duplicate_files = sorted(p for p in duplicate_dir.glob("*.jsonl"))
    duplicate_hashes = {p.name: sha256_file(p) for p in duplicate_files}
    manifest = {
        "created_at_utc": utc_now(),
        "db_path": str(db_path.resolve().relative_to(ROOT)),
        "db_artifact_sha256_before": db_before,
        "db_artifact_sha256_after": db_after,
        "database_mode": "ro",
        "query_only": True,
        "date_range": [START_DATE, END_DATE],
        "post_609_expected_rows": EXPECTED_ROWS_AFTER_609,
        "row_count": row_count,
        "distinct_dates": len(dates),
        "dates": dates,
        "date_counts": date_counts,
        "snapshot_path": str(row_path.relative_to(ROOT)),
        "snapshot_sha256": snapshot_hash,
        "duplicate_api_key_groups": duplicate_key_count,
        "duplicate_key_files": duplicate_hashes,
        "source_columns": list(SOURCE_COLUMNS),
        "assignment_columns": list(ASSIGNMENT_COLUMNS),
        "raw_row_json_included": False,
    }
    write_json_atomic(output_dir / "snapshot_manifest.json", manifest)
    print(json.dumps({k: manifest[k] for k in (
        "row_count", "distinct_dates", "duplicate_api_key_groups", "snapshot_sha256",
        "db_artifact_sha256_after"
    )}, ensure_ascii=False))


def is_dns_error(exc: BaseException) -> bool:
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, socket.gaierror):
            return True
        reason = getattr(current, "reason", None)
        if isinstance(reason, BaseException):
            pending.append(reason)
        cause = getattr(current, "__cause__", None)
        context = getattr(current, "__context__", None)
        if isinstance(cause, BaseException):
            pending.append(cause)
        if isinstance(context, BaseException):
            pending.append(context)
    return False


def exception_summary(exc: BaseException) -> dict[str, str]:
    return {"error_type": type(exc).__name__, "error": str(exc)[:500], "dns_error": is_dns_error(exc)}


class PageValidationError(ValueError):
    def __init__(self, message: str, response_meta: dict[str, object], cause: BaseException):
        super().__init__(message)
        self.response_meta = response_meta
        self.__cause__ = cause


def fetch_and_parse(training_date: str) -> dict[str, object]:
    fields = make_form(training_date)
    parts = urlsplit(ENDPOINT)
    require(parts.scheme == "https" and parts.hostname == HOST and parts.path == PATH,
            "Configured official endpoint changed")
    request = Request(
        ENDPOINT,
        data=urlencode(fields).encode("ascii"),
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; KRA official research collector)",
            "Accept": "text/html",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    opener = build_opener(FixedEndpointRedirect())
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            status = response.status
            final_url = response.geturl()
            content_type = response.headers.get("Content-Type", "")
            raw = response.read(MAX_BYTES + 1)
    except HTTPError as response:
        raw = response.read(MAX_BYTES + 1)
        error_meta = {
            "date": training_date, "method": "POST", "url": ENDPOINT,
            "final_url": response.geturl(), "http_status": response.code,
            "content_type": response.headers.get("Content-Type", ""),
            "form_fields": fields, "retrieved_at_utc": utc_now(),
            "bytes": len(raw), "sha256": sha256_bytes(raw), "raw": raw,
        }
        raise PageValidationError(f"Official HTTP status {response.code}", error_meta, response) from response
    final = urlsplit(final_url)
    response_meta = {
        "date": training_date,
        "method": "POST",
        "url": ENDPOINT,
        "final_url": final_url,
        "http_status": status,
        "content_type": content_type,
        "form_fields": fields,
        "retrieved_at_utc": utc_now(),
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
        "raw": raw,
    }
    try:
        require(status == 200, f"Official HTTP status {status}")
        require(len(raw) <= MAX_BYTES, "Official page exceeded 4 MiB limit")
        require(
            final.scheme == "https" and final.hostname == HOST and final.path == PATH
            and final.port in (None, 443) and final.username is None and final.password is None,
            "Final response outside fixed official HTTPS host/path",
        )
        require("text/html" in content_type.lower(), f"Unexpected content type: {content_type[:100]}")
        parsed = parse_official_page(raw, training_date)
    except Exception as exc:
        raise PageValidationError(
            f"Official response failed content validation: {exc}", response_meta, exc
        ) from exc
    return {**response_meta, "parsed": parsed}


def key_from_api_row(row: dict[str, object]) -> tuple[str, str, str, str, int] | None:
    start = row.get("start_time_local")
    end = row.get("end_time_local")
    duration = row.get("duration_seconds")
    horse_id = row.get("horse_id")
    training_date = row.get("date")
    if not isinstance(horse_id, str) or not isinstance(training_date, str):
        return None
    if not isinstance(start, str) or not isinstance(end, str) or not isinstance(duration, int) or duration <= 0:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:00", start):
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:00", end):
        return None
    if start[:10].replace("/", "-") != training_date or end[:10].replace("/", "-") != training_date:
        return None
    return horse_id, training_date, start[11:16], end[11:16], duration


def key_from_page_row(row: dict[str, object]) -> tuple[str, str, str, str, int] | None:
    if not isinstance(row.get("start"), str) or not isinstance(row.get("end"), str):
        return None
    duration = row.get("duration_seconds")
    if not isinstance(duration, int) or duration <= 0:
        return None
    return (str(row["horse_id"]), str(row["date"]), str(row["start"]), str(row["end"]), duration)


def read_snapshot_rows(snapshot_path: Path):
    previous: tuple[str, int] | None = None
    with snapshot_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            value = json.loads(line)
            training_date = str(value["date"])
            row_id = int(value["row_id"])
            sort_key = (training_date, row_id)
            require(previous is None or previous <= sort_key, f"Snapshot order broken at line {line_number}")
            previous = sort_key
            yield value


def grouped_snapshot_rows(snapshot_path: Path):
    import itertools

    for training_date, records in itertools.groupby(read_snapshot_rows(snapshot_path), key=lambda r: r["date"]):
        yield training_date, list(records)


def load_api_duplicate_keys(snapshot_dir: Path, training_date: str):
    path = snapshot_dir / "api_duplicate_keys" / f"{date_key(training_date)}.jsonl"
    if not path.exists():
        return set()
    result = set()
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            value = json.loads(line)
            result.add((str(value["horse_id"]), training_date,
                        str(value["start_time_local"])[11:16], str(value["end_time_local"])[11:16],
                        int(value["duration_seconds"])))
    return result


def load_snapshot_manifest(snapshot_dir: Path) -> dict[str, object]:
    path = safe_child(COLLECTION, snapshot_dir / "snapshot_manifest.json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    row_file = safe_child(COLLECTION, snapshot_dir / "target_rows.jsonl")
    require(sha256_file(row_file) == manifest["snapshot_sha256"], "Snapshot JSONL SHA mismatch")
    require(manifest["row_count"] == EXPECTED_ROWS_AFTER_609, "Unexpected snapshot target row count")
    require(manifest["distinct_dates"] == EXPECTED_DATES_AFTER_609, "Unexpected snapshot date count")
    for name, digest in manifest["duplicate_key_files"].items():
        path = safe_child(COLLECTION, snapshot_dir / "api_duplicate_keys" / name)
        require(sha256_file(path) == digest, f"Duplicate-key index SHA mismatch: {name}")
    return manifest


def load_attempt_state(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        attempts = value.get("attempts", [])
        return attempts if isinstance(attempts, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save_failed_date(run_dir: Path, training_date: str, attempts: list[dict[str, object]], terminal: bool) -> None:
    key = date_key(training_date)
    state_path = run_dir / "date_receipts" / f"{key}.json"
    receipt = {
        "date": training_date,
        "date_key": key,
        "status": "failed_terminal" if terminal else "failed_retryable",
        "attempts": attempts,
        "updated_at_utc": utc_now(),
    }
    write_json_atomic(state_path, receipt)


def build_date_result(
    training_date: str,
    rows: list[dict[str, object]],
    parsed_page: dict[str, object],
    duplicate_api_keys: set[tuple[str, str, str, str, int]],
    parse_label,
    jockey_names: set[str],
    page_manifest: dict[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object]], Counter[str]]:
    page_rows = parsed_page["rows"]
    page_by_key: dict[tuple[str, str, str, str, int], list[dict[str, object]]] = defaultdict(list)
    horse_date_timing: set[str] = set()
    for page_row in page_rows:
        if isinstance(page_row.get("start"), str) and isinstance(page_row.get("end"), str):
            horse_date_timing.add(str(page_row["horse_id"]))
        key = key_from_page_row(page_row)
        if key is not None:
            page_by_key[key].append(page_row)

    outcomes: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    counts: Counter[str] = Counter()
    for snapshot_row in rows:
        row_id = int(snapshot_row["row_id"])
        source = snapshot_row["source"]
        horse_id = str(source["horse_id"])
        key = key_from_api_row({**source, "date": training_date})
        if key is None:
            status = "missing_or_invalid_api_timing"
            outcome = {
                "row_id": row_id,
                "date": training_date,
                "horse_id": horse_id,
                "status": status,
                "label": None,
                "candidate_type": "미분류",
                "jockey_name": None,
            }
            outcomes.append(outcome)
            counts[status] += 1
            continue

        api_duplicate = key in duplicate_api_keys
        page_matches = page_by_key.get(key, [])
        if api_duplicate or len(page_matches) > 1:
            status = "ambiguous_api_and_website_key" if api_duplicate and len(page_matches) > 1 else (
                "ambiguous_api_key" if api_duplicate else "ambiguous_website_key"
            )
            label = None
            kind, jockey_name = "미분류", None
        elif not page_matches:
            status = "no_exact_website_event_match"
            label = None
            kind, jockey_name = "미분류", None
        else:
            matched = page_matches[0]
            label = str(matched["label"])
            kind, jockey_name = parse_label(label, jockey_names)
            status = "classifiable_exact_match" if kind != "미분류" else "exact_match_label_unresolved"

        outcome = {
            "row_id": row_id,
            "date": training_date,
            "horse_id": horse_id,
            "status": status,
            "label": label,
            "candidate_type": kind,
            "jockey_name": jockey_name,
        }
        outcomes.append(outcome)
        counts[status] += 1
        if status == "classifiable_exact_match":
            matched = page_matches[0]
            candidates.append({
                "row_id": row_id,
                "date": training_date,
                "horse_id": horse_id,
                "label": label,
                "candidate_type": kind,
                "jockey_name": jockey_name,
                "start": matched["start"],
                "end": matched["end"],
                "duration_seconds": matched["duration_seconds"],
                "source_path": page_manifest["source_path"],
                "source_sha256": page_manifest["sha256"],
                "url": page_manifest["url"],
                "form_fields": page_manifest["form_fields"],
                "method": "unique_exact_horse_date_start_end_duration",
            })

    return outcomes, candidates, counts


def verify_committed_day(run_dir: Path, training_date: str) -> dict[str, object] | None:
    key = date_key(training_date)
    receipt_path = run_dir / "date_receipts" / f"{key}.json"
    if not receipt_path.exists():
        return None
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "success":
        return None
    require(receipt.get("date") == training_date and receipt.get("url") == ENDPOINT,
            f"Committed receipt date/URL binding mismatch: {training_date}")
    require(receipt.get("form_fields") == make_form(training_date),
            f"Committed request form mismatch: {training_date}")
    require(receipt.get("page", {}).get("date") == training_date
            and receipt.get("page", {}).get("url") == ENDPOINT,
            f"Committed page date/URL binding mismatch: {training_date}")
    for entry in receipt.get("files", []):
        path = safe_child(run_dir, run_dir / entry["path"])
        require(path.is_file() and sha256_file(path) == entry["sha256"],
                f"Committed day file changed: {entry['path']}")
    # Page provenance is intentionally stored relative to the repository root,
    # unlike per-day output paths, which are relative to the run directory.
    page_path = safe_child(run_dir, ROOT / receipt["page"]["source_path"])
    require(page_path.is_file() and sha256_file(page_path) == receipt["page"]["sha256"],
            f"Committed page changed: {page_path}")
    return receipt


def commit_success_day(
    run_dir: Path,
    training_date: str,
    attempt: dict[str, object],
    outcomes: list[dict[str, object]],
    candidates: list[dict[str, object]],
    counts: Counter[str],
    previous_attempts: list[dict[str, object]],
) -> dict[str, object]:
    key = date_key(training_date)
    day_dir = run_dir / "day_results"
    day_dir.mkdir(parents=True, exist_ok=True)
    page_dir = run_dir / "pages"
    page_dir.mkdir(parents=True, exist_ok=True)
    page_path = page_dir / f"{key}.html"
    raw = attempt.pop("raw")
    parsed = attempt.pop("parsed")
    require(isinstance(raw, bytes), "Missing response body")
    write_atomic(page_path, raw)
    page_manifest = {k: v for k, v in attempt.items() if k != "raw"}
    page_manifest.update({
        "source_path": str(page_path.relative_to(ROOT)),
        "sha256": sha256_bytes(raw),
        "parsed_row_count": parsed["row_count"],
        "invalid_timing_rows": parsed["invalid_timing_rows"],
        "legend_validation": "passed",
        "hidden_date_meet_validation": "passed",
        "table_header_validation": "passed",
    })
    receipt_path = run_dir / "date_receipts" / f"{key}.json"
    outcomes_path = day_dir / f"{key}.outcomes.jsonl"
    candidates_path = day_dir / f"{key}.candidates.jsonl"
    if receipt_path.exists():
        prior_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        require(prior_receipt.get("status") != "success",
                f"Refusing to overwrite immutable result for {training_date}")
    # Files without a successful receipt are an interrupted, uncommitted write.
    outcomes_path.unlink(missing_ok=True)
    candidates_path.unlink(missing_ok=True)
    # Per-date files are written once, then the receipt is atomically renamed as commit marker.
    write_atomic(outcomes_path, b"".join(jsonl_line(row) for row in outcomes))
    write_atomic(candidates_path, b"".join(jsonl_line(row) for row in candidates))
    files = [
        {"path": str(outcomes_path.relative_to(run_dir)), "sha256": sha256_file(outcomes_path),
         "rows": len(outcomes)},
        {"path": str(candidates_path.relative_to(run_dir)), "sha256": sha256_file(candidates_path),
         "rows": len(candidates)},
    ]
    receipt = {
        "date": training_date,
        "date_key": key,
        "status": "success",
        "committed_at_utc": utc_now(),
        "url": ENDPOINT,
        "form_fields": attempt["form_fields"],
        "page": page_manifest,
        "attempts": previous_attempts,
        "counts": dict(counts),
        "files": files,
    }
    write_json_atomic(receipt_path, receipt)
    return receipt


def persist_attempt_failure(run_dir: Path, training_date: str, attempt_number: int,
                            exc: BaseException, response_meta: dict[str, object] | None = None) -> dict[str, object]:
    summary: dict[str, object] = {
        "attempt": attempt_number,
        "attempted_at_utc": utc_now(),
        **exception_summary(exc),
    }
    if response_meta:
        failures = run_dir / "failed_responses"
        failures.mkdir(parents=True, exist_ok=True)
        body = response_meta.get("raw")
        if isinstance(body, bytes):
            path = failures / f"{date_key(training_date)}-attempt{attempt_number}.html"
            write_atomic(path, body)
            summary.update({"response_path": str(path.relative_to(ROOT)),
                            "response_sha256": sha256_bytes(body),
                            "response_bytes": len(body)})
        summary.update({k: v for k, v in response_meta.items() if k != "raw"})
    attempt_dir = run_dir / "attempt_logs"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    attempt_path = attempt_dir / f"{date_key(training_date)}.json"
    attempts = load_attempt_state(attempt_path)
    attempts.append(summary)
    write_json_atomic(attempt_path, {"date": training_date, "attempts": attempts})
    return summary


def process_date(training_date: str, rows: list[dict[str, object]], duplicate_api_keys,
                 parse_label, jockey_names, run_dir: Path) -> dict[str, object]:
    existing = verify_committed_day(run_dir, training_date)
    if existing:
        return {"date": training_date, "status": "already_committed", "receipt": existing}

    attempts_path = run_dir / "attempt_logs" / f"{date_key(training_date)}.json"
    attempts = load_attempt_state(attempts_path)
    # Prior terminal errors remain traceable. A resumed run gets one fresh try plus one retry.
    first_attempt = len(attempts) + 1
    last_exc: BaseException | None = None
    for retry_index in range(RETRIES + 1):
        attempt_number = first_attempt + retry_index
        response_meta = None
        try:
            response_meta = fetch_and_parse(training_date)
            page = response_meta["parsed"]
            duplicate_keys = duplicate_api_keys
            provisional_manifest = {
                "url": response_meta["url"],
                "form_fields": response_meta["form_fields"],
                "source_path": str((run_dir / "pages" / f"{date_key(training_date)}.html").relative_to(ROOT)),
                "sha256": response_meta["sha256"],
            }
            outcomes, candidates, counts = build_date_result(
                training_date, rows, page, duplicate_keys, parse_label, jockey_names, provisional_manifest
            )
            receipt = commit_success_day(run_dir, training_date, response_meta, outcomes,
                                         candidates, counts, attempts)
            return {"date": training_date, "status": "success", "receipt": receipt}
        except BaseException as exc:
            last_exc = exc
            if response_meta is None:
                response_meta = getattr(exc, "response_meta", None)
            failure = persist_attempt_failure(run_dir, training_date, attempt_number, exc, response_meta)
            attempts.append(failure)
            if is_dns_error(exc):
                save_failed_date(run_dir, training_date, attempts, terminal=False)
                return {"date": training_date, "status": "dns_blocked", "error": exception_summary(exc)}
            if retry_index < RETRIES:
                time.sleep(0.25)
                continue
    assert last_exc is not None
    save_failed_date(run_dir, training_date, attempts, terminal=True)
    return {"date": training_date, "status": "failed_terminal", "error": exception_summary(last_exc)}


def write_checkpoint(run_dir: Path, snapshot_manifest: dict[str, object], completed: int,
                     last_date: str | None, state: str, counters: Counter[str]) -> None:
    checkpoint = {
        "updated_at_utc": utc_now(),
        "state": state,
        "completed_dates_this_invocation": completed,
        "last_date": last_date,
        "snapshot_sha256": snapshot_manifest["snapshot_sha256"],
        "target_rows": snapshot_manifest["row_count"],
        "target_dates": snapshot_manifest["distinct_dates"],
        "status_counts": dict(counters),
    }
    write_json_atomic(run_dir / "checkpoint.json", checkpoint)


def initialize_run(run_dir: Path, snapshot_dir: Path, snapshot_manifest: dict[str, object], roster_info: dict[str, object]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "run_manifest.json"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(existing["snapshot_sha256"] == snapshot_manifest["snapshot_sha256"],
                "Run directory is bound to a different source snapshot")
        require(existing["roster"] == roster_info, "Official jockey roster changed since this run began")
        require(existing.get("frozen_at_utc") is None, "Run is frozen; no more writes allowed")
        return
    manifest = {
        "created_at_utc": utc_now(),
        "state": "collecting",
        "root_relative_directory": str(run_dir.relative_to(ROOT)),
        "snapshot_manifest_sha256": sha256_file(snapshot_dir / "snapshot_manifest.json"),
        "snapshot_sha256": snapshot_manifest["snapshot_sha256"],
        "target_rows": snapshot_manifest["row_count"],
        "target_dates": snapshot_manifest["dates"],
        "official_endpoint": ENDPOINT,
        "http_method": "POST",
        "request_form_template": {
            "meet": "2", "Act": "10", "Sub": "3", "trDate": "YYYY/MM/DD",
            "trDateReplace": "YYYYMMDD", "trYo": "", "trNo": "", "trName": "",
        },
        "limits": {"workers": WORKERS, "timeout_seconds": TIMEOUT_SECONDS,
                   "max_response_bytes": MAX_BYTES, "retries_per_invocation": RETRIES},
        "classification": "existing parse_label exact API307 roster or explicit official label only",
        "roster": roster_info,
        "database_writes": False,
        "raw_row_json_included": False,
        "frozen_at_utc": None,
    }
    write_json_atomic(manifest_path, manifest)


def run_collection(snapshot_dir: Path, run_dir: Path) -> None:
    snapshot_dir = snapshot_dir.resolve(strict=True)
    require(snapshot_dir.is_relative_to(COLLECTION), "Snapshot directory must stay inside collection/")
    run_dir = run_dir.resolve()
    require(run_dir.is_relative_to(COLLECTION), "Run directory must stay inside collection/")
    snapshot_manifest = load_snapshot_manifest(snapshot_dir)
    jockey_names, roster_info = roster_names()
    parse_label = load_classifier()
    initialize_run(run_dir, snapshot_dir, snapshot_manifest, roster_info)
    snapshot_path = snapshot_dir / "target_rows.jsonl"
    dates = snapshot_manifest["dates"]
    counters: Counter[str] = Counter()
    completed = 0
    date_iter = iter(grouped_snapshot_rows(snapshot_path))
    next_group = next(date_iter, None)
    require(next_group is not None, "Empty snapshot unexpectedly")

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        active = {}
        stop_for_dns = False
        while next_group is not None or active:
            while not stop_for_dns and next_group is not None and len(active) < WORKERS:
                training_date, rows = next_group
                require(training_date in dates, f"Snapshot contains unexpected date {training_date}")
                duplicate_keys = load_api_duplicate_keys(snapshot_dir, training_date)
                future = pool.submit(process_date, training_date, rows, duplicate_keys,
                                     parse_label, jockey_names, run_dir)
                active[future] = training_date
                next_group = next(date_iter, None)
            if not active:
                break
            for future in as_completed(tuple(active)):
                training_date = active.pop(future)
                result = future.result()
                completed += 1
                counters[str(result["status"])] += 1
                if result["status"] == "dns_blocked":
                    stop_for_dns = True
                if completed % CHECKPOINT_EVERY == 0:
                    write_checkpoint(run_dir, snapshot_manifest, completed, training_date,
                                     "dns_blocked" if stop_for_dns else "collecting", counters)
                print(json.dumps({"completed": completed, "target_dates": len(dates),
                                  "date": training_date, "status": result["status"]}, ensure_ascii=False),
                      flush=True)
                break
        # In-flight work is allowed to finish and is recorded after a DNS stop.
        for future in as_completed(tuple(active)):
            training_date = active.pop(future)
            result = future.result()
            completed += 1
            counters[str(result["status"])] += 1
            if completed % CHECKPOINT_EVERY == 0:
                write_checkpoint(run_dir, snapshot_manifest, completed, training_date,
                                 "dns_blocked" if stop_for_dns else "collecting", counters)
            print(json.dumps({"completed": completed, "target_dates": len(dates),
                              "date": training_date, "status": result["status"]}, ensure_ascii=False),
                  flush=True)

    status = "dns_blocked" if stop_for_dns else "collection_pass_complete"
    write_checkpoint(run_dir, snapshot_manifest, completed, None, status, counters)
    print(json.dumps({"state": status, "dates_processed_this_invocation": completed,
                      "status_counts": dict(counters)}, ensure_ascii=False))


def finalize(snapshot_dir: Path, run_dir: Path, allow_failed: bool) -> None:
    snapshot_dir = snapshot_dir.resolve(strict=True)
    run_dir = run_dir.resolve(strict=True)
    require(snapshot_dir.is_relative_to(COLLECTION) and run_dir.is_relative_to(COLLECTION),
            "Finalize paths must stay inside collection/")
    snapshot_manifest = load_snapshot_manifest(snapshot_dir)
    run_manifest_path = run_dir / "run_manifest.json"
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    require(run_manifest.get("frozen_at_utc") is None, "Run is already frozen")
    require(run_manifest["snapshot_sha256"] == snapshot_manifest["snapshot_sha256"],
            "Run snapshot binding mismatch")
    receipts: list[dict[str, object]] = []
    missing: list[str] = []
    for training_date in snapshot_manifest["dates"]:
        key = date_key(training_date)
        receipt_path = run_dir / "date_receipts" / f"{key}.json"
        if not receipt_path.exists():
            missing.append(training_date)
            continue
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("status") == "success":
            verify_committed_day(run_dir, training_date)
        elif receipt.get("status") not in {"failed_retryable", "failed_terminal"}:
            missing.append(training_date)
        elif not allow_failed:
            missing.append(training_date)
        receipts.append(receipt)
    require(not missing, f"Cannot freeze: pending/unapproved dates remain ({len(missing)})")

    # Materialize final page_failed outcomes for dates that remained unavailable.
    failed_dates = {str(r["date"]): r for r in receipts if r.get("status") != "success"}
    snapshot_rows = grouped_snapshot_rows(snapshot_dir / "target_rows.jsonl")
    expected_dates = iter(snapshot_manifest["dates"])
    all_candidates = run_dir / "candidates.jsonl"
    all_outcomes = run_dir / "outcomes.jsonl"
    outcomes_tmp = run_dir / ".outcomes.jsonl.tmp"
    candidates_tmp = run_dir / ".candidates.jsonl.tmp"
    require(not all_outcomes.exists() and not all_candidates.exists(), "Combined outputs already exist")
    total_outcomes = 0
    total_candidates = 0
    aggregate_counts: Counter[str] = Counter()
    with outcomes_tmp.open("wb") as outcome_stream, candidates_tmp.open("wb") as candidate_stream:
        for training_date, rows in snapshot_rows:
            next(expected_dates, None)
            if training_date in failed_dates:
                failed = failed_dates[training_date]
                status = "official_page_failed"
                error = failed.get("attempts", [])[-1] if failed.get("attempts") else {}
                for source_row in rows:
                    record = {
                        "row_id": int(source_row["row_id"]),
                        "date": training_date,
                        "horse_id": str(source_row["source"]["horse_id"]),
                        "status": status,
                        "label": None,
                        "candidate_type": "미분류",
                        "jockey_name": None,
                        "page_error_type": error.get("error_type"),
                    }
                    outcome_stream.write(jsonl_line(record))
                    total_outcomes += 1
                    aggregate_counts[status] += 1
                continue
            key = date_key(training_date)
            day_outcomes = run_dir / "day_results" / f"{key}.outcomes.jsonl"
            day_candidates = run_dir / "day_results" / f"{key}.candidates.jsonl"
            with day_outcomes.open("rb") as source:
                for line in source:
                    outcome_stream.write(line)
                    total_outcomes += 1
                    aggregate_counts[json.loads(line)["status"]] += 1
            with day_candidates.open("rb") as source:
                for line in source:
                    candidate_stream.write(line)
                    total_candidates += 1
        outcome_stream.flush()
        os.fsync(outcome_stream.fileno())
        candidate_stream.flush()
        os.fsync(candidate_stream.fileno())
    require(total_outcomes == snapshot_manifest["row_count"],
            f"Final outcome row count mismatch: expected {snapshot_manifest['row_count']}, got {total_outcomes}")
    os.replace(outcomes_tmp, all_outcomes)
    os.replace(candidates_tmp, all_candidates)

    receipts_by_date = {str(r["date"]): r for r in receipts}
    page_rows = sum(int(r.get("page", {}).get("parsed_row_count", 0)) for r in receipts if r.get("status") == "success")
    candidate_check = Counter()
    with all_candidates.open("r", encoding="utf-8") as stream:
        for line in stream:
            candidate_check[json.loads(line)["candidate_type"]] += 1
    run_manifest["frozen_at_utc"] = utc_now()
    run_manifest["state"] = "frozen_with_failures" if failed_dates else "frozen_complete"
    run_manifest["dates_successful"] = sum(1 for r in receipts if r.get("status") == "success")
    run_manifest["dates_failed"] = len(failed_dates)
    run_manifest["page_rows"] = page_rows
    run_manifest["total_outcome_rows"] = total_outcomes
    run_manifest["total_candidates"] = total_candidates
    run_manifest["candidate_type_counts"] = dict(candidate_check)
    run_manifest["outcome_status_counts"] = dict(aggregate_counts)
    run_manifest["combined_files"] = {
        "outcomes.jsonl": {"sha256": sha256_file(all_outcomes), "rows": total_outcomes},
        "candidates.jsonl": {"sha256": sha256_file(all_candidates), "rows": total_candidates},
    }
    run_manifest["receipt_date_count"] = len(receipts_by_date)
    run_manifest["failed_dates"] = sorted(failed_dates)
    run_manifest["database_writes"] = False
    write_json_atomic(run_manifest_path, run_manifest)
    write_checkpoint(run_dir, snapshot_manifest, len(receipts), None, "frozen", Counter({"frozen": len(receipts)}))
    print(json.dumps({"state": run_manifest["state"], "dates": len(receipts),
                      "dates_failed": len(failed_dates), "outcomes": total_outcomes,
                      "candidates": total_candidates,
                      "outcome_status_counts": dict(aggregate_counts)}, ensure_ascii=False))


def verify_sample_parser() -> None:
    sample_manifest_path = SOURCE_RESEARCH / "homepage/daily_all_2010/manifest.json"
    manifest = json.loads(sample_manifest_path.read_text(encoding="utf-8"))[0]
    sample_path = (ROOT / manifest["source_path"]).resolve(strict=True)
    require(sample_path.is_relative_to(SOURCE_RESEARCH.resolve()), "Sample source path escaped evidence directory")
    raw = sample_path.read_bytes()
    require(sha256_bytes(raw) == manifest["sha256"], "Saved sample HTML SHA mismatch")
    parsed = parse_official_page(raw, "2010-01-04")
    sample = [row for row in parsed["rows"] if row["horse_id"] == "3011374"
              and row["start"] == "07:31" and row["end"] == "07:46"
              and row["duration_seconds"] == 900]
    require(len(sample) == 1 and sample[0]["label"] == "관", "Known 2010 sample row did not parse")
    print(json.dumps({"sample_date": parsed["date"], "page_rows": parsed["row_count"],
                      "known_horse_id": sample[0]["horse_id"], "label": sample[0]["label"],
                      "start": sample[0]["start"], "end": sample[0]["end"],
                      "duration_seconds": sample[0]["duration_seconds"]}, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot_parser = commands.add_parser("snapshot", help="Create a post-609 read-only target snapshot")
    snapshot_parser.add_argument("--db", type=Path, default=DB_DEFAULT)
    snapshot_parser.add_argument("--output-dir", required=True)
    fetch_parser = commands.add_parser("fetch", help="Resume bounded official daily-detail collection")
    fetch_parser.add_argument("--snapshot-dir", required=True)
    fetch_parser.add_argument("--run-dir", required=True)
    finalize_parser = commands.add_parser("finalize", help="Freeze combined outcomes and candidates")
    finalize_parser.add_argument("--snapshot-dir", required=True)
    finalize_parser.add_argument("--run-dir", required=True)
    finalize_parser.add_argument("--allow-failed-pages", action="store_true")
    commands.add_parser("verify-sample-parser", help="Check the stdlib parser against the saved 2010 page")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "snapshot":
        output = output_run_dir(args.output_dir)
        snapshot(args.db, output)
    elif args.command == "fetch":
        snapshot_dir = output_run_dir(args.snapshot_dir)
        run_dir = output_run_dir(args.run_dir)
        run_collection(snapshot_dir, run_dir)
    elif args.command == "finalize":
        snapshot_dir = output_run_dir(args.snapshot_dir)
        run_dir = output_run_dir(args.run_dir)
        finalize(snapshot_dir, run_dir, args.allow_failed_pages)
    elif args.command == "verify-sample-parser":
        verify_sample_parser()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit("Interrupted; committed day receipts remain resumable")
