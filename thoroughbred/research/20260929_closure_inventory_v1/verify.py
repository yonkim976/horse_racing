"""Check source-backed planned closures against the operational race table."""

from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
INPUT = HERE / "closures.csv"
OUTPUT = HERE / "validation.json"
DB = ROOT / "data" / "horse_racing.sqlite3"
CUTOFF = date.fromisoformat("2026-09-20")


def main() -> None:
    rows = list(csv.DictReader(INPUT.open(encoding="utf-8", newline="")))
    assert rows, "closure ledger is empty"
    keys: set[tuple[int, str, str]] = set()
    for row in rows:
        meet = int(row["meet_code"])
        start = date.fromisoformat(row["start_date"])
        end = date.fromisoformat(row["end_date"])
        assert meet in (1, 3), row
        assert start <= end <= CUTOFF, row
        key = (meet, start.isoformat(), end.isoformat())
        assert key not in keys, f"duplicate interval: {key}"
        keys.add(key)
        assert row["source_url"].startswith("https://race.kra.co.kr/"), row

    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    findings: list[dict[str, object]] = []
    for row in rows:
        count, first, last = connection.execute(
            """
            SELECT COUNT(*), MIN(r.race_date_local), MAX(r.race_date_local)
            FROM races r
            JOIN racecourses c ON c.id = r.racecourse_id
            WHERE c.kra_meet_code = ?
              AND r.race_date_local BETWEEN ? AND ?
            """,
            (int(row["meet_code"]), row["start_date"], row["end_date"]),
        ).fetchone()
        findings.append(
            {
                "meet_code": int(row["meet_code"]),
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "race_rows": count,
                "first_race_date": first,
                "last_race_date": last,
            }
        )
    connection.close()

    result = {
        "scope": "Official planned closures found for 2018-2019 and 2022-2026 plus the documented 2020 COVID suspension, Seoul and Busan-Gyeongnam only; not a complete historical closure calendar.",
        "cutoff": CUTOFF.isoformat(),
        "source_rows": len(rows),
        "rows_by_year": dict(sorted(Counter(row["start_date"][:4] for row in rows).items())),
        "rows_by_meet": dict(sorted(Counter(row["meet_code"] for row in rows).items())),
        "race_rows_inside_closures": sum(item["race_rows"] for item in findings),
        "conflicts": [item for item in findings if item["race_rows"]],
        "checks": findings,
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("source_rows", "race_rows_inside_closures", "conflicts")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
