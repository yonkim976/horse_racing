"""Rebuild temporal features, replay frozen predictions and audit holdout boundaries."""

import json
import pickle

import numpy as np
import polars as pl
from polars.testing import assert_frame_equal
from scipy.optimize import minimize_scalar

from horse_racing.analysis.jeju_context_features import build_features as context_features
from horse_racing.analysis.jeju_hybrid_evaluation import (
    accepted_layout,
    conditional_calibration_loss,
    evaluate_hybrid_race,
)
from horse_racing.analysis.jeju_place_probability import evaluate_place_race
from horse_racing.analysis.jeju_top3_evaluation import evaluate_race
from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor
from horse_racing.analysis.jeju_transition_features import build_features
from scripts.freeze_jeju_transition_protocol import CTX, DATA, FEAT, H3, OUT, ROOT, sha
from scripts.run_jeju_top3_experiment import order_loss, race_groups
from scripts.run_jeju_transition_holdout import data_frame, order_scores, rank_scores, save


def hashes(folder):
    m = json.loads((folder / "manifest.json").read_text())
    m = {k: v["sha256"] for k, v in m["files"].items()} if "files" in m else m
    for name, digest in m.items():
        assert sha(folder / name) == digest, (folder, name)
    return len(m)


def main():
    p = json.loads((OUT / "protocol.json").read_text())
    parents = {}
    for folder, digest in p["parents"].items():
        assert sha(ROOT / folder / "manifest.json") == digest
        parents[folder] = hashes(ROOT / folder)
    parents[str(FEAT.relative_to(ROOT))] = hashes(FEAT)
    own = hashes(OUT) if (OUT / "manifest.json").exists() else 0
    for file, digest in json.loads((OUT / "pre_fit_source_hashes.json").read_text()).items():
        assert sha(ROOT / file) == digest, file
    target = pl.read_parquet(FEAT / "transition_targets.parquet")
    history = pl.read_parquet(FEAT / "transition_history.parquet")
    features, lineage = build_features(target.to_dicts(), history.to_dicts())
    ff = pl.read_parquet(FEAT / "features.parquet")
    assert_frame_equal(pl.DataFrame(features, infer_schema_length=None), ff, check_exact=True)
    assert_frame_equal(
        pl.DataFrame(lineage, infer_schema_length=None),
        pl.read_parquet(FEAT / "lineage.parquet"),
        check_exact=True,
    )
    assert all(
        r["previous_date"] is None or r["previous_date"] <= r["cutoff_date"] for r in lineage
    )
    rebuilt = context_features(
        pl.read_parquet(FEAT / "context_targets.parquet").to_dicts(),
        pl.read_parquet(FEAT / "context_history.parquet").to_dicts(),
    )
    cf = pl.read_parquet(FEAT / "context_features.parquet")
    assert_frame_equal(
        pl.DataFrame(rebuilt, infer_schema_length=None).select(cf.columns), cf, check_exact=True
    )
    old = pl.read_parquet(CTX / "features.parquet").sort("entry_id")
    assert_frame_equal(
        cf.join(old.select("entry_id"), on="entry_id", how="semi").sort("entry_id"),
        old,
        check_exact=True,
    )
    cards = pl.read_parquet(H3 / "features.parquet")
    c = target.join(
        cards.select("entry_id", "declared_grade_number", "declared_burden_kg"),
        on="entry_id",
        suffix="_card",
        validate="1:1",
    )
    for col in ["declared_grade_number", "declared_burden_kg"]:
        np.testing.assert_allclose(
            c[col].to_numpy().astype(float),
            c[col + "_card"].to_numpy().astype(float),
            equal_nan=True,
            atol=0,
            rtol=0,
        )
    lock = json.loads((OUT / "prediction_lock.json").read_text())
    for file, digest in lock["files"].items():
        assert sha(OUT / file) == digest
    assert lock["feature_manifest_sha256"] == sha(FEAT / "manifest.json")
    release = json.loads((OUT / "evaluation_release.json").read_text())
    assert lock["frozen_at"] < release["evaluated_at"] and release["lock_sha256"] == sha(
        OUT / "prediction_lock.json"
    )
    frame, truth, folds = data_frame()
    parts = {
        role: frame.join(
            folds.filter(pl.col("role") == role).select("race_id"), on="race_id", how="semi"
        ).sort("race_id", "horse_id")
        for role in ["fit", "tune", "calibration", "evaluation"]
    }
    for role in ["fit", "tune", "calibration"]:
        assert parts[role]["event_date"].max().year <= 2025
    assert parts["evaluation"]["label_top3"].null_count() == 4852
    assert parts["evaluation"]["finish_position"].null_count() == 4852
    raw = pl.read_parquet(OUT / "frozen_scores.parquet")
    h = pl.read_parquet(OUT / "horse_predictions.parquet")
    races = pl.read_parquet(OUT / "race_predictions.parquet")
    assert len(raw) == len(h) == 6 * 4852 and len(races) == 6 * 510
    assert raw.select(pl.struct("model", "entry_id").n_unique()).item() == len(raw)
    assert races.select(pl.struct("model", "race_id").n_unique()).item() == len(races)
    expected = set(parts["evaluation"]["entry_id"])
    for model in raw["model"].unique():
        assert set(raw.filter(pl.col("model") == model)["entry_id"]) == expected
    evtruth = {}
    for r in (
        pl.read_parquet(DATA / "accepted_orders.parquet")
        .filter(pl.col("event_date").dt.year() == 2026)
        .iter_rows(named=True)
    ):
        evtruth.setdefault(r["race_id"], []).append(
            (r["first_horse_id"], r["second_horse_id"], r["third_horse_id"])
        )
    labels = pl.read_parquet(DATA / "labels.parquet").filter(pl.col("event_date").dt.year() == 2026)
    official = {}
    for r in labels.filter(pl.col("label_top3") == 1).iter_rows(named=True):
        official.setdefault(r["race_id"], []).append(r["horse_id"])
    saved = {(r["model"], r["race_id"]): r for r in races.iter_rows(named=True)}
    replays = 0
    calfits = 0
    for path in sorted((OUT / "bundles").glob("*.pkl")):
        b = pickle.loads(path.read_bytes())
        name = b["model_name"]
        root = b["rank_bundle"] if b["kind"] == "hybrid" else b
        pre = FitPreprocessor().fit(parts["fit"], root["features"])
        for k in ["medians", "means", "scales", "keep"]:
            np.testing.assert_array_equal(getattr(pre, k), getattr(root["preprocessor"], k))
        assert pre.names == root["preprocessor"].names
        if b["kind"] == "joint_order":
            calraw = order_scores(b, parts["calibration"])
            rb = pickle.loads((OUT / "bundles/frozen_2026__R_FORM.pkl").read_bytes())
            rcal = rank_scores(rb, parts["calibration"])
            layouts = []
            for lo, hi, _ in race_groups(parts["calibration"], truth):
                part = parts["calibration"].slice(lo, hi - lo)
                rid = int(part["race_id"][0])
                layouts.append(
                    accepted_layout(
                        part["horse_id"].to_list(),
                        rcal[lo:hi],
                        calraw[lo:hi],
                        truth[rid],
                        rb["beta"],
                    )
                )
            opt = minimize_scalar(
                lambda x, layouts=layouts: conditional_calibration_loss(x, layouts),
                bounds=(-4, 4),
                method="bounded",
                options={"xatol": 1e-5},
            )
            assert opt.success and abs(np.exp(opt.x) - b["beta_order"]) < 1e-12
            calfits += 1
            replays += 1
            continue
        if b["kind"] == "ranker":
            assert b["features"] == p["rank_candidates"][name]
            calraw = rank_scores(b, parts["calibration"])
            groups = race_groups(parts["calibration"], truth)
            opt = minimize_scalar(
                lambda x, calraw=calraw, groups=groups: order_loss(calraw, groups, np.exp(x)),
                bounds=(-4, 4),
                method="bounded",
                options={"xatol": 1e-5},
            )
            assert opt.success and abs(np.exp(opt.x) - b["beta"]) < 1e-12
            calfits += 1
        sr = raw.filter(pl.col("model") == name).sort("race_id", "horse_id")
        score = rank_scores(root, parts["evaluation"])
        np.testing.assert_allclose(score, sr["score"], atol=1e-12, rtol=0)
        order = None
        if b["kind"] == "hybrid":
            ob = pickle.loads((OUT / "bundles/frozen_2026__O_BASE.pkl").read_bytes())
            order = order_scores(b["order_bundle"], parts["evaluation"])
            np.testing.assert_allclose(
                order, order_scores(ob, parts["evaluation"]), atol=1e-12, rtol=0
            )
            np.testing.assert_allclose(order, sr["order_score"], atol=1e-12, rtol=0)
            assert b["beta_order"] == ob["beta_order"]
        for lo, hi, _ in race_groups(parts["evaluation"], evtruth):
            part = parts["evaluation"].slice(lo, hi - lo)
            rid = int(part["race_id"][0])
            ids = part["horse_id"].to_list()
            if order is None:
                metrics = {
                    **evaluate_place_race(ids, score[lo:hi], official[rid], beta=root["beta"]),
                    **evaluate_race(ids, score[lo:hi], evtruth[rid], beta=root["beta"]),
                }
            else:
                metrics = evaluate_hybrid_race(
                    ids,
                    score[lo:hi],
                    order[lo:hi],
                    evtruth[rid],
                    official[rid],
                    beta_set=root["beta"],
                    beta_order=b["beta_order"],
                )
                assert (
                    abs(metrics["set_probability_sum"] - 1) < 1e-10
                    and abs(metrics["order_probability_sum"] - 1) < 1e-10
                )
                for key in ["pick_horse_id", "predicted_set"]:
                    assert metrics[key] == saved[(b["set_parent"], rid)][key]
            row = saved[(name, rid)]
            for k in [
                "pick_horse_id",
                "predicted_set",
                "predicted_order",
                "pick_hit",
                "set_hit",
                "order_hit",
            ]:
                assert metrics[k] == row[k]
            for k in ["place_brier", "place_logloss", "set_nll", "order_nll", "pick_probability"]:
                assert abs(metrics[k] - row[k]) < 1e-12
            hs = h.filter((pl.col("model") == name) & (pl.col("race_id") == rid)).sort("horse_id")
            np.testing.assert_allclose(
                metrics["pl_marginals"], hs["pl_place_probability"], atol=1e-12, rtol=0
            )
            np.testing.assert_array_equal(metrics["official_labels"], hs["official_top3"])
            assert abs(hs["pl_place_probability"].sum() - 3) < 1e-10
        replays += 1
    ledger = json.loads((OUT / "run_ledger.json").read_text())
    assert ledger["status"] == "complete" and ledger["protocol_sha256"] == sha(
        OUT / "protocol.json"
    )
    assert (
        len(ledger["estimator_fits"]) == 8
        and len(ledger["calibration_fits"]) == 4
        and replays == 7
        and calfits == 4
    )
    assert all(
        x["status"] == "complete" for x in ledger["estimator_fits"] + ledger["calibration_fits"]
    )
    for row in json.loads((OUT / "summary.json").read_text()):
        part = races.filter(pl.col("model") == row["model"])
        nt = part.filter(~pl.col("boundary_tie"))
        assert len(part) == row["races"] == 510 and len(nt) == row["probability_races"]
        for a, z in [
            ("single_hits", "pick_hit"),
            ("set_hits", "set_hit"),
            ("order_hits", "order_hit"),
        ]:
            assert row[a] == part[z].sum()
        for k in ["place_brier", "place_logloss"]:
            assert abs(row[k] - nt[k].mean()) < 1e-12
    joined = h.join(ff.select("entry_id", "transition_6to5"), on="entry_id", validate="m:1").filter(
        ~pl.col("boundary_tie")
    )
    for row in json.loads((OUT / "grade_subgroups.json").read_text()):
        part = joined.filter(pl.col("model") == row["model"])
        col = pl.col("transition_6to5")
        part = part.filter(
            col == 1
            if row["group"] == "6to5"
            else col == 0
            if row["group"] == "other_same_year"
            else ~col.is_finite()
        )
        assert len(part) == row["entries"]
        assert abs(part["official_top3"].mean() - row["observed_rate"]) < 1e-12
        assert abs(part["pl_place_probability"].mean() - row["mean_probability"]) < 1e-12
    comparisons = {
        (r["candidate"], r["reference"]): r
        for r in json.loads((OUT / "paired_comparisons.json").read_text())
    }
    decision = json.loads((OUT / "decision.json").read_text())
    base = races.filter(pl.col("model") == "HY_R_FORM").sort("race_id")
    dates, dayids = np.unique(base["event_date"].to_numpy(), return_inverse=True)
    rng = np.random.default_rng(17)
    rng.integers(0, len(base), size=(5000, len(base)))
    draw = rng.integers(0, len(dates), size=(5000, len(dates)))
    counts = np.bincount(dayids, minlength=len(dates))
    for row in decision["primary_comparisons"]:
        candidate = races.filter(pl.col("model") == row["candidate"]).sort("race_id")
        diff = candidate["set_hit"].to_numpy().astype(float) - base["set_hit"].to_numpy().astype(
            float
        )
        total = np.bincount(dayids, weights=diff, minlength=len(dates))
        boot = total[draw].sum(axis=1) / counts[draw].sum(axis=1)
        ci = np.quantile(boot, [0.0125, 0.9875])
        np.testing.assert_allclose(ci, row["set_primary_ci_97_5"], atol=1e-12, rtol=0)
        cmp = comparisons[(row["candidate"], "HY_R_FORM")]
        assert abs(diff.mean() - cmp["set_hit"]["delta"]) < 1e-12
        passes = ci[0] > 0 and cmp["pick_hit"]["delta"] >= 0 and cmp["order_hit"]["delta"] >= 0
        assert bool(passes) == row["passed"]
    assert decision["retained_research_selection"] == "HY_R_FORM"
    assert not any(r["passed"] for r in decision["primary_comparisons"])
    result = dict(
        passed=True,
        manifest_files_checked=own,
        parent_files_checked=parents,
        feature_rows_rebuilt=len(features),
        context_rows_rebuilt=len(cf),
        legacy_context_unchanged=len(old),
        replayed_bundles=replays,
        calibrations_rebuilt=calfits,
        prediction_lock_verified=True,
        primary_intervals_and_decision_rebuilt=True,
        fit_2026_rows=0,
        evaluation_races=510,
        evaluation_entries=4852,
        models=6,
        holdout_consumed=True,
        post_evaluation_refits=0,
    )
    save("verification.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
