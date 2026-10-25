"""Post-result explanatory audits only; no candidate refit or tuning."""

import itertools
import json

import numpy as np
import pandas as pd
import run as r
from scipy.special import expit


def main():
    r.check()
    p = pd.read_parquet(r.OUT / "predictions.parquet")
    d = pd.read_parquet(r.SOURCE)
    expected = []
    for row in p.itertuples():
        if not np.isfinite([row.early, row.g3f, row.g1f]).all():
            label = "missing"
        elif row.early <= 0:
            label = "no_early_advantage"
        elif row.g3f > 0 and row.g1f > 0:
            label = "early_fast_both_finish_fast"
        elif row.g3f <= 0 and row.g1f <= 0:
            label = "early_fast_both_finish_slow"
        else:
            label = "early_fast_finish_mixed"
        expected.append(label)
    assert np.array_equal(expected, p.profile)
    profiles = pd.read_csv(r.OUT / "profiles.csv", dtype={"period": str})
    allocation = pd.read_csv(r.OUT / "outcome_allocation.csv", dtype={"period": str})
    deltas = pd.read_csv(r.OUT / "paired_differences.csv", dtype={"period": str})
    checked = alloc_checked = 0
    for period, frame in r.periods(p):
        for name, g in frame[frame.is_target].groupby("profile"):
            for variant in r.VARIANTS:
                row = profiles[
                    profiles.period.eq(period)
                    & profiles.profile.eq(name)
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
                delta = (g[variant] - outcome) ** 2 - (g.joint - outcome) ** 2
                assert row.n == len(g)
                assert np.allclose(
                    [
                        row.early,
                        row.g3f,
                        row.g1f,
                        row.risk,
                        row.brier_difference,
                        row.brier_difference_sum,
                    ],
                    [
                        g.early.mean(),
                        g.g3f.mean(),
                        g.g1f.mean(),
                        g[variant].mean(),
                        delta.mean(),
                        delta.sum(),
                    ],
                    atol=1e-14,
                    rtol=0,
                )
                alloc_checked += 1
        for variant in r.FEATURES:
            h = allocation[allocation.period.eq(period) & allocation.variant.eq(variant)]
            ref = deltas[
                deltas.period.eq(period)
                & deltas.group.eq("target")
                & deltas.variant.eq(variant)
                & deltas.reference.eq("joint")
                & deltas.metric.eq("brier")
            ].iloc[0]
            assert np.isclose(h.brier_difference_sum.sum() / h.n.sum(), ref.difference, atol=1e-14)
    model = json.loads((r.OUT / "models/finish_interaction_2026.json").read_text())
    for row in pd.read_csv(r.OUT / "examples.csv").itertuples():
        assert row.raw_top3 == 0.75 and row.early == 0.5 and row.recent == 0.5
        z = {
            n: np.clip(
                (getattr(row, n) - model["scales"][n]["mean"]) / model["scales"][n]["std"], -3, 3
            )
            for n in model["features"]
        }
        x = [1.0]
        for n in model["features"]:
            x += [z[n], 0.0]
        exposure = np.clip(max(row.early, 0) / model["scales"]["early"]["std"], 0, 3)
        x += [exposure * z["g3f"], exposure * z["g1f"]]
        q = expit(np.log(0.25 / 0.75) + np.array(x) @ model["coefficients"])
        assert np.isclose(row.adjusted_top3, 1 - q, atol=1e-14)
    correlations = []
    for year in [2024, 2025, 2026]:
        train = d[d.year.lt(year) & r.target(d)]
        f = pd.DataFrame(
            dict(
                early=-train.axis_gap_section_early_mean3,
                recent=train.axis_moist_last3_record_index_mean,
                g3f=-train.axis_gap_section_last600_mean3,
                g1f=-train.axis_gap_section_late_mean3,
            )
        )
        for left, right in itertools.combinations(f.columns, 2):
            h = f[[left, right]].dropna()
            correlations.append(
                dict(
                    evaluation_year=year,
                    left=left,
                    right=right,
                    n=len(h),
                    pearson=float(h[left].corr(h[right])),
                )
            )
    pd.DataFrame(correlations).to_csv(r.OUT / "feature_correlation.csv", index=False)
    dec = json.loads((r.OUT / "decision.json").read_text())
    primary = deltas.query(
        "group=='target' and variant=='finish_interaction' "
        "and reference=='joint' and metric=='brier'"
    )
    allrow = primary[primary.period.eq("all")].iloc[0]
    consistent = (
        allrow.high < 0
        and primary[primary.period.isin(["2024", "2025", "2026"])].difference.lt(0).all()
    )
    assert np.allclose(
        [dec["primary_difference"], dec["primary_low"], dec["primary_high"]],
        [allrow.difference, allrow.low, allrow.high],
    )
    assert dec["consistent_evidence"] == bool(consistent) and not dec["promotion"]
    r.save(
        r.OUT / "diagnostic_audit.json",
        dict(
            status="passed",
            script_sha256=r.sha(r.HERE / "audit_diagnostics.py"),
            profiles_classified=len(p),
            profile_metric_rows=checked,
            allocation_rows=alloc_checked,
            examples=9,
            diagnostic_only=True,
            refits=0,
        ),
    )
    r.check()
    print("Diagnostic verification passed", checked, alloc_checked)
    print(pd.DataFrame(correlations).to_string(index=False))


if __name__ == "__main__":
    main()
