"""Three prespecified risk signals with expanding-window logistic calibration."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit, logit
from sklearn.metrics import roc_auc_score

HERE = Path(__file__).resolve().parent
R = HERE.parent
ROOT = R.parent.parent
OUT = HERE / "outputs"
A = R / "20261009_axis_collapse_v1/outputs/race_inputs.parquet"
H = R / "20261009_section_style_finish_v1/outputs/features.parquet"
PREVIOUS = R / "20261010_axis_probability_conditions_v1/outputs/races.parquet"
FUTURE = R / "20261009_late_recovery_ablation_v1/outputs/future_validation_contract.json"
REGISTRY = ROOT / "config/prediction_model_registry.json"
BASE = R / "20261008_profile_carried_weight_v1/outputs/research_baseline_selection.json"
FEATURES = [
    "intercept",
    "logit_base_risk",
    "early_slower",
    "distance_up200",
    "high_probability_grade5",
    "early_missing",
    "distance_missing",
    "high_probability_grade_missing",
]
VARIANTS = ["raw", "calibration", "signals"]
L2 = 10.0
SEED = 391010
B = 2000


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def check():
    for name, value in json.loads((OUT / "source_lock.json").read_text()).items():
        assert sha(ROOT / name) == value, name


def design(d):
    q = d.base_risk.to_numpy(dtype=float)
    assert np.isfinite(q).all() and ((q > 0) & (q < 1)).all()
    early = d.axis_gap_section_early_mean3
    delta = d.axis_distance_m - d.axis_section_previous_distance
    high = 1 - d.base_risk >= 0.7
    return np.column_stack(
        [
            np.ones(len(d)),
            logit(np.clip(q, 1e-8, 1 - 1e-8)),
            early.ge(0).astype(float),
            delta.ge(200).astype(float),
            (high & d.axis_grade.eq(5)).astype(float),
            early.isna().astype(float),
            delta.isna().astype(float),
            (high & d.axis_grade.isna()).astype(float),
        ]
    )


def objective(beta, x, y):
    center = np.zeros(len(beta))
    center[1] = 1
    penalty = np.ones(len(beta)) * L2
    penalty[0] = 0
    z = x @ beta
    loss = np.logaddexp(0, z).sum() - y @ z + 0.5 * np.sum(penalty * (beta - center) ** 2)
    grad = x.T @ (expit(z) - y) + penalty * (beta - center)
    return float(loss), grad


def fit(x, y):
    start = np.zeros(x.shape[1])
    start[1] = 1
    result = minimize(
        objective,
        start,
        args=(x, y),
        method="BFGS",
        jac=True,
        options={"gtol": 1e-7, "maxiter": 1000},
    )
    loss, gradient = objective(result.x, x, y)
    assert np.max(np.abs(gradient)) < 1e-4, result.message
    return result.x, dict(
        optimizer_success=bool(result.success),
        message=str(result.message),
        objective=loss,
        max_abs_gradient=float(np.max(np.abs(gradient))),
    )


def predict(d, artifact):
    """Use pre-race frozen original-axis inputs; does not pick another axis."""
    x = design(d)[:, : len(artifact["features"])]
    assert artifact["features"] == FEATURES[: x.shape[1]]
    return expit(x @ np.array(artifact["coefficients"]))


def periods(d):
    yield "all", d
    for y in [2024, 2025, 2026]:
        yield str(y), d[d.year.eq(y)]
    yield "2025_26", d[d.year.ge(2025)]


def groups(d):
    yield "all", d
    for meet in [1, 3]:
        yield f"meet{meet}", d[d.meet.eq(meet)]
    for name, mask in [
        ("prob70plus", 1 - d.base_risk >= 0.7),
        ("early_slower", d.early_slower.eq(1)),
        ("distance_up200", d.distance_up200.eq(1)),
        ("high_probability_grade5", d.high_probability_grade5.eq(1)),
    ]:
        yield name, d[mask]


def metrics(g):
    y, p = g.collapsed.to_numpy(), g.risk.to_numpy()
    p = np.clip(p, 1e-12, 1 - 1e-12)
    flag = g.flag.to_numpy(dtype=bool)
    quiet = ~flag
    return dict(
        n=len(g),
        failures=int(y.sum()),
        mean_risk=float(p.mean()),
        observed_risk=float(y.mean()),
        brier=float(np.mean((p - y) ** 2)),
        logloss=float(-np.mean(y * np.log(p) + (1 - y) * np.log1p(-p))),
        auc=float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else None,
        flagged=int(flag.sum()),
        flagged_failures=int(y[flag].sum()),
        flagged_rate=float(y[flag].mean()) if flag.any() else None,
        false_alarms=int((1 - y[flag]).sum()),
        quiet=int(quiet.sum()),
        quiet_axis_top3=float(1 - y[quiet].mean()) if quiet.any() else None,
    )


def interval(values, dates):
    a = pd.DataFrame(dict(value=values, date=dates)).groupby("date").value.agg(["sum", "count"])
    rng = np.random.default_rng(SEED)
    w = rng.multinomial(len(a), np.full(len(a), 1 / len(a)), B)
    v = (w @ a["sum"].to_numpy()) / (w @ a["count"].to_numpy(dtype=float))
    lo, hi = np.quantile(v, [0.025, 0.975])
    return float(lo), float(hi)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    assert not (OUT / "source_lock.json").exists()
    paths = [
        A,
        H,
        PREVIOUS,
        FUTURE,
        REGISTRY,
        BASE,
        HERE / "PLAN.md",
        HERE / "run.py",
        HERE / "verify.py",
    ]
    save(OUT / "source_lock.json", {str(p.relative_to(ROOT)): sha(p) for p in paths})
    d = pd.read_parquet(A).sort_values(["race_date", "race_key"]).reset_index(drop=True)
    x = design(d)
    for i, col in enumerate(FEATURES[2:], 2):
        d[col] = x[:, i]
    d.to_parquet(OUT / "race_inputs.parquet", index=False)
    predictions, coefficients, models = [], [], []
    for year in [2024, 2025, 2026]:
        train = d.year.lt(year)
        prior = d.year.eq(year - 1)
        test = d.year.eq(year)
        for variant in VARIANTS:
            artifact = None
            if variant == "raw":
                prior_p = d.loc[prior, "base_risk"].to_numpy()
                p = d.loc[test, "base_risk"].to_numpy()
            else:
                size = 2 if variant == "calibration" else len(FEATURES)
                beta, diag = fit(x[train, :size], d.loc[train, "collapsed"].to_numpy(dtype=float))
                artifact = dict(
                    variant=variant,
                    evaluation_year=year,
                    features=FEATURES[:size],
                    coefficients=beta.tolist(),
                    train_start=str(d.loc[train, "race_date"].min().date()),
                    train_end=str(d.loc[train, "race_date"].max().date()),
                    train_years=sorted(d.loc[train, "year"].unique().tolist()),
                    train_n=int(train.sum()),
                    l2=L2,
                    gradient_diagnostics=diag,
                )
                p, prior_p = predict(d.loc[test], artifact), predict(d.loc[prior], artifact)
                for name, value in zip(FEATURES[:size], beta, strict=True):
                    coefficients.append(
                        dict(
                            variant=variant,
                            year=year,
                            feature=name,
                            coefficient=float(value),
                            odds_multiplier=float(np.exp(value))
                            if name not in FEATURES[:2]
                            else None,
                        )
                    )
            threshold = float(np.quantile(prior_p, 0.7))
            if artifact is not None:
                artifact["warning_threshold"] = threshold
                artifact["threshold_source_year"] = year - 1
                path = OUT / "models" / f"{variant}_{year}.json"
                save(path, artifact)
                models.append(str(path.relative_to(ROOT)))
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
                    *FEATURES[2:],
                ],
            ].copy()
            g["variant"], g["risk"], g["threshold"], g["flag"] = (
                variant,
                p,
                threshold,
                p >= threshold,
            )
            predictions.append(g)
            print("Fit/predict", year, variant, "n", len(g), flush=True)
    p = pd.concat(predictions, ignore_index=True)
    p.to_parquet(OUT / "risk_predictions.parquet", index=False)
    pd.DataFrame(coefficients).to_csv(OUT / "coefficients.csv", index=False)
    quality, differences = [], []
    for tag, f in periods(p):
        for group, g in groups(f):
            for variant, h in g.groupby("variant"):
                quality.append(dict(period=tag, group=group, variant=variant, **metrics(h)))
            wide = g.pivot(index="race_key", columns="variant", values="risk")
            meta = g.drop_duplicates("race_key").set_index("race_key").loc[wide.index]
            y = meta.collapsed.to_numpy()
            for left, right in [
                ("signals", "calibration"),
                ("signals", "raw"),
                ("calibration", "raw"),
            ]:
                for metric in ["brier", "logloss"]:

                    def loss(q, y=y, metric=metric):
                        q = np.clip(q, 1e-12, 1 - 1e-12)
                        return (
                            (q - y) ** 2
                            if metric == "brier"
                            else -y * np.log(q) - (1 - y) * np.log1p(-q)
                        )

                    delta = loss(wide[left].to_numpy()) - loss(wide[right].to_numpy())
                    lo, hi = interval(delta, meta.race_date.to_numpy())
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
                        )
                    )
    pd.DataFrame(quality).to_csv(OUT / "quality.csv", index=False)
    pd.DataFrame(differences).to_csv(OUT / "paired_differences.csv", index=False)
    upstream = json.loads(FUTURE.read_text())
    prospective = [
        dict(path=name, sha256=sha(ROOT / name)) for name in models if name.endswith("_2026.json")
    ]
    save(
        OUT / "future_validation_contract.json",
        dict(
            status="frozen_not_evaluated",
            earliest_race_date="2026-10-11",
            last_race_date="2026-12-31",
            timezone="Asia/Seoul",
            source_data_end="2026-09-20",
            minimum_races=300,
            minimum_dates=20,
            primary_comparison="signals_minus_calibration_brier",
            variants=VARIANTS,
            risk_models=prospective,
            base_models=[v for v in upstream["models"] if v["variant"] == "baseline22"],
            upstream_contract_path=str(FUTURE.relative_to(ROOT)),
            upstream_contract_sha256=sha(FUTURE),
            prediction_timestamp_before_race_start_required=True,
            historical_cutoff_rule="T-2 calendar days, existing 730-day actual-slot contract",
            rule_changes_require_new_version=True,
            automatic_collection=False,
            live_predictions_generated=0,
            upstream_input_builder_and_timestamp_audit_still_required=True,
        ),
    )
    save(
        OUT / "cohort.json",
        dict(
            training_and_evaluation_races=len(d),
            evaluation_races=int(d.year.ge(2024).sum()),
            training_min_date=str(d.race_date.min().date()),
            source_max_date=str(d.race_date.max().date()),
            new_small_risk_models=len(models),
            new_horse_ability_models=0,
            prospective_evaluated_races=0,
        ),
    )
    check()
    print(
        pd.DataFrame(quality).query("period=='all' and group=='all'").to_string(index=False),
        flush=True,
    )
    print(
        pd.DataFrame(differences).query("period=='all' and group=='all'").to_string(index=False),
        flush=True,
    )


if __name__ == "__main__":
    main()
