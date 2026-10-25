"""Independently recompute the approved three-fold reward fit receipt.

Reads only the fitted models, source receipts, fixed non-label runner inputs,
OOF score allowlists, and labels filtered to years before each fold. It does
not read evaluation-year outcome labels, the database, or any choice ledger.
All candidate sets are transient, one race at a time.
"""

from __future__ import annotations

from datetime import date, timedelta
from itertools import combinations
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "jeju/research/20261025_top5_reward_learning_v1"
OUT = STUDY / "outputs"
FEATURES_REL = "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
FEATURES_SHA = "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f"
YEARS = (2024, 2025, 2026)
PROVIDERS = {
    2019: ("jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2020/calibration_scores.parquet", "277595cfe5d9976d24a8dc1c0c0e302a9fd58e467046e337a9af13d3c7287cdc", "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2020/meta.json", "119f8e8e298914c1ee61420de2cc6eb52fec2728e601a46c84403cf103ae2737", "2018-12-29"),
    2020: ("jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2021/calibration_scores.parquet", "ca2254c97e54a102954f706433864be8e5715d142ebf8237610311e4cbaa4c50", "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2021/meta.json", "dac78c9c396a7c2ccd614a691f43755d659de7b2dbdb118faf95cc0d6d81ed52", "2019-12-28"),
    2021: ("jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2022/calibration_scores.parquet", "3665e2039946362b97fe4fa72e50d2e13c8fb3b77f9f71225a9ae9d5c4b84ee9", "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2022/meta.json", "6b8939ef969e0104f966e1d05bb8f4c389822a6f1ed26b90a7102b3df12946f3", "2020-12-20"),
    2022: ("jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2023/calibration_scores.parquet", "35c38b4acf6a5ca3236c41a85ba851577ab3053e92abb741a1e135f68942aa71", "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2023/meta.json", "91a84492a10e2d5f5c40edd7a7845f48544183cc552433fb3ab6a417cd85c794", "2021-12-25"),
    2023: ("jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/calibration_scores.parquet", "360cc559b1ab19cde177e0bb23206fd36f123b707714fbcb63547fdb9bed05b2", "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/meta.json", "15acbf959654da82d2240027e7b7d768bb9226af18395dac9ec92a68a4471726", "2022-12-24"),
    2024: ("jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/calibration_scores.parquet", "b092d28f0cbd45dd3a184a4a8ab89e9b5b5a78eef8068c45fda3de92734a3755", "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/meta.json", "23c4b0684477f34fbb2e99c22d0037cd903d5459db369f084773ec25c640f4a8", "2023-12-30"),
    2025: ("jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/calibration_scores.parquet", "6a7ed320e59add698faafd9008c882dc8a83a84f9198094371525f4c4ebd37d8", "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/meta.json", "e9dbfe5226571cb29e34b352a4ad8808a735d70929e66b42efb41b3e807ff06d", "2024-12-28"),
}
INPUTS = (
    "log_observed_starts", "log_same_starts", "log_same_valid_times",
    "mean5_rank_fraction", "mean5_rank_fraction_missing",
    "hist_s1f_relpos_mean5", "log_hist_s1f_relpos_n",
    "hist_s1f_to_c4_forward_mean5", "log_hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_forward_mean5", "log_hist_c4_to_g1f_pair_n",
)
BASE_FEATURE_COLS = (
    "api_record_id", "race_id", "race_date", "year", "horse_id",
    "horse_number", "field_n", "observed_starts", "same_starts",
    "same_valid_times", "mean5_rank_fraction", "hist_s1f_relpos_mean5",
    "hist_s1f_relpos_n", "hist_s1f_to_c4_forward_mean5",
    "hist_s1f_to_c4_pair_n", "hist_c4_to_g1f_forward_mean5",
    "hist_c4_to_g1f_pair_n",
)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fixed_source(rel: str, digest: str) -> Path:
    p = ROOT / rel
    if p.is_symlink() or not p.resolve(strict=True).is_relative_to(ROOT):
        raise ValueError(f"unsafe fixed source: {rel}")
    if sha(p) != digest:
        raise ValueError(f"source hash mismatch: {rel}")
    return p


