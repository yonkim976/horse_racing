"""Independent fit/prediction, component isolation, and paired loss verification."""

# ruff: noqa: B007 -- pandas query references the loop variables.

import json

import numpy as np
import pandas as pd
import run as a
from scipy.special import expit, logit


def main():
    a.check()
    e = a.e
    d = pd.read_parquet(a.PRIOR / "outputs/race_inputs.parquet")
    p = pd.read_parquet(a.OUT / "risk_predictions.parquet")
    old = pd.read_parquet(a.PRIOR / "outputs/risk_predictions.parquet")
    pd.testing.assert_frame_equal(p[p.variant.isin(a.REUSED)].reset_index(drop=True), old)
    assert len(p) == 4799 * 7 and p.risk.between(0, 1).all()
    assert p.groupby(["race_key", "variant"]).size().eq(1).all()
    assert p.groupby("variant").collapsed.sum().eq(1937).all()
    x = e.design(d)
    mutated = d.copy()
    mutated["collapsed"] = 1 - d.collapsed
    np.testing.assert_array_equal(x, e.design(mutated))
    assert a.FEATURE_SETS == {
        "early_only": [0, 1, 2, 5],
        "distance_only": [0, 1, 3, 6],
        "grade5_only": [0, 1, 4, 7],
        "grade5_local_raw": [4],
    }
    for year in [2024, 2025, 2026]:
        train, prior, test = d.year.lt(year), d.year.eq(year - 1), d.year.eq(year)
        for variant, indices in a.FEATURE_SETS.items():
            model = json.loads((a.OUT / "models" / f"{variant}_{year}.json").read_text())
            beta = np.array(model["coefficients"])
            assert model["indices"] == indices and model["features"] == [
                e.FEATURES[i] for i in indices
            ]
            assert model["train_n"] == train.sum() and model["train_years"] == list(
                range(2020, year)
            )
            assert model["train_end"] == str(d.loc[train, "race_date"].max().date())
            assert pd.Timestamp(model["train_end"]) < d.loc[test, "race_date"].min()
            z = x[train][:, indices] @ beta
            center, penalty = np.zeros(len(beta)), np.full(len(beta), e.L2)
            if variant == "grade5_local_raw":
                z += logit(d.loc[train, "base_risk"].to_numpy())
            else:
                center[1] = 1
                penalty[0] = 0
            grad = x[train][:, indices].T @ (
                expit(z) - d.loc[train, "collapsed"].to_numpy()
            ) + penalty * (beta - center)
            assert np.max(np.abs(grad)) < 1e-4
            risks = []
            for mask in [test, prior]:
                z = x[mask][:, indices] @ beta
                if variant == "grade5_local_raw":
                    z += logit(d.loc[mask, "base_risk"].to_numpy())
                risk = expit(z)
                if variant == "grade5_local_raw":
                    risk = np.where(x[mask, 4] == 0, d.loc[mask, "base_risk"].to_numpy(), risk)
                risks.append(risk)
            rows = (
                p[p.year.eq(year) & p.variant.eq(variant)]
                .set_index("race_key")
                .loc[d.loc[test, "race_key"]]
            )
            np.testing.assert_allclose(rows.risk, risks[0], atol=1e-14)
            threshold = np.quantile(risks[1], 0.7)
            np.testing.assert_allclose(rows.threshold, threshold, atol=1e-14)
            np.testing.assert_array_equal(rows.flag, risks[0] >= threshold)
            np.testing.assert_array_equal(rows.axis_number, d.loc[test, "axis_number"])
            if variant == "grade5_local_raw":
                other = rows.high_probability_grade5.eq(0)
                np.testing.assert_array_equal(rows.loc[other, "risk"], rows.loc[other, "base_risk"])
    quality = pd.read_csv(a.OUT / "quality.csv", dtype={"period": str})
    diff = pd.read_csv(a.OUT / "paired_differences.csv", dtype={"period": str})
    intervals = 0
    for tag, frame in e.periods(p):
        for group, g in a.groups(frame):
            wide = g.pivot(index="race_key", columns="variant", values="risk")
            meta = g.drop_duplicates("race_key").set_index("race_key").loc[wide.index]
            for variant, h in g.groupby("variant"):
                row = quality.query("period==@tag and group==@group and variant==@variant").iloc[0]
                y, q = h.collapsed.to_numpy(), h.risk.to_numpy()
                np.testing.assert_allclose(
                    [row.brier, row.logloss, row.mean_risk, row.observed_risk],
                    [
                        np.mean((q - y) ** 2),
                        np.mean(-y * np.log(q) - (1 - y) * np.log1p(-q)),
                        q.mean(),
                        y.mean(),
                    ],
                )
                assert row.n == len(h) and row.failures == y.sum()
                flag = h.flag.to_numpy()
                assert row.flagged == flag.sum() and row.flagged_failures == y[flag].sum()
                assert row.false_alarms == (1 - y[flag]).sum()
                if (~flag).any():
                    np.testing.assert_allclose(row.quiet_axis_top3, 1 - y[~flag].mean())
                else:
                    assert pd.isna(row.quiet_axis_top3)
            for row in diff[diff.period.eq(tag) & diff.group.eq(group)].itertuples():
                left, right, y = (
                    wide[row.left].to_numpy(),
                    wide[row.right].to_numpy(),
                    meta.collapsed.to_numpy(),
                )
                delta = (
                    (left - y) ** 2 - (right - y) ** 2
                    if row.metric == "brier"
                    else -y * np.log(left / right) - (1 - y) * np.log((1 - left) / (1 - right))
                )
                np.testing.assert_allclose(row.difference, delta.mean(), atol=1e-12)
                daily = (
                    pd.DataFrame(dict(date=meta.race_date.to_numpy(), value=delta))
                    .groupby("date")
                    .value.agg(["sum", "count"])
                )
                rng = np.random.default_rng(e.SEED)
                weights = rng.multinomial(len(daily), np.full(len(daily), 1 / len(daily)), e.B)
                draw = (weights @ daily["sum"].to_numpy()) / (
                    weights @ daily["count"].to_numpy(dtype=float)
                )
                np.testing.assert_allclose(
                    [row.low, row.high, row.bonferroni3_low, row.bonferroni3_high],
                    np.quantile(draw, [0.025, 0.975, 0.05 / 6, 1 - 0.05 / 6]),
                    atol=1e-12,
                )
                intervals += 1
    assert diff.primary_family.sum() == 3
    outside = diff.query(
        "group=='outside_high_probability_grade5' and left=='grade5_local_raw' and right=='raw'"
    )
    assert outside[["difference", "low", "high"]].eq(0).all().all()
    # Full local gain is exactly weighted target-subgroup gain.
    for tag in ["all", "2024", "2025", "2026", "2025_26"]:
        rows = diff.query(
            "period==@tag and left=='grade5_local_raw' and right=='raw' and metric=='brier'"
        ).set_index("group")
        np.testing.assert_allclose(
            rows.loc["all", "difference"],
            rows.loc["high_probability_grade5", "difference"]
            * rows.loc["high_probability_grade5", "n"]
            / rows.loc["all", "n"],
            atol=1e-12,
        )
    a.check()
    a.save(
        a.OUT / "verification.json",
        dict(
            status="passed",
            races=4799,
            new_small_models=12,
            reused_variants_exact=True,
            allowed_feature_sets_verified=True,
            local_outside_probabilities_exactly_preserved=True,
            current_outcome_mutation_invariant=True,
            training_boundaries_verified=True,
            stored_predictions_reproduced=True,
            quality_rows=len(quality),
            paired_interval_rows=intervals,
            primary_family_count=3,
            existing_future_contract_unchanged=True,
            existing_history_audit_reference=str(
                (a.PRIOR / "outputs/verification.json").relative_to(a.ROOT)
            ),
        ),
    )
    print("Verified", len(quality), "quality rows;", intervals, "paired rows", flush=True)


if __name__ == "__main__":
    main()
