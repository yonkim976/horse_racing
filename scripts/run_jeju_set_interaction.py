"""Fixed additive versus pair/triple set experiment, 2025 development only."""

from __future__ import annotations

import json
import pickle
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import polars as pl
from scipy.optimize import minimize_scalar

from horse_racing.analysis.jeju_joint_top3 import build_layout
from horse_racing.analysis.jeju_set_interaction import (
    INTERACTION_INPUTS,
    INTERACTION_NAMES,
    SetInteractionMLP,
    evaluate_set_race,
    interaction_features,
    set_loss_gradient,
)
from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor
from scripts.run_jeju_conditional_experiment import (
    CTX,
    DATA,
    H3,
    RB,
    ROOT,
    V3,
    V4,
    V5,
    V6,
    data_frame,
    sha,
)
from scripts.run_jeju_context_experiment import order_scores
from scripts.run_jeju_top3_experiment import race_groups

V7 = ROOT / "data/research/jeju_native_conditional_order_v7_20260916"
OUT = ROOT / "data/research/jeju_native_set_interaction_v8_20260916"
PARENTS = [DATA, H3, CTX, RB, V3, V4, V5, V6, V7]


def save(name, value):
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n"
    )


def load_frame():
    return data_frame(json.loads((V7 / "protocol.json").read_text()))


def prepare(frame, truth, pre):
    groups = race_groups(frame, truth)
    sizes = [hi - lo for lo, hi, _ in groups]
    layout = build_layout(sizes, [o for _, _, o in groups])
    z = interaction_features(frame.select(INTERACTION_INPUTS).to_numpy(), sizes)
    return pre.transform(frame), z, layout, groups


def raw_sets(bundle, x, z, layout):
    if not bundle["interactions"]:
        z = z[:, :0]
    return np.mean([m.predict_sets(x, z, layout) for m in bundle["models"]], axis=0)


