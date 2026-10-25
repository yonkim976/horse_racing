"""Independent reconstruction of historical section-time slot support.

Reads saved F1 history IDs and the immutable source snapshot, then reconstructs
the three proposed time summaries from the DB's normalized quality-value views.
It does not call the candidate feature builder, score a model, or fit anything.
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
F1_FEATURES = F1_DIR / "outputs/features.parquet"
F1_LINEAGE = F1_DIR / "outputs/historical_lineage.parquet"
SOURCE_SNAPSHOT = (
    ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet"
)
TIME_RESEARCH = ROOT / "jeju/research/20261009_time_benchmarks_outliers_v1"
TIME_EXTRACTION = TIME_RESEARCH / "extraction.json"
DB_PATH = ROOT / "jeju/data/jeju_native_core.sqlite3"
OUT = HERE / "independent_outputs"

TIME_VIEW = "jeju_race_section_time_values"
ORDER_VIEW = "jeju_race_section_order_quality_values"
GROUP_VIEW = "jeju_race_section_group_quality_values"
QUALITY_VIEW = "jeju_race_postrace_sections_quality_2026"

FIELDS = {
    "s1f": {"time_field": "jeS1fTime", "order_field": "sjS1fOrd", "point": "S1F"},
    "g3f": {"time_field": "jeG3fTime", "order_field": None, "point": None},
    "g1f": {"time_field": "jeG1fTime", "order_field": "sjG1fOrd", "point": "G1F"},
}
ALLOWED_TIME_STATUSES = {"website_corrected", "api_positive_unreviewed"}
KNOWN_TIME_STATUSES = {
    "api_positive_unreviewed",
    "api_unavailable_or_nonpositive",
    "website_corrected",
    "unresolved_official_website_anomaly",
    "website_review_not_applied",
    "api_source_changed_since_review",
}
ALLOWED_ORDER_STATUSES = {
    "api_positive_unreviewed",
    "api_unavailable_or_nonpositive_or_sentinel",
    "website_corrected",
    "unresolved_official_internal_conflict",
    "website_review_not_applied",
    "api_source_changed_since_review",
    "internal_conflict_review_not_applied",
    "api_source_changed_since_conflict_review",
}
ALLOWED_GROUP_STATUSES = {
    "api_group_unavailable",
    "api_group_unreviewed",
    "unresolved_official_internal_conflict",
    "internal_conflict_review_not_applied",
    "api_source_changed_since_conflict_review",
}
HOLD_MARKERS = (
    "conflict",
    "not_applied",
    "source_changed",
)
CHUNK_SIZE = 5000


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_new(path, value):
    if path.exists():
        raise FileExistsError(path)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False, default=json_default)
        stream.write("\n")


def json_default(item):
    if isinstance(item, np.generic):
        return item.item()
    raise TypeError(f"unsupported JSON value: {type(item).__name__}")


def write_csv_new(path, frame):
    if path.exists():
        raise FileExistsError(path)
    frame.to_csv(path, index=False, encoding="utf-8")


def sql_rows_by_ids(connection, view, columns, id_values, suffix_sql="", suffix_values=()):
    rows = []
    for start in range(0, len(id_values), CHUNK_SIZE):
        batch = id_values[start:start + CHUNK_SIZE]
        id_placeholders = ",".join("?" for _ in batch)
        sql = (
            f"SELECT {columns} FROM {view} "
            f"WHERE api_record_id IN ({id_placeholders}) {suffix_sql}"
        )
        rows.extend(connection.execute(sql, [*batch, *suffix_values]).fetchall())
    return rows


def sql_rows_by_races(connection, view, columns, race_tuples, suffix_sql="", suffix_values=()):
    """Query only F1 historical race keys, in small bound-parameter batches."""
    rows = []
    batch_size = 500
    for start in range(0, len(race_tuples), batch_size):
        batch = race_tuples[start:start + batch_size]
        tuples_sql = ",".join("(?,?,?)" for _ in batch)
        race_values = [value for race in batch for value in race]
        sql = (
            f"SELECT {columns} FROM {view} "
            f"WHERE (race_date,meet_code,race_number) IN (VALUES {tuples_sql}) {suffix_sql}"
        )
        rows.extend(connection.execute(sql, [*race_values, *suffix_values]).fetchall())
    return rows


def status_inventory(connection, view, status_col, allowed):
    counts = {
        ("<NULL>" if value is None else str(value)): int(count)
        for value, count in connection.execute(
            f"SELECT {status_col}, COUNT(*) FROM {view} GROUP BY {status_col}"
        )
    }
    unexpected = set(counts) - allowed - {"<NULL>"}
    if unexpected:
        raise AssertionError(f"unknown {view}.{status_col} status: {sorted(unexpected)}")
    return counts


def hold_match(value):
    if value is None or pd.isna(value):
        return False
    text = str(value).lower()
    return any(marker in text for marker in HOLD_MARKERS)


def main():
    OUT.mkdir(exist_ok=True)
    if any(OUT.iterdir()):
        raise FileExistsError(f"independent output folder must be empty: {OUT}")
    features = pd.read_parquet(F1_FEATURES)
    lineage = pd.read_parquet(F1_LINEAGE)
    source = pd.read_parquet(SOURCE_SNAPSHOT)

    assert len(features) == 52155 and features.race_id.nunique() == 5206
    assert len(source) == 92513 and source.api_record_id.is_unique
    assert features.api_record_id.is_unique
    assert not features.horse_id.astype(str).eq("3005648").any()

    slots = lineage.loc[
        lineage.history_kind.eq("last5_same_distance_start")
    ].copy()
    assert len(slots) == 178459
    assert slots.source_started.eq(True).all()
    assert slots.target_horse_id.astype(str).eq(slots.source_horse_id.astype(str)).all()
    assert slots.target_distance_m.eq(slots.source_distance_m).all()
    assert slots.source_race_date.astype(str).le(slots.target_cutoff.astype(str)).all()
    assert slots.groupby("target_api_record_id").size().le(5).all()

    grouped_ids = {
        int(target_id): [
            int(value) for value in group.sort_values("slot_oldest_to_newest").source_api_record_id
        ]
        for target_id, group in slots.groupby("target_api_record_id", sort=False)
    }
    for row in features[["api_record_id", "last5_same_source_ids"]].itertuples(index=False):
        ids = [] if row.last5_same_source_ids is None else [int(value) for value in row.last5_same_source_ids]
        assert ids == grouped_ids.get(int(row.api_record_id), []), int(row.api_record_id)

    # Build the one-row-per-source cache once; repeated target-slot references
    # never trigger per-row source snapshot conversion or SQL reads.
    source_index = source.set_index("api_record_id", drop=False)
    slot_sources = slots.merge(
        source_index.reset_index(drop=True),
        left_on="source_api_record_id", right_on="api_record_id",
        how="left", validate="many_to_one", indicator=True,
        suffixes=("_lineage", "_snapshot"),
    )
    assert slot_sources._merge.eq("both").all()
    assert slot_sources.source_horse_id.astype(str).eq(slot_sources.horse_id.astype(str)).all()
    assert slot_sources.source_race_date.astype(str).eq(slot_sources.race_date.astype(str)).all()
    assert slot_sources.source_distance_m.eq(slot_sources.race_distance_m).all()
    assert slot_sources.source_started.eq(slot_sources.started).all()

    requested_ids = sorted(int(value) for value in slots.source_api_record_id.unique())
    db_baseline = json.loads(TIME_EXTRACTION.read_text(encoding="utf-8"))
    assert db_baseline["db_sha256"] == "a878a40fd5dc28e1385801c40136e506d9e3bc406e357e4158e5eb6883f5f21e"
    assert db_baseline["source_view"] == QUALITY_VIEW
    assert DB_PATH.stat().st_size == 1793323008

    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        connection.execute("PRAGMA query_only=ON")
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        time_statuses = status_inventory(
            connection, TIME_VIEW, "time_status", KNOWN_TIME_STATUSES
        )
        order_statuses = status_inventory(
            connection, ORDER_VIEW, "quality_order_status", ALLOWED_ORDER_STATUSES
        )
        group_statuses = status_inventory(
            connection, GROUP_VIEW, "group_status", ALLOWED_GROUP_STATUSES
        )

        time_rows = sql_rows_by_ids(
            connection,
            TIME_VIEW,
            "api_record_id,race_date,meet_code,race_number,horse_id,field_name,time_seconds,time_status",
            requested_ids,
            "AND field_name IN (?,?,?)",
            (FIELDS["s1f"]["time_field"], FIELDS["g3f"]["time_field"], FIELDS["g1f"]["time_field"]),
        )
        times_long = pd.DataFrame(time_rows, columns=[
            "api_record_id", "race_date", "meet_code", "race_number", "horse_id",
            "field_name", "time_seconds", "time_status",
        ])

        relevant_races = sorted({
            (str(row.source_race_date), int(row.meet_code), int(row.race_number))
            for row in slot_sources[["source_race_date", "meet_code", "race_number"]]
            .drop_duplicates().itertuples(index=False)
        })
        order_rows = sql_rows_by_races(
            connection, ORDER_VIEW,
            "race_date,meet_code,race_number,field_name,quality_order_status",
            relevant_races, "AND field_name IN (?,?)",
            (FIELDS["s1f"]["order_field"], FIELDS["g1f"]["order_field"]),
        )
        group_rows = sql_rows_by_races(
            connection, GROUP_VIEW,
            "race_date,meet_code,race_number,point,field_name,group_status",
            relevant_races, "AND point IN (?,?)",
            (FIELDS["s1f"]["point"], FIELDS["g1f"]["point"]),
        )
        order_conflict_rows = [row for row in order_rows if hold_match(row[4])]
        group_conflict_rows = [row for row in group_rows if hold_match(row[5])]
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
    finally:
        connection.close()

    assert len(times_long) == 3 * len(requested_ids)
    assert not times_long.duplicated(["api_record_id", "field_name"]).any()
    assert times_long.field_name.isin([v["time_field"] for v in FIELDS.values()]).all()
    assert times_long.time_status.dropna().isin(KNOWN_TIME_STATUSES).all()

    expected_review_cases = [
        (178142, "jeS1fTime", 20.0, "website_corrected"),
        (180747, "jeS1fTime", 17.8, "website_corrected"),
        (191451, "jeG1fTime", None, "unresolved_official_website_anomaly"),
        (190686, "jeG1fTime", 16.0, "website_corrected"),
    ]
    review_case_checks = []
    for record_id, field_name, expected_seconds, expected_status in expected_review_cases:
        selected = times_long.loc[
            times_long.api_record_id.eq(record_id) & times_long.field_name.eq(field_name)
        ]
        assert len(selected) == 1, (record_id, field_name, len(selected))
        actual_seconds = selected.time_seconds.iloc[0]
        actual_seconds = None if pd.isna(actual_seconds) else float(actual_seconds)
        actual_status = str(selected.time_status.iloc[0])
        assert (actual_seconds, actual_status) == (expected_seconds, expected_status)
        review_case_checks.append({
            "api_record_id": record_id,
            "field_name": field_name,
            "time_seconds": actual_seconds,
            "time_status": actual_status,
            "slot_references": int(slots.source_api_record_id.eq(record_id).sum()),
        })

    # The quality main view obtains section times by joining its aggregate
    # jeju_race_section_times view, which aggregates these exact selected
    # jeju_race_section_time_values by API4 record ID. The order and group
    # quality aggregates are likewise built from their respective *_values
    # views. Verify those dependency edges to make this extraction equivalent.
    sql_map = {name: sql or "" for name, sql in connection_rows_for_view_sql()}
    expected_sql_views = {
        TIME_VIEW, "jeju_race_section_times", "jeju_race_postrace_sections_2026",
        "jeju_race_postrace_sections_reviewed_2026", QUALITY_VIEW,
        ORDER_VIEW, GROUP_VIEW, "jeju_race_section_order_quality",
        "jeju_race_section_group_quality",
    }
    assert set(sql_map) == expected_sql_views, (set(sql_map), expected_sql_views)
    view_sql_hashes = {
        name: hashlib.sha256(sql.encode("utf-8")).hexdigest()
        for name, sql in sorted(sql_map.items())
    }
    required_edges = {
        "time_values_into_time_aggregate": ("jeju_race_section_times", TIME_VIEW),
        "time_aggregate_into_postrace": ("jeju_race_postrace_sections_2026", "jeju_race_section_times"),
        "postrace_into_reviewed": ("jeju_race_postrace_sections_reviewed_2026", "jeju_race_postrace_sections_2026"),
        "reviewed_into_quality": (QUALITY_VIEW, "jeju_race_postrace_sections_reviewed_2026"),
        "order_values_into_order_aggregate": ("jeju_race_section_order_quality", ORDER_VIEW),
        "group_values_into_group_aggregate": ("jeju_race_section_group_quality", GROUP_VIEW),
        "order_aggregate_into_quality": (QUALITY_VIEW, "jeju_race_section_order_quality"),
        "group_aggregate_into_quality": (QUALITY_VIEW, "jeju_race_section_group_quality"),
    }
    for edge_name, (view_name, source_name) in required_edges.items():
        assert source_name in sql_map[view_name], (edge_name, view_name, source_name)

    # Fail closed on any current or future quality status that names a
    # conflict, unapplied review, or changed source. Race/section masks apply
    # to all referenced starters at that exact point only.
    conflict_rows = []
    for row in order_conflict_rows:
        day, meet, race, field, status = row
        point = {"sjS1fOrd": "S1F", "sjG1fOrd": "G1F"}[field]
        conflict_rows.append((str(day), int(meet), int(race), point, str(status), "order"))
    for row in group_conflict_rows:
        day, meet, race, point, field, status = row
        conflict_rows.append((str(day), int(meet), int(race), str(point), str(status), "group"))
    conflict_frame = pd.DataFrame(conflict_rows, columns=[
        "race_date", "meet_code", "race_number", "point", "status", "source_kind",
    ])
    conflict_frame = conflict_frame.loc[conflict_frame.point.isin(["S1F", "G1F"])].copy()
    conflict_frame["race_key"] = (
        conflict_frame.race_date + "_"
        + conflict_frame.meet_code.astype(str) + "_"
        + conflict_frame.race_number.astype(str)
    )
    conflict_points = {
        (str(row.race_key), str(row.point))
        for row in conflict_frame.itertuples(index=False)
    }

    times = times_long.pivot(
        index="api_record_id", columns="field_name", values=["time_seconds", "time_status"]
    )
    times.columns = [f"{field}__{value}" for value, field in times.columns]
    times = times.reset_index()
    slots_ready = slot_sources.merge(
        times, left_on="source_api_record_id", right_on="api_record_id",
        how="left", validate="many_to_one", suffixes=("", "_selected"),
    )
    assert slots_ready.source_api_record_id.isin(times_long.api_record_id).all()
    assert slots_ready.api_record_id_selected.eq(slots_ready.source_api_record_id).all()
    assert slots_ready.race_number.notna().all() and slots_ready.meet_code.notna().all()

    slots_ready["source_race_key"] = (
        slots_ready.race_date.astype(str) + "_"
        + slots_ready.meet_code.astype("Int64").astype(str) + "_"
        + slots_ready.race_number.astype("Int64").astype(str)
    )
    slots_ready["s1f_conflict_hold"] = slots_ready.source_race_key.map(
        lambda key: (str(key), "S1F") in conflict_points
    )
    slots_ready["g1f_conflict_hold"] = slots_ready.source_race_key.map(
        lambda key: (str(key), "G1F") in conflict_points
    )

    field_outputs = {}
    field_summary = []
    for name, spec in FIELDS.items():
        time_col = f"{spec['time_field']}__time_seconds"
        status_col = f"{spec['time_field']}__time_status"
        value = pd.to_numeric(slots_ready[time_col], errors="coerce")
        status_ok = slots_ready[status_col].isin(ALLOWED_TIME_STATUSES)
        positive = value.notna() & np.isfinite(value) & value.gt(0)
        valid_time = slots_ready.valid_time.eq(True)
        if name == "s1f":
            clear_point = ~slots_ready.s1f_conflict_hold
        elif name == "g1f":
            clear_point = ~slots_ready.g1f_conflict_hold
        else:
            clear_point = pd.Series(True, index=slots_ready.index)
        eligible = positive & status_ok & valid_time & clear_point
        slots_ready[f"{name}_selected_seconds"] = value
        slots_ready[f"{name}_selected_status"] = slots_ready[status_col]
        slots_ready[f"{name}_eligible"] = eligible
        slots_ready[f"{name}_used_seconds"] = value.where(eligible)
        field_outputs[name] = f"{name}_used_seconds"
        field_summary.append({
            "section": name,
            "actual_slot_rows": int(len(slots_ready)),
            "source_snapshot_valid_time_rows": int(valid_time.sum()),
            "positive_quality_selected_time_rows": int((positive & status_ok).sum()),
            "eligible_slot_rows": int(eligible.sum()),
            "excluded_for_invalid_source_time": int((positive & status_ok & ~valid_time).sum()),
            "excluded_for_section_conflict": int((positive & status_ok & valid_time & ~clear_point).sum()),
            "missing_or_unusable_values_kept_as_slots": int((~eligible).sum()),
            "time_status_counts_on_slots": {
                str(key): int(value)
                for key, value in slots_ready[status_col].fillna("<NULL>").value_counts().items()
            },
        })

    per_target = slots_ready.groupby("target_api_record_id", sort=False).agg(
        actual_same_distance_slot_n=("source_api_record_id", "size"),
        s1f_valid_n=("s1f_eligible", "sum"),
        g3f_valid_n=("g3f_eligible", "sum"),
        g1f_valid_n=("g1f_eligible", "sum"),
        history_s1f_mean5_seconds=("s1f_used_seconds", "mean"),
        history_g3f_mean5_seconds=("g3f_used_seconds", "mean"),
        history_g1f_mean5_seconds=("g1f_used_seconds", "mean"),
    ).reset_index().rename(columns={"target_api_record_id": "api_record_id"})

    targets = features[[
        "api_record_id", "year", "race_date", "race_id", "distance_m", "observed_starts",
    ]].copy()
    feature_reconstruction = targets.merge(
        per_target, on="api_record_id", how="left", validate="one_to_one"
    )
    no_slots = feature_reconstruction.actual_same_distance_slot_n.isna()
    feature_reconstruction.loc[no_slots, "actual_same_distance_slot_n"] = 0
    for col in ("s1f_valid_n", "g3f_valid_n", "g1f_valid_n"):
        feature_reconstruction[col] = feature_reconstruction[col].fillna(0)
    feature_reconstruction["actual_same_distance_slot_n"] = (
        feature_reconstruction.actual_same_distance_slot_n.astype("int64")
    )
    for col in ("s1f_valid_n", "g3f_valid_n", "g1f_valid_n"):
        feature_reconstruction[col] = feature_reconstruction[col].astype("int64")
    assert feature_reconstruction.actual_same_distance_slot_n.le(5).all()
    for valid_col in ("s1f_valid_n", "g3f_valid_n", "g1f_valid_n"):
        assert feature_reconstruction[valid_col].le(
            feature_reconstruction.actual_same_distance_slot_n
        ).all()
    for section in FIELDS:
        mean_col = f"history_{section}_mean5_seconds"
        valid_col = f"{section}_valid_n"
        assert feature_reconstruction.loc[
            feature_reconstruction[valid_col].eq(0), mean_col
        ].isna().all()

    feature_reconstruction["experience_group"] = pd.cut(
        feature_reconstruction.observed_starts,
        [-1, 0, 4, np.inf], labels=["0", "1_4", "5_plus"],
    ).astype("string")

    support_rows = []
    for group_kind, keys in (
        ("distance_m", ["distance_m"]),
        ("year", ["year"]),
        ("distance_year", ["distance_m", "year"]),
        ("experience_group", ["experience_group"]),
    ):
        for key, group in feature_reconstruction.groupby(keys, dropna=False, sort=True):
            values = key if isinstance(key, tuple) else (key,)
            keydata = dict(zip(keys, [str(x) for x in values]))
            for section in FIELDS:
                col = f"{section}_valid_n"
                dist = group[col].value_counts().reindex(range(6), fill_value=0)
                support_rows.append({
                    "group_kind": group_kind,
                    **keydata,
                    "section": section,
                    "target_rows": int(len(group)),
                    "targets_with_any_valid_slot": int(group[col].gt(0).sum()),
                    "eligible_historical_slots": int(group[col].sum()),
                    **{f"targets_n_{n}": int(dist.loc[n]) for n in range(6)},
                })

    support = pd.DataFrame(support_rows)
    evaluation = feature_reconstruction.loc[feature_reconstruction.year.ge(2024)]
    quality_view_sql = sql_map[QUALITY_VIEW]
    same_distance_times = TIME_VIEW in sql_map["jeju_race_section_times"]
    assert same_distance_times
    checks = {
        "db_opened_read_only_query_only": True,
        "f1_target_population_52155_rows_5206_races": len(features) == 52155 and features.race_id.nunique() == 5206,
        "all_178459_actual_slot_ids_match_f1_last5_order": True,
        "slots_all_started_same_horse_same_distance_t_minus_2": bool(
            slot_sources.source_started.eq(True).all()
            and slot_sources.source_horse_id.astype(str).eq(slot_sources.horse_id.astype(str)).all()
            and slot_sources.source_distance_m.eq(slot_sources.race_distance_m).all()
            and slot_sources.source_race_date.astype(str).le(slot_sources.target_cutoff.astype(str)).all()
        ),
        "time_values_duplicate_free_and_all_requested_ids_present": (
            len(times_long) == len(requested_ids) * 3
            and times_long.groupby("api_record_id").field_name.nunique().eq(3).all()
        ),
        "main_quality_time_chain_uses_same_selected_time_values": same_distance_times
        and all(source_name in sql_map[view_name] for view_name, source_name in required_edges.values()),
        "status_domains_known_and_no_unrecognized_values": True,
        "slot_window_preserved_when_time_unusable": int(len(slots_ready)) == 178459,
        "no_backfill_more_than_five_actual_slots": feature_reconstruction.actual_same_distance_slot_n.le(5).all(),
        "no_mean_when_valid_count_zero": all(
            feature_reconstruction.loc[feature_reconstruction[f"{s}_valid_n"].eq(0), f"history_{s}_mean5_seconds"].isna().all()
            for s in FIELDS
        ),
        "evaluation_population_17412_rows_1779_races": len(evaluation) == 17412 and evaluation.race_id.nunique() == 1779,
        "fail_closed_order_and_group_conflict_markers_used": set(HOLD_MARKERS).issuperset({"conflict", "not_applied", "source_changed"})
        and len(order_rows) > 0 and len(group_rows) > 0,
        "no_model_score_fit_temperature_or_prediction_metric": True,
    }
    assert all(checks.values()), checks

    manifest_paths = [F1_FEATURES, F1_LINEAGE, SOURCE_SNAPSHOT, TIME_EXTRACTION]
    refs = {
        path.relative_to(ROOT).as_posix(): {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in manifest_paths
    }
    report = {
        "audit_status": "independent_source_slot_availability_reconstruction",
        "fit_executed": False,
        "saved_model_scoring_executed": False,
        "temperature_optimization_executed": False,
        "prediction_metrics_calculated": False,
        "database_write_executed": False,
        "quality_view": QUALITY_VIEW,
        "quality_view_sql_chain_equivalence": {
            name: {"source_view": pair[1], "present_in_sql": True}
            for name, pair in required_edges.items()
        },
        "quality_view_dependency_ddl_sha256": view_sql_hashes,
        "database_reference": {
            "sha256_from_existing_time_extraction_lock": db_baseline["db_sha256"],
            "current_bytes": DB_PATH.stat().st_size,
            "current_sha_rehashed": False,
            "reason": "Reuse the existing locked DB digest; avoid repeating a 1.8 GB full-file hash.",
        },
        "f1_population": {
            "rows": int(len(features)),
            "races": int(features.race_id.nunique()),
            "evaluation_rows": int(len(evaluation)),
            "evaluation_races": int(evaluation.race_id.nunique()),
            "evaluation_dates": int(evaluation.race_date.nunique()),
            "source_snapshot_rows_denominator": int(len(source)),
            "actual_same_distance_slots": int(len(slots)),
            "distinct_slot_source_ids": int(len(requested_ids)),
            "targets_with_any_actual_slot": int(slots.target_api_record_id.nunique()),
        },
        "quality_status_counts": {
            "time_status": time_statuses,
            "order_status": order_statuses,
            "group_status": group_statuses,
        },
        "known_quality_selected_review_case_checks": review_case_checks,
        "field_slot_audit": field_summary,
        "race_section_conflict_mask": {
            "order_conflict_rows_selected": int(len(order_conflict_rows)),
            "group_conflict_rows_selected": int(len(group_conflict_rows)),
            "distinct_race_points": int(len(conflict_points)),
            "specific_scope": "S1F/G1F conflict status on the exact race+point; all referenced horses at that point held; other points and slots retained.",
            "masked_race_points": sorted([{"race_key": race, "point": point} for race, point in conflict_points], key=lambda x: (x["race_key"], x["point"])),
        },
        "preflight_checks": checks,
        "references": refs,
        "review_code_sha256": sha256(Path(__file__)),
    }

    write_csv_new(OUT / "independent_slot_lineage_and_selected_times.csv", slots_ready[
        ["target_api_record_id", "source_api_record_id", "source_race_date", "target_cutoff",
         "target_horse_id", "source_horse_id", "target_distance_m", "source_distance_m",
         "source_started", "valid_time", "s1f_selected_seconds", "s1f_selected_status",
         "s1f_conflict_hold", "s1f_eligible", "g3f_selected_seconds", "g3f_selected_status",
         "g3f_eligible", "g1f_selected_seconds", "g1f_selected_status", "g1f_conflict_hold",
         "g1f_eligible"]
    ])
    write_csv_new(OUT / "independent_target_feature_reconstruction.csv", feature_reconstruction)
    write_csv_new(OUT / "independent_support_by_distance_year_experience.csv", support)
    write_json_new(OUT / "independent_source_availability_receipt.json", report)
    print(json.dumps({
        "audit_status": report["audit_status"],
        "f1_population": report["f1_population"],
        "field_slot_audit": field_summary,
        "quality_status_counts": report["quality_status_counts"],
        "race_section_conflict_mask": report["race_section_conflict_mask"],
    }, ensure_ascii=False, indent=2))


def connection_rows_for_view_sql():
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        connection.execute("PRAGMA query_only=ON")
        names = (
            TIME_VIEW,
            "jeju_race_section_times",
            "jeju_race_postrace_sections_2026",
            "jeju_race_postrace_sections_reviewed_2026",
            QUALITY_VIEW,
            ORDER_VIEW,
            GROUP_VIEW,
            ORDER_VIEW.replace("_values", ""),
            GROUP_VIEW.replace("_values", ""),
        )
        placeholders = ",".join("?" for _ in names)
        return connection.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='view' "
            f"AND name IN ({placeholders})",
            names,
        ).fetchall()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
