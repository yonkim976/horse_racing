"""Archive retired Jeju Halla records to Zstd Parquet, then optionally purge them."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

SELECTION_RULE = "racecourses.kra_meet_code = 2 AND races.grade LIKE '한%'"

RACE_FILTER = "id IN (SELECT id FROM selected_halla_races)"
ENTRY_FILTER = "race_id IN (SELECT id FROM selected_halla_races)"
HORSE_FILTER = "id IN (SELECT id FROM selected_halla_horses)"
HORSE_CHILD_FILTER = "horse_id IN (SELECT id FROM selected_halla_horses)"
RACE_KEY_FILTER = """
EXISTS (
    SELECT 1
    FROM selected_halla_races r
    WHERE r.race_date_local = {table}.race_date_local
      AND r.race_number = {table}.race_number
      AND {table}.meet_code = 2
)
"""

EXPORT_QUERIES = {
    "races": f"SELECT * FROM races WHERE {RACE_FILTER}",
    "race_entries": f"SELECT * FROM race_entries WHERE {ENTRY_FILTER}",
    "race_results": """
        SELECT rr.* FROM race_results rr
        JOIN race_entries e ON e.id = rr.race_entry_id
        WHERE e.race_id IN (SELECT id FROM selected_halla_races)
    """,
    "race_section_results": """
        SELECT rs.* FROM race_section_results rs
        JOIN race_entries e ON e.id = rs.race_entry_id
        WHERE e.race_id IN (SELECT id FROM selected_halla_races)
    """,
    "odds_snapshots": (
        "SELECT * FROM odds_snapshots "
        "WHERE race_id IN (SELECT id FROM selected_halla_races)"
    ),
    "horses": f"SELECT * FROM horses WHERE {HORSE_FILTER}",
    "horse_profile_snapshots": (
        f"SELECT * FROM horse_profile_snapshots WHERE {HORSE_CHILD_FILTER}"
    ),
    "horse_rating_snapshots": (
        f"SELECT * FROM horse_rating_snapshots WHERE {HORSE_CHILD_FILTER}"
    ),
    "horse_weight_history": (
        f"SELECT * FROM horse_weight_history WHERE {HORSE_CHILD_FILTER}"
    ),
    "horse_training": f"SELECT * FROM horse_training WHERE {HORSE_CHILD_FILTER}",
    "horse_medical": f"SELECT * FROM horse_medical WHERE {HORSE_CHILD_FILTER}",
    "horse_grade_changes": (
        f"SELECT * FROM horse_grade_changes WHERE {HORSE_CHILD_FILTER}"
    ),
    "horse_start_training": (
        f"SELECT * FROM horse_start_training WHERE {HORSE_CHILD_FILTER}"
    ),
    "jockey_changes": """
        SELECT * FROM jockey_changes
        WHERE horse_id IN (SELECT id FROM selected_halla_horses)
           OR {race_key_filter}
    """.format(race_key_filter=RACE_KEY_FILTER.format(table="jockey_changes")),
    "race_scratches": """
        SELECT * FROM race_scratches
        WHERE horse_id IN (SELECT id FROM selected_halla_horses)
           OR {race_key_filter}
    """.format(race_key_filter=RACE_KEY_FILTER.format(table="race_scratches")),
    "entry_equipment": """
        SELECT * FROM entry_equipment
        WHERE horse_id IN (SELECT id FROM selected_halla_horses)
           OR {race_key_filter}
    """.format(race_key_filter=RACE_KEY_FILTER.format(table="entry_equipment")),
    "race_steward_reports": "SELECT * FROM race_steward_reports WHERE "
    + RACE_KEY_FILTER.format(table="race_steward_reports"),
    "running_trial_results": (
        f"SELECT * FROM running_trial_results WHERE {HORSE_CHILD_FILTER}"
    ),
    "model_predictions": (
        "SELECT * FROM model_predictions "
        "WHERE race_id IN (SELECT id FROM selected_halla_races)"
    ),
    "prediction_outcomes": """
        SELECT po.* FROM prediction_outcomes po
        JOIN model_predictions mp ON mp.id = po.model_prediction_id
        WHERE mp.race_id IN (SELECT id FROM selected_halla_races)
    """,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def prepare_selection(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS temp.selected_halla_races")
    conn.execute("DROP TABLE IF EXISTS temp.selected_halla_horses")
    conn.execute(
        """
        CREATE TEMP TABLE selected_halla_races AS
        SELECT r.*
        FROM races r
        JOIN racecourses c ON c.id = r.racecourse_id
        WHERE c.kra_meet_code = 2 AND r.grade LIKE '한%'
        """
    )
    conn.execute(
        """
        CREATE TEMP TABLE selected_halla_horses AS
        SELECT DISTINCT h.*
        FROM horses h
        JOIN race_entries e ON e.horse_id = h.id
        JOIN selected_halla_races r ON r.id = e.race_id
        """
    )


def selection_summary(conn: sqlite3.Connection) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT COUNT(*), MIN(race_date_local), MAX(race_date_local)
        FROM selected_halla_races
        """
    ).fetchone()
    horse_count = conn.execute("SELECT COUNT(*) FROM selected_halla_horses").fetchone()[0]
    shared_horses = conn.execute(
        """
        SELECT COUNT(DISTINCT e.horse_id)
        FROM race_entries e
        WHERE e.horse_id IN (SELECT id FROM selected_halla_horses)
          AND e.race_id NOT IN (SELECT id FROM selected_halla_races)
        """
    ).fetchone()[0]
    prediction_count = conn.execute(
        """
        SELECT COUNT(*) FROM model_predictions
        WHERE race_id IN (SELECT id FROM selected_halla_races)
        """
    ).fetchone()[0]
    return {
        "race_count": row[0],
        "first_race_date": row[1],
        "last_race_date": row[2],
        "horse_count": horse_count,
        "horses_with_non_halla_entries": shared_horses,
        "model_prediction_count": prediction_count,
    }


