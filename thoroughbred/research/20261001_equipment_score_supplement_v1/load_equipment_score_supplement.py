"""Validate and optionally append the retrospective equipment score supplement.

Default behavior is a read-only dry run. The write path is intentionally
opt-in and pinned to the reviewed core DuckDB path and its pre-change hash.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
REVIEW = ROOT / "thoroughbred/research/20261001_equipment_unobserved_review_v1"
CORE_DIR = ROOT / "thoroughbred/data/core_api_2010_20260929_v1"
CORE_DB = CORE_DIR / "thoroughbred_core.duckdb"
CORE_MANIFEST = CORE_DIR / "manifest.json"
BACKUP_DIR = CORE_DIR / "backups/20261001_before_equipment_score_supplement"

PIN_FILE = OUT / "source_hashes.json"
REPORT_FILE = OUT / "dry_run_report.json"
LOAD_MANIFEST_FILE = OUT / "load_manifest.json"

EXPECTED_BASE_DB_SHA256 = "c3cd5caf16991293e852405f49988f201a2f2c595bd5abd6e727fcd13e39267e"
EXPECTED_SOURCE_MANIFEST_NAME = "equipment_score_supplement_v1"
STATUS_RETROSPECTIVE = "retrospective_score_observation_not_verified_pre_race"
STATUS_API78 = "row_not_provided_in_requeried_api"
SCORE_SOURCE = "KRA_official_score_html"
MARK_RE = re.compile(r"^(.+?)\s*([+-])\s*$")

RUNNER_COLUMNS = [
    "meet",
    "result_date",
    "race_no",
    "horse_no",
    "horse_id",
    "horse_name_raw",
    "normalrank",
    "equipment_raw",
    "source",
    "source_url",
    "observed_at_kst",
    "observed_at_basis",
    "raw_path",
    "raw_sha256",
    "availability_status",
    "api78_status",
]
TOKEN_COLUMNS = [
    "meet",
    "result_date",
    "race_no",
    "horse_no",
    "horse_id",
    "token_position",
    "token_raw",
    "equipment_name_raw",
    "mark_status",
    "source",
    "source_url",
    "observed_at_kst",
    "observed_at_basis",
    "raw_path",
    "raw_sha256",
    "availability_status",
    "api78_status",
]

RUNNER_SCHEMA_SQL = """CREATE TABLE equipment_score_supplement (
    meet VARCHAR NOT NULL,
    result_date VARCHAR NOT NULL,
    race_no VARCHAR NOT NULL,
    horse_no VARCHAR NOT NULL,
    horse_id VARCHAR NOT NULL,
    horse_name_raw VARCHAR NOT NULL,
    normalrank VARCHAR NOT NULL,
    equipment_raw VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    source_url VARCHAR NOT NULL,
    observed_at_kst VARCHAR NOT NULL,
    observed_at_basis VARCHAR NOT NULL,
    raw_path VARCHAR NOT NULL,
    raw_sha256 VARCHAR NOT NULL,
    availability_status VARCHAR NOT NULL,
    api78_status VARCHAR NOT NULL,
    PRIMARY KEY (meet, result_date, race_no, horse_no, horse_id)
)"""

TOKEN_SCHEMA_SQL = """CREATE TABLE equipment_score_supplement_tokens (
    meet VARCHAR NOT NULL,
    result_date VARCHAR NOT NULL,
    race_no VARCHAR NOT NULL,
    horse_no VARCHAR NOT NULL,
    horse_id VARCHAR NOT NULL,
    token_position INTEGER NOT NULL,
    token_raw VARCHAR NOT NULL,
    equipment_name_raw VARCHAR NOT NULL,
    mark_status VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    source_url VARCHAR NOT NULL,
    observed_at_kst VARCHAR NOT NULL,
    observed_at_basis VARCHAR NOT NULL,
    raw_path VARCHAR NOT NULL,
    raw_sha256 VARCHAR NOT NULL,
    availability_status VARCHAR NOT NULL,
    api78_status VARCHAR NOT NULL,
    PRIMARY KEY (meet, result_date, race_no, horse_no, horse_id, token_position)
)"""

ACTIVE_VIEW_SQL = """CREATE VIEW equipment_score_supplement_active_declared AS
SELECT *
FROM equipment_score_supplement_tokens
WHERE mark_status IN ('unmarked', 'new')"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as stream:
        temp_path = Path(stream.name)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    temp_path.replace(path)


def contained_file(relative_path: str, allowed_dir: Path) -> Path:
    candidate = (ROOT / relative_path).resolve(strict=True)
    if not candidate.is_relative_to(allowed_dir.resolve(strict=True)):
        raise ValueError(f"source path escapes allowed directory: {relative_path}")
    if not candidate.is_file():
        raise ValueError(f"source path is not a file: {relative_path}")
    return candidate


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def key_of(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row["meet"]),
        str(row.get("result_date", row.get("date", ""))).replace("-", ""),
        str(row.get("race_no", "")),
        str(row.get("horse_no", "")),
        str(row.get("horse_id", "")),
    )


