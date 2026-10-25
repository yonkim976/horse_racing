"""Report the frozen riding-conditions pair candidate against its saved ID baseline.

This file only reads frozen study artifacts.  ``report`` writes the final
README once; ``manifest`` is a separate finalization step that requires the
independent root metrics review to have passed.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import scipy


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261015_pair_riding_conditions_v1"
OUT = STUDY / "outputs"
PREFIT = STUDY / "outputs_prefit_v2"
BASE = ROOT / "jeju/research/20261012_pair_jockey_id_v1"
DIRECT = ROOT / "jeju/research/20261011_pair_top3_direct_v1"

PREDICTIONS = OUT / "evaluation_pair_predictions.parquet"
PREDICTION_RECEIPT = OUT / "PREDICTION_RECEIPT.json"
FIT = OUT / "FIT.json"
FIT_RECEIPT = OUT / "FIT_RECEIPT.json"
APPROVAL = OUT / "APPROVAL.json"
BASE_PREDICTIONS = BASE / "outputs/evaluation_pair_predictions.parquet"
BASE_PREDICTION_RECEIPT = BASE / "outputs/PREDICTION_RECEIPT.json"
BASE_FIT = BASE / "outputs/FIT.json"
RUNNER_BASIS = PREFIT / "riding_conditions_runner_basis.parquet"
FEATURE_PREFLIGHT = PREFIT / "FEATURE_PREFLIGHT.json"
DESIGN_DRY_RUN = PREFIT / "DESIGN_DRY_RUN.json"
SAVED_ID_RECONCILIATION = PREFIT / "SAVED_ID_RECONCILIATION.json"
FIRST60_RECONCILIATION = PREFIT / "NEW_CANDIDATE_FIRST60_RECONCILIATION.json"
SOURCE_HASHES = STUDY / "SOURCE_HASHES.json"
PROTECTED_INPUTS = STUDY / "ROOT_PROTECTED_INPUTS.json"
INDEPENDENT_PREFIT = STUDY / "audit/independent_prefit_receipt.json"
INDEPENDENT_DUPLICATE = STUDY / "audit/independent_h1_duplicate_receipt.json"
ROOT_REVIEW = STUDY / "ROOT_METRICS_REVIEW.json"
BOOTSTRAP = DIRECT / "outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT = DIRECT / "outputs/date_bootstrap_schedule.json"
BOOTSTRAP_SOURCE_FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"

README = STUDY / "README.md"
MANIFEST = STUDY / "ARTIFACT_MANIFEST.json"
DOCUMENT_CORRECTION_RECEIPT = STUDY / "DOCUMENT_CORRECTION_RECEIPT.json"
REPORT_JSON = OUT / "REPORT.json"
REPORT_DIR = OUT / "report"
PAIRED_RACE_CSV = REPORT_DIR / "paired_race_metrics.csv"
CHANGED_SELECTIONS_CSV = REPORT_DIR / "changed_selections.csv"

EXPECTED_BASELINE_SHA = "0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6"
EXPECTED_SCHEDULE_SHA = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
EXPECTED_BOOTSTRAP_SOURCE_FEATURES_SHA = "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f"
EXPECTED_RUNNER_BASIS_SHA = "e6d3e09ccf1ac25c3699929242d5fec6c1b992862dacf64c9d118bc7dbfa112c"

KEYS = ["race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j"]
PAIR_KEYS = ["race_id", "horse_i", "horse_j"]
OLD_BASELINE_SELECTOR = "selected_jockey_id_candidate"
OLD_BASELINE_PROBABILITY = "jockey_id_candidate_calibrated_probability"
RAW_TOP2_SELECTOR = "selected_raw_top2"
CANDIDATE_PROBABILITY = "riding_conditions_candidate_calibrated_probability"
CANDIDATE_SELECTOR = "selected_riding_conditions_candidate"
CANDIDATE_RAW_PROBABILITY = "riding_conditions_candidate_raw_probability"
CANDIDATE_ETA = "riding_conditions_candidate_eta"
EXPECTED_ADDED_COLUMNS = [CANDIDATE_ETA, CANDIDATE_RAW_PROBABILITY, CANDIDATE_PROBABILITY, CANDIDATE_SELECTOR]

RUNNER_STATE_COLUMNS = [
    "race_id", "horse_number", "previous_rider_retained", "previous_rider_unknown",
    "horse_current_rider_first_observed", "horse_current_rider_history_unavailable",
    "horse_current_rider_prior_n",
]
RELIABILITY_BINS = ((0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.30), (0.30, 1.0))
RELIABILITY_NAMES = ("[0,.05)", "[.05,.10)", "[.10,.20)", "[.20,.30)", "[.30,1]")
EXPECTED_YEAR_RACES = {2024: 637, 2025: 654, 2026: 488}
EXPECTED_RACES = 1779
EXPECTED_DATES = 269
EXPECTED_PAIR_ROWS = 76848


class ReportError(RuntimeError):
    """Raised when a frozen artifact or comparison contract is inconsistent."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReportError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def checked(path: Path) -> Path:
    """Resolve a fixed study path and reject symlinks or workspace escapes."""
    candidate = path.absolute()
    root = ROOT
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ReportError(f"input outside repository root: {path}") from exc
    current = root
    for part in relative.parts:
        current = current / part
        require(not current.is_symlink(), f"symlink path component is not allowed: {current}")
    resolved = candidate.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"missing or invalid input file: {path}")
    return resolved


def read_json(path: Path) -> dict[str, Any]:
    result = json.loads(checked(path).read_text(encoding="utf-8"))
    require(isinstance(result, dict), f"JSON root must be an object: {path}")
    return result


def write_once(path: Path, content: str) -> None:
    try:
        relative_parent = path.parent.absolute().relative_to(STUDY)
    except ValueError as exc:
        raise ReportError(f"output escaped study directory: {path}") from exc
    current = STUDY
    for part in relative_parent.parts:
        current = current / part
        require(not current.is_symlink(), f"output directory symlink is not allowed: {current}")
        if not current.exists():
            current.mkdir()
    require(path.parent.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite output: {path}")
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)


