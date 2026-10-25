"""Prepare, dry-run, or append 31 verified event-level training rider names."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

import duckdb
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[3]
STAGE = Path(__file__).resolve().parent
INPUT_MANIFEST = STAGE / "input/input_manifest.json"
REPORTS = STAGE / "reports"
SCHEMA = STAGE / "schema.sql"
CORE_DIR = ROOT / "thoroughbred/data/core_api_2010_20260929_v1"
CORE_DB = CORE_DIR / "thoroughbred_core.duckdb"
CORE_MANIFEST = CORE_DIR / "manifest.json"
BACKUP_DIR = CORE_DIR / "backups/20261015_before_event_name_31"
BACKUP_DB = BACKUP_DIR / CORE_DB.name
BACKUP_MANIFEST = BACKUP_DIR / CORE_MANIFEST.name
BACKUP_ATTESTATION = BACKUP_DIR / "backup_pair_attestation.json"
SOURCE_MANIFEST_NAME = "daily_training_rider_event_name_links_v1"
TABLE_NAME = "daily_training_rider_event_name_links"
BASE_DB_SHA256 = "16a5e0127a830dd1d95db2bfd1178fa4af8f43265d80de852dc2f409329c02f3"
BASE_MANIFEST_SHA256 = "b03854c7cfd4b55a2d8fa955f681d295dd83247db6ed505c74f1a7e89b249d26"
EXPECTED_DATES = {
    "2026-09-04": 6, "2026-09-05": 7, "2026-09-06": 6,
    "2026-09-09": 6, "2026-09-10": 6,
}
RAW_FIELDS = (
    "observation_id", "event_date", "meet", "official_horse_id", "horse_name_raw",
    "rider_type_raw", "rider_id_raw", "started_at_raw", "ended_at_raw",
)
EVENT_FIELDS = (
    "observation_id", "rider_id_raw", "event_date", "meet_raw", "official_horse_id",
    "horse_name_raw", "rider_type_raw", "started_at_raw", "ended_at_raw", "event_name",
    "event_name_basis", "source_service", "source_file", "source_sha256", "evidence_file",
    "evidence_sha256", "matching_method", "web_row_no", "web_started_at_display",
    "web_ended_at_display", "identity_limit",
)
CONFLICT_OBSERVATION_ID = (
    "api18_1:api18-monthly-m1-202609-fresh-8667fb7f6c:"
    "7c2ef0c7e449dc216e246dd4b6a05eeba3bc806e6239dea181603bf34f305bed:p1:r1345"
)
MATCHING_METHOD = (
    "date+meet+official horse ID+entry minute+exit minute; unique candidate required; "
    "horse name checked; raw seconds retained"
)
IDENTITY_LIMIT = (
    "Same-event official webpage display name only; no mapping from the raw rider ID to an official profile ID."
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def repo_path(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ValueError(f"evidence path must be repository-relative: {relative}")
    resolved = (ROOT / candidate).resolve()
    if not resolved.is_relative_to(ROOT):
        raise ValueError(f"evidence path escapes the repository: {relative}")
    return resolved


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_inputs() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    manifest = json.loads(INPUT_MANIFEST.read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != "daily_training_rider_event_names_v1"
            or manifest.get("baseline_database_sha256") != BASE_DB_SHA256
            or manifest.get("baseline_core_manifest_sha256") != BASE_MANIFEST_SHA256
            or manifest.get("approved_rider_id_raw") != "080626"
            or manifest.get("approved_event_name") != "다비드"
            or manifest.get("expected_rows") != 31
            or manifest.get("expected_date_counts") != EXPECTED_DATES):
        raise ValueError("input manifest has a different baseline or approved scope")
    hashes: dict[str, str] = {}
    for item in manifest["files"]:
        path = repo_path(item["path"])
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            raise ValueError(f"pinned input hash mismatch: {item['path']}")
        hashes[item["path"]] = item["sha256"]
    required_paths = {
        manifest["evidence_file"], manifest["verification_file"],
        manifest["capture_manifest_file"], manifest["raw_source_file"],
        *manifest["official_html_files"],
    }
    if required_paths != set(hashes):
        raise ValueError("pinned input list does not equal the declared evidence set")

    evidence_path = repo_path(manifest["evidence_file"])
    evidence = read_jsonl(evidence_path)
    verification = json.loads(repo_path(manifest["verification_file"]).read_text(encoding="utf-8"))
    if (verification.get("status") != "same_event_name_verified_id_relationship_unresolved"
            or verification.get("verified_rows") != 31
            or verification.get("web_names") != {"다비드": 31}):
        raise ValueError("the 080626 verification summary does not preserve the unresolved ID relationship")
    if len(evidence) != 31 or len({row.get("observation_id") for row in evidence}) != 31:
        raise ValueError("event evidence must contain exactly 31 unique observation IDs")

    captures = {row["name"]: row for row in read_jsonl(repo_path(manifest["capture_manifest_file"]))}
    html_by_key: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    pages_by_date: dict[str, tuple[str, str]] = {}
    for relative in manifest["official_html_files"]:
        expected_page = repo_path(relative)
        capture = next((item for item in captures.values() if item.get("file") == relative.split("/20261015_training_rider_roles_followup_v1/", 1)[-1]), None)
        if capture is None or capture.get("sha256") != hashes[relative]:
            raise ValueError(f"official page is not pinned by the capture manifest: {relative}")
        request = capture.get("request_form", {})
        day = str(request.get("trDate", "")).replace("/", "-")
        if request.get("meet") != "3" or day in pages_by_date:
            raise ValueError(f"unexpected official day-page request metadata: {relative}")
        pages_by_date[day] = (relative, hashes[relative])
        soup = BeautifulSoup(expected_page.read_bytes().decode(capture.get("encoding", "cp949")), "html.parser")
        tables = [table for table in soup.find_all("table")
                  if table.find("caption") and "전체일별상세조교현황" in table.find("caption").get_text()]
        if len(tables) != 1 or str(request.get("trDate", "")) not in soup.get_text(" ", strip=True):
            raise ValueError(f"official page has no unique daily-training table for {day}")
        for tr in tables[0].find_all("tr"):
            cells = tr.find_all("td", recursive=False)
            if not cells:
                continue
            if len(cells) != 13:
                raise ValueError(f"unexpected official daily-training row width on {day}")
            values = [cell.get_text(" ", strip=True) for cell in cells]
            anchor = cells[3].find("a", href=True)
            horse = re.fullmatch(r"javascript:goPage4\('([0-9]+)'\)", anchor["href"] if anchor else "")
            if not horse:
                raise ValueError(f"official page row has no official horse ID on {day}")
            html_by_key[(day, "3", horse.group(1), values[7], values[8])].append(
                {"values": values, "file": relative, "sha256": hashes[relative]}
            )
    if set(pages_by_date) != set(EXPECTED_DATES):
        raise ValueError("official daily pages do not cover the approved five dates")

    event_rows: list[dict[str, Any]] = []
    date_counts: Counter[str] = Counter()
    seen_event_keys: set[tuple[str, str, str, str, str]] = set()
    for row in evidence:
        day = str(row["event_date"])
        raw_started, raw_ended = str(row["started_at_raw"]), str(row["ended_at_raw"])
        if (row.get("rider_id_raw") != "080626" or row.get("rider_type_raw") != "기수"
                or row.get("meet") != "3" or row.get("web_rider_name") != "다비드"
                or row.get("raw_path") != manifest["raw_source_file"]
                or row.get("raw_sha256") != hashes[manifest["raw_source_file"]]
                or row.get("web_values", [None] * 13)[5] != "다비드"):
            raise ValueError(f"approved event evidence fields differ: {row.get('observation_id')}")
        key = (day, "3", str(row["official_horse_id"]), str(row["web_values"][7]), str(row["web_values"][8]))
        if key in seen_event_keys or len(html_by_key.get(key, [])) != 1:
            raise ValueError(f"official page event match is not unique: {key}")
        seen_event_keys.add(key)
        official = html_by_key[key][0]
        values = official["values"]
        source_file_within_review = official["file"].split(
            "/20261015_training_rider_roles_followup_v1/", 1
        )[-1]
        if (values[3] != row["horse_name_raw"] or values[5] != "다비드"
                or values[7] != row["web_values"][7] or values[8] != row["web_values"][8]
                or values[0] != str(row["web_values"][0])
                or row.get("web_file") != source_file_within_review
                or row.get("web_sha256") != official["sha256"]):
            raise ValueError(f"official horse/name/time evidence mismatch: {row.get('observation_id')}")
        if raw_started[8:12] != values[7].replace(":", "") or raw_ended[8:12] != values[8].replace(":", ""):
            raise ValueError(f"official minute display disagrees with raw time: {row.get('observation_id')}")
        date_counts[day] += 1
        matching = MATCHING_METHOD
        event_rows.append({
            "observation_id": row["observation_id"], "rider_id_raw": row["rider_id_raw"],
            "event_date": day, "meet_raw": row["meet"], "official_horse_id": row["official_horse_id"],
            "horse_name_raw": row["horse_name_raw"], "rider_type_raw": row["rider_type_raw"],
            "started_at_raw": raw_started, "ended_at_raw": raw_ended, "event_name": "다비드",
            "event_name_basis": matching, "source_service": "KRA official daily-training detail page",
            "source_file": official["file"], "source_sha256": official["sha256"],
            "evidence_file": manifest["evidence_file"], "evidence_sha256": hashes[manifest["evidence_file"]],
            "matching_method": matching, "web_row_no": str(values[0]),
            "web_started_at_display": values[7], "web_ended_at_display": values[8],
            "identity_limit": IDENTITY_LIMIT,
        })
    if dict(date_counts) != EXPECTED_DATES:
        raise ValueError(f"approved event date counts differ: {dict(date_counts)}")
    return manifest, event_rows, hashes


def current_identity() -> tuple[str, str, dict[str, Any]]:
    db_hash = sha256_file(CORE_DB)
    manifest_hash = sha256_file(CORE_MANIFEST)
    core_manifest = json.loads(CORE_MANIFEST.read_text(encoding="utf-8"))
    if db_hash != BASE_DB_SHA256 or manifest_hash != BASE_MANIFEST_SHA256:
        raise ValueError("core DB or manifest differs from the pinned post-rider-links baseline")
    if core_manifest.get("database_sha256") != BASE_DB_SHA256:
        raise ValueError("core manifest database_sha256 differs from the pinned DB baseline")
    return db_hash, manifest_hash, core_manifest


def event_values(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(date.fromisoformat(row["event_date"]) if name == "event_date" else row[name]
                 for name in EVENT_FIELDS)


def check_raw_and_ledger(connection: duckdb.DuckDBPyConnection,
                         event_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    expected = {
        row["observation_id"]: (
            str(row["observation_id"]), str(row["event_date"]), str(row["meet_raw"]),
            str(row["official_horse_id"]), str(row["horse_name_raw"]),
            str(row["rider_type_raw"]), str(row["rider_id_raw"]),
            str(row["started_at_raw"]), str(row["ended_at_raw"]),
        )
        for row in event_rows
    }
    query = "SELECT observation_id,event_date::VARCHAR,meet,official_horse_id,horse_name_raw,rider_type_raw,rider_id_raw,started_at_raw,ended_at_raw FROM daily_training_raw WHERE rider_id_raw=?"
    raw = {row[0]: tuple(row) for row in connection.execute(query, ["080626"]).fetchall()}
    if raw != expected:
        raise ValueError("the current raw 080626 rows differ from the exact 31-row evidence tuple set")
    checks.append({"name": "current_raw_rows_match_31_evidence_tuples", "status": "passed", "rows": len(raw)})
    if int(connection.execute("SELECT count(*) FROM rider_unmatched_ids").fetchone()[0]) != 70:
        raise ValueError("rider_unmatched_ids no longer contains the original 70 rows")
    ledger = connection.execute("SELECT daily_training_rows,identity_status FROM rider_unmatched_ids WHERE rider_id_raw=?", ["080626"]).fetchone()
    if ledger != (31, "profile_id_unmatched"):
        raise ValueError("the historical 080626 unmatched ledger row changed")
    if int(connection.execute("SELECT count(*) FROM rider_unmatched_ids WHERE rider_id_raw<>'080626'").fetchone()[0]) != 69:
        raise ValueError("the 69 other unmatched IDs are not all present")
    if int(connection.execute("SELECT count(*) FROM rider_name_links").fetchone()[0]) != 282:
        raise ValueError("the global profile name mapping count changed")
    profile = connection.execute("SELECT name_snapshot,official_jockey_id_raw_string FROM rider_name_links WHERE rider_id_raw=?", ["080584"]).fetchone()
    if profile != ("다비드", "080584"):
        raise ValueError("the existing official 080584 profile mapping changed")
    if connection.execute("SELECT count(*) FROM rider_name_links WHERE rider_id_raw=?", ["080626"]).fetchone()[0] != 0:
        raise ValueError("raw 080626 unexpectedly has a profile-ID mapping")
    if connection.execute("SELECT count(*) FROM rider_identity_conflict_holds WHERE observation_id IN (SELECT observation_id FROM daily_training_raw WHERE rider_id_raw='080626')").fetchone()[0] != 0:
        raise ValueError("approved event rows overlap a source-conflict hold")
    checks.append({"name": "profile_mapping_unmatched_ledger_and_hold_scope_preserved", "status": "passed",
                   "profile_links": 282, "unmatched_ids": 70, "other_unmatched_ids": 69})
    return checks


def insert_event_rows(connection: duckdb.DuckDBPyConnection,
                      event_rows: list[dict[str, Any]]) -> None:
    marks = ",".join("?" for _ in EVENT_FIELDS)
    sql = f"INSERT INTO {TABLE_NAME} ({','.join(EVENT_FIELDS)}) VALUES ({marks})"
    connection.executemany(sql, [event_values(row) for row in event_rows])


def run_view_checks(connection: duckdb.DuckDBPyConnection,
                    event_rows: list[dict[str, Any]], expected_source_manifests: int) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    ids = [row["observation_id"] for row in event_rows]
    marks = ",".join("?" for _ in ids)
    rows = connection.execute(f"""
        SELECT observation_id,rider_id_raw,horse_name_raw,started_at_raw,ended_at_raw,
               rider_name_candidate,rider_name_linked,rider_official_id_candidate,
               rider_official_id_linked,rider_identity_status,rider_name_basis,
               event_verification_status,event_verification_web_rider_display_raw,
               rider_profile_source_service,rider_profile_source_file,rider_profile_source_sha256,
               event_name_source_service,event_name_source_file,event_name_source_sha256,
               event_name_evidence_file,event_name_evidence_sha256,event_name_matching_method,
               event_name_web_row_no
        FROM daily_training_rider_linked WHERE observation_id IN ({marks})
    """, ids).fetchall()
    if len(rows) != 31:
        raise ValueError(f"linked view returns {len(rows)} approved rows, expected 31")
    by_id = {row[0]: row for row in rows}
    for item in event_rows:
        row = by_id.get(item["observation_id"])
        if row is None:
            raise ValueError(f"approved event missing from linked view: {item['observation_id']}")
        expected = (
            item["observation_id"], "080626", item["horse_name_raw"], item["started_at_raw"],
            item["ended_at_raw"], "다비드", "다비드", None, None, "exact_event_web_name_link",
            MATCHING_METHOD, "exact_event_web_name_verified_profile_id_unmatched", "다비드",
            None, None, None, item["source_service"], item["source_file"], item["source_sha256"],
            item["evidence_file"], item["evidence_sha256"], MATCHING_METHOD, item["web_row_no"],
        )
        if row != expected:
            raise ValueError(f"approved event view values differ: {item['observation_id']}")
    checks.append({"name": "approved_31_names_status_ids_verification_and_provenance", "status": "passed", "rows": 31})

    total = int(connection.execute("SELECT count(*) FROM daily_training_rider_linked").fetchone()[0])
    if total != 5_173_033:
        raise ValueError(f"linked view row count changed: {total}")
    ledger = connection.execute("SELECT daily_training_rows,identity_status FROM rider_unmatched_ids WHERE rider_id_raw=?", ["080626"]).fetchone()
    if ledger != (31, "profile_id_unmatched"):
        raise ValueError("the historical 080626 unmatched ledger was changed")
    legacy = connection.execute("""
        SELECT count(DISTINCT u.rider_id_raw), count(*),
               count(*) FILTER (WHERE v.rider_identity_status='profile_id_unmatched'
                                  AND v.rider_name_candidate IS NULL AND v.rider_name_linked IS NULL)
        FROM rider_unmatched_ids u JOIN daily_training_rider_linked v USING (rider_id_raw)
        WHERE u.rider_id_raw<>'080626'
    """).fetchone()
    if legacy != (69, 190_344, 190_344):
        raise ValueError(f"legacy 69 unmatched IDs changed: {legacy}")
    if int(connection.execute("SELECT count(*) FROM source_manifests").fetchone()[0]) != expected_source_manifests:
        raise ValueError("source_manifests row count differs from expected stage")
    checks.append({"name": "raw_view_legacy_unmatched_and_source_manifest_counts", "status": "passed",
                   "linked_rows": total, "legacy_unmatched_ids": legacy[0], "legacy_unmatched_rows": legacy[1],
                   "source_manifests": expected_source_manifests})

    hold = connection.execute("""
        SELECT v.rider_name_candidate,v.rider_name_linked,v.rider_official_id_candidate,
               v.rider_official_id_linked,v.rider_identity_status,v.event_verification_status,
               v.event_verification_web_rider_display_raw,v.rider_link_hold_reason,
               v.event_name_source_file
        FROM daily_training_rider_linked v WHERE v.observation_id=?
    """, [CONFLICT_OBSERVATION_ID]).fetchone()
    expected_hold = ("오수철", None, "080608", None, "source_conflict_hold",
                     "exact_event_web_name_conflicts_profile_hold", "유승완", hold[7] if hold else None, None)
    if hold != expected_hold or not hold[7]:
        raise ValueError("Songdang Sky source-conflict hold or linked-view result changed")
    other_080608 = connection.execute("""
        SELECT count(*) FILTER (WHERE rider_name_linked IS NOT NULL), count(*)
        FROM daily_training_rider_linked WHERE rider_id_raw='080608' AND observation_id<>?
    """, [CONFLICT_OBSERVATION_ID]).fetchone()
    if other_080608 != (5866, 5866):
        raise ValueError(f"unrelated 080608 rows changed: {other_080608}")
    checks.append({"name": "songdang_sky_hold_priority_and_other_080608_links", "status": "passed",
                   "held_observation": CONFLICT_OBSERVATION_ID, "other_080608_linked": 5866})
    return checks


def schema_sql(temporary: bool = False) -> str:
    sql = SCHEMA.read_text(encoding="utf-8")
    if temporary:
        sql = sql.replace(f"CREATE TABLE {TABLE_NAME}", f"CREATE TEMP TABLE {TABLE_NAME}", 1)
        sql = sql.replace("CREATE VIEW daily_training_rider_linked", "CREATE TEMP VIEW daily_training_rider_linked", 1)
    return sql


def execute_schema(connection: duckdb.DuckDBPyConnection, temporary: bool = False) -> None:
    for statement in schema_sql(temporary).split(";"):
        if statement.strip():
            connection.execute(statement)


def tracked_hashes(manifest: dict[str, Any], input_hashes: dict[str, str]) -> dict[str, str]:
    result = dict(input_hashes)
    for path in (INPUT_MANIFEST, SCHEMA, Path(__file__).resolve()):
        result[path.relative_to(ROOT).as_posix()] = sha256_file(path)
    return result


def run_prepare() -> dict[str, Any]:
    manifest, events, hashes = load_inputs()
    return {"status": "inputs_prepared", "rows": len(events), "date_counts": EXPECTED_DATES,
            "input_hashes": tracked_hashes(manifest, hashes), "database_read_or_written": False}


def run_dry_run() -> dict[str, Any]:
    manifest, events, hashes = load_inputs()
    db_hash, manifest_hash, _ = current_identity()
    memory = duckdb.connect(":memory:")
    escaped = str(CORE_DB.resolve()).replace("'", "''")
    memory.execute(f"ATTACH '{escaped}' AS core_db (READ_ONLY)")
    memory.execute("USE core_db")
    checks = check_raw_and_ledger(memory, events)
    memory.execute("SELECT count(*) FROM rider_web_event_verification").fetchone()
    if memory.execute("SELECT count(*) FROM source_manifests WHERE name=?", [SOURCE_MANIFEST_NAME]).fetchone()[0]:
        raise ValueError("event-name source manifest is already registered")
    execute_schema(memory, temporary=True)
    insert_event_rows(memory, events)
    checks.extend(run_view_checks(memory, events, 28))
    memory.close()
    report = {
        "status": "dry_run_passed", "applied": False,
        "database_sha256_before": db_hash, "core_manifest_sha256_before": manifest_hash,
        "source_manifests_before": 28, "source_manifests_after_apply": 29,
        "expected_new_table_rows": 31, "expected_new_main_objects": 1,
        "linked_view_rows": 5_173_033, "checks": checks,
        "input_hashes": tracked_hashes(manifest, hashes),
        "database_mode": "read_only core attached to in-memory DuckDB; temporary schema only",
    }
    write_json_atomic(REPORTS / "dry_run_report.json", report)
    return report


def verify_backup_pair() -> dict[str, Any]:
    attestation = json.loads(BACKUP_ATTESTATION.read_text(encoding="utf-8"))
    attested = (attestation.get("verified_equal") is True
                or (attestation.get("status") == "verified_equal"
                    and attestation.get("source_unchanged") is True))
    if (not attested
            or attestation.get("baseline_db_sha256") != BASE_DB_SHA256
            or attestation.get("baseline_manifest_sha256") != BASE_MANIFEST_SHA256
            or attestation.get("backup_db_sha256") != BASE_DB_SHA256
            or attestation.get("backup_manifest_sha256") != BASE_MANIFEST_SHA256):
        raise ValueError("root backup-pair attestation does not match the pinned baseline")
    db_hash, manifest_hash = sha256_file(BACKUP_DB), sha256_file(BACKUP_MANIFEST)
    if (db_hash, manifest_hash) != (BASE_DB_SHA256, BASE_MANIFEST_SHA256):
        raise ValueError("backup files no longer match the verified baseline pair")
    return {"path": BACKUP_ATTESTATION.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(BACKUP_ATTESTATION), "database_sha256": db_hash,
            "manifest_sha256": manifest_hash, "verified_equal": True}


def source_manifest_value(manifest: dict[str, Any], hashes: dict[str, str]) -> dict[str, Any]:
    records = []
    for path, digest in hashes.items():
        records.append({"path": path, "sha256": digest,
                        "rows": 31 if path == manifest["evidence_file"] else None})
    for path in (INPUT_MANIFEST, SCHEMA, Path(__file__).resolve()):
        relative = path.relative_to(ROOT).as_posix()
        records.append({"path": relative, "sha256": sha256_file(path), "rows": None})
    return {
        "name": SOURCE_MANIFEST_NAME, "schema_version": "daily_training_rider_event_names_v1",
        "baseline_database_sha256": BASE_DB_SHA256,
        "baseline_core_manifest_sha256": BASE_MANIFEST_SHA256,
        "scope": {"rider_id_raw": "080626", "event_dates": EXPECTED_DATES,
                  "event_count": 31, "meet_raw": "3"},
        "event_name": "다비드", "identity_rule": IDENTITY_LIMIT,
        "matching_method": MATCHING_METHOD,
        "official_jockey_id_assignment": None,
        "source_tables": ["daily_training_raw", "rider_name_links", "rider_unmatched_ids",
                          "rider_identity_conflict_holds", "rider_web_event_verification"],
        "global_profile_name_links_changed": False,
        "historical_unmatched_ledger_changed": False,
        "source_conflict_holds_changed": False,
        "files": records,
    }


def catalog_signature(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    objects = dict(connection.execute("""
        SELECT table_name,table_type FROM information_schema.tables WHERE table_schema='main'
    """).fetchall())
    columns = connection.execute("""
        SELECT table_name,column_name,ordinal_position,data_type,is_nullable
        FROM information_schema.columns WHERE table_schema='main'
        ORDER BY table_name,ordinal_position
    """).fetchall()
    views = connection.execute("SELECT view_name,sql FROM duckdb_views() WHERE schema_name='main'").fetchall()
    return {"objects": objects, "columns": columns, "views": views}


def update_external_manifest(before: dict[str, Any], after_hash: str,
                             source_manifest: dict[str, Any], backup: dict[str, Any]) -> dict[str, Any]:
    updated = dict(before)
    updated["database_sha256"] = after_hash
    counts = dict(before["table_and_view_counts"])
    counts[TABLE_NAME] = 31
    counts["daily_training_rider_linked"] = 5_173_033
    counts["source_manifests"] = 29
    updated["table_and_view_counts"] = counts
    additions = []
    existing_by_path = {row.get("path"): row for row in before.get("input_files", [])}
    for record in source_manifest["files"]:
        previous = existing_by_path.get(record["path"])
        if previous is not None:
            if previous.get("sha256") != record["sha256"]:
                raise ValueError(f"existing core input hash differs for {record['path']}")
            continue
        additions.append({"table": f"{TABLE_NAME}_input", **record})
    updated["input_files"] = list(before["input_files"]) + additions
    source_text = canonical_json(source_manifest)
    updated["supplement_loads"] = list(before.get("supplement_loads", [])) + [{
        "name": SOURCE_MANIFEST_NAME,
        "applied_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "baseline_database_sha256": BASE_DB_SHA256, "database_sha256_after": after_hash,
        "backup_database": BACKUP_DB.relative_to(ROOT).as_posix(),
        "backup_manifest": BACKUP_MANIFEST.relative_to(ROOT).as_posix(),
        "backup_pair_attestation": backup["path"], "source_manifest_name": SOURCE_MANIFEST_NAME,
        "new_main_object_counts": {TABLE_NAME: 31, "daily_training_rider_linked": 5_173_033,
                                    "main_objects_after": 214, "source_manifests_after": 29},
        "source_manifest_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "loader_sha256": sha256_file(Path(__file__).resolve()),
        "schema_sha256": sha256_file(SCHEMA),
    }]
    return updated


def run_apply() -> dict[str, Any]:
    report_path = REPORTS / "dry_run_report.json"
    if not report_path.is_file():
        raise ValueError("run --dry-run and retain its passing report before --apply")
    dry = json.loads(report_path.read_text(encoding="utf-8"))
    if dry.get("status") != "dry_run_passed" or dry.get("applied") is not False:
        raise ValueError("the most recent dry-run report is missing or did not pass")
    db_hash, manifest_hash, core_before = current_identity()
    if (db_hash, manifest_hash) != (dry["database_sha256_before"], dry["core_manifest_sha256_before"]):
        raise ValueError("core DB or manifest changed since dry-run")
    manifest, events, hashes = load_inputs()
    input_hashes = tracked_hashes(manifest, hashes)
    if dry.get("input_hashes") != input_hashes:
        raise ValueError("input, schema, or loader hash changed since dry-run")
    backup = verify_backup_pair()
    connection = duckdb.connect(str(CORE_DB), read_only=False)
    committed = False
    before_signature = catalog_signature(connection)
    if (len(before_signature["objects"]) != 213 or TABLE_NAME in before_signature["objects"]
            or int(connection.execute("SELECT count(*) FROM source_manifests").fetchone()[0]) != 28
            or connection.execute("SELECT count(*) FROM source_manifests WHERE name=?", [SOURCE_MANIFEST_NAME]).fetchone()[0]):
        connection.close()
        raise ValueError("core catalog or source manifest count differs from the pinned pre-append state")
    try:
        checks = check_raw_and_ledger(connection, events)
        connection.execute("BEGIN TRANSACTION")
        connection.execute("DROP VIEW daily_training_rider_linked")
        execute_schema(connection)
        insert_event_rows(connection, events)
        checks.extend(run_view_checks(connection, events, 28))
        source_manifest = source_manifest_value(manifest, hashes)
        connection.execute("INSERT INTO source_manifests(name,json_text) VALUES (?,?)",
                           [SOURCE_MANIFEST_NAME, canonical_json(source_manifest)])
        source_count_after = int(connection.execute("SELECT count(*) FROM source_manifests").fetchone()[0])
        if source_count_after != 29:
            raise ValueError(f"source_manifests count after append is {source_count_after}, expected 29")
        checks.append({"name": "source_manifest_appended", "status": "passed", "rows_after": source_count_after})
        after_signature = catalog_signature(connection)
        expected_objects = dict(before_signature["objects"])
        expected_objects[TABLE_NAME] = "BASE TABLE"
        expected_objects["daily_training_rider_linked"] = "VIEW"
        if after_signature["objects"] != expected_objects:
            raise ValueError("core catalog changed beyond the one declared table and linked view replacement")
        before_cols = [row for row in before_signature["columns"] if row[0] != "daily_training_rider_linked"]
        after_cols = [row for row in after_signature["columns"] if row[0] not in ("daily_training_rider_linked", TABLE_NAME)]
        if before_cols != after_cols:
            raise ValueError("an existing non-linked object column definition changed")
        before_views = {name: sql for name, sql in before_signature["views"] if name != "daily_training_rider_linked"}
        after_views = {name: sql for name, sql in after_signature["views"] if name != "daily_training_rider_linked"}
        if before_views != after_views:
            raise ValueError("an unrelated view definition changed")
        connection.execute("COMMIT")
        committed = True
    except Exception:
        if not committed:
            try:
                connection.execute("ROLLBACK")
            except Exception:
                pass
        connection.close()
        raise
    connection.close()

    try:
        after_hash = sha256_file(CORE_DB)
        updated = update_external_manifest(core_before, after_hash, source_manifest, backup)
        write_json_atomic(CORE_MANIFEST, updated)
        if json.loads(CORE_MANIFEST.read_text(encoding="utf-8")).get("database_sha256") != after_hash:
            raise ValueError("core manifest DB hash failed after update")
        result = {"status": "applied_and_verified", "applied": True,
                  "database_sha256_before": BASE_DB_SHA256, "database_sha256_after": after_hash,
                  "core_manifest_sha256_after": sha256_file(CORE_MANIFEST),
                  "source_manifest_name": SOURCE_MANIFEST_NAME, "source_manifests_after": 29,
                  "new_table_rows": 31, "main_objects_after": 214,
                  "backup_verification": backup, "checks": checks}
        write_json_atomic(REPORTS / "apply_report.json", result)
        return result
    except Exception:
        shutil.copy2(BACKUP_DB, CORE_DB)
        shutil.copy2(BACKUP_MANIFEST, CORE_MANIFEST)
        if sha256_file(CORE_DB) != BASE_DB_SHA256 or sha256_file(CORE_MANIFEST) != BASE_MANIFEST_SHA256:
            raise RuntimeError("apply failed and backup-pair restore did not verify")
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true", help="validate pinned inputs and official page matches")
    group.add_argument("--dry-run", action="store_true", help="validate against a read-only attached core in memory")
    group.add_argument("--apply", action="store_true", help="append after passing dry-run and verified backup pair")
    args = parser.parse_args()
    report = run_prepare() if args.prepare else run_dry_run() if args.dry_run else run_apply()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"inputs_prepared", "dry_run_passed", "applied_and_verified"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
