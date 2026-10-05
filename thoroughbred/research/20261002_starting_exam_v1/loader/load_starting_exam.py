"""Read-only validate, then optionally append the API21_1 starting-exam research set."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
DATASET_DIR = OUT.parent
CORE_DIR = ROOT / "thoroughbred/data/core_api_2010_20260929_v1"
CORE_DB = CORE_DIR / "thoroughbred_core.duckdb"
CORE_MANIFEST = CORE_DIR / "manifest.json"
BACKUP_DIR = CORE_DIR / "backups/20261002_before_starting_exam"
PARQUET = DATASET_DIR / "input/starting_exam.parquet"
CAPTURE_MANIFEST = DATASET_DIR / "raw/capture_manifest.json"
COVERAGE_FILE = DATASET_DIR / "raw/coverage_summary.json"
BASE_DB_SHA256 = "5c9fa0e4d53a776a643d045440717727c5a9299b158f43ea93109eb53e770ec7"
SOURCE_NAME = "starting_exam_api21_1_v1"
AVAILABILITY = "retrospective_starting_exam_not_verified_pre_race"
VENUE_STATUS = "raw_meet_preserved_physical_venue_unadjudicated"
START_DATE = date(2010, 1, 1)
END_DATE = date(2026, 9, 29)
MEETS = ("1", "3")
YEARS = tuple(range(2010, 2027))
ENDPOINT = "API21_1"
API_FIELDS = (
    "meet", "trainDate", "daySerial", "trainNo", "chulNo", "hrName", "hrNo",
    "name", "sex", "age", "rider", "trName", "trNo", "owName", "owNo",
    "passFlag", "reason", "nopassReason",
)
INPUT_COLUMNS = (
    "dataset", "observation_id", "event_date", "meet", "official_horse_id", "raw_name",
    "raw_path", "raw_sha256", "source_page_no", "source_row_no", "source_captured_at",
    "capture_basis", "endpoint", "raw_payload_json", "typed_fields_json", "link_status",
    "linked_core_horse_id", "qa_flags_json", "capture_id",
)
TABLE_COLUMNS = INPUT_COLUMNS + (
    "availability_status", "historical_prerace_eligibility_verified", "physical_venue_status",
)
OBJECTS = {
    "starting_exam_observations": "BASE TABLE",
    "starting_exam_source_files": "BASE TABLE",
    "starting_exam_partition_coverage": "BASE TABLE",
    "starting_exam_results": "VIEW",
    "starting_exam_sessions": "VIEW",
    "starting_exam_qa": "VIEW",
    "starting_exam_date_coverage": "VIEW",
    "starting_exam_entity_links": "VIEW",
}
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def safe_path(relative: str, *, must_exist: bool = True) -> Path:
    if not isinstance(relative, str) or not relative or "://" in relative:
        raise ValueError(f"invalid repository-relative path: {relative!r}")
    path = (ROOT / relative).resolve(strict=must_exist)
    if not path.is_relative_to(ROOT.resolve(strict=True)):
        raise ValueError(f"path escapes repository root: {relative}")
    if must_exist and not path.is_file():
        raise ValueError(f"expected a file: {relative}")
    return path


def parse_int(value: Any, label: str, *, optional: bool = False) -> int | None:
    if optional and value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer: {value!r}") from exc


def parse_timestamp(value: Any, label: str) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO timestamp or null")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
        if not re.search(r"[+-]\d{2}:?\d{2}$", text):
            text += "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def expected_partitions() -> set[tuple[int, str]]:
    return {(year, meet) for year in YEARS for meet in MEETS}


def normalize_inputs() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    manifest = json_load(CAPTURE_MANIFEST)
    coverage = json_load(COVERAGE_FILE)
    if manifest.get("dataset") != "starting_exam" or manifest.get("endpoint") != ENDPOINT:
        raise ValueError("capture manifest dataset/endpoint mismatch")
    if coverage.get("dataset") != "starting_exam" or coverage.get("endpoint") != ENDPOINT:
        raise ValueError("coverage summary dataset/endpoint mismatch")
    expected_scope = {"start_date_inclusive": START_DATE.isoformat(),
                      "end_date_inclusive": END_DATE.isoformat(), "meets": list(MEETS)}
    scope = manifest.get("scope") or {}
    for key, expected in expected_scope.items():
        actual = scope.get(key) if key in ("start_date_inclusive", "end_date_inclusive") else scope.get("meets")
        if actual != expected:
            raise ValueError(f"capture manifest scope mismatch for {key}: {actual!r}")
    for key, expected in (("scope_start_date_inclusive", START_DATE.isoformat()),
                          ("scope_end_date_inclusive", END_DATE.isoformat()),
                          ("meet_scope", list(MEETS))):
        if coverage.get(key) != expected:
            raise ValueError(f"coverage summary scope mismatch for {key}")

    parquet_path = safe_path(str(manifest.get("parquet_path", "")))
    if parquet_path != PARQUET.resolve(strict=True):
        raise ValueError("capture manifest points at a different Parquet file")
    parquet_sha = sha256_file(PARQUET)
    if manifest.get("parquet_sha256") != parquet_sha:
        raise ValueError("starting-exam Parquet SHA-256 mismatch")
    if manifest.get("row_count") is None or int(manifest["row_count"]) < 0:
        raise ValueError("invalid Parquet row_count in capture manifest")

    partitions_raw = coverage.get("partitions")
    sources_raw = manifest.get("source_files")
    if not isinstance(partitions_raw, list) or not isinstance(sources_raw, list):
        raise ValueError("capture/coverage documents require source_files and partitions arrays")
    if int(coverage.get("partition_count_expected", -1)) != 34 or len(partitions_raw) != 34:
        raise ValueError("starting-exam inventory must contain all 34 year×meet partitions")
    partitions: list[dict[str, Any]] = []
    for row in partitions_raw:
        year = parse_int(row.get("year"), "partition.year")
        meet = str(row.get("meet"))
        if (year, meet) not in expected_partitions():
            raise ValueError(f"out-of-scope partition: {year}/{meet}")
        status = str(row.get("status"))
        if status not in {"complete", "zero", "fail"}:
            raise ValueError(f"unknown partition status {status!r} for {year}/{meet}")
        total = parse_int(row.get("total_count"), "partition.total_count", optional=True)
        observed = parse_int(row.get("observed_row_count"), "partition.observed_row_count")
        page_size = parse_int(row.get("page_size"), "partition.page_size", optional=True)
        page_count = parse_int(row.get("page_count"), "partition.page_count")
        capture_id = row.get("capture_id")
        if status == "fail":
            raise ValueError(f"source capture is incomplete for {year}/{meet}: {row.get('failure_class')}")
        if not capture_id or observed < 0 or page_count < 0:
            raise ValueError(f"invalid partition metadata for {year}/{meet}")
        if status == "zero" and (total != 0 or observed != 0):
            raise ValueError(f"zero partition has nonzero counts for {year}/{meet}")
        if status == "complete" and (total is None or total <= 0 or total != observed):
            raise ValueError(f"complete partition count mismatch for {year}/{meet}")
        partitions.append({
            "dataset": "starting_exam", "capture_year": year, "meet": meet,
            "coverage_status": status, "selected_capture_id": str(capture_id),
            "expected_rows": total, "observed_rows": observed,
            "page_size": page_size, "page_count": page_count,
            "failure_class": row.get("failure_class"),
            "started_at_utc": parse_timestamp(row.get("started_at_utc"), "partition.started_at_utc"),
            "finished_at_utc": parse_timestamp(row.get("finished_at_utc"), "partition.finished_at_utc"),
            "coverage_basis": "verified API21_1 year×meet response pages; daily absence derives from a complete partition",
        })
    partition_keys = [(row["capture_year"], row["meet"]) for row in partitions]
    if set(partition_keys) != expected_partitions() or len(partition_keys) != len(set(partition_keys)):
        raise ValueError("partition ledger does not exactly cover the requested 34 year×meet cells")
    selected_capture = {(row["capture_year"], row["meet"]): row["selected_capture_id"] for row in partitions}

    source_files: list[dict[str, Any]] = []
    seen_pages: set[tuple[int, str, str, int]] = set()
    for item in sources_raw:
        year = parse_int(item.get("year"), "source_file.year")
        meet = str(item.get("meet"))
        capture_id = str(item.get("capture_id") or "")
        page_no = parse_int(item.get("source_page_no"), "source_file.source_page_no", optional=True)
        raw_path = item.get("raw_path")
        raw_sha = str(item.get("raw_sha256") or "").lower()
        row_count = parse_int(item.get("source_row_count", 0), "source_file.source_row_count")
        page_total = parse_int(item.get("page_total_count"), "source_file.page_total_count", optional=True)
        item_count = parse_int(item.get("page_item_count"), "source_file.page_item_count", optional=True)
        page_size = parse_int(item.get("page_size"), "source_file.page_size", optional=True)
        status_code = parse_int(item.get("status_code"), "source_file.status_code", optional=True)
        result_code = item.get("result_code")
        failure_class = item.get("failure_class")
        if (year, meet) not in expected_partitions() or not capture_id or row_count < 0:
            raise ValueError("invalid or out-of-scope source file metadata")
        key = (year, meet, capture_id, page_no or -1)
        if key in seen_pages:
            raise ValueError(f"duplicate source page ledger key: {key}")
        seen_pages.add(key)
        selected = bool(raw_path) and selected_capture[(year, meet)] == capture_id and not failure_class
        actual_sha = None
        if raw_path:
            if not HASH_RE.fullmatch(raw_sha):
                raise ValueError(f"invalid page SHA-256: {raw_path}")
            source_path = safe_path(str(raw_path))
            actual_sha = sha256_file(source_path)
            if actual_sha != raw_sha:
                raise ValueError(f"raw API page SHA-256 mismatch: {raw_path}")
        if selected and page_no is None:
            raise ValueError(f"selected raw page lacks a page number: {raw_path}")
        safe_metadata = {
            key: item.get(key) for key in (
                "status_code", "result_code", "failure_class", "response_bytes", "content_type",
            ) if key in item
        }
        source_files.append({
            "dataset": "starting_exam", "meet": meet, "capture_year": year,
            "capture_id": capture_id, "source_page_no": page_no,
            "raw_path": str(raw_path) if raw_path else None,
            "raw_sha256": raw_sha if raw_path else None,
            "source_row_count": row_count, "page_total_count": page_total,
            "page_item_count": item_count, "page_size": page_size,
            "requested_at_utc": parse_timestamp(item.get("requested_at_utc"), "source_file.requested_at_utc"),
            "retrieved_at_utc": parse_timestamp(item.get("retrieved_at_utc"), "source_file.retrieved_at_utc"),
            "source_captured_at_utc": parse_timestamp(item.get("source_captured_at_utc"), "source_file.source_captured_at_utc"),
            "status_code": status_code, "result_code": str(result_code) if result_code is not None else None,
            "failure_class": str(failure_class) if failure_class is not None else None,
            "is_selected": selected,
            "hash_check_status": "verified" if raw_path else "no_raw_page_file",
            "source_metadata_json": json.dumps(safe_metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        })

    for partition in partitions:
        key = (partition["capture_year"], partition["meet"])
        pages = [f for f in source_files if (f["capture_year"], f["meet"], f["capture_id"]) ==
                 (key[0], key[1], partition["selected_capture_id"]) and f["is_selected"]]
        pages.sort(key=lambda row: row["source_page_no"] or -1)
        if len(pages) != partition["page_count"]:
            raise ValueError(f"selected source page count mismatch for {key}: {len(pages)} != {partition['page_count']}")
        if not pages:
            raise ValueError(f"complete/zero partition has no hash-verified source page: {key}")
        if [p["source_page_no"] for p in pages] != list(range(1, len(pages) + 1)):
            raise ValueError(f"selected page numbers are not contiguous for {key}")
        if sum(p["source_row_count"] for p in pages) != partition["observed_rows"]:
            raise ValueError(f"source page item counts do not match partition total for {key}")
        if any(p["page_total_count"] != partition["expected_rows"] for p in pages):
            raise ValueError(f"selected page totalCount differs from partition ledger for {key}")

    hashes = {
        PARQUET.relative_to(ROOT).as_posix(): parquet_sha,
        CAPTURE_MANIFEST.relative_to(ROOT).as_posix(): sha256_file(CAPTURE_MANIFEST),
        COVERAGE_FILE.relative_to(ROOT).as_posix(): sha256_file(COVERAGE_FILE),
    }
    parquet_connection = duckdb.connect(":memory:")
    try:
        desc = parquet_connection.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(PARQUET)]).fetchall()
        actual_schema = [(str(row[0]), str(row[1]).upper()) for row in desc]
        expected_schema = [
            ("dataset", "VARCHAR"), ("observation_id", "VARCHAR"), ("event_date", "DATE"),
            ("meet", "VARCHAR"), ("official_horse_id", "VARCHAR"), ("raw_name", "VARCHAR"),
            ("raw_path", "VARCHAR"), ("raw_sha256", "VARCHAR"), ("source_page_no", "INTEGER"),
            ("source_row_no", "INTEGER"), ("source_captured_at", "TIMESTAMP"),
            ("capture_basis", "VARCHAR"), ("endpoint", "VARCHAR"), ("raw_payload_json", "VARCHAR"),
            ("typed_fields_json", "VARCHAR"), ("link_status", "VARCHAR"),
            ("linked_core_horse_id", "VARCHAR"), ("qa_flags_json", "VARCHAR"), ("capture_id", "VARCHAR"),
        ]
        if actual_schema != expected_schema:
            raise ValueError(f"Parquet schema does not match the explicit 19-column contract: {actual_schema}")
        row_count = int(parquet_connection.execute("SELECT count(*) FROM read_parquet(?)", [str(PARQUET)]).fetchone()[0])
    finally:
        parquet_connection.close()
    if row_count != int(manifest["row_count"]):
        raise ValueError(f"Parquet count differs from capture manifest: {row_count} != {manifest['row_count']}")
    if coverage.get("scoped_row_counts", {}).get("included_rows") != row_count:
        raise ValueError("coverage summary scoped included_rows differs from the Parquet count")
    if coverage.get("scoped_row_counts", {}).get("invalid_or_missing_date_rows") != 0:
        raise ValueError("coverage summary reports invalid or missing event dates")
    return {"manifest": manifest, "coverage": coverage}, source_files, partitions, hashes


def catalog_objects(connection: duckdb.DuckDBPyConnection) -> dict[str, str]:
    rows = connection.execute("""
        SELECT table_name, table_type FROM information_schema.tables
        WHERE table_catalog=current_database() AND table_schema='main'
    """).fetchall()
    return {str(name): str(kind) for name, kind in rows}


def inspect_core() -> tuple[str, dict[str, str], int, dict[str, Any], bool]:
    db_hash = sha256_file(CORE_DB)
    manifest = json_load(CORE_MANIFEST)
    if manifest.get("database_sha256") != db_hash:
        raise ValueError("research core manifest database_sha256 mismatch")
    con = duckdb.connect(str(CORE_DB), read_only=True)
    try:
        objects = catalog_objects(con)
        sources = int(con.execute("SELECT count(*) FROM source_manifests").fetchone()[0])
        source_rows = int(con.execute("SELECT count(*) FROM source_manifests WHERE name=?", [SOURCE_NAME]).fetchone()[0])
    finally:
        con.close()
    present = {name: objects[name] for name in OBJECTS if name in objects}
    if not present and source_rows == 0:
        if db_hash != BASE_DB_SHA256 or len(objects) != 101 or sources != 23:
            raise ValueError("research core is not the pinned 101-object/23-source baseline")
        replay = False
    elif present == OBJECTS and source_rows == 1 and sources == 24:
        replay = True
    else:
        raise ValueError(f"partial/conflicting starting-exam append: objects={present}, source_rows={source_rows}, sources={sources}")
    return db_hash, objects, sources, manifest, replay


def configure(connection: duckdb.DuckDBPyConnection, temp_dir: Path) -> None:
    connection.execute("SET memory_limit='2GB'")
    connection.execute("SET threads=2")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute("SET temp_directory=" + sql_literal(str(temp_dir)))


def schema_apply(connection: duckdb.DuckDBPyConnection, *, dry_run: bool) -> None:
    text = (OUT / "schema.sql").read_text(encoding="utf-8")
    # Let DuckDB parse statement boundaries so semicolons inside SQL string
    # literals do not split a view definition into invalid fragments.
    for parsed in duckdb.extract_statements(text):
        raw = parsed.query.strip()
        if not raw:
            continue
        statement = re.sub(r"(?m)^\s*--.*$", "", raw).strip()
        if dry_run and statement.upper().startswith("CREATE TABLE STARTING_EXAM_OBSERVATIONS"):
            continue
        if dry_run:
            statement = re.sub(r"^CREATE TABLE\b", "CREATE TEMP TABLE", statement, count=1, flags=re.I)
            statement = re.sub(r"^CREATE VIEW\b", "CREATE TEMP VIEW", statement, count=1, flags=re.I)
        connection.execute(statement)


def coverage_rows() -> list[dict[str, Any]]:
    payload = json_load(COVERAGE_FILE)
    output = []
    for row in payload["partitions"]:
        output.append({
            "dataset": "starting_exam", "capture_year": int(row["year"]), "meet": str(row["meet"]),
            "coverage_status": str(row["status"]), "selected_capture_id": str(row["capture_id"]),
            "expected_rows": parse_int(row.get("total_count"), "partition.total_count", optional=True),
            "observed_rows": int(row["observed_row_count"]),
            "page_size": parse_int(row.get("page_size"), "partition.page_size", optional=True),
            "page_count": int(row["page_count"]), "failure_class": row.get("failure_class"),
            "started_at_utc": parse_timestamp(row.get("started_at_utc"), "partition.started_at_utc"),
            "finished_at_utc": parse_timestamp(row.get("finished_at_utc"), "partition.finished_at_utc"),
            "coverage_basis": "verified API21_1 year×meet response pages; daily absence derives from a complete partition",
        })
    return output


def insert_dict_rows(connection: duckdb.DuckDBPyConnection, table: str,
                     columns: list[str], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    col_sql = ",".join('"' + name + '"' for name in columns)
    placeholders = ",".join("?" for _ in columns)
    values = [tuple(row[name] for name in columns) for row in rows]
    connection.executemany(f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})", values)


def insert_metadata(connection: duckdb.DuckDBPyConnection, files: list[dict[str, Any]],
                     partitions: list[dict[str, Any]]) -> None:
    file_cols = ["dataset", "meet", "capture_year", "capture_id", "source_page_no", "raw_path", "raw_sha256",
                 "source_row_count", "page_total_count", "page_item_count", "page_size", "requested_at_utc",
                 "retrieved_at_utc", "source_captured_at_utc", "status_code", "result_code", "failure_class",
                 "is_selected", "hash_check_status", "source_metadata_json"]
    part_cols = ["dataset", "capture_year", "meet", "coverage_status", "selected_capture_id", "expected_rows",
                 "observed_rows", "page_size", "page_count", "failure_class", "started_at_utc", "finished_at_utc",
                 "coverage_basis"]
    insert_dict_rows(connection, "starting_exam_source_files", file_cols, files)
    insert_dict_rows(connection, "starting_exam_partition_coverage", part_cols, partitions)


def prepare(connection: duckdb.DuckDBPyConnection, files: list[dict[str, Any]],
             partitions: list[dict[str, Any]], *, dry_run: bool) -> None:
    parquet_path = safe_path(PARQUET.relative_to(ROOT).as_posix())
    if dry_run:
        connection.execute("CREATE TEMP VIEW entity_reference_roster AS SELECT * FROM core_db.entity_reference_roster")
        connection.execute(f"""
            CREATE TEMP VIEW starting_exam_observations AS
            SELECT p.*, '{AVAILABILITY}'::VARCHAR AS availability_status,
                   FALSE::BOOLEAN AS historical_prerace_eligibility_verified,
                   '{VENUE_STATUS}'::VARCHAR AS physical_venue_status
            FROM read_parquet({sql_literal(str(parquet_path))}) AS p
        """)
    schema_apply(connection, dry_run=dry_run)
    insert_metadata(connection, files, partitions)


def validate(connection: duckdb.DuckDBPyConnection, manifest: dict[str, Any],
             files: list[dict[str, Any]], partitions: list[dict[str, Any]]) -> dict[str, Any]:
    total = int(connection.execute("SELECT count(*) FROM starting_exam_observations").fetchone()[0])
    distinct_ids = int(connection.execute("SELECT count(DISTINCT observation_id) FROM starting_exam_observations").fetchone()[0])
    if total != int(manifest["row_count"]) or total != distinct_ids:
        raise ValueError(f"starting-exam row count/observation ID gate failed: rows={total}, ids={distinct_ids}")
    scope_bad = int(connection.execute("""
        SELECT count(*) FROM starting_exam_observations
        WHERE dataset<>'starting_exam' OR endpoint<>'API21_1' OR meet NOT IN ('1','3')
           OR event_date<DATE '2010-01-01' OR event_date>DATE '2026-09-29'
           OR year(event_date) NOT BETWEEN 2010 AND 2026
    """).fetchone()[0])
    if scope_bad:
        raise ValueError(f"{scope_bad} observations fall outside the API21_1 scope")
    empty_bad = int(connection.execute("""
        SELECT count(*) FROM starting_exam_observations
        WHERE observation_id IS NULL OR observation_id='' OR raw_path IS NULL OR raw_path=''
           OR raw_sha256 IS NULL OR capture_id IS NULL OR capture_id=''
           OR capture_basis IS NULL OR capture_basis='' OR raw_payload_json IS NULL
           OR typed_fields_json IS NULL OR qa_flags_json IS NULL OR link_status IS NULL
           OR source_page_no IS NULL OR source_page_no<1 OR source_row_no IS NULL OR source_row_no<1
    """).fetchone()[0])
    if empty_bad:
        raise ValueError(f"{empty_bad} observations lack required values or page/row provenance")
    json_bad = int(connection.execute("""
        SELECT count(*) FROM starting_exam_observations
        WHERE NOT json_valid(raw_payload_json) OR NOT json_valid(typed_fields_json)
           OR NOT json_valid(qa_flags_json) OR raw_payload_json<>typed_fields_json
    """).fetchone()[0])
    if json_bad:
        raise ValueError(f"{json_bad} observations have invalid or nonidentical raw/typed JSON")
    expected_api_keys = "(" + ",".join(sql_literal(field) for field in API_FIELDS) + ")"
    api_shape_bad = int(connection.execute(f"""
        SELECT count(*) FROM starting_exam_observations AS o
        WHERE json_type(typed_fields_json)<>'OBJECT'
           OR EXISTS (
                SELECT 1 FROM json_each(o.typed_fields_json) AS field
                WHERE field.key NOT IN {expected_api_keys}
           )
    """).fetchone()[0])
    if api_shape_bad:
        raise ValueError(f"{api_shape_bad} observations contain a key outside the documented 18 API21_1 fields")
    raw_mismatch = int(connection.execute("""
        SELECT count(*) FROM starting_exam_observations
        WHERE json_extract_string(typed_fields_json,'$.trainDate') IS DISTINCT FROM strftime(event_date,'%Y%m%d')
           OR CASE json_extract_string(typed_fields_json,'$.meet')
                WHEN '1' THEN '1' WHEN '서울' THEN '1'
                WHEN '3' THEN '3' WHEN '부산경남' THEN '3' WHEN '부경' THEN '3' WHEN '영남' THEN '3'
                ELSE NULL END IS DISTINCT FROM meet
           OR CASE WHEN json_extract_string(typed_fields_json,'$.hrNo') IS NULL
                         OR json_extract_string(typed_fields_json,'$.hrNo') IN ('','-')
                   THEN NULL ELSE json_extract_string(typed_fields_json,'$.hrNo') END
                IS DISTINCT FROM official_horse_id
           OR json_extract_string(typed_fields_json,'$.hrName') IS DISTINCT FROM raw_name
    """).fetchone()[0])
    if raw_mismatch:
        raise ValueError(f"{raw_mismatch} observations disagree with source date/meet/horse/name fields")
    bad_link = int(connection.execute("""
        SELECT count(*)
        FROM starting_exam_observations o
        LEFT JOIN entity_reference_roster h
          ON h.entity_type='horse' AND h.entity_id_official_string=o.official_horse_id
        WHERE (o.official_horse_id IS NULL AND
               (o.link_status<>'missing_official_id' OR o.linked_core_horse_id IS NOT NULL))
           OR (o.official_horse_id IS NOT NULL AND h.entity_id_official_string IS NOT NULL AND
               (o.link_status<>'exact_core_roster_match' OR o.linked_core_horse_id IS DISTINCT FROM o.official_horse_id))
           OR (o.official_horse_id IS NOT NULL AND h.entity_id_official_string IS NULL AND
               (o.link_status<>'unmatched_official_id' OR o.linked_core_horse_id IS NOT NULL))
    """).fetchone()[0])
    if bad_link:
        raise ValueError(f"{bad_link} exact official horse-ID links are inconsistent with the core roster")
    dup_roster = int(connection.execute("""
        SELECT count(*) FROM (
          SELECT entity_type,entity_id_official_string FROM entity_reference_roster
          WHERE entity_type IN ('horse','trainer','owner')
          GROUP BY entity_type,entity_id_official_string HAVING count(*)>1
        )
    """).fetchone()[0])
    if dup_roster:
        raise ValueError(f"core horse/trainer/owner roster has {dup_roster} duplicated exact IDs")

    unlinked_pages = int(connection.execute("""
        SELECT count(*) FROM starting_exam_observations o
        LEFT JOIN starting_exam_source_files f
          ON f.dataset=o.dataset AND f.meet=o.meet AND f.capture_year=year(o.event_date)
         AND f.capture_id=o.capture_id AND f.raw_path=o.raw_path AND f.raw_sha256=o.raw_sha256
         AND f.source_page_no=o.source_page_no AND f.is_selected
        WHERE f.raw_path IS NULL
    """).fetchone()[0])
    if unlinked_pages:
        raise ValueError(f"{unlinked_pages} observations do not reference a selected hash-verified source page")
    bad_page_row = int(connection.execute("""
        SELECT count(*) FROM starting_exam_observations o
        JOIN starting_exam_source_files f
          ON f.dataset=o.dataset AND f.meet=o.meet AND f.capture_year=year(o.event_date)
         AND f.capture_id=o.capture_id AND f.raw_path=o.raw_path AND f.raw_sha256=o.raw_sha256
         AND f.source_page_no=o.source_page_no AND f.is_selected
        WHERE o.source_row_no>f.source_row_count
    """).fetchone()[0])
    if bad_page_row:
        raise ValueError(f"{bad_page_row} observations have row numbers beyond their source page item count")
    partition_bad = int(connection.execute("""
        SELECT count(*) FROM starting_exam_partition_coverage p
        LEFT JOIN (
          SELECT year(event_date) AS capture_year,meet,count(*) AS rows
          FROM starting_exam_observations GROUP BY 1,2
        ) o USING (capture_year,meet)
        WHERE p.coverage_status NOT IN ('complete','zero')
           OR (p.capture_year<2026 AND coalesce(o.rows,0)<>p.observed_rows)
           OR (p.capture_year=2026 AND coalesce(o.rows,0)>p.observed_rows)
    """).fetchone()[0])
    if partition_bad:
        raise ValueError(f"{partition_bad} partition row-count/scope checks failed")
    bad_coverage = int(connection.execute("""
        SELECT count(*) FROM starting_exam_date_coverage
        WHERE coverage_status NOT IN ('complete_rows','complete_zero_rows')
           OR (coverage_status='complete_rows' AND observed_rows<=0)
           OR (coverage_status='complete_zero_rows' AND observed_rows<>0)
    """).fetchone()[0])
    expected_dates = ((END_DATE - START_DATE).days + 1) * len(MEETS)
    coverage_count = int(connection.execute("SELECT count(*) FROM starting_exam_date_coverage").fetchone()[0])
    if coverage_count != expected_dates or bad_coverage:
        raise ValueError(f"daily date×meet coverage failed: cells={coverage_count}, bad={bad_coverage}")

    counts = {
        "starting_exam_observations": total,
        "starting_exam_source_files": int(connection.execute("SELECT count(*) FROM starting_exam_source_files").fetchone()[0]),
        "starting_exam_partition_coverage": int(connection.execute("SELECT count(*) FROM starting_exam_partition_coverage").fetchone()[0]),
        "starting_exam_results": int(connection.execute("SELECT count(*) FROM starting_exam_results").fetchone()[0]),
        "starting_exam_sessions": int(connection.execute("SELECT count(*) FROM starting_exam_sessions").fetchone()[0]),
        "starting_exam_qa": int(connection.execute("SELECT count(*) FROM starting_exam_qa").fetchone()[0]),
        "starting_exam_date_coverage": coverage_count,
        "starting_exam_entity_links": int(connection.execute("SELECT count(*) FROM starting_exam_entity_links").fetchone()[0]),
    }
    return {
        "dataset_observation_rows": total,
        "unique_observation_ids": distinct_ids,
        "source_file_inventory_rows": counts["starting_exam_source_files"],
        "partition_coverage_rows": counts["starting_exam_partition_coverage"],
        "daily_coverage_rows": coverage_count,
        "complete_partitions": int(connection.execute("SELECT count(*) FROM starting_exam_partition_coverage WHERE coverage_status='complete'").fetchone()[0]),
        "zero_partitions": int(connection.execute("SELECT count(*) FROM starting_exam_partition_coverage WHERE coverage_status='zero'").fetchone()[0]),
        "exact_horse_link_rows": int(connection.execute("SELECT count(*) FROM starting_exam_observations WHERE link_status='exact_core_roster_match'").fetchone()[0]),
        "unmatched_horse_id_rows": int(connection.execute("SELECT count(*) FROM starting_exam_observations WHERE link_status='unmatched_official_id'").fetchone()[0]),
        "missing_horse_id_rows": int(connection.execute("SELECT count(*) FROM starting_exam_observations WHERE link_status='missing_official_id'").fetchone()[0]),
        "rows_with_natural_key_repeat_flag": int(connection.execute("""
            SELECT count(*) FROM starting_exam_observations
            WHERE json_contains(qa_flags_json, '"exact_natural_key_payload_repeat"')
               OR json_contains(qa_flags_json, '"natural_key_payload_variant"')
        """).fetchone()[0]),
        "rows_with_missing_natural_key_component_flag": int(connection.execute("""
            SELECT count(*) FROM starting_exam_observations
            WHERE json_contains(qa_flags_json, '"natural_key_has_missing_component"')
        """).fetchone()[0]),
        "object_row_counts": counts,
    }


def source_manifest_value(manifest: dict[str, Any], hashes: dict[str, str],
                          metrics: dict[str, Any], app_hashes: dict[str, str]) -> dict[str, Any]:
    coverage = json_load(COVERAGE_FILE)
    return {
        "source": "KRA OpenAPI API21_1 starting-test results",
        "dataset": "starting_exam", "endpoint": ENDPOINT,
        "scope": "2010-01-01..2026-09-29 inclusive; meets 1 and 3; no Jeju",
        "capture_selection": "one hash-verified complete API response capture per year×meet partition",
        "availability_status": AVAILABILITY,
        "historical_prerace_eligibility_verified": False,
        "pass_judgment_promotion_performed": False,
        "physical_venue_status": VENUE_STATUS,
        "meet3_note": "raw Yeongnam-region source label is preserved; physical venue is not inferred",
        "identity_rule": "exact official ID string match to entity_reference_roster by entity_type; never link rider by name",
        "placeholder_rule": "retain blank, dash, 휴양마, and other source placeholders separately; never resolve by name",
        "session_rule": "date/meet/daySerial/trainNo is a source grouping only, not a race identity",
        "observation_rule": "retain every API occurrence, exact repeat, and same-key variant without correction",
        "input_sha256": hashes,
        "loader_and_schema_sha256": app_hashes,
        "capture_id": manifest.get("capture_id"),
        "partition_status_counts": coverage.get("partition_status_counts"),
        "dataset_counts": metrics,
        "appended_objects": list(OBJECTS),
    }


def parquet_sql_path() -> str:
    path = PARQUET.resolve(strict=True)
    if not path.is_relative_to(ROOT.resolve(strict=True)):
        raise ValueError("Parquet input is outside the repository")
    return sql_literal(str(path))


def dry_run_report(current_hash: str, source_count: int, metrics: dict[str, Any],
                   hashes: dict[str, str], app_hashes: dict[str, str], replay: bool) -> dict[str, Any]:
    return {
        "status": "dry_run_replay_passed" if replay else "dry_run_passed",
        "applied": False,
        "idempotent_replay": replay,
        "core_database": CORE_DB.relative_to(ROOT).as_posix(),
        "core_database_sha256_before": current_hash,
        "baseline_database_sha256": BASE_DB_SHA256,
        "existing_core_objects": 101,
        "existing_source_manifest_rows": source_count,
        "input_sha256": hashes,
        "loader_and_schema_sha256": app_hashes,
        "dataset_counts": metrics,
        "proposed_objects": [{"name": name, "type": kind, "rows": metrics["object_row_counts"][name]}
                             for name, kind in OBJECTS.items()],
        "proposed_source_manifest": SOURCE_NAME,
        "expected_core_after_apply": {"objects": 109, "source_manifest_rows": 24},
        "backup_directory": BACKUP_DIR.relative_to(ROOT).as_posix(),
        "status_rules": {
            "availability_status": AVAILABILITY,
            "historical_prerace_eligibility_verified": False,
            "pass_flag_adjudication_performed": False,
            "rider_name_linked_to_jockey_id": False,
            "physical_venue_adjudicated": False,
            "session_group_is_race": False,
        },
    }


def row_hash_sql(alias: str) -> str:
    fields = ",".join(f'"{name}" := {alias}."{name}"' for name in TABLE_COLUMNS)
    return f"sha256(to_json(struct_pack({fields})))"


def verify_replay(connection: duckdb.DuckDBPyConnection, expected_source: dict[str, Any],
                  source_count: int) -> dict[str, Any]:
    if source_count != 24:
        raise ValueError("replay core source manifest count must be 24")
    rows = connection.execute("SELECT json_text FROM core_db.source_manifests WHERE name=?", [SOURCE_NAME]).fetchall()
    expected_text = json.dumps(expected_source, ensure_ascii=False, sort_keys=True)
    if len(rows) != 1 or rows[0][0] != expected_text:
        raise ValueError("stored starting-exam source manifest differs from the current frozen inputs/code")
    left = row_hash_sql("stored")
    right = row_hash_sql("incoming")
    diff_a = int(connection.execute(f"""
        SELECT count(*) FROM (
          SELECT {left} AS row_sha FROM core_db.starting_exam_observations AS stored
          EXCEPT ALL
          SELECT {right} AS row_sha FROM starting_exam_observations AS incoming
        )
    """).fetchone()[0])
    diff_b = int(connection.execute(f"""
        SELECT count(*) FROM (
          SELECT {right} AS row_sha FROM starting_exam_observations AS incoming
          EXCEPT ALL
          SELECT {left} AS row_sha FROM core_db.starting_exam_observations AS stored
        )
    """).fetchone()[0])
    if diff_a or diff_b:
        raise ValueError(f"full-row SHA replay parity failed: core-only={diff_a}, input-only={diff_b}")
    return {"core_only_row_hashes": diff_a, "input_only_row_hashes": diff_b, "method": "SHA-256 of every typed table column; bidirectional EXCEPT ALL"}


def metrics_readonly(files: list[dict[str, Any]], partitions: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    scratch = tempfile.TemporaryDirectory(prefix="starting-exam-dryrun-")
    connection = duckdb.connect(":memory:")
    try:
        configure(connection, Path(scratch.name))
        connection.execute(f"ATTACH DATABASE {sql_literal(str(CORE_DB.resolve(strict=True)))} AS core_db (READ_ONLY)")
        prepare(connection, files, partitions, dry_run=True)
        manifest = json_load(CAPTURE_MANIFEST)
        metrics = validate(connection, manifest, files, partitions)
        return metrics, connection
    except Exception:
        connection.close()
        scratch.cleanup()
        raise


def apply_schema_and_rows(connection: duckdb.DuckDBPyConnection, files: list[dict[str, Any]],
                          partitions: list[dict[str, Any]]) -> None:
    schema_apply(connection, dry_run=False)
    insert_metadata(connection, files, partitions)
    cols = ",".join('"' + col + '"' for col in TABLE_COLUMNS)
    in_cols = ",".join('p."' + col + '"' for col in INPUT_COLUMNS)
    connection.execute(f"""
        INSERT INTO starting_exam_observations ({cols})
        SELECT {in_cols}, '{AVAILABILITY}', FALSE, '{VENUE_STATUS}'
        FROM read_parquet({parquet_sql_path()}) AS p
    """)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as stream:
        temp = Path(stream.name)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def backup_copy(source: Path, destination: Path) -> None:
    if destination.exists():
        raise ValueError(f"refusing to overwrite a paired backup file: {destination}")
    if sys.platform == "darwin":
        subprocess.run(["/bin/cp", "-c", str(source), str(destination)], check=True)
    else:
        shutil.copy2(source, destination)


def append_core(manifest: dict[str, Any], files: list[dict[str, Any]], partitions: list[dict[str, Any]],
                hashes: dict[str, str], metrics: dict[str, Any], expected_source: dict[str, Any]) -> dict[str, Any]:
    manifest_bytes = CORE_MANIFEST.read_bytes()
    before_manifest = json.loads(manifest_bytes)
    if sha256_file(CORE_DB) != BASE_DB_SHA256 or before_manifest.get("database_sha256") != BASE_DB_SHA256:
        raise ValueError("research core changed after dry-run; refusing append")
    if BACKUP_DIR.exists():
        raise ValueError(f"paired backup already exists: {BACKUP_DIR}")
    BACKUP_DIR.mkdir(parents=True)
    backup_db, backup_manifest = BACKUP_DIR / CORE_DB.name, BACKUP_DIR / CORE_MANIFEST.name
    backup_copy(CORE_DB, backup_db)
    backup_copy(CORE_MANIFEST, backup_manifest)
    if sha256_file(backup_db) != BASE_DB_SHA256 or sha256_file(backup_manifest) != hashlib.sha256(manifest_bytes).hexdigest():
        raise ValueError("paired pre-append backup verification failed")
    scratch = tempfile.TemporaryDirectory(prefix="starting-exam-apply-")
    connection = duckdb.connect(str(CORE_DB), read_only=False)
    committed = False
    try:
        configure(connection, Path(scratch.name))
        before_objects = catalog_objects(connection)
        before_sources = int(connection.execute("SELECT count(*) FROM source_manifests").fetchone()[0])
        if len(before_objects) != 101 or before_sources != 23 or any(name in before_objects for name in OBJECTS):
            raise ValueError("core append precondition changed")
        connection.execute("BEGIN TRANSACTION")
        apply_schema_and_rows(connection, files, partitions)
        # Temporary roster shadows are avoided here; the permanent core table resolves these views.
        actual = validate(connection, manifest, files, partitions)
        if actual != metrics:
            raise ValueError("pre-commit counts differ from the reviewed read-only dry-run")
        source_text = json.dumps(expected_source, ensure_ascii=False, sort_keys=True)
        connection.execute("INSERT INTO source_manifests(name,json_text) VALUES (?,?)", [SOURCE_NAME, source_text])
        after_objects = catalog_objects(connection)
        expected_after = dict(before_objects)
        expected_after.update(OBJECTS)
        if after_objects != expected_after or int(connection.execute("SELECT count(*) FROM source_manifests").fetchone()[0]) != 24:
            raise ValueError("post-append catalog/source-manifest gate failed")
        connection.execute("COMMIT")
        committed = True
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except Exception:
            pass
        connection.close()
        scratch.cleanup()
        raise
    connection.close()
    scratch.cleanup()
    try:
        after_hash = sha256_file(CORE_DB)
        updated = json.loads(json.dumps(before_manifest))
        updated["database_sha256"] = after_hash
        inputs = updated.setdefault("input_files", [])
        known = {row.get("path") for row in inputs if isinstance(row, dict)}
        report_hashes = dict(hashes)
        report_hashes.update({
            (OUT / "load_starting_exam.py").relative_to(ROOT).as_posix(): sha256_file(OUT / "load_starting_exam.py"),
            (OUT / "schema.sql").relative_to(ROOT).as_posix(): sha256_file(OUT / "schema.sql"),
            (OUT / "input_contract.json").relative_to(ROOT).as_posix(): sha256_file(OUT / "input_contract.json"),
        })
        for path, digest in report_hashes.items():
            if path not in known:
                inputs.append({"table": "starting_exam_observations", "path": path,
                               "sha256": digest, "rows": metrics["dataset_observation_rows"] if path.endswith(".parquet") else None})
                known.add(path)
        counts = updated.setdefault("table_and_view_counts", {})
        counts.update(metrics["object_row_counts"])
        counts["source_manifests"] = 24
        loads = updated.setdefault("supplement_loads", [])
        if any(isinstance(item, dict) and item.get("name") == SOURCE_NAME for item in loads):
            raise ValueError("starting-exam manifest append already exists")
        load_entry = {
            "name": SOURCE_NAME,
            "applied_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "baseline_database_sha256": BASE_DB_SHA256,
            "database_sha256_after": after_hash,
            "backup_database": backup_db.relative_to(ROOT).as_posix(),
            "backup_manifest": backup_manifest.relative_to(ROOT).as_posix(),
            "source_manifest_name": SOURCE_NAME,
            "observation_rows": metrics["dataset_observation_rows"],
            "partition_rows": metrics["partition_coverage_rows"],
            "source_file_rows": metrics["source_file_inventory_rows"],
            "input_sha256": report_hashes,
        }
        loads.append(load_entry)
        write_json_atomic(CORE_MANIFEST, updated)
        if json_load(CORE_MANIFEST).get("database_sha256") != after_hash:
            raise ValueError("core manifest post-write hash check failed")
        return {"status": "applied", "applied": True, **load_entry}
    except Exception:
        if committed:
            shutil.copy2(backup_db, CORE_DB)
            shutil.copy2(backup_manifest, CORE_MANIFEST)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="append only after root review")
    parser.add_argument("--confirm-core-append", action="store_true", help="second explicit core-write flag")
    args = parser.parse_args()
    if args.apply != args.confirm_core_append:
        parser.error("core writes require both --apply and --confirm-core-append")
    normalized, files, partitions, hashes = normalize_inputs()
    manifest = normalized["manifest"]
    current_hash, _, source_count, _, replay = inspect_core()
    app_hashes = {
        "loader": sha256_file(OUT / "load_starting_exam.py"),
        "schema": sha256_file(OUT / "schema.sql"),
        "contract": sha256_file(OUT / "input_contract.json"),
    }
    hashes.update({
        (OUT / "load_starting_exam.py").relative_to(ROOT).as_posix(): app_hashes["loader"],
        (OUT / "schema.sql").relative_to(ROOT).as_posix(): app_hashes["schema"],
        (OUT / "input_contract.json").relative_to(ROOT).as_posix(): app_hashes["contract"],
    })
    scratch = tempfile.TemporaryDirectory(prefix="starting-exam-metrics-")
    connection = duckdb.connect(":memory:")
    try:
        configure(connection, Path(scratch.name))
        connection.execute(f"ATTACH DATABASE {sql_literal(str(CORE_DB.resolve(strict=True)))} AS core_db (READ_ONLY)")
        prepare(connection, files, partitions, dry_run=True)
        metrics = validate(connection, manifest, files, partitions)
        expected_source = source_manifest_value(manifest, hashes, metrics, app_hashes)
        replay_result = verify_replay(connection, expected_source, source_count) if replay else None
    finally:
        connection.close()
        scratch.cleanup()
    if args.apply:
        result = append_core(manifest, files, partitions, hashes, metrics, expected_source)
        result["dataset_counts"] = metrics
        write_json_atomic(OUT / "apply_report.json", result)
    else:
        result = dry_run_report(current_hash, source_count, metrics, hashes, app_hashes, replay)
        result["replay_verification"] = replay_result
        write_json_atomic(OUT / "dry_run_report.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
