"""Independent local-source audit of Seoul 2020–2021 held passing-group cells.

Reads the two pinned Parquet sources once into in-memory DuckDB tables, then
compares literal-value candidates at race grain. Reads the named baseline DB
only with DuckDB read_only=True. No API, network, or database writes occur.
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import duckdb


HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
ROOT = PACKAGE.parents[2]
API_PATH = PACKAGE / "api_source/api_observations.parquet"
RPT_PATH = PACKAGE / "rpt_mapping/rpt_point_observations.parquet"
API_MANIFEST = PACKAGE / "api_source/source_manifest.json"
RPT_MANIFEST = PACKAGE / "rpt_mapping/manifest.json"
BASELINE_DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/backups/20261002_before_steward_reports/thoroughbred_core.duckdb"
BASELINE_ATTESTATION = BASELINE_DB.parent / "backup_pair_attestation.json"
START_DATE = "2020-01-01"
END_DATE = "2021-12-31"
API_POINTS = {
    "corner_1": "1C",
    "corner_2": "2C",
    "corner_3": "3C",
    "corner_4": "4C",
    "corner_7": "S1F",
    "corner_8": "G1F",
}
RPT_POINTS = {
    "C1": "1C",
    "C2": "2C",
    "C3": "3C",
    "C4": "4C",
    "S-1F": "S1F",
    "G-1F": "G1F",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip(" ")
    return None if normalized in ("", "-", "X") else normalized


def json_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def verify_source_pins() -> dict[str, Any]:
    api_manifest = json.loads(API_MANIFEST.read_text(encoding="utf-8"))
    rpt_manifest = json.loads(RPT_MANIFEST.read_text(encoding="utf-8"))
    api_expected = api_manifest["artifact_sha256"]["api_observations.parquet"]
    rpt_expected = next(
        item["sha256"] for item in rpt_manifest["outputs"]
        if item["path"] == "rpt_point_observations.parquet"
    )
    api_actual, rpt_actual = sha256(API_PATH), sha256(RPT_PATH)
    if (api_expected, rpt_expected) != (api_actual, rpt_actual):
        raise ValueError("Pinned source hash mismatch")
    attestation = json.loads(BASELINE_ATTESTATION.read_text(encoding="utf-8"))
    db_actual = sha256(BASELINE_DB)
    if db_actual != attestation["backup_db_sha256"]:
        raise ValueError("Read-only baseline DB hash differs from its backup attestation")
    return {
        "api_observations": {"path": str(API_PATH.relative_to(ROOT)), "sha256": api_actual},
        "rpt_point_observations": {"path": str(RPT_PATH.relative_to(ROOT)), "sha256": rpt_actual},
        "baseline_db": {"path": str(BASELINE_DB.relative_to(ROOT)), "sha256_before": db_actual,
                         "attested_sha256": attestation["backup_db_sha256"]},
    }


def main() -> None:
    input_pins = verify_source_pins()
    con = duckdb.connect(":memory:")
    # Each source parquet is scanned exactly once and reduced to the target years.
    con.execute(
        """CREATE TEMP TABLE api_source AS
           SELECT actual_meet_code, requested_year, requested_meet,
                  race_date_iso AS event_date, rcNo AS race_no,
                  source_row_sha256 AS observation_locator,
                  source_path, page_sha256 AS source_sha256, page_no, row_no,
                  corner_1, corner_2, corner_3, corner_4, corner_5,
                  corner_6, corner_7, corner_8, corner_9
           FROM read_parquet(?)
           WHERE actual_meet_code=1 AND requested_year IN (2020,2021)
             AND row_scope_status='in_scope'""",
        [str(API_PATH)],
    )
    con.execute(
        """CREATE TEMP TABLE rpt_source AS
           SELECT actual_meet_code, event_date, race_no, print_label_raw,
                  notation_raw, notation_state, observation_locator,
                  source_path, source_sha256, source_line_no, raw_line_text,
                  raw_line_bytes_hex, notation_raw_bytes_hex
           FROM read_parquet(?)
           WHERE actual_meet_code=1 AND event_date BETWEEN ? AND ?
             AND print_label_raw IN ('C1','C2','C3','C4','S-1F','G-1F')""",
        [str(RPT_PATH), START_DATE, END_DATE],
    )
    api_rows = [dict(zip([d[0] for d in con.description], row))
                for row in con.execute("SELECT * FROM api_source ORDER BY event_date,race_no,observation_locator").fetchall()]
    rpt_rows = [dict(zip([d[0] for d in con.description], row))
                for row in con.execute("SELECT * FROM rpt_source ORDER BY event_date,race_no,observation_locator").fetchall()]
    con.close()

    api_by_race: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    rpt_by_race: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in api_rows:
        api_by_race[(row["event_date"], int(row["race_no"]))].append(row)
    for row in rpt_rows:
        rpt_by_race[(row["event_date"], int(row["race_no"]))].append(row)

    duplicate_api_race_keys = {key: len(rows) for key, rows in api_by_race.items() if len(rows) != 1}
    if duplicate_api_race_keys:
        raise ValueError(f"API race key is not unique: {list(duplicate_api_race_keys.items())[:5]}")

    # Build normalized literal occurrence groups independently from the DB views.
    api_cells: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    rpt_points: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    api_fields_by_value: dict[tuple[str, int, str], set[str]] = defaultdict(set)
    rpt_labels_by_value: dict[tuple[str, int, str], set[str]] = defaultdict(set)
    for key, rows in api_by_race.items():
        for row in rows:
            for field, nominal_point in API_POINTS.items():
                value = row[field]
                norm = normalize(value)
                if norm is None:
                    continue
                cell = {
                    "event_date": key[0], "race_no": key[1], "api_field": field,
                    "nominal_point_code": nominal_point, "notation_raw": value,
                    "normalized_value": norm, "observation_locator": row["observation_locator"],
                    "source_path": row["source_path"], "source_sha256": row["source_sha256"],
                    "page_no": row["page_no"], "row_no": row["row_no"],
                }
                api_cells[key].append(cell)
                api_fields_by_value[(*key, norm)].add(field)
    for key, rows in rpt_by_race.items():
        for row in rows:
            norm = normalize(row["notation_raw"])
            if norm is None:
                continue
            point = RPT_POINTS[row["print_label_raw"]]
            rptpoint = {
                "event_date": key[0], "race_no": key[1],
                "canonical_point_code": point, "print_label_raw": row["print_label_raw"],
                "notation_raw": row["notation_raw"], "normalized_value": norm,
                "observation_locator": row["observation_locator"],
                "source_path": row["source_path"], "source_sha256": row["source_sha256"],
                "source_line_no": row["source_line_no"], "raw_line_text": row["raw_line_text"],
                "raw_line_bytes_hex": row["raw_line_bytes_hex"],
                "notation_raw_bytes_hex": row["notation_raw_bytes_hex"],
            }
            rpt_points[key].append(rptpoint)
            rpt_labels_by_value[(*key, norm)].add(row["print_label_raw"])

    # A cell is independently considered uniquely mapped only when its exact
    # normalized value occurs in one API field and one official RPT location.
    unique_api_by_point: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    held_cells: list[dict[str, Any]] = []
    held_group_keys: set[tuple[str, int, str]] = set()
    for key, cells in api_cells.items():
        for cell in cells:
            value_key = (*key, cell["normalized_value"])
            candidate_fields = sorted(api_fields_by_value[value_key])
            candidate_labels = sorted(rpt_labels_by_value.get(value_key, set()))
            candidate_points = sorted({RPT_POINTS[label] for label in candidate_labels})
            api_n, rpt_n = len(candidate_fields), len(candidate_points)
            if api_n == 1 and rpt_n == 1:
                mapped = dict(cell)
                mapped["canonical_point_code"] = candidate_points[0]
                unique_api_by_point[(*key, candidate_points[0])].append(mapped)
                continue
            if rpt_n == 0:
                category = "no_rpt_candidate"
            elif api_n > 1 and rpt_n > 1:
                category = "multiple_api_fields_and_multiple_rpt_points"
            elif api_n > 1:
                category = "multiple_api_fields_only"
            else:
                category = "multiple_rpt_points_only"
            held_cells.append({
                **cell,
                "candidate_api_fields_json": json_list(candidate_fields),
                "candidate_api_field_count": api_n,
                "candidate_rpt_labels_json": json_list(candidate_labels),
                "candidate_rpt_print_label_count": len(candidate_labels),
                "candidate_rpt_points_json": json_list(candidate_points),
                "candidate_rpt_point_count": rpt_n,
                "candidate_class": category,
                "candidate_group_has_balanced_multiplicity": api_n == rpt_n and api_n > 1,
                "rpt_candidate_raw_literals_json": json_list(sorted({
                    p["notation_raw"] for p in rpt_points.get(key, [])
                    if p["print_label_raw"] in candidate_labels
                })),
            })
            held_group_keys.add(value_key)

    if len(held_cells) != 414:
        raise ValueError(f"Independent held-cell count was {len(held_cells)}, expected 414")

    # Independently assemble value-group evidence. Counts refer to concrete
    # API field names and canonical RPT locations, avoiding inherited column
    # names from the earlier match artifact.
    group_rows: list[dict[str, Any]] = []
    for key in sorted(held_group_keys):
        event_date, race_no, norm = key
        api_group = [cell for cell in api_cells[(event_date, race_no)] if cell["normalized_value"] == norm]
        rpt_group = [point for point in rpt_points.get((event_date, race_no), []) if point["normalized_value"] == norm]
        api_fields = sorted({cell["api_field"] for cell in api_group})
        rpt_labels = sorted({point["print_label_raw"] for point in rpt_group})
        rpt_codes = sorted({point["canonical_point_code"] for point in rpt_group})
        group_rows.append({
            "event_date": event_date, "race_no": race_no, "normalized_value": norm,
            "api_fields_json": json_list(api_fields), "api_field_count": len(api_fields),
            "rpt_labels_json": json_list(rpt_labels), "rpt_label_count": len(rpt_labels),
            "rpt_point_codes_json": json_list(rpt_codes), "rpt_point_count": len(rpt_codes),
            "api_rpt_multiplicity_balanced": len(api_fields) == len(rpt_codes) and len(api_fields) > 1,
            "raw_api_values_json": json_list(sorted({cell["notation_raw"] for cell in api_group})),
            "raw_rpt_values_json": json_list(sorted({point["notation_raw"] for point in rpt_group})),
            "rpt_observation_locators_json": json_list(sorted({point["observation_locator"] for point in rpt_group})),
            "rpt_line_sources_json": json_list(sorted({point["source_path"] for point in rpt_group})),
        })

    # Directly derive final race×RPT-point values from the two source parquets.
    # API wins only at a uniquely mapped point with one normalized literal;
    # otherwise a unique literal at the printed RPT point fills that key.
    all_keys = set(unique_api_by_point)
    all_keys.update((key[0], key[1], point["canonical_point_code"])
                    for key, points in rpt_points.items() for point in points)
    direct_selection: dict[tuple[str, int, str], dict[str, Any]] = {}
    held_count_by_race = Counter((cell["event_date"], cell["race_no"]) for cell in held_cells)
    for key in sorted(all_keys):
        event_date, race_no, point_code = key
        api_at_point = sorted(unique_api_by_point.get(key, []), key=lambda row: row["observation_locator"])
        rpt_at_point = sorted(
            [point for point in rpt_points.get((event_date, race_no), [])
             if point["canonical_point_code"] == point_code],
            key=lambda row: row["observation_locator"],
        )
        api_values = sorted({row["normalized_value"] for row in api_at_point})
        rpt_values = sorted({row["normalized_value"] for row in rpt_at_point})
        selected_value = None
        selected_raw = None
        selected_source = None
        if api_at_point and len(api_values) == 1:
            selected_raw = api_at_point[0]["notation_raw"]
            selected_value = api_values[0]
            selected_source = "api303"
            if rpt_at_point and len(rpt_values) > 1:
                status = "api_primary_rpt_internal_variants"
            elif rpt_at_point and len(rpt_values) == 1 and rpt_values[0] != selected_value:
                status = "api_primary_with_rpt_discrepancy"
            elif rpt_at_point:
                status = "api_primary_exact_agreement_after_outer_space_trim"
            else:
                status = "api_primary_unique_literal"
        elif api_at_point and len(api_values) > 1:
            status = "api_internal_value_conflict_hold"
        elif rpt_at_point and len(rpt_values) == 1:
            selected_raw = rpt_at_point[0]["notation_raw"]
            selected_value = rpt_values[0]
            selected_source = "dacom11_rpt"
            status = ("rpt_unique_literal_fill_api_mapping_held_same_race"
                      if held_count_by_race[(event_date, race_no)] > 0
                      else "rpt_unique_literal_fill_api_absent")
        elif rpt_at_point and len(rpt_values) > 1:
            status = "rpt_internal_value_conflict_hold"
        else:
            status = "no_selectable_source_value"
        direct_selection[key] = {
            "actual_meet_code": 1, "event_date": event_date, "race_no": race_no,
            "canonical_point_code": point_code, "notation_raw": selected_raw,
            "normalized_value": selected_value, "selected_source": selected_source,
            "selection_status": status,
            "api_unique_pair_occurrences": len(api_at_point),
            "rpt_nonempty_occurrences": len(rpt_at_point),
            "rpt_normalized_variant_count": len(rpt_values),
            "held_api_cells_in_race": held_count_by_race[(event_date, race_no)],
            "rpt_observation_locators_json": json_list([r["observation_locator"] for r in rpt_at_point]),
            "rpt_labels_json": json_list(sorted({r["print_label_raw"] for r in rpt_at_point})),
        }

    # Baseline DB is opened only as a read-only second connection. These reads
    # verify both its 414 held-cell ledger and its final race×point choices.
    db_before = sha256(BASELINE_DB)
    baseline = duckdb.connect(str(BASELINE_DB), read_only=True)
    db_held = [dict(zip([d[0] for d in baseline.description], row)) for row in baseline.execute(
        """SELECT observation_locator,event_date,race_no,source_point_label_raw,
                  notation_raw,source_path,source_sha256,page_no,row_no
           FROM passing_api_unmapped_point_observations
           WHERE actual_meet_code=1 AND event_date BETWEEN ? AND ?
           ORDER BY event_date,race_no,source_point_label_raw""",
        [START_DATE, END_DATE],
    ).fetchall()]
    db_final = [dict(zip([d[0] for d in baseline.description], row)) for row in baseline.execute(
        """SELECT actual_meet_code,event_date,race_no,canonical_point_code,
                  notation_raw,selected_source,selection_status
           FROM race_passing_groups
           WHERE actual_meet_code=1 AND event_date BETWEEN ? AND ?
           ORDER BY event_date,race_no,canonical_point_code""",
        [START_DATE, END_DATE],
    ).fetchall()]
    db_status_counts = {
        f"{source}|{status}": count for source, status, count in baseline.execute(
            """SELECT selected_source,selection_status,count(*)
               FROM race_passing_groups
               WHERE actual_meet_code=1 AND event_date BETWEEN ? AND ?
               GROUP BY 1,2 ORDER BY 1,2""",
            [START_DATE, END_DATE],
        ).fetchall()
    }
    baseline.close()
    db_after = sha256(BASELINE_DB)
    if db_before != db_after:
        raise ValueError("Baseline database hash changed during read-only audit")

    # Pair each DB held row back to direct raw API source by stable source locator.
    source_cells_by_locator = {
        (cell["observation_locator"], cell["api_field"]): cell
        for cells in api_cells.values() for cell in cells
    }
    if len(db_held) != 414:
        raise ValueError(f"Baseline DB held-cell count was {len(db_held)}, expected 414")
    held_parity_errors = []
    for held in db_held:
        raw = source_cells_by_locator.get((held["observation_locator"], held["source_point_label_raw"]))
        if raw is None or (raw["event_date"], raw["race_no"], raw["api_field"], raw["notation_raw"]) != (
            held["event_date"], int(held["race_no"]), held["source_point_label_raw"], held["notation_raw"]
        ):
            held_parity_errors.append(held)

    # Compare the independent source-derived selected point universe and values.
    db_final_by_key = {
        (row["event_date"], int(row["race_no"]), row["canonical_point_code"]): row
        for row in db_final
    }
    selection_mismatches: list[dict[str, Any]] = []
    selection_parity_rows: list[dict[str, Any]] = []
    if set(db_final_by_key) != set(direct_selection):
        missing_from_db = sorted(set(direct_selection) - set(db_final_by_key))
        missing_from_direct = sorted(set(db_final_by_key) - set(direct_selection))
        selection_mismatches.append({"type": "key_universe", "missing_from_db": missing_from_db[:25],
                                     "missing_from_direct": missing_from_direct[:25],
                                     "direct_count": len(direct_selection), "db_count": len(db_final_by_key)})
    for key in sorted(set(db_final_by_key) & set(direct_selection)):
        direct = direct_selection[key]
        db = db_final_by_key[key]
        db_norm = normalize(db["notation_raw"])
        match = direct["selected_source"] == db["selected_source"] and direct["normalized_value"] == db_norm
        selection_parity_rows.append({
            **direct,
            "baseline_selected_source": db["selected_source"],
            "baseline_selection_status": db["selection_status"],
            "baseline_notation_raw": db["notation_raw"],
            "baseline_normalized_value": db_norm,
            "matches_baseline_source_and_value": match,
        })
        if not match:
            selection_mismatches.append({
                "type": "value_or_source", "key": list(key),
                "direct_source": direct["selected_source"], "db_source": db["selected_source"],
                "direct_value": direct["normalized_value"], "db_value": db_norm,
            })

    candidate_counts = Counter(row["candidate_class"] for row in held_cells)
    flag_counts = {
        "cells_with_multiple_api_fields": sum(row["candidate_api_field_count"] > 1 for row in held_cells),
        "cells_with_multiple_rpt_points": sum(row["candidate_rpt_point_count"] > 1 for row in held_cells),
        "cells_with_no_rpt_candidate": sum(row["candidate_rpt_point_count"] == 0 for row in held_cells),
        "cells_with_balanced_multi_api_multi_rpt_candidates": sum(row["candidate_group_has_balanced_multiplicity"] for row in held_cells),
    }
    final_source_counts = Counter(row["selected_source"] or "unselected" for row in direct_selection.values())
    final_status_counts = Counter(row["selection_status"] for row in direct_selection.values())
    held_races = sorted({(row["event_date"], row["race_no"]) for row in held_cells})
    held_cells_by_year = Counter(row["event_date"][:4] for row in held_cells)
    held_races_by_year = Counter(date[:4] for date, _ in held_races)
    candidate_pair_cell_counts = Counter(
        "+".join(sorted(json.loads(row["candidate_rpt_points_json"]))) for row in held_cells
    )
    candidate_pair_group_counts = Counter(
        "+".join(sorted(json.loads(row["rpt_point_codes_json"]))) for row in group_rows
    )
    candidate_point_expected_values: dict[tuple[str, int, str], str] = {}
    for cell in held_cells:
        for point_code in json.loads(cell["candidate_rpt_points_json"]):
            candidate_point_expected_values[(cell["event_date"], cell["race_no"], point_code)] = cell["normalized_value"]
    candidate_point_keys = set(candidate_point_expected_values)
    candidate_point_keys_all_rpt = all(
        key in direct_selection
        and direct_selection[key]["selected_source"] == "dacom11_rpt"
        and direct_selection[key]["normalized_value"] == expected_value
        and direct_selection[key]["rpt_normalized_variant_count"] == 1
        for key, expected_value in candidate_point_expected_values.items()
    )
    rpt_final_rows = [row for row in selection_parity_rows if row["selected_source"] == "dacom11_rpt"]
    rpt_final_all_verified = all(
        row["matches_baseline_source_and_value"]
        and row["baseline_selected_source"] == "dacom11_rpt"
        and row["rpt_normalized_variant_count"] == 1
        and row["rpt_nonempty_occurrences"] > 0
        for row in rpt_final_rows
    )
    if held_parity_errors or selection_mismatches or not rpt_final_all_verified or not candidate_point_keys_all_rpt:
        raise ValueError(
            "Audit parity check failed: "
            f"held_errors={len(held_parity_errors)} sample={held_parity_errors[:2]!r}; "
            f"selection_errors={len(selection_mismatches)} sample={selection_mismatches[:3]!r}; "
            f"rpt_final_all_verified={rpt_final_all_verified}; "
            f"candidate_point_keys={len(candidate_point_keys)} all_rpt={candidate_point_keys_all_rpt}; "
            f"direct_source_counts={dict(final_source_counts) if 'final_source_counts' in locals() else 'not computed'}"
        )

    write_csv(HERE / "unmapped_cells.csv", held_cells, [
        "event_date", "race_no", "api_field", "nominal_point_code", "notation_raw",
        "normalized_value", "candidate_api_fields_json", "candidate_api_field_count",
        "candidate_rpt_labels_json", "candidate_rpt_print_label_count",
        "candidate_rpt_points_json", "candidate_rpt_point_count", "candidate_class",
        "candidate_group_has_balanced_multiplicity", "rpt_candidate_raw_literals_json",
        "observation_locator", "source_path", "source_sha256", "page_no", "row_no",
    ])
    write_csv(HERE / "ambiguous_value_groups.csv", group_rows, [
        "event_date", "race_no", "normalized_value", "api_fields_json", "api_field_count",
        "rpt_labels_json", "rpt_label_count", "rpt_point_codes_json", "rpt_point_count",
        "api_rpt_multiplicity_balanced", "raw_api_values_json", "raw_rpt_values_json",
        "rpt_observation_locators_json", "rpt_line_sources_json",
    ])
    write_csv(HERE / "rpt_final_fill_points.csv", rpt_final_rows, [
        "event_date", "race_no", "canonical_point_code", "notation_raw", "normalized_value",
        "selection_status", "api_unique_pair_occurrences", "rpt_nonempty_occurrences",
        "rpt_normalized_variant_count", "held_api_cells_in_race", "rpt_labels_json",
        "rpt_observation_locators_json", "baseline_selected_source", "baseline_selection_status",
        "baseline_notation_raw", "matches_baseline_source_and_value",
    ])
    write_csv(HERE / "point_selection_reconciliation.csv", selection_parity_rows, [
        "event_date", "race_no", "canonical_point_code", "notation_raw", "normalized_value",
        "selected_source", "selection_status", "api_unique_pair_occurrences", "rpt_nonempty_occurrences",
        "rpt_normalized_variant_count", "held_api_cells_in_race", "baseline_selected_source",
        "baseline_selection_status", "baseline_notation_raw", "baseline_normalized_value",
        "matches_baseline_source_and_value", "rpt_labels_json", "rpt_observation_locators_json",
    ])

    summary = {
        "status": "complete_independent_local_parquet_recheck",
        "scope": {"actual_meet_code": 1, "venue": "Seoul", "start_date": START_DATE,
                  "end_date": END_DATE, "official_rpt_labels": sorted(RPT_POINTS)},
        "source_pins": input_pins,
        "method": {
            "source_parquet_scans": 2,
            "materialization": "one in-memory DuckDB materialization per source, filtered to Seoul 2020-2021",
            "normalization": "strip outer ASCII spaces only for equality; placeholders null/empty/-/X excluded",
            "mapping_rule": "an API field/value maps only when that normalized value occurs in exactly one relevant API field and exactly one canonical official RPT location in the same race",
            "notation_grammar_parsed": False,
            "baseline_database_mode": "read_only=True",
            "network_or_api_calls": False,
        },
        "counts": {
            "materialized_api_race_rows": len(api_rows),
            "materialized_api_race_keys": len(api_by_race),
            "materialized_rpt_point_rows": len(rpt_rows),
            "rpt_race_keys": len(rpt_by_race),
            "api_nonempty_mapped_fields": sum(len(v) for v in api_cells.values()),
            "held_api_cells_independent": len(held_cells),
            "held_api_cells_baseline_db": len(db_held),
            "held_api_cells_locally_reconciled": len(held_cells) - len(held_parity_errors),
            "held_races": len(held_races),
            "held_cells_by_year": dict(sorted(held_cells_by_year.items())),
            "held_races_by_year": dict(sorted(held_races_by_year.items())),
            "candidate_class_counts": {
                "no_rpt_candidate": candidate_counts.get("no_rpt_candidate", 0),
                "multiple_api_fields_only": candidate_counts.get("multiple_api_fields_only", 0),
                "multiple_rpt_points_only": candidate_counts.get("multiple_rpt_points_only", 0),
                "multiple_api_fields_and_multiple_rpt_points": candidate_counts.get("multiple_api_fields_and_multiple_rpt_points", 0),
            },
            "candidate_flags_nonexclusive": flag_counts,
            "ambiguous_race_value_groups": len(group_rows),
            "balanced_multi_api_and_multi_rpt_value_groups": sum(r["api_rpt_multiplicity_balanced"] for r in group_rows),
            "ambiguous_groups_by_api_field_count": dict(sorted(Counter(r["api_field_count"] for r in group_rows).items())),
            "ambiguous_groups_by_rpt_point_count": dict(sorted(Counter(r["rpt_point_count"] for r in group_rows).items())),
            "candidate_rpt_point_pair_cell_counts": dict(sorted(candidate_pair_cell_counts.items())),
            "candidate_rpt_point_pair_group_counts": dict(sorted(candidate_pair_group_counts.items())),
            "candidate_rpt_point_keys_from_all_held_cells": len(candidate_point_keys),
            "candidate_rpt_point_keys_selected_from_one_literal_rpt_value": sum(
                direct_selection[key]["selected_source"] == "dacom11_rpt"
                and direct_selection[key]["normalized_value"] == expected_value
                and direct_selection[key]["rpt_normalized_variant_count"] == 1
                for key, expected_value in candidate_point_expected_values.items()
            ),
            "candidate_rpt_point_keys_missing_or_not_rpt_selected": len(candidate_point_keys) - sum(
                direct_selection[key]["selected_source"] == "dacom11_rpt"
                and direct_selection[key]["normalized_value"] == expected_value
                and direct_selection[key]["rpt_normalized_variant_count"] == 1
                for key, expected_value in candidate_point_expected_values.items()
            ),
            "final_race_point_rows_independent": len(direct_selection),
            "final_race_point_rows_baseline_db": len(db_final),
            "final_selection_source_counts_independent": dict(final_source_counts),
            "final_selection_status_counts_independent": dict(final_status_counts),
            "baseline_selection_source_and_status_counts": db_status_counts,
            "rpt_filled_point_rows_independent": len(rpt_final_rows),
            "rpt_filled_point_rows_all_have_one_rpt_literal_and_match_baseline": rpt_final_all_verified,
            "all_held_candidate_rpt_point_keys_filled_from_unique_rpt_literals": candidate_point_keys_all_rpt,
            "independent_vs_baseline_point_value_or_source_mismatches": len(selection_mismatches),
            "baseline_db_sha256_after": db_after,
        },
        "parity": {
            "all_414_held_cells_match_raw_api_source_locator_and_literal": not held_parity_errors,
            "all_direct_point_selections_match_baseline_source_and_normalized_value": not selection_mismatches,
            "baseline_db_hash_unchanged": db_before == db_after,
        },
        "interpretation": {
            "cell_level_mapping": "The 414 cells remain individually unmappable by value alone wherever multiple API fields and/or multiple RPT points carry the same literal.",
            "final_point_values": "Every race×RPT point selected from Dacom11 has exactly one normalized RPT literal; the entire independent selected-point universe matches the read-only baseline DB.",
        },
        "outputs": [
            "README.md", "unmapped_cells.csv", "ambiguous_value_groups.csv",
            "rpt_final_fill_points.csv", "point_selection_reconciliation.csv", "recheck_unmapped.py",
        ],
    }
    (HERE / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
