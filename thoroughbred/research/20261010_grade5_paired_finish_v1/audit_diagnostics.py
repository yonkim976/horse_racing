"""Verify explanatory tables only; no refit or post-result threshold search."""

import json

import numpy as np
import pandas as pd
import run as r


def main():
    r.check()
    p = pd.read_parquet(r.OUT / "predictions.parquet")
    profiles = pd.read_csv(r.OUT / "profiles.csv", dtype={"period": str})
    allocation = pd.read_csv(r.OUT / "outcome_allocation.csv", dtype={"period": str})
    differences = pd.read_csv(r.OUT / "paired_differences.csv", dtype={"period": str})
    checked = outcome_checks = 0
    for period, frame in r.periods(p):
        for label, g in frame[frame.is_target].groupby("profile"):
            for variant in r.VARIANTS:
                row = profiles[
                    profiles.period.eq(period)
                    & profiles.profile.eq(label)
                    & profiles.variant.eq(variant)
                ].iloc[0]
                assert row.n == len(g)
                assert np.allclose(
                    [row.actual_top3, row.mean_top3, row.brier],
                    [
                        1 - g.collapsed.mean(),
                        1 - g[variant].mean(),
                        ((g[variant] - g.collapsed) ** 2).mean(),
                    ],
                    atol=1e-14,
                    rtol=0,
                )
                checked += 1
        for outcome, g in frame[frame.is_target].groupby("collapsed"):
            for variant in ["joint", "constant", *r.FEATURES]:
                row = allocation[
                    allocation.period.eq(period)
                    & allocation.collapsed.eq(outcome)
                    & allocation.variant.eq(variant)
                ].iloc[0]
                v = (g[variant] - outcome) ** 2 - (g.joint - outcome) ** 2
                assert row.n == len(g)
                assert np.allclose(
                    [
                        row.early,
                        row.paired_g3,
                        row.paired_g1,
                        row.risk,
                        row.brier_difference,
                        row.brier_difference_sum,
                    ],
                    [
                        g.early.mean(),
                        g.paired_g3.mean(),
                        g.paired_g1.mean(),
                        g[variant].mean(),
                        v.mean(),
                        v.sum(),
                    ],
                    atol=1e-14,
                    rtol=0,
                    equal_nan=True,
                )
                outcome_checks += 1
        for variant in r.FEATURES:
            h = allocation[allocation.period.eq(period) & allocation.variant.eq(variant)]
            row = differences[
                differences.period.eq(period)
                & differences.group.eq("target")
                & differences.variant.eq(variant)
                & differences.reference.eq("joint")
                & differences.metric.eq("brier")
            ].iloc[0]
            assert np.isclose(h.brier_difference_sum.sum() / h.n.sum(), row.difference, atol=1e-14)
    dec = json.loads((r.OUT / "decision.json").read_text())
    primary = differences.query(
        "group=='target' and variant=='paired_full' and reference=='joint' and metric=='brier'"
    )
    row = primary[primary.period.eq("all")].iloc[0]
    consistent = (
        row.high < 0
        and primary[primary.period.isin(["2024", "2025", "2026"])].difference.lt(0).all()
    )
    assert np.allclose(
        [dec["primary_difference"], dec["primary_low"], dec["primary_high"]],
        [row.difference, row.low, row.high],
    )
    assert dec["consistent_evidence"] == bool(consistent) and not dec["promotion"]
    r.save(
        r.OUT / "diagnostic_audit.json",
        dict(
            status="passed",
            script_sha256=r.sha(r.HERE / "audit_diagnostics.py"),
            profile_metric_rows=checked,
            allocation_rows=outcome_checks,
            refits=0,
            diagnostic_only=True,
        ),
    )
    r.check()
    print("Diagnostic tables verified", checked, outcome_checks)


if __name__ == "__main__":
    main()
