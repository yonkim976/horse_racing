"""Freeze report code and all prediction inputs before candidate metrics run."""
from __future__ import annotations

import json
from pathlib import Path

from train_candidate import OUT, ROOT, YEARS, sha256, write_json_new


HERE = Path(__file__).resolve().parent
LOCK_PATH = OUT / "evaluation_source_lock.json"
REPORT_OUTPUTS = (
    "candidate_evaluation_runner_predictions.parquet",
    "candidate_evaluation_race_metrics.parquet",
    "candidate_evaluation_canonical_max6.parquet",
    "paired_runner_metrics.parquet",
    "paired_race_metrics.parquet",
    "paired_canonical_max6.parquet",
    "evaluation_date_support.parquet",
    "race_metric_comparisons.parquet",
    "runner_metric_comparisons.parquet",
    "primary_1000m_bootstrap_draws.parquet",
    "all_1000m_profiles.parquet",
    "profile_examples.csv",
    "1000m_runner_comparison.parquet",
    "1000m_race_comparison.parquet",
    "evaluation_summary.json",
    "evaluation_report_receipt.json",
)


def freeze() -> dict:
    assert not LOCK_PATH.exists(), "evaluation source lock already exists; refusing to rewrite"
    assert not any((OUT / name).exists() for name in REPORT_OUTPUTS), (
        "report output exists; evaluation code must be frozen before metric computation"
    )
    fit_lock_path = OUT / "prepared_lock.json"
    fit_lock = json.loads(fit_lock_path.read_text(encoding="utf-8"))
    completion_path = OUT / "candidate_training_completion.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    approval_path = OUT / "root_fit_approval.json"
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    assert completion.get("passed") is True and completion.get("candidate_outcome_metrics_computed") is False
    assert completion.get("candidate_models") == 3 and completion.get("lightgbm_train_calls") == 6
    assert approval.get("approved") is True and approval.get("approved_by") == "root"
    assert approval.get("prepared_lock_sha256") == sha256(fit_lock_path)

    files: dict[str, dict] = {}

    def add(path: Path, role: str) -> None:
        relative = str(path.relative_to(ROOT))
        entry = {"bytes": int(path.stat().st_size), "sha256": sha256(path), "role": role}
        if relative in files:
            assert files[relative]["sha256"] == entry["sha256"]
        else:
            files[relative] = entry

    # Inherit all frozen baseline, source bundle, prepared feature, and code
    # hashes used to authorize the fit.
    for relative, entry in fit_lock["input_files"].items():
        path = ROOT / relative
        assert path.is_file() and path.stat().st_size == int(entry["bytes"])
        assert sha256(path) == entry["sha256"], f"fit lock input changed: {relative}"
        files[relative] = {**entry, "role": "inherited pre-fit lock input"}
    for path, role in (
        (fit_lock_path, "pre-fit feature and source lock"),
        (OUT / "source_preflight.json", "passing source and feature preflight"),
        (OUT / "root_fit_approval.json", "explicit root fit approval"),
        (OUT / "candidate_training_completion.json", "approved three-fold fit receipt"),
        (OUT / "candidate_scores_fit_stage.parquet", "frozen OOS raw scores"),
        (HERE / "evaluate_candidate.py", "frozen one-pass evaluator source"),
        (HERE / "selftest_evaluator.py", "outcome-free evaluator synthetic test"),
        (HERE / "freeze_evaluation_source.py", "report source lock generator"),
        (ROOT / "jeju/research/20261017_1000m_five_section_rootreview_v1/ROOT_FEATURE_REVIEW.json",
         "independent root source/feature arithmetic review"),
        (ROOT / "jeju/research/20261017_1000m_five_section_rootreview_v1/ROOT_BASELINE_REPLAY.json",
         "independent saved baseline replay review"),
        (ROOT / "jeju/research/20261017_1000m_five_section_design_review_v1/DESIGN_REVIEW.md",
         "read-only design review and availability limitation"),
    ):
        add(path, role)
    for year in YEARS:
        folder = OUT / f"F1_STYLE6_5SECTION_{year}"
        for name in ("top3.txt", "meta.json", "calibration_scores.parquet", "evaluation_scores.parquet"):
            add(folder / name, "frozen candidate fit artifact and OOS scores")

    lock = {
        "lock_status": "FROZEN_BEFORE_METRIC_EVALUATION",
        "study": HERE.name,
        "evaluator": "evaluate_candidate.py",
        "evaluator_sha256": sha256(HERE / "evaluate_candidate.py"),
        "freezer_sha256": sha256(HERE / "freeze_evaluation_source.py"),
        "fit_approval_sha256": sha256(approval_path),
        "candidate_training_completion_sha256": sha256(completion_path),
        "fit_lock_sha256": sha256(fit_lock_path),
        "report_metric_runs_before_lock": 0,
        "outcome_free_synthetic_test_required": True,
        "fixed_scope": {
            "primary_distance_m": 1000,
            "primary_years": [2024, 2025, 2026],
            "primary_races": 508,
            "primary_runner_rows": 5013,
            "metric": "runner Top3 binary logloss and Brier, average within race then race-equal",
            "delta_sign": "candidate minus saved F1_STYLE6",
            "bootstrap_dates": 269,
            "bootstrap_draws": 2000,
            "bootstrap_schedule_sha256": "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
            "sparse_auxiliary_zero_denominator_draws": "excluded from CI quantiles with valid_draw_count reported; fixed schedule unchanged; primary must have all 2000 valid draws",
            "profile_example_rule": "First 2024-2026 evaluation row in stable race_date,race_id,horse_number,api_record_id order per segment and n bucket 0,1,2-4,5; no target outcomes used.",
        },
        "input_files": files,
        "candidate_outcome_metrics_computed": False,
        "candidate_refit_after_approval": False,
        "production_changed": False,
        "database_changed": False,
    }
    write_json_new(LOCK_PATH, lock)
    return lock


if __name__ == "__main__":
    print(json.dumps(freeze(), ensure_ascii=False, indent=2))
