"""Generate the fixed 2024–2026 evaluation pair predictions for the approved arm.

This module only predicts from the approved 67-column fit and appends its four
columns to the frozen pair table. It does not calculate evaluation metrics.
"""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import io
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit, logit

ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261014_pair_reliability_v1"
OUT = STUDY / "outputs"
FIT_PATH = OUT / "FIT.json"
FIT_RECEIPT = OUT / "FIT_RECEIPT.json"
APPROVAL = OUT / "APPROVAL.json"
PREFLIGHT = OUT / "SOURCE_PREFLIGHT.json"
DRY_RUN = OUT / "DESIGN_DRY_RUN.json"
PREDICTIONS = OUT / "evaluation_pair_predictions.parquet"
PREDICTION_RECEIPT = OUT / "PREDICTION_RECEIPT.json"
FEATURES = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
DIRECT = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
EXPANSION = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
ID = ROOT / "jeju/research/20261012_pair_jockey_id_v1"
BASIC = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
CURRENT_PAIR_REFERENCE = ID / "outputs/evaluation_pair_predictions.parquet"
CURRENT_PREDICTION_RECEIPT = ID / "outputs/PREDICTION_RECEIPT.json"
BASELINE_FIT = EXPANSION / "outputs/expanded_h1_fit.json"
BASE_SOURCE_LOCK = EXPANSION / "outputs/HISTORICAL_SOURCE_LOCK.json"
DIRECT_CORE = DIRECT / "core.py"
PAIR_PREDICT = EXPANSION / "pair_predict.py"
JOCKEY_INPUT = BASIC / "jockey_input.py"
ID_BASIS = ID / "pair_jockey_id_basis.py"
FIT_CODE = STUDY / "pair_reliability_fit.py"
BASIS_CODE = STUDY / "pair_reliability_basis.py"
SOURCE_PREFLIGHT_CODE = STUDY / "source_preflight.py"
FIT_YEARS = (2024, 2025, 2026)
EXPECTED_RACES = {2024: 637, 2025: 654, 2026: 488}
EXPECTED_RUNNERS = {2024: 6329, 2025: 6410, 2026: 4673}
EXPECTED_DATES = {2024: 98, 2025: 98, 2026: 73}
PAIR_KEYS = ["race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j"]
NEW_COLUMNS = [
    "reliability_candidate_eta",
    "reliability_candidate_raw_probability",
    "reliability_candidate_calibrated_probability",
    "selected_reliability_candidate",
]
MODEL_SCOPE = "pair_reliability_h1_h2_fit"
APPROVAL_SHA256 = "76f3e529452d35184fd9e06409973add43c1b62d24eff04f72825bfecab38af3"
EXPECTED_CURRENT_PAIR_SHA256 = "0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6"
ROLLING_BASIS_NAME = "jockey365_past_field_relative_top3_sum"


