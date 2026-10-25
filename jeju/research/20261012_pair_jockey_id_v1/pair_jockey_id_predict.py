"""Create the one fixed evaluation prediction artifact for the ID candidate."""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit, logit

ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261012_pair_jockey_id_v1"
OUT = STUDY / "outputs"
BASE = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
EXPANSION = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
DIRECT = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
FIT_PATH = OUT / "FIT.json"
FIT_RECEIPT = OUT / "FIT_RECEIPT.json"
PREFLIGHT = OUT / "SOURCE_PREFLIGHT.json"
APPROVAL = OUT / "APPROVAL.json"
DRY_RUN = OUT / "DESIGN_DRY_RUN.json"
PAIR_PREDICTIONS = OUT / "evaluation_pair_predictions.parquet"
RACE_DIAGNOSTICS = OUT / "evaluation_race_probabilities.parquet"
PREDICTION_RECEIPT = OUT / "PREDICTION_RECEIPT.json"
BASE_PAIR_PREDICTIONS = BASE / "outputs/evaluation_pair_predictions.parquet"
BASE_RACE_DIAGNOSTICS = BASE / "outputs/evaluation_race_probabilities.parquet"
BASELINE_FIT = EXPANSION / "outputs/expanded_h1_fit.json"
BASE_SOURCE_LOCK = EXPANSION / "outputs/HISTORICAL_SOURCE_LOCK.json"
DIRECT_CORE = DIRECT / "core.py"
INPUT_HELPER = BASE / "jockey_input.py"
FIT_HELPER = BASE / "pair_jockey_fit.py"
ID_BASIS = STUDY / "pair_jockey_id_basis.py"
FIT_YEARS = (2024, 2025, 2026)
EXPECTED_RACES = {2024: 637, 2025: 654, 2026: 488}
KEYS = ["race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j"]


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


def write_json_once(path: Path, value: dict[str, Any]) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def write_parquet_once(path: Path, frame: pd.DataFrame) -> None:
    require(path.resolve().is_relative_to(STUDY), f"output escaped study directory: {path}")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=False)


def import_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, checked(path))
    require(spec is not None and spec.loader is not None, f"cannot load helper: {path}")
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
    fit_script = STUDY / "pair_jockey_id_fit.py"
    preflight_script = STUDY / "source_preflight.py"
    require(fit.get("status") == "PASS" and fit.get("h1_fit_count") == 3
            and fit.get("h2_candidate_map_count") == 3, "approved candidate fit is not PASS")
    require(receipt.get("status") == "PASS" and receipt.get("candidate_fit_sha256") == sha256(FIT_PATH)
            and receipt.get("fit_code_sha256") == sha256(fit_script), "fit receipt/hash mismatch")
    require(approval.get("approved") is True and approval.get("approved_by") == "root"
            and approval.get("scope") == "pair_jockey_id_h1_h2_fit", "root approval missing or scope differs")
    require(approval.get("fit_code_sha256") == sha256(fit_script)
            and approval.get("id_basis_sha256") == sha256(ID_BASIS)
            and approval.get("source_preflight_sha256") == sha256(PREFLIGHT)
            and approval.get("source_preflight_code_sha256") == sha256(preflight_script)
            and approval.get("design_dry_run_sha256") == sha256(DRY_RUN), "approval no longer matches code/source locks")
    require(preflight.get("status") == "PASS" and preflight.get("finish_labels_read") is False
            and dry_run.get("status") == "PASS" and dry_run.get("optimizer_runs") == 0,
            "source or design preflight status changed")
    require(receipt.get("approval_sha256") == sha256(APPROVAL)
            and fit.get("approval_sha256") == sha256(APPROVAL), "approval lineage mismatch")
    for relative, expected in preflight.get("source_hashes", {}).items():
        require(sha256(checked(ROOT / relative)) == expected, f"pinned input source changed: {relative}")
    require(not PAIR_PREDICTIONS.exists() and not RACE_DIAGNOSTICS.exists()
            and not PREDICTION_RECEIPT.exists(), "evaluation prediction artifact already exists")
    return fit, approval, preflight


