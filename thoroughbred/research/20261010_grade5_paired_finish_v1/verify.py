"""Independently verify paired-history calibrators and all scores."""

import json

import numpy as np
import pandas as pd
import run as r
from scipy.special import expit

NAMES = {
    "paired_times": [
        "early",
        "recent",
        "paired_g3",
        "paired_g1",
        "paired_fast_n",
        "paired_valid_n",
    ],
    "paired_rate": ["early", "recent", "paired_keep_rate", "paired_fast_n", "paired_valid_n"],
    "paired_full": [
        "early",
        "recent",
        "paired_g3",
        "paired_g1",
        "paired_keep_rate",
        "paired_fast_n",
        "paired_valid_n",
    ],
}
FIELDS = {
    "early": "axis_gap_section_early_mean3",
    "recent": "axis_moist_last3_record_index_mean",
    **{
        k: k
        for k in ["paired_g3", "paired_g1", "paired_keep_rate", "paired_fast_n", "paired_valid_n"]
    },
}


def independent_x(frame, tr, model):
    cols = [np.ones(len(frame))]
    for name in model["features"]:
        sign = -1 if name == "early" else 1
        tv = sign * tr[FIELDS[name]].to_numpy(dtype=float)
        tv = tv[np.isfinite(tv)]
        mu, sd = tv.mean(), tv.std() or 1.0
        assert np.isclose(model["scales"][name]["mean"], mu)
        assert np.isclose(model["scales"][name]["std"], sd)
        v = sign * frame[FIELDS[name]].to_numpy(dtype=float)
        valid = np.isfinite(v)
        z = np.clip(np.where(valid, (v - mu) / sd, 0.0), -3, 3)
        cols += [z, (~valid).astype(float)]
    return np.column_stack(cols)


