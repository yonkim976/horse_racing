#!/usr/bin/env python3
"""Export the Supabase legacy point tables before the one-time duplicate cleanup."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from datetime import UTC, datetime

from remove_legacy_point_duplicates import ROOT, connect_supabase

BACKUP_DIR = ROOT / "data/backups/supabase_point_cleanup_20260928"
TABLES = ("race_section_results", "race_passing_summaries")


def backup_table(connection, table: str) -> dict[str, object]:
    expected = connection.execute(f"SELECT count(*) FROM public.{table}").fetchone()[0]
    destination = BACKUP_DIR / f"{table}.csv.gz"
    partial = BACKUP_DIR / f"{table}.csv.gz.partial"
    if destination.exists() or partial.exists():
        raise RuntimeError(f"Backup already exists: {destination}")

    with gzip.open(partial, "wb") as output:
        with connection.cursor().copy(
            f"COPY (SELECT * FROM public.{table} ORDER BY id) "
            "TO STDOUT WITH (FORMAT csv, HEADER true)"
        ) as copy:
            for chunk in copy:
                output.write(chunk)

    with gzip.open(partial, "rt", encoding="utf-8", newline="") as source:
        rows = sum(1 for _ in csv.reader(source)) - 1
    if rows != expected:
        raise RuntimeError(f"Backup count mismatch for {table}: {rows} != {expected}")

    digest = hashlib.sha256()
    with partial.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    partial.replace(destination)
    return {
        "table": table,
        "rows": rows,
        "path": str(destination.relative_to(ROOT)),
        "bytes": destination.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def main() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = BACKUP_DIR / "manifest.json"
    if manifest_path.exists():
        raise RuntimeError(f"Backup manifest already exists: {manifest_path}")
    with connect_supabase() as connection:
        items = [backup_table(connection, table) for table in TABLES]
    manifest = {
        "project_ref": "xkykmhhkjtosptoibduo",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "tables": items,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    for item in items:
        print(f"{item['table']}: {item['rows']} rows, {item['bytes']} bytes")
    print(f"manifest: {manifest_path}")


if __name__ == "__main__":
    main()
