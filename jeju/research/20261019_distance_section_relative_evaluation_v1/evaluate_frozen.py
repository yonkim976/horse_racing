"""Hash-gated, one-pass evaluation for frozen F1_STYLE6 distance-section models.

This evaluator consumes saved baseline/candidate raw scores and frozen feature
tables. It never fits or predicts a model and never opens the project database.
Preflight checks identities and hashes without joining scores to target labels.
Metric computation is blocked until a root EVAL_APPROVAL binds this exact code
and the immutable input-lock receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STUDY_ID = "20261019_distance_section_relative_ablation_v1"
STUDY_DIR = ROOT / "jeju/research" / STUDY_ID
STUDY_OUT = STUDY_DIR / "outputs"
BASELINE_DIR = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs"
FEATURE_PATH = STUDY_OUT / "features_f1_style6_distance_section_relative10.parquet"
BASE_FEATURE_PATH = BASELINE_DIR / "features.parquet"
BOOTSTRAP_PATH = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy"
BOOTSTRAP_RECEIPT_PATH = ROOT / "jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.json"
YEARS = (2024, 2025, 2026)
TARGET_DISTANCES = (900, 1000, 1110, 1200)
VARIANT = "F1_STYLE6_DISTANCE_SECTION_RELATIVE10"
EXPECTED_FULL_ROWS = 52155
EXPECTED_FULL_RACES = 5206
EXPECTED_TEST_ROWS = 17412
EXPECTED_TEST_RACES = 1779
EXPECTED_PRIMARY_ROWS = 14714
EXPECTED_PRIMARY_RACES = 1503
EXPECTED_DATES = 269
EXPECTED_SCHEDULE_SHAPE = (2000, 269)
EXPECTED_SCHEDULE_SHA256 = "d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd"
EXPECTED_DATE_INVENTORY_SHA256 = "e4aa73b866eac00b361d0354fdd62b7b2bd98915e003f250adc40a8df0a66b84"
PRIMARY_METRICS = ("log_loss", "brier")
RACE_METRICS = (
    "log_loss", "brier", "trio_nll", "six_combo_hit", "six_combo_mass",
    "top3_capture", "top3_all3", "top4_capture", "top4_all3",
    "top5_capture", "top5_all3", "top6_capture", "top6_all3", "pick_hit",
)
LOCK_PATH = HERE / "outputs/evaluation_input_lock.json"
PREFLIGHT_PATH = HERE / "outputs/evaluation_preflight.json"
SUMMARY_PATH = HERE / "outputs/evaluation_summary.json"
RECEIPT_PATH = HERE / "outputs/evaluation_report_receipt.json"
ROOT_EVAL_APPROVAL_PATH = HERE / "outputs/EVAL_APPROVAL.json"
OUTPUT_NAMES = (
    "baseline_runner_predictions.parquet",
    "candidate_runner_predictions.parquet",
    "baseline_race_metrics.parquet",
    "candidate_race_metrics.parquet",
    "baseline_canonical_max6.parquet",
    "candidate_canonical_max6.parquet",
    "paired_runner_metrics.parquet",
    "paired_race_metrics.parquet",
    "paired_canonical_max6.parquet",
    "scope_comparisons.parquet",
    "primary_bootstrap_draws.parquet",
    "calibration_bins.parquet",
    "date_support.parquet",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(ROOT):
        raise AssertionError(f"evaluation input is outside repository root: {resolved}")
    return resolved.relative_to(ROOT).as_posix()


def _file_record(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"required frozen input is missing: {_relative(path)}")
    return {
        "role": role,
        "path": _relative(path),
        "bytes": int(path.stat().st_size),
        "sha256": sha256(path),
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _write_parquet_new(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        frame.to_parquet(stream, index=False)


def _load_added_features() -> list[str]:
    feature_path = STUDY_DIR / "feature_core.py"
    spec = importlib.util.spec_from_file_location("distance_section_relative_feature_core", feature_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import locked candidate feature list: {feature_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    columns = list(module.ADDED_FEATURES)
    if len(columns) != 10 or len(set(columns)) != 10:
        raise AssertionError("candidate must contain exactly the predeclared ten added features")
    return columns


def _baseline_paths(year: int) -> dict[str, Path]:
    folder = BASELINE_DIR / f"F1_STYLE6_{year}"
    return {
        "model": folder / "top3.txt",
        "meta": folder / "meta.json",
        "calibration_scores": folder / "calibration_scores.parquet",
        "evaluation_scores": folder / "evaluation_scores.parquet",
    }


def _candidate_paths(year: int) -> dict[str, Path]:
    folder = STUDY_OUT / f"{VARIANT}_{year}"
    return {
        "model": folder / "top3.txt",
        "meta": folder / "meta.json",
        "calibration_scores": folder / "calibration_scores.parquet",
        "evaluation_scores": folder / "evaluation_scores.parquet",
    }


def _assert_meta_artifacts(meta: dict[str, Any], paths: dict[str, Path], year: int,
                           expected_variant: str, expected_features: list[str]) -> None:
    assert meta.get("variant") == expected_variant, (year, meta.get("variant"))
    assert int(meta.get("evaluation_year", -1)) == year
    assert meta.get("features") == expected_features
    assert int(meta.get("feature_count", -1)) == len(expected_features)
    assert np.isfinite(float(meta.get("tau", np.nan))) and float(meta["tau"]) > 0
    assert meta.get("model_sha256") == sha256(paths["model"]), f"{year} model digest disagrees with meta"
    assert meta.get("evaluation_scores_sha256") == sha256(paths["evaluation_scores"]), (
        f"{year} saved score digest disagrees with meta"
    )
    if "calibration_scores_sha256" in meta:
        assert meta["calibration_scores_sha256"] == sha256(paths["calibration_scores"]), (
            f"{year} calibration-score digest disagrees with meta"
        )


def _assert_score_file(path: Path, expected_ids: pd.Series, year: int, role: str) -> None:
    scores = pd.read_parquet(path)
    assert list(scores.columns) == ["api_record_id", "score"], (role, year, list(scores.columns))
    assert scores.api_record_id.astype("int64").tolist() == expected_ids.astype("int64").tolist(), (
        f"{role} score IDs/order do not match frozen evaluation feature rows for {year}"
    )
    raw = pd.to_numeric(scores.score, errors="raise").to_numpy(dtype="float64")
    assert len(raw) == len(expected_ids) and np.isfinite(raw).all(), f"invalid {role} raw scores for {year}"


def _compare_base_features(candidate: pd.DataFrame, baseline: pd.DataFrame,
                           base_columns: list[str]) -> None:
    assert candidate.api_record_id.astype("int64").tolist() == baseline.api_record_id.astype("int64").tolist()
    identity_columns = ["race_id", "race_date", "year", "horse_id", "horse_number", "distance_m"]
    for column in identity_columns:
        if column in candidate and column in baseline:
            a = candidate[column].astype("string").fillna("<NA>")
            b = baseline[column].astype("string").fillna("<NA>")
            assert a.equals(b), f"frozen feature identity mismatch: {column}"
    pd.testing.assert_frame_equal(
        candidate.loc[:, base_columns].reset_index(drop=True),
        baseline.loc[:, base_columns].reset_index(drop=True),
        check_dtype=False, check_exact=True, check_categorical=False,
        check_like=False, obj="candidate versus frozen F1_STYLE6 base inputs",
    )


def _date_inventory(features: pd.DataFrame) -> list[str]:
    dates = sorted(features.loc[features.year.isin(YEARS), "race_date"].astype("string").unique().tolist())
    digest = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    assert len(dates) == EXPECTED_DATES and digest == EXPECTED_DATE_INVENTORY_SHA256
    return dates


def _verify_schedule(dates: list[str]) -> tuple[np.ndarray, dict[str, Any]]:
    receipt = _read_json(BOOTSTRAP_RECEIPT_PATH)
    schedule = np.load(BOOTSTRAP_PATH, allow_pickle=False)
    assert schedule.shape == EXPECTED_SCHEDULE_SHAPE
    assert schedule.dtype.kind in "iu" and schedule.min() >= 0 and schedule.max() < len(dates)
    digest = sha256(BOOTSTRAP_PATH)
    assert digest == EXPECTED_SCHEDULE_SHA256 == receipt.get("schedule_sha256")
    date_digest = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    assert date_digest == receipt.get("date_inventory_sha256") == EXPECTED_DATE_INVENTORY_SHA256
    assert int(receipt.get("draws", schedule.shape[0])) == schedule.shape[0]
    assert int(receipt.get("dates", receipt.get("date_count", schedule.shape[1]))) == schedule.shape[1]
    return schedule, {
        "path": _relative(BOOTSTRAP_PATH),
        "schedule_sha256": digest,
        "receipt_path": _relative(BOOTSTRAP_RECEIPT_PATH),
        "date_inventory_sha256": date_digest,
        "date_count": len(dates),
        "shape": list(schedule.shape),
    }


def _preflight_source_and_model_artifacts() -> dict[str, Any]:
    assert not LOCK_PATH.exists() and not PREFLIGHT_PATH.exists(), "preflight lock already exists; refusing overwrite"
    assert not RECEIPT_PATH.exists() and not SUMMARY_PATH.exists(), "evaluation already completed; refusing rerun"
    for name in OUTPUT_NAMES:
        assert not (HERE / "outputs" / name).exists(), f"evaluation output already exists: {name}"

    added = _load_added_features()
    baseline_features = pd.read_parquet(BASE_FEATURE_PATH)
    candidate_features = pd.read_parquet(FEATURE_PATH)
    assert len(baseline_features) == len(candidate_features) == EXPECTED_FULL_ROWS
    assert baseline_features.api_record_id.is_unique and candidate_features.api_record_id.is_unique
    assert baseline_features.race_id.nunique() == candidate_features.race_id.nunique() == EXPECTED_FULL_RACES

    first_meta = _read_json(_baseline_paths(YEARS[0])["meta"])
    base_columns = list(first_meta["features"])
    assert len(base_columns) == 30
    assert added == [
        "hist_relative_seg_1_mean5", "hist_relative_seg_1_n",
        "hist_relative_seg_2_mean5", "hist_relative_seg_2_n",
        "hist_relative_seg_3_mean5", "hist_relative_seg_3_n",
        "hist_relative_seg_4_mean5", "hist_relative_seg_4_n",
        "hist_relative_seg_5_mean5", "hist_relative_seg_5_n",
    ], "added model columns changed from the predeclared 10-column contract"
    _compare_base_features(candidate_features, baseline_features, base_columns)
    assert candidate_features.columns.is_unique and set(base_columns + added).issubset(candidate_features.columns)

    eval_mask = candidate_features.year.isin(YEARS)
    eval_features = candidate_features.loc[eval_mask].reset_index(drop=True)
    assert len(eval_features) == EXPECTED_TEST_ROWS and eval_features.race_id.nunique() == EXPECTED_TEST_RACES
    primary_mask = pd.to_numeric(eval_features.distance_m, errors="raise").isin(TARGET_DISTANCES)
    primary = eval_features.loc[primary_mask]
    assert len(primary) == EXPECTED_PRIMARY_ROWS
    assert primary.race_id.nunique() == EXPECTED_PRIMARY_RACES
    dates = _date_inventory(candidate_features)
    schedule, schedule_info = _verify_schedule(dates)

    training_completion_path = STUDY_OUT / "candidate_training_completion.json"
    fit_approval_path = STUDY_OUT / "root_fit_approval.json"
    prepared_lock_path = STUDY_OUT / "prepared_lock.json"
    preflight_path = STUDY_OUT / "source_preflight.json"
    baseline_replay_path = STUDY_OUT / "baseline_replay_verification.json"
    for path in (training_completion_path, fit_approval_path, prepared_lock_path, preflight_path, baseline_replay_path):
        assert path.is_file(), f"candidate fit/source receipt is missing: {_relative(path)}"
    completion = _read_json(training_completion_path)
    fit_approval = _read_json(fit_approval_path)
    source_preflight = _read_json(preflight_path)
    baseline_replay = _read_json(baseline_replay_path)
    assert completion.get("passed") is True and completion.get("candidate") == VARIANT
    assert int(completion.get("candidate_models", -1)) == 3
    assert int(completion.get("lightgbm_train_calls", -1)) == 6
    assert int(completion.get("temperature_optimizations", -1)) == 3
    assert int(completion.get("candidate_score_rows", -1)) == EXPECTED_TEST_ROWS
    assert completion.get("candidate_outcome_metrics_computed") is False
    assert completion.get("no_refit_after_this_point") is True
    assert fit_approval.get("approved") is True and fit_approval.get("approved_by") == "root"
    assert fit_approval.get("candidate") == VARIANT and int(fit_approval.get("candidate_models", -1)) == 3
    assert int(fit_approval.get("lightgbm_train_calls", -1)) == 6
    assert int(fit_approval.get("temperature_optimizations", -1)) == 3
    assert source_preflight.get("passed") is True and source_preflight.get("candidate_outcome_metrics_computed") is False
    assert baseline_replay.get("passed") is True
    assert int(baseline_replay.get("baseline_models_reloaded", -1)) == 3
    assert int(baseline_replay.get("runner_rows_reproduced", -1)) == EXPECTED_TEST_ROWS
    assert int(baseline_replay.get("distinct_races_reproduced", -1)) == EXPECTED_TEST_RACES

    records: dict[str, dict[str, Any]] = {}

    def add(path: Path, role: str) -> None:
        records[_relative(path)] = _file_record(path, role)

    add(FEATURE_PATH, "candidate_frozen_features")
    add(BASE_FEATURE_PATH, "baseline_frozen_features")
    for path, role in (
        (training_completion_path, "candidate_fit_manifest"),
        (fit_approval_path, "root_fit_approval"),
        (prepared_lock_path, "candidate_prepared_input_lock"),
        (preflight_path, "candidate_source_preflight"),
        (baseline_replay_path, "frozen_baseline_replay_receipt"),
        (BOOTSTRAP_PATH, "fixed_bootstrap_schedule"),
        (BOOTSTRAP_RECEIPT_PATH, "fixed_bootstrap_schedule_receipt"),
    ):
        add(path, role)
    for year in YEARS:
        for role, path in _baseline_paths(year).items():
            add(path, f"baseline_{year}_{role}")
        for role, path in _candidate_paths(year).items():
            add(path, f"candidate_{year}_{role}")
        baseline_meta = _read_json(_baseline_paths(year)["meta"])
        candidate_meta = _read_json(_candidate_paths(year)["meta"])
        _assert_meta_artifacts(baseline_meta, _baseline_paths(year), year, "F1_STYLE6", base_columns)
        _assert_meta_artifacts(candidate_meta, _candidate_paths(year), year, VARIANT, base_columns + added)
        assert int(baseline_meta.get("evaluation_rows", -1)) == int(candidate_meta.get("evaluation_rows", -2))
        assert int(candidate_meta.get("evaluation_rows", -1)) == int(eval_features.year.eq(year).sum())
        assert int(candidate_meta.get("evaluation_races", -1)) == int(eval_features.loc[eval_features.year.eq(year), "race_id"].nunique())
        expected_ids = eval_features.loc[eval_features.year.eq(year), "api_record_id"]
        _assert_score_file(_baseline_paths(year)["evaluation_scores"], expected_ids, year, "baseline")
        _assert_score_file(_candidate_paths(year)["evaluation_scores"], expected_ids, year, "candidate")

    aggregate_scores_path = STUDY_OUT / "candidate_scores_fit_stage.parquet"
    add(aggregate_scores_path, "candidate_aggregate_oos_scores")
    aggregate_scores = pd.read_parquet(aggregate_scores_path)
    assert list(aggregate_scores.columns) == ["api_record_id", "score", "year"]
    assert len(aggregate_scores) == EXPECTED_TEST_ROWS
    assert aggregate_scores.api_record_id.astype("int64").is_unique
    for year in YEARS:
        expected = pd.read_parquet(_candidate_paths(year)["evaluation_scores"])
        actual = aggregate_scores.loc[aggregate_scores.year.eq(year), ["api_record_id", "score"]].reset_index(drop=True)
        pd.testing.assert_frame_equal(
            actual, expected.reset_index(drop=True), check_dtype=False, check_exact=True,
            check_categorical=False, check_like=False,
        )

    lock = {
        "status": "FROZEN_EVALUATION_INPUTS_NO_PERFORMANCE_METRICS",
        "study": STUDY_ID,
        "candidate": VARIANT,
        "evaluator_sha256": sha256(Path(__file__)),
        "contract_sha256": sha256(STUDY_DIR / "CONTRACT.md"),
        "candidate_feature_core_sha256": sha256(STUDY_DIR / "feature_core.py"),
        "primary_definition": {
            "distances_m": list(TARGET_DISTANCES),
            "years": list(YEARS),
            "runner_rows": EXPECTED_PRIMARY_ROWS,
            "races": EXPECTED_PRIMARY_RACES,
            "race_weighting": "equal weight per race; within-race runner mean for log loss/Brier",
            "metrics": list(PRIMARY_METRICS),
            "delta": "candidate minus baseline",
            "gate": "both point deltas < 0 and at least one paired date-bootstrap 95% upper bound < 0",
        },
        "full_test_cohort": {"runner_rows": EXPECTED_TEST_ROWS, "races": EXPECTED_TEST_RACES, "date_count": len(dates)},
        "bootstrap": schedule_info,
        "candidate_fit_manifest_sha256": sha256(training_completion_path),
        "candidate_fit_approval_sha256": sha256(fit_approval_path),
        "candidate_prepared_lock_sha256": sha256(prepared_lock_path),
        "input_files": records,
        "score_label_pairing_performed": False,
        "candidate_performance_metrics_computed": False,
        "database_opened": False,
        "training_or_calibration_performed_by_evaluator": False,
        "created_by": "evaluate_frozen.py preflight",
    }
    return lock


def preflight() -> dict[str, Any]:
    lock = _preflight_source_and_model_artifacts()
    _write_json_new(LOCK_PATH, lock)
    preflight_receipt = {
        "status": "PASS_FROZEN_INPUTS_AND_MODEL_ARTIFACTS_NO_METRICS",
        "study": STUDY_ID,
        "candidate": VARIANT,
        "input_lock_sha256": sha256(LOCK_PATH),
        "evaluator_sha256": sha256(Path(__file__)),
        "candidate_fit_manifest_sha256": lock["candidate_fit_manifest_sha256"],
        "candidate_fit_approval_sha256": lock["candidate_fit_approval_sha256"],
        "bootstrap_schedule_sha256": lock["bootstrap"]["schedule_sha256"],
        "full_test_rows": EXPECTED_TEST_ROWS,
        "full_test_races": EXPECTED_TEST_RACES,
        "primary_rows": EXPECTED_PRIMARY_ROWS,
        "primary_races": EXPECTED_PRIMARY_RACES,
        "primary_distances_m": list(TARGET_DISTANCES),
        "candidate_outcome_metrics_computed": False,
        "score_label_pairing_performed": False,
        "database_opened": False,
    }
    _write_json_new(PREFLIGHT_PATH, preflight_receipt)
    return preflight_receipt


def _verify_root_eval_approval(approval_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    assert LOCK_PATH.is_file() and PREFLIGHT_PATH.is_file(), "run preflight and freeze inputs first"
    assert not RECEIPT_PATH.exists() and not SUMMARY_PATH.exists(), "evaluation receipt exists; rerun prohibited"
    lock = _read_json(LOCK_PATH)
    preflight_receipt = _read_json(PREFLIGHT_PATH)
    approval_path = Path(approval_path).resolve()
    _relative(approval_path)
    approval = _read_json(approval_path)
    assert approval.get("approved") is True and approval.get("approved_by") == "root", (
        "root EVAL_APPROVAL must explicitly approve this frozen metric evaluation"
    )
    assert approval.get("study") == STUDY_ID and approval.get("candidate") == VARIANT
    assert approval.get("evaluator_sha256") == sha256(Path(__file__)) == lock["evaluator_sha256"]
    approved_lock_hash = approval.get("evaluation_input_lock_sha256", approval.get("input_lock_sha256"))
    assert approved_lock_hash == sha256(LOCK_PATH) == preflight_receipt["input_lock_sha256"]
    approved_preflight_hash = approval.get("evaluation_preflight_sha256", approval.get("preflight_sha256"))
    assert approved_preflight_hash == sha256(PREFLIGHT_PATH)
    assert approval.get("candidate_fit_manifest_sha256") == lock["candidate_fit_manifest_sha256"]
    assert approval.get("candidate_fit_approval_sha256") == lock["candidate_fit_approval_sha256"]
    assert approval.get("bootstrap_schedule_sha256") == lock["bootstrap"]["schedule_sha256"]
    return lock, approval


def _load_saved_metric_core():
    style_dir = ROOT / "jeju/research/20261010_style_history_ablation_v1"
    if str(style_dir) not in sys.path:
        sys.path.insert(0, str(style_dir))
    path = style_dir / "run.py"
    spec = importlib.util.spec_from_file_location("frozen_distance_section_f1_style6_run", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen F1_STYLE6 metric functions: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.OLD


def _add_pick_hit(races: pd.DataFrame, runners: pd.DataFrame) -> pd.DataFrame:
    picks = []
    for race_id, group in runners.groupby("race_id", sort=False):
        first = group.sort_values("score", ascending=False, kind="stable").iloc[0]
        picks.append({"race_id": race_id, "pick_hit": int(first.y)})
    out = races.merge(pd.DataFrame(picks), on="race_id", how="left", validate="one_to_one")
    assert out.pick_hit.notna().all()
    return out


def _make_model_outputs(features: pd.DataFrame, model_side: str, evaluator: Any) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    assert model_side in {"baseline", "candidate"}
    race_frames, runner_frames, ticket_frames = [], [], []
    for year in YEARS:
        paths = _baseline_paths(year) if model_side == "baseline" else _candidate_paths(year)
        meta = _read_json(paths["meta"])
        score = pd.read_parquet(paths["evaluation_scores"])
        test = features.loc[features.year.eq(year)].reset_index(drop=True)
        assert score.api_record_id.astype("int64").tolist() == test.api_record_id.astype("int64").tolist()
        raw = pd.to_numeric(score.score, errors="raise").to_numpy(dtype="float64")
        assert np.isfinite(raw).all()
        race, runner, ticket = evaluator.evaluate(test, raw, float(meta["tau"]), meta["variant"])
        race_frames.append(race)
        runner_frames.append(runner)
        ticket_frames.append(ticket)
    races = _add_pick_hit(pd.concat(race_frames, ignore_index=True), pd.concat(runner_frames, ignore_index=True))
    runners = pd.concat(runner_frames, ignore_index=True)
    tickets = pd.concat(ticket_frames, ignore_index=True)
    assert len(runners) == EXPECTED_TEST_ROWS and runners.api_record_id.is_unique
    assert races.race_id.nunique() == EXPECTED_TEST_RACES and races.race_id.is_unique
    assert len(tickets) == 6 * EXPECTED_TEST_RACES
    return races, runners, tickets


def _paired_frames(candidate_races: pd.DataFrame, candidate_runners: pd.DataFrame,
                   baseline_races: pd.DataFrame, baseline_runners: pd.DataFrame,
                   candidate_tickets: pd.DataFrame, baseline_tickets: pd.DataFrame,
                   expected_runner_rows: int = EXPECTED_TEST_ROWS,
                   expected_races: int = EXPECTED_TEST_RACES
                   ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    runner_keys = ["api_record_id", "race_id", "race_date", "year", "distance_m", "horse_id", "horse_number"]
    metric_runner_cols = ["variant", "score", "p_top3", "log_loss", "brier", "y"]
    left = candidate_runners[runner_keys + metric_runner_cols].rename(columns={
        column: f"{column}_candidate" for column in metric_runner_cols
    })
    right = baseline_runners[runner_keys + metric_runner_cols].rename(columns={
        column: f"{column}_baseline" for column in metric_runner_cols
    })
    paired_runners = left.merge(right, on=runner_keys, how="outer", validate="one_to_one", indicator=True)
    assert len(paired_runners) == expected_runner_rows
    assert paired_runners._merge.eq("both").all()
    assert paired_runners.y_candidate.astype("int8").equals(paired_runners.y_baseline.astype("int8"))
    paired_runners = paired_runners.drop(columns="_merge")

    race_keys = ["race_id", "race_date", "year", "distance_m", "field_n"]
    candidate = candidate_races.rename(columns={
        "variant": "variant_candidate", **{metric: f"{metric}_candidate" for metric in RACE_METRICS},
    })
    baseline = baseline_races.rename(columns={
        "variant": "variant_baseline", **{metric: f"{metric}_baseline" for metric in RACE_METRICS},
    })
    paired_races = candidate.merge(baseline, on=race_keys, how="outer", validate="one_to_one", indicator=True)
    assert len(paired_races) == expected_races and paired_races._merge.eq("both").all()
    paired_races = paired_races.drop(columns="_merge")

    ticket_keys = ["race_id", "selection_rank"]
    left_ticket = candidate_tickets[ticket_keys + ["numbers", "probability", "hit"]].rename(columns={
        "numbers": "numbers_candidate", "probability": "probability_candidate", "hit": "hit_candidate",
    })
    right_ticket = baseline_tickets[ticket_keys + ["numbers", "probability", "hit"]].rename(columns={
        "numbers": "numbers_baseline", "probability": "probability_baseline", "hit": "hit_baseline",
    })
    paired_tickets = left_ticket.merge(right_ticket, on=ticket_keys, how="outer", validate="one_to_one", indicator=True)
    assert len(paired_tickets) == 6 * expected_races and paired_tickets._merge.eq("both").all()
    assert paired_tickets.groupby("race_id").selection_rank.nunique().eq(6).all()
    return paired_runners, paired_races, paired_tickets.drop(columns="_merge")


def _date_bootstrap(group: pd.DataFrame, metric: str, dates: list[str], schedule: np.ndarray
                    ) -> tuple[float, float, float, np.ndarray, int]:
    values = pd.to_numeric(group[f"{metric}_candidate"], errors="raise").to_numpy(dtype="float64") - \
        pd.to_numeric(group[f"{metric}_baseline"], errors="raise").to_numpy(dtype="float64")
    assert len(values) == len(group) and np.isfinite(values).all()
    date_index = {date: i for i, date in enumerate(dates)}
    daily_sum = np.zeros(len(dates), dtype="float64")
    daily_count = np.zeros(len(dates), dtype="int64")
    for date, value in zip(group.race_date.astype("string"), values):
        idx = date_index[str(date)]
        daily_sum[idx] += value
        daily_count[idx] += 1
    numerator = daily_sum[schedule].sum(axis=1)
    denominator = daily_count[schedule].sum(axis=1)
    draws = np.full(schedule.shape[0], np.nan, dtype="float64")
    valid = denominator > 0
    draws[valid] = numerator[valid] / denominator[valid]
    finite = draws[np.isfinite(draws)]
    if len(finite):
        low, high = np.quantile(finite, [0.025, 0.975]).astype("float64").tolist()
    else:
        low = high = float("nan")
    return float(values.mean()), float(low), float(high), draws, int(valid.sum())


def _build_scopes(races: pd.DataFrame) -> list[tuple[str, str, pd.DataFrame]]:
    distance = pd.to_numeric(races.distance_m, errors="raise").astype("int64")
    year = pd.to_numeric(races.year, errors="raise").astype("int64")
    scopes: list[tuple[str, str, pd.DataFrame]] = [
        ("all_eval", "all", races),
        ("primary_distance_cohort", "900_1000_1110_1200", races.loc[distance.isin(TARGET_DISTANCES)]),
        ("non_target_distances", "other", races.loc[~distance.isin(TARGET_DISTANCES)]),
    ]
    for value in sorted(distance.unique()):
        scopes.append(("distance", str(int(value)), races.loc[distance.eq(value)]))
    for value in YEARS:
        scopes.append(("year_all_distances", str(value), races.loc[year.eq(value)]))
        scopes.append(("year_primary_distances", str(value), races.loc[year.eq(value) & distance.isin(TARGET_DISTANCES)]))
    for year_value in YEARS:
        for distance_value in sorted(distance.unique()):
            group = races.loc[year.eq(year_value) & distance.eq(distance_value)]
            if len(group):
                scopes.append(("year_distance", f"{year_value}_{int(distance_value)}", group))
    return [(kind, label, frame) for kind, label, frame in scopes if len(frame)]


def _scope_summaries(paired_races: pd.DataFrame, dates: list[str], schedule: np.ndarray
                     ) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    summary_rows, draw_rows = [], []
    for kind, label, group in _build_scopes(paired_races):
        for metric in RACE_METRICS:
            c = pd.to_numeric(group[f"{metric}_candidate"], errors="raise").to_numpy(dtype="float64")
            b = pd.to_numeric(group[f"{metric}_baseline"], errors="raise").to_numpy(dtype="float64")
            point, low, high, draws, valid = _date_bootstrap(group, metric, dates, schedule)
            summary_rows.append({
                "scope": kind, "scope_value": label, "metric": metric,
                "races": int(group.race_id.nunique()), "dates_with_races": int(group.race_date.nunique()),
                "candidate_mean_race_equal": float(c.mean()), "baseline_mean_race_equal": float(b.mean()),
                "candidate_minus_baseline": point, "paired_date_ci95_low": low,
                "paired_date_ci95_high": high, "bootstrap_draws": int(schedule.shape[0]),
                "valid_bootstrap_draws": valid,
                "zero_denominator_draws": int(schedule.shape[0] - valid),
            })
            if kind == "primary_distance_cohort" and metric in PRIMARY_METRICS:
                draw_rows.extend({
                    "metric": metric, "draw": int(i), "candidate_minus_baseline": float(value),
                } for i, value in enumerate(draws) if np.isfinite(value))
    summary = pd.DataFrame(summary_rows)
    primary = summary.loc[
        summary.scope.eq("primary_distance_cohort") & summary.metric.isin(PRIMARY_METRICS)
    ]
    assert len(primary) == len(PRIMARY_METRICS)
    delta = {row.metric: float(row.candidate_minus_baseline) for row in primary.itertuples(index=False)}
    upper = {row.metric: float(row.paired_date_ci95_high) for row in primary.itertuples(index=False)}
    gate = bool(all(delta[m] < 0 for m in PRIMARY_METRICS) and any(upper[m] < 0 for m in PRIMARY_METRICS))
    receipt = {
        "primary_gate_passed": gate,
        "required_both_primary_point_deltas_below_zero": True,
        "required_at_least_one_primary_paired_95pct_ci_upper_below_zero": True,
        "primary_candidate_minus_baseline": delta,
        "primary_ci95_upper": upper,
        "primary_races": int(paired_races.loc[
            pd.to_numeric(paired_races.distance_m, errors="raise").isin(TARGET_DISTANCES), "race_id"
        ].nunique()),
        "primary_runner_rows": EXPECTED_PRIMARY_ROWS,
        "bootstrap_shape": list(schedule.shape),
        "bootstrap_fixed_date_count": len(dates),
        "non_target_dates_contribute_zero_to_primary_sum_and_count": True,
    }
    return summary, pd.DataFrame(draw_rows), receipt


def _calibration_bins(runners: pd.DataFrame) -> pd.DataFrame:
    edges = np.linspace(0.0, 1.0, 11)
    rows = []
    scopes: list[tuple[str, str, pd.DataFrame]] = [("all_eval", "all", runners)]
    primary_mask = pd.to_numeric(runners.distance_m, errors="raise").isin(TARGET_DISTANCES)
    scopes.append(("primary_distance_cohort", "900_1000_1110_1200", runners.loc[primary_mask]))
    for distance in sorted(pd.to_numeric(runners.distance_m, errors="raise").astype("int64").unique()):
        scopes.append(("distance", str(int(distance)), runners.loc[
            pd.to_numeric(runners.distance_m, errors="raise").eq(distance)
        ]))
    for scope, label, subset in scopes:
        for model, probability, outcome in (
            ("baseline", "p_top3_baseline", "y_baseline"),
            ("candidate", "p_top3_candidate", "y_candidate"),
        ):
            p = pd.to_numeric(subset[probability], errors="raise")
            y = pd.to_numeric(subset[outcome], errors="raise")
            assert p.between(0, 1).all() and y.isin([0, 1]).all()
            bin_index = np.minimum(np.floor(p.to_numpy(dtype="float64") * 10).astype("int64"), 9)
            for idx in range(10):
                mask = bin_index == idx
                rows.append({
                    "scope": scope, "scope_value": label, "model": model,
                    "bin": idx, "bin_lower_inclusive": float(edges[idx]),
                    "bin_upper_exclusive": float(edges[idx + 1]) if idx < 9 else 1.0,
                    "runner_rows": int(mask.sum()),
                    "mean_predicted_top3": float(p.to_numpy()[mask].mean()) if mask.any() else np.nan,
                    "observed_top3_rate": float(y.to_numpy()[mask].mean()) if mask.any() else np.nan,
                })
    return pd.DataFrame(rows)


def _date_support(features: pd.DataFrame, dates: list[str]) -> pd.DataFrame:
    test = features.loc[features.year.isin(YEARS), ["race_id", "race_date", "distance_m"]].drop_duplicates()
    d = pd.to_numeric(test.distance_m, errors="raise").astype("int64")
    test = test.assign(is_primary_distance=d.isin(TARGET_DISTANCES))
    counts = test.groupby("race_date", sort=True).agg(
        all_distance_races=("race_id", "nunique"),
        primary_distance_races=("is_primary_distance", "sum"),
    )
    result = pd.DataFrame({"race_date": dates}).set_index("race_date").join(counts, how="left").fillna(0).reset_index()
    result["all_distance_races"] = result.all_distance_races.astype("int64")
    result["primary_distance_races"] = result.primary_distance_races.astype("int64")
    assert len(result) == EXPECTED_DATES
    assert int(result.all_distance_races.sum()) == EXPECTED_TEST_RACES
    assert int(result.primary_distance_races.sum()) == EXPECTED_PRIMARY_RACES
    return result


def evaluate(approval_path: Path) -> dict[str, Any]:
    lock, approval = _verify_root_eval_approval(approval_path)
    for relative, entry in lock["input_files"].items():
        path = ROOT / relative
        assert path.is_file() and path.stat().st_size == int(entry["bytes"])
        assert sha256(path) == entry["sha256"], f"locked evaluation input changed: {relative}"
    for name in OUTPUT_NAMES:
        assert not (HERE / "outputs" / name).exists(), f"refusing overwrite: {name}"

    features = pd.read_parquet(FEATURE_PATH)
    baseline_features = pd.read_parquet(BASE_FEATURE_PATH)
    baseline_meta_2024 = _read_json(_baseline_paths(YEARS[0])["meta"])
    base_columns = list(baseline_meta_2024["features"])
    added = _load_added_features()
    _compare_base_features(features, baseline_features, base_columns)
    assert len(features) == EXPECTED_FULL_ROWS
    dates = _date_inventory(features)
    schedule, schedule_info = _verify_schedule(dates)

    evaluator = _load_saved_metric_core()
    baseline_races, baseline_runners, baseline_tickets = _make_model_outputs(features, "baseline", evaluator)
    candidate_races, candidate_runners, candidate_tickets = _make_model_outputs(features, "candidate", evaluator)
    paired_runners, paired_races, paired_tickets = _paired_frames(
        candidate_races, candidate_runners, baseline_races, baseline_runners,
        candidate_tickets, baseline_tickets,
    )
    assert len(paired_tickets) == 6 * EXPECTED_TEST_RACES
    assert np.array_equal(
        paired_runners["y_candidate"].to_numpy(dtype="int8"),
        paired_runners["y_baseline"].to_numpy(dtype="int8"),
    )
    scope_summary, bootstrap_draws, primary_gate = _scope_summaries(paired_races, dates, schedule)
    primary_bootstrap_count = bootstrap_draws.groupby("metric").draw.nunique().to_dict()
    assert primary_bootstrap_count == {"brier": 2000, "log_loss": 2000}
    cal_bins = _calibration_bins(paired_runners)
    date_support = _date_support(features, dates)

    # Candidate and baseline use the same frozen runner/race keys and the same
    # OLD.evaluate ranking and canonical MAX6 implementation.
    for model_tickets in (candidate_tickets, baseline_tickets):
        assert len(model_tickets) == 6 * EXPECTED_TEST_RACES
        assert model_tickets.groupby("race_id").selection_rank.nunique().eq(6).all()
    assert candidate_runners.race_id.nunique() == baseline_runners.race_id.nunique() == EXPECTED_TEST_RACES
    assert set(candidate_runners.api_record_id.astype("int64")) == set(baseline_runners.api_record_id.astype("int64"))

    outputs: dict[str, dict[str, Any]] = {}
    frames = {
        "baseline_runner_predictions.parquet": baseline_runners,
        "candidate_runner_predictions.parquet": candidate_runners,
        "baseline_race_metrics.parquet": baseline_races,
        "candidate_race_metrics.parquet": candidate_races,
        "baseline_canonical_max6.parquet": baseline_tickets,
        "candidate_canonical_max6.parquet": candidate_tickets,
        "paired_runner_metrics.parquet": paired_runners,
        "paired_race_metrics.parquet": paired_races,
        "paired_canonical_max6.parquet": paired_tickets,
        "scope_comparisons.parquet": scope_summary,
        "primary_bootstrap_draws.parquet": bootstrap_draws,
        "calibration_bins.parquet": cal_bins,
        "date_support.parquet": date_support,
    }
    for filename, frame in frames.items():
        path = HERE / "outputs" / filename
        _write_parquet_new(path, frame)
        outputs[filename] = {"bytes": int(path.stat().st_size), "sha256": sha256(path)}

    summary = {
        "status": "PASS_FROZEN_METRIC_EVALUATION",
        "study": STUDY_ID,
        "candidate": VARIANT,
        "approval_sha256": sha256(approval_path),
        "input_lock_sha256": sha256(LOCK_PATH),
        "evaluator_sha256": sha256(Path(__file__)),
        "candidate_fit_manifest_sha256": lock["candidate_fit_manifest_sha256"],
        "primary": primary_gate,
        "scope_summary_path": "scope_comparisons.parquet",
        "calibration_bins": {
            "method": "runner-weighted 10 equal-width bins over [0,1]; the final bin includes 1.0",
            "rows": int(len(cal_bins)),
        },
        "candidate_metrics_computed_once": True,
        "candidate_refit_after_evaluation": False,
        "model_predict_calls_by_evaluator": 0,
        "training_calls_by_evaluator": 0,
        "calibration_calls_by_evaluator": 0,
        "database_opened": False,
        "database_writes": 0,
        "production_or_registry_changes": 0,
        "baseline_models": 3,
        "candidate_models": 3,
        "full_test_rows": EXPECTED_TEST_ROWS,
        "full_test_races": EXPECTED_TEST_RACES,
        "primary_distance_m": list(TARGET_DISTANCES),
        "primary_runner_rows": EXPECTED_PRIMARY_ROWS,
        "primary_races": EXPECTED_PRIMARY_RACES,
        "bootstrap": schedule_info,
        "outputs": outputs,
    }
    _write_json_new(SUMMARY_PATH, summary)
    receipt = {
        "passed": True,
        "status": "PASS_FROZEN_METRIC_EVALUATION",
        "study": STUDY_ID,
        "candidate": VARIANT,
        "approval_path": _relative(approval_path),
        "approval_sha256": sha256(approval_path),
        "input_lock_sha256": sha256(LOCK_PATH),
        "evaluator_sha256": sha256(Path(__file__)),
        "summary_sha256": sha256(SUMMARY_PATH),
        "candidate_metrics_computed_once": True,
        "training_or_calibration_by_evaluator": False,
        "database_opened": False,
        "production_or_registry_changes": 0,
        "outputs": outputs,
    }
    _write_json_new(RECEIPT_PATH, receipt)
    return summary


def _self_check() -> dict[str, Any]:
    """Exercise only synthetic paired-date/calibration math; read no study scores."""
    dates = ["2026-01-01", "2026-01-02", "2026-01-03"]
    schedule = np.array([[0, 1, 2], [0, 0, 2], [1, 1, 1]], dtype="int16")
    toy = pd.DataFrame({
        "race_date": dates,
        "log_loss_candidate": [1.0, 3.0, 5.0],
        "log_loss_baseline": [2.0, 2.0, 3.0],
    })
    point, low, high, draws, valid = _date_bootstrap(toy, "log_loss", dates, schedule)
    assert point == (2.0 / 3.0)
    assert valid == 3 and np.isfinite(draws).all()
    assert low <= high and low == float(np.quantile(draws, .025)) and high == float(np.quantile(draws, .975))
    toy_runners = pd.DataFrame({
        "distance_m": [900, 900],
        "p_top3_candidate": [0.0, 1.0], "y_candidate": [0, 1],
        "p_top3_baseline": [0.2, 0.8], "y_baseline": [0, 1],
    })
    bins = _calibration_bins(toy_runners)
    assert len(bins) == 60 and bins.loc[bins.runner_rows.gt(0)].runner_rows.sum() == 12

    race_key = {"race_id": "toy-race", "race_date": "2026-01-01", "year": 2026,
                "distance_m": 900, "field_n": 2}
    base_race = {**race_key, "variant": "F1_STYLE6", **{metric: 0.1 for metric in RACE_METRICS}}
    candidate_race = {**race_key, "variant": VARIANT, **{metric: 0.2 for metric in RACE_METRICS}}
    race_keys = [{"api_record_id": 1, "horse_id": "h1", "horse_number": 1, "y": 1,
                  "score": 0.2, "p_top3": 0.8, "log_loss": 0.1, "brier": 0.04},
                 {"api_record_id": 2, "horse_id": "h2", "horse_number": 2, "y": 0,
                  "score": -0.2, "p_top3": 0.2, "log_loss": 0.1, "brier": 0.04}]
    runner_rows = pd.DataFrame([{**race_key, **row} for row in race_keys])
    ticket_rows = pd.DataFrame([{
        "race_id": "toy-race", "selection_rank": rank, "numbers": f"{rank}-2-3",
        "probability": 1 / 6, "hit": int(rank == 1),
    } for rank in range(1, 7)])
    toy_paired_runners, toy_paired_races, toy_paired_tickets = _paired_frames(
        pd.DataFrame([candidate_race]), runner_rows.assign(variant=VARIANT),
        pd.DataFrame([base_race]), runner_rows.assign(variant="F1_STYLE6"),
        ticket_rows, ticket_rows,
        expected_runner_rows=2, expected_races=1,
    )
    assert len(toy_paired_runners) == 2 and len(toy_paired_races) == 1 and len(toy_paired_tickets) == 6
    assert "_merge" not in toy_paired_races and "_merge" not in toy_paired_tickets

    race_metrics = []
    for index, date in enumerate(dates):
        item = {
            "race_id": f"race-{index}", "race_date": date, "year": 2024,
            "distance_m": 900, "field_n": 8,
        }
        for metric in RACE_METRICS:
            base_value = 0.4 if metric == "log_loss" else 0.2
            if metric == "log_loss":
                candidate_value = base_value - 0.1
            elif metric == "brier":
                candidate_value = base_value - 0.05
            else:
                candidate_value = base_value
            item[f"{metric}_baseline"] = base_value
            item[f"{metric}_candidate"] = candidate_value
        race_metrics.append(item)
    summaries, primary_draws, gate = _scope_summaries(pd.DataFrame(race_metrics), dates, schedule)
    assert gate["primary_gate_passed"] is True
    assert gate["primary_races"] == 3 and gate["primary_runner_rows"] == EXPECTED_PRIMARY_ROWS
    assert set(primary_draws.metric) == {"log_loss", "brier"}
    assert len(summaries.loc[
        summaries.scope.eq("primary_distance_cohort") & summaries.metric.isin(PRIMARY_METRICS)
    ]) == 2
    assert not LOCK_PATH.exists(), "self-check must not create evaluation locks"
    assert not RECEIPT_PATH.exists(), "self-check must not create metric outputs"
    return {"status": "PASS_SYNTHETIC_MATH_AND_PAIRING_ONLY", "study_scores_read": False,
            "candidate_metrics_computed": False, "synthetic_bootstrap_draws": 3,
            "synthetic_calibration_rows": int(bins.runner_rows.sum()),
            "synthetic_paired_runners": len(toy_paired_runners),
            "synthetic_paired_races": len(toy_paired_races),
            "synthetic_paired_tickets": len(toy_paired_tickets),
            "synthetic_primary_gate_passed": gate["primary_gate_passed"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("self-check", "preflight", "evaluate"))
    parser.add_argument("--approval", type=Path, help="root EVAL_APPROVAL receipt (defaults to outputs/EVAL_APPROVAL.json)")
    args = parser.parse_args()
    if args.command == "self-check":
        result = _self_check()
    elif args.command == "preflight":
        result = preflight()
    else:
        approval_path = args.approval or ROOT_EVAL_APPROVAL_PATH
        if not approval_path.is_file():
            parser.error(f"root EVAL_APPROVAL receipt is required: {approval_path}")
        result = evaluate(approval_path)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
