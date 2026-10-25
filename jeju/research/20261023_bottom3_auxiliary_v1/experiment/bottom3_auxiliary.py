#!/usr/bin/env python3
"""Approval-gated fixed Bottom3 auxiliary-model comparison.

Default and --synthetic-checks use only synthetic examples. --source-preflight
checks frozen inputs, labels, time roles, and exact keys without fitting,
calibrating, or calculating Bottom3 probabilities/performance. --run is the
single hash-approved evaluation path.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import platform
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import scipy
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp


PROJECT = Path(__file__).resolve().parents[4]
STUDY = PROJECT / "jeju/research/20261023_bottom3_auxiliary_v1"
EXPERIMENT = STUDY / "experiment"
OUTPUTS = EXPERIMENT / "outputs"
MODELS = EXPERIMENT / "models"
PLAN = EXPERIMENT / "PLAN.md"
TEST = EXPERIMENT / "test_bottom3_auxiliary.py"
CONTRACT = STUDY / "supervisor/DESIGN_CONTRACT.md"
SESSION_START = STUDY / "supervisor/SESSION_START.json"
APPROVAL = STUDY / "supervisor/EXECUTION_APPROVAL.json"
PREFLIGHT = OUTPUTS / "source_preflight.json"

F1_ROOT = PROJECT / "jeju/research/20261010_style_history_ablation_v1"
F1_FEATURES = F1_ROOT / "outputs/features.parquet"
F1_ARTIFACTS = F1_ROOT / "ARTIFACT_MANIFEST.json"
F1_META = {year: F1_ROOT / f"outputs/F1_STYLE6_{year}/meta.json" for year in (2024, 2025, 2026)}

S_STUDY = PROJECT / "jeju/research/20261022_tb_state_transfer_v1"
SOURCE_AUDIT = STUDY / "audit/SOURCE_AUDIT.json"
S_PARAMS = S_STUDY / "experiment/outputs/parameters.json"
S_SCORES = S_STUDY / "experiment/outputs/candidate_oos_scores.parquet"
S_ENGINE = S_STUDY / "experiment/state_transfer.py"
S_FINAL_MANIFEST = S_STUDY / "FINAL_MANIFEST.json"
S_STATE_FEATURES = S_STUDY / "inputs/state_features.parquet"
S_STATE_LINEAGE = S_STUDY / "inputs/state_lineage.parquet"
S_INPUT_MANIFEST = S_STUDY / "inputs/input_manifest.json"
S_SOURCE_MANIFEST = S_STUDY / "audit/source_manifest.json"
S_HISTORY_LEDGER = S_STUDY / "audit/history_eligibility.parquet"

BOOTSTRAP = PROJECT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT = PROJECT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"

CONTRACT_SHA256 = "ff6e3af2d454cd30edb56df1251700320b01de3478939c98199e0886bf22f084"
SESSION_START_SHA256 = "c7cd21d7300e0d3b4b070c51a10ca058bbb3214b73df6cc959b2cbff15c64bbe"
EXPECTED_BOOTSTRAP_SHA256 = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
EXPECTED_BOOTSTRAP_RECEIPT_SHA256 = "6bdcf550065a2e6bb5038fc8d02eb070f026ba0efe5d3ebf1c3530a4e53c397e"
EXPECTED_DATE_INVENTORY_SHA256 = "e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84"
EXPECTED_F1_FEATURES_SHA256 = "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f"
EXPECTED_COHORT = {"runners": 52_155, "races": 5_206, "eval_runners": 17_412,
                   "eval_races": 1_779, "eval_dates": 269, "eval_bottom3": 5_337}
EXPECTED_EVAL_END = "2026-09-19"
YEARS = (2024, 2025, 2026)
YEAR_RACES = {2024: 637, 2025: 654, 2026: 488}
TEMPERATURE_BOUNDS = (0.35, 4.0)
TEMPERATURE_XTOL = 1e-12
SELECTION_TOLERANCE = 1e-12
EPS = 1e-15
MAX_STUDY_BYTES = 30_000_000
BOOTSTRAP_DRAWS = 2_000

STATE_COLUMNS = (
    "state_rank_mean", "state_rank_sd", "state_distance_slope", "state_distance_sd",
    "state_rank_current", "state_rank_current_sd", "state_rank_n",
    "state_days_since_rank_observation", "state_rank_current_field_gap", "state_rank_current_field_rank",
)
CAT_COLUMNS = ("grade_raw", "previous_sex", "previous_result_status")
META_COLUMNS = (
    "api_record_id", "race_id", "race_date", "horse_id", "horse_number", "distance_m",
    "field_n", "finish_position",
)
SCORE_KEY_COLUMNS = ("api_record_id", "race_id", "race_date", "horse_number", "field_n")
BIN_EDGES = np.asarray(
    [0.0, 0.00001, 0.00005, 0.0001, 0.00025, 0.0005, 0.001, 0.0025,
     0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0], dtype=np.float64
)
LGBM_PARAMS = {
    "objective": "binary", "metric": "binary_logloss", "learning_rate": 0.04,
    "num_leaves": 15, "min_data_in_leaf": 100, "lambda_l2": 5.0,
    "num_threads": 4, "deterministic": True, "force_col_wise": True,
    "verbosity": -1, "seed": 20261008,
}

SOURCE_PINS: dict[str, tuple[Path, str]] = {
    "SOURCE_AUDIT": (SOURCE_AUDIT, "a69bc897e896427e38e2e61ce3470c909cea10c2a3dbfa7bab5c19b9b50c6137"),
    "F1_FEATURES": (F1_FEATURES, EXPECTED_F1_FEATURES_SHA256),
    "F1_ARTIFACT_MANIFEST": (F1_ARTIFACTS, "6afc0e8f73ec086052fad4cde4d7edcd62fdf1bbc782108da89732dc3a5b4a4e"),
    "F1_META_2024": (F1_META[2024], "15acbf959654da82d2240027e7b7d768bb9226af18395dac9ec92a68a4471726"),
    "F1_META_2025": (F1_META[2025], "23c4b0684477f34fbb2e99c22d0037cd903d5459db369f084773ec25c640f4a8"),
    "F1_META_2026": (F1_META[2026], "e9dbfe5226571cb29e34b352a4ad8808a735d70929e66b42efb41b3e807ff06d"),
    "S_STATE_FEATURES": (S_STATE_FEATURES, "ac956c959ce853aa129c738113c598d4ecc968d88dc1306c0f5fa5f4712a78e7"),
    "S_STATE_LINEAGE": (S_STATE_LINEAGE, "62c4c0896b3a0a4c44b64e56f53ad1ad1b862953c6ded618892e1861624f5dd0"),
    "S_INPUT_MANIFEST": (S_INPUT_MANIFEST, "7561d6f91d5a1a5059add0741d912e33896b04810a19dd1dab955b0ebd229f5e"),
    "S_SOURCE_MANIFEST": (S_SOURCE_MANIFEST, "810e4043e5f3bf3e15b5131f17afc5dcb4067ba6b353f488508f16df04d3f445"),
    "S_HISTORY_LEDGER": (S_HISTORY_LEDGER, "0aeef4ba4e5c072d19993d4286023c68ee06fabaaf6b29fa651ffad95ee1b3ef"),
    "S_PARAMETERS": (S_PARAMS, "46fda546b2a537373291c83190ef7c6f00ffda94fccebcf9090c6f01dfc9c23e"),
    "S_OOS_SCORES": (S_SCORES, "fe08bdf93b07f8a180ad02416cbbc1488db282c761564b67b886114ece56f6e9"),
    "S_ENGINE": (S_ENGINE, "963b2bcb574f3d49e539ae4e944a8a2f8f9bd769568d83018c2dcbcd2fa0623c"),
    "S_FINAL_MANIFEST": (S_FINAL_MANIFEST, "86d0153e287f877add1b10c3172471cf5c3aac9f251890423cd7d97f75abba3a"),
    "BOOTSTRAP_SCHEDULE": (BOOTSTRAP, EXPECTED_BOOTSTRAP_SHA256),
    "BOOTSTRAP_RECEIPT": (BOOTSTRAP_RECEIPT, EXPECTED_BOOTSTRAP_RECEIPT_SHA256),
    "DESIGN_CONTRACT": (CONTRACT, CONTRACT_SHA256),
    "SESSION_START": (SESSION_START, SESSION_START_SHA256),
}

LIGHTGBM_TRAIN_CALLS = 0
TEMPERATURE_FIT_CALLS = 0


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def _json_default(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def code_hashes() -> dict[str, str]:
    engine_sha = sha256_file(EXPERIMENT / "bottom3_auxiliary.py")
    test_sha = sha256_file(TEST)
    digest = hashlib.sha256()
    for path in (EXPERIMENT / "bottom3_auxiliary.py", TEST):
        relative = path.relative_to(PROJECT).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(path)))
    return {"plan_sha256": sha256_file(PLAN), "engine_sha256": engine_sha,
            "test_sha256": test_sha, "code_bundle_sha256": digest.hexdigest(),
            "contract_sha256": sha256_file(CONTRACT)}


def _ensure_experiment_path(path: Path) -> Path:
    resolved = Path(path).resolve(strict=False)
    require(resolved.is_relative_to(EXPERIMENT.resolve()), f"write target escapes experiment: {path}")
    return resolved


def _write_json_once(path: Path, value: Any) -> None:
    target = _ensure_experiment_path(path)
    require(not target.exists(), f"refusing to overwrite: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                         allow_nan=False, default=_json_default).encode("utf-8") + b"\n"
    with target.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _write_frame_once(path: Path, frame: pd.DataFrame) -> None:
    target = _ensure_experiment_path(path)
    require(not target.exists(), f"refusing to overwrite: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        frame.to_parquet(stream, index=False, compression="zstd")
        stream.flush()
        os.fsync(stream.fileno())


def _study_bytes() -> int:
    return sum(p.stat().st_size for p in STUDY.rglob("*") if p.is_file() and not p.is_symlink())


def _safe_source_record(name: str, path: Path, expected_sha: str) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(PROJECT.resolve()), f"source path outside project: {name}")
    digest = sha256_file(resolved)
    require(digest == expected_sha, f"frozen source SHA mismatch: {name}")
    return {"path": resolved.relative_to(PROJECT).as_posix(), "sha256": digest,
            "bytes": resolved.stat().st_size}


def _canonical_date(series: pd.Series, name: str) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce")
    require(parsed.notna().all(), f"invalid dates in {name}")
    return parsed.dt.strftime("%Y-%m-%d")


def _get_s_model_metadata(parameters: Mapping[str, Any], year: int) -> dict[str, Any]:
    found = [row for row in parameters.get("models", [])
             if row.get("arm") == "S" and int(row.get("evaluation_year", -1)) == year]
    require(len(found) == 1, f"S metadata missing or duplicated for {year}")
    return found[0]


def _vocabulary_from_initial_train(frame: pd.DataFrame, year: int,
                                   categorical_columns: Sequence[str]) -> dict[str, list[str]]:
    mask = frame.year.between(2017, year - 3)
    require(mask.any(), f"empty initial train set for vocabulary in {year}")
    vocab: dict[str, list[str]] = {}
    for column in categorical_columns:
        values = sorted(frame.loc[mask, column].dropna().astype(str).unique().tolist())
        require(values, f"empty train-only category vocabulary: {column}/{year}")
        vocab[column] = values
    return vocab


def _load_frozen_inputs(*, read_score_values: bool = False) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    source_records = {name: _safe_source_record(name, path, expected)
                      for name, (path, expected) in SOURCE_PINS.items()}
    params = read_json(S_PARAMS)
    f1_artifacts = read_json(F1_ARTIFACTS)
    source_artifacts = f1_artifacts.get("study_artifacts", {})
    input_manifest = read_json(S_INPUT_MANIFEST)

    f1_keys = list(params.get("features", {}).get("S", []))
    require(len(f1_keys) == 40 and len(set(f1_keys)) == 40, "frozen S feature order/count changed")
    require(tuple(f1_keys[30:]) == STATE_COLUMNS, "frozen S state feature block changed")
    cat_columns = list(params.get("features", {}).get("categorical_columns", []))
    require(tuple(cat_columns) == CAT_COLUMNS, "frozen categorical feature list changed")
    require(params.get("lightgbm_parameters") == LGBM_PARAMS,
            "S LightGBM parameter contract changed")
    require(params.get("fit_budget", {}).get("final_models") == 6 and
            params.get("fit_budget", {}).get("LightGBM_train_calls") == 12,
            "S reference fit metadata changed")
    expected_target = input_manifest.get("cohort_census", {}).get("target_2017_plus", {})
    require(expected_target.get("rows") == EXPECTED_COHORT["runners"] and
            expected_target.get("races") == EXPECTED_COHORT["races"],
            "frozen S target cohort census changed")
    for name, (path, _) in SOURCE_PINS.items():
        if name.startswith("F1_META_"):
            rel = path.relative_to(PROJECT).as_posix()
            entry = source_artifacts.get(rel)
            require(isinstance(entry, Mapping) and entry.get("sha256") == source_records[name]["sha256"],
                    f"F1 artifact manifest does not pin {name}")

    base_features = f1_keys[:30]
    require(set(CAT_COLUMNS).issubset(base_features), "categoricals are not within the 30 F1 columns")
    feature_columns = list(dict.fromkeys([*META_COLUMNS, *base_features]))
    frame = pd.read_parquet(F1_FEATURES, columns=feature_columns)
    require(len(frame) == EXPECTED_COHORT["runners"] and frame.api_record_id.dtype == np.dtype("int64") and
            frame.api_record_id.is_unique, "frozen F1 target row/id inventory changed")
    require(frame.race_id.map(lambda v: type(v) is str and bool(v)).all() and
            frame.horse_id.map(lambda v: type(v) is str and bool(v)).all(), "invalid F1 race/horse IDs")
    frame["race_date"] = _canonical_date(frame.race_date, "F1 race_date")
    frame["year"] = frame.race_date.str[:4].astype(np.int16)
    require(set(frame.year.unique()) == set(range(2017, 2027)), "F1 target year support changed")
    require(frame.distance_m.notna().all() and frame.field_n.notna().all() and
            frame.finish_position.notna().all(), "target roster/label fields are missing")
    for col in ("field_n", "finish_position", "horse_number"):
        values = pd.to_numeric(frame[col], errors="coerce").to_numpy(dtype=np.float64)
        require(np.isfinite(values).all() and np.equal(values, np.rint(values)).all(),
                f"F1 integer field malformed: {col}")
        frame[col] = values.astype(np.int64)
    require((frame.field_n >= 3).all(), "Bottom3 subset definition requires every race N>=3")
    frame["distance_m"] = pd.to_numeric(frame.distance_m, errors="coerce")
    require(np.isfinite(frame.distance_m.to_numpy(dtype=np.float64)).all(), "invalid distance input")

    state_columns = ["api_record_id", "race_id", "race_date", "cutoff", "historydate", *STATE_COLUMNS]
    state = pd.read_parquet(S_STATE_FEATURES, columns=state_columns)
    require(list(state.columns) == state_columns and len(state) == EXPECTED_COHORT["runners"] and
            state.api_record_id.dtype == np.dtype("int64") and state.api_record_id.is_unique,
            "S state feature schema/keys changed")
    require(state.race_id.map(lambda v: type(v) is str and bool(v)).all(), "invalid state race IDs")
    state["race_date"] = _canonical_date(state.race_date, "state race_date")
    state["cutoff"] = _canonical_date(state.cutoff, "state cutoff")
    state["historydate"] = pd.to_datetime(state.historydate, errors="coerce").dt.strftime("%Y-%m-%d")
    require((pd.to_datetime(state.cutoff) == pd.to_datetime(state.race_date) - pd.Timedelta(days=2)).all(),
            "state cutoff differs from target date T-2")
    available = state.historydate.notna()
    require((state.loc[available, "historydate"] <= state.loc[available, "cutoff"]).all(),
            "state history exceeds target T-2 cutoff")
    numeric_state = state.loc[:, list(STATE_COLUMNS)].to_numpy(dtype=np.float64, na_value=np.nan)
    require((np.isfinite(numeric_state) | np.isnan(numeric_state)).all(), "state has infinite values")
    require(np.isfinite(state[list(set(STATE_COLUMNS) - {"state_days_since_rank_observation"})]
                        .to_numpy(dtype=np.float64)).all(), "state has unexpected missing inputs")

    lineage_columns = ["api_record_id", "race_id", "horse_id", "cutoff", "historydate",
                       "latest_history_race_id", "history_update_count"]
    lineage = pd.read_parquet(S_STATE_LINEAGE, columns=lineage_columns)
    require(list(lineage.columns) == lineage_columns and len(lineage) == EXPECTED_COHORT["runners"] and
            lineage.api_record_id.dtype == np.dtype("int64") and lineage.api_record_id.is_unique,
            "S state lineage schema/keys changed")
    lineage["cutoff"] = _canonical_date(lineage.cutoff, "lineage cutoff")
    lineage["historydate"] = pd.to_datetime(lineage.historydate, errors="coerce").dt.strftime("%Y-%m-%d")
    lineage["race_date"] = (pd.to_datetime(lineage.cutoff) + pd.Timedelta(days=2)).dt.strftime("%Y-%m-%d")
    f1_lineage = frame[["api_record_id", "race_id", "race_date", "horse_id"]]
    actual_lineage = lineage[["api_record_id", "race_id", "race_date", "horse_id"]]
    joined_lineage = f1_lineage.merge(actual_lineage, on=["api_record_id", "race_id", "race_date", "horse_id"],
                                      how="outer", validate="one_to_one", indicator=True)
    require(len(joined_lineage) == EXPECTED_COHORT["runners"] and joined_lineage._merge.eq("both").all(),
            "state lineage identity keys differ from F1 target keys")
    dates = state[["api_record_id", "race_id", "race_date", "cutoff", "historydate"]].merge(
        lineage[["api_record_id", "race_id", "race_date", "cutoff", "historydate"]],
        on=["api_record_id", "race_id", "race_date"], how="outer", suffixes=("_state", "_lineage"),
        validate="one_to_one", indicator=True)
    history_equal = dates.historydate_state.eq(dates.historydate_lineage) | (
        dates.historydate_state.isna() & dates.historydate_lineage.isna())
    require(len(dates) == EXPECTED_COHORT["runners"] and dates._merge.eq("both").all() and
            dates.cutoff_state.eq(dates.cutoff_lineage).all() and history_equal.all(),
            "state lineage cutoff/history date mismatch")
    updates = pd.to_numeric(lineage.history_update_count, errors="coerce").to_numpy(dtype=np.float64)
    require(np.isfinite(updates).all() and np.equal(updates, np.rint(updates)).all() and (updates >= 0).all(),
            "invalid lineage history update counts")
    rank_support = pd.to_numeric(state.state_rank_n, errors="coerce").to_numpy(dtype=np.float64)
    require(np.isfinite(rank_support).all() and np.equal(rank_support, np.rint(rank_support)).all() and
            np.array_equal(rank_support.astype(np.int64), updates.astype(np.int64)),
            "state lineage history count differs from state support count")

    joined = frame.merge(state[["api_record_id", "race_id", "race_date", *STATE_COLUMNS]],
                         on=["api_record_id", "race_id", "race_date"], how="outer",
                         validate="one_to_one", indicator=True)
    require(len(joined) == EXPECTED_COHORT["runners"] and joined._merge.eq("both").all(),
            "F1/S state key set differs")
    joined = joined.drop(columns="_merge")
    require(joined.horse_id.notna().all() and joined.horse_number.notna().all(), "joined roster metadata missing")
    for feature in f1_keys:
        if feature not in CAT_COLUMNS:
            require(pd.api.types.is_numeric_dtype(joined[feature].dtype),
                    f"non-numeric model feature requires unexpected preprocessing: {feature}")
            values = pd.to_numeric(joined[feature], errors="coerce").to_numpy(dtype=np.float64, na_value=np.nan)
            require((np.isfinite(values) | np.isnan(values)).all(), f"infinite model feature: {feature}")
    joined = joined.sort_values(["race_date", "race_id", "horse_number"], kind="mergesort").reset_index(drop=True)

    race_counts = 0
    bottom3_total = 0
    for race_id, group in joined.groupby("race_id", sort=False):
        n_values = group.field_n.unique()
        require(len(n_values) == 1, f"field size varies within race {race_id}")
        n = int(n_values[0])
        ranks = group.finish_position.to_numpy(dtype=np.int64)
        require(n >= 3 and len(group) == n and group.api_record_id.is_unique and group.horse_id.is_unique and
                group.horse_number.is_unique and sorted(ranks.tolist()) == list(range(1, n + 1)),
                f"incomplete or invalid normal-finish roster in {race_id}")
        y = ranks >= n - 2
        require(int(y.sum()) == 3, f"Bottom3 label count is not three in {race_id}")
        race_counts += 1
        bottom3_total += int(y.sum())
    require((len(joined), race_counts, bottom3_total) == (52_155, 5_206, 15_618),
            "frozen Bottom3 training label census changed")

    models = {year: _get_s_model_metadata(params, year) for year in YEARS}
    vocab_by_year: dict[int, dict[str, list[str]]] = {}
    folds: dict[str, Any] = {}
    for year in YEARS:
        vocab = _vocabulary_from_initial_train(joined, year, cat_columns)
        require(models[year].get("feature_names") == f1_keys and
                models[year].get("categorical_vocabulary") == vocab,
                f"train-only category or ordered feature metadata differs from S in {year}")
        vocab_by_year[year] = vocab
        values = joined.year.to_numpy(dtype=np.int64)
        role_masks = {
            "initial_train": (values >= 2017) & (values <= year - 3),
            "early_stop": values == year - 2,
            "refit": (values >= 2017) & (values <= year - 2),
            "calibration": values == year - 1,
            "evaluation": (values == year) & (joined.race_date.to_numpy() <= EXPECTED_EVAL_END),
        }
        expected_years = {
            "initial_train": set(range(2017, year - 2)), "early_stop": {year - 2},
            "refit": set(range(2017, year - 1)), "calibration": {year - 1}, "evaluation": {year},
        }
        folds[str(year)] = {}
        for role, mask in role_masks.items():
            frame_part = joined.loc[mask]
            require(set(frame_part.year.unique()) == expected_years[role], f"{role} year support changed in {year}")
            folds[str(year)][role] = {"rows": len(frame_part), "races": int(frame_part.race_id.nunique()),
                                      "date_min": str(frame_part.race_date.min()),
                                      "date_max": str(frame_part.race_date.max())}
        require(folds[str(year)]["evaluation"]["races"] == YEAR_RACES[year],
                f"evaluation denominator changed for {year}")

    score_columns = ["arm", "year", "role", *SCORE_KEY_COLUMNS]
    if read_score_values:
        score_columns.append("score")
    score_frame = pd.read_parquet(S_SCORES, columns=score_columns)
    require(set(score_frame.arm.dropna().unique()) >= {"S"}, "S score arm missing")
    score_frame = score_frame.loc[score_frame.arm.eq("S") & score_frame.role.isin(["calibration", "evaluation"])].copy()
    score_frame["race_date"] = _canonical_date(score_frame.race_date, "S score race_date")
    require(score_frame.year.isin(YEARS).all(), "unexpected S provider vintage")
    require(not score_frame.duplicated(["year", "role", "api_record_id"]).any(), "duplicate S OOS role keys")
    score_rows: dict[str, Any] = {}
    for year in YEARS:
        score_rows[str(year)] = {}
        for role in ("calibration", "evaluation"):
            provided = score_frame.loc[score_frame.year.eq(year) & score_frame.role.eq(role)].copy()
            race_year = year - 1 if role == "calibration" else year
            target_mask = joined.year.eq(race_year)
            if role == "evaluation":
                target_mask &= joined.race_date.le(EXPECTED_EVAL_END)
            target = joined.loc[target_mask, list(SCORE_KEY_COLUMNS)].copy()
            expected_rows = target.merge(provided.loc[:, list(SCORE_KEY_COLUMNS)],
                                         on=list(SCORE_KEY_COLUMNS), how="outer", validate="one_to_one",
                                         indicator=True)
            require(len(provided) == len(target) and expected_rows._merge.eq("both").all(),
                    f"S {year}/{role} provider keys differ from target cohort")
            require((provided.race_date.str[:4].astype(int) == race_year).all(),
                    f"S {year}/{role} race-year provenance mismatch")
            if read_score_values:
                scores = pd.to_numeric(provided.score, errors="coerce").to_numpy(dtype=np.float64)
                require(np.isfinite(scores).all(), f"non-finite S {year}/{role} raw score")
            score_rows[str(year)][role] = {"rows": len(provided), "races": int(provided.race_id.nunique()),
                                           "date_min": str(provided.race_date.min()),
                                           "date_max": str(provided.race_date.max())}

    evaluation = joined.loc[joined.year.isin(YEARS) & joined.race_date.le(EXPECTED_EVAL_END)].copy()
    require((len(evaluation), evaluation.race_id.nunique(), evaluation.race_date.nunique()) ==
            (EXPECTED_COHORT["eval_runners"], EXPECTED_COHORT["eval_races"], EXPECTED_COHORT["eval_dates"]),
            "fixed evaluation cohort changed")
    eval_bottom3 = int((evaluation.finish_position >= evaluation.field_n - 2).sum())
    require(eval_bottom3 == EXPECTED_COHORT["eval_bottom3"], "evaluation Bottom3 label census changed")
    expected_eval_years = evaluation.groupby("year").race_id.nunique().to_dict()
    require({int(k): int(v) for k, v in expected_eval_years.items()} == YEAR_RACES,
            "annual evaluation race census changed")

    schedule = np.load(BOOTSTRAP, allow_pickle=False)
    receipt = read_json(BOOTSTRAP_RECEIPT)
    dates_sorted = sorted(evaluation.race_date.unique().tolist())
    require(schedule.shape == (BOOTSTRAP_DRAWS, EXPECTED_COHORT["eval_dates"]) and
            schedule.dtype == np.dtype("int32") and schedule.min() >= 0 and
            schedule.max() < len(dates_sorted), "frozen date bootstrap dimensions/index range changed")
    require(receipt.get("date_inventory_sha256") == EXPECTED_DATE_INVENTORY_SHA256 and
            receipt.get("schedule_shape") == [BOOTSTRAP_DRAWS, EXPECTED_COHORT["eval_dates"]] and
            receipt.get("schedule_sha256") == sha256_file(BOOTSTRAP), "frozen bootstrap receipt changed")

    fold_digest_payload = json.dumps(folds, sort_keys=True, separators=(",", ":")).encode("utf-8")
    structural = {
        "status": "PASS_STRUCTURAL_ONLY_NO_BOTTOM3_PROBABILITIES_OR_METRICS",
        "study": "jeju/research/20261023_bottom3_auxiliary_v1",
        **code_hashes(),
        "source_hashes": source_records,
        "cohort": {"rows": len(joined), "races": race_counts, "bottom3_label_count": bottom3_total,
                   "eval_rows": len(evaluation), "eval_races": int(evaluation.race_id.nunique()),
                   "eval_dates": int(evaluation.race_date.nunique()), "eval_bottom3_label_count": eval_bottom3,
                   "evaluation_year_races": {str(k): int(v) for k, v in expected_eval_years.items()},
                   "field_n_min": int(joined.field_n.min()), "field_n_max": int(joined.field_n.max())},
        "feature_contract": {"features": f1_keys, "categorical_columns": cat_columns,
                             "state_features": list(STATE_COLUMNS),
                             "vocabulary_by_evaluation_year": {
                                 str(year): vocab for year, vocab in vocab_by_year.items()},
                             "vocabulary_sha256_by_year": {
                                 str(year): hashlib.sha256(json.dumps(vocab_by_year[year], ensure_ascii=False,
                                     sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                                 for year in YEARS}},
        "annual_folds": folds, "annual_folds_canonical_sha256": hashlib.sha256(fold_digest_payload).hexdigest(),
        "s_oos_provider_roles": score_rows,
        "bootstrap": {"sha256": sha256_file(BOOTSTRAP), "receipt_sha256": sha256_file(BOOTSTRAP_RECEIPT),
                      "shape": list(schedule.shape), "dtype": str(schedule.dtype),
                      "date_inventory_sha256": EXPECTED_DATE_INVENTORY_SHA256},
        "guard": {"bottom3_model_fit": False, "temperature_optimization": False,
                  "bottom3_probabilities_computed": False, "outcome_performance_metrics_computed": False,
                  "database_opened": False, "source_inputs_copied": False},
    }
    return joined, structural, {"parameters": params, "vocab_by_year": vocab_by_year,
                               "feature_names": f1_keys, "categorical_columns": cat_columns,
                               "score_frame": score_frame if read_score_values else None,
                               "evaluation_dates": dates_sorted}


def build_source_preflight() -> dict[str, Any]:
    _frame, structural, _context = _load_frozen_inputs(read_score_values=False)
    structural["created_at_utc"] = datetime.now(timezone.utc).isoformat()
    return structural


def write_source_preflight() -> dict[str, Any]:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    require(not PREFLIGHT.exists(), "source_preflight exists; preserve the prior receipt before refresh")
    require(not (OUTPUTS / "execution_claim.json").exists(), "execution already claimed")
    require(sorted(p.name for p in OUTPUTS.iterdir()) == [], "outputs must be empty before preflight")
    report = build_source_preflight()
    _write_json_once(PREFLIGHT, report)
    require(_study_bytes() <= MAX_STUDY_BYTES, "study storage budget exceeded during preflight")
    return report


def _canonical_without_timestamp(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "created_at_utc"}


def _validate_approval() -> dict[str, Any]:
    require(PREFLIGHT.is_file(), "run source preflight before fit/evaluation")
    saved = read_json(PREFLIGHT)
    fresh = build_source_preflight()
    require(_canonical_without_timestamp(saved) == _canonical_without_timestamp(fresh),
            "fresh structural preflight differs from saved receipt")
    require(saved.get("status") == "PASS_STRUCTURAL_ONLY_NO_BOTTOM3_PROBABILITIES_OR_METRICS",
            "source preflight status is not PASS")
    require(APPROVAL.is_file(), "missing supervisor/EXECUTION_APPROVAL.json")
    approval = read_json(APPROVAL)
    require(approval.get("status") == "PASS" and approval.get("scope") == "fit_evaluate" and
            approval.get("run_count") == 1, "approval status/scope/run count mismatch")
    require(approval.get("study") == "jeju/research/20261023_bottom3_auxiliary_v1" and
            approval.get("candidate") == "BOTTOM3_AUXILIARY_B" and
            approval.get("fit_count") == 6 and approval.get("temperature_optimizations") == 6,
            "approval study/candidate/fit budget mismatch")
    hashes = {**code_hashes(), "source_preflight_sha256": sha256_file(PREFLIGHT)}
    for key, value in hashes.items():
        require(approval.get(key) == value, f"approval hash mismatch: {key}")
    source_hashes = {key: value["sha256"] for key, value in saved["source_hashes"].items()}
    require(approval.get("source_hashes") == source_hashes, "approval source hash map mismatch")
    require(not (OUTPUTS / "execution_claim.json").exists(), "execution already claimed; no retry")
    require(not MODELS.exists() or not any(MODELS.iterdir()), "model directory is not empty")
    require(sorted(p.name for p in OUTPUTS.iterdir()) == ["source_preflight.json"],
            "outputs must contain only source_preflight before the one run")
    require(_study_bytes() < MAX_STUDY_BYTES, "study storage budget exceeded before execution")
    return {"approval": approval, "approval_sha256": sha256_file(APPROVAL), "hashes": hashes,
            "source_hashes": source_hashes, "source_preflight_sha256": sha256_file(PREFLIGHT)}


def _bottom3_labels(ranks: Sequence[int], field_n: int) -> np.ndarray:
    raw_n = np.asarray(field_n)
    require(raw_n.ndim == 0, "field_n must be a scalar exact integer")
    numeric_n = float(raw_n)
    require(math.isfinite(numeric_n) and numeric_n == round(numeric_n),
            "field_n must be finite and exactly integral")
    field_n = int(numeric_n)
    raw = np.asarray(ranks)
    require(raw.ndim == 1 and len(raw) == field_n and field_n >= 3, "invalid rank vector for Bottom3 labels")
    numeric = raw.astype(np.float64)
    require(np.isfinite(numeric).all() and np.equal(numeric, np.rint(numeric)).all(),
            "rank values must be finite exact integers")
    integer = numeric.astype(np.int64)
    require(sorted(integer.tolist()) == list(range(1, field_n + 1)), "ranks must be exactly 1..N")
    labels = integer >= field_n - 2
    require(int(labels.sum()) == 3, "exactly three Bottom3 labels required")
    return labels


def bottom3_subset_distribution(utilities: Sequence[float], temperature: float) -> tuple[list[tuple[int, int, int]], np.ndarray, np.ndarray]:
    utility = np.asarray(utilities, dtype=np.float64)
    require(utility.ndim == 1 and len(utility) >= 3 and np.isfinite(utility).all(),
            "utilities must be finite and field size at least three")
    require(math.isfinite(float(temperature)) and temperature > 0.0, "temperature must be positive and finite")
    subsets = list(itertools.combinations(range(len(utility)), 3))
    logits = np.fromiter((sum(utility[list(subset)]) / temperature for subset in subsets),
                         dtype=np.float64, count=len(subsets))
    log_z = float(logsumexp(logits))
    probabilities = np.exp(logits - log_z)
    require(np.isfinite(probabilities).all() and np.all(probabilities >= 0.0),
            "invalid exact Bottom3 subset probabilities")
    require(abs(float(probabilities.sum()) - 1.0) <= 1e-12, "Bottom3 subset distribution does not sum to one")
    marginals = np.zeros(len(utility), dtype=np.float64)
    for subset, probability in zip(subsets, probabilities):
        marginals[list(subset)] += probability
    require(np.all(marginals >= -1e-12) and np.all(marginals <= 1.0 + 1e-12) and
            abs(float(marginals.sum()) - 3.0) <= 1e-10, "Bottom3 marginal identity failed")
    return subsets, probabilities, marginals


def bottom3_set_nll(utilities: Sequence[float], temperature: float, truth_indices: Sequence[int]) -> float:
    utility = np.asarray(utilities, dtype=np.float64)
    require(utility.ndim == 1 and len(utility) >= 3 and np.isfinite(utility).all(), "invalid utility vector")
    require(math.isfinite(float(temperature)) and temperature > 0.0, "invalid temperature")
    raw_truth = np.asarray(truth_indices)
    require(raw_truth.ndim == 1, "truth indices must be one-dimensional")
    numeric_truth = raw_truth.astype(np.float64)
    require(np.isfinite(numeric_truth).all() and np.equal(numeric_truth, np.rint(numeric_truth)).all(),
            "truth indices must be finite exact integers")
    truth = tuple(sorted(int(x) for x in numeric_truth))
    require(len(truth) == 3 and len(set(truth)) == 3 and min(truth) >= 0 and max(truth) < len(utility),
            "truth must identify exactly three unique runners")
    logits = np.fromiter((sum(utility[list(subset)]) / temperature
                          for subset in itertools.combinations(range(len(utility)), 3)),
                         dtype=np.float64)
    log_z = float(logsumexp(logits))
    true_logit = float(sum(utility[list(truth)]) / temperature)
    return max(0.0, log_z - true_logit)


def choose_bottom3(utilities: Sequence[float], horse_numbers: Sequence[int],
                   tolerance: float = SELECTION_TOLERANCE) -> tuple[int, int, int]:
    utility = np.asarray(utilities, dtype=np.float64)
    numbers = np.asarray(horse_numbers)
    require(utility.ndim == 1 and numbers.ndim == 1 and len(utility) == len(numbers) and len(utility) >= 3,
            "utility and horse number vectors must align and have N>=3")
    require(np.isfinite(utility).all() and np.isfinite(numbers.astype(np.float64)).all() and
            np.equal(numbers.astype(np.float64), np.rint(numbers.astype(np.float64))).all(),
            "selection values must be finite and horse numbers exact integers")
    require(len(set(numbers.astype(np.int64).tolist())) == len(numbers), "horse numbers must be unique")
    require(math.isfinite(float(tolerance)) and tolerance >= 0.0, "tie tolerance must be finite and nonnegative")
    remaining = set(range(len(utility)))
    selected: list[int] = []
    for _ in range(3):
        maximum = max(float(utility[index]) for index in remaining)
        eligible = [index for index in remaining if float(utility[index]) >= maximum - tolerance]
        chosen = min(eligible, key=lambda index: int(numbers[index]))
        selected.append(chosen)
        remaining.remove(chosen)
    return tuple(selected)


def _record_arrays(records: Sequence[Mapping[str, Any]]) -> list[tuple[np.ndarray, tuple[int, int, int]]]:
    output: list[tuple[np.ndarray, tuple[int, int, int]]] = []
    require(len(records) > 0, "temperature fit requires calibration races")
    for record in records:
        utility = np.asarray(record["utilities"], dtype=np.float64)
        raw_truth = np.asarray(record["truth_indices"])
        require(raw_truth.ndim == 1, "calibration truth indices must be one-dimensional")
        numeric_truth = raw_truth.astype(np.float64)
        require(np.isfinite(numeric_truth).all() and np.equal(numeric_truth, np.rint(numeric_truth)).all(),
                "calibration truth indices must be finite exact integers")
        truth = tuple(sorted(int(x) for x in numeric_truth))
        require(utility.ndim == 1 and len(utility) >= 3 and np.isfinite(utility).all() and len(truth) == 3,
                "invalid synthetic/calibration race record")
        output.append((utility, truth))
    return output


def fit_bottom3_temperature(records: Sequence[Mapping[str, Any]], *, count_call: bool = False) -> dict[str, Any]:
    global TEMPERATURE_FIT_CALLS
    arrays = _record_arrays(records)

    def objective(temp: float) -> float:
        losses = [bottom3_set_nll(utility, float(temp), truth) for utility, truth in arrays]
        return float(np.mean(losses))

    result = minimize_scalar(objective, bounds=TEMPERATURE_BOUNDS, method="bounded",
                             options={"xatol": TEMPERATURE_XTOL, "maxiter": 500})
    require(bool(result.success) and math.isfinite(float(result.x)), "bounded Bottom3 temperature optimizer failed")
    candidates = [(TEMPERATURE_BOUNDS[0], objective(TEMPERATURE_BOUNDS[0])),
                  (float(result.x), objective(float(result.x))),
                  (TEMPERATURE_BOUNDS[1], objective(TEMPERATURE_BOUNDS[1]))]
    temperature, loss = min(candidates, key=lambda pair: (pair[1], pair[0]))
    require(TEMPERATURE_BOUNDS[0] <= temperature <= TEMPERATURE_BOUNDS[1] and math.isfinite(loss),
            "temperature optimum outside contract")
    if count_call:
        TEMPERATURE_FIT_CALLS += 1
    return {"temperature": float(temperature), "objective": "mean race-equal unordered Bottom3 set NLL",
            "nll": float(loss), "races": len(arrays), "bounds": list(TEMPERATURE_BOUNDS),
            "method": "scipy.optimize.minimize_scalar(method=bounded)", "xatol": TEMPERATURE_XTOL,
            "optimizer_success": bool(result.success), "optimizer_x": float(result.x),
            "optimizer_nfev": int(result.nfev), "endpoint_objectives": {
                str(TEMPERATURE_BOUNDS[0]): float(candidates[0][1]),
                str(TEMPERATURE_BOUNDS[1]): float(candidates[2][1])},
            "selected_candidate": "lower_endpoint" if temperature == TEMPERATURE_BOUNDS[0] else
                                 "upper_endpoint" if temperature == TEMPERATURE_BOUNDS[1] else "bounded_optimum"}


def _frame_with_categories(frame: pd.DataFrame, feature_names: Sequence[str],
                           vocabulary: Mapping[str, Sequence[str]]) -> pd.DataFrame:
    transformed = frame.loc[:, list(feature_names)].copy()
    for column, levels in vocabulary.items():
        if column in transformed.columns:
            transformed[column] = pd.Categorical(transformed[column].astype("string"), categories=list(levels))
    return transformed


def _fit_b_year(frame: pd.DataFrame, *, year: int, feature_names: Sequence[str],
                vocabulary: Mapping[str, Sequence[str]]) -> tuple[lgb.Booster, dict[str, Any], pd.DataFrame, np.ndarray, pd.DataFrame, np.ndarray]:
    global LIGHTGBM_TRAIN_CALLS
    years = frame.year.to_numpy(dtype=np.int64)
    train_mask = (years >= 2017) & (years <= year - 3)
    valid_mask = years == year - 2
    refit_mask = (years >= 2017) & (years <= year - 2)
    cal_mask = years == year - 1
    eval_mask = (years == year) & (frame.race_date.to_numpy() <= EXPECTED_EVAL_END)
    require(all(mask.any() for mask in (train_mask, valid_mask, refit_mask, cal_mask, eval_mask)),
            f"empty annual B split in {year}")
    for mask, expected_years, role in (
        (train_mask, set(range(2017, year - 2)), "initial_train"),
        (valid_mask, {year - 2}, "early_stop"),
        (refit_mask, set(range(2017, year - 1)), "refit"),
        (cal_mask, {year - 1}, "calibration"),
        (eval_mask, {year}, "evaluation"),
    ):
        require(set(years[mask].tolist()) == expected_years, f"{role} year boundary mismatch in {year}")

    x = _frame_with_categories(frame, feature_names, vocabulary)
    field_sizes = pd.to_numeric(frame.field_n, errors="coerce").to_numpy(dtype=np.float64)
    ranks = pd.to_numeric(frame.finish_position, errors="coerce").to_numpy(dtype=np.float64)
    require(np.isfinite(field_sizes).all() and np.equal(field_sizes, np.rint(field_sizes)).all() and
            np.isfinite(ranks).all() and np.equal(ranks, np.rint(ranks)).all(),
            "B training roster fields must be finite exact integers before casting")
    field_sizes = field_sizes.astype(np.int64)
    ranks = ranks.astype(np.int64)
    # Build labels row-wise after validating each whole race.
    y = np.zeros(len(frame), dtype=np.int8)
    for _, group in frame.groupby("race_id", sort=False):
        ix = group.index.to_numpy()
        n = int(group.field_n.iloc[0])
        y[ix] = _bottom3_labels(group.finish_position.to_numpy(dtype=np.int64), n).astype(np.int8)
    weights = 1.0 / field_sizes
    require(np.isfinite(weights).all() and (weights > 0.0).all(), "invalid 1/N race-equal weights")
    categorical = [column for column in CAT_COLUMNS if column in feature_names]

    def dataset(mask: np.ndarray) -> lgb.Dataset:
        return lgb.Dataset(x.loc[mask], label=y[mask], weight=weights[mask],
                           categorical_feature=categorical, feature_name=list(feature_names), free_raw_data=False)

    initial_train = lgb.train(LGBM_PARAMS, dataset(train_mask), num_boost_round=800,
                              valid_sets=[dataset(valid_mask)], valid_names=["early_stop"],
                              callbacks=[lgb.early_stopping(25, verbose=False)])
    LIGHTGBM_TRAIN_CALLS += 1
    best_iteration = int(initial_train.best_iteration)
    require(0 < best_iteration <= 800, f"invalid early-stopping iteration for B/{year}")
    model = lgb.train(LGBM_PARAMS, dataset(refit_mask), num_boost_round=best_iteration)
    LIGHTGBM_TRAIN_CALLS += 1
    cal_frame = frame.loc[cal_mask].copy().sort_values(["race_date", "race_id", "horse_number"], kind="mergesort")
    eval_frame = frame.loc[eval_mask].copy().sort_values(["race_date", "race_id", "horse_number"], kind="mergesort")
    cal_scores = np.asarray(model.predict(x.loc[cal_mask], raw_score=True, num_threads=4), dtype=np.float64)
    eval_scores = np.asarray(model.predict(x.loc[eval_mask], raw_score=True, num_threads=4), dtype=np.float64)
    require(np.isfinite(cal_scores).all() and np.isfinite(eval_scores).all(), f"B/{year} scores are not finite")
    # Preserve the model frame order used by prediction arrays.
    cal_frame = frame.loc[cal_mask].copy().reset_index(drop=True)
    eval_frame = frame.loc[eval_mask].copy().reset_index(drop=True)
    meta = {
        "arm": "B", "target": "1[finish_position >= field_n - 2]", "evaluation_year": year,
        "feature_names": list(feature_names), "feature_count": len(feature_names),
        "categorical_columns": list(categorical), "categorical_vocabulary": {k: list(v) for k, v in vocabulary.items()},
        "parameters": dict(LGBM_PARAMS), "seed": 20261008, "max_rounds": 800,
        "early_stopping_rounds": 25, "best_iteration": best_iteration,
        "initial_train_min": str(frame.loc[train_mask, "race_date"].min()),
        "initial_train_max": str(frame.loc[train_mask, "race_date"].max()),
        "early_stop_min": str(frame.loc[valid_mask, "race_date"].min()),
        "early_stop_max": str(frame.loc[valid_mask, "race_date"].max()),
        "refit_min": str(frame.loc[refit_mask, "race_date"].min()),
        "refit_max": str(frame.loc[refit_mask, "race_date"].max()),
        "calibration_min": str(frame.loc[cal_mask, "race_date"].min()),
        "calibration_max": str(frame.loc[cal_mask, "race_date"].max()),
        "evaluation_min": str(frame.loc[eval_mask, "race_date"].min()),
        "evaluation_max": str(frame.loc[eval_mask, "race_date"].max()),
        "split_counts": {name: {"rows": int(mask.sum()), "races": int(frame.loc[mask, "race_id"].nunique())}
                         for name, mask in (("initial_train", train_mask), ("early_stop", valid_mask),
                                            ("refit", refit_mask), ("calibration", cal_mask),
                                            ("evaluation", eval_mask))},
        "race_weighting": "each runner weight 1/field_n; each race total weight 1",
        "lightgbm_train_calls": 2,
    }
    return model, meta, cal_frame, cal_scores, eval_frame, eval_scores


def _race_records(frame: pd.DataFrame, utilities: Sequence[float]) -> list[dict[str, Any]]:
    values = np.asarray(utilities, dtype=np.float64)
    require(len(frame) == len(values) and np.isfinite(values).all(), "raw utility vector does not match frame")
    working = frame[["race_id", "race_date", "year", "field_n", "horse_number", "finish_position"]].copy()
    working["utility"] = values
    records: list[dict[str, Any]] = []
    for race_id, group in working.groupby("race_id", sort=True):
        group = group.sort_values("horse_number", kind="mergesort")
        raw_field_sizes = pd.to_numeric(group.field_n, errors="coerce").to_numpy(dtype=np.float64)
        raw_horse_numbers = pd.to_numeric(group.horse_number, errors="coerce").to_numpy(dtype=np.float64)
        require(np.isfinite(raw_field_sizes).all() and np.equal(raw_field_sizes, np.rint(raw_field_sizes)).all() and
                np.all(raw_field_sizes == raw_field_sizes[0]), "race field size must be a constant exact integer")
        require(np.isfinite(raw_horse_numbers).all() and
                np.equal(raw_horse_numbers, np.rint(raw_horse_numbers)).all() and
                len(np.unique(raw_horse_numbers)) == len(group), "race horse numbers must be unique exact integers")
        n = int(raw_field_sizes[0])
        labels = _bottom3_labels(group.finish_position.to_numpy(), n)
        truth = tuple(np.flatnonzero(labels).tolist())
        records.append({"race_id": str(race_id), "race_date": str(group.race_date.iloc[0]),
                        "year": int(group.year.iloc[0]), "n": n,
                        "horse_numbers": raw_horse_numbers.astype(np.int64),
                        "utilities": group.utility.to_numpy(dtype=np.float64),
                        "ranks": pd.to_numeric(group.finish_position, errors="coerce").to_numpy(dtype=np.float64),
                        "truth_indices": truth})
    return records


def _bin_indices(probabilities: np.ndarray) -> np.ndarray:
    raw = np.searchsorted(BIN_EDGES, probabilities, side="right") - 1
    return np.clip(raw, 0, len(BIN_EDGES) - 2).astype(np.int64)


def _evaluate_arm_race(record: Mapping[str, Any], *, arm: str, temperature: float) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, np.ndarray]]:
    utilities = np.asarray(record["utilities"], dtype=np.float64)
    raw_ranks = np.asarray(record["ranks"])
    numeric_ranks = raw_ranks.astype(np.float64)
    require(np.isfinite(numeric_ranks).all() and np.equal(numeric_ranks, np.rint(numeric_ranks)).all(),
            "evaluation ranks must be finite exact integers before casting")
    ranks = numeric_ranks.astype(np.int64)
    numbers_raw = np.asarray(record["horse_numbers"])
    numeric_numbers = numbers_raw.astype(np.float64)
    require(np.isfinite(numeric_numbers).all() and np.equal(numeric_numbers, np.rint(numeric_numbers)).all(),
            "evaluation horse numbers must be finite exact integers before casting")
    numbers = numeric_numbers.astype(np.int64)
    raw_n = np.asarray(record["n"])
    require(raw_n.ndim == 0 and math.isfinite(float(raw_n)) and float(raw_n) == round(float(raw_n)),
            "evaluation field size must be a finite exact integer before casting")
    n = int(raw_n)
    labels = _bottom3_labels(ranks, n)
    truth_indices = tuple(np.flatnonzero(labels).tolist())
    subsets, subset_probabilities, marginals = bottom3_subset_distribution(utilities, temperature)
    truth = tuple(sorted(truth_indices))
    try:
        truth_ix = subsets.index(truth)
    except ValueError as exc:
        raise RuntimeError("true Bottom3 set missing from complete subset support") from exc
    p_true = float(subset_probabilities[truth_ix])
    set_nll = -math.log(max(EPS, p_true))
    set_brier = float(np.square(subset_probabilities).sum() - 2.0 * p_true + 1.0)
    clipped = np.clip(marginals, EPS, 1.0 - EPS)
    binary_nll_per_runner = -(labels * np.log(clipped) + (1 - labels) * np.log1p(-clipped))
    binary_brier_per_runner = np.square(marginals - labels.astype(np.float64))
    selected_indices = choose_bottom3(utilities, numbers)
    selected_numbers = [int(numbers[ix]) for ix in selected_indices]
    actual_numbers = sorted(int(numbers[ix]) for ix in truth_indices)
    selected_set = set(selected_indices)
    captured = int(len(selected_set.intersection(truth_indices)))
    top3_indices = set(np.flatnonzero(ranks <= 3).tolist())
    excluded_top3 = int(len(selected_set.intersection(top3_indices)))
    any_top3_excluded = excluded_top3 > 0
    winner_excluded = int(1 in ranks[list(selected_indices)])
    metrics = {
        "race_id": str(record["race_id"]), "race_date": str(record["race_date"]),
        "year": int(record["year"]), "field_n": n, "arm": arm,
        "bottom3_set_nll": float(set_nll), "bottom3_set_brier_sum": float(set_brier),
        "runner_binary_logloss_mean": float(binary_nll_per_runner.mean()),
        "runner_binary_brier_mean": float(binary_brier_per_runner.mean()),
        "true_bottom3_set_probability": p_true,
        "selected_bottom3_set_probability": float(subset_probabilities[subsets.index(tuple(sorted(selected_indices)))]),
        "actual_bottom3_horse_numbers": actual_numbers,
        "selected_bottom3_horse_numbers": selected_numbers,
        "bottom3_captured_count": captured,
        "bottom3_precision_at_3": captured / 3.0, "bottom3_recall_at_3": captured / 3.0,
        "exact_bottom3_set_match": captured == 3,
        "top3_excluded_count": excluded_top3, "any_top3_excluded": any_top3_excluded,
        "all_top3_retained": not any_top3_excluded, "winner_excluded": bool(winner_excluded),
    }
    runner_rows = [{"arm": arm, "year": int(record["year"]), "race_id": str(record["race_id"]),
                    "race_date": str(record["race_date"]), "horse_number": int(numbers[i]),
                    "finish_position": int(ranks[i]), "p_bottom3": float(marginals[i])}
                   for i in range(n)]
    event_data = {"set_probabilities": subset_probabilities,
                  "true_subset_index": np.asarray([truth_ix], dtype=np.int64),
                  "runner_probabilities": marginals, "runner_labels": labels.astype(np.int8)}
    return metrics, runner_rows, event_data


def _new_reliability_accumulator() -> dict[tuple[str, str, str, int], list[float]]:
    return defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])


def _accumulate_reliability(accumulator: dict[tuple[str, str, str, int], list[float]], *,
                            arm: str, year: int, set_probabilities: np.ndarray,
                            true_subset_index: int, runner_probabilities: np.ndarray,
                            runner_labels: np.ndarray) -> None:
    """Accumulate a race into fixed bins without retaining its full subset vector."""
    set_p = np.asarray(set_probabilities, dtype=np.float64)
    require(set_p.ndim == 1 and len(set_p) > 0 and np.isfinite(set_p).all(),
            "invalid per-race subset probabilities for reliability")
    require(0 <= int(true_subset_index) < len(set_p), "true Bottom3 set index outside support")
    set_y = np.zeros(len(set_p), dtype=np.float64)
    set_y[int(true_subset_index)] = 1.0
    runner_p = np.asarray(runner_probabilities, dtype=np.float64)
    runner_y = np.asarray(runner_labels, dtype=np.float64)
    require(runner_p.ndim == 1 and len(runner_p) == len(runner_y) and
            np.isfinite(runner_p).all() and np.isfinite(runner_y).all(),
            "invalid runner marginal inputs for reliability")
    for period in ("ALL", str(int(year))):
        for kind, probabilities, labels in (("set", set_p, set_y), ("runner", runner_p, runner_y)):
            bins = _bin_indices(probabilities)
            event_brier = np.square(probabilities - labels)
            for bin_index in range(len(BIN_EDGES) - 1):
                selected = bins == bin_index
                if not selected.any():
                    continue
                cell = accumulator[(arm, kind, period, bin_index)]
                cell[0] += float(selected.sum())
                cell[1] += float(probabilities[selected].sum())
                cell[2] += float(labels[selected].sum())
                cell[3] += float(event_brier[selected].sum())


def _reliability_frame(accumulator: Mapping[tuple[str, str, str, int], Sequence[float]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for arm in ("L", "B"):
        for kind in ("set", "runner"):
            for period in ("ALL", *(str(year) for year in YEARS)):
                for ix, values in enumerate(BIN_EDGES[:-1]):
                    count, sum_p, sum_y, sum_brier = accumulator.get((arm, kind, period, ix),
                                                                     [0.0, 0.0, 0.0, 0.0])
                    rows.append({"arm": arm, "probability_kind": kind, "period": period,
                                 "bin_index": ix, "bin_lower": float(BIN_EDGES[ix]),
                                 "bin_upper": float(BIN_EDGES[ix + 1]),
                                 "upper_inclusive": bool(ix == len(BIN_EDGES) - 2),
                                 "event_count": int(count),
                                 "mean_probability": float(sum_p / count) if count else np.nan,
                                 "observed_rate": float(sum_y / count) if count else np.nan,
                                 "mean_event_brier": float(sum_brier / count) if count else np.nan,
                                 "weighting": "pooled event count"})
    return pd.DataFrame(rows)


def _paired_date_bootstrap(race_metrics: pd.DataFrame, evaluation_dates: Sequence[str],
                           schedule: np.ndarray) -> tuple[pd.DataFrame, dict[str, Any]]:
    metric_names = ["bottom3_set_nll", "bottom3_set_brier_sum", "runner_binary_logloss_mean",
                    "runner_binary_brier_mean", "bottom3_captured_count", "bottom3_precision_at_3",
                    "bottom3_recall_at_3", "exact_bottom3_set_match", "top3_excluded_count",
                    "any_top3_excluded", "all_top3_retained", "winner_excluded"]
    key_cols = ["race_id", "race_date", "year"]
    wide_frames: dict[str, pd.DataFrame] = {}
    for arm in ("L", "B"):
        part = race_metrics.loc[race_metrics.arm.eq(arm), [*key_cols, *metric_names]].copy()
        require(not part.duplicated(key_cols).any(), f"duplicate race metric keys for {arm}")
        wide_frames[arm] = part.set_index(key_cols).sort_index()
    require(wide_frames["L"].index.equals(wide_frames["B"].index), "L/B race metric keys differ")
    left, right = wide_frames["L"], wide_frames["B"]
    deltas = {metric: (pd.to_numeric(right[metric]).astype(np.float64).to_numpy() -
                       pd.to_numeric(left[metric]).astype(np.float64).to_numpy())
              for metric in metric_names}
    dates_for_races = np.asarray([key[1] for key in left.index.tolist()], dtype=object)
    date_to_index = {date: index for index, date in enumerate(evaluation_dates)}
    race_date_indices = np.asarray([date_to_index[date] for date in dates_for_races], dtype=np.int64)
    n_dates = len(evaluation_dates)
    date_race_counts = np.bincount(race_date_indices, minlength=n_dates).astype(np.float64)
    require(np.all(date_race_counts > 0.0) and len(dates_for_races) == EXPECTED_COHORT["eval_races"],
            "bootstrap date/race inventory mismatch")
    draw_date_counts = np.zeros((schedule.shape[0], n_dates), dtype=np.float64)
    rows_ix = np.arange(schedule.shape[0])[:, None]
    np.add.at(draw_date_counts, (rows_ix, schedule.astype(np.int64)), 1.0)
    denominators = draw_date_counts @ date_race_counts
    require((denominators > 0.0).all(), "bootstrap draw has no evaluation races")
    bootstrap_rows: list[dict[str, Any]] = []
    summaries: dict[str, Any] = {}
    for metric, difference in deltas.items():
        date_sums = np.bincount(race_date_indices, weights=difference, minlength=n_dates)
        draws = (draw_date_counts @ date_sums) / denominators
        point = float(difference.mean())
        lower, upper = np.quantile(draws, [0.025, 0.975], method="linear")
        summaries[metric] = {"point_difference_B_minus_L": point,
                             "bootstrap_ci95": [float(lower), float(upper)],
                             "races": int(len(difference))}
        bootstrap_rows.extend({"draw": int(index), "metric": metric, "difference_B_minus_L": float(value)}
                              for index, value in enumerate(draws))
    return pd.DataFrame(bootstrap_rows), summaries


def _summaries(race_metrics: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    value_cols = ["bottom3_set_nll", "bottom3_set_brier_sum", "runner_binary_logloss_mean",
                  "runner_binary_brier_mean", "bottom3_captured_count", "bottom3_precision_at_3",
                  "bottom3_recall_at_3", "exact_bottom3_set_match", "top3_excluded_count",
                  "any_top3_excluded", "all_top3_retained", "winner_excluded"]
    period_rows = []
    for arm in ("L", "B"):
        for period, selector in [("ALL", pd.Series(True, index=race_metrics.index)),
                                 *((str(year), race_metrics.year.eq(year)) for year in YEARS)]:
            part = race_metrics.loc[race_metrics.arm.eq(arm) & selector]
            require(len(part) > 0, f"missing race metrics for {arm}/{period}")
            row: dict[str, Any] = {"arm": arm, "period": period, "races": len(part)}
            row.update({col: float(part[col].astype(float).mean()) for col in value_cols})
            period_rows.append(row)
    summary_frame = pd.DataFrame(period_rows)
    overall = summary_frame.loc[summary_frame.period.eq("ALL")].set_index("arm")
    point_differences = {col: float(overall.loc["B", col] - overall.loc["L", col]) for col in value_cols}
    return {"period_summary": summary_frame.to_dict("records"), "point_differences_B_minus_L": point_differences}, summary_frame


def _build_calibration_records(frame: pd.DataFrame, utilities: np.ndarray) -> list[dict[str, Any]]:
    return _race_records(frame, utilities)


def _selected_score_source(score_frame: pd.DataFrame, year: int, role: str,
                           target: pd.DataFrame) -> pd.DataFrame:
    source = score_frame.loc[score_frame.arm.eq("S") & score_frame.year.eq(year) &
                             score_frame.role.eq(role)].copy()
    actual_year = year - 1 if role == "calibration" else year
    expected = target.loc[target.year.eq(actual_year)].copy()
    if role == "evaluation":
        expected = expected.loc[expected.race_date.le(EXPECTED_EVAL_END)]
    # Drop provider-year/role metadata before joining; the target frame's year is
    # the race year and must remain unambiguous in calibration/evaluation records.
    joined = expected.merge(source[[*SCORE_KEY_COLUMNS, "score"]], on=list(SCORE_KEY_COLUMNS),
                            how="outer", validate="one_to_one", indicator=True)
    require(len(source) == len(expected) and joined._merge.eq("both").all(),
            f"S raw scores do not exactly join {year}/{role} target keys")
    return joined.drop(columns="_merge").sort_values(["race_date", "race_id", "horse_number"],
                                                       kind="mergesort").reset_index(drop=True)


def _output_candidate_scores(year: int, role: str, frame: pd.DataFrame,
                             raw_scores: Sequence[float]) -> list[dict[str, Any]]:
    values = np.asarray(raw_scores, dtype=np.float64)
    require(len(values) == len(frame) and np.isfinite(values).all(), "B raw score coverage invalid")
    result = []
    for row, score in zip(frame.itertuples(index=False), values):
        result.append({"provider_year": int(year), "role": role, "api_record_id": int(row.api_record_id),
                       "race_id": str(row.race_id), "race_date": str(row.race_date),
                       "race_year": int(row.year), "horse_number": int(row.horse_number),
                       "field_n": int(row.field_n), "finish_position": int(row.finish_position),
                       "score": float(score)})
    return result


def _period_value_summary(race_metrics: pd.DataFrame, group_column: str) -> list[dict[str, Any]]:
    metrics = ["bottom3_set_nll", "bottom3_set_brier_sum", "runner_binary_logloss_mean",
               "runner_binary_brier_mean", "bottom3_captured_count", "any_top3_excluded", "winner_excluded"]
    result = []
    for (arm, period), group in race_metrics.groupby(["arm", group_column], sort=True):
        row = {"arm": str(arm), group_column: int(period), "races": int(group.race_id.nunique())}
        row.update({metric: float(group[metric].astype(float).mean()) for metric in metrics})
        result.append(row)
    return result


def run_approved_once() -> dict[str, Any]:
    global LIGHTGBM_TRAIN_CALLS, TEMPERATURE_FIT_CALLS
    authorization = _validate_approval()
    started_at = datetime.now(timezone.utc).isoformat()
    claim_path = OUTPUTS / "execution_claim.json"
    _write_json_once(claim_path, {"status": "RUN_CLAIMED_NO_RETRY", "scope": "fit_evaluate",
                                  "started_at_utc": started_at, "run_count": 1,
                                  "approval_sha256": authorization["approval_sha256"],
                                  "code_bundle_sha256": authorization["hashes"]["code_bundle_sha256"]})
    print(json.dumps({"phase": "fit_evaluate_started", "started_at_utc": started_at,
                      "approval_sha256": authorization["approval_sha256"]}), flush=True)
    start_clock = time.monotonic()

    # This second read is permitted only after the exclusive execution claim and valid approval.
    frame, _structural, context = _load_frozen_inputs(read_score_values=True)
    params = context["parameters"]
    feature_names = context["feature_names"]
    vocab_by_year = context["vocab_by_year"]
    score_frame = context["score_frame"]
    require(isinstance(score_frame, pd.DataFrame) and np.isfinite(score_frame.score.to_numpy(dtype=np.float64)).all(),
            "S score source contains non-finite values")
    evaluation_dates = context["evaluation_dates"]

    model_metadata: dict[str, dict[str, Any]] = {}
    B_scores: dict[tuple[int, str], tuple[pd.DataFrame, np.ndarray]] = {}
    candidate_score_rows: list[dict[str, Any]] = []
    models: dict[int, lgb.Booster] = {}
    for year in YEARS:
        model, meta, cal_frame, cal_scores, eval_frame, eval_scores = _fit_b_year(
            frame, year=year, feature_names=feature_names, vocabulary=vocab_by_year[year])
        model_path = _ensure_experiment_path(MODELS / f"B_{year}.txt")
        require(not model_path.exists(), f"refusing to overwrite model: {model_path.name}")
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model_bytes = model.model_to_string(num_iteration=model.current_iteration()).encode("utf-8")
        with model_path.open("xb") as stream:
            stream.write(model_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        meta["model_path"] = model_path.relative_to(EXPERIMENT).as_posix()
        meta["model_sha256"] = sha256_file(model_path)
        model_metadata[str(year)] = meta
        models[year] = model
        B_scores[(year, "calibration")] = (cal_frame, cal_scores)
        B_scores[(year, "evaluation")] = (eval_frame, eval_scores)
        candidate_score_rows.extend(_output_candidate_scores(year, "calibration", cal_frame, cal_scores))
        candidate_score_rows.extend(_output_candidate_scores(year, "evaluation", eval_frame, eval_scores))
        print(json.dumps({"phase": "B_annual_model_complete", "year": year,
                          "best_iteration": meta["best_iteration"], "train_calls": LIGHTGBM_TRAIN_CALLS,
                          "elapsed_seconds": round(time.monotonic() - start_clock, 2)}), flush=True)

    temperatures: dict[str, dict[str, Any]] = {"L": {}, "B": {}}
    for year in YEARS:
        s_cal = _selected_score_source(score_frame, year, "calibration", frame)
        l_records = _build_calibration_records(s_cal, -s_cal.score.to_numpy(dtype=np.float64))
        temperatures["L"][str(year)] = fit_bottom3_temperature(l_records, count_call=True)
        b_cal_frame, b_cal_scores = B_scores[(year, "calibration")]
        b_records = _build_calibration_records(b_cal_frame, b_cal_scores)
        temperatures["B"][str(year)] = fit_bottom3_temperature(b_records, count_call=True)
        print(json.dumps({"phase": "annual_temperature_complete", "year": year,
                          "L": temperatures["L"][str(year)]["temperature"],
                          "B": temperatures["B"][str(year)]["temperature"],
                          "temperature_calls": TEMPERATURE_FIT_CALLS,
                          "elapsed_seconds": round(time.monotonic() - start_clock, 2)}), flush=True)

    evaluation_records: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for year in YEARS:
        s_eval = _selected_score_source(score_frame, year, "evaluation", frame)
        l_frame = s_eval.copy()
        l_frame["utility"] = -l_frame.score.to_numpy(dtype=np.float64)
        evaluation_records[(year, "L")] = _race_records(l_frame, l_frame.utility.to_numpy(dtype=np.float64))
        b_frame, b_eval_scores = B_scores[(year, "evaluation")]
        evaluation_records[(year, "B")] = _race_records(b_frame, b_eval_scores)

    race_metric_rows: list[dict[str, Any]] = []
    runner_rows: list[dict[str, Any]] = []
    reliability_accumulator = _new_reliability_accumulator()
    for year in YEARS:
        for arm in ("L", "B"):
            temp = float(temperatures[arm][str(year)]["temperature"])
            for record in evaluation_records[(year, arm)]:
                metrics, runners, event_data = _evaluate_arm_race(record, arm=arm, temperature=temp)
                race_metric_rows.append(metrics)
                runner_rows.extend(runners)
                _accumulate_reliability(
                    reliability_accumulator, arm=arm, year=year,
                    set_probabilities=event_data["set_probabilities"],
                    true_subset_index=int(event_data["true_subset_index"][0]),
                    runner_probabilities=event_data["runner_probabilities"],
                    runner_labels=event_data["runner_labels"])
    race_metrics = pd.DataFrame(race_metric_rows)
    require(len(race_metrics) == 2 * EXPECTED_COHORT["eval_races"] and
            set(race_metrics.arm.unique()) == {"L", "B"}, "evaluation race metric count/arms changed")
    runner_probabilities = pd.DataFrame(runner_rows)
    require(len(runner_probabilities) == 2 * EXPECTED_COHORT["eval_runners"] and
            not runner_probabilities.duplicated(["arm", "race_id", "horse_number"]).any(),
            "runner probability coverage or key uniqueness failed")
    reliability = _reliability_frame(reliability_accumulator)
    summary_values, summary_frame = _summaries(race_metrics)
    bootstrap_schedule = np.load(BOOTSTRAP, allow_pickle=False)
    bootstrap_draws, bootstrap_summary = _paired_date_bootstrap(race_metrics, evaluation_dates, bootstrap_schedule)
    overall_differences = summary_values["point_differences_B_minus_L"]
    comparison = bootstrap_summary
    prediction_gate = bool(
        comparison["bottom3_set_nll"]["bootstrap_ci95"][1] < 0.0 and
        overall_differences["bottom3_set_brier_sum"] <= 0.0 and
        overall_differences["runner_binary_logloss_mean"] <= 0.0 and
        overall_differences["runner_binary_brier_mean"] <= 0.0)
    exclusion_gate = bool(prediction_gate and overall_differences["any_top3_excluded"] <= 0.0 and
                          overall_differences["winner_excluded"] <= 0.0)
    all_summary = summary_frame.to_dict("records")
    by_year = _period_value_summary(race_metrics, "year")
    by_field = _period_value_summary(race_metrics, "field_n")
    source_summary = {key: value for key, value in authorization["source_hashes"].items()}
    report = {
        "status": "COMPLETED_RESEARCH_ONLY", "study": "jeju/research/20261023_bottom3_auxiliary_v1",
        "candidate": "B: same S 40 inputs, binary Bottom3 target; comparison L: negative saved S raw score",
        "execution_completed": True, "prediction_research_candidate_gate_pass": prediction_gate,
        "exclusion_auxiliary_candidate_gate_pass": exclusion_gate,
        "fit_count": LIGHTGBM_TRAIN_CALLS, "temperature_optimization_count": TEMPERATURE_FIT_CALLS,
        "cohort": {"cohort_rows": EXPECTED_COHORT["runners"], "cohort_races": EXPECTED_COHORT["races"],
                   "cohort_bottom3_labels": 15_618, "eval_runners_per_arm": EXPECTED_COHORT["eval_runners"],
                   "eval_races": EXPECTED_COHORT["eval_races"], "eval_dates": EXPECTED_COHORT["eval_dates"],
                   "eval_bottom3_labels_per_arm": EXPECTED_COHORT["eval_bottom3"],
                   "year_races": {str(k): v for k, v in YEAR_RACES.items()}},
        "arm_point_differences_B_minus_L": overall_differences,
        "paired_date_bootstrap": bootstrap_summary,
        "period_summary": all_summary, "year_summary": by_year, "field_size_summary": by_field,
        "gates": {"prediction_research_candidate": {
                      "bottom3_set_nll_bootstrap_upper_lt_0": comparison["bottom3_set_nll"]["bootstrap_ci95"][1] < 0.0,
                      "bottom3_set_brier_point_le_0": overall_differences["bottom3_set_brier_sum"] <= 0.0,
                      "runner_binary_logloss_point_le_0": overall_differences["runner_binary_logloss_mean"] <= 0.0,
                      "runner_binary_brier_point_le_0": overall_differences["runner_binary_brier_mean"] <= 0.0,
                      "passed": prediction_gate},
                  "exclusion_auxiliary_candidate": {
                      "requires_prediction_gate": prediction_gate,
                      "any_top3_excluded_rate_point_le_0": overall_differences["any_top3_excluded"] <= 0.0,
                      "winner_excluded_rate_point_le_0": overall_differences["winner_excluded"] <= 0.0,
                      "statistical_noninferiority_claimed": False, "passed": exclusion_gate}},
        "selection_contract": {"tolerance": SELECTION_TOLERANCE, "tie_break": "horse number, sequential"},
        "eps": EPS, "temperature_bounds": list(TEMPERATURE_BOUNDS),
        "future_independent_validation": False, "market_roi_evaluated": False,
        "operational_exclusion_or_promotion": False, "sources": source_summary,
    }
    parameters = {
        "study": "jeju/research/20261023_bottom3_auxiliary_v1", "contract_sha256": CONTRACT_SHA256,
        "candidate": "B binary Bottom3; L=-S saved raw utility; both use unordered exact-3 subset softmax",
        "target": "1[finish_position >= field_n - 2] on complete normal finish ranks 1..N",
        "feature_names": feature_names, "categorical_columns": context["categorical_columns"],
        "lightgbm_parameters": dict(LGBM_PARAMS), "temperature_fits": temperatures,
        "models": model_metadata, "source_hashes": authorization["source_hashes"],
        "score_source_roles": {"L": "S score table filtered arm=S, provider_year=Y, role=calibration/evaluation",
                               "B": "new model raw_score=True for provider-year calibration/evaluation"},
        "split_contract": {str(year): {"initial_train_years": [2017, year - 3], "early_stop_year": year - 2,
                                        "refit_through_year": year - 2, "calibration_year": year - 1,
                                        "evaluation_year": year} for year in YEARS},
        "fit_budget": {"final_B_models": 3, "lightgbm_train_calls_expected": 6,
                       "temperature_fits_expected": 6, "actual_lightgbm_train_calls": LIGHTGBM_TRAIN_CALLS,
                       "actual_temperature_fits": TEMPERATURE_FIT_CALLS},
        "selection": {"tie_tolerance": SELECTION_TOLERANCE, "tie_break": "horse_number sequential"},
        "probability_contract": {"bottom3_subset_distribution": "normalized over all C(N,3) unordered subsets",
                                 "bottom3_marginal_sum": 3.0, "eps": EPS},
        "environment": {"python": sys.version, "numpy": np.__version__, "pandas": pd.__version__,
                        "pyarrow": pa.__version__,
                        "lightgbm": lgb.__version__, "scipy": scipy.__version__,
                        "platform": platform.platform()},
    }
    require(LIGHTGBM_TRAIN_CALLS == 6 and TEMPERATURE_FIT_CALLS == 6,
            "actual fit/calibration call count differs from fixed budget")
    # Recheck the static source pins before writing the final outputs.
    for name, (path, expected) in SOURCE_PINS.items():
        require(sha256_file(path) == expected, f"frozen source changed during execution: {name}")

    output_frames = {
        "candidate_oos_scores.parquet": pd.DataFrame(candidate_score_rows),
        "runner_probabilities.parquet": runner_probabilities,
        "race_metrics.parquet": race_metrics,
        "reliability_bins.parquet": reliability,
        "comparison_bootstrap_draws.parquet": bootstrap_draws,
    }
    for name, output_frame in output_frames.items():
        _write_frame_once(OUTPUTS / name, output_frame)
        require(_study_bytes() <= MAX_STUDY_BYTES, "study budget exceeded while writing outputs")
    _write_frame_once(OUTPUTS / "period_summary.parquet", summary_frame)
    _write_json_once(OUTPUTS / "parameters.json", parameters)
    _write_json_once(OUTPUTS / "summary.json", report)
    artifact_names = [*output_frames, "period_summary.parquet", "parameters.json", "summary.json"]
    artifacts: dict[str, Any] = {}
    for name in artifact_names:
        path = OUTPUTS / name
        details: dict[str, Any] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        if name.endswith(".parquet"):
            details["rows"] = int(pq.ParquetFile(path).metadata.num_rows)
        artifacts[name] = details
    artifacts.update({f"models/B_{year}.txt": {"sha256": model_metadata[str(year)]["model_sha256"],
                                              "bytes": (MODELS / f"B_{year}.txt").stat().st_size}
                      for year in YEARS})
    receipt = {
        "status": "COMPLETED_RESEARCH_ONLY", "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_count": 1, "elapsed_seconds": float(time.monotonic() - start_clock),
        "approval_sha256": authorization["approval_sha256"], "source_preflight_sha256": authorization["source_preflight_sha256"],
        "hashes": authorization["hashes"], "source_hashes": authorization["source_hashes"],
        "actual_lightgbm_train_calls": LIGHTGBM_TRAIN_CALLS, "actual_temperature_fits": TEMPERATURE_FIT_CALLS,
        "fit_count": LIGHTGBM_TRAIN_CALLS, "calibration_count": TEMPERATURE_FIT_CALLS,
        "candidate": "BOTTOM3_AUXILIARY_B", "artifacts": artifacts,
        "study_bytes_before_receipt": _study_bytes(), "prediction_research_candidate_gate_pass": prediction_gate,
        "exclusion_auxiliary_candidate_gate_pass": exclusion_gate,
    }
    _write_json_once(OUTPUTS / "fit_run_receipt.json", receipt)
    require(_study_bytes() <= MAX_STUDY_BYTES, "study budget exceeded after receipt")
    return report


def run_synthetic_checks() -> dict[str, Any]:
    checks: list[str] = []
    utility = np.asarray([0.7, -0.4, 0.1, 0.8, -0.2], dtype=np.float64)
    subsets, probabilities, marginals = bottom3_subset_distribution(utility, 1.3)
    require(len(subsets) == math.comb(5, 3) and abs(probabilities.sum() - 1.0) < 1e-12,
            "synthetic exact subset mass failed")
    require(abs(marginals.sum() - 3.0) < 1e-12 and np.all((marginals >= 0.0) & (marginals <= 1.0)),
            "synthetic marginal identity failed")
    checks.append("all_C_N_3_normalization_and_marginals")

    _, uniform_probabilities, uniform_marginals = bottom3_subset_distribution(np.zeros(6), 0.7)
    require(np.allclose(uniform_probabilities, np.full(20, 1.0 / 20.0), atol=1e-14, rtol=0.0) and
            np.allclose(uniform_marginals, np.full(6, 0.5), atol=1e-14, rtol=0.0),
            "synthetic uniform subset distribution failed")
    checks.append("uniform_subset_and_runner_marginal_closed_form")

    n10_bottom = _bottom3_labels(np.arange(1, 11), 10)
    require(np.flatnonzero(n10_bottom).tolist() == [7, 8, 9], "N=10 Bottom3 should be ranks 8..10")
    n5_bottom = _bottom3_labels([1, 2, 3, 4, 5], 5)
    require(np.flatnonzero(n5_bottom).tolist() == [2, 3, 4], "N=5 Bottom3 label mismatch")
    checks.append("target_is_exact_bottom_three_not_non_top_three")

    picked = choose_bottom3([0.9, 0.7, 0.2, 0.5, -0.1], [9, 1, 4, 6, 8])
    require([int([9, 1, 4, 6, 8][i]) for i in picked] == [9, 1, 6], "synthetic utility selection failed")
    tied = choose_bottom3([1.0, 1.0 - 0.5e-12, 0.0, -1.0], [7, 2, 5, 3])
    require(tied[0] == 1, "within-tolerance tie did not choose lowest horse number")
    checks.append("fixed_sequential_selection_and_tie_rule")

    records = [{"utilities": [0.5, 0.2, -0.1, 0.3, -0.3], "truth_indices": (2, 4, 3)},
               {"utilities": [-0.4, 0.1, 0.8, 0.2, 0.0], "truth_indices": (0, 3, 4)}]
    optimized = fit_bottom3_temperature(records)
    require(TEMPERATURE_BOUNDS[0] <= optimized["temperature"] <= TEMPERATURE_BOUNDS[1] and
            set(optimized["endpoint_objectives"]) == {"0.35", "4.0"},
            "synthetic bounded temperature check failed")
    checks.append("synthetic_temperature_objective_and_endpoint_comparison")

    # A synthetic race confirms selection and reported labels are internally aligned.
    synthetic_record = {"race_id": "synthetic", "race_date": "2026-01-01", "year": 2026,
                        "n": 5, "horse_numbers": np.asarray([5, 1, 8, 3, 7]),
                        "utilities": np.asarray([0.8, 0.6, -0.2, -0.1, -0.4]),
                        "ranks": np.asarray([1, 2, 5, 4, 3]), "truth_indices": (2, 3, 4)}
    metrics, runner_rows, _ = _evaluate_arm_race(synthetic_record, arm="B", temperature=1.0)
    require(metrics["actual_bottom3_horse_numbers"] == [3, 7, 8] and
            metrics["all_top3_retained"] == (not metrics["any_top3_excluded"]) and
            len(runner_rows) == 5 and abs(sum(row["p_bottom3"] for row in runner_rows) - 3.0) < 1e-10,
            "synthetic race ledger consistency failed")
    checks.append("race_metrics_keep_actual_bottom3_and_top3_protection")

    reliability_accumulator = _new_reliability_accumulator()
    _accumulate_reliability(reliability_accumulator, arm="B", year=2026,
                            set_probabilities=np.asarray([0.2, 0.3, 0.5]), true_subset_index=2,
                            runner_probabilities=np.asarray([0.1, 0.5, 0.8]),
                            runner_labels=np.asarray([0, 1, 1]))
    reliability = _reliability_frame(reliability_accumulator)
    require(len(reliability) == 256 and
            int(reliability.loc[(reliability.probability_kind == "set") &
                                (reliability.period == "ALL"), "event_count"].sum()) == 3 and
            int(reliability.loc[(reliability.probability_kind == "runner") &
                                (reliability.period == "2026"), "event_count"].sum()) == 3,
            "synthetic streaming reliability accumulation failed")
    checks.append("fixed_bin_reliability_streams_one_race_at_a_time")

    require(LIGHTGBM_TRAIN_CALLS == 0 and TEMPERATURE_FIT_CALLS == 0,
            "synthetic checks must not increment real run counters")
    return {"status": "PASS_SYNTHETIC_ONLY", "checks": checks, "check_count": len(checks),
            "real_sources_opened": False, "model_fit_performed": False,
            "real_bottom3_probabilities_or_metrics_computed": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--synthetic-checks", action="store_true")
    group.add_argument("--source-preflight", action="store_true")
    group.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.source_preflight:
        result = write_source_preflight()
    elif args.run:
        result = run_approved_once()
    else:
        result = run_synthetic_checks()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False, default=_json_default))


if __name__ == "__main__":
    main()
