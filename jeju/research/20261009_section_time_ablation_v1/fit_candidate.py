"""One gated F1S fit: three evaluation years, no search or follow-up models.

The file can only execute training with the explicit --root-approved flag.
It reuses the established F1 training split, feature weighting, category
vocabulary rule, temperature routine, and additive-set evaluator.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

import lightgbm as lgb
import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
F1_DIR = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
F1_OUT = F1_DIR / "outputs"
F1_RUN = F1_DIR / "run.py"
FEATURES_PATH = OUT / "features_f1s.parquet"
YEARS = (2024, 2025, 2026)
BOOTSTRAP_REPS = 2000
BOOTSTRAP_SEED = 20261008

_spec = importlib.util.spec_from_file_location("section_time_f1_training_reference", F1_RUN)
if str(F1_DIR) not in sys.path:
    sys.path.insert(0, str(F1_DIR))
F1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F1)
BASE = F1.OLD
PARAMS = BASE.PARAMS
MODEL_CATS = F1.MODEL_CATS
BASE_FEATURES = json.loads((F1_OUT / "F1_2024/meta.json").read_text(encoding="utf-8"))["features"]
NEW_FEATURES = [
    "history_s1f_mean5_seconds", "history_s1f_valid_n",
    "history_g3f_mean5_seconds", "history_g3f_valid_n",
    "history_g1f_mean5_seconds", "history_g1f_valid_n",
]
FEATURES = BASE_FEATURES + NEW_FEATURES
RACE_METRICS = list(BASE.METRICS)
PRIMARY_METRICS = ["log_loss", "brier"]


def sha(path):
    return F1.e.sha(path)


def write_json_new(path, payload):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False,
                  default=lambda value: value.item() if isinstance(value, np.generic) else str(value))
        stream.write("\n")


def write_csv_new(path, frame):
    with Path(path).open("x", encoding="utf-8") as stream:
        frame.to_csv(stream, index=False)


def assert_locked_inputs_and_protection():
    lock = json.loads((OUT / "prefit_lock.json").read_text(encoding="utf-8"))
    assert lock["fit_authorization_state"] == "conditional_root_approval_granted"
    assert lock["approval_conditions"]["independent_fit_code_review_passed"] is True
    assert lock["approval_conditions"]["before_fit_check_passed"] is True
    assert lock["fit_executed"] is False
    check = json.loads((OUT / "before_fit_integrity_check.json").read_text(encoding="utf-8"))
    assert check["passed"] and check["phase"] == "before_fit"
    for relative, info in lock["scoped_reference_sha256"].items():
        path = ROOT / relative
        assert path.stat().st_size == info["bytes"] and sha(path) == info["sha256"], relative
    for relative, info in lock["protected_live_state_sha256"].items():
        path = ROOT / relative
        assert path.stat().st_size == info["bytes"] and sha(path) == info["sha256"], relative
    assert json.loads((OUT / "candidate_feature_preflight.json").read_text(encoding="utf-8"))["passed"]
    assert json.loads((OUT / "f1_saved_model_replay.json").read_text(encoding="utf-8"))["passed"]
    return lock


def save_frame(path, frame, parquet=False):
    with Path(path).open("xb") as stream:
        if parquet:
            frame.to_parquet(stream, index=False)
        else:
            frame.to_csv(stream, index=False)


def check_output_absence():
    expected_new = [
        OUT / f"F1S_{year}" for year in YEARS
    ] + [
        OUT / "fit_execution_started.json", OUT / "f1s_runner_predictions.parquet",
        OUT / "f1s_race_metrics.csv", OUT / "f1s_six_combinations.csv",
        OUT / "f1s_paired_differences.csv", OUT / "f1s_metrics_by_group.csv",
        OUT / "f1s_paired_differences_by_group.csv", OUT / "f1s_runner_metrics_by_group.csv",
        OUT / "f1s_runner_paired_differences_by_group.csv", OUT / "f1s_calibration_bins.csv",
        OUT / "f1s_operating_common_467_race_metrics.csv",
        OUT / "f1s_operating_common_467_runner_predictions.parquet",
        OUT / "f1s_operating_common_467_six_combinations.csv",
        OUT / "f1s_operating_common_467_summary.csv",
        OUT / "f1s_operating_common_467_paired_differences.csv",
        OUT / "f1s_gate.json", OUT / "fit_execution_completion.json",
    ]
    existing = [str(path) for path in expected_new if path.exists()]
    assert not existing, f"refusing to overwrite existing fit output(s): {existing}"


def fit_year(features, year, counter):
    train_mask = features.year.between(2017, year - 3)
    valid_mask = features.year.eq(year - 2)
    calibration_mask = features.year.eq(year - 1)
    test_mask = features.year.eq(year)
    assert all(mask.any() for mask in (train_mask, valid_mask, calibration_mask, test_mask))
    assert train_mask.sum() > 0 and not (train_mask & valid_mask).any()
    assert not (valid_mask & calibration_mask).any() and not (calibration_mask & test_mask).any()

    x = features[FEATURES].copy()
    vocabulary = {}
    for column in MODEL_CATS:
        if column in FEATURES:
            vocabulary[column] = sorted(
                features.loc[train_mask, column].dropna().astype(str).unique().tolist()
            )
            x[column] = pd.Categorical(x[column].astype("string"), categories=vocabulary[column])

    # Because only six numeric fields are appended, the old F1 categorical
    # vocabularies must stay identical to those saved with the frozen models.
    saved_meta = json.loads((F1_OUT / f"F1_{year}/meta.json").read_text(encoding="utf-8"))
    assert saved_meta["parameters"] == PARAMS
    assert saved_meta["seed"] == BOOTSTRAP_SEED
    assert saved_meta["vocabulary"] == vocabulary

    target = features.finish_position.le(3).astype(int)
    weight = 1 / features.field_n

    def dataset(mask):
        return lgb.Dataset(
            x.loc[mask], label=target.loc[mask], weight=weight.loc[mask], free_raw_data=False,
        )

    initial = lgb.train(
        PARAMS, dataset(train_mask), num_boost_round=200, valid_sets=[dataset(valid_mask)],
        callbacks=[lgb.early_stopping(25, verbose=False)],
    )
    counter["lightgbm_train_calls"] += 1
    assert initial.best_iteration > 0
    model = lgb.train(
        PARAMS, dataset(train_mask | valid_mask), num_boost_round=initial.best_iteration,
    )
    counter["lightgbm_train_calls"] += 1

    calibration = features.loc[calibration_mask].reset_index(drop=True)
    evaluation = features.loc[test_mask].reset_index(drop=True)
    cal_x = x.loc[calibration_mask]
    test_x = x.loc[test_mask]
    cal_scores = model.predict(cal_x, raw_score=True, num_threads=4)
    test_scores = model.predict(test_x, raw_score=True, num_threads=4)
    tau = BASE.temperature(calibration, cal_scores)
    counter["temperature_optimizations"] += 1
    assert np.isfinite(tau) and 0.35 <= tau <= 4.0

    folder = OUT / f"F1S_{year}"
    folder.mkdir(exist_ok=False)
    model_path = folder / "top3.txt"
    model.save_model(str(model_path))
    metadata = {
        "variant": "F1S", "evaluation_year": year, "features": FEATURES,
        "vocabulary": vocabulary, "trees": int(initial.best_iteration), "tau": float(tau),
        "seed": BOOTSTRAP_SEED, "parameters": PARAMS,
        "lightgbm_train_calls": 2, "temperature_optimizations": 1,
        "training_min": str(features.loc[train_mask, "race_date"].min()),
        "initial_training_max": str(features.loc[train_mask, "race_date"].max()),
        "early_stopping_min": str(features.loc[valid_mask, "race_date"].min()),
        "refit_max": str(features.loc[valid_mask, "race_date"].max()),
        "calibration_min": str(features.loc[calibration_mask, "race_date"].min()),
        "calibration_max": str(features.loc[calibration_mask, "race_date"].max()),
        "evaluation_min": str(features.loc[test_mask, "race_date"].min()),
        "evaluation_max": str(features.loc[test_mask, "race_date"].max()),
        "train_rows": int((train_mask | valid_mask).sum()),
        "train_races": int(features.loc[train_mask | valid_mask, "race_id"].nunique()),
        "calibration_rows": int(calibration_mask.sum()),
        "calibration_races": int(calibration.race_id.nunique()),
        "evaluation_rows": int(test_mask.sum()),
        "evaluation_races": int(evaluation.race_id.nunique()),
        "model_sha256": sha(model_path),
        "gain": dict(zip(FEATURES, map(float, model.feature_importance(importance_type="gain")))),
    }
    write_json_new(folder / "meta.json", metadata)
    save_frame(folder / "calibration_scores.parquet", pd.DataFrame({
        "api_record_id": calibration.api_record_id.to_numpy(), "score": cal_scores,
    }), parquet=True)
    race_result, runner_result, set_result = BASE.evaluate(
        evaluation, test_scores, tau, "F1S"
    )
    print(
        f"F1S {year}: trees={initial.best_iteration}, tau={tau:.6f}, "
        f"{len(runner_result):,} runners/{len(race_result):,} races.", flush=True,
    )
    return race_result, runner_result, set_result


def bootstrap_race(candidate, baseline, metric):
    left = candidate[["race_id", "race_date", metric]].rename(columns={metric: "candidate"})
    right = baseline[["race_id", metric]].rename(columns={metric: "f1"})
    pair = left.merge(right, on="race_id", how="inner", validate="one_to_one")
    assert len(pair) == len(candidate) == len(baseline)
    pair["delta"] = pair.candidate - pair.f1
    daily = pair.groupby("race_date").delta.agg(["sum", "size"])
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    indices = rng.integers(0, len(daily), size=(BOOTSTRAP_REPS, len(daily)))
    samples = (
        daily["sum"].to_numpy()[indices].sum(axis=1)
        / daily["size"].to_numpy()[indices].sum(axis=1)
    )
    return {
        "delta_f1s_minus_f1": float(pair.delta.mean()),
        "ci95_lo": float(np.quantile(samples, 0.025)),
        "ci95_hi": float(np.quantile(samples, 0.975)),
        "races": int(len(pair)), "days": int(len(daily)),
        "resamples": BOOTSTRAP_REPS, "seed": BOOTSTRAP_SEED,
    }


def bootstrap_runner(candidate, baseline, metric):
    left = candidate[["api_record_id", "race_date", metric]].rename(columns={metric: "candidate"})
    right = baseline[["api_record_id", metric]].rename(columns={metric: "f1"})
    pair = left.merge(right, on="api_record_id", how="inner", validate="one_to_one")
    assert len(pair) == len(candidate) == len(baseline)
    pair["delta"] = pair.candidate - pair.f1
    daily = pair.groupby("race_date").delta.agg(["sum", "size"])
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    indices = rng.integers(0, len(daily), size=(BOOTSTRAP_REPS, len(daily)))
    samples = (
        daily["sum"].to_numpy()[indices].sum(axis=1)
        / daily["size"].to_numpy()[indices].sum(axis=1)
    )
    return {
        "delta_f1s_minus_f1": float(pair.delta.mean()),
        "ci95_lo": float(np.quantile(samples, 0.025)),
        "ci95_hi": float(np.quantile(samples, 0.975)),
        "rows": int(len(pair)), "days": int(len(daily)),
        "resamples": BOOTSTRAP_REPS, "seed": BOOTSTRAP_SEED,
    }


def add_context(predictions, features):
    context = features[[
        "api_record_id", "observed_starts", "same_starts", "same_distance_last5_actual_n",
        "history_s1f_valid_n", "history_g3f_valid_n", "history_g1f_valid_n",
    ]]
    return predictions.merge(context, on="api_record_id", how="left", validate="one_to_one")


def race_group_tables(candidate_races, baseline_races):
    groups = [("all", "all", candidate_races, baseline_races)]
    for year, part in candidate_races.groupby("year", sort=True):
        ref = baseline_races.loc[baseline_races.year.eq(year)]
        groups.append(("year", str(int(year)), part, ref))
    for distance, part in candidate_races.groupby("distance_m", sort=True):
        ref = baseline_races.loc[baseline_races.distance_m.eq(distance)]
        groups.append(("distance_m", str(int(distance)), part, ref))
    rows, diffs = [], []
    for kind, value, candidate, baseline in groups:
        for variant, frame in (("F1", baseline), ("F1S", candidate)):
            rows.append({
                "group": kind, "value": value, "variant": variant,
                "races": len(frame), "days": frame.race_date.nunique(),
                **{metric: float(frame[metric].mean()) for metric in RACE_METRICS},
            })
        for metric in RACE_METRICS:
            diffs.append({
                "group": kind, "value": value, "metric": metric,
                **bootstrap_race(candidate, baseline, metric),
            })
    return pd.DataFrame(rows), pd.DataFrame(diffs)


def runner_group_tables(candidate, baseline):
    groups = [("all", "all", candidate, baseline)]
    for year, part in candidate.groupby("year", sort=True):
        groups.append(("year", str(int(year)), part, baseline.loc[baseline.year.eq(year)]))
    for distance, part in candidate.groupby("distance_m", sort=True):
        groups.append(("distance_m", str(int(distance)), part, baseline.loc[baseline.distance_m.eq(distance)]))
    for column in ("observed_starts", "same_distance_last5_actual_n"):
        bins = pd.cut(candidate[column], [-1, 0, 4, np.inf], labels=["0", "1_4", "5_plus"])
        base_bins = pd.cut(baseline[column], [-1, 0, 4, np.inf], labels=["0", "1_4", "5_plus"])
        for label in ("0", "1_4", "5_plus"):
            groups.append((column, label, candidate.loc[bins.astype("string").eq(label)],
                           baseline.loc[base_bins.astype("string").eq(label)]))
    for column in ("history_s1f_valid_n", "history_g3f_valid_n", "history_g1f_valid_n"):
        for n in range(6):
            groups.append((column, str(n), candidate.loc[candidate[column].eq(n)],
                           baseline.loc[baseline[column].eq(n)]))

    rows, diffs = [], []
    for kind, value, candidate_frame, baseline_frame in groups:
        if candidate_frame.empty:
            continue
        for variant, frame in (("F1", baseline_frame), ("F1S", candidate_frame)):
            rows.append({
                "group": kind, "value": value, "variant": variant,
                "rows": len(frame), "races": frame.race_id.nunique(),
                "runner_mean_log_loss": float(frame.log_loss.mean()),
                "runner_mean_brier": float(frame.brier.mean()),
                "mean_p_top3": float(frame.p_top3.mean()),
                "observed_top3_rate": float(frame.y.mean()),
            })
        for metric in ("log_loss", "brier"):
            diffs.append({
                "group": kind, "value": value, "metric": metric,
                **bootstrap_runner(candidate_frame, baseline_frame, metric),
            })
    return pd.DataFrame(rows), pd.DataFrame(diffs)


def calibration_bins(candidate, baseline):
    rows = []
    edges = np.arange(0, 1.0001, 0.1)
    for variant, frame in (("F1", baseline), ("F1S", candidate)):
        bins = pd.cut(frame.p_top3, edges, include_lowest=True)
        for interval, part in frame.groupby(bins, observed=True):
            weight = 1 / part.field_n
            rows.append({
                "variant": variant, "probability_bin": str(interval), "rows": len(part),
                "races": part.race_id.nunique(),
                "predicted": float(np.average(part.p_top3, weights=weight)),
                "observed": float(np.average(part.y, weights=weight)),
            })
    return pd.DataFrame(rows)


def operating_common_outputs(candidate_races, candidate_runners, candidate_sets):
    baseline_race_path = F1_OUT / "operating_common_467_race_metrics.csv"
    baseline_runner_path = F1_OUT / "operating_common_467_runner_predictions.parquet"
    baseline_sets_path = F1_OUT / "operating_common_467_six_combinations.csv"
    prior_races = pd.read_csv(baseline_race_path)
    prior_runners = pd.read_parquet(baseline_runner_path)
    prior_sets = pd.read_csv(baseline_sets_path)
    common_ids = set(prior_races.loc[prior_races.variant.eq("HY_R_FORM"), "race_id"])
    assert len(common_ids) == 467
    candidate_2026 = candidate_runners.loc[
        candidate_runners.year.eq(2026) & candidate_runners.race_id.isin(common_ids)
    ].copy()
    assert len(candidate_2026) == 4475
    reference = prior_runners.loc[prior_runners.variant.eq("HY_R_FORM")].copy()
    left = candidate_2026.sort_values(["race_id", "horse_id"], kind="stable").reset_index(drop=True)
    right = reference.sort_values(["race_id", "horse_id"], kind="stable").reset_index(drop=True)
    assert left[["race_id", "horse_id", "y"]].astype(str).equals(
        right[["race_id", "horse_id", "y"]].astype(str)
    )

    race_by_id = candidate_races.set_index("race_id", drop=False)
    candidate_op_races = []
    for race_id, group in candidate_2026.groupby("race_id", sort=False):
        group = group.sort_values("horse_number", kind="stable")
        ranked = group.sort_values("score", ascending=False, kind="stable")
        metrics = race_by_id.loc[race_id]
        candidate_op_races.append({
            "race_id": race_id, "race_date": str(group.race_date.iloc[0]),
            "distance_m": int(group.distance_m.iloc[0]), "field_n": int(len(group)),
            "variant": "F1S", "brier": float(metrics.brier),
            "log_loss": float(metrics.log_loss), "pick_hit": int(ranked.y.iloc[0]),
            "top3_all3": int(metrics.top3_all3), "top5_all3": int(metrics.top5_all3),
            "top5_capture": float(metrics.top5_capture),
            "six_combo_hit": int(metrics.six_combo_hit),
        })
    candidate_op_races = pd.DataFrame(candidate_op_races)
    selected_prior_races = prior_races.loc[prior_races.variant.isin(["HY_R_FORM", "F1"])].copy()
    op_races = pd.concat([selected_prior_races, candidate_op_races], ignore_index=True)
    op_metrics = ["brier", "log_loss", "pick_hit", "top3_all3", "top5_all3", "top5_capture", "six_combo_hit"]
    summary = op_races.groupby("variant", sort=True).agg(
        races=("race_id", "nunique"), days=("race_date", "nunique"),
        **{metric: (metric, "mean") for metric in op_metrics},
    ).reset_index()
    differences = []
    for comparison, left_variant, right_variant in (
        ("F1S-HY_R_FORM", "F1S", "HY_R_FORM"),
        ("F1S-F1", "F1S", "F1"),
    ):
        for metric in op_metrics:
            differences.append({
                "comparison": comparison, "metric": metric,
                **bootstrap_race(
                    op_races.loc[op_races.variant.eq(left_variant)],
                    op_races.loc[op_races.variant.eq(right_variant)], metric,
                ),
            })
    op_runner = pd.concat([
        prior_runners.loc[prior_runners.variant.isin(["HY_R_FORM", "F1"])],
        candidate_2026,
    ], ignore_index=True)
    op_sets = pd.concat([
        prior_sets.loc[prior_sets.variant.isin(["HY_R_FORM", "F1"])],
        candidate_sets.loc[candidate_sets.race_id.isin(common_ids)],
    ], ignore_index=True)
    assert op_races.groupby("variant").race_id.nunique().eq(467).all()
    assert op_runner.groupby("variant").size().eq(4475).all()
    return op_races, op_runner, op_sets, summary, pd.DataFrame(differences)


def run_preflight():
    """Verify fixed split, weight, vocabulary, and call counts without fitting."""
    candidate_preflight = json.loads(
        (OUT / "candidate_feature_preflight.json").read_text(encoding="utf-8")
    )
    replay = json.loads((OUT / "f1_saved_model_replay.json").read_text(encoding="utf-8"))
    assert candidate_preflight["passed"] and replay["passed"]
    features = pd.read_parquet(FEATURES_PATH)
    assert (len(features), features.race_id.nunique()) == (52155, 5206)
    assert len(BASE_FEATURES) == 24 and len(FEATURES) == 30
    assert FEATURES == candidate_preflight["model_columns_f1s"]
    assert all(column in features.columns for column in FEATURES)

    yearly = {}
    for year in YEARS:
        train = features.year.between(2017, year - 3)
        valid = features.year.eq(year - 2)
        calibration = features.year.eq(year - 1)
        test = features.year.eq(year)
        assert all(mask.any() for mask in (train, valid, calibration, test))
        assert features.loc[train, "year"].max() <= year - 3
        assert features.loc[valid, "year"].eq(year - 2).all()
        assert features.loc[calibration, "year"].eq(year - 1).all()
        assert features.loc[test, "year"].eq(year).all()
        train_weights = (1 / features.loc[train, "field_n"]).groupby(
            features.loc[train, "race_id"]
        ).sum()
        assert np.allclose(train_weights.to_numpy(float), 1.0, rtol=0, atol=1e-12)

        vocabulary = {}
        for column in MODEL_CATS:
            if column in FEATURES:
                vocabulary[column] = sorted(
                    features.loc[train, column].dropna().astype(str).unique().tolist()
                )
        meta = json.loads((F1_OUT / f"F1_{year}/meta.json").read_text(encoding="utf-8"))
        assert meta["parameters"] == PARAMS
        assert meta["seed"] == BOOTSTRAP_SEED
        assert meta["features"] == BASE_FEATURES
        assert meta["vocabulary"] == vocabulary
        yearly[str(year)] = {
            "initial_train_years": [2017, year - 3],
            "initial_train_rows": int(train.sum()),
            "initial_train_races": int(features.loc[train, "race_id"].nunique()),
            "early_stop_year": year - 2,
            "early_stop_rows": int(valid.sum()),
            "early_stop_races": int(features.loc[valid, "race_id"].nunique()),
            "refit_through_year": year - 2,
            "refit_rows": int((train | valid).sum()),
            "refit_races": int(features.loc[train | valid, "race_id"].nunique()),
            "calibration_year": year - 1,
            "calibration_rows": int(calibration.sum()),
            "calibration_races": int(features.loc[calibration, "race_id"].nunique()),
            "evaluation_rows": int(test.sum()),
            "evaluation_races": int(features.loc[test, "race_id"].nunique()),
            "existing_f1_trees": int(meta["trees"]),
            "category_vocabulary_matches_frozen_f1": True,
            "race_weight_sum_is_one": True,
        }
    receipt = {
        "passed": True,
        "fit_executed": False,
        "saved_model_scoring_executed": False,
        "temperature_optimization_executed": False,
        "prediction_metrics_calculated": False,
        "model_columns": FEATURES,
        "model_column_count": len(FEATURES),
        "parameters": PARAMS,
        "seed": BOOTSTRAP_SEED,
        "expected_lightgbm_train_calls": 6,
        "expected_temperature_optimizations": 3,
        "resampling": {"unit": "race_date", "repetitions": BOOTSTRAP_REPS, "seed": BOOTSTRAP_SEED},
        "yearly_split_and_vocab_checks": yearly,
        "f1_fit_harness_reference": str(F1_RUN.relative_to(ROOT)),
        "candidate_fit_code_sha256": sha(HERE / "fit_candidate.py"),
    }
    write_json_new(OUT / "fit_runner_preflight.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--preflight", action="store_true",
                         help="check split, weight, vocabulary, and run budget without fitting")
    actions.add_argument("--root-approved", action="store_true",
                         help="execute only after supervisor conditions and approval are recorded")
    args = parser.parse_args()
    if args.preflight:
        run_preflight()
        return
    if not args.root_approved:
        parser.error("training is gated; pass --root-approved only after the supervisor conditions pass")

    lock = assert_locked_inputs_and_protection()
    check_output_absence()
    features = pd.read_parquet(FEATURES_PATH)
    assert (len(features), features.race_id.nunique()) == (52155, 5206)
    assert FEATURES == lock["fit_scope"]["model_columns"]
    assert len(FEATURES) == 30 and len(BASE_FEATURES) == 24
    assert all(column in features.columns for column in FEATURES)

    started = {
        "root_approval_evidence": "Root conditionally authorized one F1S three-year fit after run-code review and before_fit integrity PASS; execute without another wait when both conditions are met.",
        "authorization_scope": "2024/2025/2026 F1S only; 6 LightGBM train calls; 3 temperature optimizations; no result-based follow-up fit.",
        "approval_conditions": lock["approval_conditions"],
        "prefit_lock_sha256": sha(OUT / "prefit_lock.json"),
        "run_code_sha256": sha(HERE / "fit_candidate.py"),
        "started_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    write_json_new(OUT / "fit_execution_started.json", started)

    counter = {"lightgbm_train_calls": 0, "temperature_optimizations": 0}
    results = [fit_year(features, year, counter) for year in YEARS]
    assert counter == {"lightgbm_train_calls": 6, "temperature_optimizations": 3}, counter
    candidate_races = pd.concat([item[0] for item in results], ignore_index=True)
    candidate_runners = pd.concat([item[1] for item in results], ignore_index=True)
    candidate_sets = pd.concat([item[2] for item in results], ignore_index=True)
    assert (len(candidate_runners), candidate_runners.race_id.nunique()) == (17412, 1779)
    assert len(candidate_races) == 1779 and len(candidate_sets) == 10674

    baseline_races = pd.read_csv(OUT / "f1_reproduced_race_metrics.csv")
    baseline_runners = pd.read_parquet(OUT / "f1_reproduced_runner_predictions.parquet")
    baseline_sets = pd.read_csv(OUT / "f1_reproduced_six_combinations.csv")
    assert len(baseline_races) == 1779 and len(baseline_runners) == 17412
    assert len(baseline_sets) == 10674
    baseline_races["year"] = baseline_races.year.astype(int)
    candidate_races["year"] = candidate_races.year.astype(int)
    baseline_runners = add_context(baseline_runners, features)
    candidate_runners = add_context(candidate_runners, features)

    race_groups, paired_race_groups = race_group_tables(candidate_races, baseline_races)
    runner_groups, paired_runner_groups = runner_group_tables(candidate_runners, baseline_runners)
    paired_all = pd.DataFrame([
        {"metric": metric, **bootstrap_race(candidate_races, baseline_races, metric)}
        for metric in RACE_METRICS
    ])
    calibration = calibration_bins(candidate_runners, baseline_runners)
    op_races, op_runners, op_sets, op_summary, op_differences = operating_common_outputs(
        candidate_races, candidate_runners, candidate_sets
    )

    full = paired_all.set_index("metric")
    losses = {metric: full.loc[metric].to_dict() for metric in PRIMARY_METRICS}
    baseline_loss = {metric: float(baseline_races[metric].mean()) for metric in PRIMARY_METRICS}
    candidate_loss = {metric: float(candidate_races[metric].mean()) for metric in PRIMARY_METRICS}
    gate = (
        all(candidate_loss[metric] < baseline_loss[metric] for metric in PRIMARY_METRICS)
        and any(float(losses[metric]["ci95_hi"]) < 0 for metric in PRIMARY_METRICS)
    )

    output_frames = [
        (OUT / "f1s_runner_predictions.parquet", candidate_runners, True),
        (OUT / "f1s_race_metrics.csv", candidate_races, False),
        (OUT / "f1s_six_combinations.csv", candidate_sets, False),
        (OUT / "f1s_paired_differences.csv", paired_all, False),
        (OUT / "f1s_metrics_by_group.csv", race_groups, False),
        (OUT / "f1s_paired_differences_by_group.csv", paired_race_groups, False),
        (OUT / "f1s_runner_metrics_by_group.csv", runner_groups, False),
        (OUT / "f1s_runner_paired_differences_by_group.csv", paired_runner_groups, False),
        (OUT / "f1s_calibration_bins.csv", calibration, False),
        (OUT / "f1s_operating_common_467_race_metrics.csv", op_races, False),
        (OUT / "f1s_operating_common_467_runner_predictions.parquet", op_runners, True),
        (OUT / "f1s_operating_common_467_six_combinations.csv", op_sets, False),
        (OUT / "f1s_operating_common_467_summary.csv", op_summary, False),
        (OUT / "f1s_operating_common_467_paired_differences.csv", op_differences, False),
    ]
    for path, frame, parquet in output_frames:
        save_frame(path, frame, parquet)
    write_json_new(OUT / "f1s_gate.json", {
        "candidate": "F1S", "baseline": "F1", "primary_metrics": losses,
        "baseline_primary_loss": baseline_loss, "candidate_primary_loss": candidate_loss,
        "retention_candidate_gate_passed": bool(gate),
        "gate_definition": "both race-equal loss point estimates are lower and at least one date-paired 95% upper bound is below zero",
        "interpretation": "retrospective research candidate only; not independent future validation or production adoption",
    })

    # Recheck every locked read-only input and all four protected live-state files
    # after fitting and evaluation, before writing the completion receipt.
    assert_locked_inputs_and_protection()
    completion = {
        "passed": True,
        "models": 3,
        "evaluation_years": list(YEARS),
        "lightgbm_train_calls": counter["lightgbm_train_calls"],
        "temperature_optimizations": counter["temperature_optimizations"],
        "seed": BOOTSTRAP_SEED,
        "bootstrap_repetitions": BOOTSTRAP_REPS,
        "evaluation_rows_per_model": 17412,
        "evaluation_races_per_model": 1779,
        "evaluation_six_set_rows_per_model": 10674,
        "operating_common_races": 467,
        "operating_common_runner_rows_per_model": 4475,
        "retention_candidate_gate_passed": bool(gate),
        "result_dependent_followup_fit": False,
        "production_changed": False,
        "database_changed": False,
        "prefit_lock_sha256": sha(OUT / "prefit_lock.json"),
        "outputs": {path.name: sha(path) for path in OUT.iterdir() if path.is_file()},
        "model_files": {
            str(path.relative_to(OUT)): sha(path)
            for year in YEARS for path in (OUT / f"F1S_{year}").iterdir() if path.is_file()
        },
    }
    write_json_new(OUT / "fit_execution_completion.json", completion)
    print(json.dumps({
        "passed": True, "fit_models": 3,
        "lightgbm_train_calls": counter["lightgbm_train_calls"],
        "temperature_optimizations": counter["temperature_optimizations"],
        "retention_candidate_gate_passed": bool(gate),
        "primary_losses": losses,
        "production_changed": False, "database_changed": False,
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