def make_raw(frame: pd.DataFrame) -> np.ndarray:
    vals: dict[str, np.ndarray] = {}
    for col in ("observed_starts", "same_starts", "same_valid_times", "hist_s1f_relpos_n", "hist_s1f_to_c4_pair_n", "hist_c4_to_g1f_pair_n"):
        raw = pd.to_numeric(frame[col], errors="raise").to_numpy(dtype=np.float64)
        if not np.isfinite(raw).all() or (raw < 0).any():
            raise ValueError(f"invalid count: {col}")
        if col.startswith("hist_") and (not np.equal(raw, np.floor(raw)).all() or (raw > 5).any()):
            raise ValueError(f"invalid support count: {col}")
        if not col.startswith("hist_") and not np.equal(raw, np.floor(raw)).all():
            raise ValueError(f"invalid start count: {col}")
        vals[f"log_{col}"] = np.log1p(raw)
    mean5 = pd.to_numeric(frame["mean5_rank_fraction"], errors="raise")
    vals["mean5_rank_fraction"] = mean5.to_numpy(dtype=np.float64, na_value=np.nan)
    vals["mean5_rank_fraction_missing"] = mean5.isna().to_numpy(dtype=np.float64)
    for mean_col, count_col in (
        ("hist_s1f_relpos_mean5", "hist_s1f_relpos_n"),
        ("hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n"),
        ("hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n"),
    ):
        mean = pd.to_numeric(frame[mean_col], errors="raise")
        support = pd.to_numeric(frame[count_col], errors="raise").to_numpy(dtype=np.float64)
        if not np.array_equal(mean.isna().to_numpy(), support == 0):
            raise ValueError(f"support/NULL contract failed: {mean_col}")
        vals[mean_col] = mean.to_numpy(dtype=np.float64, na_value=np.nan)
        vals[f"log_{count_col}"] = np.log1p(support)
    return np.column_stack([vals[n] for n in INPUTS]).astype(np.float64, copy=False)


