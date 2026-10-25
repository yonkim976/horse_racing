#!/usr/bin/env python3
"""Read-only audit of API18 rider employee IDs against stored official identities."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DASH_MARKERS = {"-", "–", "—", "−", "－"}
ZERO_MARKERS = {"0"}
SOURCE_TABLES = ("race_result_rows", "running_trial_rows")
ROLE_SPECS = {
    "jockey": {
        "race_result_rows": ("jockey_id", "jockey_name", "race_date"),
        "running_trial_rows": ("jockey_id", "jockey_name", "trial_date"),
    },
    "trainer": {
        "race_result_rows": ("trainer_id", "trainer_name", "race_date"),
        "running_trial_rows": ("trainer_id", "trainer_name", "trial_date"),
    },
}
EXPECTED_DAILY_ROWS = 908_316
EXPECTED_PRNO_VALUE_ROWS = 816_151


def raw_state(value: str | None) -> str:
    """Classify raw ID values without trimming or changing their stored text."""
    if value is None:
        return "null"
    if value == "":
        return "empty"
    if value.isspace():
        return "whitespace_only"
    if value in DASH_MARKERS:
        return "dash"
    if value in ZERO_MARKERS:
        return "zero"
    return "identifier"


def name_state(value: str | None) -> str:
    if value is None:
        return "null"
    if value == "":
        return "empty"
    if value.isspace():
        return "whitespace_only"
    if value in DASH_MARKERS:
        return "dash"
    return "name"


def normalize_name_whitespace(value: str | None) -> str | None:
    """Comparison key only; all raw names remain in the audit outputs."""
    if value is None:
        return None
    return "".join(value.split())


def stable_key(value: Any) -> tuple[int, str]:
    return (0, "") if value is None else (1, str(value))


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sorted_raw(values: set[str | None]) -> list[str | None]:
    return sorted(values, key=stable_key)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def add_name_record(target: dict[str, Any], source: str, value: str | None) -> None:
    target["record_count"] += 1
    target["source_row_counts"][source] += 1
    target["name_state_counts"][name_state(value)] += 1
    target["source_names"][source].add(value)
    target["all_names"].add(value)
    if value is not None:
        target["normalized_names"].add(normalize_name_whitespace(value))


def load_official_identities(con: sqlite3.Connection) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    identities: dict[str, dict[str, Any]] = {
        role: defaultdict(
            lambda: {
                "record_count": 0,
                "source_row_counts": Counter(),
                "source_names": defaultdict(set),
                "all_names": set(),
                "normalized_names": set(),
                "name_state_counts": Counter(),
                "min_date": None,
                "max_date": None,
            }
        )
        for role in ROLE_SPECS
    }
    source_id_states: dict[str, Counter[str]] = defaultdict(Counter)
    source_id_rows: Counter[str] = Counter()

    # Table and column identifiers are fixed constants in ROLE_SPECS; all data values
    # come from SQLite result rows and are never interpolated into query text.
    for role, sources in ROLE_SPECS.items():
        for table, (id_column, name_column, date_column) in sources.items():
            query = f"SELECT {id_column}, {name_column}, {date_column} FROM {table}"
            for raw_id, raw_name, observed_date in con.execute(query):
                state = raw_state(raw_id)
                source_id_states[f"{table}.{id_column}"][state] += 1
                source_id_rows[f"{table}.{id_column}"] += 1
                if state != "identifier":
                    continue
                record = identities[role][raw_id]
                add_name_record(record, table, raw_name)
                if observed_date is not None:
                    record["min_date"] = observed_date if record["min_date"] is None else min(record["min_date"], observed_date)
                    record["max_date"] = observed_date if record["max_date"] is None else max(record["max_date"], observed_date)

    role_overlap = sorted(set(identities["jockey"]) & set(identities["trainer"]))
    summary: dict[str, Any] = {
        "source_id_state_rows": {
            field: dict(sorted(counter.items()))
            for field, counter in sorted(source_id_states.items())
        },
        "source_id_rows": dict(sorted(source_id_rows.items())),
        "valid_id_count_by_role_and_source": {},
        "valid_id_union_count_by_role": {
            role: len(identities[role]) for role in ROLE_SPECS
        },
        "valid_jockey_trainer_id_overlap_count": len(role_overlap),
        "valid_jockey_trainer_id_overlap_values": role_overlap,
        "name_audit_by_role": {},
        "normalized_name_id_collisions": [],
    }

    for role, role_map in identities.items():
        by_source_counts: dict[str, int] = {}
        for source in SOURCE_TABLES:
            id_set = {
                raw_id
                for raw_id, record in role_map.items()
                if record["source_row_counts"].get(source, 0) > 0
            }
            by_source_counts[source] = len(id_set)
        summary["valid_id_count_by_role_and_source"][role] = by_source_counts

        raw_variant_ids = 0
        normalized_variant_ids = 0
        whitespace_only_variant_ids = 0
        cross_source_exact_mismatch_ids = 0
        cross_source_normalized_mismatch_ids = 0
        normalized_name_to_ids: dict[str, set[str]] = defaultdict(set)
        for raw_id, record in role_map.items():
            raw_names = {name for name in record["all_names"] if name_state(name) == "name"}
            normalized_names = {
                normalize_name_whitespace(name)
                for name in raw_names
                if normalize_name_whitespace(name)
            }
            raw_variant_ids += len(raw_names) > 1
            normalized_variant_ids += len(normalized_names) > 1
            whitespace_only_variant_ids += len(raw_names) > 1 and len(normalized_names) == 1

            race_names = {
                name for name in record["source_names"].get("race_result_rows", set())
                if name_state(name) == "name"
            }
            trial_names = {
                name for name in record["source_names"].get("running_trial_rows", set())
                if name_state(name) == "name"
            }
            if race_names and trial_names:
                cross_source_exact_mismatch_ids += race_names != trial_names
                cross_source_normalized_mismatch_ids += {
                    normalize_name_whitespace(name) for name in race_names
                } != {
                    normalize_name_whitespace(name) for name in trial_names
                }
            for normalized_name in normalized_names:
                normalized_name_to_ids[normalized_name].add(raw_id)

        collisions = [
            {"role": role, "normalized_name": normalized_name, "official_ids": sorted(ids)}
            for normalized_name, ids in normalized_name_to_ids.items()
            if len(ids) > 1
        ]
        summary["normalized_name_id_collisions"].extend(collisions)
        summary["name_audit_by_role"][role] = {
            "valid_id_count": len(role_map),
            "id_with_multiple_raw_names": raw_variant_ids,
            "id_with_multiple_whitespace_collapsed_names": normalized_variant_ids,
            "id_with_whitespace_only_name_variants": whitespace_only_variant_ids,
            "id_with_race_trial_raw_name_mismatch": cross_source_exact_mismatch_ids,
            "id_with_race_trial_whitespace_collapsed_name_mismatch": cross_source_normalized_mismatch_ids,
            "normalized_name_shared_by_multiple_ids": len(collisions),
        }
    return identities, summary


def candidate_names(record: dict[str, Any] | None) -> tuple[list[str], list[str], dict[str, int]]:
    if record is None:
        return [], [], {}
    raw = sorted(
        {name for name in record["all_names"] if name_state(name) == "name"},
        key=stable_key,
    )
    normalized = sorted(
        {normalize_name_whitespace(name) for name in raw if normalize_name_whitespace(name)},
        key=stable_key,
    )
    return raw, normalized, dict(sorted(record["source_row_counts"].items()))


def classify_employee_id(category: str | None, raw_id: str | None, identities: dict[str, dict[str, Any]]) -> dict[str, Any]:
    state = raw_state(raw_id)
    if state != "identifier":
        return {
            "employee_id_state": state,
            "official_role_candidates": [],
            "jockey_names_raw": [],
            "trainer_names_raw": [],
            "identity_mapping_status": f"no_mapping_{state}",
            "safe_rider_mapping": False,
            "safe_rider_name_raw": None,
        }

    role_candidates = [role for role in ("jockey", "trainer") if raw_id in identities[role]]
    jockey_names, jockey_normalized, jockey_source_counts = candidate_names(identities["jockey"].get(raw_id))
    trainer_names, trainer_normalized, trainer_source_counts = candidate_names(identities["trainer"].get(raw_id))
    jockey_unambiguous = len(jockey_names) == 1 and len(jockey_normalized) == 1
    trainer_unambiguous = len(trainer_names) == 1 and len(trainer_normalized) == 1
    safe_rider = False

    if len(role_candidates) > 1:
        status = "unresolved_valid_id_matches_multiple_official_roles"
    elif category == "기수":
        if role_candidates == ["jockey"] and jockey_unambiguous:
            status = "safe_exact_jockey_id_name_match"
            safe_rider = True
        elif role_candidates == ["jockey"]:
            status = "unresolved_jockey_name_conflict_or_missing"
        elif role_candidates == ["trainer"]:
            status = "unresolved_category_jockey_id_matches_trainer_only"
        else:
            status = "unresolved_no_exact_jockey_id_match"
    elif category == "기수후보생":
        if role_candidates == ["jockey"] and jockey_unambiguous:
            status = "jockey_id_match_candidate_category_review"
        elif role_candidates == ["jockey"]:
            status = "candidate_category_jockey_name_conflict_or_missing"
        else:
            status = "candidate_category_no_exact_jockey_id_match"
    elif category == "조교사":
        if role_candidates == ["trainer"] and trainer_unambiguous:
            status = "safe_exact_trainer_id_name_match_for_rider_category_trainer"
            safe_rider = True
        elif role_candidates == ["trainer"]:
            status = "trainer_id_name_conflict_or_missing"
        elif role_candidates == ["jockey"]:
            status = "unresolved_trainer_category_id_matches_jockey_only"
        else:
            status = "unresolved_no_exact_trainer_id_match"
    elif category is None or category == "-":
        if role_candidates == ["jockey"] and jockey_unambiguous:
            status = "role_unspecified_jockey_identity_candidate_review"
        elif role_candidates == ["trainer"] and trainer_unambiguous:
            status = "role_unspecified_trainer_identity_candidate_review"
        elif role_candidates:
            status = "role_unspecified_official_name_conflict_review"
        else:
            status = "unresolved_role_unspecified_no_official_id_match"
    else:
        if role_candidates:
            status = "non_jockey_category_official_role_overlap_review"
        else:
            status = "unresolved_non_jockey_id_not_in_official_jockey_trainer_tables"

    return {
        "employee_id_state": state,
        "official_role_candidates": role_candidates,
        "jockey_names_raw": jockey_names,
        "jockey_names_whitespace_collapsed": jockey_normalized,
        "jockey_official_source_row_counts": jockey_source_counts,
        "trainer_names_raw": trainer_names,
        "trainer_names_whitespace_collapsed": trainer_normalized,
        "trainer_official_source_row_counts": trainer_source_counts,
        "identity_mapping_status": status,
        "safe_rider_mapping": safe_rider,
        "safe_rider_name_raw": (
            jockey_names[0] if safe_rider and category == "기수"
            else trainer_names[0] if safe_rider and category == "조교사"
            else None
        ),
    }


def load_trainer_name_usage(con: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    usage: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "raw_name_rows": Counter(),
            "exact_match_rows": 0,
            "whitespace_collapsed_match_rows": 0,
            "usable_name_rows": 0,
        }
    )
    # This is an API18 name comparison for trainer-category rows only. It never
    # contributes to rider identity matching.
    for raw_id, raw_trainer_name, row_count in con.execute(
        """
        SELECT prNo_raw, trName_raw, COUNT(*)
        FROM daily_training_api_rows
        WHERE prGubun_raw='조교사'
        GROUP BY prNo_raw, trName_raw
        """
    ):
        if raw_id is None:
            continue
        entry = usage[raw_id]
        entry["raw_name_rows"][raw_trainer_name] += row_count
        if name_state(raw_trainer_name) == "name":
            entry["usable_name_rows"] += row_count
    return usage


def load_website_name_sets(con: sqlite3.Connection) -> tuple[dict[tuple[str, str], list[str | None]], int]:
    name_sets: dict[tuple[str, str], list[str | None]] = defaultdict(list)
    row_count = 0
    for training_date, horse_id, rider_raw in con.execute(
        "SELECT training_date, horse_id, rider_raw FROM starting_training_website_rows_latest"
    ):
        row_count += 1
        name_sets[(horse_id, training_date)].append(rider_raw)
    return name_sets, row_count


def website_status(candidate_name: str, raw_values: list[str | None]) -> str:
    usable = {name for name in raw_values if name_state(name) == "name"}
    if not usable:
        return "website_rows_without_usable_rider_name"
    if candidate_name in usable:
        if usable == {candidate_name}:
            return "candidate_is_only_usable_website_name"
        return "candidate_in_multi_name_website_set"
    candidate_normalized = normalize_name_whitespace(candidate_name)
    website_normalized = {normalize_name_whitespace(name) for name in usable}
    if candidate_normalized in website_normalized:
        return "whitespace_normalized_match_only"
    return "website_names_present_without_match"


def build_website_crosscheck(
    con: sqlite3.Connection,
    identities: dict[str, dict[str, Any]],
    website_sets: dict[tuple[str, str], list[str | None]],
) -> tuple[list[dict[str, Any]], dict[tuple[str | None, str], Counter[str]], dict[str | None, Counter[str]]]:
    detail_rows: list[dict[str, Any]] = []
    per_employee: dict[tuple[str | None, str], Counter[str]] = defaultdict(Counter)
    per_category: dict[str | None, Counter[str]] = defaultdict(Counter)
    query = """
        SELECT daily_training_api_row_id, prGubun_raw, prNo_raw, horse_id, training_date
        FROM daily_training_api_rows
        WHERE prGubun_raw IN (?, ?, ?)
        ORDER BY prGubun_raw, prNo_raw, training_date, horse_id, daily_training_api_row_id
    """
    for row_id, category, raw_id, horse_id, training_date in con.execute(
        query, ("기수", "기수후보생", "조교사")
    ):
        if raw_state(raw_id) != "identifier":
            continue
        official_role = "trainer" if category == "조교사" else "jockey"
        official = identities[official_role].get(raw_id)
        names, normalized_names, _ = candidate_names(official)
        if len(names) != 1 or len(normalized_names) != 1:
            continue
        candidate_name = names[0]
        values = website_sets.get((horse_id, training_date))
        if values is None:
            status = "no_same_horse_date_website_rows"
            website_values: list[str | None] = []
        else:
            status = website_status(candidate_name, values)
            website_values = sorted_raw(set(values))
        per_employee[(category, raw_id)][status] += 1
        per_category[category][status] += 1
        if values is not None:
            detail_rows.append(
                {
                    "daily_training_api_row_id": row_id,
                    "prGubun_raw": category,
                    "prNo_raw": raw_id,
                    "official_identity_role": official_role,
                    "horse_id": horse_id,
                    "training_date": training_date,
                    "official_id_name_candidate_raw": candidate_name,
                    "website_row_count": len(values),
                    "website_raw_rider_name_set_json": json_text(website_values),
                    "comparison_status": status,
                }
            )
    return detail_rows, per_employee, per_category


def crosswalk_rows(identities: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    collisions: list[dict[str, Any]] = []
    for role, role_map in identities.items():
        normalized_name_to_ids: dict[str, set[str]] = defaultdict(set)
        normalized_name_to_raw: dict[str, set[str]] = defaultdict(set)
        for raw_id, record in role_map.items():
            raw_names = sorted(
                {name for name in record["all_names"] if name_state(name) == "name"},
                key=stable_key,
            )
            normalized_names = sorted(
                {normalize_name_whitespace(name) for name in raw_names if normalize_name_whitespace(name)},
                key=stable_key,
            )
            source_names = {
                source: sorted(
                    {name for name in names if name_state(name) == "name"},
                    key=stable_key,
                )
                for source, names in sorted(record["source_names"].items())
            }
            race_names = source_names.get("race_result_rows", [])
            trial_names = source_names.get("running_trial_rows", [])
            source_exact_agreement = None if not (race_names and trial_names) else race_names == trial_names
            source_normalized_agreement = None if not (race_names and trial_names) else {
                normalize_name_whitespace(name) for name in race_names
            } == {
                normalize_name_whitespace(name) for name in trial_names
            }
            for normalized_name in normalized_names:
                normalized_name_to_ids[normalized_name].add(raw_id)
                normalized_name_to_raw[normalized_name].update(raw_names)
            rows.append(
                {
                    "official_role": role,
                    "official_id_raw": raw_id,
                    "records_by_source_json": json_text(dict(sorted(record["source_row_counts"].items()))),
                    "official_name_values_raw_json": json_text(raw_names),
                    "official_name_values_whitespace_collapsed_json": json_text(normalized_names),
                    "raw_name_variant_count": len(raw_names),
                    "whitespace_collapsed_name_variant_count": len(normalized_names),
                    "race_trial_raw_name_sets_agree": source_exact_agreement,
                    "race_trial_whitespace_collapsed_name_sets_agree": source_normalized_agreement,
                    "race_result_name_values_raw_json": json_text(race_names),
                    "running_trial_name_values_raw_json": json_text(trial_names),
                    "first_official_record_date": record["min_date"],
                    "last_official_record_date": record["max_date"],
                }
            )
        for normalized_name, ids in normalized_name_to_ids.items():
            if len(ids) > 1:
                collisions.append(
                    {
                        "official_role": role,
                        "normalized_name": normalized_name,
                        "official_ids_json": json_text(sorted(ids)),
                        "raw_name_values_json": json_text(sorted(normalized_name_to_raw[normalized_name])),
                    }
                )
    rows.sort(key=lambda row: (row["official_role"], row["official_id_raw"]))
    collisions.sort(key=lambda row: (row["official_role"], row["normalized_name"]))
    return rows, collisions


def output_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in columns})


def output_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> int:
    audit_dir = Path(__file__).resolve().parent
    jeju_dir = audit_dir.parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=jeju_dir / "data" / "jeju_native_core.sqlite3",
        help="SQLite DB path; opened in SQLite mode=ro with query_only enabled.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=audit_dir / "results",
        help="New output directory inside this audit folder; existing result files are never overwritten.",
    )
    args = parser.parse_args()
    db_path = args.db.expanduser().resolve(strict=True)
    output_dir = args.output_dir.expanduser().resolve()
    try:
        output_dir.relative_to(audit_dir)
    except ValueError:
        parser.error("--output-dir must resolve inside this audit directory")
    if not db_path.is_file():
        parser.error("--db must point to a regular SQLite file")
    if db_path.stat().st_size == 0:
        parser.error("--db is empty")

    expected_outputs = (
        "summary.json",
        "safe_rider_mappings.json",
        "category_summary.csv",
        "employee_id_evidence.csv",
        "unresolved_employee_ids.csv",
        "official_identity_crosswalk.csv",
        "normalized_name_collisions.csv",
        "website_crosscheck_by_employee.csv",
        "website_crosscheck_details.csv",
    )
    existing = [name for name in expected_outputs if (output_dir / name).exists()]
    if existing:
        parser.error(
            "result files already exist and are immutable: " + ", ".join(existing)
            + "; choose a new --output-dir under this audit folder"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    db_sha_before = sha256_file(db_path)
    con = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    query_only = con.execute("PRAGMA query_only").fetchone()[0]
    if query_only != 1:
        raise RuntimeError("SQLite query_only could not be enabled")
    schema_names = {
        row[0]
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        )
    }
    required = {
        "daily_training_api_rows",
        "race_result_rows",
        "running_trial_rows",
        "starting_training_website_rows_latest",
    }
    missing = sorted(required - schema_names)
    if missing:
        con.close()
        raise RuntimeError("required SQLite objects are missing: " + ", ".join(missing))

    daily_rows = con.execute("SELECT COUNT(*) FROM daily_training_api_rows").fetchone()[0]
    if daily_rows != EXPECTED_DAILY_ROWS:
        con.close()
        raise RuntimeError(f"daily_training_api_rows count changed: expected {EXPECTED_DAILY_ROWS}, found {daily_rows}")

    identities, official_summary = load_official_identities(con)
    raw_groups: list[dict[str, Any]] = []
    category_stats: dict[str | None, dict[str, Any]] = defaultdict(
        lambda: {
            "row_count": 0,
            "prNo_state_row_counts": Counter(),
            "raw_prNo_values_by_state": defaultdict(set),
            "valid_employee_ids": set(),
        }
    )
    global_prno_states: Counter[str] = Counter()
    for category, raw_id, training_rows, distinct_horses, first_date, last_date in con.execute(
        """
        SELECT prGubun_raw, prNo_raw, COUNT(*) AS training_rows,
               COUNT(DISTINCT horse_id) AS distinct_horses,
               MIN(training_date) AS first_training_date,
               MAX(training_date) AS last_training_date
        FROM daily_training_api_rows
        GROUP BY prGubun_raw, prNo_raw
        ORDER BY prGubun_raw, prNo_raw
        """
    ):
        state = raw_state(raw_id)
        stats = category_stats[category]
        stats["row_count"] += training_rows
        stats["prNo_state_row_counts"][state] += training_rows
        stats["raw_prNo_values_by_state"][state].add(raw_id)
        if state == "identifier":
            stats["valid_employee_ids"].add(raw_id)
        global_prno_states[state] += training_rows
        raw_groups.append(
            {
                "prGubun_raw": category,
                "prNo_raw": raw_id,
                "training_rows": training_rows,
                "distinct_horses": distinct_horses,
                "first_training_date": first_date,
                "last_training_date": last_date,
            }
        )

    trainer_name_usage: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "raw_name_rows": Counter(),
            "usable_name_rows": 0,
        }
    )
    for raw_id, raw_name, count in con.execute(
        """
        SELECT prNo_raw, trName_raw, COUNT(*)
        FROM daily_training_api_rows
        WHERE prGubun_raw='조교사'
        GROUP BY prNo_raw, trName_raw
        """
    ):
        trainer_name_usage[raw_id]["raw_name_rows"][raw_name] += count
        if name_state(raw_name) == "name":
            trainer_name_usage[raw_id]["usable_name_rows"] += count

    for group in raw_groups:
        category = group["prGubun_raw"]
        raw_id = group["prNo_raw"]
        evidence = classify_employee_id(category, raw_id, identities)
        group.update(evidence)
        trainer_usage = trainer_name_usage.get(raw_id, {}) if category == "조교사" else {}
        trainer_raw_values = set(trainer_usage.get("raw_name_rows", {}))
        official_trainer_names = set(evidence.get("trainer_names_raw", []))
        official_trainer_normalized = {
            normalize_name_whitespace(value)
            for value in official_trainer_names
            if normalize_name_whitespace(value)
        }
        training_trainer_normalized = {
            normalize_name_whitespace(value)
            for value in trainer_raw_values
            if name_state(value) == "name" and normalize_name_whitespace(value)
        }
        group["trName_raw_values_json"] = json_text(sorted_raw(trainer_raw_values))
        group["trName_raw_usable_row_count"] = trainer_usage.get("usable_name_rows", 0)
        group["trName_any_exact_official_trainer_name_match"] = bool(trainer_raw_values & official_trainer_names)
        group["trName_any_whitespace_collapsed_official_trainer_name_match"] = bool(
            training_trainer_normalized & official_trainer_normalized
        )
        group["trName_comparison_scope"] = (
            "trainer-name-only auxiliary check; never used to map prNo to a rider"
            if category == "조교사"
            else "not applicable"
        )

    website_sets, website_view_rows = load_website_name_sets(con)
    website_details, website_per_employee, website_per_category = build_website_crosscheck(
        con, identities, website_sets
    )
    crosswalk, normalized_collisions = crosswalk_rows(identities)

    # `기수` codes use official jockey_id; the API's `조교사` rider category
    # uses official trainer_id. The separate trName_raw field is never the rider key.
    safe_groups = [
        group for group in raw_groups
        if group.get("safe_rider_mapping") and group["prGubun_raw"] in ("기수", "조교사")
    ]
    safe_ids = {(group["prGubun_raw"], group["prNo_raw"]) for group in safe_groups}
    candidate_groups = [
        group for group in raw_groups
        if group["identity_mapping_status"] == "jockey_id_match_candidate_category_review"
    ]
    review_groups = [
        group for group in raw_groups
        if group["employee_id_state"] == "identifier"
        and (group["prGubun_raw"], group["prNo_raw"]) not in safe_ids
    ]

    website_employee_rows: list[dict[str, Any]] = []
    for group in raw_groups:
        category = group["prGubun_raw"]
        raw_id = group["prNo_raw"]
        if category not in ("기수", "기수후보생", "조교사") or raw_state(raw_id) != "identifier":
            continue
        statuses = website_per_employee.get((category, raw_id), Counter())
        website_employee_rows.append(
            {
                "prGubun_raw": category,
                "prNo_raw": raw_id,
                "official_id_name_candidate_raw": (
                    group.get("safe_rider_name_raw")
                    or (group.get("jockey_names_raw") or [None])[0]
                ),
                "training_rows": group["training_rows"],
                "same_horse_date_rows_with_website": sum(statuses.values()) - statuses.get("no_same_horse_date_website_rows", 0),
                "daily_rows_without_same_horse_date_website": statuses.get("no_same_horse_date_website_rows", 0),
                "website_comparison_status_counts_json": json_text(dict(sorted(statuses.items()))),
                "website_comparison_scope": "supplemental name-set check only; no ID inferred from website names",
            }
        )
    website_employee_rows.sort(key=lambda row: (stable_key(row["prGubun_raw"]), stable_key(row["prNo_raw"])))

    employee_rows: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    for group in raw_groups:
        category = group["prGubun_raw"]
        raw_id = group["prNo_raw"]
        role_candidates = group.get("official_role_candidates", [])
        trainer_usage = trainer_name_usage.get(raw_id, {}) if category == "조교사" else {}
        status = group["identity_mapping_status"]
        employee_row = {
            "prGubun_raw": category,
            "prNo_raw": raw_id,
            "prNo_raw_state": group["employee_id_state"],
            "training_rows": group["training_rows"],
            "distinct_horses": group["distinct_horses"],
            "first_training_date": group["first_training_date"],
            "last_training_date": group["last_training_date"],
            "official_role_candidates_json": json_text(role_candidates),
            "jockey_names_raw_json": json_text(group.get("jockey_names_raw", [])),
            "jockey_names_whitespace_collapsed_json": json_text(group.get("jockey_names_whitespace_collapsed", [])),
            "jockey_official_source_row_counts_json": json_text(group.get("jockey_official_source_row_counts", {})),
            "trainer_names_raw_json": json_text(group.get("trainer_names_raw", [])),
            "trainer_names_whitespace_collapsed_json": json_text(group.get("trainer_names_whitespace_collapsed", [])),
            "trainer_official_source_row_counts_json": json_text(group.get("trainer_official_source_row_counts", {})),
            "identity_mapping_status": status,
            "safe_rider_mapping": group.get("safe_rider_mapping", False),
            "safe_rider_name_raw": group.get("safe_rider_name_raw"),
            "trName_raw_values_json": group["trName_raw_values_json"],
            "trName_raw_usable_row_count": group["trName_raw_usable_row_count"],
            "trName_any_exact_official_trainer_name_match": group["trName_any_exact_official_trainer_name_match"],
            "trName_any_whitespace_collapsed_official_trainer_name_match": group["trName_any_whitespace_collapsed_official_trainer_name_match"],
            "trName_comparison_scope": group["trName_comparison_scope"],
        }
        employee_rows.append(employee_row)
        if group["employee_id_state"] == "identifier" and not group.get("safe_rider_mapping"):
            unresolved_rows.append(employee_row)
    employee_rows.sort(key=lambda row: (stable_key(row["prGubun_raw"]), stable_key(row["prNo_raw"])))
    unresolved_rows.sort(key=lambda row: (stable_key(row["prGubun_raw"]), stable_key(row["prNo_raw"])))

    category_rows: list[dict[str, Any]] = []
    category_summary_for_json: list[dict[str, Any]] = []
    for category, stats in sorted(category_stats.items(), key=lambda item: stable_key(item[0])):
        mapping_status_counts = Counter(
            group["identity_mapping_status"]
            for group in raw_groups
            if group["prGubun_raw"] == category
        )
        state_counts = dict(sorted(stats["prNo_state_row_counts"].items()))
        safe_row_count = sum(
            group["training_rows"] for group in safe_groups
            if group["prGubun_raw"] == category
        )
        row = {
            "prGubun_raw": category,
            "training_rows": stats["row_count"],
            "distinct_nonmissing_prNo_raw_values": len(stats["valid_employee_ids"]),
            "prNo_state_row_counts_json": json_text(state_counts),
            "distinct_raw_prNo_by_state_json": json_text(
                {
                    state: sorted_raw(values)
                    for state, values in sorted(stats["raw_prNo_values_by_state"].items())
                }
            ),
            "safe_rider_mapped_rows": safe_row_count,
            "identity_mapping_status_counts_json": json_text(dict(sorted(mapping_status_counts.items()))),
        }
        category_rows.append(row)
        category_summary_for_json.append(
            {
                "prGubun_raw": category,
                "training_rows": stats["row_count"],
                "distinct_nonmissing_prNo_raw_values": len(stats["valid_employee_ids"]),
                "prNo_state_row_counts": state_counts,
                "safe_rider_mapped_rows": safe_row_count,
                "identity_mapping_status_counts": dict(sorted(mapping_status_counts.items())),
            }
        )

    website_status_summary: dict[str, Any] = {
        "latest_view_row_count": website_view_rows,
        "latest_view_horse_date_group_count": len(website_sets),
        "horse_date_groups_with_multiple_rows": sum(len(values) > 1 for values in website_sets.values()),
        "horse_date_groups_with_multiple_distinct_raw_rider_values": sum(len(set(values)) > 1 for values in website_sets.values()),
        "daily_training_rows_compared_by_category": {
            category: dict(sorted(counts.items()))
            for category, counts in sorted(website_per_category.items(), key=lambda item: stable_key(item[0]))
        },
        "detail_rows_written": len(website_details),
        "name_match_direction": "official ID-derived candidate name compared to all website rider_raw values as a set; website names never infer employee IDs",
    }
    safe_mapping_entries: list[dict[str, Any]] = []
    for group in safe_groups:
        statuses = website_per_employee.get((group["prGubun_raw"], group["prNo_raw"]), Counter())
        safe_mapping_entries.append(
            {
                "prGubun_raw": group["prGubun_raw"],
                "prNo_raw": group["prNo_raw"],
                "person_name_from_official_id_raw": group["safe_rider_name_raw"],
                "identity_mapping_status": group["identity_mapping_status"],
                "official_role": group["official_role_candidates"][0],
                "official_id_field": "jockey_id" if group["prGubun_raw"] == "기수" else "trainer_id",
                "daily_training_row_count": group["training_rows"],
                "daily_training_first_date": group["first_training_date"],
                "daily_training_last_date": group["last_training_date"],
                "official_source_row_counts": (
                    group["jockey_official_source_row_counts"]
                    if group["prGubun_raw"] == "기수"
                    else group["trainer_official_source_row_counts"]
                ),
                "official_name_raw_values": (
                    group["jockey_names_raw"]
                    if group["prGubun_raw"] == "기수"
                    else group["trainer_names_raw"]
                ),
                "official_name_whitespace_collapsed_values": (
                    group["jockey_names_whitespace_collapsed"]
                    if group["prGubun_raw"] == "기수"
                    else group["trainer_names_whitespace_collapsed"]
                ),
                "same_horse_date_website_comparison_status_counts": dict(sorted(statuses.items())),
                "mapping_basis": (
                    "exact raw prGubun_raw='기수' and prNo_raw == official jockey_id"
                    if group["prGubun_raw"] == "기수"
                    else "exact raw prGubun_raw='조교사' and prNo_raw == official trainer_id; trName_raw remains separate"
                ) + "; no name or prefix inference",
                "canonical_current_name_source": "historical race/trial rows only; API307 is not stored in the audited DB and may supply a newer display name while preserving this evidence",
            }
        )
    safe_mapping_entries.sort(key=lambda row: row["prNo_raw"])

    candidate_only_entries = []
    for group in candidate_groups:
        candidate_only_entries.append(
            {
                "prGubun_raw": group["prGubun_raw"],
                "prNo_raw": group["prNo_raw"],
                "candidate_name_from_official_jockey_id": group["jockey_names_raw"][0] if group["jockey_names_raw"] else None,
                "daily_training_row_count": group["training_rows"],
                "identity_mapping_status": group["identity_mapping_status"],
                "note": "Preserve the raw candidate category; do not relabel as `기수` or automatic rider mapping.",
            }
        )

    daily_category_count = len(category_stats)
    training_valid_prno_rows = global_prno_states.get("identifier", 0)
    if training_valid_prno_rows != EXPECTED_PRNO_VALUE_ROWS:
        con.close()
        raise RuntimeError(
            f"prNo_raw non-sentinel row count changed: expected {EXPECTED_PRNO_VALUE_ROWS}, found {training_valid_prno_rows}"
        )
    source_name_table_count = {
        table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in SOURCE_TABLES
    }
    con.close()
    db_sha_after = sha256_file(db_path)
    if db_sha_before != db_sha_after:
        raise RuntimeError("SQLite main-file SHA-256 changed during read-only audit")

    summary = {
        "audit": "Jeju API18 daily training rider employee-ID identity audit",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "database": {
            "path": str(db_path),
            "sqlite_open_mode": "mode=ro",
            "pragma_query_only": bool(query_only),
            "main_file_sha256_before": db_sha_before,
            "main_file_sha256_after": db_sha_after,
            "main_file_unchanged": db_sha_before == db_sha_after,
            "size_bytes": db_path.stat().st_size,
            "table_counts": {
                "daily_training_api_rows": daily_rows,
                **source_name_table_count,
                "starting_training_website_rows_latest": website_view_rows,
            },
        },
        "daily_training": {
            "row_count": daily_rows,
            "prNo_raw_state_row_counts": dict(sorted(global_prno_states.items())),
            "prNo_raw_nonmissing_identifier_rows": training_valid_prno_rows,
            "raw_identifier_definition": "non-NULL, nonempty, not Unicode-whitespace-only, not exact dash marker, and not exact '0'; stored raw strings are unchanged",
            "prGubun_category_count": daily_category_count,
            "category_summary": category_summary_for_json,
        },
        "official_identity_evidence": {
            "tables": ["race_result_rows", "running_trial_rows"],
            "fields": {
                "jockey": ["jockey_id", "jockey_name"],
                "trainer": ["trainer_id", "trainer_name"],
            },
            "summary": official_summary,
            "name_normalization": "whitespace was removed only for conflict diagnostics; all raw names are preserved and no normalized name is used as an ID key",
            "api307": "not present as a normalized table or api_records record_type in this DB snapshot; current-name refresh should retain the official-ID evidence and raw historical variants separately",
        },
        "mapping_summary": {
            "safe_rider_mapping_group_count": len(safe_mapping_entries),
            "safe_rider_distinct_employee_id_count": len({row["prNo_raw"] for row in safe_mapping_entries}),
            "safe_rider_training_rows": sum(row["daily_training_row_count"] for row in safe_mapping_entries),
            "candidate_only_id_count": len(candidate_only_entries),
            "review_employee_id_group_count": len(review_groups),
            "safe_rule": "Auto-map only by exact category-specific ID and a unique official name: prGubun_raw='기수' requires raw prNo_raw == jockey_id; prGubun_raw='조교사' requires raw prNo_raw == trainer_id. Each matched official ID must have exactly one raw name and one whitespace-collapsed name, and the observed valid jockey/trainer ID namespaces must be disjoint. trName_raw is never used as the rider name.",
            "never_map": [
                "prGubun_raw='기수후보생' as an automatic 기수 assignment; retain the raw candidate category and candidate-name evidence",
                "prGubun_raw='조교승인' or '조교보' without direct official role evidence",
                "prGubun_raw='-' or NULL as an automatic rider role; exact official-ID name evidence may be shown separately while role remains unknown",
                "prNo_raw NULL, empty, whitespace-only, dash marker, or '0'",
                "any ID inferred from names, whitespace normalization, or numeric/prefix transformation",
            ],
        },
        "website_crosscheck": website_status_summary,
        "notes": [
            "The output is a read-only research audit, not a DB update or model-input adoption.",
            "`prGubun_raw` and `prNo_raw` remain authoritative raw fields; leading zeroes are preserved by exact TEXT comparisons.",
            "Starting-training names are auxiliary same-horse/same-date sets; repeated rows are all retained in row counts and unique raw name sets, and are never used to infer employee IDs.",
        ],
    }

    safe_json = {
        "audit": summary["audit"],
        "database_sha256": db_sha_before,
        "mapping_rule": summary["mapping_summary"]["safe_rule"],
        "safe_rider_mappings": safe_mapping_entries,
        "candidate_only_person_identity_links": candidate_only_entries,
        "unresolved_or_role_review_ids": [
            {
                "prGubun_raw": row["prGubun_raw"],
                "prNo_raw": row["prNo_raw"],
                "identity_mapping_status": row["identity_mapping_status"],
                "jockey_names_raw": json.loads(row["jockey_names_raw_json"]),
                "trainer_names_raw": json.loads(row["trainer_names_raw_json"]),
                "training_rows": row["training_rows"],
            }
            for row in unresolved_rows
        ],
    }

    category_columns = [
        "prGubun_raw", "training_rows", "distinct_nonmissing_prNo_raw_values",
        "prNo_state_row_counts_json", "distinct_raw_prNo_by_state_json",
        "safe_rider_mapped_rows", "identity_mapping_status_counts_json",
    ]
    employee_columns = [
        "prGubun_raw", "prNo_raw", "prNo_raw_state", "training_rows", "distinct_horses",
        "first_training_date", "last_training_date", "official_role_candidates_json",
        "jockey_names_raw_json", "jockey_names_whitespace_collapsed_json",
        "jockey_official_source_row_counts_json", "trainer_names_raw_json",
        "trainer_names_whitespace_collapsed_json", "trainer_official_source_row_counts_json",
        "identity_mapping_status", "safe_rider_mapping", "safe_rider_name_raw",
        "trName_raw_values_json", "trName_raw_usable_row_count",
        "trName_any_exact_official_trainer_name_match",
        "trName_any_whitespace_collapsed_official_trainer_name_match", "trName_comparison_scope",
    ]
    crosswalk_columns = [
        "official_role", "official_id_raw", "records_by_source_json",
        "official_name_values_raw_json", "official_name_values_whitespace_collapsed_json",
        "raw_name_variant_count", "whitespace_collapsed_name_variant_count",
        "race_trial_raw_name_sets_agree", "race_trial_whitespace_collapsed_name_sets_agree",
        "race_result_name_values_raw_json", "running_trial_name_values_raw_json",
        "first_official_record_date", "last_official_record_date",
    ]
    collision_columns = ["official_role", "normalized_name", "official_ids_json", "raw_name_values_json"]
    website_employee_columns = [
        "prGubun_raw", "prNo_raw", "official_id_name_candidate_raw", "training_rows",
        "same_horse_date_rows_with_website", "daily_rows_without_same_horse_date_website",
        "website_comparison_status_counts_json", "website_comparison_scope",
    ]
    website_detail_columns = [
        "daily_training_api_row_id", "prGubun_raw", "prNo_raw", "horse_id", "training_date",
        "official_id_name_candidate_raw", "website_row_count", "website_raw_rider_name_set_json",
        "comparison_status",
    ]

    output_json(output_dir / "summary.json", summary)
    output_json(output_dir / "safe_rider_mappings.json", safe_json)
    output_csv(output_dir / "category_summary.csv", category_columns, category_rows)
    output_csv(output_dir / "employee_id_evidence.csv", employee_columns, employee_rows)
    output_csv(output_dir / "unresolved_employee_ids.csv", employee_columns, unresolved_rows)
    output_csv(output_dir / "official_identity_crosswalk.csv", crosswalk_columns, crosswalk)
    output_csv(output_dir / "normalized_name_collisions.csv", collision_columns, normalized_collisions)
    output_csv(output_dir / "website_crosscheck_by_employee.csv", website_employee_columns, website_employee_rows)
    output_csv(output_dir / "website_crosscheck_details.csv", website_detail_columns, website_details)

    print(json.dumps({
        "database_sha256": db_sha_before,
        "daily_rows": daily_rows,
            "safe_rider_mapping_groups": len(safe_mapping_entries),
        "safe_rider_rows": summary["mapping_summary"]["safe_rider_training_rows"],
        "candidate_only_ids": len(candidate_only_entries),
        "review_id_groups": len(review_groups),
        "website_crosscheck_detail_rows": len(website_details),
        "output_dir": str(output_dir),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
        print(f"audit failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
