"""Generate only the four missing F1_STYLE6 calibration-year raw OOS scores.

This runner cannot execute without a root-written approval file that pins the
preflight, source lock, plan, and this code. It never writes outside this study.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
sys.dont_write_bytecode = True
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd


STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[2]
OUT = STUDY / "outputs"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
STYLE_PREPARE = ROOT / "jeju/research/20261010_style_history_ablation_v1/prepare.py"
PREFLIGHT_PATH = OUT / "HISTORICAL_PREFLIGHT.json"
SOURCE_LOCK_PATH = OUT / "HISTORICAL_SOURCE_LOCK.json"
APPROVAL_PATH = OUT / "HISTORICAL_FIT_APPROVAL.json"
RUN_RECEIPT_PATH = OUT / "HISTORICAL_REFIT_RECEIPT.json"
FOLDS = (2020, 2021, 2022, 2023)
EXPECTED_TRAIN_CALLS = 8


class HistoricalRefitError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise HistoricalRefitError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def checked_source(path: Path) -> Path:
    require(not path.is_symlink(), f"source symlink is not allowed: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"source outside workspace: {path}")
    return resolved


def output_path(path: Path) -> Path:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study: {path}")
    require(not path.is_symlink(), f"output symlink is not allowed: {path}")
    require(not path.exists(), f"refusing to overwrite existing output: {path}")
    return path


def write_json_once(path: Path, payload: dict) -> None:
    output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def write_parquet_once(path: Path, frame: pd.DataFrame) -> None:
    output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Serialize before opening an exclusive destination so an existing file is
    # never truncated by a failed or repeated run.
    import io

    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    with path.open("xb") as stream:
        stream.write(buffer.getvalue())


def load_style_module():
    path = checked_source(STYLE_PREPARE)
    spec = importlib.util.spec_from_file_location("f1_style6_frozen_prepare", path)
    require(spec is not None and spec.loader is not None, "cannot load frozen STYLE6 recipe")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_approval() -> tuple[dict, dict, dict]:
    require(OUT.is_dir(), "historical preflight outputs are missing")
    preflight_path = checked_source(PREFLIGHT_PATH)
    lock_path = checked_source(SOURCE_LOCK_PATH)
    approval_path = checked_source(APPROVAL_PATH)
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    require(preflight.get("status") == "PASS", "historical source preflight did not pass")
    require(preflight.get("historical_refit_performed") is False, "preflight must precede historical refit")
    require(preflight.get("raw_oos_scores_generated") is False, "preflight must precede score generation")
    require(preflight.get("pair_fit_performed") is False, "preflight must precede pair fit")
    require(approval.get("approved") is True, "explicit root fit approval is required")
    require(approval.get("approved_by") == "root", "approval identity must be root")
    require(approval.get("scope") == "historical_F1_STYLE6_calibration_raw_scores_only", "approval scope mismatch")
    require(approval.get("folds") == list(FOLDS), "approval fold list mismatch")
    require(approval.get("lightgbm_train_calls") == EXPECTED_TRAIN_CALLS, "approval train-call budget mismatch")
    require(approval.get("temperature_optimizations") == 0, "no temperature fitting is authorized")
    require(approval.get("preflight_sha256") == sha256(preflight_path), "approval preflight hash mismatch")
    require(approval.get("source_lock_sha256") == sha256(lock_path), "approval source lock hash mismatch")
    require(approval.get("historical_refit_sha256") == sha256(Path(__file__)), "approval code hash mismatch")
    require(approval.get("plan_sha256") == sha256(STUDY / "PLAN.md"), "approval plan hash mismatch")
    require(lock.get("status") == "PASS", "historical source lock did not pass")
    required_recipe_sources = {
        "jeju/research/20261010_style_history_ablation_v1/prepare.py",
        "jeju/research/20261009_finish_history_ablation_v1/prepare.py",
        "jeju/research/20261008_horse_profile_baseline_v1/run.py",
    }
    require(required_recipe_sources.issubset(set(lock.get("sources", {}))),
            "source lock omits part of the transitive STYLE6 recipe")
    for relative, expected in lock["sources"].items():
        source = checked_source(ROOT / relative)
        require(sha256(source) == expected, f"locked source changed: {relative}")
    require(not RUN_RECEIPT_PATH.exists(), "historical refit already has a completion receipt")
    for fold in FOLDS:
        folder = OUT / f"F1_STYLE6_{fold}"
        require(not folder.exists(), f"historical fold output already exists: {folder}")
    return preflight, lock, approval


def fit_one_fold(features: pd.DataFrame, recipe, fold: int) -> dict:
    columns = list(recipe.MODEL_COLUMNS)
    model_cats = list(recipe.F1.base.CATS) + ["previous_result_status"]
    require(len(columns) == 30, "frozen F1_STYLE6 feature count changed")
    x = features[columns].copy()

    train = features["year"].between(2017, fold - 3)
    valid = features["year"].eq(fold - 2)
    calibration = features["year"].eq(fold - 1)
    require(train.any() and valid.any() and calibration.any(), f"empty historical split for fold {fold}")

    vocabulary: dict[str, list[str]] = {}
    for column in model_cats:
        if column in columns:
            vocabulary[column] = sorted(features.loc[train, column].dropna().astype(str).unique().tolist())
            x[column] = pd.Categorical(x[column].astype("string"), categories=vocabulary[column])

    target = features["finish_position"].le(3).astype(int)
    weight = 1.0 / features["field_n"].astype(float)

    def dataset(mask: pd.Series) -> lgb.Dataset:
        return lgb.Dataset(
            x.loc[mask], label=target.loc[mask], weight=weight.loc[mask], free_raw_data=False
        )

    initial = lgb.train(
        recipe.F1.base.PARAMS,
        dataset(train),
        num_boost_round=200,
        valid_sets=[dataset(valid)],
        callbacks=[lgb.early_stopping(25, verbose=False)],
    )
    trees = int(initial.best_iteration)
    require(trees > 0, f"invalid best iteration for fold {fold}")
    model = lgb.train(recipe.F1.base.PARAMS, dataset(train | valid), num_boost_round=trees)

    calibration_rows = features.loc[calibration].reset_index(drop=True)
    raw_scores = np.asarray(model.predict(x.loc[calibration], raw_score=True, num_threads=4), dtype=float)
    require(len(raw_scores) == len(calibration_rows), f"score row count mismatch for fold {fold}")
    require(np.isfinite(raw_scores).all(), f"non-finite raw score for fold {fold}")

    folder = output_path(OUT / f"F1_STYLE6_{fold}")
    folder.mkdir(parents=True, exist_ok=False)
    model_path = folder / "top3.txt"
    require(not model_path.exists(), "model output unexpectedly exists")
    # The destination is fixed under this study and the enclosing fold folder
    # was just created exclusively above.
    model.save_model(str(model_path))
    score_path = folder / "calibration_scores.parquet"
    write_parquet_once(score_path, pd.DataFrame({
        "api_record_id": calibration_rows["api_record_id"].to_numpy(dtype=np.int64),
        "score": raw_scores,
    }))

    meta = {
        "variant": "F1_STYLE6",
        "evaluation_year": int(fold),
        "score_role_generated": "calibration_only",
        "features": columns,
        "feature_count": len(columns),
        "vocabulary": vocabulary,
        "trees": trees,
        "seed": int(recipe.F1.base.SEED),
        "parameters": recipe.F1.base.PARAMS,
        "lightgbm_train_calls": 2,
        "temperature_optimizations": 0,
        "temperature_omission_reason": "pair input contract uses raw score at tau=1; frozen score model is unchanged",
        "initial_training_min": str(features.loc[train, "race_date"].min()),
        "initial_training_max": str(features.loc[train, "race_date"].max()),
        "early_stopping_min": str(features.loc[valid, "race_date"].min()),
        "early_stopping_max": str(features.loc[valid, "race_date"].max()),
        "refit_min": str(features.loc[train | valid, "race_date"].min()),
        "refit_max": str(features.loc[train | valid, "race_date"].max()),
        "calibration_min": str(calibration_rows["race_date"].min()),
        "calibration_max": str(calibration_rows["race_date"].max()),
        "train_rows": int((train | valid).sum()),
        "train_races": int(features.loc[train | valid, "race_id"].nunique()),
        "calibration_rows": int(len(calibration_rows)),
        "calibration_races": int(calibration_rows["race_id"].nunique()),
        "model_sha256": sha256(model_path),
        "calibration_scores_sha256": sha256(score_path),
        "source_features_sha256": sha256(FEATURES),
        "historical_refit_code_sha256": sha256(Path(__file__)),
        "outcome_metrics_computed": False,
        "evaluation_scores_generated": False,
        "pair_fit_performed": False,
    }
    meta_path = folder / "meta.json"
    with meta_path.open("x", encoding="utf-8") as stream:
        json.dump(meta, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return {
        "fold": int(fold),
        "calibration_year": int(fold - 1),
        "train_calls": 2,
        "trees": trees,
        "refit_max": meta["refit_max"],
        "calibration_rows": meta["calibration_rows"],
        "calibration_races": meta["calibration_races"],
        "model_sha256": meta["model_sha256"],
        "calibration_scores_sha256": meta["calibration_scores_sha256"],
        "meta_sha256": sha256(meta_path),
    }


def run() -> None:
    verify_approval()
    recipe = load_style_module()
    features_path = checked_source(FEATURES)
    features = pd.read_parquet(features_path)
    require(len(features) == 52155, "frozen feature row count changed")
    require(features["api_record_id"].is_unique, "feature API record keys are not unique")
    require(features["race_id"].notna().all(), "null race ID in frozen feature table")
    require(set(recipe.MODEL_COLUMNS).issubset(features.columns), "frozen model columns are missing")

    fold_results = [fit_one_fold(features, recipe, fold) for fold in FOLDS]
    require(sum(item["train_calls"] for item in fold_results) == EXPECTED_TRAIN_CALLS,
            "historical LightGBM train-call budget changed")
    receipt = {
        "status": "PASS",
        "scope": "historical_F1_STYLE6_calibration_raw_scores_only",
        "folds": fold_results,
        "lightgbm_train_calls": EXPECTED_TRAIN_CALLS,
        "temperature_optimizations": 0,
        "calibration_raw_scores_generated": True,
        "historical_evaluation_scores_generated": False,
        "pair_fit_performed": False,
        "pair_performance_metrics_computed": False,
        "source_lock_sha256": sha256(SOURCE_LOCK_PATH),
        "preflight_sha256": sha256(PREFLIGHT_PATH),
        "approval_sha256": sha256(APPROVAL_PATH),
        "historical_refit_code_sha256": sha256(Path(__file__)),
    }
    write_json_once(RUN_RECEIPT_PATH, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "fit-approved-historical-oos":
        raise SystemExit("usage: historical_refit.py fit-approved-historical-oos")
    run()

