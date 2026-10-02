#!/usr/bin/env python3
"""Remove only legacy point rows superseded by verified score-sheet rows.

Dry run by default. The operation is resumable: each bounded DELETE commits
separately and never touches legacy-only points or tempo/3F/4F summary fields.
Do not run against Supabase until the web revision using section_read is live.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
LOCAL_DB = ROOT / "data/horse_racing.sqlite3"
LOCAL_BACKUP = ROOT / "data/backups/horse_racing_before_point_migration_20260928.sqlite3"
EXPECTED_BATCHES = 31
EXPECTED_SECTIONS = 1_823_443
EXPECTED_GROUPS = 103_410
BATCH_SIZE = 5_000

CORNER_POINTS = {
    1: {1: "1C", 2: "2C", 3: "3C", 4: "4C", 7: "S1F", 8: "G1F"},
    2: {1: "1C", 2: "2C", 3: "3C", 4: "4C", 7: "S1F", 8: "G1F"},
    3: {1: "G8F", 2: "G6F", 3: "G4F", 5: "G3F", 7: "S1F", 8: "G2F", 9: "G1F"},
    4: {1: "G8F", 2: "G6F", 3: "G4F", 5: "G3F", 7: "S1F", 8: "G2F", 9: "G1F"},
}


def connect_local() -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{LOCAL_DB}?mode=rw", uri=True)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def connect_supabase():
    import psycopg

    url = os.getenv("SUPABASE_DB_URL") or dotenv_values(ROOT / ".env").get(
        "HORSE_RACING_DATABASE_URL"
    )
    if not url:
        raise SystemExit("Supabase URL is not configured")
    parts = urlsplit(url)
    if parts.scheme == "postgresql+psycopg":
        url = urlunsplit(("postgresql", parts.netloc, parts.path, parts.query, parts.fragment))
    elif parts.scheme not in {"postgres", "postgresql"}:
        raise SystemExit("Expected a Postgres connection URL")
    if not parts.username or "xkykmhhkjtosptoibduo" not in parts.username:
        raise SystemExit("Connection is not horse-racing-prod")
    return psycopg.connect(url, sslmode="require", connect_timeout=20)


def scalar(connection, query: str, params: tuple = ()) -> int:
    return int(connection.execute(query, params).fetchone()[0])


def inspect_target(connection, *, remote: bool) -> tuple[int, int]:
    prefix = "public." if remote else ""
    batches = scalar(connection, f"SELECT count(*) FROM {prefix}race_point_source_batches")
    sections = scalar(connection, f"SELECT count(*) FROM {prefix}race_section_times")
    groups = scalar(connection, f"SELECT count(*) FROM {prefix}race_passing_groups")
    if (batches, sections, groups) != (
        EXPECTED_BATCHES,
        EXPECTED_SECTIONS,
        EXPECTED_GROUPS,
    ):
        raise RuntimeError(f"Canonical batch counts changed: {batches}/{sections}/{groups}")
    overlap = scalar(
        connection,
        f"""SELECT count(*) FROM {prefix}race_section_results old
            WHERE EXISTS (SELECT 1 FROM {prefix}race_section_times newer
                WHERE newer.race_entry_id=old.race_entry_id
                  AND newer.point_code=old.section_code)""",
    )
    legacy_total = scalar(connection, f"SELECT count(*) FROM {prefix}race_section_results")
    return overlap, legacy_total


def clear_duplicate_corners(connection, *, remote: bool) -> int:
    prefix = "public." if remote else ""
    placeholder = "%s" if remote else "?"
    cleared = 0
    for meet, points in CORNER_POINTS.items():
        for index, point in points.items():
            column = f"corner_{index}_raw"
            result = connection.execute(
                f"""UPDATE {prefix}race_passing_summaries
                    SET {column}=NULL
                    WHERE {column} IS NOT NULL AND race_id IN (
                        SELECT g.race_id FROM {prefix}race_passing_groups g
                        JOIN {prefix}races r ON r.id=g.race_id
                        JOIN {prefix}racecourses c ON c.id=r.racecourse_id
                        WHERE c.kra_meet_code={placeholder} AND g.point_code={placeholder}
                    )""",
                (meet, point),
            )
            cleared += result.rowcount
            connection.commit()
    return cleared


def execute_cutover(connection, *, remote: bool) -> tuple[int, int]:
    prefix = "public." if remote else ""
    placeholder = "%s" if remote else "?"
    removed = 0
    while True:
        result = connection.execute(
            f"""DELETE FROM {prefix}race_section_results WHERE id IN (
                SELECT old.id FROM {prefix}race_section_results old
                WHERE EXISTS (
                    SELECT 1 FROM {prefix}race_section_times newer
                    WHERE newer.race_entry_id=old.race_entry_id
                      AND newer.point_code=old.section_code
                ) LIMIT {placeholder}
            )""",
            (BATCH_SIZE,),
        )
        count = result.rowcount
        connection.commit()
        removed += count
        if removed and removed % 50_000 == 0:
            print(f"removed={removed}", flush=True)
        if count == 0:
            break
    cleared = clear_duplicate_corners(connection, remote=remote)
    return removed, cleared


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local", "supabase"), required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    remote = args.target == "supabase"
    if not remote and not LOCAL_BACKUP.is_file():
        raise SystemExit("Verified local backup is missing")
    connection = connect_supabase() if remote else connect_local()
    try:
        if remote:
            connection.execute("SET lock_timeout = '5s'")
            connection.execute("SET statement_timeout = '60s'")
            connection.commit()
        overlap, legacy_total = inspect_target(connection, remote=remote)
        print(f"target={args.target} legacy={legacy_total} overlap={overlap}")
        if not args.execute:
            print("dry-run only; pass --execute to delete overlapping rows")
            return
        removed, cleared = execute_cutover(connection, remote=remote)
        remaining, final_total = inspect_target(connection, remote=remote)
        if remaining:
            raise RuntimeError(f"Overlapping rows remain: {remaining}")
        if final_total != legacy_total - removed:
            raise RuntimeError("Unexpected legacy row count after deletion")
        print(f"deleted={removed} cleared_corner_fields={cleared} legacy_remaining={final_total}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
