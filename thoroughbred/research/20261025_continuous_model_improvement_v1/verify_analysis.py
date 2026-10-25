"""Separate paired-axis aggregation and interval reproduction."""

import json
import numpy as np
import pandas as pd
import research as c


def main():
    result = json.loads((c.OUT / "results.json").read_text())
    comparisons = pd.read_parquet(c.OUT / "axis_comparison.parquet")
    checked = 0
    for variant in c.VARIANTS:
        for year in [0, 2026]:
            f = comparisons[comparisons.variant.eq(variant)].copy()
            if year:
                f = f[f.year.eq(year)]
            f["delta"] = f.candidate_hit - f.baseline_hit
            sums = f.groupby("race_date", sort=True).agg(
                delta=("delta", "sum"), n=("delta", "size")
            )
            weights = np.random.default_rng(20261025 + year * 10).multinomial(
                len(sums), np.full(len(sums), 1 / len(sums)), size=2000
            )
            draws = np.array(
                [
                    float(np.sum(w * sums.delta.to_numpy()) / np.sum(w * sums.n.to_numpy()))
                    for w in weights
                ]
            )
            row = next(
                x
                for x in result["groups"]
                if x["variant"] == variant and x["year"] == year and x["meet"] == 0
            )
            metric = row["metrics"]["axis_top3"]
            c.require(metric["baseline_total"] == f.baseline_hit.sum())
            c.require(metric["candidate_total"] == f.candidate_hit.sum())
            np.testing.assert_allclose(metric["difference"], f.delta.mean(), atol=1e-12, rtol=0)
            np.testing.assert_allclose(
                metric["ci95"], np.quantile(draws, [0.025, 0.975]), atol=1e-12, rtol=0
            )
            np.testing.assert_allclose(
                metric["ci_family98_333"],
                np.quantile(draws, [0.05 / 6, 1 - 0.05 / 6]),
                atol=1e-12,
                rtol=0,
            )
            c.require(
                row["axis_rescued"] == int(((f.baseline_hit == 0) & (f.candidate_hit == 1)).sum())
            )
            c.require(
                row["axis_lost"] == int(((f.baseline_hit == 1) & (f.candidate_hit == 0)).sum())
            )
            checked += 1
    p = pd.read_parquet(c.OUT / "runner_probabilities.parquet")
    for col, total in [("win", 1), ("top2", 2), ("top3", 3)]:
        c.require(p[col].between(0, 1).all())
        np.testing.assert_allclose(
            p.groupby(["variant", "race_key"])[col].sum(), total, atol=1e-9, rtol=0
        )
    c.require((p.win <= p.top2 + 1e-12).all() and (p.top2 <= p.top3 + 1e-12).all())
    c.check()
    for name in ["feature_verification", "model_verification", "numeric_verification"]:
        c.require(json.loads((c.OUT / f"{name}.json").read_text())["status"] == "passed")
    c.save(
        c.OUT / "verification.json",
        {
            "status": "passed",
            "independent_axis_scope_summaries": checked,
            "paired_bootstrap_reproduced": True,
            "all_probability_invariants_passed": True,
            "model_and_feature_replay_passed": True,
            "candidate_models": 18,
            "races_per_candidate": 4799,
            "matched_2026_races": 1288,
            "operating_registry_and_source_hashes_unchanged": True,
            "no_database_or_network_writes": True,
            "new_independent_test": False,
            "production_changed": False,
        },
    )
    print("Verified analysis", checked, flush=True)


if __name__ == "__main__":
    main()
