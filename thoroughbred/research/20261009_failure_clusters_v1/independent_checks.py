"""Formula-based probability and cell-weight audits, independent of run helpers."""

import json

import numpy as np
import pandas as pd
import run as e


def main():
    e.check()
    f = pd.read_parquet(e.OUT / "runner_inputs.parquet")
    low = pd.read_parquet(e.OUT / "low_rank_runners.parquet")
    races = pd.read_parquet(e.OUT / "clustered_races.parquet")
    summaries = pd.read_csv(e.OUT / "runner_condition_summary.csv")
    # Elementary symmetric polynomial marginal; no enumeration of triple scores.
    for _, g in f.groupby("race_key"):
        z = g.score.to_numpy() / g.tau.iloc[0]
        w = np.exp(z - z.max())
        others = w.sum() - w
        pair = (others**2 - (np.square(w).sum() - w**2)) / 2
        unnormalized = w * pair
        p = unnormalized / (unnormalized.sum() / 3)
        np.testing.assert_allclose(p, g.prob_top3, rtol=1e-11, atol=1e-12)
    # Independent cell iteration, without the main pivot/unstack implementation.
    strata = ["year", "meet", "distance_band", "grade_band", "field_band", "rank_band"]
    for row in summaries.itertuples():
        period = str(row.period)
        one = (
            low
            if period == "all"
            else low[low.year.ge(2025)]
            if period == "2025_2026"
            else low[low.year.eq(int(period))]
        )
        flags = e.flags(one)
        member = (
            one.cluster.eq(int(row.condition.split("_")[1]))
            if row.condition.startswith("cluster_")
            else pd.Series(True, index=one.index)
        )
        if not row.condition.startswith("cluster_"):
            for name in row.condition.split(" & "):
                member &= flags[name]
        weight = actual = expected = 0
        for _, cell in one.groupby(strata):
            yes = cell[member.loc[cell.index]]
            no = cell[~member.loc[cell.index]]
            if len(yes) >= 3 and len(no) >= 3:
                weight += len(yes)
                actual += yes.top3.sum()
                expected += len(yes) * no.top3.mean()
        if weight:
            assert weight == row.matched_runners
            assert abs(actual / weight - row.matched_actual_rate) < 1e-12
            assert abs(expected / weight - row.matched_control_rate) < 1e-12
    # Independent date aggregation using integer codes, then the frozen resampling seed.
    later = low[low.year.ge(2025)].reset_index(drop=True)
    member = (
        later.g3f_pct.ge(2 / 3)
        & later.g1f_pct.ge(2 / 3)
        & later.section_last600_n5.ge(3)
        & later.section_late_n5.ge(3)
        & later.style_recovery_mean5.ge(0.4)
        & later.style_recovery_n5.ge(3)
    )
    codes, dates = pd.factorize(later.race_date, sort=True)
    residual = (later.top3 - later.prob_top3).to_numpy()
    selected = member.to_numpy()
    sums = [
        np.bincount(codes, weights=residual * mask, minlength=len(dates))
        for mask in [selected, ~selected]
    ]
    counts = [
        np.bincount(codes, weights=mask.astype(int), minlength=len(dates))
        for mask in [selected, ~selected]
    ]
    ix = np.random.default_rng(e.SEED).integers(0, len(dates), (2000, len(dates)))
    draws = sums[0][ix].sum(1) / counts[0][ix].sum(1) - sums[1][ix].sum(1) / counts[1][ix].sum(1)
    row = summaries[
        (summaries.period.eq("2025_2026"))
        & summaries.condition.eq("late_both_topthird & recover_often")
    ].iloc[0]
    np.testing.assert_allclose(
        np.quantile(draws, [0.025, 0.975]),
        [row.excess_difference_ci_low, row.excess_difference_ci_high],
        atol=1e-12,
    )
    joined = later.merge(
        races[["race_key", "trio_fail", "hit53", "outside5_count"]],
        on="race_key",
        validate="many_to_one",
    )
    selected_winners = joined[member.to_numpy() & joined.top3.eq(1)]
    selected_winners.to_csv(e.OUT / "late_recovery_winners.csv", index=False)
    audit = dict(
        later_races=int(races.year.ge(2025).sum()),
        condition_runners=int(member.sum()),
        condition_winners=len(selected_winners),
        winners_in_failed_races=int(selected_winners.trio_fail.sum()),
        failed_races_with_condition_winner=int(
            selected_winners[selected_winners.trio_fail.eq(1)].race_key.nunique()
        ),
        condition_winner_finish_counts={
            str(k): int(v) for k, v in selected_winners.outcome.value_counts().sort_index().items()
        },
        condition_failed_races_rescued53=int(
            selected_winners[selected_winners.trio_fail.eq(1)]
            .drop_duplicates("race_key")
            .hit53.sum()
        ),
    )
    subgroup = []
    for keys, g in joined.groupby(["year", "distance_band"]):
        m = (
            g.g3f_pct.ge(2 / 3)
            & g.g1f_pct.ge(2 / 3)
            & g.section_last600_n5.ge(3)
            & g.section_late_n5.ge(3)
            & g.style_recovery_mean5.ge(0.4)
            & g.style_recovery_n5.ge(3)
        )
        group = g[m]
        subgroup.append(
            dict(
                year=int(keys[0]),
                distance_band=keys[1],
                runners=len(group),
                actual_top3=int(group.top3.sum()),
                actual_rate=float(group.top3.mean()),
                predicted_rate=float(group.prob_top3.mean()),
            )
        )
    pd.DataFrame(subgroup).to_csv(e.OUT / "late_recovery_distance_diagnostic.csv", index=False)
    e.save(e.OUT / "failure_linkage.json", audit)
    e.save(
        e.OUT / "independent_checks.json",
        dict(
            status="passed",
            probability_formula="elementary_symmetric_polynomial",
            matching="independent_cell_iteration_all_summaries",
            bootstrap="integer_date_bincount_strongest_frozen_rule",
            linkage=audit,
            code_sha256=e.sha(e.HERE / "independent_checks.py"),
        ),
    )
    e.check()
    print(json.dumps(audit, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
