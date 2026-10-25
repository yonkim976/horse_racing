#!/usr/bin/env python3
"""One-run, approval-gated S40 versus S43 entry-conditions experiment.

Preparation commands are read-only with respect to sealed studies. The source
preflight checks the auditor-owned thin feature table but never fits a model,
constructs Q distributions, or calculates candidate outcome metrics. The run
path requires a code/input-hash-bound supervisor receipt and writes only below
this experiment directory.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import platform
import shutil
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

from entry_input_contract import FEATURE_COLUMNS, validate_audited_inputs


PROJECT = Path(__file__).resolve().parents[4]
STUDY = PROJECT / "jeju/research/20261024_s_entry_conditions_v1"
EXPERIMENT = STUDY / "experiment"
OUTPUTS = EXPERIMENT / "outputs"
MODELS = EXPERIMENT / "models"
PLAN = EXPERIMENT / "PLAN.md"
CONTRACT = STUDY / "supervisor/DESIGN_CONTRACT.md"
APPROVAL = STUDY / "supervisor/ENTRY_CONDITIONS_EXECUTION_APPROVAL.json"
SOURCE_CONTRACT = STUDY / "audit/source_contract.json"
AUDIT_FEATURES = STUDY / "audit/entry_condition_inputs.parquet"

S_STUDY = PROJECT / "jeju/research/20261022_tb_state_transfer_v1"
S_EXPERIMENT = S_STUDY / "experiment"
S_INPUTS = S_STUDY / "inputs"
S_OUTPUTS = S_EXPERIMENT / "outputs"
S_MODELS = S_EXPERIMENT / "models"
S_RECEIPT = S_OUTPUTS / "fit_run_receipt.json"
S_PARAMETERS = S_OUTPUTS / "parameters.json"
S_SCORES = S_OUTPUTS / "candidate_oos_scores.parquet"
S_METRICS = S_OUTPUTS / "race_pool_metrics.parquet"
S_SELECTIONS = S_OUTPUTS / "selected_ticket_ledger.parquet"
S_MARGINALS = S_OUTPUTS / "evaluation_runner_marginals.parquet"
S_AXIS = S_OUTPUTS / "win_axis_ledger.parquet"
S_PAIR_DIAGNOSTICS = S_OUTPUTS / "pair_selection_diagnostics.parquet"
S_QUARANTINE = S_OUTPUTS / "evaluation_quarantine.parquet"
S_PIPELINE = S_EXPERIMENT / "state_transfer.py"
S_FINAL_MANIFEST = S_STUDY / "FINAL_MANIFEST.json"
S_FINAL_MANIFEST_SHA256 = "86d0153e287f877add1b10c3172471cf5c3aac9f251890423cd7d97f75abba3a"
S_PIPELINE_BYTES = 90_034
S_PIPELINE_SHA256 = "963b2bcb574f3d49e539ae4e944a8a2f8f9bd769568d83018c2dcbcd2fa0623c"

BOOTSTRAP = PROJECT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT = PROJECT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
RULES = PROJECT / "jeju/research/20261022_joint_wager_baseline_v1/rules_contract/rules_contract.json"

YEARS = (2024, 2025, 2026)
ARMS = ("S", "E")
POOL_ORDER = ("WIN", "PLC", "QNL", "EXA", "QPL", "TLA", "TRI")
POOL_MIN_STARTERS = {"WIN": 2, "PLC": 5, "QNL": 3, "EXA": 3, "QPL": 5, "TLA": 4, "TRI": 4}
BIN_EDGES = np.asarray(
    [0.0, 0.00001, 0.00005, 0.0001, 0.00025, 0.0005, 0.001, 0.0025,
     0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0], dtype=np.float64
)
EXPECTED_RUNNERS = 52_155
EXPECTED_RACES = 5_206
EXPECTED_EVAL_RUNNERS = 17_412
EXPECTED_EVAL_RACES = 1_779
EXPECTED_EVAL_DATES = 269
EXPECTED_PLC_RACES = 1_743
EXPECTED_EVAL_END = "2026-09-19"
MAX_STUDY_BYTES = 40_000_000
FINAL_OUTPUT_RESERVE_BYTES = 1_000_000
EXTRA_OUTPUT_RESERVE_BYTES = 5_000_000
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


def _write_once(path: Path, payload: bytes) -> None:
    resolved = Path(path).resolve(strict=False)
    require(resolved.is_relative_to(EXPERIMENT.resolve()), f"write target escapes experiment: {path}")
    require(not resolved.exists(), f"refusing to overwrite: {resolved}")
    reserve = 0 if resolved.name == "fit_run_receipt.json" else FINAL_OUTPUT_RESERVE_BYTES
    require(_study_bytes() + len(payload) + reserve <= MAX_STUDY_BYTES,
            "write would exceed the 40 MB study budget or consume the final-report reserve")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with resolved.open("xb") as stream:
            created = True
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        require(_study_bytes() <= MAX_STUDY_BYTES,
                "concurrent study writes exceeded the 40 MB budget")
    except BaseException:
        if created and resolved.exists():
            resolved.unlink()
        raise


def _write_json_once(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                         allow_nan=False, default=_json_default).encode("utf-8") + b"\n"
    _write_once(path, payload)


def _write_frame_once(path: Path, frame: pd.DataFrame) -> None:
    resolved = Path(path).resolve(strict=False)
    require(resolved.is_relative_to(EXPERIMENT.resolve()), f"write target escapes experiment: {path}")
    require(not resolved.exists(), f"refusing to overwrite: {resolved}")
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False, compression="zstd")
    _write_once(resolved, buffer.getvalue())


def _study_bytes() -> int:
    return sum(p.stat().st_size for p in STUDY.rglob("*") if p.is_file() and not p.is_symlink())


def _tree_sha256(root: Path) -> str:
    root = Path(root).resolve(strict=True)
    digest = hashlib.sha256()
    paths = sorted((p for p in root.rglob("*") if p.is_file() and not p.is_symlink()),
                   key=lambda item: item.relative_to(root).as_posix())
    for path in paths:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def _verify_s40_manifest_file(path: Path) -> dict[str, Any]:
    require(S_FINAL_MANIFEST.is_file() and not S_FINAL_MANIFEST.is_symlink(),
            "sealed S40 final manifest is absent or non-regular")
    require(sha256_file(S_FINAL_MANIFEST) == S_FINAL_MANIFEST_SHA256,
            "sealed S40 final manifest hash differs from the pinned study")
    manifest = read_json(S_FINAL_MANIFEST)
    relative = path.relative_to(PROJECT).as_posix()
    entries = [item for item in manifest.get("files_excluding_manifest", [])
               if item.get("path") == relative]
    require(len(entries) == 1, f"sealed S40 manifest does not uniquely list {relative}")
    expected = entries[0]
    require(path.is_file() and not path.is_symlink() and
            path.stat().st_size == int(expected.get("bytes", -1)) and
            sha256_file(path) == expected.get("sha256"),
            f"sealed S40 manifest file bytes/SHA mismatch: {relative}")
    return expected


def _load_sealed_s_module() -> types.ModuleType:
    pipeline_entry = _verify_s40_manifest_file(S_PIPELINE)
    require(int(pipeline_entry["bytes"]) == S_PIPELINE_BYTES and
            pipeline_entry["sha256"] == S_PIPELINE_SHA256 and
            S_PIPELINE.stat().st_size == S_PIPELINE_BYTES and sha256_file(S_PIPELINE) == S_PIPELINE_SHA256,
            "sealed S40 pipeline differs from its pinned size/SHA")
    before = _tree_sha256(S_EXPERIMENT)
    source_bytes = S_PIPELINE.read_bytes()
    name = "sealed_tb_state_transfer_readonly"
    module = types.ModuleType(name)
    module.__file__ = str(S_PIPELINE)
    module.__package__ = ""
    sys.modules[name] = module
    exec(compile(source_bytes, str(S_PIPELINE), "exec", dont_inherit=True), module.__dict__)
    after = _tree_sha256(S_EXPERIMENT)
    require(before == after, "loading sealed S40 code changed its experiment tree")
    module.__tree_sha256__ = after
    return module


def code_bundle_sha256() -> str:
    paths = (EXPERIMENT / "entry_pipeline.py", EXPERIMENT / "entry_input_contract.py",
             EXPERIMENT / "test_entry_input_contract.py")
    digest = hashlib.sha256()
    for path in paths:
        require(path.is_file(), f"missing code bundle component: {path.name}")
        relative = path.relative_to(PROJECT).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def _runtime_environment() -> dict[str, str]:
    return {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__,
            "pandas": pd.__version__, "lightgbm": lgb.__version__, "scipy": scipy.__version__}


def _assert_runtime_environment(expected: Mapping[str, Any]) -> dict[str, str]:
    current = _runtime_environment()
    for key, value in current.items():
        require(expected.get(key) == value,
                f"runtime environment differs from sealed S40 parameters: {key}")
    return current


def _s40_assets() -> dict[str, Any]:
    for path in (S_RECEIPT, S_PARAMETERS, S_SCORES, S_METRICS, S_SELECTIONS,
                 S_MARGINALS, S_AXIS, S_PAIR_DIAGNOSTICS, S_QUARANTINE):
        _verify_s40_manifest_file(path)
    receipt = read_json(S_RECEIPT)
    params = read_json(S_PARAMETERS)
    require(receipt.get("status") == "COMPLETED_RESEARCH_ONLY" and
            receipt.get("production_changed") is False and receipt.get("database_changed") is False,
            "sealed S40 receipt is missing or does not describe the completed research-only run")
    s_models = {year: S_MODELS / f"S_{year}.txt" for year in YEARS}
    model_meta = {(int(row["year"]), str(row["arm"])): row for row in params.get("models", [])}
    require(all((year, "S") in model_meta for year in YEARS), "S40 temperature/model metadata incomplete")
    for year, path in s_models.items():
        require(path.is_file() and sha256_file(path) == model_meta[(year, "S")].get("model_sha256"),
                f"sealed S40 model hash mismatch for {year}")
    require(S_SCORES.is_file() and S_METRICS.is_file() and S_SELECTIONS.is_file() and
            S_MARGINALS.is_file() and S_AXIS.is_file() and S_PAIR_DIAGNOSTICS.is_file() and
            S_QUARANTINE.is_file(), "sealed S40 replay/evaluation assets are incomplete")
    return {
        "receipt_sha256": sha256_file(S_RECEIPT), "parameters_sha256": sha256_file(S_PARAMETERS),
        "scores_sha256": sha256_file(S_SCORES), "metrics_sha256": sha256_file(S_METRICS),
        "selections_sha256": sha256_file(S_SELECTIONS), "marginals_sha256": sha256_file(S_MARGINALS),
        "axis_sha256": sha256_file(S_AXIS), "pair_diagnostics_sha256": sha256_file(S_PAIR_DIAGNOSTICS),
        "quarantine_sha256": sha256_file(S_QUARANTINE), "models": {
            str(year): {"path": path.relative_to(PROJECT).as_posix(), "sha256": sha256_file(path),
                        "temperature": float(model_meta[(year, "S")]["temperature_fit"]["temperature"]),
                        "best_iteration": int(model_meta[(year, "S")]["best_iteration"])}
            for year, path in s_models.items()},
        "sealed_s_experiment_tree_sha256": _tree_sha256(S_EXPERIMENT),
    }


def _project_run_storage_bytes() -> dict[str, int]:
    manifest = read_json(S_FINAL_MANIFEST)
    output_prefix = S_OUTPUTS.relative_to(PROJECT).as_posix() + "/"
    old_output_bytes = sum(int(item["bytes"]) for item in manifest.get("files_excluding_manifest", [])
                           if str(item.get("path", "")).startswith(output_prefix))
    # The manifest is the size authority for the three sealed S models.
    model_prefix = S_MODELS.relative_to(PROJECT).as_posix() + "/S_"
    old_model_bytes = sum(int(item["bytes"]) for item in manifest.get("files_excluding_manifest", [])
                          if str(item.get("path", "")).startswith(model_prefix) and
                          str(item.get("path", "")).endswith(".txt"))
    # New score/evaluation outputs should be comparable to S40's output bundle;
    # reserve 50% overhead plus 2x model bytes, extra diagnostics, and final metadata.
    projected_generated = int(math.ceil(1.5 * old_output_bytes)) + 2 * old_model_bytes + \
        EXTRA_OUTPUT_RESERVE_BYTES + FINAL_OUTPUT_RESERVE_BYTES
    return {"sealed_output_bundle_bytes": old_output_bytes, "sealed_model_bytes": old_model_bytes,
            "projected_generated_bytes": projected_generated,
            "projected_total_study_bytes": _study_bytes() + projected_generated}


def _source_contract_inputs(s_module: types.ModuleType) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    for path, root in ((SOURCE_CONTRACT, STUDY / "audit"), (AUDIT_FEATURES, STUDY / "audit")):
        require(path.is_file() and not path.is_symlink(), f"missing/non-regular auditor input: {path.name}")
        require(path.resolve(strict=True).is_relative_to(root.resolve(strict=True)),
                f"auditor input escapes the study audit folder: {path.name}")
    require(SOURCE_CONTRACT.is_file() and AUDIT_FEATURES.is_file(),
            "auditor-owned source contract or thin input table is absent")
    contract = read_json(SOURCE_CONTRACT)
    audit_meta = contract.get("input_artifact", contract.get("feature_artifact", {}))
    require(isinstance(audit_meta, Mapping), "source contract lacks thin input artifact metadata")
    require(audit_meta.get("path") == AUDIT_FEATURES.relative_to(PROJECT).as_posix() and
            audit_meta.get("format") == "parquet" and audit_meta.get("compression") == "zstd" and
            int(audit_meta.get("rows", -1)) == EXPECTED_RUNNERS and
            int(audit_meta.get("races", -1)) == EXPECTED_RACES,
            "auditor thin input path/format/compression/row inventory differs from the pinned contract")
    expected_sha = audit_meta.get("sha256")
    expected_bytes = audit_meta.get("bytes")
    expected_rows = audit_meta.get("rows")
    require(expected_sha == sha256_file(AUDIT_FEATURES) and int(expected_bytes or -1) == AUDIT_FEATURES.stat().st_size,
            "auditor thin input SHA/size mismatch")
    require(int(expected_rows or -1) == EXPECTED_RUNNERS, "auditor thin input expected row count mismatch")
    s_rows, _state, frozen = s_module.load_frozen_frames()
    require((len(s_rows), s_rows.race_id.nunique()) == (EXPECTED_RUNNERS, EXPECTED_RACES),
            "sealed S40 target roster changed")
    audit = pd.read_parquet(AUDIT_FEATURES)
    model_only, validation_receipt = validate_audited_inputs(s_rows, audit, contract)
    model_rows = s_rows.merge(model_only, on=["api_record_id", "race_id"], how="left",
                              validate="one_to_one", indicator=True)
    require(model_rows._merge.eq("both").all() and len(model_rows) == EXPECTED_RUNNERS,
            "validated entry inputs do not join to the exact S40 target roster")
    model_rows = model_rows.drop(columns="_merge")
    model_rows = model_rows.sort_values(["race_date", "race_id", "horse_number"], kind="mergesort").reset_index(drop=True)
    return model_rows, {"source_contract": contract, "source_contract_sha256": sha256_file(SOURCE_CONTRACT),
                        "audit_features_sha256": sha256_file(AUDIT_FEATURES),
                        "audit_features_bytes": AUDIT_FEATURES.stat().st_size,
                        "audit_validation": validation_receipt, "s40_frozen_receipt": frozen}, validation_receipt


def _validate_saved_s_scores(model_rows: pd.DataFrame) -> tuple[pd.DataFrame, dict[int, float]]:
    params = read_json(S_PARAMETERS)
    rows = pd.read_parquet(S_SCORES)
    required = ["arm", "year", "role", "api_record_id", "race_id", "race_date", "horse_number", "field_n", "score"]
    require(list(rows.columns) == required, "sealed S40 OOS score schema changed")
    rows = rows.loc[rows.arm.eq("S")].copy()
    require(not rows.duplicated(["year", "role", "api_record_id"]).any(),
            "sealed S40 score ledger has duplicate vintage/role/runner keys")
    temperatures: dict[int, float] = {}
    for year in YEARS:
        meta = next(item for item in params["models"] if item["arm"] == "S" and int(item["year"]) == year)
        temperatures[year] = float(meta["temperature_fit"]["temperature"])
        for role, year_value in (("calibration", year - 1), ("evaluation", year)):
            saved = rows.loc[rows.year.eq(year) & rows.role.eq(role)].copy()
            mask = model_rows.year.eq(year_value)
            if role == "evaluation":
                mask &= model_rows.race_date.le(EXPECTED_EVAL_END)
            target = model_rows.loc[mask, ["api_record_id", "race_id", "race_date", "horse_number", "field_n"]]
            joined = target.merge(saved[["api_record_id", "race_id", "race_date", "horse_number", "field_n", "score"]],
                                  on="api_record_id", how="outer", suffixes=("_target", "_saved"),
                                  validate="one_to_one", indicator=True)
            require(len(joined) == len(target) == len(saved) and joined._merge.eq("both").all(),
                    f"sealed S40 {role} score key inventory changed for {year}")
            for column in ("race_id", "race_date", "horse_number", "field_n"):
                require(joined[f"{column}_target"].eq(joined[f"{column}_saved"]).all(),
                        f"sealed S40 {role} score {column} mismatch for {year}")
            require(np.isfinite(joined.score.to_numpy(dtype=np.float64)).all(),
                    f"sealed S40 {role} raw scores contain non-finite values for {year}")
    return rows, temperatures


def _validate_quarantine_and_bootstrap(model_rows: pd.DataFrame) -> dict[str, Any]:
    schedule = np.load(BOOTSTRAP, mmap_mode="r", allow_pickle=False)
    schedule_hash = sha256_file(BOOTSTRAP)
    require(schedule.shape == (2000, EXPECTED_EVAL_DATES) and
            np.issubdtype(schedule.dtype, np.integer) and int(schedule.min()) >= 0 and
            int(schedule.max()) < EXPECTED_EVAL_DATES, "fixed date bootstrap schedule changed")
    receipt = read_json(BOOTSTRAP_RECEIPT)
    dates = sorted(model_rows.loc[model_rows.race_date.between("2024-01-01", EXPECTED_EVAL_END),
                                  "race_date"].astype(str).unique().tolist())
    date_hash = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(len(dates) == EXPECTED_EVAL_DATES and receipt.get("draws") == 2000 and
            receipt.get("dates_per_draw") == EXPECTED_EVAL_DATES and
            receipt.get("date_inventory_sha256") == date_hash and
            receipt.get("schedule_sha256") == schedule_hash,
            "fixed date bootstrap receipt/date inventory mismatch")
    old_quarantine = pd.read_parquet(S_QUARANTINE)
    require(list(old_quarantine.columns) == ["race_id", "race_date", "field_n", "pool", "reason"] and
            len(old_quarantine) == EXPECTED_EVAL_RACES - EXPECTED_PLC_RACES,
            "sealed S40 PLC quarantine schema/count changed")
    eval_rows = model_rows.loc[model_rows.race_date.between("2024-01-01", EXPECTED_EVAL_END)]
    races = eval_rows.groupby("race_id", sort=True).agg(
        race_date=("race_date", "first"), field_n=("field_n", "first"), n=("api_record_id", "size"),
    ).reset_index()
    actual_unknown = races.loc[races.field_n.eq(7), ["race_id", "race_date", "field_n"]].copy()
    quarantine_keys = old_quarantine.loc[:, ["race_id", "race_date", "field_n"]].sort_values("race_id").reset_index(drop=True)
    actual_unknown = actual_unknown.sort_values("race_id").reset_index(drop=True)
    require(actual_unknown.equals(quarantine_keys), "reconstructed PLC quarantine keys differ from sealed S40")
    require((len(eval_rows), len(races), races.race_date.nunique()) ==
            (EXPECTED_EVAL_RUNNERS, EXPECTED_EVAL_RACES, EXPECTED_EVAL_DATES),
            "fixed evaluation roster/date denominator changed")
    require((races.n == races.field_n).all(), "fixed evaluation race roster does not match field_n")
    counts = {pool: int((races.field_n >= minimum).sum()) for pool, minimum in POOL_MIN_STARTERS.items()}
    counts["PLC"] = int((races.field_n >= 8).sum())
    require(counts == {"WIN": 1779, "PLC": 1743, "QNL": 1779, "EXA": 1779,
                       "QPL": 1779, "TLA": 1779, "TRI": 1779},
            f"per-pool denominator drift: {counts}")
    return {"bootstrap_sha256": schedule_hash, "bootstrap_receipt_sha256": sha256_file(BOOTSTRAP_RECEIPT),
            "date_inventory_sha256": date_hash, "dates": dates,
            "pool_denominators": counts, "quarantine_keys_sha256": _key_digest(quarantine_keys, ["race_id"]),
            "quarantine_rows": len(quarantine_keys)}


def _key_digest(frame: pd.DataFrame, columns: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for row in frame.loc[:, list(columns)].sort_values(list(columns), kind="mergesort").itertuples(index=False, name=None):
        item = json.dumps([value.item() if isinstance(value, np.generic) else value for value in row],
                          ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        digest.update(len(item).to_bytes(8, "big"))
        digest.update(item)
    return digest.hexdigest()


def _source_hash_bundle(s_module: types.ModuleType, info: Mapping[str, Any], schedule_info: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "code_bundle_sha256": code_bundle_sha256(), "plan_sha256": sha256_file(PLAN),
        "design_contract_sha256": sha256_file(CONTRACT),
        "source_contract_sha256": info["source_contract_sha256"],
        "audit_features_sha256": info["audit_features_sha256"],
        "s40_experiment_tree_sha256": s_module.__tree_sha256__,
        "s40_assets": _s40_assets(),
        "s40_features_sha256": info["s40_frozen_receipt"]["f1_features_sha256"],
        "s40_state_features_sha256": info["s40_frozen_receipt"]["state_features_sha256"],
        "s40_state_lineage_sha256": info["s40_frozen_receipt"]["state_lineage_sha256"],
        "rules_sha256": sha256_file(RULES),
        "bootstrap_sha256": schedule_info["bootstrap_sha256"],
        "bootstrap_receipt_sha256": schedule_info["bootstrap_receipt_sha256"],
    }


def source_preflight() -> dict[str, Any]:
    require(_study_bytes() < MAX_STUDY_BYTES, "study already exceeds 40 MB before execution")
    s_module = _load_sealed_s_module()
    saved_parameters = read_json(S_PARAMETERS)
    environment = _assert_runtime_environment(saved_parameters.get("environment", {}))
    model_rows, info, _ = _source_contract_inputs(s_module)
    s_scores, temperatures = _validate_saved_s_scores(model_rows)
    schedule_info = _validate_quarantine_and_bootstrap(model_rows)
    s_meta = _s40_assets()
    storage_projection = _project_run_storage_bytes()
    require(storage_projection["projected_total_study_bytes"] <= MAX_STUDY_BYTES,
            "conservative pre-run output/storage projection exceeds the 40 MB study budget")
    f1_info = s_module._validate_f1_meta_sources()
    # Verify that training vocabularies and model hyperparameters remain the exact S40 contract.
    require(saved_parameters.get("lightgbm_parameters") == LGBM_PARAMS,
            "entry candidate hyperparameters differ from the sealed S40 recipe")
    vocab_by_year: dict[str, Any] = {}
    for year in YEARS:
        vocab = s_module._fold_vocabulary(model_rows, year, f1_info["categorical_columns"])
        saved_s = next(row for row in saved_parameters["models"] if row["arm"] == "S" and int(row["year"]) == year)
        require(vocab == saved_s["categorical_vocabulary"], f"S40 train-only vocabulary mismatch for {year}")
        vocab_by_year[str(year)] = vocab
    model_features = saved_parameters["features"]["S"] + list(FEATURE_COLUMNS)
    require(len(model_features) == 43 and len(set(model_features)) == 43,
            "candidate must have exactly S40's 40 features plus the 3 contracted numeric inputs")
    hashes = _source_hash_bundle(s_module, info, schedule_info)
    report = {
        "status": "PASS_STRUCTURAL_PREFLIGHT_NO_FIT_OR_METRICS",
        "fitted": False, "candidate_probabilities_computed": False,
        "candidate_outcome_metrics_computed": False, "candidate_temperature_optimized": False,
        "source_contract": {
            "current_weight_source_type": info["source_contract"].get("current_weight_source_type"),
            "publication_time_status": info["source_contract"].get("publication_time_status"),
            "pre_race_availability_verified": info["audit_validation"]["pre_race_availability_verified"],
            "pre_race_availability_assumption": info["audit_validation"]["pre_race_availability_assumption"],
            "current_burden_nonmissing_rows": info["audit_validation"]["current_burden_nonmissing_rows"],
            "prior_actual_burden_nonmissing_rows": info["audit_validation"]["prior_burden_nonmissing_rows"],
            "burden_change_nonmissing_rows": info["audit_validation"]["burden_change_nonmissing_rows"],
            "declared_number_fraction_missing_rows": info["audit_validation"]["declared_number_fraction_missing_rows"],
        },
        "cohort": {"rows": EXPECTED_RUNNERS, "races": EXPECTED_RACES,
                   "evaluation_rows": EXPECTED_EVAL_RUNNERS, "evaluation_races": EXPECTED_EVAL_RACES,
                   "evaluation_dates": EXPECTED_EVAL_DATES},
        "arms": {"S": "sealed S40 raw scores and temperature; no refit",
                 "E": "S40 40 features plus exactly three audited numeric inputs"},
        "fit_scope": {"candidate_arm": "E", "final_models": 3, "LightGBM_train_calls": 6,
                      "candidate_PL_temperature_optimizations": 3,
                      "S40_fit_calls": 0, "S40_temperature_optimizations": 0,
                      "vintages": list(YEARS)},
        "features": {"E": model_features, "candidate_numeric_columns": list(FEATURE_COLUMNS),
                     "categorical_columns": list(f1_info["categorical_columns"]),
                     "train_only_vocabulary_by_year": vocab_by_year},
        "lightgbm_parameters": LGBM_PARAMS,
        "annual_splits": {str(year): {"initial_train_years": [2017, year - 3],
                                       "early_stop_year": year - 2,
                                       "refit_years": [2017, year - 2],
                                       "calibration_year": year - 1, "evaluation_year": year,
                                       "max_rounds": 800, "early_stopping_rounds": 25}
                          for year in YEARS},
        "pool_denominators": schedule_info["pool_denominators"],
        "plc_quarantine_rows": schedule_info["quarantine_rows"],
        "bootstrap_sha256": schedule_info["bootstrap_sha256"],
        "bootstrap_date_inventory_sha256": schedule_info["date_inventory_sha256"],
        "s40_baseline_temperatures": {str(year): temperatures[year] for year in YEARS},
        "s40_assets": s_meta, "audit_validation_receipt": info["audit_validation"],
        "hashes": hashes, "maximum_new_study_bytes": MAX_STUDY_BYTES,
        "study_bytes_before_run": _study_bytes(),
        "storage_projection": storage_projection,
        "free_bytes_before_run": shutil.disk_usage(PROJECT).free,
        "baseline_score_rows_read": len(s_scores),
        "runtime_environment": environment,
        "output_write_boundary": "all generated artifacts are exclusive-created beneath experiment/",
    }
    output = OUTPUTS / "source_preflight.json"
    _write_json_once(output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, default=_json_default), flush=True)
    return report


def _validate_approval() -> dict[str, Any]:
    require(APPROVAL.is_file(), "supervisor one-run fit/evaluation approval is absent")
    approval = read_json(APPROVAL)
    preflight_path = OUTPUTS / "source_preflight.json"
    require(preflight_path.is_file(), "source preflight receipt is absent")
    preflight = read_json(preflight_path)
    require(approval.get("status") == "PASS" and approval.get("scope") == "fit_evaluate" and
            int(approval.get("permitted_runs", 0)) == 1,
            "approval must authorize exactly one fit/evaluation run")
    require(preflight.get("status") == "PASS_STRUCTURAL_PREFLIGHT_NO_FIT_OR_METRICS" and
            preflight.get("fitted") is False and preflight.get("candidate_probabilities_computed") is False and
            preflight.get("candidate_outcome_metrics_computed") is False and
            preflight.get("candidate_temperature_optimized") is False,
            "preflight is not a verified no-fit/no-candidate-evaluation receipt")
    _assert_runtime_environment(preflight.get("runtime_environment", {}))
    s_module = _load_sealed_s_module()
    model_rows, info, _ = _source_contract_inputs(s_module)
    _validate_saved_s_scores(model_rows)
    schedule_info = _validate_quarantine_and_bootstrap(model_rows)
    actual_hashes = _source_hash_bundle(s_module, info, schedule_info)
    actual_hashes["preflight_sha256"] = sha256_file(preflight_path)
    preflight_hashes = preflight.get("hashes", {})
    require(isinstance(preflight_hashes, Mapping), "preflight hash map is invalid")
    for key, value in actual_hashes.items():
        if key == "preflight_sha256":
            continue
        require(preflight_hashes.get(key) == value, f"preflight input/code hash changed: {key}")
    approved_hashes = approval.get("hashes", {})
    require(isinstance(approved_hashes, Mapping), "approval hash map is invalid")
    for key, value in actual_hashes.items():
        require(approved_hashes.get(key) == value, f"approval hash mismatch: {key}")
    require(approval.get("candidate") == "S40_vs_E43" and
            approval.get("final_models") == 3 and approval.get("lightgbm_train_calls") == 6 and
            approval.get("temperature_optimizations") == 3,
            "approval candidate or fit budget mismatch")
    require(_study_bytes() < MAX_STUDY_BYTES, "study exceeds 40 MB before authorized run")
    storage_projection = _project_run_storage_bytes()
    require(storage_projection["projected_total_study_bytes"] <= MAX_STUDY_BYTES,
            "conservative output/storage projection exceeds 40 MB immediately before the one-run claim")
    require(not (OUTPUTS / "execution_claim.json").exists(), "run already claimed; retries are prohibited")
    require(not MODELS.exists() or not any(MODELS.iterdir()), "candidate model directory is not empty")
    require(set(p.name for p in OUTPUTS.iterdir()) == {"source_preflight.json"},
            "only no-fit source preflight may exist before the single run")
    return {"approval_sha256": sha256_file(APPROVAL), "hashes": actual_hashes,
            "preflight_sha256": actual_hashes["preflight_sha256"]}


def _transform_features(frame: pd.DataFrame, columns: Sequence[str],
                        vocabulary: Mapping[str, Sequence[str]]) -> pd.DataFrame:
    values = frame.loc[:, list(columns)].copy()
    for column, categories in vocabulary.items():
        if column in values.columns:
            values[column] = pd.Categorical(values[column].astype("string"), categories=list(categories))
    return values


def _race_records(frame: pd.DataFrame, scores: Sequence[float]) -> list[dict[str, Any]]:
    score_values = np.asarray(scores, dtype=np.float64)
    require(len(frame) == len(score_values) and np.isfinite(score_values).all(), "score vector does not match frame")
    tmp = frame[["race_id", "race_date", "year", "field_n", "horse_number", "finish_position"]].copy()
    tmp["__score"] = score_values
    records: list[dict[str, Any]] = []
    for race_id, group in tmp.groupby("race_id", sort=True):
        group = group.sort_values("horse_number", kind="mergesort")
        ranks = group.finish_position.to_numpy(dtype=np.int64)
        require(len(group) == int(group.field_n.iloc[0]) and sorted(ranks.tolist()) == list(range(1, len(group) + 1)),
                f"invalid ordered Top-3 calibration race {race_id}")
        records.append({"race_id": str(race_id), "race_date": str(group.race_date.iloc[0]),
                        "year": int(group.year.iloc[0]), "n": len(group),
                        "numbers": group.horse_number.to_numpy(dtype=np.int64), "ranks": ranks,
                        "scores": group["__score"].to_numpy(dtype=np.float64)})
    return records


def _fit_temperature(records: Sequence[Mapping[str, Any]], engine) -> dict[str, Any]:
    result = engine.fit_joint_temperature(records, bounds=(0.35, 4.0))
    require(math.isfinite(float(result["temperature"])) and 0.35 <= float(result["temperature"]) <= 4.0 and
            result.get("optimizer_success") is True and int(result.get("races", -1)) == len(records),
            "candidate joint PL temperature fit failed its contract")
    return result


def _fit_entry_year(frame: pd.DataFrame, *, year: int, columns: Sequence[str],
                    categorical_vocab: Mapping[str, Sequence[str]], s_module: types.ModuleType):
    require(len(columns) == 43 and len(set(columns)) == 43, "E must have exactly 43 model features")
    year_values = frame.year.to_numpy(dtype=np.int64)
    train_mask = (year_values >= 2017) & (year_values <= year - 3)
    valid_mask = year_values == year - 2
    cal_mask = year_values == year - 1
    eval_mask = (year_values == year) & (frame.race_date.to_numpy() <= EXPECTED_EVAL_END)
    require(all(mask.any() for mask in (train_mask, valid_mask, cal_mask, eval_mask)), f"empty E annual split {year}")
    for mask, role, expected_year in ((valid_mask, "early stop", year - 2),
                                      (cal_mask, "calibration", year - 1),
                                      (eval_mask, "evaluation", year)):
        require(set(year_values[mask].tolist()) == {expected_year}, f"E {role} vintage mismatch {year}")
    require(set(year_values[train_mask].tolist()) == set(range(2017, year - 2)),
            f"E initial training years mismatch {year}")
    x = _transform_features(frame, columns, categorical_vocab)
    target = (frame.finish_position.to_numpy(dtype=np.int64) <= 3).astype(np.int8)
    weights = 1.0 / frame.field_n.to_numpy(dtype=np.float64)
    require(np.isfinite(weights).all() and (weights > 0.0).all(), "invalid race-equal Top-3 runner weights")
    categories = [column for column in categorical_vocab if column in columns]

    def dataset(mask: np.ndarray) -> lgb.Dataset:
        return lgb.Dataset(x.loc[mask], label=target[mask], weight=weights[mask],
                           categorical_feature=categories, feature_name=list(columns), free_raw_data=False)

    initial = lgb.train(LGBM_PARAMS, dataset(train_mask), num_boost_round=800,
                        valid_sets=[dataset(valid_mask)], valid_names=["early_stop"],
                        callbacks=[lgb.early_stopping(25, verbose=False)])
    best_iteration = int(initial.best_iteration)
    require(best_iteration > 0, f"E early stopping returned no iteration for {year}")
    refit_mask = train_mask | valid_mask
    final = lgb.train(LGBM_PARAMS, dataset(refit_mask), num_boost_round=best_iteration)
    cal_scores = np.asarray(final.predict(x.loc[cal_mask], raw_score=True, num_threads=4), dtype=np.float64)
    eval_scores = np.asarray(final.predict(x.loc[eval_mask], raw_score=True, num_threads=4), dtype=np.float64)
    require(np.isfinite(cal_scores).all() and np.isfinite(eval_scores).all(), f"E raw scores are non-finite for {year}")
    meta = {
        "arm": "E", "year": int(year), "evaluation_year": int(year),
        "feature_count": 43, "feature_names": list(columns),
        "categorical_vocabulary": {key: list(value) for key, value in categorical_vocab.items()},
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
    require(s_module.LGBM_PARAMS == LGBM_PARAMS, "loaded S40 trainer settings drifted")
    return final, meta, cal_scores, eval_scores, cal_mask, eval_mask


def validate_oos_score_vintages(score_rows: pd.DataFrame, arm: str,
                                expected_calibration_rows: Mapping[int, int],
                                expected_evaluation_rows: Mapping[int, int]) -> None:
    """Check that ledger year is model vintage and role dates use the expected years."""
    required = {"arm", "year", "role", "api_record_id", "race_date"}
    require(required.issubset(score_rows.columns), "OOS score ledger vintage schema is incomplete")
    rows = score_rows.loc[score_rows.arm.eq(arm)].copy()
    vintages = set(int(value) for value in expected_calibration_rows)
    require(set(int(value) for value in expected_evaluation_rows) == vintages,
            f"{arm} expected calibration/evaluation vintage maps differ")
    require(set(pd.to_numeric(rows.year, errors="coerce").dropna().astype(int).unique()) == vintages,
            f"{arm} score ledger year values do not identify model vintages")
    require(not rows.duplicated(["year", "role", "api_record_id"]).any(),
            f"{arm} score ledger has duplicate vintage/role/runner keys")
    rows["__event_year"] = pd.to_datetime(rows.race_date, errors="coerce").dt.year
    require(rows.__event_year.notna().all(), f"{arm} score ledger has invalid race dates")
    for year in sorted(vintages):
        vintage = rows.loc[rows.year.eq(year)]
        calibration = vintage.loc[vintage.role.eq("calibration")]
        evaluation = vintage.loc[vintage.role.eq("evaluation")]
        require(len(calibration) == int(expected_calibration_rows[year]) and
                len(evaluation) == int(expected_evaluation_rows[year]),
                f"{arm} score vintage {year} role row counts differ")
        require(calibration.__event_year.eq(year - 1).all() and evaluation.__event_year.eq(year).all(),
                f"{arm} score vintage {year} role dates do not match calibration/evaluation years")
    require(set(rows.role.astype(str).unique()) == {"calibration", "evaluation"},
            f"{arm} score ledger has an unexpected role")


def _top_k_tickets(tickets: Mapping[tuple[int, ...], float], k: int) -> list[tuple[int, ...]]:
    require(k > 0 and len(tickets) >= k, "invalid top-k ticket request")
    remaining = dict(tickets)
    selected: list[tuple[int, ...]] = []
    for _ in range(k):
        best = max(float(value) for value in remaining.values())
        key = min(ticket for ticket, value in remaining.items() if float(value) >= best - 1e-12)
        selected.append(key)
        del remaining[key]
    return selected


def _pair_selection_diagnostic(record: Mapping[str, Any], scores: np.ndarray,
                               pool: str, selected: Sequence[tuple[int, ...]], engine) -> dict[str, Any]:
    chosen = [tuple(int(value) for value in ticket) for ticket in selected]
    counts = np.zeros(4, dtype=np.float64)
    for i, j, k, probability in engine.iter_pl_top3(scores):
        numbers = [int(record["numbers"][ix]) for ix in (i, j, k)]
        observed = ({tuple(sorted((numbers[0], numbers[1])))} if pool == "QNL" else
                    {tuple(sorted(pair)) for pair in ((numbers[0], numbers[1]),
                                                       (numbers[0], numbers[2]),
                                                       (numbers[1], numbers[2]))})
        counts[len(set(chosen).intersection(observed))] += float(probability)
    require(abs(float(counts.sum()) - 1.0) <= 3e-11, f"{pool} pair-selection probability mass mismatch")
    tickets = record["tickets"]
    truths = record["truths"]
    return {
        "selected_tickets_json": json.dumps([list(key) for key in chosen], separators=(",", ":")),
        "selected_probabilities_json": json.dumps([float(tickets[key]) for key in chosen], separators=(",", ":")),
        "selected_union_probability": float(counts[1:].sum()),
        "expected_hits": float(np.dot(np.arange(4, dtype=np.float64), counts)),
        "realized_hit_count": int(sum(ticket in truths for ticket in chosen)),
        "count_probability_0": float(counts[0]), "count_probability_1": float(counts[1]),
        "count_probability_2": float(counts[2]), "count_probability_3": float(counts[3]),
        "selected_ticket_count": len(chosen),
        "count_semantics": "number of selected unordered pairs present in actual ordered Top-3; QNL actual count is 0/1",
    }


def _mean_rows(metrics: pd.DataFrame, groupers: list[str]) -> pd.DataFrame:
    return metrics.groupby(groupers, sort=False).agg(
        races=("race_id", "nunique"), mean_race_nll=("race_nll", "mean"),
        mean_race_brier=("race_brier", "mean"), ticket_count=("ticket_count", "sum"),
        event_count=("event_count", "sum"),
    ).reset_index()


def _bootstrap_mean_difference(part: pd.DataFrame, schedule: np.ndarray, dates: Sequence[str],
                               value: str) -> tuple[np.ndarray, float, float]:
    day_sums = part.groupby("race_date", sort=True)[value].sum().reindex(dates, fill_value=0).to_numpy(np.float64)
    day_counts = part.groupby("race_date", sort=True)["race_id"].count().reindex(dates, fill_value=0).to_numpy(np.float64)
    draws = np.empty(schedule.shape[0], dtype=np.float64)
    for index, selection in enumerate(schedule):
        mult = np.bincount(np.asarray(selection, dtype=np.int64), minlength=len(dates)).astype(np.float64)
        denom = float(np.dot(mult, day_counts))
        require(denom > 0.0, "empty paired date-bootstrap draw")
        draws[index] = float(np.dot(mult, day_sums) / denom)
    lo, hi = np.quantile(draws, [0.025, 0.975], method="linear")
    return draws, float(lo), float(hi)


def _pair_selection_bootstrap(pair_rows: pd.DataFrame, schedule: np.ndarray,
                              dates: Sequence[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    summaries: list[dict[str, Any]] = []
    draw_rows: list[dict[str, Any]] = []
    schedule_hash = sha256_file(BOOTSTRAP)
    date_hash = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    metric_sources = {
        "hit_any": lambda frame: frame.realized_hit_count.gt(0).astype(np.float64),
        "realized_hit_count": lambda frame: frame.realized_hit_count.astype(np.float64),
        "expected_hits": lambda frame: frame.expected_hits.astype(np.float64),
        "selected_union_probability": lambda frame: frame.selected_union_probability.astype(np.float64),
    }
    for pool in ("QNL", "QPL"):
        for k in (1, 3):
            arm_frames = {
                arm: pair_rows.loc[pair_rows.arm.eq(arm) & pair_rows.pool.eq(pool) & pair_rows.k.eq(k)]
                .set_index("race_id") for arm in ARMS
            }
            for metric_name, getter in metric_sources.items():
                e_values = getter(arm_frames["E"])
                s_values = getter(arm_frames["S"])
                joined = pd.DataFrame({"race_date_E": arm_frames["E"].race_date,
                                       "race_date_S": arm_frames["S"].race_date,
                                       "value_E": e_values, "value_S": s_values},
                                      index=arm_frames["E"].index).join(
                                          arm_frames["S"][["race_date"]].rename(columns={"race_date": "race_date_S_check"}),
                                          how="outer", validate="one_to_one")
                require(len(joined) == EXPECTED_EVAL_RACES and joined.notna().all().all() and
                        joined.race_date_E.eq(joined.race_date_S).all() and
                        joined.race_date_E.eq(joined.race_date_S_check).all(),
                        f"paired date/row mismatch for {pool} k={k} {metric_name}")
                part = pd.DataFrame({"race_id": joined.index.astype(str),
                                     "race_date": joined.race_date_E.astype(str).to_numpy(),
                                     "delta": (joined.value_E - joined.value_S).to_numpy(dtype=np.float64)})
                draws, low, high = _bootstrap_mean_difference(part, schedule, dates, "delta")
                positive = int((part.delta > 0).sum())
                negative = int((part.delta < 0).sum())
                summaries.append({"comparison": "E_minus_S", "pool": pool, "k": k,
                                  "metric": metric_name, "races": len(part),
                                  "left_mean": float(joined.value_E.mean()),
                                  "right_mean": float(joined.value_S.mean()),
                                  "delta": float(part.delta.mean()),
                                  "ci95": [low, high], "gains": positive, "losses": negative,
                                  "ties": len(part) - positive - negative,
                                  "bootstrap_draws": len(draws), "schedule_sha256": schedule_hash,
                                  "date_inventory_sha256": date_hash, "descriptive_only": True})
                draw_rows.extend({"comparison": "E_minus_S", "pool": pool, "k": k,
                                  "metric": metric_name, "draw": index, "difference": float(value)}
                                 for index, value in enumerate(draws))
    return pd.DataFrame(summaries), pd.DataFrame(draw_rows)


def _compare_s_replay(metrics: pd.DataFrame, selections: pd.DataFrame, marginals: pd.DataFrame,
                      axis: pd.DataFrame, pair: pd.DataFrame) -> dict[str, float]:
    checks = (
        (S_METRICS, metrics, ["race_id", "pool", "race_nll", "race_brier"], "race metrics"),
        (S_SELECTIONS, selections, ["race_id", "pool", "selected_ticket_key", "selected_probability",
                                    "selected_hit", "realized_event_count", "realized_event_keys_json",
                                    "realized_event_probabilities_json"], "selected-ticket ledger"),
        (S_MARGINALS, marginals, ["race_id", "horse_number", "p_win", "p_exact2", "p_exact3", "p_top2", "p_top3"],
         "runner marginals"),
        (S_AXIS, axis, ["race_id", "selected_horse_number", "selected_probability", "selected_hit_top3"], "WIN axis"),
        (S_PAIR_DIAGNOSTICS, pair, ["race_id", "pool", "k", "selected_tickets_json", "selected_probabilities_json",
                                    "selected_union_probability", "expected_hits", "realized_hit_count",
                                    "count_probability_0", "count_probability_1", "count_probability_2",
                                    "count_probability_3"], "pair-selection diagnostics"),
    )
    errors: dict[str, float] = {}
    for path, current, columns, label in checks:
        old = pd.read_parquet(path)
        old = old.loc[old.arm.eq("S"), columns].copy()
        new = current.loc[current.arm.eq("S"), columns].copy()
        keys = [column for column in columns if column in ("race_id", "pool", "horse_number", "k")]
        if not keys:
            keys = ["race_id"]
        old = old.sort_values(keys, kind="mergesort").reset_index(drop=True)
        new = new.sort_values(keys, kind="mergesort").reset_index(drop=True)
        require(len(old) == len(new) and old[keys].equals(new[keys]), f"sealed S replay key/schema mismatch: {label}")
        numeric = [column for column in columns if pd.api.types.is_numeric_dtype(old[column]) and
                   not pd.api.types.is_bool_dtype(old[column])]
        error = 0.0
        for column in numeric:
            old_values = old[column].to_numpy(dtype=np.float64)
            new_values = new[column].to_numpy(dtype=np.float64)
            error = max(error, float(np.nanmax(np.abs(old_values - new_values))))
            require(np.allclose(old_values, new_values, atol=1e-12, rtol=0.0, equal_nan=True),
                    f"sealed S replay numeric mismatch: {label}/{column}")
        for column in set(columns) - set(numeric):
            require(old[column].astype(str).equals(new[column].astype(str)),
                    f"sealed S replay categorical mismatch: {label}/{column}")
        errors[label] = error
    return errors


def evaluate_scores(model_rows: pd.DataFrame, score_rows: pd.DataFrame,
                    temperatures: Mapping[tuple[str, int], float], engine,
                    schedule: np.ndarray) -> dict[str, Any]:
    eval_mask = model_rows.race_date.between("2024-01-01", EXPECTED_EVAL_END)
    target = model_rows.loc[eval_mask].copy()
    eval_scores = score_rows.loc[score_rows.role.eq("evaluation"),
                                 ["arm", "year", "api_record_id", "score"]]
    target_keys = target[["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
                          "field_n", "finish_position", "distance_m"]]
    scores = target_keys.merge(eval_scores, on=["year", "api_record_id"], how="left",
                               validate="one_to_many", indicator=True)
    require(scores._merge.eq("both").all() and len(scores) == EXPECTED_EVAL_RUNNERS * 2 and
            scores.score.notna().all() and scores.groupby("arm").api_record_id.nunique().to_dict() == {"E": EXPECTED_EVAL_RUNNERS,
                                                                                                    "S": EXPECTED_EVAL_RUNNERS},
            "S/E evaluation score keys do not cover the fixed roster")
    scores = scores.drop(columns="_merge")
    records_by_arm_race: dict[tuple[str, str], dict[str, Any]] = {}
    for arm, arm_rows in scores.groupby("arm", sort=True):
        require(arm in ARMS, f"unexpected score arm {arm}")
        for race_id, group in arm_rows.groupby("race_id", sort=True):
            group = group.sort_values("horse_number", kind="mergesort").reset_index(drop=True)
            require(len(group) == int(group.field_n.iloc[0]) and group.race_id.nunique() == 1 and
                    sorted(group.finish_position.astype(int).tolist()) == list(range(1, len(group) + 1)),
                    f"score/truth roster mismatch {arm}/{race_id}")
            records_by_arm_race[(arm, str(race_id))] = {
                "race_id": str(race_id), "race_date": str(group.race_date.iloc[0]),
                "year": int(group.year.iloc[0]), "n": len(group),
                "numbers": group.horse_number.to_numpy(dtype=np.int64),
                "ranks": group.finish_position.to_numpy(dtype=np.int64),
                "scores": group.score.to_numpy(dtype=np.float64), "runner_rows": group,
            }
    require(len(records_by_arm_race) == len(ARMS) * EXPECTED_EVAL_RACES,
            "S/E arm/race score inventory mismatch")

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
        year, race_date = int(base.year.iloc[0]), str(base.race_date.iloc[0])
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
            maps, marginal, full_mass = engine.probability_maps_from_scenarios([scaled], [1.0], record["numbers"], plc_top)
            require(abs(full_mass - 1.0) <= 3e-11, f"ordered Q mass mismatch: {arm}/{race_id}")
            truths_by_pool: dict[str, set[tuple[int, ...]]] = {}
            for pool in POOL_ORDER:
                if n < POOL_MIN_STARTERS[pool] or (pool == "PLC" and plc_top is None):
                    continue
                truths = engine.truth_ticket_keys(pool, record["numbers"], record["ranks"], plc_top)
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
                        index = min(max(int(np.searchsorted(BIN_EDGES, p, side="right") - 1), 0), len(BIN_EDGES) - 2)
                        observed = float(key in truths)
                        item = bins[(pool, arm, period, index)]
                        item[0] += 1.0
                        item[1] += p
                        item[2] += observed
                        item[3] += (p - observed) ** 2
            for ix, horse_number in enumerate(record["numbers"]):
                marginal_rows.append({"race_id": str(race_id), "race_date": race_date, "year": year,
                                      "horse_number": int(horse_number), "arm": arm,
                                      **{key: float(value[ix]) for key, value in marginal.items()}})
            win_probability = marginal["p_win"]
            maximum = float(win_probability.max())
            selected_ix = min(ix for ix, value in enumerate(win_probability) if float(value) >= maximum - 1e-12)
            axis_rows.append({"race_id": str(race_id), "race_date": race_date, "year": year, "arm": arm,
                              "selected_horse_number": int(record["numbers"][selected_ix]),
                              "selected_probability": float(win_probability[selected_ix]),
                              "selected_hit_top3": bool(record["ranks"][selected_ix] <= 3)})
            for pool in ("QNL", "QPL"):
                truths = truths_by_pool[pool]
                for k in (1, 3):
                    selected = _top_k_tickets(maps[pool], k)
                    diag = _pair_selection_diagnostic({"numbers": record["numbers"], "truths": truths,
                                                       "tickets": maps[pool]}, scaled, pool, selected, engine)
                    pair_rows.append({"race_id": str(race_id), "race_date": race_date, "year": year,
                                      "field_n": n, "arm": arm, "pool": pool, "k": k, **diag})

    metrics, selections = pd.DataFrame(metric_rows), pd.DataFrame(selection_rows)
    marginals, axis = pd.DataFrame(marginal_rows), pd.DataFrame(axis_rows)
    pair_diagnostics, contract_ledger = pd.DataFrame(pair_rows), pd.DataFrame(contract_rows)
    quarantine = pd.DataFrame(quarantine_rows, columns=["race_id", "race_date", "field_n", "pool", "reason"])
    require(len(metrics) == 2 * (6 * EXPECTED_EVAL_RACES + EXPECTED_PLC_RACES) and
            len(selections) == len(metrics) and len(marginals) == 2 * EXPECTED_EVAL_RUNNERS and
            len(axis) == 2 * EXPECTED_EVAL_RACES and len(pair_diagnostics) == 2 * EXPECTED_EVAL_RACES * 4,
            "S/E probability/evaluation ledger row count mismatch")
    saved_quarantine = pd.read_parquet(S_QUARANTINE).sort_values("race_id").reset_index(drop=True)
    require(quarantine.sort_values("race_id").reset_index(drop=True).equals(saved_quarantine),
            "recomputed PLC quarantine differs from the exact sealed S40 key set")
    for pool in POOL_ORDER:
        expected = EXPECTED_PLC_RACES if pool == "PLC" else EXPECTED_EVAL_RACES
        counts = metrics.loc[metrics.pool.eq(pool)].groupby("arm").race_id.nunique().to_dict()
        require(counts == {arm: expected for arm in ARMS}, f"per-arm {pool} denominator mismatch: {counts}")

    replay_errors = _compare_s_replay(metrics, selections, marginals, axis, pair_diagnostics)
    summary = _mean_rows(metrics, ["pool", "arm"])
    year_summary = _mean_rows(metrics, ["pool", "arm", "year"])
    paired_rows: list[dict[str, Any]] = []
    pool_comparisons: list[dict[str, Any]] = []
    year_comparisons: list[dict[str, Any]] = []
    for pool in POOL_ORDER:
        left = metrics.loc[metrics.arm.eq("E") & metrics.pool.eq(pool)].set_index("race_id")
        right = metrics.loc[metrics.arm.eq("S") & metrics.pool.eq(pool)].set_index("race_id")
        joined = left[["race_date", "year", "race_nll", "race_brier"]].join(
            right[["race_nll", "race_brier"]], how="outer", lsuffix="_E", rsuffix="_S", validate="one_to_one")
        expected_races = EXPECTED_PLC_RACES if pool == "PLC" else EXPECTED_EVAL_RACES
        require(len(joined) == expected_races and joined.notna().all().all(), f"paired {pool} E−S keys differ")
        part = joined.reset_index(names="race_id")
        part["comparison"] = "E_minus_S"
        part["pool"] = pool
        part["delta_nll"] = part.race_nll_E - part.race_nll_S
        part["delta_brier"] = part.race_brier_E - part.race_brier_S
        paired_rows.extend(part.to_dict("records"))
        pool_comparisons.append({"comparison": "E_minus_S", "pool": pool, "races": len(part),
                                 "delta_mean_race_nll": float(part.delta_nll.mean()),
                                 "delta_mean_race_brier": float(part.delta_brier.mean()),
                                 "left_mean_race_nll": float(part.race_nll_E.mean()),
                                 "right_mean_race_nll": float(part.race_nll_S.mean()),
                                 "left_mean_race_brier": float(part.race_brier_E.mean()),
                                 "right_mean_race_brier": float(part.race_brier_S.mean())})
        for year in YEARS:
            yearly = part.loc[part.year.eq(year)]
            year_comparisons.append({"comparison": "E_minus_S", "pool": pool, "year": year,
                                     "races": len(yearly), "delta_mean_race_nll": float(yearly.delta_nll.mean()),
                                     "delta_mean_race_brier": float(yearly.delta_brier.mean())})
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
    require(schedule.shape == (2000, len(dates)), "bootstrap schedule shape/date mismatch")
    tri = paired.loc[paired.pool.eq("TRI")]
    draws, tri_lo, tri_hi = _bootstrap_mean_difference(tri, schedule, dates, "delta_nll")
    bootstrap_draws = pd.DataFrame({"comparison": "E_minus_S", "draw": np.arange(len(draws), dtype=np.int64),
                                   "tri_nll_difference": draws})
    win = paired.loc[paired.pool.eq("WIN")]
    tri_gate = bool(tri_hi < 0.0 and float(tri.delta_brier.mean()) <= 0.0)
    win_protection = bool(win.delta_nll.mean() <= 0.0 and win.delta_brier.mean() <= 0.0)
    comparison = {"comparison": "E_minus_S", "tri_races": len(tri), "dates": len(dates),
                  "bootstrap_draws": len(draws), "tri_delta_mean_race_nll": float(tri.delta_nll.mean()),
                  "tri_delta_nll_ci95": [tri_lo, tri_hi], "tri_delta_mean_race_brier": float(tri.delta_brier.mean()),
                  "tri_gate_pass": tri_gate, "win_delta_mean_race_nll": float(win.delta_nll.mean()),
                  "win_delta_mean_race_brier": float(win.delta_brier.mean()),
                  "win_point_protection_pass": win_protection,
                  "comparison_gate_pass": bool(tri_gate and win_protection),
                  "schedule_sha256": sha256_file(BOOTSTRAP), "date_inventory_sha256": date_hash,
                  "statistical_noninferiority_claimed": False}
    axis_summary, axis_bootstrap = _axis_reports(axis, schedule, dates)
    pair_bootstrap_summary, pair_bootstrap_draws = _pair_selection_bootstrap(pair_diagnostics, schedule, dates)
    pair_summary = pair_diagnostics.groupby(["arm", "pool", "k"], sort=False).agg(
        races=("race_id", "nunique"), mean_union_probability=("selected_union_probability", "mean"),
        realized_hit_rate=("realized_hit_count", lambda values: float(np.mean(values > 0))),
        expected_hits=("expected_hits", "mean"), mean_realized_hit_count=("realized_hit_count", "mean"),
    ).reset_index()
    report = {
        "status": "EVALUATED_RESEARCH_ONLY", "arms": list(ARMS),
        "evaluation_races": EXPECTED_EVAL_RACES, "evaluation_runners": EXPECTED_EVAL_RUNNERS,
        "evaluation_dates": EXPECTED_EVAL_DATES,
        "per_pool_denominators": {pool: EXPECTED_PLC_RACES if pool == "PLC" else EXPECTED_EVAL_RACES for pool in POOL_ORDER},
        "comparison": comparison,
        "overall_research_candidate_gate_pass": comparison["comparison_gate_pass"],
        "gate_scope": "predeclared research-only criteria on reused development evaluations; no production promotion",
        "win_axis": axis_summary.to_dict("records"), "win_axis_bootstrap": axis_bootstrap.to_dict("records"),
        "pair_selection_summary": pair_summary.to_dict("records"),
        "pair_selection_bootstrap": pair_bootstrap_summary.to_dict("records"),
        "S_replay_max_abs_errors": replay_errors, "fit_uncertainty_included": False,
        "reliability_weighting": "pooled ticket-event count; proper losses are race-equal",
    }
    return {
        "race_pool_metrics": metrics, "selected_ticket_ledger": selections,
        "evaluation_runner_marginals": marginals, "win_axis_ledger": axis,
        "pair_selection_diagnostics": pair_diagnostics, "race_contract_ledger": contract_ledger,
        "evaluation_quarantine": quarantine, "pool_summary": summary, "pool_year_summary": year_summary,
        "pool_comparisons": pd.DataFrame(pool_comparisons),
        "pool_year_comparisons": pd.DataFrame(year_comparisons),
        "paired_pool_comparisons": paired, "reliability_bins": reliability,
        "comparison_bootstrap_draws": bootstrap_draws,
        "win_axis_summary": axis_summary, "win_axis_bootstrap": axis_bootstrap,
        "pair_selection_summary": pair_summary,
        "pair_selection_bootstrap_summary": pair_bootstrap_summary,
        "pair_selection_bootstrap_draws": pair_bootstrap_draws,
        "evaluation_report": report,
    }


def _axis_reports(axis: pd.DataFrame, schedule: np.ndarray, dates: Sequence[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    summary = []
    boot = []
    by_arm: dict[str, pd.DataFrame] = {}
    for arm in ARMS:
        frame = axis.loc[axis.arm.eq(arm)].set_index("race_id")
        require(len(frame) == EXPECTED_EVAL_RACES and frame.index.is_unique, f"WIN axis coverage failed: {arm}")
        by_arm[arm] = frame
        hits = int(frame.selected_hit_top3.sum())
        summary.append({"arm": arm, "races": len(frame), "top3_hit_count": hits,
                        "top3_hit_rate": hits / len(frame)})
    pair = by_arm["E"][["race_date", "selected_hit_top3"]].join(
        by_arm["S"]["selected_hit_top3"], how="outer", lsuffix="_E", rsuffix="_S", validate="one_to_one")
    require(len(pair) == EXPECTED_EVAL_RACES and pair.notna().all().all(), "WIN axis paired keys mismatch")
    delta = pair.selected_hit_top3_E.astype(np.float64) - pair.selected_hit_top3_S.astype(np.float64)
    day = pd.DataFrame({"date": pair.race_date.astype(str), "delta": delta}).groupby("date").delta.agg(["sum", "count"])
    sums = day["sum"].reindex(dates, fill_value=0).to_numpy(float)
    counts = day["count"].reindex(dates, fill_value=0).to_numpy(float)
    draws = np.empty(schedule.shape[0], dtype=float)
    for ix, selected_dates in enumerate(schedule):
        mult = np.bincount(np.asarray(selected_dates, dtype=np.int64), minlength=len(dates)).astype(float)
        denom = float(np.dot(mult, counts))
        require(denom > 0.0, "empty WIN axis bootstrap sample")
        draws[ix] = float(np.dot(mult, sums) / denom)
    low, high = np.quantile(draws, [0.025, 0.975], method="linear")
    boot.append({"comparison": "E_minus_S", "races": len(pair), "hit_rate_difference": float(delta.mean()),
                 "hit_rate_difference_ci95": [float(low), float(high)], "date_bootstrap_draws": len(draws),
                 "schedule_sha256": sha256_file(BOOTSTRAP),
                 "date_inventory_sha256": hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()})
    return pd.DataFrame(summary), pd.DataFrame(boot)


def _run_approved_once() -> dict[str, Any]:
    authorized = _validate_approval()
    started = datetime.now(timezone.utc).isoformat()
    _write_json_once(OUTPUTS / "execution_claim.json", {
        "status": "RUN_CLAIMED_NO_RETRY", "scope": "fit_evaluate", "started_at_utc": started,
        "approval_sha256": authorized["approval_sha256"],
        "code_bundle_sha256": authorized["hashes"]["code_bundle_sha256"], "permitted_runs": 1,
    })
    clock = time.monotonic()
    s_module = _load_sealed_s_module()
    model_rows, info, _ = _source_contract_inputs(s_module)
    s_scores, s_temperatures = _validate_saved_s_scores(model_rows)
    f1_info = s_module._validate_f1_meta_sources()
    feature_columns = list(read_json(S_PARAMETERS)["features"]["S"]) + list(FEATURE_COLUMNS)
    categories = list(f1_info["categorical_columns"])
    engine = s_module._load_math_engine()
    temperatures: dict[tuple[str, int], float] = {("S", year): s_temperatures[year] for year in YEARS}
    fit_meta: list[dict[str, Any]] = []
    e_score_rows: list[pd.DataFrame] = []
    for year in YEARS:
        vocabulary = s_module._fold_vocabulary(model_rows, year, categories)
        model, meta, cal_scores, eval_scores, cal_mask, eval_mask = _fit_entry_year(
            model_rows, year=year, columns=feature_columns, categorical_vocab=vocabulary, s_module=s_module)
        model_path = MODELS / f"E_{year}.txt"
        model_payload = model.model_to_string(num_iteration=model.current_iteration()).encode("utf-8")
        _write_once(model_path, model_payload)
        meta["model_sha256"] = sha256_file(model_path)
        cal_frame = model_rows.loc[cal_mask].copy().reset_index(drop=True)
        temp_fit = _fit_temperature(_race_records(cal_frame, cal_scores), engine)
        temperatures[("E", year)] = float(temp_fit["temperature"])
        meta["temperature_fit"] = temp_fit
        meta["categorical_vocabulary_sha256"] = hashlib.sha256(
            json.dumps(meta["categorical_vocabulary"], ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")).hexdigest()
        fit_meta.append(meta)
        for role, mask, raw in (("calibration", cal_mask, cal_scores), ("evaluation", eval_mask, eval_scores)):
            part = model_rows.loc[mask, ["api_record_id", "race_id", "race_date", "year", "horse_number", "field_n"]].copy()
            require(len(part) == len(raw), f"E {year} {role} score frame mismatch")
            # S40 stores `year` as the model vintage; race_date records the event year.
            part["year"] = year
            part["arm"] = "E"
            part["role"] = role
            part["score"] = raw
            e_score_rows.append(part[["arm", "year", "role", "api_record_id", "race_id", "race_date",
                                      "horse_number", "field_n", "score"]])
        print(json.dumps({"phase": "candidate_vintage_fit_complete", "arm": "E", "year": year,
                          "best_iteration": meta["best_iteration"], "temperature": temp_fit["temperature"],
                          "elapsed_seconds": round(time.monotonic() - clock, 2)}), flush=True)
    baseline_scores = s_scores.loc[s_scores.role.isin(["calibration", "evaluation"])].copy()
    all_scores = pd.concat([baseline_scores, *e_score_rows], ignore_index=True)
    all_scores = all_scores.sort_values(["arm", "year", "role", "api_record_id"], kind="mergesort").reset_index(drop=True)
    calibration_counts = {year: int(model_rows.year.eq(year - 1).sum()) for year in YEARS}
    evaluation_counts = {year: int((model_rows.year.eq(year) &
                                     model_rows.race_date.le(EXPECTED_EVAL_END)).sum()) for year in YEARS}
    for arm in ARMS:
        validate_oos_score_vintages(all_scores, arm, calibration_counts, evaluation_counts)
    require(all_scores.arm.value_counts().to_dict().get("E") > 0 and
            all_scores.loc[all_scores.arm.eq("E"), "role"].value_counts().to_dict() ==
            {"calibration": int(sum(calibration_counts.values())),
             "evaluation": EXPECTED_EVAL_RUNNERS}, "E score ledger coverage mismatch")
    # Persist the complete model-vintage raw score ledger and fit/temperature
    # metadata before evaluation so an evaluator failure does not require any refit.
    _write_frame_once(OUTPUTS / "candidate_oos_scores.parquet", all_scores)
    _write_json_once(OUTPUTS / "fit_checkpoint.json", {
        "status": "FIT_COMPLETE_EVALUATION_PENDING", "arm": "E", "model_vintages": list(YEARS),
        "models": fit_meta,
        "temperatures": {arm: {str(year): float(temperatures[(arm, year)]) for year in YEARS}
                         for arm in ARMS},
        "score_ledger_path": (OUTPUTS / "candidate_oos_scores.parquet").relative_to(PROJECT).as_posix(),
        "score_ledger_sha256": sha256_file(OUTPUTS / "candidate_oos_scores.parquet"),
        "approval_sha256": authorized["approval_sha256"],
        "approved_hashes": authorized["hashes"],
        "fit_counts": {"candidate_final_models": 3, "candidate_LightGBM_train_calls": 6,
                       "candidate_PL_temperature_optimizations": 3,
                       "S_fit_calls": 0, "S_temperature_optimizations": 0},
    })
    schedule = np.load(BOOTSTRAP, allow_pickle=False)
    evaluated = evaluate_scores(model_rows, all_scores, temperatures, engine, schedule)
    for name, frame in evaluated.items():
        if isinstance(frame, pd.DataFrame):
            _write_frame_once(OUTPUTS / f"{name}.parquet", frame)
    source_metadata = {
        "current_weight_source_type": info["source_contract"].get("current_weight_source_type"),
        "publication_time_status": info["source_contract"].get("publication_time_status"),
        "pre_race_availability_verified": False,
        "pre_race_availability_assumption": info["audit_validation"]["pre_race_availability_assumption"],
        "previous_weight_source_type": info["source_contract"].get("previous_weight_source_type"),
        "previous_weight_rule": info["source_contract"].get("previous_weight_rule"),
        "number_fraction_formula": info["source_contract"].get("number_fraction_formula"),
        "number_denominator_rule": info["source_contract"].get("number_denominator_rule"),
        "target_roster_is_result_based": True,
        "result_recorded_weight_proxy_used": False,
    }
    parameters = {
        "study": "20261024_s_entry_conditions_v1", "design_contract_sha256": sha256_file(CONTRACT),
        "arms": {"S": "sealed S40 raw scores plus sealed same-vintage PL temperature",
                 "E": "S40 40 inputs plus exactly three audited numeric inputs; fresh annual model"},
        "features": {"S": read_json(S_PARAMETERS)["features"]["S"], "E": feature_columns,
                     "candidate_numeric_columns": list(FEATURE_COLUMNS), "categorical_columns": categories,
                     "train_vocabulary_by_year": {str(year): s_module._fold_vocabulary(model_rows, year, categories)
                                                   for year in YEARS}},
        "lightgbm_parameters": LGBM_PARAMS,
        "annual_splits": {str(year): {"initial_train": [2017, year - 3], "early_stop": year - 2,
                                       "refit_through": year - 2, "calibration": year - 1, "evaluation": year}
                          for year in YEARS},
        "models": fit_meta,
        "S_temperatures_reused": {str(year): {"temperature": s_temperatures[year],
                                              "source": "sealed_tb_state_transfer_v1 S arm"} for year in YEARS},
        "PL_temperature_bounds": [0.35, 4.0],
        "selection": "top ticket(s) p >= current maximum−1e-12, then horse-number lexicographic; probability map unchanged",
        "pool_minimums": POOL_MIN_STARTERS,
        "fit_budget": {"candidate_final_models": 3, "candidate_LightGBM_train_calls": 6,
                       "candidate_PL_temperature_optimizations": 3,
                       "S_fit_calls": 0, "S_temperature_optimizations": 0},
        "audit_source_metadata": source_metadata,
        "input_hashes": authorized["hashes"], "frozen_input_receipt": info,
        "environment": {"python": sys.version, "platform": platform.platform(), "numpy": np.__version__,
                        "pandas": pd.__version__, "lightgbm": lgb.__version__, "scipy": scipy.__version__},
    }
    _write_json_once(OUTPUTS / "parameters.json", parameters)
    final_report = dict(evaluated["evaluation_report"])
    final_report["source_availability"] = {
        "current_values_are_historical_H3_dated_declarations": True,
        "publication_time_status": source_metadata["publication_time_status"],
        "pre_race_availability_verified": False,
        "date_based_availability_assumption": source_metadata["pre_race_availability_assumption"],
        "evaluation_roster_is_result_based": True,
        "result_recorded_weight_proxy_used": False,
        "operational_pre_race_availability_claimed": False,
    }
    _write_json_once(OUTPUTS / "report.json", final_report)
    elapsed = time.monotonic() - clock
    artifacts = [{"path": path.relative_to(PROJECT).as_posix(), "bytes": path.stat().st_size,
                  "sha256": sha256_file(path)}
                 for path in sorted([*OUTPUTS.glob("*"), *MODELS.glob("*")], key=lambda item: item.name)
                 if path.is_file()]
    receipt = {"status": "COMPLETED_RESEARCH_ONLY", "approval_sha256": authorized["approval_sha256"],
               "approved_hashes": authorized["hashes"], "execution_started_at_utc": started,
               "execution_completed_at_utc": datetime.now(timezone.utc).isoformat(),
               "elapsed_seconds": elapsed, "fit_counts": parameters["fit_budget"],
               "evaluation_races": EXPECTED_EVAL_RACES, "evaluation_runners": EXPECTED_EVAL_RUNNERS,
               "models": 3, "maximum_new_study_bytes": MAX_STUDY_BYTES,
               "artifacts": artifacts, "production_changed": False, "database_changed": False}
    receipt_path = OUTPUTS / "fit_run_receipt.json"
    base_bytes = _study_bytes()
    for _ in range(8):
        expected_total = base_bytes + len(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False,
                       default=_json_default).encode("utf-8") + b"\n")
        if receipt.get("study_bytes_after_receipt") == expected_total:
            break
        receipt["study_bytes_after_receipt"] = expected_total
    else:
        require(False, "receipt byte-count calculation did not converge")
    payload = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False,
                         default=_json_default).encode("utf-8") + b"\n"
    require(base_bytes + len(payload) <= MAX_STUDY_BYTES, "new study artifacts exceed the 40 MB budget")
    _write_once(receipt_path, payload)
    require(_study_bytes() == receipt["study_bytes_after_receipt"], "final study byte receipt mismatch")
    print(json.dumps({"phase": "fit_evaluate_complete", "elapsed_seconds": elapsed,
                      "study_bytes": _study_bytes(), "report": evaluated["evaluation_report"]},
                     ensure_ascii=False, indent=2, default=_json_default), flush=True)
    return receipt


def run_synthetic_checks() -> dict[str, Any]:
    from test_entry_input_contract import run_tests
    result = run_tests()
    require(result.get("status") == "PASS_SYNTHETIC" and result.get("fit_calls") == 0 and
            result.get("source_rows_read") == 0 and result.get("candidate_probabilities_or_outcomes") is False,
            "synthetic-only input contract checks failed")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--synthetic-checks", action="store_true")
    actions.add_argument("--source-preflight", action="store_true")
    actions.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.synthetic_checks:
        run_synthetic_checks()
    elif args.source_preflight:
        source_preflight()
    else:
        _run_approved_once()


if __name__ == "__main__":
    main()
