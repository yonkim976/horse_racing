"""Validate and optionally append the hash-pinned full API78 equipment export.

The default run is read-only with respect to the core DuckDB and core manifest.
The only write mode requires both --apply and --confirm-core-append.
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
import tempfile
from typing import Any, Iterable

import duckdb


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
DEFAULT_INVENTORY = OUT.parent / "inventory"
CORE_DIR = ROOT / "thoroughbred/data/core_api_2010_20260929_v1"
CORE_DB = CORE_DIR / "thoroughbred_core.duckdb"
CORE_MANIFEST = CORE_DIR / "manifest.json"
BACKUP_DIR = CORE_DIR / "backups/20261002_before_equipment_api78_full"
EXPECTED_BASE_DB_SHA256 = "d4be443d8ee3a43b11d30add89a84a197d93dc57510e7266fa45969a913cd77e"
SOURCE_MANIFEST_NAME = "equipment_api78_full_v1"
SOURCE_ENDPOINT = "/API78/chulmainfo"
API78_AVAILABILITY = "retrospective_api78_observation_not_verified_pre_race"
PHYSICAL_WEAR = "unknown"
CHANGE_RE = re.compile(r"^(.+?)\s*([+-])\s*$")
EXPECTED_EXPORTS = {
    "api78_runner_records.csv", "api78_selected_batches.csv", "api78_selected_pages.csv",
    "api78_batch_inventory.csv", "api78_source_document_inventory.csv",
    "api78_explicit_change_marks.csv", "api78_core_runner_ledger.csv",
    "api78_unresolved_runner_identity_ledger.csv", "api78_missing_core_date_meets.csv",
    "api78_coverage_by_meet_year.csv", "api78_capture_queue_status.csv",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def safe_file(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve(strict=True)
    if not candidate.is_relative_to(root.resolve(strict=True)) or not candidate.is_file():
        raise ValueError(f"input path is outside the repository or not a file: {relative}")
    return candidate


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def bool_value(value: str) -> bool:
    if value.casefold() in {"true", "1", "yes"}:
        return True
    if value.casefold() in {"false", "0", "no", ""}:
        return False
    raise ValueError(f"invalid boolean CSV value: {value!r}")


def int_or_none(value: str) -> int | None:
    return int(value) if value not in ("", None) else None


def int_required(value: str, label: str) -> int:
    result = int_or_none(value)
    if result is None:
        raise ValueError(f"missing required integer {label}")
    return result


def text_or_none(value: str) -> str | None:
    return value if value != "" else None


def date8(value: str) -> str:
    text = value.strip()
    match = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일?", text)
    if not match:
        match = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", text)
    if match:
        year, month, day = map(int, match.groups())
        return f"{year:04d}{month:02d}{day:02d}"
    digits = "".join(re.findall(r"\d", text))
    if len(digits) < 8:
        raise ValueError(f"invalid event date: {value!r}")
    return digits[:8]


def catalog_objects(connection: duckdb.DuckDBPyConnection) -> dict[str, str]:
    rows = connection.execute("""SELECT table_name, table_type
                                  FROM information_schema.tables
                                  WHERE table_catalog=current_database() AND table_schema='main'""").fetchall()
    return {str(name): str(kind) for name, kind in rows}


def number(value: object) -> int | None:
    match = re.search(r"(\d+)", "" if value is None else str(value).strip())
    return int(match.group(1)) if match else None


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def rows_from_csv(path: Path, required_columns: set[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = required_columns - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
        return list(reader)


def verify_frozen_inputs(inventory: Path) -> tuple[dict[str, list[dict[str, str]]], dict[str, Any], dict[str, str]]:
    summary_path = inventory / "snapshot_summary.json"
    summary = load_json(summary_path)
    manifest_path = inventory / "frozen_export_manifest.csv"
    expected_manifest_rel = summary.get("frozen_export_manifest_path")
    expected_manifest_sha = summary.get("frozen_export_manifest_sha256")
    if not expected_manifest_rel or not expected_manifest_sha:
        raise ValueError("snapshot summary lacks a frozen export manifest hash pin")
    if Path(expected_manifest_rel).resolve() != manifest_path.resolve():
        raise ValueError("snapshot summary points at a different frozen export manifest")
    manifest_sha = sha256_file(manifest_path)
    if expected_manifest_sha and manifest_sha != expected_manifest_sha:
        raise ValueError("frozen export manifest SHA-256 does not match snapshot summary")
    manifest_rows = read_csv(manifest_path)
    pins = {row["file_name"]: row for row in manifest_rows}
    if set(pins) != EXPECTED_EXPORTS:
        raise ValueError(f"frozen export file set differs: expected {sorted(EXPECTED_EXPORTS)}, found {sorted(pins)}")
    data: dict[str, list[dict[str, str]]] = {}
    hashes: dict[str, str] = {"frozen_export_manifest.csv": manifest_sha}
    for name in sorted(EXPECTED_EXPORTS):
        path = inventory / name
        actual = sha256_file(path)
        if actual != pins[name]["sha256"]:
            raise ValueError(f"CSV hash does not match frozen export manifest: {name}")
        rows = read_csv(path)
        if len(rows) != int(pins[name]["row_count"]):
            raise ValueError(f"CSV row count does not match frozen export manifest: {name}")
        data[name] = rows
        hashes[name] = actual

    for path_key, hash_key in (
        ("historical_capture_manifest_snapshot_path", "historical_capture_manifest_snapshot_sha256"),
        ("historical_targets_manifest_snapshot_path", "historical_targets_manifest_snapshot_sha256"),
    ):
        relative = summary.get(path_key)
        expected = summary.get(hash_key)
        if not relative or not expected:
            raise ValueError(f"snapshot summary lacks frozen input pin {path_key}")
        frozen_path = safe_file(ROOT, relative)
        if sha256_file(frozen_path) != expected:
            raise ValueError(f"frozen source manifest hash mismatch: {relative}")
        hashes[relative] = expected

    for path in (OUT / "load_equipment_api78_full.py", OUT / "schema.sql"):
        hashes[str(path.relative_to(ROOT))] = sha256_file(path)

    missing = data["api78_missing_core_date_meets.csv"]
    if missing:
        raise ValueError(f"API78 coverage has {len(missing)} missing core date-meets; full-scope gate failed")
    return data, summary, hashes


def verify_raw_pages(data: dict[str, list[dict[str, str]]]) -> dict[str, Path]:
    page_rows = data["api78_selected_pages.csv"]
    pages_by_ref: dict[str, dict[str, str]] = {}
    raw_by_batch: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    page_paths: dict[str, Path] = {}
    for page in page_rows:
        ref = page["document_ref"]
        if ref in pages_by_ref:
            raise ValueError(f"duplicate selected page document ref: {ref}")
        path = safe_file(ROOT, page["local_path"])
        digest = sha256_file(path)
        if digest != page["sha256"]:
            raise ValueError(f"raw selected page hash mismatch: {page['local_path']}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            items = payload["response"]["body"]["items"]["item"]
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(f"selected page payload is not a valid API78 response: {page['local_path']}: {exc}") from exc
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            raise ValueError(f"selected page item payload is not a list: {page['local_path']}")
        pages_by_ref[ref] = page
        page_paths[ref] = path
        raw_by_batch.setdefault(page["batch_id"], []).extend((int(page["page_no"]), item) for item in items)

    runner_rows = data["api78_runner_records.csv"]
    observed_by_batch: dict[str, list[dict[str, str]]] = {}
    for row in runner_rows:
        page = pages_by_ref.get(row["source_document_ref"])
        if page is None:
            raise ValueError(f"observation references a page outside the selected page set: {row['observation_id']}")
        for field in ("batch_id", "event_date", "meet", "page_no", "source_sha256"):
            expected = page["sha256"] if field == "source_sha256" else page[field]
            if row[field] != expected:
                raise ValueError(f"observation/page provenance mismatch for {row['observation_id']}: {field}")
        observed_by_batch.setdefault(row["batch_id"], []).append(row)

    if set(raw_by_batch) != set(observed_by_batch):
        raise ValueError("raw selected pages and runner export have different batch sets")
    for batch_id, raw_pairs in raw_by_batch.items():
        raw_pairs.sort(key=lambda pair: pair[0])
        rows = sorted(observed_by_batch[batch_id], key=lambda row: int(row["source_index_in_batch"]))
        if len(raw_pairs) != len(rows):
            raise ValueError(f"raw payload/export runner count differs in batch {batch_id}")
        seen: set[tuple[int, int]] = set()
        for index, ((page_no, item), row) in enumerate(zip(raw_pairs, rows), start=1):
            key = (number(item.get("raceNo")) or -1, number(item.get("gtno")) or -1)
            if key in seen:
                raise ValueError(f"duplicate raw runner key in selected batch {batch_id}: {key}")
            seen.add(key)
            if int(row["source_index_in_batch"]) != index or int(row["page_no"]) != page_no:
                raise ValueError(f"raw item order/page differs from exported observation {row['observation_id']}")
            if (row["race_no"], row["horse_no"]) != tuple(map(str, key)):
                raise ValueError(f"raw runner key differs from export: {row['observation_id']}")
            if row["api_horse_name_raw"] != ("" if item.get("hrnm") is None else str(item.get("hrnm")).strip()):
                raise ValueError(f"raw horse name differs from export: {row['observation_id']}")
            field_present = "equipCrs" in item
            is_null = field_present and item.get("equipCrs") is None
            value_state = "field_missing" if not field_present else "null" if is_null else "blank" if not str(item.get("equipCrs", "")).strip() else "nonblank"
            raw_value = None if not field_present or is_null else str(item["equipCrs"])
            if bool_value(row["equipment_field_present"]) != field_present or bool_value(row["equipment_is_null"]) != is_null:
                raise ValueError(f"raw equipment presence/null flags differ: {row['observation_id']}")
            if row["equipment_value_state"] != value_state or row["equipment_raw"] != ("" if raw_value is None else raw_value):
                raise ValueError(f"raw equipment value/state differs: {row['observation_id']}")
    batches = {row["batch_id"]: row for row in data["api78_selected_batches.csv"]}
    if set(raw_by_batch) != set(batches):
        raise ValueError("selected batch inventory differs from selected raw page batch set")
    page_counts: dict[str, list[int]] = {}
    for page in page_rows:
        page_counts.setdefault(page["batch_id"], []).append(int(page["page_no"]))
    for batch_id, batch in batches.items():
        expected_pages = int(batch["page_count"])
        actual_pages = sorted(page_counts.get(batch_id, []))
        if actual_pages != list(range(1, expected_pages + 1)):
            raise ValueError(f"selected page sequence is incomplete for {batch_id}: {actual_pages}")
        if len(observed_by_batch[batch_id]) != int(batch["runner_rows_exported"]):
            raise ValueError(f"selected runner count differs from batch metadata: {batch_id}")
        if len(raw_by_batch[batch_id]) != int(batch["api_total_count"]):
            raise ValueError(f"selected raw item count differs from API totalCount: {batch_id}")
    return page_paths


def token_rows_for_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    token_rows: list[dict[str, Any]] = []
    for obs in observations:
        if obs["equipment_value_state"] != "nonblank":
            continue
        for position, token in enumerate(obs["equipment_raw"].split(","), start=1):
            stripped = token.strip()
            if not stripped:
                continue
            match = CHANGE_RE.fullmatch(stripped)
            if match and match.group(1).strip():
                equipment_name = match.group(1).strip()
                mark = "new" if match.group(2) == "+" else "removed"
            elif stripped in {"-", "+"}:
                # A lone dash/plus is a source placeholder, never an equipment action.
                continue
            else:
                equipment_name = stripped
                mark = "unmarked"
            token_rows.append({
                "observation_id": obs["observation_id"], "token_position": position,
                "token_raw": token, "equipment_name_raw": equipment_name, "mark_status": mark,
            })
    return token_rows


def verify_identity_and_coverage(data: dict[str, list[dict[str, str]]], runner_rows: list[dict[str, Any]]) -> dict[str, Any]:
    db = duckdb.connect(str(CORE_DB), read_only=True)
    try:
        core_rows = db.execute("""SELECT source_meet, result_date, result_race_no, horse_program_no_raw,
                                         horse_id_raw, horse_name_raw
                                  FROM confirmed_runners
                                  WHERE source_meet IN ('1','3','4')
                                    AND result_date BETWEEN '20100101' AND '20260929'""").fetchall()
        manifest_count = db.execute("SELECT count(*) FROM source_manifests").fetchone()[0]
        base_objects = catalog_objects(db)
        source_row_count = db.execute("SELECT count(*) FROM source_manifests WHERE name=?", [SOURCE_MANIFEST_NAME]).fetchone()[0]
    finally:
        db.close()
    core_keys = {(str(a), str(b), str(c), str(d), str(e)) for a, b, c, d, e, _ in core_rows}
    if len(core_rows) != 330465 or len(core_keys) != len(core_rows):
        raise ValueError(f"core five-key uniqueness/cardinality gate failed: rows={len(core_rows)}, keys={len(core_keys)}")
    ledger = data["api78_core_runner_ledger.csv"]
    ledger_keys = {(r["core_meet"], date8(r["core_event_date"]), r["core_race_no"], r["core_horse_no"], r["core_horse_id"]) for r in ledger}
    if len(ledger) != 330465 or ledger_keys != core_keys:
        raise ValueError(f"core coverage ledger does not exactly cover confirmed_runners: ledger={len(ledger)}, keys={len(ledger_keys)}")
    linked_keys: list[tuple[str, str, str, str, str]] = []
    linked_statuses = {"linked_op_id_corroborated", "linked_core_key_name_only"}
    for row in runner_rows:
        linked_id = row["linked_core_horse_id"]
        if row["link_status"] in linked_statuses:
            key = (row["meet"], date8(row["event_date"]), row["race_no"], row["horse_no"], linked_id)
            if not linked_id or key not in core_keys:
                raise ValueError(f"linked API78 identity is not an exact confirmed_runner five-key: {row['observation_id']}")
            if (row["linked_core_meet"], date8(row["linked_core_event_date"]), row["linked_core_race_no"], row["linked_core_horse_no"]) != key[:4]:
                raise ValueError(f"linked API78 identity event key differs from source row: {row['observation_id']}")
            linked_keys.append(key)
        elif linked_id or any(row[k] for k in ("linked_core_meet", "linked_core_event_date", "linked_core_race_no", "linked_core_horse_no")):
            raise ValueError(f"unresolved API78 row carries linked core identity: {row['observation_id']}")
    if len(set(linked_keys)) != len(linked_keys):
        raise ValueError("duplicate API78 linked core five-key would multiply coverage joins")
    missing_dates = data["api78_missing_core_date_meets.csv"]
    target_batch_rows = [r for r in data["api78_selected_batches.csv"] if bool_value(r["core_date_meet_target"])]
    batch_targets = {(r["event_date"], r["meet"]) for r in target_batch_rows}
    if len(batch_targets) != len(target_batch_rows):
        raise ValueError("multiple canonical selected batches exist for a core date-meet")
    core_dates = {(k[1], k[0]) for k in core_keys}
    if batch_targets != core_dates:
        raise ValueError(f"selected complete API78 date-meet set differs from core scope: batches={len(batch_targets)}, core={len(core_dates)}")
    unresolved = {r["observation_id"] for r in runner_rows if r["link_status"] == "unresolved"}
    unresolved_export = {r["observation_id"] for r in data["api78_unresolved_runner_identity_ledger.csv"]}
    if unresolved != unresolved_export:
        raise ValueError("unresolved identity ledger does not exactly partition unresolved observations")
    collisions = {name for name in (
        "equipment_api78_source_documents", "equipment_api78_capture_batches", "equipment_api78_capture_pages",
        "equipment_api78_card_observations", "equipment_api78_core_runner_ledger", "equipment_api78_card_tokens",
        "equipment_api78_identity_conflicts", "equipment_api78_latest_card_observations",
        "equipment_api78_active_declared", "equipment_core_coverage", "equipment_declared_union_fallback",
    ) if name in base_objects}
    expected_object_names = {
        "equipment_api78_source_documents", "equipment_api78_capture_batches", "equipment_api78_capture_pages",
        "equipment_api78_card_observations", "equipment_api78_core_runner_ledger", "equipment_api78_card_tokens",
        "equipment_api78_identity_conflicts", "equipment_api78_latest_card_observations",
        "equipment_api78_active_declared", "equipment_core_coverage", "equipment_declared_union_fallback",
    }
    if manifest_count not in {21, 22}:
        raise ValueError(f"expected 21 baseline or 22 post-append source manifest entries, found {manifest_count}")
    if (manifest_count == 21 and (collisions or source_row_count != 0)) or (manifest_count == 22 and (collisions != expected_object_names or source_row_count != 1)):
        raise ValueError("API78 catalog objects and source manifest count are inconsistent")
    return {
        "core_confirmed_runner_rows": len(core_rows), "core_unique_five_key_rows": len(core_keys),
        "source_manifest_rows_before_append": manifest_count, "linked_observation_rows": len(linked_keys),
        "unique_linked_core_five_keys": len(set(linked_keys)), "unresolved_observation_rows": len(unresolved),
        "complete_core_date_meets": len(core_dates), "missing_core_date_meets": len(missing_dates),
        "existing_api78_objects": sorted(collisions),
        "source_manifest_rows": manifest_count,
    }


def source_inventory_rows(data: dict[str, list[dict[str, str]]], selected_refs: set[str]) -> list[dict[str, Any]]:
    rows = []
    for index, r in enumerate(data["api78_source_document_inventory.csv"], start=1):
        ref = r["document_ref"]
        if r["local_path"]:
            candidate = (ROOT / r["local_path"]).resolve(strict=False)
            if not candidate.is_relative_to(ROOT.resolve(strict=True)):
                raise ValueError(f"source document path escapes repository root: {r['local_path']}")
        rows.append({
            "source_inventory_row_id": f"doc-{index:06d}-{hashlib.sha256(ref.encode()).hexdigest()[:12]}",
            "source_kind": r["source_kind"], "source_document_ref": ref,
            "source_document_id": r["document_id"] or ref, "source_document_id_raw": r["document_id"],
            "ingestion_run_id": text_or_none(r["ingestion_run_id"]), "event_date": text_or_none(r["event_date"]),
            "meet": text_or_none(r["meet"]), "page_no": int_or_none(r["page_no"]), "raw_path": text_or_none(r["local_path"]),
            "sha256_expected": text_or_none(r["sha256_expected"]), "raw_sha256": text_or_none(r["sha256_actual"]),
            "file_hash_valid": bool_value(r["file_hash_valid"]), "payload_valid": bool_value(r["payload_valid"]),
            "page_total_count": int_or_none(r["page_total_count"]), "page_size": int_or_none(r["page_size"]),
            "item_count": int_or_none(r["item_count"]), "requested_at_ms": int_or_none(r["requested_at_ms"]),
            "retrieved_at_ms": int_or_none(r["retrieved_at_ms"]), "http_status_code": int_or_none(r["http_status_code"]),
            "response_bytes": int_or_none(r["response_bytes"]), "run_source": text_or_none(r["run_source"]),
            "run_data_type": text_or_none(r["run_data_type"]), "run_started_at_ms": int_or_none(r["run_started_at_ms"]),
            "run_completed_at_ms": int_or_none(r["run_completed_at_ms"]), "ingestion_status": r["run_status"],
            "request_identity_basis": r["request_identity_basis"], "observed_time_basis": r["capture_time_basis"],
            "validation_error": r["validation_error"], "selected_for_canonical_snapshot": ref in selected_refs,
        })
    return rows


def build_rows(data: dict[str, list[dict[str, str]]], page_paths: dict[str, Path]) -> dict[str, list[dict[str, Any]]]:
    page_by_ref = {r["document_ref"]: r for r in data["api78_selected_pages.csv"]}
    page_by_batch = {r["batch_id"]: r for r in data["api78_selected_pages.csv"]}
    selected_refs = set(page_by_ref)
    batches = []
    for r in data["api78_selected_batches.csv"]:
        if not bool_value(r["selected"]) or not bool_value(r["complete_payload"]):
            raise ValueError(f"selected batch is not complete: {r['batch_id']}")
        batches.append({
            "batch_id": r["batch_id"], "meet": r["meet"], "race_date": date8(r["event_date"]),
            "ingestion_run_id": text_or_none(r["ingestion_run_id"]), "ingestion_status": r["ingestion_run_status"],
            "source_document_refs": r["source_document_refs"], "is_complete": True,
            "page_count": int_required(r["page_count"], "page_count"), "page_numbers": r["page_numbers"],
            "api_total_count": int_or_none(r["api_total_count"]), "source_runner_count": int_required(r["observed_runner_count"], "observed_runner_count"),
            "runner_rows_exported": int_required(r["runner_rows_exported"], "runner_rows_exported"),
            "equipment_field_missing_count": int_required(r["equipment_field_missing_count"], "field_missing_count"),
            "equipment_null_count": int_required(r["equipment_null_count"], "equipment_null_count"),
            "equipment_blank_count": int_required(r["equipment_blank_count"], "equipment_blank_count"),
            "equipment_nonblank_count": int_required(r["equipment_nonblank_count"], "equipment_nonblank_count"),
            "observed_empty_count": int_required(r["equipment_blank_count"], "equipment_blank_count"),
            "observed_value_count": int_required(r["equipment_nonblank_count"], "equipment_nonblank_count"),
            "observed_unknown_count": int_required(r["equipment_field_missing_count"], "field_missing_count") + int_required(r["equipment_null_count"], "equipment_null_count"),
            "explicit_added_mark_count": int_required(r["explicit_added_mark_count"], "added_mark_count"),
            "explicit_removed_mark_count": int_required(r["explicit_removed_mark_count"], "removed_mark_count"),
            "linked_op_id_corroborated_count": int_required(r["linked_op_id_corroborated_count"], "op_link_count"),
            "linked_core_key_name_only_count": int_required(r["linked_core_key_name_only_count"], "core_name_link_count"),
            "unresolved_identity_count": int_required(r["unresolved_identity_count"], "unresolved_count"),
            "validation_errors": r["validation_errors"], "requested_at_ms": int_or_none(r["requested_at_ms"]),
            "requested_at_kst": r["requested_at_kst"], "retrieved_at_ms": int_or_none(r["retrieved_at_ms"]),
            "retrieved_at_kst": r["retrieved_at_kst"], "capture_time_basis": r["capture_time_basis"],
            "selection_rule": "latest_hash_and_page_verified_complete_capture_per_date_meet",
        })

    pages = []
    for r in data["api78_selected_pages.csv"]:
        pages.append({
            "source_document_ref": r["document_ref"], "batch_id": r["batch_id"], "meet": r["meet"],
            "event_date": date8(r["event_date"]), "source_kind": r["source_kind"],
            "source_document_id": r["document_id"] or r["document_ref"], "ingestion_run_id": text_or_none(r["ingestion_run_id"]),
            "ingestion_run_status": r["ingestion_run_status"], "page_no": int_required(r["page_no"], "page_no"),
            "raw_path": r["local_path"], "raw_sha256": r["sha256"], "requested_at_ms": int_or_none(r["requested_at_ms"]),
            "requested_at_kst": r["requested_at_kst"], "retrieved_at_ms": int_required(r["retrieved_at_ms"], "retrieved_at_ms"),
            "retrieved_at_kst": r["retrieved_at_kst"], "http_status_code": int_required(r["http_status_code"], "http_status_code"),
            "response_bytes": int_required(r["response_bytes"], "response_bytes"),
            "request_identity_basis": r["request_identity_basis"], "observed_time_basis": r["capture_time_basis"],
            "total_count": None, "item_count": 0,
        })
    # Fill page payload counts directly from independently hash-verified raw files.
    for page in pages:
        payload = json.loads(page_paths[page["source_document_ref"]].read_text(encoding="utf-8"))
        items = payload["response"]["body"]["items"]["item"]
        page["item_count"] = len(items) if isinstance(items, list) else 1
        total = payload["response"]["body"].get("totalCount")
        page["total_count"] = number(total)

    observations = []
    conflicts = []
    for r in data["api78_runner_records.csv"]:
        page = page_by_ref[r["source_document_ref"]]
        if r["source_kind"] != page["source_kind"]:
            raise ValueError(f"source kind differs from selected page: {r['observation_id']}")
        value_state = r["equipment_value_state"]
        mapped_state = {"field_missing": "field_missing", "null": "json_null", "blank": "observed_empty", "nonblank": "observed_value"}.get(value_state)
        if mapped_state is None:
            raise ValueError(f"unknown equipment value state: {value_state}")
        raw = r["equipment_raw"]
        if value_state == "nonblank" and raw.strip() == "-":
            mapped_state = "dash_placeholder"
        evidence = {
            "link_status": r["link_status"], "link_method": r["link_method"], "link_reason": r["link_reason"],
            "core_key_candidate_count": r["core_key_candidate_count"], "core_key_name_match_count": r["core_key_name_match_count"],
            "operational_key_candidate_count": r["operational_key_candidate_count"],
            "operational_key_name_match_count": r["operational_key_name_match_count"],
            "api_horse_name_normalized": r["api_horse_name_normalized"],
            "core_horse_name_normalized_candidate": r["core_horse_name_normalized_candidate"],
            "operational_horse_id_candidate": r["operational_horse_id_candidate"],
        }
        obs = {
            "observation_id": r["observation_id"], "batch_id": r["batch_id"], "source_kind": r["source_kind"],
            "source_document_ref": r["source_document_ref"], "source_document_id": r["source_document_id"] or r["source_document_ref"],
            "ingestion_run_id": text_or_none(r["ingestion_run_id"]), "ingestion_run_status": r["ingestion_run_status"],
            "source_sha256": r["source_sha256"], "page_no": int_required(r["page_no"], "page_no"),
            "source_index_in_batch": int_required(r["source_index_in_batch"], "source_index_in_batch"),
            "event_date": date8(r["event_date"]), "meet": r["meet"], "race_no": r["race_no"], "horse_no": r["horse_no"],
            "api_horse_name_raw": r["api_horse_name_raw"], "api_horse_name_normalized": r["api_horse_name_normalized"],
            "equipment_raw": raw if value_state not in {"field_missing", "null"} else None,
            "equipment_field_present": bool_value(r["equipment_field_present"]), "equipment_is_null": bool_value(r["equipment_is_null"]),
            "equipment_value_state": value_state, "equipment_field_state": mapped_state,
            "source_endpoint": SOURCE_ENDPOINT, "capture_retrieved_at_ms": int_required(r["capture_retrieved_at_ms"], "retrieved_at_ms"),
            "capture_retrieved_at_kst": r["capture_retrieved_at_kst"], "observed_time_basis": page["capture_time_basis"],
            "availability_status": API78_AVAILABILITY, "physical_wear_status": PHYSICAL_WEAR,
            "link_status": r["link_status"], "link_method": text_or_none(r["link_method"]), "link_reason": text_or_none(r["link_reason"]),
            "core_key_candidate_count": int_required(r["core_key_candidate_count"], "core_key_candidate_count"),
            "core_key_name_match_count": int_required(r["core_key_name_match_count"], "core_key_name_match_count"),
            "operational_key_candidate_count": int_required(r["operational_key_candidate_count"], "operational_key_candidate_count"),
            "operational_key_name_match_count": int_required(r["operational_key_name_match_count"], "operational_key_name_match_count"),
            "core_horse_name_raw_candidate": text_or_none(r["core_horse_name_raw_candidate"]),
            "core_horse_name_normalized_candidate": text_or_none(r["core_horse_name_normalized_candidate"]),
            "operational_horse_name_raw_candidate": text_or_none(r["operational_horse_name_raw_candidate"]),
            "operational_horse_id_candidate": text_or_none(r["operational_horse_id_candidate"]),
            "linked_core_meet": text_or_none(r["linked_core_meet"]),
            "linked_core_event_date": date8(r["linked_core_event_date"]) if r["linked_core_event_date"] else None,
            "linked_core_race_no": text_or_none(r["linked_core_race_no"]), "linked_core_horse_no": text_or_none(r["linked_core_horse_no"]),
            "linked_core_horse_id": text_or_none(r["linked_core_horse_id"]), "source_document_path": page["local_path"],
            "identity_match_evidence": canonical_json(evidence),
        }
        observations.append(obs)
        if r["link_status"] not in {"linked_op_id_corroborated", "linked_core_key_name_only"}:
            reason = r["link_reason"]
            conflict_class = "not_in_confirmed_core" if reason == "no_core_runner_at_exact_meet_date_race_program" else "identity_unresolved_or_conflicting"
            conflicts.append({
                "observation_id": r["observation_id"], "meet": r["meet"], "event_date": date8(r["event_date"]),
                "race_no": r["race_no"], "horse_no": r["horse_no"], "api_horse_name_raw": r["api_horse_name_raw"],
                "link_status": r["link_status"], "link_method": text_or_none(r["link_method"]), "link_reason": text_or_none(reason),
                "conflict_class": conflict_class, "core_key_candidate_count": int_required(r["core_key_candidate_count"], "core candidates"),
                "core_key_name_match_count": int_required(r["core_key_name_match_count"], "core name matches"),
                "operational_key_candidate_count": int_required(r["operational_key_candidate_count"], "operational candidates"),
                "operational_key_name_match_count": int_required(r["operational_key_name_match_count"], "operational name matches"),
                "operational_horse_id_candidate": text_or_none(r["operational_horse_id_candidate"]),
                "identity_match_evidence": canonical_json(evidence), "source_document_ref": r["source_document_ref"],
                "source_document_path": page["local_path"], "source_sha256": r["source_sha256"],
            })

    ledger = []
    for r in data["api78_core_runner_ledger.csv"]:
        ledger.append({
            "core_meet": r["core_meet"], "core_event_date": date8(r["core_event_date"]), "core_race_no": r["core_race_no"],
            "core_horse_no": r["core_horse_no"], "core_horse_id": r["core_horse_id"],
            "core_horse_name_raw": r["core_horse_name_raw"], "core_horse_name_normalized": r["core_horse_name_normalized"],
            "equipment_observation_state": r["equipment_observation_state"], "selected_batch_id": text_or_none(r["selected_batch_id"]),
            "selected_batch_source_kind": text_or_none(r["selected_batch_source_kind"]),
            "selected_batch_run_status": r["selected_batch_run_status"],
            "api78_observation_id_candidate": text_or_none(r["api78_observation_id_candidate"]),
            "api78_link_status_candidate": text_or_none(r["api78_link_status_candidate"]),
            "api78_link_reason_candidate": text_or_none(r["api78_link_reason_candidate"]),
            "api78_horse_name_raw_candidate": text_or_none(r["api78_horse_name_raw_candidate"]),
            "api78_equipment_raw_candidate": text_or_none(r["api78_equipment_raw_candidate"]),
            "api78_equipment_value_state_candidate": text_or_none(r["api78_equipment_value_state_candidate"]),
            "api78_source_document_ref_candidate": text_or_none(r["api78_source_document_ref_candidate"]),
            "api78_source_sha256_candidate": text_or_none(r["api78_source_sha256_candidate"]),
        })
    tokens = token_rows_for_observations(observations)
    expected_marks = data["api78_explicit_change_marks.csv"]
    generated_marks = {
        (t["observation_id"], t["token_position"], "added" if t["mark_status"] == "new" else "removed", t["token_raw"], t["equipment_name_raw"])
        for t in tokens if t["mark_status"] in {"new", "removed"}
    }
    export_marks = {
        (r["observation_id"], int(r["position"]), r["change_type"], r["token_raw"], r["equipment_name_raw"])
        for r in expected_marks
    }
    if generated_marks != export_marks:
        raise ValueError(f"literal +/− mark CSV differs from token parser: generated={len(generated_marks)}, exported={len(export_marks)}")
    source_docs = source_inventory_rows(data, selected_refs)
    return {
        "documents": source_docs, "batches": batches, "pages": pages, "observations": observations,
        "ledger": ledger, "tokens": tokens, "conflicts": conflicts,
    }


TABLE_COLUMNS = {
    "equipment_api78_source_documents": ["source_inventory_row_id","source_kind","source_document_ref","source_document_id","source_document_id_raw","ingestion_run_id","event_date","meet","page_no","raw_path","sha256_expected","raw_sha256","file_hash_valid","payload_valid","page_total_count","page_size","item_count","requested_at_ms","retrieved_at_ms","http_status_code","response_bytes","run_source","run_data_type","run_started_at_ms","run_completed_at_ms","ingestion_status","request_identity_basis","observed_time_basis","validation_error","selected_for_canonical_snapshot"],
    "equipment_api78_capture_batches": ["batch_id","meet","race_date","ingestion_run_id","ingestion_status","source_document_refs","is_complete","page_count","page_numbers","api_total_count","source_runner_count","runner_rows_exported","equipment_field_missing_count","equipment_null_count","equipment_blank_count","equipment_nonblank_count","observed_empty_count","observed_value_count","observed_unknown_count","explicit_added_mark_count","explicit_removed_mark_count","linked_op_id_corroborated_count","linked_core_key_name_only_count","unresolved_identity_count","validation_errors","requested_at_ms","requested_at_kst","retrieved_at_ms","retrieved_at_kst","capture_time_basis","selection_rule"],
    "equipment_api78_capture_pages": ["source_document_ref","batch_id","meet","event_date","source_kind","source_document_id","ingestion_run_id","ingestion_run_status","page_no","raw_path","raw_sha256","requested_at_ms","requested_at_kst","retrieved_at_ms","retrieved_at_kst","http_status_code","response_bytes","request_identity_basis","observed_time_basis","total_count","item_count"],
    "equipment_api78_card_observations": ["observation_id","batch_id","source_kind","source_document_ref","source_document_id","ingestion_run_id","ingestion_run_status","source_sha256","page_no","source_index_in_batch","event_date","meet","race_no","horse_no","api_horse_name_raw","api_horse_name_normalized","equipment_raw","equipment_field_present","equipment_is_null","equipment_value_state","equipment_field_state","source_endpoint","capture_retrieved_at_ms","capture_retrieved_at_kst","observed_time_basis","availability_status","physical_wear_status","link_status","link_method","link_reason","core_key_candidate_count","core_key_name_match_count","operational_key_candidate_count","operational_key_name_match_count","core_horse_name_raw_candidate","core_horse_name_normalized_candidate","operational_horse_name_raw_candidate","operational_horse_id_candidate","linked_core_meet","linked_core_event_date","linked_core_race_no","linked_core_horse_no","linked_core_horse_id","source_document_path","identity_match_evidence"],
    "equipment_api78_core_runner_ledger": ["core_meet","core_event_date","core_race_no","core_horse_no","core_horse_id","core_horse_name_raw","core_horse_name_normalized","equipment_observation_state","selected_batch_id","selected_batch_source_kind","selected_batch_run_status","api78_observation_id_candidate","api78_link_status_candidate","api78_link_reason_candidate","api78_horse_name_raw_candidate","api78_equipment_raw_candidate","api78_equipment_value_state_candidate","api78_source_document_ref_candidate","api78_source_sha256_candidate"],
    "equipment_api78_card_tokens": ["observation_id","token_position","token_raw","equipment_name_raw","mark_status"],
    "equipment_api78_identity_conflicts": ["observation_id","meet","event_date","race_no","horse_no","api_horse_name_raw","link_status","link_method","link_reason","conflict_class","core_key_candidate_count","core_key_name_match_count","operational_key_candidate_count","operational_key_name_match_count","operational_horse_id_candidate","identity_match_evidence","source_document_ref","source_document_path","source_sha256"],
}


def tuples_for(rows: list[dict[str, Any]], columns: list[str]) -> list[tuple[Any, ...]]:
    return [tuple(row[column] for column in columns) for row in rows]


def hash_rows(rows: Iterable[tuple[Any, ...]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(canonical_json(row).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def verify_existing(connection: duckdb.DuckDBPyConnection, rows_by_table: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    results = {}
    key_columns = {
        "equipment_api78_source_documents": ["source_inventory_row_id"],
        "equipment_api78_capture_batches": ["batch_id"], "equipment_api78_capture_pages": ["source_document_ref"],
        "equipment_api78_card_observations": ["observation_id"],
        "equipment_api78_core_runner_ledger": ["core_meet","core_event_date","core_race_no","core_horse_no","core_horse_id"],
        "equipment_api78_card_tokens": ["observation_id","token_position"],
        "equipment_api78_identity_conflicts": ["observation_id"],
    }
    for table, rows in rows_by_table.items():
        columns = TABLE_COLUMNS[table]
        keys = key_columns[table]
        expected_rows = sorted(tuples_for(rows, columns), key=lambda row: tuple(str(row[columns.index(k)]) for k in keys))
        actual = connection.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
        actual_rows = sorted(actual, key=lambda row: tuple(str(row[columns.index(k)]) for k in keys))
        if len(expected_rows) != len(actual_rows) or hash_rows(expected_rows) != hash_rows(actual_rows):
            raise ValueError(f"existing table differs from this pinned export: {table}")
        results[table] = {"rows": len(actual_rows), "canonical_rows_sha256": hash_rows(actual_rows)}
    return results


def database_rows_by_table(built: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "equipment_api78_source_documents": built["documents"],
        "equipment_api78_capture_batches": built["batches"],
        "equipment_api78_capture_pages": built["pages"],
        "equipment_api78_card_observations": built["observations"],
        "equipment_api78_core_runner_ledger": built["ledger"],
        "equipment_api78_card_tokens": built["tokens"],
        "equipment_api78_identity_conflicts": built["conflicts"],
    }


def source_manifest_value(rows_by_table: dict[str, list[dict[str, Any]]], hashes: dict[str, str], summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "API78", "endpoint": SOURCE_ENDPOINT, "scope": "20100101..20260929; meets 1,3,4",
        "selection_rule": "latest hash-and-page-verified complete capture per date-meet",
        "availability_status": API78_AVAILABILITY, "physical_wear_status": PHYSICAL_WEAR,
        "historical_prerace_eligibility_verified": False,
        "snapshot_summary": summary,
        "verified_input_sha256": hashes,
        "appended_objects": {table: len(rows) for table, rows in rows_by_table.items()},
        "identity_rule": "exact meet/date/race/program key and normalized name; linked ID comes from confirmed_runners; operational ID corroboration where available",
        "token_rule": "literal comma tokens only; suffix + means new, suffix - means removed, unmarked is declared; no cross-race inference; lone +/- is not an equipment token",
        "interpretation": ["Declared list is not proof of physical wear.", "Null, missing, whitespace, and dash placeholders retain separate states.", "No historical pre-race availability claim is made."],
    }


def proposed_view_counts(built: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    linked_statuses = {"linked_op_id_corroborated", "linked_core_key_name_only"}
    observations = {row["observation_id"]: row for row in built["observations"]}
    api_keys = {
        (row["linked_core_meet"], row["linked_core_event_date"], row["linked_core_race_no"], row["linked_core_horse_no"], row["linked_core_horse_id"])
        for row in built["observations"] if row["link_status"] in linked_statuses
    }
    active_api_count = sum(
        token["mark_status"] != "removed"
        and observations[token["observation_id"]]["link_status"] in linked_statuses
        for token in built["tokens"]
    )
    con = duckdb.connect(str(CORE_DB), read_only=True)
    try:
        fallback_rows = con.execute("""SELECT meet, result_date, race_no, horse_no, horse_id
                                          FROM equipment_score_supplement_active_declared""").fetchall()
    finally:
        con.close()
    fallback_count = sum(
        (str(meet), date8(str(event_date)), str(race), str(program), str(horse_id)) not in api_keys
        for meet, event_date, race, program, horse_id in fallback_rows
    )
    return {"equipment_api78_active_declared": sum(token["mark_status"] != "removed" for token in built["tokens"]),
            "equipment_core_coverage": 330465,
            "equipment_declared_union_fallback": active_api_count + fallback_count}


def dry_run(data: dict[str, list[dict[str, str]]], summary: dict[str, Any], hashes: dict[str, str], built: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    current_db_hash = sha256_file(CORE_DB)
    core_manifest = load_json(CORE_MANIFEST)
    if core_manifest.get("database_sha256") != current_db_hash:
        raise ValueError("core manifest and current database hash disagree")
    links = verify_identity_and_coverage(data, built["observations"])
    is_replay = bool(links["existing_api78_objects"])
    expected_object_names = set(TABLE_COLUMNS) | {
        "equipment_api78_latest_card_observations", "equipment_api78_active_declared",
        "equipment_core_coverage", "equipment_declared_union_fallback",
    }
    if is_replay:
        if current_db_hash == EXPECTED_BASE_DB_SHA256 or set(links["existing_api78_objects"]) != expected_object_names or links["source_manifest_rows"] != 22:
            raise ValueError("existing API78 object set is incomplete or inconsistent with the pinned baseline")
    elif current_db_hash != EXPECTED_BASE_DB_SHA256 or links["source_manifest_rows"] != 21:
        raise ValueError("core database is neither the pinned baseline nor a complete API78 append")
    verification = None
    if is_replay:
        con = duckdb.connect(str(CORE_DB), read_only=True)
        try:
            verification = verify_existing(con, database_rows_by_table(built))
            source_row = con.execute("SELECT json_text FROM source_manifests WHERE name=?", [SOURCE_MANIFEST_NAME]).fetchall()
            expected_source = json.dumps(source_manifest_value(database_rows_by_table(built), hashes, summary), ensure_ascii=False, sort_keys=True)
            if len(source_row) != 1 or source_row[0][0] != expected_source:
                raise ValueError("existing API78 source manifest differs from this frozen export")
            coverage_count = con.execute("SELECT count(*) FROM equipment_core_coverage").fetchone()[0]
            coverage_distinct = con.execute("SELECT count(DISTINCT (meet,result_date,race_no,horse_no,horse_id)) FROM equipment_core_coverage").fetchone()[0]
            if coverage_count != 330465 or coverage_distinct != coverage_count:
                raise ValueError("existing API78 coverage view no longer has one row per core five-key")
        finally:
            con.close()
    else:
        con = duckdb.connect(":memory:")
        try:
            # DuckDB does not allow a bound parameter in ATTACH. This path is
            # a code-pinned repository path, resolved and SQL-quoted here.
            core_path_sql = str(CORE_DB.resolve(strict=True)).replace("'", "''")
            con.execute(f"ATTACH DATABASE '{core_path_sql}' AS core_db (READ_ONLY)")
            con.execute("CREATE VIEW confirmed_runners AS SELECT * FROM core_db.confirmed_runners")
            con.execute("CREATE VIEW equipment_score_supplement AS SELECT * FROM core_db.equipment_score_supplement")
            con.execute("CREATE VIEW equipment_score_supplement_active_declared AS SELECT * FROM core_db.equipment_score_supplement_active_declared")
            schema_sql = (OUT / "schema.sql").read_text(encoding="utf-8")
            for statement in [part.strip() for part in schema_sql.split(";") if part.strip()]:
                con.execute(statement)
            coverage_count = con.execute("SELECT count(*) FROM equipment_core_coverage").fetchone()[0]
            coverage_distinct = con.execute("SELECT count(DISTINCT (meet,result_date,race_no,horse_no,horse_id)) FROM equipment_core_coverage").fetchone()[0]
            if coverage_count != 330465 or coverage_distinct != coverage_count:
                raise ValueError(f"proposed coverage view cardinality invalid: rows={coverage_count}, unique={coverage_distinct}")
        finally:
            con.close()
    tokens = built["tokens"]
    count_by_mark = {mark: sum(row["mark_status"] == mark for row in tokens) for mark in ("unmarked", "new", "removed")}
    table_rows = database_rows_by_table(built)
    view_counts = proposed_view_counts(built)
    proposed_counts = {name: len(rows) for name, rows in table_rows.items()}
    proposed_counts.update({"equipment_api78_latest_card_observations": len(built["observations"]), **view_counts})
    return {
        "status": "dry_run_replay_passed" if is_replay else "dry_run_passed", "applied": False, "idempotent_replay": is_replay,
        "core_database": str(CORE_DB.relative_to(ROOT)), "core_database_sha256_before": EXPECTED_BASE_DB_SHA256,
        "inventory_snapshot_at_kst": summary.get("historical_manifest_snapshot_at_kst"),
        "source_hashes": hashes, "identity_coverage": links,
        "existing_table_verification": verification if is_replay else None,
        "row_counts": {table: len(rows) for table, rows in built.items()},
        "token_counts_by_mark_status": count_by_mark,
        "coverage_view_rows": 330465,
        "proposed_objects": [{"name": name, "type": "BASE TABLE" if name in TABLE_COLUMNS else "VIEW", "rows": proposed_counts[name]} for name in (
            *TABLE_COLUMNS.keys(), "equipment_api78_latest_card_observations", "equipment_api78_active_declared", "equipment_core_coverage", "equipment_declared_union_fallback")],
        "core_manifest_plan": {"append_source_manifest": SOURCE_MANIFEST_NAME, "backup_directory": str(BACKUP_DIR.relative_to(ROOT)), "core_manifest_update": "append-only inputs/load; preserve existing fields"},
        "safety_notes": ["Dry-run does not write the core database or core manifest.", "API78 availability is retrospective; pre-race eligibility is unverified.", "Declared tokens do not establish physical wear."],
    }


def insert_rows(connection: duckdb.DuckDBPyConnection, table: str, rows: list[dict[str, Any]]) -> None:
    import pyarrow as pa

    columns = TABLE_COLUMNS[table]
    quoted = ", ".join(f'"{column}"' for column in columns)
    sql = f"INSERT INTO {table} ({quoted}) SELECT {quoted} FROM incoming_rows"
    batch_size = 5000
    for start in range(0, len(rows), batch_size):
        incoming = pa.Table.from_pylist([{column: row[column] for column in columns} for row in rows[start:start + batch_size]])
        connection.register("incoming_rows", incoming)
        try:
            connection.execute(sql)
        finally:
            connection.unregister("incoming_rows")


def apply(data: dict[str, list[dict[str, str]]], hashes: dict[str, str], summary: dict[str, Any], built: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    manifest_before_bytes = CORE_MANIFEST.read_bytes()
    manifest_before = json.loads(manifest_before_bytes)
    if sha256_file(CORE_DB) != EXPECTED_BASE_DB_SHA256 or manifest_before.get("database_sha256") != EXPECTED_BASE_DB_SHA256:
        raise ValueError("core changed after dry-run baseline; refusing append")
    if BACKUP_DIR.exists():
        raise ValueError(f"backup directory already exists; refusing to overwrite it: {BACKUP_DIR}")
    BACKUP_DIR.mkdir(parents=True)
    backup_db, backup_manifest = BACKUP_DIR / CORE_DB.name, BACKUP_DIR / CORE_MANIFEST.name
    shutil.copy2(CORE_DB, backup_db)
    shutil.copy2(CORE_MANIFEST, backup_manifest)
    if sha256_file(backup_db) != EXPECTED_BASE_DB_SHA256 or sha256_file(backup_manifest) != hashlib.sha256(manifest_before_bytes).hexdigest():
        raise ValueError("paired pre-append backup hash verification failed")

    con = duckdb.connect(str(CORE_DB), read_only=False)
    committed = False
    try:
        objects = catalog_objects(con)
        expected_objects = {**{name: "BASE TABLE" for name in TABLE_COLUMNS},
            "equipment_api78_latest_card_observations": "VIEW", "equipment_api78_active_declared": "VIEW",
            "equipment_core_coverage": "VIEW", "equipment_declared_union_fallback": "VIEW"}
        present = {name: objects[name] for name in expected_objects if name in objects}
        if present:
            if present != expected_objects:
                raise ValueError(f"partial or type-mismatched API78 object set: {present}")
            prior = con.execute("SELECT json_text FROM source_manifests WHERE name=?", [SOURCE_MANIFEST_NAME]).fetchall()
            expected_source = json.dumps(source_manifest_value(database_rows_by_table(built), hashes, summary), ensure_ascii=False, sort_keys=True)
            if len(prior) != 1 or prior[0][0] != expected_source:
                raise ValueError("existing API78 source manifest differs from this frozen export")
            verified = verify_existing(con, database_rows_by_table(built))
            return {"status": "idempotent_replay", "applied": False, "existing_table_verification": verified}

        source_manifest = source_manifest_value(database_rows_by_table(built), hashes, summary)
        source_manifest_text = json.dumps(source_manifest, ensure_ascii=False, sort_keys=True)
        con.execute("BEGIN TRANSACTION")
        for statement in [part.strip() for part in (OUT / "schema.sql").read_text(encoding="utf-8").split(";") if part.strip()]:
            con.execute(statement)
        mapping = {
            "equipment_api78_source_documents": built["documents"], "equipment_api78_capture_batches": built["batches"],
            "equipment_api78_capture_pages": built["pages"], "equipment_api78_card_observations": built["observations"],
            "equipment_api78_core_runner_ledger": built["ledger"], "equipment_api78_card_tokens": built["tokens"],
            "equipment_api78_identity_conflicts": built["conflicts"],
        }
        for table, rows in mapping.items():
            insert_rows(con, table, rows)
        if con.execute("SELECT count(*) FROM equipment_core_coverage").fetchone()[0] != 330465:
            raise ValueError("coverage view failed the 330465-row pre-commit cardinality gate")
        actual_union_count = con.execute("SELECT count(*) FROM equipment_declared_union_fallback").fetchone()[0]
        if con.execute("SELECT count(*) FROM equipment_api78_card_observations WHERE availability_status<>? OR physical_wear_status<>?", [API78_AVAILABILITY, PHYSICAL_WEAR]).fetchone()[0]:
            raise ValueError("API78 status fields do not meet the required conservative labels")
        con.execute("INSERT INTO source_manifests(name,json_text) VALUES (?,?)", [SOURCE_MANIFEST_NAME, source_manifest_text])
        after = catalog_objects(con)
        if set(after) != set(objects) | set(expected_objects):
            raise ValueError("database catalog changed beyond the 11 declared API78 objects")
        con.execute("COMMIT")
        committed = True
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        con.close()
        raise
    con.close()

    try:
        new_db_hash = sha256_file(CORE_DB)
        updated = json.loads(json.dumps(manifest_before))
        updated["database_sha256"] = new_db_hash
        inputs = updated.setdefault("input_files", [])
        existing = {row.get("path") for row in inputs if isinstance(row, dict)}
        for name, table in (
            ("api78_runner_records.csv", "equipment_api78_card_observations"),
            ("api78_selected_batches.csv", "equipment_api78_capture_batches"),
            ("api78_selected_pages.csv", "equipment_api78_capture_pages"),
            ("api78_source_document_inventory.csv", "equipment_api78_source_documents"),
            ("api78_core_runner_ledger.csv", "equipment_api78_core_runner_ledger"),
        ):
            rel = f"thoroughbred/research/20261002_equipment_full_v1/inventory/{name}"
            if rel not in existing:
                inputs.append({"table": table, "path": rel, "sha256": hashes[name], "rows": len(data[name])})
        updated.setdefault("table_and_view_counts", {}).update({
            **{name: len(rows) for name, rows in {
                "equipment_api78_source_documents": built["documents"], "equipment_api78_capture_batches": built["batches"],
                "equipment_api78_capture_pages": built["pages"], "equipment_api78_card_observations": built["observations"],
                "equipment_api78_core_runner_ledger": built["ledger"], "equipment_api78_card_tokens": built["tokens"],
                "equipment_api78_identity_conflicts": built["conflicts"],
            }.items()},
            "equipment_api78_latest_card_observations": len(built["observations"]),
            "equipment_api78_active_declared": sum(t["mark_status"] != "removed" for t in built["tokens"]),
            "equipment_core_coverage": 330465,
            "equipment_declared_union_fallback": actual_union_count,
            "source_manifests": int(updated.get("table_and_view_counts", {}).get("source_manifests", 21)) + 1,
        })
        applied_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        loads = updated.setdefault("supplement_loads", [])
        if any(row.get("name") == SOURCE_MANIFEST_NAME for row in loads if isinstance(row, dict)):
            raise ValueError("core manifest already contains this API78 load entry")
        load_entry = {
            "name": SOURCE_MANIFEST_NAME, "applied_at_utc": applied_at,
            "baseline_database_sha256": EXPECTED_BASE_DB_SHA256, "database_sha256_after": new_db_hash,
            "backup_database": str(backup_db.relative_to(ROOT)), "backup_manifest": str(backup_manifest.relative_to(ROOT)),
            "source_manifest_name": SOURCE_MANIFEST_NAME, "observation_rows": len(built["observations"]),
            "token_rows": len(built["tokens"]), "identity_conflict_rows": len(built["conflicts"]),
            "core_runner_coverage_rows": len(built["ledger"]), "source_hashes": hashes,
        }
        loads.append(load_entry)
        write_json_atomic(CORE_MANIFEST, updated)
        if load_json(CORE_MANIFEST).get("database_sha256") != new_db_hash:
            raise ValueError("updated core manifest failed database hash readback")
        return {"status": "applied", "applied": True, **load_entry}
    except Exception:
        if committed:
            shutil.copy2(backup_db, CORE_DB)
            shutil.copy2(backup_manifest, CORE_MANIFEST)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory-dir", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--apply", action="store_true", help="append after completed dry-run review")
    parser.add_argument("--confirm-core-append", action="store_true", help="second explicit opt-in for the core write path")
    args = parser.parse_args()
    if args.apply != args.confirm_core_append:
        parser.error("core writes require both --apply and --confirm-core-append")
    inventory = args.inventory_dir.resolve(strict=True)
    if not inventory.is_relative_to(ROOT.resolve(strict=True)):
        parser.error("inventory directory must remain inside this repository")
    data, summary, hashes = verify_frozen_inputs(inventory)
    page_paths = verify_raw_pages(data)
    built = build_rows(data, page_paths)
    links = verify_identity_and_coverage(data, built["observations"])
    if args.apply:
        report = apply(data, hashes, summary, built)
        report["source_hashes"] = hashes
        write_json_atomic(OUT / "load_manifest.json", report)
    else:
        report = dry_run(data, summary, hashes, built)
        report["identity_coverage"] = links
        write_json_atomic(OUT / "dry_run_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
