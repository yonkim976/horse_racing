"""Read-only audit of pre-2017 Jeju histories for the 2017 native cohort."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCORE_DB = ROOT / "data/research/jeju_2017_score_20260925/jeju_2017.sqlite3"
OPERATIONAL_DB = ROOT / "data/horse_racing.sqlite3"
ARCHIVE_DIR = ROOT / "data/raw/jeju_native_results"


def open_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def main() -> None:
    with open_read_only(SCORE_DB) as conn:
        cohort = {
            str(row[0]).strip()
            for row in conn.execute("SELECT DISTINCT kra_horse_id FROM entry")
            if row[0] is not None and str(row[0]).strip()
        }
        native_races_2017 = conn.execute("SELECT COUNT(*) FROM race").fetchone()[0]
        cohort_races = conn.execute(
            "SELECT COUNT(DISTINCT race_date || '-' || race_number) FROM entry"
        ).fetchone()[0]

    archive_rows: list[tuple[str, str, int]] = []
    archive_races: set[tuple[str, int]] = set()
    for year in range(2002, 2015):
        path = ARCHIVE_DIR / f"native_results_{year}.jsonl"
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                item = json.loads(line)
                # Repeat the explicit native-race predicate used by the archive.
                if not str(item.get("rank", "")).startswith("제"):
                    continue
                horse_id = str(item.get("hrNo", "")).strip()
                date = str(item.get("rcDate", "")).strip()
                race_no = int(item.get("rcNo") or 0)
                if not horse_id or not date or not race_no:
                    continue
                archive_rows.append((horse_id, date, race_no))
                archive_races.add((date, race_no))

    with open_read_only(OPERATIONAL_DB) as conn:
        operational_rows = [
            (str(horse_id).strip(), str(date).replace("-", ""), int(race_no))
            for horse_id, date, race_no in conn.execute(
                """
                SELECT h.kra_horse_id, r.race_date_local, r.race_number
                FROM races AS r
                JOIN race_entries AS e ON e.race_id = r.id
                JOIN horses AS h ON h.id = e.horse_id
                WHERE r.racecourse_id = 2
                  AND h.meet_code = 2
                  AND r.race_date_local >= '2015-01-01'
                  AND r.race_date_local < '2017-01-01'
                """
            )
            if horse_id is not None and str(horse_id).strip()
        ]

    older_rows = archive_rows + operational_rows
    history_horses = {horse_id for horse_id, _, _ in older_rows}
    linked_horses = cohort & history_horses
    linked_rows = [row for row in older_rows if row[0] in cohort]
    linked_archived = [row for row in archive_rows if row[0] in cohort]
    linked_operational = [row for row in operational_rows if row[0] in cohort]
    years = Counter(date[:4] for _, date, _ in linked_rows)
    earliest = min((date for _, date, _ in linked_rows), default=None)

    report = {
        "scope": "2017 Jeju native scorecard horse IDs matched to pre-2017 Jeju result records",
        "sources": {
            "2017_cohort": str(SCORE_DB.relative_to(ROOT)),
            "explicit_native_archive_2002_2014": str(ARCHIVE_DIR.relative_to(ROOT)),
            "operational_jeju_race_entries_2015_2016": str(OPERATIONAL_DB.relative_to(ROOT)),
        },
        "cohort": {
            "scorecard_races": native_races_2017,
            "races_with_entries": cohort_races,
            "unique_horses": len(cohort),
        },
        "pre_2017_linkage": {
            "horses_with_any_observed_history": len(linked_horses),
            "horses_without_observed_history": len(cohort - linked_horses),
            "observed_history_coverage": round(len(linked_horses) / len(cohort), 6),
            "linked_start_rows": len(linked_rows),
            "earliest_linked_start_date": earliest,
            "linked_rows_by_year": dict(sorted(years.items())),
            "archive_2002_2014": {
                "linked_horses": len({row[0] for row in linked_archived}),
                "linked_start_rows": len(linked_archived),
            },
            "operational_2015_2016": {
                "linked_horses": len({row[0] for row in linked_operational}),
                "linked_start_rows": len(linked_operational),
            },
        },
        "method_notes": [
            "Horse histories are linked by official KRA horse ID, never by name.",
            "The 2002-2014 archive is filtered to rank values beginning with 제.",
            "The 2015-2016 rows are Jeju-course operational entries whose horse IDs occur in the 2017 native cohort; those historical rows are not independently filtered by a contemporaneous 제 rank label.",
            "The cohort is an audit population only; it must not be used to select historical training rows using future participation.",
            "This audit reads local files and databases in read-only mode; it does not train a model or modify the sources.",
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
