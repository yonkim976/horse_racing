"""Verify the 2026-09-17 Busan freshness capture against the frozen DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from horse_racing.collectors.kra_api import response_body


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data/research/busan_complete_db_20260916/busan_complete.sqlite3"
SECTION_FIELDS = (
    "buS1fTime", "buS1fAccTime", "buG1fAccTime", "buG2fAccTime",
    "buG3fAccTime", "buG4fAccTime", "buG6fAccTime", "buG8fAccTime",
    "bu_1fGTime", "bu_2fGTime", "bu_3fGTime", "bu_4_2fTime",
    "bu_6_4fTime", "bu_8_6fTime", "bu_10_8fTime",
)


def load_rows(directory: Path, name: str) -> list[dict]:
    result: list[dict] = []
    for path in sorted(directory.glob(f"{name}_page_*.json")):
        container = response_body(json.loads(path.read_text(encoding="utf-8"))).get("items") or {}
        rows = container.get("item") if isinstance(container, dict) else []
        if isinstance(rows, dict):
            rows = [rows]
        result.extend(rows or [])
    return result


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def date8(value: object) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())[:8]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    audit = args.audit_dir.resolve()
    db_path = args.database.resolve()
    capture = json.loads((audit / "freshness_report.json").read_text(encoding="utf-8"))
    as_of = capture["as_of_kst"].replace("-", "")

    race_rows = load_rows(audit, "race_result_year")
    trial_rows = load_rows(audit, "trial_result_year")
    daily_rows = load_rows(audit, "daily_training_month")
    start_rows = load_rows(audit, "start_training_month")
    medical_rows = load_rows(audit, "medical_year")
    weight_rows = load_rows(audit, "weight_month")
    equipment_rows = load_rows(audit, "equipment_recent_default_window")

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    race_current = [row for row in race_rows if date8(row["rcDate"]) <= as_of]
    race_future = [row for row in race_rows if date8(row["rcDate"]) > as_of]
    api_race_keys = {
        (date8(row["rcDate"]), int(row["rcNo"]), clean(row["hrNo"]).zfill(7))
        for row in race_current
    }
    db_race_keys = {
        (row[0].replace("-", ""), row[1], clean(row[2]).zfill(7))
        for row in con.execute(
            "SELECT race_date,race_no,hr_no FROM entry "
            "WHERE race_date BETWEEN '2026-01-01' AND ?", (capture["as_of_kst"],))
    }
    db_results = {
        (row[0].replace("-", ""), row[1], clean(row[2]).zfill(7)): row[3:]
        for row in con.execute(
            "SELECT race_date,race_no,hr_no,finish_raw,race_time_s,win_odds,place_odds "
            "FROM result WHERE race_date BETWEEN '2026-01-01' AND ?", (capture["as_of_kst"],))
    }
    result_mismatches = 0
    for row in race_current:
        key = (date8(row["rcDate"]), int(row["rcNo"]), clean(row["hrNo"]).zfill(7))
        actual = db_results[key]
        expected = (
            clean(row.get("ord")), float(row.get("rcTime") or 0),
            float(row.get("winOdds") or 0), float(row.get("plcOdds") or 0),
        )
        observed = (clean(actual[0]), float(actual[1] or 0), float(actual[2] or 0), float(actual[3] or 0))
        result_mismatches += expected != observed
    db_sections = {
        (row[0].replace("-", ""), row[1], clean(row[2]).zfill(7), row[3]): row[4]
        for row in con.execute(
            "SELECT race_date,race_no,hr_no,source_field,value_s FROM section "
            "WHERE race_date BETWEEN '2026-01-01' AND ?", (capture["as_of_kst"],))
    }
    section_mismatches = 0
    for row in race_current:
        prefix = (date8(row["rcDate"]), int(row["rcNo"]), clean(row["hrNo"]).zfill(7))
        for field in SECTION_FIELDS:
            section_mismatches += float(row.get(field) or 0) != float(db_sections[prefix + (field,)] or 0)
    completed_dates = [
        date8(row["rcDate"]) for row in race_current
        if float(row.get("rcTime") or 0) > 0 or int(row.get("ord") or 0) > 0
    ]

    api_trial = {
        (date8(row["trainDate"]), int(row["trainNo"]), int(row["chulNo"])): row
        for row in trial_rows if date8(row["trainDate"]) <= as_of
    }
    db_trial_raw = {
        (row[0].replace("-", ""), row[1], row[2]): json.loads(row[3])
        for row in con.execute(
            "SELECT trial_date,trial_no,chul_no,raw_json FROM trial_api_entry "
            "WHERE trial_date BETWEEN '2026-01-01' AND ?", (capture["as_of_kst"],))
    }
    trial_revisions = []
    for key in sorted(api_trial.keys() & db_trial_raw.keys()):
        fresh, old = api_trial[key], db_trial_raw[key]
        changes = {
            field: {"database": old.get(field), "fresh_api": fresh.get(field)}
            for field in sorted(set(fresh) | set(old)) if fresh.get(field) != old.get(field)
        }
        if changes:
            trial_revisions.append({
                "trial_date": key[0], "trial_no": key[1], "chul_no": key[2],
                "hr_no": fresh.get("hrNo"), "horse_name": fresh.get("hrName"),
                "changes": changes,
            })

    def date_delta(rows: list[dict], field: str, table: str, where: str = "1=1") -> dict:
        api_counts = Counter(date8(row[field]) for row in rows if date8(row[field]) <= as_of)
        query = f"SELECT replace(event_date,'-',''),count(*) FROM {table} WHERE {where} AND event_date<=? GROUP BY 1"
        db_counts = dict(con.execute(query, (capture["as_of_kst"],)).fetchall())
        return {
            day: {"fresh_api": api_counts.get(day, 0), "database": db_counts.get(day, 0),
                  "delta": api_counts.get(day, 0) - db_counts.get(day, 0)}
            for day in sorted(set(api_counts) | set(db_counts)) if day.startswith(as_of[:6])
        }

    daily_delta = date_delta(daily_rows, "trDate", "training_event", "source_type='horse_training'")
    start_delta = date_delta(start_rows, "trDate", "training_event", "source_type='start_training'")
    daily_snapshot = capture["datasets"]["daily_training_month"]["snapshot_last_date"].replace("-", "")
    start_snapshot = capture["datasets"]["start_training_month"]["snapshot_last_date"].replace("-", "")
    medical_snapshot = capture["datasets"]["medical_year"]["snapshot_last_date"].replace("-", "")

    def after_snapshot(rows: list[dict], field: str, snapshot: str) -> dict:
        selected = [row for row in rows if snapshot < date8(row[field]) <= as_of]
        return {
            "rows": len(selected),
            "horses": len({clean(row.get("hrNo")) for row in selected if clean(row.get("hrNo"))}),
            "by_date": dict(sorted(Counter(date8(row[field]) for row in selected).items())),
        }

    fresh_medical = Counter(
        (date8(row["clinicDate"]), clean(row.get("hrNo")), clean(row.get("hrName")),
         clean(row.get("part")), clean(row.get("hospiName")), clean(row.get("illName1")),
         clean(row.get("illName2")))
        for row in medical_rows if date8(row["clinicDate"]) <= as_of
    )
    db_medical = Counter(
        (row[0].replace("-", ""), *(clean(value) for value in row[1:]))
        for row in con.execute(
            "SELECT event_date,hr_no,horse_name,part_raw,facility_raw,diagnosis_1_raw,diagnosis_2_raw "
            "FROM medical_api_event WHERE event_date BETWEEN '2026-01-01' AND ?",
            (capture["as_of_kst"],))
    )

    historical_weight = [row for row in weight_rows if date8(row["rcDate"]) <= as_of]
    future_weight = [row for row in weight_rows if date8(row["rcDate"]) > as_of]
    actual_weight_keys = {
        (date8(row["rcDate"]), int(row["rcNo"]), int(row["chulNo"]))
        for row in historical_weight if int(row.get("wgHr") or 0) > 0
    }
    db_weight_keys = {
        (row[0].replace("-", ""), row[1], row[2])
        for row in con.execute(
            "SELECT race_date,race_no,chul_no FROM race_day_weight "
            "WHERE race_date<=? AND race_date>='2026-09-01' AND link_status='confirmed'",
            (capture["as_of_kst"],))
    }

    yeongcheon_weight_rows = con.execute(
        "SELECT count(*) FROM race_day_weight WHERE race_date='2026-09-13' "
        "AND source_path LIKE '%20260913dacom12.rpt'"
    ).fetchone()[0]
    exposed_yeongcheon_rows = con.execute(
        "SELECT count(*) FROM analysis_race_entry_history WHERE race_date='2026-09-13'"
    ).fetchone()[0]
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = len(con.execute("PRAGMA foreign_key_check").fetchall())
    con.close()

    verification = {
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "as_of_kst": capture["as_of_kst"],
        "database": str(db_path),
        "database_sha256": sha256(db_path),
        "database_integrity": integrity,
        "foreign_key_violations": foreign_keys,
        "verdict": "partially_current_update_required",
        "race": {
            "latest_confirmed_date": max(completed_dates),
            "fresh_rows_on_or_before_as_of": len(race_current),
            "database_rows_2026_on_or_before_as_of": len(db_race_keys),
            "api_only_keys": len(api_race_keys - db_race_keys),
            "database_only_keys": len(db_race_keys - api_race_keys),
            "result_value_mismatches": result_mismatches,
            "section_values_compared": len(race_current) * len(SECTION_FIELDS),
            "section_value_mismatches": section_mismatches,
            "future_card": {
                "dates": dict(sorted(Counter(date8(row["rcDate"]) for row in race_future).items())),
                "races": len({(date8(row["rcDate"]), int(row["rcNo"])) for row in race_future}),
                "rows": len(race_future),
                "all_result_fields_zero": all(
                    float(row.get("rcTime") or 0) == 0 and int(row.get("ord") or 0) == 0
                    for row in race_future),
            },
        },
        "trial": {
            "latest_date": max(key[0] for key in api_trial),
            "fresh_rows": len(api_trial), "database_rows": len(db_trial_raw),
            "api_only_keys": len(api_trial.keys() - db_trial_raw.keys()),
            "database_only_keys": len(db_trial_raw.keys() - api_trial.keys()),
            "revised_rows": trial_revisions,
        },
        "daily_training": {"new": after_snapshot(daily_rows, "trDate", daily_snapshot),
                           "september_date_counts": daily_delta},
        "start_training": {"new": after_snapshot(start_rows, "trDate", start_snapshot),
                           "september_date_counts": start_delta},
        "medical": {
            "new": after_snapshot(medical_rows, "clinicDate", medical_snapshot),
            "fresh_2026_rows": sum(fresh_medical.values()),
            "database_2026_rows": sum(db_medical.values()),
            "fresh_multiset_additions": sum((fresh_medical - db_medical).values()),
            "stale_multiset_rows_removed_by_current_api": sum((db_medical - fresh_medical).values()),
        },
        "weight": {
            "historical_actual_api_keys": len(actual_weight_keys),
            "historical_confirmed_database_keys": len(db_weight_keys),
            "api_only_actual_keys": len(actual_weight_keys - db_weight_keys),
            "database_only_confirmed_keys": len(db_weight_keys - actual_weight_keys),
            "future_rows": len(future_weight),
            "future_rows_with_positive_weight": sum(int(row.get("wgHr") or 0) > 0 for row in future_weight),
        },
        "equipment": {
            "future_rows": sum(date8(row["rcDate"]) > as_of for row in equipment_rows),
            "future_dates": sorted({date8(row["rcDate"]) for row in equipment_rows if date8(row["rcDate"]) > as_of}),
        },
        "scope_issue": {
            "yeongcheon_weight_rows_in_base_table": yeongcheon_weight_rows,
            "link_status": "unmatched",
            "rows_exposed_by_analysis_view": exposed_yeongcheon_rows,
            "source_header": "(영천) 26년 9월 13일",
        },
    }
    output = audit / "verification.json"
    output.write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "verdict": verification["verdict"],
        "race_latest": verification["race"]["latest_confirmed_date"],
        "trial_revisions": len(trial_revisions),
        "daily_training_new": verification["daily_training"]["new"]["rows"],
        "start_training_new": verification["start_training"]["new"]["rows"],
        "medical_new": verification["medical"]["new"]["rows"],
        "yeongcheon_weight_rows": yeongcheon_weight_rows,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
