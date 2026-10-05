#!/usr/bin/env python3
"""Import frozen Jeju API16 clinic rows and current API42 profiles into a SQLite copy.

The loader has no network client. Source files and dictionary Parquets are verified
before use. It requires explicit paths and a database SHA pin for every apply.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError as exc:  # pragma: no cover - message is the useful behavior
    raise SystemExit("Use the repository .venv Python, which includes pyarrow.") from exc


PARSER_VERSION = "jeju-api16-clinic-import-v1"
API16_RUN_RELATIVE = Path(
    "jeju/research/20260929_api_detail_sources/raw/"
    "full_year_clinic_judgement_start_training/20260929T150517.740550Z"
)
API16_OPERATION = "raceHorseClinic_1"
API16_ENDPOINT = "https://apis.data.go.kr/B551015/API16_1/raceHorseClinic_1"
API16_DATASET_ID = "15057799"
API16_DATASET_NAME = "마필진료 정보"
API16_RUN_MANIFEST_SHA256 = "2984aeb0c982e67b4d8157ae1afe7a202aa199d2c9944b1a099b03450d79bd38"
API16_FIELDS = (
    "meet", "clinicDate", "hrName", "hrNo", "hospiName", "illName1", "illName2", "part",
)
EXPECTED_API16_ROWS = 12_030
EXPECTED_API16_PAGES = 32
EXPECTED_API16_YEARS = tuple(range(2002, 2027))
ANALYSIS_CUTOFF = "2026-09-19"
PROFILE_ROWS_NAME = "validated_profile_rows.jsonl"
PROFILE_MANIFEST_NAME = "collection_manifest.json"
PROFILE_TARGET_NAME = "target_manifest.json"
PROFILE_EXPECTED_COUNT = 81
API42_OPERATION = "totalHorseInfo_1"
API42_ENDPOINT = "https://apis.data.go.kr/B551015/API42_1/totalHorseInfo_1"
API42_DATASET_ID = "15057985"
API42_DATASET_NAME = "마필종합 상세정보"
PROFILE_FINAL_LOGICAL_ROOT = "jeju/research/20261002_medical_db_load/profile_collection"
SMALL_BEAR_ID = "3005648"

DICTIONARY_PINNED_FILES = {
    "manifest.json": ("08f85681b4125faea6be5912ad4b136c7199f25eb2ef3bad5ae856fb90b024ab", 12937),
    "schema.json": ("8b5fbf61dd72b7234384ab41c3b97548f3f9f65078cb1415f6a9a180a9521963", 9614),
    "README.md": ("134599fd27b6dce1ded46f4a569292d0fb5e3be42c68aa44e73d37e954aa68b9", 4437),
    "build_dictionary.py": ("4e10697fc66318fc16ec537624818c12aaf76c8aa0e44ef11f2788a5dc82e9fd", 47670),
}
DICTIONARY_PINNED_PARQUETS = {
    "api33_source_rows.parquet": ("3e9e8e99f5a2f79e135f70f40f41d019df94c43556443a7d9d0fec7580c62a75", 252942, 3523),
    "api33_terms.parquet": ("8766e10b60fc240d2277affc115bd3bdf57f8ff5f5e2c59c2f1103510ad05945", 201047, 3511),
    "phrase_decisions.parquet": ("bc8eb16e757f7ee98587b16a7cb5e762ab5b1db04bf12c7fca249821d08810b4", 362145, 5397),
    "phrase_components.parquet": ("9d1e55d8ffb9dd2796b375385871a162a4533c66c305e0fbc4a332c79d6eb5bb", 289639, 9113),
    "explanation_observations.parquet": ("57b6c6c612a73b32bfef165ae2e12c8f4309505e025f641d7f76f3c4e3e9181a", 157534, 145),
    "explanation_terms.parquet": ("7bfce6799b4f328dd6cfc2a6f0fdd11e8585568ee10b02610ba361f342dc7857", 72477, 119),
}
DICTIONARY_TABLES = {
    "api33_source_rows.parquet": "medical_api33_source_rows",
    "api33_terms.parquet": "medical_api33_terms",
    "phrase_decisions.parquet": "medical_phrase_decisions",
    "phrase_components.parquet": "medical_phrase_components",
    "explanation_observations.parquet": "medical_explanation_observations",
    "explanation_terms.parquet": "medical_explanation_terms",
}
EXPECTED_DICTIONARY_SAFETY = {
    "automatic_event_linking_enabled": False,
    "legacy_dacom72_prefix_rule_reuse_enabled": False,
    "api33_ill_desc_used_as_explanation": False,
}

MIGRATION_PATH = Path(__file__).resolve().with_name("20261002_add_medical_api_rows.sql")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value


def add_frozen_file(files: dict[str, dict[str, Any]], path: Path, label: str) -> bytes:
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"Frozen input is not a regular file: {label}")
    raw = resolved.read_bytes()
    files[label] = {"path": resolved, "sha256": sha256_bytes(raw), "bytes": len(raw)}
    return raw


def recheck_frozen_files(files: dict[str, dict[str, Any]]) -> None:
    for label, info in files.items():
        path = info["path"]
        if not path.is_file() or path.stat().st_size != info["bytes"] or sha256_file(path) != info["sha256"]:
            raise ValueError(f"Frozen input changed during the load: {label}")


def safe_local_path(base: Path, relative: str) -> Path:
    rel = PurePosixPath(relative)
    if not relative or rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValueError("A frozen source path is not a safe relative path")
    resolved_base = base.resolve(strict=True)
    candidate = base.joinpath(*rel.parts).resolve(strict=True)
    candidate.relative_to(resolved_base)
    if not candidate.is_file():
        raise ValueError("A frozen source path does not name a regular file")
    return candidate


def project_relative(path: Path, project_root: Path) -> str:
    return path.resolve(strict=True).relative_to(project_root.resolve(strict=True)).as_posix()


def raw_text(value: Any) -> str | None:
    return None if value is None else str(value)


def json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise ValueError(f"Unsupported JSON value type: {type(value).__name__}")


def response_items(payload: Any) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ValueError("Source response root is not an object")
    wrapper = payload.get("response", payload)
    if not isinstance(wrapper, dict):
        raise ValueError("Source response wrapper is not an object")
    header, body = wrapper.get("header"), wrapper.get("body")
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise ValueError("Source response header or body is missing")
    item_value = body.get("items")
    if isinstance(item_value, dict):
        item_value = item_value.get("item")
    if item_value is None or item_value == "":
        rows: list[dict[str, Any]] = []
    elif isinstance(item_value, dict):
        rows = [item_value]
    elif isinstance(item_value, list) and all(isinstance(item, dict) for item in item_value):
        rows = item_value
    else:
        raise ValueError("Source response items have an unsupported shape")
    return header, body, rows


def safe_public_url(url: str, operation: str) -> dict[str, str]:
    parts = urlsplit(url)
    expected_path = "/B551015/API16_1/raceHorseClinic_1"
    if parts.scheme != "https" or parts.netloc != "apis.data.go.kr" or parts.path != expected_path:
        raise ValueError("API16 source URL does not match the frozen public endpoint")
    pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=False)
    if any("key" in key.lower() for key, _ in pairs):
        raise ValueError("A source URL contains an authentication parameter")
    params = dict(pairs)
    if len(params) != len(pairs) or params.get("_type") != "json":
        raise ValueError("API16 source URL parameters are duplicated or invalid")
    return params


def parse_source_date(value: Any) -> tuple[str | None, str | None]:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None, None
    raw = str(value)
    if not re.fullmatch(r"\d{8}", raw):
        return raw, None
    try:
        parsed = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    except ValueError:
        return raw, None
    return raw, parsed.isoformat()


def official_horse_id(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if value > 0 else None
    if isinstance(value, str) and re.fullmatch(r"\d+", value):
        return value
    return None


def kst_date(timestamp: str) -> str:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("A profile observation timestamp must include a timezone")
    return parsed.astimezone(ZoneInfo("Asia/Seoul")).date().isoformat()


def verify_public_request_params(url: str, year: int, page_no: int) -> dict[str, str]:
    params = safe_public_url(url, API16_OPERATION)
    expected = {
        "meet": "2",
        "clinic_year": str(year),
        "pageNo": str(page_no),
        "numOfRows": "1000",
        "_type": "json",
    }
    if params != expected:
        raise ValueError(f"API16 page has unexpected public request parameters for {year}/{page_no}: {params}")
    return params


def load_api16_source(
    project_root: Path,
    source_run_dir: Path,
    frozen: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    project_root = project_root.resolve(strict=True)
    source_run_dir = source_run_dir.resolve(strict=True)
    source_run_dir.relative_to(project_root)
    manifest_path = source_run_dir / "run_manifest.json"
    run_bytes = add_frozen_file(frozen, manifest_path, "api16_run_manifest")
    run_sha = sha256_bytes(run_bytes)
    if run_sha != API16_RUN_MANIFEST_SHA256:
        raise ValueError("API16 run manifest differs from the frozen approved SHA-256")
    manifest = json.loads(run_bytes)
    summary = manifest.get("summary", {})
    clinic = manifest.get("datasets", {}).get("clinic", {})
    clinic_summary = summary.get("datasets", {}).get("clinic", {})
    if summary.get("status") != "complete" or clinic.get("operation") != API16_OPERATION:
        raise ValueError("API16 clinic source manifest is incomplete or names another operation")
    if (clinic_summary.get("rows"), clinic_summary.get("pages"), clinic_summary.get("years_complete"),
            clinic_summary.get("years_positive"), clinic_summary.get("failed_or_incomplete_years")) != (
            EXPECTED_API16_ROWS, EXPECTED_API16_PAGES, 25, 16, []):
        raise ValueError("API16 clinic source summary differs from the verified 25-year scope")
    year_map = clinic.get("years")
    if not isinstance(year_map, dict) or {int(k) for k in year_map} != set(EXPECTED_API16_YEARS):
        raise ValueError("API16 clinic manifest does not cover every requested year from 2002 through 2026")

    years: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    raw_source_items: list[dict[str, Any]] = []
    total_rows = 0
    after_cutoff = 0
    for year in EXPECTED_API16_YEARS:
        year_meta = year_map[str(year)]
        expected_year_status = "complete_year_partition" if int(year_meta.get("actual_total_rows", -1)) > 0 else "query_complete_zero_rows"
        if year_meta.get("year") != year or year_meta.get("status") != expected_year_status:
            raise ValueError(f"API16 year partition {year} has an unexpected retrieval status")
        year_manifest_path = source_run_dir / "clinic" / str(year) / "year_manifest.json"
        year_manifest_bytes = add_frozen_file(frozen, year_manifest_path, f"api16_year_manifest_{year}")
        year_manifest = json.loads(year_manifest_bytes)
        for field in (
            "year", "status", "pages", "api_total_count", "expected_page_count",
            "actual_page_count", "actual_total_rows", "rows_matching_requested_year",
            "rows_after_cutoff", "rows_with_unparseable_date", "date_min", "date_max",
            "positive_data_evidence",
        ):
            if year_manifest.get(field) != year_meta.get(field):
                raise ValueError(f"API16 year manifest {year} differs from its run manifest for {field}")
        year_page_list = year_meta.get("pages")
        if not isinstance(year_page_list, list) or len(year_page_list) != int(year_meta.get("actual_page_count", -1)):
            raise ValueError(f"API16 year manifest {year} has an inconsistent page count")
        year_rows = 0
        year_after_cutoff = 0
        year_dates: list[str] = []
        for page_meta in year_page_list:
            page_no = int(page_meta.get("page_no", 0))
            if page_no < 1 or int(page_meta.get("reported_page_no", -1)) != page_no:
                raise ValueError(f"API16 page number is invalid for {year}")
            if page_meta.get("status_code") != 200 or page_meta.get("api_result_code") not in {"00", "0000"}:
                raise ValueError(f"API16 page response is not a successful service response for {year}/{page_no}")
            params = verify_public_request_params(
                str(page_meta.get("source_url_without_key", "")), year, page_no,
            )
            response_path = safe_local_path(source_run_dir, str(page_meta.get("response_file", "")))
            response_bytes = add_frozen_file(
                frozen, response_path, f"api16_page_{year}_{page_no}",
            )
            response_sha = sha256_bytes(response_bytes)
            if response_sha != page_meta.get("response_sha256") or len(response_bytes) != page_meta.get("response_bytes"):
                raise ValueError(f"API16 page {year}/{page_no} fails its frozen size or SHA-256 check")
            payload = json.loads(response_bytes)
            header, body, items = response_items(payload)
            if str(header.get("resultCode", "")).strip() not in {"00", "0000"}:
                raise ValueError(f"API16 page {year}/{page_no} has an unsuccessful API header")
            if len(items) != int(page_meta.get("actual_page_rows", -1)):
                raise ValueError(f"API16 page {year}/{page_no} item count differs from its manifest")
            if int(body.get("totalCount", -1)) != int(page_meta.get("api_total_count", -2)):
                raise ValueError(f"API16 page {year}/{page_no} totalCount differs from its manifest")
            if int(body.get("pageNo", -1)) != page_no:
                raise ValueError(f"API16 page {year}/{page_no} returned an unexpected page number")
            if int(body.get("numOfRows", -1)) != int(page_meta.get("api_page_size", -2)):
                raise ValueError(f"API16 page {year}/{page_no} page size differs from its manifest")
            if int(page_meta.get("api_total_count", -1)) != int(year_meta.get("api_total_count", -2)):
                raise ValueError(f"API16 page {year}/{page_no} totalCount differs from year manifest")
            for item_index, raw in enumerate(items, 1):
                raw_date, iso_date = parse_source_date(raw.get("clinicDate"))
                if iso_date is None or int(iso_date[:4]) != year:
                    raise ValueError(f"API16 item {year}/{page_no}/{item_index} has an invalid or wrong-year clinicDate")
                year_dates.append(raw_date)
                if iso_date > ANALYSIS_CUTOFF:
                    year_after_cutoff += 1
                raw_source_items.append({
                    "year": year,
                    "page_no": page_no,
                    "source_row_no": item_index,
                    "raw": raw,
                    "raw_date": raw_date,
                    "clinic_date": iso_date,
                    "source_path": response_path,
                    "source_relative_path": project_relative(response_path, project_root),
                    "page_meta": page_meta,
                    "params": params,
                    "response_bytes": response_bytes,
                    "response_sha256": response_sha,
                    "attempt_id": source_run_dir.name,
                })
            year_rows += len(items)
            page = {
                "year": year,
                "page_no": page_no,
                "path": response_path,
                "relative_path": project_relative(response_path, project_root),
                "bytes": response_bytes,
                "sha256": response_sha,
                "items": items,
                "page_meta": page_meta,
                "params": params,
                "attempt_id": source_run_dir.name,
            }
            pages.append(page)
        if (year_rows, year_after_cutoff) != (
            int(year_meta.get("actual_total_rows", -1)),
            int(year_meta.get("rows_after_cutoff", -2)),
        ):
            raise ValueError(f"API16 year {year} actual row or post-cutoff count differs from its manifest")
        actual_min = min(year_dates) if year_dates else None
        actual_max = max(year_dates) if year_dates else None
        if actual_min != year_meta.get("date_min") or actual_max != year_meta.get("date_max"):
            raise ValueError(f"API16 year {year} date bounds differ from its manifest")
        if int(year_meta.get("rows_matching_requested_year", -1)) != year_rows:
            raise ValueError(f"API16 year {year} matching-year row count differs from its manifest")
        if int(year_meta.get("rows_with_unparseable_date", -1)) != 0:
            raise ValueError(f"API16 year {year} reports an unparseable date")
        years.append({
            "year": year,
            "metadata": year_meta,
            "manifest_path": year_manifest_path,
            "manifest_sha256": sha256_bytes(year_manifest_bytes),
            "manifest_json": canonical_json(year_manifest),
        })
        total_rows += year_rows
        after_cutoff += year_after_cutoff

    if total_rows != EXPECTED_API16_ROWS or len(pages) != EXPECTED_API16_PAGES:
        raise ValueError("API16 full-year page or source-row totals differ from the verified count")
    if after_cutoff != 39:
        raise ValueError("API16 post-2026-09-19 row count differs from the verified 39-row tally")
    return {
        "manifest": manifest,
        "manifest_sha256": run_sha,
        "manifest_path": manifest_path,
        "years": years,
        "pages": pages,
        "raw_source_items": raw_source_items,
        "source_rows": total_rows,
        "pages_count": len(pages),
        "after_cutoff_rows": after_cutoff,
    }


def load_dictionary(dictionary_dir: Path, frozen: dict[str, dict[str, Any]]) -> dict[str, Any]:
    dictionary_dir = dictionary_dir.resolve(strict=True)
    file_data: dict[str, bytes] = {}
    for name, (expected_sha, expected_size) in DICTIONARY_PINNED_FILES.items():
        path = dictionary_dir / name
        raw = add_frozen_file(frozen, path, f"dictionary_{name}")
        if sha256_bytes(raw) != expected_sha or len(raw) != expected_size:
            raise ValueError(f"Dictionary support file differs from its root-verified pin: {name}")
        file_data[name] = raw
    manifest = json.loads(file_data["manifest.json"])
    schema = json.loads(file_data["schema.json"])
    if manifest.get("dataset") != "medical_dictionary_snapshot_v1":
        raise ValueError("Medical dictionary manifest identifies another data snapshot")
    for key, expected in EXPECTED_DICTIONARY_SAFETY.items():
        if manifest.get("safety", {}).get(key) is not expected:
            raise ValueError(f"Medical dictionary safety contract differs for {key}")
    if manifest.get("safety", {}).get("operating_sqlite_or_supabase_accessed") is not False:
        raise ValueError("Medical dictionary provenance indicates an operating database read")
    output_files = manifest.get("output_files", {})
    tables: list[dict[str, Any]] = []
    output_hash_rows: list[dict[str, Any]] = []
    for parquet_name, table_name in DICTIONARY_TABLES.items():
        expected_sha, expected_size, expected_rows = DICTIONARY_PINNED_PARQUETS[parquet_name]
        path = dictionary_dir / parquet_name
        parquet_bytes = add_frozen_file(frozen, path, f"dictionary_{parquet_name}")
        digest = sha256_bytes(parquet_bytes)
        pin = output_files.get(parquet_name, {})
        if digest != expected_sha or len(parquet_bytes) != expected_size:
            raise ValueError(f"Dictionary Parquet differs from its root-verified pin: {parquet_name}")
        if pin.get("sha256") != digest or pin.get("bytes") != len(parquet_bytes) or pin.get("row_count") != expected_rows:
            raise ValueError(f"Dictionary manifest differs from the verified Parquet pin: {parquet_name}")
        arrow_table = pq.read_table(path)
        rows = arrow_table.to_pylist()
        if len(rows) != expected_rows:
            raise ValueError(f"Dictionary Parquet row count differs from its pin: {parquet_name}")
        actual_schema = []
        for field in arrow_table.schema:
            actual_type = str(field.type)
            if actual_type == "int32":
                mapped_type = "int32"
            elif actual_type == "int64":
                mapped_type = "int64"
            elif actual_type == "string":
                mapped_type = "string"
            elif actual_type == "bool":
                mapped_type = "bool"
            else:
                raise ValueError(f"Unsupported Arrow type {actual_type} in {parquet_name}")
            actual_schema.append({"name": field.name, "arrow_type": mapped_type, "nullable": field.nullable})
        if actual_schema != schema.get(parquet_name):
            raise ValueError(f"Dictionary Parquet Arrow schema differs from schema.json: {parquet_name}")
        columns = [item["name"] for item in actual_schema]
        if any(not re.fullmatch(r"[a-z][a-z0-9_]*", column) for column in columns):
            raise ValueError(f"Dictionary schema has an unsafe SQLite identifier: {parquet_name}")
        for row in rows:
            if set(row) != set(columns):
                raise ValueError(f"Dictionary row columns do not match its Arrow schema: {parquet_name}")
            for field in actual_schema:
                value = row[field["name"]]
                if value is None:
                    if not field["nullable"]:
                        raise ValueError(f"Unexpected null in non-nullable dictionary field: {parquet_name}/{field['name']}")
                    continue
                want = field["arrow_type"]
                if want == "string" and not isinstance(value, str):
                    raise ValueError(f"Dictionary field type changed: {parquet_name}/{field['name']}")
                if want in {"int32", "int64"} and (not isinstance(value, int) or isinstance(value, bool)):
                    raise ValueError(f"Dictionary field type changed: {parquet_name}/{field['name']}")
                if want == "bool" and not isinstance(value, bool):
                    raise ValueError(f"Dictionary field type changed: {parquet_name}/{field['name']}")
        if parquet_name == "api33_source_rows.parquet" and any(row.get("ill_desc") != "-" for row in rows):
            raise ValueError("API33 descriptions differ from the audited dash-only source values")
        entry = {
            "file_name": parquet_name,
            "table_name": table_name,
            "sha256": digest,
            "response_bytes": len(parquet_bytes),
            "row_count": expected_rows,
            "schema": actual_schema,
            "rows": rows,
        }
        tables.append(entry)
        output_hash_rows.append({
            "file_name": parquet_name,
            "sha256": digest,
            "response_bytes": len(parquet_bytes),
            "row_count": expected_rows,
            "column_schema_json": canonical_json(actual_schema),
        })
    if set(schema) != set(DICTIONARY_TABLES):
        raise ValueError("Dictionary schema.json does not describe exactly the six approved Parquets")
    expected_metric_rows = {
        "api33_source_rows.parquet": 3523,
        "api33_terms.parquet": 3511,
        "phrase_decisions.parquet": 5397,
        "phrase_components.parquet": 9113,
        "explanation_observations.parquet": 145,
        "explanation_terms.parquet": 119,
    }
    if {name: data["row_count"] for name, data in output_files.items() if name in expected_metric_rows} != expected_metric_rows:
        raise ValueError("Dictionary manifest does not report the verified six-table row counts")
    return {
        "manifest": manifest,
        "manifest_sha256": sha256_bytes(file_data["manifest.json"]),
        "schema_sha256": sha256_bytes(file_data["schema.json"]),
        "tables": tables,
        "output_hash_rows": output_hash_rows,
        "dictionary_dir": dictionary_dir,
    }


def extract_exclusions(project_root: Path, frozen: dict[str, dict[str, Any]]) -> tuple[set[str], dict[str, Any]]:
    path = project_root / "jeju/data/horse_exclusions.json"
    raw = add_frozen_file(frozen, path, "jeju_horse_exclusions")
    data = json.loads(raw)
    horses = data.get("horses")
    if not isinstance(horses, dict):
        raise ValueError("Horse exclusion source has an unexpected schema")
    excluded = {SMALL_BEAR_ID}
    excluded.update(
        str(horse_id) for horse_id, record in horses.items()
        if isinstance(record, dict) and record.get("reimport_allowed") is False
    )
    if SMALL_BEAR_ID not in excluded:
        raise ValueError("Small Bear exclusion is missing")
    return excluded, data


def load_profiles(
    profile_dir: Path,
    api16: dict[str, Any],
    current_jeju_ids: set[str],
    excluded_ids: set[str],
    frozen: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    profile_dir = profile_dir.resolve(strict=True)
    manifest_path = profile_dir / PROFILE_MANIFEST_NAME
    manifest_bytes = add_frozen_file(frozen, manifest_path, "profile_collection_manifest")
    manifest = json.loads(manifest_bytes)
    rows_path = profile_dir / PROFILE_ROWS_NAME
    rows_bytes = add_frozen_file(frozen, rows_path, "profile_validated_rows")
    target_rel = manifest.get("files", {}).get("target_manifest", PROFILE_TARGET_NAME)
    if not isinstance(target_rel, str):
        raise ValueError("API42 collection manifest has no safe target-manifest path")
    target_path = safe_local_path(profile_dir, target_rel)
    target_bytes = add_frozen_file(frozen, target_path, "profile_target_manifest")
    target_manifest = json.loads(target_bytes)
    source_candidate_ids = {
        horse_id
        for entry in api16["raw_source_items"]
        if entry["raw"].get("meet") == "제주"
        for horse_id in [official_horse_id(entry["raw"].get("hrNo"))]
        if horse_id is not None and horse_id not in excluded_ids
    }
    missing_ids = source_candidate_ids - current_jeju_ids
    lines = rows_bytes.decode("utf-8").splitlines()
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"Validated API42 row is not an object at line {line_no}")
        rows.append(item)
    if len(rows) != PROFILE_EXPECTED_COUNT:
        raise ValueError("API42 validated profile JSONL does not contain the approved 81 rows")
    if len({str(row.get("horse_id")) for row in rows}) != PROFILE_EXPECTED_COUNT:
        raise ValueError("API42 validated profile JSONL repeats an official horse ID")
    profile_ids = {str(row["horse_id"]) for row in rows}
    if not missing_ids <= profile_ids:
        raise ValueError(
            f"API42 collection does not cover every missing current Jeju profile ID "
            f"(missing={len(missing_ids)}, collected={len(profile_ids)}, "
            f"not_collected={sorted(missing_ids-profile_ids)[:5]})"
        )
    if not profile_ids <= source_candidate_ids:
        raise ValueError("API42 profile collection includes IDs absent from the API16 Jeju source")
    target_rows = target_manifest.get("targets")
    if not isinstance(target_rows, list):
        raise ValueError("API42 target manifest has no target list")
    target_ids = {str(target.get("horse_id")) for target in target_rows if isinstance(target, dict)}
    if len(target_rows) != PROFILE_EXPECTED_COUNT or target_ids != profile_ids:
        raise ValueError("API42 validated profiles do not exactly match the frozen 81-ID target manifest")
    if len(missing_ids) not in {0, PROFILE_EXPECTED_COUNT}:
        raise ValueError("API42 collection target set is only partially missing from current profiles")
    if missing_ids and missing_ids != profile_ids:
        raise ValueError("Initial API42 target IDs are not exactly the source IDs missing current profiles")
    if SMALL_BEAR_ID in profile_ids or profile_ids & excluded_ids:
        raise ValueError("An excluded horse appears in the API42 current-profile collection")
    manifest_count = manifest.get("validated_profile_count", manifest.get("row_count"))
    if manifest_count != PROFILE_EXPECTED_COUNT or manifest.get("target_unique_profile_count") != PROFILE_EXPECTED_COUNT:
        raise ValueError("API42 collection manifest target or validated profile count differs from 81")
    source_summary = manifest.get("source_summary", {})
    if (source_summary.get("api16_source_run_id") != "20260929T150517.740550Z"
            or source_summary.get("api16_source_rows") != EXPECTED_API16_ROWS
            or source_summary.get("unlinked_clinic_rows") != 156
            or source_summary.get("unlinked_unique_horse_ids") != PROFILE_EXPECTED_COUNT
            or source_summary.get("small_bear_3005648_clinic_rows") != 0):
        raise ValueError("API42 collection manifest source target summary differs from the verified 81-profile scope")
    if manifest.get("status") not in {"complete", "completed", "verified", "complete_verified", None}:
        raise ValueError("API42 collection manifest is not complete")
    if (manifest.get("small_bear_excluded") is False
            or manifest.get("small_bear_3005648_reimport_allowed") is not False):
        raise ValueError("API42 collection manifest does not confirm the Small Bear exclusion")

    by_source_ref: dict[tuple[str, int, int], dict[str, Any]] = {}
    for entry in api16["raw_source_items"]:
        raw = entry["raw"]
        by_source_ref[(entry["source_relative_path"], entry["page_no"], entry["source_row_no"])] = {
            "horse_id": official_horse_id(raw.get("hrNo")),
            "clinic_date_raw": str(raw.get("clinicDate")),
            "meet_raw": raw_text(raw.get("meet")),
            "page_sha256": entry["response_sha256"],
            "page_bytes": len(entry["response_bytes"]),
        }

    profiles: list[dict[str, Any]] = []
    expected_api16_refs: dict[str, set[tuple[Any, ...]]] = {horse_id: set() for horse_id in profile_ids}
    source_prefix = f"{API16_RUN_RELATIVE.as_posix()}/"
    for entry in api16["raw_source_items"]:
        raw = entry["raw"]
        target_id = official_horse_id(raw.get("hrNo"))
        if target_id not in expected_api16_refs or raw.get("meet") != "제주":
            continue
        project_relative_path = entry["source_relative_path"]
        if not project_relative_path.startswith(source_prefix):
            raise ValueError("API16 target source page path is outside the frozen clinic run")
        expected_api16_refs[target_id].add((
            project_relative_path[len(source_prefix):], entry["page_no"], entry["source_row_no"],
            str(raw.get("clinicDate")), target_id, raw_text(raw.get("meet")),
            entry["response_sha256"], len(entry["response_bytes"]), "20260929T150517.740550Z",
        ))
    expected_target_refs: dict[str, set[tuple[Any, ...]]] = {}
    for target in target_rows:
        if not isinstance(target, dict):
            raise ValueError("API42 target manifest contains a malformed target")
        target_id = str(target.get("horse_id", ""))
        source_rows = target.get("source_rows")
        if not isinstance(source_rows, list):
            raise ValueError(f"API42 target {target_id} has no source-row evidence")
        expected_target_refs[target_id] = {
            (
                ref.get("source_page_relative_path"), ref.get("page_no"), ref.get("item_index"),
                ref.get("clinic_date_raw"), ref.get("horse_id"), ref.get("meet_raw"),
                ref.get("source_page_sha256"), ref.get("source_page_bytes"), ref.get("source_run_id"),
            )
            for ref in source_rows if isinstance(ref, dict)
        }
        if len(expected_target_refs[target_id]) != len(source_rows):
            raise ValueError(f"API42 target {target_id} source-row references are duplicated or malformed")
    if expected_target_refs != expected_api16_refs:
        raise ValueError("API42 target manifest does not exactly cover all matching API16 source rows")
    if sum(map(len, expected_api16_refs.values())) != 156:
        raise ValueError("Frozen API16 source does not resolve to the expected 156 target references")
    for row in rows:
        horse_id = str(row.get("horse_id", ""))
        if not re.fullmatch(r"\d+", horse_id):
            raise ValueError("API42 row horse_id is not a digits-only official ID")
        raw_item = row.get("raw_item")
        if not isinstance(raw_item, dict):
            raise ValueError(f"API42 profile {horse_id} does not preserve the complete raw item")
        if len(raw_item) != 218 or official_horse_id(raw_item.get("hrNo")) != horse_id:
            raise ValueError(f"API42 profile {horse_id} fails its 218-field exact-ID check")
        expected_keys = sorted(raw_item)
        if row.get("item_field_keys") != expected_keys:
            raise ValueError(f"API42 profile {horse_id} field-key snapshot differs from raw_item")
        expected_types = {key: json_type(raw_item[key]) for key in sorted(raw_item)}
        if row.get("item_field_types") != expected_types:
            raise ValueError(f"API42 profile {horse_id} field-type snapshot differs from raw_item")
        if row.get("breed_label_raw") != raw_text(raw_item.get("breed")) or raw_text(raw_item.get("breed")) != "제주마":
            raise ValueError(f"API42 profile {horse_id} is not a current 제주마 profile")
        if row.get("horse_name_raw") != raw_text(raw_item.get("hrNm")):
            raise ValueError(f"API42 profile {horse_id} current name differs from raw_item")
        if not isinstance(raw_item.get("hrNm"), str) or not raw_item["hrNm"].strip():
            raise ValueError(f"API42 profile {horse_id} has no usable current horse name")
        if row.get("birth_date_raw") != raw_item.get("birthDt"):
            raise ValueError(f"API42 profile {horse_id} birth date differs from raw_item")
        birth_date = raw_item.get("birthDt")
        birth_date_text = str(birth_date) if birth_date is not None else ""
        if not re.fullmatch(r"\d{8}", birth_date_text):
            raise ValueError(f"API42 profile {horse_id} birth date is not YYYYMMDD")
        try:
            date.fromisoformat(
                f"{birth_date_text[:4]}-{birth_date_text[4:6]}-{birth_date_text[6:8]}"
            )
        except ValueError as exc:
            raise ValueError(f"API42 profile {horse_id} birth date is not a valid calendar date") from exc
        if row.get("api_result_code") not in {"00", "0000"} or row.get("api_total_count") != 1:
            raise ValueError(f"API42 profile {horse_id} is not a successful single-profile response")
        if row.get("http_status") != 200 or row.get("returned_item_count") != 1 or row.get("exact_hr_no_match_count") != 1:
            raise ValueError(f"API42 profile {horse_id} collection validation flags are not successful")
        response_relative = row.get("response_file")
        if not isinstance(response_relative, str):
            raise ValueError(f"API42 profile {horse_id} lacks a response path")
        response_path = safe_local_path(profile_dir, response_relative)
        response_bytes = add_frozen_file(frozen, response_path, f"api42_response_{horse_id}")
        digest = sha256_bytes(response_bytes)
        if digest != row.get("response_sha256") or len(response_bytes) != row.get("response_bytes"):
            raise ValueError(f"API42 profile {horse_id} response fails its frozen size or SHA-256 check")
        payload = json.loads(response_bytes)
        header, body, items = response_items(payload)
        if str(header.get("resultCode", "")).strip() not in {"00", "0000"}:
            raise ValueError(f"API42 profile {horse_id} source response has an unsuccessful API header")
        if int(body.get("totalCount", -1)) != 1 or len(items) != 1 or items[0] != raw_item:
            raise ValueError(f"API42 profile {horse_id} raw response does not match its validated item")
        observed = row.get("observed_at_utc")
        if not isinstance(observed, str) or row.get("observed_kst_date") != kst_date(observed):
            raise ValueError(f"API42 profile {horse_id} observation timestamp is invalid")
        metadata = row.get("request_metadata")
        if not isinstance(metadata, dict):
            raise ValueError(f"API42 profile {horse_id} request metadata is missing")
        public_params = metadata.get("public_params", {})
        if not isinstance(public_params, dict) or any("key" in str(key).lower() for key in public_params):
            raise ValueError(f"API42 profile {horse_id} request parameters contain a credential key")
        expected_public_params = {
            "_type": "json", "hr_no": horse_id, "numOfRows": 1000, "pageNo": 1,
        }
        if public_params != expected_public_params:
            raise ValueError(f"API42 profile {horse_id} public request parameters do not match the exact ID query")
        endpoint_path = str(metadata.get("endpoint_path", "/API42_1/totalHorseInfo_1"))
        if endpoint_path not in {"/API42_1/totalHorseInfo_1", "/B551015/API42_1/totalHorseInfo_1"}:
            raise ValueError(f"API42 profile {horse_id} request endpoint is unexpected")
        if metadata.get("operation", API42_OPERATION) != API42_OPERATION:
            raise ValueError(f"API42 profile {horse_id} operation is unexpected")
        response_parts = PurePosixPath(response_relative).parts
        if (len(response_parts) != 5 or response_parts[0:2] != ("raw", "api42_profiles")
                or response_parts[3] != "source_pages" or not response_parts[2]
                or not response_parts[4].endswith(".json")):
            raise ValueError(f"API42 profile {horse_id} response path lacks its source attempt ID")

        refs = row.get("clinic_source_rows")
        if not isinstance(refs, list) or not refs:
            raise ValueError(f"API42 profile {horse_id} lacks source API16 row evidence")
        actual_target_refs: set[tuple[Any, ...]] = set()
        for ref in refs:
            if not isinstance(ref, dict):
                raise ValueError(f"API42 profile {horse_id} source row reference is malformed")
            raw_relative = ref.get("source_page_relative_path")
            full_relative = f"{API16_RUN_RELATIVE.as_posix()}/{raw_relative}" if isinstance(raw_relative, str) else ""
            ref_key = (full_relative, ref.get("page_no"), ref.get("item_index"))
            source = by_source_ref.get(ref_key)
            if ref.get("source_run_id") != "20260929T150517.740550Z":
                raise ValueError(f"API42 profile {horse_id} references another clinic source run")
            if (source is None or ref.get("horse_id") != horse_id
                    or str(ref.get("clinic_date_raw")) != source["clinic_date_raw"]
                    or ref.get("meet_raw") != source["meet_raw"]
                    or ref.get("source_page_sha256") != source["page_sha256"]
                    or ref.get("source_page_bytes") != source["page_bytes"]
                    or source["horse_id"] != horse_id):
                raise ValueError(f"API42 profile {horse_id} source row reference does not resolve exactly")
            actual_target_refs.add((
                raw_relative, ref.get("page_no"), ref.get("item_index"),
                ref.get("clinic_date_raw"), ref.get("horse_id"), ref.get("meet_raw"),
                ref.get("source_page_sha256"), ref.get("source_page_bytes"), ref.get("source_run_id"),
            ))
        if actual_target_refs != expected_api16_refs.get(horse_id):
            raise ValueError(f"API42 profile {horse_id} source references do not exactly cover all target clinic rows")
        if len(actual_target_refs) != len(refs):
            raise ValueError(f"API42 profile {horse_id} repeats a clinic source-row reference")
        profiles.append({
            "horse_id": horse_id,
            "raw_item": raw_item,
            "payload_json": canonical_json(raw_item),
            "payload_sha256": sha256_bytes(canonical_json(raw_item).encode("utf-8")),
            "response_path": response_path,
            "response_relative_path": f"{PROFILE_FINAL_LOGICAL_ROOT}/{response_relative}",
            "response_bytes": response_bytes,
            "response_sha256": digest,
            "observed_at_utc": observed,
            "observed_kst_date": row["observed_kst_date"],
            "public_params": public_params,
            "http_status": int(row["http_status"]),
            "content_type": str(row.get("content_type") or "application/json;charset=UTF-8"),
            "attempt_id": response_parts[2],
            "normalized": {
                "horse_name_raw": raw_text(raw_item.get("hrNm")),
                "birth_date_raw": raw_text(raw_item.get("birthDt")),
                "age_raw": raw_text(raw_item.get("age")),
                "breed_label_raw": raw_text(raw_item.get("breed")),
                "sex_raw": raw_text(raw_item.get("sex")),
                "color_raw": raw_text(raw_item.get("color")),
                "production_country_raw": raw_text(raw_item.get("prdCty")),
            },
            "clinic_source_rows": refs,
        })
    return {
        "manifest": manifest,
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "rows_sha256": sha256_bytes(rows_bytes),
        "rows_bytes": len(rows_bytes),
        "target_manifest_sha256": sha256_bytes(target_bytes),
        "profiles": profiles,
        "profile_ids": profile_ids,
        "missing_ids_before_import": missing_ids,
        "source_refs_validated": sum(len(profile["clinic_source_rows"]) for profile in profiles),
    }


def load_inputs(args: argparse.Namespace) -> dict[str, Any]:
    project_root = args.project_root.resolve(strict=True)
    source_dir = args.source_run_dir.resolve(strict=True) if args.source_run_dir else (project_root / API16_RUN_RELATIVE).resolve(strict=True)
    dictionary_dir = args.dictionary_dir.resolve(strict=True) if args.dictionary_dir else (
        project_root / "thoroughbred/research/20261002_medical_v1/dictionary"
    ).resolve(strict=True)
    frozen: dict[str, dict[str, Any]] = {}
    add_frozen_file(frozen, MIGRATION_PATH, "load_sql_migration")
    api16 = load_api16_source(project_root, source_dir, frozen)
    dictionary = load_dictionary(dictionary_dir, frozen)
    excluded_ids, exclusion_doc = extract_exclusions(project_root, frozen)
    # profile set equality depends on the explicit database snapshot, so profiles are
    # completed in build_plan() after the read-only DB profile set is known.
    return {
        "project_root": project_root,
        "source_dir": source_dir,
        "dictionary_dir": dictionary_dir,
        "frozen": frozen,
        "api16": api16,
        "dictionary": dictionary,
        "excluded_ids": excluded_ids,
        "exclusion_doc": exclusion_doc,
        "profile_dir": args.profile_collection_dir.resolve(strict=True),
    }


def sqlite_affinity(arrow_type: str) -> str:
    if arrow_type in {"int32", "int64", "bool"}:
        return "INTEGER"
    if arrow_type == "string":
        return "TEXT"
    raise ValueError(f"Unsupported dictionary column type: {arrow_type}")


def dictionary_table_sql(table: dict[str, Any]) -> str:
    table_name = table["table_name"]
    if table_name not in set(DICTIONARY_TABLES.values()):
        raise ValueError("Unexpected dictionary table name")
    columns = ["dictionary_row_no INTEGER PRIMARY KEY", "source_row_json TEXT NOT NULL"]
    for field in table["schema"]:
        name = field["name"]
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError("Unsafe dictionary column identifier")
        columns.append(f'"{name}" {sqlite_affinity(field["arrow_type"])}')
    return f'CREATE TABLE IF NOT EXISTS "{table_name}" (' + ", ".join(columns) + ")"


def execute_sql_file(conn: sqlite3.Connection, path: Path) -> None:
    pending = ""
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            if pending.strip():
                conn.execute(pending)
            pending = ""
    if pending.strip():
        raise ValueError("The migration SQL ends with an incomplete statement")


def sqlite_object_sql(conn: sqlite3.Connection) -> dict[tuple[str, str], str]:
    return {
        (str(row["type"]), str(row["name"])): str(row["sql"] or "")
        for row in conn.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        )
    }


def verify_database_integrity(conn: sqlite3.Connection) -> None:
    integrity = conn.execute("PRAGMA integrity_check").fetchall()
    if len(integrity) != 1 or integrity[0][0] != "ok":
        raise ValueError(f"SQLite integrity_check failed: {[row[0] for row in integrity[:10]]}")
    foreign_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_errors:
        raise ValueError(f"SQLite foreign_key_check found {len(foreign_errors)} existing violations")


def open_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve(strict=True)}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def open_readwrite_existing(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve(strict=True)}?mode=rw", uri=True, timeout=60)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=60000")
    return connection


def current_jeju_profile_ids(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT horse_id FROM horse_analysis_2026 WHERE profile_breed_label_raw='제주마'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def verify_existing_profile_target(conn: sqlite3.Connection, profile: dict[str, Any]) -> None:
    artifact = make_profile_artifact(profile)
    n = profile["normalized"]
    row = conn.execute(
        """SELECT hpo.api_record_id,hpo.horse_id,hpo.observed_at_utc,hpo.observed_kst_date,
                  hpo.horse_name_raw,hpo.birth_date_raw,hpo.age_raw,hpo.breed_label_raw,
                  hpo.sex_raw,hpo.color_raw,hpo.production_country_raw,
                  ar.record_index,ar.record_type,ar.natural_key,ar.payload_json,ar.payload_sha256,
                  sa.raw_relative_path,sa.sha256,sa.response_bytes,sa.operation,sa.attempt_id,
                  sa.request_params_json,sa.source_url_without_key,sa.http_status_code,
                  sa.content_type,sa.parser_version
           FROM horse_profile_observations hpo
           JOIN api_records ar ON ar.api_record_id=hpo.api_record_id
           JOIN source_artifacts sa ON sa.source_artifact_id=ar.source_artifact_id
           WHERE hpo.horse_id=? AND hpo.observed_at_utc=?""",
        (profile["horse_id"], profile["observed_at_utc"]),
    ).fetchall()
    if len(row) != 1:
        raise ValueError(
            f"Current profile target {profile['horse_id']} already exists in the Jeju profile set "
            "but has no unique exact imported API42 observation at its frozen timestamp"
        )
    observed = row[0]
    normalized = (
        observed["api_record_id"], observed["horse_id"], observed["observed_at_utc"],
        observed["observed_kst_date"], observed["horse_name_raw"], observed["birth_date_raw"],
        observed["age_raw"], observed["breed_label_raw"], observed["sex_raw"], observed["color_raw"],
        observed["production_country_raw"],
    )
    expected_normalized = (
        observed["api_record_id"], profile["horse_id"], profile["observed_at_utc"],
        profile["observed_kst_date"], n["horse_name_raw"], n["birth_date_raw"], n["age_raw"],
        n["breed_label_raw"], n["sex_raw"], n["color_raw"], n["production_country_raw"],
    )
    record_and_artifact = (
        observed["record_index"], observed["record_type"], observed["natural_key"],
        observed["payload_json"], observed["payload_sha256"], observed["raw_relative_path"],
        observed["sha256"], observed["response_bytes"], observed["operation"], observed["attempt_id"],
        observed["request_params_json"], observed["source_url_without_key"], observed["http_status_code"],
        observed["content_type"], observed["parser_version"],
    )
    expected_record_and_artifact = (
        1, "horse_profile", profile["horse_id"], profile["payload_json"], profile["payload_sha256"],
        artifact["raw_relative_path"], artifact["sha256"], artifact["response_bytes"],
        artifact["operation"], artifact["attempt_id"], artifact["request_params_json"],
        artifact["source_url_without_key"], artifact["http_status_code"], artifact["content_type"],
        artifact["parser_version"],
    )
    if normalized != expected_normalized or record_and_artifact != expected_record_and_artifact:
        raise ValueError(f"Existing API42 profile {profile['horse_id']} is not an exact replay of the frozen input")
    breed_rows = conn.execute(
        """SELECT horse_id,observed_event_date,breed_label_raw,evidence_kind,source_artifact_id,
                  api_record_id,timing_basis,notes
           FROM breed_evidence WHERE api_record_id=?""",
        (observed["api_record_id"],),
    ).fetchall()
    expected_breed = (
        profile["horse_id"], None, n["breed_label_raw"], "API42_1 current profile breed",
        # the source artifact is the one linked by this API record
        int(conn.execute("SELECT source_artifact_id FROM api_records WHERE api_record_id=?",
                         (observed["api_record_id"],)).fetchone()[0]),
        observed["api_record_id"], "profile_retrieval_time",
        "Current API42_1 profile breed observed at " + profile["observed_at_utc"] +
        "; the source does not provide a historical effective date.",
    )
    if len(breed_rows) != 1 or tuple(breed_rows[0]) != expected_breed:
        raise ValueError(f"Existing API42 profile {profile['horse_id']} lacks its exact current-breed provenance row")


def ensure_profile_candidate_links(
    conn: sqlite3.Connection, inputs: dict[str, Any],
) -> dict[str, Any]:
    api16 = inputs["api16"]
    current_ids = current_jeju_profile_ids(conn)
    input_profiles = load_profiles(
        inputs["profile_dir"], api16, current_ids, inputs["excluded_ids"], inputs["frozen"],
    )
    for profile in input_profiles["profiles"]:
        if profile["horse_id"] in current_ids:
            verify_existing_profile_target(conn, profile)
    return {
        "current_jeju_profile_ids_before": current_ids,
        "profiles": input_profiles,
        "new_profile_ids": input_profiles["profile_ids"],
        "missing_profile_ids_before": input_profiles["missing_ids_before_import"],
        "all_jeju_profile_ids": current_ids | input_profiles["profile_ids"],
        "source_candidate_ids": input_profiles["profile_ids"] | input_profiles["missing_ids_before_import"],
    }


def source_tuple(entry: dict[str, Any]) -> tuple[Any, ...]:
    raw = entry["raw"]
    present = sorted(raw.keys())
    absent = sorted(field for field in API16_FIELDS if field not in raw)
    field_types = {key: json_type(raw[key]) for key in sorted(raw)}
    raw_id = official_horse_id(raw.get("hrNo"))
    if raw_id is None:
        raise ValueError("API16 item has a non-canonical official horse number")
    return (
        entry["clinic_date"],
        raw_id,
        raw_text(raw.get("meet")),
        entry["raw_date"],
        raw_text(raw.get("hrName")),
        raw_text(raw.get("hrNo")),
        raw_text(raw.get("hospiName")),
        raw_text(raw.get("illName1")),
        raw_text(raw.get("illName2")),
        raw_text(raw.get("part")),
        canonical_json(present),
        canonical_json(absent),
        canonical_json(field_types),
    )


def make_api16_artifact(entry_page: dict[str, Any], project_root: Path) -> dict[str, Any]:
    page_meta = entry_page["page_meta"]
    retrieved_ms = int(page_meta["retrieved_at_ms"])
    retrieved_at = datetime.fromtimestamp(retrieved_ms / 1000, tz=UTC).isoformat(timespec="milliseconds")
    return {
        "source_family": "kra_openapi",
        "source_role": "primary",
        "public_dataset_id": API16_DATASET_ID,
        "dataset_name": API16_DATASET_NAME,
        "endpoint": API16_ENDPOINT,
        "operation": API16_OPERATION,
        "attempt_id": entry_page["attempt_id"],
        "request_params_json": canonical_json(entry_page["params"]),
        "source_url_without_key": page_meta["source_url_without_key"],
        "collected_at_utc": retrieved_at,
        "http_status_code": int(page_meta["status_code"]),
        "content_type": str(page_meta.get("content_type") or "application/json;charset=UTF-8"),
        "raw_relative_path": entry_page["relative_path"],
        "response_bytes": len(entry_page["bytes"]),
        "sha256": entry_page["sha256"],
        "parser_version": PARSER_VERSION,
    }


def make_profile_artifact(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_family": "kra_openapi",
        "source_role": "primary",
        "public_dataset_id": API42_DATASET_ID,
        "dataset_name": API42_DATASET_NAME,
        "endpoint": API42_ENDPOINT,
        "operation": API42_OPERATION,
        "attempt_id": profile["attempt_id"],
        "request_params_json": canonical_json(profile["public_params"]),
        "source_url_without_key": API42_ENDPOINT,
        "collected_at_utc": profile["observed_at_utc"],
        "http_status_code": profile["http_status"],
        "content_type": profile["content_type"],
        "raw_relative_path": profile["response_relative_path"],
        "response_bytes": len(profile["response_bytes"]),
        "sha256": profile["response_sha256"],
        "parser_version": "jeju-api42-current-profile-followup-v1",
    }


ARTIFACT_VALUE_COLUMNS = (
    "source_family", "source_role", "public_dataset_id", "dataset_name", "endpoint", "operation",
    "attempt_id", "request_params_json", "source_url_without_key", "collected_at_utc",
    "http_status_code", "content_type", "raw_relative_path", "response_bytes", "sha256",
    "parser_version",
)


def ensure_artifact(
    conn: sqlite3.Connection, artifact: dict[str, Any], created_at_utc: str,
) -> tuple[int, bool]:
    existing = conn.execute(
        "SELECT source_artifact_id," + ",".join(ARTIFACT_VALUE_COLUMNS) +
        ",created_at_utc FROM source_artifacts WHERE raw_relative_path=?",
        (artifact["raw_relative_path"],),
    ).fetchall()
    if len(existing) > 1:
        raise ValueError("Multiple source artifacts already use the same raw response path")
    if existing:
        row = existing[0]
        if tuple(row[column] for column in ARTIFACT_VALUE_COLUMNS) != tuple(artifact[column] for column in ARTIFACT_VALUE_COLUMNS):
            raise ValueError("An existing source artifact at the same path differs from frozen source metadata")
        return int(row["source_artifact_id"]), False
    columns = (*ARTIFACT_VALUE_COLUMNS, "created_at_utc")
    values = tuple(artifact[column] for column in ARTIFACT_VALUE_COLUMNS) + (created_at_utc,)
    placeholders = ",".join("?" for _ in columns)
    cursor = conn.execute(
        "INSERT INTO source_artifacts(" + ",".join(columns) + ") VALUES(" + placeholders + ")",
        values,
    )
    return int(cursor.lastrowid), True


def ensure_api_record(
    conn: sqlite3.Connection,
    artifact_id: int,
    record_index: int,
    record_type: str,
    natural_key: str | None,
    payload_json: str,
) -> tuple[int, bool]:
    digest = sha256_bytes(payload_json.encode("utf-8"))
    existing = conn.execute(
        """SELECT api_record_id,record_type,natural_key,payload_json,payload_sha256
           FROM api_records WHERE source_artifact_id=? AND record_index=?""",
        (artifact_id, record_index),
    ).fetchone()
    expected = (record_type, natural_key, payload_json, digest)
    if existing:
        observed = tuple(existing[key] for key in (
            "record_type", "natural_key", "payload_json", "payload_sha256",
        ))
        if observed != expected:
            raise ValueError("An existing API record at the same artifact item differs from frozen source")
        return int(existing["api_record_id"]), False
    cursor = conn.execute(
        """INSERT INTO api_records(
               source_artifact_id,record_index,record_type,natural_key,payload_json,payload_sha256)
           VALUES(?,?,?,?,?,?)""",
        (artifact_id, record_index, record_type, natural_key, payload_json, digest),
    )
    return int(cursor.lastrowid), True


def ensure_profile_observation(
    conn: sqlite3.Connection, profile: dict[str, Any], api_record_id: int,
) -> bool:
    n = profile["normalized"]
    expected = (
        api_record_id, profile["horse_id"], profile["observed_at_utc"], profile["observed_kst_date"],
        n["horse_name_raw"], n["birth_date_raw"], n["age_raw"], n["breed_label_raw"],
        n["sex_raw"], n["color_raw"], n["production_country_raw"],
    )
    existing = conn.execute(
        """SELECT api_record_id,horse_id,observed_at_utc,observed_kst_date,horse_name_raw,
                  birth_date_raw,age_raw,breed_label_raw,sex_raw,color_raw,production_country_raw
           FROM horse_profile_observations WHERE api_record_id=?""",
        (api_record_id,),
    ).fetchone()
    same_time = conn.execute(
        "SELECT api_record_id FROM horse_profile_observations WHERE horse_id=? AND observed_at_utc=?",
        (profile["horse_id"], profile["observed_at_utc"]),
    ).fetchone()
    if existing:
        if tuple(existing) != expected or same_time is None or int(same_time[0]) != api_record_id:
            raise ValueError("An existing API42 profile observation differs from this validated profile")
        return False
    if same_time is not None:
        raise ValueError("A different profile record already uses this horse ID and observation timestamp")
    conn.execute(
        """INSERT INTO horse_profile_observations(
               api_record_id,horse_id,observed_at_utc,observed_kst_date,horse_name_raw,birth_date_raw,
               age_raw,breed_label_raw,sex_raw,color_raw,production_country_raw)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        expected,
    )
    return True


