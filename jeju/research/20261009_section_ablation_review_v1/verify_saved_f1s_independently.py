"""Reload saved F1S boosters and independently reproduce their evaluation.

This verifier does not import candidate fit or finalizer functions. It only
loads saved models, re-scores the fixed calibration/evaluation rows with the
stored temperature, and independently derives probabilities, losses, race
metrics, tickets, and the locked paired date bootstrap.
"""
import sys

sys.dont_write_bytecode = True

import hashlib
import itertools
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODEL_DIR = ROOT / "jeju/research/20261009_section_time_ablation_v1"
OUT = MODEL_DIR / "outputs"
F1_DIR = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
F1_OUT = F1_DIR / "outputs"
FEATURES_PATH = OUT / "features_f1s.parquet"
F1_FEATURES_PATH = F1_OUT / "features.parquet"
BASE_RUN_PATH = ROOT / "jeju/research/20261008_horse_profile_baseline_v1/run.py"
REPLAY_DIR = HERE / "independent_outputs/independent_f1s_saved_model_replay_v2"
RECEIPT = HERE / "independent_outputs/independent_f1s_saved_model_replay_v2_receipt.json"
YEARS = (2024, 2025, 2026)
SEED = 20261008
BOOTSTRAPS = 2000
RACE_METRICS = [
    "log_loss", "brier", "trio_nll", "top3_capture", "top4_capture",
    "top5_capture", "top6_capture", "top5_all3", "top6_all3",
    "six_combo_hit", "six_combo_mass",
]
PRIMARY_METRICS = ("log_loss", "brier")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_info(path):
    return {"bytes": Path(path).stat().st_size, "sha256": sha256(path)}


def independently_evaluate(frame, scores, tau, year):
    race_rows, runner_rows, ticket_rows = [], [], []
    score_by_pos = np.asarray(scores, dtype=np.float64)
    assert len(score_by_pos) == len(frame)
    for race_id, positions in frame.groupby("race_id", sort=False).indices.items():
        indexes = np.asarray(positions, dtype=np.int64)
        one = frame.iloc[indexes]
        z = score_by_pos[indexes]
        n = len(one)
        assert n >= 6
        assert one.horse_number.is_monotonic_increasing

        triples = np.asarray(list(itertools.combinations(range(n), 3)), dtype=np.int64)
        # Preserve the existing F1 combination-energy arithmetic order. The
        # original evaluator sorts each triple's three runner scores before summing.
        energy = np.sort(z[triples], axis=1).sum(axis=1)
        truth_positions = np.flatnonzero(one.finish_position.to_numpy(dtype=float) <= 3)
        assert len(truth_positions) == 3
        truth_mask = (triples == truth_positions[None, :]).all(axis=1)
        assert int(truth_mask.sum()) == 1
        target = int(np.flatnonzero(truth_mask)[0])

        scaled = energy / float(tau)
        normalizer = float(logsumexp(scaled))
        log_q = scaled - normalizer
        q = np.exp(log_q)
        incidence = np.zeros((len(triples), n), dtype=np.float64)
        incidence[np.arange(len(triples))[:, None], triples] = 1.0
        p_top3 = incidence.T @ q
        assert np.isclose(float(q.sum()), 1.0, rtol=0, atol=1e-12)
        assert np.isclose(float(p_top3.sum()), 3.0, rtol=0, atol=1e-10)

        y = (one.finish_position.to_numpy(dtype=float) <= 3).astype(np.int64)
        clipped = np.clip(p_top3, 1e-12, 1.0 - 1e-12)
        runner_logloss = -y * np.log(clipped) - (1 - y) * np.log1p(-clipped)
        runner_brier = (p_top3 - y) ** 2
        raw_order = np.argsort(-z, kind="stable")
        combo_order = np.argsort(-energy, kind="stable")[:6]
        true_triple = set(triples[target].tolist())

        race_rows.append({
            "race_id": race_id,
            "race_date": one.race_date.iloc[0],
            "year": int(one.year.iloc[0]),
            "variant": "F1S",
            "distance_m": int(one.distance_m.iloc[0]),
            "grade_raw": one.grade_raw.iloc[0],
            "field_n": int(n),
            "any_no_history": bool(one.observed_starts.eq(0).any()),
            "any_low_history": bool(one.observed_starts.lt(5).any()),
            "any_no_same_time": bool(one.same_valid_times.eq(0).any()),
            "log_loss": float(runner_logloss.mean()),
            "brier": float(runner_brier.mean()),
            "trio_nll": float(-log_q[target]),
            "six_combo_hit": int(target in set(combo_order.tolist())),
            "six_combo_mass": float(q[combo_order].sum()),
            "top3_capture": len(true_triple.intersection(set(raw_order[:3].tolist()))) / 3.0,
            "top4_capture": len(true_triple.intersection(set(raw_order[:4].tolist()))) / 3.0,
            "top5_capture": len(true_triple.intersection(set(raw_order[:5].tolist()))) / 3.0,
            "top6_capture": len(true_triple.intersection(set(raw_order[:6].tolist()))) / 3.0,
            "top3_all3": int(true_triple.issubset(set(raw_order[:3].tolist()))),
            "top4_all3": int(true_triple.issubset(set(raw_order[:4].tolist()))),
            "top5_all3": int(true_triple.issubset(set(raw_order[:5].tolist()))),
            "top6_all3": int(true_triple.issubset(set(raw_order[:6].tolist()))),
        })
        for local, global_index in enumerate(indexes):
            row = one.iloc[local]
            runner_rows.append({
                "api_record_id": row.api_record_id,
                "race_id": row.race_id,
                "race_date": row.race_date,
                "year": int(row.year),
                "distance_m": int(row.distance_m),
                "grade_raw": row.grade_raw,
                "horse_id": row.horse_id,
                "horse_number": row.horse_number,
                "observed_starts": row.observed_starts,
                "same_valid_times": row.same_valid_times,
                "field_n": int(n),
                "variant": "F1S",
                "score": float(score_by_pos[global_index]),
                "p_top3": float(p_top3[local]),
                "y": int(y[local]),
                "log_loss": float(runner_logloss[local]),
                "brier": float(runner_brier[local]),
            })
        horse_numbers = one.horse_number.to_numpy()
        for rank, combo_index in enumerate(combo_order, start=1):
            chosen = triples[combo_index]
            ticket_rows.append({
                "race_id": race_id,
                "variant": "F1S",
                "selection_rank": rank,
                "numbers": ",".join(str(int(horse_numbers[position])) for position in chosen),
                "probability": float(q[combo_index]),
                "hit": int(int(combo_index) == target),
            })

    races = pd.DataFrame.from_records(race_rows)
    runners = pd.DataFrame.from_records(runner_rows)
    tickets = pd.DataFrame.from_records(ticket_rows)
    assert len(races) == frame.race_id.nunique()
    assert len(runners) == len(frame)
    assert len(tickets) == len(races) * 6
    return races, runners, tickets


