"""Read-only source and slot-availability audit for F1 + past section times.

This script does not build model features, score saved models, fit models,
optimize calibration, or calculate prediction metrics. It reads only the
status-bearing constituent views named by the SQL definition of
jeju_race_postrace_sections_quality_2026; it never selects raw source fields.
"""
import sys

sys.dont_write_bytecode = True

import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
F1_DIR = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
F1_OUT = F1_DIR / "outputs"
F1_FEATURES = F1_OUT / "features.parquet"
F1_LINEAGE = F1_OUT / "historical_lineage.parquet"
SOURCE_SNAPSHOT = (
    ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet"
)
DB_PATH = ROOT / "jeju/data/jeju_native_core.sqlite3"
QUALITY_VIEW = "jeju_race_postrace_sections_quality_2026"
OUT = HERE / "outputs"

SECTION_FIELDS = {
    "s1f": {
        "time": "s1f_time_seconds",
        "time_status": "s1f_time_status",
        "order_status": "s1f_order_status",
        "group_status": "s1f_group_status",
    },
    "g3f": {
        "time": "g3f_time_seconds",
        "time_status": "g3f_time_status",
        "order_status": None,
        "group_status": None,
    },
    "g1f": {
        "time": "g1f_time_seconds",
        "time_status": "g1f_time_status",
        "order_status": "g1f_order_status",
        "group_status": "g1f_group_status",
    },
}
USABLE_TIME_STATUSES = {"website_corrected", "api_positive_unreviewed"}
UNRESOLVED_SECTION_STATUS = "unresolved_official_internal_conflict"
ORDER_FAILURE_PATTERN = r"conflict|not_applied|source_changed"
ORDER_STATUS_ALLOWED = {
    "api_positive_unreviewed", "api_unavailable_or_nonpositive_or_sentinel",
    "website_corrected", "website_review_not_applied", "api_source_changed_since_review",
    "unresolved_official_internal_conflict", "internal_conflict_review_not_applied",
    "api_source_changed_since_conflict_review",
}
GROUP_STATUS_ALLOWED = {
    "api_group_unavailable", "api_group_unreviewed",
    "unresolved_official_internal_conflict", "internal_conflict_review_not_applied",
    "api_source_changed_since_conflict_review",
}
TIME_STATUS_ALLOWED = {
    "website_corrected", "api_positive_unreviewed", "unresolved_official_website_anomaly",
    "website_review_not_applied", "api_source_changed_since_review",
    "api_unavailable_or_nonpositive",
}
TIME_FIELDS_BY_SOURCE_NAME = {
    "jeS1fTime": "s1f", "jeG3fTime": "g3f", "jeG1fTime": "g1f",
}
KNOWN_TIME_CASE_IDS = (178142, 180747, 191451, 190686)
ORDER_FIELDS_BY_SECTION = {"s1f": "sjS1fOrd", "g1f": "sjG1fOrd"}
GROUP_POINTS_BY_SECTION = {"s1f": "S1F", "g1f": "G1F"}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite_integer(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if np.isfinite(number) and number == np.floor(number) else None


def save_new_json(path, payload):
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing audit output: {path}")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def save_new_csv(path, frame):
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing audit output: {path}")
    frame.to_csv(path, index=False, encoding="utf-8")


def save_new_parquet(path, frame):
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing audit output: {path}")
    frame.to_parquet(path, index=False)


def reference_manifest(features, lineage):
    files = [
        F1_DIR / "CONTRACT.md",
        F1_DIR / "README.md",
        F1_DIR / "prepare.py",
        F1_DIR / "run.py",
        F1_FEATURES,
        F1_OUT / "feature_contract.csv",
        F1_OUT / "historical_lineage.parquet",
        F1_OUT / "source_audit_summary.json",
        F1_DIR.parent / "20261008_horse_profile_baseline_v1/run.py",
        SOURCE_SNAPSHOT,
        DB_PATH,
    ]
    items = {}
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        items[rel] = {"bytes": path.stat().st_size, "sha256": sha256(path)}

    models = {}
    for year in (2024, 2025, 2026):
        folder = F1_OUT / f"F1_{year}"
        model_path = folder / "top3.txt"
        meta_path = folder / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        model_hash = sha256(model_path)
        header = model_path.read_text(encoding="utf-8").splitlines()[:9]
        names_line = next((line for line in header if line.startswith("feature_names=")), None)
        names = names_line.removeprefix("feature_names=").split() if names_line else []
        assert model_hash == meta["model_sha256"], f"saved F1 {year} model hash mismatch"
        assert names == meta["features"], f"saved F1 {year} feature header mismatch"
        models[str(year)] = {
            "top3_bytes": model_path.stat().st_size,
            "top3_sha256": model_hash,
            "meta_bytes": meta_path.stat().st_size,
            "meta_sha256": sha256(meta_path),
            "features": meta["features"],
            "vocabulary": meta["vocabulary"],
            "trees": int(meta["trees"]),
            "tau": float(meta["tau"]),
            "seed": int(meta["seed"]),
            "parameters": meta["parameters"],
            "evaluation_rows": int(meta["evaluation_rows"]),
            "evaluation_races": int(meta["evaluation_races"]),
        }

    assert all(len(models[str(year)]["features"]) == 24 for year in models)
    assert all(models[str(year)]["seed"] == 20261008 for year in models)
    assert features.api_record_id.is_unique
    assert lineage.target_api_record_id.isin(features.api_record_id).all()
    return {"files": items, "saved_f1_models": models}


def read_quality_components(source_ids, race_tuples):
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        max_variables = connection.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
        ids = sorted(set(int(value) for value in source_ids))
        tuples = sorted(set((str(d), int(m), int(r)) for d, m, r in race_tuples))
        assert len(tuples) * 3 + 4 <= max_variables

        time_fields = tuple(TIME_FIELDS_BY_SOURCE_NAME)
        time_field_marks = ",".join("?" for _ in time_fields)
        time_batches = []
        batch_size = min(8000, max_variables - len(time_fields))
        assert batch_size > 0
        for offset in range(0, len(ids), batch_size):
            batch_ids = ids[offset:offset + batch_size]
            time_id_marks = ",".join("?" for _ in batch_ids)
            time_batches.append(pd.read_sql_query(
                "SELECT api_record_id,race_date,meet_code,race_number,horse_id,field_name,"
                "time_seconds,time_status FROM jeju_race_section_time_values "
                f"WHERE api_record_id IN ({time_id_marks}) AND field_name IN ({time_field_marks})",
                connection, params=batch_ids + list(time_fields),
            ))
        time_rows = pd.concat(time_batches, ignore_index=True)

        race_marks = ",".join("(?,?,?)" for _ in tuples)
        race_values = [value for race in tuples for value in race]
        order_fields = tuple(ORDER_FIELDS_BY_SECTION.values())
        order_field_marks = ",".join("?" for _ in order_fields)
        order_rows = pd.read_sql_query(
            "SELECT api_record_id,race_date,meet_code,race_number,horse_number,horse_id,"
            "field_name,quality_order_status FROM jeju_race_section_order_quality_values "
            f"WHERE (race_date,meet_code,race_number) IN (VALUES {race_marks}) "
            f"AND field_name IN ({order_field_marks})",
            connection, params=race_values + list(order_fields),
        )
        group_points = tuple(GROUP_POINTS_BY_SECTION.values())
        group_point_marks = ",".join("?" for _ in group_points)
        group_rows = pd.read_sql_query(
            "SELECT api_record_id,race_date,meet_code,race_number,point,group_status "
            "FROM jeju_race_section_group_quality_values "
            f"WHERE (race_date,meet_code,race_number) IN (VALUES {race_marks}) "
            f"AND point IN ({group_point_marks})",
            connection, params=race_values + list(group_points),
        )

        view_names = [
            "jeju_race_postrace_sections_quality_2026",
            "jeju_race_postrace_sections_reviewed_2026",
            "jeju_race_postrace_sections_2026",
            "jeju_race_section_times", "jeju_race_section_time_values",
            "jeju_race_section_order_quality", "jeju_race_section_order_quality_values",
            "jeju_race_section_group_quality", "jeju_race_section_group_quality_values",
        ]
        ddl = {}
        for name in view_names:
            row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (name,)
            ).fetchone()
            assert row and row[0], f"missing source view definition: {name}"
            ddl[name] = row[0]
        assert "jeju_race_section_order_quality o" in ddl[QUALITY_VIEW]
        assert "jeju_race_section_group_quality g" in ddl[QUALITY_VIEW]
        assert "jeju_race_postrace_sections_2026 a" in ddl["jeju_race_postrace_sections_reviewed_2026"]
        assert "jeju_race_section_orders s" in ddl["jeju_race_postrace_sections_reviewed_2026"]
        assert "jeju_race_section_times s" in ddl["jeju_race_postrace_sections_2026"]
        assert "FROM jeju_race_section_time_values" in ddl["jeju_race_section_times"]
        for source_field, section in TIME_FIELDS_BY_SOURCE_NAME.items():
            output_column = f"{section}_time_seconds"
            assert f"MAX(CASE WHEN field_name='{source_field}' THEN time_seconds END) AS {output_column}" in ddl["jeju_race_section_times"]
            assert f"{output_column}," in ddl["jeju_race_postrace_sections_2026"]
        assert "WHEN o.api_record_id IS NOT NULL THEN o.effective_seconds" in ddl["jeju_race_section_time_values"]
        assert "WHEN o.api_record_id IS NOT NULL THEN o.review_status" in ddl["jeju_race_section_time_values"]
        assert "FROM jeju_race_section_time_values" in ddl["jeju_race_section_times"]
        assert "FROM jeju_race_section_order_quality_values" in ddl["jeju_race_section_order_quality"]
        assert "FROM jeju_race_section_group_quality_values" in ddl["jeju_race_section_group_quality"]
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        ddl_hashes = {
            name: hashlib.sha256(sql.encode("utf-8")).hexdigest()
            for name, sql in ddl.items()
        }
        return time_rows, order_rows, group_rows, ddl_hashes
    finally:
        connection.close()


