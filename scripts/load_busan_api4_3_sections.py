#!/usr/bin/env python3
"""Add Busan API4_3 cumulative, segment, and closing times to the score DBs.

Reads the archived raceResult_3 pages. Does not write the operational DB.
Existing rows with the same point and time kind are kept. A difference above
100ms is counted and not overwritten.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from collect_busan_history_results import items

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/research/busan_api4_3_sections_20260925/raw"
DBS = {
    2026: ROOT / "data/research/busan_2026_score_20260925/busan_2026.sqlite3",
    2025: ROOT / "data/research/busan_2025_score_20260925/busan_2025.sqlite3",
    2024: ROOT / "data/research/busan_2024_score_20260925/busan_2024.sqlite3",
    2023: ROOT / "data/research/busan_2023_score_20260925/busan_2023.sqlite3",
    2022: ROOT / "data/research/busan_2022_score_20260925/busan_2022.sqlite3",
    2021: ROOT / "data/research/busan_2021_score_20260925/busan_2021.sqlite3",
    2020: ROOT / "data/research/busan_2020_score_20260925/busan_2020.sqlite3",
    2019: ROOT / "data/research/busan_2019_score_20260925/busan_2019.sqlite3",
    2018: ROOT / "data/research/busan_2018_score_20260925/busan_2018.sqlite3",
    2017: ROOT / "data/research/busan_2017_score_20260925/busan_2017.sqlite3",
}

FIELDS = (
    ("buS1fAccTime", "S1F", "cumulative"),
    ("buG8fAccTime", "G8F", "cumulative"),
    ("buG6fAccTime", "G6F", "cumulative"),
    ("buG4fAccTime", "G4F", "cumulative"),
    ("buG3fAccTime", "G3F", "cumulative"),
    ("buG2fAccTime", "G2F", "cumulative"),
    ("buG1fAccTime", "G1F", "cumulative"),
    ("bu_3fGTime", "G3F", "closing"),
    ("bu_1fGTime", "G1F", "closing"),
    ("buS1fTime", "S-1F", "segment"),
    ("bu_10_8fTime", "10-8F", "segment"),
    ("bu_8_6fTime", "8-6F", "segment"),
    ("bu_6_4fTime", "6-4F", "segment"),
    ("bu_4_2fTime", "4-2F", "segment"),
    ("bu_2fGTime", "2F-G", "segment"),
)


def seconds_to_ms(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return int(round(seconds * 1000))


def race_date(value: object) -> str:
    text = str(value)
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def load_year(year: int) -> None:
    path = RAW / str(year) / "page_0001.json"
    rows = items(json.loads(path.read_bytes()))
    db = DBS[year]
    con = sqlite3.connect(db)
    columns = {row[1] for row in con.execute("PRAGMA table_info(section_time)")}
    if "source_field" not in columns:
        con.execute("ALTER TABLE section_time ADD COLUMN source_field TEXT")
    known = {
        (date, number, horse)
        for date, number, horse in con.execute(
            "SELECT race_date, race_number, kra_horse_id FROM entry"
        )
    }
    stored = {
        (date, number, horse, point, kind): ms
        for date, number, horse, point, kind, ms in con.execute(
            """
            SELECT race_date, race_number, kra_horse_id, point_code, time_kind, elapsed_time_ms
            FROM section_time
            """
        )
    }
    inserted = 0
    agreed = 0
    mismatched = 0
    skipped_horse = 0
    samples: list[tuple] = []
    pending: list[tuple] = []
    for row in rows:
        key = (race_date(row["rcDate"]), int(row["rcNo"]), str(row["hrNo"]))
        if key not in known:
            skipped_horse += 1
            continue
        for field, point, kind in FIELDS:
            ms = seconds_to_ms(row.get(field))
            if ms is None:
                continue
            slot = (*key, point, kind)
            current = stored.get(slot)
            if current is None:
                pending.append((*key, point, kind, ms, field))
                stored[slot] = ms
                inserted += 1
            elif abs(int(current) - ms) <= 100:
                agreed += 1
            else:
                mismatched += 1
                if len(samples) < 8:
                    samples.append((*key, point, kind, current, ms, field))
    con.executemany(
        """
        INSERT INTO section_time (
          meet_code, race_date, race_number, kra_horse_id, point_code, time_kind,
          elapsed_time_ms, position, source_name, source_field
        ) VALUES (3,?,?,?,?,?,?,NULL,'api4_3',?)
        """,
        pending,
    )
    con.commit()
    print(
        json.dumps(
            {
                "year": year,
                "api_rows": len(rows),
                "inserted": inserted,
                "already_agreed": agreed,
                "mismatched_kept": mismatched,
                "api_horses_not_in_score_db": skipped_horse,
                "mismatch_samples": samples,
            },
            ensure_ascii=False,
        )
    )
    con.close()


def main() -> None:
    for year in (2026, 2025, 2024, 2023, 2022, 2021, 2020, 2019, 2018, 2017):
        load_year(year)


if __name__ == "__main__":
    main()
