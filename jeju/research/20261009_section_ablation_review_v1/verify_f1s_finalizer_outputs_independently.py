"""Reconcile F1S recovery outputs against the independent saved-model replay.

All model scores, probabilities, runner/race losses, tickets, and bootstrap
intervals originate from `verify_saved_f1s_independently.py`, which reloads
the three locked boosters and implements the evaluator independently. This
script independently re-aggregates group and 467-race reports; it imports no
candidate scoring, evaluation, bootstrap, or reporting helpers.
"""
import sys

sys.dont_write_bytecode = True

import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODEL_DIR = ROOT / "jeju/research/20261009_section_time_ablation_v1"
OUT = MODEL_DIR / "outputs"
F1_OUT = ROOT / "jeju/research/20261009_finish_history_ablation_v1/outputs"
REPLAY_DIR = HERE / "independent_outputs/independent_f1s_saved_model_replay_v2"
REPLAY_RECEIPT = HERE / "independent_outputs/independent_f1s_saved_model_replay_v2_receipt.json"
RECEIPT = HERE / "independent_outputs/independent_f1s_finalizer_output_review.json"
SEED = 20261008
BOOTSTRAPS = 2000
RACE_METRICS = [
    "log_loss", "brier", "trio_nll", "top3_capture", "top4_capture",
    "top5_capture", "top6_capture", "top5_all3", "six_combo_hit",
]
RAW_RACE_METRICS = [
    "log_loss", "brier", "trio_nll", "top3_capture", "top4_capture",
    "top5_capture", "top6_capture", "top3_all3", "top4_all3", "top5_all3",
    "top6_all3", "six_combo_hit", "six_combo_mass",
]
RUNNER_METRICS = ("log_loss", "brier")
OP_METRICS = ("brier", "log_loss", "pick_hit", "top3_all3", "top5_all3", "top5_capture", "six_combo_hit")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_info(path):
    return {"bytes": Path(path).stat().st_size, "sha256": sha256(path)}


def compare_table(expected, actual, keys, numeric=(), strings=(), booleans=()):
    left = expected.sort_values(keys, kind="stable").reset_index(drop=True)
    right = actual.sort_values(keys, kind="stable").reset_index(drop=True)
    assert len(left) == len(right), (len(left), len(right))
    for column in keys:
        assert left[column].fillna("<NA>").astype(str).equals(right[column].fillna("<NA>").astype(str)), column
    for column in strings:
        assert left[column].fillna("<NA>").astype(str).equals(right[column].fillna("<NA>").astype(str)), column
    for column in numeric:
        a = pd.to_numeric(left[column], errors="coerce").to_numpy(float)
        b = pd.to_numeric(right[column], errors="coerce").to_numpy(float)
        assert np.allclose(a, b, rtol=0, atol=1e-12, equal_nan=True), column
    for column in booleans:
        assert left[column].astype(bool).equals(right[column].astype(bool)), column
    return {"rows": int(len(left)), "keys_exact": True, "numeric_atol": 1e-12}


def date_bootstrap(candidate, baseline, metric, key="race_id"):
    left_cols = [key, "race_date", metric]
    right_cols = [key, metric]
    left = candidate[left_cols].rename(columns={metric: "candidate"})
    right = baseline[right_cols].rename(columns={metric: "baseline"})
    pair = left.merge(right, on=key, how="inner", validate="one_to_one")
    assert len(pair) == len(candidate) == len(baseline)
    pair["delta"] = pair.candidate - pair.baseline
    daily = pair.groupby("race_date", sort=True).delta.agg(["sum", "size"])
    rng = np.random.default_rng(SEED)
    indices = rng.integers(0, len(daily), size=(BOOTSTRAPS, len(daily)))
    sample = daily["sum"].to_numpy(float)[indices].sum(axis=1) / daily["size"].to_numpy(float)[indices].sum(axis=1)
    return {
        "delta_f1s_minus_f1": float(pair.delta.mean()),
        "ci95_lo": float(np.quantile(sample, 0.025)),
        "ci95_hi": float(np.quantile(sample, 0.975)),
        "races": int(len(pair)), "days": int(len(daily)),
        "resamples": BOOTSTRAPS, "seed": SEED,
    }


