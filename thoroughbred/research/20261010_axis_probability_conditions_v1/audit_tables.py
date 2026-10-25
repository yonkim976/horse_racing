"""Independent probability-bin intervals and common-cell standardization audit."""

import numpy as np
import pandas as pd
import run as e


def main():
    e.check()
    d = pd.read_parquet(e.OUT / "races.parquet")
    masks = pd.read_parquet(e.OUT / "rule_memberships.parquet").set_index("race_key")
    d = d.set_index("race_key", drop=False)
    bins = pd.read_csv(e.OUT / "probability_bins.csv", dtype={"period": str})
    matching = pd.read_csv(e.OUT / "matched_conditions.csv", dtype={"period": str})
    n_ci = n_matched = 0
    for tag, frame in e.period(d):
        rows = bins[bins.period.eq(tag)]
        for row in rows.itertuples():
            g = frame[frame.probability_band.eq(row.band)]
            a = (
                g.assign(error=g.collapsed - g.base_risk)
                .groupby("race_date")
                .agg(n=("collapsed", "size"), y=("collapsed", "sum"), error=("error", "sum"))
                .sort_index()
            )
            rng = np.random.default_rng(e.SEED)
            w = rng.multinomial(len(a), np.full(len(a), 1 / len(a)), e.B)
            den = w @ a.n.to_numpy(dtype=float)
            for col, metric in [("y", "failure_rate"), ("error", "residual")]:
                v = (w @ a[col].to_numpy(dtype=float)) / den
                np.testing.assert_allclose(
                    [getattr(row, metric + "_low"), getattr(row, metric + "_high")],
                    np.quantile(v, [0.025, 0.975]),
                    atol=1e-12,
                )
                n_ci += 1
        # Build cell counts, sums and complementary means with pivoted aggregates.
        keys = ["year", "meet", "prob5", "distance_band", "grade_band", "field_band"]
        for rule in e.NAMES:
            member = masks.loc[frame.index, rule]
            x = frame.loc[member.notna()].copy()
            x["member"] = member.dropna().astype(bool)
            a = (
                x.groupby(keys + ["member"], observed=True)
                .agg(n=("collapsed", "size"), y=("collapsed", "mean"), r=("residual", "mean"))
                .unstack("member")
            )
            if True not in a.n.columns or False not in a.n.columns:
                a = a.iloc[:0]
            else:
                a = a[(a.n[True] >= 3) & (a.n[False] >= 3)]
            row = matching[matching.period.eq(tag) & matching.rule.eq(rule)].iloc[0]
            assert row.cells == len(a)
            if len(a):
                assert row.matched_n == a.n[True].sum()
                np.testing.assert_allclose(
                    [row.matched_rate, row.standardized_complement_rate, row.matched_residual_diff],
                    [
                        np.average(a.y[True], weights=a.n[True]),
                        np.average(a.y[False], weights=a.n[True]),
                        np.average(a.r[True] - a.r[False], weights=a.n[True]),
                    ],
                    atol=1e-12,
                )
            else:
                assert row.matched_n == 0 and pd.isna(row.matched_residual_diff)
            n_matched += 1
    e.save(
        e.OUT / "tables_audit.json",
        dict(
            status="passed",
            probability_bin_intervals=n_ci,
            standardized_rows=n_matched,
            audit_script_sha256=e.sha(e.HERE / "audit_tables.py"),
        ),
    )
    e.check()
    print("Audited", n_ci, "intervals and", n_matched, "standardized rows")


if __name__ == "__main__":
    main()
