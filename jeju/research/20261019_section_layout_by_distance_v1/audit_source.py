"""Read-only audit of Jeju per-horse section-time support by race distance."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
SNAPSHOT = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet"
START_DATE = "2017-01-01"
END_DATE = "2026-09-19"
DISTANCES = [400, 800, 900, 1000, 1110, 1200, 1300, 1400, 1610]
TIME_FIELDS = ["jeS1fTime", "je_1cTime", "je_2cTime", "je_3cTime", "je_4cTime", "jeG3fTime", "jeG1fTime"]
FIELD_LABELS = {
    "jeS1fTime": "S1F",
    "je_1cTime": "1C",
    "je_2cTime": "2C",
    "je_3cTime": "3C",
    "je_4cTime": "4C",
    "jeG3fTime": "G3F_duration",
    "jeG1fTime": "G1F_duration",
}
STATUS_ALLOWED = {"api_positive_unreviewed", "website_corrected"}
STATUS_HOLD = {
    "unresolved_official_website_anomaly",
    "website_review_not_applied",
    "api_source_changed_since_review",
}
TOL = 1e-8


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return str(value) if not isinstance(value, (str, int, bool)) else value


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def summarize(values: pd.Series) -> dict:
    x = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if x.empty:
        return {"min": None, "p10": None, "median": None, "p90": None, "max": None}
    q = x.quantile([0.1, 0.5, 0.9])
    return {
        "min": float(x.min()),
        "p10": float(q.loc[0.1]),
        "median": float(q.loc[0.5]),
        "p90": float(q.loc[0.9]),
        "max": float(x.max()),
    }


def main() -> None:
    frozen_roster = pd.read_parquet(SNAPSHOT)
    frozen_snapshot_rows = int(len(frozen_roster))
    roster_all = frozen_roster.loc[
        frozen_roster["race_date"].between(START_DATE, END_DATE)
        & frozen_roster["meet_code"].eq(2)
        & frozen_roster["race_distance_m"].isin(DISTANCES)
    ].copy()
    roster = roster_all.loc[roster_all["started"].astype(bool)].copy()
    roster["api_record_id"] = pd.to_numeric(roster["api_record_id"], errors="raise").astype("int64")
    roster["race_distance_m"] = pd.to_numeric(roster["race_distance_m"], errors="raise").astype("int64")
    roster = roster.sort_values("api_record_id").reset_index(drop=True)
    assert roster.api_record_id.is_unique
    assert not roster.horse_id.astype(str).eq("3005648").any(), "project-excluded horse appeared in the scoped starter roster"

    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA temp_store=MEMORY")
    # Connection-local TEMP IDs are populated while the main DB remains mode=ro.
    # After setting query_only=ON, this connection performs SELECTs only.
    con.execute("CREATE TEMP TABLE audit_ids(api_record_id INTEGER PRIMARY KEY)")
    con.executemany("INSERT INTO audit_ids(api_record_id) VALUES (?)", [(int(x),) for x in roster.api_record_id])
    con.commit()
    con.execute("PRAGMA query_only=ON")
    assert con.execute("PRAGMA query_only").fetchone()[0] == 1
    con.execute("BEGIN")
    con.execute("SELECT api_record_id FROM api_records ORDER BY api_record_id LIMIT 1").fetchone()
    data_version_start = int(con.execute("PRAGMA data_version").fetchone()[0])
    view_row = con.execute(
        "SELECT sql FROM sqlite_master WHERE type=? AND name=?",
        ("view", "jeju_race_section_time_values"),
    ).fetchone()
    if not view_row or not view_row[0]:
        raise RuntimeError("quality-selected time view is missing")
    view_sql_sha256 = sha256_bytes(view_row[0].encode("utf-8"))
    time_marks = ",".join("?" for _ in TIME_FIELDS)
    query = (
        "SELECT v.api_record_id,v.race_date,v.meet_code,v.race_number,v.horse_number,v.horse_id,"
        "v.field_name,v.api_value_json_type,v.api_payload_sha256,v.api_source_artifact_id,"
        "v.api_source_page_sha256,v.api_source_page_path,v.time_seconds,v.time_status "
        "FROM jeju_race_section_time_values v JOIN audit_ids x USING(api_record_id) "
        f"WHERE v.field_name IN ({time_marks}) "
        "ORDER BY v.api_record_id,v.field_name"
    )
    times = pd.read_sql_query(query, con, params=TIME_FIELDS)
    data_version_end = int(con.execute("PRAGMA data_version").fetchone()[0])
    query_only = int(con.execute("PRAGMA query_only").fetchone()[0])
    con.close()

    assert query_only == 1
    assert not times.api_record_id.is_unique
    assert not times.duplicated(["api_record_id", "field_name"]).any()
    assert set(times.field_name.unique()) == set(TIME_FIELDS)
    assert set(times.api_record_id.astype("int64")) == set(roster.api_record_id)
    assert times.groupby("api_record_id").field_name.nunique().eq(len(TIME_FIELDS)).all()

    times["api_record_id"] = times.api_record_id.astype("int64")
    times = times.merge(
        roster[[
            "api_record_id", "race_date", "meet_code", "race_number", "horse_number", "horse_id",
            "race_distance_m", "finish_position", "finish_time_seconds", "valid_time", "race_id",
        ]],
        on=["api_record_id", "race_date", "meet_code", "race_number", "horse_number", "horse_id"],
        how="left",
        validate="many_to_one",
        suffixes=("_quality", "_snapshot"),
    )
    assert times.race_distance_m.notna().all()
    times["accepted"] = (
        times.time_status.isin(STATUS_ALLOWED)
        & pd.to_numeric(times.time_seconds, errors="coerce").gt(0)
    )
    times["field_label"] = times.field_name.map(FIELD_LABELS)

    count_rows = []
    for distance in DISTANCES:
        all_d = roster_all.loc[roster_all.race_distance_m.eq(distance)]
        started_d = roster.loc[roster.race_distance_m.eq(distance)]
        count_rows.append({
            "race_distance_m": distance,
            "candidate_rows": int(len(all_d)),
            "candidate_races": int(all_d.race_id.nunique()),
            "started_rows": int(len(started_d)),
            "started_races": int(started_d.race_id.nunique()),
            "nonstarted_rows": int(len(all_d) - len(started_d)),
            "first_race_date": str(all_d.race_date.min()) if len(all_d) else None,
            "last_race_date": str(all_d.race_date.max()) if len(all_d) else None,
            "positive_finish_time_rows": int(pd.to_numeric(started_d.finish_time_seconds, errors="coerce").gt(0).sum()),
            "positive_finish_time_and_valid_time_rows": int((pd.to_numeric(started_d.finish_time_seconds, errors="coerce").gt(0) & started_d.valid_time.astype(bool)).sum()),
            "valid_time_rows": int(started_d.valid_time.astype(bool).sum()),
        })
    counts = pd.DataFrame(count_rows)

    coverage_rows = []
    status_rows = []
    grouped = times.groupby(["race_distance_m", "field_name"], dropna=False)
    for distance in DISTANCES:
        starter_n = int(roster.race_distance_m.eq(distance).sum())
        for field_name in TIME_FIELDS:
            sub = grouped.get_group((distance, field_name)) if (distance, field_name) in grouped.groups else times.iloc[0:0]
            accepted = sub.loc[sub.accepted]
            coverage_rows.append({
                "race_distance_m": distance,
                "field": FIELD_LABELS[field_name],
                "started_rows": starter_n,
                "selected_positive_time_rows": int(sub.accepted.sum()),
                "selected_positive_time_coverage_of_starters_pct": round(100 * float(sub.accepted.sum()) / starter_n, 4) if starter_n else None,
                "races_with_selected_positive_time": int(accepted.race_id.nunique()),
                "time_value_review_hold_rows": int(sub.time_status.isin(STATUS_HOLD).sum()),
                "api_positive_unreviewed_rows": int((sub.time_status == "api_positive_unreviewed").sum()),
                "website_corrected_rows": int((sub.time_status == "website_corrected").sum()),
                "other_unavailable_rows": int((~sub.time_status.isin(STATUS_HOLD | STATUS_ALLOWED)).sum()),
            })
            for status, n in sub.time_status.fillna("<NULL>").value_counts().sort_index().items():
                status_rows.append({"race_distance_m": distance, "field": FIELD_LABELS[field_name], "time_status": status, "rows": int(n)})
    coverage = pd.DataFrame(coverage_rows)
    status_counts = pd.DataFrame(status_rows)

    pivot = times.pivot(index="api_record_id", columns="field_name", values="time_seconds")
    status_pivot = times.pivot(index="api_record_id", columns="field_name", values="time_status")
    time_pivot = pd.DataFrame(index=roster.api_record_id.astype("int64"))
    for field_name, label in FIELD_LABELS.items():
        time_pivot[label] = pd.to_numeric(pivot[field_name].reindex(time_pivot.index), errors="coerce")
        time_pivot[label + "_accepted"] = status_pivot[field_name].reindex(time_pivot.index).isin(STATUS_ALLOWED) & time_pivot[label].gt(0)
    meta = roster.set_index("api_record_id").copy()
    time_pivot["race_distance_m"] = meta.race_distance_m
    time_pivot["race_id"] = meta.race_id
    time_pivot["finish_time_seconds"] = pd.to_numeric(meta.finish_time_seconds, errors="coerce")
    time_pivot["valid_time"] = meta.valid_time.astype(bool)
    time_pivot["finish_accepted"] = time_pivot.finish_time_seconds.gt(0) & time_pivot.valid_time
    time_pivot["G3F_crossing_elapsed_seconds"] = np.where(
        time_pivot.finish_accepted & time_pivot.G3F_duration_accepted,
        time_pivot.finish_time_seconds - time_pivot.G3F_duration,
        np.nan,
    )
    time_pivot["G1F_crossing_elapsed_seconds"] = np.where(
        time_pivot.finish_accepted & time_pivot.G1F_duration_accepted,
        time_pivot.finish_time_seconds - time_pivot.G1F_duration,
        np.nan,
    )
    time_pivot["Finish"] = np.where(time_pivot.finish_accepted, time_pivot.finish_time_seconds, np.nan)
    for name in ["S1F", "1C", "2C", "3C", "4C"]:
        time_pivot[name] = time_pivot[name].where(time_pivot[name + "_accepted"])
    endpoint_names = ["S1F", "1C", "2C", "3C", "4C", "G3F_crossing_elapsed_seconds", "G1F_crossing_elapsed_seconds", "Finish"]

    relation_rows = []
    for distance in DISTANCES:
        ids = meta.index[meta.race_distance_m.eq(distance)]
        data = time_pivot.loc[ids]
        for i, left in enumerate(endpoint_names):
            for right in endpoint_names[i + 1:]:
                pair = data[[left, right]].dropna()
                delta = pair[right] - pair[left]
                relation_rows.append({
                    "race_distance_m": distance,
                    "left_endpoint": left,
                    "right_endpoint": right,
                    "pair_rows": int(len(pair)),
                    "left_before_right_rows": int((delta > TOL).sum()),
                    "equal_within_1e_8_rows": int((delta.abs() <= TOL).sum()),
                    "left_after_right_rows": int((delta < -TOL).sum()),
                    "delta_right_minus_left_min_seconds": float(delta.min()) if len(delta) else None,
                    "delta_right_minus_left_median_seconds": float(delta.median()) if len(delta) else None,
                    "delta_right_minus_left_p90_seconds": float(delta.quantile(.9)) if len(delta) else None,
                    "delta_right_minus_left_max_seconds": float(delta.max()) if len(delta) else None,
                })
    relations = pd.DataFrame(relation_rows)

    g3f_rows = []
    for distance in DISTANCES:
        data = time_pivot.loc[meta.index[meta.race_distance_m.eq(distance)]].copy()
        both = data.loc[data["3C"].notna() & data["G3F_crossing_elapsed_seconds"].notna()].copy()
        residual = both["3C"] - both["G3F_crossing_elapsed_seconds"]
        g3f_rows.append({
            "race_distance_m": distance,
            "rows_with_3C_G3F_and_valid_finish": int(len(both)),
            "exact_equal_within_1e_8_rows": int((residual.abs() <= TOL).sum()),
            "within_0_15_seconds_rows": int((residual.abs() <= .15 + TOL).sum()),
            "3C_before_G3F_crossing_rows": int((residual < -TOL).sum()),
            "3C_after_G3F_crossing_rows": int((residual > TOL).sum()),
            **{f"residual_3C_minus_T_minus_G3F_{key}_seconds": value for key, value in summarize(residual).items()},
            "maximum_absolute_residual_seconds": float(residual.abs().max()) if len(residual) else None,
        })
    g3f_consistency = pd.DataFrame(g3f_rows)

    chronology_rows = []
    nominal_orders = {
        400: ["S1F", "G1F_crossing_elapsed_seconds", "Finish"],
        800: ["S1F", "3C", "4C", "G1F_crossing_elapsed_seconds", "Finish"],
        900: ["S1F", "3C", "4C", "G1F_crossing_elapsed_seconds", "Finish"],
        1000: ["S1F", "3C", "4C", "G1F_crossing_elapsed_seconds", "Finish"],
        1110: ["S1F", "3C", "4C", "G1F_crossing_elapsed_seconds", "Finish"],
        1200: ["S1F", "3C", "4C", "G1F_crossing_elapsed_seconds", "Finish"],
        1300: ["2C", "S1F", "3C", "4C", "G1F_crossing_elapsed_seconds", "Finish"],
        1400: ["S1F", "2C", "3C", "4C", "G1F_crossing_elapsed_seconds", "Finish"],
        1610: ["S1F", "1C", "2C", "3C", "4C", "G1F_crossing_elapsed_seconds", "Finish"],
    }
    for distance, sequence in nominal_orders.items():
        data = time_pivot.loc[meta.index[meta.race_distance_m.eq(distance)]]
        pair_total = 0
        pair_ordered = 0
        pair_equal = 0
        pair_reversed = 0
        for left, right in zip(sequence, sequence[1:]):
            pair = data[[left, right]].dropna()
            if pair.empty:
                continue
            delta = pair[right] - pair[left]
            pair_total += len(pair)
            pair_ordered += int((delta > TOL).sum())
            pair_equal += int((delta.abs() <= TOL).sum())
            pair_reversed += int((delta < -TOL).sum())
        endpoints = data[sequence].dropna()
        if len(endpoints):
            arr = endpoints.to_numpy(dtype=float)
            fully_monotone = int((np.diff(arr, axis=1) >= -TOL).all(axis=1).sum())
        else:
            fully_monotone = 0
        chronology_rows.append({
            "race_distance_m": distance,
            "nominal_endpoint_sequence": " > ".join(sequence),
            "adjacent_pairs_with_both_endpoints": pair_total,
            "adjacent_pairs_in_time_order": pair_ordered,
            "adjacent_pairs_equal_within_1e_8": pair_equal,
            "adjacent_pairs_reversed": pair_reversed,
            "rows_with_all_sequence_endpoints": int(len(endpoints)),
            "all_endpoints_monotone_rows": fully_monotone,
        })
    chronology = pd.DataFrame(chronology_rows)

    profile_specs = {
        400: {
            "support_class": "legacy400_separate",
            "proposed_nonoverlap_segment_count": 2,
            "ordered_boundary_chain": "Start → S1F (= T−G1F crossing; 200m) → Finish (400m)",
            "numeric_aliases": "S1F = T−G1F crossing in all 1,257 rows with both endpoints",
            "geometry_and_coverage_note": "Only S1F/G1F are positive; 1C–4C and G3F are absent. Retain as a separate legacy profile; do not join to the standard distance family.",
        },
        800: {
            "support_class": "standard_short",
            "proposed_nonoverlap_segment_count": 4,
            "ordered_boundary_chain": "Start → S1F (= 3C = T−G3F crossing; 200m) → 4C (~400m) → T−G1F crossing (600m) → Finish (800m)",
            "numeric_aliases": "S1F = 3C in all 13,803 shared rows; 3C = T−G3F in all 13,799 shared rows",
            "geometry_and_coverage_note": "S1F and duration-derived crossings have exact official distances; C3/C4 retain approximate corner labels. 1C/2C unavailable.",
        },
        900: {
            "support_class": "standard",
            "proposed_nonoverlap_segment_count": 5,
            "ordered_boundary_chain": "Start → S1F (200m) → 3C (= T−G3F crossing; ~300m) → 4C (~500m) → T−G1F crossing (700m) → Finish (900m)",
            "numeric_aliases": "3C = T−G3F in all 9,715 rows with both endpoints; 1C/2C unavailable",
            "geometry_and_coverage_note": "S1F and duration-derived crossings have exact official distances; C3/C4 retain approximate corner labels.",
        },
        1000: {
            "support_class": "standard_existing_study",
            "proposed_nonoverlap_segment_count": 5,
            "ordered_boundary_chain": "Start → S1F (200m) → 3C (= T−G3F crossing; ~400m) → 4C (~600m) → T−G1F crossing (800m) → Finish (1000m)",
            "numeric_aliases": "3C = T−G3F in all 15,502 rows with both endpoints; 1C/2C unavailable",
            "geometry_and_coverage_note": "This reproduces the existing measured five-interval layout; C3/C4 retain approximate corner labels.",
        },
        1110: {
            "support_class": "standard_s1f_210m_exception",
            "proposed_nonoverlap_segment_count": 5,
            "ordered_boundary_chain": "Start → S1F (210m) → 3C (= T−G3F crossing; ~510m) → 4C (~710m) → T−G1F crossing (910m) → Finish (1110m)",
            "numeric_aliases": "3C = T−G3F in all 10,700 rows with both endpoints; 1C/2C unavailable",
            "geometry_and_coverage_note": "S1F is officially 210m at 1110m; do not scale it to 200m. C3/C4 retain approximate corner labels.",
        },
        1200: {
            "support_class": "standard",
            "proposed_nonoverlap_segment_count": 5,
            "ordered_boundary_chain": "Start → S1F (200m) → 3C (= T−G3F crossing; ~600m) → 4C (~800m) → T−G1F crossing (1000m) → Finish (1200m)",
            "numeric_aliases": "3C = T−G3F in all 5,176 rows with both endpoints; one G1F value remains held by website review",
            "geometry_and_coverage_note": "S1F and duration-derived crossings have exact official distances; C3/C4 retain approximate corner labels.",
        },
        1300: {
            "support_class": "standard_with_early_2C",
            "proposed_nonoverlap_segment_count": 6,
            "ordered_boundary_chain": "Start → 2C (~100m) → S1F (200m) → 3C (= T−G3F crossing; ~700m) → 4C (~900m) → T−G1F crossing (1100m) → Finish (1300m)",
            "numeric_aliases": "3C = T−G3F in all 666 rows with both endpoints; 2C precedes S1F in all 666 rows (median C2−S1F = −8.3s)",
            "geometry_and_coverage_note": "C2 is approximately 1200m from the finish (about 100m elapsed); C3/C4 remain approximate.",
        },
        1400: {
            "support_class": "standard_with_early_2C_duplicate",
            "proposed_nonoverlap_segment_count": 5,
            "ordered_boundary_chain": "Start → S1F (= 2C; 200m nominal) → 3C (= T−G3F crossing; ~800m) → 4C (~1000m) → T−G1F crossing (1200m) → Finish (1400m)",
            "numeric_aliases": "S1F = 2C in all 951 rows; 3C = T−G3F in all 951 rows",
            "geometry_and_coverage_note": "Keep both S1F/C2 source labels on one numeric boundary; C2 is an approximate corner position.",
        },
        1610: {
            "support_class": "standard_with_early_1C_duplicate_small_support",
            "proposed_nonoverlap_segment_count": 6,
            "ordered_boundary_chain": "Start → S1F (= 1C; 210m nominal) → 2C (~410m) → 3C (= T−G3F crossing; ~1010m) → 4C (~1210m) → T−G1F crossing (1410m) → Finish (1610m)",
            "numeric_aliases": "S1F = 1C in all 84 rows; 3C = T−G3F in all 84 rows",
            "geometry_and_coverage_note": "S1F is officially 210m at 1610m; 1C is approximately 1400m from finish. Only 9 started races.",
        },
    }
    profile_rows = []
    for distance in DISTANCES:
        counts_row = counts.loc[counts.race_distance_m.eq(distance)].iloc[0]
        profile_rows.append({
            "race_distance_m": distance,
            "support_class": profile_specs[distance]["support_class"],
            "started_races": int(counts_row.started_races),
            "started_rows": int(counts_row.started_rows),
            "proposed_nonoverlap_segment_count": profile_specs[distance]["proposed_nonoverlap_segment_count"],
            "ordered_boundary_chain": profile_specs[distance]["ordered_boundary_chain"],
            "numeric_aliases": profile_specs[distance]["numeric_aliases"],
            "geometry_and_coverage_note": profile_specs[distance]["geometry_and_coverage_note"],
        })
    profiles = pd.DataFrame(profile_rows)

    # Fingerprint only the selected race rows and their quality-view time/status provenance.
    source_keys = [
        "race_date", "meet_code", "race_number", "horse_number", "horse_id",
        "race_distance_m", "finish_position", "finish_time_seconds", "valid_time", "race_id",
    ]
    source_lookup = roster.set_index("api_record_id")
    time_sorted = times.sort_values(["api_record_id", "field_name"]).reset_index(drop=True)
    row_hashes_by_distance: dict[int, list[str]] = {d: [] for d in DISTANCES}
    for api_record_id, group in time_sorted.groupby("api_record_id", sort=True):
        source = source_lookup.loc[int(api_record_id)]
        fields = []
        for row in group.itertuples(index=False):
            fields.append([
                row.field_name,
                canonical(row.api_value_json_type),
                canonical(row.api_payload_sha256),
                canonical(row.api_source_artifact_id),
                canonical(row.api_source_page_sha256),
                canonical(row.api_source_page_path),
                canonical(row.time_seconds),
                canonical(row.time_status),
            ])
        source_identity = {"api_record_id": int(api_record_id)}
        source_identity.update({key: canonical(source[key]) for key in source_keys})
        row_hash = sha256_bytes(json_bytes({"source": source_identity, "quality_time_fields": fields}))
        row_hashes_by_distance[int(source.race_distance_m)].append(f"{int(api_record_id)}:{row_hash}")
    fingerprints = {
        str(distance): {
            "scoped_started_source_rows": len(row_hashes_by_distance[distance]),
            "api_record_id_plus_quality_time_row_hash_sha256": sha256_bytes(
                "\n".join(row_hashes_by_distance[distance]).encode("utf-8")
            ),
        }
        for distance in DISTANCES
    }
    fingerprints["all_distances"] = {
        "scoped_started_source_rows": int(len(roster)),
        "api_record_id_plus_quality_time_row_hash_sha256": sha256_bytes(
            "\n".join(
                item for distance in DISTANCES for item in row_hashes_by_distance[distance]
            ).encode("utf-8")
        ),
    }

    counts.to_csv(OUT / "distance_counts.csv", index=False)
    coverage.to_csv(OUT / "time_coverage.csv", index=False)
    status_counts.to_csv(OUT / "time_status_counts.csv", index=False)
    relations.to_csv(OUT / "endpoint_relations.csv", index=False)
    g3f_consistency.to_csv(OUT / "c3_g3f_crossing_consistency.csv", index=False)
    chronology.to_csv(OUT / "chronology_summary.csv", index=False)
    profiles.to_csv(OUT / "proposed_distance_profiles.csv", index=False)

    scope = {
        "audit_status": "complete_read_only_source_layout_inventory",
        "scope": {
            "frozen_roster_snapshot": str(SNAPSHOT.relative_to(ROOT)),
            "frozen_roster_rows": frozen_snapshot_rows,
            "frozen_roster_snapshot_sha256": file_sha256(SNAPSHOT),
            "meet_code": 2,
            "race_date_min_inclusive": START_DATE,
            "race_date_max_inclusive": END_DATE,
            "distance_m": DISTANCES,
            "starter_rule": "finish_position 1..89 or 91/92, inherited from 20261017 five-section study",
            "scoped_candidate_rows": int(len(roster_all)),
            "scoped_started_rows": int(len(roster)),
            "scoped_started_races": int(roster.race_id.nunique()),
            "excluded_project_horse_rows_in_scope": 0,
            "date_range_of_started_rows": [str(roster.race_date.min()), str(roster.race_date.max())],
        },
        "database_access": {
            "uri_mode": "ro",
            "sqlite_query_only": query_only == 1,
            "connection_local_temp_id_table_only": True,
            "main_database_mutations": False,
            "data_version_start": data_version_start,
            "data_version_end": data_version_end,
            "whole_database_hash_claimed_unchanged": False,
            "quality_time_view": "jeju_race_section_time_values",
            "quality_time_view_sql_sha256": view_sql_sha256,
            "record_scoped_source_fingerprints": fingerprints,
        },
        "accepted_time_rule": {
            "selected_time_must_be_positive": True,
            "accepted_statuses": sorted(STATUS_ALLOWED),
            "held_statuses": sorted(STATUS_HOLD),
            "model_input_valid_time_filter": "not applied to per-field coverage counts; valid_time is separately reported and used for finish-derived crossing endpoints",
            "full_race_order_group_point_mask_applied": False,
            "eligible_as_model_input": False,
            "explanation": "Descriptive time-only inventory. Race-point order/group conflict masks and the inherited feature eligibility contract were not audited or applied; additional review is required before any time-derived feature use.",
            "api6_leader_times_used": False,
        },
        "available_per_horse_api4_time_fields": [FIELD_LABELS[field] for field in TIME_FIELDS],
        "g2f": {
            "quality_selected_api4_time_field_present": False,
            "basis": "the current quality-selected jeju_race_section_time_values contract enumerates only S1F, 1C, 2C, 3C, 4C, G3F, and G1F; no G2F time field is exposed",
        },
        "endpoint_definitions": {
            "cumulative_elapsed": ["S1F", "1C", "2C", "3C", "4C"],
            "G3F_crossing_elapsed_seconds": "finish_time_seconds - G3F_duration; calculated only for positive valid_time finish endpoints and accepted positive G3F",
            "G1F_crossing_elapsed_seconds": "finish_time_seconds - G1F_duration; calculated only for positive valid_time finish endpoints and accepted positive G1F",
            "Finish": "positive finish_time_seconds where frozen baseline valid_time is true",
            "exact_numeric_duplicate_tolerance_seconds": TOL,
            "rounding_residual_reported_tolerance_seconds": 0.15,
        },
        "outputs": [
            "distance_counts.csv",
            "time_coverage.csv",
            "time_status_counts.csv",
            "endpoint_relations.csv",
            "c3_g3f_crossing_consistency.csv",
            "chronology_summary.csv",
            "proposed_distance_profiles.csv",
        ],
    }
    (OUT / "source_audit.json").write_text(json.dumps(scope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"started_rows": len(roster), "races": int(roster.race_id.nunique()), "source_view_hash": view_sql_sha256, "data_version_start": data_version_start, "data_version_end": data_version_end}, ensure_ascii=False))


if __name__ == "__main__":
    main()
