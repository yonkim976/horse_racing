#!/usr/bin/env python3
"""Build section_points.sqlite3 without writing the operational DB."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
OPERATIONAL = ROOT / "data/horse_racing.sqlite3"
RESEARCH = ROOT / "data/research/thoroughbred_unified_20260918/thoroughbred_unified.duckdb"
OUT = ROOT / "data/research/section_point_db_20260925/section_points.sqlite3"
EXT = ROOT / "data/research/section_point_db_20260925/section_points_ext.sqlite3"
VERIFIED = ROOT / "data/research/section_point_db_20260925/section_points_verified.sqlite3"

TRACKS = [
    (1, 1000, "연장주로", "3코너 쪽 연장주로에서 외주로 합류. 결승은 외주로", "서울 경주로 구조, Seoul Track Analysis"),
    (1, 1200, "외주로", "외주로 후방 직선 출발", "서울 경주로 구조, Seoul Track Analysis"),
    (1, 1300, "외주로", "외주로 후방 직선 출발", "서울 경주로 구조, Seoul Track Analysis"),
    (1, 1400, "외주로", "외주로 후방 직선을 100m 연장한 출발", "서울 경주로 구조, Seoul Track Analysis"),
    (1, 1600, "외주로", "1·2코너 사이 지선. 1300m 지점에서 직선", "Seoul Track Analysis"),
    (1, 1700, "내주로", "관람대 앞 출발 후 외주로 결승. 야간 합류 지점이 다를 수 있음", "Seoul Track Analysis"),
    (1, 1800, "내주로", "주간은 내주로 후 외주로 결승. 야간은 1700m 출발 후 1300m에서 외주로", "서울 경주로 구조, Seoul Track Analysis"),
    (1, 1900, "내주로", "주간은 내주로 후 외주로 결승. 야간은 1800m 출발 후 1300m에서 외주로", "서울 경주로 구조, Seoul Track Analysis"),
    (1, 2000, "내주로", "1900m와 같은 출발. 1300m에서 외주로 합류", "Seoul Track Analysis"),
    (1, 2300, "외주로", "결승 직선 연장. 결승선을 두 번 통과", "서울 경주로 구조, Seoul Track Analysis"),
    (3, 1000, "연장주로", "3코너 연장주로에서 외주로 합류. 한글 단거리=내주로 문구와 다름", "Busan Track Analysis"),
    (3, 1200, "외주로", "외주로 후방 직선. 한글 단거리=내주로 문구와 다름", "Busan Track Analysis"),
    (3, 1300, "외주로", "외주로 후방 직선", "Busan Track Analysis"),
    (3, 1400, "외주로", "외주로 후방 직선", "Busan Track Analysis"),
    (3, 1600, "외주로", "후방 직선 시작 연장주로", "Busan Track Analysis"),
    (3, 1800, "내주로", "내주로 출발, 결승 직선은 외주로", "Busan Track Analysis"),
    (3, 1900, "내주로", "첫 코너 끝, 잔여 1300m에서 외주로 합류", "Busan Track Analysis"),
    (3, 2000, "내주로", "첫 코너 끝에서 외주로 합류", "Busan Track Analysis"),
    (3, 2200, "외주로", "관람대 앞. 결승선을 두 번 통과", "Busan Track Analysis"),
]

FIELD_MAP = {
    "buS1fAccTime": ("S1F", "start", "cumulative"),
    "buG8fAccTime": ("G8F", "furlong", "cumulative"),
    "buG6fAccTime": ("G6F", "furlong", "cumulative"),
    "buG4fAccTime": ("G4F", "furlong", "cumulative"),
    "buG3fAccTime": ("G3F", "furlong", "cumulative"),
    "buG2fAccTime": ("G2F", "furlong", "cumulative"),
    "buG1fAccTime": ("G1F", "furlong", "cumulative"),
    "bu_3fGTime": ("G3F", "furlong", "closing"),
    "bu_1fGTime": ("G1F", "furlong", "closing"),
    "bu_10_8fTime": ("10-8F", "segment", "segment"),
    "bu_8_6fTime": ("8-6F", "segment", "segment"),
    "bu_6_4fTime": ("6-4F", "segment", "segment"),
    "bu_4_2fTime": ("4-2F", "segment", "segment"),
    "bu_2fGTime": ("2F-G", "segment", "segment"),
}


def create(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE track_by_distance (
          meet_code INTEGER NOT NULL, distance_m INTEGER NOT NULL,
          start_track TEXT NOT NULL, route TEXT NOT NULL, source_note TEXT NOT NULL,
          PRIMARY KEY (meet_code, distance_m));
        CREATE TABLE section_time (
          id INTEGER PRIMARY KEY,
          meet_code INTEGER NOT NULL, race_date TEXT NOT NULL, race_number INTEGER NOT NULL,
          distance_m INTEGER, kra_horse_id TEXT, horse_number INTEGER, race_entry_id INTEGER,
          point_code TEXT NOT NULL, point_kind TEXT NOT NULL, time_kind TEXT NOT NULL,
          meters_from_start INTEGER, meters_before_finish INTEGER,
          elapsed_time_ms INTEGER NOT NULL, position INTEGER,
          source_name TEXT NOT NULL, source_field TEXT, source_basis TEXT,
          classification TEXT NOT NULL, geometry_note TEXT);
        CREATE TABLE finish_time (
          race_entry_id INTEGER PRIMARY KEY,
          meet_code INTEGER NOT NULL, race_date TEXT NOT NULL, race_number INTEGER NOT NULL,
          distance_m INTEGER, kra_horse_id TEXT, horse_number INTEGER,
          finish_position INTEGER, finish_time_ms INTEGER, scratched INTEGER NOT NULL,
          rank_remark TEXT, result_state TEXT NOT NULL);
        CREATE UNIQUE INDEX uq_section_source ON section_time (
          meet_code, race_date, race_number, ifnull(kra_horse_id,''), ifnull(horse_number,-1),
          point_code, time_kind, source_name, ifnull(source_field,''));
        """
    )
    con.executemany("INSERT INTO track_by_distance VALUES (?,?,?,?,?)", TRACKS)


