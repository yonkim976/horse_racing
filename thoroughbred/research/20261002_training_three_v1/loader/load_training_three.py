"""Validate and optionally append hash-pinned API18_1/API22_1/API216 research rows.

The default command reads the core database read-only and evaluates the proposed
tables and views in a temporary DuckDB database. Core writes require both
``--apply`` and ``--confirm-core-append``.
"""

from __future__ import annotations

import argparse
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


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
DEFAULT_INPUT = OUT / "input"
CORE_DIR = ROOT / "thoroughbred/data/core_api_2010_20260929_v1"
CORE_DB = CORE_DIR / "thoroughbred_core.duckdb"
CORE_MANIFEST = CORE_DIR / "manifest.json"
BACKUP_DIR = CORE_DIR / "backups/20261002_before_training_three"
BASE_DB_SHA256 = "087914d31ac0f7025c6f399e5a5aef7ebd221c7bc5dfe08078caf1207847eae1"
SOURCE_MANIFEST_NAME = "training_three_api18_api22_api216_v1"
AVAILABILITY_STATUS = "retrospective_training_observation_not_verified_pre_race"
PHYSICAL_VENUE_STATUS = "raw_venue_not_adjudicated"
START_DATE = date(2010, 1, 1)
END_DATE = date(2026, 9, 29)
MEETS = ("1", "3")
DATASETS = {
    "daily_training": {
        "parquet": "daily_training.parquet",
        "inventory": "daily_training_inventory.json",
        "endpoint": "API18_1",
    },
    "start_training": {
        "parquet": "start_training.parquet",
        "inventory": "start_training_inventory.json",
        "endpoint": "API22_1",
    },
    "swim_training": {
        "parquet": "swim_training.parquet",
        "inventory": "swim_training_inventory.json",
        "endpoint": "API216",
    },
}
PARQUET_COLUMNS = [
    "dataset", "observation_id", "event_date", "meet", "official_horse_id",
    "raw_name", "raw_path", "raw_sha256", "source_page_no", "source_row_no",
    "source_captured_at", "capture_basis", "endpoint", "raw_payload_json",
    "typed_fields_json", "link_status", "linked_core_horse_id", "qa_flags_json",
    "capture_id",
]
RAW_TABLE_COLUMNS = PARQUET_COLUMNS + [
    "availability_status", "historical_prerace_eligibility_verified", "physical_venue_status",
]
CORE_OBJECT_TYPES = {
    "training_raw_observations": "BASE TABLE",
    "training_capture_coverage": "BASE TABLE",
    "training_source_files": "BASE TABLE",
    "daily_training_raw": "VIEW",
    "start_training_raw": "VIEW",
    "swim_training_raw": "VIEW",
    "training_observation_qa": "VIEW",
    "training_date_coverage": "VIEW",
    "training_source_entities": "VIEW",
}
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_KEY_RE = re.compile(r"(?i)(secret|service.?key|authorization|access.?token|api.?key|url)")
URL_RE = re.compile(r"(?i)https?://")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def sql_literal(value: str) -> str:
    """Quote a validated local path for DuckDB's non-parameterizable file reader."""
    return "'" + value.replace("'", "''") + "'"


def safe_repository_file(relative: str, *, must_exist: bool = True) -> Path:
    if not isinstance(relative, str) or not relative or URL_RE.search(relative):
        raise ValueError(f"expected a repository-relative file path: {relative!r}")
    candidate = (ROOT / relative).resolve(strict=must_exist)
    if not candidate.is_relative_to(ROOT.resolve(strict=True)):
        raise ValueError(f"input path escapes repository root: {relative}")
    if must_exist and not candidate.is_file():
        raise ValueError(f"input path is not a file: {relative}")
    return candidate


def assert_no_secret_material(value: Any, location: str = "inventory") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if FORBIDDEN_KEY_RE.search(str(key)):
                raise ValueError(f"sensitive or URL metadata key is not allowed in {location}: {key}")
            assert_no_secret_material(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_no_secret_material(item, f"{location}[{index}]")
    elif isinstance(value, str) and URL_RE.search(value):
        raise ValueError(f"URL metadata is not allowed in {location}")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def parse_date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} is not an ISO date: {value!r}") from exc