def write_archive(
    conn: sqlite3.Connection, database: Path, output_dir: Path
) -> dict[str, object]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Archive directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    schema_path = output_dir / "schema.sql"
    schema_rows = conn.execute(
        """
        SELECT sql FROM sqlite_master
        WHERE type = 'table' AND sql IS NOT NULL
        ORDER BY name
        """
    ).fetchall()
    schema_path.write_text(";\n\n".join(row[0] for row in schema_rows) + ";\n")

    table_manifest: dict[str, dict[str, object]] = {}
    for table, query in EXPORT_QUERIES.items():
        frame = pl.read_database(query, conn, infer_schema_length=None)
        record: dict[str, object] = {"rows": frame.height}
        if frame.height:
            destination = output_dir / f"{table}.parquet"
            frame.write_parquet(
                destination,
                compression="zstd",
                compression_level=9,
                statistics=True,
            )
            verified = pl.read_parquet(destination)
            if verified.height != frame.height or verified.columns != frame.columns:
                raise RuntimeError(f"Parquet verification failed: {table}")
            record.update(
                {
                    "file": destination.name,
                    "bytes": destination.stat().st_size,
                    "sha256": sha256(destination),
                    "columns": frame.columns,
                }
            )
        table_manifest[table] = record

    summary = selection_summary(conn)
    manifest = {
        "archive_format": "table-wise parquet",
        "compression": "zstd level 9",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source_database": str(database.resolve()),
        "selection_rule": SELECTION_RULE,
        "selection": summary,
        "tables": table_manifest,
        "schema": {
            "file": schema_path.name,
            "bytes": schema_path.stat().st_size,
            "sha256": sha256(schema_path),
        },
        "retained_in_operational_storage": [
            "source_documents and ingestion_runs (mixed-source audit metadata)",
            "shared jockey, trainer, owner, and racecourse entities",
            "immutable derived datasets and historical experiment artifacts",
        ],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def purge(conn: sqlite3.Connection, expected: dict[str, object]) -> dict[str, object]:
    current = selection_summary(conn)
    if current != expected:
        raise RuntimeError(
            f"Selection changed after archive: expected={expected}, current={current}"
        )
    if not current["race_count"]:
        raise RuntimeError("No Halla races matched; refusing an empty purge")
    if current["horses_with_non_halla_entries"]:
        raise RuntimeError("At least one selected horse also has non-Halla entries")
    if current["model_prediction_count"]:
        raise RuntimeError("Halla model predictions exist; refusing to break the ledger")

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("BEGIN IMMEDIATE")
    try:
        for table in ("jockey_changes", "race_scratches", "entry_equipment"):
            conn.execute(
                f"""
                DELETE FROM {table}
                WHERE horse_id IN (SELECT id FROM selected_halla_horses)
                   OR {RACE_KEY_FILTER.format(table=table)}
                """
            )
        conn.execute(
            "DELETE FROM race_steward_reports WHERE "
            + RACE_KEY_FILTER.format(table="race_steward_reports")
        )
        conn.execute(
            """
            DELETE FROM running_trial_results
            WHERE horse_id IN (SELECT id FROM selected_halla_horses)
            """
        )
        deleted_races = conn.execute(
            "DELETE FROM races WHERE id IN (SELECT id FROM selected_halla_races)"
        ).rowcount
        deleted_horses = conn.execute(
            "DELETE FROM horses WHERE id IN (SELECT id FROM selected_halla_horses)"
        ).rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    remaining = conn.execute(
        """
        SELECT COUNT(*)
        FROM races r JOIN racecourses c ON c.id = r.racecourse_id
        WHERE c.kra_meet_code = 2 AND r.grade LIKE '한%'
        """
    ).fetchone()[0]
    foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if remaining or foreign_key_errors or integrity != "ok":
        raise RuntimeError(
            "Post-purge verification failed: "
            f"remaining={remaining}, foreign_keys={foreign_key_errors}, integrity={integrity}"
        )
    return {
        "purged_at_utc": datetime.now(UTC).isoformat(),
        "deleted_races": deleted_races,
        "deleted_horses": deleted_horses,
        "remaining_halla_races": remaining,
        "foreign_key_check": "ok",
        "integrity_check": integrity,
        "vacuum_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/horse_racing.sqlite3"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--purge",
        action="store_true",
        help="Delete the verified selection after writing the archive",
    )
    args = parser.parse_args()
    if not args.database.is_file():
        raise FileNotFoundError(args.database)

    with sqlite3.connect(args.database) as conn:
        prepare_selection(conn)
        summary = selection_summary(conn)
        if not summary["race_count"]:
            raise RuntimeError("No Halla races matched the selection rule")
        manifest = write_archive(conn, args.database, args.output_dir)
        result = {"archive": manifest["selection"], "purged": False}
        if args.purge:
            purge_result = purge(conn, summary)
            purge_path = args.output_dir / "purge_result.json"
            purge_path.write_text(
                json.dumps(purge_result, ensure_ascii=False, indent=2) + "\n"
            )
            result.update({"purged": True, "purge_result": purge_result})
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
