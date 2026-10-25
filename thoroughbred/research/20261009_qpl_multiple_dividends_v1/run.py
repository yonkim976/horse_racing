"""Read-only SQLite payout extraction and frozen QPL multi-hit accounting."""

import hashlib
import itertools
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = R.parents[1]
OUT = HERE / "outputs"
P = R / "20261009_pair_trio_budget_v1/outputs"
A = R / "20261009_axis_collapse_v1/outputs"
DB = ROOT / "data/horse_racing.sqlite3"
END = "2026-10-09"


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, x):
    p.write_text(json.dumps(x, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def check():
    for path, h in json.loads((OUT / "source_lock.json").read_text()).items():
        assert sha(ROOT / path) == h, path


def extract():
    with sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True) as c:
        c.execute("PRAGMA query_only=ON")
        c.execute("BEGIN")
        races = pd.read_sql_query(
            """
          SELECT r.id race_id, rc.kra_meet_code meet, r.race_date_local race_date,
                 r.race_number race_no, r.status
          FROM races r JOIN racecourses rc ON rc.id=r.racecourse_id
          WHERE rc.kra_meet_code IN (1,3) AND r.race_date_local BETWEEN ? AND ?
          ORDER BY r.race_date_local, rc.kra_meet_code, r.race_number
        """,
            c,
            params=("2026-01-01", END),
        )
        runners = pd.read_sql_query(
            """
          SELECT r.id race_id, e.horse_number program_no, h.kra_horse_id horse_id,
                 rr.finish_position outcome, rr.disqualified, e.scratched
          FROM races r JOIN racecourses rc ON rc.id=r.racecourse_id
          JOIN race_entries e ON e.race_id=r.id
          JOIN horses h ON h.id=e.horse_id LEFT JOIN race_results rr ON rr.race_entry_id=e.id
          WHERE rc.kra_meet_code IN (1,3) AND r.race_date_local BETWEEN ? AND ?
          ORDER BY r.id, e.horse_number
        """,
            c,
            params=("2026-01-01", END),
        )
        odds = pd.read_sql_query(
            """
          SELECT o.race_id, o.selection_key, o.odds, o.observed_at_ms, o.id source_id
          FROM odds_snapshots o JOIN races r ON r.id=o.race_id
          JOIN racecourses rc ON rc.id=r.racecourse_id
          WHERE rc.kra_meet_code IN (1,3) AND r.race_date_local BETWEEN ? AND ?
                AND o.bet_type='QPL'
          ORDER BY o.race_id, o.selection_key, o.observed_at_ms, o.id
        """,
            c,
            params=("2026-01-01", END),
        )
        c.rollback()
    races["race_key"] = races.apply(
        lambda r: f"{r.meet}:{r.race_date.replace('-', '')}:{r.race_no}", axis=1
    )
    for name, frame in [("db_races", races), ("db_runners", runners), ("db_qpl_odds", odds)]:
        frame.to_parquet(OUT / (name + ".parquet"), index=False)
    save(
        OUT / "database_snapshot.json",
        dict(
            path=str(DB.relative_to(ROOT)),
            read_only=True,
            requested_end=END,
            extract_hashes={
                name: sha(OUT / (name + ".parquet"))
                for name in ["db_races", "db_runners", "db_qpl_odds"]
            },
            whole_db_hash_omitted="Live SQLite/WAL; freeze queried rows in one read transaction",
        ),
    )
    return races, runners, odds


def payout_data(races, runners, odds):
    latest = odds.drop_duplicates(["race_id", "selection_key"], keep="last").set_index(
        ["race_id", "selection_key"]
    )
    lookup = {rid: g for rid, g in runners.groupby("race_id", sort=False)}
    rows, coverage = [], []
    for _, r in races.iterrows():
        g = lookup.get(r.race_id, pd.DataFrame(columns=["outcome", "program_no"]))
        top = g[g.outcome.between(1, 3)]
        exact = sorted(top.outcome.tolist()) == [1, 2, 3]
        complete = r.status == "completed" and exact
        values = []
        for pair in (
            itertools.combinations(sorted(top.program_no.astype(int)), 2) if complete else []
        ):
            key = "-".join(map(str, pair))
            value = (
                float(latest.loc[(r.race_id, key), "odds"])
                if (r.race_id, key) in latest.index
                else np.nan
            )
            valid = bool(np.isfinite(value) and 0 < value < 9999.9)
            values.append(valid)
            rows.append(
                dict(
                    race_key=r.race_key,
                    race_id=int(r.race_id),
                    meet=int(r.meet),
                    race_date=r.race_date,
                    programs=",".join(map(str, pair)),
                    odds=value,
                    valid=valid,
                )
            )
        coverage.append(
            dict(
                race_key=r.race_key,
                race_id=int(r.race_id),
                status=r.status,
                unique_top3=bool(exact),
                normal_payouts=sum(values),
                eligible=bool(complete and sum(values) == 3),
            )
        )
    payouts = pd.DataFrame(rows)
    cov = pd.DataFrame(coverage)
    payouts = payouts.merge(cov[["race_key", "eligible"]], on="race_key", validate="many_to_one")
    payouts.to_parquet(OUT / "winning_pair_payouts.parquet", index=False)
    cov.to_csv(OUT / "payout_coverage.csv", index=False)
    return payouts, cov


def stats(payouts):
    f = payouts[payouts.eligible]
    rows = []
    for scope, g in [("all", f)] + [(str(meet), f[f.meet.eq(meet)]) for meet in [1, 3]]:
        odds = g.odds.to_numpy()
        assert len(odds) > 0
        rec = dict(
            scope=scope,
            races=int(g.race_key.nunique()),
            winning_pairs=len(g),
            first_date=str(g.race_date.min()),
            last_date=str(g.race_date.max()),
            mean=float(odds.mean()),
            median=float(np.median(odds)),
            min=float(odds.min()),
            max=float(odds.max()),
            p25=float(np.quantile(odds, 0.25)),
            p75=float(np.quantile(odds, 0.75)),
        )
        for alpha in [0.01, 0.05]:
            lo, hi = np.quantile(odds, [alpha, 1 - alpha])
            trimmed = odds[(odds >= lo) & (odds <= hi)]
            suffix = str(int(alpha * 100))
            rec.update(
                {
                    f"trim{suffix}_low": float(lo),
                    f"trim{suffix}_high": float(hi),
                    f"trim{suffix}_count": len(trimmed),
                    f"trim{suffix}_mean": float(trimmed.mean()),
                }
            )
        rows.append(rec)
    result = pd.DataFrame(rows)
    result.to_csv(OUT / "dividend_summary.csv", index=False)
    return result


def model_accounting(races, runners, payouts, cov):
    f = pd.read_parquet(A / "oof_runners.parquet")
    f = f[f.year.eq(2026)]
    lookup = {r: g for r, g in runners.groupby("race_id", sort=False)}
    race_lookup = races.set_index("race_key")
    eligible = set(cov.loc[cov.eligible, "race_key"])
    accepted, alignment = [], []
    for rid, g in f.groupby("race_key", sort=False):
        status = "missing_race"
        if rid in race_lookup.index:
            race_id = int(race_lookup.loc[rid, "race_id"])
            raw = lookup.get(race_id, pd.DataFrame())
            raw = raw[raw.scratched.eq(0)].copy()
            a = (
                g[["program_no", "horse_id", "outcome"]]
                .sort_values("program_no")
                .reset_index(drop=True)
            )
            b = (
                raw[["program_no", "horse_id", "outcome"]]
                .sort_values("program_no")
                .reset_index(drop=True)
            )
            for one in [a, b]:
                one["outcome"] = (
                    one.outcome.where(one.outcome.between(1, 20), 0).fillna(0).astype(int)
                )
                one["horse_id"] = one.horse_id.astype(str)
            same = len(a) == len(b) and np.array_equal(
                a.astype(str).to_numpy(), b.astype(str).to_numpy()
            )
            status = (
                "matched"
                if same and rid in eligible
                else "runner_mismatch"
                if not same
                else "payout_incomplete"
            )
            if status == "matched":
                accepted.append(rid)
        alignment.append(dict(race_key=rid, status=status))
    pd.DataFrame(alignment).to_csv(OUT / "model_alignment.csv", index=False)
    tickets = pd.read_parquet(P / "tickets.parquet")
    tickets = tickets[tickets.bet.eq("quinella_place") & tickets.race_key.isin(accepted)].copy()
    win = payouts[payouts.eligible][["race_key", "programs", "odds"]]
    tickets = tickets.merge(win, on=["race_key", "programs"], how="left", validate="many_to_one")
    assert tickets.hit.eq(tickets.odds.notna().astype(int)).all()
    tickets["display_return"] = tickets.odds.fillna(0)
    tickets.to_parquet(OUT / "matched_ticket_returns.parquet", index=False)
    events = (
        tickets.groupby(["race_key", "policy"])
        .agg(
            tickets=("hit", "size"),
            winning_tickets=("hit", "sum"),
            display_return=("display_return", "sum"),
        )
        .reset_index()
    )
    events["hit"] = events.winning_tickets.gt(0).astype(int)
    events.to_parquet(OUT / "matched_race_returns.parquet", index=False)
    summary = []
    for policy, g in events.groupby("policy"):
        winner = tickets[tickets.policy.eq(policy) & tickets.hit.eq(1)]
        summary.append(
            dict(
                policy=policy,
                races=len(g),
                tickets=int(g.tickets.sum()),
                hits=int(g.hit.sum()),
                hit_rate=float(g.hit.mean()),
                winning_tickets=int(g.winning_tickets.sum()),
                mean_winning_odds=float(winner.odds.mean()),
                display_return=float(g.display_return.sum()),
                gross_return_ratio=float(g.display_return.sum() / g.tickets.sum()),
                net_ratio_before_adjustments=float(g.display_return.sum() / g.tickets.sum() - 1),
            )
        )
    result = pd.DataFrame(summary)
    result.to_csv(OUT / "model_return_summary.csv", index=False)
    return result


def main():
    OUT.mkdir(exist_ok=True)
    refs = (
        [HERE / n for n in ["PLAN.md", "run.py", "verify.py"]]
        + [P / n for n in ["tickets.parquet", "race_metrics.parquet", "verification.json"]]
        + [
            A / "oof_runners.parquet",
            ROOT / "config/prediction_model_registry.json",
            R / "20261008_profile_carried_weight_v1/outputs/research_baseline_selection.json",
        ]
    )
    assert not (OUT / "source_lock.json").exists()
    save(OUT / "source_lock.json", {str(p.relative_to(ROOT)): sha(p) for p in refs})
    races, runners, odds = extract()
    payouts, cov = payout_data(races, runners, odds)
    print(stats(payouts).to_string(index=False), flush=True)
    print(model_accounting(races, runners, payouts, cov).to_string(index=False), flush=True)
    old = pd.read_parquet(P / "race_metrics.parquet")
    old = old[old.bet.eq("quinella_place")]
    multi = old.groupby(["policy", "winning_tickets"]).size().rename("races").reset_index()
    multi["race_share"] = multi.races / 4799
    multi.to_csv(OUT / "multiple_hit_counts.csv", index=False)
    check()


if __name__ == "__main__":
    main()
