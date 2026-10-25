"""Predict the fixed 2024–2026 evaluation cohort from the approved fit.

The writer appends four candidate columns to the frozen ID prediction table.
It does not calculate evaluation performance metrics or modify old columns.
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
STUDY = ROOT / "jeju/research/20261015_pair_riding_conditions_v1"
OUT = STUDY / "outputs"
PREFIT = STUDY / "outputs_prefit_v2"
PLAN = STUDY / "PLAN.md"
PREFLIGHT = PREFIT / "FEATURE_PREFLIGHT.json"
DRY_RUN = PREFIT / "DESIGN_DRY_RUN.json"
RUNNER_BASIS = PREFIT / "riding_conditions_runner_basis.parquet"
RECONCILIATION = PREFIT / "SAVED_ID_RECONCILIATION.json"
ROOT_SOURCE_REVIEW = STUDY / "ROOT_SOURCE_REVIEW.json"
NEW_DESIGN_RECONCILIATION = PREFIT / "NEW_CANDIDATE_FIRST60_RECONCILIATION.json"
SOURCE_HASHES = STUDY / "SOURCE_HASHES.json"
SOURCE_CACHE = STUDY / "outputs/source_started_event_rider.parquet"
SOURCE_CACHE_RECEIPT = STUDY / "outputs/SOURCE_CACHE_RECEIPT.json"
RELIABILITY_FIT_HELPER = ROOT / "jeju/research/20261014_pair_reliability_v1/pair_reliability_fit.py"
APPROVAL = OUT / "APPROVAL.json"
FIT_PATH = OUT / "FIT.json"
FIT_RECEIPT = OUT / "FIT_RECEIPT.json"
PREDICTIONS = OUT / "evaluation_pair_predictions.parquet"
PREDICTION_RECEIPT = OUT / "PREDICTION_RECEIPT.json"
FIT_CODE = STUDY / "pair_riding_conditions_fit.py"
PREDICT_CODE = STUDY / "pair_riding_conditions_predict.py"
BASIS_CODE = STUDY / "riding_conditions_basis.py"
PREPARE_CODE = STUDY / "prepare.py"
BASE = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
ID = ROOT / "jeju/research/20261012_pair_jockey_id_v1"
EXPANSION = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
DIRECT = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
ID_PREDICT_CODE = ID / "pair_jockey_id_predict.py"
ID_BASIS_CODE = ID / "pair_jockey_id_basis.py"
ID_FIT = ID / "outputs/FIT.json"
ID_PREDICTIONS = ID / "outputs/evaluation_pair_predictions.parquet"
ID_PREDICTION_RECEIPT = ID / "outputs/PREDICTION_RECEIPT.json"
EXPANDED_FIT = EXPANSION / "outputs/expanded_h1_fit.json"
SOURCE_LOCK = EXPANSION / "outputs/HISTORICAL_SOURCE_LOCK.json"
DIRECT_CORE = DIRECT / "core.py"
PAIR_PREDICT = EXPANSION / "pair_predict.py"
JOCKEY_INPUT = BASE / "jockey_input.py"
KEYS = ["race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j"]
FIT_YEARS = (2024, 2025, 2026)
EXPECTED_RACES = {2024: 637, 2025: 654, 2026: 488}
EXPECTED_DATES = {2024: 98, 2025: 98, 2026: 73}
BASELINE_P = "jockey_id_candidate_calibrated_probability"
BASELINE_ETA = "jockey_id_candidate_eta"
BASELINE_SELECTED = "selected_jockey_id_candidate"
NEW_COLUMNS = [
    "riding_conditions_candidate_eta",
    "riding_conditions_candidate_raw_probability",
    "riding_conditions_candidate_calibrated_probability",
    "selected_riding_conditions_candidate",
]
MODEL_SCOPE = "pair_riding_conditions_h1_h2_fit"


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
    require(not path.is_symlink(), f"input symlink rejected: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"input outside workspace: {path}")
    return resolved


def json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(json_safe(value), stream, ensure_ascii=False, indent=2, allow_nan=False)
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


def validate_fit() -> tuple[dict, dict, dict]:
    require(not PREDICTIONS.exists() and not PREDICTIONS.is_symlink()
            and not PREDICTION_RECEIPT.exists() and not PREDICTION_RECEIPT.is_symlink(),
            "prediction artifact exists; refusing retry/overwrite")
    fit = json.loads(checked(FIT_PATH).read_text(encoding="utf-8"))
    fit_receipt = json.loads(checked(FIT_RECEIPT).read_text(encoding="utf-8"))
    approval = json.loads(checked(APPROVAL).read_text(encoding="utf-8"))
    preflight = json.loads(checked(PREFLIGHT).read_text(encoding="utf-8"))
    dry_run = json.loads(checked(DRY_RUN).read_text(encoding="utf-8"))
    cache_receipt = json.loads(checked(SOURCE_CACHE_RECEIPT).read_text(encoding="utf-8"))
    reconcile = json.loads(checked(RECONCILIATION).read_text(encoding="utf-8"))
    root_review = json.loads(checked(ROOT_SOURCE_REVIEW).read_text(encoding="utf-8"))
    require(fit.get("status") == "PASS" and fit.get("h1_fit_count") == 3
            and fit.get("h2_candidate_map_count") == 3
            and fit.get("scope") == "single fixed riding-conditions arm; three H1 fits and three H2 Platt fits only; no evaluation predictions or metrics",
            "approved candidate fit is not PASS or scope differs")
    require(fit.get("evaluation_predictions_generated") is False
            and fit.get("performance_metrics_computed") is False,
            "fit artifact exceeds approved scope")
    require(fit_receipt.get("status") == "PASS"
            and fit_receipt.get("scope") == MODEL_SCOPE
            and fit_receipt.get("candidate_fit_sha256") == sha256(FIT_PATH)
            and fit_receipt.get("approval_sha256") == sha256(APPROVAL)
            and fit_receipt.get("fit_code_sha256") == sha256(FIT_CODE)
            and fit_receipt.get("predict_code_sha256") == sha256(PREDICT_CODE),
            "fit receipt/hash lineage mismatch")
    require(approval.get("approved") is True and approval.get("approved_by") == "root"
            and approval.get("scope") == MODEL_SCOPE
            and approval.get("fit_code_sha256") == sha256(FIT_CODE)
            and approval.get("predict_code_sha256") == sha256(PREDICT_CODE)
            and approval.get("plan_sha256") == sha256(checked(PLAN))
            and approval.get("preflight_sha256") == sha256(checked(PREFLIGHT))
            and approval.get("dry_run_sha256") == sha256(checked(DRY_RUN))
            and approval.get("runner_basis_sha256") == sha256(checked(RUNNER_BASIS))
            and approval.get("source_hashes_sha256") == sha256(checked(SOURCE_HASHES))
            and approval.get("cache_receipt_sha256") == sha256(checked(SOURCE_CACHE_RECEIPT))
            and approval.get("reconciliation_sha256") == sha256(checked(RECONCILIATION))
            and approval.get("new_design_reconciliation_sha256") == sha256(checked(NEW_DESIGN_RECONCILIATION))
            and approval.get("reliability_fit_helper_sha256") == sha256(checked(RELIABILITY_FIT_HELPER))
            and approval.get("root_source_review_sha256") == sha256(checked(ROOT_SOURCE_REVIEW)),
            "root approval no longer matches reviewed sources/code")
    require(preflight.get("status") == "PASS" and preflight.get("target_current_outcome_used_in_features") is False
            and preflight.get("future_history_after_cutoff_used") is False
            and dry_run.get("status") == "PASS" and dry_run.get("optimizer_runs") == 0
            and reconcile.get("status") == "PASS" and reconcile.get("selection_mismatches") == 0,
            "prefit design or frozen ID reconstruction status changed")
    require(cache_receipt.get("status") == "PASS"
            and cache_receipt.get("cache_sha256") == sha256(SOURCE_CACHE)
            and fit.get("source_cache_sha256") == sha256(SOURCE_CACHE),
            "frozen event-rider cache changed")
    require(fit.get("preflight_sha256") == sha256(PREFLIGHT)
            and fit.get("design_dry_run_sha256") == sha256(DRY_RUN)
            and fit.get("runner_basis_sha256") == sha256(RUNNER_BASIS)
            and fit.get("source_lock_sha256") == sha256(SOURCE_HASHES)
            and fit.get("frozen_reliability_fit_helper_sha256") == sha256(checked(RELIABILITY_FIT_HELPER)),
            "fit source lineage changed")
    for relative, expected in fit.get("source_hashes", {}).items():
        require(sha256(checked(ROOT / relative)) == expected, f"pinned input changed: {relative}")
    require(sha256(checked(ID_PREDICTIONS)) == fit["source_hashes"].get(
        ID_PREDICTIONS.relative_to(ROOT).as_posix()), "frozen current-ID prediction changed")
    require(sha256(checked(ID_PREDICTION_RECEIPT)) == fit["source_hashes"].get(
        ID_PREDICTION_RECEIPT.relative_to(ROOT).as_posix()), "frozen current-ID receipt changed")
    source_lock = json.loads(checked(SOURCE_LOCK).read_text(encoding="utf-8"))
    require(source_lock.get("status") == "PASS", "frozen F1_STYLE6 source lock is not PASS")
    return fit, approval, source_lock


def attach_runner_basis(rows: pd.DataFrame, basis_module) -> pd.DataFrame:
    columns = ["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number", "distance_m",
               *basis_module.RUNNER_COLUMNS]
    source = pd.read_parquet(checked(RUNNER_BASIS), columns=columns)
    for column in ("api_record_id", "race_id", "horse_id"):
        source[column] = source[column].astype("string")
    source["race_date"] = pd.to_datetime(source["race_date"], errors="coerce").dt.normalize()
    left = rows.copy()
    for column in ("api_record_id", "race_id", "horse_id"):
        left[column] = left[column].astype("string")
    left["race_date"] = pd.to_datetime(left["race_date"], errors="coerce").dt.normalize()
    year = int(left["year"].iloc[0])
    right = source.loc[source["year"].eq(year)]
    require(left["api_record_id"].is_unique and right["api_record_id"].is_unique
            and set(left["api_record_id"]) == set(right["api_record_id"]),
            f"evaluation runner-basis API coverage differs: {year}")
    keys = ("race_id", "race_date", "year", "horse_id", "horse_number", "distance_m")
    joined = left.merge(right, on="api_record_id", how="left", suffixes=("", "_source"), validate="one_to_one")
    for key in keys:
        source_key = f"{key}_source" if key in left.columns else key
        lhs, rhs = joined[key], joined[source_key]
        if key in ("year", "horse_number", "distance_m"):
            lhs, rhs = pd.to_numeric(lhs, errors="coerce"), pd.to_numeric(rhs, errors="coerce")
        elif key == "race_date":
            lhs, rhs = pd.to_datetime(lhs, errors="coerce").dt.normalize(), pd.to_datetime(rhs, errors="coerce").dt.normalize()
        else:
            lhs, rhs = lhs.astype("string"), rhs.astype("string")
        require(lhs.notna().all() and rhs.notna().all() and lhs.eq(rhs).all(),
                f"evaluation runner-basis key mismatch: {key}")
    return joined


def frozen_60_design(core, id_basis, old_predict, race: pd.DataFrame,
                     baseline_fold: dict, saved_id_fold: dict, rolling_moment: dict):
    race = race.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
    numbers = race["horse_number"].to_numpy(dtype=int)
    require(len(numbers) >= 4 and len(set(numbers.tolist())) == len(numbers),
            "invalid evaluation race roster")
    pairs = list(itertools.combinations(sorted(numbers.tolist()), 2))
    position = {int(number): i for i, number in enumerate(numbers.tolist())}
    runner_stats, old_pair_stats = old_predict.standardization_from_baseline(core, baseline_fold)
    z, missing = core.transform_runners(race, runner_stats)
    raw20 = np.vstack([
        core.pair_basis(z[position[a]], z[position[b]], missing[position[a]], missing[position[b]])
        for a, b in pairs
    ])
    prior_map, _ = core.q0_from_scores(numbers.tolist(), race["score"].astype(float).tolist())
    p0 = np.asarray([prior_map[pair] for pair in pairs], dtype=np.float64)
    require(np.isfinite(p0).all() and ((p0 > 0.0) & (p0 < 1.0)).all(), "invalid frozen pair prior")
    style_x = core.transform_pair_basis(raw20, old_pair_stats)

    value_by_number = {int(row.horse_number): float(row.jockey365_field_relative_top3)
                       for row in race.itertuples(index=False)}
    pair_rolling = np.asarray([value_by_number[a] + value_by_number[b] for a, b in pairs], dtype=np.float64)
    rolling_z = np.zeros(len(pairs), dtype=np.float64) if rolling_moment["degenerate"] else (
        pair_rolling - float(rolling_moment["mean"])
    ) / float(rolling_moment["scale"])
    category = saved_id_fold["category_encoding"]
    vocabulary = tuple(category["vocabulary_h1_only"])
    pi = np.asarray([float(category["pi"][key]) for key in vocabulary], dtype=np.float64)
    sigma = np.asarray([float(category["sigma"][key]) for key in vocabulary], dtype=np.float64)
    fake_rows = race[["horse_number", "jockey_id"]]
    category_x = id_basis.race_pair_basis(fake_rows, pairs, vocabulary, pi, sigma)
    x60 = np.column_stack((style_x, rolling_z, category_x))
    require(x60.shape == (len(pairs), 60) and np.isfinite(x60).all(), "frozen 60-column evaluation design changed")

    # First-60 numerical reconciliation: apply saved ID coefficients and saved
    # Platt map to the new candidate's actual first 60 columns and frozen offset.
    id_beta = np.asarray(
        [saved_id_fold["beta_by_basis"][name] for name in core.BASIS_NAMES]
        + [float(saved_id_fold["gamma_jockey365_pair_sum"])]
        + [float(saved_id_fold["theta_by_jockey_id"][key]) for key in vocabulary],
        dtype=np.float64,
    )
    require(id_beta.shape == (60,) and np.isfinite(id_beta).all(), "saved ID coefficient schema changed")
    id_eta = logit(p0) + x60 @ id_beta
    saved_cal = saved_id_fold["h2_candidate_platt"]
    id_calibrated = expit(float(saved_cal["A"]) + float(saved_cal["B"]) * id_eta)
    id_rows, _ = old_predict.predict_race(core, id_basis, race, saved_id_fold, baseline_fold)
    require(len(id_rows) == len(pairs), "frozen ID helper returned wrong pair count")
    require(np.max(np.abs(id_eta - np.asarray([row[BASELINE_ETA] for row in id_rows]))) <= 1e-12
            and np.max(np.abs(id_calibrated - np.asarray([row[BASELINE_P] for row in id_rows]))) <= 1e-12,
            "new candidate first-60 design fails saved-ID numerical reconstruction")
    return race, pairs, p0, x60, id_eta, id_calibrated, id_rows


def prediction_race(core, id_basis, basis_module, old_predict, race: pd.DataFrame,
                    candidate_fold: dict, baseline_fold: dict, saved_id_fold: dict,
                    rolling_moment: dict):
    race, pairs, p0, x60, id_eta, id_calibrated, _ = frozen_60_design(
        core, id_basis, old_predict, race, baseline_fold, saved_id_fold, rolling_moment,
    )
    value_by_number = {int(row.horse_number): float(row.jockey365_field_relative_top3)
                       for row in race.itertuples(index=False)}
    score_by_number = {int(row.horse_number): float(row.score) for row in race.itertuples(index=False)}
    pair_rolling = np.asarray([value_by_number[a] + value_by_number[b] for a, b in pairs], dtype=np.float64)
    require(candidate_fold["frozen_21st_rolling_moment"] == rolling_moment,
            "candidate fit changed the frozen 21st rolling moment")
    rolling_moment = candidate_fold["frozen_21st_rolling_moment"]
    rolling_z = np.zeros(len(pairs), dtype=np.float64) if rolling_moment["degenerate"] else (
        pair_rolling - float(rolling_moment["mean"])
    ) / float(rolling_moment["scale"])
    category = candidate_fold["category_encoding"]
    vocabulary = tuple(category["vocabulary_h1_only"])
    pi = np.asarray([float(category["pi"][key]) for key in vocabulary], dtype=np.float64)
    sigma = np.asarray([float(category["sigma"][key]) for key in vocabulary], dtype=np.float64)
    require(list(vocabulary) == list(saved_id_fold["category_encoding"]["vocabulary_h1_only"]),
            "candidate fold changed frozen H1 ID vocabulary")
    saved_category = saved_id_fold["category_encoding"]
    saved_pi = np.asarray([float(saved_category["pi"][key]) for key in vocabulary], dtype=np.float64)
    saved_sigma = np.asarray([float(saved_category["sigma"][key]) for key in vocabulary], dtype=np.float64)
    require(np.array_equal(pi, saved_pi) and np.array_equal(sigma, saved_sigma),
            "candidate fit changed frozen ID category moments")
    raw_pair = basis_module.pair_features_for_race(race)
    pair_keys = list(zip(raw_pair["horse_i"].astype(int), raw_pair["horse_j"].astype(int), strict=True))
    require(pair_keys == pairs, "riding-condition pair order differs from frozen 60-column pair order")
    x_extra = basis_module.transform_pair_features(raw_pair, candidate_fold["new_basis_moments"])
    x_candidate = np.column_stack((x60, x_extra))
    beta = np.asarray(candidate_fold["coefficients"], dtype=np.float64)
    require(x_candidate.shape == (len(pairs), len(beta)) and np.isfinite(x_candidate).all()
            and np.isfinite(beta).all(), "candidate evaluation matrix/coefficient shape changed")
    eta = logit(p0) + x_candidate @ beta
    raw = expit(eta)
    calibration = candidate_fold["h2_candidate_platt"]
    calibrated = expit(float(calibration["A"]) + float(calibration["B"]) * eta)
    chosen = core.pair_choice_from_logits(pairs, eta)
    id_selected = core.pair_choice_from_logits(pairs, id_eta)
    require(float(calibration["B"]) > 0.0
            and chosen == core.pair_choice_from_logits(pairs, float(calibration["A"]) + float(calibration["B"]) * eta),
            "positive H2 Platt slope changed the candidate selector")
    date = pd.Timestamp(race["race_date"].iloc[0]).date().isoformat()
    year = int(race["year"].iloc[0])
    distance = int(race["distance_m"].iloc[0])
    race_id = str(race["race_id"].iloc[0])
    rows = []
    for index, (a, b) in enumerate(pairs):
        rows.append({
            "race_id": race_id, "race_date": date, "evaluation_year": year,
            "distance_m": distance, "horse_i": int(a), "horse_j": int(b),
            "riding_conditions_candidate_eta": float(eta[index]),
            "riding_conditions_candidate_raw_probability": float(raw[index]),
            "riding_conditions_candidate_calibrated_probability": float(calibrated[index]),
            "selected_riding_conditions_candidate": int((a, b) == chosen),
            "_reconstructed_saved_id_eta": float(id_eta[index]),
            "_reconstructed_saved_id_probability": float(id_calibrated[index]),
            "_reconstructed_saved_id_selected": int((a, b) == id_selected),
            "_p0_check": float(p0[index]),
            "_score_i_check": score_by_number[a],
            "_score_j_check": score_by_number[b],
        })
    return rows


def run_first60_reconciliation() -> None:
    """Reconcile this new predictor's first 60 columns before any new-model fit."""
    require(not NEW_DESIGN_RECONCILIATION.exists() and not NEW_DESIGN_RECONCILIATION.is_symlink(),
            "refusing to overwrite first-60 reconciliation receipt")
    core = import_module("prefit_pair_core_first60_reconciliation", DIRECT_CORE)
    pair_predict = import_module("prefit_pair_predict_first60_reconciliation", PAIR_PREDICT)
    jockey_input = import_module("prefit_jockey_input_first60_reconciliation", JOCKEY_INPUT)
    id_basis = import_module("prefit_id_basis_first60_reconciliation", ID_BASIS_CODE)
    old_predict = import_module("prefit_id_predict_first60_reconciliation", ID_PREDICT_CODE)
    basis_module = import_module("prefit_riding_basis_first60_reconciliation", BASIS_CODE)
    baseline_fit = json.loads(checked(EXPANDED_FIT).read_text(encoding="utf-8"))
    basic_fit = json.loads(checked(BASE / "outputs/FIT.json").read_text(encoding="utf-8"))
    saved_id_fit = json.loads(checked(ID_FIT).read_text(encoding="utf-8"))
    source_lock = json.loads(checked(SOURCE_LOCK).read_text(encoding="utf-8"))
    old = pd.read_parquet(checked(ID_PREDICTIONS))
    require(len(old) == 76848 and old["race_id"].nunique() == 1779
            and old["race_date"].nunique() == 269, "frozen ID pair reference cohort changed")
    features = pd.read_parquet(
        checked(pair_predict.FEATURES), columns=pair_predict.EVAL_FEATURE_COLUMNS,
        filters=[("year", ">=", 2024), ("year", "<=", 2026)],
    )
    features["race_date"] = pd.to_datetime(features["race_date"], errors="coerce").dt.normalize()
    require(features["race_date"].notna().all(), "frozen evaluation dates invalid")
    starts = jockey_input.load_starts(include_results=True)
    rebuilt: list[dict] = []
    score_sources = {}
    for year in FIT_YEARS:
        rows, source = pair_predict.evaluation_runner_scores(year, features, source_lock)
        score_sources[str(year)] = source
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
        require(event["jockey365_field_relative_top3"].notna().all(), f"frozen rider365 input missing: {year}")
        event = attach_runner_basis(event, basis_module)
        base_fold = next(row for row in baseline_fit["folds"] if int(row["evaluation_year"]) == year)
        basic_fold = next(row for row in basic_fit["folds"] if int(row["evaluation_year"]) == year)
        id_fold = next(row for row in saved_id_fit["folds"] if int(row["evaluation_year"]) == year)
        race_count = 0
        for _, race in event.groupby("race_id", sort=True):
            _, pairs, p0, x60, eta, probability, _ = frozen_60_design(
                core, id_basis, old_predict, race, base_fold, id_fold, basic_fold["new_pair_moment"],
            )
            selected = core.pair_choice_from_logits(pairs, eta)
            date = pd.Timestamp(race["race_date"].iloc[0]).date().isoformat()
            race_id = str(race["race_id"].iloc[0])
            year_value = int(race["year"].iloc[0])
            distance = int(race["distance_m"].iloc[0])
            for index, (horse_i, horse_j) in enumerate(pairs):
                rebuilt.append({
                    "race_id": race_id, "race_date": date, "evaluation_year": year_value,
                    "distance_m": distance, "horse_i": int(horse_i), "horse_j": int(horse_j),
                    "eta": float(eta[index]), "probability": float(probability[index]),
                    "selected": int((horse_i, horse_j) == selected), "p0": float(p0[index]),
                })
            race_count += 1
        require(race_count == EXPECTED_RACES[year], f"reconciliation race count changed: {year}")
    new = pd.DataFrame(rebuilt)
    require(len(new) == 76848 and new["race_id"].nunique() == 1779
            and new["race_date"].nunique() == 269, "new predictor 60-column coverage changed")
    require(not new.duplicated(KEYS).any() and not old.duplicated(KEYS).any(),
            "duplicate first-60 reconciliation pair key")
    compare = old[KEYS + [BASELINE_ETA, BASELINE_P, BASELINE_SELECTED, "p0"]].merge(
        new, on=KEYS, how="outer", validate="one_to_one", indicator=True,
    )
    require(compare["_merge"].eq("both").all(), "new/old first-60 pair keys differ")
    max_diff = {
        "eta": float(np.max(np.abs(compare[BASELINE_ETA] - compare["eta"]))),
        "calibrated_probability": float(np.max(np.abs(compare[BASELINE_P] - compare["probability"]))),
        "logit_offset_prior": float(np.max(np.abs(compare["p0_x"] - compare["p0_y"]))),
    }
    selector_diff = int(np.count_nonzero(
        compare[BASELINE_SELECTED].to_numpy(dtype=np.int64) != compare["selected"].to_numpy(dtype=np.int64)
    ))
    require(max(max_diff.values()) <= 1e-12 and selector_diff == 0
            and int(compare["selected"].sum()) == 1779,
            "new candidate 60-column matrix does not reproduce frozen ID")
    receipt = {
        "status": "PASS",
        "scope": "new candidate prediction implementation's first 60 columns and offset only; no candidate fit/prediction or performance metrics",
        "new_prediction_code_sha256": sha256(checked(PREDICT_CODE)),
        "frozen_predict_code_sha256": sha256(checked(ID_PREDICT_CODE)),
        "frozen_id_fit_sha256": sha256(checked(ID_FIT)),
        "frozen_id_prediction_sha256": sha256(checked(ID_PREDICTIONS)),
        "frozen_basic_fit_sha256": sha256(checked(BASE / "outputs/FIT.json")),
        "frozen_expanded_fit_sha256": sha256(checked(EXPANDED_FIT)),
        "runner_basis_sha256": sha256(checked(RUNNER_BASIS)),
        "pair_rows": int(len(new)), "races": int(new["race_id"].nunique()),
        "evaluation_dates": int(new["race_date"].nunique()),
        "selection_mismatches": selector_diff,
        "max_abs_differences": max_diff,
        "tolerance": 1e-12,
        "historical_results_read_for_frozen_tminus2_rolling_input": True,
        "target_evaluation_outcomes_used": False,
        "performance_metrics_computed": False,
        "score_sources": score_sources,
    }
    write_json_once(NEW_DESIGN_RECONCILIATION, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


def run_predictions() -> None:
    fit, approval, source_lock = validate_fit()
    core = import_module("frozen_pair_core_for_riding_predict", DIRECT_CORE)
    pair_predict = import_module("frozen_pair_predict_for_riding_predict", PAIR_PREDICT)
    jockey_input = import_module("frozen_jockey_input_for_riding_predict", JOCKEY_INPUT)
    id_basis = import_module("frozen_id_basis_for_riding_predict", ID_BASIS_CODE)
    old_predict = import_module("frozen_id_predict_for_riding_predict", ID_PREDICT_CODE)
    basis_module = import_module("riding_conditions_basis_for_predict", BASIS_CODE)
    baseline_fit = json.loads(checked(EXPANDED_FIT).read_text(encoding="utf-8"))
    basic_fit = json.loads(checked(BASE / "outputs/FIT.json").read_text(encoding="utf-8"))
    saved_id_fit = json.loads(checked(ID_FIT).read_text(encoding="utf-8"))
    features = pd.read_parquet(
        checked(pair_predict.FEATURES), columns=pair_predict.EVAL_FEATURE_COLUMNS,
        filters=[("year", ">=", 2024), ("year", "<=", 2026)],
    )
    features["race_date"] = pd.to_datetime(features["race_date"], errors="coerce").dt.normalize()
    require(features["race_date"].notna().all() and features["year"].isin(FIT_YEARS).all(),
            "frozen evaluation feature schema/date changed")
    starts = jockey_input.load_starts(include_results=True)
    old = pd.read_parquet(checked(ID_PREDICTIONS))
    require(len(old) == 76848 and old["race_id"].nunique() == 1779
            and old["race_date"].nunique() == 269, "frozen ID prediction cohort changed")
    old_columns = old.columns.tolist()
    require(old_columns[:6] == KEYS and BASELINE_P in old.columns and BASELINE_ETA in old.columns
            and BASELINE_SELECTED in old.columns, "frozen ID prediction schema changed")

    new_rows: list[dict] = []
    score_sources = {}
    for year in FIT_YEARS:
        rows, score_source = pair_predict.evaluation_runner_scores(year, features, source_lock)
        score_sources[str(year)] = score_source
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
        require(event["jockey365_field_relative_top3"].notna().all(), f"frozen rider365 value missing: {year}")
        event = attach_runner_basis(event, basis_module)
        fold = next(row for row in fit["folds"] if int(row["evaluation_year"]) == year)
        baseline_fold = next(row for row in baseline_fit["folds"] if int(row["evaluation_year"]) == year)
        basic_fold = next(row for row in basic_fit["folds"] if int(row["evaluation_year"]) == year)
        saved_id_fold = next(row for row in saved_id_fit["folds"] if int(row["evaluation_year"]) == year)
        race_count = 0
        for _, race in event.groupby("race_id", sort=True):
            new_rows.extend(prediction_race(
                core, id_basis, basis_module, old_predict, race, fold, baseline_fold, saved_id_fold,
                basic_fold["new_pair_moment"],
            ))
            race_count += 1
        require(race_count == EXPECTED_RACES[year], f"evaluation race count changed: {year}")

    candidate = pd.DataFrame(new_rows)
    require(len(candidate) == 76848 and candidate["race_id"].nunique() == 1779,
            "candidate prediction pair/race coverage changed")
    require(candidate["race_date"].nunique() == 269, "candidate evaluation dates changed")
    require(not candidate.duplicated(KEYS).any(), "duplicate candidate pair key")
    require((candidate.groupby("race_id")["selected_riding_conditions_candidate"].sum() == 1).all(),
            "candidate must select exactly one pair per race")
    numeric_columns = NEW_COLUMNS[:3] + [
        "_reconstructed_saved_id_eta", "_reconstructed_saved_id_probability", "_p0_check",
        "_score_i_check", "_score_j_check",
    ]
    require(np.isfinite(candidate[numeric_columns].to_numpy(dtype=np.float64)).all(),
            "non-finite candidate prediction")

    joined = old[KEYS + [BASELINE_ETA, BASELINE_P, BASELINE_SELECTED, "p0", "score_i", "score_j"]].merge(
        candidate[KEYS + numeric_columns + [NEW_COLUMNS[3], "_reconstructed_saved_id_selected"]],
        on=KEYS, how="outer", validate="one_to_one", indicator=True,
    )
    require(joined["_merge"].eq("both").all(), "candidate and frozen ID pair keys differ")
    id_eta_diff = float(np.max(np.abs(joined[BASELINE_ETA] - joined["_reconstructed_saved_id_eta"])))
    id_prob_diff = float(np.max(np.abs(joined[BASELINE_P] - joined["_reconstructed_saved_id_probability"])))
    p0_diff = float(np.max(np.abs(joined["p0"] - joined["_p0_check"])))
    score_i_diff = float(np.max(np.abs(joined["score_i"] - joined["_score_i_check"])))
    score_j_diff = float(np.max(np.abs(joined["score_j"] - joined["_score_j_check"])))
    require(id_eta_diff <= 1e-12 and id_prob_diff <= 1e-12 and p0_diff <= 1e-15,
            "candidate first-60/offset saved-ID reconstruction failed")
    require(score_i_diff == 0.0 and score_j_diff == 0.0,
            "frozen F1_STYLE6 runner scores differ from saved ID reference")
    saved_selection = joined[BASELINE_SELECTED].to_numpy(dtype=np.int64)
    reconstructed_selection = joined["_reconstructed_saved_id_selected"].to_numpy(dtype=np.int64)
    require(np.count_nonzero(saved_selection != reconstructed_selection) == 0
            and int(reconstructed_selection.sum()) == 1779,
            "reconstructed first-60 selector differs from saved ID selected pairs")

    # Keep old rows, order, dtypes and values; append only the approved columns.
    order = old[KEYS].copy()
    order["_old_row_order"] = np.arange(len(order), dtype=np.int64)
    aligned = order.merge(candidate[KEYS + NEW_COLUMNS], on=KEYS, how="left",
                          validate="one_to_one", sort=False).sort_values("_old_row_order", kind="mergesort")
    require(aligned[NEW_COLUMNS].notna().all().all(), "candidate append alignment produced missing values")
    output = old.copy()
    for column in NEW_COLUMNS:
        output[column] = aligned[column].to_numpy()
    require(output.columns.tolist() == old_columns + NEW_COLUMNS, "old prediction columns/order changed")
    for column in old_columns:
        pd.testing.assert_series_equal(output[column], old[column], check_dtype=True, check_names=True)

    write_parquet_once(PREDICTIONS, output)
    saved_output = pd.read_parquet(checked(PREDICTIONS))
    require(saved_output.columns.tolist() == old_columns + NEW_COLUMNS
            and len(saved_output) == len(old), "written candidate prediction schema/rows changed")
    for column in old_columns:
        pd.testing.assert_series_equal(saved_output[column], old[column], check_dtype=True, check_names=True)
    receipt = {
        "status": "PASS", "study": STUDY.name, "scope": "fixed-cohort candidate predictions only; no evaluation metrics",
        "fit_sha256": sha256(checked(FIT_PATH)), "fit_receipt_sha256": sha256(checked(FIT_RECEIPT)),
        "approval_sha256": sha256(checked(APPROVAL)), "fit_code_sha256": sha256(checked(FIT_CODE)),
        "prediction_code_sha256": sha256(checked(PREDICT_CODE)),
        "runner_basis_sha256": sha256(checked(RUNNER_BASIS)),
        "frozen_id_reference_sha256": sha256(checked(ID_PREDICTIONS)),
        "prediction_rows": int(len(saved_output)), "prediction_races": int(saved_output["race_id"].nunique()),
        "evaluation_dates": int(saved_output["race_date"].nunique()),
        "selected_candidate_per_race": int(saved_output[NEW_COLUMNS[3]].sum()),
        "candidate_probability_column": NEW_COLUMNS[2],
        "candidate_selector_column": NEW_COLUMNS[3],
        "selector_column": NEW_COLUMNS[3],
        "old_columns_preserved_count": len(old_columns),
        "old_columns_preserved_order_and_values": True,
        "frozen_comparator_columns_preserved": True,
        "first_60_reconstruction": {
            "saved_id_eta_max_abs_difference": id_eta_diff,
            "saved_id_calibrated_probability_max_abs_difference": id_prob_diff,
            "p0_offset_max_abs_difference": p0_diff,
            "runner_score_i_max_abs_difference": score_i_diff,
            "runner_score_j_max_abs_difference": score_j_diff,
            "selected_pair_mismatches": 0,
            "pair_rows": int(len(joined)),
            "races": int(joined["race_id"].nunique()),
            "dates": int(joined["race_date"].nunique()),
            "tolerance": 1e-12,
        },
        "historical_results_read_for_frozen_tminus2_rolling_input": True,
        "target_evaluation_outcomes_used_for_prediction": False,
        "performance_metrics_computed": False,
        "score_sources": score_sources,
        "pair_predictions_sha256": sha256(PREDICTIONS),
    }
    write_json_once(PREDICTION_RECEIPT, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("reconcile-first60", "predict-approved"), nargs="?", default=None)
    args = parser.parse_args()
    if args.action is None:
        print("inert: use reconcile-first60 for prefit matrix validation or predict-approved after fit approval")
        return
    if args.action == "reconcile-first60":
        run_first60_reconciliation()
    else:
        run_predictions()


if __name__ == "__main__":
    main()
