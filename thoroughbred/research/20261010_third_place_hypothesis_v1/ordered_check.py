"""One-slot-vs-one-slot comparison from the frozen operating ordered joint."""

import numpy as np
import pandas as pd
import run as e


def main():
    e.check()
    paths = [
        e.HERE / "ORDERED_PLAN.md",
        e.HERE / "ordered_check.py",
        e.OP / "operating_runner_predictions.parquet",
        e.OUT / "races.parquet",
    ]
    e.save(
        e.OUT / "ordered_source_lock.json", {str(p.relative_to(e.ROOT)): e.sha(p) for p in paths}
    )
    race = pd.read_parquet(e.OUT / "races.parquet")
    common = set(race[race.variant.eq("operating_snapshot2026")].race_key)
    p = pd.read_parquet(e.OP / "operating_runner_predictions.parquet")
    p["race_key"] = [
        f"{int(m)}:{str(d).replace('-', '')}:{int(str(k).rsplit(':', 1)[1])}"
        for m, d, k in zip(p.meet, p.race_date, p.race_key, strict=True)
    ]
    p = p[p.race_key.isin(common)].copy()
    p["exact1"] = p.prob_win
    p["exact2"] = p.prob_top2 - p.prob_win
    p["exact3"] = p.prob_top3 - p.prob_top2
    assert p[["exact1", "exact2", "exact3"]].min().min() >= -1e-12
    np.testing.assert_allclose(
        p.groupby("race_key")[["exact1", "exact2", "exact3"]].sum(), 1, atol=1e-12
    )
    rows = []
    for rid, g in p.groupby("race_key"):
        for place in [1, 2, 3]:
            col = f"exact{place}"
            order = g.sort_values([col, "program_no"], ascending=[False, True])
            y = order.outcome.eq(place).to_numpy()
            assert y.sum() == 1
            truth_rank = int(np.flatnonzero(y)[0]) + 1
            rows.append(
                dict(
                    race_key=rid,
                    race_date=g.race_date.iloc[0],
                    actual_place=place,
                    one_hit=int(truth_rank == 1),
                    top3_hit=int(truth_rank <= 3),
                    truth_rank=truth_rank,
                    maximum_probability=float(order[col].iloc[0]),
                    truth_probability=float(order.loc[order.outcome.eq(place), col].iloc[0]),
                    nll=float(-np.log(order.loc[order.outcome.eq(place), col].iloc[0])),
                )
            )
    r = pd.DataFrame(rows)
    r.to_parquet(e.OUT / "ordered_race_metrics.parquet", index=False)
    summaries = (
        r.groupby("actual_place")
        .agg(
            races=("race_key", "size"),
            hits=("one_hit", "sum"),
            hit_rate=("one_hit", "mean"),
            top3_rate=("top3_hit", "mean"),
            mean_maximum_probability=("maximum_probability", "mean"),
            mean_truth_rank=("truth_rank", "mean"),
            mean_nll=("nll", "mean"),
        )
        .reset_index()
    )
    summaries.to_csv(e.OUT / "ordered_summary.csv", index=False)
    pivot = r.pivot(
        index=["race_key", "race_date"], columns="actual_place", values="one_hit"
    ).reset_index()
    differences = []
    for earlier in [1, 2]:
        delta = pivot[3] - pivot[earlier]
        lo, hi = e.boot(pivot, delta)
        # Independent date aggregation audit, not the main pandas implementation.
        code, dates = pd.factorize(pivot.race_date, sort=True)
        total = np.bincount(code, weights=delta)
        counts = np.bincount(code)
        ix = np.random.default_rng(e.SEED).integers(0, len(dates), (2000, len(dates)))
        draws = total[ix].sum(1) / counts[ix].sum(1)
        np.testing.assert_allclose(np.quantile(draws, [0.025, 0.975]), [lo, hi], atol=1e-12)
        differences.append(
            dict(
                comparison=f"exact3_minus_exact{earlier}",
                races=len(pivot),
                difference=float(delta.mean()),
                ci_low=lo,
                ci_high=hi,
            )
        )
    pd.DataFrame(differences).to_csv(e.OUT / "ordered_paired_differences.csv", index=False)
    for rid, g in p.groupby("race_key"):
        for place, probability in [
            (1, g.prob_win),
            (2, g.prob_top2 - g.prob_win),
            (3, g.prob_top3 - g.prob_top2),
        ]:
            # Explicit lexicographic ordering independent of DataFrame sort.
            order = np.lexsort((g.program_no.to_numpy(), -probability.to_numpy()))
            actual = g.outcome.eq(place).to_numpy()[order]
            stored = r[r.race_key.eq(rid) & r.actual_place.eq(place)].iloc[0]
            assert stored.one_hit == int(actual[0])
            assert stored.top3_hit == int(actual[:3].any())
    e.save(
        e.OUT / "ordered_verification.json",
        dict(
            status="passed",
            operating_matched_races=len(pivot),
            probabilities_nested_and_each_sum_one=True,
            exact_probability_subtractions_valid=True,
            one_slot_targets_compared=True,
            ranking_and_paired_intervals_independently_recomputed=True,
            separately_trained_third_place_model=False,
            source_hashes_unchanged=True,
        ),
    )
    e.check()
    print(summaries.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
