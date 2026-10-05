"""Normalize validated archived API16 snapshots and local dacom72 files."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from source_common import OBSERVATION_SCHEMA, ParquetRowWriter, iso_day, row_locator_hash, sha256_bytes, sha256_file


REPO = Path(__file__).resolve().parents[4]
OUT = REPO / "thoroughbred/research/20261002_medical_v1/source"
API_ROOT = REPO / "data/raw/kra/horse_medical"
TEXT_ROOT = REPO / "data/raw/kra_text/dacom72"
TEXT_MANIFEST = REPO / "data/raw/kra_text/_manifests/dacom72/manifest.jsonl"
START_DATE = "2010-01-01"
END_DATE = "2026-09-29"
MEET_NAMES = {1: {"서울"}, 2: {"제주"}, 3: {"부산경남", "영남", "부경"}, 4: {"영천"}}
DAILY_FILENAME = re.compile(r"page_(\d{4})_(\d{13})_([0-9a-f]{12})\.json$")
DATE_LIKE = re.compile(rb"^\s*20\d{2}[./-]\d{1,2}[./-]\d{1,2}")
OLD_REGEX = re.compile(
    r"^\s*(20\d\d)[./-](\d\d)[./-](\d\d)\s+(\S+)\s+"
    r"(\d{1,2})\s+(\S+)\s+(.+?)\s*$"
)


def unpack_api(raw: bytes) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(raw)
    envelope = payload.get("response", payload)
    if not isinstance(envelope, dict):
        raise ValueError("response_envelope_not_object")
    header, body = envelope.get("header"), envelope.get("body")
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise ValueError("response_header_or_body_not_object")
    container = body.get("items")
    raw_items = container.get("item", []) if isinstance(container, dict) else []
    if raw_items is None:
        items: list[dict[str, Any]] = []
    elif isinstance(raw_items, dict):
        items = [raw_items]
    elif isinstance(raw_items, list) and all(isinstance(item, dict) for item in raw_items):
        items = raw_items
    else:
        raise ValueError("item_container_not_rows")
    return header, body, items


def pydict_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        table = pa.Table.from_pylist(rows)
    else:
        table = pa.table({"empty_result": pa.array([], type=pa.string())})
    pq.write_table(table, path, compression="zstd")


def archived_meet_date(path: Path) -> tuple[str, int, str]:
    parts = path.relative_to(API_ROOT).parts
    if len(parts) < 6:
        raise ValueError("unexpected_api_raw_path")
    try:
        request_date = date(int(parts[0]), int(parts[1]), int(parts[2])).isoformat()
    except ValueError as exc:
        raise ValueError("invalid_request_date_in_path") from exc
    meet_match = re.fullmatch(r"meet_(\d+)", parts[3])
    run_match = re.fullmatch(r"run_(\d+)", parts[4])
    if meet_match is None or run_match is None:
        raise ValueError("invalid_meet_or_run_path")
    return request_date, int(meet_match.group(1)), parts[4]


def collect_archived_daily() -> dict[str, Any]:
    candidates = sorted(API_ROOT.rglob("*.json")) if API_ROOT.exists() else []
    inventory: list[dict[str, Any]] = []
    page_ledger: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    runs: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    coverage_counter: Counter[tuple[int, int]] = Counter()
    coverage_days: dict[tuple[int, int], set[str]] = defaultdict(set)
    coverage_horses: dict[tuple[int, int], set[str]] = defaultdict(set)
    coverage_files: dict[tuple[int, int], set[str]] = defaultdict(set)
    good_page_count = 0
    invalid_count = 0
    archived_obs_count = 0
    archived_scope_exclusion_count = 0

    with ParquetRowWriter(OUT / "api16_archived_daily_observations.parquet", OBSERVATION_SCHEMA) as obs_writer:
        for path in candidates:
            rel = path.relative_to(REPO).as_posix()
            raw = path.read_bytes()
            sha = sha256_bytes(raw)
            filename_match = DAILY_FILENAME.fullmatch(path.name)
            record: dict[str, Any] = {
                "source_kind": "api16_archived", "source_cohort": "archived_daily_snapshot",
                "source_path": rel, "source_sha256": sha, "source_bytes": len(raw),
                "filename_page_no": int(filename_match.group(1)) if filename_match else None,
                "filename_retrieved_at_ms": filename_match.group(2) if filename_match else None,
                "filename_sha256_prefix": filename_match.group(3) if filename_match else None,
                "filename_hash_prefix_valid": bool(filename_match and sha.startswith(filename_match.group(3))),
                "response_result_code": None, "response_page_no": None,
                "response_total_count": None, "response_num_of_rows": None,
                "response_item_count": 0, "requested_date_from_path": None,
                "requested_meet_from_path": None, "returned_date_min": None,
                "returned_date_max": None, "returned_meets": None,
                "page_capture_status": "unverified", "scope_status": "unverified",
            }
            try:
                request_date, meet, run_id = archived_meet_date(path)
                record["requested_date_from_path"] = request_date
                record["requested_meet_from_path"] = meet
                header, body, items = unpack_api(raw)
                result_code = str(header.get("resultCode", ""))
                page_no = int(body.get("pageNo") or 0)
                total_count = int(body.get("totalCount") or 0)
                page_size = int(body.get("numOfRows") or 0)
                record.update({
                    "response_result_code": result_code, "response_page_no": page_no,
                    "response_total_count": total_count, "response_num_of_rows": page_size,
                    "response_item_count": len(items),
                })
                if not filename_match or int(filename_match.group(1)) != page_no:
                    record["page_capture_status"] = "filename_page_number_mismatch"
                    raise ValueError("filename_page_number_mismatch")
                if not record["filename_hash_prefix_valid"]:
                    record["page_capture_status"] = "filename_hash_prefix_mismatch"
                    raise ValueError("filename_hash_prefix_mismatch")
                if result_code not in {"00", "0000"}:
                    record["page_capture_status"] = "api_error_payload"
                    record["scope_status"] = "not_reused"
                    raise ValueError("api_error_payload")
                if page_no < 1 or page_size < 1 or len(items) > page_size:
                    record["page_capture_status"] = "invalid_page_metadata"
                    raise ValueError("invalid_page_metadata")
                retrieved_at = datetime.fromtimestamp(int(filename_match.group(2)) / 1000, UTC).isoformat(timespec="milliseconds")
                returned_dates: list[str] = []
                returned_meets: set[str] = set()
                capture_id = f"{request_date}:meet_{meet}:{run_id}"
                for row_no, item in enumerate(items, 1):
                    event_date = iso_day(item.get("clinicDate"))
                    meet_raw = None if item.get("meet") is None else str(item.get("meet"))
                    if event_date:
                        returned_dates.append(event_date)
                    if meet_raw:
                        returned_meets.add(meet_raw)
                    if event_date != request_date:
                        reason = "returned_event_date_does_not_match_request_path"
                    elif meet_raw not in MEET_NAMES.get(meet, set()):
                        reason = "returned_meet_does_not_match_request_path"
                    elif meet not in {1, 3}:
                        reason = "meet_outside_research_scope"
                    elif not START_DATE <= event_date <= END_DATE:
                        reason = "event_date_outside_research_cutoff"
                    else:
                        reason = None
                    row_rel = rel
                    page_row_hash = row_locator_hash("api16_archived", row_rel, page_no=page_no, row_no=row_no)
                    if reason:
                        exclusions.append({
                            "source_kind": "api16_archived", "source_cohort": "archived_daily_snapshot",
                            "reason": reason, "event_date": event_date, "request_date": request_date,
                            "request_meet": meet, "source_path": rel, "source_sha256": sha,
                            "capture_id": capture_id, "page_no": page_no, "row_no": row_no,
                            "source_row_hash": page_row_hash,
                            "raw_payload_json": json.dumps(item, ensure_ascii=False, separators=(",", ":")),
                        })
                        archived_scope_exclusion_count += 1
                        continue
                    obs_writer.append({
                        "source_kind": "api16_archived", "source_cohort": "archived_daily_snapshot",
                        "event_date": event_date, "source_file_date": request_date,
                        "meet_code": meet, "meet_raw": meet_raw,
                        "horse_name_raw": None if item.get("hrName") is None else str(item.get("hrName")),
                        "hr_no_raw": None if item.get("hrNo") is None else str(item.get("hrNo")),
                        "stable_no_raw": None,
                        "part_raw": None if item.get("part") is None else str(item.get("part")),
                        "hospital_name_raw": None if item.get("hospiName") is None else str(item.get("hospiName")),
                        "ill_name1_raw": None if item.get("illName1") is None else str(item.get("illName1")),
                        "ill_name2_raw": None if item.get("illName2") is None else str(item.get("illName2")),
                        "diagnosis_rpt_raw": None,
                        "raw_payload_json": json.dumps(item, ensure_ascii=False, separators=(",", ":")),
                        "raw_line": None, "decode_has_replacement": None,
                        "source_path": rel, "source_sha256": sha, "capture_id": capture_id,
                        "source_captured_at_utc": retrieved_at,
                        "capture_timestamp_basis": "raw_store_filename_retrieved_at_ms",
                        "page_no": page_no, "row_no": row_no, "line_no": None,
                        "request_year": int(request_date[:4]), "request_meet": meet,
                        "response_result_code": result_code,
                        "response_result_message": str(header.get("resultMsg", "")),
                        "source_row_hash": page_row_hash,
                    })
                    archived_obs_count += 1
                    key = (int(event_date[:4]), meet)
                    coverage_counter[key] += 1
                    coverage_days[key].add(event_date)
                    coverage_files[key].add(rel)
                    horse_name = item.get("hrName")
                    if horse_name:
                        coverage_horses[key].add(str(horse_name))
                record.update({
                    "returned_date_min": min(returned_dates) if returned_dates else None,
                    "returned_date_max": max(returned_dates) if returned_dates else None,
                    "returned_meets": "|".join(sorted(returned_meets)),
                    "capture_id": capture_id,
                    "source_captured_at_utc": retrieved_at,
                    "capture_timestamp_basis": "raw_store_filename_retrieved_at_ms",
                    "page_capture_status": "success_header_and_page_metadata_verified",
                    "scope_status": "request_scope_verified_rows_retained_or_excluded",
                })
                page_ledger.append({
                    "source_kind": "api16_archived", "source_cohort": "archived_daily_snapshot",
                    "capture_id": capture_id, "source_path": rel, "source_sha256": sha,
                    "source_bytes": len(raw), "source_captured_at_utc": retrieved_at,
                    "capture_timestamp_basis": "raw_store_filename_retrieved_at_ms",
                    "request_date": request_date, "request_meet": meet,
                    "page_no": page_no, "page_size": page_size,
                    "reported_total_count": total_count, "response_row_count": len(items),
                    "response_result_code": result_code,
                    "filename_hash_prefix_valid": True,
                    "scope_history_completeness": "daily capture only; not year-complete evidence",
                })
                runs[(request_date, meet, run_id)].append(page_ledger[-1])
                good_page_count += 1
            except Exception as exc:
                invalid_count += 1
                record["parse_or_validation_error"] = str(exc)
                exclusions.append({
                    "source_kind": "api16_archived", "source_cohort": "archived_daily_snapshot",
                    "reason": str(exc), "source_path": rel, "source_sha256": sha,
                    "request_date": record.get("requested_date_from_path"),
                    "request_meet": record.get("requested_meet_from_path"),
                })
            inventory.append(record)

    # A response page is useful raw history even when another page from its run
    # is missing; the ledger distinguishes that capture from a complete request.
    for (request_date, meet, run_id), pages in runs.items():
        page_nos = sorted(int(page["page_no"]) for page in pages)
        total_counts = {int(page["reported_total_count"]) for page in pages}
        page_sizes = {int(page["page_size"]) for page in pages}
        total_pages = None
        if len(total_counts) == 1 and len(page_sizes) == 1 and next(iter(page_sizes)) > 0:
            total_pages = (next(iter(total_counts)) + next(iter(page_sizes)) - 1) // next(iter(page_sizes))
        row_sum = sum(int(page["response_row_count"]) for page in pages)
        status = "complete_daily_page_set" if (
            total_pages is not None
            and page_nos == list(range(1, total_pages + 1))
            and row_sum == next(iter(total_counts))
        ) else "partial_daily_page_set"
        for page in pages:
            page["daily_request_page_set_status"] = status
    pydict_parquet(OUT / "existing_raw_inventory.parquet", inventory)
    pydict_parquet(OUT / "api16_archived_page_ledger.parquet", page_ledger)
    pydict_parquet(OUT / "api16_archived_exclusions.parquet", exclusions)
    coverage = []
    for year in range(2010, 2027):
        for meet in (1, 3):
            key = (year, meet)
            coverage.append({
                "source_kind": "api16_archived", "source_cohort": "archived_daily_snapshot",
                "event_year": year, "meet_code": meet,
                "observation_occurrence_count": coverage_counter[key],
                "distinct_event_date_count": len(coverage_days[key]),
                "distinct_horse_name_count": len(coverage_horses[key]),
                "source_file_count": len(coverage_files[key]),
                "historical_completeness": "partial daily snapshots; coverage incomplete or unknown",
            })
    pydict_parquet(OUT / "archived_daily_coverage.parquet", coverage)
    manifest = {
        "source_kind": "api16_archived", "source_cohort": "archived_daily_snapshot",
        "input_root": "data/raw/kra/horse_medical",
        "candidate_page_file_count": len(candidates), "validated_success_page_count": good_page_count,
        "invalid_or_error_page_count": invalid_count,
        "normalized_in_scope_observation_occurrences": archived_obs_count,
        "scope_excluded_row_count": archived_scope_exclusion_count,
        "exclusions_parquet": "api16_archived_exclusions.parquet",
        "page_inventory_parquet": "existing_raw_inventory.parquet",
        "page_ledger_parquet": "api16_archived_page_ledger.parquet",
        "coverage_parquet": "archived_daily_coverage.parquet",
        "year_completeness_claimed": False,
        "capture_time_basis": "raw_store filename retrieved_at_ms, checked against full file SHA-256 prefix",
    }
    safe_manifest(OUT / "api16_archived_capture_manifest.json", manifest)
    return manifest


def path_scope(path: Path) -> tuple[int, int, str]:
    parts = path.relative_to(TEXT_ROOT).parts
    meet_match = re.fullmatch(r"meet=(\d+)", parts[0]) if parts else None
    year_match = re.fullmatch(r"year=(\d{4})", parts[1]) if len(parts) > 1 else None
    month_match = next((re.fullmatch(r"month=(\d{2})", part) for part in parts if re.fullmatch(r"month=(\d{2})", part)), None)
    day_match = next((re.fullmatch(r"day=(\d{2})", part) for part in parts if re.fullmatch(r"day=(\d{2})", part)), None)
    if not meet_match or not year_match or not month_match or not day_match:
        raise ValueError("invalid_dacom72_path_scope")
    meet, year, month, day_no = int(meet_match.group(1)), int(year_match.group(1)), int(month_match.group(1)), int(day_match.group(1))
    try:
        file_date = date(year, month, day_no).isoformat()
    except ValueError as exc:
        raise ValueError("invalid_dacom72_file_date") from exc
    return meet, year, file_date


def dacom72_capture_evidence() -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    """Match downloaded metadata by exact repository path and complete file hash.

    Only the explicitly safe evidence fields are copied; manifest URLs are never
    written to outputs or logs. Ambiguous or absent matches stop normalization.
    """
    if not TEXT_MANIFEST.is_file():
        raise FileNotFoundError(TEXT_MANIFEST)
    manifest_hash = sha256_file(TEXT_MANIFEST)
    matches: dict[tuple[str, str], dict[str, Any]] = {}
    downloaded_count = 0
    with TEXT_MANIFEST.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid_dacom72_manifest_jsonl_line_{line_no}") from exc
            if row.get("status") != "downloaded":
                continue
            local_path, file_hash = row.get("local_path"), row.get("sha256")
            retrieved_at_ms = row.get("retrieved_at_ms")
            run_id = row.get("run_id")
            if (not isinstance(local_path, str) or not isinstance(file_hash, str)
                    or not isinstance(retrieved_at_ms, int) or not isinstance(run_id, int)):
                continue
            downloaded_count += 1
            key = (local_path, file_hash)
            if key in matches:
                matches[key]["duplicate_count"] += 1
            else:
                matches[key] = {"retrieved_at_ms": retrieved_at_ms, "run_id": run_id,
                                "duplicate_count": 1}
    metadata = {
        "manifest_path": TEXT_MANIFEST.relative_to(REPO).as_posix(),
        "manifest_sha256": manifest_hash,
        "downloaded_metadata_row_count": downloaded_count,
        "match_key": ["local_path", "sha256"],
        "timestamp_field": "retrieved_at_ms",
        "selection_rule": "exact path and full SHA-256; exactly one downloaded entry is required",
        "capture_id_basis": "dacom72:manifest-run:<run_id>",
        "source_url_copied": False,
    }
    return matches, metadata


def decode_field(value: bytes) -> tuple[str | None, bool]:
    decoded = value.decode("cp949", errors="replace")
    decoded = decoded.strip()
    return (decoded or None), ("\ufffd" in decoded)


def parse_fixed_width(raw_line: bytes) -> dict[str, Any] | None:
    """Decode the independently verified CP949 byte layout; never split diagnoses."""
    if len(raw_line) < 45:
        return None
    if raw_line[10:11] != b" " or raw_line[31:32] != b" " or raw_line[44:45] != b" ":
        return None
    event_date = iso_day(raw_line[0:10].decode("ascii", errors="replace"))
    stable_text = raw_line[29:31].decode("ascii", errors="replace").strip()
    if event_date is None or not stable_text.isdigit():
        return None
    horse, bad_horse = decode_field(raw_line[11:29])
    hospital, bad_hospital = decode_field(raw_line[32:44])
    diagnosis, bad_diagnosis = decode_field(raw_line[45:])
    if hospital is None or diagnosis is None:
        return None
    return {
        "event_date": event_date,
        "horse_name_raw": horse,
        "stable_no_raw": stable_text,
        "hospital_name_raw": hospital,
        "diagnosis_rpt_raw": diagnosis,
        "decode_has_replacement": bad_horse or bad_hospital or bad_diagnosis,
    }


def safe_manifest(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def collect_dacom72() -> dict[str, Any]:
    capture_entries, capture_metadata = dacom72_capture_evidence()
    paths = []
    for path in sorted(TEXT_ROOT.glob("meet=*/year=*/month=*/day=*/*.rpt")):
        meet, year, _ = path_scope(path)
        if meet in {1, 3} and 2010 <= year <= 2026:
            paths.append(path)
    file_ledger: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    layout_diff_count = 0
    layout_diff_sample: list[dict[str, Any]] = []
    year_meet_count: Counter[tuple[int, int]] = Counter()
    year_meet_days: dict[tuple[int, int], set[str]] = defaultdict(set)
    year_meet_horses: dict[tuple[int, int], set[str]] = defaultdict(set)
    year_meet_files: dict[tuple[int, int], set[str]] = defaultdict(set)
    physical_lines = 0
    candidate_lines = 0
    parsed_rows = 0
    quarantine_count = 0
    replacement_rows = 0
    used_capture_keys: set[tuple[str, str]] = set()

    layout_schema = pa.schema([
        ("source_path", pa.string()), ("source_sha256", pa.string()),
        ("line_no", pa.int32()), ("raw_line", pa.string()),
        ("old_regex_matched", pa.bool_()), ("old_regex_horse_name", pa.string()),
        ("old_regex_stable_no", pa.string()), ("old_regex_hospital", pa.string()),
        ("old_regex_diagnosis", pa.string()), ("fixed_horse_name", pa.string()),
        ("fixed_stable_no", pa.string()), ("fixed_hospital", pa.string()),
        ("fixed_diagnosis", pa.string()), ("changed_fields_json", pa.string()),
    ])
    with ParquetRowWriter(OUT / "dacom72_observations.parquet", OBSERVATION_SCHEMA, batch_size=32_000) as obs_writer, \
         ParquetRowWriter(OUT / "dacom72_layout_reconciliation.parquet", layout_schema, batch_size=32_000) as diff_writer:
        for path in paths:
            meet, file_year, file_date = path_scope(path)
            rel = path.relative_to(REPO).as_posix()
            raw_file = path.read_bytes()
            source_hash = sha256_bytes(raw_file)
            capture = capture_entries.get((rel, source_hash))
            if capture is None or capture["duplicate_count"] != 1:
                raise ValueError(f"dacom72_capture_metadata_not_unique_for:{rel}")
            used_capture_keys.add((rel, source_hash))
            captured_at = datetime.fromtimestamp(capture["retrieved_at_ms"] / 1000, UTC).isoformat(
                timespec="milliseconds"
            ).replace("+00:00", "Z")
            capture_id = f"dacom72:manifest-run:{capture['run_id']}"
            raw_lines = raw_file.splitlines()
            per_file_parsed = 0
            per_file_quarantine = 0
            event_dates: list[str] = []
            replacement_file = False
            for line_no, raw_line_bytes in enumerate(raw_lines, 1):
                physical_lines += 1
                if not DATE_LIKE.match(raw_line_bytes):
                    if raw_line_bytes.strip():
                        # Non-date headers/text are not medical candidates.
                        pass
                    continue
                candidate_lines += 1
                raw_line = raw_line_bytes.decode("cp949", errors="replace")
                parsed = parse_fixed_width(raw_line_bytes)
                if parsed is None:
                    per_file_quarantine += 1
                    quarantine_count += 1
                    exclusions.append({
                        "source_kind": "dacom72", "source_cohort": "rpt",
                        "source_path": rel, "source_sha256": source_hash,
                        "source_file_date": file_date, "meet_code": meet,
                        "line_no": line_no, "raw_line": raw_line,
                        "reason": "date_like_line_failed_fixed_width_medical_parse",
                        "source_row_hash": row_locator_hash("dacom72", rel, line_no=line_no),
                    })
                    continue
                event_date = parsed["event_date"]
                if not START_DATE <= event_date <= END_DATE:
                    per_file_quarantine += 1
                    quarantine_count += 1
                    exclusions.append({
                        "source_kind": "dacom72", "source_cohort": "rpt",
                        "source_path": rel, "source_sha256": source_hash,
                        "source_file_date": file_date, "event_date": event_date,
                        "meet_code": meet, "line_no": line_no, "raw_line": raw_line,
                        "reason": "event_date_outside_research_scope",
                        "source_row_hash": row_locator_hash("dacom72", rel, line_no=line_no),
                    })
                    continue
                parsed_rows += 1
                per_file_parsed += 1
                event_dates.append(event_date)
                replacement_file = replacement_file or parsed["decode_has_replacement"]
                replacement_rows += int(parsed["decode_has_replacement"])
                obs_writer.append({
                    "source_kind": "dacom72", "source_cohort": "rpt",
                    "event_date": event_date, "source_file_date": file_date,
                    "meet_code": meet, "meet_raw": "서울" if meet == 1 else "영남",
                    "horse_name_raw": parsed["horse_name_raw"], "hr_no_raw": None,
                    "stable_no_raw": parsed["stable_no_raw"], "part_raw": None,
                    "hospital_name_raw": parsed["hospital_name_raw"],
                    "ill_name1_raw": None, "ill_name2_raw": None,
                    "diagnosis_rpt_raw": parsed["diagnosis_rpt_raw"],
                    "raw_payload_json": None, "raw_line": raw_line,
                    "decode_has_replacement": parsed["decode_has_replacement"],
                    "source_path": rel, "source_sha256": source_hash,
                    "capture_id": capture_id, "source_captured_at_utc": captured_at,
                    "capture_timestamp_basis": "dacom72_manifest_exact_path_sha256_retrieved_at_ms",
                    "page_no": None, "row_no": None, "line_no": line_no,
                    "request_year": None, "request_meet": None,
                    "response_result_code": None, "response_result_message": None,
                    "source_row_hash": row_locator_hash("dacom72", rel, line_no=line_no),
                })
                key = (int(event_date[:4]), meet)
                year_meet_count[key] += 1
                year_meet_days[key].add(event_date)
                year_meet_files[key].add(rel)
                if parsed["horse_name_raw"]:
                    year_meet_horses[key].add(parsed["horse_name_raw"])

                old = OLD_REGEX.match(raw_line)
                old_fields = {
                    "horse_name": old.group(4) if old else None,
                    "stable_no": old.group(5) if old else None,
                    "hospital": old.group(6) if old else None,
                    "diagnosis": old.group(7).rstrip() if old else None,
                }
                fixed_fields = {
                    "horse_name": parsed["horse_name_raw"],
                    "stable_no": parsed["stable_no_raw"],
                    "hospital": parsed["hospital_name_raw"],
                    "diagnosis": parsed["diagnosis_rpt_raw"],
                }
                changed = [field for field in fixed_fields if old_fields[field] != fixed_fields[field]]
                if changed:
                    layout_diff_count += 1
                    diff_writer.append({
                        "source_path": rel, "source_sha256": source_hash,
                        "line_no": line_no, "raw_line": raw_line,
                        "old_regex_matched": old is not None,
                        "old_regex_horse_name": old_fields["horse_name"],
                        "old_regex_stable_no": old_fields["stable_no"],
                        "old_regex_hospital": old_fields["hospital"],
                        "old_regex_diagnosis": old_fields["diagnosis"],
                        "fixed_horse_name": fixed_fields["horse_name"],
                        "fixed_stable_no": fixed_fields["stable_no"],
                        "fixed_hospital": fixed_fields["hospital"],
                        "fixed_diagnosis": fixed_fields["diagnosis"],
                        "changed_fields_json": json.dumps(changed, ensure_ascii=False),
                    })
            file_ledger.append({
                "source_kind": "dacom72", "source_cohort": "rpt",
                "source_path": rel, "source_sha256": source_hash,
                "source_bytes": len(raw_file), "capture_id": capture_id,
                "source_captured_at_utc": captured_at,
                "capture_timestamp_basis": "dacom72_manifest_exact_path_sha256_retrieved_at_ms",
                "decode_encoding": "cp949", "decode_has_replacement": replacement_file,
                "source_file_date": file_date, "path_year": file_year, "meet_code": meet,
                "physical_line_count": len(raw_lines),
                "candidate_date_line_count": sum(1 for row in raw_lines if DATE_LIKE.match(row)),
                "parsed_in_scope_row_count": per_file_parsed,
                "quarantined_candidate_line_count": per_file_quarantine,
                "body_event_date_min": min(event_dates) if event_dates else None,
                "body_event_date_max": max(event_dates) if event_dates else None,
                "body_year_matches_path_year": None if not event_dates else all(day[:4] == str(file_year) for day in event_dates),
            })

    if len(paths) != len(used_capture_keys):
        raise ValueError("dacom72_manifest_exact_match_count_differs_from_input_file_count")
    pydict_parquet(OUT / "dacom72_file_ledger.parquet", file_ledger)
    pydict_parquet(OUT / "dacom72_exclusions.parquet", exclusions)
    coverage = []
    for year in range(2010, 2027):
        for meet in (1, 3):
            key = (year, meet)
            coverage.append({
                "source_kind": "dacom72", "source_cohort": "rpt",
                "event_year": year, "meet_code": meet,
                "observation_occurrence_count": year_meet_count[key],
                "distinct_event_date_count": len(year_meet_days[key]),
                "distinct_horse_name_count": len(year_meet_horses[key]),
                "source_file_count": len(year_meet_files[key]),
                "historical_completeness": "local file inventory only; event history completeness unverified",
            })
    pydict_parquet(OUT / "dacom72_year_meet_coverage.parquet", coverage)
    manifest = {
        "source_kind": "dacom72", "source_cohort": "rpt",
        "input_root": "data/raw/kra_text/dacom72",
        "input_file_count": len(paths), "physical_line_count": physical_lines,
        "date_like_candidate_line_count": candidate_lines,
        "normalized_in_scope_occurrences": parsed_rows,
        "quarantined_date_like_line_count": quarantine_count,
        "decode_replacement_row_count": replacement_rows,
        "layout_reconciliation_difference_count": layout_diff_count,
        "fixed_width_layout": {
            "encoding": "CP949 bytes",
            "date": "0:10", "separator_1": "10:11", "horse_name": "11:29",
            "stable_no": "29:31", "separator_2": "31:32", "hospital": "32:44",
            "separator_3": "44:45", "single_combined_diagnosis": "45:end (right padding trimmed)",
            "raw_line_preserved": True,
        },
        "file_date_vs_body_date": "captured separately; mismatch is not a parse error",
        "official_horse_id": "null in dacom72 observations; no name-only linkage",
        "capture_time_evidence": {
            **capture_metadata,
            "input_file_exact_match_count": len(paths),
            "capture_time_verified_file_count": len(file_ledger),
        },
        "outputs": ["dacom72_observations.parquet", "dacom72_file_ledger.parquet",
                    "dacom72_year_meet_coverage.parquet", "dacom72_exclusions.parquet",
                    "dacom72_layout_reconciliation.parquet"],
    }
    safe_manifest(OUT / "dacom72_capture_manifest.json", manifest)
    return manifest


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dacom72-only", action="store_true",
                        help="rebuild only local text source outputs; leave archived API snapshots untouched")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if not args.dacom72_only:
        archived = collect_archived_daily()
        print(json.dumps({"source_cohort": "archived_daily_snapshot",
                          "files": archived["candidate_page_file_count"],
                          "observations": archived["normalized_in_scope_observation_occurrences"],
                          "invalid_pages": archived["invalid_or_error_page_count"]}), flush=True)
    text = collect_dacom72()
    print(json.dumps({"source_cohort": "rpt", "files": text["input_file_count"],
                      "observations": text["normalized_in_scope_occurrences"],
                      "quarantine": text["quarantined_date_like_line_count"],
                      "layout_differences": text["layout_reconciliation_difference_count"]}), flush=True)


if __name__ == "__main__":
    main()