def runner_bootstrap(candidate, baseline, metric):
    left = candidate[["api_record_id", "race_date", metric]].rename(columns={metric: "candidate"})
    right = baseline[["api_record_id", metric]].rename(columns={metric: "baseline"})
    pair = left.merge(right, on="api_record_id", how="inner", validate="one_to_one")
    assert len(pair) == len(candidate) == len(baseline)
    pair["delta"] = pair.candidate - pair.baseline
    daily = pair.groupby("race_date", sort=True).delta.agg(["sum", "size"])
    rng = np.random.default_rng(SEED)
    indices = rng.integers(0, len(daily), size=(BOOTSTRAPS, len(daily)))
    sample = daily["sum"].to_numpy(float)[indices].sum(axis=1) / daily["size"].to_numpy(float)[indices].sum(axis=1)
    return {
        "delta_f1s_minus_f1": float(pair.delta.mean()),
        "ci95_lo": float(np.quantile(sample, 0.025)),
        "ci95_hi": float(np.quantile(sample, 0.975)),
        "rows": int(len(pair)), "days": int(len(daily)),
        "resamples": BOOTSTRAPS, "seed": SEED,
    }


def add_context_independently(predictions, features):
    columns = [
        "api_record_id", "same_starts", "days_since_same",
        "same_distance_last5_actual_n", "history_s1f_valid_n",
        "history_g3f_valid_n", "history_g1f_valid_n",
    ]
    context = features[columns]
    assert context.api_record_id.is_unique
    missing = [column for column in columns if column not in predictions.columns and column != "api_record_id"]
    overlap = [column for column in columns if column in predictions.columns and column != "api_record_id"]
    if overlap:
        check = predictions[["api_record_id", *overlap]].merge(
            context[["api_record_id", *overlap]], on="api_record_id", validate="one_to_one",
            suffixes=("_runner", "_feature"), how="left",
        )
        for column in overlap:
            a, b = check[f"{column}_runner"], check[f"{column}_feature"]
            assert a.equals(b) or np.array_equal(a.to_numpy(), b.to_numpy(), equal_nan=True), column
    if not missing:
        return predictions
    right = context[["api_record_id", *missing]].copy()
    right["_matched"] = True
    out = predictions.merge(right, on="api_record_id", how="left", validate="one_to_one", sort=False)
    assert out["_matched"].fillna(False).all()
    assert out.api_record_id.astype(str).tolist() == predictions.api_record_id.astype(str).tolist()
    return out.drop(columns="_matched")


def race_group_tables(candidate, baseline):
    groups = [("all", "all", candidate, baseline)]
    for year, part in candidate.groupby("year", sort=True):
        groups.append(("year", str(int(year)), part, baseline.loc[baseline.year.eq(year)]))
    for distance, part in candidate.groupby("distance_m", sort=True):
        groups.append(("distance_m", str(int(distance)), part, baseline.loc[baseline.distance_m.eq(distance)]))
    rows, diffs = [], []
    for kind, value, cand, base in groups:
        for variant, frame in (("F1", base), ("F1S", cand)):
            rows.append({
                "group": kind, "value": value, "variant": variant,
                "races": len(frame), "days": frame.race_date.nunique(),
                **{metric: float(frame[metric].mean()) for metric in RACE_METRICS},
            })
        for metric in RACE_METRICS:
            diffs.append({
                "group": kind, "value": value, "metric": metric,
                **date_bootstrap(cand, base, metric),
            })
    return pd.DataFrame(rows), pd.DataFrame(diffs)


