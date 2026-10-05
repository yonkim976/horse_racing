"""Prepare unverified archive references without writing either operational database.

Run verify_dividend_backfill.py afterwards to verify both physical databases.
"""

from __future__ import annotations

import argparse
import fcntl
import json

import backfill_dividends_verified as backfill
from sqlalchemy import text
from sqlalchemy.orm import Session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=backfill.Path, required=True)
    args = parser.parse_args()
    folder = args.run_dir.resolve()
    if not folder.is_relative_to(backfill.ROOT / "data"):
        parser.error("run-dir must be inside workspace/data")
    with (folder / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        prepare(folder)


def prepare(folder):
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    if report["errors"]:
        raise ValueError("audit_errors_require_resolution")
    engine = backfill.create_engine_for_url(
        f"sqlite:///{backfill.ROOT / 'data/horse_racing.sqlite3'}"
    )
    with engine.connect() as connection:
        pairs = [
            (str(d), int(m))
            for d, m in connection.execute(
                text("""
            SELECT DISTINCT r.race_date_local,c.kra_meet_code FROM races r
            JOIN racecourses c ON c.id=r.racecourse_id WHERE r.status='completed'
            AND r.race_date_local BETWEEN :start AND :end ORDER BY 1 DESC,2
            """),
                {"start": report["start"], "end": report["end"]},
            )
        ]
    if len(pairs) != report["planned_pairs"]:
        raise ValueError("operational_race_scope_changed")
    done = {(r["day"], r["meet"]) for r in report["pairs"]}
    for day, meet in pairs:
        if (day, meet) in done:
            continue
        if (folder / f"{day}_{meet}.json").exists():
            pages, _ = backfill.pages_for(None, folder, day, meet)
        else:
            pages, _ = backfill.archive_pages(folder, day, meet)
        items = [
            i for p in pages for i in backfill.parse_items(p.payload, backfill.FinalDividendItem)
        ]
        backfill.require_complete_pages(pages, len(items))
        with Session(engine) as session:
            races, entries = backfill.inventory(session, day, meet)
            expected, ignored, duplicate = backfill.validate(items, day, meet, races, entries)
            retained = backfill.confirmed_nonstarter_zero_keys(session, races, items)
            reference = backfill.reconcile(session, races, expected, 0, False, retained)
            if reference["inserted"] or reference["updated"]:
                raise ValueError("unapplied_changes_cannot_be_prepared")
        row = dict(
            day=day,
            meet=meet,
            source_rows=len(items),
            pages=len(pages),
            source_origin="sha_verified_official_archive"
            if (folder / f"{day}_{meet}.origin.json").exists()
            else "fresh_official_api",
            positive_rows=len(expected),
            nonpositive_rows=ignored,
            source_duplicates=duplicate,
            race_count=len(races),
            cancelled_races=[n for n, (_, s) in races.items() if s == "confirmed_cancelled"],
            cancelled_positive_source_rows=sum(
                i.odds is not None and races[i.race_number][1] == "confirmed_cancelled"
                for i in items
            ),
            sentinel_9999_9=sum(v == 9999.9 for v in expected.values()),
            audit_only_no_new_ingestion_run=True,
            databases={},
        )
        for name in ("local", "supabase"):
            # A local reference does not assert that the remote database is already verified.
            row["databases"][name] = json.loads(json.dumps(reference))
            row["databases"][name]["reference_origin"] = "local_pending_whole_year_verification"
            if name == "supabase":
                for field in ("retained_nonstarter_zero_values", "retained_cancelled_race_values"):
                    for value in row["databases"][name][field]:
                        value.pop("id", None)
        report["pairs"].append(row)
        backfill.save_json(folder / "report.json", report)
        print(
            json.dumps(
                {
                    "prepared": len(report["pairs"]),
                    "day": day,
                    "meet": meet,
                    "cancelled_races": row["cancelled_races"],
                }
            ),
            flush=True,
        )
    engine.dispose()


if __name__ == "__main__":
    main()
