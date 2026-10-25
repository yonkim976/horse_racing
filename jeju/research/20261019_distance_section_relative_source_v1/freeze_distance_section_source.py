"""Freeze the read-only distance-specific Jeju section source bundle.

This is a source audit only: no candidate fitting or scoring. It preserves the
complete saved F1_STYLE6 population and its saved last-five same-distance
lineage, then applies the inherited quality-selected endpoint and full-race
point gates to the frozen reference roster.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
F1_FEATURES = ROOT / "jeju/research/20261009_finish_history_ablation_v1/outputs/features.parquet"
F1_LINEAGE = ROOT / "jeju/research/20261009_finish_history_ablation_v1/outputs/historical_lineage.parquet"
STYLE_FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
BASELINE_SOURCE = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet"
DISTANCES = (900, 1000, 1110, 1200)
TARGET_CUTOFF = "2026-09-19"
MIN_REFERENCE_RACES = 20
GOOD_TIME_STATUS = {"api_positive_unreviewed", "website_corrected"}
ORDER_FIELDS = {"s1f": "sjS1fOrd", "c3": "sj_3cOrd", "c4": "sj_4cOrd", "g1f": "sjG1fOrd"}
GROUP_POINTS = {"s1f": "S1F", "c3": "3C", "c4": "4C", "g1f": "G1F"}
ORDER_STATUS_ALLOWED = {
    "api_positive_unreviewed", "api_unavailable_or_nonpositive_or_sentinel",
    "website_corrected", "website_review_not_applied", "api_source_changed_since_review",
    "unresolved_official_internal_conflict", "internal_conflict_review_not_applied",
    "api_source_changed_since_conflict_review",
}
GROUP_STATUS_ALLOWED = {
    "api_group_unavailable", "api_group_unreviewed", "unresolved_official_internal_conflict",
    "internal_conflict_review_not_applied", "api_source_changed_since_conflict_review",
}
FAIL_TOKENS = ("conflict", "not_applied", "source_changed")
QUALITY_COLUMNS = [
    "api_record_id", "race_date", "meet_code", "race_number", "horse_number", "horse_id",
    "horse_name", "race_distance_m", "finish_position", "finish_status_raw", "finish_time_seconds",
    "api4_3_sjS1fOrd_raw", "api4_3_sjS1fOrd_json_type", "api4_3_sj_3cOrd_raw",
    "api4_3_sj_3cOrd_json_type", "api4_3_sj_4cOrd_raw", "api4_3_sj_4cOrd_json_type",
    "api4_3_sjG1fOrd_raw", "api4_3_sjG1fOrd_json_type", "api4_3_payload_sha256",
    "api4_3_source_artifact_id", "api4_3_source_page_sha256", "api4_3_source_page_path",
    "api303_api_record_id", "api303_payload_sha256", "api303_source_artifact_id",
    "api303_source_page_sha256", "api303_source_page_path", "s1f_time_seconds", "s1f_time_status",
    "c3_time_seconds", "c3_time_status", "c4_time_seconds", "c4_time_status",
    "g3f_time_seconds", "g3f_time_status", "g1f_time_seconds", "g1f_time_status",
    "section_time_website_correction_count", "section_time_review_required_count",
    "section_order_website_correction_count", "section_order_review_required_count",
    "section_internal_conflict_order_count", "section_internal_conflict_group_count",
    "s1f_order", "s1f_order_status", "s1f_group", "s1f_group_status",
    "c3_order", "c3_order_status", "c3_group", "c3_group_status",
    "c4_order", "c4_order_status", "c4_group", "c4_group_status",
    "g1f_order", "g1f_order_status", "g1f_group", "g1f_group_status",
]
TIME_FIELDS = {
    "s1f": ("s1f_time_seconds", "s1f_time_status", "jeS1fTime"),
    "c3": ("c3_time_seconds", "c3_time_status", "je_3cTime"),
    "c4": ("c4_time_seconds", "c4_time_status", "je_4cTime"),
    "g3f": ("g3f_time_seconds", "g3f_time_status", "jeG3fTime"),
    "g1f": ("g1f_time_seconds", "g1f_time_status", "jeG1fTime"),
}
POINT_STATUS_COLS = {
    "s1f": ("s1f_order_status", "s1f_group_status"),
    "c3": ("c3_order_status", "c3_group_status"),
    "c4": ("c4_order_status", "c4_group_status"),
    "g1f": ("g1f_order_status", "g1f_group_status"),
}
SEGMENTS = {
    "seg_1": {"label": "S1F elapsed", "formula": "S1F", "endpoints": ["s1f"], "points": ["s1f"]},
    "seg_2": {"label": "S1F to 3C", "formula": "C3 - S1F", "endpoints": ["s1f", "c3"], "points": ["s1f", "c3"]},
    "seg_3": {"label": "3C to 4C", "formula": "C4 - C3", "endpoints": ["c3", "c4"], "points": ["c3", "c4"]},
    "seg_4": {"label": "4C to G1F crossing", "formula": "T - G1F - C4", "endpoints": ["c4", "g1f"], "points": ["c4", "g1f"]},
    "seg_5": {"label": "G1F elapsed", "formula": "G1F", "endpoints": ["g1f"], "points": ["g1f"]},
}
NOMINAL_LENGTHS = {
    900: [200, 100, 200, 200, 200],
    1000: [200, 200, 200, 200, 200],
    1110: [210, 300, 200, 200, 200],
    1200: [200, 400, 200, 200, 200],
}


def canonical(value):
    if value is None or value is pd.NA:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value.item() if isinstance(value, np.generic) else value


def row_hash(row, columns):
    payload = {column: canonical(row[column]) for column in columns}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_entry(path: Path) -> dict:
    return {"path": str(path.relative_to(ROOT)), "bytes": int(path.stat().st_size), "sha256": file_sha256(path)}


def open_readonly(ids, race_keys=()):
    connection = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.execute("CREATE TEMP TABLE audit_ids (api_record_id INTEGER PRIMARY KEY)")
    connection.executemany("INSERT INTO audit_ids(api_record_id) VALUES (?)", [(int(x),) for x in sorted(set(ids))])
    connection.execute(
        "CREATE TEMP TABLE audit_races (race_date TEXT, meet_code INTEGER, race_number INTEGER, "
        "PRIMARY KEY(race_date,meet_code,race_number))"
    )
    connection.executemany(
        "INSERT INTO audit_races(race_date,meet_code,race_number) VALUES (?,?,?)",
        sorted(set((str(d), int(m), int(r)) for d, m, r in race_keys)),
    )
    connection.commit()  # TEMP tables only; main database URI is mode=ro.
    connection.execute("PRAGMA query_only=ON")
    assert int(connection.execute("PRAGMA query_only").fetchone()[0]) == 1
    connection.execute("BEGIN")
    connection.execute("SELECT api_record_id FROM api_records ORDER BY api_record_id LIMIT 1").fetchone()
    return connection


def source_fingerprints(ids):
    connection = open_readonly(ids)
    try:
        frame = pd.read_sql_query(
            "SELECT a.api_record_id,a.source_artifact_id,a.record_type,a.payload_sha256,"
            "s.sha256 AS source_page_sha256,s.raw_relative_path AS source_page_path "
            "FROM api_records a JOIN source_artifacts s USING(source_artifact_id) "
            "JOIN audit_ids x USING(api_record_id) ORDER BY a.api_record_id", connection,
        )
        assert frame.api_record_id.is_unique
        fpcols = ["api_record_id", "source_artifact_id", "record_type", "payload_sha256", "source_page_sha256", "source_page_path"]
        frame["source_row_fingerprint_sha256"] = frame.apply(lambda row: row_hash(row, fpcols), axis=1)
        return frame
    finally:
        connection.close()


def normalize_ids(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    if not isinstance(value, (list, tuple, np.ndarray)):
        raise AssertionError(f"unexpected saved last5 list: {type(value)!r}")
    return [int(x) for x in value]


def positive_time(value, status):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0 and str(status) in GOOD_TIME_STATUS


def point_status_failed(value, allowed):
    if value is None or pd.isna(value):
        return True
    text = str(value)
    return text not in allowed or any(token in text.lower() for token in FAIL_TOKENS)


def started_by_inherited_f1_rule(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return False
    return (1 <= number <= 89) or number in {91, 92}


def make_intervals(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    s1 = pd.to_numeric(result.s1f_time_seconds, errors="coerce")
    c3 = pd.to_numeric(result.c3_time_seconds, errors="coerce")
    c4 = pd.to_numeric(result.c4_time_seconds, errors="coerce")
    finish = pd.to_numeric(result.finish_time_seconds, errors="coerce")
    g1 = pd.to_numeric(result.g1f_time_seconds, errors="coerce")
    raw = {"seg_1": s1, "seg_2": c3 - s1, "seg_3": c4 - c3, "seg_4": finish - g1 - c4, "seg_5": g1}
    endpoint_ok = {
        "seg_1": result.s1f_time_selected_positive,
        "seg_2": result.s1f_time_selected_positive & result.c3_time_selected_positive,
        "seg_3": result.c3_time_selected_positive & result.c4_time_selected_positive,
        "seg_4": result.c4_time_selected_positive & result.g1f_time_selected_positive & result.finish_time_positive,
        "seg_5": result.g1f_time_selected_positive,
    }
    for name, spec in SEGMENTS.items():
        values = pd.to_numeric(raw[name], errors="coerce")
        point_clear = pd.Series(True, index=result.index)
        for point in spec["points"]:
            point_clear &= result[f"{point}_point_clear_full_race"].astype(bool)
        positive = values.gt(0) & np.isfinite(values)
        result[f"{name}_raw_delta_seconds"] = values
        result[f"{name}_endpoint_measurement_eligible"] = pd.Series(endpoint_ok[name], index=result.index).astype(bool)
        result[f"{name}_point_quality_clear"] = point_clear
        result[f"{name}_quality_eligible"] = result[f"{name}_endpoint_measurement_eligible"] & point_clear & positive
        result[f"{name}_feature_eligible"] = result[f"{name}_quality_eligible"] & result.valid_time.astype(bool)
        result[f"{name}_feature_seconds"] = values.where(result[f"{name}_feature_eligible"])
    return result


def build_reference_stats(race_medians: pd.DataFrame, source_events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for distance in DISTANCES:
        event_group = source_events.loc[source_events.race_distance_m.astype(int).eq(distance)]
        for segment_id in SEGMENTS:
            eligible = race_medians.loc[
                race_medians.race_distance_m.astype(int).eq(distance)
                & race_medians.segment_id.eq(segment_id)
                & race_medians.reference_race_eligible.astype(bool)
            ].sort_values(["race_date", "race_id"], kind="stable")
            dates = pd.to_datetime(eligible.race_date.astype(str)).to_numpy(dtype="datetime64[ns]")
            values = pd.to_numeric(eligible.race_median_seconds, errors="coerce").to_numpy(float)
            prefix_sum = np.concatenate(([0.0], np.cumsum(values)))
            prefix_n = np.arange(len(values) + 1, dtype=np.int64)
            eligible_rows = event_group[["race_id", "race_date", "race_distance_m"]].drop_duplicates().copy()
            eligible_rows["reference_cutoff_t_minus_2"] = (
                pd.to_datetime(eligible_rows.race_date.astype(str)) - pd.to_timedelta(2, unit="D")
            ).dt.strftime("%Y-%m-%d")
            cutoff_values = pd.to_datetime(eligible_rows.reference_cutoff_t_minus_2).to_numpy(dtype="datetime64[ns]")
            stop = np.searchsorted(dates, cutoff_values, side="right")
            counts = prefix_n[stop]
            means = np.divide(prefix_sum[stop], counts, out=np.full(len(counts), np.nan), where=counts > 0)
            # Prefix rows are race medians sorted by date and race ID; the first
            # eligible date is shared by every nonempty prefix.
            all_dates = eligible.race_date.astype(str).to_numpy()
            first_dates = np.array([all_dates[0] if n > 0 else None for n in counts], dtype=object)
            last_dates = np.array([all_dates[n - 1] if n > 0 else None for n in counts], dtype=object)
            for i, row in enumerate(eligible_rows.itertuples(index=False)):
                n = int(counts[i])
                rows.append({
                    "source_race_id": str(row.race_id),
                    "source_race_date": str(row.race_date),
                    "race_distance_m": int(row.race_distance_m),
                    "segment_id": segment_id,
                    "reference_cutoff_t_minus_2": str(row.reference_cutoff_t_minus_2),
                    "minimum_prior_eligible_races": MIN_REFERENCE_RACES,
                    "prior_eligible_race_n": n,
                    "reference_first_race_date": first_dates[i],
                    "reference_last_race_date": last_dates[i],
                    "mean_of_prior_race_medians_seconds": float(means[i]) if n >= MIN_REFERENCE_RACES else None,
                    "benchmark_exists": bool(n >= MIN_REFERENCE_RACES),
                })
    return pd.DataFrame(rows)


def main():
    for path in (DB, F1_FEATURES, F1_LINEAGE, STYLE_FEATURES, BASELINE_SOURCE):
        if not path.is_file():
            raise FileNotFoundError(path)
    for path in HERE.iterdir():
        if path.is_file() and path.name not in {"freeze_distance_section_source.py"}:
            raise FileExistsError(f"refusing to overwrite existing file in fresh output directory: {path}")

    f1 = pd.read_parquet(F1_FEATURES)
    lineage = pd.read_parquet(F1_LINEAGE)
    style = pd.read_parquet(STYLE_FEATURES)
    baseline = pd.read_parquet(BASELINE_SOURCE)
    assert f1.api_record_id.is_unique and style.api_record_id.is_unique and baseline.api_record_id.is_unique
    assert len(style) == 52155 and set(style.api_record_id.astype("int64")) == set(f1.api_record_id.astype("int64"))
    assert not style.columns.duplicated().any()
    # The upstream saved F1_STYLE6 population already omits this known-excluded
    # horse. This audit applies no additional horse filter and keeps all 52,155 rows.
    assert not style.horse_id.astype(str).eq("3005648").any()

    targets = f1.loc[
        pd.to_numeric(f1.distance_m, errors="coerce").isin(DISTANCES)
        & f1.race_date.astype(str).le(TARGET_CUTOFF)
    ].copy()
    targets = targets.sort_values(["race_date", "race_id", "horse_number"], kind="stable").reset_index(drop=True)
    target_ids = set(targets.api_record_id.astype("int64"))
    target_slots = lineage.loc[
        lineage.history_kind.eq("last5_same_distance_start")
        & lineage.target_api_record_id.astype("int64").isin(target_ids)
    ].copy()
    target_slots = target_slots.sort_values(["target_api_record_id", "slot_oldest_to_newest"], kind="stable").reset_index(drop=True)
    expected_cutoff = (
        pd.to_datetime(targets.race_date.astype(str)) - pd.to_timedelta(2, unit="D")
    ).dt.strftime("%Y-%m-%d")
    assert targets.history_cutoff.astype(str).reset_index(drop=True).equals(expected_cutoff.reset_index(drop=True))

    lineage_ids = {
        int(target_id): [int(x) for x in group.sort_values("slot_oldest_to_newest").source_api_record_id]
        for target_id, group in target_slots.groupby("target_api_record_id", sort=False)
    }
    for row in targets[["api_record_id", "last5_same_source_ids"]].itertuples(index=False):
        assert normalize_ids(row.last5_same_source_ids) == lineage_ids.get(int(row.api_record_id), []), row.api_record_id
    assert target_slots.slot_oldest_to_newest.notna().all()
    assert target_slots.slot_oldest_to_newest.astype(int).between(1, 5).all()
    assert target_slots.source_started.eq(True).all()
    assert target_slots.target_horse_id.astype(str).eq(target_slots.source_horse_id.astype(str)).all()
    assert target_slots.target_distance_m.astype(int).isin(DISTANCES).all()
    assert target_slots.source_distance_m.astype(int).eq(target_slots.target_distance_m.astype(int)).all()
    assert target_slots.source_race_date.astype(str).le(target_slots.target_cutoff.astype(str)).all()
    assert target_slots.groupby("target_api_record_id").slot_oldest_to_newest.apply(
        lambda s: s.astype(int).tolist() == list(range(1, len(s) + 1))
    ).all()
    assert not targets.horse_id.astype(str).eq("3005648").any()

    baseline["race_distance_m"] = pd.to_numeric(baseline.race_distance_m, errors="coerce")
    baseline["meet_code"] = pd.to_numeric(baseline.meet_code, errors="coerce")
    baseline["api_record_id"] = baseline.api_record_id.astype("int64")
    baseline["race_id"] = baseline.race_id.astype(str)
    candidate_started = baseline.loc[
        baseline.meet_code.eq(2) & baseline.started.astype(bool) & baseline.race_distance_m.isin(DISTANCES)
    ].copy()
    candidate_race_ids = set(candidate_started.race_id.astype(str))
    candidate_rows = baseline.loc[baseline.race_id.astype(str).isin(candidate_race_ids)].copy()
    assert candidate_rows.race_id.nunique() == len(candidate_race_ids)
    assert candidate_rows.race_distance_m.astype(int).isin(DISTANCES).all()
    assert candidate_rows.meet_code.astype(int).eq(2).all()
    assert candidate_started[["api_record_id", "horse_id", "horse_number"]].notna().all().all()
    assert not candidate_started.horse_id.astype(str).eq("3005648").any()
    assert not candidate_started.duplicated(["race_id", "api_record_id"]).any()
    assert not candidate_started.duplicated(["race_id", "horse_id"]).any()
    assert not candidate_started.duplicated(["race_id", "horse_number"]).any()
    assert target_ids.issubset(set(candidate_started.api_record_id.astype("int64")))
    source_ids = set(target_slots.source_api_record_id.astype("int64"))
    assert source_ids.issubset(set(candidate_started.api_record_id.astype("int64")))
    assert set(target_slots.source_race_id.astype(str)).issubset(candidate_race_ids)

    baseline_index = baseline.set_index("api_record_id", drop=False)
    all_target_ids = set(style.api_record_id.astype("int64"))
    assert all_target_ids.issubset(set(baseline_index.index.astype("int64")))
    race_info = candidate_rows[["race_id", "race_date", "meet_code", "race_number"]].drop_duplicates()
    assert race_info.race_id.is_unique
    race_keys = list(race_info[["race_date", "meet_code", "race_number"]].itertuples(index=False, name=None))

    # First read only the current result roster. The frozen baseline is the fixed
    # reference-median population; current DB starters supply the full-race mask
    # denominator and may contain additional rows in known partial old snapshots.
    roster_connection = open_readonly((), race_keys)
    try:
        db_roster_pre = pd.read_sql_query(
            "SELECT r.api_record_id,r.race_date,r.meet_code,r.race_number,r.horse_number,r.horse_id,r.finish_position "
            "FROM race_result_rows r JOIN audit_races k USING(race_date,meet_code,race_number) "
            "ORDER BY r.race_date,r.meet_code,r.race_number,r.horse_number,r.api_record_id", roster_connection,
        )
        assert int(roster_connection.execute("PRAGMA query_only").fetchone()[0]) == 1
    finally:
        roster_connection.close()
    db_roster_pre["api_record_id"] = db_roster_pre.api_record_id.astype("int64")
    db_roster_pre["race_id"] = db_roster_pre.race_date.astype(str) + "_" + db_roster_pre.meet_code.astype("Int64").astype(str) + "_" + db_roster_pre.race_number.astype("Int64").astype(str)
    db_roster_pre["started"] = db_roster_pre.finish_position.map(started_by_inherited_f1_rule)
    db_started_pre = db_roster_pre.loc[db_roster_pre.started].copy()
    frozen_event_ids = set(candidate_rows.api_record_id.astype("int64"))
    frozen_started_ids = set(candidate_started.api_record_id.astype("int64"))
    db_event_ids_pre = set(db_roster_pre.api_record_id.astype("int64"))
    db_started_ids_pre = set(db_started_pre.api_record_id.astype("int64"))
    assert db_roster_pre.api_record_id.is_unique and db_started_pre.api_record_id.is_unique
    assert frozen_event_ids.issubset(db_event_ids_pre), "frozen baseline event row missing from current DB roster"
    assert frozen_started_ids.issubset(db_started_ids_pre), "frozen baseline started row missing from current DB roster"
    assert not db_roster_pre.horse_id.astype(str).eq("3005648").any()
    assert not (db_event_ids_pre - frozen_event_ids) & frozen_event_ids

    db_roster_pre_index = db_roster_pre.set_index("api_record_id", drop=False)
    frozen_event_index = candidate_rows.set_index("api_record_id", drop=False)
    frozen_common = frozen_event_index.loc[sorted(frozen_event_ids)].sort_index()
    current_common = db_roster_pre_index.loc[sorted(frozen_event_ids)].sort_index()
    assert frozen_common.race_id.astype(str).equals(current_common.race_id.astype(str))
    assert frozen_common.horse_id.astype(str).equals(current_common.horse_id.astype(str))
    assert pd.to_numeric(frozen_common.horse_number, errors="coerce").equals(pd.to_numeric(current_common.horse_number, errors="coerce"))
    assert pd.to_numeric(frozen_common.finish_position, errors="coerce").equals(pd.to_numeric(current_common.finish_position, errors="coerce"))

    mask_only_db_rows = db_roster_pre.loc[db_roster_pre.api_record_id.astype("int64").isin(db_event_ids_pre - frozen_event_ids)].copy()
    mask_only_db_rows["row_role"] = "full_race_mask_only_current_db_row"
    mask_only_db_rows["included_in_frozen_reference_median_population"] = False
    mask_only_db_rows["missing_from_frozen_reference_snapshot_reason"] = "current_db_row_absent_from_frozen_92513_source_snapshot"
    assert not mask_only_db_rows.horse_id.astype(str).eq("3005648").any()
    roster_reconciliation_rows = []
    for race_id in sorted(candidate_race_ids):
        b_event = candidate_rows.loc[candidate_rows.race_id.astype(str).eq(race_id)]
        b_started = candidate_started.loc[candidate_started.race_id.astype(str).eq(race_id)]
        d_event = db_roster_pre.loc[db_roster_pre.race_id.astype(str).eq(race_id)]
        d_started = db_started_pre.loc[db_started_pre.race_id.astype(str).eq(race_id)]
        b_ids = set(b_event.api_record_id.astype("int64"))
        d_ids = set(d_event.api_record_id.astype("int64"))
        b_start_ids = set(b_started.api_record_id.astype("int64"))
        d_start_ids = set(d_started.api_record_id.astype("int64"))
        roster_reconciliation_rows.append({
            "race_id": race_id, "race_date": str(d_event.race_date.iloc[0]),
            "race_distance_m": int(b_event.race_distance_m.iloc[0]),
            "frozen_candidate_event_rows": len(b_ids), "current_db_event_rows": len(d_ids),
            "frozen_reference_started_rows": len(b_start_ids), "current_db_started_rows": len(d_start_ids),
            "current_db_extra_event_rows": len(d_ids - b_ids), "frozen_only_event_rows": len(b_ids - d_ids),
            "current_db_extra_started_rows": len(d_start_ids - b_start_ids),
            "frozen_only_started_rows": len(b_start_ids - d_start_ids),
            "frozen_full_race_starter_coverage": bool(b_start_ids == d_start_ids),
            "reference_median_population": "frozen_snapshot_started_rows_only",
            "point_mask_denominator": "current_database_started_roster",
        })
    roster_reconciliation = pd.DataFrame(roster_reconciliation_rows)
    assert int(roster_reconciliation.current_db_extra_event_rows.sum()) == len(mask_only_db_rows)
    assert int(roster_reconciliation.current_db_extra_started_rows.sum()) == len(db_started_ids_pre - frozen_started_ids)
    assert roster_reconciliation.frozen_only_event_rows.sum() == 0
    assert roster_reconciliation.frozen_only_started_rows.sum() == 0
    partial_frozen_races = roster_reconciliation.loc[~roster_reconciliation.frozen_full_race_starter_coverage].copy()

    # Query the quality view for the fixed frozen reference roster. Current
    # DB-only starters stay in the full-race point denominator; their missing
    # quality-view provenance will fail closed in the point masks below.
    quality_ids = frozen_started_ids
    assert target_ids.issubset(quality_ids)
    assert source_ids.issubset(quality_ids)
    fingerprint_ids = frozen_event_ids | db_event_ids_pre | all_target_ids
    baseline_ids_for_quality = quality_ids & set(baseline_index.index.astype("int64"))
    selected_baseline = baseline_index.loc[sorted(baseline_ids_for_quality)].copy().reset_index(drop=True)
    selected_baseline["api_record_id"] = selected_baseline.api_record_id.astype("int64")
    expected_ids_by_race = {
        str(race_id): set(group.api_record_id.astype("int64"))
        for race_id, group in db_started_pre.groupby("race_id", sort=False)
    }
    expected_identity_by_race = {
        str(race_id): {
            int(row.api_record_id): (str(row.horse_id), int(row.horse_number))
            for row in group[["api_record_id", "horse_id", "horse_number"]].itertuples(index=False)
        }
        for race_id, group in db_started_pre.groupby("race_id", sort=False)
    }
    db_roster_pre_signature = db_roster_pre[["api_record_id", "race_id", "horse_id", "horse_number", "finish_position", "started"]].sort_values("api_record_id").reset_index(drop=True)
    before_fp = source_fingerprints(fingerprint_ids)
    assert set(before_fp.api_record_id.astype("int64")) == fingerprint_ids
    connection = open_readonly(quality_ids, race_keys)
    try:
        data_version_at_snapshot = int(connection.execute("PRAGMA data_version").fetchone()[0])
        db_roster = pd.read_sql_query(
            "SELECT r.api_record_id,r.race_date,r.meet_code,r.race_number,r.horse_number,r.horse_id,r.finish_position "
            "FROM race_result_rows r JOIN audit_races k USING(race_date,meet_code,race_number) "
            "ORDER BY r.race_date,r.meet_code,r.race_number,r.horse_number,r.api_record_id", connection,
        )
        db_roster["api_record_id"] = db_roster.api_record_id.astype("int64")
        db_roster["race_id"] = db_roster.race_date.astype(str) + "_" + db_roster.meet_code.astype("Int64").astype(str) + "_" + db_roster.race_number.astype("Int64").astype(str)
        db_roster["started"] = db_roster.finish_position.map(started_by_inherited_f1_rule)
        db_started = db_roster.loc[db_roster.started].copy()
        db_roster_signature = db_roster[["api_record_id", "race_id", "horse_id", "horse_number", "finish_position", "started"]].sort_values("api_record_id").reset_index(drop=True)
        assert_frame_equal(db_roster_pre_signature, db_roster_signature, check_dtype=False, check_exact=True)
        assert db_roster.api_record_id.is_unique and db_started.api_record_id.is_unique

        quality_sql = "SELECT " + ",".join(f"q.{col}" for col in QUALITY_COLUMNS) + " FROM jeju_race_postrace_sections_quality_2026 q JOIN audit_ids x USING(api_record_id) ORDER BY q.api_record_id"
        quality = pd.read_sql_query(quality_sql, connection)
        assert quality.api_record_id.is_unique
        quality_observed_ids = set(quality.api_record_id.astype("int64"))
        assert quality_observed_ids == quality_ids, (
            f"quality-view coverage mismatch: missing={len(quality_ids - quality_observed_ids)}, "
            f"extra={len(quality_observed_ids - quality_ids)}"
        )

        time_marks = ",".join("?" for _ in TIME_FIELDS)
        review_rows = pd.read_sql_query(
            "SELECT r.api_record_id,r.field_name,r.review_status,r.api_seconds_at_review,r.api_payload_sha256_at_review,"
            "r.website_display,r.website_seconds,r.effective_seconds,r.website_url,r.checked_date_kst,"
            "r.evidence_relative_path,r.evidence_sha256,r.decision_reason,r.applied_at_utc "
            "FROM race_section_time_reviews r JOIN audit_ids x USING(api_record_id) "
            f"WHERE r.field_name IN ({time_marks}) ORDER BY r.api_record_id,r.field_name",
            connection, params=[v[2] for v in TIME_FIELDS.values()],
        )
        order_marks = ",".join("?" for _ in ORDER_FIELDS)
        order_values = pd.read_sql_query(
            "SELECT v.api_record_id,v.race_date,v.meet_code,v.race_number,v.horse_number,v.horse_id,v.field_name,"
            "v.quality_order_value,v.quality_order_status,v.api_payload_sha256,v.api_source_artifact_id,"
            "v.api_source_page_sha256,v.api_source_page_path FROM jeju_race_section_order_quality_values v "
            "JOIN audit_races r USING(race_date,meet_code,race_number) "
            f"WHERE v.field_name IN ({order_marks}) "
            "ORDER BY v.race_date,v.meet_code,v.race_number,v.field_name,v.horse_number,v.horse_id",
            connection, params=list(ORDER_FIELDS.values()),
        )
        group_marks = ",".join("?" for _ in GROUP_POINTS)
        group_values = pd.read_sql_query(
            "SELECT v.api_record_id,a.source_artifact_id,a.record_type,v.race_date,v.meet_code,v.race_number,"
            "v.point,v.group_status,v.group_value,v.payload_sha256,v.source_page_sha256,"
            "v.raw_relative_path AS source_page_path FROM jeju_race_section_group_quality_values v "
            "JOIN api_records a USING(api_record_id) JOIN audit_races r USING(race_date,meet_code,race_number) "
            f"WHERE v.point IN ({group_marks}) "
            "ORDER BY v.race_date,v.meet_code,v.race_number,v.point,v.api_record_id",
            connection, params=list(GROUP_POINTS.values()),
        )
        view_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='view' AND name='jeju_race_postrace_sections_quality_2026'"
        ).fetchone()
        assert view_row and view_row[0]
        view_sql_sha256 = hashlib.sha256(view_row[0].encode("utf-8")).hexdigest()
        assert int(connection.execute("PRAGMA query_only").fetchone()[0]) == 1
    finally:
        connection.close()

    # Reconcile frozen baseline rows and quality-view selected values/fingerprints.
    quality = quality.merge(
        selected_baseline[["api_record_id", "race_id", "race_distance_m", "started", "valid_time", "api4_3_payload_sha256", "finish_time_seconds"]],
        on="api_record_id", how="left", validate="one_to_one", suffixes=("", "_baseline"),
    )
    quality["frozen_reference_roster_member"] = quality.api_record_id.astype("int64").isin(frozen_started_ids)
    quality["full_race_mask_only_current_db_starter"] = quality.api_record_id.astype("int64").isin(db_started_ids_pre - frozen_started_ids)
    quality["quality_race_id"] = (
        quality.race_date.astype(str) + "_" + quality.meet_code.astype("Int64").astype(str)
        + "_" + quality.race_number.astype("Int64").astype(str)
    )
    frozen_quality = quality.loc[quality.frozen_reference_roster_member].copy()
    assert len(frozen_quality) == len(frozen_started_ids)
    frozen_lookup = selected_baseline.set_index("api_record_id", drop=False)
    assert frozen_quality.race_id.astype(str).eq(
        frozen_lookup.loc[frozen_quality.api_record_id.astype("int64"), "race_id"].astype(str).reset_index(drop=True)
    ).all()
    assert frozen_quality.horse_id.astype(str).eq(
        frozen_lookup.loc[frozen_quality.api_record_id.astype("int64"), "horse_id"].astype(str).reset_index(drop=True)
    ).all()
    assert frozen_quality.horse_number.astype(int).eq(
        frozen_lookup.loc[frozen_quality.api_record_id.astype("int64"), "horse_number"].astype(int).reset_index(drop=True)
    ).all()
    assert frozen_quality.race_distance_m.astype(float).eq(frozen_quality.race_distance_m_baseline.astype(float)).all()
    assert frozen_quality.race_distance_m.astype(int).isin(DISTANCES).all()
    assert np.array_equal(
        pd.to_numeric(frozen_quality.finish_time_seconds, errors="coerce").to_numpy(float),
        pd.to_numeric(frozen_lookup.loc[frozen_quality.api_record_id.astype("int64"), "finish_time_seconds"], errors="coerce").to_numpy(float),
        equal_nan=True,
    )
    assert frozen_quality.started.astype(bool).equals(
        frozen_lookup.loc[frozen_quality.api_record_id.astype("int64"), "started"].astype(bool).reset_index(drop=True)
    )
    assert frozen_quality.valid_time.astype(bool).equals(
        frozen_lookup.loc[frozen_quality.api_record_id.astype("int64"), "valid_time"].astype(bool).reset_index(drop=True)
    )
    assert frozen_quality.api4_3_payload_sha256.astype(str).eq(frozen_quality.api4_3_payload_sha256_baseline.astype(str)).all()
    quality_missing_current_starters = db_started_ids_pre - quality_observed_ids
    assert quality_missing_current_starters == db_started_ids_pre - frozen_started_ids
    assert quality_missing_current_starters == set(mask_only_db_rows.api_record_id.astype("int64"))
    assert quality_missing_current_starters.isdisjoint(target_ids | source_ids)
    mask_only_db_rows["quality_view_row_present"] = False
    mask_only_db_rows["quality_view_missing_consequence"] = "full_race_point_mask_fails_closed"

    order_values["race_id"] = order_values.race_date.astype(str) + "_" + order_values.meet_code.astype("Int64").astype(str) + "_" + order_values.race_number.astype("Int64").astype(str)
    group_values["race_id"] = group_values.race_date.astype(str) + "_" + group_values.meet_code.astype("Int64").astype(str) + "_" + group_values.race_number.astype("Int64").astype(str)
    assert not order_values.duplicated(["api_record_id", "field_name"]).any()
    order_values["api_record_id"] = pd.to_numeric(order_values.api_record_id, errors="raise").astype("int64")
    order_values["is_started_roster_member"] = order_values.api_record_id.isin(db_started_ids_pre)
    group_values["api_record_id"] = pd.to_numeric(group_values.api_record_id, errors="raise").astype("int64")
    quality_index = quality.set_index("api_record_id", drop=False)
    quality_by_race = {}
    quality_missing_by_race = {}
    for race_id in candidate_race_ids:
        expected_ids = expected_ids_by_race[race_id]
        available_ids = expected_ids & quality_observed_ids
        quality_by_race[race_id] = quality_index.loc[sorted(available_ids)].copy()
        quality_missing_by_race[race_id] = expected_ids - available_ids
    api303_selection = {}
    for race_id in sorted(candidate_race_ids):
        q = quality_by_race[race_id]
        raw_ids = q.api303_api_record_id
        null_n = int(raw_ids.isna().sum())
        unique_ids = sorted({int(v) for v in raw_ids.dropna()})
        quality_roster_complete = len(quality_missing_by_race[race_id]) == 0
        consistent = quality_roster_complete and null_n == 0 and len(unique_ids) == 1
        api303_selection[race_id] = {
            "api303_selected_record_id": unique_ids[0] if len(unique_ids) == 1 else None,
            "api303_selection_consistent_across_started_roster": bool(consistent),
            "api303_selected_id_null_runner_n": null_n,
            "api303_distinct_selected_ids_n": len(unique_ids),
            "quality_view_started_roster_complete": bool(quality_roster_complete),
            "quality_view_missing_started_runner_n": int(len(quality_missing_by_race[race_id])),
        }
    group_values["api303_selected_record_id"] = group_values.race_id.map({k: v["api303_selected_record_id"] for k, v in api303_selection.items()})
    group_values["is_started_roster_selected_api303_record"] = (
        group_values.api303_selected_record_id.notna()
        & group_values.api_record_id.eq(pd.to_numeric(group_values.api303_selected_record_id, errors="coerce"))
    )
    order_by_key = {key: group for key, group in order_values.groupby(["race_id", "field_name"], sort=False)}
    group_by_key = {key: group for key, group in group_values.groupby(["race_id", "point"], sort=False)}
    point_records = []
    for race_id in sorted(candidate_race_ids):
        expected_ids = expected_ids_by_race[race_id]
        expected_n = len(expected_ids)
        expected_identity = expected_identity_by_race[race_id]
        for point, field_name in ORDER_FIELDS.items():
            all_orders = order_by_key.get((race_id, field_name), order_values.iloc[0:0])
            orders = all_orders.loc[all_orders.api_record_id.isin(expected_ids)]
            groups = group_by_key.get((race_id, GROUP_POINTS[point]), group_values.iloc[0:0])
            selected_id = api303_selection[race_id]["api303_selected_record_id"]
            selected_groups = groups.loc[groups.api_record_id.eq(selected_id)] if selected_id is not None else groups.iloc[0:0]
            quality_roster_complete = len(quality_missing_by_race[race_id]) == 0
            observed_ids = set(orders.api_record_id.astype("int64"))
            ids_equal = observed_ids == expected_ids and len(orders) == len(expected_ids)
            identity_equal = ids_equal and all(
                expected_identity.get(int(row.api_record_id)) == (str(row.horse_id), int(row.horse_number))
                for row in orders[["api_record_id", "horse_id", "horse_number"]].itertuples(index=False)
            )
            order_bad = orders.quality_order_status.apply(lambda v: point_status_failed(v, ORDER_STATUS_ALLOWED))
            group_bad = selected_groups.group_status.apply(lambda v: point_status_failed(v, GROUP_STATUS_ALLOWED))
            group_exact = len(selected_groups) == 1
            group_fp_match = False
            group_status_match = False
            if group_exact:
                selected_group = selected_groups.iloc[0]
                qrows = quality_by_race[race_id]
                status_col = POINT_STATUS_COLS[point][1]
                view_statuses = {"<NULL>" if pd.isna(v) else str(v) for v in qrows[status_col]}
                selected_status = "<NULL>" if pd.isna(selected_group.group_status) else str(selected_group.group_status)
                group_status_match = quality_roster_complete and view_statuses == {selected_status}
                qrow = qrows.iloc[0]
                pairs = [
                    (selected_group.payload_sha256, qrow.api303_payload_sha256),
                    (selected_group.source_artifact_id, qrow.api303_source_artifact_id),
                    (selected_group.source_page_sha256, qrow.api303_source_page_sha256),
                    (selected_group.source_page_path, qrow.api303_source_page_path),
                ]
                group_fp_match = quality_roster_complete and all(not pd.isna(a) and not pd.isna(b) and str(a) == str(b) for a, b in pairs)
            point_records.append({
                "race_id": race_id, "point": point,
                "race_date": str(race_id.rsplit("_", 2)[0]),
                "race_distance_m": int(candidate_started.loc[candidate_started.race_id.astype(str).eq(race_id), "race_distance_m"].iloc[0]),
                "expected_full_roster_runner_rows": expected_n, "observed_order_status_rows": int(len(orders)),
                "expected_started_api_record_ids_sha256": hashlib.sha256(",".join(map(str, sorted(expected_ids))).encode()).hexdigest(),
                "observed_order_api_record_ids_sha256": hashlib.sha256(",".join(map(str, sorted(observed_ids))).encode()).hexdigest(),
                "order_status_coverage_complete": bool(ids_equal and identity_equal),
                "order_started_api_id_set_exact": bool(ids_equal), "order_started_horse_identity_exact": bool(identity_equal),
                "order_status_missing_or_unknown_or_hold_n": int(order_bad.sum()),
                "order_status_values": sorted({str(v) for v in orders.quality_order_status.dropna()}),
                "group_status_rows": int(len(groups)), "api303_selected_record_id": selected_id,
                "api303_selection_consistent_across_started_roster": api303_selection[race_id]["api303_selection_consistent_across_started_roster"],
                "quality_view_started_roster_complete": bool(quality_roster_complete),
                "quality_view_missing_started_runner_n": int(len(quality_missing_by_race[race_id])),
                "api303_selected_id_null_runner_n": api303_selection[race_id]["api303_selected_id_null_runner_n"],
                "api303_distinct_selected_ids_n": api303_selection[race_id]["api303_distinct_selected_ids_n"],
                "group_selected_record_status_rows": int(len(selected_groups)), "group_status_coverage_present": bool(group_exact),
                "group_status_missing_or_unknown_or_hold_n": int(group_bad.sum()),
                "group_status_values": sorted({str(v) for v in selected_groups.group_status.dropna()}),
                "group_selected_source_fingerprint_matches_quality_view": bool(group_fp_match),
                "group_quality_status_matches_quality_view": bool(group_status_match),
                "point_clear_full_race": bool(
                    ids_equal and identity_equal and group_exact
                    and quality_roster_complete
                    and api303_selection[race_id]["api303_selection_consistent_across_started_roster"]
                    and group_fp_match and group_status_match and not order_bad.any() and not group_bad.any()
                ),
            })
    point_masks = pd.DataFrame(point_records)
    assert len(point_masks) == len(candidate_race_ids) * len(ORDER_FIELDS)
    point_hash_columns = [
        "race_id", "point", "expected_full_roster_runner_rows", "observed_order_status_rows",
        "expected_started_api_record_ids_sha256", "observed_order_api_record_ids_sha256",
        "order_status_coverage_complete", "order_started_api_id_set_exact", "order_started_horse_identity_exact",
        "order_status_missing_or_unknown_or_hold_n", "order_status_values", "group_status_rows",
        "api303_selected_record_id", "api303_selection_consistent_across_started_roster",
        "quality_view_started_roster_complete", "quality_view_missing_started_runner_n",
        "api303_selected_id_null_runner_n", "api303_distinct_selected_ids_n", "group_selected_record_status_rows",
        "group_status_coverage_present", "group_status_missing_or_unknown_or_hold_n", "group_status_values",
        "group_selected_source_fingerprint_matches_quality_view", "group_quality_status_matches_quality_view", "point_clear_full_race",
    ]
    point_masks["race_point_status_mask_sha256"] = point_masks.apply(lambda r: row_hash(r, point_hash_columns), axis=1)
    clear_wide = point_masks.pivot(index="race_id", columns="point", values="point_clear_full_race").rename(
        columns={point: f"{point}_point_clear_full_race" for point in ORDER_FIELDS}
    ).reset_index()
    assert set(clear_wide.race_id.astype(str)) == candidate_race_ids

    for name, (time_col, status_col, _) in TIME_FIELDS.items():
        quality[f"{name}_time_selected_positive"] = quality.apply(lambda row: positive_time(row[time_col], row[status_col]), axis=1)
    quality["finish_time_positive"] = pd.to_numeric(quality.finish_time_seconds, errors="coerce").gt(0)
    quality["finish_time_valid_baseline"] = quality.valid_time.astype(bool)
    quality["finish_time_feature_endpoint_eligible"] = quality.finish_time_positive & quality.finish_time_valid_baseline
    role = pd.Series("full_race_mask_only_current_db_starter", index=quality.index, dtype="object")
    role.loc[quality.frozen_reference_roster_member] = "benchmark_reference_roster"
    role.loc[quality.api_record_id.astype("int64").isin(target_ids)] = "target_and_reference_roster"
    role.loc[quality.api_record_id.astype("int64").isin(source_ids)] = "history_source_and_reference_roster"
    role.loc[quality.api_record_id.astype("int64").isin(target_ids & source_ids)] = "target_and_history_source_and_reference_roster"
    quality.insert(0, "source_row_role", role)
    quality["source_row_fingerprint_sha256"] = quality.apply(lambda row: row_hash(row, QUALITY_COLUMNS), axis=1)

    reference_roster = candidate_started[[
        "api_record_id", "race_id", "race_date", "meet_code", "race_number", "race_distance_m",
        "horse_id", "horse_number", "finish_position", "finish_time_seconds", "started", "valid_time",
        "api4_3_payload_sha256",
    ]].copy()
    current_started_counts = db_started_pre.groupby("race_id").size().to_dict()
    frozen_started_counts = candidate_started.groupby("race_id").size().to_dict()
    reference_roster["frozen_reference_started_n"] = reference_roster.race_id.map(frozen_started_counts).astype(int)
    reference_roster["current_db_full_race_started_n"] = reference_roster.race_id.map(current_started_counts).astype(int)
    reference_roster["frozen_source_has_full_started_roster"] = reference_roster.frozen_reference_started_n.eq(
        reference_roster.current_db_full_race_started_n
    )
    reference_roster["median_population_scope"] = "frozen_snapshot_eligible_starters_only"
    reference_roster = reference_roster.merge(
        quality[["api_record_id", "api4_3_source_artifact_id", "api4_3_source_page_sha256", "api4_3_source_page_path", "api303_api_record_id", "api303_payload_sha256", "api303_source_artifact_id", "api303_source_page_sha256", "api303_source_page_path"]],
        on="api_record_id", how="left", validate="one_to_one",
    )
    assert reference_roster.api4_3_source_artifact_id.notna().all()
    time_quality_cols = ["api_record_id", "race_id", "race_date", "race_distance_m", "valid_time", "finish_time_seconds"]
    for name, (time_col, status_col, _) in TIME_FIELDS.items():
        time_quality_cols += [time_col, status_col, f"{name}_time_selected_positive"]
    reference_intervals = candidate_started[time_quality_cols[:0] + ["api_record_id", "race_id", "race_date", "race_distance_m", "horse_id", "horse_number", "finish_position", "finish_time_seconds", "started", "valid_time"]].merge(
        quality[time_quality_cols], on=["api_record_id", "race_id", "race_date", "race_distance_m", "finish_time_seconds", "valid_time"],
        how="left", validate="one_to_one", suffixes=("", "_q"),
    )
    reference_intervals = reference_intervals.merge(clear_wide, on="race_id", how="left", validate="many_to_one")
    assert reference_intervals.s1f_point_clear_full_race.notna().all()
    reference_intervals["finish_time_positive"] = pd.to_numeric(reference_intervals.finish_time_seconds, errors="coerce").gt(0)
    reference_intervals = make_intervals(reference_intervals)
    reference_intervals["nominal_length_m"] = reference_intervals.race_distance_m.astype(int).map(
        {d: lengths for d, lengths in NOMINAL_LENGTHS.items()}
    )
    for name, idx in zip(SEGMENTS, range(5)):
        reference_intervals[f"{name}_nominal_length_m"] = reference_intervals.nominal_length_m.map(lambda v: v[idx])
    reference_intervals = reference_intervals.drop(columns=["nominal_length_m"])
    reference_intervals["frozen_source_has_full_started_roster"] = reference_intervals.race_id.map(
        roster_reconciliation.set_index("race_id").frozen_full_race_starter_coverage.astype(bool).to_dict()
    )
    reference_intervals["median_population_scope"] = "frozen_snapshot_eligible_starters_only"

    # One row per frozen reference race and generic interval. Races with zero usable
    # starters stay in this table with count 0 and NULL median.
    reference_race_rows = []
    for (race_id, distance, race_date), group in reference_intervals.groupby(["race_id", "race_distance_m", "race_date"], sort=False):
        for segment_id in SEGMENTS:
            eligible = group.loc[group[f"{segment_id}_feature_eligible"].astype(bool), f"{segment_id}_feature_seconds"]
            n = int(eligible.notna().sum())
            reference_race_rows.append({
                "race_id": str(race_id), "race_date": str(race_date), "race_distance_m": int(distance),
                "segment_id": segment_id, "eligible_runner_n": n,
                "race_median_seconds": float(eligible.median()) if n else None,
                "reference_race_eligible": bool(n > 0),
                "frozen_source_has_full_started_roster": bool(group.frozen_source_has_full_started_roster.all()),
                "median_population_scope": "frozen_snapshot_eligible_starters_only",
            })
    reference_race_medians = pd.DataFrame(reference_race_rows)
    source_events = target_slots[["source_race_id", "source_race_date", "source_distance_m"]].drop_duplicates().rename(
        columns={"source_race_id": "race_id", "source_race_date": "race_date", "source_distance_m": "race_distance_m"}
    )
    source_events["race_distance_m"] = source_events.race_distance_m.astype(int)
    source_event_benchmarks = build_reference_stats(reference_race_medians, source_events)

    # Keep every last-five slot, including invalid source sections and slots with
    # fewer than 20 prior reference races. No older source slot is selected.
    source_time_cols = ["api_record_id", "race_id", "race_date", "race_distance_m", "valid_time", "finish_time_seconds"]
    for name, (time_col, status_col, _) in TIME_FIELDS.items():
        source_time_cols.extend([time_col, status_col, f"{name}_time_selected_positive"])
    source_section_rows = reference_intervals.loc[reference_intervals.api_record_id.isin(source_ids)].copy()
    slot_base = target_slots.merge(
        source_section_rows[["api_record_id", "race_id", "race_date", "race_distance_m", "valid_time"] +
            [c for seg in SEGMENTS for c in (f"{seg}_raw_delta_seconds", f"{seg}_feature_seconds", f"{seg}_feature_eligible", f"{seg}_quality_eligible", f"{seg}_nominal_length_m")]],
        left_on="source_api_record_id", right_on="api_record_id", how="left", validate="many_to_one", suffixes=("", "_source"),
    )
    assert slot_base.api_record_id.notna().all()
    assert slot_base.race_id.astype(str).eq(slot_base.source_race_id.astype(str)).all()
    assert slot_base.race_date.astype(str).eq(slot_base.source_race_date.astype(str)).all()
    assert slot_base.race_distance_m.astype(int).eq(slot_base.source_distance_m.astype(int)).all()
    relative_rows = []
    benchmark_index = source_event_benchmarks.set_index(["source_race_id", "segment_id"], drop=False)
    for row in slot_base.itertuples(index=False):
        for segment_id in SEGMENTS:
            b = benchmark_index.loc[(str(row.source_race_id), segment_id)]
            if isinstance(b, pd.DataFrame):
                raise AssertionError("duplicate source event benchmark stats")
            feature_ok = bool(getattr(row, f"{segment_id}_feature_eligible"))
            benchmark_exists = bool(b.benchmark_exists)
            raw_seconds = getattr(row, f"{segment_id}_raw_delta_seconds")
            benchmark_seconds = b.mean_of_prior_race_medians_seconds
            relative_ok = feature_ok and benchmark_exists and not pd.isna(raw_seconds)
            relative_rows.append({
                "target_api_record_id": int(row.target_api_record_id),
                "slot_oldest_to_newest": int(row.slot_oldest_to_newest),
                "source_api_record_id": int(row.source_api_record_id),
                "source_race_id": str(row.source_race_id), "source_race_date": str(row.source_race_date),
                "target_cutoff": str(row.target_cutoff), "target_distance_m": int(row.target_distance_m),
                "source_distance_m": int(row.source_distance_m), "segment_id": segment_id,
                "nominal_length_m": int(getattr(row, f"{segment_id}_nominal_length_m")),
                "raw_delta_seconds": None if pd.isna(raw_seconds) else float(raw_seconds),
                "feature_seconds": None if pd.isna(getattr(row, f"{segment_id}_feature_seconds")) else float(getattr(row, f"{segment_id}_feature_seconds")),
                "feature_eligible": feature_ok,
                "prior_reference_cutoff_t_minus_2": str(b.reference_cutoff_t_minus_2),
                "prior_eligible_race_n": int(b.prior_eligible_race_n),
                "reference_first_race_date": b.reference_first_race_date,
                "reference_last_race_date": b.reference_last_race_date,
                "minimum_prior_eligible_races": MIN_REFERENCE_RACES,
                "benchmark_exists": benchmark_exists,
                "mean_of_prior_race_medians_seconds": None if pd.isna(benchmark_seconds) else float(benchmark_seconds),
                "relative_performance_seconds": (
                    float(benchmark_seconds) - float(raw_seconds) if relative_ok else None
                ),
                "relative_performance_eligible": bool(relative_ok),
                "relative_null_reason": (
                    None if relative_ok else ("source_interval_ineligible" if not feature_ok else "fewer_than_20_prior_reference_races")
                ),
            })
    target_last5_relative = pd.DataFrame(relative_rows)
    # Correctly link target race IDs from the saved target roster without altering lineage.
    target_race_lookup = targets.set_index("api_record_id").race_id.astype(str).to_dict()
    target_last5_relative["target_race_id"] = target_last5_relative.target_api_record_id.map(target_race_lookup)
    assert len(target_last5_relative) == len(target_slots) * len(SEGMENTS)

    after_fp = source_fingerprints(fingerprint_ids)
    assert set(after_fp.api_record_id.astype("int64")) == fingerprint_ids
    before = before_fp.rename(columns={
        "source_artifact_id": "before_source_artifact_id", "record_type": "before_record_type",
        "payload_sha256": "before_payload_sha256", "source_page_sha256": "before_source_page_sha256",
        "source_page_path": "before_source_page_path", "source_row_fingerprint_sha256": "before_source_row_fingerprint_sha256",
    })
    after = after_fp.rename(columns={
        "source_artifact_id": "after_source_artifact_id", "record_type": "after_record_type",
        "payload_sha256": "after_payload_sha256", "source_page_sha256": "after_source_page_sha256",
        "source_page_path": "after_source_page_path", "source_row_fingerprint_sha256": "after_source_row_fingerprint_sha256",
    })
    compare = before.merge(after, on="api_record_id", how="outer", validate="one_to_one")
    view_fp = quality[["api_record_id", "api4_3_payload_sha256", "api4_3_source_artifact_id", "api4_3_source_page_sha256", "api4_3_source_page_path"]]
    compare = compare.merge(view_fp, on="api_record_id", how="left", validate="one_to_one")
    compare["quality_view_scoped_query_member"] = compare.api_record_id.astype("int64").isin(quality_ids)
    compare["quality_view_row_returned"] = compare.quality_view_scoped_query_member & compare.api4_3_payload_sha256.notna()
    compare["before_after_fingerprint_equal"] = compare.before_source_row_fingerprint_sha256.eq(compare.after_source_row_fingerprint_sha256)
    compare["source_record_type_equal_before_after"] = compare.before_record_type.eq(compare.after_record_type)
    compare["source_page_path_equal_before_after"] = compare.before_source_page_path.eq(compare.after_source_page_path)
    compare["source_artifact_equal_before_after"] = compare.before_source_artifact_id.eq(compare.after_source_artifact_id)
    compare["quality_view_source_fingerprint_matches_before"] = compare.apply(
        lambda r: pd.isna(r.api4_3_payload_sha256) or (
            str(r.api4_3_payload_sha256) == str(r.before_payload_sha256)
            and int(r.api4_3_source_artifact_id) == int(r.before_source_artifact_id)
            and str(r.api4_3_source_page_sha256) == str(r.before_source_page_sha256)
            and str(r.api4_3_source_page_path) == str(r.before_source_page_path)
        ), axis=1,
    )
    compare["quality_view_source_fingerprint_matches_after"] = compare.apply(
        lambda r: pd.isna(r.api4_3_payload_sha256) or (
            str(r.api4_3_payload_sha256) == str(r.after_payload_sha256)
            and int(r.api4_3_source_artifact_id) == int(r.after_source_artifact_id)
            and str(r.api4_3_source_page_sha256) == str(r.after_source_page_sha256)
            and str(r.api4_3_source_page_path) == str(r.after_source_page_path)
        ), axis=1,
    )
    assert compare.before_after_fingerprint_equal.all()
    assert compare.source_record_type_equal_before_after.all()
    assert compare.source_page_path_equal_before_after.all()
    assert compare.source_artifact_equal_before_after.all()
    assert compare.quality_view_source_fingerprint_matches_before.all()
    assert compare.quality_view_source_fingerprint_matches_after.all()

    target_roster = targets[[
        "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number", "finish_position",
        "distance_m", "history_cutoff", "last5_same_source_ids",
    ]].copy()
    target_roster["target_distance_cohort"] = target_roster.distance_m.astype(int)
    target_lineage = target_slots.copy()
    target_lineage["target_api_record_id"] = target_lineage.target_api_record_id.astype("int64")
    target_lineage["source_api_record_id"] = target_lineage.source_api_record_id.astype("int64")

    nominal_contract = pd.DataFrame([
        {"race_distance_m": d, "segment_id": seg, "nominal_length_m": NOMINAL_LENGTHS[d][i],
         "formula": SEGMENTS[seg]["formula"], "nominal_basis": "user_authorized_nominal_distance_assumption",
         "raw_seconds_scaled": False}
        for d in DISTANCES for i, seg in enumerate(SEGMENTS)
    ])
    assert nominal_contract.groupby("race_distance_m").nominal_length_m.sum().to_dict() == {d: d for d in DISTANCES}

    outputs = {
        "target_f1_style6_features.parquet": style,
        "target_distance_roster.parquet": target_roster,
        "target_last5_lineage.parquet": target_lineage,
        "benchmark_reference_roster.parquet": reference_roster,
        "candidate_race_roster_reconciliation.parquet": roster_reconciliation,
        "mask_only_current_db_rows.parquet": mask_only_db_rows,
        "api4_quality_source_snapshot.parquet": quality,
        "source_race_point_quality_masks.parquet": point_masks,
        "source_point_order_status_evidence.parquet": order_values,
        "source_point_group_status_evidence.parquet": group_values,
        "reference_section_intervals.parquet": reference_intervals,
        "reference_race_segment_medians.parquet": reference_race_medians,
        "source_event_benchmark_stats.parquet": source_event_benchmarks,
        "target_last5_relative_history.parquet": target_last5_relative,
        "source_fingerprint_before_after.parquet": compare,
        "section_time_reviews.parquet": review_rows,
        "nominal_segment_contract.csv": nominal_contract,
    }
    for name, frame in outputs.items():
        path = HERE / name
        if path.exists():
            raise FileExistsError(path)
        if name.endswith(".csv"):
            frame.to_csv(path, index=False)
        else:
            frame.to_parquet(path, index=False)

    by_distance = {}
    for d in DISTANCES:
        tx = targets.loc[targets.distance_m.astype(int).eq(d)]
        lx = target_slots.loc[target_slots.target_distance_m.astype(int).eq(d)]
        rx = candidate_started.loc[candidate_started.race_distance_m.astype(int).eq(d)]
        by_distance[str(d)] = {
            "target_rows": int(len(tx)), "target_races": int(tx.race_id.nunique()),
            "target_date_min": str(tx.race_date.min()), "target_date_max": str(tx.race_date.max()),
            "saved_last5_slots": int(len(lx)), "targets_with_slots": int(lx.target_api_record_id.nunique()),
            "unique_source_records": int(lx.source_api_record_id.nunique()),
            "unique_source_races": int(lx.source_race_id.nunique()),
            "source_slot_date_min": str(lx.source_race_date.min()), "source_slot_date_max": str(lx.source_race_date.max()),
            "reference_roster_started_rows": int(len(rx)), "reference_roster_races": int(rx.race_id.nunique()),
            "reference_roster_date_min": str(rx.race_date.min()), "reference_roster_date_max": str(rx.race_date.max()),
            "reference_roster_rows_by_year": {str(y): int(n) for y, n in rx.groupby(rx.race_date.str[:4]).size().items()},
            "reference_roster_races_by_year": {
                str(y): int(n) for y, n in rx.drop_duplicates("race_id").groupby(rx.drop_duplicates("race_id").race_date.str[:4]).size().items()
            },
            "relative_slot_rows_eligible": int(target_last5_relative.loc[
                target_last5_relative.target_distance_m.astype(int).eq(d), "relative_performance_eligible"
            ].sum()),
        }
    status_domains = {}
    for column in [
        "s1f_time_status", "c3_time_status", "c4_time_status", "g3f_time_status", "g1f_time_status",
        "s1f_order_status", "c3_order_status", "c4_order_status", "g1f_order_status",
        "s1f_group_status", "c3_group_status", "c4_group_status", "g1f_group_status",
    ]:
        status_domains[column] = {str(k): int(v) for k, v in quality[column].fillna("<NULL>").value_counts().items()}

    input_paths = [F1_FEATURES, F1_LINEAGE, STYLE_FEATURES, BASELINE_SOURCE]
    input_manifest = {p.name: file_entry(p) for p in input_paths}
    audit = {
        "audit_status": "read_only_distance_specific_source_snapshot_complete",
        "model_fit_or_score_computed": False,
        "database_access": {
            "uri_mode": "ro", "sqlite_query_only": True,
            "quality_view": "jeju_race_postrace_sections_quality_2026", "quality_view_scan_count": 1,
            "quality_view_sql_sha256": view_sql_sha256, "snapshot_data_version": data_version_at_snapshot,
            "whole_database_hash_claimed_unchanged": False,
            "api4_fingerprint_scope": "all rows in candidate benchmark reference races plus all 52,155 F1 targets",
            "api4_source_fingerprints_equal_before_after": bool(compare.before_after_fingerprint_equal.all()),
            "quality_view_fingerprints_match_before_after": bool(compare.quality_view_source_fingerprint_matches_before.all() and compare.quality_view_source_fingerprint_matches_after.all()),
        },
        "inputs": input_manifest,
        "contract": {
            "target_population": "all saved F1_STYLE6 rows, 52,155. The frozen upstream population already omits known-excluded horse 3005648; this audit applies no additional horse filter.",
            "saved_last5_lineage": "exact saved last5_same_source_ids and last5_same_distance_start rows; retain invalid slots; T-2 inclusive; no reselect/backfill",
            "reference_roster": "all started rows in frozen baseline source snapshot, meet_code=2, distances 900/1000/1110/1200, all dates in the snapshot. Known-excluded horse 3005648 is absent from the frozen baseline and current mask roster; no additional filter is applied.",
            "reference_source_snapshot_date_range": [str(baseline.race_date.min()), str(baseline.race_date.max())],
            "intervals": SEGMENTS,
            "nominal_lengths_by_distance": NOMINAL_LENGTHS,
            "nominal_lengths_are_assumptions": True,
            "raw_times_unchanged": True,
            "reference_race_median_rule": "for each source event s and section, same-distance eligible prior race medians dated <= s race date minus two days; equal weight per eligible race; minimum 20 distinct races required; no current/future source race",
            "reference_median_row_rule": "median over feature-eligible rows in the fixed frozen reference roster for that race and interval; race contributes one median regardless of eligible runner count. Seven old races have partial frozen roster coverage; their medians are snapshot-subset medians, not full-field medians, and are flagged.",
            "quality_time_rule": f"selected positive field time and status in {sorted(GOOD_TIME_STATUS)}; positive finite segment delta; valid_time=True for reference/slot contributions",
            "point_mask_rule": "full current DB started-roster exact API4 point ID/horse ID/program number coverage, race-consistent selected API303 record, exactly one selected API303 point row, fingerprint and quality status parity; unknown/missing/held values fail closed using inherited 1000m source-audit gate. Current DB-only rows are included for masks only and excluded from frozen reference medians.",
            "api6_used": False,
            "minimum_prior_races": MIN_REFERENCE_RACES,
            "relative_sign": "benchmark mean of prior race medians minus actual source interval seconds; positive means faster than historical same-distance/section benchmark",
        },
        "counts": {
            "baseline_f1_style6_rows": int(len(style)), "baseline_f1_style6_unique_api_record_ids": int(style.api_record_id.nunique()),
            "target_rows_4_distances": int(len(targets)), "target_races_4_distances": int(targets.race_id.nunique()),
            "target_rows_by_distance": by_distance,
            "exact_last5_slots": int(len(target_slots)), "targets_with_any_saved_slot": int(target_slots.target_api_record_id.nunique()),
            "distinct_history_source_api_records": int(target_slots.source_api_record_id.nunique()),
            "benchmark_reference_started_rows": int(len(candidate_started)), "benchmark_reference_races": int(len(candidate_race_ids)),
            "benchmark_reference_date_min": str(candidate_started.race_date.min()), "benchmark_reference_date_max": str(candidate_started.race_date.max()),
            "full_candidate_event_rows_reconciled": int(len(db_roster)), "full_started_roster_rows_reconciled": int(len(db_started)),
            "frozen_snapshot_partial_roster_race_n": int(len(partial_frozen_races)),
            "frozen_snapshot_partial_roster_races": partial_frozen_races[["race_id", "race_date", "race_distance_m", "frozen_reference_started_rows", "current_db_started_rows"]].to_dict("records"),
            "current_db_mask_only_rows": int(len(mask_only_db_rows)),
            "known_excluded_horse_3005648_absent_from_saved_f1_style6": True,
            "known_excluded_horse_3005648_absent_from_frozen_reference_roster": True,
            "known_excluded_horse_3005648_absent_from_current_full_race_mask_roster": True,
            "api4_quality_view_rows": int(len(quality)),
            "quality_view_missing_full_race_starter_rows": int(len(quality_missing_current_starters)),
            "quality_view_missing_full_race_starter_ids": sorted(map(int, quality_missing_current_starters)),
            "quality_view_scoped_expected_rows": int(compare.quality_view_scoped_query_member.sum()),
            "quality_view_scoped_returned_rows": int(compare.quality_view_row_returned.sum()),
            "scoped_api4_fingerprint_rows": int(len(compare)),
            "point_masks_total": int(len(point_masks)), "point_masks_clear": int(point_masks.point_clear_full_race.sum()),
            "point_masks_by_point": {
                p: {"races": int(g.race_id.nunique()), "clear": int(g.point_clear_full_race.sum()), "blocked": int((~g.point_clear_full_race).sum())}
                for p, g in point_masks.groupby("point", sort=True)
            },
            "reference_interval_feature_eligible_by_segment": {
                seg: int(reference_intervals[f"{seg}_feature_eligible"].sum()) for seg in SEGMENTS
            },
            "reference_race_segment_medians_eligible": int(reference_race_medians.reference_race_eligible.sum()),
            "source_event_benchmarks_exists_by_segment": {
                seg: int(source_event_benchmarks.loc[source_event_benchmarks.segment_id.eq(seg), "benchmark_exists"].sum()) for seg in SEGMENTS
            },
            "target_last5_relative_rows": int(len(target_last5_relative)),
            "target_last5_relative_eligible": int(target_last5_relative.relative_performance_eligible.sum()),
            "target_last5_relative_null_reasons": {str(k): int(v) for k, v in target_last5_relative.relative_null_reason.fillna("<NULL>").value_counts().items()},
            "status_domains": status_domains,
        },
        "outputs": {},
    }
    for name, frame in outputs.items():
        path = HERE / name
        audit["outputs"][name] = {"rows": int(len(frame)), "bytes": int(path.stat().st_size), "sha256": file_sha256(path)}
    audit_path = HERE / "source_audit.json"
    with audit_path.open("x", encoding="utf-8") as stream:
        json.dump(audit, stream, ensure_ascii=False, indent=2, allow_nan=False, default=canonical)
        stream.write("\n")
    manifest = {
        "manifest_status": "frozen_read_only_distance_section_source_snapshot",
        "audit_json": "source_audit.json",
        "audit_json_sha256": file_sha256(audit_path),
        "inputs": input_manifest,
        "outputs": audit["outputs"],
    }
    with (HERE / "artifact_manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False, default=canonical))


if __name__ == "__main__":
    main()
