"""Frozen local adaptive calibration, with expanding target-only training."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit, logit

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = R.parent.parent
OUT = HERE / "outputs"
PRIOR = R / "20261010_axis_single_signal_ablation_v1"
spec = importlib.util.spec_from_file_location("frozen_ablation40", PRIOR / "run.py")
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
e = a.e
sha, save = e.sha, e.save
SOURCE = a.PRIOR / "outputs/race_inputs.parquet"
FEATURES = {
    "early": "early_advantage_seconds",
    "recent": "recent_record_index",
    "joint": ["early_advantage_seconds", "recent_record_index"],
}
FEATURES = {k: [v] if isinstance(v, str) else v for k, v in FEATURES.items()}
VARIANTS = ["raw", "constant", *FEATURES]
L2, B, SEED = 10.0, 2000, 421010


def check():
    a.check()
    for name, digest in json.loads((OUT / "source_lock.json").read_text()).items():
        assert sha(ROOT / name) == digest, name


def inputs(d):
    return pd.DataFrame(
        {
            "early_advantage_seconds": -d.axis_gap_section_early_mean3,
            "recent_record_index": d.axis_moist_last3_record_index_mean,
        },
        index=d.index,
    )


def scales(d, names):
    x = inputs(d)
    result = {}
    for name in names:
        v = x[name].to_numpy(dtype=float)
        good = np.isfinite(v)
        assert good.any()
        std = float(v[good].std(ddof=0))
        result[name] = dict(mean=float(v[good].mean()), std=std if std > 0 else 1.0)
    return result


def design(d, artifact):
    x = inputs(d)
    cols = [np.ones(len(d))]
    for name in artifact["features"]:
        v = x[name].to_numpy(dtype=float)
        good = np.isfinite(v)
        scale = artifact["scales"][name]
        z = np.where(good, (v - scale["mean"]) / scale["std"], 0.0)
        cols.extend([np.clip(z, -3.0, 3.0), (~good).astype(float)])
    return np.column_stack(cols)


def objective(beta, x, offset, y):
    z = offset + x @ beta
    return float(np.logaddexp(0, z).sum() - y @ z + L2 * (beta @ beta) / 2), (
        x.T @ (expit(z) - y) + L2 * beta
    )


def target(d):
    return ((1 - d.base_risk) >= 0.7) & d.axis_grade.eq(5)


def predict(d, artifact):
    q = d.base_risk.to_numpy(dtype=float).copy()
    m = target(d).to_numpy()
    q[m] = expit(logit(q[m]) + design(d.loc[m], artifact) @ artifact["coefficients"])
    return q


def losses(q, y):
    q = np.clip(q, 1e-12, 1 - 1e-12)
    return {"brier": (q - y) ** 2, "logloss": -y * np.log(q) - (1 - y) * np.log1p(-q)}


def interval(values, dates):
    g = pd.DataFrame(dict(v=values, date=dates)).groupby("date").v.agg(["sum", "count"])
    w = np.random.default_rng(SEED).multinomial(len(g), np.full(len(g), 1 / len(g)), B)
    return np.quantile(w @ g["sum"].to_numpy() / (w @ g["count"].to_numpy()), [0.025, 0.975])


def periods(d):
    yield "all", d
    for year in [2024, 2025, 2026]:
        yield str(year), d[d.year.eq(year)]
    yield "2025_26", d[d.year.ge(2025)]


def groups(d):
    yield "target", d[d.is_target]
    yield "all", d
    yield "outside", d[~d.is_target]
    yield (
        "supported_target",
        d[d.is_target & d.axis_profile_count3.ge(3) & d.axis_section_early_n5.ge(3)],
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    assert not (OUT / "source_lock.json").exists()
    locked = (
        [HERE / n for n in ["PLAN.md", "run.py", "verify.py"]]
        + [
            PRIOR / "run.py",
            PRIOR / "outputs/risk_predictions.parquet",
            SOURCE,
            e.REGISTRY,
            e.BASE,
            a.PRIOR / "outputs/future_validation_contract.json",
        ]
        + sorted((PRIOR / "outputs/models").glob("grade5_local_raw_*.json"))
    )
    save(OUT / "source_lock.json", {str(p.relative_to(ROOT)): sha(p) for p in locked})
    d = pd.read_parquet(SOURCE)
    assert len(d) == 10770 and d.race_key.is_unique
    eval_d = d[d.year.ge(2024)].copy()
    assert len(eval_d) == 4799 and target(eval_d).sum() == 205
    p = eval_d[
        [
            "race_key",
            "race_date",
            "year",
            "meet",
            "axis_number",
            "axis_horse_id",
            "collapsed",
            "base_risk",
            "axis_profile_count3",
            "axis_section_early_n5",
        ]
    ].copy()
    p["is_target"], p["raw"] = target(eval_d), eval_d.base_risk
    old = pd.read_parquet(PRIOR / "outputs/risk_predictions.parquet")
    for new, prior in [("raw", "raw"), ("constant", "grade5_local_raw")]:
        v = old[old.variant.eq(prior)].set_index("race_key")
        assert len(v) == len(p) and v.index.is_unique
        assert np.array_equal(v.loc[p.race_key, "axis_number"].to_numpy(), p.axis_number)
        assert np.array_equal(v.loc[p.race_key, "collapsed"].to_numpy(), p.collapsed)
        p[new] = v.loc[p.race_key, "risk"].to_numpy()
    coefficient_rows, profile_rows = [], []
    for year in [2024, 2025, 2026]:
        train = d[d.year.lt(year) & target(d)]
        test = eval_d[eval_d.year.eq(year)]
        assert train.race_date.max() < test.race_date.min()
        for variant, names in FEATURES.items():
            artifact = dict(
                variant=variant,
                features=names,
                scales=scales(train, names),
                evaluation_year=year,
                train_n=len(train),
                train_start=str(train.race_date.min().date()),
                train_end=str(train.race_date.max().date()),
                train_years=list(range(2020, year)),
                l2=L2,
            )
            x = design(train, artifact)
            y = train.collapsed.to_numpy(dtype=float)
            offset = logit(train.base_risk.to_numpy())
            fit = minimize(
                objective,
                np.zeros(x.shape[1]),
                args=(x, offset, y),
                jac=True,
                method="BFGS",
                options=dict(gtol=1e-7, maxiter=1000),
            )
            loss, grad = objective(fit.x, x, offset, y)
            assert np.max(np.abs(grad)) < 1e-4
            artifact.update(
                coefficients=fit.x.tolist(),
                objective=loss,
                max_abs_gradient=float(np.max(np.abs(grad))),
                optimizer_success=bool(fit.success),
            )
            save(OUT / "models" / f"{variant}_{year}.json", artifact)
            p.loc[test.index, variant] = predict(test, artifact)
            terms = ["intercept"] + [t for n in names for t in [n, n + "_missing"]]
            for name, beta in zip(terms, fit.x, strict=True):
                coefficient_rows.append(
                    dict(year=year, variant=variant, feature=name, coefficient=beta)
                )
            if variant == "joint":
                ix = inputs(test)
                p.loc[test.index, "early_advantage_seconds"] = ix.early_advantage_seconds
                p.loc[test.index, "recent_record_index"] = ix.recent_record_index
                early, recent = ix.early_advantage_seconds, ix.recent_record_index
                labels = np.where(
                    early.isna() | recent.isna(),
                    "missing",
                    np.char.add(
                        np.where(
                            early.ge(artifact["scales"][names[0]]["mean"]),
                            "early_high",
                            "early_low",
                        ),
                        np.where(
                            recent.ge(artifact["scales"][names[1]]["mean"]),
                            "_recent_high",
                            "_recent_low",
                        ),
                    ),
                )
                p.loc[test.index, "profile"] = labels
            print("Fit", year, variant, "n", len(train), flush=True)
    p.to_parquet(OUT / "predictions.parquet", index=False)
    pd.DataFrame(coefficient_rows).to_csv(OUT / "coefficients.csv", index=False)
    quality, deltas = [], []
    for period, frame in periods(p):
        for group, g in groups(frame):
            y = g.collapsed.to_numpy(dtype=float)
            for variant in VARIANTS:
                q = g[variant].to_numpy()
                ls = losses(q, y)
                cut = q - g.raw.to_numpy()
                quality.append(
                    dict(
                        period=period,
                        group=group,
                        variant=variant,
                        n=len(g),
                        failures=int(y.sum()),
                        mean_top3=float(1 - q.mean()),
                        actual_top3=float(1 - y.mean()),
                        brier=float(ls["brier"].mean()),
                        logloss=float(ls["logloss"].mean()),
                        mean_cut=float(cut.mean()),
                        cut_p10=float(np.quantile(cut, 0.1)),
                        cut_p90=float(np.quantile(cut, 0.9)),
                        increased_top3=int((cut < -1e-12).sum()),
                    )
                )
            for variant in FEATURES:
                for reference in ["constant", "raw"]:
                    for metric in ["brier", "logloss"]:
                        v = (
                            losses(g[variant].to_numpy(), y)[metric]
                            - losses(g[reference].to_numpy(), y)[metric]
                        )
                        lo, hi = interval(v, g.race_date.to_numpy())
                        deltas.append(
                            dict(
                                period=period,
                                group=group,
                                variant=variant,
                                reference=reference,
                                metric=metric,
                                n=len(g),
                                difference=float(v.mean()),
                                low=float(lo),
                                high=float(hi),
                            )
                        )
        for profile, g in frame[frame.is_target].groupby("profile"):
            for variant in VARIANTS:
                profile_rows.append(
                    dict(
                        period=period,
                        profile=profile,
                        variant=variant,
                        n=len(g),
                        actual_top3=float(1 - g.collapsed.mean()),
                        mean_top3=float(1 - g[variant].mean()),
                        brier=float(((g[variant] - g.collapsed) ** 2).mean()),
                    )
                )
    quality, deltas = pd.DataFrame(quality), pd.DataFrame(deltas)
    quality.to_csv(OUT / "quality.csv", index=False)
    deltas.to_csv(OUT / "paired_differences.csv", index=False)
    pd.DataFrame(profile_rows).to_csv(OUT / "profiles.csv", index=False)
    m = json.loads((OUT / "models/joint_2026.json").read_text())
    examples = []
    for early in [0.1, 0.3, 0.5]:
        for recent in [0.0, 0.5, 1.0]:
            dummy = pd.DataFrame(
                dict(
                    base_risk=[0.25],
                    axis_grade=[5],
                    axis_gap_section_early_mean3=[-early],
                    axis_moist_last3_record_index_mean=[recent],
                )
            )
            q = predict(dummy, m)[0]
            examples.append(
                dict(
                    early_advantage_seconds=early,
                    recent_record_index=recent,
                    raw_top3=0.75,
                    adjusted_top3=float(1 - q),
                    cut=float(q - 0.25),
                )
            )
    pd.DataFrame(examples).to_csv(OUT / "examples.csv", index=False)
    primary = deltas.query(
        "period=='all' and group=='target' and variant=='joint' "
        "and reference=='constant' and metric=='brier'"
    ).iloc[0]
    annual = deltas.query(
        "period in ['2024','2025','2026'] and group=='target' and variant=='joint' "
        "and reference=='constant' and metric=='brier'"
    )
    save(
        OUT / "decision.json",
        dict(
            primary_difference=primary.difference,
            primary_low=primary.low,
            primary_high=primary.high,
            all_years_point_improve=bool(annual.difference.lt(0).all()),
            consistent_evidence=bool(primary.high < 0 and annual.difference.lt(0).all()),
            exploratory=True,
            promotion=False,
        ),
    )
    save(
        OUT / "cohort.json",
        dict(
            races=len(p),
            target_races=int(p.is_target.sum()),
            new_small_models=9,
            new_ability_models=0,
            end_date=str(p.race_date.max().date()),
            database_access=False,
            network_access=False,
            future_access=False,
        ),
    )
    check()
    print(quality.query("group=='target'").to_string(index=False), flush=True)
    print(
        deltas.query(
            "group=='target' and variant=='joint' and reference=='constant' and metric=='brier'"
        ).to_string(index=False),
        flush=True,
    )


if __name__ == "__main__":
    main()
