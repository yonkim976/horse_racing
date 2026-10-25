"""Recompute reported date bootstrap differences independently of run.py."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"


def main():
    config = json.loads((HERE / "config.json").read_text())
    a = pd.read_csv(OUT / "race_metrics.csv")
    reported = pd.read_csv(OUT / "paired_differences.csv")
    checks = []
    for z in reported.itertuples():
        frame = a.copy()
        if z.scope != "all":
            frame = frame[frame[z.scope].astype(str) == str(z.value)]
        first = frame[frame.policy == z.policy].set_index("rid").sort_index()
        base = frame[frame.policy == z.baseline].set_index("rid").loc[first.index]
        metric = "six_hit" if z.metric == "companion_given_axis" else z.metric
        if z.metric != "six_hit":
            good = first.axis_placed.eq(1)
            first, base = first[good], base[good]
        value = first[metric] - base[metric]
        valid = value.notna()
        value, first = value[valid], first[valid]
        dated = pd.DataFrame({"date": first.race_date, "v": value})
        totals = dated.groupby("date").v.agg(["sum", "count"])
        random = np.random.default_rng(config["seed"])
        ix = random.integers(0, len(totals), size=(config["bootstrap_draws"], len(totals)))
        bootstrap = totals["sum"].to_numpy()[ix].sum(axis=1) / totals["count"].to_numpy()[ix].sum(
            axis=1
        )
        result = np.array([value.mean(), *np.quantile(bootstrap, [0.025, 0.975])])
        expected = np.array([z.delta, z.lo, z.hi])
        assert np.allclose(result, expected, atol=1e-12, rtol=0), z
        checks.append(
            dict(
                scope=z.scope,
                value=z.value,
                policy=z.policy,
                baseline=z.baseline,
                metric=z.metric,
                maximum_error=float(abs(result - expected).max()),
            )
        )
    # Every policy uses the same axis and full evaluation population.
    assert a.groupby("rid").policy.nunique().eq(a.policy.nunique()).all()
    assert a.groupby("rid").axis_number.nunique().eq(1).all()
    assert a.groupby("rid").axis_placed.nunique().eq(1).all()
    assert a.groupby("rid").axis_probability.nunique().eq(1).all()
    hashes = {
        n: hashlib.sha256((OUT / n).read_bytes()).hexdigest()
        for n in [
            "race_metrics.csv",
            "paired_differences.csv",
            "summary.csv",
            "six_tickets.parquet",
        ]
    }
    with (OUT / "independent_statistics_verification.json").open("x") as f:
        json.dump(
            dict(
                passed=True,
                comparisons=len(checks),
                max_error=max(c["maximum_error"] for c in checks),
                all_axes_and_evaluation_populations_identical=True,
                hashes=hashes,
                details=checks,
            ),
            f,
            indent=2,
        )
    print("Independent bootstrap comparisons", len(checks), "passed")


if __name__ == "__main__":
    main()
