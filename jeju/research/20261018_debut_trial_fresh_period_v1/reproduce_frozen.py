"""Verify frozen 30-input history and saved 2026 score outputs in memory.

This preflight reads only the prior studies' immutable artifacts. It does not
open the database, inspect post-2026-09-19 outcomes, fit/calibrate a model, or
write anywhere outside this new study's outputs directory.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
STYLE = ROOT / "jeju/research/20261010_style_history_ablation_v1"
TRIAL = ROOT / "jeju/research/20261018_debut_trial_ablation_v1"
BASE_COLUMNS = [
    "distance_m", "grade_raw", "field_n", "observed_starts", "days_since_start",
    "previous_age", "previous_sex", "same_starts", "same_valid_times", "days_since_same",
    "last_time_s", "mean5_s", "valid_n5", "opp_mean5_valid_n",
    "opp_mean5_valid_fraction", "opp_mean5_median_s", "mean5_minus_opp_mean_s",
    "mean5_minus_opp_median_s", "mean5_minus_opp_fast2mean_s", "opp_mean5_faster_n",
    "mean5_rank_fraction", "previous_finish_relative_rank", "previous_top3",
    "previous_result_status", "hist_s1f_relpos_mean5", "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n",
]
ADDED_COLUMNS = [
    "trial_peer_relative_time_mean3", "trial_peer_relative_time_n3",
    "trial_days_since_latest_event_pre", "trial_event_count_pre",
]
IDENTITY_COLUMNS = [
    "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
]
EXPECTED_ROWS = 52155
EXPECTED_RACES = 5206
EVALUATION_YEAR = 2026


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compare_column(left: pd.Series, right: pd.Series, name: str) -> float:
    if pd.api.types.is_numeric_dtype(left) and pd.api.types.is_numeric_dtype(right):
        a = pd.to_numeric(left, errors="raise").to_numpy(dtype="float64", na_value=np.nan)
        b = pd.to_numeric(right, errors="raise").to_numpy(dtype="float64", na_value=np.nan)
        assert np.allclose(a, b, rtol=0, atol=0, equal_nan=True), f"30-input value changed: {name}"
        return float(np.nanmax(np.abs(a - b))) if np.isfinite(a - b).any() else 0.0
    a = left.astype("string").fillna("<NA>").reset_index(drop=True)
    b = right.astype("string").fillna("<NA>").reset_index(drop=True)
    assert a.equals(b), f"30-input text value changed: {name}"
    return 0.0


def assert_exact_model_input_order(meta: dict, expected: list[str], label: str) -> None:
    assert meta.get("features") == expected, f"{label} input order differs from frozen contract"
    assert int(meta.get("feature_count", -1)) == len(expected), f"{label} input count changed"


def predict_frozen(frame: pd.DataFrame, model_path: Path, meta: dict) -> np.ndarray:
    columns = meta["features"]
    model_input = frame[columns].copy()
    vocabulary = meta["vocabulary"]
    for name, values in vocabulary.items():
        if name in columns:
            model_input[name] = pd.Categorical(
                model_input[name].astype("string"), categories=values
            )
    booster = lgb.Booster(model_file=str(model_path))
    assert booster.num_feature() == len(columns)
    return booster.predict(model_input, raw_score=True, num_threads=4)


def main() -> dict:
    receipt_path = OUT / "historical_reproduction.json"
    assert receipt_path.resolve().is_relative_to(OUT.resolve())
    assert not receipt_path.exists(), "refusing to overwrite the historical preflight receipt"

    style_features_path = STYLE / "outputs/features.parquet"
    trial_features_path = TRIAL / "outputs/features_f1_style6_debut_trial4.parquet"
    style_features = pd.read_parquet(style_features_path)
    trial_features = pd.read_parquet(trial_features_path)
    assert len(style_features) == len(trial_features) == EXPECTED_ROWS
    assert style_features.race_id.nunique() == trial_features.race_id.nunique() == EXPECTED_RACES
    assert style_features.api_record_id.is_unique and trial_features.api_record_id.is_unique
    assert style_features.api_record_id.astype("int64").equals(
        trial_features.api_record_id.astype("int64")
    ), "saved F1_STYLE6 row order/identity differs in the prior trial study"

    missing_base = set(IDENTITY_COLUMNS + BASE_COLUMNS) - set(style_features.columns)
    missing_trial = set(IDENTITY_COLUMNS + BASE_COLUMNS + ADDED_COLUMNS) - set(trial_features.columns)
    assert not missing_base, f"saved F1_STYLE6 table lacks {sorted(missing_base)}"
    assert not missing_trial, f"prior trial table lacks {sorted(missing_trial)}"
    max_base_error = {
        name: compare_column(style_features[name], trial_features[name], name)
        for name in IDENTITY_COLUMNS + BASE_COLUMNS
    }

    preflight_path = TRIAL / "outputs/preflight_verification.json"
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    assert preflight.get("passed") is True
    assert preflight.get("base_feature_values_exact") is True
    assert preflight.get("input_dataset", {}).get("row_order_exact") is True
    assert int(preflight.get("candidate_feature_count", -1)) == 34

    baseline_folder = STYLE / "outputs/F1_STYLE6_2026"
    candidate_folder = TRIAL / "outputs/F1_STYLE6_DEBUT_TRIAL4_2026"
    baseline_meta_path = baseline_folder / "meta.json"
    candidate_meta_path = candidate_folder / "meta.json"
    baseline_meta = json.loads(baseline_meta_path.read_text(encoding="utf-8"))
    candidate_meta = json.loads(candidate_meta_path.read_text(encoding="utf-8"))
    assert_exact_model_input_order(baseline_meta, BASE_COLUMNS, "F1_STYLE6 baseline")
    assert_exact_model_input_order(candidate_meta, BASE_COLUMNS + ADDED_COLUMNS,
                                   "F1_STYLE6_DEBUT_TRIAL4 candidate")
    assert candidate_meta.get("features", [])[:len(BASE_COLUMNS)] == BASE_COLUMNS
    assert candidate_meta.get("features", [])[len(BASE_COLUMNS):] == ADDED_COLUMNS
    assert baseline_meta["vocabulary"] == candidate_meta["vocabulary"]
    assert baseline_meta["parameters"] == candidate_meta["parameters"]
    assert baseline_meta["seed"] == candidate_meta["seed"] == 20261008

    baseline_model = baseline_folder / "top3.txt"
    candidate_model = candidate_folder / "top3.txt"
    assert sha256(baseline_model) == baseline_meta["model_sha256"]
    assert sha256(candidate_model) == candidate_meta["model_sha256"]

    evaluation_features = trial_features.loc[trial_features.year.eq(EVALUATION_YEAR)].reset_index(drop=True)
    assert len(evaluation_features) == 4673
    baseline_evaluation_features = style_features.loc[
        style_features.year.eq(EVALUATION_YEAR)
    ].reset_index(drop=True)
    assert evaluation_features.api_record_id.astype("int64").equals(
        baseline_evaluation_features.api_record_id.astype("int64")
    )

    replay_receipts = []
    for label, frame, model, meta, folder in (
        ("F1_STYLE6", baseline_evaluation_features, baseline_model, baseline_meta, baseline_folder),
        ("F1_STYLE6_DEBUT_TRIAL4", evaluation_features, candidate_model, candidate_meta, candidate_folder),
    ):
        score_path = folder / "evaluation_scores.parquet"
        locked_scores = pd.read_parquet(score_path)
        assert locked_scores.api_record_id.astype("int64").tolist() == frame.api_record_id.astype("int64").tolist()
        replayed = predict_frozen(frame, model, meta)
        stored = locked_scores.score.to_numpy(dtype="float64")
        assert np.array_equal(replayed, stored), f"saved {label} raw scores do not replay exactly"
        replay_receipts.append({
            "model": label,
            "model_sha256": sha256(model),
            "meta_sha256": sha256(folder / "meta.json"),
            "tau_frozen": float(meta["tau"]),
            "saved_score_sha256": sha256(score_path),
            "runner_rows_replayed": int(len(replayed)),
            "raw_score_replay_exact": True,
            "maximum_raw_score_error": 0.0,
        })

    receipt = {
        "passed": True,
        "status": "historical_input_and_saved_score_reproduction_only",
        "new_period_roster_locked": False,
        "new_period_outcome_metrics_computed": False,
        "candidate_fit_or_calibration_calls": 0,
        "source_inputs": {
            "F1_STYLE6_features": {
                "path": str(style_features_path.relative_to(ROOT)),
                "sha256": sha256(style_features_path),
                "rows": int(len(style_features)),
                "races": int(style_features.race_id.nunique()),
            },
            "prior_trial_features": {
                "path": str(trial_features_path.relative_to(ROOT)),
                "sha256": sha256(trial_features_path),
                "rows": int(len(trial_features)),
            },
            "prior_trial_preflight": {
                "path": str(preflight_path.relative_to(ROOT)),
                "sha256": sha256(preflight_path),
            },
            "this_script_sha256": sha256(Path(__file__)),
        },
        "base_inputs_exact_and_in_order": True,
        "base_input_max_absolute_error": max(max_base_error.values(), default=0.0),
        "base_input_column_max_absolute_error": max_base_error,
        "historical_2026_evaluation_rows": int(len(evaluation_features)),
        "saved_2026_model_replays": replay_receipts,
        "guardrails": {
            "database_opened": False,
            "new_period_outcome_rows_read": False,
            "outcome_metrics_computed": False,
            "stored_models_changed": False,
            "stored_model_vocabulary_changed": False,
            "stored_tau_changed": False,
        },
    }
    with receipt_path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return receipt


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2))
