"""Correct the archived 2023 Seoul 9R nonfinish code without touching raw sources."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB = Path("data/research/seoul_backfill_20260915_v1/history.sqlite3")


def main() -> None:
    con = sqlite3.connect(DB)
    keys = [
        r[0]
        for r in con.execute("""SELECT hr_no FROM result
      WHERE race_date='2023-01-15' AND race_no=9 AND finish_raw='98'""")
    ]
    if len(keys) != 12:
        raise ValueError(f"Expected 12 source-code 98 rows, found {len(keys)}")
    before = con.execute("""SELECT count(*) FROM result WHERE finish_raw='98'
      AND result_status='finished'""").fetchone()[0]
    if before == 0:
        print(json.dumps({"status": "already_corrected", "code98_rows": len(keys)}))
        return
    if before != 12:
        raise ValueError(f"Unexpected pre-correction state: {before}")
    con.execute("""UPDATE result SET finish_order=NULL,
      result_status='unmapped_special_98',is_dead_heat=0
      WHERE race_date='2023-01-15' AND race_no=9 AND finish_raw='98'""")
    con.execute("""UPDATE race SET official_result_state='special_only_unresolved'
      WHERE race_date='2023-01-15' AND race_no=9""")
    con.execute("""UPDATE research_entry SET current_finish_order=NULL,
      current_result_status='unmapped_special_98'
      WHERE race_date='2023-01-15' AND race_no=9""")
    placeholders = ",".join("?" for _ in keys)
    cursor = con.execute(
        f"""UPDATE research_entry SET prior_races=prior_races-1
      WHERE hr_no IN ({placeholders}) AND race_date>'2023-01-15'""",
        keys,
    )
    con.commit()
    print(
        json.dumps(
            {
                "status": "corrected",
                "code98_rows": len(keys),
                "later_research_rows_corrected": cursor.rowcount,
            }
        )
    )
    con.close()


if __name__ == "__main__":
    main()
