#!/usr/bin/env python3
"""Build the frozen, read-only population flags for the 2026-10-22 comparison.

Run from any working directory with:
    .venv/bin/python thoroughbred/research/20261022_probability_comparison_v1/audit_population.py

The script reads the 2026-09-29 normalized DuckDB snapshot with read_only=True,
joins the already-stored full103 evaluation rows, and writes only
outputs/population_flags.parquet. It does not collect data, train models, or
write to either DuckDB file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs" / "population_flags.parquet"
PREDICTIONS = (
    ROOT
    / "thoroughbred/research/20261009_gate_front_late_v1/outputs/runner_predictions.parquet"
)
FEATURES = ROOT / "thoroughbred/research/20261009_gate_front_late_v1/outputs/features.parquet"
UPSTREAM_MANIFEST = (
    ROOT / "thoroughbred/research/20261009_gate_front_late_v1/outputs/input_manifest.json"
)
DATASET_DB = ROOT / "thoroughbred/data/dataset_20260929_v1/thoroughbred.duckdb"
DATASET_VALIDATION = ROOT / "thoroughbred/data/dataset_20260929_v1/validation.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dataset_projection_hash(con: duckdb.DuckDBPyConnection) -> str:
    """Hash the source rows used by the output, in deterministic key order."""
    query = f"""
        SELECT
            p.race_key,
            p.program_no,
            p.horse_id,
            e.finish_raw,
            e.finish_order,
            e.result_status,
            e.race_time_s,
            e.official_result_state,
            e.is_dead_heat,
            e.is_model_target,
            e.is_rank_label,
            e.source_dataset
        FROM read_parquet('{PREDICTIONS.as_posix()}') AS p
        JOIN entry_result AS e
          ON p.meet = e.canonical_meet
         AND CAST(p.race_date AS DATE) = e.race_date
         AND p.program_no = e.chul_no
         AND p.horse_id = e.hr_no
         AND p.race_key = CAST(p.meet AS VARCHAR) || ':'
                          || strftime(e.race_date, '%Y%m%d') || ':'
                          || CAST(e.race_no AS VARCHAR)
        WHERE p.target = 3 AND p.variant = 'full103'
        ORDER BY p.race_key, p.program_no, p.horse_id
    """
    digest = hashlib.sha256()
    for row in con.execute(query).fetchall():
        encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str)
        digest.update(encoded.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def build(*, force: bool = False) -> dict:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite existing artifact: {OUT}; pass --force")
    for path in (PREDICTIONS, FEATURES, UPSTREAM_MANIFEST, DATASET_DB, DATASET_VALIDATION):
        if not path.is_file():
            raise FileNotFoundError(path)

    con = duckdb.connect(str(DATASET_DB), read_only=True)
    try:
        input_relation = f"read_parquet('{PREDICTIONS.as_posix()}')"
        feature_relation = f"read_parquet('{FEATURES.as_posix()}')"
        output_query = f"""
            WITH pred AS (
                SELECT
                    race_key,
                    CAST(program_no AS INTEGER) AS program_no,
                    horse_id,
                    CAST(meet AS INTEGER) AS meet,
                    CAST(race_date AS DATE) AS race_date,
                    CAST(year AS INTEGER) AS year,
                    CAST(outcome AS INTEGER) AS candidate_outcome,
                    CAST(raw_score AS DOUBLE) AS raw_score
                FROM {input_relation}
                WHERE target = 3 AND variant = 'full103'
            ),
            joined AS (
                SELECT
                    p.race_key,
                    p.program_no,
                    p.horse_id,
                    p.meet,
                    p.race_date,
                    p.year,
                    p.candidate_outcome,
                    p.raw_score,
                    e.finish_raw,
                    e.finish_order,
                    e.result_status,
                    e.race_time_s,
                    e.official_result_state,
                    COALESCE(e.is_dead_heat, FALSE) AS is_dead_heat,
                    e.is_model_target,
                    e.is_rank_label,
                    e.source_dataset,
                    CASE
                        WHEN e.result_status = 'finished'
                         AND e.finish_order BETWEEN 1 AND 16
                         AND e.race_time_s > 0
                        THEN TRUE ELSE FALSE
                    END AS normal_finisher,
                    CASE
                        WHEN e.result_status IN (
                            'special_result', 'unmapped_special_98', 'void_or_unresulted'
                        ) OR e.official_result_state = 'special_only_unresolved'
                        THEN TRUE ELSE FALSE
                    END AS ambiguous_flag
                FROM pred AS p
                LEFT JOIN entry_result AS e
                  ON p.meet = e.canonical_meet
                 AND p.race_date = e.race_date
                 AND p.program_no = e.chul_no
                 AND p.horse_id = e.hr_no
                 AND p.race_key = CAST(p.meet AS VARCHAR) || ':'
                                  || strftime(e.race_date, '%Y%m%d') || ':'
                                  || CAST(e.race_no AS VARCHAR)
            )
            SELECT * FROM joined
        """

        row_count = con.execute(f"SELECT count(*) FROM ({output_query})").fetchone()[0]
        unmatched = con.execute(
            f"SELECT count(*) FROM ({output_query}) WHERE result_status IS NULL"
        ).fetchone()[0]
        key_duplicates = con.execute(
            f"""
            SELECT count(*) FROM (
                SELECT race_key, program_no, horse_id, count(*) AS n
                FROM ({output_query})
                GROUP BY ALL HAVING count(*) > 1
            )
            """
        ).fetchone()[0]
        if row_count != 50_754 or unmatched != 0 or key_duplicates != 0:
            raise AssertionError(
                f"Unexpected population: rows={row_count}, unmatched={unmatched}, "
                f"duplicate_keys={key_duplicates}"
            )

        output_sql_path = OUT.as_posix().replace("'", "''")
        con.execute(
            f"COPY ({output_query}) TO '{output_sql_path}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 15)"
        )
        if OUT.stat().st_size > 1_000_000:
            OUT.unlink()
            raise AssertionError("population_flags.parquet exceeds the 1 MB artifact limit")

        status_counts = con.execute(
            f"""
            SELECT meet, result_status, finish_raw, official_result_state, count(*) AS n
            FROM read_parquet('{OUT.as_posix()}')
            GROUP BY ALL
            ORDER BY meet, result_status, finish_raw, official_result_state
            """
        ).fetchall()
        flag_counts = con.execute(
            f"""
            SELECT
                count(*) AS rows,
                count(DISTINCT race_key) AS races,
                count(*) FILTER (WHERE normal_finisher) AS normal_finisher_rows,
                count(*) FILTER (WHERE ambiguous_flag) AS ambiguous_rows,
                count(DISTINCT race_key) FILTER (WHERE ambiguous_flag) AS ambiguous_races,
                count(*) FILTER (WHERE NOT normal_finisher AND NOT ambiguous_flag) AS known_nonfinisher_rows
            FROM read_parquet('{OUT.as_posix()}')
            """
        ).fetchone()
        status_hash = dataset_projection_hash(con)
    finally:
        con.close()

    stat = DATASET_DB.stat()
    metadata = {
        "artifact": str(OUT.relative_to(ROOT)),
        "artifact_sha256": sha256(OUT),
        "artifact_bytes": OUT.stat().st_size,
        "schema": [
            "race_key", "program_no", "horse_id", "meet", "race_date", "year",
            "candidate_outcome", "raw_score", "finish_raw", "finish_order",
            "result_status", "race_time_s", "official_result_state", "is_dead_heat",
            "is_model_target", "is_rank_label", "source_dataset", "normal_finisher",
            "ambiguous_flag",
        ],
        "population": {
            "rows": flag_counts[0],
            "races": flag_counts[1],
            "normal_finisher_rows": flag_counts[2],
            "ambiguous_rows": flag_counts[3],
            "ambiguous_races": flag_counts[4],
            "known_nonfinisher_rows": flag_counts[5],
            "status_counts": [
                {
                    "meet": row[0], "result_status": row[1], "finish_raw": row[2],
                    "official_result_state": row[3], "rows": row[4],
                }
                for row in status_counts
            ],
        },
        "join": {
            "keys": ["race_key", "program_no", "horse_id"],
            "rows": row_count,
            "unmatched": unmatched,
            "duplicate_keys": key_duplicates,
            "left_dataset_join": "candidate predictions to entry_result by meet/date/race_no/chul_no/hr_no and exact race_key",
        },
        "normal_finisher_rule": "result_status == finished AND finish_order in 1..16 AND race_time_s > 0",
        "ambiguous_rule": "special_result, unmapped_special_98, void_or_unresulted, or official_result_state == special_only_unresolved",
        "sources": {
            "predictions": {
                "path": str(PREDICTIONS.relative_to(ROOT)),
                "sha256": sha256(PREDICTIONS),
                "bytes": PREDICTIONS.stat().st_size,
            },
            "features": {
                "path": str(FEATURES.relative_to(ROOT)),
                "sha256": sha256(FEATURES),
                "bytes": FEATURES.stat().st_size,
            },
            "upstream_input_manifest": {
                "path": str(UPSTREAM_MANIFEST.relative_to(ROOT)),
                "sha256": sha256(UPSTREAM_MANIFEST),
                "bytes": UPSTREAM_MANIFEST.stat().st_size,
            },
            "normalized_dataset": {
                "path": str(DATASET_DB.relative_to(ROOT)),
                "read_only": True,
                "bytes": stat.st_size,
                "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "validation_path": str(DATASET_VALIDATION.relative_to(ROOT)),
                "validation_sha256": sha256(DATASET_VALIDATION),
                "joined_projection_sha256": status_hash,
            },
        },
    }
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="replace the generated flags file")
    args = parser.parse_args()
    print(json.dumps(build(force=args.force), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
