"""Independent scalar enumeration of the complete frozen comparison."""

import itertools

import numpy as np
import pandas as pd
import run as e
from scipy.special import softmax


def main():
    e.check()
    f = pd.read_parquet(e.SRC / "oof_runners.parquet")
    f = f[f.year.ge(2024)]
    metrics = pd.read_parquet(e.OUT / "race_metrics.parquet")
    tickets = pd.read_parquet(e.OUT / "tickets.parquet")
    flag = pd.read_parquet(e.SRC / "risk_predictions.parquet")
    flag = flag[flag.variant.eq("context")].set_index("race_key").flag.to_dict()
    old = pd.read_csv(e.SRC / "race_metrics.csv")
    saved = {
        (r, p): g.sort_values("selection_rank")
        for (r, p), g in tickets.groupby(["race_key", "policy"], sort=False)
    }
    tested = 0
    for rid, g in f.groupby("race_key", sort=False):
        g = g.sort_values(["score", "program_no"], ascending=[False, True]).reset_index(drop=True)
        nums = g.program_no.to_numpy()
        scores = g.score.to_numpy() / g.tau.iloc[0]
        combos = list(itertools.combinations(range(len(g)), 3))
        prob = softmax([sum(sorted(scores[list(t)])) for t in combos])
        ordered = sorted(
            range(len(combos)), key=lambda i: (-prob[i], tuple(sorted(nums[list(combos[i])])))
        )
        inside = [i for i in ordered if 0 in combos[i] and max(combos[i]) < 7][:6]
        outside = [i for i in ordered if 0 not in combos[i]][:6]
        wanted = {f"in{k}_out{6 - k}": inside[:k] + outside[: 6 - k] for k in range(7)}
        wanted.update(
            global6=ordered[:6],
            global12=ordered[:12],
            in6_out6=inside + outside,
            risk_add6=inside + outside if flag[rid] else inside,
        )
        truth = set(g.loc[g.outcome.between(1, 3), "program_no"])
        for policy, indices in wanted.items():
            old_tickets = saved[rid, policy]
            expected = [",".join(map(str, sorted(nums[list(combos[i])]))) for i in indices]
            assert old_tickets.programs.tolist() == expected
            assert len(set(expected)) == len(expected)
            assert np.max(np.abs(old_tickets.probability.to_numpy() - prob[indices])) < 1e-12
            assert old_tickets.hit.sum() == int(
                any(set(map(int, t.split(","))) == truth for t in expected)
            )
            tested += 1
    aggregate = metrics.groupby("policy").hit.sum()
    assert aggregate.in6_out0 == 1204 and aggregate.global6 == 1228
    assert metrics[metrics.policy.eq("risk_add6")].ticket_count.sum() == 4799 * 6 + 1434 * 6
    expected = old[old.policy.eq("fixed7")].set_index("race_key").hit
    actual = metrics[metrics.policy.eq("in6_out0")].set_index("race_key").hit
    assert expected.sort_index().equals(actual.sort_index())
    for _, r in pd.read_csv(e.OUT / "paired_differences.csv").iterrows():
        wide = metrics.pivot(index="race_key", columns="policy", values="hit")
        d = (wide[r.candidate] - wide[r.control]).to_numpy()
        dates = (
            metrics.drop_duplicates("race_key").set_index("race_key").loc[wide.index, "race_date"]
        )
        ag = pd.DataFrame({"d": d, "date": dates.to_numpy()}).groupby("date").d.agg(["sum", "size"])
        rng = np.random.default_rng(e.SEED)
        ix = rng.integers(len(ag), size=(2000, len(ag)))
        draws = ag["sum"].to_numpy()[ix].sum(1) / ag["size"].to_numpy()[ix].sum(1)
        assert (
            np.max(
                np.abs(
                    np.array([d.mean(), *np.quantile(draws, [0.025, 0.975])])
                    - [r.delta, r.ci_low, r.ci_high]
                )
            )
            < 1e-12
        )
    e.check()
    e.save(
        e.OUT / "verification.json",
        dict(
            status="passed",
            race_policies=tested,
            tickets=len(tickets),
            baseline_hits_reproduced=True,
            independent_enumeration=True,
            duplicate_free=True,
            budgets_verified=True,
            paired_bootstraps_replayed=True,
            source_hashes_unchanged=True,
            new_training=False,
            production_changed=False,
            selected_baseline_changed=False,
            database_access=False,
            jeju_access=False,
        ),
    )
    print("Verified", tested, len(tickets), flush=True)


if __name__ == "__main__":
    main()
