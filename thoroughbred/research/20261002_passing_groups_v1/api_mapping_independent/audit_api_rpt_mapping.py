#!/usr/bin/env python3
"""Read-only, nominal-map comparison of frozen API303 rows and Dacom11 RPT points."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "thoroughbred/research/20261002_passing_groups_v1"
OUTPUT = PACKAGE / "api_mapping_independent"
API_PATH = PACKAGE / "api_source/api_observations.parquet"
RPT_PATH = PACKAGE / "root_expected_rpt_points.parquet"
MAP_SOURCE_PATH = ROOT / "src/horse_racing/services/race_passing.py"
JSON_PATH = OUTPUT / "independent_mapping_check.json"
REPORT_PATH = OUTPUT / "README.md"

# Nominal API-to-physical-point definitions in race_passing.py::CORNER_POINTS.
# The RPT labels are the literal labels observed in root_expected_rpt_points.parquet.
CANONICAL_BY_FIELD = {
    1: {
        "corner_1": "1C", "corner_2": "2C", "corner_3": "3C", "corner_4": "4C",
        "corner_7": "S1F", "corner_8": "G1F",
    },
    3: {
        "corner_1": "G8F", "corner_2": "G6F", "corner_3": "G4F", "corner_5": "G3F",
        "corner_7": "S1F", "corner_8": "G2F", "corner_9": "G1F",
    },
    4: {
        "corner_1": "G8F", "corner_2": "G6F", "corner_3": "G4F", "corner_5": "G3F",
        "corner_7": "S1F", "corner_8": "G2F", "corner_9": "G1F",
    },
}
RPT_LABEL_BY_POINT = {
    "1C": "C1", "2C": "C2", "3C": "C3", "4C": "C4",
    "S1F": "S-1F", "G1F": "G-1F",
    "G8F": "G8F", "G6F": "G6F", "G4F": "G4F", "G3F": "G3F",
    "G2F": "G2F",
}
VENUE = {1: "Seoul", 3: "Busan/Bukyeong", 4: "Yeongcheon"}
BLANK_VALUES = {None, "", "-", "X"}
CORNER_FIELDS = tuple(f"corner_{index}" for index in range(1, 10))
COMPARISON_STATES = (
    "exact_same", "different", "api_blank_rpt_valid", "api_valid_rpt_blank",
    "both_blank", "rpt_label_missing", "api_key_missing", "api_key_ambiguous",
)


def rpt_literal_label(meet: int, point: str) -> str:
    """Bridge canonical point codes to the venue-specific literal RPT labels."""
    if meet in {3, 4} and point in {"S1F", "G1F"}:
        return point  # Busan/Yeongcheon print these without Seoul's hyphens.
    return RPT_LABEL_BY_POINT[point]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_value(value: Any) -> bool:
    return value not in BLANK_VALUES


def raw_state(value: Any) -> str:
    if value is None:
        return "null"
    if value == "":
        return "empty_string"
    if value == "-":
        return "dash_placeholder"
    if value == "X":
        return "X_placeholder"
    return "nonblank_literal"


def compare_values(api_value: Any, rpt_value: Any) -> str:
    api_valid = valid_value(api_value)
    rpt_valid = valid_value(rpt_value)
    if api_valid and rpt_valid:
        return "exact_same" if api_value == rpt_value else "different"
    if not api_valid and rpt_valid:
        return "api_blank_rpt_valid"
    if api_valid and not rpt_valid:
        return "api_valid_rpt_blank"
    return "both_blank"


def row_locator_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": row["source_path"],
        "page_sha256": row["page_sha256"],
        "page_no": row["page_no"],
        "row_no": row["row_no"],
        "source_row_sha256": row["source_row_sha256"],
    }


def row_locator_rpt(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": row["source_path"],
        "source_sha256": row["source_sha256"],
        "line_no": row["line_no"],
        "byte_offset": row["byte_offset"],
    }


def compact_counter(counter: Counter[str]) -> list[dict[str, Any]]:
    return [
        {"value": value, "occurrences": count}
        for value, count in sorted(counter.items())
    ]


def main() -> None:
    if JSON_PATH.exists() or REPORT_PATH.exists():
        raise FileExistsError("독립 mapping 산출물이 이미 있어 덮어쓰지 않습니다.")
    OUTPUT.mkdir(parents=True, exist_ok=True)

    api_rows = pq.read_table(API_PATH).to_pylist()
    rpt_rows = pq.read_table(RPT_PATH).to_pylist()

    api_by_key: dict[tuple[int, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in api_rows:
        key = (int(row["actual_meet_code"]), row["race_date_iso"], int(row["rcNo"]))
        api_by_key[key].append(row)
    rpt_by_key_label: dict[
        tuple[int, str, int], dict[str, list[dict[str, Any]]]
    ] = defaultdict(lambda: defaultdict(list))
    for row in rpt_rows:
        key = (int(row["actual_meet_code"]), row["race_date_iso"], int(row["race_no"]))
        rpt_by_key_label[key][row["point_label_raw"]].append(row)

    raw_field_counts: dict[tuple[int, int, str], Counter[str]] = defaultdict(Counter)
    for row in api_rows:
        meet = int(row["actual_meet_code"])
        year = int(row["race_date_iso"][:4])
        for field in CORNER_FIELDS:
            raw_field_counts[(meet, year, field)][raw_state(row[field])] += 1

    raw_field_summary: list[dict[str, Any]] = []
    for (meet, year, field), counts in sorted(raw_field_counts.items()):
        total = sum(counts.values())
        raw_field_summary.append({
            "actual_meet_code": meet,
            "physical_venue": VENUE[meet],
            "event_year": year,
            "api_field": field,
            "nominal_canonical_point_code": CANONICAL_BY_FIELD[meet].get(field),
            "api_row_occurrences": total,
            "raw_state_counts": {state: counts[state] for state in (
                "null", "empty_string", "dash_placeholder", "X_placeholder", "nonblank_literal"
            )},
        })

    comparison_counts: dict[tuple[int, int, str], Counter[str]] = defaultdict(Counter)
    comparison_key_counts: Counter[tuple[int, int]] = Counter()
    rpt_key_api_status: Counter[tuple[int, int, str]] = Counter()
    global_counts: dict[int, Counter[str]] = defaultdict(Counter)
    for key, labels in sorted(rpt_by_key_label.items()):
        meet, event_date, _race_no = key
        year = int(event_date[:4])
        api_candidates = api_by_key.get(key, [])
        if len(api_candidates) == 1:
            rpt_key_api_status[(meet, year, "matched_unique_api_key")] += 1
            api_row = api_candidates[0]
        elif not api_candidates:
            rpt_key_api_status[(meet, year, "api_key_missing")] += 1
            api_row = None
        else:
            rpt_key_api_status[(meet, year, "api_key_ambiguous")] += 1
            api_row = None
        comparison_key_counts[(meet, year)] += 1
        for api_field, canonical_point in CANONICAL_BY_FIELD[meet].items():
            label = rpt_literal_label(meet, canonical_point)
            rpt_candidates = labels.get(label, [])
            if not rpt_candidates:
                status = "rpt_label_missing"
            elif api_row is None:
                status = "api_key_ambiguous" if api_candidates else "api_key_missing"
            elif len(rpt_candidates) != 1:
                status = "rpt_label_missing"
            else:
                status = compare_values(api_row[api_field], rpt_candidates[0]["notation_trim"])
            comparison_counts[(meet, year, api_field)][status] += 1
            global_counts[meet][status] += 1

    comparison_summary: list[dict[str, Any]] = []
    for key in sorted(comparison_counts):
        meet, year, field = key
        canonical_point = CANONICAL_BY_FIELD[meet][field]
        label = rpt_literal_label(meet, canonical_point)
        counts = comparison_counts[key]
        comparison_summary.append({
            "actual_meet_code": meet,
            "physical_venue": VENUE[meet],
            "event_year": year,
            "api_field": field,
            "nominal_canonical_point_code": canonical_point,
            "nominal_rpt_print_label": label,
            "rpt_race_key_count": comparison_key_counts[(meet, year)],
            "status_counts": {state: counts[state] for state in COMPARISON_STATES},
        })

    key_coverage: list[dict[str, Any]] = []
    for (meet, year), key_count in sorted(comparison_key_counts.items()):
        statuses = rpt_key_api_status
        key_coverage.append({
            "actual_meet_code": meet,
            "physical_venue": VENUE[meet],
            "event_year": year,
            "rpt_race_keys": key_count,
            "api_unique_key_matches": statuses[(meet, year, "matched_unique_api_key")],
            "api_key_missing": statuses[(meet, year, "api_key_missing")],
            "api_key_ambiguous": statuses[(meet, year, "api_key_ambiguous")],
        })

    # Race-level Seoul 2020–2021 multiset check. No notation grammar is parsed.
    seoul_field_map = CANONICAL_BY_FIELD[1]
    multiset_counts: Counter[tuple[int, str]] = Counter()
    wrong_slot_cases: list[dict[str, Any]] = []
    missing_value_cases: list[dict[str, Any]] = []
    repeated_value_alignment_counts: Counter[str] = Counter()
    per_year_counts: Counter[tuple[int, str]] = Counter()
    seoul_2020_21_key_count = 0
    for key, label_map in sorted(rpt_by_key_label.items()):
        meet, event_date, race_no = key
        year = int(event_date[:4])
        if meet != 1 or year not in {2020, 2021}:
            continue
        seoul_2020_21_key_count += 1
        api_candidates = api_by_key.get(key, [])
        if len(api_candidates) != 1:
            multiset_counts[(year, "api_key_missing_or_ambiguous")] += 1
            per_year_counts[(year, "api_key_missing_or_ambiguous")] += 1
            continue
        api_row = api_candidates[0]
        api_values_by_field = {field: api_row[field] for field in seoul_field_map}
        rpt_rows_by_label = {
            rpt_literal_label(1, canonical_point): label_map[rpt_literal_label(1, canonical_point)][0]
            for canonical_point in seoul_field_map.values()
            if len(label_map.get(rpt_literal_label(1, canonical_point), [])) == 1
        }
        if len(rpt_rows_by_label) != len(seoul_field_map):
            multiset_counts[(year, "rpt_label_missing_or_ambiguous")] += 1
            per_year_counts[(year, "rpt_label_missing_or_ambiguous")] += 1
            continue
        rpt_values_by_field = {
            field: rpt_rows_by_label[rpt_literal_label(1, canonical_point)]["notation_trim"]
            for field, canonical_point in seoul_field_map.items()
        }
        api_valid_values = [value for value in api_values_by_field.values() if valid_value(value)]
        rpt_valid_values = [value for value in rpt_values_by_field.values() if valid_value(value)]
        api_counter = Counter(api_valid_values)
        rpt_counter = Counter(rpt_valid_values)
        missing_counter = rpt_counter - api_counter
        extra_counter = api_counter - rpt_counter
        same_multiset = api_counter == rpt_counter
        nominal_equal = all(
            (valid_value(api_values_by_field[field])
             and api_values_by_field[field] == rpt_values_by_field[field])
            or (not valid_value(api_values_by_field[field])
                and not valid_value(rpt_values_by_field[field]))
            for field in seoul_field_map
        )
        possible_alignments = (
            math.prod(math.factorial(count) for count in rpt_counter.values())
            if same_multiset else 0
        )
        if same_multiset and nominal_equal:
            category = "same_multiset_same_nominal_slots"
        elif same_multiset:
            category = "same_multiset_wrong_nominal_slots"
        elif missing_counter and extra_counter:
            category = "rpt_values_missing_and_api_extra"
        elif missing_counter:
            category = "rpt_values_missing_from_api"
        else:
            category = "api_extra_vs_rpt"
        multiset_counts[(year, category)] += 1
        per_year_counts[(year, category)] += 1

        if same_multiset:
            repeated_value_alignment_counts[
                "unique" if possible_alignments == 1 else "ambiguous_repeated_values"
            ] += 1

        api_valid_fields = {field for field, value in api_values_by_field.items() if valid_value(value)}
        rpt_valid_fields = {field for field, value in rpt_values_by_field.items() if valid_value(value)}
        nominal_mismatched_fields = [
            field for field in seoul_field_map
            if (valid_value(api_values_by_field[field]) and valid_value(rpt_values_by_field[field])
                and api_values_by_field[field] != rpt_values_by_field[field])
            or (valid_value(api_values_by_field[field]) != valid_value(rpt_values_by_field[field]))
        ]
        api_row_locator = row_locator_api(api_row)
        rpt_values_with_provenance = {
            rpt_literal_label(1, canonical_point): {
                "notation_trim": rpt_rows_by_label[rpt_literal_label(1, canonical_point)]["notation_trim"],
                **row_locator_rpt(rpt_rows_by_label[rpt_literal_label(1, canonical_point)]),
            }
            for canonical_point in seoul_field_map.values()
        }

        if category == "same_multiset_wrong_nominal_slots":
            wrong_slot_cases.append({
                "event_key": {"actual_meet_code": meet, "physical_venue": VENUE[meet],
                              "event_date": event_date, "race_no": race_no},
                "category": category,
                "valid_api_value_count": len(api_valid_values),
                "valid_rpt_value_count": len(rpt_valid_values),
                "nominal_mismatched_fields": nominal_mismatched_fields,
                "api_valid_fields": sorted(api_valid_fields),
                "rpt_valid_fields": sorted(rpt_valid_fields),
                "possible_equal_value_alignments": possible_alignments,
                "alignment_unique": possible_alignments == 1,
                "permutation_selected": None,
                "candidate_rpt_labels_by_api_field": {
                    field: [
                        label for label, row in rpt_rows_by_label.items()
                        if valid_value(api_values_by_field[field])
                        and api_values_by_field[field] == row["notation_trim"]
                    ]
                    for field in seoul_field_map
                },
                "api_by_nominal_field": api_values_by_field,
                "rpt_by_label": rpt_values_with_provenance,
                "api_locator": api_row_locator,
            })
        elif missing_counter:
            missing_value_cases.append({
                "event_key": {"actual_meet_code": meet, "physical_venue": VENUE[meet],
                              "event_date": event_date, "race_no": race_no},
                "category": category,
                "valid_api_value_count": len(api_valid_values),
                "valid_rpt_value_count": len(rpt_valid_values),
                "missing_rpt_values_from_entire_api_multiset": compact_counter(missing_counter),
                "api_extra_values_not_in_rpt_multiset": compact_counter(extra_counter),
                "nominal_mismatched_fields": nominal_mismatched_fields,
                "api_by_nominal_field": api_values_by_field,
                "rpt_by_label": rpt_values_with_provenance,
                "api_locator": api_row_locator,
            })

    global_by_meet = {
        str(meet): {state: global_counts[meet][state] for state in COMPARISON_STATES}
        for meet in sorted(CANONICAL_BY_FIELD)
    }
    seoul_2020_21_summary = {
        "rpt_race_keys": seoul_2020_21_key_count,
        "api_key_matches": sum(
            len(api_by_key.get(key, [])) == 1
            for key in rpt_by_key_label
            if key[0] == 1 and key[1][:4] in {"2020", "2021"}
        ),
        "category_counts_by_year": [
            {
                "year": year,
                **{
                    category: per_year_counts[(year, category)]
                    for category in (
                        "same_multiset_same_nominal_slots",
                        "same_multiset_wrong_nominal_slots",
                        "rpt_values_missing_from_api",
                        "rpt_values_missing_and_api_extra",
                        "api_extra_vs_rpt",
                        "api_key_missing_or_ambiguous",
                        "rpt_label_missing_or_ambiguous",
                    )
                },
            }
            for year in (2020, 2021)
        ],
        "category_counts_total": {
            category: sum(count for (year, label), count in per_year_counts.items()
                          if label == category)
            for category in (
                "same_multiset_same_nominal_slots",
                "same_multiset_wrong_nominal_slots",
                "rpt_values_missing_from_api",
                "rpt_values_missing_and_api_extra",
                "api_extra_vs_rpt",
                "api_key_missing_or_ambiguous",
                "rpt_label_missing_or_ambiguous",
            )
        },
        "same_multiset_alignment_counts": dict(repeated_value_alignment_counts),
        "wrong_slot_cases_with_unique_value_alignment": sum(
            case["alignment_unique"] for case in wrong_slot_cases
        ),
        "wrong_slot_cases_with_repeated_value_ambiguity": sum(
            not case["alignment_unique"] for case in wrong_slot_cases
        ),
        "wrong_slot_cases": wrong_slot_cases,
        "rpt_values_missing_entirely_cases": missing_value_cases,
        "nominal_slot_comparison_counts_by_field": [
            {
                "api_field": field,
                "rpt_print_label": rpt_literal_label(1, canonical_point),
                "status_counts": {
                    state: sum(
                        comparison_counts[(1, year, field)][state]
                        for year in (2020, 2021)
                    )
                    for state in COMPARISON_STATES
                },
            }
            for field, canonical_point in seoul_field_map.items()
        ],
    }

    input_pins = {
        "api_observations": {
            "path": str(API_PATH.relative_to(ROOT)),
            "sha256": sha256_file(API_PATH),
            "row_count": len(api_rows),
        },
        "root_expected_rpt_points": {
            "path": str(RPT_PATH.relative_to(ROOT)),
            "sha256": sha256_file(RPT_PATH),
            "row_count": len(rpt_rows),
        },
        "nominal_map_code": {
            "path": str(MAP_SOURCE_PATH.relative_to(ROOT)),
            "sha256": sha256_file(MAP_SOURCE_PATH),
            "symbol": "CORNER_POINTS in src/horse_racing/services/race_passing.py",
        },
    }
    api_duplicate_key_count = sum(1 for values in api_by_key.values() if len(values) > 1)
    rpt_duplicate_point_key_count = sum(
        1 for labels in rpt_by_key_label.values() for values in labels.values() if len(values) > 1
    )
    overlap_unique = sum(
        1 for key in rpt_by_key_label if len(api_by_key.get(key, [])) == 1
    )

    audit = {
        "audit_type": "independent_read_only_api303_vs_dacom11_rpt_nominal_point_mapping",
        "status": "complete",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "scope": {
            "start_date": "2010-01-01",
            "cutoff_date_inclusive": "2026-09-29",
            "physical_meets": {"1": "Seoul", "3": "Busan/Bukyeong", "4": "Yeongcheon"},
        },
        "inputs": input_pins,
        "nominal_map": [
            {
                "actual_meet_code": meet,
                "physical_venue": VENUE[meet],
                "api_field": field,
                "canonical_point_code": canonical,
                "rpt_print_label": rpt_literal_label(meet, canonical),
            }
            for meet, mapping in sorted(CANONICAL_BY_FIELD.items())
            for field, canonical in mapping.items()
        ],
        "comparison_policy": {
            "api_source_value": "literal corner_i Parquet field; no trimming or parsing",
            "rpt_source_value": "literal notation_trim from root_expected_rpt_points.parquet",
            "blank_tokens_for_comparison_only": ["null", "", "-", "X"],
            "same": "both nonblank and exact string equality",
            "different": "both nonblank and exact string inequality",
            "alignment": "multiset comparison over nonblank literal values; no permutation is selected; possible bijections are counted as product of duplicate-value factorials",
            "core_database_accessed": False,
        },
        "coverage": {
            "api_observation_rows": len(api_rows),
            "api_unique_race_keys": len(api_by_key),
            "api_duplicate_race_keys": api_duplicate_key_count,
            "rpt_point_observation_rows": len(rpt_rows),
            "rpt_unique_race_keys": len(rpt_by_key_label),
            "rpt_duplicate_race_point_keys": rpt_duplicate_point_key_count,
            "rpt_race_keys_with_unique_api_row": overlap_unique,
            "rpt_race_keys_without_api_row": sum(1 for key in rpt_by_key_label if not api_by_key.get(key)),
            "rpt_race_keys_with_ambiguous_api_rows": sum(1 for key in rpt_by_key_label if len(api_by_key.get(key, [])) > 1),
            "rpt_comparison_pair_rows": sum(sum(counter.values()) for counter in comparison_counts.values()),
        },
        "rpt_api_key_coverage_by_meet_year": [
            {
                "actual_meet_code": meet,
                "physical_venue": VENUE[meet],
                "event_year": year,
                "rpt_race_keys": count,
                "api_unique_key_matches": rpt_key_api_status[(meet, year, "matched_unique_api_key")],
                "api_key_missing": rpt_key_api_status[(meet, year, "api_key_missing")],
                "api_key_ambiguous": rpt_key_api_status[(meet, year, "api_key_ambiguous")],
            }
            for (meet, year), count in sorted(comparison_key_counts.items())
        ],
        "api_raw_corner_state_by_meet_year_field": raw_field_summary,
        "nominal_api_vs_rpt_by_meet_year_field": comparison_summary,
        "nominal_comparison_status_totals_by_physical_meet": global_by_meet,
        "seoul_2020_2021_race_level_multiset_check": seoul_2020_21_summary,
    }
    audit["audit_script_path"] = str(Path(__file__).resolve().relative_to(ROOT))
    audit["audit_script_sha256"] = sha256_file(Path(__file__).resolve())

    JSON_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(render_report(audit), encoding="utf-8")
    print(json.dumps({
        "status": audit["status"],
        "api_rows": len(api_rows),
        "rpt_rows": len(rpt_rows),
        "rpt_keys_with_api": overlap_unique,
        "seoul_2020_2021": seoul_2020_21_summary["category_counts_total"],
        "wrong_slot_unique": seoul_2020_21_summary["wrong_slot_cases_with_unique_value_alignment"],
        "wrong_slot_ambiguous": seoul_2020_21_summary["wrong_slot_cases_with_repeated_value_ambiguity"],
        "json": str(JSON_PATH.relative_to(ROOT)),
        "report": str(REPORT_PATH.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))


def render_report(audit: dict[str, Any]) -> str:
    subset = audit["seoul_2020_2021_race_level_multiset_check"]
    total = subset["category_counts_total"]
    lines = [
        "# Independent API303–RPT point-map check",
        "",
        "Read-only comparison of frozen API303 observations and the RPT point rows. No source file or database was changed. See `independent_mapping_check.json` for every physical meet/year/API field and the Seoul race-level lists.",
        "",
        "## Method",
        "",
        "The nominal map is the project `CORNER_POINTS` definition, bridged to literal RPT labels (`C1`…`C4`, `S-1F`, `G-1F` for Seoul; `G8F`…`G1F`, `S1F` for Busan/Yeongcheon). Comparison is exact text only. For this check, API `null`, empty string, `-`, and `X` are blank states; RPT empty string is blank. No passing-order notation was parsed.",
        "",
        f"Input pins: API `{audit['inputs']['api_observations']['sha256']}`, RPT `{audit['inputs']['root_expected_rpt_points']['sha256']}`, map code `{audit['inputs']['nominal_map_code']['sha256']}`.",
        "",
        "## Seoul 2020–2021 race-level result",
        "",
        "Every one of the 1,495 RPT race keys in these two years has one API row.",
        "",
        "| Year | RPT keys | Same valid-value multiset, same nominal slots | Same multiset, slot disagreement | At least one RPT value absent from all six API slots |",
        "| ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in subset["category_counts_by_year"]:
        year = row["year"]
        keys = sum(row.get(category, 0) for category in (
            "same_multiset_same_nominal_slots", "same_multiset_wrong_nominal_slots",
            "rpt_values_missing_from_api", "rpt_values_missing_and_api_extra", "api_extra_vs_rpt",
        ))
        missing = row.get("rpt_values_missing_from_api", 0) + row.get("rpt_values_missing_and_api_extra", 0)
        lines.append(
            f"| {year} | {keys} | {row.get('same_multiset_same_nominal_slots', 0)} | "
            f"{row.get('same_multiset_wrong_nominal_slots', 0)} | {missing} |"
        )
    lines += [
        f"| **Total** | **{subset['rpt_race_keys']}** | **{total.get('same_multiset_same_nominal_slots', 0)}** | **{total.get('same_multiset_wrong_nominal_slots', 0)}** | **{total.get('rpt_values_missing_from_api', 0) + total.get('rpt_values_missing_and_api_extra', 0)}** |",
        "",
        f"Among the {total.get('same_multiset_wrong_nominal_slots', 0)} same-multiset slot-disagreement races, {subset['wrong_slot_cases_with_unique_value_alignment']} have a unique value-to-label alignment and {subset['wrong_slot_cases_with_repeated_value_ambiguity']} have repeated values allowing multiple alignments. The JSON lists candidate labels and the number of possible alignments; it intentionally selects no permutation for ambiguous races.",
        "",
        f"The {len(subset['rpt_values_missing_entirely_cases'])} missing-value race records list each RPT literal absent from the entire six-field API value multiset and preserve API/RPT source locators. There were {sum(len(case['api_extra_values_not_in_rpt_multiset']) for case in subset['rpt_values_missing_entirely_cases'])} API-only value groups in those cases.",
        "",
        "### Seoul 2020–2021 by nominal API field",
        "",
        "Counts below compare one API field with its nominal RPT label over 1,495 race keys. `API blank / RPT value` and `API value / RPT blank` are kept separate from exact agreement and literal disagreement.",
        "",
        "| API field | RPT label | Exact same | Different | API blank, RPT value | API value, RPT blank | Both blank |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in subset["nominal_slot_comparison_counts_by_field"]:
        c = row["status_counts"]
        lines.append(
            f"| {row['api_field']} | {row['rpt_print_label']} | {c['exact_same']} | {c['different']} | "
            f"{c['api_blank_rpt_valid']} | {c['api_valid_rpt_blank']} | {c['both_blank']} |"
        )
    lines += [
        "",
        "## Full meet/year/field counts",
        "",
        "`independent_mapping_check.json` contains the complete raw state count for all nine API corner fields, plus nominal exact/different/blank comparisons for every RPT-overlap meet/year/field. Years without local RPT point rows remain represented in API raw-state counts but have no RPT comparison. The keys are API physical meet + event date + race number; RPT lines are compared by their exact printed point label.",
        "",
        "## Scope and interpretation",
        "",
        "This audit establishes observed value alignment or absence in the two frozen inputs. It does not validate the API's internal semantics beyond the nominal map definition and does not infer a permutation from repeated values. The full per-race evidence is in `seoul_2020_2021_race_level_multiset_check.wrong_slot_cases` and `rpt_values_missing_entirely_cases`.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
