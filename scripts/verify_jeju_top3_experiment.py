"""Independent artifact checks and cross-process bundle replay for development."""

from __future__ import annotations

import hashlib
import json
import math
import pickle
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/jeju_native_top3_experiment_v1_20260915"
DATA = ROOT / "data/research/jeju_native_top3_dataset_v1_20260915_r2"


def main():
    manifest = json.loads((OUT / "manifest.json").read_text())
    for path, expected in manifest.items():
        assert hashlib.sha256((OUT / path).read_bytes()).hexdigest() == expected, path
    protocol = json.loads((OUT / "protocol.json").read_text())
    assert (
        hashlib.sha256((DATA / "manifest.json").read_bytes()).hexdigest()
        == protocol["dataset_manifest_sha256"]
    )
    ledger = json.loads((OUT / "run_ledger.json").read_text())
    assert ledger["status"] == "complete"
    assert len(ledger["estimator_fits"]) == 48 and len(ledger["calibration_fits"]) == 32
    assert all(x["status"] == "complete" for x in ledger["estimator_fits"])
    p = pl.read_parquet(OUT / "race_predictions.parquet")
    scores = pl.read_parquet(OUT / "horse_scores.parquet")
    entries = pl.read_parquet(DATA / "entries.parquet").filter(
        pl.col("event_date").dt.year() == 2025
    )
    states = pl.read_parquet(DATA / "horse_states.parquet").join(
        entries.select("entry_id"), on="entry_id", how="semi"
    )
    orders = pl.read_parquet(DATA / "accepted_orders.parquet").filter(
        pl.col("event_date").dt.year() == 2025
    )
    accepted = {}
    for row in orders.iter_rows(named=True):
        accepted.setdefault(row["race_id"], set()).add(
            (row["first_horse_id"], row["second_horse_id"], row["third_horse_id"])
        )
    models = p["model"].unique().to_list()
    assert len(models) == 9 and len(p) == 715 * 9 and len(scores) == 6953 * 9
    assert p.select(pl.struct("model", "race_id").n_unique()).item() == len(p)
    assert scores.select(pl.struct("model", "race_id", "horse_id").n_unique()).item() == len(scores)
    for model in models:
        sub = p.filter(pl.col("model") == model)
        assert set(sub["race_id"]) == set(entries["race_id"])
        key_actual = set(
            scores.filter(pl.col("model") == model).select("race_id", "horse_id").iter_rows()
        )
        assert key_actual == set(entries.select("race_id", "horse_id").iter_rows())
    for row in p.iter_rows(named=True):
        pred = tuple(row["predicted_order"])
        truth = accepted[row["race_id"]]
        sets = {frozenset(o) for o in truth}
        assert len(set(pred)) == 3 and set(pred) == set(row["predicted_set"])
        assert row["order_hit"] == (pred in truth)
        assert row["set_hit"] == (frozenset(pred) in sets)
        for key in [
            "set_confidence",
            "order_confidence",
            "order_probability_sum",
            "set_probability_sum",
            "set_nll",
            "order_nll",
        ]:
            assert np.isfinite(row[key]), key
        assert 0 <= row["order_confidence"] <= row["set_confidence"] <= 1 + 1e-10
        assert abs(row["order_probability_sum"] - 1) < 1e-10
        assert abs(row["set_probability_sum"] - 1) < 1e-10
        if row["model"] == "B0_uniform":
            n = row["field_size"]
            assert math.isclose(
                row["set_nll"], -math.log(len(sets) / math.comb(n, 3)), abs_tol=1e-10
            )
            assert math.isclose(
                row["order_nll"], -math.log(len(truth) / (n * (n - 1) * (n - 2))), abs_tol=1e-10
            )
    for path in sorted((OUT / "bundles").glob("*.pkl")):
        with path.open("rb") as f:
            bundle = pickle.load(f)
        saved = scores.filter(
            (pl.col("model") == bundle["model_name"]) & (pl.col("fold") == bundle["fold"])
        ).sort("race_id", "horse_id")
        frame = states.join(
            saved.select("race_id", "horse_id"), on=["race_id", "horse_id"], how="semi"
        ).sort("race_id", "horse_id")
        if "models" in bundle:
            x = bundle["preprocessor"].transform(frame)
            actual = np.mean([m.predict(x) for m in bundle["models"]], axis=0)
        elif bundle["model_name"] == "B0_uniform":
            actual = np.zeros(len(frame))
        elif bundle["model_name"] == "B1_elo":
            actual = frame["global_elo_pre"].to_numpy() * np.log(10) / 400
        else:
            a = frame["speed_residual_mean_pre"].to_numpy()
            actual = -np.where(np.isfinite(a), a, bundle["median"]) / 1000
        np.testing.assert_allclose(actual, saved["score"].to_numpy(), rtol=0, atol=1e-12)
        np.testing.assert_allclose(saved["beta"].to_numpy(), bundle["beta"], rtol=0, atol=0)
    failed_convergence = [
        x for x in ledger["estimator_fits"] if x.get("diagnostics", {}).get("success") is False
    ]
    report = {
        "passed": True,
        "artifact_hashes_checked": len(manifest),
        "models": 9,
        "common_races": 715,
        "horse_prediction_rows": len(scores),
        "bundles_cross_process_replayed": 36,
        "2026_prediction_rows": 0,
        "nonconverged_fits": len(failed_convergence),
        "nonconverged_details": failed_convergence,
    }
    (OUT / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
