"""Fixed experience/section calibration audit and frozen-versus-reselected policy test."""

import json
import pickle
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl

from horse_racing.analysis.jeju_experience_calibration import (
    OFFSET_NAMES,
    ExperienceSetCalibrator,
    evaluate_policy,
    experience_design,
)
from horse_racing.analysis.jeju_hybrid_evaluation import distribution as baseline_distribution
from horse_racing.analysis.jeju_joint_top3 import build_layout
from scripts.run_jeju_context_experiment import order_scores, rank_scores
from scripts.run_jeju_set_interaction import (
    PARENTS as OLD_PARENTS,
)
from scripts.run_jeju_set_interaction import (
    ROOT,
    V5,
    load_frame,
    sha,
)
from scripts.run_jeju_top3_experiment import race_groups

V8 = ROOT / "data/research/jeju_native_set_interaction_v8_20260916"
OUT = ROOT / "data/research/jeju_native_experience_calibration_v9_20260916"
PARENTS = [*OLD_PARENTS, V8]


def save(name, value):
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n"
    )


def design(frame):
    return experience_design(
        frame["distance_starts_pre"].to_numpy(),
        frame["historical_early_front_rate"].to_numpy(),
        frame["closing_speed_quality_mean_3"].to_numpy(),
    )


def prepare(frame, truth, parent):
    groups = race_groups(frame, truth)
    layout = build_layout([hi - lo for lo, hi, _ in groups], [o for _, _, o in groups])
    raw = rank_scores(parent["rank_bundle"], frame)
    order = order_scores(parent["order_bundle"], frame)
    base = []
    for lo, hi, _ in groups:
        base.append(
            baseline_distribution(
                raw[lo:hi], order[lo:hi], parent["rank_bundle"]["beta"], parent["beta_order"]
            )[2]
        )
    x, _, _ = design(frame)
    return np.concatenate(base), x[layout.set_indices].sum(axis=1), layout, order, groups


