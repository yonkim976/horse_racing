"""Independent, label-free replay of a locked Top5 choice artifact.

Run only after ROOT_SELECTION_APPROVAL.json and the main choice receipt exist.
This script intentionally does not import the fit, selection, or outcome code.
It reads only explicit non-outcome columns from the frozen sources and writes
compact replay artifacts into this independent-review directory.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
REVIEW = Path(__file__).resolve().parent
MAIN = ROOT / "jeju/research/20261025_top5_direct_learning_v1"
OUT = MAIN / "outputs"

PLAN_PATH = MAIN / "PLAN.md"
SOURCE_AUDIT_PATH = MAIN / "SOURCE_AUDIT.md"
SELECT_CODE_PATH = MAIN / "select_sets.py"
FIT_RECEIPT_PATH = OUT / "FIT_RECEIPT.json"
SELECTION_APPROVAL_PATH = OUT / "ROOT_SELECTION_APPROVAL.json"
CHOICES_PATH = OUT / "candidate_choices.jsonl"
CHOICES_RECEIPT_PATH = OUT / "CHOICES_RECEIPT.json"

PLAN_SHA256 = "c5683a8716e62094a7856cadfd44119dfac3c6ac3edd9f08652a951e42297012"
SOURCE_AUDIT_SHA256 = "c70596688c22c97deb7fa48cba21ef6e5442ea29e1901f790277c1f03fbe3fbd"
ROOT_AUDIT_SHA256 = "b263703aae9e7d5eca2bda394d4c20de67144bcaf78e959f5add9efffc8310f8"
FEATURES_REL = "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
FEATURES_SHA256 = "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f"
BASELINE_REL = "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet"
BASELINE_SHA256 = "c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1"
EVAL_YEARS = (2024, 2025, 2026)
PRIMARY_DISTANCES = {900, 1000, 1110, 1200}
TIE_TOLERANCE = 1e-12
OBJECTIVE_ID = "partial_event_gibbs_nll_additive_selection_head_v1"
MODEL_NAMES = tuple(f"model_{year}.json" for year in EVAL_YEARS)

EVAL_SCORE_SOURCES: dict[int, tuple[str, str]] = {
    2024: (
        "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/evaluation_scores.parquet",
        "b9541396c81e307f99f6c8eff4441594b181b9a0398120a4fa5f529add55cd60",
    ),
    2025: (
        "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/evaluation_scores.parquet",
        "45247f00f286197067957d25ee46e0594f2ef0d26089c6b6081592272651eb12",
    ),
    2026: (
        "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/evaluation_scores.parquet",
        "0ccae2475fc1ea87ddf62b054572961ab32fed26b332070907853ebbd412989a",
    ),
}

BASELINE_COLUMNS = [
    "api_record_id",
    "race_id",
    "race_date",
    "year",
    "distance_m",
    "horse_id",
    "horse_number",
    "field_n",
    "variant",
    "score",
]
FEATURE_COLUMNS = [
    "api_record_id",
    "race_id",
    "race_date",
    "year",
    "horse_id",
    "horse_number",
    "field_n",
    "observed_starts",
    "same_starts",
    "same_valid_times",
    "mean5_rank_fraction",
    "hist_s1f_relpos_mean5",
    "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5",
    "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5",
    "hist_c4_to_g1f_pair_n",
]
RAW_INPUT_NAMES = [
    "log_observed_starts",
    "log_same_starts",
    "log_same_valid_times",
    "mean5_rank_fraction",
    "mean5_rank_fraction_missing",
    "hist_s1f_relpos_mean5",
    "log_hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5",
    "log_hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5",
    "log_hist_c4_to_g1f_pair_n",
]
STYLE_PAIRS = (
    ("hist_s1f_relpos_mean5", "hist_s1f_relpos_n"),
    ("hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n"),
    ("hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n"),
)
LOG_COUNT_INPUTS = (
    "observed_starts",
    "same_starts",
    "same_valid_times",
    "hist_s1f_relpos_n",
    "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_pair_n",
)


class ReplayError(RuntimeError):
    """Raised when a frozen source or locked choice artifact fails replay."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReplayError(message)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def source_path(relative: str, expected_hash: str) -> Path:
    path = ROOT / relative
    require(not path.is_symlink(), f"source symlink is not allowed: {relative}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"source escaped workspace: {relative}")
    require(digest(resolved) == expected_hash, f"source hash mismatch: {relative}")
    return resolved


def read_json(path: Path, name: str) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"required locked artifact missing or unsafe: {name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON root is not an object: {name}")
    return value


