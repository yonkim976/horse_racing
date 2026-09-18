"""Quarantine zero-time numeric ranks from unconfirmed Seoul API races."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB = Path("data/research/seoul_backfill_20260915_v1/history.sqlite3")


def main() -> None:
    con = sqlite3.connect(DB)
    bad = con.execute("""SELECT race_date,race_no,hr_no,finish_raw
      FROM result WHERE result_status='finished' AND race_time_s<=0""").fetchall()
    if not bad:
        print(json.dumps({"status": "already_corrected"}))
        return
    if len(bad) != 35 or {day for day, _, _, _ in bad} != {"2026-08-24", "2026-08-31"}:
        raise ValueError(f"Unexpected zero-time ranked rows: {len(bad)}")
    con.execute("CREATE TEMP TABLE invalid_rank(hr_no TEXT,race_date TEXT,raw_rank TEXT)")
    con.executemany(
        "INSERT INTO invalid_rank VALUES(?,?,?)", [(hr, day, raw) for day, _, hr, raw in bad]
    )
    con.execute("CREATE INDEX invalid_rank_hr_date ON invalid_rank(hr_no,race_date)")
    con.execute("""UPDATE result SET finish_order=NULL,
      result_status='ranked_time_missing_unconfirmed',is_dead_heat=0
      WHERE result_status='finished' AND race_time_s<=0""")
    con.execute("""UPDATE research_entry SET current_finish_order=NULL,
      current_result_status='ranked_time_missing_unconfirmed'
      WHERE (race_date,race_no,hr_no) IN
        (SELECT race_date,race_no,hr_no FROM result
         WHERE result_status='ranked_time_missing_unconfirmed')""")
    con.execute("""UPDATE research_entry SET
      prior_races=prior_races-(SELECT count(*) FROM invalid_rank b
        WHERE b.hr_no=research_entry.hr_no AND b.race_date<research_entry.race_date),
      prior_wins=prior_wins-(SELECT count(*) FROM invalid_rank b
        WHERE b.hr_no=research_entry.hr_no AND b.race_date<research_entry.race_date
          AND b.raw_rank='1')
      WHERE EXISTS(SELECT 1 FROM invalid_rank b WHERE b.hr_no=research_entry.hr_no
        AND b.race_date<research_entry.race_date)""")
    con.execute("""UPDATE race SET official_result_state='special_only_unresolved'
      WHERE race_date IN ('2026-08-24','2026-08-31')
        AND NOT EXISTS(SELECT 1 FROM result x WHERE x.race_date=race.race_date
          AND x.race_no=race.race_no AND x.result_status='finished')""")
    con.commit()
    print(
        json.dumps(
            {
                "status": "corrected",
                "zero_time_rank_rows": len(bad),
                "affected_races": len({(day, no) for day, no, _, _ in bad}),
                "later_research_rows_recalculated": con.total_changes - len(bad),
            }
        )
    )
    con.close()


if __name__ == "__main__":
    main()