def attach_context_independently(predictions, features):
    columns = [
        "api_record_id", "same_starts", "days_since_same",
        "same_distance_last5_actual_n", "history_s1f_valid_n",
        "history_g3f_valid_n", "history_g1f_valid_n",
    ]
    context = features[columns]
    assert context.api_record_id.is_unique
    existing = [column for column in columns if column in predictions.columns and column != "api_record_id"]
    if existing:
        checked = predictions[["api_record_id", *existing]].merge(
            context[["api_record_id", *existing]], on="api_record_id", validate="one_to_one",
            suffixes=("_row", "_feature"), how="left",
        )
        for column in existing:
            a, b = checked[f"{column}_row"], checked[f"{column}_feature"]
            assert a.equals(b) or np.array_equal(a.to_numpy(), b.to_numpy(), equal_nan=True), column
    missing = [column for column in columns if column not in predictions.columns and column != "api_record_id"]
    if not missing:
        return predictions
    join_context = context[["api_record_id", *missing]].copy()
    join_context["_context_row_present"] = True
    joined = predictions.merge(join_context, on="api_record_id", how="left", validate="one_to_one")
    assert len(joined) == len(predictions)
    assert joined["_context_row_present"].fillna(False).all()
    return joined.drop(columns="_context_row_present")


def compare_frames(expected, observed, keys, numeric, string=(), boolean=()):
    left = expected.sort_values(keys, kind="stable").reset_index(drop=True)
    right = observed.sort_values(keys, kind="stable").reset_index(drop=True)
    assert len(left) == len(right), (len(left), len(right))
    for column in keys:
        assert left[column].fillna("<NA>").astype(str).equals(right[column].fillna("<NA>").astype(str)), column
    for column in string:
        assert left[column].fillna("<NA>").astype(str).equals(right[column].fillna("<NA>").astype(str)), column
    for column in numeric:
        a = pd.to_numeric(left[column], errors="coerce").to_numpy(dtype=np.float64)
        b = pd.to_numeric(right[column], errors="coerce").to_numpy(dtype=np.float64)
        assert np.allclose(a, b, rtol=0, atol=1e-12, equal_nan=True), column
    for column in boolean:
        assert left[column].astype(bool).equals(right[column].astype(bool)), column
    return {"rows": int(len(left)), "keys_exact": True, "numeric_tolerance": 1e-12}


