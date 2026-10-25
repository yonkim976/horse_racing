"""Freeze evaluator source and all post-fit inputs before metric computation."""
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
    "cold_primary_metrics.parquet",
    "cold_primary_bootstrap_draws.parquet",
    "cold_raw_score_concordance_by_race.parquet",
    "race_diagnostic_comparisons.parquet",
    "runner_scope_comparisons.parquet",
    "cold_trial_signal_support.parquet",
    "frozen_2026_01_02_jeju1r_example.csv",
    "evaluation_summary.json",
    "evaluation_report_receipt.json",
)


def freeze() -> dict:
    assert not LOCK_PATH.exists(), "evaluation source lock already exists"
    assert not any((OUT / name).exists() for name in REPORT_OUTPUTS), "metric/report output exists before freeze"
    fit_lock_path = OUT / "prepared_lock.json"
    approval_path = OUT / "root_fit_approval.json"
    completion_path = OUT / "candidate_training_completion.json"
    fit_lock = json.loads(fit_lock_path.read_text(encoding="utf-8"))
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    assert approval.get("approved") is True and approval.get("approved_by") == "root"
    assert approval.get("prepared_lock_sha256") == sha256(fit_lock_path)
    assert completion.get("passed") is True and completion.get("candidate_models") == 3
    assert completion.get("lightgbm_train_calls") == 6 and completion.get("temperature_optimizations") == 3
    assert completion.get("candidate_outcome_metrics_computed") is False

    files: dict[str, dict] = {}

    def add(path: Path, role: str) -> None:
        path = Path(path).resolve()
        assert path.is_relative_to(ROOT.resolve()), f"report input outside repository root: {path}"
        relative = path.relative_to(ROOT.resolve()).as_posix()
        entry = {"bytes": int(path.stat().st_size), "sha256": sha256(path), "role": role}
        if relative in files:
            assert files[relative]["sha256"] == entry["sha256"]
        else:
            files[relative] = entry

    for relative, entry in fit_lock["input_files"].items():
        path = ROOT / relative
        assert path.is_file() and path.stat().st_size == int(entry["bytes"])
        assert sha256(path) == entry["sha256"], f"pre-fit input changed: {relative}"
        files[relative] = {**entry, "role": "inherited pre-fit input"}
    for path, role in (
        (fit_lock_path, "frozen 34-input features and source lock"),
        (OUT / "preflight_verification.json", "source and feature preflight"),
        (approval_path, "root fit approval"),
        (OUT / "fit_execution_started.json", "one-shot fit start receipt"),
        (completion_path, "three-fold fit completion receipt"),
        (OUT / "candidate_scores_fit_stage.parquet", "frozen candidate out-of-sample raw scores"),
        (OUT / "evaluation_failed_attempt_audit.json", "transparent record of the schema-only failed reporting attempt"),
        (OUT / "evaluation_source_lock_failed_attempt.json", "preserved initial evaluator lock used by the failed attempt"),
        (OUT / "baseline_replayed_runner_predictions.parquet", "saved-baseline replay predictions"),
        (OUT / "baseline_replayed_race_metrics.parquet", "saved-baseline replay race metrics"),
        (OUT / "baseline_replayed_canonical_max6.parquet", "saved-baseline replay six-combination metrics"),
        (HERE / "evaluate_candidate.py", "frozen post-fit evaluator source"),
        (HERE / "selftest_evaluator.py", "synthetic evaluator verification"),
        (HERE / "freeze_evaluation_source.py", "report input lock generator"),
        (ROOT / "jeju/research/20261018_debut_trial_rootreview_v1/ROOT_EVALUATION_CONTRACT.json",
         "preregistered primary and secondary evaluation contract"),
        (ROOT / "jeju/research/20261018_debut_trial_rootreview_v1/ROOT_EXAMPLE_SELECTION.json",
         "prefit-fixed human example selection"),
        (ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy",
         "fixed paired date bootstrap schedule"),
        (ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json",
         "fixed schedule and date inventory receipt"),
    ):
        add(path, role)
    for year in YEARS:
        folder = OUT / f"F1_STYLE6_DEBUT_TRIAL4_{year}"
        for name in ("top3.txt", "meta.json", "calibration_scores.parquet", "evaluation_scores.parquet"):
            add(folder / name, "frozen candidate model, calibration, or OOS score")

    lock = {
        "lock_status": "FROZEN_BEFORE_FINAL_REPORT_OUTPUT",
        "study": HERE.name,
        "candidate": "F1_STYLE6_DEBUT_TRIAL4",
        "evaluator": "evaluate_candidate.py",
        "evaluator_sha256": sha256(HERE / "evaluate_candidate.py"),
        "freezer_sha256": sha256(HERE / "freeze_evaluation_source.py"),
        "selftest_sha256": sha256(HERE / "selftest_evaluator.py"),
        "fit_lock_sha256": sha256(fit_lock_path),
        "fit_approval_sha256": sha256(approval_path),
        "candidate_training_completion_sha256": sha256(completion_path),
        "successful_reports_before_lock": 0,
        "failed_evaluation_attempts_before_lock": 1,
        "failed_attempt_metrics_computed_in_memory": True,
        "failed_attempt_outputs_written_or_values_emitted": False,
        "fixed_scope": {
            "primary": "Runner-binary Top3 LL and Brier, cold runners average within race, then equal race weighting.",
            "cold_runner_rows": 661,
            "cold_races": 252,
            "bootstrap_draws": 2000,
            "bootstrap_dates_per_draw": 269,
            "bootstrap_schedule_sha256": "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd",
            "bootstrap_missing_cold_dates": "Contribute zero race-loss sum and zero race count; no remapping.",
            "cold_concordance": "118 eligible races, 398 cross-label pairs; raw score, exact ties 0.5; descriptive only.",
            "human_example": "All eight observed_starts=0 runners in the frozen 2026-01-02 Jeju 1R.",
            "no_variants_or_refits": True,
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
