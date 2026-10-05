"""Read-only preflight and explicitly gated append for medical research v1.

Default operation is --dry-run. --apply exists for the parent/root operator only;
this agent will not invoke it. No operational database path is opened here.
"""
from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "thoroughbred/research/20261002_medical_v1"
LOADER = PACKAGE / "loader"
CONTRACT_PATH = LOADER / "input_contract.json"
SCHEMA_PATH = LOADER / "schema.sql"
DRY_RUN_REPORT = LOADER / "dry_run_report.json"
APPLY_REPORT = LOADER / "apply_report.json"
CORE_DIR = ROOT / "thoroughbred/data/core_api_2010_20260929_v1"
CORE_DB = CORE_DIR / "thoroughbred_core.duckdb"
CORE_MANIFEST = CORE_DIR / "manifest.json"
BACKUP_DIR = CORE_DIR / "backups/20261002_before_medical"
BACKUP_DB = BACKUP_DIR / "thoroughbred_core.duckdb"
BACKUP_MANIFEST = BACKUP_DIR / "manifest.json"
BACKUP_ATTESTATION = BACKUP_DIR / "backup_pair_attestation.json"
BASE_DB_SHA256 = "828942c5b59f4632998c12f142c4e18e4ee2e6316a0e5a56f826f37a68c726a6"
BASE_MANIFEST_SHA256 = "aa8648e439b75bdacbd7328c2d5e6ccf0aaf6105bce70f69fc7ec1f5547df7de"
SOURCE_NAME = "medical_research_v1"
START_DATE = "2010-01-01"
END_DATE = "2026-09-29"
MEETS = (1, 3)
EXPECTED_ROWS = {
    "current_annual": 243_411,
    "archived_daily_snapshot": 238_591,
    "rpt": 1_619_071,
}
EXPECTED_TOTAL_ROWS = sum(EXPECTED_ROWS.values())
EXPECTED_OBSERVATION_COLUMNS = (
    "source_kind", "source_cohort", "event_date", "source_file_date", "meet_code", "meet_raw",
    "horse_name_raw", "hr_no_raw", "stable_no_raw", "part_raw", "hospital_name_raw",
    "ill_name1_raw", "ill_name2_raw", "diagnosis_rpt_raw", "raw_payload_json", "raw_line",
    "decode_has_replacement", "source_path", "source_sha256", "capture_id",
    "source_captured_at_utc", "capture_timestamp_basis", "page_no", "row_no", "line_no",
    "request_year", "request_meet", "response_result_code", "response_result_message", "source_row_hash",
)
OBSERVATION_TYPES = {
    "meet_code": "SMALLINT", "decode_has_replacement": "BOOLEAN", "page_no": "INTEGER",
    "row_no": "INTEGER", "line_no": "INTEGER", "request_year": "SMALLINT", "request_meet": "SMALLINT",
}
OBSERVATION_FILES = (
    "thoroughbred/research/20261002_medical_v1/source/api16_current_annual_observations.parquet",
    "thoroughbred/research/20261002_medical_v1/source/api16_archived_daily_observations.parquet",
    "thoroughbred/research/20261002_medical_v1/source/dacom72_observations.parquet",
)
SOURCE_INPUTS = {
    "input_api16_page_ledger": "api16_page_ledger.parquet",
    "input_api16_year_meet_coverage": "api16_year_meet_coverage.parquet",
    "input_api16_archived_page_ledger": "api16_archived_page_ledger.parquet",
    "input_archived_daily_coverage": "archived_daily_coverage.parquet",
    "input_api16_current_exclusions": "api16_current_annual_exclusions.parquet",
    "input_api16_archived_exclusions": "api16_archived_exclusions.parquet",
    "input_existing_raw_inventory": "existing_raw_inventory.parquet",
    "input_dacom72_file_ledger": "dacom72_file_ledger.parquet",
    "input_dacom72_exclusions": "dacom72_exclusions.parquet",
    "input_dacom72_layout_reconciliation": "dacom72_layout_reconciliation.parquet",
    "input_dacom72_year_meet_coverage": "dacom72_year_meet_coverage.parquet",
    "input_medical_api_comparison_ledger": "medical_api_comparison_ledger.parquet",
    "input_medical_fingerprint_candidates": "medical_fingerprint_candidates.parquet",
    "input_source_year_meet_coverage": "source_year_meet_coverage.parquet",
}
DICTIONARY_INPUTS = {
    "input_api33_source_rows": "api33_source_rows.parquet",
    "input_api33_terms": "api33_terms.parquet",
    "input_phrase_decisions": "phrase_decisions.parquet",
    "input_phrase_components": "phrase_components.parquet",
    "input_explanation_observations": "explanation_observations.parquet",
    "input_explanation_terms": "explanation_terms.parquet",
}
EXPECTED_INPUT_ROWS = {
    "source/api16_page_ledger.parquet": 42,
    "source/api16_year_meet_coverage.parquet": 34,
    "source/api16_archived_page_ledger.parquet": 2524,
    "source/archived_daily_coverage.parquet": 34,
    "source/api16_current_annual_exclusions.parquet": 475,
    "source/api16_archived_exclusions.parquet": 8775,
    "source/existing_raw_inventory.parquet": 2524,
    "source/dacom72_file_ledger.parquet": 3377,
    "source/dacom72_exclusions.parquet": 32,
    "source/dacom72_layout_reconciliation.parquet": 272079,
    "source/dacom72_year_meet_coverage.parquet": 34,
    "source/medical_api_comparison_ledger.parquet": 1825169,
    "source/medical_fingerprint_candidates.parquet": 1904555,
    "source/source_year_meet_coverage.parquet": 102,
    "dictionary/api33_source_rows.parquet": 3523,
    "dictionary/api33_terms.parquet": 3511,
    "dictionary/phrase_decisions.parquet": 5397,
    "dictionary/phrase_components.parquet": 9113,
    "dictionary/explanation_observations.parquet": 145,
    "dictionary/explanation_terms.parquet": 119,
}
MANIFEST_FILES = (
    "thoroughbred/research/20261002_medical_v1/source/source_capture_manifest.json",
    "thoroughbred/research/20261002_medical_v1/source/coverage_manifest.json",
    "thoroughbred/research/20261002_medical_v1/source/api16_current_annual_capture_manifest.json",
    "thoroughbred/research/20261002_medical_v1/source/api16_archived_capture_manifest.json",
    "thoroughbred/research/20261002_medical_v1/source/dacom72_capture_manifest.json",
    "thoroughbred/research/20261002_medical_v1/dictionary/manifest.json",
    "thoroughbred/research/20261002_medical_v1/dictionary/schema.json",
)
SOURCE_OUTPUT_HASHES = "thoroughbred/research/20261002_medical_v1/source/source_output_hashes.csv"
OBJECT_RE = re.compile(r"(?im)^\s*CREATE\s+(TABLE|VIEW)\s+([a-z_][a-z0-9_]*)\b")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_repo_path(value: str, *, must_exist: bool = True) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or "://" in value:
        raise ValueError(f"invalid repository-relative path: {value!r}")
    relative = Path(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"unsafe repository-relative path: {value!r}")
    path = (ROOT / relative).resolve(strict=must_exist)
    if not path.is_relative_to(ROOT.resolve(strict=True)):
        raise ValueError(f"path escapes repository root: {value}")
    if must_exist and not path.is_file():
        raise ValueError(f"expected a file: {value}")
    return path