def runner_group_tables(candidate, baseline):
    groups = [("all", "all", candidate, baseline)]
    for year, part in candidate.groupby("year", sort=True):
        groups.append(("year", str(int(year)), part, baseline.loc[baseline.year.eq(year)]))
    for distance, part in candidate.groupby("distance_m", sort=True):
        groups.append(("distance_m", str(int(distance)), part, baseline.loc[baseline.distance_m.eq(distance)]))
    for column in ("observed_starts", "same_distance_last5_actual_n"):
        labels = pd.cut(candidate[column], [-1, 0, 4, np.inf], labels=["0", "1_4", "5_plus"])
        base_labels = pd.cut(baseline[column], [-1, 0, 4, np.inf], labels=["0", "1_4", "5_plus"])
        for label in ("0", "1_4", "5_plus"):
            groups.append((column, label, candidate.loc[labels.astype("string").eq(label)], baseline.loc[base_labels.astype("string").eq(label)]))
    for column in ("history_s1f_valid_n", "history_g3f_valid_n", "history_g1f_valid_n"):
        for number in range(6):
            groups.append((column, str(number), candidate.loc[candidate[column].eq(number)], baseline.loc[baseline[column].eq(number)]))
    rows, diffs = [], []
    for kind, value, cand, base in groups:
        if cand.empty:
            continue
        for variant, frame in (("F1", base), ("F1S", cand)):
            rows.append({
                "group": kind, "value": value, "variant": variant,
                "rows": len(frame), "races": frame.race_id.nunique(),
                "runner_mean_log_loss": float(frame.log_loss.mean()),
                "runner_mean_brier": float(frame.brier.mean()),
                "mean_p_top3": float(frame.p_top3.mean()),
                "observed_top3_rate": float(frame.y.mean()),
            })
        for metric in RUNNER_METRICS:
            diffs.append({
                "group": kind, "value": value, "metric": metric,
                **runner_bootstrap(cand, base, metric),
            })
    summary = pd.DataFrame(rows)
    paired = pd.DataFrame(diffs)
    group_races = summary.loc[summary.variant.eq("F1S"), ["group", "value", "races"]].drop_duplicates(["group", "value"])
    paired = paired.merge(group_races, on=["group", "value"], how="left", validate="many_to_one")
    assert paired.races.notna().all()
    return summary, paired


def calibration_bins(candidate, baseline):
    rows = []
    bins_edges = np.arange(0, 1.0001, 0.1)
    for variant, frame in (("F1", baseline), ("F1S", candidate)):
        bins = pd.cut(frame.p_top3, bins_edges, include_lowest=True)
        for interval, part in frame.groupby(bins, observed=True):
            weights = 1.0 / part.field_n
            rows.append({
                "variant": variant, "probability_bin": str(interval),
                "rows": len(part), "races": part.race_id.nunique(),
                "predicted": float(np.average(part.p_top3, weights=weights)),
                "observed": float(np.average(part.y, weights=weights)),
            })
    return pd.DataFrame(rows)


