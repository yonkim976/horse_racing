"""Recompute winner identities, trimming, multiple wins, and display returns."""

import itertools
import json

import numpy as np
import pandas as pd
import run as e


def main():
    e.check()
    snap = json.loads((e.OUT / "database_snapshot.json").read_text())
    for name, h in snap["extract_hashes"].items():
        assert e.sha(e.OUT / (name + ".parquet")) == h
    races = pd.read_parquet(e.OUT / "db_races.parquet")
    runners = pd.read_parquet(e.OUT / "db_runners.parquet")
    odds = pd.read_parquet(e.OUT / "db_qpl_odds.parquet")
    payouts = pd.read_parquet(e.OUT / "winning_pair_payouts.parquet")
    cov = pd.read_csv(e.OUT / "payout_coverage.csv")
    latest = (
        odds.sort_values(["race_id", "selection_key", "observed_at_ms", "source_id"])
        .drop_duplicates(["race_id", "selection_key"], keep="last")
        .set_index(["race_id", "selection_key"])
    )
    rlookup = {r: g for r, g in runners.groupby("race_id")}
    for _, r in payouts.iterrows():
        top = rlookup[r.race_id]
        top = top[top.outcome.between(1, 3)]
        expected = {
            ",".join(map(str, t))
            for t in itertools.combinations(sorted(top.program_no.astype(int)), 2)
        }
        assert r.programs in expected and sorted(top.outcome.tolist()) == [1, 2, 3]
        key = (r.race_id, r.programs.replace(",", "-"))
        value = float(latest.loc[key, "odds"]) if key in latest.index else np.nan
        assert (np.isnan(value) and pd.isna(r.odds)) or value == r.odds
        assert r.valid == bool(np.isfinite(value) and 0 < value < 9999.9)
    valid = payouts[payouts.eligible]
    assert valid.groupby("race_key").size().eq(3).all()
    for _, r in pd.read_csv(e.OUT / "dividend_summary.csv").iterrows():
        z = valid if str(r.scope) == "all" else valid[valid.meet.eq(int(r.scope))]
        values = z.odds.to_numpy()
        assert len(values) == r.winning_pairs
        assert abs(values.mean() - r["mean"]) < 1e-12
        assert abs(np.median(values) - r["median"]) < 1e-12
        assert abs(z.groupby("race_key").odds.mean().mean() - values.mean()) < 1e-12
        for alpha in [0.01, 0.05]:
            lo, hi = np.quantile(values, [alpha, 1 - alpha])
            keep = values[(values >= lo) & (values <= hi)]
            assert abs(keep.mean() - r[f"trim{int(alpha * 100)}_mean"]) < 1e-12
    t = pd.read_parquet(e.OUT / "matched_ticket_returns.parquet")
    m = pd.read_parquet(e.OUT / "matched_race_returns.parquet")
    win = valid.set_index(["race_key", "programs"]).odds.to_dict()
    for _, r in t.iterrows():
        expected = win.get((r.race_key, r.programs), 0)
        assert r.display_return == expected and r.hit == int(expected > 0)
    checkm = (
        t.groupby(["race_key", "policy"])
        .agg(
            tickets=("hit", "size"),
            winning_tickets=("hit", "sum"),
            display_return=("display_return", "sum"),
        )
        .sort_index()
    )
    assert np.allclose(
        checkm.to_numpy(),
        m.set_index(["race_key", "policy"]).sort_index()[checkm.columns].to_numpy(),
    )
    for _, r in pd.read_csv(e.OUT / "model_return_summary.csv").iterrows():
        z = t[t.policy.eq(r.policy)]
        g = m[m.policy.eq(r.policy)]
        assert int(z.hit.sum()) == r.winning_tickets and g.hit.sum() == r.hits
        assert abs(z.display_return.sum() / len(z) - r.gross_return_ratio) < 1e-12
    old = pd.read_parquet(e.P / "race_metrics.parquet")
    old = old[old.bet.eq("quinella_place")]
    multi = pd.read_csv(e.OUT / "multiple_hit_counts.csv")
    for _, r in multi.iterrows():
        assert (
            len(old[old.policy.eq(r.policy) & old.winning_tickets.eq(r.winning_tickets)]) == r.races
        )
    axis = multi[multi.policy.eq("in3_out3")].set_index("winning_tickets").races
    assert axis.to_dict() == {0: 1581, 1: 2193, 2: 332, 3: 693}
    assert (axis.index.to_numpy() * axis.to_numpy()).sum() == 4936
    assert set(races.meet) <= {1, 3} and races.race_date.max() <= e.END
    assert set(cov.loc[cov.eligible, "race_key"]) == set(valid.race_key)
    e.check()
    e.save(
        e.OUT / "verification.json",
        dict(
            status="passed",
            read_only_snapshot_hashes=True,
            winning_payout_identity_verified=True,
            three_payouts_per_eligible_race=True,
            trimmed_statistics_recomputed=True,
            multiple_hit_counts_reproduced=True,
            all_selected_ticket_returns_recomputed=True,
            multi_win_returns_summed=True,
            valid_market_races=int(valid.race_key.nunique()),
            matched_model_races=int(m.race_key.nunique()),
            production_changed=False,
            selected_baseline_changed=False,
            new_training=False,
            database_writes=False,
            supabase_access=False,
            jeju_access=False,
        ),
    )
    print("Verified", valid.race_key.nunique(), m.race_key.nunique(), len(t), flush=True)


if __name__ == "__main__":
    main()