def freeze():
    OUT.mkdir(exist_ok=True)
    assert not (OUT / "protocol.json").exists()
    save(
        "protocol.json",
        dict(
            version="experience_calibration_v9",
            created_at=datetime.now(UTC).isoformat(),
            parent_manifests={p.name: sha(p / "manifest.json") for p in PARENTS},
            references=["HY_R_FORM"],
            calibrators={"C_GLOBAL": False, "C_EXPERIENCE": True},
            policies={
                "C_GLOBAL_FIXED": ["C_GLOBAL", "fixed"],
                "C_EXPERIENCE_FIXED": ["C_EXPERIENCE", "fixed"],
                "C_EXPERIENCE_SELECT": ["C_EXPERIENCE", "select"],
            },
            offset_names=OFFSET_NAMES,
            params=dict(l2=0.01, max_iter=150),
            experience_bins=["0", "1-2", "3-5", "6+", "unknown"],
            section_missing="Nonfinite historical_early_front_rate or closing_speed_quality_mean_3.",  # noqa: E501
            probability_bins=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
            audit_min_entries=100,
            audit_min_days=10,
            counts=dict(calibration_fits=8, bundles=8, base_refits=0),
            objective="CAL nonboundary races only; equal race weight, within-race mean binary "
            "logloss of coherent top3 marginals; L2 .01 all parameters towards identity. "
            "No TUNE/EVAL fitting, no group-only training or sign constraints.",
            model="log set weight = exp(log_scale)*frozen base log set probability + sum of "
            "horse group offsets. log_scale and offsets bounded[-2,2]. 6+ complete reference. "
            "Global has only scale; experience has scale plus five offsets. Softmax all sets.",
            base="Frozen HY_R_FORM includes its original CAL temperature. New calibrators use same "
            "CAL partition, not a new independent sample. Frozen order head and temperature.",
            policy="FIXED retains original actions, updates probabilities and confidence. "
            "SELECT uses same experience probabilities, largest marginal pick, MAP set then "
            "MAP within-set order. Both probability errors identical, actions may differ.",
            comparisons=[
                ["C_GLOBAL_FIXED", "HY_R_FORM"],
                ["C_EXPERIENCE_FIXED", "C_GLOBAL_FIXED"],
                ["C_EXPERIENCE_FIXED", "HY_R_FORM"],
                ["C_EXPERIENCE_SELECT", "HY_R_FORM"],
                ["C_EXPERIENCE_SELECT", "C_EXPERIENCE_FIXED"],
            ],
            audit="All 709 nonboundary EVAL races; all entrants and fixed baseline-picked horses "
            "separately; distance bins, section status and cross cells. Entry-weighted bias "
            "mean(p-y), Brier/logloss and fixed confidence bins. Day-cluster bootstrap5000 "
            "seed17 ratio of summed residual to entries. Positive bias=overprediction. "
            "Report counts, sparse cells, exploratory unadjusted95% intervals; no causal claim.",
            decision="Calibration candidate only if day95% upper bound of Brier difference "
            "vs HY_R_FORM<0 and logloss point not worse. Reselection candidate only if "
            "day95% lower bound of set-hit difference>0 and pick/order point not worse. "
            "Otherwise retain reference; no post-EVAL added fits or rules.",
            metrics="715 races hits/set/orderNLL,709 nonboundary probability errors,98days2025. "
            "5000 paired race/day bootstrap seed17. Repeated development, not independent test.",
            limits="T-2 historical features; actual starters; retrospective cards with unproven "
            "publication/revision times. No2026 outcomes/inference. Diagnostic hypothesis "
            "came from v8 selected error cases; current audit uses full fixed population.",
        ),
    )


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    assert not (OUT / "run_ledger.json").exists()
    for p in PARENTS:
        assert sha(p / "manifest.json") == protocol["parent_manifests"][p.name]
    for sub in ["bundles", "reproduce"]:
        (OUT / sub).mkdir(exist_ok=True)
    for source in [
        Path(__file__),
        ROOT / "scripts/report_jeju_experience_calibration.py",
        ROOT / "scripts/audit_jeju_experience_calibration.py",
        ROOT / "scripts/verify_jeju_experience_calibration.py",
        ROOT / "src/horse_racing/analysis/jeju_experience_calibration.py",
        ROOT / "tests/test_jeju_experience_calibration.py",
        ROOT / "pyproject.toml",
    ]:
        shutil.copy2(source, OUT / "reproduce" / source.name)
    ledger = dict(
        status="running",
        started_at=datetime.now(UTC).isoformat(),
        protocol_sha256=sha(OUT / "protocol.json"),
        base_refits=0,
        calibration_fits=[],
    )
    save("run_ledger.json", ledger)
    frame, meta, truth, folds = load_frame()
    prior = pl.read_parquet(V8 / "race_predictions.parquet").filter(pl.col("model") == "HY_R_FORM")
    oldh = pl.read_parquet(V8 / "horse_predictions.parquet").filter(pl.col("model") == "HY_R_FORM")
    predictions, horses = prior.to_dicts(), oldh.to_dicts()
    reference = {r["race_id"]: r for r in predictions}
    context = frame.filter(pl.col("event_date").dt.year() == 2025).sort("race_id", "horse_id")
    x, bins, missing = design(context)
    context.select(
        "entry_id",
        "race_id",
        "horse_id",
        "event_date",
        "distance_starts_pre",
        "historical_early_front_rate",
        "closing_speed_quality_mean_3",
    ).with_columns(
        pl.Series("experience_bin", bins), pl.Series("section_missing", missing)
    ).write_parquet(OUT / "audit_context.parquet")
    for fold in sorted(folds["fold_id"].unique()):
        split = folds.filter(pl.col("fold_id") == fold)
        parts = {
            role: frame.join(
                split.filter(pl.col("role") == role).select("race_id"), on="race_id", how="semi"
            ).sort("race_id", "horse_id")
            for role in ["calibration", "evaluation"]
        }
        assert parts["calibration"]["event_date"].max() < parts["evaluation"]["event_date"].min()
        good = [
            rid for rid in parts["calibration"]["race_id"].unique() if not meta[rid]["boundary_tie"]
        ]
        cal = parts["calibration"].filter(pl.col("race_id").is_in(good))
        ev = parts["evaluation"]
        parent = pickle.loads((V5 / "bundles" / f"{fold}__HY_R_FORM.pkl").read_bytes())
        base, z, layout, _, _ = prepare(cal, truth, parent)
        eb, ez, el, order, groups = prepare(ev, truth, parent)
        labels = cal["label_top3"].to_numpy()
        fitted = {}
        for name, grouped in protocol["calibrators"].items():
            event = dict(
                model=name,
                fold=fold,
                status="started",
                partition="calibration",
                races=layout.n_races,
                entries=len(cal),
                excluded_boundary_races=int(
                    parts["calibration"]["race_id"].n_unique() - layout.n_races
                ),
            )
            ledger["calibration_fits"].append(event)
            save("run_ledger.json", ledger)
            model = ExperienceSetCalibrator(grouped=grouped, **protocol["params"]).fit(
                base, z, layout, labels
            )
            assert model.success_, model.message_
            bundle = dict(model_name=name, fold=fold, calibrator=model, parent=parent)
            fitted[name] = bundle
            event.update(
                status="complete",
                parameters=model.theta_.tolist(),
                objective=model.objective_,
                iterations=model.n_iter_,
                at_boundary=model.at_boundary_,
                success=model.success_,
                message=model.message_,
            )
            save("run_ledger.json", ledger)
            with (OUT / "bundles" / f"{fold}__{name}.pkl").open("wb") as f:
                pickle.dump(bundle, f)
            print(f"{fold} {name} complete {model.n_iter_} iterations", flush=True)
        for name, (calibrator, policy) in protocol["policies"].items():
            logits = fitted[calibrator]["calibrator"].predict_logits(eb, ez)
            for j, (lo, hi, _) in enumerate(groups):
                race = ev.slice(lo, hi - lo)
                rid = int(race["race_id"][0])
                ids = race["horse_id"].to_list()
                official = race.filter(pl.col("label_top3") == 1)["horse_id"].to_list()
                metrics = evaluate_policy(
                    ids,
                    logits[el.set_starts[j] : el.set_ends[j]],
                    order[lo:hi],
                    truth[rid],
                    official,
                    parent["beta_order"],
                    fixed=reference[rid] if policy == "fixed" else None,
                )
                marg = metrics.pop("pl_marginals")
                ys = metrics.pop("official_labels")
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
                            score=None,
                            beta=None,
                            order_score=float(order[lo + i]),
                            beta_set=None,
                            beta_order=parent["beta_order"],
                            pl_place_probability=float(marg[i]),
                            official_top3=int(ys[i]),
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
    ledger.update(status="complete", completed_at=datetime.now(UTC).isoformat())
    save("run_ledger.json", ledger)


if __name__ == "__main__":
    import sys

    freeze() if "--freeze" in sys.argv else main()
