"""Normalize the archived KRA API4_3 response rows without discarding source data.

This is a research export only. It reads the immutable raw response archive and
the preceding API calendar ledgers; it does not read or write an operational DB.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CALENDAR = ROOT / "thoroughbred/research/20260929_calendar_api_v1"
RAW = CALENDAR / "raw/race_execution_probe"
START_DATE = "20100101"
CUTOFF = "20260929"
MEETS = (1, 3, 4)
YEARS = range(2010, 2027)

# Values repeated on each runner item but describing the event. Their original
# values and within-event disagreements are summarized in race_events.csv.
EVENT_FIELDS = (
    "meet", "rcDate", "rcDay", "rcNo", "rcDist", "rcName", "rank",
    "prizeCond", "track", "weather", "chaksun1", "chaksun2", "chaksun3",
    "chaksun4", "chaksun5", "buga1",
)

RUNNER_COLUMNS = (
    ("result_rank_raw", "ord"),
    ("finish_time_seconds_raw", "rcTime"),
    ("horse_program_no_raw", "chulNo"),
    ("horse_id_raw", "hrNo"),
    ("horse_name_raw", "hrName"),
    ("horse_name_en_raw", "hrNameEn"),
    ("horse_age_raw", "age"),
    ("horse_age_condition_raw", "ageCond"),
    ("horse_sex_raw", "sex"),
    ("horse_sex_condition_raw", "sexCond"),
    ("horse_origin_raw", "name"),
    ("jockey_id_raw", "jkNo"),
    ("jockey_name_raw", "jkName"),
    ("trainer_id_raw", "trNo"),
    ("trainer_name_raw", "trName"),
    ("owner_id_raw", "owNo"),
    ("owner_name_raw", "owName"),
    ("carried_weight_raw", "wgBudam"),
    ("horse_weight_raw", "wgHr"),
    ("odds_win_raw", "winOdds"),
    ("odds_place_raw", "plcOdds"),
    ("additional_prize_1_raw", "buga1"),
    ("track_condition_raw", "track"),
    ("weather_raw", "weather"),
    ("race_distance_m_raw", "rcDist"),
    ("race_name_raw", "rcName"),
    ("grade_raw", "rank"),
    ("finish_margin_raw", "diffUnit"),
    ("days_since_previous_raw", "ilsu"),
    ("horse_rating_raw", "rating"),
    ("prize_condition_raw", "prizeCond"),
    ("burden_type_raw", "budam"),
)


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def json_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def api_rows(payload: dict[str, Any], path: Path) -> tuple[int, list[dict[str, Any]]]:
    response = payload.get("response") or {}
    header = response.get("header") or {}
    if str(header.get("resultCode")) not in {"00", "0000"}:
        raise ValueError(f"API response error in {rel(path)}: {header.get('resultCode')}")
    body = response.get("body") or {}
    block = body.get("items") or {}
    rows = block.get("item") or [] if isinstance(block, dict) else []
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"Unexpected API item structure in {rel(path)}")
    total = int(body.get("totalCount") or 0)
    if total != len(rows):
        raise ValueError(f"Incomplete API payload in {rel(path)}: totalCount={total}, items={len(rows)}")
    return total, rows


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def positive_finish(row: dict[str, Any]) -> bool:
    rank = int_or_none(row.get("ord"))
    try:
        race_time = float(row.get("rcTime") or 0)
    except (TypeError, ValueError):
        race_time = 0.0
    # Match the calendar ledger's evidence rule. Raw ord/rcTime remain intact;
    # statuses such as ord=99 or rcTime=0 are never converted into a finish.
    return rank is not None and 1 <= rank <= 89 and race_time > 0


def event_field_distribution(rows: list[dict[str, Any]]) -> str:
    summary: dict[str, list[dict[str, Any]]] = {}
    for field in EVENT_FIELDS:
        counts: Counter[str] = Counter()
        values: dict[str, dict[str, Any]] = {}
        for row in rows:
            if field in row:
                entry = {"present": True, "value": row[field]}
            else:
                entry = {"present": False}
            key = json_compact(entry)
            counts[key] += 1
            values[key] = entry
        summary[field] = [
            {**values[key], "row_count": counts[key]}
            for key in values
        ]
    return json_compact(summary)


def uniform_event_value(rows: list[dict[str, Any]], field: str) -> Any:
    """Return a convenience value only when every row has the same raw value."""
    if not rows or any(field not in row for row in rows):
        return ""
    values = {json_compact(row[field]) for row in rows}
    return rows[0][field] if len(values) == 1 else ""


def audit_event_fields(groups: dict[tuple[int, str, int], list[dict[str, Any]]]) -> dict[str, Any]:
    """Count event-field agreement and missingness; runner-only fields are excluded."""
    audit: dict[str, Any] = {}
    for field in EVENT_FIELDS:
        with_multiple_values = 0
        partially_missing_or_null = 0
        all_missing_or_null = 0
        blank_value = 0
        consistent = 0
        for rows in groups.values():
            present = [row[field] for row in rows if field in row and row[field] is not None]
            unique = {json_compact(value) for value in present}
            incomplete = len(present) != len(rows)
            if len(unique) > 1:
                with_multiple_values += 1
            if any(value == "" for value in present):
                blank_value += 1
            if incomplete and present:
                partially_missing_or_null += 1
            elif not present:
                all_missing_or_null += 1
            if not incomplete and len(unique) == 1:
                consistent += 1
        audit[field] = {
            "consistent_events": consistent,
            "multi_value_events": with_multiple_values,
            "partially_missing_or_null_events": partially_missing_or_null,
            "all_missing_or_null_events": all_missing_or_null,
            "events_with_blank_value": blank_value,
        }
    return audit


def load_plan() -> dict[tuple[int, str, int], dict[str, str]]:
    rows = read_csv(CALENDAR / "race_plan.csv")
    out: dict[tuple[int, str, int], dict[str, str]] = {}
    for row in rows:
        key = (int(row["meet"]), row["date"], int(row["race_no"]))
        if key in out:
            raise ValueError(f"Duplicate race_plan key: {key}")
        out[key] = row
    return out


def load_flags() -> dict[tuple[int, str, int], dict[str, str]]:
    rows = read_csv(CALENDAR / "race_execution_flags.csv")
    out: dict[tuple[int, str, int], dict[str, str]] = {}
    for row in rows:
        key = (int(row["meet"]), row["date"], int(row["race_no"]))
        if key in out:
            raise ValueError(f"Duplicate race_execution_flags key: {key}")
        out[key] = row
    return out


def build() -> dict[str, Any]:
    plan = load_plan()
    flags = load_flags()
    excluded_keys = set()
    for filename, expected in (("planless_positive_result_review.csv", 20),
                               ("result_only_nonfinish_anomaly_review.csv", 52)):
        review = read_csv(CALENDAR / filename)
        keys = {(int(row["meet"]), row["date"], int(row["race_no"])) for row in review}
        if len(review) != len(keys) or len(keys) != expected or keys & excluded_keys:
            raise ValueError(f"Confirmed anomalous result key ledger changed: {filename}")
        excluded_keys |= keys
    if excluded_keys & set(plan):
        raise ValueError("Confirmed anomalous result key ledger changed")
    if len(plan) != 29_826:
        raise ValueError(f"Unexpected race_plan row count: {len(plan)}")
    if len(flags) != 29_826 or excluded_keys & set(flags):
        raise ValueError(f"Unexpected execution flag row count: {len(flags)}")
    if not set(plan).issubset(flags):
        raise ValueError("Some plan keys are absent from race_execution_flags.csv")

    grouped: dict[tuple[int, str, int], list[dict[str, Any]]] = defaultdict(list)
    grouped_source_files: dict[tuple[int, str, int], set[str]] = defaultdict(set)
    runner_rows: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    source_manifest: list[dict[str, Any]] = []
    total_raw_rows = 0
    included_raw_rows = 0

    for year in YEARS:
        for meet in MEETS:
            path = RAW / str(year) / f"meet_{meet}.json.gz"
            if not path.exists():
                raise FileNotFoundError(path)
            compressed = path.read_bytes()
            uncompressed = gzip.decompress(compressed)
            payload = json.loads(uncompressed)
            total_count, rows = api_rows(payload, path)
            source_rel = rel(path)
            source_entry = {
                "source": "KRA data.go.kr API4_3/raceResult_3",
                "request_year": year,
                "request_meet": meet,
                "source_file": source_rel,
                "compression": "gzip",
                "compressed_sha256": sha256(compressed),
                "response_payload_sha256": sha256(uncompressed),
                "total_count": total_count,
                "included_rows": 0,
                "scope_excluded_rows": 0,
            }
            source_manifest.append(source_entry)
            total_raw_rows += total_count

            for item_index, item in enumerate(rows):
                date_value = item.get("rcDate")
                date = str(date_value) if date_value is not None else ""
                if len(date) != 8 or not date.isdigit():
                    raise ValueError(f"Invalid rcDate in {source_rel} item {item_index}: {date_value!r}")
                if date[:4] != str(year):
                    raise ValueError(f"rcDate/request year mismatch in {source_rel} item {item_index}: {date}")
                if date < START_DATE or date > CUTOFF:
                    exclusions.append({
                        "source_file": source_rel,
                        "source_item_index": item_index,
                        "request_year": year,
                        "request_meet": meet,
                        "raw_date": date,
                        "exclusion_reason": "outside_declared_date_scope",
                    })
                    source_entry["scope_excluded_rows"] += 1
                    continue

                race_no = int_or_none(item.get("rcNo"))
                if race_no is None:
                    raise ValueError(f"Invalid rcNo in {source_rel} item {item_index}")
                key = (meet, date, race_no)
                if key in excluded_keys:
                    exclusions.append({
                        "source_file": source_rel,
                        "source_item_index": item_index,
                        "request_year": year,
                        "request_meet": meet,
                        "raw_date": date,
                        "exclusion_reason": "confirmed_reused_or_modified_prior_race_api_anomaly",
                    })
                    source_entry["scope_excluded_rows"] += 1
                    continue
                grouped[key].append(item)
                grouped_source_files[key].add(source_rel)
                included_raw_rows += 1
                source_entry["included_rows"] += 1
                flag = flags.get(key)
                if flag is None:
                    raise ValueError(f"Result row key absent from race_execution_flags.csv: {key}")
                row = {
                    "source_meet": meet,
                    "result_date": date,
                    "result_race_no": race_no,
                    "in_plan_api": flag["in_plan_api"],
                    "execution_status": flag["execution_status"],
                    "positive_finish_evidence": int(positive_finish(item)),
                    "source_file": source_rel,
                    "source_item_index": item_index,
                }
                row.update({out_name: item.get(api_name) for out_name, api_name in RUNNER_COLUMNS})
                runner_rows.append(row)

    # Every API result key is represented by the prior flags; an unexpected key
    # fails above, and a flag with no raw items remains in race_events.csv.
    result_keys = set(grouped)
    if result_keys != {key for key, flag in flags.items() if int(flag["source_result_rows"]) > 0}:
        raise ValueError("Raw result event keys do not match race_execution_flags.csv")

    event_rows: list[dict[str, Any]] = []
    for key in sorted(flags):
        meet, date, race_no = key
        flag = flags[key]
        plan_row = plan.get(key)
        results = grouped.get(key, [])
        positive_count = sum(positive_finish(row) for row in results)
        if len(results) != int(flag["source_result_rows"]):
            raise ValueError(f"Result row count mismatch for {key}: {len(results)} != {flag['source_result_rows']}")
        if positive_count != int(flag["positive_finish_rows"]):
            raise ValueError(f"Positive finish count mismatch for {key}: {positive_count} != {flag['positive_finish_rows']}")
        files = sorted(grouped_source_files.get(key, set()))
        event_rows.append({
            "source_meet": meet,
            "result_date_key": date,
            "result_race_no_key": race_no,
            "scheduled_in_plan_api": flag["in_plan_api"],
            "scheduled_date": plan_row["date"] if plan_row else "",
            "scheduled_meet": plan_row["meet"] if plan_row else "",
            "scheduled_race_no": plan_row["race_no"] if plan_row else "",
            "scheduled_venue_label_raw": plan_row["api_meet_label"] if plan_row else "",
            "scheduled_distance_m": plan_row["distance_m"] if plan_row else "",
            "scheduled_grade_raw": plan_row["grade_raw"] if plan_row else "",
            "scheduled_race_name_raw": plan_row["race_name_raw"] if plan_row else "",
            "scheduled_start_raw": plan_row["scheduled_start_raw"] if plan_row else "",
            "plan_source_file": plan_row["source_file"] if plan_row else "",
            "actual_venue_label_raw": uniform_event_value(results, "meet"),
            "actual_date_raw": uniform_event_value(results, "rcDate"),
            "actual_race_no_raw": uniform_event_value(results, "rcNo"),
            "actual_race_day_raw": uniform_event_value(results, "rcDay"),
            "actual_distance_m_raw": uniform_event_value(results, "rcDist"),
            "actual_race_name_raw": uniform_event_value(results, "rcName"),
            "actual_grade_raw": uniform_event_value(results, "rank"),
            "actual_track_condition_raw": uniform_event_value(results, "track"),
            "actual_weather_raw": uniform_event_value(results, "weather"),
            "actual_additional_prize_1_raw": uniform_event_value(results, "buga1"),
            "result_item_count": len(results),
            "positive_finish_rows": positive_count,
            "execution_status_from_prior_ledger": flag["execution_status"],
            "result_only_key_unverified": int(plan_row is None),
            "result_source_files_json": json_compact(files),
            "result_event_field_distributions_json": event_field_distribution(results) if results else "{}",
        })

    unverified_rows = [row for row in event_rows if int(row["result_only_key_unverified"]) == 1]
    unverified_positive = [
        row for row in unverified_rows
        if row["execution_status_from_prior_ledger"] == "positive_result_without_plan_unverified"
    ]

    expected = {
        "race_plan_rows": 29_826,
        "race_result_probe_rows": 331_811,
        "executed_plan_keys": 29_710,
        "positive_result_only_keys": 0,
    }
    actual = {
        "race_plan_rows": len(plan),
        "race_result_probe_rows": included_raw_rows,
        "executed_plan_keys": sum(row["execution_status_from_prior_ledger"] == "executed_plan_and_result" for row in event_rows),
        "positive_result_only_keys": len(unverified_positive),
    }
    if actual != expected:
        raise ValueError(f"Expected prior-ledger counts do not match: {actual}")
    known_nonfinish_events = {
        key: rows for key, rows in grouped.items()
        if key[0] == 1 and key[1] == "20200809"
    }
    known_nonfinish_valid = (
        len(known_nonfinish_events) == 12
        and all(1 <= len(rows) <= 12 for rows in known_nonfinish_events.values())
        and all(9 <= len(rows) <= 11 for rows in known_nonfinish_events.values())
        and all(flags[key]["execution_status"] == "planned_no_execution_evidence" for key in known_nonfinish_events)
        and all(int(flags[key]["positive_finish_rows"]) == 0 for key in known_nonfinish_events)
        and all(not positive_finish(row) for rows in known_nonfinish_events.values() for row in rows)
        and all(
            int_or_none(row.get("ord")) == 99 and float(row.get("rcTime") or 0) == 0
            for rows in known_nonfinish_events.values() for row in rows
        )
    )
    if not known_nonfinish_valid:
        raise ValueError("2020-08-09 Seoul non-finish evidence changed unexpectedly")

    event_headers = [
        "source_meet", "result_date_key", "result_race_no_key",
        "scheduled_in_plan_api", "scheduled_date", "scheduled_meet", "scheduled_race_no",
        "scheduled_venue_label_raw", "scheduled_distance_m", "scheduled_grade_raw",
        "scheduled_race_name_raw", "scheduled_start_raw", "plan_source_file",
        "actual_venue_label_raw", "actual_date_raw", "actual_race_no_raw",
        "actual_race_day_raw", "actual_distance_m_raw", "actual_race_name_raw",
        "actual_grade_raw", "actual_track_condition_raw", "actual_weather_raw",
        "actual_additional_prize_1_raw",
        "result_item_count", "positive_finish_rows", "execution_status_from_prior_ledger",
        "result_only_key_unverified", "result_source_files_json",
        "result_event_field_distributions_json",
    ]
    runner_headers = [
        "source_meet", "result_date", "result_race_no", "in_plan_api",
        "execution_status", "positive_finish_evidence", "source_file", "source_item_index",
        *[column for column, _ in RUNNER_COLUMNS],
    ]
    exclusion_headers = [
        "source_file", "source_item_index", "request_year", "request_meet",
        "raw_date", "exclusion_reason",
    ]
    unverified_headers = event_headers
    event_attribute_audit = audit_event_fields(grouped)

    write_csv(HERE / "race_events.csv", event_headers, event_rows)
    write_csv(HERE / "runner_results.csv", runner_headers, runner_rows)
    write_csv(HERE / "unverified_result_only_keys.csv", unverified_headers, unverified_rows)
    write_csv(HERE / "scope_exclusions.csv", exclusion_headers, exclusions)

    status_counts = dict(sorted(Counter(row["execution_status_from_prior_ledger"] for row in event_rows).items()))
    counts = {
        **actual,
        "raw_api_rows_total": total_raw_rows,
        "scope_excluded_rows": len(exclusions),
        "excluded_anomalous_result_keys": len(excluded_keys),
        "event_keys_from_prior_ledger": len(event_rows),
        "result_event_keys": len(result_keys),
        "planned_keys_without_result_rows": sum(
            int(row["scheduled_in_plan_api"]) == 1 and int(row["result_item_count"]) == 0 for row in event_rows
        ),
        "unverified_result_only_keys_all": len(unverified_rows),
        "unverified_result_only_keys_positive_finish": len(unverified_positive),
        "runner_result_rows": len(runner_rows),
        "status_counts": status_counts,
    }
    outputs = {}
    for filename, row_count in (
        ("race_events.csv", len(event_rows)),
        ("runner_results.csv", len(runner_rows)),
        ("unverified_result_only_keys.csv", len(unverified_rows)),
        ("scope_exclusions.csv", len(exclusions)),
    ):
        data = (HERE / filename).read_bytes()
        outputs[filename] = {"row_count": row_count, "sha256": sha256(data)}

    prior_ledgers = []
    for filename in ("race_plan.csv", "race_execution_flags.csv"):
        data = (CALENDAR / filename).read_bytes()
        prior_ledgers.append({"path": rel(CALENDAR / filename), "sha256": sha256(data)})
    manifest = {
        "dataset": "KRA API4_3 race results normalized research dataset",
        "version": 1,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "declared_date_scope": {"from": START_DATE, "through": CUTOFF},
        "join_key": ["source_meet", "rcDate/result_date", "rcNo/result_race_no"],
        "prior_key_sources": prior_ledgers,
        "source_api": "KRA data.go.kr B551015 API4_3/raceResult_3",
        "inputs": source_manifest,
        "outputs": outputs,
        "counts": counts,
        "validation": {
            "all_source_total_counts_match_item_rows": True,
            "all_in_scope_api_items_have_runner_result_rows": len(runner_rows) == included_raw_rows,
            "result_keys_match_prior_execution_flags": True,
            "result_counts_and_positive_finish_counts_match_prior_flags": True,
            "all_plan_keys_present_in_event_table": set(plan).issubset(flags),
            "expected_calendar_counts_match": actual == expected,
            "seoul_20200809_all_12_races_ord99_time0_not_counted_as_execution": known_nonfinish_valid,
            "raw_pointer_is_source_file_and_zero_based_item_index": True,
            "raw_fields_are_retained_in_archived_response_payload": True,
        },
        "event_attribute_audit": event_attribute_audit,
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = build()
    print(json.dumps({"counts": result["counts"], "outputs": result["outputs"]}, ensure_ascii=False, indent=2))
