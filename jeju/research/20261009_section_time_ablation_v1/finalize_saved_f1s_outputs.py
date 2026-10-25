"""Score saved F1S models and complete reporting without fitting or calibration.

This is a recovery-only postprocessor for the single authorized fit. It loads
the three already-saved models and their frozen temperatures, then regenerates
evaluation outputs. It contains no model fitting or temperature optimization.
"""
import sys

sys.dont_write_bytecode = True

import hashlib
import importlib.util
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
F1_DIR = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
F1_OUT = F1_DIR / "outputs"
YEARS = (2024, 2025, 2026)
NEW_FEATURES = [
    "history_s1f_mean5_seconds", "history_s1f_valid_n",
    "history_g3f_mean5_seconds", "history_g3f_valid_n",
    "history_g1f_mean5_seconds", "history_g1f_valid_n",
]

spec = importlib.util.spec_from_file_location("section_time_f1s_fit_reference", HERE / "fit_candidate.py")
FIT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(FIT)
BASE = FIT.BASE
FEATURES = FIT.FEATURES
MODEL_CATS = FIT.MODEL_CATS


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_new(path, payload):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False,
                  default=lambda value: value.item() if isinstance(value, np.generic) else str(value))
        stream.write("\n")


def save_frame(path, frame, parquet=False):
    with Path(path).open("xb") as stream:
        if parquet:
            frame.to_parquet(stream, index=False)
        else:
            frame.to_csv(stream, index=False)


def add_context_without_duplicate_columns(predictions, features):
    context_columns = [
        "api_record_id", "observed_starts", "same_starts", "same_valid_times",
        "days_since_same", "same_distance_last5_actual_n",
        "history_s1f_valid_n", "history_g3f_valid_n", "history_g1f_valid_n",
    ]
    context = features[context_columns].copy()
    assert context.api_record_id.is_unique
    overlap = [column for column in context_columns if column in predictions.columns and column != "api_record_id"]
    if overlap:
        checked = predictions[["api_record_id", *overlap]].merge(
            context[["api_record_id", *overlap]], on="api_record_id", how="left",
            validate="one_to_one", suffixes=("_prediction", "_feature"),
        )
        for column in overlap:
            left = checked[f"{column}_prediction"]
            right = checked[f"{column}_feature"]
            assert left.equals(right) or np.array_equal(
                left.to_numpy(), right.to_numpy(), equal_nan=True
            ), f"existing prediction context differs from frozen feature row: {column}"
    missing = [column for column in context_columns if column not in predictions.columns]
    if not missing:
        return predictions
    out = predictions.merge(
        context[["api_record_id", *missing]], on="api_record_id", how="left",
        validate="one_to_one", indicator="_context_merge", sort=False,
    )
    assert len(out) == len(predictions)
    assert out["_context_merge"].eq("both").all(), "prediction ID missing from frozen feature context"
    assert out.api_record_id.astype(str).tolist() == predictions.api_record_id.astype(str).tolist()
    expected = predictions[["api_record_id"]].merge(
        context[["api_record_id", *missing]], on="api_record_id", how="left",
        validate="one_to_one", sort=False,
    )
    for column in missing:
        assert out[column].reset_index(drop=True).equals(expected[column].reset_index(drop=True)), column
    out = out.drop(columns="_context_merge")
    return out


def model_lock():
    models = {}
    for year in YEARS:
        folder = OUT / f"F1S_{year}"
        model_path, meta_path = folder / "top3.txt", folder / "meta.json"
        calibration_path = folder / "calibration_scores.parquet"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["variant"] == "F1S" and meta["evaluation_year"] == year
        assert meta["model_sha256"] == sha(model_path)
        assert meta["lightgbm_train_calls"] == 2
        assert meta["temperature_optimizations"] == 1
        assert meta["features"] == FEATURES and len(meta["features"]) == 30
        assert meta["seed"] == 20261008
        models[str(year)] = {
            path.name: {"bytes": path.stat().st_size, "sha256": sha(path)}
            for path in (model_path, meta_path, calibration_path)
        }
    return models


def score_saved_models():
    features = pd.read_parquet(OUT / "features_f1s.parquet")
    assert (len(features), features.race_id.nunique()) == (52155, 5206)
    assert all(column in features.columns for column in FEATURES)
    results = []
    for year in YEARS:
        folder = OUT / f"F1S_{year}"
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        model_path = folder / "top3.txt"
        assert sha(model_path) == meta["model_sha256"]
        # Rebuild from raw frozen features for each year so one model's
        # categorical vocabulary cannot coerce another year's values.
        x = features[FEATURES].copy()
        for column in MODEL_CATS:
            if column in FEATURES:
                x[column] = pd.Categorical(x[column].astype("string"), categories=meta["vocabulary"][column])
        evaluation = features.loc[features.year.eq(year)].reset_index(drop=True)
        test_x = x.loc[features.year.eq(year)]
        assert len(test_x) == len(evaluation) == meta["evaluation_rows"]
        model = lgb.Booster(model_file=str(model_path))
        scores = model.predict(test_x, raw_score=True, num_threads=4)
        race, runner, six_sets = BASE.evaluate(evaluation, scores, float(meta["tau"]), "F1S")
        results.append((race, runner, six_sets))
    races = pd.concat([part[0] for part in results], ignore_index=True)
    runners = pd.concat([part[1] for part in results], ignore_index=True)
    six_sets = pd.concat([part[2] for part in results], ignore_index=True)
    assert (len(runners), runners.race_id.nunique()) == (17412, 1779)
    assert len(races) == 1779 and len(six_sets) == 10674
    return features, races, runners, six_sets