def jsonl_rows(path: Path) -> list[dict[str, Any]]:
    require(path.is_file() and not path.is_symlink(), "locked candidate choices are missing or unsafe")
    result: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReplayError(f"invalid choice JSONL row {line_no}") from exc
            require(isinstance(item, dict), f"choice row is not an object: {line_no}")
            result.append(item)
    return result


def validate_locks() -> tuple[dict[int, dict[str, Any]], dict[str, str], dict[str, Any], dict[str, Any]]:
    require(digest(PLAN_PATH) == PLAN_SHA256, "plan changed since review")
    require(digest(SOURCE_AUDIT_PATH) == SOURCE_AUDIT_SHA256, "source audit changed since review")
    fit_receipt = read_json(FIT_RECEIPT_PATH, "FIT_RECEIPT.json")
    require(fit_receipt.get("status") == "PASS" and fit_receipt.get("fit_count") == 3, "fit receipt is not a three-fold PASS")
    require(fit_receipt.get("evaluation_outcomes_read") is False, "fit receipt reports evaluation outcome access")
    require(fit_receipt.get("outcome_metrics_computed") is False, "fit receipt reports evaluation metrics")
    require(fit_receipt.get("plan_sha256") == PLAN_SHA256, "fit receipt plan hash mismatch")
    require(fit_receipt.get("source_audit_sha256") == SOURCE_AUDIT_SHA256, "fit receipt source audit hash mismatch")
    require(fit_receipt.get("source_audit_root_sha256") == ROOT_AUDIT_SHA256, "fit receipt root audit hash mismatch")
    require(fit_receipt.get("fit_code_sha256") == "257542455ad60ba8299f0952ee3976cc1a6916a432b3a1ecdbbf9420241e94a3", "fit code hash mismatch")
    fit_receipt_sha = digest(FIT_RECEIPT_PATH)

    models: dict[int, dict[str, Any]] = {}
    model_hashes: dict[str, str] = {}
    model_artifacts = fit_receipt.get("model_artifacts")
    require(isinstance(model_artifacts, dict), "fit receipt has no model artifact inventory")
    for year, name in zip(EVAL_YEARS, MODEL_NAMES, strict=True):
        artifact = model_artifacts.get(name)
        require(isinstance(artifact, dict), f"fit receipt missing model inventory: {name}")
        path = OUT / name
        require(path.is_file() and not path.is_symlink(), f"model missing or unsafe: {name}")
        require(digest(path) == artifact.get("sha256"), f"model hash mismatch: {name}")
        require(path.stat().st_size == int(artifact.get("bytes", -1)), f"model byte count mismatch: {name}")
        model = read_json(path, name)
        require(model.get("evaluation_year") == year, f"model evaluation year mismatch: {name}")
        require(model.get("objective_id") == OBJECTIVE_ID, f"model objective mismatch: {name}")
        require(model.get("feature_names") == RAW_INPUT_NAMES, f"model input order mismatch: {name}")
        require(model.get("score_prior", {}).get("fixed_coefficient") == 1.0, f"model fixed score coefficient mismatch: {name}")
        means = np.asarray(model.get("feature_means"), dtype=np.float64)
        scales = np.asarray(model.get("feature_scales"), dtype=np.float64)
        beta = np.asarray(model.get("beta"), dtype=np.float64)
        require(means.shape == scales.shape == beta.shape == (len(RAW_INPUT_NAMES),), f"model width mismatch: {name}")
        require(np.isfinite(means).all() and np.isfinite(scales).all() and (scales > 0).all() and np.isfinite(beta).all(), f"model has invalid coefficients/scaler: {name}")
        fold = fit_receipt.get("folds", {}).get(str(year), {})
        validation = fold.get("training_label_validation", {})
        expected_train_years = list(range(2019, year))
        require(fold.get("status") == "PASS", f"fit fold not PASS: {year}")
        require(validation.get("status") == "PASS", f"training label validation not PASS: {year}")
        require(validation.get("label_years") == expected_train_years, f"training label years mismatch: {year}")
        require(validation.get("evaluation_year_labels_accessed") is False, f"fit receipt says evaluation labels were accessed: {year}")
        require(fold.get("evaluation_labels_read") is False and fold.get("outcome_metrics_computed") is False, f"fit receipt reports evaluation-label use: {year}")
        models[year] = model
        model_hashes[name] = digest(path)

    approval = read_json(SELECTION_APPROVAL_PATH, "ROOT_SELECTION_APPROVAL.json")
    require(approval.get("status") == "approved", "root selection approval is absent or not approved")
    require(approval.get("plan_sha256") == PLAN_SHA256, "selection approval plan hash mismatch")
    require(approval.get("source_audit_sha256") == SOURCE_AUDIT_SHA256, "selection approval source audit hash mismatch")
    require(approval.get("source_audit_root_sha256") == ROOT_AUDIT_SHA256, "selection approval root audit hash mismatch")
    require(approval.get("fit_receipt_sha256") == fit_receipt_sha, "selection approval fit receipt hash mismatch")
    require(approval.get("model_sha256s") == model_hashes, "selection approval model hashes mismatch")
    require(approval.get("selection_code_sha256") == digest(SELECT_CODE_PATH), "selection approval code hash is stale")

    choice_receipt = read_json(CHOICES_RECEIPT_PATH, "CHOICES_RECEIPT.json")
    require(choice_receipt.get("status") == "PASS", "choice receipt is not PASS")
    require(choice_receipt.get("outcome_labels_read") is False, "choice receipt reports outcome label access")
    require(choice_receipt.get("selection_code_sha256") == digest(SELECT_CODE_PATH), "choice receipt code hash is stale")
    require(choice_receipt.get("root_selection_approval_sha256") == digest(SELECTION_APPROVAL_PATH), "choice receipt references another selection approval")
    require(choice_receipt.get("fit_receipt_sha256") == fit_receipt_sha, "choice receipt references another fit receipt")
    require(choice_receipt.get("plan_sha256") == PLAN_SHA256 and choice_receipt.get("source_audit_sha256") == SOURCE_AUDIT_SHA256, "choice receipt source lock mismatch")
    require(choice_receipt.get("models") == model_hashes, "choice receipt model hashes mismatch")
    require(choice_receipt.get("choices_file") == "candidate_choices.jsonl", "choice receipt references another choices file")
    require(choice_receipt.get("selection_columns_allowlist") == BASELINE_COLUMNS, "selection allowlist in receipt changed")
    require(choice_receipt.get("tie_rule") == "max energy; within 1e-12 tie choose greatest raw-score Top5 overlap, then lexicographically smallest horse-number tuple", "choice tie rule in receipt changed")
    require(CHOICES_PATH.stat().st_size == int(choice_receipt.get("choices_bytes", -1)), "choice byte count differs from receipt")
    require(digest(CHOICES_PATH) == choice_receipt.get("choices_sha256"), "choice artifact hash differs from receipt")
    return models, model_hashes, approval, choice_receipt


