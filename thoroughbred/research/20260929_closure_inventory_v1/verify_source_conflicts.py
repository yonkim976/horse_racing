"""Check official closure intervals against each principal race table."""

import csv
import json
import sqlite3
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CLOSURES = list(csv.DictReader((HERE / "closures.csv").open(encoding="utf-8")))
SOURCES = {
    "operational_sqlite": ROOT / "data/horse_racing.sqlite3",
    "historical_unified_duckdb": ROOT / "data/research/thoroughbred_unified_20260918/thoroughbred_unified.duckdb",
    "research_dataset_v1_duckdb": ROOT / "thoroughbred/data/dataset_20260929_v1/thoroughbred.duckdb",
}
OUTPUT = HERE / "source_conflicts.json"


def main():
    findings = {}
    for name, path in SOURCES.items():
        if name == "operational_sqlite":
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            con.execute("PRAGMA query_only=ON")
            query = (
                "SELECT racecourse_id, race_date_local, race_number FROM races "
                "WHERE racecourse_id=? AND race_date_local BETWEEN ? AND ? "
                "ORDER BY race_date_local,race_number"
            )
        else:
            con = duckdb.connect(str(path), read_only=True)
            query = (
                "SELECT canonical_meet, race_date, race_no FROM race "
                "WHERE canonical_meet=? AND race_date BETWEEN ? AND ? "
                "ORDER BY race_date,race_no"
            )
        try:
            conflicts = []
            for closure in CLOSURES:
                for meet, race_date, race_no in con.execute(
                    query, [int(closure["meet_code"]), closure["start_date"], closure["end_date"]]
                ).fetchall():
                    conflicts.append(
                        {
                            "meet_code": meet,
                            "race_date": str(race_date),
                            "race_number": race_no,
                            "closure_start": closure["start_date"],
                            "closure_end": closure["end_date"],
                            "official_source_url": closure["source_url"],
                        }
                    )
            findings[name] = {"race_rows_inside_closures": len(conflicts), "conflicts": conflicts}
        finally:
            con.close()
    report = {
        "closure_rows": len(CLOSURES),
        "scope": "Listed official planned closure intervals only; this does not validate all historical non-race dates.",
        "interpretation": "A race row inside a documented closure is a review flag, not automatic proof of which source is correct.",
        "sources": findings,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print({name: x["race_rows_inside_closures"] for name, x in findings.items()})


if __name__ == "__main__":
    main()
