"""Read-only operational equipment inventory and strong-key comparison.

This deliberately does not read source_documents payloads or emit raw equipment
strings. It compares the new confirmed-runner core with operational SQLite using
meet/date/race/horse-number plus official horse ID.

Run from the repository root with ``.venv/bin/python``. The only output file is
``audit_summary.json`` beside this script.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[4]
CORE_PATH = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
OPERATIONAL_PATH = ROOT / "data/horse_racing.sqlite3"
OUTPUT_PATH = Path(__file__).resolve().parent / "audit_summary.json"
START_DATE = "2010-01-01"
END_DATE = "2026-09-29"
MEETS = (1, 3, 4)
DATE_IN_TEXT = re.compile(r"20\d{2}[.\-/]\s?\d{1,2}[.\-/]\s?\d{1,2}")


def iso_day(value: Any) -> str:
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return date.fromisoformat(text[:10]).isoformat()


def normalized(value: str | None) -> str:
    return "".join((value or "").split())


def runner_key(row: sqlite3.Row | tuple[Any, ...]) -> tuple[int, str, int, int]:
    return int(row[0]), iso_day(row[1]), int(row[2]), int(row[3])


def run() -> dict[str, Any]:
    core_db = duckdb.connect(str(CORE_PATH), read_only=True)
    try:
        equipment_columns = core_db.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema='main'
              AND (column_name ILIKE '%equip%' OR column_name ILIKE '%장구%')
            ORDER BY table_name, column_name
            """
        ).fetchall()
        core_rows = core_db.execute(
            """
            SELECT source_meet, result_date, result_race_no,
                   horse_program_no_raw, horse_id_raw
            FROM confirmed_runners
            """
        ).fetchall()
    finally:
        core_db.close()

    core: dict[tuple[int, str, int, int], str] = {}
    for meet, day, race_no, horse_no, horse_id in core_rows:
        key = (int(meet), iso_day(day), int(race_no), int(horse_no))
        if key in core:
            raise RuntimeError("confirmed_runners contains a duplicate strong key")
        core[key] = str(horse_id)

    sqlite_uri = f"file:{OPERATIONAL_PATH.as_posix()}?mode=ro"
    operational_db = sqlite3.connect(sqlite_uri, uri=True, timeout=10)
    operational_db.row_factory = sqlite3.Row
    operational_db.execute("PRAGMA query_only=ON")
    operational_db.execute("BEGIN")
    try:
        scope = (START_DATE, END_DATE)
        entries = operational_db.execute(
            """
            SELECT c.kra_meet_code, r.race_date_local, r.race_number,
                   e.horse_number, h.kra_horse_id, e.id,
                   e.equipment, e.equipment_card_raw,
                   e.equipment_card_observed_at_ms
            FROM race_entries AS e
            JOIN races AS r ON r.id=e.race_id
            JOIN racecourses AS c ON c.id=r.racecourse_id
            JOIN horses AS h ON h.id=e.horse_id
            WHERE c.kra_meet_code IN (1, 3, 4)
              AND r.race_date_local BETWEEN ? AND ?
            """,
            scope,
        ).fetchall()
        equipment_rows = operational_db.execute(
            """
            SELECT q.meet_code, q.race_date_local, q.race_number,
                   q.horse_number, h.kra_horse_id, q.equipment_raw,
                   q.observed_at_ms
            FROM entry_equipment AS q
            LEFT JOIN horses AS h ON h.id=q.horse_id
            WHERE q.meet_code IN (1, 3, 4)
              AND q.race_date_local BETWEEN ? AND ?
            """,
            scope,
        ).fetchall()
        marks = operational_db.execute(
            """
            SELECT m.race_entry_id, m.change_type
            FROM entry_equipment_changes AS m
            JOIN race_entries AS e ON e.id=m.race_entry_id
            JOIN races AS r ON r.id=e.race_id
            JOIN racecourses AS c ON c.id=r.racecourse_id
            WHERE c.kra_meet_code IN (1, 3, 4)
              AND r.race_date_local BETWEEN ? AND ?
            """,
            scope,
        ).fetchall()
        raw_rows = operational_db.execute(
            """
            SELECT meet_code, race_date_local, equipment_raw, observed_at_ms
            FROM entry_equipment
            WHERE meet_code IN (1, 3, 4)
              AND race_date_local BETWEEN ? AND ?
            """,
            scope,
        ).fetchall()
    finally:
        operational_db.rollback()
        operational_db.close()

    operational: dict[tuple[int, str, int, int], sqlite3.Row] = {}
    for row in entries:
        key = runner_key(row)
        if key in operational:
            raise RuntimeError("race_entries contains a duplicate strong key")
        operational[key] = row

    raw_by_key: dict[tuple[int, str, int, int], sqlite3.Row] = {}
    for row in equipment_rows:
        key = runner_key(row)
        if key in raw_by_key:
            raise RuntimeError("entry_equipment contains a duplicate strong key")
        raw_by_key[key] = row

    marks_by_entry: Counter[int] = Counter(int(row[0]) for row in marks)
    marks_by_type: Counter[str] = Counter(str(row[1]) for row in marks)
    marks_by_entry_type: Counter[tuple[int, str]] = Counter(
        (int(row[0]), str(row[1])) for row in marks
    )
    per_meet: dict[int, Counter[str]] = defaultdict(Counter)
    totals: Counter[str] = Counter()
    period_counts: dict[tuple[int, str], Counter[str]] = defaultdict(Counter)
    period_timestamps: dict[tuple[int, str], set[int]] = defaultdict(set)

    windows = (("2010-2014", "2010", "2014"), ("2015-2024", "2015", "2024"), ("2025-2026", "2025", "2026"))
    for row in raw_rows:
        meet = int(row[0])
        year = str(row[1])[:4]
        raw = row[2]
        window = next((label for label, start, end in windows if start <= year <= end), None)
        if window is None:
            continue
        bucket = period_counts[(meet, window)]
        bucket["rows"] += 1
        bucket["raw_nonblank"] += bool(normalized(raw))
        bucket["contains_date_pattern"] += bool(raw and DATE_IN_TEXT.search(raw))
        bucket["multiline_or_aggregated_separator"] += bool(raw and ("\n" in raw or " | " in raw))
        if row[3] is not None:
            period_timestamps[(meet, window)].add(int(row[3]))

    for row in entries:
        meet = int(row[0])
        raw_card = row[7]
        stats = per_meet[meet]
        stats["operational_entries"] += 1
        totals["operational_entries"] += 1
        if normalized(row[6]):
            stats["race_entries_equipment_nonblank"] += 1
            totals["race_entries_equipment_nonblank"] += 1
        if row[8] is not None:
            stats["api78_observed_entries"] += 1
            totals["api78_observed_entries"] += 1
            if normalized(raw_card):
                stats["api78_card_raw_nonblank"] += 1
                totals["api78_card_raw_nonblank"] += 1
            else:
                stats["api78_observed_empty_card_raw"] += 1
                totals["api78_observed_empty_card_raw"] += 1
        elif raw_card is not None:
            stats["card_raw_without_observation_timestamp"] += 1
            totals["card_raw_without_observation_timestamp"] += 1

    for row in equipment_rows:
        meet = int(row[0])
        per_meet[meet]["entry_equipment_rows"] += 1
        totals["entry_equipment_rows"] += 1
        if normalized(row[5]):
            per_meet[meet]["entry_equipment_raw_nonblank"] += 1
            totals["entry_equipment_raw_nonblank"] += 1

    for (meet, _day, _race, _number), horse_id in core.items():
        stats = per_meet[meet]
        stats["confirmed_core_runners"] += 1
        totals["confirmed_core_runners"] += 1

    api24_like_to_core = 0
    id_conflicts = 0
    id_missing = 0
    raw_nonblank_core_matches = 0
    raw_nonblank_with_shared_null = 0
    both_nonblank = 0
    both_nonblank_equal = 0
    both_nonblank_different = 0
    operational_key_matches = 0
    operational_id_matches = 0
    operational_id_conflicts = 0
    operational_equipment_nonblank_core_matches = 0
    api78_observed_core_matches = 0
    api78_nonblank_core_matches = 0
    api78_empty_core_matches = 0
    api78_marks_core_matches = 0
    api78_marks_core_by_type: Counter[str] = Counter()
    api78_missing_2017plus = 0
    api78_marks_core_types: Counter[str] = Counter()
    by_core_key: dict[int, Counter[str]] = defaultdict(Counter)

    for key, horse_id in core.items():
        meet = key[0]
        entry = operational.get(key)
        raw_event = raw_by_key.get(key)

        if entry is not None:
            operational_key_matches += 1
            by_core_key[meet]["operational_key_match"] += 1
            if str(entry[4]) == horse_id:
                operational_id_matches += 1
                by_core_key[meet]["operational_id_match"] += 1
                if normalized(entry[6]):
                    operational_equipment_nonblank_core_matches += 1
                    by_core_key[meet]["race_entries_equipment_nonblank_core_match"] += 1
                if entry[8] is not None:
                    api78_observed_core_matches += 1
                    by_core_key[meet]["api78_observed_core_match"] += 1
                    if normalized(entry[7]):
                        api78_nonblank_core_matches += 1
                        by_core_key[meet]["api78_card_raw_nonblank_core_match"] += 1
                    else:
                        api78_empty_core_matches += 1
                        by_core_key[meet]["api78_empty_card_raw_core_match"] += 1
                    api78_marks_core_matches += marks_by_entry[int(entry[5])]
                    by_core_key[meet]["api78_marks_core_match"] += marks_by_entry[int(entry[5])]
                    for change_type in ("added", "removed"):
                        matched_marks = marks_by_entry_type[(int(entry[5]), change_type)]
                        api78_marks_core_by_type[change_type] += matched_marks
                        by_core_key[meet][f"api78_{change_type}_marks_core_match"] += matched_marks
                elif key[1] >= "2017-01-01":
                    api78_missing_2017plus += 1
                    by_core_key[meet]["api78_missing_2017plus_core_match"] += 1
            else:
                operational_id_conflicts += 1
                by_core_key[meet]["operational_id_conflict"] += 1

        if raw_event is not None:
            api24_like_to_core += 1
            by_core_key[meet]["entry_equipment_key_match"] += 1
            raw_horse_id = raw_event[4]
            if raw_horse_id is None:
                id_missing += 1
                by_core_key[meet]["entry_equipment_horse_id_missing"] += 1
            elif str(raw_horse_id) == horse_id:
                by_core_key[meet]["entry_equipment_horse_id_match"] += 1
                if normalized(raw_event[5]):
                    raw_nonblank_core_matches += 1
                    if entry is not None and str(entry[4]) == horse_id:
                        if normalized(entry[6]):
                            both_nonblank += 1
                            if normalized(entry[6]) == normalized(raw_event[5]):
                                both_nonblank_equal += 1
                            else:
                                both_nonblank_different += 1
                        else:
                            raw_nonblank_with_shared_null += 1
            else:
                id_conflicts += 1
                by_core_key[meet]["entry_equipment_horse_id_conflict"] += 1

    # All +/- rows are also counted across the full operational population.
    for mark in marks:
        entry_id, change_type = int(mark[0]), str(mark[1])
        if change_type not in {"added", "removed"}:
            raise RuntimeError("entry_equipment_changes contains an unknown change type")

    mixed_origin_windows: dict[str, dict[str, int]] = {}
    mixed_origin_by_meet: dict[str, dict[str, dict[str, int]]] = {}
    for label, _start, _end in windows:
        counts: Counter[str] = Counter()
        timestamp_union: set[int] = set()
        per_meet_window: dict[str, dict[str, int]] = {}
        for meet in MEETS:
            meet_counts = period_counts[(meet, label)]
            counts.update(meet_counts)
            timestamp_union.update(period_timestamps[(meet, label)])
            per_meet_window[str(meet)] = {
                **dict(meet_counts),
                "distinct_observed_at_values": len(period_timestamps[(meet, label)]),
            }
        mixed_origin_windows[label] = {
            **dict(counts),
            "distinct_observed_at_values": len(timestamp_union),
        }
        mixed_origin_by_meet[label] = per_meet_window

    summary: dict[str, Any] = {
        "scope": {
            "start_date": START_DATE,
            "end_date": END_DATE,
            "meets": list(MEETS),
            "meet_names": {"1": "서울", "3": "부산경남", "4": "영천"},
        },
        "core": {
            "confirmed_runner_rows": len(core),
            "equipment_named_columns": [list(row) for row in equipment_columns],
            "strong_key_unique": True,
        },
        "operational_totals": {
            **dict(totals),
            "entry_equipment_changes_rows": len(marks),
            "entry_equipment_changes_by_type": dict(marks_by_type),
            "by_meet": {str(meet): dict(values) for meet, values in sorted(per_meet.items())},
        },
        "strong_key_linkage": {
            "race_entries_key_matches": operational_key_matches,
            "race_entries_official_horse_id_matches": operational_id_matches,
            "race_entries_official_horse_id_conflicts": operational_id_conflicts,
            "entry_equipment_key_matches": api24_like_to_core,
            "entry_equipment_official_horse_id_matches": api24_like_to_core - id_conflicts - id_missing,
            "entry_equipment_official_horse_id_conflicts": id_conflicts,
            "entry_equipment_official_horse_id_missing": id_missing,
            "entry_equipment_raw_nonblank_official_id_matches": raw_nonblank_core_matches,
            "entry_equipment_raw_nonblank_but_race_entries_equipment_null": raw_nonblank_with_shared_null,
            "both_raw_and_shared_nonblank": both_nonblank,
            "both_nonblank_equal_after_whitespace_removal": both_nonblank_equal,
            "both_nonblank_different_after_whitespace_removal": both_nonblank_different,
            "race_entries_equipment_nonblank_with_official_id_match": operational_equipment_nonblank_core_matches,
            "api78_observations_with_official_id_match": api78_observed_core_matches,
            "api78_nonblank_card_raw_with_official_id_match": api78_nonblank_core_matches,
            "api78_observed_empty_card_raw_with_official_id_match": api78_empty_core_matches,
            "api78_change_rows_with_official_id_match": api78_marks_core_matches,
            "api78_change_rows_by_type_with_official_id_match": dict(api78_marks_core_by_type),
            "2017plus_core_entries_missing_api78_observation_after_operational_id_match": api78_missing_2017plus,
            "per_meet": {str(meet): dict(values) for meet, values in sorted(by_core_key.items())},
        },
        "entry_equipment_mixed_origin_diagnostics": {
            "meaning": "Raw-string heuristics only; they do not classify row origin.",
            "windows": mixed_origin_windows,
            "by_meet_and_window": mixed_origin_by_meet,
            "row_level_source_document_foreign_key": False,
        },
        "api78_raw_state": {
            "observed_empty_is_raw_nonnull_and_whitespace_only": True,
            "missing_observation_is_observed_at_null": True,
            "raw_without_observation_timestamp": totals["card_raw_without_observation_timestamp"],
            "change_type_counts_operational": dict(marks_by_type),
        },
        "read_only": {
            "core_duckdb_read_only": True,
            "operational_sqlite_mode_ro": True,
            "operational_sqlite_query_only": True,
            "operational_sqlite_read_transaction": True,
            "source_document_urls_and_params_read_or_emitted": False,
            "database_writes_or_collection": False,
        },
    }
    OUTPUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
