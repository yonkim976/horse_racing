"""Fit fixed2025 models, freeze2026 scores, then evaluate once."""

import json
import pickle
from datetime import UTC, datetime

import lightgbm as lgb
import numpy as np
import polars as pl
from scipy.optimize import minimize_scalar

from horse_racing.analysis.jeju_hybrid_evaluation import (
    accepted_layout,
    conditional_calibration_loss,
    evaluate_hybrid_race,
)
from horse_racing.analysis.jeju_joint_top3 import JointTop3MLP
from horse_racing.analysis.jeju_place_probability import evaluate_place_race
from horse_racing.analysis.jeju_top3_evaluation import evaluate_race
from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor
from scripts.freeze_jeju_transition_protocol import DATA, FEAT, H3, OUT, ROOT, sha
from scripts.run_jeju_context_experiment import order_scores, rank_scores
from scripts.run_jeju_top3_experiment import order_loss, race_groups


def save(name, obj):
    (OUT / name).write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n"
    )


def data_frame():
    states = pl.read_parquet(DATA / "horse_states.parquet")
    h3 = pl.read_parquet(H3 / "features.parquet")
    frame = states.join(
        h3.select("entry_id", *[c for c in h3.columns if c not in states.columns]),
        on="entry_id",
        validate="1:1",
    )
    frame = frame.join(
        pl.read_parquet(FEAT / "context_features.parquet"), on="entry_id", validate="1:1"
    ).join(pl.read_parquet(FEAT / "features.parquet"), on="entry_id", validate="1:1")
    # 2026 labels are deliberately absent from this model-facing frame.
    labels = pl.read_parquet(DATA / "labels.parquet").filter(pl.col("event_date").dt.year() <= 2025)
    frame = frame.join(
        labels.select("entry_id", "label_top3", "finish_position"),
        on="entry_id",
        how="left",
        validate="1:1",
    )
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
        pl.col("fold_id") == "frozen_2026"
    )
    return frame, truth, folds


def score_frozen():
    lock = json.loads((OUT / "prediction_lock.json").read_text())
    for file, digest in lock["files"].items():
        assert sha(OUT / file) == digest, file
    assert not (OUT / "race_predictions.parquet").exists(), "No second evaluation"
    raw = pl.read_parquet(OUT / "frozen_scores.parquet")
    labels = pl.read_parquet(DATA / "labels.parquet").filter(pl.col("event_date").dt.year() == 2026)
    official = {}
    for r in labels.filter(pl.col("label_top3") == 1).iter_rows(named=True):
        official.setdefault(r["race_id"], []).append(r["horse_id"])
    truth = {}
    for r in (
        pl.read_parquet(DATA / "accepted_orders.parquet")
        .filter(pl.col("event_date").dt.year() == 2026)
        .iter_rows(named=True)
    ):
        truth.setdefault(r["race_id"], []).append(
            (r["first_horse_id"], r["second_horse_id"], r["third_horse_id"])
        )
    meta = {
        r["race_id"]: r
        for r in pl.read_parquet(DATA / "races.parquet")
        .filter(pl.col("event_date").dt.year() == 2026)
        .iter_rows(named=True)
    }
    races = []
    horses = []
    for (name, rid), part in raw.partition_by(["model", "race_id"], as_dict=True).items():
        part = part.sort("horse_id")
        r = part.row(0, named=True)
        ids = part["horse_id"].to_list()
        scores = part["score"].to_numpy()
        if name.startswith("HY_"):
            metrics = evaluate_hybrid_race(
                ids,
                scores,
                part["order_score"].to_numpy(),
                truth[rid],
                official[rid],
                beta_set=r["beta"],
                beta_order=r["beta_order"],
            )
        else:
            metrics = {
                **evaluate_place_race(ids, scores, official[rid], beta=r["beta"]),
                **evaluate_race(ids, scores, truth[rid], beta=r["beta"]),
            }
        marginal = metrics.pop("pl_marginals")
        ys = metrics.pop("official_labels")
        row = dict(
            model=name,
            fold="frozen_2026",
            race_id=rid,
            event_date=r["event_date"],
            distance_m=r["distance_m"],
            field_size=len(part),
            boundary_tie=meta[rid]["boundary_tie"],
            podium_tie=meta[rid]["podium_tie"],
            **metrics,
        )
        races.append(row)
        for i, horse in enumerate(ids):
            item = part.row(i, named=True)
            horses.append(
                item
                | dict(
                    pl_place_probability=float(marginal[i]),
                    official_top3=int(ys[i]),
                    boundary_tie=row["boundary_tie"],
                    selected=horse == row["pick_horse_id"],
                )
            )
    pl.DataFrame(races, infer_schema_length=None).write_parquet(OUT / "race_predictions.parquet")
    pl.DataFrame(horses, infer_schema_length=None).write_parquet(OUT / "horse_predictions.parquet")
    save(
        "evaluation_release.json",
        dict(
            evaluated_at=datetime.now(UTC).isoformat(),
            lock_sha256=sha(OUT / "prediction_lock.json"),
            races=510,
            models=6,
            reuse_as_untouched_allowed=False,
        ),
    )


