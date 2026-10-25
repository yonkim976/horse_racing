#!/usr/bin/env python3
"""Approval-gated F1_STYLE6 vs rank-state transfer comparison.

Default execution is prohibited: run ``--synthetic-checks`` or
``--source-preflight`` during preparation. ``--run`` requires a single-run
supervisor receipt bound to all code, data, and frozen reference hashes.
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
import types
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import lightgbm as lgb
import numpy as np
import pandas as pd
import scipy


PROJECT = Path(__file__).resolve().parents[4]
STUDY = PROJECT / "jeju/research/20261022_tb_state_transfer_v1"
EXPERIMENT = STUDY / "experiment"
INPUTS = STUDY / "inputs"
OUTPUTS = EXPERIMENT / "outputs"
MODELS = EXPERIMENT / "models"
PLAN = EXPERIMENT / "PLAN.md"
CONTRACT = STUDY / "supervisor/DESIGN_CONTRACT.md"
APPROVAL = STUDY / "supervisor/TB_STATE_TRANSFER_EXECUTION_APPROVAL.json"
INPUT_MANIFEST = INPUTS / "input_manifest.json"
STATE_FEATURES = INPUTS / "state_features.parquet"
STATE_LINEAGE = INPUTS / "state_lineage.parquet"
SOURCE_MANIFEST = STUDY / "audit/source_manifest.json"
HISTORY_LEDGER = STUDY / "audit/history_eligibility.parquet"
F1_ROOT = PROJECT / "jeju/research/20261010_style_history_ablation_v1"
F1_FEATURES = F1_ROOT / "outputs/features.parquet"
F1_ARTIFACTS = F1_ROOT / "ARTIFACT_MANIFEST.json"
F1_META = {year: F1_ROOT / f"outputs/F1_STYLE6_{year}/meta.json" for year in (2024, 2025, 2026)}
F1_CAL = {year: F1_ROOT / f"outputs/F1_STYLE6_{year}/calibration_scores.parquet" for year in (2024, 2025, 2026)}
F1_EVAL = {year: F1_ROOT / f"outputs/F1_STYLE6_{year}/evaluation_scores.parquet" for year in (2024, 2025, 2026)}
F1_TRAIN_SCRIPT = F1_ROOT / "run.py"
REFERENCE_STUDY = PROJECT / "jeju/research/20261022_dynamic_ability_pace_v1"
REFERENCE_ENGINE = REFERENCE_STUDY / "experiment/dynamic_ability_pace.py"
REFERENCE_PARAMETERS = REFERENCE_STUDY / "experiment/outputs/parameters.json"
REFERENCE_METRICS = REFERENCE_STUDY / "experiment/outputs/race_pool_metrics.parquet"
REFERENCE_AXIS = REFERENCE_STUDY / "experiment/outputs/win_axis_ledger.parquet"
RULES = PROJECT / "jeju/research/20261022_joint_wager_baseline_v1/rules_contract/rules_contract.json"
BOOTSTRAP = PROJECT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT = PROJECT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"

CONTRACT_SHA256 = "7dc4b4f861e91e080a238e7ad85475fb50a9a5fa695896f554b131c9a6540092"
BOOTSTRAP_SHA256 = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
DATE_INVENTORY_SHA256 = "e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84"
EXPECTED_F1_FEATURES_SHA256 = "036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f"
EXPECTED_RUNNERS = 52_155
EXPECTED_RACES = 5_206
EXPECTED_EVAL_RUNNERS = 17_412
EXPECTED_EVAL_RACES = 1_779
EXPECTED_EVAL_DATES = 269
EXPECTED_EVAL_END = "2026-09-19"
EXPECTED_PLC_RACES = 1_743
MAX_STUDY_BYTES = 100_000_000
YEARS = (2024, 2025, 2026)
ARMS = ("R", "C", "S")
POOL_ORDER = ("WIN", "PLC", "QNL", "EXA", "QPL", "TLA", "TRI")
POOL_MIN_STARTERS = {"WIN": 2, "PLC": 5, "QNL": 3, "EXA": 3, "QPL": 5, "TLA": 4, "TRI": 4}
BIN_EDGES = np.asarray(
    [0.0, 0.00001, 0.00005, 0.0001, 0.00025, 0.0005, 0.001, 0.0025,
     0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0], dtype=np.float64
)
CAT_COLUMNS = ("grade_raw", "previous_sex", "previous_result_status")
STYLE_COLUMNS = (
    "hist_s1f_relpos_mean5", "hist_s1f_relpos_n", "hist_s1f_to_c4_forward_mean5",
    "hist_s1f_to_c4_pair_n", "hist_c4_to_g1f_forward_mean5", "hist_c4_to_g1f_pair_n",
)
STATE_COLUMNS = (
    "state_rank_mean", "state_rank_sd", "state_distance_slope", "state_distance_sd",
    "state_rank_current", "state_rank_current_sd", "state_rank_n",
    "state_days_since_rank_observation", "state_rank_current_field_gap",
    "state_rank_current_field_rank",
)
META_COLUMNS = (
    "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
    "distance_m", "field_n", "finish_position",
)
EVAL_RUNNER_KEYS = ("api_record_id", "race_id", "race_date", "horse_id", "horse_number")
EVAL_RACE_KEYS = ("race_id", "race_date", "distance_m", "field_n")
LGBM_PARAMS = {
    "objective": "binary", "metric": "binary_logloss", "learning_rate": 0.04,
    "num_leaves": 15, "min_data_in_leaf": 100, "lambda_l2": 5.0,
    "num_threads": 4, "deterministic": True, "force_col_wise": True,
    "verbosity": -1, "seed": 20261008,
}


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


def code_bundle_sha256() -> str:
    paths = (EXPERIMENT / "state_transfer.py", EXPERIMENT / "test_state_transfer.py")
    digest = hashlib.sha256()
    for path in paths:
        require(path.is_file(), f"missing code bundle file: {path.name}")
        relative = path.relative_to(PROJECT).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


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


def _ensure_experiment_path(path: Path) -> Path:
    resolved = path.resolve(strict=False)
    require(resolved.is_relative_to(EXPERIMENT.resolve()), f"write target escapes experiment: {path}")
    return resolved


def _write_json_once(path: Path, value: Any) -> None:
    path = _ensure_experiment_path(path)
    require(not path.exists(), f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                         allow_nan=False, default=_json_default).encode("utf-8") + b"\n"
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _write_frame_once(path: Path, frame: pd.DataFrame) -> None:
    path = _ensure_experiment_path(path)
    require(not path.exists(), f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=False, compression="zstd")
        stream.flush()
        os.fsync(stream.fileno())


def _study_bytes() -> int:
    return sum(p.stat().st_size for p in STUDY.rglob("*") if p.is_file() and not p.is_symlink())


def _load_math_engine():
    # Execute the already hash-pinned source directly so the sealed prior study's
    # __pycache__ cannot be created or refreshed as a side effect of importlib.
    before_tree = _readonly_tree_sha256(REFERENCE_STUDY / "experiment")
    name = "sealed_dynamic_ability_pace_math"
    source_bytes = REFERENCE_ENGINE.read_bytes()
    module = types.ModuleType(name)
    module.__file__ = str(REFERENCE_ENGINE)
    module.__package__ = ""
    sys.modules[name] = module
    exec(compile(source_bytes, str(REFERENCE_ENGINE), "exec", dont_inherit=True), module.__dict__)
    after_tree = _readonly_tree_sha256(REFERENCE_STUDY / "experiment")
    require(after_tree == before_tree, "loading the sealed reference modified its read-only study tree")
    module.__reference_tree_sha256__ = after_tree
    return module


def _readonly_tree_sha256(root: Path) -> str:
    root = Path(root).resolve(strict=True)
    require(root.is_relative_to(REFERENCE_STUDY.resolve()), "read-only fingerprint escaped reference study")
    digest = hashlib.sha256()
    for path in sorted((p for p in root.rglob("*") if p.is_file() and not p.is_symlink()),
                       key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def _canonical_date(frame: pd.DataFrame, column: str) -> pd.Series:
    values = pd.to_datetime(frame[column], errors="coerce")
    require(values.notna().all(), f"invalid {column} date")
    return values.dt.strftime("%Y-%m-%d")


def _manifest_file_entry(manifest: Mapping[str, Any], file_name: str) -> Mapping[str, Any]:
    files = manifest.get("files")
    require(isinstance(files, Mapping) and file_name in files, f"input manifest lacks {file_name}")
    entry = files[file_name]
    require(isinstance(entry, Mapping), f"invalid input manifest entry: {file_name}")
    return entry


def _validate_source_asset(relative: str, expected_sha: str | None = None) -> dict[str, Any]:
    path = (PROJECT / relative).resolve(strict=True)
    require(path.is_relative_to(PROJECT.resolve()), f"source reference outside project: {relative}")
    digest = sha256_file(path)
    if expected_sha:
        require(digest == expected_sha, f"source SHA mismatch: {relative}")
    return {"path": path.relative_to(PROJECT).as_posix(), "bytes": path.stat().st_size, "sha256": digest}


def _canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                         allow_nan=False, default=_json_default).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _target_key_digest(features: pd.DataFrame) -> str:
    required = ["api_record_id", "race_id", "race_date", "horse_id", "horse_number", "distance_m", "field_n"]
    require(set(required).issubset(features.columns), "F1 target metadata lacks canonical input-key columns")
    digest = hashlib.sha256()
    ordered = features.sort_values("api_record_id", kind="mergesort")
    for row in ordered[required].itertuples(index=False, name=None):
        api_record_id, race_id, race_date, horse_id, horse_number, distance_m, field_n = row
        encoded = "\t".join((str(int(api_record_id)), str(race_id), str(race_date), str(horse_id),
                             str(int(horse_number)), str(float(distance_m)), str(int(field_n))))
        digest.update(encoded.encode("utf-8") + b"\n")
    return digest.hexdigest()


def _expected_f1_columns() -> tuple[list[str], list[str]]:
    metas = {year: read_json(path) for year, path in F1_META.items()}
    columns = list(metas[2024].get("features", []))
    require(len(columns) == 30 and len(set(columns)) == 30, "F1_STYLE6 feature schema is not 30 unique inputs")
    for year in YEARS:
        require(metas[year].get("variant") == "F1_STYLE6" and int(metas[year].get("evaluation_year", -1)) == year,
                f"F1 meta vintage mismatch for {year}")
        require(metas[year].get("features") == columns and int(metas[year].get("feature_count", -1)) == 30,
                f"F1 feature list drift in vintage {year}")
        require(metas[year].get("seed") == 20261008, f"F1 seed drift in vintage {year}")
        require(metas[year].get("parameters") == LGBM_PARAMS,
                f"F1_STYLE6 locked model parameters differ in vintage {year}")
        require(set(metas[year].get("vocabulary", {})) == set(CAT_COLUMNS),
                f"F1 categorical vocabulary schema changed in vintage {year}")
    return columns, list(CAT_COLUMNS)


def _validate_f1_meta_sources() -> dict[str, Any]:
    columns, categorical_columns = _expected_f1_columns()
    artifact = read_json(F1_ARTIFACTS)
    sources: list[dict[str, Any]] = []
    for year in YEARS:
        meta = read_json(F1_META[year])
        require(meta.get("model_sha256") and meta.get("calibration_scores_sha256") and
                meta.get("evaluation_scores_sha256"), f"F1 meta missing artifact SHA for {year}")
        for role, path, meta_key in (("calibration_raw", F1_CAL[year], "calibration_scores_sha256"),
                                     ("evaluation_raw", F1_EVAL[year], "evaluation_scores_sha256")):
            record = _validate_source_asset(path.relative_to(PROJECT).as_posix(), str(meta[meta_key]))
            scores = pd.read_parquet(path)
            require(list(scores.columns) == ["api_record_id", "score"], f"unexpected raw score schema: {path.name}")
            require(scores.api_record_id.dtype == np.dtype("int64") and scores.score.dtype == np.dtype("float64"),
                    f"raw score dtype mismatch: {path.name}")
            require(scores.api_record_id.is_unique and np.isfinite(scores.score.to_numpy()).all(),
                    f"raw score has duplicate IDs or non-finite values: {path.name}")
            sources.append({**record, "year": year, "role": role, "rows": len(scores)})
        # Cross-check the original artifact manifest where that path is registered.
        for path in (F1_META[year], F1_CAL[year], F1_EVAL[year]):
            rel = path.relative_to(PROJECT).as_posix()
            entries = artifact.get("study_artifacts", {})
            require(isinstance(entries, Mapping) and rel in entries and
                    entries[rel].get("sha256") == sha256_file(path),
                    f"F1 artifact manifest mismatch: {rel}")
    return {"features": columns, "categorical_columns": categorical_columns, "sources": sources}


def _fold_vocabulary(frame: pd.DataFrame, year: int, categorical_columns: Sequence[str]) -> dict[str, list[str]]:
    train = frame.year.between(2017, year - 3)
    require(train.any(), f"empty initial training cohort for category vocabulary {year}")
    result: dict[str, list[str]] = {}
    for column in categorical_columns:
        result[column] = sorted(frame.loc[train, column].dropna().astype(str).unique().tolist())
        require(result[column], f"empty train-only categorical vocabulary: {column}/{year}")
    return result


def _validate_r_reference() -> dict[str, Any]:
    parameters = read_json(REFERENCE_PARAMETERS)
    refs = parameters.get("R_reference_fits")
    require(isinstance(refs, Mapping) and set(refs) >= {str(y) for y in YEARS},
            "previous F1 raw-to-PL temperature references are incomplete")
    result: dict[str, Any] = {"parameters_sha256": sha256_file(REFERENCE_PARAMETERS), "fits": {}}
    for year in YEARS:
        fit = refs[str(year)]
        require(fit.get("provider") == f"F1_STYLE6_{year}" and fit.get("score_semantics") == "raw_score_before_temperature",
                f"R reference is not same-vintage raw F1 score for {year}")
        require(int(fit.get("calibration_year", -1)) == year - 1 and int(fit.get("evaluation_year", -1)) == year,
                f"R calibration/evaluation year mismatch for {year}")
        temperature = float(fit.get("temperature", math.nan))
        require(math.isfinite(temperature) and 0.35 <= temperature <= 4.0 and
                float(fit.get("optimizer_x", math.nan)) == temperature,
                f"invalid frozen R temperature for {year}")
        meta = read_json(F1_META[year])
        require(str(fit.get("calibration_score_sha256")) == str(meta.get("calibration_scores_sha256")) and
                str(fit.get("evaluation_score_sha256")) == str(meta.get("evaluation_scores_sha256")),
                f"R score hashes differ from provider metadata for {year}")
        cal_sha = sha256_file(F1_CAL[year])
        eval_sha = sha256_file(F1_EVAL[year])
        require(cal_sha == fit.get("calibration_score_sha256") and eval_sha == fit.get("evaluation_score_sha256"),
                f"R source raw score file SHA mismatch for {year}")
        refit_max = pd.Timestamp(meta.get("refit_max"))
        cal_min = pd.Timestamp(meta.get("calibration_min"))
        eval_min = pd.Timestamp(meta.get("evaluation_min"))
        require(refit_max <= cal_min - pd.Timedelta(days=2) and
                refit_max <= eval_min - pd.Timedelta(days=2),
                f"F1 refit cutoff violates T−2 before calibration/evaluation in {year}")
        result["fits"][str(year)] = {
            "temperature": temperature, "calibration_year": year - 1,
            "calibration_scores_sha256": cal_sha, "evaluation_scores_sha256": eval_sha,
            "provider_meta_sha256": sha256_file(F1_META[year]),
        }
    return result


def _validate_rules_and_bootstrap(model_rows: pd.DataFrame) -> dict[str, Any]:
    rules = read_json(RULES)
    require(RULES.is_file(), "official rules contract missing")
    primary = rules.get("primary_rule", {})
    minimums = primary.get("article_4_minimum_starters", {})
    require(minimums == POOL_MIN_STARTERS, "official article-4 pool minimums differ from frozen evaluator")
    split = primary.get("plc_field_split", {})
    require(split.get("field_count_basis") == "number of starters when ticket sales begin" and
            split.get("5_to_7") == "Top2" and split.get("8_or_more") == "Top3",
            "official PLC opening-count contract mismatch")
    schedule = np.load(BOOTSTRAP, mmap_mode="r", allow_pickle=False)
    require(schedule.shape == (2000, EXPECTED_EVAL_DATES), "bootstrap shape mismatch")
    require(np.issubdtype(schedule.dtype, np.integer) and int(schedule.min()) >= 0 and
            int(schedule.max()) < EXPECTED_EVAL_DATES, "bootstrap schedule has invalid date indices")
    receipt = read_json(BOOTSTRAP_RECEIPT)
    schedule_sha = sha256_file(BOOTSTRAP)
    require(schedule_sha == BOOTSTRAP_SHA256 == receipt.get("schedule_sha256"), "bootstrap schedule SHA mismatch")
    require(receipt.get("draws") == 2000 and receipt.get("dates_per_draw") == EXPECTED_EVAL_DATES and
            receipt.get("date_inventory_sha256") == DATE_INVENTORY_SHA256,
            "bootstrap schedule receipt differs from frozen dates")
    eval_mask = model_rows.year.between(2024, 2026) & model_rows.race_date.le(EXPECTED_EVAL_END)
    eval_rows = model_rows.loc[eval_mask]
    races = eval_rows.groupby("race_id", sort=True).agg(
        race_date=("race_date", "first"), field_n=("field_n", "first"),
        n_rows=("api_record_id", "size"), unique_fields=("field_n", "nunique"),
    ).reset_index()
    require((len(eval_rows), len(races), races.race_date.nunique()) ==
            (EXPECTED_EVAL_RUNNERS, EXPECTED_EVAL_RACES, EXPECTED_EVAL_DATES), "evaluation cohort count drift")
    require((races.n_rows == races.field_n).all() and races.unique_fields.eq(1).all(),
            "evaluation race roster/field size mismatch")
    counts: dict[str, int] = {}
    for pool, minimum in POOL_MIN_STARTERS.items():
        if pool == "PLC":
            counts[pool] = int((races.field_n >= 8).sum())
        else:
            counts[pool] = int((races.field_n >= minimum).sum())
    require(counts == {"WIN": 1779, "PLC": EXPECTED_PLC_RACES, "QNL": 1779,
                       "EXA": 1779, "QPL": 1779, "TLA": 1779, "TRI": 1779},
            f"legal per-pool denominator drift: {counts}")
    dates = sorted(eval_rows.race_date.astype(str).unique().tolist())
    digest = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(digest == DATE_INVENTORY_SHA256, "evaluation date inventory differs from fixed bootstrap")
    return {"rules_sha256": sha256_file(RULES), "bootstrap_sha256": schedule_sha,
            "bootstrap_receipt_sha256": sha256_file(BOOTSTRAP_RECEIPT),
            "evaluation_races": len(races), "evaluation_runners": len(eval_rows),
            "evaluation_dates": len(dates), "date_inventory_sha256": digest,
            "pool_denominators": counts, "plc_unknown_actual_5_to_7": int(races.field_n.between(5, 7).sum())}


def load_frozen_frames(*, full: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    require(INPUT_MANIFEST.is_file() and STATE_FEATURES.is_file() and F1_FEATURES.is_file(),
            "required audited input files are not present")
    manifest = read_json(INPUT_MANIFEST)
    require(manifest.get("study") == "20261022_tb_state_transfer_v1" and
            "no model fit" in str(manifest.get("purpose", "")), "state input manifest scope mismatch")
    files = manifest.get("files")
    require(isinstance(files, Mapping), "input manifest file inventory missing")
    for name, path, expected_rows in (("state_features.parquet", STATE_FEATURES, EXPECTED_RUNNERS),
                                      ("state_lineage.parquet", STATE_LINEAGE, EXPECTED_RUNNERS)):
        entry = _manifest_file_entry(manifest, name)
        require(path.is_file() and sha256_file(path) == entry.get("sha256") and
                int(path.stat().st_size) == int(entry.get("bytes", -1)) and
                int(entry.get("rows", -1)) == expected_rows,
                f"audited state input SHA/size/row mismatch: {name}")
    require(manifest.get("fit_or_evaluation_run") is False, "input manifest reports model/evaluation execution")
    require(manifest.get("target_table_outcome_columns_read") == [] and
            manifest.get("target_feature_columns_read") == [],
            "state input builder read target outcomes or engineered target features")
    require(manifest.get("cutoff", {}).get("rule") ==
            "race_date minus two calendar days; source event date <= cutoff inclusive",
            "input manifest cutoff contract mismatch")
    require(manifest.get("source_manifest_sha256") == sha256_file(SOURCE_MANIFEST),
            "state input manifest source-audit hash mismatch")
    require(sha256_file(CONTRACT) == CONTRACT_SHA256, "frozen design contract SHA changed")

    feature_meta = _validate_f1_meta_sources()
    feature_cols = feature_meta["features"]
    feature_source_sha = sha256_file(F1_FEATURES)
    require(bool(EXPECTED_F1_FEATURES_SHA256) and feature_source_sha == EXPECTED_F1_FEATURES_SHA256,
            "F1_STYLE6 source feature SHA differs from the frozen audit pin")
    artifact = read_json(F1_ARTIFACTS)
    f1_artifact_path = F1_FEATURES.relative_to(PROJECT).as_posix()
    require(artifact.get("study_artifacts", {}).get(f1_artifact_path, {}).get("sha256") == EXPECTED_F1_FEATURES_SHA256,
            "F1_ARTIFACT_MANIFEST does not pin the expected F1 feature source SHA")
    f1_source_info = read_json(SOURCE_MANIFEST).get("sources", {})
    expected_feature_sha = f1_source_info.get("jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet", {}).get("sha256")
    if expected_feature_sha:
        require(feature_source_sha == expected_feature_sha, "F1_STYLE6 source feature hash drift")

    cols = list(dict.fromkeys([*META_COLUMNS, *feature_cols]))
    features = pd.read_parquet(F1_FEATURES, columns=cols)
    require(len(features) == EXPECTED_RUNNERS and features.api_record_id.dtype == np.dtype("int64") and
            features.api_record_id.is_unique, "F1 target features row/id inventory changed")
    require(features.race_id.notna().all() and features.horse_id.notna().all() and
            features.race_id.map(lambda v: type(v) is str and bool(v)).all() and
            features.horse_id.map(lambda v: type(v) is str and bool(v)).all(), "F1 race/horse identifiers malformed")
    features["race_date"] = _canonical_date(features, "race_date")
    features["year"] = features.race_date.str[:4].astype(np.int16)
    require(set(features.year.unique()) == set(range(2017, 2027)), "F1 target year support changed")
    for col in feature_cols:
        require(col in features.columns, f"missing F1 model feature: {col}")
    require(set(CAT_COLUMNS).issubset(feature_cols), "categorical F1 model input schema changed")
    require(features.finish_position.notna().all() and features.field_n.notna().all(), "target labels/field size missing")
    require((pd.to_numeric(features.finish_position, errors="coerce") ==
             np.rint(pd.to_numeric(features.finish_position, errors="coerce"))).all(), "finish ranks not exact integers")
    for column in ("horse_number", "field_n"):
        numeric_key = pd.to_numeric(features[column], errors="coerce").to_numpy(dtype=np.float64)
        require(np.isfinite(numeric_key).all() and np.equal(numeric_key, np.rint(numeric_key)).all(),
                f"target {column} values are not finite exact integers")
    target_distance = pd.to_numeric(features.distance_m, errors="coerce").to_numpy(dtype=np.float64)
    require(np.isfinite(target_distance).all() and np.equal(target_distance, np.rint(target_distance)).all(),
            "target distance values are not finite exact integers")
    target_digest = _target_key_digest(features)
    require(target_digest == manifest.get("target_key_digest_sha256"),
            "input manifest target-key digest differs from the exact F1 metadata")

    state = pd.read_parquet(STATE_FEATURES)
    lineage = pd.read_parquet(STATE_LINEAGE)
    required_state = ["api_record_id", "race_id", "race_date", "cutoff", "historydate", *STATE_COLUMNS]
    require(list(state.columns) == required_state, "state input schema differs from contract")
    required_lineage = ["api_record_id", "race_id", "horse_id", "cutoff", "historydate",
                        "latest_history_race_id", "history_update_count"]
    require(list(lineage.columns) == required_lineage and len(lineage) == EXPECTED_RUNNERS,
            "state lineage schema/row count differs from contract")
    require(lineage.api_record_id.dtype == np.dtype("int64") and lineage.api_record_id.is_unique and
            lineage.race_id.map(lambda v: type(v) is str and bool(v)).all() and
            lineage.horse_id.map(lambda v: type(v) is str and bool(v)).all(),
            "state lineage identifiers malformed")
    require(state.api_record_id.dtype == np.dtype("int64") and state.api_record_id.is_unique and
            state.race_id.map(lambda v: type(v) is str and bool(v)).all(), "state input keys malformed")
    state["race_date"] = _canonical_date(state, "race_date")
    state["cutoff"] = _canonical_date(state, "cutoff")
    state["historydate"] = pd.to_datetime(state.historydate, errors="coerce").dt.strftime("%Y-%m-%d")
    lineage["cutoff"] = _canonical_date(lineage, "cutoff")
    lineage["historydate"] = pd.to_datetime(lineage.historydate, errors="coerce").dt.strftime("%Y-%m-%d")
    lineage["race_date"] = (pd.to_datetime(lineage.cutoff) + pd.Timedelta(days=2)).dt.strftime("%Y-%m-%d")
    update_count = pd.to_numeric(lineage.history_update_count, errors="coerce").to_numpy(dtype=np.float64)
    require(np.isfinite(update_count).all() and np.equal(update_count, np.rint(update_count)).all() and
            (update_count >= 0).all(), "state lineage history counts are invalid")
    lineage["history_update_count"] = update_count.astype(np.int64)
    require((pd.to_datetime(state.cutoff) == pd.to_datetime(state.race_date) - pd.Timedelta(days=2)).all(),
            "state cutoff not exactly target date T−2")
    available = state.historydate.notna()
    require((state.loc[available, "historydate"] <= state.loc[available, "cutoff"]).all(),
            "state latest history date exceeds T−2 cutoff")
    require((state.state_rank_n >= 0).all() and (state.state_rank_n == np.rint(state.state_rank_n)).all(),
            "state support count is invalid")
    require(state.loc[state.state_rank_n.eq(0), "state_days_since_rank_observation"].isna().all() and
            state.loc[state.state_rank_n.gt(0), "state_days_since_rank_observation"].notna().all(),
            "state no-history age encoding changed")
    numeric = state.loc[:, list(STATE_COLUMNS)].to_numpy(dtype=np.float64, na_value=np.nan)
    require((np.isfinite(numeric) | np.isnan(numeric)).all(), "state features contain non-finite values")
    require(np.isfinite(state[list(set(STATE_COLUMNS) - {"state_days_since_rank_observation"})].to_numpy(float)).all(),
            "state feature missing outside no-history age")
    left = features.loc[:, ["api_record_id", "race_id", "race_date"]].copy()
    right = state.loc[:, ["api_record_id", "race_id", "race_date"]].copy()
    join = left.merge(right, on=["api_record_id", "race_id", "race_date"], how="outer",
                      validate="one_to_one", indicator=True)
    require(len(join) == EXPECTED_RUNNERS and join._merge.eq("both").all(),
            "state key set differs from target F1 feature cohort")
    target_lineage = features.loc[:, ["api_record_id", "race_id", "race_date", "horse_id"]].copy()
    lineage_keys = lineage.loc[:, ["api_record_id", "race_id", "race_date", "horse_id"]].copy()
    lineage_join = target_lineage.merge(lineage_keys, on=["api_record_id", "race_id", "race_date", "horse_id"],
                                        how="outer", validate="one_to_one", indicator=True)
    require(len(lineage_join) == EXPECTED_RUNNERS and lineage_join._merge.eq("both").all(),
            "state lineage API/race/date/horse keys differ from F1 target metadata")
    state_lineage = state[["api_record_id", "race_id", "race_date", "cutoff", "historydate"]].merge(
        lineage[["api_record_id", "race_id", "race_date", "cutoff", "historydate", "history_update_count"]],
        on=["api_record_id", "race_id", "race_date"], how="outer", suffixes=("_state", "_lineage"),
        validate="one_to_one", indicator=True)
    historydate_equal = (state_lineage.historydate_state.eq(state_lineage.historydate_lineage) |
                         (state_lineage.historydate_state.isna() & state_lineage.historydate_lineage.isna()))
    require(len(state_lineage) == EXPECTED_RUNNERS and state_lineage._merge.eq("both").all() and
            state_lineage.cutoff_state.eq(state_lineage.cutoff_lineage).all() and historydate_equal.all(),
            "state lineage cutoff/historydate do not match state feature rows")
    count_join = state[["api_record_id", "state_rank_n"]].merge(
        lineage[["api_record_id", "history_update_count"]], on="api_record_id", how="outer",
        validate="one_to_one", indicator=True)
    require(len(count_join) == EXPECTED_RUNNERS and count_join._merge.eq("both").all() and
            np.array_equal(count_join.state_rank_n.to_numpy(dtype=np.int64),
                           count_join.history_update_count.to_numpy(dtype=np.int64)),
            "state lineage update count differs from state_rank_n")
    features = features.merge(state[["api_record_id", *STATE_COLUMNS]], on="api_record_id",
                              how="left", validate="one_to_one")
    required_finite = list(set(STATE_COLUMNS) - {"state_days_since_rank_observation"})
    require(features[required_finite].notna().all(axis=1).all(),
            "state join produced missing model features outside explicit no-history age")
    expected_eval_mask = features.race_date.between("2024-01-01", EXPECTED_EVAL_END)
    eval_frame = features.loc[expected_eval_mask].copy()
    require((len(eval_frame), eval_frame.race_id.nunique(), eval_frame.race_date.nunique()) ==
            (EXPECTED_EVAL_RUNNERS, EXPECTED_EVAL_RACES, EXPECTED_EVAL_DATES), "exact evaluation cohort changed")
    for race_id, group in features.groupby("race_id", sort=False):
        n = int(group.field_n.iloc[0])
        ranks = group.finish_position.to_numpy(dtype=np.int64)
        require(len(group) == n and group.field_n.nunique() == 1 and
                group.api_record_id.is_unique and group.horse_id.is_unique and group.horse_number.is_unique and
                sorted(ranks.tolist()) == list(range(1, n + 1)), f"invalid target roster/ranks in {race_id}")
    if full:
        require(len(features) == EXPECTED_RUNNERS, "input frame did not load full fixed cohort")
    features = features.sort_values(["race_date", "race_id", "horse_number"], kind="mergesort").reset_index(drop=True)
    category_vocabularies = {str(year): _fold_vocabulary(features, year, feature_meta["categorical_columns"])
                             for year in YEARS}
    for year in YEARS:
        provider_meta = read_json(F1_META[year])
        require(provider_meta["vocabulary"] == category_vocabularies[str(year)],
                f"F1 provider train-only category vocabulary differs in vintage {year}")
    frozen = {
        "input_manifest_sha256": sha256_file(INPUT_MANIFEST),
        "state_features_sha256": sha256_file(STATE_FEATURES),
        "state_lineage_sha256": sha256_file(STATE_LINEAGE),
        "f1_features_sha256": feature_source_sha,
        "target_key_digest_sha256": target_digest,
        "source_manifest_sha256": sha256_file(SOURCE_MANIFEST),
        "contract_sha256": sha256_file(CONTRACT),
        "f1_columns": feature_cols,
        "categorical_columns": feature_meta["categorical_columns"],
        "category_vocabulary_by_year": category_vocabularies,
        "rows": len(features), "races": int(features.race_id.nunique()),
        "eval_rows": len(eval_frame), "eval_races": int(eval_frame.race_id.nunique()),
        "eval_dates": int(eval_frame.race_date.nunique()),
    }
    return features, state, frozen


def _reference_hashes() -> dict[str, Any]:
    refs = {
        "design_contract": CONTRACT,
        "source_manifest": SOURCE_MANIFEST,
        "history_eligibility": HISTORY_LEDGER,
        "f1_features": F1_FEATURES,
        "f1_artifact_manifest": F1_ARTIFACTS,
        "f1_train_script": F1_TRAIN_SCRIPT,
        "reference_engine": REFERENCE_ENGINE,
        "reference_parameters": REFERENCE_PARAMETERS,
        "reference_metrics": REFERENCE_METRICS,
        "reference_win_axis": REFERENCE_AXIS,
        "rules_contract": RULES,
        "bootstrap_schedule": BOOTSTRAP,
        "bootstrap_receipt": BOOTSTRAP_RECEIPT,
        "input_manifest": INPUT_MANIFEST,
        "state_features": STATE_FEATURES,
        "state_lineage": STATE_LINEAGE,
    }
    result: dict[str, Any] = {}
    for name, path in refs.items():
        require(path.is_file(), f"required referenced artifact missing: {name}")
        result[name] = {"path": path.relative_to(PROJECT).as_posix(),
                        "sha256": sha256_file(path), "bytes": path.stat().st_size}
    for year in YEARS:
        for role, path in (("meta", F1_META[year]), ("calibration", F1_CAL[year]), ("evaluation", F1_EVAL[year])):
            result[f"f1_{year}_{role}"] = {"path": path.relative_to(PROJECT).as_posix(),
                                            "sha256": sha256_file(path), "bytes": path.stat().st_size}
    source_manifest = read_json(SOURCE_MANIFEST)
    tb_source_map = source_manifest.get("sources", {})
    required_tb = (
        "thoroughbred/research/20261022_dynamic_race_model_v1/README.md",
        "thoroughbred/research/20261022_dynamic_race_model_v1/PLAN.md",
        "thoroughbred/research/20261022_dynamic_race_model_v1/state.py",
        "thoroughbred/research/20261022_dynamic_race_model_v1/common.py",
        "thoroughbred/research/20261022_dynamic_race_model_v1/train_models.py",
        "thoroughbred/research/20261022_dynamic_race_model_v1/joint.py",
        "thoroughbred/research/20261022_dynamic_race_model_v1/outputs/state_contract.json",
    )
    result["TB_58C_method_sources"] = {}
    for relative in required_tb:
        entry = tb_source_map.get(relative)
        require(isinstance(entry, Mapping), f"TB 58C source absent from audit manifest: {relative}")
        require(int(entry.get("bytes", -1)) >= 0 and isinstance(entry.get("sha256"), str),
                f"invalid TB 58C manifest record: {relative}")
        asset = _validate_source_asset(relative, str(entry["sha256"]))
        require(asset["bytes"] == int(entry["bytes"]), f"TB 58C source size mismatch: {relative}")
        result["TB_58C_method_sources"][relative] = asset
    return result


def source_preflight() -> dict[str, Any]:
    require(sha256_file(CONTRACT) == CONTRACT_SHA256, "contract SHA does not match final supervised decision")
    inputs, _state, frozen = load_frozen_frames()
    f1 = _validate_f1_meta_sources()
    reference = _validate_r_reference()
    rule_check = _validate_rules_and_bootstrap(inputs)
    source = read_json(SOURCE_MANIFEST)
    require(source.get("study") == "20261022_tb_state_transfer_v1", "source audit manifest study mismatch")
    require(sha256_file(HISTORY_LEDGER) == source.get("history_eligibility_ledger", {}).get("sha256"),
            "history eligibility ledger hash mismatch")
    expected_training_calls = 12
    expected_models = 6
    require(expected_training_calls == 2 * expected_models, "internal fit budget inconsistency")
    hashes = {
        "code_bundle_sha256": code_bundle_sha256(),
        "plan_sha256": sha256_file(PLAN),
        "design_contract_sha256": sha256_file(CONTRACT),
        "input_manifest_sha256": frozen["input_manifest_sha256"],
        "state_features_sha256": frozen["state_features_sha256"],
        "state_lineage_sha256": frozen["state_lineage_sha256"],
        "source_manifest_sha256": frozen["source_manifest_sha256"],
        "f1_features_sha256": frozen["f1_features_sha256"],
        "rules_contract_sha256": rule_check["rules_sha256"],
        "bootstrap_sha256": rule_check["bootstrap_sha256"],
        "bootstrap_receipt_sha256": rule_check["bootstrap_receipt_sha256"],
        "reference_parameters_sha256": reference["parameters_sha256"],
        "reference_engine_sha256": sha256_file(REFERENCE_ENGINE),
        "reference_metrics_sha256": sha256_file(REFERENCE_METRICS),
        "reference_assets_sha256": _canonical_json_sha256(_reference_hashes()),
    }
    report = {
        "status": "PASS_STRUCTURAL_PREFLIGHT_NO_FIT_OR_METRICS",
        "fitted": False, "probabilities_computed": False, "temperature_optimized": False,
        "outcome_metrics_computed": False,
        "fit_scope": {"arms": ["C", "S"], "final_models": expected_models,
                      "LightGBM_train_calls": expected_training_calls,
                      "PL_temperature_optimizations": 6,
                      "training_vintages": list(YEARS), "no_extra_fit": True},
        "cohort": {"rows": frozen["rows"], "races": frozen["races"],
                   "evaluation_rows": frozen["eval_rows"], "evaluation_races": frozen["eval_races"],
                   "evaluation_dates": frozen["eval_dates"]},
        "pool_denominators": rule_check["pool_denominators"],
        "plc_unknown_actual_5_to_7": rule_check["plc_unknown_actual_5_to_7"],
        "annual_splits": {
            str(year): {"initial_train_years": [2017, year - 3], "early_stop_year": year - 2,
                        "refit_years": [2017, year - 2], "calibration_year": year - 1,
                        "evaluation_year": year, "max_rounds": 800, "early_stopping_rounds": 25}
            for year in YEARS
        },
        "R_reference": reference,
        "F1_feature_count": len(f1["features"]), "F1_categorical_columns": f1["categorical_columns"],
        "reference_assets": _reference_hashes(), "hashes": hashes,
        "output_confinement": "all new writes use exclusive create beneath experiment/",
        "maximum_new_study_bytes": MAX_STUDY_BYTES,
    }
    require(_study_bytes() < MAX_STUDY_BYTES, "study already exceeds 100 MB before fit")
    preflight_path = OUTPUTS / "source_preflight.json"
    _write_json_once(preflight_path, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2), flush=True)
    return report


def _validate_approval() -> dict[str, Any]:
    require(APPROVAL.is_file(), "supervisor execution approval receipt is absent")
    approval = read_json(APPROVAL)
    require(approval.get("status") == "PASS" and approval.get("scope") == "fit_evaluate" and
            int(approval.get("permitted_runs", 0)) == 1,
            "approval must authorize exactly one fit/evaluation execution")
    preflight_path = OUTPUTS / "source_preflight.json"
    require(preflight_path.is_file(), "structural preflight receipt is missing")
    preflight = read_json(preflight_path)
    require(preflight.get("status") == "PASS_STRUCTURAL_PREFLIGHT_NO_FIT_OR_METRICS" and
            preflight.get("fitted") is False and preflight.get("probabilities_computed") is False and
            preflight.get("outcome_metrics_computed") is False,
            "source preflight does not satisfy no-fit/no-metrics contract")
    current, _state, frozen = load_frozen_frames()
    rule_check = _validate_rules_and_bootstrap(current)
    reference = _validate_r_reference()
    actual_hashes = {
        "code_bundle_sha256": code_bundle_sha256(), "plan_sha256": sha256_file(PLAN),
        "source_preflight_sha256": sha256_file(preflight_path),
        "design_contract_sha256": sha256_file(CONTRACT),
        "input_manifest_sha256": frozen["input_manifest_sha256"],
        "state_features_sha256": frozen["state_features_sha256"],
        "state_lineage_sha256": frozen["state_lineage_sha256"],
        "source_manifest_sha256": frozen["source_manifest_sha256"],
        "f1_features_sha256": frozen["f1_features_sha256"],
        "rules_contract_sha256": rule_check["rules_sha256"],
        "bootstrap_sha256": rule_check["bootstrap_sha256"],
        "bootstrap_receipt_sha256": rule_check["bootstrap_receipt_sha256"],
        "reference_parameters_sha256": reference["parameters_sha256"],
        "reference_engine_sha256": sha256_file(REFERENCE_ENGINE),
        "reference_metrics_sha256": sha256_file(REFERENCE_METRICS),
        "reference_assets_sha256": _canonical_json_sha256(_reference_hashes()),
    }
    approved_hashes = approval.get("hashes", {})
    require(isinstance(approved_hashes, Mapping), "approval hash map is invalid")
    for key, value in actual_hashes.items():
        require(approved_hashes.get(key) == value, f"approval hash mismatch: {key}")
        if key != "source_preflight_sha256":
            require(preflight.get("hashes", {}).get(key) == value, f"preflight hash mismatch: {key}")
    require(preflight.get("reference_assets") == _reference_hashes(),
            "referenced source assets changed after structural preflight")
    require(approval.get("candidate") == "TB_STATE_TRANSFER_C_S" and
            approval.get("final_models") == 6 and approval.get("lightgbm_train_calls") == 12 and
            approval.get("temperature_optimizations") == 6,
            "approval fit budget/candidate mismatch")
    require(_study_bytes() < MAX_STUDY_BYTES, "study exceeds 100 MB before execution")
    require(not (OUTPUTS / "execution_claim.json").exists(), "execution was already claimed; no retry allowed")
    require(not MODELS.exists() or not any(MODELS.iterdir()), "model directory already contains artifacts")
    require(sorted(p.name for p in OUTPUTS.iterdir()) == ["source_preflight.json"],
            "outputs must contain only structural preflight before the one run")
    return {"approval": approval, "approval_sha256": sha256_file(APPROVAL),
            "hashes": actual_hashes, "preflight_sha256": sha256_file(preflight_path)}


def _transform_features(frame: pd.DataFrame, columns: Sequence[str], vocabulary: Mapping[str, Sequence[str]]) -> pd.DataFrame:
    values = frame.loc[:, list(columns)].copy()
    for column, categories in vocabulary.items():
        if column in values.columns:
            values[column] = pd.Categorical(values[column].astype("string"), categories=list(categories))
    return values


def _race_records(frame: pd.DataFrame, scores: Sequence[float]) -> list[dict[str, Any]]:
    score_values = np.asarray(scores, dtype=np.float64)
    require(len(frame) == len(score_values) and np.isfinite(score_values).all(), "score vector does not match frame")
    records: list[dict[str, Any]] = []
    tmp = frame[["race_id", "race_date", "year", "field_n", "horse_number", "finish_position"]].copy()
    tmp["__score"] = score_values
    for race_id, group in tmp.groupby("race_id", sort=True):
        group = group.sort_values("horse_number", kind="mergesort")
        numbers = group.horse_number.to_numpy(dtype=np.int64)
        ranks = group.finish_position.to_numpy(dtype=np.int64)
        require(len(group) == int(group.field_n.iloc[0]) and sorted(ranks.tolist()) == list(range(1, len(group) + 1)),
                f"invalid rank/roster in calibration race {race_id}")
        records.append({"race_id": str(race_id), "race_date": str(group.race_date.iloc[0]),
                        "year": int(group.year.iloc[0]), "n": len(group), "numbers": numbers,
                        "ranks": ranks, "scores": group.__score.to_numpy(dtype=np.float64)})
    return records


def _fit_temperature(records: Sequence[Mapping[str, Any]], engine) -> dict[str, Any]:
    result = engine.fit_joint_temperature(records, bounds=(0.35, 4.0))
    require(math.isfinite(float(result["temperature"])) and 0.35 <= float(result["temperature"]) <= 4.0,
            "joint PL temperature fit returned invalid temperature")
    require(result.get("optimizer_success") is True and int(result.get("races", -1)) == len(records),
            "joint PL temperature fit metadata mismatch")
    return result


def _fit_arm_year(frame: pd.DataFrame, *, arm: str, year: int, base_columns: Sequence[str],
                  categorical_vocab: Mapping[str, Sequence[str]]) -> tuple[lgb.Booster, dict[str, Any], np.ndarray, np.ndarray]:
    require(arm in ("C", "S"), "only new C/S candidates may be fit")
    columns = list(base_columns) + (list(STATE_COLUMNS) if arm == "S" else [])
    require(len(columns) == (40 if arm == "S" else 30), f"{arm} feature count is not contracted")
    year_values = frame.year.to_numpy(dtype=np.int64)
    train_mask = (year_values >= 2017) & (year_values <= year - 3)
    valid_mask = year_values == year - 2
    cal_mask = year_values == year - 1
    eval_mask = (year_values == year) & (frame.race_date.to_numpy() <= EXPECTED_EVAL_END)
    require(all(mask.any() for mask in (train_mask, valid_mask, cal_mask, eval_mask)), f"empty annual split for {arm}/{year}")
    for mask, role, year_expected in ((train_mask, "initial train", year - 3),
                                      (valid_mask, "early stopping", year - 2),
                                      (cal_mask, "calibration", year - 1),
                                      (eval_mask, "evaluation", year)):
        years_present = set(year_values[mask].tolist())
        if role == "initial train":
            require(years_present == set(range(2017, year_expected + 1)), f"initial train vintage drift {arm}/{year}")
        else:
            require(years_present == {year_expected}, f"annual {role} vintage drift {arm}/{year}")
    x = _transform_features(frame, columns, categorical_vocab)
    target = (frame.finish_position.to_numpy(dtype=np.int64) <= 3).astype(np.int8)
    weight = 1.0 / frame.field_n.to_numpy(dtype=np.float64)
    require(np.isfinite(weight).all() and (weight > 0).all(), "invalid race-equal binary runner weights")
    categories = [column for column in categorical_vocab if column in columns]

    def dataset(mask: np.ndarray) -> lgb.Dataset:
        return lgb.Dataset(x.loc[mask], label=target[mask], weight=weight[mask],
                           categorical_feature=categories, feature_name=list(columns), free_raw_data=False)

    initial = lgb.train(LGBM_PARAMS, dataset(train_mask), num_boost_round=800,
                        valid_sets=[dataset(valid_mask)], valid_names=["early_stop"],
                        callbacks=[lgb.early_stopping(25, verbose=False)])
    best_iteration = int(initial.best_iteration)
    require(best_iteration > 0, f"LightGBM early stopping returned no iteration for {arm}/{year}")
    refit_mask = train_mask | valid_mask
    final = lgb.train(LGBM_PARAMS, dataset(refit_mask), num_boost_round=best_iteration)
    cal_scores = np.asarray(final.predict(x.loc[cal_mask], raw_score=True, num_threads=4), dtype=np.float64)
    eval_scores = np.asarray(final.predict(x.loc[eval_mask], raw_score=True, num_threads=4), dtype=np.float64)
    require(np.isfinite(cal_scores).all() and np.isfinite(eval_scores).all(), f"non-finite raw score {arm}/{year}")
    meta = {
        "arm": arm, "evaluation_year": int(year), "feature_count": len(columns),
        "feature_names": list(columns), "categorical_vocabulary": {k: list(v) for k, v in categorical_vocab.items()},
        "parameters": LGBM_PARAMS, "seed": 20261008, "max_rounds": 800,
        "early_stopping_rounds": 25, "best_iteration": best_iteration,
        "train_min": str(frame.loc[train_mask, "race_date"].min()),
        "initial_train_max": str(frame.loc[train_mask, "race_date"].max()),
        "early_stop_min": str(frame.loc[valid_mask, "race_date"].min()),
        "early_stop_max": str(frame.loc[valid_mask, "race_date"].max()),
        "refit_max": str(frame.loc[refit_mask, "race_date"].max()),
        "calibration_min": str(frame.loc[cal_mask, "race_date"].min()),
        "calibration_max": str(frame.loc[cal_mask, "race_date"].max()),
        "evaluation_min": str(frame.loc[eval_mask, "race_date"].min()),
        "evaluation_max": str(frame.loc[eval_mask, "race_date"].max()),
        "initial_train_rows": int(train_mask.sum()), "initial_train_races": int(frame.loc[train_mask, "race_id"].nunique()),
        "refit_rows": int(refit_mask.sum()), "refit_races": int(frame.loc[refit_mask, "race_id"].nunique()),
        "calibration_rows": int(cal_mask.sum()), "calibration_races": int(frame.loc[cal_mask, "race_id"].nunique()),
        "evaluation_rows": int(eval_mask.sum()), "evaluation_races": int(frame.loc[eval_mask, "race_id"].nunique()),
        "lightgbm_calls": 2, "temperature_optimization_count": 1,
    }
    return final, meta, cal_scores, eval_scores


def _load_r_scores(model_rows: pd.DataFrame, reference_parameters: Mapping[str, Any]) -> tuple[dict[int, pd.DataFrame], dict[int, float]]:
    fits = reference_parameters["R_reference_fits"]
    output: dict[int, pd.DataFrame] = {}
    temperatures: dict[int, float] = {}
    for year in YEARS:
        path = F1_EVAL[year]
        raw = pd.read_parquet(path)
        target = model_rows.loc[(model_rows.year == year) & (model_rows.race_date <= EXPECTED_EVAL_END),
                                ["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
                                 "field_n", "finish_position", "distance_m"]].copy()
        require(len(raw) == len(target) and raw.api_record_id.is_unique,
                f"R source row count mismatch for year {year}")
        joined = target.merge(raw, on="api_record_id", how="outer", validate="one_to_one", indicator=True)
        require(joined._merge.eq("both").all() and np.isfinite(joined.score.to_numpy(dtype=np.float64)).all(),
                f"R source keys/scores do not match frozen F1 target rows for {year}")
        joined = joined.drop(columns="_merge")
        joined["race_date"] = joined.race_date.astype(str)
        output[year] = joined
        temperatures[year] = float(fits[str(year)]["temperature"])
    return output, temperatures


def _reliability_add(bins: dict[tuple[str, str, int], list[float]], pool: str, arm: str,
                     year: int, tickets: Mapping[tuple[int, ...], float], truths: set[tuple[int, ...]]) -> None:
    for period in ("ALL", str(year)):
        for key, probability in tickets.items():
            p = float(probability)
            require(math.isfinite(p) and 0 <= p <= 1, "invalid probability in reliability bins")
            index = min(max(int(np.searchsorted(BIN_EDGES, p, side="right") - 1), 0), len(BIN_EDGES) - 2)
            item = bins[(pool, arm, period, index)]
            y = float(key in truths)
            item[0] += 1.0
            item[1] += p
            item[2] += y
            item[3] += (p - y) ** 2


def _top_k_tickets(tickets: Mapping[tuple[int, ...], float], k: int, tolerance: float = 1e-12) -> list[tuple[int, ...]]:
    remaining = dict(tickets)
    selected: list[tuple[int, ...]] = []
    for _ in range(k):
        require(remaining, "not enough tickets to select requested k")
        best = max(float(p) for p in remaining.values())
        key = min(ticket for ticket, p in remaining.items() if float(p) >= best - tolerance)
        selected.append(key)
        del remaining[key]
    return selected


def _pair_selection_diagnostic(record: Mapping[str, Any], scaled_scores: np.ndarray,
                               pool: str, selected: Sequence[tuple[int, ...]], engine) -> dict[str, Any]:
    require(pool in ("QNL", "QPL") and len(selected) in (1, 3), "invalid pair selection diagnostic")
    chosen = [tuple(int(x) for x in ticket) for ticket in selected]
    counts = np.zeros(4, dtype=np.float64)
    for i, j, k, probability in engine.iter_pl_top3(scaled_scores):
        numbers = [int(record["numbers"][ix]) for ix in (i, j, k)]
        if pool == "QNL":
            observed = {tuple(sorted((numbers[0], numbers[1])))}
        else:
            observed = {tuple(sorted(pair)) for pair in ((numbers[0], numbers[1]),
                                                           (numbers[0], numbers[2]),
                                                           (numbers[1], numbers[2]))}
        count = len(set(chosen).intersection(observed))
        counts[count] += float(probability)
    require(abs(float(counts.sum()) - 1.0) <= 3e-11, f"{pool} selection count distribution mass mismatch")
    return {
        "selected_tickets_json": json.dumps([list(key) for key in chosen], separators=(",", ":")),
        "selected_probabilities_json": json.dumps([float(record["tickets"][key]) for key in chosen], separators=(",", ":")),
        "selected_union_probability": float(counts[1:].sum()),
        "expected_hits": float(np.dot(np.arange(4, dtype=np.float64), counts)),
        "realized_hit_count": int(sum(ticket in set(record["truths"]) for ticket in chosen)),
        "count_probability_0": float(counts[0]), "count_probability_1": float(counts[1]),
        "count_probability_2": float(counts[2]), "count_probability_3": float(counts[3]),
        "selected_ticket_count": len(chosen),
        "count_semantics": "number of selected unordered pairs present in actual ordered Top-3; QNL actual count is 0/1",
    }


def _race_truth(record: Mapping[str, Any], pool: str, plc_top: int | None, engine) -> set[tuple[int, ...]]:
    return engine.truth_ticket_keys(pool, record["numbers"], record["ranks"], plc_top)


def _evaluate_all(model_rows: pd.DataFrame, c_s_scores: pd.DataFrame, r_scores: Mapping[int, pd.DataFrame],
                  temperatures: Mapping[tuple[str, int], float], engine, schedule: np.ndarray) -> dict[str, pd.DataFrame | dict[str, Any]]:
    eval_mask = model_rows.race_date.between("2024-01-01", EXPECTED_EVAL_END)
    target = model_rows.loc[eval_mask].copy()
    scores = target[["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
                     "field_n", "finish_position", "distance_m"]].merge(
        c_s_scores.loc[c_s_scores.role.eq("evaluation"), ["arm", "year", "api_record_id", "score"]],
        on=["year", "api_record_id"], how="left", validate="one_to_many")
    require(len(scores) == EXPECTED_EVAL_RUNNERS * 2 and scores.score.notna().all(),
            "C/S evaluation raw score keys do not cover exact cohort")
    records_by_arm_race: dict[tuple[str, str], dict[str, Any]] = {}
    for arm, group in scores.groupby("arm", sort=False):
        for race_id, one in group.groupby("race_id", sort=True):
            one = one.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
            require(one.arm.nunique() == 1 and one.year.nunique() == 1 and len(one) == int(one.field_n.iloc[0]),
                    f"C/S evaluation race key mismatch: {arm}/{race_id}")
            records_by_arm_race[(arm, str(race_id))] = {
                "race_id": str(race_id), "race_date": str(one.race_date.iloc[0]),
                "year": int(one.year.iloc[0]), "n": len(one),
                "numbers": one.horse_number.to_numpy(dtype=np.int64),
                "ranks": one.finish_position.to_numpy(dtype=np.int64),
                "scores": one.score.to_numpy(dtype=np.float64),
                "runner_rows": one,
            }
    for year, one in r_scores.items():
        for race_id, group in one.groupby("race_id", sort=True):
            group = group.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
            records_by_arm_race[("R", str(race_id))] = {
                "race_id": str(race_id), "race_date": str(group.race_date.iloc[0]),
                "year": int(year), "n": len(group),
                "numbers": group.horse_number.to_numpy(dtype=np.int64),
                "ranks": group.finish_position.to_numpy(dtype=np.int64),
                "scores": group.score.to_numpy(dtype=np.float64), "runner_rows": group,
            }
    require(len(records_by_arm_race) == 3 * EXPECTED_EVAL_RACES, "arm/race score record inventory mismatch")

    metric_rows: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    marginal_rows: list[dict[str, Any]] = []
    axis_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    contract_rows: list[dict[str, Any]] = []
    quarantine_rows: list[dict[str, Any]] = []
    bins: dict[tuple[str, str, str, int], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for race_id in sorted(target.race_id.unique()):
        base = target.loc[target.race_id.eq(race_id)].sort_values("horse_number", kind="mergesort").reset_index(drop=True)
        n = len(base)
        require(n == int(base.field_n.iloc[0]) and sorted(base.finish_position.astype(int).tolist()) == list(range(1, n + 1)),
                f"truth roster invalid at evaluation: {race_id}")
        year = int(base.year.iloc[0])
        race_date = str(base.race_date.iloc[0])
        plc_top, plc_status = engine.plc_top_for_actual_field(n)
        contract_rows.append({"race_id": str(race_id), "race_date": race_date, "year": year,
                              "field_n": n, "opening_field_n": None,
                              "opening_count_source": "actual_lower_bound" if n >= 8 else "unobserved",
                              "plc_top": plc_top, "plc_status": plc_status,
                              "official_sales_or_pool_availability": "not_audited"})
        if plc_top is None and 5 <= n <= 7:
            quarantine_rows.append({"race_id": str(race_id), "race_date": race_date, "field_n": n,
                                    "pool": "PLC", "reason": "opening_field_unknown_actual_5_to_7"})
        for arm in ARMS:
            record = records_by_arm_race[(arm, str(race_id))]
            temp = float(temperatures[(arm, year)])
            scaled = record["scores"] / temp
            maps, marginal, full_mass = engine.probability_maps_from_scenarios(
                [scaled], [1.0], record["numbers"], plc_top)
            require(abs(full_mass - 1.0) <= 3e-11, f"Q mass mismatch: {arm}/{race_id}")
            truths_by_pool: dict[str, set[tuple[int, ...]]] = {}
            for pool in POOL_ORDER:
                if n < POOL_MIN_STARTERS[pool] or (pool == "PLC" and plc_top is None):
                    continue
                truths = _race_truth(record, pool, plc_top, engine)
                truths_by_pool[pool] = truths
                metric, selection = engine.pool_race_metrics(pool, maps[pool], truths)
                metric.update({"race_id": str(race_id), "race_date": race_date, "year": year,
                               "field_n": n, "arm": arm})
                selection.update({"race_id": str(race_id), "race_date": race_date, "year": year,
                                  "field_n": n, "arm": arm})
                metric_rows.append(metric)
                selection_rows.append(selection)
                for period in ("ALL", str(year)):
                    for key, probability in maps[pool].items():
                        p = float(probability)
                        idx = min(max(int(np.searchsorted(BIN_EDGES, p, side="right") - 1), 0), len(BIN_EDGES) - 2)
                        y = float(key in truths)
                        item = bins[(pool, arm, period, idx)]
                        item[0] += 1.0
                        item[1] += p
                        item[2] += y
                        item[3] += (p - y) ** 2
            for ix, horse_number in enumerate(record["numbers"]):
                marginal_rows.append({"race_id": str(race_id), "race_date": race_date, "year": year,
                                      "horse_number": int(horse_number), "arm": arm,
                                      **{key: float(value[ix]) for key, value in marginal.items()}})
            win_p = marginal["p_win"]
            max_p = float(win_p.max())
            selected_ix = min(ix for ix, p in enumerate(win_p) if float(p) >= max_p - 1e-12)
            axis_rows.append({"race_id": str(race_id), "race_date": race_date, "year": year, "arm": arm,
                              "selected_horse_number": int(record["numbers"][selected_ix]),
                              "selected_probability": float(win_p[selected_ix]),
                              "selected_hit_top3": bool(record["ranks"][selected_ix] <= 3)})
            for pool in ("QNL", "QPL"):
                tickets = maps[pool]
                truths = truths_by_pool[pool]
                for k in (1, 3):
                    selected = _top_k_tickets(tickets, k, tolerance=1e-12)
                    diag_record = {"numbers": record["numbers"], "truths": truths,
                                   "tickets": tickets}
                    diagnostic = _pair_selection_diagnostic(diag_record, scaled, pool, selected, engine)
                    pair_rows.append({"race_id": str(race_id), "race_date": race_date, "year": year,
                                      "field_n": n, "arm": arm, "pool": pool, "k": k, **diagnostic})
    metrics = pd.DataFrame(metric_rows)
    selections = pd.DataFrame(selection_rows)
    marginals = pd.DataFrame(marginal_rows)
    axis = pd.DataFrame(axis_rows)
    pair_diagnostics = pd.DataFrame(pair_rows)
    contract_ledger = pd.DataFrame(contract_rows)
    quarantine = pd.DataFrame(quarantine_rows, columns=["race_id", "race_date", "field_n", "pool", "reason"])
    require(len(metrics) == 3 * (6 * EXPECTED_EVAL_RACES + EXPECTED_PLC_RACES), "pool metric row count mismatch")
    require(len(selections) == len(metrics) and len(marginals) == 3 * EXPECTED_EVAL_RUNNERS and
            len(axis) == 3 * EXPECTED_EVAL_RACES, "evaluation ledger row count mismatch")
    require(len(quarantine) == EXPECTED_EVAL_RACES - EXPECTED_PLC_RACES, "PLC quarantine count mismatch")
    for pool in POOL_ORDER:
        expected = EXPECTED_PLC_RACES if pool == "PLC" else EXPECTED_EVAL_RACES
        counts = metrics.loc[metrics.pool.eq(pool)].groupby("arm").race_id.nunique().to_dict()
        require(counts == {arm: expected for arm in ARMS}, f"per-arm {pool} denominator mismatch: {counts}")

    old_axis = pd.read_parquet(REFERENCE_AXIS)
    old_r_axis = old_axis.loc[old_axis.arm.eq("R"),
                              ["race_id", "race_date", "selected_horse_number", "selected_hit_top3"]].copy()
    new_r_axis = axis.loc[axis.arm.eq("R"),
                          ["race_id", "race_date", "selected_horse_number", "selected_hit_top3"]].copy()
    axis_check = old_r_axis.merge(new_r_axis, on=["race_id", "race_date"], how="outer",
                                  suffixes=("_old", "_new"), validate="one_to_one", indicator=True)
    require(len(axis_check) == EXPECTED_EVAL_RACES and axis_check._merge.eq("both").all() and
            axis_check.selected_horse_number_old.eq(axis_check.selected_horse_number_new).all() and
            axis_check.selected_hit_top3_old.eq(axis_check.selected_hit_top3_new).all(),
            "recomputed R WIN axis differs from the sealed prior axis ledger")
    require(int(new_r_axis.selected_hit_top3.sum()) == 1023,
            "R WIN Top3 axis hit count does not reproduce the sealed 1,023 reference")

    # Recompute and enforce the exact saved R arm scorecard before using it as a baseline.
    old_metrics = pd.read_parquet(REFERENCE_METRICS)
    old_r = old_metrics.loc[old_metrics.arm.eq("R"), ["race_id", "pool", "race_nll", "race_brier"]].copy()
    new_r = metrics.loc[metrics.arm.eq("R"), ["race_id", "pool", "race_nll", "race_brier"]].copy()
    check_r = old_r.merge(new_r, on=["race_id", "pool"], how="outer", suffixes=("_old", "_new"),
                          validate="one_to_one", indicator=True)
    require(len(check_r) == len(old_r) == len(new_r) and check_r._merge.eq("both").all(),
            "recomputed R metric ledger keys differ from sealed prior study")
    max_r_error = float(np.max(np.abs(check_r.race_nll_old - check_r.race_nll_new)))
    max_r_brier_error = float(np.max(np.abs(check_r.race_brier_old - check_r.race_brier_new)))
    require(max_r_error <= 1e-12 and max_r_brier_error <= 1e-12,
            f"recomputed R metrics fail exact reference replay: nll={max_r_error}, brier={max_r_brier_error}")

    summary = metrics.groupby(["pool", "arm"], sort=False).agg(
        races=("race_id", "nunique"), mean_race_nll=("race_nll", "mean"),
        mean_race_brier=("race_brier", "mean"), ticket_count=("ticket_count", "sum"),
        event_count=("event_count", "sum"),
    ).reset_index()
    year_summary = metrics.groupby(["pool", "arm", "year"], sort=False).agg(
        races=("race_id", "nunique"), mean_race_nll=("race_nll", "mean"),
        mean_race_brier=("race_brier", "mean"), ticket_count=("ticket_count", "sum"),
        event_count=("event_count", "sum"),
    ).reset_index()
    paired_rows: list[dict[str, Any]] = []
    pool_comparisons: list[dict[str, Any]] = []
    year_comparisons: list[dict[str, Any]] = []
    for left, right in (("C", "R"), ("S", "C"), ("S", "R")):
        for pool in POOL_ORDER:
            left_frame = metrics.loc[metrics.arm.eq(left) & metrics.pool.eq(pool)].set_index("race_id")
            right_frame = metrics.loc[metrics.arm.eq(right) & metrics.pool.eq(pool)].set_index("race_id")
            join = left_frame[["race_date", "year", "race_nll", "race_brier"]].join(
                right_frame[["race_nll", "race_brier"]], how="outer", lsuffix=f"_{left}", rsuffix=f"_{right}",
                validate="one_to_one")
            require(len(join) == (EXPECTED_PLC_RACES if pool == "PLC" else EXPECTED_EVAL_RACES) and
                    join.notna().all().all(), f"paired {pool}/{left}-{right} keys differ")
            part = join.reset_index(names="race_id")
            part["comparison"] = f"{left}_minus_{right}"
            part["pool"] = pool
            part["delta_nll"] = part[f"race_nll_{left}"] - part[f"race_nll_{right}"]
            part["delta_brier"] = part[f"race_brier_{left}"] - part[f"race_brier_{right}"]
            paired_rows.extend(part.to_dict("records"))
            pool_comparisons.append({"comparison": f"{left}_minus_{right}", "pool": pool,
                                     "races": len(part), "delta_mean_race_nll": float(part.delta_nll.mean()),
                                     "delta_mean_race_brier": float(part.delta_brier.mean()),
                                     "left_mean_race_nll": float(part[f"race_nll_{left}"].mean()),
                                     "right_mean_race_nll": float(part[f"race_nll_{right}"].mean()),
                                     "left_mean_race_brier": float(part[f"race_brier_{left}"].mean()),
                                     "right_mean_race_brier": float(part[f"race_brier_{right}"].mean())})
            for year in YEARS:
                sub = part.loc[part.year.eq(year)]
                year_comparisons.append({"comparison": f"{left}_minus_{right}", "pool": pool,
                                         "year": year, "races": len(sub),
                                         "delta_mean_race_nll": float(sub.delta_nll.mean()),
                                         "delta_mean_race_brier": float(sub.delta_brier.mean())})
    paired = pd.DataFrame(paired_rows)
    reliability_rows: list[dict[str, Any]] = []
    for pool in POOL_ORDER:
        for arm in ARMS:
            for period in ("ALL", "2024", "2025", "2026"):
                for index, (low, high) in enumerate(zip(BIN_EDGES[:-1], BIN_EDGES[1:])):
                    count, sum_p, sum_y, sum_brier = bins.get((pool, arm, period, index), [0, 0, 0, 0])
                    reliability_rows.append({"pool": pool, "arm": arm, "evaluation_period": period,
                                             "bin_index": index, "bin_lower": float(low), "bin_upper": float(high),
                                             "upper_inclusive": bool(index == len(BIN_EDGES) - 2),
                                             "ticket_events": int(count),
                                             "mean_probability": float(sum_p / count) if count else np.nan,
                                             "observed_event_rate": float(sum_y / count) if count else np.nan,
                                             "mean_ticket_brier": float(sum_brier / count) if count else np.nan,
                                             "weighting": "pooled_ticket_event_count"})
    reliability = pd.DataFrame(reliability_rows)

    dates = sorted(target.race_date.astype(str).unique().tolist())
    date_hash = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(date_hash == DATE_INVENTORY_SHA256 and schedule.shape == (2000, len(dates)),
            "bootstrap date inventory mismatch")
    bootstrap_draw_rows: list[dict[str, Any]] = []
    bootstrap_summaries: list[dict[str, Any]] = []
    for left, right in (("C", "R"), ("S", "C"), ("S", "R")):
        part = paired.loc[paired.pool.eq("TRI") & paired.comparison.eq(f"{left}_minus_{right}")]
        day_sums = part.groupby("race_date", sort=True).delta_nll.sum().reindex(dates, fill_value=0).to_numpy(float)
        day_counts = part.groupby("race_date", sort=True).race_id.count().reindex(dates, fill_value=0).to_numpy(float)
        draws = np.empty(schedule.shape[0], dtype=np.float64)
        for ix, selection in enumerate(schedule):
            mult = np.bincount(np.asarray(selection, dtype=np.int64), minlength=len(dates)).astype(np.float64)
            denom = float(np.dot(mult, day_counts))
            require(denom > 0, "empty TRI bootstrap draw")
            draws[ix] = float(np.dot(mult, day_sums) / denom)
            bootstrap_draw_rows.append({"comparison": f"{left}_minus_{right}", "draw": ix,
                                        "tri_nll_difference": float(draws[ix])})
        low, high = np.quantile(draws, [0.025, 0.975], method="linear")
        tri = part
        win_part = paired.loc[paired.pool.eq("WIN") & paired.comparison.eq(f"{left}_minus_{right}")]
        bootstrap_summaries.append({"comparison": f"{left}_minus_{right}",
                                    "tri_races": len(tri), "dates": len(dates),
                                    "bootstrap_draws": len(draws),
                                    "tri_delta_mean_race_nll": float(tri.delta_nll.mean()),
                                    "tri_delta_nll_ci95": [float(low), float(high)],
                                    "tri_delta_mean_race_brier": float(tri.delta_brier.mean()),
                                    "tri_gate_pass": bool(high < 0 and float(tri.delta_brier.mean()) <= 0),
                                    "win_delta_mean_race_nll": float(win_part.delta_nll.mean()),
                                    "win_delta_mean_race_brier": float(win_part.delta_brier.mean()),
                                    "win_point_protection_pass": bool(win_part.delta_nll.mean() <= 0 and
                                                                       win_part.delta_brier.mean() <= 0),
                                    "comparison_gate_pass": bool(high < 0 and tri.delta_brier.mean() <= 0 and
                                                                  win_part.delta_nll.mean() <= 0 and
                                                                  win_part.delta_brier.mean() <= 0),
                                    "schedule_sha256": BOOTSTRAP_SHA256,
                                    "date_inventory_sha256": date_hash,
                                    "statistical_noninferiority_claimed": False})
    axis_summary, axis_bootstrap = _axis_reports(axis, schedule, dates)
    pair_summary = pair_diagnostics.groupby(["arm", "pool", "k"], sort=False).agg(
        races=("race_id", "nunique"), mean_union_probability=("selected_union_probability", "mean"),
        realized_hit_rate=("realized_hit_count", lambda values: float(np.mean(values > 0))),
        expected_hits=("expected_hits", "mean"), mean_realized_hit_count=("realized_hit_count", "mean"),
    ).reset_index()
    report = {
        "status": "EVALUATED_RESEARCH_ONLY", "arms": list(ARMS),
        "evaluation_races": EXPECTED_EVAL_RACES, "evaluation_runners": EXPECTED_EVAL_RUNNERS,
        "evaluation_dates": EXPECTED_EVAL_DATES,
        "per_pool_denominators": {pool: (EXPECTED_PLC_RACES if pool == "PLC" else EXPECTED_EVAL_RACES)
                                   for pool in POOL_ORDER},
        "comparisons": bootstrap_summaries,
        "S_minus_C_gate_pass": next(row["comparison_gate_pass"] for row in bootstrap_summaries if row["comparison"] == "S_minus_C"),
        "S_minus_R_gate_pass": next(row["comparison_gate_pass"] for row in bootstrap_summaries if row["comparison"] == "S_minus_R"),
        "C_minus_R_descriptive_only": True,
        "overall_research_candidate_gate_pass": all(row["comparison_gate_pass"] for row in bootstrap_summaries
                                                    if row["comparison"] in ("S_minus_C", "S_minus_R")),
        "gate_scope": "predeclared research-only criteria on reused development evaluations; no production promotion",
        "win_axis": axis_summary.to_dict("records"), "win_axis_bootstrap": axis_bootstrap.to_dict("records"),
        "pair_selection_summary": pair_summary.to_dict("records"),
        "R_replay_max_abs_nll_error": max_r_error, "R_replay_max_abs_brier_error": max_r_brier_error,
        "fit_uncertainty_included": False,
        "reliability_weighting": "pooled ticket-event count; proper losses are race-equal",
    }
    return {
        "race_pool_metrics": metrics, "selected_ticket_ledger": selections,
        "evaluation_runner_marginals": marginals, "win_axis_ledger": axis,
        "pair_selection_diagnostics": pair_diagnostics, "race_contract_ledger": contract_ledger,
        "evaluation_quarantine": quarantine, "pool_summary": summary, "pool_year_summary": year_summary,
        "pool_comparisons": pd.DataFrame(pool_comparisons), "pool_year_comparisons": pd.DataFrame(year_comparisons),
        "paired_pool_comparisons": paired, "reliability_bins": reliability,
        "comparison_bootstrap_draws": pd.DataFrame(bootstrap_draw_rows),
        "win_axis_summary": axis_summary, "win_axis_bootstrap": axis_bootstrap,
        "pair_selection_summary": pair_summary, "evaluation_report": report,
    }


def _axis_reports(axis: pd.DataFrame, schedule: np.ndarray, dates: Sequence[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    by_arm: dict[str, pd.DataFrame] = {}
    summary: list[dict[str, Any]] = []
    boot: list[dict[str, Any]] = []
    for arm in ARMS:
        frame = axis.loc[axis.arm.eq(arm)].set_index("race_id")
        require(len(frame) == EXPECTED_EVAL_RACES and frame.index.is_unique, f"axis ledger coverage failed: {arm}")
        by_arm[arm] = frame
        hits = int(frame.selected_hit_top3.sum())
        if arm == "R":
            require(hits == 1023, "R WIN Top3 axis must reproduce exactly 1,023 hits")
        summary.append({"arm": arm, "races": len(frame), "top3_hit_count": hits,
                        "top3_hit_rate": hits / len(frame), "benchmark_R_hits": 1023,
                        "benchmark_10pct_count_target": 1126,
                        "relative_improvement_vs_R": (hits / 1023.0) - 1.0})
    for left, right in (("C", "R"), ("S", "C"), ("S", "R")):
        pair = by_arm[left][["race_date", "selected_hit_top3"]].join(
            by_arm[right][["selected_hit_top3"]], how="outer", lsuffix=f"_{left}", rsuffix=f"_{right}",
            validate="one_to_one")
        require(len(pair) == EXPECTED_EVAL_RACES and pair.notna().all().all(), f"axis paired keys mismatch {left}-{right}")
        delta = pair[f"selected_hit_top3_{left}"].astype(np.float64) - pair[f"selected_hit_top3_{right}"].astype(np.float64)
        sums = pd.DataFrame({"date": pair.race_date.astype(str), "delta": delta}).groupby("date").delta.sum().reindex(dates, fill_value=0).to_numpy(float)
        counts = pd.DataFrame({"date": pair.race_date.astype(str), "delta": delta}).groupby("date").delta.count().reindex(dates, fill_value=0).to_numpy(float)
        draws = np.empty(schedule.shape[0], dtype=float)
        for ix, sample in enumerate(schedule):
            mult = np.bincount(np.asarray(sample, dtype=np.int64), minlength=len(dates)).astype(float)
            denom = float(np.dot(mult, counts))
            require(denom > 0, "empty axis bootstrap sample")
            draws[ix] = float(np.dot(mult, sums) / denom)
        low, high = np.quantile(draws, [0.025, 0.975], method="linear")
        boot.append({"comparison": f"{left}_minus_{right}", "races": len(pair),
                     "hit_rate_difference": float(delta.mean()),
                     "hit_rate_difference_ci95": [float(low), float(high)],
                     "date_bootstrap_draws": len(draws), "schedule_sha256": BOOTSTRAP_SHA256,
                     "date_inventory_sha256": DATE_INVENTORY_SHA256})
    return pd.DataFrame(summary), pd.DataFrame(boot)


def _read_f1_calibration(model_rows: pd.DataFrame) -> dict[int, pd.DataFrame]:
    result: dict[int, pd.DataFrame] = {}
    for year in YEARS:
        raw = pd.read_parquet(F1_CAL[year])
        target = model_rows.loc[model_rows.year.eq(year - 1),
                                ["api_record_id", "race_id", "race_date", "year", "horse_number", "field_n", "finish_position"]]
        require(len(raw) == len(target) and raw.api_record_id.is_unique, f"calibration raw score rows changed for {year}")
        join = target.merge(raw, on="api_record_id", how="outer", validate="one_to_one", indicator=True)
        require(join._merge.eq("both").all(), f"calibration score key set changed for {year}")
        result[year] = join.drop(columns="_merge")
    return result


def _model_receipt_rows(fits: Mapping[tuple[str, int], Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{**meta, "arm": arm, "year": year} for (arm, year), meta in fits.items()]


def run_fit_evaluate() -> dict[str, Any]:
    authorized = _validate_approval()
    started = datetime.now(timezone.utc).isoformat()
    _write_json_once(OUTPUTS / "execution_claim.json", {
        "status": "RUN_CLAIMED_NO_RETRY", "scope": "fit_evaluate", "started_at_utc": started,
        "approval_sha256": authorized["approval_sha256"],
        "code_bundle_sha256": authorized["hashes"]["code_bundle_sha256"], "permitted_runs": 1,
    })
    print(json.dumps({"phase": "fit_evaluate_started", "started_at_utc": started,
                      "approval_sha256": authorized["approval_sha256"]}), flush=True)
    start_clock = time.monotonic()
    model_rows, _state, frozen = load_frozen_frames()
    f1_info = _validate_f1_meta_sources()
    feature_cols = f1_info["features"]
    categorical_columns = f1_info["categorical_columns"]
    math_engine = _load_math_engine()
    reference_parameters = read_json(REFERENCE_PARAMETERS)
    r_scores, r_temperatures = _load_r_scores(model_rows, reference_parameters)
    calibration_data = _read_f1_calibration(model_rows)

    score_records: list[dict[str, Any]] = []
    fits: dict[tuple[str, int], dict[str, Any]] = {}
    calibration_temperatures: dict[tuple[str, int], float] = {("R", year): r_temperatures[year] for year in YEARS}
    for arm in ("C", "S"):
        for year in YEARS:
            model, meta, cal_scores, eval_scores = _fit_arm_year(
                model_rows, arm=arm, year=year, base_columns=feature_cols,
                categorical_vocab=_fold_vocabulary(model_rows, year, categorical_columns),
            )
            model_path = _ensure_experiment_path(MODELS / f"{arm}_{year}.txt")
            require(not model_path.exists(), f"refusing to overwrite model {model_path.name}")
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model_payload = model.model_to_string(num_iteration=model.current_iteration()).encode("utf-8")
            with model_path.open("xb") as stream:
                stream.write(model_payload)
                stream.flush()
                os.fsync(stream.fileno())
            meta["model_sha256"] = sha256_file(model_path)
            for role, mask, raw_scores in (("calibration", model_rows.year.eq(year - 1), cal_scores),
                                            ("evaluation", model_rows.year.eq(year) & model_rows.race_date.le(EXPECTED_EVAL_END), eval_scores)):
                part = model_rows.loc[mask, ["api_record_id", "race_id", "race_date", "year", "horse_number",
                                             "field_n", "finish_position"]].copy().reset_index(drop=True)
                require(len(part) == len(raw_scores), f"{arm}/{year} {role} prediction coverage mismatch")
                for row, value in zip(part.itertuples(index=False), raw_scores):
                    score_records.append({"arm": arm, "year": year, "role": role,
                                          "api_record_id": int(row.api_record_id), "race_id": str(row.race_id),
                                          "race_date": str(row.race_date), "horse_number": int(row.horse_number),
                                          "field_n": int(row.field_n), "score": float(value)})
            cal_frame = model_rows.loc[model_rows.year.eq(year - 1)].copy().reset_index(drop=True)
            temp_fit = _fit_temperature(_race_records(cal_frame, cal_scores), math_engine)
            calibration_temperatures[(arm, year)] = float(temp_fit["temperature"])
            meta["temperature_fit"] = temp_fit
            meta["categorical_vocabulary_sha256"] = hashlib.sha256(
                json.dumps(meta["categorical_vocabulary"], ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            fits[(arm, year)] = meta
            print(json.dumps({"phase": "annual_model_complete", "arm": arm, "year": year,
                              "best_iteration": meta["best_iteration"], "temperature": temp_fit["temperature"],
                              "elapsed_seconds": round(time.monotonic() - start_clock, 2)}), flush=True)
    cs_scores = pd.DataFrame(score_records)
    require(cs_scores.api_record_id.notna().all() and not cs_scores.duplicated(["arm", "year", "role", "api_record_id"]).any(),
            "candidate OOS score ledger has duplicate or missing keys")
    evaluation_scores = cs_scores.loc[cs_scores.role.eq("evaluation")]
    require((len(evaluation_scores), evaluation_scores.arm.nunique(), evaluation_scores.year.nunique()) ==
            (2 * EXPECTED_EVAL_RUNNERS, 2, 3), "candidate evaluation OOS score row count mismatch")
    evaluated = _evaluate_all(model_rows, evaluation_scores, r_scores, calibration_temperatures,
                              math_engine, np.load(BOOTSTRAP, allow_pickle=False))

    outputs: dict[str, pd.DataFrame] = {
        "candidate_oos_scores.parquet": cs_scores,
        **{f"{name}.parquet": value for name, value in evaluated.items() if isinstance(value, pd.DataFrame)},
    }
    for name, frame in outputs.items():
        _write_frame_once(OUTPUTS / name, frame)
    parameters = {
        "study": "20261022_tb_state_transfer_v1", "contract_sha256": sha256_file(CONTRACT),
        "arms": {"R": "reused F1_STYLE6 raw scores + prior same-vintage PL temperature",
                 "C": "same 30 F1_STYLE6 inputs, binary Top3 fresh annual fit",
                 "S": "same 30 inputs plus 10 contracted TB rank/distance state inputs"},
        "features": {"C": feature_cols, "S": feature_cols + list(STATE_COLUMNS),
                     "categorical_columns": categorical_columns,
                     "train_vocabulary_by_year": frozen["category_vocabulary_by_year"]},
        "lightgbm_parameters": LGBM_PARAMS, "annual_splits": evaluated.get("annual_splits", {
            str(year): {"initial_train": [2017, year - 3], "early_stop": year - 2,
                        "refit_through": year - 2, "calibration": year - 1, "evaluation": year}
            for year in YEARS}),
        "models": _model_receipt_rows(fits),
        "R_temperatures_reused": {str(year): {"temperature": r_temperatures[year],
                                             "source": "prior dynamic_ability_pace_v1 R_reference_fits"}
                                  for year in YEARS},
        "PL_temperature_bounds": [0.35, 4.0],
        "selection": "top ticket(s) p >= current maximum−1e-12, then horse-number lexicographic; probability map unchanged",
        "pool_minimums": POOL_MIN_STARTERS,
        "reliability_weighting": "pooled ticket-event-count; proper race loss is race-equal",
        "input_hashes": authorized["hashes"], "frozen_frame_receipt": frozen,
        "environment": {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__,
                        "pandas": pd.__version__, "lightgbm": lgb.__version__, "scipy": scipy.__version__},
        "fit_budget": {"final_models": 6, "LightGBM_train_calls": 12,
                       "C_S_PL_temperature_optimizations": 6, "R_temperature_optimizations": 0},
        "R_reference_temperature_optimizations_reused": 3,
    }
    _write_json_once(OUTPUTS / "parameters.json", parameters)
    report = evaluated["evaluation_report"]
    _write_json_once(OUTPUTS / "report.json", report)
    elapsed = time.monotonic() - start_clock
    artifact_rows = []
    for path in sorted([*OUTPUTS.glob("*"), *MODELS.glob("*")], key=lambda p: p.name):
        if path.is_file():
            artifact_rows.append({"path": path.relative_to(PROJECT).as_posix(),
                                  "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    receipt = {
        "status": "COMPLETED_RESEARCH_ONLY", "approval_sha256": authorized["approval_sha256"],
        "approved_hashes": authorized["hashes"], "execution_started_at_utc": started,
        "execution_completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": elapsed, "fit_counts": parameters["fit_budget"],
        "evaluation_races": EXPECTED_EVAL_RACES, "evaluation_runners": EXPECTED_EVAL_RUNNERS,
        "models": 6, "study_bytes_after_receipt": 0, "maximum_new_study_bytes": MAX_STUDY_BYTES,
        "artifacts": artifact_rows, "production_changed": False, "database_changed": False,
    }
    receipt_path = OUTPUTS / "fit_run_receipt.json"
    base_bytes = _study_bytes()
    payload = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2,
                         allow_nan=False, default=_json_default).encode("utf-8") + b"\n"
    for _ in range(8):
        expected_size = base_bytes + len(payload)
        if receipt["study_bytes_after_receipt"] == expected_size:
            break
        receipt["study_bytes_after_receipt"] = expected_size
        payload = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2,
                             allow_nan=False, default=_json_default).encode("utf-8") + b"\n"
    require(base_bytes + len(payload) < MAX_STUDY_BYTES, "new study artifacts exceed 100 MB")
    with _ensure_experiment_path(receipt_path).open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    require(_study_bytes() == receipt["study_bytes_after_receipt"], "final study byte count receipt mismatch")
    print(json.dumps({"phase": "fit_evaluate_complete", "elapsed_seconds": elapsed,
                      "study_bytes": _study_bytes(), "gate": report}, ensure_ascii=False, indent=2), flush=True)
    return receipt


def run_synthetic_checks() -> dict[str, Any]:
    path = EXPERIMENT / "test_state_transfer.py"
    require(path.is_file(), "synthetic test file is missing")
    spec = importlib.util.spec_from_file_location("tb_state_transfer_tests", path)
    require(spec is not None and spec.loader is not None, "cannot load synthetic checks")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.run_tests(_load_math_engine(), sys.modules[__name__])
    require(result.get("status") == "PASS_SYNTHETIC", "synthetic checks failed")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--synthetic-checks", action="store_true", help="run only synthetic checks")
    actions.add_argument("--source-preflight", action="store_true", help="validate frozen sources/keys without fit or outcome metrics")
    actions.add_argument("--run", action="store_true", help="execute the single hash-bound approved fit/evaluation run")
    args = parser.parse_args()
    if args.synthetic_checks:
        run_synthetic_checks()
    elif args.source_preflight:
        source_preflight()
    elif args.run:
        run_fit_evaluate()


if __name__ == "__main__":
    main()
