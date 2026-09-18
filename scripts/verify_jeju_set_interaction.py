"""Replay all set models and enforce untouched inputs and probability contracts."""

import json
import pickle

import numpy as np
import polars as pl

from horse_racing.analysis.jeju_set_interaction import evaluate_set_race
from horse_racing.analysis.jeju_top3_preprocessing import FitPreprocessor
from scripts.run_jeju_context_experiment import order_scores
from scripts.run_jeju_set_interaction import (
    OUT,
    PARENTS,
    V7,
    load_frame,
    prepare,
    raw_sets,
    save,
    sha,
)


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    checked = {}
    for folder in PARENTS:
        assert sha(folder / "manifest.json") == protocol["parent_manifests"][folder.name]
        manifest = json.loads((folder / "manifest.json").read_text())
        hashes = (
            {k: v["sha256"] for k, v in manifest["files"].items()}
            if "files" in manifest
            else manifest
        )
        for name, digest in hashes.items():
            assert sha(folder / name) == digest, (folder.name, name)
        checked[folder.name] = len(hashes)
    own = 0
    if (OUT / "manifest.json").exists():
        for name, digest in json.loads((OUT / "manifest.json").read_text()).items():
            assert sha(OUT / name) == digest, name
            own += 1
    frame, meta, truth, folds = load_frame()
    p = pl.read_parquet(OUT / "race_predictions.parquet")
    h = pl.read_parquet(OUT / "horse_predictions.parquet")
    models = list(protocol["candidates"]) + protocol["references"]
    assert set(p["model"].unique()) == set(models)
    assert len(p) == len(models) * 715 and len(h) == len(models) * 6953
    assert p.select(pl.struct("model", "race_id").n_unique()).item() == len(p)
    assert h.select(pl.struct("model", "race_id", "horse_id").n_unique()).item() == len(h)
    assert h["event_date"].str.starts_with("2025").all()
    rows = {(r["model"], r["race_id"]): r for r in p.iter_rows(named=True)}
    expected = set(
        frame.filter(pl.col("event_date").dt.year() == 2025)
        .select("race_id", "horse_id")
        .iter_rows()
    )
    for name in models:
        assert (
            set(h.filter(pl.col("model") == name).select("race_id", "horse_id").iter_rows())
            == expected
        )
    for key, race in h.partition_by(["model", "race_id"], as_dict=True).items():
        probs = race["pl_place_probability"].to_numpy()
        assert np.isfinite(probs).all() and probs.min() >= -1e-12 and probs.max() <= 1 + 1e-12
        assert abs(probs.sum() - 3) < 1e-10 and race["selected"].sum() == 1
        row = rows[key]
        selected = race.filter(pl.col("selected")).row(0, named=True)
        assert row["pick_horse_id"] == selected["horse_id"]
        assert row["pick_hit"] == bool(selected["official_top3"])
        assert row["set_hit"] == (
            tuple(sorted(row["predicted_set"])) in {tuple(sorted(o)) for o in truth[key[1]]}
        )
        assert row["order_hit"] == (tuple(row["predicted_order"]) in set(truth[key[1]]))
        if key[0] in protocol["candidates"]:
            assert abs(row["pick_probability"] - max(probs)) < 1e-12
    for filename, keys in [
        ("race_predictions.parquet", ["model", "race_id"]),
        ("horse_predictions.parquet", ["model", "race_id", "horse_id"]),
    ]:
        prior = (
            pl.read_parquet(V7 / filename)
            .filter(pl.col("model").is_in(protocol["references"]))
            .sort(keys)
        )
        new = (
            pl.read_parquet(OUT / filename)
            .filter(pl.col("model").is_in(protocol["references"]))
            .sort(keys)
        )
        assert prior.equals(new.select(prior.columns))
    replays = []
    for path in sorted((OUT / "bundles").glob("*.pkl")):
        b = pickle.loads(path.read_bytes())
        fold = b["fold"]
        name = b["model_name"]
        split = folds.filter(pl.col("fold_id") == fold)

        def part(role, split=split):
            return frame.join(
                split.filter(pl.col("role") == role).select("race_id"), on="race_id", how="semi"
            ).sort("race_id", "horse_id")

        fit = part("fit")
        ev = part("evaluation")
        rebuilt = FitPreprocessor().fit(fit, protocol["features"])
        for k in ["medians", "means", "scales", "keep"]:
            np.testing.assert_array_equal(getattr(rebuilt, k), getattr(b["preprocessor"], k))
        assert rebuilt.names == b["preprocessor"].names
        assert (
            b["features"] == protocol["features"]
            and b["interactions"] == protocol["candidates"][name]
        )
        x, z, layout, groups = prepare(ev, truth, b["preprocessor"])
        raw = raw_sets(b, x, z, layout)
        order = order_scores(b["order_bundle"], ev)
        for j, (lo, hi, _) in enumerate(groups):
            race = ev.slice(lo, hi - lo)
            rid = int(race["race_id"][0])
            ids = race["horse_id"].to_list()
            official = race.filter(pl.col("label_top3") == 1)["horse_id"].to_list()
            result = evaluate_set_race(
                ids,
                raw[layout.set_starts[j] : layout.set_ends[j]],
                order[lo:hi],
                truth[rid],
                official,
                beta_set=b["beta_set"],
                beta_order=b["beta_order"],
            )
            row = rows[(name, rid)]
            assert abs(result["set_probability_sum"] - 1) < 1e-10
            assert abs(result["order_probability_sum"] - 1) < 1e-10
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
            hh = h.filter((pl.col("model") == name) & (pl.col("race_id") == rid)).sort("horse_id")
            np.testing.assert_allclose(
                result["pl_marginals"], hh["pl_place_probability"], atol=1e-12, rtol=0
            )
            old = h.filter((pl.col("model") == "HY_R_FORM") & (pl.col("race_id") == rid)).sort(
                "horse_id"
            )
            np.testing.assert_allclose(order[lo:hi], old["order_score"], atol=1e-12, rtol=0)
            assert abs(b["beta_order"] - old["beta_order"][0]) < 1e-12
        replays.append(path.name)
    ledger = json.loads((OUT / "run_ledger.json").read_text())
    assert ledger["status"] == "complete" and ledger["protocol_sha256"] == sha(
        OUT / "protocol.json"
    )
    assert (
        len(ledger["estimator_fits"]) == 16
        and len(ledger["calibration_fits"]) == 8
        and len(replays) == 8
    )
    assert all(
        e["status"] == "complete" for e in ledger["estimator_fits"] + ledger["calibration_fits"]
    )
    for row in json.loads((OUT / "summary.json").read_text()):
        s = p.filter(pl.col("model") == row["model"])
        nt = s.filter(~pl.col("boundary_tie"))
        assert len(s) == 715 and len(nt) == 709
        for a, b in [
            ("single_hits", "pick_hit"),
            ("set_hits", "set_hit"),
            ("order_hits", "order_hit"),
        ]:
            assert row[a] == s[b].sum()
        for k in ["place_brier", "place_logloss"]:
            assert abs(row[k] - nt[k].mean()) < 1e-12
    diag = json.loads((OUT / "missing_horse_diagnostic.json").read_text())
    pairs = pl.read_parquet(OUT / "missing_horse_pairs.parquet")
    assert len(pairs) == diag["pair_races"] and pairs["race_id"].n_unique() == len(pairs)
    for pair in pairs.iter_rows(named=True):
        rid = pair["race_id"]
        row = rows[("HY_R_FORM", rid)]
        assert not meta[rid]["boundary_tie"]
        actual = set(truth[rid][0])
        chosen = set(row["predicted_set"])
        assert actual - chosen == {pair["missing_horse_id"]}
        assert chosen - actual == {pair["selected_nonpodium_horse_id"]}
    for transition in json.loads((OUT / "set_transitions.json").read_text()):
        ref = p.filter(pl.col("model") == "HY_R_FORM").sort("race_id")
        new = p.filter(pl.col("model") == transition["model"]).sort("race_id")
        assert transition["both_set_correct"] == int((ref["set_hit"] & new["set_hit"]).sum())
        assert transition["lost_set_correct"] == int((ref["set_hit"] & ~new["set_hit"]).sum())
        assert transition["gained_set_correct"] == int((~ref["set_hit"] & new["set_hit"]).sum())
        assert transition["old_two_to_three"] == int(
            ((ref["compatible_max_overlap"] == 2) & new["set_hit"]).sum()
        )
        assert transition["overlap_counts"] == {
            str(i): int((new["compatible_max_overlap"] == i).sum()) for i in range(4)
        }
    result = dict(
        passed=True,
        manifest_files_checked=own,
        parent_files_checked=checked,
        replayed_bundles=len(replays),
        models=len(models),
        common_races=715,
        probability_races=709,
        unchanged_references=True,
        unchanged_order_head=True,
        fit_preprocessors_rebuilt=True,
        diagnostic_pairs_checked=len(pairs),
        predictions_2026=0,
    )
    save("verification.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
