"""Local late-section calibration: additive and early-positive interactions."""

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
PRIOR = R / "20261010_grade5_adaptive_correction_v1"
spec = importlib.util.spec_from_file_location("frozen_adaptive42", PRIOR / "run.py")
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
SOURCE, sha, save = b.SOURCE, b.sha, b.save
FEATURES = {
    "g3f_add": ["early", "recent", "g3f"],
    "g1f_add": ["early", "recent", "g1f"],
    "finish_add": ["early", "recent", "g3f", "g1f"],
    "finish_interaction": ["early", "recent", "g3f", "g1f"],
}
VARIANTS = ["raw", "constant", "joint", *FEATURES]
COLUMNS = {
    "early": "axis_gap_section_early_mean3",
    "recent": "axis_moist_last3_record_index_mean",
    "g3f": "axis_gap_section_last600_mean3",
    "g1f": "axis_gap_section_late_mean3",
}
L2, B, SEED = 10.0, 2000, 431010


def check():
    b.check()
    for name, digest in json.loads((OUT / "source_lock.json").read_text()).items():
        assert sha(ROOT / name) == digest, name


def inputs(d):
    return pd.DataFrame(
        {name: d[col] * (1 if name == "recent" else -1) for name, col in COLUMNS.items()},
        index=d.index,
    )


def target(d):
    return ((1 - d.base_risk) >= 0.7) & d.axis_grade.eq(5)


def design(d, model):
    f = inputs(d)
    cols, zvalues = [np.ones(len(d))], {}
    for name in model["features"]:
        v = f[name].to_numpy(dtype=float)
        good = np.isfinite(v)
        sc = model["scales"][name]
        z = np.clip(np.where(good, (v - sc["mean"]) / sc["std"], 0.0), -3, 3)
        cols += [z, (~good).astype(float)]
        zvalues[name] = z
    if model["variant"] == "finish_interaction":
        ev = f.early.to_numpy(dtype=float)
        positive = np.clip(
            np.where(np.isfinite(ev), np.maximum(ev, 0.0) / model["scales"]["early"]["std"], 0.0),
            0.0,
            3.0,
        )
        for name in ["g3f", "g1f"]:
            cols += [positive * zvalues[name]]
    return np.column_stack(cols)


def predict(d, model):
    q = d.base_risk.to_numpy(dtype=float).copy()
    mask = target(d).to_numpy()
    q[mask] = expit(logit(q[mask]) + design(d.loc[mask], model) @ model["coefficients"])
    return q


def objective(beta, x, offset, y):
    z = offset + x @ beta
    return float(np.logaddexp(0, z).sum() - y @ z + L2 * (beta @ beta) / 2), x.T @ (
        expit(z) - y
    ) + L2 * beta


def losses(q, y):
    return {"brier": (q - y) ** 2, "logloss": -y * np.log(q) - (1 - y) * np.log1p(-q)}


def interval(v, dates):
    g = pd.DataFrame(dict(v=v, date=dates)).groupby("date").v.agg(["sum", "count"])
    w = np.random.default_rng(SEED).multinomial(len(g), np.full(len(g), 1 / len(g)), B)
    return np.quantile((w @ g["sum"].to_numpy()) / (w @ g["count"].to_numpy()), [0.025, 0.975])


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
        d[
            d.is_target
            & d.axis_profile_count3.ge(3)
            & d.axis_section_early_n5.ge(3)
            & d.axis_section_last600_n5.ge(3)
            & d.axis_section_late_n5.ge(3)
        ],
    )