def load_operational(con: sqlite3.Connection) -> None:
    con.execute("ATTACH DATABASE ? AS op", (f"file:{OPERATIONAL}?mode=ro",))
    con.execute(
        """
        INSERT INTO finish_time
        SELECT e.id, rc.kra_meet_code, r.race_date_local, r.race_number, r.distance_m,
               h.kra_horse_id, e.horse_number, res.finish_position, res.finish_time_ms,
               e.scratched, res.rank_remark,
               CASE
                 WHEN e.scratched = 1 THEN 'scratched'
                 WHEN res.finish_position IS NULL THEN 'no_finish_position'
                 WHEN res.finish_position >= 90 THEN 'special_result'
                 WHEN res.finish_time_ms IS NULL OR res.finish_time_ms <= 0 THEN 'finish_position_no_time'
                 ELSE 'finished'
               END
        FROM op.race_entries e
        JOIN op.races r ON r.id = e.race_id
        JOIN op.racecourses rc ON rc.id = r.racecourse_id
        JOIN op.horses h ON h.id = e.horse_id
        LEFT JOIN op.race_results res ON res.race_entry_id = e.id
        WHERE r.status = 'completed'
        """
    )
    con.execute(
        """
        INSERT INTO section_time (
          meet_code, race_date, race_number, distance_m, kra_horse_id, horse_number, race_entry_id,
          point_code, point_kind, time_kind, meters_from_start, meters_before_finish,
          elapsed_time_ms, position, source_name, source_field, source_basis, classification, geometry_note)
        SELECT rc.kra_meet_code, r.race_date_local, r.race_number, r.distance_m, h.kra_horse_id,
               e.horse_number, e.id, s.section_code,
               CASE WHEN s.section_code IN ('1C','2C','3C','4C') THEN 'corner'
                    WHEN s.section_code = 'S1F' THEN 'start'
                    WHEN s.section_code = 'FIN' THEN 'finish' ELSE 'furlong' END,
               'pending',
               CASE WHEN s.section_code = 'S1F' AND rc.kra_meet_code = 2 AND r.distance_m IN (1110,1610) THEN 210
                    WHEN s.section_code = 'S1F' THEN 200
                    WHEN s.section_code = 'G1F' AND r.distance_m > 200 THEN r.distance_m - 200
                    WHEN s.section_code = 'G2F' AND r.distance_m > 400 THEN r.distance_m - 400
                    WHEN s.section_code = 'G3F' AND r.distance_m > 600 THEN r.distance_m - 600
                    WHEN s.section_code = 'G4F' AND r.distance_m > 800 THEN r.distance_m - 800
                    WHEN s.section_code = 'G6F' AND r.distance_m > 1200 THEN r.distance_m - 1200
                    WHEN s.section_code = 'G8F' AND r.distance_m > 1600 THEN r.distance_m - 1600
                    WHEN s.section_code = 'FIN' THEN r.distance_m END,
               CASE WHEN s.section_code = 'G1F' THEN 200 WHEN s.section_code = 'G2F' THEN 400
                    WHEN s.section_code = 'G3F' THEN 600 WHEN s.section_code = 'G4F' THEN 800
                    WHEN s.section_code = 'G6F' THEN 1200 WHEN s.section_code = 'G8F' THEN 1600
                    WHEN s.section_code = 'S1F' AND rc.kra_meet_code = 2 AND r.distance_m IN (1110,1610) THEN r.distance_m - 210
                    WHEN s.section_code = 'S1F' AND r.distance_m > 200 THEN r.distance_m - 200 END,
               s.elapsed_time_ms, s.position, 'operational', COALESCE(s.source_kind,''), s.time_basis,
               'pending',
               CASE WHEN s.section_code IN ('1C','2C','3C','4C') THEN 'corner_distance_not_assigned'
                    WHEN s.section_code = 'S1F' AND rc.kra_meet_code = 2 AND r.distance_m IN (1110,1610) THEN 's1f_210m' END
        FROM op.race_section_results s
        JOIN op.race_entries e ON e.id = s.race_entry_id
        JOIN op.races r ON r.id = e.race_id
        JOIN op.racecourses rc ON rc.id = r.racecourse_id
        JOIN op.horses h ON h.id = e.horse_id
        WHERE s.elapsed_time_ms > 0
        """
    )
    con.commit()
    con.execute("DETACH DATABASE op")
    con.execute("UPDATE section_time SET time_kind='cumulative', classification='fixed_code' WHERE point_code IN ('S1F','FIN','1C','2C','3C','4C')")
    con.execute("UPDATE section_time SET time_kind='closing', classification='source_basis' WHERE meet_code=1 AND source_basis='closing' AND time_kind='pending'")
    con.execute("UPDATE section_time SET time_kind='cumulative', classification='source_basis' WHERE meet_code IN (1,3,4) AND source_basis='cumulative' AND time_kind='pending'")
    con.execute(
        """
        UPDATE section_time
        SET time_kind = (
          SELECT CASE
            WHEN abs(section_time.elapsed_time_ms * 1.0 / section_time.meters_before_finish
                     - f.finish_time_ms * 1.0 / section_time.distance_m)
              <= abs(section_time.elapsed_time_ms * 1.0 / section_time.meters_from_start
                     - f.finish_time_ms * 1.0 / section_time.distance_m)
            THEN 'closing' ELSE 'cumulative' END
          FROM finish_time f
          WHERE f.race_entry_id = section_time.race_entry_id
            AND f.finish_time_ms > 0),
            classification = 'pace_vs_finish'
        WHERE time_kind = 'pending'
          AND meters_before_finish > 0 AND meters_from_start > 0
          AND race_entry_id IN (SELECT race_entry_id FROM finish_time WHERE finish_time_ms > 0)
        """
    )
    con.execute("UPDATE section_time SET time_kind='unresolved', classification='unresolved' WHERE time_kind='pending'")