def ensure_api42_breed_evidence(
    conn: sqlite3.Connection, profile: dict[str, Any], artifact_id: int, api_record_id: int,
) -> bool:
    expected = (
        profile["horse_id"], None, profile["normalized"]["breed_label_raw"],
        "API42_1 current profile breed", artifact_id, api_record_id,
        "profile_retrieval_time",
        "Current API42_1 profile breed observed at " + profile["observed_at_utc"] +
        "; the source does not provide a historical effective date.",
    )
    existing = conn.execute(
        """SELECT horse_id,observed_event_date,breed_label_raw,evidence_kind,
                  source_artifact_id,api_record_id,timing_basis,notes
           FROM breed_evidence WHERE api_record_id=?""",
        (api_record_id,),
    ).fetchall()
    if existing:
        if len(existing) != 1 or tuple(existing[0]) != expected:
            raise ValueError("An existing API42 profile breed evidence row differs from frozen input")
        return False
    conn.execute(
        """INSERT INTO breed_evidence(
               horse_id,observed_event_date,breed_label_raw,evidence_kind,source_artifact_id,
               api_record_id,timing_basis,notes)
           VALUES(?,?,?,?,?,?,?,?)""",
        expected,
    )
    return True


def ensure_medical_row(
    conn: sqlite3.Connection, entry: dict[str, Any], artifact_id: int, api_record_id: int,
) -> bool:
    expected = (
        api_record_id, artifact_id, entry["source_row_no"],
        *source_tuple(entry),
    )
    names = (
        "api_record_id", "source_artifact_id", "source_row_no", "clinic_date", "horse_id",
        "meet_raw", "clinic_date_raw", "hr_name_raw", "hr_no_raw", "hospi_name_raw",
        "ill_name1_raw", "ill_name2_raw", "part_raw", "raw_key_presence_json",
        "raw_key_absence_json", "raw_field_types_json",
    )
    existing = conn.execute(
        "SELECT " + ",".join(names) + " FROM medical_api_rows WHERE api_record_id=?",
        (api_record_id,),
    ).fetchone()
    item_location = conn.execute(
        "SELECT api_record_id FROM medical_api_rows WHERE source_artifact_id=? AND source_row_no=?",
        (artifact_id, entry["source_row_no"]),
    ).fetchone()
    if existing:
        if tuple(existing) != expected or item_location is None or int(item_location[0]) != api_record_id:
            raise ValueError("An existing normalized API16 row differs from frozen source")
        return False
    if item_location is not None:
        raise ValueError("An API16 source artifact/item is already linked to another normalized row")
    conn.execute(
        "INSERT INTO medical_api_rows(" + ",".join(names) + ") VALUES(" +
        ",".join("?" for _ in names) + ")",
        expected,
    )
    return True


