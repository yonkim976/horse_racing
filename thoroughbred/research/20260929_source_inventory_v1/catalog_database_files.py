"""List candidate database files; inclusion as a source requires later review."""

import csv
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).with_name("database_file_catalog.csv")
DETAILED = {
    "data/horse_racing.sqlite3",
    "data/research/thoroughbred_unified_20260918/thoroughbred_unified.duckdb",
    "data/research/section_point_db_20260925/section_points_adjudicated.sqlite3",
    "thoroughbred/data/dataset_20260929_v1/thoroughbred.duckdb",
    "thoroughbred/data/section_passing_raw_2010plus_20260929_v1/section_passing_raw.duckdb",
}


def classify(path: Path, relative: str):
    if path.is_symlink():
        return "symlink_alias", f"Points to {path.resolve().relative_to(ROOT).as_posix()}"
    if relative in DETAILED:
        return "table_profiled", "Detailed table coverage in inventory.json."
    if relative.startswith("data/experiments/"):
        return "synthetic_experiment_excluded", "Test/event fixture, outside historical source scope."
    if "jeju" in relative:
        return "jeju_excluded", "Jeju is outside Thoroughbred meet scope."
    if relative.startswith("data/backups/") or relative.startswith("data/horse_racing_"):
        return "backup_key_compared", "Race and entry keys compared in operational_backup_key_deltas.json; other tables unreviewed."
    if "_score_20260925/" in relative:
        return "annual_score_profiled", "Tables and keys compared in supplemental_score_sources.json."
    if "section_point_db_20260925/section_points" in relative:
        return "section_predecessor_unreviewed", "Earlier section database version; content comparison remains open."
    return "file_only_unreviewed", "File presence does not establish unique historical source coverage."


def main() -> None:
    paths = sorted(
        path
        for folder in (ROOT / "data", ROOT / "thoroughbred/data")
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in {".sqlite3", ".duckdb", ".db"}
    )
    with OUTPUT.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["path", "bytes", "modified_local", "inventory_status", "note"])
        for path in paths:
            relative = path.relative_to(ROOT).as_posix()
            stat = path.stat()
            status, note = classify(path, relative)
            writer.writerow(
                [
                    relative,
                    stat.st_size,
                    datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    status,
                    note,
                ]
            )
    print(f"database_files={len(paths)} detailed={len(DETAILED)} output={OUTPUT}")


if __name__ == "__main__":
    main()
