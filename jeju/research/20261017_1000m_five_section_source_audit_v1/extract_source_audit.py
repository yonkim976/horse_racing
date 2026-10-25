"""Pin saved-F1 1000 m targets and their exact last-five API4 sources.

The main database is opened with SQLite URI mode=ro. A single transaction
reads the quality view for the selected target/source IDs; before/after source
fingerprints use indexed base-table lookups only. This script does no fitting.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
F1_FEATURES = ROOT / "jeju/research/20261009_finish_history_ablation_v1/outputs/features.parquet"
F1_LINEAGE = ROOT / "jeju/research/20261009_finish_history_ablation_v1/outputs/historical_lineage.parquet"
BASELINE_SOURCE = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet"
CUTOFF = "2026-09-19"
EXCLUDED_HORSE_ID = "3005648"
GOOD_TIME_STATUS = {"api_positive_unreviewed", "website_corrected"}
POINT_HOLD_TOKENS = ("conflict", "unresolved", "not_applied", "source_changed")
ORDER_FIELDS = {
    "s1f": "sjS1fOrd", "c3": "sj_3cOrd", "c4": "sj_4cOrd", "g1f": "sjG1fOrd",
}
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
ORDER_FAILURE_TOKENS = ("conflict", "not_applied", "source_changed")

QUALITY_COLUMNS = [
    "api_record_id", "race_date", "meet_code", "race_number", "horse_number",
    "horse_id", "horse_name", "race_distance_m", "finish_position",
    "finish_status_raw", "finish_time_seconds",
    "api4_3_sjS1fOrd_raw", "api4_3_sjS1fOrd_json_type",
    "api4_3_sj_3cOrd_raw", "api4_3_sj_3cOrd_json_type",
    "api4_3_sj_4cOrd_raw", "api4_3_sj_4cOrd_json_type",
    "api4_3_sjG1fOrd_raw", "api4_3_sjG1fOrd_json_type",
    "api4_3_payload_sha256", "api4_3_source_artifact_id",
    "api4_3_source_page_sha256", "api4_3_source_page_path",
    "api303_api_record_id", "api303_payload_sha256",
    "api303_source_artifact_id", "api303_source_page_sha256",
    "api303_source_page_path",
    "s1f_time_seconds", "s1f_time_status", "c3_time_seconds", "c3_time_status",
    "c4_time_seconds", "c4_time_status", "g3f_time_seconds", "g3f_time_status",
    "g1f_time_seconds", "g1f_time_status",
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
    "seg_0_200": "s1f",
    "seg_200_to_c3_approx400": "c3_minus_s1f",
    "seg_c3_approx400_to_c4_approx600": "c4_minus_c3",
    "seg_c4_approx600_to_800": "finish_minus_g1f_minus_c4",
    "seg_800_to_1000": "g1f",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


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


def row_hash(row, columns) -> str:
    payload = {column: canonical(row[column]) for column in columns}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def open_readonly_with_ids(ids, race_keys=()):
    connection = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA temp_store=MEMORY")
    # A connection-local TEMP table avoids bind-variable limits; mode=ro keeps
    # the actual project database immutable. Load it before query_only is set.
    connection.execute("CREATE TEMP TABLE audit_ids (api_record_id INTEGER PRIMARY KEY)")
    connection.executemany(
        "INSERT INTO audit_ids(api_record_id) VALUES (?)",
        [(int(value),) for value in sorted(set(ids))],
    )
    connection.execute(
        "CREATE TEMP TABLE audit_races (race_date TEXT, meet_code INTEGER, race_number INTEGER, "
        "PRIMARY KEY(race_date, meet_code, race_number))"
    )
    connection.executemany(
        "INSERT INTO audit_races(race_date,meet_code,race_number) VALUES (?,?,?)",
        sorted(set((str(d), int(m), int(r)) for d, m, r in race_keys)),
    )
    connection.commit()  # commits connection-local TEMP rows only; main DB is URI mode=ro
    connection.execute("PRAGMA query_only=ON")
    assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
    connection.execute("BEGIN")
    # First main-database read pins the transaction snapshot.
    connection.execute("SELECT api_record_id FROM api_records ORDER BY api_record_id LIMIT 1").fetchone()
    return connection


def source_fingerprints(ids):
    connection = open_readonly_with_ids(ids)
    try:
        frame = pd.read_sql_query(
            "SELECT a.api_record_id, a.source_artifact_id, a.record_type, a.payload_sha256, "
            "s.sha256 AS source_page_sha256, s.raw_relative_path AS source_page_path "
            "FROM api_records a JOIN source_artifacts s USING(source_artifact_id) "
            "JOIN audit_ids x USING(api_record_id) ORDER BY a.api_record_id",
            connection,
        )
        assert frame.api_record_id.is_unique
        frame["source_row_fingerprint_sha256"] = frame.apply(
            lambda row: row_hash(row, [
                "api_record_id", "source_artifact_id", "record_type", "payload_sha256",
                "source_page_sha256", "source_page_path",
            ]), axis=1,
        )
        return frame
    finally:
        connection.close()


def normalize_ids(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    if not isinstance(value, (list, tuple, np.ndarray)):
        raise AssertionError(f"unexpected saved last5 type: {type(value)!r}")
    return [int(x) for x in value]


def bool_status_hold(value):
    if value is None or pd.isna(value):
        return False
    text = str(value).lower()
    return any(token in text for token in POINT_HOLD_TOKENS)


def point_status_failed(value, allowed):
    if value is None or pd.isna(value):
        return True
    text = str(value)
    return text not in allowed or any(token in text.lower() for token in ORDER_FAILURE_TOKENS)


def positive_time(value, status):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0 and str(status) in GOOD_TIME_STATUS


def inherited_started(finish_position):
    """Use the F1 source-audit starter definition without reclassifying codes."""
    try:
        value = int(finish_position)
    except (TypeError, ValueError):
        return False
    return (1 <= value <= 89) or value in {91, 92}


def main():
    for path in (F1_FEATURES, F1_LINEAGE, BASELINE_SOURCE, DB):
        if not path.is_file():
            raise FileNotFoundError(path)

    features = pd.read_parquet(F1_FEATURES)
    lineage = pd.read_parquet(F1_LINEAGE)
    baseline = pd.read_parquet(BASELINE_SOURCE)
    assert features.api_record_id.is_unique and baseline.api_record_id.is_unique
    targets = features.loc[
        pd.to_numeric(features.distance_m, errors="coerce").eq(1000)
        & features.race_date.astype(str).le(CUTOFF)
        & features.horse_id.astype(str).ne(EXCLUDED_HORSE_ID)
    ].copy()
    targets = targets.sort_values(["race_date", "race_id", "horse_number"], kind="stable")
    target_ids = set(targets.api_record_id.astype("int64"))
    target_slots = lineage.loc[
        lineage.history_kind.eq("last5_same_distance_start")
        & lineage.target_api_record_id.isin(target_ids)
    ].copy()
    target_slots = target_slots.sort_values(
        ["target_api_record_id", "slot_oldest_to_newest"], kind="stable"
    ).reset_index(drop=True)

    date_delta = pd.to_datetime(targets.race_date.astype(str)) - pd.to_timedelta(2, unit="D")
    expected_cutoff = date_delta.dt.strftime("%Y-%m-%d").reset_index(drop=True)
    actual_cutoff = targets.history_cutoff.astype(str).reset_index(drop=True)
    assert actual_cutoff.equals(expected_cutoff), "saved target history_cutoff is not exact race-date T-2"

    # Reconfirm the exact saved F1 last5 list, target identity, T-2 cutoff,
    # exact distance, started status, and baseline validity field.
    lineage_ids = {
        int(target_id): [int(x) for x in group.sort_values("slot_oldest_to_newest").source_api_record_id]
        for target_id, group in target_slots.groupby("target_api_record_id", sort=False)
    }
    for row in targets[["api_record_id", "last5_same_source_ids"]].itertuples(index=False):
        assert normalize_ids(row.last5_same_source_ids) == lineage_ids.get(int(row.api_record_id), [])
    assert target_slots.slot_oldest_to_newest.notna().all()
    assert target_slots.source_started.eq(True).all()
    assert target_slots.target_horse_id.astype(str).eq(target_slots.source_horse_id.astype(str)).all()
    assert target_slots.target_distance_m.astype(int).eq(1000).all()
    assert target_slots.source_distance_m.astype(int).eq(1000).all()
    assert target_slots.source_race_date.astype(str).le(target_slots.target_cutoff.astype(str)).all()
    assert target_slots.groupby("target_api_record_id").slot_oldest_to_newest.apply(
        lambda values: values.astype(int).tolist() == list(range(1, len(values) + 1))
    ).all()

    baseline_index = baseline.set_index("api_record_id", drop=False)
    source_ids = set(target_slots.source_api_record_id.astype("int64"))
    needed_ids = target_ids | source_ids
    assert source_ids.issubset(set(baseline_index.index.astype("int64")))

    source_race_ids = set(target_slots.source_race_id.astype(str))
    full_source_race_rows = baseline.loc[baseline.race_id.astype(str).isin(source_race_ids)].copy()
    assert full_source_race_rows.race_id.nunique() == len(source_race_ids)
    full_source_event_ids = set(full_source_race_rows.api_record_id.astype("int64"))
    full_source_started_rows = full_source_race_rows.loc[full_source_race_rows.started.astype(bool)].copy()
    full_source_started_ids = set(full_source_started_rows.api_record_id.astype("int64"))
    assert pd.to_numeric(full_source_race_rows.race_distance_m, errors="coerce").eq(1000).all()
    assert full_source_started_rows[["api_record_id", "horse_id", "horse_number"]].notna().all().all()
    assert not full_source_started_rows.duplicated(["race_id", "api_record_id"]).any()
    assert not full_source_started_rows.duplicated(["race_id", "horse_id"]).any()
    assert not full_source_started_rows.duplicated(["race_id", "horse_number"]).any()
    # The quality view includes every exact started row in the source race
    # roster, so selected API303 provenance can be checked race-wide.
    quality_ids = needed_ids | full_source_started_ids
    selected_baseline = baseline_index.loc[sorted(quality_ids)].copy().reset_index(drop=True)
    selected_baseline["api_record_id"] = selected_baseline.api_record_id.astype("int64")
    fingerprint_ids = needed_ids | full_source_event_ids
    race_info = full_source_race_rows[[
        "race_id", "race_date", "meet_code", "race_number",
    ]].drop_duplicates()
    assert race_info.race_id.is_unique
    source_race_keys = list(race_info[["race_date", "meet_code", "race_number"]].itertuples(index=False, name=None))
    expected_ids_by_race = {
        str(race_id): set(group.api_record_id.astype("int64"))
        for race_id, group in full_source_started_rows.groupby("race_id", sort=False)
    }

    target_roster = targets[[
        "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
        "finish_position", "distance_m", "history_cutoff", "last5_same_source_ids",
    ]].copy()
    target_roster["api_record_id"] = target_roster.api_record_id.astype("int64")
    target_roster["source_row_role"] = "target"

    lineage_out = target_slots[[
        "target_api_record_id", "slot_oldest_to_newest", "source_api_record_id",
        "source_race_id", "source_race_date", "target_cutoff", "target_horse_id",
        "source_horse_id", "target_distance_m", "source_distance_m", "source_started",
        "starter_n", "event_rank_sequence_complete", "duplicate_horse_in_source_event",
        "raw_finish_position", "valid_individual_rank", "individual_top3",
    ]].copy()
    lineage_out["target_api_record_id"] = lineage_out.target_api_record_id.astype("int64")
    lineage_out["source_api_record_id"] = lineage_out.source_api_record_id.astype("int64")

    before_fp = source_fingerprints(fingerprint_ids)
    assert set(before_fp.api_record_id.astype("int64")) == fingerprint_ids

    connection = open_readonly_with_ids(quality_ids, source_race_keys)
    try:
        data_version_at_snapshot = int(connection.execute("PRAGMA data_version").fetchone()[0])
        db_roster = pd.read_sql_query(
            "SELECT r.api_record_id, r.race_date, r.meet_code, r.race_number, "
            "r.horse_number, r.horse_id, r.finish_position "
            "FROM race_result_rows r JOIN audit_races k "
            "USING(race_date,meet_code,race_number) "
            "ORDER BY r.race_date,r.meet_code,r.race_number,r.horse_number,r.api_record_id",
            connection,
        )
        db_roster["api_record_id"] = db_roster.api_record_id.astype("int64")
        db_roster["race_id"] = (
            db_roster.race_date.astype(str) + "_"
            + db_roster.meet_code.astype("Int64").astype(str) + "_"
            + db_roster.race_number.astype("Int64").astype(str)
        )
        db_roster["started"] = db_roster.finish_position.map(inherited_started)
        db_started = db_roster.loc[db_roster.started].copy()
        baseline_started = full_source_race_rows.loc[full_source_race_rows.started.astype(bool)].copy()
        assert db_roster.api_record_id.is_unique
        assert db_started.api_record_id.is_unique
        assert db_started[["api_record_id", "horse_id", "horse_number"]].notna().all().all()
        assert not db_started.duplicated(["race_id", "api_record_id"]).any()
        assert not db_started.duplicated(["race_id", "horse_id"]).any()
        assert not db_started.duplicated(["race_id", "horse_number"]).any()
        assert set(db_roster.api_record_id.astype("int64")) == full_source_event_ids, (
            "baseline full candidate race rows do not exactly match current race_result_rows"
        )
        assert set(db_started.api_record_id.astype("int64")) == full_source_started_ids, (
            "baseline started roster does not exactly match current race_result_rows"
        )
        for race_id in sorted(source_race_ids):
            b = baseline_started.loc[baseline_started.race_id.astype(str).eq(race_id)].copy()
            d = db_started.loc[db_started.race_id.astype(str).eq(race_id)].copy()
            assert set(b.api_record_id.astype("int64")) == set(d.api_record_id.astype("int64"))
            assert b.api_record_id.is_unique and d.api_record_id.is_unique
            b = b.set_index("api_record_id").sort_index()
            d = d.set_index("api_record_id").sort_index()
            assert b.horse_id.astype(str).equals(d.horse_id.astype(str))
            assert pd.to_numeric(b.horse_number, errors="coerce").equals(
                pd.to_numeric(d.horse_number, errors="coerce")
            )
        select_sql = (
            "SELECT " + ", ".join(f"q.{column}" for column in QUALITY_COLUMNS)
            + " FROM jeju_race_postrace_sections_quality_2026 q "
            + "JOIN audit_ids x ON x.api_record_id=q.api_record_id "
            + "ORDER BY q.api_record_id"
        )
        quality = pd.read_sql_query(select_sql, connection)
        assert quality.api_record_id.is_unique
        assert set(quality.api_record_id.astype("int64")) == quality_ids
        time_marks = ",".join("?" for _ in TIME_FIELDS)
        review_rows = pd.read_sql_query(
            "SELECT r.api_record_id, r.field_name, r.review_status, r.api_seconds_at_review, "
            "r.api_payload_sha256_at_review, r.website_display, r.website_seconds, "
            "r.effective_seconds, r.website_url, r.checked_date_kst, r.evidence_relative_path, "
            "r.evidence_sha256, r.decision_reason, r.applied_at_utc "
            "FROM race_section_time_reviews r JOIN audit_ids x USING(api_record_id) "
            f"WHERE r.field_name IN ({time_marks}) ORDER BY r.api_record_id, r.field_name",
            connection, params=[item[2] for item in TIME_FIELDS.values()],
        )
        order_marks = ",".join("?" for _ in ORDER_FIELDS)
        order_values = pd.read_sql_query(
            "SELECT v.api_record_id, v.race_date, v.meet_code, v.race_number, "
            "v.horse_number, v.horse_id, v.field_name, v.quality_order_value, "
            "v.quality_order_status, v.api_payload_sha256, v.api_source_artifact_id, "
            "v.api_source_page_sha256, v.api_source_page_path "
            "FROM jeju_race_section_order_quality_values v "
            "JOIN audit_races r USING(race_date,meet_code,race_number) "
            f"WHERE v.field_name IN ({order_marks}) "
            "ORDER BY v.race_date,v.meet_code,v.race_number,v.field_name,v.horse_number,v.horse_id",
            connection, params=list(ORDER_FIELDS.values()),
        )
        group_marks = ",".join("?" for _ in GROUP_POINTS)
        group_values = pd.read_sql_query(
            "SELECT v.api_record_id, a.source_artifact_id, a.record_type, "
            "v.race_date, v.meet_code, v.race_number, "
            "v.point, v.group_status, v.group_value, v.payload_sha256, "
            "v.source_page_sha256, v.raw_relative_path AS source_page_path "
            "FROM jeju_race_section_group_quality_values v "
            "JOIN api_records a USING(api_record_id) "
            "JOIN audit_races r USING(race_date,meet_code,race_number) "
            f"WHERE v.point IN ({group_marks}) "
            "ORDER BY v.race_date,v.meet_code,v.race_number,v.point,v.api_record_id",
            connection, params=list(GROUP_POINTS.values()),
        )
        view_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='view' "
            "AND name='jeju_race_postrace_sections_quality_2026'"
        ).fetchone()
        assert view_sql and view_sql[0]
        view_sql_sha256 = hashlib.sha256(view_sql[0].encode("utf-8")).hexdigest()
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
    finally:
        connection.close()

    after_fp = source_fingerprints(fingerprint_ids)
    assert set(after_fp.api_record_id.astype("int64")) == fingerprint_ids

    # All quality-view rows must map to the preserved baseline source row.
    quality = quality.merge(
        selected_baseline[[
            "api_record_id", "race_id", "race_distance_m", "started", "valid_time",
            "api4_3_payload_sha256", "finish_time_seconds",
        ]], on="api_record_id", how="left", validate="one_to_one", suffixes=("", "_baseline"),
    )
    assert quality.race_distance_m.astype(float).eq(quality.race_distance_m_baseline.astype(float)).all()
    assert quality.race_id.notna().all()
    assert quality.race_date.astype(str).eq(
        selected_baseline.set_index("api_record_id").loc[quality.api_record_id, "race_date"].astype(str).reset_index(drop=True)
    ).all()
    assert quality.race_id.astype(str).eq(
        selected_baseline.set_index("api_record_id").loc[quality.api_record_id, "race_id"].astype(str).reset_index(drop=True)
    ).all()
    assert quality.horse_id.astype(str).eq(
        selected_baseline.set_index("api_record_id").loc[quality.api_record_id, "horse_id"].astype(str).reset_index(drop=True)
    ).all()
    assert quality.horse_number.astype(int).eq(
        selected_baseline.set_index("api_record_id").loc[quality.api_record_id, "horse_number"].astype(int).reset_index(drop=True)
    ).all()
    assert np.array_equal(
        pd.to_numeric(quality.finish_time_seconds, errors="coerce").to_numpy(float),
        pd.to_numeric(
            selected_baseline.set_index("api_record_id").loc[quality.api_record_id, "finish_time_seconds"],
            errors="coerce",
        ).to_numpy(float),
        equal_nan=True,
    )
    assert quality.race_distance_m.astype(float).eq(1000).all()
    assert quality.started.astype(bool).equals(
        selected_baseline.set_index("api_record_id").loc[quality.api_record_id, "started"].astype(bool).reset_index(drop=True)
    )
    assert quality.api4_3_payload_sha256.astype(str).eq(
        quality.api4_3_payload_sha256_baseline.astype(str)
    ).all()
    assert quality.valid_time.astype(bool).equals(
        selected_baseline.set_index("api_record_id").loc[quality.api_record_id, "valid_time"].astype(bool).reset_index(drop=True)
    ), "baseline valid_time changed/misaligned for a quality snapshot row"

    # Build exact full-race point masks. The denominator is the exact started
    # roster reconciled to current race_result_rows, not the baseline candidate
    # row count. Both order IDs and horse identities must match that roster.
    order_values["race_id"] = (
        order_values.race_date.astype(str) + "_"
        + order_values.meet_code.astype("Int64").astype(str) + "_"
        + order_values.race_number.astype("Int64").astype(str)
    )
    group_values["race_id"] = (
        group_values.race_date.astype(str) + "_"
        + group_values.meet_code.astype("Int64").astype(str) + "_"
        + group_values.race_number.astype("Int64").astype(str)
    )
    assert not order_values.duplicated(["api_record_id", "field_name"]).any()
    order_values["api_record_id"] = pd.to_numeric(order_values.api_record_id, errors="raise").astype("int64")
    order_values["is_started_roster_member"] = order_values.api_record_id.isin(full_source_started_ids)
    group_values["api_record_id"] = pd.to_numeric(group_values.api_record_id, errors="raise").astype("int64")
    # API303 selection must be race-consistent over all started runners. The
    # group gate below then binds to exactly that selected API303 record.
    quality_index = quality.set_index("api_record_id", drop=False)
    quality_by_race = {
        race_id: quality_index.loc[
            sorted(expected_ids_by_race[race_id])
        ].copy()
        for race_id in source_race_ids
    }
    api303_selection = {}
    for race_id in sorted(source_race_ids):
        roster_q = quality_by_race[race_id]
        raw_ids = roster_q.api303_api_record_id
        null_n = int(raw_ids.isna().sum())
        unique_ids = sorted({int(value) for value in raw_ids.dropna()})
        consistent = null_n == 0 and len(unique_ids) == 1
        api303_selection[race_id] = {
            "api303_selected_record_id": unique_ids[0] if consistent else None,
            "api303_selection_consistent_across_started_roster": bool(consistent),
            "api303_selected_id_null_runner_n": null_n,
            "api303_distinct_selected_ids_n": len(unique_ids),
        }
    group_values["api303_selected_record_id"] = group_values.race_id.map(
        {race_id: item["api303_selected_record_id"] for race_id, item in api303_selection.items()}
    )
    group_values["is_started_roster_selected_api303_record"] = (
        group_values.api303_selected_record_id.notna()
        & group_values.api_record_id.eq(pd.to_numeric(group_values.api303_selected_record_id, errors="coerce"))
    )
    order_by_key = {
        key: group.copy()
        for key, group in order_values.groupby(["race_id", "field_name"], sort=False)
    }
    group_by_key = {
        key: group.copy()
        for key, group in group_values.groupby(["race_id", "point"], sort=False)
    }
    point_records = []
    for race_id in sorted(source_race_ids):
        expected_ids = expected_ids_by_race[race_id]
        expected_n = len(expected_ids)
        roster_b = baseline_started.loc[baseline_started.race_id.astype(str).eq(race_id)]
        expected_identity = {
            int(row.api_record_id): (str(row.horse_id), int(row.horse_number))
            for row in roster_b[["api_record_id", "horse_id", "horse_number"]].itertuples(index=False)
        }
        for point, field_name in ORDER_FIELDS.items():
            all_orders = order_by_key.get((race_id, field_name), order_values.iloc[0:0])
            orders = all_orders.loc[all_orders.api_record_id.isin(expected_ids)]
            groups = group_by_key.get((race_id, GROUP_POINTS[point]), group_values.iloc[0:0])
            selected_id = api303_selection[race_id]["api303_selected_record_id"]
            selected_groups = (
                groups.loc[groups.api_record_id.eq(selected_id)]
                if selected_id is not None else groups.iloc[0:0]
            )
            observed_ids = set(orders.api_record_id.astype("int64"))
            ids_equal = observed_ids == expected_ids and len(orders) == len(expected_ids)
            identity_equal = ids_equal and all(
                expected_identity.get(int(row.api_record_id)) == (str(row.horse_id), int(row.horse_number))
                for row in orders[["api_record_id", "horse_id", "horse_number"]].itertuples(index=False)
            )
            order_bad = orders.quality_order_status.apply(
                lambda value: point_status_failed(value, ORDER_STATUS_ALLOWED)
            )
            group_bad = selected_groups.group_status.apply(
                lambda value: point_status_failed(value, GROUP_STATUS_ALLOWED)
            )
            group_coverage_exact = len(selected_groups) == 1
            group_view_fingerprint_matches = False
            group_quality_status_matches = False
            if group_coverage_exact:
                selected_group = selected_groups.iloc[0]
                roster_quality = quality_by_race[race_id]
                q_status_column = POINT_STATUS_COLS[point][1]
                q_statuses = set(
                    "<NULL>" if pd.isna(v) else str(v)
                    for v in roster_quality[q_status_column]
                )
                selected_status = "<NULL>" if pd.isna(selected_group.group_status) else str(selected_group.group_status)
                group_quality_status_matches = q_statuses == {selected_status}
                qrow = roster_quality.iloc[0]
                source_fingerprint_pairs = [
                    (selected_group.payload_sha256, qrow.api303_payload_sha256),
                    (selected_group.source_artifact_id, qrow.api303_source_artifact_id),
                    (selected_group.source_page_sha256, qrow.api303_source_page_sha256),
                    (selected_group.source_page_path, qrow.api303_source_page_path),
                ]
                group_view_fingerprint_matches = bool(all(
                    not pd.isna(left) and not pd.isna(right) and str(left) == str(right)
                    for left, right in source_fingerprint_pairs
                ))
            order_coverage_complete = ids_equal and identity_equal
            group_coverage_present = group_coverage_exact
            point_records.append({
                "race_id": race_id, "point": point,
                "race_date": str(race_id.rsplit("_", 2)[0]),
                "expected_full_roster_runner_rows": expected_n,
                "observed_order_status_rows": int(len(orders)),
                "expected_started_api_record_ids_sha256": hashlib.sha256(
                    ",".join(str(x) for x in sorted(expected_ids)).encode("utf-8")
                ).hexdigest(),
                "observed_order_api_record_ids_sha256": hashlib.sha256(
                    ",".join(str(x) for x in sorted(observed_ids)).encode("utf-8")
                ).hexdigest(),
                "order_status_coverage_complete": bool(order_coverage_complete),
                "order_started_api_id_set_exact": bool(ids_equal),
                "order_started_horse_identity_exact": bool(identity_equal),
                "order_status_missing_or_unknown_or_hold_n": int(order_bad.sum()),
                "order_status_values": sorted({str(x) for x in orders.quality_order_status.dropna()}),
                "group_status_rows": int(len(groups)),
                "api303_selected_record_id": selected_id,
                "api303_selection_consistent_across_started_roster": api303_selection[race_id]["api303_selection_consistent_across_started_roster"],
                "api303_selected_id_null_runner_n": api303_selection[race_id]["api303_selected_id_null_runner_n"],
                "api303_distinct_selected_ids_n": api303_selection[race_id]["api303_distinct_selected_ids_n"],
                "group_selected_record_status_rows": int(len(selected_groups)),
                "group_status_coverage_present": bool(group_coverage_present),
                "group_status_missing_or_unknown_or_hold_n": int(group_bad.sum()),
                "group_status_values": sorted({str(x) for x in selected_groups.group_status.dropna()}),
                "group_selected_source_fingerprint_matches_quality_view": bool(group_view_fingerprint_matches),
                "group_quality_status_matches_quality_view": bool(group_quality_status_matches),
                "point_clear_full_race": bool(
                    order_coverage_complete and group_coverage_present
                    and api303_selection[race_id]["api303_selection_consistent_across_started_roster"]
                    and group_view_fingerprint_matches and group_quality_status_matches
                    and not order_bad.any() and not group_bad.any()
                ),
            })
    point_masks = pd.DataFrame(point_records)
    assert len(point_masks) == len(source_race_ids) * len(ORDER_FIELDS)
    point_masks["race_point_status_mask_sha256"] = point_masks.apply(
        lambda row: row_hash(row, [
            "race_id", "point", "expected_full_roster_runner_rows", "observed_order_status_rows",
            "expected_started_api_record_ids_sha256", "observed_order_api_record_ids_sha256",
            "order_status_coverage_complete", "order_started_api_id_set_exact",
            "order_started_horse_identity_exact", "order_status_missing_or_unknown_or_hold_n",
            "order_status_values", "group_status_rows", "api303_selected_record_id",
            "api303_selection_consistent_across_started_roster", "api303_selected_id_null_runner_n",
            "api303_distinct_selected_ids_n", "group_selected_record_status_rows",
            "group_status_coverage_present", "group_status_missing_or_unknown_or_hold_n",
            "group_status_values", "group_selected_source_fingerprint_matches_quality_view",
            "group_quality_status_matches_quality_view",
            "point_clear_full_race",
        ]), axis=1,
    )
    clear_wide = point_masks.pivot(
        index="race_id", columns="point", values="point_clear_full_race"
    ).rename(columns={point: f"{point}_point_clear_full_race" for point in ORDER_FIELDS})
    clear_wide = clear_wide.reset_index()
    assert np.array_equal(clear_wide.race_id.astype(str).to_numpy(), np.array(sorted(source_race_ids)))

    for name, (time_col, status_col, _) in TIME_FIELDS.items():
        quality[f"{name}_time_selected_positive"] = quality.apply(
            lambda row: positive_time(row[time_col], row[status_col]), axis=1
        )
    quality["finish_time_positive"] = pd.to_numeric(
        quality.finish_time_seconds, errors="coerce"
    ).gt(0)
    quality["finish_time_valid_baseline"] = quality.valid_time.astype(bool)
    quality["finish_time_feature_endpoint_eligible"] = (
        quality.finish_time_positive & quality.finish_time_valid_baseline
    )

    role = pd.Series(index=quality.index, dtype="object")
    role.loc[quality.api_record_id.astype("int64").isin(full_source_started_ids)] = "full_started_race_mask_roster"
    role.loc[quality.api_record_id.astype("int64").isin(target_ids)] = "target"
    role.loc[quality.api_record_id.astype("int64").isin(source_ids)] = "history_source"
    both = quality.api_record_id.astype("int64").isin(target_ids & source_ids)
    role.loc[both] = "target_and_history_source"
    quality.insert(0, "source_row_role", role)
    quality["source_row_fingerprint_sha256"] = quality.apply(
        lambda row: row_hash(row, QUALITY_COLUMNS), axis=1,
    )

    # Attach exact source record times and full-race point-status masks to the
    # saved target/slot lineage. No history IDs are chosen or backfilled here.
    slot_cols = lineage_out.copy()
    slot_cols = slot_cols.merge(
        quality[["api_record_id"] + [
            "race_id", "api4_3_payload_sha256", "api4_3_source_artifact_id", "api4_3_source_page_sha256",
            "api4_3_source_page_path", "api303_api_record_id", "api303_payload_sha256",
            "api303_source_artifact_id", "api303_source_page_sha256", "api303_source_page_path",
            "started", "valid_time", "finish_time_seconds",
            "s1f_time_seconds", "s1f_time_status", "c3_time_seconds", "c3_time_status",
            "c4_time_seconds", "c4_time_status", "g3f_time_seconds", "g3f_time_status",
            "g1f_time_seconds", "g1f_time_status", "s1f_order_status", "s1f_group_status",
            "c3_order_status", "c3_group_status", "c4_order_status", "c4_group_status",
            "g1f_order_status", "g1f_group_status", "s1f_time_selected_positive",
            "c3_time_selected_positive", "c4_time_selected_positive", "g3f_time_selected_positive",
            "g1f_time_selected_positive", "finish_time_positive", "finish_time_valid_baseline",
        ]].rename(columns={
            "api_record_id": "source_api_record_id", "race_id": "quality_source_race_id",
        }),
        on="source_api_record_id", how="left", validate="many_to_one",
    )
    assert slot_cols.api4_3_payload_sha256.notna().all()
    assert len(slot_cols) == len(target_slots)
    assert slot_cols.source_race_id.astype(str).eq(slot_cols.quality_source_race_id.astype(str)).all()
    slot_cols = slot_cols.merge(
        clear_wide.rename(columns={"race_id": "source_race_id"}),
        on="source_race_id", how="left", validate="many_to_one", indicator="full_race_point_mask_match",
    )
    assert slot_cols.full_race_point_mask_match.eq("both").all()
    for point in ORDER_FIELDS:
        slot_cols[f"{point}_point_clear_full_race"] = slot_cols[f"{point}_point_clear_full_race"].astype(bool)

    # The stored history feature is stricter than a raw measured difference:
    # each section endpoint must have a usable time, the whole source race-point
    # must pass its fail-closed order/group status mask, the delta must be >0,
    # and the baseline contract requires valid_time=True for every contribution.
    def add_segment(name, raw_values, endpoint_ok, point_names):
        raw_values = pd.to_numeric(raw_values, errors="coerce")
        slot_cols[f"{name}_raw_delta_seconds"] = raw_values
        measurement_ok = pd.Series(endpoint_ok, index=slot_cols.index).astype(bool)
        point_clear = pd.Series(True, index=slot_cols.index)
        for point in point_names:
            point_clear &= slot_cols[f"{point}_point_clear_full_race"]
        positive = raw_values.gt(0) & np.isfinite(raw_values)
        slot_cols[f"{name}_endpoint_measurement_eligible"] = measurement_ok
        slot_cols[f"{name}_point_quality_clear"] = point_clear
        slot_cols[f"{name}_quality_eligible"] = measurement_ok & point_clear & positive
        slot_cols[f"{name}_feature_eligible"] = (
            slot_cols[f"{name}_quality_eligible"] & slot_cols.valid_time.astype(bool)
        )
        slot_cols[f"{name}_feature_seconds"] = raw_values.where(slot_cols[f"{name}_feature_eligible"])

    add_segment("seg_0_200", slot_cols.s1f_time_seconds,
        slot_cols.s1f_time_selected_positive, ["s1f"])
    add_segment("seg_200_to_c3_approx400",
        pd.to_numeric(slot_cols.c3_time_seconds, errors="coerce")
        - pd.to_numeric(slot_cols.s1f_time_seconds, errors="coerce"),
        slot_cols.s1f_time_selected_positive & slot_cols.c3_time_selected_positive,
        ["s1f", "c3"])
    add_segment("seg_c3_approx400_to_c4_approx600",
        pd.to_numeric(slot_cols.c4_time_seconds, errors="coerce")
        - pd.to_numeric(slot_cols.c3_time_seconds, errors="coerce"),
        slot_cols.c3_time_selected_positive & slot_cols.c4_time_selected_positive,
        ["c3", "c4"])
    add_segment("seg_c4_approx600_to_800",
        pd.to_numeric(slot_cols.finish_time_seconds, errors="coerce")
        - pd.to_numeric(slot_cols.g1f_time_seconds, errors="coerce")
        - pd.to_numeric(slot_cols.c4_time_seconds, errors="coerce"),
        slot_cols.finish_time_positive & slot_cols.g1f_time_selected_positive
        & slot_cols.c4_time_selected_positive,
        ["c4", "g1f"])
    add_segment("seg_800_to_1000", slot_cols.g1f_time_seconds,
        slot_cols.g1f_time_selected_positive, ["g1f"])

    slot_cols["g3f_identity_residual_finish_minus_c3_minus_g3f"] = (
        pd.to_numeric(slot_cols.finish_time_seconds, errors="coerce")
        - pd.to_numeric(slot_cols.c3_time_seconds, errors="coerce")
        - pd.to_numeric(slot_cols.g3f_time_seconds, errors="coerce")
    )
    slot_cols["g3f_identity_diagnostic_eligible"] = (
        slot_cols.finish_time_positive & slot_cols.valid_time.astype(bool)
        & slot_cols.c3_time_selected_positive & slot_cols.g3f_time_selected_positive
        & slot_cols.c3_point_clear_full_race
    )
    slot_cols["g3f_identity_within_0_15s"] = (
        slot_cols.g3f_identity_diagnostic_eligible
        & slot_cols.g3f_identity_residual_finish_minus_c3_minus_g3f.abs().le(0.15)
    )
    slot_cols["five_sections_measurement_monotone"] = slot_cols[
        [f"{name}_quality_eligible" for name in SEGMENTS]
    ].all(axis=1)
    slot_cols["five_sections_feature_eligible_and_monotone"] = slot_cols[
        [f"{name}_feature_eligible" for name in SEGMENTS]
    ].all(axis=1)

    # Compare only source-payload fingerprints around the pinned quality-view
    # extraction. Quality/review values themselves remain the one transaction
    # snapshot captured above; whole-DB hashes are intentionally not claimed.
    fpcols = ["api_record_id", "source_artifact_id", "record_type", "payload_sha256", "source_page_sha256", "source_page_path"]
    before = before_fp.rename(columns={
        "source_artifact_id": "before_source_artifact_id", "record_type": "before_record_type",
        "payload_sha256": "before_payload_sha256", "source_page_sha256": "before_source_page_sha256",
        "source_page_path": "before_source_page_path",
        "source_row_fingerprint_sha256": "before_source_row_fingerprint_sha256",
    })
    after = after_fp.rename(columns={
        "source_artifact_id": "after_source_artifact_id", "record_type": "after_record_type",
        "payload_sha256": "after_payload_sha256", "source_page_sha256": "after_source_page_sha256",
        "source_page_path": "after_source_page_path",
        "source_row_fingerprint_sha256": "after_source_row_fingerprint_sha256",
    })
    compare = before.merge(after, on="api_record_id", how="outer", validate="one_to_one")
    view_fp = quality[[
        "api_record_id", "api4_3_payload_sha256", "api4_3_source_artifact_id",
        "api4_3_source_page_sha256", "api4_3_source_page_path",
    ]].copy()
    compare = compare.merge(view_fp, on="api_record_id", how="left", validate="one_to_one")
    compare["before_after_fingerprint_equal"] = compare.before_source_row_fingerprint_sha256.eq(
        compare.after_source_row_fingerprint_sha256
    )
    compare["source_record_type_equal_before_after"] = compare.before_record_type.eq(compare.after_record_type)
    compare["source_page_path_equal_before_after"] = compare.before_source_page_path.eq(compare.after_source_page_path)
    compare["source_artifact_equal_before_after"] = compare.before_source_artifact_id.eq(compare.after_source_artifact_id)
    compare["quality_view_source_fingerprint_matches_before"] = compare.apply(
        lambda r: (
            pd.isna(r.api4_3_payload_sha256)
            or (
                str(r.api4_3_payload_sha256) == str(r.before_payload_sha256)
                and int(r.api4_3_source_artifact_id) == int(r.before_source_artifact_id)
                and str(r.api4_3_source_page_sha256) == str(r.before_source_page_sha256)
                and str(r.api4_3_source_page_path) == str(r.before_source_page_path)
            )
        ), axis=1,
    )
    compare["quality_view_source_fingerprint_matches_after"] = compare.apply(
        lambda r: (
            pd.isna(r.api4_3_payload_sha256)
            or (
                str(r.api4_3_payload_sha256) == str(r.after_payload_sha256)
                and int(r.api4_3_source_artifact_id) == int(r.after_source_artifact_id)
                and str(r.api4_3_source_page_sha256) == str(r.after_source_page_sha256)
                and str(r.api4_3_source_page_path) == str(r.after_source_page_path)
            )
        ), axis=1,
    )

    assert len(targets) == 14457
    assert targets.race_id.nunique() == 1424
    assert len(target_slots) == 53828
    assert target_slots.source_api_record_id.nunique() == 14193
    assert len(quality) == len(quality_ids)
    assert compare.before_after_fingerprint_equal.all(), "API source row fingerprint changed during extraction"
    assert compare.source_record_type_equal_before_after.all()
    assert compare.source_page_path_equal_before_after.all()
    assert compare.source_artifact_equal_before_after.all()
    assert compare.quality_view_source_fingerprint_matches_before.all()
    assert compare.quality_view_source_fingerprint_matches_after.all()

    # Write only new files. Keep this extraction rerunnable only into a fresh folder.
    outputs = {
        "target_1000m_roster.parquet": target_roster,
        "target_last5_lineage.parquet": lineage_out,
        "api4_quality_source_snapshot.parquet": quality,
        "target_last5_section_intervals.parquet": slot_cols,
        "source_race_point_quality_masks.parquet": point_masks,
        "source_point_order_status_evidence.parquet": order_values,
        "source_point_group_status_evidence.parquet": group_values,
        "source_fingerprint_before_after.parquet": compare,
        "section_time_reviews.parquet": review_rows,
    }
    for name, frame in outputs.items():
        output = HERE / name
        if output.exists():
            raise FileExistsError(f"refusing to overwrite: {output}")
        frame.to_parquet(output, index=False)

    segment_availability = {}
    for name, _formula in SEGMENTS.items():
        history = slot_cols
        measurement_elig = history[f"{name}_endpoint_measurement_eligible"].astype(bool)
        quality_elig = history[f"{name}_quality_eligible"].astype(bool)
        history_elig = history[f"{name}_feature_eligible"].astype(bool)
        segment_availability[name] = {
            "formula": _formula,
            "last5_lineage_slots": int(len(history)),
            "slots_with_positive_endpoint_times_and_usable_status_n": int(measurement_elig.sum()),
            "slots_with_full_race_point_masks_and_positive_delta_n": int(quality_elig.sum()),
            "slots_with_f1s_valid_time_and_feature_eligible_n": int(history_elig.sum()),
            "targets_with_one_or_more_feature_eligible_slots_n": int(
                history.loc[history_elig].target_api_record_id.nunique()
            ),
            "targets_with_five_feature_eligible_slots_n": int(
                history.groupby("target_api_record_id")[f"{name}_feature_eligible"].sum().eq(5).sum()
            ),
        }

    status_domains = {}
    for column in [
        "s1f_time_status", "c3_time_status", "c4_time_status", "g3f_time_status", "g1f_time_status",
        "s1f_order_status", "c3_order_status", "c4_order_status", "g1f_order_status",
        "s1f_group_status", "c3_group_status", "c4_group_status", "g1f_group_status",
    ]:
        status_domains[column] = {
            str(key): int(value)
            for key, value in quality[column].fillna("<NULL>").value_counts(dropna=False).items()
        }
    full_roster_status_domains = {
        "individual_order": {
            str(key): int(value)
            for key, value in order_values.loc[order_values.is_started_roster_member,
                "quality_order_status"].fillna("<NULL>").value_counts(dropna=False).items()
        },
        "race_group": {
            str(key): int(value)
            for key, value in group_values.loc[group_values.is_started_roster_selected_api303_record,
                "group_status"].fillna("<NULL>").value_counts(dropna=False).items()
        },
    }

    audit = {
        "audit_status": "read_only_source_snapshot_complete",
        "database_access": {
            "uri_mode": "ro",
            "sqlite_query_only": True,
            "quality_view_scan_count": 1,
            "quality_view": "jeju_race_postrace_sections_quality_2026",
            "quality_view_sql_sha256": view_sql_sha256,
            "snapshot_data_version": data_version_at_snapshot,
            "full_source_race_order_and_group_status_queries_in_same_snapshot": True,
            "whole_database_hash_claimed_unchanged": False,
            "api4_source_rows_before_after_fingerprints_equal": bool(compare.before_after_fingerprint_equal.all()),
            "record_type_artifact_payload_page_sha_and_path_equal_before_after": bool(
                compare.source_record_type_equal_before_after.all()
                and compare.source_artifact_equal_before_after.all()
                and compare.source_page_path_equal_before_after.all()
            ),
            "api4_quality_view_fingerprint_matches_before_and_after": bool(
                compare.quality_view_source_fingerprint_matches_before.all()
                and compare.quality_view_source_fingerprint_matches_after.all()
            ),
        },
        "source_contract": {
            "target_roster_source": str(F1_FEATURES.relative_to(ROOT)),
            "saved_last5_lineage_source": str(F1_LINEAGE.relative_to(ROOT)),
            "started_valid_time_source": str(BASELINE_SOURCE.relative_to(ROOT)),
            "target_distance_m": 1000,
            "target_race_date_max_inclusive": CUTOFF,
            "excluded_horse_id": EXCLUDED_HORSE_ID,
            "history_slots": "the exact saved `last5_same_source_ids` list; no new history selection",
            "time_source": "quality-selected API4 individual-horse section fields; API6 not used",
            "api4_times": ["S1F", "C3", "C4", "G3F", "G1F", "finish_time_seconds"],
            "point_quality": "full-roster order/group-quality values for S1F, C3, C4, G1F from the same read transaction; one bad, NULL, unknown, or incomplete race-point status blocks that entire point for every horse",
            "segment_formulas": SEGMENTS,
            "point_order_status_allowlist": sorted(ORDER_STATUS_ALLOWED),
            "point_group_status_allowlist": sorted(GROUP_STATUS_ALLOWED),
            "point_mask_rule": "full source race-point; the exact order-status API-record-ID set and horse ID/program number must match the current race_result_rows started roster, independently reconciled to the baseline candidate snapshot; the quality-view-selected API303 record must be consistent across all started runners and have exactly one selected point row whose payload/artifact/page fingerprint and group status match the quality-view attachment; NULL/unrecognized status or status containing conflict/not_applied/source_changed fails closed; explicit known unavailable statuses remain recognized domain values, while each time endpoint separately requires a positive time allowlist status",
            "time_status_allowed": sorted(GOOD_TIME_STATUS),
            "f1s_feature_validity_rule": "every historical section contribution requires baseline valid_time=True; preserve but do not impute/backfill invalid slots",
            "finish_time_endpoint_requires": "positive finish time; feature contribution additionally requires baseline valid_time=True",
            "g3f_identity_diagnostic": "finish_time_seconds - C3 - G3F, reported separately; positive field statuses, valid_time, and full-race C3 clear mask; absolute tolerance 0.15 seconds; never an extra segment",
            "distance_labels": "official glossary describes 3C/4C as approximately 600m/400m remaining; middle interval labels retain approximate notation",
        },
        "counts": {
            "target_rows": int(len(targets)),
            "target_races": int(targets.race_id.nunique()),
            "target_race_date_min": str(targets.race_date.min()),
            "target_race_date_max": str(targets.race_date.max()),
            "target_rows_by_year": {
                str(year): {"rows": int(group.api_record_id.size), "races": int(group.race_id.nunique())}
                for year, group in targets.groupby("year", sort=True)
            },
            "exact_last5_slots": int(len(target_slots)),
            "targets_with_last5_slots": int(target_slots.target_api_record_id.nunique()),
            "distinct_history_source_ids": int(target_slots.source_api_record_id.nunique()),
            "history_source_race_date_min": str(target_slots.source_race_date.min()),
            "history_source_race_date_max": str(target_slots.source_race_date.max()),
            "quality_snapshot_unique_records_target_history_or_started_roster": int(len(quality)),
            "source_rows_baseline_valid_time_false": int((~quality.valid_time.astype(bool)).sum()),
            "source_rows_baseline_started_false": int((~quality.started.astype(bool)).sum()),
            "source_rows_with_nonpositive_or_unusable_field_time": {
                field: int((~quality[f"{field}_time_selected_positive"]).sum())
                for field in TIME_FIELDS
            },
            "referenced_source_races": int(len(source_race_ids)),
            "source_race_roster_reconciliation": {
                "baseline_full_candidate_rows": int(len(full_source_race_rows)),
                "current_db_full_candidate_rows": int(len(db_roster)),
                "baseline_full_started_rows": int(len(baseline_started)),
                "current_db_full_started_rows": int(len(db_started)),
                "races_with_exact_candidate_api_id_set_match": int(
                    len(source_race_ids) if set(db_roster.api_record_id.astype("int64")) == full_source_event_ids else 0
                ),
                "races_with_exact_started_api_id_horse_id_horse_number_match": int(len(source_race_ids)),
                "starter_definition": "finish_position 1..89 or 91/92, inherited F1 source audit; other codes not reclassified",
                "all_candidate_ids_match": bool(set(db_roster.api_record_id.astype("int64")) == full_source_event_ids),
                "all_started_ids_match": bool(set(db_started.api_record_id.astype("int64")) == full_source_started_ids),
            },
            "full_racepoint_masks": {
                point: {
                    "race_points_total": int(point_masks.point.eq(point).sum()),
                    "race_points_clear": int(point_masks.loc[point_masks.point.eq(point), "point_clear_full_race"].sum()),
                    "race_points_blocked": int((~point_masks.loc[point_masks.point.eq(point), "point_clear_full_race"]).sum()),
                    "full_roster_order_coverage_complete": int(point_masks.loc[point_masks.point.eq(point), "order_status_coverage_complete"].sum()),
                    "order_started_id_sets_exact": int(point_masks.loc[point_masks.point.eq(point), "order_started_api_id_set_exact"].sum()),
                    "order_started_horse_identity_exact": int(point_masks.loc[point_masks.point.eq(point), "order_started_horse_identity_exact"].sum()),
                    "group_status_coverage_present": int(point_masks.loc[point_masks.point.eq(point), "group_status_coverage_present"].sum()),
                    "group_selected_source_fingerprint_matches_quality_view": int(point_masks.loc[point_masks.point.eq(point), "group_selected_source_fingerprint_matches_quality_view"].sum()),
                    "group_quality_status_matches_quality_view": int(point_masks.loc[point_masks.point.eq(point), "group_quality_status_matches_quality_view"].sum()),
                    "api303_selection_consistent_across_started_roster": int(point_masks.loc[point_masks.point.eq(point), "api303_selection_consistent_across_started_roster"].sum()),
                }
                for point in ORDER_FIELDS
            },
            "g3f_identity_diagnostic_slots": int(slot_cols.g3f_identity_diagnostic_eligible.sum()),
            "g3f_identity_within_0_15s_n": int(slot_cols.g3f_identity_within_0_15s.sum()),
            "g3f_identity_abs_residual_max_s": (
                None if not slot_cols.g3f_identity_diagnostic_eligible.any()
                else float(slot_cols.loc[slot_cols.g3f_identity_diagnostic_eligible,
                    "g3f_identity_residual_finish_minus_c3_minus_g3f"].abs().max())
            ),
            "slots_all_five_measurements_monotone_n": int(slot_cols.five_sections_measurement_monotone.sum()),
            "slots_all_five_features_eligible_and_monotone_n": int(slot_cols.five_sections_feature_eligible_and_monotone.sum()),
            "segment_availability": segment_availability,
            "status_domains": status_domains,
            "full_roster_status_domains": full_roster_status_domains,
            "source_fingerprint_before_after_equal_rows": int(compare.before_after_fingerprint_equal.sum()),
            "source_fingerprint_rows": int(len(compare)),
        },
        "outputs": {},
    }
    for name in outputs:
        path = HERE / name
        audit["outputs"][name] = {
            "rows": int(len(outputs[name])), "bytes": int(path.stat().st_size),
            "sha256": sha256_file(path),
        }
    audit_path = HERE / "source_audit.json"
    with audit_path.open("x", encoding="utf-8") as stream:
        json.dump(audit, stream, ensure_ascii=False, indent=2, allow_nan=False, default=canonical)
        stream.write("\n")
    print(json.dumps(audit, ensure_ascii=False, indent=2, allow_nan=False, default=canonical))


if __name__ == "__main__":
    main()
