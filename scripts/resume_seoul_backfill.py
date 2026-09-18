"""Resume materialization from the committed isolated Seoul source tables."""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

from build_seoul_backfill import research, validate_and_report

ROOT = Path("data/research/seoul_backfill_20260915_v1")


def main() -> None:
    tmp = ROOT / "history.building.sqlite3"
    con = sqlite3.connect(tmp)
    if con.execute("SELECT count(*) FROM research_entry").fetchone()[0] != 0:
        raise RuntimeError("Research rows already exist; inspect before resuming")
    research(con)
    counts = Counter()
    for year, n in con.execute("SELECT substr(race_date,1,4),count(*) FROM entry GROUP BY 1"):
        counts[(year, "entries")] = n
    for year, n in con.execute("""SELECT substr(source_path,-19,4),count(*)
      FROM source_inventory WHERE source_type='result_api' GROUP BY 1"""):
        counts[(year, "pages")] = n
    for (
        source,
        month,
        n,
    ) in con.execute("""SELECT source_type,replace(substr(event_date,1,7),'-',''),count(*)
      FROM training_event GROUP BY 1,2"""):
        counts[(source, month, "rows")] = n
    for source, table, date_col in (
        ("dacom72", "medical_event", "event_date"),
        ("dacom12", "race_day_weight", "race_date"),
        ("dacom71", "entry_equipment", "race_date"),
    ):
        for year, n in con.execute(
            f"SELECT substr({date_col},1,4),count(*) FROM {table} GROUP BY 1"
        ):
            counts[(source, year, "events")] = n
    for source, year, n in con.execute("""SELECT source_type,substr(file_date,1,4),count(*)
      FROM source_inventory WHERE source_type LIKE 'dacom%' GROUP BY 1,2"""):
        counts[(source, year, "files")] = n
    validate_and_report(con, ROOT, counts)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    tmp.replace(ROOT / "history.sqlite3")


if __name__ == "__main__":
    main()
