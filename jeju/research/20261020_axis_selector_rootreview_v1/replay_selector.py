"""Independently replay the fitted selector, objective and paired evaluation."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
from independent_features import FEATURE_NAMES, load_training_rows, pairwise_objective, rows_from_scores, select

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STUDY = ROOT / "jeju/research/20261020_axis_selector_v1"
OUT = STUDY / "outputs"
STYLE = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs"
PRED = ROOT / "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet"
SCHEDULE = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
WORKER_NAMES = [c.replace("log1p_", "log_") for c in FEATURE_NAMES]


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def same(a, b):
    np.testing.assert_allclose(a, b, atol=2e-12, rtol=2e-12, equal_nan=True)


def summarize(g):
    n = len(g)
    old, new = int(g.baseline_hit.sum()), int(g.selector_hit.sum())
    counts = g.outcome.value_counts()
    return {"races": n, "baseline_top3_hits": old, "selector_top3_hits": new,
            "baseline_top3_rate": old/n, "selector_top3_rate": new/n,
            "selector_minus_baseline": (new-old)/n,
            "axis_changed_races": int(g.axis_changed.sum()), "axis_changed_rate": float(g.axis_changed.mean()),
            "new_selector_hits": int(counts.get("selector_only", 0)), "lost_baseline_hits": int(counts.get("baseline_only", 0)),
            "both_hit": int(counts.get("both", 0)), "neither_hit": int(counts.get("neither", 0)),
            "outcome_counts": {k: int(counts.get(k, 0)) for k in ["both", "baseline_only", "selector_only", "neither"]}}


def compare_summary(actual, expected):
    for k, value in actual.items():
        if isinstance(value, dict):
            assert value == expected[k]
        else:
            same(value, expected[k])


def main():
    receipt = json.loads((OUT / "FIT_RECEIPT.json").read_text())
    assert receipt["status"] == "PASS" and receipt["fits_completed"] == 3
    for rel, expected in receipt["source_hashes"].items():
        p = (ROOT / rel).resolve(strict=True)
        assert p.is_relative_to(ROOT) and sha(p) == expected
    for rel, expected in receipt["output_sha256"].items():
        p = (OUT / rel).resolve(strict=True)
        assert p.is_relative_to(OUT) and sha(p) == expected
    approval = json.loads((OUT / "ROOT_FIT_APPROVAL.json").read_text())
    assert sha(STUDY / "fit_selector.py") == approval["fit_code_sha256"] == receipt["fit_code_sha256"]
    f = pd.read_parquet(STYLE / "features.parquet")
    p = pd.read_parquet(PRED)
    train = load_training_rows()
    workers = pd.read_parquet(OUT / "candidate_predictions.parquet").set_index("api_record_id")
    assert workers.index.is_unique
    all_choices = []
    model_checks = []
    max_utility_error = 0.0
    for year in [2024, 2025, 2026]:
        model = json.loads((OUT / f"model_{year}.json").read_text())
        assert model["basis_order"] == WORKER_NAMES and model["candidate_count"] == 3
        assert model["utility_is_probability"] is False and model["baseline_p_top3_used_as_feature"] is False
        t = train.loc[train.year.lt(year)].copy()
        assert str(t.race_date.max()) == model["training_max_label_date"]
        assert pd.Timestamp(t.race_date.max()) <= pd.Timestamp(p.loc[p.year.eq(year), "race_date"].min()) - pd.Timedelta(days=2)
        x = t[FEATURE_NAMES].to_numpy(dtype=float)
        root_mean, root_sd = x.mean(axis=0), x.std(axis=0, ddof=0)
        root_scale = np.where(root_sd == 0, 1.0, root_sd)
        mean = np.array([model["mean_by_feature"][c] for c in WORKER_NAMES])
        scale = np.array([model["scale_by_feature"][c] for c in WORKER_NAMES])
        beta = np.array([model["coefficients"][c] for c in WORKER_NAMES])
        same(mean, root_mean)
        same(scale, root_scale)
        objective, gradient, rmix, pair_n = pairwise_objective(beta, t, root_mean, root_scale)
        same(objective, model["optimizer"]["objective_value"])
        same(gradient, [model["optimizer"]["gradient"][c] for c in WORKER_NAMES])
        assert np.max(np.abs(gradient)) <= 1e-6
        assert model["training_counts"]["candidate_rows"] == len(t)
        assert model["training_counts"]["informative_races_R_mix"] == rmix
        assert model["training_counts"]["informative_pair_rows"] == pair_n
        assert model["optimizer"]["success"] and model["optimizer"]["maxiter"] == 1000
        assert model["optimizer"]["ftol"] == 1e-12 and model["optimizer"]["gtol"] == 1e-8
        for provider in model["training_score_providers"]:
            assert provider["provider_role"] == "calibration_raw_score_only"
            assert provider["provider_fold"] == provider["race_year"] + 1
            assert provider["race_year"] < year
            assert sha(ROOT / provider["source_path"]) == provider["source_sha256"]
        assert model["evaluation_score_provider"]["provider_role"] == "evaluation_raw_score_only"
        assert model["evaluation_score_provider"]["provider_fold"] == year
        scores = p.loc[p.year.eq(year), ["api_record_id", "score"]]
        ev = rows_from_scores(f, scores)
        replay, chosen = select(ev, beta, mean, scale)
        z = replay.set_index("api_record_id").sort_index()
        w = workers.loc[z.index].sort_index()
        np.testing.assert_array_equal(z.race_id, w.race_id)
        np.testing.assert_array_equal(z.score_rank, w.score_rank)
        np.testing.assert_array_equal(z.score, w.base_score)
        np.testing.assert_array_equal(z.target_top3, w.y)
        np.testing.assert_array_equal(w.base_p, p.set_index("api_record_id").loc[z.index, "p_top3"])
        same(z.root_utility, w.utility)
        max_utility_error = max(max_utility_error, float(np.abs(z.root_utility-w.utility).max()))
        np.testing.assert_array_equal(w.selector_chosen, w.index.isin(chosen.api_record_id))
        np.testing.assert_array_equal(w.baseline_chosen, w.score_rank.eq(1))
        all_choices.append(chosen)
        model_checks.append({"year": year, "training_candidates": len(t), "training_races": t.race_id.nunique(),
                             "informative_races": rmix, "pairs": pair_n, "replayed_eval_candidates": len(z),
                             "objective": float(objective), "max_abs_gradient": float(np.abs(gradient).max())})

    new = pd.concat(all_choices, ignore_index=True)[["race_id", "api_record_id", "horse_id", "horse_number", "target_top3", "root_utility"]]
    b = pd.read_parquet(HERE / "ROOT_BASELINE_RACE_LEDGER.parquet")
    r = b.merge(new, on="race_id", suffixes=("_old", "_new"), validate="one_to_one")
    assert len(r) == 1779
    r["baseline_hit"] = r.y.astype(bool)
    r["selector_hit"] = r.target_top3.astype(bool)
    r["axis_changed"] = r.api_record_id_old.ne(r.api_record_id_new)
    r["outcome"] = np.select([r.baseline_hit&r.selector_hit, r.baseline_hit&~r.selector_hit,
                               ~r.baseline_hit&r.selector_hit], ["both", "baseline_only", "selector_only"], default="neither")
    w = pd.read_parquet(OUT / "race_choices.parquet").set_index("race_id")
    assert w.index.is_unique
    w = w.loc[r.race_id]
    np.testing.assert_array_equal(r.api_record_id_old, w.baseline_axis_api_record_id)
    np.testing.assert_array_equal(r.api_record_id_new, w.selector_axis_api_record_id)
    for col in ["year", "race_date", "distance_m", "field_n", "baseline_hit", "selector_hit", "axis_changed", "outcome"]:
        np.testing.assert_array_equal(r[col], w[col])
    primary = r.loc[r.primary]
    report = json.loads((OUT / "REPORT.json").read_text())
    compare_summary(summarize(primary), report["primary_four_distance_cohort"])
    compare_summary(summarize(r), report["all_distance_cohort"])
    for frame, label in [(primary, "primary"), (r, "all_distance")]:
        for col, key in [("year", "by_year"), ("distance_m", "by_distance_m")]:
            for value, g in frame.groupby(col):
                compare_summary(summarize(g), report[f"{label}_{key}"][str(int(value))])
    for label, mask in [("0", primary.observed_starts.eq(0)), ("1-4", primary.observed_starts.between(1,4)), ("5+", primary.observed_starts.ge(5))]:
        compare_summary(summarize(primary.loc[mask]), report["primary_by_baseline_axis_career"][label])
    for frame, key in [(primary, "primary_four_distance"), (r, "all_distances")]:
        coverage = report["k5_coverage_diagnostic"][key]
        assert coverage["races"] == len(frame) and coverage["covered_races"] == int(frame.top5_actual_top3_n.gt(0).sum())

    dates = sorted(r.race_date.unique())
    schedule = np.load(SCHEDULE, allow_pickle=False)
    weights = np.vstack([np.bincount(row, minlength=len(dates)) for row in schedule])
    daily = primary.groupby("race_date").agg(n=("race_id", "size"), old=("baseline_hit", "sum"), new=("selector_hit", "sum")).reindex(dates, fill_value=0)
    counts = weights @ daily[["n", "old", "new"]].to_numpy(dtype=np.int64)
    deltas = (counts[:,2]-counts[:,1])/counts[:,0]
    draws = pd.read_parquet(OUT / "bootstrap_draws.parquet")
    np.testing.assert_array_equal(counts, draws[["primary_races", "baseline_hits", "selector_hits"]])
    same(deltas, draws.selector_minus_baseline)
    ci = np.quantile(deltas, [.025, .975])
    same(ci, report["primary_four_distance_cohort"]["paired_date_bootstrap_ci95"])
    gate = bool(summarize(primary)["selector_minus_baseline"] > 0 and ci[0] > 0)
    assert gate == report["primary_four_distance_cohort"]["primary_gate_pass"] == receipt["primary_gate_pass"]
    for rel, expected in receipt["source_hashes"].items():
        assert sha(ROOT / rel) == expected
    with (HERE / "ROOT_REPLAY_RACE_LEDGER.parquet").open("xb") as out:
        r.to_parquet(out, index=False)
    result = {"passed": True, "models_independently_checked": model_checks,
              "candidate_predictions_checked": len(workers), "race_choices_checked": len(r),
              "maximum_utility_difference": max_utility_error, "bootstrap_draws_checked": len(deltas),
              "primary": summarize(primary), "all_distances": summarize(r), "primary_ci95": ci.tolist(),
              "primary_gate_pass": gate, "source_hashes_unchanged": len(receipt["source_hashes"]),
              "fit_receipt_sha256": sha(OUT / "FIT_RECEIPT.json"), "root_models_fitted": 0,
              "database_opened": False}
    with (HERE / "ROOT_REPLAY_REVIEW.json").open("x") as out:
        json.dump(result, out, indent=2, ensure_ascii=False)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
