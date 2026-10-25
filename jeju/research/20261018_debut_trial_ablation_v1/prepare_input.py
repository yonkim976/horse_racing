"""Build and preflight the frozen 34-column study input; never fit/evaluate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from feature_core import ADDED_FEATURES, add_features
from train_candidate import BASE_COLUMNS, FEATURE_COLUMNS, ROOT, STYLE_OUT, VARIANT, YEARS


HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SOURCE_DIR = ROOT / "jeju/research/20261018_debut_trial_source_audit_v1"
SOURCE_OUT = SOURCE_DIR / "outputs"
ROOT_REVIEW_DIR = ROOT / "jeju/research/20261018_debut_trial_rootreview_v1"
STYLE_OUT = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs"
BASELINE_FEATURES = STYLE_OUT / "features.parquet"
SOURCE_MANIFEST = SOURCE_OUT / "audit_manifest.json"
SOURCE_SUMMARY = SOURCE_OUT / "audit_summary.json"
ROOT_EVALUATION_CONTRACT = ROOT_REVIEW_DIR / "ROOT_EVALUATION_CONTRACT.json"
ROOT_SOURCE_LOCK = ROOT_REVIEW_DIR / "ROOT_SOURCE_LOCK.json"
ROOT_EXAMPLE_SELECTION = ROOT_REVIEW_DIR / "ROOT_EXAMPLE_SELECTION.json"
ROOT_TRIAL_FEATURE_REFERENCE = ROOT_REVIEW_DIR / "ROOT_TRIAL_FEATURE_REFERENCE.parquet"
PINNED_SOURCE_MANIFEST_SHA256 = "2b51b2638823b2c4ff3673b24d9c68ee6d94cc734f75902e1ec8c69adefda7ea"
FEATURE_FILE = OUT / "features_f1_style6_debut_trial4.parquet"
SLOT_FILE = OUT / "cold_target_trial_feature_slots.parquet"
LINEAGE_FILE = OUT / "cold_target_trial_source_lineage.parquet"
PREFLIGHT_FILE = OUT / "preflight_verification.json"
PREPARED_LOCK_FILE = OUT / "prepared_lock.json"

SOURCE_ARTIFACTS = (
    "api20_trial_event_rows.parquet",
    "audit_summary.json",
    "cold_target_prior_race_history_audit.parquet",
    "cold_target_roster.parquet",
    "cold_target_trial_lineage.parquet",
    "source_artifacts.json",
    "trial_event_key_audit.parquet",
    "trial_event_relative_peer_ledger.parquet",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_child(parent: Path, name: str) -> Path:
    if Path(name).name != name or name in {".", ".."}:
        raise AssertionError(f"unsafe artifact filename: {name!r}")
    candidate = (parent / name).resolve()
    if not candidate.is_relative_to(parent.resolve()):
        raise AssertionError(f"artifact path escapes its allowed directory: {name!r}")
    return candidate


def _write_json_new(path: Path, payload: dict) -> None:
    path = Path(path)
    if not path.resolve().is_relative_to(OUT.resolve()):
        raise AssertionError("refusing to write preflight outside this study")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _write_parquet_new(path: Path, frame: pd.DataFrame) -> None:
    path = Path(path)
    if not path.resolve().is_relative_to(OUT.resolve()):
        raise AssertionError("refusing to write prepared input outside this study")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=False)


def _check_source_manifest() -> dict:
    manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
    assert sha256(SOURCE_MANIFEST) == PINNED_SOURCE_MANIFEST_SHA256, "source manifest changed after root handoff"
    summary = json.loads(SOURCE_SUMMARY.read_text(encoding="utf-8"))
    assert manifest["audit_name"] == "20261018_debut_trial_source_audit_v1"
    assert manifest["scope"].startswith("Read-only source audit")
    assert manifest["database"]["read_mode"].startswith("SQLite URI mode=ro")
    assert manifest["database"]["whole_database_hash"] is None
    assert manifest["database"]["source_scope_fingerprints"]["stable_across_captures"] is True
    source_contract = manifest["source_contract"]
    assert source_contract["trial_source"].startswith("API20 GET /API20_1/ridingTestResult_1")
    assert source_contract["starting_exam_api21"] == "Out of scope and not joined."
    assert source_contract["current_profile"].startswith("Not queried or joined")
    assert source_contract["event_key"] == ["trial_date", "meet_code", "trial_number"]
    assert source_contract["relative_time_validity"]["ordinal"] == "Raw ord must parse as an integer in 1..89; special codes remain raw and held."
    assert source_contract["relative_time_validity"]["time"] == "Raw rcTime must be finite and positive."
    assert source_contract["relative_time_validity"]["peers"].startswith("At least two other valid explicit-Jeju records")
    assert source_contract["event_count_semantics"].startswith("Count distinct observed target horse-event record keys, including cancelled/unperformed records")
    assert source_contract["distance"].startswith("API20 raw `rcDist` key is absent")
    coverage = summary["api20_target_trial_coverage"]
    assert coverage["target_registered_trial_event_rows_through_individual_T_minus_2"] == 3500
    assert coverage["target_horses_with_one_or_more_registered_trial_event_rows"] == 1946
    assert coverage["target_horses_without_registered_trial_event_rows"] == 0
    assert coverage["target_event_key_count"] == 961
    assert coverage["all_full_event_roster_rows"] == 8824
    assert coverage["all_full_event_roster_distinct_horses"] == 3194
    assert coverage["events_with_daySerial_inconsistency"] == 0
    assert coverage["events_with_duplicate_horse_rows"] == 0
    assert coverage["duplicate_natural_key_groups"] == 0
    assert coverage["natural_keys_with_multiple_payload_sha"] == 0
    assert coverage["target_candidate_time_and_known_judgment_count"] == 3413
    assert coverage["latest3_lineage_slots"] == 3240
    assert coverage["latest3_relative_gap_candidate_eligible_count"] == 3168
    for name in SOURCE_ARTIFACTS:
        path = _safe_child(SOURCE_OUT, name)
        entry = manifest["outputs"].get(name)
        assert path.is_file() and isinstance(entry, dict), f"missing source artifact: {name}"
        assert path.stat().st_size == int(entry["bytes"]), f"source byte count changed: {name}"
        assert sha256(path) == entry["sha256"], f"source artifact hash changed: {name}"
    return manifest


def _normalize_trial_rows(raw: pd.DataFrame) -> pd.DataFrame:
    required = {
        "api_record_id", "trial_date", "meet_code", "trial_number", "horse_id",
        "breed_label_raw", "rcTime_seconds_numeric", "raw_ord", "raw_passFlag",
        "valid_for_relative_time_candidate", "trial_event_key", "daySerial_raw",
        "event_key_valid", "payload_sha256", "payload_json",
    }
    assert required.issubset(raw.columns), f"source event schema missing {required - set(raw.columns)}"
    assert raw.event_key_valid.map(bool).all()
    assert raw.breed_label_raw.astype("string").eq("제주").all()
    assert raw.breed_assessment.astype("string").eq("api_native_label").all()
    assert raw.meet_code.astype("int64").eq(2).all()
    assert raw.payload_sha256.notna().all() and raw.payload_json.notna().all()
    return pd.DataFrame({
        "source_api_record_id": raw.api_record_id.astype("int64"),
        "trial_event_key": raw.trial_event_key.astype("string"),
        "trial_event_order": raw.trial_number.astype("int64"),
        "trial_date": raw.trial_date.astype("string"),
        "meet_code": raw.meet_code.astype("int64"),
        "trial_day_serial": raw.daySerial_raw.astype("int64"),
        "horse_id": raw.horse_id.astype("string"),
        "breed_label_raw": raw.breed_label_raw.astype("string"),
        "finish_time_seconds": pd.to_numeric(raw.rcTime_seconds_numeric, errors="coerce"),
        "trial_ord_raw": raw.raw_ord.astype("string"),
        "trial_judgment_raw": raw.raw_passFlag.astype("string"),
        "time_eligible": raw.valid_for_relative_time_candidate.astype(bool),
    })


def _compare_source_lineage(slots: pd.DataFrame, source_lineage: pd.DataFrame,
                            source_peer_ledger: pd.DataFrame,
                            cold_roster: pd.DataFrame,
                            features: pd.DataFrame) -> dict:
    assert len(source_lineage) == 3500 and source_lineage.target_trial_api_record_id.is_unique
    assert len(source_peer_ledger) == 3500
    assert source_lineage.trial_event_key.notna().all()
    assert source_lineage.trial_slot_rank_desc.ge(1).all()
    source_latest = source_lineage.loc[source_lineage.is_latest3_trial_record].copy()
    assert len(source_latest) == 3240
    expected_keys = set(zip(
        source_latest.target_api_record_id.astype("int64"),
        source_latest.target_trial_api_record_id.astype("int64"),
    ))
    actual_keys = set(zip(
        slots.target_api_record_id.astype("int64"), slots.source_api_record_id.astype("int64")
    ))
    assert actual_keys == expected_keys, "feature core's latest-three source rows differ from audit lineage"

    peers = source_peer_ledger[[
        "target_api_record_id", "target_trial_api_record_id", "target_relative_time_eligible",
        "valid_peer_count_excluding_target", "valid_peer_median_rcTime_seconds",
        "valid_peer_api_record_ids_json", "relative_time_gap_candidate_eligible",
        "relative_time_gap_candidate",
    ]].copy()
    joined = slots.merge(
        peers,
        left_on=["target_api_record_id", "source_api_record_id"],
        right_on=["target_api_record_id", "target_trial_api_record_id"],
        how="left", validate="one_to_one", suffixes=("_core", "_source"),
    )
    assert joined.valid_peer_count_excluding_target.notna().all()
    assert joined.peer_positive_time_n.astype("int64").equals(
        joined.valid_peer_count_excluding_target.astype("int64")
    )
    assert joined.source_time_eligible.astype(bool).equals(
        joined.target_relative_time_eligible.astype(bool)
    )
    source_gap_eligible = joined.relative_time_gap_candidate_eligible.astype(bool)
    core_gap_eligible = joined.relative_time.notna()
    assert source_gap_eligible.equals(core_gap_eligible)
    core_median = pd.to_numeric(joined.peer_median_time_seconds, errors="coerce").to_numpy(float)
    source_median = pd.to_numeric(joined.valid_peer_median_rcTime_seconds, errors="coerce").to_numpy(float)
    assert np.allclose(core_median, source_median, rtol=0, atol=0, equal_nan=True)
    core_gap = pd.to_numeric(joined.relative_time, errors="coerce").to_numpy(float)
    source_gap = pd.to_numeric(joined.relative_time_gap_candidate, errors="coerce").to_numpy(float)
    assert np.allclose(core_gap, source_gap, rtol=0, atol=1e-15, equal_nan=True)
    assert joined.peer_api_record_ids_json.astype("string").equals(
        joined.valid_peer_api_record_ids_json.astype("string")
    )

    mapped = slots[["target_api_record_id", "source_trial_date", "source_api_record_id"]].merge(
        source_latest[["target_api_record_id", "target_trial_api_record_id", "trial_date"]],
        left_on=["target_api_record_id", "source_api_record_id"],
        right_on=["target_api_record_id", "target_trial_api_record_id"],
        how="left", validate="one_to_one",
    )
    assert mapped.trial_date.astype("string").equals(mapped.source_trial_date.astype("string"))

    target_features = features.loc[
        features.observed_starts.eq(0), [
            "api_record_id", "trial_peer_relative_time_mean3", "trial_peer_relative_time_n3",
            "trial_days_since_latest_event_pre", "trial_event_count_pre",
        ]
    ].copy()
    counts = cold_roster[[
        "target_api_record_id", "trial_event_record_n_including_invalid_or_cancelled_rows",
        "latest3_relative_time_valid_n", "latest3_relative_time_gap_mean",
        "trial_latest_record_date", "race_date", "days_from_latest_record_to_cutoff",
    ]].copy()
    validation = target_features.merge(
        counts, left_on="api_record_id", right_on="target_api_record_id",
        how="left", validate="one_to_one",
    )
    assert len(validation) == 1946 and validation.trial_event_record_n_including_invalid_or_cancelled_rows.notna().all()
    assert validation.trial_event_count_pre.astype("int64").equals(
        validation.trial_event_record_n_including_invalid_or_cancelled_rows.astype("int64")
    )
    assert validation.trial_peer_relative_time_n3.astype("int64").equals(
        validation.latest3_relative_time_valid_n.astype("int64")
    )
    expected_mean = pd.to_numeric(validation.latest3_relative_time_gap_mean, errors="coerce").to_numpy(float)
    actual_mean = pd.to_numeric(validation.trial_peer_relative_time_mean3, errors="coerce").to_numpy(float)
    assert np.allclose(actual_mean, expected_mean, rtol=0, atol=1e-15, equal_nan=True)
    expected_days = pd.to_numeric(validation.days_from_latest_record_to_cutoff, errors="raise") + 2
    assert validation.trial_days_since_latest_event_pre.astype("int64").equals(expected_days.astype("int64"))
    root_reference = pd.read_parquet(ROOT_TRIAL_FEATURE_REFERENCE).sort_values(
        "api_record_id", kind="stable"
    ).reset_index(drop=True)
    observed_reference = target_features.sort_values("api_record_id", kind="stable").reset_index(drop=True)
    assert root_reference.api_record_id.astype("int64").equals(observed_reference.api_record_id.astype("int64"))
    root_reference_max_abs_error = 0.0
    for column in ADDED_FEATURES:
        expected_values = pd.to_numeric(root_reference[column], errors="coerce").to_numpy(float)
        actual_values = pd.to_numeric(observed_reference[column], errors="coerce").to_numpy(float)
        assert np.allclose(actual_values, expected_values, rtol=0, atol=1e-12, equal_nan=True), (
            f"independent root trial feature reference mismatch: {column}"
        )
        finite = np.isfinite(expected_values) & np.isfinite(actual_values)
        if finite.any():
            root_reference_max_abs_error = max(
                root_reference_max_abs_error,
                float(np.max(np.abs(actual_values[finite] - expected_values[finite]))),
            )
    return {
        "latest3_slots_exactly_match_source_lineage": True,
        "selected_slot_rows_compared_to_source_peer_ledger": int(len(joined)),
        "peer_count_median_gap_and_peer_ids_match": True,
        "cold_record_counts_latest3_n_mean_and_recency_match_source_roster": True,
        "all_four_features_match_independent_root_reference_with_1e_12_abs_tolerance": True,
        "independent_root_reference_rows": int(len(root_reference)),
        "independent_root_reference_max_abs_error": root_reference_max_abs_error,
        "source_target_event_records": int(len(source_lineage)),
        "source_latest3_records": int(len(source_latest)),
    }


def _input_entry(path: Path) -> dict:
    return {"sha256": sha256(path), "bytes": int(path.stat().st_size)}


def build() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    for output in (FEATURE_FILE, SLOT_FILE, LINEAGE_FILE, PREFLIGHT_FILE, PREPARED_LOCK_FILE):
        assert not output.exists(), f"refusing to overwrite prepared output: {output.name}"
    manifest = _check_source_manifest()
    baseline = pd.read_parquet(BASELINE_FEATURES)
    assert len(baseline) == 52155 and baseline.api_record_id.is_unique
    assert len(BASE_COLUMNS) == 30 and list(BASE_COLUMNS) == json.loads(
        (STYLE_OUT / "F1_STYLE6_2024/meta.json").read_text(encoding="utf-8")
    )["features"]
    cold_roster = pd.read_parquet(SOURCE_OUT / "cold_target_roster.parquet")
    targets = cold_roster.rename(columns={
        "target_api_record_id": "api_record_id",
        "observed_starts_baseline": "observed_starts",
    })[["api_record_id", "race_id", "race_date", "history_cutoff", "horse_id", "observed_starts"]].copy()
    raw_events = pd.read_parquet(SOURCE_OUT / "api20_trial_event_rows.parquet")
    source_rows = _normalize_trial_rows(raw_events)
    features, selected_slots = add_features(baseline, targets, source_rows)
    source_lineage = pd.read_parquet(SOURCE_OUT / "cold_target_trial_lineage.parquet")
    source_peer_ledger = pd.read_parquet(SOURCE_OUT / "trial_event_relative_peer_ledger.parquet")
    peer_checks = _compare_source_lineage(
        selected_slots, source_lineage, source_peer_ledger, cold_roster, features
    )

    eval_features = features.loc[features.year.ge(2024)].copy()
    cold = features.observed_starts.eq(0)
    cold_eval = cold & features.year.ge(2024)
    experienced = ~cold
    assert len(eval_features) == 17412 and eval_features.race_id.nunique() == 1779
    assert int(cold.sum()) == 1946 and int(cold_eval.sum()) == 661
    assert int(features.loc[cold_eval, "race_id"].nunique()) == 252
    assert features.loc[experienced, ADDED_FEATURES].isna().all().all()
    assert features.loc[cold, ADDED_FEATURES[1]].notna().all()
    assert features.loc[cold, ADDED_FEATURES[3]].notna().all()
    assert features.loc[cold, ADDED_FEATURES[1]].between(0, 3).all()
    assert features.loc[cold & features[ADDED_FEATURES[1]].eq(0), ADDED_FEATURES[0]].isna().all()
    assert features.loc[cold & features[ADDED_FEATURES[3]].eq(0), [ADDED_FEATURES[0], ADDED_FEATURES[2]]].isna().all().all()
    pd.testing.assert_frame_equal(
        features[baseline.columns].reset_index(drop=True), baseline.reset_index(drop=True), check_exact=True
    )
    cold_by_year = {}
    for year in (2024, 2025, 2026):
        rows = features.loc[cold & features.year.eq(year)]
        cold_by_year[str(year)] = {"rows": int(len(rows)), "races": int(rows.race_id.nunique())}
    assert cold_by_year == {"2024": {"rows": 224, "races": 90},
                            "2025": {"rows": 246, "races": 89},
                            "2026": {"rows": 191, "races": 73}}
    replay_path = OUT / "baseline_replay_verification.json"
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    assert replay.get("passed") is True and replay.get("baseline_models_reloaded") == 3
    assert replay.get("candidate_fit_models") == 0 and replay.get("candidate_outcome_metrics_computed") is False

    # Persist only after all in-memory source, cohort, baseline, and independent
    # feature-reference checks have passed.
    _write_parquet_new(FEATURE_FILE, features)
    _write_parquet_new(SLOT_FILE, selected_slots)
    _write_parquet_new(LINEAGE_FILE, source_lineage)

    source_summary = json.loads(SOURCE_SUMMARY.read_text(encoding="utf-8"))
    audit_entries = manifest["outputs"]
    input_paths = {
        BASELINE_FEATURES,
        replay_path,
        ROOT_EVALUATION_CONTRACT,
        ROOT_SOURCE_LOCK,
        ROOT_EXAMPLE_SELECTION,
        ROOT_TRIAL_FEATURE_REFERENCE,
        SOURCE_DIR / "audit_source.py",
        SOURCE_DIR / "README.md",
        SOURCE_MANIFEST,
        SOURCE_SUMMARY,
        *(STYLE_OUT / f"F1_STYLE6_{year}/{filename}" for year in YEARS for filename in (
            "top3.txt", "meta.json", "calibration_scores.parquet", "evaluation_scores.parquet")),
    }
    input_paths.update(_safe_child(SOURCE_OUT, name) for name in SOURCE_ARTIFACTS)
    input_paths.update(OUT / name for name in (
        "baseline_replayed_runner_predictions.parquet",
        "baseline_replayed_race_metrics.parquet",
        "baseline_replayed_canonical_max6.parquet",
    ))
    input_files = {}
    for path in sorted(input_paths, key=lambda item: str(item)):
        assert path.is_file(), f"missing frozen source artifact: {path}"
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
        input_files[relative] = _input_entry(path)
    for name in (FEATURE_FILE.name, SLOT_FILE.name, LINEAGE_FILE.name):
        path = OUT / name
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
        input_files[relative] = _input_entry(path)
    code_files = (
        "PLAN.md", "CONTRACT.md", "feature_core.py", "prepare_input.py",
        "baseline_replay.py", "train_candidate.py", "selftest_feature_core.py",
    )
    code_hashes = {name: sha256(HERE / name) for name in code_files}
    preflight = {
        "passed": True,
        "candidate": VARIANT,
        "candidate_feature_count": int(len(FEATURE_COLUMNS)),
        "base_feature_values_exact": True,
        "source_audit_passed": True,
        "source_audit_manifest_sha256": sha256(SOURCE_MANIFEST),
        "source_audit_summary_sha256": sha256(SOURCE_SUMMARY),
        "input_dataset": {
            "features_rows": int(len(features)),
            "features_columns_context_and_model": int(features.shape[1]),
            "base_model_features": int(len(BASE_COLUMNS)),
            "candidate_model_features": int(len(FEATURE_COLUMNS)),
            "candidate_feature_count": int(len(FEATURE_COLUMNS)),
            "added_model_features": ADDED_FEATURES,
            "base_feature_values_exact": True,
            "row_order_exact": True,
            "labels_and_splits_unchanged": True,
            "training_period": [str(features.race_date.min()), str(features.race_date.max())],
            "evaluation_period": [str(eval_features.race_date.min()), str(eval_features.race_date.max())],
            "full_rows": int(len(features)),
            "full_races": int(features.race_id.nunique()),
            "evaluation_rows": int(len(eval_features)),
            "evaluation_races": int(eval_features.race_id.nunique()),
            "evaluation_race_days": int(eval_features.race_date.nunique()),
            "cold_rows_all": int(cold.sum()),
            "cold_rows_evaluation": int(cold_eval.sum()),
            "cold_races_evaluation": int(features.loc[cold_eval, "race_id"].nunique()),
            "cold_evaluation_by_year": cold_by_year,
        },
        "source_support": {
            "full_linked_event_roster_rows": 8824,
            "full_linked_event_roster_horses": 3194,
            "target_horse_event_records_through_T_minus_2": 3500,
            "target_horses_with_record": 1946,
            "validated_event_keys": 961,
            "latest_three_target_slots": 3240,
            "latest_three_slots_with_valid_relative_signal": 3168,
            "all_target_events_have_two_peer_support_if_target_valid": True,
            "all_explicit_jeju_trial_record_date_range": [
                str(source_summary["current_api20_explicit_jeju_scope"]["date_min"]),
                str(source_summary["current_api20_explicit_jeju_scope"]["date_max"]),
            ],
            "target_linked_event_date_range_through_individual_cutoffs": [
                str(raw_events.trial_date.min()), str(raw_events.trial_date.max())
            ],
            "event_date_is_publication_time": False,
            "rcDist_explicit_field_rows": 0,
            "only_api20": True,
            "api21_current_profile_or_training_joined": False,
            "peer_source_crosschecks": peer_checks,
        },
        "null_and_range_checks": {
            "experienced_rows": int(experienced.sum()),
            "experienced_added_fields_all_null": True,
            "cold_rows": int(cold.sum()),
            "cold_n_count_all_present": True,
            "cold_valid_n_range": [0, 3],
            "cold_mean_null_exactly_when_valid_n_zero": True,
            "cold_count_zero_rows": int(features.loc[cold, ADDED_FEATURES[3]].eq(0).sum()),
            "cold_mean_and_recency_null_when_count_zero": True,
            "selected_latest_three_slot_rows": int(len(selected_slots)),
            "invalid_or_cancelled_rows_retained_in_slot_count": True,
            "no_backfill_after_invalid_latest_slot": True,
        },
        "baseline_replay": {
            "passed": True,
            "models_reloaded": 3,
            "raw_score_replay_exact": True,
            "raw_score_max_abs_error": 0.0,
            "candidate_fit_models": 0,
            "candidate_outcome_metrics_computed": False,
        },
        "candidate_fit_models": 0,
        "lightgbm_train_calls": 0,
        "temperature_optimizations": 0,
        "candidate_outcome_metrics_computed": False,
        "candidate_scores_computed": False,
        "results_viewed": False,
        "code_sha256": code_hashes,
        "output_sha256": {
            FEATURE_FILE.name: sha256(FEATURE_FILE),
            SLOT_FILE.name: sha256(SLOT_FILE),
            LINEAGE_FILE.name: sha256(LINEAGE_FILE),
        },
    }
    _write_json_new(PREFLIGHT_FILE, preflight)
    prepared_lock = {
        "variant": VARIANT,
        "input_files": input_files,
        "study_code_sha256": code_hashes,
        "prepared_artifacts": {
            FEATURE_FILE.name: _input_entry(FEATURE_FILE),
            SLOT_FILE.name: _input_entry(SLOT_FILE),
            LINEAGE_FILE.name: _input_entry(LINEAGE_FILE),
            PREFLIGHT_FILE.name: _input_entry(PREFLIGHT_FILE),
        },
        "source_audit_manifest_sha256": sha256(SOURCE_MANIFEST),
        "baseline_replay_sha256": sha256(replay_path),
        "baseline_models_refit": 0,
        "candidate_fit_models": 0,
        "candidate_outcome_metrics_computed": False,
        "whole_database_hash_checked": False,
    }
    _write_json_new(PREPARED_LOCK_FILE, prepared_lock)
    print(json.dumps({
        "passed": True,
        "candidate": VARIANT,
        "features": str(FEATURE_FILE.relative_to(ROOT)),
        "feature_rows": int(len(features)),
        "feature_columns": int(features.shape[1]),
        "candidate_model_columns": len(FEATURE_COLUMNS),
        "selected_slots": int(len(selected_slots)),
        "candidate_fit_models": 0,
        "candidate_outcome_metrics_computed": False,
        "preflight_sha256": sha256(PREFLIGHT_FILE),
        "prepared_lock_sha256": sha256(PREPARED_LOCK_FILE),
    }, ensure_ascii=False, indent=2))
    return preflight


if __name__ == "__main__":
    build()