def parse_utc_naive(value: Any, label: str) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).replace(tzinfo=None)
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO timestamp, epoch milliseconds, or null")
    text = value.strip()
    if text.isdigit():
        return datetime.fromtimestamp(int(text) / 1000, tz=timezone.utc).replace(tzinfo=None)
    if text.endswith("Z"):
        # Accept both a conventional UTC suffix (`...T...Z`) and source
        # inventories that retain an explicit zero offset before the suffix
        # (`...T...+00:00Z`).
        text = text[:-1]
        if not re.search(r"[+-]\d{2}:?\d{2}$", text):
            text += "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label} is not a timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        # Inventory timestamp fields ending in _utc have already been normalized
        # to UTC by the capture agent; source_metadata_json retains the raw basis.
        return parsed
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def parse_optional_integer(value: Any, label: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer or null: {value!r}") from exc


def parse_bool(value: Any, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.casefold().strip()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    raise ValueError(f"{label} must be a boolean")


def expected_calendar_pairs() -> set[tuple[date, str]]:
    days = (END_DATE - START_DATE).days + 1
    return {
        (date.fromordinal(START_DATE.toordinal() + offset), meet)
        for offset in range(days) for meet in MEETS
    }


def catalog_objects(connection: duckdb.DuckDBPyConnection) -> dict[str, str]:
    rows = connection.execute("""
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_catalog = current_database() AND table_schema = 'main'
    """).fetchall()
    return {str(name): str(kind) for name, kind in rows}


def arrow_insert(connection: duckdb.DuckDBPyConnection, table_name: str,
                 columns: list[str], rows: list[dict[str, Any]], schema: Any) -> None:
    import pyarrow as pa

    if not rows:
        return
    insert_columns = ", ".join(f'"{column}"' for column in columns)
    sql = f"INSERT INTO {table_name} ({insert_columns}) SELECT {insert_columns} FROM _training_incoming"
    for offset in range(0, len(rows), 5000):
        table = pa.Table.from_pylist(rows[offset:offset + 5000], schema=schema)
        connection.register("_training_incoming", table)
        try:
            connection.execute(sql)
        finally:
            connection.unregister("_training_incoming")


def normalize_inventory_file(dataset: str, entry: dict[str, Any],
                             dataset_endpoint: str) -> dict[str, Any]:
    required = ("raw_path", "raw_sha256", "row_count", "capture_id", "capture_basis", "endpoint", "is_selected")
    missing = [name for name in required if name not in entry]
    if missing:
        raise ValueError(f"{dataset} source_files item lacks required fields: {missing}")
    raw_path = entry["raw_path"]
    selected = parse_bool(entry["is_selected"], f"{dataset}.is_selected")
    source_path = safe_repository_file(raw_path, must_exist=selected)
    expected_sha = str(entry["raw_sha256"]).lower()
    if not HASH_RE.fullmatch(expected_sha):
        raise ValueError(f"invalid source SHA-256 in {dataset} inventory: {raw_path}")
    if str(entry["endpoint"]) != dataset_endpoint:
        raise ValueError(f"source file endpoint mismatch for {dataset}: {raw_path}")
    actual_sha = sha256_file(source_path) if selected else None
    if selected and actual_sha != expected_sha:
        raise ValueError(f"selected raw source hash mismatch: {raw_path}")

    page_no = parse_optional_integer(entry.get("source_page_no"), f"{dataset}.source_page_no")
    row_count = parse_optional_integer(entry.get("row_count"), f"{dataset}.source_files.row_count")
    if row_count is None or row_count < 0:
        raise ValueError(f"source file row_count must be a nonnegative integer: {raw_path}")
    capture_id = entry["capture_id"]
    capture_basis = str(entry["capture_basis"])
    if capture_id in (None, "") or not capture_basis:
        raise ValueError(f"source file capture_id/capture_basis is empty: {raw_path}")
    page_total = parse_optional_integer(entry.get("page_total_count"), f"{dataset}.page_total_count")
    item_count = parse_optional_integer(entry.get("page_item_count", entry.get("item_count")),
                                        f"{dataset}.page_item_count")
    if item_count is not None and item_count != row_count:
        raise ValueError(f"frozen source page item count differs from row_count: {raw_path}")
    if page_total is not None and item_count is not None and page_total < item_count:
        raise ValueError(f"source page total is below page item count: {raw_path}")

    metadata = dict(entry)
    for key in required:
        metadata.pop(key, None)
    metadata.pop("source_page_no", None)
    metadata.pop("row_count", None)
    assert_no_secret_material(metadata, f"{dataset}.source_files[{raw_path}]")

    request_time = entry.get("requested_at_utc", entry.get("requested_at_ms", entry.get("requested_at")))
    retrieve_time = entry.get("retrieved_at_utc", entry.get("retrieved_at_ms", entry.get("retrieved_at")))
    captured_time = entry.get("source_captured_at", entry.get("source_captured_at_utc"))
    return {
        "dataset": dataset,
        "raw_path": raw_path,
        "raw_sha256": expected_sha,
        "source_page_no": page_no,
        "source_row_count": row_count,
        "page_total_count": page_total,
        "page_item_count": item_count,
        "capture_id": str(capture_id),
        "source_captured_at_utc": parse_utc_naive(captured_time, f"{dataset}.source_captured_at"),
        "requested_at_utc": parse_utc_naive(request_time, f"{dataset}.requested_at"),
        "retrieved_at_utc": parse_utc_naive(retrieve_time, f"{dataset}.retrieved_at"),
        "capture_basis": capture_basis,
        "endpoint": str(entry["endpoint"]),
        "is_selected": selected,
        "hash_check_status": "verified_selected_file" if selected else "not_selected_hash_not_rechecked",
        "source_metadata_json": canonical_json(metadata),
    }


def normalize_coverage(dataset: str, entry: dict[str, Any]) -> dict[str, Any]:
    required = ("event_date", "meet", "coverage_status", "selected_capture_id", "selection_rule",
                "coverage_basis", "expected_rows", "observed_rows")
    missing = [name for name in required if name not in entry]
    if missing:
        raise ValueError(f"{dataset} date_coverage item lacks required fields: {missing}")
    event_date = parse_date(entry["event_date"], f"{dataset}.event_date")
    meet = str(entry["meet"])
    status = str(entry["coverage_status"])
    selected_capture = entry["selected_capture_id"]
    selection_rule = str(entry["selection_rule"])
    coverage_basis = str(entry["coverage_basis"])
    expected_rows = parse_optional_integer(entry["expected_rows"], f"{dataset}.expected_rows")
    observed_rows = parse_optional_integer(entry["observed_rows"], f"{dataset}.observed_rows")
    if observed_rows is None or observed_rows < 0 or (expected_rows is not None and expected_rows < 0):
        raise ValueError(f"invalid row counts in {dataset} date_coverage for {event_date}/{meet}")
    if meet not in MEETS or not START_DATE <= event_date <= END_DATE:
        raise ValueError(f"date_coverage row outside requested scope: {dataset} {event_date}/{meet}")
    if status not in {"complete_rows", "complete_zero_rows", "missing_capture", "incomplete_capture"}:
        raise ValueError(f"unknown coverage_status for {dataset} {event_date}/{meet}: {status}")
    if status in {"complete_rows", "complete_zero_rows"}:
        if not selected_capture:
            raise ValueError(f"complete capture lacks selected_capture_id: {dataset} {event_date}/{meet}")
        rule_lower = selection_rule.casefold()
        if "latest" not in rule_lower or "complete" not in rule_lower:
            raise ValueError(f"capture selection rule does not state latest complete: {dataset} {event_date}/{meet}")
        if status == "complete_rows" and observed_rows <= 0:
            raise ValueError(f"complete_rows has no rows: {dataset} {event_date}/{meet}")
        if status == "complete_zero_rows" and observed_rows != 0:
            raise ValueError(f"complete_zero_rows has positive row count: {dataset} {event_date}/{meet}")
    elif selected_capture:
        raise ValueError(f"incomplete/missing coverage cannot be selected as canonical: {dataset} {event_date}/{meet}")
    assert_no_secret_material(entry, f"{dataset}.date_coverage[{event_date}/{meet}]")
    return {
        "dataset": dataset,
        "event_date": event_date,
        "meet": meet,
        "coverage_status": status,
        "selected_capture_id": str(selected_capture) if selected_capture else None,
        "selection_rule": selection_rule,
        "coverage_basis": coverage_basis,
        "expected_rows": expected_rows,
        "observed_rows": observed_rows,
    }


def verify_inputs(input_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Path], dict[str, str]]:
    input_dir = input_dir.resolve(strict=True)
    if not input_dir.is_relative_to(ROOT.resolve(strict=True)):
        raise ValueError("input directory must remain inside this repository")
    inventories: dict[str, Any] = {}
    source_files: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    parquet_paths: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    expected_pairs = expected_calendar_pairs()

    for dataset, config in DATASETS.items():
        parquet_path = input_dir / config["parquet"]
        inventory_path = input_dir / config["inventory"]
        if not parquet_path.is_file() or not inventory_path.is_file():
            raise ValueError(f"missing frozen input for {dataset}: {parquet_path.name} or {inventory_path.name}")
        inventory = load_json(inventory_path)
        assert_no_secret_material(inventory, f"{dataset}.inventory")
        if inventory.get("schema_version") != 1 or inventory.get("dataset") != dataset:
            raise ValueError(f"inventory identity/schema mismatch for {dataset}")
        if inventory.get("endpoint") != config["endpoint"]:
            raise ValueError(f"inventory endpoint mismatch for {dataset}")
        if inventory.get("scope_start") != START_DATE.isoformat() or inventory.get("scope_end") != END_DATE.isoformat():
            raise ValueError(f"inventory scope mismatch for {dataset}")
        expected_parquet_rel = parquet_path.resolve(strict=True).relative_to(ROOT.resolve(strict=True)).as_posix()
        if inventory.get("parquet_path") != expected_parquet_rel:
            raise ValueError(f"inventory points at a different Parquet file for {dataset}")
        parquet_hash = sha256_file(parquet_path)
        if inventory.get("parquet_sha256") != parquet_hash:
            raise ValueError(f"Parquet SHA-256 mismatch for {dataset}")
        expected_rows = parse_optional_integer(inventory.get("row_count"), f"{dataset}.row_count")
        if expected_rows is None or expected_rows < 0:
            raise ValueError(f"invalid Parquet row_count in {dataset} inventory")

        raw_files = inventory.get("source_files")
        raw_coverage = inventory.get("date_coverage")
        if not isinstance(raw_files, list) or not isinstance(raw_coverage, list):
            raise ValueError(f"inventory requires source_files and date_coverage arrays: {dataset}")
        normalized_files = [normalize_inventory_file(dataset, item, config["endpoint"])
                            for item in raw_files if isinstance(item, dict)]
        if len(normalized_files) != len(raw_files):
            raise ValueError(f"source_files contains a non-object entry: {dataset}")
        file_keys = [(r["raw_path"], r["source_page_no"], r["capture_id"]) for r in normalized_files]
        if len(file_keys) != len(set(file_keys)):
            raise ValueError(f"duplicate source file inventory key for {dataset}")
        if not any(r["is_selected"] for r in normalized_files) and expected_rows:
            raise ValueError(f"positive observation export has no selected raw source files: {dataset}")

        normalized_coverage = [normalize_coverage(dataset, item)
                               for item in raw_coverage if isinstance(item, dict)]
        if len(normalized_coverage) != len(raw_coverage):
            raise ValueError(f"date_coverage contains a non-object entry: {dataset}")
        coverage_pairs = [(r["event_date"], r["meet"]) for r in normalized_coverage]
        if len(coverage_pairs) != len(set(coverage_pairs)) or set(coverage_pairs) != expected_pairs:
            raise ValueError(f"date_coverage does not exactly cover every requested date×meet: {dataset}")
        not_complete = [r for r in normalized_coverage if r["coverage_status"] not in {"complete_rows", "complete_zero_rows"}]
        if not_complete:
            example = not_complete[0]
            raise ValueError(f"scope has a missing/incomplete capture for {dataset}: {example['event_date']}/{example['meet']} ({example['coverage_status']})")

        inventories[dataset] = {
            **inventory,
            "inventory_path": inventory_path.resolve().relative_to(ROOT.resolve()).as_posix(),
            "inventory_sha256": sha256_file(inventory_path),
            "parquet_path_absolute": str(parquet_path.resolve()),
            "parquet_path": expected_parquet_rel,
            "parquet_sha256": parquet_hash,
            "row_count": expected_rows,
            "source_files_normalized": normalized_files,
            "date_coverage_normalized": normalized_coverage,
        }
        source_files.extend(normalized_files)
        coverage_rows.extend(normalized_coverage)
        parquet_paths[dataset] = parquet_path.resolve()
        hashes[expected_parquet_rel] = parquet_hash
        hashes[inventories[dataset]["inventory_path"]] = inventories[dataset]["inventory_sha256"]

        # Explicit DuckDB types guard against all-null first batches and schema drift.
        con = duckdb.connect(":memory:")
        try:
            desc = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(parquet_path)]).fetchall()
            schema = [(row[0], str(row[1]).upper()) for row in desc]
            expected_types = {
                "dataset": "VARCHAR", "observation_id": "VARCHAR", "event_date": "DATE",
                "meet": "VARCHAR", "official_horse_id": "VARCHAR", "raw_name": "VARCHAR",
                "raw_path": "VARCHAR", "raw_sha256": "VARCHAR", "source_page_no": "INTEGER",
                "source_row_no": "INTEGER", "source_captured_at": "TIMESTAMP", "capture_basis": "VARCHAR",
                "endpoint": "VARCHAR", "raw_payload_json": "VARCHAR", "typed_fields_json": "VARCHAR",
                "link_status": "VARCHAR", "linked_core_horse_id": "VARCHAR", "qa_flags_json": "VARCHAR",
                "capture_id": "VARCHAR",
            }
            if [name for name, _ in schema] != PARQUET_COLUMNS:
                raise ValueError(f"explicit Parquet column order/names differ for {dataset}: {[n for n, _ in schema]}")
            for name, actual_type in schema:
                if actual_type != expected_types[name]:
                    raise ValueError(f"Parquet field {dataset}.{name} has type {actual_type}, expected {expected_types[name]}")
            actual_count = con.execute("SELECT count(*) FROM read_parquet(?)", [str(parquet_path)]).fetchone()[0]
        finally:
            con.close()
        if actual_count != expected_rows:
            raise ValueError(f"Parquet row count mismatch for {dataset}: inventory={expected_rows}, file={actual_count}")

    # Return each input inventory once; report itself stores only hashes and summaries.
    return inventories, source_files, coverage_rows, parquet_paths, hashes