def safe_capture_path(value: str) -> Path:
    """Resolve source-ledger locators only within this repository."""
    if not isinstance(value, str) or not value or "://" in value or "\\" in value:
        raise ValueError(f"invalid source locator: {value!r}")
    path = (ROOT / value).resolve(strict=True)
    if not path.is_relative_to(ROOT.resolve(strict=True)) or not path.is_file():
        raise ValueError(f"source locator escapes repository or is not a file: {value}")
    return path


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object at {path}")
    return value


def contract() -> dict[str, Any]:
    return json_object(CONTRACT_PATH)


def verify_contract_files(c: dict[str, Any]) -> dict[str, dict[str, Any]]:
    pins = c.get("file_pins")
    if not isinstance(pins, dict) or not pins:
        raise ValueError("input_contract.json must contain non-empty file_pins")
    actual: dict[str, dict[str, Any]] = {}
    for relative, expected in pins.items():
        path = safe_repo_path(relative)
        if not isinstance(expected, dict) or not SHA_RE.fullmatch(str(expected.get("sha256", ""))):
            raise ValueError(f"invalid SHA pin for {relative}")
        digest = sha256_file(path)
        size = path.stat().st_size
        if digest != expected["sha256"] or size != int(expected.get("bytes", -1)):
            raise ValueError(f"pinned input changed: {relative}")
        rows = None
        if path.suffix == ".parquet":
            rows = pq.ParquetFile(path).metadata.num_rows
            if rows != int(expected.get("rows", -1)):
                raise ValueError(f"Parquet row count pin mismatch: {relative}: {rows}")
        actual[relative] = {"sha256": digest, "bytes": size, "rows": rows}
    return actual


def input_file_paths(c: dict[str, Any]) -> tuple[dict[str, Path], list[Path]]:
    pinned = c["file_pins"]
    source_dir = PACKAGE / "source"
    dictionary_dir = PACKAGE / "dictionary"
    source_inputs = {alias: safe_repo_path(f"thoroughbred/research/20261002_medical_v1/source/{filename}")
                     for alias, filename in SOURCE_INPUTS.items()}
    dictionary_inputs = {alias: safe_repo_path(f"thoroughbred/research/20261002_medical_v1/dictionary/{filename}")
                         for alias, filename in DICTIONARY_INPUTS.items()}
    if not source_dir.is_dir() or not dictionary_dir.is_dir():
        raise ValueError("source or dictionary input directory missing")
    for path in (*source_inputs.values(), *dictionary_inputs.values()):
        rel = path.relative_to(ROOT).as_posix()
        if rel not in pinned:
            raise ValueError(f"input_contract.json does not pin required input: {rel}")
    obs_paths = [safe_repo_path(p) for p in OBSERVATION_FILES]
    for path in obs_paths:
        if path.relative_to(ROOT).as_posix() not in pinned:
            raise ValueError(f"input_contract.json does not pin observation input: {path}")
    return source_inputs | dictionary_inputs, obs_paths


def artifact_hash_rows(c: dict[str, Any]) -> list[dict[str, Any]]:
    source = PACKAGE / "source"
    with (source / "source_output_hashes.csv").open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        row["bytes"] = int(row["bytes"])
        row["row_count"] = int(row["row_count"]) if row.get("row_count") else None
        if not SHA_RE.fullmatch(row.get("sha256", "")):
            raise ValueError(f"invalid source output SHA in inventory: {row.get('path')}")
    # The inventory file intentionally does not hash itself.
    return rows


def metadata_rows(relative_paths: tuple[str, ...]) -> list[dict[str, str]]:
    rows = []
    for relative in relative_paths:
        path = safe_repo_path(relative)
        rows.append({
            "metadata_name": Path(relative).name.removesuffix(".json"),
            "source_path": relative,
            "source_sha256": sha256_file(path),
            "metadata_json": path.read_text(encoding="utf-8"),
        })
    return rows


def register_arrow(connection: duckdb.DuckDBPyConnection, name: str,
                   rows: list[dict[str, Any]], schema: pa.Schema) -> None:
    connection.register(name, pa.Table.from_pylist(rows, schema=schema))


