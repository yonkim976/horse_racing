"""Build one canonical Seoul/Busan/Yeongcheon thoroughbred research dataset.

The source databases are opened read-only.  The output is a new DuckDB plus
Parquet tables.  Race labels start in 2006; older Seoul and late-2005 Busan
rows are retained as warm-up history.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import duckdb
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SEOUL_DB = ROOT / "data/research/seoul_backfill_20260915_v1/history.sqlite3"
SEOUL_TRIAL_DB = ROOT / "data/research/seoul_running_trials_20260915_v1/trials.sqlite3"
BUSAN_DB = ROOT / "data/research/busan_complete_db_20260916/busan_complete.sqlite3"
OPERATING_DB = ROOT / "data/horse_racing.sqlite3"
BUSAN_API_RAW = ROOT / "data/research/busan_history_20260915/raw"

VENUE_NAMES = {"SEOUL": "서울", "BUSAN": "부산경남", "YEONGCHEON": "영천"}
VENUE_MEETS = {"SEOUL": 1, "BUSAN": 3, "YEONGCHEON": 4}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


PREFIX = re.compile(r"^\[(?:서울|부산경남|부경|부|영천|제주|제)\]")


def normalized_name(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = PREFIX.sub("", str(value).strip())
    return re.sub(r"\s+", "", text)


def race_id(venue: str, date_value: object, number: object) -> str:
    day = str(date_value).replace("-", "")[:8]
    return f"RACE:{venue}:{day}:{int(number):02d}"


def trial_id(venue: str, date_value: object, number: object) -> str:
    day = str(date_value).replace("-", "")[:8]
    return f"TRIAL:{venue}:{day}:{int(number):02d}"


def sqlite_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    return con


def append_frame(db: duckdb.DuckDBPyConnection, table: str, frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    db.register("_chunk", frame)
    try:
        db.execute(f"INSERT INTO {table} BY NAME SELECT * FROM _chunk")
    finally:
        db.unregister("_chunk")


def copy_query(
    source: sqlite3.Connection,
    query: str,
    db: duckdb.DuckDBPyConnection,
    table: str,
    transform: Callable[[pd.DataFrame], pd.DataFrame],
    params: tuple = (),
    chunksize: int = 100_000,
) -> int:
    count = 0
    for frame in pd.read_sql_query(query, source, params=params, chunksize=chunksize):
        frame = transform(frame)
        append_frame(db, table, frame)
        count += len(frame)
    return count


def api_items(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = payload.get("response", {}).get("body", {})
    wrapped = body.get("items") or {}
    rows = wrapped.get("item") if isinstance(wrapped, dict) else []
    if isinstance(rows, dict):
        return [rows]
    return rows or []


def load_busan_extras() -> tuple[dict, dict]:
    entries: dict[tuple[str, int, str], dict] = {}
    races: dict[tuple[str, int], dict] = {}
    for path in sorted(BUSAN_API_RAW.glob("*/page_*.json")):
        for row in api_items(path):
            day = str(row.get("rcDate") or "")
            number = int(row.get("rcNo") or 0)
            horse = str(row.get("hrNo") or "").zfill(7)
            entries[(day, number, horse)] = row
            races.setdefault((day, number), row)
    return entries, races


def create_schema(db: duckdb.DuckDBPyConnection) -> None:
    db.execute("""
      CREATE TABLE venue_dimension(
        venue_code VARCHAR PRIMARY KEY, canonical_meet INTEGER, region_code VARCHAR,
        name_ko VARCHAR, role VARCHAR, note VARCHAR);
      CREATE TABLE race(
        race_id VARCHAR PRIMARY KEY, venue_code VARCHAR, canonical_meet INTEGER,
        region_code VARCHAR, race_date DATE, race_no INTEGER, race_type VARCHAR,
        race_class VARCHAR, distance_m INTEGER, burden_type VARCHAR,
        track_raw VARCHAR, weather_raw VARCHAR, track_moisture_percent DOUBLE,
        rating_condition_raw VARCHAR, label_scope VARCHAR,
        official_result_state VARCHAR, rating_system VARCHAR,
        surface_regime VARCHAR, mile_1600_era VARCHAR,
        source_dataset VARCHAR, source_path VARCHAR);
      CREATE TABLE entry_result(
        race_id VARCHAR, venue_code VARCHAR, canonical_meet INTEGER, race_date DATE,
        race_no INTEGER, chul_no INTEGER, hr_no VARCHAR, horse_name_raw VARCHAR,
        horse_name_normalized VARCHAR, origin_raw VARCHAR, sex_raw VARCHAR,
        age_raw INTEGER, rating_raw DOUBLE, jockey_no VARCHAR, trainer_no VARCHAR,
        owner_no VARCHAR, owner_no_raw_json VARCHAR, jockey_name VARCHAR,
        trainer_name VARCHAR, owner_name VARCHAR, burden_weight_kg DOUBLE,
        horse_weight_raw VARCHAR, horse_weight_kg INTEGER,
        horse_weight_delta_kg INTEGER, finish_raw VARCHAR, finish_order INTEGER,
        result_status VARCHAR, race_time_s DOUBLE, win_odds DOUBLE,
        place_odds DOUBLE, diff_raw VARCHAR, is_dead_heat BOOLEAN,
        source_prior_races INTEGER, source_prior_wins INTEGER,
        source_training_28d INTEGER, source_training_seconds_28d BIGINT,
        source_start_training_28d INTEGER, source_confirmed_medical_28d INTEGER,
        source_availability_status VARCHAR, training_28d_status VARCHAR,
        start_training_28d_status VARCHAR, medical_28d_status VARCHAR,
        current_weight_availability VARCHAR, label_scope VARCHAR,
        official_result_state VARCHAR, is_model_target BOOLEAN,
        is_rank_label BOOLEAN, source_dataset VARCHAR, source_path VARCHAR,
        source_row INTEGER, PRIMARY KEY(race_id, hr_no));
      CREATE TABLE section(
        race_id VARCHAR, venue_code VARCHAR, canonical_meet INTEGER, race_date DATE,
        race_no INTEGER, hr_no VARCHAR, source_field VARCHAR, section_code VARCHAR,
        value_ms BIGINT, unit VARCHAR, time_basis VARCHAR,
        canonical_closing_ms BIGINT, position_raw VARCHAR,
        semantic_status VARCHAR, source_dataset VARCHAR, source_path VARCHAR,
        source_row INTEGER);
      CREATE TABLE trial_entry(
        trial_event_id VARCHAR, venue_code VARCHAR, canonical_meet INTEGER,
        region_code VARCHAR, source_meet INTEGER, venue_resolution_status VARCHAR,
        trial_date DATE, trial_no INTEGER, participant_no INTEGER,
        trial_round INTEGER, trial_kind VARCHAR, distance_m INTEGER,
        weather_raw VARCHAR, track_raw VARCHAR, track_moisture_percent DOUBLE,
        hr_no VARCHAR, horse_name_raw VARCHAR, horse_name_normalized VARCHAR,
        origin_raw VARCHAR, sex_raw VARCHAR, age_raw INTEGER,
        jockey_no VARCHAR, jockey_name_raw VARCHAR, trainer_no VARCHAR,
        trainer_name_raw VARCHAR, finish_raw VARCHAR, finish_position INTEGER,
        result_state VARCHAR, judgement_raw VARCHAR, failure_reason_raw VARCHAR,
        inspection_reason_raw VARCHAR, body_weight_kg INTEGER,
        finish_time_ms BIGINT, section_json VARCHAR, horse_link_status VARCHAR,
        person_link_status VARCHAR, availability_status VARCHAR,
        source_dataset VARCHAR, source_path VARCHAR,
        PRIMARY KEY(trial_event_id, participant_no));
      CREATE TABLE training_event(
        training_event_id VARCHAR PRIMARY KEY, training_venue_code VARCHAR,
        source_meet INTEGER, source_type VARCHAR, event_date DATE, hr_no VARCHAR,
        horse_name VARCHAR, duration_seconds INTEGER, start_time_raw VARCHAR,
        end_time_raw VARCHAR, intensity_1 INTEGER, intensity_2 INTEGER,
        trainer_name_raw VARCHAR, part_raw VARCHAR, rider_no_raw VARCHAR,
        remark_raw VARCHAR, availability_status VARCHAR,
        source_dataset VARCHAR, source_path VARCHAR, source_row INTEGER);
      CREATE TABLE medical_event(
        medical_event_id VARCHAR PRIMARY KEY, source_venue_code VARCHAR,
        source_meet INTEGER, source_type VARCHAR, event_date DATE, hr_no VARCHAR,
        horse_name VARCHAR, stable_no_raw VARCHAR, facility_raw VARCHAR,
        diagnosis_1_raw VARCHAR, diagnosis_2_raw VARCHAR, has_content BOOLEAN,
        link_status VARCHAR, candidate_hr_nos_json VARCHAR,
        availability_status VARCHAR, source_dataset VARCHAR,
        source_path VARCHAR, source_row INTEGER);
      CREATE TABLE weight_event(
        weight_event_id VARCHAR PRIMARY KEY, race_id VARCHAR,
        venue_code VARCHAR, canonical_meet INTEGER, race_date DATE,
        race_no INTEGER, chul_no INTEGER, hr_no VARCHAR, horse_name_raw VARCHAR,
        horse_name_normalized VARCHAR, weight_kg INTEGER, weight_delta_kg INTEGER,
        link_status VARCHAR, availability_status VARCHAR,
        source_dataset VARCHAR, source_path VARCHAR, source_row INTEGER);
      CREATE TABLE equipment_event(
        equipment_event_id VARCHAR PRIMARY KEY, race_id VARCHAR,
        venue_code VARCHAR, canonical_meet INTEGER, race_date DATE,
        race_no INTEGER, chul_no INTEGER, hr_no VARCHAR, horse_name_raw VARCHAR,
        horse_name_normalized VARCHAR, detail_raw VARCHAR,
        bleeding_count INTEGER, bleeding_date_raw VARCHAR, illness_note VARCHAR,
        link_status VARCHAR, availability_status VARCHAR,
        source_dataset VARCHAR, source_path VARCHAR, source_row INTEGER);
      CREATE TABLE identity_issue(
        issue_type VARCHAR, venue_code VARCHAR, event_date DATE,
        event_no INTEGER, participant_no INTEGER, source_value VARCHAR,
        candidate_value VARCHAR, status VARCHAR, evidence VARCHAR);
    """)
    db.executemany("INSERT INTO venue_dimension VALUES(?,?,?,?,?,?)", [
        ("SEOUL", 1, "SEOUL", "서울", "race_and_training_venue",
         "Official meet=1; history begins 2000, training warm-up 1998."),
        ("BUSAN", 3, "YEONGNAM", "부산경남", "race_and_training_venue",
         "Official race meet=3; Yeongcheon Text rows are excluded by actual venue."),
        ("YEONGCHEON", 4, "YEONGNAM", "영천", "race_venue",
         "Official race meet=4; first confirmed meeting 2026-09-13; cold start."),
    ])


def load_races(
    db: duckdb.DuckDBPyConnection,
    seoul: sqlite3.Connection,
    busan: sqlite3.Connection,
    operating: sqlite3.Connection,
    busan_race_extra: dict,
) -> dict:
    counts = {}

    def seoul_transform(frame: pd.DataFrame) -> pd.DataFrame:
        frame["race_id"] = [race_id("SEOUL", d, n) for d, n in zip(frame.race_date, frame.race_no)]
        frame["venue_code"] = "SEOUL"
        frame["canonical_meet"] = 1
        frame["region_code"] = "SEOUL"
        frame["track_moisture_percent"] = frame.track_raw.str.extract(r"\((\d+(?:\.\d+)?)%\)")[0]
        frame["source_dataset"] = "seoul_backfill_20260915_v1"
        return frame

    counts["race_seoul"] = copy_query(seoul, """
      SELECT race_date,race_no,race_type,race_class,distance_m,burden_type,
        track_raw,weather_raw,rating_condition_raw,label_scope,official_result_state,
        rating_system,surface_regime,mile_1600_era,source_path
      FROM race ORDER BY race_date,race_no""", db, "race", seoul_transform)

    def busan_transform(frame: pd.DataFrame) -> pd.DataFrame:
        frame["race_id"] = [race_id("BUSAN", d, n) for d, n in zip(frame.race_date, frame.race_no)]
        frame["venue_code"] = "BUSAN"
        frame["canonical_meet"] = 3
        frame["region_code"] = "YEONGNAM"
        frame["track_moisture_percent"] = frame.track_raw.str.extract(r"\((\d+(?:\.\d+)?)%\)")[0]
        frame["rating_condition_raw"] = [
            (busan_race_extra.get((str(d).replace("-", ""), int(n))) or {}).get("prizeCond")
            for d, n in zip(frame.race_date, frame.race_no)]
        frame["rating_system"] = None
        frame["surface_regime"] = None
        frame["mile_1600_era"] = None
        frame["source_dataset"] = "busan_complete_db_20260916"
        return frame

    counts["race_busan"] = copy_query(busan, """
      WITH state AS (
        SELECT meet,race_date,race_no,
          CASE WHEN max(CASE WHEN result_status='finished' AND race_time_s>0 THEN 1 ELSE 0 END)=1
               THEN 'confirmed'
               WHEN max(CASE WHEN result_status='void' THEN 1 ELSE 0 END)=1 THEN 'void'
               ELSE 'special_only_unresolved' END official_result_state
        FROM result GROUP BY meet,race_date,race_no)
      SELECT r.race_date,r.race_no,r.race_type,r.race_class,r.distance_m,
        r.burden_type,r.track_raw,r.weather_raw,r.label_scope,
        s.official_result_state,r.source_path
      FROM race r JOIN state s USING(meet,race_date,race_no)
      ORDER BY r.race_date,r.race_no""", db, "race", busan_transform)

    def yeongcheon_transform(frame: pd.DataFrame) -> pd.DataFrame:
        frame["race_id"] = [race_id("YEONGCHEON", d, n) for d, n in zip(frame.race_date, frame.race_no)]
        frame["venue_code"] = "YEONGCHEON"
        frame["canonical_meet"] = 4
        frame["region_code"] = "YEONGNAM"
        frame["race_type"] = frame.pop("race_name")
        frame["race_class"] = frame.pop("grade")
        frame["track_raw"] = frame.track_condition.fillna("") + " (" + frame.track_moisture_percent.fillna(0).astype(str) + "%)"
        frame["weather_raw"] = frame.pop("weather")
        frame["rating_condition_raw"] = frame.pop("rating_condition")
        frame["label_scope"] = "official_race"
        frame["official_result_state"] = "confirmed"
        frame["rating_system"] = "rating"
        frame["surface_regime"] = "yeongcheon_initial_2026"
        frame["mile_1600_era"] = None
        frame["source_dataset"] = "operating_db_meet4_confirmed"
        frame["source_path"] = "data/horse_racing.sqlite3"
        return frame.drop(columns=["track_condition"])

    counts["race_yeongcheon"] = copy_query(operating, """
      SELECT r.race_date_local race_date,r.race_number race_no,r.race_name,
        r.grade,r.distance_m,r.burden_type,r.track_condition,r.weather,
        r.track_moisture_percent,r.rating_condition
      FROM races r JOIN racecourses c ON c.id=r.racecourse_id
      WHERE c.kra_meet_code=4 AND r.status='completed'
        AND EXISTS(SELECT 1 FROM race_entries e JOIN race_results x
          ON x.race_entry_id=e.id WHERE e.race_id=r.id AND x.finish_time_ms>0)
      ORDER BY r.race_date_local,r.race_number""", db, "race", yeongcheon_transform)
    return counts


def load_entries(
    db: duckdb.DuckDBPyConnection,
    seoul: sqlite3.Connection,
    busan: sqlite3.Connection,
    operating: sqlite3.Connection,
    busan_entry_extra: dict,
) -> dict:
    counts = {}

    def common(frame: pd.DataFrame, venue: str, dataset: str) -> pd.DataFrame:
        frame["race_id"] = [race_id(venue, d, n) for d, n in zip(frame.race_date, frame.race_no)]
        frame["venue_code"] = venue
        frame["canonical_meet"] = VENUE_MEETS[venue]
        frame["horse_name_raw"] = frame.pop("horse_name")
        frame["horse_name_normalized"] = frame.horse_name_raw.map(normalized_name)
        frame["is_model_target"] = (
            (pd.to_datetime(frame.race_date) >= pd.Timestamp("2006-01-01")) &
            (frame.official_result_state == "confirmed"))
        frame["is_rank_label"] = (
            (frame.result_status == "finished") & frame.finish_order.notna() &
            (frame.race_time_s.fillna(0) > 0))
        frame["source_dataset"] = dataset
        return frame

    def seoul_transform(frame: pd.DataFrame) -> pd.DataFrame:
        frame["current_weight_availability"] = "retrospective_result_api"
        return common(frame, "SEOUL", "seoul_backfill_20260915_v1")

    counts["entry_seoul"] = copy_query(seoul, """
      SELECT e.race_date,e.race_no,e.chul_no,e.hr_no,e.horse_name,
        e.horse_origin_raw origin_raw,e.horse_sex_raw sex_raw,e.horse_age_raw age_raw,
        e.rating_raw,e.jockey_no,e.trainer_no,e.owner_no,e.owner_no_raw_json,
        e.jockey_name,e.trainer_name,e.owner_name,e.burden_weight_kg,
        e.horse_weight_raw,e.horse_weight_kg,e.horse_weight_delta_kg,
        x.finish_raw,x.finish_order,x.result_status,x.race_time_s,x.win_odds,
        x.place_odds,x.diff_raw,x.is_dead_heat,
        q.prior_races source_prior_races,q.prior_wins source_prior_wins,
        q.prior_training_28d source_training_28d,
        q.prior_training_seconds_28d source_training_seconds_28d,
        q.prior_start_training_28d source_start_training_28d,
        q.prior_confirmed_medical_28d source_confirmed_medical_28d,
        q.availability_status source_availability_status,q.training_28d_status,
        q.start_training_28d_status,q.medical_28d_status,r.label_scope,
        r.official_result_state,e.source_path,e.source_row
      FROM entry e JOIN result x USING(meet,race_date,race_no,hr_no)
      JOIN race r USING(meet,race_date,race_no)
      LEFT JOIN research_entry q USING(meet,race_date,race_no,hr_no)
      ORDER BY e.race_date,e.race_no,e.chul_no""", db, "entry_result", seoul_transform)

    def busan_transform(frame: pd.DataFrame) -> pd.DataFrame:
        extras = [busan_entry_extra.get((str(d).replace("-", ""), int(n), str(h).zfill(7)), {})
                  for d, n, h in zip(frame.race_date, frame.race_no, frame.hr_no)]
        frame["origin_raw"] = [row.get("name") for row in extras]
        frame["sex_raw"] = [row.get("sex") for row in extras]
        frame["age_raw"] = [row.get("age") for row in extras]
        frame["rating_raw"] = [row.get("rating") for row in extras]
        frame["training_28d_status"] = None
        frame["start_training_28d_status"] = None
        frame["medical_28d_status"] = None
        frame["current_weight_availability"] = "retrospective_result_api"
        return common(frame, "BUSAN", "busan_complete_db_20260916")

    counts["entry_busan"] = copy_query(busan, """
      WITH state AS (
        SELECT meet,race_date,race_no,
          CASE WHEN max(CASE WHEN result_status='finished' AND race_time_s>0 THEN 1 ELSE 0 END)=1
               THEN 'confirmed'
               WHEN max(CASE WHEN result_status='void' THEN 1 ELSE 0 END)=1 THEN 'void'
               ELSE 'special_only_unresolved' END official_result_state
        FROM result GROUP BY meet,race_date,race_no)
      SELECT e.race_date,e.race_no,e.chul_no,e.hr_no,e.horse_name,
        e.jockey_no,e.trainer_no,e.owner_no,e.owner_no_raw_json,e.jockey_name,
        e.trainer_name,e.owner_name,e.burden_weight_kg,e.horse_weight_raw,
        e.horse_weight_kg,e.horse_weight_delta_kg,x.finish_raw,x.finish_order,
        x.result_status,x.race_time_s,x.win_odds,x.place_odds,x.diff_raw,
        0 is_dead_heat,q.prior_races source_prior_races,q.prior_wins source_prior_wins,
        q.prior_training_28d source_training_28d,
        q.prior_training_seconds_28d source_training_seconds_28d,
        q.prior_start_training_28d source_start_training_28d,
        q.prior_confirmed_medical_28d source_confirmed_medical_28d,
        q.availability_status source_availability_status,r.label_scope,
        s.official_result_state,e.source_path,e.source_row
      FROM entry e JOIN result x USING(meet,race_date,race_no,hr_no)
      JOIN race r USING(meet,race_date,race_no)
      JOIN state s USING(meet,race_date,race_no)
      LEFT JOIN research_entry q USING(meet,race_date,race_no,hr_no)
      ORDER BY e.race_date,e.race_no,e.chul_no""", db, "entry_result", busan_transform)

    def yeongcheon_transform(frame: pd.DataFrame) -> pd.DataFrame:
        frame["race_id"] = [race_id("YEONGCHEON", d, n) for d, n in zip(frame.race_date, frame.race_no)]
        frame["venue_code"] = "YEONGCHEON"
        frame["canonical_meet"] = 4
        frame["horse_name_raw"] = frame.pop("horse_name")
        frame["horse_name_normalized"] = frame.horse_name_raw.map(normalized_name)
        frame["horse_weight_raw"] = frame.body_weight_kg.astype("Int64").astype(str) + "(" + frame.body_weight_change_kg.fillna(0).astype("Int64").astype(str) + ")"
        frame["finish_raw"] = frame.finish_position.astype("Int64").astype(str)
        frame["result_status"] = frame.apply(
            lambda row: "disqualified" if row.disqualified else
            ("finished" if pd.notna(row.finish_position) and (row.finish_time_ms or 0) > 0 else
             ("scratched" if row.scratched else "void_or_unresulted")), axis=1)
        frame["race_time_s"] = frame.finish_time_ms / 1000.0
        frame["is_dead_heat"] = False
        frame["source_prior_races"] = None
        frame["source_prior_wins"] = None
        frame["source_training_28d"] = None
        frame["source_training_seconds_28d"] = None
        frame["source_start_training_28d"] = None
        frame["source_confirmed_medical_28d"] = None
        frame["source_availability_status"] = "cold_start_venue"
        frame["training_28d_status"] = "linked_across_home_training_venue_later"
        frame["start_training_28d_status"] = "linked_across_home_training_venue_later"
        frame["medical_28d_status"] = "linked_across_home_training_venue_later"
        frame["current_weight_availability"] = "retrospective_operating_db"
        frame["label_scope"] = "official_race"
        frame["official_result_state"] = "confirmed"
        frame["is_model_target"] = True
        frame["is_rank_label"] = frame.result_status.eq("finished")
        frame["source_dataset"] = "operating_db_meet4_confirmed"
        frame["source_path"] = "data/horse_racing.sqlite3"
        frame["source_row"] = frame.pop("entry_id")
        frame["owner_no_raw_json"] = frame.owner_no
        frame["diff_raw"] = frame.pop("margin_text")
        frame["horse_weight_delta_kg"] = frame.pop("body_weight_change_kg")
        frame["horse_weight_kg"] = frame.pop("body_weight_kg")
        frame["burden_weight_kg"] = frame.pop("carried_weight_kg")
        frame["age_raw"] = frame.pop("age")
        frame["sex_raw"] = frame.pop("sex")
        frame["origin_raw"] = frame.pop("origin_country")
        frame["rating_raw"] = frame.pop("rating")
        frame["win_odds"] = None
        frame["place_odds"] = None
        frame = frame.drop(columns=["finish_position", "finish_time_ms", "disqualified", "scratched"])
        return frame

    counts["entry_yeongcheon"] = copy_query(operating, """
      SELECT e.id entry_id,r.race_date_local race_date,r.race_number race_no,
        e.horse_number chul_no,h.kra_horse_id hr_no,h.name_ko horse_name,
        h.origin_country,h.sex,CAST((julianday(r.race_date_local)-julianday(h.birth_date))/365.25 AS INTEGER) age,
        e.rating,j.kra_jockey_id jockey_no,t.kra_trainer_id trainer_no,
        o.kra_owner_id owner_no,j.name_ko jockey_name,t.name_ko trainer_name,
        o.name_ko owner_name,e.carried_weight_kg,e.body_weight_kg,
        e.body_weight_change_kg,e.scratched,x.finish_position,x.finish_time_ms,
        x.margin_text,x.disqualified
      FROM races r JOIN racecourses c ON c.id=r.racecourse_id
      JOIN race_entries e ON e.race_id=r.id JOIN horses h ON h.id=e.horse_id
      LEFT JOIN jockeys j ON j.id=e.jockey_id LEFT JOIN trainers t ON t.id=e.trainer_id
      LEFT JOIN owners o ON o.id=e.owner_id JOIN race_results x ON x.race_entry_id=e.id
      WHERE c.kra_meet_code=4 AND r.status='completed' AND x.finish_time_ms>0
      ORDER BY r.race_date_local,r.race_number,e.horse_number""", db, "entry_result", yeongcheon_transform)

    db.execute("""
      UPDATE entry_result e SET is_dead_heat=true
      FROM (SELECT race_id,finish_order FROM entry_result
            WHERE is_rank_label GROUP BY race_id,finish_order HAVING count(*)>1) d
      WHERE e.race_id=d.race_id AND e.finish_order=d.finish_order
    """)
    return counts


def load_sections(
    db: duckdb.DuckDBPyConnection,
    seoul: sqlite3.Connection,
    busan: sqlite3.Connection,
    operating: sqlite3.Connection,
) -> dict:
    counts = {}

    def transform(frame: pd.DataFrame, venue: str, dataset: str) -> pd.DataFrame:
        frame["race_id"] = [race_id(venue, d, n) for d, n in zip(frame.race_date, frame.race_no)]
        frame["venue_code"] = venue
        frame["canonical_meet"] = VENUE_MEETS[venue]
        frame["source_dataset"] = dataset
        return frame

    counts["section_seoul"] = copy_query(seoul, """
      SELECT race_date,race_no,hr_no,source_field,section_code,
        CAST(round(value_s*1000) AS INTEGER) value_ms,unit,time_basis,
        CAST(round(canonical_closing_s*1000) AS INTEGER) canonical_closing_ms,
        position_raw,semantic_status,source_path,source_row
      FROM section ORDER BY race_date,race_no,hr_no,source_field""", db, "section",
      lambda f: transform(f, "SEOUL", "seoul_backfill_20260915_v1"))

    counts["section_busan"] = copy_query(busan, """
      SELECT race_date,race_no,hr_no,source_field,NULL section_code,
        CAST(round(value_s*1000) AS INTEGER) value_ms,unit,
        'source_specific_unverified' time_basis,NULL canonical_closing_ms,
        NULL position_raw,semantic_status,source_path,source_row
      FROM section ORDER BY race_date,race_no,hr_no,source_field""", db, "section",
      lambda f: transform(f, "BUSAN", "busan_complete_db_20260916"))

    def y_transform(frame: pd.DataFrame) -> pd.DataFrame:
        frame["race_id"] = [race_id("YEONGCHEON", d, n) for d, n in zip(frame.race_date, frame.race_no)]
        frame["venue_code"] = "YEONGCHEON"
        frame["canonical_meet"] = 4
        frame["source_field"] = frame.section_code
        frame["value_ms"] = frame.pop("elapsed_time_ms")
        frame["unit"] = "milliseconds"
        frame["canonical_closing_ms"] = None
        frame["position_raw"] = frame.pop("position").astype("Int64").astype(str)
        frame["semantic_status"] = "official_api_verified_first_meeting"
        frame["source_dataset"] = "operating_db_meet4_confirmed"
        frame["source_path"] = "data/horse_racing.sqlite3"
        frame["source_row"] = frame.pop("section_id")
        return frame

    counts["section_yeongcheon"] = copy_query(operating, """
      SELECT s.id section_id,r.race_date_local race_date,r.race_number race_no,
        h.kra_horse_id hr_no,s.section_code,s.elapsed_time_ms,s.position,
        s.time_basis
      FROM race_section_results s JOIN race_entries e ON e.id=s.race_entry_id
      JOIN races r ON r.id=e.race_id JOIN racecourses c ON c.id=r.racecourse_id
      JOIN horses h ON h.id=e.horse_id
      WHERE c.kra_meet_code=4 AND r.status='completed'
      ORDER BY r.race_date_local,r.race_number,e.horse_number,s.id""",
      db, "section", y_transform)
    return counts


def load_training(
    db: duckdb.DuckDBPyConnection,
    seoul: sqlite3.Connection,
    busan: sqlite3.Connection,
    operating: sqlite3.Connection,
) -> dict:
    counts = {}

    def history_transform(frame: pd.DataFrame, venue: str, dataset: str) -> pd.DataFrame:
        frame["training_event_id"] = dataset + ":" + frame.pop("event_id").astype(str)
        frame["training_venue_code"] = venue
        frame["source_meet"] = VENUE_MEETS[venue]
        frame["source_dataset"] = dataset
        return frame

    query = """SELECT event_id,source_type,event_date,hr_no,horse_name,duration_seconds,
      start_time_raw,end_time_raw,intensity_1,intensity_2,trainer_name_raw,part_raw,
      rider_no_raw,remark_raw,availability_status,source_path,source_row
      FROM training_event ORDER BY event_date,event_id"""
    counts["training_seoul_history"] = copy_query(
        seoul, query, db, "training_event",
        lambda f: history_transform(f, "SEOUL", "seoul_backfill_20260915_v1"))
    counts["training_busan_history"] = copy_query(
        busan, query, db, "training_event",
        lambda f: history_transform(f, "BUSAN", "busan_complete_db_20260916"))

    max_dates = {
        ("SEOUL", "horse_training"): "2026-09-13",
        ("SEOUL", "start_training"): "2026-09-11",
        ("BUSAN", "horse_training"): "2026-09-13",
        ("BUSAN", "start_training"): "2026-09-12",
    }

    def operating_transform(frame: pd.DataFrame, venue: str, kind: str) -> pd.DataFrame:
        frame["training_event_id"] = "operating:" + kind + ":" + frame.pop("id").astype(str)
        frame["training_venue_code"] = venue
        frame["source_meet"] = VENUE_MEETS[venue]
        frame["source_type"] = kind
        frame["event_date"] = frame.pop("training_date_local")
        frame["availability_status"] = "availability_unverified"
        frame["source_dataset"] = "operating_increment_20260918"
        frame["source_path"] = "data/horse_racing.sqlite3"
        frame["source_row"] = frame.training_event_id.str.rsplit(":", n=1).str[-1].astype(int)
        return frame

    for venue, meet in (("SEOUL", 1), ("BUSAN", 3)):
        cutoff = max_dates[(venue, "horse_training")]
        q = """SELECT x.id,x.training_date_local,h.kra_horse_id hr_no,h.name_ko horse_name,
          x.duration_seconds,x.started_at_raw start_time_raw,x.ended_at_raw end_time_raw,
          x.canter_count intensity_1,x.gallop_count intensity_2,
          x.trainer_name trainer_name_raw,CAST(x.stable_part AS VARCHAR) part_raw,
          x.rider_id rider_no_raw,x.entry_plan remark_raw
          FROM horse_training x JOIN horses h ON h.id=x.horse_id
          WHERE x.meet_code=? AND x.training_date_local>? ORDER BY x.training_date_local,x.id"""
        counts[f"training_{venue.lower()}_increment"] = copy_query(
            operating, q, db, "training_event",
            lambda f, v=venue: operating_transform(f, v, "horse_training"),
            (meet, cutoff))
        cutoff = max_dates[(venue, "start_training")]
        q = """SELECT x.id,x.training_date_local,h.kra_horse_id hr_no,h.name_ko horse_name,
          NULL duration_seconds,NULL start_time_raw,NULL end_time_raw,NULL intensity_1,
          NULL intensity_2,NULL trainer_name_raw,CAST(x.stable_part AS VARCHAR) part_raw,
          NULL rider_no_raw,coalesce(x.rider_name,'')||'|'||coalesce(x.remark,'') remark_raw
          FROM horse_start_training x JOIN horses h ON h.id=x.horse_id
          WHERE x.meet_code=? AND x.training_date_local>? ORDER BY x.training_date_local,x.id"""
        counts[f"start_training_{venue.lower()}_increment"] = copy_query(
            operating, q, db, "training_event",
            lambda f, v=venue: operating_transform(f, v, "start_training"),
            (meet, cutoff))
    return counts


def load_trials(
    db: duckdb.DuckDBPyConnection,
    seoul_trials: sqlite3.Connection,
    busan: sqlite3.Connection,
    operating: sqlite3.Connection,
) -> dict:
    counts = {}

    def s_transform(frame: pd.DataFrame) -> pd.DataFrame:
        frame["trial_event_id"] = [trial_id("SEOUL", d, n) for d, n in zip(frame.trial_date, frame.trial_no)]
        frame["venue_code"] = "SEOUL"
        frame["canonical_meet"] = 1
        frame["region_code"] = "SEOUL"
        frame["source_meet"] = 1
        frame["venue_resolution_status"] = "confirmed"
        frame["trial_kind"] = "running_trial_or_practice"
        frame["horse_name_normalized"] = frame.horse_name_raw.map(normalized_name)
        frame["person_link_status"] = frame.jockey_link_status.fillna("") + "|" + frame.trainer_link_status.fillna("")
        frame["availability_status"] = "retrospective_only"
        frame["source_dataset"] = "seoul_running_trials_20260915_v1"
        frame["section_json"] = frame.apply(lambda r: json.dumps({
            "g3f_ms": r.g3f_ms, "s1f_ms": r.s1f_ms,
            "corner_3_ms": r.corner_3_ms, "corner_4_ms": r.corner_4_ms,
            "g1f_ms": r.g1f_ms, "passing_order_raw": r.passing_order_raw,
        }, ensure_ascii=False), axis=1)
        return frame.drop(columns=["jockey_link_status", "trainer_link_status", "g3f_ms",
                                   "s1f_ms", "corner_3_ms", "corner_4_ms", "g1f_ms",
                                   "passing_order_raw"])

    counts["trial_seoul"] = copy_query(seoul_trials, """
      WITH people AS (
        SELECT meet,trial_date,trial_race_no,horse_number,
          max(CASE WHEN actor_type='jockey' THEN linked_official_id END) jockey_no,
          max(CASE WHEN actor_type='trainer' THEN linked_official_id END) trainer_no,
          max(CASE WHEN actor_type='jockey' THEN link_status END) jockey_link_status,
          max(CASE WHEN actor_type='trainer' THEN link_status END) trainer_link_status
        FROM trial_person_link GROUP BY 1,2,3,4)
      SELECT x.trial_date,x.trial_race_no trial_no,x.horse_number participant_no,
        t.trial_round,t.distance_m,t.weather weather_raw,t.track_condition track_raw,
        t.track_moisture_percent,x.official_hr_no hr_no,x.horse_name_raw,
        x.origin_raw,x.sex_raw,x.age_raw,p.jockey_no,x.jockey_name_raw,p.trainer_no,
        x.trainer_name_raw,x.finish_rank_raw finish_raw,
        CASE WHEN x.finish_rank_raw GLOB '[0-9]*' AND CAST(x.finish_rank_raw AS INTEGER)<90
             THEN CAST(x.finish_rank_raw AS INTEGER) END finish_position,
        x.result_state,x.judgement_raw,x.failure_reason_raw,
        x.inspection_reason_raw,x.body_weight_kg,x.finish_time_ms,x.horse_link_status,
        p.jockey_link_status,p.trainer_link_status,x.g3f_ms,x.s1f_ms,x.corner_3_ms,
        x.corner_4_ms,x.g1f_ms,x.passing_order_raw,t.source_path
      FROM trial_result x JOIN trial t USING(meet,trial_date,trial_race_no)
      LEFT JOIN people p USING(meet,trial_date,trial_race_no,horse_number)
      ORDER BY x.trial_date,x.trial_race_no,x.horse_number""", db, "trial_entry", s_transform)

    def b_transform(frame: pd.DataFrame) -> pd.DataFrame:
        frame["trial_event_id"] = [trial_id("BUSAN", d, n) for d, n in zip(frame.trial_date, frame.trial_no)]
        frame["venue_code"] = "BUSAN"
        frame["canonical_meet"] = 3
        frame["region_code"] = "YEONGNAM"
        frame["source_meet"] = 3
        frame["venue_resolution_status"] = "confirmed_historical_text"
        frame["horse_name_normalized"] = frame.horse_name_raw.map(normalized_name)
        frame["result_state"] = frame.apply(lambda r: "timed_trial" if (r.finish_time_ms or 0)>0 else "untimed_or_special", axis=1)
        frame["failure_reason_raw"] = None
        frame["person_link_status"] = "official_api_exact_event_key_when_available"
        frame["source_dataset"] = "busan_trial_linkage_20260915"
        return frame

    counts["trial_busan"] = copy_query(busan, """
      SELECT e.trial_date,e.trial_no,e.chul_no participant_no,t.trial_round,
        t.trial_kind,t.distance_m,t.weather_raw,t.track_raw,t.track_moisture_percent,
        e.hr_no,e.horse_name_raw,e.origin_raw,e.sex_raw,e.age_raw,
        a.jockey_no,e.jockey_name_raw,a.trainer_no,e.trainer_name_raw,e.finish_raw,
        e.finish_position,e.judgement_raw,e.inspection_reason_raw,e.body_weight_kg,
        e.finish_time_ms,e.section_json,e.link_status horse_link_status,
        e.availability_status,e.source_path
      FROM trial_entry e JOIN trial t USING(meet,trial_date,trial_no)
      LEFT JOIN trial_api_entry a ON a.meet=e.meet AND a.trial_date=e.trial_date
        AND a.trial_no=e.trial_no AND a.chul_no=e.chul_no
      ORDER BY e.trial_date,e.trial_no,e.chul_no""", db, "trial_entry", b_transform)

    # Apply current official revisions while preserving their provenance.
    for day, no, chul, judgement, failure in [
        ("2026-08-13", 3, 5, "불합격", None),
        ("2026-09-03", 2, 8, "합격", "-"),
    ]:
        db.execute("""UPDATE trial_entry SET judgement_raw=?,failure_reason_raw=?,
          source_dataset='busan_trial_linkage_plus_api_revision_20260917'
          WHERE venue_code='BUSAN' AND trial_date=? AND trial_no=? AND participant_no=?""",
                   [judgement, failure, day, no, chul])

    def op_transform(frame: pd.DataFrame, venue: str | None) -> pd.DataFrame:
        event_venue = venue or "YEONGNAM_UNRESOLVED"
        frame["trial_event_id"] = [trial_id(event_venue, d, n) for d, n in zip(frame.trial_date, frame.trial_no)]
        frame["venue_code"] = venue
        frame["canonical_meet"] = VENUE_MEETS[venue] if venue else None
        frame["region_code"] = "SEOUL" if venue == "SEOUL" else "YEONGNAM"
        frame["source_meet"] = 1 if venue == "SEOUL" else 3
        frame["venue_resolution_status"] = "confirmed" if venue else "unresolved_after_yeongcheon_split"
        frame["trial_kind"] = "running_trial"
        frame["horse_name_normalized"] = frame.horse_name_raw.map(normalized_name)
        frame["result_state"] = frame.apply(lambda r: "timed_trial" if (r.finish_time_ms or 0)>0 else "untimed_or_special", axis=1)
        frame["horse_link_status"] = frame.hr_no.notna().map({True:"confirmed_official_id",False:"unmatched"})
        frame["person_link_status"] = "operating_official_relationship"
        frame["availability_status"] = "availability_unverified"
        frame["source_dataset"] = "operating_increment_20260918"
        frame["source_path"] = "data/horse_racing.sqlite3"
        frame["section_json"] = frame.pop("sections_json")
        return frame

    op_query = """
      SELECT t.trial_date_local trial_date,t.trial_race_number trial_no,
        x.horse_number participant_no,t.trial_round,t.distance_m,t.weather weather_raw,
        t.track_condition track_raw,t.track_moisture_percent,h.kra_horse_id hr_no,
        x.horse_name_raw,x.origin_country origin_raw,x.sex sex_raw,x.age age_raw,
        j.kra_jockey_id jockey_no,x.jockey_name_raw,tr.kra_trainer_id trainer_no,
        x.trainer_name_raw,x.finish_rank_raw finish_raw,x.finish_position,
        x.judgement judgement_raw,x.failure_reason failure_reason_raw,
        x.inspection_reason inspection_reason_raw,x.body_weight_kg,x.finish_time_ms,
        json_object('g3f_ms',x.g3f_ms,'s1f_ms',x.s1f_ms,'corner_3_ms',x.corner_3_ms,
          'corner_4_ms',x.corner_4_ms,'g1f_ms',x.g1f_ms,'section_400_ms',x.section_400_ms,
          'final_400_ms',x.final_400_ms,'passing_order_raw',x.passing_order_raw) sections_json
      FROM running_trials t JOIN running_trial_results x ON x.running_trial_id=t.id
      LEFT JOIN horses h ON h.id=x.horse_id LEFT JOIN jockeys j ON j.id=x.jockey_id
      LEFT JOIN trainers tr ON tr.id=x.trainer_id
      WHERE t.meet_code=? AND t.trial_date_local>? ORDER BY t.trial_date_local,t.trial_race_number,x.horse_number"""
    counts["trial_seoul_increment"] = copy_query(
        operating, op_query, db, "trial_entry", lambda f: op_transform(f, "SEOUL"),
        (1, "2026-09-10"))
    counts["trial_yeongnam_unresolved_increment"] = copy_query(
        operating, op_query, db, "trial_entry", lambda f: op_transform(f, None),
        (3, "2026-09-10"))

    conflicts = [
        ("trial_source_conflict", "SEOUL", "2026-06-04", 2, 1, "커널이클립티컬", "0061460|캡틴리엄"),
        ("trial_source_conflict", "SEOUL", "2026-06-11", 1, 7, "원평대세", "0061529|원평크라운"),
        ("trial_source_conflict", "SEOUL", "2026-06-18", 3, 1, "아모스챔프", "0055209|클러치마일"),
        ("trial_source_conflict", "SEOUL", "2026-07-02", 2, 2, "아모스월드", "0055466|클러치더비"),
    ]
    db.executemany("INSERT INTO identity_issue VALUES(?,?,?,?,?,?,?,?,?)", [
        (*row, "ambiguous_source_conflict", "Same trial date/no/participant but Text and current API identify different horses.")
        for row in conflicts])
    return counts


def load_medical(
    db: duckdb.DuckDBPyConnection,
    seoul: sqlite3.Connection,
    busan: sqlite3.Connection,
    operating: sqlite3.Connection,
) -> dict:
    counts = {}

    def text_transform(frame: pd.DataFrame, venue: str, dataset: str) -> pd.DataFrame:
        frame["medical_event_id"] = dataset + ":text:" + frame.pop("event_id").astype(str)
        frame["source_venue_code"] = venue
        frame["source_meet"] = VENUE_MEETS[venue]
        frame["source_type"] = "text"
        frame["diagnosis_1_raw"] = frame.pop("diagnosis_raw")
        frame["diagnosis_2_raw"] = None
        frame["has_content"] = frame.diagnosis_1_raw.fillna("").ne("-")
        frame["source_dataset"] = dataset
        frame["source_row"] = frame.pop("line_no")
        return frame

    text_query = """SELECT event_id,event_date,horse_name,stable_no_raw,facility_raw,
      diagnosis_raw,hr_no,link_status,candidate_hr_nos_json,availability_status,
      source_path,line_no FROM medical_event ORDER BY event_date,event_id"""
    counts["medical_text_seoul"] = copy_query(
        seoul, text_query, db, "medical_event",
        lambda f: text_transform(f, "SEOUL", "seoul_backfill_20260915_v1"))
    counts["medical_text_busan"] = copy_query(
        busan, text_query, db, "medical_event",
        lambda f: text_transform(f, "BUSAN", "busan_complete_db_20260916"))

    def api_history_transform(frame: pd.DataFrame) -> pd.DataFrame:
        frame["medical_event_id"] = "busan_complete:api:" + frame.pop("event_id").astype(str)
        frame["source_venue_code"] = "BUSAN"
        frame["source_meet"] = 3
        frame["source_type"] = "official_api"
        frame["stable_no_raw"] = frame.pop("part_raw")
        frame["link_status"] = "confirmed_official_id"
        frame["candidate_hr_nos_json"] = "[]"
        frame["source_dataset"] = "busan_complete_db_20260916"
        return frame

    counts["medical_api_busan_pre2025"] = copy_query(busan, """
      SELECT event_id,event_date,hr_no,horse_name,part_raw,facility_raw,
        diagnosis_1_raw,diagnosis_2_raw,has_content,availability_status,
        source_path,source_row FROM medical_api_event WHERE event_date<'2025-01-01'
      ORDER BY event_date,event_id""", db, "medical_event", api_history_transform)

    def op_transform(frame: pd.DataFrame, venue: str) -> pd.DataFrame:
        frame["medical_event_id"] = "operating:api:" + frame.pop("id").astype(str)
        frame["source_venue_code"] = venue
        frame["source_meet"] = VENUE_MEETS[venue]
        frame["source_type"] = "official_api"
        frame["event_date"] = frame.pop("clinic_date_local")
        frame["stable_no_raw"] = frame.pop("stable_part").astype("Int64").astype(str)
        frame["has_content"] = frame.diagnosis_1_raw.fillna("").ne("-") | frame.diagnosis_2_raw.fillna("").ne("-")
        frame["link_status"] = "confirmed_official_id"
        frame["candidate_hr_nos_json"] = "[]"
        frame["availability_status"] = "availability_unverified"
        frame["source_dataset"] = "operating_official_api_2025plus"
        frame["source_path"] = "data/horse_racing.sqlite3"
        frame["source_row"] = frame.medical_event_id.str.rsplit(":", n=1).str[-1].astype(int)
        return frame

    query = """SELECT x.id,x.clinic_date_local,h.kra_horse_id hr_no,h.name_ko horse_name,
      x.stable_part,x.hospital_name facility_raw,x.diagnosis_1 diagnosis_1_raw,
      x.diagnosis_2 diagnosis_2_raw FROM horse_medical x JOIN horses h ON h.id=x.horse_id
      WHERE x.meet_code=? ORDER BY x.clinic_date_local,x.id"""
    for venue, meet in (("SEOUL", 1), ("BUSAN", 3)):
        counts[f"medical_api_{venue.lower()}_2025plus"] = copy_query(
            operating, query, db, "medical_event", lambda f, v=venue: op_transform(f, v), (meet,))
    return counts


def entry_lookup(db: duckdb.DuckDBPyConnection) -> dict:
    frame = db.execute("""SELECT venue_code,CAST(race_date AS VARCHAR) race_date,race_no,
      chul_no,hr_no,horse_name_normalized,race_id FROM entry_result""").fetch_df()
    return {(row.venue_code, row.race_date, int(row.race_no), int(row.chul_no)):
            (row.hr_no, row.horse_name_normalized, row.race_id)
            for row in frame.itertuples(index=False)}


def load_weights_and_equipment(
    db: duckdb.DuckDBPyConnection,
    seoul: sqlite3.Connection,
    busan: sqlite3.Connection,
    operating: sqlite3.Connection,
    lookup: dict,
) -> dict:
    counts = {}

    def weight_transform(frame: pd.DataFrame, venue: str, dataset: str) -> pd.DataFrame:
        source_rows = []
        keep = []
        for i, row in frame.iterrows():
            day = str(row.race_date)
            key = (venue, day, int(row.race_no), int(row.chul_no))
            candidate = lookup.get(key)
            raw_norm = normalized_name(row.horse_name)
            if candidate and raw_norm == candidate[1]:
                hr_no, race_value, status = candidate[0], candidate[2], "confirmed_canonical_race_key"
            elif candidate:
                hr_no, race_value, status = row.hr_no, candidate[2], "ambiguous_name_conflict"
            else:
                # The known 2026-09-13 meet=3 Text file is actually Yeongcheon.
                if venue == "BUSAN" and day == "2026-09-13":
                    keep.append(False)
                    source_rows.append(None)
                    continue
                hr_no, race_value, status = row.hr_no, None, row.link_status
            keep.append(True)
            source_rows.append((hr_no, race_value, status, raw_norm))
        frame = frame.loc[keep].copy()
        source_rows = [value for value in source_rows if value is not None]
        frame["hr_no"] = [value[0] for value in source_rows]
        frame["race_id"] = [value[1] for value in source_rows]
        frame["link_status"] = [value[2] for value in source_rows]
        frame["horse_name_normalized"] = [value[3] for value in source_rows]
        frame["weight_event_id"] = dataset + ":" + frame.race_date.astype(str).str.replace("-", "") + ":" + frame.race_no.astype(str) + ":" + frame.chul_no.astype(str) + ":" + frame.source_path.astype(str)
        frame["venue_code"] = venue
        frame["canonical_meet"] = VENUE_MEETS[venue]
        frame["horse_name_raw"] = frame.pop("horse_name")
        frame["availability_status"] = "availability_unverified"
        frame["source_dataset"] = dataset
        frame["source_row"] = frame.pop("line_no")
        return frame

    query = """SELECT race_date,race_no,chul_no,horse_name,weight_kg,
      weight_delta_kg,hr_no,link_status,source_path,line_no FROM race_day_weight
      ORDER BY race_date,race_no,chul_no,source_path"""
    counts["weight_seoul"] = copy_query(
        seoul, query, db, "weight_event",
        lambda f: weight_transform(f, "SEOUL", "seoul_backfill_20260915_v1"))
    counts["weight_busan"] = copy_query(
        busan, query, db, "weight_event",
        lambda f: weight_transform(f, "BUSAN", "busan_complete_db_20260916"))

    def y_weight(frame: pd.DataFrame) -> pd.DataFrame:
        frame["weight_event_id"] = "operating:weight:" + frame.pop("id").astype(str)
        frame["race_id"] = [race_id("YEONGCHEON", d, n) for d, n in zip(frame.race_date, frame.race_no)]
        frame["venue_code"] = "YEONGCHEON"
        frame["canonical_meet"] = 4
        frame["horse_name_raw"] = frame.pop("horse_name")
        frame["horse_name_normalized"] = frame.horse_name_raw.map(normalized_name)
        frame["link_status"] = "confirmed_official_id"
        frame["availability_status"] = "availability_unverified"
        frame["source_dataset"] = "operating_db_meet4_confirmed"
        frame["source_path"] = "data/horse_racing.sqlite3"
        frame["source_row"] = frame.weight_event_id.str.rsplit(":", n=1).str[-1].astype(int)
        return frame

    counts["weight_yeongcheon"] = copy_query(operating, """
      SELECT w.id,w.race_date_local race_date,w.race_number race_no,
        w.horse_number chul_no,h.kra_horse_id hr_no,h.name_ko horse_name,
        w.body_weight_kg weight_kg,w.body_weight_change_kg weight_delta_kg
      FROM horse_weight_history w JOIN horses h ON h.id=w.horse_id
      WHERE w.meet_code=4 AND w.race_date_local IN
        (SELECT r.race_date_local FROM races r JOIN racecourses c ON c.id=r.racecourse_id
         WHERE c.kra_meet_code=4 AND r.status='completed')
      ORDER BY w.race_date_local,w.race_number,w.horse_number""", db, "weight_event", y_weight)

    def equipment_transform(frame: pd.DataFrame, venue: str, dataset: str) -> pd.DataFrame:
        values = []
        keep = []
        for _, row in frame.iterrows():
            day = str(row.race_date)
            candidate = lookup.get((venue, day, int(row.race_no), int(row.chul_no)))
            raw_norm = normalized_name(row.horse_name)
            if candidate and raw_norm == candidate[1]:
                values.append((candidate[0], candidate[2], "confirmed_canonical_race_key", raw_norm))
                keep.append(True)
            elif candidate:
                values.append((row.hr_no, candidate[2], "ambiguous_name_conflict", raw_norm))
                keep.append(True)
            elif venue == "BUSAN" and day == "2026-09-13":
                keep.append(False); values.append(None)
            else:
                values.append((row.hr_no, None, row.link_status, raw_norm)); keep.append(True)
        frame = frame.loc[keep].copy()
        values = [value for value in values if value is not None]
        frame["hr_no"] = [value[0] for value in values]
        frame["race_id"] = [value[1] for value in values]
        frame["link_status"] = [value[2] for value in values]
        frame["horse_name_normalized"] = [value[3] for value in values]
        frame["equipment_event_id"] = dataset + ":" + frame.race_date.astype(str).str.replace("-", "") + ":" + frame.race_no.astype(str) + ":" + frame.chul_no.astype(str) + ":" + frame.source_path.astype(str)
        frame["venue_code"] = venue
        frame["canonical_meet"] = VENUE_MEETS[venue]
        frame["horse_name_raw"] = frame.pop("horse_name")
        frame["bleeding_count"] = None
        frame["bleeding_date_raw"] = None
        frame["illness_note"] = None
        frame["availability_status"] = "availability_unverified"
        frame["source_dataset"] = dataset
        frame["source_row"] = frame.pop("line_no")
        return frame

    eq_query = """SELECT race_date,race_no,chul_no,horse_name,hr_no,link_status,
      detail_raw,source_path,line_no FROM entry_equipment
      ORDER BY race_date,race_no,chul_no,source_path"""
    counts["equipment_seoul"] = copy_query(
        seoul, eq_query, db, "equipment_event",
        lambda f: equipment_transform(f, "SEOUL", "seoul_backfill_20260915_v1"))
    counts["equipment_busan"] = copy_query(
        busan, eq_query, db, "equipment_event",
        lambda f: equipment_transform(f, "BUSAN", "busan_complete_db_20260916"))

    def y_equipment(frame: pd.DataFrame) -> pd.DataFrame:
        frame["equipment_event_id"] = "operating:equipment:" + frame.pop("id").astype(str)
        frame["race_id"] = [race_id("YEONGCHEON", d, n) for d, n in zip(frame.race_date, frame.race_no)]
        frame["venue_code"] = "YEONGCHEON"
        frame["canonical_meet"] = 4
        frame["horse_name_raw"] = frame.pop("horse_name")
        frame["horse_name_normalized"] = frame.horse_name_raw.map(normalized_name)
        frame["detail_raw"] = frame.pop("equipment_raw")
        frame["link_status"] = "confirmed_official_id"
        frame["availability_status"] = "availability_unverified"
        frame["source_dataset"] = "operating_db_meet4_confirmed"
        frame["source_path"] = "data/horse_racing.sqlite3"
        frame["source_row"] = frame.equipment_event_id.str.rsplit(":", n=1).str[-1].astype(int)
        return frame

    counts["equipment_yeongcheon"] = copy_query(operating, """
      SELECT q.id,q.race_date_local race_date,q.race_number race_no,
        q.horse_number chul_no,h.kra_horse_id hr_no,h.name_ko horse_name,
        q.equipment_raw,q.bleeding_count,q.bleeding_date_raw,q.illness_note
      FROM entry_equipment q LEFT JOIN horses h ON h.id=q.horse_id
      WHERE q.meet_code=4 AND q.race_date_local IN
        (SELECT r.race_date_local FROM races r JOIN racecourses c ON c.id=r.racecourse_id
         WHERE c.kra_meet_code=4 AND r.status='completed')
      ORDER BY q.race_date_local,q.race_number,q.horse_number""", db, "equipment_event", y_equipment)

    # Preserve the excluded misfile as one explicit issue, not 54 fake Busan weights.
    db.execute("""INSERT INTO identity_issue VALUES
      ('source_venue_mismatch','BUSAN','2026-09-13',NULL,NULL,
       'meet=3 Text path','YEONGCHEON (meet=4)','quarantined',
       '54 dacom12 weight rows have an explicit Yeongcheon document header; official meet=4 rows are used instead.')""")
    return counts


def build_features(db: duckdb.DuckDBPyConnection) -> None:
    db.execute("""
      CREATE TABLE pre_race_training_features AS
      SELECT e.race_id,e.hr_no,
        count(DISTINCT CASE WHEN t.source_type='horse_training' THEN t.event_date END)
          FILTER(WHERE t.event_date>=e.race_date-INTERVAL 3 DAY) training_days_3d,
        count(DISTINCT CASE WHEN t.source_type='horse_training' THEN t.event_date END)
          FILTER(WHERE t.event_date>=e.race_date-INTERVAL 7 DAY) training_days_7d,
        count(DISTINCT CASE WHEN t.source_type='horse_training' THEN t.event_date END)
          FILTER(WHERE t.event_date>=e.race_date-INTERVAL 14 DAY) training_days_14d,
        count(DISTINCT CASE WHEN t.source_type='horse_training' THEN t.event_date END) training_days_28d,
        coalesce(sum(CASE WHEN t.source_type='horse_training' AND
          t.event_date>=e.race_date-INTERVAL 7 DAY THEN t.duration_seconds END),0) training_seconds_7d,
        coalesce(sum(CASE WHEN t.source_type='horse_training' THEN t.duration_seconds END),0) training_seconds_28d,
        count(*) FILTER(WHERE t.source_type='start_training') start_training_events_28d,
        count(DISTINCT t.training_venue_code) training_venues_28d
      FROM entry_result e LEFT JOIN training_event t ON t.hr_no=e.hr_no
        AND t.event_date<e.race_date AND t.event_date>=e.race_date-INTERVAL 28 DAY
      WHERE e.is_model_target GROUP BY e.race_id,e.hr_no
    """)
    db.execute("""
      CREATE TABLE pre_race_medical_features AS
      SELECT e.race_id,e.hr_no,
        count(DISTINCT CASE WHEN m.source_type='official_api' THEN m.medical_event_id END)
          official_medical_events_28d,
        count(DISTINCT CASE WHEN m.source_type='text' AND m.link_status='confirmed'
          THEN concat(CAST(m.event_date AS VARCHAR),'|',coalesce(m.facility_raw,''),'|',
                      coalesce(m.diagnosis_1_raw,''),'|',coalesce(m.diagnosis_2_raw,'')) END)
          confirmed_text_medical_events_28d
      FROM entry_result e LEFT JOIN medical_event m ON m.hr_no=e.hr_no
        AND m.event_date<e.race_date AND m.event_date>=e.race_date-INTERVAL 28 DAY
        AND m.has_content
      WHERE e.is_model_target GROUP BY e.race_id,e.hr_no
    """)
    db.execute("""
      CREATE TABLE model_entry_base AS
      WITH history AS (
        SELECT e.*,
          row_number() OVER(PARTITION BY hr_no ORDER BY race_date,race_no,venue_code)-1 prior_starts_all,
          count(*) FILTER(WHERE is_rank_label) OVER(PARTITION BY hr_no ORDER BY race_date,race_no,venue_code ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) prior_finished_all,
          count(*) FILTER(WHERE is_rank_label AND finish_order=1) OVER(PARTITION BY hr_no ORDER BY race_date,race_no,venue_code ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) prior_wins_all,
          count(*) FILTER(WHERE is_rank_label AND finish_order<=3) OVER(PARTITION BY hr_no ORDER BY race_date,race_no,venue_code ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) prior_top3_all,
          row_number() OVER(PARTITION BY hr_no,venue_code ORDER BY race_date,race_no)-1 prior_starts_at_venue,
          lag(race_date) OVER(PARTITION BY hr_no ORDER BY race_date,race_no,venue_code) previous_race_date,
          lag(venue_code) OVER(PARTITION BY hr_no ORDER BY race_date,race_no,venue_code) previous_race_venue,
          first_value(venue_code) OVER(PARTITION BY hr_no ORDER BY race_date,race_no,venue_code ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) first_observed_venue
        FROM entry_result e)
      SELECT h.*,
        h.prior_starts_all-h.prior_starts_at_venue prior_starts_other_venue,
        CASE WHEN h.previous_race_date IS NULL THEN NULL
             ELSE date_diff('day',h.previous_race_date,h.race_date) END days_since_last_race,
        coalesce(h.previous_race_venue<>h.venue_code,false) venue_changed_since_last_start,
        h.prior_starts_at_venue=0 first_start_at_venue,
        h.venue_code<>h.first_observed_venue away_from_first_observed_venue,
        coalesce(t.training_days_3d,0) training_days_3d,
        coalesce(t.training_days_7d,0) training_days_7d,
        coalesce(t.training_days_14d,0) training_days_14d,
        coalesce(t.training_days_28d,0) training_days_28d,
        coalesce(t.training_seconds_7d,0) training_seconds_7d,
        coalesce(t.training_seconds_28d,0) training_seconds_28d,
        coalesce(t.start_training_events_28d,0) start_training_events_28d,
        coalesce(t.training_venues_28d,0) training_venues_28d,
        coalesce(m.official_medical_events_28d,0) official_medical_events_28d,
        coalesce(m.confirmed_text_medical_events_28d,0) confirmed_text_medical_events_28d,
        extract(year FROM h.race_date)::INTEGER race_year,
        extract(month FROM h.race_date)::INTEGER race_month,
        'strictly_before_race_date' history_cutoff_contract
      FROM history h
      LEFT JOIN pre_race_training_features t USING(race_id,hr_no)
      LEFT JOIN pre_race_medical_features m USING(race_id,hr_no)
    """)
    db.execute("CREATE TABLE model_target_entry AS SELECT * FROM model_entry_base WHERE is_model_target")
    db.execute("""
      CREATE TABLE model_training_entry AS
      SELECT
        m.race_id,m.venue_code,m.canonical_meet,r.region_code,m.race_date,m.race_no,
        r.race_type,r.race_class,r.distance_m,r.burden_type,r.rating_condition_raw,
        r.track_raw,r.weather_raw,r.track_moisture_percent,
        m.chul_no,m.hr_no,m.horse_name_normalized,m.origin_raw,m.sex_raw,m.age_raw,
        m.rating_raw,m.jockey_no,m.trainer_no,m.owner_no,m.burden_weight_kg,
        m.horse_weight_kg race_day_weight_kg,
        m.horse_weight_delta_kg race_day_weight_delta_kg,
        m.current_weight_availability race_day_weight_availability,
        m.prior_starts_all,m.prior_finished_all,m.prior_wins_all,m.prior_top3_all,
        m.prior_starts_at_venue,m.prior_starts_other_venue,m.days_since_last_race,
        m.previous_race_venue,m.venue_changed_since_last_start,m.first_start_at_venue,
        m.away_from_first_observed_venue,m.training_days_3d,m.training_days_7d,
        m.training_days_14d,m.training_days_28d,m.training_seconds_7d,
        m.training_seconds_28d,m.start_training_events_28d,m.training_venues_28d,
        m.official_medical_events_28d,m.confirmed_text_medical_events_28d,
        m.race_year,m.race_month,
        m.result_status target_result_status,m.finish_order target_finish_order,
        m.race_time_s target_race_time_s,m.is_rank_label target_is_rank_label,
        m.is_dead_heat target_is_dead_heat,
        'exclude race_day_weight_* and race-day track/weather unless historical publication timing is independently verified' feature_availability_note,
        m.history_cutoff_contract
      FROM model_target_entry m JOIN race r USING(race_id)
    """)
    db.execute("""
      CREATE TABLE horse_dimension AS
      SELECT hr_no,min(horse_name_normalized) canonical_name,
        string_agg(DISTINCT horse_name_raw,' | ' ORDER BY horse_name_raw) raw_name_variants,
        min(race_date) first_race_date,max(race_date) last_race_date,
        arg_min(venue_code,race_date) first_observed_venue,
        count(*) race_entry_rows,count(DISTINCT venue_code) observed_venue_count
      FROM entry_result GROUP BY hr_no
    """)


def build_coverage(db: duckdb.DuckDBPyConnection) -> None:
    db.execute("""
      CREATE TABLE coverage_year_source AS
      SELECT venue_code,'race' source_name,year(race_date)::INTEGER coverage_year,
        count(*) row_count,count(DISTINCT race_id) object_count,
        NULL::BIGINT distinct_horses,1.0::DOUBLE official_id_rate,
        min(race_date) first_date,max(race_date) last_date,
        string_agg(DISTINCT official_result_state,', ' ORDER BY official_result_state) statuses
      FROM race GROUP BY 1,2,3
      UNION ALL
      SELECT venue_code,'entry_result',year(race_date)::INTEGER,count(*),
        count(DISTINCT race_id),count(DISTINCT hr_no),
        avg((coalesce(hr_no,'')<>'')::INTEGER),min(race_date),max(race_date),
        string_agg(DISTINCT result_status,', ' ORDER BY result_status)
      FROM entry_result GROUP BY 1,2,3
      UNION ALL
      SELECT venue_code,'section',year(race_date)::INTEGER,count(*),
        count(DISTINCT race_id),count(DISTINCT hr_no),
        avg((coalesce(hr_no,'')<>'')::INTEGER),min(race_date),max(race_date),
        string_agg(DISTINCT semantic_status,', ' ORDER BY semantic_status)
      FROM section GROUP BY 1,2,3
      UNION ALL
      SELECT coalesce(venue_code,'YEONGNAM_UNRESOLVED'),'trial_entry',year(trial_date)::INTEGER,
        count(*),count(DISTINCT trial_event_id),count(DISTINCT hr_no),
        avg((coalesce(hr_no,'')<>'')::INTEGER),min(trial_date),max(trial_date),
        string_agg(DISTINCT venue_resolution_status||':'||coalesce(horse_link_status,''),
          ', ' ORDER BY venue_resolution_status||':'||coalesce(horse_link_status,''))
      FROM trial_entry GROUP BY 1,2,3
      UNION ALL
      SELECT training_venue_code,'training_'||source_type,year(event_date)::INTEGER,
        count(*),count(DISTINCT event_date||'|'||hr_no),count(DISTINCT hr_no),
        avg((coalesce(hr_no,'')<>'')::INTEGER),min(event_date),max(event_date),
        string_agg(DISTINCT availability_status,', ' ORDER BY availability_status)
      FROM training_event GROUP BY 1,2,3
      UNION ALL
      SELECT source_venue_code,'medical_'||source_type,year(event_date)::INTEGER,
        count(*),count(DISTINCT medical_event_id),count(DISTINCT hr_no),
        avg((coalesce(hr_no,'')<>'')::INTEGER),min(event_date),max(event_date),
        string_agg(DISTINCT link_status,', ' ORDER BY link_status)
      FROM medical_event GROUP BY 1,2,3
      UNION ALL
      SELECT venue_code,'weight_event',year(race_date)::INTEGER,count(*),
        count(DISTINCT race_id),count(DISTINCT hr_no),
        avg((link_status LIKE 'confirmed%')::INTEGER),min(race_date),max(race_date),
        string_agg(DISTINCT link_status,', ' ORDER BY link_status)
      FROM weight_event GROUP BY 1,2,3
      UNION ALL
      SELECT venue_code,'equipment_event',year(race_date)::INTEGER,count(*),
        count(DISTINCT race_id),count(DISTINCT hr_no),
        avg((link_status LIKE 'confirmed%')::INTEGER),min(race_date),max(race_date),
        string_agg(DISTINCT link_status,', ' ORDER BY link_status)
      FROM equipment_event GROUP BY 1,2,3
      UNION ALL
      SELECT venue_code,'model_target_entry',year(race_date)::INTEGER,count(*),
        count(DISTINCT race_id),count(DISTINCT hr_no),
        avg((coalesce(hr_no,'')<>'')::INTEGER),min(race_date),max(race_date),
        string_agg(DISTINCT target_result_status,', ' ORDER BY target_result_status)
      FROM model_training_entry GROUP BY 1,2,3
    """)


def build_unresolved_ledger(db: duckdb.DuckDBPyConnection) -> None:
    db.execute("""
      CREATE TABLE unresolved_identity_ledger AS
      SELECT issue_type issue_domain,venue_code,event_date,
        concat(coalesce(CAST(event_no AS VARCHAR),''),'|',coalesce(CAST(participant_no AS VARCHAR),'')) event_key,
        CAST(participant_no AS VARCHAR) participant_no,source_value,candidate_value,
        status,evidence,'identity_issue' source_dataset,NULL::VARCHAR source_path,NULL::INTEGER source_row
      FROM identity_issue
      UNION ALL
      SELECT 'medical_identity',source_venue_code,event_date,medical_event_id,NULL,
        horse_name,candidate_hr_nos_json,link_status,
        'Historical Text medical identity is retained without automatic name-only assignment.',
        source_dataset,source_path,source_row
      FROM medical_event WHERE link_status<>'confirmed_official_id' AND link_status<>'confirmed'
      UNION ALL
      SELECT 'weight_identity',venue_code,race_date,coalesce(race_id,concat(race_date,'|',race_no)),
        CAST(chul_no AS VARCHAR),horse_name_raw,hr_no,link_status,
        'Race/chul candidate conflicts with normalized horse name or no canonical race candidate exists.',
        source_dataset,source_path,source_row
      FROM weight_event WHERE link_status NOT LIKE 'confirmed%'
      UNION ALL
      SELECT 'equipment_identity',venue_code,race_date,coalesce(race_id,concat(race_date,'|',race_no)),
        CAST(chul_no AS VARCHAR),horse_name_raw,hr_no,link_status,
        'Race/chul candidate conflicts with normalized horse name or no canonical race candidate exists.',
        source_dataset,source_path,source_row
      FROM equipment_event WHERE link_status NOT LIKE 'confirmed%'
      UNION ALL
      SELECT 'trial_identity_or_venue',coalesce(venue_code,'YEONGNAM_UNRESOLVED'),trial_date,
        trial_event_id,CAST(participant_no AS VARCHAR),horse_name_raw,hr_no,
        CASE WHEN venue_resolution_status LIKE 'unresolved%' THEN venue_resolution_status
             ELSE horse_link_status END,
        'Horse identity and actual venue resolution are evaluated independently.',
        source_dataset,source_path,NULL
      FROM trial_entry
      WHERE venue_resolution_status LIKE 'unresolved%'
         OR horse_link_status IN ('ambiguous','ambiguous_historical_age','signature_conflict','unmatched_profile','unmatched')
      UNION ALL
      SELECT 'entry_actor_identity',venue_code,race_date,race_id,CAST(chul_no AS VARCHAR),
        horse_name_raw,
        concat('trainer=',coalesce(trainer_no,''),';owner=',coalesce(owner_no,'')),
        'missing_official_actor_id','Trainer or owner ID remains absent in the canonical historical source.',
        source_dataset,source_path,source_row
      FROM entry_result
      WHERE coalesce(trainer_no,'')='' OR coalesce(owner_no,'')=''
    """)


def validate(db: duckdb.DuckDBPyConnection) -> dict:
    counts = {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in [
        "race", "entry_result", "section", "trial_entry", "training_event",
        "medical_event", "weight_event", "equipment_event", "model_entry_base",
        "model_target_entry", "model_training_entry", "horse_dimension",
        "coverage_year_source", "unresolved_identity_ledger", "identity_issue"]}
    by_venue = [dict(zip(["venue_code", "races", "entries", "first_date", "last_date"], row))
                for row in db.execute("""SELECT r.venue_code,count(DISTINCT r.race_id),
                  count(e.hr_no),min(r.race_date),max(r.race_date) FROM race r
                  LEFT JOIN entry_result e USING(race_id) GROUP BY r.venue_code ORDER BY r.venue_code""").fetchall()]
    result = {
        "counts": counts,
        "by_venue": by_venue,
        "primary_key_duplicates": {
            "race": db.execute("SELECT count(*) FROM (SELECT race_id,count(*) n FROM race GROUP BY 1 HAVING n>1)").fetchone()[0],
            "entry_result": db.execute("SELECT count(*) FROM (SELECT race_id,hr_no,count(*) n FROM entry_result GROUP BY 1,2 HAVING n>1)").fetchone()[0],
            "trial_entry": db.execute("SELECT count(*) FROM (SELECT trial_event_id,participant_no,count(*) n FROM trial_entry GROUP BY 1,2 HAVING n>1)").fetchone()[0],
        },
        "orphan_counts": {
            "entry_without_race": db.execute("SELECT count(*) FROM entry_result e LEFT JOIN race r USING(race_id) WHERE r.race_id IS NULL").fetchone()[0],
            "section_without_entry": db.execute("SELECT count(*) FROM section s LEFT JOIN entry_result e USING(race_id,hr_no) WHERE e.race_id IS NULL").fetchone()[0],
        },
        "future_history_violations": {
            "training_feature_contract_enforced": True,
            "feature_contract": "All pre_race_* feature joins use event_date < race_date and a 28-day lower bound.",
        },
        "model_targets": dict(zip(
            ["races", "entries", "rank_label_entries"],
            db.execute("""SELECT count(DISTINCT race_id),count(*),
              count(*) FILTER(WHERE is_rank_label) FROM model_target_entry""").fetchone()
        )),
        "cross_venue": {
            "horses_multiple_venues": db.execute("SELECT count(*) FROM horse_dimension WHERE observed_venue_count>1").fetchone()[0],
            "venue_change_rows": db.execute("SELECT count(*) FROM model_entry_base WHERE venue_changed_since_last_start").fetchone()[0],
        },
        "venue_integrity": {
            "busan_20260913_races": db.execute("SELECT count(*) FROM race WHERE venue_code='BUSAN' AND race_date='2026-09-13'").fetchone()[0],
            "yeongcheon_20260913_races": db.execute("SELECT count(*) FROM race WHERE venue_code='YEONGCHEON' AND race_date='2026-09-13'").fetchone()[0],
            "busan_20260913_weights": db.execute("SELECT count(*) FROM weight_event WHERE venue_code='BUSAN' AND race_date='2026-09-13'").fetchone()[0],
            "yeongcheon_20260913_weights": db.execute("SELECT count(*) FROM weight_event WHERE venue_code='YEONGCHEON' AND race_date='2026-09-13'").fetchone()[0],
        },
        "id_missing": {
            "entry_hr_no": db.execute("SELECT count(*) FROM entry_result WHERE coalesce(hr_no,'')='' ").fetchone()[0],
            "entry_jockey_no": db.execute("SELECT count(*) FROM entry_result WHERE coalesce(jockey_no,'')='' ").fetchone()[0],
            "entry_trainer_no": db.execute("SELECT count(*) FROM entry_result WHERE coalesce(trainer_no,'')='' ").fetchone()[0],
            "entry_owner_no": db.execute("SELECT count(*) FROM entry_result WHERE coalesce(owner_no,'')='' ").fetchone()[0],
        },
        "weight_link_status": dict(db.execute("SELECT link_status,count(*) FROM weight_event GROUP BY 1 ORDER BY 1").fetchall()),
        "trial_venue_resolution": dict(db.execute("SELECT venue_resolution_status,count(*) FROM trial_entry GROUP BY 1 ORDER BY 1").fetchall()),
        "medical_link_status": dict(db.execute("SELECT source_type||':'||link_status,count(*) FROM medical_event GROUP BY 1 ORDER BY 1").fetchall()),
    }
    return result


def export_tables(db: duckdb.DuckDBPyConnection, out: Path) -> list[Path]:
    parquet = out / "parquet"
    parquet.mkdir()
    tables = [
        "venue_dimension", "race", "entry_result", "section", "trial_entry",
        "training_event", "medical_event", "weight_event", "equipment_event",
        "model_entry_base", "model_target_entry", "model_training_entry", "horse_dimension",
        "coverage_year_source", "unresolved_identity_ledger", "identity_issue",
    ]
    outputs = []
    for table in tables:
        path = parquet / f"{table}.parquet"
        db.execute(f"COPY {table} TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(path)])
        outputs.append(path)
    coverage_csv = out / "coverage_year_source.csv"
    db.execute("COPY (SELECT * FROM coverage_year_source ORDER BY venue_code,source_name,coverage_year) "
               "TO ? (HEADER, DELIMITER ',')", [str(coverage_csv)])
    outputs.append(coverage_csv)
    unresolved_csv = out / "unresolved_identity_summary.csv"
    db.execute("COPY (SELECT issue_domain,status,count(*) row_count,"
               "min(event_date) first_date,max(event_date) last_date "
               "FROM unresolved_identity_ledger GROUP BY 1,2 ORDER BY 1,2) "
               "TO ? (HEADER, DELIMITER ',')", [str(unresolved_csv)])
    outputs.append(unresolved_csv)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    (out / "tmp").mkdir()
    database = out / "thoroughbred_unified.duckdb"
    db = duckdb.connect(str(database))
    db.execute("SET threads=4")
    db.execute("SET memory_limit='4GB'")
    db.execute("SET temp_directory=?", [str(out / "tmp")])
    create_schema(db)

    seoul = sqlite_ro(SEOUL_DB)
    seoul_trials = sqlite_ro(SEOUL_TRIAL_DB)
    busan = sqlite_ro(BUSAN_DB)
    operating = sqlite_ro(OPERATING_DB)
    operating.execute("BEGIN")
    extras, race_extras = load_busan_extras()
    source_counts: dict[str, int] = {}
    try:
        source_counts.update(load_races(db, seoul, busan, operating, race_extras))
        source_counts.update(load_entries(db, seoul, busan, operating, extras))
        source_counts.update(load_sections(db, seoul, busan, operating))
        source_counts.update(load_trials(db, seoul_trials, busan, operating))
        source_counts.update(load_training(db, seoul, busan, operating))
        source_counts.update(load_medical(db, seoul, busan, operating))
        lookup = entry_lookup(db)
        source_counts.update(load_weights_and_equipment(db, seoul, busan, operating, lookup))
        build_features(db)
        build_coverage(db)
        build_unresolved_ledger(db)
        validation = validate(db)
        db.execute("CHECKPOINT")
        parquet_files = export_tables(db, out)
        db.execute("CHECKPOINT")
    finally:
        operating.rollback()
        for connection in (seoul, seoul_trials, busan, operating):
            connection.close()
        db.close()

    validation["built_at_utc"] = datetime.now(timezone.utc).isoformat()
    validation["source_counts"] = source_counts
    validation["database"] = str(database.relative_to(ROOT))
    validation["database_sha256"] = sha256(database)
    validation["existing_databases_modified"] = False
    (out / "validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8")

    manifest_paths = [database, out / "validation.json", Path(__file__).resolve(), *parquet_files]
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_version": "2026-09-18",
        "artifacts": {
            str(path.relative_to(ROOT)): {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in manifest_paths
        },
        "read_only_sources": [str(path.relative_to(ROOT)) for path in
                              (SEOUL_DB, SEOUL_TRIAL_DB, BUSAN_DB, OPERATING_DB)],
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"database": str(database), "validation": validation},
                     ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
