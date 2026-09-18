"""Rebuild feature lineage, CAL scalars and replay every new saved predictor."""

import json
import pickle
from datetime import date

import numpy as np
import polars as pl
from polars.testing import assert_frame_equal
from scipy.optimize import minimize_scalar

from horse_racing.analysis.jeju_hybrid_evaluation import evaluate_hybrid_race
from horse_racing.analysis.jeju_place_probability import evaluate_place_race
from horse_racing.analysis.jeju_top3_evaluation import evaluate_race
from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor
from horse_racing.analysis.jeju_trial_features import build_features
from scripts.build_jeju_trial_features import DB, load_trials
from scripts.freeze_jeju_trial_protocol import DATA, OUT, ROOT, TRIAL, V5, V9, sha
from scripts.run_jeju_top3_experiment import order_loss, race_groups
from scripts.run_jeju_trial_experiment import data_frame, order_scores, rank_scores, save


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    checked = {}
    for folder, digest in protocol["parents"].items():
        directory = ROOT / folder
        assert sha(directory / "manifest.json") == digest
        m = json.loads((directory / "manifest.json").read_text())
        hashes = {k: v["sha256"] for k, v in m["files"].items()} if "files" in m else m
        for name, value in hashes.items():
            assert sha(directory / name) == value, (folder, name)
        checked[directory.name] = len(hashes)
    own = 0
    if (OUT / "manifest.json").exists():
        for name, value in json.loads((OUT / "manifest.json").read_text()).items():
            assert sha(OUT / name) == value, name
            own += 1
    for name, value in json.loads((OUT / "pre_fit_source_hashes.json").read_text()).items():
        assert sha(ROOT / name) == value, name
    trials = [json.loads(line) for line in (TRIAL / "source_trials.jsonl").read_text().splitlines()]
    for row in trials:
        row["event_date"] = date.fromisoformat(row["event_date"])
    source_report = json.loads((TRIAL / "build_report.json").read_text())
    assert sha(DB) == source_report["source_sha256"]["database"]
    assert trials == load_trials()
    entries = pl.read_parquet(DATA / "entries.parquet").filter(
        pl.col("event_date").dt.year() <= 2025
    )
    rebuilt, lineage = build_features(entries.to_dicts(), trials)
    assert_frame_equal(pl.DataFrame(rebuilt), pl.read_parquet(TRIAL / "features.parquet"))
    assert_frame_equal(
        pl.DataFrame(lineage, infer_schema_length=None), pl.read_parquet(TRIAL / "lineage.parquet")
    )
    frame, meta, truth, folds = data_frame(protocol)
    p = pl.read_parquet(OUT / "race_predictions.parquet")
    h = pl.read_parquet(OUT / "horse_predictions.parquet")
    models = list(protocol["rank_candidates"]) + list(protocol["hybrids"]) + protocol["references"]
    assert set(p["model"]) == set(models) and len(p) == 5005 and len(h) == 48671
    assert p.select(pl.struct("model", "race_id").n_unique()).item() == len(p)
    assert h.select(pl.struct("model", "race_id", "horse_id").n_unique()).item() == len(h)
    assert h["event_date"].str.starts_with("2025").all()
    rows = {(r["model"], r["race_id"]): r for r in p.iter_rows(named=True)}
    ev = frame.filter(pl.col("event_date").dt.year() == 2025)
    expected = set(ev.select("race_id", "horse_id").iter_rows())
    labels = {(r["race_id"], r["horse_id"]): r["label_top3"] for r in ev.iter_rows(named=True)}
    for name in models:
        assert (
            set(h.filter(pl.col("model") == name).select("race_id", "horse_id").iter_rows())
            == expected
        )
    for (name, rid), race in h.partition_by(["model", "race_id"], as_dict=True).items():
        probs = race["pl_place_probability"].to_numpy()
        assert np.isfinite(probs).all() and probs.min() >= 0 and probs.max() <= 1
        assert abs(probs.sum() - 3) < 1e-10 and race["selected"].sum() == 1
        row = rows[(name, rid)]
        selected = race.filter(pl.col("selected")).row(0, named=True)
        assert row["pick_horse_id"] == selected["horse_id"]
        assert row["pick_hit"] == bool(labels[(rid, selected["horse_id"])])
        assert abs(row["pick_probability"] - selected["pl_place_probability"]) < 1e-12
        assert row["set_hit"] == (
            tuple(sorted(row["predicted_set"])) in {tuple(sorted(o)) for o in truth[rid]}
        )
        assert row["order_hit"] == (tuple(row["predicted_order"]) in set(truth[rid]))
        assert all(
            r["official_top3"] == labels[(rid, r["horse_id"])] for r in race.iter_rows(named=True)
        )
    for folder, names in [(V5, ["R_FORM", "HY_R_FORM"]), (V9, ["C_EXPERIENCE_FIXED"])]:
        for file, keys in [
            ("race_predictions.parquet", ["model", "race_id"]),
            ("horse_predictions.parquet", ["model", "race_id", "horse_id"]),
        ]:
            old = pl.read_parquet(folder / file).filter(pl.col("model").is_in(names)).sort(keys)
            new = pl.read_parquet(OUT / file).filter(pl.col("model").is_in(names)).sort(keys)
            assert_frame_equal(old, new.select(old.columns), check_dtypes=False)
    replays = []
    calibrations = 0
    for path in sorted((OUT / "bundles").glob("*.pkl")):
        b = pickle.loads(path.read_bytes())
        name = b["model_name"]
        fold = b["fold"]
        split = folds.filter(pl.col("fold_id") == fold)
        parts = {
            role: frame.join(
                split.filter(pl.col("role") == role).select("race_id"), on="race_id", how="semi"
            ).sort("race_id", "horse_id")
            for role in ["fit", "calibration", "evaluation"]
        }
        part = parts["evaluation"]
        rb = b if b["kind"] == "ranker" else b["rank_bundle"]
        pre = FitPreprocessor().fit(parts["fit"], rb["features"])
        assert rb["features"] == protocol["rank_candidates"][rb["model_name"]]
        for k in ["medians", "means", "scales", "keep"]:
            np.testing.assert_array_equal(getattr(pre, k), getattr(rb["preprocessor"], k))
        assert pre.names == rb["preprocessor"].names
        raw = rank_scores(rb, part)
        s = h.filter((pl.col("model") == name) & (pl.col("fold") == fold)).sort(
            "race_id", "horse_id"
        )
        np.testing.assert_allclose(raw, s["score"], atol=1e-12, rtol=0)
        ob = None
        if b["kind"] == "ranker":
            cal = rank_scores(rb, parts["calibration"])
            groups = race_groups(parts["calibration"], truth)
            opt = minimize_scalar(
                lambda x, cal=cal, groups=groups: order_loss(cal, groups, np.exp(x)),
                bounds=(-4, 4),
                method="bounded",
                options={"xatol": 1e-5},
            )
            assert opt.success and abs(float(np.exp(opt.x)) - rb["beta"]) < 1e-12
            calibrations += 1
        else:
            ob = order_scores(b["order_bundle"], part)
            parent = pickle.loads((V5 / "bundles" / f"{fold}__HY_R_FORM.pkl").read_bytes())
            np.testing.assert_allclose(
                ob, order_scores(parent["order_bundle"], part), atol=1e-12, rtol=0
            )
            assert b["beta_order"] == parent["beta_order"]
            np.testing.assert_allclose(ob, s["order_score"], atol=1e-12, rtol=0)
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
                assert abs(result["set_probability_sum"] - 1) < 1e-10
                assert abs(result["order_probability_sum"] - 1) < 1e-10
                for k in ["pick_horse_id", "predicted_set", "pick_hit", "set_hit"]:
                    assert result[k] == rows[(b["set_parent"], rid)][k]
            row = rows[(name, rid)]
            for k in [
                "predicted_set",
                "predicted_order",
                "pick_horse_id",
                "set_hit",
                "order_hit",
                "pick_hit",
            ]:
                assert result[k] == row[k], (name, rid, k)
            for k in ["set_nll", "order_nll", "place_brier", "place_logloss", "pick_probability"]:
                assert abs(result[k] - row[k]) < 1e-12, (name, rid, k)
            np.testing.assert_allclose(
                result["pl_marginals"],
                s.slice(lo, hi - lo)["pl_place_probability"],
                atol=1e-12,
                rtol=0,
            )
        replays.append(path.name)
    ledger = json.loads((OUT / "run_ledger.json").read_text())
    assert ledger["status"] == "complete" and ledger["protocol_sha256"] == sha(
        OUT / "protocol.json"
    )
    assert len(ledger["estimator_fits"]) == 16 and len(ledger["calibration_fits"]) == 8
    assert len(replays) == 16 and calibrations == 8
    assert all(
        e["status"] == "complete" for e in ledger["estimator_fits"] + ledger["calibration_fits"]
    )
    for row in json.loads((OUT / "summary.json").read_text()):
        s = p.filter(pl.col("model") == row["model"])
        nt = s.filter(~pl.col("boundary_tie"))
        assert len(s) == 715 and len(nt) == 709
        for a, z in [
            ("single_hits", "pick_hit"),
            ("set_hits", "set_hit"),
            ("order_hits", "order_hit"),
        ]:
            assert row[a] == s[z].sum()
        for k in ["place_brier", "place_logloss"]:
            assert abs(row[k] - nt[k].mean()) < 1e-12
    context = pl.read_parquet(OUT / "subgroup_context.parquet")
    assert_frame_equal(context, ev.select(context.columns))
    joined = h.join(context, on=["race_id", "horse_id"], validate="m:1")
    for row in json.loads((OUT / "zero_experience_diagnostic.json").read_text()):
        part = joined.filter(
            (pl.col("model") == row["model"])
            & (~pl.col("boundary_tie"))
            & (pl.col("starts_pre") == 0)
        )
        prob = part["pl_place_probability"].to_numpy()
        y = part["official_top3"].to_numpy()
        assert len(part) == row["entries"] == 292
        assert abs(float(np.mean((prob - y) ** 2)) - row["brier"]) < 1e-12
        assert abs(float(np.mean(prob)) - row["mean_probability"]) < 1e-12
        assert abs(float(np.mean(y)) - row["observed_rate"]) < 1e-12
    paired = {
        (r["candidate"], r["reference"]): r
        for r in json.loads((OUT / "paired_comparisons.json").read_text())
    }
    decision = json.loads((OUT / "decision.json").read_text())
    for row in decision["comparisons"]:
        c = paired[(row["candidate"], row["reference"])]
        passed = (
            c["set_hit"]["day_ci"][0] > 0
            and c["pick_hit"]["delta"] >= 0
            and c["order_hit"]["delta"] >= 0
        )
        assert passed == row["passes_selection_criterion"]
    assert not any(r["passes_selection_criterion"] for r in decision["comparisons"])
    result = dict(
        passed=True,
        manifest_files_checked=own,
        parent_files_checked=checked,
        feature_rows_rebuilt=len(rebuilt),
        lineage_rows_rebuilt=len(lineage),
        replayed_bundles=len(replays),
        calibration_scalars_rebuilt=calibrations,
        fit_preprocessors_rebuilt=True,
        unchanged_references=True,
        unchanged_order_head=True,
        race_rows=len(p),
        horse_rows=len(h),
        predictions_2026=0,
    )
    save("verification.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
