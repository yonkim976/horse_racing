#!/usr/bin/env python3
"""Frozen, approval-gated fresh-history scorer and shared-pack mixture study.

The default command runs synthetic checks only.  ``--run`` is the sole real
data path and requires a supervisor receipt bound to this code, the audited
input manifest, source/rules contracts, reference assets, and bootstrap file.
This module never opens a database or changes an existing study.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import lightgbm as lgb
import numpy as np
import pandas as pd
import scipy
from scipy.optimize import minimize, minimize_scalar
from scipy.special import expit, logsumexp


PROJECT = Path(__file__).resolve().parents[4]
STUDY = PROJECT / "jeju/research/20261022_dynamic_ability_pace_v1"
EXPERIMENT = STUDY / "experiment"
INPUTS = STUDY / "inputs"
MODEL_INPUTS = INPUTS / "model_inputs.parquet"
RACE_INPUTS = INPUTS / "race_inputs.parquet"
HISTORY_LINEAGE = INPUTS / "history_lineage.parquet"
INPUT_MANIFEST = INPUTS / "input_manifest.json"
SOURCE_MANIFEST = STUDY / "audit/source_manifest.json"
CONTRACT = STUDY / "supervisor/DESIGN_CONTRACT.md"
APPROVAL = STUDY / "supervisor/DYNAMIC_ABILITY_PACE_EXECUTION_APPROVAL.json"
RULES = PROJECT / "jeju/research/20261022_joint_wager_baseline_v1/rules_contract/rules_contract.json"
REFERENCE_MANIFEST = PROJECT / "jeju/research/20261022_joint_wager_baseline_v1/assets_audit/assets_manifest.json"
BOOTSTRAP = PROJECT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT = PROJECT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
STYLE_OUTPUTS = PROJECT / "jeju/research/20261010_style_history_ablation_v1/outputs"
OUTPUTS = EXPERIMENT / "outputs"
MODELS = EXPERIMENT / "models"

CHANNELS = ("rank", "margin", "early", "recovery")
CHANNEL_SUFFIXES = (
    "all_mean",
    "exact_distance_deviation",
    "all_weight_sum",
    "exact_distance_weight_sum",
    "all_weighted_variance",
    "days_since_last_valid",
)
A_FEATURES = tuple(f"{channel}_{suffix}" for channel in CHANNELS for suffix in CHANNEL_SUFFIXES) + (
    "distance_m",
    "field_size",
    "gate_scaled",
)
RACE_SUMMARY_FEATURES = (
    "early_mean_race_mean",
    "early_mean_race_max",
    "early_mean_race_known_count",
    "recovery_mean_race_mean",
    "recovery_mean_race_max",
    "recovery_mean_race_known_count",
)
RUNNER_PHASE_FEATURES = A_FEATURES + RACE_SUMMARY_FEATURES + (
    "early_mean_race_centered",
    "recovery_mean_race_centered",
)
RACE_Z_FEATURES = RACE_SUMMARY_FEATURES + ("distance_m", "field_size")
KEY_COLUMNS = (
    "api_record_id",
    "race_id",
    "race_date",
    "year",
    "horse_id",
    "horse_number",
    "race_distance_m",
    "field_n",
    "finish_position",
)
RUNNER_LABELS = ("label_early", "label_recovery")
RACE_BASE_KEYS = ("race_id", "race_date", "year")
RACE_KEYS = ("race_id", "race_date", "year", "race_distance_m", "field_n")
RACE_META_KEYS = ("strict_cohort",)
RACE_LABEL = "label_z_early_pack_ge2"
EVAL_YEARS = (2024, 2025, 2026)
FIRST_OOS_YEAR = 2019
LAST_OOS_YEAR = 2026
EVAL_END = "2026-09-19"
POOL_ORDER = ("WIN", "PLC", "QNL", "EXA", "QPL", "TLA", "TRI")
CATEGORICAL_POOLS = frozenset(("WIN", "QNL", "EXA", "TLA", "TRI"))
POOL_MIN_STARTERS = {"WIN": 2, "QNL": 3, "EXA": 3, "TLA": 4, "TRI": 4, "PLC": 5, "QPL": 5}
BIN_EDGES = np.asarray(
    [0.0, 0.00001, 0.00005, 0.0001, 0.00025, 0.0005, 0.001, 0.0025,
     0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0], dtype=np.float64
)
EPS = 1e-15
PHASE_EPS = 1e-12
TEMPERATURE_BOUNDS = (0.35, 4.0)
HESSIAN_FLOOR = 1e-6
EXPECTED_BOOTSTRAP_SHA = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
EXPECTED_DATE_SHA = "e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84"
EXPECTED_EVAL = {"races": 1779, "runners": 17412, "dates": 269, "plc_races": 1743, "plc_unknown": 36}
EXPECTED_TOTAL = {"races": 5206, "runners": 52155}
REFERENCE_FEATURES = PROJECT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/features.parquet"
EXPECTED_REFERENCE_FEATURES_SHA = "6f6540d4786ada0c0e288ff5defc0d4c665cc796a025a074f19f3d4fe218f12f"
EXPECTED_AXIS_REFERENCE_HITS = 1023
MAX_STUDY_BYTES = 100_000_000

LGBM_COMMON = {
    "num_leaves": 15,
    "learning_rate": 0.04,
    "min_data_in_leaf": 100,
    "lambda_l2": 10.0,
    "max_bin": 63,
    "deterministic": True,
    "force_col_wise": True,
    "num_threads": 2,
    "seed": 20261022,
    "verbosity": -1,
    "feature_fraction": 1.0,
    "bagging_fraction": 1.0,
    "bagging_freq": 0,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def code_bundle_sha256() -> str:
    paths = (EXPERIMENT / "dynamic_ability_pace.py", EXPERIMENT / "test_dynamic_ability_pace.py")
    digest = hashlib.sha256()
    for path in paths:
        require(path.is_file(), f"missing approved code component: {path.name}")
        rel = path.relative_to(PROJECT).as_posix().encode("utf-8")
        digest.update(len(rel).to_bytes(4, "big"))
        digest.update(rel)
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def json_read(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    require(isinstance(value, dict), f"expected JSON object at {path}")
    return value


def confined_output_path(relative_name: str, *, allow_existing: bool = False) -> Path:
    """Resolve only a caller-independent output name beneath this experiment."""
    candidate = OUTPUTS / relative_name
    root = EXPERIMENT.resolve()
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"output path escapes the owned experiment: {relative_name}") from exc
    require(resolved != root and resolved != INPUTS.resolve(), "invalid output target")
    if not allow_existing:
        require(not resolved.exists(), f"refusing to overwrite existing output: {relative_name}")
    return resolved


def confined_model_path(relative_name: str, *, allow_existing: bool = False) -> Path:
    candidate = MODELS / relative_name
    root = EXPERIMENT.resolve()
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"model path escapes the owned experiment: {relative_name}") from exc
    if not allow_existing:
        require(not resolved.exists(), f"refusing to overwrite existing model: {relative_name}")
    return resolved


def write_bytes_once(path: Path, payload: bytes) -> None:
    require(path.parent.resolve().is_relative_to(EXPERIMENT.resolve()), "write outside experiment is forbidden")
    require(not path.exists(), f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def write_json_once(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False,
                         default=_json_default).encode("utf-8")
    write_bytes_once(path, payload + b"\n")


def _json_default(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    raise TypeError(f"unsupported JSON value {type(value).__name__}")


def write_frame_once(path: Path, frame: pd.DataFrame) -> None:
    require(path.parent.resolve().is_relative_to(EXPERIMENT.resolve()), "write outside experiment is forbidden")
    require(not path.exists(), f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=False, compression="zstd")
        stream.flush()
        os.fsync(stream.fileno())


def study_size_bytes() -> int:
    total = 0
    for path in STUDY.rglob("*"):
        if path.is_file() and not path.is_symlink():
            total += path.stat().st_size
    return total


def validate_temporal_record(record: Mapping[str, Any], target_year: int) -> None:
    require(int(record.get("target_year", -1)) == target_year, "OOS target-year mismatch")
    require(int(record.get("train_max_year", -1)) <= target_year - 2, "training labels exceed T−2 year boundary")
    require(int(record.get("calibration_year", -1)) == target_year - 1, "calibration year mismatch")
    require(int(record.get("prediction_year", -1)) == target_year, "prediction year mismatch")
    require(record.get("in_sample") is False, "in-sample predictions cannot enter OOS design")


def validate_input_manifest(manifest: Mapping[str, Any]) -> None:
    require(manifest.get("status") in {"PASS", "passed", "ready"}, "input audit manifest is not passed/ready")
    require(manifest.get("history_start") == "2017-01-01", "unexpected historical source start")
    require(manifest.get("history_max_age_days") == 730, "history window must be 730 days")
    require(manifest.get("history_cutoff") == "race_date_minus_2_calendar_days_inclusive", "T−2 cutoff mismatch")
    files = manifest.get("files")
    require(isinstance(files, dict), "input manifest must contain files object")
    for name, path, rows, races in (
        ("model_inputs.parquet", MODEL_INPUTS, EXPECTED_TOTAL["runners"], EXPECTED_TOTAL["races"]),
        ("race_inputs.parquet", RACE_INPUTS, EXPECTED_TOTAL["races"], EXPECTED_TOTAL["races"]),
        ("history_lineage.parquet", HISTORY_LINEAGE, 4 * EXPECTED_TOTAL["runners"], EXPECTED_TOTAL["races"]),
    ):
        entry = files.get(name)
        require(isinstance(entry, dict), f"input manifest missing {name}")
        require(path.is_file(), f"missing audited input {name}")
        require(entry.get("sha256") == sha256_file(path), f"input file SHA mismatch: {name}")
        require(int(entry.get("rows", -1)) == rows, f"input row count mismatch: {name}")
        require(int(entry.get("races", -1)) == races, f"input race count mismatch: {name}")
    expected_model_columns = list(KEY_COLUMNS) + ["strict_cohort"] + list(A_FEATURES) + list(
        feature for feature in RUNNER_PHASE_FEATURES if feature not in A_FEATURES
    ) + list(RUNNER_LABELS)
    expected_race_columns = list(RACE_KEYS) + ["strict_cohort"] + list(RACE_Z_FEATURES) + [RACE_LABEL]
    require(files["model_inputs.parquet"].get("columns") == expected_model_columns,
            "model input column order differs from frozen schema")
    require(files["race_inputs.parquet"].get("columns") == expected_race_columns,
            "race input column order differs from frozen schema")
    require(manifest.get("source_manifest_sha256") == sha256_file(SOURCE_MANIFEST),
            "input manifest does not pin the current source audit manifest")
    require(tuple(manifest.get("a_features", ())) == A_FEATURES, "A feature order differs from frozen allowlist")
    require(tuple(manifest.get("runner_phase_features", ())) == RUNNER_PHASE_FEATURES,
            "runner phase feature order differs from frozen allowlist")
    require(tuple(manifest.get("race_z_features", ())) == RACE_Z_FEATURES,
            "race scenario feature order differs from frozen allowlist")
    require(manifest.get("eval_cohort") == EXPECTED_EVAL, "evaluation cohort contract mismatch")
    require(manifest.get("eval_year_races") == {"2024": 637, "2025": 654, "2026": 488},
            "evaluation annual race counts mismatch")
    require(manifest.get("normal_complete_cohort") == EXPECTED_TOTAL, "normal-complete cohort contract mismatch")
    require(manifest.get("runner_key_columns") == list(KEY_COLUMNS) + ["strict_cohort"],
            "runner input key schema differs from contract")
    require(manifest.get("race_key_columns") == list(RACE_KEYS) + list(RACE_META_KEYS),
            "race input key schema differs from contract")
    require(manifest.get("runner_labels") == list(RUNNER_LABELS) and manifest.get("race_label") == RACE_LABEL,
            "input label schema differs from frozen contract")


def _validate_binary_label(series: pd.Series, name: str) -> None:
    values = series.dropna().to_numpy(dtype=np.float64)
    require(np.isin(values, (0.0, 1.0)).all(), f"non-binary label in {name}")


def _exact_binary(value: Any, name: str) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError(f"{name} must be exactly 0 or 1") from exc
    require(math.isfinite(number) and number in (0.0, 1.0), f"{name} must be exactly 0 or 1")
    return int(number)


def _string_key_series(series: pd.Series, name: str) -> None:
    require(series.notna().all(), f"null {name}")
    require(all(type(value) is str and value for value in series.array), f"{name} keys must be non-empty strings")
    require(not series.map(lambda value: "\x00" in value).any(), f"{name} contains an invalid NUL key")


def _canonical_key_hash(frame: pd.DataFrame, columns: Sequence[str]) -> str:
    """Hash an ordered key table with explicit type and length framing."""
    require(set(columns).issubset(frame.columns), "key hash columns missing")
    rows = frame.loc[:, list(columns)].sort_values(list(columns), kind="mergesort")
    digest = hashlib.sha256()
    for row in rows.itertuples(index=False, name=None):
        normalized = [value.item() if isinstance(value, np.generic) else value for value in row]
        encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _manifest_key_receipt_hash(frame: pd.DataFrame, columns: Sequence[str]) -> str:
    """Match the asset builder's UTF-8 JSON-lines receipt encoding exactly."""
    ordered = frame.loc[:, list(columns)].sort_values(columns[0], kind="mergesort")
    digest = hashlib.sha256()
    for row in ordered.itertuples(index=False, name=None):
        normalized = [value.item() if isinstance(value, np.generic) else value for value in row]
        digest.update(json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def validate_frozen_reference_keys(model: pd.DataFrame, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Join input keys to the immutable ID/label-only cohort reference."""
    require(REFERENCE_FEATURES.is_file(), "immutable normal-complete key reference missing")
    reference_sha = sha256_file(REFERENCE_FEATURES)
    require(reference_sha == EXPECTED_REFERENCE_FEATURES_SHA, "immutable key reference SHA mismatch")
    reference_columns = ["api_record_id", "race_id", "race_date", "horse_id", "horse_number",
                         "finish_position", "distance_m", "field_n"]
    reference = pd.read_parquet(REFERENCE_FEATURES, columns=reference_columns)
    require(reference["api_record_id"].dtype == np.dtype("int64"), "reference record key dtype changed")
    _string_key_series(reference["race_id"], "reference race_id")
    _string_key_series(reference["horse_id"], "reference horse_id")
    ref_distance = pd.to_numeric(reference["distance_m"], errors="coerce")
    require(ref_distance.notna().all() and np.isfinite(ref_distance.to_numpy(dtype=np.float64)).all() and
            (ref_distance.to_numpy(dtype=np.float64) == np.rint(ref_distance.to_numpy(dtype=np.float64))).all(),
            "reference distance is not an exact integer")
    reference["distance_m"] = ref_distance.astype(np.int64)
    _string_key_series(model["race_id"], "input race_id")
    _string_key_series(model["horse_id"], "input horse_id")
    key_cols = ["api_record_id", "race_id", "race_date", "horse_id", "horse_number", "finish_position",
                "race_distance_m", "field_n"]
    left = model.loc[:, key_cols].copy()
    right = reference.rename(columns={"distance_m": "race_distance_m"}).loc[:, key_cols].copy()
    left["race_date"] = pd.to_datetime(left["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    right["race_date"] = pd.to_datetime(right["race_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    require(left["race_date"].notna().all() and right["race_date"].notna().all(), "invalid date in frozen key join")
    require(len(left) == len(right) == EXPECTED_TOTAL["runners"], "frozen key row counts differ")
    require(not left.duplicated(key_cols).any() and not right.duplicated(key_cols).any(), "duplicate frozen runner key")
    merged = left.merge(right, on=key_cols, how="outer", indicator=True, validate="one_to_one")
    require(len(merged) == len(left) and bool((merged["_merge"] == "both").all()),
            "model input runner keys differ from frozen normal-complete cohort")
    ref_eval = right.loc[right["race_date"].between("2024-01-01", EVAL_END)].copy()
    input_eval = left.loc[left["race_date"].between("2024-01-01", EVAL_END)].copy()
    eval_runner_cols = ["api_record_id", "race_id", "race_date", "horse_id", "horse_number"]
    eval_race_cols = ["race_id", "race_date", "race_distance_m", "field_n"]
    receipt = manifest.get("evaluation_key_receipt")
    require(isinstance(receipt, dict), "input manifest lacks exact evaluation key receipt")
    require(receipt.get("reference_path") == REFERENCE_FEATURES.relative_to(PROJECT).as_posix() and
            receipt.get("reference_sha256") == EXPECTED_REFERENCE_FEATURES_SHA == reference_sha,
            "evaluation key receipt does not identify the frozen reference asset")
    runner_hash = _manifest_key_receipt_hash(input_eval, eval_runner_cols)
    reference_runner_hash = _manifest_key_receipt_hash(ref_eval, eval_runner_cols)
    require(runner_hash == reference_runner_hash == receipt.get("runner_key_sha256"),
            "exact evaluation runner-key receipt mismatch")
    ref_eval_races = ref_eval.loc[:, eval_race_cols].drop_duplicates()
    input_eval_races = input_eval.loc[:, eval_race_cols].drop_duplicates()
    race_hash = _manifest_key_receipt_hash(input_eval_races, eval_race_cols)
    reference_race_hash = _manifest_key_receipt_hash(ref_eval_races, eval_race_cols)
    require(race_hash == reference_race_hash == receipt.get("race_key_sha256"),
            "exact evaluation race-key receipt mismatch")
    require(receipt.get("runner_key_columns") == eval_runner_cols and receipt.get("race_key_columns") == eval_race_cols,
            "evaluation key receipt schema mismatch")
    return {
        "reference_path": REFERENCE_FEATURES.relative_to(PROJECT).as_posix(),
        "reference_sha256": reference_sha,
        "reference_key_columns": reference_columns,
        "all_runner_key_sha256": _canonical_key_hash(right, key_cols),
        "evaluation_runner_key_sha256": runner_hash,
        "evaluation_race_key_sha256": race_hash,
        "evaluation_races": int(ref_eval["race_id"].nunique()),
        "evaluation_runners": int(len(ref_eval)),
    }


def validate_history_lineage(model: pd.DataFrame, manifest: Mapping[str, Any]) -> dict[str, Any]:
    entry = manifest["files"]["history_lineage.parquet"]
    require(entry.get("sha256") == sha256_file(HISTORY_LINEAGE), "history-lineage SHA mismatch")
    lineage = pd.read_parquet(HISTORY_LINEAGE)
    expected_columns = {
        "api_record_id", "race_id", "history_start", "history_lower_inclusive", "history_cutoff_inclusive",
        "left_censored_at_2017_start", "channel", "valid_observations_all_n",
        "valid_observations_exact_distance_n", "latest_history_date", "no_valid_history",
    }
    require(set(lineage.columns) == expected_columns, "history-lineage schema mismatch")
    require(len(lineage) == 4 * len(model), "history-lineage row count mismatch")
    _string_key_series(lineage["race_id"], "history-lineage race_id")
    require(set(lineage["channel"].unique()) == set(CHANNELS), "history-lineage channels mismatch")
    require(not lineage.duplicated(["api_record_id", "channel"]).any(), "duplicate history-lineage runner/channel")
    target = model.loc[:, ["api_record_id", "race_id", "race_date"]].drop_duplicates("api_record_id")
    require(len(target) == len(model), "duplicate target runner IDs in history lineage join")
    joined = lineage.merge(target, on=["api_record_id", "race_id"], how="left", validate="many_to_one", indicator=True)
    require(joined["_merge"].eq("both").all(), "history lineage includes a runner outside the input cohort")
    target_dates = pd.to_datetime(joined["race_date"], errors="coerce")
    lower = pd.to_datetime(joined["history_lower_inclusive"], errors="coerce")
    cutoff = pd.to_datetime(joined["history_cutoff_inclusive"], errors="coerce")
    latest = pd.to_datetime(joined["latest_history_date"], errors="coerce")
    require(target_dates.notna().all() and lower.notna().all() and cutoff.notna().all(), "invalid history-lineage date")
    require(joined["history_start"].eq("2017-01-01").all(), "history-lineage start date mismatch")
    require((cutoff == target_dates - pd.Timedelta(days=2)).all(), "history cutoff is not T−2 inclusive")
    require((lower == target_dates - pd.Timedelta(days=730)).all(), "history lower boundary is not 730 days inclusive")
    no_history = joined["no_valid_history"].astype(bool)
    require(joined.loc[no_history, "latest_history_date"].isna().all(), "no-history rows have a latest date")
    require(joined.loc[~no_history, "latest_history_date"].notna().all(), "history rows lack a latest date")
    require((latest.loc[~no_history] <= cutoff.loc[~no_history]).all(), "history observation falls after T−2")
    require((latest.loc[~no_history] >= lower.loc[~no_history]).all(), "history observation exceeds 730-day lookback")
    require(joined.loc[no_history, "valid_observations_all_n"].eq(0).all(), "no-history support count is not zero")
    require(joined.loc[~no_history, "valid_observations_all_n"].gt(0).all(), "history support count is not positive")
    return {
        "path": HISTORY_LINEAGE.relative_to(PROJECT).as_posix(),
        "sha256": entry["sha256"],
        "rows": len(lineage),
        "channels": list(CHANNELS),
        "t_minus_2_and_730_day_bounds_pass": True,
        "no_future_history_rows": int((~no_history).sum()),
        "no_history_rows": int(no_history.sum()),
    }


def validate_input_frames(model: pd.DataFrame, race: pd.DataFrame, manifest: Mapping[str, Any] | None = None) -> None:
    required_model = set(KEY_COLUMNS) | set(A_FEATURES) | set(RUNNER_PHASE_FEATURES) | set(RUNNER_LABELS) | {"strict_cohort"}
    require(required_model.issubset(model.columns), f"model input columns missing: {sorted(required_model-set(model.columns))}")
    require(set(model.columns) == required_model, f"unexpected model input columns: {sorted(set(model.columns)-required_model)}")
    require(model["strict_cohort"].eq(True).all(), "model rows extend beyond normal-complete cohort")
    forbidden = {"f1_style6_score", "score", "popularity", "dividend", "favorite_id", "actual_phase", "finish_time_seconds"}
    require(not (set(model.columns) & forbidden), "forbidden model-input column present")
    require(model["api_record_id"].dtype == np.dtype("int64"), "runner record key must be int64")
    require(model["api_record_id"].notna().all() and model["api_record_id"].is_unique, "invalid runner record key")
    _string_key_series(model["race_id"], "input race_id")
    _string_key_series(model["horse_id"], "input horse_id")
    require(model["race_date"].notna().all(), "null race date")
    dates = pd.to_datetime(model["race_date"], errors="coerce")
    require(dates.notna().all(), "invalid race date")
    require((dates.dt.strftime("%Y-%m-%d").to_numpy() == model["race_date"].to_numpy()).all(),
            "race_date must use canonical ISO YYYY-MM-DD strings")
    require((dates.dt.year.to_numpy() == model["year"].to_numpy(dtype=np.int64)).all(), "date/year mismatch")
    require((model["year"].between(2017, 2026)).all(), "unexpected target year")
    require((model["field_n"] >= 3).all(), "field smaller than ordered Top-3 contract")
    require((model["horse_number"] >= 1).all(), "invalid horse number")
    for column in A_FEATURES + tuple(c for c in RUNNER_PHASE_FEATURES if c not in A_FEATURES):
        values = pd.to_numeric(model[column], errors="coerce")
        require((values.notna() | model[column].isna()).all(), f"non-numeric feature: {column}")
        require(np.isfinite(values.dropna().to_numpy(dtype=np.float64)).all(), f"non-finite feature: {column}")
    for label in RUNNER_LABELS:
        _validate_binary_label(model[label], label)
    per_race = model.groupby("race_id", sort=False, dropna=False)
    require(int(per_race.ngroups) == EXPECTED_TOTAL["races"], "normal-complete race count mismatch")
    for race_id, group in per_race:
        n = len(group)
        require(group["field_n"].nunique() == 1 and int(group["field_n"].iloc[0]) == n,
                f"roster/field size mismatch: {race_id}")
        require(group["horse_number"].is_unique and group["horse_id"].is_unique,
                f"duplicate runner within race: {race_id}")
        positions = group["finish_position"].to_numpy(dtype=np.int64)
        require(sorted(positions.tolist()) == list(range(1, n + 1)), f"invalid complete finish ranks: {race_id}")
        require(group["race_date"].nunique() == 1 and group["year"].nunique() == 1,
                f"race date/year vary within race: {race_id}")
        expected_gate = (group["horse_number"].to_numpy(dtype=np.float64) - 1.0) / (n - 1.0)
        actual_gate = group["gate_scaled"].to_numpy(dtype=np.float64)
        require(np.allclose(expected_gate, actual_gate, rtol=0.0, atol=1e-12), f"gate feature mismatch: {race_id}")
    require(len(model) == EXPECTED_TOTAL["runners"], "normal-complete runner count mismatch")
    evaluation = model.loc[model["year"].between(2024, 2026)].copy()
    evaluation["race_date_parsed"] = pd.to_datetime(evaluation["race_date"])
    evaluation = evaluation.loc[evaluation["race_date_parsed"] <= EVAL_END]
    eval_races = evaluation.drop_duplicates("race_id")
    require((len(eval_races), len(evaluation), eval_races["race_date_parsed"].nunique()) ==
            (EXPECTED_EVAL["races"], EXPECTED_EVAL["runners"], EXPECTED_EVAL["dates"]),
            "evaluation cohort counts/dates mismatch")
    plc_unknown = int((eval_races["field_n"] == 7).sum())
    require(plc_unknown == EXPECTED_EVAL["plc_unknown"], "PLC unknown opening-count denominator changed")
    require(int((eval_races["field_n"] >= 8).sum()) == EXPECTED_EVAL["plc_races"], "PLC eligible denominator changed")

    required_race = set(RACE_KEYS) | set(RACE_Z_FEATURES) | set(RACE_META_KEYS) | {RACE_LABEL}
    require(required_race.issubset(race.columns), f"race input columns missing: {sorted(required_race-set(race.columns))}")
    require(set(race.columns) == required_race, f"unexpected race input columns: {sorted(set(race.columns)-required_race)}")
    require(race["strict_cohort"].eq(True).all(), "race rows extend beyond normal-complete cohort")
    require(not (set(race.columns) & forbidden), "forbidden race-input column present")
    _string_key_series(race["race_id"], "race input race_id")
    require(race["race_date"].notna().all(), "null race input date")
    require(race["race_date"].map(lambda v: isinstance(v, str) and len(v) == 10).all(),
            "race input date must be a string")
    require(race["race_id"].is_unique, "duplicate race input key")
    require(len(race) == EXPECTED_TOTAL["races"] and set(race["race_id"]) == set(model["race_id"]),
            "race input roster differs from runner cohort")
    _validate_binary_label(race[RACE_LABEL], RACE_LABEL)
    race_by_id = model.groupby("race_id", sort=False).first()
    aligned = race.set_index("race_id").loc[race_by_id.index]
    require(np.array_equal(aligned["year"].to_numpy(), race_by_id["year"].to_numpy()), "race year mismatch")
    require(np.array_equal(aligned["race_date"].astype(str).to_numpy(), race_by_id["race_date"].astype(str).to_numpy()),
            "race date mismatch")
    require(np.array_equal(aligned["race_distance_m"].to_numpy(), race_by_id["race_distance_m"].to_numpy()),
            "race distance metadata mismatch")
    require(np.array_equal(aligned["field_n"].to_numpy(), race_by_id["field_n"].to_numpy()),
            "race field size metadata mismatch")
    require((race["distance_m"].to_numpy(dtype=np.float64) == race["race_distance_m"].to_numpy(dtype=np.float64)).all(),
            "race distance metadata/feature mismatch")
    require((race["field_size"].to_numpy(dtype=np.float64) == race["field_n"].to_numpy(dtype=np.float64)).all(),
            "race field metadata/feature mismatch")
    for feature in RACE_Z_FEATURES:
        values = pd.to_numeric(race[feature], errors="coerce")
        require((values.notna() | race[feature].isna()).all(), f"non-numeric race feature: {feature}")
        require(np.isfinite(values.dropna().to_numpy(dtype=np.float64)).all(), f"non-finite race feature: {feature}")
    if manifest is not None:
        frozen = validate_frozen_reference_keys(model, manifest)
        require(frozen["evaluation_races"] == EXPECTED_EVAL["races"] and
                frozen["evaluation_runners"] == EXPECTED_EVAL["runners"],
                "frozen exact evaluation key reference counts changed")


def ordered_race_groups(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Return race-contiguous row order and group sizes for LightGBM PL loss."""
    _string_key_series(frame["race_id"], "PL race_id")
    race_values = frame["race_id"].to_numpy(dtype=object)
    horse_values = frame["horse_number"].to_numpy(dtype=np.int64)
    # Factorization avoids implicit str coercion, which could collapse mixed keys.
    race_order = sorted(set(race_values.tolist()))
    categories = pd.Categorical(race_values, categories=race_order, ordered=True)
    require((categories.codes >= 0).all(), "unrecognized PL race key")
    order = np.lexsort((horse_values, categories.codes))
    ordered = frame.iloc[order]
    group_sizes = ordered.groupby("race_id", sort=False).size().to_numpy(dtype=np.int32)
    return order, group_sizes


def _group_slices(group_sizes: Sequence[int], expected_rows: int) -> Iterator[slice]:
    offset = 0
    for raw_size in group_sizes:
        size = int(raw_size)
        require(size >= 3, "PL race has fewer than three runners")
        yield slice(offset, offset + size)
        offset += size
    require(offset == expected_rows, "group sizes do not cover all runner rows")


def ordered_top3_pl_nll_grad_hess(
    scores: Sequence[float],
    ranks: Sequence[int],
    group_sizes: Sequence[int],
    *,
    hessian_floor: float | None = None,
    validate_labels: bool = True,
) -> tuple[float, np.ndarray, np.ndarray]:
    """Race-mean exact ordered Top-3 PL NLL and derivatives (unfloored by default)."""
    score = np.asarray(scores, dtype=np.float64)
    raw_rank = np.asarray(ranks, dtype=np.float64)
    require(score.ndim == raw_rank.ndim == 1 and len(score) == len(raw_rank), "invalid PL score/label vectors")
    require(np.isfinite(score).all(), "non-finite PL scores")
    require(hessian_floor is None or (math.isfinite(hessian_floor) and hessian_floor > 0),
            "invalid PL Hessian floor")
    if validate_labels:
        require(np.isfinite(raw_rank).all() and (raw_rank == np.rint(raw_rank)).all(),
                "PL labels must be finite integer ranks")
    rank = raw_rank.astype(np.int64)
    sizes = np.asarray(group_sizes, dtype=np.int64)
    require(len(sizes) > 0, "PL objective has no races")
    counts = sizes.astype(np.int64)
    require((counts >= 3).all() and int(counts.sum()) == len(score), "invalid PL group sizes")
    starts = np.concatenate((np.asarray([0], dtype=np.int64), np.cumsum(counts[:-1])))
    group_ids = np.repeat(np.arange(len(counts), dtype=np.int64), counts)
    local_rank = rank.astype(np.int64)
    per_row_n = counts[group_ids]
    if validate_labels:
        require(((local_rank >= 1) & (local_rank <= per_row_n)).all(), "PL rank outside its race")
        # A complete permutation is enough to prove each rank is unique within race.
        pair_codes = group_ids * (int(counts.max()) + 1) + local_rank
        require(len(np.unique(pair_codes)) == len(pair_codes), "PL race ranks are duplicated")
    grad_sum = np.zeros_like(score)
    hess_sum = np.zeros_like(score)
    loss_sum = 0.0
    for target_rank in (1, 2, 3):
        active = local_rank >= target_rank
        masked = np.where(active, score, -np.inf)
        group_max = np.maximum.reduceat(masked, starts)
        exp_shifted = np.exp(np.where(active, score - group_max[group_ids], -np.inf))
        denominator = np.add.reduceat(exp_shifted, starts)
        require((denominator > 0).all(), "empty stage denominator")
        log_den = group_max + np.log(denominator)
        winner_scores = np.add.reduceat(np.where(local_rank == target_rank, score, 0.0), starts)
        loss_sum += float(np.sum(log_den - winner_scores))
        probability = exp_shifted / denominator[group_ids]
        grad_sum += probability - (local_rank == target_rank).astype(np.float64)
        hess_sum += probability * (1.0 - probability)
    count = float(len(counts))
    loss, grad, hess = loss_sum / count, grad_sum / count, hess_sum / count
    require(math.isfinite(loss) and np.isfinite(grad).all() and np.isfinite(hess).all(), "non-finite PL derivatives")
    if hessian_floor is not None:
        require(math.isfinite(hessian_floor) and hessian_floor > 0, "invalid Hessian floor")
        hess = np.maximum(hess, hessian_floor)
    return float(loss), grad, hess


def ordered_top3_pl_nll(scores: Sequence[float], ranks: Sequence[int], group_sizes: Sequence[int]) -> float:
    return ordered_top3_pl_nll_grad_hess(scores, ranks, group_sizes)[0]


def lightgbm_ordered_top3_objective(predictions: np.ndarray, dataset: lgb.Dataset) -> tuple[np.ndarray, np.ndarray]:
    labels = dataset.get_label()
    group_sizes = dataset.get_group()
    require(group_sizes is not None and len(group_sizes) > 0, "LightGBM PL dataset lacks race groups")
    _, grad_mean, hess_mean = ordered_top3_pl_nll_grad_hess(predictions, labels, group_sizes)
    # LightGBM's lambda_l2 acts on the supplied summed objective. Each race
    # contributes one full ordered Top-3 loss; floor the diagonal Hessian only
    # after converting mean helper derivatives back to the sum scale.
    races = float(len(group_sizes))
    grad_sum = races * grad_mean
    hess_sum = np.maximum(races * hess_mean, HESSIAN_FLOOR)
    return grad_sum, hess_sum


def make_lightgbm_ordered_top3_objective(ranks: Sequence[int], group_sizes: Sequence[int]):
    """Prevalidate immutable race labels once, then use the fast grouped PL callback."""
    rank_values = np.asarray(ranks, dtype=np.float64)
    sizes = np.asarray(group_sizes, dtype=np.int32)
    # Synthetic zero scores exercise all label/group validation before fit.
    ordered_top3_pl_nll_grad_hess(np.zeros(len(rank_values)), rank_values, sizes)

    def objective(predictions: np.ndarray, _dataset: lgb.Dataset) -> tuple[np.ndarray, np.ndarray]:
        _, grad_mean, hess_mean = ordered_top3_pl_nll_grad_hess(
            predictions, rank_values, sizes, validate_labels=False
        )
        races = float(len(sizes))
        return races * grad_mean, np.maximum(races * hess_mean, HESSIAN_FLOOR)

    return objective


def observed_order_logprob(scores: Sequence[float], ranks: Sequence[int]) -> float:
    score = np.asarray(scores, dtype=np.float64)
    raw_rank = np.asarray(ranks, dtype=np.float64)
    require(raw_rank.ndim == 1 and np.isfinite(raw_rank).all() and (raw_rank == np.rint(raw_rank)).all(),
            "observed PL ranks must be finite exact integers")
    rank = raw_rank.astype(np.int64)
    require(score.ndim == rank.ndim == 1 and len(score) == len(rank) and len(score) >= 3,
            "invalid observed-order probability vectors")
    require(np.isfinite(score).all(), "non-finite utility in PL log probability")
    n = len(score)
    require(sorted(rank.tolist()) == list(range(1, n + 1)), "observed ranks are incomplete or tied")
    winners = [int(np.flatnonzero(rank == target)[0]) for target in (1, 2, 3)]
    remaining = np.ones(n, dtype=bool)
    result = 0.0
    for winner in winners:
        active = np.flatnonzero(remaining)
        result += float(score[winner] - logsumexp(score[active]))
        remaining[winner] = False
    return result


def fit_joint_temperature(records: Sequence[Mapping[str, Any]], *, bounds: tuple[float, float] = TEMPERATURE_BOUNDS) -> dict[str, Any]:
    require(len(records) > 0, "temperature calibration has no races")

    def objective(temperature: float) -> float:
        require(temperature > 0 and math.isfinite(temperature), "invalid temperature trial")
        losses = [
            -observed_order_logprob(np.asarray(row["scores"], dtype=np.float64) / temperature, row["ranks"])
            for row in records
        ]
        result = float(np.mean(losses))
        require(math.isfinite(result), "non-finite joint temperature objective")
        return result

    result = minimize_scalar(objective, bounds=bounds, method="bounded", options={"xatol": 1e-12})
    require(result.success and math.isfinite(float(result.x)), f"joint temperature optimizer failed: {result.message}")
    trials = [(float(bounds[0]), objective(float(bounds[0]))),
              (float(bounds[1]), objective(float(bounds[1]))),
              (float(result.x), objective(float(result.x)))]
    temperature, loss = min(trials, key=lambda pair: (pair[1], pair[0]))
    return {
        "temperature": temperature,
        "objective_nll": loss,
        "boundary": bool(abs(temperature - bounds[0]) <= 1e-12 or abs(temperature - bounds[1]) <= 1e-12),
        "lower_bound_objective": trials[0][1],
        "upper_bound_objective": trials[1][1],
        "optimizer_x": float(result.x),
        "optimizer_success": bool(result.success),
        "optimizer_message": str(result.message),
        "races": len(records),
        "method": "scipy.optimize.minimize_scalar(method=bounded,xatol=1e-12)",
    }


def _binary_race_groups(labels: np.ndarray, race_ids: Sequence[Any]) -> list[np.ndarray]:
    require(len(labels) == len(race_ids), "binary label/race key size mismatch")
    require(all(type(race_id) is str and race_id for race_id in race_ids), "binary race keys must be non-empty strings")
    grouped: dict[str, list[int]] = defaultdict(list)
    for i, race_id in enumerate(race_ids):
        if np.isfinite(labels[i]):
            grouped[race_id].append(i)
    return [np.asarray(indices, dtype=np.int64) for _, indices in sorted(grouped.items(), key=lambda item: item[0])]


def _binary_weighted_mean_loss(logits: np.ndarray, labels: np.ndarray, race_ids: Sequence[Any], temperature: float) -> float:
    require(temperature > 0 and math.isfinite(temperature), "invalid binary temperature")
    values = np.asarray(labels, dtype=np.float64)
    logits_arr = np.asarray(logits, dtype=np.float64)
    require(values.shape == logits_arr.shape and np.isfinite(logits_arr).all(), "invalid binary calibration arrays")
    p = np.clip(expit(logits_arr / temperature), PHASE_EPS, 1.0 - PHASE_EPS)
    losses = -(values * np.log(p) + (1.0 - values) * np.log1p(-p))
    race_losses = [float(np.mean(losses[indices])) for indices in _binary_race_groups(values, race_ids)]
    require(len(race_losses) > 0, "binary calibration has no labeled race")
    result = float(np.mean(race_losses))
    require(math.isfinite(result), "non-finite binary calibration loss")
    return result


def fit_binary_temperature(logits: Sequence[float], labels: Sequence[float], race_ids: Sequence[Any]) -> dict[str, Any]:
    logits_arr = np.asarray(logits, dtype=np.float64)
    labels_arr = np.asarray(labels, dtype=np.float64)
    require(logits_arr.shape == labels_arr.shape and len(labels_arr) == len(race_ids), "binary calibration shape mismatch")
    known = np.isfinite(labels_arr)
    logits_arr, labels_arr = logits_arr[known], labels_arr[known]
    kept_races = [race_id for race_id, use in zip(race_ids, known) if use]
    require(np.isin(labels_arr, (0.0, 1.0)).all(), "binary calibration labels are not 0/1")
    positives = int(np.sum(labels_arr == 1.0))
    negatives = int(np.sum(labels_arr == 0.0))
    require(positives >= 10 and negatives >= 10, "binary calibration support below 10 positive/negative labels")

    def objective(temperature: float) -> float:
        return _binary_weighted_mean_loss(logits_arr, labels_arr, kept_races, temperature)

    result = minimize_scalar(objective, bounds=TEMPERATURE_BOUNDS, method="bounded", options={"xatol": 1e-12})
    require(result.success and math.isfinite(float(result.x)), f"binary temperature optimizer failed: {result.message}")
    trials = [(TEMPERATURE_BOUNDS[0], objective(TEMPERATURE_BOUNDS[0])),
              (TEMPERATURE_BOUNDS[1], objective(TEMPERATURE_BOUNDS[1])),
              (float(result.x), objective(float(result.x)))]
    temperature, loss = min(trials, key=lambda pair: (pair[1], pair[0]))
    return {
        "temperature": float(temperature),
        "objective_nll": float(loss),
        "boundary": bool(abs(temperature - TEMPERATURE_BOUNDS[0]) <= 1e-12 or
                         abs(temperature - TEMPERATURE_BOUNDS[1]) <= 1e-12),
        "positive_labels": positives,
        "negative_labels": negatives,
        "labeled_races": len(set(kept_races)),
        "weighting": "labeled-runner loss weights sum to one per labeled race; mean over labeled races",
        "clipping_epsilon": PHASE_EPS,
        "optimizer_success": bool(result.success),
        "optimizer_message": str(result.message),
    }


def scenario_design(early_probability: Sequence[float], recovery_probability: Sequence[float], z: int) -> np.ndarray:
    early = np.asarray(early_probability, dtype=np.float64)
    recovery = np.asarray(recovery_probability, dtype=np.float64)
    require(early.ndim == recovery.ndim == 1 and len(early) == len(recovery) >= 3,
            "invalid phase probability vectors")
    require(np.isfinite(early).all() and np.isfinite(recovery).all(), "non-finite phase probability")
    require(((0.0 <= early) & (early <= 1.0)).all() and ((0.0 <= recovery) & (recovery <= 1.0)).all(),
            "phase probabilities outside [0,1]")
    z_value = _exact_binary(z, "scenario indicator")
    l = early - float(early.mean())
    h = recovery - float(recovery.mean())
    return np.column_stack((l, h, float(z_value) * l, float(z_value) * h))


def conditional_gamma_objective_grad_hess(
    gamma: Sequence[float],
    races: Sequence[Mapping[str, Any]],
    *,
    penalty: float = 0.01,
) -> tuple[float, np.ndarray, np.ndarray]:
    """Conditional full-field Top-3 NLL and exact 4x4 Hessian for observed Z."""
    coef = np.asarray(gamma, dtype=np.float64)
    require(coef.shape == (4,) and np.isfinite(coef).all(), "gamma must have four finite coefficients")
    require(len(races) > 0 and penalty >= 0 and math.isfinite(penalty), "invalid gamma fit inputs")
    total_loss = 0.0
    total_grad = np.zeros(4, dtype=np.float64)
    total_hess = np.zeros((4, 4), dtype=np.float64)
    for race in races:
        raw_ranks = np.asarray(race["ranks"], dtype=np.float64)
        require(raw_ranks.ndim == 1 and np.isfinite(raw_ranks).all() and
                (raw_ranks == np.rint(raw_ranks)).all(),
                "conditional expert ranks must be finite exact integers")
        ranks = raw_ranks.astype(np.int64)
        a = np.asarray(race["a"], dtype=np.float64)
        z = _exact_binary(race["z"], "conditional expert Z label")
        x = scenario_design(race["p_early"], race["p_recovery"], z)
        require(a.shape == ranks.shape == (len(x),) and np.isfinite(a).all(), "invalid conditional expert race")
        require(sorted(ranks.tolist()) == list(range(1, len(ranks) + 1)), "invalid conditional expert ranks")
        utility = a + x @ coef
        remaining = np.ones(len(utility), dtype=bool)
        race_loss = 0.0
        race_grad = np.zeros(4, dtype=np.float64)
        race_hess = np.zeros((4, 4), dtype=np.float64)
        for target_rank in (1, 2, 3):
            winner = int(np.flatnonzero(ranks == target_rank)[0])
            active = np.flatnonzero(remaining)
            active_x = x[active]
            p = np.exp(utility[active] - logsumexp(utility[active]))
            race_loss += float(logsumexp(utility[active]) - utility[winner])
            race_grad += active_x.T @ p - x[winner]
            mean_x = active_x.T @ p
            race_hess += active_x.T @ (active_x * p[:, None]) - np.outer(mean_x, mean_x)
            remaining[winner] = False
        total_loss += race_loss
        total_grad += race_grad
        total_hess += race_hess
    count = float(len(races))
    loss = total_loss / count + 0.5 * penalty * float(coef @ coef)
    grad = total_grad / count + penalty * coef
    hess = total_hess / count + penalty * np.eye(4, dtype=np.float64)
    require(math.isfinite(loss) and np.isfinite(grad).all() and np.isfinite(hess).all(), "non-finite gamma objective")
    return float(loss), grad, hess


def fit_gamma(races: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    require(len(races) > 0, "B conditional expert fit has no usable Z-labeled races")

    def objective(coef: np.ndarray) -> tuple[float, np.ndarray]:
        loss, grad, _ = conditional_gamma_objective_grad_hess(coef, races)
        return loss, grad

    result = minimize(
        objective,
        np.zeros(4, dtype=np.float64),
        method="L-BFGS-B",
        jac=True,
        options={"maxiter": 1000, "ftol": 1e-12, "gtol": 1e-8, "maxls": 40, "maxcor": 10},
    )
    coef = np.asarray(result.x, dtype=np.float64)
    loss, grad, hess = conditional_gamma_objective_grad_hess(coef, races)
    eig = np.linalg.eigvalsh(hess)
    require(bool(result.success), f"gamma optimizer did not converge: {result.message}")
    require(np.isfinite(coef).all() and np.isfinite(eig).all() and float(eig.min()) > 0.0,
            "gamma solution is non-finite or unidentifiable")
    require(np.linalg.norm(grad, ord=np.inf) <= 5e-6, "gamma optimizer gradient residual too large")
    return {
        "gamma": coef.tolist(),
        "objective": float(loss),
        "gradient_inf_norm": float(np.linalg.norm(grad, ord=np.inf)),
        "hessian_eigenvalues": eig.tolist(),
        "training_races": len(races),
        "penalty": 0.01,
        "optimizer": "scipy.optimize.minimize(method=L-BFGS-B,zero_init,fixed_options)",
        "optimizer_success": bool(result.success),
        "optimizer_message": str(result.message),
        "iterations": int(result.nit),
        "function_evaluations": int(result.nfev),
    }


def _mixture_observed_logprob(
    base_a: np.ndarray,
    p_early: np.ndarray,
    p_recovery: np.ndarray,
    z_probability: float,
    ranks: np.ndarray,
    gamma: np.ndarray,
    temperature: float,
) -> float:
    require(0.0 <= z_probability <= 1.0 and math.isfinite(z_probability), "invalid scenario probability")
    logs = []
    for z in (0, 1):
        x = scenario_design(p_early, p_recovery, z)
        utility = (base_a + x @ gamma) / temperature
        logs.append(observed_order_logprob(utility, ranks))
    return float(np.logaddexp(math.log1p(-z_probability) + logs[0] if z_probability < 1 else -np.inf,
                              math.log(z_probability) + logs[1] if z_probability > 0 else -np.inf))


def fit_mixture_temperature(records: Sequence[Mapping[str, Any]], gamma: Sequence[float]) -> dict[str, Any]:
    coef = np.asarray(gamma, dtype=np.float64)
    require(coef.shape == (4,) and np.isfinite(coef).all(), "invalid gamma for B calibration")
    require(len(records) > 0, "B temperature calibration has no races")

    def objective(temperature: float) -> float:
        losses = [
            -_mixture_observed_logprob(
                np.asarray(row["a"], dtype=np.float64),
                np.asarray(row["p_early"], dtype=np.float64),
                np.asarray(row["p_recovery"], dtype=np.float64),
                float(row["q_z"]),
                np.asarray(row["ranks"], dtype=np.int64),
                coef,
                temperature,
            )
            for row in records
        ]
        result = float(np.mean(losses))
        require(math.isfinite(result), "non-finite B mixture calibration objective")
        return result

    result = minimize_scalar(objective, bounds=TEMPERATURE_BOUNDS, method="bounded", options={"xatol": 1e-12})
    require(result.success and math.isfinite(float(result.x)), f"B mixture temperature optimizer failed: {result.message}")
    trials = [(TEMPERATURE_BOUNDS[0], objective(TEMPERATURE_BOUNDS[0])),
              (TEMPERATURE_BOUNDS[1], objective(TEMPERATURE_BOUNDS[1])),
              (float(result.x), objective(float(result.x)))]
    temperature, loss = min(trials, key=lambda pair: (pair[1], pair[0]))
    return {
        "temperature": float(temperature),
        "objective_nll": float(loss),
        "boundary": bool(abs(temperature - TEMPERATURE_BOUNDS[0]) <= 1e-12 or
                         abs(temperature - TEMPERATURE_BOUNDS[1]) <= 1e-12),
        "lower_bound_objective": trials[0][1],
        "upper_bound_objective": trials[1][1],
        "optimizer_success": bool(result.success),
        "optimizer_message": str(result.message),
        "races": len(records),
    }


def iter_pl_top3(scores: Sequence[float]) -> Iterator[tuple[int, int, int, float]]:
    """Yield one race's exact full-field ordered Top-3 PL outcomes."""
    utility = np.asarray(scores, dtype=np.float64)
    require(utility.ndim == 1 and len(utility) >= 3 and np.isfinite(utility).all(), "invalid PL utilities")
    n = len(utility)
    all_norm = float(logsumexp(utility))
    for i in range(n):
        logp_i = float(utility[i] - all_norm)
        remaining_i = np.arange(n) != i
        after_i = np.flatnonzero(remaining_i)
        norm_i = float(logsumexp(utility[after_i]))
        for j in after_i:
            logp_ij = logp_i + float(utility[j] - norm_i)
            remaining_ij = remaining_i & (np.arange(n) != j)
            after_ij = np.flatnonzero(remaining_ij)
            norm_ij = float(logsumexp(utility[after_ij]))
            for k in after_ij:
                probability = math.exp(logp_ij + float(utility[k] - norm_ij))
                yield i, int(j), int(k), probability


def _new_ticket_maps() -> dict[str, defaultdict[tuple[int, ...], float]]:
    return {pool: defaultdict(float) for pool in POOL_ORDER}


def probability_maps_from_scenarios(
    scenario_utilities: Sequence[Sequence[float]],
    scenario_weights: Sequence[float],
    horse_numbers: Sequence[int],
    plc_top: int | None,
) -> tuple[dict[str, dict[tuple[int, ...], float]], dict[str, np.ndarray], float]:
    """Aggregate full ordered Q transiently into pool maps and runner marginals."""
    require(len(scenario_utilities) > 0 and len(scenario_utilities) == len(scenario_weights),
            "scenario utility/weight count mismatch")
    numbers = np.asarray(horse_numbers, dtype=np.int64)
    require(numbers.ndim == 1 and len(numbers) >= 3 and len(set(numbers.tolist())) == len(numbers),
            "invalid horse-number roster")
    weights = np.asarray(scenario_weights, dtype=np.float64)
    require(np.isfinite(weights).all() and (weights >= 0).all() and abs(float(weights.sum()) - 1.0) <= 1e-12,
            "scenario weights must be a probability distribution")
    if plc_top is not None:
        require(int(plc_top) in (2, 3), "PLC event depth must be Top2/Top3 or unknown")
    maps = _new_ticket_maps()
    p_win = np.zeros(len(numbers), dtype=np.float64)
    p_exact2 = np.zeros(len(numbers), dtype=np.float64)
    p_exact3 = np.zeros(len(numbers), dtype=np.float64)
    full_mass = 0.0
    number_range = np.arange(len(numbers))
    for utility_values, weight in zip(scenario_utilities, weights):
        utility = np.asarray(utility_values, dtype=np.float64)
        require(utility.shape == numbers.shape and np.isfinite(utility).all(), "scenario score roster mismatch")
        scenario_mass = 0.0
        for i, j, k, q in iter_pl_top3(utility):
            scenario_mass += q
            q_weighted = q * float(weight)
            p_win[i] += q_weighted
            p_exact2[j] += q_weighted
            p_exact3[k] += q_weighted
            ni, nj, nk = int(numbers[i]), int(numbers[j]), int(numbers[k])
            maps["QNL"][tuple(sorted((ni, nj)))] += q_weighted
            maps["EXA"][(ni, nj)] += q_weighted
            maps["TLA"][tuple(sorted((ni, nj, nk)))] += q_weighted
            maps["TRI"][(ni, nj, nk)] += q_weighted
            for pair in combinations(sorted((ni, nj, nk)), 2):
                maps["QPL"][pair] += q_weighted
        require(abs(scenario_mass - 1.0) <= 3e-11, "PL ordered-triple mass mismatch in scenario")
        full_mass += float(weight) * scenario_mass
    p_top2 = p_win + p_exact2
    p_top3 = p_top2 + p_exact3
    maps["WIN"] = defaultdict(float, {(int(numbers[ix]),): float(p_win[ix]) for ix in range(len(numbers))})
    if plc_top is not None:
        place = p_top2 if plc_top == 2 else p_top3
        maps["PLC"] = defaultdict(float, {(int(numbers[ix]),): float(place[ix]) for ix in range(len(numbers))})
    else:
        maps["PLC"] = defaultdict(float)
    result_maps = {pool: dict(items) for pool, items in maps.items()}
    marginal = {
        "p_win": p_win,
        "p_exact2": p_exact2,
        "p_exact3": p_exact3,
        "p_top2": p_top2,
        "p_top3": p_top3,
    }
    require(abs(full_mass - 1.0) <= 3e-11, f"mixture ordered triple mass is {full_mass:.17g}")
    require(np.isfinite(np.concatenate(list(marginal.values()))).all(), "non-finite mixture marginal")
    require((p_win >= 0).all() and (p_top2 >= 0).all() and (p_top3 >= 0).all(), "negative mixture marginal")
    require(abs(float(p_win.sum()) - 1.0) <= 3e-11, "win marginal mass mismatch")
    require(abs(float(p_exact2.sum()) - 1.0) <= 3e-11 and abs(float(p_exact3.sum()) - 1.0) <= 3e-11,
            "exact-rank marginal mass mismatch")
    require(abs(float(p_top2.sum()) - 2.0) <= 3e-11 and abs(float(p_top3.sum()) - 3.0) <= 3e-11,
            "Top-k marginal mass mismatch")
    require(np.all(p_win <= p_top2 + 3e-12) and np.all(p_top2 <= p_top3 + 3e-12),
            "nested runner marginal invariant failed")
    expected_mass = {"WIN": 1.0, "QNL": 1.0, "EXA": 1.0, "QPL": 3.0, "TLA": 1.0, "TRI": 1.0}
    if plc_top is not None:
        expected_mass["PLC"] = float(plc_top)
    for pool, mass in expected_mass.items():
        got = float(sum(result_maps[pool].values()))
        require(abs(got - mass) <= 5e-11, f"{pool} event-map mass is {got:.17g}, expected {mass}")
    return result_maps, marginal, full_mass


def plc_top_for_actual_field(actual_field_n: int, opening_field_n: int | None = None) -> tuple[int | None, str]:
    if opening_field_n is not None:
        n_open = int(opening_field_n)
        if 5 <= n_open <= 7:
            return 2, "observed_sales_opening_count"
        if n_open >= 8:
            return 3, "observed_sales_opening_count"
        return None, "below_statutory_minimum"
    if int(actual_field_n) >= 8:
        return 3, "actual_starter_lower_bound_assuming_no_post_open_additions"
    return None, "opening_field_unknown"


def truth_ticket_keys(pool: str, horse_numbers: Sequence[int], ranks: Sequence[int], plc_top: int | None) -> set[tuple[int, ...]]:
    require(pool in POOL_MIN_STARTERS, f"unknown pool {pool}")
    numbers = [int(value) for value in horse_numbers]
    rank_values = [int(value) for value in ranks]
    require(len(numbers) == len(rank_values) and len(set(numbers)) == len(numbers), "truth roster mismatch")
    require(len(numbers) >= POOL_MIN_STARTERS[pool],
            f"{pool} event scoring is below the statutory minimum starter count")
    by_rank = {rank: number for number, rank in zip(numbers, rank_values)}
    require(set(by_rank) >= {1, 2, 3}, "truth does not contain ordered Top-3")
    first, second, third = by_rank[1], by_rank[2], by_rank[3]
    if pool == "WIN":
        return {(first,)}
    if pool == "PLC":
        require(plc_top in (2, 3), "PLC truth requested for unknown event depth")
        return {(number,) for number, rank in zip(numbers, rank_values) if rank <= plc_top}
    if pool == "QNL":
        return {tuple(sorted((first, second)))}
    if pool == "EXA":
        return {(first, second)}
    if pool == "QPL":
        return {tuple(sorted(pair)) for pair in combinations((first, second, third), 2)}
    if pool == "TLA":
        return {tuple(sorted((first, second, third)))}
    if pool == "TRI":
        return {(first, second, third)}
    raise RuntimeError(f"unknown pool {pool}")


def _selected_ticket(tickets: Mapping[tuple[int, ...], float], tolerance: float = 1e-12) -> tuple[tuple[int, ...], float]:
    require(bool(tickets) and 0.0 < tolerance < 1e-6, "invalid ticket selection inputs")
    max_p = max(float(value) for value in tickets.values())
    chosen = min(key for key, probability in tickets.items() if float(probability) >= max_p - tolerance)
    return chosen, float(tickets[chosen])


def pool_race_metrics(
    pool: str,
    tickets: Mapping[tuple[int, ...], float],
    truths: set[tuple[int, ...]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    require(pool in POOL_ORDER and bool(tickets) and truths and truths.issubset(tickets), f"invalid {pool} event map/truth")
    keys = sorted(tickets)
    probs = np.asarray([float(tickets[key]) for key in keys], dtype=np.float64)
    require(np.isfinite(probs).all() and (probs >= 0).all(), f"invalid {pool} probability")
    y = np.fromiter((1.0 if key in truths else 0.0 for key in keys), dtype=np.float64, count=len(keys))
    if pool in CATEGORICAL_POOLS:
        require(len(truths) == 1 and abs(float(probs.sum()) - 1.0) <= 5e-10, f"{pool} categorical mass mismatch")
        true_key = next(iter(truths))
        true_p = float(tickets[true_key])
        nll = -math.log(max(true_p, EPS))
        brier = float(np.square(probs - y).sum())
    else:
        clipped = np.clip(probs, EPS, 1.0 - EPS)
        losses = -(y * np.log(clipped) + (1.0 - y) * np.log1p(-clipped))
        nll = float(losses.mean())
        brier = float(np.square(probs - y).mean())
        true_p = float(np.mean([tickets[key] for key in sorted(truths)]))
    selected, selected_probability = _selected_ticket(tickets)
    metric = {
        "pool": pool,
        "race_nll": float(nll),
        "race_brier": float(brier),
        "ticket_count": int(len(tickets)),
        "event_count": int(len(truths)),
        "realized_event_probability_mean": float(true_p),
    }
    selection = {
        "pool": pool,
        "selected_ticket_key": json.dumps(list(selected), separators=(",", ":")),
        "selected_probability": float(selected_probability),
        "selected_hit": bool(selected in truths),
        "realized_event_count": int(len(truths)),
        "realized_event_keys_json": json.dumps([list(key) for key in sorted(truths)], separators=(",", ":")),
        "realized_event_probabilities_json": json.dumps([float(tickets[key]) for key in sorted(truths)], separators=(",", ":")),
    }
    return metric, selection


def _bin_accumulate(
    bins: dict[tuple[str, str, str, int], list[float]],
    pool: str,
    arm: str,
    evaluation_period: str,
    tickets: Mapping[tuple[int, ...], float],
    truths: set[tuple[int, ...]],
) -> None:
    """Accumulate reliability by pooled ticket-event count, not race-equal."""
    require(pool in POOL_ORDER and arm in ("A", "B", "R") and
            evaluation_period in ("ALL", "2024", "2025", "2026"), "invalid reliability group")
    require(bool(tickets) and truths.issubset(tickets), "reliability truth/ticket mismatch")
    for key, raw_probability in tickets.items():
        probability = float(raw_probability)
        require(math.isfinite(probability) and 0.0 <= probability <= 1.0,
                "invalid ticket probability for reliability")
        index = int(np.searchsorted(BIN_EDGES, probability, side="right") - 1)
        index = min(max(index, 0), len(BIN_EDGES) - 2)
        observed = 1.0 if key in truths else 0.0
        item = bins[(pool, arm, evaluation_period, index)]
        item[0] += 1.0
        item[1] += probability
        item[2] += observed
        item[3] += (probability - observed) ** 2


def _build_reliability_frame(
    bins: Mapping[tuple[str, str, str, int], Sequence[float]], arms: Sequence[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for pool in POOL_ORDER:
        for arm in arms:
            for period in ("ALL", "2024", "2025", "2026"):
                for index, (lower, upper) in enumerate(zip(BIN_EDGES[:-1], BIN_EDGES[1:])):
                    count, sum_probability, sum_observed, sum_brier = bins.get(
                        (pool, arm, period, index), (0, 0, 0, 0))
                    rows.append({
                        "pool": pool, "arm": arm, "evaluation_period": period, "bin_index": index,
                        "bin_lower": float(lower), "bin_upper": float(upper),
                        "upper_inclusive": bool(index == len(BIN_EDGES) - 2),
                        "ticket_events": int(count),
                        "mean_probability": (float(sum_probability / count) if count else np.nan),
                        "observed_event_rate": (float(sum_observed / count) if count else np.nan),
                        "mean_ticket_brier": (float(sum_brier / count) if count else np.nan),
                        "weighting": "pooled_ticket_event_count",
                    })
    return pd.DataFrame(rows)


def lightgbm_parameters(objective: Any) -> dict[str, Any]:
    params = dict(LGBM_COMMON)
    params["objective"] = objective
    params["metric"] = "None"
    return params


def train_a_model(training_rows: pd.DataFrame) -> lgb.Booster:
    ordered = training_rows.sort_values(["race_id", "horse_number"], kind="mergesort")
    order, group_sizes = ordered_race_groups(ordered)
    require(np.array_equal(order, np.arange(len(ordered))), "A rows were not preordered by race/horse number")
    dataset = lgb.Dataset(
        ordered.loc[:, A_FEATURES],
        label=ordered["finish_position"].to_numpy(dtype=np.float64),
        group=group_sizes,
        feature_name=list(A_FEATURES),
        free_raw_data=True,
    )
    objective = make_lightgbm_ordered_top3_objective(
        ordered["finish_position"].to_numpy(dtype=np.float64), group_sizes
    )
    model = lgb.train(
        lightgbm_parameters(objective),
        dataset,
        num_boost_round=180,
        keep_training_booster=False,
    )
    return model


def _race_equal_binary_weights(rows: pd.DataFrame) -> np.ndarray:
    counts = rows.groupby("race_id", sort=False)["race_id"].transform("size").to_numpy(dtype=np.float64)
    require((counts > 0).all(), "empty runner race in binary weights")
    return 1.0 / counts


def train_runner_binary_model(training_rows: pd.DataFrame, label_column: str) -> lgb.Booster:
    require(label_column in RUNNER_LABELS, f"unapproved runner phase target: {label_column}")
    labeled = training_rows.loc[training_rows[label_column].notna()].sort_values(
        ["race_id", "horse_number"], kind="mergesort"
    )
    _require_binary_support(labeled[label_column].to_numpy(dtype=np.float64), min_each=50, where=f"train {label_column}")
    dataset = lgb.Dataset(
        labeled.loc[:, RUNNER_PHASE_FEATURES],
        label=labeled[label_column].to_numpy(dtype=np.float64),
        weight=_race_equal_binary_weights(labeled),
        feature_name=list(RUNNER_PHASE_FEATURES),
        free_raw_data=True,
    )
    model = lgb.train(lightgbm_parameters("binary"), dataset, num_boost_round=180, keep_training_booster=False)
    return model


def train_race_binary_model(training_races: pd.DataFrame) -> lgb.Booster:
    labeled = training_races.loc[training_races[RACE_LABEL].notna()].sort_values(
        ["race_date", "race_id"], kind="mergesort"
    )
    _require_binary_support(labeled[RACE_LABEL].to_numpy(dtype=np.float64), min_each=50, where="train scenario Z")
    dataset = lgb.Dataset(
        labeled.loc[:, RACE_Z_FEATURES],
        label=labeled[RACE_LABEL].to_numpy(dtype=np.float64),
        weight=np.ones(len(labeled), dtype=np.float64),
        feature_name=list(RACE_Z_FEATURES),
        free_raw_data=True,
    )
    model = lgb.train(lightgbm_parameters("binary"), dataset, num_boost_round=180, keep_training_booster=False)
    return model


def _require_binary_support(labels: Sequence[float], *, min_each: int, where: str) -> dict[str, int]:
    values = np.asarray(labels, dtype=np.float64)
    require(np.isfinite(values).all() and np.isin(values, (0.0, 1.0)).all(), f"invalid binary labels: {where}")
    positives = int(np.sum(values == 1.0))
    negatives = int(np.sum(values == 0.0))
    require(positives >= min_each and negatives >= min_each,
            f"insufficient binary support for {where}: positives={positives}, negatives={negatives}")
    return {"positive": positives, "negative": negatives, "rows": len(values)}


def audit_phase_support(model_rows: pd.DataFrame, race_rows: pd.DataFrame) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    failures: list[str] = []
    for target_year in range(FIRST_OOS_YEAR, LAST_OOS_YEAR + 1):
        train_mask = model_rows["year"] <= target_year - 2
        cal_mask = model_rows["year"] == target_year - 1
        race_train_mask = race_rows["year"] <= target_year - 2
        race_cal_mask = race_rows["year"] == target_year - 1
        fold: dict[str, Any] = {"target_year": target_year, "heads": {}}
        for label in RUNNER_LABELS:
            head: dict[str, Any] = {}
            for role, mask, threshold in (("train", train_mask, 50), ("calibration", cal_mask, 10)):
                vals = model_rows.loc[mask, label].dropna().to_numpy(dtype=np.float64)
                support = {"positive": int(np.sum(vals == 1)), "negative": int(np.sum(vals == 0)), "rows": len(vals)}
                head[role] = support
                if support["positive"] < threshold or support["negative"] < threshold:
                    failures.append(f"{target_year}:{label}:{role}")
            fold["heads"][label] = head
        head_z: dict[str, Any] = {}
        for role, mask, threshold in (("train", race_train_mask, 50), ("calibration", race_cal_mask, 10)):
            vals = race_rows.loc[mask, RACE_LABEL].dropna().to_numpy(dtype=np.float64)
            support = {"positive": int(np.sum(vals == 1)), "negative": int(np.sum(vals == 0)), "rows": len(vals)}
            head_z[role] = support
            if support["positive"] < threshold or support["negative"] < threshold:
                failures.append(f"{target_year}:scenario_Z:{role}")
        fold["heads"][RACE_LABEL] = head_z
        records.append(fold)
    return {"all_folds_supported": not failures, "folds": records, "failures": failures}


def _feature_matrix(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    require(tuple(columns) in (A_FEATURES, RUNNER_PHASE_FEATURES, RACE_Z_FEATURES), "feature matrix not in frozen allowlist")
    result = frame.loc[:, list(columns)].astype(np.float64, copy=False)
    finite = np.isfinite(result.to_numpy(dtype=np.float64, na_value=np.nan)) | result.isna().to_numpy()
    require(finite.all(), "feature matrix contains a non-finite non-null value")
    return result


def _prediction_records(frame: pd.DataFrame, scores: Sequence[float]) -> list[dict[str, Any]]:
    score_values = np.asarray(scores, dtype=np.float64)
    require(len(frame) == len(score_values) and np.isfinite(score_values).all(), "prediction rows/scores mismatch")
    copy = frame.loc[:, ["race_id", "race_date", "year", "field_n", "horse_number", "finish_position"]].copy()
    _string_key_series(copy["race_id"], "prediction race_id")
    copy["__score"] = score_values
    records: list[dict[str, Any]] = []
    for race_id, group in copy.groupby("race_id", sort=True):
        group = group.sort_values("horse_number", kind="mergesort")
        records.append({
            "race_id": race_id,
            "race_date": str(group["race_date"].iloc[0]),
            "year": int(group["year"].iloc[0]),
            "n": int(group["field_n"].iloc[0]),
            "numbers": group["horse_number"].to_numpy(dtype=np.int64),
            "ranks": group["finish_position"].to_numpy(dtype=np.int64),
            "scores": group["__score"].to_numpy(dtype=np.float64),
        })
    return records


def _calibration_records(frame: pd.DataFrame, scores: Sequence[float]) -> list[dict[str, Any]]:
    return _prediction_records(frame, scores)


def _raw_binary_logits(model: lgb.Booster, frame: pd.DataFrame, columns: Sequence[str]) -> np.ndarray:
    logits = np.asarray(model.predict(_feature_matrix(frame, columns), raw_score=True), dtype=np.float64)
    require(len(logits) == len(frame) and np.isfinite(logits).all(), "invalid raw LightGBM binary logits")
    return logits


def _save_booster(model: lgb.Booster, relative_name: str) -> str:
    path = confined_model_path(relative_name)
    payload = model.model_to_string(num_iteration=model.current_iteration()).encode("utf-8")
    write_bytes_once(path, payload)
    return sha256_file(path)


def _weighted_race_label_count(labels: pd.Series, race_ids: pd.Series) -> tuple[int, int, int]:
    known = labels.notna().to_numpy()
    values = labels.to_numpy(dtype=np.float64, na_value=np.nan)[known]
    races = race_ids.to_numpy()[known]
    require(all(type(race_id) is str and race_id for race_id in races), "phase race keys must be strings")
    return int(np.sum(values == 1)), int(np.sum(values == 0)), len(set(races.tolist()))


def _project_input(relative_path: str) -> Path:
    candidate = (PROJECT / relative_path).resolve(strict=True)
    require(candidate.is_relative_to(PROJECT.resolve()), f"source path escapes project: {relative_path}")
    return candidate


def _source_file_record(path: Path, expected_sha: str, *, name: str) -> dict[str, Any]:
    require(path.is_file(), f"missing source asset: {name}")
    observed = sha256_file(path)
    require(observed == expected_sha, f"source asset SHA mismatch: {name}")
    return {"path": path.relative_to(PROJECT).as_posix(), "sha256": observed, "bytes": path.stat().st_size}


def load_input_bundle() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    manifest = json_read(INPUT_MANIFEST)
    validate_input_manifest(manifest)
    model = pd.read_parquet(MODEL_INPUTS)
    race = pd.read_parquet(RACE_INPUTS)
    validate_input_frames(model, race, manifest)
    reference_keys = validate_frozen_reference_keys(model, manifest)
    lineage = validate_history_lineage(model, manifest)
    require(model["api_record_id"].dtype == np.dtype("int64"), "model input key dtype changed")
    require(race["race_date"].map(lambda value: isinstance(value, str)).all(), "race input date keys must be strings")
    frozen = {
        "input_manifest_sha256": sha256_file(INPUT_MANIFEST),
        "model_inputs_sha256": sha256_file(MODEL_INPUTS),
        "race_inputs_sha256": sha256_file(RACE_INPUTS),
        "history_lineage_sha256": sha256_file(HISTORY_LINEAGE),
        "source_manifest_sha256": sha256_file(SOURCE_MANIFEST),
        "reference_key_audit": reference_keys,
        "history_lineage_audit": lineage,
        "rows": len(model),
        "races": int(model["race_id"].nunique()),
        "eval_races": int(model.loc[model["year"].between(2024, 2026) & model["race_date"].le(EVAL_END), "race_id"].nunique()),
        "eval_runners": int((model["year"].between(2024, 2026) & model["race_date"].le(EVAL_END)).sum()),
    }
    return model, race, manifest, frozen


def _score_table(path: Path, expected_sha: str, expected_rows: int, year: int, role: str,
                 model_rows: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    record = _source_file_record(path, expected_sha, name=f"F1_STYLE6 {year} {role}")
    score = pd.read_parquet(path)
    require(list(score.columns) == ["api_record_id", "score"], f"raw score schema mismatch: {path.name}")
    require(score["api_record_id"].dtype == np.dtype("int64") and score["score"].dtype == np.dtype("float64"),
            f"raw score dtypes mismatch: {path.name}")
    require(score["api_record_id"].is_unique and np.isfinite(score["score"].to_numpy()).all(),
            f"duplicate or non-finite raw scores: {path.name}")
    target = model_rows.loc[model_rows["year"] == year, ["api_record_id", "race_id", "race_date", "year",
                                                               "horse_number", "field_n", "finish_position"]].copy()
    require(len(score) == expected_rows == len(target), f"raw score row count mismatch: {path.name}")
    joined = target.merge(score, on="api_record_id", how="outer", validate="one_to_one", indicator=True)
    require(joined["_merge"].eq("both").all(), f"raw score IDs differ from audited year {year}: {path.name}")
    joined = joined.drop(columns="_merge")
    require(joined["race_id"].notna().all(), f"raw score key join lost race IDs: {path.name}")
    info = {**record, "year": year, "role": role, "rows": len(joined),
            "races": int(joined["race_id"].nunique()),
            "key_sha256": _canonical_key_hash(joined, ["api_record_id", "race_id", "race_date", "year", "horse_number"])}
    return joined, info


def load_f1_reference(model: pd.DataFrame) -> tuple[dict[int, pd.DataFrame], dict[int, pd.DataFrame], list[dict[str, Any]]]:
    manifest = json_read(REFERENCE_MANIFEST)
    raw_by_year = {int(row["label_year"]): row for row in manifest.get("raw_oos_score_assets", [])}
    eval_by_year = {int(row["evaluation_year"]): row for row in manifest.get("evaluation_score_assets", [])}
    require(set(raw_by_year) >= {2023, 2024, 2025}, "reference manifest lacks preceding-year raw calibration scores")
    require(set(eval_by_year) >= set(EVAL_YEARS), "reference manifest lacks evaluation raw scores")
    calibration: dict[int, pd.DataFrame] = {}
    evaluation: dict[int, pd.DataFrame] = {}
    source_rows: list[dict[str, Any]] = []
    for target_year in EVAL_YEARS:
        cal_entry = raw_by_year[target_year - 1]
        eval_entry = eval_by_year[target_year]
        require(int(cal_entry["provider_fold_year"]) == target_year,
                f"R calibration source is not from F1_STYLE6_{target_year}")
        cal_path = _project_input(str(cal_entry["path"]))
        eval_path = _project_input(str(eval_entry["path"]))
        cal_meta_path = _project_input(str(cal_entry["provider_meta_path"]))
        eval_meta_path = eval_path.parent / "meta.json"
        require(cal_meta_path.resolve() == eval_meta_path.resolve(),
                f"R calibration/evaluation providers differ for {target_year}")
        meta = json_read(cal_meta_path)
        require(meta.get("variant") == "F1_STYLE6" and int(meta.get("evaluation_year", -1)) == target_year,
                f"R provider vintage mismatch for {target_year}")
        require(str(meta.get("score_role_generated", "")) in {"", "calibration_only", "evaluation"},
                f"unexpected score-generation role for R vintage {target_year}")
        require(str(cal_entry.get("score_semantics")) == "raw_score_before_temperature",
                f"R calibration is not raw for {target_year}")
        cal_frame, cal_info = _score_table(cal_path, str(cal_entry["sha256"]), int(cal_entry["rows"]),
                                           target_year - 1, "calibration_raw", model)
        eval_frame, eval_info = _score_table(eval_path, str(eval_entry["sha256"]), int(eval_entry["rows"]),
                                             target_year, "evaluation_raw", model)
        require(meta.get("calibration_scores_sha256") == cal_info["sha256"],
                f"provider metadata does not pin raw calibration score file for {target_year}")
        require(meta.get("evaluation_scores_sha256") == eval_info["sha256"],
                f"provider metadata does not pin raw evaluation score file for {target_year}")
        refit_max = pd.Timestamp(meta["refit_max"])
        for name, frame, prefix in (("calibration", cal_frame, "calibration"), ("evaluation", eval_frame, "evaluation")):
            min_date, max_date = pd.Timestamp(frame["race_date"].min()), pd.Timestamp(frame["race_date"].max())
            require(refit_max <= min_date - pd.Timedelta(days=2),
                    f"R {name} refit_max violates T−2 in {target_year}")
            require(pd.Timestamp(meta[f"{prefix}_min"]) == min_date and
                    pd.Timestamp(meta[f"{prefix}_max"]) == max_date,
                    f"R provider {name} date range mismatch in {target_year}")
        calibration[target_year] = cal_frame
        evaluation[target_year] = eval_frame
        source_rows.extend([
            {**cal_info, "provider_meta_path": cal_meta_path.relative_to(PROJECT).as_posix(),
             "provider_meta_sha256": sha256_file(cal_meta_path), "refit_max": str(meta["refit_max"]),
             "target_date_min": str(cal_frame["race_date"].min()), "target_date_max": str(cal_frame["race_date"].max())},
            {**eval_info, "provider_meta_path": eval_meta_path.relative_to(PROJECT).as_posix(),
             "provider_meta_sha256": sha256_file(eval_meta_path), "refit_max": str(meta["refit_max"]),
             "target_date_min": str(eval_frame["race_date"].min()), "target_date_max": str(eval_frame["race_date"].max())},
        ])
    return calibration, evaluation, source_rows


def _validate_rules_and_bootstrap(model: pd.DataFrame) -> dict[str, Any]:
    rules = json_read(RULES)
    minimums = rules["primary_rule"]["article_4_minimum_starters"]
    require({pool: int(minimums[pool]) for pool in POOL_ORDER} == POOL_MIN_STARTERS,
            "official pool minimums differ from frozen event contract")
    split = rules["primary_rule"]["plc_field_split"]
    require(split.get("5_to_7") == "Top2" and split.get("8_or_more") == "Top3",
            "official PLC field split differs from frozen contract")
    qpl_rule = next(item for item in rules["event_space"]["pools"] if item["code"] == "QPL")
    require("places 1-3" in qpl_rule["event"], "QPL event must be Top3 combinations")
    require(BOOTSTRAP.is_file() and BOOTSTRAP_RECEIPT.is_file(), "frozen date bootstrap asset missing")
    receipt = json_read(BOOTSTRAP_RECEIPT)
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS", "bootstrap schedule is not frozen")
    require(receipt.get("schedule_sha256") == EXPECTED_BOOTSTRAP_SHA == sha256_file(BOOTSTRAP),
            "frozen bootstrap schedule SHA mismatch")
    dates = sorted(model.loc[model["year"].between(2024, 2026) & model["race_date"].le(EVAL_END), "race_date"].unique())
    date_sha = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(date_sha == EXPECTED_DATE_SHA == receipt.get("date_inventory_sha256"),
            "evaluation date inventory does not match frozen bootstrap")
    schedule = np.load(BOOTSTRAP, mmap_mode="r", allow_pickle=False)
    require(schedule.shape == (2000, 269) and schedule.dtype == np.int32,
            "frozen bootstrap dimensions/dtype mismatch")
    require(int(schedule.min()) >= 0 and int(schedule.max()) < len(dates), "bootstrap date index out of range")
    eval_races = model.loc[model["year"].between(2024, 2026) & model["race_date"].le(EVAL_END),
                           ["race_id", "field_n"]].drop_duplicates()
    pool_denominators = {}
    for pool in POOL_ORDER:
        legal = eval_races["field_n"] >= POOL_MIN_STARTERS[pool]
        if pool == "PLC":
            # Actual N>=8 establishes a robust Top3 event under the frozen
            # no-post-opening-additions assumption. Actual N=5..7 stays out.
            legal &= eval_races["field_n"] >= 8
        count = int(legal.sum())
        expected = EXPECTED_EVAL["plc_races"] if pool == "PLC" else EXPECTED_EVAL["races"]
        require(count == expected,
                f"{pool} legal event denominator changed: expected {expected}, found {count}")
        pool_denominators[pool] = count
    return {"rules_sha256": sha256_file(RULES), "reference_manifest_sha256": sha256_file(REFERENCE_MANIFEST),
            "bootstrap_path": BOOTSTRAP.relative_to(PROJECT).as_posix(),
            "bootstrap_sha256": sha256_file(BOOTSTRAP), "bootstrap_receipt_sha256": sha256_file(BOOTSTRAP_RECEIPT),
            "bootstrap_shape": list(schedule.shape), "date_inventory_sha256": date_sha,
            "pool_legal_event_denominators": pool_denominators}


def source_preflight() -> dict[str, Any]:
    synthetic = run_synthetic_checks()
    model, race, manifest, frozen = load_input_bundle()
    support = audit_phase_support(model, race)
    calibration, evaluation, reference_sources = load_f1_reference(model)
    rules_bootstrap = _validate_rules_and_bootstrap(model)
    require(len(calibration) == 3 and len(evaluation) == 3, "R fold count mismatch")
    source_hashes = {
        "source_manifest": {"path": SOURCE_MANIFEST.relative_to(PROJECT).as_posix(), "sha256": sha256_file(SOURCE_MANIFEST)},
        "input_manifest": {"path": INPUT_MANIFEST.relative_to(PROJECT).as_posix(), "sha256": frozen["input_manifest_sha256"]},
        "model_inputs": {"path": MODEL_INPUTS.relative_to(PROJECT).as_posix(), "sha256": frozen["model_inputs_sha256"]},
        "race_inputs": {"path": RACE_INPUTS.relative_to(PROJECT).as_posix(), "sha256": frozen["race_inputs_sha256"]},
        "history_lineage": {"path": HISTORY_LINEAGE.relative_to(PROJECT).as_posix(), "sha256": frozen["history_lineage_sha256"]},
        "rules_contract": {"path": RULES.relative_to(PROJECT).as_posix(), "sha256": rules_bootstrap["rules_sha256"]},
        "design_contract": {"path": CONTRACT.relative_to(PROJECT).as_posix(), "sha256": sha256_file(CONTRACT)},
        "reference_manifest": {"path": REFERENCE_MANIFEST.relative_to(PROJECT).as_posix(), "sha256": rules_bootstrap["reference_manifest_sha256"]},
        "bootstrap": {"path": rules_bootstrap["bootstrap_path"], "sha256": rules_bootstrap["bootstrap_sha256"]},
        "bootstrap_receipt": {"path": BOOTSTRAP_RECEIPT.relative_to(PROJECT).as_posix(), "sha256": rules_bootstrap["bootstrap_receipt_sha256"]},
    }
    report = {
        "status": "PASS_STRUCTURAL_PREFLIGHT_NO_FIT_OR_METRICS",
        "scope": "hash/schema/key/cutoff/source/label-support checks only; no model fit, probability calculation, or outcome metric",
        "study": "20261022_dynamic_ability_pace_v1",
        "plan_sha256": sha256_file(EXPERIMENT / "PLAN.md"),
        "code_bundle_sha256": code_bundle_sha256(),
        "input_manifest_sha256": frozen["input_manifest_sha256"],
        "source_manifest_sha256": frozen["source_manifest_sha256"],
        "rows": frozen["rows"], "races": frozen["races"],
        "evaluation": {"races": frozen["eval_races"], "runners": frozen["eval_runners"], "dates": EXPECTED_EVAL["dates"]},
        "plc_eligible_races": EXPECTED_EVAL["plc_races"], "plc_unknown_races": EXPECTED_EVAL["plc_unknown"],
        "input_key_audit": frozen["reference_key_audit"],
        "history_lineage_audit": frozen["history_lineage_audit"],
        "phase_support": support,
        "phase_B_available_by_support": bool(support["all_folds_supported"]),
        "R_raw_score_sources": reference_sources,
        "rules_bootstrap": rules_bootstrap,
        "source_hashes": source_hashes,
        "synthetic_checks": synthetic,
        "database_opened": False,
        "models_loaded": False,
        "fitted": False,
        "probabilities_computed": False,
        "outcome_metrics_computed": False,
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    write_json_once(confined_output_path("source_preflight.json"), report)
    print(json.dumps({"status": report["status"], "code_bundle_sha256": report["code_bundle_sha256"],
                      "input_manifest_sha256": report["input_manifest_sha256"],
                      "evaluation": report["evaluation"],
                      "phase_B_available_by_support": report["phase_B_available_by_support"]},
                     ensure_ascii=False, indent=2))
    return report


def _record_model_output(
    frame: pd.DataFrame,
    *,
    target_year: int,
    train_max_year: int,
    calibration_year: int,
    score: np.ndarray,
    temperature: float,
    raw_early: np.ndarray | None = None,
    p_early: np.ndarray | None = None,
    raw_recovery: np.ndarray | None = None,
    p_recovery: np.ndarray | None = None,
) -> pd.DataFrame:
    require(len(frame) == len(score), "annual score output row mismatch")
    output_columns = ["api_record_id", "race_id", "race_date", "year", "field_n", "horse_number", "finish_position",
                      *RUNNER_LABELS]
    output = frame.loc[:, output_columns].copy()
    output["score_a"] = np.asarray(score, dtype=np.float64)
    output["temperature_a"] = float(temperature)
    output["a_utility"] = output["score_a"] / float(temperature)
    output["model_train_max_year"] = int(train_max_year)
    output["calibration_year"] = int(calibration_year)
    output["prediction_year"] = int(target_year)
    output["in_sample"] = False
    if raw_early is not None:
        output["logit_early"] = np.asarray(raw_early, dtype=np.float64)
        output["p_early"] = np.asarray(p_early, dtype=np.float64)
    if raw_recovery is not None:
        output["logit_recovery"] = np.asarray(raw_recovery, dtype=np.float64)
        output["p_recovery"] = np.asarray(p_recovery, dtype=np.float64)
    require(np.isfinite(output["score_a"].to_numpy()).all() and np.isfinite(output["a_utility"].to_numpy()).all(),
            "non-finite A annual OOS output")
    if "p_early" in output:
        require(np.isfinite(output["p_early"].to_numpy()).all() and
                ((output["p_early"] >= 0) & (output["p_early"] <= 1)).all(), "invalid early annual OOS probability")
    if "p_recovery" in output:
        require(np.isfinite(output["p_recovery"].to_numpy()).all() and
                ((output["p_recovery"] >= 0) & (output["p_recovery"] <= 1)).all(), "invalid recovery annual OOS probability")
    validate_temporal_record({"target_year": target_year, "train_max_year": train_max_year,
                              "calibration_year": calibration_year, "prediction_year": target_year,
                              "in_sample": False}, target_year)
    return output


def _record_race_output(
    frame: pd.DataFrame,
    *,
    target_year: int,
    train_max_year: int,
    calibration_year: int,
    raw_z: np.ndarray,
    q_z: np.ndarray,
    temperature: float,
) -> pd.DataFrame:
    require(len(frame) == len(raw_z) == len(q_z), "annual race-output row mismatch")
    output = frame.loc[:, [*RACE_KEYS, RACE_LABEL]].copy()
    output["logit_z"] = np.asarray(raw_z, dtype=np.float64)
    output["q_z"] = np.asarray(q_z, dtype=np.float64)
    output["temperature_z"] = float(temperature)
    output["model_train_max_year"] = int(train_max_year)
    output["calibration_year"] = int(calibration_year)
    output["prediction_year"] = int(target_year)
    output["in_sample"] = False
    require(np.isfinite(output["q_z"].to_numpy()).all() and
            ((output["q_z"] >= 0) & (output["q_z"] <= 1)).all(), "invalid scenario annual OOS probability")
    validate_temporal_record({"target_year": target_year, "train_max_year": train_max_year,
                              "calibration_year": calibration_year, "prediction_year": target_year,
                              "in_sample": False}, target_year)
    return output


def fit_annual_oos(model_rows: pd.DataFrame, race_rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Fit one annual prior-only vintage for A and all three phase heads."""
    runner_outputs: list[pd.DataFrame] = []
    race_outputs: list[pd.DataFrame] = []
    fold_parameters: dict[str, Any] = {}
    for target_year in range(FIRST_OOS_YEAR, LAST_OOS_YEAR + 1):
        print(json.dumps({"phase": "annual_oos_fold_started", "target_year": target_year,
                          "estimated_models": 4}, ensure_ascii=False), flush=True)
        train_max = target_year - 2
        calibration_year = target_year - 1
        train_rows = model_rows.loc[model_rows["year"] <= train_max]
        cal_rows = model_rows.loc[model_rows["year"] == calibration_year]
        target_rows = model_rows.loc[model_rows["year"] == target_year]
        train_races = race_rows.loc[race_rows["year"] <= train_max]
        cal_races = race_rows.loc[race_rows["year"] == calibration_year]
        target_races = race_rows.loc[race_rows["year"] == target_year]
        require(len(train_rows) > 0 and len(cal_rows) > 0 and len(target_rows) > 0,
                f"empty annual A fold {target_year}")
        require(len(train_races) > 0 and len(cal_races) > 0 and len(target_races) > 0,
                f"empty annual scenario fold {target_year}")

        a_model = train_a_model(train_rows)
        print(json.dumps({"phase": "annual_a_model_fit_complete", "target_year": target_year},
                         ensure_ascii=False), flush=True)
        a_cal_raw = np.asarray(a_model.predict(_feature_matrix(cal_rows, A_FEATURES), raw_score=True), dtype=np.float64)
        a_cal_records = _calibration_records(cal_rows, a_cal_raw)
        a_temperature = fit_joint_temperature(a_cal_records)
        a_target_raw = np.asarray(a_model.predict(_feature_matrix(target_rows, A_FEATURES), raw_score=True), dtype=np.float64)
        require(np.isfinite(a_target_raw).all(), f"non-finite A output in {target_year}")
        a_sha = _save_booster(a_model, f"A_{target_year}.txt")

        phase_fit: dict[str, Any] = {}
        phase_raw_target: dict[str, np.ndarray] = {}
        phase_p_target: dict[str, np.ndarray] = {}
        for label, stem in (("label_early", "early"), ("label_recovery", "recovery")):
            head = train_runner_binary_model(train_rows, label)
            cal_logits = _raw_binary_logits(head, cal_rows, RUNNER_PHASE_FEATURES)
            temp = fit_binary_temperature(cal_logits, cal_rows[label].to_numpy(dtype=np.float64),
                                          cal_rows["race_id"].tolist())
            target_logits = _raw_binary_logits(head, target_rows, RUNNER_PHASE_FEATURES)
            target_probability = np.clip(expit(target_logits / float(temp["temperature"])),
                                         PHASE_EPS, 1.0 - PHASE_EPS)
            model_sha = _save_booster(head, f"PHASE_{stem}_{target_year}.txt")
            phase_fit[stem] = {**temp, "model_sha256": model_sha,
                               "train_support": _require_binary_support(
                                   train_rows.loc[train_rows[label].notna(), label].to_numpy(dtype=np.float64),
                                   min_each=50, where=f"train {stem} {target_year}"),
                               "calibration_races": len(set(cal_rows.loc[cal_rows[label].notna(), "race_id"].tolist()))}
            phase_raw_target[stem] = target_logits
            phase_p_target[stem] = target_probability
            print(json.dumps({"phase": "annual_runner_phase_head_fit_complete", "target_year": target_year,
                              "head": stem}, ensure_ascii=False), flush=True)

        z_head = train_race_binary_model(train_races)
        z_cal_logits = _raw_binary_logits(z_head, cal_races, RACE_Z_FEATURES)
        z_temp = fit_binary_temperature(z_cal_logits, cal_races[RACE_LABEL].to_numpy(dtype=np.float64),
                                        cal_races["race_id"].tolist())
        z_target_logits = _raw_binary_logits(z_head, target_races, RACE_Z_FEATURES)
        z_target_probability = np.clip(expit(z_target_logits / float(z_temp["temperature"])),
                                       PHASE_EPS, 1.0 - PHASE_EPS)
        z_sha = _save_booster(z_head, f"PHASE_z_{target_year}.txt")
        print(json.dumps({"phase": "annual_race_z_head_fit_complete", "target_year": target_year},
                         ensure_ascii=False), flush=True)

        target_out = _record_model_output(
            target_rows, target_year=target_year, train_max_year=train_max,
            calibration_year=calibration_year, score=a_target_raw,
            temperature=float(a_temperature["temperature"]),
            raw_early=phase_raw_target["early"], p_early=phase_p_target["early"],
            raw_recovery=phase_raw_target["recovery"], p_recovery=phase_p_target["recovery"],
        )
        race_out = _record_race_output(
            target_races, target_year=target_year, train_max_year=train_max,
            calibration_year=calibration_year, raw_z=z_target_logits,
            q_z=z_target_probability, temperature=float(z_temp["temperature"]),
        )
        require(target_out["race_id"].nunique() == int(target_races["race_id"].nunique()),
                f"runner/race annual target mismatch in {target_year}")
        runner_outputs.append(target_out)
        race_outputs.append(race_out)
        fold_parameters[str(target_year)] = {
            "target_year": target_year,
            "train_max_year": train_max,
            "calibration_year": calibration_year,
            "training_races": int(train_rows["race_id"].nunique()),
            "training_runners": len(train_rows),
            "calibration_races": int(cal_rows["race_id"].nunique()),
            "calibration_runners": len(cal_rows),
            "target_races": int(target_races["race_id"].nunique()),
            "target_runners": len(target_rows),
            "A": {**a_temperature, "model_sha256": a_sha},
            "phase": {**phase_fit,
                      "z": {**z_temp, "model_sha256": z_sha,
                            "train_support": _require_binary_support(
                                train_races.loc[train_races[RACE_LABEL].notna(), RACE_LABEL].to_numpy(dtype=np.float64),
                                min_each=50, where=f"train Z {target_year}")}},
            "provenance": {"model_fit_years_max": train_max,
                           "calibration_year": calibration_year,
                           "target_year": target_year,
                           "in_sample_predictions": False},
        }
        print(json.dumps({"phase": "annual_oos_fold_complete", "target_year": target_year,
                          "target_races": int(target_races["race_id"].nunique()),
                          "target_runners": len(target_rows), "models_fit_this_fold": 4},
                         ensure_ascii=False), flush=True)
    runner = pd.concat(runner_outputs, ignore_index=True).sort_values(
        ["year", "race_id", "horse_number"], kind="mergesort"
    ).reset_index(drop=True)
    races = pd.concat(race_outputs, ignore_index=True).sort_values(
        ["year", "race_date", "race_id"], kind="mergesort"
    ).reset_index(drop=True)
    expected_runner = model_rows.loc[model_rows["year"] >= FIRST_OOS_YEAR,
                                     ["api_record_id", "race_id", "year"]].copy()
    expected_race = race_rows.loc[race_rows["year"] >= FIRST_OOS_YEAR,
                                  ["race_id", "year"]].copy()
    require(len(runner) == len(expected_runner) and len(races) == len(expected_race),
            "annual OOS output row coverage mismatch")
    require(not runner["api_record_id"].duplicated().any() and not races["race_id"].duplicated().any(),
            "duplicate annual OOS prediction key")
    expected_runner_keys = expected_runner.sort_values(["api_record_id"], kind="mergesort").reset_index(drop=True)
    actual_runner_keys = runner.loc[:, ["api_record_id", "race_id", "year"]].sort_values(
        ["api_record_id"], kind="mergesort").reset_index(drop=True)
    require(expected_runner_keys.equals(actual_runner_keys), "annual OOS runner key coverage is not exact")
    expected_race_keys = expected_race.sort_values(["race_id"], kind="mergesort").reset_index(drop=True)
    actual_race_keys = races.loc[:, ["race_id", "year"]].sort_values(["race_id"], kind="mergesort").reset_index(drop=True)
    require(expected_race_keys.equals(actual_race_keys), "annual OOS race key coverage is not exact")
    return runner, races, fold_parameters


def _oos_race_records(
    runner_oos: pd.DataFrame,
    race_oos: pd.DataFrame,
    *,
    year_min: int | None = None,
    year_max: int | None = None,
    require_observed_z: bool,
) -> tuple[list[dict[str, Any]], int]:
    selected = runner_oos
    race_selected = race_oos
    if year_min is not None:
        selected = selected.loc[selected["year"] >= year_min]
        race_selected = race_selected.loc[race_selected["year"] >= year_min]
    if year_max is not None:
        selected = selected.loc[selected["year"] <= year_max]
        race_selected = race_selected.loc[race_selected["year"] <= year_max]
    temporal_fields = ["year", "model_train_max_year", "calibration_year", "prediction_year", "in_sample"]
    for row in selected[temporal_fields].drop_duplicates().to_dict("records"):
        validate_temporal_record({
            "target_year": row["year"], "train_max_year": row["model_train_max_year"],
            "calibration_year": row["calibration_year"], "prediction_year": row["prediction_year"],
            "in_sample": row["in_sample"],
        }, int(row["year"]))
    for row in race_selected[temporal_fields].drop_duplicates().to_dict("records"):
        validate_temporal_record({
            "target_year": row["year"], "train_max_year": row["model_train_max_year"],
            "calibration_year": row["calibration_year"], "prediction_year": row["prediction_year"],
            "in_sample": row["in_sample"],
        }, int(row["year"]))
    race_index = race_selected.set_index("race_id")
    require(race_index.index.is_unique, "annual race OOS keys are not unique")
    records: list[dict[str, Any]] = []
    missing_z = 0
    for race_id, group in selected.groupby("race_id", sort=True):
        require(race_id in race_index.index, f"missing annual race prediction {race_id}")
        race_row = race_index.loc[race_id]
        group = group.sort_values("horse_number", kind="mergesort")
        require(group["year"].nunique() == 1 and int(group["year"].iloc[0]) == int(race_row["year"]),
                f"annual OOS year mismatch for race {race_id}")
        if require_observed_z and pd.isna(race_row[RACE_LABEL]):
            missing_z += 1
            continue
        record: dict[str, Any] = {
            "race_id": race_id,
            "race_date": str(group["race_date"].iloc[0]),
            "year": int(group["year"].iloc[0]),
            "numbers": group["horse_number"].to_numpy(dtype=np.int64),
            "ranks": group["finish_position"].to_numpy(dtype=np.int64),
            "a": group["a_utility"].to_numpy(dtype=np.float64),
            "p_early": group["p_early"].to_numpy(dtype=np.float64),
            "p_recovery": group["p_recovery"].to_numpy(dtype=np.float64),
            "q_z": float(race_row["q_z"]),
        }
        if not pd.isna(race_row[RACE_LABEL]):
            record["z"] = _exact_binary(race_row[RACE_LABEL], "OOS observed Z")
        records.append(record)
    return records, missing_z


def fit_reference_and_b(
    runner_oos: pd.DataFrame,
    race_oos: pd.DataFrame,
    model_rows: pd.DataFrame,
    reference_calibration: Mapping[int, pd.DataFrame],
    reference_evaluation: Mapping[int, pd.DataFrame],
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]], dict[int, pd.DataFrame]]:
    reference_fit: dict[int, dict[str, Any]] = {}
    evaluation_r: dict[int, pd.DataFrame] = {}
    for target_year in EVAL_YEARS:
        cal_frame = reference_calibration[target_year]
        eval_frame = reference_evaluation[target_year]
        calibration_records = _calibration_records(cal_frame, cal_frame["score"].to_numpy(dtype=np.float64))
        temperature = fit_joint_temperature(calibration_records)
        eval_frame = eval_frame.copy()
        eval_frame["utility_r"] = eval_frame["score"].to_numpy(dtype=np.float64) / float(temperature["temperature"])
        evaluation_r[target_year] = eval_frame
        reference_fit[target_year] = {
            **temperature,
            "provider": f"F1_STYLE6_{target_year}",
            "calibration_year": target_year - 1,
            "evaluation_year": target_year,
            "score_semantics": "raw_score_before_temperature",
            "calibration_races": int(cal_frame["race_id"].nunique()),
            "calibration_runners": len(cal_frame),
            "evaluation_races": int(eval_frame["race_id"].nunique()),
            "evaluation_runners": len(eval_frame),
            "calibration_score_sha256": sha256_file(_project_input(
                next(row["path"] for row in json_read(REFERENCE_MANIFEST)["raw_oos_score_assets"]
                     if int(row["label_year"]) == target_year - 1))),
            "evaluation_score_sha256": sha256_file(_project_input(
                next(row["path"] for row in json_read(REFERENCE_MANIFEST)["evaluation_score_assets"]
                     if int(row["evaluation_year"]) == target_year))),
        }

    b_fits: dict[int, dict[str, Any]] = {}
    for target_year in EVAL_YEARS:
        gamma_records, missing_z = _oos_race_records(
            runner_oos, race_oos, year_min=FIRST_OOS_YEAR, year_max=target_year - 2,
            require_observed_z=True,
        )
        require(gamma_records, f"B gamma training has no observed Z races for {target_year}")
        gamma_fit = fit_gamma(gamma_records)
        calibration_records, _ = _oos_race_records(
            runner_oos, race_oos, year_min=target_year - 1, year_max=target_year - 1,
            require_observed_z=False,
        )
        b_temperature = fit_mixture_temperature(calibration_records, gamma_fit["gamma"])
        b_fits[target_year] = {
            "evaluation_year": target_year,
            "gamma_training_vintages": [FIRST_OOS_YEAR, target_year - 2],
            "gamma_training_rows": len(gamma_records),
            "gamma_training_races": len(gamma_records),
            "gamma_training_races_missing_Z_excluded": missing_z,
            "gamma": gamma_fit,
            "temperature_calibration_year": target_year - 1,
            "temperature_calibration_races": len(calibration_records),
            "temperature_calibration": b_temperature,
            "provenance": {
                "gamma_inputs_are_annual_OOS": True,
                "gamma_fit_outcomes_through_year": target_year - 2,
                "temperature_input_oos_vintage": target_year - 1,
                "temperature_A_phase_fit_max_year": target_year - 3,
                "temperature_A_phase_calibration_year": target_year - 2,
                "evaluation_year": target_year,
                "no_target_Z_used_for_prediction": True,
            },
        }
    return reference_fit, b_fits, evaluation_r


def _arm_scenarios(
    arm: str,
    runner: pd.DataFrame,
    race: pd.Series,
    *,
    reference_scores: np.ndarray,
    reference_temperature: float,
    b_fit: Mapping[str, Any],
) -> tuple[list[np.ndarray], list[float]]:
    if arm == "A":
        return [runner["a_utility"].to_numpy(dtype=np.float64)], [1.0]
    if arm == "R":
        return [reference_scores / float(reference_temperature)], [1.0]
    require(arm == "B", f"unknown evaluation arm {arm}")
    gamma = np.asarray(b_fit["gamma"]["gamma"], dtype=np.float64)
    a = runner["a_utility"].to_numpy(dtype=np.float64)
    p_early = runner["p_early"].to_numpy(dtype=np.float64)
    p_recovery = runner["p_recovery"].to_numpy(dtype=np.float64)
    z0 = scenario_design(p_early, p_recovery, 0)
    z1 = scenario_design(p_early, p_recovery, 1)
    temperature = float(b_fit["temperature_calibration"]["temperature"])
    q = float(race["q_z"])
    require(math.isfinite(q) and 0 <= q <= 1, "invalid race-level scenario forecast")
    return [(a + z0 @ gamma) / temperature, (a + z1 @ gamma) / temperature], [1.0 - q, q]


def _race_contract_rows(eval_races: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    contract_rows: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    for race in eval_races.sort_values(["race_date", "race_id"], kind="mergesort").itertuples(index=False):
        n = int(race.field_n)
        top, basis = plc_top_for_actual_field(n)
        if 5 <= n <= 7 and top is None:
            quarantine.append({
                "race_id": race.race_id, "race_date": race.race_date, "year": int(race.year),
                "pool": "PLC", "reason": "opening_field_unknown_actual_5_to_7",
                "opening_count": None, "opening_count_observed": False,
                "opening_count_lower_bound": None,
                "rule_basis": "unknown; actual 5-7 does not determine opening 5-7 vs 8+",
            })
        for pool in POOL_ORDER:
            minimum = POOL_MIN_STARTERS[pool]
            if n < minimum:
                status = "below_statutory_minimum"
            elif pool == "PLC" and top is None:
                status = "opening_field_unknown_quarantined"
            else:
                status = "structural_event_label_available_pool_offering_unverified"
            contract_rows.append({
                "race_id": race.race_id, "race_date": race.race_date, "year": int(race.year),
                "pool": pool, "actual_field_n": n, "statutory_minimum_starters": minimum,
                "pool_minimum_met_from_actual_field": n >= minimum,
                "official_race_status": "not_audited", "pool_offered_status": "not_audited",
                "pool_offering_evidence": "not_audited", "N_at_open": None,
                "N_at_open_observed": False,
                "N_at_open_lower_bound": 8 if n >= 8 else None,
                "N_at_open_count_source": ("actual_starter_lower_bound_assuming_no_post_open_additions"
                                           if n >= 8 else "unknown_actual_field_below_8"),
                "plc_event_top_k": top,
                "plc_rule_basis": basis,
                "event_label_status": status,
                "plc_top3_robust_under_no_post_open_additions": bool(pool == "PLC" and n >= 8),
            })
    return pd.DataFrame(contract_rows), pd.DataFrame(quarantine)


def _comparison_rows(metrics: pd.DataFrame, left_arm: str, right_arm: str) -> pd.DataFrame:
    left = metrics.loc[metrics["arm"] == left_arm].copy()
    right = metrics.loc[metrics["arm"] == right_arm].copy()
    keys = ["pool", "race_id"]
    joined = left.merge(right, on=keys, how="outer", suffixes=(f"_{left_arm}", f"_{right_arm}"),
                        indicator=True, validate="one_to_one")
    require(joined["_merge"].eq("both").all(), f"{left_arm}/{right_arm} metric key coverage differs")
    for field in ("race_date", "year", "field_n"):
        require(joined[f"{field}_{left_arm}"].eq(joined[f"{field}_{right_arm}"]).all(),
                f"{left_arm}/{right_arm} {field} differs")
    joined["comparison"] = f"{left_arm}_minus_{right_arm}"
    joined["race_date"] = joined[f"race_date_{left_arm}"]
    joined["year"] = joined[f"year_{left_arm}"]
    joined["field_n"] = joined[f"field_n_{left_arm}"]
    joined["delta_nll"] = joined[f"race_nll_{left_arm}"] - joined[f"race_nll_{right_arm}"]
    joined["delta_brier"] = joined[f"race_brier_{left_arm}"] - joined[f"race_brier_{right_arm}"]
    return joined.drop(columns="_merge")


def _summary_comparisons(metrics: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    all_rows: list[pd.DataFrame] = []
    comparison_rows: list[dict[str, Any]] = []
    year_rows: list[dict[str, Any]] = []
    for left, right in (("A", "R"), ("B", "A"), ("B", "R")):
        paired = _comparison_rows(metrics, left, right)
        all_rows.append(paired)
        comparison = f"{left}_minus_{right}"
        for pool in POOL_ORDER:
            part = paired.loc[paired["pool"] == pool]
            comparison_rows.append({
                "comparison": comparison, "pool": pool, "races": int(part["race_id"].nunique()),
                "left_mean_race_nll": float(part[f"race_nll_{left}"].mean()),
                "right_mean_race_nll": float(part[f"race_nll_{right}"].mean()),
                "delta_mean_race_nll": float(part["delta_nll"].mean()),
                "left_mean_race_brier": float(part[f"race_brier_{left}"].mean()),
                "right_mean_race_brier": float(part[f"race_brier_{right}"].mean()),
                "delta_mean_race_brier": float(part["delta_brier"].mean()),
            })
            for year in EVAL_YEARS:
                year_part = part.loc[part["year"] == year]
                year_rows.append({
                    "comparison": comparison, "pool": pool, "year": year,
                    "races": int(year_part["race_id"].nunique()),
                    "left_mean_race_nll": float(year_part[f"race_nll_{left}"].mean()),
                    "right_mean_race_nll": float(year_part[f"race_nll_{right}"].mean()),
                    "delta_mean_race_nll": float(year_part["delta_nll"].mean()),
                    "left_mean_race_brier": float(year_part[f"race_brier_{left}"].mean()),
                    "right_mean_race_brier": float(year_part[f"race_brier_{right}"].mean()),
                    "delta_mean_race_brier": float(year_part["delta_brier"].mean()),
                })
    paired_all = pd.concat(all_rows, ignore_index=True)
    return pd.DataFrame(comparison_rows), pd.DataFrame(year_rows), paired_all


def _bootstrap_comparison(
    paired: pd.DataFrame,
    *, left_arm: str,
    right_arm: str,
    schedule: np.ndarray,
    dates: Sequence[str],
) -> tuple[dict[str, Any], pd.DataFrame]:
    part = paired.loc[paired["pool"].eq("TRI") &
                      paired["comparison"].eq(f"{left_arm}_minus_{right_arm}")].copy()
    require(part["race_id"].nunique() == EXPECTED_EVAL["races"] and len(part) == EXPECTED_EVAL["races"],
            f"{left_arm}/{right_arm} TRI bootstrap denominator mismatch")
    date_hash = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(date_hash == EXPECTED_DATE_SHA, "bootstrap date inventory changed during comparison")
    date_sums: dict[str, float] = defaultdict(float)
    date_counts: dict[str, int] = defaultdict(int)
    for row in part.itertuples(index=False):
        day = str(row.race_date)
        require(day in set(dates), f"TRI race has date outside bootstrap roster: {day}")
        date_sums[day] += float(row.delta_nll)
        date_counts[day] += 1
    sums = np.asarray([date_sums[day] for day in dates], dtype=np.float64)
    counts = np.asarray([date_counts[day] for day in dates], dtype=np.float64)
    draws: list[dict[str, Any]] = []
    for draw_index, draw in enumerate(schedule):
        multiplicity = np.bincount(draw, minlength=len(dates)).astype(np.float64)
        denominator = float(np.dot(multiplicity, counts))
        require(denominator > 0, "empty date bootstrap draw")
        value = float(np.dot(multiplicity, sums) / denominator)
        draws.append({"comparison": f"{left_arm}_minus_{right_arm}", "draw": draw_index,
                      "tri_nll_difference": value})
    draws_frame = pd.DataFrame(draws)
    low, high = np.quantile(draws_frame["tri_nll_difference"].to_numpy(dtype=np.float64),
                            [0.025, 0.975], method="linear")
    tri = part.loc[part["pool"].eq("TRI")]
    win = paired.loc[paired["pool"].eq("WIN") &
                      paired["comparison"].eq(f"{left_arm}_minus_{right_arm}")]
    tri_delta_brier = float(tri["delta_brier"].mean())
    win_delta_nll = float(win["delta_nll"].mean())
    win_delta_brier = float(win["delta_brier"].mean())
    primary_pass = bool(high < 0.0 and tri_delta_brier <= 0.0)
    win_pass = bool(win_delta_nll <= 0.0 and win_delta_brier <= 0.0)
    return ({
        "comparison": f"{left_arm}_minus_{right_arm}", "tri_races": EXPECTED_EVAL["races"],
        "dates": len(dates), "bootstrap_draws": int(schedule.shape[0]),
        "tri_delta_mean_race_nll": float(tri["delta_nll"].mean()),
        "tri_delta_nll_ci95": [float(low), float(high)],
        "tri_delta_mean_race_brier": tri_delta_brier,
        "tri_gate_pass": primary_pass,
        "win_races": EXPECTED_EVAL["races"], "win_delta_mean_race_nll": win_delta_nll,
        "win_delta_mean_race_brier": win_delta_brier, "win_point_protection_pass": win_pass,
        "comparison_gate_pass": bool(primary_pass and win_pass),
        "schedule_sha256": EXPECTED_BOOTSTRAP_SHA, "date_inventory_sha256": date_hash,
        "weighting": "paired dates sampled with replacement; all date races included; equal race weight",
        "fitted_parameters_fixed_across_draws": True, "fit_uncertainty_included": False,
        "statistical_noninferiority_claimed": False,
    }, draws_frame)


def _axis_summary(axis: pd.DataFrame, schedule: np.ndarray, dates: Sequence[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary_rows: list[dict[str, Any]] = []
    bootstrap_rows: list[dict[str, Any]] = []
    date_hash = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(date_hash == EXPECTED_DATE_SHA, "axis hit-rate bootstrap date inventory changed")
    by_arm = {}
    for arm in ("A", "B", "R"):
        indexed = axis.loc[axis["arm"].eq(arm)].set_index("race_id")
        require(indexed.index.is_unique, f"{arm} axis race keys are not unique")
        by_arm[arm] = indexed
    for arm, frame in by_arm.items():
        require(len(frame) == EXPECTED_EVAL["races"], f"{arm} axis denominator mismatch")
        hits = int(frame["selected_hit_top3"].sum())
        summary_rows.append({"arm": arm, "races": len(frame), "top3_hit_count": hits,
                             "top3_hit_rate": hits / len(frame),
                             "benchmark_10pct_count_target": 1126,
                             "hits_needed_vs_f1_1023": 103,
                             "relative_improvement_vs_1023": hits / EXPECTED_EVAL["races"] / (1023 / 1779) - 1.0})
    for left, right in (("A", "R"), ("B", "A"), ("B", "R")):
        pair = by_arm[left][["race_date", "selected_hit_top3"]].join(
            by_arm[right][["selected_hit_top3"]], how="outer", lsuffix=f"_{left}", rsuffix=f"_{right}",
            validate="one_to_one")
        require(len(pair) == EXPECTED_EVAL["races"] and pair.notna().all().all(),
                f"{left}/{right} axis race keys mismatch")
        delta = (pair[f"selected_hit_top3_{left}"].astype(np.float64) -
                 pair[f"selected_hit_top3_{right}"].astype(np.float64))
        day_sums: dict[str, float] = defaultdict(float)
        day_counts: dict[str, int] = defaultdict(int)
        for day, value in zip(pair["race_date"].astype(str), delta):
            day_sums[day] += float(value)
            day_counts[day] += 1
        ordered_sums = np.asarray([day_sums[day] for day in dates], dtype=np.float64)
        ordered_counts = np.asarray([day_counts[day] for day in dates], dtype=np.float64)
        draws = np.empty(schedule.shape[0], dtype=np.float64)
        for index, sample in enumerate(schedule):
            multiplicity = np.bincount(sample, minlength=len(dates)).astype(np.float64)
            denom = float(np.dot(multiplicity, ordered_counts))
            require(denom > 0, "empty axis date bootstrap draw")
            draws[index] = float(np.dot(multiplicity, ordered_sums) / denom)
        low, high = np.quantile(draws, [0.025, 0.975], method="linear")
        bootstrap_rows.append({"comparison": f"{left}_minus_{right}", "races": len(pair),
                               "hit_rate_difference": float(delta.mean()),
                               "hit_rate_difference_ci95": [float(low), float(high)],
                               "date_bootstrap_draws": int(len(draws)),
                               "schedule_sha256": EXPECTED_BOOTSTRAP_SHA,
                               "date_inventory_sha256": date_hash})
    return pd.DataFrame(summary_rows), pd.DataFrame(bootstrap_rows)


def _phase_prediction_diagnostics(runner_oos: pd.DataFrame, race_oos: pd.DataFrame) -> pd.DataFrame:
    """Summarize OOS binary accuracy and race-level expected event-count calibration."""
    rows: list[dict[str, Any]] = []
    runner_heads = (("early", "label_early", "p_early"), ("recovery", "label_recovery", "p_recovery"))
    observed_years = sorted(set(int(year) for year in runner_oos["year"].unique()) &
                            set(int(year) for year in race_oos["year"].unique()))
    require(observed_years, "phase diagnostics have no shared annual OOS vintages")
    for period in ("ALL",) + tuple(str(year) for year in observed_years):
        if period == "ALL":
            runners = runner_oos
            races = race_oos
        else:
            target_year = int(period)
            runners = runner_oos.loc[runner_oos["year"].eq(target_year)]
            races = race_oos.loc[race_oos["year"].eq(target_year)]
        for head, label_col, probability_col in runner_heads:
            known = runners.loc[runners[label_col].notna()].copy()
            require(len(known) > 0, f"no OOS labels available for phase diagnostic {head}/{period}")
            labels = known[label_col].to_numpy(dtype=np.float64)
            probabilities = known[probability_col].to_numpy(dtype=np.float64)
            require(np.isin(labels, (0.0, 1.0)).all() and np.isfinite(probabilities).all() and
                    ((probabilities >= PHASE_EPS) & (probabilities <= 1.0 - PHASE_EPS)).all(),
                    f"invalid OOS phase diagnostics for {head}/{period}")
            clipped = np.clip(probabilities, PHASE_EPS, 1.0 - PHASE_EPS)
            row_loss = -(labels * np.log(clipped) + (1.0 - labels) * np.log1p(-clipped))
            group_rows = []
            for race_id, group in known.groupby("race_id", sort=True):
                y = group[label_col].to_numpy(dtype=np.float64)
                p = group[probability_col].to_numpy(dtype=np.float64)
                per = -(y * np.log(np.clip(p, PHASE_EPS, 1.0 - PHASE_EPS)) +
                        (1.0 - y) * np.log1p(-np.clip(p, PHASE_EPS, 1.0 - PHASE_EPS)))
                group_rows.append({
                    "race_id": race_id,
                    "predicted_count": float(p.sum()),
                    "observed_count": float(y.sum()),
                    "accuracy": float(np.mean((p >= 0.5) == (y == 1.0))),
                    "mean_nll": float(np.mean(per)),
                    "mean_brier": float(np.mean(np.square(p - y))),
                })
            race_diagnostics = pd.DataFrame(group_rows)
            count_error = race_diagnostics["predicted_count"].to_numpy(dtype=np.float64) - \
                race_diagnostics["observed_count"].to_numpy(dtype=np.float64)
            rows.append({
                "evaluation_period": period, "head": head,
                "labeled_rows": len(known), "labeled_races": int(known["race_id"].nunique()),
                "positive_labels": int(labels.sum()), "negative_labels": int(len(labels) - labels.sum()),
                "race_equal_logloss": float(race_diagnostics["mean_nll"].mean()),
                "race_equal_brier": float(race_diagnostics["mean_brier"].mean()),
                "race_equal_accuracy_at_0_5": float(race_diagnostics["accuracy"].mean()),
                "mean_predicted_probability": float(probabilities.mean()),
                "observed_positive_rate": float(labels.mean()),
                "calibration_in_large_difference": float(probabilities.mean() - labels.mean()),
                "count_calibration_races": len(race_diagnostics),
                "mean_predicted_event_count_per_race": float(race_diagnostics["predicted_count"].mean()),
                "mean_observed_event_count_per_race": float(race_diagnostics["observed_count"].mean()),
                "mean_event_count_error": float(count_error.mean()),
                "mae_event_count_error": float(np.abs(count_error).mean()),
                "rmse_event_count_error": float(np.sqrt(np.mean(np.square(count_error)))),
            })
        known_z = races.loc[races[RACE_LABEL].notna()].copy()
        require(len(known_z) > 0, f"no OOS labels available for phase diagnostic Z/{period}")
        labels_z = known_z[RACE_LABEL].to_numpy(dtype=np.float64)
        probabilities_z = known_z["q_z"].to_numpy(dtype=np.float64)
        require(np.isin(labels_z, (0.0, 1.0)).all() and np.isfinite(probabilities_z).all() and
                ((probabilities_z >= PHASE_EPS) & (probabilities_z <= 1.0 - PHASE_EPS)).all(),
                f"invalid OOS Z diagnostics for {period}")
        clipped_z = np.clip(probabilities_z, PHASE_EPS, 1.0 - PHASE_EPS)
        z_losses = -(labels_z * np.log(clipped_z) + (1.0 - labels_z) * np.log1p(-clipped_z))
        z_errors = probabilities_z - labels_z
        rows.append({
            "evaluation_period": period, "head": "Z",
            "labeled_rows": len(known_z), "labeled_races": int(known_z["race_id"].nunique()),
            "positive_labels": int(labels_z.sum()), "negative_labels": int(len(labels_z) - labels_z.sum()),
            "race_equal_logloss": float(z_losses.mean()),
            "race_equal_brier": float(np.square(z_errors).mean()),
            "race_equal_accuracy_at_0_5": float(np.mean((probabilities_z >= 0.5) == (labels_z == 1.0))),
            "mean_predicted_probability": float(probabilities_z.mean()),
            "observed_positive_rate": float(labels_z.mean()),
            "calibration_in_large_difference": float(probabilities_z.mean() - labels_z.mean()),
            "count_calibration_races": len(known_z),
            "mean_predicted_event_count_per_race": float(probabilities_z.mean()),
            "mean_observed_event_count_per_race": float(labels_z.mean()),
            "mean_event_count_error": float(z_errors.mean()),
            "mae_event_count_error": float(np.abs(z_errors).mean()),
            "rmse_event_count_error": float(np.sqrt(np.mean(np.square(z_errors)))),
        })
    result = pd.DataFrame(rows)
    require(len(result) == 3 * (len(observed_years) + 1), "phase diagnostic row coverage mismatch")
    require(result.notna().all().all(), "phase diagnostic contains missing summary values")
    return result


def evaluate_comparison(
    model_rows: pd.DataFrame,
    runner_oos: pd.DataFrame,
    race_oos: pd.DataFrame,
    reference_evaluation: Mapping[int, pd.DataFrame],
    reference_fit: Mapping[int, Mapping[str, Any]],
    b_fits: Mapping[int, Mapping[str, Any]],
) -> dict[str, pd.DataFrame]:
    eval_rows = model_rows.loc[
        model_rows["year"].between(2024, 2026) & model_rows["race_date"].le(EVAL_END)
    ].copy()
    eval_races = eval_rows.loc[:, ["race_id", "race_date", "year", "field_n"]].drop_duplicates()
    require((len(eval_rows), eval_races["race_id"].nunique(), eval_rows["race_date"].nunique()) ==
            (EXPECTED_EVAL["runners"], EXPECTED_EVAL["races"], EXPECTED_EVAL["dates"]),
            "evaluation cohort changed before probability evaluation")
    a_eval = runner_oos.loc[runner_oos["year"].between(2024, 2026) &
                            runner_oos["race_date"].le(EVAL_END)].copy()
    q_eval = race_oos.loc[race_oos["year"].between(2024, 2026) &
                          race_oos["race_date"].le(EVAL_END)].copy()
    require(len(a_eval) == len(eval_rows) and q_eval["race_id"].nunique() == EXPECTED_EVAL["races"],
            "annual OOS coverage differs from exact evaluation cohort")
    eval_models = eval_rows.loc[:, ["api_record_id", "race_id", "race_date", "year", "field_n",
                                    "horse_number", "finish_position"]].merge(
        a_eval, on=["api_record_id", "race_id", "race_date", "year", "field_n", "horse_number", "finish_position"],
        how="outer", validate="one_to_one", indicator=True,
    )
    require(eval_models["_merge"].eq("both").all(), "A OOS rows differ from exact evaluation rows")
    eval_models = eval_models.drop(columns="_merge")
    require(eval_models["api_record_id"].is_unique, "duplicate evaluation A output key")
    q_index = q_eval.set_index("race_id")
    require(q_index.index.is_unique, "scenario OOS race keys are not unique")

    bins: dict[tuple[str, str, str, int], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    metric_rows: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    marginal_rows: list[dict[str, Any]] = []
    axis_rows: list[dict[str, Any]] = []
    for race_id, runner_group in eval_models.groupby("race_id", sort=True):
        require(race_id in q_index.index, f"missing scenario OOS prediction: {race_id}")
        runner_group = runner_group.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
        q_race = q_index.loc[race_id]
        year = int(runner_group["year"].iloc[0])
        ref_group = reference_evaluation[year].loc[
            reference_evaluation[year]["race_id"].eq(race_id)
        ].sort_values("horse_number", kind="mergesort").reset_index(drop=True)
        require(len(ref_group) == len(runner_group) and
                np.array_equal(ref_group["api_record_id"].to_numpy(dtype=np.int64),
                               runner_group["api_record_id"].to_numpy(dtype=np.int64)),
                f"R raw-score keys differ from evaluation race {race_id}")
        n = int(runner_group["field_n"].iloc[0])
        numbers = runner_group["horse_number"].to_numpy(dtype=np.int64)
        ranks = runner_group["finish_position"].to_numpy(dtype=np.int64)
        require(len(numbers) == n and sorted(ranks.tolist()) == list(range(1, n + 1)),
                f"invalid evaluation roster/ranks {race_id}")
        race_meta = {"race_id": race_id, "date": str(runner_group["race_date"].iloc[0]),
                     "year": year, "n": n, "numbers": numbers, "ranks": ranks}
        reference_scores = ref_group["score"].to_numpy(dtype=np.float64)
        arms = ("A", "B", "R")
        for arm in arms:
            scenario_utilities, scenario_weights = _arm_scenarios(
                arm, runner_group, q_race,
                reference_scores=reference_scores,
                reference_temperature=float(reference_fit[year]["temperature"]),
                b_fit=b_fits[year],
            )
            plc_top, _ = plc_top_for_actual_field(n)
            maps, marginal, mass = probability_maps_from_scenarios(
                scenario_utilities, scenario_weights, numbers, plc_top
            )
            require(abs(mass - 1.0) <= 3e-11, f"joint Q mass mismatch for {arm}/{race_id}")
            for pool in POOL_ORDER:
                if n < POOL_MIN_STARTERS[pool] or (pool == "PLC" and plc_top is None):
                    continue
                require(n >= POOL_MIN_STARTERS[pool], f"{pool} scored below legal minimum in {race_id}")
                truths = truth_ticket_keys(pool, numbers, ranks, plc_top)
                metric, selection = pool_race_metrics(pool, maps[pool], truths)
                metric.update({"race_id": race_id, "race_date": race_meta["date"], "year": year,
                               "field_n": n, "arm": arm})
                selection.update({"race_id": race_id, "race_date": race_meta["date"], "year": year,
                                  "field_n": n, "arm": arm})
                metric_rows.append(metric)
                selection_rows.append(selection)
                _bin_accumulate(bins, pool, arm, str(year), maps[pool], truths)
                _bin_accumulate(bins, pool, arm, "ALL", maps[pool], truths)
            for ix, horse_number in enumerate(numbers):
                marginal_rows.append({
                    "race_id": race_id, "race_date": race_meta["date"], "year": year,
                    "horse_number": int(horse_number), "arm": arm,
                    "p_win": float(marginal["p_win"][ix]), "p_exact2": float(marginal["p_exact2"][ix]),
                    "p_exact3": float(marginal["p_exact3"][ix]), "p_top2": float(marginal["p_top2"][ix]),
                    "p_top3": float(marginal["p_top3"][ix]),
                })
            max_win = float(marginal["p_win"].max())
            selected_ix = min(ix for ix, p in enumerate(marginal["p_win"]) if float(p) >= max_win - 1e-12)
            axis_rows.append({
                "race_id": race_id, "race_date": race_meta["date"], "year": year, "arm": arm,
                "selected_horse_number": int(numbers[selected_ix]),
                "selected_probability": float(marginal["p_win"][selected_ix]),
                "selected_hit_top3": bool(ranks[selected_ix] <= 3),
            })
    metrics = pd.DataFrame(metric_rows)
    selections = pd.DataFrame(selection_rows)
    marginals = pd.DataFrame(marginal_rows)
    axis = pd.DataFrame(axis_rows)
    require(metrics["race_id"].nunique() == EXPECTED_EVAL["races"], "metric race count changed")
    for pool in POOL_ORDER:
        target_count = EXPECTED_EVAL["plc_races"] if pool == "PLC" else EXPECTED_EVAL["races"]
        if pool == "PLC":
            require(metrics.loc[metrics["pool"] == pool, "race_id"].nunique() == target_count,
                    "PLC evaluation denominator changed")
        else:
            require(metrics.loc[metrics["pool"] == pool, "race_id"].nunique() == target_count,
                    f"{pool} evaluation denominator changed")
    summary = metrics.groupby(["pool", "arm"], sort=False).agg(
        races=("race_id", "nunique"), mean_race_nll=("race_nll", "mean"),
        mean_race_brier=("race_brier", "mean"), total_ticket_events=("ticket_count", "sum"),
        realized_events=("event_count", "sum"),
    ).reset_index()
    year_summary = metrics.groupby(["pool", "arm", "year"], sort=False).agg(
        races=("race_id", "nunique"), mean_race_nll=("race_nll", "mean"),
        mean_race_brier=("race_brier", "mean"), total_ticket_events=("ticket_count", "sum"),
        realized_events=("event_count", "sum"),
    ).reset_index()
    reliability = _build_reliability_frame(bins, arms)
    contract_ledger, quarantine = _race_contract_rows(eval_races)
    expected_by_pool = {pool: EXPECTED_EVAL["plc_races"] if pool == "PLC" else EXPECTED_EVAL["races"]
                        for pool in POOL_ORDER}
    observed_by_pool = {pool: int(metrics.loc[metrics["pool"].eq(pool), "race_id"].nunique())
                        for pool in POOL_ORDER}
    require(observed_by_pool == expected_by_pool,
            f"per-pool event denominator changed: {observed_by_pool}")
    require(len(quarantine) == EXPECTED_EVAL["plc_unknown"], "PLC quarantine count changed")
    comparison_summary, year_comparisons, paired_comparisons = _summary_comparisons(metrics)
    dates = sorted(eval_races["race_date"].astype(str).unique().tolist())
    schedule = np.load(BOOTSTRAP, mmap_mode="r", allow_pickle=False)
    bootstrap_reports: list[dict[str, Any]] = []
    bootstrap_draw_rows: list[pd.DataFrame] = []
    for left, right in (("A", "R"), ("B", "A"), ("B", "R")):
        report, draws = _bootstrap_comparison(paired_comparisons, left_arm=left, right_arm=right,
                                              schedule=schedule, dates=dates)
        bootstrap_reports.append(report)
        bootstrap_draw_rows.append(draws)
    axis_summary, axis_bootstrap = _axis_summary(axis, schedule, dates)
    phase_diagnostics = _phase_prediction_diagnostics(runner_oos, race_oos)
    selection_summary = selections.groupby(["pool", "arm"], sort=False).agg(
        races=("race_id", "nunique"), selected_hit_count=("selected_hit", "sum"),
        mean_selected_probability=("selected_probability", "mean"),
    ).reset_index()
    gate_by_comparison = {row["comparison"]: bool(row["comparison_gate_pass"])
                          for row in bootstrap_reports}
    report = {
        "status": "EVALUATED_RESEARCH_ONLY",
        "evaluation_races": EXPECTED_EVAL["races"], "evaluation_runners": EXPECTED_EVAL["runners"],
        "evaluation_dates": EXPECTED_EVAL["dates"], "pool_legal_event_denominators": observed_by_pool,
        "comparisons": bootstrap_reports,
        "A_minus_R_gate_pass": gate_by_comparison["A_minus_R"],
        "B_minus_A_gate_pass": gate_by_comparison["B_minus_A"],
        "B_minus_R_gate_pass": gate_by_comparison["B_minus_R"],
        "B_overall_research_candidate_gate_pass": bool(
            gate_by_comparison["B_minus_A"] and gate_by_comparison["B_minus_R"]),
        "gate_scope": "research-only point and fixed date-bootstrap criteria; no production promotion",
        "statistical_noninferiority_claimed": False,
        "win_axis": axis_summary.to_dict("records"),
        "win_axis_paired_date_bootstrap": axis_bootstrap.to_dict("records"),
        "selection_summary": selection_summary.to_dict("records"),
        "phase_diagnostic_rows": len(phase_diagnostics),
        "fit_uncertainty_included_in_bootstrap": False,
    }
    return {
        "race_pool_metrics": metrics,
        "selected_ticket_ledger": selections,
        "evaluation_runner_marginals": marginals,
        "win_axis_ledger": axis,
        "pool_summary": summary,
        "pool_year_summary": year_summary,
        "pool_comparisons": comparison_summary,
        "pool_year_comparisons": year_comparisons,
        "paired_pool_comparisons": paired_comparisons,
        "reliability_bins": reliability,
        "comparison_bootstrap_draws": pd.concat(bootstrap_draw_rows, ignore_index=True),
        "win_axis_summary": axis_summary,
        "win_axis_bootstrap": axis_bootstrap,
        "selection_summary": selection_summary,
        "phase_diagnostics": phase_diagnostics,
        "evaluation_report": report,
        "race_contract_ledger": contract_ledger,
        "evaluation_quarantine": quarantine,
    }


def run_synthetic_checks() -> dict[str, Any]:
    test_path = EXPERIMENT / "test_dynamic_ability_pace.py"
    require(test_path.is_file(), "synthetic test bundle is missing")
    spec = importlib.util.spec_from_file_location("dynamic_ability_pace_synthetic_tests", test_path)
    require(spec is not None and spec.loader is not None, "could not load synthetic checks")
    tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tests)
    result = tests.run_tests(sys.modules[__name__])
    require(result.get("status") == "PASS_SYNTHETIC", "synthetic checks did not pass")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return result


def _approval_hash_expectations() -> dict[str, str]:
    return {
        "code_bundle_sha256": code_bundle_sha256(),
        "plan_sha256": sha256_file(EXPERIMENT / "PLAN.md"),
        "source_preflight_sha256": sha256_file(OUTPUTS / "source_preflight.json"),
        "input_manifest_sha256": sha256_file(INPUT_MANIFEST),
        "model_inputs_sha256": sha256_file(MODEL_INPUTS),
        "race_inputs_sha256": sha256_file(RACE_INPUTS),
        "history_lineage_sha256": sha256_file(HISTORY_LINEAGE),
        "source_manifest_sha256": sha256_file(SOURCE_MANIFEST),
        "rules_contract_sha256": sha256_file(RULES),
        "design_contract_sha256": sha256_file(CONTRACT),
        "reference_manifest_sha256": sha256_file(REFERENCE_MANIFEST),
        "bootstrap_sha256": sha256_file(BOOTSTRAP),
        "bootstrap_receipt_sha256": sha256_file(BOOTSTRAP_RECEIPT),
    }


def validate_execution_approval() -> dict[str, Any]:
    require(APPROVAL.is_file(), "supervisor fit/evaluate approval receipt is missing")
    approval = json_read(APPROVAL)
    require(approval.get("status") == "PASS", "execution approval status is not PASS")
    require(approval.get("scope") == "fit_evaluate", "execution approval scope is not fit_evaluate")
    require(int(approval.get("permitted_runs", 0)) == 1, "approval must permit exactly one execution")
    preflight_path = OUTPUTS / "source_preflight.json"
    require(preflight_path.is_file(), "structural source preflight is missing")
    preflight = json_read(preflight_path)
    require(preflight.get("status") == "PASS_STRUCTURAL_PREFLIGHT_NO_FIT_OR_METRICS",
            "structural source preflight did not pass")
    require(preflight.get("fitted") is False and preflight.get("probabilities_computed") is False and
            preflight.get("outcome_metrics_computed") is False,
            "preflight receipt indicates unauthorized model/probability/metric work")
    expected = _approval_hash_expectations()
    provided = approval.get("hashes", {}) if isinstance(approval.get("hashes", {}), dict) else {}
    for key, value in expected.items():
        actual = approval.get(key, provided.get(key))
        require(actual == value, f"execution approval {key} does not match current files")
    require(preflight.get("code_bundle_sha256") == expected["code_bundle_sha256"],
            "source preflight does not pin the current code bundle")
    require(preflight.get("plan_sha256") == expected["plan_sha256"], "source preflight plan hash is stale")
    require(preflight.get("input_manifest_sha256") == expected["input_manifest_sha256"],
            "source preflight input manifest hash is stale")
    require(preflight.get("source_manifest_sha256") == expected["source_manifest_sha256"],
            "source preflight source manifest hash is stale")
    # Revalidate read-only inputs, score sources, rules, bootstrap and labels
    # immediately before claiming the one approved fit/evaluation execution.
    model, race, manifest, frozen = load_input_bundle()
    rules_bootstrap = _validate_rules_and_bootstrap(model)
    reference_calibration, reference_evaluation, _ = load_f1_reference(model)
    require(len(reference_calibration) == len(reference_evaluation) == len(EVAL_YEARS),
            "R raw-score source preflight no longer has the expected folds")
    support = audit_phase_support(model, race)
    require(support.get("all_folds_supported") is True,
            "one or more phase heads lack predeclared support; B fit is not authorized")
    require(frozen["input_manifest_sha256"] == expected["input_manifest_sha256"],
            "fresh input bundle hash differs from approval")
    require(rules_bootstrap["rules_sha256"] == expected["rules_contract_sha256"] and
            rules_bootstrap["bootstrap_sha256"] == expected["bootstrap_sha256"] and
            rules_bootstrap["bootstrap_receipt_sha256"] == expected["bootstrap_receipt_sha256"],
            "fresh rules/bootstrap audit differs from approval")
    require(study_size_bytes() < MAX_STUDY_BYTES, "study already exceeds the 100 MB storage limit")
    return {
        "approval_sha256": sha256_file(APPROVAL), "hashes": expected,
        "input_rows": len(model), "input_races": int(model["race_id"].nunique()),
        "evaluation_races": frozen["eval_races"], "phase_support": support,
        "pool_legal_event_denominators": rules_bootstrap["pool_legal_event_denominators"],
        "approval_reviewer": approval.get("reviewer"), "approved_at": approval.get("approved_at"),
    }


def _artifact_records() -> list[dict[str, Any]]:
    files = sorted(
        [path for root in (OUTPUTS, MODELS) for path in root.rglob("*")
         if path.is_file() and not path.is_symlink() and path.name != "fit_run_receipt.json"],
        key=lambda path: path.relative_to(PROJECT).as_posix(),
    )
    return [{"path": path.relative_to(PROJECT).as_posix(), "sha256": sha256_file(path),
             "bytes": path.stat().st_size} for path in files]


def _write_final_receipt(receipt: dict[str, Any]) -> None:
    path = confined_output_path("fit_run_receipt.json")
    base_bytes = study_size_bytes()
    receipt["study_bytes_after_receipt"] = 0
    payload = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2,
                         allow_nan=False, default=_json_default).encode("utf-8") + b"\n"
    for _ in range(8):
        expected_total = base_bytes + len(payload)
        if receipt["study_bytes_after_receipt"] == expected_total:
            break
        receipt["study_bytes_after_receipt"] = expected_total
        payload = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2,
                             allow_nan=False, default=_json_default).encode("utf-8") + b"\n"
    require(base_bytes + len(payload) < MAX_STUDY_BYTES, "fit outputs would exceed the 100 MB storage limit")
    write_bytes_once(path, payload)
    require(study_size_bytes() == receipt["study_bytes_after_receipt"],
            "final study-byte receipt does not match on-disk size")


def run_fit_evaluate() -> dict[str, Any]:
    """Execute the single approved fit/evaluate run; never retry after a claim."""
    approvals = validate_execution_approval()
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    existing_output_names = sorted(path.name for path in OUTPUTS.iterdir())
    require(existing_output_names == ["source_preflight.json"],
            "fit run requires an empty output directory except for source_preflight.json")
    require(not MODELS.exists() or not any(MODELS.iterdir()), "model output directory is not empty")
    started = datetime.now(timezone.utc).isoformat()
    claim_path = confined_output_path("execution_claim.json")
    write_json_once(claim_path, {
        "status": "RUN_CLAIMED_NO_RETRY", "scope": "fit_evaluate", "started_at_utc": started,
        "approval_sha256": approvals["approval_sha256"],
        "code_bundle_sha256": approvals["hashes"]["code_bundle_sha256"], "permitted_runs": 1,
    })
    print(json.dumps({"phase": "fit_evaluate_started", "started_at_utc": started,
                      "approval_sha256": approvals["approval_sha256"]}), flush=True)

    model_rows, race_rows, _manifest, _frozen = load_input_bundle()
    runner_oos, race_oos, fold_parameters = fit_annual_oos(model_rows, race_rows)
    write_frame_once(confined_output_path("annual_oos_runner_predictions.parquet"), runner_oos)
    write_frame_once(confined_output_path("annual_oos_race_predictions.parquet"), race_oos)
    print(json.dumps({"phase": "annual_oos_complete", "runner_rows": len(runner_oos),
                      "race_rows": len(race_oos), "folds": len(fold_parameters)}), flush=True)

    reference_calibration, reference_evaluation, reference_sources = load_f1_reference(model_rows)
    reference_fit, b_fits, evaluation_r = fit_reference_and_b(
        runner_oos, race_oos, model_rows, reference_calibration, reference_evaluation
    )
    evaluated = evaluate_comparison(model_rows, runner_oos, race_oos, evaluation_r, reference_fit, b_fits)
    output_frames = {
        "race_pool_metrics.parquet": evaluated["race_pool_metrics"],
        "selected_ticket_ledger.parquet": evaluated["selected_ticket_ledger"],
        "evaluation_runner_marginals.parquet": evaluated["evaluation_runner_marginals"],
        "win_axis_ledger.parquet": evaluated["win_axis_ledger"],
        "pool_summary.parquet": evaluated["pool_summary"],
        "pool_year_summary.parquet": evaluated["pool_year_summary"],
        "pool_comparisons.parquet": evaluated["pool_comparisons"],
        "pool_year_comparisons.parquet": evaluated["pool_year_comparisons"],
        "paired_pool_comparisons.parquet": evaluated["paired_pool_comparisons"],
        "reliability_bins.parquet": evaluated["reliability_bins"],
        "comparison_bootstrap_draws.parquet": evaluated["comparison_bootstrap_draws"],
        "win_axis_summary.parquet": evaluated["win_axis_summary"],
        "win_axis_bootstrap.parquet": evaluated["win_axis_bootstrap"],
        "selection_summary.parquet": evaluated["selection_summary"],
        "phase_diagnostics.parquet": evaluated["phase_diagnostics"],
        "race_contract_ledger.parquet": evaluated["race_contract_ledger"],
        "evaluation_quarantine.parquet": evaluated["evaluation_quarantine"],
    }
    for name, frame in output_frames.items():
        write_frame_once(confined_output_path(name), frame)
    model_count = len(list(MODELS.glob("*.txt")))
    require(model_count == 32, f"expected 32 saved LightGBM models, found {model_count}")
    source_score_manifest = json_read(REFERENCE_MANIFEST)
    f1_eval_files = []
    for year in EVAL_YEARS:
        item = next(row for row in source_score_manifest["evaluation_score_assets"]
                    if int(row["evaluation_year"]) == year)
        path = _project_input(str(item["path"]))
        f1_eval_files.append({"year": year, "path": path.relative_to(PROJECT).as_posix(),
                              "sha256": sha256_file(path)})
    parameters = {
        "study": "20261022_dynamic_ability_pace_v1",
        "design_contract_path": CONTRACT.relative_to(PROJECT).as_posix(),
        "design_contract_sha256": approvals["hashes"]["design_contract_sha256"],
        "features": {"A": list(A_FEATURES), "runner_phase": list(RUNNER_PHASE_FEATURES),
                     "race_Z": list(RACE_Z_FEATURES)},
        "lightgbm_common": {key: value for key, value in LGBM_COMMON.items() if key != "objective"},
        "A_rounds": 180, "phase_rounds": 180, "hessian_floor": HESSIAN_FLOOR,
        "ordered_top3_denominators": [
            "N starters at rank 1",
            "N-1 remaining starters after the actual rank-1 horse is removed",
            "N-2 remaining starters after the actual rank-1 and rank-2 horses are removed",
        ],
        "annual_oos_fold_parameters": fold_parameters,
        "R_reference_fits": reference_fit, "B_vintage_fits": b_fits,
        "R_raw_score_sources": reference_sources, "F1_evaluation_score_sources": f1_eval_files,
        "optimizer_bounds": list(TEMPERATURE_BOUNDS), "phase_clip_epsilon": PHASE_EPS,
        "selection_rule": "tickets p >= max(p)-1e-12 then lexicographically smallest horse-number key; selected p is its own probability",
        "reliability_weighting": "pooled_ticket_event_count, reported for ALL and each evaluation year, separate from race-equal proper scores",
        "environment": {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__,
                        "pandas": pd.__version__, "lightgbm": lgb.__version__, "scipy": scipy.__version__},
        "training_run_count": 1,
        "optimizer_fit_counts": {"A_temperature": 8, "phase_temperatures": 24,
                                 "R_temperature": 3, "B_temperature": 3, "gamma_vectors": 3,
                                 "LightGBM_models": 32},
        "output_artifacts": list(output_frames),
    }
    write_json_once(confined_output_path("parameters.json"), parameters)
    write_json_once(confined_output_path("report.json"), evaluated["evaluation_report"])
    require(study_size_bytes() < MAX_STUDY_BYTES, "study exceeds the 100 MB limit before execution receipt")
    artifacts = _artifact_records()
    report_sha = sha256_file(OUTPUTS / "report.json")
    finished = datetime.now(timezone.utc).isoformat()
    expected_oos_rows = model_rows.loc[model_rows["year"] >= FIRST_OOS_YEAR]
    receipt = {
        "status": "COMPLETED_ONE_APPROVED_FIT_EVALUATE_RUN", "scope": "fit_evaluate",
        "approval_sha256": approvals["approval_sha256"], **approvals["hashes"],
        "started_at_utc": started, "finished_at_utc": finished,
        "fitted_model_counts": {"A_lightgbm": 8, "phase_lightgbm": 24, "gamma_vectors": 3,
                                "scalar_temperatures": 38, "all_lightgbm": model_count},
        "annual_oos_coverage": {
            "races": int(race_oos["race_id"].nunique()), "runners": len(runner_oos),
            "first_year": FIRST_OOS_YEAR, "last_year": LAST_OOS_YEAR,
            "expected_target_rows_year_ge_2019": int(len(expected_oos_rows)),
            "expected_target_races_year_ge_2019": int(expected_oos_rows["race_id"].nunique()),
        },
        "evaluation_report_sha256": report_sha, "output_artifacts": artifacts,
        "study_bytes_before_receipt": study_size_bytes(), "study_bytes_after_receipt": 0,
        "report": evaluated["evaluation_report"], "fit_uncertainty_in_bootstrap": False,
    }
    _write_final_receipt(receipt)
    print(json.dumps({
        "phase": "fit_evaluate_complete",
        "receipt": (OUTPUTS / "fit_run_receipt.json").relative_to(PROJECT).as_posix(),
        "study_bytes": study_size_bytes(), "report": evaluated["evaluation_report"],
    }, ensure_ascii=False, indent=2, allow_nan=False, default=_json_default), flush=True)
    return evaluated["evaluation_report"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--synthetic-checks", action="store_true",
                       help="run synthetic numerical and fail-closed checks only")
    modes.add_argument("--source-preflight", action="store_true",
                       help="run read-only input/source structural preflight only")
    modes.add_argument("--run", action="store_true",
                       help="execute the single supervisor-approved fit/evaluate run")
    args = parser.parse_args(argv)
    if args.run:
        run_fit_evaluate()
    elif args.source_preflight:
        source_preflight()
    else:
        run_synthetic_checks()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())