class PredictionError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise PredictionError(message)


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


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite output: {path}")
    encoded = json.dumps(_json_safe(value), ensure_ascii=False, indent=2, allow_nan=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
        stream.write("\n")


def write_parquet_once(path: Path, frame: pd.DataFrame) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite output: {path}")
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(buffer.getbuffer())


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, checked(path))
    require(spec is not None and spec.loader is not None, f"cannot load frozen helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def validate_fit() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fit = json.loads(checked(FIT_PATH).read_text(encoding="utf-8"))
    receipt = json.loads(checked(FIT_RECEIPT).read_text(encoding="utf-8"))
    approval = json.loads(checked(APPROVAL).read_text(encoding="utf-8"))
    preflight = json.loads(checked(PREFLIGHT).read_text(encoding="utf-8"))
    dry_run = json.loads(checked(DRY_RUN).read_text(encoding="utf-8"))
    require(sha256(APPROVAL) == APPROVAL_SHA256, "root approval hash differs from the reviewed approval")
    require(approval.get("approved") is True and approval.get("approved_by") == "root"
            and approval.get("scope") == MODEL_SCOPE, "root approval missing or scope differs")
    require(fit.get("status") == "PASS"
            and fit.get("scope") == "single pair reliability arm H1/H2 fit only; no evaluation predictions or performance metrics"
            and fit.get("h1_fit_count") == 3 and fit.get("h2_candidate_map_count") == 3,
            "approved H1/H2 fit is not PASS")
    require(fit.get("evaluation_predictions_generated") is False
            and fit.get("performance_metrics_computed") is False,
            "fit artifact exceeds its approved scope")
    require(receipt.get("status") == "PASS" and receipt.get("scope") == MODEL_SCOPE
            and receipt.get("candidate_fit_sha256") == sha256(FIT_PATH),
            "fit receipt/hash mismatch")
    require(receipt.get("approval_sha256") == sha256(APPROVAL)
            and fit.get("approval_sha256") == sha256(APPROVAL), "fit approval lineage mismatch")
    require(receipt.get("fit_code_sha256") == sha256(FIT_CODE)
            and approval.get("fit_code_sha256") == sha256(FIT_CODE), "approved fit code changed")
    require(approval.get("plan_sha256") == sha256(checked(STUDY / "PLAN.md"))
            and approval.get("basis_sha256") == sha256(checked(BASIS_CODE))
            and approval.get("source_preflight_code_sha256") == sha256(checked(SOURCE_PREFLIGHT_CODE))
            and approval.get("source_preflight_sha256") == sha256(checked(PREFLIGHT))
            and approval.get("design_dry_run_sha256") == sha256(checked(DRY_RUN)),
            "approval no longer matches source/design/code hashes")
    require(preflight.get("status") == "PASS" and preflight.get("finish_labels_read") is False
            and preflight.get("evaluation_target_labels_read") is False,
            "saved source preflight changed status or scope")
    require(dry_run.get("status") == "PASS" and dry_run.get("optimizer_runs") == 0
            and dry_run.get("h2_calibration_fits") == 0
            and dry_run.get("evaluation_predictions_generated") is False
            and dry_run.get("evaluation_metrics_computed") is False,
            "saved design dry-run changed scope")
    require(approval.get("source_hashes") == preflight.get("source_hashes")
            and fit.get("source_hashes") == preflight.get("source_hashes"),
            "fit/approval source hashes differ from preflight")
    for relative, expected in preflight.get("source_hashes", {}).items():
        require(sha256(checked(ROOT / relative)) == expected, f"pinned preflight source changed: {relative}")
    require(sha256(CURRENT_PAIR_REFERENCE) == EXPECTED_CURRENT_PAIR_SHA256
            and preflight["fixed_current_pair_reference"]["sha256"] == EXPECTED_CURRENT_PAIR_SHA256,
            "frozen current-ID pair predictions changed")
    current_receipt = json.loads(checked(CURRENT_PREDICTION_RECEIPT).read_text(encoding="utf-8"))
    require(current_receipt.get("status") == "PASS"
            and current_receipt.get("pair_predictions_sha256") == EXPECTED_CURRENT_PAIR_SHA256,
            "frozen current-ID prediction receipt/hash mismatch")
    require(not PREDICTIONS.exists() and not PREDICTIONS.is_symlink()
            and not PREDICTION_RECEIPT.exists() and not PREDICTION_RECEIPT.is_symlink(),
            "new prediction artifact already exists; refusing retry")
    return fit, approval, preflight


def read_history_source() -> pd.DataFrame:
    columns = [
        "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
        "distance_m", "history_cutoff", "observed_starts", "same_starts", "same_valid_times",
        "days_since_same", "mean5_s", "valid_n5", "std5_s",
    ]
    frame = pd.read_parquet(
        checked(FEATURES), columns=columns,
        filters=[("year", ">=", 2024), ("year", "<=", 2026)],
    )
    for column in ("api_record_id", "race_id", "horse_id"):
        frame[column] = frame[column].astype("string")
    frame["race_date"] = pd.to_datetime(frame["race_date"], errors="coerce").dt.normalize()
    frame["history_cutoff"] = pd.to_datetime(frame["history_cutoff"], errors="coerce").dt.normalize()
    require(frame["api_record_id"].notna().all() and frame["api_record_id"].is_unique,
            "evaluation history API key is missing or duplicated")
    require(frame["race_id"].notna().all() and frame["horse_id"].notna().all()
            and frame["race_date"].notna().all(), "evaluation history join key is missing")
    require((frame["history_cutoff"] == frame["race_date"] - pd.Timedelta(days=2)).all(),
            "evaluation history cutoff is not exactly T-2")
    return frame


def attach_history(rows: pd.DataFrame, source: pd.DataFrame, year: int) -> pd.DataFrame:
    left = rows.copy()
    for column in ("api_record_id", "race_id", "horse_id"):
        left[column] = left[column].astype("string")
    left["race_date"] = pd.to_datetime(left["race_date"], errors="coerce").dt.normalize()
    right = source.loc[source["year"].eq(year)].copy()
    require(left["api_record_id"].notna().all() and left["api_record_id"].is_unique
            and right["api_record_id"].is_unique, f"evaluation API key missing or duplicated: {year}")
    require(set(left["api_record_id"]) == set(right["api_record_id"]),
            f"evaluation score/history API coverage differs: {year}")
    keys = ("race_id", "race_date", "year", "horse_id", "horse_number", "distance_m")
    history_columns = (
        "history_cutoff", "observed_starts", "same_starts", "same_valid_times",
        "days_since_same", "mean5_s", "valid_n5", "std5_s",
    )
    joined = left.merge(
        right[["api_record_id", *keys, *history_columns]], on="api_record_id",
        how="left", validate="one_to_one", suffixes=("", "_history"),
    )
    for column in keys:
        source_column = f"{column}_history" if column in left.columns else column
        observed = joined[column]
        expected = joined[source_column]
        if column in ("year", "horse_number", "distance_m"):
            observed = pd.to_numeric(observed, errors="coerce")
            expected = pd.to_numeric(expected, errors="coerce")
        elif column == "race_date":
            observed = pd.to_datetime(observed, errors="coerce").dt.normalize()
            expected = pd.to_datetime(expected, errors="coerce").dt.normalize()
        else:
            observed = observed.astype("string")
            expected = expected.astype("string")
        require(observed.notna().all() and expected.notna().all() and observed.eq(expected).all(),
                f"evaluation history {column} differs after API-key join: {year}")
    require((joined["history_cutoff"] == joined["race_date_history"] - pd.Timedelta(days=2)).all(),
            f"joined evaluation history violates T-2: {year}")
    require(len(joined) == len(left) and joined["api_record_id"].is_unique,
            f"evaluation history join changed roster coverage: {year}")
    return joined


def standardization_from_baseline(core, baseline_fold: dict[str, Any]):
    runner_doc = baseline_fold["runner_standardization"]
    pair_doc = baseline_fold["pair_standardization"]
    runner = core.Standardization(
        columns=core.RUNNER_COLUMNS,
        mean=np.asarray([runner_doc[name]["mean"] for name in core.RUNNER_COLUMNS], dtype=np.float64),
        scale=np.asarray([runner_doc[name]["scale"] for name in core.RUNNER_COLUMNS], dtype=np.float64),
        degenerate=tuple(bool(runner_doc[name]["degenerate"]) for name in core.RUNNER_COLUMNS),
        support_weight=tuple(float(runner_doc[name]["support_weight"]) for name in core.RUNNER_COLUMNS),
    )
    pair = core.PairStandardization(
        mean=np.asarray([pair_doc[name]["mean"] for name in core.BASIS_NAMES], dtype=np.float64),
        scale=np.asarray([pair_doc[name]["scale"] for name in core.BASIS_NAMES], dtype=np.float64),
        degenerate=tuple(bool(pair_doc[name]["degenerate"]) for name in core.BASIS_NAMES),
        support_weight=tuple(float(pair_doc[name]["support_weight"]) for name in core.BASIS_NAMES),
    )
    require(len(runner.mean) == 7 and len(pair.mean) == 20, "frozen style moments changed dimensions")
    return runner, pair


def _fit_coefficients(core, reliability_basis, fit_fold: dict[str, Any]):
    frozen = fit_fold["frozen_60_column_contract"]
    vocabulary = tuple(frozen["id_vocabulary_reused"])
    require(len(vocabulary) == 39 and len(set(vocabulary)) == 39, "saved H1 ID vocabulary changed")
    pi_map, sigma_map = frozen["id_pi_reused"], frozen["id_sigma_reused"]
    pi = np.asarray([pi_map[key] for key in vocabulary], dtype=np.float64)
    sigma = np.asarray([sigma_map[key] for key in vocabulary], dtype=np.float64)
    names = [*core.BASIS_NAMES, ROLLING_BASIS_NAME]
    names.extend(f"jockey_id_effect:{value}" for value in vocabulary)
    names.extend(reliability_basis.BASIS_NAMES)
    require(names == fit_fold["coefficient_order"] and len(names) == 67,
            "saved 67-column coefficient order differs from prediction design")
    beta = np.asarray(fit_fold["coefficients"], dtype=np.float64)
    require(beta.shape == (67,) and np.isfinite(beta).all(), "saved candidate coefficient vector invalid")
    moments_doc = fit_fold["new_basis_moments"]
    require(moments_doc["basis_names"] == list(reliability_basis.BASIS_NAMES),
            "saved reliability moment basis order changed")
    moments = {
        "basis_names": list(moments_doc["basis_names"]),
        "mean": np.asarray(moments_doc["mean"], dtype=np.float64),
        "scale": np.asarray(moments_doc["scale"], dtype=np.float64),
        "degenerate": tuple(bool(value) for value in moments_doc["degenerate"]),
    }
    require(moments["mean"].shape == moments["scale"].shape == (7,)
            and np.isfinite(moments["mean"]).all() and np.isfinite(moments["scale"]).all()
            and (moments["scale"] > 0).all(), "saved reliability moments invalid")
    return vocabulary, pi, sigma, beta, moments


def predict_race(core, id_basis, reliability_basis, race: pd.DataFrame,
                 fit_fold: dict[str, Any], baseline_fold: dict[str, Any]) -> list[dict[str, Any]]:
    race = race.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
    numbers = race["horse_number"].to_numpy(dtype=np.int64)
    require(len(numbers) >= 4 and len(np.unique(numbers)) == len(numbers), "invalid evaluation runner roster")
    require(race["race_id"].nunique() == race["race_date"].nunique() == race["year"].nunique()
            == race["distance_m"].nunique() == 1, "evaluation race metadata conflict")
    require(fit_fold["frozen_60_column_contract"]["style_moments_reused"]
            == baseline_fold["pair_standardization"], "frozen style pair moments differ")
    core_runner, core_pair = standardization_from_baseline(core, baseline_fold)
    runner_z, runner_missing = core.transform_runners(race, core_runner)
    pairs = list(itertools.combinations(sorted(int(number) for number in numbers), 2))
    row_by_number = {int(number): index for index, number in enumerate(numbers)}
    raw_style = np.vstack([
        core.pair_basis(runner_z[row_by_number[a]], runner_z[row_by_number[b]],
                        runner_missing[row_by_number[a]], runner_missing[row_by_number[b]])
        for a, b in pairs
    ])
    style_x = core.transform_pair_basis(raw_style, core_pair)
    p0_map, _ = core.q0_from_scores(numbers.tolist(), race["score"].astype(float).tolist())
    p0 = np.asarray([p0_map[pair] for pair in pairs], dtype=np.float64)
    require(np.isfinite(p0).all() and ((p0 > 0.0) & (p0 < 1.0)).all(), "invalid frozen F1_STYLE6 pair prior")

    rolling_by_number = {
        int(row.horse_number): float(row.jockey365_field_relative_top3)
        for row in race.itertuples(index=False)
    }
    rolling_pair_sum = np.asarray([rolling_by_number[a] + rolling_by_number[b] for a, b in pairs], dtype=np.float64)
    rolling_moment = fit_fold["frozen_60_column_contract"]["rolling_moment_reused"]
    rolling_z = np.zeros(len(pairs), dtype=np.float64) if rolling_moment["degenerate"] else (
        rolling_pair_sum - float(rolling_moment["mean"])
    ) / float(rolling_moment["scale"])

    vocabulary, pi, sigma, beta, moments = _fit_coefficients(core, reliability_basis, fit_fold)
    category_x = id_basis.race_pair_basis(race, pairs, vocabulary, pi, sigma)
    raw_reliability = reliability_basis.race_pair_basis(race, pairs)
    reliability_z = reliability_basis.transform_race(raw_reliability, moments)
    x = np.column_stack((style_x, rolling_z, category_x, reliability_z))
    require(x.shape == (len(pairs), 67) and np.isfinite(x).all(), "evaluation 67-column design invalid")
    require(np.array_equal(x[:, :20], style_x) and np.array_equal(x[:, 20], rolling_z)
            and np.array_equal(x[:, 21:60], category_x) and np.array_equal(x[:, 60:], reliability_z),
            "evaluation basis column order changed")
    eta = logit(p0) + x @ beta
    raw_probability = expit(eta)
    calibration = fit_fold["h2_candidate_platt"]
    slope = float(calibration["B"])
    require(slope > 0.0, "H2 calibrator slope must remain positive")
    calibrated_probability = expit(float(calibration["A"]) + slope * eta)
    selected_pair = core.pair_choice_from_logits(pairs, eta)
    calibrated_selected = core.pair_choice_from_logits(pairs, float(calibration["A"]) + slope * eta)
    require(selected_pair == calibrated_selected, "positive-slope calibration changed pair ranking")
    require(np.isfinite(eta).all() and np.isfinite(raw_probability).all()
            and np.isfinite(calibrated_probability).all()
            and ((raw_probability > 0.0) & (raw_probability < 1.0)).all()
            and ((calibrated_probability > 0.0) & (calibrated_probability < 1.0)).all(),
            "invalid candidate pair probability")
    race_id = str(race["race_id"].iloc[0])
    race_date = race["race_date"].iloc[0].date().isoformat()
    eval_year = int(race["year"].iloc[0])
    distance = int(race["distance_m"].iloc[0])
    return [{
        "race_id": race_id, "race_date": race_date, "evaluation_year": eval_year,
        "distance_m": distance, "horse_i": int(a), "horse_j": int(b),
        "reliability_candidate_eta": float(eta[index]),
        "reliability_candidate_raw_probability": float(raw_probability[index]),
        "reliability_candidate_calibrated_probability": float(calibrated_probability[index]),
        "selected_reliability_candidate": int((a, b) == selected_pair),
        "p0_check": float(p0[index]),
        "score_i_check": float(race.loc[row_by_number[a], "score"]),
        "score_j_check": float(race.loc[row_by_number[b], "score"]),
    } for index, (a, b) in enumerate(pairs)]


def _canonical_pair_keys(frame: pd.DataFrame) -> list[tuple[str, str, int, int, int, int]]:
    require(set(PAIR_KEYS).issubset(frame.columns), "pair keys are incomplete")
    ids = frame["race_id"].astype("string")
    dates = pd.to_datetime(frame["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    years = pd.to_numeric(frame["evaluation_year"], errors="coerce")
    distances = pd.to_numeric(frame["distance_m"], errors="coerce")
    horse_i = pd.to_numeric(frame["horse_i"], errors="coerce")
    horse_j = pd.to_numeric(frame["horse_j"], errors="coerce")
    require(ids.notna().all() and dates.notna().all() and years.notna().all()
            and distances.notna().all() and horse_i.notna().all() and horse_j.notna().all(),
            "pair key contains a missing value")
    numeric = (years, distances, horse_i, horse_j)
    require(all(np.equal(values.to_numpy(dtype=np.float64), np.floor(values.to_numpy(dtype=np.float64))).all()
                for values in numeric), "pair key numeric fields are not integer-valued")
    return list(zip(ids.astype(str), dates.astype(str), years.astype(int), distances.astype(int),
                    horse_i.astype(int), horse_j.astype(int), strict=True))


def run_predictions() -> None:
    fit, approval, preflight = validate_fit()
    core = import_module("reliability_prediction_direct_core", DIRECT_CORE)
    pair_predict = import_module("reliability_prediction_pair_helper", PAIR_PREDICT)
    jockey_input = import_module("reliability_prediction_jockey_input", JOCKEY_INPUT)
    id_basis = import_module("reliability_prediction_id_basis", ID_BASIS)
    reliability_basis = import_module("reliability_prediction_pair_basis", BASIS_CODE)
    source_lock = json.loads(checked(BASE_SOURCE_LOCK).read_text(encoding="utf-8"))
    require(source_lock.get("status") == "PASS", "frozen OOS score source lock is not PASS")
    baseline_fit = json.loads(checked(BASELINE_FIT).read_text(encoding="utf-8"))
    feature_frame = pd.read_parquet(
        checked(FEATURES), columns=pair_predict.EVAL_FEATURE_COLUMNS,
        filters=[("year", ">=", 2024), ("year", "<=", 2026)],
    )
    feature_frame["race_date"] = pd.to_datetime(feature_frame["race_date"], errors="coerce").dt.normalize()
    require(feature_frame["race_date"].notna().all() and feature_frame["year"].isin(FIT_YEARS).all(),
            "evaluation fixed feature source schema/range changed")
    history_source = read_history_source()
    starts = jockey_input.load_starts(include_results=True)

    candidate_rows: list[dict[str, Any]] = []
    score_sources: dict[str, Any] = {}
    for year in FIT_YEARS:
        rows, score_sources[str(year)] = pair_predict.evaluation_runner_scores(year, feature_frame, source_lock)
        rows = attach_history(rows, history_source, year)
        for column in ("api_record_id", "race_id", "horse_id"):
            rows[column] = rows[column].astype("string")
        rows["race_date"] = pd.to_datetime(rows["race_date"], errors="coerce").dt.normalize()
        event = jockey_input.attach_event_jockey(rows, starts)
        rolling = jockey_input.rolling_features(event, starts)
        event = event.merge(
            rolling[["api_record_id", "jockey365_n", "jockey365_top3", "jockey365_expected_top3",
                     "jockey365_field_relative_top3"]],
            on="api_record_id", how="left", validate="one_to_one",
        )
        require(event["jockey365_field_relative_top3"].notna().all(),
                f"evaluation rolling rider feature is missing: {year}")
        fit_fold = next(row for row in fit["folds"] if int(row["evaluation_year"]) == year)
        baseline_fold = next(row for row in baseline_fit["folds"] if int(row["evaluation_year"]) == year)
        race_count = 0
        runner_count = 0
        for _, race in event.groupby("race_id", sort=True):
            candidate_rows.extend(predict_race(core, id_basis, reliability_basis, race, fit_fold, baseline_fold))
            race_count += 1
            runner_count += len(race)
        require(race_count == EXPECTED_RACES[year] and runner_count == EXPECTED_RUNNERS[year],
                f"evaluation race/runner roster changed: {year}")
        require(event["race_date"].dt.date.nunique() == EXPECTED_DATES[year],
                f"evaluation date inventory changed: {year}")

    candidate = pd.DataFrame(candidate_rows)
    require(len(candidate) == 76848 and candidate["race_id"].nunique() == 1779
            and candidate["race_date"].nunique() == 269, "candidate evaluation pair roster changed")
    require(not candidate.duplicated(PAIR_KEYS).any(), "candidate evaluation pair key duplicated")
    require((candidate.groupby("race_id")["selected_reliability_candidate"].sum() == 1).all(),
            "candidate must select exactly one pair per race")
    require(np.isfinite(candidate[NEW_COLUMNS].to_numpy(dtype=np.float64)).all(),
            "candidate evaluation output contains a non-finite value")

    # The frozen table is read as an immutable comparator and copied through;
    # its existing y_pair column is neither used to build predictions nor scored here.
    old = pd.read_parquet(checked(CURRENT_PAIR_REFERENCE))
    require(len(old) == 76848 and old["race_id"].nunique() == 1779,
            "frozen current pair reference row/race count changed")
    old_columns = old.columns.tolist()
    require(not set(NEW_COLUMNS).intersection(old_columns), "new reliability output columns already exist")
    old_keys = _canonical_pair_keys(old)
    new_keys = _canonical_pair_keys(candidate)
    require(len(set(old_keys)) == len(old_keys) and len(set(new_keys)) == len(new_keys),
            "duplicate pair key in current or candidate table")
    require(set(old_keys) == set(new_keys), "candidate and frozen pair key sets differ")
    index_by_key = {key: index for index, key in enumerate(new_keys)}
    positions = np.asarray([index_by_key[key] for key in old_keys], dtype=np.int64)
    aligned = candidate.iloc[positions].reset_index(drop=True)
    require(np.allclose(pd.to_numeric(old["p0"], errors="coerce").to_numpy(dtype=np.float64),
                        aligned["p0_check"].to_numpy(dtype=np.float64), rtol=0.0, atol=1e-15),
            "fixed F1_STYLE6 pair prior changed")
    if "score_i" in old and "score_j" in old:
        require(np.array_equal(pd.to_numeric(old["score_i"], errors="coerce").to_numpy(dtype=np.float64),
                               aligned["score_i_check"].to_numpy(dtype=np.float64))
                and np.array_equal(pd.to_numeric(old["score_j"], errors="coerce").to_numpy(dtype=np.float64),
                                   aligned["score_j_check"].to_numpy(dtype=np.float64)),
                "fixed F1_STYLE6 runner score changed")
    result = old.copy()
    for column in NEW_COLUMNS:
        result[column] = aligned[column].to_numpy()
    require(result.columns.tolist() == old_columns + NEW_COLUMNS,
            "prediction schema must preserve every old column and append exactly four reliability fields")
    require(len(result) == 76848 and result["race_id"].nunique() == 1779
            and result["race_date"].nunique() == 269, "final prediction table dimensions changed")
    require((result.groupby("race_id")["selected_reliability_candidate"].sum() == 1).all(),
            "final output candidate selector does not select one pair per race")

    receipt = {
        "status": "PASS", "study": STUDY.name,
        "scope": "fixed evaluation pair prediction only; no evaluation performance metrics",
        "fit_sha256": sha256(FIT_PATH), "fit_receipt_sha256": sha256(FIT_RECEIPT),
        "approval_sha256": sha256(APPROVAL), "source_preflight_sha256": sha256(PREFLIGHT),
        "design_dry_run_sha256": sha256(DRY_RUN),
        "prediction_code_sha256": sha256(Path(__file__).resolve()),
        "reliability_basis_sha256": sha256(BASIS_CODE),
        "frozen_current_pair_reference_sha256": sha256(CURRENT_PAIR_REFERENCE),
        "source_preflight_code_sha256": sha256(SOURCE_PREFLIGHT_CODE),
        "frozen_direct_core_sha256": sha256(DIRECT_CORE),
        "frozen_pair_prediction_helper_sha256": sha256(PAIR_PREDICT),
        "frozen_jockey_input_helper_sha256": sha256(JOCKEY_INPUT),
        "frozen_jockey_id_basis_sha256": sha256(ID_BASIS),
        "evaluation_score_sources": score_sources,
        "prediction_rows": int(len(result)), "prediction_races": int(result["race_id"].nunique()),
        "evaluation_dates": int(result["race_date"].nunique()),
        "by_year_rows": {str(int(k)): int(v) for k, v in result.groupby("evaluation_year").size().items()},
        "by_year_races": {str(int(k)): int(v) for k, v in result.groupby("evaluation_year")["race_id"].nunique().items()},
        "candidate_probability_column": "reliability_candidate_calibrated_probability",
        "candidate_raw_probability_column": "reliability_candidate_raw_probability",
        "candidate_eta_column": "reliability_candidate_eta",
        "candidate_selector_column": "selected_reliability_candidate",
        "fixed_id_probability_column": "jockey_id_candidate_calibrated_probability",
        "fixed_id_selector_column": "selected_jockey_id_candidate",
        "secondary_selector_columns": ["selected_raw_top2", "selected_jockey_basic_candidate"],
        "selected_candidate_per_race": int(result.groupby("race_id")["selected_reliability_candidate"].sum().eq(1).sum()),
        "frozen_input_columns_preserved": True,
        "output_columns": result.columns.tolist(),
        "evaluation_labels_used_for_prediction": False,
        "performance_metrics_computed": False,
        "pair_predictions_sha256": None,
    }
    # Serialize and write only after all roster, prior, schema, and probability checks pass.
    temp_buffer = io.BytesIO()
    result.to_parquet(temp_buffer, index=False)
    prediction_bytes = temp_buffer.getvalue()
    receipt["pair_predictions_sha256"] = hashlib.sha256(prediction_bytes).hexdigest()
    require(not PREDICTIONS.exists() and not PREDICTIONS.is_symlink()
            and not PREDICTION_RECEIPT.exists() and not PREDICTION_RECEIPT.is_symlink(),
            "prediction output appeared during generation; refusing overwrite")
    PREDICTIONS.parent.mkdir(parents=True, exist_ok=True)
    with PREDICTIONS.open("xb") as stream:
        stream.write(prediction_bytes)
    require(sha256(PREDICTIONS) == receipt["pair_predictions_sha256"],
            "written prediction hash differs from prepared output")
    write_json_once(PREDICTION_RECEIPT, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "predict":
        raise SystemExit("usage: pair_reliability_predict.py predict")
    run_predictions()
