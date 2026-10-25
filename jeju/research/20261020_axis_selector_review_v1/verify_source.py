"""Read-only source and chronology review for the Jeju axis-selector study.

The script checks frozen artifacts and writes only outputs/SOURCE_REVIEW.json.
It does not train a model, connect to a database, or access the network.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[3]
STUDY = ROOT / "jeju/research/20261020_axis_selector_review_v1"
OUT = STUDY / "outputs"
FEATURES_PATH = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet"
LINEAGE_PATH = ROOT / "jeju/research/20261010_style_history_ablation_v1/outputs/style_history_lineage.parquet"
FROZEN_PREDICTIONS = ROOT / "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/baseline_runner_predictions.parquet"
HISTORICAL = ROOT / "jeju/research/20261011_pair_top3_oos_expansion_v1"
FIXED_STUDY = ROOT / "jeju/research/20261010_style_history_ablation_v1"
FIXED_F1 = FIXED_STUDY / "outputs"
TARGET_DISTANCES = (900, 1000, 1110, 1200)
EXPECTED_FEATURE_ROWS = 52155
EXPECTED_FEATURE_RACES = 5206
EXPECTED_BASELINE_ROWS = 17412
EXPECTED_BASELINE_RACES = 1779
EXPECTED_PRIMARY_ROWS = 14714
EXPECTED_PRIMARY_RACES = 1503


class ReviewError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReviewError(message)


def checked(path: Path) -> Path:
    require(not path.is_symlink(), f"symlink input is not allowed: {path}")
    resolved = path.resolve(strict=True)
    require(resolved.is_file() and resolved.is_relative_to(ROOT), f"input outside workspace: {path}")
    return resolved


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with checked(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(checked(path).read_text(encoding="utf-8"))


def load_style_module():
    path = checked(FIXED_STUDY / "prepare.py")
    spec = importlib.util.spec_from_file_location("axis_selector_review_f1_prepare", path)
    require(spec is not None and spec.loader is not None, "cannot load frozen F1 evaluator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit_feature_dates(features: pd.DataFrame, lineage: pd.DataFrame) -> dict:
    dates = pd.to_datetime(features["race_date"], errors="coerce").dt.normalize()
    cutoffs = pd.to_datetime(features["history_cutoff"], errors="coerce").dt.normalize()
    latest = pd.to_datetime(features["latest_history_date"], errors="coerce").dt.normalize()
    require(dates.notna().all() and cutoffs.notna().all(), "invalid feature date/cutoff")
    require((cutoffs == dates - pd.Timedelta(days=2)).all(), "feature cutoff differs from race date T-2")
    require((latest.isna() | (latest <= cutoffs)).all(), "feature history exceeds T-2")

    feature_dates = features.set_index("api_record_id")["race_date"]
    target_dates = pd.to_datetime(lineage["target_api_record_id"].map(feature_dates), errors="coerce").dt.normalize()
    target_cutoffs = pd.to_datetime(lineage["target_cutoff"], errors="coerce").dt.normalize()
    source_dates = pd.to_datetime(lineage["source_race_date"], errors="coerce").dt.normalize()
    require(target_dates.notna().all(), "lineage target key does not map to a feature row")
    require(target_cutoffs.notna().all() and (target_cutoffs == target_dates - pd.Timedelta(days=2)).all(),
            "lineage target cutoff differs from race date T-2")
    require(source_dates.notna().all() and (source_dates <= target_cutoffs).all(),
            "lineage source date exceeds target cutoff")
    return {
        "feature_rows_checked": int(len(features)),
        "feature_t2_cutoff_pass": True,
        "latest_history_at_or_before_cutoff_pass": True,
        "style_lineage_rows_checked": int(len(lineage)),
        "lineage_target_t2_pass": True,
        "lineage_source_at_or_before_cutoff_pass": True,
    }


def audit_oos_scores(features: pd.DataFrame) -> list[dict]:
    records = []
    source_columns: list[str] | None = None
    for target_year in range(2019, 2026):
        provider_year = target_year + 1
        if provider_year <= 2023:
            provider_dir = HISTORICAL / "outputs" / f"F1_STYLE6_{provider_year}"
        else:
            provider_dir = FIXED_F1 / f"F1_STYLE6_{provider_year}"
        meta_path = provider_dir / "meta.json"
        score_path = provider_dir / "calibration_scores.parquet"
        model_path = provider_dir / "top3.txt"
        meta = read_json(meta_path)
        score = pd.read_parquet(checked(score_path))
        target = features.loc[features["year"].eq(target_year)].copy()
        require(len(target) > 0, f"no feature rows for target year {target_year}")
        require(meta.get("variant") == "F1_STYLE6" and int(meta.get("evaluation_year", -1)) == provider_year,
                f"wrong F1 provider metadata for target year {target_year}")
        require(meta.get("features") and len(meta["features"]) == 30, f"F1 feature count mismatch {provider_year}")
        if source_columns is None:
            source_columns = list(meta["features"])
        require(list(meta["features"]) == source_columns, "F1 input contract changes between provider folds")
        require(score.columns.tolist() == ["api_record_id", "score"], f"score schema mismatch: {score_path}")
        require(score["api_record_id"].is_unique, f"duplicate raw score keys: {score_path}")
        require(np.isfinite(pd.to_numeric(score["score"], errors="raise").to_numpy(dtype="float64")).all(),
                f"nonfinite raw score: {score_path}")
        joined = target[["api_record_id", "race_id", "race_date"]].merge(
            score, on="api_record_id", how="outer", validate="one_to_one", indicator=True
        )
        require(joined["_merge"].eq("both").all(), f"raw score coverage mismatch: {target_year}")
        race_dates = pd.to_datetime(target["race_date"], errors="coerce").dt.normalize()
        refit_max = pd.Timestamp(meta["refit_max"]).normalize()
        cutoff_min = race_dates.min() - pd.Timedelta(days=2)
        require(refit_max <= cutoff_min, f"provider refit is not before target T-2: {target_year}")
        require(str(meta.get("score_role_generated", "calibration_only")) == "calibration_only",
                f"non-calibration provider role for target year {target_year}")
        require(int(meta.get("calibration_rows", -1)) == len(score), f"provider row count mismatch {target_year}")
        require(int(meta.get("calibration_races", -1)) == target["race_id"].nunique(),
                f"provider race count mismatch {target_year}")
        require(pd.Timestamp(meta["calibration_min"]).date() == race_dates.min().date(),
                f"provider calibration start mismatch {target_year}")
        require(pd.Timestamp(meta["calibration_max"]).date() == race_dates.max().date(),
                f"provider calibration end mismatch {target_year}")
        require(meta.get("calibration_scores_sha256") == sha256(score_path),
                f"provider score hash mismatch {target_year}")
        require(meta.get("model_sha256") == sha256(model_path), f"provider model hash mismatch {target_year}")
        if provider_year <= 2023:
            require(meta.get("source_features_sha256") == sha256(FEATURES_PATH),
                    f"historical provider feature source hash mismatch {target_year}")
            require(meta.get("outcome_metrics_computed") is False, f"historical outcome metrics present {provider_year}")
            require(meta.get("evaluation_scores_generated") is False, f"historical evaluation scores present {provider_year}")
            require(meta.get("pair_fit_performed") is False, f"pair fit flag unexpected {provider_year}")
            require(int(meta.get("temperature_optimizations", -1)) == 0,
                    f"historical temperature fit unexpected {provider_year}")
        records.append({
            "target_year": target_year,
            "provider_fold_year": provider_year,
            "provider_role": "calibration_only",
            "provider_path": str(score_path.relative_to(ROOT)),
            "provider_model_sha256": sha256(model_path),
            "provider_meta_sha256": sha256(meta_path),
            "raw_score_sha256": sha256(score_path),
            "rows": int(len(score)),
            "races": int(target["race_id"].nunique()),
            "first_race_date": race_dates.min().date().isoformat(),
            "last_race_date": race_dates.max().date().isoformat(),
            "refit_max": refit_max.date().isoformat(),
            "earliest_t2": cutoff_min.date().isoformat(),
            "refit_before_t2": True,
            "exact_unique_finite_score_coverage": True,
            "temperature_optimized_on_target_year": False if provider_year <= 2023 else None,
        })
    return records


def audit_frozen_evaluation(features: pd.DataFrame, style_module) -> dict:
    predictions = pd.read_parquet(checked(FROZEN_PREDICTIONS))
    require(predictions["api_record_id"].is_unique, "duplicate frozen baseline runner key")
    forbidden = ("odds", "favorite", "fav_id", "인기", "배당")
    columns = list(predictions.columns) + list(features.columns)
    require(not any(any(term in str(column).casefold() for term in forbidden) for column in columns),
            "market/favorite field found in frozen score or feature inputs")

    eval_features = features.loc[features["year"].isin((2024, 2025, 2026))].copy()
    require(len(eval_features) == EXPECTED_BASELINE_ROWS, "frozen baseline runner denominator changed")
    require(eval_features["race_id"].nunique() == EXPECTED_BASELINE_RACES, "frozen baseline race count changed")
    require(eval_features["race_date"].nunique() == 269, "frozen baseline date count changed")
    model_columns = None
    year_details = []
    for year in (2024, 2025, 2026):
        fold_dir = FIXED_F1 / f"F1_STYLE6_{year}"
        meta = read_json(fold_dir / "meta.json")
        score_path = fold_dir / "evaluation_scores.parquet"
        score = pd.read_parquet(checked(score_path))
        fold_features = features.loc[features["year"].eq(year)].reset_index(drop=True)
        fold_pred = predictions.loc[predictions["year"].eq(year)].copy()
        require(meta.get("variant") == "F1_STYLE6" and int(meta.get("evaluation_year", -1)) == year,
                f"wrong frozen F1 evaluation metadata {year}")
        require(len(meta.get("features", [])) == 30, f"frozen F1 model does not expose 30 inputs {year}")
        if model_columns is None:
            model_columns = list(meta["features"])
        require(list(meta["features"]) == model_columns, "frozen F1 30-input contract differs by year")
        require(set(model_columns).issubset(features.columns), "frozen F1 inputs absent from feature table")
        require(score.columns.tolist() == ["api_record_id", "score"], f"evaluation score schema mismatch {year}")
        require(score["api_record_id"].astype("int64").tolist() == fold_features["api_record_id"].astype("int64").tolist(),
                f"evaluation score key/order mismatch {year}")
        require(meta.get("evaluation_scores_sha256") == sha256(score_path), f"evaluation score hash mismatch {year}")
        eval_dates = pd.to_datetime(fold_features["race_date"], errors="coerce").dt.normalize()
        require(pd.Timestamp(meta["refit_max"]).normalize() <= eval_dates.min() - pd.Timedelta(days=2),
                f"frozen model refit date is not before evaluation T-2 {year}")
        require(pd.Timestamp(meta["calibration_max"]).normalize() <= eval_dates.min() - pd.Timedelta(days=2),
                f"frozen tau uses outcomes after evaluation T-2 {year}")
        require(fold_pred["api_record_id"].astype("int64").tolist() == fold_features["api_record_id"].astype("int64").tolist(),
                f"frozen baseline prediction key/order mismatch {year}")
        require(np.array_equal(fold_pred["score"].to_numpy(dtype="float64"), score["score"].to_numpy(dtype="float64")),
                f"frozen baseline score differs from evaluation score {year}")
        race_frame, runner_frame, _ = style_module.F1.base.evaluate(
            fold_features, score["score"].to_numpy(dtype="float64"), float(meta["tau"]), meta["variant"]
        )
        require(len(race_frame) == fold_features["race_id"].nunique(), f"frozen evaluator race count changed {year}")
        runner_frame = runner_frame.sort_values("api_record_id").reset_index(drop=True)
        fold_pred = fold_pred.sort_values("api_record_id").reset_index(drop=True)
        require(runner_frame["api_record_id"].equals(fold_pred["api_record_id"]),
                f"frozen evaluator key mismatch {year}")
        score_diff = float(np.max(np.abs(runner_frame["score"].to_numpy() - fold_pred["score"].to_numpy())))
        probability_diff = float(np.max(np.abs(runner_frame["p_top3"].to_numpy() - fold_pred["p_top3"].to_numpy())))
        label_diff = int(np.max(np.abs(runner_frame["y"].to_numpy(dtype="int8") - fold_pred["y"].to_numpy(dtype="int8"))))
        require(score_diff == 0.0 and probability_diff == 0.0 and label_diff == 0,
                f"frozen baseline prediction replay mismatch {year}")
        year_details.append({
            "year": year,
            "rows": int(len(fold_features)),
            "races": int(fold_features["race_id"].nunique()),
            "first_race_date": eval_dates.min().date().isoformat(),
            "last_race_date": eval_dates.max().date().isoformat(),
            "model_refit_max": str(meta["refit_max"]),
            "tau_calibration_max": str(meta["calibration_max"]),
            "model_inputs": len(model_columns),
            "score_max_abs_difference": score_diff,
            "p_top3_max_abs_difference": probability_diff,
            "label_max_difference": label_diff,
            "evaluation_scores_sha256": sha256(score_path),
            "meta_sha256": sha256(fold_dir / "meta.json"),
        })

    joined = predictions[["api_record_id", "race_id", "race_date", "year", "horse_number", "score", "p_top3", "y"]].merge(
        eval_features[["api_record_id", "race_id", "race_date", "year", "horse_number", "distance_m", "finish_position"]],
        on=["api_record_id", "race_id", "race_date", "year", "horse_number"],
        how="outer", validate="one_to_one", indicator=True,
    )
    require(joined["_merge"].eq("both").all() and len(joined) == EXPECTED_BASELINE_ROWS,
            "frozen baseline predictions do not align exactly with evaluation feature rows")
    require((joined["y"].astype("int8") == joined["finish_position"].le(3).astype("int8")).all(),
            "frozen baseline Top3 labels differ from finish positions")
    primary = eval_features.loc[pd.to_numeric(eval_features["distance_m"], errors="raise").isin(TARGET_DISTANCES)]
    require(len(primary) == EXPECTED_PRIMARY_ROWS and primary["race_id"].nunique() == EXPECTED_PRIMARY_RACES,
            "fixed target-distance primary cohort changed")
    require(primary["race_id"].isin(eval_features["race_id"]).all(), "primary race absent from full evaluation")
    return {
        "full_cohort": {
            "rows": int(len(eval_features)),
            "races": int(eval_features["race_id"].nunique()),
            "dates": int(eval_features["race_date"].nunique()),
            "scope": "2024-01-05 through 2026-09-19; full 2024-2026 frozen baseline",
        },
        "primary_target_distance_cohort": {
            "rows": int(len(primary)),
            "races": int(primary["race_id"].nunique()),
            "distances_m": list(TARGET_DISTANCES),
            "scope": "fixed four-distance mask; not favorite/market filtered",
        },
        "favorite_1477_cohort_used": False,
        "odds_or_favorite_columns_used": False,
        "frozen_predictions_exactly_replayed": True,
        "preserved_base_inputs": 30,
        "score_p_top3_and_label_max_diff": 0.0,
        "by_year": year_details,
    }


def main() -> None:
    report_path = OUT / "SOURCE_REVIEW.json"
    require(not report_path.exists() and not report_path.is_symlink(), "refusing to overwrite source review")
    features_path = checked(FEATURES_PATH)
    lineage_path = checked(LINEAGE_PATH)
    frozen_predictions_path = checked(FROZEN_PREDICTIONS)
    features = pd.read_parquet(features_path)
    lineage = pd.read_parquet(lineage_path, columns=["target_api_record_id", "target_cutoff", "source_race_date"])
    require(len(features) == EXPECTED_FEATURE_ROWS, "feature table row count changed")
    require(features["api_record_id"].is_unique, "feature runner keys are not unique")
    require(features["race_id"].nunique() == EXPECTED_FEATURE_RACES, "feature race count changed")
    require(not features.duplicated(["race_id", "horse_id"]).any(), "duplicate horse within race")

    fixed_meta = read_json(FIXED_F1 / "F1_STYLE6_2024/meta.json")
    model_columns = list(fixed_meta["features"])
    require(len(model_columns) == 30 and set(model_columns).issubset(features.columns),
            "frozen 30-column base input contract changed")
    prepared_lock = read_json(FIXED_F1 / "prepared_lock.json")
    require(prepared_lock.get("artifacts", {}).get("features.parquet") == sha256(FEATURES_PATH),
            "fixed F1 prepared lock does not pin the source feature table")
    feature_dates = audit_feature_dates(features, lineage)
    oos_scores = audit_oos_scores(features)
    style_module = load_style_module()
    frozen = audit_frozen_evaluation(features, style_module)

    input_paths = [
        ROOT / "jeju/AGENTS.md",
        ROOT / "jeju/docs/RESTART_PLAN_20260928.md",
        ROOT / "jeju/review_documents/README.md",
        HISTORICAL / "README.md",
        HISTORICAL / "PLAN.md",
        HISTORICAL / "historical_refit.py",
        HISTORICAL / "outputs/HISTORICAL_PREFLIGHT.json",
        HISTORICAL / "outputs/HISTORICAL_SOURCE_LOCK.json",
        HISTORICAL / "outputs/HISTORICAL_REFIT_RECEIPT.json",
        FIXED_STUDY / "prepare.py",
        FEATURES_PATH,
        LINEAGE_PATH,
        FROZEN_PREDICTIONS,
        ROOT / "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/evaluation_input_lock.json",
        ROOT / "jeju/research/20261019_distance_section_relative_evaluation_v1/outputs/evaluation_preflight.json",
        FIXED_F1 / "prepared_lock.json",
    ]
    for year in range(2020, 2027):
        if year <= 2023:
            fold_dir = HISTORICAL / "outputs" / f"F1_STYLE6_{year}"
        else:
            fold_dir = FIXED_F1 / f"F1_STYLE6_{year}"
        input_paths.extend([fold_dir / "meta.json", fold_dir / "calibration_scores.parquet", fold_dir / "top3.txt"])
        if year >= 2024:
            input_paths.append(fold_dir / "evaluation_scores.parquet")
    inputs = {str(path.relative_to(ROOT)): {"sha256": sha256(path), "bytes": checked(path).stat().st_size}
              for path in sorted(set(input_paths))}
    report = {
        "status": "PASS",
        "review_scope": "source lineage, rolling OOS raw-score timing, fixed F1_STYLE6 evaluation preservation, and cohort boundaries",
        "review_completed": "2026-10-20",
        "model_training_performed": False,
        "database_accessed": False,
        "network_accessed": False,
        "operational_registry_modified": False,
        "feature_history": feature_dates,
        "fixed_model_input_columns": model_columns,
        "oos_training_score_sources": oos_scores,
        "frozen_evaluation": frozen,
        "input_artifacts": inputs,
        "method_notes": [
            "Use one selector algorithm and fixed settings with expanding year-forward fits: 2024 train labels through 2023, 2025 through 2024, 2026 through 2025.",
            "Use raw next-fold calibration scores for historical selector training. Do not apply a tau fitted on that same calibration-year outcomes to form training p_top3 inputs.",
            "Preserve the frozen evaluation score and p_top3 outputs and join the 30 base F1_STYLE6 inputs by api_record_id with exact identity checks.",
            "Primary scope is the fixed 900/1000/1110/1200 m cohort (1,503 races); the full 1,779-race evaluation is secondary. Exclude the 1,477-race favorite cohort and all market inputs.",
            "K=3 is the primary one-horse selector candidate pool; K=5 is a coverage diagnostic. This review contains no selector performance result.",
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({
        "status": report["status"],
        "oos_training_score_years": len(oos_scores),
        "full_evaluation_races": frozen["full_cohort"]["races"],
        "primary_races": frozen["primary_target_distance_cohort"]["races"],
        "output": str(report_path.relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
