#!/usr/bin/env python3
"""Build read-only, literal API303↔Dacom11 exact-value mapping evidence."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "thoroughbred/research/20261002_passing_groups_v1"
API_PATH = PACKAGE / "api_source/api_observations.parquet"
RPT_PATH = PACKAGE / "rpt_mapping/rpt_point_observations.parquet"
RPT_MAP_PATH = PACKAGE / "rpt_mapping/rpt_point_mapping.csv"
OUT = PACKAGE / "api_mapping_independent"
MATCH_PATH = OUT / "api_rpt_value_matches.parquet"
YEAR_PATH = OUT / "api_mapping_validation_by_year.parquet"
YEAR_CSV_PATH = OUT / "api_mapping_validation_by_year.csv"
MANIFEST_PATH = OUT / "api_match_artifact_manifest.json"

FIELDS = tuple(f"corner_{i}" for i in range(1, 10))
PLACEHOLDERS = {None, "", "-", "X"}
VENUES = {1: "Seoul", 3: "Busan/Bukyeong", 4: "Yeongcheon"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def comparison_value(value: str | None) -> str | None:
    # This is a separate comparison field only. Raw source strings remain intact.
    if value is None:
        return None
    return value.strip(" ")


def raw_state(value: str | None) -> str:
    if value is None:
        return "null"
    if value == "":
        return "empty_string"
    if value == "-":
        return "dash_placeholder"
    if value == "X":
        return "X_placeholder"
    return "nonblank_literal"


def is_valid(value: str | None) -> bool:
    return comparison_value(value) not in PLACEHOLDERS


def main() -> None:
    targets = (MATCH_PATH, YEAR_PATH, YEAR_CSV_PATH, MANIFEST_PATH)
    if any(p.exists() for p in targets):
        raise FileExistsError("API↔RPT mapping artifacts already exist; refusing overwrite.")

    input_hashes = {
        str(p.relative_to(ROOT)): sha256_file(p)
        for p in (API_PATH, RPT_PATH, RPT_MAP_PATH)
    }
    api_table = pq.read_table(API_PATH)
    rpt_table = pq.read_table(RPT_PATH)
    api_rows = api_table.to_pylist()
    rpt_rows = rpt_table.to_pylist()

    point_map: dict[tuple[int, str], tuple[str, str]] = {}
    with RPT_MAP_PATH.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            point_map[(int(row["actual_meet_code"]), row["print_label_raw"])] = (
                row["canonical_point_code"], row["api_field_nominal"]
            )

    api_in_scope = [r for r in api_rows if r["row_scope_status"] == "in_scope"]
    api_by_key: dict[tuple[int, str, int], list[dict]] = defaultdict(list)
    api_years: Counter[tuple[int, int]] = Counter()
    for row in api_in_scope:
        key = (int(row["actual_meet_code"]), row["race_date_iso"], int(row["rcNo"]))
        api_by_key[key].append(row)
        api_years[(key[0], int(key[1][:4]))] += 1

    rpt_by_key: dict[tuple[int, str, int], list[dict]] = defaultdict(list)
    rpt_by_key_label: dict[tuple[int, str, int], dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    rpt_years: Counter[tuple[int, int]] = Counter()
    for row in rpt_rows:
        key = (int(row["actual_meet_code"]), row["event_date"], int(row["race_no"]))
        rpt_by_key[key].append(row)
        rpt_by_key_label[key][row["print_label_raw"]].append(row)
        rpt_years[(key[0], int(key[1][:4]))] += 1

    # One sparse row for every exact literal API-field/RPT-point pair within a race.
    match_rows: list[dict] = []
    for key, candidates in sorted(api_by_key.items()):
        meet, event_date, race_no = key
        point_rows = [r for r in rpt_by_key.get(key, []) if is_valid(r["notation_raw"])]
        if not point_rows:
            continue
        for api in candidates:
            for field in FIELDS:
                api_raw = api[field]
                api_cmp = comparison_value(api_raw)
                if api_cmp in PLACEHOLDERS:
                    continue
                exact_points = [r for r in point_rows if comparison_value(r["notation_raw"]) == api_cmp]
                if not exact_points:
                    continue
                for rpt in exact_points:
                    label_key = (meet, rpt["print_label_raw"])
                    canonical = point_map.get(label_key, (None, None))[0]
                    same_value_api_fields = [
                        f for f in FIELDS
                        if comparison_value(api[f]) == api_cmp and is_valid(api[f])
                    ]
                    same_value_rpt_points = [
                        r for r in point_rows
                        if comparison_value(r["notation_raw"]) == api_cmp
                    ]
                    same_label_lines = [
                        r for r in point_rows
                        if r["print_label_raw"] == rpt["print_label_raw"]
                    ]
                    if len(candidates) != 1:
                        evidence = "duplicate_api_race_key"
                    elif len(same_label_lines) != 1:
                        evidence = "duplicate_rpt_point_line"
                    elif len(same_value_api_fields) == 1 and len(same_value_rpt_points) == 1:
                        evidence = "unique_exact_value_pair"
                    else:
                        evidence = "ambiguous_repeated_value"
                    match_rows.append({
                        "observation_locator": api["source_row_sha256"],
                        "source_cohort": api["source_cohort"],
                        "actual_meet_code": meet,
                        "event_date": event_date,
                        "race_no": race_no,
                        "api_field_raw": field,
                        "api_value_raw": api_raw,
                        "api_value_compare": api_cmp,
                        "canonical_point_code": canonical,
                        "rpt_observation_locator": rpt["observation_locator"],
                        "rpt_print_label_raw": rpt["print_label_raw"],
                        "rpt_value_raw": rpt["notation_raw"],
                        "rpt_value_compare": comparison_value(rpt["notation_raw"]),
                        "api_source_path": api["source_path"],
                        "api_page_sha256": api["page_sha256"],
                        "api_page_no": api["page_no"],
                        "api_row_no": api["row_no"],
                        "api_source_row_sha256": api["source_row_sha256"],
                        "api_source_captured_at_utc": api["source_captured_at_utc"],
                        "api_source_captured_at_ms": api["source_captured_at_ms"],
                        "rpt_source_path": rpt["source_path"],
                        "rpt_source_sha256": rpt["source_sha256"],
                        "rpt_line_no": rpt["source_line_no"],
                        "rpt_byte_offset": rpt["source_line_byte_offset"],
                        "rpt_source_capture_time_status": rpt["source_capture_time_status"],
                        "rpt_source_captured_at_utc": rpt["source_captured_at_utc"],
                        "rpt_source_captured_at_ms": rpt["source_captured_at_ms"],
                        "api_field_candidate_count": len(same_value_rpt_points),
                        "rpt_point_candidate_count": len(same_value_api_fields),
                        "mapping_evidence": evidence,
                    })

    match_schema = pa.schema([
        ("observation_locator", pa.string()), ("source_cohort", pa.string()),
        ("actual_meet_code", pa.int16()), ("event_date", pa.string()), ("race_no", pa.int16()),
        ("api_field_raw", pa.string()), ("api_value_raw", pa.string()),
        ("api_value_compare", pa.string()), ("canonical_point_code", pa.string()),
        ("rpt_observation_locator", pa.string()), ("rpt_print_label_raw", pa.string()),
        ("rpt_value_raw", pa.string()), ("rpt_value_compare", pa.string()),
        ("api_source_path", pa.string()), ("api_page_sha256", pa.string()),
        ("api_page_no", pa.int32()), ("api_row_no", pa.int32()),
        ("api_source_row_sha256", pa.string()), ("api_source_captured_at_utc", pa.string()),
        ("api_source_captured_at_ms", pa.int64()), ("rpt_source_path", pa.string()),
        ("rpt_source_sha256", pa.string()), ("rpt_line_no", pa.int32()),
        ("rpt_byte_offset", pa.int64()), ("rpt_source_capture_time_status", pa.string()),
        ("rpt_source_captured_at_utc", pa.string()), ("rpt_source_captured_at_ms", pa.int64()),
        ("api_field_candidate_count", pa.int16()), ("rpt_point_candidate_count", pa.int16()),
        ("mapping_evidence", pa.string()),
    ])
    match_table = pa.Table.from_pylist(match_rows, schema=match_schema)
    pq.write_table(match_table, MATCH_PATH, compression="zstd")

    # Annual field table compares each documented nominal field to its same-label RPT row.
    year_rows: list[dict] = []
    all_years = sorted(set(api_years) | set(rpt_years))
    for meet, year in all_years:
        rpt_keys = sorted(k for k in rpt_by_key if k[0] == meet and int(k[1][:4]) == year)
        api_rows_y = [r for r in api_in_scope if int(r["actual_meet_code"]) == meet and r["race_date_iso"].startswith(str(year))]
        api_key_count = len({(int(r["actual_meet_code"]), r["race_date_iso"], int(r["rcNo"])) for r in api_rows_y})
        for field in FIELDS:
            canonical = next((point for (m, _label), (point, nom) in point_map.items() if m == meet and nom == field), None)
            label = next((lbl for (m, lbl), (point, nom) in point_map.items() if m == meet and nom == field), None)
            counts = Counter()
            for key in rpt_keys:
                api_candidates = api_by_key.get(key, [])
                if not api_candidates:
                    counts["api_key_missing"] += 1
                    continue
                if len(api_candidates) != 1:
                    counts["api_key_ambiguous"] += 1
                    continue
                label_rows = rpt_by_key_label[key].get(label, []) if label else []
                if not label_rows:
                    counts["rpt_label_missing"] += 1
                    continue
                if len(label_rows) != 1:
                    counts["rpt_label_duplicate"] += 1
                    continue
                api_value = api_candidates[0][field]
                rpt_value = comparison_value(label_rows[0]["notation_raw"])
                api_cmp = comparison_value(api_value)
                api_ok = api_cmp not in PLACEHOLDERS
                rpt_ok = rpt_value not in PLACEHOLDERS
                if api_ok and rpt_ok:
                    counts["exact_same"] += int(api_cmp == rpt_value)
                    counts["different"] += int(api_cmp != rpt_value)
                elif not api_ok and rpt_ok:
                    counts["api_blank_rpt_value"] += 1
                elif api_ok and not rpt_ok:
                    counts["api_value_rpt_blank"] += 1
                else:
                    counts["both_blank"] += 1
            if meet == 1 and year in {2020, 2021}:
                evidence_status = "seoul_2020_2021_per_race_exact_value_evidence_only"
            elif not rpt_keys:
                evidence_status = "official_nominal_map_no_rpt_overlap_evidence"
            else:
                evidence_status = "official_nominal_map_observed_comparison"
            role = "documented_canonical_field" if canonical else "unused_raw_api_field"
            year_rows.append({
                "actual_meet_code": meet,
                "physical_venue": VENUES[meet],
                "event_year": year,
                "api_field": field,
                "canonical_point_code_nominal": canonical,
                "rpt_print_label_nominal": label,
                "field_role": role,
                "api_in_scope_row_count": len(api_rows_y),
                "api_unique_race_key_count": api_key_count,
                "rpt_race_key_count": len(rpt_keys),
                "api_key_missing": counts["api_key_missing"],
                "api_key_ambiguous": counts["api_key_ambiguous"],
                "rpt_label_missing": counts["rpt_label_missing"],
                "rpt_label_duplicate": counts["rpt_label_duplicate"],
                "nominal_exact_same": counts["exact_same"],
                "nominal_different": counts["different"],
                "api_blank_rpt_value": counts["api_blank_rpt_value"],
                "api_value_rpt_blank": counts["api_value_rpt_blank"],
                "both_blank": counts["both_blank"],
                "evidence_status": evidence_status,
            })
    year_table = pa.Table.from_pylist(year_rows)
    pq.write_table(year_table, YEAR_PATH, compression="zstd")
    with YEAR_CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=year_table.column_names)
        writer.writeheader()
        writer.writerows(year_rows)

    # Rehash inputs to ensure this read-only builder observed stable source artifacts.
    input_hashes_after = {
        str(p.relative_to(ROOT)): sha256_file(p)
        for p in (API_PATH, RPT_PATH, RPT_MAP_PATH)
    }
    if input_hashes_after != input_hashes:
        raise RuntimeError("Pinned source input changed during comparison; outputs require review.")
    manifest = {
        "status": "complete_read_only_exact_literal_comparison",
        "comparison_normalization": "ASCII outer spaces stripped only in separate comparison fields; source raw values unchanged",
        "placeholders_excluded_from_exact_mapping": ["null", "", "-", "X"],
        "no_notation_parsing": True,
        "official_nominal_map_remains_default_outside_seoul_2020_2021": True,
        "seoul_2020_2021_policy": "Only unique same-race exact-value pairs are assignment evidence; repeated-value candidates remain ambiguous; no year-wide permutation inferred.",
        "inputs": input_hashes,
        "outputs": {
            MATCH_PATH.name: {"sha256": sha256_file(MATCH_PATH), "row_count": match_table.num_rows},
            YEAR_PATH.name: {"sha256": sha256_file(YEAR_PATH), "row_count": year_table.num_rows},
            YEAR_CSV_PATH.name: {"sha256": sha256_file(YEAR_CSV_PATH), "row_count": len(year_rows)},
        },
        "mapping_evidence_counts": dict(Counter(r["mapping_evidence"] for r in match_rows)),
        "built_by_script_sha256": sha256_file(Path(__file__)),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