def normalize_keys(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["race_id"] = result["race_id"].astype("string")
    result["race_date"] = pd.to_datetime(result["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    require(result["race_date"].notna().all(), "invalid race date in pair artifact")
    for column in ("evaluation_year", "distance_m", "horse_i", "horse_j"):
        result[column] = pd.to_numeric(result[column], errors="raise").astype("int64")
    return result


def probability_losses(probability: pd.Series, labels: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    p = np.clip(probability.to_numpy(dtype=float), 1e-15, 1.0 - 1e-15)
    y = labels.to_numpy(dtype=float)
    brier = np.square(p - y)
    logloss = -(y * np.log(p) + (1.0 - y) * np.log1p(-p))
    return brier, logloss


def race_equal_metrics(frame: pd.DataFrame, probability_column: str) -> dict[str, Any]:
    brier, logloss = probability_losses(frame[probability_column], frame["y_pair"])
    work = frame[["race_id"]].copy()
    work["brier"] = brier
    work["logloss"] = logloss
    by_race = work.groupby("race_id", sort=True)[["brier", "logloss"]].mean()
    return {
        "races": int(len(by_race)),
        "brier": float(by_race["brier"].mean()),
        "logloss": float(by_race["logloss"].mean()),
    }


def add_date_index(frame: pd.DataFrame, dates: list[str]) -> pd.DataFrame:
    result = frame.copy()
    result["race_date"] = pd.to_datetime(result["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    require(result["race_date"].notna().all(), "invalid date in evaluation rows")
    lookup = {date: index for index, date in enumerate(dates)}
    require(result["race_date"].isin(lookup).all(), "race date outside frozen bootstrap inventory")
    result["_date_index"] = result["race_date"].map(lookup).astype(int)
    return result


def date_ci(frame: pd.DataFrame, value_column: str, dates: list[str], schedule: np.ndarray) -> dict[str, Any]:
    require("_date_index" in frame.columns, "date index missing before bootstrap")
    if frame.empty:
        return {"estimate": None, "ci_low": None, "ci_high": None, "valid_draws": 0, "undefined_draws": int(schedule.shape[0])}
    sums = np.zeros(len(dates), dtype=float)
    counts = np.zeros(len(dates), dtype=float)
    grouped = frame.groupby("_date_index")[value_column].agg(["sum", "count"])
    for index, row in grouped.iterrows():
        sums[int(index)] = float(row["sum"])
        counts[int(index)] = float(row["count"])
    denominator = counts[schedule].sum(axis=1)
    numerator = sums[schedule].sum(axis=1)
    valid = denominator > 0
    draws = numerator[valid] / denominator[valid]
    return {
        "estimate": float(frame[value_column].mean()),
        "ci_low": float(np.quantile(draws, 0.025)) if len(draws) else None,
        "ci_high": float(np.quantile(draws, 0.975)) if len(draws) else None,
        "valid_draws": int(valid.sum()),
        "undefined_draws": int((~valid).sum()),
    }


def load_bootstrap(dates: list[str]) -> tuple[np.ndarray, dict[str, Any]]:
    receipt = read_json(BOOTSTRAP_RECEIPT)
    schedule_path = checked(BOOTSTRAP)
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS", "bootstrap schedule is not frozen")
    require(receipt.get("generator") == "numpy.random.default_rng"
            and receipt.get("bit_generator") == "PCG64"
            and receipt.get("schedule_shape") == [2000, EXPECTED_DATES]
            and receipt.get("source_features_sha256") == EXPECTED_BOOTSTRAP_SOURCE_FEATURES_SHA
            and sha256(checked(BOOTSTRAP_SOURCE_FEATURES)) == EXPECTED_BOOTSTRAP_SOURCE_FEATURES_SHA,
            "frozen bootstrap source or generator metadata changed")
    require(receipt.get("seed") == 20261011 and receipt.get("draws") == 2000,
            "bootstrap recipe differs from the predeclared schedule")
    require(receipt.get("dates_per_draw") == EXPECTED_DATES, "bootstrap date count changed")
    require(receipt.get("schedule_sha256") == EXPECTED_SCHEDULE_SHA == sha256(schedule_path),
            "frozen date schedule hash mismatch")
    require(receipt.get("date_inventory_sha256") == hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest(),
            "evaluation dates differ from frozen bootstrap date inventory")
    require(receipt.get("date_min") == dates[0] and receipt.get("date_max") == dates[-1],
            "bootstrap date boundaries changed")
    schedule = np.load(schedule_path, allow_pickle=False)
    require(schedule.shape == (2000, len(dates)) and schedule.dtype == np.int32,
            "bootstrap array shape or dtype changed")
    require(((schedule >= 0) & (schedule < len(dates))).all(), "invalid bootstrap date index")
    require(receipt.get("numpy_version") == np.__version__, "NumPy version differs from frozen schedule")
    rng = np.random.default_rng(20261011)
    expected = rng.integers(0, len(dates), size=(2000, len(dates)), endpoint=False, dtype=np.int32)
    require(np.array_equal(schedule, expected), "bootstrap array no longer matches the frozen RNG recipe")
    return schedule, receipt


def verify_pre_fitting_lineage() -> dict[str, Any]:
    feature = read_json(FEATURE_PREFLIGHT)
    dry_run = read_json(DESIGN_DRY_RUN)
    reconciliation = read_json(SAVED_ID_RECONCILIATION)
    first60 = read_json(FIRST60_RECONCILIATION)
    independent = read_json(INDEPENDENT_PREFIT)
    duplicate = read_json(INDEPENDENT_DUPLICATE)
    source_hashes = read_json(SOURCE_HASHES)
    protected = read_json(PROTECTED_INPUTS)
    require(feature.get("status") == "PASS" and dry_run.get("status") == "PASS",
            "source or design preflight is not PASS")
    require(independent.get("status") == "PASS" and duplicate.get("status") == "PASS",
            "independent prefit audit is not PASS")
    require(reconciliation.get("status") == "PASS"
            and reconciliation.get("selection_mismatches") == 0
            and reconciliation.get("maximum_absolute_difference", {}).get("jockey_id_candidate_calibrated_probability") == 0.0,
            "frozen saved-ID reconstruction did not match exactly")
    require(first60.get("status") == "PASS" and first60.get("pair_rows") == EXPECTED_PAIR_ROWS
            and first60.get("races") == EXPECTED_RACES and first60.get("evaluation_dates") == EXPECTED_DATES
            and first60.get("selection_mismatches") == 0
            and max(first60.get("max_abs_differences", {}).values()) == 0.0
            and first60.get("frozen_id_prediction_sha256") == EXPECTED_BASELINE_SHA
            and first60.get("runner_basis_sha256") == EXPECTED_RUNNER_BASIS_SHA
            and first60.get("target_evaluation_outcomes_used") is False
            and first60.get("performance_metrics_computed") is False,
            "candidate prediction first-60 reconstruction did not match the frozen ID model exactly")
    require(first60.get("new_prediction_code_sha256") == sha256(checked(STUDY / "pair_riding_conditions_predict.py")),
            "candidate predictor changed after its first-60 reconstruction audit")
    require(dry_run.get("candidate_optimization_budget_after_separate_root_approval") == {
        "h1_fits": 3,
        "h2_positive_slope_platt_fits": 3,
        "total_fit_or_calibration_calls": 6,
        "no_retry_or_tuning": True,
    }, "predeclared single-arm fit budget changed")
    require(dry_run.get("pair_input_columns") and len(dry_run["pair_input_columns"]) == 10,
            "predeclared raw candidate input schema changed")
    require(set(dry_run.get("folds", {})) == {"2024", "2025", "2026"}
            and all(int(row.get("joint_candidate_columns_after_degenerate_drop", -1)) == 69
                    for row in dry_run["folds"].values()),
            "fold-specific active joint feature count differs from the frozen 69-column design")
    expected_runner_hash = feature.get("runner_basis_sha256")
    require(expected_runner_hash == EXPECTED_RUNNER_BASIS_SHA
            and sha256(checked(RUNNER_BASIS)) == expected_runner_hash,
            "frozen runner basis differs from independent prefit lock")
    require(source_hashes.get("status") == "PINNED_SOURCE_FILES", "source hash inventory status changed")
    baseline_relative = BASE_PREDICTIONS.relative_to(ROOT).as_posix()
    baseline_source = next((item for item in source_hashes.get("sources", [])
                            if item.get("path") == baseline_relative), None)
    require(protected.get("files", {}).get(baseline_relative) == EXPECTED_BASELINE_SHA
            and baseline_source is not None and baseline_source.get("sha256") == EXPECTED_BASELINE_SHA
            and reconciliation.get("saved_prediction_sha256") == EXPECTED_BASELINE_SHA
            and sha256(checked(BASE_PREDICTIONS)) == EXPECTED_BASELINE_SHA,
            "frozen saved-ID baseline hash differs from its protected input locks")
    return {
        "feature_preflight_sha256": sha256(checked(FEATURE_PREFLIGHT)),
        "design_dry_run_sha256": sha256(checked(DESIGN_DRY_RUN)),
        "independent_prefit_receipt_sha256": sha256(checked(INDEPENDENT_PREFIT)),
        "independent_duplicate_receipt_sha256": sha256(checked(INDEPENDENT_DUPLICATE)),
        "saved_id_reconciliation_sha256": sha256(checked(SAVED_ID_RECONCILIATION)),
        "first60_reconciliation_sha256": sha256(checked(FIRST60_RECONCILIATION)),
        "runner_basis_sha256": expected_runner_hash,
        "source_hash_inventory_sha256": sha256(checked(SOURCE_HASHES)),
        "protected_input_lock_sha256": sha256(checked(PROTECTED_INPUTS)),
        "saved_id_baseline_sha256": EXPECTED_BASELINE_SHA,
        "raw_candidate_columns": list(dry_run["pair_input_columns"]),
        "active_candidate_columns_by_fold": {
            str(year): int(row["joint_candidate_columns_after_degenerate_drop"])
            for year, row in dry_run["folds"].items()
        },
    }


def verify_document_correction_snapshots() -> dict[str, Any]:
    receipt = read_json(DOCUMENT_CORRECTION_RECEIPT)
    require(receipt.get("status") == "PASS"
            and receipt.get("scope") == "documentation corrections only; no model fit, prediction, or performance-metric change"
            and receipt.get("snapshot_directory") == "review_snapshots/pre_document_fix"
            and receipt.get("snapshotted_before_renderer_or_document_edits") is True
            and receipt.get("model_refit_performed") is False
            and receipt.get("prediction_rerun_performed") is False
            and receipt.get("metric_values_changed") is False,
            "document correction receipt scope or state changed")
    expected_paths = {
        "README.md": STUDY / "review_snapshots/pre_document_fix/README.md",
        "outputs/REPORT.json": STUDY / "review_snapshots/pre_document_fix/REPORT.json",
        "ARTIFACT_MANIFEST.json": STUDY / "review_snapshots/pre_document_fix/ARTIFACT_MANIFEST.json",
    }
    pinned = receipt.get("previous_documents", {})
    require(set(pinned) == set(expected_paths), "document correction snapshot inventory changed")
    for relative, path in expected_paths.items():
        item = pinned[relative]
        require(item.get("snapshot_path") == path.relative_to(STUDY).as_posix()
                and sha256(checked(path)) == item.get("sha256")
                and path.stat().st_size == item.get("bytes"),
                f"pre-correction snapshot does not match receipt: {relative}")
    require(receipt.get("previous_prediction_sha256") == sha256(checked(PREDICTIONS))
            and receipt.get("root_metrics_review_sha256") == sha256(checked(ROOT_REVIEW)),
            "prediction or independent root review changed after document snapshot")
    return {
        "receipt_path": DOCUMENT_CORRECTION_RECEIPT.relative_to(STUDY).as_posix(),
        "receipt_sha256": sha256(checked(DOCUMENT_CORRECTION_RECEIPT)),
        "snapshot_directory": receipt["snapshot_directory"],
        "previous_documents": receipt["previous_documents"],
        "corrections": receipt["corrections"],
        "model_refit_performed": False,
        "prediction_rerun_performed": False,
        "metric_values_changed": False,
    }


def validate_fit_and_predictions() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any], dict[str, Any]]:
    fit = read_json(FIT)
    fit_receipt = read_json(FIT_RECEIPT)
    approval = read_json(APPROVAL)
    prediction_receipt = read_json(PREDICTION_RECEIPT)
    baseline_receipt = read_json(BASE_PREDICTION_RECEIPT)
    require(fit.get("status") == "PASS" and fit_receipt.get("status") == "PASS",
            "candidate fit or fit receipt is not PASS")
    require(approval.get("approved") is True and approval.get("approved_by") == "root",
            "root fit approval is missing")
    require(fit_receipt.get("candidate_fit_sha256") == sha256(checked(FIT)), "fit receipt hash mismatch")
    require(fit.get("fit_budget") == {
        "h1_fits": 3, "h2_positive_slope_platt_fits": 3,
        "total_optimizer_calls": 6, "no_retry_or_tuning": True,
    } and fit.get("h1_fit_count") == 3 and fit.get("h2_candidate_map_count") == 3,
            "candidate fit budget differs from the predeclared single-arm contract")
    require(fit.get("target_evaluation_outcomes_used") is False
            and fit.get("evaluation_predictions_generated") is False
            and fit.get("performance_metrics_computed") is False,
            "fit artifact reports evaluation labels, predictions, or metrics were used early")
    require(fit_receipt.get("fit_count") == {"h1": 3, "h2_platt": 3}
            and fit_receipt.get("evaluation_predictions_generated") is False
            and fit_receipt.get("performance_metrics_computed") is False,
            "fit receipt differs from the predeclared six-call budget")
    require(fit.get("approval_sha256") == sha256(checked(APPROVAL))
            and fit_receipt.get("approval_sha256") == sha256(checked(APPROVAL)),
            "fit approval lineage mismatch")
    require(prediction_receipt.get("status") == "PASS", "candidate prediction receipt is not PASS")
    require(prediction_receipt.get("candidate_probability_column") == CANDIDATE_PROBABILITY
            and prediction_receipt.get("candidate_selector_column") == CANDIDATE_SELECTOR
            and prediction_receipt.get("selector_column") == CANDIDATE_SELECTOR,
            "candidate prediction columns differ from the predeclared contract")
    require(prediction_receipt.get("prediction_rows") == EXPECTED_PAIR_ROWS
            and prediction_receipt.get("prediction_races") == EXPECTED_RACES
            and prediction_receipt.get("evaluation_dates") == EXPECTED_DATES,
            "candidate prediction cohort size changed")
    require(prediction_receipt.get("old_columns_preserved_count") == 54
            and prediction_receipt.get("target_evaluation_outcomes_used_for_prediction") is False,
            "candidate prediction receipt differs from the frozen 54-column/no-target contract")
    require(prediction_receipt.get("old_columns_preserved_order_and_values") is True
            and prediction_receipt.get("frozen_comparator_columns_preserved") is True,
            "prediction writer did not certify frozen comparator preservation")
    require(prediction_receipt.get("selected_candidate_per_race") == EXPECTED_RACES,
            "candidate selector count differs from the evaluation race count")
    require(prediction_receipt.get("performance_metrics_computed") is False,
            "prediction receipt indicates metrics were computed before report")
    require(baseline_receipt.get("status") == "PASS"
            and baseline_receipt.get("pair_predictions_sha256") == EXPECTED_BASELINE_SHA
            and baseline_receipt.get("performance_metrics_computed") is False,
            "frozen saved-ID prediction receipt is invalid")
    require(sha256(checked(BASE_PREDICTIONS)) == EXPECTED_BASELINE_SHA,
            "frozen saved-ID baseline prediction hash changed")
    pair_path = checked(PREDICTIONS)
    require(prediction_receipt.get("pair_predictions_sha256") == sha256(pair_path),
            "prediction receipt hash mismatch")

    baseline_source = pd.read_parquet(checked(BASE_PREDICTIONS))
    candidate_source = pd.read_parquet(pair_path)
    require(list(candidate_source.columns[:len(baseline_source.columns)]) == list(baseline_source.columns),
            "candidate artifact does not preserve all baseline columns in order")
    require(list(candidate_source.columns[len(baseline_source.columns):]) == EXPECTED_ADDED_COLUMNS,
            "candidate artifact added or reordered unplanned output columns")
    for column in baseline_source.columns:
        require(str(baseline_source[column].dtype) == str(candidate_source[column].dtype),
                f"frozen baseline column dtype changed: {column}")
    baseline_canonical = normalize_keys(baseline_source)
    candidate_canonical = normalize_keys(candidate_source)
    baseline_order = baseline_canonical.assign(_source_index=np.arange(len(baseline_source))).sort_values(
        KEYS, kind="mergesort")[["_source_index"]]["_source_index"].to_numpy()
    candidate_order = candidate_canonical.assign(_source_index=np.arange(len(candidate_source))).sort_values(
        KEYS, kind="mergesort")[["_source_index"]]["_source_index"].to_numpy()
    baseline_source = baseline_source.iloc[baseline_order].reset_index(drop=True)
    candidate_source = candidate_source.iloc[candidate_order].reset_index(drop=True)
    baseline = baseline_canonical.iloc[baseline_order].reset_index(drop=True)
    candidate = candidate_canonical.iloc[candidate_order].reset_index(drop=True)
    require(len(baseline) == EXPECTED_PAIR_ROWS and len(candidate) == EXPECTED_PAIR_ROWS,
            "prediction row count differs from frozen cohort")
    require(not baseline.duplicated(PAIR_KEYS).any() and not candidate.duplicated(PAIR_KEYS).any(),
            "duplicate pair key in comparison artifact")
    for column in baseline.columns:
        left, right = baseline_source[column], candidate_source[column]
        if pd.api.types.is_numeric_dtype(left.dtype):
            require(np.array_equal(left.to_numpy(), right.to_numpy(), equal_nan=True),
                    f"frozen baseline numeric column changed: {column}")
        else:
            require(left.equals(right), f"frozen baseline column changed: {column}")
    require(baseline[PAIR_KEYS].equals(candidate[PAIR_KEYS]), "pair roster differs from saved ID baseline")
    require(set(baseline["race_id"].unique()) == set(candidate["race_id"].unique()), "race roster differs")
    require((baseline.groupby("race_id")["y_pair"].sum() == 3).all(), "pair labels do not encode three Top3 horses")
    require(baseline.groupby("race_id")["race_date"].nunique().eq(1).all()
            and baseline.groupby("race_id")["distance_m"].nunique().eq(1).all()
            and baseline.groupby("race_id")["evaluation_year"].nunique().eq(1).all(),
            "race metadata varies inside a pair roster")
    for column in (OLD_BASELINE_PROBABILITY, CANDIDATE_PROBABILITY, CANDIDATE_RAW_PROBABILITY):
        values = candidate[column].to_numpy(dtype=float) if column in candidate else baseline[column].to_numpy(dtype=float)
        require(np.isfinite(values).all() and ((values >= 0.0) & (values <= 1.0)).all(),
                f"invalid probability values in {column}")
    for selector in (OLD_BASELINE_SELECTOR, RAW_TOP2_SELECTOR, CANDIDATE_SELECTOR):
        require(candidate[selector].isin([0, 1]).all(), f"selector is not binary: {selector}")
        require(candidate.groupby("race_id")[selector].sum().eq(1).all(),
                f"selector does not choose one pair per race: {selector}")
    dates = sorted(candidate["race_date"].unique().tolist())
    require(len(dates) == EXPECTED_DATES, "evaluation date inventory changed")
    race_counts = candidate.groupby("evaluation_year")["race_id"].nunique().to_dict()
    require({int(year): int(count) for year, count in race_counts.items()} == EXPECTED_YEAR_RACES,
            "year-specific evaluation roster changed")
    require(len(candidate["race_id"].unique()) == EXPECTED_RACES, "race count changed")
    return baseline, candidate, fit, fit_receipt, prediction_receipt


def selected_one(frame: pd.DataFrame, selector: str) -> pd.DataFrame:
    selected = frame.loc[frame[selector].eq(1)].copy()
    require(len(selected) == frame["race_id"].nunique() and selected["race_id"].is_unique,
            f"selector does not produce one row per race: {selector}")
    return selected


def race_choice_comparison(candidate_pairs: pd.DataFrame, baseline_pairs: pd.DataFrame,
                           dates: list[str], schedule: np.ndarray) -> tuple[dict[str, Any], pd.DataFrame]:
    candidate_selected = selected_one(candidate_pairs, CANDIDATE_SELECTOR)
    baseline_selected = selected_one(baseline_pairs, OLD_BASELINE_SELECTOR)
    require(int(baseline_selected["y_pair"].sum()) == 438,
            "saved ID baseline selected-hit total differs from its frozen 438/1,779 reference")
    keys = ["race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j", "y_pair"]
    cand = candidate_selected[keys].copy().rename(columns={
        "horse_i": "candidate_horse_i", "horse_j": "candidate_horse_j", "y_pair": "candidate_hit",
    })
    base = baseline_selected[keys].copy().rename(columns={
        "horse_i": "baseline_horse_i", "horse_j": "baseline_horse_j", "y_pair": "baseline_hit",
    })
    races = base.merge(cand, on=["race_id", "race_date", "evaluation_year", "distance_m"],
                       how="inner", validate="one_to_one")
    require(len(races) == EXPECTED_RACES, "candidate and baseline selected races do not align")
    races["pair_changed"] = races["candidate_horse_i"].ne(races["baseline_horse_i"]) \
        | races["candidate_horse_j"].ne(races["baseline_horse_j"])
    races["hit_delta"] = races["candidate_hit"].astype(float) - races["baseline_hit"].astype(float)
    indexed = add_date_index(races, dates)
    change = indexed.loc[indexed["pair_changed"]]
    comparison = {
        "races": int(len(indexed)),
        "candidate_hits": int(indexed["candidate_hit"].sum()),
        "baseline_hits": int(indexed["baseline_hit"].sum()),
        "candidate_hit_rate": float(indexed["candidate_hit"].mean()),
        "baseline_hit_rate": float(indexed["baseline_hit"].mean()),
        "candidate_minus_baseline": date_ci(indexed, "hit_delta", dates, schedule),
        "changed_pair_races": int(len(change)),
        "wins_on_changed_pairs": int(change["hit_delta"].eq(1.0).sum()),
        "losses_on_changed_pairs": int(change["hit_delta"].eq(-1.0).sum()),
        "ties_on_changed_pairs": int(change["hit_delta"].eq(0.0).sum()),
        "unchanged_pair_races": int((~indexed["pair_changed"]).sum()),
    }
    raw = selected_one(baseline_pairs, RAW_TOP2_SELECTOR)
    require(int(raw["y_pair"].sum()) == 429,
            "saved raw Top2 selected-hit total differs from its frozen 429/1,779 reference")
    raw_comp = raw[keys].copy().rename(columns={"horse_i": "raw_horse_i", "horse_j": "raw_horse_j", "y_pair": "raw_hit"})
    raw_join = cand.merge(raw_comp, on=["race_id", "race_date", "evaluation_year", "distance_m"],
                          how="inner", validate="one_to_one")
    require(len(raw_join) == EXPECTED_RACES, "raw Top2 comparison does not cover every race")
    raw_join["difference"] = raw_join["candidate_hit"].astype(float) - raw_join["raw_hit"].astype(float)
    raw_join["pair_changed"] = raw_join["candidate_horse_i"].ne(raw_join["raw_horse_i"]) \
        | raw_join["candidate_horse_j"].ne(raw_join["raw_horse_j"])
    raw_indexed = add_date_index(raw_join, dates)
    comparison["secondary_raw_top2_429"] = {
        "candidate_hits": int(raw_indexed["candidate_hit"].sum()),
        "raw_top2_hits": int(raw_indexed["raw_hit"].sum()),
        "candidate_minus_raw_top2": date_ci(raw_indexed, "difference", dates, schedule),
        "changed_pair_races": int(raw_indexed["pair_changed"].sum()),
        "wins_on_changed_pairs": int(raw_indexed.loc[raw_indexed["pair_changed"], "difference"].eq(1.0).sum()),
        "losses_on_changed_pairs": int(raw_indexed.loc[raw_indexed["pair_changed"], "difference"].eq(-1.0).sum()),
        "ties_on_changed_pairs": int(raw_indexed.loc[raw_indexed["pair_changed"], "difference"].eq(0.0).sum()),
    }
    return comparison, indexed


def join_baseline_pair_states(baseline_pairs: pd.DataFrame, runner_basis: pd.DataFrame,
                              races: pd.DataFrame) -> pd.DataFrame:
    runner_basis = runner_basis.loc[:, RUNNER_STATE_COLUMNS].copy()
    runner_basis["race_id"] = runner_basis["race_id"].astype("string")
    runner_basis["horse_number"] = pd.to_numeric(runner_basis["horse_number"], errors="raise").astype("int64")
    require(not runner_basis.duplicated(["race_id", "horse_number"]).any(), "runner status key is not unique")
    for column in ("previous_rider_retained", "previous_rider_unknown", "horse_current_rider_first_observed",
                   "horse_current_rider_history_unavailable"):
        require(runner_basis[column].isin([0, 1, 0.0, 1.0]).all(), f"runner status is not binary: {column}")
    require((runner_basis["previous_rider_unknown"] == runner_basis["horse_current_rider_history_unavailable"]).all(),
            "source status duplicate unexpectedly differs")
    require((runner_basis["horse_current_rider_first_observed"]
             + runner_basis["horse_current_rider_history_unavailable"]
             + runner_basis["horse_current_rider_prior_n"].gt(0).astype(int) == 1).all(),
            "current-rider history states are not mutually exclusive")
    baseline_selected = selected_one(baseline_pairs, OLD_BASELINE_SELECTOR)
    keys = ["race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j", "y_pair"]
    left = runner_basis.rename(columns={
        "horse_number": "horse_i",
        "previous_rider_retained": "retained_i",
        "previous_rider_unknown": "previous_unknown_i",
        "horse_current_rider_first_observed": "first_i",
        "horse_current_rider_history_unavailable": "history_unknown_i",
        "horse_current_rider_prior_n": "prior_n_i",
    })
    right = runner_basis.rename(columns={
        "horse_number": "horse_j",
        "previous_rider_retained": "retained_j",
        "previous_rider_unknown": "previous_unknown_j",
        "horse_current_rider_first_observed": "first_j",
        "horse_current_rider_history_unavailable": "history_unknown_j",
        "horse_current_rider_prior_n": "prior_n_j",
    })
    left_columns = ["race_id", "horse_i", "retained_i", "previous_unknown_i", "first_i", "history_unknown_i", "prior_n_i"]
    right_columns = ["race_id", "horse_j", "retained_j", "previous_unknown_j", "first_j", "history_unknown_j", "prior_n_j"]
    states = baseline_selected[keys].merge(left[left_columns], on=["race_id", "horse_i"], how="left", validate="one_to_one")
    states = states.merge(right[right_columns], on=["race_id", "horse_j"], how="left", validate="one_to_one")
    require(states[["retained_i", "previous_unknown_i", "first_i", "history_unknown_i", "prior_n_i",
                    "retained_j", "previous_unknown_j", "first_j", "history_unknown_j", "prior_n_j"]].notna().all().all(),
            "baseline selected pair lacks a frozen runner state")
    states["previous_unknown_count"] = states["previous_unknown_i"].astype(int) + states["previous_unknown_j"].astype(int)
    states["previous_retained_count"] = states["retained_i"].astype(int) + states["retained_j"].astype(int)
    states["previous_switch_count"] = 2 - states["previous_unknown_count"] - states["previous_retained_count"]
    require(states["previous_switch_count"].between(0, 2).all(), "invalid previous-rider switch count")
    def prev_label(row: pd.Series) -> str:
        unknown = int(row["previous_unknown_count"])
        switches = int(row["previous_switch_count"])
        return f"unknown {unknown}; confirmed switch {switches}" if unknown else f"confirmed switch {switches}"
    states["previous_rider_group"] = states.apply(prev_label, axis=1)
    states["first_observed_count"] = states["first_i"].astype(int) + states["first_j"].astype(int)
    states["history_unknown_count"] = states["history_unknown_i"].astype(int) + states["history_unknown_j"].astype(int)
    states["repeated_count"] = states["prior_n_i"].gt(0).astype(int) + states["prior_n_j"].gt(0).astype(int)
    require((states["first_observed_count"] + states["history_unknown_count"] + states["repeated_count"] == 2).all(),
            "baseline pair rider-history status counts do not sum to two")
    states["current_rider_history_group"] = states.apply(
        lambda row: f"first {int(row['first_observed_count'])}, repeated {int(row['repeated_count'])}, unknown {int(row['history_unknown_count'])}",
        axis=1,
    )
    result = races.merge(states[["race_id", "previous_rider_group", "current_rider_history_group",
                                 "previous_switch_count", "previous_unknown_count", "first_observed_count",
                                 "repeated_count", "history_unknown_count"]],
                         on="race_id", how="left", validate="one_to_one")
    require(result["previous_rider_group"].notna().all() and result["current_rider_history_group"].notna().all(),
            "baseline selected context groups do not cover all races")
    return result


def grouped_selection_report(races: pd.DataFrame, group_column: str, dates: list[str],
                             schedule: np.ndarray) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, part in races.groupby(group_column, sort=True, dropna=False):
        part = part.copy()
        part["hit_delta"] = part["candidate_hit"].astype(float) - part["baseline_hit"].astype(float)
        indexed = add_date_index(part, dates)
        changed = indexed.loc[indexed["pair_changed"]]
        rows.append({
            "group": str(label),
            "races": int(len(indexed)),
            "dates": int(indexed["race_date"].nunique()),
            "baseline_hits": int(indexed["baseline_hit"].sum()),
            "candidate_hits": int(indexed["candidate_hit"].sum()),
            "baseline_rate": float(indexed["baseline_hit"].mean()),
            "candidate_rate": float(indexed["candidate_hit"].mean()),
            "candidate_minus_baseline": date_ci(indexed, "hit_delta", dates, schedule),
            "changed_pair_races": int(len(changed)),
            "wins": int(changed["hit_delta"].eq(1.0).sum()),
            "losses": int(changed["hit_delta"].eq(-1.0).sum()),
            "ties": int(changed["hit_delta"].eq(0.0).sum()),
            "descriptive_only": bool(len(indexed) < 100 or indexed["race_date"].nunique() < 20),
        })
    return rows


def grouped_by_field(races: pd.DataFrame, group_column: str, dates: list[str],
                     schedule: np.ndarray) -> list[dict[str, Any]]:
    rows = []
    for value, part in races.groupby(group_column, sort=True):
        part = part.copy()
        part["hit_delta"] = part["candidate_hit"].astype(float) - part["baseline_hit"].astype(float)
        indexed = add_date_index(part, dates)
        rows.append({
            "value": int(value),
            "races": int(len(indexed)),
            "dates": int(indexed["race_date"].nunique()),
            "baseline_hits": int(indexed["baseline_hit"].sum()),
            "candidate_hits": int(indexed["candidate_hit"].sum()),
            "baseline_rate": float(indexed["baseline_hit"].mean()),
            "candidate_rate": float(indexed["candidate_hit"].mean()),
            "candidate_minus_baseline": date_ci(indexed, "hit_delta", dates, schedule),
        })
    return rows


def reliability_table(frame: pd.DataFrame, probability_column: str, equal_race_weight: bool) -> list[dict[str, Any]]:
    work = frame[["race_id", probability_column, "y_pair"]].copy()
    work["p"] = work[probability_column].astype(float)
    if equal_race_weight:
        work["weight"] = 1.0 / work.groupby("race_id")["race_id"].transform("size")
    else:
        work["weight"] = 1.0
    rows = []
    for (lower, upper), name in zip(RELIABILITY_BINS, RELIABILITY_NAMES, strict=True):
        in_bin = work["p"].ge(lower) & (work["p"].le(upper) if upper == 1.0 else work["p"].lt(upper))
        subset = work.loc[in_bin]
        if subset.empty:
            rows.append({"bin": name, "pairs": 0, "races": 0, "predicted": None, "observed": None})
            continue
        weights = subset["weight"].to_numpy(dtype=float)
        total = float(weights.sum())
        rows.append({
            "bin": name,
            "pairs": int(len(subset)),
            "races": int(subset["race_id"].nunique()),
            "predicted": float(np.dot(weights, subset["p"].to_numpy(dtype=float)) / total),
            "observed": float(np.dot(weights, subset["y_pair"].to_numpy(dtype=float)) / total),
        })
    return rows


def coverage_summary(frame: pd.DataFrame, probability_column: str, dates: list[str],
                     schedule: np.ndarray, threshold: float = 0.20) -> dict[str, Any]:
    require(frame["race_id"].is_unique, "coverage summary requires one pair per race")
    selected = frame.loc[frame[probability_column].ge(threshold)].copy()
    selected = add_date_index(selected, dates)
    return {
        "threshold": threshold,
        "selected_races": int(len(frame)),
        "covered_races": int(len(selected)),
        "coverage": float(len(selected) / len(frame)) if len(frame) else None,
        "hits": int(selected["y_pair"].sum()),
        "hit_rate": float(selected["y_pair"].mean()) if len(selected) else None,
        "covered_hit_rate_date_ci": date_ci(selected, "y_pair", dates, schedule),
    }


def race_level_probabilities(frame: pd.DataFrame, probability_column: str) -> pd.DataFrame:
    result = frame[["race_id", "race_date", "evaluation_year", "distance_m", "y_pair", probability_column]].copy()
    result["brier_loss"], result["logloss_loss"] = probability_losses(result[probability_column], result["y_pair"])
    return result


def probability_comparisons(candidate: pd.DataFrame, baseline: pd.DataFrame,
                            baseline_selected: pd.DataFrame, candidate_selected: pd.DataFrame,
                            dates: list[str], schedule: np.ndarray) -> dict[str, Any]:
    # Candidate and baseline rows are already key-aligned and baseline columns
    # have been compared byte-for-value before this point.
    fixed = baseline_selected[["race_id", "horse_i", "horse_j", "race_date", "evaluation_year", "distance_m",
                               "y_pair", OLD_BASELINE_PROBABILITY]].copy()
    candidate_lookup = candidate.set_index(PAIR_KEYS)[CANDIDATE_PROBABILITY]
    fixed_index = pd.MultiIndex.from_frame(fixed[PAIR_KEYS])
    fixed[CANDIDATE_PROBABILITY] = candidate_lookup.reindex(fixed_index).to_numpy(dtype=float)
    require(fixed[CANDIDATE_PROBABILITY].notna().all(), "candidate probability missing on baseline-selected pair")
    fixed["candidate_brier"], fixed["candidate_logloss"] = probability_losses(fixed[CANDIDATE_PROBABILITY], fixed["y_pair"])
    fixed["baseline_brier"], fixed["baseline_logloss"] = probability_losses(fixed[OLD_BASELINE_PROBABILITY], fixed["y_pair"])
    fixed["brier_delta"] = fixed["candidate_brier"] - fixed["baseline_brier"]
    fixed["logloss_delta"] = fixed["candidate_logloss"] - fixed["baseline_logloss"]
    fixed = add_date_index(fixed, dates)
    fixed_metrics = {
        "races": int(len(fixed)),
        "baseline_brier": float(fixed["baseline_brier"].mean()),
        "candidate_brier": float(fixed["candidate_brier"].mean()),
        "candidate_minus_baseline_brier": date_ci(fixed, "brier_delta", dates, schedule),
        "baseline_logloss": float(fixed["baseline_logloss"].mean()),
        "candidate_logloss": float(fixed["candidate_logloss"].mean()),
        "candidate_minus_baseline_logloss": date_ci(fixed, "logloss_delta", dates, schedule),
    }

    candidate_races = race_level_probabilities(candidate, CANDIDATE_PROBABILITY)
    baseline_races = race_level_probabilities(baseline, OLD_BASELINE_PROBABILITY)
    per_race = candidate_races.groupby("race_id", sort=True)[["brier_loss", "logloss_loss"]].mean().rename(
        columns={"brier_loss": "candidate_brier", "logloss_loss": "candidate_logloss"}
    ).join(
        baseline_races.groupby("race_id", sort=True)[["brier_loss", "logloss_loss"]].mean().rename(
            columns={"brier_loss": "baseline_brier", "logloss_loss": "baseline_logloss"}
        ), validate="one_to_one"
    )
    meta = candidate[["race_id", "race_date", "evaluation_year", "distance_m"]].drop_duplicates("race_id").set_index("race_id")
    per_race = meta.join(per_race, validate="one_to_one").reset_index()
    per_race["brier_delta"] = per_race["candidate_brier"] - per_race["baseline_brier"]
    per_race["logloss_delta"] = per_race["candidate_logloss"] - per_race["baseline_logloss"]
    per_race = add_date_index(per_race, dates)
    all_pairs = {
        "races": int(len(per_race)),
        "baseline_brier": float(per_race["baseline_brier"].mean()),
        "candidate_brier": float(per_race["candidate_brier"].mean()),
        "candidate_minus_baseline_brier": date_ci(per_race, "brier_delta", dates, schedule),
        "baseline_logloss": float(per_race["baseline_logloss"].mean()),
        "candidate_logloss": float(per_race["candidate_logloss"].mean()),
        "candidate_minus_baseline_logloss": date_ci(per_race, "logloss_delta", dates, schedule),
    }

    baseline_selected = baseline_selected.copy()
    candidate_selected = candidate_selected.copy()
    baseline_selected_index = pd.MultiIndex.from_frame(baseline_selected[PAIR_KEYS])
    baseline_selected[CANDIDATE_PROBABILITY] = candidate_lookup.reindex(baseline_selected_index).to_numpy(dtype=float)
    reliability = {
        "all_pairs_race_equal_weight": {
            "baseline_id": reliability_table(baseline, OLD_BASELINE_PROBABILITY, True),
            "candidate": reliability_table(candidate, CANDIDATE_PROBABILITY, True),
        },
        "selected_pair_cases": {
            "baseline_id_on_its_selection": reliability_table(baseline_selected, OLD_BASELINE_PROBABILITY, False),
            "candidate_on_baseline_id_selection": reliability_table(baseline_selected, CANDIDATE_PROBABILITY, False),
            "candidate_on_its_selection": reliability_table(candidate_selected, CANDIDATE_PROBABILITY, False),
        },
    }
    candidate_selected_confidence = candidate_selected[["race_id", "race_date", "evaluation_year", "distance_m", "y_pair",
                                                         CANDIDATE_PROBABILITY]].copy()
    baseline_selected_confidence = baseline_selected[["race_id", "race_date", "evaluation_year", "distance_m", "y_pair",
                                                       OLD_BASELINE_PROBABILITY, CANDIDATE_PROBABILITY]].copy()
    coverage = {
        "baseline_id_on_its_selection": coverage_summary(
            baseline_selected_confidence.rename(columns={OLD_BASELINE_PROBABILITY: "p"}), "p", dates, schedule
        ),
        "candidate_on_baseline_selection": coverage_summary(
            baseline_selected_confidence.rename(columns={CANDIDATE_PROBABILITY: "p"}), "p", dates, schedule
        ),
        "candidate_on_its_selection": coverage_summary(
            candidate_selected_confidence.rename(columns={CANDIDATE_PROBABILITY: "p"}), "p", dates, schedule
        ),
    }
    probability_sums = {}
    for name, frame, column in (
        ("baseline_id", baseline, OLD_BASELINE_PROBABILITY),
        ("candidate", candidate, CANDIDATE_PROBABILITY),
    ):
        sums = frame.groupby("race_id")[column].sum().to_numpy(dtype=float)
        residual = sums - 3.0
        probability_sums[name] = {
            "races": int(len(sums)),
            "mean_signed_sum_minus_3": float(np.mean(residual)),
            "mean_absolute_sum_minus_3": float(np.mean(np.abs(residual))),
            "p95_absolute_sum_minus_3": float(np.quantile(np.abs(residual), 0.95)),
        }
    return {"fixed_baseline_selected_pair": fixed_metrics, "all_pairs_race_equal": all_pairs,
            "reliability": reliability, "coverage_at_20pct": coverage,
            "pair_probability_sum_diagnostic": probability_sums}


def gates(selection: dict[str, Any], probability: dict[str, Any]) -> dict[str, Any]:
    hit = selection["candidate_minus_baseline"]
    selection_pass = bool(hit["estimate"] is not None and hit["estimate"] > 0
                          and hit["ci_low"] is not None and hit["ci_low"] > 0)
    fixed = probability["fixed_baseline_selected_pair"]
    brier = fixed["candidate_minus_baseline_brier"]
    logloss = fixed["candidate_minus_baseline_logloss"]
    fixed_point_nonworse = bool(brier["estimate"] <= 0 and logloss["estimate"] <= 0)
    fixed_pass = bool(fixed_point_nonworse and (
        (brier["ci_high"] is not None and brier["ci_high"] < 0)
        or (logloss["ci_high"] is not None and logloss["ci_high"] < 0)
    ))
    all_pairs = probability["all_pairs_race_equal"]
    all_pass = bool(all_pairs["candidate_minus_baseline_brier"]["estimate"] <= 0
                    and all_pairs["candidate_minus_baseline_logloss"]["estimate"] <= 0)
    all_gates = selection_pass and fixed_pass and all_pass
    return {
        "selection_improvement": {"passed": selection_pass, "criterion": "candidate hit-rate lift > 0 and paired date CI lower bound > 0"},
        "fixed_baseline_pair_probability": {"passed": fixed_pass, "point_estimates_nonworse": fixed_point_nonworse,
                                             "criterion": "both candidate-minus-baseline Brier and log loss <= 0; at least one paired date CI upper bound < 0"},
        "all_pair_guard": {"passed": all_pass, "criterion": "candidate-minus-baseline race-equal Brier and log loss both <= 0"},
        "composite_passed": bool(all_gates),
        "decision": "predeclared composite gate passed" if all_gates else "improvement not established; retain as unadopted research candidate",
    }


def attach_selected_probabilities(races: pd.DataFrame, baseline: pd.DataFrame,
                                 candidate: pd.DataFrame) -> pd.DataFrame:
    baseline_lookup = baseline.set_index(PAIR_KEYS)[OLD_BASELINE_PROBABILITY]
    candidate_lookup = candidate.set_index(PAIR_KEYS)[CANDIDATE_PROBABILITY]
    baseline_keys = pd.MultiIndex.from_frame(races[["race_id", "baseline_horse_i", "baseline_horse_j"]].rename(
        columns={"baseline_horse_i": "horse_i", "baseline_horse_j": "horse_j"}
    )[PAIR_KEYS])
    candidate_keys = pd.MultiIndex.from_frame(races[["race_id", "candidate_horse_i", "candidate_horse_j"]].rename(
        columns={"candidate_horse_i": "horse_i", "candidate_horse_j": "horse_j"}
    )[PAIR_KEYS])
    result = races.copy()
    result["baseline_selected_pair_baseline_probability"] = baseline_lookup.reindex(baseline_keys).to_numpy(dtype=float)
    result["baseline_selected_pair_candidate_probability"] = candidate_lookup.reindex(baseline_keys).to_numpy(dtype=float)
    result["candidate_selected_pair_candidate_probability"] = candidate_lookup.reindex(candidate_keys).to_numpy(dtype=float)
    require(result[["baseline_selected_pair_baseline_probability", "baseline_selected_pair_candidate_probability",
                    "candidate_selected_pair_candidate_probability"]].notna().all().all(),
            "selected-pair probabilities are missing from saved pair predictions")
    return result


def paired_race_artifact_frame(context: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "race_id", "race_date", "evaluation_year", "distance_m",
        "baseline_horse_i", "baseline_horse_j", "candidate_horse_i", "candidate_horse_j",
        "baseline_hit", "candidate_hit", "pair_changed", "hit_delta",
        "baseline_selected_pair_baseline_probability", "baseline_selected_pair_candidate_probability",
        "candidate_selected_pair_candidate_probability", "previous_rider_group", "previous_switch_count",
        "previous_unknown_count", "current_rider_history_group", "first_observed_count", "repeated_count",
        "history_unknown_count",
    ]
    result = context.loc[:, columns].copy().sort_values(["race_date", "race_id"], kind="mergesort")
    result["baseline_hit"] = result["baseline_hit"].astype(int)
    result["candidate_hit"] = result["candidate_hit"].astype(int)
    result["pair_changed"] = result["pair_changed"].astype(bool)
    return result.reset_index(drop=True)


def csv_text(frame: pd.DataFrame) -> str:
    return frame.to_csv(index=False, lineterminator="\n", float_format="%.12g")


def report_json_text(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def build_report() -> tuple[dict[str, Any], str, pd.DataFrame]:
    prefit_lineage = verify_pre_fitting_lineage()
    baseline, candidate, fit, fit_receipt, prediction_receipt = validate_fit_and_predictions()
    dates = sorted(candidate["race_date"].unique().tolist())
    schedule, schedule_receipt = load_bootstrap(dates)
    candidate_pairs = candidate.copy()
    baseline_pairs = baseline.copy()
    for frame in (candidate_pairs, baseline_pairs):
        frame["y_pair"] = pd.to_numeric(frame["y_pair"], errors="raise").astype(int)
    selection, races = race_choice_comparison(candidate_pairs, baseline_pairs, dates, schedule)
    races = attach_selected_probabilities(races, baseline_pairs, candidate_pairs)
    probability = probability_comparisons(
        candidate_pairs, baseline_pairs,
        selected_one(baseline_pairs, OLD_BASELINE_SELECTOR),
        selected_one(candidate_pairs, CANDIDATE_SELECTOR), dates, schedule,
    )
    runner_basis = pd.read_parquet(checked(RUNNER_BASIS), columns=RUNNER_STATE_COLUMNS)
    context = join_baseline_pair_states(baseline_pairs, runner_basis, races)
    context_tables = {
        "previous_rider_status_on_baseline_pair": grouped_selection_report(context, "previous_rider_group", dates, schedule),
        "current_rider_history_on_baseline_pair": grouped_selection_report(context, "current_rider_history_group", dates, schedule),
    }
    by_year = grouped_by_field(races, "evaluation_year", dates, schedule)
    by_distance = grouped_by_field(races, "distance_m", dates, schedule)
    result = {
        "study": STUDY.name,
        "status": "PASS",
        "evaluation": {
            "years": [2024, 2025, 2026], "races": EXPECTED_RACES, "dates": EXPECTED_DATES,
            "pair_rows": EXPECTED_PAIR_ROWS, "date_min": dates[0], "date_max": dates[-1],
            "year_races": EXPECTED_YEAR_RACES, "date_bootstrap_draws": int(schedule.shape[0]),
            "bootstrap_seed": int(schedule_receipt["seed"]),
            "bootstrap_schedule_sha256": sha256(checked(BOOTSTRAP)),
            "bootstrap_receipt": {
                key: schedule_receipt[key] for key in (
                    "status", "generator", "bit_generator", "seed", "numpy_version", "draws",
                    "dates_per_draw", "schedule_shape", "date_inventory_sha256", "date_min", "date_max",
                    "schedule_sha256", "source_features_sha256",
                )
            },
            "repeated_development_sample": True, "2026_partial_through": dates[-1],
        },
        "candidate": {
            "outcome": "unordered pair both in official Top3",
            "frozen_horse_scores": "saved F1_STYLE6 runner scores; unchanged",
            "baseline_pair_model": "saved jockey-ID pair candidate, 20 style bases + rolling365 scalar + 39 H1-only jockey ID effects",
            "candidate_pair_model": "same 60-column baseline plus riding-condition bundle; one H1 fit and one H2 positive-slope Platt map per fold",
            "raw_riding_condition_columns": 10,
            "active_riding_condition_columns_by_fold": prefit_lineage["active_candidate_columns_by_fold"],
            "exact_duplicate_removed": {"horse_current_rider_history_unavailable_count": "previous_rider_unknown_count"},
            "h1_fit_count": fit.get("h1_fit_count"),
            "h2_calibration_count": fit.get("h2_candidate_map_count"),
            "fit_receipt_sha256": sha256(checked(FIT_RECEIPT)),
            "prediction_receipt_sha256": sha256(checked(PREDICTION_RECEIPT)),
            "prediction_sha256": sha256(checked(PREDICTIONS)),
            "metrics_created_only_after_prediction": True,
            "payout_or_roi_inputs_used": False,
        },
        "pre_fit_lineage": prefit_lineage,
        "selection_comparison_to_saved_id": selection,
        "probability_comparison": probability,
        "baseline_selected_pair_context": context_tables,
        "selection_by_year": by_year,
        "selection_by_distance_m": by_distance,
        "predeclared_gates": gates(selection, probability),
        "report_artifacts": {
            "summary_json": str(REPORT_JSON.relative_to(STUDY)),
            "paired_race_metrics_csv": str(PAIRED_RACE_CSV.relative_to(STUDY)),
            "changed_selections_csv": str(CHANGED_SELECTIONS_CSV.relative_to(STUDY)),
            "paired_race_rows": int(len(context)),
            "changed_selection_rows": int(selection["changed_pair_races"]),
        },
        "source_limits": {
            "time_cutoff": "T−2 calendar days inclusive; publication timestamps were unavailable",
            "full_history": "observed started history, not confirmed lifetime record",
            "evaluation": "reused retrospective development period; not independent future holdout",
            "interpretation": "conditional association in the two-horse co-Top3 selection layer; not causal rider ability or exact finishing-order evidence",
        },
    }
    if DOCUMENT_CORRECTION_RECEIPT.exists():
        result["document_correction"] = verify_document_correction_snapshots()
    return result, render_readme(result), paired_race_artifact_frame(context)


def fmt_number(value: Any, digits: int = 4) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    return f"{float(value):.{digits}f}"


def fmt_pct(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{100.0 * float(value):.{digits}f}%"


def fmt_pp(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    return f"{100.0 * float(value):+.{digits}f}%p"


def fmt_ci(ci: dict[str, Any], scale: float = 100.0, digits: int = 3) -> str:
    if ci.get("ci_low") is None or ci.get("ci_high") is None:
        return "—"
    return f"[{scale * float(ci['ci_low']):+.{digits}f}, {scale * float(ci['ci_high']):+.{digits}f}]"


def fmt_rate_ci_percent(ci: dict[str, Any], digits: int = 3) -> str:
    if ci.get("ci_low") is None or ci.get("ci_high") is None:
        return "—"
    return f"[{100.0 * float(ci['ci_low']):.{digits}f}%, {100.0 * float(ci['ci_high']):.{digits}f}%]"


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def selection_table(selection: dict[str, Any], key: str = "candidate_minus_baseline") -> list[list[str]]:
    ci = selection[key]
    return [[
        f"{selection['baseline_hits']:,}/{selection['races']:,}", fmt_pct(selection["baseline_hit_rate"]),
        f"{selection['candidate_hits']:,}/{selection['races']:,}", fmt_pct(selection["candidate_hit_rate"]),
        fmt_pp(ci["estimate"]), fmt_ci(ci),
    ]]


def render_readme(result: dict[str, Any]) -> str:
    selection = result["selection_comparison_to_saved_id"]
    probability = result["probability_comparison"]
    gate = result["predeclared_gates"]
    fixed = probability["fixed_baseline_selected_pair"]
    all_pairs = probability["all_pairs_race_equal"]
    raw = selection["secondary_raw_top2_429"]
    lines = [
        "# 제주 F1_STYLE6 pair 기승조건 증분 비교",
        "",
        f"**사전 지정 복합 게이트 판정: {gate['decision']}.** 이 결과는 2024–2026 반복 개발 자료에서 저장 기수-ID pair 후보에 기승조건 묶음 하나를 추가한 비교다. 2026년 자료는 9월 19일까지의 부분연도이며 독립 미래 검증이 아니다.",
        "",
        "말별 F1_STYLE6 점수, 기존 pair 선택 기준, 평가 roster와 평가 목표를 고정했다. 평가 목표는 선택한 두 말이 공식 Top3에 함께 드는 사건이다. 정확한 1·2·3착 순서나 운영 HY_R_FORM의 직접 비교는 이번 실험 범위가 아니다.",
        "",
        "## 사전 지정 게이트",
        "",
        markdown_table(
            ["기준 적중", "기준 적중률", "후보 적중", "후보 적중률", "차이", "paired 날짜 95% CI (%p)"],
            selection_table(selection),
        ),
        "",
        f"후보가 바꾼 선택은 {selection['changed_pair_races']:,}경주다. 바뀐 조합에서 적중을 얻은 경주는 {selection['wins_on_changed_pairs']:,}, 기준 적중을 잃은 경주는 {selection['losses_on_changed_pairs']:,}, 결과가 같은 경주는 {selection['ties_on_changed_pairs']:,}였다. 기존 말 점수와 기수-ID 비교기 출력은 그대로 유지됐다.",
        "",
        f"선택 적중은 baseline {selection['baseline_hits']:,}회에서 후보 {selection['candidate_hits']:,}회로 1회 줄었다(차이 {fmt_pp(selection['candidate_minus_baseline']['estimate'])}, paired date 95% CI {fmt_ci(selection['candidate_minus_baseline'])}); 따라서 선택 개선 gate는 미통과다. 한편 같은 baseline 선택 pair에 확률만 적용한 Brier 차이는 {fmt_number(fixed['candidate_minus_baseline_brier']['estimate'], 7)} (95% CI {fmt_ci(fixed['candidate_minus_baseline_brier'], 1.0, 7)}), log loss 차이는 {fmt_number(fixed['candidate_minus_baseline_logloss']['estimate'], 7)} (95% CI {fmt_ci(fixed['candidate_minus_baseline_logloss'], 1.0, 7)})로 둘 다 개선됐다. 전체 pair 경주균등 Brier 차이는 {fmt_number(all_pairs['candidate_minus_baseline_brier']['estimate'], 7)} (95% CI {fmt_ci(all_pairs['candidate_minus_baseline_brier'], 1.0, 7)}), log loss 차이는 {fmt_number(all_pairs['candidate_minus_baseline_logloss']['estimate'], 7)} (95% CI {fmt_ci(all_pairs['candidate_minus_baseline_logloss'], 1.0, 7)})다. 따라서 확률 점수에는 증분 신호가 보이지만 선택쌍 적중 개선을 입증하지 못해 사전 복합 gate는 실패하며, 후보를 미채택 연구 상태로 둔다. 이는 정확 착순 순서 개선의 증거도 아니다.",
        "",
        markdown_table(
            ["Gate", "결과", "기준"],
            [
                ["선택 적중 개선", "PASS" if gate["selection_improvement"]["passed"] else "미통과",
                 gate["selection_improvement"]["criterion"]],
                ["기준 선택 pair 확률 개선", "PASS" if gate["fixed_baseline_pair_probability"]["passed"] else "미통과",
                 gate["fixed_baseline_pair_probability"]["criterion"]],
                ["전체 pair 확률 guard", "PASS" if gate["all_pair_guard"]["passed"] else "미통과",
                 gate["all_pair_guard"]["criterion"]],
                ["복합 판정", "PASS" if gate["composite_passed"] else "미통과", "세 gate 모두 PASS일 때만 복합 개선"],
            ],
        ),
        "",
        "세 gate 모두 PASS일 때만 사전 복합 개선으로 판정한다. 미통과는 효과가 없다는 증명이 아니며, 예측 개선이 확인되지 않은 후보는 미채택 상태로 둔다.",
        "",
        "### 같은 pair의 확률과 전체 pair 분포",
        "",
        markdown_table(
            ["평가", "기준 Brier", "후보 Brier", "후보−기준 95% CI", "기준 log loss", "후보 log loss", "후보−기준 95% CI"],
            [
                ["기준 ID 선택 pair 고정", fmt_number(fixed["baseline_brier"], 6), fmt_number(fixed["candidate_brier"], 6),
                 fmt_ci(fixed["candidate_minus_baseline_brier"], 1.0, 6), fmt_number(fixed["baseline_logloss"], 6),
                 fmt_number(fixed["candidate_logloss"], 6), fmt_ci(fixed["candidate_minus_baseline_logloss"], 1.0, 6)],
                ["전체 pair, 경주 균등 평균", fmt_number(all_pairs["baseline_brier"], 6), fmt_number(all_pairs["candidate_brier"], 6),
                 fmt_ci(all_pairs["candidate_minus_baseline_brier"], 1.0, 6), fmt_number(all_pairs["baseline_logloss"], 6),
                 fmt_number(all_pairs["candidate_logloss"], 6), fmt_ci(all_pairs["candidate_minus_baseline_logloss"], 1.0, 6)],
            ],
        ),
        "",
        "기준 선택 pair 고정 지표는 같은 두 말에 대한 확률만 바꿔 비교한다. 전체 pair 지표는 각 경주 안의 모든 무순서 pair loss를 평균한 뒤 경주를 동일 가중한다. 둘은 후보가 바꾼 pair의 적중률과 서로 다른 평가다.",
        "",
        "### 확률 calibration과 coverage",
        "",
        "신뢰도 표의 각 구간은 예측확률과 실제 동시입상률을 함께 표시한다. 전체 pair 표는 경주별 총가중치를 같게 둔다. 선택 pair 표는 해당 selection 정책의 경주당 한 pair를 사용한다.",
        "",
        render_reliability_tables(probability["reliability"]),
        "",
        markdown_table(
            ["선택·확률 적용", "기준 경주", "p≥20% 경주", "Coverage", "적중/선택", "선택집단 적중률", "날짜 95% CI (%)"],
            coverage_rows(probability["coverage_at_20pct"]),
        ),
        "",
        "### 저장 기수-ID 선택 pair의 rider 상태별 결과",
        "",
        "하위집단은 후보가 새로 고른 pair가 아니라 저장 기수-ID 기준 후보가 선택한 pair의 T−2 rider 상태로 고정했다. 따라서 분모가 후보 선택에 따라 바뀌지 않는다. 희소한 하위집단은 설명용이며 별도 채택 gate가 아니다.",
        "",
        "직전 기수 유지·교체 상태:",
        "",
        render_context_table(result["baseline_selected_pair_context"]["previous_rider_status_on_baseline_pair"]),
        "",
        "현재 말×기수 이력의 first-observed / repeated / unknown 상태:",
        "",
        render_context_table(result["baseline_selected_pair_context"]["current_rider_history_on_baseline_pair"]),
        "",
        "### 연도·거리별 선택 결과",
        "",
        markdown_table(["연도", "경주", "기준 적중", "후보 적중", "기준률", "후보률", "차이", "날짜 95% CI (%p)"],
                       field_rows(result["selection_by_year"], "value")),
        "",
        markdown_table(["거리(m)", "경주", "기준 적중", "후보 적중", "기준률", "후보률", "차이", "날짜 95% CI (%p)"],
                       field_rows(result["selection_by_distance_m"], "value")),
        "",
        "연도·거리 표는 성능 방향의 안정성을 살피는 보조표다. 하위기간 결과로 새 규칙을 만들거나 이번 단일 후보를 다시 튜닝하지 않았다.",
        "",
        "### 보조 비교: raw F1_STYLE6 상위 두 말",
        "",
        markdown_table(
            ["비교", "raw Top2 적중", "후보 적중", "변경 경주", "후보 승", "기준 승", "동률", "차이", "날짜 95% CI"],
            [[f"후보 − raw Top2", f"{raw['raw_top2_hits']:,}/{EXPECTED_RACES:,}", f"{raw['candidate_hits']:,}/{EXPECTED_RACES:,}",
              str(raw["changed_pair_races"]), str(raw["wins_on_changed_pairs"]), str(raw["losses_on_changed_pairs"]),
              str(raw["ties_on_changed_pairs"]), fmt_pp(raw["candidate_minus_raw_top2"]["estimate"]),
              fmt_ci(raw["candidate_minus_raw_top2"]) ]],
        ),
        "",
        "이 비교는 PLAN에서 보조로 지정했으며 복합 gate에 포함하지 않는다.",
        "",
        "## 입력·평가 계약",
        "",
        "- 저장 F1_STYLE6 점수와 기존 기수-ID pair 후보의 모든 54개 열을 동결했다. 새 runner 상태 10개를 unordered pair 양 끝 말에서 합산했다. H1에서 `horse_current_rider_history_unavailable_count`가 `previous_rider_unknown_count`와 정확히 중복되어 첫 열만 유지했고, fold별 활성 rider-condition 입력은 9개였다. 총 공동 입력은 각 fold 69열이다.",
        "- 세 평가 fold는 2024년 637경주, 2025년 654경주, 2026년 488경주다. H1에서 fold별 1회 적합, H2에서 양의 기울기를 갖는 Platt 보정 1회, 총 3+3회만 수행했다. 추가 arm, 재시도, 튜닝은 하지 않았다.",
        "- bootstrap은 기존 고정 269경주일·seed 20261011·2,000회 paired date schedule을 사용했다. 같은 경주일의 경주를 묶어 경주일 단위로 재표집했다.",
        "- rider history는 보유 started 기록이며 생애 전체 기승 자료라고 보장하지 않는다. 모든 feature cutoff는 대상 경주일 기준 T−2 포함이다. 기록 공개 timestamp가 없으므로 T−2는 실제 공개를 확인한 시각이 아니다.",
        "- 승식 배당, 사후 배당, ROI는 입력이나 결과에 사용하지 않았다. 이번 모델은 pair 동시 Top3 분류기이며 정확 Top3 순서 예측기가 아니다.",
        "",
        "## 재현 자료와 상태",
        "",
        f"- 입력·독립 prefit 감사: `SOURCE_AUDIT.md`, `audit/independent_prefit_receipt.json`, `audit/independent_h1_duplicate_receipt.json`, `outputs_prefit_v2/SAVED_ID_RECONCILIATION.json`, `outputs_prefit_v2/NEW_CANDIDATE_FIRST60_RECONCILIATION.json`.",
        f"- 후보 적합·예측 receipt: `outputs/FIT_RECEIPT.json`, `outputs/PREDICTION_RECEIPT.json`.",
        f"- prediction SHA-256: `{result['candidate']['prediction_sha256']}`.",
        f"- 고정 paired date schedule SHA-256: `{result['evaluation']['bootstrap_schedule_sha256']}`.",
        "- 전체 metric JSON은 `outputs/REPORT.json`, race별 선택·확률·기수 상태는 `outputs/report/paired_race_metrics.csv`, 선택 변경 경주는 `outputs/report/changed_selections.csv`에 저장했다.",
        "- 문서 정정 receipt와 정정 전 README, REPORT.json, manifest 사본은 `DOCUMENT_CORRECTION_RECEIPT.json` 및 `review_snapshots/pre_document_fix/`에 보존했다.",
        f"- 독립 root metrics 확인: `{ROOT_REVIEW.name}` (manifest 단계에서 PASS와 prediction hash를 확인). 검산 PASS는 독립 재계산 일치이며 모델 성능개선 PASS를 뜻하지 않는다.",
        "- 실험 결과는 운영 모델, 데이터베이스, 등록부, 중앙 결론을 변경하지 않는다.",
        "",
    ]
    return "\n".join(lines)


def render_reliability_tables(reliability: dict[str, Any]) -> str:
    chunks = []
    groups = [
        ("전체 pair: baseline ID", reliability["all_pairs_race_equal_weight"]["baseline_id"]),
        ("전체 pair: rider-condition 후보", reliability["all_pairs_race_equal_weight"]["candidate"]),
        ("ID 선택 pair: baseline ID 확률", reliability["selected_pair_cases"]["baseline_id_on_its_selection"]),
        ("ID 선택 pair: 후보 확률", reliability["selected_pair_cases"]["candidate_on_baseline_id_selection"]),
        ("후보 선택 pair: 후보 확률", reliability["selected_pair_cases"]["candidate_on_its_selection"]),
    ]
    for label, rows in groups:
        chunks.extend([
            f"**{label}**",
            "",
            markdown_table(["예측확률 구간", "pair", "경주", "가중 평균 예측", "가중 실제 비율"], [
                [row["bin"], f"{row['pairs']:,}", f"{row['races']:,}", fmt_pct(row["predicted"]), fmt_pct(row["observed"])]
                for row in rows
            ]),
            "",
        ])
    return "\n".join(chunks).rstrip()


def coverage_rows(coverage: dict[str, Any]) -> list[list[str]]:
    labels = {
        "baseline_id_on_its_selection": "baseline ID 선택 / baseline 확률",
        "candidate_on_baseline_selection": "baseline ID 선택 / 후보 확률",
        "candidate_on_its_selection": "후보 선택 / 후보 확률",
    }
    rows = []
    for name, item in coverage.items():
        ci = item["covered_hit_rate_date_ci"]
        rows.append([
            labels[name], f"{item['selected_races']:,}", f"{item['covered_races']:,}", fmt_pct(item["coverage"]),
            f"{item['hits']:,}/{item['covered_races']:,}", fmt_pct(item["hit_rate"]), fmt_rate_ci_percent(ci),
        ])
    return rows


def render_context_table(rows: list[dict[str, Any]]) -> str:
    return markdown_table(
        ["기준 pair 상태", "경주", "날짜", "ID 기준 적중", "후보 적중", "ID 기준률", "후보률", "차이", "날짜 95% CI (%p)", "변경 경주/승/패/동률"],
        [[row["group"], f"{row['races']:,}", f"{row['dates']:,}", f"{row['baseline_hits']:,}",
          f"{row['candidate_hits']:,}", fmt_pct(row["baseline_rate"]), fmt_pct(row["candidate_rate"]),
          fmt_pp(row["candidate_minus_baseline"]["estimate"]), fmt_ci(row["candidate_minus_baseline"]),
          f"{row['changed_pair_races']:,}/{row['wins']:,}/{row['losses']:,}/{row['ties']:,}" + (" · 설명용" if row["descriptive_only"] else "")]
         for row in rows],
    )


def field_rows(rows: list[dict[str, Any]], key: str) -> list[list[str]]:
    return [[
        str(row[key]), f"{row['races']:,}", f"{row['baseline_hits']:,}", f"{row['candidate_hits']:,}",
        fmt_pct(row["baseline_rate"]), fmt_pct(row["candidate_rate"]),
        fmt_pp(row["candidate_minus_baseline"]["estimate"]), fmt_ci(row["candidate_minus_baseline"]),
    ] for row in rows]


def verify_root_metrics(result: dict[str, Any]) -> dict[str, Any]:
    review = read_json(ROOT_REVIEW)
    require(review.get("status") == "PASS", "independent root metrics review is not PASS")
    require(review.get("baseline_sha256") == sha256(checked(BASE_PREDICTIONS)), "root review baseline hash mismatch")
    require(review.get("candidate_sha256") == sha256(checked(PREDICTIONS)), "root review candidate hash mismatch")
    require(review.get("all_old_columns_unchanged") is True and review.get("stable_argmax_verified") is True,
            "root review did not verify frozen columns and candidate argmax")
    require(review.get("training_runs") == 0 and review.get("database_access") is False
            and review.get("recorded_h1_fits") == 3 and review.get("recorded_h2_fits") == 3
            and review.get("probability_map_max_errors") == {"2024": 0.0, "2025": 0.0, "2026": 0.0},
            "root review did not certify a read-only, fit-free check of the frozen prediction artifacts")
    selection = result["selection_comparison_to_saved_id"]
    require(int(review.get("old_hits", -1)) == int(selection["baseline_hits"])
            and int(review.get("new_hits", -1)) == int(selection["candidate_hits"]),
            "independent root hit counts differ from report")
    require(int(review.get("changed", -1)) == int(selection["changed_pair_races"])
            and int(review.get("gains", -1)) == int(selection["wins_on_changed_pairs"])
            and int(review.get("losses", -1)) == int(selection["losses_on_changed_pairs"])
            and int(review.get("changed_ties", -1)) == int(selection["ties_on_changed_pairs"]),
            "independent root changed-pair counts differ from report")
    independent = review.get("independent_date_bootstrap", {})
    comparisons = {
        "hit_delta": selection["candidate_minus_baseline"],
        "fixed_brier_delta": result["probability_comparison"]["fixed_baseline_selected_pair"]["candidate_minus_baseline_brier"],
        "fixed_logloss_delta": result["probability_comparison"]["fixed_baseline_selected_pair"]["candidate_minus_baseline_logloss"],
        "all_brier_delta": result["probability_comparison"]["all_pairs_race_equal"]["candidate_minus_baseline_brier"],
        "all_logloss_delta": result["probability_comparison"]["all_pairs_race_equal"]["candidate_minus_baseline_logloss"],
    }
    for name, expected in comparisons.items():
        found = independent.get(name, {})
        interval = found.get("ci95")
        require(isinstance(interval, list) and len(interval) == 2
                and math.isclose(float(found.get("estimate", math.nan)), float(expected["estimate"]), rel_tol=0, abs_tol=1e-12)
                and math.isclose(float(interval[0]), float(expected["ci_low"]), rel_tol=0, abs_tol=1e-12)
                and math.isclose(float(interval[1]), float(expected["ci_high"]), rel_tol=0, abs_tol=1e-12),
                f"independent root metrics differ from report: {name}")
    return {"path": str(ROOT_REVIEW.relative_to(ROOT)), "sha256": sha256(checked(ROOT_REVIEW)),
            "status": review["status"], "scope": review.get("scope")}


def run_report() -> None:
    outputs = [README, REPORT_JSON, PAIRED_RACE_CSV, CHANGED_SELECTIONS_CSV]
    require(not MANIFEST.exists() and not MANIFEST.is_symlink()
            and all(not path.exists() and not path.is_symlink() for path in outputs),
            "one or more report outputs already exists; refusing to overwrite")
    result, markdown, paired_races = build_report()
    changed = paired_races.loc[paired_races["pair_changed"]].copy()
    require(len(paired_races) == EXPECTED_RACES
            and len(changed) == result["selection_comparison_to_saved_id"]["changed_pair_races"],
            "saved race-level artifacts do not align with the computed comparison")
    report_json = report_json_text(result)
    paired_csv = csv_text(paired_races)
    changed_csv = csv_text(changed)
    write_once(README, markdown)
    write_once(REPORT_JSON, report_json)
    write_once(PAIRED_RACE_CSV, paired_csv)
    write_once(CHANGED_SELECTIONS_CSV, changed_csv)
    print(json.dumps({
        "status": result["status"],
        "readme": str(README.relative_to(ROOT)),
        "candidate_hits": result["selection_comparison_to_saved_id"]["candidate_hits"],
        "baseline_hits": result["selection_comparison_to_saved_id"]["baseline_hits"],
        "gates": result["predeclared_gates"],
        "prediction_sha256": result["candidate"]["prediction_sha256"],
        "report_json": str(REPORT_JSON.relative_to(ROOT)),
        "paired_race_csv": str(PAIRED_RACE_CSV.relative_to(ROOT)),
        "changed_selections_csv": str(CHANGED_SELECTIONS_CSV.relative_to(ROOT)),
        "paired_race_rows": len(paired_races),
        "changed_selection_rows": len(changed),
    }, ensure_ascii=False, indent=2, allow_nan=False))


def replace_document_once(path: Path, content: str) -> None:
    require(path.is_relative_to(STUDY) and path.exists() and not path.is_symlink(),
            f"document replacement target must be an existing study file: {path}")
    temporary = path.with_name(f".{path.name}.document_fix.tmp")
    require(not temporary.exists() and not temporary.is_symlink(),
            f"temporary document path already exists: {temporary}")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(content)
    temporary.replace(path)


def run_refresh_documents() -> None:
    summary = verify_document_correction_snapshots()
    receipt = read_json(DOCUMENT_CORRECTION_RECEIPT)
    require(README.exists() and REPORT_JSON.exists() and MANIFEST.exists()
            and not README.is_symlink() and not REPORT_JSON.is_symlink() and not MANIFEST.is_symlink(),
            "all three pre-correction documents must still exist")
    for relative, path in (
        ("README.md", README),
        ("outputs/REPORT.json", REPORT_JSON),
        ("ARTIFACT_MANIFEST.json", MANIFEST),
    ):
        require(sha256(checked(path)) == receipt["previous_documents"][relative]["sha256"],
                f"current document changed after pre-correction snapshot: {relative}")

    old_report = read_json(STUDY / receipt["previous_documents"]["outputs/REPORT.json"]["snapshot_path"])
    result, markdown, paired_races = build_report()
    serialized_result = json.loads(report_json_text(result))
    require(all(serialized_result.get(key) == value for key, value in old_report.items()),
            "a pre-existing report field changed; document-only refresh is refused")
    require(result["candidate"]["prediction_sha256"] == receipt["previous_prediction_sha256"],
            "prediction artifact changed during document-only refresh")
    changed = paired_races.loc[paired_races["pair_changed"]].copy()
    require(checked(PAIRED_RACE_CSV).read_text(encoding="utf-8") == csv_text(paired_races)
            and checked(CHANGED_SELECTIONS_CSV).read_text(encoding="utf-8") == csv_text(changed),
            "frozen race-level result files changed during document-only refresh")
    verify_root_metrics(result)
    replace_document_once(README, markdown)
    replace_document_once(REPORT_JSON, report_json_text(result))
    run_manifest(replace_existing=True)
    print(json.dumps({
        "status": "PASS",
        "scope": "documentation only; model fit, prediction, and metric values unchanged",
        "receipt": str(DOCUMENT_CORRECTION_RECEIPT.relative_to(ROOT)),
        "snapshot_directory": str((STUDY / summary["snapshot_directory"]).relative_to(ROOT)),
        "readme": str(README.relative_to(ROOT)),
        "report_json": str(REPORT_JSON.relative_to(ROOT)),
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "prediction_sha256": result["candidate"]["prediction_sha256"],
    }, ensure_ascii=False, indent=2, allow_nan=False))


def run_manifest(*, replace_existing: bool = False) -> None:
    require(README.exists() and REPORT_JSON.exists() and PAIRED_RACE_CSV.exists()
            and CHANGED_SELECTIONS_CSV.exists()
            and ((MANIFEST.exists() and not MANIFEST.is_symlink()) if replace_existing
                 else (not MANIFEST.exists() and not MANIFEST.is_symlink())),
            "report outputs or manifest do not match the requested finalization mode")
    result, markdown, paired_races = build_report()
    require(checked(README).read_text(encoding="utf-8") == markdown,
            "README differs from frozen saved-prediction report")
    require(checked(REPORT_JSON).read_text(encoding="utf-8") == report_json_text(result),
            "REPORT.json differs from frozen saved-prediction metrics")
    changed = paired_races.loc[paired_races["pair_changed"]].copy()
    require(checked(PAIRED_RACE_CSV).read_text(encoding="utf-8") == csv_text(paired_races)
            and checked(CHANGED_SELECTIONS_CSV).read_text(encoding="utf-8") == csv_text(changed),
            "race-level CSV artifacts differ from frozen saved-prediction metrics")
    root_review = verify_root_metrics(result)
    source_inventory = read_json(SOURCE_HASHES)
    external_sources = {
        item["path"]: {"sha256": item["sha256"], "bytes": int(item["bytes"])}
        for item in source_inventory.get("sources", [])
    }
    require(len(external_sources) == int(source_inventory.get("source_count", -1)),
            "source hash inventory has duplicate or missing entries")
    local_artifacts = []
    for path in sorted(STUDY.rglob("*")):
        if not path.is_file() or path == MANIFEST or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        checked(path)
        local_artifacts.append({
            "path": str(path.relative_to(STUDY)),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        })
    manifest = {
        "status": "PASS",
        "study": STUDY.name,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "decision": result["predeclared_gates"]["decision"],
        "evaluation_races": EXPECTED_RACES,
        "evaluation_dates": EXPECTED_DATES,
        "root_metrics_review": root_review,
        "document_correction": result.get("document_correction"),
        "report_artifacts": {
            path.relative_to(STUDY).as_posix(): {"sha256": sha256(checked(path)), "bytes": path.stat().st_size}
            for path in (REPORT_JSON, PAIRED_RACE_CSV, CHANGED_SELECTIONS_CSV)
        },
        "local_artifacts": local_artifacts,
        "external_sources": dict(sorted(external_sources.items())),
        "runtime_dependencies": {
            "python": platform.python_version(), "numpy": np.__version__,
            "pandas": pd.__version__, "scipy": scipy.__version__,
        },
        "manifest_self_hash_excluded": True,
    }
    content = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if replace_existing:
        temporary = MANIFEST.with_name(".ARTIFACT_MANIFEST.json.document_fix.tmp")
        require(not temporary.exists() and not temporary.is_symlink(),
                "temporary manifest path already exists")
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(content)
        temporary.replace(MANIFEST)
    else:
        write_once(MANIFEST, content)
    print(json.dumps({"status": "PASS", "manifest": str(MANIFEST.relative_to(ROOT)),
                      "root_metrics_review_sha256": root_review["sha256"],
                      "artifacts": len(local_artifacts)}, ensure_ascii=False, indent=2))


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"report", "manifest", "refresh-documents"}:
        raise SystemExit("usage: riding_conditions_report.py {report|manifest|refresh-documents}")
    if sys.argv[1] == "report":
        run_report()
    elif sys.argv[1] == "refresh-documents":
        run_refresh_documents()
    else:
        run_manifest()


if __name__ == "__main__":
    main()
