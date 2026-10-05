"""Read-only source-key coverage audit of obsolete section-point databases.

Compares the three databases explicitly marked unused/forbidden in
docs/SECTION_POINT_DB_HANDOFF_2026-09-25.md with the retained adjudicated DB.
Every attached SQLite file is opened using mode=ro and query_only is enabled.
The script writes only its JSON report beside itself.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DB_DIR = ROOT / "data/research/section_point_db_20260925"
CURRENT = DB_DIR / "section_points_adjudicated.sqlite3"
CANDIDATES = [
    DB_DIR / "section_points.sqlite3",
    DB_DIR / "section_points_ext.sqlite3",
    DB_DIR / "section_points_repaired.sqlite3",
]
RAW_SOURCE_KEY = [
    "meet_code",
    "race_date",
    "race_number",
    "distance_m",
    "kra_horse_id",
    "horse_number",
    "point_code",
    "elapsed_time_ms",
    "source_name",
    "source_field",
]
COMPARE_TABLES = ["finish_time", "track_by_distance", "s1f_field_mismatch"]


def open_read_only(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    return con


def table_columns(con: sqlite3.Connection, schema: str, table: str) -> list[str]:
    # Identifiers are fixed constants from this script, not user input.
    return [row[1] for row in con.execute(f"PRAGMA {schema}.table_info('{table}')")]


def table_rows(con: sqlite3.Connection, schema: str, table: str) -> int | None:
    exists = con.execute(
        f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        return None
    return int(con.execute(f"SELECT COUNT(*) FROM {schema}.'{table}'").fetchone()[0])


def set_difference_count(
    con: sqlite3.Connection, source_schema: str, source_table: str,
    target_schema: str, target_table: str, columns: list[str],
) -> int:
    projection = ",".join(f'"{col}"' for col in columns)
    query = (
        f"SELECT COUNT(*) FROM (SELECT {projection} FROM {source_schema}.'{source_table}' "
        f"EXCEPT SELECT {projection} FROM {target_schema}.'{target_table}')"
    )
    return int(con.execute(query).fetchone()[0])


def compare_one(path: Path) -> dict[str, object]:
    print(f"comparing {path.name}", flush=True)
    con = open_read_only(path)
    try:
        con.execute("ATTACH DATABASE ? AS current", (CURRENT.as_uri() + "?mode=ro",))
        con.execute("PRAGMA query_only=ON")
        old_section_rows = table_rows(con, "main", "section_time")
        current_section_rows = table_rows(con, "current", "section_time")
        projection = ",".join(f'"{col}"' for col in RAW_SOURCE_KEY)
        missing_query = (
            f"SELECT {projection} FROM main.section_time "
            f"EXCEPT SELECT {projection} FROM current.section_time"
        )
        missing_source_keys = 0
        null_horse_count = 0
        group_counts: dict[tuple[object, object], list[int]] = defaultdict(lambda: [0, 0])
        samples: list[list[object]] = []
        # Stream one set-difference result; grouping and samples are accumulated
        # in memory so the large EXCEPT operation is not repeated several times.
        for row in con.execute(missing_query):
            missing_source_keys += 1
            values = tuple(row)
            horse_number = values[5]
            if horse_number is None:
                null_horse_count += 1
            group = group_counts[(values[8], values[9])]
            group[0] += 1
            group[1] += int(horse_number is None)
            if len(samples) < 5:
                samples.append(list(values))
        groups = [
            {
                "source_name": key[0],
                "source_field": key[1],
                "rows": counts[0],
                "null_horse_number_rows": counts[1],
            }
            for key, counts in sorted(group_counts.items(), key=lambda item: item[1][0], reverse=True)[:25]
        ]

        table_results: dict[str, object] = {}
        for table in COMPARE_TABLES:
            old_rows = table_rows(con, "main", table)
            current_rows = table_rows(con, "current", table)
            if old_rows is None or current_rows is None:
                missing = None
            else:
                missing = set_difference_count(
                    con,
                    "main",
                    table,
                    "current",
                    table,
                    table_columns(con, "main", table),
                )
            table_results[table] = {
                "old_rows": old_rows,
                "current_rows": current_rows,
                "old_rows_missing_from_current": missing,
            }

        result = {
            "path": str(path.relative_to(ROOT)),
            "bytes": path.stat().st_size,
            "section_time_rows": old_section_rows,
            "current_section_time_rows": current_section_rows,
            "source_key_columns": RAW_SOURCE_KEY,
            "old_distinct_source_keys_missing_from_current": missing_source_keys,
            "missing_source_keys_with_null_horse_number": null_horse_count,
            "missing_source_groups": groups,
            "missing_source_samples": samples,
            "other_tables": table_results,
        }
        print(
            f"finished {path.name}: missing_source_keys={missing_source_keys}",
            flush=True,
        )
        return result
    finally:
        con.close()


def main() -> None:
    results = [compare_one(path) for path in CANDIDATES]
    by_name = {Path(row["path"]).name: row for row in results}
    ext_missing = by_name["section_points_ext.sqlite3"]["old_distinct_source_keys_missing_from_current"]
    repaired_missing = by_name["section_points_repaired.sqlite3"]["old_distinct_source_keys_missing_from_current"]
    base_missing = by_name["section_points.sqlite3"]["old_distinct_source_keys_missing_from_current"]
    report = {
        "scope": "Read-only set comparison of source-value keys and listed support tables against the retained adjudicated DB.",
        "current_db": {
            "path": str(CURRENT.relative_to(ROOT)),
            "bytes": CURRENT.stat().st_size,
        },
        "method": {
            "sqlite_read_only": True,
            "query_only": True,
            "set_semantics": "EXCEPT compares distinct projected rows; IDs and derived classification fields are intentionally excluded from the source-key comparison.",
            "source_key_columns": RAW_SOURCE_KEY,
            "other_tables": COMPARE_TABLES,
        },
        "results": results,
        "recommendation": {
            "section_points.sqlite3": (
                "preserve: distinct source-value keys are absent from the adjudicated DB"
                if base_missing else "candidate for deletion after review"
            ),
            "section_points_ext.sqlite3": (
                "candidate for deletion after independent review: source keys and compared support tables are covered"
                if ext_missing == 0 else "preserve: source-value keys are absent from the adjudicated DB"
            ),
            "section_points_repaired.sqlite3": (
                "candidate for deletion after independent review: source keys and compared support tables are covered"
                if repaired_missing == 0 else "preserve: source-value keys are absent from the adjudicated DB"
            ),
            "limitations": [
                "Coverage against the adjudicated DB does not by itself establish that the old DB can never be needed to rerun its historical build stage.",
                "The verified DB is separately retained as the direct input to adjudicate_section_points.py and is outside this deletion proposal.",
            ],
        },
    }
    output = HERE / "section_comparison.json"
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"report": str(output), "results": [
        {"path": row["path"], "missing_source_keys": row["old_distinct_source_keys_missing_from_current"]}
        for row in results
    ]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
