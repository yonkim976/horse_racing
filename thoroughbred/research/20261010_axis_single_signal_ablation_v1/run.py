"""Prespecified single-condition ablation, plus a strictly local grade5 offset."""

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
PRIOR = R / "20261010_axis_signal_calibration_v1"
spec = importlib.util.spec_from_file_location("frozen_axis_calibration39", PRIOR / "run.py")
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)
sha, save = e.sha, e.save
FEATURE_SETS = {
    "early_only": [0, 1, 2, 5],
    "distance_only": [0, 1, 3, 6],
    "grade5_only": [0, 1, 4, 7],
    "grade5_local_raw": [4],
}
REUSED = ["raw", "calibration", "signals"]
VARIANTS = REUSED + list(FEATURE_SETS)
PAIRS = (
    [(v, "calibration") for v in FEATURE_SETS]
    + [(v, "raw") for v in FEATURE_SETS]
    + [(v, "signals") for v in FEATURE_SETS]
)


def check():
    e.check()
    for name, value in json.loads((OUT / "source_lock.json").read_text()).items():
        assert sha(ROOT / name) == value, name


def local_objective(beta, x, offset, y):
    z = offset + x @ beta
    return float(np.logaddexp(0, z).sum() - y @ z + e.L2 * np.sum(beta**2) / 2), x.T @ (
        expit(z) - y
    ) + e.L2 * beta


def predict(d, artifact):
    x = e.design(d)[:, artifact["indices"]]
    z = x @ np.array(artifact["coefficients"])
    if artifact["variant"] == "grade5_local_raw":
        z = z + logit(np.clip(d.base_risk.to_numpy(), 1e-8, 1 - 1e-8))
        # Preserve exact original floating values outside the selected condition.
        return np.where(x[:, 0] == 0, d.base_risk.to_numpy(), expit(z))
    return expit(z)


def groups(d):
    yield from e.groups(d)
    yield "outside_high_probability_grade5", d[d.high_probability_grade5.eq(0)]