def main():
    expected_new = [
        "f1s_runner_predictions.parquet", "f1s_race_metrics.csv", "f1s_six_combinations.csv",
        "f1s_paired_differences.csv", "f1s_metrics_by_group.csv",
        "f1s_paired_differences_by_group.csv", "f1s_runner_metrics_by_group.csv",
        "f1s_runner_paired_differences_by_group.csv", "f1s_calibration_bins.csv",
        "f1s_operating_common_467_race_metrics.csv",
        "f1s_operating_common_467_runner_predictions.parquet",
        "f1s_operating_common_467_six_combinations.csv", "f1s_operating_common_467_summary.csv",
        "f1s_operating_common_467_paired_differences.csv", "f1s_gate.json",
        "fit_execution_completion.json", "postfit_saved_model_integrity_lock.json",
    ]
    assert not [name for name in expected_new if (OUT / name).exists()], "refusing to overwrite outputs"
    started = json.loads((OUT / "fit_execution_started.json").read_text(encoding="utf-8"))
    lock = json.loads((OUT / "prefit_lock.json").read_text(encoding="utf-8"))
    assert started["prefit_lock_sha256"] == sha(OUT / "prefit_lock.json")
    assert lock["approval_conditions"]["independent_fit_code_review_passed"]
    assert lock["approval_conditions"]["before_fit_check_passed"]
    before = json.loads((OUT / "before_fit_integrity_check.json").read_text(encoding="utf-8"))
    assert before["passed"] and before["phase"] == "before_fit"

    interruption_path = OUT / "fit_execution_interruption.json"
    interruption = json.loads(interruption_path.read_text(encoding="utf-8"))
    assert interruption["fit_counts"] == {"lightgbm_train_calls": 6, "temperature_optimizations": 3}
    saved_model_hashes = model_lock()
    integrity = {
        "lock_type": "postfit_saved_model_integrity_lock",
        "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "fit_execution_started_sha256": sha(OUT / "fit_execution_started.json"),
        "fit_execution_interruption_sha256": sha(interruption_path),
        "prefit_lock_sha256": sha(OUT / "prefit_lock.json"),
        "fit_candidate_sha256": sha(HERE / "fit_candidate.py"),
        "finalizer_sha256": sha(HERE / "finalize_saved_f1s_outputs.py"),
        "saved_models_metadata_calibration_hashes": saved_model_hashes,
    }
    write_json_new(OUT / "postfit_saved_model_integrity_lock.json", integrity)

    features, candidate_races, candidate_runners, candidate_sets = score_saved_models()
    baseline_races = pd.read_csv(OUT / "f1_reproduced_race_metrics.csv")
    baseline_runners = pd.read_parquet(OUT / "f1_reproduced_runner_predictions.parquet")
    baseline_sets = pd.read_csv(OUT / "f1_reproduced_six_combinations.csv")
    assert len(baseline_races) == 1779 and len(baseline_runners) == 17412 and len(baseline_sets) == 10674
    baseline_races["year"] = baseline_races.year.astype(int)
    candidate_races["year"] = candidate_races.year.astype(int)
    baseline_runners = add_context_without_duplicate_columns(baseline_runners, features)
    candidate_runners = add_context_without_duplicate_columns(candidate_runners, features)

    race_groups, paired_race_groups = FIT.race_group_tables(candidate_races, baseline_races)
    runner_groups, paired_runner_groups = FIT.runner_group_tables(candidate_runners, baseline_runners)
    runner_group_races = (
        runner_groups.loc[runner_groups.variant.eq("F1S"), ["group", "value", "races"]]
        .drop_duplicates(["group", "value"])
    )
    paired_runner_groups = paired_runner_groups.merge(
        runner_group_races, on=["group", "value"], how="left", validate="many_to_one",
    )
    assert paired_runner_groups.races.notna().all()
    paired_all = pd.DataFrame([
        {"metric": metric, **FIT.bootstrap_race(candidate_races, baseline_races, metric)}
        for metric in FIT.RACE_METRICS
    ])
    calibration = FIT.calibration_bins(candidate_runners, baseline_runners)
    op_races, op_runners, op_sets, op_summary, op_differences = FIT.operating_common_outputs(
        candidate_races, candidate_runners, candidate_sets
    )

    full = paired_all.set_index("metric")
    losses = {metric: full.loc[metric].to_dict() for metric in FIT.PRIMARY_METRICS}
    baseline_loss = {metric: float(baseline_races[metric].mean()) for metric in FIT.PRIMARY_METRICS}
    candidate_loss = {metric: float(candidate_races[metric].mean()) for metric in FIT.PRIMARY_METRICS}
    gate = (
        all(candidate_loss[metric] < baseline_loss[metric] for metric in FIT.PRIMARY_METRICS)
        and any(float(losses[metric]["ci95_hi"]) < 0 for metric in FIT.PRIMARY_METRICS)
    )

    # Mark descriptive groups with fewer than 30 races as small support. Keep
    # both runner rows and race counts visible in the same tables.
    for frame in (race_groups, paired_race_groups, runner_groups, paired_runner_groups):
        assert "races" in frame.columns
        frame["support_rule"] = "small_support_if_fewer_than_30_races"
        frame["support_status"] = np.where(frame["races"].lt(30), "small_support", "30plus_races")

    output_frames = [
        ("f1s_runner_predictions.parquet", candidate_runners, True),
        ("f1s_race_metrics.csv", candidate_races, False),
        ("f1s_six_combinations.csv", candidate_sets, False),
        ("f1s_paired_differences.csv", paired_all, False),
        ("f1s_metrics_by_group.csv", race_groups, False),
        ("f1s_paired_differences_by_group.csv", paired_race_groups, False),
        ("f1s_runner_metrics_by_group.csv", runner_groups, False),
        ("f1s_runner_paired_differences_by_group.csv", paired_runner_groups, False),
        ("f1s_calibration_bins.csv", calibration, False),
        ("f1s_operating_common_467_race_metrics.csv", op_races, False),
        ("f1s_operating_common_467_runner_predictions.parquet", op_runners, True),
        ("f1s_operating_common_467_six_combinations.csv", op_sets, False),
        ("f1s_operating_common_467_summary.csv", op_summary, False),
        ("f1s_operating_common_467_paired_differences.csv", op_differences, False),
    ]
    for filename, frame, parquet in output_frames:
        save_frame(OUT / filename, frame, parquet)

    write_json_new(OUT / "f1s_gate.json", {
        "candidate": "F1S", "baseline": "F1", "primary_metrics": losses,
        "baseline_primary_loss": baseline_loss, "candidate_primary_loss": candidate_loss,
        "retention_candidate_gate_passed": bool(gate),
        "gate_definition": "both race-equal loss point estimates are lower and at least one date-paired 95% upper bound is below zero",
        "interpretation": "retrospective research candidate only; not independent future validation or production adoption",
        "fit_model_sha256": {year: info["top3.txt"]["sha256"] for year, info in saved_model_hashes.items()},
        "model_fit_repeated_during_postprocessing": False,
        "temperature_optimization_repeated_during_postprocessing": False,
    })

    # Recheck prefit-locked inputs and protected state after scoring/reporting.
    FIT.assert_locked_inputs_and_protection()
    assert model_lock() == saved_model_hashes, "saved F1S models or metadata changed during finalization"
    completion = {
        "passed": True,
        "fit_models": 3,
        "evaluation_years": list(YEARS),
        "lightgbm_train_calls": 6,
        "temperature_optimizations": 3,
        "postfit_scoring_passes": 2,
        "fit_retry_or_refit": False,
        "temperature_retry_or_optimization": False,
        "fit_runner_postprocessing_interruption": "KeyError observed_starts from duplicate context merge; original fit_candidate.py preserved unchanged",
        "result_generation": "separate finalizer loaded saved models and fixed frozen tau values",
        "subgroup_support_label_rule": "support_status=small_support when the subgroup has fewer than 30 races; all tables retain rows/races/days counts where applicable",
        "seed": 20261008,
        "bootstrap_repetitions": 2000,
        "evaluation_rows_per_model": 17412,
        "evaluation_races_per_model": 1779,
        "evaluation_six_set_rows_per_model": 10674,
        "operating_common_races": 467,
        "operating_common_runner_rows_per_model": 4475,
        "retention_candidate_gate_passed": bool(gate),
        "result_dependent_followup_fit": False,
        "production_changed": False,
        "database_changed": False,
        "fit_candidate_sha256": sha(HERE / "fit_candidate.py"),
        "finalizer_sha256": sha(HERE / "finalize_saved_f1s_outputs.py"),
        "prefit_lock_sha256": sha(OUT / "prefit_lock.json"),
        "postfit_model_integrity_lock_sha256": sha(OUT / "postfit_saved_model_integrity_lock.json"),
        "model_files": saved_model_hashes,
        "new_output_sha256": {filename: sha(OUT / filename) for filename, _, _ in output_frames}
        | {"f1s_gate.json": sha(OUT / "f1s_gate.json")},
    }
    write_json_new(OUT / "fit_execution_completion.json", completion)
    print(json.dumps({
        "passed": True, "fit_models": 3, "lightgbm_train_calls": 6,
        "temperature_optimizations": 3, "retention_candidate_gate_passed": bool(gate),
        "primary_losses": losses, "production_changed": False, "database_changed": False,
        "postfit_finalizer_only": True,
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
