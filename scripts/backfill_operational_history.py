#!/usr/bin/env python3
"""Backfill trusted historical research records into the operational SQLite DB.

The loader is deliberately conservative:

* races/entries/results/sections are loaded only before 2015-01-01;
* horse-history events are loaded only before 2025-01-01;
* only rows with official horse IDs and confirmed identity/link states are used;
* every insert is idempotent through the operational natural keys;
* source hashes, cutoff policy, row counts, and validation results are recorded in
  ``historical_backfill_batches``.

The original research databases remain the row-level lineage archives.  This
script records batch-level provenance in the serving database instead of copying
millions of repeated source paths into hot operational tables.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data/horse_racing.sqlite3"
DEFAULT_THOROUGHBRED = (
    ROOT / "data/research/thoroughbred_unified_20260918/thoroughbred_unified.duckdb"
)
DEFAULT_JEJU = (
    ROOT / "data/research/jeju_native_text_phase2_db_20260915" / "jeju_native_text_phase2.sqlite3"
)

RACE_CUTOFF_ISO = "2015-01-01"
EVENT_CUTOFF_ISO = "2025-01-01"
RACE_CUTOFF_COMPACT = "20150101"
EVENT_CUTOFF_COMPACT = "20250101"
CHUNK_SIZE = 20_000


def now_ms() -> int:
    return int(time.time() * 1000)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compact_to_iso(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value)
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clip(value: Any, length: int) -> str | None:
    if value is None:
        return None
    return str(value)[:length]


def positive_int(value: Any) -> int | None:
    parsed = int_or_none(value)
    return parsed if parsed is not None and parsed > 0 else None


def parse_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_position(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    return int(text) if text.isdigit() and int(text) > 0 else None


def chunks(cursor: Any, size: int = CHUNK_SIZE) -> Iterator[list[Sequence[Any]]]:
    while True:
        rows = cursor.fetchmany(size)
        if not rows:
            return
        yield rows


def insert_many(
    connection: sqlite3.Connection,
    sql: str,
    rows: Iterable[Sequence[Any]],
) -> int:
    before = connection.total_changes
    connection.executemany(sql, rows)
    return connection.total_changes - before


def stream_insert(
    connection: sqlite3.Connection,
    cursor: Any,
    sql: str,
    transform: Callable[[Sequence[Any]], Sequence[Any] | None],
) -> int:
    written = 0
    for source_rows in chunks(cursor):
        target_rows = []
        for row in source_rows:
            mapped = transform(row)
            if mapped is not None:
                target_rows.append(mapped)
        if target_rows:
            written += insert_many(connection, sql, target_rows)
    return written


def operational_maps(connection: sqlite3.Connection) -> dict[str, dict[Any, Any]]:
    return {
        "horse": dict(connection.execute("SELECT kra_horse_id,id FROM horses")),
        "jockey": dict(connection.execute("SELECT kra_jockey_id,id FROM jockeys")),
        "trainer": dict(connection.execute("SELECT kra_trainer_id,id FROM trainers")),
        "owner": dict(connection.execute("SELECT kra_owner_id,id FROM owners")),
        "course": dict(connection.execute("SELECT kra_meet_code,id FROM racecourses")),
    }


def begin_batch(
    connection: sqlite3.Connection,
    batch_key: str,
    source_name: str,
    source_path: Path,
    source_hash: str,
) -> int:
    policy = json.dumps(
        {
            "race_before": RACE_CUTOFF_ISO,
            "event_before": EVENT_CUTOFF_ISO,
            "identity_policy": "confirmed_official_ids_only",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    connection.execute(
        """
        INSERT INTO historical_backfill_batches(
          batch_key,source_name,source_path,source_sha256,cutoff_policy_json,
          started_at_ms,status,records_written_json,validation_json
        ) VALUES(?,?,?,?,?,?,'running','{}','{}')
        ON CONFLICT(batch_key) DO UPDATE SET
          source_name=excluded.source_name,
          source_path=excluded.source_path,
          source_sha256=excluded.source_sha256,
          cutoff_policy_json=excluded.cutoff_policy_json,
          started_at_ms=excluded.started_at_ms,
          completed_at_ms=NULL,
          status='running',
          records_written_json='{}',
          validation_json='{}'
        """,
        (batch_key, source_name, str(source_path), source_hash, policy, now_ms()),
    )
    return int(
        connection.execute(
            "SELECT id FROM historical_backfill_batches WHERE batch_key=?", (batch_key,)
        ).fetchone()[0]
    )


def should_skip_completed_batch(
    connection: sqlite3.Connection, batch_key: str, source_hash: str
) -> bool:
    row = connection.execute(
        """
        SELECT status,source_sha256
        FROM historical_backfill_batches
        WHERE batch_key=?
        """,
        (batch_key,),
    ).fetchone()
    if row is None:
        return False
    status, recorded_hash = row
    if status == "completed" and recorded_hash == source_hash:
        return True
    if status == "completed" and recorded_hash != source_hash:
        raise RuntimeError(
            f"{batch_key} already completed with a different source hash; "
            "use a new batch key after reviewing the changed source"
        )
    return False


def update_batch(
    connection: sqlite3.Connection,
    batch_id: int,
    status: str,
    counts: dict[str, int],
    validation: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        """
        UPDATE historical_backfill_batches
        SET status=?, completed_at_ms=?, records_written_json=?, validation_json=?
        WHERE id=?
        """,
        (
            status,
            now_ms() if status != "running" else None,
            json.dumps(counts, ensure_ascii=False, sort_keys=True),
            json.dumps(validation or {}, ensure_ascii=False, sort_keys=True),
            batch_id,
        ),
    )


def load_people_from_thoroughbred(
    target: sqlite3.Connection, source: duckdb.DuckDBPyConnection
) -> dict[str, int]:
    counts: dict[str, int] = {}
    specifications = [
        ("jockeys", "kra_jockey_id", "jockey_no", "jockey_name"),
        ("trainers", "kra_trainer_id", "trainer_no", "trainer_name"),
        ("owners", "kra_owner_id", "owner_no", "owner_name"),
    ]
    for table, target_id, source_id, source_name in specifications:
        cursor = source.execute(
            f"""
            SELECT {source_id},max({source_name})
            FROM entry_result
            WHERE race_date < DATE '{RACE_CUTOFF_ISO}'
              AND {source_id} IS NOT NULL AND trim({source_id})<>''
            GROUP BY 1
            """
        )
        counts[table] = stream_insert(
            target,
            cursor,
            f"INSERT OR IGNORE INTO {table}({target_id},name_ko) VALUES(?,?)",
            lambda row: (str(row[0]), str(row[1] or row[0])),
        )
    return counts


def load_thoroughbred_races(
    target: sqlite3.Connection, source: duckdb.DuckDBPyConnection
) -> dict[str, int]:
    counts = load_people_from_thoroughbred(target, source)
    maps = operational_maps(target)
    venue_meet = {"SEOUL": 1, "BUSAN": 3}
    race_cursor = source.execute(
        f"""
        SELECT venue_code,race_date,race_no,distance_m,race_class,race_type,
               burden_type,track_raw,weather_raw,track_moisture_percent,
               official_result_state,rating_condition_raw
        FROM race
        WHERE race_date < DATE '{RACE_CUTOFF_ISO}' AND venue_code IN ('SEOUL','BUSAN')
        ORDER BY race_date,venue_code,race_no
        """
    )

    def map_race(row: Sequence[Any]) -> Sequence[Any]:
        meet = venue_meet[str(row[0])]
        state = str(row[10] or "confirmed")
        status = "completed" if state == "confirmed" else state
        return (
            maps["course"][meet],
            str(row[1]),
            row[2],
            row[3],
            clip(row[4], 50),
            clip(row[5], 200),
            clip(row[6], 50),
            clip(row[8], 30),
            clip(row[7], 30),
            row[9],
            clip(row[11], 100),
            status,
        )

    counts["races"] = stream_insert(
        target,
        race_cursor,
        """
        INSERT OR IGNORE INTO races(
          racecourse_id,race_date_local,race_number,distance_m,grade,race_name,
          burden_type,weather,track_condition,track_moisture_percent,
          rating_condition,status
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        map_race,
    )
    target.commit()
    race_map = {
        (meet, date, number): race_id
        for race_id, meet, date, number in target.execute(
            """
            SELECT r.id,rc.kra_meet_code,r.race_date_local,r.race_number
            FROM races r JOIN racecourses rc ON rc.id=r.racecourse_id
            WHERE r.race_date_local < ?
            """,
            (RACE_CUTOFF_ISO,),
        )
    }
    maps = operational_maps(target)
    entry_cursor = source.execute(
        f"""
        SELECT venue_code,race_date,race_no,chul_no,hr_no,jockey_no,trainer_no,owner_no,
               burden_weight_kg,horse_weight_kg,horse_weight_delta_kg,rating_raw,
               result_status,finish_order,race_time_s,diff_raw
        FROM entry_result
        WHERE race_date < DATE '{RACE_CUTOFF_ISO}' AND venue_code IN ('SEOUL','BUSAN')
        ORDER BY race_date,venue_code,race_no,chul_no
        """
    )

    def map_entry(row: Sequence[Any]) -> Sequence[Any] | None:
        meet = venue_meet[str(row[0])]
        race_id = race_map.get((meet, str(row[1]), int(row[2])))
        horse_id = maps["horse"].get(str(row[4]))
        if race_id is None or horse_id is None:
            return None
        status = str(row[12] or "")
        return (
            race_id,
            horse_id,
            maps["jockey"].get(str(row[5])) if row[5] else None,
            maps["trainer"].get(str(row[6])) if row[6] else None,
            maps["owner"].get(str(row[7])) if row[7] else None,
            row[3],
            row[8],
            row[9],
            row[10],
            row[11],
            int(status in {"scratched", "start_excluded"}),
        )

    counts["race_entries"] = stream_insert(
        target,
        entry_cursor,
        """
        INSERT OR IGNORE INTO race_entries(
          race_id,horse_id,jockey_id,trainer_id,owner_id,horse_number,
          carried_weight_kg,body_weight_kg,body_weight_change_kg,rating,scratched
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        map_entry,
    )
    target.commit()
    entry_map = dict(
        target.execute(
            """
            SELECT r.id||':'||h.kra_horse_id,re.id
            FROM race_entries re JOIN races r ON r.id=re.race_id
            JOIN horses h ON h.id=re.horse_id
            WHERE r.race_date_local < ?
            """,
            (RACE_CUTOFF_ISO,),
        )
    )
    result_cursor = source.execute(
        f"""
        SELECT venue_code,race_date,race_no,hr_no,finish_order,race_time_s,diff_raw,result_status
        FROM entry_result
        WHERE race_date < DATE '{RACE_CUTOFF_ISO}' AND venue_code IN ('SEOUL','BUSAN')
        ORDER BY race_date,venue_code,race_no,chul_no
        """
    )

    def map_result(row: Sequence[Any]) -> Sequence[Any] | None:
        meet = venue_meet[str(row[0])]
        race_id = race_map.get((meet, str(row[1]), int(row[2])))
        entry_id = entry_map.get(f"{race_id}:{row[3]}")
        if entry_id is None:
            return None
        status = str(row[7] or "")
        finish_ms = int(round(float(row[5]) * 1000)) if row[5] and float(row[5]) > 0 else None
        return (
            entry_id,
            positive_int(row[4]),
            finish_ms,
            row[6],
            int(status in {"disqualified", "race_excluded"}),
            status,
        )

    counts["race_results"] = stream_insert(
        target,
        result_cursor,
        """
        INSERT OR IGNORE INTO race_results(
          race_entry_id,finish_position,finish_time_ms,margin_text,disqualified,rank_remark
        ) VALUES(?,?,?,?,?,?)
        """,
        map_result,
    )
    section_cursor = source.execute(
        f"""
        SELECT venue_code,race_date,race_no,hr_no,section_code,value_ms,time_basis,
               position_raw,semantic_status
        FROM section
        WHERE race_date < DATE '{RACE_CUTOFF_ISO}' AND venue_code IN ('SEOUL','BUSAN')
        ORDER BY race_date,venue_code,race_no,hr_no,section_code
        """
    )

    def map_section(row: Sequence[Any]) -> Sequence[Any] | None:
        meet = venue_meet[str(row[0])]
        race_id = race_map.get((meet, str(row[1]), int(row[2])))
        entry_id = entry_map.get(f"{race_id}:{row[3]}")
        if entry_id is None or row[4] is None:
            return None
        return (
            entry_id,
            str(row[4]),
            None,
            positive_int(row[5]),
            str(row[6] or "cumulative"),
            "historical_research",
            parse_position(row[7]),
            str(row[8] or ""),
        )

    counts["race_section_results"] = stream_insert(
        target,
        section_cursor,
        """
        INSERT OR IGNORE INTO race_section_results(
          race_entry_id,section_code,distance_from_start_m,elapsed_time_ms,
          time_basis,source_kind,position,group_notation_raw
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        map_section,
    )
    target.commit()
    return counts


def load_thoroughbred_history(
    target: sqlite3.Connection, source: duckdb.DuckDBPyConnection, observed_ms: int
) -> dict[str, int]:
    counts: dict[str, int] = {}
    maps = operational_maps(target)
    training_cursor = source.execute(
        f"""
        SELECT source_meet,event_date,hr_no,part_raw,trainer_name_raw,rider_no_raw,
               start_time_raw,end_time_raw,duration_seconds,intensity_1,intensity_2,remark_raw
        FROM training_event
        WHERE source_type='horse_training' AND event_date < DATE '{EVENT_CUTOFF_ISO}'
        QUALIFY row_number() OVER(
          PARTITION BY hr_no,source_meet,event_date,start_time_raw,end_time_raw
          ORDER BY training_event_id
        )=1
        ORDER BY event_date,source_meet,hr_no
        """
    )

    def map_training(row: Sequence[Any]) -> Sequence[Any] | None:
        horse_id = maps["horse"].get(str(row[2]))
        if horse_id is None:
            return None
        return (
            horse_id,
            row[0],
            str(row[1]),
            int_or_none(row[3]),
            None,
            clip(row[4], 100),
            None,
            clip(row[5], 30),
            clip(row[6], 20),
            clip(row[7], 20),
            row[8],
            row[9],
            row[10],
            clip(row[11], 50),
            observed_ms,
        )

    counts["horse_training"] = stream_insert(
        target,
        training_cursor,
        """
        INSERT OR IGNORE INTO horse_training(
          horse_id,meet_code,training_date_local,stable_part,stable_number,trainer_name,
          rider_type,rider_id,started_at_raw,ended_at_raw,duration_seconds,canter_count,
          gallop_count,entry_plan,observed_at_ms
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        map_training,
    )
    target.commit()

    start_cursor = source.execute(
        f"""
        SELECT source_meet,event_date,hr_no,part_raw,rider_no_raw,remark_raw
        FROM training_event
        WHERE source_type='start_training' AND event_date < DATE '{EVENT_CUTOFF_ISO}'
        ORDER BY event_date,source_meet,hr_no
        """
    )

    def map_start(row: Sequence[Any]) -> Sequence[Any] | None:
        horse_id = maps["horse"].get(str(row[2]))
        if horse_id is None:
            return None
        return (
            horse_id,
            row[0],
            str(row[1]),
            int_or_none(row[3]),
            None,
            clip(row[4], 100),
            clip(row[5], 200),
            observed_ms,
        )

    counts["horse_start_training"] = stream_insert(
        target,
        start_cursor,
        """
        INSERT OR IGNORE INTO horse_start_training(
          horse_id,meet_code,training_date_local,stable_part,stable_number,
          rider_name,remark,observed_at_ms
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        map_start,
    )
    target.commit()

    medical_cursor = source.execute(
        f"""
        SELECT source_meet,event_date,hr_no,stable_no_raw,facility_raw,
               diagnosis_1_raw,diagnosis_2_raw
        FROM medical_event
        WHERE event_date < DATE '{EVENT_CUTOFF_ISO}'
          AND link_status IN ('confirmed','confirmed_official_id')
        QUALIFY row_number() OVER(
          PARTITION BY hr_no,source_meet,event_date,facility_raw,diagnosis_1_raw,diagnosis_2_raw
          ORDER BY CASE source_type WHEN 'official_api' THEN 0 ELSE 1 END,medical_event_id
        )=1
        ORDER BY event_date,source_meet,hr_no
        """
    )

    def map_medical(row: Sequence[Any]) -> Sequence[Any] | None:
        horse_id = maps["horse"].get(str(row[2]))
        if horse_id is None:
            return None
        return (
            horse_id,
            row[0],
            str(row[1]),
            int_or_none(row[3]),
            clip(row[4], 100),
            clip(row[5], 200),
            clip(row[6], 200),
            observed_ms,
        )

    counts["horse_medical"] = stream_insert(
        target,
        medical_cursor,
        """
        INSERT OR IGNORE INTO horse_medical(
          horse_id,meet_code,clinic_date_local,stable_part,hospital_name,
          diagnosis_1,diagnosis_2,observed_at_ms
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        map_medical,
    )
    target.commit()

    weight_cursor = source.execute(
        f"""
        SELECT canonical_meet,race_date,race_no,chul_no,hr_no,weight_kg,weight_delta_kg
        FROM weight_event
        WHERE race_date < DATE '{EVENT_CUTOFF_ISO}' AND link_status LIKE 'confirmed%'
        ORDER BY race_date,canonical_meet,race_no,chul_no
        """
    )

    def map_weight(row: Sequence[Any]) -> Sequence[Any] | None:
        horse_id = maps["horse"].get(str(row[4]))
        if horse_id is None:
            return None
        return (horse_id, row[0], str(row[1]), row[2], row[3], row[5], row[6], observed_ms)

    counts["horse_weight_history"] = stream_insert(
        target,
        weight_cursor,
        """
        INSERT OR IGNORE INTO horse_weight_history(
          horse_id,meet_code,race_date_local,race_number,horse_number,
          body_weight_kg,body_weight_change_kg,observed_at_ms
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        map_weight,
    )
    target.commit()

    equipment_cursor = source.execute(
        f"""
        SELECT canonical_meet,race_date,race_no,chul_no,max(hr_no),
               string_agg(DISTINCT detail_raw,' | '),max(bleeding_count),
               max(bleeding_date_raw),string_agg(DISTINCT illness_note,' | ')
        FROM equipment_event
        WHERE race_date < DATE '{EVENT_CUTOFF_ISO}' AND link_status LIKE 'confirmed%'
        GROUP BY 1,2,3,4
        ORDER BY race_date,canonical_meet,race_no,chul_no
        """
    )

    def map_equipment(row: Sequence[Any]) -> Sequence[Any]:
        horse_id = maps["horse"].get(str(row[4])) if row[4] else None
        return (
            horse_id,
            row[0],
            str(row[1]),
            row[2],
            row[3],
            clip(row[5], 200),
            row[6],
            clip(row[7], 40),
            clip(row[8], 200),
            observed_ms,
        )

    counts["entry_equipment"] = stream_insert(
        target,
        equipment_cursor,
        """
        INSERT OR IGNORE INTO entry_equipment(
          horse_id,meet_code,race_date_local,race_number,horse_number,equipment_raw,
          bleeding_count,bleeding_date_raw,illness_note,observed_at_ms
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        map_equipment,
    )
    target.commit()
    return counts


def load_thoroughbred_trials(
    target: sqlite3.Connection, source: duckdb.DuckDBPyConnection, observed_ms: int
) -> dict[str, int]:
    counts: dict[str, int] = {}
    maps = operational_maps(target)
    allowed = (
        "('confirmed','linked_profile_signature','linked_race_age_corroborated',"
        "'linked_training_date_corroborated','linked_training_disambiguated')"
    )
    trial_cursor = source.execute(
        f"""
        SELECT canonical_meet,trial_date,trial_no,max(trial_round),max(distance_m),
               max(weather_raw),max(track_raw),max(track_moisture_percent)
        FROM trial_entry
        WHERE trial_date < DATE '{EVENT_CUTOFF_ISO}' AND horse_link_status IN {allowed}
        GROUP BY 1,2,3 ORDER BY trial_date,canonical_meet,trial_no
        """
    )
    counts["running_trials"] = stream_insert(
        target,
        trial_cursor,
        """
        INSERT OR IGNORE INTO running_trials(
          meet_code,trial_date_local,trial_race_number,trial_round,distance_m,
          weather,track_condition,track_moisture_percent,observed_at_ms
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        lambda r: (r[0], str(r[1]), r[2], r[3], r[4], r[5], r[6], r[7], observed_ms),
    )
    target.commit()
    trial_map = dict(
        target.execute(
            """
            SELECT meet_code||':'||trial_date_local||':'||trial_race_number,id
            FROM running_trials WHERE trial_date_local < ?
            """,
            (EVENT_CUTOFF_ISO,),
        )
    )
    maps = operational_maps(target)
    result_cursor = source.execute(
        f"""
        SELECT canonical_meet,trial_date,trial_no,participant_no,hr_no,horse_name_raw,
               jockey_no,trainer_no,finish_position,finish_raw,origin_raw,sex_raw,age_raw,
               body_weight_kg,finish_time_ms,judgement_raw,failure_reason_raw,
               inspection_reason_raw,section_json,jockey_name_raw,trainer_name_raw
        FROM trial_entry
        WHERE trial_date < DATE '{EVENT_CUTOFF_ISO}' AND horse_link_status IN {allowed}
        ORDER BY trial_date,canonical_meet,trial_no,participant_no
        """
    )

    def map_trial_result(row: Sequence[Any]) -> Sequence[Any] | None:
        trial_id = trial_map.get(f"{row[0]}:{row[1]}:{row[2]}")
        if trial_id is None:
            return None
        segment = parse_json(row[18])
        return (
            trial_id,
            maps["horse"].get(str(row[4])),
            maps["jockey"].get(str(row[6])) if row[6] else None,
            maps["trainer"].get(str(row[7])) if row[7] else None,
            row[3],
            row[5] or str(row[4]),
            positive_int(row[8]),
            row[9],
            row[10],
            row[11],
            row[12],
            row[19],
            row[20],
            row[13],
            positive_int(row[14]),
            row[15],
            row[16],
            row[17],
            positive_int(segment.get("g3f_ms")),
            positive_int(segment.get("s1f_ms")),
            positive_int(segment.get("corner_3_ms")),
            positive_int(segment.get("corner_4_ms")),
            positive_int(segment.get("g1f_ms")),
            positive_int(segment.get("section_400_ms")),
            positive_int(segment.get("final_400_ms")),
            segment.get("passing_order_raw"),
            observed_ms,
        )

    counts["running_trial_results"] = stream_insert(
        target,
        result_cursor,
        """
        INSERT OR IGNORE INTO running_trial_results(
          running_trial_id,horse_id,jockey_id,trainer_id,horse_number,horse_name_raw,
          finish_position,finish_rank_raw,origin_country,sex,age,jockey_name_raw,
          trainer_name_raw,body_weight_kg,finish_time_ms,judgement,failure_reason,
          inspection_reason,g3f_ms,s1f_ms,corner_3_ms,corner_4_ms,g1f_ms,section_400_ms,
          final_400_ms,passing_order_raw,observed_at_ms
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        map_trial_result,
    )
    target.commit()
    return counts


def load_jeju_people_and_races(
    target: sqlite3.Connection, source: sqlite3.Connection
) -> dict[str, int]:
    counts: dict[str, int] = {}
    rows = source.execute(
        """
        SELECT e.tr_no,max(json_extract(s.normalized_json,'$.trName'))
        FROM entry e JOIN event v ON v.id=e.event_id JOIN source_row s ON s.id=e.source_row_id
        WHERE v.event_type='race' AND v.event_date<? AND e.tr_no IS NOT NULL AND e.tr_no<>''
        GROUP BY e.tr_no
        """,
        (RACE_CUTOFF_COMPACT,),
    )
    counts["trainers"] = insert_many(
        target,
        "INSERT OR IGNORE INTO trainers(kra_trainer_id,name_ko) VALUES(?,?)",
        ((str(r[0]), str(r[1] or r[0])) for r in rows),
    )
    rows = source.execute(
        """
        SELECT e.ow_no,max(json_extract(s.normalized_json,'$.owName'))
        FROM entry e JOIN event v ON v.id=e.event_id JOIN source_row s ON s.id=e.source_row_id
        WHERE v.event_type='race' AND v.event_date<? AND e.ow_no IS NOT NULL AND e.ow_no<>''
        GROUP BY e.ow_no
        """,
        (RACE_CUTOFF_COMPACT,),
    )
    counts["owners"] = insert_many(
        target,
        "INSERT OR IGNORE INTO owners(kra_owner_id,name_ko) VALUES(?,?)",
        ((str(r[0]), str(r[1] or r[0])) for r in rows),
    )
    rows = source.execute(
        """
        SELECT json_extract(s.normalized_json,'$.jkNo'),
               max(json_extract(s.normalized_json,'$.jkName'))
        FROM entry e JOIN event v ON v.id=e.event_id JOIN source_row s ON s.id=e.source_row_id
        WHERE v.event_type='race' AND v.event_date<?
          AND json_extract(s.normalized_json,'$.jkNo') IS NOT NULL
        GROUP BY 1
        """,
        (RACE_CUTOFF_COMPACT,),
    )
    counts["jockeys"] = insert_many(
        target,
        "INSERT OR IGNORE INTO jockeys(kra_jockey_id,name_ko) VALUES(?,?)",
        ((str(r[0]), str(r[1] or r[0])) for r in rows),
    )
    maps = operational_maps(target)
    race_rows = source.execute(
        """
        SELECT event_date,event_number,distance_m,grade,event_name,weather,
               track_condition,track_moisture_percent
        FROM event WHERE event_type='race' AND event_date<? ORDER BY event_date,event_number
        """,
        (RACE_CUTOFF_COMPACT,),
    )
    counts["races"] = insert_many(
        target,
        """
        INSERT OR IGNORE INTO races(
          racecourse_id,race_date_local,race_number,distance_m,grade,race_name,
          weather,track_condition,track_moisture_percent,status
        ) VALUES(?,?,?,?,?,?,?,?,?,'completed')
        """,
        (
            (maps["course"][2], compact_to_iso(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], r[7])
            for r in race_rows
        ),
    )
    target.commit()
    maps = operational_maps(target)
    race_map = dict(
        target.execute(
            """
            SELECT race_date_local||':'||race_number,id FROM races
            WHERE racecourse_id=? AND race_date_local<?
            """,
            (maps["course"][2], RACE_CUTOFF_ISO),
        )
    )
    entry_rows = source.execute(
        """
        SELECT v.event_date,v.event_number,e.horse_number,e.hr_no,e.tr_no,e.ow_no,
               e.record_status,e.finish_position,e.finish_time_ms,s.normalized_json
        FROM entry e JOIN event v ON v.id=e.event_id JOIN source_row s ON s.id=e.source_row_id
        WHERE v.event_type='race' AND v.event_date<?
        ORDER BY v.event_date,v.event_number,e.horse_number
        """,
        (RACE_CUTOFF_COMPACT,),
    )

    def jeju_entry_rows() -> Iterator[Sequence[Any]]:
        for row in entry_rows:
            raw = parse_json(row[9])
            race_id = race_map.get(f"{compact_to_iso(row[0])}:{row[1]}")
            horse_id = maps["horse"].get(str(row[3]))
            if race_id is None or horse_id is None:
                continue
            weight_raw = str(raw.get("wgHr") or "")
            weight = int_or_none(weight_raw.split("(", 1)[0])
            change = None
            if "(" in weight_raw and ")" in weight_raw:
                change = int_or_none(weight_raw.split("(", 1)[1].split(")", 1)[0].replace("+", ""))
            yield (
                race_id,
                horse_id,
                maps["jockey"].get(str(raw.get("jkNo"))) if raw.get("jkNo") else None,
                maps["trainer"].get(str(row[4])) if row[4] else None,
                maps["owner"].get(str(row[5])) if row[5] else None,
                row[2],
                raw.get("wgBudam"),
                weight,
                change,
                float_or_none(raw.get("rating")),
                int(str(row[6] or "") in {"scratched", "start_excluded"}),
            )

    counts["race_entries"] = insert_many(
        target,
        """
        INSERT OR IGNORE INTO race_entries(
          race_id,horse_id,jockey_id,trainer_id,owner_id,horse_number,carried_weight_kg,
          body_weight_kg,body_weight_change_kg,rating,scratched
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        jeju_entry_rows(),
    )
    target.commit()
    entry_map = dict(
        target.execute(
            """
            SELECT r.race_date_local||':'||r.race_number||':'||h.kra_horse_id,re.id
            FROM race_entries re JOIN races r ON r.id=re.race_id
            JOIN horses h ON h.id=re.horse_id
            WHERE r.racecourse_id=? AND r.race_date_local<?
            """,
            (maps["course"][2], RACE_CUTOFF_ISO),
        )
    )
    result_rows = source.execute(
        """
        SELECT v.event_date,v.event_number,e.hr_no,e.finish_position,e.finish_time_ms,
               e.record_status
        FROM entry e JOIN event v ON v.id=e.event_id
        WHERE v.event_type='race' AND v.event_date<?
        ORDER BY v.event_date,v.event_number,e.horse_number
        """,
        (RACE_CUTOFF_COMPACT,),
    )
    counts["race_results"] = insert_many(
        target,
        """
        INSERT OR IGNORE INTO race_results(
          race_entry_id,finish_position,finish_time_ms,disqualified,rank_remark
        ) VALUES(?,?,?,?,?)
        """,
        (
            (
                entry_map[f"{compact_to_iso(r[0])}:{r[1]}:{r[2]}"],
                positive_int(r[3]),
                positive_int(r[4]),
                int(str(r[5] or "") in {"disqualified", "race_excluded"}),
                r[5],
            )
            for r in result_rows
            if f"{compact_to_iso(r[0])}:{r[1]}:{r[2]}" in entry_map
        ),
    )
    section_rows = source.execute(
        """
        SELECT v.event_date,v.event_number,e.hr_no,c.section_code,c.distance_from_start_m,
               c.elapsed_from_start_ms,c.time_basis,c.source_kind
        FROM section_checkpoint c JOIN entry e ON e.id=c.entry_id JOIN event v ON v.id=e.event_id
        WHERE v.event_type='race' AND v.event_date<?
        ORDER BY v.event_date,v.event_number,e.horse_number,c.section_code
        """,
        (RACE_CUTOFF_COMPACT,),
    )
    counts["race_section_results"] = insert_many(
        target,
        """
        INSERT OR IGNORE INTO race_section_results(
          race_entry_id,section_code,distance_from_start_m,elapsed_time_ms,time_basis,source_kind
        ) VALUES(?,?,?,?,?,?)
        """,
        (
            (entry_map[f"{compact_to_iso(r[0])}:{r[1]}:{r[2]}"], r[3], r[4], r[5], r[6], r[7])
            for r in section_rows
            if f"{compact_to_iso(r[0])}:{r[1]}:{r[2]}" in entry_map
        ),
    )
    target.commit()
    return counts


def load_jeju_history(
    target: sqlite3.Connection, source: sqlite3.Connection, observed_ms: int
) -> dict[str, int]:
    counts: dict[str, int] = {}
    maps = operational_maps(target)
    counts["horse_training"] = insert_many(
        target,
        """
        INSERT OR IGNORE INTO horse_training(
          horse_id,meet_code,training_date_local,stable_part,stable_number,rider_type,
          rider_id,duration_seconds,canter_count,gallop_count,entry_plan,observed_at_ms
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            (
                maps["horse"][r[0]],
                2,
                compact_to_iso(r[1]),
                r[2],
                r[3],
                r[4],
                r[5],
                r[6],
                r[7],
                r[8],
                r[9],
                observed_ms,
            )
            for r in source.execute(
                """SELECT hr_no,event_date,part,part_no,exercise_person_type,exercise_person_no,
                training_duration_seconds,canter_count,gallop_count,entry_plan
                FROM daily_training_record WHERE event_date<? ORDER BY event_date,hr_no""",
                (EVENT_CUTOFF_COMPACT,),
            )
            if r[0] in maps["horse"]
        ),
    )
    target.commit()
    counts["horse_start_training"] = insert_many(
        target,
        """
        INSERT OR IGNORE INTO horse_start_training(
          horse_id,meet_code,training_date_local,stable_part,stable_number,rider_name,
          remark,observed_at_ms
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            (maps["horse"][r[0]], 2, compact_to_iso(r[1]), r[2], r[3], r[4], r[5], observed_ms)
            for r in source.execute(
                """SELECT hr_no,event_date,part,part_no,exercise_person_name,remark
                FROM start_training_record
                WHERE event_date<? AND duplicate_status='first_occurrence'
                ORDER BY event_date,hr_no""",
                (EVENT_CUTOFF_COMPACT,),
            )
            if r[0] in maps["horse"]
        ),
    )
    target.commit()
    counts["horse_medical"] = insert_many(
        target,
        """
        INSERT OR IGNORE INTO horse_medical(
          horse_id,meet_code,clinic_date_local,stable_part,hospital_name,
          diagnosis_1,diagnosis_2,observed_at_ms
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            (maps["horse"][r[0]], 2, compact_to_iso(r[1]), r[2], r[3], r[4], r[5], observed_ms)
            for r in source.execute(
                """SELECT hr_no,event_date,part,hospital_name,diagnosis_1,diagnosis_2
                FROM medical_record
                WHERE event_date<? AND duplicate_status='first_occurrence'
                ORDER BY event_date,hr_no""",
                (EVENT_CUTOFF_COMPACT,),
            )
            if r[0] in maps["horse"]
        ),
    )
    target.commit()
    counts["horse_weight_history"] = insert_many(
        target,
        """
        INSERT OR IGNORE INTO horse_weight_history(
          horse_id,meet_code,race_date_local,race_number,horse_number,
          body_weight_kg,body_weight_change_kg,observed_at_ms
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            (maps["horse"][r[0]], 2, compact_to_iso(r[1]), r[2], r[3], r[4], r[5], observed_ms)
            for r in source.execute(
                """
                SELECT hr_no,race_date,race_number,horse_number,
                       body_weight_kg,body_weight_change_kg
                FROM measured_weight_record
                WHERE race_date<?
                ORDER BY race_date,race_number,horse_number
                """,
                (EVENT_CUTOFF_COMPACT,),
            )
            if r[0] in maps["horse"]
        ),
    )
    target.commit()
    equipment_rows = source.execute(
        """
        SELECT event_date,event_number,horse_number,max(hr_no),
               group_concat(DISTINCT trim(json_extract(parsed_json,'$.detail_raw')))
        FROM text_native_record
        WHERE record_type='entry_medical_equipment' AND event_date<?
        GROUP BY event_date,event_number,horse_number
        ORDER BY event_date,event_number,horse_number
        """,
        (EVENT_CUTOFF_COMPACT,),
    )
    counts["entry_equipment"] = insert_many(
        target,
        """
        INSERT OR IGNORE INTO entry_equipment(
          horse_id,meet_code,race_date_local,race_number,horse_number,equipment_raw,observed_at_ms
        ) VALUES(?,?,?,?,?,?,?)
        """,
        (
            (
                maps["horse"].get(str(r[3])) if r[3] else None,
                2,
                compact_to_iso(r[0]),
                r[1],
                r[2],
                r[4],
                observed_ms,
            )
            for r in equipment_rows
        ),
    )
    target.commit()
    return counts


def load_jeju_supplementals(
    target: sqlite3.Connection, source: sqlite3.Connection, observed_ms: int
) -> dict[str, int]:
    counts: dict[str, int] = {}
    maps = operational_maps(target)
    jockey_by_name: dict[str, str] = {}
    for kra_id, name in target.execute("SELECT kra_jockey_id,name_ko FROM jockeys"):
        if name and name not in jockey_by_name:
            jockey_by_name[name] = kra_id
        elif name:
            jockey_by_name[name] = ""
    changes = []
    for date, race_no, horse_no, hr_no, payload in source.execute(
        """SELECT event_date,event_number,horse_number,hr_no,parsed_json
        FROM text_native_record WHERE record_type='jockey_change' AND event_date<?
        ORDER BY event_date,event_number,horse_number""",
        (EVENT_CUTOFF_COMPACT,),
    ):
        raw = parse_json(payload)
        before_name = raw.get("previous_jockey_name")
        after_name = raw.get("new_jockey_name")
        before_id = jockey_by_name.get(before_name) or None
        after_id = jockey_by_name.get(after_name) or None
        changes.append(
            (
                maps["horse"].get(str(hr_no)) if hr_no else None,
                2,
                compact_to_iso(date),
                race_no,
                horse_no,
                before_id,
                before_name,
                after_id,
                after_name,
                raw.get("burden_weight_kg"),
                raw.get("burden_weight_kg"),
                raw.get("reason"),
                observed_ms,
            )
        )
    counts["jockey_changes"] = insert_many(
        target,
        """
        INSERT OR IGNORE INTO jockey_changes(
          horse_id,meet_code,race_date_local,race_number,horse_number,jockey_before_id,
          jockey_before_name,jockey_after_id,jockey_after_name,carried_weight_before_kg,
          carried_weight_after_kg,reason,observed_at_ms
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        changes,
    )
    scratch_rows = []
    for date, race_no, horse_no, hr_no, payload in source.execute(
        """SELECT event_date,event_number,horse_number,hr_no,parsed_json
        FROM text_native_record WHERE record_type='race_cancellation' AND event_date<?
        ORDER BY event_date,event_number,horse_number""",
        (EVENT_CUTOFF_COMPACT,),
    ):
        raw = parse_json(payload)
        scratch_rows.append(
            (
                maps["horse"].get(str(hr_no)) if hr_no else None,
                2,
                compact_to_iso(date),
                race_no,
                horse_no,
                raw.get("detail_raw"),
                observed_ms,
            )
        )
    counts["race_scratches"] = insert_many(
        target,
        """
        INSERT OR IGNORE INTO race_scratches(
          horse_id,meet_code,race_date_local,race_number,horse_number,reason,observed_at_ms
        ) VALUES(?,?,?,?,?,?,?)
        """,
        scratch_rows,
    )
    target.commit()
    return counts


def load_jeju_trials(
    target: sqlite3.Connection, source: sqlite3.Connection, observed_ms: int
) -> dict[str, int]:
    counts: dict[str, int] = {}
    maps = operational_maps(target)
    rows = source.execute(
        """
        SELECT event_date,event_number,trial_round,distance_m,weather,track_condition,
               track_moisture_percent
        FROM event WHERE event_type='trial' AND event_date<?
        ORDER BY event_date,event_number
        """,
        (EVENT_CUTOFF_COMPACT,),
    )
    counts["running_trials"] = insert_many(
        target,
        """
        INSERT OR IGNORE INTO running_trials(
          meet_code,trial_date_local,trial_race_number,trial_round,distance_m,weather,
          track_condition,track_moisture_percent,observed_at_ms
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        ((2, compact_to_iso(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], observed_ms) for r in rows),
    )
    target.commit()
    trial_map = dict(
        target.execute(
            """SELECT trial_date_local||':'||trial_race_number,id FROM running_trials
            WHERE meet_code=2 AND trial_date_local<?""",
            (EVENT_CUTOFF_ISO,),
        )
    )
    result_rows = source.execute(
        """
        SELECT v.event_date,v.event_number,e.horse_number,e.hr_no,e.horse_name,e.finish_position,
               e.finish_time_ms,s.normalized_json
        FROM entry e JOIN event v ON v.id=e.event_id JOIN source_row s ON s.id=e.source_row_id
        WHERE v.event_type='trial' AND v.event_date<?
        ORDER BY v.event_date,v.event_number,e.horse_number
        """,
        (EVENT_CUTOFF_COMPACT,),
    )

    def mapped_results() -> Iterator[Sequence[Any]]:
        for row in result_rows:
            trial_id = trial_map.get(f"{compact_to_iso(row[0])}:{row[1]}")
            if trial_id is None:
                continue
            raw = parse_json(row[7]).get("trial_result") or {}
            yield (
                trial_id,
                maps["horse"].get(str(row[3])),
                row[2],
                row[4],
                positive_int(row[5]),
                raw.get("finish_rank_raw"),
                raw.get("origin_country"),
                raw.get("sex"),
                raw.get("age"),
                raw.get("carried_weight_base_kg"),
                raw.get("carried_weight_extra_kg"),
                raw.get("carried_weight_raw"),
                raw.get("jockey_name"),
                raw.get("trainer_name"),
                raw.get("body_weight_kg"),
                positive_int(row[6]),
                raw.get("margin_text"),
                raw.get("judgement"),
                raw.get("failure_reason"),
                raw.get("inspection_reason"),
                positive_int(raw.get("g3f_ms")),
                positive_int(raw.get("s1f_ms")),
                positive_int(raw.get("corner_3_ms")),
                positive_int(raw.get("corner_4_ms")),
                positive_int(raw.get("g1f_ms")),
                positive_int(raw.get("section_400_ms")),
                positive_int(raw.get("final_400_ms")),
                raw.get("passing_order_raw"),
                observed_ms,
            )

    counts["running_trial_results"] = insert_many(
        target,
        """
        INSERT OR IGNORE INTO running_trial_results(
          running_trial_id,horse_id,horse_number,horse_name_raw,finish_position,finish_rank_raw,
          origin_country,sex,age,carried_weight_base_kg,carried_weight_extra_kg,
          carried_weight_raw,jockey_name_raw,trainer_name_raw,body_weight_kg,finish_time_ms,
          margin_text,judgement,failure_reason,inspection_reason,g3f_ms,s1f_ms,corner_3_ms,
          corner_4_ms,g1f_ms,section_400_ms,final_400_ms,passing_order_raw,observed_at_ms
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        mapped_results(),
    )
    target.commit()
    return counts


def validate_target(connection: sqlite3.Connection) -> dict[str, Any]:
    datasets = {
        "races": ("race_date_local",),
        "horse_training": ("training_date_local",),
        "horse_start_training": ("training_date_local",),
        "horse_medical": ("clinic_date_local",),
        "horse_weight_history": ("race_date_local",),
        "entry_equipment": ("race_date_local",),
        "running_trials": ("trial_date_local",),
    }
    ranges = {}
    for table, (date_column,) in datasets.items():
        ranges[table] = connection.execute(
            f"SELECT count(*),min({date_column}),max({date_column}) FROM {table}"
        ).fetchone()
    fk = connection.execute("PRAGMA foreign_key_check").fetchall()
    return {"foreign_key_violations": len(fk), "ranges": ranges}


def dry_run_counts(thoroughbred: Path, jeju: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"cutoffs": {"race": RACE_CUTOFF_ISO, "event": EVENT_CUTOFF_ISO}}
    t = duckdb.connect(str(thoroughbred), read_only=True)

    def duck_count(query: str) -> int:
        return int(t.execute(query).fetchone()[0])

    result["thoroughbred"] = {
        "races": duck_count(
            f"""
            SELECT count(*) FROM race
            WHERE race_date<DATE '{RACE_CUTOFF_ISO}'
              AND venue_code IN ('SEOUL','BUSAN')
            """
        ),
        "entries": duck_count(
            f"""
            SELECT count(*) FROM entry_result
            WHERE race_date<DATE '{RACE_CUTOFF_ISO}'
              AND venue_code IN ('SEOUL','BUSAN')
            """
        ),
        "sections": duck_count(
            f"""
            SELECT count(*) FROM section
            WHERE race_date<DATE '{RACE_CUTOFF_ISO}'
              AND venue_code IN ('SEOUL','BUSAN')
            """
        ),
        "training": duck_count(
            f"""
            SELECT count(*) FROM training_event
            WHERE source_type='horse_training'
              AND event_date<DATE '{EVENT_CUTOFF_ISO}'
            """
        ),
        "start_training": duck_count(
            f"""
            SELECT count(*) FROM training_event
            WHERE source_type='start_training'
              AND event_date<DATE '{EVENT_CUTOFF_ISO}'
            """
        ),
        "medical_confirmed": duck_count(
            f"""
            SELECT count(*) FROM medical_event
            WHERE event_date<DATE '{EVENT_CUTOFF_ISO}'
              AND link_status IN ('confirmed','confirmed_official_id')
            """
        ),
        "weight_confirmed": duck_count(
            f"""
            SELECT count(*) FROM weight_event
            WHERE race_date<DATE '{EVENT_CUTOFF_ISO}'
              AND link_status LIKE 'confirmed%'
            """
        ),
        "equipment_confirmed": duck_count(
            f"""
            SELECT count(*) FROM equipment_event
            WHERE race_date<DATE '{EVENT_CUTOFF_ISO}'
              AND link_status LIKE 'confirmed%'
            """
        ),
        "trials_confirmed": duck_count(
            f"""
            SELECT count(*) FROM trial_entry
            WHERE trial_date<DATE '{EVENT_CUTOFF_ISO}'
              AND horse_link_status IN {
                (
                    "('confirmed','linked_profile_signature',"
                    "'linked_race_age_corroborated',"
                    "'linked_training_date_corroborated',"
                    "'linked_training_disambiguated')"
                )
            }
            """
        ),
    }
    t.close()
    j = sqlite3.connect(f"file:{jeju}?mode=ro", uri=True)

    def sqlite_count(query: str, cutoff: str) -> int:
        return int(j.execute(query, (cutoff,)).fetchone()[0])

    result["jeju"] = {
        "races": sqlite_count(
            "SELECT count(*) FROM event WHERE event_type='race' AND event_date<?",
            RACE_CUTOFF_COMPACT,
        ),
        "entries": sqlite_count(
            """
            SELECT count(*) FROM entry e JOIN event v ON v.id=e.event_id
            WHERE v.event_type='race' AND v.event_date<?
            """,
            RACE_CUTOFF_COMPACT,
        ),
        "sections": sqlite_count(
            """
            SELECT count(*) FROM section_checkpoint c
            JOIN entry e ON e.id=c.entry_id JOIN event v ON v.id=e.event_id
            WHERE v.event_type='race' AND v.event_date<?
            """,
            RACE_CUTOFF_COMPACT,
        ),
        "training": sqlite_count(
            "SELECT count(*) FROM daily_training_record WHERE event_date<?",
            EVENT_CUTOFF_COMPACT,
        ),
        "start_training": sqlite_count(
            """
            SELECT count(*) FROM start_training_record
            WHERE event_date<? AND duplicate_status='first_occurrence'
            """,
            EVENT_CUTOFF_COMPACT,
        ),
        "medical": sqlite_count(
            """
            SELECT count(*) FROM medical_record
            WHERE event_date<? AND duplicate_status='first_occurrence'
            """,
            EVENT_CUTOFF_COMPACT,
        ),
        "weight": sqlite_count(
            "SELECT count(*) FROM measured_weight_record WHERE race_date<?",
            EVENT_CUTOFF_COMPACT,
        ),
        "trials": sqlite_count(
            """
            SELECT count(*) FROM entry e JOIN event v ON v.id=e.event_id
            WHERE v.event_type='trial' AND v.event_date<?
            """,
            EVENT_CUTOFF_COMPACT,
        ),
    }
    j.close()
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    database = args.database.resolve()
    thoroughbred = args.thoroughbred.resolve()
    jeju = args.jeju.resolve()
    for path in (database, thoroughbred, jeju):
        if not path.exists():
            raise FileNotFoundError(path)
    dry_counts = dry_run_counts(thoroughbred, jeju)
    if args.dry_run:
        return {"mode": "dry-run", "source_counts": dry_counts}

    target = sqlite3.connect(database, timeout=60)
    target.execute("PRAGMA foreign_keys=ON")
    target.execute("PRAGMA journal_mode=WAL")
    target.execute("PRAGMA synchronous=NORMAL")
    target.execute("PRAGMA busy_timeout=60000")
    target.execute("PRAGMA cache_size=-262144")
    observed_ms = now_ms()
    output: dict[str, Any] = {"mode": "apply", "source_counts": dry_counts, "written": {}}
    try:
        source_hash = sha256_file(thoroughbred)
        batch_key = "thoroughbred-history-v1"
        if should_skip_completed_batch(target, batch_key, source_hash):
            output["written"]["thoroughbred"] = {"skipped_completed_batch": 1}
        else:
            batch_id = begin_batch(
                target, batch_key, "thoroughbred_unified", thoroughbred, source_hash
            )
            target.commit()
            counts: dict[str, int] = {}
            source = duckdb.connect(str(thoroughbred), read_only=True)
            try:
                for loader in (load_thoroughbred_races,):
                    for key, value in loader(target, source).items():
                        counts[key] = counts.get(key, 0) + value
                for loader in (load_thoroughbred_history, load_thoroughbred_trials):
                    for key, value in loader(target, source, observed_ms).items():
                        counts[key] = counts.get(key, 0) + value
            finally:
                source.close()
            validation = validate_target(target)
            update_batch(target, batch_id, "completed", counts, validation)
            target.commit()
            target.execute("PRAGMA wal_checkpoint(PASSIVE)")
            output["written"]["thoroughbred"] = counts

        source_hash = sha256_file(jeju)
        batch_key = "jeju-history-v1"
        if should_skip_completed_batch(target, batch_key, source_hash):
            output["written"]["jeju"] = {"skipped_completed_batch": 1}
        else:
            batch_id = begin_batch(target, batch_key, "jeju_native_text_phase2", jeju, source_hash)
            target.commit()
            counts = {}
            source_sqlite = sqlite3.connect(f"file:{jeju}?mode=ro", uri=True)
            try:
                for loader in (load_jeju_people_and_races,):
                    for key, value in loader(target, source_sqlite).items():
                        counts[key] = counts.get(key, 0) + value
                for loader in (load_jeju_history, load_jeju_supplementals, load_jeju_trials):
                    for key, value in loader(target, source_sqlite, observed_ms).items():
                        counts[key] = counts.get(key, 0) + value
            finally:
                source_sqlite.close()
            validation = validate_target(target)
            update_batch(target, batch_id, "completed", counts, validation)
            target.commit()
            target.execute("PRAGMA wal_checkpoint(PASSIVE)")
            output["written"]["jeju"] = counts
        output["validation"] = validate_target(target)
        return output
    except Exception:
        target.rollback()
        raise
    finally:
        target.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--thoroughbred", type=Path, default=DEFAULT_THOROUGHBRED)
    parser.add_argument("--jeju", type=Path, default=DEFAULT_JEJU)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