def source_manifest_value(inventories: dict[str, Any], hashes: dict[str, str],
                          counts: dict[str, Any], app_code_hashes: dict[str, str]) -> dict[str, Any]:
    return {
        "source": "API18_1/API22_1/API216",
        "dataset_endpoints": {dataset: config["endpoint"] for dataset, config in DATASETS.items()},
        "scope": "2010-01-01..2026-09-29 inclusive; meets 1 and 3; no Jeju",
        "capture_selection": "latest hash-verified complete capture per event-date × meet, regardless of year/month/day partition",
        "availability_status": AVAILABILITY_STATUS,
        "historical_prerace_eligibility_verified": False,
        "historical_14_00_publication_time_inferred": False,
        "physical_venue_status": PHYSICAL_VENUE_STATUS,
        "venue_note": "meet 3 raw Yeongnam source labels are preserved; actual venue split is unresolved",
        "identity_rule": "exact official horse ID string match to core entity_reference_roster entity_type=horse; unmatched IDs remain raw; no names used for linking",
        "observation_rule": "preserve each source occurrence, including same-key conflicts and exact repeats; no deduplication or raw-value correction",
        "start_training_rule": "API22 occurrence ordinal is a storage order only, not an event ID or chronological order",
        "swim_training_rule": "API216 cnt and horsepart/trpart are source raw values; unit and field equivalence remain unresolved",
        "verified_input_sha256": hashes,
        "loader_and_schema_sha256": app_code_hashes,
        "dataset_counts": counts,
        "appended_objects": list(CORE_OBJECT_TYPES),
        "input_inventory_paths": {dataset: inventories[dataset]["inventory_path"] for dataset in DATASETS},
        "coverage_summary": {
            dataset: {
                "coverage_rows": len(inventories[dataset]["date_coverage_normalized"]),
                "complete_rows": sum(r["coverage_status"] == "complete_rows" for r in inventories[dataset]["date_coverage_normalized"]),
                "complete_zero_rows": sum(r["coverage_status"] == "complete_zero_rows" for r in inventories[dataset]["date_coverage_normalized"]),
                "missing_or_incomplete_rows": 0,
            }
            for dataset in DATASETS
        },
    }


def configure_duckdb(connection: duckdb.DuckDBPyConnection, temp_dir: Path) -> None:
    connection.execute("SET memory_limit='2GB'")
    connection.execute(f"SET temp_directory={sql_literal(str(temp_dir))}")


def parquet_sql_path(path: Path) -> str:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(ROOT.resolve(strict=True)):
        raise ValueError(f"Parquet input is outside repository: {path}")
    return sql_literal(str(resolved))


def arrow_schemas() -> tuple[Any, Any]:
    import pyarrow as pa

    coverage = pa.schema([
        ("dataset", pa.string()), ("event_date", pa.date32()), ("meet", pa.string()),
        ("coverage_status", pa.string()), ("selected_capture_id", pa.string()),
        ("selection_rule", pa.string()), ("coverage_basis", pa.string()),
        ("expected_rows", pa.int64()), ("observed_rows", pa.int64()),
    ])
    files = pa.schema([
        ("dataset", pa.string()), ("raw_path", pa.string()), ("raw_sha256", pa.string()),
        ("source_page_no", pa.int32()), ("source_row_count", pa.int64()),
        ("page_total_count", pa.int64()), ("page_item_count", pa.int64()),
        ("capture_id", pa.string()), ("source_captured_at_utc", pa.timestamp("us")),
        ("requested_at_utc", pa.timestamp("us")), ("retrieved_at_utc", pa.timestamp("us")),
        ("capture_basis", pa.string()), ("endpoint", pa.string()), ("is_selected", pa.bool_()),
        ("hash_check_status", pa.string()), ("source_metadata_json", pa.string()),
    ])
    return coverage, files


