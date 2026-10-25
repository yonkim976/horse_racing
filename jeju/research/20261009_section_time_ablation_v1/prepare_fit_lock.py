"""Create the scoped, pre-authorization lock receipt for the candidate fit."""
import sys

sys.dont_write_bytecode = True

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
F1_DIR = ROOT / "jeju/research/20261009_finish_history_ablation_v1"
F1_OUT = F1_DIR / "outputs"
REVIEW = ROOT / "jeju/research/20261009_section_ablation_review_v1"
TIME_REVIEW = ROOT / "jeju/research/20261002_section_passing_audit/website_time_check"
CONFLICT_REVIEW = ROOT / "jeju/research/20261003_unresolved_section_review"
LOCK_PATH = OUT / "prefit_lock.json"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def relative(path):
    return str(Path(path).relative_to(ROOT).as_posix())


def main():
    if LOCK_PATH.exists():
        raise FileExistsError(f"refusing to overwrite prefit lock: {LOCK_PATH}")
    audit = json.loads((OUT / "source_availability_audit.json").read_text(encoding="utf-8"))
    candidate = json.loads((OUT / "candidate_feature_preflight.json").read_text(encoding="utf-8"))
    replay = json.loads((OUT / "f1_saved_model_replay.json").read_text(encoding="utf-8"))
    assert audit["audit_status"] == "availability_only_preflight"
    assert all(audit["preflight_checks"].values())
    runner_preflight = json.loads((OUT / "fit_runner_preflight.json").read_text(encoding="utf-8"))
    assert candidate["passed"] and replay["passed"] and runner_preflight["passed"]
    assert candidate["fit_executed"] is False and replay["model_refit_count"] == 0
    assert replay["temperature_optimization_count"] == 0

    prior_lock_path = F1_OUT / "prepared_lock.json"
    prior_lock = json.loads(prior_lock_path.read_text(encoding="utf-8"))
    protected = {}
    for path, prior in prior_lock["protected"].items():
        current_path = ROOT / path
        current = {"bytes": current_path.stat().st_size, "sha256": sha256(current_path)}
        assert current == {"bytes": prior["bytes"], "sha256": prior["sha256"]}, path
        protected[path] = current

    reference_paths = [
        HERE / "CONTRACT.md", HERE / "IMPLEMENTATION_PLAN.md",
        HERE / "audit_source_availability.py", HERE / "build_candidate_features.py",
        HERE / "replay_saved_f1.py", HERE / "fit_candidate.py", HERE / "prepare_fit_lock.py",
        HERE / "verify_fit_lock.py", HERE / "outputs/fit_runner_preflight.json",
        HERE / "outputs/source_availability_audit.json",
        HERE / "outputs/source_availability_by_group.csv",
        HERE / "outputs/source_valid_n_distribution.csv",
        HERE / "outputs/source_slot_section_times.parquet",
        HERE / "outputs/features_f1s.parquet",
        HERE / "outputs/candidate_feature_preflight.json",
        HERE / "outputs/f1_saved_model_replay.json",
        HERE / "outputs/f1_reproduced_runner_predictions.parquet",
        HERE / "outputs/f1_reproduced_race_metrics.csv",
        HERE / "outputs/f1_reproduced_six_combinations.csv",
        F1_DIR / "CONTRACT.md", F1_DIR / "README.md", F1_DIR / "prepare.py",
        F1_DIR / "run.py", F1_DIR / "verify.py", prior_lock_path,
        F1_OUT / "features.parquet", F1_OUT / "historical_lineage.parquet",
        F1_OUT / "source_audit_summary.json", F1_OUT / "final_verification.json",
        F1_OUT / "runner_predictions_canonical.parquet",
        F1_OUT / "race_metrics.csv", F1_OUT / "six_combinations.csv",
        F1_OUT / "operating_common_467_runner_predictions.parquet",
        F1_OUT / "operating_common_467_race_metrics.csv",
        F1_OUT / "operating_common_467_six_combinations.csv",
        ROOT / "jeju/research/20261008_horse_profile_baseline_v1/run.py",
        ROOT / "jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet",
        ROOT / "jeju/AGENTS.md", ROOT / "jeju/docs/RESTART_PLAN_20260928.md",
        ROOT / "jeju/review_documents/README.md",
        ROOT / "jeju/research/RESEARCH_PUBLICATION_POLICY.md",
        ROOT / "jeju/data/horse_exclusions.json",
        TIME_REVIEW / "application_manifest.json", TIME_REVIEW / "evidence.json",
        TIME_REVIEW / "guard_verification.json", TIME_REVIEW / "independent_review.json",
        CONFLICT_REVIEW / "summary.json", CONFLICT_REVIEW / "application_receipt.json",
        CONFLICT_REVIEW / "root_independent_verification.json",
        CONFLICT_REVIEW / "root_special_outcome_check.json",
        CONFLICT_REVIEW / "guard_verification.json",
        CONFLICT_REVIEW / "semantic_review/semantic_audit_summary.json",
        CONFLICT_REVIEW / "semantic_review/runner_point_audit.json",
        CONFLICT_REVIEW / "semantic_review/group_point_audit.json",
        REVIEW / "INDEPENDENT_SOURCE_REVIEW.md",
        REVIEW / "verify_source_availability_independently.py",
        REVIEW / "compare_candidate_source_audit_independently.py",
        REVIEW / "independent_candidate_support_comparison.json",
        REVIEW / "independent_outputs/independent_source_availability_receipt.json",
        REVIEW / "independent_outputs/independent_target_feature_reconstruction.csv",
        REVIEW / "independent_outputs/independent_slot_lineage_and_selected_times.csv",
        REVIEW / "independent_outputs/independent_support_by_distance_year_experience.csv",
    ]
    for year in (2024, 2025, 2026):
        folder = F1_OUT / f"F1_{year}"
        reference_paths.extend([folder / "top3.txt", folder / "meta.json", folder / "calibration_scores.parquet"])
    reference_hashes = {}
    for path in reference_paths:
        assert path.is_file(), f"missing scoped lock reference: {path}"
        reference_hashes[relative(path)] = {
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }

    time_manifest = json.loads((TIME_REVIEW / "application_manifest.json").read_text(encoding="utf-8"))
    conflict_summary = json.loads((CONFLICT_REVIEW / "summary.json").read_text(encoding="utf-8"))
    assert time_manifest["status"] == "applied_and_verified"
    assert time_manifest["review_rows"] == 4
    assert conflict_summary["review_order_fields"] == 70
    assert conflict_summary["review_group_points"] == 20
    assert conflict_summary["individual_order_fields_selected_null"] == 70
    assert conflict_summary["group_points_selected_null"] == 20

    receipt = {
        "receipt_type": "scoped_prefit_lock",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "created_at_kst": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
        "fit_authorization_state": "conditional_root_approval_granted",
        "root_conditional_approval_evidence": "Root directed: after the fit runner is locked, independent reviewer C confirms the existing F1 split/parameters/weights/initial-train vocabulary/temperature process, and before_fit passes, run the single three-year fit without waiting for another root reply and record approval evidence.",
        "approval_conditions": {
            "root_conditional_fit_authorization_recorded": True,
            "fit_runner_code_locked": True,
            "independent_fit_code_review_passed": False,
            "before_fit_check_passed": False,
        },
        "independent_fit_code_review": {
            "reviewer": "section_review",
            "status": "pending",
            "required_checks": [
                "existing F1 split boundaries",
                "same LightGBM parameters and race-equal weights",
                "initial-train-only categorical vocabulary",
                "existing temperature/calibration procedure",
                "exactly six train calls and three temperature optimizations",
            ],
        },
        "fit_scope": {
            "candidate": "F1S",
            "model_columns": [
                *json.loads((F1_OUT / "F1_2024/meta.json").read_text(encoding="utf-8"))["features"],
                "history_s1f_mean5_seconds", "history_s1f_valid_n",
                "history_g3f_mean5_seconds", "history_g3f_valid_n",
                "history_g1f_mean5_seconds", "history_g1f_valid_n",
            ],
            "model_column_count": 30,
            "evaluation_years": [2024, 2025, 2026],
            "candidate_models": 3,
            "lightgbm_train_calls": 6,
            "temperature_optimizations": 3,
            "seed": 20261008,
            "additional_features_or_search": False,
            "result_dependent_followup_fit": False,
        },
        "fit_executed": False,
        "temperature_optimization_executed": False,
        "prefit_gates": {
            "source_availability_audit_passed": True,
            "independent_source_audit_passed": True,
            "six_column_candidate_feature_preflight_passed": True,
            "frozen_f1_saved_model_replay_passed": True,
            "fit_runner_preflight_passed": True,
            "frozen_f1_scores_metrics_and_six_sets_match": True,
            "independent_fit_code_review_passed": False,
            "before_fit_check_passed": False,
        },
        "section_time_quality_evidence": {
            "quality_view": "jeju_race_postrace_sections_quality_2026",
            "quality_view_definition_sha256": audit["quality_source_access"]["quality_view_definition_sha256"],
            "quality_dependency_ddl_sha256": audit["quality_source_access"]["quality_view_dependency_ddl_sha256"],
            "four_reviewed_time_cases": time_manifest["case_values"],
            "time_review_evidence_sha256": time_manifest["evidence_sha256"],
            "unresolved_individual_order_fields": 70,
            "unresolved_group_points": 20,
            "unresolved_order_group_receipt_status": conflict_summary["status"],
        },
        "protected_live_state_sha256": protected,
        "scoped_reference_sha256": reference_hashes,
    }
    with LOCK_PATH.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({
        "receipt": relative(LOCK_PATH),
        "fit_authorization_state": receipt["fit_authorization_state"],
        "protected_paths": list(protected),
        "scoped_reference_count": len(reference_hashes),
        "created_at_kst": receipt["created_at_kst"],
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
