"""Pinned dry-run and root-only gated append for passing-group research v1.

Default invocation runs an in-memory preflight with the existing core attached
READ_ONLY. This program never opens an operating database or service. Only the
root operator may invoke --apply after reviewing the dry-run and paired backup.
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
PACKAGE = ROOT / "thoroughbred/research/20261002_passing_groups_v1"
LOADER = PACKAGE / "loader"
CONTRACT_PATH = LOADER / "input_contract.json"
SCHEMA_PATH = LOADER / "schema.sql"
DRY_RUN_REPORT = LOADER / "dry_run_report.json"
APPLY_REPORT = LOADER / "apply_report.json"
CORE_DIR = ROOT / "thoroughbred/data/core_api_2010_20260929_v1"
CORE_DB = CORE_DIR / "thoroughbred_core.duckdb"
CORE_MANIFEST = CORE_DIR / "manifest.json"
BACKUP_DIR = CORE_DIR / "backups/20261002_before_passing_groups"
BACKUP_DB = BACKUP_DIR / "thoroughbred_core.duckdb"
BACKUP_MANIFEST = BACKUP_DIR / "manifest.json"
BACKUP_ATTESTATION = BACKUP_DIR / "backup_pair_attestation.json"
BACKUP_ROOT_ATTESTATION = PACKAGE / "root_backup_attestation.json"

BASE_DB_SHA256 = "c30202a65a1a82c2927efc8e0ef150c03a0c9950e953ee445beb1b3a7f8c2de6"
BASE_MANIFEST_SHA256 = "3fc7cd7dbbe13b908424e33d11955f2089834333870da2778e53099312758ee4"
BASE_OBJECTS = 153
BASE_SOURCE_MANIFESTS = 25
SOURCE_NAME = "passing_groups_research_v1"
START_DATE = "2010-01-01"
END_DATE = "2026-09-29"
MEETS = (1, 3, 4)
EXPECTED = {
    "api_observations": 29_774,
    "api_page_ledger": 48,
    "api_exclusions": 0,
    "rpt_race_headers": 17_371,
    "rpt_point_observations": 111_467,
    "rpt_source_files": 1_827,
    "rpt_point_mapping": 20,
    "rpt_snapshot_comparison": 126_406,
    "api_rpt_value_matches": 87_334,
    "api_mapping_validation": 315,
    "confirmed_race_keys": 29_710,
    "core_execution_ledger": 29_826,
    "api_error_evidence": 72,
}

API_DIR = PACKAGE / "api_source"
RPT_DIR = PACKAGE / "rpt_mapping"
INPUTS: dict[str, tuple[str, str]] = {
    "input_api_observations": ("api_source/api_observations.parquet", "passing_api_observations"),
    "input_api_page_ledger": ("api_source/api_page_ledger.parquet", "passing_api_page_ledger"),
    "input_api_exclusions": ("api_source/api_exclusions.parquet", "passing_api_exclusions"),
    "input_rpt_race_headers": ("rpt_mapping/rpt_race_headers.parquet", "passing_rpt_race_headers"),
    "input_rpt_point_observations": ("rpt_mapping/rpt_point_observations.parquet", "passing_rpt_point_observations"),
    "input_rpt_source_files": ("rpt_mapping/rpt_source_files.parquet", "passing_rpt_source_files"),
    "input_rpt_point_mapping": ("rpt_mapping/rpt_point_mapping.csv", "passing_rpt_point_mapping"),
    "input_rpt_snapshot_comparison": ("rpt_mapping/rpt_snapshot_comparison.parquet", "passing_rpt_snapshot_comparison"),
    "input_api_mapping_validation": ("api_mapping_independent/api_mapping_validation_by_year.parquet", "passing_api_mapping_validation"),
    "input_api_rpt_value_matches": ("api_mapping_independent/api_rpt_value_matches.parquet", "passing_api_rpt_value_matches"),
}
JSON_INPUTS = {
    "input_confirmed_race_keys": ("root_expected_confirmed_races.json", "passing_confirmed_race_keys"),
}
AUDIT_INPUTS = {"input_expected_selected_points": "root_expected_selected_points.parquet"}
ERROR_CSVS = {
    "planless_positive_result_review": "thoroughbred/research/20260929_calendar_api_v1/planless_positive_result_review.csv",
    "result_only_nonfinish_anomaly_review": "thoroughbred/research/20260929_calendar_api_v1/result_only_nonfinish_anomaly_review.csv",
}
METADATA_FILES = (
    "thoroughbred/research/20261002_passing_groups_v1/api_source/source_manifest.json",
    "thoroughbred/research/20261002_passing_groups_v1/api_source/api_year_meet_coverage.json",
    "thoroughbred/research/20261002_passing_groups_v1/api_source/raw_page_sha256_manifest.json",
    "thoroughbred/research/20261002_passing_groups_v1/rpt_mapping/manifest.json",
    "thoroughbred/research/20261002_passing_groups_v1/rpt_mapping/root_independent_parse_parity.json",
    "thoroughbred/research/20261002_passing_groups_v1/api_mapping_independent/api_match_artifact_manifest.json",
    "thoroughbred/research/20261002_passing_groups_v1/api_mapping_independent/independent_mapping_check.json",
    "thoroughbred/research/20261002_passing_groups_v1/root_api_verification.json",
    "thoroughbred/research/20261002_passing_groups_v1/root_pair_evidence_verification.json",
    "thoroughbred/research/20261002_passing_groups_v1/root_rpt_verification.json",
    "thoroughbred/research/20261002_passing_groups_v1/root_expected_noncore_keys.json",
    "thoroughbred/research/20261002_passing_groups_v1/root_backup_attestation.json",
)
OBJECT_RE = re.compile(r"(?im)^\s*CREATE\s+(TABLE|VIEW)\s+([a-z_][a-z0-9_]*)\b")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


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


def safe_capture_path(base: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or "://" in value:
        raise ValueError(f"invalid capture locator: {value!r}")
    path = (base / value).resolve(strict=True)
    if not path.is_relative_to(base.resolve(strict=True)) or not path.is_file():
        raise ValueError(f"capture locator escapes its source root or is not a file: {value}")
    return path


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def contract() -> dict[str, Any]:
    value = read_json(CONTRACT_PATH)
    expect(isinstance(value, dict), "input contract must be a JSON object")
    return value


def verify_pins(c: dict[str, Any]) -> dict[str, dict[str, Any]]:
    pins = c.get("file_pins")
    expect(isinstance(pins, dict) and bool(pins), "input contract requires file_pins")
    actual: dict[str, dict[str, Any]] = {}
    for relative, pin in pins.items():
        path = safe_repo_path(relative)
        expect(isinstance(pin, dict) and SHA_RE.fullmatch(str(pin.get("sha256", ""))),
               f"invalid input pin for {relative}")
        digest, size = sha256_file(path), path.stat().st_size
        expect(digest == pin["sha256"] and size == int(pin.get("bytes", -1)),
               f"pinned artifact changed: {relative}")
        rows = pq.ParquetFile(path).metadata.num_rows if path.suffix == ".parquet" else None
        if rows is not None:
            expect(rows == int(pin.get("rows", -1)), f"Parquet rows differ from pin: {relative}")
        actual[relative] = {"sha256": digest, "bytes": size, "rows": rows}
    return actual


def input_paths(c: dict[str, Any]) -> tuple[dict[str, Path], dict[str, Path], dict[str, Path], dict[str, Path]]:
    pq_csv: dict[str, Path] = {}
    for alias, (relative, _) in INPUTS.items():
        path = safe_repo_path(f"thoroughbred/research/20261002_passing_groups_v1/{relative}")
        expect(path.relative_to(ROOT).as_posix() in c["file_pins"], f"unpinned input: {relative}")
        pq_csv[alias] = path
    json_files: dict[str, Path] = {}
    for alias, (relative, _) in JSON_INPUTS.items():
        path = safe_repo_path(f"thoroughbred/research/20261002_passing_groups_v1/{relative}")
        expect(path.relative_to(ROOT).as_posix() in c["file_pins"], f"unpinned input: {relative}")
        json_files[alias] = path
    errors = {name: safe_repo_path(path) for name, path in ERROR_CSVS.items()}
    for path in errors.values():
        expect(path.relative_to(ROOT).as_posix() in c["file_pins"], f"unpinned error evidence: {path}")
    audit_inputs = {alias: safe_repo_path(f"thoroughbred/research/20261002_passing_groups_v1/{relative}")
                    for alias, relative in AUDIT_INPUTS.items()}
    for path in audit_inputs.values():
        expect(path.relative_to(ROOT).as_posix() in c["file_pins"], f"unpinned audit input: {path}")
    return pq_csv, json_files, errors, audit_inputs


def schema_objects() -> list[tuple[str, str]]:
    return [(kind.upper(), name) for kind, name in OBJECT_RE.findall(SCHEMA_PATH.read_text(encoding="utf-8"))]


def register_rows(con: duckdb.DuckDBPyConnection, name: str, rows: list[dict[str, Any]], schema: pa.Schema) -> None:
    con.register(name, pa.Table.from_pylist(rows, schema=schema))


def stage_inputs(con: duckdb.DuckDBPyConnection, pq_csv: dict[str, Path],
                 json_files: dict[str, Path], errors: dict[str, Path], audit_inputs: dict[str, Path],
                 pins: dict[str, dict[str, Any]], core_catalog: str) -> None:
    for alias, path in pq_csv.items():
        if path.suffix == ".csv":
            con.execute(f"CREATE TEMP VIEW {alias} AS SELECT * FROM read_csv_auto({sql_literal(str(path))}, header=true)")
        else:
            con.execute(f"CREATE TEMP VIEW {alias} AS SELECT * FROM read_parquet({sql_literal(str(path))})")

    # The confirmed key artifact is an independent root-verified list, then compared
    # in both directions to the core's confirmed_races view.
    rows = read_json(json_files["input_confirmed_race_keys"])
    expect(isinstance(rows, list), "confirmed-race key input must be a JSON list")
    register_rows(con, "input_confirmed_race_keys", rows,
                  pa.schema([("meet", pa.int16()), ("event_date", pa.string()),
                             ("race_no", pa.int16()), ("distance_raw", pa.string())]))

    error_rows: list[dict[str, Any]] = []
    for source, path in errors.items():
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                error_rows.append({**row, "error_source": source})
    expect(len(error_rows) == EXPECTED["api_error_evidence"], "reviewed API error evidence count mismatch")
    error_fields = list(error_rows[0]) if error_rows else ["error_source"]
    register_rows(con, "input_api_error_evidence", error_rows,
                  pa.schema([(field, pa.string()) for field in error_fields]))

    metadata_rows = []
    for relative in METADATA_FILES:
        path = safe_repo_path(relative)
        metadata_rows.append({"metadata_name": path.name, "source_path": relative,
                              "source_sha256": sha256_file(path),
                              "metadata_json": path.read_text(encoding="utf-8")})
    register_rows(con, "input_source_metadata", metadata_rows, pa.schema([
        ("metadata_name", pa.string()), ("source_path", pa.string()),
        ("source_sha256", pa.string()), ("metadata_json", pa.string())]))

    pin_rows = [{"path": path, "sha256": info["sha256"], "bytes": info["bytes"],
                 "row_count": info["rows"]} for path, info in sorted(pins.items())]
    register_rows(con, "input_source_output_hashes", pin_rows, pa.schema([
        ("path", pa.string()), ("sha256", pa.string()), ("bytes", pa.int64()),
        ("row_count", pa.int64())]))

    expect(core_catalog in {"core", "thoroughbred_core"}, "invalid core catalog alias")
    con.execute(f"CREATE TEMP VIEW input_core_execution_ledger AS SELECT * FROM {core_catalog}.race_execution_adjudicated")
    con.execute(f"""
      CREATE TEMP VIEW input_core_confirmed_races AS
      SELECT CASE actual_venue_label_raw WHEN '서울' THEN 1 WHEN '부산경남' THEN 3 WHEN '부경' THEN 3
                                         WHEN '부산' THEN 3 WHEN '영천' THEN 4 END::SMALLINT AS meet,
             cast(race_date AS VARCHAR) AS event_date,
             try_cast(result_race_no_key AS SMALLINT) AS race_no,
             source_meet,actual_venue_label_raw,scheduled_distance_m,actual_distance_m_raw
      FROM {core_catalog}.confirmed_races
      WHERE race_date BETWEEN DATE '2010-01-01' AND DATE '2026-09-29'
    """)
    for alias, path in audit_inputs.items():
        con.execute(f"CREATE TEMP VIEW {alias} AS SELECT * FROM read_parquet({sql_literal(str(path))})")


def scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> Any:
    return con.execute(sql, params or []).fetchone()[0]


def verify_manifests(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    api = read_json(API_DIR / "api_year_meet_coverage.json")
    api_manifest = read_json(API_DIR / "source_manifest.json")
    rpt = read_json(RPT_DIR / "manifest.json")
    parity = read_json(RPT_DIR / "root_independent_parse_parity.json")
    api_check = read_json(PACKAGE / "root_api_verification.json")
    pair_check = read_json(PACKAGE / "root_pair_evidence_verification.json")
    rpt_check = read_json(PACKAGE / "root_rpt_verification.json")
    mapping_manifest = read_json(PACKAGE / "api_mapping_independent/api_match_artifact_manifest.json")
    expect(api.get("history_start_date") == START_DATE and api.get("cutoff_date") == END_DATE,
           "API date scope mismatch")
    expect(api.get("partitions_requested") == 35 and api.get("partitions_captured") == 35
           and api.get("all_partitions_response_complete") is True, "API partition coverage incomplete")
    expect(api.get("observation_occurrence_count") == EXPECTED["api_observations"]
           and api.get("in_scope_occurrence_count") == EXPECTED["api_observations"]
           and api.get("excluded_occurrence_count") == 0, "API occurrence totals differ")
    expect(len(api.get("partitions", [])) == 35 and all(p.get("response_complete") for p in api["partitions"]),
           "API partition response ledger incomplete")
    expect(api_manifest.get("capture_id") == api.get("capture_id"), "API manifest capture ID mismatch")
    expect(rpt.get("scope", {}).get("start_date") == START_DATE and rpt.get("scope", {}).get("end_date") == END_DATE,
           "RPT source scope mismatch")
    expect(rpt.get("counts", {}).get("source_file_count") == EXPECTED["rpt_source_files"]
           and rpt.get("counts", {}).get("race_header_count") == EXPECTED["rpt_race_headers"]
           and rpt.get("counts", {}).get("point_line_count") == EXPECTED["rpt_point_observations"],
           "RPT source manifest row counts mismatch")
    expect(parity.get("all_source_coordinate_rows_match") is True
           and parity.get("our_point_rows") == EXPECTED["rpt_point_observations"]
           and parity.get("field_mismatch_counts") == {}, "independent RPT line parity failed")
    expect(api_check.get("all_passed") is True and api_check.get("confirmed_keys_missing") == [],
           "independent API capture verification failed")
    expect(api_check.get("noncore_dispositions", {}).get("adjudicated_nonexecution") == 64
           and api_check.get("noncore_dispositions", {}).get("unknown_keys") == [],
           "API noncore dispositions are not fully adjudicated")
    expect(pair_check.get("all_passed") is True and pair_check.get("complete_pair_set_verified") is True
           and pair_check.get("raw_exact_match_pairs_checked") == EXPECTED["api_rpt_value_matches"],
           "API/RPT exact-match evidence audit failed")
    expect(mapping_manifest.get("outputs", {}).get("api_rpt_value_matches.parquet", {}).get("row_count")
           == EXPECTED["api_rpt_value_matches"], "mapping manifest match-row count mismatch")
    expected_mapping_inputs = {
        "thoroughbred/research/20261002_passing_groups_v1/api_source/api_observations.parquet":
            sha256_file(API_DIR / "api_observations.parquet"),
        "thoroughbred/research/20261002_passing_groups_v1/rpt_mapping/rpt_point_observations.parquet":
            sha256_file(RPT_DIR / "rpt_point_observations.parquet"),
        "thoroughbred/research/20261002_passing_groups_v1/rpt_mapping/rpt_point_mapping.csv":
            sha256_file(RPT_DIR / "rpt_point_mapping.csv"),
    }
    expect(mapping_manifest.get("inputs") == expected_mapping_inputs,
           "API/RPT mapping evidence manifest input pins mismatch")
    expect(rpt_check.get("all_passed") is True, "independent RPT file/line verification failed")
    expect(rpt.get("source_read_contract", {}).get("operating_database") == "not opened or modified",
           "RPT source contract reports operational database access")
    return {"api_capture_id": api.get("capture_id"), "api_partitions": 35,
            "api_pages": api.get("page_count"), "api_rows": api.get("observation_occurrence_count"),
            "rpt_files": rpt["counts"]["source_file_count"],
            "rpt_races": rpt["counts"]["race_header_count"],
            "rpt_points": rpt["counts"]["point_line_count"],
            "rpt_capture_timestamp_matched_files": rpt["counts"].get("source_capture_matched_file_count"),
            "rpt_independent_line_parity": parity.get("all_source_coordinate_rows_match")}


def verify_source_bytes(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    page_rows = con.execute("""
       SELECT raw_page_path,response_body_sha256,response_body_bytes
       FROM input_api_page_ledger ORDER BY requested_year,requested_meet,reported_page_no
    """).fetchall()
    for relative, expected_sha, expected_bytes in page_rows:
        path = safe_capture_path(API_DIR, relative)
        expect(path.stat().st_size == expected_bytes and sha256_file(path) == expected_sha,
               f"API response page bytes/hash mismatch: {relative}")
    rpt_rows = con.execute("SELECT source_path,source_sha256,source_file_bytes FROM input_rpt_source_files").fetchall()
    for relative, expected_sha, expected_bytes in rpt_rows:
        path = safe_repo_path(relative)
        expect(path.stat().st_size == expected_bytes and sha256_file(path) == expected_sha,
               f"RPT source file bytes/hash mismatch: {relative}")
    return {"api_raw_page_files_verified": len(page_rows), "rpt_source_files_verified": len(rpt_rows)}


def verify_inputs(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    for table, expected in EXPECTED.items():
        if table in {"confirmed_race_keys", "core_execution_ledger", "api_error_evidence"}:
            continue
        alias = {
            "api_observations": "input_api_observations", "api_page_ledger": "input_api_page_ledger",
            "api_exclusions": "input_api_exclusions", "rpt_race_headers": "input_rpt_race_headers",
            "rpt_point_observations": "input_rpt_point_observations", "rpt_source_files": "input_rpt_source_files",
            "rpt_point_mapping": "input_rpt_point_mapping", "rpt_snapshot_comparison": "input_rpt_snapshot_comparison",
        }.get(table)
        if alias:
            actual = int(scalar(con, f"SELECT count(*) FROM {alias}"))
            expect(actual == expected, f"input {table} row count mismatch: {actual} != {expected}")
    expect(scalar(con, "SELECT count(*) FROM input_confirmed_race_keys") == EXPECTED["confirmed_race_keys"],
           "confirmed race key count mismatch")
    expect(scalar(con, "SELECT count(*) FROM input_core_execution_ledger") == EXPECTED["core_execution_ledger"],
           "core execution ledger row count mismatch")
    expect(scalar(con, "SELECT count(*) FROM input_api_error_evidence") == EXPECTED["api_error_evidence"],
           "API error evidence row count mismatch")
    expect(scalar(con, "SELECT count(*) FROM input_api_mapping_validation") == EXPECTED["api_mapping_validation"],
           "annual API mapping validation row count mismatch")
    expect(scalar(con, "SELECT count(*) FROM input_api_rpt_value_matches") == EXPECTED["api_rpt_value_matches"],
           "API/RPT value-match evidence row count mismatch")
    match_statuses = con.execute("""
       SELECT mapping_evidence,count(*)::BIGINT FROM input_api_rpt_value_matches
       GROUP BY 1 ORDER BY 1
    """).fetchall()
    expect({status: int(n) for status, n in match_statuses} == {
        "ambiguous_repeated_value": 10_693, "unique_exact_value_pair": 76_641
    }, f"API/RPT match evidence status counts differ: {match_statuses}")
    duplicate_map_validation = scalar(con, """
       SELECT count(*)-count(DISTINCT actual_meet_code::VARCHAR||'|'||event_year::VARCHAR||'|'||api_field)
       FROM input_api_mapping_validation
    """)
    expect(duplicate_map_validation == 0, f"annual mapping validation duplicate keys: {duplicate_map_validation}")
    dup_api = scalar(con, """
       SELECT count(*)-count(DISTINCT actual_meet_code::VARCHAR||'|'||race_date_iso||'|'||rcNo::VARCHAR)
       FROM input_api_observations WHERE row_scope_status='in_scope'
    """)
    expect(dup_api == 0, f"API capture has {dup_api} duplicate race keys")
    invalid_api = scalar(con, """
       SELECT count(*) FROM input_api_observations
       WHERE row_scope_status='in_scope' AND (
         actual_meet_code NOT IN (1,3,4) OR race_date_iso < ? OR race_date_iso > ?
         OR try_cast(rcNo AS SMALLINT) IS NULL OR NOT regexp_full_match(page_sha256,'[0-9a-f]{64}')
         OR NOT regexp_full_match(source_row_sha256,'[0-9a-f]{64}'))
    """, [START_DATE, END_DATE])
    expect(invalid_api == 0, f"{invalid_api} API rows violate scope/locator checks")
    invalid_rpt = scalar(con, """
       SELECT count(*) FROM input_rpt_point_observations
       WHERE actual_meet_code NOT IN (1,3,4) OR event_date < ? OR event_date > ?
         OR NOT regexp_full_match(source_sha256,'[0-9a-f]{64}')
         OR NOT regexp_full_match(raw_line_bytes_hex,'([0-9a-fA-F]{2})+')
    """, [START_DATE, END_DATE])
    expect(invalid_rpt == 0, f"{invalid_rpt} RPT lines violate scope/provenance checks")
    duplicate_rpt = scalar(con, "SELECT count(*)-count(DISTINCT observation_locator) FROM input_rpt_point_observations")
    expect(duplicate_rpt == 0, f"RPT source locator duplicates: {duplicate_rpt}")
    wrongscope = scalar(con, """
       SELECT count(*) FROM input_confirmed_race_keys
       WHERE meet NOT IN (1,3,4) OR event_date < ? OR event_date > ? OR race_no NOT BETWEEN 1 AND 20
    """, [START_DATE, END_DATE])
    expect(wrongscope == 0, f"confirmed race list has {wrongscope} out-of-scope keys")
    duplicate_keys = scalar(con, """
       SELECT count(*)-count(DISTINCT meet::VARCHAR||'|'||event_date||'|'||race_no::VARCHAR)
       FROM input_confirmed_race_keys
    """)
    expect(duplicate_keys == 0, f"confirmed key list has {duplicate_keys} duplicates")
    # Compare the independently generated key set with the confirmed core view.
    unmapped_venue = scalar(con, "SELECT count(*) FROM input_core_confirmed_races WHERE meet IS NULL")
    expect(unmapped_venue == 0, f"core confirmed race venue bridge has {unmapped_venue} unmapped rows")
    mismatched_venue_code = scalar(con, """
       SELECT count(*) FROM input_core_confirmed_races
       WHERE (actual_venue_label_raw='서울' AND source_meet<>'1')
          OR (actual_venue_label_raw IN ('부산경남','부경','부산') AND source_meet<>'3')
          OR (actual_venue_label_raw='영천' AND source_meet<>'4')
    """)
    expect(mismatched_venue_code == 0, f"source meet/physical venue mismatch rows: {mismatched_venue_code}")
    core_count = scalar(con, "SELECT count(*) FROM input_core_confirmed_races")
    expect(core_count == EXPECTED["confirmed_race_keys"], f"core confirmed race count mismatch: {core_count}")
    missing = scalar(con, """
       SELECT count(*) FROM (
         (SELECT meet,event_date,race_no FROM input_confirmed_race_keys
          EXCEPT ALL SELECT meet,event_date,race_no FROM input_core_confirmed_races)
         UNION ALL
         (SELECT meet,event_date,race_no FROM input_core_confirmed_races
          EXCEPT ALL SELECT meet,event_date,race_no FROM input_confirmed_race_keys)
       ) q
    """)
    expect(missing == 0, f"confirmed input/core key EXCEPT ALL mismatch: {missing}")
    # The API capture has 64 additional event keys; preserve and classify every one.
    con.execute("CREATE TEMP VIEW input_api_reconciliation_preview AS "
                "SELECT a.actual_meet_code,a.race_date_iso,a.rcNo "
                "FROM input_api_observations a LEFT JOIN input_core_confirmed_races k "
                "ON k.meet=a.actual_meet_code AND k.event_date=a.race_date_iso AND k.race_no=a.rcNo "
                "WHERE a.row_scope_status='in_scope' AND k.meet IS NULL")
    noncore = scalar(con, "SELECT count(*) FROM input_api_reconciliation_preview")
    expect(noncore == 64, f"API noncore occurrence count mismatch: {noncore}")
    expected_selected_rows = scalar(con, "SELECT count(*) FROM input_expected_selected_points")
    expect(expected_selected_rows == 144_001, f"independent expected selected point count differs: {expected_selected_rows}")
    return {"api_observations": EXPECTED["api_observations"], "api_duplicate_race_keys": dup_api,
            "confirmed_races": core_count, "confirmed_keys_bidirectional_except_all_mismatch": missing,
            "api_noncore_occurrences": noncore, "rpt_points": EXPECTED["rpt_point_observations"],
            "api_error_review_rows": EXPECTED["api_error_evidence"],
            "independent_expected_selected_point_rows": expected_selected_rows,
            "unmapped_core_venue_rows": unmapped_venue,
            "core_source_meet_physical_venue_mismatches": mismatched_venue_code,
            "api_rpt_value_match_rows": EXPECTED["api_rpt_value_matches"],
            "api_mapping_validation_rows": EXPECTED["api_mapping_validation"]}


def schema_apply(con: duckdb.DuckDBPyConnection, *, temporary: bool) -> None:
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    for parsed in duckdb.extract_statements(text):
        statement = re.sub(r"(?m)^\s*--.*$", "", parsed.query).strip()
        if not statement:
            continue
        if temporary:
            statement = re.sub(r"^CREATE TABLE\b", "CREATE TEMP TABLE", statement, count=1, flags=re.I)
            statement = re.sub(r"^CREATE VIEW\b", "CREATE TEMP VIEW", statement, count=1, flags=re.I)
        con.execute(statement)


def object_inventory(con: duckdb.DuckDBPyConnection, catalog: str) -> dict[str, str]:
    tables = con.execute("""SELECT table_name FROM duckdb_tables()
        WHERE database_name=? AND schema_name='main' AND NOT internal""", [catalog]).fetchall()
    views = con.execute("""SELECT view_name FROM duckdb_views()
        WHERE database_name=? AND schema_name='main' AND NOT internal""", [catalog]).fetchall()
    return {n: "TABLE" for (n,) in tables} | {n: "VIEW" for (n,) in views}


def table_view_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    return {name: int(scalar(con, f'SELECT count(*) FROM "{name}"')) for _, name in schema_objects()}


def validate_loaded_schema(con: duckdb.DuckDBPyConnection, catalog: str) -> dict[str, Any]:
    objects = schema_objects()
    expect(len(objects) == len({name for _, name in objects}), "schema contains duplicate object names")
    actual = object_inventory(con, catalog)
    expected = {name: kind for kind, name in objects}
    expect({name: kind for name, kind in actual.items() if name.startswith("passing_") or name == "race_passing_groups"}
           == expected, "created object set/type differs from schema contract")
    counts = table_view_counts(con)
    for table, expected_count in EXPECTED.items():
        actual_count = counts.get("passing_" + table)
        if table == "confirmed_race_keys":
            actual_count = counts.get("passing_confirmed_race_keys")
        elif table == "core_execution_ledger":
            actual_count = counts.get("passing_core_execution_ledger")
        elif table == "api_error_evidence":
            actual_count = counts.get("passing_api_error_evidence")
        expect(actual_count == expected_count, f"loaded table count mismatch for {table}: {actual_count}")
    expect(counts.get("race_passing_groups", 0) > 0, "no race passing-group evidence rows")
    expect(counts.get("passing_race_coverage") == EXPECTED["confirmed_race_keys"],
           "race coverage must include every confirmed race exactly once")
    expect(counts.get("passing_api_race_times") == EXPECTED["api_observations"],
           "race-level timing view row count mismatch")
    groups = con.execute("""
       SELECT selected_source,selection_status,count(*)::BIGINT
       FROM race_passing_groups GROUP BY ALL ORDER BY ALL
    """).fetchall()
    selected_api = scalar(con, "SELECT count(*) FROM race_passing_groups WHERE selected_source='api303'")
    selected_rpt = scalar(con, "SELECT count(*) FROM race_passing_groups WHERE selected_source='dacom11_rpt'")
    discrepant_api = scalar(con, "SELECT count(*) FROM race_passing_groups WHERE selection_status='api_primary_with_rpt_discrepancy'")
    expect((selected_api, selected_rpt, discrepant_api) == (142_227, 1_774, 50),
           f"independent selected-point totals differ: API={selected_api} RPT={selected_rpt} discrepant API={discrepant_api}")
    pubs = scalar(con, """
       SELECT count(*) FROM race_passing_groups
       WHERE historical_publication_time_verified IS DISTINCT FROM FALSE OR source_publication_at_kst IS NOT NULL
    """)
    expect(pubs == 0, "selected passing-group rows claim historical publication time")
    parity = scalar(con, """
       SELECT count(*) FROM (
         (SELECT actual_meet_code::BIGINT AS actual_meet_code,event_date,race_no::BIGINT AS race_no,
                 canonical_point_code,notation_raw,selected_source
          FROM race_passing_groups WHERE selected_source IS NOT NULL
          EXCEPT ALL
          SELECT actual_meet_code,event_date,race_no,canonical_point_code,notation_raw,selected_source
          FROM input_expected_selected_points)
         UNION ALL
         (SELECT actual_meet_code,event_date,race_no,canonical_point_code,notation_raw,selected_source
          FROM input_expected_selected_points
          EXCEPT ALL
          SELECT actual_meet_code::BIGINT,event_date,race_no::BIGINT,canonical_point_code,notation_raw,selected_source
          FROM race_passing_groups WHERE selected_source IS NOT NULL)
       ) d
    """)
    expect(parity == 0, f"root independent selected-point EXCEPT ALL parity failed: {parity}")
    empty_placeholder_rows = scalar(con, """
       SELECT count(*) FROM passing_api_point_observations
       WHERE coalesce(trim(notation_raw,' '),'') IN ('','-','X')
    """)
    expect(empty_placeholder_rows == 0, "placeholder API slots entered the mapped point candidate view")
    unknown_events = scalar(con, """
       SELECT count(*) FROM passing_api_event_reconciliation
       WHERE reconciliation_status='api_key_not_in_confirmed_or_reviewed_core_ledgers'
    """)
    expect(unknown_events == 0, f"unclassified API event receipts: {unknown_events}")
    return {"created_object_count": len(objects), "objects": objects, "row_counts": counts,
            "selected_source_counts": {"api303": selected_api, "dacom11_rpt": selected_rpt,
                                       "api_primary_with_rpt_discrepancy": discrepant_api},
            "selection_status_counts": [{"source": r[0], "status": r[1], "rows": int(r[2])} for r in groups],
            "unknown_api_event_receipts": unknown_events,
            "historical_publication_time_claims": pubs,
            "independent_selected_point_except_all_mismatch": parity}


def core_preflight(con: duckdb.DuckDBPyConnection, catalog: str) -> dict[str, Any]:
    objects = object_inventory(con, catalog)
    manifest_rows = int(scalar(con, f"SELECT count(*) FROM {catalog}.source_manifests"))
    existing = int(scalar(con, f"SELECT count(*) FROM {catalog}.source_manifests WHERE name=?", [SOURCE_NAME]))
    collisions = sorted(set(name for _, name in schema_objects()) & set(objects))
    expect(not collisions, f"target object name collisions in core: {collisions}")
    expect(len(objects) == BASE_OBJECTS, f"core object count differs: {len(objects)}")
    expect(manifest_rows == BASE_SOURCE_MANIFESTS, f"source_manifests count differs: {manifest_rows}")
    expect(existing == 0, f"source manifest {SOURCE_NAME!r} already exists")
    return {"core_object_count": len(objects), "source_manifests_rows": manifest_rows,
            "source_name_existing_rows": existing, "object_collisions": collisions}


def run_dry_run() -> dict[str, Any]:
    c = contract()
    expect(c.get("dataset") == SOURCE_NAME, "input contract dataset mismatch")
    expect(c.get("scope") == {"start_date": START_DATE, "end_date": END_DATE, "meets": list(MEETS)},
           "input contract scope mismatch")
    pins = verify_pins(c)
    expect(sha256_file(CORE_DB) == BASE_DB_SHA256, "core DuckDB SHA differs from frozen baseline")
    expect(sha256_file(CORE_MANIFEST) == BASE_MANIFEST_SHA256, "core manifest SHA differs from frozen baseline")
    core_manifest = read_json(CORE_MANIFEST)
    expect(core_manifest.get("database_sha256") == BASE_DB_SHA256, "core manifest database SHA mismatch")
    con = duckdb.connect(":memory:")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET memory_limit='8GB'")
    con.execute("ATTACH " + sql_literal(str(CORE_DB)) + " AS core (READ_ONLY)")
    base = core_preflight(con, "core")
    pq_csv, json_files, errors, audit_inputs = input_paths(c)
    stage_inputs(con, pq_csv, json_files, errors, audit_inputs, pins, "core")
    manifests = verify_manifests(con)
    input_validation = verify_inputs(con)
    raw_validation = verify_source_bytes(con)
    schema_apply(con, temporary=True)
    loaded = validate_loaded_schema(con, "temp")
    after = sha256_file(CORE_DB)
    expect(after == BASE_DB_SHA256, "read-only dry-run changed core DB hash")
    report = {
        "status": "preflight_passed_dry_run_only", "applied": False,
        "operating_database_opened_or_modified": False,
        "core_database_path": CORE_DB.relative_to(ROOT).as_posix(),
        "baseline_core_database_sha256": BASE_DB_SHA256,
        "baseline_core_manifest_sha256": BASE_MANIFEST_SHA256,
        "core_sha256_after_dry_run": after,
        "loader_sha256": sha256_file(Path(__file__).resolve()),
        "schema_sha256": sha256_file(SCHEMA_PATH),
        "input_contract_sha256": sha256_file(CONTRACT_PATH),
        "input_file_pins": pins,
        "core_preflight": base,
        "source_manifests": manifests,
        "input_validation": input_validation,
        "raw_capture_hash_verification": raw_validation,
        "schema_validation": loaded,
        "timing_and_availability": {"source_capture_times_preserved": True,
            "historical_publication_time_verified": False, "source_publication_at_kst": None,
            "notation_grammar_parsed": False, "operational_database_accessed": False},
        "executed_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    DRY_RUN_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    con.close()
    return report


def verify_backup_pair() -> dict[str, Any]:
    for p in (BACKUP_DB, BACKUP_MANIFEST, BACKUP_ATTESTATION, BACKUP_ROOT_ATTESTATION):
        expect(p.is_file(), f"paired backup evidence missing: {p}")
    att = read_json(BACKUP_ATTESTATION)
    root_att = read_json(BACKUP_ROOT_ATTESTATION)
    for item in (att, root_att):
        for key, value in {"baseline_db_sha256": BASE_DB_SHA256,
                           "baseline_manifest_sha256": BASE_MANIFEST_SHA256,
                           "backup_db_sha256": BASE_DB_SHA256,
                           "backup_manifest_sha256": BASE_MANIFEST_SHA256,
                           "verified_equal": True}.items():
            expect(item.get(key) == value, f"backup attestation mismatch: {key}")
    expect(sha256_file(BACKUP_DB) == BASE_DB_SHA256 and sha256_file(BACKUP_MANIFEST) == BASE_MANIFEST_SHA256,
           "backup pair hash mismatch")
    return {"backup_db_sha256": BASE_DB_SHA256, "backup_manifest_sha256": BASE_MANIFEST_SHA256,
            "backup_attestation_sha256": sha256_file(BACKUP_ATTESTATION),
            "root_attestation_sha256": sha256_file(BACKUP_ROOT_ATTESTATION)}


def loaded_input_path_map() -> dict[str, str]:
    result = {
        f"thoroughbred/research/20261002_passing_groups_v1/{relative}": table
        for relative, table in INPUTS.values()
    }
    for relative, table in JSON_INPUTS.values():
        result[f"thoroughbred/research/20261002_passing_groups_v1/{relative}"] = table
    for relative in METADATA_FILES:
        result[relative] = "passing_source_metadata"
    for path in ERROR_CSVS.values():
        result[path] = "passing_api_error_evidence"
    return result


def atomic_update_core_manifest(post_db_sha: str, table_counts: dict[str, int],
                                pins: dict[str, dict[str, Any]], dry_run: dict[str, Any]) -> str:
    manifest = read_json(CORE_MANIFEST)
    expect(manifest.get("database_sha256") == BASE_DB_SHA256, "core manifest baseline changed before update")
    manifest.setdefault("table_and_view_counts", {}).update(table_counts)
    input_files = manifest.setdefault("input_files", [])
    expect(isinstance(input_files, list), "core manifest input_files must be a list")
    existing = {item.get("path"): item.get("sha256") for item in input_files if isinstance(item, dict)}
    path_to_table = loaded_input_path_map()
    audit_paths = {f"thoroughbred/research/20261002_passing_groups_v1/{relative}"
                   for relative in AUDIT_INPUTS.values()}
    for path, info in sorted(pins.items()):
        if path in existing:
            expect(existing[path] == info["sha256"], f"core manifest already pins {path} to different bytes")
            continue
        item: dict[str, Any] = {"path": path, "sha256": info["sha256"], "bytes": info["bytes"]}
        if info["rows"] is not None:
            item["rows"] = info["rows"]
        if path in path_to_table:
            item.update({"table": path_to_table[path], "loaded_to_database": True})
        elif path in audit_paths:
            item.update({"artifact": "independent_selection_parity_input", "loaded_to_database": False})
        else:
            item.update({"artifact": "pinned_research_source_or_audit_evidence", "loaded_to_database": False})
        input_files.append(item)
    manifest.setdefault("supplement_loads", []).append({
        "name": SOURCE_NAME, "applied_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "baseline_database_sha256": BASE_DB_SHA256, "database_sha256_after": post_db_sha,
        "backup_database": BACKUP_DB.relative_to(ROOT).as_posix(),
        "backup_manifest": BACKUP_MANIFEST.relative_to(ROOT).as_posix(),
        "backup_attestation": BACKUP_ROOT_ATTESTATION.relative_to(ROOT).as_posix(),
        "source_manifest_name": SOURCE_NAME, "api_observation_rows": EXPECTED["api_observations"],
        "rpt_point_observation_rows": EXPECTED["rpt_point_observations"],
        "confirmed_races": EXPECTED["confirmed_race_keys"],
        "loader_sha256": dry_run["loader_sha256"], "schema_sha256": dry_run["schema_sha256"],
        "input_contract_sha256": dry_run["input_contract_sha256"],
    })
    manifest["database_sha256"] = post_db_sha
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CORE_DIR,
                                         prefix=".passing_groups_manifest_", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, CORE_MANIFEST)
        dir_fd = os.open(CORE_DIR, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return sha256_file(CORE_MANIFEST)


def run_apply() -> dict[str, Any]:
    c = contract()
    pins = verify_pins(c)
    dry = read_json(DRY_RUN_REPORT)
    expect(dry.get("status") == "preflight_passed_dry_run_only" and dry.get("applied") is False,
           "a passing dry-run report is required before append")
    expect(dry.get("loader_sha256") == sha256_file(Path(__file__).resolve()), "loader changed after dry run")
    expect(dry.get("schema_sha256") == sha256_file(SCHEMA_PATH), "schema changed after dry run")
    expect(dry.get("input_contract_sha256") == sha256_file(CONTRACT_PATH), "contract changed after dry run")
    expect(sha256_file(CORE_DB) == BASE_DB_SHA256 and sha256_file(CORE_MANIFEST) == BASE_MANIFEST_SHA256,
           "core baseline changed after dry run")
    backup = verify_backup_pair()
    con = duckdb.connect(str(CORE_DB))
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET memory_limit='8GB'")
    base = core_preflight(con, "thoroughbred_core")
    pq_csv, json_files, errors, audit_inputs = input_paths(c)
    stage_inputs(con, pq_csv, json_files, errors, audit_inputs, pins, "thoroughbred_core")
    verify_manifests(con)
    verify_inputs(con)
    verify_source_bytes(con)
    try:
        con.execute("BEGIN TRANSACTION")
        schema_apply(con, temporary=False)
        loaded = validate_loaded_schema(con, "thoroughbred_core")
        manifest_json = {
            "dataset": SOURCE_NAME, "scope": {"start_date": START_DATE, "end_date": END_DATE,
            "actual_meets": {"1": "Seoul", "3": "Busan-Gyeongnam", "4": "Yeongcheon"}},
            "api_observations": EXPECTED["api_observations"], "rpt_point_observations": EXPECTED["rpt_point_observations"],
            "confirmed_races": EXPECTED["confirmed_race_keys"], "api_pages": EXPECTED["api_page_ledger"],
            "source_capture_manifest_sha256": sha256_file(API_DIR / "source_manifest.json"),
            "rpt_manifest_sha256": sha256_file(RPT_DIR / "manifest.json"),
            "input_contract_sha256": sha256_file(CONTRACT_PATH),
            "loader_sha256": sha256_file(Path(__file__).resolve()), "schema_sha256": sha256_file(SCHEMA_PATH),
            "historical_publication_time": "unverified", "notation_grammar_parsed": False,
            "raw_api_and_rpt_occurrences_preserved": True,
        }
        con.execute("INSERT INTO source_manifests(name,json_text) VALUES (?,?)",
                    [SOURCE_NAME, json.dumps(manifest_json, ensure_ascii=False, indent=2)])
        con.execute("COMMIT")
        con.execute("CHECKPOINT")
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        con.close()
        raise
    manifest_rows = int(scalar(con, "SELECT count(*) FROM source_manifests"))
    expect(manifest_rows == BASE_SOURCE_MANIFESTS + 1, "source_manifests append count mismatch")
    counts = table_view_counts(con)
    counts["source_manifests"] = manifest_rows
    con.close()
    post_sha = sha256_file(CORE_DB)
    updated_manifest_sha = atomic_update_core_manifest(post_sha, counts, pins, dry)
    report = {"status": "applied", "applied": True, "source_name": SOURCE_NAME,
              "baseline_core_sha256": BASE_DB_SHA256, "core_sha256_after": post_sha,
              "core_manifest_sha256_after": updated_manifest_sha,
              "backup_pair": backup, "new_objects": loaded, "table_and_view_counts": counts,
              "source_manifests_rows_after": manifest_rows,
              "applied_at_utc": datetime.now(UTC).isoformat(timespec="seconds")}
    APPLY_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="default: read-only in-memory preflight")
    modes.add_argument("--apply", action="store_true", help="root-only append gated by dry-run and backup")
    args = parser.parse_args()
    result = run_apply() if args.apply else run_dry_run()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
