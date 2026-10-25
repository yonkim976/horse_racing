"""Independent reconciliation of cohort composition and fixed-cell decomposition."""

# ruff: noqa: B007 -- pandas query references loop variables.

import json

import numpy as np
import pandas as pd
import run as r
from scipy.special import expit, logit


def main():
    r.check()
    d = pd.read_parquet(r.OUT / "races.parquet")
    pd.testing.assert_frame_equal(d, r.load())
    assert len(d) == 4799 and d.target.sum() == 205
    assert d[d.target].groupby("year").size().to_dict() == {2024: 71, 2025: 78, 2026: 56}
    assert d[d.year.eq(2026)].race_date.max() == pd.Timestamp("2026-09-20")
    assert (d.target == (d.axis_probability.ge(0.7) & d.axis_grade.eq(5))).all()
    assert (d.calendar_matched == (d.race_date.dt.strftime("%m%d") <= "0920")).all()
    prior = (
        pd.read_parquet(r.PREV / "outputs/risk_predictions.parquet")
        .query("variant=='grade5_local_raw'")
        .set_index("race_key")
    )
    np.testing.assert_array_equal(d.corrected_risk, prior.loc[d.race_key].risk)
    summary = pd.read_csv(r.OUT / "summary.csv", dtype={"period": str})
    numeric = pd.read_csv(r.OUT / "numeric_shift.csv")
    cat = pd.read_csv(r.OUT / "categorical_shift.csv")
    standardized = pd.read_csv(r.OUT / "standardized.csv")
    cells = pd.read_csv(r.OUT / "standardization_cells.csv")
    interval_checks = 0
    for scope, frame in r.scopes(d):
        target = frame[frame.target]
        for row in summary[summary.scope.eq(scope)].itertuples():
            g = (
                target[target.time.eq(row.period)]
                if row.period == "2024_25"
                else target[target.year.eq(int(row.period))]
            )
            assert row.n == len(g) and row.failures == g.collapsed.sum()
            np.testing.assert_allclose(
                [row.mean_raw_risk, row.mean_corrected_risk, row.residual, row.brier_delta],
                [
                    g.base_risk.mean(),
                    g.corrected_risk.mean(),
                    (g.collapsed - g.base_risk).mean(),
                    (
                        (g.corrected_risk - g.collapsed) ** 2 - (g.base_risk - g.collapsed) ** 2
                    ).mean(),
                ],
            )
        old, new = target[target.time.eq("2024_25")], target[target.time.eq("2026")]
        boot = []
        for g in [old, new]:
            dates = sorted(g.race_date.unique())
            w = np.random.default_rng(r.SEED).multinomial(
                len(dates), np.full(len(dates), 1 / len(dates)), r.B
            )
            result = {}
            for col in ["collapsed", "residual", *r.NUMERIC]:
                daily = (
                    g.groupby("race_date")[col].agg(["sum", "count"]).reindex(dates, fill_value=0)
                )
                den = w @ daily["count"].to_numpy(dtype=float)
                result[col] = np.divide(
                    w @ daily["sum"].to_numpy(), den, out=np.full(r.B, np.nan), where=den > 0
                )
            boot.append(result)
        for row in numeric[numeric.scope.eq(scope)].itertuples():
            o, n = old[row.feature].dropna(), new[row.feature].dropna()
            assert row.old_n == len(o) and row.new_n == len(n)
            np.testing.assert_allclose(
                [row.old_mean, row.new_mean, row.difference],
                [o.mean(), n.mean(), n.mean() - o.mean()],
            )
            np.testing.assert_allclose(
                row.smd, (n.mean() - o.mean()) / np.sqrt((o.var() + n.var()) / 2)
            )
            delta = boot[1][row.feature] - boot[0][row.feature]
            delta = delta[np.isfinite(delta)]
            np.testing.assert_allclose(
                [row.low, row.high], np.quantile(delta, [0.025, 0.975]), atol=1e-12
            )
            interval_checks += 1
        differences = pd.read_csv(r.OUT / "year_differences.csv")
        for metric in ["collapsed", "residual"]:
            row = differences.query("scope==@scope and metric==@metric").iloc[0]
            np.testing.assert_allclose(row.difference, new[metric].mean() - old[metric].mean())
            delta = boot[1][metric] - boot[0][metric]
            np.testing.assert_allclose(
                [row.low, row.high], np.quantile(delta, [0.025, 0.975]), atol=1e-12
            )
            interval_checks += 1
        for col in r.CAT:
            rows = cat[cat.scope.eq(scope) & cat.feature.eq(col)]
            assert rows.old_n.sum() == len(old) and rows.new_n.sum() == len(new)
            for row in rows.itertuples():
                o, n = old[old[col].eq(row.level)], new[new[col].eq(row.level)]
                assert row.old_n == len(o) and row.new_n == len(n)
                np.testing.assert_allclose(
                    [row.old_share, row.new_share], [len(o) / len(old), len(n) / len(new)]
                )
        schemes = [(col, [col], 5, 3) for col in r.CAT] + [
            ("region_probability", ["meet_band", "prob_band"], 5, 3),
            ("region_season", ["meet_band", "season"], 5, 3),
            ("joint_context", ["meet_band", "prob_band", "distance_band", "field_band"], 3, 2),
        ]
        for name, keys, mo, mn in schemes:
            row = standardized.query("scope==@scope and scheme==@name").iloc[0]
            expected, c = r.standardize(target, keys, mo, mn)
            assert (
                row.cells == expected["cells"]
                and row.new_n == expected["new_n"]
                and row.old_n == expected["old_n"]
            )
            for metric in ["risk", "residual"]:
                if len(c):
                    table = cells[cells.scope.eq(scope) & cells.scheme.eq(name)]
                    assert len(table) == len(c)
                    weights = table.new_n / table.new_n.sum()
                    standardized_old = (weights * table["old_" + metric]).sum()
                    np.testing.assert_allclose(
                        getattr(row, "standardized_old_" + metric), standardized_old
                    )
                    np.testing.assert_allclose(
                        getattr(row, "total_" + metric),
                        getattr(row, "composition_" + metric) + getattr(row, "within_" + metric),
                        atol=1e-12,
                    )
    cf = pd.read_csv(r.OUT / "coefficient_counterfactual.csv")
    new = d[d.target & d.year.eq(2026)]
    for row in cf.itertuples():
        p = (
            new.base_risk.to_numpy()
            if row.beta == 0
            else expit(logit(new.base_risk.to_numpy()) + row.beta)
        )
        np.testing.assert_allclose(
            [row.mean_risk, row.overshoot, row.brier],
            [
                p.mean(),
                p.mean() - new.collapsed.mean(),
                np.mean((p - new.collapsed.to_numpy()) ** 2),
            ],
        )
    sensitivity = json.loads((r.OUT / "sensitivity.json").read_text())
    delta = new.brier_delta.sum()
    effect = np.sort((2 * new.correction)[new.collapsed.eq(0)].to_numpy())[::-1]
    k = sensitivity["minimum_additional_failure_outcomes_to_reverse_brier_delta"]
    assert delta - effect[:k].sum() <= 0 and (k == 1 or delta - effect[: k - 1].sum() > 0)
    r.check()
    r.save(
        r.OUT / "verification.json",
        dict(
            status="passed",
            races=4799,
            target_races=205,
            year_counts_verified=True,
            calendar_comparison_verified=True,
            numeric_difference_intervals=interval_checks,
            categorical_rows=len(cat),
            standardized_rows=len(standardized),
            fixed_cell_decomposition_identity_passed=True,
            original_probabilities_and_results_unchanged=True,
            counterfactual_coefficients_reconciled=True,
            new_models=0,
        ),
    )
    print(
        "Verified",
        interval_checks,
        "difference intervals and",
        len(standardized),
        "decompositions",
        flush=True,
    )


if __name__ == "__main__":
    main()
