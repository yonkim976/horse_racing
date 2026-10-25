#!/usr/bin/env python3
"""Report the frozen seven-input reliability pair candidate against the saved ID model."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import scipy
from scipy.special import expit


ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261014_pair_reliability_v1"
OUT = STUDY / "outputs"
REPORT_DIR = OUT / "report"
PREDICTIONS = OUT / "evaluation_pair_predictions.parquet"
PREDICTION_RECEIPT = OUT / "PREDICTION_RECEIPT.json"
PREDICTION_CODE = STUDY / "pair_reliability_predict.py"
FIT = OUT / "FIT.json"
FIT_RECEIPT = OUT / "FIT_RECEIPT.json"
APPROVAL = OUT / "APPROVAL.json"
PREFLIGHT = OUT / "SOURCE_PREFLIGHT.json"
DESIGN_DRY_RUN = OUT / "DESIGN_DRY_RUN.json"
REPORT_PATH = OUT / "REPORT.json"
REPORT_RECEIPT = OUT / "REPORT_RECEIPT.json"
README = STUDY / "README.md"
MANIFEST = STUDY / "ARTIFACT_MANIFEST.json"

BASE = ROOT / "jeju/research/20261012_pair_jockey_id_v1"
BASE_PREDICTIONS = BASE / "outputs/evaluation_pair_predictions.parquet"
BASE_REPORT = BASE / "outputs/REPORT.json"
BASE_REPORT_RECEIPT = BASE / "outputs/REPORT_RECEIPT.json"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
DIRECT = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
DIRECT_REPORT = DIRECT / "report.py"
BOOTSTRAP = DIRECT / "outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT = DIRECT / "outputs/date_bootstrap_schedule.json"
ODDS_ROWS = ROOT / "jeju/research/20261013_postrace_ev_exploration_v1/race_rows.csv"

EXPECTED_BASE_PREDICTIONS_SHA = "0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6"
EXPECTED_FEATURES_SHA = "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f"
EXPECTED_BOOTSTRAP_SHA = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
EXPECTED_BOOTSTRAP_RECEIPT_SHA = "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e"
EXPECTED_DIRECT_REPORT_SHA = "ad07cf566020edbb6f9e924b3fc0211c4ad917391ab9ba434bf34cba786bdc1f"
EXPECTED_ODDS_ROWS_SHA = "4fc2e924dcf4f987c22962977d42dd83a786bebc2f70606bc565bd97d2869198"

PAIR_KEYS = ["race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j"]
RACE_KEYS = ["race_id", "race_date", "evaluation_year", "distance_m"]
NEW_PROBABILITY_COLUMNS = [
    "reliability_candidate_eta",
    "reliability_candidate_raw_probability",
    "reliability_candidate_calibrated_probability",
    "selected_reliability_candidate",
]
SELECTOR_COLUMNS = (
    "selected_jockey_id_candidate",
    "selected_jockey_basic_candidate",
    "selected_raw_top2",
    "selected_reliability_candidate",
)
FIXED_HISTORY_BINS = ((0, 0, "0"), (1, 2, "1-2"), (3, 5, "3-5"), (6, 10, "6-10"), (11, math.inf, "11+"))
ODDS_BINS = ((1.0, 2.0, "[1,2)"), (2.0, 3.0, "[2,3)"), (3.0, 5.0, "[3,5)"),
             (5.0, 10.0, "[5,10)"), (10.0, math.inf, "[10,inf)"))
EXPECTED_YEAR_RACES = {2024: 637, 2025: 654, 2026: 488}
EXPECTED_BASE_COLUMNS = 54
EXPECTED_CANDIDATE_COLUMNS = 58
EXPECTED_RACES = 1_779
EXPECTED_PAIR_ROWS = 76_848
EXPECTED_RUNNERS = 17_412
EXPECTED_DATES = 269


class ReportError(RuntimeError):
    pass


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
    require(not path.is_symlink(), f"input symlink is not allowed: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"input outside workspace: {path}")
    return resolved


def checked_output(path: Path) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite report artifact: {path}")


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    checked_output(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, checked(path))
    require(spec is not None and spec.loader is not None, f"cannot load frozen report helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def json_file(path: Path) -> dict[str, Any]:
    value = json.loads(checked(path).read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def validate_lineage() -> tuple[Any, list[str], np.ndarray, dict[str, Any], dict[str, str]]:
    approval = json_file(APPROVAL)
    fit = json_file(FIT)
    fit_receipt = json_file(FIT_RECEIPT)
    preflight = json_file(PREFLIGHT)
    dry_run = json_file(DESIGN_DRY_RUN)
    prediction_receipt = json_file(PREDICTION_RECEIPT)

    require(approval.get("approved") is True and approval.get("approved_by") == "root",
            "root fit approval is missing")
    require(fit.get("status") == "PASS" and fit_receipt.get("status") == "PASS",
            "approved fold fit is not PASS")
    require(fit_receipt.get("candidate_fit_sha256") == sha256(FIT), "fit receipt hash mismatch")
    require(fit.get("approval_sha256") == sha256(APPROVAL), "fit approval lineage mismatch")
    require(preflight.get("status") == "PASS" and dry_run.get("status") == "PASS",
            "source/design preflight is not PASS")
    require(dry_run.get("optimizer_runs") == 0, "design dry-run reports optimizer execution")
    require(prediction_receipt.get("status") == "PASS", "candidate prediction receipt is not PASS")
    require(prediction_receipt.get("study") == STUDY.name
            and prediction_receipt.get("scope") ==
            "fixed evaluation pair prediction only; no evaluation performance metrics",
            "candidate prediction receipt study/scope changed")
    require(prediction_receipt.get("pair_predictions_sha256") == sha256(PREDICTIONS),
            "candidate prediction artifact hash mismatch")
    require(prediction_receipt.get("fit_sha256") == sha256(FIT), "prediction receipt fit lineage mismatch")
    require(prediction_receipt.get("fit_receipt_sha256") == sha256(FIT_RECEIPT),
            "prediction receipt fit-receipt lineage mismatch")
    require(prediction_receipt.get("approval_sha256") == sha256(APPROVAL),
            "prediction receipt approval lineage mismatch")
    require(prediction_receipt.get("source_preflight_sha256") == sha256(PREFLIGHT),
            "prediction receipt source-preflight lineage mismatch")
    require(prediction_receipt.get("design_dry_run_sha256") == sha256(DESIGN_DRY_RUN),
            "prediction receipt design dry-run lineage mismatch")
    require(prediction_receipt.get("prediction_code_sha256") == sha256(checked(PREDICTION_CODE)),
            "prediction receipt code hash mismatch")
    require(int(prediction_receipt.get("prediction_rows", -1)) == EXPECTED_PAIR_ROWS,
            "candidate prediction receipt row count changed")
    require(int(prediction_receipt.get("prediction_races", -1)) == EXPECTED_RACES,
            "candidate prediction receipt race count changed")
    require(int(prediction_receipt.get("evaluation_dates", -1)) == EXPECTED_DATES,
            "candidate prediction receipt date count changed")

    require(sha256(BASE_PREDICTIONS) == EXPECTED_BASE_PREDICTIONS_SHA,
            "frozen selected-ID baseline pair file changed")
    base_receipt = json_file(BASE_REPORT_RECEIPT)
    require(base_receipt.get("status") == "PASS" and base_receipt.get("report_sha256") == sha256(BASE_REPORT),
            "saved baseline report receipt does not match its report")
    require(sha256(FEATURES) == EXPECTED_FEATURES_SHA, "frozen source feature file changed")
    require(sha256(BOOTSTRAP) == EXPECTED_BOOTSTRAP_SHA, "frozen paired date schedule changed")
    require(sha256(BOOTSTRAP_RECEIPT) == EXPECTED_BOOTSTRAP_RECEIPT_SHA,
            "frozen paired date schedule receipt changed")
    require(sha256(DIRECT_REPORT) == EXPECTED_DIRECT_REPORT_SHA,
            "frozen date-bootstrap helper changed")
    require(sha256(ODDS_ROWS) == EXPECTED_ODDS_ROWS_SHA, "verified fixed-pair odds file changed")

    for relative, expected in preflight.get("source_hashes", {}).items():
        require(sha256(checked(ROOT / relative)) == expected, f"preflight source hash changed: {relative}")

    helper = import_module("frozen_reliability_date_report_helper", DIRECT_REPORT)
    dates, schedule, schedule_receipt = helper.load_bootstrap()
    require(len(dates) == EXPECTED_DATES and schedule.shape == (2_000, EXPECTED_DATES),
            "paired date schedule dimensions changed")
    require(schedule.dtype == np.int32, "paired date schedule dtype changed")
    expected_outputs = [REPORT_PATH, REPORT_RECEIPT, README, MANIFEST, REPORT_DIR]
    for path in expected_outputs:
        require(not path.is_symlink() and not path.exists(), f"report output already exists: {path}")

    locked = {
        "candidate_predictions": sha256(PREDICTIONS),
        "prediction_receipt": sha256(PREDICTION_RECEIPT),
        "prediction_code": sha256(PREDICTION_CODE),
        "fit": sha256(FIT),
        "fit_receipt": sha256(FIT_RECEIPT),
        "approval": sha256(APPROVAL),
        "source_preflight": sha256(PREFLIGHT),
        "design_dry_run": sha256(DESIGN_DRY_RUN),
        "baseline_predictions": EXPECTED_BASE_PREDICTIONS_SHA,
        "baseline_report": sha256(BASE_REPORT),
        "baseline_report_receipt": sha256(BASE_REPORT_RECEIPT),
        "runner_features": EXPECTED_FEATURES_SHA,
        "bootstrap_schedule": EXPECTED_BOOTSTRAP_SHA,
        "bootstrap_receipt": EXPECTED_BOOTSTRAP_RECEIPT_SHA,
        "bootstrap_helper": EXPECTED_DIRECT_REPORT_SHA,
        "fixed_pair_odds_rows": EXPECTED_ODDS_ROWS_SHA,
    }
    return helper, dates, schedule, schedule_receipt, locked


def recheck_input_locks(locked_hashes: dict[str, str]) -> None:
    paths = {
        "candidate_predictions": PREDICTIONS,
        "prediction_receipt": PREDICTION_RECEIPT,
        "prediction_code": PREDICTION_CODE,
        "fit": FIT,
        "fit_receipt": FIT_RECEIPT,
        "approval": APPROVAL,
        "source_preflight": PREFLIGHT,
        "design_dry_run": DESIGN_DRY_RUN,
        "baseline_predictions": BASE_PREDICTIONS,
        "baseline_report": BASE_REPORT,
        "baseline_report_receipt": BASE_REPORT_RECEIPT,
        "runner_features": FEATURES,
        "bootstrap_schedule": BOOTSTRAP,
        "bootstrap_receipt": BOOTSTRAP_RECEIPT,
        "bootstrap_helper": DIRECT_REPORT,
        "fixed_pair_odds_rows": ODDS_ROWS,
    }
    for name, path in paths.items():
        require(sha256(checked(path)) == locked_hashes[name], f"input changed during report calculation: {name}")


def normalize_pair_frame(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    result = frame.copy()
    require(set(PAIR_KEYS).issubset(result.columns), f"{label} pair keys are incomplete")
    result["race_id"] = result["race_id"].astype(str)
    result["race_date"] = pd.to_datetime(result["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    require(result["race_date"].notna().all(), f"{label} contains invalid dates")
    for column in ("evaluation_year", "distance_m", "horse_i", "horse_j"):
        values = pd.to_numeric(result[column], errors="raise")
        require(np.isfinite(values.to_numpy(dtype=float)).all(), f"{label} has non-finite {column}")
        require(np.equal(values.to_numpy(dtype=float), np.floor(values.to_numpy(dtype=float))).all(),
                f"{label} has non-integer {column}")
        result[column] = values.astype(int)
    result["y_pair"] = pd.to_numeric(result["y_pair"], errors="raise").astype(int)
    require(result["y_pair"].isin((0, 1)).all(), f"{label} labels are not binary")
    return result


def validate_predictions(helper: Any) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    baseline_raw = pd.read_parquet(checked(BASE_PREDICTIONS))
    candidate_raw = pd.read_parquet(checked(PREDICTIONS))
    baseline_column_count = len(baseline_raw.columns)
    require(baseline_column_count == EXPECTED_BASE_COLUMNS,
            "frozen baseline prediction schema no longer has the pinned 54 columns")
    require(len(candidate_raw.columns) == EXPECTED_CANDIDATE_COLUMNS,
            "candidate prediction schema no longer has the pinned 58 columns")
    require(list(candidate_raw.columns[:baseline_column_count]) == list(baseline_raw.columns),
            "candidate did not preserve all baseline columns in order")
    require(list(candidate_raw.columns[baseline_column_count:]) == NEW_PROBABILITY_COLUMNS,
            "candidate appended prediction schema differs from the predeclared four columns")
    prediction_receipt = json_file(PREDICTION_RECEIPT)
    require(prediction_receipt.get("output_columns") == list(candidate_raw.columns),
            "prediction receipt column schema does not match the parquet")
    require(list(prediction_receipt.get("output_columns", []))[baseline_column_count:] == NEW_PROBABILITY_COLUMNS,
            "prediction receipt appended-column declaration changed")
    require(prediction_receipt.get("candidate_probability_column") ==
            "reliability_candidate_calibrated_probability"
            and prediction_receipt.get("candidate_raw_probability_column") ==
            "reliability_candidate_raw_probability"
            and prediction_receipt.get("candidate_eta_column") == "reliability_candidate_eta"
            and prediction_receipt.get("candidate_selector_column") == "selected_reliability_candidate",
            "prediction receipt candidate column declaration changed")
    require(prediction_receipt.get("fixed_id_probability_column") ==
            "jockey_id_candidate_calibrated_probability"
            and prediction_receipt.get("fixed_id_selector_column") == "selected_jockey_id_candidate",
            "prediction receipt fixed comparator declaration changed")
    require(prediction_receipt.get("secondary_selector_columns") == [
        "selected_raw_top2", "selected_jockey_basic_candidate",
    ], "prediction receipt secondary selector declaration changed")
    require(prediction_receipt.get("frozen_input_columns_preserved") is True,
            "prediction receipt does not attest to preserved baseline columns")
    require(prediction_receipt.get("evaluation_labels_used_for_prediction") is False,
            "evaluation labels were used to generate predictions")
    require(prediction_receipt.get("performance_metrics_computed") is False,
            "prediction stage already computed evaluation performance metrics")
    require(prediction_receipt.get("selected_candidate_per_race") == EXPECTED_RACES,
            "prediction receipt candidate selector race count changed")
    pd.testing.assert_frame_equal(
        candidate_raw.loc[:, baseline_raw.columns].reset_index(drop=True),
        baseline_raw.reset_index(drop=True), check_exact=True, check_dtype=True,
        check_like=False, obj="candidate-preserved baseline columns",
    )
    baseline = normalize_pair_frame(baseline_raw, "frozen baseline")
    candidate = normalize_pair_frame(candidate_raw, "candidate")

    require(len(candidate) == EXPECTED_PAIR_ROWS and candidate["race_id"].nunique() == EXPECTED_RACES,
            "candidate evaluation cohort size changed")
    require(not candidate.duplicated(PAIR_KEYS).any(), "duplicate evaluation pair key")
    require((candidate.groupby("race_id", sort=False)["y_pair"].sum() == 3).all(),
            "pair-label arithmetic changed")
    require(candidate.groupby("race_id")["race_date"].nunique().eq(1).all(), "race spans multiple dates")
    require(candidate.groupby("race_id")["evaluation_year"].nunique().eq(1).all(), "race spans multiple years")
    require(candidate.groupby("race_id")["distance_m"].nunique().eq(1).all(), "race spans multiple distances")
    year_races = candidate.groupby("evaluation_year", sort=True)["race_id"].nunique().to_dict()
    require(year_races == EXPECTED_YEAR_RACES,
            "evaluation year race counts changed")
    for column in SELECTOR_COLUMNS:
        values = pd.to_numeric(candidate[column], errors="raise")
        require(values.isin((0, 1)).all(), f"selector is not binary: {column}")
        candidate[column] = values.astype(int)

    numeric_columns = [
        "jockey_id_candidate_calibrated_probability",
        "candidate_calibrated_probability",
        "reliability_candidate_eta",
        "reliability_candidate_raw_probability",
        "reliability_candidate_calibrated_probability",
    ]
    for column in numeric_columns:
        values = pd.to_numeric(candidate[column], errors="raise").to_numpy(dtype=float)
        require(np.isfinite(values).all(), f"non-finite prediction value: {column}")
        candidate[column] = values
    for column in numeric_columns[:2] + numeric_columns[3:]:
        require(candidate[column].between(0.0, 1.0).all(), f"probability outside [0,1]: {column}")
    raw_from_eta = expit(candidate["reliability_candidate_eta"].to_numpy(dtype=float))
    require(np.allclose(raw_from_eta, candidate["reliability_candidate_raw_probability"].to_numpy(dtype=float),
                        rtol=0.0, atol=1e-12), "candidate raw probability does not match eta")

    selected_hits: dict[str, Any] = {}
    for selector, expected_hits in (
        ("selected_jockey_id_candidate", 438),
        ("selected_jockey_basic_candidate", 429),
        ("selected_raw_top2", 429),
        ("selected_reliability_candidate", None),
    ):
        selected = helper.one_selected_per_race(candidate, selector)
        hits = int(selected["y_pair"].sum())
        if expected_hits is not None:
            require(hits == expected_hits, f"frozen selected comparator changed: {selector}")
        selected_hits[selector] = {"races": len(selected), "hits": hits, "hit_rate": float(selected["y_pair"].mean())}

    baseline_report = json_file(BASE_REPORT)
    baseline_hits = baseline_report.get("pair_hit_rate_by_policy", {}).get("jockey_id_candidate", {}).get("hits")
    require(baseline_hits == 438, "saved baseline report no longer records 438 selected-ID hits")
    return baseline, candidate, {
        "selected_hits": selected_hits, "baseline_report": baseline_report,
        "prediction_schema": {
            "preserved_baseline_columns": baseline_column_count,
            "appended_candidate_columns": list(NEW_PROBABILITY_COLUMNS),
            "candidate_total_columns": len(candidate_raw.columns),
        },
    }


def runner_support_for_selected_pairs(selected: pd.DataFrame, label: str) -> pd.DataFrame:
    feature_columns = [
        "api_record_id", "race_id", "race_date", "year", "distance_m", "horse_number",
        "observed_starts", "same_valid_times",
    ]
    features = pd.read_parquet(checked(FEATURES), columns=feature_columns)
    features["race_id"] = features["race_id"].astype(str)
    features["race_date"] = pd.to_datetime(features["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    require(features["race_date"].notna().all(), "runner feature source has invalid dates")
    features["api_record_id"] = features["api_record_id"].astype(str)
    for column in ("year", "distance_m", "horse_number"):
        features[column] = pd.to_numeric(features[column], errors="raise").astype(int)
    for column in ("observed_starts", "same_valid_times"):
        values = pd.to_numeric(features[column], errors="raise")
        require(np.isfinite(values.to_numpy(dtype=float)).all() and values.ge(0).all(),
                f"invalid runner support count: {column}")
        require(np.equal(values.to_numpy(dtype=float), np.floor(values.to_numpy(dtype=float))).all(),
                f"runner support count is not integral: {column}")
        features[column] = values.astype(int)

    race_ids = set(selected["race_id"].astype(str))
    features = features.loc[features["race_id"].isin(race_ids)].copy()
    require(len(features) == EXPECTED_RUNNERS, "evaluation feature runner count changed")
    require(not features["api_record_id"].duplicated().any(), "duplicate API record ID in runner feature source")
    require(not features.duplicated(["race_id", "horse_number"]).any(), "duplicate race/horse-number feature key")
    require(features.groupby("race_id").size().ge(4).all(), "runner feature race roster has fewer than four horses")
    pairs = selected[[*RACE_KEYS, "horse_i", "horse_j"]].copy()
    pairs["race_id"] = pairs["race_id"].astype(str)
    roster_keys = features[["race_id", "horse_number", "api_record_id"]]
    profile_columns = ["api_record_id", "horse_number", "race_id", "race_date", "year", "distance_m",
                       "observed_starts", "same_valid_times"]

    def attach_endpoint(number_column: str, side: str) -> pd.DataFrame:
        mapped = pairs[[*RACE_KEYS, number_column]].merge(
            roster_keys, left_on=["race_id", number_column], right_on=["race_id", "horse_number"],
            how="left", validate="many_to_one",
        )
        require(mapped["api_record_id"].notna().all(), f"{label} pair endpoint lacks API record ID")
        profile = features[profile_columns].rename(columns={
            "api_record_id": f"profile_api_record_id_{side}",
            "horse_number": f"profile_horse_number_{side}",
            "race_id": f"profile_race_id_{side}",
            "race_date": f"profile_race_date_{side}",
            "year": f"profile_year_{side}",
            "distance_m": f"profile_distance_m_{side}",
            "observed_starts": f"{side}_observed_starts",
            "same_valid_times": f"{side}_same_valid_times",
        })
        mapped = mapped.rename(columns={"api_record_id": f"api_record_id_{side}"})
        joined = mapped.merge(
            profile,
            left_on=[f"api_record_id_{side}", number_column],
            right_on=[f"profile_api_record_id_{side}", f"profile_horse_number_{side}"],
            how="left", validate="many_to_one",
        )
        require(joined[f"profile_race_id_{side}"].eq(joined["race_id"]).all(),
                f"{label} pair endpoint failed API-ID/horse-number join")
        require(joined[f"profile_race_date_{side}"].eq(joined["race_date"]).all(),
                f"{label} pair endpoint date mismatch")
        require(joined[f"profile_year_{side}"].eq(joined["evaluation_year"]).all(),
                f"{label} pair endpoint year mismatch")
        require(joined[f"profile_distance_m_{side}"].eq(joined["distance_m"]).all(),
                f"{label} pair endpoint distance mismatch")
        require(joined[f"{side}_observed_starts"].notna().all()
                and joined[f"{side}_same_valid_times"].notna().all(),
                f"{label} pair endpoint support is missing")
        return joined[["race_id", f"{side}_observed_starts", f"{side}_same_valid_times"]]

    left = attach_endpoint("horse_i", "i")
    right = attach_endpoint("horse_j", "j")
    joined = left.merge(right, on="race_id", how="inner", validate="one_to_one")
    result = joined[["race_id"]].copy()
    result[f"{label}_min_observed_starts"] = np.minimum(
        joined["i_observed_starts"].to_numpy(dtype=int), joined["j_observed_starts"].to_numpy(dtype=int)
    )
    result[f"{label}_min_same_valid_times"] = np.minimum(
        joined["i_same_valid_times"].to_numpy(dtype=int), joined["j_same_valid_times"].to_numpy(dtype=int)
    )
    result[f"{label}_i_observed_starts"] = joined["i_observed_starts"].astype(int).to_numpy()
    result[f"{label}_j_observed_starts"] = joined["j_observed_starts"].astype(int).to_numpy()
    result[f"{label}_i_same_valid_times"] = joined["i_same_valid_times"].astype(int).to_numpy()
    result[f"{label}_j_same_valid_times"] = joined["j_same_valid_times"].astype(int).to_numpy()
    require(not result["race_id"].duplicated().any(), f"{label} support mapping repeats races")
    return result


def loss_values(probability: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    p = np.clip(np.asarray(probability, dtype=float), 1e-15, 1.0 - 1e-15)
    y = np.asarray(labels, dtype=float)
    return (p - y) ** 2, -(y * np.log(p) + (1.0 - y) * np.log1p(-p))


def build_race_metrics(helper: Any, candidate: pd.DataFrame, dates: list[str]) -> pd.DataFrame:
    selected_base = helper.one_selected_per_race(candidate, "selected_jockey_id_candidate")
    selected_candidate = helper.one_selected_per_race(candidate, "selected_reliability_candidate")
    fixed = selected_base[[
        *RACE_KEYS, "horse_i", "horse_j", "y_pair", "jockey_id_candidate_calibrated_probability",
        "reliability_candidate_eta", "reliability_candidate_raw_probability",
        "reliability_candidate_calibrated_probability",
    ]].copy().rename(columns={
        "horse_i": "baseline_fixed_horse_i", "horse_j": "baseline_fixed_horse_j", "y_pair": "baseline_fixed_hit",
        "jockey_id_candidate_calibrated_probability": "baseline_fixed_probability",
        "reliability_candidate_eta": "candidate_fixed_eta",
        "reliability_candidate_raw_probability": "candidate_fixed_raw_probability",
        "reliability_candidate_calibrated_probability": "candidate_fixed_calibrated_probability",
    })
    fixed["candidate_fixed_hit"] = fixed["baseline_fixed_hit"].astype(int)
    selected = selected_candidate[[
        "race_id", "horse_i", "horse_j", "y_pair", "reliability_candidate_eta",
        "reliability_candidate_raw_probability", "reliability_candidate_calibrated_probability",
    ]].copy().rename(columns={
        "horse_i": "candidate_selected_horse_i", "horse_j": "candidate_selected_horse_j",
        "y_pair": "candidate_selected_hit", "reliability_candidate_eta": "candidate_selected_eta",
        "reliability_candidate_raw_probability": "candidate_selected_raw_probability",
        "reliability_candidate_calibrated_probability": "candidate_selected_calibrated_probability",
    })
    result = fixed.merge(selected, on="race_id", how="inner", validate="one_to_one")
    require(len(result) == EXPECTED_RACES, "fixed and re-ranked selected pairs do not align one-to-one")

    for policy, selector in (
        ("raw_top2", "selected_raw_top2"),
        ("jockey_basic", "selected_jockey_basic_candidate"),
    ):
        rows = helper.one_selected_per_race(candidate, selector)[["race_id", "horse_i", "horse_j", "y_pair"]]
        rows = rows.rename(columns={
            "horse_i": f"{policy}_horse_i", "horse_j": f"{policy}_horse_j", "y_pair": f"{policy}_hit",
        })
        result = result.merge(rows, on="race_id", how="inner", validate="one_to_one")

    result["selection_changed"] = (
        result["baseline_fixed_horse_i"].ne(result["candidate_selected_horse_i"])
        | result["baseline_fixed_horse_j"].ne(result["candidate_selected_horse_j"])
    )
    result["candidate_minus_baseline_selected_hit"] = (
        result["candidate_selected_hit"].astype(float) - result["baseline_fixed_hit"].astype(float)
    )
    result["candidate_minus_raw_top2_hit"] = (
        result["candidate_selected_hit"].astype(float) - result["raw_top2_hit"].astype(float)
    )
    result["candidate_minus_jockey_basic_hit"] = (
        result["candidate_selected_hit"].astype(float) - result["jockey_basic_hit"].astype(float)
    )

    fixed_loss_map = {
        "baseline_fixed": "baseline_fixed_probability",
        "candidate_fixed_raw": "candidate_fixed_raw_probability",
        "candidate_fixed_calibrated": "candidate_fixed_calibrated_probability",
    }
    for prefix, probability_column in fixed_loss_map.items():
        brier, logloss = loss_values(result[probability_column].to_numpy(), result["baseline_fixed_hit"].to_numpy())
        result[f"{prefix}_brier"] = brier
        result[f"{prefix}_log_loss"] = logloss
    result["candidate_fixed_raw_minus_baseline_brier"] = (
        result["candidate_fixed_raw_brier"] - result["baseline_fixed_brier"]
    )
    result["candidate_fixed_raw_minus_baseline_log_loss"] = (
        result["candidate_fixed_raw_log_loss"] - result["baseline_fixed_log_loss"]
    )
    result["candidate_fixed_calibrated_minus_baseline_brier"] = (
        result["candidate_fixed_calibrated_brier"] - result["baseline_fixed_brier"]
    )
    result["candidate_fixed_calibrated_minus_baseline_log_loss"] = (
        result["candidate_fixed_calibrated_log_loss"] - result["baseline_fixed_log_loss"]
    )

    pair_metrics = candidate[["race_id", "y_pair", "jockey_id_candidate_calibrated_probability",
                              "reliability_candidate_raw_probability",
                              "reliability_candidate_calibrated_probability"]].copy()
    all_pair_names = {
        "baseline_all_pair": "jockey_id_candidate_calibrated_probability",
        "candidate_raw_all_pair": "reliability_candidate_raw_probability",
        "candidate_calibrated_all_pair": "reliability_candidate_calibrated_probability",
    }
    for prefix, column in all_pair_names.items():
        brier, logloss = loss_values(pair_metrics[column].to_numpy(), pair_metrics["y_pair"].to_numpy())
        pair_metrics[f"{prefix}_brier_pair"] = brier
        pair_metrics[f"{prefix}_log_loss_pair"] = logloss
    aggregated = pair_metrics.groupby("race_id", sort=False)[[
        f"{prefix}_brier_pair" for prefix in all_pair_names
    ] + [f"{prefix}_log_loss_pair" for prefix in all_pair_names]].mean().reset_index()
    aggregated = aggregated.rename(columns={
        f"{prefix}_brier_pair": f"{prefix}_brier" for prefix in all_pair_names
    } | {
        f"{prefix}_log_loss_pair": f"{prefix}_log_loss" for prefix in all_pair_names
    })
    result = result.merge(aggregated, on="race_id", how="inner", validate="one_to_one")
    for measure in ("brier", "log_loss"):
        result[f"candidate_raw_all_pair_minus_baseline_{measure}"] = (
            result[f"candidate_raw_all_pair_{measure}"] - result[f"baseline_all_pair_{measure}"]
        )
        result[f"candidate_calibrated_all_pair_minus_baseline_{measure}"] = (
            result[f"candidate_calibrated_all_pair_{measure}"] - result[f"baseline_all_pair_{measure}"]
        )

    base_support = runner_support_for_selected_pairs(selected_base, "baseline_fixed")
    candidate_support = runner_support_for_selected_pairs(selected_candidate, "candidate_selected")
    result = result.merge(base_support, on="race_id", how="inner", validate="one_to_one")
    result = result.merge(candidate_support, on="race_id", how="inner", validate="one_to_one")
    result["observed_career_subgroup"] = result["baseline_fixed_min_observed_starts"].map(history_bin)
    result["same_valid_time_subgroup"] = result["baseline_fixed_min_same_valid_times"].map(history_bin)
    result = helper.add_date_index(result, dates)
    require(len(result) == EXPECTED_RACES and result["race_id"].is_unique,
            "race-level report table is not one row per evaluation race")
    return result


def history_bin(value: int) -> str:
    number = int(value)
    for lower, upper, label in FIXED_HISTORY_BINS:
        if lower <= number <= upper:
            return label
    raise ReportError(f"history support count has no predeclared bin: {number}")


def date_ci(frame: pd.DataFrame, value_column: str, dates: list[str], schedule: np.ndarray) -> dict[str, Any]:
    if frame.empty:
        return {"estimate": None, "ci_low": None, "ci_high": None, "valid_draws": 0, "undefined_draws": int(schedule.shape[0])}
    sums = np.zeros(len(dates), dtype=float)
    counts = np.zeros(len(dates), dtype=float)
    for index, row in frame.groupby("_date_index")[value_column].agg(["sum", "count"]).iterrows():
        sums[int(index)] = float(row["sum"])
        counts[int(index)] = float(row["count"])
    denominator = counts[schedule].sum(axis=1)
    numerator = sums[schedule].sum(axis=1)
    valid = denominator > 0.0
    replicates = numerator[valid] / denominator[valid]
    return {
        "estimate": float(frame[value_column].mean()),
        "ci_low": float(np.quantile(replicates, 0.025)) if len(replicates) else None,
        "ci_high": float(np.quantile(replicates, 0.975)) if len(replicates) else None,
        "valid_draws": int(valid.sum()),
        "undefined_draws": int((~valid).sum()),
    }


def groups_for_report(races: pd.DataFrame) -> list[tuple[str, str, pd.DataFrame]]:
    groups: list[tuple[str, str, pd.DataFrame]] = [("overall", "all", races)]
    for year in (2024, 2025, 2026):
        groups.append(("year", str(year), races.loc[races["evaluation_year"].eq(year)]))
    for distance in sorted(races["distance_m"].unique().tolist()):
        groups.append(("distance_m", str(int(distance)), races.loc[races["distance_m"].eq(distance)]))
    for column, group_name in (
        ("observed_career_subgroup", "observed_career_min_pair"),
        ("same_valid_time_subgroup", "same_distance_valid_times_min_pair"),
    ):
        for _, _, label in FIXED_HISTORY_BINS:
            groups.append((group_name, label, races.loc[races[column].eq(label)]))
    return groups


def row_ci(group_type: str, group: str, metric: str, frame: pd.DataFrame,
           value_column: str, dates: list[str], schedule: np.ndarray,
           comparison: str) -> dict[str, Any]:
    ci = date_ci(frame, value_column, dates, schedule)
    return {
        "group_type": group_type, "group": group, "comparison": comparison, "metric": metric,
        "races": int(len(frame)), "dates": int(frame["race_date"].nunique()) if len(frame) else 0,
        **ci,
    }


def make_summary_tables(races: pd.DataFrame, dates: list[str], schedule: np.ndarray) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    primary_scopes = [(t, g, f) for t, g, f in groups_for_report(races) if t in ("overall", "year", "distance_m")]
    support_scopes = [(t, g, f) for t, g, f in groups_for_report(races)
                      if t in ("observed_career_min_pair", "same_distance_valid_times_min_pair")]
    summary_rows: list[dict[str, Any]] = []
    subgroup_rows: list[dict[str, Any]] = []
    ci_rows: list[dict[str, Any]] = []

    comparisons = (
        ("reliability_selected_vs_jockey_id", "hit_rate_difference", "candidate_minus_baseline_selected_hit"),
        ("reliability_selected_vs_raw_top2", "hit_rate_difference", "candidate_minus_raw_top2_hit"),
        ("reliability_selected_vs_jockey_basic", "hit_rate_difference", "candidate_minus_jockey_basic_hit"),
        ("candidate_fixed_calibrated_vs_baseline_fixed", "brier_difference", "candidate_fixed_calibrated_minus_baseline_brier"),
        ("candidate_fixed_calibrated_vs_baseline_fixed", "log_loss_difference", "candidate_fixed_calibrated_minus_baseline_log_loss"),
        ("candidate_fixed_raw_vs_baseline_fixed", "brier_difference", "candidate_fixed_raw_minus_baseline_brier"),
        ("candidate_fixed_raw_vs_baseline_fixed", "log_loss_difference", "candidate_fixed_raw_minus_baseline_log_loss"),
        ("candidate_all_pair_calibrated_vs_baseline", "brier_difference", "candidate_calibrated_all_pair_minus_baseline_brier"),
        ("candidate_all_pair_calibrated_vs_baseline", "log_loss_difference", "candidate_calibrated_all_pair_minus_baseline_log_loss"),
        ("candidate_all_pair_raw_vs_baseline", "brier_difference", "candidate_raw_all_pair_minus_baseline_brier"),
        ("candidate_all_pair_raw_vs_baseline", "log_loss_difference", "candidate_raw_all_pair_minus_baseline_log_loss"),
    )
    for group_type, group, frame in primary_scopes + support_scopes:
        record: dict[str, Any] = {
            "group_type": group_type, "group": group, "races": int(len(frame)),
            "dates": int(frame["race_date"].nunique()) if len(frame) else 0,
        }
        if frame.empty:
            numeric_fields = [
                "baseline_selected_hits", "candidate_selected_hits", "baseline_selected_hit_rate",
                "candidate_selected_hit_rate", "candidate_minus_baseline_hit_rate",
                "selections_changed", "gains", "losses", "ties_on_changed_selections",
                "baseline_fixed_brier", "candidate_fixed_calibrated_brier", "fixed_brier_difference",
                "baseline_fixed_log_loss", "candidate_fixed_calibrated_log_loss", "fixed_log_loss_difference",
                "baseline_all_pair_brier", "candidate_all_pair_calibrated_brier", "all_pair_brier_difference",
                "baseline_all_pair_log_loss", "candidate_all_pair_calibrated_log_loss", "all_pair_log_loss_difference",
            ]
            record.update({column: None for column in numeric_fields})
        else:
            record.update({
                "baseline_selected_hits": int(frame["baseline_fixed_hit"].sum()),
                "candidate_selected_hits": int(frame["candidate_selected_hit"].sum()),
                "baseline_selected_hit_rate": float(frame["baseline_fixed_hit"].mean()),
                "candidate_selected_hit_rate": float(frame["candidate_selected_hit"].mean()),
                "candidate_minus_baseline_hit_rate": float(frame["candidate_minus_baseline_selected_hit"].mean()),
                "selections_changed": int(frame["selection_changed"].sum()),
                "gains": int(((frame["candidate_minus_baseline_selected_hit"] == 1.0) & frame["selection_changed"]).sum()),
                "losses": int(((frame["candidate_minus_baseline_selected_hit"] == -1.0) & frame["selection_changed"]).sum()),
                "ties_on_changed_selections": int(((frame["candidate_minus_baseline_selected_hit"] == 0.0) & frame["selection_changed"]).sum()),
                "baseline_fixed_brier": float(frame["baseline_fixed_brier"].mean()),
                "candidate_fixed_calibrated_brier": float(frame["candidate_fixed_calibrated_brier"].mean()),
                "fixed_brier_difference": float(frame["candidate_fixed_calibrated_minus_baseline_brier"].mean()),
                "baseline_fixed_log_loss": float(frame["baseline_fixed_log_loss"].mean()),
                "candidate_fixed_calibrated_log_loss": float(frame["candidate_fixed_calibrated_log_loss"].mean()),
                "fixed_log_loss_difference": float(frame["candidate_fixed_calibrated_minus_baseline_log_loss"].mean()),
                "baseline_all_pair_brier": float(frame["baseline_all_pair_brier"].mean()),
                "candidate_all_pair_calibrated_brier": float(frame["candidate_calibrated_all_pair_brier"].mean()),
                "all_pair_brier_difference": float(frame["candidate_calibrated_all_pair_minus_baseline_brier"].mean()),
                "baseline_all_pair_log_loss": float(frame["baseline_all_pair_log_loss"].mean()),
                "candidate_all_pair_calibrated_log_loss": float(frame["candidate_calibrated_all_pair_log_loss"].mean()),
                "all_pair_log_loss_difference": float(frame["candidate_calibrated_all_pair_minus_baseline_log_loss"].mean()),
            })
        for comp, metric, column in comparisons:
            ci_rows.append(row_ci(group_type, group, metric, frame, column, dates, schedule, comp))
        if group_type in ("observed_career_min_pair", "same_distance_valid_times_min_pair"):
            subgroup_rows.append(record)
        else:
            summary_rows.append(record)
    summary = pd.DataFrame(summary_rows)
    subgroups = pd.DataFrame(subgroup_rows)
    bootstrap = pd.DataFrame(ci_rows)
    return summary, subgroups, bootstrap


def make_changed_selections(races: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "race_id", "race_date", "evaluation_year", "distance_m",
        "baseline_fixed_horse_i", "baseline_fixed_horse_j", "baseline_fixed_hit",
        "candidate_selected_horse_i", "candidate_selected_horse_j", "candidate_selected_hit",
        "candidate_minus_baseline_selected_hit", "selection_changed",
        "baseline_fixed_min_observed_starts", "candidate_selected_min_observed_starts",
        "baseline_fixed_min_same_valid_times", "candidate_selected_min_same_valid_times",
        "candidate_selected_raw_probability", "candidate_selected_calibrated_probability",
    ]
    changed = races.loc[races["selection_changed"], columns].copy()
    changed["selection_outcome"] = np.select(
        [changed["candidate_minus_baseline_selected_hit"].eq(1.0),
         changed["candidate_minus_baseline_selected_hit"].eq(-1.0)],
        ["gain", "loss"], default="tie",
    )
    return changed.sort_values(["race_date", "race_id"], kind="mergesort").reset_index(drop=True)


def make_odds_calibration(races: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    odds = pd.read_csv(checked(ODDS_ROWS))
    odds = odds.loc[odds["selector"].eq("jockey_id_candidate")].copy()
    require(len(odds) == 1_142 and odds["race_id"].astype(str).nunique() == 1_142,
            "fixed-ID QPL odds source is not the expected 2025-26 1,142 rows")
    odds["race_id"] = odds["race_id"].astype(str)
    fixed = races.loc[races["evaluation_year"].isin((2025, 2026)), [
        "race_id", "baseline_fixed_horse_i", "baseline_fixed_horse_j", "baseline_fixed_hit",
        "baseline_fixed_probability", "candidate_fixed_calibrated_probability",
    ]].copy()
    joined = odds.merge(fixed, on="race_id", how="left", validate="one_to_one")
    require(len(joined) == 1_142 and joined["baseline_fixed_probability"].notna().all(),
            "fixed-ID odds rows do not join to the saved baseline pair cohort")
    joined["expected_pair"] = [
        f"{min(int(a), int(b))}-{max(int(a), int(b))}"
        for a, b in zip(joined["baseline_fixed_horse_i"], joined["baseline_fixed_horse_j"], strict=True)
    ]
    require(joined["pair"].astype(str).eq(joined["expected_pair"]).all(),
            "fixed-pair odds source selected a different pair")
    require(np.allclose(joined["p"].to_numpy(dtype=float), joined["baseline_fixed_probability"].to_numpy(dtype=float),
                        rtol=0.0, atol=1e-12), "fixed-pair odds source baseline probability changed")
    require(pd.to_numeric(joined["hit"], errors="raise").astype(int).eq(joined["baseline_fixed_hit"]).all(),
            "fixed-pair odds source hit label changed")
    joined["final_quote"] = pd.to_numeric(joined["final_quote"], errors="coerce")
    joined["price_valid"] = pd.to_numeric(joined["price_valid"], errors="coerce").fillna(0).astype(int)
    joined["old_p"] = joined["baseline_fixed_probability"].astype(float)
    joined["new_p"] = joined["candidate_fixed_calibrated_probability"].astype(float)
    joined["actual_hit"] = joined["baseline_fixed_hit"].astype(int)
    joined["price_bin"] = None
    valid_quote = joined["price_valid"].eq(1) & np.isfinite(joined["final_quote"]) & joined["final_quote"].gt(0.0)
    for lower, upper, name in ODDS_BINS:
        mask = valid_quote & joined["final_quote"].ge(lower) & joined["final_quote"].lt(upper)
        joined.loc[mask, "price_bin"] = name

    rows: list[dict[str, Any]] = []
    for _, _, name in ODDS_BINS:
        part = joined.loc[joined["price_bin"].eq(name)]
        actual = float(part["actual_hit"].mean()) if len(part) else None
        old_mean = float(part["old_p"].mean()) if len(part) else None
        new_mean = float(part["new_p"].mean()) if len(part) else None
        rows.append({
            "price_bin": name, "races": int(len(part)), "hits": int(part["actual_hit"].sum()),
            "observed_hit_rate": actual, "baseline_fixed_p_mean": old_mean,
            "candidate_calibrated_p_mean": new_mean,
            "baseline_probability_minus_hit_gap": old_mean - actual if len(part) else None,
            "candidate_probability_minus_hit_gap": new_mean - actual if len(part) else None,
        })
    excluded = joined.loc[joined["price_bin"].isna()]
    rows.append({
        "price_bin": "not_in_fixed_price_bins", "races": int(len(excluded)),
        "hits": int(excluded["actual_hit"].sum()),
        "observed_hit_rate": float(excluded["actual_hit"].mean()) if len(excluded) else None,
        "baseline_fixed_p_mean": float(excluded["old_p"].mean()) if len(excluded) else None,
        "candidate_calibrated_p_mean": float(excluded["new_p"].mean()) if len(excluded) else None,
        "baseline_probability_minus_hit_gap": (
            float(excluded["old_p"].mean() - excluded["actual_hit"].mean()) if len(excluded) else None
        ),
        "candidate_probability_minus_hit_gap": (
            float(excluded["new_p"].mean() - excluded["actual_hit"].mean()) if len(excluded) else None
        ),
    })
    require(sum(row["races"] for row in rows) == 1_142, "posthoc price bins do not cover fixed-pair cohort")
    return pd.DataFrame(rows), {
        "fixed_pair_rows": len(joined),
        "valid_price_rows": int(valid_quote.sum()),
        "rows_outside_predeclared_bins": int(len(excluded)),
        "purpose": "posthoc only; no feature, fit, calibration, selector or threshold input",
    }


def metric_value(frame: pd.DataFrame, column: str) -> float:
    require(not frame.empty, f"cannot calculate metric on empty frame: {column}")
    value = float(frame[column].mean())
    require(math.isfinite(value), f"metric is non-finite: {column}")
    return value


def build_report(races: pd.DataFrame, summary: pd.DataFrame, subgroups: pd.DataFrame,
                 bootstrap: pd.DataFrame, odds_info: dict[str, Any],
                 selected_hits: dict[str, Any], schedule_receipt: dict[str, Any],
                 locked_hashes: dict[str, str]) -> dict[str, Any]:
    overall = races
    fixed_brier_delta = metric_value(overall, "candidate_fixed_calibrated_minus_baseline_brier")
    fixed_logloss_delta = metric_value(overall, "candidate_fixed_calibrated_minus_baseline_log_loss")
    all_pair_brier_delta = metric_value(overall, "candidate_calibrated_all_pair_minus_baseline_brier")
    all_pair_logloss_delta = metric_value(overall, "candidate_calibrated_all_pair_minus_baseline_log_loss")
    selection_delta = metric_value(overall, "candidate_minus_baseline_selected_hit")
    fixed_ci = bootstrap.loc[
        bootstrap["group_type"].eq("overall")
        & bootstrap["comparison"].eq("candidate_fixed_calibrated_vs_baseline_fixed")
    ].set_index("metric")
    selection_ci = bootstrap.loc[
        bootstrap["group_type"].eq("overall")
        & bootstrap["comparison"].eq("reliability_selected_vs_jockey_id")
    ].set_index("metric")
    brier_upper = float(fixed_ci.loc["brier_difference", "ci_high"])
    logloss_upper = float(fixed_ci.loc["log_loss_difference", "ci_high"])
    hit_lower = float(selection_ci.loc["hit_rate_difference", "ci_low"])
    probability_gate = bool(
        fixed_brier_delta < 0.0 and fixed_logloss_delta < 0.0 and min(brier_upper, logloss_upper) < 0.0
    )
    selection_confirmed = bool(selection_delta >= 0.0 and hit_lower > 0.0)
    all_pair_brier_worsened = all_pair_brier_delta > 0.0
    all_pair_logloss_worsened = all_pair_logloss_delta > 0.0
    all_pair_guardrail = not (all_pair_brier_worsened or all_pair_logloss_worsened)
    composite = probability_gate and selection_confirmed and all_pair_guardrail
    changed = int(races["selection_changed"].sum())
    changed_gains = int(((races["candidate_minus_baseline_selected_hit"] == 1.0) & races["selection_changed"]).sum())
    changed_losses = int(((races["candidate_minus_baseline_selected_hit"] == -1.0) & races["selection_changed"]).sum())
    changed_ties = int(((races["candidate_minus_baseline_selected_hit"] == 0.0) & races["selection_changed"]).sum())
    return {
        "study": STUDY.name,
        "status": "ARITHMETIC_PASS",
        "improvement_status": "PASS" if composite else "FAIL",
        "operational_recommendation": False,
        "evaluation_scope": "repeated historical development data 2024-01-05 through 2026-09-19; 2026 is partial; not an independent future holdout",
        "cohort": {
            "races": int(len(races)), "race_dates": int(races["race_date"].nunique()),
            "pair_rows": EXPECTED_PAIR_ROWS, "positive_pair_labels": EXPECTED_RACES * 3,
            "races_by_year": {str(year): int(count) for year, count in races["evaluation_year"].value_counts().sort_index().items()},
            "date_min": str(races["race_date"].min()), "date_max": str(races["race_date"].max()),
        },
        "predeclared_primary_gates": {
            "fixed_old_ID_selected_pair_probability": {
                "baseline_probability": "jockey_id_candidate_calibrated_probability",
                "candidate_probability": "reliability_candidate_calibrated_probability",
                "brier_candidate_minus_baseline": fixed_brier_delta,
                "log_loss_candidate_minus_baseline": fixed_logloss_delta,
                "brier_date_bootstrap_ci_high": brier_upper,
                "log_loss_date_bootstrap_ci_high": logloss_upper,
                "both_point_estimates_improved": bool(fixed_brier_delta < 0 and fixed_logloss_delta < 0),
                "at_least_one_95pct_ci_upper_below_zero": bool(min(brier_upper, logloss_upper) < 0),
                "status": "PASS" if probability_gate else "FAIL",
            },
            "reranked_selected_pair_hit_rate": {
                "baseline_hits": selected_hits["selected_jockey_id_candidate"]["hits"],
                "candidate_hits": selected_hits["selected_reliability_candidate"]["hits"],
                "candidate_minus_baseline_hit_rate": selection_delta,
                "paired_date_bootstrap_ci_low": hit_lower,
                "selection_changes": changed, "gains": changed_gains, "losses": changed_losses,
                "ties_on_changed_selections": changed_ties,
                "status": "PASS" if selection_confirmed else "NOT_CONFIRMED",
            },
            "all_pair_race_equal_guardrail": {
                "baseline_brier": metric_value(overall, "baseline_all_pair_brier"),
                "candidate_brier": metric_value(overall, "candidate_calibrated_all_pair_brier"),
                "brier_candidate_minus_baseline": all_pair_brier_delta,
                "brier_point_deteriorated": all_pair_brier_worsened,
                "baseline_log_loss": metric_value(overall, "baseline_all_pair_log_loss"),
                "candidate_log_loss": metric_value(overall, "candidate_calibrated_all_pair_log_loss"),
                "log_loss_candidate_minus_baseline": all_pair_logloss_delta,
                "log_loss_point_deteriorated": all_pair_logloss_worsened,
                "status": "PASS" if all_pair_guardrail else "FAIL",
            },
            "composite": {"status": "PASS" if composite else "FAIL", "passed": bool(composite)},
        },
        "secondary_selection_context": {
            "raw_top2": selected_hits["selected_raw_top2"],
            "saved_basic_429": selected_hits["selected_jockey_basic_candidate"],
            "candidate_minus_raw_top2_hit_rate": metric_value(overall, "candidate_minus_raw_top2_hit"),
            "candidate_minus_saved_basic_hit_rate": metric_value(overall, "candidate_minus_jockey_basic_hit"),
            "not_used_as_primary_gate": True,
        },
        "metrics_contract": {
            "fixed_pair": "old selected_jockey_id_candidate pair in every race; compare stored baseline probability with candidate raw/calibrated probability",
            "reranked_pair": "new selected_reliability_candidate pair; report actual concurrent Top3 hits separately from fixed-pair probability loss",
            "all_pair_guardrail": "mean pair Brier/log loss within race, then equal weight per race; candidate calibrated probability vs frozen ID baseline",
            "probability_clipping": "p clipped to [1e-15, 1-1e-15] for log loss; Brier uses the same clipped p",
            "date_bootstrap": "frozen 2,000 x 269 date schedule; paired race-level differences; zero-denominator draws excluded and counted",
            "history_subgroups": "minimum of the two horses' observed starts or same-distance valid-time observations on the old fixed selected pair; bins 0, 1-2, 3-5, 6-10, 11+",
            "odds_table": "posthoc QPL final-price bins on the fixed old ID selections in 2025-2026; no model or selection use",
        },
        "odds_posthoc": odds_info,
        "bootstrap": {
            "schedule_sha256": EXPECTED_BOOTSTRAP_SHA, "draws": int(schedule_receipt["draws"]),
            "dates_per_draw": int(schedule_receipt["dates_per_draw"]), "date_min": schedule_receipt["date_min"],
            "date_max": schedule_receipt["date_max"],
        },
        "input_hashes": locked_hashes,
        "tables": {
            "paired_race_metrics": "outputs/report/paired_race_metrics.csv",
            "summary": "outputs/report/summary.csv",
            "bootstrap_ci": "outputs/report/bootstrap_ci.csv",
            "changed_selections": "outputs/report/changed_selections.csv",
            "subgroup_summary": "outputs/report/subgroup_summary.csv",
            "posthoc_odds_calibration": "outputs/report/posthoc_odds_calibration.csv",
        },
        "interpretation_limits": [
            "CV from the last five actual same-distance starts is a descriptive relative-time variation measure, not a validated reliability cause or a condition-adjusted stability measure.",
            "Historical evaluation dates were reused in prior development and do not form an independent future holdout.",
            "The 2026 evaluation period is partial through 2026-09-19.",
            "A report gate does not select an operating model; operational promotion is outside this study.",
        ],
    }


def render_readme(report: dict[str, Any], summary: pd.DataFrame) -> str:
    gates = report["predeclared_primary_gates"]
    fixed = gates["fixed_old_ID_selected_pair_probability"]
    selected = gates["reranked_selected_pair_hit_rate"]
    all_pair = gates["all_pair_race_equal_guardrail"]
    lines = [
        "# 제주 F1_STYLE6 두 말 동시 Top3 신뢰도 입력 비교", "",
        "이 보고서는 저장된 F1_STYLE6 말 점수와 기존 선택 ID 모델을 고정한 7개 기록 지원도·변동성 입력 후보를 비교한다. 2024~2026 반복 개발자료 1,779경주·269경주일·76,848 pair를 사용했고, 2026년은 9월 19일까지의 부분기간이다. 독립 미래 검증이나 운영 승격 결과가 아니다.", "",
        "## 사전 지정 gate", "",
        f"고정 비교 pair의 candidate−baseline Brier 차이는 {fixed['brier_candidate_minus_baseline']:+.6f}, log loss 차이는 {fixed['log_loss_candidate_minus_baseline']:+.6f}다. 점추정치 두 개가 모두 개선되고 한 지표 이상 날짜 CI 상한이 0 아래여야 하는 확률 gate: **{fixed['status']}**.",
        f"후보가 새로 고른 pair는 {selected['candidate_hits']}/{report['cohort']['races']} 적중, 기존 선택은 {selected['baseline_hits']}/{report['cohort']['races']}다. 차이는 {100*selected['candidate_minus_baseline_hit_rate']:+.3f}%p이고 날짜 CI 하한은 {100*selected['paired_date_bootstrap_ci_low']:+.3f}%p다. 선택 개선 확인: **{selected['status']}**.",
        f"전체 pair 경주균등 guardrail 차이는 Brier {all_pair['brier_candidate_minus_baseline']:+.6f}, log loss {all_pair['log_loss_candidate_minus_baseline']:+.6f}다. Brier 악화={all_pair['brier_point_deteriorated']}, log loss 악화={all_pair['log_loss_point_deteriorated']}; guardrail: **{all_pair['status']}**.",
        f"산술/보고 상태는 **{report['status']}**이며 복합 개선 상태는 **{report['improvement_status']}**다. 운영 추천은 `false`로 유지한다.", "",
        "고정 old-ID pair에서 확률 손실을 비교한 결과와 후보가 pair를 다시 선택했을 때의 적중률은 별도 표로 계산했다. log loss에는 사전 지정한 1e-15 clipping을 적용했다. Bootstrap은 기존 2,000×269 date schedule을 그대로 사용하고, 하위집단 반복에서 분모가 0인 추출은 CI에서 제외해 개수를 기록했다.", "",
        "경력 하위집단은 old-ID 고정 pair 두 말 중 `observed_starts` 최솟값, 동일거리 관측 하위집단은 `same_valid_times` 최솟값으로 나눴다. 두 수 모두 고정 원천에 보유된 관측 지원도이며 말의 평생 기록 전수값이 아니다. CV는 최근 실제 같은 거리 슬롯에서 유효 완주시간이 3개 이상인 경우의 표본 표준편차/평균으로, 안정성의 원인이나 경주 조건을 보정한 신뢰도라고 해석하지 않는다.", "",
        "QPL 가격표는 2025~2026년 기존 old-ID 고정 선택 pair의 검증된 최종 가격을 사후에 구간화해 old/new 확률 평균과 실제 적중률 간 차이를 표시한다. 후보 새 선택 pair, 가격 학습, 구매 기준, ROI에는 쓰지 않았다.", "",
        "## 코호트와 하위집단", "", "`outputs/report/summary.csv`에는 전체·연도·거리별 비교가, `subgroup_summary.csv`에는 두 과거 지원도별 비교가 있다. 날짜 paired CI, 선택이 바뀐 개별 경주, 사후 가격 구간은 같은 폴더의 나머지 CSV를 참조한다.", "",
        "| 범위 | 경주 | 기존 ID 선택 적중 | 후보 선택 적중 | 후보−기존 적중 차이 |", "|---|---:|---:|---:|---:|",
    ]
    for row in summary.itertuples(index=False):
        lines.append(
            f"| {row.group_type} {row.group} | {int(row.races):,} | {int(row.baseline_selected_hits):,} | "
            f"{int(row.candidate_selected_hits):,} | {100*row.candidate_minus_baseline_hit_rate:+.3f}%p |"
        )
    lines.extend([
        "", "재현 근거와 파일별 SHA-256·바이트 수는 `outputs/REPORT_RECEIPT.json` 및 `ARTIFACT_MANIFEST.json`에 기록한다. 실험 범위, 데이터 출처와 시점 정의는 [PLAN.md](PLAN.md)를 따른다.", "",
    ])
    return "\n".join(lines)


def write_report_artifacts(report: dict[str, Any], races: pd.DataFrame,
                           summary: pd.DataFrame, subgroups: pd.DataFrame,
                           bootstrap: pd.DataFrame, changed: pd.DataFrame,
                           odds: pd.DataFrame, locked_hashes: dict[str, str]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=False)
    table_files = {
        REPORT_DIR / "paired_race_metrics.csv": races.drop(columns=["_date_index"]),
        REPORT_DIR / "summary.csv": summary,
        REPORT_DIR / "bootstrap_ci.csv": bootstrap,
        REPORT_DIR / "changed_selections.csv": changed,
        REPORT_DIR / "subgroup_summary.csv": subgroups,
        REPORT_DIR / "posthoc_odds_calibration.csv": odds,
    }
    for path, frame in table_files.items():
        checked_output(path)
        frame.to_csv(path, index=False, encoding="utf-8")

    readme = render_readme(report, summary)
    checked_output(README)
    with README.open("x", encoding="utf-8") as stream:
        stream.write(readme)

    output_hashes = {
        str(path.relative_to(STUDY)): {"sha256": sha256(path), "bytes": path.stat().st_size}
        for path in [*table_files, README]
    }
    report["output_hashes"] = output_hashes
    write_json_once(REPORT_PATH, report)
    report_receipt = {
        "status": "PASS",
        "arithmetic_status": report["status"],
        "improvement_status": report["improvement_status"],
        "performance_metrics_computed": True,
        "study": STUDY.name,
        "report_sha256": sha256(REPORT_PATH),
        "report_code_sha256": sha256(checked(STUDY / "pair_reliability_report.py")),
        "readme_sha256": sha256(README),
        "input_hashes": locked_hashes,
        "outputs": output_hashes,
        "primary_probability_gate_passed": report["predeclared_primary_gates"]["fixed_old_ID_selected_pair_probability"]["status"] == "PASS",
        "selection_improvement_confirmed": report["predeclared_primary_gates"]["reranked_selected_pair_hit_rate"]["status"] == "PASS",
        "all_pair_guardrail_passed": report["predeclared_primary_gates"]["all_pair_race_equal_guardrail"]["status"] == "PASS",
        "operational_recommendation": False,
    }
    write_json_once(REPORT_RECEIPT, report_receipt)

    local_artifacts: list[dict[str, Any]] = []
    for path in sorted(
        item for item in STUDY.rglob("*")
        if item.is_file() and item != MANIFEST and "__pycache__" not in item.parts
        and ".report-stage" not in str(item)
    ):
        checked(path)
        local_artifacts.append({"path": str(path.relative_to(STUDY)), "sha256": sha256(path), "bytes": path.stat().st_size})
    external_paths = [
        BASE_PREDICTIONS, BASE_REPORT, BASE_REPORT_RECEIPT, FEATURES, BOOTSTRAP,
        BOOTSTRAP_RECEIPT, DIRECT_REPORT, ODDS_ROWS,
    ]
    external_sources = {}
    for path in external_paths:
        source = checked(path)
        relative = str(source.relative_to(ROOT))
        expected = {
            str(BASE_PREDICTIONS.relative_to(ROOT)): EXPECTED_BASE_PREDICTIONS_SHA,
            str(FEATURES.relative_to(ROOT)): EXPECTED_FEATURES_SHA,
            str(BOOTSTRAP.relative_to(ROOT)): EXPECTED_BOOTSTRAP_SHA,
            str(BOOTSTRAP_RECEIPT.relative_to(ROOT)): EXPECTED_BOOTSTRAP_RECEIPT_SHA,
            str(DIRECT_REPORT.relative_to(ROOT)): EXPECTED_DIRECT_REPORT_SHA,
            str(ODDS_ROWS.relative_to(ROOT)): EXPECTED_ODDS_ROWS_SHA,
        }.get(relative)
        digest = sha256(source)
        if expected is not None:
            require(digest == expected, f"external input changed before manifest write: {relative}")
        external_sources[relative] = {"sha256": digest, "bytes": source.stat().st_size}
    manifest = {
        "status": "PASS",
        "study": STUDY.name,
        "local_artifacts": local_artifacts,
        "external_sources": dict(sorted(external_sources.items())),
        "runtime_dependencies": {
            "python": platform.python_version(), "numpy": np.__version__,
            "pandas": pd.__version__, "scipy": scipy.__version__,
        },
        "manifest_self_hash_excluded": True,
    }
    write_json_once(MANIFEST, manifest)


def run_report() -> None:
    helper, dates, schedule, schedule_receipt, locked_hashes = validate_lineage()
    _, candidate, validation = validate_predictions(helper)
    races = build_race_metrics(helper, candidate, dates)
    summary, subgroups, bootstrap = make_summary_tables(races, dates, schedule)
    changed = make_changed_selections(races)
    odds, odds_info = make_odds_calibration(races)
    report = build_report(
        races, summary, subgroups, bootstrap, odds_info,
        validation["selected_hits"], schedule_receipt, locked_hashes,
    )
    recheck_input_locks(locked_hashes)
    write_report_artifacts(report, races, summary, subgroups, bootstrap, changed, odds, locked_hashes)
    print(json.dumps({
        "status": report["status"], "improvement_status": report["improvement_status"],
        "report_sha256": sha256(REPORT_PATH), "report_receipt_sha256": sha256(REPORT_RECEIPT),
        "operational_recommendation": False,
    }, ensure_ascii=False, indent=2), flush=True)


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] != "report":
        raise SystemExit("usage: pair_reliability_report.py report")
    run_report()


if __name__ == "__main__":
    main()