def read_frozen_inputs() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    baseline_path = source_path(BASELINE_REL, BASELINE_SHA256)
    baseline = pd.read_parquet(baseline_path, columns=BASELINE_COLUMNS)
    require(baseline.columns.tolist() == BASELINE_COLUMNS, "baseline non-outcome allowlist/schema changed")
    require(len(baseline) == 17412 and baseline["api_record_id"].is_unique, "baseline runner key inventory changed")
    require(set(baseline["variant"].astype(str)) == {"F1_STYLE6"}, "baseline variant is not fixed F1_STYLE6")
    require(set(baseline["year"].astype(int).unique()) == set(EVAL_YEARS), "baseline year roster changed")
    require(np.isfinite(baseline["score"].to_numpy(dtype=np.float64)).all(), "baseline score contains nonfinite values")

    score_checks: dict[str, Any] = {}
    for year, (relative, expected_hash) in EVAL_SCORE_SOURCES.items():
        saved_path = source_path(relative, expected_hash)
        saved = pd.read_parquet(saved_path, columns=["api_record_id", "score"])
        base = baseline.loc[baseline["year"].astype(int).eq(year), ["api_record_id", "score"]]
        require(len(saved) == len(base) and saved["api_record_id"].is_unique, f"saved score coverage changed: {year}")
        paired = base.merge(saved, on="api_record_id", how="outer", suffixes=("_base", "_saved"), indicator=True, validate="one_to_one")
        require(paired["_merge"].eq("both").all(), f"saved score key mismatch: {year}")
        require(np.array_equal(paired["score_base"].to_numpy(dtype=np.float64), paired["score_saved"].to_numpy(dtype=np.float64)), f"frozen score parity failed: {year}")
        score_checks[str(year)] = {
            "rows": len(base),
            "score_path": relative,
            "score_sha256": expected_hash,
            "exact_score_parity": True,
        }

    feature_path = source_path(FEATURES_REL, FEATURES_SHA256)
    features = pd.read_parquet(feature_path, columns=FEATURE_COLUMNS)
    require(features.columns.tolist() == FEATURE_COLUMNS, "feature allowlist/schema changed")
    require(len(features) == 52155 and features["api_record_id"].is_unique, "feature runner key inventory changed")
    feature_years = pd.to_numeric(features["year"], errors="coerce")
    require(feature_years.notna().all(), "feature year metadata invalid")
    features["year"] = feature_years.astype(int)
    eval_features = features.loc[features["year"].isin(EVAL_YEARS)].copy()
    require(len(eval_features) == 17412, "evaluation feature row count changed")
    require(set(eval_features["api_record_id"].astype(int)) == set(baseline["api_record_id"].astype(int)), "evaluation baseline/feature keys differ")

    # Distance is roster metadata stored separately from the model input allowlist.
    distance = pd.read_parquet(feature_path, columns=["api_record_id", "year", "distance_m"])
    require(len(distance) == 52155 and distance["api_record_id"].is_unique, "distance metadata key inventory changed")
    require(np.isfinite(distance["distance_m"].to_numpy(dtype=np.float64)).all(), "distance metadata contains nonfinite values")
    eval_distance = distance.loc[pd.to_numeric(distance["year"], errors="coerce").astype(int).isin(EVAL_YEARS)]
    merged_distance = baseline[["api_record_id", "distance_m"]].merge(
        eval_distance[["api_record_id", "distance_m"]], on="api_record_id", how="outer",
        suffixes=("_base", "_feature"), indicator=True, validate="one_to_one",
    )
    require(merged_distance["_merge"].eq("both").all(), "evaluation distance metadata keys differ")
    require(np.array_equal(merged_distance["distance_m_base"].to_numpy(dtype=np.float64), merged_distance["distance_m_feature"].to_numpy(dtype=np.float64)), "evaluation distance metadata differs")

    feature_meta = ["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number", "field_n"]
    paired_meta = baseline.merge(eval_features[feature_meta], on="api_record_id", how="inner", suffixes=("_base", "_feature"), validate="one_to_one", sort=False)
    require(len(paired_meta) == len(baseline), "metadata merge dropped rows")
    for col in ("race_id", "race_date", "year", "horse_id", "horse_number", "field_n"):
        require(paired_meta[f"{col}_base"].astype(str).equals(paired_meta[f"{col}_feature"].astype(str)), f"baseline/feature metadata differs: {col}")
    eval_features = eval_features.merge(baseline[["api_record_id", "score", "distance_m"]], on="api_record_id", how="inner", validate="one_to_one", sort=False)
    require(len(eval_features) == 17412, "evaluation input join dropped rows")
    return baseline, eval_features, score_checks