def main():
    p = json.loads((OUT / "protocol.json").read_text())
    assert not (OUT / "run_ledger.json").exists(), "Refuse refit"
    for folder, digest in p["parents"].items():
        assert sha(ROOT / folder / "manifest.json") == digest
    (OUT / "bundles").mkdir()
    frame, truth, folds = data_frame()
    parts = {
        role: frame.join(
            folds.filter(pl.col("role") == role).select("race_id"), on="race_id", how="semi"
        ).sort("race_id", "horse_id")
        for role in ["fit", "tune", "calibration", "evaluation"]
    }
    for left, right in [("fit", "tune"), ("tune", "calibration"), ("calibration", "evaluation")]:
        assert parts[left]["event_date"].max() < parts[right]["event_date"].min()
    assert parts["evaluation"]["label_top3"].null_count() == len(parts["evaluation"]) == 4852
    assert parts["evaluation"]["race_id"].n_unique() == 510
    groups = {
        role: race_groups(part, truth) for role, part in parts.items() if role != "evaluation"
    }
    ledger = dict(
        status="running",
        started_at=datetime.now(UTC).isoformat(),
        protocol_sha256=sha(OUT / "protocol.json"),
        feature_manifest_sha256=sha(FEAT / "manifest.json"),
        estimator_fits=[],
        calibration_fits=[],
        evaluation_fits=0,
    )
    dimensions = []
    bundles = {}
    raw = {}

    def flush():
        save("run_ledger.json", ledger)

    flush()
    for name, features in p["rank_candidates"].items():
        pre = FitPreprocessor().fit(parts["fit"], features)
        xs = {role: pre.transform(part) for role, part in parts.items()}
        dimensions.append(
            dict(
                model=name,
                features=features,
                input_names=pre.names,
                input_dimensions=len(pre.names),
            )
        )
        models = []
        ys = {
            role: np.where(
                np.isfinite(part["finish_position"].to_numpy().astype(float))
                & (part["finish_position"].to_numpy().astype(float) <= 3),
                4 - part["finish_position"].to_numpy().astype(float),
                0,
            ).astype(int)
            for role, part in parts.items()
            if role in ["fit", "tune"]
        }
        for seed in p["seeds"]:
            event = dict(model=name, seed=seed, status="started")
            ledger["estimator_fits"].append(event)
            flush()
            model = lgb.LGBMRanker(
                objective="lambdarank",
                label_gain=[0, 1, 3, 7],
                random_state=seed,
                verbosity=-1,
                **p["rank_params"],
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
            print(name, seed, "complete", flush=True)
        bundle = dict(
            kind="ranker",
            model_name=name,
            fold="frozen_2026",
            features=features,
            preprocessor=pre,
            models=models,
        )
        raws = {role: rank_scores(bundle, parts[role]) for role in ["calibration", "evaluation"]}
        opt = minimize_scalar(
            lambda x, raws=raws: order_loss(raws["calibration"], groups["calibration"], np.exp(x)),
            bounds=(-4, 4),
            method="bounded",
            options={"xatol": 1e-5},
        )
        assert opt.success
        bundle["beta"] = float(np.exp(opt.x))
        bundles[name] = bundle
        raw[name] = raws
        ledger["calibration_fits"].append(
            dict(
                model=name,
                partition="calibration",
                status="complete",
                beta=bundle["beta"],
                objective=float(opt.fun),
            )
        )
        flush()
        with (OUT / "bundles" / f"frozen_2026__{name}.pkl").open("wb") as f:
            pickle.dump(bundle, f)
    pre = FitPreprocessor().fit(parts["fit"], p["order_features"])
    xs = {k: pre.transform(v) for k, v in parts.items()}
    sizes = {k: [hi - lo for lo, hi, _ in g] for k, g in groups.items()}
    orders = {k: [o for _, _, o in g] for k, g in groups.items()}
    models = []
    for seed in p["seeds"]:
        event = dict(model="O_BASE", seed=seed, status="started")
        ledger["estimator_fits"].append(event)
        flush()
        model = JointTop3MLP(**p["order_params"])
        model.fit(
            xs["fit"],
            sizes["fit"],
            orders["fit"],
            tune=(xs["tune"], sizes["tune"], orders["tune"]),
            seed=seed,
            joint_weight=p["joint_weight"],
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
        print("O_BASE", seed, "complete", flush=True)
    ob = dict(
        kind="joint_order",
        model_name="O_BASE",
        fold="frozen_2026",
        features=p["order_features"],
        preprocessor=pre,
        models=models,
        joint_weight=1.0,
    )
    oraw = {k: order_scores(ob, parts[k]) for k in ["calibration", "evaluation"]}
    layouts = []
    for lo, hi, _ in groups["calibration"]:
        race = parts["calibration"].slice(lo, hi - lo)
        rid = int(race["race_id"][0])
        layouts.append(
            accepted_layout(
                race["horse_id"].to_list(),
                raw["R_FORM"]["calibration"][lo:hi],
                oraw["calibration"][lo:hi],
                truth[rid],
                bundles["R_FORM"]["beta"],
            )
        )
    opt = minimize_scalar(
        lambda x: conditional_calibration_loss(x, layouts),
        bounds=(-4, 4),
        method="bounded",
        options={"xatol": 1e-5},
    )
    assert opt.success
    order_beta = float(np.exp(opt.x))
    ob["beta_order"] = order_beta
    ledger["calibration_fits"].append(
        dict(
            model="O_BASE",
            partition="calibration",
            status="complete",
            beta_order=order_beta,
            objective=float(opt.fun),
        )
    )
    flush()
    with (OUT / "bundles/frozen_2026__O_BASE.pkl").open("wb") as f:
        pickle.dump(ob, f)
    for name, parent in p["hybrids"].items():
        bundle = dict(
            kind="hybrid",
            model_name=name,
            fold="frozen_2026",
            rank_bundle=bundles[parent],
            order_bundle=ob,
            beta_order=order_beta,
            set_parent=parent,
        )
        with (OUT / "bundles" / f"frozen_2026__{name}.pkl").open("wb") as f:
            pickle.dump(bundle, f)
    scores = []
    for name in list(p["rank_candidates"]) + list(p["hybrids"]):
        parent = p["hybrids"].get(name, name)
        hybrid = name in p["hybrids"]
        for i, r in enumerate(
            parts["evaluation"]
            .select("entry_id", "race_id", "horse_id", "event_date", "distance_m")
            .iter_rows(named=True)
        ):
            scores.append(
                dict(
                    **{**r, "event_date": str(r["event_date"])},
                    model=name,
                    score=float(raw[parent]["evaluation"][i]),
                    beta=bundles[parent]["beta"],
                    order_score=float(oraw["evaluation"][i]) if hybrid else None,
                    beta_order=order_beta if hybrid else None,
                )
            )
    pl.DataFrame(scores, infer_schema_length=None).write_parquet(OUT / "frozen_scores.parquet")
    save("feature_dimensions.json", dimensions)
    save(
        "split_dates.json",
        {
            k: dict(
                min=str(v["event_date"].min()),
                max=str(v["event_date"].max()),
                races=v["race_id"].n_unique(),
                entries=len(v),
            )
            for k, v in parts.items()
        },
    )
    files = [OUT / "frozen_scores.parquet", OUT / "protocol.json", *(OUT / "bundles").glob("*.pkl")]
    save(
        "prediction_lock.json",
        dict(
            frozen_at=datetime.now(UTC).isoformat(),
            feature_manifest_sha256=sha(FEAT / "manifest.json"),
            files={str(f.relative_to(OUT)): sha(f) for f in files},
            no_2026_labels_in_model_frame=True,
        ),
    )
    ledger.update(status="predictions_frozen")
    flush()
    score_frozen()
    ledger.update(
        status="complete",
        completed_at=datetime.now(UTC).isoformat(),
        evaluation_races=510,
        predictions_2026=510,
        models=6,
    )
    flush()
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
