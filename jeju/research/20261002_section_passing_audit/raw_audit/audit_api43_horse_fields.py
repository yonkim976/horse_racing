#!/usr/bin/env python3
"""Read-only audit of horse-level API4_3 section times and passing orders."""

from __future__ import annotations

import collections
import csv
import hashlib
import json
import math
import pathlib
import re
import sqlite3
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[4]
DB_PATH = ROOT / "jeju/data/jeju_native_core.sqlite3"
OUT = ROOT / "jeju/research/20261002_section_passing_audit/raw_audit"
EXCLUSIONS = ROOT / "jeju/data/horse_exclusions.json"
SMALL_BEAR_RECEIPT = ROOT / "jeju/maintenance/small_bear_removal_20261002/deletion_receipt.json"
CLEANUP_README = ROOT / "jeju/maintenance/zero_time_cleanup_20260930/README.md"
CANCELLATION_REVIEW = ROOT / "jeju/research/20261001_user_cancellation_confirmation/confirmed_76_review.jsonl"

TIME_LABELS = {
    "jeS1fTime": "S1F",
    "je_1cTime": "1C",
    "je_2cTime": "2C",
    "je_3cTime": "3C",
    "je_4cTime": "4C",
    "jeG3fTime": "G3F",
    "jeG1fTime": "G1F",
}
ORDER_LABELS = {
    "sjS1fOrd": "S1F",
    "sj_1cOrd": "1C",
    "sj_2cOrd": "2C",
    "sj_3cOrd": "3C",
    "sj_4cOrd": "4C",
    "sjG3fOrd": "G3F",
    "sjG1fOrd": "G1F",
}
POINT_ORDER = ["jeS1fTime", "je_1cTime", "je_2cTime", "je_3cTime", "je_4cTime"]
TIME_KEY_RE = re.compile(r"je.*Time\Z")
ORDER_KEY_RE = re.compile(r"sj.*Ord\Z")


def number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
    elif isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return parsed if math.isfinite(parsed) else None


def kind(value: Any, present: bool) -> str:
    if not present:
        return "missing_key"
    if value is None:
        return "json_null"
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
    return type(value).__name__


def category(value: Any, present: bool, ordinal: bool = False) -> str:
    if not present:
        return "missing_key"
    if value is None:
        return "json_null"
    parsed = number(value)
    if parsed is None:
        return "invalid_or_non_numeric"
    if ordinal and not parsed.is_integer():
        return "non_integer_ordinal"
    if parsed == 0:
        return "zero"
    if parsed < 0:
        return "negative"
    return "positive"


