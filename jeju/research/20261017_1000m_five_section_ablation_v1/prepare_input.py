"""Prepare the frozen 40-column feature table and outcome-free preflight.

Reads only saved F1 artifacts and the separately frozen read-only source audit
bundle. It does not open the database, fit a candidate, or compute candidate
outcome metrics.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from feature_core import ADDED_FEATURES, SEGMENTS, add_history_features, _normalize_ids
from train_candidate import BASE_COLUMNS, ROOT, STYLE_DIR, STYLE_OUT, sha256, write_json_new, write_parquet_new


HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SOURCE_DIR = ROOT / "jeju/research/20261017_1000m_five_section_source_audit_v1"
SOURCE_AUDIT_PATH = SOURCE_DIR / "source_audit.json"
SOURCE_MANIFEST_PATH = SOURCE_DIR / "artifact_manifest.json"
BASE_FEATURES_PATH = STYLE_OUT / "features.parquet"
FINISH_FEATURES_PATH = ROOT / "jeju/research/20261009_finish_history_ablation_v1/outputs/features.parquet"
FINISH_LINEAGE_PATH = ROOT / "jeju/research/20261009_finish_history_ablation_v1/outputs/historical_lineage.parquet"
STYLE_LINEAGE_PATH = STYLE_OUT / "style_history_lineage.parquet"
BASELINE_REPLAY_PATH = OUT / "baseline_replay_verification.json"
BOOTSTRAP_PATH = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT_PATH = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
FEATURE_OUTPUT_PATH = OUT / "features_f1_style6_5section.parquet"
SLOT_OUTPUT_PATH = OUT / "historical_section_slot_ledger.parquet"
PREFLIGHT_PATH = OUT / "source_preflight.json"
LOCK_PATH = OUT / "prepared_lock.json"

SOURCE_OUTPUTS = (
    "target_1000m_roster.parquet",
    "target_last5_lineage.parquet",
    "api4_quality_source_snapshot.parquet",
    "target_last5_section_intervals.parquet",
    "source_race_point_quality_masks.parquet",
    "source_point_order_status_evidence.parquet",
    "source_point_group_status_evidence.parquet",
    "source_fingerprint_before_after.parquet",
    "section_time_reviews.parquet",
)
YEARS = (2024, 2025, 2026)


def _hash_entry(path: Path, role: str) -> dict:
    return {
        "bytes": int(path.stat().st_size),
        "sha256": sha256(path),
        "role": role,
    }


def _source_manifest_preflight() -> tuple[dict, dict]:
    manifest = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    audit = json.loads(SOURCE_AUDIT_PATH.read_text(encoding="utf-8"))
    assert manifest["manifest_status"] == "frozen_read_only_source_snapshot"
    assert manifest["audit_json"] == "source_audit.json"
    assert sha256(SOURCE_AUDIT_PATH) == manifest["audit_json_sha256"]
    assert audit["audit_status"] == "read_only_source_snapshot_complete"
    assert audit["database_access"]["uri_mode"] == "ro"
    assert audit["database_access"]["sqlite_query_only"] is True
    assert audit["database_access"]["quality_view_scan_count"] == 1
    assert audit["database_access"]["whole_database_hash_claimed_unchanged"] is False
    assert audit["database_access"]["api4_source_rows_before_after_fingerprints_equal"] is True
    assert audit["database_access"]["record_type_artifact_payload_page_sha_and_path_equal_before_after"] is True
    assert audit["database_access"]["api4_quality_view_fingerprint_matches_before_and_after"] is True

    for logical, item in manifest["inputs"].items():
        path = ROOT / item["path"]
        assert path.is_file(), f"missing frozen source input {logical}: {item['path']}"
        assert path.stat().st_size == int(item["bytes"]), f"source input size changed: {logical}"
        assert sha256(path) == item["sha256"], f"source input SHA changed: {logical}"
    assert manifest["inputs"]["saved_f1_target_features_parquet"]["path"] == str(
        FINISH_FEATURES_PATH.relative_to(ROOT)
    )
    assert manifest["inputs"]["saved_f1_historical_lineage_parquet"]["path"] == str(
        FINISH_LINEAGE_PATH.relative_to(ROOT)
    )

    for name in SOURCE_OUTPUTS:
        entry = manifest["outputs"][name]
        path = SOURCE_DIR / name
        assert path.is_file() and path.stat().st_size == int(entry["bytes"]), name
        assert sha256(path) == entry["sha256"], f"source bundle SHA mismatch: {name}"
    return manifest, audit


def _same_saved_lineage(source_lineage: pd.DataFrame, saved_lineage: pd.DataFrame,
                        target_ids: set[int]) -> int:
    exact = saved_lineage.loc[
        saved_lineage.history_kind.eq("last5_same_distance_start")
        & saved_lineage.target_api_record_id.astype("int64").isin(target_ids)
    ].copy()
    source = source_lineage.copy()
    source = source.loc[source.target_api_record_id.astype("int64").isin(target_ids)].copy()
    assert len(source) == 53828
    assert len(exact) == len(source)
    shared = [
        "target_api_record_id", "slot_oldest_to_newest", "source_api_record_id",
        "source_race_id", "source_race_date", "target_cutoff", "target_horse_id",
        "source_horse_id", "target_distance_m", "source_distance_m", "source_started",
        "starter_n", "event_rank_sequence_complete", "duplicate_horse_in_source_event",
        "raw_finish_position", "valid_individual_rank", "individual_top3",
    ]
    left = source[shared].sort_values(
        ["target_api_record_id", "slot_oldest_to_newest"], kind="stable"
    ).reset_index(drop=True)
    right = exact[shared].sort_values(
        ["target_api_record_id", "slot_oldest_to_newest"], kind="stable"
    ).reset_index(drop=True)
    left["target_api_record_id"] = left.target_api_record_id.astype("int64")
    right["target_api_record_id"] = right.target_api_record_id.astype("int64")
    left["source_api_record_id"] = left.source_api_record_id.astype("int64")
    right["source_api_record_id"] = right.source_api_record_id.astype("int64")
    left["slot_oldest_to_newest"] = left.slot_oldest_to_newest.astype("int64")
    right["slot_oldest_to_newest"] = right.slot_oldest_to_newest.astype("int64")
    assert_frame_equal(left, right, check_dtype=False, check_exact=True)
    return int(len(exact))


def _check_target_roster(base: pd.DataFrame, target: pd.DataFrame,
                         finish_features: pd.DataFrame) -> set[int]:
    distance = pd.to_numeric(base.distance_m, errors="raise")
    base_target = base.loc[distance.eq(1000)].copy()
    assert len(base_target) == 14457
    assert len(target) == 14457 and target.api_record_id.is_unique
    target_ids = set(target.api_record_id.astype("int64"))
    assert target_ids == set(base_target.api_record_id.astype("int64"))

    identity = [
        "api_record_id", "race_id", "race_date", "horse_id", "horse_number",
        "finish_position", "distance_m", "history_cutoff",
    ]
    left = base_target[identity].sort_values("api_record_id", kind="stable").reset_index(drop=True)
    right = target[identity].sort_values("api_record_id", kind="stable").reset_index(drop=True)
    assert_frame_equal(left, right, check_dtype=False, check_exact=True)
    finish_target = finish_features.loc[
        pd.to_numeric(finish_features.distance_m, errors="raise").eq(1000)
    ].copy()
    assert set(finish_target.api_record_id.astype("int64")) == target_ids
    assert_frame_equal(
        left,
        finish_target[identity].sort_values("api_record_id", kind="stable").reset_index(drop=True),
        check_dtype=False,
        check_exact=True,
    )

    base_ids = base.set_index("api_record_id")
    target_ids_order = target.sort_values("api_record_id", kind="stable").api_record_id.astype("int64")
    expected = target.sort_values("api_record_id", kind="stable").last5_same_source_ids.tolist()
    observed = base_ids.loc[target_ids_order, "last5_same_source_ids"].tolist()
    for target_id, actual_ids, expected_ids in zip(target_ids_order, observed, expected):
        assert _normalize_ids(actual_ids) == _normalize_ids(expected_ids), (
            f"saved last5 source-ID mismatch at target {target_id}"
        )
    return target_ids


def _slot_ledger(source_slots: pd.DataFrame, compact_slots: pd.DataFrame,
                 prepared_features: pd.DataFrame) -> pd.DataFrame:
    key = ["target_api_record_id", "slot_oldest_to_newest"]
    compact_columns = key + [
        "source_api_record_id", "source_race_id", "source_race_date", "source_horse_id",
        "valid_time",
    ]
    for spec in SEGMENTS:
        compact_columns.extend((
            f"{spec['key']}_seconds", f"{spec['key']}_source_quality_eligible",
            f"{spec['key']}_feature_eligible", f"{spec['key']}_ineligible_reason",
        ))
    compact = compact_slots[compact_columns].copy()
    raw = source_slots.copy()
    ledger = raw.merge(compact, on=key, how="left", validate="one_to_one", suffixes=("", "_computed"))
    assert len(ledger) == len(raw) and ledger.source_api_record_id.equals(
        ledger.source_api_record_id_computed.astype("int64")
    )
    mean_columns = [column for column in ADDED_FEATURES]
    targets = prepared_features[["api_record_id", *mean_columns]].rename(
        columns={"api_record_id": "target_api_record_id"}
    )
    ledger = ledger.merge(targets, on="target_api_record_id", how="left", validate="many_to_one")
    assert len(ledger) == len(raw)
    return ledger.sort_values(key, kind="stable").reset_index(drop=True)


def _locked_files(manifest: dict) -> dict:
    pinned: dict[str, dict] = {}

    def add(path: Path, role: str) -> None:
        relative = str(path.relative_to(ROOT))
        if relative in pinned:
            assert pinned[relative]["sha256"] == sha256(path)
            return
        pinned[relative] = _hash_entry(path, role)

    add(BASE_FEATURES_PATH, "saved F1_STYLE6 full-candidate input feature table")
    add(FINISH_FEATURES_PATH, "source audit target roster feature source")
    add(FINISH_LINEAGE_PATH, "source audit saved last5 lineage source")
    add(STYLE_LINEAGE_PATH, "saved F1_STYLE6 section feature lineage")
    add(BOOTSTRAP_PATH, "fixed paired-date bootstrap schedule")
    add(BOOTSTRAP_RECEIPT_PATH, "fixed paired-date schedule/date-inventory receipt")
    add(BASELINE_REPLAY_PATH, "saved baseline replay receipt")
    add(OUT / "baseline_replayed_runner_predictions.parquet", "saved baseline replay runner output")
    add(OUT / "baseline_replayed_race_metrics.parquet", "saved baseline replay race output")
    add(OUT / "baseline_replayed_canonical_max6.parquet", "saved baseline replay combination output")
    for name in ("CONTRACT.md", "PLAN.md", "feature_core.py", "prepare_input.py", "train_candidate.py", "replay_baseline.py", "selftest_feature_core.py"):
        add(HERE / name, "study contract or fit-critical code")
    add(FEATURE_OUTPUT_PATH, "prepared 40-column candidate feature table")
    add(SLOT_OUTPUT_PATH, "prepared exact-history interval audit ledger")

    # The fitted candidate imports these fixed source contracts and reads these
    # saved fold artifacts; no legacy prepared-lock/DB hash verifier is invoked.
    add(STYLE_DIR / "run.py", "saved STYLE6 fold/scoring constants")
    for year in YEARS:
        folder = STYLE_OUT / f"F1_STYLE6_{year}"
        for name in ("top3.txt", "meta.json", "calibration_scores.parquet", "evaluation_scores.parquet"):
            add(folder / name, "saved F1_STYLE6 model or fold artifact")
    for path in (
        STYLE_OUT / "report/runner_predictions.parquet",
        STYLE_OUT / "report/race_metrics.parquet",
        STYLE_OUT / "report/canonical_six_combinations.csv",
    ):
        add(path, "saved F1_STYLE6 evaluation outputs")

    add(SOURCE_MANIFEST_PATH, "frozen source snapshot manifest")
    add(SOURCE_AUDIT_PATH, "frozen source audit receipt")
    add(SOURCE_DIR / "extract_source_audit.py", "frozen source snapshot extractor")
    for name in SOURCE_OUTPUTS:
        add(SOURCE_DIR / name, "frozen source snapshot parquet")
    for item in manifest["inputs"].values():
        add(ROOT / item["path"], "source audit pinned input")
    return pinned


def prepare() -> dict:
    assert not FEATURE_OUTPUT_PATH.exists(), "prepared feature output already exists; refusing overwrite"
    assert not SLOT_OUTPUT_PATH.exists(), "history slot ledger already exists; refusing overwrite"
    assert not PREFLIGHT_PATH.exists(), "preflight receipt already exists; refusing overwrite"
    assert not LOCK_PATH.exists(), "prepared lock already exists; refusing overwrite"

    source_manifest, audit = _source_manifest_preflight()
    base = pd.read_parquet(BASE_FEATURES_PATH)
    finish_features = pd.read_parquet(FINISH_FEATURES_PATH)
    target = pd.read_parquet(SOURCE_DIR / "target_1000m_roster.parquet")
    source_lineage = pd.read_parquet(SOURCE_DIR / "target_last5_lineage.parquet")
    saved_lineage = pd.read_parquet(FINISH_LINEAGE_PATH)
    source_slots = pd.read_parquet(SOURCE_DIR / "target_last5_section_intervals.parquet")

    assert base.api_record_id.is_unique and len(base) == 52155
    assert len(BASE_COLUMNS) == 30
    assert set(BASE_COLUMNS).issubset(base.columns)
    assert list(base.loc[:, BASE_COLUMNS].columns) == BASE_COLUMNS
    target_ids = _check_target_roster(base, target, finish_features)
    exact_slots = _same_saved_lineage(source_lineage, saved_lineage, target_ids)
    assert exact_slots == 53828

    bootstrap_receipt = json.loads(BOOTSTRAP_RECEIPT_PATH.read_text(encoding="utf-8"))
    evaluation_dates = sorted(
        base.loc[base.year.isin(YEARS), "race_date"].astype("string").dropna().unique().tolist()
    )
    evaluation_date_hash = hashlib.sha256("\n".join(evaluation_dates).encode("utf-8")).hexdigest()
    schedule = np.load(BOOTSTRAP_PATH, allow_pickle=False)
    assert schedule.shape == (2000, 269)
    assert schedule.dtype.kind in "iu"
    assert schedule.min() >= 0 and schedule.max() < 269
    assert len(evaluation_dates) == 269
    assert bootstrap_receipt["status"] == "FROZEN_BEFORE_EVALUATION_METRICS"
    assert bootstrap_receipt["date_inventory_sha256"] == evaluation_date_hash
    assert bootstrap_receipt["schedule_sha256"] == sha256(BOOTSTRAP_PATH)
    assert bootstrap_receipt["schedule_shape"] == [2000, 269]

    features, compact_slots = add_history_features(base, target, source_slots)
    assert list(features.columns) == list(base.columns) + ADDED_FEATURES
    assert len(features) == 52155 and features.api_record_id.equals(base.api_record_id)
    assert len(compact_slots) == 53828
    assert set(features.loc[:, ADDED_FEATURES].columns) == set(ADDED_FEATURES)

    write_parquet_new(FEATURE_OUTPUT_PATH, features)
    ledger = _slot_ledger(source_slots, compact_slots, features.loc[features.api_record_id.isin(target_ids)])
    write_parquet_new(SLOT_OUTPUT_PATH, ledger)

    written_features = pd.read_parquet(FEATURE_OUTPUT_PATH)
    assert_frame_equal(written_features, features, check_exact=True)
    assert len(ledger) == 53828

    segment_summary = {}
    for spec in SEGMENTS:
        mean_col, n_col = spec["mean"], spec["n"]
        target_values = features.loc[features.api_record_id.isin(target_ids), [mean_col, n_col]]
        segment_summary[spec["key"]] = {
            "mean_feature": mean_col,
            "n_feature": n_col,
            "eligible_history_slots": int(source_slots[spec["feature_eligible"]].astype(bool).sum()),
            "targets_with_any_support": int(target_values[n_col].gt(0).sum()),
            "targets_with_five_support": int(target_values[n_col].eq(5).sum()),
            "target_n0_mean_null": bool(target_values.loc[target_values[n_col].eq(0), mean_col].isna().all()),
            "non_1000m_mean_and_n_all_null": bool(
                features.loc[~features.api_record_id.isin(target_ids), [mean_col, n_col]].isna().all().all()
            ),
        }
    assert all(item["target_n0_mean_null"] and item["non_1000m_mean_and_n_all_null"]
               for item in segment_summary.values())

    replay = json.loads(BASELINE_REPLAY_PATH.read_text(encoding="utf-8"))
    assert replay["passed"] is True and replay["baseline_models_reloaded"] == 3
    assert replay["runner_rows_reproduced"] == 17412
    assert replay["distinct_races_reproduced"] == 1779
    assert replay["canonical_max6_rows_reproduced"] == 10674
    assert replay["raw_score_replay_exact"] is True
    assert replay["candidate_fit_models"] == 0 and replay["candidate_outcome_metrics_computed"] is False

    lock = {
        "lock_status": "frozen_pre_fit_input_lock",
        "candidate": "F1_STYLE6_5SECTION",
        "input_scope": "saved F1_STYLE6 features and frozen source audit bundle; no database or registry reads",
        "fit_performed": False,
        "input_files": _locked_files(source_manifest),
        "feature_schema": {
            "baseline_feature_count": len(BASE_COLUMNS),
            "candidate_feature_count": len(BASE_COLUMNS) + len(ADDED_FEATURES),
            "baseline_features": BASE_COLUMNS,
            "added_features": ADDED_FEATURES,
            "feature_output": str(FEATURE_OUTPUT_PATH.relative_to(ROOT)),
            "feature_output_sha256": sha256(FEATURE_OUTPUT_PATH),
            "feature_output_bytes": int(FEATURE_OUTPUT_PATH.stat().st_size),
            "history_slot_ledger": str(SLOT_OUTPUT_PATH.relative_to(ROOT)),
            "history_slot_ledger_sha256": sha256(SLOT_OUTPUT_PATH),
            "history_slot_ledger_bytes": int(SLOT_OUTPUT_PATH.stat().st_size),
        },
        "predeclared_comparison": {
            "cohort_rows": 52155,
            "cohort_races": 5206,
            "evaluation_rows": 17412,
            "evaluation_races": 1779,
            "years": [2024, 2025, 2026],
            "target_distance_m": 1000,
            "target_rows": 14457,
            "target_races": 1424,
            "history_slots": 53828,
            "bootstrap_schedule": str(BOOTSTRAP_PATH.relative_to(ROOT)),
            "bootstrap_shape": [2000, 269],
            "bootstrap_sha256": sha256(BOOTSTRAP_PATH),
            "bootstrap_known_expected_sha256": "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
            "evaluation_date_count": len(evaluation_dates),
            "evaluation_date_inventory_sha256": evaluation_date_hash,
            "bootstrap_receipt_sha256": sha256(BOOTSTRAP_RECEIPT_PATH),
            "primary_metric": "runner Top3 binary logloss and Brier averaged within race, then equally across races",
            "candidate_fits": 3,
            "lightgbm_train_calls": 6,
            "temperature_optimizations": 3,
        },
    }
    assert lock["predeclared_comparison"]["bootstrap_sha256"] == lock["predeclared_comparison"]["bootstrap_known_expected_sha256"]
    write_json_new(LOCK_PATH, lock)

    preflight = {
        "passed": True,
        "status": "PASS_PREFIT_SOURCE_AND_FEATURE_PREPARATION",
        "study": HERE.name,
        "source_audit_manifest_sha256": sha256(SOURCE_MANIFEST_PATH),
        "source_audit_sha256": sha256(SOURCE_AUDIT_PATH),
        "prepared_lock_sha256": sha256(LOCK_PATH),
        "prepared_lock_path": str(LOCK_PATH.relative_to(ROOT)),
        "baseline_replay_sha256": sha256(BASELINE_REPLAY_PATH),
        "baseline_replay_passed": True,
        "saved_baseline_models_retrained": 0,
        "candidate_fit_models": 0,
        "candidate_outcome_metrics_computed": False,
        "candidate_score_files_created": False,
        "database_opened_by_preparation": False,
        "source_bundle_file_hashes_verified": len(SOURCE_OUTPUTS),
        "baseline_full_30_feature_rows_exactly_preserved": True,
        "saved_last5_ids_exactly_reconciled_to_lineage": exact_slots,
        "candidate_features_appended": ADDED_FEATURES,
        "candidate_feature_rows": int(len(features)),
        "candidate_feature_columns": int(len(features.columns)),
        "target_1000m_rows": int(len(target_ids)),
        "target_1000m_races": int(target.race_id.nunique()),
        "target_1000m_eval_rows_2024_2026": 5013,
        "target_1000m_eval_races_2024_2026": 508,
        "history_slot_ledger_rows": int(len(ledger)),
        "segment_support": segment_summary,
        "source_audit_checks": {
            "read_only_quality_view_single_scan": audit["database_access"]["quality_view_scan_count"] == 1,
            "full_roster_masks_and_fingerprints": True,
            "target_cutoff_is_race_date_minus_2": True,
            "valid_time_required_without_backfill": True,
            "g3f_identity_diagnostic_only": True,
        },
        "feature_output_sha256": sha256(FEATURE_OUTPUT_PATH),
        "history_slot_ledger_sha256": sha256(SLOT_OUTPUT_PATH),
        "bootstrap_schedule_sha256": sha256(BOOTSTRAP_PATH),
        "bootstrap_receipt_sha256": sha256(BOOTSTRAP_RECEIPT_PATH),
        "evaluation_date_count": len(evaluation_dates),
        "evaluation_date_inventory_sha256": evaluation_date_hash,
        "root_fit_approval_required_before_candidate_training": True,
    }
    write_json_new(PREFLIGHT_PATH, preflight)
    return preflight


if __name__ == "__main__":
    print(json.dumps(prepare(), ensure_ascii=False, indent=2))
