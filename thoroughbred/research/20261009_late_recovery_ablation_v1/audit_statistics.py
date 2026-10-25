"""Independent rank-outcome metrics and date-block confidence intervals."""

import numpy as np
import pandas as pd
import run as e


def main():
    e.check()
    r = pd.read_parquet(e.OUT / "race_metrics.parquet")
    h = pd.read_parquet(e.OUT / "runner_metrics.parquet")
    summaries = pd.read_csv(e.OUT / "summary.csv")
    pairs = pd.read_csv(e.OUT / "paired_differences.csv")
    lookup = r.set_index(["variant", "race_key"])
    for key, g in h.groupby(["variant", "race_key"]):
        y = g.sort_values("model_rank").outcome.to_numpy()
        top2 = set(np.flatnonzero((y >= 1) & (y <= 2)))
        row = lookup.loc[key]
        assert row.axis_top3 == int(1 <= y[0] <= 3)
        assert row.axis_top2 == int(1 <= y[0] <= 2)
        assert row.axis_win == int(y[0] == 1)
        assert row.quinella_one == int(top2 == {0, 1})
        assert row.quinella_box4 == int(top2 <= set(range(4)))
    for row in summaries.itertuples():
        g = r[r.variant.eq(row.variant)]
        if str(row.period) == "2025_2026":
            g = g[g.year.ge(2025)]
        elif str(row.period) != "all":
            g = g[g.year.eq(int(row.period))]
        assert len(g) == row.races
        assert g.low_winners_up.sum() == row.low_winners_up
        assert g.old_winners_down.sum() == row.old_winners_down
        for metric in [
            "trio6",
            "axis_top3",
            "axis_top2",
            "axis_win",
            "quinella_one",
            "quinella_box4",
            "top5_contains_truth",
        ]:
            assert g[metric].sum() == getattr(row, metric + "_hits")
            assert abs(g[metric].mean() - getattr(row, metric + "_rate")) < 1e-12
    intervals = 0
    for row in pairs.itertuples():
        a = r[r.variant.eq(row.candidate)].set_index("race_key").sort_index()
        b = r[r.variant.eq(row.baseline)].set_index("race_key").sort_index()
        if str(row.period) == "2025_2026":
            a = a[a.year.ge(2025)]
        elif str(row.period) != "all":
            a = a[a.year.eq(int(row.period))]
        b = b.loc[a.index]
        assert len(a) == row.races
        delta = a[row.metric] - b[row.metric]
        assert abs(delta.mean() - row.difference) < 1e-12
        if pd.notna(row.gained):
            assert ((a[row.metric] == 1) & (b[row.metric] == 0)).sum() == row.gained
            assert ((a[row.metric] == 0) & (b[row.metric] == 1)).sum() == row.lost
        # Different aggregation implementation: pandas date grouping, no factorize/bincount.
        daily = (
            pd.DataFrame(dict(date=a.race_date.to_numpy(), delta=delta.to_numpy()))
            .groupby("date")
            .delta.agg(["sum", "size"])
        )
        ix = np.random.default_rng(e.config()["bootstrap_seed"]).integers(
            0, len(daily), (2000, len(daily))
        )
        means = daily["sum"].to_numpy()[ix].sum(1) / daily["size"].to_numpy()[ix].sum(1)
        np.testing.assert_allclose(
            np.quantile(means, [0.025, 0.975]), [row.ci_low, row.ci_high], atol=1e-12
        )
        intervals += 1
    e.save(
        e.OUT / "statistics_audit.json",
        dict(
            status="passed",
            rank_metrics_independent=True,
            summary_denominators_recomputed=True,
            paired_intervals_independently_recomputed=intervals,
            gain_loss_counts_independently_recomputed=True,
            code_sha256=e.sha(e.HERE / "audit_statistics.py"),
        ),
    )
    e.check()
    print("Statistics verified", intervals, flush=True)


if __name__ == "__main__":
    main()
