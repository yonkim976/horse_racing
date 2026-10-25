"""Audit collapse tables, standardized controls, and conditional residuals."""

import numpy as np
import pandas as pd
import run as e
from verify import selected


def main():
    e.check()
    r = pd.read_parquet(e.OUT / "races.parquet")
    c = pd.read_csv(e.OUT / "collapse_summary.csv")
    for row in c.itertuples():
        one = selected(r, row.variant, row.cohort, row.period)
        if row.condition.startswith("top2_placed_"):
            mask = one.top2_placed.eq(int(row.condition.rsplit("_", 1)[1]))
        else:
            mask = one.axis_out.eq(int(row.condition.endswith("out")))
            if row.condition.startswith("strong_"):
                mask &= one.axis_probability.ge(0.6)
        g = one[mask]
        assert len(g) == row.races
        for col in ["outside1", "outside2", "outside3", "rank3"]:
            assert abs(g[col].mean() - getattr(row, col)) < 1e-12
    matched = pd.read_csv(e.OUT / "matched_collapse.csv")
    for row in matched.itertuples():
        one = selected(r, row.variant, row.cohort, row.period)
        strata = [
            "year",
            "meet",
            "distance_band",
            "grade_band",
            "field_band",
            "axis_probability_band",
        ]
        # Pivot cell sums and counts instead of the main independent cell loop.
        cells = (
            one.groupby(strata + ["axis_out"])[f"outside{row.actual_place}"]
            .agg(["sum", "size"])
            .unstack(fill_value=0)
        )
        valid = cells["size", 0].ge(3) & cells["size", 1].ge(3)
        cells = cells[valid]
        n = cells["size", 1].sum()
        actual = cells["sum", 1].sum() / n
        standard = ((cells["sum", 0] / cells["size", 0]) * cells["size", 1]).sum() / n
        assert n == row.matched_axis_out_races
        assert abs(actual - row.actual_rate) < 1e-12
        assert abs(standard - row.standardized_axis_placed_rate) < 1e-12
    mechanics = pd.read_csv(e.OUT / "conditional_mechanics.csv")
    for row in mechanics.itertuples():
        one = selected(r, row.variant, row.cohort, row.period)
        g = one[one.axis_out.eq(row.axis_out)]
        assert len(g) == row.races
        delta = g.outside_count - g.expected_outside_observed_state
        assert abs(delta.mean() - row.residual) < 1e-12
        codes, dates = pd.factorize(g.race_date, sort=True)
        sums = np.bincount(codes, weights=delta)
        counts = np.bincount(codes)
        ix = np.random.default_rng(e.SEED).integers(0, len(dates), (2000, len(dates)))
        means = sums[ix].sum(1) / counts[ix].sum(1)
        np.testing.assert_allclose(
            np.quantile(means, [0.025, 0.975]), [row.ci_low, row.ci_high], atol=1e-12
        )
    e.save(
        e.OUT / "conditions_audit.json",
        dict(
            status="passed",
            collapse_table_rows_checked=len(c),
            matched_control_rows_checked=len(matched),
            conditional_residual_intervals_checked=len(mechanics),
            standardized_matching_independently_recomputed=True,
            observed_state_not_causal=True,
            code_sha256=e.sha(e.HERE / "audit_conditions.py"),
        ),
    )
    e.check()
    print("Condition statistics verified", len(c), len(matched), len(mechanics), flush=True)


if __name__ == "__main__":
    main()
