"""Independent reconciliation to frozen axes, histories and statistical tables."""

# ruff: noqa: B007 -- pandas query references the loop variables by name.

import json

import numpy as np
import pandas as pd
import run as e


def main():
    e.check()
    d = pd.read_parquet(e.OUT / "races.parquet")
    old = pd.read_parquet(e.P).query("variant=='month_gate_weight22'").set_index("race_key")
    assert len(d) == 4799 and d.collapsed.sum() == 1937 and d.race_key.is_unique
    np.testing.assert_allclose(d.axis_probability, old.loc[d.race_key].axis_probability, atol=1e-12)
    np.testing.assert_array_equal(d.collapsed, old.loc[d.race_key].axis_out)
    for col in ["history_source_date", "profile_source_date"]:
        assert (d[col].isna() | d[col].le(d.cutoff_date)).all()
    assert (d.cutoff_date == d.race_date - pd.Timedelta(days=2)).all()
    s = pd.read_parquet(e.S)
    s = s[s.race_key.isin(d.race_key)]
    actual_axis = s.merge(
        d[["race_key", "axis_number", "axis_horse_id", "collapsed", "other_supported_front_count"]],
        left_on=["race_key", "program_no", "horse_id"],
        right_on=["race_key", "axis_number", "axis_horse_id"],
        validate="one_to_one",
    )
    assert len(actual_axis) == len(d)
    assert ((~actual_axis.outcome.isin([1, 2, 3])).astype(int) == actual_axis.collapsed).all()
    for col in ["history_source_date", "profile_source_date"]:
        assert (s[col].isna() | s[col].le(s.cutoff_date)).all()
    fronts = s[s.style_role_n5.ge(3) & s.style_role0_rate5.ge(0.6)].groupby("race_key").size()
    independent_front_count = actual_axis.race_key.map(fronts).fillna(0) - (
        actual_axis.style_role_n5.ge(3) & actual_axis.style_role0_rate5.ge(0.6)
    ).astype(int)
    np.testing.assert_array_equal(independent_front_count, actual_axis.other_supported_front_count)
    memberships = pd.read_parquet(e.OUT / "rule_memberships.parquet").set_index("race_key")
    recomputed = pd.DataFrame(e.rules(e.load())).set_axis(d.race_key)
    pd.testing.assert_frame_equal(memberships, recomputed, check_names=False)
    tables = {
        name: pd.read_csv(e.OUT / f"{name}.csv", dtype={"period": str})
        for name in [
            "summary",
            "probability_bins",
            "conditions",
            "matched_conditions",
            "reference_bins",
        ]
    }
    checks = 0
    for tag, g in e.period(d):
        row = tables["summary"].query("period==@tag").iloc[0]
        assert row.n == len(g) and row.failures == g.collapsed.sum()
        for b, h in g.groupby("probability_band", observed=True):
            row = tables["probability_bins"].query("period==@tag and band==@b").iloc[0]
            assert row.n == len(h) and row.failures == h.collapsed.sum()
            np.testing.assert_allclose(
                [row.failure_rate, row.expected_risk, row.residual, row.failure_share],
                [
                    h.collapsed.mean(),
                    h.base_risk.mean(),
                    (h.collapsed - h.base_risk).mean(),
                    h.collapsed.sum() / g.collapsed.sum(),
                ],
            )
        for name, mask in e.rules(g).items():
            for scope in ["all", "prob70plus"]:
                h = g if scope == "all" else g[g.axis_probability.ge(0.7)]
                row = (
                    tables["conditions"]
                    .query("period==@tag and scope==@scope and rule==@name")
                    .iloc[0]
                )
                m = mask.loc[h.index]
                a, b = h[m.fillna(False)], h[(~m).fillna(False)]
                assert (
                    row.n == len(a)
                    and row.failures == a.collapsed.sum()
                    and row.missing == m.isna().sum()
                )
                if len(a):
                    np.testing.assert_allclose(
                        [row.failure_rate, row.expected_risk, row.residual],
                        [a.collapsed.mean(), a.base_risk.mean(), a.residual.mean()],
                    )
                    if len(b):
                        np.testing.assert_allclose(
                            row.residual_diff, a.residual.mean() - b.residual.mean()
                        )
                # Regenerate cluster resamples independently from dated sums.
                x = h[m.notna()]
                dates = sorted(x.race_date.unique())
                if len(a):
                    rng = np.random.default_rng(e.SEED)
                    w = rng.multinomial(len(dates), np.full(len(dates), 1 / len(dates)), e.B)
                    distributions = []
                    for frame in [a, b]:
                        perday = (
                            frame.assign(error=frame.collapsed - frame.base_risk)
                            .groupby("race_date")
                            .agg(n=("error", "size"), total=("error", "sum"))
                            .reindex(dates, fill_value=0)
                        )
                        den = w @ perday.n.to_numpy(dtype=float)
                        distributions.append(
                            np.divide(
                                w @ perday.total.to_numpy(dtype=float),
                                den,
                                out=np.full(e.B, np.nan),
                                where=den > 0,
                            )
                        )
                    if len(b):
                        v = distributions[0] - distributions[1]
                        v = v[np.isfinite(v)]
                        if len(v) >= 1900:
                            np.testing.assert_allclose(
                                [row.residual_diff_low, row.residual_diff_high],
                                np.quantile(v, [0.025, 0.975]),
                                atol=1e-12,
                            )
                            checks += 1
    c = tables["conditions"]
    selected = (
        c.query("period=='2024' and scope=='all' and n>=80 and failures>=20 and residual_diff>0")
        .sort_values(["residual_diff", "rule"], ascending=[False, True])
        .head(5)
        .rule.tolist()
    )
    assert selected == json.loads((e.OUT / "discovery_selection.json").read_text())["rules"]
    # Cross-study probability bin checks for all models, including operating reference.
    p = pd.read_parquet(e.P)
    for row in tables["reference_bins"].itertuples():
        h = p[p.variant.eq(row.variant)]
        h = h[
            pd.cut(
                h.axis_probability,
                [0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.000001],
                labels=e.LABELS,
                right=False,
            ).eq(row.band)
        ]
        assert row.n == len(h) and row.failures == h.axis_out.sum()
    assert d.axis_probability.between(0, 1).all()
    assert tables["probability_bins"].query("period=='all'").n.sum() == 4799
    e.check()
    e.save(
        e.OUT / "verification.json",
        dict(
            status="passed",
            primary_races=len(d),
            failures=int(d.collapsed.sum()),
            historical_runner_rows=len(s),
            condition_rows=len(c),
            bootstrap_residual_diff_intervals_checked=checks,
            axes_and_probabilities_reconciled=True,
            discovery_selection_reconciled=True,
            missing_not_conflated=True,
            future_access=False,
            new_models=0,
        ),
    )
    print("Verified", len(d), "races;", checks, "cluster intervals", flush=True)


if __name__ == "__main__":
    main()