def race_keys(frame, date_column="race_date"):
    return (
        frame[date_column].astype(str)
        + "_"
        + frame["meet_code"].astype("Int64").astype(str)
        + "_"
        + frame["race_number"].astype("Int64").astype(str)
    )


def build_slot_audit(features, lineage, source, time_rows, order_rows, group_rows):
    slots = lineage.loc[lineage.history_kind.eq("last5_same_distance_start")].copy()
    assert len(slots) == 178459
    assert slots.target_api_record_id.nunique() <= len(features)
    assert not slots.source_api_record_id.is_unique
    assert slots.source_started.eq(True).all()
    assert slots.target_horse_id.astype(str).eq(slots.source_horse_id.astype(str)).all()
    assert slots.target_distance_m.eq(slots.source_distance_m).all()
    assert slots.source_race_date.astype(str).le(slots.target_cutoff.astype(str)).all()
    assert slots.groupby("target_api_record_id").size().le(5).all()

    grouped_ids = {
        key: [int(value) for value in group.sort_values("slot_oldest_to_newest").source_api_record_id]
        for key, group in slots.groupby("target_api_record_id", sort=False)
    }
    for row in features[["api_record_id", "last5_same_source_ids"]].itertuples(index=False):
        value = row.last5_same_source_ids
        ids = [] if value is None or (isinstance(value, float) and np.isnan(value)) else [int(x) for x in value]
        assert ids == grouped_ids.get(int(row.api_record_id), []), row.api_record_id

    source_cols = [
        "api_record_id", "race_id", "race_date", "meet_code", "race_number",
        "horse_id", "race_distance_m", "started", "valid_time",
    ]
    source_view = source[source_cols].copy()
    source_view["api_record_id"] = source_view.api_record_id.astype("int64")
    assert source_view.api_record_id.is_unique and len(source_view) == 92513

    unique_source_ids = set(slots.source_api_record_id.astype("int64"))
    assert set(time_rows.field_name.unique()) == set(TIME_FIELDS_BY_SOURCE_NAME)
    assert not time_rows.duplicated(["api_record_id", "field_name"]).any()
    time_counts = time_rows.groupby("api_record_id").size()
    assert time_counts.eq(3).all()
    assert unique_source_ids.issubset(set(time_counts.index.astype("int64")))
    assert set(time_counts.index.astype("int64")).issubset(unique_source_ids | set(KNOWN_TIME_CASE_IDS))
    time_meta = time_rows.groupby("api_record_id", sort=False).agg(
        quality_race_date=("race_date", "first"), quality_meet_code=("meet_code", "first"),
        quality_race_number=("race_number", "first"), quality_horse_id=("horse_id", "first"),
    )
    time_meta["quality_race_key"] = (
        time_meta.quality_race_date.astype(str) + "_"
        + time_meta.quality_meet_code.astype("Int64").astype(str) + "_"
        + time_meta.quality_race_number.astype("Int64").astype(str)
    )
    time_seconds = time_rows.pivot(
        index="api_record_id", columns="field_name", values="time_seconds"
    ).rename(columns={key: f"{value}_time_seconds" for key, value in TIME_FIELDS_BY_SOURCE_NAME.items()})
    time_status = time_rows.pivot(
        index="api_record_id", columns="field_name", values="time_status"
    ).rename(columns={key: f"{value}_time_status" for key, value in TIME_FIELDS_BY_SOURCE_NAME.items()})
    assert set(time_rows.time_status.dropna().astype(str).unique()).issubset(TIME_STATUS_ALLOWED)
    time_wide = time_meta.join(time_seconds).join(time_status).reset_index()
    time_wide = time_wide.rename(columns={"api_record_id": "quality_api_record_id"})

    merged = slots.merge(
        source_view, left_on="source_api_record_id", right_on="api_record_id",
        how="left", validate="many_to_one", indicator="source_match",
    )
    assert merged.source_match.eq("both").all()
    merged = merged.merge(
        time_wide, left_on="source_api_record_id", right_on="quality_api_record_id",
        how="left", validate="many_to_one", indicator="quality_time_match",
    )
    assert merged.quality_time_match.eq("both").all()
    assert merged.source_race_date.astype(str).eq(merged.quality_race_date.astype(str)).all()
    assert merged.source_horse_id.astype(str).eq(merged.quality_horse_id.astype(str)).all()
    assert merged.source_race_date.astype(str).eq(merged.race_date.astype(str)).all()
    assert merged.source_horse_id.astype(str).eq(merged.horse_id.astype(str)).all()
    assert merged.source_distance_m.eq(merged.race_distance_m).all()
    assert merged.source_started.eq(merged.started).all()
    assert merged.source_race_id.astype(str).eq(merged.race_id.astype(str)).all()
    merged["source_race_key"] = (
        merged.race_date.astype(str) + "_"
        + merged.meet_code.astype("Int64").astype(str) + "_"
        + merged.race_number.astype("Int64").astype(str)
    )
    merged["quality_race_key"] = (
        merged.quality_race_date.astype(str) + "_"
        + merged.quality_meet_code.astype("Int64").astype(str) + "_"
        + merged.quality_race_number.astype("Int64").astype(str)
    )
    assert merged.source_race_key.eq(merged.quality_race_key).all()

    order_status_domains = {}
    order_mask_frames = []
    order_rows["race_key"] = race_keys(order_rows)
    assert set(order_rows.quality_order_status.dropna().astype(str).unique()).issubset(ORDER_STATUS_ALLOWED)
    for field, source_name in ORDER_FIELDS_BY_SECTION.items():
        frame = order_rows.loc[order_rows.field_name.eq(source_name)].copy()
        frame["fail_closed"] = frame.quality_order_status.isna() | frame.quality_order_status.astype("string").str.contains(
            ORDER_FAILURE_PATTERN, case=False, regex=True, na=True
        )
        order_status_domains[field] = sorted(frame.quality_order_status.dropna().astype(str).unique())
        values = frame.groupby("race_key").fail_closed.any().rename(f"{field}_order_conflict")
        order_mask_frames.append(values)
    group_status_domains = {}
    group_mask_frames = []
    group_rows["race_key"] = race_keys(group_rows)
    assert set(group_rows.group_status.dropna().astype(str).unique()).issubset(GROUP_STATUS_ALLOWED)
    for field, point in GROUP_POINTS_BY_SECTION.items():
        frame = group_rows.loc[group_rows.point.eq(point)].copy()
        frame["fail_closed"] = frame.group_status.isna() | frame.group_status.astype("string").str.contains(
            ORDER_FAILURE_PATTERN, case=False, regex=True, na=True
        )
        group_status_domains[field] = sorted(frame.group_status.dropna().astype(str).unique())
        values = frame.groupby("race_key").fail_closed.any().rename(f"{field}_group_conflict")
        group_mask_frames.append(values)
    race_mask = pd.concat(order_mask_frames + group_mask_frames, axis=1)
    referenced_race_keys = sorted(merged.source_race_key.astype(str).unique())
    race_mask = race_mask.reindex(referenced_race_keys)
    mask_components = [
        "s1f_order_conflict", "g1f_order_conflict", "s1f_group_conflict", "g1f_group_conflict",
    ]
    for column in mask_components:
        # Missing race-point status coverage is not evidence of a clean point.
        race_mask[column] = race_mask[column].fillna(True).astype(bool)
    race_mask = race_mask.reset_index()
    for field in ("s1f", "g1f"):
        race_mask[f"{field}_race_section_conflict"] = (
            race_mask[f"{field}_order_conflict"] | race_mask[f"{field}_group_conflict"]
        )
    merged = merged.merge(
        race_mask, left_on="source_race_key", right_on="race_key",
        how="left", validate="many_to_one", indicator="race_mask_match",
    )
    assert merged.race_mask_match.eq("both").all()

    status_count_rows = []
    for field, names in SECTION_FIELDS.items():
        time_col = names["time"]
        status_col = names["time_status"]
        is_selected_value = (
            merged[time_col].notna()
            & pd.to_numeric(merged[time_col], errors="coerce").gt(0)
            & merged[status_col].isin(USABLE_TIME_STATUSES)
        )
        valid_time = merged.valid_time.eq(True)
        if field == "s1f":
            clear_race = ~merged.s1f_race_section_conflict
        elif field == "g1f":
            clear_race = ~merged.g1f_race_section_conflict
        else:
            clear_race = pd.Series(True, index=merged.index)
        merged[f"{field}_selected_value"] = is_selected_value
        merged[f"{field}_eligible"] = is_selected_value & valid_time & clear_race
        status_counts = merged[status_col].fillna("<NULL>").value_counts(dropna=False).to_dict()
        eligible_values = pd.to_numeric(merged.loc[merged[f"{field}_eligible"], time_col], errors="coerce")
        status_count_rows.append({
            "section": field,
            "slot_rows": int(len(merged)),
            "selected_value_rows_before_valid_time_and_conflict_mask": int(is_selected_value.sum()),
            "valid_time_rows": int(valid_time.sum()),
            "rows_excluded_by_valid_time": int((is_selected_value & ~valid_time).sum()),
            "rows_excluded_by_race_section_conflict": int((is_selected_value & valid_time & ~clear_race).sum()),
            "eligible_slot_rows": int(merged[f"{field}_eligible"].sum()),
            "eligible_value_min_seconds": None if eligible_values.empty else float(eligible_values.min()),
            "eligible_value_max_seconds": None if eligible_values.empty else float(eligible_values.max()),
            "unique_referenced_source_records_with_usable_time": int(
                merged.loc[is_selected_value, "source_api_record_id"].nunique()
            ),
            "time_status_counts_on_slot_rows": {str(k): int(v) for k, v in status_counts.items()},
        })

    reference_status = merged.groupby("target_api_record_id", sort=False).agg(
        actual_section_slot_n=("source_api_record_id", "size"),
        s1f_valid_n=("s1f_eligible", "sum"),
        g3f_valid_n=("g3f_eligible", "sum"),
        g1f_valid_n=("g1f_eligible", "sum"),
    ).reset_index()
    support = features[[
        "api_record_id", "year", "race_date", "race_id", "distance_m", "observed_starts",
    ]].merge(
        reference_status, left_on="api_record_id", right_on="target_api_record_id",
        how="left", validate="one_to_one",
    )
    for column in ("actual_section_slot_n", "s1f_valid_n", "g3f_valid_n", "g1f_valid_n"):
        support[column] = support[column].fillna(0).astype("int64")
    assert support.actual_section_slot_n.le(5).all()
    assert support.s1f_valid_n.le(support.actual_section_slot_n).all()
    assert support.g3f_valid_n.le(support.actual_section_slot_n).all()
    assert support.g1f_valid_n.le(support.actual_section_slot_n).all()

    for field in SECTION_FIELDS:
        expected_n = slots.groupby("target_api_record_id").size()
        actual_n = support.set_index("api_record_id").actual_section_slot_n
        assert np.array_equal(
            actual_n.loc[expected_n.index].to_numpy(dtype="int64"),
            expected_n.to_numpy(dtype="int64"),
        )

    # These four cases are checked directly in the quality-selected time view,
    # even if their source record is absent from the saved last-five lineages.
    known_cases = [
        (178142, "jeS1fTime", 20.0, "website_corrected"),
        (180747, "jeS1fTime", 17.8, "website_corrected"),
        (191451, "jeG1fTime", None, "unresolved_official_website_anomaly"),
        (190686, "jeG1fTime", 16.0, "website_corrected"),
    ]
    cases = []
    time_rows["api_record_id"] = time_rows.api_record_id.astype("int64")
    for record_id, source_field, expected_seconds, expected_status in known_cases:
        value_row = time_rows.loc[
            time_rows.api_record_id.eq(record_id) & time_rows.field_name.eq(source_field)
        ]
        ref = slots.loc[slots.source_api_record_id.eq(record_id)]
        assert len(value_row) == 1
        actual_value = value_row.time_seconds.iloc[0]
        actual_status = str(value_row.time_status.iloc[0])
        assert (None if pd.isna(actual_value) else float(actual_value)) == expected_seconds
        assert actual_status == expected_status
        cases.append({
            "api_record_id": record_id,
            "section": TIME_FIELDS_BY_SOURCE_NAME[source_field],
            "slot_reference_rows": int(len(ref)),
            "race_date": str(value_row.race_date.iloc[0]),
            "race_number": int(value_row.race_number.iloc[0]),
            "horse_id": str(value_row.horse_id.iloc[0]),
            "time_seconds": None if pd.isna(actual_value) else float(actual_value),
            "time_status": actual_status,
        })

    mask_summary = {}
    for field in ("s1f", "g1f"):
        col = f"{field}_race_section_conflict"
        masked_races = race_mask.loc[race_mask[col], "race_key"].astype(str).tolist()
        masked_slot_rows = int(merged[col].sum())
        valid_selected_excluded = int((
            merged[f"{field}_selected_value"]
            & merged.valid_time.eq(True)
            & merged[col]
        ).sum())
        mask_summary[field] = {
            "distinct_referenced_races_masked_by_quality_components": int(len(masked_races)),
            "distinct_lineage_races_referenced_and_masked": int(
                merged.loc[merged[col], "source_race_key"].nunique()
            ),
            "same_distance_slot_rows_at_masked_point": masked_slot_rows,
            "selected_positive_valid_time_slot_rows_excluded_by_mask": valid_selected_excluded,
            "race_keys": masked_races,
        }

    return merged, support, status_count_rows, mask_summary, cases, order_status_domains, group_status_domains