def paired_date_bootstrap(candidate, baseline, metric):
    left = candidate[["race_id", "race_date", metric]].rename(columns={metric: "candidate"})
    right = baseline[["race_id", metric]].rename(columns={metric: "baseline"})
    pair = left.merge(right, on="race_id", how="inner", validate="one_to_one")
    assert len(pair) == len(candidate) == len(baseline)
    assert pair.race_date.notna().all()
    pair["delta"] = pair.candidate - pair.baseline
    days = pair.groupby("race_date", sort=True).delta.agg(["sum", "size"])
    rng = np.random.default_rng(SEED)
    draw = rng.integers(0, len(days), size=(BOOTSTRAPS, len(days)))
    samples = days["sum"].to_numpy(dtype=float)[draw].sum(axis=1) / days["size"].to_numpy(dtype=float)[draw].sum(axis=1)
    return {
        "delta_f1s_minus_f1": float(pair.delta.mean()),
        "ci95_lo": float(np.quantile(samples, 0.025)),
        "ci95_hi": float(np.quantile(samples, 0.975)),
        "races": int(len(pair)),
        "days": int(len(days)),
        "resamples": BOOTSTRAPS,
        "seed": SEED,
    }


def main():
    prefit_lock = json.loads((OUT / "prefit_lock.json").read_text(encoding="utf-8"))
    started = json.loads((OUT / "fit_execution_started.json").read_text(encoding="utf-8"))
    interruption = json.loads((OUT / "fit_execution_interruption.json").read_text(encoding="utf-8"))
    candidate_features = pd.read_parquet(FEATURES_PATH)
    frozen_f1_features = pd.read_parquet(F1_FEATURES_PATH)
    candidate_replay_receipt = json.loads((OUT / "f1_saved_model_replay.json").read_text(encoding="utf-8"))
    assert prefit_lock["fit_executed"] is False
    assert started["approval_conditions"]["independent_fit_code_review_passed"] is True
    assert started["approval_conditions"]["before_fit_check_passed"] is True
    assert started["run_code_sha256"] == prefit_lock["scoped_reference_sha256"]["jeju/research/20261009_section_time_ablation_v1/fit_candidate.py"]["sha256"]
    assert interruption["status"] == "fit_completed_postprocessing_interrupted"
    assert interruption["fit_counts"] == {"lightgbm_train_calls": 6, "temperature_optimizations": 3}
    assert interruption["fit_retry_or_refit"] is False
    assert interruption["temperature_retry_or_optimization"] is False
    assert candidate_replay_receipt["model_refit_count"] == 0

    expected_f1_features = json.loads((F1_OUT / "F1_2024/meta.json").read_text(encoding="utf-8"))["features"]
    features = expected_f1_features + [
        "history_s1f_mean5_seconds", "history_s1f_valid_n",
        "history_g3f_mean5_seconds", "history_g3f_valid_n",
        "history_g1f_mean5_seconds", "history_g1f_valid_n",
    ]
    assert list(candidate_features.columns) == list(frozen_f1_features.columns) + features[len(expected_f1_features):]
    assert candidate_features[frozen_f1_features.columns].equals(frozen_f1_features)
    assert len(candidate_features) == 52155 and candidate_features.race_id.nunique() == 5206

    all_races, all_runners, all_tickets = [], [], []
    calibration_check = {}
    model_artifacts = {}
    year_results = {}
    for year in YEARS:
        folder = OUT / f"F1S_{year}"
        model_path, meta_path = folder / "top3.txt", folder / "meta.json"
        cal_path = folder / "calibration_scores.parquet"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["variant"] == "F1S" and meta["evaluation_year"] == year
        assert meta["features"] == features
        assert meta["seed"] == SEED
        assert meta["lightgbm_train_calls"] == 2
        assert meta["temperature_optimizations"] == 1
        model_hash = sha256(model_path)
        assert meta["model_sha256"] == model_hash
        model = lgb.Booster(model_file=str(model_path))
        assert model.current_iteration() == int(meta["trees"])
        x = candidate_features[features].copy()
        for column, vocabulary in meta["vocabulary"].items():
            x[column] = pd.Categorical(x[column].astype("string"), categories=vocabulary)

        cal_mask = candidate_features.year.eq(year - 1)
        eval_mask = candidate_features.year.eq(year)
        calibration = candidate_features.loc[cal_mask].reset_index(drop=True)
        evaluation = candidate_features.loc[eval_mask].reset_index(drop=True)
        cal_scores = model.predict(x.loc[cal_mask], raw_score=True, num_threads=4)
        eval_scores = model.predict(x.loc[eval_mask], raw_score=True, num_threads=4)

        stored_cal = pd.read_parquet(cal_path)
        assert stored_cal.api_record_id.astype(str).equals(calibration.api_record_id.astype(str))
        assert np.allclose(stored_cal.score.to_numpy(float), cal_scores, rtol=0, atol=1e-12)
        saved_f1_meta = json.loads((F1_OUT / f"F1_{year}/meta.json").read_text(encoding="utf-8"))
        assert meta["parameters"] == saved_f1_meta["parameters"]
        assert meta["vocabulary"] == saved_f1_meta["vocabulary"]
        assert meta["trees"] > 0 and np.isfinite(meta["tau"])

        races, runners, tickets = independently_evaluate(evaluation, eval_scores, float(meta["tau"]), year)
        all_races.append(races)
        all_runners.append(runners)
        all_tickets.append(tickets)
        calibration_check[str(year)] = {
            "saved_calibration_rows": int(len(stored_cal)),
            "calibration_scores_replayed_exact_with_fixed_model": True,
            "fixed_tau": float(meta["tau"]),
            "tau_reoptimization_executed": False,
            "saved_model_trees": int(model.current_iteration()),
            "model_sha256_matches_meta": True,
        }
        model_artifacts[str(year)] = {
            path.name: file_info(path) for path in (model_path, meta_path, cal_path)
        }
        year_results[str(year)] = {
            "calibration_rows": int(len(calibration)),
            "evaluation_rows": int(len(evaluation)),
            "evaluation_races": int(evaluation.race_id.nunique()),
            "trees": int(meta["trees"]),
            "tau": float(meta["tau"]),
        }

    races = pd.concat(all_races, ignore_index=True)
    runners = pd.concat(all_runners, ignore_index=True)
    tickets = pd.concat(all_tickets, ignore_index=True)
    assert len(runners) == 17412 and runners.race_id.nunique() == 1779
    assert len(races) == 1779 and len(tickets) == 10674
    assert np.allclose(runners.groupby("race_id", sort=False).p_top3.sum().to_numpy(), 3.0, rtol=0, atol=1e-10)

    # Persist independent raw replay, then compare it with recovery-only outputs
    # if that finalizer has completed. This script never writes candidate paths.
    REPLAY_DIR.mkdir(exist_ok=True)
    independent_files = {
        "f1s_runner_predictions.parquet": runners,
        "f1s_race_metrics.csv": races,
        "f1s_six_combinations.csv": tickets,
    }
    for name, frame in independent_files.items():
        path = REPLAY_DIR / name
        if path.exists():
            raise FileExistsError(path)
        if name.endswith(".parquet"):
            frame.to_parquet(path, index=False)
        else:
            frame.to_csv(path, index=False)

    candidate_outputs_exist = all(
        (OUT / name).is_file() for name in (
            "f1s_runner_predictions.parquet", "f1s_race_metrics.csv",
            "f1s_six_combinations.csv", "f1s_gate.json",
        )
    )
    comparison = {"candidate_recovery_outputs_present": candidate_outputs_exist}
    primary = {}
    gate = None
    if candidate_outputs_exist:
        observed_runners = pd.read_parquet(OUT / "f1s_runner_predictions.parquet")
        observed_races = pd.read_csv(OUT / "f1s_race_metrics.csv")
        observed_tickets = pd.read_csv(OUT / "f1s_six_combinations.csv")
        assert "observed_starts" in observed_runners.columns
        runners_with_context = attach_context_independently(runners, candidate_features)
        comparison["runners"] = compare_frames(
            runners_with_context, observed_runners, ["api_record_id"],
            ["year", "distance_m", "horse_number", "observed_starts", "same_valid_times", "field_n", "score", "p_top3", "y", "log_loss", "brier"],
            string=["race_id", "race_date", "grade_raw", "horse_id", "variant"],
        )
        comparison["races"] = compare_frames(
            races, observed_races, ["race_id"],
            ["year", "distance_m", "field_n", "log_loss", "brier", "trio_nll", "six_combo_hit", "six_combo_mass", "top3_capture", "top4_capture", "top5_capture", "top6_capture", "top3_all3", "top4_all3", "top5_all3", "top6_all3"],
            string=["race_date", "variant", "grade_raw"],
            boolean=["any_no_history", "any_low_history", "any_no_same_time"],
        )
        comparison["six_sets"] = compare_frames(
            tickets, observed_tickets, ["race_id", "selection_rank"],
            ["probability", "hit"], string=["variant", "numbers"],
        )
        baseline_races = pd.read_csv(OUT / "f1_reproduced_race_metrics.csv")
        baseline_races["year"] = baseline_races.year.astype(int)
        paired = {metric: paired_date_bootstrap(races, baseline_races, metric) for metric in PRIMARY_METRICS}
        candidate_means = {metric: float(races[metric].mean()) for metric in PRIMARY_METRICS}
        baseline_means = {metric: float(baseline_races[metric].mean()) for metric in PRIMARY_METRICS}
        gate = bool(
            all(candidate_means[metric] < baseline_means[metric] for metric in PRIMARY_METRICS)
            and any(paired[metric]["ci95_hi"] < 0 for metric in PRIMARY_METRICS)
        )
        candidate_gate = json.loads((OUT / "f1s_gate.json").read_text(encoding="utf-8"))
        assert candidate_gate["retention_candidate_gate_passed"] is gate
        assert candidate_gate["fit_model_sha256"] == {year: rows["top3.txt"]["sha256"] for year, rows in model_artifacts.items()}
        assert candidate_gate["model_fit_repeated_during_postprocessing"] is False
        assert candidate_gate["temperature_optimization_repeated_during_postprocessing"] is False
        primary = {
            metric: {
                "candidate_race_equal_mean": candidate_means[metric],
                "baseline_f1_race_equal_mean": baseline_means[metric],
                **paired[metric],
            }
            for metric in PRIMARY_METRICS
        }

    receipt = {
        "review_status": "saved_f1s_models_independently_reloaded_and_replayed",
        "candidate_model_functions_reused": False,
        "candidate_finalizer_functions_reused": False,
        "fit_or_temperature_optimization_executed": False,
        "saved_model_scoring_only": True,
        "combination_energy": "sum of each triple's ascending sorted runner scores, matching the frozen F1 evaluator arithmetic order",
        "year_results": year_results,
        "calibration_fixed_tau_score_checks": calibration_check,
        "population": {
            "candidate_feature_rows": int(len(candidate_features)),
            "candidate_feature_races": int(candidate_features.race_id.nunique()),
            "evaluation_rows": int(len(runners)),
            "evaluation_races": int(races.race_id.nunique()),
            "evaluation_days": int(races.race_date.nunique()),
            "six_set_rows": int(len(tickets)),
            "race_runner_probability_sum3_max_error": float((runners.groupby("race_id", sort=False).p_top3.sum() - 3).abs().max()),
        },
        "model_artifacts": model_artifacts,
        "raw_output_checks": {
            "runner_row_count": int(len(runners)),
            "race_row_count": int(len(races)),
            "six_set_row_count": int(len(tickets)),
            "runner_order_is_stable_saved_feature_order": True,
            "saved_f1s_probabilities_losses_race_metrics_and_tickets_reproduced": comparison.get("candidate_recovery_outputs_present", False),
        },
        "candidate_output_comparison": comparison,
        "primary_race_loss_and_date_ci": primary,
        "retention_candidate_gate_independently_recomputed": gate,
        "interruption_receipt_sha256": sha256(OUT / "fit_execution_interruption.json"),
        "prefit_lock_sha256": sha256(OUT / "prefit_lock.json"),
        "fit_runner_sha256": sha256(MODEL_DIR / "fit_candidate.py"),
        "review_code_sha256": sha256(Path(__file__)),
        "independent_outputs": {path.name: file_info(path) for path in REPLAY_DIR.iterdir() if path.is_file()},
    }
    assert not RECEIPT.exists(), f"refusing to overwrite {RECEIPT}"
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
