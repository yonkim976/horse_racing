"""Bounded trial-detail feature experiment with frozen conditional order heads."""

import json
import pickle
from datetime import UTC, datetime

import lightgbm as lgb
import numpy as np
import polars as pl
from scipy.optimize import minimize_scalar

from horse_racing.analysis.jeju_hybrid_evaluation import evaluate_hybrid_race
from horse_racing.analysis.jeju_place_probability import evaluate_place_race
from horse_racing.analysis.jeju_top3_evaluation import evaluate_race
from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor
from scripts.freeze_jeju_trial_protocol import OUT, ROOT, TRIAL, V5, V9, sha
from scripts.run_jeju_context_experiment import data_frame as base_frame
from scripts.run_jeju_context_experiment import order_scores, rank_scores
from scripts.run_jeju_top3_experiment import order_loss, race_groups


def save(name, obj):
    (OUT / name).write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n"
    )


def data_frame(protocol):
    frame, meta, truth, folds = base_frame(protocol)
    return (
        frame.join(pl.read_parquet(TRIAL / "features.parquet"), on="entry_id", validate="1:1"),
        meta,
        truth,
        folds,
    )


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    assert not (OUT / "run_ledger.json").exists(), "Refuse overwrite"
    for folder, digest in protocol["parents"].items():
        assert sha(ROOT / folder / "manifest.json") == digest
    (OUT / "bundles").mkdir()
    ledger = dict(
        status="running",
        started_at=datetime.now(UTC).isoformat(),
        protocol_sha256=sha(OUT / "protocol.json"),
        estimator_fits=[],
        calibration_fits=[],
        reference_refits=0,
        order_refits=0,
        order_recalibrations=0,
    )

    def flush():
        save("run_ledger.json", ledger)

    flush()
    frame, meta, truth, folds = data_frame(protocol)
    predictions = []
    horses = []
    for folder, names in [(V5, ["R_FORM", "HY_R_FORM"]), (V9, ["C_EXPERIENCE_FIXED"])]:
        predictions.extend(
            pl.read_parquet(folder / "race_predictions.parquet")
            .filter(pl.col("model").is_in(names))
            .to_dicts()
        )
        horses.extend(
            pl.read_parquet(folder / "horse_predictions.parquet")
            .filter(pl.col("model").is_in(names))
            .to_dicts()
        )
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
        with (V5 / "bundles" / f"{fold}__HY_R_FORM.pkl").open("rb") as f:
            parent = pickle.load(f)
        ob = parent["order_bundle"]
        order_raw = order_scores(ob, parts["evaluation"])
        for name, rank_parent in protocol["hybrids"].items():
            rb = rank_bundles[rank_parent]
            bundle = dict(
                kind="hybrid",
                model_name=name,
                fold=fold,
                rank_bundle=rb,
                order_bundle=ob,
                beta_order=parent["beta_order"],
                set_parent=rank_parent,
            )
            with (OUT / "bundles" / f"{fold}__{name}.pkl").open("wb") as f:
                pickle.dump(bundle, f)
            evaluate(
                name,
                fold,
                parts["evaluation"],
                rank_scores(rb, parts["evaluation"]),
                rb["beta"],
                order_raw,
                parent["beta_order"],
            )
    assert len(predictions) == 7 * 715 and len(horses) == 7 * 6953
    assert len(ledger["estimator_fits"]) == 16 and len(ledger["calibration_fits"]) == 8
    ledger.update(
        status="complete",
        completed_at=datetime.now(UTC).isoformat(),
        models=7,
        new_bundles=16,
        common_races=715,
        predictions_2026=0,
    )
    flush()
    print("COMPLETE", flush=True)


if __name__ == "__main__":
    main()