def support_tables(support):
    rows = []
    field_columns = {
        "s1f": "s1f_valid_n", "g3f": "g3f_valid_n", "g1f": "g1f_valid_n",
    }

    def append_group(kind, key_columns):
        grouped = support.groupby(key_columns, dropna=False, sort=True)
        for key, group in grouped:
            keys = key if isinstance(key, tuple) else (key,)
            key_data = dict(zip(key_columns, [str(value) for value in keys]))
            for field, column in field_columns.items():
                n_counts = group[column].value_counts().reindex(range(6), fill_value=0)
                rows.append({
                    "group_kind": kind,
                    **key_data,
                    "section": field,
                    "target_rows": int(len(group)),
                    "targets_with_any_valid_slot": int(group[column].gt(0).sum()),
                    "eligible_historical_slots": int(group[column].sum()),
                    **{f"targets_n_{n}": int(n_counts.loc[n]) for n in range(6)},
                })

    append_group("distance_m", ["distance_m"])
    append_group("year", ["year"])
    experience = support.copy()
    experience["experience_group"] = pd.cut(
        experience.observed_starts, [-1, 0, 4, np.inf], labels=["0", "1_4", "5_plus"]
    ).astype("string")
    support_with_experience = experience
    append_group("distance_year", ["distance_m", "year"])
    for group_name, group in support_with_experience.groupby("experience_group", dropna=False, sort=True):
        for field, column in field_columns.items():
            n_counts = group[column].value_counts().reindex(range(6), fill_value=0)
            rows.append({
                "group_kind": "experience_group",
                "experience_group": str(group_name),
                "section": field,
                "target_rows": int(len(group)),
                "targets_with_any_valid_slot": int(group[column].gt(0).sum()),
                "eligible_historical_slots": int(group[column].sum()),
                **{f"targets_n_{n}": int(n_counts.loc[n]) for n in range(6)},
            })
    return pd.DataFrame(rows), support_with_experience


