"""Independent sorted-list/set scoring, direct ticket enumeration and paired intervals."""

import itertools
import json
import numpy as np
import pandas as pd
import analyze as c


def main():
    c.check()
    d = pd.read_parquet(c.OUT / "matched_ranks.parquet")
    saved = pd.read_parquet(c.OUT / "race_metrics.parquet").set_index(["race_key", "model"])
    require = c.require
    checks = 0
    rank_checks = 0
    max_error = 0.0
    for key, g in d.groupby("race_key"):
        actual = {
            int(r.outcome): int(r.program_no) for r in g.itertuples() if r.outcome in [1, 2, 3]
        }
        require(len(actual) == 3)
        truth = frozenset(actual.values())
        for model in ["old", "current"]:
            records = sorted(
                g.to_dict("records"),
                key=lambda row: (-round(row[model + "_prob"], 12), row["program_no"]),
            )
            programs = [int(x["program_no"]) for x in records]
            for rank, row in enumerate(records, 1):
                require(row[model + "_rank"] == rank)
                rank_checks += 1
            companions = set(programs[1:5])
            n = len(truth & companions)
            expected = {
                "companion4_hits": n,
                "companion4_atleast2": int(n >= 2),
                "companion2_both": int(set(programs[1:3]) <= truth),
                "companion3_atleast2": int(len(set(programs[1:4]) & truth) >= 2),
            }
            ticket_sets = [
                frozenset([programs[0], a, b]) for a, b in itertools.combinations(programs[1:5], 2)
            ]
            require(len(ticket_sets) == 6)
            expected["axis_trio6"] = int(truth in ticket_sets)
            for rank in range(1, 6):
                expected[f"rank{rank}_hit"] = int(programs[rank - 1] in truth)
                if rank > 1:
                    expected[f"rank{rank}_predicted"] = records[rank - 1][model + "_prob"]
            for k in [3, 4, 5]:
                expected[f"top{k}_all3"] = int(truth <= set(programs[:k]))
                if k != 4:
                    expected[f"top{k}_hits"] = len(truth & set(programs[:k]))
            for finish in [1, 2, 3]:
                for k in [3, 5]:
                    expected[f"actual{finish}_top{k}"] = int(actual[finish] in programs[:k])
            row = saved.loc[key, model]
            for name in c.METRICS:
                error = abs(float(expected[name]) - float(row[name]))
                require(error < 1e-12, (key, model, name))
                max_error = max(max_error, error)
                checks += 1
    old = saved.xs("old", level="model").reset_index()
    new = saved.xs("current", level="model").reset_index()
    wide = old.merge(new, on="race_key", suffixes=("_old", "_current"), validate="one_to_one")
    result = json.loads((c.OUT / "results.json").read_text())
    intervals = 0
    for row in result["groups"]:
        g = wide.copy()
        if row["scope"] != "all_races":
            g = g[g.axis_old.eq(g.axis_current)]
        if row["scope"] == "same_axis_and_axis_hit":
            g = g[g.rank1_hit_old.eq(1)]
        if row["meet"]:
            g = g[g.meet_old.eq(row["meet"])]
        require(len(g) == row["races"])
        g["delta"] = g[c.PRIMARY + "_current"] - g[c.PRIMARY + "_old"]
        days = g.groupby("race_date_old", sort=True).agg(
            delta=("delta", "sum"), n=("delta", "size")
        )
        ix = np.random.default_rng(20261025).integers(0, len(days), size=(2000, len(days)))
        distribution = np.array(
            [
                float(days.delta.to_numpy()[picked].sum() / days.n.to_numpy()[picked].sum())
                for picked in ix
            ]
        )
        np.testing.assert_allclose(
            row["metrics"][c.PRIMARY]["ci95"],
            np.quantile(distribution, [0.025, 0.975]),
            atol=1e-12,
            rtol=0,
        )
        for metric in c.METRICS:
            m = row["metrics"][metric]
            np.testing.assert_allclose(
                [m["old_total"], m["current_total"]],
                [g[metric + "_old"].sum(), g[metric + "_current"].sum()],
                atol=1e-9,
                rtol=0,
            )
        intervals += 1
    previous = json.loads((c.COMPARISON / "results.json").read_text())
    for row in result["native_pool_comparison"]:
        prior = next(
            x
            for x in previous["groups"]
            if x["variant"] == "personal_t2" and x["meet"] == row["meet"]
        )
        for metric in c.POOLS:
            a, b = row["metrics"][metric], prior["metrics"][metric]
            require(
                a["old_total"] == b["operating_total"]
                and a["current_total"] == b["candidate_total"]
            )
            np.testing.assert_allclose(a["ci95"], b["ci95"], atol=1e-12, rtol=0)
    require(int(old.rank1_hit.sum()) == 800 and int(new.rank1_hit.sum()) == 830)
    c.check()
    c.save(
        c.OUT / "verification.json",
        {
            "status": "passed",
            "matched_races": 1258,
            "matched_starters": 13315,
            "independent_rank_checks": rank_checks,
            "independent_metric_checks": checks,
            "axis_companion_trio_tickets_enumerated": 1258 * 2 * 6,
            "primary_bootstrap_intervals_reproduced": intervals,
            "prior_native_pool_totals_and_intervals_reproduced": True,
            "max_numeric_error": max_error,
            "input_models_registry_unchanged": True,
            "new_model_fits": 0,
            "actual_live_publications_compared": False,
            "new_independent_test": False,
            "production_changed": False,
        },
    )
    print("Verified", checks, "metrics,", rank_checks, "ranks,", intervals, "intervals", flush=True)


if __name__ == "__main__":
    main()