def operating_common_467(candidate_races, candidate_runners, candidate_sets):
    base_races = pd.read_csv(F1_OUT / "operating_common_467_race_metrics.csv")
    base_runners = pd.read_parquet(F1_OUT / "operating_common_467_runner_predictions.parquet")
    base_sets = pd.read_csv(F1_OUT / "operating_common_467_six_combinations.csv")
    common_ids = set(base_races.loc[base_races.variant.eq("HY_R_FORM"), "race_id"])
    assert len(common_ids) == 467
    candidate_2026 = candidate_runners.loc[
        candidate_runners.year.eq(2026) & candidate_runners.race_id.isin(common_ids)
    ].copy()
    assert len(candidate_2026) == 4475 and candidate_2026.race_id.nunique() == 467
    assert candidate_2026.api_record_id.is_unique
    ids = candidate_2026[["race_id", "horse_id", "y"]].sort_values(["race_id", "horse_id"], kind="stable").astype(str).reset_index(drop=True)
    prior_hy = base_runners.loc[base_runners.variant.eq("HY_R_FORM"), ["race_id", "horse_id", "y"]].sort_values(["race_id", "horse_id"], kind="stable").astype(str).reset_index(drop=True)
    assert ids.equals(prior_hy)

    metric_by_race = candidate_races.set_index("race_id", drop=False)
    op_candidate_rows = []
    for race_id, part in candidate_2026.groupby("race_id", sort=False):
        ordered = part.sort_values("horse_number", kind="stable")
        ranked = ordered.sort_values("score", ascending=False, kind="stable")
        metric = metric_by_race.loc[race_id]
        op_candidate_rows.append({
            "race_id": race_id,
            "race_date": str(ordered.race_date.iloc[0]),
            "distance_m": int(ordered.distance_m.iloc[0]),
            "field_n": int(len(ordered)),
            "variant": "F1S",
            "brier": float(metric.brier),
            "log_loss": float(metric.log_loss),
            "pick_hit": int(ranked.y.iloc[0]),
            "top3_all3": int(metric.top3_all3),
            "top5_all3": int(metric.top5_all3),
            "top5_capture": float(metric.top5_capture),
            "six_combo_hit": int(metric.six_combo_hit),
        })
    op_races = pd.concat([
        base_races.loc[base_races.variant.isin(["HY_R_FORM", "F1"])].copy(),
        pd.DataFrame(op_candidate_rows),
    ], ignore_index=True)
    op_summary = op_races.groupby("variant", sort=True).agg(
        races=("race_id", "nunique"), days=("race_date", "nunique"),
        **{metric: (metric, "mean") for metric in OP_METRICS},
    ).reset_index()
    op_diffs = []
    for comparison, left_variant, right_variant in (
        ("F1S-HY_R_FORM", "F1S", "HY_R_FORM"),
        ("F1S-F1", "F1S", "F1"),
    ):
        for metric in OP_METRICS:
            op_diffs.append({
                "comparison": comparison, "metric": metric,
                **date_bootstrap(
                    op_races.loc[op_races.variant.eq(left_variant)],
                    op_races.loc[op_races.variant.eq(right_variant)], metric,
                ),
            })
    op_runners = pd.concat([
        base_runners.loc[base_runners.variant.isin(["HY_R_FORM", "F1"])].copy(),
        candidate_2026,
    ], ignore_index=True)
    op_sets = pd.concat([
        base_sets.loc[base_sets.variant.isin(["HY_R_FORM", "F1"])].copy(),
        candidate_sets.loc[candidate_sets.race_id.isin(common_ids)].copy(),
    ], ignore_index=True)
    assert op_races.groupby("variant").race_id.nunique().eq(467).all()
    assert op_runners.groupby("variant").size().eq(4475).all()
    assert op_sets.groupby("variant").race_id.nunique().eq(467).all()
    return op_races, op_runners, op_sets, op_summary, pd.DataFrame(op_diffs), common_ids


