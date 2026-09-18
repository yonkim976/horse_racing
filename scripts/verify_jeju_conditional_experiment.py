"""Verify context features, preserved sets, probability replay and immutable inputs."""

from __future__ import annotations

import json
import pickle

import numpy as np
import polars as pl

from horse_racing.analysis.jeju_hybrid_evaluation import evaluate_hybrid_race
from horse_racing.analysis.jeju_place_probability import evaluate_place_race
from horse_racing.analysis.jeju_top3_evaluation import evaluate_race
from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor
from scripts.run_jeju_conditional_experiment import (
    CTX,
    DATA,
    H3,
    OUT,
    RB,
    V3,
    V4,
    V5,
    V6,
    data_frame,
    order_scores,
    rank_scores,
    save,
    sha,
)
from scripts.run_jeju_top3_experiment import race_groups


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    checked = {}
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
        manifest = json.loads((folder / "manifest.json").read_text())
        hashes = (
            {k: v["sha256"] for k, v in manifest["files"].items()}
            if "files" in manifest
            else manifest
        )
        for name, value in hashes.items():
            assert sha(folder / name) == value, name
        checked[folder.name] = len(hashes)
    n_manifest = 0
    if (OUT / "manifest.json").exists():
        for name, value in json.loads((OUT / "manifest.json").read_text()).items():
            assert sha(OUT / name) == value, name
            n_manifest += 1
    lineage = pl.read_parquet(RB / "lineage.parquet")
    assert len(lineage) == 79731
    assert lineage.filter(pl.col("max_history_date") > pl.col("cutoff_date")).is_empty()
    assert lineage["event_date"].max().year == 2025
    frame, meta, truth, folds = data_frame(protocol)
    ev = frame.filter(pl.col("event_date").dt.year() == 2025)
    expected = set(ev.select("race_id", "horse_id").iter_rows())
    labels = {(r["race_id"], r["horse_id"]): r["label_top3"] for r in ev.iter_rows(named=True)}
    p = pl.read_parquet(OUT / "race_predictions.parquet")
    h = pl.read_parquet(OUT / "horse_predictions.parquet")
    assert len(p) == 10 * 715 and len(h) == 10 * 6953
    assert p.select(pl.struct("model", "race_id").n_unique()).item() == len(p)
    assert h.select(pl.struct("model", "race_id", "horse_id").n_unique()).item() == len(h)
    assert h["event_date"].str.starts_with("2025").all()
    rows = {(r["model"], r["race_id"]): r for r in p.iter_rows(named=True)}
    for name in p["model"].unique():
        assert (
            set(h.filter(pl.col("model") == name).select("race_id", "horse_id").iter_rows())
            == expected
        )
    for (name, rid), race in h.partition_by(["model", "race_id"], as_dict=True).items():
        probs = race["pl_place_probability"].to_numpy()
        assert np.isfinite(probs).all() and probs.min() >= -1e-12 and probs.max() <= 1 + 1e-12
        assert abs(probs.sum() - 3) < 1e-10 and race["selected"].sum() == 1
        row = rows[(name, rid)]
        sel = race.filter(pl.col("selected")).row(0, named=True)
        assert row["pick_horse_id"] == sel["horse_id"] and row["pick_hit"] == bool(
            labels[(rid, sel["horse_id"])]
        )
        assert abs(row["pick_probability"] - sel["pl_place_probability"]) < 1e-12
        assert row["set_hit"] == (
            tuple(sorted(row["predicted_set"])) in {tuple(sorted(o)) for o in truth[rid]}
        )
        assert row["order_hit"] == (tuple(row["predicted_order"]) in set(truth[rid]))
    oldp = pl.read_parquet(V6 / "race_predictions.parquet").filter(
        pl.col("model").is_in(protocol["references"])
    )
    for r in oldp.iter_rows(named=True):
        assert all(rows[(r["model"], r["race_id"])][k] == v for k, v in r.items())
    oldh = (
        pl.read_parquet(V6 / "horse_predictions.parquet")
        .filter(pl.col("model").is_in(protocol["references"]))
        .sort("model", "race_id", "horse_id")
    )
    assert (
        h.filter(pl.col("model").is_in(protocol["references"]))
        .sort("model", "race_id", "horse_id")
        .select(oldh.columns)
        .equals(oldh)
    )
    for name, (parent, _order_parent) in protocol["hybrids"].items():
        for r in p.filter(pl.col("model") == name).iter_rows(named=True):
            b = rows[(parent, r["race_id"])]
            for key in ["predicted_set", "set_hit", "pick_horse_id", "pick_hit"]:
                assert r[key] == b[key], (name, r["race_id"], key)
            for key in ["set_nll", "pick_probability", "place_brier", "place_logloss"]:
                assert abs(r[key] - b[key]) < 1e-11, (name, r["race_id"], key)
    replay = []
    for path in sorted((OUT / "bundles").glob("*.pkl")):
        with path.open("rb") as f:
            b = pickle.load(f)
        name, fold = b["model_name"], b["fold"]
        role = folds.filter(pl.col("fold_id") == fold)
        part = frame.join(
            role.filter(pl.col("role") == "evaluation").select("race_id"), on="race_id", how="semi"
        ).sort("race_id", "horse_id")
        if b["kind"] == "conditional":
            assert b["features"] == protocol["order_candidates"][name]
            raw = order_scores(b, part)
            for hybrid, (_rank, order) in protocol["hybrids"].items():
                if order != name:
                    continue
                saved = h.filter((pl.col("model") == hybrid) & (pl.col("fold") == fold)).sort(
                    "race_id", "horse_id"
                )
                np.testing.assert_allclose(raw, saved["order_score"].to_numpy(), atol=1e-12, rtol=0)
            fit = frame.join(
                role.filter(pl.col("role") == "fit").select("race_id"), on="race_id", how="semi"
            ).sort("race_id", "horse_id")
            pre = FitPreprocessor().fit(fit, b["features"])
            for key in ["medians", "means", "scales", "keep"]:
                np.testing.assert_array_equal(getattr(pre, key), getattr(b["preprocessor"], key))
            replay.append(path.name)
            continue
        if b["kind"] == "ranker":
            assert b["features"] == protocol["rank_candidates"][name]
        s = h.filter((pl.col("model") == name) & (pl.col("fold") == fold)).sort(
            "race_id", "horse_id"
        )
        assert len(part) == len(s)
        rb = b if b["kind"] == "ranker" else b["rank_bundle"]
        raw = rank_scores(rb, part)
        np.testing.assert_allclose(raw, s["score"].to_numpy(), atol=1e-12, rtol=0)
        ob = None if b["kind"] == "ranker" else order_scores(b["order_bundle"], part)
        if ob is not None:
            np.testing.assert_allclose(ob, s["order_score"].to_numpy(), atol=1e-12, rtol=0)
        if b["kind"] == "ranker":
            fit = frame.join(
                role.filter(pl.col("role") == "fit").select("race_id"), on="race_id", how="semi"
            ).sort("race_id", "horse_id")
            check = FitPreprocessor().fit(fit, b["features"])
            for key in ["medians", "means", "scales", "keep"]:
                np.testing.assert_array_equal(getattr(check, key), getattr(b["preprocessor"], key))
        for lo, hi, _ in race_groups(part, truth):
            race = part.slice(lo, hi - lo)
            rid = int(race["race_id"][0])
            ids = race["horse_id"].to_list()
            official = race.filter(pl.col("label_top3") == 1)["horse_id"].to_list()
            if ob is None:
                result = {
                    **evaluate_place_race(ids, raw[lo:hi], official, beta=rb["beta"]),
                    **evaluate_race(ids, raw[lo:hi], truth[rid], beta=rb["beta"]),
                }
            else:
                result = evaluate_hybrid_race(
                    ids,
                    raw[lo:hi],
                    ob[lo:hi],
                    truth[rid],
                    official,
                    beta_set=rb["beta"],
                    beta_order=b["beta_order"],
                )
                assert abs(result["order_probability_sum"] - 1) < 1e-10
                assert abs(result["set_probability_sum"] - 1) < 1e-10
            row = rows[(name, rid)]
            for key in [
                "predicted_set",
                "predicted_order",
                "pick_horse_id",
                "set_hit",
                "order_hit",
                "pick_hit",
            ]:
                assert result[key] == row[key]
            for key in ["set_nll", "order_nll", "place_brier", "place_logloss", "pick_probability"]:
                assert abs(result[key] - row[key]) < 1e-12, key
            np.testing.assert_allclose(
                result["pl_marginals"],
                s.slice(lo, hi - lo)["pl_place_probability"].to_numpy(),
                atol=1e-12,
                rtol=0,
            )
        replay.append(path.name)
    ledger = json.loads((OUT / "run_ledger.json").read_text())
    assert (
        ledger["status"] == "complete"
        and len(ledger["estimator_fits"]) == 24
        and len(ledger["calibration_fits"]) == 20
    )
    assert all(
        e["status"] == "complete" for e in ledger["estimator_fits"] + ledger["calibration_fits"]
    )
    assert len(replay) == 28 and ledger["protocol_sha256"] == sha(OUT / "protocol.json")
    for row in json.loads((OUT / "summary.json").read_text()):
        s = p.filter(pl.col("model") == row["model"])
        nt = s.filter(~pl.col("boundary_tie"))
        assert len(nt) == 709 and row["probability_races"] == 709
        for key in ["place_brier", "place_logloss"]:
            assert abs(row[key] - nt[key].mean()) < 1e-12
        assert (
            row["single_hits"] == s["pick_hit"].sum()
            and row["set_hits"] == s["set_hit"].sum()
            and row["order_hits"] == s["order_hit"].sum()
        )
    diagnostic = json.loads((OUT / "error_decomposition.json").read_text())
    reference = p.filter(pl.col("model") == diagnostic["reference"])
    overlaps = {str(i): 0 for i in range(4)}
    for row in reference.iter_rows(named=True):
        overlap = max(
            len(set(row["predicted_set"]) & set(order)) for order in truth[row["race_id"]]
        )
        overlaps[str(overlap)] += 1
    assert diagnostic["posthoc_diagnostic"] is True
    assert diagnostic["overlap_counts"] == overlaps
    assert diagnostic["total_races"] == len(reference)
    assert diagnostic["set_correct"] == reference["set_hit"].sum() == overlaps["3"]
    assert diagnostic["order_correct"] == reference["order_hit"].sum()
    assert diagnostic["set_wrong"] == len(reference) - overlaps["3"]
    assert diagnostic["set_correct_order_wrong"] == overlaps["3"] - reference["order_hit"].sum()
    assert abs(diagnostic["fixed_set_order_ceiling"] - overlaps["3"] / len(reference)) < 1e-12
    result = dict(
        passed=True,
        manifest_files_checked=n_manifest,
        parent_hashes_checked=checked,
        common_races=715,
        probability_races=709,
        models=10,
        race_rows=len(p),
        horse_rows=len(h),
        replayed_bundles=len(replay),
        hybrid_set_and_pick_preserved=True,
        fit_preprocessors_rebuilt=True,
        reference_predictions_unchanged=True,
        error_decomposition_checked=True,
        predictions_2026=0,
    )
    save("verification.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
