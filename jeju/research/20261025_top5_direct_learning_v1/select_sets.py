"""Create the hash-locked, label-free deterministic Top5 choices."""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import fit_selector as fit


BASELINE_REL = "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet"
BASELINE_SHA256 = "c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1"
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
SELECTION_APPROVAL = fit.OUT / "ROOT_SELECTION_APPROVAL.json"
FIT_RECEIPT_PATH = fit.OUT / "FIT_RECEIPT.json"
CHOICES_PATH_NAME = "candidate_choices.jsonl"
CHOICES_RECEIPT_NAME = "CHOICES_RECEIPT.json"
TIE_TOLERANCE = 1e-12
PRIMARY_DISTANCES = {900, 1000, 1110, 1200}

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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise fit.FitError(message)


def read_json(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"required receipt missing or unsafe: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def require_selection_approval(fit_receipt_sha: str, model_hashes: dict[str, str]) -> tuple[dict[str, Any], str]:
    approval = read_json(SELECTION_APPROVAL)
    require(approval.get("status") == "approved", "root selection approval status is not approved")
    require(approval.get("plan_sha256") == fit.sha256(fit.PLAN_PATH), "selection approval plan hash is stale")
    require(approval.get("source_audit_sha256") == fit.sha256(fit.SOURCE_AUDIT_PATH), "selection approval source hash is stale")
    require(approval.get("fit_receipt_sha256") == fit_receipt_sha, "selection approval references a different fit receipt")
    require(approval.get("model_sha256s") == model_hashes, "selection approval model hashes do not match")
    require(approval.get("selection_code_sha256") == fit.sha256(Path(__file__).resolve()), "selection approval code hash is stale")
    return approval, fit.sha256(SELECTION_APPROVAL)


def load_models_and_receipt() -> tuple[dict[int, dict[str, Any]], dict[str, Any], dict[str, str]]:
    receipt = read_json(FIT_RECEIPT_PATH)
    require(receipt.get("status") == "PASS" and receipt.get("fit_count") == 3, "fit receipt is not a complete three-fold fit")
    require(receipt.get("evaluation_outcomes_read") is False, "fit stage reports evaluation outcomes read")
    models: dict[int, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    for year in fit.EVAL_YEARS:
        name = f"model_{year}.json"
        path = fit.source_path(f"jeju/research/20261025_top5_direct_learning_v1/outputs/{name}", receipt["model_artifacts"][name]["sha256"])
        require(path.stat().st_size == int(receipt["model_artifacts"][name]["bytes"]), f"model size changed: {name}")
        model = json.loads(path.read_text(encoding="utf-8"))
        require(model.get("objective_id") == fit.OBJECTIVE_ID, f"model objective mismatch: {name}")
        require(model.get("feature_names") == list(fit.RAW_INPUT_NAMES), f"model input basis mismatch: {name}")
        require(len(model.get("beta", [])) == len(fit.RAW_INPUT_NAMES), f"model beta width mismatch: {name}")
        require(np.isfinite(np.asarray(model["beta"], dtype=np.float64)).all(), f"nonfinite beta: {name}")
        models[year] = model
        hashes[name] = fit.sha256(path)
    return models, receipt, hashes


def read_baseline_allowlist() -> pd.DataFrame:
    path = fit.source_path(BASELINE_REL, BASELINE_SHA256)
    frame = pd.read_parquet(path, columns=BASELINE_COLUMNS)
    require(frame.columns.tolist() == BASELINE_COLUMNS, "baseline allowlist/schema changed")
    require(len(frame) == 17412 and frame["api_record_id"].is_unique, "baseline evaluation row/key mismatch")
    require(set(frame["variant"].astype(str)) == {"F1_STYLE6"}, "baseline includes a non-F1_STYLE6 variant")
    require(set(frame["year"].astype(int).unique()) == set(fit.EVAL_YEARS), "baseline evaluation years changed")
    require(np.isfinite(frame["score"].to_numpy(dtype=np.float64)).all(), "baseline raw score has nonfinite values")
    return frame


def verify_eval_score_parity(baseline: pd.DataFrame) -> dict[str, Any]:
    receipt: dict[str, Any] = {}
    for year, (relative, expected_sha) in EVAL_SCORE_SOURCES.items():
        path = fit.source_path(relative, expected_sha)
        stored = pd.read_parquet(path, columns=["api_record_id", "score"])
        target = baseline.loc[baseline["year"].astype(int).eq(year), ["api_record_id", "score"]]
        require(len(stored) == len(target) and stored["api_record_id"].is_unique, f"evaluation raw score coverage mismatch: {year}")
        merged = target.merge(stored, on="api_record_id", how="outer", suffixes=("_baseline", "_saved"), indicator=True, validate="one_to_one")
        require(merged["_merge"].eq("both").all(), f"evaluation score key mismatch: {year}")
        require(np.array_equal(merged["score_baseline"].to_numpy(dtype=np.float64), merged["score_saved"].to_numpy(dtype=np.float64)), f"baseline raw score differs from saved evaluation score: {year}")
        receipt[str(year)] = {"rows": len(target), "score_path": relative, "score_sha256": expected_sha, "exact_score_parity": True}
    return receipt


def read_feature_distance() -> pd.DataFrame:
    path = fit.source_path(fit.FEATURES_REL, fit.FEATURES_SHA256)
    distance = pd.read_parquet(path, columns=["api_record_id", "year", "distance_m"])
    require(len(distance) == 52155 and distance["api_record_id"].is_unique, "distance metadata source row/key mismatch")
    require(np.isfinite(distance["distance_m"].to_numpy(dtype=np.float64)).all(), "feature distance metadata is nonfinite")
    return distance


def verify_eval_keys(baseline: pd.DataFrame, features: pd.DataFrame, feature_distance: pd.DataFrame) -> pd.DataFrame:
    eval_features = features.loc[features["year"].astype(int).isin(fit.EVAL_YEARS)].copy()
    require(len(eval_features) == 17412, "evaluation feature row count changed")
    require(eval_features["api_record_id"].is_unique, "evaluation feature API key is not unique")
    require(set(eval_features["api_record_id"].astype(int)) == set(baseline["api_record_id"].astype(int)), "evaluation baseline/feature key coverage changed")
    feature_cols = ["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number", "field_n"]
    joined = baseline.merge(eval_features[feature_cols], on="api_record_id", how="inner", suffixes=("_base", "_feature"), validate="one_to_one", sort=False)
    require(len(joined) == len(baseline), "evaluation baseline/feature join lost rows")
    for field in ("race_id", "race_date", "year", "horse_id", "horse_number", "field_n"):
        left = joined[f"{field}_base"].astype(str)
        right = joined[f"{field}_feature"].astype(str)
        require(left.equals(right), f"evaluation baseline/feature {field} mismatch")
    eval_distance = feature_distance.loc[feature_distance["year"].astype(int).isin(fit.EVAL_YEARS)]
    require(len(eval_distance) == 17412, "evaluation distance metadata row count changed")
    distance_join = baseline[["api_record_id", "distance_m"]].merge(
        eval_distance[["api_record_id", "distance_m"]],
        on="api_record_id",
        how="outer",
        suffixes=("_baseline", "_feature"),
        indicator=True,
        validate="one_to_one",
    )
    require(distance_join["_merge"].eq("both").all(), "evaluation distance metadata key mismatch")
    require(np.array_equal(distance_join["distance_m_baseline"].to_numpy(dtype=np.float64), distance_join["distance_m_feature"].to_numpy(dtype=np.float64)), "evaluation baseline/feature distance mismatch")
    eval_features = eval_features.merge(baseline[["api_record_id", "score", "distance_m"]], on="api_record_id", how="inner", validate="one_to_one", sort=False)
    require(len(eval_features) == 17412, "evaluation features lost raw scores")
    return eval_features


def score_zscore(score: np.ndarray) -> np.ndarray:
    score = np.asarray(score, dtype=np.float64)
    require(np.isfinite(score).all(), "nonfinite race raw scores")
    sd = float(score.std(ddof=0))
    if sd == 0.0:
        return np.zeros_like(score)
    return (score - float(score.mean())) / sd


def select_one_race(rows: pd.DataFrame, model: dict[str, Any], x_by_id: dict[int, np.ndarray]) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = rows.sort_values("horse_number", kind="stable").reset_index(drop=True)
    z, _, numbers, horse_ids = fit.validate_race_rows(rows, training=False)
    n = len(rows)
    beta = np.asarray(model["beta"], dtype=np.float64)
    x_race = np.vstack([x_by_id[int(api_id)] for api_id in rows["api_record_id"].to_numpy(dtype=np.int64)])
    baseline_idx = sorted(range(n), key=lambda i: (-float(rows.loc[i, "score"]), int(numbers[i])))[:5]
    baseline_set = frozenset(baseline_idx)
    baseline_numbers = [int(numbers[i]) for i in baseline_idx]
    baseline_ids = [str(horse_ids[i]) for i in baseline_idx]

    # Exhaustively enumerate the exact five-set decision space. Candidate sets
    # stay in memory for one race only and are never written to disk.
    combo_list = list(itertools.combinations(range(n), 5))
    require(len(combo_list) == math.comb(n, 5), "incomplete all-five-set enumeration")
    combos = np.asarray(combo_list, dtype=np.int16)
    base_energy = z[combos].sum(axis=1, dtype=np.float64)
    phi_energy = x_race[combos].sum(axis=1, dtype=np.float64) @ beta
    energies = base_energy + phi_energy
    require(np.isfinite(energies).all(), "nonfinite candidate energy")

    # The β=0 negative control uses the same deterministic tie rule.
    zero_energies = base_energy
    zero_max = float(zero_energies.max())
    zero_tied = np.flatnonzero(np.abs(zero_energies - zero_max) <= TIE_TOLERANCE)
    zero_choice = min(zero_tied, key=lambda k: (-len(set(combos[k].tolist()) & baseline_set), tuple(int(numbers[i]) for i in combos[k])))
    require(frozenset(combos[zero_choice].tolist()) == baseline_set, f"zero-beta control differs from raw Top5: {rows['race_id'].iloc[0]}")

    max_energy = float(energies.max())
    tied = np.flatnonzero(np.abs(energies - max_energy) <= TIE_TOLERANCE)
    choice_index = min(
        tied,
        key=lambda k: (
            -len(set(combos[k].tolist()) & baseline_set),
            tuple(int(numbers[i]) for i in combos[k]),
        ),
    )
    chosen_idx = [int(i) for i in combos[choice_index]]
    chosen_numbers = [int(numbers[i]) for i in chosen_idx]
    chosen_ids = [str(horse_ids[i]) for i in chosen_idx]
    require(len(set(chosen_ids)) == len(set(chosen_numbers)) == 5, "selected set is not five unique runners")
    record = {
        "race_id": str(rows["race_id"].iloc[0]),
        "race_date": str(rows["race_date"].iloc[0]),
        "year": int(rows["year"].iloc[0]),
        "distance_m": float(rows["distance_m"].iloc[0]),
        "field_n": n,
        "baseline_top5_horse_ids": baseline_ids,
        "baseline_top5_horse_numbers": baseline_numbers,
        "selector_top5_horse_ids": chosen_ids,
        "selector_top5_horse_numbers": chosen_numbers,
        "baseline_energy": float(base_energy[zero_choice]),
        "selector_energy": float(energies[choice_index]),
        "candidate_set_count": len(combo_list),
        "zero_beta_matches_baseline": True,
    }
    diagnostics = {
        "race_id": record["race_id"],
        "distance_m": record["distance_m"],
        "n_candidates": len(combo_list),
        "changed": set(chosen_ids) != set(baseline_ids),
        "primary": int(record["distance_m"]) in PRIMARY_DISTANCES,
    }
    return record, diagnostics


def main() -> None:
    require(FIT_RECEIPT_PATH.is_file(), "fit receipt is required before selection")
    models, fit_receipt, model_hashes = load_models_and_receipt()
    fit_receipt_sha = fit.sha256(FIT_RECEIPT_PATH)
    approval, approval_sha = require_selection_approval(fit_receipt_sha, model_hashes)
    require(approval.get("source_audit_root_sha256") == fit.ROOT_AUDIT_SHA256, "selection approval references a different root source audit")

    outdir = fit.OUT.resolve(strict=True)
    for name in (CHOICES_PATH_NAME, CHOICES_RECEIPT_NAME):
        path = fit.OUT / name
        require(not path.exists() and not path.is_symlink(), f"refusing to overwrite selection artifact: {name}")
        require(path.resolve(strict=False).is_relative_to(outdir), "selection output escaped study outputs")

    baseline = read_baseline_allowlist()
    score_parity = verify_eval_score_parity(baseline)
    features = fit.read_feature_inputs()
    feature_distance = read_feature_distance()
    eval_rows = verify_eval_keys(baseline, features, feature_distance)
    raw = fit.raw_runner_inputs(eval_rows)
    choices: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    for evaluation_year in fit.EVAL_YEARS:
        model = models[evaluation_year]
        means = np.asarray(model["feature_means"], dtype=np.float64)
        scales = np.asarray(model["feature_scales"], dtype=np.float64)
        x_year_mask = eval_rows["year"].astype(int).eq(evaluation_year).to_numpy()
        x_year = fit.apply_scaler(raw[x_year_mask], means, scales)
        api_year = eval_rows.loc[x_year_mask, "api_record_id"].to_numpy(dtype=np.int64)
        x_by_id = {int(api_id): x_year[i] for i, api_id in enumerate(api_year)}
        year_rows = eval_rows.loc[x_year_mask].copy()
        for _, race in year_rows.groupby("race_id", sort=True):
            record, diag = select_one_race(race, model, x_by_id)
            choices.append(record)
            diagnostics.append(diag)

    require(len(choices) == 1779, f"unexpected evaluation race count: {len(choices)}")
    require(len({record["race_id"] for record in choices}) == len(choices), "duplicate selected race ID")
    require(all(record["zero_beta_matches_baseline"] for record in choices), "zero-beta negative control failed")
    require(sum(record["distance_m"] in PRIMARY_DISTANCES for record in choices) == 1503, "primary cohort count changed")
    choices_path = fit.output_path(CHOICES_PATH_NAME)
    with choices_path.open("x", encoding="utf-8") as stream:
        for record in sorted(choices, key=lambda r: (r["race_date"], r["race_id"])):
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
    choice_receipt = {
        "status": "PASS",
        "study": fit.STUDY.name,
        "outcome_labels_read": False,
        "candidate_choices_created": len(choices),
        "candidate_sets_enumerated": int(sum(d["n_candidates"] for d in diagnostics)),
        "zero_beta_negative_control_matches_baseline_all_races": True,
        "primary_races": 1503,
        "full_races": 1779,
        "primary_changed_choices": int(sum(d["changed"] and d["primary"] for d in diagnostics)),
        "full_changed_choices": int(sum(d["changed"] for d in diagnostics)),
        "evaluation_score_parity": score_parity,
        "models": model_hashes,
        "fit_receipt_sha256": fit_receipt_sha,
        "plan_sha256": fit.sha256(fit.PLAN_PATH),
        "source_audit_sha256": fit.sha256(fit.SOURCE_AUDIT_PATH),
        "selection_code_sha256": fit.sha256(Path(__file__).resolve()),
        "root_selection_approval_sha256": approval_sha,
        "choices_file": CHOICES_PATH_NAME,
        "choices_sha256": fit.sha256(choices_path),
        "choices_bytes": choices_path.stat().st_size,
        "tie_rule": "max energy; within 1e-12 tie choose greatest raw-score Top5 overlap, then lexicographically smallest horse-number tuple",
        "selection_columns_allowlist": BASELINE_COLUMNS,
    }
    receipt_path = fit.output_path(CHOICES_RECEIPT_NAME)
    fit.write_json_once(receipt_path, choice_receipt)
    print(json.dumps({"status": "PASS", "choices": len(choices), "choices_sha256": choice_receipt["choices_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
