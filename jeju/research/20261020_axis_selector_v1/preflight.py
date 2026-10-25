"""Source-only preflight for the frozen F1_STYLE6 axis selector plan.

This script validates source hashes, OOS key/date coverage, fixed cohort sizes,
and the reusable date bootstrap schedule. It does not fit a model, select an
evaluation axis, or calculate outcome metrics.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STUDY = Path(__file__).resolve().parent
ROOT = STUDY.parents[2]
OUT = STUDY / "outputs"
LOCK_PATH = OUT / "SOURCE_LOCK.json"
PREFLIGHT_PATH = OUT / "PREFLIGHT.json"

FEATURES_REL = "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
BASELINE_REL = "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet"
HIST_STUDY_REL = "jeju/research/20261011_pair_top3_oos_expansion_v1"
HIST_OUT_REL = f"{HIST_STUDY_REL}/outputs"
STYLE_OUT_REL = "jeju/research/20261010_style_history_ablation_v1/outputs"
BOOTSTRAP_REL = "jeju/research/20261011_pair_top3_direct_v1/outputs"

SELECTOR_FEATURES = (
    "observed_starts",
    "days_since_start",
    "same_starts",
    "same_valid_times",
    "days_since_same",
    "mean5_rank_fraction",
)
EXPECTED_YEAR_COUNTS = {
    2019: (5890, 576),
    2020: (3290, 329),
    2021: (4331, 418),
    2022: (5261, 512),
    2023: (6506, 657),
    2024: (6329, 637),
    2025: (6410, 654),
}
EXPECTED_SELECTOR_WINDOWS = {
    2024: (2019, 2023, 25278, 2492, "2023-12-30", 6329, 637),
    2025: (2019, 2024, 31607, 3129, "2024-12-28", 6410, 654),
    2026: (2019, 2025, 38017, 3783, "2025-12-27", 4673, 488),
}
EXPECTED_HISTORICAL_FOLDS = (2020, 2021, 2022, 2023)
EXPECTED_CURRENT_FOLDS = (2024, 2025, 2026)
EXPECTED_EVAL_RUNNERS = 17412
EXPECTED_EVAL_RACES = 1779
EXPECTED_MAIN_RACES = 1503
EXPECTED_EVAL_DATES = 269


class PreflightError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PreflightError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def checked_source(relative: str) -> Path:
    path = ROOT / relative
    require(not path.is_symlink(), f"source symlink is not allowed: {relative}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(ROOT) and resolved.is_file(), f"invalid source path: {relative}")
    return resolved


def checked_study_file(relative: str) -> Path:
    path = STUDY / relative
    require(not path.is_symlink(), f"study symlink is not allowed: {relative}")
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(STUDY) and resolved.is_file(), f"invalid study artifact: {relative}")
    return resolved


def source_path_inventory() -> set[str]:
    paths = {
        FEATURES_REL,
        BASELINE_REL,
        f"{HIST_OUT_REL}/HISTORICAL_REFIT_RECEIPT.json",
        f"{HIST_OUT_REL}/HISTORICAL_SOURCE_LOCK.json",
        f"{HIST_OUT_REL}/HISTORICAL_PREFLIGHT.json",
        f"{HIST_OUT_REL}/HISTORICAL_FIT_APPROVAL.json",
        f"{HIST_STUDY_REL}/historical_refit.py",
        f"{BOOTSTRAP_REL}/date_bootstrap_schedule.npy",
        f"{BOOTSTRAP_REL}/date_bootstrap_schedule.json",
        "jeju/research/20261010_style_history_ablation_v1/outputs/style_history_lineage.parquet",
        "jeju/research/20261010_style_history_ablation_v1/prepare.py",
        "jeju/research/20261009_finish_history_ablation_v1/prepare.py",
        "jeju/research/20261008_horse_profile_baseline_v1/run.py",
    }
    for fold in EXPECTED_HISTORICAL_FOLDS:
        paths.update(
            {
                f"{HIST_OUT_REL}/F1_STYLE6_{fold}/calibration_scores.parquet",
                f"{HIST_OUT_REL}/F1_STYLE6_{fold}/meta.json",
                f"{HIST_OUT_REL}/F1_STYLE6_{fold}/top3.txt",
            }
        )
    for fold in EXPECTED_CURRENT_FOLDS:
        paths.update(
            {
                f"{STYLE_OUT_REL}/F1_STYLE6_{fold}/calibration_scores.parquet",
                f"{STYLE_OUT_REL}/F1_STYLE6_{fold}/evaluation_scores.parquet",
                f"{STYLE_OUT_REL}/F1_STYLE6_{fold}/meta.json",
                f"{STYLE_OUT_REL}/F1_STYLE6_{fold}/top3.txt",
            }
        )
    return paths


def verify_source_lock() -> tuple[dict[str, str], str]:
    lock_path = checked_study_file("outputs/SOURCE_LOCK.json")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    require(lock.get("status") == "FROZEN_BEFORE_PREFLIGHT", "source lock status mismatch")
    sources = lock.get("sources")
    require(isinstance(sources, dict), "source lock sources must be an object")
    require(set(sources) == source_path_inventory(), "source lock path inventory changed")
    actual: dict[str, str] = {}
    for relative, expected in sorted(sources.items()):
        source = checked_source(relative)
        actual[relative] = sha256(source)
        require(actual[relative] == expected, f"locked source changed: {relative}")
    artifact_hashes = lock.get("study_artifacts")
    require(isinstance(artifact_hashes, dict), "source lock study_artifacts must be an object")
    expected_artifacts = {"PLAN.md", "SOURCE_AUDIT.md", "preflight.py"}
    require(set(artifact_hashes) == expected_artifacts, "locked study artifact inventory changed")
    for relative, expected in sorted(artifact_hashes.items()):
        require(sha256(checked_study_file(relative)) == expected, f"locked study artifact changed: {relative}")
    return actual, sha256(lock_path)


def load_json_source(relative: str) -> dict[str, Any]:
    return json.loads(checked_source(relative).read_text(encoding="utf-8"))


def validate_historical_receipt(source_hashes: dict[str, str]) -> dict[str, Any]:
    receipt_path = f"{HIST_OUT_REL}/HISTORICAL_REFIT_RECEIPT.json"
    lock_path = f"{HIST_OUT_REL}/HISTORICAL_SOURCE_LOCK.json"
    preflight_path = f"{HIST_OUT_REL}/HISTORICAL_PREFLIGHT.json"
    approval_path = f"{HIST_OUT_REL}/HISTORICAL_FIT_APPROVAL.json"
    runner_path = f"{HIST_STUDY_REL}/historical_refit.py"
    receipt = load_json_source(receipt_path)
    source_lock = load_json_source(lock_path)
    approval = load_json_source(approval_path)
    old_preflight = load_json_source(preflight_path)

    require(receipt.get("status") == "PASS", "historical OOS receipt did not pass")
    require(receipt.get("scope") == "historical_F1_STYLE6_calibration_raw_scores_only", "historical OOS receipt scope mismatch")
    require(receipt.get("historical_evaluation_scores_generated") is False, "historical evaluation scores were generated")
    require(receipt.get("pair_fit_performed") is False, "historical receipt reports pair fit")
    require(receipt.get("pair_performance_metrics_computed") is False, "historical receipt reports performance metrics")
    require(receipt.get("temperature_optimizations") == 0, "historical OOS receipt reports tau fitting")
    require(receipt.get("source_lock_sha256") == source_hashes[lock_path], "historical source lock hash mismatch")
    require(receipt.get("preflight_sha256") == source_hashes[preflight_path], "historical preflight hash mismatch")
    require(receipt.get("approval_sha256") == source_hashes[approval_path], "historical approval hash mismatch")
    require(receipt.get("historical_refit_code_sha256") == source_hashes[runner_path], "historical refit code hash mismatch")
    require(source_lock.get("status") == "PASS", "historical source lock did not pass")
    require(approval.get("approved") is True, "historical OOS approval is missing")
    require(approval.get("scope") == "historical_F1_STYLE6_calibration_raw_scores_only", "historical OOS approval scope mismatch")
    require(old_preflight.get("status") == "PASS", "historical OOS source preflight did not pass")
    require(old_preflight.get("historical_refit_performed") is False, "historical source preflight includes a refit")
    require(old_preflight.get("raw_oos_scores_generated") is False, "historical source preflight includes score generation")
    require(old_preflight.get("pair_fit_performed") is False, "historical source preflight includes pair fit")
    for relative, expected in source_lock.get("sources", {}).items():
        require(relative in source_hashes, f"locked historical recipe dependency is absent: {relative}")
        require(source_hashes[relative] == expected, f"historical recipe dependency changed: {relative}")

    receipt_folds = {int(item["fold"]): item for item in receipt.get("folds", [])}
    require(set(receipt_folds) == set(EXPECTED_HISTORICAL_FOLDS), "historical receipt fold list mismatch")
    return {"receipt": receipt, "folds": receipt_folds}


def assert_race_roster(frame: pd.DataFrame, label_column: str | None, label: str) -> None:
    grouped = frame.groupby("race_id", sort=False)
    sizes = grouped.size()
    field_counts = grouped["field_n"].first()
    require((grouped["field_n"].nunique() == 1).all(), f"{label}: field_n changes inside race")
    require((sizes == field_counts).all(), f"{label}: duplicate or incomplete field_n roster")
    require((sizes >= 3).all(), f"{label}: race has fewer than three runners")
    require((grouped["horse_number"].nunique() == sizes).all(), f"{label}: duplicate horse number within race")
    if label_column is not None:
        top3_counts = grouped[label_column].sum()
        require((top3_counts == 3).all(), f"{label}: race does not have exactly three Top3 labels")
        top3_positions = grouped["finish_position"].apply(lambda values: set(values[values.le(3)].astype(int).tolist()))
        require(top3_positions.map(lambda values: values == {1, 2, 3}).all(), f"{label}: Top3 positions are not exactly 1, 2, 3")


def training_candidate_counts(
    features: pd.DataFrame,
    score_maps: dict[int, pd.Series],
    year_min: int,
    year_max: int,
) -> dict[str, int]:
    training = features.loc[features["year"].between(year_min, year_max)].copy()
    raw_scores = np.full(len(training), np.nan, dtype=float)
    for year in range(year_min, year_max + 1):
        year_mask = training["year"].eq(year).to_numpy()
        key_values = training.loc[year_mask, "api_record_id"]
        scores = score_maps[year].reindex(key_values)
        require(scores.notna().all(), f"training OOS score missing before candidate count for {year}")
        raw_scores[year_mask] = scores.to_numpy(dtype=float)
    require(np.isfinite(raw_scores).all(), "training OOS raw score is non-finite")
    training["_raw_score_for_roster"] = raw_scores
    ordered = training.sort_values(
        ["race_id", "_raw_score_for_roster", "horse_number"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    ordered["_score_rank_for_roster"] = ordered.groupby("race_id", sort=False).cumcount() + 1
    candidates = ordered.loc[ordered["_score_rank_for_roster"].le(3)]
    require(len(candidates) == 3 * training["race_id"].nunique(), "training candidate count is not three per race")
    candidate_groups = candidates.groupby("race_id", sort=False)["finish_position"].apply(lambda values: int(values.le(3).sum()))
    mixed_races = int(candidate_groups.between(1, 2).sum())
    require(mixed_races > 0, f"training window has no informative Top3 candidate races: {year_min}-{year_max}")
    return {
        "source_races": int(training["race_id"].nunique()),
        "source_runners": int(len(training)),
        "candidate_fit_rows": int(len(candidates)),
        "informative_training_races_R_mix": mixed_races,
        "informative_pair_rows": 2 * mixed_races,
    }


def verify_oos_sources(
    features: pd.DataFrame,
    historical_receipt: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[int, pd.Series]]:
    provider_records: list[dict[str, Any]] = []
    provider_score_maps: dict[int, pd.Series] = {}

    for race_year, (expected_rows, expected_races) in EXPECTED_YEAR_COUNTS.items():
        fold = race_year + 1
        if fold <= 2023:
            relative_base = f"{HIST_OUT_REL}/F1_STYLE6_{fold}"
            receipt_fold = historical_receipt["folds"][fold]
        else:
            relative_base = f"{STYLE_OUT_REL}/F1_STYLE6_{fold}"
            receipt_fold = None
        score_rel = f"{relative_base}/calibration_scores.parquet"
        meta_rel = f"{relative_base}/meta.json"
        score_frame = pd.read_parquet(checked_source(score_rel))
        meta = load_json_source(meta_rel)
        require("api_record_id" in score_frame and "score" in score_frame, f"invalid OOS columns: {score_rel}")
        require(score_frame["api_record_id"].is_unique, f"duplicate OOS api_record_id: {score_rel}")
        require(np.isfinite(score_frame["score"].to_numpy(dtype=float)).all(), f"non-finite OOS raw score: {score_rel}")
        require(int(meta.get("evaluation_year")) == fold, f"OOS provider fold mismatch: {meta_rel}")
        if fold <= 2023:
            require(meta.get("score_role_generated") == "calibration_only", f"historical score role mismatch: {meta_rel}")
            require(meta.get("temperature_optimizations") == 0, f"historical tau was fit: {meta_rel}")
            require(meta.get("outcome_metrics_computed") is False, f"historical metrics were computed: {meta_rel}")
            require(meta.get("evaluation_scores_generated") is False, f"historical evaluation scores exist: {meta_rel}")
            require(meta.get("pair_fit_performed") is False, f"historical pair fit exists: {meta_rel}")
            require(receipt_fold["calibration_scores_sha256"] == sha256(checked_source(score_rel)), f"receipt raw score hash mismatch: {score_rel}")
            require(receipt_fold["meta_sha256"] == sha256(checked_source(meta_rel)), f"receipt metadata hash mismatch: {meta_rel}")
            model_rel = f"{relative_base}/top3.txt"
            require(receipt_fold["model_sha256"] == sha256(checked_source(model_rel)), f"receipt model hash mismatch: {model_rel}")
        else:
            require(meta.get("calibration_scores_sha256") == sha256(checked_source(score_rel)), f"current calibration score hash mismatch: {score_rel}")
            model_rel = f"{relative_base}/top3.txt"
            require(meta.get("model_sha256") == sha256(checked_source(model_rel)), f"current model hash mismatch: {model_rel}")

        joined = score_frame.merge(
            features[["api_record_id", "race_id", "race_date", "year"]],
            on="api_record_id",
            how="left",
            validate="one_to_one",
            indicator=True,
        )
        year_rows = features.loc[features["year"].eq(race_year), "api_record_id"]
        require(joined["_merge"].eq("both").all(), f"OOS score key missing in features for {race_year}")
        require(joined["year"].eq(race_year).all(), f"OOS provider mapped to wrong year: {race_year}")
        require(len(score_frame) == expected_rows and joined["race_id"].nunique() == expected_races, f"OOS inventory changed for {race_year}")
        require(set(score_frame["api_record_id"]) == set(year_rows), f"OOS score does not cover full year {race_year}")
        refit_max = pd.Timestamp(meta["refit_max"])
        race_dates = pd.to_datetime(joined["race_date"], errors="raise")
        require(((race_dates - refit_max).dt.days >= 2).all(), f"OOS provider violates row-level T-2 boundary for {race_year}")
        require(str(race_dates.min().date()) == str(meta["calibration_min"]), f"OOS calibration start mismatch for {race_year}")
        require(str(race_dates.max().date()) == str(meta["calibration_max"]), f"OOS calibration end mismatch for {race_year}")
        require(int(meta["calibration_rows"]) == expected_rows, f"OOS metadata row count mismatch for {race_year}")
        require(int(meta["calibration_races"]) == expected_races, f"OOS metadata race count mismatch for {race_year}")
        if receipt_fold is not None:
            require(receipt_fold["calibration_rows"] == expected_rows, f"historical receipt row count mismatch for {race_year}")
            require(receipt_fold["calibration_races"] == expected_races, f"historical receipt race count mismatch for {race_year}")
            require(receipt_fold["refit_max"] == meta["refit_max"], f"historical receipt refit boundary mismatch for {race_year}")
        provider_score_maps[race_year] = score_frame.set_index("api_record_id")["score"]
        provider_records.append(
            {
                "race_year": race_year,
                "provider_fold": fold,
                "provider_role": "calibration_raw_score_only",
                "rows": expected_rows,
                "races": expected_races,
                "first_date": str(race_dates.min().date()),
                "last_date": str(race_dates.max().date()),
                "provider_refit_max": str(refit_max.date()),
                "score_sha256": sha256(checked_source(score_rel)),
                "meta_sha256": sha256(checked_source(meta_rel)),
            }
        )
    return provider_records, provider_score_maps


def validate_eval_sources(features: pd.DataFrame, baseline: pd.DataFrame) -> list[dict[str, Any]]:
    feature_eval = features.loc[features["year"].isin(EXPECTED_CURRENT_FOLDS)].copy()
    require(len(feature_eval) == EXPECTED_EVAL_RUNNERS, "frozen evaluation feature runner count changed")
    require(feature_eval["race_id"].nunique() == EXPECTED_EVAL_RACES, "frozen evaluation feature race count changed")
    require(baseline["api_record_id"].is_unique, "baseline api_record_id is not unique")
    require(not baseline.duplicated(["race_id", "horse_number"]).any(), "duplicate baseline race/horse-number key")
    require(set(feature_eval["api_record_id"]) == set(baseline["api_record_id"]), "baseline and frozen feature keys differ")
    require(len(baseline) == EXPECTED_EVAL_RUNNERS, "baseline runner count changed")
    require(baseline["race_id"].nunique() == EXPECTED_EVAL_RACES, "baseline race count changed")
    require(np.isfinite(baseline["score"].to_numpy(dtype=float)).all(), "baseline raw score is non-finite")
    require(np.isfinite(baseline["p_top3"].to_numpy(dtype=float)).all(), "baseline p_top3 is non-finite")
    require(baseline["p_top3"].between(0.0, 1.0).all(), "baseline p_top3 is outside [0,1]")
    require(baseline["y"].isin([0, 1]).all(), "baseline y is not binary")
    require(not baseline["horse_id"].astype(str).eq("3005648").any(), "excluded horse 3005648 appears in baseline")
    require(set(baseline["variant"].unique()) == {"F1_STYLE6"}, "baseline source variant changed")
    banned_columns = [
        column for column in baseline.columns
        if any(token in column.lower() for token in ("odds", "favorite", "fav"))
    ]
    require(not banned_columns, f"odds/favorite columns found in baseline source: {banned_columns}")

    joined = baseline.merge(
        feature_eval[["api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number", "finish_position", "field_n"]],
        on="api_record_id",
        how="left",
        validate="one_to_one",
        suffixes=("_base", "_feature"),
        indicator=True,
    )
    require(joined["_merge"].eq("both").all(), "baseline row is absent from frozen feature source")
    for left, right in (("race_id_base", "race_id_feature"), ("race_date_base", "race_date_feature"),
                        ("year_base", "year_feature"), ("horse_id_base", "horse_id_feature"),
                        ("horse_number_base", "horse_number_feature"), ("field_n_base", "field_n_feature")):
        require(joined[left].eq(joined[right]).all(), f"baseline identity field differs from frozen features: {left}")
    expected_y = joined["finish_position"].le(3).astype(np.int8)
    require(np.array_equal(joined["y"].to_numpy(dtype=np.int8), expected_y.to_numpy()), "baseline y differs from frozen Top3 label")

    eval_records: list[dict[str, Any]] = []
    canonical_features: list[str] | None = None
    for year in EXPECTED_CURRENT_FOLDS:
        base_rel = f"{STYLE_OUT_REL}/F1_STYLE6_{year}"
        meta_rel = f"{base_rel}/meta.json"
        score_rel = f"{base_rel}/evaluation_scores.parquet"
        meta = load_json_source(meta_rel)
        score_frame = pd.read_parquet(checked_source(score_rel))
        require(int(meta.get("evaluation_year")) == year, f"evaluation provider year mismatch: {meta_rel}")
        require(len(meta.get("features", [])) == 30 and int(meta.get("feature_count")) == 30, "frozen F1_STYLE6 input count changed")
        if canonical_features is None:
            canonical_features = list(meta["features"])
        require(list(meta["features"]) == canonical_features, f"frozen F1_STYLE6 30-input order changed in {year}")
        require(set(SELECTOR_FEATURES).issubset(set(meta["features"])), "selector input is outside frozen F1_STYLE6 30 columns")
        require(meta.get("evaluation_scores_sha256") == sha256(checked_source(score_rel)), f"evaluation score hash mismatch: {score_rel}")
        require(score_frame["api_record_id"].is_unique and "score" in score_frame, f"invalid evaluation score schema: {score_rel}")
        eval_year = baseline.loc[baseline["year"].eq(year)].copy()
        require(set(score_frame["api_record_id"]) == set(eval_year["api_record_id"]), f"evaluation score coverage differs for {year}")
        score_map = score_frame.set_index("api_record_id")["score"]
        require(np.isfinite(score_map.to_numpy(dtype=float)).all(), f"non-finite evaluation score in {year}")
        replay = score_map.reindex(eval_year["api_record_id"]).to_numpy(dtype=float)
        base_score = eval_year["score"].to_numpy(dtype=float)
        require(np.array_equal(replay, base_score), f"baseline raw score differs from frozen F1_STYLE6 evaluation score in {year}")
        tau = float(meta["tau"])
        eval_dates = pd.to_datetime(eval_year["race_date"], errors="raise")
        refit_max = pd.Timestamp(meta["refit_max"])
        require(((eval_dates - refit_max).dt.days >= 2).all(), f"evaluation provider violates row-level T-2 boundary in {year}")
        require(str(eval_dates.min().date()) == str(meta["evaluation_min"]), f"evaluation minimum date mismatch in {year}")
        require(str(eval_dates.max().date()) == str(meta["evaluation_max"]), f"evaluation maximum date mismatch in {year}")
        require(int(meta.get("evaluation_rows")) == len(eval_year), f"evaluation metadata runner count mismatch in {year}")
        require(int(meta.get("evaluation_races")) == eval_year["race_id"].nunique(), f"evaluation metadata race count mismatch in {year}")
        tau_calibration_max = pd.Timestamp(meta["calibration_max"])
        require((eval_dates.min() - tau_calibration_max).days >= 2, f"evaluation tau calibration window violates T-2 boundary in {year}")
        require(np.isfinite(tau) and tau > 0.0, f"invalid frozen temperature in {year}")
        eval_records.append(
            {
                "year": year,
                "rows": len(eval_year),
                "races": int(eval_year["race_id"].nunique()),
                "first_date": str(eval_dates.min().date()),
                "last_date": str(eval_dates.max().date()),
                "provider_refit_max": str(refit_max.date()),
                "raw_score_exact_match_to_baseline": True,
                "tau_calibration_max": str(tau_calibration_max.date()),
                "p_top3_preserved_from_locked_baseline": True,
            }
        )
    return eval_records


def validate_schedule(features: pd.DataFrame) -> dict[str, Any]:
    receipt_rel = f"{BOOTSTRAP_REL}/date_bootstrap_schedule.json"
    schedule_rel = f"{BOOTSTRAP_REL}/date_bootstrap_schedule.npy"
    receipt = load_json_source(receipt_rel)
    schedule_path = checked_source(schedule_rel)
    require(receipt.get("status") == "FROZEN_BEFORE_EVALUATION_METRICS", "bootstrap schedule was not frozen before metrics")
    require(receipt.get("seed") == 20261011 and receipt.get("draws") == 2000, "bootstrap schedule recipe changed")
    require(receipt.get("dates_per_draw") == EXPECTED_EVAL_DATES, "bootstrap date count changed")
    require(receipt.get("schedule_sha256") == sha256(schedule_path), "bootstrap schedule hash differs from receipt")
    require(receipt.get("source_features_sha256") == sha256(checked_source(FEATURES_REL)), "bootstrap feature source hash mismatch")
    require(receipt.get("numpy_version") == np.__version__, "bootstrap schedule NumPy version differs from runtime")
    evaluation_features = features.loc[features["year"].isin(EXPECTED_CURRENT_FOLDS)].copy()
    dates = sorted(pd.to_datetime(evaluation_features["race_date"], errors="raise").dt.strftime("%Y-%m-%d").unique().tolist())
    date_hash = hashlib.sha256("\n".join(dates).encode("utf-8")).hexdigest()
    require(len(dates) == EXPECTED_EVAL_DATES, "evaluation date inventory changed")
    require(date_hash == receipt.get("date_inventory_sha256"), "bootstrap date ordering/inventory mismatch")
    require(dates[0] == receipt.get("date_min") and dates[-1] == receipt.get("date_max"), "bootstrap date span mismatch")
    schedule = np.load(schedule_path, allow_pickle=False)
    require(schedule.shape == (2000, EXPECTED_EVAL_DATES) and schedule.dtype == np.int32, "bootstrap schedule shape or type changed")
    require(((schedule >= 0) & (schedule < len(dates))).all(), "bootstrap schedule has invalid date index")
    expected = np.random.default_rng(20261011).integers(
        0, len(dates), size=(2000, len(dates)), endpoint=False, dtype=np.int32
    )
    require(np.array_equal(schedule, expected), "bootstrap values differ from frozen seed recipe")
    return {
        "draws": int(schedule.shape[0]),
        "dates_per_draw": len(dates),
        "date_min": dates[0],
        "date_max": dates[-1],
        "date_inventory_sha256": date_hash,
        "schedule_sha256": sha256(schedule_path),
        "schedule_matches_frozen_recipe": True,
    }


def run() -> dict[str, Any]:
    require(OUT.is_dir() and not OUT.is_symlink(), "study outputs directory is missing or symlinked")
    require(not PREFLIGHT_PATH.exists(), "refusing to overwrite a preflight receipt")
    source_hashes, source_lock_hash = verify_source_lock()
    historical = validate_historical_receipt(source_hashes)
    feature_path = checked_source(FEATURES_REL)
    baseline_path = checked_source(BASELINE_REL)
    features = pd.read_parquet(feature_path)
    baseline = pd.read_parquet(baseline_path)

    required_feature_columns = {
        "api_record_id", "race_id", "race_date", "year", "horse_id", "horse_number",
        "finish_position", "distance_m", "field_n", "history_cutoff", "latest_history_date",
        *SELECTOR_FEATURES,
    }
    require(required_feature_columns.issubset(features.columns), "frozen feature schema is missing required fields")
    require(features["api_record_id"].is_unique, "frozen feature api_record_id is not unique")
    require(not features.duplicated(["race_id", "horse_number"]).any(), "duplicate frozen race/horse-number key")
    require(not features["horse_id"].astype(str).eq("3005648").any(), "excluded horse 3005648 appears in frozen feature source")
    require(pd.to_datetime(features["race_date"], errors="coerce").notna().all(), "invalid race date in frozen features")
    race_dates = pd.to_datetime(features["race_date"], errors="raise")
    cutoffs = pd.to_datetime(features["history_cutoff"], errors="coerce")
    latest = pd.to_datetime(features["latest_history_date"], errors="coerce")
    require(cutoffs.notna().all(), "missing/invalid history cutoff")
    require((cutoffs == race_dates - pd.Timedelta(days=2)).all(), "frozen history cutoff is not race date minus two days")
    require((latest.isna() | latest.le(cutoffs)).all(), "latest historical input exceeds T-2 cutoff")
    for column in ("observed_starts", "same_starts", "same_valid_times"):
        require(np.isfinite(features[column].to_numpy(dtype=float)).all(), f"non-finite support input: {column}")
        require(features[column].ge(0).all(), f"negative support input: {column}")
    for column in ("days_since_start", "days_since_same"):
        observed = features[column].dropna().to_numpy(dtype=float)
        require(np.isfinite(observed).all() and (observed >= 0).all(), f"invalid recency input: {column}")
    ability = features["mean5_rank_fraction"].dropna().to_numpy(dtype=float)
    require(np.isfinite(ability).all(), "non-finite field-relative ability input")
    require(not features["horse_id"].astype(str).eq("3005648").any(), "excluded horse 3005648 is present")

    label_source = features.copy()
    label_source["y"] = label_source["finish_position"].le(3).astype(np.int8)
    assert_race_roster(label_source, "y", "frozen source")

    historical_records, training_score_maps = verify_oos_sources(features, historical)
    evaluation_records = validate_eval_sources(features, baseline)
    assert_race_roster(baseline, None, "frozen baseline evaluation")
    require((baseline.groupby("race_id", sort=False)["y"].sum() == 3).all(), "baseline race does not contain exactly three Top3 labels")
    main_races = int(baseline.loc[baseline["distance_m"].isin([900, 1000, 1110, 1200]), "race_id"].nunique())
    require(main_races == EXPECTED_MAIN_RACES, "primary four-distance cohort changed")
    full_dates = set(pd.to_datetime(baseline["race_date"], errors="raise").dt.strftime("%Y-%m-%d"))
    primary_dates = set(pd.to_datetime(baseline.loc[baseline["distance_m"].isin([900, 1000, 1110, 1200]), "race_date"], errors="raise").dt.strftime("%Y-%m-%d"))
    require(primary_dates == full_dates and len(full_dates) == EXPECTED_EVAL_DATES,
            "primary four-distance cohort does not cover all 269 evaluation dates")
    schedule = validate_schedule(features)

    window_records: list[dict[str, Any]] = []
    historical_records_by_year = {record["race_year"] for record in historical_records}
    for evaluation_year, spec in EXPECTED_SELECTOR_WINDOWS.items():
        first_year, last_year, expected_rows, expected_races, expected_last_date, eval_rows, eval_races = spec
        train = features.loc[features["year"].between(first_year, last_year)]
        evaluation = baseline.loc[baseline["year"].eq(evaluation_year)]
        train_max = pd.to_datetime(train["race_date"], errors="raise").max()
        eval_min = pd.to_datetime(evaluation["race_date"], errors="raise").min()
        require(len(train) == expected_rows and train["race_id"].nunique() == expected_races, f"selector training window changed for {evaluation_year}")
        require(str(train_max.date()) == expected_last_date, f"selector training max label date changed for {evaluation_year}")
        require(len(evaluation) == eval_rows and evaluation["race_id"].nunique() == eval_races, f"selector evaluation cohort changed for {evaluation_year}")
        require((eval_min - train_max).days >= 2, f"selector train/evaluation T-2 boundary failed for {evaluation_year}")
        for year in range(first_year, last_year + 1):
            require(year in historical_records_by_year, f"selector training year lacks recipe-valid OOS source: {year}")
        candidate_counts = training_candidate_counts(features, training_score_maps, first_year, last_year)
        require(candidate_counts["source_runners"] == expected_rows, f"training source runner count mismatch for {evaluation_year}")
        require(candidate_counts["source_races"] == expected_races, f"training source race count mismatch for {evaluation_year}")
        require(candidate_counts["candidate_fit_rows"] == 3 * expected_races, f"training candidate fit row count mismatch for {evaluation_year}")
        window_records.append(
            {
                "evaluation_year": evaluation_year,
                "training_year_min": first_year,
                "training_year_max": last_year,
                "training_rows": len(train),
                "training_races": int(train["race_id"].nunique()),
                "training_last_label_date": str(train_max.date()),
                "evaluation_rows": len(evaluation),
                "evaluation_races": int(evaluation["race_id"].nunique()),
                "evaluation_first_date": str(eval_min.date()),
                "train_to_evaluation_gap_days": int((eval_min - train_max).days),
                **candidate_counts,
            }
        )

    receipt = {
        "status": "PASS",
        "scope": "source_contract_only_before_selector_fit",
        "source_lock_sha256": source_lock_hash,
        "source_hashes": source_hashes,
        "source_rows": int(len(features)),
        "source_races": int(features["race_id"].nunique()),
        "source_date_min": str(race_dates.min().date()),
        "source_date_max": str(race_dates.max().date()),
        "frozen_f1_feature_count": 30,
        "selector_input_columns": list(SELECTOR_FEATURES),
        "historical_oos_providers": historical_records,
        "frozen_evaluation_providers": evaluation_records,
        "selector_windows": window_records,
        "evaluation_rows": len(baseline),
        "evaluation_races": int(baseline["race_id"].nunique()),
        "evaluation_dates": int(baseline["race_date"].nunique()),
        "primary_four_distance_races": main_races,
        "primary_covers_all_evaluation_dates": True,
        "date_bootstrap": schedule,
        "history_cutoff_is_race_minus_two_days": True,
        "latest_history_never_exceeds_cutoff": True,
        "excluded_horse_3005648_absent": True,
        "odds_or_favorite_inputs_present": False,
        "baseline_score_p_y_preserved_source": True,
        "historical_same_year_tau_used_as_selector_input": False,
        "model_fit_performed": False,
        "selector_predictions_generated": False,
        "axis_hit_metrics_computed": False,
        "outcome_performance_metrics_computed": False,
    }
    output_path = OUT / "PREFLIGHT.json"
    require(not output_path.is_symlink() and output_path.resolve().is_relative_to(STUDY), "preflight output escaped study folder")
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return receipt


if __name__ == "__main__":
    try:
        result = run()
    except PreflightError as exc:
        raise SystemExit(f"PREFLIGHT BLOCKED: {exc}") from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))