def load_staging_rows(connection: duckdb.DuckDBPyConnection, coverage_rows: list[dict[str, Any]],
                      source_files: list[dict[str, Any]]) -> None:
    coverage_schema, files_schema = arrow_schemas()
    arrow_insert(connection, "training_capture_coverage", [
        "dataset", "event_date", "meet", "coverage_status", "selected_capture_id",
        "selection_rule", "coverage_basis", "expected_rows", "observed_rows",
    ], coverage_rows, coverage_schema)
    arrow_insert(connection, "training_source_files", [
        "dataset", "raw_path", "raw_sha256", "source_page_no", "source_row_count",
        "page_total_count", "page_item_count", "capture_id", "source_captured_at_utc",
        "requested_at_utc", "retrieved_at_utc", "capture_basis", "endpoint", "is_selected",
        "hash_check_status", "source_metadata_json",
    ], source_files, files_schema)


def apply_schema(connection: duckdb.DuckDBPyConnection, *, dry_run: bool) -> None:
    schema_sql = (OUT / "schema.sql").read_text(encoding="utf-8")
    for statement in (part.strip() for part in schema_sql.split(";") if part.strip()):
        executable = re.sub(r"(?m)^\s*--.*$", "", statement).strip()
        if dry_run and executable.upper().startswith("CREATE TABLE TRAINING_RAW_OBSERVATIONS"):
            continue
        if dry_run:
            executable = re.sub(r"^CREATE TABLE\b", "CREATE TEMP TABLE", executable, count=1, flags=re.IGNORECASE)
            executable = re.sub(r"^CREATE VIEW\b", "CREATE TEMP VIEW", executable, count=1, flags=re.IGNORECASE)
            statement = executable
        connection.execute(statement)


