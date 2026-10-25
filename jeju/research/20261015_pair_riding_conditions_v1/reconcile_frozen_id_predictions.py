"""Rebuild frozen ID predictions from saved coefficients and verify exact lineage.

This is a prediction-path reconciliation only: no fitting, target labels, or
performance metrics are used. Historical start results are read solely to
recreate the already-frozen T-2 rolling input.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/Users/kimyongjin/Desktop/horse_racing").resolve()
STUDY = ROOT / "jeju/research/20261015_pair_riding_conditions_v1"
OUT = STUDY / "outputs_prefit_v2"
ID = ROOT / "jeju/research/20261012_pair_jockey_id_v1"
EXPANSION = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
DIRECT = ROOT / "jeju/research/20261011_pair_top3_direct_v1"
BASIC = ROOT / "jeju/research/20261012_pair_jockey_basic_v1"
BASELINE = EXPANSION / "outputs/expanded_h1_fit.json"
SOURCE_LOCK = EXPANSION / "outputs/HISTORICAL_SOURCE_LOCK.json"
SAVED_ID_FIT = ID / "outputs/FIT.json"
SAVED_ID_PREDICTIONS = ID / "outputs/evaluation_pair_predictions.parquet"
SAVED_ID_RECEIPT = ID / "outputs/PREDICTION_RECEIPT.json"
RECONCILIATION = OUT / "SAVED_ID_RECONCILIATION.json"
PREDICT_CODE = ID / "pair_jockey_id_predict.py"
KEYS = ["race_id", "race_date", "evaluation_year", "distance_m", "horse_i", "horse_j"]
COMPARE = {
    "eta": "jockey_id_candidate_eta",
    "raw_probability": "jockey_id_candidate_raw_probability",
    "calibrated_probability": "jockey_id_candidate_calibrated_probability",
}


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            sha.update(block)
    return sha.hexdigest()


def checked(path: Path) -> Path:
    if path.is_symlink():
        raise RuntimeError(f"symlink input rejected: {path}")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(ROOT) or not resolved.is_file():
        raise RuntimeError(f"input outside study workspace: {path}")
    return resolved


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, checked(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import pinned helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run() -> None:
    for path in (OUT,):
        path.mkdir(parents=True, exist_ok=True)
    require(not RECONCILIATION.exists() and not RECONCILIATION.is_symlink(),
            "refusing to overwrite reconciliation receipt")

    old_predict = load_module("frozen_id_predict_for_riding_reconciliation", PREDICT_CODE)
    pair_predict = load_module("frozen_pair_predict_for_riding_reconciliation", EXPANSION / "pair_predict.py")
    jockey_input = load_module("frozen_jockey_input_for_riding_reconciliation", BASIC / "jockey_input.py")
    core = load_module("frozen_pair_core_for_riding_reconciliation", DIRECT / "core.py")
    id_basis = load_module("frozen_id_basis_for_riding_reconciliation", ID / "pair_jockey_id_basis.py")

    old = pd.read_parquet(checked(SAVED_ID_PREDICTIONS))
    fit = json.loads(checked(SAVED_ID_FIT).read_text(encoding="utf-8"))
    receipt = json.loads(checked(SAVED_ID_RECEIPT).read_text(encoding="utf-8"))
    baseline_fit = json.loads(checked(BASELINE).read_text(encoding="utf-8"))
    source_lock = json.loads(checked(SOURCE_LOCK).read_text(encoding="utf-8"))
    require(fit.get("status") == "PASS" and fit.get("h1_fit_count") == 3
            and fit.get("h2_candidate_map_count") == 3, "saved ID fit is not PASS")
    require(receipt.get("status") == "PASS"
            and receipt.get("pair_predictions_sha256") == digest(SAVED_ID_PREDICTIONS),
            "saved ID prediction receipt/hash mismatch")
    require(source_lock.get("status") == "PASS", "frozen historical score source lock is not PASS")
    require(old_predict.FIT_YEARS == (2024, 2025, 2026), "frozen evaluation years changed")

    features = pd.read_parquet(
        checked(pair_predict.FEATURES), columns=pair_predict.EVAL_FEATURE_COLUMNS,
        filters=[("year", ">=", 2024), ("year", "<=", 2026)],
    )
    features["race_date"] = pd.to_datetime(features["race_date"], errors="coerce").dt.normalize()
    require(features["race_date"].notna().all(), "evaluation feature dates are invalid")
    # Historical outcomes are read only to reconstruct frozen T-2 rolling rider inputs.
    starts = jockey_input.load_starts(include_results=True)

    rebuilt: list[dict] = []
    score_sources: dict[str, dict] = {}
    for year in old_predict.FIT_YEARS:
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
        require(event["jockey365_field_relative_top3"].notna().all(),
                f"frozen T-2 rolling input missing for {year}")
        fit_fold = next(row for row in fit["folds"] if int(row["evaluation_year"]) == year)
        baseline_fold = next(row for row in baseline_fit["folds"] if int(row["evaluation_year"]) == year)
        race_count = 0
        for _, race in event.groupby("race_id", sort=True):
            pred_rows, _ = old_predict.predict_race(core, id_basis, race, fit_fold, baseline_fold)
            rebuilt.extend(pred_rows)
            race_count += 1
        require(race_count == old_predict.EXPECTED_RACES[year], f"evaluation race count changed: {year}")

    current = pd.DataFrame(rebuilt)
    require(len(current) == 76848 and current["race_id"].nunique() == 1779,
            "rebuilt frozen ID prediction coverage changed")
    require(not current.duplicated(KEYS).any() and not old.duplicated(KEYS).any(),
            "duplicate pair key in saved/rebuilt ID predictions")
    compare_columns = [*COMPARE.values(), "selected_jockey_id_candidate"]
    require(set(KEYS + compare_columns).issubset(old.columns), "saved prediction columns changed")
    check = old[KEYS + compare_columns].merge(
        current[KEYS + compare_columns], on=KEYS, how="outer", suffixes=("_saved", "_rebuilt"),
        validate="one_to_one", indicator=True,
    )
    require(check["_merge"].eq("both").all(), "saved/rebuilt ID pair key coverage differs")
    maxima = {}
    for column in COMPARE.values():
        left = check[f"{column}_saved"].to_numpy(dtype=np.float64)
        right = check[f"{column}_rebuilt"].to_numpy(dtype=np.float64)
        require(np.isfinite(left).all() and np.isfinite(right).all(), f"non-finite ID output: {column}")
        maxima[column] = float(np.max(np.abs(left - right)))
        require(maxima[column] <= 1e-12, f"saved ID reconstruction exceeds tolerance: {column}")
    saved_selection = check["selected_jockey_id_candidate_saved"].to_numpy(dtype=np.int64)
    rebuilt_selection = check["selected_jockey_id_candidate_rebuilt"].to_numpy(dtype=np.int64)
    selection_mismatches = int(np.count_nonzero(saved_selection != rebuilt_selection))
    require(selection_mismatches == 0 and int(saved_selection.sum()) == 1779,
            "saved/rebuilt ID selected pair differs")

    result = {
        "status": "PASS",
        "scope": "saved ID 60-column design, offset and H2 Platt reconstruction only; no fitting or evaluation metrics",
        "reconstruction": "recreated frozen F1_STYLE6 score rows, frozen T-2 current rider365, 20 standardized style bases, rolling basis, H1-only ID encoding, saved 60 coefficients, saved H2 Platt A/B, and logit(p0) offset via the frozen prediction implementation",
        "historical_results_read": True,
        "target_evaluation_outcomes_used": False,
        "pair_rows": int(len(current)),
        "races": int(current["race_id"].nunique()),
        "evaluation_dates": int(current["race_date"].nunique()),
        "selected_pairs_reconstructed": int(rebuilt_selection.sum()),
        "selection_mismatches": selection_mismatches,
        "maximum_absolute_difference": maxima,
        "tolerance": 1e-12,
        "fit_sha256": digest(SAVED_ID_FIT),
        "saved_prediction_sha256": digest(SAVED_ID_PREDICTIONS),
        "saved_prediction_receipt_sha256": digest(SAVED_ID_RECEIPT),
        "frozen_predict_code_sha256": digest(PREDICT_CODE),
        "score_sources": score_sources,
        "reconciliation_code_sha256": digest(Path(__file__).resolve()),
    }
    with RECONCILIATION.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