def inspect_inputs() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Hash-pin inputs and independently verify all 103 saved score HTML pages."""
    pins = load_json(PIN_FILE)
    pinned_files = pins.get("files")
    if not isinstance(pinned_files, dict):
        raise ValueError("source_hashes.json has no files map")

    fixed_inputs = {
        "score_supplement_candidates.csv": REVIEW / "score_supplement_candidates.csv",
        "score_supplement_tokens.csv": REVIEW / "score_supplement_tokens.csv",
        "official_checks.json": REVIEW / "official_checks.json",
        "root_verification.json": REVIEW / "root_verification.json",
    }
    checked_hashes: dict[str, str] = {}
    for name, path in fixed_inputs.items():
        pin = pinned_files.get(name)
        if not path.is_file() or not isinstance(pin, str):
            raise ValueError(f"missing pinned source input: {name}")
        actual = sha256_file(path)
        if actual != pin:
            raise ValueError(f"input hash mismatch: {name}")
        checked_hashes[name] = actual

    expected_db_sha = pins.get("baseline_database_sha256")
    manifest = load_json(CORE_MANIFEST)
    if expected_db_sha != EXPECTED_BASE_DB_SHA256:
        raise ValueError("source pin baseline database hash does not match code pin")
    database_sha = sha256_file(CORE_DB)
    if manifest.get("database_sha256") != database_sha:
        raise ValueError("core database hash and current core manifest disagree")

    root_check = load_json(fixed_inputs["root_verification.json"])
    if root_check.get("passed") is not True:
        raise ValueError("prior root verification did not pass")
    official = load_json(fixed_inputs["official_checks.json"])
    if len(official.get("targets", [])) != 104:
        raise ValueError("official checks target count is not 104")
    if len(official.get("official_score", [])) != 103:
        raise ValueError("official score page count is not 103")

    # Reuse the verified score parser and Korean-name normalizer from the
    # preceding review package. Import has no network or database side effects.
    sys.path.insert(0, str(REVIEW))
    from check_official import name_key, score_table  # noqa: PLC0415
    from verify_and_prepare import verify_header  # noqa: PLC0415

    candidates = read_csv(fixed_inputs["score_supplement_candidates.csv"])
    tokens = read_csv(fixed_inputs["score_supplement_tokens.csv"])
    if len(candidates) != 104 or len(tokens) != 170:
        raise ValueError(f"expected 104 candidate rows and 170 token rows; got {len(candidates)} and {len(tokens)}")
    if len({key_of(row) for row in candidates}) != 104:
        raise ValueError("candidate natural keys are not unique")
    if any(row.get("candidate_only_not_loaded") != "True" for row in candidates):
        raise ValueError("candidate ledger contains a row not marked candidate-only")
    if any(row.get("availability_status") != STATUS_RETROSPECTIVE for row in candidates):
        raise ValueError("candidate availability status is not retrospective-only")
    if any(row.get("api78_status") != STATUS_API78 for row in candidates):
        raise ValueError("candidate API78 missing status changed")

    # Metadata is keyed by official score event. Candidate rows retain date as
    # ISO text; the official evidence ledger uses YYYYMMDD.
    score_records: dict[tuple[str, str, str], dict[str, Any]] = {}
    raw_pin_entries = pins.get("raw_score_html", [])
    if not isinstance(raw_pin_entries, list) or len(raw_pin_entries) != 103:
        raise ValueError("source hash pin must list exactly 103 raw score HTML files")
    raw_pins = {entry["path"]: entry["sha256"] for entry in raw_pin_entries}
    if len(raw_pins) != 103:
        raise ValueError("raw score HTML pin paths are not unique")

    for record in official["official_score"]:
        meta = record["metadata"]
        event = (str(record["meet"]), str(record["date"]).replace("-", ""), str(record["race"]))
        if event in score_records:
            raise ValueError(f"duplicate official score page event: {event}")
        artifact = str(meta["artifact"])
        if artifact not in raw_pins or raw_pins[artifact] != meta.get("sha256"):
            raise ValueError(f"official score metadata does not match raw source pin: {artifact}")
        score_records[event] = record

    if set(score_records) != {
        (str(row["meet"]), row["date"].replace("-", ""), str(row["race_no"]))
        for row in candidates
    }:
        raise ValueError("official score page set does not match candidate event set")

    token_map: dict[tuple[str, str, str, str, str], list[dict[str, str]]] = {}
    for token in tokens:
        k = key_of(token)
        token_map.setdefault(k, []).append(token)
    if set(token_map) != {key_of(row) for row in candidates}:
        raise ValueError("token table does not cover exactly the candidate keys")

    raw_checked: dict[str, str] = {}
    token_counts = {"unmarked": 0, "new": 0, "removed": 0}
    runner_rows: list[dict[str, Any]] = []
    token_rows: list[dict[str, Any]] = []

    for candidate in candidates:
        k = key_of(candidate)
        event = (k[0], k[1], k[2])
        record = score_records[event]
        meta = record["metadata"]
        artifact = str(meta["artifact"])
        raw_path = contained_file(artifact, REVIEW / "official")
        actual_hash = sha256_file(raw_path)
        if actual_hash != raw_pins[artifact] or actual_hash != candidate["sha256"]:
            raise ValueError(f"raw HTML SHA-256 mismatch: {artifact}")
        if candidate["raw_path"] != artifact:
            raise ValueError(f"candidate raw path mismatch for {k}")
        raw_checked[artifact] = actual_hash

        content = raw_path.read_bytes()
        verify_header(record, content)
        rows_by_program = score_table(content)
        score_row = rows_by_program.get(int(k[3]))
        if score_row is None:
            raise ValueError(f"candidate program number missing from official score HTML: {k}")
        expected_target = next(
            (target for target in record["target_checks"] if str(target["horse_no"]) == k[3]),
            None,
        )
        if expected_target is None:
            raise ValueError(f"official check row absent for candidate key: {k}")
        checks = {
            "horse_id": score_row.get("horse_id") == k[4] == str(expected_target["horse_id"]),
            "horse_name": name_key(str(score_row.get("name", ""))) == name_key(candidate["horse_name"]),
            "rank": str(score_row.get("rank", "")) == str(expected_target["core_rank"]),
            "equipment": str(score_row.get("equipment_raw", "")).strip() == candidate["equipment_raw"].strip(),
            "source_url": candidate["source_url"].startswith(str(meta["source_url"]) + "?"),
            "retrieved_at": candidate["retrieved_at_kst"] == meta["retrieved_at_kst"],
        }
        if not all(checks.values()):
            raise ValueError(f"official score row/provenance mismatch for {k}: {checks}")
        if candidate["retrieved_at_basis"] != meta.get("retrieved_at_basis"):
            raise ValueError(f"retrieval timestamp basis mismatch for {k}")

        runner = {
            "meet": k[0],
            "result_date": k[1],
            "race_no": k[2],
            "horse_no": k[3],
            "horse_id": k[4],
            "horse_name_raw": candidate["horse_name"],
            "normalrank": str(score_row["rank"]),
            "equipment_raw": candidate["equipment_raw"],
            "source": candidate["source"],
            "source_url": candidate["source_url"],
            "observed_at_kst": candidate["retrieved_at_kst"],
            "observed_at_basis": candidate["retrieved_at_basis"],
            "raw_path": candidate["raw_path"],
            "raw_sha256": candidate["sha256"],
            "availability_status": candidate["availability_status"],
            "api78_status": candidate["api78_status"],
        }
        runner_rows.append(runner)

        pieces: list[tuple[int, str, str, str]] = []
        for position, raw_token in enumerate(candidate["equipment_raw"].split(","), start=1):
            token_raw = raw_token.strip()
            if not token_raw:
                continue
            mark = MARK_RE.fullmatch(token_raw)
            if mark and mark.group(2) == "+":
                status, name = "new", mark.group(1).strip()
            elif mark and mark.group(2) == "-":
                status, name = "removed", mark.group(1).strip()
            else:
                status, name = "unmarked", token_raw
            pieces.append((position, token_raw, name, status))
            token_counts[status] += 1

        observed_tokens = sorted(token_map[k], key=lambda row: int(row["position"]))
        expected_tokens = [
            (str(position), raw, name, status)
            for position, raw, name, status in pieces
        ]
        actual_tokens = [
            (row["position"], row["token_raw"], row["equipment_name_raw"], row["mark"])
            for row in observed_tokens
        ]
        if actual_tokens != expected_tokens:
            raise ValueError(f"ordered token parse mismatch for {k}")

        for position, token_raw, name, status in pieces:
            token_rows.append(
                {
                    "meet": k[0],
                    "result_date": k[1],
                    "race_no": k[2],
                    "horse_no": k[3],
                    "horse_id": k[4],
                    "token_position": position,
                    "token_raw": token_raw,
                    "equipment_name_raw": name,
                    "mark_status": status,
                    "source": candidate["source"],
                    "source_url": candidate["source_url"],
                    "observed_at_kst": candidate["retrieved_at_kst"],
                    "observed_at_basis": candidate["retrieved_at_basis"],
                    "raw_path": candidate["raw_path"],
                    "raw_sha256": candidate["sha256"],
                    "availability_status": candidate["availability_status"],
                    "api78_status": candidate["api78_status"],
                }
            )

    if set(raw_checked) != set(raw_pins):
        raise ValueError("pinned raw HTML set differs from verified candidate evidence set")
    if len(runner_rows) != 104 or len(token_rows) != 170 or token_counts != {"unmarked": 163, "new": 3, "removed": 4}:
        raise ValueError(f"supplement totals changed: rows={len(runner_rows)}, tokens={len(token_rows)}, marks={token_counts}")

    checked_hashes["core_database"] = database_sha
    return runner_rows, token_rows, {
        "fixed_input_hashes": checked_hashes,
        "raw_score_html_count": len(raw_checked),
        "raw_score_html_hashes": raw_checked,
        "token_counts": token_counts,
        "official_checks_targets": 104,
        "official_score_pages": 103,
    }


def catalog_objects(connection: duckdb.DuckDBPyConnection) -> dict[str, str]:
    rows = connection.execute(
        "SELECT table_name, table_type FROM information_schema.tables "
        "WHERE table_schema='main' ORDER BY table_name"
    ).fetchall()
    return {str(name): str(kind) for name, kind in rows}


def check_core_links(
    connection: duckdb.DuckDBPyConnection,
    runner_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    linked = 0
    ranks: list[str] = []
    for runner in runner_rows:
        rows = connection.execute(
            "SELECT result_rank_raw, horse_name_raw FROM confirmed_runners "
            "WHERE source_meet=? AND result_date=? AND result_race_no=? "
            "AND horse_program_no_raw=? AND horse_id_raw=?",
            [
                runner["meet"],
                runner["result_date"],
                runner["race_no"],
                runner["horse_no"],
                runner["horse_id"],
            ],
        ).fetchall()
        if len(rows) != 1:
            raise ValueError(f"core exact natural-key link count is {len(rows)} for {key_of(runner)}")
        rank = str(rows[0][0] or "").strip()
        if not rank.isdigit() or not 1 <= int(rank) <= 30:
            raise ValueError(f"core normalrank is not a normal finish rank for {key_of(runner)}: {rank!r}")
        if rank != runner["normalrank"]:
            raise ValueError(f"official/core rank mismatch for {key_of(runner)}: {rank} vs {runner['normalrank']}")
        ranks.append(rank)
        linked += 1
    return {"candidate_rows": len(runner_rows), "unique_exact_core_links": linked, "normalrank_rows_1_to_30": len(ranks)}


def source_manifest_value(source_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 1,
        "source": SCORE_SOURCE,
        "scope": "104 confirmed Seoul/Busan-Gyeongnam runner score observations with API78 row not provided",
        "interpretation": STATUS_RETROSPECTIVE,
        "api78_status": STATUS_API78,
        "candidate_file": {
            "path": "thoroughbred/research/20261001_equipment_unobserved_review_v1/score_supplement_candidates.csv",
            "sha256": source_summary["fixed_input_hashes"]["score_supplement_candidates.csv"],
            "rows": 104,
        },
        "token_file": {
            "path": "thoroughbred/research/20261001_equipment_unobserved_review_v1/score_supplement_tokens.csv",
            "sha256": source_summary["fixed_input_hashes"]["score_supplement_tokens.csv"],
            "rows": 170,
        },
        "raw_score_html_count": source_summary["raw_score_html_count"],
        "raw_score_html_sha256_by_path": source_summary["raw_score_html_hashes"],
        "token_mark_counts": source_summary["token_counts"],
        "tables": {
            "equipment_score_supplement": 104,
            "equipment_score_supplement_tokens": 170,
        },
        "active_declared_view": "equipment_score_supplement_active_declared",
        "view_rule": "mark_status IN ('unmarked', 'new'); signed source token remains unchanged",
        "limitations": [
            "A retrospective score observation is not evidence that the value was known before the race.",
            "A declared equipment token does not establish that equipment was physically worn.",
            "A missing equipment list does not establish that no equipment was used.",
        ],
    }


def dry_run_report(
    runner_rows: list[dict[str, Any]],
    token_rows: list[dict[str, Any]],
    source_summary: dict[str, Any],
) -> dict[str, Any]:
    if sha256_file(CORE_DB) != EXPECTED_BASE_DB_SHA256:
        raise ValueError("core database is not at its reviewed pre-append state")
    if load_json(CORE_MANIFEST).get("database_sha256") != EXPECTED_BASE_DB_SHA256:
        raise ValueError("core manifest changed during validation")
    connection = duckdb.connect(str(CORE_DB), read_only=True)
    prior_catalog_object_count = 0
    try:
        before = catalog_objects(connection)
        prior_catalog_object_count = len(before)
        for name in (
            "equipment_score_supplement",
            "equipment_score_supplement_tokens",
            "equipment_score_supplement_active_declared",
        ):
            if name in before:
                raise ValueError(f"target object already exists in core database: {name}")
        duplicate_manifest = connection.execute(
            "SELECT count(*) FROM source_manifests WHERE name=?", [EXPECTED_SOURCE_MANIFEST_NAME]
        ).fetchone()[0]
        if duplicate_manifest:
            raise ValueError("source_manifests already contains equipment_score_supplement_v1")
        source_manifest_count = connection.execute("SELECT count(*) FROM source_manifests").fetchone()[0]
        if source_manifest_count != 20:
            raise ValueError(f"expected 20 baseline source manifest rows, found {source_manifest_count}")
        core_check = check_core_links(connection, runner_rows)
    finally:
        connection.close()

    return {
        "status": "dry_run_passed",
        "applied": False,
        "core_database": str(CORE_DB.relative_to(ROOT)),
        "core_database_sha256_before": EXPECTED_BASE_DB_SHA256,
        "prior_core_catalog_objects": prior_catalog_object_count,
        "candidate_rows": len(runner_rows),
        "token_rows": len(token_rows),
        "active_declared_token_rows": sum(row["mark_status"] in ("unmarked", "new") for row in token_rows),
        "removed_token_rows_retained_but_excluded_from_active_view": sum(row["mark_status"] == "removed" for row in token_rows),
        "core_link_check": core_check,
        "official_evidence_check": {
            "raw_score_html_hashes_verified": source_summary["raw_score_html_count"],
            "official_score_targets": source_summary["official_checks_targets"],
            "candidate_rows_exactly_reparsed": len(runner_rows),
            "source_status": STATUS_RETROSPECTIVE,
            "api78_status": STATUS_API78,
        },
        "token_marks": source_summary["token_counts"],
        "proposed_objects": [
            {"name": "equipment_score_supplement", "type": "BASE TABLE", "rows": len(runner_rows), "key": ["meet", "result_date", "race_no", "horse_no", "horse_id"]},
            {"name": "equipment_score_supplement_tokens", "type": "BASE TABLE", "rows": len(token_rows), "key": ["meet", "result_date", "race_no", "horse_no", "horse_id", "token_position"]},
            {"name": "equipment_score_supplement_active_declared", "type": "VIEW", "rows": sum(row["mark_status"] in ("unmarked", "new") for row in token_rows), "rule": "mark_status IN ('unmarked', 'new')"},
        ],
        "source_hashes": source_summary["fixed_input_hashes"],
        "raw_score_html_sha256_by_path": source_summary["raw_score_html_hashes"],
        "core_manifest_plan": {
            "preserve_existing_fields": True,
            "append_input_file_entries": 2,
            "append_source_manifest_row": EXPECTED_SOURCE_MANIFEST_NAME,
            "append_separate_load_manifest": str(LOAD_MANIFEST_FILE.relative_to(ROOT)),
            "backup_directory": str(BACKUP_DIR.relative_to(ROOT)),
        },
        "safety_notes": [
            "No core database or core manifest writes occurred during this run.",
            "All IDs and ranks are held as text; leading zeroes are preserved.",
            "The active view means declared list status only, not physical wear.",
            "An empty declaration is not interpreted as no equipment used.",
        ],
    }


def rows_as_tuples(rows: list[dict[str, Any]], columns: list[str]) -> list[tuple[Any, ...]]:
    return [tuple(row[col] for col in columns) for row in rows]


def verify_existing_rows(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    expected_rows: list[dict[str, Any]],
    columns: list[str],
    key_columns: tuple[str, ...],
) -> bool:
    actual = connection.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
    if len(actual) != len(expected_rows):
        return False
    expected = {tuple(row[col] for col in key_columns): tuple(row[col] for col in columns) for row in expected_rows}
    observed = {tuple(record[columns.index(col)] for col in key_columns): record for record in actual}
    return expected == observed


def verify_applied_replay(
    runner_rows: list[dict[str, Any]],
    token_rows: list[dict[str, Any]],
    source_summary: dict[str, Any],
    prior_load: dict[str, Any],
) -> dict[str, Any]:
    """Read-only verification for reruns after a successful prior append."""
    current_sha = sha256_file(CORE_DB)
    current_core_manifest = load_json(CORE_MANIFEST)
    if current_sha != prior_load.get("database_sha256_after"):
        raise ValueError("database hash differs from the recorded applied load; refusing replay")
    if current_core_manifest.get("database_sha256") != current_sha:
        raise ValueError("core manifest does not match the recorded applied database")
    if prior_load.get("baseline_database_sha256") != EXPECTED_BASE_DB_SHA256:
        raise ValueError("applied load manifest has an unexpected baseline hash")
    if prior_load.get("backup_database") != str((BACKUP_DIR / CORE_DB.name).relative_to(ROOT)):
        raise ValueError("applied load manifest points to an unexpected database backup")
    if prior_load.get("backup_manifest") != str((BACKUP_DIR / CORE_MANIFEST.name).relative_to(ROOT)):
        raise ValueError("applied load manifest points to an unexpected manifest backup")

    backup_db = BACKUP_DIR / CORE_DB.name
    backup_manifest_path = BACKUP_DIR / CORE_MANIFEST.name
    if not backup_db.is_file() or sha256_file(backup_db) != EXPECTED_BASE_DB_SHA256:
        raise ValueError("pre-append database backup is missing or does not match the pinned baseline")
    if not backup_manifest_path.is_file():
        raise ValueError("pre-append core manifest backup is missing")
    baseline_manifest = load_json(backup_manifest_path)
    if baseline_manifest.get("database_sha256") != EXPECTED_BASE_DB_SHA256:
        raise ValueError("pre-append core manifest backup does not match the pinned baseline")

    source_manifest_text = json.dumps(source_manifest_value(source_summary), ensure_ascii=False, sort_keys=True)
    baseline = duckdb.connect(str(backup_db), read_only=True)
    current = duckdb.connect(str(CORE_DB), read_only=True)
    try:
        base_objects = catalog_objects(baseline)
        current_objects = catalog_objects(current)
        expected_objects = {
            "equipment_score_supplement": "BASE TABLE",
            "equipment_score_supplement_tokens": "BASE TABLE",
            "equipment_score_supplement_active_declared": "VIEW",
        }
        if current_objects != {**base_objects, **expected_objects}:
            raise ValueError("current catalog differs from baseline plus the three supplement objects")
        if not verify_existing_rows(
            current,
            "equipment_score_supplement",
            runner_rows,
            RUNNER_COLUMNS,
            ("meet", "result_date", "race_no", "horse_no", "horse_id"),
        ):
            raise ValueError("applied runner supplement rows differ from pinned evidence")
        if not verify_existing_rows(
            current,
            "equipment_score_supplement_tokens",
            token_rows,
            TOKEN_COLUMNS,
            ("meet", "result_date", "race_no", "horse_no", "horse_id", "token_position"),
        ):
            raise ValueError("applied token supplement rows differ from pinned evidence")
        active_rows = [row for row in token_rows if row["mark_status"] in ("unmarked", "new")]
        if not verify_existing_rows(
            current,
            "equipment_score_supplement_active_declared",
            active_rows,
            TOKEN_COLUMNS,
            ("meet", "result_date", "race_no", "horse_no", "horse_id", "token_position"),
        ):
            raise ValueError("active declared view rows differ from unmarked/new source tokens")

        baseline_manifests = sorted(baseline.execute("SELECT name, json_text FROM source_manifests").fetchall())
        current_manifests = sorted(current.execute("SELECT name, json_text FROM source_manifests").fetchall())
        expected_manifests = sorted(
            baseline_manifests + [(EXPECTED_SOURCE_MANIFEST_NAME, source_manifest_text)]
        )
        if current_manifests != expected_manifests or len(current_manifests) != 21:
            raise ValueError("source_manifests does not equal its 20-row baseline plus the supplement record")
    finally:
        baseline.close()
        current.close()

    # The core manifest preserves every baseline field, with explicit append
    # exceptions for its DB hash, appended inputs, object counts, and load log.
    allowed_changed_fields = {"database_sha256", "input_files", "table_and_view_counts", "supplement_loads"}
    for key, value in baseline_manifest.items():
        if key not in allowed_changed_fields and current_core_manifest.get(key) != value:
            raise ValueError(f"core manifest prior field changed during append: {key}")
    base_inputs = baseline_manifest.get("input_files", [])
    current_inputs = current_core_manifest.get("input_files", [])
    if current_inputs[: len(base_inputs)] != base_inputs:
        raise ValueError("core manifest original input records were not preserved in order")
    expected_counts = dict(baseline_manifest.get("table_and_view_counts", {}))
    expected_counts.update(
        {
            "equipment_score_supplement": 104,
            "equipment_score_supplement_tokens": 170,
            "equipment_score_supplement_active_declared": 166,
            "source_manifests": 21,
        }
    )
    if current_core_manifest.get("table_and_view_counts") != expected_counts:
        raise ValueError("core manifest object counts differ from the expected supplement append")
    load_rows = current_core_manifest.get("supplement_loads", [])
    if not any(
        row.get("name") == "equipment_score_supplement_v1"
        and row.get("database_sha256_after") == current_sha
        for row in load_rows
        if isinstance(row, dict)
    ):
        raise ValueError("core manifest has no matching equipment supplement load record")

    return {
        "status": "already_applied_verified",
        "applied": True,
        "database_mutated_during_replay": False,
        "core_database_sha256": current_sha,
        "baseline_database_sha256": EXPECTED_BASE_DB_SHA256,
        "runner_rows_verified": len(runner_rows),
        "token_rows_verified": len(token_rows),
        "active_declared_rows_verified": len(active_rows),
        "source_manifests_rows_verified": 21,
        "raw_score_html_hashes_reverified": source_summary["raw_score_html_count"],
        "backup_database": prior_load["backup_database"],
        "backup_manifest": prior_load["backup_manifest"],
    }


def current_source_manifest(connection: duckdb.DuckDBPyConnection) -> str | None:
    rows = connection.execute(
        "SELECT json_text FROM source_manifests WHERE name=?", [EXPECTED_SOURCE_MANIFEST_NAME]
    ).fetchall()
    if len(rows) > 1:
        raise ValueError("duplicate supplement source manifest records")
    return str(rows[0][0]) if rows else None


def apply_transaction(
    runner_rows: list[dict[str, Any]],
    token_rows: list[dict[str, Any]],
    source_summary: dict[str, Any],
) -> dict[str, Any]:
    """Append through one DuckDB transaction after a paired DB/manifest backup."""
    manifest_before_bytes = CORE_MANIFEST.read_bytes()
    manifest_before = json.loads(manifest_before_bytes.decode("utf-8"))
    if sha256_file(CORE_DB) != EXPECTED_BASE_DB_SHA256:
        raise ValueError("core database changed after dry run; refusing write")
    if manifest_before.get("database_sha256") != EXPECTED_BASE_DB_SHA256:
        raise ValueError("core manifest changed after dry run; refusing write")

    BACKUP_DIR.mkdir(parents=True, exist_ok=False)
    backup_db = BACKUP_DIR / CORE_DB.name
    backup_manifest = BACKUP_DIR / CORE_MANIFEST.name
    shutil.copy2(CORE_DB, backup_db)
    shutil.copy2(CORE_MANIFEST, backup_manifest)
    if sha256_file(backup_db) != EXPECTED_BASE_DB_SHA256 or sha256_file(backup_manifest) != hashlib.sha256(manifest_before_bytes).hexdigest():
        raise ValueError("pre-write backup hash verification failed")

    source_manifest = source_manifest_value(source_summary)
    source_manifest_text = json.dumps(source_manifest, ensure_ascii=False, sort_keys=True)
    applied_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    connection = duckdb.connect(str(CORE_DB), read_only=False)
    db_committed = False
    try:
        before = catalog_objects(connection)
        desired = {
            "equipment_score_supplement": "BASE TABLE",
            "equipment_score_supplement_tokens": "BASE TABLE",
            "equipment_score_supplement_active_declared": "VIEW",
        }
        present = {name: before.get(name) for name in desired if name in before}
        if present and set(present) != set(desired):
            raise ValueError(f"partial prior supplement objects exist; refusing append: {present}")

        connection.execute("BEGIN TRANSACTION")
        if not present:
            connection.execute(RUNNER_SCHEMA_SQL)
            connection.execute(TOKEN_SCHEMA_SQL)
            connection.execute(ACTIVE_VIEW_SQL)
            runner_marks = ", ".join("?" for _ in RUNNER_COLUMNS)
            token_marks = ", ".join("?" for _ in TOKEN_COLUMNS)
            connection.executemany(
                f"INSERT INTO equipment_score_supplement ({', '.join(RUNNER_COLUMNS)}) VALUES ({runner_marks})",
                rows_as_tuples(runner_rows, RUNNER_COLUMNS),
            )
            connection.executemany(
                f"INSERT INTO equipment_score_supplement_tokens ({', '.join(TOKEN_COLUMNS)}) VALUES ({token_marks})",
                rows_as_tuples(token_rows, TOKEN_COLUMNS),
            )
            connection.execute(
                "INSERT INTO source_manifests(name, json_text) VALUES (?, ?)",
                [EXPECTED_SOURCE_MANIFEST_NAME, source_manifest_text],
            )
        else:
            if not verify_existing_rows(
                connection,
                "equipment_score_supplement",
                runner_rows,
                RUNNER_COLUMNS,
                ("meet", "result_date", "race_no", "horse_no", "horse_id"),
            ):
                raise ValueError("existing equipment score rows differ from pinned input; refusing idempotent apply")
            if not verify_existing_rows(
                connection,
                "equipment_score_supplement_tokens",
                token_rows,
                TOKEN_COLUMNS,
                ("meet", "result_date", "race_no", "horse_no", "horse_id", "token_position"),
            ):
                raise ValueError("existing equipment token rows differ from pinned input; refusing idempotent apply")
            existing_source_manifest = current_source_manifest(connection)
            if existing_source_manifest != source_manifest_text:
                raise ValueError("existing source manifest differs from pinned input; refusing idempotent apply")
            view_sql = connection.execute(
                "SELECT sql FROM duckdb_views() WHERE view_name=?", ["equipment_score_supplement_active_declared"]
            ).fetchone()
            if not view_sql or "mark_status IN ('unmarked', 'new')" not in str(view_sql[0]):
                raise ValueError("existing active declared view definition is not the expected filter")

        after = catalog_objects(connection)
        allowed_names = set(desired)
        if set(after) != set(before) | allowed_names:
            # Existing full set may be the verified idempotent case.
            if set(after) != set(before):
                raise ValueError("catalog changed beyond the three approved supplement objects")
        if any(after.get(name) != kind for name, kind in desired.items()):
            raise ValueError("created supplement object type mismatch")
        connection.execute("COMMIT")
        db_committed = True
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        connection.close()

    try:
        new_db_sha = sha256_file(CORE_DB)
        updated_manifest = json.loads(json.dumps(manifest_before))
        updated_manifest["database_sha256"] = new_db_sha
        updated_manifest.setdefault("input_files", [])
        supplement_inputs = [
            {
                "table": "equipment_score_supplement",
                "path": "thoroughbred/research/20261001_equipment_unobserved_review_v1/score_supplement_candidates.csv",
                "sha256": source_summary["fixed_input_hashes"]["score_supplement_candidates.csv"],
                "rows": 104,
            },
            {
                "table": "equipment_score_supplement_tokens",
                "path": "thoroughbred/research/20261001_equipment_unobserved_review_v1/score_supplement_tokens.csv",
                "sha256": source_summary["fixed_input_hashes"]["score_supplement_tokens.csv"],
                "rows": 170,
            },
        ]
        existing_paths = {entry.get("path") for entry in updated_manifest["input_files"] if isinstance(entry, dict)}
        for entry in supplement_inputs:
            if entry["path"] not in existing_paths:
                updated_manifest["input_files"].append(entry)
        updated_manifest.setdefault("table_and_view_counts", {})
        updated_manifest["table_and_view_counts"].update(
            {
                "equipment_score_supplement": 104,
                "equipment_score_supplement_tokens": 170,
                "equipment_score_supplement_active_declared": 166,
                "source_manifests": 21,
            }
        )
        load_entry = {
            "name": "equipment_score_supplement_v1",
            "applied_at_utc": applied_at,
            "baseline_database_sha256": EXPECTED_BASE_DB_SHA256,
            "database_sha256_after": new_db_sha,
            "backup_database": str(backup_db.relative_to(ROOT)),
            "backup_manifest": str(backup_manifest.relative_to(ROOT)),
            "source_manifest_name": EXPECTED_SOURCE_MANIFEST_NAME,
            "runner_rows": 104,
            "token_rows": 170,
        }
        loads = updated_manifest.setdefault("supplement_loads", [])
        if not any(row.get("name") == load_entry["name"] for row in loads if isinstance(row, dict)):
            loads.append(load_entry)
        write_json_atomic(CORE_MANIFEST, updated_manifest)
        if load_json(CORE_MANIFEST).get("database_sha256") != new_db_sha:
            raise ValueError("updated core manifest failed post-write hash readback")
        load_manifest = {
            "status": "applied",
            "applied": True,
            **load_entry,
            "source_hashes": source_summary["fixed_input_hashes"],
            "raw_score_html_count": source_summary["raw_score_html_count"],
            "token_marks": source_summary["token_counts"],
        }
        write_json_atomic(LOAD_MANIFEST_FILE, load_manifest)
        return load_manifest
    except Exception:
        # If filesystem manifest finalization fails after DB commit, restore the
        # paired snapshots so the database and manifest remain a matched pair.
        if db_committed:
            shutil.copy2(backup_db, CORE_DB)
            shutil.copy2(backup_manifest, CORE_MANIFEST)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="append the verified supplement to the pinned core DB")
    parser.add_argument(
        "--confirm-core-append",
        action="store_true",
        help="required second opt-in for a core DB write; root must direct this separately",
    )
    args = parser.parse_args()
    if args.apply != args.confirm_core_append:
        parser.error("core writes require both --apply and --confirm-core-append")

    runner_rows, token_rows, source_summary = inspect_inputs()
    if LOAD_MANIFEST_FILE.is_file():
        prior_load = load_json(LOAD_MANIFEST_FILE)
        if prior_load.get("status") == "applied" and prior_load.get("applied") is True:
            replay = verify_applied_replay(runner_rows, token_rows, source_summary, prior_load)
            print(json.dumps(replay, ensure_ascii=False, indent=2))
            return
    if source_summary["fixed_input_hashes"]["core_database"] != EXPECTED_BASE_DB_SHA256:
        raise SystemExit("core database changed without a matching applied load manifest; refusing write or report")
    report = dry_run_report(runner_rows, token_rows, source_summary)
    write_json_atomic(REPORT_FILE, report)
    if args.apply:
        result = apply_transaction(runner_rows, token_rows, source_summary)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        dry_load_manifest = {
            "status": "dry_run_passed",
            "applied": False,
            "core_database": str(CORE_DB.relative_to(ROOT)),
            "baseline_database_sha256": EXPECTED_BASE_DB_SHA256,
            "runner_rows_proposed": len(runner_rows),
            "token_rows_proposed": len(token_rows),
            "input_hashes": source_summary["fixed_input_hashes"],
            "raw_score_html_count": source_summary["raw_score_html_count"],
            "token_marks": source_summary["token_counts"],
            "report": str(REPORT_FILE.relative_to(ROOT)),
        }
        write_json_atomic(LOAD_MANIFEST_FILE, dry_load_manifest)
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
