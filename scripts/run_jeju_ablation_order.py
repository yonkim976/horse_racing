"""Five group ablations and expanded joint/order models, 2025 development only."""

from __future__ import annotations

import json
import pickle
import shutil
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl
from scipy.optimize import minimize, minimize_scalar

from horse_racing.analysis.jeju_hybrid_evaluation import (
    accepted_layout,
    conditional_calibration_loss,
    evaluate_hybrid_race,
)
from horse_racing.analysis.jeju_joint_evaluation import evaluate_joint_race
from horse_racing.analysis.jeju_joint_top3 import JointTop3MLP, build_layout
from horse_racing.analysis.jeju_place_probability import evaluate_place_race
from horse_racing.analysis.jeju_top3_evaluation import evaluate_race
from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor
from scripts.run_jeju_joint_top3 import DATA, H3, ROOT, load_data, sha
from scripts.run_jeju_top3_experiment import order_loss, race_groups

OUT = ROOT / "data/research/jeju_native_ablation_order_v6_20260916"
CTX = ROOT / "data/research/jeju_native_context_features_v1_20260916"
V3 = ROOT / "data/research/jeju_native_h3_experiment_v3_20260916"
V4 = ROOT / "data/research/jeju_native_joint_top3_v4_20260916"
V5 = ROOT / "data/research/jeju_native_context_experiment_v5_20260916"


def save(name, value):
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n"
    )


def data_frame(protocol):
    frame, meta, truth, folds = load_data()
    finish = pl.read_parquet(DATA / "labels.parquet").select("entry_id", "finish_position")
    extra = pl.read_parquet(CTX / "features.parquet").select(
        "entry_id", *protocol["context_features"], *protocol["form_features"]
    )
    return (
        frame.join(finish, on="entry_id", validate="1:1").join(
            extra, on="entry_id", validate="1:1"
        ),
        meta,
        truth,
        folds,
    )


def rank_scores(bundle, frame):
    x = bundle["preprocessor"].transform(frame)
    return np.mean([m.predict(x, raw_score=True) for m in bundle["models"]], axis=0)


