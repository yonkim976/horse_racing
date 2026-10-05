"""Validate the normalized trial dataset against all archived API source rows."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from build_dataset import (
    HERE,
    SOURCE_API,
    SOURCE_ENDPOINT,
    SOURCE_ROOT,
    is_missing_identifier,
    json_items,
)


PARTICIPANTS_PATH = HERE / "participants.csv"
SESSIONS_PATH = HERE / "sessions.csv"
UNIDENTIFIED_PATH = HERE / "unidentified_participants.csv"
MANIFEST_PATH = HERE / "source_manifest.json"
VALIDATION_PATH = HERE / "validation.json"
EXPECTED = {
    "source_file_count": 34,
    "participant_row_count": 61_777,
    "session_count": 6_199,
    "source_meet_date_count": 1_633,
    "unidentified_horse_id_row_count": 104,
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csv_cell(value: Any) -> str:
    return "" if value is None else str(value)


def validate() -> dict[str, Any]:
    for path in (PARTICIPANTS_PATH, SESSIONS_PATH, UNIDENTIFIED_PATH, MANIFEST_PATH):
        if not path.is_file():
            raise FileNotFoundError(path)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    participants = read_csv(PARTICIPANTS_PATH)
    sessions = read_csv(SESSIONS_PATH)
    unidentified = read_csv(UNIDENTIFIED_PATH)
    source_by_id: dict[str, tuple[dict[str, Any], dict[str, Any], int]] = {}
    input_files = sorted(SOURCE_ROOT.glob("*/meet_*.json"))
    source_labels: Counter[str] = Counter()
    source_rows_by_meet: Counter[str] = Counter()
    source_missing_ids_by_meet: Counter[str] = Counter()
    source_files_by_year: Counter[int] = Counter()
    source_meet_dates: set[tuple[int, str]] = set()
    recomputed_sessions: dict[tuple[int, str, str], dict[str, Any]] = {}
    raw_api_fields: set[str] = set()
    missing_id_source_rows: set[str] = set()
    date_values: list[str] = []
    raw_schema_grade_fields: set[str] = set()
    source_hashes: dict[str, str] = {}

    for path in input_files:
        relative_source = path.relative_to(HERE.parents[2]).as_posix()
        # HERE.parents[2] is the repository root (the research directory is nested three levels down).
        try:
            year = int(path.parent.name)
            request_meet = int(path.stem.removeprefix("meet_"))
        except ValueError as exc:
            raise ValueError(f"Unexpected source path: {path}") from exc
        raw_bytes = path.read_bytes()
        payload = json.loads(raw_bytes)
        header, source_items = json_items(payload, path)
        digest = file_sha256(path)
        source_hashes[relative_source] = digest
        source_files_by_year[year] += 1
        source_rows_by_meet[str(request_meet)] += len(source_items)
        manifest_item = next((entry for entry in manifest["source_files"]
                              if entry["source_file"] == relative_source), None)
        if manifest_item is None:
            raise AssertionError(f"Missing source manifest row: {relative_source}")
        if manifest_item["source_file_sha256"] != digest:
            raise AssertionError(f"Source hash mismatch in manifest: {relative_source}")
        if manifest_item["source_item_count"] != len(source_items):
            raise AssertionError(f"Source item count mismatch in manifest: {relative_source}")

        for item_index, item in enumerate(source_items):
            participant_id = f"{relative_source}#item={item_index}"
            source_by_id[participant_id] = (item, header, request_meet)
            raw_api_fields.update(item)
            if any("grade" in name.lower() for name in item):
                raw_schema_grade_fields.update(name for name in item if "grade" in name.lower())
            raw_date = str(item.get("trainDate"))
            date_values.append(raw_date)
            source_meet_dates.add((request_meet, raw_date))
            source_labels[str(item.get("meet"))] += 1
            missing_id = is_missing_identifier(item.get("hrNo"))
            if missing_id:
                missing_id_source_rows.add(participant_id)
                source_missing_ids_by_meet[str(request_meet)] += 1
            trial_no = str(item.get("trainNo"))
            key = (request_meet, raw_date, trial_no)
            group = recomputed_sessions.setdefault(key, {
                "participant_rows": 0,
                "missing_horse_id_rows": 0,
                "api_meet_label": item.get("meet"),
                "source_file": relative_source,
            })
            if group["api_meet_label"] != item.get("meet"):
                raise AssertionError(f"Conflicting meet labels in source session {key}")
            group["participant_rows"] += 1
            group["missing_horse_id_rows"] += int(missing_id)

    participant_by_id: dict[str, dict[str, str]] = {}
    duplicate_ids: list[str] = []
    for row in participants:
        key = row["participant_row_id"]
        if key in participant_by_id:
            duplicate_ids.append(key)
        participant_by_id[key] = row
    if duplicate_ids:
        raise AssertionError(f"Duplicate participant IDs: {duplicate_ids[:3]}")
    if set(participant_by_id) != set(source_by_id):
        raise AssertionError(
            f"Participant/source row IDs differ: missing={len(set(source_by_id)-set(participant_by_id))}, "
            f"unexpected={len(set(participant_by_id)-set(source_by_id))}"
        )

    if not participants:
        raise AssertionError("Participant file is empty")
    if len(manifest.get("source_files", [])) != len(input_files):
        raise AssertionError("Source manifest contains an unexpected number of files")
    participant_headers = list(participants[0])
    if "grade" in participant_headers:
        raise AssertionError("No grade field should be synthesized")
    if "venue" in participant_headers:
        raise AssertionError("No physical venue should be inferred")

    for participant_id, (source_item, source_header, request_meet) in source_by_id.items():
        row = participant_by_id[participant_id]
        raw_record = json.loads(row["source_record_json"])
        if raw_record != source_item:
            raise AssertionError(f"Raw source record changed at {participant_id}")
        source_path = row["source_file"]
        if row["source_file_sha256"] != source_hashes[source_path]:
            raise AssertionError(f"Source provenance hash mismatch at {participant_id}")
        if row["source_api_service"] != SOURCE_API or row["source_endpoint"] != SOURCE_ENDPOINT:
            raise AssertionError(f"API provenance mismatch at {participant_id}")
        if int(row["source_meet_query"]) != request_meet:
            raise AssertionError(f"Request meet provenance mismatch at {participant_id}")
        if row["source_result_code"] != str(source_header.get("resultCode", "")):
            raise AssertionError(f"API result code mismatch at {participant_id}")
        if int(row["source_item_index"]) != int(participant_id.rsplit("=", 1)[1]):
            raise AssertionError(f"Source array index mismatch at {participant_id}")
        expected_date = str(source_item["trainDate"])
        normalized_date = f"{expected_date[:4]}-{expected_date[4:6]}-{expected_date[6:8]}"
        if row["trial_date"] != normalized_date:
            raise AssertionError(f"Normalized date mismatch at {participant_id}")
        if row["horse_id_missing"] != str(is_missing_identifier(source_item.get("hrNo"))).lower():
            raise AssertionError(f"Horse ID missing flag mismatch at {participant_id}")
        if row["horse_id"] != csv_cell(source_item.get("hrNo")):
            raise AssertionError(f"Horse ID differs from source at {participant_id}")
        if row["api_meet_label"] != csv_cell(source_item.get("meet")):
            raise AssertionError(f"API meet label differs from source at {participant_id}")
        for field, value in source_item.items():
            if row.get(f"api_{field}") != csv_cell(value):
                raise AssertionError(f"Flattened API field differs: {field} at {participant_id}")

    expected_session_ids: set[str] = set()
    for request_meet, raw_date, trial_no in recomputed_sessions:
        expected_session_ids.add(f"meet={request_meet}|date={raw_date}|trial={trial_no}")
    session_ids = [row["trial_session_id"] for row in sessions]
    if len(session_ids) != len(set(session_ids)) or set(session_ids) != expected_session_ids:
        raise AssertionError("Session IDs are duplicated, missing, or unexpected")
    session_by_id = {row["trial_session_id"]: row for row in sessions}
    for (request_meet, raw_date, trial_no), group in recomputed_sessions.items():
        session_id = f"meet={request_meet}|date={raw_date}|trial={trial_no}"
        row = session_by_id[session_id]
        if int(row["participant_rows"]) != group["participant_rows"]:
            raise AssertionError(f"Participant count mismatch for {session_id}")
        if int(row["missing_horse_id_rows"]) != group["missing_horse_id_rows"]:
            raise AssertionError(f"Unidentified count mismatch for {session_id}")
        if row["api_meet_label"] != csv_cell(group["api_meet_label"]):
            raise AssertionError(f"Meet label mismatch for {session_id}")
        if row["source_file"] != group["source_file"]:
            raise AssertionError(f"Session provenance mismatch for {session_id}")

    unidentified_by_id = {row["participant_row_id"]: row for row in unidentified}
    expected_unidentified_ids = {
        key for key, source in source_by_id.items() if is_missing_identifier(source[0].get("hrNo"))
    }
    if set(unidentified_by_id) != expected_unidentified_ids:
        raise AssertionError("Unidentified participant extract does not match source rows")
    for key in expected_unidentified_ids:
        if unidentified_by_id[key]["source_record_json"] != participant_by_id[key]["source_record_json"]:
            raise AssertionError(f"Unidentified participant changed in extract: {key}")

    source_file_count = len(input_files)
    participant_count = len(participants)
    session_count = len(sessions)
    meet_date_count = len(source_meet_dates)
    unidentified_count = len(unidentified)
    actual = {
        "source_file_count": source_file_count,
        "participant_row_count": participant_count,
        "session_count": session_count,
        "source_meet_date_count": meet_date_count,
        "unidentified_horse_id_row_count": unidentified_count,
    }
    for key, expected in EXPECTED.items():
        if actual[key] != expected:
            raise AssertionError(f"{key}: expected {expected}, got {actual[key]}")
    if manifest.get("participant_row_count") != participant_count:
        raise AssertionError("Source manifest participant count differs")
    if len(source_by_id) != participant_count:
        raise AssertionError("Not every source participant was indexed")
    if sum(int(row["participant_rows"]) for row in sessions) != participant_count:
        raise AssertionError("Session counts do not sum to all participants")

    special_sessions = [row for row in sessions
                        if row["source_meet_query"] == "3" and row["trial_date"] == "2026-09-17"]
    if not special_sessions or any(row["api_meet_label"] != "영남" for row in special_sessions):
        raise AssertionError("Expected 2026-09-17 meet=3 rows to retain API label 영남")
    if any("venue" in row for row in sessions):
        raise AssertionError("No physical venue should be inferred for the meet=3 session")

    output_paths = [PARTICIPANTS_PATH, SESSIONS_PATH, UNIDENTIFIED_PATH, MANIFEST_PATH]
    report = {
        "passed": True,
        "checks": {
            "all_source_participant_rows_retained_and_raw_payloads_match": True,
            "source_file_sha256_provenance_matches": True,
            "normalized_date_and_trial_session_keys_match_api_fields": True,
            "unidentified_horse_rows_retained_in_main_and_review_extracts": True,
            "no_grade_or_inferred_physical_venue_column": True,
            "meet_3_2026_09_17_keeps_raw_label_yeongnam": True,
            "source_session_participant_counts_reconcile": True,
            "expected_source_counts_match": True,
        },
        "counts": actual,
        "participant_rows_by_source_meet_query": dict(sorted(source_rows_by_meet.items())),
        "missing_horse_id_rows_by_source_meet_query": dict(sorted(source_missing_ids_by_meet.items())),
        "source_api_meet_label_rows": dict(sorted(source_labels.items())),
        "source_files_by_year": {str(year): count for year, count in sorted(source_files_by_year.items())},
        "trial_date_min": min(date_values),
        "trial_date_max": max(date_values),
        "api_field_count": len(raw_api_fields),
        "api_grade_fields_found": sorted(raw_schema_grade_fields),
        "source_meet_3_2026_09_17": {
            "session_count": len(special_sessions),
            "participant_rows": sum(int(row["participant_rows"]) for row in special_sessions),
            "api_meet_label": "영남",
            "physical_venue": None,
            "interpretation": "Venue is unresolved; no Yeongcheon or other physical venue was assigned.",
        },
        "output_file_sha256": {
            path.name: file_sha256(path) for path in output_paths
        },
    }
    VALIDATION_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    report = validate()
    print(json.dumps({"passed": report["passed"], **report["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