def raw_inputs(frame: pd.DataFrame) -> np.ndarray:
    values: dict[str, np.ndarray] = {}
    for col in LOG_COUNT_INPUTS:
        raw = pd.to_numeric(frame[col], errors="raise").to_numpy(dtype=np.float64)
        require(np.isfinite(raw).all() and (raw >= 0).all(), f"invalid count input: {col}")
        if col.startswith("hist_"):
            require(np.equal(raw, np.floor(raw)).all() and (raw <= 5).all(), f"invalid 0..5 style support: {col}")
        else:
            require(np.equal(raw, np.floor(raw)).all(), f"noninteger count input: {col}")
        values[f"log_{col}"] = np.log1p(raw)

    rank_series = pd.to_numeric(frame["mean5_rank_fraction"], errors="raise")
    rank = rank_series.to_numpy(dtype=np.float64, na_value=np.nan)
    rank_missing = rank_series.isna().to_numpy()
    require(np.isfinite(rank[~rank_missing]).all(), "mean5 rank has infinite values")
    values["mean5_rank_fraction"] = rank
    values["mean5_rank_fraction_missing"] = rank_missing.astype(np.float64)

    for mean_col, support_col in STYLE_PAIRS:
        support = pd.to_numeric(frame[support_col], errors="raise").to_numpy(dtype=np.float64)
        mean_series = pd.to_numeric(frame[mean_col], errors="raise")
        mean = mean_series.to_numpy(dtype=np.float64, na_value=np.nan)
        missing = mean_series.isna().to_numpy()
        require(np.isfinite(support).all() and np.equal(support, np.floor(support)).all() and (support >= 0).all() and (support <= 5).all(), f"invalid support count: {support_col}")
        require(np.isfinite(mean[~missing]).all(), f"style mean has infinite values: {mean_col}")
        require(np.array_equal(missing, support == 0), f"style mean/support NULL rule changed: {mean_col}")
        values[mean_col] = mean
        values[f"log_{support_col}"] = np.log1p(support)

    require(set(values) == set(RAW_INPUT_NAMES), "raw feature list changed")
    result = np.column_stack([values[name] for name in RAW_INPUT_NAMES]).astype(np.float64, copy=False)
    require(result.shape == (len(frame), len(RAW_INPUT_NAMES)) and not np.isinf(result).any(), "raw feature matrix is invalid")
    return result


