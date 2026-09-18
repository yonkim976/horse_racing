"""Read verified historical evidence without modifying the operational database.

The optional local archive contains older Jeju races and trials. Its identifiers
have a separate namespace: callers merge rows by official horse ID and event
date/number, never by ``archive_entry_id``.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
from datetime import date
from pathlib import Path

LOGGER = logging.getLogger(__name__)
DEFAULT_ARCHIVE_DB = (
    Path(__file__).resolve().parents[3]
    / "data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3"
)
SOURCE_LABEL = "검증된 제주 공식 과거자료"
MAX_HORSES = 64
MAX_HISTORY = 500


def load_verified_archive(
    horse_kra_ids: list[str],
    before: date,
    *,
    db_path: Path | None = None,
    limit_per_horse: int = 60,
) -> dict[str, dict[str, object]]:
    """Return bounded race/trial evidence strictly before the selected race day.

    Limits apply separately to each horse's races and trials. ``race_total`` and
    ``trial_total`` include all verified rows before the cutoff, allowing callers
    to distinguish a truncated list from a horse with no older evidence. This is
    an optional archive: a missing file returns an empty mapping. Invalid/corrupt
    databases also return an empty mapping, with a warning that contains no path
    or source payload. Environment overrides are server configuration only.
    """
    if not 1 <= limit_per_horse <= MAX_HISTORY:
        raise ValueError(f"limit_per_horse must be between 1 and {MAX_HISTORY}")
    horse_ids = sorted(
        {
            str(value).zfill(7)
            for value in horse_kra_ids
            if re.fullmatch(r"[0-9]{1,7}", str(value))
        }
    )
    if not horse_ids:
        return {}
    if len(horse_ids) > MAX_HORSES:
        raise ValueError(f"At most {MAX_HORSES} horses may be loaded at once")
    configured = os.environ.get("HORSE_RACING_ANALYSIS_ARCHIVE_DB")
    path = (
        db_path if db_path is not None else Path(configured) if configured else DEFAULT_ARCHIVE_DB
    )
    try:
        if not path.is_file():
            return {}
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        try:
            return _load(connection, horse_ids, before, limit_per_horse)
        finally:
            connection.close()
    except (sqlite3.Error, OSError) as error:
        LOGGER.warning("Verified analysis archive unavailable (%s)", type(error).__name__)
        return {}


def _load(
    connection: sqlite3.Connection,
    horse_ids: list[str],
    before: date,
    limit: int,
) -> dict[str, dict[str, object]]:
    placeholders = ",".join("?" for _ in horse_ids)
    rows = connection.execute(
        f"""
        WITH ranked AS (
          SELECT e.id AS archive_entry_id,e.hr_no,e.horse_number,e.horse_name,
            e.finish_position,e.finish_time_ms,e.record_status,e.segment_quality,
            e.time_analysis_eligible,e.identity_status,e.source_row_id,e.event_id,
            v.event_type,v.event_date,v.event_number,v.trial_round,v.meet,
            v.distance_m,v.grade,v.weather,v.track_condition,v.track_moisture_percent,
            ROW_NUMBER() OVER (
              PARTITION BY e.hr_no,v.event_type
              ORDER BY v.event_date DESC,v.event_number DESC,e.id DESC
            ) AS row_number,
            COUNT(*) OVER (PARTITION BY e.hr_no,v.event_type) AS total_count
          FROM entry e JOIN event v ON v.id=e.event_id
          WHERE e.hr_no IN ({placeholders}) AND v.meet=2 AND v.event_date<?
            AND e.record_status IN ('normal_completed','non_positive_result_entry')
            AND (
              (v.event_type='race' AND e.identity_status='official_race_ids_linked'
                AND v.population_status='confirmed_native_normal_race')
              OR (v.event_type='trial' AND e.identity_status='official_trial_hr_tr_linked'
                AND v.population_status='native_confirmed_trial')
            )
        )
        SELECT ranked.*,
          (SELECT COUNT(*) FROM entry peers WHERE peers.event_id=ranked.event_id) AS field_size,
          s.normalized_json
        FROM ranked LEFT JOIN source_row s ON s.id=ranked.source_row_id
        WHERE row_number<=?
        ORDER BY hr_no,event_type,event_date DESC,event_number DESC,archive_entry_id DESC
        """,
        [*horse_ids, before.strftime("%Y%m%d"), limit],
    ).fetchall()
    result: dict[str, dict[str, object]] = {}
    records: dict[int, dict[str, object]] = {}
    for row in rows:
        try:
            event_day = date.fromisoformat(row["event_date"])
        except (TypeError, ValueError):
            LOGGER.warning("Ignored verified archive row with an invalid event date")
            continue
        if event_day >= before:
            continue
        horse = result.setdefault(
            row["hr_no"],
            {"races": [], "trials": [], "race_total": 0, "trial_total": 0,
             "races_truncated": False, "trials_truncated": False},
        )
        kind = row["event_type"]
        horse[f"{kind}_total"] = row["total_count"]
        horse[f"{kind}s_truncated"] = row["total_count"] > limit
        record: dict[str, object] = {
            "archive_entry_id": row["archive_entry_id"],
            "date": event_day.isoformat(),
            "meet": row["meet"],
            "event_number": row["event_number"],
            "trial_round": row["trial_round"],
            "distance": row["distance_m"],
            "grade": row["grade"],
            "weather": row["weather"],
            "track_condition": row["track_condition"],
            "track_moisture_percent": row["track_moisture_percent"],
            "field_size": row["field_size"],
            "horse_number": row["horse_number"],
            "horse_name": row["horse_name"],
            "finish_position": row["finish_position"],
            "time_ms": row["finish_time_ms"],
            "record_status": row["record_status"],
            "segment_quality": row["segment_quality"],
            "time_analysis_eligible": bool(row["time_analysis_eligible"]),
            "identity_status": row["identity_status"],
            "source_label": SOURCE_LABEL,
            "sections": {},
            **_context(row["normalized_json"]),
        }
        horse[f"{kind}s"].append(record)
        records[row["archive_entry_id"]] = record
    entry_ids = list(records)
    for offset in range(0, len(entry_ids), 400):
        batch = entry_ids[offset:offset + 400]
        section_rows = connection.execute(
            "SELECT entry_id,section_code,source_value_ms,elapsed_from_start_ms,"
            "time_basis,distance_from_start_m,distance_is_approximate,source_kind "
            "FROM section_checkpoint WHERE entry_id IN ("
            + ",".join("?" for _ in batch) + ")",
            batch,
        )
        for section in section_rows:
            records[section["entry_id"]]["sections"][section["section_code"]] = {
                "raw_ms": section["source_value_ms"],
                "elapsed_ms": section["elapsed_from_start_ms"],
                "time_basis": section["time_basis"],
                "distance_from_start_m": section["distance_from_start_m"],
                "approximate": bool(section["distance_is_approximate"]),
                "source_kind": section["source_kind"],
            }
    return result


def _context(serialized: str | None) -> dict[str, object]:
    """Return only display fields; never expose archived URLs or full source JSON."""
    try:
        payload = json.loads(serialized or "{}")
    except (ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    trial = payload.get("trial_result")
    trial = trial if isinstance(trial, dict) else {}
    weight_text = str(payload.get("wgHr", ""))
    body_weight = re.match(r"^([0-9]+)", weight_text)
    return {
        "jockey": _text(trial.get("jockey_name") or payload.get("jkName")),
        "trainer": _text(trial.get("trainer_name") or payload.get("trName")),
        "carried_weight_kg": _number(
            trial.get("carried_weight_base_kg") if trial else payload.get("wgBudam")
        ),
        "carried_weight_extra_kg": _number(trial.get("carried_weight_extra_kg")),
        "carried_weight_raw": _text(trial.get("carried_weight_raw")),
        "body_weight_kg": _number(
            trial.get("body_weight_kg") if trial else body_weight[1] if body_weight else None
        ),
        "judgement": _text(trial.get("judgement")),
        "failure_reason": _text(trial.get("failure_reason")),
        "inspection_reason": _text(trial.get("inspection_reason")),
        "passing_order": _text(trial.get("passing_order_raw")),
        "finish_rank_raw": _text(trial.get("finish_rank_raw")),
    }


def _text(value: object) -> str | None:
    return str(value)[:200] if value is not None else None


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) and number >= 0 else None
