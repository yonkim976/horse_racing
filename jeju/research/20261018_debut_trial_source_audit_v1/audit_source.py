"""Freeze the API20 running-trial source rows linked to F1-style cold targets.

Reads the SQLite database through read-only/query-only connections and writes
only new files in this audit directory. It does not fit models or modify the DB.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
BASELINE_SOURCE = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet"
STYLE_README = ROOT / "jeju/research/20261010_style_history_ablation_v1/README.md"
TRIAL_BACKFILL_README = ROOT / "jeju/research/20260929_trial_api_backfill_2003_2025/README.md"
HORSE_ANALYSIS_README = ROOT / "jeju/research/20261001_horse_analysis_2026/README.md"
SOURCE_CONTRACT = ROOT / "jeju/research/20261007_foundation_v1/SOURCE_CONTRACT.md"
TRIAL_INVENTORY = ROOT / "jeju/research/20261007_foundation_v1/trial_inventory.json"
API20_LOADER = ROOT / "jeju/scripts/build_native_core_from_api_raw.py"
AGENTS_GUIDANCE = ROOT / "jeju/AGENTS.md"
RESTART_PLAN = ROOT / "jeju/docs/RESTART_PLAN_20260928.md"
REVIEW_DOCS_README = ROOT / "jeju/review_documents/README.md"
AUDIT_README = HERE / "README.md"

COMPLETED_JUDGMENT_LABELS = {
    "합격", "불합격", "주행불합격", "출발불합격", "불합격(능검)",
    "발주불합격", "불합격(발검)",
}
TIME_FIELDS = [
    "rcTime", "rcTimeS1f", "rcTime_1c", "rcTime_2c", "rcTime_3c",
    "rcTime_4c", "rcTimeG3f", "rcTimeG1f", "rcTime_400", "rcTimeG400",
    "passtime_3f", "passtime_4f",
]
CORE_FIELDS = [
    "trainDate", "meet", "daySerial", "trainNo", "chulNo", "hrNo",
    "majong", "rcDist", "rcTime", "ord", "passFlag", "nopassReason",
    "reason", "wgBudam", "wgJkAdd", "wgHr", "age", "sex",
    *[f for f in TIME_FIELDS if f not in {"rcTime", "rcDist"}],
    "s1f", "g1f", "g2f", "g3f_4c", "g4f_3c", "g6f_2c", "g8f_1c",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def stable_fingerprint(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda row: (str(row.get("api_record_id", "")), str(row.get("source_artifact_id", "")))):
        digest.update(stable_json(record).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def raw_scalar_text(value: Any) -> str | None:
    """Arrow-safe display of a mixed-type API scalar; payload_json remains exact."""
    if value is None:
        return None
    return value if isinstance(value, str) else stable_json(value)


def iso_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date().isoformat()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def open_read_only() -> sqlite3.Connection:
    uri = f"file:{DB.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    return conn


def fetch_all(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def chunked_event_rows(conn: sqlite3.Connection, event_keys: list[tuple[str, int, int]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source_select = """
        SELECT t.api_record_id,t.trial_date,t.meet_code,t.trial_number,t.horse_number,
               t.horse_id,t.finish_position,t.finish_status_raw,t.finish_time_seconds,
               t.body_weight_kg,t.carried_weight_base_kg,t.jockey_overweight_kg,
               t.jockey_id,t.jockey_name,t.trainer_id,t.trainer_name,t.pass_flag_raw,
               t.failure_reason_raw,t.inspection_reason_raw,t.section_times_json,
               t.breed_label_raw,t.breed_assessment,t.breed_assessment_note,
               ar.record_index,ar.record_type,ar.natural_key,ar.payload_json,
               ar.payload_sha256,ar.source_artifact_id,
               sa.source_family,sa.source_role,sa.public_dataset_id,sa.dataset_name,
               sa.endpoint,sa.operation,sa.attempt_id,sa.request_params_json,
               sa.source_url_without_key,sa.collected_at_utc,sa.http_status_code,
               sa.raw_relative_path,sa.response_bytes,sa.sha256 AS response_sha256,
               sa.parser_version,sa.created_at_utc
        FROM target_events e
        JOIN running_trial_rows t
          ON t.trial_date=e.trial_date AND t.meet_code=e.meet_code
         AND t.trial_number=e.trial_number
        JOIN api_records ar ON ar.api_record_id=t.api_record_id
        JOIN source_artifacts sa ON sa.source_artifact_id=ar.source_artifact_id
        ORDER BY t.trial_date,t.meet_code,t.trial_number,t.horse_number,t.api_record_id
    """
    for start in range(0, len(event_keys), 120):
        batch = event_keys[start:start + 120]
        values_sql = ",".join("(?,?,?)" for _ in batch)
        params: list[Any] = []
        for trial_date, meet_code, trial_number in batch:
            params.extend((trial_date, meet_code, trial_number))
        sql = f"WITH target_events(trial_date,meet_code,trial_number) AS (VALUES {values_sql})\n" + source_select
        rows.extend(fetch_all(conn, sql, tuple(params)))
    return rows


def capture_database_snapshot(targets: pd.DataFrame, *, include_global_inventory: bool) -> dict[str, Any]:
    conn = open_read_only()
    try:
        target_ids = sorted(targets.horse_id.astype(str).unique().tolist())
        cutoff_by_horse = dict(zip(targets.horse_id.astype(str), targets.history_cutoff.astype(str)))
        max_cutoff = max(cutoff_by_horse.values())
        target_trial_rows: list[dict[str, Any]] = []
        race_history_rows: list[dict[str, Any]] = []

        trial_sql = """
            SELECT t.api_record_id,t.trial_date,t.meet_code,t.trial_number,t.horse_number,
                   t.horse_id,t.finish_position,t.finish_status_raw,t.finish_time_seconds,
                   t.body_weight_kg,t.carried_weight_base_kg,t.jockey_overweight_kg,
                   t.jockey_id,t.jockey_name,t.trainer_id,t.trainer_name,t.pass_flag_raw,
                   t.failure_reason_raw,t.inspection_reason_raw,t.section_times_json,
                   t.breed_label_raw,t.breed_assessment,t.breed_assessment_note,
                   ar.record_index,ar.record_type,ar.natural_key,ar.payload_json,
                   ar.payload_sha256,ar.source_artifact_id,
                   sa.source_family,sa.source_role,sa.public_dataset_id,sa.dataset_name,
                   sa.endpoint,sa.operation,sa.attempt_id,sa.request_params_json,
                   sa.source_url_without_key,sa.collected_at_utc,sa.http_status_code,
                   sa.raw_relative_path,sa.response_bytes,sa.sha256 AS response_sha256,
                   sa.parser_version,sa.created_at_utc
            FROM running_trial_rows t
            JOIN api_records ar ON ar.api_record_id=t.api_record_id
            JOIN source_artifacts sa ON sa.source_artifact_id=ar.source_artifact_id
            WHERE t.horse_id IN ({placeholders}) AND t.trial_date<=?
              AND t.meet_code=2 AND t.breed_assessment='api_native_label'
            ORDER BY t.horse_id,t.trial_date,t.trial_number,t.api_record_id
        """
        race_sql = """
            SELECT r.api_record_id,r.race_date,r.race_number,r.horse_number,r.horse_id,
                   r.finish_position,r.finish_time_seconds,ar.payload_sha256,
                   ar.source_artifact_id,sa.sha256 AS response_sha256,
                   sa.raw_relative_path,sa.collected_at_utc
            FROM race_result_rows r
            JOIN api_records ar ON ar.api_record_id=r.api_record_id
            JOIN source_artifacts sa ON sa.source_artifact_id=ar.source_artifact_id
            WHERE r.horse_id IN ({placeholders}) AND r.race_date<=?
            ORDER BY r.horse_id,r.race_date,r.race_number,r.api_record_id
        """
        for batch in chunks(target_ids, 400):
            in_sql = ",".join("?" for _ in batch)
            target_trial_rows.extend(fetch_all(conn, trial_sql.format(placeholders=in_sql), (*batch, max_cutoff)))
            race_history_rows.extend(fetch_all(conn, race_sql.format(placeholders=in_sql), (*batch, max_cutoff)))

        cutoff_by_horse = {str(row.horse_id): str(row.history_cutoff) for row in targets.itertuples(index=False)}
        target_trial_rows = [row for row in target_trial_rows if row["trial_date"] <= cutoff_by_horse[row["horse_id"]]]
        race_history_rows = [row for row in race_history_rows if row["race_date"] <= cutoff_by_horse[row["horse_id"]]]
        event_keys = sorted({(row["trial_date"], int(row["meet_code"]), int(row["trial_number"])) for row in target_trial_rows})
        event_rows = chunked_event_rows(conn, event_keys)

        global_inventory = None
        if include_global_inventory:
            global_rows = fetch_all(conn, """
                SELECT t.api_record_id,t.trial_date,t.meet_code,t.trial_number,t.horse_number,
                       t.horse_id,t.finish_position,t.finish_status_raw,t.finish_time_seconds,
                       t.pass_flag_raw,t.breed_label_raw,t.breed_assessment,
                       ar.payload_json,ar.payload_sha256,ar.source_artifact_id
                FROM running_trial_rows t JOIN api_records ar USING(api_record_id)
                WHERE t.meet_code=2 AND t.breed_assessment='api_native_label'
                ORDER BY t.trial_date,t.trial_number,t.horse_number,t.api_record_id
            """)
            global_inventory = build_field_inventory(global_rows)

        return {
            "target_trial_rows": target_trial_rows,
            "race_history_rows": race_history_rows,
            "event_rows": event_rows,
            "event_keys": event_keys,
            "global_inventory": global_inventory,
            "read_snapshot": {
                "connection_uri_mode": "mode=ro",
                "pragma_query_only": True,
                "explicit_transaction": True,
                "event_key": "normalized (trial_date, meet_code, trial_number) = raw (trainDate, requested meet=2, trainNo); raw daySerial is preserved and checked as an event invariant, not a second event number",
            },
        }
    finally:
        conn.rollback()
        conn.close()


def value_state(value: Any, *, present: bool) -> str:
    if not present:
        return "key_absent"
    if value is None:
        return "json_null"
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return "empty_string"
        if text == "-":
            return "hyphen_code"
        number = safe_float(text)
        if number is not None:
            if number == 0:
                return "numeric_zero_string"
            return "positive_numeric_string" if number > 0 else "negative_numeric_string"
        return "other_string"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = safe_float(value)
        if number is None:
            return "nonfinite_number"
        if number == 0:
            return "numeric_zero"
        return "positive_number" if number > 0 else "negative_number"
    if isinstance(value, bool):
        return "boolean"
    return type(value).__name__


def build_field_inventory(rows: list[dict[str, Any]]) -> dict[str, Any]:
    payloads = [json.loads(row["payload_json"]) for row in rows]
    inventory: dict[str, Any] = {}
    for field in CORE_FIELDS:
        states: Counter[str] = Counter()
        values: Counter[str] = Counter()
        numerics: list[float] = []
        for payload in payloads:
            present = field in payload
            value = payload.get(field)
            states[value_state(value, present=present)] += 1
            values["<ABSENT>" if not present else stable_json(value)] += 1
            number = safe_float(value)
            if number is not None:
                numerics.append(number)
        numeric_summary: dict[str, Any] = {"count": len(numerics)}
        if numerics:
            numeric_summary.update(min=min(numerics), max=max(numerics), median=float(pd.Series(numerics).median()))
        distinct_items = sorted(values.items(), key=lambda item: (-item[1], item[0]))
        # Keep complete raw enum/order inventories where they are interpretable;
        # avoid embedding thousands of horse IDs/dates in a small audit summary.
        retain_all = field in {"ord", "passFlag", "rcDist", "majong", "meet", "sex"} or len(distinct_items) <= 60
        inventory[field] = {
            "key_present_rows": int(sum(count for state, count in states.items() if state != "key_absent")),
            "state_counts": dict(sorted(states.items())),
            "distinct_raw_value_count": len(distinct_items),
            "distinct_raw_value_counts": dict(distinct_items if retain_all else distinct_items[:25]),
            "distinct_raw_value_counts_truncated": not retain_all,
            "numeric_value_summary": numeric_summary,
        }
    payload_key_counts: Counter[str] = Counter()
    for payload in payloads:
        payload_key_counts.update(payload.keys())
    pass_counts = Counter("<ABSENT>" if "passFlag" not in payload else stable_json(payload.get("passFlag")) for payload in payloads)
    ord_counts = Counter("<ABSENT>" if "ord" not in payload else stable_json(payload.get("ord")) for payload in payloads)
    return {
        "row_count": len(rows),
        "horse_count": len({str(row["horse_id"]) for row in rows if row["horse_id"] is not None}),
        "date_min": min((row["trial_date"] for row in rows), default=None),
        "date_max": max((row["trial_date"] for row in rows), default=None),
        "payload_key_presence_counts": dict(sorted(payload_key_counts.items())),
        "field_inventory": inventory,
        "passFlag_raw_counts": dict(sorted(pass_counts.items(), key=lambda item: (-item[1], item[0]))),
        "ord_raw_counts": dict(sorted(ord_counts.items(), key=lambda item: (-item[1], item[0]))),
        "explicit_distance_field_rows": inventory.get("rcDist", {}).get("key_present_rows", 0),
        "time_field_status_note": "raw item values and key/null/empty/hyphen/zero states are preserved; no time code is converted to zero",
    }


def row_validity(row: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(row["payload_json"])
    raw_order = payload.get("ord") if "ord" in payload else None
    try:
        ordinal = int(str(raw_order).strip())
        ordinal_valid = 1 <= ordinal <= 89 and str(raw_order).strip() == str(ordinal)
    except (TypeError, ValueError):
        ordinal = None
        ordinal_valid = False
    raw_time = payload.get("rcTime") if "rcTime" in payload else None
    time_value = safe_float(raw_time)
    time_valid = time_value is not None and time_value > 0
    raw_judgment = payload.get("passFlag") if "passFlag" in payload else None
    judgment_valid = raw_judgment in COMPLETED_JUDGMENT_LABELS
    reasons = []
    if not ordinal_valid:
        reasons.append("ord_not_integer_1_to_89")
    if not time_valid:
        reasons.append("rcTime_not_finite_positive")
    if not judgment_valid:
        reasons.append("passFlag_outside_known_judgment_allowlist")
    return {
        "raw_ord": raw_scalar_text(raw_order),
        "raw_ord_json": stable_json(raw_order),
        "ordinal_1_to_89": ordinal if ordinal_valid else None,
        "ordinal_valid": ordinal_valid,
        "raw_rcTime": raw_scalar_text(raw_time),
        "raw_rcTime_json": stable_json(raw_time),
        "rcTime_seconds_numeric": time_value,
        "rcTime_valid_positive": time_valid,
        "raw_passFlag": raw_scalar_text(raw_judgment),
        "raw_passFlag_json": stable_json(raw_judgment),
        "passFlag_known_judgment_allowlisted": judgment_valid,
        "valid_for_relative_time_candidate": ordinal_valid and time_valid and judgment_valid,
        "relative_time_hold_reasons": ";".join(reasons),
    }


def dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame.from_records(records)


def build_outputs(targets: pd.DataFrame, snapshot: dict[str, Any], baseline_source: pd.DataFrame) -> dict[str, Any]:
    target_rows = snapshot["target_trial_rows"]
    event_rows = snapshot["event_rows"]
    race_history_rows = snapshot["race_history_rows"]

    target_map = {str(row.horse_id): row._asdict() for row in targets.itertuples(index=False)}
    event_groups: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    natural_key_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in event_rows:
        key = (str(row["trial_date"]), int(row["meet_code"]), int(row["trial_number"]))
        event_groups[key].append(row)
        natural_key_groups[str(row["natural_key"])].append(row)

    event_metrics: dict[tuple[str, int, int], dict[str, Any]] = {}
    event_row_annotated: list[dict[str, Any]] = []
    for key, rows in event_groups.items():
        payloads = [json.loads(row["payload_json"]) for row in rows]
        days = {stable_json(payload.get("daySerial", "<ABSENT>")) for payload in payloads}
        dates_agree = all(iso_date(payload.get("trainDate")) == key[0] for payload in payloads)
        train_numbers_agree = all(safe_float(payload.get("trainNo")) == key[2] for payload in payloads)
        meet_labels = {str(payload.get("meet", "<ABSENT>")) for payload in payloads}
        breed_labels = {str(payload.get("majong", "<ABSENT>")) for payload in payloads}
        ids = [str(row["horse_id"]) for row in rows]
        duplicates = len(ids) - len(set(ids))
        valid_rows = [row for row in rows if row_validity(row)["valid_for_relative_time_candidate"]]
        event_metrics[key] = {
            "trial_event_key": f"{key[0]}|{key[1]}|{key[2]}",
            "trial_date": key[0],
            "meet_code": key[1],
            "trial_number": key[2],
            "daySerial_raw_values_json": stable_json(sorted(days)),
            "daySerial_consistent": len(days) == 1,
            "trainDate_payload_matches_normalized": dates_agree,
            "trainNo_payload_matches_normalized": train_numbers_agree,
            "raw_meet_labels_json": stable_json(sorted(meet_labels)),
            "raw_majong_labels_json": stable_json(sorted(breed_labels)),
            "raw_meet_labels_are_jeju": meet_labels == {"제주"},
            "raw_majong_labels_are_jeju": breed_labels == {"제주"},
            "all_rows_native_label_assessment": all(row["breed_assessment"] == "api_native_label" for row in rows),
            "event_row_count": len(rows),
            "event_distinct_horse_count": len(set(ids)),
            "duplicate_horse_row_count": duplicates,
            "valid_time_peer_count_all_roster": len(valid_rows),
            "event_key_valid": (
                len(days) == 1 and dates_agree and train_numbers_agree and duplicates == 0
                and meet_labels == {"제주"} and breed_labels == {"제주"}
                and all(row["breed_assessment"] == "api_native_label" for row in rows)
            ),
        }
        for row in rows:
            payload = json.loads(row["payload_json"])
            valid = row_validity(row)
            record = dict(row)
            record.update(valid)
            record.update({
                "trial_event_key": event_metrics[key]["trial_event_key"],
                "daySerial_raw": payload.get("daySerial"),
                "raw_trainDate": payload.get("trainDate"),
                "raw_trainNo": payload.get("trainNo"),
                "raw_meet": payload.get("meet"),
                "raw_majong": payload.get("majong"),
                "event_key_valid": event_metrics[key]["event_key_valid"],
                "event_roster_row_count": len(rows),
                "event_roster_distinct_horse_count": len(set(ids)),
                "natural_key_row_count": len(natural_key_groups[str(row["natural_key"])]),
                "natural_key_payload_sha_count": len({item["payload_sha256"] for item in natural_key_groups[str(row["natural_key"])]}),
            })
            event_row_annotated.append(record)

    event_rows_by_record = {int(row["api_record_id"]): row for row in event_row_annotated}
    target_lineage: list[dict[str, Any]] = []
    peer_ledger: list[dict[str, Any]] = []
    target_history: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in target_rows:
        target_history[str(row["horse_id"])].append(row)
    for horse_id, rows in target_history.items():
        rows.sort(key=lambda item: (str(item["trial_date"]), int(item["trial_number"]), int(item["horse_number"] or -1), int(item["api_record_id"])))
        total_count = len(rows)
        for index, row in enumerate(rows):
            slot_desc = total_count - index
            target = target_map[horse_id]
            key = (str(row["trial_date"]), int(row["meet_code"]), int(row["trial_number"]))
            row_id = int(row["api_record_id"])
            event_row = event_rows_by_record[row_id]
            validity = row_validity(row)
            peer_rows = [
                other for other in event_groups[key]
                if str(other["horse_id"]) != horse_id and row_validity(other)["valid_for_relative_time_candidate"]
            ]
            peer_times = [float(row_validity(other)["rcTime_seconds_numeric"]) for other in peer_rows]
            peer_median = float(pd.Series(peer_times).median()) if peer_times else None
            relative_gap = None
            if validity["valid_for_relative_time_candidate"] and len(peer_times) >= 2 and peer_median is not None and peer_median > 0:
                relative_gap = (float(validity["rcTime_seconds_numeric"]) - peer_median) / peer_median
            payload = json.loads(row["payload_json"])
            gap_days = (date.fromisoformat(str(target["history_cutoff"])) - date.fromisoformat(str(row["trial_date"]))).days
            lineage_row = {
                "target_api_record_id": int(target["api_record_id"]),
                "target_race_id": str(target["race_id"]),
                "target_race_date": str(target["race_date"]),
                "target_history_cutoff": str(target["history_cutoff"]),
                "target_horse_id": horse_id,
                "target_horse_number": int(target["horse_number"]),
                "target_distance_m": float(target["distance_m"]),
                "trial_slot_rank_desc": slot_desc,
                "is_latest3_trial_record": slot_desc <= 3,
                "trial_event_key": event_metrics[key]["trial_event_key"],
                "trial_date": str(row["trial_date"]),
                "meet_code": int(row["meet_code"]),
                "trial_number": int(row["trial_number"]),
                "daySerial_raw": payload.get("daySerial"),
                "trial_horse_number": row["horse_number"],
                "trial_horse_id": horse_id,
                "target_trial_api_record_id": row_id,
                "target_trial_payload_sha256": row["payload_sha256"],
                "source_artifact_id": int(row["source_artifact_id"]),
                "source_response_sha256": row["response_sha256"],
                "source_raw_relative_path": row["raw_relative_path"],
                "source_collected_at_utc": row["collected_at_utc"],
                "source_parser_version": row["parser_version"],
                "raw_ord": validity["raw_ord"],
                "raw_rcTime": validity["raw_rcTime"],
                "rcTime_seconds_numeric": validity["rcTime_seconds_numeric"],
                "raw_passFlag": validity["raw_passFlag"],
                "ordinal_valid_1_to_89": validity["ordinal_valid"],
                "rcTime_valid_finite_positive": validity["rcTime_valid_positive"],
                "passFlag_known_judgment_allowlisted": validity["passFlag_known_judgment_allowlisted"],
                "valid_for_relative_time_candidate": validity["valid_for_relative_time_candidate"],
                "relative_time_hold_reasons": validity["relative_time_hold_reasons"],
                "event_key_valid": event_row["event_key_valid"],
                "days_before_cutoff": gap_days,
            }
            target_lineage.append(lineage_row)
            peer_ledger.append({
                "target_api_record_id": int(target["api_record_id"]),
                "target_race_id": str(target["race_id"]),
                "target_race_date": str(target["race_date"]),
                "target_history_cutoff": str(target["history_cutoff"]),
                "target_horse_id": horse_id,
                "target_trial_api_record_id": row_id,
                "target_trial_payload_sha256": row["payload_sha256"],
                "trial_event_key": event_metrics[key]["trial_event_key"],
                "trial_date": str(row["trial_date"]),
                "meet_code": int(row["meet_code"]),
                "trial_number": int(row["trial_number"]),
                "daySerial_raw": payload.get("daySerial"),
                "event_key_valid": event_row["event_key_valid"],
                "event_roster_row_count": event_row["event_roster_row_count"],
                "event_roster_distinct_horse_count": event_row["event_roster_distinct_horse_count"],
                "event_explicit_jeju_row_count": sum(x["breed_assessment"] == "api_native_label" for x in event_groups[key]),
                "event_roster_horse_ids_json": stable_json(sorted({str(x["horse_id"]) for x in event_groups[key]})),
                "target_raw_ord": validity["raw_ord"],
                "target_raw_rcTime": validity["raw_rcTime"],
                "target_raw_passFlag": validity["raw_passFlag"],
                "target_relative_time_eligible": validity["valid_for_relative_time_candidate"],
                "valid_peer_count_excluding_target": len(peer_rows),
                "valid_peer_median_rcTime_seconds": peer_median,
                "valid_peer_api_record_ids_json": stable_json(sorted(int(x["api_record_id"]) for x in peer_rows)),
                "valid_peer_horse_ids_json": stable_json(sorted(str(x["horse_id"]) for x in peer_rows)),
                "relative_time_gap_candidate": relative_gap,
                "relative_time_gap_candidate_eligible": relative_gap is not None and event_row["event_key_valid"],
                "relative_time_formula": "(target rcTime - median(valid same-event explicit-Jeju peers excluding target)) / median(valid same-event explicit-Jeju peers excluding target)",
            })

    lineage_df = dataframe(target_lineage)
    peer_df = dataframe(peer_ledger)
    if len(lineage_df):
        lineage_df = lineage_df.sort_values(["target_horse_id", "trial_slot_rank_desc"], ascending=[True, True], kind="stable")
        peer_df = peer_df.sort_values(["target_horse_id", "trial_date", "trial_number", "target_trial_api_record_id"], kind="stable")

    history_by_horse: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in race_history_rows:
        history_by_horse[str(row["horse_id"])].append(row)
    baseline_by_horse: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in baseline_source.to_dict(orient="records"):
        if str(row["horse_id"]) in target_map:
            baseline_by_horse[str(row["horse_id"])].append(row)

    race_history_audit: list[dict[str, Any]] = []
    target_roster: list[dict[str, Any]] = []
    for target in targets.to_dict(orient="records"):
        horse_id = str(target["horse_id"])
        cutoff = str(target["history_cutoff"])
        db_rows = [row for row in history_by_horse[horse_id] if str(row["race_date"]) <= cutoff]
        base_rows = [row for row in baseline_by_horse[horse_id] if str(row["race_date"]) <= cutoff]
        started_db = [row for row in db_rows if row["finish_position"] is not None and (1 <= int(row["finish_position"]) <= 89 or int(row["finish_position"]) in (91, 92))]
        started_base = [row for row in base_rows if bool(row.get("started"))]
        base_api_ids = {int(row["api_record_id"]) for row in base_rows}
        db_api_ids = {int(row["api_record_id"]) for row in db_rows}
        trial_rows_horse = [row for row in target_rows if str(row["horse_id"]) == horse_id]
        trial_rows_horse.sort(key=lambda row: (str(row["trial_date"]), int(row["trial_number"]), int(row["api_record_id"])), reverse=True)
        latest = trial_rows_horse[0] if trial_rows_horse else None
        cutoff_day = date.fromisoformat(cutoff)
        latest_gap = (cutoff_day - date.fromisoformat(str(latest["trial_date"]))).days if latest else None
        target_peer_rows = peer_df.loc[peer_df.target_horse_id.eq(horse_id)] if len(peer_df) else pd.DataFrame()
        latest3 = target_peer_rows.loc[target_peer_rows.target_trial_api_record_id.isin([int(x["api_record_id"]) for x in trial_rows_horse[:3]])] if len(target_peer_rows) else target_peer_rows
        latest3_valid = latest3.loc[latest3.relative_time_gap_candidate_eligible.eq(True)] if len(latest3) else latest3
        latest3_values = latest3_valid.relative_time_gap_candidate.astype(float).tolist() if len(latest3_valid) else []
        target_roster.append({
            "target_api_record_id": int(target["api_record_id"]),
            "race_id": str(target["race_id"]),
            "race_date": str(target["race_date"]),
            "year": int(target["year"]),
            "history_cutoff": cutoff,
            "horse_id": horse_id,
            "horse_number": int(target["horse_number"]),
            "distance_m": float(target["distance_m"]),
            "observed_starts_baseline": int(target["observed_starts"]),
            "baseline_prior_source_rows_n": len(base_rows),
            "baseline_prior_started_rows_n": len(started_base),
            "current_db_prior_rows_n": len(db_rows),
            "current_db_prior_started_rows_n": len(started_db),
            "current_db_prior_nonstarted_rows_n": len(db_rows) - len(started_db),
            "baseline_current_db_prior_row_ids_equal": base_api_ids == db_api_ids,
            "current_db_prior_row_ids_not_in_frozen_source_json": stable_json(sorted(db_api_ids - base_api_ids)),
            "frozen_source_prior_row_ids_missing_from_current_db_json": stable_json(sorted(base_api_ids - db_api_ids)),
            "trial_event_record_n_including_invalid_or_cancelled_rows": len(trial_rows_horse),
            "trial_distinct_event_n": len({(row["trial_date"], row["meet_code"], row["trial_number"]) for row in trial_rows_horse}),
            "trial_latest_record_date": str(latest["trial_date"]) if latest else None,
            "days_from_latest_record_to_cutoff": latest_gap,
            "latest3_trial_record_n": min(3, len(trial_rows_horse)),
            "latest3_relative_time_valid_n": len(latest3_valid),
            "latest3_relative_time_gap_mean": float(sum(latest3_values) / len(latest3_values)) if latest3_values else None,
        })
        for row in db_rows:
            race_history_audit.append({
                "target_api_record_id": int(target["api_record_id"]),
                "target_race_id": str(target["race_id"]),
                "target_race_date": str(target["race_date"]),
                "target_history_cutoff": cutoff,
                "target_horse_id": horse_id,
                "historical_race_api_record_id": int(row["api_record_id"]),
                "historical_race_date": str(row["race_date"]),
                "historical_race_number": int(row["race_number"]),
                "historical_horse_number": row["horse_number"],
                "historical_finish_position_raw": row["finish_position"],
                "historical_finish_time_seconds": row["finish_time_seconds"],
                "started_by_f1_rule": row["finish_position"] is not None and (1 <= int(row["finish_position"]) <= 89 or int(row["finish_position"]) in (91, 92)),
                "historical_payload_sha256": row["payload_sha256"],
                "historical_source_artifact_id": int(row["source_artifact_id"]),
                "historical_source_response_sha256": row["response_sha256"],
                "historical_source_raw_relative_path": row["raw_relative_path"],
            })

    # Attach a per-target summary to the event lineage without adding profile data.
    target_roster_df = dataframe(target_roster).sort_values(["race_date", "race_id", "horse_number"], kind="stable")
    target_trial_lineage_df = lineage_df
    event_rows_df = dataframe(event_row_annotated).sort_values(["trial_date", "trial_number", "horse_number", "api_record_id"], kind="stable")
    race_history_df = dataframe(race_history_audit).sort_values(["target_horse_id", "historical_race_date", "historical_race_api_record_id"], kind="stable") if race_history_audit else pd.DataFrame()

    event_metrics_rows = list(event_metrics.values())
    event_key_audit = dataframe(event_metrics_rows)
    event_key_audit = event_key_audit.sort_values(["trial_date", "trial_number"], kind="stable") if len(event_key_audit) else event_key_audit

    # A scoped fingerprint contains target-linked API20 payloads, all peer rows for
    # those events, their source-artifact provenance, and target prior-race rows.
    related_api_fingerprint = stable_fingerprint(event_rows)
    target_api_fingerprint = stable_fingerprint(target_rows)
    history_fingerprint = stable_fingerprint(race_history_rows)
    source_artifacts = {}
    for row in event_rows:
        source_artifacts[int(row["source_artifact_id"])] = {
            name: row[name] for name in (
                "source_artifact_id", "source_family", "source_role", "public_dataset_id",
                "dataset_name", "endpoint", "operation", "attempt_id", "request_params_json",
                "source_url_without_key", "collected_at_utc", "http_status_code",
                "raw_relative_path", "response_bytes", "response_sha256", "parser_version",
                "created_at_utc",
            )
        }
    return {
        "target_roster": target_roster_df,
        "target_trial_lineage": target_trial_lineage_df,
        "trial_event_rows": event_rows_df,
        "trial_event_relative_peer_ledger": peer_df,
        "target_prior_race_history_audit": race_history_df,
        "event_key_audit": event_key_audit,
        "source_artifacts": list(source_artifacts.values()),
        "fingerprints": {
            "target_linked_api20_rows_sha256": related_api_fingerprint,
            "cold_horse_target_api20_rows_sha256": target_api_fingerprint,
            "target_prior_race_rows_sha256": history_fingerprint,
            "event_row_count": len(event_rows),
            "target_trial_row_count": len(target_rows),
            "target_prior_race_row_count": len(race_history_rows),
            "event_count": len(event_groups),
        },
    }


def counts_and_summary(targets: pd.DataFrame, outputs: dict[str, Any], global_inventory: dict[str, Any]) -> dict[str, Any]:
    roster = outputs["target_roster"]
    lineage = outputs["target_trial_lineage"]
    event_rows = outputs["trial_event_rows"]
    peers = outputs["trial_event_relative_peer_ledger"]
    event_audit = outputs["event_key_audit"]
    if len(lineage):
        pass_counts = Counter(str(v) for v in lineage.raw_passFlag.fillna("<NULL>"))
        ordinal_valid = int(lineage.ordinal_valid_1_to_89.sum())
        rc_time_valid = int(lineage.rcTime_valid_finite_positive.sum())
        pair_valid = int(lineage.valid_for_relative_time_candidate.sum())
    else:
        pass_counts, ordinal_valid, rc_time_valid, pair_valid = Counter(), 0, 0, 0
    latest3_lineage = lineage.loc[lineage.is_latest3_trial_record.eq(True)] if len(lineage) else lineage
    latest3_peer_valid = latest3_lineage.loc[latest3_lineage.valid_for_relative_time_candidate.eq(True)] if len(latest3_lineage) else latest3_lineage
    supported_latest3 = peers.loc[peers.relative_time_gap_candidate_eligible.eq(True) & peers.target_trial_api_record_id.isin(latest3_lineage.target_trial_api_record_id)] if len(peers) else peers
    prior_nonstarted = outputs["target_prior_race_history_audit"]
    return {
        "frozen_target_cohort": {
            "features_path": str(FEATURES.relative_to(ROOT)),
            "features_sha256": sha256_file(FEATURES),
            "features_rows": int(len(pd.read_parquet(FEATURES))),
            "cold_target_rows": int(len(targets)),
            "cold_target_horses": int(targets.horse_id.nunique()),
            "cold_target_races": int(targets.race_id.nunique()),
            "observed_starts_definition": "F1_STYLE6 features.parquet observed_starts == 0; this is no prior started source row under the frozen DB/source definition, not proof of lifetime first race.",
            "user_excluded_horse_3005648_in_target": bool(targets.horse_id.astype(str).eq("3005648").any()),
            "race_date_min": str(targets.race_date.min()),
            "race_date_max": str(targets.race_date.max()),
            "history_cutoff_min": str(targets.history_cutoff.min()),
            "history_cutoff_max": str(targets.history_cutoff.max()),
            "all_history_cutoffs_equal_race_date_minus_2_days": bool(all(
                date.fromisoformat(str(row.race_date)) - timedelta(days=2) == date.fromisoformat(str(row.history_cutoff))
                for row in targets.itertuples(index=False)
            )),
        },
        "current_api20_explicit_jeju_scope": global_inventory,
        "cold_target_history_check": {
            "current_database_prior_race_rows": int(len(prior_nonstarted)),
            "current_database_prior_started_rows_by_f1_rule": int(prior_nonstarted.started_by_f1_rule.sum()) if len(prior_nonstarted) else 0,
            "current_database_prior_nonstarted_rows": int((~prior_nonstarted.started_by_f1_rule).sum()) if len(prior_nonstarted) else 0,
            "targets_with_any_prior_race_row": int(prior_nonstarted.target_horse_id.nunique()) if len(prior_nonstarted) else 0,
            "targets_with_any_prior_started_row": int(prior_nonstarted.loc[prior_nonstarted.started_by_f1_rule, "target_horse_id"].nunique()) if len(prior_nonstarted) else 0,
            "prior_finish_position_raw_counts": dict(Counter(str(value) for value in prior_nonstarted.historical_finish_position_raw.fillna("<NULL>"))) if len(prior_nonstarted) else {},
            "all_targets_current_db_prior_started_rows_zero": bool(roster.current_db_prior_started_rows_n.eq(0).all()),
            "baseline_and_current_prior_row_ids_equal_for_all_targets": bool(roster.baseline_current_db_prior_row_ids_equal.all()),
            "baseline_prior_started_rows_zero_for_all_targets": bool(roster.baseline_prior_started_rows_n.eq(0).all()),
            "interpretation": "Prior rows with finish codes 94/95/99 remain non-starters under the F1 rule. Event record alone does not establish a lifetime first start.",
        },
        "api20_target_trial_coverage": {
            "target_registered_trial_event_rows_through_individual_T_minus_2": int(len(lineage)),
            "target_horses_with_one_or_more_registered_trial_event_rows": int(roster.loc[roster.trial_event_record_n_including_invalid_or_cancelled_rows.gt(0), "horse_id"].nunique()),
            "target_horses_without_registered_trial_event_rows": int(roster.loc[roster.trial_event_record_n_including_invalid_or_cancelled_rows.eq(0), "horse_id"].nunique()),
            "target_event_key_count": int(event_audit.trial_event_key.nunique()) if len(event_audit) else 0,
            "all_full_event_roster_rows": int(len(event_rows)),
            "all_full_event_roster_distinct_horses": int(event_rows.horse_id.nunique()) if len(event_rows) else 0,
            "full_event_roster_min_horses": int(event_audit.event_distinct_horse_count.min()) if len(event_audit) else None,
            "full_event_roster_max_horses": int(event_audit.event_distinct_horse_count.max()) if len(event_audit) else None,
            "all_event_rows_api_native_label": bool(event_rows.breed_assessment.eq("api_native_label").all()) if len(event_rows) else False,
            "events_daySerial_invariant": int(event_audit.daySerial_consistent.eq(True).sum()) if len(event_audit) else 0,
            "events_with_daySerial_inconsistency": int(event_audit.daySerial_consistent.eq(False).sum()) if len(event_audit) else 0,
            "events_trainDate_and_trainNo_match_normalized": int((event_audit.trainDate_payload_matches_normalized & event_audit.trainNo_payload_matches_normalized).sum()) if len(event_audit) else 0,
            "events_raw_meet_and_majong_labels_are_jeju": int((event_audit.raw_meet_labels_are_jeju & event_audit.raw_majong_labels_are_jeju).sum()) if len(event_audit) else 0,
            "events_all_rows_native_label_assessment": int(event_audit.all_rows_native_label_assessment.eq(True).sum()) if len(event_audit) else 0,
            "validated_event_key_count": int(event_audit.event_key_valid.sum()) if len(event_audit) else 0,
            "events_with_duplicate_horse_rows": int(event_audit.duplicate_horse_row_count.gt(0).sum()) if len(event_audit) else 0,
            "duplicate_natural_key_groups": int((event_rows.natural_key_row_count.gt(1)).sum()) if len(event_rows) else 0,
            "natural_keys_with_multiple_payload_sha": int(event_rows.loc[event_rows.natural_key_payload_sha_count.gt(1), "natural_key"].nunique()) if len(event_rows) else 0,
            "target_raw_passFlag_counts": dict(sorted(pass_counts.items())),
            "target_positive_finite_rcTime_count": rc_time_valid,
            "target_ordinal_integer_1_to_89_count": ordinal_valid,
            "target_candidate_time_and_known_judgment_count": pair_valid,
            "target_valid_peer_count_ge_2_slots": int(peers.valid_peer_count_excluding_target.ge(2).sum()) if len(peers) else 0,
            "target_relative_gap_candidate_eligible_slots": int(peers.relative_time_gap_candidate_eligible.sum()) if len(peers) else 0,
            "latest3_lineage_slots": int(len(latest3_lineage)),
            "latest3_source_row_valid_by_time_order_judgment_count": int(len(latest3_peer_valid)),
            "latest3_relative_gap_candidate_eligible_count": int(len(supported_latest3)),
            "invalid_or_cancelled_slot_policy": "Retain the API20 horse-event record in count and latest-three lineage; raw ord, rcTime, passFlag and hold reason remain explicit. Do not call every row a performed trial.",
        },
        "time_and_event_key_contract": {
            "normalized_event_key": ["trial_date", "meet_code", "trial_number"],
            "raw_event_key_fields": ["trainDate", "request meet=2", "trainNo"],
            "daySerial": "Preserved as a raw API20 field and checked for within-event invariance; not the event number in local loader natural-key code.",
            "participant_natural_key": "trainDate|2|trainNo|chulNo|hrNo in local API20 parser; raw API item and response-page hashes are stored separately.",
            "event_order": "Within target horse, ascending trial_date then trial_number; latest record rank 1. Same-day separate trainNo values remain separate event slots. daySerial must be invariant within the normalized event key.",
            "relative_time_candidate": "Only within the same event; target and at least two other explicit-Jeju peers each require finite positive rcTime, integer ord 1..89, and passFlag in the observed known-judgment allowlist. Candidate=(target rcTime - median(peer rcTime))/median(peer rcTime).",
            "unknown_distance": "API20 raw `rcDist` key is absent in the current explicit-Jeju source. No cross-distance raw-time average or trial-to-race time conversion is supported.",
            "public_availability": "Source events have a date, while API collection timestamps identify later retrieval. Historical public availability time was not established; date cutoff is a retrospective T-2 filter only.",
        },
    }


def write_parquet_new(path: Path, frame: pd.DataFrame) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite {path}")
    frame.to_parquet(path, index=False)


def write_json_new(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n", encoding="utf-8")


def main() -> None:
    if OUT.exists() and any(OUT.iterdir()):
        raise FileExistsError(f"Refusing to overwrite non-empty output directory: {OUT}")
    OUT.mkdir(exist_ok=True)

    features = pd.read_parquet(FEATURES)
    target = features.loc[features.observed_starts.eq(0), [
        "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
        "distance_m", "history_cutoff", "observed_starts",
    ]].copy()
    target["horse_id"] = target.horse_id.astype(str)
    target["history_cutoff"] = target.history_cutoff.astype(str)
    target["race_date"] = target.race_date.astype(str)
    if target.horse_id.duplicated().any() or target.api_record_id.duplicated().any():
        raise AssertionError("Expected exactly one frozen cold target start per horse and target API record")
    for row in target.itertuples(index=False):
        if date.fromisoformat(str(row.race_date)) - timedelta(days=2) != date.fromisoformat(str(row.history_cutoff)):
            raise AssertionError(f"Unexpected F1 history cutoff for target {row.api_record_id}")

    baseline_source = pd.read_parquet(BASELINE_SOURCE)
    baseline_source["horse_id"] = baseline_source.horse_id.astype(str)
    if "started" not in baseline_source.columns:
        raise AssertionError("Frozen F1 source snapshot lacks the started indicator")

    # Take a scoped pre-capture fingerprint, one complete extraction snapshot,
    # then an independent scoped post-capture fingerprint. No whole-DB hash is used.
    before = capture_database_snapshot(target, include_global_inventory=False)
    source_outputs = capture_database_snapshot(target, include_global_inventory=True)
    after = capture_database_snapshot(target, include_global_inventory=False)
    before_fingerprint = build_outputs(target, before, baseline_source)["fingerprints"]
    source_output = build_outputs(target, source_outputs, baseline_source)
    after_fingerprint = build_outputs(target, after, baseline_source)["fingerprints"]

    # The audit outputs intentionally keep the cold target definition and source
    # observations separate. Profile-current columns are never queried.
    write_parquet_new(OUT / "cold_target_roster.parquet", source_output["target_roster"])
    write_parquet_new(OUT / "api20_trial_event_rows.parquet", source_output["trial_event_rows"])
    write_parquet_new(OUT / "trial_event_relative_peer_ledger.parquet", source_output["trial_event_relative_peer_ledger"])
    write_parquet_new(OUT / "cold_target_trial_lineage.parquet", source_output["target_trial_lineage"])
    write_parquet_new(OUT / "cold_target_prior_race_history_audit.parquet", source_output["target_prior_race_history_audit"])
    write_parquet_new(OUT / "trial_event_key_audit.parquet", source_output["event_key_audit"])
    write_json_new(OUT / "source_artifacts.json", source_output["source_artifacts"])

    source_stable = before_fingerprint == source_output["fingerprints"] == after_fingerprint
    summary = counts_and_summary(target, source_output, source_outputs["global_inventory"])
    summary["scoped_source_stability"] = {
        "pre_capture": before_fingerprint,
        "within_extraction_transaction": source_output["fingerprints"],
        "post_capture": after_fingerprint,
        "stable_across_captures": source_stable,
        "scope": "only cold-target linked API20 participant rows, complete source rows for linked events, source artifacts, and cold-target prior race rows; no whole-database checksum",
    }
    write_json_new(OUT / "audit_summary.json", summary)

    input_paths = [
        FEATURES, BASELINE_SOURCE, STYLE_README, TRIAL_BACKFILL_README,
        HORSE_ANALYSIS_README, SOURCE_CONTRACT, TRIAL_INVENTORY,
        API20_LOADER, AGENTS_GUIDANCE, RESTART_PLAN, REVIEW_DOCS_README,
        AUDIT_README,
    ]
    output_paths = sorted(path for path in OUT.iterdir() if path.is_file())
    manifest = {
        "audit_name": "20261018_debut_trial_source_audit_v1",
        "created_at_local": datetime.now().astimezone().isoformat(),
        "scope": "Read-only source audit for F1_STYLE6 cold targets; no fitting, prediction, model or DB writes.",
        "audit_code": {"path": str(Path(__file__).relative_to(ROOT)), "sha256": sha256_file(Path(__file__))},
        "database": {
            "path": str(DB),
            "read_mode": "SQLite URI mode=ro; PRAGMA query_only=ON; explicit read transaction for all related source rows and source_artifact provenance.",
            "whole_database_hash": None,
            "source_scope_fingerprints": summary["scoped_source_stability"],
        },
        "frozen_inputs": {
            str(path.relative_to(ROOT)): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in input_paths
        },
        "source_contract": {
            "trial_source": "API20 GET /API20_1/ridingTestResult_1; explicitly native-label rows only; event date is not publication time.",
            "starting_exam_api21": "Out of scope and not joined.",
            "current_profile": "Not queried or joined; no current name, age, sex, or affiliation is copied into features.",
            "event_key": summary["time_and_event_key_contract"]["normalized_event_key"],
            "event_order": summary["time_and_event_key_contract"]["event_order"],
            "relative_time_validity": {
                "ordinal": "Raw ord must parse as an integer in 1..89; special codes remain raw and held.",
                "time": "Raw rcTime must be finite and positive.",
                "judgment_allowlist_observed_in_source": sorted(COMPLETED_JUDGMENT_LABELS),
                "peers": "At least two other valid explicit-Jeju records in the same validated event key, excluding the target.",
                "formula": summary["time_and_event_key_contract"]["relative_time_candidate"],
            },
            "event_count_semantics": "Count distinct observed target horse-event record keys, including cancelled/unperformed records; this is not a count of actual completed tests.",
            "distance": summary["time_and_event_key_contract"]["unknown_distance"],
        },
        "official_source_references": [
            {"title": "한국마사회 주행심사 상세결과 API20", "url": "https://www.data.go.kr/data/15056974/openapi.do", "note": "Official description lists test date, examination round/race number, rank, entry/horse number, judgement, reasons, and time-related result fields; accessible metadata does not provide a distance field or a complete judgment enum table."},
            {"title": "KRA 제주 경마시행계획 2024", "url": "https://race.kra.co.kr/down/raceplan_2024_jeju.pdf", "note": "Official rules describe a breed-dependent test distance; this does not add an event-level distance to the API20 payload."},
            {"title": "KRA 제주 경마시행 주요 변경사항", "url": "https://race.kra.co.kr/raceoper/RaceoperView.do?Act=12&Sub=2&meet=2", "note": "Official current rule notes future distance changes; reinforces that distance must not be guessed as a timeless constant."},
        ],
        "outputs": {
            path.name: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in output_paths
        },
        "manifest_contract": "This manifest records row-scoped source fingerprints, not a whole-DB hash. Current source rows may change independently outside the audited scope.",
    }
    write_json_new(OUT / "audit_manifest.json", manifest)

    print(json.dumps({
        "output_dir": str(OUT),
        "target_count": len(target),
        "event_row_count": len(source_output["trial_event_rows"]),
        "target_trial_lineage_count": len(source_output["target_trial_lineage"]),
        "event_key_count": len(source_output["event_key_audit"]),
        "scoped_source_stable": source_stable,
        "summary": summary["api20_target_trial_coverage"],
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
