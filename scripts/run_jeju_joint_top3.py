"""Predeclared joint podium-set/conditional-order development experiment."""

from __future__ import annotations

import hashlib
import json
import pickle
import platform
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl
from scipy.optimize import minimize

from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor
from scripts.run_jeju_top3_experiment import race_groups

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/jeju_native_joint_top3_v4_20260916"
OLD = ROOT / "data/research/jeju_native_h3_experiment_v3_20260916"
H3 = ROOT / "data/research/jeju_native_h3_features_v1_20260916"
DATA = ROOT / "data/research/jeju_native_top3_dataset_v1_20260915_r2"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n"
    )


def load_data():
    entries = pl.read_parquet(DATA / "entries.parquet").filter(
        pl.col("event_date").dt.year() <= 2025
    )
    states = pl.read_parquet(DATA / "horse_states.parquet").join(
        entries.select("entry_id"), on="entry_id", how="semi"
    )
    labels = pl.read_parquet(DATA / "labels.parquet").join(
        entries.select("entry_id"), on="entry_id", how="semi"
    )
    frame = (
        states.join(labels.select("entry_id", "label_top3"), on="entry_id", validate="1:1")
        .join(pl.read_parquet(H3 / "features.parquet"), on="entry_id", validate="1:1")
        .sort("race_id", "horse_id")
    )
    meta = {
        r["race_id"]: r
        for r in pl.read_parquet(DATA / "races.parquet")
        .filter(pl.col("event_date").dt.year() <= 2025)
        .iter_rows(named=True)
    }
    truth = {}
    for row in (
        pl.read_parquet(DATA / "accepted_orders.parquet")
        .filter(pl.col("event_date").dt.year() <= 2025)
        .iter_rows(named=True)
    ):
        truth.setdefault(row["race_id"], []).append(
            (row["first_horse_id"], row["second_horse_id"], row["third_horse_id"])
        )
    folds = pl.read_parquet(DATA / "fold_assignments.parquet").filter(
        pl.col("fold_id").str.starts_with("dev_2025")
    )
    return frame, meta, truth, folds