def write_csv(path: pathlib.Path, records: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def safe_project_path(raw_relative_path: str) -> pathlib.Path | None:
    candidate = (ROOT / raw_relative_path).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError:
        return None
    return candidate


def manifest_page_match(page_path: pathlib.Path, attempt_id: str, expected_sha: str) -> tuple[str, bool]:
    for ancestor in page_path.parents:
        manifest_path = ancestor / "attempt_manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("attempt_id") != attempt_id:
            continue
        for item in manifest.get("source_pages", []):
            if item.get("response_sha256") != expected_sha:
                continue
            relative = item.get("response_file")
            if not relative:
                continue
            possible = [manifest_path.parent / relative, manifest_path.parent.parent / relative]
            for candidate in possible:
                if candidate.resolve() == page_path.resolve():
                    return str(manifest_path.relative_to(ROOT)), True
    return "", False


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.is_file():
        raise FileNotFoundError(DB_PATH)

    # Static query, read-only URI, and one pass over the analysis view. The
    # denominator is the complete API4_3 race_result_rows entrant set, which
    # can include mixed-breed runners outside the Jeju candidate view.
    uri = DB_PATH.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    query = """
    WITH full_race AS (
        SELECT race_date, meet_code, race_number,
               count(*) AS all_api43_rows,
               sum(CASE WHEN finish_time_seconds > 0 THEN 1 ELSE 0 END) AS all_positive_finish_rows
        FROM race_result_rows
        GROUP BY race_date, meet_code, race_number
    )
    SELECT c.api_record_id, c.race_date, c.meet_code, c.race_number,
           c.horse_number, c.horse_id, c.horse_name, c.race_distance_m,
           c.finish_position, c.finish_status_raw, c.finish_time_seconds,
           c.breed_assessment, c.api4_3_payload_sha256,
           c.api4_3_source_artifact_id, c.api4_3_source_page_sha256,
           c.api4_3_source_page_path, a.payload_json, a.payload_sha256,
           a.record_index, f.all_api43_rows, f.all_positive_finish_rows,
           sa.attempt_id, sa.response_bytes, sa.sha256 AS artifact_page_sha256
    FROM jeju_race_analysis_2026 c
    JOIN api_records a USING(api_record_id)
    JOIN source_artifacts sa ON sa.source_artifact_id = a.source_artifact_id
    LEFT JOIN full_race f
      ON f.race_date = c.race_date AND f.meet_code = c.meet_code
     AND f.race_number = c.race_number
    """

    rows: list[dict[str, Any]] = []
    event_rows: dict[tuple[str, int, int], list[dict[str, Any]]] = collections.defaultdict(list)
    field_keys: set[str] = set()
    type_counts: collections.Counter[tuple[str, str]] = collections.Counter()
    category_counts: collections.Counter[tuple[str, str]] = collections.Counter()
    value_counts: collections.Counter[tuple[str, str, str]] = collections.Counter()
    year_distance_counts: collections.Counter[tuple[str, str, str, str]] = collections.Counter()
    first_positive_counts: collections.Counter[tuple[str, str, str]] = collections.Counter()
    nonzero_signatures: collections.Counter[tuple[str, str, str]] = collections.Counter()
    partial_samples: dict[tuple[str, str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    no_time_cases: list[dict[str, Any]] = []
    no_order_cases: list[dict[str, Any]] = []
    over_field_cases: list[dict[str, Any]] = []
    consistency_cases: list[dict[str, Any]] = []
    rank_values_by_event: dict[tuple[str, int, int, str, int], list[dict[str, Any]]] = collections.defaultdict(list)
    event_seen: set[tuple[str, int, int]] = set()
    duplicate_api_ids: set[int] = set()
    year_min = year_max = None

    cursor = conn.execute(query)
    for dbrow in cursor:
        api_id = int(dbrow["api_record_id"])
        if api_id in duplicate_api_ids:
            raise AssertionError(f"duplicate analysis api_record_id: {api_id}")
        duplicate_api_ids.add(api_id)
        raw = json.loads(dbrow["payload_json"])
        if not isinstance(raw, dict):
            raise AssertionError(f"API4_3 payload is not an object for {api_id}")
        time_keys = sorted(k for k in raw if TIME_KEY_RE.fullmatch(k))
        order_keys = sorted(k for k in raw if ORDER_KEY_RE.fullmatch(k))
        field_keys.update(time_keys)
        field_keys.update(order_keys)
        year = str(dbrow["race_date"] or "")[:4]
        distance = "NULL" if dbrow["race_distance_m"] is None else str(dbrow["race_distance_m"])
        finish = number(dbrow["finish_time_seconds"])
        positive_finish = finish is not None and finish > 0
        valid_finish = positive_finish and number(dbrow["finish_position"]) is not None and 1 <= number(dbrow["finish_position"]) < 90
        time_numeric: dict[str, float | None] = {}
        order_numeric: dict[str, float | None] = {}
        time_present = {key: key in raw for key in time_keys}
        order_present = {key: key in raw for key in order_keys}
        time_signature: list[str] = []
        for key in time_keys:
            value = raw[key]
            value_kind = kind(value, True)
            value_category = category(value, True)
            parsed = number(value)
            type_counts[(key, value_kind)] += 1
            category_counts[(key, value_category)] += 1
            value_counts[(key, value_kind, json.dumps(value, ensure_ascii=False, sort_keys=True))] += 1
            year_distance_counts[(year, distance, key, value_category)] += 1
            time_numeric[key] = parsed
            time_signature.append(f"{key}={value_category}")
        for key in order_keys:
            value = raw[key]
            value_kind = kind(value, True)
            value_category = category(value, True, ordinal=True)
            parsed = number(value)
            if parsed is not None and not parsed.is_integer():
                parsed = None
            type_counts[(key, value_kind)] += 1
            category_counts[(key, value_category)] += 1
            value_counts[(key, value_kind, json.dumps(value, ensure_ascii=False, sort_keys=True))] += 1
            year_distance_counts[(year, distance, key, value_category)] += 1
            order_numeric[key] = parsed

        race_key = (str(dbrow["race_date"]), int(dbrow["meet_code"]), int(dbrow["race_number"]))
        event_seen.add(race_key)
        candidate_row = {
            "api_record_id": api_id,
            "race_date": dbrow["race_date"],
            "race_number": dbrow["race_number"],
            "horse_number": dbrow["horse_number"],
            "horse_id": dbrow["horse_id"],
            "horse_name": dbrow["horse_name"],
            "race_distance_m": dbrow["race_distance_m"],
            "finish_position": dbrow["finish_position"],
            "finish_status_raw": dbrow["finish_status_raw"],
            "finish_time_seconds": dbrow["finish_time_seconds"],
            "positive_finish_time": int(positive_finish),
            "ordinary_finish_screen_1_to_89": int(valid_finish),
            "breed_assessment": dbrow["breed_assessment"],
            "api4_3_payload_sha256": dbrow["api4_3_payload_sha256"],
            "api4_3_source_artifact_id": dbrow["api4_3_source_artifact_id"],
            "api4_3_source_page_sha256": dbrow["api4_3_source_page_sha256"],
            "api4_3_source_page_path": dbrow["api4_3_source_page_path"],
            "api4_3_record_index": dbrow["record_index"],
            "all_api43_rows_in_race": dbrow["all_api43_rows"],
            "all_positive_finish_rows_in_race": dbrow["all_positive_finish_rows"],
            "time_values": {k: raw.get(k) for k in sorted(set(time_keys) | set(TIME_LABELS))},
            "order_values": {k: raw.get(k) for k in sorted(set(order_keys) | set(ORDER_LABELS))},
        }
        rows.append(candidate_row)
        event_rows[race_key].append(candidate_row)
        year_min = year if year_min is None or year < year_min else year_min
        year_max = year if year_max is None or year > year_max else year_max

        positive_times = [k for k in time_keys if time_numeric.get(k) is not None and time_numeric[k] > 0]
        positive_orders = [k for k in order_keys if order_numeric.get(k) is not None and order_numeric[k] > 0]
        if positive_finish and not positive_times:
            no_time_cases.append(candidate_row)
        if positive_finish and not positive_orders:
            no_order_cases.append(candidate_row)
        if positive_finish and positive_times:
            first_key = next((k for k in POINT_ORDER if k in positive_times), None)
            first_positive_counts[(year, distance, first_key or "only_non_checkpoint_time")]+=1
            signature = "|".join(sorted(time_signature))
            nonzero_signatures[(year, distance, signature)] += 1
            if len(partial_samples[(year, distance, signature)]) < 2:
                partial_samples[(year, distance, signature)].append(candidate_row)

        full_starters = int(dbrow["all_api43_rows"] or 0)
        for key, value in order_numeric.items():
            if positive_finish and value is not None and value > 0:
                rank_values_by_event[(race_key[0], race_key[1], race_key[2], key, int(value))].append(candidate_row)
                if value > full_starters:
                    over_field_cases.append({
                        "race_date": race_key[0], "race_number": race_key[2], "field": key,
                        "raw_rank": raw[key], "rank_value": int(value), "full_api43_starter_rows": full_starters,
                        "candidate_rows": None, "horse_number": dbrow["horse_number"], "horse_id": dbrow["horse_id"],
                        "finish_time_seconds": dbrow["finish_time_seconds"], "api_record_id": api_id,
                        "payload_sha256": dbrow["api4_3_payload_sha256"],
                    })

        if positive_finish:
            for key in order_keys:
                value = order_numeric.get(key)
                if value is not None and value > 0:
                    rank_values_by_event[(race_key[0], race_key[1], race_key[2], key, int(value))].append(candidate_row)

            # Candidate screen only: raw point values remain untouched.
            # S1F/C1-C4 labels do not establish an ordering of physical
            # checkpoints across every distance, so decreases are provisional.
            present_points = [(key, time_numeric.get(key)) for key in POINT_ORDER if key in time_numeric and time_numeric.get(key) is not None and time_numeric[key] > 0]
            for (left_key, left_value), (right_key, right_value) in zip(present_points, present_points[1:]):
                if right_value < left_value:
                    consistency_cases.append({
                        "issue_type": "provisional_display_order_decrease",
                        "race_date": race_key[0], "race_number": race_key[2], "horse_number": dbrow["horse_number"],
                        "horse_id": dbrow["horse_id"], "race_distance_m": dbrow["race_distance_m"],
                        "field_a": left_key, "value_a": left_value, "field_b": right_key, "value_b": right_value,
                        "finish_time_seconds": finish, "api_record_id": api_id,
                        "payload_sha256": dbrow["api4_3_payload_sha256"],
                    })
            for key, value in time_numeric.items():
                if value is not None and value > 0 and finish is not None and value > finish:
                    if key != "jeG3fTime" or (dbrow["race_distance_m"] or 0) >= 600:
                        consistency_cases.append({
                            "issue_type": "section_time_exceeds_finish_time",
                            "race_date": race_key[0], "race_number": race_key[2], "horse_number": dbrow["horse_number"],
                            "horse_id": dbrow["horse_id"], "race_distance_m": dbrow["race_distance_m"],
                            "field_a": key, "value_a": value, "field_b": "finish_time_seconds", "value_b": finish,
                            "finish_time_seconds": finish, "api_record_id": api_id,
                            "payload_sha256": dbrow["api4_3_payload_sha256"],
                        })
            g3 = time_numeric.get("jeG3fTime")
            g1 = time_numeric.get("jeG1fTime")
            if (dbrow["race_distance_m"] or 0) >= 600 and g3 is not None and g1 is not None and g3 > 0 and g1 > g3:
                consistency_cases.append({
                    "issue_type": "G1F_closing_time_exceeds_G3F_closing_time",
                    "race_date": race_key[0], "race_number": race_key[2], "horse_number": dbrow["horse_number"],
                    "horse_id": dbrow["horse_id"], "race_distance_m": dbrow["race_distance_m"],
                    "field_a": "jeG3fTime", "value_a": g3, "field_b": "jeG1fTime", "value_b": g1,
                    "finish_time_seconds": finish, "api_record_id": api_id,
                    "payload_sha256": dbrow["api4_3_payload_sha256"],
                })

    conn.close()

    candidate_counts_by_event = {key: len(value) for key, value in event_rows.items()}
    for case in over_field_cases:
        key = (case["race_date"], 2, case["race_number"])
        case["candidate_rows"] = candidate_counts_by_event.get(key)

    duplicate_groups = []
    for (race_date, meet, race_no, key, rank), members in rank_values_by_event.items():
        unique = {m["api_record_id"]: m for m in members}
        if len(unique) > 1:
            first = next(iter(unique.values()))
            duplicate_groups.append({
                "race_date": race_date, "meet_code": meet, "race_number": race_no,
                "field": key, "positive_rank": rank, "candidate_rows_with_same_rank": len(unique),
                "horse_numbers": ";".join(str(m["horse_number"]) for m in unique.values()),
                "horse_ids": ";".join(str(m["horse_id"]) for m in unique.values()),
                "finish_times_seconds": ";".join(str(m["finish_time_seconds"]) for m in unique.values()),
            })

    race_records = []
    for (race_date, meet, race_no), group in sorted(event_rows.items()):
        candidates = len(group)
        full_rows = max(int(row["all_api43_rows"] or 0) for row in group)
        full_positive = max(int(row["all_positive_finish_rows"] or 0) for row in group)
        positive = sum(int(row["positive_finish_time"]) for row in group)
        all_candidate_times_zero = all(not any(number(value) is not None and number(value) > 0 for value in row["time_values"].values()) for row in group)
        race_records.append({
            "race_date": race_date, "meet_code": meet, "race_number": race_no,
            "candidate_entrant_rows": candidates, "full_api43_entrant_rows_mixed_race": full_rows,
            "candidate_positive_finish_time_rows": positive,
            "full_mixed_race_positive_finish_rows": full_positive,
            "candidate_all_finish_times_zero_or_missing": int(all(row["finish_time_seconds"] in (0, 0.0, None) for row in group)),
            "candidate_section_time_fields_all_no_positive": int(all_candidate_times_zero),
            "event_scope_note": "candidate rows are Jeju population candidates; full rows include the entire API4_3 race field",
        })

    field_summary = []
    for key in sorted(field_keys):
        is_order = key.startswith("sj")
        cats = ["missing_key", "json_null", "zero", "positive", "negative", "invalid_or_non_numeric"]
        if is_order:
            cats.append("non_integer_ordinal")
        record = {"field": key, "field_kind": "passing_order" if is_order else "section_time"}
        for cat in cats:
            record[cat] = category_counts[(key, cat)]
        record["key_present"] = sum(type_counts[(key, value_type)] for value_type in ["integer", "number", "string", "boolean", "array", "object", "json_null"])
        for type_name in ["integer", "number", "string", "boolean", "array", "object"]:
            record[f"json_{type_name}"] = type_counts[(key, type_name)]
        field_summary.append(record)

    annual_rows = []
    for (year, distance, field, cat), count in sorted(year_distance_counts.items()):
        annual_rows.append({"year": year, "race_distance_m": distance, "field": field, "value_status": cat, "row_count": count})
    first_rows = [
        {"year": year, "race_distance_m": distance, "first_positive_checkpoint_or_time": field, "positive_finish_rows": count}
        for (year, distance, field), count in sorted(first_positive_counts.items())
    ]
    value_rows = [
        {"field": field, "json_type": json_type, "raw_json_value": raw_value, "row_count": count}
        for (field, json_type, raw_value), count in sorted(value_counts.items())
    ]

    partial_case_rows = []
    for (year, distance, signature), sample in sorted(partial_samples.items()):
        sample_count = nonzero_signatures[(year, distance, signature)]
        for rank, row in enumerate(sample, 1):
            partial_case_rows.append({
                "year": year, "race_distance_m": distance, "signature_row_count": sample_count,
                "sample_number_within_signature": rank, "time_value_signature": signature,
                "race_date": row["race_date"], "race_number": row["race_number"],
                "horse_number": row["horse_number"], "horse_id": row["horse_id"],
                "finish_position": row["finish_position"], "finish_time_seconds": row["finish_time_seconds"],
                "section_time_raw_json": json.dumps(row["time_values"], ensure_ascii=False, sort_keys=True),
                "api_record_id": row["api_record_id"], "payload_sha256": row["api4_3_payload_sha256"],
            })

    def case_record(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "race_date": row["race_date"], "race_number": row["race_number"],
            "horse_number": row["horse_number"], "horse_id": row["horse_id"],
            "horse_name": row["horse_name"], "race_distance_m": row["race_distance_m"],
            "finish_position": row["finish_position"], "finish_status_raw": row["finish_status_raw"],
            "finish_time_seconds": row["finish_time_seconds"],
            "section_time_raw_json": json.dumps(row["time_values"], ensure_ascii=False, sort_keys=True),
            "passing_order_raw_json": json.dumps(row["order_values"], ensure_ascii=False, sort_keys=True),
            "api_record_id": row["api_record_id"], "payload_sha256": row["api4_3_payload_sha256"],
            "source_artifact_id": row["api4_3_source_artifact_id"],
            "source_page_sha256": row["api4_3_source_page_sha256"],
            "source_page_path": row["api4_3_source_page_path"],
        }

    write_csv(OUT / "field_distribution.csv", value_rows, ["field", "json_type", "raw_json_value", "row_count"])
    write_csv(OUT / "field_coverage.csv", field_summary, list(field_summary[0]) if field_summary else ["field"])
    write_csv(OUT / "year_distance_coverage.csv", annual_rows, ["year", "race_distance_m", "field", "value_status", "row_count"])
    write_csv(OUT / "first_positive_checkpoint.csv", first_rows, ["year", "race_distance_m", "first_positive_checkpoint_or_time", "positive_finish_rows"])
    write_csv(OUT / "race_scope.csv", race_records, list(race_records[0]) if race_records else ["race_date"])
    case_columns = ["race_date", "race_number", "horse_number", "horse_id", "horse_name", "race_distance_m", "finish_position", "finish_status_raw", "finish_time_seconds", "section_time_raw_json", "passing_order_raw_json", "api_record_id", "payload_sha256", "source_artifact_id", "source_page_sha256", "source_page_path"]
    write_csv(OUT / "positive_finish_all_section_times_zero_or_missing.csv", [case_record(row) for row in no_time_cases], case_columns)
    write_csv(OUT / "positive_finish_all_passing_orders_zero_or_missing.csv", [case_record(row) for row in no_order_cases], case_columns)
    write_csv(OUT / "positive_finish_partial_section_time_samples.csv", partial_case_rows, ["year", "race_distance_m", "signature_row_count", "sample_number_within_signature", "time_value_signature", "race_date", "race_number", "horse_number", "horse_id", "finish_position", "finish_time_seconds", "section_time_raw_json", "api_record_id", "payload_sha256"])
    write_csv(OUT / "positive_rank_over_full_field.csv", over_field_cases, ["race_date", "race_number", "field", "raw_rank", "rank_value", "full_api43_starter_rows", "candidate_rows", "horse_number", "horse_id", "finish_time_seconds", "api_record_id", "payload_sha256"])
    write_csv(OUT / "duplicate_positive_passing_orders.csv", duplicate_groups, ["race_date", "meet_code", "race_number", "field", "positive_rank", "candidate_rows_with_same_rank", "horse_numbers", "horse_ids", "finish_times_seconds"])
    write_csv(OUT / "time_consistency_flags.csv", consistency_cases, ["issue_type", "race_date", "race_number", "horse_number", "horse_id", "race_distance_m", "field_a", "value_a", "field_b", "value_b", "finish_time_seconds", "api_record_id", "payload_sha256"])

    artifact_map: dict[int, dict[str, Any]] = {}
    for row in rows:
        artifact_id = int(row["api4_3_source_artifact_id"])
        if artifact_id not in artifact_map:
            artifact_map[artifact_id] = {
                "source_artifact_id": artifact_id,
                "attempt_id": row.get("attempt_id"),
                "path": row["api4_3_source_page_path"],
                "expected_sha256": row["api4_3_source_page_sha256"],
                "db_artifact_sha256": row.get("artifact_page_sha256"),
                "expected_bytes": row.get("response_bytes"),
            }
    manifest_rows = []
    for item in artifact_map.values():
        page = safe_project_path(str(item["path"] or ""))
        exists = page is not None and page.is_file()
        actual_sha = ""
        actual_bytes = None
        if exists and page is not None:
            actual_bytes = page.stat().st_size
            digest = hashlib.sha256()
            with page.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            actual_sha = digest.hexdigest()
        manifest_rel, manifest_match = manifest_page_match(page, str(item["attempt_id"]), str(item["expected_sha256"])) if page else ("", False)
        manifest_rows.append({
            "source_artifact_id": item["source_artifact_id"], "attempt_id": item["attempt_id"],
            "raw_relative_path": item["path"], "db_source_artifact_sha256": item["db_artifact_sha256"],
            "db_candidate_view_sha256": item["expected_sha256"], "file_sha256": actual_sha,
            "db_response_bytes": item["expected_bytes"], "file_bytes": actual_bytes,
            "file_exists_within_repo": int(exists),
            "db_view_artifact_hash_match": int(item["db_artifact_sha256"] == item["expected_sha256"]),
            "file_hash_match": int(actual_sha == item["expected_sha256"]),
            "file_size_match": int(actual_bytes == item["expected_bytes"]),
            "manifest_path": manifest_rel, "manifest_page_hash_match": int(manifest_match),
        })
    write_csv(OUT / "raw_manifest_page_hash_audit.csv", manifest_rows, list(manifest_rows[0]) if manifest_rows else ["source_artifact_id"])

    # Event-level disposition without rewriting source results. Current active
    # all-zero events are the 147 cancellation/non-start group confirmed in the
    # previous cause audit; 19 replayed events are already absent from the
    # active result layer and are recorded below from its cleanup receipt.
    all_zero_events = [r for r in race_records if r["candidate_all_finish_times_zero_or_missing"]]
    all_zero_rows = sum(r["candidate_entrant_rows"] for r in all_zero_events)
    review_keys = set()
    if CANCELLATION_REVIEW.is_file():
        for line in CANCELLATION_REVIEW.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                review_keys.add((record.get("race_date"), int(record.get("race_number"))))
    event_status_rows = []
    for row in all_zero_events:
        key = (row["race_date"], row["race_number"])
        event_status_rows.append({
            "race_date": row["race_date"], "race_number": row["race_number"],
            "candidate_rows": row["candidate_entrant_rows"],
            "status": "cancellation_confirmed_in_20261001_review" if key in review_keys else "confirmed_cancel_or_race_failure_in_147_event_review",
            "evidence": "jeju/research/20261001_user_cancellation_confirmation/confirmed_76_review.jsonl" if key in review_keys else "jeju/research/20260930_zero_time_cause_audit/README.md (aggregate states all 147 remaining zero-time events were reviewed)",
        })
    write_csv(OUT / "all_zero_time_event_statuses.csv", event_status_rows, ["race_date", "race_number", "candidate_rows", "status", "evidence"])

    all_candidates = len(rows)
    positive_finish_rows = sum(int(row["positive_finish_time"]) for row in rows)
    ordinary_positive_finish_rows = sum(int(row["ordinary_finish_screen_1_to_89"]) for row in rows)
    no_positive_times = len(no_time_cases)
    no_positive_orders = len(no_order_cases)
    field_counts = {key: {cat: count for (field, cat), count in category_counts.items() if field == key} for key in sorted(field_keys)}
    manifest_summary = {
        "pages_referenced_by_candidate_rows": len(manifest_rows),
        "pages_file_hash_match": sum(r["file_hash_match"] for r in manifest_rows),
        "pages_file_size_match": sum(r["file_size_match"] for r in manifest_rows),
        "pages_manifest_hash_match": sum(r["manifest_page_hash_match"] for r in manifest_rows),
        "pages_missing": sum(1 - r["file_exists_within_repo"] for r in manifest_rows),
    }
    exclusion_registry = json.loads(EXCLUSIONS.read_text(encoding="utf-8")) if EXCLUSIONS.is_file() else {}
    small_bear_id = "3005648"
    small_bear = exclusion_registry.get("horses", {}).get(small_bear_id, {})
    receipt = json.loads(SMALL_BEAR_RECEIPT.read_text(encoding="utf-8")) if SMALL_BEAR_RECEIPT.is_file() else {}
    replay_events = [
        {"event_range": "2026-07-07 R1-R4", "races": 4, "rows": 40},
        {"event_range": "2026-08-25 R1-R8", "races": 8, "rows": 75},
        {"event_range": "2026-08-26 R1-R7", "races": 7, "rows": 67},
    ]
    replay_excluded = {"races": 19, "rows": 182, "event_ranges": replay_events, "source": "jeju/maintenance/zero_time_cleanup_20260930/README.md"}
    summary = {
        "scope": "read-only horse-level API4_3 rows exposed by jeju_race_analysis_2026; candidate breed filter is rank_class_candidate/api_cross_reference_candidate/program_rule_candidate",
        "db": "jeju/data/jeju_native_core.sqlite3",
        "sqlite_open_mode": "mode=ro",
        "query_strategy": "single pass over analysis view, raw api_records payload, source_artifacts, and one grouped full-race API4_3 starter denominator",
        "population": {
            "candidate_rows": all_candidates,
            "candidate_races": len(event_seen),
            "candidate_unique_horse_ids": len({str(row["horse_id"]) for row in rows if row["horse_id"]}),
            "first_race_date": min((key[0] for key in event_seen), default=None),
            "last_race_date": max((key[0] for key in event_seen), default=None),
            "first_year": year_min,
            "last_year": year_max,
            "candidate_rows_positive_finish_time": positive_finish_rows,
            "candidate_rows_ordinary_rank_1_to_89_and_positive_finish_time": ordinary_positive_finish_rows,
            "positive_time_rows_with_all_section_times_zero_or_missing": no_positive_times,
            "positive_time_rows_with_all_passing_orders_zero_or_missing": no_positive_orders,
            "candidate_positive_finish_rows_outside_ordinary_rank_1_to_89": positive_finish_rows - ordinary_positive_finish_rows,
            "all_zero_finish_time_cancel_or_failure_events": len(all_zero_events),
            "all_zero_finish_time_cancel_or_failure_candidate_rows": all_zero_rows,
            "full_mixed_race_rows_across_candidate_races": sum(r["full_api43_entrant_rows_mixed_race"] for r in race_records),
            "full_mixed_race_positive_finish_rows_across_candidate_races": sum(r["full_mixed_race_positive_finish_rows"] for r in race_records),
        },
        "observed_raw_field_keys": sorted(field_keys),
        "field_stats": field_counts,
        "time_order_screen": {
            "observed_display_order_decreases": sum(r["issue_type"] == "provisional_display_order_decrease" for r in consistency_cases),
            "section_time_exceeds_finish_time": sum(r["issue_type"] == "section_time_exceeds_finish_time" for r in consistency_cases),
            "G1F_time_greater_than_G3F_time": sum(r["issue_type"] == "G1F_closing_time_exceeds_G3F_closing_time" for r in consistency_cases),
            "semantics_note": "S1F and C1-C4 event-specific physical checkpoint order is not established for every distance; the display-order decrease is provisional. G3F/G1F are late-section times, per the source adjudication report. No raw value is changed.",
        },
        "rank_checks": {
            "positive_rank_over_full_api43_starter_rows": len(over_field_cases),
            "same_point_duplicate_positive_rank_groups": len(duplicate_groups),
            "duplicate_rank_interpretation": "reported as repeated raw positive ranks; not called an error because dead heats/tie basis are not established by this field alone",
            "G3F_rank_positive_rows": category_counts.get(("sjG3fOrd", "positive"), 0),
        },
        "source_manifest_check": manifest_summary,
        "excluded_or_separate_statuses": {
            "small_bear": {
                "horse_id": small_bear_id,
                "registered_status": small_bear.get("status"),
                "reimport_allowed": small_bear.get("reimport_allowed"),
                "race_result_rows_deleted": receipt.get("deleted_db_rows", {}).get("race_result_rows", 0),
                "api_record_rows_deleted": receipt.get("deleted_db_rows", {}).get("api_records", 0),
                "source": "jeju/data/horse_exclusions.json and jeju/maintenance/small_bear_removal_20261002/deletion_receipt.json",
            },
            "replayed_result_rows_removed_from_active_result_layer": replay_excluded,
            "cancel_or_failure_status": {
                "events": len(all_zero_events), "candidate_rows": all_zero_rows,
                "per_event_details_file": "all_zero_time_event_statuses.csv",
                "status_source": "jeju/research/20260930_zero_time_cause_audit/README.md and 20261001 confirmed review",
            },
        },
        "created_csvs": [
            "field_coverage.csv", "field_distribution.csv", "year_distance_coverage.csv",
            "first_positive_checkpoint.csv", "race_scope.csv",
            "positive_finish_all_section_times_zero_or_missing.csv",
            "positive_finish_all_passing_orders_zero_or_missing.csv",
            "positive_finish_partial_section_time_samples.csv", "positive_rank_over_full_field.csv",
            "duplicate_positive_passing_orders.csv", "time_consistency_flags.csv",
            "raw_manifest_page_hash_audit.csv", "all_zero_time_event_statuses.csv",
        ],
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "candidate_rows": all_candidates,
        "candidate_positive_finish_time_rows": positive_finish_rows,
        "ordinary_rank_positive_finish_rows": ordinary_positive_finish_rows,
        "section_all_zero_or_missing": no_positive_times,
        "orders_all_zero_or_missing": no_positive_orders,
        "time_order_provisional_decreases": summary["time_order_screen"]["observed_display_order_decreases"],
        "section_time_over_finish": summary["time_order_screen"]["section_time_exceeds_finish_time"],
        "G1F_gt_G3F": summary["time_order_screen"]["G1F_time_greater_than_G3F_time"],
        "rank_over_full_field": len(over_field_cases),
        "duplicate_positive_rank_groups": len(duplicate_groups),
        "manifest": manifest_summary,
        "output": str(OUT.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