def main():
    r.check()
    d = pd.read_parquet(r.SOURCE)
    paired = pd.read_parquet(r.OUT / "paired_features.parquet")
    d = d.merge(paired, on="race_key", how="left", validate="one_to_one")
    d[["paired_fast_n", "paired_valid_n", "paired_keep_n"]] = d[
        ["paired_fast_n", "paired_valid_n", "paired_keep_n"]
    ].fillna(0.0)
    p = pd.read_parquet(r.OUT / "predictions.parquet")
    source = d.set_index("race_key").loc[p.race_key].reset_index()
    assert p.race_key.is_unique and len(p) == 4799
    assert np.array_equal(p.is_target, (1 - source.base_risk >= 0.7) & source.axis_grade.eq(5))
    assert p.is_target.sum() == 205
    prior = (
        pd.read_parquet(r.PRIOR / "outputs/predictions.parquet")
        .set_index("race_key")
        .loc[p.race_key]
    )
    for name in ["axis_number", "axis_horse_id", "base_risk", "collapsed", "race_date"]:
        assert np.array_equal(p[name], source[name])
        assert np.array_equal(p[name], prior[name])
    for name in ["raw", "constant", "joint", "finish_add", "finish_interaction"]:
        assert np.array_equal(p[name], prior[name])
    for name, col in FIELDS.items():
        assert np.allclose(p[name], source[col] * (-1 if name == "early" else 1), equal_nan=True)
    models = 0
    for year in [2024, 2025, 2026]:
        tr = d[d.year.lt(year) & (1 - d.base_risk >= 0.7) & d.axis_grade.eq(5)]
        te = source[source.year.eq(year)]
        for variant, names in NAMES.items():
            m = json.loads((r.OUT / "models" / f"{variant}_{year}.json").read_text())
            assert m["features"] == names and m["l2"] == 10 and m["train_n"] == len(tr)
            assert m["train_years"] == list(range(2020, year))
            assert m["train_end"] == str(tr.race_date.max().date())
            assert pd.Timestamp(m["train_end"]) < te.race_date.min()
            beta = np.array(m["coefficients"])
            x = independent_x(tr, tr, m)
            offset = np.log(tr.base_risk.to_numpy() / (1 - tr.base_risk.to_numpy()))
            grad = x.T @ (expit(offset + x @ beta) - tr.collapsed.to_numpy()) + 10 * beta
            assert np.max(np.abs(grad)) < 1e-4
            q = te.base_risk.to_numpy().copy()
            z = np.log(q / (1 - q)) + independent_x(te, tr, m) @ beta
            mask = ((1 - te.base_risk) >= 0.7) & te.axis_grade.eq(5)
            q[mask] = expit(z[mask])
            assert np.allclose(q, p.loc[p.year.eq(year), variant], atol=1e-14, rtol=0)
            mutated = te.copy()
            mutated["collapsed"] = 1 - mutated.collapsed
            for name in ["year", "meet", "axis_number", "gate_number", "score1", "axis_distance_m"]:
                mutated[name] = -999
            assert np.array_equal(r.predict(mutated, m), r.predict(te, m))
            models += 1
    for variant in NAMES:
        assert np.array_equal(p.loc[~p.is_target, variant], p.loc[~p.is_target, "raw"])
        assert p[variant].between(0, 1, inclusive="neither").all()
    quality = pd.read_csv(r.OUT / "quality.csv", dtype={"period": str})
    delta = pd.read_csv(r.OUT / "paired_differences.csv", dtype={"period": str})
    quality_checks = ci_checks = 0
    for period, frame in r.periods(p):
        subsets = dict(
            target=frame[frame.is_target],
            all=frame,
            outside=frame[~frame.is_target],
            supported_target=frame[frame.is_target & frame.paired_fast_n.ge(2)],
        )
        for group, g in subsets.items():
            losses = {}
            for variant in r.VARIANTS:
                y, q = g.collapsed.to_numpy(), g[variant].to_numpy()
                losses[variant, "brier"] = np.square(q - y)
                losses[variant, "logloss"] = -(y * np.log(q) + (1 - y) * np.log(1 - q))
                row = quality[
                    quality.period.eq(period)
                    & quality.group.eq(group)
                    & quality.variant.eq(variant)
                ].iloc[0]
                assert row.n == len(g) and row.failures == y.sum()
                for k, v in dict(
                    mean_top3=1 - q.mean(),
                    actual_top3=1 - y.mean(),
                    brier=losses[variant, "brier"].mean(),
                    logloss=losses[variant, "logloss"].mean(),
                    mean_cut=(q - g.raw).mean(),
                ).items():
                    assert np.isclose(row[k], v, atol=1e-14, rtol=0)
                quality_checks += 1
            for variant in NAMES:
                for ref in ["joint", "finish_add", "finish_interaction", "constant", "raw"]:
                    for metric in ["brier", "logloss"]:
                        v = losses[variant, metric] - losses[ref, metric]
                        daily = (
                            pd.DataFrame(dict(date=g.race_date.to_numpy(), v=v))
                            .groupby("date")
                            .v.agg(["sum", "count"])
                        )
                        w = np.random.default_rng(441010).multinomial(
                            len(daily), np.repeat(1 / len(daily), len(daily)), 2000
                        )
                        lo, hi = np.percentile(
                            (w @ daily["sum"].to_numpy()) / (w @ daily["count"].to_numpy()),
                            [2.5, 97.5],
                        )
                        row = delta[
                            delta.period.eq(period)
                            & delta.group.eq(group)
                            & delta.variant.eq(variant)
                            & delta.reference.eq(ref)
                            & delta.metric.eq(metric)
                        ].iloc[0]
                        assert np.allclose(
                            [row.difference, row.low, row.high],
                            [v.mean(), lo, hi],
                            atol=1e-14,
                            rtol=0,
                        )
                        ci_checks += 1
    r.save(
        r.OUT / "verification.json",
        dict(
            status="passed",
            models=models,
            metric_rows=quality_checks,
            paired_ci_rows=ci_checks,
            unchanged_outside=4594,
            preserved_axis=4799,
            chronological_training_and_scaling="passed",
            paired_features="independently audited in verify_history.py",
            outcome_and_unused_field_mutation="passed",
            source_hashes="passed",
        ),
    )
    r.check()
    print("Independent verification passed", models, quality_checks, ci_checks)


if __name__ == "__main__":
    main()