def stage_inputs(connection: duckdb.DuckDBPyConnection,
                 file_inputs: dict[str, Path], observation_paths: list[Path]) -> None:
    paths_sql = ",".join(sql_literal(str(p)) for p in observation_paths)
    connection.execute(
        "CREATE TEMP VIEW input_medical_observations AS "
        f"SELECT * FROM read_parquet([{paths_sql}], union_by_name=false)"
    )
    for alias, path in file_inputs.items():
        connection.execute(
            f"CREATE TEMP VIEW {alias} AS SELECT * FROM read_parquet({sql_literal(str(path))})"
        )

    source_meta = metadata_rows(tuple(MANIFEST_FILES[:5]))
    dictionary_meta = metadata_rows(tuple(MANIFEST_FILES[5:]))
    metadata_schema = pa.schema([
        ("metadata_name", pa.string()), ("source_path", pa.string()),
        ("source_sha256", pa.string()), ("metadata_json", pa.string()),
    ])
    register_arrow(connection, "input_source_metadata", source_meta, metadata_schema)
    register_arrow(connection, "input_dictionary_metadata", dictionary_meta, metadata_schema)

    source_hash_schema = pa.schema([
        ("path", pa.string()), ("sha256", pa.string()), ("bytes", pa.int64()),
        ("row_count", pa.int64()),
    ])
    register_arrow(connection, "input_medical_source_output_hashes", artifact_hash_rows(contract()), source_hash_schema)
    dictionary_manifest = json_object(PACKAGE / "dictionary/manifest.json")
    dictionary_rows = []
    for name, item in dictionary_manifest.get("output_files", {}).items():
        if not isinstance(item, dict) or not SHA_RE.fullmatch(str(item.get("sha256", ""))):
            continue
        dictionary_rows.append({
            "path": f"dictionary/{name}", "sha256": item["sha256"],
            "bytes": int(item["bytes"]),
            "row_count": None if item.get("row_count") is None else int(item["row_count"]),
        })
    register_arrow(connection, "input_medical_dictionary_output_hashes", dictionary_rows, source_hash_schema)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def scalar(connection: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> Any:
    return connection.execute(sql, params or []).fetchone()[0]


def verify_source_manifests(connection: duckdb.DuckDBPyConnection, c: dict[str, Any]) -> dict[str, Any]:
    source_capture = json_object(PACKAGE / "source/source_capture_manifest.json")
    coverage = json_object(PACKAGE / "source/coverage_manifest.json")
    dictionary = json_object(PACKAGE / "dictionary/manifest.json")
    expected_scope = {"start_date": START_DATE, "end_date": END_DATE,
                      "meets": {"1": "서울", "3": "영남 (부산경남/영천 혼합)"}}
    expect(source_capture.get("scope") == expected_scope, "source capture scope mismatch")
    expect(coverage.get("scope") == expected_scope, "source coverage scope mismatch")
    expect(source_capture.get("observation_schema") == "source_common.OBSERVATION_SCHEMA (30 columns; fixed Arrow types)",
           "source observation schema declaration mismatch")
    expect(coverage.get("total_source_observation_occurrences") == EXPECTED_TOTAL_ROWS,
           "source coverage observation total mismatch")
    reported = {item["source_cohort"]: int(item["observation_occurrences"])
                for item in coverage.get("source_observation_occurrences", [])}
    expect(reported == EXPECTED_ROWS, f"source cohort row counts mismatch: {reported}")
    expect(coverage.get("operational_database_accessed") is False
           and coverage.get("operational_database_modified") is False,
           "source manifest indicates an operational DB touch")
    expect(int(coverage.get("api_current_annual", {}).get("year_meet_request_count", -1)) == 34,
           "API current annual query ledger must contain 34 year×meet cells")
    expect(int(coverage.get("api_current_annual", {}).get("successful_empty_responses", -1)) == 17,
           "API successful-empty response count mismatch")
    expect(int(coverage.get("dacom72", {}).get("input_file_count", -1)) == 3377,
           "RPT input file count mismatch")
    expect(int(coverage.get("dacom72", {}).get("normalized_in_scope_occurrences", -1)) == EXPECTED_ROWS["rpt"],
           "RPT in-scope occurrence count mismatch")
    expect(dictionary.get("dataset") == "medical_dictionary_snapshot_v1", "dictionary dataset mismatch")
    expect(dictionary.get("safety", {}).get("automatic_event_linking_enabled") is False,
           "dictionary enables automatic event links")

    source_outputs = {item["path"]: item for item in source_capture.get("output_artifacts", [])}
    csv_outputs = {item["path"]: item for item in artifact_hash_rows(c)}
    for relative in EXPECTED_INPUT_ROWS:
        source_path = f"thoroughbred/research/20261002_medical_v1/{relative}"
        if relative.startswith("source/"):
            item = source_outputs.get(source_path)
            expect(item is not None, f"source capture manifest omits {source_path}")
            pin = c["file_pins"].get(f"thoroughbred/research/20261002_medical_v1/{relative}")
            expect(pin is not None and item.get("sha256") == pin.get("sha256"),
                   f"source capture manifest hash mismatch for {source_path}")
            expect(int(item.get("row_count", -1)) == EXPECTED_INPUT_ROWS[relative],
                   f"source capture manifest row count mismatch for {source_path}")
            out = csv_outputs.get(source_path)
            expect(out is not None and out.get("sha256") == item.get("sha256"),
                   f"source output hash CSV disagrees for {source_path}")
        else:
            file_name = relative.split("/", 1)[1]
            item = dictionary.get("output_files", {}).get(file_name)
            expect(item is not None and int(item.get("row_count", -1)) == EXPECTED_INPUT_ROWS[relative],
                   f"dictionary manifest row count mismatch for {file_name}")
    return {"scope": expected_scope, "source_total": EXPECTED_TOTAL_ROWS,
            "cohort_rows": reported, "source_manifest_artifacts": len(source_outputs),
            "dictionary_manifest_sha256": sha256_file(PACKAGE / "dictionary/manifest.json")}


def verify_inputs(connection: duckdb.DuckDBPyConnection, c: dict[str, Any]) -> dict[str, Any]:
    columns = connection.execute("DESCRIBE SELECT * FROM input_medical_observations").fetchall()
    names = tuple(row[0] for row in columns)
    expect(names == EXPECTED_OBSERVATION_COLUMNS, "medical observation source column order mismatch")
    for name, expected_type in OBSERVATION_TYPES.items():
        actual = next(row[1] for row in columns if row[0] == name)
        expect(actual.upper() == expected_type, f"medical observation type mismatch for {name}: {actual}")
    counts = connection.execute("""
        SELECT source_cohort, source_kind, count(*)::BIGINT
        FROM input_medical_observations GROUP BY ALL ORDER BY source_cohort
    """).fetchall()
    cohort_counts = {row[0]: int(row[2]) for row in counts}
    expect(cohort_counts == EXPECTED_ROWS, f"source observation counts mismatch: {counts}")
    expect(sum(cohort_counts.values()) == EXPECTED_TOTAL_ROWS, "total observation count mismatch")
    invalid = scalar(connection, """
        SELECT count(*) FROM input_medical_observations
        WHERE source_cohort NOT IN ('current_annual','archived_daily_snapshot','rpt')
           OR source_kind NOT IN ('api16','api16_archived','dacom72')
           OR meet_code NOT IN (1,3)
           OR try_cast(event_date AS DATE) IS NULL
           OR event_date < ? OR event_date > ?
           OR source_path IS NULL OR source_path=''
           OR source_sha256 IS NULL OR NOT regexp_full_match(source_sha256,'[0-9a-f]{64}')
           OR source_row_hash IS NULL OR NOT regexp_full_match(source_row_hash,'[0-9a-f]{64}')
    """, [START_DATE, END_DATE])
    expect(invalid == 0, f"{invalid} source observations have invalid scope or provenance")
    bad_cohort = scalar(connection, """
        SELECT count(*) FROM input_medical_observations
        WHERE NOT ((source_kind='api16' AND source_cohort='current_annual')
                OR (source_kind='api16_archived' AND source_cohort='archived_daily_snapshot')
                OR (source_kind='dacom72' AND source_cohort='rpt'))
    """)
    expect(bad_cohort == 0, f"{bad_cohort} observations have inconsistent kind/cohort values")
    duplicate_locators = scalar(connection, """
        SELECT count(*)-count(DISTINCT source_row_hash) FROM input_medical_observations
    """)
    expect(duplicate_locators == 0, f"source_row_hash collision/duplicate count is {duplicate_locators}")
    bad_raw = scalar(connection, """
        SELECT count(*) FROM input_medical_observations
        WHERE (source_cohort IN ('current_annual','archived_daily_snapshot')
               AND (raw_payload_json IS NULL OR raw_line IS NOT NULL OR diagnosis_rpt_raw IS NOT NULL))
           OR (source_cohort='rpt'
               AND (raw_line IS NULL OR raw_payload_json IS NOT NULL OR hr_no_raw IS NOT NULL
                    OR ill_name1_raw IS NOT NULL OR ill_name2_raw IS NOT NULL))
    """)
    expect(bad_raw == 0, f"{bad_raw} observations violate source-specific raw field contract")
    missing_times = scalar(connection, """
        SELECT count(*) FROM input_medical_observations
        WHERE source_captured_at_utc IS NULL OR source_captured_at_utc=''
           OR capture_timestamp_basis IS NULL OR capture_timestamp_basis=''
    """)
    expect(missing_times == 0, f"{missing_times} observations lack captured-time provenance")
    rpt_replacement = scalar(connection, """
        SELECT count(*) FROM input_medical_observations
        WHERE source_cohort='rpt' AND decode_has_replacement=TRUE
    """)
    expect(rpt_replacement == 0, f"{rpt_replacement} RPT observations contain decode replacement characters")
    fingerprint_occurrences = scalar(connection, "SELECT sum(occurrence_count)::UBIGINT FROM input_medical_fingerprint_candidates")
    expect(int(fingerprint_occurrences) == EXPECTED_TOTAL_ROWS,
           f"fingerprint occurrence parity mismatch: {fingerprint_occurrences}")

    annual = connection.execute("""
        SELECT count(*)::INTEGER, count(DISTINCT request_year*10+request_meet)::INTEGER,
               sum(normalized_in_scope_row_count)::UBIGINT,
               count(*) FILTER (WHERE pagination_complete=FALSE)::INTEGER,
               count(*) FILTER (WHERE successful_empty_response)::INTEGER
        FROM input_api16_year_meet_coverage
    """).fetchone()
    expect(tuple(int(value) for value in annual) == (34,34,EXPECTED_ROWS["current_annual"],0,17),
           f"annual API coverage gate failed: {annual}")
    archive_rows = scalar(connection, "SELECT sum(observation_occurrence_count)::UBIGINT FROM input_archived_daily_coverage")
    expect(int(archive_rows) == EXPECTED_ROWS["archived_daily_snapshot"], "archived daily coverage count mismatch")
    rpt_file_summary = connection.execute("""
        SELECT count(*)::INTEGER, sum(parsed_in_scope_row_count)::UBIGINT,
               count(*) FILTER (WHERE source_captured_at_utc IS NULL OR source_captured_at_utc='')::INTEGER,
               count(*) FILTER (WHERE decode_has_replacement)::INTEGER
        FROM input_dacom72_file_ledger
    """).fetchone()
    expect(tuple(int(value) for value in rpt_file_summary) == (3377,EXPECTED_ROWS["rpt"],0,0),
           f"RPT file ledger gate failed: {rpt_file_summary}")
    source_coverage = connection.execute("""
        SELECT count(*)::INTEGER, count(DISTINCT source_kind || ':' || source_cohort || ':' || event_year || ':' || meet_code)::INTEGER,
               sum(observation_occurrence_count)::UBIGINT
        FROM input_source_year_meet_coverage
    """).fetchone()
    expect(tuple(int(value) for value in source_coverage) == (102,102,EXPECTED_TOTAL_ROWS),
           f"source year×meet coverage gate failed: {source_coverage}")
    auto_linked = scalar(connection, "SELECT count(*) FROM input_medical_api_comparison_ledger WHERE automatically_linked=TRUE")
    expect(auto_linked == 0, f"comparison ledger contains {auto_linked} automatic links")
    return {
        "cohort_counts": cohort_counts,
        "total_observation_rows": EXPECTED_TOTAL_ROWS,
        "source_row_hash_unique": True,
        "raw_api_fields_untouched": True,
        "rpt_whole_literal_preserved": True,
        "fingerprint_occurrence_sum": int(fingerprint_occurrences),
        "annual_coverage_rows": int(annual[0]),
        "annual_successful_empty_responses": int(annual[4]),
        "rpt_files": int(rpt_file_summary[0]),
        "source_coverage_rows": int(source_coverage[0]),
        "automatic_cross_source_links": int(auto_linked),
    }


def verify_capture_file_hashes(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    ledgers = (
        ("input_api16_page_ledger", "source_path", "source_sha256", "source_bytes"),
        ("input_api16_archived_page_ledger", "source_path", "source_sha256", "source_bytes"),
        ("input_dacom72_file_ledger", "source_path", "source_sha256", "source_bytes"),
    )
    totals: dict[str, int] = {}
    verified = 0
    for table, path_col, hash_col, bytes_col in ledgers:
        query = f'SELECT "{path_col}", "{hash_col}", "{bytes_col}" FROM {table}'
        rows = connection.execute(query).fetchall()
        seen: set[str] = set()
        for relative, expected_hash, expected_size in rows:
            if relative in seen:
                continue
            seen.add(relative)
            path = safe_capture_path(str(relative))
            if path.stat().st_size != int(expected_size) or sha256_file(path) != str(expected_hash):
                raise ValueError(f"source file hash/size mismatch: {relative}")
            verified += 1
        totals[table] = len(seen)
    return {"raw_source_files_hash_verified": verified, "ledger_file_counts": totals}


def schema_objects() -> list[tuple[str, str]]:
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    return [(kind.upper(), name.lower()) for kind, name in OBJECT_RE.findall(text)]


def loaded_table_path_map() -> dict[str, str]:
    alias_to_table = {
        "input_api16_page_ledger": "medical_api16_page_ledger",
        "input_api16_year_meet_coverage": "medical_api16_year_meet_coverage",
        "input_api16_archived_page_ledger": "medical_api16_archived_page_ledger",
        "input_archived_daily_coverage": "medical_archived_daily_coverage",
        "input_api16_current_exclusions": "medical_api16_current_exclusions",
        "input_api16_archived_exclusions": "medical_api16_archived_exclusions",
        "input_existing_raw_inventory": "medical_existing_raw_inventory",
        "input_dacom72_file_ledger": "medical_dacom72_file_ledger",
        "input_dacom72_exclusions": "medical_dacom72_exclusions",
        "input_dacom72_layout_reconciliation": "medical_dacom72_layout_reconciliation",
        "input_dacom72_year_meet_coverage": "medical_dacom72_year_meet_coverage",
        "input_medical_api_comparison_ledger": "medical_api_comparison_ledger",
        "input_medical_fingerprint_candidates": "medical_fingerprint_candidates",
        "input_source_year_meet_coverage": "medical_source_year_meet_coverage",
        "input_api33_source_rows": "medical_api33_source_rows",
        "input_api33_terms": "medical_api33_terms",
        "input_phrase_decisions": "medical_phrase_decisions",
        "input_phrase_components": "medical_phrase_components",
        "input_explanation_observations": "medical_explanation_observations",
        "input_explanation_terms": "medical_explanation_terms",
    }
    table_names = {name for kind, name in schema_objects() if kind == "TABLE"}
    expect(set(alias_to_table.values()) <= table_names,
           f"input alias table mapping references missing schema tables: {sorted(set(alias_to_table.values())-table_names)}")
    paths = {
        f"thoroughbred/research/20261002_medical_v1/source/{SOURCE_INPUTS[alias]}": table
        for alias, table in alias_to_table.items() if alias in SOURCE_INPUTS
    }
    paths.update({
        f"thoroughbred/research/20261002_medical_v1/dictionary/{DICTIONARY_INPUTS[alias]}": table
        for alias, table in alias_to_table.items() if alias in DICTIONARY_INPUTS
    })
    for relative in OBSERVATION_FILES:
        paths[relative] = "medical_observations"
    expect(len(set(paths.values())) == len(alias_to_table) + 1,
           "input alias-to-table mapping is not a one-table-per-alias mapping")
    return paths


def schema_apply(connection: duckdb.DuckDBPyConnection, *, temporary: bool) -> None:
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    for parsed in duckdb.extract_statements(text):
        statement = re.sub(r"(?m)^\s*--.*$", "", parsed.query).strip()
        if not statement:
            continue
        if temporary:
            statement = re.sub(r"^CREATE TABLE\b", "CREATE TEMP TABLE", statement, count=1, flags=re.I)
            statement = re.sub(r"^CREATE VIEW\b", "CREATE TEMP VIEW", statement, count=1, flags=re.I)
        connection.execute(statement)


def object_inventory(connection: duckdb.DuckDBPyConnection, database_name: str) -> dict[str, str]:
    tables = connection.execute("""
        SELECT table_name FROM duckdb_tables()
        WHERE database_name=? AND schema_name='main' AND NOT internal
    """, [database_name]).fetchall()
    views = connection.execute("""
        SELECT view_name FROM duckdb_views()
        WHERE database_name=? AND schema_name='main' AND NOT internal
    """, [database_name]).fetchall()
    return {name: "TABLE" for (name,) in tables} | {name: "VIEW" for (name,) in views}


def view_counts(connection: duckdb.DuckDBPyConnection) -> dict[str, int]:
    counts = {}
    for kind, name in schema_objects():
        counts[name] = int(scalar(connection, f'SELECT count(*) FROM "{name}"'))
    return counts


def validate_loaded_schema(connection: duckdb.DuckDBPyConnection,
                           expected_base_object_count: int,
                           target_catalog: str) -> dict[str, Any]:
    objects = schema_objects()
    expect(len(objects) == len({name for _, name in objects}), "schema declares duplicate object names")
    actual = object_inventory(connection, target_catalog)
    # A read-only attached core object is separate from this in-memory target catalog.
    medical = {name: kind for name, kind in actual.items() if name.startswith("medical_")}
    expect(set(medical) == {name for _, name in objects}, "schema smoke-test object set mismatch")
    for kind, name in objects:
        expect(medical[name] == kind, f"schema object type mismatch for {name}")
    counts = view_counts(connection)
    expect(counts["medical_observations"] == EXPECTED_TOTAL_ROWS, "loaded medical_observations row count mismatch")
    expect(counts["medical_current_api_records"] == EXPECTED_ROWS["current_annual"], "current API view row count mismatch")
    expect(counts["medical_api16_archived_candidates"] == EXPECTED_ROWS["archived_daily_snapshot"], "archived API view row count mismatch")
    expected_slots = 2 * (EXPECTED_ROWS["current_annual"] + EXPECTED_ROWS["archived_daily_snapshot"]) + EXPECTED_ROWS["rpt"]
    expect(counts["medical_raw_diagnosis_slots"] == expected_slots, "raw diagnosis slot count mismatch")
    links = connection.execute("""
        SELECT source_cohort, link_status, count(*)::UBIGINT
        FROM medical_entity_links GROUP BY ALL ORDER BY source_cohort, link_status
    """).fetchall()
    link_map = {(row[0],row[1]): int(row[2]) for row in links}
    expected_links = {
        ("current_annual", "exact_core_roster_match"): 238344,
        ("current_annual", "unmatched_official_id"): 5067,
        ("archived_daily_snapshot", "exact_core_roster_match"): 228615,
        ("archived_daily_snapshot", "unmatched_official_id"): 9976,
        ("rpt", "source_has_no_official_id"): EXPECTED_ROWS["rpt"],
    }
    expect(link_map == expected_links, f"exact source-ID link status counts differ: {link_map}")
    repeated_archive = int(scalar(connection, """
        SELECT count(*) FROM medical_api16_archived_candidates
        WHERE current_exact_raw_payload_string_capture_count>0
    """))
    union_counts = connection.execute("""
        SELECT candidate_type, count(*)::UBIGINT FROM medical_union_candidates GROUP BY 1 ORDER BY 1
    """).fetchall()
    phrase_statuses = connection.execute("""
        SELECT exact_phrase_review_status, count(*)::UBIGINT
        FROM medical_api16_current_phrase_review GROUP BY 1 ORDER BY 1
    """).fetchall()
    mapping_statuses = connection.execute("""
        SELECT mapping_disposition, count(*)::UBIGINT, count(DISTINCT raw_text)::UBIGINT
        FROM medical_diagnosis_term_links GROUP BY 1 ORDER BY 1
    """).fetchall()
    explanation_rows = int(scalar(connection, "SELECT count(*) FROM medical_observed_diagnosis_explanations"))
    return {
        "created_objects": len(objects),
        "new_object_names": [name for _, name in objects],
        "row_counts": counts,
        "exact_horse_link_counts": [{"source_cohort": k[0], "status": k[1], "rows": v}
                                     for k, v in sorted(link_map.items())],
        "archived_rows_with_exact_current_raw_payload_string_match": repeated_archive,
        "union_candidate_rows_by_type": [{"type": row[0], "rows": int(row[1])} for row in union_counts],
        "current_api_phrase_review_rows_by_status": [{"status": row[0], "rows": int(row[1])}
                                                      for row in phrase_statuses],
        "term_component_metadata_rows_by_disposition": [
            {"disposition": row[0], "component_rows": int(row[1]), "phrases": int(row[2])}
            for row in mapping_statuses
        ],
        "observed_record_to_captured_description_rows": explanation_rows,
        "baseline_object_count": expected_base_object_count,
        "append_object_count": len(objects),
    }


def core_preflight(connection: duckdb.DuckDBPyConnection, database_name: str) -> dict[str, Any]:
    objects = object_inventory(connection, database_name)
    source_manifest_count = int(scalar(connection, f"SELECT count(*) FROM {database_name}.source_manifests"))
    existing_names = connection.execute(
        f"SELECT count(*) FROM {database_name}.source_manifests WHERE name=?", [SOURCE_NAME]
    ).fetchone()[0]
    expect(existing_names == 0, f"source manifest entry {SOURCE_NAME!r} already exists")
    target_names = {name for _, name in schema_objects()}
    collisions = sorted(target_names.intersection(objects))
    expect(not collisions, f"target object collision(s): {collisions}")
    expect(len(objects) == 109, f"core object count changed from baseline 109: {len(objects)}")
    expect(source_manifest_count == 24, f"source_manifests row count changed from baseline 24: {source_manifest_count}")
    roster_duplicate_count = int(scalar(connection, f"""
        SELECT count(*)-count(DISTINCT entity_type || ':' || entity_id_official_string)
        FROM {database_name}.entity_reference_roster
        WHERE entity_type='horse' AND entity_id_official_string IS NOT NULL
    """))
    expect(roster_duplicate_count == 0, f"horse roster official-ID duplicate count is {roster_duplicate_count}")
    return {"core_object_count": len(objects), "source_manifests_rows": source_manifest_count,
            "target_object_collisions": collisions, "horse_roster_duplicate_official_ids": roster_duplicate_count}


def run_dry_run() -> dict[str, Any]:
    c = contract()
    expect(c.get("dataset") == "medical_research_v1", "input contract dataset mismatch")
    expect(c.get("scope") == {"start_date": START_DATE, "end_date": END_DATE, "meets": [1,3]},
           "input contract scope mismatch")
    pins = verify_contract_files(c)
    expect(sha256_file(CORE_DB) == BASE_DB_SHA256, "core DuckDB SHA differs from pinned baseline")
    expect(sha256_file(CORE_MANIFEST) == BASE_MANIFEST_SHA256, "core manifest SHA differs from pinned baseline")
    core_manifest = json_object(CORE_MANIFEST)
    expect(core_manifest.get("database_sha256") == BASE_DB_SHA256, "core manifest baseline SHA mismatch")

    connection = duckdb.connect(":memory:")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute("SET memory_limit='6GB'")
    connection.execute("ATTACH " + sql_literal(str(CORE_DB)) + " AS core (READ_ONLY)")
    base = core_preflight(connection, "core")
    connection.execute("CREATE TEMP VIEW entity_reference_roster AS SELECT * FROM core.entity_reference_roster")
    file_inputs, observation_paths = input_file_paths(c)
    stage_inputs(connection, file_inputs, observation_paths)
    manifests = verify_source_manifests(connection, c)
    input_report = verify_inputs(connection, c)
    file_hash_report = verify_capture_file_hashes(connection)
    table_map = loaded_table_path_map()
    required_input_paths = {
        path.relative_to(ROOT).as_posix() for path in (*file_inputs.values(), *observation_paths)
    }
    mapped_input_paths = set(table_map)
    expect(mapped_input_paths == required_input_paths,
           "loaded input path-to-table mapping does not cover exactly all materialized Parquet inputs")
    schema_apply(connection, temporary=True)
    loaded = validate_loaded_schema(connection, base["core_object_count"], "temp")
    report = {
        "status": "preflight_passed_dry_run_only",
        "applied": False,
        "operational_database_opened_or_modified": False,
        "core_database_path": CORE_DB.relative_to(ROOT).as_posix(),
        "baseline_core_database_sha256": BASE_DB_SHA256,
        "baseline_core_manifest_sha256": BASE_MANIFEST_SHA256,
        "core_sha256_after_dry_run": sha256_file(CORE_DB),
        "code_sha256": sha256_file(Path(__file__).resolve()),
        "schema_sha256": sha256_file(SCHEMA_PATH),
        "input_contract_sha256": sha256_file(CONTRACT_PATH),
        "input_file_pins": pins,
        "core_preflight": base,
        "source_manifests": manifests,
        "input_validation": input_report,
        "raw_capture_hash_verification": file_hash_report,
        "input_table_mapping": {
            "materialized_parquet_input_count": len(table_map),
            "input_path_to_table": table_map,
            "pinned_but_not_materialized_artifact_count": sum(
                1 for relative in c["file_pins"] if relative.endswith(".parquet") and relative not in table_map
            ),
        },
        "schema_validation": loaded,
        "timing_and_availability": {
            "source_capture_timestamps_preserved": True,
            "historical_publication_time_verified": False,
            "medical_history_completeness_verified": False,
            "zero_API_response_means_no_event": False,
        },
        "execution_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    expect(report["core_sha256_after_dry_run"] == BASE_DB_SHA256, "read-only dry run changed core file")
    DRY_RUN_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    connection.close()
    return report


def verify_backup_pair() -> dict[str, Any]:
    for path in (BACKUP_DB, BACKUP_MANIFEST, BACKUP_ATTESTATION):
        if not path.is_file():
            raise ValueError(f"required paired backup file is missing: {path}")
    attestation = json_object(BACKUP_ATTESTATION)
    expected = {
        "baseline_db_sha256": BASE_DB_SHA256,
        "baseline_manifest_sha256": BASE_MANIFEST_SHA256,
        "backup_db_sha256": BASE_DB_SHA256,
        "backup_manifest_sha256": BASE_MANIFEST_SHA256,
        "verified_equal": True,
    }
    for key, value in expected.items():
        expect(attestation.get(key) == value, f"backup attestation mismatch for {key}")
    expect(sha256_file(BACKUP_DB) == BASE_DB_SHA256, "backup DB hash mismatch")
    expect(sha256_file(BACKUP_MANIFEST) == BASE_MANIFEST_SHA256, "backup manifest hash mismatch")
    expect(sha256_file(CORE_MANIFEST) == BASE_MANIFEST_SHA256, "source core manifest changed after backup")
    return {"backup_database_sha256": BASE_DB_SHA256,
            "backup_manifest_sha256": BASE_MANIFEST_SHA256,
            "backup_attestation_sha256": sha256_file(BACKUP_ATTESTATION),
            "attestation": attestation}


def apply_manifest_update(post_db_sha: str, table_counts: dict[str, int],
                          input_records: list[dict[str, Any]], code_sha: str,
                          schema_sha: str, contract_sha: str) -> None:
    original = json_object(CORE_MANIFEST)
    expect(original.get("database_sha256") == BASE_DB_SHA256, "core manifest changed before append")
    for name, count in table_counts.items():
        original.setdefault("table_and_view_counts", {})[name] = count
    original.setdefault("input_files", []).extend(input_records)
    original.setdefault("supplement_loads", []).append({
        "name": SOURCE_NAME,
        "applied_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "baseline_database_sha256": BASE_DB_SHA256,
        "database_sha256_after": post_db_sha,
        "backup_database": BACKUP_DB.relative_to(ROOT).as_posix(),
        "backup_manifest": BACKUP_MANIFEST.relative_to(ROOT).as_posix(),
        "backup_attestation": BACKUP_ATTESTATION.relative_to(ROOT).as_posix(),
        "source_manifest_name": SOURCE_NAME,
        "source_observation_rows": EXPECTED_TOTAL_ROWS,
        "current_api_observation_rows": EXPECTED_ROWS["current_annual"],
        "archived_api_candidate_rows": EXPECTED_ROWS["archived_daily_snapshot"],
        "rpt_source_occurrences": EXPECTED_ROWS["rpt"],
        "loader_sha256": code_sha,
        "schema_sha256": schema_sha,
        "input_contract_sha256": contract_sha,
    })
    original["database_sha256"] = post_db_sha
    manifest_tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CORE_DIR,
                                         prefix=".medical_manifest_", suffix=".tmp", delete=False) as stream:
            manifest_tmp = Path(stream.name)
            stream.write(json.dumps(original, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(manifest_tmp, CORE_MANIFEST)
        dir_fd = os.open(CORE_DIR, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if manifest_tmp and manifest_tmp.exists():
            manifest_tmp.unlink()


def run_apply() -> dict[str, Any]:
    # Explicit append mode is implemented for the parent/root operator. Never call from this agent.
    c = contract()
    pins = verify_contract_files(c)
    dry = json_object(DRY_RUN_REPORT)
    expect(dry.get("status") == "preflight_passed_dry_run_only" and dry.get("applied") is False,
           "a passing dry-run report is required")
    expect(dry.get("code_sha256") == sha256_file(Path(__file__).resolve()), "loader code changed after dry run")
    expect(dry.get("schema_sha256") == sha256_file(SCHEMA_PATH), "schema changed after dry run")
    expect(dry.get("input_contract_sha256") == sha256_file(CONTRACT_PATH), "input contract changed after dry run")
    expect(dry.get("baseline_core_database_sha256") == BASE_DB_SHA256, "dry-run baseline DB pin mismatch")
    expect(sha256_file(CORE_DB) == BASE_DB_SHA256, "core DB changed after dry run")
    backup = verify_backup_pair()

    core_manifest = json_object(CORE_MANIFEST)
    input_records = []
    loaded_table_by_path = loaded_table_path_map()
    for path, item in pins.items():
        if path.endswith(".parquet"):
            input_record = {"path": path, "sha256": item["sha256"], "rows": item["rows"]}
            if path in loaded_table_by_path:
                input_record.update({"table": loaded_table_by_path[path], "loaded_to_database": True})
            else:
                input_record.update({"artifact": "pinned_source_input", "loaded_to_database": False})
            input_records.append(input_record)
    connection = duckdb.connect(str(CORE_DB))
    connection.execute("SET preserve_insertion_order=false")
    connection.execute("SET memory_limit='6GB'")
    core_before = core_preflight(connection, "thoroughbred_core")
    file_inputs, observation_paths = input_file_paths(c)
    stage_inputs(connection, file_inputs, observation_paths)
    verify_source_manifests(connection, c)
    verify_inputs(connection, c)
    verify_capture_file_hashes(connection)
    try:
        connection.execute("BEGIN TRANSACTION")
        schema_apply(connection, temporary=False)
        loaded = validate_loaded_schema(connection, core_before["core_object_count"], "thoroughbred_core")
        manifest_json = {
            "dataset": SOURCE_NAME,
            "applied_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "scope": {"start_date_inclusive": START_DATE, "end_date_inclusive": END_DATE,
                      "meets": [1,3], "jeju": "excluded"},
            "source_observation_rows": EXPECTED_TOTAL_ROWS,
            "cohorts": EXPECTED_ROWS,
            "source_capture_manifest_sha256": sha256_file(PACKAGE / "source/source_capture_manifest.json"),
            "coverage_manifest_sha256": sha256_file(PACKAGE / "source/coverage_manifest.json"),
            "dictionary_manifest_sha256": sha256_file(PACKAGE / "dictionary/manifest.json"),
            "input_contract_sha256": sha256_file(CONTRACT_PATH),
            "loader_sha256": sha256_file(Path(__file__).resolve()),
            "schema_sha256": sha256_file(SCHEMA_PATH),
            "historical_medical_completeness": "unverified",
            "historical_publication_time": "unverified",
            "raw_occurrences_preserved": True,
            "automatic_event_linking": False,
        }
        connection.execute("INSERT INTO source_manifests(name,json_text) VALUES (?,?)",
                           [SOURCE_NAME, json.dumps(manifest_json, ensure_ascii=False, indent=2)])
        connection.execute("COMMIT")
        connection.execute("CHECKPOINT")
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except Exception:
            pass
        connection.close()
        raise
    post_manifest_rows = int(scalar(connection, "SELECT count(*) FROM source_manifests"))
    expect(post_manifest_rows == 25, f"source_manifests append count mismatch: {post_manifest_rows}")
    actual_counts = view_counts(connection)
    actual_counts["source_manifests"] = post_manifest_rows
    connection.close()
    post_db_sha = sha256_file(CORE_DB)
    apply_manifest_update(post_db_sha, actual_counts, input_records,
                          sha256_file(Path(__file__).resolve()), sha256_file(SCHEMA_PATH), sha256_file(CONTRACT_PATH))
    report = {
        "status": "applied",
        "applied": True,
        "source_manifest_name": SOURCE_NAME,
        "baseline_database_sha256": BASE_DB_SHA256,
        "database_sha256_after": post_db_sha,
        "database_manifest_sha256_after": sha256_file(CORE_MANIFEST),
        "backup_pair": backup,
        "input_file_pins": pins,
        "loaded_schema": loaded,
        "source_manifests_rows_after": post_manifest_rows,
        "core_manifest_updated_atomically": True,
        "execution_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    APPLY_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="preflight in memory; never writes the core DB (default)")
    group.add_argument("--apply", action="store_true", help="append only after dry-run and verified paired backup")
    args = parser.parse_args()
    result = run_apply() if args.apply else run_dry_run()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
