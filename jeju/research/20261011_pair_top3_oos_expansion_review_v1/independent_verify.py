"""Independent, fit-free verification of the expanded pair study outputs.

Uses the pinned direct-review NumPy reference only. Replays stored LightGBM
models with predict(), evaluates saved H1/H2 objectives and gradients, and
reconstructs evaluation predictions and the original date-bootstrap metrics.
It never calls a model fitter, optimizer, or writes outside this review folder.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
REVIEW = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_review_v1"
OUT = STUDY / "outputs"
DIRECT = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
STYLE_OUT = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs"
REFERENCE = ROOT / "jeju/research/20261011_pair_top3_direct_review_v1/independent_reference.py"
MANIFEST = STUDY / "ARTIFACT_MANIFEST.json"
RECEIPT = REVIEW / "INDEPENDENT_REVIEW_RECEIPT.json"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def need(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)


def close(a, b, tol=2e-12) -> bool:
    return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a) - float(b)) <= tol


spec = importlib.util.spec_from_file_location("pinned_pair_independent_reference", REFERENCE)
ref = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ref
spec.loader.exec_module(ref)


def runner_stats(row):
    d = row["runner_standardization"]
    names = ref.RUNNER_COLUMNS
    return ref.RunnerMoments(
        names,
        np.array([d[n]["mean"] for n in names], float),
        np.array([d[n]["scale"] for n in names], float),
        tuple(bool(d[n]["degenerate"]) for n in names),
        tuple(float(d[n]["support_weight"]) for n in names),
    )


def pair_stats(row):
    d = row["pair_standardization"]
    names = ref.BASIS_NAMES
    return ref.PairMoments(
        np.array([d[n]["mean"] for n in names], float),
        np.array([d[n]["scale"] for n in names], float),
        tuple(bool(d[n]["degenerate"]) for n in names),
        tuple(float(d[n]["support_weight"]) for n in names),
    )


def build_races(frame, rm, pm=None):
    result = []
    for race_id, g in frame.groupby("race_id", sort=True):
        g = g.sort_values("horse_number", kind="stable").reset_index(drop=True)
        vals = {name: g[name].to_numpy(float) for name in ref.RUNNER_COLUMNS}
        z, missing = ref.transform_runner_values(vals, rm)
        pairs, basis = ref.race_pair_matrix(g.horse_number.to_numpy(int), z, missing)
        _, p0, _ = ref.exact_top3_pair_prior(g.horse_number.to_numpy(int), g.score.to_numpy(float))
        labels = ref.pair_label(
            dict(zip(g.horse_number.astype(int), g.finish_position.astype(int), strict=True)), pairs
        )
        if pm is not None:
            basis = ref.apply_pair_moments(basis, pm)
        result.append({
            "race_id": str(race_id), "race_date": g.race_date.iloc[0].date().isoformat(),
            "race": g, "pairs": pairs, "basis": basis, "p0": p0, "labels": labels,
        })
    return result


def source_join(features, source):
    path = ROOT / source["source_path"]
    score = pd.read_parquet(path)
    rows = features.loc[features.year.eq(int(source["race_year"]))].copy()
    need(score.api_record_id.is_unique and set(score.api_record_id) == set(rows.api_record_id),
         f"historical score coverage/key mismatch: {source['race_year']}")
    joined = rows.merge(score, on="api_record_id", how="left", validate="one_to_one")
    need(joined.score.notna().all(), f"historical score join missing: {source['race_year']}")
    meta = json.loads((ROOT / source["meta_path"]).read_text())
    need(sha(path) == source["source_sha256"] and sha(ROOT / source["meta_path"]) == source["meta_sha256"],
         f"historical provider source hash changed: {source['race_year']}")
    refit_max = pd.Timestamp(meta["refit_max"]).normalize()
    need(((joined.race_date.dt.normalize() - pd.Timedelta(days=2)) >= refit_max).all(),
         f"historical provider T-2 violation: {source['race_year']}")
    return joined


def replay_saved_historical_models(manifest, hist_receipt):
    frame = pd.read_parquet(FEATURES)
    need(len(frame) == 52155 and frame.api_record_id.is_unique, "frozen feature inventory changed")
    results = []
    for row in hist_receipt["folds"]:
        fold = int(row["fold"])
        folder = OUT / f"F1_STYLE6_{fold}"
        meta = json.loads((folder / "meta.json").read_text())
        model_path = folder / "top3.txt"
        score_path = folder / "calibration_scores.parquet"
        need(sha(model_path) == row["model_sha256"], f"historical model hash changed: {fold}")
        need(sha(score_path) == row["calibration_scores_sha256"], f"historical score hash changed: {fold}")
        cal = frame.loc[frame.year.eq(fold - 1)].copy().reset_index(drop=True)
        x = cal[meta["features"]].copy()
        for column, vocab in meta["vocabulary"].items():
            x[column] = pd.Categorical(x[column].astype("string"), categories=vocab)
        model = lgb.Booster(model_file=str(model_path))
        score = model.predict(x, raw_score=True, num_threads=4)
        saved = pd.read_parquet(score_path)
        replay = pd.DataFrame({"api_record_id": cal.api_record_id, "score": score})
        compared = replay.merge(saved, on="api_record_id", how="outer", validate="one_to_one", suffixes=("_replay", "_saved"), indicator=True)
        need(compared._merge.eq("both").all(), f"historical replay key coverage mismatch: {fold}")
        delta = float(np.max(np.abs(compared.score_replay.to_numpy(float) - compared.score_saved.to_numpy(float))))
        need(delta == 0.0, f"historical saved-model score replay differs: {fold}: {delta}")
        results.append({"provider_fold": fold, "calibration_year": fold - 1,
                        "rows": len(saved), "races": int(cal.race_id.nunique()),
                        "max_abs_score_delta": delta, "model_sha256": sha(model_path),
                        "score_sha256": sha(score_path)})
    return results


def independent_fit_gradients(features, h1, h2):
    fold_map = {int(row["evaluation_year"]): row for row in h1["folds"]}
    maps = {(int(row["evaluation_year"]), row["map"]): row for row in h2["fold_maps"]}
    summary = []
    for eval_year, fit in fold_map.items():
        cal_year = int(fit["calibration_year"])
        sources = fit["h1_sources"]
        by_year = {int(src["race_year"]): source_join(features, src) for src in sources}
        h2source = next(src for src in sources if int(src["race_year"]) == cal_year)
        h2full = by_year[cal_year]
        h2_dates = h2full.loc[h2full.race_date.dt.month.ge(7)].copy()
        first_h2 = h2_dates.race_date.min().normalize()
        cutoff = first_h2 - pd.Timedelta(days=2)
        h1parts = [by_year[y] for y in sorted(by_year) if y != cal_year]
        current = h2full.loc[h2full.race_date.dt.month.le(6) & h2full.race_date.dt.normalize().le(cutoff)].copy()
        h1parts.append(current)
        h1frame = pd.concat(h1parts, ignore_index=True)
        h2frame = h2_dates
        need(h1frame.api_record_id.is_unique and h2frame.api_record_id.is_unique, f"fit source duplicate runner {eval_year}")
        need(h1frame.race_date.max().normalize() <= cutoff, f"H1/H2 T-2 boundary failure {eval_year}")
        rm = ref.fit_runner_moments({n: h1frame[n].to_numpy(float) for n in ref.RUNNER_COLUMNS}, h1frame.race_id.astype(str).to_numpy())
        h1r = build_races(h1frame, rm)
        pm = ref.fit_pair_moments([r["basis"] for r in h1r])
        saved_rm = runner_stats(fit)
        saved_pm = pair_stats(fit)
        need(np.allclose(rm.mean, saved_rm.mean, rtol=0, atol=1e-12)
             and np.allclose(rm.scale, saved_rm.scale, rtol=0, atol=1e-12)
             and rm.degenerate == saved_rm.degenerate
             and np.allclose(rm.support_weight, saved_rm.support_weight, rtol=0, atol=1e-12),
             f"independent H1 runner moments differ from saved fit: {eval_year}")
        need(np.allclose(pm.mean, saved_pm.mean, rtol=0, atol=1e-12)
             and np.allclose(pm.scale, saved_pm.scale, rtol=0, atol=1e-12)
             and pm.degenerate == saved_pm.degenerate
             and np.allclose(pm.support_weight, saved_pm.support_weight, rtol=0, atol=1e-12),
             f"independent H1 pair moments differ from saved fit: {eval_year}")
        standardized = [ref.apply_pair_moments(r["basis"], pm) for r in h1r]
        beta = np.array([fit["beta_by_basis"][n] for n in ref.BASIS_NAMES], float)
        obj, grad = ref.h1_objective_gradient(beta, standardized, [r["p0"] for r in h1r], [r["labels"] for r in h1r])
        need(len(h1r) == int(fit["h1_races"]), f"H1 race count mismatch {eval_year}")
        need(close(obj, fit["objective"], 3e-13), f"H1 objective mismatch {eval_year}")
        need(np.max(np.abs(grad - np.array(fit["gradient"], float))) < 5e-13, f"H1 gradient mismatch {eval_year}")

        h2r = build_races(h2frame, rm, pm)
        need(len(h2r) == int(maps[(eval_year, "candidate")]["h2_races"]), f"H2 race count mismatch {eval_year}")
        raw_by_race = []
        candidate_by_race = []
        labels_by_race = []
        for race in h2r:
            x = race["basis"]
            off = ref.logit(race["p0"])
            raw_by_race.append(off)
            candidate_by_race.append(off + x @ beta)
            labels_by_race.append(race["labels"])
        h2_checks = {}
        for map_name, raw in (("candidate", candidate_by_race), ("baseline", raw_by_race)):
            row = maps[(eval_year, map_name)]
            objective, gradient = ref.platt_objective_gradient((row["A"], row["B"]), raw, labels_by_race)
            need(close(objective, row["objective"], 3e-13), f"H2 objective mismatch {eval_year}/{map_name}")
            need(np.max(np.abs(gradient - np.array(row["gradient"], float))) < 5e-12,
                 f"H2 gradient mismatch {eval_year}/{map_name}")
            h2_checks[map_name] = {"objective_abs_delta": abs(objective - row["objective"]),
                                    "gradient_inf_norm": float(np.max(np.abs(gradient)))}
        summary.append({"evaluation_year": eval_year, "h1_races": len(h1r),
                        "h1_objective_abs_delta": abs(obj - fit["objective"]),
                        "h1_gradient_inf_delta": float(np.max(np.abs(grad - np.array(fit["gradient"], float)))),
                        "h2": h2_checks})
    return summary


def independent_eval_predictions(features, h1, h2):
    fitrows = {int(x["evaluation_year"]): x for x in h1["folds"]}
    maps = {(int(x["evaluation_year"]), x["map"]): x for x in h2["fold_maps"]}
    predicted = []
    eval_sources = []
    for year in (2024, 2025, 2026):
        rows = features.loc[features.year.eq(year)].copy()
        scorepath = STYLE_OUT / f"F1_STYLE6_{year}/evaluation_scores.parquet"
        score = pd.read_parquet(scorepath)
        need(score.api_record_id.is_unique and set(score.api_record_id) == set(rows.api_record_id),
             f"evaluation score key coverage changed: {year}")
        rows = rows.merge(score, on="api_record_id", how="left", validate="one_to_one")
        need(rows.score.notna().all(), f"evaluation score missing: {year}")
        meta = json.loads((STYLE_OUT / f"F1_STYLE6_{year}/meta.json").read_text())
        need(((rows.race_date.dt.normalize() - pd.Timedelta(days=2)) >= pd.Timestamp(meta["refit_max"]).normalize()).all(),
             f"evaluation refit T-2 violation: {year}")
        fit = fitrows[year]; rm = runner_stats(fit); pm = pair_stats(fit)
        beta = np.array([fit["beta_by_basis"][n] for n in ref.BASIS_NAMES], float)
        cmap = maps[(year, "candidate")]; bmap = maps[(year, "baseline")]
        for rid, g in rows.groupby("race_id", sort=True):
            g = g.sort_values("horse_number", kind="stable").reset_index(drop=True)
            vals = {n: g[n].to_numpy(float) for n in ref.RUNNER_COLUMNS}
            pred = ref.produce_race_predictions(g.horse_number.to_numpy(int), g.score.to_numpy(float), vals,
                rm, pm, beta, (cmap["A"], cmap["B"]), (bmap["A"], bmap["B"]))
            finish = dict(zip(g.horse_number.astype(int), g.finish_position.astype(int), strict=True))
            labels = ref.pair_label(finish, pred["pairs"])
            for i, (a, b) in enumerate(pred["pairs"]):
                predicted.append({"race_id": str(rid), "race_date": g.race_date.iloc[0].date().isoformat(),
                    "evaluation_year": year, "distance_m": int(g.distance_m.iloc[0]), "horse_i": a, "horse_j": b,
                    "score_i": float(g.loc[g.horse_number.eq(a), "score"].iloc[0]),
                    "score_j": float(g.loc[g.horse_number.eq(b), "score"].iloc[0]),
                    "p0": float(pred["p0"][i]), "eta": float(pred["eta"][i]),
                    "candidate_raw_probability": float(pred["candidate_raw_probability"][i]),
                    "candidate_calibrated_probability": float(pred["candidate_calibrated_probability"][i]),
                    "baseline_calibrated_probability": float(pred["baseline_calibrated_probability"][i]),
                    "selected_candidate": int(pred["pairs"][i] == pred["candidate_pair"]),
                    "selected_baseline": int(pred["pairs"][i] == pred["baseline_pair"]),
                    "y_pair": int(labels[i])})
        eval_sources.append({"year": year, "score_sha256": sha(scorepath), "refit_max": meta["refit_max"]})
    return pd.DataFrame(predicted), eval_sources


def compare_report_and_bootstrap(pred, old, report):
    schedule_path = DIRECT / "outputs/date_bootstrap_schedule.npy"
    schedule_hash = sha(schedule_path)
    need(schedule_hash == "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
         "original bootstrap schedule hash changed")
    schedule = np.load(schedule_path, allow_pickle=False)
    dates = sorted(pred.race_date.astype(str).unique())
    need(schedule.shape == (2000, 269) and schedule.dtype == np.int32, "bootstrap shape or dtype changed")
    meta = json.loads((DIRECT / "outputs/date_bootstrap_schedule.json").read_text())
    need(meta["schedule_sha256"] == schedule_hash and meta["schedule_shape"] == [2000, 269],
         "bootstrap schedule receipt mismatch")
    need(meta["date_inventory_sha256"] == hashlib.sha256("\n".join(dates).encode()).hexdigest(),
         "bootstrap race-date inventory changed")

    keys = ["race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j"]
    need(pred.groupby("race_id").size().sum() == 76848 and not pred.duplicated(keys).any(), "independent expected pair keys invalid")
    need(old.race_id.nunique() == 1779 and len(old) == 76848, "old frozen evaluation table changed")
    direct = pd.read_parquet(OUT / "evaluation_pair_predictions.parquet")
    joined = direct.merge(pred, on=keys, how="outer", validate="one_to_one", indicator=True, suffixes=("", "_ind"))
    need(joined._merge.eq("both").all() and len(joined) == 76848, "expanded prediction key coverage mismatch")
    max_delta = {}
    for col in ("score_i", "score_j", "p0", "eta", "candidate_raw_probability", "candidate_calibrated_probability", "baseline_calibrated_probability"):
        delta = np.abs(joined[col].to_numpy(float) - joined[col + "_ind"].to_numpy(float))
        max_delta[col] = float(delta.max())
        need(max_delta[col] <= 2e-13, f"independent prediction differs in {col}: {max_delta[col]}")
    for col in ("selected_candidate", "selected_baseline", "y_pair"):
        need(np.array_equal(joined[col].to_numpy(int), joined[col + "_ind"].to_numpy(int)), f"independent {col} mismatch")

    # Fixed old score, probabilities, labels, and all non-direct selectors must be unchanged.
    keymerge = old.merge(direct, on=keys, how="outer", validate="one_to_one", indicator=True, suffixes=("_old", "_new"))
    need(keymerge._merge.eq("both").all(), "old/new key coverage mismatch")
    fixed_binary = ["y_pair", "selected_baseline", "selected_raw_top2", "selected_saved_f1_top2",
                    "selected_candidate_joint_marginal_top2", "selected_candidate_joint_maxpair", "selected_matched_joint_maxpair"]
    for c in fixed_binary:
        need(np.array_equal(keymerge[c + "_old"].to_numpy(), keymerge[c + "_new"].to_numpy()), f"fixed comparator changed: {c}")
    for c in ("score_i", "score_j", "p0", "baseline_calibrated_probability"):
        need(np.array_equal(keymerge[c + "_old"].to_numpy(float), keymerge[c + "_new"].to_numpy(float)), f"fixed value changed: {c}")
    need(np.array_equal(keymerge.selected_candidate_old.to_numpy(int), keymerge.selected_old_direct.to_numpy(int)), "old direct selector alias changed")
    need(np.array_equal(keymerge.candidate_calibrated_probability_old.to_numpy(float), keymerge.old_direct_candidate_calibrated_probability.to_numpy(float)), "old direct probability alias changed")

    raw_pick = {}
    for race_id, group in direct.groupby("race_id", sort=False):
        pairs = list(zip(group.horse_i.astype(int), group.horse_j.astype(int), strict=True))
        score_sums = group.score_i.to_numpy(float) + group.score_j.to_numpy(float)
        raw_pick[str(race_id)] = ref.choose_pair(pairs, score_sums)
    raw_flags = direct.apply(
        lambda row: int((int(row.horse_i), int(row.horse_j)) == raw_pick[str(row.race_id)]), axis=1
    ).to_numpy(int)
    need(np.array_equal(raw_flags, direct.selected_raw_top2.to_numpy(int)), "raw score Top2 selector differs from independent max-score-pair rule")

    policies = {
        "direct_pair_model": "selected_candidate", "old_direct_pair_model": "selected_old_direct",
        "H2_calibrated_p0_baseline": "selected_baseline", "raw_F1_STYLE6_score_Top2": "selected_raw_top2",
        "saved_F1_STYLE6_PTop3_Top2": "selected_saved_f1_top2",
        "existing_candidate_joint_marginal_Top2": "selected_candidate_joint_marginal_top2",
        "existing_candidate_maximum_joint_pair": "selected_candidate_joint_maxpair",
        "existing_matched_maximum_joint_pair": "selected_matched_joint_maxpair",
    }
    race = direct[["race_id", "race_date", "evaluation_year", "distance_m"]].drop_duplicates().sort_values("race_id").reset_index(drop=True)
    for policy, selector in policies.items():
        selected = direct.loc[direct[selector].eq(1), ["race_id", "y_pair"]]
        need(len(selected) == 1779 and selected.race_id.is_unique, f"selector not one-per-race: {policy}")
        race = race.merge(selected.rename(columns={"y_pair": policy}), on="race_id", validate="one_to_one")
    need((direct.groupby("race_id").y_pair.sum() == 3).all(), "non-three-positive pair label race")
    date_index = {d: i for i, d in enumerate(dates)}

    def ci(frame, values):
        x = np.asarray(values, float)
        idx = frame.race_date.astype(str).map(date_index).to_numpy(int)
        sums = np.bincount(idx, weights=x, minlength=len(dates))
        counts = np.bincount(idx, minlength=len(dates)).astype(float)
        denominators = counts[schedule].sum(axis=1)
        numerators = sums[schedule].sum(axis=1)
        valid = denominators > 0
        return {"estimate": float(x.mean()), "ci_low": float(np.quantile(numerators[valid] / denominators[valid], .025)),
                "ci_high": float(np.quantile(numerators[valid] / denominators[valid], .975)),
                "valid_draws": int(valid.sum()), "undefined_draws": int((~valid).sum())}

    rates = {p: {"hits": int(race[p].sum()), "races": len(race), "hit_rate": float(race[p].mean())} for p in policies}
    diffs = {}
    for p in policies:
        if p != "direct_pair_model":
            diffs[p] = ci(race, race.direct_pair_model.to_numpy(float) - race[p].to_numpy(float))
    rep_rates = report["pair_hit_rate_by_policy"]
    need(rates.keys() == rep_rates.keys(), "report policy set changed")
    for p, v in rates.items():
        need(v["hits"] == rep_rates[p]["hits"] and v["races"] == rep_rates[p]["races"] and close(v["hit_rate"], rep_rates[p]["hit_rate"], 1e-15), f"hit rate mismatch {p}")
    for p, v in diffs.items():
        rv = report["paired_date_cluster_differences_direct_minus_comparator"][p]
        need(all(close(v[k], rv[kk], 2e-14) for k, kk in (("estimate", "estimate"), ("ci_low", "ci_low"), ("ci_high", "ci_high"))), f"date CI mismatch {p}")
        need(v["valid_draws"] == rv["valid_draws"] == 2000 and v["undefined_draws"] == rv["undefined_draws"] == 0, f"date CI draw counts mismatch {p}")

    sum_probability_checks = {}
    for label, column in (("candidate", "candidate_calibrated_probability"), ("baseline", "baseline_calibrated_probability")):
        deviation = direct.groupby("race_id", sort=True)[column].sum() - 3.0
        absolute = deviation.abs()
        actual = {"races": len(deviation), "signed_mean": float(deviation.mean()),
                  "signed_median": float(deviation.median()), "absolute_mean": float(absolute.mean()),
                  "absolute_median": float(absolute.median()), "absolute_p95": float(np.quantile(absolute, .95)),
                  "absolute_max": float(absolute.max())}
        saved = report["sum_pair_probability_minus_three_diagnostics"][label]
        need(actual["races"] == saved["races"] and all(close(actual[k], saved[k], 2e-12) for k in actual if k != "races"),
             f"pair-marginal probability sum diagnostics mismatch: {label}")
        sum_probability_checks[label] = actual

    candidate = direct.loc[direct.selected_candidate.eq(1)].set_index("race_id")
    raw = direct.loc[direct.selected_raw_top2.eq(1)].set_index("race_id")
    changed = candidate.horse_i.ne(raw.horse_i) | candidate.horse_j.ne(raw.horse_j)
    delta = race.direct_pair_model.astype(int) - race.raw_F1_STYLE6_score_Top2.astype(int)
    change = {"races_with_pair_changed_vs_raw_top2": int(changed.sum()),
              "gains_on_changed_races": int(((delta == 1) & race.race_id.isin(changed[changed].index)).sum()),
              "losses_on_changed_races": int(((delta == -1) & race.race_id.isin(changed[changed].index)).sum()),
              "ties_on_changed_races": int(((delta == 0) & race.race_id.isin(changed[changed].index)).sum())}
    need(change == report["selection_change_vs_raw_score_top2"], "raw-relative selector change summary mismatch")
    primary = diffs["raw_F1_STYLE6_score_Top2"]
    expected_gate = rates["direct_pair_model"]["hit_rate"] > rates["raw_F1_STYLE6_score_Top2"]["hit_rate"] and primary["ci_low"] > 0
    need(report["primary_gate"]["passed"] is expected_gate and not expected_gate, "primary gate mismatch")

    # Independently recompute race-equal probability quality for all-pair and selected rows.
    probability_replay = {}
    for label, pcol, selector in (("candidate", "candidate_calibrated_probability", "selected_candidate"),
                                  ("baseline", "baseline_calibrated_probability", "selected_baseline"),
                                  ("old_direct", "old_direct_candidate_calibrated_probability", "selected_old_direct")):
        grouped = [g for _, g in direct.groupby("race_id", sort=True)]
        pp = [g[pcol].to_numpy(float) for g in grouped]
        yy = [g.y_pair.to_numpy(float) for g in grouped]
        allm = ref.race_equal_pair_metrics(pp, [ref.logit(x) for x in pp], yy)
        chosen = direct.loc[direct[selector].eq(1)].sort_values("race_id")
        sm = ref.race_equal_pair_metrics([np.array([x]) for x in chosen[pcol].to_numpy(float)],
            [ref.logit([x]) for x in chosen[pcol].to_numpy(float)], [np.array([x]) for x in chosen.y_pair.to_numpy(float)])
        rel = ref.reliability_bins(pp, yy, selected=False)
        chosen_by_race = [g for _, g in chosen.groupby("race_id", sort=True)]
        rel_selected = ref.reliability_bins([g[pcol].to_numpy(float) for g in chosen_by_race],
                                             [g.y_pair.to_numpy(float) for g in chosen_by_race], selected=True)
        probability_replay[label] = {"all_pair": allm, "selected_pair": sm,
                                     "all_pair_reliability": rel, "selected_pair_reliability": rel_selected}
        target = report["probability_quality_separate_diagnostics"][label]
        for loc, actual in (("all_pair", allm), ("selected_pair", sm)):
            for key in ("brier", "log_loss", "races"):
                need(close(actual[key], target[loc][key], 2e-13), f"probability metric mismatch {label}/{loc}/{key}")
        for loc, actual, reportkey in (("all_pair_reliability", rel, "all_pair_reliability"),
                                       ("selected_pair_reliability", rel_selected, "selected_pair_reliability")):
            saved = target[reportkey]
            need(len(actual) == len(saved), f"reliability bins differ {label}/{loc}")
            fieldmap = (("pairs", "pairs"), ("races", "races"), ("mean_prediction", "predicted"),
                        ("observed_rate", "observed"), ("weight_sum", "total_weight"))
            for a, b in zip(actual, saved, strict=True):
                for src, dst in fieldmap:
                    if a[src] is None or b[dst] is None:
                        need(a[src] is None and b[dst] is None, f"reliability null mismatch {label}/{loc}")
                    else:
                        need(close(a[src], b[dst], 2e-12), f"reliability value mismatch {label}/{loc}/{src}")

    return {"schedule_sha256": schedule_hash, "schedule_shape": list(schedule.shape),
            "rows": len(direct), "races": len(race), "dates": len(dates),
            "max_abs_prediction_deltas": max_delta, "policy_hits": rates,
            "paired_date_differences": diffs, "selector_changes_vs_raw": change,
            "primary_gate_passed": expected_gate, "probability_quality_reproduced": True,
            "raw_top2_reproduced": True, "probability_sum_diagnostics": sum_probability_checks}


def main():
    need(not RECEIPT.exists(), "refusing to overwrite review receipt")
    manifest = json.loads(MANIFEST.read_text())
    need(manifest["study"] == STUDY.name and manifest["status"] == "complete", "study manifest status/name mismatch")
    manifest_checks = {"manifest_sha256": sha(MANIFEST), "artifact_count": len(manifest["artifacts"]),
                       "artifact_hashes_pass": True, "source_hashes_pass": True}
    for item in manifest["artifacts"]:
        path = ROOT / item["path"]
        need(path.is_file() and sha(path) == item["sha256"], f"manifest artifact hash mismatch: {item['path']}")
    for relative, digest in manifest["source_inputs_sha256"].items():
        need(sha(ROOT / relative) == digest, f"manifest source hash mismatch: {relative}")

    hist = json.loads((OUT / "HISTORICAL_REFIT_RECEIPT.json").read_text())
    h1 = json.loads((OUT / "expanded_h1_fit.json").read_text())
    h2 = json.loads((OUT / "expanded_h2_calibration.json").read_text())
    report = json.loads((OUT / "REPORT.json").read_text())
    readme = (STUDY / "README.md").read_text()
    report_receipt = json.loads((OUT / "REPORT_RECEIPT.json").read_text())
    pair_input = pd.read_parquet(OUT / "evaluation_pair_predictions.parquet")
    direct_old = pd.read_parquet(DIRECT / "outputs/evaluation_pair_predictions.parquet")
    need(hist["status"] == "PASS" and hist["lightgbm_train_calls"] == 8 and hist["temperature_optimizations"] == 0,
         "historical score receipt scope failed")
    need(hist["pair_fit_performed"] is False and hist["historical_evaluation_scores_generated"] is False,
         "historical score stage scope changed")

    # Replay saved score models and reproduce fit-time moments/objectives only; no fitting calls.
    hist_replay = replay_saved_historical_models(manifest, hist)
    fit_features = pd.read_parquet(FEATURES, columns=["api_record_id", "race_id", "race_date", "year", "horse_number",
        "field_n", "finish_position", *ref.RUNNER_COLUMNS[1:]], filters=[("year", ">=", 2019), ("year", "<=", 2025)])
    fit_features.race_date = pd.to_datetime(fit_features.race_date, errors="coerce")
    need(fit_features.race_date.notna().all(), "fit feature date parse failed")
    fit_gradient = independent_fit_gradients(fit_features, h1, h2)

    eval_features = pd.read_parquet(FEATURES, columns=["api_record_id", "race_id", "race_date", "year", "horse_number",
        "field_n", "finish_position", "distance_m", *ref.RUNNER_COLUMNS[1:]], filters=[("year", ">=", 2024), ("year", "<=", 2026)])
    eval_features.race_date = pd.to_datetime(eval_features.race_date, errors="coerce")
    independent, eval_sources = independent_eval_predictions(eval_features, h1, h2)
    result_replay = compare_report_and_bootstrap(independent, direct_old, report)

    report_content = {k: v for k, v in report.items() if k not in {"study", "study_description", "evaluation_scope", "interpretation_limits"}}
    fingerprint = hashlib.sha256(json.dumps(report_content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    need(fingerprint == report_receipt.get("metric_fingerprint_sha256"), "report numeric metric fingerprint mismatch")
    need(report["study"] == STUDY.name and report_receipt["study"] == STUDY.name, "expanded report still carries old study label")
    need("H1 확장은" in readme and "독립 holdout이 아니다" in readme, "README metadata/limits repair absent")
    need(report_receipt["report_sha256"] == sha(OUT / "REPORT.json") and report_receipt["readme_sha256"] == sha(STUDY / "README.md"),
         "final report receipt hash mismatch")
    need(report_receipt["bootstrap_schedule_sha256"] == result_replay["schedule_sha256"], "report receipt did not pin original schedule")
    need(report["training_window_contrast"]["primary_gate_unchanged"] == "expanded direct pair minus raw F1_STYLE6 score Top2",
         "primary comparator identity changed")

    receipt = {
        "status": "PASS", "study": STUDY.name, "scope": "independent read-only replay; no model fits or optimizer calls",
        "reference_sha256": sha(REFERENCE), "study_manifest": manifest_checks,
        "historical_saved_model_replay": hist_replay,
        "pair_fit_objective_gradient_reproduction": fit_gradient,
        "evaluation_score_sources_replayed": eval_sources,
        "evaluation_prediction_and_report_reproduction": result_replay,
        "final_report": {"study_label": report["study"], "metric_fingerprint_sha256": fingerprint,
                         "report_sha256": sha(OUT / "REPORT.json"), "readme_sha256": sha(STUDY / "README.md"),
                         "report_receipt_sha256": sha(OUT / "REPORT_RECEIPT.json"),
                         "expanded_vs_old_direct": report["training_window_contrast"]["paired_date_bootstrap_95pct_ci"],
                         "primary_vs_raw_top2": report["primary_gate"]["difference_ci"],
                         "primary_gate_passed": report["primary_gate"]["passed"]},
        "prohibited_work": {"additional_lightgbm_training": 0, "additional_pair_optimizer_calls": 0,
                            "new_bootstrap_schedule_generated": False},
    }
    with RECEIPT.open("x", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
