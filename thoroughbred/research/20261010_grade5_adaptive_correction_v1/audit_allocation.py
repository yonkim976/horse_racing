"""Post-result diagnostics only; no refit or candidate selection."""

import json

import numpy as np
import pandas as pd
import run as r
from scipy.special import expit


def main():
    r.check()
    p = pd.read_parquet(r.OUT / "predictions.parquet")
    d = pd.read_parquet(r.SOURCE).set_index("race_key").loc[p.race_key].reset_index()
    rows, checked_profiles = [], 0
    for year in [2024, 2025, 2026]:
        model = json.loads((r.OUT / "models" / f"joint_{year}.json").read_text())
        g = p[p.year.eq(year) & p.is_target]
        for profile, h in g.groupby("profile"):
            v = d[d.race_key.isin(h.race_key)]
            early, recent = -v.axis_gap_section_early_mean3, v.axis_moist_last3_record_index_mean
            for ei, ri in zip(early, recent, strict=True):
                label = (
                    "missing"
                    if not np.isfinite(ei) or not np.isfinite(ri)
                    else (
                        (
                            "early_high"
                            if ei >= model["scales"]["early_advantage_seconds"]["mean"]
                            else "early_low"
                        )
                        + (
                            "_recent_high"
                            if ri >= model["scales"]["recent_record_index"]["mean"]
                            else "_recent_low"
                        )
                    )
                )
                assert label == profile
                checked_profiles += 1
        for outcome, h in g.groupby("collapsed"):
            delta = (h.joint - outcome) ** 2 - (h.constant - outcome) ** 2
            rows.append(
                dict(
                    year=year,
                    collapsed=int(outcome),
                    n=len(h),
                    early_advantage=float(h.early_advantage_seconds.mean()),
                    recent_record=float(h.recent_record_index.mean()),
                    constant_risk=float(h.constant.mean()),
                    joint_risk=float(h.joint.mean()),
                    brier_difference=float(delta.mean()),
                    brier_difference_sum=float(delta.sum()),
                )
            )
    rows = pd.DataFrame(rows)
    rows.to_csv(r.OUT / "outcome_allocation.csv", index=False)
    differences = pd.read_csv(r.OUT / "paired_differences.csv")
    for year, h in rows.groupby("year"):
        row = differences[
            differences.period.eq(str(year))
            & differences.group.eq("target")
            & differences.variant.eq("joint")
            & differences.reference.eq("constant")
            & differences.metric.eq("brier")
        ].iloc[0]
        assert np.isclose(h.brier_difference_sum.sum() / h.n.sum(), row.difference, atol=1e-14)
    profiles = pd.read_csv(r.OUT / "profiles.csv")
    profile_rows = 0
    for period, frame in r.periods(p):
        for name, h in frame[frame.is_target].groupby("profile"):
            for variant in r.VARIANTS:
                q = profiles[
                    profiles.period.eq(period)
                    & profiles.profile.eq(name)
                    & profiles.variant.eq(variant)
                ].iloc[0]
                assert q.n == len(h)
                assert np.isclose(q.actual_top3, 1 - h.collapsed.mean())
                assert np.isclose(q.mean_top3, 1 - h[variant].mean())
                assert np.isclose(q.brier, ((h[variant] - h.collapsed) ** 2).mean())
                profile_rows += 1
    model = json.loads((r.OUT / "models/joint_2026.json").read_text())
    examples = pd.read_csv(r.OUT / "examples.csv")
    for row in examples.itertuples():
        z1 = np.clip(
            (row.early_advantage_seconds - model["scales"]["early_advantage_seconds"]["mean"])
            / model["scales"]["early_advantage_seconds"]["std"],
            -3,
            3,
        )
        z2 = np.clip(
            (row.recent_record_index - model["scales"]["recent_record_index"]["mean"])
            / model["scales"]["recent_record_index"]["std"],
            -3,
            3,
        )
        c = model["coefficients"]
        q = expit(np.log(0.25 / 0.75) + c[0] + c[1] * z1 + c[3] * z2)
        assert np.isclose(row.adjusted_top3, 1 - q, atol=1e-14)
        assert np.isclose(row.cut, q - 0.25, atol=1e-14)
    decision = json.loads((r.OUT / "decision.json").read_text())
    primary = differences.query(
        "period=='all' and group=='target' and variant=='joint' "
        "and reference=='constant' and metric=='brier'"
    ).iloc[0]
    assert np.isclose(decision["primary_difference"], primary.difference)
    assert not decision["consistent_evidence"] and not decision["promotion"]
    r.save(
        r.OUT / "allocation_audit.json",
        dict(
            status="passed",
            script_sha256=r.sha(r.HERE / "audit_allocation.py"),
            profiles_classified=checked_profiles,
            profile_metric_rows=profile_rows,
            examples=9,
            diagnostic_only=True,
            refits=0,
        ),
    )
    r.check()
    print(rows.to_string(index=False))


if __name__ == "__main__":
    main()
