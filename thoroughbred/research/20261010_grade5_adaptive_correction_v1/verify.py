"""Independent prediction, training optimality, metrics and cluster-CI checks."""

import json

import numpy as np
import pandas as pd
import run as r
from scipy.special import expit


def main():
    r.check()
    d = pd.read_parquet(r.SOURCE)
    p = pd.read_parquet(r.OUT / "predictions.parquet")
    source = d.set_index("race_key").loc[p.race_key].reset_index()
    assert p.race_key.is_unique and len(p) == 4799
    mask = (1 - source.base_risk >= 0.7) & source.axis_grade.eq(5)
    assert np.array_equal(mask, p.is_target) and mask.sum() == 205
    for name in ["axis_number", "axis_horse_id", "collapsed", "base_risk", "race_date"]:
        assert np.array_equal(source[name], p[name]), name
    old = pd.read_parquet(r.PRIOR / "outputs/risk_predictions.parquet")
    for name, variant in [("raw", "raw"), ("constant", "grade5_local_raw")]:
        v = old[old.variant.eq(variant)].set_index("race_key").loc[p.race_key, "risk"]
        assert np.array_equal(v, p[name])
    feature_names = {
        "early": ["early_advantage_seconds"],
        "recent": ["recent_record_index"],
        "joint": ["early_advantage_seconds", "recent_record_index"],
    }
    checked_models = 0
    for year in [2024, 2025, 2026]:
        tr = d[d.year.lt(year) & (1 - d.base_risk >= 0.7) & d.axis_grade.eq(5)]
        te = source[source.year.eq(year)]
        for variant, names in feature_names.items():
            m = json.loads((r.OUT / "models" / f"{variant}_{year}.json").read_text())
            assert m["features"] == names and m["l2"] == 10
            assert m["train_n"] == len(tr) and m["train_years"] == list(range(2020, year))
            assert m["train_end"] == str(tr.race_date.max().date())
            assert pd.Timestamp(m["train_end"]) < te.race_date.min()

            def independent_x(frame, names=names, tr=tr, m=m):
                cols = [np.ones(len(frame))]
                for n in names:
                    v = (
                        -frame.axis_gap_section_early_mean3
                        if n.startswith("early")
                        else frame.axis_moist_last3_record_index_mean
                    ).to_numpy(dtype=float)
                    finite = np.isfinite(v)
                    train_v = (
                        -tr.axis_gap_section_early_mean3
                        if n.startswith("early")
                        else tr.axis_moist_last3_record_index_mean
                    ).to_numpy(dtype=float)
                    train_v = train_v[np.isfinite(train_v)]
                    mu, sd = train_v.mean(), train_v.std() or 1.0
                    assert np.isclose(m["scales"][n]["mean"], mu)
                    assert np.isclose(m["scales"][n]["std"], sd)
                    cols += [
                        np.clip(np.where(finite, (v - mu) / sd, 0.0), -3, 3),
                        (~finite).astype(float),
                    ]
                return np.column_stack(cols)

            beta = np.array(m["coefficients"])
            x = independent_x(tr)
            z = np.log(tr.base_risk.to_numpy() / (1 - tr.base_risk.to_numpy())) + x @ beta
            grad = x.T @ (expit(z) - tr.collapsed.to_numpy()) + 10 * beta
            assert abs(grad).max() < 1e-4
            q = te.base_risk.to_numpy().copy()
            mt = (1 - te.base_risk >= 0.7) & te.axis_grade.eq(5)
            offsets = np.log(q / (1 - q)) + independent_x(te) @ beta
            q[mt] = expit(offsets[mt])
            assert np.allclose(q, p.loc[p.year.eq(year), variant], atol=1e-14, rtol=0)
            mutation = te.copy()
            mutation["collapsed"] = 1 - mutation.collapsed
            for name in ["year", "meet", "axis_number", "gate_number", "axis_distance_m", "score1"]:
                mutation[name] = -999
            assert np.array_equal(r.predict(mutation, m), r.predict(te, m))
            checked_models += 1
    for variant in feature_names:
        assert np.array_equal(p.loc[~p.is_target, variant], p.loc[~p.is_target, "raw"])
        assert p[variant].between(0, 1, inclusive="neither").all()
    quality = pd.read_csv(r.OUT / "quality.csv")
    deltas = pd.read_csv(r.OUT / "paired_differences.csv")
    metric_checks = ci_checks = 0
    for period, frame in r.periods(p):
        # Group masks independently specified here.
        subsets = dict(
            target=frame[frame.is_target],
            all=frame,
            outside=frame[~frame.is_target],
            supported_target=frame[
                frame.is_target
                & frame.axis_profile_count3.ge(3)
                & frame.axis_section_early_n5.ge(3)
            ],
        )
        for group, g in subsets.items():
            y = g.collapsed.to_numpy()
            loss = {}
            for variant in r.VARIANTS:
                q = g[variant].to_numpy()
                loss[variant, "brier"] = np.square(q - y)
                loss[variant, "logloss"] = -(y * np.log(q) + (1 - y) * np.log(1 - q))
                row = quality[
                    (quality.period.eq(period))
                    & quality.group.eq(group)
                    & quality.variant.eq(variant)
                ].iloc[0]
                assert row.n == len(g) and row.failures == y.sum()
                for key, val in dict(
                    mean_top3=1 - q.mean(),
                    actual_top3=1 - y.mean(),
                    brier=loss[variant, "brier"].mean(),
                    logloss=loss[variant, "logloss"].mean(),
                    mean_cut=(q - g.raw).mean(),
                ).items():
                    assert np.isclose(row[key], val, atol=1e-14, rtol=0), key
                metric_checks += 1
            for variant in feature_names:
                for ref in ["raw", "constant"]:
                    for metric in ["brier", "logloss"]:
                        delta = loss[variant, metric] - loss[ref, metric]
                        g2 = (
                            pd.DataFrame({"date": g.race_date.to_numpy(), "v": delta})
                            .groupby("date")
                            .v.agg(["sum", "count"])
                        )
                        rng = np.random.default_rng(421010)
                        w = rng.multinomial(len(g2), np.repeat(1 / len(g2), len(g2)), 2000)
                        draws = (w @ g2["sum"].to_numpy()) / (w @ g2["count"].to_numpy())
                        lo, hi = np.percentile(draws, [2.5, 97.5])
                        row = deltas[
                            deltas.period.eq(period)
                            & deltas.group.eq(group)
                            & deltas.variant.eq(variant)
                            & deltas.reference.eq(ref)
                            & deltas.metric.eq(metric)
                        ].iloc[0]
                        assert np.allclose(
                            [row.difference, row.low, row.high],
                            [delta.mean(), lo, hi],
                            atol=1e-14,
                            rtol=0,
                        )
                        ci_checks += 1
    r.save(
        r.OUT / "verification.json",
        dict(
            status="passed",
            models=checked_models,
            metric_rows=metric_checks,
            paired_ci_rows=ci_checks,
            unchanged_outside=4594,
            preserved_axis=4799,
            outcome_and_unused_field_mutation="passed",
            chronological_training_and_scaling="passed",
            source_hashes="passed",
        ),
    )
    r.check()
    print("Independent verification passed", checked_models, metric_checks, ci_checks)


if __name__ == "__main__":
    main()