def main():
    if OUT.exists() and any(OUT.iterdir()):
        raise FileExistsError(f"refusing to reuse nonempty output directory: {OUT}")
    OUT.mkdir(parents=True, exist_ok=True)

    features = pd.read_parquet(F1_FEATURES)
    lineage = pd.read_parquet(F1_LINEAGE)
    source = pd.read_parquet(SOURCE_SNAPSHOT)
    assert len(features) == 52155 and features.race_id.nunique() == 5206
    evaluation = features.loc[features.year.ge(2024)]
    assert len(evaluation) == 17412 and evaluation.race_id.nunique() == 1779
    assert not features.horse_id.astype(str).eq("3005648").any()
    assert source.api_record_id.is_unique and len(source) == 92513

    refs = reference_manifest(features, lineage)
    lineage_slots = lineage.loc[lineage.history_kind.eq("last5_same_distance_start")]
    source_ids = sorted(set(lineage_slots.source_api_record_id.astype("int64")))
    source_subset = source.loc[source.api_record_id.astype("int64").isin(source_ids)]
    assert source_subset.api_record_id.nunique() == len(source_ids)
    race_tuples = sorted(set(zip(
        source_subset.race_date.astype(str),
        source_subset.meet_code.astype(int),
        source_subset.race_number.astype(int),
    )))
    print(
        f"Reading quality-selected time/order/group components for {len(source_ids):,} historical IDs "
        f"and {len(race_tuples):,} referenced races.", flush=True
    )
    time_rows, order_rows, group_rows, view_ddl_hashes = read_quality_components(
        source_ids + list(KNOWN_TIME_CASE_IDS), race_tuples
    )
    slots, support, field_status, mask_summary, known_cases, order_domains, group_domains = build_slot_audit(
        features, lineage, source, time_rows, order_rows, group_rows
    )
    tables, support = support_tables(support)
    n_distribution_rows = []
    for keys, group in support.groupby(["year", "distance_m", "experience_group"], dropna=False, sort=True):
        year, distance, experience = keys
        for field, column in (("s1f", "s1f_valid_n"), ("g3f", "g3f_valid_n"), ("g1f", "g1f_valid_n")):
            counts = group[column].value_counts().reindex(range(6), fill_value=0)
            for valid_n, count in counts.items():
                n_distribution_rows.append({
                    "year": int(year), "distance_m": int(distance),
                    "experience_group": str(experience), "section": field,
                    "valid_n": int(valid_n), "target_rows": int(count),
                })
    n_distribution = pd.DataFrame(n_distribution_rows)

    source_summary = {
        "source_snapshot_rows": int(len(source)),
        "unique_history_source_records": int(len(source_ids)),
        "history_source_date_min": str(source_subset.race_date.min()),
        "history_source_date_max": str(source_subset.race_date.max()),
        "referenced_races": int(len(race_tuples)),
        "quality_selected_time_rows": int(len(time_rows)),
        "quality_order_status_rows": int(len(order_rows)),
        "quality_group_status_rows": int(len(group_rows)),
        "full_quality_view_scan_performed": False,
        "quality_view_semantics_verified_through_ddl_dependencies": True,
        "quality_selected_time_projection_and_status_logic_verified_in_ddl": True,
        "raw_time_order_or_group_columns_selected": False,
        "database_uri_mode": "ro",
        "pragma_query_only": True,
        "quality_view_definition_sha256": view_ddl_hashes[QUALITY_VIEW],
        "quality_view_dependency_ddl_sha256": view_ddl_hashes,
        "selected_time_values_from": "jeju_race_section_time_values.time_seconds/time_status",
        "selected_order_statuses_from": "jeju_race_section_order_quality_values.quality_order_status",
        "selected_group_statuses_from": "jeju_race_section_group_quality_values.group_status",
    }
    checks = {
        "features_rows_52155": len(features) == 52155,
        "features_races_5206": int(features.race_id.nunique()) == 5206,
        "evaluation_rows_17412": len(evaluation) == 17412,
        "evaluation_races_1779": int(evaluation.race_id.nunique()) == 1779,
        "excluded_horse_3005648_absent": not features.horse_id.astype(str).eq("3005648").any(),
        "lineage_all_started_same_horse_same_distance_and_cutoff": bool(
            slots.source_started.eq(True).all()
            and slots.target_horse_id.astype(str).eq(slots.source_horse_id.astype(str)).all()
            and slots.target_distance_m.eq(slots.source_distance_m).all()
            and slots.source_race_date.astype(str).le(slots.target_cutoff.astype(str)).all()
        ),
        "lineage_ids_match_saved_last5_slots_in_order": True,
        "quality_view_constituent_definitions_form_exact_dependency_chain": True,
        "quality_selected_time_source_lineage_matches_date_horse": bool(
            len(time_rows) >= 3 * len(source_ids)
            and slots.source_race_date.astype(str).eq(slots.quality_race_date.astype(str)).all()
            and slots.source_horse_id.astype(str).eq(slots.quality_horse_id.astype(str)).all()
        ),
        "quality_selected_order_and_group_status_domains_allowlisted": True,
        "known_three_corrections_and_unresolved_g1f_asserted_from_quality_time_view": True,
        "no_model_scoring_or_fit_or_temperature_or_prediction_metrics": True,
        "database_opened_mode_ro_and_query_only": True,
    }
    assert all(checks.values())

    summary = {
        "audit_status": "availability_only_preflight",
        "fit_executed": False,
        "saved_model_scoring_executed": False,
        "temperature_optimization_executed": False,
        "prediction_metrics_calculated": False,
        "database_write_executed": False,
        "schema_or_view_changed": False,
        "quality_view": QUALITY_VIEW,
        "quality_source_access": source_summary,
        "f1_population": {
            "rows": int(len(features)), "races": int(features.race_id.nunique()),
            "start_date": str(features.race_date.min()), "end_date": str(features.race_date.max()),
            "year_row_counts": {str(k): int(v) for k, v in features.year.value_counts().sort_index().items()},
            "distance_row_counts_m": {str(int(k)): int(v) for k, v in features.distance_m.value_counts().sort_index().items()},
            "evaluation_rows": int(len(evaluation)),
            "evaluation_races": int(evaluation.race_id.nunique()),
            "evaluation_days": int(evaluation.race_date.nunique()),
            "excluded_horse_3005648_rows": int(features.horse_id.astype(str).eq("3005648").sum()),
            "actual_same_distance_slots": int(len(slots)),
            "target_rows_with_any_actual_same_distance_slot": int(slots.target_api_record_id.nunique()),
            "slot_count_distribution": {
                str(k): int(v) for k, v in slots.groupby("target_api_record_id").size().value_counts().sort_index().items()
            },
        },
        "proposed_additive_candidate_columns_pending_root_and_reviewer_contract_review": [
            "history_s1f_mean5_seconds", "history_s1f_valid_n",
            "history_g3f_mean5_seconds", "history_g3f_valid_n",
            "history_g1f_mean5_seconds", "history_g1f_valid_n",
        ],
        "eligible_time_policy": {
            "quality_source": QUALITY_VIEW,
            "accepted_time_statuses": sorted(USABLE_TIME_STATUSES),
            "positive_selected_time_required": True,
            "existing_source_snapshot_valid_time_required": True,
            "same_distance_actual_slots_preserved_even_when_field_missing_or_source_valid_time_false": True,
            "unresolved_race_section_mask_applies_to_all_runners_in_that_race_for_s1f_and_g1f": True,
            "g3f_order_or_group_mask": "not applicable; 제주 sjG3fOrd is 0 throughout and no G3F order/group is derived",
            "zero_fill_or_slot_backfill": False,
            "full_period_percentile_or_outlier_threshold": False,
            "whole_time_normalization_transferred_to_section_times": False,
        },
        "field_slot_audit": field_status,
        "quality_order_status_domains_by_section": order_domains,
        "quality_group_status_domains_by_section": group_domains,
        "race_section_conflict_masks": mask_summary,
        "known_review_cases_in_same_distance_history_slots": known_cases,
        "preflight_checks": checks,
        "references": refs,
        "audit_code_sha256": sha256(HERE / "audit_source_availability.py"),
    }
    extract_columns = [
        "target_api_record_id", "target_horse_id", "target_distance_m", "target_cutoff",
        "source_api_record_id", "slot_oldest_to_newest", "source_race_date", "source_distance_m",
        "valid_time", "source_race_key",
        "s1f_time_seconds", "s1f_time_status", "s1f_race_section_conflict", "s1f_eligible",
        "g3f_time_seconds", "g3f_time_status", "g3f_eligible",
        "g1f_time_seconds", "g1f_time_status", "g1f_race_section_conflict", "g1f_eligible",
    ]
    slot_extract = slots[extract_columns].copy()
    save_new_parquet(OUT / "source_slot_section_times.parquet", slot_extract)
    summary["quality_source_access"]["slot_extract_rows"] = int(len(slot_extract))
    summary["quality_source_access"]["slot_extract_sha256"] = sha256(OUT / "source_slot_section_times.parquet")
    save_new_csv(OUT / "source_availability_by_group.csv", tables)
    save_new_csv(OUT / "source_valid_n_distribution.csv", n_distribution)
    save_new_json(OUT / "source_availability_audit.json", summary)
    print(json.dumps({
        "audit_status": summary["audit_status"],
        "quality_source_access": source_summary,
        "f1_population": summary["f1_population"],
        "field_slot_audit": field_status,
        "quality_order_status_domains_by_section": order_domains,
        "quality_group_status_domains_by_section": group_domains,
        "race_section_conflict_masks": mask_summary,
        "audit_code_sha256": summary["audit_code_sha256"],
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
