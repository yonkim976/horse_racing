"""Gated 3-fold fit for the single 40-input F1_STYLE6 distance-relative-section candidate.

The existing F1_STYLE6 baseline is never fitted here. This runner requires a
root approval receipt tied to the exact source/preparation/code hashes.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

import lightgbm as lgb
import numpy as np
import pandas as pd

from feature_core import ADDED_FEATURES


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
STYLE_DIR = ROOT / "jeju/research/20261010_style_history_ablation_v1"
STYLE_OUT = STYLE_DIR / "outputs"
YEARS = (2024, 2025, 2026)
VARIANT = "F1_STYLE6_DISTANCE_SECTION_RELATIVE10"
FEATURE_PATH = OUT / "features_f1_style6_distance_section_relative10.parquet"
APPROVAL_PATH = OUT / "root_fit_approval.json"
LOCK_PATH = OUT / "prepared_lock.json"
PREFLIGHT_PATH = OUT / "source_preflight.json"
BASELINE_REPLAY_PATH = OUT / "baseline_replay_verification.json"


def sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_style_runner():
    # Load existing code only for immutable constants/scoring functions. Never
    # call its fit or verify functions (the latter also pins an old DB hash).
    if str(STYLE_DIR) not in sys.path:
        sys.path.insert(0, str(STYLE_DIR))
    spec = importlib.util.spec_from_file_location(
        "five_section_saved_style6_runner", STYLE_DIR / "run.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the saved STYLE6 training contract")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STYLE = _load_style_runner()
BASE_COLUMNS = list(STYLE.e.MODEL_COLUMNS)
FEATURE_COLUMNS = BASE_COLUMNS + ADDED_FEATURES
MODEL_CATS = list(STYLE.MODEL_CATS)
PARAMS = dict(STYLE.OLD.PARAMS)
assert len(BASE_COLUMNS) == 30 and len(FEATURE_COLUMNS) == 40


def write_json_new(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False,
                  default=lambda value: value.item() if isinstance(value, np.generic) else str(value))
        stream.write("\n")


def write_parquet_new(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=False)


def verify_locked_inputs(lock: dict) -> None:
    for relative, entry in lock["input_files"].items():
        path = ROOT / relative
        assert path.is_file(), f"missing locked input: {relative}"
        assert path.stat().st_size == int(entry["bytes"]), f"locked input size changed: {relative}"
        assert sha256(path) == entry["sha256"], f"locked input SHA changed: {relative}"


def require_root_approval() -> tuple[dict, dict]:
    for path in (LOCK_PATH, PREFLIGHT_PATH, BASELINE_REPLAY_PATH, APPROVAL_PATH):
        assert path.is_file(), f"candidate fit requires reviewed artifact: {path.name}"
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    preflight = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))
    baseline = json.loads(BASELINE_REPLAY_PATH.read_text(encoding="utf-8"))
    approval = json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))
    assert preflight.get("passed") is True and preflight.get("candidate_fit_models") == 0
    assert preflight.get("candidate_outcome_metrics_computed") is False
    assert baseline.get("passed") is True
    assert baseline.get("baseline_models_reloaded") == 3
    assert baseline.get("runner_rows_reproduced") == 17412
    assert baseline.get("distinct_races_reproduced") == 1779
    assert approval.get("approved") is True and approval.get("approved_by") == "root"
    assert approval.get("candidate") == VARIANT
    assert approval.get("candidate_models") == 3
    assert approval.get("lightgbm_train_calls") == 6
    assert approval.get("temperature_optimizations") == 3
    assert approval.get("contract_sha256") == sha256(HERE / "CONTRACT.md")
    assert approval.get("prepared_lock_sha256") == sha256(LOCK_PATH)
    assert approval.get("preflight_sha256") == sha256(PREFLIGHT_PATH)
    assert approval.get("baseline_replay_sha256") == sha256(BASELINE_REPLAY_PATH)
    assert approval.get("training_code_sha256") == sha256(Path(__file__))
    verify_locked_inputs(lock)
    return lock, approval


def fit_one_year(features: pd.DataFrame, year: int) -> dict:
    train_mask = features.year.between(2017, year - 3)
    validation_mask = features.year.eq(year - 2)
    calibration_mask = features.year.eq(year - 1)
    evaluation_mask = features.year.eq(year)
    assert all(mask.any() for mask in (train_mask, validation_mask, calibration_mask, evaluation_mask))
    assert not (train_mask & validation_mask).any()
    assert not (validation_mask & calibration_mask).any()
    assert not (calibration_mask & evaluation_mask).any()

    x = features[FEATURE_COLUMNS].copy()
    vocabulary = {}
    for column in MODEL_CATS:
        if column in FEATURE_COLUMNS:
            vocabulary[column] = sorted(
                features.loc[train_mask, column].dropna().astype(str).unique().tolist()
            )
            x[column] = pd.Categorical(x[column].astype("string"), categories=vocabulary[column])

    saved_meta = json.loads((STYLE_OUT / f"F1_STYLE6_{year}/meta.json").read_text(encoding="utf-8"))
    assert saved_meta["features"] == BASE_COLUMNS
    assert saved_meta["parameters"] == PARAMS
    assert int(saved_meta["seed"]) == int(STYLE.OLD.SEED) == 20261008
    assert saved_meta["vocabulary"] == vocabulary, f"baseline categorical split mismatch for {year}"

    target = features.finish_position.le(3).astype("int8")
    weights = 1 / pd.to_numeric(features.field_n, errors="raise")

    def make_dataset(mask):
        return lgb.Dataset(
            x.loc[mask], label=target.loc[mask], weight=weights.loc[mask], free_raw_data=False,
        )

    initial = lgb.train(
        PARAMS, make_dataset(train_mask), num_boost_round=200,
        valid_sets=[make_dataset(validation_mask)],
        callbacks=[lgb.early_stopping(25, verbose=False)],
    )
    assert 0 < int(initial.best_iteration) <= 200
    model = lgb.train(
        PARAMS, make_dataset(train_mask | validation_mask),
        num_boost_round=int(initial.best_iteration),
    )
    assert int(model.num_feature()) == len(FEATURE_COLUMNS)

    calibration = features.loc[calibration_mask].reset_index(drop=True)
    evaluation = features.loc[evaluation_mask].reset_index(drop=True)
    calibration_raw = model.predict(x.loc[calibration_mask], raw_score=True, num_threads=4)
    evaluation_raw = model.predict(x.loc[evaluation_mask], raw_score=True, num_threads=4)
    temperature = float(STYLE.OLD.temperature(calibration, calibration_raw))
    assert np.isfinite(temperature) and 0.35 <= temperature <= 4.0

    folder = OUT / f"{VARIANT}_{year}"
    folder.mkdir(exist_ok=False)
    model_path = folder / "top3.txt"
    model.save_model(str(model_path))
    write_parquet_new(folder / "calibration_scores.parquet", pd.DataFrame({
        "api_record_id": calibration.api_record_id.to_numpy(dtype="int64"),
        "score": np.asarray(calibration_raw, dtype="float64"),
    }))
    write_parquet_new(folder / "evaluation_scores.parquet", pd.DataFrame({
        "api_record_id": evaluation.api_record_id.to_numpy(dtype="int64"),
        "score": np.asarray(evaluation_raw, dtype="float64"),
    }))
    meta = {
        "variant": VARIANT,
        "evaluation_year": year,
        "features": FEATURE_COLUMNS,
        "feature_count": len(FEATURE_COLUMNS),
        "base_feature_count": len(BASE_COLUMNS),
        "added_features": ADDED_FEATURES,
        "vocabulary": vocabulary,
        "trees": int(initial.best_iteration),
        "tau": temperature,
        "seed": int(STYLE.OLD.SEED),
        "parameters": PARAMS,
        "lightgbm_train_calls": 2,
        "temperature_optimizations": 1,
        "training_min": str(features.loc[train_mask, "race_date"].min()),
        "initial_training_max": str(features.loc[train_mask, "race_date"].max()),
        "early_stopping_min": str(features.loc[validation_mask, "race_date"].min()),
        "refit_max": str(features.loc[validation_mask, "race_date"].max()),
        "calibration_min": str(features.loc[calibration_mask, "race_date"].min()),
        "calibration_max": str(features.loc[calibration_mask, "race_date"].max()),
        "evaluation_min": str(features.loc[evaluation_mask, "race_date"].min()),
        "evaluation_max": str(features.loc[evaluation_mask, "race_date"].max()),
        "train_rows_refit": int((train_mask | validation_mask).sum()),
        "train_races_refit": int(features.loc[train_mask | validation_mask, "race_id"].nunique()),
        "calibration_rows": int(calibration_mask.sum()),
        "calibration_races": int(calibration.race_id.nunique()),
        "evaluation_rows": int(evaluation_mask.sum()),
        "evaluation_races": int(evaluation.race_id.nunique()),
        "model_sha256": sha256(model_path),
        "calibration_scores_sha256": sha256(folder / "calibration_scores.parquet"),
        "evaluation_scores_sha256": sha256(folder / "evaluation_scores.parquet"),
        "feature_gain": dict(zip(FEATURE_COLUMNS, map(float, model.feature_importance(importance_type="gain")))),
        "outcome_metrics_computed": False,
    }
    write_json_new(folder / "meta.json", meta)
    return {
        "year": year,
        "trees": int(initial.best_iteration),
        "tau": temperature,
        "train_rows_refit": meta["train_rows_refit"],
        "calibration_rows": meta["calibration_rows"],
        "evaluation_rows": meta["evaluation_rows"],
        "model_sha256": meta["model_sha256"],
        "evaluation_scores_sha256": meta["evaluation_scores_sha256"],
    }


def fit() -> None:
    lock, approval = require_root_approval()
    features = pd.read_parquet(FEATURE_PATH)
    assert len(features) == 52155 and features.api_record_id.is_unique
    assert set(FEATURE_COLUMNS).issubset(features.columns)
    assert list(features[BASE_COLUMNS].columns) == BASE_COLUMNS
    assert len(features.loc[features.year.ge(2024)]) == 17412
    assert features.loc[features.year.ge(2024), "race_id"].nunique() == 1779
    assert not any((OUT / f"{VARIANT}_{year}").exists() for year in YEARS), "refit prohibited"
    assert not (OUT / "candidate_training_completion.json").exists(), "existing fit output; refusing overwrite"

    write_json_new(OUT / "fit_execution_started.json", {
        "status": "started",
        "fit_approval_sha256": sha256(APPROVAL_PATH),
        "prepared_lock_sha256": sha256(LOCK_PATH),
        "candidate_training_code_sha256": sha256(Path(__file__)),
        "started_models": 3,
        "lightgbm_train_calls_expected": 6,
        "temperature_optimizations_expected": 3,
        "candidate_outcome_metrics_computed": False,
    })
    year_receipts = [fit_one_year(features, year) for year in YEARS]
    score_frames = []
    for year in YEARS:
        scores = pd.read_parquet(OUT / f"{VARIANT}_{year}/evaluation_scores.parquet")
        scores["year"] = year
        score_frames.append(scores)
    score_frame = pd.concat(score_frames, ignore_index=True)
    assert len(score_frame) == 17412 and score_frame.api_record_id.is_unique
    write_parquet_new(OUT / "candidate_scores_fit_stage.parquet", score_frame)
    verify_locked_inputs(lock)
    completion = {
        "passed": True,
        "fit_approval_sha256": sha256(APPROVAL_PATH),
        "prepared_lock_sha256": sha256(LOCK_PATH),
        "candidate": VARIANT,
        "candidate_models": len(year_receipts),
        "lightgbm_train_calls": 2 * len(year_receipts),
        "temperature_optimizations": len(year_receipts),
        "model_years": year_receipts,
        "candidate_score_rows": int(len(score_frame)),
        "candidate_outcome_metrics_computed": False,
        "no_refit_after_this_point": True,
        "production_changed": False,
        "database_changed": False,
        "training_code_sha256": sha256(Path(__file__)),
        "contract_sha256": sha256(HERE / "CONTRACT.md"),
        "feature_core_sha256": sha256(HERE / "feature_core.py"),
    }
    write_json_new(OUT / "candidate_training_completion.json", completion)
    print(json.dumps(completion, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    if sys.argv[1:] != ["fit"]:
        raise SystemExit("usage: train_candidate.py fit (requires root_fit_approval.json)")
    fit()
