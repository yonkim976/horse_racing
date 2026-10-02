#!/usr/bin/env python3
"""Busan 2023 scorecard database from the operational DB. Read-only source.

2023 Busan sheets store S1F, G3F, and G1F only. S1F is the opening 200m
cumulative. G3F and G1F are closing, unlike the 2025 and 2026 cumulative ladders.
Passing-order slots still follow the Busan corner map, including G2F and G4F
order strings on days when those time columns are absent.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPERATIONAL = ROOT / "data/horse_racing.sqlite3"
OUT = ROOT / "data/research/busan_2023_score_20260925/busan_2023.sqlite3"

PASSING_POINTS = {
    "corner_1_raw": "G8F",
    "corner_2_raw": "G6F",
    "corner_3_raw": "G4F",
    "corner_5_raw": "G3F",
    "corner_7_raw": "S1F",
    "corner_8_raw": "G2F",
    "corner_9_raw": "G1F",
}


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    con = sqlite3.connect(OUT)
    con.executescript(
        """
        CREATE TABLE race (
          meet_code INTEGER NOT NULL,
          race_date TEXT NOT NULL,
          race_number INTEGER NOT NULL,
          distance_m INTEGER NOT NULL,
          operational_race_id INTEGER NOT NULL,
          grade TEXT, race_name TEXT, weather TEXT, track_condition TEXT,
          track_moisture_percent REAL, tempo_raw TEXT,
          PRIMARY KEY (meet_code, race_date, race_number)
        );
        CREATE TABLE entry (
          id INTEGER PRIMARY KEY,
          meet_code INTEGER NOT NULL,
          race_date TEXT NOT NULL,
          race_number INTEGER NOT NULL,
          horse_number INTEGER NOT NULL,
          kra_horse_id TEXT NOT NULL,
          horse_name TEXT NOT NULL,
          operational_race_entry_id INTEGER NOT NULL,
          finish_position INTEGER,
          finish_time_ms INTEGER,
          rank_remark TEXT,
          UNIQUE (meet_code, race_date, race_number, horse_number),
          UNIQUE (meet_code, race_date, race_number, kra_horse_id)
        );
        CREATE TABLE section_time (
          meet_code INTEGER NOT NULL,
          race_date TEXT NOT NULL,
          race_number INTEGER NOT NULL,
          kra_horse_id TEXT NOT NULL,
          point_code TEXT NOT NULL,
          time_kind TEXT NOT NULL,
          elapsed_time_ms INTEGER,
          position INTEGER,
          source_name TEXT NOT NULL,
          PRIMARY KEY (meet_code, race_date, race_number, kra_horse_id, point_code, time_kind)
        );
        CREATE TABLE passing_group (
          meet_code INTEGER NOT NULL,
          race_date TEXT NOT NULL,
          race_number INTEGER NOT NULL,
          point_code TEXT NOT NULL,
          notation_raw TEXT NOT NULL,
          PRIMARY KEY (meet_code, race_date, race_number, point_code)
        );
        CREATE VIEW point_cumulative AS
        SELECT s.meet_code, s.race_date, s.race_number, s.kra_horse_id, s.point_code,
               'cumulative' AS time_kind,
               e.finish_time_ms - s.elapsed_time_ms AS elapsed_time_ms
        FROM section_time s
        JOIN entry e
          ON e.meet_code=s.meet_code AND e.race_date=s.race_date
         AND e.race_number=s.race_number AND e.kra_horse_id=s.kra_horse_id
        WHERE s.time_kind='closing'
          AND s.point_code IN ('G3F','G1F')
          AND s.elapsed_time_ms > 0
          AND e.finish_time_ms > s.elapsed_time_ms;
        """
    )
    con.execute("ATTACH DATABASE ? AS op", (str(OPERATIONAL),))
    con.execute(
        """
        INSERT INTO race
        SELECT 3, r.race_date_local, r.race_number, r.distance_m, r.id,
               r.grade, r.race_name, r.weather, r.track_condition, r.track_moisture_percent,
               p.tempo_raw
        FROM op.races r
        JOIN op.racecourses c ON c.id=r.racecourse_id
        LEFT JOIN op.race_passing_summaries p ON p.race_id=r.id
        WHERE c.kra_meet_code=3 AND r.status='completed'
          AND r.race_date_local>='2023-01-01' AND r.race_date_local<'2024-01-01'
        """
    )
    con.execute(
        """
        INSERT INTO entry (
          meet_code, race_date, race_number, horse_number, kra_horse_id, horse_name,
          operational_race_entry_id, finish_position, finish_time_ms, rank_remark)
        SELECT 3, r.race_date_local, r.race_number, e.horse_number, h.kra_horse_id, h.name_ko,
               e.id, res.finish_position, res.finish_time_ms, res.rank_remark
        FROM op.race_entries e
        JOIN op.races r ON r.id=e.race_id
        JOIN op.racecourses c ON c.id=r.racecourse_id
        JOIN op.horses h ON h.id=e.horse_id
        LEFT JOIN op.race_results res ON res.race_entry_id=e.id
        WHERE c.kra_meet_code=3 AND r.status='completed'
          AND r.race_date_local>='2023-01-01' AND r.race_date_local<'2024-01-01'
        """
    )
    con.execute(
        """
        INSERT INTO section_time
        SELECT 3, r.race_date_local, r.race_number, h.kra_horse_id, s.section_code,
               CASE
                 WHEN s.section_code='S1F' THEN 'cumulative'
                 WHEN s.section_code IN ('G3F','G1F') THEN 'closing'
               END,
               CASE WHEN s.elapsed_time_ms>0 THEN s.elapsed_time_ms END,
               CASE WHEN s.position>0 THEN s.position END,
               'operational_2023_busan'
        FROM op.race_section_results s
        JOIN op.race_entries e ON e.id=s.race_entry_id
        JOIN op.races r ON r.id=e.race_id
        JOIN op.racecourses c ON c.id=r.racecourse_id
        JOIN op.horses h ON h.id=e.horse_id
        WHERE c.kra_meet_code=3 AND r.status='completed'
          AND r.race_date_local>='2023-01-01' AND r.race_date_local<'2024-01-01'
          AND s.section_code IN ('S1F','G3F','G1F')
          AND (s.elapsed_time_ms>0 OR s.position>0)
        """
    )
    for column, point in PASSING_POINTS.items():
        con.execute(
            f"""
            INSERT INTO passing_group
            SELECT 3, r.race_date_local, r.race_number, ?, p.{column}
            FROM op.race_passing_summaries p
            JOIN op.races r ON r.id=p.race_id
            JOIN op.racecourses c ON c.id=r.racecourse_id
            WHERE c.kra_meet_code=3 AND r.status='completed'
              AND r.race_date_local>='2023-01-01' AND r.race_date_local<'2024-01-01'
              AND p.{column} IS NOT NULL AND p.{column} NOT IN ('', '-', 'X')
            """,
            (point,),
        )
    con.commit()
    con.execute("DETACH DATABASE op")
    print("races", con.execute("SELECT COUNT(*) FROM race").fetchone()[0])
    print("entries", con.execute("SELECT COUNT(*) FROM entry").fetchone()[0])
    print(
        "sections",
        con.execute(
            "SELECT point_code, time_kind, COUNT(*) FROM section_time GROUP BY 1,2 ORDER BY 1"
        ).fetchall(),
    )
    print("groups", con.execute("SELECT point_code, COUNT(*) FROM passing_group GROUP BY 1 ORDER BY 1").fetchall())
    con.close()


if __name__ == "__main__":
    main()