def main():
    from horse_racing.analysis.jeju_joint_evaluation import evaluate_joint_race
    from horse_racing.analysis.jeju_joint_top3 import (
        JointTop3MLP,
        build_layout,
    )

    protocol = json.loads((OUT / "protocol.json").read_text())
    for folder, key in [
        (DATA, "dataset_manifest_sha256"),
        (OLD, "parent_manifest_sha256"),
        (H3, "h3_feature_manifest_sha256"),
    ]:
        assert sha(folder / "manifest.json") == protocol[key]
    assert not (OUT / "run_ledger.json").exists(), "Never overwrite an experiment"
    for sub in ["bundles", "reproduce"]:
        (OUT / sub).mkdir(exist_ok=True)
    for path in [
        Path(__file__),
        ROOT / "scripts/report_jeju_joint_top3.py",
        ROOT / "scripts/verify_jeju_joint_top3.py",
        ROOT / "tests/test_jeju_joint_integration.py",
        ROOT / "docs/JEJU_NATIVE_JOINT_TOP3_PLAN_2026-09-16.md",
        ROOT / "scripts/run_jeju_top3_experiment.py",
        ROOT / "src/horse_racing/analysis/jeju_joint_top3.py",
        ROOT / "src/horse_racing/analysis/jeju_joint_evaluation.py",
        ROOT / "src/horse_racing/analysis/jeju_top3_preprocessing.py",
        ROOT / "tests/test_jeju_joint_top3.py",
        ROOT / "tests/test_jeju_joint_evaluation.py",
        ROOT / "pyproject.toml",
    ]:
        shutil.copy2(path, OUT / "reproduce" / path.name)
    ledger = dict(
        status="running",
        started_at=datetime.now(UTC).isoformat(),
        protocol_sha256=sha(OUT / "protocol.json"),
        estimator_fits=[],
        calibration_fits=[],
        evaluation_year=2025,
        reference_refits=0,
    )

    def flush():
        save("run_ledger.json", ledger)

    flush()
    frame, meta, truth, folds = load_data()
    registry = json.loads((DATA / "feature_registry.json").read_text())
    features = [
        r["feature_name"] for r in registry if r["feature_name"] not in protocol["aliases_removed"]
    ] + protocol["h3_features"]
    assert len(features) == 68
    old_races = pl.read_parquet(OLD / "race_predictions.parquet").filter(
        pl.col("model").is_in(protocol["references"])
    )
    old_horses = pl.read_parquet(OLD / "horse_predictions.parquet").filter(
        pl.col("model").is_in(protocol["references"])
    )
    predictions = old_races.to_dicts()
    horses = old_horses.to_dicts()
    dimensions = []
    for fold in sorted(folds["fold_id"].unique().to_list()):
        split = folds.filter(pl.col("fold_id") == fold)
        parts = {
            role: frame.join(
                split.filter(pl.col("role") == role).select("race_id"), on="race_id", how="semi"
            ).sort("race_id", "horse_id")
            for role in ["fit", "tune", "calibration", "evaluation"]
        }
        dates = {k: (v["event_date"].min(), v["event_date"].max()) for k, v in parts.items()}
        for left, right in [
            ("fit", "tune"),
            ("tune", "calibration"),
            ("calibration", "evaluation"),
        ]:
            assert dates[left][1] < dates[right][0]
            assert not set(parts[left]["race_id"]) & set(parts[right]["race_id"])
        assert parts["evaluation"]["event_date"].dt.year().unique().to_list() == [2025]
        pre = FitPreprocessor().fit(parts["fit"], features)
        xs = {k: pre.transform(v) for k, v in parts.items()}
        groups = {k: race_groups(v, truth) for k, v in parts.items()}
        sizes = {k: [hi - lo for lo, hi, _ in g] for k, g in groups.items()}
        orders = {k: [o for _, _, o in g] for k, g in groups.items()}
        dimensions.append(
            dict(
                fold=fold,
                features=features,
                input_names=pre.names,
                input_dimensions=len(pre.names),
                dates=dates,
                race_counts={k: len(v) for k, v in groups.items()},
            )
        )
        save("feature_dimensions.json", dimensions)
        cal_layout = build_layout(sizes["calibration"], orders["calibration"])
        for name, weight in protocol["candidates"].items():
            models = []
            for seed in protocol["seeds"]:
                event = dict(
                    fold=fold,
                    model=name,
                    seed=seed,
                    status="started",
                    fit_races=len(groups["fit"]),
                    tune_races=len(groups["tune"]),
                )
                ledger["estimator_fits"].append(event)
                flush()
                print(f"{fold} {name} seed{seed} FIT started", flush=True)
                model = JointTop3MLP(**protocol["params"])
                model.fit(
                    xs["fit"],
                    sizes["fit"],
                    orders["fit"],
                    tune=(xs["tune"], sizes["tune"], orders["tune"]),
                    seed=seed,
                    joint_weight=weight,
                )
                event.update(
                    status="complete",
                    diagnostics={
                        k: v
                        for k, v in vars(model).items()
                        if k.endswith("_") and isinstance(v, (str, int, float, bool, type(None)))
                    },
                )
                models.append(model)
                flush()
                print(f"{fold} {name} seed{seed} FIT complete {event['diagnostics']}", flush=True)
            raw = {
                k: np.mean([m.predict(x) for m in models], axis=0)
                for k, x in xs.items()
                if k in ["calibration", "evaluation"]
            }
            event = dict(
                fold=fold,
                model=name,
                type="joint_two_temperature",
                partition="calibration",
                status="started",
            )
            ledger["calibration_fits"].append(event)
            flush()

            def objective(log_betas, raw=raw, cal_layout=cal_layout, model=models[0]):
                scaled = raw["calibration"] * np.exp(log_betas)
                loss, grad = model.scores_loss_and_gradient(scaled, cal_layout, joint_weight=1.0)
                return loss, np.sum(grad * scaled, axis=0)

            opt = minimize(
                objective,
                np.zeros(2),
                jac=True,
                method="L-BFGS-B",
                bounds=[(-4.0, 4.0), (-4.0, 4.0)],
                options={"maxiter": 100, "ftol": 1e-10},
            )
            assert opt.success, str(opt.message)
            betas = np.exp(opt.x)
            event.update(
                status="complete",
                betas=betas.tolist(),
                loss=float(opt.fun),
                iterations=int(opt.nit),
                message=str(opt.message),
                at_boundary=bool(np.any(np.abs(opt.x) > 3.999)),
            )
            flush()
            bundle = dict(
                model_name=name,
                fold=fold,
                models=models,
                preprocessor=pre,
                features=features,
                betas=betas,
                joint_weight=weight,
            )
            with (OUT / "bundles" / f"{fold}__{name}.pkl").open("wb") as f:
                pickle.dump(bundle, f)
            for lo, hi, _ in groups["evaluation"]:
                race = parts["evaluation"].slice(lo, hi - lo)
                rid = int(race["race_id"][0])
                ids = race["horse_id"].to_list()
                official = race.filter(pl.col("label_top3") == 1)["horse_id"].to_list()
                metrics = evaluate_joint_race(
                    ids,
                    raw["evaluation"][lo:hi, 0],
                    raw["evaluation"][lo:hi, 1],
                    truth[rid],
                    official,
                    beta_set=float(betas[0]),
                    beta_order=float(betas[1]),
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
                            inclusion_score=float(raw["evaluation"][lo + i, 0]),
                            order_score=float(raw["evaluation"][lo + i, 1]),
                            beta_set=float(betas[0]),
                            beta_order=float(betas[1]),
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
            print(f"{fold} {name} CAL/EVAL saved", flush=True)
    expected = set(frame.filter(pl.col("event_date").dt.year() == 2025)["race_id"])
    p = pl.DataFrame(predictions, infer_schema_length=None)
    assert len(expected) == 715 and len(p) == 5 * 715
    for name in protocol["references"] + list(protocol["candidates"]):
        assert set(p.filter(pl.col("model") == name)["race_id"]) == expected
    assert len(ledger["estimator_fits"]) == 16 and len(ledger["calibration_fits"]) == 8
    ledger.update(
        status="complete",
        completed_at=datetime.now(UTC).isoformat(),
        common_races=715,
        new_bundles=8,
        evaluated_race_ids=sorted(expected),
    )
    flush()
    save(
        "environment.json",
        dict(python=platform.python_version(), numpy=np.__version__, platform=platform.platform()),
    )
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
