"""Pinned read-only preflight and root-only append for steward-report research v1.

Default operation is a dry run with the existing research core attached READ_ONLY.
No operational database or service is opened by this loader. The root operator
may use --apply only after a passing frozen dry run and paired-backup review.
"""
from __future__ import annotations

import argparse
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
PACKAGE = ROOT / "thoroughbred/research/20261002_steward_reports_v1"
LOADER = PACKAGE / "loader"
CONTRACT_PATH = LOADER / "input_contract.json"
SCHEMA_PATH = LOADER / "schema.sql"
DRY_RUN_REPORT = LOADER / "dry_run_report.json"
APPLY_REPORT = LOADER / "apply_report.json"
CORE_DIR = ROOT / "thoroughbred/data/core_api_2010_20260929_v1"
CORE_DB = CORE_DIR / "thoroughbred_core.duckdb"
CORE_MANIFEST = CORE_DIR / "manifest.json"
BACKUP_DIR = CORE_DIR / "backups/20261002_before_steward_reports"
BACKUP_DB = BACKUP_DIR / "thoroughbred_core.duckdb"
BACKUP_MANIFEST = BACKUP_DIR / "manifest.json"
BACKUP_ATTESTATION = BACKUP_DIR / "backup_pair_attestation.json"
BACKUP_ROOT_ATTESTATION = PACKAGE / "root_backup_attestation.json"

BASE_DB_SHA256 = "616aa6111242cfbcee4b87bc2e77251644e5c3780fc8c978319f69e7b1c4c8f7"
BASE_MANIFEST_SHA256 = "6aa4d2870fbd087afa81973d5fc8f3966cfc00fd7896c656cb4fedaef2ef1697"
BASE_OBJECTS = 180
BASE_SOURCE_MANIFESTS = 26
SOURCE_NAME = "steward_reports_research_v1"
START_DATE = "2010-01-01"
END_DATE = "2026-09-29"
MEETS = (1, 3, 4)

# Fixed artifact names from the source/linker contracts. Final hashes/counts are
# pinned in input_contract.json only after both independent inputs are frozen.
PARQUET_INPUTS: dict[str, tuple[str, str]] = {
    "input_source_observations": ("source/api_observations.parquet", "steward_api_source_observations"),
    "input_api_page_ledger": ("source/api_page_ledger.parquet", "steward_api_page_ledger"),
    "input_source_exclusions": ("source/api_exclusions.parquet", "steward_api_scope_exclusions"),
    "input_report_event_paragraphs": ("linking/report_event_paragraphs.parquet", "steward_report_paragraphs"),
    "input_report_event_sentences": ("linking/report_event_sentences.parquet", "steward_report_sentences"),
    "input_report_horse_mentions": ("linking/report_horse_mentions.parquet", "steward_report_horse_mentions"),
    "input_report_horse_links": ("linking/report_horse_links.parquet", "steward_report_horse_links"),
    "input_report_marker_residuals": ("linking/report_marker_residuals.parquet", "steward_report_marker_residuals"),
}
JSON_INPUTS = (
    "source/source_manifest.json",
    "source/api_year_meet_coverage.json",
    "source/raw_page_sha256_manifest.json",
    "linking/manifest.json",
    "linking/build_summary.json",
    "root_source_verification.json",
    "root_linking_verification.json",
    "root_parser_control_verification.json",
    "root_manual_expected_links.json",
    "root_negative_controls.json",
    "root_backup_attestation.json",
    "root_sanction_entry_summary.json",
    "supplemental_audit/supplemental_audit_manifest.json",
    "supplemental_audit/supplemental_audit_summary.json",
    "supplemental_audit/official_ui_semantics_check.json",
)
CODE_INPUTS = (
    "collect_steward_api_sources.py",
    "linking/report_linker.py",
    "linking/build_linking_artifacts.py",
    "supplemental_audit/inventory_add_judgement.py",
    "root_source_verify.py",
    "root_linking_verify.py",
    "root_parser_controls.py",
    "loader/load_steward_reports.py",
    "loader/schema.sql",
)
AUDIT_TEXT_INPUTS = (
    "supplemental_audit/addjudgement_occurrences.csv",
    "supplemental_audit/unique_addjudgement_paragraphs.jsonl",
    "supplemental_audit/unique_addjudgement_values.csv",
    "supplemental_audit/future_date_reference_candidates.csv",
    "supplemental_audit/weekday_date_mismatch_candidates.csv",
)
AUDIT_PARQUET_INPUTS = {
    "input_root_sanction_entry_expectations": "root_sanction_entry_expectations.parquet",
}
OBJECT_RE = re.compile(r"(?im)^\s*CREATE\s+(TABLE|VIEW)\s+([a-z_][a-z0-9_]*)\b")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_CORE_SCOPE_ROWS = 29_826
EXPECTED_CONFIRMED_RACES = 29_710
EXPECTED_NONEXECUTION_RACES = 116
EXPECTED_SOURCE_ROWS = 61_439
EXPECTED_REPORT_ROWS = 14_867
EXPECTED_SANCTION_ROWS = 46_572
EXPECTED_SANCTION_EXCLUSIONS = 10
EXPECTED_PAGE_ROWS = 102
EXPECTED_PARTITIONS = 70


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
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


