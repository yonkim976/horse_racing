"""Read-only source freeze for the 2026-09-20..2026-10-17 F1_STYLE6 cohort.

Only this new research folder is written. The frozen September 19 source,
existing point cache, operating registry, and SQLite database are read-only.
No model is trained or scored here.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
import hashlib
import json
import math
import numbers
from pathlib import Path
import re
import sqlite3
from typing import Any

import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
BASELINE = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet"
OLD_POINT_CACHE = ROOT / "jeju/research/20261010_style_history_source_audit_v1/api4_full_started_point_quality_cache.parquet"
EXCLUSIONS = ROOT / "jeju/data/horse_exclusions.json"
START_DATE = "2026-09-20"
END_DATE = "2026-10-17"
BASELINE_END = "2026-09-19"
DISTANCES = {800, 900, 1000, 1110, 1200, 1300, 1400, 1610}
FROZEN_COLUMNS = [
    "api_record_id", "race_date", "meet_code", "race_number", "horse_id",
    "horse_name", "horse_number", "race_distance_m", "rank_class_raw",
    "finish_position", "finish_time_seconds", "carried_weight_kg", "track_raw",
    "age_at_race_raw", "sex_at_race_raw", "api4_3_payload_sha256", "race_id",
    "year", "started", "valid_time",
]
ORDER_FIELDS = {"S1F": "sjS1fOrd", "4C": "sj_4cOrd", "G1F": "sjG1fOrd"}
ORDER_OK = {"api_positive_unreviewed", "website_corrected"}
GROUP_OK = {"api_group_unreviewed", "api_group_unavailable"}
PASS_FLAGS = {
    "합격", "불합격", "주행불합격", "출발불합격", "불합격(능검)",
    "발주불합격", "불합격(발검)",
}
SOURCE_FP_COLUMNS = [
    "api_record_id", "source_artifact_id", "record_index", "record_type", "natural_key",
    "payload_json", "payload_sha256", "source_family", "source_role", "public_dataset_id",
    "dataset_name", "endpoint", "operation", "attempt_id", "request_params_json",
    "source_url_without_key", "collected_at_utc", "http_status_code", "raw_relative_path",
    "response_bytes", "response_sha256", "parser_version", "created_at_utc",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint(rows: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for row in sorted(rows, key=lambda r: stable_json(r)):
        h.update(stable_json(row).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def source_projection(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: record.get(key) for key in SOURCE_FP_COLUMNS} for record in records]


def write_frame(path: Path, frame: pd.DataFrame) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    frame.to_parquet(path, index=False)


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def connect_ro() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    return conn


def rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def chunks(values: list[str], n: int = 350) -> list[list[str]]:
    return [values[i:i+n] for i in range(0, len(values), n)]


def parse_payload(raw: str) -> dict[str, Any]:
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise TypeError("API payload_json is not an object")
    return obj


def canonical_race_id(row: dict[str, Any]) -> str:
    return f"{row['race_date']}_{int(row['meet_code'])}_{int(row['race_number'])}"


def result_source_query(where: str, params: tuple[Any, ...]) -> str:
    return f"""
        SELECT r.api_record_id,r.race_date,r.meet_code,r.race_number,r.horse_number,
               r.horse_id,r.horse_name,r.race_distance_m,r.rank_class_raw,r.race_name_raw,
               r.finish_position,r.finish_status_raw,r.finish_time_seconds,
               r.carried_weight_kg,r.body_weight_raw,r.jockey_id,r.jockey_name,
               r.trainer_id,r.trainer_name,r.owner_id,r.owner_name,r.track_raw,r.weather_raw,
               r.breed_label_raw,r.breed_assessment,r.breed_assessment_note,
               ar.record_index,ar.record_type,ar.natural_key,ar.payload_json,
               ar.payload_sha256,ar.source_artifact_id,
               sa.source_family,sa.source_role,sa.public_dataset_id,sa.dataset_name,
               sa.endpoint,sa.operation,sa.attempt_id,sa.request_params_json,
               sa.source_url_without_key,sa.collected_at_utc,sa.http_status_code,
               sa.raw_relative_path,sa.response_bytes,sa.sha256 AS response_sha256,
               sa.parser_version,sa.created_at_utc
        FROM race_result_rows r
        JOIN api_records ar ON ar.api_record_id=r.api_record_id
        JOIN source_artifacts sa ON sa.source_artifact_id=ar.source_artifact_id
        WHERE {where}
        ORDER BY r.race_date,r.meet_code,r.race_number,r.horse_number,r.api_record_id
    """


def enrich_race_rows(records: list[dict[str, Any]]) -> pd.DataFrame:
    enriched = []
    for source in records:
        r = dict(source)
        payload = parse_payload(r["payload_json"])
        if sha256_text(r["payload_json"]) != r["payload_sha256"]:
            raise AssertionError(f"payload hash mismatch for API4 record {r['api_record_id']}")
        r["api4_3_payload_sha256"] = r["payload_sha256"]
        r["race_id"] = canonical_race_id(r)
        r["year"] = int(str(r["race_date"])[:4])
        # Preserve the historical API4 fields from the exact record payload.
        r["age_at_race_raw"] = payload.get("age") if "age" in payload else None
        r["sex_at_race_raw"] = payload.get("sex") if "sex" in payload else None
        try:
            pos = int(r["finish_position"])
        except (TypeError, ValueError):
            pos = None
        time = r["finish_time_seconds"]
        r["started"] = pos is not None and (1 <= pos <= 89 or pos in {91, 92})
        r["valid_time"] = pos is not None and 1 <= pos <= 89 and time is not None and math.isfinite(float(time)) and float(time) > 0
        enriched.append(r)
    return pd.DataFrame(enriched)


def eligibility_ledger(df: pd.DataFrame, full_counts: dict[str, int]) -> pd.DataFrame:
    ledger = []
    for race_id, g in df.groupby("race_id", sort=True, dropna=False):
        n = len(g)
        reasons = []
        if not g.breed_assessment.eq("api_cross_reference_candidate").all():
            reasons.append("not_all_candidate_scope")
        if not g.race_distance_m.isin(DISTANCES).all():
            reasons.append("outside_current_distances")
        if n < 6:
            reasons.append("fewer_than_6")
        if n != full_counts.get(str(race_id)):
            reasons.append("partial_vs_full_raw_roster")
        if not g.valid_time.all():
            reasons.append("non_normal_or_nonpositive_time")
        ranks = sorted(int(x) for x in g.finish_position.dropna().tolist())
        if ranks != list(range(1, n + 1)):
            reasons.append("ranks_not_complete_unique_1_to_N")
        if g.horse_id.isna().any() or g.horse_id.nunique(dropna=False) != n:
            reasons.append("duplicate_or_missing_horse_id")
        if g.horse_number.isna().any() or (pd.to_numeric(g.horse_number, errors="coerce") <= 0).any() or g.horse_number.nunique(dropna=False) != n:
            reasons.append("invalid_or_duplicate_number")
        for col in ("race_distance_m", "rank_class_raw"):
            if g[col].nunique(dropna=False) != 1:
                reasons.append("within_race_condition_conflict")
                break
        ledger.append({
            "race_id": str(race_id), "race_date": str(g.race_date.iloc[0]),
            "meet_code": int(g.meet_code.iloc[0]), "race_number": int(g.race_number.iloc[0]),
            "candidate_rows": int(n), "full_raw_rows": int(full_counts.get(str(race_id), 0)),
            "unique_horses": int(g.horse_id.nunique(dropna=False)),
            "distance_m": None if pd.isna(g.race_distance_m.iloc[0]) else int(g.race_distance_m.iloc[0]),
            "race_included": not reasons, "eligibility_reason": "|".join(reasons),
        })
    return pd.DataFrame(ledger)


def api20_rows_for_horses(conn: sqlite3.Connection, horse_ids: list[str], max_cutoff: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    sql_template = """
        SELECT t.api_record_id,t.trial_date,t.meet_code,t.trial_number,t.horse_number,
               t.horse_id,t.horse_name,t.finish_position,t.finish_status_raw,t.finish_time_seconds,
               t.body_weight_kg,t.carried_weight_base_kg,t.jockey_overweight_kg,t.jockey_id,
               t.jockey_name,t.trainer_id,t.trainer_name,t.pass_flag_raw,t.failure_reason_raw,
               t.inspection_reason_raw,t.section_times_json,t.breed_label_raw,
               t.breed_assessment,t.breed_assessment_note,ar.record_index,ar.record_type,
               ar.natural_key,ar.payload_json,ar.payload_sha256,ar.source_artifact_id,
               sa.source_family,sa.source_role,sa.public_dataset_id,sa.dataset_name,sa.endpoint,
               sa.operation,sa.attempt_id,sa.request_params_json,sa.source_url_without_key,
               sa.collected_at_utc,sa.http_status_code,sa.raw_relative_path,sa.response_bytes,
               sa.sha256 AS response_sha256,sa.parser_version,sa.created_at_utc
        FROM running_trial_rows t
        JOIN api_records ar ON ar.api_record_id=t.api_record_id
        JOIN source_artifacts sa ON sa.source_artifact_id=ar.source_artifact_id
        WHERE t.horse_id IN ({marks}) AND t.meet_code=2 AND t.trial_date<=?
        ORDER BY t.trial_date,t.trial_number,t.horse_number,t.api_record_id
    """
    for batch in chunks(horse_ids):
        sql = sql_template.format(marks=",".join("?" for _ in batch))
        result.extend(rows(conn, sql, tuple(batch) + (max_cutoff,)))
    return result


def add_api20_raw_fields(record: dict[str, Any]) -> dict[str, Any]:
    r = dict(record)
    p = parse_payload(r["payload_json"])
    if sha256_text(r["payload_json"]) != r["payload_sha256"]:
        raise AssertionError(f"payload hash mismatch for API20 record {r['api_record_id']}")
    for key in ("trainDate", "meet", "daySerial", "trainNo", "chulNo", "hrNo", "majong", "rcDist", "rcTime", "ord", "passFlag"):
        present = key in p
        val = p.get(key) if present else None
        r[f"raw_{key}_present"] = present
        r[f"raw_{key}_json_type"] = (
            "absent" if not present else "null" if val is None else "boolean" if isinstance(val, bool)
            else "integer" if isinstance(val, int) else "number" if isinstance(val, float)
            else "string" if isinstance(val, str) else "array" if isinstance(val, list)
            else "object" if isinstance(val, dict) else type(val).__name__
        )
        r[f"raw_{key}"] = val if val is None or isinstance(val, str) else stable_json(val)
    r["raw_trainDate_matches_normalized"] = str(p.get("trainDate", "")) in {
        str(r["trial_date"]).replace("-", ""), str(r["trial_date"])
    }
    r["raw_trainNo_matches_normalized"] = str(p.get("trainNo", "")) == str(r["trial_number"])
    r["explicit_jeju_native"] = (
        r["breed_assessment"] == "api_native_label"
        and r["meet_code"] == 2
        and p.get("meet") == "제주"
        and p.get("majong") == "제주"
    )
    try:
        raw_order = p.get("ord")
        order = int(str(raw_order).strip())
        r["ord_integer_1_89"] = 1 <= order <= 89 and str(raw_order).strip() == str(order)
        r["ord_numeric"] = order if r["ord_integer_1_89"] else None
    except (TypeError, ValueError, OverflowError):
        r["ord_integer_1_89"] = False
        r["ord_numeric"] = None
    try:
        time = float(p.get("rcTime"))
        r["rcTime_finite_positive"] = math.isfinite(time) and time > 0
    except (TypeError, ValueError, OverflowError):
        r["rcTime_finite_positive"] = False
    r["passFlag_known_allowlist"] = p.get("passFlag") in PASS_FLAGS
    r["api20_row_candidate_valid"] = r["explicit_jeju_native"] and r["ord_integer_1_89"] and r["rcTime_finite_positive"] and r["passFlag_known_allowlist"]
    r["participant_natural_key_expected"] = "|".join(str(p.get(k, "")) for k in ("trainDate",)) + "|2|" + "|".join(str(p.get(k, "")) for k in ("trainNo", "chulNo", "hrNo"))
    r["natural_key_matches_expected"] = r["natural_key"] == r["participant_natural_key_expected"]
    return r


def group_interval_parses_full_roster(value: Any, roster_numbers: set[int]) -> bool:
    """Diagnostic only: same conservative roster-complete interval parser as the frozen audit."""
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return False
    text = str(value).replace(" ", "")
    token = r"(?:\(\^?\d+(?:,\^?\d+)*\)|\^?\d+)"
    if not re.fullmatch(token + r"(?:[,=≡\-]+" + token + r")*", text):
        return False
    groups = [list(map(int, re.findall(r"\d+", match.group()))) for match in re.finditer(token, text)]
    flat = [number for group in groups for number in group]
    return bool(flat and len(flat) == len(set(flat)) and set(flat) == roster_numbers)


def build_style_slot_cache(
    selected_slots: pd.DataFrame,
    targets: pd.DataFrame,
    old_cache: pd.DataFrame,
    orders: pd.DataFrame,
    quality: pd.DataFrame,
    uncached_starters: pd.DataFrame,
    point_gate_rows: list[dict[str, Any]],
) -> pd.DataFrame:
    """Build the frozen prepare.py actual-slot schema for this fresh target cohort."""
    cache_lookup = {(int(r.api_record_id), str(r.point)): r._asdict() for r in old_cache.itertuples(index=False)}
    order_lookup = {(int(r.api_record_id), str(r.field_name)): r._asdict() for r in orders.itertuples(index=False)} if len(orders) else {}
    quality_lookup = {int(r.api_record_id): r._asdict() for r in quality.itertuples(index=False)} if len(quality) else {}
    target_lookup = {int(r.api_record_id): r._asdict() for r in targets.itertuples(index=False)}
    started_n = uncached_starters.groupby("race_id").size().astype(int).to_dict() if len(uncached_starters) else {}
    roster_numbers = {
        str(race_id): set(g.horse_number.dropna().astype(int).tolist())
        for race_id, g in uncached_starters.groupby("race_id", sort=False)
    } if len(uncached_starters) else {}
    gate_lookup = {(str(r["race_id"]), str(r["point"])): r for r in point_gate_rows}
    point_specs = [
        ("S1F", "s1f", "sjS1fOrd", "s1f_group", "s1f_group_status"),
        ("4C", "c4", "sj_4cOrd", "c4_group", "c4_group_status"),
        ("G1F", "g1f", "sjG1fOrd", "g1f_group", "g1f_group_status"),
    ]
    out = []
    for slot in selected_slots.sort_values(
        ["target_api_record_id", "same_distance_slot_position_oldest_first"], kind="mergesort"
    ).itertuples(index=False):
        target_id = int(slot.target_api_record_id)
        target = target_lookup[target_id]
        source_id = int(slot.api_record_id)
        source_race = str(slot.race_id)
        source_date = str(slot.race_date)
        target_horse = str(slot.horse_id)
        target_distance = int(target["race_distance_m"])
        source_distance = int(slot.race_distance_m)
        assert target_horse == str(target["horse_id"]) and source_distance == target_distance
        in_old = source_id in old_cache.api_record_id.astype(int).unique()
        source_n = int(cache_lookup[(source_id, "S1F")]["full_started_n"]) if in_old else int(started_n[source_race])
        row: dict[str, Any] = {
            "target_api_record_id": target_id,
            "source_api_record_id": source_id,
            "source_race_id": source_race,
            "source_race_date": source_date,
            "target_cutoff": str(target["history_cutoff"]),
            "target_horse_id": target_horse,
            "target_distance_m": target_distance,
            "slot_oldest_to_newest": int(slot.same_distance_slot_position_oldest_first),
            "source_snapshot_valid_time": bool(slot.valid_time),
            "year": int(source_date[:4]),
            "full_started_n": source_n,
            "slot_position": int(slot.same_distance_slot_position_oldest_first),
            "source_horse_id": str(slot.horse_id),
            "source_distance_m": source_distance,
        }
        for point, prefix, field_name, group_col, status_col in point_specs:
            if in_old:
                cached = cache_lookup.get((source_id, point))
                if cached is None:
                    raise AssertionError(f"old point cache has incomplete point coverage for API4 source {source_id}/{point}")
                value = cached.get("quality_order_value")
                status = cached.get("quality_order_status")
                individual = bool(cached.get("local_rank_ok"))
                perm = bool(cached.get("complete_unique_1_to_n_permutation"))
                group_status = cached.get("api303_group_status")
                group_gate = bool(cached.get("api303_group_status_gate"))
                race_eligible = bool(cached.get("race_point_eligible"))
                rank = cached.get("normalized_rank")
                parsed = bool(cached.get("api303_interval_parse_pass_diagnostic_only"))
            else:
                order_row = order_lookup.get((source_id, field_name))
                qrow = quality_lookup.get(source_id)
                value = order_row.get("quality_order_value") if order_row else None
                status = order_row.get("quality_order_status") if order_row else None
                order_int = None
                if value is not None and not pd.isna(value) and not isinstance(value, bool):
                    try:
                        number = float(value)
                        if math.isfinite(number) and number.is_integer():
                            order_int = int(number)
                    except (TypeError, ValueError, OverflowError):
                        pass
                individual = bool(status in ORDER_OK and source_n >= 2 and order_int is not None and 1 <= order_int <= source_n)
                perm = bool(order_row and order_row.get("api4_full_started_permutation") is True)
                group_status = qrow.get(status_col) if qrow else None
                group_gate = bool(isinstance(group_status, str) and group_status in GROUP_OK)
                gate_row = gate_lookup.get((source_race, point))
                race_eligible = bool(gate_row and gate_row.get("race_point_eligible") is True)
                if gate_row is None:
                    race_eligible = bool(perm and group_gate)
                rank = (order_int - 1) / (source_n - 1) if race_eligible and individual and source_n >= 2 else None
                group_value = qrow.get(group_col) if qrow else None
                parse_status = group_status == "api_group_unreviewed"
                parsed = bool(parse_status and group_interval_parses_full_roster(group_value, roster_numbers.get(source_race, set())))
            if rank is not None and pd.isna(rank):
                rank = None
            final = bool(row["source_snapshot_valid_time"] and race_eligible and rank is not None)
            row[f"{prefix}_order"] = value
            row[f"{prefix}_order_status"] = status
            row[f"{prefix}_r"] = rank if race_eligible and individual else None
            row[f"{prefix}_individual_order_valid"] = bool(individual)
            row[f"{prefix}_full_point_permutation_valid"] = bool(perm)
            row[f"{prefix}_race_point_eligible"] = bool(race_eligible)
            row[f"{prefix}_api303_group_status"] = group_status
            row[f"{prefix}_group_status_gate"] = bool(group_gate)
            row[f"{prefix}_api303_group_status_gate"] = bool(group_gate)
            row[f"{prefix}_group_interval_parse_pass_diagnostic_only"] = bool(parsed)
            row[f"{prefix}_final_point_eligible"] = final
        row["s1f_to_c4_pair_eligible"] = bool(row["s1f_final_point_eligible"] and row["c4_final_point_eligible"])
        row["s1f_to_c4_forward_change"] = (
            float(row["s1f_r"]) - float(row["c4_r"]) if row["s1f_to_c4_pair_eligible"] else None
        )
        row["c4_to_g1f_pair_eligible"] = bool(row["c4_final_point_eligible"] and row["g1f_final_point_eligible"])
        row["c4_to_g1f_forward_change"] = (
            float(row["c4_r"]) - float(row["g1f_r"]) if row["c4_to_g1f_pair_eligible"] else None
        )
        out.append(row)
    columns = [
        "target_api_record_id", "source_api_record_id", "source_race_id", "source_race_date", "target_cutoff",
        "target_horse_id", "target_distance_m", "slot_oldest_to_newest", "source_snapshot_valid_time", "year",
        "full_started_n", "slot_position", "source_horse_id", "source_distance_m",
    ]
    for prefix in ("s1f", "c4", "g1f"):
        columns.extend([
            f"{prefix}_order", f"{prefix}_order_status", f"{prefix}_r",
            f"{prefix}_individual_order_valid", f"{prefix}_full_point_permutation_valid",
            f"{prefix}_race_point_eligible", f"{prefix}_api303_group_status",
            f"{prefix}_group_status_gate", f"{prefix}_api303_group_status_gate",
            f"{prefix}_group_interval_parse_pass_diagnostic_only", f"{prefix}_final_point_eligible",
        ])
    columns.extend(["s1f_to_c4_forward_change", "s1f_to_c4_pair_eligible", "c4_to_g1f_forward_change", "c4_to_g1f_pair_eligible"])
    return pd.DataFrame(out, columns=columns)


def main() -> None:
    if any(OUT.iterdir()):
        raise FileExistsError(f"refusing to run over non-empty output directory: {OUT}")
    old = pd.read_parquet(BASELINE)
    if old.columns.tolist() != FROZEN_COLUMNS or str(old.race_date.max()) != BASELINE_END:
        raise AssertionError("frozen September 19 source snapshot schema/end date differs from contract")
    old["horse_id"] = old.horse_id.astype(str)
    old["api_record_id"] = old.api_record_id.astype("int64")
    old_source_sha = sha256_file(BASELINE)
    old_point_sha = sha256_file(OLD_POINT_CACHE)
    excluded = json.loads(EXCLUSIONS.read_text(encoding="utf-8"))["horses"]
    excluded_ids = {str(k) for k, v in excluded.items() if not v.get("reimport_allowed", False)}

    conn = connect_ro()
    try:
        view_names = [
            "jeju_race_analysis_2026", "jeju_race_postrace_sections_2026",
            "jeju_race_postrace_sections_reviewed_2026", "jeju_race_postrace_sections_quality_2026",
            "jeju_race_section_order_values", "jeju_race_section_order_quality_values",
            "jeju_race_section_group_quality_values",
        ]
        quality_view_definitions = {}
        for name in view_names:
            row = conn.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (name,)).fetchone()
            if row is None or row[0] is None:
                raise AssertionError(f"missing required quality view definition: {name}")
            quality_view_definitions[name] = str(row[0])
        max_source = conn.execute("SELECT MAX(race_date) FROM race_result_rows WHERE meet_code=2").fetchone()[0]
        if str(max_source) != END_DATE:
            raise AssertionError(f"expected source end {END_DATE}, observed {max_source}")
        fresh_records = rows(conn, result_source_query(
            "r.meet_code=2 AND r.race_date>=? AND r.race_date<=?", (START_DATE, END_DATE)
        ), (START_DATE, END_DATE))
        fresh = enrich_race_rows(fresh_records)
        if len(fresh) == 0:
            raise AssertionError("no fresh-period API4 source rows")
        full = rows(conn, """
            SELECT race_date,meet_code,race_number,COUNT(*) AS full_raw_rows
            FROM race_result_rows WHERE meet_code=2 AND race_date>=? AND race_date<=?
            GROUP BY race_date,meet_code,race_number ORDER BY race_date,race_number
        """, (START_DATE, END_DATE))
        full_counts = {f"{r['race_date']}_{r['meet_code']}_{r['race_number']}": int(r["full_raw_rows"]) for r in full}
        eligibility = eligibility_ledger(fresh, full_counts)
        eligible_races = set(eligibility.loc[eligibility.race_included, "race_id"].astype(str))
        targets = fresh.loc[fresh.race_id.isin(eligible_races)].copy()
        if len(targets) == 0 or set(targets.horse_id.dropna().astype(str)) & excluded_ids:
            raise AssertionError("empty target roster or excluded horse reappeared in selected target cohort")
        targets["horse_id"] = targets.horse_id.astype(str)
        targets["history_cutoff"] = targets.race_date.map(lambda x: (date.fromisoformat(str(x)) - timedelta(days=2)).isoformat())
        if targets.duplicated(["api_record_id"]).any():
            raise AssertionError("duplicate target source record id")

        target_ids = sorted(targets.horse_id.unique().tolist())
        max_cutoff = targets.history_cutoff.max()
        history_records: list[dict[str, Any]] = []
        for batch in chunks(target_ids):
            sql = result_source_query(
                f"r.horse_id IN ({','.join('?' for _ in batch)}) AND r.race_date<=?",
                tuple(batch) + (max_cutoff,),
            )
            history_records.extend(rows(conn, sql, tuple(batch) + (max_cutoff,)))
        history_unique = enrich_race_rows(history_records)
        history_unique["horse_id"] = history_unique.horse_id.astype(str)

        # Materialize target-to-history linkage with each exact T-2 boundary.
        link_parts = []
        target_history_rows = []
        old_id_set = set(old.api_record_id.astype("int64"))
        old_by_target = old[old.horse_id.isin(target_ids)].copy()
        old_by_id = old.set_index("api_record_id", drop=False)
        for target in targets.itertuples(index=False):
            h = history_unique.loc[
                history_unique.horse_id.eq(str(target.horse_id))
                & history_unique.race_date.le(str(target.history_cutoff))
            ].copy()
            h["target_api_record_id"] = int(target.api_record_id)
            h["target_race_id"] = str(target.race_id)
            h["target_race_date"] = str(target.race_date)
            h["target_history_cutoff"] = str(target.history_cutoff)
            h["history_source_scope"] = [
                "frozen_sep19_source" if int(api_id) in old_id_set
                else ("post_sep19_warmup" if str(race_date) > BASELINE_END else "pre_sep20_not_in_frozen_source")
                for api_id, race_date in zip(h.get("api_record_id", []), h.get("race_date", []))
            ]
            target_history_rows.extend(h.to_dict("records"))
            link_parts.append(h[["target_api_record_id", "target_race_id", "target_race_date", "target_history_cutoff", "api_record_id", "race_id", "race_date", "horse_id", "started", "valid_time", "history_source_scope"]])

        history_links = pd.concat(link_parts, ignore_index=True) if link_parts else pd.DataFrame()
        history_long = pd.DataFrame(target_history_rows)
        if len(history_long):
            history_long["baseline_snapshot_row"] = history_long.api_record_id.astype("int64").isin(old_id_set)

        # Reconcile every old-source target history row against the preserved snapshot by API identity.
        current_old = history_unique.loc[history_unique.race_date.le(BASELINE_END)].copy()
        old_target = old_by_target.loc[old_by_target.race_date.le(BASELINE_END)].copy()
        old_target_by_id = old_target.drop_duplicates("api_record_id").set_index("api_record_id")
        current_old_target = current_old.loc[current_old.horse_id.isin(target_ids)].drop_duplicates("api_record_id").set_index("api_record_id")
        old_current_id = set(current_old_target.index.astype(int))
        old_snapshot_id = set(old_target_by_id.index.astype(int))
        old_missing_from_current = sorted(old_snapshot_id - old_current_id)
        current_missing_from_snapshot = sorted(old_current_id - old_snapshot_id)
        overlapping = sorted(old_current_id & old_snapshot_id)
        comparable = [c for c in FROZEN_COLUMNS if c != "api_record_id"]
        old_row_diffs = []
        for api_id in overlapping:
            cur = current_old_target.loc[api_id]
            snap = old_target_by_id.loc[api_id]
            diffs = []
            for col in comparable:
                a, b = cur[col], snap[col]
                a_is_null = bool(pd.isna(a))
                b_is_null = bool(pd.isna(b))
                if a_is_null and b_is_null:
                    continue
                # SQLite INTEGER columns and Parquet nullable numeric columns can
                # produce NumPy scalar types (for example np.int64 vs np.float64).
                # Compare their values numerically so representation alone is not
                # recorded as source drift; keep booleans on the exact-value path.
                a_is_bool = isinstance(a, bool) or type(a).__name__ == "bool_"
                b_is_bool = isinstance(b, bool) or type(b).__name__ == "bool_"
                if isinstance(a, numbers.Real) and isinstance(b, numbers.Real) and not a_is_bool and not b_is_bool:
                    if float(a) == float(b):
                        continue
                elif a_is_bool and b_is_bool and bool(a) == bool(b):
                    continue
                elif str(a) == str(b):
                    continue
                diffs.append(col)
            if diffs:
                old_row_diffs.append({"api_record_id": int(api_id), "diff_columns": "|".join(diffs), "horse_id": str(cur.horse_id), "race_date": str(cur.race_date)})
        reconcile_rows = []
        for t in targets.itertuples(index=False):
            hh = history_long.loc[history_long.target_api_record_id.eq(int(t.api_record_id))]
            frozen = hh.loc[hh.history_source_scope.eq("frozen_sep19_source")]
            fresh_warm = hh.loc[hh.history_source_scope.eq("post_sep19_warmup")]
            presep_delta = hh.loc[hh.history_source_scope.eq("pre_sep20_not_in_frozen_source")]
            reconcile_rows.append({
                "target_api_record_id": int(t.api_record_id), "target_race_id": str(t.race_id),
                "target_race_date": str(t.race_date), "history_cutoff": str(t.history_cutoff),
                "horse_id": str(t.horse_id),
                "frozen_source_rows_through_cutoff": int(len(frozen)),
                "frozen_started_n": int(frozen.started.sum()),
                "current_source_old_rows_through_cutoff": int(len(frozen) + len(presep_delta)),
                "current_source_old_started_n": int(frozen.started.sum() + presep_delta.started.sum()),
                "post_sep19_warmup_rows_through_cutoff": int(len(fresh_warm)),
                "post_sep19_warmup_started_n": int(fresh_warm.started.sum()),
                "pre_sep20_scope_delta_rows": int(len(presep_delta)),
                "pre_sep20_scope_delta_started_n": int(presep_delta.started.sum()),
                "all_current_started_n_through_cutoff": int(hh.started.sum()),
                "cold_under_frozen_snapshot": bool(frozen.started.sum() == 0),
                "cold_under_current_native_rows": bool(hh.started.sum() == 0),
            })
        target_reconciliation = pd.DataFrame(reconcile_rows)
        cold_targets = targets.merge(
            target_reconciliation[["target_api_record_id", "frozen_started_n", "current_source_old_started_n", "post_sep19_warmup_started_n", "pre_sep20_scope_delta_started_n", "all_current_started_n_through_cutoff", "cold_under_frozen_snapshot", "cold_under_current_native_rows"]],
            left_on="api_record_id", right_on="target_api_record_id", how="left", validate="one_to_one",
        )
        cold_targets = cold_targets.loc[cold_targets.cold_under_current_native_rows].copy()
        if set(cold_targets.horse_id.astype(str)) & {"3005648"}:
            raise AssertionError("excluded horse 3005648 reappeared in cold target cohort")

        # Select exact last-five same-distance started slots before consulting the
        # frozen style cache. A slot absent from that cache is never treated as NULL:
        # its complete source-race starter roster is quality-queried below.
        old_point_cache = pd.read_parquet(OLD_POINT_CACHE)
        old_point_ids = set(old_point_cache.api_record_id.astype(int).unique().tolist())
        slot_records = []
        for target in targets.itertuples(index=False):
            hh = history_long.loc[
                history_long.target_api_record_id.eq(int(target.api_record_id))
                & history_long.started
                & pd.to_numeric(history_long.race_distance_m, errors="coerce").eq(float(target.race_distance_m))
            ].sort_values(["race_date", "meet_code", "race_number", "horse_number", "api_record_id"], kind="mergesort")
            selected = hh.tail(5).copy()
            selected = selected.iloc[::-1].reset_index(drop=True)
            for rank, row in enumerate(selected.to_dict("records"), start=1):
                row["same_distance_slot_rank_latest_first"] = rank
                row["same_distance_slot_position_oldest_first"] = len(selected) - rank + 1
                row["slot_source_in_frozen_point_cache"] = int(row["api_record_id"]) in old_point_ids
                row["slot_requires_fullroster_quality_query"] = int(row["api_record_id"]) not in old_point_ids
                row["slot_source_valid_time"] = bool(row["valid_time"])
                slot_records.append(row)
        selected_slots = pd.DataFrame(slot_records)
        if len(selected_slots):
            selected_slots["source_point_cache_scope"] = selected_slots.slot_source_in_frozen_point_cache.map({True: "frozen_old_full_point_cache", False: "query_full_source_race_quality"})
        uncached_slot_ids = set(selected_slots.loc[~selected_slots.slot_source_in_frozen_point_cache, "api_record_id"].astype(int)) if len(selected_slots) else set()
        uncached_race_ids = set(selected_slots.loc[~selected_slots.slot_source_in_frozen_point_cache, "race_id"].astype(str)) if len(selected_slots) else set()
        uncached_keys = sorted({
            (str(r.race_date), int(r.meet_code), int(r.race_number))
            for r in selected_slots.loc[~selected_slots.slot_source_in_frozen_point_cache].itertuples(index=False)
        }) if len(selected_slots) else []
        uncached_full_records = []
        for batch_start in range(0, len(uncached_keys), 200):
            batch = uncached_keys[batch_start:batch_start+200]
            val_sql = ",".join("(?,?,?)" for _ in batch)
            params = tuple(x for key in batch for x in key)
            uncached_full_records.extend(rows(conn, f"""
                WITH wanted(race_date,meet_code,race_number) AS (VALUES {val_sql})
                SELECT r.api_record_id,r.race_date,r.meet_code,r.race_number,r.horse_number,
                       r.horse_id,r.horse_name,r.race_distance_m,r.rank_class_raw,r.race_name_raw,
                       r.finish_position,r.finish_status_raw,r.finish_time_seconds,r.carried_weight_kg,
                       r.body_weight_raw,r.jockey_id,r.jockey_name,r.trainer_id,r.trainer_name,
                       r.owner_id,r.owner_name,r.track_raw,r.weather_raw,r.breed_label_raw,
                       r.breed_assessment,r.breed_assessment_note,ar.record_index,ar.record_type,
                       ar.natural_key,ar.payload_json,ar.payload_sha256,ar.source_artifact_id,
                       sa.source_family,sa.source_role,sa.public_dataset_id,sa.dataset_name,sa.endpoint,
                       sa.operation,sa.attempt_id,sa.request_params_json,sa.source_url_without_key,
                       sa.collected_at_utc,sa.http_status_code,sa.raw_relative_path,sa.response_bytes,
                       sa.sha256 AS response_sha256,sa.parser_version,sa.created_at_utc
                FROM wanted w JOIN race_result_rows r
                  ON (r.race_date,r.meet_code,r.race_number)=(w.race_date,w.meet_code,w.race_number)
                JOIN api_records ar ON ar.api_record_id=r.api_record_id
                JOIN source_artifacts sa ON sa.source_artifact_id=ar.source_artifact_id
                ORDER BY r.race_date,r.meet_code,r.race_number,r.horse_number,r.api_record_id
            """, params))
        uncached_full = enrich_race_rows(uncached_full_records)
        uncached_full["frozen_source_snapshot_row"] = uncached_full.api_record_id.astype(int).isin(old_id_set)
        uncached_starters = uncached_full.loc[uncached_full.started].copy()
        for race_id, group in uncached_full.groupby("race_id", sort=False):
            if str(race_id) in uncached_race_ids:
                full_ids = set(group.loc[group.started, "api_record_id"].astype(int))
                frozen_ids = set(old.loc[old.api_record_id.astype(int).isin(full_ids), "api_record_id"].astype(int))
                if str(group.race_date.iloc[0]) <= BASELINE_END and full_ids != frozen_ids:
                    raise AssertionError(f"uncached historical race {race_id} full started roster differs from frozen snapshot")
        # API4 status snapshots cover the full started roster of each race containing
        # any missing selected source ID, including pre-Sep20 source races.
        source_api_ids = sorted(uncached_starters.api_record_id.astype(int).unique().tolist())
        order_rows: list[dict[str, Any]] = []
        for batch in [source_api_ids[i:i+3500] for i in range(0, len(source_api_ids), 3500)]:
            if not batch:
                continue
            marks = ",".join("?" for _ in batch)
            fields = list(ORDER_FIELDS.values())
            field_marks = ",".join("?" for _ in fields)
            order_rows.extend(rows(conn, f"""
                SELECT api_record_id,race_date,meet_code,race_number,horse_number,horse_id,
                       field_name,api_order_raw,api_order_json_type,api_payload_sha256,
                       api_source_artifact_id,api_source_page_sha256,api_source_page_path,
                       quality_order_value,quality_order_status,review_status,api_order_at_review,
                       website_order,effective_order,website_url,checked_date_kst,
                       evidence_relative_path,evidence_sha256,reason,applied_at,
                       conflict_evidence_path,conflict_evidence_sha256
                FROM jeju_race_section_order_quality_values
                WHERE api_record_id IN ({marks}) AND field_name IN ({field_marks})
                ORDER BY race_date,meet_code,race_number,horse_number,field_name
            """, tuple(batch) + tuple(fields)))
        orders = pd.DataFrame(order_rows)
        if len(orders):
            orders["race_id"] = orders.apply(lambda r: f"{r.race_date}_{int(r.meet_code)}_{int(r.race_number)}", axis=1)
            orders["full_roster_n"] = orders.race_id.map(uncached_starters.groupby("race_id").size()).astype("Int64")
            orders["accepted_status"] = orders.quality_order_status.isin(ORDER_OK)
            def int_order(v: Any) -> int | None:
                if v is None or pd.isna(v) or isinstance(v, bool): return None
                try:
                    f = float(v)
                    return int(f) if math.isfinite(f) and f.is_integer() else None
                except (TypeError, ValueError, OverflowError): return None
            orders["order_int"] = orders.quality_order_value.map(int_order)
            orders["order_individual_valid"] = orders.accepted_status & orders.order_int.notna() & orders.full_roster_n.ge(2) & orders.order_int.ge(1) & orders.order_int.le(orders.full_roster_n)
            perm_flags = []
            for (race_id, field), g in orders.groupby(["race_id", "field_name"], sort=True):
                ids = set(uncached_starters.loc[uncached_starters.race_id.eq(race_id), "api_record_id"].astype(int))
                got_ids = set(g.api_record_id.astype(int))
                n = len(ids)
                vals = g.order_int.dropna().astype(int).tolist()
                ok = got_ids == ids and len(g) == n and g.accepted_status.all() and len(vals) == n and sorted(vals) == list(range(1, n + 1))
                perm_flags.append({"race_id": race_id, "field_name": field, "api4_full_started_permutation": bool(ok), "quality_rows": int(len(g)), "started_roster_n": int(n)})
            perm = pd.DataFrame(perm_flags)
            orders = orders.merge(perm, on=["race_id", "field_name"], how="left", validate="many_to_one")

        quality_rows = []
        race_keys = uncached_keys
        if race_keys:
            qview = "jeju_race_postrace_sections_quality_2026"
            for batch_start in range(0, len(race_keys), 200):
                batch = race_keys[batch_start:batch_start+200]
                val_sql = ",".join("(?,?,?)" for _ in batch)
                params = tuple(x for key in batch for x in key)
                quality_rows.extend(rows(conn, f"""
                    WITH wanted(race_date,meet_code,race_number) AS (VALUES {val_sql})
                    SELECT q.api_record_id,q.race_date,q.meet_code,q.race_number,q.horse_number,
                           q.horse_id,q.race_distance_m,q.rank_class_raw,q.finish_position,
                           q.api4_3_payload_sha256,q.api4_3_source_artifact_id,q.api4_3_source_page_sha256,
                           q.api4_3_source_page_path,q.api303_api_record_id,q.api303_payload_sha256,
                           q.api303_source_artifact_id,q.api303_source_page_sha256,q.api303_source_page_path,
                           q.s1f_order,q.s1f_order_status,q.s1f_group,q.s1f_group_status,
                           q.c4_order,q.c4_order_status,q.c4_group,q.c4_group_status,
                           q.g1f_order,q.g1f_order_status,q.g1f_group,q.g1f_group_status
                    FROM {qview} q JOIN wanted w
                      ON (q.race_date,q.meet_code,q.race_number)=(w.race_date,w.meet_code,w.race_number)
                    ORDER BY q.race_date,q.race_number,q.horse_number,q.api_record_id
                """, params))
        quality = pd.DataFrame(quality_rows)
        point_gate_rows = []
        if len(quality):
            quality["race_id"] = quality.apply(lambda r: f"{r.race_date}_{int(r.meet_code)}_{int(r.race_number)}", axis=1)
            quality["full_started_row"] = quality.api_record_id.astype(int).isin(set(uncached_starters.api_record_id.astype(int)))
            for point in ("s1f", "c4", "g1f"):
                quality[f"{point}_group_status_allowed"] = quality[f"{point}_group_status"].isin(GROUP_OK)
                quality[f"{point}_order_status_allowed"] = quality[f"{point}_order_status"].isin(ORDER_OK)
            point_name_to_field = {"s1f": "sjS1fOrd", "c4": "sj_4cOrd", "g1f": "sjG1fOrd"}
            for race_id in sorted(uncached_race_ids):
                for point, field_name in point_name_to_field.items():
                    roster = uncached_starters.loc[uncached_starters.race_id.eq(race_id)]
                    q = quality.loc[quality.race_id.eq(race_id) & quality.full_started_row]
                    group_col = f"{point}_group_status"
                    group_rows = q[["api_record_id", "horse_id", group_col]].copy()
                    ids = set(roster.api_record_id.astype(int))
                    qids = set(group_rows.api_record_id.astype(int))
                    statuses = group_rows[group_col]
                    group_ok = (
                        qids == ids and len(group_rows) == len(roster)
                        and len(statuses) == len(roster) and statuses.notna().all()
                        and statuses.isin(GROUP_OK).all()
                    )
                    order_perm_row = None
                    if len(orders):
                        candidate = orders.loc[orders.race_id.eq(race_id) & orders.field_name.eq(field_name)]
                        if len(candidate):
                            order_perm_row = bool(candidate.api4_full_started_permutation.iloc[0])
                    point_gate_rows.append({
                        "race_id": race_id, "point": {"s1f": "S1F", "c4": "4C", "g1f": "G1F"}[point],
                        "api4_field_name": field_name, "started_roster_n": int(len(roster)),
                        "api4_quality_rows_n": int(len(orders.loc[orders.race_id.eq(race_id) & orders.field_name.eq(field_name)])) if len(orders) else 0,
                        "api4_full_started_permutation": order_perm_row,
                        "api303_status_rows_n": int(len(group_rows)),
                        "api303_status_values": "|".join(sorted({str(x) for x in statuses.dropna().tolist()})),
                        "api303_full_roster_status_gate": bool(group_ok),
                        "race_point_eligible": bool(order_perm_row is True and group_ok),
                    })

        # API20 source rows linked only to the actual cold target IDs; peer rows remain full explicit-Jeju event rosters.
        cold_ids = sorted(cold_targets.horse_id.astype(str).unique().tolist())
        cold_cutoff = dict(zip(cold_targets.horse_id.astype(str), cold_targets.history_cutoff.astype(str)))
        cold_trial_source = api20_rows_for_horses(conn, cold_ids, max(cold_cutoff.values())) if cold_ids else []
        cold_trial_all = [add_api20_raw_fields(r) for r in cold_trial_source]
        cold_trial_link = []
        for r in cold_trial_all:
            cutoff = cold_cutoff.get(str(r["horse_id"]))
            if cutoff and str(r["trial_date"]) <= cutoff and r["explicit_jeju_native"]:
                row = dict(r)
                row["target_history_cutoff"] = cutoff
                tr = cold_targets.loc[cold_targets.horse_id.astype(str).eq(str(r["horse_id"]))].iloc[0]
                row["target_api_record_id"] = int(tr.api_record_id)
                row["target_race_id"] = str(tr.race_id)
                cold_trial_link.append(row)
        event_keys = sorted({(str(r["trial_date"]), int(r["meet_code"]), int(r["trial_number"])) for r in cold_trial_link})
        peer_rows = []
        for batch_start in range(0, len(event_keys), 120):
            batch = event_keys[batch_start:batch_start+120]
            val_sql = ",".join("(?,?,?)" for _ in batch)
            params = tuple(x for key in batch for x in key)
            raw_peers = rows(conn, f"""
                WITH wanted(trial_date,meet_code,trial_number) AS (VALUES {val_sql})
                SELECT t.api_record_id,t.trial_date,t.meet_code,t.trial_number,t.horse_number,
                       t.horse_id,t.horse_name,t.finish_position,t.finish_status_raw,t.finish_time_seconds,
                       t.body_weight_kg,t.carried_weight_base_kg,t.jockey_overweight_kg,t.jockey_id,
                       t.jockey_name,t.trainer_id,t.trainer_name,t.pass_flag_raw,t.failure_reason_raw,
                       t.inspection_reason_raw,t.section_times_json,t.breed_label_raw,
                       t.breed_assessment,t.breed_assessment_note,ar.record_index,ar.record_type,
                       ar.natural_key,ar.payload_json,ar.payload_sha256,ar.source_artifact_id,
                       sa.source_family,sa.source_role,sa.public_dataset_id,sa.dataset_name,sa.endpoint,
                       sa.operation,sa.attempt_id,sa.request_params_json,sa.source_url_without_key,
                       sa.collected_at_utc,sa.http_status_code,sa.raw_relative_path,sa.response_bytes,
                       sa.sha256 AS response_sha256,sa.parser_version,sa.created_at_utc
                FROM wanted w JOIN running_trial_rows t
                  ON (t.trial_date,t.meet_code,t.trial_number)=(w.trial_date,w.meet_code,w.trial_number)
                JOIN api_records ar ON ar.api_record_id=t.api_record_id
                JOIN source_artifacts sa ON sa.source_artifact_id=ar.source_artifact_id
                WHERE t.meet_code=2 AND t.breed_assessment='api_native_label'
                ORDER BY t.trial_date,t.meet_code,t.trial_number,t.horse_number,t.api_record_id
            """, params)
            peer_rows.extend(add_api20_raw_fields(r) for r in raw_peers)
        peer_events: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
        for r in peer_rows:
            if r["explicit_jeju_native"]:
                peer_events[(str(r["trial_date"]), int(r["meet_code"]), int(r["trial_number"]))].append(r)
        event_summary: dict[tuple[str, int, int], dict[str, Any]] = {}
        for key, event_roster in peer_events.items():
            days = [x.get("raw_daySerial") for x in event_roster]
            unique_horse = len({str(x["horse_id"]) for x in event_roster}) == len(event_roster)
            unique_natural = len({str(x["natural_key"]) for x in event_roster}) == len(event_roster)
            event_summary[key] = {
                "event_explicit_jeju_roster_n": len(event_roster),
                "event_daySerial_invariant": bool(event_roster and all(x == days[0] for x in days)),
                "event_unique_horse_ids": unique_horse,
                "event_unique_natural_keys": unique_natural,
                "event_eligible_peer_count": sum(bool(x["api20_row_candidate_valid"]) for x in event_roster),
            }
            event_summary[key]["event_key_valid_for_candidate"] = (
                len(event_roster) >= 3
                and all(x["raw_trainDate_matches_normalized"] and x["raw_trainNo_matches_normalized"] for x in event_roster)
                and event_summary[key]["event_daySerial_invariant"]
                and unique_horse and unique_natural
            )
        for r in peer_rows:
            r["normalized_event_key"] = f"{r['trial_date']}_{r['meet_code']}_{r['trial_number']}"
            key = (str(r["trial_date"]), int(r["meet_code"]), int(r["trial_number"]))
            r.update(event_summary.get(key, {
                "event_explicit_jeju_roster_n": 0,
                "event_daySerial_invariant": False,
                "event_unique_horse_ids": False,
                "event_unique_natural_keys": False,
                "event_eligible_peer_count": 0,
                "event_key_valid_for_candidate": False,
            }))
        trial_lineage = []
        for horse_id, group in pd.DataFrame(cold_trial_link).groupby("horse_id", sort=True) if cold_trial_link else []:
            ordered = group.sort_values(["trial_date", "trial_number", "api_record_id"], ascending=[False, False, False]).copy()
            for rank, row in enumerate(ordered.to_dict("records"), start=1):
                row["registered_event_record_rank_latest_first"] = rank
                row["is_latest3_registered_record"] = rank <= 3
                trial_lineage.append(row)

        # Artifact inventory includes every source artifact represented in the row-level bundle.
        all_source_records = fresh_records + history_records + cold_trial_source
        if peer_rows:
            all_source_records += peer_rows
        artifact_by_id: dict[int, dict[str, Any]] = {}
        for r in all_source_records:
            artifact_by_id[int(r["source_artifact_id"])] = {
                "source_artifact_id": int(r["source_artifact_id"]),
                **{k: r.get(k) for k in (
                    "source_family", "source_role", "public_dataset_id", "dataset_name", "endpoint",
                    "operation", "attempt_id", "request_params_json", "source_url_without_key",
                    "collected_at_utc", "http_status_code", "raw_relative_path", "response_bytes",
                    "response_sha256", "parser_version", "created_at_utc",
                )},
            }
        quality_artifact_ids = sorted({
            int(r["api303_source_artifact_id"])
            for r in quality_rows if r.get("api303_source_artifact_id") is not None
        })
        if quality_artifact_ids:
            for batch_start in range(0, len(quality_artifact_ids), 800):
                batch = quality_artifact_ids[batch_start:batch_start+800]
                for r in rows(conn, f"""
                    SELECT source_artifact_id,source_family,source_role,public_dataset_id,dataset_name,
                           endpoint,operation,attempt_id,request_params_json,source_url_without_key,
                           collected_at_utc,http_status_code,raw_relative_path,response_bytes,
                           sha256 AS response_sha256,parser_version,created_at_utc
                    FROM source_artifacts WHERE source_artifact_id IN ({','.join('?' for _ in batch)})
                """, tuple(batch)):
                    artifact_by_id[int(r["source_artifact_id"])] = r

        # Capture scoped source rows and per-row fingerprints within this single RO snapshot.
        snapshot_rows = {
            "fresh_api4": fresh_records,
            "target_history_api4": history_records,
            "cold_api20_target_rows": cold_trial_source,
            "cold_api20_full_peer_rows": peer_rows,
            "fresh_history_order_quality": order_rows,
            "fresh_history_quality_contract_view": quality_rows,
        }
        snapshot_fingerprints = {
            name: fingerprint(source_projection(value)) if name in {
                "fresh_api4", "target_history_api4", "cold_api20_target_rows", "cold_api20_full_peer_rows"
            } else fingerprint(value)
            for name, value in snapshot_rows.items()
        }
        snapshot_counts = {name: len(value) for name, value in snapshot_rows.items()}
    finally:
        conn.rollback()
        conn.close()

    # Reopen a second RO snapshot after extraction and compare exact scoped row sources.
    # Queries are intentionally restricted to selected row IDs/event keys, not a DB-wide digest.
    conn2 = connect_ro()
    try:
        quality_view_definitions_after = {}
        for name in view_names:
            row = conn2.execute("SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (name,)).fetchone()
            quality_view_definitions_after[name] = str(row[0]) if row and row[0] else None
        ids_fresh = sorted(set(int(x) for x in fresh.api_record_id.tolist()))
        ids_hist = sorted(set(int(x) for x in history_unique.api_record_id.tolist()))
        ids_trial = sorted(set(int(x["api_record_id"]) for x in cold_trial_source))
        keys_trial = event_keys
        def source_by_ids(ids: list[int]) -> list[dict[str, Any]]:
            if not ids: return []
            out = []
            for start in range(0, len(ids), 800):
                batch = ids[start:start+800]
                out.extend(rows(conn2, f"""
                    SELECT a.api_record_id,a.source_artifact_id,a.record_index,a.record_type,a.natural_key,
                           a.payload_json,a.payload_sha256,sa.source_family,sa.source_role,
                           sa.public_dataset_id,sa.dataset_name,sa.endpoint,sa.operation,sa.attempt_id,
                           sa.request_params_json,sa.source_url_without_key,sa.collected_at_utc,
                           sa.http_status_code,sa.raw_relative_path,sa.response_bytes,
                           sa.sha256 AS response_sha256,sa.parser_version,sa.created_at_utc
                    FROM api_records a JOIN source_artifacts sa USING(source_artifact_id)
                    WHERE a.api_record_id IN ({','.join('?' for _ in batch)}) ORDER BY a.api_record_id
                """, tuple(batch)))
            return out
        # Requery same source identities with the same immutable payload/artifact columns.
        ids_peer = sorted({int(r["api_record_id"]) for r in peer_rows})
        raw_after = {
            "fresh_api4": source_by_ids(ids_fresh),
            "target_history_api4": source_by_ids(ids_hist),
            "cold_api20_target_rows": source_by_ids(ids_trial),
            "cold_api20_full_peer_rows": source_by_ids(ids_peer),
        }
        after_hashes = {k: fingerprint(v) for k, v in raw_after.items()}
        # Quality values and API303 joined status rows are re-read on the new snapshot too.
        order_after = []
        for start in range(0, len(source_api_ids), 3500):
            batch = source_api_ids[start:start+3500]
            if not batch: continue
            fields = list(ORDER_FIELDS.values())
            order_after.extend(rows(conn2, f"""
                SELECT api_record_id,race_date,meet_code,race_number,horse_number,horse_id,
                       field_name,api_order_raw,api_order_json_type,api_payload_sha256,
                       api_source_artifact_id,api_source_page_sha256,api_source_page_path,
                       quality_order_value,quality_order_status,review_status,api_order_at_review,
                       website_order,effective_order,website_url,checked_date_kst,
                       evidence_relative_path,evidence_sha256,reason,applied_at,
                       conflict_evidence_path,conflict_evidence_sha256
                FROM jeju_race_section_order_quality_values
                WHERE api_record_id IN ({','.join('?' for _ in batch)})
                  AND field_name IN ({','.join('?' for _ in fields)})
                ORDER BY race_date,meet_code,race_number,horse_number,field_name
            """, tuple(batch) + tuple(fields)))
        quality_after = []
        for start in range(0, len(uncached_keys), 200):
            batch = uncached_keys[start:start+200]
            if not batch: continue
            val_sql = ",".join("(?,?,?)" for _ in batch)
            params = tuple(x for key in batch for x in key)
            quality_after.extend(rows(conn2, f"""
                WITH wanted(race_date,meet_code,race_number) AS (VALUES {val_sql})
                SELECT q.api_record_id,q.race_date,q.meet_code,q.race_number,q.horse_number,
                       q.horse_id,q.race_distance_m,q.rank_class_raw,q.finish_position,
                       q.api4_3_payload_sha256,q.api4_3_source_artifact_id,q.api4_3_source_page_sha256,
                       q.api4_3_source_page_path,q.api303_api_record_id,q.api303_payload_sha256,
                       q.api303_source_artifact_id,q.api303_source_page_sha256,q.api303_source_page_path,
                       q.s1f_order,q.s1f_order_status,q.s1f_group,q.s1f_group_status,
                       q.c4_order,q.c4_order_status,q.c4_group,q.c4_group_status,
                       q.g1f_order,q.g1f_order_status,q.g1f_group,q.g1f_group_status
                FROM jeju_race_postrace_sections_quality_2026 q JOIN wanted w
                  ON (q.race_date,q.meet_code,q.race_number)=(w.race_date,w.meet_code,w.race_number)
                ORDER BY q.race_date,q.race_number,q.horse_number,q.api_record_id
            """, params))
        after_hashes["fresh_history_order_quality"] = fingerprint(order_after)
        after_hashes["fresh_history_quality_contract_view"] = fingerprint(quality_after)
    finally:
        conn2.rollback()
        conn2.close()

    before_lineage_hashes = {
        "fresh_api4": fingerprint(source_projection(fresh_records)),
        "target_history_api4": fingerprint(source_projection(history_records)),
        "cold_api20_target_rows": fingerprint(source_projection(cold_trial_source)),
        "cold_api20_full_peer_rows": fingerprint(source_projection(peer_rows)),
    }
    if any(after_hashes.get(k) != v for k, v in before_lineage_hashes.items()):
        raise AssertionError("scoped raw API payload/artifact lineage changed across RO snapshots")
    if after_hashes.get("fresh_history_order_quality") != snapshot_fingerprints.get("fresh_history_order_quality"):
        raise AssertionError("scoped API4 point quality values changed across RO snapshots")
    if after_hashes.get("fresh_history_quality_contract_view") != snapshot_fingerprints.get("fresh_history_quality_contract_view"):
        raise AssertionError("scoped API303 group/status quality view changed across RO snapshots")
    if sha256_file(BASELINE) != old_source_sha or sha256_file(OLD_POINT_CACHE) != old_point_sha:
        raise AssertionError("frozen source/cache file changed while reading")
    if quality_view_definitions_after != quality_view_definitions:
        raise AssertionError("selected source quality view definitions changed across RO snapshots")
    if set(fresh.api_record_id.astype(int)) & set(old.api_record_id.astype(int)):
        raise AssertionError("fresh period API4 record ID overlaps frozen snapshot")
    if current_missing_from_snapshot or old_missing_from_current or old_row_diffs:
        # Preserve this explicit scope warning in outputs; do not silently relabel these rows cold.
        pass

    # Write row-level source bundle; it is frozen once the manifest is written.
    target_columns = FROZEN_COLUMNS + [
        "history_cutoff", "race_included", "eligibility_reason", "baseline_horse_id_seen",
        "frozen_started_n", "current_source_old_started_n", "post_sep19_warmup_started_n",
        "pre_sep20_scope_delta_started_n", "all_current_started_n_through_cutoff",
        "cold_under_frozen_snapshot", "cold_under_current_native_rows",
        "source_artifact_id", "record_index", "record_type", "natural_key", "payload_json",
        "payload_sha256", "source_family", "source_role", "endpoint", "operation",
        "attempt_id", "request_params_json", "source_url_without_key", "collected_at_utc",
        "http_status_code", "raw_relative_path", "response_bytes", "response_sha256",
        "breed_assessment", "breed_assessment_note", "race_full_raw_rows", "full_raw_roster_match",
    ]
    race_meta = eligibility[["race_id", "race_included", "eligibility_reason", "full_raw_rows"]].rename(columns={"full_raw_rows": "race_full_raw_rows"})
    target_out = targets.merge(race_meta, on="race_id", how="left", validate="many_to_one")
    target_out["full_raw_roster_match"] = target_out.apply(lambda r: len(fresh.loc[fresh.race_id.eq(r.race_id)]) == int(r.race_full_raw_rows), axis=1)
    target_out = target_out.merge(target_reconciliation[["target_api_record_id", "frozen_started_n", "current_source_old_started_n", "post_sep19_warmup_started_n", "pre_sep20_scope_delta_started_n", "all_current_started_n_through_cutoff", "cold_under_frozen_snapshot", "cold_under_current_native_rows"]], left_on="api_record_id", right_on="target_api_record_id", how="left", validate="one_to_one")
    target_out["baseline_horse_id_seen"] = target_out.horse_id.isin(set(old.horse_id.astype(str)))
    target_out = target_out[[c for c in target_columns if c in target_out.columns]]

    actual_slot_cache = build_style_slot_cache(
        selected_slots, targets, old_point_cache, orders, quality, uncached_starters, point_gate_rows,
    )
    fresh_history_source_rows = history_unique.loc[
        history_unique.race_date.gt(BASELINE_END), FROZEN_COLUMNS
    ].drop_duplicates("api_record_id").sort_values("api_record_id", kind="mergesort")
    if len(actual_slot_cache):
        if actual_slot_cache.duplicated(["target_api_record_id", "slot_oldest_to_newest"]).any():
            raise AssertionError("duplicate target/style-history actual slot")
        for target_id, group in actual_slot_cache.groupby("target_api_record_id", sort=False):
            ordered = group.sort_values("slot_oldest_to_newest", kind="stable")
            if ordered.slot_oldest_to_newest.astype(int).tolist() != list(range(1, len(ordered) + 1)):
                raise AssertionError(f"non-contiguous actual style slot positions for {target_id}")
            if len(ordered) > 5:
                raise AssertionError(f"more than five style-history slots for {target_id}")

    write_frame(OUT / "fresh_raw_race_rows.parquet", fresh)
    write_frame(OUT / "race_eligibility_ledger.parquet", eligibility)
    write_frame(OUT / "eligible_target_roster.parquet", target_out)
    write_frame(OUT / "cold_target_roster.parquet", cold_targets)
    write_frame(OUT / "target_history_through_tminus2.parquet", history_long)
    write_frame(OUT / "target_history_reconciliation.parquet", target_reconciliation)
    write_frame(OUT / "fresh_history_source_rows_20col.parquet", fresh_history_source_rows)
    write_frame(OUT / "fresh_target_last5_same_distance_slots.parquet", selected_slots)
    write_frame(OUT / "selected_history_missingcache_full_race_rows.parquet", uncached_full)
    write_frame(OUT / "selected_history_missingcache_full_started_rosters.parquet", uncached_starters)
    write_frame(OUT / "api4_selected_point_quality.parquet", orders)
    write_frame(OUT / "api303_group_status_by_starter.parquet", quality)
    write_frame(OUT / "style6_source_point_gate_audit.parquet", pd.DataFrame(point_gate_rows))
    write_frame(OUT / "actual_slot_point_eligibility_fresh_targets.parquet", actual_slot_cache)
    write_frame(OUT / "api20_cold_target_trial_rows.parquet", pd.DataFrame(trial_lineage))
    write_frame(OUT / "api20_linked_full_peer_event_rows.parquet", pd.DataFrame(peer_rows))
    write_frame(OUT / "api20_target_trial_source_rows_all.parquet", pd.DataFrame(cold_trial_all))
    write_json(OUT / "source_artifacts.json", sorted(artifact_by_id.values(), key=lambda x: x["source_artifact_id"]))
    write_json(OUT / "quality_view_definitions.json", quality_view_definitions)
    write_frame(OUT / "presep20_source_scope_diffs.parquet", pd.DataFrame(old_row_diffs, columns=["api_record_id", "diff_columns", "horse_id", "race_date"]))
    write_json(OUT / "source_scope_id_reconciliation.json", {
        "current_old_rows_missing_from_frozen_snapshot_n": len(current_missing_from_snapshot),
        "frozen_snapshot_old_rows_missing_from_current_db_n": len(old_missing_from_current),
        "old_row_field_differences_n": len(old_row_diffs),
        "current_old_missing_api_record_ids": current_missing_from_snapshot,
        "frozen_old_missing_api_record_ids": old_missing_from_current,
        "interpretation": "Pre-Sep20 current rows absent from the frozen Sep19 snapshot are preserved as explicit scope deltas and cannot silently count as cold history. Post-Sep19 records are warm-up history, not old-source drift.",
    })

    # Required population and provenance checks; these are source counts, not prediction metrics.
    date_counts = eligibility.loc[eligibility.race_included].groupby("race_date").agg(races=("race_id", "size"), rows=("candidate_rows", "sum")).reset_index().to_dict("records")
    cold_by_date = cold_targets.groupby("race_date").agg(runners=("api_record_id", "size"), horses=("horse_id", "nunique")).reset_index().to_dict("records")
    if len(fresh) != 464 or len(eligibility) != 49 or len(targets) != 426 or targets.race_id.nunique() != 45:
        raise AssertionError(f"unexpected population counts rows={len(fresh)},races={len(eligibility)},eligible={len(targets)},eligible_races={targets.race_id.nunique()}")
    if current_missing_from_snapshot or old_missing_from_current or old_row_diffs:
        # Not a fatal source failure, but surfaced and requires root disposition before performance claims.
        old_reconciliation_clean = False
    else:
        old_reconciliation_clean = True
    if len(cold_targets) != 14 or cold_targets.horse_id.nunique() != 14:
        raise AssertionError(f"expected 14 current-source cold rows/IDs; got {len(cold_targets)}/{cold_targets.horse_id.nunique()}")

    output_hashes = {p.name: sha256_file(p) for p in sorted(OUT.iterdir()) if p.is_file()}
    manifest = {
        "audit_name": "fresh_period_source_freeze_v1",
        "source_period": {"requested_start": START_DATE, "requested_end": END_DATE, "observed_raw_dates": sorted(fresh.race_date.unique().tolist()), "latest_raw_race_date": str(fresh.race_date.max()), "baseline_cutoff": BASELINE_END},
        "snapshot_contract": {"sqlite_mode": "mode=ro", "query_only": True, "explicit_transaction": True, "whole_database_hash_used": False, "database_path": str(DB), "cutoff": "target race date minus two calendar days, inclusive; event/public-availability timestamp not established"},
        "frozen_inputs": {"baseline_source_snapshot": str(BASELINE.relative_to(ROOT)), "baseline_source_snapshot_sha256": old_source_sha, "baseline_rows": int(len(old)), "baseline_schema": FROZEN_COLUMNS, "baseline_max_race_date": str(old.race_date.max()), "old_full_point_cache": str(OLD_POINT_CACHE.relative_to(ROOT)), "old_full_point_cache_sha256": old_point_sha},
        "target_population_contract": {"distances_m": sorted(DISTANCES), "n_min": 6, "all_normal_positive_finish_time": True, "ranks_exact_1_to_N": True, "full_raw_roster_required": True, "unique_horse_ids_and_positive_unique_horse_numbers": True, "constant_distance_and_raw_grade": True, "history_started_codes": "1..89 or 91/92", "valid_time": "finish position 1..89 and finite positive full race time"},
        "api4_point_contract": {"fields": ORDER_FIELDS, "accepted_individual_statuses": sorted(ORDER_OK), "api303_accepted_group_statuses": sorted(GROUP_OK), "point_gate": "full started API4 roster exact integer 1..N permutation and explicit API303 status allowlist; absent/NULL/unknown fails closed", "fresh_history_point_rows_only": False, "missing_frozen_cache_rule": "for every actual last-five same-distance source ID absent from the frozen point cache, query its exact full started source race roster and selected API4/API303 quality rows; older cache is reused without global rebuild", "quality_view_definitions_sha256": {name: sha256_text(sql) for name, sql in quality_view_definitions.items()}},
        "api20_contract": {"source": "API20 ridingTestResult_1", "event_key": ["trial_date", "meet_code", "trial_number"], "explicit_jeju_peer_scope": "meet_code=2, raw meet=제주, raw majong=제주, breed_assessment=api_native_label", "row_candidate_rule": "finite positive rcTime, integer ord 1..89, passFlag in locked source allowlist", "latest_three_slots_keep_invalid_rows": True, "rcDist_raw_converted_or_inferred": False, "horse_exclusion_3005648": "never reimported"},
        "population_counts": {"fresh_raw_rows": int(len(fresh)), "observed_dates": int(fresh.race_date.nunique()), "raw_races": int(len(eligibility)), "eligible_races": int(targets.race_id.nunique()), "eligible_runner_rows": int(len(targets)), "eligible_by_date": date_counts, "cold_rows": int(len(cold_targets)), "cold_unique_horses": int(cold_targets.horse_id.nunique()), "cold_by_date": cold_by_date, "cold_dates_K": int(cold_targets.race_date.nunique()), "fresh_postsep19_history_races_used": int(history_long.loc[history_long.history_source_scope.eq("post_sep19_warmup"), "race_id"].nunique()), "selected_same_distance_slots": int(len(selected_slots)), "selected_unique_source_api4_ids": int(selected_slots.api_record_id.nunique()) if len(selected_slots) else 0, "selected_ids_in_frozen_old_point_cache": int(selected_slots.loc[selected_slots.slot_source_in_frozen_point_cache, "api_record_id"].nunique()) if len(selected_slots) else 0, "selected_ids_missing_old_point_cache": int(selected_slots.loc[~selected_slots.slot_source_in_frozen_point_cache, "api_record_id"].nunique()) if len(selected_slots) else 0, "missingcache_source_races_fullroster_queried": int(len(uncached_race_ids)), "missingcache_source_starter_rows_queried": int(len(uncached_starters)), "missingcache_source_race_point_eligible_points": int(pd.DataFrame(point_gate_rows).race_point_eligible.sum()) if point_gate_rows else 0, "actual_slot_point_eligibility_rows": int(len(actual_slot_cache)), "fresh_history_model_schema_rows": int(len(fresh_history_source_rows))},
        "history_reconciliation": {"current_db_vs_frozen_sep19_old_rows_clean": old_reconciliation_clean, "pre_sep20_rows_missing_from_snapshot_n": len(current_missing_from_snapshot), "frozen_rows_missing_from_current_n": len(old_missing_from_current), "overlap_field_diff_rows_n": len(old_row_diffs), "all_target_history_link_rows": int(len(history_long)), "current_pre_cutoff_started_n": int(target_reconciliation.all_current_started_n_through_cutoff.sum()), "scope_delta_started_n": int(target_reconciliation.pre_sep20_scope_delta_started_n.sum()), "source_parity_note": "Current DB source rows dated <=2026-09-19 are compared only with the preserved frozen source snapshot; rows dated >=2026-09-20 are separately labeled warm-up."},
        "api20_counts": {"cold_target_link_rows": int(len(trial_lineage)), "cold_target_horses_with_api20_rows": int(pd.DataFrame(trial_lineage).horse_id.nunique()) if trial_lineage else 0, "linked_event_keys": int(len(event_keys)), "linked_full_explicit_jeju_peer_rows": int(len(peer_rows)), "rcDist_absent_in_peer_rows": int(sum(not r.get("raw_rcDist_present", False) for r in peer_rows)), "trial_collection_timestamps": sorted({str(r.get("collected_at_utc")) for r in peer_rows if r.get("collected_at_utc")})},
        "scoped_fingerprints": {"extracted_row_counts": snapshot_counts, "extracted_rows_sha256": snapshot_fingerprints, "after_reopen_raw_lineage_sha256": after_hashes, "after_reopen_raw_lineage_scope": "selected API record IDs and their immutable payload/page lineage columns only; not a database-wide guard"},
        "output_sha256": output_hashes,
        "prohibitions_checked": {"no_model_fit": True, "no_prediction_scoring": True, "no_outcome_metrics": True, "database_write": False, "operating_registry_write": False, "old_research_folder_write": False},
    }
    write_json(OUT / "audit_manifest.json", manifest)
    print(json.dumps({"counts": manifest["population_counts"], "history": manifest["history_reconciliation"], "api20": manifest["api20_counts"], "output_files": sorted(list(output_hashes) + ["audit_manifest.json"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
