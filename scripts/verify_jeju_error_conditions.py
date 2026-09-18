"""Verify source lineage, timing, pair labels and frozen score explanations."""

import json
import pickle
import sqlite3
from bisect import bisect_right
from datetime import date, timedelta

import numpy as np
import polars as pl

from horse_racing.analysis.jeju_context_features import parse_body_weight, parse_track_moisture
from horse_racing.analysis.jeju_error_conditions import changed, delta, flags, rank_quality
from scripts.audit_jeju_error_conditions import (
    DATA,
    DB,
    METRICS,
    OUT,
    ROOT,
    V5,
    V8,
    paired_stats,
    save,
    sha,
)
from scripts.diagnose_jeju_grade_transitions import grade
from scripts.run_jeju_trial_experiment import data_frame


def same(a, b):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) < 1e-10 if isinstance(a, (int, float)) else a == b


def main():
    p = json.loads((OUT / "protocol.json").read_text())
    checked = {}
    for folder, digest in p["parents"].items():
        directory = ROOT / folder
        assert sha(directory / "manifest.json") == digest
        m = json.loads((directory / "manifest.json").read_text())
        hashes = {k: v["sha256"] for k, v in m["files"].items()} if "files" in m else m
        for name, value in hashes.items():
            assert sha(directory / name) == value, (folder, name)
        checked[folder] = len(hashes)
    assert sha(DB) == p["database_sha256"]
    own = 0
    if (OUT / "manifest.json").exists():
        for name, value in json.loads((OUT / "manifest.json").read_text()).items():
            assert sha(OUT / name) == value, name
            own += 1
    entries = pl.read_parquet(DATA / "entries.parquet").filter(
        pl.col("event_date").dt.year() <= 2025
    )
    e = {r["entry_id"]: r for r in entries.iter_rows(named=True)}
    history = {}
    for r in entries.sort("event_date", "entry_id").iter_rows(named=True):
        history.setdefault(r["horse_id"], []).append((r["event_date"], r["entry_id"]))
    evidence = {
        r["entry_id"]: r
        for r in [json.loads(s) for s in (OUT / "source_evidence.jsonl").read_text().splitlines()]
    }
    raw = {eid: json.loads(r["normalized_json"]) for eid, r in evidence.items()}
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    for eid, r in evidence.items():
        src = dict(
            c.execute(
                "select e.source_row_id,s.normalized_json,s.row_sha256,s.line_number from entry e join source_row s on s.id=e.source_row_id where e.id=?",  # noqa: E501
                (eid,),
            ).fetchone()
        )
        assert all(r[k] == v for k, v in src.items())
    c.close()
    protocol = json.loads((V5 / "protocol.json").read_text())
    frame, meta, truth, folds = data_frame(protocol)
    fm = {r["entry_id"]: r for r in frame.iter_rows(named=True)}
    rframe = pl.read_parquet(OUT / "entry_conditions.parquet")
    records = rframe.to_dicts()
    assert len(records) == 6953 and rframe["entry_id"].n_unique() == 6953
    assert len(rframe.filter(~pl.col("boundary_tie"))) == 6894
    assert all(r["event_date"].startswith("2025") for r in records)
    hp = pl.read_parquet(V5 / "horse_predictions.parquet").filter(pl.col("model") == "HY_R_FORM")
    hm = {(r["race_id"], r["horse_id"]): r for r in hp.iter_rows(named=True)}
    pred = {
        r["race_id"]: r
        for r in pl.read_parquet(V5 / "race_predictions.parquet")
        .filter(pl.col("model") == "HY_R_FORM")
        .iter_rows(named=True)
    }
    for r in records:
        eid = r["entry_id"]
        src = raw[eid]
        f = fm[eid]
        cutoff = date.fromisoformat(r["event_date"]) - timedelta(days=2)
        candidates = history[r["horse_id"]]
        index = bisect_right(candidates, (cutoff, float("inf")))
        prev = candidates[index - 1][1] if index else None
        assert prev == r["previous_entry_id"]
        old = raw[prev] if prev else {}
        assert r["cutoff_date"] == str(cutoff)
        assert same(
            r["pre_distance_change_m"],
            delta(f["distance_m"], e[prev]["distance_m"] if prev else None),
        )
        assert same(r["pre_burden_change_kg"], delta(f["declared_burden_kg"], old.get("wgBudam")))
        assert same(r["pre_jockey_changed"], changed(r["pre_declared_jockey"], old.get("jkName")))
        assert same(r["post_bodyweight_kg"], parse_body_weight(src.get("wgHr")))
        assert same(
            r["post_bodyweight_change_kg"],
            delta(parse_body_weight(src.get("wgHr")), parse_body_weight(old.get("wgHr"))),
        )
        assert same(
            r["post_moisture_change_pp"],
            delta(parse_track_moisture(src.get("track")), parse_track_moisture(old.get("track"))),
        )
        assert r["post_early_rank"] == src["sjS1fOrd"] or r["post_early_rank"] is None
        assert r["post_g1_rank"] == src["sjG1fOrd"] or r["post_g1_rank"] is None
        assert same(
            r["post_early_vs_history"],
            delta(rank_quality(src["sjS1fOrd"], r["field_size"]), f["early_rank_percentile_3"]),
        )
        assert same(
            r["post_closing_vs_history"],
            delta(r["post_closing_quality"], f["closing_speed_quality_mean_3"]),
        )
        assert all(same(r[k], v) for k, v in flags(r).items())
        assert r["selected"] == (r["horse_id"] in pred[r["race_id"]]["predicted_set"])
        assert r["official_top3"] == bool(hm[(r["race_id"], r["horse_id"])]["official_top3"])
        assert same(r["score"], hm[(r["race_id"], r["horse_id"])]["score"])
    lookup = {r["entry_id"]: r for r in records}
    pairs = pl.read_parquet(OUT / "paired_conditions.parquet").to_dicts()
    oldpairs = pl.read_parquet(V8 / "missing_horse_pairs.parquet")
    assert len(pairs) == 332 and {r["race_id"] for r in pairs} == set(oldpairs["race_id"])
    for r in pairs:
        assert not meta[r["race_id"]]["boundary_tie"]
        assert lookup[r["missed_entry_id"]]["role"] == "missed_podium"
        assert lookup[r["selected_entry_id"]]["role"] == "selected_miss"
        for prefix, key in [("missed", "missed_entry_id"), ("selected", "selected_entry_id")]:
            for k, v in lookup[r[key]].items():
                assert same(r[prefix + "__" + k], v), (k, r["race_id"])
        assert abs(r["score_margin"] - (r["selected__score"] - r["missed__score"])) < 1e-12
    columns = list(dict.fromkeys(list(METRICS) + list(flags({}))))
    stats = paired_stats(pairs, columns)
    stored = json.loads((OUT / "paired_statistics.json").read_text())
    assert len(stats) == len(stored) == len(columns)
    for a, b in zip(stats, stored, strict=True):
        for k in a:
            if isinstance(a[k], list):
                np.testing.assert_allclose(a[k], b[k], atol=1e-12, rtol=0)
            else:
                assert same(a[k], b[k]), k
    contributions = pl.read_parquet(OUT / "score_contribution_pairs.parquet")
    pid = {r["missed_entry_id"] for r in pairs} | {r["selected_entry_id"] for r in pairs}
    recomputed = {}
    for fold in sorted(folds["fold_id"].unique()):
        bundle = pickle.loads((V5 / "bundles" / f"{fold}__R_FORM.pkl").read_bytes())
        ids = folds.filter((pl.col("fold_id") == fold) & (pl.col("role") == "evaluation")).select(
            "race_id"
        )
        ev = (
            frame.join(ids, on="race_id", how="semi")
            .filter(pl.col("entry_id").is_in(pid))
            .sort("entry_id")
        )
        x = bundle["preprocessor"].transform(ev)
        values = np.mean([m.predict(x, pred_contrib=True) for m in bundle["models"]], axis=0)
        rawscore = np.mean([m.predict(x, raw_score=True) for m in bundle["models"]], axis=0)
        np.testing.assert_allclose(values.sum(axis=1), rawscore, atol=1e-10, rtol=0)
        for i, eid in enumerate(ev["entry_id"]):
            recomputed[eid] = dict(zip(bundle["preprocessor"].names, values[i, :-1], strict=True))
    for pair in pairs:
        a = recomputed[pair["missed_entry_id"]]
        b = recomputed[pair["selected_entry_id"]]
        saved = contributions.filter(pl.col("race_id") == pair["race_id"])
        assert len(saved) == len(a) == len(b)
        for r in saved.iter_rows(named=True):
            assert abs(r["missed_minus_selected"] - (a[r["feature"]] - b[r["feature"]])) < 1e-12
        assert abs(saved["missed_minus_selected"].sum() + pair["score_margin"]) < 1e-10
    for row in json.loads((OUT / "full_population_condition_rates.json").read_text()):
        selected = row["population"]
        s = rframe.filter(~pl.col("boundary_tie"))
        if selected != "all":
            s = s.filter(pl.col("selected") == (selected == "selected3"))
        s = s.filter(
            pl.col(row["condition"]).is_null()
            if row["value"] is None
            else pl.col(row["condition"]) == row["value"]
        )
        assert len(s) == row["entries"]
        assert same(float(s["official_top3"].mean()) if len(s) else None, row["observed_rate"])
    assert (OUT / "all_332_cases.md").read_text().count("\n## ") == 332
    grade_frame = pl.read_parquet(OUT / "grade_conditions.parquet")
    grade_rows = {r["entry_id"]: r for r in grade_frame.iter_rows(named=True)}
    assert len(grade_rows) == 6953
    for r in records:
        g = grade_rows[r["entry_id"]]
        current = grade(evidence[r["entry_id"]]["grade"])
        previous = grade(evidence.get(r["previous_entry_id"], {}).get("grade"))
        comparable = bool(
            r["previous_date"]
            and r["previous_date"].startswith("2025")
            and current is not None
            and previous is not None
        )
        assert comparable == g["comparable_2025"]
        assert g["grade6_to5"] == (float(previous == 6 and current == 5) if comparable else None)
    gdiag = json.loads((OUT / "grade_transition_diagnostic.json").read_text())
    gp = []
    for pair in pairs:
        row = {"event_date": pair["event_date"]}
        for prefix, key in [("missed", "missed_entry_id"), ("selected", "selected_entry_id")]:
            for metric in ["grade6_to5", "grade_number_decrease", "grade_number_increase"]:
                row[prefix + "__" + metric] = grade_rows[pair[key]][metric]
        gp.append(row)
    assert (
        paired_stats(gp, ["grade6_to5", "grade_number_decrease", "grade_number_increase"])
        == gdiag["paired"]
    )
    gj = rframe.join(
        grade_frame.select("entry_id", "grade6_to5"), on="entry_id", validate="1:1"
    ).filter(~pl.col("boundary_tie"))
    for row in gdiag["full_population"]:
        part = gj.filter(pl.col("grade6_to5") == row["grade6_to5"])
        if row["population"] != "all":
            part = part.filter(pl.col("selected") == (row["population"] == "selected3"))
        assert len(part) == row["entries"]
        assert same(float(part["official_top3"].mean()), row["observed_rate"])
        assert same(float(part["place_probability"].mean()), row["mean_probability"])
        daily = (
            part.group_by("event_date")
            .agg(
                (pl.col("place_probability") - pl.col("official_top3").cast(pl.Float64))
                .sum()
                .alias("error"),
                pl.len().alias("n"),
            )
            .sort("event_date")
        )
        draws = np.random.default_rng(17).integers(0, len(daily), (5000, len(daily)))
        boot = daily["error"].to_numpy()[draws].sum(axis=1) / daily["n"].to_numpy()[draws].sum(
            axis=1
        )
        np.testing.assert_allclose(
            np.quantile(boot, [0.025, 0.975]), row["bias_day_ci"], atol=1e-12, rtol=0
        )
    choices = json.loads((OUT / "case_selection.json").read_text())
    assert [r["race_id"] for r in choices if r["reason"] == "top6_score_margin"] == [
        r["race_id"] for r in sorted(pairs, key=lambda r: (-r["score_margin"], r["race_id"]))[:6]
    ]
    result = dict(
        passed=True,
        manifest_files_checked=own,
        parent_files_checked=checked,
        entry_rows_verified=len(records),
        paired_races_verified=len(pairs),
        source_evidence_rows_verified=len(evidence),
        model_contribution_rows_verified=len(contributions),
        paired_statistics_rebuilt=len(stats),
        grade_supplement_verified=True,
        fits=0,
        predictions_changed=0,
        predictions_2026=0,
        actual_race_causes_proven=False,
    )
    save("verification.json", result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
