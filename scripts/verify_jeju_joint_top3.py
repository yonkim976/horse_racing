"""Independent replay and integrity verification for joint podium experiment."""

from __future__ import annotations

import json
import pickle

import numpy as np
import polars as pl

from horse_racing.analysis.jeju_joint_evaluation import evaluate_joint_race
from scripts.run_jeju_joint_top3 import DATA, H3, OLD, OUT, load_data, save, sha
from scripts.run_jeju_top3_experiment import race_groups


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    parent_checks = {}
    for folder, key in [
        (DATA, "dataset_manifest_sha256"),
        (H3, "h3_feature_manifest_sha256"),
        (OLD, "parent_manifest_sha256"),
    ]:
        assert sha(folder / "manifest.json") == protocol[key]
        # Verify immutable data files as well as the manifest itself.
        manifest = json.loads((folder / "manifest.json").read_text())
        checked = 0
        if all(isinstance(v, str) and len(v) == 64 for v in manifest.values()):
            for name, expected in manifest.items():
                assert sha(folder / name) == expected, name
                checked += 1
        if "files" in manifest:
            for name, item in manifest["files"].items():
                assert sha(folder / name) == item["sha256"], name
                checked += 1
        parent_checks[folder.name] = checked
    checked = 0
    if (OUT / "manifest.json").exists():
        for name, expected in json.loads((OUT / "manifest.json").read_text()).items():
            assert sha(OUT / name) == expected, name
            checked += 1
    frame, meta, truth, folds = load_data()
    ev = frame.filter(pl.col("event_date").dt.year() == 2025)
    expected = set(ev.select("race_id", "horse_id").iter_rows())
    official = {(r["race_id"], r["horse_id"]): r["label_top3"] for r in ev.iter_rows(named=True)}
    p = pl.read_parquet(OUT / "race_predictions.parquet")
    h = pl.read_parquet(OUT / "horse_predictions.parquet")
    models = protocol["references"] + list(protocol["candidates"])
    assert len(p) == len(models) * 715 and len(h) == len(models) * 6953
    assert p.select(pl.struct("model", "race_id").n_unique()).item() == len(p)
    assert h.select(pl.struct("model", "race_id", "horse_id").n_unique()).item() == len(h)
    assert h["event_date"].str.starts_with("2025").all()
    rows = {(r["model"], r["race_id"]): r for r in p.iter_rows(named=True)}
    for name in models:
        assert (
            set(h.filter(pl.col("model") == name).select("race_id", "horse_id").iter_rows())
            == expected
        )
    for (name, rid), race in h.partition_by(["model", "race_id"], as_dict=True).items():
        probs = race["pl_place_probability"].to_numpy()
        assert np.isfinite(probs).all() and probs.min() >= -1e-12 and probs.max() <= 1 + 1e-12
        assert abs(probs.sum() - 3) < 1e-10
        assert race["selected"].sum() == 1
        selected = race.filter(pl.col("selected")).row(0, named=True)
        row = rows[(name, rid)]
        assert row["pick_horse_id"] == selected["horse_id"]
        assert row["pick_hit"] == bool(official[(rid, selected["horse_id"])])
        assert abs(row["pick_probability"] - selected["pl_place_probability"]) < 1e-12
        assert row["set_hit"] == (
            tuple(sorted(row["predicted_set"])) in {tuple(sorted(o)) for o in truth[rid]}
        )
        assert row["order_hit"] == (tuple(row["predicted_order"]) in set(truth[rid]))
        for r in race.iter_rows(named=True):
            assert r["official_top3"] == official[(rid, r["horse_id"])]
    old = pl.read_parquet(OLD / "race_predictions.parquet").filter(
        pl.col("model").is_in(protocol["references"])
    )
    for row in old.iter_rows(named=True):
        new = rows[(row["model"], row["race_id"])]
        for key, value in row.items():
            assert new[key] == value, (row["model"], row["race_id"], key)
    oldh = (
        pl.read_parquet(OLD / "horse_predictions.parquet")
        .filter(pl.col("model").is_in(protocol["references"]))
        .sort("model", "race_id", "horse_id")
    )
    newh = (
        h.filter(pl.col("model").is_in(protocol["references"]))
        .sort("model", "race_id", "horse_id")
        .select(oldh.columns)
    )
    assert oldh.equals(newh)
    replay = []
    for path in sorted((OUT / "bundles").glob("*.pkl")):
        with path.open("rb") as stream:
            bundle = pickle.load(stream)
        name, fold = bundle["model_name"], bundle["fold"]
        s = h.filter((pl.col("model") == name) & (pl.col("fold") == fold)).sort(
            "race_id", "horse_id"
        )
        part = frame.join(
            s.select("race_id", "horse_id"), on=["race_id", "horse_id"], how="semi"
        ).sort("race_id", "horse_id")
        split = folds.filter(pl.col("fold_id") == fold)
        assert set(part["race_id"]) == set(split.filter(pl.col("role") == "evaluation")["race_id"])
        fit = frame.join(
            split.filter(pl.col("role") == "fit").select("race_id"), on="race_id", how="semi"
        ).sort("race_id", "horse_id")
        from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor

        checkpre = FitPreprocessor().fit(fit, bundle["features"])
        for attr in ["medians", "means", "scales", "keep"]:
            np.testing.assert_array_equal(
                getattr(checkpre, attr), getattr(bundle["preprocessor"], attr)
            )
        raw = np.mean(
            [m.predict(bundle["preprocessor"].transform(part)) for m in bundle["models"]], axis=0
        )
        np.testing.assert_allclose(
            raw, s.select("inclusion_score", "order_score").to_numpy(), rtol=0, atol=1e-12
        )
        assert np.all(bundle["betas"] > 0)
        for lo, hi, _ in race_groups(part, truth):
            race = part.slice(lo, hi - lo)
            rid = int(race["race_id"][0])
            result = evaluate_joint_race(
                race["horse_id"].to_list(),
                raw[lo:hi, 0],
                raw[lo:hi, 1],
                truth[rid],
                race.filter(pl.col("label_top3") == 1)["horse_id"].to_list(),
                beta_set=float(bundle["betas"][0]),
                beta_order=float(bundle["betas"][1]),
            )
            row = rows[(name, rid)]
            assert abs(row["set_probability_sum"] - 1) < 1e-10
            assert abs(row["order_probability_sum"] - 1) < 1e-10
            for key in [
                "predicted_order",
                "predicted_set",
                "pick_horse_id",
                "pick_hit",
                "set_hit",
                "order_hit",
            ]:
                assert result[key] == row[key], key
            for key in ["set_nll", "order_nll", "pick_probability", "place_brier", "place_logloss"]:
                assert abs(result[key] - row[key]) < 1e-12, key
            np.testing.assert_allclose(
                result["pl_marginals"],
                s.slice(lo, hi - lo)["pl_place_probability"].to_numpy(),
                rtol=0,
                atol=1e-12,
            )
        replay.append(path.name)
    ledger = json.loads((OUT / "run_ledger.json").read_text())
    assert ledger["status"] == "complete" and ledger["protocol_sha256"] == sha(
        OUT / "protocol.json"
    )
    assert (
        len(ledger["estimator_fits"]) == 16
        and len(ledger["calibration_fits"]) == 8
        and len(replay) == 8
    )
    assert all(
        e["status"] == "complete" for e in ledger["estimator_fits"] + ledger["calibration_fits"]
    )
    for row in json.loads((OUT / "summary.json").read_text()):
        s = p.filter(pl.col("model") == row["model"])
        nt = s.filter(~pl.col("boundary_tie"))
        assert len(nt) == 709 and row["probability_races"] == 709
        for key in ["place_brier", "place_logloss"]:
            assert abs(row[key] - nt[key].mean()) < 1e-12
        for key, count in [
            ("pick_hit", "single_hits"),
            ("set_hit", "set_hits"),
            ("order_hit", "order_hits"),
        ]:
            assert row[count] == s[key].sum()
    result = dict(
        passed=True,
        manifest_files_checked=checked,
        parent_artifact_checks=parent_checks,
        models=len(models),
        common_races=715,
        probability_races=709,
        race_rows=len(p),
        horse_rows=len(h),
        bundles_replayed=replay,
        fit_preprocessors_rebuilt=True,
        reference_predictions_unchanged=True,
        predictions_2026=0,
    )
    save("verification.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
