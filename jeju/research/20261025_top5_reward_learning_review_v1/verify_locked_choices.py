"""Independent label-free replay of all hash-locked reward Top5 choices.

This verifier does not import the main fit or selector modules. It streams one
race's complete five-set action space at a time, writes no per-set data, and
uses only frozen score/feature/roster inputs and selected-choice ledgers.
"""

from __future__ import annotations

from itertools import combinations
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "jeju/research/20261025_top5_reward_learning_v1"
OUT = STUDY / "outputs"
BASELINE_REL = "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet"
BASELINE_SHA = "c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1"
FEATURES_REL = "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
FEATURES_SHA = "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f"
OLD_CHOICES_REL = "jeju/research/20261025_top5_direct_learning_v1/outputs/candidate_choices.jsonl"
OLD_CHOICES_SHA = "eacbea0404a41dd70872a9936a9547804579b3e41ca13386e84924ec06899545"
PLAN_SHA = "97cb3059573fd8c8352139ab9921a541dec997cabdcef2e7dc02cc19cc39d0cf"
SOURCE_AUDIT_SHA = "918f68b3d78b105e12e4e02502a024fb211ed19f75c7916203ff6db9b5459753"
FIT_CODE_SHA = "043c669ad6f8d7a9d66bb5846002758385c3e0811e7e6720727b2e5c1e9b85dc"
YEARS = (2024, 2025, 2026)
PRIMARY_DISTANCES = {900, 1000, 1110, 1200}
TIE_TOLERANCE = 1e-12
BASELINE_COLUMNS = [
    "api_record_id", "race_id", "race_date", "year", "distance_m", "horse_id",
    "horse_number", "field_n", "variant", "score",
]
FEATURE_COLUMNS = [
    "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
    "field_n", "distance_m", "observed_starts", "same_starts", "same_valid_times",
    "mean5_rank_fraction", "hist_s1f_relpos_mean5", "hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n",
]
INPUTS = (
    "log_observed_starts", "log_same_starts", "log_same_valid_times",
    "mean5_rank_fraction", "mean5_rank_fraction_missing",
    "hist_s1f_relpos_mean5", "log_hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5", "log_hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5", "log_hist_c4_to_g1f_pair_n",
)
EVAL_SCORES = {
    2024: ("jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/evaluation_scores.parquet", "b9541396c81e307f99f6c8eff4441594b181b9a0398120a4fa5f529add55cd60"),
    2025: ("jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/evaluation_scores.parquet", "45247f00f286197067957d25ee46e0594f2ef0d26089c6b6081592272651eb12"),
    2026: ("jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/evaluation_scores.parquet", "0ccae2475fc1ea87ddf62b054572961ab32fed26b332070907853ebbd412989a"),
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fixed_source(rel: str, digest: str) -> Path:
    path = ROOT / rel
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(ROOT):
        raise ValueError(f"unsafe fixed source: {rel}")
    if sha(path) != digest:
        raise ValueError(f"hash mismatch: {rel}")
    return path


def features_to_raw(frame: pd.DataFrame) -> np.ndarray:
    vals: dict[str, np.ndarray] = {}
    for col in ("observed_starts", "same_starts", "same_valid_times", "hist_s1f_relpos_n", "hist_s1f_to_c4_pair_n", "hist_c4_to_g1f_pair_n"):
        count = pd.to_numeric(frame[col], errors="raise").to_numpy(dtype=np.float64)
        if not np.isfinite(count).all() or (count < 0).any():
            raise ValueError(f"invalid count {col}")
        if col.startswith("hist_") and (not np.equal(count, np.floor(count)).all() or (count > 5).any()):
            raise ValueError(f"invalid style support count {col}")
        if not col.startswith("hist_") and not np.equal(count, np.floor(count)).all():
            raise ValueError(f"invalid starts count {col}")
        vals[f"log_{col}"] = np.log1p(count)
    mean5 = pd.to_numeric(frame["mean5_rank_fraction"], errors="raise")
    vals["mean5_rank_fraction"] = mean5.to_numpy(dtype=np.float64, na_value=np.nan)
    vals["mean5_rank_fraction_missing"] = mean5.isna().to_numpy(dtype=np.float64)
    for mean_name, count_name in (
        ("hist_s1f_relpos_mean5", "hist_s1f_relpos_n"),
        ("hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n"),
        ("hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n"),
    ):
        mean = pd.to_numeric(frame[mean_name], errors="raise")
        count = pd.to_numeric(frame[count_name], errors="raise").to_numpy(dtype=np.float64)
        if not np.array_equal(mean.isna().to_numpy(), count == 0):
            raise ValueError(f"style support/NULL mismatch: {mean_name}")
        vals[mean_name] = mean.to_numpy(dtype=np.float64, na_value=np.nan)
        vals[f"log_{count_name}"] = np.log1p(count)
    return np.column_stack([vals[name] for name in INPUTS]).astype(np.float64, copy=False)


def apply_scaler(raw: np.ndarray, means: np.ndarray, scales: np.ndarray) -> np.ndarray:
    out = np.zeros_like(raw, dtype=np.float64)
    for j in range(raw.shape[1]):
        c = raw[:, j]
        present = np.isfinite(c)
        out[present, j] = (c[present] - means[j]) / scales[j]
        out[~present, j] = 0.0
    return out


def zscore(score: np.ndarray) -> np.ndarray:
    score = np.asarray(score, dtype=np.float64)
    if not np.isfinite(score).all():
        raise ValueError("nonfinite raw scores")
    sd = float(score.std(ddof=0))
    return np.zeros_like(score) if sd == 0.0 else (score - float(score.mean())) / sd


def load_jsonl(path: Path) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            race_id = str(obj["race_id"])
            if race_id in rows:
                raise ValueError(f"duplicate race choice: {race_id}")
            rows[race_id] = obj
    return rows


def run() -> dict[str, object]:
    fit_receipt_path = OUT / "FIT_RECEIPT.json"
    choice_path = OUT / "candidate_choices.jsonl"
    choice_receipt_path = OUT / "CHOICES_RECEIPT.json"
    approval_path = OUT / "ROOT_SELECTION_APPROVAL.json"
    fit_receipt = json.loads(fit_receipt_path.read_text(encoding="utf-8"))
    choice_receipt = json.loads(choice_receipt_path.read_text(encoding="utf-8"))
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    if sha(fit_receipt_path) != choice_receipt.get("fit_receipt_sha256"):
        raise ValueError("choice receipt fit hash mismatch")
    if sha(choice_path) != choice_receipt.get("choices_sha256"):
        raise ValueError("locked choice ledger hash mismatch")
    if approval.get("status") != "approved" or approval.get("selection_code_sha256") != sha(STUDY / "select_sets.py"):
        raise ValueError("selection approval/source code mismatch")
    if approval.get("plan_sha256") != PLAN_SHA or approval.get("source_audit_sha256") != SOURCE_AUDIT_SHA:
        raise ValueError("selection approval plan/source mismatch")
    model_hashes = {name: item["sha256"] for name, item in fit_receipt["model_artifacts"].items()}
    if approval.get("fit_receipt_sha256") != sha(fit_receipt_path) or approval.get("model_sha256s") != model_hashes:
        raise ValueError("selection approval fit/model binding mismatch")
    if choice_receipt.get("selection_code_sha256") != approval.get("selection_code_sha256"):
        raise ValueError("choice receipt/approval code hash mismatch")
    if fit_receipt.get("fit_code_sha256") != FIT_CODE_SHA or sha(STUDY / "fit_selector.py") != FIT_CODE_SHA:
        raise ValueError("fit source hash mismatch")
    if sha(STUDY / "PLAN.md") != PLAN_SHA or sha(STUDY / "SOURCE_AUDIT.md") != SOURCE_AUDIT_SHA:
        raise ValueError("plan/source audit changed after approval")
    model_by_year: dict[int, dict[str, object]] = {}
    for year in YEARS:
        name = f"model_{year}.json"
        path = OUT / name
        expected = fit_receipt["model_artifacts"][name]["sha256"]
        if sha(path) != expected:
            raise ValueError(f"model hash mismatch: {name}")
        model_by_year[year] = json.loads(path.read_text(encoding="utf-8"))

    baseline_path = fixed_source(BASELINE_REL, BASELINE_SHA)
    baseline = pd.read_parquet(baseline_path, columns=BASELINE_COLUMNS)
    if len(baseline) != 17412 or baseline.api_record_id.isna().any() or not baseline.api_record_id.is_unique:
        raise ValueError("baseline roster row/key mismatch")
    if set(baseline.variant.astype(str)) != {"F1_STYLE6"} or set(baseline.year.astype(int).unique()) != set(YEARS):
        raise ValueError("baseline variant/year mismatch")
    features = pd.read_parquet(fixed_source(FEATURES_REL, FEATURES_SHA), columns=FEATURE_COLUMNS)
    if len(features) != 52155 or not features.api_record_id.is_unique:
        raise ValueError("feature row/key mismatch")
    features["year"] = features.year.astype(int)
    feature_eval = features.loc[features.year.isin(YEARS)].copy()
    baseline_keys = set(baseline.api_record_id.astype(int))
    if len(feature_eval) != 17412 or set(feature_eval.api_record_id.astype(int)) != baseline_keys:
        raise ValueError("evaluation feature/baseline coverage mismatch")
    merged = baseline.merge(feature_eval, on="api_record_id", how="inner", suffixes=("_base", "_feature"), validate="one_to_one", sort=False)
    for field in ("race_id", "race_date", "year", "horse_id", "horse_number", "field_n", "distance_m"):
        if not merged[f"{field}_base"].astype(str).equals(merged[f"{field}_feature"].astype(str)):
            raise ValueError(f"baseline/feature metadata mismatch: {field}")
    score_parity_rows = 0
    for year, (rel, digest) in EVAL_SCORES.items():
        saved = pd.read_parquet(fixed_source(rel, digest), columns=["api_record_id", "score"])
        target = baseline.loc[baseline.year.astype(int).eq(year), ["api_record_id", "score"]]
        check = target.merge(saved, on="api_record_id", how="outer", suffixes=("_base", "_eval"), indicator=True, validate="one_to_one")
        if len(saved) != len(target) or not check._merge.eq("both").all():
            raise ValueError(f"saved evaluation score keys differ: {year}")
        if not np.array_equal(check.score_base.to_numpy(dtype=np.float64), check.score_eval.to_numpy(dtype=np.float64)):
            raise ValueError(f"saved evaluation raw scores differ: {year}")
        score_parity_rows += len(target)

    actual_choices = load_jsonl(choice_path)
    old_path = fixed_source(OLD_CHOICES_REL, OLD_CHOICES_SHA)
    old_choices = load_jsonl(old_path)
    if len(actual_choices) != 1779 or len(old_choices) != 1779:
        raise ValueError("choice ledger race count mismatch")
    if set(actual_choices) != set(old_choices):
        raise ValueError("new and old head race cohorts differ")

    raw = features_to_raw(merged)
    merged["_raw_row"] = np.arange(len(merged), dtype=np.int64)
    # `merged` follows baseline order, while raw rows were built in the same order.
    x_by_year: dict[int, dict[int, np.ndarray]] = {}
    for year in YEARS:
        model = model_by_year[year]
        means = np.asarray(model["feature_means"], dtype=np.float64)
        scales = np.asarray(model["feature_scales"], dtype=np.float64)
        mask = merged.year_base.astype(int).eq(year).to_numpy()
        x_year = apply_scaler(raw[mask], means, scales)
        api = merged.loc[mask, "api_record_id"].to_numpy(dtype=np.int64)
        x_by_year[year] = {int(key): x_year[i] for i, key in enumerate(api)}

    total_candidates = 0
    choice_match_count = 0
    metadata_match_count = 0
    energy_match_count = 0
    beta_zero_match_count = 0
    reward_old_equal = 0
    reward_raw_equal = 0
    reward_old_changed = 0
    reward_raw_changed = 0
    old_raw_changed = 0
    max_energy_abs_error = 0.0
    max_baseline_energy_abs_error = 0.0
    tie_races = 0
    by_year: dict[str, dict[str, int]] = {}
    by_distance: dict[str, dict[str, int]] = {}

    for race_id, rows in merged.groupby("race_id_base", sort=True):
        rows = rows.sort_values("horse_number_base", kind="stable")
        year = int(rows.year_base.iloc[0])
        distance = int(rows.distance_m_base.iloc[0])
        n = int(rows.field_n_base.iloc[0])
        if len(rows) != n or n < 5 or not rows.horse_number_base.is_unique or rows.horse_id_base.isna().any():
            raise ValueError(f"invalid evaluation roster: {race_id}")
        scores = rows.score.to_numpy(dtype=np.float64)
        z = zscore(scores)
        nums = rows.horse_number_base.to_numpy(dtype=np.int64)
        ids = rows.horse_id_base.astype(str).to_numpy()
        api_ids = rows.api_record_id.to_numpy(dtype=np.int64)
        x = np.vstack([x_by_year[year][int(api)] for api in api_ids])
        beta = np.asarray(model_by_year[year]["beta"], dtype=np.float64)
        baseline_order = sorted(range(n), key=lambda i: (-float(scores[i]), int(nums[i])))[:5]
        baseline_set = frozenset(baseline_order)
        combos = np.asarray(list(combinations(range(n), 5)), dtype=np.int16)
        if len(combos) != math.comb(n, 5):
            raise AssertionError("not all five-sets enumerated")
        base_energy = z[combos].sum(axis=1, dtype=np.float64)
        phi = x[combos].sum(axis=1, dtype=np.float64)
        energies = base_energy + phi @ beta
        if not np.isfinite(energies).all():
            raise ValueError(f"nonfinite utility: {race_id}")
        max_e = float(np.max(energies))
        tied = np.flatnonzero(np.abs(energies - max_e) <= TIE_TOLERANCE)
        if len(tied) > 1:
            tie_races += 1
        chosen_ix = min(
            tied,
            key=lambda k: (
                -len(set(combos[k].tolist()) & baseline_set),
                tuple(int(nums[i]) for i in combos[k]),
            ),
        )
        selected_indices = [int(i) for i in combos[chosen_ix]]
        selected_numbers = [int(nums[i]) for i in selected_indices]
        selected_ids = [str(ids[i]) for i in selected_indices]
        chosen = actual_choices[str(race_id)]
        old = old_choices[str(race_id)]
        expected_raw_ids = {str(ids[i]) for i in baseline_order}
        expected_raw_numbers = {int(nums[i]) for i in baseline_order}
        if set(map(str, chosen["baseline_top5_horse_ids"])) != expected_raw_ids or set(map(int, chosen["baseline_top5_horse_numbers"])) != expected_raw_numbers:
            raise ValueError(f"saved raw-score Top5 differs from independent ranking: {race_id}")
        if set(map(str, old["baseline_top5_horse_ids"])) != expected_raw_ids or set(map(int, old["baseline_top5_horse_numbers"])) != expected_raw_numbers:
            raise ValueError(f"old raw-score Top5 differs from independent ranking: {race_id}")
        if set(chosen["selector_top5_horse_ids"]) != set(selected_ids) or set(chosen["selector_top5_horse_numbers"]) != set(selected_numbers):
            raise ValueError(f"independent selector set mismatch: {race_id}")
        choice_match_count += 1
        if (chosen["race_date"] == str(rows.race_date_base.iloc[0]) and int(chosen["year"]) == year and int(chosen["field_n"]) == n and float(chosen["distance_m"]) == float(distance)):
            metadata_match_count += 1
        else:
            raise ValueError(f"saved choice metadata mismatch: {race_id}")
        energy_error = abs(float(chosen["selector_energy"]) - float(energies[chosen_ix]))
        baseline_combo_index = next(k for k, combo in enumerate(combos) if frozenset(combo.tolist()) == baseline_set)
        base_choice_energy = float(base_energy[baseline_combo_index])
        base_error = abs(float(chosen["baseline_energy"]) - base_choice_energy)
        max_energy_abs_error = max(max_energy_abs_error, energy_error)
        max_baseline_energy_abs_error = max(max_baseline_energy_abs_error, base_error)
        if energy_error > 1e-11 or base_error > 1e-11:
            raise ValueError(f"saved utility mismatch: {race_id}")
        energy_match_count += 1

        zero_max = float(base_energy.max())
        zero_ties = np.flatnonzero(np.abs(base_energy - zero_max) <= TIE_TOLERANCE)
        zero_ix = min(zero_ties, key=lambda k: (-len(set(combos[k].tolist()) & baseline_set), tuple(int(nums[i]) for i in combos[k])))
        if frozenset(combos[zero_ix].tolist()) != baseline_set or chosen.get("zero_beta_matches_baseline") is not True:
            raise ValueError(f"beta-zero identity failed: {race_id}")
        beta_zero_match_count += 1

        reward_set = frozenset(selected_ids)
        old_set = frozenset(str(v) for v in old["selector_top5_horse_ids"])
        raw_set = frozenset(str(v) for v in chosen["baseline_top5_horse_ids"])
        reward_old_equal += int(reward_set == old_set)
        reward_raw_equal += int(reward_set == raw_set)
        reward_old_changed += int(reward_set != old_set)
        reward_raw_changed += int(reward_set != raw_set)
        old_raw_changed += int(old_set != raw_set)

        year_key, dist_key = str(year), str(distance)
        for table, key in ((by_year, year_key), (by_distance, dist_key)):
            cell = table.setdefault(key, {"races": 0, "reward_changed_vs_raw": 0, "reward_changed_vs_old": 0})
            cell["races"] += 1
            cell["reward_changed_vs_raw"] += int(reward_set != raw_set)
            cell["reward_changed_vs_old"] += int(reward_set != old_set)
        total_candidates += len(combos)

    primary_count = sum(1 for row in actual_choices.values() if int(row["distance_m"]) in PRIMARY_DISTANCES)
    if choice_match_count != 1779 or metadata_match_count != 1779 or energy_match_count != 1779 or beta_zero_match_count != 1779:
        raise ValueError("one or more complete-cohort checks failed")
    if primary_count != 1503 or int(choice_receipt["candidate_choices_created"]) != 1779:
        raise ValueError("primary/full race count mismatch")
    if total_candidates != int(choice_receipt["candidate_sets_enumerated"]):
        raise ValueError("candidate count differs from the choice receipt")
    if reward_raw_changed != int(choice_receipt["full_changed_choices"]):
        raise ValueError("full changed choice count differs from choice receipt")
    if sum(v["reward_changed_vs_raw"] for k, v in by_distance.items() if int(k) in PRIMARY_DISTANCES) != int(choice_receipt["primary_changed_choices"]):
        raise ValueError("primary changed choice count differs from receipt")
    return {
        "status": "PASS",
        "selection_code_sha256": choice_receipt["selection_code_sha256"],
        "fit_receipt_sha256": sha(fit_receipt_path),
        "choice_receipt_sha256": sha(choice_receipt_path),
        "selection_approval_sha256": sha(approval_path),
        "choices_sha256": sha(choice_path),
        "baseline_sha256": BASELINE_SHA,
        "feature_sha256": FEATURES_SHA,
        "old_choice_sha256": OLD_CHOICES_SHA,
        "evaluation_score_parity_rows": score_parity_rows,
        "races_replayed": choice_match_count,
        "primary_races": primary_count,
        "full_candidate_sets_enumerated": total_candidates,
        "beta_zero_raw_top5_identity_races": beta_zero_match_count,
        "selected_set_match_races": choice_match_count,
        "saved_energy_match_races": energy_match_count,
        "saved_metadata_match_races": metadata_match_count,
        "maximum_selected_energy_abs_error": max_energy_abs_error,
        "maximum_baseline_energy_abs_error": max_baseline_energy_abs_error,
        "near_tie_races": tie_races,
        "reward_changed_vs_raw_full": reward_raw_changed,
        "reward_changed_vs_old_full": reward_old_changed,
        "reward_equals_raw_full": reward_raw_equal,
        "reward_equals_old_full": reward_old_equal,
        "old_changed_vs_raw_full": old_raw_changed,
        "by_year": by_year,
        "by_distance_m": by_distance,
        "reads_evaluation_labels_or_outcome_values": False,
        "writes_per_race_replay_or_full_candidate_sets": False,
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True, indent=2))
