"""Sealed first 2025 development experiment; no 2026 evaluation."""

from __future__ import annotations

import hashlib
import json
import pickle
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp

from horse_racing.analysis.jeju_top3_direct import DirectTop3Linear
from horse_racing.analysis.jeju_top3_evaluation import evaluate_race
from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/research/jeju_native_top3_dataset_v1_20260915_r2"
OUT = ROOT / "data/research/jeju_native_top3_experiment_v1_20260915"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def race_groups(frame, truth):
    result = []
    offset = 0
    for race in frame.partition_by("race_id", maintain_order=True):
        ids = race["horse_id"].to_list()
        local = {h: i for i, h in enumerate(ids)}
        rid = race["race_id"][0]
        orders = [tuple(local[h] for h in order) for order in truth[rid]]
        result.append((offset, offset + len(race), orders))
        offset += len(race)
    return result


def order_loss(scores, groups, beta=1.0):
    """Vectorized accepted-order likelihood; each race receives equal weight."""
    width = max(hi - lo for lo, hi, _ in groups)
    indices, masks, orders_all, owners = [], [], [], []
    for owner, (lo, hi, orders) in enumerate(groups):
        for order in orders:
            indices.append(list(range(lo, hi)) + [lo] * (width - hi + lo))
            masks.append([True] * (hi - lo) + [False] * (width - hi + lo))
            orders_all.append(order)
            owners.append(owner)
    indices = np.asarray(indices)
    logits = np.asarray(scores)[indices] * beta
    logits[~np.asarray(masks)] = -np.inf
    row = np.arange(len(indices))
    orders_all = np.asarray(orders_all)
    lp = np.zeros(len(indices))
    for place in range(3):
        chosen = orders_all[:, place]
        lp += logits[row, chosen] - logsumexp(logits, axis=1)
        logits[row, chosen] = -np.inf
    owners = np.asarray(owners)
    maximum = np.full(len(groups), -np.inf)
    np.maximum.at(maximum, owners, lp)
    sums = np.zeros(len(groups))
    np.add.at(sums, owners, np.exp(lp - maximum[owners]))
    return float(-np.mean(maximum + np.log(sums)))


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    assert digest(DATA / "manifest.json") == protocol["dataset_manifest_sha256"]
    if (OUT / "run_ledger.json").exists():
        raise RuntimeError("Existing run ledger; use a new version, never silently overwrite fits")
    OUT.mkdir(exist_ok=True, parents=True)
    (OUT / "bundles").mkdir(exist_ok=True)
    (OUT / "reproduce").mkdir(exist_ok=True)
    sources = [
        Path(__file__),
        ROOT / "src/horse_racing/analysis/jeju_top3_direct.py",
        ROOT / "src/horse_racing/analysis/jeju_top3_evaluation.py",
        ROOT / "pyproject.toml",
        ROOT / "scripts/report_jeju_top3_experiment.py",
        ROOT / "tests/test_jeju_top3_experiment.py",
        ROOT / "tests/test_jeju_top3_preprocessing.py",
        ROOT / "tests/test_jeju_top3_direct.py",
        ROOT / "tests/test_jeju_top3_evaluation.py",
        ROOT / "src/horse_racing/analysis/jeju_top3_preprocessing.py",
    ]
    for path in sources:
        shutil.copy2(path, OUT / "reproduce" / path.name)
    ledger = {
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "protocol_sha256": digest(OUT / "protocol.json"),
        "estimator_fits": [],
        "calibration_fits": [],
        "evaluated_race_ids": [],
        "evaluation_year": 2025,
        "python": sys.version,
        "lightgbm": lgb.__version__,
        "numpy": np.__version__,
        "polars": pl.__version__,
    }

    def flush():
        save_json(OUT / "run_ledger.json", ledger)

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
        labels.select("entry_id", "finish_position", "outcome_status"),
        on="entry_id",
        validate="1:1",
    ).sort(["race_id", "horse_id"])
    accepted = pl.read_parquet(DATA / "accepted_orders.parquet").filter(
        pl.col("event_date").dt.year() <= 2025
    )
    truth = {}
    for r in accepted.iter_rows(named=True):
        truth.setdefault(r["race_id"], []).append(
            (r["first_horse_id"], r["second_horse_id"], r["third_horse_id"])
        )
    folds = pl.read_parquet(DATA / "fold_assignments.parquet").filter(
        pl.col("fold_id").str.starts_with("dev_2025")
    )
    registry = json.loads((DATA / "feature_registry.json").read_text())
    aliases = set(protocol["aliases_removed"])
    feature_sets = {}
    for arm, prefixes in [("H0", ("H0",)), ("H1", ("H0", "H1")), ("H2", ("H0", "H1", "H2"))]:
        feature_sets[arm] = [
            r["feature_name"]
            for r in registry
            if r["arm"].startswith(prefixes) and r["feature_name"] not in aliases
        ]
    predictions, score_rows = [], []
    for fold in sorted(folds["fold_id"].unique().to_list()):
        split = folds.filter(pl.col("fold_id") == fold)
        parts = {
            role: frame.join(
                split.filter(pl.col("role") == role).select("race_id"), on="race_id", how="semi"
            ).sort(["race_id", "horse_id"])
            for role in ["fit", "tune", "calibration", "evaluation"]
        }
        groups = {role: race_groups(part, truth) for role, part in parts.items()}
        assert parts["evaluation"]["event_date"].dt.year().unique().to_list() == [2025]
        print(f"{fold}: " + ", ".join(f"{k}={len(groups[k])}" for k in groups), flush=True)

        def fit_cal_evaluate(name, scores, bundle, *, fold=fold, parts=parts, groups=groups):
            if name == "B0_uniform":
                beta = 1.0
            else:
                opt = minimize_scalar(
                    lambda b: order_loss(scores["calibration"], groups["calibration"], np.exp(b)),
                    bounds=(-4, 4),
                    method="bounded",
                    options={"xatol": 1e-5},
                )
                assert opt.success
                beta = float(np.exp(opt.x))
                ledger["calibration_fits"].append(
                    {
                        "fold": fold,
                        "model": name,
                        "beta": beta,
                        "cal_order_nll": float(opt.fun),
                        "partition": "calibration",
                        "near_boundary": abs(float(opt.x)) > 3.99,
                    }
                )
                flush()
            bundle["beta"] = beta
            bundle["fold"] = fold
            bundle["model_name"] = name
            bundle_path = OUT / "bundles" / f"{fold}__{name}.pkl"
            with bundle_path.open("wb") as f:
                pickle.dump(bundle, f)
            with bundle_path.open("rb") as f:
                restored = pickle.load(f)
            ev = parts["evaluation"]
            if "models" in restored:
                xp = restored["preprocessor"].transform(ev)
                reload_scores = np.mean([model.predict(xp) for model in restored["models"]], axis=0)
            elif name == "B0_uniform":
                reload_scores = np.zeros(len(ev))
            elif name == "B1_elo":
                reload_scores = ev["global_elo_pre"].to_numpy() * np.log(10) / 400
            else:
                a = ev["speed_residual_mean_pre"].to_numpy()
                reload_scores = -np.where(np.isfinite(a), a, restored["median"]) / 1000
            np.testing.assert_allclose(reload_scores, scores["evaluation"], rtol=0, atol=1e-12)
            for lo, hi, _ in groups["evaluation"]:
                race = ev.slice(lo, hi - lo)
                rid = int(race["race_id"][0])
                metrics = evaluate_race(
                    race["horse_id"].to_list(), scores["evaluation"][lo:hi], truth[rid], beta=beta
                )
                row = {
                    "model": name,
                    "fold": fold,
                    "race_id": rid,
                    "event_date": str(race["event_date"][0]),
                    "distance_m": int(race["distance_m"][0]),
                    "field_size": hi - lo,
                    "has_dq_dnf": any(
                        x != "normal_completed" for x in race["outcome_status"].to_list()
                    ),
                    "new_horse": bool((race["starts_pre"] == 0).any()),
                    "long_layoff": bool(
                        (race["days_since_previous_start"] >= 90).fill_null(False).any()
                    ),
                    **metrics,
                }
                predictions.append(row)
                for h, score in zip(race["horse_id"], scores["evaluation"][lo:hi], strict=True):
                    score_rows.append(
                        {
                            "model": name,
                            "fold": fold,
                            "race_id": rid,
                            "horse_id": h,
                            "score": float(score),
                            "beta": beta,
                        }
                    )
            print(f"  {name}: beta={beta:.4f}", flush=True)
            pl.DataFrame(predictions, infer_schema_length=None).write_parquet(
                OUT / "race_predictions.parquet"
            )
            pl.DataFrame(score_rows).write_parquet(OUT / "horse_scores.parquet")

        fit_cal_evaluate("B0_uniform", {k: np.zeros(len(v)) for k, v in parts.items()}, {})
        fit_cal_evaluate(
            "B1_elo",
            {k: v["global_elo_pre"].to_numpy() * np.log(10) / 400 for k, v in parts.items()},
            {},
        )
        speed_fit = parts["fit"]["speed_residual_mean_pre"].to_numpy()
        median = float(np.nanmedian(speed_fit))
        fit_cal_evaluate(
            "B2_speed",
            {
                k: -np.where(
                    np.isfinite(v["speed_residual_mean_pre"].to_numpy()),
                    v["speed_residual_mean_pre"].to_numpy(),
                    median,
                )
                / 1000
                for k, v in parts.items()
            },
            {"median": median},
        )
        for arm, features in feature_sets.items():
            pre = FitPreprocessor().fit(parts["fit"], features)
            xs = {k: pre.transform(v) for k, v in parts.items()}
            ys = {
                k: np.where(
                    np.isfinite(v["finish_position"].to_numpy())
                    & (v["finish_position"].to_numpy() <= 3),
                    4 - v["finish_position"].to_numpy(),
                    0,
                ).astype(int)
                for k, v in parts.items()
            }
            sizes = {k: [hi - lo for lo, hi, _ in g] for k, g in groups.items()}
            models = []
            for seed in [17, 43]:
                model = lgb.LGBMRanker(
                    objective="lambdarank",
                    deterministic=True,
                    force_col_wise=True,
                    n_estimators=250,
                    num_leaves=15,
                    max_depth=5,
                    learning_rate=0.04,
                    min_child_samples=50,
                    reg_lambda=5,
                    colsample_bytree=0.9,
                    subsample=0.85,
                    subsample_freq=1,
                    random_state=seed,
                    n_jobs=4,
                    verbosity=-1,
                    label_gain=[0, 1, 3, 7],
                )
                event = {
                    "fold": fold,
                    "model": "M0_" + arm,
                    "seed": seed,
                    "status": "started",
                    "features": pre.names,
                    "fit_races": len(sizes["fit"]),
                }
                ledger["estimator_fits"].append(event)
                flush()
                model.fit(
                    xs["fit"],
                    ys["fit"],
                    group=sizes["fit"],
                    eval_set=[(xs["tune"], ys["tune"])],
                    eval_group=[sizes["tune"]],
                    eval_at=[3],
                    callbacks=[lgb.early_stopping(30, verbose=False)],
                )
                event.update(status="complete", best_iteration=int(model.best_iteration_))
                flush()
                models.append(model)
            fit_cal_evaluate(
                "M0_" + arm,
                {k: np.mean([m.predict(x) for m in models], axis=0) for k, x in xs.items()},
                {"models": models, "preprocessor": pre, "features": features},
            )
            candidates = []
            for l2 in [0.01, 0.1]:
                model = DirectTop3Linear(l2=l2, max_iter=150)
                event = {
                    "fold": fold,
                    "model": "M1_" + arm,
                    "l2": l2,
                    "status": "started",
                    "features": pre.names,
                    "fit_races": len(sizes["fit"]),
                }
                ledger["estimator_fits"].append(event)
                flush()
                model.fit(xs["fit"], sizes["fit"], [orders for _, _, orders in groups["fit"]])
                loss = order_loss(model.predict(xs["tune"]), groups["tune"])
                event.update(
                    status="complete",
                    tune_order_nll=loss,
                    diagnostics={
                        "success": model.success_,
                        "iterations": model.n_iter_,
                        "objective": model.objective_,
                        "message": model.message_,
                    },
                )
                flush()
                candidates.append((loss, l2, model))
            _, chosen_l2, chosen = min(candidates, key=lambda t: (t[0], t[1]))
            fit_cal_evaluate(
                "M1_" + arm,
                {k: chosen.predict(x) for k, x in xs.items()},
                {
                    "models": [chosen],
                    "preprocessor": pre,
                    "features": features,
                    "chosen_l2": chosen_l2,
                },
            )
    expected = set(
        entries.filter(pl.col("event_date").dt.year() == 2025)["race_id"].unique().to_list()
    )
    preds = pl.DataFrame(predictions, infer_schema_length=None)
    assert len(expected) == 715
    for name in preds["model"].unique():
        sub = preds.filter(pl.col("model") == name)
        assert len(sub) == 715 and set(sub["race_id"]) == expected
    assert len(ledger["estimator_fits"]) == 48 and len(ledger["calibration_fits"]) == 32
    ledger.update(
        status="complete",
        completed_at=datetime.now(UTC).isoformat(),
        evaluated_race_ids=sorted(expected),
        common_races=len(expected),
        bundle_reload_verified=True,
    )
    flush()
    save_json(
        OUT / "manifest.json",
        {
            str(p.relative_to(OUT)): digest(p)
            for p in sorted(OUT.rglob("*"))
            if p.is_file() and p.name != "manifest.json"
        },
    )
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
