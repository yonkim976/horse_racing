"""Independent rank, conditional-distribution, cohort, and bootstrap checks."""

import itertools

import numpy as np
import pandas as pd
import run as e


def selected(r, variant, cohort, period):
    one = r[r.variant.eq(variant)]
    if cohort == "matched_2026":
        one = one[one.matched_2026]
    if str(period) != "all":
        one = one[one.year.eq(int(period))]
    return one


def main():
    e.check()
    p = pd.read_parquet(e.OUT / "runners.parquet")
    r = pd.read_parquet(e.OUT / "races.parquet")
    lookup = r.set_index(["variant", "race_key"])
    for variant in ["month_gate_weight22", "style_history53"]:
        assert len(p[p.variant.eq(variant)]) == 50754
        assert len(r[r.variant.eq(variant)]) == 4799
    assert len(r[r.variant.eq("operating_snapshot2026")]) == 1258
    assert r[r.variant.eq("month_gate_weight22")].trio6.sum() == 1228
    assert r[r.variant.eq("style_history53")].trio6.sum() == 1313
    dates = pd.to_datetime(p.race_date)
    assert p.cutoff_date.le(dates - pd.Timedelta(days=2)).all()
    for col in ["history_source_date", "profile_source_date"]:
        assert (p[col].isna() | p[col].le(p.cutoff_date)).all()
    nulls = 0
    for key, g in p.groupby(["variant", "race_key"]):
        ordered = g.sort_values(["score", "program_no"], ascending=[False, True])
        assert np.array_equal(ordered.model_rank, np.arange(1, len(g) + 1))
        assert set(g[g.outcome.between(1, 3)].outcome) == {1, 2, 3}
        row = lookup.loc[key]
        axis = ordered.iloc[0]
        assert row.axis_out == int(not 1 <= axis.outcome <= 3)
        assert row.top2_placed == ordered.head(2).outcome.between(1, 3).sum()
        ranks = []
        for place in [1, 2, 3]:
            horse = g[g.outcome.eq(place)].iloc[0]
            assert row[f"rank{place}"] == horse.model_rank
            assert row[f"outside{place}"] == int(horse.model_rank > 5)
            ranks.append(int(horse.model_rank))
        assert row.outside_count == sum(k > 5 for k in ranks)
        assert abs(g.prob_top3.sum() - 3) < 1e-11
        if key[0] != "operating_snapshot2026":
            g = g.sort_values("program_no")
            scores = g.score.to_numpy() / g.tau.iloc[0]
            w = np.exp(scores - scores.max())
            sets = list(itertools.combinations(range(len(g)), 3))
            values = np.array([w[a] * w[b] * w[c] for a, b, c in sets])
            probabilities = values / values.sum()
            ai = int(np.flatnonzero(g.model_rank.eq(1))[0])
            contains = np.array([ai in s for s in sets])
            outsiders = np.array([sum(g.model_rank.iloc[j] > 5 for j in s) for s in sets])
            for state, mask in [("in", contains), ("out", ~contains)]:
                expected = np.average(outsiders[mask], weights=probabilities[mask])
                assert abs(expected - row["expected_outside_axis_" + state]) < 1e-11
            assert abs(probabilities[contains].sum() - row.axis_probability) < 1e-11
            nulls += 1
    summaries = pd.read_csv(e.OUT / "position_summary.csv")
    for row in summaries.itertuples():
        one = selected(r, row.variant, row.cohort, row.period)
        values = one[f"rank{row.actual_place}"]
        assert len(one) == row.races
        assert abs(values.mean() - row.mean_model_rank) < 1e-12
        assert abs(values.median() - row.median_model_rank) < 1e-12
        for n in [3, 5, 7]:
            assert values.le(n).sum() == getattr(row, f"top{n}_hits")
            assert abs(values.le(n).mean() - getattr(row, f"top{n}_capture")) < 1e-12
    # Independent integer date aggregation instead of the main dataframe pivot.
    differences = pd.read_csv(e.OUT / "paired_differences.csv")
    for row in differences.itertuples():
        one = selected(r, row.variant, row.cohort, row.period)
        if row.comparison.startswith("third_minus_"):
            earlier = int(row.comparison.rsplit("_", 1)[1])
            delta = (
                one.rank3 - one[f"rank{earlier}"]
                if row.metric == "rank"
                else one.rank3.le(5).astype(int) - one[f"rank{earlier}"].le(5).astype(int)
            )
            member = np.ones(len(one), bool)
            point = delta.mean()
        else:
            delta = (
                one.outside3 - one.outside2
                if row.metric == "third_outside_minus_second_outside"
                else one[row.metric]
            )
            member = one.axis_out.to_numpy() == 1
            point = delta[member].mean() - delta[~member].mean()
        assert abs(point - row.difference) < 1e-12
        codes, dates = pd.factorize(one.race_date, sort=True)
        ix = np.random.default_rng(e.SEED).integers(0, len(dates), (2000, len(dates)))
        sums = np.bincount(codes, weights=np.asarray(delta) * member, minlength=len(dates))
        counts = np.bincount(codes, weights=member.astype(int), minlength=len(dates))
        means = sums[ix].sum(1) / np.maximum(counts[ix].sum(1), 1)
        if not row.comparison.startswith("third_minus_"):
            sums = np.bincount(codes, weights=np.asarray(delta) * (~member), minlength=len(dates))
            counts = np.bincount(codes, weights=(~member).astype(int), minlength=len(dates))
            means -= sums[ix].sum(1) / np.maximum(counts[ix].sum(1), 1)
        np.testing.assert_allclose(
            np.quantile(means, [0.025, 0.975]), [row.ci_low, row.ci_high], atol=1e-12
        )
    for row in pd.read_csv(e.OUT / "miss_patterns.csv").itertuples():
        one = selected(r, row.variant, row.cohort, row.period)
        if row.scope == "top5_roster_miss":
            one = one[one.outside_count.gt(0)]
        elif row.scope == "trio6_fail":
            one = one[one.trio6.eq(0)]
        assert len(one) == row.denominator
        assert one.miss_pattern.eq(row.pattern).sum() == row.races
    # Complete common-roster/outcome equality across all three reference variants.
    for _, group in p[p.matched_2026].groupby("race_key"):
        signatures = [
            set(zip(g.program_no, g.horse_id, g.outcome, strict=True))
            for _, g in group.groupby("variant")
        ]
        assert len(signatures) == 3 and signatures[0] == signatures[1] == signatures[2]
    e.check()
    e.save(
        e.OUT / "verification.json",
        dict(
            status="passed",
            research_races_per_model=4799,
            operating_common_races=1258,
            condition_distributions_independently_recomputed=nulls,
            paired_confidence_intervals_recomputed=len(differences),
            exact_rosters_and_outcomes_matched=True,
            ranks_positions_and_capture_denominators_recomputed=True,
            top5_miss_patterns_recomputed=True,
            prior_source_dates_checked=True,
            source_hashes_unchanged=True,
            new_models=0,
            production_changed=False,
            selected_baseline_changed=False,
            jeju_access=False,
            database_access=False,
            future_period_access=False,
        ),
    )
    print("Verified", nulls, len(differences), flush=True)


if __name__ == "__main__":
    main()
