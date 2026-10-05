#!/usr/bin/env python3
"""Materialize raw sectional and passing-order source tables from 2010 onward.

Source tables keep their source column names and values. Derived operational
race/entry context tables are separate join bridges. All inputs are read-only.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import duckdb
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SECTION_DB = ROOT / "data/research/section_point_db_20260925/section_points_adjudicated.sqlite3"
OPERATIONAL_DB = ROOT / "data/horse_racing.sqlite3"
OUT = ROOT / "thoroughbred/data/section_passing_raw_2010plus_20260929_v1"
START_DATE = "2010-01-01"
MEETS = (1, 3, 4)
MEET_VENUE = {1: "SEOUL", 3: "BUSAN", 4: "YEONGCHEON"}


def confirmed_error_keys() -> set[tuple[int, str, int]]:
    base = ROOT / "thoroughbred/research/20260929_calendar_api_v1"
    all_keys = set()
    for filename, expected in (("planless_positive_result_review.csv", 20),
                               ("result_only_nonfinish_anomaly_review.csv", 52)):
        with (base / filename).open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        keys = {(int(r["meet"]), f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:]}",
                 int(r["race_no"])) for r in rows}
        if len(rows) != len(keys) or len(keys) != expected or all_keys & keys:
            raise ValueError(f"Confirmed anomalous race key ledger changed: {filename}")
        all_keys |= keys
    return all_keys


def exclude_confirmed_errors(db: duckdb.DuckDBPyConnection, output: Path, inventory: dict) -> int:
    """Remove confirmed result API anomalies from the active sectional snapshot."""
    keys = confirmed_error_keys()
    db.execute("CREATE TEMP TABLE _excluded_races(meet_code INTEGER, race_date VARCHAR, race_number INTEGER)")
    db.executemany("INSERT INTO _excluded_races VALUES (?, ?, ?)", sorted(keys))
    db.execute("CREATE TEMP TABLE _excluded_entries AS SELECT race_entry_id FROM spdb_finish_time f "
               "JOIN _excluded_races b USING(meet_code,race_date,race_number)")
    related = {
        "spdb_section_time": db.execute("SELECT count(*) FROM spdb_section_time s JOIN _excluded_races b "
                                         "USING(meet_code,race_date,race_number)").fetchone()[0],
        "spdb_point_position": db.execute("SELECT count(*) FROM spdb_point_position "
                                           "WHERE race_entry_id IN (SELECT race_entry_id FROM _excluded_entries)").fetchone()[0],
    }
    if any(related.values()):
        raise ValueError(f"Unexpected related rows for confirmed API anomalies: {related}")
    removed = db.execute("SELECT count(*) FROM _excluded_entries").fetchone()[0]
    db.execute("DELETE FROM spdb_finish_time f USING _excluded_races b "
               "WHERE f.meet_code=b.meet_code AND f.race_date=b.race_date "
               "AND f.race_number=b.race_number")
    inventory["spdb_finish_time"]["rows"] = db.execute("SELECT count(*) FROM spdb_finish_time").fetchone()[0]
    parquet = output / "parquet/spdb_finish_time.parquet"
    if removed:
        replacement = parquet.with_name("spdb_finish_time.filtered.parquet")
        db.execute("COPY spdb_finish_time TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(replacement)])
        replacement.replace(parquet)
    db.execute("DROP TABLE _excluded_entries")
    db.execute("DROP TABLE _excluded_races")
    return removed

SECTION_QUERIES = {
    "spdb_finish_time": """
        SELECT * FROM finish_time
        WHERE meet_code IN (1,3,4) AND race_date >= '2010-01-01'
    """,
    "spdb_section_time": """
        SELECT * FROM section_time
        WHERE meet_code IN (1,3,4) AND race_date >= '2010-01-01'
    """,
    "spdb_point_position": """
        SELECT p.* FROM point_position p JOIN finish_time f USING(race_entry_id)
        WHERE f.meet_code IN (1,3,4) AND f.race_date >= '2010-01-01'
    """,
    "spdb_quality_issue": """
        SELECT q.* FROM quality_issue q JOIN section_time s ON s.id=q.section_id
        WHERE s.meet_code IN (1,3,4) AND s.race_date >= '2010-01-01'
    """,
    "spdb_s1f_field_mismatch": """
        SELECT m.* FROM s1f_field_mismatch m
        WHERE EXISTS (
          SELECT 1 FROM finish_time f
          WHERE f.meet_code IN (1,3,4) AND f.race_date >= '2010-01-01'
            AND f.race_date=m.race_date AND f.race_number=m.race_number
            AND f.kra_horse_id=m.kra_horse_id
        )
    """,
    "spdb_section_source_evidence": """
        SELECT e.* FROM section_source_evidence e JOIN section_time s ON s.id=e.section_id
        WHERE s.meet_code IN (1,3,4) AND s.race_date >= '2010-01-01'
    """,
    "spdb_source_adjudication": """
        SELECT a.* FROM source_adjudication a JOIN section_time s ON s.id=a.section_id
        WHERE s.meet_code IN (1,3,4) AND s.race_date >= '2010-01-01'
    """,
    "spdb_pair_adjudication": """
        SELECT p.* FROM pair_adjudication p
        WHERE EXISTS (
          SELECT 1 FROM section_time s
          WHERE s.id IN (p.cumulative_section_id,p.closing_section_id)
            AND s.meet_code IN (1,3,4) AND s.race_date >= '2010-01-01'
        )
    """,
    "spdb_track_by_distance": """
        SELECT * FROM track_by_distance WHERE meet_code IN (1,3,4)
    """,
}

OPERATIONAL_QUERIES = {
    "op_race_passing_groups": """
        SELECT q.* FROM race_passing_groups q
        JOIN races r ON r.id=q.race_id JOIN racecourses c ON c.id=r.racecourse_id
        WHERE c.kra_meet_code IN (1,3,4) AND r.race_date_local >= '2010-01-01'
    """,
    "op_race_passing_summaries": """
        SELECT q.* FROM race_passing_summaries q
        JOIN races r ON r.id=q.race_id JOIN racecourses c ON c.id=r.racecourse_id
        WHERE c.kra_meet_code IN (1,3,4) AND r.race_date_local >= '2010-01-01'
    """,
    "op_race_section_results": """
        SELECT q.* FROM race_section_results q
        JOIN race_entries e ON e.id=q.race_entry_id
        JOIN races r ON r.id=e.race_id JOIN racecourses c ON c.id=r.racecourse_id
        WHERE c.kra_meet_code IN (1,3,4) AND r.race_date_local >= '2010-01-01'
    """,
    "op_race_section_times": """
        SELECT q.* FROM race_section_times q
        JOIN race_entries e ON e.id=q.race_entry_id
        JOIN races r ON r.id=e.race_id JOIN racecourses c ON c.id=r.racecourse_id
        WHERE c.kra_meet_code IN (1,3,4) AND r.race_date_local >= '2010-01-01'
    """,
}


def open_sqlite_readonly(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    return con


def duck_type(sqlite_type: str) -> str:
    kind = sqlite_type.upper()
    if "INT" in kind:
        return "BIGINT"
    if any(x in kind for x in ("REAL", "FLOA", "DOUB")):
        return "DOUBLE"
    if "BLOB" in kind:
        return "BLOB"
    return "VARCHAR"


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def create_empty_table(db: duckdb.DuckDBPyConnection, src: sqlite3.Connection,
                       source_table: str, dest_table: str) -> None:
    schema = src.execute(f"PRAGMA table_info({quote_ident(source_table)})").fetchall()
    columns = ",".join(f"{quote_ident(row[1])} {duck_type(row[2])}" for row in schema)
    db.execute(f"CREATE TABLE {quote_ident(dest_table)} ({columns})")


def materialize(db: duckdb.DuckDBPyConnection, src: sqlite3.Connection,
                source_table: str, dest_table: str, query: str) -> int:
    count = 0
    # Create from SQLite's declared schema first. Pandas infers from each chunk;
    # some source TEXT columns contain numeric-looking values in early chunks.
    create_empty_table(db, src, source_table, dest_table)
    for frame in pd.read_sql_query(query, src, chunksize=100_000):
        db.register("_incoming", frame)
        try:
            db.execute(f"INSERT INTO {quote_ident(dest_table)} BY NAME SELECT * FROM _incoming")
            count += len(frame)
        finally:
            db.unregister("_incoming")
    return count


def main() -> None:
    for path in (SECTION_DB, OPERATIONAL_DB):
        if not path.is_file():
            raise FileNotFoundError(path)
    if OUT.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {OUT}")
    OUT.mkdir(parents=True)
    (OUT / "parquet").mkdir()

    section = open_sqlite_readonly(SECTION_DB)
    operational = open_sqlite_readonly(OPERATIONAL_DB)
    db = duckdb.connect(str(OUT / "section_passing_raw.duckdb"))
    db.execute("SET threads=4")
    db.execute("SET memory_limit='4GB'")

    inventory: dict[str, dict[str, object]] = {}
    for table, query in SECTION_QUERIES.items():
        source_table = table.removeprefix("spdb_")
        rows = materialize(db, section, source_table, table, query)
        parquet = OUT / "parquet" / f"{table}.parquet"
        db.execute(f"COPY {quote_ident(table)} TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(parquet)])
        cols = [r[1] for r in section.execute(f"PRAGMA table_info({quote_ident(source_table)})").fetchall()]
        inventory[table] = {"source_db": str(SECTION_DB.relative_to(ROOT)), "source_table": source_table,
                            "rows": rows, "source_columns": cols, "date_filter": "2010-01-01 onward; meets 1, 3, 4"}

    for table, query in OPERATIONAL_QUERIES.items():
        source_table = table.removeprefix("op_")
        rows = materialize(db, operational, source_table, table, query)
        parquet = OUT / "parquet" / f"{table}.parquet"
        db.execute(f"COPY {quote_ident(table)} TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(parquet)])
        cols = [r[1] for r in operational.execute(f"PRAGMA table_info({quote_ident(source_table)})").fetchall()]
        inventory[table] = {"source_db": str(OPERATIONAL_DB.relative_to(ROOT)), "source_table": source_table,
                            "rows": rows, "source_columns": cols, "date_filter": "2010-01-01 onward; meets 1, 3, 4"}

    # These two separate bridges add no fields to the raw source tables.
    race_context = pd.read_sql_query("""
        SELECT r.id AS race_id,c.kra_meet_code AS meet_code,c.name_ko AS venue_name,
               r.race_date_local AS race_date,r.race_number,r.distance_m,r.grade,r.race_name,r.status
        FROM races r JOIN racecourses c ON c.id=r.racecourse_id
        WHERE c.kra_meet_code IN (1,3,4) AND r.race_date_local >= ?
        ORDER BY r.race_date_local,r.race_number,c.kra_meet_code
    """, operational, params=(START_DATE,))
    entry_context = pd.read_sql_query("""
        SELECT e.id AS race_entry_id,e.race_id,c.kra_meet_code AS meet_code,c.name_ko AS venue_name,
               r.race_date_local AS race_date,r.race_number,e.horse_number,h.kra_horse_id,h.name_ko AS horse_name
        FROM race_entries e JOIN races r ON r.id=e.race_id
        JOIN racecourses c ON c.id=r.racecourse_id JOIN horses h ON h.id=e.horse_id
        WHERE c.kra_meet_code IN (1,3,4) AND r.race_date_local >= ?
        ORDER BY r.race_date_local,r.race_number,e.horse_number
    """, operational, params=(START_DATE,))
    for frame in (race_context, entry_context):
        frame["venue_code"] = frame.meet_code.map(MEET_VENUE)
        frame["canonical_race_id"] = [
            f"RACE:{venue}:{str(day).replace('-', '')[:8]}:{int(no):02d}"
            for venue, day, no in zip(frame.venue_code, frame.race_date, frame.race_number)
        ]
    for name, frame in (("op_race_context", race_context), ("op_entry_context", entry_context)):
        db.register("_bridge", frame)
        db.execute(f"CREATE TABLE {name} AS SELECT * FROM _bridge")
        db.unregister("_bridge")
        db.execute(f"COPY {name} TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(OUT / "parquet" / f"{name}.parquet")])
        inventory[name] = {"source_db": str(OPERATIONAL_DB.relative_to(ROOT)), "source_table": "derived_join_bridge",
                           "rows": len(frame), "source_columns": list(frame.columns),
                           "date_filter": "2010-01-01 onward; meets 1, 3, 4; derived from current race/entry tables"}

    excluded_finish_rows = exclude_confirmed_errors(db, OUT, inventory)
    db.execute("CHECKPOINT")
    coverage = {
        "dataset_version": "2026-09-29-section-passing-raw-v1",
        "history_start_date": START_DATE,
        "included_meets": {"1": "SEOUL", "3": "BUSAN", "4": "YEONGCHEON"},
        "tables": inventory,
        "confirmed_api_anomaly_finish_rows_excluded": excluded_finish_rows,
        "latest_source_dates": {
            "spdb_finish_time": db.execute("SELECT max(race_date) FROM spdb_finish_time").fetchone()[0],
            "spdb_section_time": db.execute("SELECT max(race_date) FROM spdb_section_time").fetchone()[0],
            "op_race_context": db.execute("SELECT max(race_date) FROM op_race_context").fetchone()[0],
        },
        "row_grain_notes": [
            "spdb_section_time and op_race_section_times retain source rows at point/time granularity.",
            "op_race_passing_groups and op_race_passing_summaries are race-level; they are not expanded to runner rows.",
            "All raw source column names are preserved in separate source-prefixed tables.",
            "op_race_context and op_entry_context are separate bridges and do not alter raw tables.",
            "Confirmed API anomaly keys are excluded from the active finish-time snapshot; archived upstream research source rows are preserved.",
        ],
    }
    (OUT / "coverage.json").write_text(json.dumps(coverage, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    db.close()
    section.close()
    operational.close()
    print(json.dumps({"output": str(OUT.relative_to(ROOT)), "latest_source_dates": coverage["latest_source_dates"],
                      "table_rows": {k: v["rows"] for k, v in inventory.items()}},
                     ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