def load_busan_history(con: sqlite3.Connection) -> None:
    research = duckdb.connect(str(RESEARCH), read_only=True)
    field_sql = ",".join(f"'{name}'" for name in FIELD_MAP)
    rows = research.execute(
        f"""
        SELECT s.race_date::VARCHAR, s.race_no, lpad(s.hr_no, 7, '0'), s.source_field, s.value_ms,
               r.distance_m
        FROM section s
        LEFT JOIN race r ON r.venue_code=s.venue_code AND r.race_date=s.race_date AND r.race_no=s.race_no
        WHERE s.venue_code='BUSAN' AND s.race_date < DATE '2015-01-01'
          AND s.value_ms > 0 AND s.source_field IN ({field_sql})
        """
    ).fetchall()
    payload = []
    for race_date, race_no, horse_id, field, value_ms, distance_m in rows:
        code, kind, time_kind = FIELD_MAP[field]
        before = {"G1F": 200, "G2F": 400, "G3F": 600, "G4F": 800, "G6F": 1200, "G8F": 1600}.get(code)
        from_start = 200 if code == "S1F" else (distance_m - before if distance_m and before and distance_m > before else None)
        payload.append((3, race_date, race_no, distance_m, horse_id, code, kind, time_kind, from_start, before, int(value_ms), field))
    con.executemany(
        """
        INSERT OR IGNORE INTO section_time (
          meet_code, race_date, race_number, distance_m, kra_horse_id, point_code, point_kind, time_kind,
          meters_from_start, meters_before_finish, elapsed_time_ms, source_name, source_field, classification)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,'busan_research',?,'api_field')
        """,
        payload,
    )
    research.close()


SEGMENT_LENGTH = {
    1000: {"4-2F": 400, "2F-G": 400},
    1200: {"6-4F": 400, "4-2F": 400, "2F-G": 400},
    1300: {"8-6F": 100, "6-4F": 400, "4-2F": 400, "2F-G": 400},
    1400: {"6-4F": 400, "4-2F": 400, "2F-G": 400},
    1500: {"8-6F": 300, "6-4F": 400, "4-2F": 400, "2F-G": 400},
    1600: {"8-6F": 400, "6-4F": 400, "4-2F": 400, "2F-G": 400},
    1800: {"8-6F": 400, "6-4F": 400, "4-2F": 400, "2F-G": 400},
    1900: {"10-8F": 300, "8-6F": 400, "6-4F": 400, "4-2F": 400, "2F-G": 400},
    2000: {"10-8F": 400, "8-6F": 400, "6-4F": 400, "4-2F": 400, "2F-G": 400},
    2200: {"10-8F": 400, "8-6F": 400, "6-4F": 400, "4-2F": 400, "2F-G": 400},
}
SEGMENT_ORDER = ["10-8F", "8-6F", "6-4F", "4-2F", "2F-G"]
SEGMENT_FROM_START = {1200, 1300, 1500, 1600, 1900, 2000}
POLE_BEFORE = {"G1F": 200, "G2F": 400, "G3F": 600, "G4F": 800, "G6F": 1200, "G8F": 1600}


