"""Correct live H2 state features from fresh, result-free official sources."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl


def _day(value: Any) -> date:
    text = str(value)
    return datetime.strptime(text[:8], "%Y%m%d").date()


def _horse_id(value: Any) -> str:
    return str(value).strip().zfill(7)


def _items(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    container = payload["response"]["body"].get("items") or {}
    value = container.get("item") if isinstance(container, dict) else None
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else []


def _all_items(root: Path, prefix: str) -> list[dict]:
    rows: list[dict] = []
    paths = sorted(root.glob(f"{prefix}_page_*.json"))
    if not paths:
        raise FileNotFoundError(f"No official pages for {prefix}: {root}")
    for path in paths:
        rows.extend(_items(path))
    return rows


def _database_earlier_month_rows(
    database: Path,
    horse_ids: list[str],
    low: date,
    high: date,
) -> tuple[list[dict], list[dict]]:
    placeholders = ",".join("?" for _ in horse_ids)
    params = [*horse_ids, low.strftime("%Y%m%d"), high.strftime("%Y%m%d")]
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        training = [
            dict(row)
            for row in connection.execute(
                f"""
                SELECT hr_no,event_date,training_duration_seconds,canter_count,gallop_count
                FROM daily_training_record
                WHERE meet=2 AND hr_no IN ({placeholders})
                  AND event_date BETWEEN ? AND ?
                """,
                params,
            )
        ]
        start = [
            dict(row)
            for row in connection.execute(
                f"""
                SELECT hr_no,event_date,horse_name,exercise_person_name,remark,part,part_no
                FROM analysis_start_training_distinct
                WHERE meet=2 AND hr_no IN ({placeholders})
                  AND event_date BETWEEN ? AND ?
                """,
                params,
            )
        ]
    finally:
        connection.close()
    return training, start


def corrected_h2(
    *,
    official_root: Path,
    database: Path,
    horse_ids: list[str],
    target_date: date,
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Return corrected training/start-training/medical features at the fixed T-2 cutoff."""
    ids = {_horse_id(value) for value in horse_ids}
    high = target_date - timedelta(days=2)
    training_low = target_date - timedelta(days=29)
    medical_low = target_date - timedelta(days=91)
    month_start = high.replace(day=1)
    prior_training, prior_start = _database_earlier_month_rows(
        database, sorted(ids), training_low, month_start - timedelta(days=1)
    )

    fresh_training = [
        row
        for row in _all_items(official_root, "training_month")
        if _horse_id(row.get("hrNo")) in ids
        and training_low <= _day(row["trDate"]) <= high
    ]
    fresh_start = [
        row
        for row in _all_items(official_root, "start_training_month")
        if _horse_id(row.get("hrNo")) in ids
        and training_low <= _day(row["trDate"]) <= high
    ]
    fresh_medical = [
        row
        for row in _all_items(official_root, "medical_year")
        if _horse_id(row.get("hrNo")) in ids
        and medical_low <= _day(row["clinicDate"]) <= high
    ]

    training_by_horse: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    for row in prior_training:
        training_by_horse[_horse_id(row["hr_no"])].append(
            (
                int(row.get("training_duration_seconds") or 0),
                int(row.get("canter_count") or 0),
                int(row.get("gallop_count") or 0),
            )
        )
    seen_training: set[tuple[Any, ...]] = set()
    for row in fresh_training:
        key = (
            _horse_id(row.get("hrNo")),
            str(row.get("trDate")),
            str(row.get("stTime")),
            str(row.get("spTime")),
            str(row.get("part")),
            str(row.get("partNo")),
            str(row.get("prNo")),
        )
        if key in seen_training:
            continue
        seen_training.add(key)
        training_by_horse[key[0]].append(
            (
                int(row.get("trTerm") or 0),
                int(row.get("run1Cnt") or 0),
                int(row.get("run2Cnt") or 0),
            )
        )

    start_by_horse: dict[str, int] = defaultdict(int)
    for row in prior_start:
        start_by_horse[_horse_id(row["hr_no"])] += 1
    seen_start: set[tuple[Any, ...]] = set()
    for row in fresh_start:
        key = tuple(
            str(row.get(field) or "")
            for field in ("hrNo", "trDate", "part", "partNo", "prName", "remark")
        )
        if key in seen_start:
            continue
        seen_start.add(key)
        start_by_horse[_horse_id(row.get("hrNo"))] += 1

    medical_by_horse: dict[str, int] = defaultdict(int)
    seen_medical: set[tuple[Any, ...]] = set()
    for row in fresh_medical:
        key = tuple(
            str(row.get(field) or "")
            for field in (
                "hrNo",
                "clinicDate",
                "hospiName",
                "illName1",
                "illName2",
                "part",
            )
        )
        if key in seen_medical:
            continue
        seen_medical.add(key)
        medical_by_horse[_horse_id(row.get("hrNo"))] += 1

    rows = []
    for horse_id in sorted(ids):
        training = training_by_horse.get(horse_id, [])
        start_count = start_by_horse.get(horse_id, 0)
        medical_count = medical_by_horse.get(horse_id, 0)
        rows.append(
            {
                "horse_id": horse_id,
                "training_28d_count": len(training),
                "training_28d_duration_seconds": sum(value[0] for value in training),
                "training_28d_canter_count": sum(value[1] for value in training),
                "training_28d_gallop_count": sum(value[2] for value in training),
                "training_28d_coverage_unknown": 1,
                "training_28d_observed_any": int(bool(training)),
                "start_training_28d_count": start_count,
                "start_training_28d_coverage_unknown": 1,
                "start_training_28d_observed_any": int(start_count > 0),
                "medical_90d_count": medical_count,
                "medical_90d_coverage_unknown": 1,
                "medical_90d_observed_any": int(medical_count > 0),
            }
        )
    metadata = {
        "cutoff_date": high.isoformat(),
        "training_window": [training_low.isoformat(), high.isoformat()],
        "medical_window": [medical_low.isoformat(), high.isoformat()],
        "fresh_training_rows_for_card": len(fresh_training),
        "fresh_start_training_rows_for_card": len(fresh_start),
        "fresh_medical_rows_for_card": len(fresh_medical),
        "prior_month_training_rows_for_card": len(prior_training),
        "prior_month_start_training_rows_for_card": len(prior_start),
        "result_endpoints_called": [],
    }
    return pl.DataFrame(rows, infer_schema_length=None), metadata


def overlay_h2(states: pl.DataFrame, corrected: pl.DataFrame) -> pl.DataFrame:
    feature_columns = [column for column in corrected.columns if column != "horse_id"]
    renamed = corrected.rename({column: f"{column}__fresh" for column in feature_columns})
    joined = states.join(renamed, on="horse_id", validate="m:1")
    return joined.with_columns(
        [pl.col(f"{column}__fresh").alias(column) for column in feature_columns]
    ).drop([f"{column}__fresh" for column in feature_columns])
