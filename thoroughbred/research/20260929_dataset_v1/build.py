#!/usr/bin/env python3
"""Build a fresh 2010+ Thoroughbred research snapshot.

The previous unified DuckDB is a read-only materialized source for historical
rows because its original Seoul/Busan staging databases are no longer present.
The current operational SQLite and adjudicated section-point DB supply the
latest race cards and canonical section points. Nothing is written to sources.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
LEGACY = ROOT / "data/research/thoroughbred_unified_20260918/thoroughbred_unified.duckdb"
OPERATIONAL = ROOT / "data/horse_racing.sqlite3"
SECTION_POINTS = ROOT / "data/research/section_point_db_20260925/section_points_adjudicated.sqlite3"
OUT = ROOT / "thoroughbred/data/dataset_20260929_v1"
START_DATE = "2010-01-01"
MODEL_START = "2017-01-01"
LEGACY_END = "2026-09-13"
MEET_TO_VENUE = {1: ("SEOUL", "SEOUL"), 3: ("BUSAN", "YEONGNAM"), 4: ("YEONGCHEON", "YEONGNAM")}


def exclude_confirmed_error_races(db: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Remove confirmed copied API races before calculating any history features."""
    base = ROOT / "thoroughbred/research/20260929_calendar_api_v1"
    keys = set()
    for filename, expected in (("planless_positive_result_review.csv", 20),
                               ("result_only_nonfinish_anomaly_review.csv", 52)):
        with (base / filename).open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        current = {(int(r["meet"]), f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:]}",
                    int(r["race_no"])) for r in rows}
        if len(rows) != len(current) or len(current) != expected or keys & current:
            raise ValueError(f"Confirmed anomalous race key ledger changed: {filename}")
        keys |= current
    db.execute("CREATE TEMP TABLE _confirmed_error_keys(meet INTEGER, race_date DATE, race_no INTEGER)")
    db.executemany("INSERT INTO _confirmed_error_keys VALUES (?, ?, ?)", sorted(keys))
    db.execute("CREATE TEMP TABLE _confirmed_error_ids AS SELECT r.race_id FROM race r "
               "JOIN _confirmed_error_keys b ON r.canonical_meet=b.meet "
               "AND r.race_date=b.race_date AND r.race_no=b.race_no")
    counts = {}
    for table in ("entry_result", "section", "section_point", "weight_event", "equipment_event", "race"):
        counts[table] = db.execute(f"SELECT count(*) FROM {table} "
                                   "WHERE race_id IN (SELECT race_id FROM _confirmed_error_ids)").fetchone()[0]
        db.execute(f"DELETE FROM {table} WHERE race_id IN (SELECT race_id FROM _confirmed_error_ids)")
    db.execute("DROP TABLE _confirmed_error_ids")
    db.execute("DROP TABLE _confirmed_error_keys")
    return counts


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def race_id(venue: str, day: object, no: int) -> str:
    return f"RACE:{venue}:{str(day).replace('-', '')[:8]}:{int(no):02d}"


