"""Direct conditional order and contextual rebound factorial comparison, 2025 development only."""

from __future__ import annotations

import json
import pickle
import shutil
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl
from scipy.optimize import minimize_scalar

from horse_racing.analysis.jeju_conditional_order import ConditionalOrderMLP
from horse_racing.analysis.jeju_hybrid_evaluation import (
    accepted_layout,
    conditional_calibration_loss,
    evaluate_hybrid_race,
)
from horse_racing.analysis.jeju_place_probability import evaluate_place_race
from horse_racing.analysis.jeju_top3_evaluation import evaluate_race
from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor
from scripts.run_jeju_joint_top3 import DATA, H3, ROOT, load_data, sha
from scripts.run_jeju_top3_experiment import order_loss, race_groups

OUT = ROOT / "data/research/jeju_native_conditional_order_v7_20260916"
CTX = ROOT / "data/research/jeju_native_context_features_v1_20260916"
V3 = ROOT / "data/research/jeju_native_h3_experiment_v3_20260916"
V4 = ROOT / "data/research/jeju_native_joint_top3_v4_20260916"
V5 = ROOT / "data/research/jeju_native_context_experiment_v5_20260916"
V6 = ROOT / "data/research/jeju_native_ablation_order_v6_20260916"
RB = ROOT / "data/research/jeju_native_rebound_features_v1_20260916"


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
        frame.join(finish, on="entry_id", validate="1:1")
        .join(extra, on="entry_id", validate="1:1")
        .join(pl.read_parquet(RB / "features.parquet"), on="entry_id", validate="1:1"),
        meta,
        truth,
        folds,
    )


def rank_scores(bundle, frame):
    x = bundle["preprocessor"].transform(frame)
    return np.mean([m.predict(x, raw_score=True) for m in bundle["models"]], axis=0)


def order_scores(bundle, frame):
    x = bundle["preprocessor"].transform(frame)
    return np.mean([m.predict(x) for m in bundle["models"]], axis=0)


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
        (V6, "v6_manifest_sha256"),
        (RB, "rebound_manifest_sha256"),
    ]:
        assert sha(folder / "manifest.json") == protocol[key]
    for sub in ["reproduce", "bundles"]:
        (OUT / sub).mkdir(exist_ok=True)
    for path in [
        Path(__file__),
        ROOT / "scripts/report_jeju_conditional_experiment.py",
        ROOT / "scripts/verify_jeju_conditional_experiment.py",
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
        ROOT / "scripts/freeze_jeju_conditional_protocol.py",
        ROOT / "scripts/build_jeju_rebound_features.py",
        ROOT / "src/horse_racing/analysis/jeju_rebound_features.py",
        ROOT / "src/horse_racing/analysis/jeju_conditional_order.py",
        ROOT / "tests/test_jeju_conditional_order.py",
        ROOT / "tests/test_jeju_rebound_features.py",
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
    oldp = pl.read_parquet(V6 / "race_predictions.parquet").filter(
        pl.col("model").is_in(protocol["references"])
    )
    oldh = pl.read_parquet(V6 / "horse_predictions.parquet").filter(
        pl.col("model").is_in(protocol["references"])
    )
    predictions = oldp.to_dicts()
    horses = oldh.to_dicts()
    dimensions = []

    def evaluate(name, fold, ev, raw, beta, ob=None, order_beta=None):
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
                metrics = evaluate_hybrid_race(
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
                    **protocol["rank_params"],
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
        order_bundles = {}
        for name, features in protocol["order_candidates"].items():
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
                model = ConditionalOrderMLP(**protocol["order_params"])
                model.fit(
                    xs["fit"],
                    sizes["fit"],
                    accepted["fit"],
                    tune=(xs["tune"], sizes["tune"], accepted["tune"]),
                    seed=seed,
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
            bundle = dict(
                kind="conditional",
                model_name=name,
                fold=fold,
                models=models,
                preprocessor=pre,
                features=features,
            )
            order_bundles[name] = bundle
            with (OUT / "bundles" / f"{fold}__{name}.pkl").open("wb") as f:
                pickle.dump(bundle, f)
        for name, (parent, order_parent) in protocol["hybrids"].items():
            obundle = order_bundles[order_parent]
            braw = {k: order_scores(obundle, parts[k]) for k in ["calibration", "evaluation"]}
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
                order_parent=order_parent,
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
    assert len(p) == 10 * 715 and p["model"].n_unique() == 10
    assert all(
        p.filter(pl.col("model") == m)["race_id"].n_unique() == 715 for m in p["model"].unique()
    )
    assert len(ledger["estimator_fits"]) == 24 and len(ledger["calibration_fits"]) == 20
    ledger.update(
        status="complete",
        completed_at=datetime.now(UTC).isoformat(),
        models=10,
        new_bundles=28,
        common_races=715,
        predictions_2026=0,
    )
    flush()
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
