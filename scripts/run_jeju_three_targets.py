"""Compare one-horse place, complete set, and exact order on frozen dev folds."""

from __future__ import annotations

import hashlib
import json
import pickle
import shutil
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl
from scipy.optimize import minimize_scalar

from horse_racing.analysis.jeju_place_calibration import PositivePlattCalibrator
from horse_racing.analysis.jeju_place_probability import evaluate_place_race
from horse_racing.analysis.jeju_top3_evaluation import evaluate_race
from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor
from scripts.run_jeju_top3_experiment import order_loss, race_groups

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/jeju_native_three_targets_v2_20260915"
OLD = ROOT / "data/research/jeju_native_top3_experiment_v1_20260915"
DATA = ROOT / "data/research/jeju_native_top3_dataset_v1_20260915_r2"


def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n")


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    assert sha(DATA / "manifest.json") == protocol["dataset_manifest_sha256"]
    assert sha(OLD / "manifest.json") == protocol["parent_manifest_sha256"]
    assert not (OUT / "run_ledger.json").exists(), "Never overwrite an existing experiment"
    for d in ["reproduce", "bundles"]:
        (OUT / d).mkdir(exist_ok=True)
    for path in [
        Path(__file__),
        ROOT / "scripts/run_jeju_top3_experiment.py",
        ROOT / "src/horse_racing/analysis/jeju_place_calibration.py",
        ROOT / "src/horse_racing/analysis/jeju_place_probability.py",
        ROOT / "src/horse_racing/analysis/jeju_top3_preprocessing.py",
        ROOT / "src/horse_racing/analysis/jeju_top3_evaluation.py",
        ROOT / "tests/test_jeju_place_calibration.py",
        ROOT / "tests/test_jeju_place_probability.py",
        ROOT / "pyproject.toml",
        ROOT / "docs/JEJU_NATIVE_THREE_TARGETS_PLAN_2026-09-15.md",
    ]:
        shutil.copy2(path, OUT / "reproduce" / path.name)
    ledger = {
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "protocol_sha256": sha(OUT / "protocol.json"),
        "estimator_fits": [],
        "calibration_fits": [],
        "evaluation_year": 2025,
        "reference_refits": 0,
    }

    def flush():
        save("run_ledger.json", ledger)

    flush()
    entries = pl.read_parquet(DATA / "entries.parquet").filter(
        pl.col("event_date").dt.year() <= 2025
    )
    states = pl.read_parquet(DATA / "horse_states.parquet").join(
        entries.select("entry_id"), on="entry_id", how="semi"
    )
    labels = pl.read_parquet(DATA / "labels.parquet").join(
        entries.select("entry_id"), on="entry_id", how="semi"
    )
    frame = states.join(
        labels.select("entry_id", "label_top3"), on="entry_id", validate="1:1"
    ).sort("race_id", "horse_id")
    race_meta = {
        r["race_id"]: r
        for r in pl.read_parquet(DATA / "races.parquet")
        .filter(pl.col("event_date").dt.year() <= 2025)
        .iter_rows(named=True)
    }
    truth = {}
    for r in (
        pl.read_parquet(DATA / "accepted_orders.parquet")
        .filter(pl.col("event_date").dt.year() <= 2025)
        .iter_rows(named=True)
    ):
        truth.setdefault(r["race_id"], []).append(
            (r["first_horse_id"], r["second_horse_id"], r["third_horse_id"])
        )
    folds = pl.read_parquet(DATA / "fold_assignments.parquet").filter(
        pl.col("fold_id").str.starts_with("dev_2025")
    )
    registry = json.loads((DATA / "feature_registry.json").read_text())
    predictions, horse_predictions = [], []

    def evaluate(model, fold, ev, scores, beta, native=None):
        for lo, hi, _ in race_groups(ev, truth):
            race = ev.slice(lo, hi - lo)
            rid = int(race["race_id"][0])
            ids = race["horse_id"].to_list()
            official = race.filter(pl.col("label_top3") == 1)["horse_id"].to_list()
            metrics = evaluate_place_race(
                ids,
                scores[lo:hi],
                official,
                beta=beta,
                native_probabilities=None if native is None else native[lo:hi],
            )
            marginals = metrics.pop("pl_marginals")
            official_labels = metrics.pop("official_labels")
            row = {
                "model": model,
                "fold": fold,
                "race_id": rid,
                "event_date": str(race["event_date"][0]),
                "field_size": len(race),
                "distance_m": int(race["distance_m"][0]),
                "boundary_tie": race_meta[rid]["boundary_tie"],
                "podium_tie": race_meta[rid]["podium_tie"],
                **metrics,
                **evaluate_race(ids, scores[lo:hi], truth[rid], beta=beta),
            }
            predictions.append(row)
            for i, h in enumerate(ids):
                horse_predictions.append(
                    {
                        "model": model,
                        "fold": fold,
                        "race_id": rid,
                        "horse_id": h,
                        "event_date": row["event_date"],
                        "score": float(scores[lo + i]),
                        "beta": float(beta),
                        "pl_place_probability": float(marginals[i]),
                        "native_place_probability": None
                        if native is None
                        else float(native[lo + i]),
                        "official_top3": int(official_labels[i]),
                        "boundary_tie": row["boundary_tie"],
                        "selected": h == metrics["pick_horse_id"],
                    }
                )
        pl.DataFrame(predictions, infer_schema_length=None).write_parquet(
            OUT / "race_predictions.parquet"
        )
        pl.DataFrame(horse_predictions, infer_schema_length=None).write_parquet(
            OUT / "horse_predictions.parquet"
        )
        print(f"{fold} {model} evaluated", flush=True)

    # Fixed v1 predictions: no new fitting or selection.
    old_scores = pl.read_parquet(OLD / "horse_scores.parquet")
    for (model, fold), s in old_scores.partition_by(["model", "fold"], as_dict=True).items():
        s = s.sort("race_id", "horse_id")
        ev = frame.join(
            s.select("race_id", "horse_id"), on=["race_id", "horse_id"], how="semi"
        ).sort("race_id", "horse_id")
        assert len(s) == len(ev) and ev["event_date"].dt.year().unique().to_list() == [2025]
        evaluate(model, fold, ev, s["score"].to_numpy(), float(s["beta"][0]))
    for fold in sorted(folds["fold_id"].unique().to_list()):
        split = folds.filter(pl.col("fold_id") == fold)
        parts = {
            role: frame.join(
                split.filter(pl.col("role") == role).select("race_id"), on="race_id", how="semi"
            ).sort("race_id", "horse_id")
            for role in ["fit", "tune", "calibration", "evaluation"]
        }
        ys = {k: v["label_top3"].to_numpy() for k, v in parts.items()}
        weights = {k: 1 / v["field_size"].to_numpy().astype(float) for k, v in parts.items()}
        groups = race_groups(parts["calibration"], truth)
        for arm, prefixes in [("H0", ("H0",)), ("H1", ("H0", "H1")), ("H2", ("H0", "H1", "H2"))]:
            name = "P_" + arm
            features = [
                r["feature_name"]
                for r in registry
                if r["arm"].startswith(prefixes)
                and r["feature_name"] not in protocol["aliases_removed"]
            ]
            pre = FitPreprocessor().fit(parts["fit"], features)
            xs = {k: pre.transform(v) for k, v in parts.items()}
            models = []
            for seed in [17, 43]:
                m = lgb.LGBMClassifier(
                    objective="binary",
                    random_state=seed,
                    verbosity=-1,
                    **protocol["binary_model"]["params"],
                )
                event = {
                    "fold": fold,
                    "model": name,
                    "seed": seed,
                    "status": "started",
                    "features": pre.names,
                    "fit_races": parts["fit"]["race_id"].n_unique(),
                }
                ledger["estimator_fits"].append(event)
                flush()
                m.fit(
                    xs["fit"],
                    ys["fit"],
                    sample_weight=weights["fit"] / weights["fit"].mean(),
                    eval_set=[(xs["tune"], ys["tune"])],
                    eval_sample_weight=[weights["tune"] / weights["tune"].mean()],
                    eval_metric="binary_logloss",
                    callbacks=[lgb.early_stopping(30, verbose=False)],
                )
                event.update(status="complete", best_iteration=int(m.best_iteration_))
                flush()
                models.append(m)
            raw = {
                k: np.mean([m.predict(x, raw_score=True) for m in models], axis=0)
                for k, x in xs.items()
            }
            event = {
                "fold": fold,
                "model": name,
                "type": "native_platt",
                "partition": "calibration",
                "status": "started",
            }
            ledger["calibration_fits"].append(event)
            flush()
            nativecal = PositivePlattCalibrator().fit(
                raw["calibration"], ys["calibration"], sample_weight=weights["calibration"]
            )
            assert nativecal.success_
            event.update(status="complete")
            flush()
            event = {
                "fold": fold,
                "model": name,
                "type": "joint_PL",
                "partition": "calibration",
                "status": "started",
            }
            ledger["calibration_fits"].append(event)
            flush()
            opt = minimize_scalar(
                lambda b, raw=raw, groups=groups: order_loss(raw["calibration"], groups, np.exp(b)),
                bounds=(-4, 4),
                method="bounded",
                options={"xatol": 1e-5},
            )
            assert opt.success
            beta = float(np.exp(opt.x))
            event.update(status="complete", beta=beta, objective=float(opt.fun))
            flush()
            bundle = {
                "model_name": name,
                "fold": fold,
                "models": models,
                "preprocessor": pre,
                "native_calibrator": nativecal,
                "beta": beta,
                "features": features,
            }
            path = OUT / "bundles" / f"{fold}__{name}.pkl"
            with path.open("wb") as f:
                pickle.dump(bundle, f)
            with path.open("rb") as f:
                restored = pickle.load(f)
            x = restored["preprocessor"].transform(parts["evaluation"])
            replayed = np.mean([m.predict(x, raw_score=True) for m in restored["models"]], axis=0)
            np.testing.assert_allclose(replayed, raw["evaluation"], rtol=0, atol=1e-12)
            native = nativecal.predict(raw["evaluation"])
            np.testing.assert_allclose(
                restored["native_calibrator"].predict(replayed), native, rtol=0, atol=1e-12
            )
            evaluate(name, fold, parts["evaluation"], raw["evaluation"], beta, native)
    p = pl.DataFrame(predictions, infer_schema_length=None)
    expected = set(entries.filter(pl.col("event_date").dt.year() == 2025)["race_id"])
    assert len(expected) == 715 and p["model"].n_unique() == 12
    for model in p["model"].unique():
        part = p.filter(pl.col("model") == model)
        assert len(part) == 715 and set(part["race_id"]) == expected
    assert len(ledger["estimator_fits"]) == 24 and len(ledger["calibration_fits"]) == 24
    ledger.update(
        status="complete",
        completed_at=datetime.now(UTC).isoformat(),
        common_races=715,
        evaluated_race_ids=sorted(expected),
        new_bundles=12,
    )
    flush()
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
