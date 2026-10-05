#!/usr/bin/env python3
"""Stage and append official Jeju starting-training website observations.

The loader never makes HTTP requests. It verifies staged HTML byte hashes and
reads the archived API22 manifest/pages for cross-source diagnostics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

SCHEMA_VERSION = 1
CUTOFF_DATE = "2026-09-19"
ARTIFACT_TABLE = "website_training_artifacts"
ROW_TABLE = "starting_training_website_rows"
LATEST_VIEW = "starting_training_website_rows_latest"
ANALYSIS_VIEW = "starting_training_website_rows_analysis_2026"
RAW_FIELDS = ("affiliation", "trainer_no", "horse_name", "rider", "location", "note")
API_FIELD_MAP = {
    "affiliation": "part",
    "trainer_no": "partNo",
    "horse_name": "hrName",
    "rider": "prName",
    "note": "remark",
}


def fail(message: str) -> "NoReturn":
    raise ValueError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_child(base: Path, relative: str, label: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute():
        fail(f"{label} must be relative: {relative}")
    base_real = base.resolve(strict=True)
    candidate = (base_real / rel).resolve(strict=True)
    try:
        candidate.relative_to(base_real)
    except ValueError:
        fail(f"{label} escapes its input directory: {relative}")
    if not candidate.is_file():
        fail(f"{label} is not a regular file: {relative}")
    return candidate


def parse_date(value: object, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        fail(f"{label} must be YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        fail(f"invalid {label}: {value}")
    return value


def normalize_time(value: object) -> str:
    if not isinstance(value, str):
        fail("requested_at must be an ISO-8601 string")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        fail(f"invalid requested_at: {value}")
    if moment.tzinfo is None:
        fail("requested_at must include a timezone")
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def validate_url(value: object) -> str:
    if not isinstance(value, str):
        fail("url must be a string")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname != "race.kra.co.kr" or parsed.username or parsed.password:
        fail("url must point to the official race.kra.co.kr host")
    if not parsed.path.endswith("/startingData/getStartingTrainListAll.do"):
        fail("url path is not the official starting-training listing endpoint")
    return value


def norm_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value.strip()


def norm_part(value: object) -> str | None:
    text = norm_text(value)
    if text is None:
        return None
    text = re.sub(r"\s+", "", text)
    return text[:-1] if text.endswith("조") else text


def norm_trainer_no(value: object) -> str | None:
    return norm_text(value)


def norm_note(value: object) -> str | None:
    text = norm_text(value)
    return "" if text in {None, "-"} else text


def comparable_values(website: dict, api_item: dict) -> dict:
    result = {}
    for field, api_field in API_FIELD_MAP.items():
        if api_field not in api_item or api_item[api_field] is None:
            result[field] = "api_field_missing"
            continue
        left = website.get(field)
        right = api_item[api_field]
        if field == "affiliation":
            left_value, right_value = norm_part(left), norm_part(right)
        elif field == "trainer_no":
            left_value, right_value = norm_trainer_no(left), norm_trainer_no(right)
        elif field == "note":
            left_value, right_value = norm_note(left), norm_note(right)
        else:
            left_value, right_value = norm_text(left), norm_text(right)
        result[field] = "equal" if left_value == right_value else "different"
    return result


def canonical_api_key(value: object) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return value
    return None


def extract_api_items(payload: object, label: str) -> list[dict]:
    if not isinstance(payload, dict):
        fail(f"API page is not a JSON object: {label}")
    response = payload.get("response")
    body = response.get("body") if isinstance(response, dict) else None
    items = body.get("items") if isinstance(body, dict) else None
    item = items.get("item") if isinstance(items, dict) else None
    if item is None:
        return []
    if isinstance(item, dict):
        return [item]
    if isinstance(item, list) and all(isinstance(x, dict) for x in item):
        return item
    fail(f"API page item structure is unexpected: {label}")


def load_api_index(api_run_dir: Path) -> tuple[dict, dict]:
    manifest_path = api_run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset = manifest.get("datasets", {}).get("starting_training")
    if not isinstance(dataset, dict):
        fail("API manifest has no datasets.starting_training section")
    years = dataset.get("years")
    if not isinstance(years, dict) or not years:
        fail("API starting_training manifest has no year partitions")
    index: dict[tuple[str, str], list[dict]] = defaultdict(list)
    page_count = row_count = 0
    for year_key, year in years.items():
        if not isinstance(year, dict):
            fail(f"invalid API year partition: {year_key}")
        for page in year.get("pages", []):
            if page.get("status_code") != 200 or page.get("api_result_code") not in {"00", "INFO-000"}:
                fail(f"API22 page not successful: year={year_key} page={page.get('page_no')}")
            rel = page.get("response_file")
            if not isinstance(rel, str):
                fail(f"API22 page has no response_file: year={year_key}")
            file_path = safe_child(api_run_dir, rel, "API22 response_file")
            raw = file_path.read_bytes()
            expected_hash = page.get("response_sha256")
            actual_hash = sha256_bytes(raw)
            if not isinstance(expected_hash, str) or expected_hash != actual_hash:
                fail(f"API22 response SHA-256 mismatch: {rel}")
            page_items = extract_api_items(json.loads(raw.decode("utf-8")), rel)
            page_count += 1
            for item_index, item in enumerate(page_items, 1):
                horse_id = canonical_api_key(item.get("hrNo"))
                date = canonical_api_key(item.get("trDate"))
                if horse_id is None or date is None:
                    continue
                evidence = {
                    "year": str(year_key),
                    "page_no": page.get("page_no"),
                    "item_index": item_index,
                    "response_file": rel,
                    "response_sha256": actual_hash,
                    "raw": {key: item.get(key) for key in ("hrNo", "trDate", "hrName", "part", "partNo", "prName", "remark")},
                }
                index[(horse_id, date)].append(evidence)
                row_count += 1
    return index, {"manifest_path": "run_manifest.json", "pages_indexed": page_count, "api_rows_indexed": row_count}


def load_collection(collection_dir: Path, database: Path, api_run_dir: Path, scope_date: str | None, profiles: dict, api_index: dict) -> tuple[list, dict]:
    manifest_path = collection_dir / "collection_manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        fail(f"collection schema_version must be {SCHEMA_VERSION}")
    date_entries = manifest.get("dates")
    if not isinstance(date_entries, list):
        fail("collection manifest dates must be a list")
    out = []
    seen_rows = set()
    seen_artifacts = set()
    for entry in date_entries:
        if not isinstance(entry, dict):
            fail("date entry must be an object")
        training_date = parse_date(entry.get("date"), "date")
        if scope_date and training_date != scope_date:
            continue
        status = entry.get("status")
        if status not in {"complete", "fetch_failed", "parse_failed", "empty"}:
            fail(f"unsupported collection status for {training_date}: {status}")
        requested_at = normalize_time(entry.get("requested_at"))
        url = validate_url(entry.get("url"))
        html_rel = entry.get("html_path")
        html_hash = entry.get("html_sha256")
        html_bytes = None
        stored_html_rel = None
        if html_rel is not None:
            if not isinstance(html_rel, str):
                fail(f"html_path must be a relative string for {training_date}")
            html_path = safe_child(collection_dir, html_rel, "html_path")
            raw_html = html_path.read_bytes()
            actual = sha256_bytes(raw_html)
            if not isinstance(html_hash, str) or actual != html_hash:
                fail(f"HTML SHA-256 mismatch for {training_date}: {html_rel}")
            html_bytes = len(raw_html)
            jeju_root = database.parent.parent
            try:
                collection_store_root = collection_dir.relative_to(jeju_root).as_posix()
            except ValueError:
                collection_store_root = collection_dir.as_posix()
            stored_html_rel = (Path(collection_store_root) / html_rel).as_posix()
        elif status in {"complete", "empty"}:
            fail(f"successful response has no HTML file for {training_date}")
        if html_hash is not None and (not isinstance(html_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", html_hash)):
            fail(f"invalid html_sha256 for {training_date}")
        if status == "complete" and html_bytes is None:
            fail(f"complete collection has no HTML bytes for {training_date}")
        rows = entry.get("rows", [])
        if not isinstance(rows, list):
            fail(f"rows must be a list for {training_date}")
        if status == "empty" and rows:
            fail(f"empty artifact has rows for {training_date}")
        natural = json.dumps([training_date, requested_at, url, html_hash], ensure_ascii=False, separators=(",", ":"))
        artifact_key = sha256_bytes(natural.encode("utf-8"))
        if artifact_key in seen_artifacts:
            fail(f"duplicate artifact identity in manifest: {training_date}")
        seen_artifacts.add(artifact_key)
        prepared_rows = []
        for row in rows:
            if not isinstance(row, dict):
                fail(f"row must be an object for {training_date}")
            row_no = row.get("source_row_no")
            if isinstance(row_no, bool) or not isinstance(row_no, int) or row_no < 1:
                fail(f"source_row_no must be a positive integer for {training_date}")
            row_key = (artifact_key, row_no)
            if row_key in seen_rows:
                fail(f"duplicate source_row_no={row_no} for {training_date}")
            seen_rows.add(row_key)
            values = {}
            for field in RAW_FIELDS:
                value = row.get(field)
                if value is not None and not isinstance(value, str):
                    fail(f"raw {field} must be string or null for {training_date} row {row_no}")
                values[field] = value
            raw_id = row.get("horse_id_raw")
            if raw_id is not None and not isinstance(raw_id, str):
                fail(f"horse_id_raw must be string or null for {training_date} row {row_no}")
            raw_json = row.get("raw_row_json", row)
            try:
                raw_json_text = json.dumps(raw_json, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            except (TypeError, ValueError) as exc:
                fail(f"raw_row_json is not JSON serializable for {training_date} row {row_no}")
            profile = profiles.get(raw_id) if raw_id is not None else None
            profile_observation_id = None
            horse_id = None
            if status != "complete":
                match_status = "collection_incomplete_row_unconfirmed"
            elif raw_id is None or raw_id == "":
                match_status = "missing_website_horse_id"
            elif raw_id != raw_id.strip() or not raw_id.isascii() or not raw_id.isdigit():
                match_status = "invalid_website_horse_id_format"
            elif profile is None:
                match_status = "profile_not_found"
            elif profile["breed_label_raw"] != "제주마":
                match_status = "profile_not_jeju"
            else:
                horse_id = raw_id
                profile_observation_id = profile["horse_profile_observation_id"]
                name = values["horse_name"]
                if name and profile["horse_name_raw"] and norm_text(name) != norm_text(profile["horse_name_raw"]):
                    match_status = "verified_website_id_jeju_profile_name_differs"
                else:
                    match_status = "verified_website_id_jeju"
            api_items = api_index.get((raw_id, training_date.replace("-", "")), []) if raw_id and raw_id.isascii() and raw_id.isdigit() else []
            comparisons = []
            for item in api_items:
                api_raw = item["raw"]
                field_states = comparable_values(values, api_raw)
                comparisons.append({
                    "year": item["year"], "page_no": item["page_no"], "item_index": item["item_index"],
                    "response_file": item["response_file"], "response_sha256": item["response_sha256"],
                    "field_states": field_states,
                    "exact_comparable_fields": all(state == "equal" for state in field_states.values()),
                    "api_raw_fields": {"horse_name": api_raw.get("hrName"), "affiliation": api_raw.get("part"), "trainer_no": api_raw.get("partNo"), "rider": api_raw.get("prName"), "note": api_raw.get("remark")},
                })
            if not api_items:
                api_match_state = "no_api22_item_for_horse_date"
            else:
                exact_count = sum(1 for item in comparisons if item["exact_comparable_fields"])
                api_match_state = "one_exact_field_match" if exact_count == 1 else "multiple_exact_field_matches" if exact_count > 1 else "same_horse_date_fields_differ_or_missing"
            field_states_summary = {}
            for field in API_FIELD_MAP:
                states = [item["field_states"][field] for item in comparisons]
                field_states_summary[field] = (
                    "no_api22_item_for_horse_date" if not states else
                    "equal_in_all_items" if all(x == "equal" for x in states) else
                    "conflict_in_some_items" if "different" in states else
                    "api_field_missing_in_some_items"
                )
            api_evidence = {
                "source": "KRA API22_1 startingTranning_1 archived raw pages",
                "source_status": "indexed_and_hash_verified",
                "source_run_directory": api_run_dir.as_posix(),
                "horse_id_used": raw_id,
                "training_date_used": training_date,
                "same_horse_date_item_count": len(api_items),
                "row_correspondence_diagnostic": api_match_state,
                "field_diagnostics": field_states_summary,
                "api22_items": comparisons,
            }
            prepared_rows.append({
                "source_row_no": row_no, **{f"{k}_raw": values[k] for k in RAW_FIELDS},
                "horse_id_raw": raw_id, "horse_id": horse_id,
                "horse_profile_observation_id": profile_observation_id,
                "matching_status": match_status,
                "api_evidence_json": json.dumps(api_evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                "raw_row_json": raw_json_text,
            })
        out.append({
            "artifact_key": artifact_key, "training_date": training_date,
            "requested_at_utc": requested_at, "collection_directory": collection_dir.as_posix(),
            "source_url": url, "html_sha256": html_hash,
            "status": status, "http_status": entry.get("http_status"),
            "content_type": entry.get("content_type"), "html_relative_path": stored_html_rel,
            "html_bytes": html_bytes, "manifest_sha256": sha256_bytes(manifest_bytes),
            "row_count": len(prepared_rows), "rows": prepared_rows,
        })
    return out, {"manifest_sha256": sha256_bytes(manifest_bytes), "dates_in_manifest": len(date_entries), "dates_in_scope": len(out)}


def load_profiles(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT horse_id, horse_profile_observation_id, horse_name_raw, breed_label_raw FROM horse_profile_latest").fetchall()
    return {r[0]: {"horse_profile_observation_id": r[1], "horse_name_raw": r[2], "breed_label_raw": r[3]} for r in rows}


def validate_existing_schema(conn: sqlite3.Connection) -> None:
    for table in (ARTIFACT_TABLE, ROW_TABLE):
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if exists:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            required = (set("website_artifact_id artifact_key training_date requested_at_utc collection_directory source_url html_sha256 status manifest_sha256 row_count".split()) if table == ARTIFACT_TABLE else set("starting_training_website_row_id website_artifact_id source_row_no affiliation_raw trainer_no_raw horse_name_raw rider_raw location_raw note_raw horse_id_raw horse_id horse_profile_observation_id matching_status api_evidence_json raw_row_json".split()))
            if not required.issubset(cols):
                fail(f"existing {table} schema differs from this loader")


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(f"""
    CREATE TABLE IF NOT EXISTS {ARTIFACT_TABLE} (
        website_artifact_id INTEGER PRIMARY KEY,
        artifact_key TEXT NOT NULL UNIQUE,
        training_date TEXT NOT NULL,
        requested_at_utc TEXT NOT NULL,
        collection_directory TEXT NOT NULL,
        source_url TEXT NOT NULL,
        html_sha256 TEXT,
        status TEXT NOT NULL CHECK(status IN ('complete','fetch_failed','parse_failed','empty')),
        http_status INTEGER,
        content_type TEXT,
        html_relative_path TEXT,
        html_bytes INTEGER,
        manifest_sha256 TEXT NOT NULL CHECK(length(manifest_sha256)=64),
        row_count INTEGER NOT NULL CHECK(row_count>=0),
        inserted_at_utc TEXT NOT NULL
    )""")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_website_training_artifacts_date ON {ARTIFACT_TABLE}(training_date, requested_at_utc DESC)")
    conn.execute(f"""
    CREATE TABLE IF NOT EXISTS {ROW_TABLE} (
        starting_training_website_row_id INTEGER PRIMARY KEY,
        website_artifact_id INTEGER NOT NULL REFERENCES {ARTIFACT_TABLE}(website_artifact_id),
        source_row_no INTEGER NOT NULL CHECK(source_row_no>0),
        affiliation_raw TEXT,
        trainer_no_raw TEXT,
        horse_name_raw TEXT,
        rider_raw TEXT,
        location_raw TEXT,
        note_raw TEXT,
        horse_id_raw TEXT,
        horse_id TEXT,
        horse_profile_observation_id INTEGER REFERENCES horse_profile_observations(horse_profile_observation_id),
        matching_status TEXT NOT NULL,
        api_evidence_json TEXT NOT NULL,
        raw_row_json TEXT NOT NULL,
        UNIQUE(website_artifact_id, source_row_no),
        CHECK((horse_id IS NULL AND horse_profile_observation_id IS NULL) OR
              (horse_id IS NOT NULL AND horse_profile_observation_id IS NOT NULL))
    )""")
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_starting_training_website_rows_horse_date ON {ROW_TABLE}(horse_id, website_artifact_id)")
    conn.execute(f"""
    CREATE VIEW IF NOT EXISTS {LATEST_VIEW} AS
    WITH ranked AS (
        SELECT a.*, row_number() OVER (
            PARTITION BY a.training_date
            ORDER BY a.requested_at_utc DESC, a.website_artifact_id DESC
        ) AS artifact_rank
        FROM {ARTIFACT_TABLE} a
        WHERE a.status='complete'
    )
    SELECT r.training_date, r.website_artifact_id, r.requested_at_utc, r.source_url,
           r.html_sha256, r.row_count AS artifact_row_count,
           w.starting_training_website_row_id, w.source_row_no,
           w.affiliation_raw, w.trainer_no_raw AS stable_horse_number_raw,
           w.horse_name_raw, w.rider_raw,
           w.location_raw, w.note_raw, w.horse_id_raw, w.horse_id,
           w.horse_profile_observation_id, w.matching_status,
           w.api_evidence_json, w.raw_row_json
    FROM ranked r JOIN {ROW_TABLE} w USING (website_artifact_id)
    WHERE r.artifact_rank=1 AND w.horse_id IS NOT NULL""")
    conn.execute(f"""
    CREATE VIEW IF NOT EXISTS {ANALYSIS_VIEW} AS
    SELECT latest.*, analysis.horse_name AS current_horse_name,
           analysis.age AS current_horse_age_2026,
           analysis.age_reference_year AS current_horse_age_reference_year
    FROM {LATEST_VIEW} latest
    JOIN horse_analysis_2026 analysis ON analysis.horse_id=latest.horse_id
    WHERE latest.training_date <= '{CUTOFF_DATE}'""")


def create_backup(conn: sqlite3.Connection, db_path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_path = db_path.with_name(db_path.name + f".pre_website_training_{stamp}.bak")
    target = sqlite3.connect(str(backup_path))
    try:
        conn.backup(target)
        target.commit()
    finally:
        target.close()
    if not backup_path.is_file() or backup_path.stat().st_size == 0:
        fail("database backup was not created")
    return backup_path


def existing_artifact_equal(conn: sqlite3.Connection, artifact: dict) -> bool:
    existing = conn.execute(
        f"SELECT website_artifact_id, training_date, requested_at_utc, collection_directory, source_url, html_sha256, status, http_status, content_type, html_relative_path, html_bytes, manifest_sha256, row_count FROM {ARTIFACT_TABLE} WHERE artifact_key=?",
        (artifact["artifact_key"],),
    ).fetchone()
    if not existing:
        return False
    expected = (artifact["training_date"], artifact["requested_at_utc"], artifact["collection_directory"], artifact["source_url"], artifact["html_sha256"], artifact["status"], artifact["http_status"], artifact["content_type"], artifact["html_relative_path"], artifact["html_bytes"])
    if tuple(existing[1:11]) != expected or existing[12] != artifact["row_count"]:
        fail(f"existing artifact metadata differs for {artifact['training_date']}; refusing idempotency conflict")
    row_data = conn.execute(
        f"SELECT source_row_no, affiliation_raw, trainer_no_raw, horse_name_raw, rider_raw, location_raw, note_raw, horse_id_raw, horse_id, horse_profile_observation_id, matching_status, api_evidence_json, raw_row_json FROM {ROW_TABLE} WHERE website_artifact_id=? ORDER BY source_row_no",
        (existing[0],),
    ).fetchall()
    expected_rows = [tuple(row[k] for k in ("source_row_no", "affiliation_raw", "trainer_no_raw", "horse_name_raw", "rider_raw", "location_raw", "note_raw", "horse_id_raw", "horse_id", "horse_profile_observation_id", "matching_status", "api_evidence_json", "raw_row_json")) for row in artifact["rows"]]
    if [tuple(row) for row in row_data] != expected_rows:
        fail(f"existing artifact rows differ for {artifact['training_date']}; refusing idempotency conflict")
    return True


def apply_collection(database: Path, artifacts: list) -> dict:
    if not database.is_file():
        fail(f"database does not exist: {database}")
    conn = sqlite3.connect(str(database), timeout=30)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    try:
        validate_existing_schema(conn)
        backup_path = create_backup(conn, database)
        added_artifacts = added_rows = replayed = 0
        conn.execute("BEGIN IMMEDIATE")
        create_schema(conn)
        for artifact in artifacts:
            if existing_artifact_equal(conn, artifact):
                replayed += 1
                continue
            cursor = conn.execute(
                f"INSERT INTO {ARTIFACT_TABLE}(artifact_key, training_date, requested_at_utc, collection_directory, source_url, html_sha256, status, http_status, content_type, html_relative_path, html_bytes, manifest_sha256, row_count, inserted_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (artifact["artifact_key"], artifact["training_date"], artifact["requested_at_utc"], artifact["collection_directory"], artifact["source_url"], artifact["html_sha256"], artifact["status"], artifact["http_status"], artifact["content_type"], artifact["html_relative_path"], artifact["html_bytes"], artifact["manifest_sha256"], artifact["row_count"], datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")),
            )
            artifact_id = cursor.lastrowid
            for row in artifact["rows"]:
                conn.execute(
                    f"INSERT INTO {ROW_TABLE}(website_artifact_id, source_row_no, affiliation_raw, trainer_no_raw, horse_name_raw, rider_raw, location_raw, note_raw, horse_id_raw, horse_id, horse_profile_observation_id, matching_status, api_evidence_json, raw_row_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (artifact_id, row["source_row_no"], row["affiliation_raw"], row["trainer_no_raw"], row["horse_name_raw"], row["rider_raw"], row["location_raw"], row["note_raw"], row["horse_id_raw"], row["horse_id"], row["horse_profile_observation_id"], row["matching_status"], row["api_evidence_json"], row["raw_row_json"]),
                )
                added_rows += 1
            added_artifacts += 1
        bad = conn.execute(f"PRAGMA foreign_key_check({ROW_TABLE})").fetchall()
        if bad:
            fail(f"foreign-key check failed for inserted website rows: {len(bad)} violation(s)")
        conn.commit()
        return {"backup_path": str(backup_path), "artifacts_added": added_artifacts, "rows_added": added_rows, "artifacts_replayed_unchanged": replayed}
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def summarize(artifacts: list, api_summary: dict, collection_summary: dict) -> dict:
    row_statuses = Counter()
    api_states = Counter()
    for artifact in artifacts:
        for row in artifact["rows"]:
            row_statuses[row["matching_status"]] += 1
            api = json.loads(row["api_evidence_json"])
            api_states[api["row_correspondence_diagnostic"]] += 1
    return {
        "mode": "apply-ready" if artifacts else "no-artifacts-in-scope",
        "database_write": "not_performed_in_dry_run",
        "collection": collection_summary,
        "api22": api_summary,
        "artifacts": len(artifacts),
        "collection_status_counts": dict(Counter(a["status"] for a in artifacts)),
        "website_rows": sum(a["row_count"] for a in artifacts),
        "matching_status_counts": dict(row_statuses),
        "api22_correspondence_diagnostics": dict(api_states),
        "analysis_cutoff_date": CUTOFF_DATE,
        "model_input_promotion": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection-dir", required=True, type=Path, help="directory containing collection_manifest.json and staged HTML")
    parser.add_argument("--database", required=True, type=Path, help="existing jeju_native_core.sqlite3 file")
    parser.add_argument("--api-run-dir", required=True, type=Path, help="archived API22 run directory containing run_manifest.json")
    parser.add_argument("--scope-date", help="only process one YYYY-MM-DD collection date")
    parser.add_argument("--plan-out", type=Path, help="write the dry-run plan JSON to this path")
    parser.add_argument("--apply", action="store_true", help="backup the DB, then insert in one transaction")
    args = parser.parse_args()
    if args.scope_date:
        args.scope_date = parse_date(args.scope_date, "scope-date")
    try:
        collection_dir = args.collection_dir.resolve(strict=True)
        api_run_dir = args.api_run_dir.resolve(strict=True)
        database = args.database.resolve(strict=True)
        if not database.is_file():
            fail("database must be an existing file")
        read_conn = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        try:
            profiles = load_profiles(read_conn)
        finally:
            read_conn.close()
        api_index, api_summary = load_api_index(api_run_dir)
        artifacts, collection_summary = load_collection(collection_dir, database, api_run_dir, args.scope_date, profiles, api_index)
        plan = summarize(artifacts, api_summary, collection_summary)
        if args.apply:
            outcome = apply_collection(database, artifacts)
            plan["mode"] = "applied"
            plan["database_write"] = outcome
        output = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.plan_out:
            args.plan_out.write_text(output, encoding="utf-8")
        print(output, end="")
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