def main():
    with (REPLAY_RECEIPT).open("r", encoding="utf-8") as stream:
        replay_receipt = json.load(stream)
    assert replay_receipt["candidate_model_functions_reused"] is False
    assert replay_receipt["fit_or_temperature_optimization_executed"] is False
    independent_runners = pd.read_parquet(REPLAY_DIR / "f1s_runner_predictions.parquet")
    independent_races = pd.read_csv(REPLAY_DIR / "f1s_race_metrics.csv")
    independent_sets = pd.read_csv(REPLAY_DIR / "f1s_six_combinations.csv")
    features = pd.read_parquet(OUT / "features_f1s.parquet")
    independent_runners = add_context_independently(independent_runners, features)
    baseline_runners = add_context_independently(pd.read_parquet(OUT / "f1_reproduced_runner_predictions.parquet"), features)
    baseline_races = pd.read_csv(OUT / "f1_reproduced_race_metrics.csv")
    baseline_races["year"] = baseline_races.year.astype(int)

    completion = json.loads((OUT / "fit_execution_completion.json").read_text(encoding="utf-8"))
    prefit = json.loads((OUT / "prefit_lock.json").read_text(encoding="utf-8"))
    postfit_lock = json.loads((OUT / "postfit_saved_model_integrity_lock.json").read_text(encoding="utf-8"))
    finalizer_preflight = json.loads((OUT / "finalizer_preflight.json").read_text(encoding="utf-8"))
    finalizer_path = MODEL_DIR / "finalize_saved_f1s_outputs.py"
    assert completion["passed"] and completion["fit_retry_or_refit"] is False
    assert completion["temperature_retry_or_optimization"] is False
    assert completion["lightgbm_train_calls"] == 6 and completion["temperature_optimizations"] == 3
    assert completion["retention_candidate_gate_passed"] is False
    assert finalizer_preflight["status"] == "PASS"
    assert finalizer_preflight["fit_or_temperature_calls"] == 0
    assert postfit_lock["fit_candidate_sha256"] == completion["fit_candidate_sha256"]
    assert postfit_lock["finalizer_sha256"] == sha256(finalizer_path) == completion["finalizer_sha256"]
    assert postfit_lock["prefit_lock_sha256"] == sha256(OUT / "prefit_lock.json")
    assert completion["postfit_model_integrity_lock_sha256"] == sha256(OUT / "postfit_saved_model_integrity_lock.json")
    assert prefit["fit_scope"]["seed"] == SEED

    # Confirm output receipt hashes and that fitted model/meta/calibration bytes
    # are the same ones independently reloaded above.
    model_artifacts = replay_receipt["model_artifacts"]
    for year, entries in model_artifacts.items():
        for name, expected in entries.items():
            path = OUT / f"F1S_{year}" / name
            assert file_info(path) == expected
            assert completion["model_files"][year][name] == expected
            assert postfit_lock["saved_models_metadata_calibration_hashes"][year][name] == expected
    output_hashes = {}
    for name, expected_hash in completion["new_output_sha256"].items():
        observed_hash = sha256(OUT / name)
        assert observed_hash == expected_hash, name
        output_hashes[name] = observed_hash

    observed_runners = pd.read_parquet(OUT / "f1s_runner_predictions.parquet")
    observed_races = pd.read_csv(OUT / "f1s_race_metrics.csv")
    observed_sets = pd.read_csv(OUT / "f1s_six_combinations.csv")
    assert observed_runners.columns.tolist() == independent_runners.columns.tolist()
    runner_check = compare_table(
        independent_runners, observed_runners, ["api_record_id"],
        numeric=["year", "distance_m", "horse_number", "observed_starts", "same_valid_times", "field_n", "score", "p_top3", "y", "log_loss", "brier", "same_starts", "days_since_same", "same_distance_last5_actual_n", "history_s1f_valid_n", "history_g3f_valid_n", "history_g1f_valid_n"],
        strings=["race_id", "race_date", "grade_raw", "horse_id", "variant"],
    )
    race_check = compare_table(
        independent_races, observed_races, ["race_id"],
        numeric=["year", "distance_m", "field_n", *RAW_RACE_METRICS],
        strings=["race_date", "variant", "grade_raw"],
        booleans=["any_no_history", "any_low_history", "any_no_same_time"],
    )
    sets_check = compare_table(
        independent_sets, observed_sets, ["race_id", "selection_rank"],
        numeric=["probability", "hit"], strings=["variant", "numbers"],
    )

    paired_expected = pd.DataFrame([
        {"metric": metric, **date_bootstrap(independent_races, baseline_races, metric)}
        for metric in RACE_METRICS
    ])
    paired_observed = pd.read_csv(OUT / "f1s_paired_differences.csv")
    paired_check = compare_table(
        paired_expected, paired_observed, ["metric"],
        numeric=["delta_f1s_minus_f1", "ci95_lo", "ci95_hi", "races", "days", "resamples", "seed"],
    )
    primary = {}
    for metric in ("log_loss", "brier"):
        row = paired_expected.loc[paired_expected.metric.eq(metric)].iloc[0]
        primary[metric] = {
            "candidate_race_equal_mean": float(independent_races[metric].mean()),
            "f1_race_equal_mean": float(baseline_races[metric].mean()),
            "delta": float(row.delta_f1s_minus_f1),
            "ci95_lo": float(row.ci95_lo), "ci95_hi": float(row.ci95_hi),
            "races": int(row.races), "days": int(row.days),
        }
    independently_derived_gate = bool(
        all(primary[metric]["candidate_race_equal_mean"] < primary[metric]["f1_race_equal_mean"] for metric in primary)
        and any(primary[metric]["ci95_hi"] < 0 for metric in primary)
    )
    gate = json.loads((OUT / "f1s_gate.json").read_text(encoding="utf-8"))
    assert gate["retention_candidate_gate_passed"] is independently_derived_gate is False

    context_runners = independent_runners
    group_races, group_race_diffs = race_group_tables(independent_races, baseline_races)
    group_runners, group_runner_diffs = runner_group_tables(context_runners, baseline_runners)
    for frame in (group_races, group_race_diffs, group_runners, group_runner_diffs):
        frame["support_rule"] = "small_support_if_fewer_than_30_races"
        frame["support_status"] = np.where(frame.races.lt(30), "small_support", "30plus_races")
    observed_group_races = pd.read_csv(OUT / "f1s_metrics_by_group.csv")
    observed_group_race_diffs = pd.read_csv(OUT / "f1s_paired_differences_by_group.csv")
    observed_group_runners = pd.read_csv(OUT / "f1s_runner_metrics_by_group.csv")
    observed_group_runner_diffs = pd.read_csv(OUT / "f1s_runner_paired_differences_by_group.csv")
    gr_check = compare_table(
        group_races, observed_group_races, ["group", "value", "variant"],
        numeric=["races", "days", *RACE_METRICS],
        strings=["support_rule", "support_status"],
    )
    grd_check = compare_table(
        group_race_diffs, observed_group_race_diffs, ["group", "value", "metric"],
        numeric=["delta_f1s_minus_f1", "ci95_lo", "ci95_hi", "races", "days", "resamples", "seed"],
        strings=["support_rule", "support_status"],
    )
    grn_check = compare_table(
        group_runners, observed_group_runners, ["group", "value", "variant"],
        numeric=["rows", "races", "runner_mean_log_loss", "runner_mean_brier", "mean_p_top3", "observed_top3_rate"],
        strings=["support_rule", "support_status"],
    )
    grnd_check = compare_table(
        group_runner_diffs, observed_group_runner_diffs, ["group", "value", "metric"],
        numeric=["delta_f1s_minus_f1", "ci95_lo", "ci95_hi", "rows", "days", "resamples", "seed", "races"],
        strings=["support_rule", "support_status"],
    )

    calibration_expected = calibration_bins(independent_runners, baseline_runners)
    calibration_observed = pd.read_csv(OUT / "f1s_calibration_bins.csv")
    calibration_check = compare_table(
        calibration_expected, calibration_observed, ["variant", "probability_bin"],
        numeric=["rows", "races", "predicted", "observed"],
    )

    op_races, op_runners, op_sets, op_summary, op_differences, common_ids = operating_common_467(
        independent_races, independent_runners, independent_sets
    )
    observed_op_races = pd.read_csv(OUT / "f1s_operating_common_467_race_metrics.csv")
    observed_op_runners = pd.read_parquet(OUT / "f1s_operating_common_467_runner_predictions.parquet")
    observed_op_sets = pd.read_csv(OUT / "f1s_operating_common_467_six_combinations.csv")
    observed_op_summary = pd.read_csv(OUT / "f1s_operating_common_467_summary.csv")
    observed_op_diffs = pd.read_csv(OUT / "f1s_operating_common_467_paired_differences.csv")
    op_race_check = compare_table(
        op_races, observed_op_races, ["race_id", "variant"],
        numeric=["distance_m", "field_n", "brier", "log_loss", "pick_hit", "top3_all3", "top5_all3", "top5_capture", "six_combo_hit"],
        strings=["race_date"],
    )
    op_runner_check = compare_table(
        op_runners, observed_op_runners, ["race_id", "horse_id", "variant"],
        numeric=["horse_number", "y", "p_top3", "brier", "log_loss"],
    )
    op_set_check = compare_table(
        op_sets, observed_op_sets, ["race_id", "variant", "selection_rank"],
        numeric=["probability", "hit"], strings=["numbers"],
    )
    op_summary_check = compare_table(
        op_summary, observed_op_summary, ["variant"],
        numeric=["races", "days", *OP_METRICS],
    )
    op_diff_check = compare_table(
        op_differences, observed_op_diffs, ["comparison", "metric"],
        numeric=["delta_f1s_minus_f1", "ci95_lo", "ci95_hi", "races", "days", "resamples", "seed"],
    )

    checks = {
        "saved_model_meta_calibration_hashes_unchanged": True,
        "finalizer_outputs_match_completion_sha256": len(output_hashes) == 15,
        "independent_runner_probabilities_and_losses_match": True,
        "independent_race_metrics_match": True,
        "independent_six_sets_match": True,
        "all_primary_and_race_metric_date_bootstraps_match": True,
        "all_year_distance_race_group_tables_match": True,
        "all_runner_experience_group_tables_match": True,
        "all_calibration_bins_match": True,
        "operating_common_467_race_runner_set_summary_and_ci_match": True,
        "operating_common_scope_is_467_races_4475_runners": len(common_ids) == 467 and len(op_runners.loc[op_runners.variant.eq("F1S")]) == 4475,
        "independently_recomputed_retention_gate_is_false": independently_derived_gate is False,
    }
    assert all(checks.values()), checks
    receipt = {
        "review_status": "F1S_recovery_outputs_independently_reconciled",
        "review_code_sha256": sha256(Path(__file__)),
        "candidate_functions_reused": False,
        "new_fit_or_temperature_optimization": False,
        "interruption_preserved": completion["fit_runner_postprocessing_interruption"],
        "model_hashes_verified_against_previously_independent_replay": model_artifacts,
        "runner_match": runner_check,
        "race_match": race_check,
        "six_set_match": sets_check,
        "paired_race_metrics_match": paired_check,
        "race_group_metrics_match": gr_check,
        "race_group_paired_differences_match": grd_check,
        "runner_group_metrics_match": grn_check,
        "runner_group_paired_differences_match": grnd_check,
        "calibration_bins_match": calibration_check,
        "primary_losses_and_gate": {
            "metrics": primary,
            "retention_candidate_gate_passed": independently_derived_gate,
            "candidate_gate_artifact_matches": True,
        },
        "operating_common_467": {
            "common_races": len(common_ids),
            "candidate_runner_rows": int(len(op_runners.loc[op_runners.variant.eq("F1S")])),
            "race_rows_per_variant": 467,
            "runner_rows_per_variant": 4475,
            "race_metrics_match": op_race_check,
            "runner_predictions_match": op_runner_check,
            "six_sets_match": op_set_check,
            "summary_match": op_summary_check,
            "paired_date_ci_match": op_diff_check,
        },
        "checks": checks,
        "candidate_reference_hashes": {
            "fit_execution_completion": file_info(OUT / "fit_execution_completion.json"),
            "postfit_saved_model_integrity_lock": file_info(OUT / "postfit_saved_model_integrity_lock.json"),
            "finalizer_preflight": file_info(OUT / "finalizer_preflight.json"),
            "finalizer_code": file_info(finalizer_path),
            "prefit_lock": file_info(OUT / "prefit_lock.json"),
        },
    }
    assert not RECEIPT.exists(), f"refusing to overwrite {RECEIPT}"
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