def freeze():
    OUT.mkdir(exist_ok=True)
    assert not (OUT / "protocol.json").exists()
    previous = json.loads((V7 / "protocol.json").read_text())
    save(
        "protocol.json",
        dict(
            version="set_interaction_v8",
            created_at=datetime.now(UTC).isoformat(),
            parent_manifests={p.name: sha(p / "manifest.json") for p in PARENTS},
            candidates={"S_ADDITIVE": False, "S_INTERACTION": True},
            references=["HY_R_FORM", "R_NO_GROWTH", "HY_C_REBOUND"],
            features=previous["order_candidates"]["O_BASE"],
            interaction_inputs=INTERACTION_INPUTS,
            interaction_names=INTERACTION_NAMES,
            params=dict(hidden_dim=16, l2=0.001, max_iter=100),
            seeds=[17, 43],
            counts=dict(estimator_fits=16, calibration_fits=8, bundles=8, reference_refits=0),
            training="All FIT races, accepted-set NLL; boundary ties summed per unique set. "
            "FIT-only imputation/scaling; TUNE set NLL checkpoint including initialization. "
            "Same unary initialization, interaction weights start zero. Average seed logits.",
            interactions="Within-race finite midranks scaled [-1,1], missing or <2 known values=0. "
            "Eight mean pair products, eight triple products, three symmetric cross pairs. "
            "No outcome or fitted statistics. Missing indicators remain in unary inputs.",
            calibration="CAL scalar positive set temperature, log bounds[-4,4]. "
            "Frozen V5 HY_R_FORM order head and order temperature, no order refit.",
            policy="Pick maximal inclusion marginal; MAP set then MAP conditional order. "
            "All entrants and all three-horse combinations; never restrict to correct old sets.",
            comparisons=[
                ["S_ADDITIVE", "HY_R_FORM"],
                ["S_INTERACTION", "S_ADDITIVE"],
                ["S_INTERACTION", "HY_R_FORM"],
                ["S_INTERACTION", "R_NO_GROWTH"],
            ],
            metrics="715 races/98 days2025; 709 nonboundary marginal errors. "
            "Paired race/day bootstrap5000 seed17, exploratory unadjusted intervals.",
            decision="No automatic promotion by best metric. Require positive set hit change with "
            "day95% lower bound>0 versus HY_R_FORM and no lower pick/order point estimates; "
            "even then research candidate pending untouched-period validation.",
            limits="2025 reused development; actual starters, publication times unproven. "
            "No2026 outcomes/inference. Posthoc missing-horse diagnostic is descriptive only. "
            "No candidates or fit retries added after EVAL.",
        ),
    )


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    assert not (OUT / "run_ledger.json").exists()
    for p in PARENTS:
        assert sha(p / "manifest.json") == protocol["parent_manifests"][p.name]
    for sub in ["bundles", "reproduce"]:
        (OUT / sub).mkdir(exist_ok=True)
    sources = [
        Path(__file__),
        ROOT / "scripts/report_jeju_set_interaction.py",
        ROOT / "scripts/verify_jeju_set_interaction.py",
        ROOT / "scripts/diagnose_jeju_missing_podium.py",
        ROOT / "src/horse_racing/analysis/jeju_set_interaction.py",
        ROOT / "tests/test_jeju_set_interaction.py",
        ROOT / "pyproject.toml",
    ]
    for path in sources:
        shutil.copy2(path, OUT / "reproduce" / path.name)
    ledger = dict(
        status="running",
        started_at=datetime.now(UTC).isoformat(),
        protocol_sha256=sha(OUT / "protocol.json"),
        estimator_fits=[],
        calibration_fits=[],
    )
    save("run_ledger.json", ledger)
    frame, meta, truth, folds = load_frame()
    p = pl.read_parquet(V7 / "race_predictions.parquet").filter(
        pl.col("model").is_in(protocol["references"])
    )
    h = pl.read_parquet(V7 / "horse_predictions.parquet").filter(
        pl.col("model").is_in(protocol["references"])
    )
    predictions, horses = p.to_dicts(), h.to_dicts()
    dimensions = []
    for fold in sorted(folds["fold_id"].unique()):
        split = folds.filter(pl.col("fold_id") == fold)
        parts = {
            role: frame.join(
                split.filter(pl.col("role") == role).select("race_id"), on="race_id", how="semi"
            ).sort("race_id", "horse_id")
            for role in ["fit", "tune", "calibration", "evaluation"]
        }
        for a, b in [("fit", "tune"), ("tune", "calibration"), ("calibration", "evaluation")]:
            assert parts[a]["event_date"].max() < parts[b]["event_date"].min()
        pre = FitPreprocessor().fit(parts["fit"], protocol["features"])
        prepared = {k: prepare(v, truth, pre) for k, v in parts.items()}
        dimensions.append(
            dict(
                fold=fold,
                input_names=pre.names,
                dimensions=len(pre.names),
                interaction_dimensions=19,
                races={k: len(v[3]) for k, v in prepared.items()},
                candidate_sets={k: len(v[2].set_indices) for k, v in prepared.items()},
            )
        )
        save("feature_dimensions.json", dimensions)
        with (V5 / "bundles" / f"{fold}__HY_R_FORM.pkl").open("rb") as f:
            old = pickle.load(f)
        order_raw = order_scores(old["order_bundle"], parts["evaluation"])
        for name, interactions in protocol["candidates"].items():
            models = []
            x, z, layout, _ = prepared["fit"]
            tx, tz, tl, _ = prepared["tune"]
            for seed in protocol["seeds"]:
                event = dict(model=name, fold=fold, seed=seed, status="started")
                ledger["estimator_fits"].append(event)
                save("run_ledger.json", ledger)
                print(f"{fold} {name} seed{seed} started", flush=True)
                model = SetInteractionMLP(**protocol["params"]).fit(
                    x,
                    z if interactions else z[:, :0],
                    layout,
                    tune=(tx, tz if interactions else tz[:, :0], tl),
                    seed=seed,
                )
                models.append(model)
                event.update(
                    status="complete",
                    diagnostics={
                        k: v
                        for k, v in vars(model).items()
                        if k.endswith("_") and isinstance(v, (int, float, str, bool))
                    },
                )
                save("run_ledger.json", ledger)
                print(
                    f"{fold} {name} seed{seed} complete checkpoint{model.selected_iteration_}",
                    flush=True,
                )
            bundle = dict(
                model_name=name,
                fold=fold,
                features=protocol["features"],
                preprocessor=pre,
                models=models,
                interactions=interactions,
                order_bundle=old["order_bundle"],
                beta_order=old["beta_order"],
            )
            cx, cz, cl, _ = prepared["calibration"]
            cal_logits = raw_sets(bundle, cx, cz, cl)
            opt = minimize_scalar(
                lambda b, cal_logits=cal_logits, cl=cl: set_loss_gradient(
                    cal_logits * np.exp(b), cl
                )[0],
                bounds=(-4, 4),
                method="bounded",
                options={"xatol": 1e-5},
            )
            assert opt.success
            bundle["beta_set"] = float(np.exp(opt.x))
            ledger["calibration_fits"].append(
                dict(
                    model=name,
                    fold=fold,
                    status="complete",
                    partition="calibration",
                    beta_set=bundle["beta_set"],
                    objective=float(opt.fun),
                    at_boundary=bool(abs(opt.x) > 3.999),
                )
            )
            save("run_ledger.json", ledger)
            with (OUT / "bundles" / f"{fold}__{name}.pkl").open("wb") as f:
                pickle.dump(bundle, f)
            ex, ez, el, groups = prepared["evaluation"]
            logits = raw_sets(bundle, ex, ez, el)
            for j, (lo, hi, _) in enumerate(groups):
                race = parts["evaluation"].slice(lo, hi - lo)
                rid = int(race["race_id"][0])
                ids = race["horse_id"].to_list()
                official = race.filter(pl.col("label_top3") == 1)["horse_id"].to_list()
                raw = logits[el.set_starts[j] : el.set_ends[j]]
                metrics = evaluate_set_race(
                    ids,
                    raw,
                    order_raw[lo:hi],
                    truth[rid],
                    official,
                    beta_set=bundle["beta_set"],
                    beta_order=bundle["beta_order"],
                )
                marg = metrics.pop("pl_marginals")
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
                            score=None,
                            beta=None,
                            order_score=float(order_raw[lo + i]),
                            beta_set=bundle["beta_set"],
                            beta_order=bundle["beta_order"],
                            pl_place_probability=float(marg[i]),
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
    ledger.update(status="complete", completed_at=datetime.now(UTC).isoformat())
    save("run_ledger.json", ledger)


if __name__ == "__main__":
    import sys

    freeze() if "--freeze" in sys.argv else main()
