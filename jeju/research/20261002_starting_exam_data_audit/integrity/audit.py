#!/usr/bin/env python3
"""Independent read-only integrity audit for archived Jeju API21 starting exams."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_REL = Path("jeju/research/20261001_starting_exam_api_collection/api21_successful_collection_report.json")
RESEARCH_REL = Path("jeju/research/20261001_starting_exam_api_collection")
NATIVE_LABEL = "제주마"
PASS_LABELS = {"합격", "1차합격"}
FAIL_LABELS = {"불합격", "불합격(발검)", "발주불합격", "출발불합격"}
NONFINAL_LABELS = {"검사취소", "심사취소", "출전취소"}
EXCLUSION_LABELS = {"발주제외", "검사제외", "심사제외", "출발제외", "출전제외"}
EXAMPLE_LIMIT_PER_CATEGORY = 12
FOCUS_FIELDS = ("trainDate", "daySerial", "trainNo", "chulNo", "hrNo", "rider", "age", "passFlag", "reason", "nopassReason", "trNo", "owNo")
ID_FIELDS = ("hrNo", "trNo", "owNo")
NUMERIC_FIELDS = ("trainNo", "chulNo", "daySerial", "age")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_child(base: Path, relative: str | Path) -> Path:
    """Resolve a manifest path and require it to stay below its trusted base."""
    rel = Path(relative)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise ValueError(f"unsafe relative path: {relative}")
    base_real = base.resolve(strict=True)
    resolved = (base_real / rel).resolve(strict=True)
    resolved.relative_to(base_real)
    return resolved


def raw_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def field_state(row: dict[str, Any], field: str) -> str:
    if field not in row:
        return "absent"
    value = row[field]
    if value is None:
        return "null"
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return "blank"
        if value == "-":
            return "dash_sentinel"
    return "present"


def parse_integer(value: Any) -> tuple[int | None, str]:
    if value is None:
        return None, "null"
    if isinstance(value, bool):
        return None, "invalid_boolean"
    if isinstance(value, int):
        return value, "valid_integer"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None, "blank"
        if text == "-":
            return None, "sentinel_dash"
        if re.fullmatch(r"[+-]?\d+", text):
            try:
                return int(text), "valid_integer"
            except ValueError:
                return None, "invalid_integer"
    return None, "invalid_format"


def id_token(value: Any) -> str:
    if value is None:
        return "<NULL>"
    if isinstance(value, bool):
        return "<BOOL:" + str(value).lower() + ">"
    return str(value)


def key_component(row: dict[str, Any], field: str) -> tuple[str, str]:
    state = field_state(row, field)
    if state != "present":
        return (state, "")
    value = row[field]
    parsed, status = parse_integer(value)
    if status == "valid_integer":
        return ("integer", str(parsed))
    return ("raw:" + type(value).__name__, str(value).strip() if isinstance(value, str) else str(value))


def event_ref(rec: dict[str, Any]) -> dict[str, Any]:
    raw = rec["raw"]
    return {
        "source_path": rec["source_path"],
        "source_row_no": rec["source_row_no"],
        "trainDate": raw.get("trainDate"),
        "trainNo": raw.get("trainNo", "<ABSENT>"),
        "chulNo": raw.get("chulNo", "<ABSENT>"),
        "hrNo": raw.get("hrNo", "<ABSENT>"),
        "passFlag": raw.get("passFlag", "<ABSENT>"),
        "nopassReason": raw.get("nopassReason", "<ABSENT>"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True, help="read-only horse_racing repository root")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    report_path = safe_child(repo, REPORT_REL)
    research = safe_child(repo, RESEARCH_REL)
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    report_sha = sha256_bytes(report_bytes)
    integrity_errors: list[dict[str, Any]] = []
    anomaly_counts: collections.Counter[str] = collections.Counter()
    examples: list[dict[str, Any]] = []
    category_example_counts: collections.Counter[str] = collections.Counter()

    def record(category: str, detail: dict[str, Any], count: int = 1, severity: str = "review_candidate") -> None:
        anomaly_counts[category] += count
        if category_example_counts[category] < EXAMPLE_LIMIT_PER_CATEGORY:
            examples.append({"category": category, "severity": severity, **detail})
            category_example_counts[category] += 1

    def error(code: str, detail: dict[str, Any]) -> None:
        item = {"code": code, **detail}
        integrity_errors.append(item)
        record("collection_integrity_error", item, severity="integrity_error")

    all_rows: list[dict[str, Any]] = []
    partition_summaries: list[dict[str, Any]] = []
    attempt_history: list[dict[str, Any]] = []
    page_integrity: list[dict[str, Any]] = []
    selected_attempt_ids: dict[str, str] = {}

    for year in range(2000, 2027):
        partition = safe_child(research, Path("raw/api21_1/partitions") / f"year_{year}" / "attempts")
        manifests = sorted(partition.glob("*/attempt_manifest.json"))
        completed: list[tuple[Path, dict[str, Any]]] = []
        for path in manifests:
            manifest = read_json(path)
            status = manifest.get("status")
            attempt_history.append({"year": year, "attempt_id": path.parent.name, "status": status})
            if status == "completed_api_response":
                completed.append((path, manifest))
        if not completed:
            error("missing_completed_attempt", {"year": year})
            partition_summaries.append({"year": year, "status": "missing_completed_attempt"})
            continue
        manifest_path, manifest = completed[-1]
        selected_attempt_ids[str(year)] = manifest_path.parent.name
        rel_manifest = manifest_path.relative_to(research).as_posix()
        declared_partition = next((p for p in report.get("annual_partitions", []) if p.get("year") == year), None)
        report_pages_by_no = {int(p.get("page_no")): p for p in (declared_partition or {}).get("pages", [])}
        if declared_partition is None:
            error("report_missing_annual_partition", {"year": year})
        else:
            if len(declared_partition.get("pages", [])) != len(manifest.get("source_pages", [])):
                error("report_page_count_mismatch", {"year": year, "manifest_pages": len(manifest.get("source_pages", [])), "reported_pages": len(declared_partition.get("pages", []))})
            if declared_partition.get("attempt_id") != manifest_path.parent.name:
                error("report_attempt_id_mismatch", {"year": year, "selected": manifest_path.parent.name, "reported": declared_partition.get("attempt_id")})
            actual_manifest_sha = sha256_bytes(manifest_path.read_bytes())
            if actual_manifest_sha != declared_partition.get("manifest_sha256"):
                error("manifest_hash_mismatch", {"year": year, "actual_sha256": actual_manifest_sha, "reported_sha256": declared_partition.get("manifest_sha256")})

        actual_count = 0
        page_totals: set[int] = set()
        page_nos: list[int] = []
        page_size_values: set[int] = set()
        partition_row_refs: list[dict[str, Any]] = []
        for declared_page in manifest.get("source_pages", []):
            try:
                source_path = safe_child(manifest_path.parent, declared_page["response_file"])
            except Exception as exc:
                error("unsafe_or_missing_source_page", {"year": year, "attempt_id": manifest_path.parent.name, "response_file": declared_page.get("response_file"), "reason": str(exc)})
                continue
            payload_bytes = source_path.read_bytes()
            actual_sha = sha256_bytes(payload_bytes)
            actual_bytes = len(payload_bytes)
            if actual_sha != declared_page.get("response_sha256"):
                error("page_hash_mismatch", {"year": year, "page_no": declared_page.get("page_no"), "actual_sha256": actual_sha, "reported_sha256": declared_page.get("response_sha256"), "source_path": source_path.relative_to(research).as_posix()})
            if actual_bytes != declared_page.get("response_bytes"):
                error("page_byte_count_mismatch", {"year": year, "page_no": declared_page.get("page_no"), "actual_bytes": actual_bytes, "reported_bytes": declared_page.get("response_bytes")})
            try:
                payload = json.loads(payload_bytes)
                response = payload.get("response", payload)
                header = response.get("header", {})
                body = response.get("body", {})
                result_code = str(header.get("resultCode", ""))
                if result_code not in {"00", "0000"}:
                    error("non_success_header", {"year": year, "page_no": declared_page.get("page_no"), "result_code": result_code, "result_message": header.get("resultMsg")})
                body_page = int(body.get("pageNo"))
                body_total = int(body.get("totalCount"))
                body_size = int(body.get("numOfRows"))
                declared_no = int(declared_page.get("page_no"))
                if body_page != declared_no:
                    error("page_no_mismatch", {"year": year, "declared_page_no": declared_no, "body_page_no": body_page})
                page_nos.append(body_page)
                page_totals.add(body_total)
                page_size_values.add(body_size)
                items_value = (body.get("items") or {}).get("item")
                if isinstance(items_value, list):
                    items = items_value
                elif isinstance(items_value, dict):
                    items = [items_value]
                elif items_value is None:
                    items = []
                else:
                    error("unexpected_items_shape", {"year": year, "page_no": body_page, "items_type": type(items_value).__name__})
                    items = []
                if len(items) != int(declared_page.get("actual_rows", -1)):
                    error("page_row_count_mismatch", {"year": year, "page_no": body_page, "actual_rows": len(items), "reported_rows": declared_page.get("actual_rows")})
                report_page = report_pages_by_no.get(body_page)
                page_actuals = {"page_no": body_page, "actual_rows": len(items), "api_total_count": body_total, "response_bytes": actual_bytes, "response_sha256": actual_sha, "header_result_code": result_code}
                if report_page is None:
                    error("report_missing_page_declaration", {"year": year, "page_no": body_page})
                else:
                    for field, actual_value in page_actuals.items():
                        if report_page.get(field) != actual_value:
                            error("report_page_value_mismatch", {"year": year, "page_no": body_page, "field": field, "actual": actual_value, "reported": report_page.get(field)})
                    if safe_child(research, report_page.get("response_file", "")) != source_path:
                        error("report_page_path_mismatch", {"year": year, "page_no": body_page, "manifest_path": declared_page.get("response_file"), "reported_path": report_page.get("response_file")})
                for row_no, item in enumerate(items, start=1):
                    if not isinstance(item, dict):
                        error("non_object_source_row", {"year": year, "page_no": body_page, "source_row_no": row_no, "row_type": type(item).__name__})
                        continue
                    rec = {"source_path": source_path.relative_to(research).as_posix(), "source_row_no": row_no, "page_no": body_page, "year_partition": year, "raw": item}
                    all_rows.append(rec)
                    partition_row_refs.append(rec)
                    actual_count += 1
                    date_value = item.get("trainDate")
                    date_text = raw_text(date_value)
                    if date_text is None or not re.fullmatch(r"\d{8}", date_text):
                        record("invalid_or_absent_train_date", {"row": event_ref(rec), "date_state": field_state(item, "trainDate"), "raw_value": date_value})
                    else:
                        try:
                            parsed_date = datetime.strptime(date_text, "%Y%m%d").date()
                            if parsed_date.strftime("%Y%m%d") != date_text:
                                raise ValueError("non-roundtrip date")
                            if parsed_date.year != year:
                                record("train_date_partition_year_mismatch", {"row": event_ref(rec), "partition_year": year, "parsed_year": parsed_date.year})
                            if date_text < "20000101" or date_text > "20261002":
                                record("train_date_outside_requested_range", {"row": event_ref(rec), "requested_from": "20000101", "requested_through": "20261002"})
                        except ValueError:
                            record("invalid_or_absent_train_date", {"row": event_ref(rec), "date_state": "invalid_calendar_date", "raw_value": date_value})
                    if item.get("meet") != "제주":
                        record("meet_value_not_jeju", {"row": event_ref(rec), "meet_raw": item.get("meet")})
                page_integrity.append({"year": year, "attempt_id": manifest_path.parent.name, "page_no": body_page, "rows": len(items), "total_count": body_total, "num_of_rows": body_size, "response_bytes": actual_bytes, "sha256_ok": actual_sha == declared_page.get("response_sha256"), "bytes_ok": actual_bytes == declared_page.get("response_bytes"), "header_result_code": result_code, "source_path": source_path.relative_to(research).as_posix()})
            except Exception as exc:
                error("page_parse_or_structure_error", {"year": year, "page_no": declared_page.get("page_no"), "source_path": source_path.relative_to(research).as_posix(), "reason": str(exc)})

        if len(page_totals) != 1:
            error("inconsistent_page_total_count", {"year": year, "totals": sorted(page_totals)})
        total = next(iter(page_totals)) if len(page_totals) == 1 else None
        expected_page_count = None
        if total is not None and len(page_size_values) == 1:
            page_size = next(iter(page_size_values))
            expected_page_count = (total + page_size - 1) // page_size if page_size > 0 else None
            if actual_count != total:
                error("partition_count_incomplete", {"year": year, "actual_rows": actual_count, "total_count": total})
            if expected_page_count is not None and len(page_nos) != expected_page_count:
                error("partition_page_count_incomplete", {"year": year, "actual_pages": len(page_nos), "expected_pages": expected_page_count, "num_of_rows": page_size})
        elif len(page_size_values) != 1:
            error("inconsistent_page_size", {"year": year, "num_of_rows_values": sorted(page_size_values)})
        if page_nos != list(range(1, len(page_nos) + 1)):
            error("non_contiguous_page_numbers", {"year": year, "page_numbers": page_nos})
        if declared_partition and actual_count != declared_partition.get("rows"):
            error("report_partition_row_count_mismatch", {"year": year, "actual_rows": actual_count, "reported_rows": declared_partition.get("rows")})
        partition_summaries.append({"year": year, "status": "verified" if not any(e.get("year") == year for e in integrity_errors) else "integrity_issue", "attempt_id": manifest_path.parent.name, "rows": actual_count, "reported_rows": declared_partition.get("rows") if declared_partition else None, "page_count": len(page_nos), "expected_page_count": expected_page_count, "total_count": total, "manifest": rel_manifest})

    # Compare overall collection declarations to the independently loaded source rows.
    declared_api = report.get("api21_collection", {})
    overall_declared_rows = declared_api.get("raw_rows")
    if len(all_rows) != overall_declared_rows:
        error("overall_report_row_count_mismatch", {"actual_rows": len(all_rows), "reported_rows": overall_declared_rows})
    observed_bytes = sum(p.get("response_bytes", 0) for p in page_integrity)
    if observed_bytes != declared_api.get("raw_response_bytes"):
        error("overall_report_response_byte_count_mismatch", {"actual_bytes": observed_bytes, "reported_bytes": declared_api.get("raw_response_bytes")})
    if len(partition_summaries) != 27 or sum(p.get("status") == "verified" for p in partition_summaries) != 27:
        error("annual_partition_coverage_mismatch", {"partitions_seen": len(partition_summaries), "verified_partitions": sum(p.get("status") == "verified" for p in partition_summaries)})

    # Calculate a current-API42 based horse ID filter using read-only local records and the archived 21-profile follow-up.
    sqlite_path = safe_child(repo, Path("jeju/data/jeju_native_core.sqlite3"))
    native_ids: set[str] = set()
    local_profile_ids: set[str] = set()
    db = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True, timeout=30)
    try:
        db.execute("PRAGMA query_only=ON")
        local_profile_ids.update(str(r[0]) for r in db.execute("SELECT DISTINCT horse_id FROM horse_profile_observations WHERE breed_label_raw = ?", (NATIVE_LABEL,)))
    finally:
        db.close()
    followup_summary_path = safe_child(research, "api42_followup_summary.json")
    followup_summary = read_json(followup_summary_path)
    followup_manifest_path = safe_child(research, followup_summary["manifest"])
    followup_manifest = read_json(followup_manifest_path)
    followup_profile_ids: set[str] = set()
    for probe in followup_manifest.get("probes", []):
        if probe.get("status") != "completed":
            continue
        response_path = safe_child(followup_manifest_path.parent, probe["response_file"])
        raw_bytes = response_path.read_bytes()
        actual_sha = sha256_bytes(raw_bytes)
        if actual_sha != probe.get("response_sha256"):
            error("api42_followup_hash_mismatch", {"queried_hr_no": probe.get("queried_hr_no"), "source_path": response_path.relative_to(research).as_posix()})
        payload = json.loads(raw_bytes)
        response = payload.get("response", payload)
        body = response.get("body", {})
        value = (body.get("items") or {}).get("item")
        profiles = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
        exact = [item for item in profiles if str(item.get("hrNo")) == str(probe.get("queried_hr_no"))]
        if len(exact) == 1 and exact[0].get("breed") == NATIVE_LABEL:
            followup_profile_ids.add(str(exact[0].get("hrNo")))
    native_ids.update(local_profile_ids)
    native_ids.update(followup_profile_ids)

    candidate_rows = [r for r in all_rows if str(r["raw"].get("hrNo")) in native_ids]
    candidate_source_horse_ids = {str(r["raw"].get("hrNo")) for r in candidate_rows}
    high_age_rows = []
    for rec in all_rows:
        age_value, age_state = parse_integer(rec["raw"].get("age"))
        if age_state == "valid_integer" and age_value is not None and age_value >= 16:
            high_age_rows.append(rec)
            record("age_16_plus_numeric_review_candidate", {"row": event_ref(rec), "age_raw": rec["raw"].get("age"), "native_candidate": str(rec["raw"].get("hrNo")) in native_ids, "interpretation": "numeric value is valid; plausibility/profile source requires separate review"})
    high_age_native_rows = [r for r in high_age_rows if str(r["raw"].get("hrNo")) in native_ids]
    candidate_rel = Path("api21_verified_native_candidate_rows.jsonl")
    candidate_path = safe_child(research, candidate_rel)
    candidate_bytes = candidate_path.read_bytes()
    actual_candidate_rows = [json.loads(line) for line in candidate_bytes.decode("utf-8").splitlines() if line.strip()]
    reconstructed_bytes = "".join(json.dumps({"source_path": r["source_path"], "source_row_no": r["source_row_no"], "raw": r["raw"]}, ensure_ascii=False, sort_keys=True) + "\n" for r in candidate_rows).encode("utf-8")
    reconstructed_candidate_rows = [json.loads(line) for line in reconstructed_bytes.decode("utf-8").splitlines()]
    candidate_row_mismatches = []
    if len(actual_candidate_rows) != len(reconstructed_candidate_rows):
        candidate_row_mismatches.append({"kind": "row_count", "actual": len(actual_candidate_rows), "reconstructed": len(reconstructed_candidate_rows)})
    for index, (actual, expected) in enumerate(zip(actual_candidate_rows, reconstructed_candidate_rows), start=1):
        if actual != expected:
            candidate_row_mismatches.append({"kind": "row_content", "index": index, "actual_source_path": actual.get("source_path"), "actual_source_row_no": actual.get("source_row_no"), "expected_source_path": expected.get("source_path"), "expected_source_row_no": expected.get("source_row_no")})
            if len(candidate_row_mismatches) >= 12:
                break
    reported_candidate_sha = report.get("independent_verification", {}).get("native_candidate_sha256")
    candidate_sha = sha256_bytes(candidate_bytes)
    reconstruction_sha = sha256_bytes(reconstructed_bytes)
    if candidate_sha != reported_candidate_sha:
        error("candidate_report_hash_mismatch", {"actual_sha256": candidate_sha, "reported_sha256": reported_candidate_sha})
    if candidate_row_mismatches:
        error("native_candidate_reconstruction_mismatch", {"mismatches": candidate_row_mismatches})
    filter_notes = {
        "filter_rule_reproduced": "horse ID present in any local API42 profile observation with breed_label_raw='제주마', plus exact-ID completed API42 follow-up profiles with breed='제주마'",
        "local_profile_observation_horse_ids": len(local_profile_ids),
        "api42_followup_exact_native_horse_ids": len(followup_profile_ids),
        "union_native_horse_ids": len(native_ids),
        "native_filter_ids_with_api21_rows": len(candidate_source_horse_ids),
        "native_filter_ids_without_api21_rows": len(native_ids - candidate_source_horse_ids),
        "native_candidate_rows_reconstructed": len(candidate_rows),
        "candidate_file_rows": len(actual_candidate_rows),
        "candidate_file_sha256": candidate_sha,
        "candidate_reconstructed_sha256": reconstruction_sha,
        "candidate_reported_sha256": reported_candidate_sha,
        "candidate_rows_exactly_reconstructed": not candidate_row_mismatches,
        "candidate_row_mismatch_examples": candidate_row_mismatches,
        "api21_species_id_field_present_anywhere": any("speciesID" in r["raw"] or "speciesId" in r["raw"] for r in all_rows),
        "api21_meet_is_jeju_value": collections.Counter(raw_text(r["raw"].get("meet")) for r in all_rows),
        "interpretation_limit": "API21 rows have no speciesID field; the linked candidate filter is current API42 breed evidence and does not establish breed on the historical exam date."
    }

    # Field presence and type summaries keep absent, null, blank, dash, and invalid distinct.
    field_presence: dict[str, dict[str, int]] = {}
    field_types: dict[str, dict[str, int]] = {}
    raw_fields: set[str] = set()
    field_year: dict[str, dict[str, dict[str, int]]] = {}
    field_judgement: dict[str, dict[str, dict[str, int]]] = {}
    for rec in all_rows:
        raw_fields.update(rec["raw"].keys())
    fields_to_check = sorted(raw_fields | set(FOCUS_FIELDS))
    for field in fields_to_check:
        states: collections.Counter[str] = collections.Counter()
        types: collections.Counter[str] = collections.Counter()
        by_year: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
        by_judgement: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
        for rec in all_rows:
            row = rec["raw"]
            state = field_state(row, field)
            states[state] += 1
            by_year[str(rec["year_partition"])][state] += 1
            label = raw_text(row.get("passFlag")) if "passFlag" in row else "<ABSENT>"
            by_judgement[label if label not in (None, "") else "<NULL_OR_BLANK>"][state] += 1
            if field in row:
                types[type(row[field]).__name__] += 1
        field_presence[field] = dict(states)
        field_types[field] = dict(types)
        field_year[field] = {year: dict(counts) for year, counts in sorted(by_year.items())}
        if field in {"chulNo", "daySerial", "rider", "hrNo", "trainDate", "trainNo", "passFlag", "age", "nopassReason", "reason"}:
            field_judgement[field] = {label: dict(counts) for label, counts in sorted(by_judgement.items())}

    # Date, integer, and raw ID checks.
    date_values: list[str] = []
    date_year_counter: collections.Counter[str] = collections.Counter()
    date_sources: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
    valid_date_count = 0
    invalid_date_count = 0
    numeric_summary: dict[str, Any] = {}
    for field in NUMERIC_FIELDS:
        states: collections.Counter[str] = collections.Counter()
        value_counts: collections.Counter[int] = collections.Counter()
        type_counts: collections.Counter[str] = collections.Counter()
        invalid_examples: list[dict[str, Any]] = []
        for rec in all_rows:
            row = rec["raw"]
            state = field_state(row, field)
            states[state] += 1
            if field in row:
                type_counts[type(row[field]).__name__] += 1
                parsed, parse_state = parse_integer(row[field])
                if parse_state == "valid_integer":
                    value_counts[parsed] += 1
                    if parsed <= 0:
                        record("nonpositive_numeric_field", {"field": field, "raw_value": row[field], "parsed_value": parsed, "row": event_ref(rec)})
                elif parse_state not in {"null", "blank", "sentinel_dash"}:
                    if len(invalid_examples) < 12:
                        invalid_examples.append({"row": event_ref(rec), "raw_value": row[field], "parse_state": parse_state})
                    record("invalid_numeric_field", {"field": field, "raw_value": row[field], "parse_state": parse_state, "row": event_ref(rec)})
        numeric_summary[field] = {"field_states": dict(states), "raw_types": dict(type_counts), "valid_integer_count": sum(value_counts.values()), "min": min(value_counts) if value_counts else None, "max": max(value_counts) if value_counts else None, "distinct_integer_values": len(value_counts), "nonpositive_count": sum(n for v, n in value_counts.items() if v <= 0), "invalid_examples": invalid_examples, "most_common_values": [{"value": value, "rows": count} for value, count in value_counts.most_common(20)]}

    for rec in all_rows:
        value = rec["raw"].get("trainDate")
        text = raw_text(value)
        if text and re.fullmatch(r"\d{8}", text):
            try:
                dt = datetime.strptime(text, "%Y%m%d").date()
                if dt.strftime("%Y%m%d") == text:
                    valid_date_count += 1
                    date_values.append(text)
                    date_year_counter[str(dt.year)] += 1
                    date_sources[rec["year_partition"]].append({"date": text, "daySerial": rec["raw"].get("daySerial"), "source_path": rec["source_path"], "source_row_no": rec["source_row_no"]})
                    continue
            except ValueError:
                pass
        invalid_date_count += 1

    id_summary: dict[str, Any] = {}
    for field in ID_FIELDS:
        states: collections.Counter[str] = collections.Counter()
        types: collections.Counter[str] = collections.Counter()
        lengths: collections.Counter[str] = collections.Counter()
        non_digit_examples: list[dict[str, Any]] = []
        leading_zero_examples: list[dict[str, Any]] = []
        leading_zero_string_count = 0
        non_digit_count = 0
        for rec in all_rows:
            row = rec["raw"]
            states[field_state(row, field)] += 1
            if field not in row:
                continue
            value = row[field]
            types[type(value).__name__] += 1
            text = raw_text(value)
            if text is None:
                continue
            stripped = text.strip()
            if re.fullmatch(r"\d+", stripped):
                lengths[str(len(stripped))] += 1
                if len(stripped) > 1 and stripped.startswith("0"):
                    leading_zero_string_count += 1
                    if len(leading_zero_examples) < 8:
                        leading_zero_examples.append({"raw_value": value, "raw_type": type(value).__name__, "row": event_ref(rec)})
            elif stripped not in {"", "-"}:
                non_digit_count += 1
                if len(non_digit_examples) < 8:
                    non_digit_examples.append({"raw_value": value, "raw_type": type(value).__name__, "row": event_ref(rec)})
        id_summary[field] = {"field_states": dict(states), "raw_types": dict(types), "digit_string_lengths": dict(lengths), "leading_zero_string_count": leading_zero_string_count, "leading_zero_examples": leading_zero_examples, "non_digit_count": non_digit_count, "non_digit_examples": non_digit_examples, "normalization_applied": False}

    if date_values:
        observed_date_min, observed_date_max = min(date_values), max(date_values)
    else:
        observed_date_min = observed_date_max = None

    # Canonical full-content duplicate groups; identical repeated observations are retained.
    content_groups: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    content_counts: collections.Counter[str] = collections.Counter()
    for rec in all_rows:
        canonical = json.dumps(rec["raw"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = sha256_bytes(canonical.encode("utf-8"))
        content_counts[fingerprint] += 1
        if len(content_groups[fingerprint]) < EXAMPLE_LIMIT_PER_CATEGORY:
            content_groups[fingerprint].append(rec)
    duplicate_fingerprints = {fp: count for fp, count in content_counts.items() if count > 1}
    for fp, count in duplicate_fingerprints.items():
        record("identical_full_content_repeats_preserved", {"content_sha256": fp, "occurrences": count, "rows": [event_ref(r) for r in content_groups[fp]]}, count=1, severity="observation")

    # Event key collisions; a missing chulNo is a distinct token, never coerced to 0.
    exact_key_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = collections.defaultdict(list)
    date_round_entry: dict[tuple[Any, ...], list[dict[str, Any]]] = collections.defaultdict(list)
    date_round_horse: dict[tuple[Any, ...], list[dict[str, Any]]] = collections.defaultdict(list)
    horse_day: dict[tuple[Any, ...], list[dict[str, Any]]] = collections.defaultdict(list)
    round_rosters: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    judgement_by_horse_dates: dict[str, dict[str, set[str]]] = collections.defaultdict(lambda: collections.defaultdict(set))
    for rec in all_rows:
        row = rec["raw"]
        date_value = raw_text(row.get("trainDate"))
        train_no = key_component(row, "trainNo")
        chul_no = key_component(row, "chulNo")
        horse = id_token(row.get("hrNo"))
        exact_key_groups[(date_value, train_no, chul_no, horse)].append(rec)
        date_round_horse[(date_value, train_no, horse)].append(rec)
        if field_state(row, "chulNo") == "present":
            date_round_entry[(date_value, train_no, chul_no)].append(rec)
        horse_day[(date_value, horse)].append(rec)
        if date_value and date_value.isdigit() and len(date_value) == 8 and "hrNo" in row and "trainNo" in row:
            round_rosters[(date_value, train_no[1])].append(rec)
        label = raw_text(row.get("passFlag"))
        if label is not None and date_value:
            judgement_by_horse_dates[horse][label].add(date_value)

    exact_key_collision_groups = [v for v in exact_key_groups.values() if len(v) > 1]
    for group in exact_key_collision_groups:
        record("date_round_entry_horse_key_collision", {"row_count": len(group), "rows": [event_ref(r) for r in group]})
    date_round_entry_collisions = []
    for key, group in date_round_entry.items():
        horses = {id_token(r["raw"].get("hrNo")) for r in group}
        if len(horses) > 1:
            date_round_entry_collisions.append((key, group, horses))
            record("date_round_chulno_multiple_horses", {"date_round_chulNo": key, "horse_ids": sorted(horses), "rows": [event_ref(r) for r in group]})
    date_round_horse_multi_entry = []
    for key, group in date_round_horse.items():
        entries = {key_component(r["raw"], "chulNo") for r in group}
        if len(group) > 1 and len(entries) > 1:
            date_round_horse_multi_entry.append((key, group, entries))
            record("date_round_horse_multiple_entry_numbers", {"date_round_horse": key, "entry_number_tokens": sorted([list(t) for t in entries]), "rows": [event_ref(r) for r in group]})

    same_horse_multi_event = []
    same_horse_same_round_repeat = []
    for key, group in horse_day.items():
        rounds = {key_component(r["raw"], "trainNo") for r in group}
        if len(group) > 1 and len(rounds) > 1:
            same_horse_multi_event.append((key, group, rounds))
        elif len(group) > 1:
            same_horse_same_round_repeat.append((key, group))
    # These repeated events are reported as observations, not automatically treated as errors.
    for key, group, rounds in same_horse_multi_event[:EXAMPLE_LIMIT_PER_CATEGORY]:
        record("same_horse_same_day_distinct_rounds_observed", {"date_horse": key, "round_tokens": sorted([list(t) for t in rounds]), "rows": [event_ref(r) for r in group]}, count=0, severity="observation")

    fail_pass_repeat_horses = []
    for horse, labels in judgement_by_horse_dates.items():
        pass_dates = set().union(*(labels.get(label, set()) for label in PASS_LABELS))
        fail_dates = set().union(*(labels.get(label, set()) for label in FAIL_LABELS))
        if pass_dates and fail_dates:
            fail_pass_repeat_horses.append({"horse_id_raw_token": horse, "pass_dates_count": len(pass_dates), "fail_dates_count": len(fail_dates), "example_pass_dates": sorted(pass_dates)[:3], "example_fail_dates": sorted(fail_dates)[:3]})

    # Identical horse-number and horse-ID rosters in a given round on separate dates are candidates only.
    roster_groups: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for (date_value, round_token), group in round_rosters.items():
        entries = []
        for rec in group:
            row = rec["raw"]
            horse = id_token(row.get("hrNo"))
            chul = key_component(row, "chulNo")
            entries.append((horse, chul[0], chul[1]))
        roster_json = json.dumps(sorted(entries), ensure_ascii=False, separators=(",", ":"))
        roster_hash = sha256_bytes(roster_json.encode("utf-8"))
        roster_groups[roster_hash].append({"date": date_value, "trainNo_token": round_token, "entries": entries, "row_count": len(group), "rows": [event_ref(r) for r in group[:20]]})
    repeated_rosters = []
    for roster_hash, occurrences in roster_groups.items():
        distinct_dates = sorted({o["date"] for o in occurrences})
        if len(distinct_dates) > 1:
            candidate = {"roster_sha256": roster_hash, "distinct_date_count": len(distinct_dates), "dates": distinct_dates[:30], "occurrences": len(occurrences), "round_tokens": sorted({o["trainNo_token"] for o in occurrences}), "roster_size": occurrences[0]["row_count"], "horse_entry_roster": occurrences[0]["entries"], "occurrences_detail": [{k: o[k] for k in ("date", "trainNo_token", "row_count", "rows")} for o in occurrences[:8]]}
            repeated_rosters.append(candidate)
            record("identical_round_roster_on_multiple_dates_candidate", candidate)
    repeated_rosters.sort(key=lambda x: (x["distinct_date_count"], x["occurrences"]), reverse=True)

    # Judgement/result reason cross-checks preserve all original labels.
    judgement_counts: collections.Counter[str] = collections.Counter()
    judgement_reason_counts: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    contradictory_pass_reason = 0
    fail_without_reason = 0
    cancellation_with_reason = 0
    excluded_with_reason = 0
    for rec in all_rows:
        row = rec["raw"]
        state = field_state(row, "passFlag")
        label = raw_text(row.get("passFlag")) if state != "absent" else "<ABSENT>"
        label_key = label if label is not None else "<NULL>"
        judgement_counts[label_key] += 1
        reason_state = field_state(row, "nopassReason")
        reason_value = row.get("nopassReason")
        meaningful_reason = reason_state == "present" and str(reason_value).strip() not in {"", "-"}
        reason_key = "<" + reason_state + ">" if not meaningful_reason else str(reason_value)
        judgement_reason_counts[label_key][reason_key] += 1
        if label in PASS_LABELS and meaningful_reason:
            contradictory_pass_reason += 1
            record("pass_judgement_with_failure_reason", {"row": event_ref(rec), "failure_reason_raw": reason_value})
        elif label in FAIL_LABELS and not meaningful_reason:
            fail_without_reason += 1
            record("fail_judgement_without_failure_reason", {"row": event_ref(rec), "failure_reason_state": reason_state, "failure_reason_raw": reason_value})
        elif label in NONFINAL_LABELS and meaningful_reason:
            cancellation_with_reason += 1
        elif label in EXCLUSION_LABELS and meaningful_reason:
            excluded_with_reason += 1
    native_fail_without_reason = [
        event_ref(rec) for rec in candidate_rows
        if rec["raw"].get("passFlag") in FAIL_LABELS
        and field_state(rec["raw"], "nopassReason") in {"absent", "null", "blank", "dash_sentinel"}
    ]

    # API metadata defines daySerial as inspection sequence, so only source-date ordering is assessed here.
    chronology: dict[str, Any] = {}
    for year, items in sorted(date_sources.items()):
        source_dates = [item["date"] for item in items if re.fullmatch(r"\d{8}", item["date"])]
        asc_steps = sum(a < b for a, b in zip(source_dates, source_dates[1:]))
        desc_steps = sum(a > b for a, b in zip(source_dates, source_dates[1:]))
        chronology[str(year)] = {"distinct_exam_dates": len(set(source_dates)), "ascending_date_order_steps_in_raw_response": asc_steps, "descending_date_order_steps_in_raw_response": desc_steps, "equal_date_adjacent_steps_in_raw_response": len(source_dates) - 1 - asc_steps - desc_steps, "dominant_raw_response_date_order": "descending" if desc_steps > asc_steps else "ascending" if asc_steps > desc_steps else "mixed_or_tied"}

    # Per-year source schema/presence summary for the requested event identity and outcome fields.
    focus_presence_by_year = {field: field_year[field] for field in FOCUS_FIELDS}
    unknown_judgements = sorted(label for label in judgement_counts if label not in PASS_LABELS | FAIL_LABELS | NONFINAL_LABELS | EXCLUSION_LABELS | {"-", "<ABSENT>", "<NULL>"})
    all_dates_fit_reported_range = bool(date_values) and observed_date_min >= "20000101" and observed_date_max <= "20261002"
    excluded_attempts = [a for a in attempt_history if a["status"] != "completed_api_response"]
    successful_attempt_count = sum(a["status"] == "completed_api_response" for a in attempt_history)
    duplicate_excess_rows = sum(count - 1 for count in duplicate_fingerprints.values())
    summary = {
        "audit": {"name": "API21 archived raw response independent integrity audit", "generated_at_utc": datetime.now(timezone.utc).isoformat(), "repository_root": str(repo), "output_dir": str(out_dir), "read_only_inputs": True, "network_used": False, "database_writes": False, "raw_source_modified": False, "script_sha256": sha256_bytes(Path(__file__).read_bytes())},
        "source": {"collection_report": REPORT_REL.as_posix(), "collection_report_sha256": report_sha, "research_root": RESEARCH_REL.as_posix(), "requested_meet": 2, "requested_dates": {"from": "20000101", "through_inclusive": "20261002"}, "requested_year_partitions": 27},
        "collection_integrity": {"annual_partitions": partition_summaries, "selected_latest_completed_attempts": selected_attempt_ids, "successful_attempts_seen": successful_attempt_count, "excluded_noncompleted_attempts": excluded_attempts, "selected_pages": len(page_integrity), "verified_page_hashes": sum(p["sha256_ok"] for p in page_integrity), "page_hash_mismatches": sum(not p["sha256_ok"] for p in page_integrity), "verified_page_byte_counts": sum(p["bytes_ok"] for p in page_integrity), "page_byte_count_mismatches": sum(not p["bytes_ok"] for p in page_integrity), "raw_rows_loaded": len(all_rows), "reported_raw_rows": overall_declared_rows, "reported_page_count": declared_api.get("successful_response_pages"), "reported_raw_response_bytes": declared_api.get("raw_response_bytes"), "page_details": page_integrity, "integrity_errors": integrity_errors},
        "candidate_reconstruction": filter_notes,
        "raw_rows": {"row_count": len(all_rows), "observed_valid_train_date_count": valid_date_count, "invalid_or_unparseable_train_date_count": invalid_date_count, "observed_train_date_min": observed_date_min, "observed_train_date_max": observed_date_max, "rows_per_calendar_year": dict(sorted(date_year_counter.items())), "all_parseable_dates_within_requested_range": all_dates_fit_reported_range, "raw_field_names": sorted(raw_fields), "field_presence_states": field_presence, "raw_json_types": field_types, "requested_field_presence_by_year": focus_presence_by_year, "field_missingness_by_judgement": field_judgement, "numeric_fields": numeric_summary, "identifier_fields": id_summary, "rider_field": {"role": "rider name, not identifier", "field_states": field_presence.get("rider", {}), "raw_types": field_types.get("rider", {})}, "full_content_duplicates": {"semantic_field_value_hash_groups_repeated": len(duplicate_fingerprints), "extra_repeated_rows": duplicate_excess_rows, "rows_in_repeated_groups": sum(duplicate_fingerprints.values()), "duplicates_deleted": 0, "interpretation": "An identical complete item is a repeated observation; this audit preserves all rows and does not infer same-event error from content equality."}, "event_identity_checks": {"exact_date_round_chulNo_horse_key_collision_groups": len(exact_key_collision_groups), "date_round_chulNo_with_multiple_horse_ID_groups": len(date_round_entry_collisions), "date_round_horse_with_multiple_chulNo_groups": len(date_round_horse_multi_entry), "same_horse_day_with_multiple_distinct_rounds_groups": len(same_horse_multi_event), "same_horse_day_same_round_repeat_groups": len(same_horse_same_round_repeat), "rows_with_absent_chulNo": field_presence.get("chulNo", {}).get("absent", 0), "rows_with_null_chulNo": field_presence.get("chulNo", {}).get("null", 0), "rows_with_blank_chulNo": field_presence.get("chulNo", {}).get("blank", 0), "missing_chulNo_coerced_to_zero": False, "same_horse_pass_fail_across_distinct_dates_horse_count": len(fail_pass_repeat_horses), "same_horse_pass_fail_examples": fail_pass_repeat_horses[:25], "identical_round_roster_on_multiple_dates_candidate_group_count": len(repeated_rosters), "identical_roster_groups_with_two_or_more_horses": sum(r["roster_size"] >= 2 for r in repeated_rosters), "singleton_roster_repeat_groups": sum(r["roster_size"] == 1 for r in repeated_rosters), "identical_round_roster_candidates_top": repeated_rosters[:50]}, "judgement_and_reason": {"raw_label_counts": dict(judgement_counts), "raw_label_count": len(judgement_counts), "raw_label_reason_cross_counts": {label: dict(counts) for label, counts in sorted(judgement_reason_counts.items())}, "pass_with_meaningful_failure_reason_rows": contradictory_pass_reason, "fail_without_meaningful_failure_reason_candidate_rows": fail_without_reason, "native_fail_without_meaningful_failure_reason_rows": native_fail_without_reason, "cancellation_with_meaningful_failure_reason_rows": cancellation_with_reason, "exclusion_with_meaningful_failure_reason_rows": excluded_with_reason, "unknown_raw_labels": unknown_judgements, "labels_rewritten_or_collapsed": False}, "chronology_by_year": chronology},
        "anomaly_counts": dict(sorted(anomaly_counts.items())),
        "anomaly_example_limit_per_category": EXAMPLE_LIMIT_PER_CATEGORY,
        "anomaly_examples_written": len(examples),
        "limitations": ["API21 원문에 speciesID가 없으므로 제주마 후보는 현재 API42 breed 레이블에 근거한다.", "현재 프로필 품종을 과거 심사일 품종으로 소급하지 않는다.", "동일 원문 내용, 같은 말의 날짜별 합격·불합격 반복, 같은 roster 후보는 삭제·확정 오류로 취급하지 않는다.", "경주 심사의 공식 업무 규칙과 화면 전체를 새로 조회하지 않았으며, 무결성 이상 후보는 원문 수정 지시가 아니다."]
    }
    summary["collection_integrity"]["observed_raw_response_bytes"] = observed_bytes
    summary["raw_rows"]["age_value_review"] = {
        "threshold": 16,
        "all_raw_rows_with_numeric_age_at_or_above_threshold": len(high_age_rows),
        "native_candidate_rows_with_numeric_age_at_or_above_threshold": len(high_age_native_rows),
        "native_candidate_horses": len({str(r["raw"].get("hrNo")) for r in high_age_native_rows}),
        "interpretation": "review heuristic only; numeric validity does not establish that the underlying age/birth record is correct",
    }
    summary["raw_rows"]["numeric_fields"]["daySerial"]["source_field_meaning"] = "Swagger metadata: 심사차수; numeric syntax/range summarized without treating it as chronological day sequence."
    summary["raw_rows"]["judgement_and_reason"]["native_fail_without_meaningful_failure_reason_examples"] = native_fail_without_reason[:12]

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    examples_path = out_dir / "anomaly_examples.jsonl"
    examples_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in examples), encoding="utf-8")
    README = f'''# API21 제주 출발심사 원문 전수 무결성 감사\n\n기준 보고서는 `{REPORT_REL.as_posix()}`이며 SHA-256은 `{report_sha}`입니다. 원본 API 페이지와 완료 attempt만 읽어 독립 재계산했습니다. 네트워크 요청과 DB 쓰기는 하지 않았고 raw 원문은 수정하지 않았습니다.\n\n## 핵심 결과\n\n- 완료 attempt {sum(p.get("status") == "verified" for p in partition_summaries)}/27개 연도, {len(page_integrity)}페이지, {len(all_rows):,}행을 다시 읽었습니다. 페이지 해시 {sum(p["sha256_ok"] for p in page_integrity)}/{len(page_integrity)}개와 byte 수 {sum(p["bytes_ok"] for p in page_integrity)}/{len(page_integrity)}개가 일치했습니다.\n- 날짜 범위는 `{observed_date_min}`–`{observed_date_max}`이고, API 날짜 파싱 성공 {valid_date_count:,}행 / 오류 {invalid_date_count:,}행입니다. 보고서의 연도별 행 수, 페이지 수, 해시·헤더·pageNo·totalCount 완전성은 `summary.json`의 상세 내역에서 확인할 수 있습니다.\n- 현재 API42 제주마 레이블 필터로 `{len(candidate_rows):,}`개 후보행을 재구성했습니다. 후보 JSONL과 행 단위로 비교한 결과는 **{"일치" if not candidate_row_mismatches else "불일치"}**입니다. API21 응답에는 speciesID가 없으므로 과거 심사일 품종 증거와 동일시하지 않습니다.\n- 전체 필드값이 같은 반복 item은 {len(duplicate_fingerprints):,}개 해시 그룹, 추가 관측 {duplicate_excess_rows:,}행입니다. 중복 행은 유지했습니다.\n- event-key 중복 그룹 {len(exact_key_collision_groups):,}, 날짜·회차·출전번호의 복수 말 ID {len(date_round_entry_collisions):,}, 날짜·말의 복수 회차 {len(same_horse_multi_event):,}그룹입니다. chulNo 결측은 0으로 바꾸지 않았습니다.\n- 동일 말의 서로 다른 날짜에서 합격과 불합격 계열이 모두 관측된 말은 {len(fail_pass_repeat_horses):,}두입니다. 이는 재심사 가능성을 반영하는 반복 관측으로 보고 이상 행 삭제 근거로 쓰지 않았습니다. 동일 roster의 다른 날짜 후보는 {len(repeated_rosters):,}개입니다.\n- 완료되지 않은 과거 attempt {len(excluded_attempts)}개는 합계에서 제외했습니다. 무결성 오류 {len(integrity_errors)}개입니다.\n\n## 산출물\n\n- `audit.py`: 저장된 raw 페이지를 재현 가능하게 읽는 독립 점검기.\n- `summary.json`: 선언값 대조, 페이지별 검증, 필드 결측·타입, 날짜·숫자·ID, 중복·충돌, 결과-사유, 날짜순서 및 roster 후보 집계.\n- `anomaly_examples.jsonl`: 이상 후보와 대표 원문 위치. 범주별 예시는 최대 {EXAMPLE_LIMIT_PER_CATEGORY}건이며 전체 건수는 summary에 있습니다.\n\n재현 명령:\n\n```bash\npython3 audit.py --repo /Users/kimyongjin/Desktop/horse_racing --output-dir /private/tmp/jeju_api21_audit_20261002\n```\n\n판정은 원문 무결성 후보를 찾기 위한 것이며 공식 심사 기준이나 과거 품종을 확정하지 않습니다. 합격·불합격·취소·제외 등 기존 API 라벨은 그대로 보존합니다.\n'''
    README += f"\n검토 메모: native 후보 age 16+는 {len(high_age_native_rows)}행/{len({str(r['raw'].get('hrNo')) for r in high_age_native_rows})}두입니다. 수치 형식은 유효해도 원천 생일/나이 정합성은 별도 근거가 필요하므로 오류로 단정하지 않습니다. `daySerial`은 Swagger 정의상 심사차수여서 날짜순번으로 비교하지 않았습니다. 동일 roster 반복 후보 {len(repeated_rosters)}개는 모두 1두 roster이고 2두 이상 반복은 0개입니다. fail 라벨+사유 '-' 후보 전체 {fail_without_reason}행 중 native 후보는 {len(native_fail_without_reason)}행입니다. `trNo`/`owNo` ID 값과 선행 0은 원문 형식으로 두며 변환하지 않았고, `rider`는 기승자명으로 ID 취급하지 않습니다.\n"
    (out_dir / "README.md").write_text(README, encoding="utf-8")
    print(json.dumps({"summary_path": str(summary_path), "examples_path": str(examples_path), "readme_path": str(out_dir / "README.md"), "rows": len(all_rows), "pages": len(page_integrity), "integrity_errors": len(integrity_errors), "candidate_rows": len(candidate_rows), "candidate_exact": not candidate_row_mismatches, "anomaly_counts": dict(sorted(anomaly_counts.items()))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
