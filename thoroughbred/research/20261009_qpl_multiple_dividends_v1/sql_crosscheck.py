"""Independent SQL winner-pair join against the live local read-only source."""

import sqlite3

import numpy as np
import pandas as pd
import run as e


def main():
    with sqlite3.connect(e.DB.as_uri() + "?mode=ro", uri=True) as c:
        c.execute("PRAGMA query_only=ON")
        result = pd.read_sql_query(
            """
          WITH winners AS (
            SELECT r.id race_id, rc.kra_meet_code meet, r.race_date_local race_date,
                   e.horse_number program_no, rr.finish_position finish
            FROM races r JOIN racecourses rc ON rc.id=r.racecourse_id
            JOIN race_entries e ON e.race_id=r.id
            JOIN race_results rr ON rr.race_entry_id=e.id
            WHERE r.status='completed' AND rc.kra_meet_code IN (1,3)
              AND r.race_date_local BETWEEN ? AND ? AND rr.finish_position BETWEEN 1 AND 3
          ), normal AS (
            SELECT race_id FROM winners GROUP BY race_id
            HAVING count(*)=3 AND count(DISTINCT finish)=3
          ), ranked_odds AS (
            SELECT o.race_id, o.selection_key, o.odds,
              row_number() OVER (PARTITION BY o.race_id,o.selection_key
                ORDER BY o.observed_at_ms DESC,o.id DESC) rn
            FROM odds_snapshots o JOIN normal n ON n.race_id=o.race_id WHERE o.bet_type='QPL'
          ), paid AS (
            SELECT w1.race_id,w1.meet,w1.race_date,w1.program_no n1,w2.program_no n2,o.odds
            FROM winners w1 JOIN winners w2 ON w1.race_id=w2.race_id AND w1.program_no<w2.program_no
            JOIN normal n ON n.race_id=w1.race_id
            JOIN ranked_odds o ON o.race_id=w1.race_id AND o.rn=1
              AND o.selection_key=cast(w1.program_no AS TEXT)||'-'||cast(w2.program_no AS TEXT)
            WHERE o.odds>0 AND o.odds<9999.9
          ), complete AS (
            SELECT race_id FROM paid GROUP BY race_id HAVING count(*)=3
          )
          SELECT p.* FROM paid p JOIN complete c ON c.race_id=p.race_id
          ORDER BY p.race_id,p.n1,p.n2
        """,
            c,
            params=("2026-01-01", e.END),
        )
    expected = pd.read_parquet(e.OUT / "winning_pair_payouts.parquet")
    expected = expected[expected.eligible].copy()
    expected[["n1", "n2"]] = expected.programs.str.split(",", expand=True).astype(int)
    cols = ["race_id", "meet", "race_date", "n1", "n2", "odds"]
    expected = expected.sort_values(["race_id", "n1", "n2"])[cols].reset_index(drop=True)
    assert np.array_equal(result[cols].astype(str).to_numpy(), expected.astype(str).to_numpy())
    f = pd.read_parquet(e.OUT / "db_runners.parquet")
    excluded = pd.read_csv(e.OUT / "payout_coverage.csv")
    reasons = []
    for _, r in excluded[excluded.status.eq("completed") & ~excluded.eligible].iterrows():
        g = f[f.race_id.eq(r.race_id)]
        reasons.append(
            dict(
                race_key=r.race_key,
                observed_top3_finish_positions=sorted(
                    g.loc[g.outcome.between(1, 3), "outcome"].astype(int).tolist()
                ),
            )
        )
    e.save(
        e.OUT / "sql_crosscheck.json",
        dict(
            status="passed",
            winning_pairs=len(result),
            races=int(result.race_id.nunique()),
            arithmetic_mean=float(result.odds.mean()),
            independent_sql_matches_frozen_extraction=True,
            excluded_completed_races=reasons,
        ),
    )
    e.check()
    print("SQL cross-check passed", len(result), float(result.odds.mean()), flush=True)


if __name__ == "__main__":
    main()