def read_sqlite(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    return con


def append_frame(db: duckdb.DuckDBPyConnection, table: str, frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    db.register("_append_frame", frame)
    try:
        db.execute(f"INSERT INTO {table} BY NAME SELECT * FROM _append_frame")
    finally:
        db.unregister("_append_frame")


def copy_legacy_tables(db: duckdb.DuckDBPyConnection) -> dict[str, int]:
    db.execute(f"ATTACH '{LEGACY.as_posix()}' AS legacy (READ_ONLY)")
    dates = {
        "race": "race_date", "entry_result": "race_date", "section": "race_date",
        "trial_entry": "trial_date", "training_event": "event_date",
        "medical_event": "event_date", "weight_event": "race_date",
        "equipment_event": "race_date", "identity_issue": "event_date",
        "unresolved_identity_ledger": "event_date",
    }
    counts: dict[str, int] = {}
    for table, date_col in dates.items():
        venue_filter = "venue_code IN ('SEOUL','BUSAN','YEONGCHEON')" if table in {
            "race", "entry_result", "section", "trial_entry"
        } else "TRUE"
        if table == "identity_issue":
            venue_filter = "venue_code IN ('SEOUL','BUSAN','YEONGCHEON')"
        if table == "unresolved_identity_ledger":
            venue_filter = "venue_code IN ('SEOUL','BUSAN','YEONGCHEON','YEONGNAM_UNRESOLVED') OR venue_code IS NULL"
        if table == "trial_entry":
            venue_filter = "venue_code IN ('SEOUL','BUSAN','YEONGCHEON') OR venue_resolution_status='unresolved_after_yeongcheon_split'"
        db.execute(f"""
            CREATE TABLE {table} AS
            SELECT * FROM legacy.main.{table}
            WHERE {date_col} >= DATE '{START_DATE}' AND ({venue_filter})
        """)
        counts[table] = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    db.execute("""
        CREATE TABLE venue_dimension AS
        SELECT * FROM legacy.main.venue_dimension
        WHERE venue_code IN ('SEOUL','BUSAN','YEONGCHEON')
    """)
    counts["venue_dimension"] = db.execute("SELECT count(*) FROM venue_dimension").fetchone()[0]
    db.execute("DETACH legacy")
    return counts


def refresh_current_cards(db: duckdb.DuckDBPyConnection) -> dict[str, int]:
    op = read_sqlite(OPERATIONAL)
    race_rows = pd.read_sql_query("""
        SELECT c.kra_meet_code meet, r.race_date_local race_date, r.race_number race_no,
               r.distance_m, r.grade, r.race_name, r.burden_type, r.track_condition,
               r.weather, r.track_moisture_percent, r.rating_condition
        FROM races r JOIN racecourses c ON c.id=r.racecourse_id
        WHERE c.kra_meet_code IN (1,3,4) AND r.status='completed'
          AND r.race_date_local > ?
          AND EXISTS (SELECT 1 FROM race_entries e JOIN race_results x
                      ON x.race_entry_id=e.id
                      WHERE e.race_id=r.id AND x.finish_time_ms>0)
        ORDER BY r.race_date_local,r.race_number
    """, op, params=(LEGACY_END,))

    races = []
    for row in race_rows.itertuples(index=False):
        venue, region = MEET_TO_VENUE[int(row.meet)]
        races.append({
            "race_id": race_id(venue, row.race_date, row.race_no),
            "venue_code": venue, "canonical_meet": int(row.meet), "region_code": region,
            "race_date": row.race_date, "race_no": int(row.race_no),
            "race_type": row.race_name, "race_class": row.grade,
            "distance_m": row.distance_m, "burden_type": row.burden_type,
            "track_raw": (str(row.track_condition or "") +
                          (f" ({row.track_moisture_percent:g}%)" if pd.notna(row.track_moisture_percent) else "")),
            "weather_raw": row.weather, "track_moisture_percent": row.track_moisture_percent,
            "rating_condition_raw": row.rating_condition, "label_scope": "official_race",
            "official_result_state": "confirmed", "rating_system": None,
            "surface_regime": "yeongcheon_initial_2026" if venue == "YEONGCHEON" else None,
            "mile_1600_era": None, "source_dataset": "operational_db_refresh_20260929",
            "source_path": "data/horse_racing.sqlite3",
        })
    race_frame = pd.DataFrame(races)
    if not race_frame.empty:
        append_frame(db, "race", race_frame)

    entry_rows = pd.read_sql_query("""
        SELECT c.kra_meet_code meet,r.race_date_local race_date,r.race_number race_no,
               e.id entry_id,e.horse_number chul_no,h.kra_horse_id hr_no,h.name_ko horse_name,
               h.origin_country origin_raw,h.sex sex_raw,
               CAST((julianday(r.race_date_local)-julianday(h.birth_date))/365.25 AS INTEGER) age_raw,
               e.rating rating_raw,j.kra_jockey_id jockey_no,t.kra_trainer_id trainer_no,
               o.kra_owner_id owner_no,j.name_ko jockey_name,t.name_ko trainer_name,
               o.name_ko owner_name,e.carried_weight_kg burden_weight_kg,
               e.body_weight_kg horse_weight_kg,e.body_weight_change_kg horse_weight_delta_kg,
               e.scratched,x.finish_position,x.finish_time_ms,x.margin_text diff_raw,
               x.disqualified,x.rank_remark
        FROM races r JOIN racecourses c ON c.id=r.racecourse_id
        JOIN race_entries e ON e.race_id=r.id JOIN horses h ON h.id=e.horse_id
        LEFT JOIN jockeys j ON j.id=e.jockey_id LEFT JOIN trainers t ON t.id=e.trainer_id
        LEFT JOIN owners o ON o.id=e.owner_id LEFT JOIN race_results x ON x.race_entry_id=e.id
        WHERE c.kra_meet_code IN (1,3,4) AND r.status='completed'
          AND r.race_date_local > ?
          AND EXISTS (SELECT 1 FROM race_entries e2 JOIN race_results x2
                      ON x2.race_entry_id=e2.id
                      WHERE e2.race_id=r.id AND x2.finish_time_ms>0)
        ORDER BY r.race_date_local,r.race_number,e.horse_number
    """, op, params=(LEGACY_END,))

    entries = []
    for row in entry_rows.itertuples(index=False):
        venue, _ = MEET_TO_VENUE[int(row.meet)]
        pos = int(row.finish_position) if pd.notna(row.finish_position) else None
        weight_raw = None
        if pd.notna(row.horse_weight_kg):
            weight_delta = 0 if pd.isna(row.horse_weight_delta_kg) else int(row.horse_weight_delta_kg)
            weight_raw = f"{int(row.horse_weight_kg)}({weight_delta})"
        if bool(row.scratched):
            status = "scratched"
        elif bool(row.disqualified):
            status = "disqualified"
        elif pos is not None and pos < 90 and pd.notna(row.finish_time_ms) and row.finish_time_ms > 0:
            status = "finished"
        elif row.rank_remark:
            status = "special_result"
        else:
            status = "did_not_finish"
        rank_label = status == "finished"
        name = str(row.horse_name or "").strip()
        entries.append({
            "race_id": race_id(venue, row.race_date, row.race_no), "venue_code": venue,
            "canonical_meet": int(row.meet), "race_date": row.race_date,
            "race_no": int(row.race_no), "chul_no": row.chul_no,
            "hr_no": str(row.hr_no).zfill(7) if row.hr_no else None,
            "horse_name_raw": name, "horse_name_normalized": "".join(name.split()),
            "origin_raw": row.origin_raw, "sex_raw": row.sex_raw,
            "age_raw": row.age_raw, "rating_raw": row.rating_raw,
            "jockey_no": row.jockey_no, "trainer_no": row.trainer_no,
            "owner_no": row.owner_no, "owner_no_raw_json": str(row.owner_no) if row.owner_no else None,
            "jockey_name": row.jockey_name, "trainer_name": row.trainer_name,
            "owner_name": row.owner_name, "burden_weight_kg": row.burden_weight_kg,
            "horse_weight_raw": weight_raw,
            "horse_weight_kg": row.horse_weight_kg,
            "horse_weight_delta_kg": row.horse_weight_delta_kg,
            "finish_raw": str(pos) if pos is not None else row.rank_remark,
            "finish_order": pos if rank_label else None, "result_status": status,
            "race_time_s": float(row.finish_time_ms) / 1000 if pd.notna(row.finish_time_ms) else None,
            "win_odds": None, "place_odds": None, "diff_raw": row.diff_raw,
            "is_dead_heat": False, "source_prior_races": None, "source_prior_wins": None,
            "source_training_28d": None, "source_training_seconds_28d": None,
            "source_start_training_28d": None, "source_confirmed_medical_28d": None,
            "source_availability_status": "operational_refresh",
            "training_28d_status": None, "start_training_28d_status": None,
            "medical_28d_status": None, "current_weight_availability": "retrospective_operational",
            "label_scope": "official_race", "official_result_state": "confirmed",
            "is_model_target": str(row.race_date) >= MODEL_START,
            "is_rank_label": rank_label, "source_dataset": "operational_db_refresh_20260929",
            "source_path": "data/horse_racing.sqlite3", "source_row": int(row.entry_id),
        })
    entry_frame = pd.DataFrame(entries)
    if not entry_frame.empty:
        append_frame(db, "entry_result", entry_frame)
    op.close()
    return {"race": len(races), "entry_result": len(entries)}


def build_section_points(db: duckdb.DuckDBPyConnection) -> int:
    src = read_sqlite(SECTION_POINTS)
    rows = pd.read_sql_query("""
        SELECT meet_code,race_date,race_number,distance_m,kra_horse_id,horse_number,
               race_entry_id,point_code,time_kind,meters_from_start,meters_before_finish,
               elapsed_time_ms,position,position_raw,position_quality_status,position_source,
               source_position,source_name,source_field,classification
        FROM common_point
        WHERE meet_code IN (1,3,4) AND race_date>=?
        ORDER BY meet_code,race_date,race_number,horse_number,point_code,time_kind
    """, src, params=(START_DATE,))
    src.close()
    rows["venue_code"] = rows["meet_code"].map({1: "SEOUL", 3: "BUSAN", 4: "YEONGCHEON"})
    rows["race_id"] = [race_id(v, d, n) for v, d, n in zip(rows.venue_code, rows.race_date, rows.race_number)]
    rows.rename(columns={"meet_code": "canonical_meet", "elapsed_time_ms": "value_ms",
                         "race_number": "race_no", "kra_horse_id": "hr_no"}, inplace=True)
    db.register("_section_points", rows)
    db.execute("CREATE TABLE section_point AS SELECT * FROM _section_points")
    db.unregister("_section_points")
    return len(rows)


def build_history_layers(db: duckdb.DuckDBPyConnection) -> None:
    duplicate = db.execute("""
        SELECT count(*) FROM (
          SELECT hr_no,race_date FROM entry_result
          WHERE hr_no IS NOT NULL AND official_result_state='confirmed'
          GROUP BY hr_no,race_date HAVING count(*)>1
        )
    """).fetchone()[0]
    if duplicate:
        raise RuntimeError(f"Confirmed same-horse same-day entries need identity review: {duplicate}")

    db.execute(f"""
      CREATE TABLE performance_history_features AS
      WITH known AS (
        SELECT race_id,venue_code,race_date,race_no,hr_no,result_status,finish_order,
               is_rank_label,
               count(*) OVER w_prior AS prior_confirmed_starts,
               count(*) FILTER(WHERE is_rank_label) OVER w_prior AS prior_ranked_starts,
               count(*) FILTER(WHERE is_rank_label AND finish_order=1) OVER w_prior AS prior_wins,
               count(*) FILTER(WHERE is_rank_label AND finish_order<=3) OVER w_prior AS prior_top3,
               max(race_date) OVER w_prior AS previous_race_date,
               last_value(venue_code) OVER w_prior AS previous_venue,
               avg(finish_order) FILTER(WHERE is_rank_label) OVER w_last1 AS last1_mean_finish,
               avg(finish_order) FILTER(WHERE is_rank_label) OVER w_last3 AS last3_mean_finish,
               avg(finish_order) FILTER(WHERE is_rank_label) OVER w_last5 AS last5_mean_finish,
               count(*) FILTER(WHERE is_rank_label) OVER w_last5 AS last5_ranked_starts,
               count(*) FILTER(WHERE is_rank_label AND finish_order=1) OVER w_last5 AS last5_wins,
               count(*) FILTER(WHERE is_rank_label AND finish_order<=3) OVER w_last5 AS last5_top3,
               avg(finish_order) FILTER(WHERE is_rank_label) OVER w_older AS older6plus_mean_finish,
               count(*) FILTER(WHERE is_rank_label) OVER w_older AS older6plus_ranked_starts,
               count(*) FILTER(WHERE is_rank_label AND finish_order=1) OVER w_older AS older6plus_wins,
               count(*) FILTER(WHERE is_rank_label AND finish_order<=3) OVER w_older AS older6plus_top3
        FROM entry_result
        WHERE hr_no IS NOT NULL AND official_result_state='confirmed'
        WINDOW
          w_prior AS (PARTITION BY hr_no ORDER BY race_date,race_no,venue_code
                      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),
          w_last1 AS (PARTITION BY hr_no ORDER BY race_date,race_no,venue_code
                      ROWS BETWEEN 1 PRECEDING AND 1 PRECEDING),
          w_last3 AS (PARTITION BY hr_no ORDER BY race_date,race_no,venue_code
                      ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING),
          w_last5 AS (PARTITION BY hr_no ORDER BY race_date,race_no,venue_code
                      ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
          w_older AS (PARTITION BY hr_no ORDER BY race_date,race_no,venue_code
                      ROWS BETWEEN UNBOUNDED PRECEDING AND 6 PRECEDING)
      )
      SELECT race_id,venue_code,race_date,race_no,hr_no,
             coalesce(prior_confirmed_starts,0) prior_confirmed_starts,
             coalesce(prior_ranked_starts,0) prior_ranked_starts,
             prior_wins,prior_top3,previous_race_date,
             date_diff('day',previous_race_date,race_date) days_since_previous_start,
             previous_venue,
             last1_mean_finish,last3_mean_finish,last5_mean_finish,
             last5_ranked_starts,last5_wins,last5_top3,
             last5_wins::DOUBLE/nullif(last5_ranked_starts,0) last5_win_rate,
             last5_top3::DOUBLE/nullif(last5_ranked_starts,0) last5_top3_rate,
             older6plus_mean_finish,older6plus_ranked_starts,older6plus_wins,older6plus_top3,
             older6plus_wins::DOUBLE/nullif(older6plus_ranked_starts,0) older6plus_win_rate,
             older6plus_top3::DOUBLE/nullif(older6plus_ranked_starts,0) older6plus_top3_rate,
             'strictly_prior_confirmed_starts; last five and older six-plus separated' history_contract
      FROM known WHERE race_date>=DATE '{MODEL_START}'
    """)
    db.execute("""
      CREATE TABLE race_label_2017_onward AS
      SELECT race_id,venue_code,race_date,race_no,hr_no,result_status,
             finish_order,race_time_s,is_dead_heat,official_result_state
      FROM entry_result
      WHERE race_date>=DATE '2017-01-01' AND is_model_target
    """)
    db.execute("""
      CREATE TABLE prediction_frame_2017_onward AS
      SELECT r.race_id,r.venue_code,r.region_code,r.race_date,r.race_no,r.distance_m,
             r.race_type,r.race_class,r.burden_type,r.rating_condition_raw,
             e.chul_no,e.hr_no,e.horse_name_normalized,e.origin_raw,e.sex_raw,e.age_raw,
             e.rating_raw,e.jockey_no,e.trainer_no,e.owner_no,e.burden_weight_kg,
             h.prior_confirmed_starts,h.prior_ranked_starts,h.prior_wins,h.prior_top3,
             h.previous_race_date,h.days_since_previous_start,h.previous_venue,
             h.last1_mean_finish,h.last3_mean_finish,h.last5_mean_finish,
             h.last5_ranked_starts,h.last5_win_rate,h.last5_top3_rate,
             h.older6plus_mean_finish,h.older6plus_ranked_starts,
             h.older6plus_win_rate,h.older6plus_top3_rate,
             e.result_status target_result_status,e.finish_order target_finish_order,
             e.race_time_s target_race_time_s,e.is_rank_label target_is_rank_label,
             e.is_dead_heat target_is_dead_heat,
             'Post-race result columns are labels only; same-day weight, track, weather and odds are excluded by default.'
               feature_availability_note
      FROM entry_result e JOIN race r ON r.race_id=e.race_id
      LEFT JOIN performance_history_features h
        ON h.race_id=e.race_id AND h.venue_code=e.venue_code AND h.race_date=e.race_date
       AND h.race_no=e.race_no AND h.hr_no=e.hr_no
      WHERE e.race_date>=DATE '2017-01-01' AND e.is_model_target
    """)


def write_outputs(db: duckdb.DuckDBPyConnection, source_counts: dict[str, object]) -> None:
    db.execute("CREATE INDEX idx_entry_horse_date ON entry_result(hr_no,race_date)")
    db.execute("CREATE INDEX idx_section_horse_date ON section_point(hr_no,race_date)")
    db.execute("ANALYZE")
    summary = {
        "dataset_version": "2026-09-29-v1",
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "history_start_date": START_DATE,
        "model_target_start_date": MODEL_START,
        "latest_completed_race_date": db.execute("SELECT max(race_date) FROM race").fetchone()[0].isoformat(),
        "source_counts": source_counts,
        "tables": {},
    }
    tables = ["venue_dimension","race","entry_result","section","section_point","trial_entry",
              "training_event","medical_event","weight_event","equipment_event","identity_issue",
              "unresolved_identity_ledger","performance_history_features","race_label_2017_onward",
              "prediction_frame_2017_onward"]
    for table in tables:
        count = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        summary["tables"][table] = {"rows": count}
        parquet = OUT / "parquet" / f"{table}.parquet"
        db.execute(f"COPY {table} TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(parquet)])

    for venue in ("SEOUL","BUSAN","YEONGCHEON"):
        summary["tables"]["race"][venue] = db.execute(
            "SELECT count(*),min(race_date),max(race_date) FROM race WHERE venue_code=?", [venue]
        ).fetchone()
        summary["tables"]["entry_result"][venue] = db.execute(
            "SELECT count(*),count(distinct hr_no),min(race_date),max(race_date) FROM entry_result WHERE venue_code=?", [venue]
        ).fetchone()
        summary["tables"]["section_point"][venue] = db.execute(
            "SELECT count(*),min(race_date),max(race_date) FROM section_point WHERE venue_code=?", [venue]
        ).fetchone()
    (OUT / "validation.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")

    sources = {}
    for label,path in (("historical_unified_snapshot",LEGACY),("operational_sqlite",OPERATIONAL),
                       ("section_points_adjudicated",SECTION_POINTS)):
        sources[label] = {"path":str(path.relative_to(ROOT)),"bytes":path.stat().st_size,"sha256":sha256(path)}
    artifact_paths = [p for p in OUT.rglob("*") if p.is_file() and p.name!="manifest.json"]
    manifest = {
        "dataset_version":"2026-09-29-v1",
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "history_range":"2010-01-01 through latest completed source race",
        "model_target_range":"2017-01-01 through latest completed source race",
        "read_only_sources":sources,
        "artifacts":{str(p.relative_to(ROOT)):{"bytes":p.stat().st_size,"sha256":sha256(p)} for p in artifact_paths},
        "limitations":[
            "Historical input is copied from the 2026-09-18 unified DuckDB because its original staging SQLite files are absent.",
            "Operational refresh supplies completed race and entry rows after 2026-09-13 through the latest available card.",
            "Adjudicated section points supply canonical S1F/G3F/G1F rows; they do not include all raw section source variants.",
            "Training, medical, weight, equipment and trial event tables retain their source-specific latest dates from the historical snapshot.",
            "Last-five and older-six-plus finish summaries are candidate features and require temporal model evaluation before promotion."
        ]
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def main() -> None:
    for path in (LEGACY,OPERATIONAL,SECTION_POINTS):
        if not path.is_file():
            raise FileNotFoundError(path)
    if OUT.exists():
        raise FileExistsError(f"Refusing to overwrite existing dataset: {OUT}")
    OUT.mkdir(parents=True)
    (OUT / "parquet").mkdir()
    db = duckdb.connect(str(OUT / "thoroughbred.duckdb"))
    db.execute("SET threads=4")
    db.execute("SET memory_limit='4GB'")
    counts = copy_legacy_tables(db)
    counts["operational_refresh"] = refresh_current_cards(db)
    counts["section_point_adjudicated"] = build_section_points(db)
    counts["confirmed_api_anomaly_rows_excluded"] = exclude_confirmed_error_races(db)
    build_history_layers(db)
    db.execute("CHECKPOINT")
    quick = db.execute("PRAGMA database_size").fetchall()
    write_outputs(db,counts)
    db.close()
    print(json.dumps({"database":str((OUT/'thoroughbred.duckdb').relative_to(ROOT)),
                      "source_counts":counts,"database_size":quick},ensure_ascii=False,default=str))


if __name__ == "__main__":
    main()
