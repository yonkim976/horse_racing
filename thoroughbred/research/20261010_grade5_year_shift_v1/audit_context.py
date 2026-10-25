"""Audit common-cell membership/DID and disclose within-region feature shifts."""

import numpy as np
import pandas as pd
import run as r


def main():
    r.check()
    d = pd.read_parquet(r.OUT / "races.parquet")
    comparison = pd.read_csv(r.OUT / "year_differences.csv")
    standard = pd.read_csv(r.OUT / "standardized.csv")
    feature_rows, checks = [], []
    for scope, frame in r.scopes(d):
        target = frame[frame.target]
        for meet, g in target.groupby("meet"):
            old, new = g[g.time.eq("2024_25")], g[g.time.eq("2026")]
            for col in r.NUMERIC:
                a, b = old[col].dropna(), new[col].dropna()
                feature_rows.append(
                    dict(
                        scope=scope,
                        meet=int(meet),
                        feature=col,
                        old_n=len(a),
                        new_n=len(b),
                        old_mean=float(a.mean()),
                        new_mean=float(b.mean()),
                        difference=float(b.mean() - a.mean()),
                    )
                )
        periods = []
        point = []
        for time in ["2024_25", "2026"]:
            g = frame[frame.time.eq(time)]
            dates = sorted(g.race_date.unique())
            rng = np.random.default_rng(r.SEED)
            w = rng.multinomial(len(dates), np.full(len(dates), 1 / len(dates)), r.B)
            per_group, means = [], []
            for flag in ["target", "high_other"]:
                x = g[g[flag]].copy()
                x["error"] = x.collapsed - x.base_risk
                daily = (
                    x.groupby("race_date").error.agg(["sum", "count"]).reindex(dates, fill_value=0)
                )
                den = w @ daily["count"].to_numpy(dtype=float)
                per_group.append(
                    np.divide(
                        w @ daily["sum"].to_numpy(), den, out=np.full(r.B, np.nan), where=den > 0
                    )
                )
                means.append(x.error.mean())
            periods.append(per_group[0] - per_group[1])
            point.append(means[0] - means[1])
        row = comparison[
            comparison.scope.eq(scope)
            & comparison.metric.eq("target_minus_high_other_residual_DID")
        ].iloc[0]
        np.testing.assert_allclose(row.difference, point[1] - point[0])
        v = periods[1] - periods[0]
        v = v[np.isfinite(v)]
        np.testing.assert_allclose([row.low, row.high], np.quantile(v, [0.025, 0.975]), atol=1e-12)
        schemes = [(col, [col], 5, 3) for col in r.CAT] + [
            ("region_probability", ["meet_band", "prob_band"], 5, 3),
            ("region_season", ["meet_band", "season"], 5, 3),
            ("joint_context", ["meet_band", "prob_band", "distance_band", "field_band"], 3, 2),
        ]
        for name, keys, mo, mn in schemes:
            # Pivot independently, then derive the exact eligible common cells.
            wide = (
                target.groupby(keys + ["time"], observed=True)
                .agg(n=("race_key", "size"), risk=("collapsed", "mean"), resid=("residual", "mean"))
                .unstack("time")
            )
            good = wide[(wide.n["2024_25"] >= mo) & (wide.n["2026"] >= mn)]
            row = standard[standard.scope.eq(scope) & standard.scheme.eq(name)].iloc[0]
            assert row.cells == len(good)
            assert row.old_n == good.n["2024_25"].sum() and row.new_n == good.n["2026"].sum()
            if len(good):
                np.testing.assert_allclose(
                    row.standardized_old_residual,
                    np.average(good.resid["2024_25"], weights=good.n["2026"]),
                )
                np.testing.assert_allclose(
                    row.standardized_old_risk,
                    np.average(good.risk["2024_25"], weights=good.n["2026"]),
                )
            checks.append(dict(scope=scope, scheme=name, status="passed"))
    pd.DataFrame(feature_rows).to_csv(r.OUT / "within_region_features.csv", index=False)
    r.save(
        r.OUT / "context_audit.json",
        dict(
            status="passed",
            did_intervals_checked=2,
            independent_common_cell_checks=checks,
            within_region_numeric_rows=len(feature_rows),
            script_sha256=r.sha(r.HERE / "audit_context.py"),
        ),
    )
    r.check()
    print("Verified DID and", len(checks), "independent cell sets")


if __name__ == "__main__":
    main()
