#!/usr/bin/env python3
"""2022 running-trial score database. Seoul, Busan, and Jeju stay separate.

Busan sheet columns are not one cumulative ladder:
S1F is the opening 200m cumulative, SEG400 is the next 400m segment,
and L400 is the last 400m. G1F is the last 200m, distinct from L400.
The printed Busan G3F is stored as its own row because it is not always
S1F + SEG400.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from horse_racing.parsers.running_trials import parse_running_trial_report

ROOT = Path(__file__).resolve().parents[1]
OPERATIONAL = ROOT / "data/horse_racing.sqlite3"
OUT = ROOT / "data/research/running_trials_2022_score_20260925/running_trials_2022.sqlite3"


def _add_file_only_rows(con: sqlite3.Connection) -> None:
    """Keep dacom23 horses that the operational trial table does not have."""
    names: dict[str, list[str]] = {}
    for horse_id, name in con.execute("SELECT kra_horse_id, name_ko FROM op.horses"):
        names.setdefault(name, []).append(horse_id)
    existing = set(con.execute("SELECT meet_code, trial_date, trial_race_number, horse_number FROM entry"))
    trials = set(con.execute("SELECT meet_code, trial_date, trial_race_number FROM trial"))
    next_id = -1
    root = ROOT / "data/raw/kra_text/dacom23"
    for meet in (1, 2, 3):
        for path in sorted((root / f"meet={meet}" / "year=2022").rglob("*.rpt")):
            for trial in parse_running_trial_report(path.read_bytes(), meet=meet):
                key = (meet, trial.trial_date.isoformat(), trial.trial_race_number)
                if key not in trials and any(((*key, row.horse_number) not in existing) for row in trial.results):
                    con.execute(
                        "INSERT INTO trial VALUES (?,?,?,?,?,?,?,?,?)",
                        (*key, trial.trial_round, trial.distance_m, trial.weather, trial.track_condition, trial.track_moisture_percent, next_id),
                    )
                    trials.add(key)
                    next_id -= 1
                for row in trial.results:
                    slot = (*key, row.horse_number)
                    if slot in existing:
                        continue
                    matched = names.get(row.horse_name, [])
                    horse_id = matched[0] if len(matched) == 1 else None
                    con.execute(
                        """
                        INSERT INTO entry (
                          meet_code, trial_date, trial_race_number, horse_number, kra_horse_id, horse_name,
                          finish_position, finish_time_ms, judgement, failure_reason, inspection_reason,
                          passing_order_raw)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (*slot, horse_id, row.horse_name, row.finish_position, row.finish_time_ms, row.judgement, row.failure_reason, row.inspection_reason, row.passing_order_raw),
                    )
                    existing.add(slot)
                    points = [
                        ("S1F", "cumulative", row.s1f_ms),
                        ("G1F", "closing", row.g1f_ms),
                        ("G3F", "closing", row.g3f_ms),
                    ]
                    if meet in (1, 2):
                        points.extend([("3C", "cumulative", row.corner_3_ms), ("4C", "cumulative", row.corner_4_ms)])
                    con.executemany(
                        "INSERT OR IGNORE INTO section_time VALUES (?,?,?,?,?,?,?)",
                        [(*slot, code, kind, ms) for code, kind, ms in points if ms and ms > 0],
                    )


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    con = sqlite3.connect(OUT)
    con.executescript(
        """
        CREATE TABLE point_definition (
          meet_code INTEGER NOT NULL,
          point_code TEXT NOT NULL,
          time_kind TEXT NOT NULL,
          meaning TEXT NOT NULL,
          PRIMARY KEY (meet_code, point_code)
        );
        CREATE TABLE trial (
          meet_code INTEGER NOT NULL,
          trial_date TEXT NOT NULL,
          trial_race_number INTEGER NOT NULL,
          trial_round INTEGER,
          distance_m INTEGER NOT NULL,
          weather TEXT,
          track_condition TEXT,
          track_moisture_percent REAL,
          operational_trial_id INTEGER NOT NULL,
          PRIMARY KEY (meet_code, trial_date, trial_race_number)
        );
        CREATE TABLE entry (
          id INTEGER PRIMARY KEY,
          meet_code INTEGER NOT NULL,
          trial_date TEXT NOT NULL,
          trial_race_number INTEGER NOT NULL,
          horse_number INTEGER NOT NULL,
          kra_horse_id TEXT,
          horse_name TEXT NOT NULL,
          finish_position INTEGER,
          finish_time_ms INTEGER,
          judgement TEXT,
          failure_reason TEXT,
          inspection_reason TEXT,
          passing_order_raw TEXT,
          UNIQUE (meet_code, trial_date, trial_race_number, horse_number)
        );
        CREATE TABLE section_time (
          meet_code INTEGER NOT NULL,
          trial_date TEXT NOT NULL,
          trial_race_number INTEGER NOT NULL,
          horse_number INTEGER NOT NULL,
          point_code TEXT NOT NULL,
          time_kind TEXT NOT NULL,
          elapsed_time_ms INTEGER NOT NULL,
          PRIMARY KEY (meet_code, trial_date, trial_race_number, horse_number, point_code)
        );
        CREATE VIEW busan_partition AS
        SELECT e.meet_code, e.trial_date, e.trial_race_number, e.horse_number,
               e.kra_horse_id, e.finish_time_ms,
               s1.elapsed_time_ms AS s1f_cumulative_ms,
               mid.elapsed_time_ms AS seg400_ms,
               last.elapsed_time_ms AS last400_ms,
               s1.elapsed_time_ms + mid.elapsed_time_ms + last.elapsed_time_ms AS partition_sum_ms,
               g3.elapsed_time_ms AS g3f_printed_ms,
               g1.elapsed_time_ms AS g1f_closing_ms
        FROM entry e
        JOIN section_time s1
          ON s1.meet_code=e.meet_code AND s1.trial_date=e.trial_date
         AND s1.trial_race_number=e.trial_race_number AND s1.horse_number=e.horse_number
         AND s1.point_code='S1F'
        JOIN section_time mid
          ON mid.meet_code=e.meet_code AND mid.trial_date=e.trial_date
         AND mid.trial_race_number=e.trial_race_number AND mid.horse_number=e.horse_number
         AND mid.point_code='SEG400'
        JOIN section_time last
          ON last.meet_code=e.meet_code AND last.trial_date=e.trial_date
         AND last.trial_race_number=e.trial_race_number AND last.horse_number=e.horse_number
         AND last.point_code='L400'
        LEFT JOIN section_time g3
          ON g3.meet_code=e.meet_code AND g3.trial_date=e.trial_date
         AND g3.trial_race_number=e.trial_race_number AND g3.horse_number=e.horse_number
         AND g3.point_code='G3F'
        LEFT JOIN section_time g1
          ON g1.meet_code=e.meet_code AND g1.trial_date=e.trial_date
         AND g1.trial_race_number=e.trial_race_number AND g1.horse_number=e.horse_number
         AND g1.point_code='G1F'
        WHERE e.meet_code=3;
        """
    )
    con.executemany(
        "INSERT INTO point_definition VALUES (?,?,?,?)",
        [
            (1, "S1F", "cumulative", "출발 200m 누적. 서울 주행심사에서는 3코너 기록과 같다."),
            (1, "3C", "cumulative", "3코너 통과 누적."),
            (1, "4C", "cumulative", "4코너 통과 누적."),
            (1, "G3F", "closing", "결승 600m 구간. 서울 경주의 누적 G3F와 다른 기록이다."),
            (1, "G1F", "closing", "결승 200m."),
            (2, "S1F", "cumulative", "출발 200m 누적. 제주 주행심사에서는 3코너 기록과 같다."),
            (2, "3C", "cumulative", "3코너 통과 누적."),
            (2, "4C", "cumulative", "4코너 통과 누적."),
            (2, "G3F", "closing", "결승 600m 구간."),
            (2, "G1F", "closing", "결승 200m."),
            (3, "S1F", "cumulative", "출발 200m 누적."),
            (3, "SEG400", "segment", "S1F 다음 400m 구간기록. 600m 누적 지점이 아니다."),
            (3, "L400", "closing", "마지막 400m. G1F(마지막 200m)와 별개다."),
            (3, "G3F", "printed", "성적표 G-3F 원기록. S1F+SEG400으로 바꾸지 않는다."),
            (3, "G1F", "closing", "마지막 200m. L400과 별개다."),
        ],
    )
    con.execute("ATTACH DATABASE ? AS op", (str(OPERATIONAL),))
    con.execute(
        """
        INSERT INTO trial
        SELECT t.meet_code, t.trial_date_local, t.trial_race_number, t.trial_round,
               t.distance_m, t.weather, t.track_condition, t.track_moisture_percent, t.id
        FROM op.running_trials t
        WHERE t.meet_code IN (1,2,3)
          AND t.trial_date_local>='2022-01-01' AND t.trial_date_local<'2023-01-01'
        """
    )
    con.execute(
        """
        INSERT INTO entry (
          meet_code, trial_date, trial_race_number, horse_number, kra_horse_id, horse_name,
          finish_position, finish_time_ms, judgement, failure_reason, inspection_reason,
          passing_order_raw)
        SELECT t.meet_code, t.trial_date_local, t.trial_race_number, r.horse_number,
               h.kra_horse_id, r.horse_name_raw, r.finish_position, r.finish_time_ms,
               r.judgement, r.failure_reason, r.inspection_reason, r.passing_order_raw
        FROM op.running_trial_results r
        JOIN op.running_trials t ON t.id=r.running_trial_id
        LEFT JOIN op.horses h ON h.id=r.horse_id
        WHERE t.meet_code IN (1,2,3)
          AND t.trial_date_local>='2022-01-01' AND t.trial_date_local<'2023-01-01'
        """
    )
    con.execute(
        """
        INSERT INTO section_time
        SELECT meet_code, trial_date, trial_race_number, horse_number, point_code, time_kind, elapsed_time_ms
        FROM (
          SELECT t.meet_code, t.trial_date_local AS trial_date, t.trial_race_number, r.horse_number,
                 'S1F' AS point_code, 'cumulative' AS time_kind, r.s1f_ms AS elapsed_time_ms
          FROM op.running_trial_results r
          JOIN op.running_trials t ON t.id=r.running_trial_id
          WHERE t.meet_code IN (1,2,3)
            AND t.trial_date_local>='2022-01-01' AND t.trial_date_local<'2023-01-01'
            AND r.s1f_ms>0
          UNION ALL
          SELECT t.meet_code, t.trial_date_local, t.trial_race_number, r.horse_number,
                 '3C', 'cumulative', r.corner_3_ms
          FROM op.running_trial_results r
          JOIN op.running_trials t ON t.id=r.running_trial_id
          WHERE t.meet_code IN (1,2)
            AND t.trial_date_local>='2022-01-01' AND t.trial_date_local<'2023-01-01'
            AND r.corner_3_ms>0
          UNION ALL
          SELECT t.meet_code, t.trial_date_local, t.trial_race_number, r.horse_number,
                 '4C', 'cumulative', r.corner_4_ms
          FROM op.running_trial_results r
          JOIN op.running_trials t ON t.id=r.running_trial_id
          WHERE t.meet_code IN (1,2)
            AND t.trial_date_local>='2022-01-01' AND t.trial_date_local<'2023-01-01'
            AND r.corner_4_ms>0
          UNION ALL
          SELECT t.meet_code, t.trial_date_local, t.trial_race_number, r.horse_number,
                 'G3F', CASE WHEN t.meet_code=3 THEN 'printed' ELSE 'closing' END, r.g3f_ms
          FROM op.running_trial_results r
          JOIN op.running_trials t ON t.id=r.running_trial_id
          WHERE t.meet_code IN (1,2,3)
            AND t.trial_date_local>='2022-01-01' AND t.trial_date_local<'2023-01-01'
            AND r.g3f_ms>0
          UNION ALL
          SELECT t.meet_code, t.trial_date_local, t.trial_race_number, r.horse_number,
                 'G1F', 'closing', r.g1f_ms
          FROM op.running_trial_results r
          JOIN op.running_trials t ON t.id=r.running_trial_id
          WHERE t.meet_code IN (1,2,3)
            AND t.trial_date_local>='2022-01-01' AND t.trial_date_local<'2023-01-01'
            AND r.g1f_ms>0
          UNION ALL
          SELECT t.meet_code, t.trial_date_local, t.trial_race_number, r.horse_number,
                 'SEG400', 'segment', r.section_400_ms
          FROM op.running_trial_results r
          JOIN op.running_trials t ON t.id=r.running_trial_id
          WHERE t.meet_code=3
            AND t.trial_date_local>='2022-01-01' AND t.trial_date_local<'2023-01-01'
            AND r.section_400_ms>0
          UNION ALL
          SELECT t.meet_code, t.trial_date_local, t.trial_race_number, r.horse_number,
                 'L400', 'closing', r.final_400_ms
          FROM op.running_trial_results r
          JOIN op.running_trials t ON t.id=r.running_trial_id
          WHERE t.meet_code=3
            AND t.trial_date_local>='2022-01-01' AND t.trial_date_local<'2023-01-01'
            AND r.final_400_ms>0
        )
        """
    )
    _add_file_only_rows(con)
    con.commit()
    con.execute("DETACH DATABASE op")
    print("trials", con.execute("SELECT meet_code, COUNT(*) FROM trial GROUP BY 1").fetchall())
    print("entries", con.execute("SELECT meet_code, COUNT(*) FROM entry GROUP BY 1").fetchall())
    print(
        "sections",
        con.execute(
            "SELECT meet_code, point_code, time_kind, COUNT(*) FROM section_time GROUP BY 1,2,3 ORDER BY 1,2"
        ).fetchall(),
    )
    print(
        "unlinked",
        con.execute("SELECT meet_code, COUNT(*) FROM entry WHERE kra_horse_id IS NULL GROUP BY 1").fetchall(),
    )
    print(
        "busan partition",
        con.execute(
            """
            SELECT COUNT(*),
                   SUM(ABS(partition_sum_ms-finish_time_ms)<=200),
                   SUM(ABS((s1f_cumulative_ms+seg400_ms)-g3f_printed_ms)>200)
            FROM busan_partition
            WHERE finish_time_ms>0
            """
        ).fetchone(),
    )
    con.close()


if __name__ == "__main__":
    main()