def profile(f):
    missing = ~np.isfinite(f[["early", "g3f", "g1f"]]).all(axis=1)
    both = f.g3f.gt(0) & f.g1f.gt(0)
    neither = f.g3f.le(0) & f.g1f.le(0)
    return np.select(
        [missing, f.early.le(0), both, neither],
        [
            "missing",
            "no_early_advantage",
            "early_fast_both_finish_fast",
            "early_fast_both_finish_slow",
        ],
        default="early_fast_finish_mixed",
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    assert not (OUT / "source_lock.json").exists()
    paths = [HERE / n for n in ["PLAN.md", "run.py", "verify.py"]] + [
        PRIOR / "run.py",
        PRIOR / "outputs/predictions.parquet",
        SOURCE,
        b.e.REGISTRY,
        b.e.BASE,
        b.a.PRIOR / "outputs/future_validation_contract.json",
    ]
    save(OUT / "source_lock.json", {str(p.relative_to(ROOT)): sha(p) for p in paths})
    d = pd.read_parquet(SOURCE)
    assert len(d) == 10770 and d.race_key.is_unique
    eval_d = d[d.year.ge(2024)]
    assert len(eval_d) == 4799 and target(eval_d).sum() == 205
    cols = [
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
        "axis_section_last600_n5",
        "axis_section_late_n5",
    ]
    p = eval_d[cols].copy()
    p["is_target"] = target(eval_d)
    f = inputs(eval_d)
    for n in f:
        p[n] = f[n]
    p["profile"] = profile(f)
    old = (
        pd.read_parquet(PRIOR / "outputs/predictions.parquet").set_index("race_key").loc[p.race_key]
    )
    for name in ["axis_number", "axis_horse_id", "collapsed", "base_risk"]:
        assert np.array_equal(old[name], p[name])
    for name in ["raw", "constant", "joint"]:
        p[name] = old[name].to_numpy()
    coefficients = []
    for year in [2024, 2025, 2026]:
        tr = d[d.year.lt(year) & target(d)]
        te = eval_d[eval_d.year.eq(year)]
        assert tr.race_date.max() < te.race_date.min()
        for variant, names in FEATURES.items():
            scales = {}
            for n in names:
                v = inputs(tr)[n].to_numpy(dtype=float)
                v = v[np.isfinite(v)]
                scales[n] = dict(mean=float(v.mean()), std=float(v.std()) or 1.0)
            model = dict(
                variant=variant,
                features=names,
                scales=scales,
                l2=L2,
                evaluation_year=year,
                train_n=len(tr),
                train_years=list(range(2020, year)),
                train_end=str(tr.race_date.max().date()),
                train_start=str(tr.race_date.min().date()),
            )
            x, y, offset = (
                design(tr, model),
                tr.collapsed.to_numpy(dtype=float),
                logit(tr.base_risk.to_numpy()),
            )
            fit = minimize(
                objective,
                np.zeros(x.shape[1]),
                args=(x, offset, y),
                jac=True,
                method="BFGS",
                options=dict(gtol=1e-7, maxiter=1000),
            )
            loss, grad = objective(fit.x, x, offset, y)
            assert abs(grad).max() < 1e-4
            model.update(
                coefficients=fit.x.tolist(),
                objective=loss,
                max_abs_gradient=float(abs(grad).max()),
                optimizer_success=bool(fit.success),
            )
            save(OUT / "models" / f"{variant}_{year}.json", model)
            p.loc[te.index, variant] = predict(te, model)
            terms = ["intercept"] + [t for n in names for t in [n, n + "_missing"]]
            if variant == "finish_interaction":
                terms += ["early_positive_x_g3f", "early_positive_x_g1f"]
            for term, coef in zip(terms, fit.x, strict=True):
                coefficients.append(
                    dict(year=year, variant=variant, term=term, coefficient=float(coef))
                )
            print("Fit", year, variant, "n", len(tr), flush=True)
    p.to_parquet(OUT / "predictions.parquet", index=False)
    pd.DataFrame(coefficients).to_csv(OUT / "coefficients.csv", index=False)
    quality, differences, profiles, outcomes = [], [], [], []
    for period, frame in periods(p):
        for group, g in groups(frame):
            y = g.collapsed.to_numpy()
            for variant in VARIANTS:
                q = g[variant].to_numpy()
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
                        brier=float(losses(q, y)["brier"].mean()),
                        logloss=float(losses(q, y)["logloss"].mean()),
                        mean_cut=float(cut.mean()),
                        cut_p10=float(np.quantile(cut, 0.1)),
                        cut_p90=float(np.quantile(cut, 0.9)),
                    )
                )
            for variant in FEATURES:
                for ref in ["joint", "constant", "raw"]:
                    for metric in ["brier", "logloss"]:
                        v = (
                            losses(g[variant].to_numpy(), y)[metric]
                            - losses(g[ref].to_numpy(), y)[metric]
                        )
                        lo, hi = interval(v, g.race_date.to_numpy())
                        differences.append(
                            dict(
                                period=period,
                                group=group,
                                variant=variant,
                                reference=ref,
                                metric=metric,
                                n=len(g),
                                difference=float(v.mean()),
                                low=float(lo),
                                high=float(hi),
                            )
                        )
        for label, h in frame[frame.is_target].groupby("profile"):
            for variant in VARIANTS:
                profiles.append(
                    dict(
                        period=period,
                        profile=label,
                        variant=variant,
                        n=len(h),
                        actual_top3=float(1 - h.collapsed.mean()),
                        mean_top3=float(1 - h[variant].mean()),
                        brier=float(((h[variant] - h.collapsed) ** 2).mean()),
                    )
                )
        for outcome, h in frame[frame.is_target].groupby("collapsed"):
            for variant in ["joint", "constant", *FEATURES]:
                v = (h[variant] - outcome) ** 2 - (h.joint - outcome) ** 2
                outcomes.append(
                    dict(
                        period=period,
                        collapsed=int(outcome),
                        variant=variant,
                        n=len(h),
                        early=float(h.early.mean()),
                        g3f=float(h.g3f.mean()),
                        g1f=float(h.g1f.mean()),
                        risk=float(h[variant].mean()),
                        brier_difference=float(v.mean()),
                        brier_difference_sum=float(v.sum()),
                    )
                )
    pd.DataFrame(quality).to_csv(OUT / "quality.csv", index=False)
    delta = pd.DataFrame(differences)
    delta.to_csv(OUT / "paired_differences.csv", index=False)
    pd.DataFrame(profiles).to_csv(OUT / "profiles.csv", index=False)
    pd.DataFrame(outcomes).to_csv(OUT / "outcome_allocation.csv", index=False)
    examples = []
    model = json.loads((OUT / "models/finish_interaction_2026.json").read_text())
    for g3f in [0.0, 1.0, 2.0]:
        for g1f in [0.0, 0.4, 0.8]:
            dummy = pd.DataFrame(
                dict(
                    base_risk=[0.25],
                    axis_grade=[5],
                    axis_gap_section_early_mean3=[-0.5],
                    axis_moist_last3_record_index_mean=[0.5],
                    axis_gap_section_last600_mean3=[-g3f],
                    axis_gap_section_late_mean3=[-g1f],
                )
            )
            q = predict(dummy, model)[0]
            examples.append(
                dict(
                    early=0.5,
                    recent=0.5,
                    g3f=g3f,
                    g1f=g1f,
                    raw_top3=0.75,
                    adjusted_top3=float(1 - q),
                )
            )
    pd.DataFrame(examples).to_csv(OUT / "examples.csv", index=False)
    prim = delta.query(
        "group=='target' and variant=='finish_interaction' "
        "and reference=='joint' and metric=='brier'"
    )
    allrow = prim[prim.period.eq("all")].iloc[0]
    consistent = (
        allrow.high < 0 and prim[prim.period.isin(["2024", "2025", "2026"])].difference.lt(0).all()
    )
    save(
        OUT / "decision.json",
        dict(
            primary_difference=allrow.difference,
            primary_low=allrow.low,
            primary_high=allrow.high,
            consistent_evidence=bool(consistent),
            exploratory=True,
            promotion=False,
        ),
    )
    save(
        OUT / "cohort.json",
        dict(
            races=len(p),
            target_races=int(p.is_target.sum()),
            new_small_models=12,
            new_ability_models=0,
            end_date=str(p.race_date.max().date()),
            database_access=False,
            network_access=False,
            jeju_access=False,
            future_access=False,
        ),
    )
    check()
    print(pd.DataFrame(quality).query("group=='target'").to_string(index=False), flush=True)
    print(prim.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
