"""Read-only, post-commit whole-year verification of a completed dividend backfill."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from sqlalchemy import text

from horse_racing.collectors.kra_api import response_body
from horse_racing.db.engine import create_engine_for_url
from horse_racing.jobs.local_race_day import load_settings
from horse_racing.parsers.horse_history import parse_meet_code
from horse_racing.parsers.race_day import FinalDividendItem, parse_items

ROOT = Path(__file__).resolve().parents[1]


def expectations(folder, report):
    expected, retained, source_rows = {}, {}, 0
    for row in report["pairs"]:
        day, meet = row["day"], row["meet"]
        total = 0
        for meta in json.loads((folder / f"{day}_{meet}.json").read_text()):
            body = Path(meta["local_path"]).read_bytes()
            if hashlib.sha256(body).hexdigest() != meta["sha256"]:
                raise ValueError("raw_hash_mismatch")
            payload = json.loads(body)
            items = parse_items(payload, FinalDividendItem)
            total += len(items)
            if int(response_body(payload).get("totalCount") or 0) != row["source_rows"]:
                raise ValueError("source_total_changed")
            for item in items:
                if item.odds is None:
                    continue
                if item.race_number in row["cancelled_races"]:
                    continue
                if item.race_date.isoformat() != day or parse_meet_code(item.meet_name) != meet:
                    raise ValueError("wrong_source_date_or_venue")
                key = (day, meet, item.race_number)
                previous = expected.setdefault(key, {}).get((item.bet_type, item.selection_key))
                if previous is not None and previous != item.odds:
                    raise ValueError("conflicting_source_key")
                expected.setdefault(key, {})[item.bet_type, item.selection_key] = item.odds
        if total != row["source_rows"]:
            raise ValueError("incomplete_cached_pages")
        source_rows += total
        for db in row["databases"].values():
            for old in db.get("retained_nonstarter_zero_values", []) + db.get(
                "retained_cancelled_race_values", []
            ):
                no, pool, selection = old["key"]
                retained[(day, meet, no, pool, selection)] = old["odds"]
    return expected, retained, source_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    folder = args.run_dir.resolve()
    if not folder.is_relative_to(ROOT / "data"):
        parser.error("run-dir must be inside workspace/data")
    report = json.loads((folder / "report.json").read_text())
    if (
        report["errors"]
        or len(report["pairs"]) != report["planned_pairs"]
        or len({(r["day"], r["meet"]) for r in report["pairs"]}) != report["planned_pairs"]
    ):
        raise ValueError("backfill_not_complete")
    settings = load_settings()
    engines = {
        "local": create_engine_for_url(f"sqlite:///{ROOT / 'data/horse_racing.sqlite3'}"),
        "supabase": create_engine_for_url(settings.database_url),
    }
    verified = {"start": report["start"], "end": report["end"], "databases": {}}
    race_scopes = {}
    sql = text("""SELECT r.race_date_local,c.kra_meet_code,r.race_number,
      o.bet_type,o.selection_key,o.odds FROM odds_snapshots o JOIN races r ON r.id=o.race_id
      JOIN racecourses c ON c.id=r.racecourse_id WHERE r.race_date_local BETWEEN :start AND :end""")
    for name, engine in engines.items():
        expected, retained, source_rows = expectations(folder, report)
        wanted = sum(len(v) for v in expected.values())
        count = mismatched = unexpected = retained_count = 0
        with engine.connect() as connection:
            if name == "supabase":
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(text("SET LOCAL statement_timeout='120s'"))
            scope = [
                (str(day), int(meet), no, status)
                for day, meet, no, status in connection.execute(
                    text("""SELECT r.race_date_local,c.kra_meet_code,
                       r.race_number,r.status FROM races r JOIN racecourses c
                       ON c.id=r.racecourse_id WHERE r.race_date_local BETWEEN :start AND :end
                       ORDER BY 1,2,3"""),
                    {"start": report["start"], "end": report["end"]},
                )
            ]
            race_scopes[name] = scope
            if name == "supabase" and race_scopes["local"] != scope:
                raise ValueError("local_remote_race_scope_mismatch")
            rows = (
                connection.execution_options(stream_results=True)
                .execute(sql, {"start": report["start"], "end": report["end"]})
                .yield_per(100000)
            )
            for day, meet, no, pool, selection, odds in rows:
                count += 1
                race = (str(day), int(meet), no)
                target = expected.get(race, {}).pop((pool, selection), None)
                if target is None:
                    target = retained.pop((*race, pool, selection), None)
                    if target is None:
                        unexpected += 1  # Includes repeat business keys.
                    else:
                        retained_count += 1
                if target is not None and not math.isclose(odds, target, rel_tol=0, abs_tol=1e-8):
                    mismatched += 1
            rows.close()
        missing = sum(len(v) for v in expected.values())
        result = dict(
            source_raw_rows=source_rows,
            expected_positive_rows=wanted,
            stored_rows=count,
            retained_cancelled_selection_rows=retained_count,
            missing_positive_rows=missing,
            mismatched_values=mismatched,
            unexpected_or_duplicate_rows=unexpected,
            missing_retained_rows=len(retained),
        )
        verified["databases"][name] = result
        print(json.dumps({"database": name, **result}), flush=True)
    path = folder / "verification.json"
    path.write_text(json.dumps(verified, ensure_ascii=False, indent=2), encoding="utf-8")
    if any(
        any(
            r[k]
            for k in (
                "missing_positive_rows",
                "mismatched_values",
                "unexpected_or_duplicate_rows",
                "missing_retained_rows",
            )
        )
        for r in verified["databases"].values()
    ):
        raise SystemExit(1)
    for row in report["pairs"]:
        for db in row["databases"].values():
            db["verified"] = True
    report["whole_year_post_commit_verified"] = True
    (folder / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