def build_slots(conn: sqlite3.Connection) -> int:
    count = 0
    rows = conn.execute(
        """SELECT r.medical_api_row_id,r.api_record_id,r.source_artifact_id,r.source_row_no,
                  r.horse_id,r.clinic_date,r.ill_name1_raw,r.ill_name2_raw
           FROM medical_api_rows AS r ORDER BY r.source_artifact_id,r.source_row_no"""
    ).fetchall()
    for row in rows:
        for ordinal, (kind, raw) in enumerate((
            ("illName1", row["ill_name1_raw"]), ("illName2", row["ill_name2_raw"]),
        ), start=1):
            normalized = None if raw is None or raw in {"", "-"} else raw
            digest = sha256_bytes(raw.encode("utf-8")) if raw is not None else None
            expected = (
                row["medical_api_row_id"], row["api_record_id"], row["source_artifact_id"],
                row["source_row_no"], row["horse_id"], row["clinic_date"], ordinal,
                kind, raw, normalized, digest,
            )
            existing = conn.execute(
                """SELECT medical_api_row_id,api_record_id,source_artifact_id,source_row_no,
                          horse_id,clinic_date,source_slot_ordinal,source_slot_kind,
                          raw_diagnosis_text,normalized_diagnosis_text,raw_text_sha256
                   FROM medical_api_diagnosis_slots
                   WHERE api_record_id=? AND source_slot_ordinal=?""",
                (row["api_record_id"], ordinal),
            ).fetchone()
            if existing:
                if tuple(existing) != expected:
                    raise ValueError("An existing API16 diagnosis slot differs from its source row")
                continue
            conn.execute(
                """INSERT INTO medical_api_diagnosis_slots(
                       medical_api_row_id,api_record_id,source_artifact_id,source_row_no,horse_id,
                       clinic_date,source_slot_ordinal,source_slot_kind,raw_diagnosis_text,
                       normalized_diagnosis_text,raw_text_sha256)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                expected,
            )
            count += 1
    return count


def make_dynamic_dictionary_schema(dictionary: dict[str, Any]) -> list[str]:
    return [dictionary_table_sql(table) for table in dictionary["tables"]]


def ensure_dictionary_tables(
    conn: sqlite3.Connection,
    dictionary: dict[str, Any],
) -> dict[str, int]:
    inserted: dict[str, int] = {}
    for table in dictionary["tables"]:
        name = table["table_name"]
        for row_no, row in enumerate(table["rows"], 1):
            column_names = [field["name"] for field in table["schema"]]
            values: list[Any] = []
            for field in table["schema"]:
                value = row[field["name"]]
                if field["arrow_type"] == "bool" and value is not None:
                    value = int(value)
                values.append(value)
            source_json = canonical_json(row)
            expected_values = (source_json, *values)
            existing = conn.execute(
                'SELECT source_row_json,' + ",".join(f'"{column}"' for column in column_names) +
                f' FROM "{name}" WHERE dictionary_row_no=?',
                (row_no,),
            ).fetchone()
            if existing:
                if tuple(existing) != expected_values:
                    raise ValueError(f"Existing dictionary source row differs: {name}:{row_no}")
                continue
            cols = ("dictionary_row_no", "source_row_json", *column_names)
            placeholders = ",".join("?" for _ in cols)
            quoted_cols = ",".join(f'"{column}"' for column in cols)
            conn.execute(
                f'INSERT INTO "{name}"({quoted_cols}) VALUES({placeholders})',
                (row_no, source_json, *values),
            )
            inserted[name] = inserted.get(name, 0) + 1
        actual = int(conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0])
        if actual != len(table["rows"]):
            raise ValueError(f"Dictionary table has unexpected extra rows: {name}")
    for row in dictionary["output_hash_rows"]:
        expected = (
            row["sha256"], row["response_bytes"], row["row_count"], row["column_schema_json"],
        )
        existing = conn.execute(
            """SELECT sha256,response_bytes,row_count,column_schema_json
               FROM medical_dictionary_output_hashes WHERE file_name=?""",
            (row["file_name"],),
        ).fetchone()
        if existing:
            if tuple(existing) != expected:
                raise ValueError(f"Existing dictionary output metadata differs for {row['file_name']}")
        else:
            conn.execute(
                """INSERT INTO medical_dictionary_output_hashes(
                       file_name,sha256,response_bytes,row_count,column_schema_json)
                   VALUES(?,?,?,?,?)""",
                (row["file_name"], *expected),
            )
    metadata = {
        "dataset": dictionary["manifest"].get("dataset"),
        "manifest_sha256": dictionary["manifest_sha256"],
        "schema_sha256": dictionary["schema_sha256"],
        "generated_at_kst": dictionary["manifest"].get("generated_at_kst"),
        "dictionary_scope_json": canonical_json(dictionary["manifest"].get("dataset_scope", {})),
        "safety_contract_json": canonical_json(dictionary["manifest"].get("safety", {})),
        "table_rows_json": canonical_json({t["table_name"]: len(t["rows"]) for t in dictionary["tables"]}),
    }
    meta_inserted = 0
    for key, value in metadata.items():
        existing = conn.execute(
            "SELECT metadata_value FROM medical_dictionary_metadata WHERE metadata_key=?",
            (key,),
        ).fetchone()
        if existing:
            if existing[0] != value:
                raise ValueError(f"Existing dictionary metadata differs: {key}")
        else:
            conn.execute(
                "INSERT INTO medical_dictionary_metadata(metadata_key,metadata_value) VALUES(?,?)",
                (key, value),
            )
            meta_inserted += 1
    inserted["medical_dictionary_metadata"] = meta_inserted
    return inserted


def ensure_year_and_page_metadata(
    conn: sqlite3.Connection,
    api16: dict[str, Any],
    artifacts_by_path: dict[str, int],
) -> tuple[int, int]:
    year_inserted = 0
    for entry in api16["years"]:
        meta = entry["metadata"]
        expected = (
            meta["status"], int(meta["actual_page_count"]), int(meta["actual_total_rows"]),
            int(meta["rows_matching_requested_year"]), int(meta["rows_after_cutoff"]),
            int(meta["rows_with_unparseable_date"]), meta.get("date_min"), meta.get("date_max"),
            None if meta.get("positive_data_evidence") is None else int(bool(meta["positive_data_evidence"])),
            entry["manifest_sha256"], entry["manifest_json"],
            "retrieval coverage metadata only; empty responses do not establish clinical-event absence",
        )
        existing = conn.execute(
            """SELECT status,actual_page_count,actual_total_rows,rows_matching_requested_year,
                      rows_after_cutoff,rows_with_unparseable_date,date_min_raw,date_max_raw,
                      positive_data_evidence,year_manifest_sha256,year_manifest_json,coverage_interpretation
               FROM medical_api16_year_coverage WHERE year=?""",
            (entry["year"],),
        ).fetchone()
        if existing:
            if tuple(existing) != expected:
                raise ValueError(f"Existing API16 year coverage metadata differs for {entry['year']}")
        else:
            conn.execute(
                """INSERT INTO medical_api16_year_coverage(
                       year,status,actual_page_count,actual_total_rows,rows_matching_requested_year,
                       rows_after_cutoff,rows_with_unparseable_date,date_min_raw,date_max_raw,
                       positive_data_evidence,year_manifest_sha256,year_manifest_json,coverage_interpretation)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (entry["year"], *expected),
            )
            year_inserted += 1
    page_inserted = 0
    for page in api16["pages"]:
        artifact_id = artifacts_by_path[page["relative_path"]]
        expected = (
            page["year"], page["page_no"], len(page["items"]), page["sha256"],
            len(page["bytes"]), canonical_json(page["page_meta"]),
        )
        existing = conn.execute(
            """SELECT year,page_no,source_row_count,response_sha256,response_bytes,page_manifest_json
               FROM medical_api16_page_ledger WHERE source_artifact_id=?""",
            (artifact_id,),
        ).fetchone()
        if existing:
            if tuple(existing) != expected:
                raise ValueError(f"Existing API16 page ledger differs for {page['year']}/{page['page_no']}")
        else:
            conn.execute(
                """INSERT INTO medical_api16_page_ledger(
                       source_artifact_id,year,page_no,source_row_count,response_sha256,response_bytes,page_manifest_json)
                   VALUES(?,?,?,?,?,?,?)""",
                (artifact_id, *expected),
            )
            page_inserted += 1
    return year_inserted, page_inserted


