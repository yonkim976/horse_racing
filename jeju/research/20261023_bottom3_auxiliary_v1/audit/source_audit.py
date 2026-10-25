#!/usr/bin/env python3
"""Read-only source and cohort audit for the contracted Bottom3 experiment.

This script checks only frozen inputs, metadata, keys, dates, label support,
and the pre-existing date-bootstrap receipt. It never fits a model, ranks
scores, computes probabilities, or evaluates outcomes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[4]
STUDY = "jeju/research/20261023_bottom3_auxiliary_v1"
AUDIT = REPO / STUDY / "audit"

CONTRACT = f"{STUDY}/supervisor/DESIGN_CONTRACT.md"
SESSION_START = f"{STUDY}/supervisor/SESSION_START.json"
EXPECTED_CONTRACT_SHA = "ff6e3af2d454cd30edb56df1251700320b01de3478939c98199e0886bf22f084"
EXPECTED_SESSION_SHA = "c7cd21d7300e0d3b4b070c51a10ca058bbb3214b73df6cc959b2cbff15c64bbe"

F1_ROOT = "jeju/research/20261010_style_history_ablation_v1"
F1_MANIFEST = f"{F1_ROOT}/ARTIFACT_MANIFEST.json"
F1_PREPARED_LOCK = f"{F1_ROOT}/outputs/prepared_lock.json"
F1_FEATURES = f"{F1_ROOT}/outputs/features.parquet"

S_ROOT = "jeju/research/20261022_tb_state_transfer_v1"
S_MANIFEST = f"{S_ROOT}/FINAL_MANIFEST.json"
S_INPUT_MANIFEST = f"{S_ROOT}/inputs/input_manifest.json"
S_STATE_FEATURES = f"{S_ROOT}/inputs/state_features.parquet"
S_STATE_LINEAGE = f"{S_ROOT}/inputs/state_lineage.parquet"
S_PARAMETERS = f"{S_ROOT}/experiment/outputs/parameters.json"
S_RAW_SCORES = f"{S_ROOT}/experiment/outputs/candidate_oos_scores.parquet"
S_SOURCE_PREFLIGHT = f"{S_ROOT}/experiment/outputs/source_preflight.json"
S_FIT_RECEIPT = f"{S_ROOT}/experiment/outputs/fit_run_receipt.json"
S_INPUT_REPORT = f"{S_ROOT}/audit/INPUT_REPORT.md"
S_STATE_PROOF = f"{S_ROOT}/supervisor/STATE_VERIFICATION.json"
S_LINEAGE_PROOF = f"{S_ROOT}/supervisor/LINEAGE_VERIFICATION.json"
S_ROSTER_PROOF = f"{S_ROOT}/supervisor/ROSTER_VERIFICATION.json"
S_IMPLEMENTATION = f"{S_ROOT}/experiment/state_transfer.py"

BOOTSTRAP = "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT = "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"

STATE_COLUMNS = [
    "state_rank_mean",
    "state_rank_sd",
    "state_distance_slope",
    "state_distance_sd",
    "state_rank_current",
    "state_rank_current_sd",
    "state_rank_n",
    "state_days_since_rank_observation",
    "state_rank_current_field_gap",
    "state_rank_current_field_rank",
]
STATE_KEY_COLUMNS = ["api_record_id", "race_id", "race_date", "cutoff", "historydate"]
EXPECTED_CATEGORIES = ["grade_raw", "previous_sex", "previous_result_status"]
EXPECTED_LGBM = {
    "objective": "binary",
    "metric": "binary_logloss",
    "learning_rate": 0.04,
    "num_leaves": 15,
    "min_data_in_leaf": 100,
    "lambda_l2": 5.0,
    "seed": 20261008,
    "deterministic": True,
    "force_col_wise": True,
    "num_threads": 4,
    "verbosity": -1,
}


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)


def safe_path(relative: str) -> Path:
    """Resolve a fixed repo-relative source and fail closed on traversal/symlinks outside root."""
    candidate = Path(relative)
    require(not candidate.is_absolute(), f"absolute source path rejected: {relative}")
    require(".." not in candidate.parts, f"parent traversal rejected: {relative}")
    resolved = (REPO / candidate).resolve(strict=True)
    require(resolved == REPO or REPO in resolved.parents, f"source escapes repository: {relative}")
    require(resolved.is_file(), f"source is not a regular file: {relative}")
    return resolved


def digest_file(path: Path) -> tuple[int, str]:
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            size += len(block)
            hasher.update(block)
    return size, hasher.hexdigest()


def read_json(relative: str) -> dict[str, Any]:
    return json.loads(safe_path(relative).read_text(encoding="utf-8"))


def tb_pin(path: str, manifest: dict[str, Any]) -> dict[str, Any] | None:
    for collection in ("files_excluding_manifest", "preserved_source_references"):
        for entry in manifest.get(collection, []):
            if entry.get("path") == path:
                return entry
    return None


def f1_artifact_pin(path: str, manifest: dict[str, Any]) -> dict[str, Any] | None:
    entry = manifest.get("study_artifacts", {}).get(path)
    if not isinstance(entry, dict):
        return None
    return {"path": path, **entry}


def verify_pin(path: str, expected: dict[str, Any] | None) -> dict[str, Any]:
    require(expected is not None, f"no sealed manifest pin for {path}")
    actual_path = safe_path(path)
    size, sha = digest_file(actual_path)
    require(size == int(expected["bytes"]), f"byte-count mismatch for {path}")
    require(sha == expected["sha256"], f"sha256 mismatch for {path}")
    return {"path": path, "bytes": size, "sha256": sha}


def check_manifest_chain() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract_ref = verify_pin(CONTRACT, {"bytes": 9799, "sha256": EXPECTED_CONTRACT_SHA})
    require(contract_ref["sha256"] == EXPECTED_CONTRACT_SHA, "design contract hash drift")
    session_ref = verify_pin(SESSION_START, {"bytes": 2271, "sha256": EXPECTED_SESSION_SHA})
    require(session_ref["sha256"] == EXPECTED_SESSION_SHA, "SESSION_START hash drift")
    session = read_json(SESSION_START)

    f1_manifest = read_json(F1_MANIFEST)
    s_manifest = read_json(S_MANIFEST)
    require("frozen" in str(f1_manifest.get("status", "")).lower(), "F1_STYLE6 artifact manifest is not frozen")
    f1_source_audit = f1_manifest.get("source_audit", {})
    require(f1_source_audit.get("passed") is True, "F1_STYLE6 source audit did not pass")
    require(f1_source_audit.get("roster_n_or_id_mismatches") == 0, "F1 source roster audit reports mismatches")
    f1_cohort = f1_manifest.get("cohort", {})
    require(
        (f1_cohort.get("target_rows"), f1_cohort.get("target_races"),
         f1_cohort.get("evaluation_rows"), f1_cohort.get("evaluation_races"),
         f1_cohort.get("evaluation_race_days")) == (52155, 5206, 17412, 1779, 269),
        "F1 frozen manifest cohort counts differ from the experiment contract",
    )
    f1_manifest_path = safe_path(F1_MANIFEST)
    f1_manifest_size, f1_manifest_sha = digest_file(f1_manifest_path)
    f1_manifest_ref = {"path": F1_MANIFEST, "bytes": f1_manifest_size, "sha256": f1_manifest_sha}
    s_manifest_pin = next(
        (p for p in session.get("protected_pins", []) if p.get("path") == S_MANIFEST), None
    )
    s_manifest_ref = verify_pin(S_MANIFEST, s_manifest_pin)
    require(s_manifest.get("status") == "COMPLETED_VERIFIED_RESEARCH", "S provider manifest not finalized")
    return session, f1_manifest, s_manifest, {
        "contract": contract_ref,
        "session_start": session_ref,
        "f1_artifact_manifest": f1_manifest_ref,
        "s_final_manifest": s_manifest_ref,
    }


def source_refs(f1_manifest: dict[str, Any], s_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    paths = [
        CONTRACT,
        SESSION_START,
        F1_MANIFEST,
        F1_PREPARED_LOCK,
        F1_FEATURES,
        *(f"{F1_ROOT}/outputs/F1_STYLE6_{year}/meta.json" for year in (2024, 2025, 2026)),
        S_MANIFEST,
        f"{S_ROOT}/supervisor/DESIGN_CONTRACT.md",
        S_INPUT_MANIFEST,
        f"{S_ROOT}/audit/source_manifest.json",
        S_INPUT_REPORT,
        S_STATE_FEATURES,
        S_STATE_LINEAGE,
        S_STATE_PROOF,
        S_LINEAGE_PROOF,
        S_ROSTER_PROOF,
        S_PARAMETERS,
        S_RAW_SCORES,
        S_SOURCE_PREFLIGHT,
        S_FIT_RECEIPT,
        S_IMPLEMENTATION,
        BOOTSTRAP,
        BOOTSTRAP_RECEIPT,
        f"{STUDY}/audit/source_audit.py",
    ]
    refs: list[dict[str, Any]] = []
    for path in paths:
        if path in (CONTRACT, SESSION_START):
            expected = {"bytes": 9799, "sha256": EXPECTED_CONTRACT_SHA} if path == CONTRACT else {
                "bytes": 2271, "sha256": EXPECTED_SESSION_SHA
            }
        elif path == S_MANIFEST:
            expected = next((p for p in read_json(SESSION_START).get("protected_pins", []) if p.get("path") == path), None)
        elif path == F1_MANIFEST:
            actual_path = safe_path(path)
            size, sha = digest_file(actual_path)
            refs.append({"path": path, "bytes": size, "sha256": sha})
            continue
        elif path == f"{STUDY}/audit/source_audit.py":
            actual_path = safe_path(path)
            size, sha = digest_file(actual_path)
            refs.append({"path": path, "bytes": size, "sha256": sha})
            continue
        elif path.startswith(F1_ROOT + "/"):
            expected = f1_artifact_pin(path, f1_manifest)
        else:
            expected = tb_pin(path, s_manifest)
            if path in (BOOTSTRAP, BOOTSTRAP_RECEIPT) and expected is None:
                preflight = read_json(S_SOURCE_PREFLIGHT)
                name = "bootstrap_schedule" if path == BOOTSTRAP else "bootstrap_receipt"
                expected = preflight.get("reference_assets", {}).get(name)
        refs.append(verify_pin(path, expected))
    return refs


def support(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "rows": int(len(frame)),
        "races": int(frame["race_id"].nunique()),
        "days": int(frame["race_date"].nunique()),
        "bottom3_labels": int(frame["y_bottom3"].sum()),
        "date_min": str(frame["race_date"].min().date()),
        "date_max": str(frame["race_date"].max().date()),
    }


def main() -> None:
    session, f1_manifest, s_manifest, chain_refs = check_manifest_chain()
    source_references = source_refs(f1_manifest, s_manifest)

    f1_path = safe_path(F1_FEATURES)
    state_path = safe_path(S_STATE_FEATURES)
    scores_path = safe_path(S_RAW_SCORES)
    features = pd.read_parquet(f1_path)
    states = pd.read_parquet(state_path)
    scores = pd.read_parquet(scores_path)

    params = read_json(S_PARAMETERS)
    input_manifest = read_json(S_INPUT_MANIFEST)
    state_source_manifest = read_json(f"{S_ROOT}/audit/source_manifest.json")
    bootstrap_receipt = read_json(BOOTSTRAP_RECEIPT)
    state_proof = read_json(S_STATE_PROOF)
    lineage_proof = read_json(S_LINEAGE_PROOF)
    roster_proof = read_json(S_ROSTER_PROOF)
    f1_metas = {
        year: read_json(f"{F1_ROOT}/outputs/F1_STYLE6_{year}/meta.json")
        for year in (2024, 2025, 2026)
    }

    # Use the already pinned metadata to verify all three parts of the 40-column input contract.
    f1_columns = list(f1_metas[2024]["features"])
    require(len(f1_columns) == 30, "F1_STYLE6 provider metadata must declare 30 inputs")
    require(all(list(f1_metas[y]["features"]) == f1_columns for y in (2025, 2026)), "F1 metadata feature lists differ by year")
    require(list(params["features"]["S"])[:30] == f1_columns, "S model does not preserve the ordered F1 30 inputs")
    require(list(params["features"]["S"])[30:] == STATE_COLUMNS, "S model state input list/order differs from the sealed state contract")
    require(len(params["features"]["S"]) == 40, "S model metadata does not declare exactly 40 inputs")
    require(params["features"]["categorical_columns"] == EXPECTED_CATEGORIES, "S categorical input list changed")
    require(params["lightgbm_parameters"] == EXPECTED_LGBM, "S fit settings differ from the Bottom3 contract")
    require(params["study"] == "20261022_tb_state_transfer_v1" and params["contract_sha256"] == "7dc4b4f861e91e080a238e7ad85475fb50a9a5fa695896f554b131c9a6540092", "S metadata/provider contract identity mismatch")
    require(params["arms"]["S"].startswith("same 30 inputs plus 10 contracted"), "S arm identity changed")
    require(input_manifest["files"]["state_features.parquet"]["sha256"] == digest_file(state_path)[1], "state input hash differs from sealed input manifest")
    require(input_manifest["source_files"]["f1_style6_target_keys_source"]["sha256"] == digest_file(f1_path)[1], "F1 feature hash differs from sealed state input manifest")
    require(state_source_manifest["study"] == "20261022_tb_state_transfer_v1", "state source manifest identity mismatch")
    require(state_proof.get("passed") is True, "sealed state verification did not pass")
    require(lineage_proof.get("passed") is True and lineage_proof.get("rows") == 52155,
            "sealed state lineage verification did not pass for the full target table")
    require(roster_proof.get("passed") is True and roster_proof.get("races") == 7066 and
            roster_proof.get("rows") == 69752, "sealed history roster verification did not pass")
    require(params["input_hashes"]["state_features_sha256"] == digest_file(state_path)[1], "S provider metadata state input hash mismatch")
    require(params["input_hashes"]["f1_features_sha256"] == digest_file(f1_path)[1], "S provider metadata F1 source hash mismatch")
    require(params["input_hashes"]["bootstrap_sha256"] == digest_file(safe_path(BOOTSTRAP))[1], "S metadata bootstrap hash mismatch")
    require(params["input_hashes"]["bootstrap_receipt_sha256"] == digest_file(safe_path(BOOTSTRAP_RECEIPT))[1], "S metadata bootstrap receipt hash mismatch")
    frozen = params["frozen_frame_receipt"]
    require(frozen["f1_features_sha256"] == digest_file(f1_path)[1] and frozen["state_features_sha256"] == digest_file(state_path)[1],
            "S frozen-frame receipt input hashes mismatch")
    require(frozen["rows"] == 52155 and frozen["races"] == 5206 and frozen["eval_rows"] == 17412 and
            frozen["eval_races"] == 1779 and frozen["eval_dates"] == 269, "S frozen-frame receipt cohort mismatch")
    require(input_manifest["cutoff"]["rule"] == "race_date minus two calendar days; source event date <= cutoff inclusive",
            "sealed state cutoff rule changed")

    require(set(f1_columns).issubset(features.columns), "one or more F1_STYLE6 columns are absent from frozen feature table")
    require(list(input_manifest["feature_schema"]) == STATE_KEY_COLUMNS + STATE_COLUMNS, "sealed state feature schema/order changed")
    require(list(states.columns) == STATE_KEY_COLUMNS + STATE_COLUMNS, "state feature table schema/order changed")
    require(set(scores.columns) == {"arm", "year", "role", "api_record_id", "race_id", "race_date", "horse_number", "field_n", "score"}, "S provider OOS score schema changed")
    require(len(features) == 52155 and features["race_id"].nunique() == 5206, "F1 target cohort row/race count drift")
    require(features["api_record_id"].notna().all() and features["api_record_id"].is_unique, "F1 API record keys are missing/duplicated")
    require(features["api_record_id"].astype(str).str.strip().ne("").all(), "F1 API record key contains a blank value")
    require(features["race_id"].notna().all() and features["race_id"].astype(str).str.strip().ne("").all(),
            "F1 race key contains a missing/blank value")
    require(len(states) == 52155 and states["api_record_id"].is_unique, "S state table row/API key count drift")
    require(len(scores) > 0, "provider OOS score table is empty")

    date = pd.to_datetime(features["race_date"], errors="raise")
    require(date.notna().all(), "F1 target race date contains a missing value")
    year = date.dt.year
    require((features["year"].astype(int).to_numpy() == year.to_numpy()).all(), "F1 calendar year column disagrees with race_date")
    cutoff = date - pd.Timedelta(days=2)
    f1_cutoff = pd.to_datetime(features["history_cutoff"], errors="raise")
    f1_latest_history = pd.to_datetime(features["latest_history_date"], errors="coerce")
    require((f1_cutoff.to_numpy() == cutoff.to_numpy()).all(), "F1 target history cutoff is not inclusive T-2")
    require(((f1_latest_history.isna()) | (f1_latest_history <= cutoff)).all(), "F1 latest history event is later than target T-2")

    features = features.copy()
    features["race_date"] = date
    for column in ("finish_position", "field_n", "horse_number"):
        numeric = pd.to_numeric(features[column], errors="raise").to_numpy(dtype=np.float64)
        require(np.isfinite(numeric).all() and np.equal(numeric, np.floor(numeric)).all(),
                f"F1 {column} contains a missing, non-finite, or non-integer value")
    require((features["horse_number"].astype(np.int64) >= 1).all(), "F1 horse number is nonpositive")
    features["y_bottom3"] = (features["finish_position"].astype(np.int64) >= features["field_n"].astype(np.int64) - 2).astype(np.int8)
    require((features["field_n"] >= 6).all(), "a target race has fewer than six runners")
    require((features["finish_position"] >= 1).all(), "frozen F1 cohort has missing/nonpositive ranks")
    race_checks = features.groupby("race_id", sort=False).agg(
        rows=("api_record_id", "size"),
        field_min=("field_n", "min"),
        field_max=("field_n", "max"),
        rank_min=("finish_position", "min"),
        rank_max=("finish_position", "max"),
        unique_ranks=("finish_position", "nunique"),
        y_count=("y_bottom3", "sum"),
        date_count=("race_date", "nunique"),
    )
    require((race_checks["rows"] == race_checks["field_min"]).all(), "F1 field_n does not match roster rows")
    require((race_checks["field_min"] == race_checks["field_max"]).all(), "field_n varies within race")
    require((race_checks["rank_min"] == 1).all(), "race rank permutation does not start at 1")
    require((race_checks["rank_max"] == race_checks["rows"]).all(), "race rank permutation does not end at N")
    require((race_checks["unique_ranks"] == race_checks["rows"]).all(), "race contains duplicate ranks")
    require((race_checks["y_count"] == 3).all(), "a race does not have exactly three Bottom3 labels")
    require((race_checks["date_count"] == 1).all(), "race ID maps to multiple dates")
    require(int(features["y_bottom3"].sum()) == 15618, "full-cohort Bottom3 label census drift")

    state_check = states.copy()
    state_check["race_date"] = pd.to_datetime(state_check["race_date"], errors="raise")
    state_check["cutoff"] = pd.to_datetime(state_check["cutoff"], errors="raise")
    state_check["historydate"] = pd.to_datetime(state_check["historydate"], errors="coerce")
    require(state_check["api_record_id"].is_unique, "state API keys are not unique")
    joined = features[["api_record_id", "race_id", "race_date", "history_cutoff", "field_n", "horse_number", "y_bottom3"]].merge(
        state_check[STATE_KEY_COLUMNS + STATE_COLUMNS], on="api_record_id", how="outer", validate="one_to_one", suffixes=("_f1", "_state"), indicator=True
    )
    require((joined["_merge"] == "both").all() and len(joined) == 52155, "F1/state API key sets differ")
    require((joined["race_id_f1"] == joined["race_id_state"]).all(), "F1/state race IDs differ")
    require((joined["race_date_f1"] == joined["race_date_state"]).all(), "F1/state race dates differ")
    joined_cutoff = pd.to_datetime(joined["history_cutoff"], errors="raise")
    state_cutoff = pd.to_datetime(joined["cutoff"], errors="raise")
    require((joined_cutoff.to_numpy() == state_cutoff.to_numpy()).all(), "F1/state T-2 cutoff keys differ")
    state_history = pd.to_datetime(joined["historydate"], errors="coerce")
    require(((state_history.isna()) | (state_history <= state_cutoff)).all(), "state history update after target T-2")
    state_history_missing = int(state_history.isna().sum())
    state_history_max = str(state_history.max().date()) if state_history.notna().any() else None

    # Verify the train-only category vocabularies from the already fitted S provider metadata.
    vocab_checks: dict[str, Any] = {}
    for vintage in (2024, 2025, 2026):
        train_mask = year.between(2017, vintage - 3)
        declared = params["features"]["train_vocabulary_by_year"][str(vintage)]
        actual_vocab: dict[str, list[str]] = {}
        for column in EXPECTED_CATEGORIES:
            actual = sorted(features.loc[train_mask, column].dropna().astype(str).unique().tolist())
            expected = list(declared[column])
            require(actual == expected, f"S {vintage} train-only vocabulary differs for {column}")
            actual_vocab[column] = actual
        require(f1_metas[vintage]["vocabulary"] == declared, f"F1/S {vintage} category vocabulary differs")
        expected_split = {
            "initial_train": [2017, vintage - 3],
            "early_stop": vintage - 2,
            "refit_through": vintage - 2,
            "calibration": vintage - 1,
            "evaluation": vintage,
        }
        actual_split = params["annual_splits"][str(vintage)]
        require(actual_split["initial_train"] == expected_split["initial_train"], f"S {vintage} initial-train years differ from contract")
        require(actual_split["early_stop"] == expected_split["early_stop"], f"S {vintage} early-stop year differs from contract")
        require(actual_split["refit_through"] == expected_split["refit_through"], f"S {vintage} refit boundary differs from contract")
        require(actual_split["calibration"] == expected_split["calibration"], f"S {vintage} calibration year differs from contract")
        require(actual_split["evaluation"] == expected_split["evaluation"], f"S {vintage} evaluation year differs from contract")
        vocab_checks[str(vintage)] = {"matches_provider_metadata": True, "columns": actual_vocab}
    s_models = [model for model in params["models"] if model.get("arm") == "S"]
    require(len(s_models) == 3 and sorted(int(model["year"]) for model in s_models) == [2024, 2025, 2026], "S provider model-vintage metadata changed")
    for model in s_models:
        require(model["feature_count"] == 40 and model["feature_names"] == list(params["features"]["S"]),
                f"S {model['year']} saved provider input metadata differs")
        require(model["parameters"] == EXPECTED_LGBM and model["max_rounds"] == 800 and
                model["early_stopping_rounds"] == 25 and model["seed"] == 20261008,
                f"S {model['year']} fit settings differ from the Bottom3 contract")

    s_code = safe_path(S_IMPLEMENTATION).read_text(encoding="utf-8")
    require('target = (frame.finish_position.to_numpy(dtype=np.int64) <= 3).astype(np.int8)' in s_code,
            "S provider source no longer trains the Top3 binary target")

    # Check the phase census and S provider score roles only; do not rank or evaluate scores.
    phase_support: dict[str, Any] = {}
    for vintage in (2024, 2025, 2026):
        masks = {
            "initial_train": year.between(2017, vintage - 3),
            "early_stop": year.eq(vintage - 2),
            "refit": year.between(2017, vintage - 2),
            "calibration": year.eq(vintage - 1),
            "evaluation": year.eq(vintage),
        }
        phase_support[str(vintage)] = {phase: support(features.loc[mask]) for phase, mask in masks.items()}

    score_check = scores.copy()
    score_check["race_date"] = pd.to_datetime(score_check["race_date"], errors="raise")
    require(set(score_check["arm"].unique()) == {"C", "S"}, "provider score table arms changed")
    require(set(score_check["role"].unique()) == {"calibration", "evaluation"}, "provider score table contains unexpected OOS roles")
    s_scores = score_check.loc[score_check["arm"].eq("S")].copy()
    require(s_scores["api_record_id"].notna().all(), "S OOS score has a missing API record ID")
    require(not s_scores.duplicated(["year", "role", "api_record_id"]).any(), "S OOS score duplicate provider-role API key")
    require(s_scores["score"].map(np.isfinite).all(), "S OOS score non-finite")
    score_support: dict[str, Any] = {}
    feature_metadata = features[["api_record_id", "race_id", "race_date", "horse_number", "field_n"]].copy()
    for vintage in (2024, 2025, 2026):
        score_support[str(vintage)] = {}
        for role, expected_calendar_year in (("calibration", vintage - 1), ("evaluation", vintage)):
            group = s_scores.loc[s_scores["year"].eq(vintage) & s_scores["role"].eq(role)].copy()
            require(len(group) > 0, f"empty S provider OOS role: {vintage}/{role}")
            require((group["race_date"].dt.year == expected_calendar_year).all(), f"S provider year/role/calendar year mismatch: {vintage}/{role}")
            if role == "evaluation" and vintage == 2026:
                require((group["race_date"] <= pd.Timestamp("2026-09-19")).all(), "S 2026 eval extends beyond frozen cohort cutoff")
            expected = feature_metadata.loc[pd.to_datetime(feature_metadata["race_date"]).dt.year.eq(expected_calendar_year)]
            require(len(group) == len(expected), f"S provider OOS row count mismatch to F1 calendar year: {vintage}/{role}")
            joined_scores = group.merge(expected, on="api_record_id", how="outer", validate="one_to_one", suffixes=("_score", "_f1"), indicator=True)
            require((joined_scores["_merge"] == "both").all(), f"S {vintage}/{role} API keys do not exactly cover the F1 year")
            for column in ("race_id", "race_date", "horse_number", "field_n"):
                left, right = joined_scores[f"{column}_score"], joined_scores[f"{column}_f1"]
                if column == "race_date":
                    require((pd.to_datetime(left).to_numpy() == pd.to_datetime(right).to_numpy()).all(), f"S {vintage}/{role} race dates mismatch")
                else:
                    require((left.astype(str).to_numpy() == right.astype(str).to_numpy()).all(), f"S {vintage}/{role} {column} mismatch")
            score_support[str(vintage)][role] = {
                "provider_year": vintage,
                "calendar_year": expected_calendar_year,
                "rows": int(len(group)),
                "races": int(group["race_id"].nunique()),
                "date_min": str(group["race_date"].min().date()),
                "date_max": str(group["race_date"].max().date()),
                "all_scores_finite": True,
                "exact_f1_api_race_date_number_field_match": True,
                "bottom3_label_support_from_f1": support(features.loc[year.eq(expected_calendar_year)]),
            }

    eval_features = features.loc[year.ge(2024)].copy()
    eval_support = support(eval_features)
    require(eval_support == {
        "rows": 17412,
        "races": 1779,
        "days": 269,
        "bottom3_labels": 5337,
        "date_min": "2024-01-05",
        "date_max": "2026-09-19",
    }, "contracted common evaluation cohort or Bottom3 label census mismatch")
    yearly_eval = {str(y): support(eval_features.loc[eval_features["race_date"].dt.year.eq(y)]) for y in (2024, 2025, 2026)}
    require([yearly_eval[str(y)]["races"] for y in (2024, 2025, 2026)] == [637, 654, 488], "annual evaluation race counts mismatch")
    require([yearly_eval[str(y)]["rows"] for y in (2024, 2025, 2026)] == [6329, 6410, 4673], "annual evaluation runner counts mismatch")

    dates = sorted(eval_features["race_date"].dt.strftime("%Y-%m-%d").unique().tolist())
    date_digest = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(len(dates) == 269 and date_digest == bootstrap_receipt["date_inventory_sha256"], "frozen bootstrap date inventory differs from evaluation cohort")
    schedule = np.load(safe_path(BOOTSTRAP), allow_pickle=False)
    require(schedule.shape == (2000, 269) and schedule.dtype == np.dtype("int32"), "frozen bootstrap shape/dtype changed")
    require(int(schedule.min()) >= 0 and int(schedule.max()) < 269, "bootstrap schedule indexes out of date range")
    require(bootstrap_receipt["schedule_shape"] == [2000, 269] and bootstrap_receipt["schedule_sha256"] == digest_file(safe_path(BOOTSTRAP))[1], "bootstrap receipt does not pin schedule")

    source_references_after = source_refs(f1_manifest, s_manifest)
    require(source_references == source_references_after, "a source file changed during audit")

    output = {
        "status": "PASS_SOURCE_AUDIT_ONLY",
        "passed": True,
        "study": STUDY,
        "contract_sha256": EXPECTED_CONTRACT_SHA,
        "source_references": source_references,
        "source_pin_chain": chain_refs,
        "provider": {
            "study": S_ROOT,
            "arm": "S",
            "score_filter": {"arm": "S", "role": ["calibration", "evaluation"], "year": [2024, 2025, 2026]},
            "raw_score_only": True,
            "score_schema": list(scores.columns),
            "score_rows_by_provider_role": score_support,
            "top3_source_objective": "binary Top3; raw score used only as u_L=-score for the pre-existing low-score baseline",
            "existing_top3_temperature_reused_for_bottom3": False,
            "S_bottom3_probability_available": False,
        },
        "feature_contract": {
            "f1_feature_count": len(f1_columns),
            "state_feature_count": len(STATE_COLUMNS),
            "combined_count": 40,
            "ordered_features": list(params["features"]["S"]),
            "categorical_columns": EXPECTED_CATEGORIES,
            "train_only_vocabularies": vocab_checks,
            "provider_LightGBM_settings_match_contract": True,
            "f1_state_join": {
                "rows": int(len(joined)),
                "exact_api_record_id_set": True,
                "race_id_and_date_match": True,
                "T_minus_2_cutoff_match": True,
                "state_history_event_not_after_cutoff": True,
                "state_historydate_missing_rows": state_history_missing,
                "latest_state_historydate": state_history_max,
                "state_rebuilt": False,
            },
        },
        "cohort_and_label_census": {
            "f1_full_cohort": support(features),
            "yearly_target_support": {
                str(y): support(features.loc[year.eq(y)]) for y in range(2017, 2027)
            },
            "annual_fit_phase_support": phase_support,
            "common_evaluation": eval_support,
            "evaluation_by_year": yearly_eval,
            "rank_contract": "each included race has unique exact ranks 1..N, field_n equals roster row count, and exactly 3 labels y=1[finish_position >= field_n-2]",
            "label_support_only_no_performance_metrics": True,
        },
        "time_and_selection_limits": {
            "feature_history_cutoff": "race_date - 2 calendar days, inclusive source event date",
            "publication_timestamp_verified": False,
            "actual_pre_race_roster_verified": False,
            "cohort_conditioning": "retrospective normal-finish complete fields with unique ranks; excludes unobserved/ambiguous finish outcomes",
            "nonfinish_dnf_dsq_tie_cancellation_labels_inferred": False,
            "evaluation_period_is_new_holdout": False,
        },
        "bootstrap_reference": {
            "schedule_path": BOOTSTRAP,
            "receipt_path": BOOTSTRAP_RECEIPT,
            "schedule_shape": list(schedule.shape),
            "date_count": len(dates),
            "date_inventory_sha256": date_digest,
            "schedule_sha256": digest_file(safe_path(BOOTSTRAP))[1],
            "copied_or_regenerated": False,
        },
        "execution_boundary": {
            "database_access": "none",
            "model_fit": False,
            "new_predictions_or_probabilities": False,
            "score_ranking_or_selection": False,
            "bottom3_performance_calculated": False,
            "source_files_copied": False,
            "outcome_metrics_read": False,
        },
        "findings": [
            "S metadata confirms one fixed 40-input provider with F1_STYLE6 30 ordered inputs plus 10 contracted rank/distance state inputs; all three annual category vocabularies match the frozen provider metadata.",
            "The S provider OOS score table separates provider year and calibration/evaluation role. For each role, S raw scores are finite and exactly cover the corresponding F1 race-year API IDs, race IDs, race dates, horse numbers, and field sizes.",
            "The frozen F1 result cohort has exact full-field ranks and supports exactly three Bottom3 labels per race: 15,618 potential labels across 5,206 races and 5,337 in the repeated 1,779-race evaluation cohort.",
            "The frozen S state table joins one-to-one by API record ID; race/date and T-2 cutoff agree and all state history dates are at or before the cutoff. Existing sealed state proofs were referenced; state generation was not rerun.",
            "The existing 2,000-by-269 paired-date bootstrap schedule is pinned and its date inventory matches the fixed evaluation dates. No model fit or Bottom3 performance was calculated.",
        ],
    }
    (AUDIT / "SOURCE_AUDIT.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": output["status"],
        "passed": output["passed"],
        "references": len(source_references),
        "features": 40,
        "full_rows": len(features),
        "full_races": int(features["race_id"].nunique()),
        "eval_rows": eval_support["rows"],
        "eval_races": eval_support["races"],
        "eval_days": eval_support["days"],
        "eval_bottom3_labels": eval_support["bottom3_labels"],
        "fit_or_performance": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
