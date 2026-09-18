"""Replay calibration fits, frozen policies and all probability outputs."""

import json
import pickle

import numpy as np
import polars as pl

from horse_racing.analysis.jeju_experience_calibration import (
    ExperienceSetCalibrator,
    evaluate_policy,
)
from scripts.run_jeju_experience_calibration import (
    OUT,
    PARENTS,
    V8,
    design,
    load_frame,
    prepare,
    save,
    sha,
)


def main():
    protocol = json.loads((OUT / "protocol.json").read_text())
    parents = {}
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
        parents[folder.name] = len(hashes)
    own = 0
    if (OUT / "manifest.json").exists():
        for name, digest in json.loads((OUT / "manifest.json").read_text()).items():
            assert sha(OUT / name) == digest, name
            own += 1
    frame, meta, truth, folds = load_frame()
    p = pl.read_parquet(OUT / "race_predictions.parquet")
    h = pl.read_parquet(OUT / "horse_predictions.parquet")
    assert len(p) == 4 * 715 and len(h) == 4 * 6953
    assert p.select(pl.struct("model", "race_id").n_unique()).item() == len(p)
    assert h.select(pl.struct("model", "race_id", "horse_id").n_unique()).item() == len(h)
    assert set(p["model"].unique()) == set(protocol["policies"]) | {"HY_R_FORM"}
    assert h["event_date"].str.starts_with("2025").all()
    rows = {(r["model"], r["race_id"]): r for r in p.iter_rows(named=True)}
    for filename, keys in [
        ("race_predictions.parquet", ["model", "race_id"]),
        ("horse_predictions.parquet", ["model", "race_id", "horse_id"]),
    ]:
        old = pl.read_parquet(V8 / filename).filter(pl.col("model") == "HY_R_FORM").sort(keys)
        new = pl.read_parquet(OUT / filename).filter(pl.col("model") == "HY_R_FORM").sort(keys)
        assert old.equals(new.select(old.columns))
    for (name, rid), race in h.partition_by(["model", "race_id"], as_dict=True).items():
        probs = race["pl_place_probability"].to_numpy()
        assert np.isfinite(probs).all() and probs.min() >= -1e-12 and probs.max() <= 1 + 1e-12
        assert abs(probs.sum() - 3) < 1e-10 and race["selected"].sum() == 1
        row = rows[(name, rid)]
        pick = race.filter(pl.col("selected")).row(0, named=True)
        assert row["pick_horse_id"] == pick["horse_id"] and row["pick_hit"] == bool(
            pick["official_top3"]
        )
        assert abs(row["pick_probability"] - pick["pl_place_probability"]) < 1e-12
        assert row["set_hit"] == (
            tuple(sorted(row["predicted_set"])) in {tuple(sorted(o)) for o in truth[rid]}
        )
        assert row["order_hit"] == (tuple(row["predicted_order"]) in set(truth[rid]))
        if name.endswith("_FIXED"):
            ref = rows[("HY_R_FORM", rid)]
            for k in [
                "pick_horse_id",
                "predicted_set",
                "predicted_order",
                "pick_hit",
                "set_hit",
                "order_hit",
            ]:
                assert row[k] == ref[k]
        if name == "C_EXPERIENCE_SELECT":
            assert abs(row["pick_probability"] - probs.max()) < 1e-12
            fixed = rows[("C_EXPERIENCE_FIXED", rid)]
            for k in ["place_brier", "place_logloss", "set_nll", "order_nll"]:
                assert abs(row[k] - fixed[k]) < 1e-12
    rebuilt = 0
    replayed = 0
    for path in sorted((OUT / "bundles").glob("*.pkl")):
        b = pickle.loads(path.read_bytes())
        fold = b["fold"]
        parent = b["parent"]
        split = folds.filter(pl.col("fold_id") == fold)

        def part(role, split=split):
            return frame.join(
                split.filter(pl.col("role") == role).select("race_id"), on="race_id", how="semi"
            ).sort("race_id", "horse_id")

        cal = part("calibration")
        ev = part("evaluation")
        assert cal["event_date"].max() < ev["event_date"].min()
        good = [rid for rid in cal["race_id"].unique() if not meta[rid]["boundary_tie"]]
        cal = cal.filter(pl.col("race_id").is_in(good))
        base, z, layout, _, _ = prepare(cal, truth, parent)
        refit = ExperienceSetCalibrator(
            grouped=protocol["calibrators"][b["model_name"]], **protocol["params"]
        ).fit(base, z, layout, cal["label_top3"].to_numpy())
        assert refit.success_
        np.testing.assert_allclose(refit.theta_, b["calibrator"].theta_, atol=1e-12, rtol=0)
        rebuilt += 1
        eb, ez, el, order, groups = prepare(ev, truth, parent)
        logits = b["calibrator"].predict_logits(eb, ez)
        for name, (calibrator, policy) in protocol["policies"].items():
            if calibrator != b["model_name"]:
                continue
            for j, (lo, hi, _) in enumerate(groups):
                race = ev.slice(lo, hi - lo)
                rid = int(race["race_id"][0])
                ids = race["horse_id"].to_list()
                official = race.filter(pl.col("label_top3") == 1)["horse_id"].to_list()
                result = evaluate_policy(
                    ids,
                    logits[el.set_starts[j] : el.set_ends[j]],
                    order[lo:hi],
                    truth[rid],
                    official,
                    parent["beta_order"],
                    fixed=rows[("HY_R_FORM", rid)] if policy == "fixed" else None,
                )
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
                for k in [
                    "set_nll",
                    "order_nll",
                    "place_brier",
                    "place_logloss",
                    "pick_probability",
                    "set_confidence",
                    "order_confidence",
                ]:
                    assert abs(result[k] - row[k]) < 1e-12, (name, rid, k)
                assert abs(result["set_probability_sum"] - 1) < 1e-10
                assert abs(result["order_probability_sum"] - 1) < 1e-10
                hh = h.filter((pl.col("model") == name) & (pl.col("race_id") == rid)).sort(
                    "horse_id"
                )
                np.testing.assert_allclose(
                    result["pl_marginals"], hh["pl_place_probability"], atol=1e-12, rtol=0
                )
                old = h.filter((pl.col("model") == "HY_R_FORM") & (pl.col("race_id") == rid)).sort(
                    "horse_id"
                )
                np.testing.assert_allclose(order[lo:hi], old["order_score"], atol=1e-12, rtol=0)
                assert parent["beta_order"] == old["beta_order"][0]
        replayed += 1
    ledger = json.loads((OUT / "run_ledger.json").read_text())
    assert ledger["status"] == "complete" and ledger["base_refits"] == 0
    assert ledger["protocol_sha256"] == sha(OUT / "protocol.json")
    assert len(ledger["calibration_fits"]) == 8 and replayed == rebuilt == 8
    assert all(r["status"] == "complete" and r["success"] for r in ledger["calibration_fits"])
    for row in json.loads((OUT / "summary.json").read_text()):
        s = p.filter(pl.col("model") == row["model"])
        nt = s.filter(~pl.col("boundary_tie"))
        assert len(nt) == 709
        for a, b in [
            ("single_hits", "pick_hit"),
            ("set_hits", "set_hit"),
            ("order_hits", "order_hit"),
        ]:
            assert row[a] == s[b].sum()
        for k in ["place_brier", "place_logloss"]:
            assert abs(row[k] - nt[k].mean()) < 1e-12
    ctx = pl.read_parquet(OUT / "audit_context.parquet").sort("race_id", "horse_id")
    ev = frame.filter(pl.col("event_date").dt.year() == 2025).sort("race_id", "horse_id")
    _, bins, missing = design(ev)
    assert len(ctx) == 6953 and ctx["experience_bin"].to_list() == bins
    assert ctx["section_missing"].to_list() == missing
    audit = h.filter(~pl.col("boundary_tie")).join(
        ctx.select("race_id", "horse_id", "experience_bin", "section_missing"),
        on=["race_id", "horse_id"],
        validate="m:1",
    )
    selected = h.filter((pl.col("model") == "HY_R_FORM") & pl.col("selected")).select(
        "race_id", "horse_id"
    )
    groups_checked = 0
    for row in json.loads((OUT / "experience_audit.json").read_text()):
        s = audit.filter(pl.col("model") == row["model"])
        if row["population"] == "baseline_selected":
            s = s.join(selected, on=["race_id", "horse_id"], how="semi")
        dim, val = row["dimension"], row["value"]
        if dim == "distance_experience":
            s = s.filter(pl.col("experience_bin") == val)
        if dim == "section_missing":
            s = s.filter(pl.col("section_missing") == (val == "true"))
        if dim == "experience_x_section":
            exp, miss = val.split("|")
            s = s.filter(
                (pl.col("experience_bin") == exp) & (pl.col("section_missing") == (miss == "true"))
            )
        assert len(s) == row["entries"] and s["event_date"].n_unique() == row["days"]
        if len(s):
            assert (
                abs((s["pl_place_probability"] - s["official_top3"]).mean() - row["overprediction"])
                < 1e-12
            )
            assert row["hits"] == s["official_top3"].sum()
        groups_checked += 1
    contrasts = {
        (r["candidate"], r["reference"]): r
        for r in json.loads((OUT / "paired_comparisons.json").read_text())
    }
    decision = json.loads((OUT / "decision.json").read_text())
    cal = contrasts[("C_EXPERIENCE_FIXED", "HY_R_FORM")]
    sel = contrasts[("C_EXPERIENCE_SELECT", "HY_R_FORM")]
    assert decision["calibration_research_candidate"] == (
        cal["place_brier"]["day_ci"][1] < 0 and cal["place_logloss"]["delta"] <= 0
    )
    assert decision["reselection_candidate"] == (
        sel["set_hit"]["day_ci"][0] > 0
        and sel["pick_hit"]["delta"] >= 0
        and sel["order_hit"]["delta"] >= 0
    )
    assert decision["production_probability_replacement"] is False
    ref = p.filter(pl.col("model") == "HY_R_FORM").sort("race_id").to_dicts()
    new = p.filter(pl.col("model") == "C_EXPERIENCE_SELECT").sort("race_id").to_dicts()
    for change in json.loads((OUT / "policy_changes.json").read_text()):
        key = change["target"]
        col = {"pick": "pick_horse_id", "set": "predicted_set", "order": "predicted_order"}[key]
        hit = key + "_hit"
        assert change["changed"] == sum(a[col] != b[col] for a, b in zip(ref, new, strict=True))
        assert change["lost"] == sum(a[hit] and not b[hit] for a, b in zip(ref, new, strict=True))
        assert change["gained"] == sum(not a[hit] and b[hit] for a, b in zip(ref, new, strict=True))
    result = dict(
        passed=True,
        manifest_files_checked=own,
        parent_files_checked=parents,
        calibration_fits_rebuilt=rebuilt,
        replayed_bundles=replayed,
        models=4,
        common_races=715,
        probability_races=709,
        group_audits_checked=groups_checked,
        unchanged_reference=True,
        unchanged_order_head=True,
        fixed_actions_preserved=True,
        policy_probabilities_equal=True,
        predictions_2026=0,
    )
    save("verification.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
