"""Audit preserved training API responses without network or database writes.

Outputs describe observations and duplicate groups; they are not model inputs
or a deduplicated training table. Source and database files remain unchanged.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DB = ROOT / "data/jeju_native_core.sqlite3"
MONTHLY = ROOT / "research/20260929_api_monthly_history"
ANNUAL = ROOT / "research/20260929_api_detail_sources/raw/full_year_clinic_judgement_start_training/20260929T150517.740550Z"
CUTOFF = "20260919"


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(row: dict) -> str:
    # All item fields and JSON value types are retained. No normalization.
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pages_for_sources():
    ledger = json.loads((MONTHLY / "ledger.json").read_text())
    daily = []
    for partition in ledger["partitions"].values():
        if partition.get("dataset") != "daily_training":
            continue
        pages = partition.get("pages", [])
        fallback = partition.get("date_fallback")
        if fallback:
            pages = [page for day in fallback["dates"].values() for page in day["pages"]]
        for page in pages:
            daily.append((MONTHLY, partition["month"], page))
    manifest = json.loads((ANNUAL / "run_manifest.json").read_text())
    starting = [
        (ANNUAL, year, page)
        for year, partition in manifest["datasets"]["starting_training"]["years"].items()
        for page in partition["pages"]
    ]
    return [("daily_training", daily), ("starting_training", starting)]


def checked_rows(base: Path, partition: str, meta: dict):
    path = (base / meta["response_file"]).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError("Invalid archived response path")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != meta["response_sha256"]:
        raise ValueError(f"Archive hash mismatch: {path}")
    parsed = json.loads(raw)
    response = parsed["response"]
    if str(response["header"]["resultCode"]) != "00":
        raise ValueError(f"Non-success API response: {path}")
    items = response["body"].get("items") or {}
    rows = items.get("item", []) if isinstance(items, dict) else []
    if isinstance(rows, dict):
        rows = [rows]
    if len(rows) != meta["actual_page_rows"]:
        raise ValueError(f"Page row count mismatch: {path}")
    page_no = meta["page_no"]
    if int(response["body"]["pageNo"]) != int(page_no):
        raise ValueError(f"API page number mismatch: {path}")
    return rows, {
        "source_file": str(path.relative_to(ROOT)),
        "source_sha256": digest,
        "partition": partition,
        "page_no": page_no,
    }


def run():
    output_files = [HERE / name for name in (
        "audit_summary.json", "starting_exact_duplicate_groups.jsonl",
        "starting_same_horse_day_different_records.jsonl",
        "missing_daily_race_horses.jsonl",
        "invalid_raw_training_ids.jsonl",
    )]
    if any(path.exists() for path in output_files):
        raise FileExistsError("Audit outputs already exist; use a new audit version")
    db_sha_before = sha_file(DB)
    connection = sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)
    profiles = {row[0]: row[1] for row in connection.execute(
        "SELECT horse_id, breed_label_raw FROM horse_profile_observations"
    )}
    if len(profiles) != 4617 or set(profiles.values()) != {"제주마"}:
        raise ValueError("Unexpected frozen profile population")
    race_ids = {row[0] for row in connection.execute(
        "SELECT DISTINCT horse_id FROM jeju_race_population_candidates"
    )}
    record_types = dict(connection.execute(
        "SELECT record_type, COUNT(*) FROM api_records GROUP BY record_type"
    ))
    if any("training" in value for value in record_types):
        raise ValueError("Training import state changed; review report wording")
    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "cutoff_date_inclusive": CUTOFF,
        "profile_count": len(profiles), "profile_breed_counts": dict(Counter(profiles.values())),
        "race_horse_count": len(race_ids),
        "race_horses_without_profile": sorted(race_ids - profiles.keys()),
        "db_record_type_counts": record_types,
        "training_imported_into_core_db": False,
        "audit_outputs_are_model_inputs": False,
        "exact_equality_definition": "All item fields, JSON types and values; object key order ignored; no string trimming, zero conversion or selected-field matching",
        "source_manifest_sha256": {
            "monthly_ledger": sha_file(MONTHLY / "ledger.json"),
            "annual_manifest": sha_file(ANNUAL / "run_manifest.json"),
        },
        "datasets": {},
    }
    duplicate_groups = []
    different_day_groups = []
    daily_matched_ids = set()
    invalid_id_rows = []
    for dataset, pages in pages_for_sources():
        counters = Counter()
        years = defaultdict(Counter)
        fields = Counter()
        field_states = defaultdict(Counter)
        months = defaultdict(Counter)
        nonzero_min = {}
        zero_max = {}
        matched_ids, all_ids = set(), set()
        matched_cutoff_ids = set()
        day_first = {}
        exact_first = {}
        exact_repeats = {}
        day_variants = defaultdict(set)
        page_hashes = defaultdict(list)
        lowest, highest = "99999999", ""
        for base, partition, meta in pages:
            rows, page_location = checked_rows(base, partition, meta)
            counters["verified_pages"] += 1
            if rows:
                page_hashes[page_location["source_sha256"]].append(page_location["source_file"])
            for index, row in enumerate(rows, 1):
                h, date = str(row.get("hrNo", "")), str(row.get("trDate", ""))
                if not (len(date) == 8 and date.isdigit()):
                    raise ValueError("Missing or invalid training date")
                if not date.startswith(partition):
                    raise ValueError("Record date does not match source partition")
                if row.get("meet") != "제주":
                    raise ValueError("Unexpected meet label")
                lowest, highest = min(lowest, date), max(highest, date)
                all_ids.add(h)
                counters["rows"] += 1
                years[date[:4]]["rows"] += 1
                if h in profiles:
                    counters["profile_matched_rows"] += 1
                    years[date[:4]]["profile_matched_rows"] += 1
                    matched_ids.add(h)
                    if date <= CUTOFF:
                        counters["profile_matched_rows_through_cutoff"] += 1
                        matched_cutoff_ids.add(h)
                if h in race_ids:
                    counters["race_population_matched_rows"] += 1
                if date > CUTOFF:
                    counters["rows_after_cutoff"] += 1
                location = {**page_location, "item_index_1based": index}
                if not h.isascii() or not h.isdigit() or h == "0":
                    counters["invalid_raw_horse_id_rows"] += 1
                    invalid_id_rows.append({"dataset": dataset, "record": row,
                                            "location": location,
                                            "profile_id_matched_without_normalization": h in profiles})
                fields.update(row.keys())
                for key, value in row.items():
                    if value is None or str(value) in ("", "-"):
                        field_states[key]["blank_or_placeholder"] += 1
                    elif str(value) in ("0", "0.0"):
                        field_states[key]["zero"] += 1
                    else:
                        field_states[key]["nonblank_nonzero"] += 1
                    if key in ("trTerm", "run1Cnt", "run2Cnt"):
                        if str(value) in ("0", "0.0"):
                            months[date[:6]][key + "_zero"] += 1
                            zero_max[key] = max(zero_max.get(key, ""), date)
                        elif value is not None and str(value) not in ("", "-"):
                            years[date[:4]][key + "_nonzero"] += 1
                            nonzero_min[key] = min(nonzero_min.get(key, "99999999"), date)
                day = (h, date)
                if day in day_first:
                    counters["duplicate_horse_day_excess"] += 1
                else:
                    day_first[day] = location
                if dataset == "starting_training":
                    content = canonical(row)
                    digest = hashlib.sha256(content.encode()).hexdigest()
                    day_variants[day].add(digest)
                    if digest in exact_first:
                        # Guard against a hash collision before classifying a repeat.
                        if exact_first[digest]["record"] != row:
                            raise ValueError("Canonical SHA collision")
                        counters["exact_duplicate_excess"] += 1
                        first = exact_first[digest]["first_location"]
                        counters["duplicate_excess_same_page_as_first" if first["source_file"] == location["source_file"] else "duplicate_excess_other_page_than_first"] += 1
                        exact_repeats.setdefault(digest, [first]).append(location)
                    else:
                        exact_first[digest] = {"record": row, "first_location": location}
        counters["duplicate_horse_day_excess"] += 0
        counters["exact_duplicate_excess"] += 0
        if dataset == "daily_training":
            # A full identical row must share hrNo and trDate. Zero day-key repeats
            # therefore establishes zero full-record repeats in this population.
            if counters["duplicate_horse_day_excess"]:
                raise ValueError("Daily day-key repeats require a separate full-record audit")
            daily_matched_ids = matched_ids
        duplication_by_year = defaultdict(Counter)
        multiplicity = Counter()
        profile_dup = Counter()
        cross_page_groups = 0
        for digest, locations in exact_repeats.items():
            row = exact_first[digest]["record"]
            excess = len(locations) - 1
            y = str(row["trDate"])[:4]
            duplication_by_year[y]["groups"] += 1
            duplication_by_year[y]["excess_rows"] += excess
            multiplicity[str(len(locations))] += 1
            if str(row["hrNo"]) in profiles:
                profile_dup["groups"] += 1
                profile_dup["excess_rows"] += excess
                if str(row["trDate"]) <= CUTOFF:
                    profile_dup["excess_rows_through_cutoff"] += excess
            cross_page_groups += len({loc["source_file"] for loc in locations}) > 1
            duplicate_groups.append({
                "canonical_record_sha256": digest, "record": row,
                "occurrence_count": len(locations), "excess_count": excess,
                "profile_id_matched": str(row["hrNo"]) in profiles,
                "locations": locations,
            })
        for day, digests in day_variants.items():
            if len(digests) > 1:
                records = [exact_first[digest]["record"] for digest in sorted(digests)]
                varying = sorted(key for key in set().union(*(row.keys() for row in records))
                                 if len({canonical({"present": key in row, "value": row.get(key)}) for row in records}) > 1)
                different_day_groups.append({
                    "horse_id": day[0], "training_date": day[1],
                    "distinct_record_count": len(records), "varying_fields": varying,
                    "records": [
                        {"canonical_record_sha256": digest, **exact_first[digest]}
                        for digest in sorted(digests)
                    ],
                })
        summary["datasets"][dataset] = {
            "counts": dict(counters), "date_min": lowest, "date_max": highest,
            "unique_horses": len(all_ids), "profile_matched_horses": len(matched_ids),
            "profile_matched_horses_through_cutoff": len(matched_cutoff_ids),
            "profiles_without_record": len(profiles.keys() - matched_ids),
            "race_horses_without_record": len(race_ids - matched_ids),
            "field_presence_counts": dict(fields), "field_states": dict(field_states),
            "nonzero_first_date": nonzero_min, "zero_last_date": zero_max,
            "monthly_zero_counts": dict(sorted(months.items())),
            "yearly_counts": dict(sorted(years.items())),
            "duplicate_groups": len(exact_repeats),
            "exact_duplicate_multiplicity_group_counts": dict(multiplicity),
            "duplicate_counts_by_year": dict(sorted(duplication_by_year.items())),
            "profile_matched_duplicate_counts": dict(profile_dup),
            "cross_page_exact_duplicate_groups": cross_page_groups,
            "same_page_only_exact_duplicate_groups": len(exact_repeats) - cross_page_groups,
            "positive_response_pages_with_repeated_whole_response_hash": [
                paths for paths in page_hashes.values() if len(paths) > 1
            ],
            "same_horse_day_distinct_content_groups": len(different_day_groups) if dataset == "starting_training" else 0,
        }
    missing = []
    for horse in sorted(race_ids - daily_matched_ids):
        first, last = connection.execute(
            "SELECT MIN(race_date), MAX(race_date) FROM jeju_race_population_candidates WHERE horse_id=?",
            (horse,),
        ).fetchone()
        missing.append({"horse_id": horse, "first_candidate_race_date": first,
                        "last_candidate_race_date": last,
                        "last_race_before_first_daily_record": last < "2007-10-01"})
    summary["missing_daily_race_horse_count"] = len(missing)
    summary["missing_daily_race_horses_all_end_before_api_observed_start"] = all(
        row["last_race_before_first_daily_record"] for row in missing
    )
    connection.close()
    db_sha_after = sha_file(DB)
    if db_sha_before != db_sha_after:
        raise ValueError("Database changed during audit")
    summary["database_sha256_before"] = db_sha_before
    summary["database_sha256_after"] = db_sha_after
    summary["database_unchanged"] = True
    for path, rows in [(output_files[1], duplicate_groups),
                       (output_files[2], different_day_groups),
                       (output_files[3], missing),
                       (output_files[4], invalid_id_rows)]:
        with path.open("x", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    summary["output_file_sha256"] = {path.name: sha_file(path) for path in output_files[1:]}
    with output_files[0].open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({
        "database_unchanged": True,
        "datasets": {key: {"counts": value["counts"],
                           "duplicate_groups": value["duplicate_groups"],
                           "multiplicity": value["exact_duplicate_multiplicity_group_counts"],
                           "duplicate_years": value["duplicate_counts_by_year"],
                           "profile_duplicates": value["profile_matched_duplicate_counts"],
                           "cross_page_groups": value["cross_page_exact_duplicate_groups"],
                           "same_page_groups": value["same_page_only_exact_duplicate_groups"],
                           "whole_response_repeats": len(value["positive_response_pages_with_repeated_whole_response_hash"])}
                     for key, value in summary["datasets"].items()},
    }, ensure_ascii=False))


if __name__ == "__main__":
    run()
