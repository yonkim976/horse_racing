"""Write the final immutable study inventory and provenance receipt."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "outputs"
MANIFEST = OUT / "FINAL_MANIFEST.json"
ROOT_REVIEW = ROOT / "jeju/research/20261018_debut_trial_rootreview_v1/ROOT_REPORT_REVIEW.json"
ROOT_NUMERIC_REVIEW = ROOT / "jeju/research/20261018_debut_trial_rootreview_v1/ROOT_REPORT_NUMERIC_ADDENDUM.json"
CODE_FILES = (
    "PLAN.md", "CONTRACT.md", "README.md", "feature_core.py", "prepare_input.py",
    "baseline_replay.py", "train_candidate.py", "selftest_feature_core.py",
    "evaluate_candidate.py", "selftest_evaluator.py", "freeze_evaluation_source.py",
    "write_final_manifest.py",
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write() -> dict:
    assert not MANIFEST.exists(), "refusing to overwrite final manifest"
    summary_path = OUT / "evaluation_summary.json"
    report_receipt_path = OUT / "evaluation_report_receipt.json"
    preflight_path = OUT / "preflight_verification.json"
    fit_receipt_path = OUT / "candidate_training_completion.json"
    fit_approval_path = OUT / "root_fit_approval.json"
    for path in (summary_path, report_receipt_path, preflight_path, fit_receipt_path,
                 fit_approval_path, ROOT_REVIEW, ROOT_NUMERIC_REVIEW):
        assert path.is_file(), f"missing final evidence file: {path}"

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    report_receipt = json.loads(report_receipt_path.read_text(encoding="utf-8"))
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    fit_receipt = json.loads(fit_receipt_path.read_text(encoding="utf-8"))
    fit_approval = json.loads(fit_approval_path.read_text(encoding="utf-8"))
    independent_review = json.loads(ROOT_REVIEW.read_text(encoding="utf-8"))
    numeric_review = json.loads(ROOT_NUMERIC_REVIEW.read_text(encoding="utf-8"))
    assert summary["primary_gate_passed"] is True
    assert report_receipt["passed"] is True and report_receipt["primary_gate_passed"] is True
    assert fit_receipt["passed"] is True and fit_receipt["candidate_models"] == 3
    assert fit_approval["approved"] is True and fit_approval["approved_by"] == "root"
    assert preflight["passed"] is True and preflight["candidate_fit_models"] == 0
    assert independent_review["status"] == "PASS"
    assert independent_review["evaluation_summary_sha256"] == sha256(summary_path)
    assert numeric_review["status"] == "PASS"

    artifacts = []
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path != MANIFEST:
            artifacts.append({
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": int(path.stat().st_size),
                "sha256": sha256(path),
            })
    code = {
        name: {"bytes": int((HERE / name).stat().st_size), "sha256": sha256(HERE / name)}
        for name in CODE_FILES
    }
    prepared_lock = json.loads((OUT / "prepared_lock.json").read_text(encoding="utf-8"))
    eval_lock = json.loads((OUT / "evaluation_source_lock.json").read_text(encoding="utf-8"))
    failed_attempt = json.loads((OUT / "evaluation_failed_attempt_audit.json").read_text(encoding="utf-8"))
    manifest = {
        "manifest_status": "FINAL_COMPLETE_NOT_PROMOTED",
        "study": HERE.name,
        "created_date": "2026-10-18",
        "candidate": "F1_STYLE6_DEBUT_TRIAL4",
        "comparison_baseline": "saved F1_STYLE6 horse-assessment model; exact replay, no refit",
        "scope": "One approved 34-input candidate; retrospective evaluation; no model promotion.",
        "fit": {
            "approved_by": fit_approval["approved_by"],
            "approval_sha256": sha256(fit_approval_path),
            "candidate_models": int(fit_receipt["candidate_models"]),
            "lightgbm_train_calls": int(fit_receipt["lightgbm_train_calls"]),
            "temperature_optimizations": int(fit_receipt["temperature_optimizations"]),
            "no_refit_after_fit": bool(fit_receipt["no_refit_after_this_point"]),
        },
        "evaluation": {
            "report_receipt_sha256": sha256(report_receipt_path),
            "summary_sha256": sha256(summary_path),
            "primary_gate_passed": bool(summary["primary_gate_passed"]),
            "primary_metrics": summary["primary_metrics"],
            "cold_raw_score_concordance": summary["cold_raw_score_concordance"],
            "experienced_score_diagnostic": summary["experienced_score_diagnostic"],
            "evaluation_source_lock_sha256": sha256(OUT / "evaluation_source_lock.json"),
        },
        "source_and_preflight": {
            "preflight_sha256": sha256(preflight_path),
            "prepared_lock_sha256": sha256(OUT / "prepared_lock.json"),
            "source_audit_manifest_sha256": prepared_lock["source_audit_manifest_sha256"],
            "feature_rows": int(preflight["input_dataset"]["features_rows"]),
            "base_inputs_exact_and_in_order": bool(preflight["input_dataset"]["base_feature_values_exact"] and preflight["input_dataset"]["row_order_exact"]),
            "candidate_model_input_count": int(preflight["input_dataset"]["candidate_model_features"]),
        },
        "fit_error_history": {
            "failed_evaluation_attempts": 1,
            "successful_report_runs": 1,
            "failed_attempt_audit_sha256": sha256(OUT / "evaluation_failed_attempt_audit.json"),
            "initial_failed_source_lock_sha256": failed_attempt["initial_evaluation_source_lock_sha256"],
            "initial_failed_evaluator_sha256": failed_attempt["initial_evaluator_sha256"],
            "failed_attempt_metrics_computed_in_memory_but_not_emitted_or_saved": True,
            "final_correction_scope": failed_attempt["correction_scope"],
        },
        "independent_root_review": {
            "path": ROOT_REVIEW.relative_to(ROOT).as_posix(),
            "sha256": sha256(ROOT_REVIEW),
            "status": independent_review["status"],
            "protected_artifacts_unchanged": int(independent_review["protected_artifacts_unchanged"]),
            "summary_sha256_verified": independent_review["evaluation_summary_sha256"],
        },
        "independent_root_numeric_review": {
            "path": ROOT_NUMERIC_REVIEW.relative_to(ROOT).as_posix(),
            "sha256": sha256(ROOT_NUMERIC_REVIEW),
            "status": numeric_review["status"],
            "runner_scope_rows_verified": int(numeric_review["runner_scope_rows_verified"]),
            "race_diagnostic_rows_verified": int(numeric_review["race_diagnostic_rows_verified"]),
            "primary_bootstrap_values_verified": int(numeric_review["primary_bootstrap_values_verified"]),
            "summary_output_hashes_verified": int(numeric_review["summary_output_hashes_verified"]),
        },
        "guardrails": {
            "production_changed": False,
            "operating_model_promoted": False,
            "database_changed": False,
            "existing_pair_order_heads_refit": False,
            "variants_or_post_result_tuning": False,
        },
        "study_code": code,
        "output_artifacts": artifacts,
    }
    with MANIFEST.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return manifest


if __name__ == "__main__":
    result = write()
    print(json.dumps({
        "manifest": str(MANIFEST.relative_to(ROOT)),
        "artifacts": len(result["output_artifacts"]),
        "primary_gate_passed": result["evaluation"]["primary_gate_passed"],
        "sha256": sha256(MANIFEST),
    }, ensure_ascii=False, indent=2))