def safe_source_path(value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or "://" in value:
        raise ValueError(f"invalid source locator: {value!r}")
    base = (PACKAGE / "source").resolve(strict=True)
    path = (base / value).resolve(strict=True)
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError(f"source locator escapes the source package: {value}")
    return path


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def contract() -> dict[str, Any]:
    value = read_json(CONTRACT_PATH)
    expect(isinstance(value, dict), "input_contract.json must be a JSON object")
    return value


def verify_pins(c: dict[str, Any]) -> dict[str, dict[str, Any]]:
    pins = c.get("file_pins")
    expect(isinstance(pins, dict) and bool(pins), "input contract must pin files")
    actual: dict[str, dict[str, Any]] = {}
    for relative, pin in pins.items():
        path = safe_repo_path(relative)
        expect(isinstance(pin, dict) and SHA_RE.fullmatch(str(pin.get("sha256", ""))),
               f"invalid SHA pin: {relative}")
        digest, size = sha256_file(path), path.stat().st_size
        expect(digest == pin["sha256"] and size == int(pin.get("bytes", -1)),
               f"pinned artifact changed: {relative}")
        rows = pq.ParquetFile(path).metadata.num_rows if path.suffix == ".parquet" else None
        if rows is not None:
            expect(rows == int(pin.get("rows", -1)), f"Parquet row-count pin mismatch: {relative}")
        actual[relative] = {"sha256": digest, "bytes": size, "rows": rows}
    required = {
        f"thoroughbred/research/20261002_steward_reports_v1/{p}"
        for p, _ in PARQUET_INPUTS.values()
    } | {f"thoroughbred/research/20261002_steward_reports_v1/{p}" for p in JSON_INPUTS}
    required |= {f"thoroughbred/research/20261002_steward_reports_v1/{p}" for p in AUDIT_PARQUET_INPUTS.values()}
    required |= {f"thoroughbred/research/20261002_steward_reports_v1/{p}" for p in CODE_INPUTS}
    required |= {f"thoroughbred/research/20261002_steward_reports_v1/{p}" for p in AUDIT_TEXT_INPUTS}
    missing = sorted(required - set(pins))
    expect(not missing, f"input contract does not pin required files: {missing}")
    return actual


def input_paths(c: dict[str, Any]) -> dict[str, Path]:
    pinned = c["file_pins"]
    result = {}
    for alias, (relative, _) in PARQUET_INPUTS.items():
        full = f"thoroughbred/research/20261002_steward_reports_v1/{relative}"
        path = safe_repo_path(full)
        expect(full in pinned, f"input contract missing pin: {full}")
        result[alias] = path
    return result


def scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> Any:
    return con.execute(sql, params or []).fetchone()[0]


def schema_objects() -> list[tuple[str, str]]:
    return [(kind.upper(), name) for kind, name in OBJECT_RE.findall(SCHEMA_PATH.read_text(encoding="utf-8"))]


def stage_inputs(con: duckdb.DuckDBPyConnection, paths: dict[str, Path],
                 pins: dict[str, dict[str, Any]], core_catalog: str) -> None:
    for alias, path in paths.items():
        replacement = " * REPLACE (CAST(source_publication_at_kst AS VARCHAR) AS source_publication_at_kst)" if alias.startswith("input_report_") else " *"
        con.execute(f"CREATE TEMP VIEW {alias} AS SELECT{replacement} FROM read_parquet({sql_literal(str(path))})")
    for alias, relative in AUDIT_PARQUET_INPUTS.items():
        path = safe_repo_path(f"thoroughbred/research/20261002_steward_reports_v1/{relative}")
        con.execute(f"CREATE TEMP VIEW {alias} AS SELECT * FROM read_parquet({sql_literal(str(path))})")

    metadata_rows = []
    for relative in JSON_INPUTS:
        full = f"thoroughbred/research/20261002_steward_reports_v1/{relative}"
        path = safe_repo_path(full)
        metadata_rows.append({"metadata_name": path.name, "source_path": full,
                              "source_sha256": sha256_file(path),
                              "metadata_json": path.read_text(encoding="utf-8")})
    con.register("input_source_metadata", pa.Table.from_pylist(metadata_rows, schema=pa.schema([
        ("metadata_name", pa.string()), ("source_path", pa.string()),
        ("source_sha256", pa.string()), ("metadata_json", pa.string())])))
    pin_rows = [{"path": path, "sha256": info["sha256"], "bytes": info["bytes"],
                 "row_count": info["rows"]} for path, info in sorted(pins.items())]
    con.register("input_source_output_hashes", pa.Table.from_pylist(pin_rows, schema=pa.schema([
        ("path", pa.string()), ("sha256", pa.string()), ("bytes", pa.int64()),
        ("row_count", pa.int64())])))

    expect(core_catalog in {"core", "thoroughbred_core"}, "invalid core catalog")
    # These temporary aliases make the same unqualified source names available
    # to schema.sql in the memory-only preflight. In apply they resolve to main.
    if core_catalog == "core":
        for name in ("runner_results", "race_events", "race_execution_adjudicated", "entity_reference_roster"):
            con.execute(f"CREATE TEMP VIEW {name} AS SELECT * FROM core.main.{name}")


def verify_manifests(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    source = read_json(PACKAGE / "source/source_manifest.json")
    coverage = read_json(PACKAGE / "source/api_year_meet_coverage.json")
    linker = read_json(PACKAGE / "linking/manifest.json")
    source_check = read_json(PACKAGE / "root_source_verification.json")
    parser_check = read_json(PACKAGE / "root_parser_control_verification.json")
    linker_check = read_json(PACKAGE / "root_linking_verification.json")
    expect(source.get("status") == "complete", "source capture manifest not complete")
    expect(source_check.get("all_passed") is True, "independent raw source verification did not pass")
    expect(parser_check.get("all_passed") is True, "independent parser controls did not pass")
    expect(linker_check.get("all_passed") is True, "independent linkage verification did not pass")
    expect(coverage.get("all_partitions_complete") is True, "API year/meet coverage is incomplete")
    expect(len(coverage.get("partitions", [])) == EXPECTED_PARTITIONS,
           "expected 70 complete source partitions")
    expect(all(p.get("response_complete") is True for p in coverage["partitions"]),
           "one or more year/meet API responses are incomplete")
    expect(source.get("counts", {}).get("source_item_occurrences") == EXPECTED_SOURCE_ROWS,
           "source manifest occurrence total differs")
    expect(linker.get("manifest_status") == "complete", "paragraph-link manifest not complete")
    expect(linker.get("source_observations_sha256") == sha256_file(PACKAGE / "source/api_observations.parquet"),
           "linker used a different API observation input")
    for filename, digest in linker_check.get("input_sha256", {}).items():
        expect(sha256_file(PACKAGE / "linking" / filename) == digest,
               f"independent linker verification used a different artifact: {filename}")
    return {"source_manifest_status": source.get("status"),
            "source_rows": source.get("counts", {}).get("source_item_occurrences"),
            "api_page_count": source.get("counts", {}).get("pages"),
            "partitions": len(coverage["partitions"]),
            "all_partitions_complete": coverage.get("all_partitions_complete"),
            "linker_status": linker.get("status"),
            "root_source_verification": source_check.get("all_passed"),
            "root_parser_controls": parser_check.get("all_passed"),
            "root_linking_verification": linker_check.get("all_passed")}


def verify_source_bytes(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    pages = con.execute("""
      SELECT raw_page_path,response_body_sha256,response_body_bytes
      FROM input_api_page_ledger ORDER BY requested_year,requested_meet,reported_page_no
    """).fetchall()
    for relative, expected_sha, expected_bytes in pages:
        path = safe_source_path(relative)
        expect(path.stat().st_size == expected_bytes and sha256_file(path) == expected_sha,
               f"raw API page size/hash mismatch: {relative}")
    return {"exact_raw_page_files_verified": len(pages)}


def verify_inputs(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    c = contract()
    expected_rows = c.get("expected_rows", {})
    for alias, (relative, _) in PARQUET_INPUTS.items():
        expected = expected_rows.get(relative)
        if expected is not None:
            actual = int(scalar(con, f"SELECT count(*) FROM {alias}"))
            expect(actual == int(expected), f"{relative} row count {actual} != pinned expected {expected}")

    total = int(scalar(con, "SELECT count(*) FROM input_source_observations"))
    report_rows = int(scalar(con, "SELECT count(*) FROM input_source_observations WHERE dataset='api215_judge_report'"))
    sanction_rows = int(scalar(con, "SELECT count(*) FROM input_source_observations WHERE dataset='api180_1_sanction_history'"))
    exclusion_rows = int(scalar(con, "SELECT count(*) FROM input_source_exclusions"))
    page_rows = int(scalar(con, "SELECT count(*) FROM input_api_page_ledger"))
    expect((total, report_rows, sanction_rows, exclusion_rows, page_rows) == (
        EXPECTED_SOURCE_ROWS, EXPECTED_REPORT_ROWS, EXPECTED_SANCTION_ROWS,
        EXPECTED_SANCTION_EXCLUSIONS, EXPECTED_PAGE_ROWS),
        f"source totals differ: observations={total}, reports={report_rows}, sanctions={sanction_rows}, "
        f"exclusions={exclusion_rows}, pages={page_rows}")

    included_by_source = con.execute("""
      SELECT dataset,row_scope_status,count(*)::BIGINT
      FROM input_source_observations GROUP BY ALL ORDER BY ALL
    """).fetchall()
    expect(all(status in {"included", "excluded"} for _, status, _ in included_by_source),
           f"unexpected source scope status: {included_by_source}")
    report_excluded = scalar(con, "SELECT count(*) FROM input_source_observations WHERE dataset='api215_judge_report' AND row_scope_status<>'included'")
    sanction_included = scalar(con, "SELECT count(*) FROM input_source_observations WHERE dataset='api180_1_sanction_history' AND row_scope_status='included'")
    sanction_excluded = scalar(con, "SELECT count(*) FROM input_source_observations WHERE dataset='api180_1_sanction_history' AND row_scope_status='excluded'")
    expect(report_excluded == 0 and sanction_included == 46_562 and sanction_excluded == 10,
           "source scope cohort counts differ")

    duplicate_locators = scalar(con, """
       SELECT count(*)-count(DISTINCT capture_id||'|'||source_location)
       FROM input_source_observations
    """)
    expect(duplicate_locators == 0, f"source occurrence locator duplicates: {duplicate_locators}")
    missing_page_evidence = scalar(con, """
       SELECT count(*) FROM input_source_observations o
       LEFT JOIN input_api_page_ledger p
         ON p.capture_id=o.capture_id AND p.raw_page_path=o.source_path
        AND p.response_body_sha256=o.page_sha256 AND p.reported_page_no=o.page_no
       WHERE p.capture_id IS NULL
    """)
    expect(missing_page_evidence == 0, f"source rows without exact page-ledger evidence: {missing_page_evidence}")

    coverage_cte = """
      WITH coverage AS (
        SELECT dataset,requested_year,requested_meet,
          count(*) FILTER (WHERE http_status=200 AND result_code='00')=count(*)
            AND sum(returned_item_count)=max(total_count)
            AND (max(total_count)=0 OR count(DISTINCT reported_page_no)=max(expected_pages_at_response))
            AS response_partition_complete,
          sum(returned_item_count)::BIGINT AS captured_item_count,
          max(total_count)::BIGINT AS reported_total_item_count
        FROM input_api_page_ledger GROUP BY dataset,requested_year,requested_meet
      )
    """
    partitions = scalar(con, coverage_cte + "SELECT count(*) FROM coverage")
    incomplete = scalar(con, coverage_cte + "SELECT count(*) FROM coverage WHERE NOT response_partition_complete")
    expect(partitions == EXPECTED_PARTITIONS and incomplete == 0,
           f"derived API partition gate failed: partitions={partitions}, incomplete={incomplete}")
    page_total_mismatches = scalar(con, """
      SELECT count(*) FROM (
       SELECT dataset,requested_year,requested_meet,sum(returned_item_count) AS captured_item_count,
              max(total_count) AS reported_total_item_count
       FROM input_api_page_ledger GROUP BY ALL
      ) coverage
      WHERE captured_item_count<>reported_total_item_count
    """)
    expect(page_total_mismatches == 0, f"{page_total_mismatches} API partitions differ from totalCount")

    bad_scope = scalar(con, """
       SELECT count(*) FROM input_source_observations
       WHERE row_scope_status='included' AND (
         actual_meet_code NOT IN (1,3,4) OR race_date_iso IS NULL
         OR race_date_iso<'2010-01-01' OR race_date_iso>'2026-09-29'
         OR try_cast(rcNo AS SMALLINT) IS NULL
       )
    """)
    expect(bad_scope == 0, f"included observations out of scope/invalid: {bad_scope}")
    report_key_audit = con.execute("""
      SELECT coalesce(a.execution_verdict,'executed_or_unmarked') AS execution_verdict,count(*)::BIGINT
      FROM input_source_observations r
      LEFT JOIN race_execution_adjudicated a
        ON a.meet=CAST(r.actual_meet_code AS VARCHAR)
       AND a.date=replace(r.race_date_iso,'-','')
       AND try_cast(a.race_no AS SMALLINT)=try_cast(r.rcNo AS SMALLINT)
      WHERE r.dataset='api215_judge_report' AND r.row_scope_status='included'
      GROUP BY 1 ORDER BY 1
    """).fetchall()
    report_key_missing = int(scalar(con, """
      SELECT count(*) FROM input_source_observations r
      LEFT JOIN race_execution_adjudicated a
        ON a.meet=CAST(r.actual_meet_code AS VARCHAR)
       AND a.date=replace(r.race_date_iso,'-','')
       AND try_cast(a.race_no AS SMALLINT)=try_cast(r.rcNo AS SMALLINT)
      WHERE r.dataset='api215_judge_report' AND r.row_scope_status='included'
        AND a.meet IS NULL
    """))
    expect(report_key_missing == 0, f"API215 occurrences without adjudicated core event keys: {report_key_missing}")
    expect(sum(int(n) for status,n in report_key_audit if status=='no_valid_completed_race')==14,
           f"API215 adjudicated nonexecution count differs: {report_key_audit}")
    expect(sum(int(n) for status,n in report_key_audit if status=='executed_or_unmarked')==14_853,
           f"API215 executed/confirmed event count differs: {report_key_audit}")
    excluded_scope = con.execute("""
       SELECT requested_year,requested_meet,race_date_iso,actual_meet_code,row_scope_status
       FROM input_source_observations WHERE row_scope_status='excluded'
    """).fetchall()
    expect(len(excluded_scope) == EXPECTED_SANCTION_EXCLUSIONS and all(
        (row[2] is not None and row[2] > END_DATE) for row in excluded_scope),
        "excluded-source rows do not match the documented post-cutoff receipts")

    unsupported_gubun = con.execute("""
      SELECT DISTINCT gubun FROM input_source_observations
      WHERE dataset='api180_1_sanction_history' AND row_scope_status='included'
        AND gubun NOT IN ('말','기수')
    """).fetchall()
    expect(not unsupported_gubun, f"unreviewed API180 target class values: {unsupported_gubun}")

    expected_sanctions = int(scalar(con, "SELECT count(*) FROM input_root_sanction_entry_expectations"))
    expect(expected_sanctions == 46_562, f"independent sanction-entry evidence has {expected_sanctions} rows")

    # Paragraph text is a literal slice of exactly the referenced API field and
    # exact source observation. The linker keeps parent and target event keys
    # separately for addJudgement historical references.
    bad_paragraph_slices = scalar(con, """
      SELECT count(*) FROM input_report_event_paragraphs p
      LEFT JOIN input_source_observations o
        ON o.capture_id||'|'||o.source_location=p.observation_locator
      WHERE p.paragraph_state='text' AND (o.source_row_sha256 IS NULL OR o.dataset<>'api215_judge_report'
         OR p.paragraph_raw IS NULL OR trim(p.paragraph_raw)=''
         OR p.span_start_codepoint IS NULL OR p.span_end_codepoint IS NULL
         OR p.span_start_codepoint<0 OR p.span_end_codepoint<p.span_start_codepoint
         OR p.span_end_codepoint>length(p.paragraph_source_text_raw)
         OR substr(p.paragraph_source_text_raw,p.span_start_codepoint+1,
                   p.span_end_codepoint-p.span_start_codepoint)<>p.paragraph_raw
         OR p.paragraph_source_text_raw IS DISTINCT FROM
            CASE p.report_text_field WHEN 'judgement' THEN o.judgement
                 WHEN 'addJudgement' THEN o.addJudgement
                 WHEN 'jkChange' THEN o.jkChange END)
    """)
    expect(bad_paragraph_slices == 0, f"paragraph source/span parity failures: {bad_paragraph_slices}")
    bad_field_states = scalar(con, """
      SELECT count(*) FROM input_report_event_paragraphs p
      LEFT JOIN input_source_observations o
        ON o.capture_id||'|'||o.source_location=p.observation_locator
      WHERE p.paragraph_state<>'text' AND (
         o.source_row_sha256 IS NULL OR o.dataset<>'api215_judge_report'
         OR p.span_start_codepoint IS NOT NULL OR p.span_end_codepoint IS NOT NULL
         OR p.paragraph_raw IS DISTINCT FROM
            CASE p.report_text_field WHEN 'judgement' THEN o.judgement
                 WHEN 'addJudgement' THEN o.addJudgement
                 WHEN 'jkChange' THEN o.jkChange END
         OR p.paragraph_source_text_raw IS DISTINCT FROM
            CASE p.report_text_field WHEN 'judgement' THEN o.judgement
                 WHEN 'addJudgement' THEN o.addJudgement
                 WHEN 'jkChange' THEN o.jkChange END
      )
    """)
    expect(bad_field_states == 0, f"report text-field state parity failures: {bad_field_states}")

    invalid_link_keys = scalar(con, """
      SELECT count(*) FROM input_report_horse_links l
      LEFT JOIN input_report_event_paragraphs p USING(paragraph_locator)
      LEFT JOIN input_source_observations o
        ON o.capture_id||'|'||o.source_location=l.observation_locator
      WHERE l.status IS DISTINCT FROM 'linked' OR l.mention_semantics IS DISTINCT FROM 'mentioned_in_report_paragraph'
         OR l.match_rule IS NULL OR l.match_rule NOT IN ('explicit_number_name_race_roster_exact',
                                 'explicit_number_name_venue_prefix_exact',
                                 'report_local_exact_name_from_unique_anchor')
         OR p.paragraph_locator IS NULL OR o.source_row_sha256 IS NULL
         OR o.dataset<>'api215_judge_report'
         OR l.target_actual_meet_code IS NULL OR l.target_actual_meet_code NOT IN (1,3,4)
         OR l.target_event_date IS NULL OR l.target_event_date<'2010-01-01' OR l.target_event_date>'2026-09-29'
         OR try_cast(l.target_race_no AS INTEGER) IS NULL
         OR l.linked_mention_locators_json IS NULL OR json_array_length(l.linked_mention_locators_json)=0
         OR l.linked_sentence_locators_json IS NULL OR json_array_length(l.linked_sentence_locators_json)=0
    """)
    expect(invalid_link_keys == 0, f"report horse-link evidence fields/status invalid: {invalid_link_keys}")
    bad_roster_links = scalar(con, """
      SELECT count(*) FROM input_report_horse_links l
      LEFT JOIN runner_results r
        ON try_cast(r.source_meet AS SMALLINT)=l.target_actual_meet_code
       AND r.result_date=replace(l.target_event_date,'-','')
       AND try_cast(r.result_race_no AS INTEGER)=try_cast(l.target_race_no AS INTEGER)
       AND r.horse_program_no_raw=l.program_no_raw
       AND r.horse_id_raw=l.official_horse_id
      WHERE r.horse_id_raw IS NULL
    """)
    expect(bad_roster_links == 0, f"report horse links without exact target-event roster proof: {bad_roster_links}")
    bad_sentence_slices = scalar(con, """
      SELECT count(*) FROM input_report_event_sentences s
      LEFT JOIN input_report_event_paragraphs p USING(paragraph_locator)
      WHERE p.paragraph_locator IS NULL OR s.sentence_raw IS NULL
         OR s.span_start_codepoint<p.span_start_codepoint
         OR s.span_end_codepoint>p.span_end_codepoint
         OR s.span_end_codepoint<s.span_start_codepoint
         OR substr(s.sentence_source_text_raw,s.span_start_codepoint+1,
                   s.span_end_codepoint-s.span_start_codepoint) IS DISTINCT FROM s.sentence_raw
         OR s.sentence_source_text_raw IS DISTINCT FROM p.paragraph_source_text_raw
    """)
    expect(bad_sentence_slices == 0, f"sentence source/span parity failures: {bad_sentence_slices}")
    bad_mention_slices = scalar(con, """
      SELECT count(*) FROM input_report_horse_mentions m
      LEFT JOIN input_report_event_paragraphs p USING(paragraph_locator)
      WHERE p.paragraph_locator IS NULL OR m.span_start_codepoint IS NULL OR m.span_end_codepoint IS NULL
         OR m.span_end_codepoint<m.span_start_codepoint
         OR substr(p.paragraph_source_text_raw,m.span_start_codepoint+1,
                   m.span_end_codepoint-m.span_start_codepoint) IS DISTINCT FROM m.mention_raw
    """)
    expect(bad_mention_slices == 0, f"horse mention source/span parity failures: {bad_mention_slices}")
    bad_link_mention_refs = scalar(con, """
      SELECT count(*) FROM input_report_horse_links l
      CROSS JOIN json_each(l.linked_mention_locators_json) j
      LEFT JOIN input_report_horse_mentions m
        ON m.mention_locator=json_extract_string(j.value,'$')
       AND m.paragraph_locator=l.paragraph_locator
      WHERE m.mention_locator IS NULL
         OR m.candidate_status NOT IN ('explicit_number_name_race_roster_exact',
               'explicit_number_name_venue_prefix_exact',
               'report_local_exact_name_from_unique_anchor')
         OR m.candidate_official_horse_id IS DISTINCT FROM l.official_horse_id
         OR m.candidate_roster_program_no_raw IS DISTINCT FROM l.program_no_raw
    """)
    expect(bad_link_mention_refs == 0,
           f"report links with missing or mismatched supporting mention rows: {bad_link_mention_refs}")
    bad_link_sentence_refs = scalar(con, """
      SELECT count(*) FROM input_report_horse_links l
      CROSS JOIN json_each(l.linked_sentence_locators_json) j
      LEFT JOIN input_report_event_sentences s
        ON s.sentence_locator=json_extract_string(j.value,'$')
       AND s.paragraph_locator=l.paragraph_locator
      WHERE s.sentence_locator IS NULL
    """)
    expect(bad_link_sentence_refs == 0,
           f"report links with missing paragraph sentence evidence: {bad_link_sentence_refs}")
    parent_target_mismatch = scalar(con, """
      SELECT count(*) FROM input_report_horse_links l
      JOIN input_report_event_paragraphs p USING(paragraph_locator)
      JOIN input_source_observations o ON o.capture_id||'|'||o.source_location=l.observation_locator
      WHERE p.observation_locator<>l.observation_locator
        OR (p.report_text_field<>'addJudgement' AND (
              l.target_actual_meet_code<>o.actual_meet_code
           OR l.target_event_date<>o.race_date_iso
           OR try_cast(l.target_race_no AS INTEGER)<>o.rcNo))
    """)
    expect(parent_target_mismatch == 0,
           f"non-addJudgement passage links do not use their report event key: {parent_target_mismatch}")

    return {"source_observations": total,"report_observations": report_rows,
            "sanction_observations_raw": sanction_rows,"sanction_observations_in_scope": sanction_included,
            "post_cutoff_exclusions": exclusion_rows,"api_pages": page_rows,
            "report_event_execution_verdict_counts":[{"verdict":s,"rows":int(n)} for s,n in report_key_audit],
            "report_event_keys_missing_from_adjudicated_core":report_key_missing,
            "complete_year_meet_partitions": partitions,"incomplete_partitions": incomplete,
            "duplicate_source_occurrence_locators": duplicate_locators,
            "source_rows_without_page_receipt": missing_page_evidence,
            "paragraph_span_parity_failures": bad_paragraph_slices,
            "report_text_field_state_parity_failures": bad_field_states,
            "sentence_span_parity_failures": bad_sentence_slices,
            "horse_mention_span_parity_failures": bad_mention_slices,
            "linked_mention_reference_failures": bad_link_mention_refs,
            "linked_sentence_reference_failures": bad_link_sentence_refs,
            "report_horse_links_without_event_roster_proof": bad_roster_links,
            "invalid_report_horse_link_fields": invalid_link_keys,
            "report_parent_target_key_mismatches": parent_target_mismatch,
            "sanction_target_class_values": [v[0] for v in con.execute("""
              SELECT DISTINCT gubun FROM input_source_observations
              WHERE dataset='api180_1_sanction_history' AND row_scope_status='included'
              ORDER BY 1
            """).fetchall()],
            "scope_group_counts": [{"dataset":d,"status":s,"rows":int(n)} for d,s,n in included_by_source],
            "independent_sanction_entry_expectation_rows": expected_sanctions}


def schema_apply(con: duckdb.DuckDBPyConnection, *, temporary: bool) -> None:
    for parsed in duckdb.extract_statements(SCHEMA_PATH.read_text(encoding="utf-8")):
        statement = re.sub(r"(?m)^\s*--.*$", "", parsed.query).strip()
        if not statement:
            continue
        if temporary:
            statement = re.sub(r"^CREATE TABLE\b", "CREATE TEMP TABLE", statement, count=1, flags=re.I)
            statement = re.sub(r"^CREATE VIEW\b", "CREATE TEMP VIEW", statement, count=1, flags=re.I)
        con.execute(statement)


def object_inventory(con: duckdb.DuckDBPyConnection, catalog: str) -> dict[str, str]:
    tables = con.execute("""SELECT table_name FROM duckdb_tables()
      WHERE database_name=? AND schema_name='main' AND NOT internal""",[catalog]).fetchall()
    views = con.execute("""SELECT view_name FROM duckdb_views()
      WHERE database_name=? AND schema_name='main' AND NOT internal""",[catalog]).fetchall()
    return {name:"TABLE" for (name,) in tables}|{name:"VIEW" for (name,) in views}


def table_view_counts(con: duckdb.DuckDBPyConnection) -> dict[str,int]:
    return {name:int(scalar(con,f'SELECT count(*) FROM "{name}"')) for _,name in schema_objects()}


def core_preflight(con: duckdb.DuckDBPyConnection,catalog: str) -> dict[str,Any]:
    objects=object_inventory(con,catalog)
    manifest_rows=int(scalar(con,f"SELECT count(*) FROM {catalog}.main.source_manifests"))
    existing=int(scalar(con,f"SELECT count(*) FROM {catalog}.main.source_manifests WHERE name=?",[SOURCE_NAME]))
    collisions=sorted(set(objects)&{name for _,name in schema_objects()})
    expect(len(objects)==BASE_OBJECTS,f"core object count differs: {len(objects)}")
    expect(manifest_rows==BASE_SOURCE_MANIFESTS,f"source_manifests count differs: {manifest_rows}")
    expect(existing==0,f"source manifest {SOURCE_NAME!r} already exists")
    expect(not collisions,f"target object collisions in core: {collisions}")
    return {"core_object_count":len(objects),"source_manifests_rows":manifest_rows,
            "source_name_existing_rows":existing,"object_collisions":collisions}


def validate_loaded_schema(con: duckdb.DuckDBPyConnection,catalog: str) -> dict[str,Any]:
    objects=schema_objects()
    expect(len(objects)==len({name for _,name in objects}),"duplicate object names in schema")
    actual=object_inventory(con,catalog)
    expected={name:kind for kind,name in objects}
    created={name:kind for name,kind in actual.items() if name.startswith("steward_") or name=="horse_steward_history"}
    expect(created==expected,f"created object set/type differs from schema: {created}")
    counts=table_view_counts(con)
    expect(counts["steward_api_source_observations"]==EXPECTED_SOURCE_ROWS,"raw observation table count mismatch")
    expect(counts["steward_api_page_ledger"]==EXPECTED_PAGE_ROWS,"page ledger count mismatch")
    expect(counts["steward_api_scope_exclusions"]==EXPECTED_SANCTION_EXCLUSIONS,"exclusion table count mismatch")
    expect(counts["steward_source_year_meet_coverage"]==EXPECTED_PARTITIONS,"year/meet coverage partition count mismatch")
    expect(counts["steward_report_event_coverage"]==EXPECTED_CORE_SCOPE_ROWS,"event coverage must retain all core event keys")
    expect(counts["steward_sanction_target_link_audit"]==46_562,"sanction audit must retain each in-scope occurrence")
    expected_links=counts["steward_report_horse_links"]
    raw_history=counts["steward_report_horse_paragraph_history"]
    expect(raw_history==expected_links,"raw horse history must preserve every verified paragraph link")
    summarized_observations=int(scalar(con,"SELECT coalesce(sum(full_report_observation_count),0) FROM horse_steward_history"))
    expect(summarized_observations==expected_links,
           "canonical horse history must account for each raw paragraph link exactly once")
    no_pub=scalar(con,"""
      SELECT count(*) FROM steward_api_source_observations
      WHERE historical_publication_time_verified IS DISTINCT FROM FALSE
         OR source_publication_at_kst IS NOT NULL
    """)
    expect(no_pub==0,"raw API observations claim historical publication times")
    nonexec=counts["steward_report_nonexecution_observations"]
    expect(nonexec==14,"14 adjudicated nonexecution API215 reports must remain attached to event ledger")
    sanction_parity=verify_sanction_expectations(con)
    sanction_status=con.execute("""
      SELECT target_link_status,count(*)::BIGINT FROM steward_sanction_target_link_audit
      GROUP BY 1 ORDER BY 1
    """).fetchall()
    return {"created_objects":objects,"row_counts":counts,
            "independent_sanction_entry_parity":sanction_parity,
            "verified_sanction_target_link_status_counts":[{"status":s,"rows":int(n)} for s,n in sanction_status],
            "nonexecution_reports_retained":nonexec,"historical_publication_claims":no_pub}


def verify_sanction_expectations(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    mismatches = int(scalar(con, """
      SELECT count(*) FROM input_root_sanction_entry_expectations e
      FULL OUTER JOIN steward_sanction_target_link_audit a
        ON a.sanction_observation_locator=e.observation_locator
      WHERE e.observation_locator IS NULL OR a.sanction_observation_locator IS NULL
         OR a.target_gubun_raw IS DISTINCT FROM e.gubun
         OR a.target_official_id_raw IS DISTINCT FROM e.prNo
         OR try_cast(a.target_program_no_raw AS SMALLINT) IS DISTINCT FROM e.chulNo
         OR try_cast(a.actual_meet_code AS TINYINT) IS DISTINCT FROM e.actual_meet_code
         OR try_cast(a.rc_date_raw AS BIGINT) IS DISTINCT FROM e.rcDate
         OR try_cast(a.race_no_raw AS SMALLINT) IS DISTINCT FROM e.rcNo
         OR a.exact_target_entry_match_count IS DISTINCT FROM e.exact_target_matches
         OR a.exact_id_entry_and_name_match_count IS DISTINCT FROM e.exact_target_name_matches
    """))
    expect(mismatches == 0,
           f"independent sanction event-entry parity has {mismatches} row mismatches")
    return {"expected_occurrences": 46_562, "mismatches": mismatches,
            "comparison": "full-outer occurrence locator, exact target ID/program/event, and independent roster match counts"}


def verify_manual_link_expectations(con: duckdb.DuckDBPyConnection) -> dict[str,Any]:
    expected_rows=read_json(PACKAGE/"root_manual_expected_links.json")
    observed={}
    for meet,date_text,race_no,field,index,program in con.execute("""
      SELECT o.actual_meet_code,o.race_date_iso,try_cast(o.rcNo AS INTEGER),
             p.report_text_field,p.paragraph_index,try_cast(l.program_no_raw AS INTEGER) AS program
      FROM input_report_event_paragraphs p
      JOIN input_report_horse_links l USING(paragraph_locator)
      JOIN input_source_observations o ON o.capture_id||'|'||o.source_location=p.observation_locator
      WHERE p.report_text_field='judgement' AND p.paragraph_state='text'
      ORDER BY o.actual_meet_code,o.race_date_iso,o.rcNo,p.paragraph_index,program
    """).fetchall():
        iso_date = str(date_text)
        if len(iso_date) == 8 and iso_date.isdigit():
            iso_date = f"{iso_date[:4]}-{iso_date[4:6]}-{iso_date[6:8]}"
        observed.setdefault((int(meet),iso_date,int(race_no)),{}).setdefault(int(index),set()).add(int(program))
    checked=0; mismatches=[]
    for item in expected_rows:
        raw_date=str(item["date"])
        iso_date=f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}" if len(raw_date)==8 and raw_date.isdigit() else raw_date
        key=(int(item["meet"]),iso_date,int(item["race_no"]))
        wanted={i:sorted(map(int,vals)) for i,vals in enumerate(item["expected_horses_by_bullet"])}
        got={i:sorted(vals) for i,vals in observed.get(key,{}).items()}
        checked+=1
        if wanted!=got:
            mismatches.append({"key":key,"expected":wanted,"observed":got})
    expect(checked==3 and not mismatches,
           f"independent three-event paragraph/link expectation failed: {mismatches}")
    return {"independent_manual_events_checked":checked,"expected_horse_paragraph_links":40,
            "manual_link_mismatches":mismatches}


def run_dry_run() -> dict[str,Any]:
    c=contract()
    expect(c.get("dataset")==SOURCE_NAME,"input contract dataset mismatch")
    expect(c.get("scope")=={"start_date":START_DATE,"end_date":END_DATE,"meets":list(MEETS)},
           "input contract scope mismatch")
    pins=verify_pins(c)
    expect(sha256_file(CORE_DB)==BASE_DB_SHA256,"core DB SHA differs from frozen baseline")
    expect(sha256_file(CORE_MANIFEST)==BASE_MANIFEST_SHA256,"core manifest SHA differs from frozen baseline")
    manifest=read_json(CORE_MANIFEST)
    expect(manifest.get("database_sha256")==BASE_DB_SHA256,"core manifest database SHA mismatch")
    con=duckdb.connect(":memory:")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET memory_limit='8GB'")
    con.execute("ATTACH "+sql_literal(str(CORE_DB))+" AS core (READ_ONLY)")
    base=core_preflight(con,"core")
    paths=input_paths(c)
    stage_inputs(con,paths,pins,"core")
    manifests=verify_manifests(con)
    raw=verify_source_bytes(con)
    input_report=verify_inputs(con)
    schema_apply(con,temporary=True)
    loaded=validate_loaded_schema(con,"temp")
    manual=verify_manual_link_expectations(con)
    after=sha256_file(CORE_DB)
    expect(after==BASE_DB_SHA256,"read-only dry run changed the core database hash")
    report={"status":"preflight_passed_dry_run_only","applied":False,
        "operational_database_or_service_opened_or_modified":False,
        "core_database_path":CORE_DB.relative_to(ROOT).as_posix(),
        "baseline_core_database_sha256":BASE_DB_SHA256,"baseline_core_manifest_sha256":BASE_MANIFEST_SHA256,
        "core_sha256_after_dry_run":after,"loader_sha256":sha256_file(Path(__file__).resolve()),
        "schema_sha256":sha256_file(SCHEMA_PATH),"input_contract_sha256":sha256_file(CONTRACT_PATH),
        "input_file_pins":pins,"core_preflight":base,"source_manifests":manifests,
        "source_page_verification":raw,"input_validation":input_report,
        "loaded_schema_validation":loaded,"independent_link_checks":manual,
        "interpretation_policy":{"historical_publication_time_verified":False,
          "source_publication_at_kst":None,"report_mentions_are_blame_attributions":False,
          "absence_of_report_or_sanction_is_clean_event_evidence":False,
          "duplicate_natural_key_sanctions_collapsed":False,
          "addJudgement_horse_links_use_validated_target_event_roster":True},
        "executed_at_utc":datetime.now(UTC).isoformat(timespec="seconds")}
    DRY_RUN_REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    con.close()
    return report


def verify_backup_pair() -> dict[str,Any]:
    for p in (BACKUP_DB,BACKUP_MANIFEST,BACKUP_ATTESTATION,BACKUP_ROOT_ATTESTATION):
        expect(p.is_file(),f"paired backup evidence missing: {p}")
    local=read_json(BACKUP_ATTESTATION); root=read_json(BACKUP_ROOT_ATTESTATION)
    for item in (local,root):
        for key,value in {"baseline_db_sha256":BASE_DB_SHA256,"baseline_manifest_sha256":BASE_MANIFEST_SHA256,
                          "backup_db_sha256":BASE_DB_SHA256,"backup_manifest_sha256":BASE_MANIFEST_SHA256,
                          "verified_equal":True}.items():
            expect(item.get(key)==value,f"backup attestation mismatch for {key}")
    expect(sha256_file(BACKUP_DB)==BASE_DB_SHA256 and sha256_file(BACKUP_MANIFEST)==BASE_MANIFEST_SHA256,
           "paired backup hashes differ from baseline")
    return {"backup_db_sha256":BASE_DB_SHA256,"backup_manifest_sha256":BASE_MANIFEST_SHA256,
            "backup_attestation_sha256":sha256_file(BACKUP_ATTESTATION),
            "root_attestation_sha256":sha256_file(BACKUP_ROOT_ATTESTATION)}


def loaded_input_path_map() -> dict[str,str]:
    return {f"thoroughbred/research/20261002_steward_reports_v1/{relative}":table
            for relative,table in PARQUET_INPUTS.values()} | {
            f"thoroughbred/research/20261002_steward_reports_v1/{p}":"steward_source_metadata"
            for p in JSON_INPUTS}


def atomic_update_core_manifest(post_db_sha: str,counts: dict[str,int],pins: dict[str,dict[str,Any]],dry: dict[str,Any]) -> str:
    manifest=read_json(CORE_MANIFEST)
    expect(manifest.get("database_sha256")==BASE_DB_SHA256,"core manifest baseline changed before update")
    manifest.setdefault("table_and_view_counts",{}).update(counts)
    inputs=manifest.setdefault("input_files",[])
    expect(isinstance(inputs,list),"core manifest input_files must be a list")
    existing={x.get("path"):x.get("sha256") for x in inputs if isinstance(x,dict)}
    paths=loaded_input_path_map()
    for rel,info in sorted(pins.items()):
        if rel in existing:
            expect(existing[rel]==info["sha256"],f"manifest already pins {rel} with different hash")
            continue
        item={"path":rel,"sha256":info["sha256"],"bytes":info["bytes"]}
        if info["rows"] is not None: item["rows"]=info["rows"]
        if rel in paths: item.update({"table":paths[rel],"loaded_to_database":True})
        else: item.update({"artifact":"pinned_research_source_or_audit_evidence","loaded_to_database":False})
        inputs.append(item)
    manifest.setdefault("supplement_loads",[]).append({
        "name":SOURCE_NAME,"applied_at_utc":datetime.now(UTC).isoformat(timespec="seconds"),
        "baseline_database_sha256":BASE_DB_SHA256,"database_sha256_after":post_db_sha,
        "backup_database":BACKUP_DB.relative_to(ROOT).as_posix(),
        "backup_manifest":BACKUP_MANIFEST.relative_to(ROOT).as_posix(),
        "backup_attestation":BACKUP_ROOT_ATTESTATION.relative_to(ROOT).as_posix(),
        "source_manifest_name":SOURCE_NAME,"source_observations":EXPECTED_SOURCE_ROWS,
        "report_observations":EXPECTED_REPORT_ROWS,"sanction_source_rows":EXPECTED_SANCTION_ROWS,
        "loader_sha256":dry["loader_sha256"],"schema_sha256":dry["schema_sha256"],
        "input_contract_sha256":dry["input_contract_sha256"]})
    manifest["database_sha256"]=post_db_sha
    temp=None
    try:
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=CORE_DIR,
                prefix=".steward_reports_manifest_",suffix=".tmp",delete=False) as stream:
            temp=Path(stream.name); stream.write(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temp,CORE_MANIFEST)
        dfd=os.open(CORE_DIR,os.O_RDONLY)
        try: os.fsync(dfd)
        finally: os.close(dfd)
    finally:
        if temp is not None and temp.exists(): temp.unlink()
    return sha256_file(CORE_MANIFEST)


def run_apply() -> dict[str,Any]:
    c=contract(); pins=verify_pins(c); dry=read_json(DRY_RUN_REPORT)
    expect(dry.get("status")=="preflight_passed_dry_run_only" and dry.get("applied") is False,
           "passing dry-run report is required")
    expect(dry.get("loader_sha256")==sha256_file(Path(__file__).resolve()),"loader changed after dry run")
    expect(dry.get("schema_sha256")==sha256_file(SCHEMA_PATH),"schema changed after dry run")
    expect(dry.get("input_contract_sha256")==sha256_file(CONTRACT_PATH),"contract changed after dry run")
    expect(sha256_file(CORE_DB)==BASE_DB_SHA256 and sha256_file(CORE_MANIFEST)==BASE_MANIFEST_SHA256,
           "core baseline changed since dry run")
    backup=verify_backup_pair()
    con=duckdb.connect(str(CORE_DB))
    con.execute("SET preserve_insertion_order=false"); con.execute("SET memory_limit='8GB'")
    catalog=str(scalar(con,"SELECT current_database()"))
    base=core_preflight(con,catalog)
    paths=input_paths(c); stage_inputs(con,paths,pins,"thoroughbred_core")
    verify_manifests(con); verify_source_bytes(con); verify_inputs(con)
    try:
        con.execute("BEGIN TRANSACTION")
        schema_apply(con,temporary=False)
        loaded=validate_loaded_schema(con,catalog)
        manifest_row={"dataset":SOURCE_NAME,"scope":{"start_date":START_DATE,"end_date":END_DATE,
            "actual_meets":{"1":"Seoul","3":"Busan-Gyeongnam","4":"Yeongcheon"}},
            "source_observations":EXPECTED_SOURCE_ROWS,"report_observations":EXPECTED_REPORT_ROWS,
            "sanction_source_rows":EXPECTED_SANCTION_ROWS,"api_pages":EXPECTED_PAGE_ROWS,
            "historical_publication_time":"unverified","sanction_natural_keys_collapsed":False,
            "report_horse_link_semantics":"mentioned_in_report_paragraph_no_blame_inference",
            "loader_sha256":dry["loader_sha256"],"schema_sha256":dry["schema_sha256"],
            "input_contract_sha256":dry["input_contract_sha256"]}
        con.execute("INSERT INTO source_manifests(name,json_text) VALUES (?,?)",
                    [SOURCE_NAME,json.dumps(manifest_row,ensure_ascii=False,indent=2)])
        con.execute("COMMIT"); con.execute("CHECKPOINT")
    except Exception:
        try: con.execute("ROLLBACK")
        except Exception: pass
        con.close(); raise
    manifest_rows=int(scalar(con,"SELECT count(*) FROM source_manifests"))
    expect(manifest_rows==BASE_SOURCE_MANIFESTS+1,"source_manifests append count mismatch")
    counts=table_view_counts(con); counts["source_manifests"]=manifest_rows; con.close()
    post_sha=sha256_file(CORE_DB)
    updated=atomic_update_core_manifest(post_sha,counts,pins,dry)
    result={"status":"applied","applied":True,"source_name":SOURCE_NAME,
            "baseline_core_sha256":BASE_DB_SHA256,"core_sha256_after":post_sha,
            "core_manifest_sha256_after":updated,"backup_pair":backup,
            "new_objects":loaded,"table_and_view_counts":counts,
            "source_manifests_rows_after":manifest_rows,
            "applied_at_utc":datetime.now(UTC).isoformat(timespec="seconds")}
    APPLY_REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run",action="store_true",help="default: read-only in-memory preflight")
    modes.add_argument("--apply",action="store_true",help="root-only append gated by passing dry run and backup")
    args=parser.parse_args()
    result=run_apply() if args.apply else run_dry_run()
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