def apply_training_scaler(raw: np.ndarray, model: dict[str, Any]) -> np.ndarray:
    mean = np.asarray(model["feature_means"], dtype=np.float64)
    scale = np.asarray(model["feature_scales"], dtype=np.float64)
    transformed = np.zeros_like(raw, dtype=np.float64)
    for j in range(raw.shape[1]):
        finite = np.isfinite(raw[:, j])
        transformed[finite, j] = (raw[finite, j] - mean[j]) / scale[j]
        transformed[~finite, j] = 0.0
    require(np.isfinite(transformed).all(), "scaled evaluation feature has nonfinite values")
    return transformed


def race_zscore(scores: np.ndarray) -> np.ndarray:
    arr = np.asarray(scores, dtype=np.float64)
    require(np.isfinite(arr).all(), "race score has nonfinite values")
    sd = float(arr.std(ddof=0))
    if sd == 0:
        return np.zeros_like(arr)
    return (arr - float(arr.mean())) / sd


def replay_one_race(rows: pd.DataFrame, model: dict[str, Any], x_lookup: dict[int, np.ndarray]) -> tuple[dict[str, Any], int, bool]:
    # Canonical runner order ensures inputs and lexicographic tie order are stable.
    race = rows.sort_values("horse_number", kind="stable").reset_index(drop=True)
    n = len(race)
    require(n >= 5 and n == int(race["field_n"].iloc[0]) and (race["field_n"].astype(int) == n).all(), f"incomplete race roster: {race['race_id'].iloc[0]}")
    require(race["api_record_id"].is_unique and race["horse_id"].is_unique and race["horse_number"].is_unique, f"duplicate runner in race: {race['race_id'].iloc[0]}")
    numbers = race["horse_number"].to_numpy(dtype=np.int64)
    ids = race["horse_id"].astype(str).to_numpy()
    score = race["score"].to_numpy(dtype=np.float64)
    z = race_zscore(score)
    x = np.vstack([x_lookup[int(key)] for key in race["api_record_id"].to_numpy(dtype=np.int64)])
    beta = np.asarray(model["beta"], dtype=np.float64)
    runner_utility = z + x @ beta

    baseline_indices = sorted(range(n), key=lambda i: (-float(score[i]), int(numbers[i])))[:5]
    baseline_members = frozenset(baseline_indices)
    baseline_ids = [str(ids[i]) for i in baseline_indices]
    baseline_numbers = [int(numbers[i]) for i in baseline_indices]

    combinations = np.asarray(list(itertools.combinations(range(n), 5)), dtype=np.int16)
    expected_count = math.comb(n, 5)
    require(combinations.shape == (expected_count, 5), f"five-set enumeration is incomplete: {race['race_id'].iloc[0]}")
    prior_energy = z[combinations].sum(axis=1, dtype=np.float64)
    residual_energy = x[combinations].sum(axis=1, dtype=np.float64) @ beta
    energy = prior_energy + residual_energy
    require(np.isfinite(energy).all(), f"candidate energy is nonfinite: {race['race_id'].iloc[0]}")

    prior_max = float(prior_energy.max())
    prior_tied = np.flatnonzero(np.abs(prior_energy - prior_max) <= TIE_TOLERANCE)
    prior_choice = min(
        prior_tied,
        key=lambda k: (
            -len(set(combinations[k].tolist()) & baseline_members),
            tuple(int(numbers[i]) for i in combinations[k]),
        ),
    )
    require(frozenset(combinations[prior_choice].tolist()) == baseline_members, f"zero-beta Top5 identity failed: {race['race_id'].iloc[0]}")

    maximum = float(energy.max())
    tied = np.flatnonzero(np.abs(energy - maximum) <= TIE_TOLERANCE)
    selected = min(
        tied,
        key=lambda k: (
            -len(set(combinations[k].tolist()) & baseline_members),
            tuple(int(numbers[i]) for i in combinations[k]),
        ),
    )
    members = [int(i) for i in combinations[selected]]
    chosen_ids = [str(ids[i]) for i in members]
    chosen_numbers = [int(numbers[i]) for i in members]
    require(len(set(chosen_ids)) == len(set(chosen_numbers)) == 5, f"selected choice is not five unique runners: {race['race_id'].iloc[0]}")

    # Additive energy identity: every five-set energy is the sum of its runner utilities.
    # Check selected energy and utility against the mathematically maximal five-runner sum.
    optimal_runner_sum = float(np.sort(runner_utility)[-5:].sum(dtype=np.float64))
    chosen_runner_sum = float(runner_utility[members].sum(dtype=np.float64))
    require(abs(chosen_runner_sum - optimal_runner_sum) <= 5e-12, f"additive Top5 identity failed: {race['race_id'].iloc[0]}")

    row = {
        "race_id": str(race["race_id"].iloc[0]),
        "race_date": str(race["race_date"].iloc[0]),
        "year": int(race["year"].iloc[0]),
        "distance_m": float(race["distance_m"].iloc[0]),
        "field_n": n,
        "baseline_top5_horse_ids": baseline_ids,
        "baseline_top5_horse_numbers": baseline_numbers,
        "selector_top5_horse_ids": chosen_ids,
        "selector_top5_horse_numbers": chosen_numbers,
        "baseline_energy": float(prior_energy[prior_choice]),
        "selector_energy": float(energy[selected]),
        "candidate_set_count": expected_count,
        "zero_beta_matches_baseline": True,
    }
    changed = set(chosen_ids) != set(baseline_ids)
    return row, expected_count, changed


