"""Read-only inventory for the new Jeju model; does not build training data."""

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
OUT = Path(__file__).with_name("db_inventory.json")


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def main():
    before = DB.stat()
    connection = sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")

    def rows(sql, parameters=()):
        return [dict(row) for row in connection.execute(sql, parameters)]

    report = {
        "inspected_at_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
        "db_path": str(DB), "db_bytes": before.st_size,
        "sqlite_version": sqlite3.sqlite_version,
        "access": "mode=ro; PRAGMA query_only=ON",
        "scope": "Current local DB aggregates, structural checks, quality hold checks; not a full source revalidation or training eligibility decision.",
        "quick_check": rows("PRAGMA quick_check"),
        "foreign_key_violation_count": len(rows("PRAGMA foreign_key_check")),
        "schema_objects": rows("SELECT type, count(*) AS count FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' GROUP BY type"),
    }
    print("Structural checks complete", flush=True)
    candidate_rows = rows("SELECT * FROM jeju_race_population_candidates")
    full_races = {
        (row["race_date"], row["meet_code"], row["race_number"]): row["entries"]
        for row in rows("SELECT race_date,meet_code,race_number,count(*) entries FROM race_result_rows GROUP BY race_date,meet_code,race_number")
    }
    profiles = {row["horse_id"]: row for row in rows("SELECT horse_id,horse_name,birth_year,age_2026 FROM horse_analysis_2026")}
    grouped = defaultdict(list)
    for row in candidate_rows:
        grouped[(row["race_date"], row["meet_code"], row["race_number"])].append(row)

    def period(start):
        selected = {key: values for key, values in grouped.items() if key[0] >= start}
        values = [row for entries in selected.values() for row in entries]
        valid = lambda row: row["finish_position"] is not None and 1 <= row["finish_position"] <= 89 and (row["finish_time_seconds"] or 0) > 0
        partial = [{"race_date": key[0], "meet_code": key[1], "race_number": key[2],
                    "candidate_entries": len(entries), "all_stored_entries": full_races[key]}
                   for key, entries in sorted(selected.items()) if len(entries) < full_races[key]]
        return {
            "rows": len(values), "races": len(selected),
            "first_date": min(row["race_date"] for row in values),
            "last_date": max(row["race_date"] for row in values),
            "horses": len({row["horse_id"] for row in values}),
            "valid_finish_rows": sum(valid(row) for row in values),
            "races_with_any_valid_finish": sum(any(valid(row) for row in entries) for entries in selected.values()),
            "races_without_valid_finish": sum(not any(valid(row) for row in entries) for entries in selected.values()),
            "partial_candidate_races": partial,
            "duplicate_race_horse_number_keys": sum(n - 1 for n in Counter((r["race_date"],r["meet_code"],r["race_number"],r["horse_number"]) for r in values).values()),
            "duplicate_race_horse_id_keys": sum(n - 1 for n in Counter((r["race_date"],r["meet_code"],r["race_number"],r["horse_id"]) for r in values).values()),
            "missing_current_profile_rows": sum(row["horse_id"] not in profiles for row in values),
            "missing_current_profile_horses": sorted({row["horse_id"] for row in values if row["horse_id"] not in profiles}),
            "missing_core_values": {field: sum(r[field] is None or r[field] == "" for r in values)
                for field in ("horse_id","race_distance_m","rank_class_raw","carried_weight_kg","jockey_id","trainer_id","owner_id","track_raw")},
            "breed_assessment_counts": dict(Counter(row["breed_assessment"] for row in values)),
            "finish_status_raw_counts": dict(Counter(row["finish_status_raw"] for row in values)),
        }
    report["candidate_population_all"] = period("0000-01-01")
    report["candidate_population_2017_plus"] = period("2017-01-01")
    report["candidate_by_year"] = rows("SELECT substr(race_date,1,4) year,count(*) entries,count(DISTINCT race_date||'|'||meet_code||'|'||race_number) races FROM jeju_race_population_candidates GROUP BY 1")
    report["profiles"] = {"horses": len(profiles), "missing_birth_year": sum(r["birth_year"] is None for r in profiles.values()), "age_reference_year": 2026}
    report["raw_race_result_rows"] = rows("SELECT count(*) rows,min(race_date) first_date,max(race_date) last_date FROM race_result_rows")[0]
    report["rank_prefix_candidate_population"] = rows("SELECT min(race_date) first_date,max(race_date) last_date,count(*) rows FROM jeju_race_population_candidates WHERE rank_class_raw LIKE '제%'")[0]
    print("Race population checks complete", flush=True)
    report["events"] = {}
    # Relation and column identifiers are fixed trusted constants, never user input.
    for label, relation, date_field in (
        ("running_trial_analysis", "jeju_trial_analysis_2026", "trial_date"),
        ("daily_training_raw", "daily_training_api_rows", "training_date"),
        ("daily_training_analysis", "daily_training_api_rows_analysis_2026", "training_date"),
        ("starting_training_analysis", "starting_training_website_rows_analysis_2026", "training_date"),
        ("starting_exam_raw", "starting_exam_api_rows", "exam_date"),
        ("starting_exam_analysis", "starting_exam_api_rows_analysis_2026", "exam_date"),
        ("medical_raw", "medical_api_rows", "clinic_date"),
        ("medical_analysis", "medical_api_rows_analysis_2026", "clinic_date"),
    ):
        sql = f'SELECT count(*) rows,count(DISTINCT horse_id) horses,min("{date_field}") first_date,max("{date_field}") last_date FROM "{relation}"'
        report["events"][label] = rows(sql)[0]
        print(label + " checked", flush=True)
    report["daily_duration_status"] = rows("SELECT duration_status,count(*) rows FROM daily_training_api_rows GROUP BY 1")
    report["starting_training_link_status"] = rows("SELECT matching_status,count(*) rows FROM starting_training_website_rows GROUP BY 1")
    report["starting_exam_rider_missing"] = rows("SELECT count(*) rows FROM starting_exam_api_rows WHERE rider_raw IS NULL")[0]
    report["section_review_counts"] = {
        "time": rows("SELECT review_status,count(*) fields FROM race_section_time_reviews GROUP BY 1"),
        "order": rows("SELECT review_status,count(*) fields FROM race_section_order_reviews GROUP BY 1"),
        "conflict": rows("SELECT source_kind,review_status,count(*) fields FROM section_internal_conflict_reviews GROUP BY 1,2"),
    }
    report["internal_conflict_races"] = rows("SELECT count(DISTINCT r.race_date||'|'||r.meet_code||'|'||r.race_number) races FROM section_internal_conflict_reviews x JOIN race_result_rows r USING(api_record_id) WHERE x.source_kind='individual_order'")[0]
    report["quality_view"] = rows("SELECT count(*) rows,count(DISTINCT api_record_id) unique_entry_ids,sum(section_internal_conflict_order_count) held_order_fields,sum(section_internal_conflict_group_count) held_group_entry_points,sum(section_order_website_correction_count) order_corrections,sum(section_time_website_correction_count) time_corrections FROM jeju_race_postrace_sections_quality_2026")[0]
    print("Quality view counts checked", flush=True)
    report["held_order_values"] = rows("SELECT quality_order_status,count(*) fields,sum(quality_order_value IS NOT NULL) nonnull_fields FROM jeju_race_section_order_quality_values WHERE quality_order_status='unresolved_official_internal_conflict' GROUP BY 1")
    report["held_group_values"] = rows("SELECT group_status,count(*) race_points,sum(group_value IS NOT NULL) nonnull_fields FROM jeju_race_section_group_quality_values WHERE group_status='unresolved_official_internal_conflict' GROUP BY 1")
    report["gwanghae_g1f"] = rows("SELECT race_date,race_number,horse_id,historical_horse_name_raw AS horse_name,time_seconds AS g1f_time_seconds,time_status AS g1f_time_status FROM jeju_race_section_time_values WHERE api_record_id IN (SELECT api_record_id FROM race_result_rows WHERE race_date=? AND race_number=? AND horse_name=?) AND field_name=?", ("2026-01-17",5,"광해청명","jeG1fTime"))
    report["excluded_horse_candidate_rows"] = rows("SELECT count(*) rows FROM jeju_race_population_candidates WHERE horse_id=?", ("3005648",))[0]
    report["open_provenance_issues"] = rows("SELECT issue_type,status,count(*) issues FROM provenance_issues GROUP BY 1,2")
    report["feature_snapshot_files"] = {name: [str(p.relative_to(ROOT)) for p in sorted((ROOT / name).rglob('*')) if p.is_file() and p.name != '.gitkeep'] for name in ("jeju/data/features", "jeju/data/snapshots")}
    report["raw_links"] = [{"path":str(p.relative_to(ROOT)),"resolved":str(p.resolve()),"exists":p.exists()} for p in sorted((ROOT / "jeju/data/raw").iterdir())]
    report["baseline_model_sha256"] = digest(ROOT / "jeju/models/current/HY_R_FORM.pkl")
    report["document_reconciliation"] = {
        "current_trial_rows": report["events"]["running_trial_analysis"]["rows"],
        "older_document_trial_rows": 15738,
        "difference_reason": "User-requested exclusion of horse 3005648 removed two running_trial_rows on 2026-10-02.",
        "deletion_receipt": "jeju/maintenance/small_bear_removal_20261002/deletion_receipt.json",
        "partial_candidate_scope": "44 races in 2002-2003; no candidate subset deficiency relative to stored race_result_rows in 2017+; this does not independently establish completeness against original entry cards.",
        "old_build_manifest_is_historical": True,
        "candidate_scope_note": "Candidate population is not identical to individually confirmed breed at each historical race date.",
    }
    connection.close()
    report["db_sha256"] = digest(DB)
    after = DB.stat()
    report["db_size_and_mtime_unchanged"] = (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    with OUT.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"output":str(OUT), "quick_check":report["quick_check"], "foreign_key_violation_count":report["foreign_key_violation_count"], "db_unchanged":report["db_size_and_mtime_unchanged"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