def scaler_and_impute(raw: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    means = np.empty(raw.shape[1], dtype=np.float64)
    scales = np.empty(raw.shape[1], dtype=np.float64)
    x = np.empty_like(raw)
    for j in range(raw.shape[1]):
        c = raw[:, j]
        present = np.isfinite(c)
        if not present.any():
            raise ValueError(f"no training support for {INPUTS[j]}")
        means[j] = c[present].mean(dtype=np.float64)
        scale = c[present].std(ddof=0, dtype=np.float64)
        scales[j] = scale if np.isfinite(scale) and scale != 0.0 else 1.0
        x[present, j] = (c[present] - means[j]) / scales[j]
        x[~present, j] = 0.0
    return means, scales, x


def load_features() -> pd.DataFrame:
    path = fixed_source(FEATURES_REL, FEATURES_SHA)
    frame = pd.read_parquet(path, columns=list(BASE_FEATURE_COLS))
    if len(frame) != 52155 or not frame.api_record_id.is_unique:
        raise ValueError("fixed feature source shape/key changed")
    frame["year"] = pd.to_numeric(frame["year"], errors="raise").astype(int)
    return frame


def load_fold(year: int, feature_rows: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    scores: list[pd.DataFrame] = []
    hashes: dict[str, str] = {}
    for label_year in range(2019, year):
        score_rel, score_sha, meta_rel, meta_sha, refit_max = PROVIDERS[label_year]
        score_path = fixed_source(score_rel, score_sha)
        meta_path = fixed_source(meta_rel, meta_sha)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("refit_max") != refit_max:
            raise ValueError(f"provider refit_max changed: {label_year}")
        scored = pd.read_parquet(score_path, columns=["api_record_id", "score"])
        if not scored.api_record_id.is_unique or not np.isfinite(scored.score.to_numpy(dtype=np.float64)).all():
            raise ValueError(f"provider score key/value failed: {label_year}")
        year_features = feature_rows.loc[feature_rows.year.eq(label_year)].copy()
        if len(year_features) != len(scored) or set(year_features.api_record_id.astype(int)) != set(scored.api_record_id.astype(int)):
            raise ValueError(f"feature/OOF-score coverage mismatch: {label_year}")
        joined = year_features.merge(scored, on="api_record_id", how="inner", validate="one_to_one", sort=False)
        dates = pd.to_datetime(joined.race_date, errors="raise").dt.date
        if not all(date.fromisoformat(refit_max) <= d - timedelta(days=2) for d in dates):
            raise ValueError(f"provider T-2 violation: {label_year}")
        scores.append(joined)
        hashes[score_rel] = score_sha
        hashes[meta_rel] = meta_sha
    train = pd.concat(scores, ignore_index=True)
    label_table = pq.read_table(
        fixed_source(FEATURES_REL, FEATURES_SHA),
        columns=["year", "api_record_id", "race_id", "finish_position", "field_n"],
        filters=[("year", ">=", 2019), ("year", "<", year)],
    )
    labels = label_table.to_pandas()
    if not ((labels.year >= 2019).all() and (labels.year < year).all()):
        raise ValueError("label filter returned a non-training year")
    if not labels.api_record_id.is_unique:
        raise ValueError("duplicate training label key")
    label_map = labels.set_index("api_record_id")[ ["race_id", "finish_position", "field_n"] ].to_dict("index")
    mapped = train.api_record_id.map(label_map)
    if mapped.isna().any():
        raise ValueError("training labels missing for score rows")
    train["label_race_id"] = [v["race_id"] for v in mapped]
    train["finish_position"] = [int(v["finish_position"]) for v in mapped]
    train["label_field_n"] = [int(v["field_n"]) for v in mapped]
    if not train.race_id.astype(str).equals(train.label_race_id.astype(str)):
        raise ValueError("label race key mismatch")
    if not np.array_equal(train.field_n.to_numpy(dtype=int), train.label_field_n.to_numpy(dtype=int)):
        raise ValueError("label field_n mismatch")
    return train, hashes


def logsumexp(v: np.ndarray) -> float:
    m = float(np.max(v))
    return m + math.log(float(np.exp(v - m).sum(dtype=np.float64)))


def recompute_fold(train: pd.DataFrame, model: dict[str, object]) -> dict[str, object]:
    raw = make_raw(train)
    means, scales, x = scaler_and_impute(raw)
    saved_means = np.asarray(model["feature_means"], dtype=np.float64)
    saved_scales = np.asarray(model["feature_scales"], dtype=np.float64)
    scaler_mean_error = float(np.max(np.abs(means - saved_means)))
    scaler_scale_error = float(np.max(np.abs(scales - saved_scales)))
    beta = np.asarray(model["beta"], dtype=np.float64)
    if model.get("feature_names") != list(INPUTS) or len(beta) != len(INPUTS):
        raise ValueError("model input contract changed")

    loss_sum = 0.0
    gradient_sum = np.zeros_like(beta)
    expected_reward_sum = 0.0
    races = 0
    action_count = 0
    positive_count = 0
    x_lookup = {int(api_id): x[i] for i, api_id in enumerate(train.api_record_id.to_numpy(dtype=np.int64))}
    for race_id, rows in train.groupby("race_id", sort=True):
        rows = rows.sort_values("horse_number", kind="stable")
        n = len(rows)
        field_n = rows.field_n.astype(int).to_numpy()
        ranks = rows.finish_position.astype(int).to_numpy()
        if n < 5 or not np.array_equal(np.sort(ranks), np.arange(1, n + 1)):
            raise ValueError(f"incomplete rank roster {race_id}")
        if not np.all(field_n == n) or not np.array_equal(rows.label_field_n.to_numpy(dtype=int), field_n):
            raise ValueError(f"field_n mismatch {race_id}")
        top3 = ranks <= 3
        if int(top3.sum()) != 3:
            raise ValueError(f"not exactly three Top3 labels {race_id}")
        score = rows.score.to_numpy(dtype=np.float64)
        sd = float(score.std(ddof=0))
        z = np.zeros_like(score) if sd == 0.0 else (score - float(score.mean())) / sd
        api_rows = rows.api_record_id.to_numpy(dtype=np.int64)
        runner_x = np.vstack([x_lookup[int(api_id)] for api_id in api_rows])
        actions = np.asarray(list(combinations(range(n), 5)), dtype=np.int16)
        phi = runner_x[actions].sum(axis=1, dtype=np.float64)
        base = z[actions].sum(axis=1, dtype=np.float64)
        good = top3[actions].sum(axis=1) == 3
        if int(good.sum()) != math.comb(n - 3, 2):
            raise ValueError(f"positive-set count mismatch {race_id}")
        energy = base + phi @ beta
        logz_all = logsumexp(energy)
        logz_good = logsumexp(energy[good])
        p_good = math.exp(logz_good - logz_all)
        weights_all = np.exp(energy - logz_all)
        weights_good = np.exp(energy[good] - logz_good)
        expected_all = weights_all @ phi
        expected_good = weights_good @ phi[good]
        loss_sum += 1.0 - 2.0 * p_good
        gradient_sum += 2.0 * p_good * (expected_all - expected_good)
        expected_reward_sum += 2.0 * p_good - 1.0
        races += 1
        action_count += len(actions)
        positive_count += int(good.sum())

    l2 = 0.5 * float(beta @ beta)
    loss = loss_sum / races + l2
    gradient = gradient_sum / races + beta
    saved = model["fit_diagnostics"]
    return {
        "training_rows": int(len(train)),
        "training_races": races,
        "training_label_years": sorted(int(y) for y in train.year.unique()),
        "candidate_sets": action_count,
        "positive_sets": positive_count,
        "scaler_mean_max_abs_error": scaler_mean_error,
        "scaler_scale_max_abs_error": scaler_scale_error,
        "objective_recomputed": loss,
        "objective_saved": float(saved["objective_value"]),
        "objective_abs_error": abs(loss - float(saved["objective_value"])),
        "gradient_max_abs_recomputed": float(np.max(np.abs(gradient))),
        "gradient_max_abs_saved": float(saved["gradient_max_abs"]),
        "mean_expected_reward_recomputed": expected_reward_sum / races,
        "mean_expected_reward_saved": float(saved["mean_expected_stochastic_reward"]),
        "optimizer_success_saved": bool(saved["success"]),
        "optimizer_iterations_saved": int(saved["iterations"]),
        "one_fit_call_saved": True,
        "evaluation_year_labels_read": False,
    }


def run() -> dict[str, object]:
    receipt_path = OUT / "FIT_RECEIPT.json"
    label_preflight_path = OUT / "LABEL_PREFLIGHT.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    preflight = json.loads(label_preflight_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "PASS" or receipt.get("fit_count") != 3 or receipt.get("evaluation_outcomes_read") is not False:
        raise ValueError("fit receipt status/label contract failed")
    if receipt.get("fit_code_sha256") != "043c669ad6f8d7a9d66bb5846002758385c3e0811e7e6720727b2e5c1e9b85dc":
        raise ValueError("fit receipt does not bind corrected source hash")
    if sha(STUDY / "fit_selector.py") != receipt["fit_code_sha256"]:
        raise ValueError("fit source changed since receipt")
    if sha(label_preflight_path) != receipt.get("label_preflight_sha256"):
        raise ValueError("label preflight receipt hash mismatch")
    if preflight.get("evaluation_labels_read") is not False or preflight.get("label_rows_returned_by_year_filter_only") is not True:
        raise ValueError("preflight indicates evaluation labels were read")
    features = load_features()
    fold_results: dict[str, object] = {}
    all_hashes = {FEATURES_REL: FEATURES_SHA}
    for year in YEARS:
        fold = receipt["folds"][str(year)]
        model_name = f"model_{year}.json"
        model_path = OUT / model_name
        expected_model_sha = receipt["model_artifacts"][model_name]["sha256"]
        if sha(model_path) != expected_model_sha:
            raise ValueError(f"model artifact hash mismatch: {model_name}")
        model = json.loads(model_path.read_text(encoding="utf-8"))
        if model.get("fit_code_sha256") != receipt["fit_code_sha256"] or model.get("objective_id") != receipt["objective_id"]:
            raise ValueError(f"model metadata source/objective mismatch: {model_name}")
        if model.get("training_label_years") != list(range(2019, year)):
            raise ValueError(f"wrong model label window: {year}")
        train, hashes = load_fold(year, features.loc[features.year.lt(year)].copy())
        result = recompute_fold(train, model)
        if result["training_rows"] != fold["training_rows"] or result["training_races"] != fold["training_races"]:
            raise ValueError(f"fit receipt train population mismatch: {year}")
        if result["candidate_sets"] != fold["candidate_sets_enumerated"] or result["positive_sets"] != fold["positive_sets_enumerated"]:
            raise ValueError(f"fit receipt candidate count mismatch: {year}")
        if result["scaler_mean_max_abs_error"] > 1e-12 or result["scaler_scale_max_abs_error"] > 1e-12:
            raise ValueError(f"saved fold scaler does not match independent training-only scaler: {year}")
        if result["objective_abs_error"] > 1e-10 or result["gradient_max_abs_recomputed"] > 1e-6:
            raise ValueError(f"saved model objective/gradient replay failed: {year}")
        if result["mean_expected_reward_recomputed"] != result["mean_expected_reward_saved"]:
            if abs(float(result["mean_expected_reward_recomputed"]) - float(result["mean_expected_reward_saved"])) > 1e-12:
                raise ValueError(f"mean reward replay mismatch: {year}")
        if not result["optimizer_success_saved"] or result["optimizer_iterations_saved"] > 1000:
            raise ValueError(f"optimizer receipt invalid: {year}")
        fold_results[str(year)] = result
        all_hashes.update(hashes)
    for relative, digest in all_hashes.items():
        if sha(ROOT / relative) != digest:
            raise ValueError(f"fit source hash mismatch in receipt: {relative}")
    return {
        "status": "PASS",
        "study": STUDY.name,
        "fit_receipt_sha256": sha(receipt_path),
        "label_preflight_sha256": sha(label_preflight_path),
        "fit_code_sha256": receipt["fit_code_sha256"],
        "source_file_count_hashed": len(all_hashes),
        "source_hashes": all_hashes,
        "folds": fold_results,
        "reads_evaluation_year_labels_or_outcomes": False,
        "reads_choices_or_outcome_summaries": False,
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True, indent=2))