def ensure_load_metadata(conn: sqlite3.Connection, values: dict[str, str]) -> int:
    inserted = 0
    for key, value in values.items():
        existing = conn.execute(
            "SELECT metadata_value FROM medical_api16_load_metadata WHERE metadata_key=?",
            (key,),
        ).fetchone()
        if existing:
            if existing[0] != value:
                raise ValueError(f"Existing API16 load metadata differs: {key}")
        else:
            conn.execute(
                "INSERT INTO medical_api16_load_metadata(metadata_key,metadata_value) VALUES(?,?)",
                (key, value),
            )
            inserted += 1
    return inserted


def schema_columns(conn: sqlite3.Connection, table: str) -> tuple[str, ...]:
    return tuple(str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")'))


def verify_schema(conn: sqlite3.Connection, dictionary: dict[str, Any]) -> None:
    expected_medical = (
        "medical_api_row_id", "api_record_id", "source_artifact_id", "source_row_no",
        "clinic_date", "horse_id", "meet_raw", "clinic_date_raw", "hr_name_raw",
        "hr_no_raw", "hospi_name_raw", "ill_name1_raw", "ill_name2_raw", "part_raw",
        "raw_key_presence_json", "raw_key_absence_json", "raw_field_types_json",
    )
    if schema_columns(conn, "medical_api_rows") != expected_medical:
        raise ValueError("medical_api_rows columns differ from the approved contract")
    view_names = {
        "medical_api_rows_analysis_2026",
        "medical_api_diagnosis_slot_review",
        "medical_api_diagnosis_components",
        "medical_api_diagnosis_explanation_terms",
        "medical_api_diagnosis_explanation_observations",
    }
    objects = sqlite_object_sql(conn)
    for view in view_names:
        if ("view", view) not in objects:
            raise ValueError(f"Expected medical analysis view was not created: {view}")
    for table in dictionary["tables"]:
        name = table["table_name"]
        expected = ("dictionary_row_no", "source_row_json", *(field["name"] for field in table["schema"]))
        if schema_columns(conn, name) != expected:
            raise ValueError(f"Dictionary table columns differ from the frozen Arrow schema: {name}")


def current_rows_by_item(conn: sqlite3.Connection) -> dict[tuple[str, int], int]:
    return {
        (str(row[0]), int(row[1])): int(row[2])
        for row in conn.execute(
            "SELECT source_artifact_id,source_row_no,medical_api_row_id FROM medical_api_rows"
        )
    }


def make_quarantine_report(api16: dict[str, Any], current_ids: set[str], new_ids: set[str], excluded_ids: set[str]) -> dict[str, Any]:
    allowed = current_ids | new_ids
    reasons = Counter()
    records: list[dict[str, Any]] = []
    for entry in api16["raw_source_items"]:
        raw = entry["raw"]
        horse_id = official_horse_id(raw.get("hrNo"))
        raw_date, normalized_date = parse_source_date(raw.get("clinicDate"))
        reason = None
        if raw.get("meet") != "제주":
            reason = "meet_not_jeju_exact"
        elif normalized_date is None:
            reason = "clinic_date_invalid"
        elif horse_id is None:
            reason = "official_horse_id_invalid"
        elif horse_id in excluded_ids:
            reason = "horse_excluded_by_user"
        elif horse_id not in allowed:
            reason = "no_exact_current_jeju_profile"
        if reason:
            reasons[reason] += 1
            records.append({
                "source_artifact_path": entry["source_relative_path"],
                "source_row_no": entry["source_row_no"],
                "clinic_date_raw": raw_date,
                "hr_no_raw": raw_text(raw.get("hrNo")),
                "hr_name_raw": raw_text(raw.get("hrName")),
                "reason": reason,
                "source_item_sha256": sha256_bytes(canonical_json(raw).encode("utf-8")),
            })
    before = Counter()
    for entry in api16["raw_source_items"]:
        raw = entry["raw"]
        horse_id = official_horse_id(raw.get("hrNo"))
        if raw.get("meet") == "제주" and horse_id is not None and horse_id not in current_ids and horse_id not in excluded_ids:
            before[horse_id] += 1
    return {
        "policy": "Raw API page and api_records retain every source item; medical_api_rows requires exact current 제주마 profile ID, exact meet text, valid date, and no exclusion.",
        "raw_source_rows": len(api16["raw_source_items"]),
        "unlinked_before_api42_profile_import": {
            "horse_count": len(before),
            "row_count": sum(before.values()),
            "official_horse_ids": sorted(before),
            "reason": "No exact current 제주마 profile existed in the frozen pre-import database baseline.",
        },
        "quarantined_after_profile_import": {
            "row_count": len(records),
            "by_reason": dict(sorted(reasons.items())),
            "rows": records,
        },
        "quarantine_items_are_not_deleted": True,
    }


def baseline_json_value(value: dict[str, Any]) -> dict[str, Any]:
    output = dict(value)
    output["schema_objects"] = [
        {"type": kind, "name": name, "sql": sql}
        for (kind, name), sql in sorted(value["schema_objects"].items())
    ]
    return output


def frozen_input_hashes(inputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        label: {"sha256": info["sha256"], "bytes": info["bytes"]}
        for label, info in sorted(inputs["frozen"].items())
    }


def count_database(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])