def order_scores(bundle, frame):
    x = bundle["preprocessor"].transform(frame)
    return np.mean([m.predict(x)[:, 1] for m in bundle["models"]], axis=0)


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    assert not (OUT / "run_ledger.json").exists(), "Refuse overwrite"
    for folder, key in [
        (DATA, "dataset_manifest_sha256"),
        (H3, "h3_manifest_sha256"),
        (V3, "v3_manifest_sha256"),
        (V4, "v4_manifest_sha256"),
        (CTX, "context_manifest_sha256"),
        (V5, "v5_manifest_sha256"),
    ]:
        assert sha(folder / "manifest.json") == protocol[key]
    for sub in ["reproduce", "bundles"]:
        (OUT / sub).mkdir(exist_ok=True)
    for path in [
        Path(__file__),
        ROOT / "scripts/report_jeju_ablation_order.py",
        ROOT / "scripts/verify_jeju_ablation_order.py",
        ROOT / "scripts/run_jeju_joint_top3.py",
        ROOT / "scripts/run_jeju_top3_experiment.py",
        ROOT / "scripts/build_jeju_context_features.py",
        ROOT / "src/horse_racing/analysis/jeju_context_features.py",
        ROOT / "src/horse_racing/analysis/jeju_hybrid_evaluation.py",
        ROOT / "src/horse_racing/analysis/jeju_top3_preprocessing.py",
        ROOT / "src/horse_racing/analysis/jeju_top3_evaluation.py",
        ROOT / "src/horse_racing/analysis/jeju_place_probability.py",
        ROOT / "src/horse_racing/analysis/jeju_joint_top3.py",
        ROOT / "src/horse_racing/analysis/jeju_joint_evaluation.py",
        ROOT / "src/horse_racing/analysis/jeju_top3_direct.py",
        ROOT / "tests/test_jeju_hybrid_evaluation.py",
        ROOT / "tests/test_jeju_context_features.py",
        ROOT / "scripts/freeze_jeju_ablation_protocol.py",
        ROOT / "tests/test_jeju_ablation_order.py",
        ROOT / "pyproject.toml",
    ]:
        shutil.copy2(path, OUT / "reproduce" / path.name)
    ledger = dict(
        status="running",
        started_at=datetime.now(UTC).isoformat(),
        protocol_sha256=sha(OUT / "protocol.json"),
        estimator_fits=[],
        calibration_fits=[],
        reference_refits=0,
    )

    def flush():
        save("run_ledger.json", ledger)

    flush()
    frame, meta, truth, folds = data_frame(protocol)
    oldp = pl.read_parquet(V5 / "race_predictions.parquet").filter(
        pl.col("model").is_in(protocol["references"])
    )
    oldh = pl.read_parquet(V5 / "horse_predictions.parquet").filter(
        pl.col("model").is_in(protocol["references"])
    )
    predictions = oldp.to_dicts()
    horses = oldh.to_dicts()
    dimensions = []

    def evaluate(name, fold, ev, raw, beta, ob=None, order_beta=None, joint=False):
        for lo, hi, _ in race_groups(ev, truth):
            race = ev.slice(lo, hi - lo)
            rid = int(race["race_id"][0])
            ids = race["horse_id"].to_list()
            official = race.filter(pl.col("label_top3") == 1)["horse_id"].to_list()
            if ob is None:
                metrics = {
                    **evaluate_place_race(ids, raw[lo:hi], official, beta=beta),
                    **evaluate_race(ids, raw[lo:hi], truth[rid], beta=beta),
                }
            else:
                metrics = (evaluate_joint_race if joint else evaluate_hybrid_race)(
                    ids,
                    raw[lo:hi],
                    ob[lo:hi],
                    truth[rid],
                    official,
                    beta_set=beta,
                    beta_order=order_beta,
                )
            marginal = metrics.pop("pl_marginals")
            labels = metrics.pop("official_labels")
            row = dict(
                model=name,
                fold=fold,
                race_id=rid,
                event_date=str(race["event_date"][0]),
                field_size=len(race),
                distance_m=int(race["distance_m"][0]),
                boundary_tie=meta[rid]["boundary_tie"],
                podium_tie=meta[rid]["podium_tie"],
                **metrics,
            )
            predictions.append(row)
            for i, horse in enumerate(ids):
                horses.append(
                    dict(
                        model=name,
                        fold=fold,
                        race_id=rid,
                        horse_id=horse,
                        event_date=row["event_date"],
                        score=float(raw[lo + i]),
                        beta=float(beta),
                        order_score=None if ob is None else float(ob[lo + i]),
                        beta_set=None if ob is None else float(beta),
                        beta_order=order_beta,
                        pl_place_probability=float(marginal[i]),
                        official_top3=int(labels[i]),
                        boundary_tie=row["boundary_tie"],
                        selected=horse == row["pick_horse_id"],
                    )
                )
        pl.DataFrame(predictions, infer_schema_length=None).write_parquet(
            OUT / "race_predictions.parquet"
        )
        pl.DataFrame(horses, infer_schema_length=None).write_parquet(
            OUT / "horse_predictions.parquet"
        )
        print(f"{fold} {name} saved", flush=True)

    for fold in sorted(folds["fold_id"].unique()):
        split = folds.filter(pl.col("fold_id") == fold)
        parts = {
            role: frame.join(
                split.filter(pl.col("role") == role).select("race_id"), on="race_id", how="semi"
            ).sort("race_id", "horse_id")
            for role in ["fit", "tune", "calibration", "evaluation"]
        }
        groups = {role: race_groups(f, truth) for role, f in parts.items()}
        for left, right in [
            ("fit", "tune"),
            ("tune", "calibration"),
            ("calibration", "evaluation"),
        ]:
            assert parts[left]["event_date"].max() < parts[right]["event_date"].min()
        rank_bundles = {}
        with (V3 / "bundles" / f"{fold}__R_H3.pkl").open("rb") as f:
            rank_bundles["R_H3"] = pickle.load(f)
        with (V4 / "bundles" / f"{fold}__J_H3_w10.pkl").open("rb") as f:
            obundle = pickle.load(f)
        with (V5 / "bundles" / f"{fold}__R_FORM.pkl").open("rb") as f:
            rank_bundles["R_FORM"] = pickle.load(f)
        for name, features in protocol["rank_candidates"].items():
            pre = FitPreprocessor().fit(parts["fit"], features)
            xs = {k: pre.transform(v) for k, v in parts.items()}
            dimensions.append(
                dict(
                    model=name,
                    fold=fold,
                    features=features,
                    input_names=pre.names,
                    input_dimensions=len(pre.names),
                )
            )
            save("feature_dimensions.json", dimensions)
            ys = {
                k: np.where(
                    np.isfinite(v["finish_position"].to_numpy())
                    & (v["finish_position"].to_numpy() <= 3),
                    4 - v["finish_position"].to_numpy(),
                    0,
                ).astype(int)
                for k, v in parts.items()
            }
            models = []
            for seed in protocol["seeds"]:
                event = dict(
                    model=name,
                    fold=fold,
                    seed=seed,
                    status="started",
                    fit_races=len(groups["fit"]),
                    tune_races=len(groups["tune"]),
                )
                ledger["estimator_fits"].append(event)
                flush()
                model = lgb.LGBMRanker(
                    objective="lambdarank",
                    label_gain=[0, 1, 3, 7],
                    random_state=seed,
                    verbosity=-1,
                    **protocol["params"],
                )
                model.fit(
                    xs["fit"],
                    ys["fit"],
                    group=[hi - lo for lo, hi, _ in groups["fit"]],
                    eval_set=[(xs["tune"], ys["tune"])],
                    eval_group=[[hi - lo for lo, hi, _ in groups["tune"]]],
                    eval_at=[3],
                    callbacks=[lgb.early_stopping(30, verbose=False)],
                )
                models.append(model)
                event.update(status="complete", best_iteration=int(model.best_iteration_))
                flush()
            bundle = dict(
                kind="ranker",
                model_name=name,
                fold=fold,
                models=models,
                preprocessor=pre,
                features=features,
            )
            raw = {k: rank_scores(bundle, parts[k]) for k in ["calibration", "evaluation"]}
            event = dict(
                model=name, fold=fold, type="PL", partition="calibration", status="started"
            )
            ledger["calibration_fits"].append(event)
            flush()
            opt = minimize_scalar(
                lambda x, raw=raw, groups=groups: order_loss(
                    raw["calibration"], groups["calibration"], np.exp(x)
                ),
                bounds=(-4, 4),
                method="bounded",
                options={"xatol": 1e-5},
            )
            assert opt.success
            bundle["beta"] = float(np.exp(opt.x))
            event.update(status="complete", beta=bundle["beta"], objective=float(opt.fun))
            flush()
            rank_bundles[name] = bundle
            with (OUT / "bundles" / f"{fold}__{name}.pkl").open("wb") as f:
                pickle.dump(bundle, f)
            evaluate(name, fold, parts["evaluation"], raw["evaluation"], bundle["beta"])
        name = "J_FORM"
        features = protocol["joint_features"]
        pre = FitPreprocessor().fit(parts["fit"], features)
        xs = {k: pre.transform(v) for k, v in parts.items()}
        sizes = {k: [hi - lo for lo, hi, _ in g] for k, g in groups.items()}
        accepted = {k: [o for _, _, o in g] for k, g in groups.items()}
        dimensions.append(
            dict(
                model=name,
                fold=fold,
                features=features,
                input_names=pre.names,
                input_dimensions=len(pre.names),
            )
        )
        save("feature_dimensions.json", dimensions)
        models = []
        for seed in protocol["seeds"]:
            event = dict(
                model=name,
                fold=fold,
                seed=seed,
                status="started",
                fit_races=len(groups["fit"]),
                tune_races=len(groups["tune"]),
            )
            ledger["estimator_fits"].append(event)
            flush()
            print(f"{fold} {name} seed{seed} started", flush=True)
            model = JointTop3MLP(**protocol["joint_params"])
            model.fit(
                xs["fit"],
                sizes["fit"],
                accepted["fit"],
                tune=(xs["tune"], sizes["tune"], accepted["tune"]),
                seed=seed,
                joint_weight=1.0,
            )
            models.append(model)
            event.update(
                status="complete",
                diagnostics={
                    k: v
                    for k, v in vars(model).items()
                    if k.endswith("_") and isinstance(v, (str, int, float, bool, type(None)))
                },
            )
            flush()
            print(f"{fold} {name} seed{seed} complete", flush=True)
        raw_joint = {
            k: np.mean([m.predict(xs[k]) for m in models], axis=0)
            for k in ["calibration", "evaluation"]
        }
        layout = build_layout(sizes["calibration"], accepted["calibration"])
        event = dict(
            model=name,
            fold=fold,
            type="joint_two_temperature",
            partition="calibration",
            status="started",
        )
        ledger["calibration_fits"].append(event)
        flush()

        def objective(log_betas, raw_joint=raw_joint, model=models[0], layout=layout):
            scaled = raw_joint["calibration"] * np.exp(log_betas)
            loss, grad = model.scores_loss_and_gradient(scaled, layout, joint_weight=1.0)
            return loss, np.sum(grad * scaled, axis=0)

        opt = minimize(
            objective,
            np.zeros(2),
            jac=True,
            method="L-BFGS-B",
            bounds=[(-4, 4), (-4, 4)],
            options={"maxiter": 100, "ftol": 1e-10},
        )
        assert opt.success, str(opt.message)
        betas = np.exp(opt.x)
        event.update(
            status="complete",
            betas=betas.tolist(),
            loss=float(opt.fun),
            iterations=int(opt.nit),
            at_boundary=bool(np.any(np.abs(opt.x) > 3.999)),
        )
        flush()
        obundle = dict(
            kind="joint",
            model_name=name,
            fold=fold,
            models=models,
            preprocessor=pre,
            features=features,
            betas=betas,
            joint_weight=1.0,
        )
        with (OUT / "bundles" / f"{fold}__{name}.pkl").open("wb") as f:
            pickle.dump(obundle, f)
        evaluate(
            name,
            fold,
            parts["evaluation"],
            raw_joint["evaluation"][:, 0],
            float(betas[0]),
            raw_joint["evaluation"][:, 1],
            float(betas[1]),
            joint=True,
        )
        braw = {k: order_scores(obundle, parts[k]) for k in ["calibration", "evaluation"]}
        for name, parent in [("HY_FORM_ORDER", "R_FORM")]:
            rb = rank_bundles[parent]
            raw = {k: rank_scores(rb, parts[k]) for k in ["calibration", "evaluation"]}
            cal = []
            for lo, hi, _local_orders in groups["calibration"]:
                race = parts["calibration"].slice(lo, hi - lo)
                rid = int(race["race_id"][0])
                cal.append(
                    accepted_layout(
                        race["horse_id"].to_list(),
                        raw["calibration"][lo:hi],
                        braw["calibration"][lo:hi],
                        truth[rid],
                        rb["beta"],
                    )
                )
            event = dict(
                model=name,
                fold=fold,
                type="conditional_order_temperature",
                partition="calibration",
                status="started",
                set_parent=parent,
                order_parent="J_FORM",
            )
            ledger["calibration_fits"].append(event)
            flush()
            opt = minimize_scalar(
                lambda x, cal=cal: conditional_calibration_loss(x, cal),
                bounds=(-4, 4),
                method="bounded",
                options={"xatol": 1e-5},
            )
            assert opt.success
            beta = float(np.exp(opt.x))
            event.update(
                status="complete",
                beta_order=beta,
                objective=float(opt.fun),
                at_boundary=bool(abs(opt.x) > 3.999),
            )
            flush()
            bundle = dict(
                kind="hybrid",
                model_name=name,
                fold=fold,
                rank_bundle=rb,
                order_bundle=obundle,
                beta_order=beta,
                set_parent=parent,
            )
            with (OUT / "bundles" / f"{fold}__{name}.pkl").open("wb") as f:
                pickle.dump(bundle, f)
            evaluate(
                name,
                fold,
                parts["evaluation"],
                raw["evaluation"],
                rb["beta"],
                braw["evaluation"],
                beta,
            )
    p = pl.DataFrame(predictions, infer_schema_length=None)
    assert len(p) == 13 * 715 and p["model"].n_unique() == 13
    assert all(
        p.filter(pl.col("model") == m)["race_id"].n_unique() == 715 for m in p["model"].unique()
    )
    assert len(ledger["estimator_fits"]) == 48 and len(ledger["calibration_fits"]) == 28
    ledger.update(
        status="complete",
        completed_at=datetime.now(UTC).isoformat(),
        models=13,
        new_bundles=28,
        common_races=715,
        predictions_2026=0,
    )
    flush()
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