def paired_interval(values, dates):
    a = pd.DataFrame(dict(value=values, date=dates)).groupby("date").value.agg(["sum", "count"])
    rng = np.random.default_rng(e.SEED)
    w = rng.multinomial(len(a), np.full(len(a), 1 / len(a)), e.B)
    draws = (w @ a["sum"].to_numpy()) / (w @ a["count"].to_numpy(dtype=float))
    low, high = np.quantile(draws, [0.025, 0.975])
    lo3, hi3 = np.quantile(draws, [0.05 / 6, 1 - 0.05 / 6])
    return float(low), float(high), float(lo3), float(hi3)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    assert not (OUT / "source_lock.json").exists()
    paths = [
        HERE / "PLAN.md",
        HERE / "run.py",
        HERE / "verify.py",
        PRIOR / "run.py",
        PRIOR / "outputs/race_inputs.parquet",
        PRIOR / "outputs/risk_predictions.parquet",
        PRIOR / "outputs/verification.json",
        PRIOR / "outputs/future_validation_contract.json",
        e.REGISTRY,
        e.BASE,
    ] + sorted((PRIOR / "outputs/models").glob("*.json"))
    save(OUT / "source_lock.json", {str(p.relative_to(ROOT)): sha(p) for p in paths})
    d = pd.read_parquet(PRIOR / "outputs/race_inputs.parquet")
    x = e.design(d)
    predictions = [pd.read_parquet(PRIOR / "outputs/risk_predictions.parquet")]
    coefficients = []
    for year in [2024, 2025, 2026]:
        train, prior, test = d.year.lt(year), d.year.eq(year - 1), d.year.eq(year)
        y = d.loc[train, "collapsed"].to_numpy(dtype=float)
        for variant, indices in FEATURE_SETS.items():
            if variant == "grade5_local_raw":
                offset = logit(np.clip(d.loc[train, "base_risk"].to_numpy(), 1e-8, 1 - 1e-8))
                result = minimize(
                    local_objective,
                    np.zeros(1),
                    args=(x[train][:, indices], offset, y),
                    jac=True,
                    method="BFGS",
                    options={"gtol": 1e-7, "maxiter": 1000},
                )
                beta = result.x
                loss, grad = local_objective(beta, x[train][:, indices], offset, y)
                assert np.max(np.abs(grad)) < 1e-4
                diag = dict(
                    optimizer_success=bool(result.success),
                    objective=loss,
                    max_abs_gradient=float(np.max(np.abs(grad))),
                )
            else:
                beta, diag = e.fit(x[train][:, indices], y)
            artifact = dict(
                variant=variant,
                indices=indices,
                features=[e.FEATURES[i] for i in indices],
                coefficients=beta.tolist(),
                evaluation_year=year,
                train_start=str(d.loc[train, "race_date"].min().date()),
                train_end=str(d.loc[train, "race_date"].max().date()),
                train_years=list(range(2020, year)),
                train_n=int(train.sum()),
                l2=e.L2,
                gradient_diagnostics=diag,
                offset="logit_base_risk" if variant == "grade5_local_raw" else None,
            )
            risk, prior_risk = predict(d.loc[test], artifact), predict(d.loc[prior], artifact)
            threshold = float(np.quantile(prior_risk, 0.7))
            artifact["warning_threshold"], artifact["threshold_source_year"] = threshold, year - 1
            save(OUT / "models" / f"{variant}_{year}.json", artifact)
            for name, value in zip(artifact["features"], beta, strict=True):
                coefficients.append(
                    dict(variant=variant, year=year, feature=name, coefficient=float(value))
                )
            g = d.loc[
                test,
                [
                    "race_key",
                    "race_date",
                    "year",
                    "meet",
                    "axis_number",
                    "axis_horse_id",
                    "collapsed",
                    "base_risk",
                    *e.FEATURES[2:],
                ],
            ].copy()
            g["variant"], g["risk"], g["threshold"], g["flag"] = (
                variant,
                risk,
                threshold,
                risk >= threshold,
            )
            predictions.append(g)
            print("Fit", variant, year, flush=True)
    p = pd.concat(predictions, ignore_index=True)
    p.to_parquet(OUT / "risk_predictions.parquet", index=False)
    pd.DataFrame(coefficients).to_csv(OUT / "coefficients.csv", index=False)
    quality, differences = [], []
    for tag, frame in e.periods(p):
        for group, g in groups(frame):
            for variant, h in g.groupby("variant"):
                quality.append(dict(period=tag, group=group, variant=variant, **e.metrics(h)))
            wide = g.pivot(index="race_key", columns="variant", values="risk")
            meta = g.drop_duplicates("race_key").set_index("race_key").loc[wide.index]
            y = meta.collapsed.to_numpy()
            losses = {}
            for variant in VARIANTS:
                q = np.clip(wide[variant].to_numpy(), 1e-12, 1 - 1e-12)
                losses[variant, "brier"] = (q - y) ** 2
                losses[variant, "logloss"] = -y * np.log(q) - (1 - y) * np.log1p(-q)
            for left, right in PAIRS:
                for metric in ["brier", "logloss"]:
                    delta = losses[left, metric] - losses[right, metric]
                    lo, hi, lo3, hi3 = paired_interval(delta, meta.race_date.to_numpy())
                    differences.append(
                        dict(
                            period=tag,
                            group=group,
                            left=left,
                            right=right,
                            metric=metric,
                            n=len(meta),
                            difference=float(delta.mean()),
                            low=lo,
                            high=hi,
                            bonferroni3_low=lo3,
                            bonferroni3_high=hi3,
                            primary_family=tag == "all"
                            and group == "all"
                            and metric == "brier"
                            and left in ["early_only", "distance_only", "grade5_only"]
                            and right == "calibration",
                        )
                    )
    pd.DataFrame(quality).to_csv(OUT / "quality.csv", index=False)
    pd.DataFrame(differences).to_csv(OUT / "paired_differences.csv", index=False)
    save(
        OUT / "cohort.json",
        dict(
            races=int(d.year.ge(2024).sum()),
            start_date="2024-01-05",
            end_date="2026-09-20",
            training_source_races=len(d),
            new_small_models=12,
            reused_small_models=6,
            variants=VARIANTS,
            new_horse_ability_models=0,
            future_access=False,
        ),
    )
    check()
    print(
        pd.DataFrame(quality).query("period=='all' and group=='all'").to_string(index=False),
        flush=True,
    )
    print(pd.DataFrame(differences).query("primary_family").to_string(index=False), flush=True)
    print(
        pd.DataFrame(quality)
        .query("period=='all' and group=='high_probability_grade5'")
        .to_string(index=False),
        flush=True,
    )


if __name__ == "__main__":
    main()
