"""Fit the predeclared F1_STYLE6 Top5 expected-reward selection head.

This script is intentionally dormant until a hash-bound ROOT_FIT_APPROVAL.json
exists. It reads training-year labels only and writes compact model parameters
and a fit receipt inside this study directory. Evaluation outcomes are not read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.optimize import minimize


ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parent
OUT = STUDY / "outputs"
FEATURES_REL = "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
FEATURES_SHA256 = "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f"
ROOT_AUDIT_REL = "jeju/research/20261025_top5_direct_learning_rootreview_v1/ROOT_SOURCE_AUDIT.json"
ROOT_AUDIT_SHA256 = "b263703aae9e7d5eca2bda394d4c20de67144bcaf78e959f5add9efffc8310f8"
FIT_APPROVAL = OUT / "ROOT_FIT_APPROVAL.json"
LABEL_PREFLIGHT_NAME = "LABEL_PREFLIGHT.json"
PLAN_PATH = STUDY / "PLAN.md"
SOURCE_AUDIT_PATH = STUDY / "SOURCE_AUDIT.md"
FIT_CODE_PATH = STUDY / "fit_selector.py"
CHOICE_CODE_PATH = STUDY / "select_sets.py"
REPORT_CODE_PATH = STUDY / "report_outcomes.py"

EVAL_YEARS = (2024, 2025, 2026)
FIRST_TRAIN_YEAR = 2019
LAMBDA = 1.0
MAXITER = 1000
FTOL = 1e-12
GTOL = 1e-8
GRADIENT_ACCEPTANCE = 1e-6
OBJECTIVE_ID = "expected_top3_in_top5_reward_gibbs_additive_selection_head_v1"

TRAIN_PROVIDERS: dict[int, dict[str, str]] = {
    2019: {
        "score": "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2020/calibration_scores.parquet",
        "score_sha256": "277595cfe5d9976d24a8dc1c0c0e302a9fd58e467046e337a9af13d3c7287cdc",
        "meta": "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2020/meta.json",
        "meta_sha256": "119f8e8e298914c1ee61420de2cc6eb52fec2728e601a46c84403cf103ae2737",
        "refit_max": "2018-12-29",
    },
    2020: {
        "score": "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2021/calibration_scores.parquet",
        "score_sha256": "ca2254c97e54a102954f706433864be8e5715d142ebf8237610311e4cbaa4c50",
        "meta": "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2021/meta.json",
        "meta_sha256": "dac78c9c396a7c2ccd614a691f43755d659de7b2dbdb118faf95cc0d6d81ed52",
        "refit_max": "2019-12-28",
    },
    2021: {
        "score": "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2022/calibration_scores.parquet",
        "score_sha256": "3665e2039946362b97fe4fa72e50d2e13c8fb3b77f9f71225a9ae9d5c4b84ee9",
        "meta": "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2022/meta.json",
        "meta_sha256": "6b8939ef969e0104f966e1d05bb8f4c389822a6f1ed26b90a7102b3df12946f3",
        "refit_max": "2020-12-20",
    },
    2022: {
        "score": "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2023/calibration_scores.parquet",
        "score_sha256": "35c38b4acf6a5ca3236c41a85ba851577ab3053e92abb741a1e135f68942aa71",
        "meta": "jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_2023/meta.json",
        "meta_sha256": "91a84492a10e2d5f5c40edd7a7845f48544183cc552433fb3ab6a417cd85c794",
        "refit_max": "2021-12-25",
    },
    2023: {
        "score": "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/calibration_scores.parquet",
        "score_sha256": "360cc559b1ab19cde177e0bb23206fd36f123b707714fbcb63547fdb9bed05b2",
        "meta": "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/meta.json",
        "meta_sha256": "15acbf959654da82d2240027e7b7d768bb9226af18395dac9ec92a68a4471726",
        "refit_max": "2022-12-24",
    },
    2024: {
        "score": "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/calibration_scores.parquet",
        "score_sha256": "b092d28f0cbd45dd3a184a4a8ab89e9b5b5a78eef8068c45fda3de92734a3755",
        "meta": "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/meta.json",
        "meta_sha256": "23c4b0684477f34fbb2e99c22d0037cd903d5459db369f084773ec25c640f4a8",
        "refit_max": "2023-12-30",
    },
    2025: {
        "score": "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/calibration_scores.parquet",
        "score_sha256": "6a7ed320e59add698faafd9008c882dc8a83a84f9198094371525f4c4ebd37d8",
        "meta": "jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/meta.json",
        "meta_sha256": "e9dbfe5226571cb29e34b352a4ad8808a735d70929e66b42efb41b3e807ff06d",
        "refit_max": "2024-12-28",
    },
}

LOG_COUNT_INPUTS = (
    "observed_starts",
    "same_starts",
    "same_valid_times",
    "hist_s1f_relpos_n",
    "hist_s1f_to_c4_pair_n",
    "hist_c4_to_g1f_pair_n",
)
STYLE_PAIRS = (
    ("hist_s1f_relpos_mean5", "hist_s1f_relpos_n"),
    ("hist_s1f_to_c4_forward_mean5", "hist_s1f_to_c4_pair_n"),
    ("hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n"),
)
RAW_INPUT_NAMES = (
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
)
FEATURE_COLUMNS = (
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
)


class FitError(RuntimeError):
    """Raised when a frozen source or fit contract fails."""


@dataclass(frozen=True)
class TrainingRace:
    race_id: str
    base_energy: np.ndarray
    set_features: np.ndarray
    good_mask: np.ndarray
    n_runners: int


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FitError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def source_path(relative: str, expected_sha256: str) -> Path:
    path = ROOT / relative
    require(not path.is_symlink(), f"source symlink is not allowed: {relative}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"source outside workspace: {relative}")
    require(sha256(resolved) == expected_sha256, f"source SHA-256 mismatch: {relative}")
    return resolved


def output_path(name: str) -> Path:
    require(Path(name).name == name and name not in (".", ".."), "invalid fixed output name")
    resolved_study = STUDY.resolve(strict=True)
    resolved_out = OUT.resolve(strict=False)
    require(resolved_out.is_relative_to(resolved_study), "output escaped study directory")
    require(not OUT.is_symlink(), "output directory must not be a symlink")
    OUT.mkdir(exist_ok=True)
    path = OUT / name
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite output: {name}")
    require(path.resolve(strict=False).is_relative_to(resolved_out), "output path escaped output directory")
    return path


def write_json_once(path: Path, payload: dict[str, Any]) -> None:
    require(path.parent == OUT, "JSON output must remain in this study's outputs directory")
    require(not path.is_symlink() and not path.exists(), f"refusing to overwrite output: {path.name}")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def check_root_audit() -> dict[str, Any]:
    audit_path = source_path(ROOT_AUDIT_REL, ROOT_AUDIT_SHA256)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    require(audit.get("passed") is True, "independent root source audit did not pass")
    require(audit.get("eval_outcomes_read") is False, "root source audit reports evaluation outcomes read")
    require(audit.get("feature_label_columns_read") is False, "root source audit reports labels read")
    require(audit.get("features_sha256") == FEATURES_SHA256, "root feature hash disagrees with this plan")
    require(audit.get("baseline_sha256") == "c3fc8a2bf10d3fa1678ab3c5463209089021f51f6d0bf500fc2db6006fda13c1", "root baseline hash disagrees with source audit")
    require(audit.get("excluded_horse_absent") is True, "excluded horse is present in root source audit")
    return audit


def reviewed_code_hashes() -> dict[str, str]:
    return {
        "fit_selector.py": sha256(FIT_CODE_PATH),
        "select_sets.py": sha256(CHOICE_CODE_PATH),
        "report_outcomes.py": sha256(REPORT_CODE_PATH),
    }


def require_fit_approval() -> tuple[dict[str, Any], str]:
    require(FIT_APPROVAL.is_file() and not FIT_APPROVAL.is_symlink(), "ROOT_FIT_APPROVAL.json is required before fitting")
    approval = json.loads(FIT_APPROVAL.read_text(encoding="utf-8"))
    require(approval.get("status") == "approved", "root fit approval status is not approved")
    require(approval.get("objective_id") == OBJECTIVE_ID, "root approved a different objective")
    require(approval.get("plan_sha256") == sha256(PLAN_PATH), "root approval plan hash is stale")
    require(approval.get("source_audit_sha256") == sha256(SOURCE_AUDIT_PATH), "root approval source audit hash is stale")
    require(approval.get("fit_code_sha256") == sha256(FIT_CODE_PATH), "root approval fit-code hash is stale")
    require(approval.get("source_audit_root_sha256") == ROOT_AUDIT_SHA256, "root approval references a different source audit")
    return approval, sha256(FIT_APPROVAL)


def read_feature_inputs() -> pd.DataFrame:
    path = source_path(FEATURES_REL, FEATURES_SHA256)
    frame = pd.read_parquet(path, columns=list(FEATURE_COLUMNS))
    require(len(frame) == 52155, "feature source row count changed")
    require(frame["api_record_id"].is_unique, "feature runner key is not unique")
    require(not frame["race_id"].isna().any() and not frame["horse_id"].isna().any(), "feature IDs contain NULL")
    years = pd.to_numeric(frame["year"], errors="coerce")
    require(years.notna().all(), "feature year contains invalid values")
    frame["year"] = years.astype(int)
    return frame


def read_labels_before_year(cutoff_year: int) -> dict[int, tuple[str, int, int]]:
    """Return only training-year labels; evaluation-year rows are filter-excluded."""
    path = source_path(FEATURES_REL, FEATURES_SHA256)
    table = pq.read_table(
        path,
        columns=["year", "api_record_id", "race_id", "finish_position", "field_n"],
        filters=[("year", ">=", FIRST_TRAIN_YEAR), ("year", "<", cutoff_year)],
    )
    frame = table.to_pandas()
    year_values = pd.to_numeric(frame["year"], errors="coerce")
    require(year_values.notna().all(), "filtered training label year is invalid")
    require((year_values >= FIRST_TRAIN_YEAR).all() and (year_values < cutoff_year).all(), "filtered label reader returned a non-training year")
    require(frame["api_record_id"].is_unique, "duplicate API key in filtered training labels")
    labels: dict[int, tuple[str, int, int]] = {}
    for row in frame.itertuples(index=False):
        api_id = int(row.api_record_id)
        value = (str(row.race_id), int(row.finish_position), int(row.field_n))
        labels[api_id] = value
    return labels


def raw_runner_inputs(frame: pd.DataFrame) -> np.ndarray:
    n_rows = len(frame)
    values: dict[str, np.ndarray] = {}
    for column in LOG_COUNT_INPUTS:
        raw = pd.to_numeric(frame[column], errors="raise").to_numpy(dtype=np.float64)
        require(np.isfinite(raw).all() and (raw >= 0).all(), f"invalid nonnegative count input: {column}")
        if column.startswith("hist_"):
            require(np.equal(raw, np.floor(raw)).all() and (raw <= 5).all(), f"style support count outside integer 0..5: {column}")
        else:
            require(np.equal(raw, np.floor(raw)).all(), f"start count is not integer: {column}")
        name = f"log_{column}"
        values[name] = np.log1p(raw)

    mean5_series = pd.to_numeric(frame["mean5_rank_fraction"], errors="raise")
    mean5 = mean5_series.to_numpy(dtype=np.float64, na_value=np.nan)
    missing = mean5_series.isna().to_numpy()
    require(np.isfinite(mean5[~missing]).all(), "mean5_rank_fraction has infinite values")
    values["mean5_rank_fraction"] = mean5
    values["mean5_rank_fraction_missing"] = missing.astype(np.float64)

    for mean_col, count_col in STYLE_PAIRS:
        support = pd.to_numeric(frame[count_col], errors="raise").to_numpy(dtype=np.float64)
        mean_series = pd.to_numeric(frame[mean_col], errors="raise")
        mean = mean_series.to_numpy(dtype=np.float64, na_value=np.nan)
        require(np.isfinite(support).all() and (support >= 0).all(), f"invalid style support count: {count_col}")
        require(np.equal(support, np.floor(support)).all() and (support <= 5).all(), f"style support count outside integer 0..5: {count_col}")
        mean_missing = mean_series.isna().to_numpy()
        require(np.isfinite(mean[~mean_missing]).all(), f"style mean contains infinite values: {mean_col}")
        require(np.array_equal(mean_missing, support == 0), f"style NULL/support contract changed: {mean_col}")
        values[mean_col] = mean
        values[f"log_{count_col}"] = np.log1p(support)

    require(set(values) == set(RAW_INPUT_NAMES), "raw selector input names changed")
    matrix = np.column_stack([values[name] for name in RAW_INPUT_NAMES]).astype(np.float64, copy=False)
    require(matrix.shape == (n_rows, len(RAW_INPUT_NAMES)), "unexpected runner input matrix shape")
    require(not np.isinf(matrix).any(), "infinite runner feature value")
    return matrix


def fit_scaler(raw: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    means = np.zeros(raw.shape[1], dtype=np.float64)
    scales = np.ones(raw.shape[1], dtype=np.float64)
    transformed = np.zeros_like(raw, dtype=np.float64)
    for j in range(raw.shape[1]):
        column = raw[:, j]
        finite = np.isfinite(column)
        require(finite.any(), f"all training values missing for {RAW_INPUT_NAMES[j]}")
        mean = float(column[finite].mean(dtype=np.float64))
        scale = float(column[finite].std(ddof=0, dtype=np.float64))
        if not np.isfinite(scale) or scale == 0.0:
            scale = 1.0
        means[j] = mean
        scales[j] = scale
        transformed[finite, j] = (column[finite] - mean) / scale
        transformed[~finite, j] = 0.0
    require(np.isfinite(transformed).all(), "nonfinite standardized selector inputs")
    return means, scales, transformed


def apply_scaler(raw: np.ndarray, means: np.ndarray, scales: np.ndarray) -> np.ndarray:
    require(raw.shape[1] == len(means) == len(scales), "scaler/input width mismatch")
    result = np.zeros_like(raw, dtype=np.float64)
    for j in range(raw.shape[1]):
        column = raw[:, j]
        finite = np.isfinite(column)
        result[finite, j] = (column[finite] - means[j]) / scales[j]
        result[~finite, j] = 0.0
    require(np.isfinite(result).all(), "nonfinite transformed selector inputs")
    return result


def read_training_score(year: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    entry = TRAIN_PROVIDERS[year]
    score_path = source_path(entry["score"], entry["score_sha256"])
    meta_path = source_path(entry["meta"], entry["meta_sha256"])
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    require(meta.get("refit_max") == entry["refit_max"], f"provider refit_max mismatch for {year}")
    score = pd.read_parquet(score_path, columns=["api_record_id", "score"])
    require(score.columns.tolist() == ["api_record_id", "score"], f"unexpected training score schema: {year}")
    require(score["api_record_id"].is_unique, f"duplicate training score key: {year}")
    require(np.isfinite(score["score"].to_numpy(dtype=np.float64)).all(), f"nonfinite training raw score: {year}")
    return score, {"score_path": entry["score"], "score_sha256": entry["score_sha256"], "meta_path": entry["meta"], "meta_sha256": entry["meta_sha256"], "refit_max": entry["refit_max"]}


def compose_training_rows(years: tuple[int, ...], feature_inputs: pd.DataFrame, labels: dict[int, tuple[str, int, int]]) -> tuple[pd.DataFrame, dict[str, Any]]:
    pieces: list[pd.DataFrame] = []
    provider_receipts: dict[str, Any] = {}
    for year in years:
        scores, provider = read_training_score(year)
        features = feature_inputs.loc[feature_inputs["year"].eq(year)].copy()
        require(len(features) == len(scores), f"training score/feature row count mismatch for {year}")
        require(set(features["api_record_id"].astype(int)) == set(scores["api_record_id"].astype(int)), f"training score/feature key mismatch for {year}")
        joined = features.merge(scores, on="api_record_id", how="inner", validate="one_to_one", sort=False)
        require(len(joined) == len(features), f"training score join lost rows for {year}")
        provider_date = date.fromisoformat(provider["refit_max"])
        race_dates = pd.to_datetime(joined["race_date"], errors="coerce").dt.date
        require(race_dates.notna().all(), f"invalid race date in training year {year}")
        require(all(provider_date <= d - timedelta(days=2) for d in race_dates), f"provider T-2 check failed in training year {year}")
        label_values = joined["api_record_id"].astype(int).map(labels)
        require(label_values.notna().all(), f"training labels absent for year {year}")
        require(all(value[0] == race for value, race in zip(label_values, joined["race_id"], strict=True)), f"training label race key mismatch in {year}")
        joined["finish_position"] = [value[1] for value in label_values]
        label_field_n = np.asarray([value[2] for value in label_values], dtype=np.int64)
        require(np.array_equal(label_field_n, joined["field_n"].to_numpy(dtype=np.int64)), f"training label field_n mismatch in {year}")
        pieces.append(joined)
        provider_receipts[str(year)] = provider | {"rows": len(joined), "races": int(joined["race_id"].nunique())}
    train = pd.concat(pieces, ignore_index=True)
    require(train["api_record_id"].is_unique, "duplicate API key in joined training rows")
    return train, provider_receipts


def validate_race_rows(frame: pd.DataFrame, training: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    require(frame["api_record_id"].is_unique, "duplicate runner key in race table")
    require(frame["horse_id"].is_unique, "duplicate horse ID in race table")
    n = int(frame["field_n"].iloc[0])
    require(n >= 5 and len(frame) == n, f"incomplete or too-small Top5 roster: {frame['race_id'].iloc[0]}")
    require((frame["field_n"].astype(int) == n).all(), f"field_n varies within race: {frame['race_id'].iloc[0]}")
    require(frame["horse_number"].notna().all() and frame["horse_number"].is_unique, f"invalid horse numbers: {frame['race_id'].iloc[0]}")
    score = frame["score"].to_numpy(dtype=np.float64)
    require(np.isfinite(score).all(), f"nonfinite raw score: {frame['race_id'].iloc[0]}")
    score_sd = float(score.std(ddof=0))
    z = np.zeros_like(score) if score_sd == 0.0 else (score - float(score.mean())) / score_sd
    if training:
        positions = frame["finish_position"].to_numpy(dtype=np.int64)
        require(np.array_equal(np.sort(positions), np.arange(1, n + 1)), f"training race ranks are not a complete 1..N finish: {frame['race_id'].iloc[0]}")
        top3 = positions <= 3
        require(int(top3.sum()) == 3, f"training race must have exactly three Top3 labels: {frame['race_id'].iloc[0]}")
    else:
        top3 = np.zeros(n, dtype=bool)
    return z, top3, frame["horse_number"].to_numpy(dtype=np.int64), frame["horse_id"].astype(str).to_numpy()


def build_training_races(frame: pd.DataFrame, x: np.ndarray) -> tuple[list[TrainingRace], dict[str, int]]:
    races: list[TrainingRace] = []
    candidate_total = 0
    positive_total = 0
    field_counts: dict[str, int] = {}
    x_by_id = {int(api_id): x[i] for i, api_id in enumerate(frame["api_record_id"].to_numpy(dtype=np.int64))}
    for race_id, rows in frame.groupby("race_id", sort=True):
        rows = rows.sort_values("horse_number", kind="stable")
        n = len(rows)
        z, top3, _, _ = validate_race_rows(rows, training=True)
        api_ids = rows["api_record_id"].to_numpy(dtype=np.int64)
        x_race = np.vstack([x_by_id[int(api_id)] for api_id in api_ids])
        combinations = np.asarray(list(itertools.combinations(range(n), 5)), dtype=np.int16)
        require(combinations.ndim == 2 and combinations.shape[1] == 5, f"candidate enumeration failed for {race_id}")
        base_energy = z[combinations].sum(axis=1, dtype=np.float64)
        set_features = x_race[combinations].sum(axis=1, dtype=np.float64)
        good_mask = top3[combinations].sum(axis=1) == 3
        expected_good = math.comb(n - 3, 2)
        require(int(good_mask.sum()) == expected_good, f"positive-set count mismatch for {race_id}")
        require(np.isfinite(base_energy).all() and np.isfinite(set_features).all(), f"nonfinite candidate matrix for {race_id}")
        races.append(TrainingRace(str(race_id), base_energy, set_features, good_mask, n))
        candidate_total += len(combinations)
        positive_total += int(good_mask.sum())
        field_counts[str(n)] = field_counts.get(str(n), 0) + 1
    require(races, "no training races")
    return races, {"races": len(races), "candidate_sets": candidate_total, "positive_sets": positive_total, "field_size_races": field_counts}


def pack_races(races: list[TrainingRace]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    base = np.concatenate([race.base_energy for race in races]).astype(np.float64, copy=False)
    features = np.concatenate([race.set_features for race in races], axis=0).astype(np.float64, copy=False)
    good = np.concatenate([race.good_mask for race in races]).astype(bool, copy=False)
    groups = np.concatenate([
        np.full(len(race.base_energy), group, dtype=np.int32)
        for group, race in enumerate(races)
    ])
    require(np.isfinite(base).all() and np.isfinite(features).all(), "packed candidate arrays contain nonfinite values")
    require(np.array_equal(np.unique(groups), np.arange(len(races))), "packed race groups are not contiguous")
    return base, features, good, groups, len(races)


def grouped_logz_and_weights(energy: np.ndarray, features: np.ndarray, groups: np.ndarray, race_count: int) -> tuple[np.ndarray, np.ndarray]:
    maxima = np.full(race_count, -np.inf, dtype=np.float64)
    np.maximum.at(maxima, groups, energy)
    require(np.isfinite(maxima).all(), "nonfinite grouped energy maximum")
    shifted = np.exp(energy - maxima[groups])
    sums = np.bincount(groups, weights=shifted, minlength=race_count).astype(np.float64)
    require(np.isfinite(sums).all() and (sums > 0).all(), "invalid grouped partition sum")
    logz = maxima + np.log(sums)
    weights = shifted / sums[groups]
    expectation = np.column_stack([
        np.bincount(groups, weights=weights * features[:, j], minlength=race_count)
        for j in range(features.shape[1])
    ])
    require(expectation.shape == (race_count, features.shape[1]), "grouped feature expectation has unexpected shape")
    require(np.isfinite(expectation).all(), "nonfinite grouped feature expectation")
    return logz, expectation


def make_objective(base: np.ndarray, features: np.ndarray, good: np.ndarray, groups: np.ndarray, race_count: int):
    good_base = base[good]
    good_features = features[good]
    good_groups = groups[good]
    require(len(good_base) > 0 and np.array_equal(np.unique(good_groups), np.arange(race_count)), "one or more training races have no positive set")

    def objective(beta: np.ndarray) -> tuple[float, np.ndarray]:
        energy = base + features @ beta
        logz_all, expectation_all = grouped_logz_and_weights(energy, features, groups, race_count)
        logz_good, expectation_good = grouped_logz_and_weights(energy[good], good_features, good_groups, race_count)
        log_probability_good = logz_good - logz_all
        require(np.isfinite(log_probability_good).all() and (log_probability_good <= 1e-10).all(), "invalid positive-set Gibbs probability")
        probability_good = np.exp(np.minimum(log_probability_good, 0.0))
        loss = float(np.mean(1.0 - 2.0 * probability_good) + 0.5 * LAMBDA * np.dot(beta, beta))
        gradient_by_race = 2.0 * probability_good[:, None] * (expectation_all - expectation_good)
        gradient = np.mean(gradient_by_race, axis=0) + LAMBDA * beta
        require(np.isfinite(loss) and np.isfinite(gradient).all(), "nonfinite reward objective or gradient")
        return loss, gradient

    return objective


def validate_training_labels(train: pd.DataFrame, evaluation_year: int) -> dict[str, Any]:
    ranks_by_year: dict[str, Any] = {}
    race_count = 0
    for year, year_frame in train.groupby("year", sort=True):
        require(FIRST_TRAIN_YEAR <= int(year) < evaluation_year, f"label outside expanding training window: {year}/{evaluation_year}")
        year_races = 0
        for race_id, rows in year_frame.groupby("race_id", sort=True):
            n = int(rows["field_n"].iloc[0])
            positions = rows["finish_position"].to_numpy(dtype=np.int64)
            require(len(rows) == n and np.array_equal(np.sort(positions), np.arange(1, n + 1)), f"training label roster is not complete normal 1..N: {race_id}")
            require(int((positions <= 3).sum()) == 3, f"training race does not have exactly three Top3 labels: {race_id}")
            year_races += 1
        ranks_by_year[str(int(year))] = {"rows": int(len(year_frame)), "races": year_races, "complete_1_to_N": True, "exactly_three_top3": True}
        race_count += year_races
    require(race_count == int(train["race_id"].nunique()), "training label race summary mismatch")
    return {
        "evaluation_year": evaluation_year,
        "training_label_years": sorted(int(year) for year in train["year"].unique()),
        "training_rows": int(len(train)),
        "training_races": race_count,
        "complete_normal_finish_validation": "PASS",
        "per_year": ranks_by_year,
    }


def fit_fold(evaluation_year: int, train: pd.DataFrame, provider_receipts: dict[str, Any], label_preflight_sha256: str) -> tuple[dict[str, Any], dict[str, Any]]:
    train_years = tuple(range(FIRST_TRAIN_YEAR, evaluation_year))
    raw = raw_runner_inputs(train)
    means, scales, x = fit_scaler(raw)
    races, candidate_summary = build_training_races(train, x)
    base, set_features, good, groups, race_count = pack_races(races)
    objective = make_objective(base, set_features, good, groups, race_count)
    initial = np.zeros(len(RAW_INPUT_NAMES), dtype=np.float64)
    result = minimize(
        objective,
        initial,
        method="L-BFGS-B",
        jac=True,
        options={"maxiter": MAXITER, "ftol": FTOL, "gtol": GTOL},
    )
    require(result.success, f"L-BFGS-B did not converge for {evaluation_year}: {result.message}")
    beta = np.asarray(result.x, dtype=np.float64)
    final_loss, final_gradient = objective(beta)
    require(np.isfinite(beta).all() and np.isfinite(final_loss) and np.isfinite(final_gradient).all(), f"nonfinite fitted state for {evaluation_year}")
    gradient_max_abs = float(np.max(np.abs(final_gradient)))
    require(gradient_max_abs <= GRADIENT_ACCEPTANCE, f"fit gradient too large for {evaluation_year}: {gradient_max_abs}")
    energy = base + set_features @ beta
    logz_all, _ = grouped_logz_and_weights(energy, set_features, groups, race_count)
    logz_good, _ = grouped_logz_and_weights(energy[good], set_features[good], groups[good], race_count)
    log_probability_good = logz_good - logz_all
    require(np.isfinite(log_probability_good).all() and (log_probability_good <= 1e-10).all(), "invalid final training reward probability")
    probability_good = np.exp(np.minimum(log_probability_good, 0.0))
    mean_expected_reward = float(np.mean(2.0 * probability_good - 1.0))
    model = {
        "model_type": "F1_STYLE6_fixed_score_top5_expected_reward_selector_head",
        "evaluation_year": evaluation_year,
        "training_label_years": list(train_years),
        "training_label_max_year": int(max(train_years)),
        "objective_id": OBJECTIVE_ID,
        "objective": "mean_r[1 - 2*P_beta(actual_Top3_subset_of_S | race_r)] + lambda/2 * ||beta||^2; P_beta is Gibbs mass over all C(N,5) sets",
        "reward": {"good_set": "actual Top3 is a subset of the five selected runners", "good": 1.0, "miss": -1.0, "temperature": 1.0},
        "policy_and_surrogate_gap_warning": "Gibbs set-selection probabilities and expected reward are stochastic training surrogates conditional on the observed actual Top3. They are not calibrated probabilities or deterministic argmax coverage; the deterministic argmax is evaluated later under a separately approved outcome stage.",
        "energy": "sum(race-wise ddof=0 standardized F1_STYLE6 raw scores) + beta dot sum(standardized 11 runner inputs)",
        "score_prior": {"source": "F1_STYLE6 raw score", "within_race_ddof": 0, "zero_sd_policy": "all z scores are zero", "fixed_coefficient": 1.0},
        "feature_names": list(RAW_INPUT_NAMES),
        "feature_aggregation": "sum across exactly five selected runners",
        "feature_means": means.tolist(),
        "feature_scales": scales.tolist(),
        "beta": beta.tolist(),
        "lambda": LAMBDA,
        "optimizer": {"method": "L-BFGS-B", "start": "zero vector", "maxiter": MAXITER, "ftol": FTOL, "gtol": GTOL, "restarts": 0},
        "fit_diagnostics": {
            "success": bool(result.success),
            "status": int(result.status),
            "message": str(result.message),
            "iterations": int(result.nit),
            "function_evaluations": int(result.nfev),
            "objective_value": final_loss,
            "gradient_max_abs": gradient_max_abs,
            "mean_expected_stochastic_reward": mean_expected_reward,
            "regularized_objective_value": final_loss,
        },
        "training_rows": int(len(train)),
        "training_races": candidate_summary["races"],
        "candidate_sets": candidate_summary["candidate_sets"],
        "positive_sets": candidate_summary["positive_sets"],
        "field_size_races": candidate_summary["field_size_races"],
        "score_providers": provider_receipts,
        "features_sha256": FEATURES_SHA256,
        "fit_code_sha256": sha256(FIT_CODE_PATH),
        "plan_sha256": sha256(PLAN_PATH),
        "source_audit_sha256": sha256(SOURCE_AUDIT_PATH),
        "label_preflight_sha256": label_preflight_sha256,
    }
    receipt = {
        "status": "PASS",
        "evaluation_year": evaluation_year,
        "training_label_years": list(train_years),
        "training_rows": int(len(train)),
        "training_races": candidate_summary["races"],
        "training_label_validation": {
            "status": "PASS",
            "label_years": list(train_years),
            "complete_rank_rule": "every training race has exactly field_n rows and finish_position values 1..field_n",
            "top3_rule": "exactly three training rows per race have finish_position <= 3",
            "evaluation_year_labels_accessed": False,
            "label_preflight_sha256": label_preflight_sha256,
        },
        "candidate_sets_enumerated": candidate_summary["candidate_sets"],
        "positive_sets_enumerated": candidate_summary["positive_sets"],
        "fit_calls": 1,
        "outcome_metrics_computed": False,
        "evaluation_labels_read": False,
        "model": f"model_{evaluation_year}.json",
        "model_payload": model,
    }
    return model, receipt


def main() -> None:
    require(ROOT.is_dir() and STUDY.is_dir(), "study or project root missing")
    require(not OUT.exists() or not OUT.is_symlink(), "outputs path is invalid")
    root_audit = check_root_audit()
    require(source_path(FEATURES_REL, FEATURES_SHA256).is_file(), "feature source unavailable")
    approval, approval_sha = require_fit_approval()
    if OUT.exists():
        existing = {path.name for path in OUT.iterdir()}
        require(existing == {FIT_APPROVAL.name}, f"unexpected existing outputs; refusing partial or prior fit: {sorted(existing)}")
    else:
        OUT.mkdir()

    feature_inputs = read_feature_inputs()
    prepared_training: dict[int, tuple[pd.DataFrame, dict[str, Any]]] = {}
    preflight_folds: dict[str, Any] = {}
    for evaluation_year in EVAL_YEARS:
        train_years = tuple(range(FIRST_TRAIN_YEAR, evaluation_year))
        labels = read_labels_before_year(evaluation_year)
        train, providers = compose_training_rows(train_years, feature_inputs, labels)
        label_audit = validate_training_labels(train, evaluation_year)
        expected_races = {2024: 2492, 2025: 3129, 2026: 3783}[evaluation_year]
        require(label_audit["training_races"] == expected_races, f"training label race count changed: {evaluation_year}")
        prepared_training[evaluation_year] = (train, providers)
        preflight_folds[str(evaluation_year)] = label_audit | {
            "score_providers": providers,
            "label_year_query": {"minimum_inclusive": FIRST_TRAIN_YEAR, "evaluation_year_exclusive": evaluation_year},
            "evaluation_year_labels_accessed": False,
        }

    label_preflight = {
        "status": "PASS",
        "study": STUDY.name,
        "stage": "training-label preflight before optimizer",
        "evaluation_labels_read": False,
        "feature_inputs_loaded_with_finish_position": False,
        "label_rows_returned_by_year_filter_only": True,
        "label_source_sha256": FEATURES_SHA256,
        "label_filter_contract": "2019 <= year < evaluation_year for each expanding fit; query result years revalidated before use",
        "normal_finish_contract": "each training race has exactly field_n rows, finish_position is a permutation of 1..field_n, and exactly three rows have finish_position <= 3",
        "folds": preflight_folds,
        "fit_or_evaluation_metrics_computed": False,
        "plan_sha256": sha256(PLAN_PATH),
        "source_audit_sha256": sha256(SOURCE_AUDIT_PATH),
        "fit_code_sha256": sha256(FIT_CODE_PATH),
        "root_fit_approval_sha256": approval_sha,
    }
    preflight_path = output_path(LABEL_PREFLIGHT_NAME)
    write_json_once(preflight_path, label_preflight)
    label_preflight_sha = sha256(preflight_path)

    models: dict[int, dict[str, Any]] = {}
    fold_receipts: dict[str, Any] = {}
    for evaluation_year in EVAL_YEARS:
        train, providers = prepared_training[evaluation_year]
        model, fold_receipt = fit_fold(evaluation_year, train, providers, label_preflight_sha)
        models[evaluation_year] = model
        fold_receipts[str(evaluation_year)] = fold_receipt

    source_hashes = {FEATURES_REL: FEATURES_SHA256, ROOT_AUDIT_REL: ROOT_AUDIT_SHA256}
    for year in range(FIRST_TRAIN_YEAR, max(EVAL_YEARS)):
        entry = TRAIN_PROVIDERS[year]
        source_path(entry["score"], entry["score_sha256"])
        source_path(entry["meta"], entry["meta_sha256"])
        source_hashes[entry["score"]] = entry["score_sha256"]
        source_hashes[entry["meta"]] = entry["meta_sha256"]

    model_paths = {}
    for year, model in models.items():
        filename = f"model_{year}.json"
        path = output_path(filename)
        write_json_once(path, model)
        model_paths[filename] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    fit_receipt = {
        "status": "PASS",
        "study": STUDY.name,
        "objective_id": OBJECTIVE_ID,
        "fit_count": 3,
        "outcome_metrics_computed": False,
        "evaluation_outcomes_read": False,
        "source_audit_root_sha256": ROOT_AUDIT_SHA256,
        "source_hashes": source_hashes,
        "plan_sha256": sha256(PLAN_PATH),
        "source_audit_sha256": sha256(SOURCE_AUDIT_PATH),
        "fit_code_sha256": sha256(FIT_CODE_PATH),
        "root_fit_approval_sha256": approval_sha,
        "label_preflight_sha256": label_preflight_sha,
        "label_preflight_file": LABEL_PREFLIGHT_NAME,
        "model_artifacts": model_paths,
        "folds": fold_receipts,
        "root_source_audit_population": {
            "evaluation_rows": int(root_audit["eval_rows"]),
            "evaluation_races": int(root_audit["eval_races"]),
            "features_rows": int(root_audit["features_rows"]),
        },
    }
    path = output_path("FIT_RECEIPT.json")
    write_json_once(path, fit_receipt)
    print(json.dumps({"status": "PASS", "fit_count": 3, "receipt_sha256": sha256(path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
