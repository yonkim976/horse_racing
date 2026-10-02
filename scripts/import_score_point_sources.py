#!/usr/bin/env python3
"""Copy immutable meet/year score-sheet passage data into canonical tables.

Sources are opened read-only. Each file is one atomic batch. This deliberately
does not remove legacy operational rows or change serving queries; cutover is
separate and must follow a complete local *and* remote import audit.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
SCORE_ROOT = ROOT / "data/research"
LOCAL_DB = ROOT / "data/horse_racing.sqlite3"
MEETS = ("seoul", "busan", "jeju", "yeongcheon")
MEET_CODES = {"seoul": 1, "jeju": 2, "busan": 3, "yeongcheon": 4}
YEARS = range(2017, 2027)


def source_files() -> list[tuple[str, int, Path]]:
    result = []
    for meet in MEETS:
        for year in (2026,) if meet == "yeongcheon" else YEARS:
            path = SCORE_ROOT / f"{meet}_{year}_score_20260925" / f"{meet}_{year}.sqlite3"
            if not path.is_file():
                raise FileNotFoundError(path)
            result.append((meet, year, path))
    return result


def source_connection(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    return con


def file_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def source_metadata(con: sqlite3.Connection) -> tuple[int, int, bool]:
    section_count = int(con.execute("SELECT count(*) FROM section_time").fetchone()[0])
    group_count = int(con.execute("SELECT count(*) FROM passing_group").fetchone()[0])
    columns = {row[1] for row in con.execute("PRAGMA table_info(section_time)")}
    return section_count, group_count, "source_field" in columns


def load_local(
    target: sqlite3.Connection,
    meet: str,
    year: int,
    path: Path,
    digest: str,
) -> tuple[int, int, str]:
    source_file = str(path.relative_to(ROOT))
    with closing(source_connection(path)) as source:
        section_count, group_count, has_source_field = source_metadata(source)
    existing = target.execute(
        """SELECT id,source_sha256,section_row_count,passing_group_row_count
           FROM race_point_source_batches WHERE meet_code=? AND race_year=?""",
        (MEET_CODES[meet], year),
    ).fetchone()
    if existing:
        batch_id, prior_digest, prior_sections, prior_groups = existing
        actual_sections = target.execute(
            "SELECT count(*) FROM race_section_times WHERE source_batch_id=?", (batch_id,)
        ).fetchone()[0]
        actual_groups = target.execute(
            "SELECT count(*) FROM race_passing_groups WHERE source_batch_id=?", (batch_id,)
        ).fetchone()[0]
        if (
            prior_digest,
            prior_sections,
            prior_groups,
            actual_sections,
            actual_groups,
        ) != (digest, section_count, group_count, section_count, group_count):
            raise RuntimeError(f"Existing batch differs from source: {source_file}")
        return section_count, group_count, "already_verified"

    target.execute("ATTACH DATABASE ? AS score", (f"file:{path}?mode=ro",))
    try:
        # The target and immutable source are on the same host, so verify every
        # official ID/natural key before a single row is copied.
        race_mismatch = target.execute(
            """SELECT count(*) FROM score.race s
               LEFT JOIN races r ON r.id=s.operational_race_id
               LEFT JOIN racecourses c ON c.id=r.racecourse_id
               WHERE r.id IS NULL OR c.kra_meet_code<>s.meet_code
                  OR r.race_date_local<>s.race_date
                  OR r.race_number<>s.race_number OR r.distance_m<>s.distance_m"""
        ).fetchone()[0]
        entry_mismatch = target.execute(
            """SELECT count(*) FROM score.entry s
               LEFT JOIN race_entries e ON e.id=s.operational_race_entry_id
               LEFT JOIN races r ON r.id=e.race_id
               LEFT JOIN racecourses c ON c.id=r.racecourse_id
               LEFT JOIN horses h ON h.id=e.horse_id
               WHERE e.id IS NULL OR c.kra_meet_code<>s.meet_code
                  OR r.race_date_local<>s.race_date OR r.race_number<>s.race_number
                  OR e.horse_number<>s.horse_number OR h.kra_horse_id<>s.kra_horse_id"""
        ).fetchone()[0]
        if race_mismatch or entry_mismatch:
            raise RuntimeError(
                f"Source IDs differ from current local operations: "
                f"races={race_mismatch}, entries={entry_mismatch}"
            )
        target.execute("BEGIN IMMEDIATE")
        batch_id = target.execute(
            """INSERT INTO race_point_source_batches
               (source_file,source_sha256,meet_code,race_year,section_row_count,
                passing_group_row_count,loaded_at_ms) VALUES (?,?,?,?,?,?,?)""",
            (
                source_file,
                digest,
                MEET_CODES[meet],
                year,
                section_count,
                group_count,
                int(time.time() * 1000),
            ),
        ).lastrowid
        field_sql = "s.source_field" if has_source_field else "NULL"
        target.execute(
            f"""INSERT INTO race_section_times
                (race_entry_id,point_code,time_kind,elapsed_time_ms,position_raw,
                 source_name,source_field,source_batch_id)
                SELECT e.operational_race_entry_id,s.point_code,s.time_kind,
                       s.elapsed_time_ms,s.position,s.source_name,{field_sql},?
                FROM score.section_time s JOIN score.entry e
                  ON e.meet_code=s.meet_code AND e.race_date=s.race_date
                 AND e.race_number=s.race_number AND e.kra_horse_id=s.kra_horse_id""",
            (batch_id,),
        )
        target.execute(
            """INSERT INTO race_passing_groups
                (race_id,point_code,notation_raw,source_batch_id)
                SELECT r.operational_race_id,g.point_code,g.notation_raw,?
                FROM score.passing_group g JOIN score.race r
                  ON r.meet_code=g.meet_code AND r.race_date=g.race_date
                 AND r.race_number=g.race_number""",
            (batch_id,),
        )
        inserted_sections = target.execute(
            "SELECT count(*) FROM race_section_times WHERE source_batch_id=?", (batch_id,)
        ).fetchone()[0]
        inserted_groups = target.execute(
            "SELECT count(*) FROM race_passing_groups WHERE source_batch_id=?", (batch_id,)
        ).fetchone()[0]
        if (inserted_sections, inserted_groups) != (section_count, group_count):
            raise RuntimeError(
                f"Import count mismatch {source_file}: "
                f"{inserted_sections}/{section_count} sections, "
                f"{inserted_groups}/{group_count} groups"
            )
        target.commit()
        return section_count, group_count, "loaded"
    except Exception:
        target.rollback()
        raise
    finally:
        target.execute("DETACH DATABASE score")


def load_postgres(
    target,
    meet: str,
    year: int,
    path: Path,
    digest: str,
) -> tuple[int, int, str]:
    source_file = str(path.relative_to(ROOT))
    with closing(source_connection(path)) as source:
        section_count, group_count, has_source_field = source_metadata(source)
        existing = target.execute(
            """SELECT id,source_sha256,section_row_count,passing_group_row_count
               FROM public.race_point_source_batches WHERE meet_code=%s AND race_year=%s""",
            (MEET_CODES[meet], year),
        ).fetchone()
        if existing:
            batch_id, prior_digest, prior_sections, prior_groups = existing
            actual_sections = target.execute(
                "SELECT count(*) FROM public.race_section_times WHERE source_batch_id=%s",
                (batch_id,),
            ).fetchone()[0]
            actual_groups = target.execute(
                "SELECT count(*) FROM public.race_passing_groups WHERE source_batch_id=%s",
                (batch_id,),
            ).fetchone()[0]
            if (
                prior_digest,
                prior_sections,
                prior_groups,
                actual_sections,
                actual_groups,
            ) != (digest, section_count, group_count, section_count, group_count):
                raise RuntimeError(f"Existing remote batch differs from source: {source_file}")
            target.commit()
            return section_count, group_count, "already_verified"

        # A whole score-sheet file is committed atomically. COPY streams from
        # the local SQLite client, never from the Postgres server filesystem.
        with target.cursor() as cursor:
            cursor.execute(
                """INSERT INTO public.race_point_source_batches
                   (source_file,source_sha256,meet_code,race_year,section_row_count,
                    passing_group_row_count,loaded_at_ms) VALUES (%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id""",
                (
                    source_file,
                    digest,
                    MEET_CODES[meet],
                    year,
                    section_count,
                    group_count,
                    int(time.time() * 1000),
                ),
            )
            batch_id = cursor.fetchone()[0]
            field_sql = "s.source_field" if has_source_field else "NULL"
            with cursor.copy(
                """COPY public.race_section_times
                   (race_entry_id,point_code,time_kind,elapsed_time_ms,position_raw,
                    source_name,source_field,source_batch_id) FROM STDIN"""
            ) as copy:
                for row in source.execute(
                    f"""SELECT e.operational_race_entry_id,s.point_code,s.time_kind,
                               s.elapsed_time_ms,s.position,s.source_name,{field_sql}
                        FROM section_time s JOIN entry e
                          ON e.meet_code=s.meet_code AND e.race_date=s.race_date
                         AND e.race_number=s.race_number AND e.kra_horse_id=s.kra_horse_id"""
                ):
                    copy.write_row((*row, batch_id))
            with cursor.copy(
                """COPY public.race_passing_groups
                   (race_id,point_code,notation_raw,source_batch_id) FROM STDIN"""
            ) as copy:
                for row in source.execute(
                    """SELECT r.operational_race_id,g.point_code,g.notation_raw
                       FROM passing_group g JOIN race r
                         ON r.meet_code=g.meet_code AND r.race_date=g.race_date
                        AND r.race_number=g.race_number"""
                ):
                    copy.write_row((*row, batch_id))
            cursor.execute(
                "SELECT count(*) FROM public.race_section_times WHERE source_batch_id=%s",
                (batch_id,),
            )
            inserted_sections = cursor.fetchone()[0]
            cursor.execute(
                "SELECT count(*) FROM public.race_passing_groups WHERE source_batch_id=%s",
                (batch_id,),
            )
            inserted_groups = cursor.fetchone()[0]
            if (inserted_sections, inserted_groups) != (section_count, group_count):
                raise RuntimeError(f"Remote import count mismatch: {source_file}")
        target.commit()
        return section_count, group_count, "loaded"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("local", "supabase"), required=True)
    parser.add_argument("--meet", choices=MEETS)
    parser.add_argument("--year", type=int, choices=YEARS)
    args = parser.parse_args()
    selected = [
        item
        for item in source_files()
        if (args.meet is None or item[0] == args.meet)
        and (args.year is None or item[1] == args.year)
    ]
    if args.target == "local":
        target = sqlite3.connect(f"file:{LOCAL_DB}?mode=rw", uri=True)
        target.execute("PRAGMA foreign_keys=ON")
        target.execute("PRAGMA busy_timeout=30000")
        loader = load_local
    else:
        import psycopg
        from dotenv import dotenv_values

        url = os.getenv("SUPABASE_DB_URL") or dotenv_values(ROOT / ".env").get(
            "HORSE_RACING_DATABASE_URL"
        )
        if not url:
            raise SystemExit("SUPABASE_DB_URL is required for remote COPY")
        parts = urlsplit(url)
        if parts.scheme == "postgresql+psycopg":
            url = urlunsplit(("postgresql", parts.netloc, parts.path, parts.query, parts.fragment))
        elif parts.scheme not in {"postgres", "postgresql"}:
            raise SystemExit("Remote target must be a Postgres URL")
        if not parts.username or "xkykmhhkjtosptoibduo" not in parts.username:
            raise SystemExit("Remote target is not the horse-racing-prod project")
        target = psycopg.connect(url, sslmode="require", connect_timeout=20)
        loader = load_postgres
    try:
        total_sections = total_groups = 0
        for meet, year, path in selected:
            digest = file_sha256(path)
            sections, groups, status = loader(target, meet, year, path, digest)
            total_sections += sections
            total_groups += groups
            print(f"{meet}/{year}: {status}, sections={sections}, groups={groups}", flush=True)
        print(f"verified: sections={total_sections}, groups={total_groups}")
    finally:
        target.close()


if __name__ == "__main__":
    main()