def standardization_from_baseline(core, fit_row: dict[str, Any]):
    runner_doc = fit_row["runner_standardization"]
    pair_doc = fit_row["pair_standardization"]
    runner = core.Standardization(
        columns=core.RUNNER_COLUMNS,
        mean=np.asarray([runner_doc[name]["mean"] for name in core.RUNNER_COLUMNS], dtype=float),
        scale=np.asarray([runner_doc[name]["scale"] for name in core.RUNNER_COLUMNS], dtype=float),
        degenerate=tuple(bool(runner_doc[name]["degenerate"]) for name in core.RUNNER_COLUMNS),
        support_weight=tuple(float(runner_doc[name]["support_weight"]) for name in core.RUNNER_COLUMNS),
    )
    pair = core.PairStandardization(
        mean=np.asarray([pair_doc[name]["mean"] for name in core.BASIS_NAMES], dtype=float),
        scale=np.asarray([pair_doc[name]["scale"] for name in core.BASIS_NAMES], dtype=float),
        degenerate=tuple(bool(pair_doc[name]["degenerate"]) for name in core.BASIS_NAMES),
        support_weight=tuple(float(pair_doc[name]["support_weight"]) for name in core.BASIS_NAMES),
    )
    require(len(runner.mean) == 7 and len(pair.mean) == 20, "frozen baseline moments dimensions changed")
    return runner, pair


def predict_race(core, id_basis, race: pd.DataFrame, fit_fold: dict[str, Any], base_fold: dict[str, Any]):
    race = race.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
    numbers = race["horse_number"].to_numpy(dtype=int)
    require(len(numbers) >= 4 and len(set(numbers.tolist())) == len(numbers), "invalid evaluation race roster")
    runner_stats, old_pair_stats = standardization_from_baseline(core, base_fold)
    z, missing = core.transform_runners(race, runner_stats)
    pairs = list(itertools.combinations(sorted(numbers.tolist()), 2))
    position = {int(number): i for i, number in enumerate(numbers.tolist())}
    raw20 = np.vstack([
        core.pair_basis(z[position[a]], z[position[b]], missing[position[a]], missing[position[b]])
        for a, b in pairs
    ])
    p0_by_pair, _ = core.q0_from_scores(numbers.tolist(), race["score"].astype(float).tolist())
    p0 = np.asarray([p0_by_pair[pair] for pair in pairs], dtype=float)
    style_x = core.transform_pair_basis(raw20, old_pair_stats)

    value_by_number = {
        int(row.horse_number): float(row.jockey365_field_relative_top3)
        for row in race.itertuples(index=False)
    }
    n_by_number = {int(row.horse_number): int(row.jockey365_n) for row in race.itertuples(index=False)}
    id_by_number = {int(row.horse_number): str(row.jockey_id) for row in race.itertuples(index=False)}
    pair_rolling = np.asarray([value_by_number[a] + value_by_number[b] for a, b in pairs], dtype=float)
    rolling_moment = fit_fold["frozen_21st_rolling_moment"]
    rolling_z = np.zeros(len(pairs), dtype=float) if rolling_moment["degenerate"] else (
        pair_rolling - float(rolling_moment["mean"])
    ) / float(rolling_moment["scale"])
    vocabulary = tuple(fit_fold["category_encoding"]["vocabulary_h1_only"])
    pi_map = fit_fold["category_encoding"]["pi"]
    sigma_map = fit_fold["category_encoding"]["sigma"]
    pi = np.asarray([float(pi_map[key]) for key in vocabulary], dtype=float)
    sigma = np.asarray([float(sigma_map[key]) for key in vocabulary], dtype=float)
    category_x = id_basis.race_pair_basis(race, pairs, vocabulary, pi, sigma)

    x = np.column_stack((style_x, rolling_z, category_x))
    require(x.shape == (len(pairs), 21 + len(vocabulary)) and np.isfinite(x).all(),
            "evaluation candidate design changed")
    beta = np.asarray(
        [fit_fold["beta_by_basis"][name] for name in core.BASIS_NAMES]
        + [float(fit_fold["gamma_jockey365_pair_sum"])]
        + [float(fit_fold["theta_by_jockey_id"][key]) for key in vocabulary], dtype=float,
    )
    require(len(beta) == x.shape[1] and np.isfinite(beta).all(), "candidate coefficient/schema mismatch")
    eta = logit(p0) + x @ beta
    raw_probability = expit(eta)
    calibration = fit_fold["h2_candidate_platt"]
    calibrated_logits = float(calibration["A"]) + float(calibration["B"]) * eta
    calibrated_probability = expit(calibrated_logits)
    selected = core.pair_choice_from_logits(pairs, eta)
    require(float(calibration["B"]) > 0.0 and selected == core.pair_choice_from_logits(pairs, calibrated_logits),
            "positive-slope H2 calibrator changed pair ranking")
    known_count = np.asarray([sum(int(id_by_number[n] in vocabulary) for n in pair) for pair in pairs], dtype=int)
    category_contribution = category_x @ beta[21:]
    scores = {int(row.horse_number): float(row.score) for row in race.itertuples(index=False)}
    race_id = str(race["race_id"].iloc[0])
    race_date = race["race_date"].iloc[0].date().isoformat()
    evaluation_year = int(race["year"].iloc[0])
    distance = int(race["distance_m"].iloc[0])
    rows = []
    for k, (a, b) in enumerate(pairs):
        rows.append({
            "race_id": race_id, "race_date": race_date, "evaluation_year": evaluation_year,
            "distance_m": distance, "horse_i": int(a), "horse_j": int(b),
            "candidate_score_i": scores[a], "candidate_score_j": scores[b],
            "candidate_p0_check": float(p0[k]), "jockey_id_candidate_eta": float(eta[k]),
            "jockey_id_candidate_raw_probability": float(raw_probability[k]),
            "jockey_id_candidate_calibrated_probability": float(calibrated_probability[k]),
            "selected_jockey_id_candidate": int((a, b) == selected),
            "jockey_id_known_runner_count_pair": int(known_count[k]),
            "jockey_id_category_logit_contribution": float(category_contribution[k]),
            "jockey365_n_i": n_by_number[a], "jockey365_n_j": n_by_number[b],
            "jockey365_d_i": value_by_number[a], "jockey365_d_j": value_by_number[b],
            "jockey365_pair_sum": float(pair_rolling[k]), "jockey365_pair_z": float(rolling_z[k]),
        })
    diagnostics = {
        "race_id": race_id, "race_date": race_date, "evaluation_year": evaluation_year,
        "distance_m": distance,
        "jockey_id_candidate_sum_probability_minus_3": math.fsum(map(float, calibrated_probability)) - 3.0,
        "known_id_runner_count": int(sum(rider_id in vocabulary for rider_id in id_by_number.values())),
    }
    diagnostics["unknown_id_runner_count"] = len(numbers) - diagnostics["known_id_runner_count"]
    return rows, diagnostics


