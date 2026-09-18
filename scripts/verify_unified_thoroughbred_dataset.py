"""Independently verify the unified Seoul/Busan/Yeongcheon dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]
SEOUL = ROOT / "data/research/seoul_backfill_20260915_v1/history.sqlite3"
BUSAN = ROOT / "data/research/busan_complete_db_20260916/busan_complete.sqlite3"
OPERATING = ROOT / "data/horse_racing.sqlite3"


def scalar(con: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    return int(con.execute(sql, params).fetchone()[0])


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    database = args.database.resolve()
    db = duckdb.connect(str(database), read_only=True)
    seoul = sqlite3.connect(f"file:{SEOUL.resolve()}?mode=ro", uri=True)
    busan = sqlite3.connect(f"file:{BUSAN.resolve()}?mode=ro", uri=True)
    operating = sqlite3.connect(f"file:{OPERATING.resolve()}?mode=ro", uri=True)
    for con in (seoul, busan, operating):
        con.execute("PRAGMA query_only=ON")

    checks: list[dict] = []

    def check(name: str, actual: object, expected: object) -> None:
        checks.append({"name": name, "actual": actual, "expected": expected,
                       "passed": actual == expected})

    try:
        source_expected = {
            "SEOUL_race": scalar(seoul, "SELECT count(*) FROM race"),
            "SEOUL_entry": scalar(seoul, "SELECT count(*) FROM entry"),
            "SEOUL_section": scalar(seoul, "SELECT count(*) FROM section"),
            "BUSAN_race": scalar(busan, "SELECT count(*) FROM race"),
            "BUSAN_entry": scalar(busan, "SELECT count(*) FROM entry"),
            "BUSAN_section": scalar(busan, "SELECT count(*) FROM section"),
            "YEONGCHEON_race": scalar(operating, """
              SELECT count(*) FROM races r JOIN racecourses c ON c.id=r.racecourse_id
              WHERE c.kra_meet_code=4 AND r.status='completed' AND EXISTS(
                SELECT 1 FROM race_entries e JOIN race_results x ON x.race_entry_id=e.id
                WHERE e.race_id=r.id AND x.finish_time_ms>0)"""),
            "YEONGCHEON_entry": scalar(operating, """
              SELECT count(*) FROM race_entries e JOIN races r ON r.id=e.race_id
              JOIN racecourses c ON c.id=r.racecourse_id
              JOIN race_results x ON x.race_entry_id=e.id
              WHERE c.kra_meet_code=4 AND r.status='completed' AND x.finish_time_ms>0"""),
            "YEONGCHEON_section": scalar(operating, """
              SELECT count(*) FROM race_section_results s
              JOIN race_entries e ON e.id=s.race_entry_id
              JOIN races r ON r.id=e.race_id JOIN racecourses c ON c.id=r.racecourse_id
              WHERE c.kra_meet_code=4 AND r.status='completed'"""),
        }
        for venue in ("SEOUL", "BUSAN", "YEONGCHEON"):
            for table, output_table in (("race", "race"), ("entry", "entry_result"),
                                        ("section", "section")):
                actual = db.execute(
                    f"SELECT count(*) FROM {output_table} WHERE venue_code=?", [venue]
                ).fetchone()[0]
                check(f"source_count_{venue}_{table}", actual,
                      source_expected[f"{venue}_{table}"])

        for table, key in {
            "race": "race_id",
            "entry_result": "race_id,hr_no",
            "trial_entry": "trial_event_id,participant_no",
            "training_event": "training_event_id",
            "medical_event": "medical_event_id",
            "weight_event": "weight_event_id",
            "equipment_event": "equipment_event_id",
        }.items():
            duplicates = db.execute(
                f"SELECT count(*) FROM (SELECT {key},count(*) n FROM {table} "
                f"GROUP BY {key} HAVING n>1)"
            ).fetchone()[0]
            check(f"primary_key_unique_{table}", duplicates, 0)

        check("entry_orphans", db.execute("""
          SELECT count(*) FROM entry_result e LEFT JOIN race r USING(race_id)
          WHERE r.race_id IS NULL""").fetchone()[0], 0)
        check("section_orphans", db.execute("""
          SELECT count(*) FROM section s LEFT JOIN entry_result e USING(race_id,hr_no)
          WHERE e.race_id IS NULL""").fetchone()[0], 0)
        check("model_training_row_preservation",
              db.execute("SELECT count(*) FROM model_training_entry").fetchone()[0],
              db.execute("SELECT count(*) FROM model_target_entry").fetchone()[0])
        check("model_target_starts_2006",
              str(db.execute("SELECT min(race_date) FROM model_target_entry").fetchone()[0]),
              "2006-01-06")
        check("nonconfirmed_model_targets", db.execute("""
          SELECT count(*) FROM model_target_entry WHERE official_result_state<>'confirmed'
             OR race_date<'2006-01-01'""").fetchone()[0], 0)
        check("future_scheduled_cards_in_targets", db.execute("""
          SELECT count(*) FROM model_target_entry WHERE race_date>'2026-09-17'""").fetchone()[0], 0)

        # Reproduce the established 2006 Busan benchmark from the independent source DB.
        check("busan_2006_races",
              db.execute("SELECT count(*) FROM race WHERE venue_code='BUSAN' AND year(race_date)=2006").fetchone()[0],
              578)
        check("busan_2006_entries",
              db.execute("SELECT count(*) FROM entry_result WHERE venue_code='BUSAN' AND year(race_date)=2006").fetchone()[0],
              6569)
        for source_type in ("dacom01", "dacom12", "dacom71"):
            actual = scalar(busan, """SELECT count(DISTINCT race_date||'|'||race_no)
              FROM text_race_heading WHERE source_type=?
                AND race_date BETWEEN '2006-01-01' AND '2006-12-31'""", (source_type,))
            check(f"busan_2006_{source_type}_heading_keys", actual, 578)

        check("busan_false_yeongcheon_races", db.execute("""
          SELECT count(*) FROM race WHERE venue_code='BUSAN' AND race_date='2026-09-13'""").fetchone()[0], 0)
        check("busan_false_yeongcheon_weights", db.execute("""
          SELECT count(*) FROM weight_event WHERE venue_code='BUSAN' AND race_date='2026-09-13'""").fetchone()[0], 0)
        check("yeongcheon_first_meeting_races", db.execute("""
          SELECT count(*) FROM race WHERE venue_code='YEONGCHEON' AND race_date='2026-09-13'""").fetchone()[0], 6)
        check("yeongcheon_first_meeting_entries", db.execute("""
          SELECT count(*) FROM entry_result WHERE venue_code='YEONGCHEON' AND race_date='2026-09-13'""").fetchone()[0], 54)
        check("yeongcheon_first_meeting_weights", db.execute("""
          SELECT count(*) FROM weight_event WHERE venue_code='YEONGCHEON' AND race_date='2026-09-13'""").fetchone()[0], 54)
        check("yeongnam_trial_venue_unresolved", db.execute("""
          SELECT count(*) FROM trial_entry WHERE venue_resolution_status='unresolved_after_yeongcheon_split'
            AND venue_code IS NULL""").fetchone()[0], 48)
        check("known_trial_source_conflicts", db.execute("""
          SELECT count(*) FROM identity_issue WHERE issue_type='trial_source_conflict'
            AND status='ambiguous_source_conflict'""").fetchone()[0], 4)

        # Recompute all 28-day training features for a deterministic 250-row sample.
        training_mismatches = db.execute("""
          WITH sample AS (
            SELECT * FROM model_training_entry ORDER BY md5(race_id||hr_no) LIMIT 250
          ), recomputed AS (
            SELECT s.race_id,s.hr_no,
              count(DISTINCT CASE WHEN t.source_type='horse_training' THEN t.event_date END)
                FILTER(WHERE t.event_date>=s.race_date-INTERVAL 3 DAY) d3,
              count(DISTINCT CASE WHEN t.source_type='horse_training' THEN t.event_date END)
                FILTER(WHERE t.event_date>=s.race_date-INTERVAL 7 DAY) d7,
              count(DISTINCT CASE WHEN t.source_type='horse_training' THEN t.event_date END)
                FILTER(WHERE t.event_date>=s.race_date-INTERVAL 14 DAY) d14,
              count(DISTINCT CASE WHEN t.source_type='horse_training' THEN t.event_date END) d28,
              coalesce(sum(CASE WHEN t.source_type='horse_training' AND
                t.event_date>=s.race_date-INTERVAL 7 DAY THEN t.duration_seconds END),0) sec7,
              coalesce(sum(CASE WHEN t.source_type='horse_training' THEN t.duration_seconds END),0) sec28,
              count(*) FILTER(WHERE t.source_type='start_training') start28,
              count(DISTINCT t.training_venue_code) venues28
            FROM sample s LEFT JOIN training_event t ON t.hr_no=s.hr_no
              AND t.event_date<s.race_date AND t.event_date>=s.race_date-INTERVAL 28 DAY
            GROUP BY s.race_id,s.hr_no
          )
          SELECT count(*) FROM sample s JOIN recomputed x USING(race_id,hr_no)
          WHERE s.training_days_3d IS DISTINCT FROM x.d3
             OR s.training_days_7d IS DISTINCT FROM x.d7
             OR s.training_days_14d IS DISTINCT FROM x.d14
             OR s.training_days_28d IS DISTINCT FROM x.d28
             OR s.training_seconds_7d IS DISTINCT FROM x.sec7
             OR s.training_seconds_28d IS DISTINCT FROM x.sec28
             OR s.start_training_events_28d IS DISTINCT FROM x.start28
             OR s.training_venues_28d IS DISTINCT FROM x.venues28
        """).fetchone()[0]
        check("sample_strict_pre_race_training_reproduction", training_mismatches, 0)

        allowed_target_columns = {
            "target_result_status", "target_finish_order", "target_race_time_s",
            "target_is_rank_label", "target_is_dead_heat",
        }
        columns = {row[0] for row in db.execute("DESCRIBE model_training_entry").fetchall()}
        forbidden = sorted((columns & {
            "finish_raw", "finish_order", "result_status", "race_time_s",
            "win_odds", "place_odds", "diff_raw", "source_prior_races",
            "source_prior_wins",
        }) - allowed_target_columns)
        check("post_race_columns_excluded_from_feature_namespace", forbidden, [])

        parquet_counts = {}
        parquet_dir = database.parent / "parquet"
        for path in sorted(parquet_dir.glob("*.parquet")):
            table = path.stem
            rows = db.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]
            parquet_counts[table] = rows
            if table in {row[0] for row in db.execute("SHOW TABLES").fetchall()}:
                check(f"parquet_rows_{table}", rows,
                      db.execute(f"SELECT count(*) FROM {table}").fetchone()[0])

        summary = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "database": str(database.relative_to(ROOT)),
            "database_sha256": file_sha256(database),
            "checks_passed": sum(item["passed"] for item in checks),
            "checks_total": len(checks),
            "status": "pass" if all(item["passed"] for item in checks) else "fail",
            "checks": checks,
            "source_expected_counts": source_expected,
            "parquet_counts": parquet_counts,
        }
    finally:
        db.close()
        seoul.close()
        busan.close()
        operating.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "passed": summary["checks_passed"],
                      "total": summary["checks_total"]}, ensure_ascii=False))
    if summary["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