def segment_place(distance_m: int | None, code: str) -> tuple[int, int, int] | None:
    lengths = SEGMENT_LENGTH.get(distance_m or 0)
    if not lengths or code not in lengths:
        return None
    cursor = 0 if distance_m in SEGMENT_FROM_START else 200
    for name in SEGMENT_ORDER:
        if name not in lengths:
            continue
        length = lengths[name]
        if name == code:
            return length, cursor, (distance_m or 0) - (cursor + length)
        cursor += length
    return None


def point_meters(code: str, kind: str, distance_m: int | None) -> tuple[int | None, int | None, int | None, str | None]:
    if kind == "segment":
        placed = segment_place(distance_m, code)
        if placed is None:
            return None, None, None, "segment_length_not_in_official_table"
        length, start, remaining = placed
        return start + length, remaining, length, "official_segment_table"
    before = POLE_BEFORE.get(code)
    if code == "S1F":
        return 200, (distance_m - 200 if distance_m and distance_m > 200 else None), None, None
    if before and distance_m and distance_m > before:
        return distance_m - before, before, None, None
    return None, before, None, None


def ensure_columns(con: sqlite3.Connection) -> None:
    cols = {row[1] for row in con.execute("PRAGMA table_info(section_time)")}
    if "segment_length_m" not in cols:
        con.execute("ALTER TABLE section_time ADD COLUMN segment_length_m INTEGER")
    con.execute("CREATE INDEX IF NOT EXISTS ix_section_horse ON section_time(meet_code, race_date, race_number, kra_horse_id)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_finish_horse ON finish_time(meet_code, race_date, race_number, kra_horse_id)")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS s1f_field_mismatch (
          race_date TEXT, race_number INTEGER, kra_horse_id TEXT,
          acc_ms INTEGER, plain_ms INTEGER, diff_ms INTEGER)
        """
    )


def apply_segment_geometry(con: sqlite3.Connection) -> None:
    rows = con.execute(
        "SELECT id, distance_m, point_code FROM section_time WHERE point_kind='segment'"
    ).fetchall()
    updates = []
    for row_id, distance_m, code in rows:
        placed = segment_place(distance_m, code)
        if placed is None:
            updates.append((None, None, None, "segment_length_not_in_official_table", row_id))
            continue
        length, start, remaining = placed
        updates.append((start + length, remaining, length, "official_segment_table", row_id))
    con.executemany(
        """
        UPDATE section_time
        SET meters_from_start=?, meters_before_finish=?, segment_length_m=?, geometry_note=?
        WHERE id=?
        """,
        updates,
    )


def link_research_entries(con: sqlite3.Connection) -> None:
    con.execute(
        """
        UPDATE section_time
        SET race_entry_id = (
              SELECT f.race_entry_id FROM finish_time f
              WHERE f.meet_code=section_time.meet_code AND f.race_date=section_time.race_date
                AND f.race_number=section_time.race_number AND f.kra_horse_id=section_time.kra_horse_id),
            horse_number = (
              SELECT f.horse_number FROM finish_time f
              WHERE f.meet_code=section_time.meet_code AND f.race_date=section_time.race_date
                AND f.race_number=section_time.race_number AND f.kra_horse_id=section_time.kra_horse_id),
            distance_m = COALESCE(distance_m, (
              SELECT f.distance_m FROM finish_time f
              WHERE f.meet_code=section_time.meet_code AND f.race_date=section_time.race_date
                AND f.race_number=section_time.race_number AND f.kra_horse_id=section_time.kra_horse_id))
        WHERE source_name='busan_research' AND race_entry_id IS NULL
        """
    )


def classify_monotonic(con: sqlite3.Connection) -> None:
    con.execute(
        """
        UPDATE section_time
        SET time_kind='cumulative', classification='monotonic_without_finish'
        WHERE id IN (
          SELECT s.id FROM section_time s
          WHERE s.time_kind='unresolved'
            AND (
              SELECT COUNT(*) FROM section_time o
              WHERE o.race_entry_id=s.race_entry_id AND o.time_kind='unresolved'
                AND o.point_kind='furlong') >= 2
            AND NOT EXISTS (
              SELECT 1 FROM section_time a
              JOIN section_time b ON b.race_entry_id=a.race_entry_id
                AND b.meters_from_start > a.meters_from_start
                AND b.elapsed_time_ms <= a.elapsed_time_ms
              WHERE a.race_entry_id=s.race_entry_id AND a.time_kind='unresolved' AND b.time_kind='unresolved')
        )
        """
    )


def load_busan_from(con: sqlite3.Connection, date_predicate: str, *, preserve_all: bool = False) -> int:
    research = duckdb.connect(str(RESEARCH), read_only=True)
    field_sql = ",".join(f"'{name}'" for name in FIELD_MAP)
    rows = research.execute(
        f"""
        SELECT s.race_date::VARCHAR, s.race_no, lpad(s.hr_no, 7, '0'), s.source_field, s.value_ms, r.distance_m
        FROM section s
        LEFT JOIN race r ON r.venue_code=s.venue_code AND r.race_date=s.race_date AND r.race_no=s.race_no
        WHERE s.venue_code='BUSAN' AND {date_predicate}
          AND s.value_ms > 0 AND s.source_field IN ({field_sql})
        """
    ).fetchall()
    research.close()
    inserted = 0
    payload = []
    for race_date, race_no, horse_id, field, value_ms, distance_m in rows:
        code, kind, time_kind = FIELD_MAP[field]
        reached, before, length, note = point_meters(code, kind, distance_m)
        payload.append((3, race_date, race_no, distance_m, horse_id, code, kind, time_kind, reached, before, length, int(value_ms), field, note))
    con.execute("DROP TABLE IF EXISTS section_stage")
    con.execute(
        """
        CREATE TABLE section_stage (
          meet_code INTEGER, race_date TEXT, race_number INTEGER, distance_m INTEGER, kra_horse_id TEXT,
          point_code TEXT, point_kind TEXT, time_kind TEXT, meters_from_start INTEGER,
          meters_before_finish INTEGER, segment_length_m INTEGER, elapsed_time_ms INTEGER,
          source_field TEXT, geometry_note TEXT)
        """
    )
    con.executemany("INSERT INTO section_stage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", payload)
    before_count = con.execute("SELECT COUNT(*) FROM section_time").fetchone()[0]
    duplicate_filter = "" if preserve_all else """
        WHERE NOT EXISTS (
          SELECT 1 FROM section_time t
          WHERE t.meet_code=s.meet_code AND t.race_date=s.race_date AND t.race_number=s.race_number
            AND t.kra_horse_id=s.kra_horse_id AND t.point_code=s.point_code AND t.time_kind=s.time_kind
            AND abs(t.elapsed_time_ms - s.elapsed_time_ms) <= 200)
    """
    con.execute(
        f"""
        INSERT INTO section_time (
          meet_code, race_date, race_number, distance_m, kra_horse_id, point_code, point_kind, time_kind,
          meters_from_start, meters_before_finish, segment_length_m, elapsed_time_ms,
          source_name, source_field, classification, geometry_note)
        SELECT s.meet_code, s.race_date, s.race_number, s.distance_m, s.kra_horse_id, s.point_code, s.point_kind,
               s.time_kind, s.meters_from_start, s.meters_before_finish, s.segment_length_m, s.elapsed_time_ms,
               'busan_research', s.source_field, 'api_field', s.geometry_note
        FROM section_stage s
        {duplicate_filter}
        """
    )
    inserted = con.execute("SELECT COUNT(*) FROM section_time").fetchone()[0] - before_count
    con.execute("DROP TABLE section_stage")
    return inserted


def load_s1f_mismatches(con: sqlite3.Connection) -> None:
    research = duckdb.connect(str(RESEARCH), read_only=True)
    rows = research.execute(
        """
        SELECT a.race_date::VARCHAR, a.race_no, lpad(a.hr_no, 7, '0'), a.value_ms, b.value_ms, a.value_ms - b.value_ms
        FROM section a
        JOIN section b ON a.venue_code=b.venue_code AND a.race_date=b.race_date AND a.race_no=b.race_no AND a.hr_no=b.hr_no
        WHERE a.venue_code='BUSAN' AND a.source_field='buS1fAccTime' AND b.source_field='buS1fTime'
          AND a.value_ms > 0 AND b.value_ms > 0 AND a.value_ms <> b.value_ms
        """
    ).fetchall()
    research.close()
    con.execute("DELETE FROM s1f_field_mismatch")
    con.executemany("INSERT INTO s1f_field_mismatch VALUES (?,?,?,?,?,?)", rows)


def repair(con: sqlite3.Connection) -> None:
    """Align Busan time kinds to API fields and keep one representative row."""
    cols = {row[1] for row in con.execute("PRAGMA table_info(section_time)")}
    if "representation" not in cols:
        con.execute("ALTER TABLE section_time ADD COLUMN representation TEXT")
    con.execute("UPDATE section_time SET representation='canonical'")
    rows = con.execute(
        """
        SELECT id, race_entry_id, kra_horse_id, race_date, race_number, point_code, time_kind,
               source_name, ifnull(source_field,''), elapsed_time_ms, distance_m, meters_before_finish
        FROM section_time
        WHERE meet_code=3 AND point_code IN ('S1F','G1F','G2F','G3F','G4F','G6F','G8F')
        """
    ).fetchall()
    by_entry: dict[tuple, list] = {}
    for row in rows:
        key = (row[1], row[5]) if row[1] is not None else (row[2], row[3], row[4], row[5])
        by_entry.setdefault(key, []).append(row)
    relabel = []
    for items in by_entry.values():
        research = [item for item in items if item[7] == "busan_research"]
        for item in items:
            if item[7] != "operational":
                continue
            matched = {
                other[6]
                for other in research
                if abs(other[9] - item[9]) <= 200
            }
            if len(matched) == 1 and item[6] != next(iter(matched)):
                relabel.append((next(iter(matched)), "aligned_to_api_field", item[0]))
    con.executemany(
        "UPDATE section_time SET time_kind=?, classification=? WHERE id=?",
        relabel,
    )
    print("relabeled", len(relabel))
    rows = con.execute(
        """
        SELECT id, race_entry_id, kra_horse_id, race_date, race_number, point_code, time_kind,
               source_name, elapsed_time_ms, distance_m, meters_before_finish
        FROM section_time
        WHERE time_kind IN ('cumulative','closing','segment')
        """
    ).fetchall()
    groups: dict[tuple, list] = {}
    for row in rows:
        identity = (row[1],) if row[1] is not None else (row[2], row[3], row[4])
        groups.setdefault((*identity, row[5], row[6]), []).append(row)
    marks = []
    for items in groups.values():
        ranked = sorted(items, key=lambda item: (item[7] != "busan_research", item[0]))
        keeper = ranked[0]
        beyond = keeper[10] is not None and keeper[9] is not None and keeper[10] > keeper[9]
        marks.append(("geometry_excluded" if beyond else "canonical", keeper[0]))
        for item in ranked[1:]:
            kind = "redundant" if abs(item[8] - keeper[8]) <= 200 else "conflict"
            if item[10] is not None and item[9] is not None and item[10] > item[9]:
                kind = "geometry_excluded"
            marks.append((kind, item[0]))
    con.executemany("UPDATE section_time SET representation=? WHERE id=?", marks)
    con.execute(
        """
        UPDATE section_time SET representation='geometry_excluded'
        WHERE meters_before_finish IS NOT NULL AND distance_m IS NOT NULL
          AND meters_before_finish > distance_m
        """
    )


def create_verified_support(con: sqlite3.Connection) -> None:
    """Keep source time and passage rank separate; flag questionable records."""
    con.executescript(
        """
        CREATE INDEX ix_section_entry_point ON section_time(race_entry_id, point_code, source_name);
        CREATE TABLE point_position (
          race_entry_id INTEGER NOT NULL,
          point_code TEXT NOT NULL,
          position_raw INTEGER NOT NULL,
          position INTEGER,
          quality_status TEXT NOT NULL,
          source_name TEXT NOT NULL,
          PRIMARY KEY (race_entry_id, point_code));
        CREATE TABLE quality_issue (
          section_id INTEGER NOT NULL,
          issue_code TEXT NOT NULL,
          detail TEXT,
          PRIMARY KEY (section_id, issue_code));
        CREATE TEMP TABLE loaded_field_size AS
        SELECT meet_code, race_date, race_number, count(*) AS runners
        FROM finish_time GROUP BY meet_code, race_date, race_number;
        CREATE INDEX ix_loaded_field_size
          ON loaded_field_size(meet_code, race_date, race_number);
        INSERT INTO point_position
        SELECT s.race_entry_id, s.point_code, s.position,
               CASE WHEN s.position BETWEEN 1 AND f.runners THEN s.position END,
               CASE WHEN s.position >= 90 OR s.position < 1 THEN 'sentinel_or_invalid'
                    WHEN s.position > f.runners THEN 'above_loaded_field_size'
                    ELSE 'valid' END,
               'operational'
        FROM section_time s
        JOIN loaded_field_size f ON f.meet_code=s.meet_code AND f.race_date=s.race_date
          AND f.race_number=s.race_number
        WHERE s.source_name='operational' AND s.position IS NOT NULL;
        DROP TABLE loaded_field_size;

        INSERT INTO quality_issue
        SELECT id, 'invalid_geometry', geometry_note
        FROM section_time WHERE representation='geometry_excluded';
        INSERT INTO quality_issue
        SELECT id, 'missing_segment_geometry', geometry_note
        FROM section_time WHERE point_kind='segment' AND segment_length_m IS NULL;
        INSERT INTO quality_issue
        SELECT id, 'unlinked_runner', 'no matching completed race entry'
        FROM section_time WHERE race_entry_id IS NULL;
        INSERT INTO quality_issue
        SELECT id, 'unresolved_time_kind', classification
        FROM section_time WHERE time_kind='unresolved';
        INSERT INTO quality_issue
        SELECT s.id, 'exceeds_finish',
               CAST(s.elapsed_time_ms - f.finish_time_ms AS TEXT) || ' ms above finish'
        FROM section_time s JOIN finish_time f ON f.race_entry_id=s.race_entry_id
        WHERE s.representation='canonical' AND s.time_kind IN ('cumulative','closing')
          AND s.point_code<>'FIN' AND f.finish_time_ms>0
          AND s.elapsed_time_ms>f.finish_time_ms+200;
        INSERT OR IGNORE INTO quality_issue
        SELECT c.id, 'source_conflict', 'another source differs by more than 200 ms'
        FROM section_time d JOIN section_time c
          ON c.race_entry_id=d.race_entry_id AND c.point_code=d.point_code
          AND c.time_kind=d.time_kind AND c.representation='canonical'
        WHERE d.representation='conflict' AND d.race_entry_id IS NOT NULL;

        CREATE TEMP TABLE bad_pair AS
        SELECT c.id AS cumulative_id, g.id AS closing_id,
               c.elapsed_time_ms + g.elapsed_time_ms - f.finish_time_ms AS residual_ms
        FROM section_time c
        JOIN section_time g ON g.race_entry_id=c.race_entry_id AND g.point_code=c.point_code
          AND g.time_kind='closing' AND g.representation='canonical'
        JOIN finish_time f ON f.race_entry_id=c.race_entry_id
        WHERE c.representation='canonical' AND c.time_kind='cumulative'
          AND c.point_code IN ('G3F','G1F') AND f.finish_time_ms>0
          AND abs(c.elapsed_time_ms + g.elapsed_time_ms - f.finish_time_ms)>200;
        INSERT INTO quality_issue
        SELECT cumulative_id, 'pair_mismatch', CAST(residual_ms AS TEXT) || ' ms residual'
        FROM bad_pair;
        INSERT INTO quality_issue
        SELECT closing_id, 'pair_mismatch', CAST(residual_ms AS TEXT) || ' ms residual'
        FROM bad_pair;
        DROP TABLE bad_pair;
        """
    )
    flag_ambiguous_api_kind(con)


def flag_ambiguous_api_kind(con: sqlite3.Connection) -> None:
    """Mark raw Busan rows that fit both API time kinds equally plausibly."""
    con.execute(
        """
        INSERT OR IGNORE INTO quality_issue (section_id, issue_code, detail)
        SELECT o.id, 'ambiguous_api_kind',
               'operational time is within 200 ms of both cumulative and closing API fields'
        FROM section_time o
        WHERE o.source_name='operational' AND o.meet_code=3
          AND o.point_code IN ('G3F','G1F')
          AND EXISTS (
            SELECT 1 FROM section_time a
            WHERE a.race_entry_id=o.race_entry_id AND a.point_code=o.point_code
              AND a.source_name='busan_research' AND a.time_kind='cumulative'
              AND abs(a.elapsed_time_ms-o.elapsed_time_ms)<=200)
          AND EXISTS (
            SELECT 1 FROM section_time g
            WHERE g.race_entry_id=o.race_entry_id AND g.point_code=o.point_code
              AND g.source_name='busan_research' AND g.time_kind='closing'
              AND abs(g.elapsed_time_ms-o.elapsed_time_ms)<=200)
        """
    )


def create_views(con: sqlite3.Connection, *, verified: bool = False) -> None:
    if verified:
        con.executescript(
            """
            DROP VIEW IF EXISTS common_point;
            CREATE VIEW common_point AS
            SELECT s.meet_code, s.race_date, s.race_number, s.distance_m, s.kra_horse_id,
                   s.horse_number, s.race_entry_id, s.point_code, s.time_kind,
                   s.meters_from_start, s.meters_before_finish, s.elapsed_time_ms,
                   p.position, p.position_raw, p.quality_status AS position_quality_status,
                   p.source_name AS position_source, s.position AS source_position,
                   s.source_name, s.source_field, s.classification
            FROM section_time s
            LEFT JOIN point_position p ON p.race_entry_id=s.race_entry_id
              AND p.point_code=s.point_code
            WHERE s.representation='canonical'
              AND NOT EXISTS (
                SELECT 1 FROM quality_issue q WHERE q.section_id=s.id
                  AND q.issue_code IN ('invalid_geometry','missing_segment_geometry',
                    'unlinked_runner','unresolved_time_kind','exceeds_finish',
                    'source_conflict','pair_mismatch'))
              AND ((s.point_code='S1F' AND s.time_kind='cumulative'
                    AND s.meters_from_start=200)
                OR (s.point_code IN ('G3F','G1F')
                    AND s.time_kind IN ('cumulative','closing')));
            """
        )
        return
    con.executescript(
        """
        DROP VIEW IF EXISTS common_point;
        CREATE VIEW common_point AS
        SELECT s.meet_code, s.race_date, s.race_number, s.distance_m, s.kra_horse_id, s.horse_number,
               s.race_entry_id, s.point_code, s.time_kind, s.meters_from_start, s.meters_before_finish,
               s.elapsed_time_ms, s.position, s.source_name, s.source_field, s.classification
        FROM section_time s
        WHERE s.representation='canonical'
          AND ((s.point_code='S1F' AND s.time_kind='cumulative' AND s.meters_from_start=200)
           OR (s.point_code IN ('G3F','G1F') AND s.time_kind IN ('cumulative','closing')));
        """
    )


def extend() -> None:
    con = sqlite3.connect(EXT, timeout=120)
    ensure_columns(con)
    apply_segment_geometry(con)
    added = load_busan_from(con, "s.race_date >= DATE '2015-01-01'")
    link_research_entries(con)
    classify_monotonic(con)
    load_s1f_mismatches(con)
    repair(con)
    create_views(con)
    con.commit()
    print("added_post_2015", added)
    print("rows", con.execute("SELECT COUNT(*) FROM section_time").fetchone()[0])
    print("unresolved", con.execute("SELECT COUNT(*) FROM section_time WHERE time_kind='unresolved'").fetchone()[0])
    print("s1f_mismatch", con.execute("SELECT COUNT(*) FROM s1f_field_mismatch").fetchone()[0])
    con.close()


def build_verified() -> None:
    """Rebuild the serving-safe research DB from the two read-only source DBs."""
    if VERIFIED.exists():
        raise FileExistsError(f"Refusing to overwrite existing DB: {VERIFIED}")
    for source in (OPERATIONAL, RESEARCH):
        if not source.is_file():
            raise FileNotFoundError(source)
    VERIFIED.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(
        prefix=".section_points_verified_build_", suffix=".sqlite3", dir=VERIFIED.parent
    )
    os.close(descriptor)
    staging = Path(staging_name)
    try:
        con = sqlite3.connect(staging, timeout=120, uri=True)
        try:
            create(con)
            load_operational(con)
            con.commit()
            load_busan_history(con)
            con.commit()
            ensure_columns(con)
            apply_segment_geometry(con)
            added = load_busan_from(
                con, "s.race_date >= DATE '2015-01-01'", preserve_all=True
            )
            con.commit()
            link_research_entries(con)
            classify_monotonic(con)
            load_s1f_mismatches(con)
            con.commit()
            repair(con)
            con.commit()
            create_verified_support(con)
            create_views(con, verified=True)
            con.execute("ANALYZE")
            con.commit()
            if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite quick_check failed")
            duplicate = con.execute(
                """
                SELECT 1 FROM common_point
                GROUP BY meet_code, race_date, race_number, kra_horse_id,
                         point_code, time_kind HAVING count(*)>1 LIMIT 1
                """
            ).fetchone()
            if duplicate is not None:
                raise RuntimeError("common_point has duplicate runner/point/time-kind")
            print("added_post_2015", added)
            for table in ("section_time", "finish_time", "point_position", "quality_issue", "common_point"):
                print(table, con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        finally:
            con.close()
        os.link(staging, VERIFIED)
        print("verified_db", VERIFIED)
    finally:
        staging.unlink(missing_ok=True)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        raise FileExistsError(f"Refusing to overwrite existing DB: {OUT}")
    con = sqlite3.connect(OUT, uri=True)
    create(con)
    load_operational(con)
    con.commit()
    load_busan_history(con)
    con.commit()
    con.execute("ANALYZE")
    print("rows", con.execute("SELECT COUNT(*) FROM section_time").fetchone()[0])
    print("unresolved", con.execute("SELECT COUNT(*) FROM section_time WHERE time_kind='unresolved'").fetchone()[0])
    con.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "build-verified":
        build_verified()
    elif len(sys.argv) > 1 and sys.argv[1] == "annotate-verified":
        if not VERIFIED.is_file():
            raise FileNotFoundError(VERIFIED)
        connection = sqlite3.connect(VERIFIED)
        try:
            flag_ambiguous_api_kind(connection)
            connection.commit()
        finally:
            connection.close()
    elif len(sys.argv) > 1 and sys.argv[1] == "extend":
        extend()
    elif len(sys.argv) > 1 and sys.argv[1] == "repair":
        connection = sqlite3.connect(EXT, timeout=120)
        repair(connection)
        create_views(connection)
        connection.commit()
        connection.close()
    else:
        main()