def run_predictions() -> None:
    fit, approval, preflight = validate_fit()
    core = import_module("frozen_direct_pair_core_jockey_id_prediction", DIRECT_CORE)
    pair_predict = import_module("frozen_expanded_pair_predict_jockey_id", EXPANSION / "pair_predict.py")
    jockey_input = import_module("pair_jockey_input_for_id_prediction", INPUT_HELPER)
    id_basis = import_module("pair_jockey_id_basis_for_prediction", ID_BASIS)
    source_lock = json.loads(checked(BASE_SOURCE_LOCK).read_text(encoding="utf-8"))
    require(source_lock.get("status") == "PASS", "frozen expanded source lock is not PASS")
    baseline_fit = json.loads(checked(BASELINE_FIT).read_text(encoding="utf-8"))
    features = pd.read_parquet(
        checked(pair_predict.FEATURES), columns=pair_predict.EVAL_FEATURE_COLUMNS,
        filters=[("year", ">=", 2024), ("year", "<=", 2026)],
    )
    features["race_date"] = pd.to_datetime(features["race_date"], errors="coerce").dt.normalize()
    require(features["race_date"].notna().all() and features["year"].isin(FIT_YEARS).all(),
            "evaluation frozen feature schema/date changed")
    starts = jockey_input.load_starts(include_results=True)
    prediction_rows: list[dict[str, Any]] = []
    diagnostic_rows: list[dict[str, Any]] = []
    score_sources: dict[str, Any] = {}
    for year in FIT_YEARS:
        rows, score_sources[str(year)] = pair_predict.evaluation_runner_scores(year, features, source_lock)
        for key in ("api_record_id", "race_id", "horse_id"):
            rows[key] = rows[key].astype("string")
        rows["race_date"] = pd.to_datetime(rows["race_date"], errors="coerce").dt.normalize()
        event = jockey_input.attach_event_jockey(rows, starts)
        rolling = jockey_input.rolling_features(event, starts)
        event = event.merge(
            rolling[["api_record_id", "jockey365_n", "jockey365_top3", "jockey365_expected_top3",
                     "jockey365_field_relative_top3"]],
            on="api_record_id", how="left", validate="one_to_one",
        )
        require(event["jockey365_field_relative_top3"].notna().all(), f"evaluation rolling feature missing: {year}")
        fit_fold = next(row for row in fit["folds"] if int(row["evaluation_year"]) == year)
        base_fold = next(row for row in baseline_fit["folds"] if int(row["evaluation_year"]) == year)
        count = 0
        for _, race in event.groupby("race_id", sort=True):
            race_rows, diagnostics = predict_race(core, id_basis, race, fit_fold, base_fold)
            prediction_rows.extend(race_rows)
            diagnostic_rows.append(diagnostics)
            count += 1
        require(count == EXPECTED_RACES[year], f"evaluation race count changed: {year}")

    candidate = pd.DataFrame(prediction_rows)
    diagnostics = pd.DataFrame(diagnostic_rows)
    require(len(diagnostics) == 1779 and diagnostics["race_id"].is_unique,
            "candidate race prediction coverage changed")
    require(not candidate.duplicated(KEYS).any(), "candidate pair prediction key duplicated")
    require((candidate.groupby("race_id")["selected_jockey_id_candidate"].sum() == 1).all(),
            "candidate must select exactly one pair per race")
    require(np.isfinite(candidate.select_dtypes(include=[np.number]).to_numpy(dtype=float)).all(),
            "non-finite candidate evaluation prediction")

    old = pd.read_parquet(checked(BASE_PAIR_PREDICTIONS))
    require(len(old) == 76848 and old["race_id"].nunique() == 1779, "frozen comparator pair table shape changed")
    merged = old.merge(candidate, on=KEYS, how="outer", validate="one_to_one", indicator=True,
                       suffixes=("", "_new"))
    require(merged["_merge"].eq("both").all(), "new and frozen candidate pair keys differ")
    require(np.allclose(merged["p0"], merged["candidate_p0_check"], rtol=0.0, atol=1e-15),
            "fixed F1_STYLE6 Top3 prior changed")
    require(np.allclose(merged["score_i"], merged["candidate_score_i"], rtol=0.0, atol=0.0)
            and np.allclose(merged["score_j"], merged["candidate_score_j"], rtol=0.0, atol=0.0),
            "fixed F1_STYLE6 runner score changed")
    merged = merged.drop(columns=["_merge", "candidate_p0_check", "candidate_score_i", "candidate_score_j"])
    merged = merged.sort_values(KEYS, kind="mergesort").reset_index(drop=True)
    old_diagnostics = pd.read_parquet(checked(BASE_RACE_DIAGNOSTICS))
    require(len(old_diagnostics) == 1779 and old_diagnostics["race_id"].is_unique,
            "frozen race diagnostics changed")
    diagnostics = old_diagnostics.merge(
        diagnostics, on=["race_id", "race_date", "evaluation_year", "distance_m"],
        how="outer", validate="one_to_one", indicator=True,
    )
    require(diagnostics["_merge"].eq("both").all(), "candidate and frozen diagnostic race keys differ")
    diagnostics = diagnostics.drop(columns="_merge").sort_values("race_id", kind="mergesort").reset_index(drop=True)
    write_parquet_once(PAIR_PREDICTIONS, merged)
    write_parquet_once(RACE_DIAGNOSTICS, diagnostics)
    receipt = {
        "status": "PASS", "study": STUDY.name,
        "scope": "fixed evaluation pair predictions only; no performance metrics",
        "fit_sha256": sha256(FIT_PATH), "fit_receipt_sha256": sha256(FIT_RECEIPT),
        "approval_sha256": sha256(APPROVAL), "source_preflight_sha256": sha256(PREFLIGHT),
        "design_dry_run_sha256": sha256(DRY_RUN), "prediction_code_sha256": sha256(Path(__file__).resolve()),
        "id_basis_sha256": sha256(ID_BASIS), "fixed_basic_pair_reference_sha256": sha256(BASE_PAIR_PREDICTIONS),
        "frozen_source_lock_sha256": sha256(BASE_SOURCE_LOCK), "frozen_core_sha256": sha256(DIRECT_CORE),
        "evaluation_score_sources": score_sources,
        "prediction_rows": int(len(merged)), "prediction_races": int(merged["race_id"].nunique()),
        "evaluation_dates": int(merged["race_date"].nunique()),
        "selected_candidate_per_race": int(merged.groupby("race_id")["selected_jockey_id_candidate"].sum().eq(1).sum()),
        "unknown_jockey_runner_count": int(diagnostics["unknown_id_runner_count"].sum()),
        "frozen_comparator_columns_preserved": True, "performance_metrics_computed": False,
        "pair_predictions_sha256": sha256(PAIR_PREDICTIONS),
        "race_diagnostics_sha256": sha256(RACE_DIAGNOSTICS),
    }
    write_json_once(PREDICTION_RECEIPT, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "predict":
        raise SystemExit("usage: pair_jockey_id_predict.py predict")
    run_predictions()

