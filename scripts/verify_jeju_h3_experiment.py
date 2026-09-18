"""Check all three targets, fixed references, probabilities, and bundle replay."""

from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/jeju_native_h3_experiment_v3_20260916"
OLD = ROOT / "data/research/jeju_native_three_targets_v2_20260915"
H3 = ROOT / "data/research/jeju_native_h3_features_v1_20260916"
DATA = ROOT / "data/research/jeju_native_top3_dataset_v1_20260915_r2"


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    for path, key in [
        (DATA / "manifest.json", "dataset_manifest_sha256"),
        (OLD / "manifest.json", "parent_manifest_sha256"),
    ]:
        assert hashlib.sha256(path.read_bytes()).hexdigest() == protocol[key]
    assert (
        hashlib.sha256((H3 / "manifest.json").read_bytes()).hexdigest()
        == protocol["h3_feature_manifest_sha256"]
    )
    for name, expected_hash in json.loads((H3 / "manifest.json").read_text()).items():
        assert hashlib.sha256((H3 / name).read_bytes()).hexdigest() == expected_hash, name
    parent_manifest = json.loads((OLD / "manifest.json").read_text())
    for name, expected_hash in parent_manifest.items():
        assert hashlib.sha256((OLD / name).read_bytes()).hexdigest() == expected_hash, name
    checked = 0
    if (OUT / "manifest.json").exists():
        for name, sha in json.loads((OUT / "manifest.json").read_text()).items():
            assert hashlib.sha256((OUT / name).read_bytes()).hexdigest() == sha, name
            checked += 1
    p = pl.read_parquet(OUT / "race_predictions.parquet")
    h = pl.read_parquet(OUT / "horse_predictions.parquet")
    old = pl.read_parquet(OLD / "race_predictions.parquet").filter(
        pl.col("model").is_in(protocol["references"])
    )
    labels = pl.read_parquet(DATA / "labels.parquet").filter(pl.col("event_date").dt.year() == 2025)
    states = pl.read_parquet(DATA / "horse_states.parquet").join(
        labels.select("entry_id"), on="entry_id", how="semi"
    )
    states = states.join(pl.read_parquet(H3 / "features.parquet"), on="entry_id", validate="1:1")
    entries = pl.read_parquet(DATA / "entries.parquet")
    lineage = pl.read_parquet(H3 / "lineage.parquet").join(
        entries.select("entry_id", "event_date"), on="entry_id", validate="1:1"
    )
    assert len(lineage) == 84583 and lineage["entry_id"].n_unique() == 84583
    observed = lineage.filter(pl.col("card_observed") == 1)
    assert observed.select(
        (pl.col("source_file_date") <= pl.col("event_date") - pl.duration(days=2)).all()
    ).item()
    assert states.filter(pl.col("card_observed") == 1).height == 6953
    expected = set(labels.select("race_id", "horse_id").iter_rows())
    racekeys = set(labels["race_id"])
    truth = {(x["race_id"], x["horse_id"]): x["label_top3"] for x in labels.iter_rows(named=True)}
    assert len(p) == 4290 and len(h) == 41718 and p["model"].n_unique() == 6
    assert p.select(pl.struct("model", "race_id").n_unique()).item() == len(p)
    assert h.select(pl.struct("model", "race_id", "horse_id").n_unique()).item() == len(h)
    for model in h["model"].unique():
        assert (
            set(h.filter(pl.col("model") == model).select("race_id", "horse_id").iter_rows())
            == expected
        )
        assert set(p.filter(pl.col("model") == model)["race_id"]) == racekeys
    assert h["event_date"].str.starts_with("2025").all()
    assert np.isfinite(h["pl_place_probability"].to_numpy()).all()
    assert (
        h["pl_place_probability"].min() >= -1e-12 and h["pl_place_probability"].max() <= 1 + 1e-12
    )
    pr = {(r["model"], r["race_id"]): r for r in p.iter_rows(named=True)}
    for (model, rid), s in h.partition_by(["model", "race_id"], as_dict=True).items():
        assert abs(s["pl_place_probability"].sum() - 3) < 1e-10
        assert s["selected"].sum() == 1
        selected = s.filter(pl.col("selected")).row(0, named=True)
        row = pr[(model, rid)]
        assert row["pick_horse_id"] == selected["horse_id"]
        assert row["pick_hit"] == bool(truth[(rid, selected["horse_id"])])
        assert abs(row["pick_probability"] - selected["pl_place_probability"]) < 1e-12
        for r in s.iter_rows(named=True):
            assert r["official_top3"] == truth[(rid, r["horse_id"])]
        if model == "B0_uniform":
            np.testing.assert_allclose(
                s["pl_place_probability"].to_numpy(), 3 / len(s), atol=1e-12, rtol=0
            )
            assert abs(row["tie_expected_pick_hit"] - s["official_top3"].sum() / len(s)) < 1e-12
    for row in old.iter_rows(named=True):
        new = pr[(row["model"], row["race_id"])]
        for k in ["set_hit", "order_hit", "predicted_set", "predicted_order"]:
            assert new[k] == row[k]
        for k in ["set_nll", "order_nll"]:
            assert abs(new[k] - row[k]) < 1e-12
    replay = []
    for path in sorted((OUT / "bundles").glob("*.pkl")):
        with path.open("rb") as f:
            b = pickle.load(f)
        s = h.filter((pl.col("model") == b["model_name"]) & (pl.col("fold") == b["fold"])).sort(
            "race_id", "horse_id"
        )
        frame = states.join(
            s.select("race_id", "horse_id"), on=["race_id", "horse_id"], how="semi"
        ).sort("race_id", "horse_id")
        x = b["preprocessor"].transform(frame)
        raw = np.mean([m.predict(x, raw_score=True) for m in b["models"]], axis=0)
        np.testing.assert_allclose(raw, s["score"].to_numpy(), atol=1e-12, rtol=0)
        if b["native_calibrator"] is not None:
            native = b["native_calibrator"].predict(raw)
            np.testing.assert_allclose(
                native, s["native_place_probability"].to_numpy(), atol=1e-12, rtol=0
            )
            cal = b["native_calibrator"]
            assert cal.success_ and cal.scale_ > 0
            replay.append(
                {
                    "bundle": path.name,
                    "success": cal.success_,
                    "scale": cal.scale_,
                    "intercept": cal.intercept_,
                    "objective": cal.objective_,
                    "iterations": cal.n_iter_,
                    "at_boundary": abs(cal.log_scale_) >= 3.999 or abs(cal.intercept_) >= 9.999,
                }
            )
    ledger = json.loads((OUT / "run_ledger.json").read_text())
    assert (
        ledger["status"] == "complete"
        and len(ledger["estimator_fits"]) == 32
        and len(ledger["calibration_fits"]) == 24
    )
    assert all(
        x["status"] == "complete" for x in ledger["estimator_fits"] + ledger["calibration_fits"]
    )
    summaries = json.loads((OUT / "summary.json").read_text())
    for row in summaries:
        s = p.filter((pl.col("model") == row["model"]) & ~pl.col("boundary_tie"))
        assert row["probability_races"] == len(s)
        assert abs(row["place_brier"] - s["place_brier"].mean()) < 1e-12
        assert abs(row["place_logloss"] - s["place_logloss"].mean()) < 1e-12
        if row["model"].startswith("P_"):
            assert abs(row["native_brier"] - s["native_brier"].mean()) < 1e-12
    result = {
        "passed": True,
        "manifest_files_checked": checked,
        "common_races": 715,
        "models": 6,
        "race_prediction_rows": len(p),
        "horse_probability_rows": len(h),
        "reference_joint_predictions_unchanged": True,
        "parent_artifact_hashes_verified": len(parent_manifest),
        "cross_process_bundles_replayed": len(list((OUT / "bundles").glob("*.pkl"))),
        "h3_declared_2025_rows": 6953,
        "2026_prediction_rows": 0,
        "calibrator_diagnostics": replay,
    }
    (OUT / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "calibrator_diagnostics"}, indent=2))


if __name__ == "__main__":
    main()