def prepare_dry_run_connection(inventories: dict[str, Any], source_files: list[dict[str, Any]],
                               coverage_rows: list[dict[str, Any]], parquet_paths: dict[str, Path],
                               temp_dir: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    configure_duckdb(connection, temp_dir)
    core_path = CORE_DB.resolve(strict=True)
    connection.execute(f"ATTACH DATABASE {sql_literal(str(core_path))} AS core_db (READ_ONLY)")
    connection.execute("CREATE TEMP VIEW entity_reference_roster AS SELECT * FROM core_db.entity_reference_roster")
    # The input files have the same explicitly checked schema; DuckDB reads them
    # in bounded batches and does not build a multi-million-row Python list.
    parquet_list = ", ".join(parquet_sql_path(parquet_paths[name]) for name in DATASETS)
    connection.execute(f"""
        CREATE TEMP TABLE training_raw_observations AS
        SELECT
            p.*,
            '{AVAILABILITY_STATUS}'::VARCHAR AS availability_status,
            FALSE::BOOLEAN AS historical_prerace_eligibility_verified,
            '{PHYSICAL_VENUE_STATUS}'::VARCHAR AS physical_venue_status
        FROM read_parquet([{parquet_list}], union_by_name=false) AS p
    """)
    # Create all permanent-shape helper tables/views in memory. The raw rows
    # stay as a Parquet-backed view until an explicit root apply.
    apply_schema(connection, dry_run=True)
    load_staging_rows(connection, coverage_rows, source_files)
    return connection


def query_dataset_counts(connection: duckdb.DuckDBPyConnection) -> dict[str, int]:
    return {
        dataset: int(connection.execute(
            "SELECT count(*) FROM training_raw_observations WHERE dataset=?", [dataset]
        ).fetchone()[0])
        for dataset in DATASETS
    }


def validate_staged_data(connection: duckdb.DuckDBPyConnection,
                         inventories: dict[str, Any],
                         source_files: list[dict[str, Any]]) -> dict[str, Any]:
    counts = query_dataset_counts(connection)
    total_rows = sum(counts.values())
    distinct_ids = int(connection.execute("SELECT count(DISTINCT observation_id) FROM training_raw_observations").fetchone()[0])
    if total_rows != distinct_ids:
        raise ValueError(f"observation_id must be unique without collapsing repeats: rows={total_rows}, unique_ids={distinct_ids}")
    for dataset, inventory in inventories.items():
        if counts[dataset] != inventory["row_count"]:
            raise ValueError(f"dataset row count changed after Parquet scan: {dataset}")
    bad_scope = int(connection.execute("""
        SELECT count(*) FROM training_raw_observations
        WHERE dataset NOT IN ('daily_training','start_training','swim_training')
           OR meet NOT IN ('1','3')
           OR event_date < DATE '2010-01-01' OR event_date > DATE '2026-09-29'
    """).fetchone()[0])
    if bad_scope:
        raise ValueError(f"{bad_scope} raw observations fall outside scope")
    bad_endpoint = int(connection.execute("""
        SELECT count(*) FROM training_raw_observations
        WHERE (dataset='daily_training' AND endpoint<>'API18_1')
           OR (dataset='start_training' AND endpoint<>'API22_1')
           OR (dataset='swim_training' AND endpoint<>'API216')
    """).fetchone()[0])
    if bad_endpoint:
        raise ValueError(f"{bad_endpoint} raw observations have an endpoint/dataset mismatch")
    nulls = int(connection.execute("""
        SELECT count(*) FROM training_raw_observations
        WHERE observation_id IS NULL OR observation_id='' OR dataset IS NULL OR event_date IS NULL
           OR meet IS NULL OR raw_path IS NULL OR raw_path='' OR raw_sha256 IS NULL
           OR raw_sha256='' OR endpoint IS NULL OR endpoint='' OR capture_basis IS NULL OR capture_basis=''
           OR raw_payload_json IS NULL OR typed_fields_json IS NULL OR qa_flags_json IS NULL
           OR capture_id IS NULL OR capture_id='' OR link_status IS NULL OR link_status=''
    """).fetchone()[0])
    if nulls:
        raise ValueError(f"{nulls} raw observations lack required source/provenance fields")
    invalid_link_statuses = int(connection.execute("""
        SELECT count(*) FROM training_raw_observations
        WHERE link_status NOT IN ('exact_core_roster_match','unmatched_official_id','missing_official_id')
    """).fetchone()[0])
    if invalid_link_statuses:
        raise ValueError(f"{invalid_link_statuses} observations have unrecognized core horse link statuses")
    bad_json = int(connection.execute("""
        SELECT count(*) FROM training_raw_observations
        WHERE NOT json_valid(raw_payload_json) OR NOT json_valid(typed_fields_json) OR NOT json_valid(qa_flags_json)
    """).fetchone()[0])
    if bad_json:
        raise ValueError(f"{bad_json} raw observation rows contain invalid JSON fields")

    nonselected_sources = int(connection.execute("""
        SELECT count(*) FROM training_raw_observations AS o
        LEFT JOIN training_source_files AS f
          ON f.dataset=o.dataset AND f.raw_path=o.raw_path AND f.raw_sha256=o.raw_sha256
         AND f.capture_id=o.capture_id AND f.is_selected
         AND f.source_page_no IS NOT DISTINCT FROM o.source_page_no
        WHERE f.raw_path IS NULL
    """).fetchone()[0])
    if nonselected_sources:
        raise ValueError(f"{nonselected_sources} observations are not tied to a hash-verified selected source file")

    bad_source_position = int(connection.execute("""
        SELECT count(*)
        FROM training_raw_observations AS o
        JOIN training_source_files AS f
          ON f.dataset=o.dataset AND f.raw_path=o.raw_path AND f.raw_sha256=o.raw_sha256
         AND f.capture_id=o.capture_id AND f.is_selected
         AND f.source_page_no IS NOT DISTINCT FROM o.source_page_no
        WHERE o.source_page_no IS NULL OR o.source_page_no < 1
           OR o.source_row_no IS NULL OR o.source_row_no < 1
           OR o.source_row_no > f.source_row_count
    """).fetchone()[0])
    if bad_source_position:
        raise ValueError(f"{bad_source_position} observations have invalid source page/row positions")

    coverage_mismatch = int(connection.execute("""
        SELECT count(*) FROM training_date_coverage
        WHERE inventory_count_mismatch
           OR (expected_rows IS NOT NULL AND expected_rows <> inventory_observed_rows)
           OR coverage_status NOT IN ('complete_rows','complete_zero_rows')
    """).fetchone()[0])
    if coverage_mismatch:
        sample = connection.execute("""
            SELECT dataset,event_date,meet,coverage_status,expected_rows,inventory_observed_rows,actual_observation_rows
            FROM training_date_coverage
            WHERE inventory_count_mismatch
               OR (expected_rows IS NOT NULL AND expected_rows <> inventory_observed_rows)
               OR coverage_status NOT IN ('complete_rows','complete_zero_rows')
            LIMIT 5
        """).fetchall()
        raise ValueError(f"date×meet completeness/count gate failed ({coverage_mismatch} rows): {sample}")

    missing_capture_inventory = int(connection.execute("""
        SELECT count(*)
        FROM training_capture_coverage AS c
        LEFT JOIN training_source_files AS f
          ON f.dataset=c.dataset AND f.capture_id=c.selected_capture_id AND f.is_selected
        WHERE c.coverage_status IN ('complete_rows','complete_zero_rows')
          AND f.capture_id IS NULL
    """).fetchone()[0])
    if missing_capture_inventory:
        sample = connection.execute("""
            SELECT c.dataset,c.event_date,c.meet,c.selected_capture_id
            FROM training_capture_coverage AS c
            LEFT JOIN training_source_files AS f
              ON f.dataset=c.dataset AND f.capture_id=c.selected_capture_id AND f.is_selected
            WHERE c.coverage_status IN ('complete_rows','complete_zero_rows')
              AND f.capture_id IS NULL
            LIMIT 5
        """).fetchall()
        raise ValueError(f"{missing_capture_inventory} complete date×meet cells reference no selected source file: {sample}")

    bad_selected_capture = int(connection.execute("""
        SELECT count(*) FROM training_raw_observations AS o
        JOIN training_capture_coverage AS c USING (dataset,event_date,meet)
        WHERE c.coverage_status <> 'complete_rows'
           OR c.selected_capture_id IS DISTINCT FROM o.capture_id
    """).fetchone()[0])
    if bad_selected_capture:
        raise ValueError(f"{bad_selected_capture} observations do not use the selected latest complete date×meet capture")

    bad_link = int(connection.execute("""
        SELECT count(*)
        FROM training_raw_observations AS o
        LEFT JOIN entity_reference_roster AS h
          ON h.entity_type='horse' AND h.entity_id_official_string=o.official_horse_id
        WHERE (o.official_horse_id IS NULL OR o.official_horse_id='')
              AND (o.link_status <> 'missing_official_id' OR o.linked_core_horse_id IS NOT NULL)
           OR o.official_horse_id IS NOT NULL AND o.official_horse_id<>'' AND h.entity_id_official_string IS NOT NULL
              AND (o.link_status <> 'exact_core_roster_match' OR o.linked_core_horse_id IS DISTINCT FROM o.official_horse_id)
           OR o.official_horse_id IS NOT NULL AND o.official_horse_id<>'' AND h.entity_id_official_string IS NULL
              AND (o.link_status <> 'unmatched_official_id' OR o.linked_core_horse_id IS NOT NULL)
    """).fetchone()[0])
    if bad_link:
        raise ValueError(f"{bad_link} exact official-ID roster linkage statuses are invalid")
    duplicate_roster_ids = int(connection.execute("""
        SELECT count(*) FROM (
            SELECT entity_id_official_string FROM entity_reference_roster
            WHERE entity_type='horse' GROUP BY entity_id_official_string HAVING count(*) > 1
        )
    """).fetchone()[0])
    if duplicate_roster_ids:
        raise ValueError(f"core horse roster has {duplicate_roster_ids} duplicated exact official IDs")

    qa_json = bad_json
    source_row_totals = {
        dataset: int(connection.execute("SELECT count(*) FROM training_source_files WHERE dataset=?", [dataset]).fetchone()[0])
        for dataset in DATASETS
    }
    coverage_totals = {
        dataset: {
            "complete_rows": int(connection.execute("SELECT count(*) FROM training_capture_coverage WHERE dataset=? AND coverage_status='complete_rows'", [dataset]).fetchone()[0]),
            "complete_zero_rows": int(connection.execute("SELECT count(*) FROM training_capture_coverage WHERE dataset=? AND coverage_status='complete_zero_rows'", [dataset]).fetchone()[0]),
            "missing_or_incomplete": int(connection.execute("SELECT count(*) FROM training_capture_coverage WHERE dataset=? AND coverage_status NOT IN ('complete_rows','complete_zero_rows')", [dataset]).fetchone()[0]),
        } for dataset in DATASETS
    }
    view_counts = {
        "daily_training_raw": counts["daily_training"],
        "start_training_raw": counts["start_training"],
        "swim_training_raw": counts["swim_training"],
        "training_observation_qa": total_rows,
        "training_date_coverage": int(connection.execute("SELECT count(*) FROM training_date_coverage").fetchone()[0]),
        "training_source_entities": int(connection.execute("SELECT count(*) FROM training_source_entities").fetchone()[0]),
    }
    return {
        "dataset_observation_rows": counts,
        "total_observation_rows": total_rows,
        "unique_observation_ids": distinct_ids,
        "source_file_inventory_rows": source_row_totals,
        "date_coverage": coverage_totals,
        "date_coverage_rows": sum(sum(group.values()) for group in coverage_totals.values()),
        "exact_roster_link_rows": int(connection.execute("SELECT count(*) FROM training_raw_observations WHERE link_status='exact_core_roster_match'").fetchone()[0]),
        "unmatched_official_id_rows": int(connection.execute("SELECT count(*) FROM training_raw_observations WHERE link_status='unmatched_official_id'").fetchone()[0]),
        "missing_official_id_rows": int(connection.execute("SELECT count(*) FROM training_raw_observations WHERE link_status='missing_official_id'").fetchone()[0]),
        "invalid_json_rows": qa_json,
        "dataset_view_rows": view_counts,
    }


def validate_input_capture_linkage(connection: duckdb.DuckDBPyConnection) -> None:
    # Selected page references and hashes must agree with the file inventory.
    selected_page_rows = int(connection.execute("""
        SELECT count(*) FROM training_source_files WHERE is_selected
    """).fetchone()[0])
    if selected_page_rows == 0:
        raise ValueError("no source-file entries are marked selected")
    bad_dataset = int(connection.execute("""
        SELECT count(*) FROM training_source_files
        WHERE (dataset='daily_training' AND endpoint<>'API18_1')
           OR (dataset='start_training' AND endpoint<>'API22_1')
           OR (dataset='swim_training' AND endpoint<>'API216')
    """).fetchone()[0])
    if bad_dataset:
        raise ValueError(f"{bad_dataset} source file entries have endpoint/dataset mismatch")


def compare_small_table(connection: duckdb.DuckDBPyConnection, table: str,
                        columns: list[str]) -> int:
    column_sql = ", ".join(f'"{column}"' for column in columns)
    return int(connection.execute(f"""
        SELECT count(*) FROM (
            (SELECT {column_sql} FROM core_db.{table}
             EXCEPT ALL SELECT {column_sql} FROM {table})
            UNION ALL
            (SELECT {column_sql} FROM {table}
             EXCEPT ALL SELECT {column_sql} FROM core_db.{table})
        )
    """).fetchone()[0])


def verify_replay(connection: duckdb.DuckDBPyConnection, expected_source_json: str,
                  source_manifest_rows: int, metrics: dict[str, Any]) -> dict[str, Any]:
    if source_manifest_rows != 23:
        raise ValueError(f"post-append core has {source_manifest_rows} source manifest rows, expected 23")
    stored = connection.execute("SELECT json_text FROM core_db.source_manifests WHERE name=?", [SOURCE_MANIFEST_NAME]).fetchall()
    if len(stored) != 1 or stored[0][0] != expected_source_json:
        raise ValueError("existing training source manifest differs from these pinned inputs/code")

    incoming_count = metrics["total_observation_rows"]
    actual_count = int(connection.execute("SELECT count(*) FROM core_db.training_raw_observations").fetchone()[0])
    if actual_count != incoming_count:
        raise ValueError(f"replay observation count differs: core={actual_count}, inputs={incoming_count}")
    observation_id_delta = int(connection.execute("""
        SELECT count(*) FROM (
            SELECT observation_id FROM core_db.training_raw_observations
            ANTI JOIN training_raw_observations USING (observation_id)
            UNION ALL
            SELECT observation_id FROM training_raw_observations
            ANTI JOIN core_db.training_raw_observations USING (observation_id)
        )
    """).fetchone()[0])
    if observation_id_delta:
        raise ValueError(f"replay observation IDs differ by {observation_id_delta} rows")
    comparison_columns = ", ".join(f'"{column}"' for column in RAW_TABLE_COLUMNS)
    mismatch = int(connection.execute(f"""
        SELECT count(*)
        FROM core_db.training_raw_observations AS stored
        JOIN training_raw_observations AS incoming USING (observation_id)
        WHERE (stored.{RAW_TABLE_COLUMNS[0]}, {', '.join('stored."' + c + '"' for c in RAW_TABLE_COLUMNS[1:])})
              IS DISTINCT FROM
              (incoming.{RAW_TABLE_COLUMNS[0]}, {', '.join('incoming."' + c + '"' for c in RAW_TABLE_COLUMNS[1:])})
    """).fetchone()[0])
    if mismatch:
        raise ValueError(f"replay raw observation contents differ for {mismatch} observation IDs")

    coverage_columns = ["dataset", "event_date", "meet", "coverage_status", "selected_capture_id", "selection_rule", "coverage_basis", "expected_rows", "observed_rows"]
    file_columns = ["dataset", "raw_path", "raw_sha256", "source_page_no", "source_row_count", "page_total_count", "page_item_count", "capture_id", "source_captured_at_utc", "requested_at_utc", "retrieved_at_utc", "capture_basis", "endpoint", "is_selected", "hash_check_status", "source_metadata_json"]
    for table, columns in (("training_capture_coverage", coverage_columns), ("training_source_files", file_columns)):
        delta = compare_small_table(connection, table, columns)
        if delta:
            raise ValueError(f"replay rows differ for {table}: {delta} symmetric-difference rows")
    for view, expected_rows in metrics["dataset_view_rows"].items():
        actual_rows = int(connection.execute(f"SELECT count(*) FROM core_db.{view}").fetchone()[0])
        if actual_rows != expected_rows:
            raise ValueError(f"replay view row count changed for {view}: {actual_rows} != {expected_rows}")
    return {"training_raw_observations": actual_count, "observation_id_delta": observation_id_delta,
            "raw_content_mismatches": mismatch, "coverage_and_source_metadata_mismatches": 0}


def inspect_core_state() -> tuple[str, dict[str, str], int, dict[str, Any], bool]:
    db_hash = sha256_file(CORE_DB)
    manifest = load_json(CORE_MANIFEST)
    if manifest.get("database_sha256") != db_hash:
        raise ValueError("core manifest database_sha256 does not match the current DuckDB file")
    connection = duckdb.connect(str(CORE_DB), read_only=True)
    try:
        objects = catalog_objects(connection)
        source_count = int(connection.execute("SELECT count(*) FROM source_manifests").fetchone()[0])
        source_row_count = int(connection.execute("SELECT count(*) FROM source_manifests WHERE name=?", [SOURCE_MANIFEST_NAME]).fetchone()[0])
    finally:
        connection.close()
    present = {name: objects[name] for name in CORE_OBJECT_TYPES if name in objects}
    if not present and source_row_count == 0:
        if db_hash != BASE_DB_SHA256 or source_count != 22 or len(objects) != 92:
            raise ValueError("core is not the pinned 92-object/22-source baseline")
        is_replay = False
    elif present == CORE_OBJECT_TYPES and source_row_count == 1 and source_count >= 23:
        is_replay = True
    else:
        raise ValueError(f"partial/conflicting training append detected: objects={present}, source_rows={source_row_count}, total_sources={source_count}")
    return db_hash, objects, source_count, manifest, is_replay


def dry_run(inventories: dict[str, Any], source_files: list[dict[str, Any]],
            coverage_rows: list[dict[str, Any]], parquet_paths: dict[str, Path],
            hashes: dict[str, str], *, is_replay: bool, current_db_hash: str,
            source_count: int, core_manifest: dict[str, Any]) -> dict[str, Any]:
    app_hashes = {
        "loader": sha256_file(OUT / "load_training_three.py"),
        "schema": sha256_file(OUT / "schema.sql"),
        "contract": sha256_file(OUT / "input_contract.json"),
    }
    with tempfile.TemporaryDirectory(prefix="training-three-duckdb-") as scratch:
        memory = duckdb.connect(":memory:")
        try:
            configure_duckdb(memory, Path(scratch))
            core_path_sql = sql_literal(str(CORE_DB.resolve(strict=True)))
            memory.execute(f"ATTACH DATABASE {core_path_sql} AS core_db (READ_ONLY)")
            memory.execute("CREATE TEMP VIEW entity_reference_roster AS SELECT * FROM core_db.entity_reference_roster")
            parquet_list = ", ".join(parquet_sql_path(parquet_paths[name]) for name in DATASETS)
            memory.execute(f"""
                CREATE TEMP VIEW training_raw_observations AS
                SELECT p.*,
                    '{AVAILABILITY_STATUS}'::VARCHAR AS availability_status,
                    FALSE::BOOLEAN AS historical_prerace_eligibility_verified,
                    '{PHYSICAL_VENUE_STATUS}'::VARCHAR AS physical_venue_status
                FROM read_parquet([{parquet_list}], union_by_name=false) AS p
            """)
            apply_schema(memory, dry_run=True)
            load_staging_rows(memory, coverage_rows, source_files)
            validate_input_capture_linkage(memory)
            metrics = validate_staged_data(memory, inventories, source_files)
            expected_source = source_manifest_value(inventories, hashes, metrics, app_hashes)
            expected_source_json = json.dumps(expected_source, ensure_ascii=False, sort_keys=True)
            replay_check = verify_replay(memory, expected_source_json, source_count, metrics) if is_replay else None
        finally:
            memory.close()
    row_counts = {
        "training_raw_observations": metrics["total_observation_rows"],
        "training_capture_coverage": metrics["date_coverage_rows"],
        "training_source_files": sum(metrics["source_file_inventory_rows"].values()),
        **metrics["dataset_view_rows"],
    }
    base_objects = 92 if not is_replay else len(inspect_core_state()[1]) - len(CORE_OBJECT_TYPES)
    return {
        "status": "dry_run_replay_passed" if is_replay else "dry_run_passed",
        "applied": False,
        "idempotent_replay": is_replay,
        "core_database": CORE_DB.relative_to(ROOT).as_posix(),
        "core_database_sha256_before": current_db_hash,
        "baseline_database_sha256": BASE_DB_SHA256,
        "existing_core_objects": base_objects,
        "existing_source_manifest_rows": source_count,
        "input_hashes": hashes,
        "loader_and_schema_sha256": app_hashes,
        "proposed_objects": [
            {"name": name, "type": kind, "rows": row_counts[name]}
            for name, kind in CORE_OBJECT_TYPES.items()
        ],
        "proposed_source_manifest": SOURCE_MANIFEST_NAME,
        "dataset_counts": metrics,
        "replay_verification": replay_check,
        "backup_plan": str(BACKUP_DIR.relative_to(ROOT)),
        "preservation_plan": {"existing_objects": 92, "expected_new_objects": 9, "expected_total_objects_after_apply": 101,
                               "existing_source_manifest_rows": 22, "expected_source_manifest_rows_after_apply": 23},
        "status_rules": {
            "availability_status": AVAILABILITY_STATUS,
            "historical_prerace_eligibility_verified": False,
            "historical_14_00_publication_time_inferred": False,
            "physical_venue_status": PHYSICAL_VENUE_STATUS,
            "api22_occurrence_is_event_id": False,
            "api22_occurrence_is_chronological": False,
            "api216_count_unit": "unresolved; source cnt retained as raw JSON/string",
        },
        "notes": [
            "Default mode is read-only against the core DuckDB and manifest.",
            "Observations are scanned from pinned Parquet without building a multi-million-row Python list.",
            "Raw observations preserve exact repeats and nonidentical natural-key rows; nothing is deduplicated or corrected.",
            "Core horse linkage is exact official-ID string matching only; unmatched IDs remain present.",
        ],
    }


def table_insert_from_parquet(connection: duckdb.DuckDBPyConnection,
                              parquet_paths: dict[str, Path]) -> None:
    for dataset, path in parquet_paths.items():
        source = parquet_sql_path(path)
        # The dataset field is pinned/validated from the producer file. Append
        # the retrospective and unresolved-venue statuses explicitly.
        connection.execute(f"""
            INSERT INTO training_raw_observations ({', '.join('"'+c+'"' for c in RAW_TABLE_COLUMNS)})
            SELECT {', '.join('p."'+c+'"' for c in PARQUET_COLUMNS)},
                   '{AVAILABILITY_STATUS}', FALSE, '{PHYSICAL_VENUE_STATUS}'
            FROM read_parquet({source}) AS p
            WHERE p.dataset = {sql_literal(dataset)}
        """)


def append_core(inventories: dict[str, Any], source_files: list[dict[str, Any]],
                coverage_rows: list[dict[str, Any]], parquet_paths: dict[str, Path],
                hashes: dict[str, str], expected_source: dict[str, Any],
                expected_metrics: dict[str, Any]) -> dict[str, Any]:
    manifest_before_bytes = CORE_MANIFEST.read_bytes()
    current_hash = sha256_file(CORE_DB)
    manifest_before = json.loads(manifest_before_bytes)
    if current_hash != BASE_DB_SHA256 or manifest_before.get("database_sha256") != BASE_DB_SHA256:
        raise ValueError("core changed after dry-run baseline; refusing append")
    if BACKUP_DIR.exists():
        raise ValueError(f"paired backup directory already exists; refusing to overwrite: {BACKUP_DIR}")
    BACKUP_DIR.mkdir(parents=True)
    backup_db = BACKUP_DIR / CORE_DB.name
    backup_manifest = BACKUP_DIR / CORE_MANIFEST.name
    shutil.copy2(CORE_DB, backup_db)
    shutil.copy2(CORE_MANIFEST, backup_manifest)
    if sha256_file(backup_db) != BASE_DB_SHA256 or sha256_file(backup_manifest) != hashlib.sha256(manifest_before_bytes).hexdigest():
        raise ValueError("paired pre-append backup hash verification failed")

    scratch_context = tempfile.TemporaryDirectory(prefix="training-three-apply-")
    connection = duckdb.connect(str(CORE_DB), read_only=False)
    committed = False
    try:
        configure_duckdb(connection, Path(scratch_context.name))
        before_objects = catalog_objects(connection)
        before_source_count = int(connection.execute("SELECT count(*) FROM source_manifests").fetchone()[0])
        existing = {name: before_objects[name] for name in CORE_OBJECT_TYPES if name in before_objects}
        if existing or before_source_count != 22 or len(before_objects) != 92:
            raise ValueError(f"core append precondition changed: existing={existing}, sources={before_source_count}, objects={len(before_objects)}")
        connection.execute("BEGIN TRANSACTION")
        apply_schema(connection, dry_run=False)
        load_staging_rows(connection, coverage_rows, source_files)
        table_insert_from_parquet(connection, parquet_paths)
        # The same full checks run against physical core tables before commit.
        metrics = validate_staged_data(connection, inventories, source_files)
        if metrics != expected_metrics:
            raise ValueError("pre-commit metrics differ from the reviewed dry-run report")
        source_text = json.dumps(expected_source, ensure_ascii=False, sort_keys=True)
        connection.execute("INSERT INTO source_manifests(name,json_text) VALUES (?,?)",
                           [SOURCE_MANIFEST_NAME, source_text])
        after_objects = catalog_objects(connection)
        expected_after = dict(before_objects)
        expected_after.update(CORE_OBJECT_TYPES)
        if after_objects != expected_after:
            raise ValueError("core catalog changed beyond the nine declared training objects")
        if int(connection.execute("SELECT count(*) FROM source_manifests").fetchone()[0]) != 23:
            raise ValueError("source manifest append count is not 23 before commit")
        connection.execute("COMMIT")
        committed = True
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except Exception:
            pass
        connection.close()
        scratch_context.cleanup()
        raise
    connection.close()
    scratch_context.cleanup()

    try:
        after_hash = sha256_file(CORE_DB)
        updated = json.loads(json.dumps(manifest_before))
        updated["database_sha256"] = after_hash
        input_files = updated.setdefault("input_files", [])
        known_paths = {row.get("path") for row in input_files if isinstance(row, dict)}
        for dataset, inventory in inventories.items():
            for path, digest, table, row_count in (
                (inventory["parquet_path"], inventory["parquet_sha256"], "training_raw_observations", inventory["row_count"]),
                (inventory["inventory_path"], inventory["inventory_sha256"], "training_source_files/training_capture_coverage", None),
            ):
                if path not in known_paths:
                    input_files.append({"table": table, "path": path, "sha256": digest, "rows": row_count})
                    known_paths.add(path)
        for rel_path, digest, table_name in (
            ("thoroughbred/research/20261002_training_three_v1/loader/load_training_three.py", sha256_file(OUT / "load_training_three.py"), "training_loader_code"),
            ("thoroughbred/research/20261002_training_three_v1/loader/schema.sql", sha256_file(OUT / "schema.sql"), "training_loader_schema"),
            ("thoroughbred/research/20261002_training_three_v1/loader/input_contract.json", sha256_file(OUT / "input_contract.json"), "training_loader_contract"),
        ):
            if rel_path not in known_paths:
                input_files.append({"table": table_name, "path": rel_path, "sha256": digest, "rows": None})
                known_paths.add(rel_path)
        counts_map = updated.setdefault("table_and_view_counts", {})
        counts_map.update({name: expected_metrics["dataset_observation_rows"][dataset]
                           for dataset, name in (("daily_training", "daily_training_raw"),
                                                 ("start_training", "start_training_raw"),
                                                 ("swim_training", "swim_training_raw"))})
        counts_map.update({
            "training_raw_observations": expected_metrics["total_observation_rows"],
            "training_capture_coverage": expected_metrics["date_coverage_rows"],
            "training_source_files": sum(expected_metrics["source_file_inventory_rows"].values()),
            "training_observation_qa": expected_metrics["total_observation_rows"],
            "training_date_coverage": expected_metrics["dataset_view_rows"]["training_date_coverage"],
            "training_source_entities": expected_metrics["dataset_view_rows"]["training_source_entities"],
            "source_manifests": 23,
        })
        loads = updated.setdefault("supplement_loads", [])
        if any(row.get("name") == SOURCE_MANIFEST_NAME for row in loads if isinstance(row, dict)):
            raise ValueError("core manifest already contains a training append entry")
        load_entry = {
            "name": SOURCE_MANIFEST_NAME,
            "applied_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "baseline_database_sha256": BASE_DB_SHA256,
            "database_sha256_after": after_hash,
            "backup_database": backup_db.relative_to(ROOT).as_posix(),
            "backup_manifest": backup_manifest.relative_to(ROOT).as_posix(),
            "source_manifest_name": SOURCE_MANIFEST_NAME,
            "observation_rows": expected_metrics["total_observation_rows"],
            "coverage_rows": expected_metrics["date_coverage_rows"],
            "source_file_rows": sum(expected_metrics["source_file_inventory_rows"].values()),
            "source_hashes": hashes,
        }
        loads.append(load_entry)
        write_json_atomic(CORE_MANIFEST, updated)
        if load_json(CORE_MANIFEST).get("database_sha256") != after_hash:
            raise ValueError("core manifest database hash failed post-write verification")
        return {"status": "applied", "applied": True, **load_entry}
    except Exception:
        if committed:
            shutil.copy2(backup_db, CORE_DB)
            shutil.copy2(backup_manifest, CORE_MANIFEST)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--apply", action="store_true", help="append after completed dry-run and root review")
    parser.add_argument("--confirm-core-append", action="store_true", help="second explicit opt-in for the core write path")
    args = parser.parse_args()
    if args.apply != args.confirm_core_append:
        parser.error("core writes require both --apply and --confirm-core-append")

    inventories, source_files, coverage_rows, parquet_paths, hashes = verify_inputs(args.input_dir)
    hashes["thoroughbred/research/20261002_training_three_v1/loader/load_training_three.py"] = sha256_file(OUT / "load_training_three.py")
    hashes["thoroughbred/research/20261002_training_three_v1/loader/schema.sql"] = sha256_file(OUT / "schema.sql")
    hashes["thoroughbred/research/20261002_training_three_v1/loader/input_contract.json"] = sha256_file(OUT / "input_contract.json")
    current_hash, _, source_count, core_manifest, is_replay = inspect_core_state()
    # Read-only validation computes the exact append manifest before any write.
    with tempfile.TemporaryDirectory(prefix="training-three-metrics-") as scratch:
        memory = prepare_dry_run_connection(inventories, source_files, coverage_rows, parquet_paths, Path(scratch))
        try:
            validate_input_capture_linkage(memory)
            metrics = validate_staged_data(memory, inventories, source_files)
        finally:
            memory.close()
    app_hashes = {
        "loader": sha256_file(OUT / "load_training_three.py"),
        "schema": sha256_file(OUT / "schema.sql"),
        "contract": sha256_file(OUT / "input_contract.json"),
    }
    expected_source = source_manifest_value(inventories, hashes, metrics, app_hashes)
    expected_source_json = json.dumps(expected_source, ensure_ascii=False, sort_keys=True)
    if is_replay:
        # Run the complete read-only replay check in a temporary connection.
        with tempfile.TemporaryDirectory(prefix="training-three-replay-") as scratch:
            memory = duckdb.connect(":memory:")
            try:
                configure_duckdb(memory, Path(scratch))
                memory.execute(f"ATTACH DATABASE {sql_literal(str(CORE_DB.resolve(strict=True)))} AS core_db (READ_ONLY)")
                memory.execute("CREATE TEMP VIEW entity_reference_roster AS SELECT * FROM core_db.entity_reference_roster")
                parquet_list = ", ".join(parquet_sql_path(parquet_paths[name]) for name in DATASETS)
                memory.execute(f"""
                    CREATE TEMP TABLE training_raw_observations AS
                    SELECT p.*,
                        '{AVAILABILITY_STATUS}'::VARCHAR AS availability_status,
                        FALSE::BOOLEAN AS historical_prerace_eligibility_verified,
                        '{PHYSICAL_VENUE_STATUS}'::VARCHAR AS physical_venue_status
                    FROM read_parquet([{parquet_list}], union_by_name=false) AS p
                """)
                apply_schema(memory, dry_run=True)
                load_staging_rows(memory, coverage_rows, source_files)
                replay = verify_replay(memory, expected_source_json, source_count, metrics)
            finally:
                memory.close()
    else:
        replay = None

    if args.apply:
        report = append_core(inventories, source_files, coverage_rows, parquet_paths,
                             hashes, expected_source, metrics)
        report["source_hashes"] = hashes
        report["metrics"] = metrics
        write_json_atomic(OUT / "load_manifest.json", report)
    else:
        report = {
            "status": "dry_run_replay_passed" if is_replay else "dry_run_passed",
            "applied": False,
            "idempotent_replay": is_replay,
            "core_database": CORE_DB.relative_to(ROOT).as_posix(),
            "core_database_sha256_before": current_hash,
            "baseline_database_sha256": BASE_DB_SHA256,
            "existing_source_manifest_rows": source_count,
            "existing_core_objects": len(inspect_core_state()[1]) - (9 if is_replay else 0),
            "input_hashes": hashes,
            "dataset_counts": metrics,
            "proposed_objects": [
                {"name": name, "type": kind,
                 "rows": (metrics["total_observation_rows"] if name in {"training_observation_qa"}
                          else metrics["dataset_view_rows"].get(name,
                               metrics["total_observation_rows"] if name == "training_raw_observations"
                               else metrics["date_coverage_rows"] if name == "training_capture_coverage"
                               else sum(metrics["source_file_inventory_rows"].values()) if name == "training_source_files"
                               else 0))}
                for name, kind in CORE_OBJECT_TYPES.items()
            ],
            "proposed_source_manifest": SOURCE_MANIFEST_NAME,
            "replay_verification": replay,
            "expected_core_after_apply": {"objects": 101, "source_manifest_rows": 23},
            "backup_directory": BACKUP_DIR.relative_to(ROOT).as_posix(),
            "status_rules": {
                "availability_status": AVAILABILITY_STATUS,
                "historical_prerace_eligibility_verified": False,
                "historical_14_00_publication_time_inferred": False,
                "physical_venue_status": PHYSICAL_VENUE_STATUS,
                "api22_occurrence_is_event_id": False,
                "api22_occurrence_is_chronological": False,
                "api216_count_unit": "unresolved",
            },
        }
        write_json_atomic(OUT / "dry_run_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
