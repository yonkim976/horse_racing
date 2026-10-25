"""Reconcile expanding-window fits, frozen axes and paired date intervals."""

# ruff: noqa: B007 -- pandas query references named loop variables.

import json

import numpy as np
import pandas as pd
import run as e
from scipy.special import expit


def main():
    e.check()
    d = pd.read_parquet(e.OUT / "race_inputs.parquet")
    original = pd.read_parquet(e.A).set_index("race_key")
    expected = original.loc[d.race_key].reset_index()
    pd.testing.assert_frame_equal(d[original.reset_index().columns], expected)
    assert d.race_key.is_unique and len(d) == 10770
    prior = pd.read_parquet(e.PREVIOUS).set_index("race_key")
    current = d[d.year.ge(2024)].set_index("race_key")
    assert len(current) == 4799
    np.testing.assert_allclose(
        1 - current.base_risk, prior.loc[current.index].axis_probability, atol=1e-12
    )
    np.testing.assert_array_equal(current.axis_number, prior.loc[current.index].axis_number)
    np.testing.assert_array_equal(current.collapsed, prior.loc[current.index].collapsed)
    # Independently reconstruct flags including missing-at-high-probability semantics.
    np.testing.assert_array_equal(d.early_slower, d.axis_gap_section_early_mean3.ge(0).astype(int))
    np.testing.assert_array_equal(
        d.distance_up200, (d.axis_distance_m - d.axis_section_previous_distance).ge(200).astype(int)
    )
    np.testing.assert_array_equal(
        d.high_probability_grade5, ((1 - d.base_risk >= 0.7) & d.axis_grade.eq(5)).astype(int)
    )
    assert np.isfinite(e.design(d)).all()
    altered = d.copy()
    altered["collapsed"] = 1 - d.collapsed
    altered["axis_number"] = -999
    np.testing.assert_array_equal(e.design(d), e.design(altered))
    # Exercise true/false/unknown flags independently from outcomes.
    example = d.head(4).copy()
    example["base_risk"] = [0.2, 0.2, 0.5, 0.2]
    example["axis_grade"] = [5, np.nan, np.nan, 4]
    example["axis_gap_section_early_mean3"] = [np.nan, 0, -1, 1]
    example["axis_distance_m"] = [1400] * 4
    example["axis_section_previous_distance"] = [np.nan, 1200, 1300, 1600]
    np.testing.assert_array_equal(
        e.design(example)[:, 2:],
        [[0, 0, 1, 1, 1, 0], [1, 1, 0, 0, 0, 1], [0, 0, 0, 0, 0, 0], [1, 0, 0, 0, 0, 0]],
    )
    h = pd.read_parquet(e.H)
    h = h[h.race_key.isin(d.race_key)]
    for col in ["history_source_date", "profile_source_date"]:
        assert (h[col].isna() | h[col].le(h.cutoff_date)).all()
    assert (h.cutoff_date == h.race_date - pd.Timedelta(days=2)).all()
    p = pd.read_parquet(e.OUT / "risk_predictions.parquet")
    assert len(p) == 4799 * 3 and p.risk.between(0, 1).all()
    assert p.groupby(["race_key", "variant"]).size().eq(1).all()
    for year in [2024, 2025, 2026]:
        train = d[d.year.lt(year)]
        test = d[d.year.eq(year)]
        previous = d[d.year.eq(year - 1)]
        for variant in e.VARIANTS:
            rows = (
                p[p.year.eq(year) & p.variant.eq(variant)].set_index("race_key").loc[test.race_key]
            )
            if variant == "raw":
                risk = test.base_risk.to_numpy()
                prior_risk = previous.base_risk.to_numpy()
            else:
                model = json.loads((e.OUT / "models" / f"{variant}_{year}.json").read_text())
                assert model["train_n"] == len(train) and model["train_years"] == list(
                    range(2020, year)
                )
                assert pd.Timestamp(model["train_end"]) < test.race_date.min()
                assert model["train_end"] == str(train.race_date.max().date())
                coeff = np.array(model["coefficients"])
                x = e.design(train)[:, : len(coeff)]
                _, grad = e.objective(coeff, x, train.collapsed.to_numpy())
                assert np.max(np.abs(grad)) < 1e-4
                # Numerical objective gradient confirms fitted analytic equation.
                for i in range(len(coeff)):
                    delta = np.zeros(len(coeff))
                    delta[i] = 1e-5
                    numerical = (
                        e.objective(coeff + delta, x, train.collapsed.to_numpy())[0]
                        - e.objective(coeff - delta, x, train.collapsed.to_numpy())[0]
                    ) / 2e-5
                    np.testing.assert_allclose(numerical, grad[i], atol=2e-5)
                risk = expit(e.design(test)[:, : len(coeff)] @ coeff)
                prior_risk = expit(e.design(previous)[:, : len(coeff)] @ coeff)
            np.testing.assert_allclose(rows.risk, risk, atol=1e-14)
            threshold = np.quantile(prior_risk, 0.7)
            np.testing.assert_allclose(rows.threshold, threshold, atol=1e-14)
            np.testing.assert_array_equal(rows.flag, risk >= threshold)
            np.testing.assert_array_equal(rows.collapsed, test.collapsed)
    quality = pd.read_csv(e.OUT / "quality.csv", dtype={"period": str})
    diff = pd.read_csv(e.OUT / "paired_differences.csv", dtype={"period": str})
    checked = 0
    for tag, g in e.periods(p):
        for scope, x in e.groups(g):
            for variant, v in x.groupby("variant"):
                row = quality.query("period==@tag and group==@scope and variant==@variant").iloc[0]
                y = v.collapsed.to_numpy()
                pred = v.risk.to_numpy()
                flag = v.flag.to_numpy()
                np.testing.assert_allclose(row.brier, np.mean((y - pred) ** 2))
                np.testing.assert_allclose(
                    row.logloss,
                    np.mean(
                        np.logaddexp(0, np.log(pred / (1 - pred))) - y * np.log(pred / (1 - pred))
                    ),
                )
                assert row.n == len(v) and row.failures == y.sum()
                assert row.flagged == flag.sum() and row.flagged_failures == y[flag].sum()
                assert row.false_alarms == (1 - y[flag]).sum()
                assert row.quiet == (~flag).sum()
                np.testing.assert_allclose(row.quiet_axis_top3, 1 - y[~flag].mean())
            wide = x.pivot(index="race_key", columns="variant", values="risk")
            meta = x.drop_duplicates("race_key").set_index("race_key").loc[wide.index]
            for row in diff[diff.period.eq(tag) & diff.group.eq(scope)].itertuples():
                a, b = wide[row.left].to_numpy(), wide[row.right].to_numpy()
                y = meta.collapsed.to_numpy()
                delta = (
                    (a - y) ** 2 - (b - y) ** 2
                    if row.metric == "brier"
                    else -y * np.log(a / b) - (1 - y) * np.log((1 - a) / (1 - b))
                )
                np.testing.assert_allclose(row.difference, delta.mean(), atol=1e-12)
                daily = (
                    pd.DataFrame(dict(date=meta.race_date.to_numpy(), v=delta))
                    .groupby("date")
                    .v.agg(["sum", "count"])
                )
                rng = np.random.default_rng(e.SEED)
                w = rng.multinomial(len(daily), np.full(len(daily), 1 / len(daily)), e.B)
                draws = (w @ daily["sum"].to_numpy()) / (w @ daily["count"].to_numpy(dtype=float))
                np.testing.assert_allclose(
                    [row.low, row.high], np.quantile(draws, [0.025, 0.975]), atol=1e-12
                )
                checked += 1
    contract = json.loads((e.OUT / "future_validation_contract.json").read_text())
    assert (
        contract["earliest_race_date"] == "2026-10-11"
        and contract["live_predictions_generated"] == 0
    )
    for model in contract["risk_models"]:
        assert e.sha(e.ROOT / model["path"]) == model["sha256"]
    for model in contract["base_models"]:
        assert e.sha(e.ROOT / model["model_path"]) == model["sha256"]
        assert e.sha(e.ROOT / model["metadata_path"]) == model["metadata_sha256"]
    assert len(contract["risk_models"]) == 2 and len(contract["base_models"]) == 2
    e.check()
    e.save(
        e.OUT / "verification.json",
        dict(
            status="passed",
            races=4799,
            new_small_risk_models=6,
            original_axis_unchanged=True,
            source_history_T_minus2_passed=True,
            stored_predictions_reproduced=True,
            training_boundaries_passed=True,
            outcome_input_mutation_invariant=True,
            independent_paired_intervals=checked,
            quality_rows=len(quality),
            future_contract_verified=True,
            prospective_predictions=0,
        ),
    )
    print("Verified", len(quality), "quality rows;", checked, "paired intervals", flush=True)


if __name__ == "__main__":
    main()