def load_choices_and_replay(models: dict[int, dict[str, Any]], choice_receipt: dict[str, Any], score_checks: dict[str, Any], rows: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    locked = jsonl_rows(CHOICES_PATH)
    require(len(locked) == 1779, "locked choice count is not 1,779")
    require(len({str(row.get("race_id")) for row in locked}) == len(locked), "locked choice race IDs are not unique")
    raw = raw_inputs(rows)

    replayed: list[dict[str, Any]] = []
    candidate_total = 0
    changed_full = 0
    changed_primary = 0
    reversed_match_count = 0
    additive_identity_count = 0
    for year in EVAL_YEARS:
        year_mask = rows["year"].astype(int).eq(year).to_numpy()
        year_frame = rows.loc[year_mask].copy()
        scaled = apply_training_scaler(raw[year_mask], models[year])
        lookup = {int(key): scaled[i] for i, key in enumerate(year_frame["api_record_id"].to_numpy(dtype=np.int64))}
        for _, group in year_frame.groupby("race_id", sort=True):
            result, n_sets, changed = replay_one_race(group, models[year], lookup)
            replayed.append(result)
            candidate_total += n_sets
            changed_full += int(changed)
            changed_primary += int(changed and int(result["distance_m"]) in PRIMARY_DISTANCES)
            additive_identity_count += 1

            # Row-order invariance: reverse original input rows, then replay through canonical sort.
            reversed_result, _, _ = replay_one_race(group.iloc[::-1].copy(), models[year], lookup)
            require(reversed_result == result, f"choice changes under reversed row order: {result['race_id']}")
            reversed_match_count += 1

    replayed.sort(key=lambda row: (row["race_date"], row["race_id"]))
    require(len(replayed) == 1779 and len({row["race_id"] for row in replayed}) == 1779, "replay race inventory is not 1,779 unique races")
    require(sum(int(row["distance_m"]) in PRIMARY_DISTANCES for row in replayed) == 1503, "replayed primary cohort is not 1,503 races")
    require(candidate_total == int(choice_receipt.get("candidate_sets_enumerated", -1)), "all-five-set candidate count differs from receipt")
    require(changed_full == int(choice_receipt.get("full_changed_choices", -1)), "full changed-choice count differs from receipt")
    require(changed_primary == int(choice_receipt.get("primary_changed_choices", -1)), "primary changed-choice count differs from receipt")
    require(choice_receipt.get("candidate_choices_created") == 1779 and choice_receipt.get("primary_races") == 1503 and choice_receipt.get("full_races") == 1779, "choice receipt population counts changed")
    require(choice_receipt.get("zero_beta_negative_control_matches_baseline_all_races") is True, "choice receipt does not report a passing zero-beta control")
    require(choice_receipt.get("evaluation_score_parity") == score_checks, "choice receipt score-parity metadata differs")

    keys = (
        "race_id", "race_date", "year", "distance_m", "field_n",
        "baseline_top5_horse_ids", "baseline_top5_horse_numbers",
        "selector_top5_horse_ids", "selector_top5_horse_numbers",
        "candidate_set_count", "zero_beta_matches_baseline",
    )
    for i, (saved, replay) in enumerate(zip(locked, replayed, strict=True), 1):
        for key in keys:
            require(saved.get(key) == replay.get(key), f"choice replay mismatch at row {i}, {key}: {replay['race_id']}")
        for key in ("baseline_energy", "selector_energy"):
            saved_value = float(saved.get(key))
            replay_value = float(replay[key])
            require(math.isfinite(saved_value) and abs(saved_value - replay_value) <= 2e-12, f"energy replay mismatch at row {i}, {key}: {replay['race_id']}")
    metrics = {
        "replayed_races": len(replayed),
        "replayed_primary_races": 1503,
        "candidate_sets_enumerated": candidate_total,
        "zero_beta_identity_passes": len(replayed),
        "row_reversal_identity_passes": reversed_match_count,
        "additive_argmax_identity_passes": additive_identity_count,
        "primary_changed_choices": changed_primary,
        "full_changed_choices": changed_full,
        "locked_choice_rows_exact_match": len(replayed),
    }
    return replayed, metrics


def write_once(path: Path, payload: str) -> None:
    require(path.parent.resolve(strict=True) == REVIEW.resolve(strict=True), "review output path escaped owned review directory")
    require(not path.exists() and not path.is_symlink(), f"refusing to overwrite review artifact: {path.name}")
    with path.open("x", encoding="utf-8") as stream:
        stream.write(payload)


def main() -> None:
    models, model_hashes, approval, choice_receipt = validate_locks()
    initial_fit_sha = digest(FIT_RECEIPT_PATH)
    initial_approval_sha = digest(SELECTION_APPROVAL_PATH)
    initial_choices_sha = digest(CHOICES_PATH)
    initial_choice_receipt_sha = digest(CHOICES_RECEIPT_PATH)
    baseline, eval_inputs, score_checks = read_frozen_inputs()
    replayed, metrics = load_choices_and_replay(models, choice_receipt, score_checks, eval_inputs)

    # Recheck hashes after reading all source and locked artifacts.
    require(digest(FIT_RECEIPT_PATH) == initial_fit_sha, "fit receipt changed during replay")
    require(digest(SELECTION_APPROVAL_PATH) == initial_approval_sha, "selection approval changed during replay")
    require(digest(CHOICES_PATH) == initial_choices_sha, "choice file changed during replay")
    require(digest(CHOICES_RECEIPT_PATH) == initial_choice_receipt_sha, "choice receipt changed during replay")

    ledger_path = REVIEW / "REPLAYED_LOCKED_CHOICES.jsonl"
    ledger_text = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n" for row in replayed)
    write_once(ledger_path, ledger_text)
    receipt = {
        "status": "PASS",
        "review": "independent label-free replay of exact five-set selector choices",
        "outcome_labels_read": False,
        "outcome_metrics_computed": False,
        "main_plan_sha256": PLAN_SHA256,
        "main_source_audit_sha256": SOURCE_AUDIT_SHA256,
        "main_selection_code_sha256": digest(SELECT_CODE_PATH),
        "main_fit_receipt_sha256": digest(FIT_RECEIPT_PATH),
        "main_model_sha256s": model_hashes,
        "root_selection_approval_sha256": digest(SELECTION_APPROVAL_PATH),
        "main_choices_sha256": digest(CHOICES_PATH),
        "main_choices_receipt_sha256": digest(CHOICES_RECEIPT_PATH),
        "source_hashes": {
            BASELINE_REL: BASELINE_SHA256,
            FEATURES_REL: FEATURES_SHA256,
            **{path: sha for path, sha in ((v[0], v[1]) for v in EVAL_SCORE_SOURCES.values())},
        },
        "input_allowlists": {
            "baseline": BASELINE_COLUMNS,
            "features": FEATURE_COLUMNS,
            "distance_metadata": ["api_record_id", "year", "distance_m"],
            "evaluation_raw_scores": ["api_record_id", "score"],
        },
        "checks": metrics,
        "score_parity": score_checks,
        "choice_file_sha256": digest(ledger_path),
        "choice_file_bytes": ledger_path.stat().st_size,
        "selection_approval_status": approval.get("status"),
        "main_choice_receipt_status": choice_receipt.get("status"),
        "baseline_runner_rows": len(baseline),
    }
    write_once(REVIEW / "REPLAYED_CHOICES_RECEIPT.json", json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"status": "PASS", **metrics}, ensure_ascii=False))


if __name__ == "__main__":
    main()