def database_baseline(conn: sqlite3.Connection) -> dict[str, Any]:
    tables = [
        str(row[0]) for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    counts = {}
    for name in tables:
        counts[name] = count_database(conn, name)
    return {
        "schema_objects": sqlite_object_sql(conn),
        "table_counts": counts,
        "profile_rows": count_database(conn, "horse_profile_observations"),
        "api_records": count_database(conn, "api_records"),
        "source_artifacts": count_database(conn, "source_artifacts"),
    }


def query_diagnostic_counts(conn: sqlite3.Connection) -> dict[str, Any]:
    row_count = count_database(conn, "medical_api_rows")
    slots = count_database(conn, "medical_api_diagnosis_slots")
    cutoff = int(conn.execute("SELECT count(*) FROM medical_api_rows_analysis_2026").fetchone()[0])
    safe = conn.execute(
        """SELECT count(*),count(DISTINCT raw_diagnosis_text)
           FROM medical_api_diagnosis_slot_review
           WHERE mapping_disposition='reviewed_exact_phrase_component_metadata_only'"""
    ).fetchone()
    nonblank = conn.execute(
        """SELECT count(*),count(DISTINCT raw_diagnosis_text)
           FROM medical_api_diagnosis_slots
           WHERE normalized_diagnosis_text IS NOT NULL"""
    ).fetchone()
    null_dash = int(conn.execute(
        "SELECT count(*) FROM medical_api_diagnosis_slots WHERE raw_diagnosis_text='-' AND normalized_diagnosis_text IS NULL"
    ).fetchone()[0])
    phrase_dispositions = [
        {"disposition": str(row[0]), "occurrences": int(row[1]), "phrases": int(row[2])}
        for row in conn.execute(
            """SELECT mapping_disposition,count(*),count(DISTINCT raw_diagnosis_text)
               FROM medical_api_diagnosis_slot_review
               GROUP BY mapping_disposition ORDER BY mapping_disposition"""
        )
    ]
    api33_dash = int(conn.execute("SELECT count(*) FROM medical_api33_source_rows WHERE ill_desc='-'").fetchone()[0])
    explanation_described_titles = int(conn.execute(
        """SELECT count(DISTINCT c.target_ill_name)
           FROM medical_api_diagnosis_components AS c
           JOIN medical_explanation_terms AS e ON e.source_title=c.target_ill_name
           WHERE c.mapping_disposition='reviewed_exact_phrase_component_metadata_only'
             AND e.description_present=1 AND e.description_text IS NOT NULL AND e.description_text<>''"""
    ).fetchone()[0])
    api_slot_target_titles = int(conn.execute(
        """SELECT count(DISTINCT target_ill_name)
           FROM medical_api_diagnosis_components
           WHERE mapping_disposition='reviewed_exact_phrase_component_metadata_only'"""
    ).fetchone()[0])
    duplicates = conn.execute(
        """SELECT count(*),coalesce(sum(n),0) FROM (
             SELECT count(*) AS n FROM api_records
             WHERE record_type='medical_api16_clinic'
             GROUP BY payload_sha256 HAVING count(*)>1
           )"""
    ).fetchone()
    same_day_diff_values = conn.execute(
        """SELECT count(*),coalesce(sum(row_count),0) FROM (
             SELECT horse_id,clinic_date,count(*) AS row_count,count(DISTINCT source_item_hash) AS variants
             FROM (
               SELECT r.horse_id,r.clinic_date,ar.payload_sha256 AS source_item_hash
               FROM medical_api_rows r JOIN api_records ar ON ar.api_record_id=r.api_record_id
             )
             GROUP BY horse_id,clinic_date HAVING variants>1
           )"""
    ).fetchone()
    query_plan = [
        str(row[3]) for row in conn.execute(
            "EXPLAIN QUERY PLAN SELECT count(*) FROM medical_api_rows_analysis_2026"
        )
    ]
    return {
        "medical_api_rows": row_count,
        "medical_api_rows_analysis_2026": cutoff,
        "medical_api_diagnosis_slots": slots,
        "nonblank_slot_occurrences": int(nonblank[0]),
        "nonblank_unique_phrases": int(nonblank[1]),
        "reviewed_safe_slot_occurrences": int(safe[0]),
        "reviewed_safe_unique_phrases": int(safe[1]),
        "all_nonblank_phrases_have_reviewed_safe_exact_mapping": (
            int(nonblank[0]) == int(safe[0]) and int(nonblank[1]) == int(safe[1])
        ),
        "slot_review_dispositions": phrase_dispositions,
        "unknown_dash_slots_preserved_raw_and_normalized_null": null_dash,
        "api33_source_rows_with_ill_desc_dash": api33_dash,
        "unique_api_slot_target_titles": api_slot_target_titles,
        "api_slot_target_titles_with_captured_text": explanation_described_titles,
        "api_slot_target_titles_without_captured_text": api_slot_target_titles - explanation_described_titles,
        "repeated_exact_api_item_hash_groups": int(duplicates[0]),
        "repeated_exact_api_item_rows_in_groups": int(duplicates[1]),
        "same_horse_date_groups_with_different_payloads": int(same_day_diff_values[0]),
        "rows_in_same_horse_date_different_payload_groups": int(same_day_diff_values[1]),
        "analysis_view_query_plan": query_plan,
        "raw_row_grain_unchanged_by_glossary_joins": cutoff == int(conn.execute(
            "SELECT count(DISTINCT medical_api_row_id) FROM medical_api_rows_analysis_2026"
        ).fetchone()[0]),
    }


def insert_all(
    conn: sqlite3.Connection,
    inputs: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        if sha256_file(inputs["db_path"]) != inputs["expected_db_sha256"]:
            raise ValueError("Database SHA-256 changed before BEGIN IMMEDIATE acquired the write lock")
        recheck_frozen_files(inputs["frozen"])
        verify_database_integrity(conn)
        before = database_baseline(conn)
        pre_existing_object_names = set(before["schema_objects"])
        for table_sql in make_dynamic_dictionary_schema(inputs["dictionary"]):
            conn.execute(table_sql)
        execute_sql_file(conn, MIGRATION_PATH)
        verify_schema(conn, inputs["dictionary"])

        now = datetime.now(UTC).isoformat(timespec="milliseconds")
        profile_artifacts_inserted = profile_records_inserted = profiles_inserted = breed_evidence_inserted = 0
        for profile in plan["profiles"]["profiles"]:
            artifact = make_profile_artifact(profile)
            artifact_id, was_inserted = ensure_artifact(conn, artifact, now)
            profile_artifacts_inserted += int(was_inserted)
            record_id, was_inserted = ensure_api_record(
                conn, artifact_id, 1, "horse_profile", profile["horse_id"], profile["payload_json"],
            )
            profile_records_inserted += int(was_inserted)
            profiles_inserted += int(ensure_profile_observation(conn, profile, record_id))
            breed_evidence_inserted += int(ensure_api42_breed_evidence(conn, profile, artifact_id, record_id))

        source_artifacts_inserted = api_records_inserted = medical_rows_inserted = 0
        artifacts_by_path: dict[str, int] = {}
        source_entry_by_item = {
            (entry["source_relative_path"], entry["source_row_no"]): entry
            for entry in inputs["api16"]["raw_source_items"]
        }
        for page in inputs["api16"]["pages"]:
            artifact = make_api16_artifact(page, inputs["project_root"])
            artifact_id, was_inserted = ensure_artifact(conn, artifact, now)
            source_artifacts_inserted += int(was_inserted)
            artifacts_by_path[page["relative_path"]] = artifact_id
            for source_row_no, raw in enumerate(page["items"], 1):
                payload_json = canonical_json(raw)
                record_id, was_inserted = ensure_api_record(
                    conn, artifact_id, source_row_no, "medical_api16_clinic", None, payload_json,
                )
                api_records_inserted += int(was_inserted)
                source_entry = source_entry_by_item[(page["relative_path"], source_row_no)]
                horse_id = official_horse_id(raw.get("hrNo"))
                if (raw.get("meet") == "제주" and source_entry["clinic_date"] is not None
                        and horse_id is not None
                        and horse_id in plan["all_jeju_profile_ids"]
                        and horse_id not in inputs["excluded_ids"]):
                    medical_rows_inserted += int(ensure_medical_row(conn, source_entry, artifact_id, record_id))

        years_inserted, page_ledger_inserted = ensure_year_and_page_metadata(
            conn, inputs["api16"], artifacts_by_path,
        )
        dictionary_inserted = ensure_dictionary_tables(conn, inputs["dictionary"])
        slots_inserted = build_slots(conn)
        load_metadata = {
            "parser_version": PARSER_VERSION,
            "api16_operation": API16_OPERATION,
            "api16_run_manifest_sha256": inputs["api16"]["manifest_sha256"],
            "api16_source_rows": str(inputs["api16"]["source_rows"]),
            "api16_source_pages": str(inputs["api16"]["pages_count"]),
            "api16_analysis_cutoff": ANALYSIS_CUTOFF,
            "api16_profile_linking_policy": "exact official hrNo to current horse_analysis_2026 horse_id where profile_breed_label_raw='제주마'; no name-based matching",
            "api16_part_field_policy": "part is retained as raw API value with captured JSON type; its meaning is unverified and it is not used as an identity",
            "api16_publication_time_policy": "clinicDate is an event date; historical publication time is unverified",
            "api16_coverage_interpretation": "year partitions document successful retrieval only; a zero-row response does not prove historical event absence or endpoint unavailability",
            "dictionary_dataset": inputs["dictionary"]["manifest"].get("dataset", ""),
            "dictionary_manifest_sha256": inputs["dictionary"]["manifest_sha256"],
            "dictionary_safety_policy": "review mappings are provenance metadata; no diagnosis is automatically applied to an event",
            "excluded_ids_json": canonical_json(sorted(inputs["excluded_ids"])),
        }
        load_meta_inserted = ensure_load_metadata(conn, load_metadata)
        all_profile_ids = current_jeju_profile_ids(conn)
        if not plan["new_profile_ids"] <= all_profile_ids:
            raise ValueError("Imported API42 profile rows did not become visible as current 제주마 profiles")
        if not plan["missing_profile_ids_before"] <= plan["new_profile_ids"]:
            raise ValueError("API42 import profiles do not cover the proven pre-import missing-ID set")
        quarantine = make_quarantine_report(
            inputs["api16"], plan["current_jeju_profile_ids_before"],
            plan["new_profile_ids"], inputs["excluded_ids"],
        )
        diagnostics = query_diagnostic_counts(conn)
        if diagnostics["medical_api_diagnosis_slots"] != diagnostics["medical_api_rows"] * 2:
            raise ValueError("The two-slot table does not preserve exactly two API slots per medical row")
        if diagnostics["medical_api_rows_analysis_2026"] != sum(
            1 for entry in inputs["api16"]["raw_source_items"]
            if entry["raw"].get("meet") == "제주"
            and entry["clinic_date"] <= ANALYSIS_CUTOFF
            and official_horse_id(entry["raw"].get("hrNo")) in plan["all_jeju_profile_ids"]
            and official_horse_id(entry["raw"].get("hrNo")) not in inputs["excluded_ids"]
        ):
            raise ValueError("The 2026 analysis view row count differs from exact linked source rows")
        verify_database_integrity(conn)
        after = database_baseline(conn)
        changed_schema_objects = {
            key: (sql, after["schema_objects"].get(key))
            for key, sql in before["schema_objects"].items()
            if after["schema_objects"].get(key) != sql
        }
        if changed_schema_objects:
            raise ValueError(
                "An existing SQLite schema object was removed or modified: "
                f"{sorted(changed_schema_objects)[:10]}"
            )
        if any(after["table_counts"].get(name) != count for name, count in before["table_counts"].items()):
            # Only explicitly approved existing append targets may grow.
            allowed = {"api_records", "source_artifacts", "horse_profile_observations", "breed_evidence"}
            bad = {
                name: (count, after["table_counts"].get(name))
                for name, count in before["table_counts"].items()
                if after["table_counts"].get(name) != count and name not in allowed
            }
            if bad:
                raise ValueError(f"Unrelated existing table counts changed: {bad}")
        new_object_names = set(after["schema_objects"]) - pre_existing_object_names
        expected_new_names = {
            ("table", "medical_api16_year_coverage"),
            ("table", "medical_api16_page_ledger"),
            ("table", "medical_api16_load_metadata"),
            ("table", "medical_api_rows"),
            ("table", "medical_api_diagnosis_slots"),
            ("table", "medical_dictionary_output_hashes"),
            ("table", "medical_dictionary_metadata"),
            ("index", "ix_medical_api_rows_horse_date"),
            ("index", "ix_medical_api_rows_date"),
            ("index", "ix_medical_api_rows_artifact_order"),
            ("index", "ix_medical_api_diagnosis_slots_text_hash"),
            ("index", "ix_medical_phrase_decisions_text_hash"),
            ("index", "ix_medical_phrase_components_text_hash"),
            ("index", "ix_medical_explanation_terms_title"),
            ("index", "ix_medical_explanation_observations_title"),
            ("view", "medical_api_rows_analysis_2026"),
            ("view", "medical_api_diagnosis_slot_review"),
            ("view", "medical_api_diagnosis_components"),
            ("view", "medical_api_diagnosis_explanation_terms"),
            ("view", "medical_api_diagnosis_explanation_observations"),
        }
        expected_new_names |= {
            ("table", table["table_name"]) for table in inputs["dictionary"]["tables"]
        }
        if not new_object_names <= expected_new_names:
            raise ValueError(f"Unexpected SQLite schema objects were added: {sorted(new_object_names-expected_new_names)}")
        conn.commit()
        return {
            "before": baseline_json_value(before),
            "after": baseline_json_value(after),
            "inserted": {
                "api42_source_artifacts": profile_artifacts_inserted,
                "api42_api_records": profile_records_inserted,
                "horse_profile_observations": profiles_inserted,
                "breed_evidence": breed_evidence_inserted,
                "api16_source_artifacts": source_artifacts_inserted,
                "api16_api_records": api_records_inserted,
                "medical_api_rows": medical_rows_inserted,
                "api16_year_coverage_rows": years_inserted,
                "api16_page_ledger_rows": page_ledger_inserted,
                "medical_api_diagnosis_slots": slots_inserted,
                "dictionary_tables_and_metadata": dictionary_inserted,
                "api16_load_metadata": load_meta_inserted,
            },
            "diagnostics": diagnostics,
            "quarantine_report": quarantine,
            "existing_tables_preserved_by_count": sorted(before["table_counts"]),
            "new_schema_objects": [list(item) for item in sorted(new_object_names)],
        }
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def make_dry_run_report(
    conn: sqlite3.Connection,
    inputs: dict[str, Any],
    plan: dict[str, Any],
    db_sha256: str,
) -> dict[str, Any]:
    verify_database_integrity(conn)
    baseline = database_baseline(conn)
    quarantine = make_quarantine_report(
        inputs["api16"], plan["current_jeju_profile_ids_before"],
        plan["new_profile_ids"], inputs["excluded_ids"],
    )
    raw_ids = {
        official_horse_id(entry["raw"].get("hrNo"))
        for entry in inputs["api16"]["raw_source_items"]
        if entry["raw"].get("meet") == "제주"
    }
    raw_ids.discard(None)
    analysis_rows = sum(
        1 for entry in inputs["api16"]["raw_source_items"]
        if entry["raw"].get("meet") == "제주"
        and entry["clinic_date"] <= ANALYSIS_CUTOFF
        and official_horse_id(entry["raw"].get("hrNo")) in (
            plan["current_jeju_profile_ids_before"] | plan["new_profile_ids"]
        )
        and official_horse_id(entry["raw"].get("hrNo")) not in inputs["excluded_ids"]
    )
    linked_rows = sum(
        1 for entry in inputs["api16"]["raw_source_items"]
        if entry["raw"].get("meet") == "제주"
        and official_horse_id(entry["raw"].get("hrNo")) in (
            plan["current_jeju_profile_ids_before"] | plan["new_profile_ids"]
        )
        and official_horse_id(entry["raw"].get("hrNo")) not in inputs["excluded_ids"]
    )
    return {
        "status": "dry_run_only",
        "production_database_modified": False,
        "frozen_input_hashes": frozen_input_hashes(inputs),
        "database": {
            "path": str(inputs["db_path"]),
            "sha256": db_sha256,
            "baseline_table_counts": baseline["table_counts"],
            "existing_profile_observation_rows": baseline["profile_rows"],
            "existing_api_record_rows": baseline["api_records"],
            "existing_source_artifact_rows": baseline["source_artifacts"],
        },
        "inputs": {
            "api16_run_manifest_sha256": inputs["api16"]["manifest_sha256"],
            "api16_source_rows": inputs["api16"]["source_rows"],
            "api16_source_pages": inputs["api16"]["pages_count"],
            "api16_post_cutoff_rows": inputs["api16"]["after_cutoff_rows"],
            "dictionary_manifest_sha256": inputs["dictionary"]["manifest_sha256"],
            "dictionary_parquet_rows": {t["table_name"]: len(t["rows"]) for t in inputs["dictionary"]["tables"]},
            "api42_collection_manifest_sha256": plan["profiles"]["manifest_sha256"],
            "api42_target_manifest_sha256": plan["profiles"]["target_manifest_sha256"],
            "api42_validated_rows_sha256": plan["profiles"]["rows_sha256"],
            "api42_profile_count": len(plan["profiles"]["profiles"]),
            "api42_exact_missing_profile_ids": len(plan["missing_profile_ids_before"]),
            "clinic_source_rows_per_profile_verified": plan["profiles"]["source_refs_validated"],
        },
        "planned_counts": {
            "api16_api_records_all_source_items": inputs["api16"]["source_rows"],
            "medical_api_rows_exact_profile_linked": linked_rows,
            "medical_api_rows_analysis_2026_cutoff": analysis_rows,
            "api42_horse_profile_observations": len(plan["missing_profile_ids_before"]),
            "api42_collection_target_profiles": len(plan["profiles"]["profiles"]),
            "api16_source_artifacts": inputs["api16"]["pages_count"],
            "api42_source_artifacts": len(plan["missing_profile_ids_before"]),
            "medical_api_diagnosis_slots": linked_rows * 2,
        },
        "quarantine": quarantine,
    }


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--profile-collection-dir", type=Path, required=True)
    parser.add_argument("--source-run-dir", type=Path)
    parser.add_argument("--dictionary-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-db-sha256")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.apply and not args.expected_db_sha256:
        raise SystemExit("--apply requires --expected-db-sha256 for a locked baseline check")
    if args.expected_db_sha256 and not re.fullmatch(r"[0-9a-f]{64}", args.expected_db_sha256):
        raise SystemExit("--expected-db-sha256 must be a lowercase 64-character SHA-256")
    if args.db.resolve(strict=False).name == "horse_racing.sqlite3":
        raise SystemExit("Refusing the shared operating horse_racing.sqlite3 database")
    if not args.db.is_file():
        raise SystemExit("The explicit SQLite database path must already exist; the loader will not create a DB")
    if not MIGRATION_PATH.is_file():
        raise SystemExit(f"Migration file is missing: {MIGRATION_PATH}")
    if not args.output_dir.is_absolute():
        raise SystemExit("--output-dir must be an explicit absolute path")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    inputs = load_inputs(args)
    dictionary_schema_sql = "-- Generated from the root-pinned dictionary/schema.json; bool is stored as 0/1 INTEGER.\n"
    dictionary_schema_sql += "\n".join(make_dynamic_dictionary_schema(inputs["dictionary"])) + "\n"
    atomic_write_text(args.output_dir / "20261002_add_medical_dictionary_tables.sql", dictionary_schema_sql)
    inputs["db_path"] = args.db.resolve(strict=True)
    db_sha = sha256_file(inputs["db_path"])
    if args.expected_db_sha256 and db_sha != args.expected_db_sha256:
        raise SystemExit("Database SHA-256 does not match --expected-db-sha256")
    with open_readonly(inputs["db_path"]) as read_conn:
        plan = ensure_profile_candidate_links(read_conn, inputs)
        if not args.apply:
            report = make_dry_run_report(read_conn, inputs, plan, db_sha)
            report_path = args.output_dir / "dry_run_report.json"
            atomic_write_json(report_path, report)
            atomic_write_json(args.output_dir / "unlinked_quarantine_report.json", report["quarantine"])
            print(json.dumps({"status": report["status"], "report": str(report_path),
                              "planned_counts": report["planned_counts"]}, ensure_ascii=False))
            return 0
    if not args.apply:
        return 0

    inputs["expected_db_sha256"] = args.expected_db_sha256
    # Reopening in read-write mode is explicit and only happens with --apply.
    with open_readwrite_existing(inputs["db_path"]) as write_conn:
        report = insert_all(write_conn, inputs, plan)
    post_sha = sha256_file(inputs["db_path"])
    native_db = (inputs["project_root"] / "jeju/data/jeju_native_core.sqlite3").resolve(strict=False)
    is_production_database = inputs["db_path"].resolve(strict=False) == native_db
    result = {
        "status": "applied_to_production_database" if is_production_database else "applied_to_explicit_database_copy",
        "production_database_modified": is_production_database,
        "frozen_input_hashes": frozen_input_hashes(inputs),
        "database": {
            "path": str(inputs["db_path"]),
            "before_sha256": args.expected_db_sha256,
            "after_sha256": post_sha,
        },
        "api16_run_manifest_sha256": inputs["api16"]["manifest_sha256"],
        "dictionary_manifest_sha256": inputs["dictionary"]["manifest_sha256"],
        "api42_collection_manifest_sha256": plan["profiles"]["manifest_sha256"],
        "api42_target_manifest_sha256": plan["profiles"]["target_manifest_sha256"],
        "result": report,
    }
    atomic_write_json(args.output_dir / "apply_report.json", result)
    atomic_write_json(args.output_dir / "unlinked_quarantine_report.json", report["quarantine_report"])
    print(json.dumps({"status": result["status"], "report": str(args.output_dir / "apply_report.json"),
                      "inserted": report["inserted"], "diagnostics": report["diagnostics"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
