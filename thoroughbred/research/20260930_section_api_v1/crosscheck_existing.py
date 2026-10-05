#!/usr/bin/env python3
"""Independent value check against the older Busan API-derived snapshot."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
API = ROOT / "thoroughbred/data/section_api_2010_20260929_v1/section_measurements.parquet"
OLDER = ROOT / "thoroughbred/data/section_passing_raw_2010plus_20260929_v1/parquet/spdb_section_time.parquet"


def main() -> None:
    db = duckdb.connect()
    row = db.execute("""
        WITH old AS (
            SELECT id, meet_code, replace(race_date, '-', '') AS race_date,
                   race_number, kra_horse_id, source_field, elapsed_time_ms
            FROM read_parquet(?)
            WHERE source_name='busan_research' AND source_field LIKE 'bu%'
        ), api AS (
            SELECT meet, race_date, race_no, horse_id, source_field, time_ms
            FROM read_parquet(?) WHERE meet IN (3,4) AND time_ms IS NOT NULL
        )
        SELECT count(*) AS older_rows,
               count(api.time_ms) AS joined_rows,
               count(*) FILTER (WHERE api.time_ms IS NULL) AS unmatched_rows,
               count(*) FILTER (WHERE api.time_ms IS NOT NULL
                                AND api.time_ms<>old.elapsed_time_ms) AS time_mismatches
        FROM old LEFT JOIN api ON old.meet_code=api.meet
          AND old.race_date=api.race_date AND old.race_number=api.race_no
          AND old.kra_horse_id=api.horse_id AND old.source_field=api.source_field
    """, [str(OLDER), str(API)]).fetchone()
    db.close()
    summary = dict(zip(("older_rows", "joined_rows", "unmatched_rows", "time_mismatches"), row))
    if summary != {"older_rows": 1_433_221, "joined_rows": 1_433_221,
                   "unmatched_rows": 0, "time_mismatches": 0}:
        raise ValueError(f"API section crosscheck failed: {summary}")
    (HERE / "crosscheck_existing.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
