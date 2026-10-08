"""Dataset, training, evaluation, and experiment-registry commands."""

import json
import sys
from datetime import datetime
from pathlib import Path

from horse_racing.cli._common import _format_cell, _print_aligned_table
from horse_racing.db.session import SessionLocal


def write_feature_catalog_command(output: str) -> int:
    from horse_racing.analysis.features.catalog import write_feature_catalog

    count = write_feature_catalog(Path(output))
    print(f"feature 카탈로그 생성 완료: {output} (등록 {count}개)")
    return 0


def build_dataset_command(
    version: str,
    as_of_policy: str,
    start_date: str | None,
    end_date: str | None,
    output_dir: str,
    with_features: bool = True,
    feature_set: str = "rich",
    meet_codes: list[int] | None = None,
) -> int:
    from horse_racing.analysis.dataset import DatasetValidationError, build_dataset

    def to_iso(value: str | None) -> str | None:
        if value is None:
            return None
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"

    with SessionLocal() as session:
        try:
            result = build_dataset(
                session,
                version=version,
                as_of_policy=as_of_policy,
                start_date=to_iso(start_date),
                end_date=to_iso(end_date),
                meet_codes=meet_codes,
                output_dir=Path(output_dir),
                with_features=with_features,
                feature_set=feature_set,
            )
        except DatasetValidationError as exc:
            print(f"데이터셋 생성 실패: {exc}", file=sys.stderr)
            return 1

    manifest = result.manifest
    print(f"데이터셋 생성 완료: {result.dataset_path}")
    print(f"manifest: {result.manifest_path}")
    print(
        f"행 {manifest['row_count']:,} / 경주 {manifest['race_count']:,} "
        f"(원천 행 {manifest['source_row_count']:,}), "
        f"기간 {manifest['date_range']['start']} ~ {manifest['date_range']['end']}"
    )
    print(f"제외: {manifest['exclusions']}")
    print(
        "라벨 비율: "
        + ", ".join(f"{name}={value:.4f}" for name, value in manifest["label_stats"].items())
    )
    if manifest["feature_names"]:
        print(f"feature {len(manifest['feature_names'])}개, hash {manifest['feature_hash'][:12]}")
    return 0


def run_baselines_command(
    version: str,
    as_of_policy: str,
    dataset_dir: str,
    *,
    include_test: bool = False,
    report_dir: str = "data/experiments/reports",
) -> int:
    import polars as pl

    from horse_racing.analysis.baselines import (
        SPLIT_BOUNDS,
        BaselineInputError,
        fetch_win_odds,
        render_baseline_report,
        run_baselines,
    )
    from horse_racing.analysis.experiments import ModelRun, record_run

    dataset_path = Path(dataset_dir) / version / as_of_policy / "dataset.parquet"
    manifest_path = Path(dataset_dir) / version / as_of_policy / "manifest.json"
    if not dataset_path.exists():
        print(f"데이터셋 없음: {dataset_path} — build-dataset 먼저 실행", file=sys.stderr)
        return 1
    frame = pl.read_parquet(dataset_path)
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )

    with SessionLocal() as session:
        odds = fetch_win_odds(session)

    evaluate_splits: tuple[str, ...] = ("train", "valid")
    if include_test:
        evaluate_splits = ("train", "valid", "test")
        print("경고: test split 평가는 G1 판정 1회 원칙에 포함됩니다.", file=sys.stderr)

    try:
        results = run_baselines(frame, odds=odds, evaluate_splits=evaluate_splits)
    except BaselineInputError as exc:
        print(f"기준 모델 실행 실패: {exc}", file=sys.stderr)
        return 1

    manifest_slim = {
        key: manifest.get(key)
        for key in ("version", "as_of_policy", "row_count", "race_count", "feature_hash")
    }
    score_features = {"B1": ["rating"], "B2": ["form_recent5_pct"]}
    run_ids: dict[str, str] = {}
    for result in results:
        flat_metrics = {
            f"{split}_{name}": value
            for split, metrics in result.metrics.items()
            for name, value in metrics.items()
        }
        run = ModelRun(
            dataset_version=f"{version}/{as_of_policy}",
            dataset_manifest=manifest_slim,
            feature_names=score_features.get(result.baseline_id, []),
            model_type=result.model_type,
            hyperparameters=result.hyperparameters,
            seed=0,
            train_period=f"~{SPLIT_BOUNDS['train'][1]}",
            valid_period=f"{SPLIT_BOUNDS['valid'][0]}~{SPLIT_BOUNDS['valid'][1]}",
            test_period=f"{SPLIT_BOUNDS['test'][0]}~" if include_test else "",
            metrics=flat_metrics,
            notes=f"{result.baseline_id}: {result.notes}",
        )
        record_run(run)
        run_ids[result.baseline_id] = run.run_id

    report = render_baseline_report(
        results,
        dataset_version=version,
        as_of_policy=as_of_policy,
        evaluate_splits=evaluate_splits,
    )
    report_path = Path(report_dir) / f"baselines_{version}_{as_of_policy}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    for split in evaluate_splits:
        print(f"[{split}]")
        headers = ["기준", "log_loss", "brier", "auc", "ece", "top1", "top3", "coverage"]
        rows = []
        for result in results:
            metrics = result.metrics.get(split)
            if metrics is None:
                continue
            rows.append(
                [
                    result.baseline_id,
                    *[
                        _format_cell(metrics.get(name))
                        for name in (
                            "log_loss",
                            "brier",
                            "auc",
                            "ece",
                            "top1_hit_rate",
                            "top3_inclusion_rate",
                            "coverage",
                        )
                    ],
                ]
            )
        _print_aligned_table(headers, rows)
        print()
    print(f"리포트: {report_path}")
    for baseline_id, run_id in run_ids.items():
        print(f"기록됨 {baseline_id}: run_id={run_id}")
    return 0


def train_model_command(
    version: str,
    as_of_policy: str,
    dataset_dir: str,
    *,
    output_dir: str = "data/experiments/models",
    report_dir: str = "data/experiments/reports",
    seed: int = 42,
    calibration: str = "auto",
    profile: str = "legacy_all",
) -> int:
    import polars as pl

    from horse_racing.analysis.baselines import SPLIT_BOUNDS
    from horse_racing.analysis.experiments import ModelRun, new_run_id, record_run
    from horse_racing.analysis.lightgbm_model import (
        ModelInputError,
        render_model_report,
        save_bundle,
        train_lightgbm_models,
    )
    from horse_racing.analysis.model_profiles import (
        PROFILES,
        ModelProfileError,
        select_profile_features,
    )

    dataset_root = Path(dataset_dir) / version / as_of_policy
    dataset_path = dataset_root / "dataset.parquet"
    manifest_path = dataset_root / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"데이터셋 또는 manifest 없음: {dataset_root}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    feature_names = list(manifest.get("feature_names") or [])
    if not feature_names:
        print(
            "manifest에 feature_names가 없습니다. build-dataset을 다시 실행하세요.",
            file=sys.stderr,
        )
        return 1
    try:
        feature_names = select_profile_features(feature_names, profile)
    except ModelProfileError as exc:
        print(f"모델 프로필 적용 실패: {exc}", file=sys.stderr)
        return 1

    frame = pl.read_parquet(dataset_path)
    try:
        result = train_lightgbm_models(
            frame,
            feature_names=feature_names,
            dataset_version=version,
            as_of_policy=as_of_policy,
            seed=seed,
            calibration=calibration,
        )
    except ModelInputError as exc:
        print(f"모델 학습 실패: {exc}", file=sys.stderr)
        return 1

    run_id = new_run_id()
    artifact_dir = Path(output_dir) / run_id
    model_path = artifact_dir / "model.pkl"
    predictions_path = artifact_dir / "predictions_valid.parquet"
    save_bundle(result.bundle, model_path)
    result.valid_predictions.write_parquet(predictions_path)

    report = render_model_report(result.bundle, result.valid_metrics, run_id=run_id)
    report_path = Path(report_dir) / f"lightgbm_{version}_{as_of_policy}_{run_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    primary = result.valid_metrics["win"]
    flat_metrics = {
        "valid_log_loss": primary["log_loss"],
        "valid_brier": primary["brier"],
        "valid_auc": primary.get("auc", float("nan")),
        "valid_ece": primary["ece"],
        "valid_top1_hit_rate": primary["top1_hit_rate"],
        "valid_top3_inclusion_rate": primary["top3_inclusion_rate"],
    }
    for label, values in result.valid_metrics.items():
        for metric_name in ("log_loss", "brier", "auc", "ece"):
            if metric_name in values:
                flat_metrics[f"valid_{label}_{metric_name}"] = values[metric_name]

    manifest_slim = {
        key: manifest.get(key)
        for key in ("version", "as_of_policy", "row_count", "race_count", "feature_hash")
    }
    run = ModelRun(
        run_id=run_id,
        dataset_version=f"{version}/{as_of_policy}",
        dataset_manifest=manifest_slim,
        feature_names=feature_names,
        model_type="lightgbm_binary_bundle",
        hyperparameters={
            **result.bundle.hyperparameters,
            "model_profile": profile,
            "model_profile_description": PROFILES[profile].description,
            "artifact_path": str(model_path),
            "calibration_requested": calibration,
            "calibration_selected": {
                label: target.calibration_method for label, target in result.bundle.targets.items()
            },
            "best_iterations": {
                label: target.best_iteration for label, target in result.bundle.targets.items()
            },
        },
        seed=seed,
        train_period=f"~{result.bundle.split_dates['calibration_end']}",
        valid_period=f"{SPLIT_BOUNDS['valid'][0]}~{SPLIT_BOUNDS['valid'][1]}",
        test_period="",
        metrics=flat_metrics,
        notes=(f"M4 LightGBM win/top2/top3; profile={profile}; artifact={model_path}; test 미평가"),
    )
    record_run(run)

    print(f"M4 LightGBM 학습 완료: run_id={run_id}")
    print(f"artifact: {model_path}")
    print(f"valid predictions: {predictions_path}")
    print(f"report: {report_path}")
    print("target  calibration  best_iter  log_loss  AUC     ECE")
    for label, target in result.bundle.targets.items():
        metrics = result.valid_metrics[label]
        print(
            f"{label:<7} {target.calibration_method:<12} {target.best_iteration:<10} "
            f"{metrics['log_loss']:.4f}    {metrics.get('auc', float('nan')):.4f}  "
            f"{metrics['ece']:.4f}"
        )
    print("test split은 평가하지 않았습니다.")
    return 0


def run_walk_forward_command(
    version: str,
    as_of_policy: str,
    dataset_dir: str,
    *,
    years: list[int],
    output_dir: str = "data/experiments/walk_forward",
    report_dir: str = "data/experiments/reports",
    seed: int = 42,
    calibration: str = "sigmoid",
    profile: str = "ability_v2_core",
    model_kind: str = "binary",
    relevance_mode: str = "finish_order",
    margin_performance: bool = False,
) -> int:
    import polars as pl

    from horse_racing.analysis.experiments import ModelRun, new_run_id, record_run
    from horse_racing.analysis.lightgbm_model import ModelInputError
    from horse_racing.analysis.model_profiles import ModelProfileError, select_profile_features
    from horse_racing.analysis.walk_forward import (
        render_walk_forward_report,
        run_lightgbm_walk_forward,
        run_racefit_walk_forward,
        run_ranking_walk_forward,
        run_segment_walk_forward,
        run_two_stage_ranking_walk_forward,
        run_two_stage_walk_forward,
    )

    dataset_root = Path(dataset_dir) / version / as_of_policy
    dataset_path = dataset_root / "dataset.parquet"
    manifest_path = dataset_root / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"데이터셋 또는 manifest 없음: {dataset_root}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    try:
        selected_features = select_profile_features(
            list(manifest.get("feature_names") or []),
            profile,
        )
        frame = pl.read_parquet(dataset_path)
        if model_kind == "racefit":
            result = run_racefit_walk_forward(
                frame,
                feature_names=selected_features,
                dataset_version=version,
                as_of_policy=as_of_policy,
                years=years,
                seed=seed,
            )
        elif model_kind in {"ranking", "full_ranking", "top5_ranking"}:
            result = run_ranking_walk_forward(
                frame,
                feature_names=selected_features,
                dataset_version=version,
                as_of_policy=as_of_policy,
                years=years,
                seed=seed,
                calibration_objective=(
                    "full_top5"
                    if model_kind == "top5_ranking"
                    else "full_top3"
                    if model_kind == "full_ranking"
                    else "winner"
                ),
                relevance_depth=5 if model_kind == "top5_ranking" else 3,
                relevance_mode=relevance_mode,
                margin_performance=margin_performance,
            )
        elif model_kind == "pace":
            result = run_two_stage_walk_forward(
                frame,
                feature_names=selected_features,
                dataset_version=version,
                as_of_policy=as_of_policy,
                years=years,
                seed=seed,
            )
        elif model_kind == "pace_ranking":
            result = run_two_stage_ranking_walk_forward(
                frame,
                feature_names=selected_features,
                dataset_version=version,
                as_of_policy=as_of_policy,
                years=years,
                seed=seed,
            )
        elif model_kind == "segment":
            result = run_segment_walk_forward(
                frame,
                feature_names=selected_features,
                dataset_version=version,
                as_of_policy=as_of_policy,
                years=years,
                seed=seed,
            )
        else:
            result = run_lightgbm_walk_forward(
                frame,
                feature_names=selected_features,
                dataset_version=version,
                as_of_policy=as_of_policy,
                years=years,
                seed=seed,
                calibration=calibration,
            )
    except (ModelInputError, ModelProfileError, ValueError) as exc:
        print(f"walk-forward 실패: {exc}", file=sys.stderr)
        return 1

    run_id = new_run_id()
    artifact_dir = Path(output_dir) / run_id
    predictions_path = artifact_dir / "predictions.parquet"
    predictions_path.parent.mkdir(parents=True, exist_ok=True)
    result.predictions.write_parquet(predictions_path)
    comparison_path: Path | None = None
    if model_kind == "top5_ranking":
        from horse_racing.analysis.ranking_model import rank_comparison_frame

        comparison_path = artifact_dir / "rank_comparison.parquet"
        rank_comparison_frame(frame, result.predictions, max_rank=5).write_parquet(comparison_path)
    report = render_walk_forward_report(
        result,
        dataset_version=version,
        as_of_policy=as_of_policy,
        profile=profile,
        seed=seed,
        model_name=(
            "RaceFit V1 scenario-mixture ranking"
            if model_kind == "racefit"
            else "Top5 Plackett-Luce LambdaRank"
            if model_kind == "top5_ranking"
            else "Full Plackett-Luce LambdaRank"
            if model_kind == "full_ranking"
            else "LightGBM LambdaRank"
            if model_kind == "ranking"
            else "Two-stage learned pace + LambdaRank"
            if model_kind == "pace_ranking"
            else "Two-stage predicted pace + LightGBM"
            if model_kind == "pace"
            else "Common binary/ranking + Jeju/long correction"
            if model_kind == "segment"
            else "LightGBM binary"
        ),
    )
    report_path = Path(report_dir) / (
        f"walk_forward_{model_kind}_{version}_{as_of_policy}_{profile}_{run_id}.md"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    aggregate = result.aggregate_metrics
    metrics: dict[str, float | None] = {
        "walk_forward_log_loss": aggregate["log_loss"],
        "walk_forward_auc": aggregate.get("auc"),
        "walk_forward_ece": aggregate["ece"],
        "walk_forward_top1_hit_rate": aggregate["top1_hit_rate"],
        "walk_forward_top3_inclusion_rate": aggregate["top3_inclusion_rate"],
    }
    for target, target_values in result.aggregate_target_metrics.items():
        metrics[f"walk_forward_{target}_log_loss"] = target_values["log_loss"]
        metrics[f"walk_forward_{target}_auc"] = target_values.get("auc")
        metrics[f"walk_forward_{target}_ece"] = target_values["ece"]
    for metric_name, metric_value in result.aggregate_rank_metrics.items():
        metrics[f"walk_forward_{metric_name}"] = metric_value
    for fold in result.folds:
        metrics[f"year_{fold.year}_log_loss"] = fold.metrics["log_loss"]
        metrics[f"year_{fold.year}_auc"] = fold.metrics.get("auc")
        metrics[f"year_{fold.year}_top1"] = fold.metrics["top1_hit_rate"]
        metrics[f"year_{fold.year}_top3"] = fold.metrics["top3_inclusion_rate"]
    run = ModelRun(
        run_id=run_id,
        dataset_version=f"{version}/{as_of_policy}",
        dataset_manifest={
            key: manifest.get(key)
            for key in (
                "version",
                "as_of_policy",
                "row_count",
                "race_count",
                "feature_hash",
                "meet_codes",
            )
        },
        feature_names=selected_features,
        model_type=f"lightgbm_{model_kind}_walk_forward",
        hyperparameters={
            "years": sorted(set(years)),
            "profile": profile,
            "calibration": calibration,
            "model_kind": model_kind,
            "predictions_path": str(predictions_path),
            "comparison_path": str(comparison_path) if comparison_path else None,
            "report_path": str(report_path),
        },
        seed=seed,
        train_period="expanding through prior calendar year",
        valid_period=",".join(str(year) for year in sorted(set(years))),
        test_period="",
        metrics=metrics,
        notes="연도별 expanding-window 진단; 신규 미래 holdout 미사용",
    )
    record_run(run)

    print(f"walk-forward 완료: run_id={run_id}")
    for fold in result.folds:
        values = fold.metrics
        print(
            f"{fold.year}: races={values['n_races']:.0f}, "
            f"log_loss={values['log_loss']:.4f}, AUC={values.get('auc', float('nan')):.4f}, "
            f"Top1={values['top1_hit_rate']:.2%}, Top3={values['top3_inclusion_rate']:.2%}"
        )
    print(
        f"aggregate: log_loss={aggregate['log_loss']:.4f}, "
        f"AUC={aggregate.get('auc', float('nan')):.4f}, "
        f"Top1={aggregate['top1_hit_rate']:.2%}, "
        f"Top3={aggregate['top3_inclusion_rate']:.2%}"
    )
    print(f"predictions: {predictions_path}")
    if comparison_path is not None:
        print(f"actual comparison: {comparison_path}")
    print(f"report: {report_path}")
    return 0


def train_ranking_command(
    version: str,
    as_of_policy: str,
    dataset_dir: str,
    *,
    output_dir: str = "data/experiments/models",
    report_dir: str = "data/experiments/reports",
    seed: int = 42,
    profile: str = "ability_v2_core",
    calibration_objective: str = "full_top3",
    relevance_depth: int = 3,
    relevance_mode: str = "finish_order",
    margin_performance: bool = False,
    regularization: str = "default",
) -> int:
    import polars as pl

    from horse_racing.analysis.baselines import assign_split
    from horse_racing.analysis.experiments import ModelRun, new_run_id, record_run
    from horse_racing.analysis.lightgbm_model import ModelInputError
    from horse_racing.analysis.model_profiles import (
        JOCKEY_RATE_FEATURES,
        ModelProfileError,
        select_profile_features,
    )
    from horse_racing.analysis.ranking_model import (
        rank_comparison_frame,
        render_ranking_report,
        save_ranking_bundle,
        train_ranking_model,
    )

    dataset_root = Path(dataset_dir) / version / as_of_policy
    dataset_path = dataset_root / "dataset.parquet"
    manifest_path = dataset_root / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"데이터셋 또는 manifest 없음: {dataset_root}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    regularization_presets = {
        "default": {},
        "jeju_moderate": {
            "num_leaves": 15,
            "min_child_samples": 120,
            "colsample_bytree": 0.75,
            "reg_lambda": 3.0,
        },
        "jeju_strong": {
            "num_leaves": 7,
            "min_child_samples": 160,
            "colsample_bytree": 0.7,
            "reg_lambda": 5.0,
        },
        "jeju_jockey_soft": {},
    }
    try:
        selected_features = select_profile_features(
            list(manifest.get("feature_names") or []), profile
        )
        regularization_params = dict(regularization_presets[regularization])
        if regularization == "jeju_jockey_soft":
            # LightGBM feature_contri는 각 feature의 split gain 상한을 곱한다.
            # 기수 승률 정보는 보존하되 다른 능력·전개 변수보다 독점적으로
            # 선택되지 않도록 절반의 gain만 인정한다.
            regularization_params["feature_contri"] = [
                0.5 if name in JOCKEY_RATE_FEATURES else 1.0
                for name in selected_features
            ]
        frame = pl.read_parquet(dataset_path)
        result = train_ranking_model(
            frame,
            feature_names=selected_features,
            dataset_version=version,
            as_of_policy=as_of_policy,
            seed=seed,
            calibration_objective=calibration_objective,
            relevance_depth=relevance_depth,
            relevance_mode=relevance_mode,
            margin_performance=margin_performance,
            hyperparameters=regularization_params,
        )
    except (ModelInputError, ModelProfileError) as exc:
        print(f"Ranking 학습 실패: {exc}", file=sys.stderr)
        return 1

    run_id = new_run_id()
    artifact_dir = Path(output_dir) / run_id
    model_path = artifact_dir / "model.pkl"
    predictions_path = artifact_dir / "predictions_valid.parquet"
    comparison_path = artifact_dir / "rank_comparison_valid.parquet"
    save_ranking_bundle(result.bundle, model_path)
    result.valid_predictions.write_parquet(predictions_path)
    valid = assign_split(frame).filter(pl.col("split") == "valid").drop("split")
    rank_comparison_frame(
        valid,
        result.valid_predictions,
        max_rank=result.bundle.max_rank,
    ).write_parquet(comparison_path)
    report_path = Path(report_dir) / f"ranking_{version}_{as_of_policy}_{run_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_ranking_report(
            result.bundle,
            result.valid_metrics,
            run_id=run_id,
            target_metrics=result.valid_target_metrics,
            ordered_top3_nll=result.ordered_top3_nll,
            ordered_topk_nll=result.ordered_topk_nll,
            topk_rps=result.topk_rps,
            actual_rank_nll=result.actual_rank_nll,
        ),
        encoding="utf-8",
    )
    metrics = result.valid_metrics
    record_run(
        ModelRun(
            run_id=run_id,
            dataset_version=f"{version}/{as_of_policy}",
            dataset_manifest={
                key: manifest.get(key)
                for key in (
                    "version",
                    "as_of_policy",
                    "row_count",
                    "race_count",
                    "feature_hash",
                    "meet_codes",
                )
            },
            feature_names=selected_features,
            model_type="lightgbm_ranking_bundle",
            hyperparameters={
                **result.bundle.hyperparameters,
                "artifact_path": str(model_path),
                "model_profile": profile,
                "regularization_preset": regularization,
                "best_iteration": result.bundle.best_iteration,
                "softmax_beta": result.bundle.softmax_beta,
                "calibration_objective": result.bundle.calibration_objective,
                "relevance_depth": result.bundle.relevance_depth,
                "relevance_mode": result.bundle.relevance_mode,
                "margin_performance": result.bundle.performance_estimator is not None,
                "performance_weight": result.bundle.performance_weight,
                "performance_scale": result.bundle.performance_scale,
                "performance_best_iteration": result.bundle.performance_best_iteration,
                "comparison_path": str(comparison_path),
            },
            seed=seed,
            train_period=f"~{result.bundle.split_dates['calibration_end']}",
            valid_period="2026-03-01~2026-05-31",
            test_period="",
            metrics={
                "valid_log_loss": metrics["log_loss"],
                "valid_brier": metrics["brier"],
                "valid_auc": metrics.get("auc"),
                "valid_ece": metrics["ece"],
                "valid_top1_hit_rate": metrics["top1_hit_rate"],
                "valid_top3_inclusion_rate": metrics["top3_inclusion_rate"],
                **{
                    f"valid_{target}_{metric_name}": metric_value
                    for target, target_values in result.valid_target_metrics.items()
                    for metric_name, metric_value in target_values.items()
                    if metric_name in {"log_loss", "brier", "auc", "ece"}
                },
                "valid_ordered_topk_nll": result.ordered_topk_nll,
                "valid_topk_rps": result.topk_rps,
                "valid_actual_rank_nll": result.actual_rank_nll,
            },
            notes=(
                "LightGBM LambdaRank; calibration block "
                f"{result.bundle.calibration_objective}; test 미평가"
            ),
        )
    )
    print(f"Ranking 학습 완료: run_id={run_id}")
    print(
        f"win: log_loss={metrics['log_loss']:.4f}, AUC={metrics.get('auc', float('nan')):.4f}, "
        f"Top1={metrics['top1_hit_rate']:.2%}, Top3={metrics['top3_inclusion_rate']:.2%}"
    )
    for target in ("top2", "top3", "top4", "top5"):
        target_metrics = result.valid_target_metrics.get(target)
        if target_metrics is not None:
            print(
                f"{target}: log_loss={target_metrics['log_loss']:.4f}, "
                f"AUC={target_metrics.get('auc', float('nan')):.4f}, "
                f"ECE={target_metrics['ece']:.4f}"
            )
    if result.ordered_top3_nll is not None:
        print(f"ordered top3 race NLL={result.ordered_top3_nll:.4f}")
    if result.bundle.max_rank > 3 and result.ordered_topk_nll is not None:
        print(f"ordered top{result.bundle.max_rank} race NLL={result.ordered_topk_nll:.4f}")
        print(
            f"top{result.bundle.max_rank} RPS={result.topk_rps:.4f}, "
            f"actual-rank bucket NLL={result.actual_rank_nll:.4f}"
        )
    print(f"artifact: {model_path}")
    print(f"actual comparison: {comparison_path}")
    print(f"report: {report_path}")
    print("test split은 평가하지 않았습니다.")
    return 0


def train_racefit_command(
    version: str,
    as_of_policy: str,
    dataset_dir: str,
    *,
    output_dir: str = "data/experiments/models",
    report_dir: str = "data/experiments/reports",
    seed: int = 42,
    profile: str = "ability_v2_core",
) -> int:
    import numpy as np
    import polars as pl

    from horse_racing.analysis.experiments import ModelRun, new_run_id, record_run
    from horse_racing.analysis.lightgbm_model import ModelInputError
    from horse_racing.analysis.model_profiles import ModelProfileError, select_profile_features
    from horse_racing.analysis.racefit_model import (
        render_racefit_report,
        save_racefit_bundle,
        train_racefit_model,
    )

    dataset_root = Path(dataset_dir) / version / as_of_policy
    dataset_path = dataset_root / "dataset.parquet"
    manifest_path = dataset_root / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"데이터셋 또는 manifest 없음: {dataset_root}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not str(manifest.get("feature_set", "")).startswith("racefit_"):
        print("RaceFit 학습에는 racefit_* feature_set 데이터셋이 필요합니다.", file=sys.stderr)
        return 1
    try:
        selected_features = select_profile_features(
            list(manifest.get("feature_names") or []), profile
        )
        result = train_racefit_model(
            pl.read_parquet(dataset_path),
            feature_names=selected_features,
            dataset_version=version,
            as_of_policy=as_of_policy,
            seed=seed,
        )
    except (ModelInputError, ModelProfileError, ValueError) as exc:
        print(f"RaceFit 학습 실패: {exc}", file=sys.stderr)
        return 1

    run_id = new_run_id()
    artifact_dir = Path(output_dir) / run_id
    model_path = artifact_dir / "model.pkl"
    predictions_path = artifact_dir / "predictions_valid.parquet"
    save_racefit_bundle(result.bundle, model_path)
    result.valid_predictions.write_parquet(predictions_path)
    report_path = Path(report_dir) / f"racefit_{version}_{as_of_policy}_{run_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_racefit_report(result, run_id=run_id), encoding="utf-8")
    metrics = result.valid_target_metrics
    recorded_metrics: dict[str, float | None] = {
        "valid_ordered_top3_nll": result.ordered_top3_nll,
    }
    for target, values in metrics.items():
        recorded_metrics[f"valid_{target}_log_loss"] = values["log_loss"]
        recorded_metrics[f"valid_{target}_brier"] = values["brier"]
        recorded_metrics[f"valid_{target}_auc"] = values.get("auc")
        recorded_metrics[f"valid_{target}_ece"] = values["ece"]
    recorded_metrics["valid_top1_hit_rate"] = result.valid_metrics["top1_hit_rate"]
    recorded_metrics["valid_top3_inclusion_rate"] = result.valid_metrics["top3_inclusion_rate"]
    record_run(
        ModelRun(
            run_id=run_id,
            dataset_version=f"{version}/{as_of_policy}",
            dataset_manifest={
                key: manifest.get(key)
                for key in (
                    "version",
                    "as_of_policy",
                    "row_count",
                    "race_count",
                    "feature_hash",
                    "feature_set",
                )
            },
            feature_names=selected_features,
            model_type="racefit_scenario_bundle",
            hyperparameters={
                **result.bundle.base_bundle.hyperparameters,
                "artifact_path": str(model_path),
                "model_profile": profile,
                "best_iteration": result.bundle.base_bundle.best_iteration,
                "scenario_beta": float(np.exp(result.bundle.log_beta)),
                "objective_weights": result.bundle.objective_weights,
                "l2_penalty": result.bundle.l2_penalty,
                "calibration_metrics": result.bundle.calibration_metrics,
            },
            seed=seed,
            train_period=f"~{result.bundle.split_dates['calibration_end']}",
            valid_period="2026-03-01~2026-05-31",
            test_period="",
            metrics=recorded_metrics,
            notes="RaceFit V1 energy/state + three-pace scenario mixture PL; test 미평가",
        )
    )
    win = result.valid_metrics
    print(f"RaceFit 학습 완료: run_id={run_id}")
    print(
        f"win: log_loss={win['log_loss']:.4f}, AUC={win.get('auc', float('nan')):.4f}, "
        f"Top1={win['top1_hit_rate']:.2%}, Top3={win['top3_inclusion_rate']:.2%}"
    )
    print(
        f"top2 LL={metrics['top2']['log_loss']:.4f}, "
        f"top3 LL={metrics['top3']['log_loss']:.4f}, "
        f"ordered NLL={result.ordered_top3_nll:.4f}"
    )
    print(f"artifact: {model_path}")
    print(f"report: {report_path}")
    print("test split은 평가하지 않았습니다.")
    return 0


def train_catboost_command(
    version: str,
    as_of_policy: str,
    dataset_dir: str,
    *,
    output_dir: str = "data/experiments/models",
    report_dir: str = "data/experiments/reports",
    seed: int = 42,
    calibration: str = "auto",
    profile: str = "legacy_all",
) -> int:
    import polars as pl

    from horse_racing.analysis.baselines import SPLIT_BOUNDS
    from horse_racing.analysis.catboost_model import (
        render_catboost_report,
        save_catboost_bundle,
        train_catboost_models,
    )
    from horse_racing.analysis.experiments import ModelRun, new_run_id, record_run
    from horse_racing.analysis.lightgbm_model import ModelInputError
    from horse_racing.analysis.model_profiles import (
        PROFILES,
        ModelProfileError,
        select_profile_features,
    )

    dataset_root = Path(dataset_dir) / version / as_of_policy
    dataset_path = dataset_root / "dataset.parquet"
    manifest_path = dataset_root / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"데이터셋 또는 manifest 없음: {dataset_root}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    feature_names = list(manifest.get("feature_names") or [])
    if not feature_names:
        print("manifest에 feature_names가 없습니다.", file=sys.stderr)
        return 1
    try:
        feature_names = select_profile_features(feature_names, profile)
    except ModelProfileError as exc:
        print(f"모델 프로필 적용 실패: {exc}", file=sys.stderr)
        return 1

    frame = pl.read_parquet(dataset_path)
    try:
        result = train_catboost_models(
            frame,
            feature_names=feature_names,
            dataset_version=version,
            as_of_policy=as_of_policy,
            seed=seed,
            calibration=calibration,
        )
    except ModelInputError as exc:
        print(f"CatBoost 학습 실패: {exc}", file=sys.stderr)
        return 1

    run_id = new_run_id()
    artifact_dir = Path(output_dir) / run_id
    model_path = artifact_dir / "model.pkl"
    predictions_path = artifact_dir / "predictions_valid.parquet"
    save_catboost_bundle(result.bundle, model_path)
    result.valid_predictions.write_parquet(predictions_path)
    report = render_catboost_report(result.bundle, result.valid_metrics, run_id=run_id)
    report_path = Path(report_dir) / f"catboost_{version}_{as_of_policy}_{run_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    primary = result.valid_metrics["win"]
    flat_metrics = {
        "valid_log_loss": primary["log_loss"],
        "valid_brier": primary["brier"],
        "valid_auc": primary.get("auc", float("nan")),
        "valid_ece": primary["ece"],
        "valid_top1_hit_rate": primary["top1_hit_rate"],
        "valid_top3_inclusion_rate": primary["top3_inclusion_rate"],
    }
    for label, values in result.valid_metrics.items():
        for metric_name in ("log_loss", "brier", "auc", "ece"):
            if metric_name in values:
                flat_metrics[f"valid_{label}_{metric_name}"] = values[metric_name]
    manifest_slim = {
        key: manifest.get(key)
        for key in ("version", "as_of_policy", "row_count", "race_count", "feature_hash")
    }
    run = ModelRun(
        run_id=run_id,
        dataset_version=f"{version}/{as_of_policy}",
        dataset_manifest=manifest_slim,
        feature_names=feature_names,
        model_type="catboost_binary_bundle",
        hyperparameters={
            **result.bundle.hyperparameters,
            "model_profile": profile,
            "model_profile_description": PROFILES[profile].description,
            "artifact_path": str(model_path),
            "calibration_requested": calibration,
            "calibration_selected": {
                label: target.calibration_method for label, target in result.bundle.targets.items()
            },
            "best_iterations": {
                label: target.best_iteration for label, target in result.bundle.targets.items()
            },
        },
        seed=seed,
        train_period=f"~{result.bundle.split_dates['calibration_end']}",
        valid_period=f"{SPLIT_BOUNDS['valid'][0]}~{SPLIT_BOUNDS['valid'][1]}",
        test_period="",
        metrics=flat_metrics,
        notes=(f"M4 CatBoost win/top2/top3; profile={profile}; artifact={model_path}; test 미평가"),
    )
    record_run(run)
    print(f"M4 CatBoost 학습 완료: run_id={run_id}")
    print(f"artifact: {model_path}")
    print(f"valid predictions: {predictions_path}")
    print(f"report: {report_path}")
    print("target  calibration  best_iter  log_loss  AUC     ECE")
    for label, target in result.bundle.targets.items():
        metrics = result.valid_metrics[label]
        print(
            f"{label:<7} {target.calibration_method:<12} {target.best_iteration:<10} "
            f"{metrics['log_loss']:.4f}    {metrics.get('auc', float('nan')):.4f}  "
            f"{metrics['ece']:.4f}"
        )
    print("test split은 평가하지 않았습니다.")
    return 0


def run_ablation_command(
    version: str,
    as_of_policy: str,
    dataset_dir: str,
    *,
    report_dir: str = "data/experiments/reports",
    seed: int = 42,
    profile: str = "legacy_all",
) -> int:
    import polars as pl

    from horse_racing.analysis.experiments import ModelRun, new_run_id, record_run
    from horse_racing.analysis.model_profiles import (
        ModelProfileError,
        select_profile_features,
    )
    from horse_racing.analysis.model_stability import (
        render_ablation_report,
        run_lightgbm_ablation,
    )

    dataset_root = Path(dataset_dir) / version / as_of_policy
    dataset_path = dataset_root / "dataset.parquet"
    manifest_path = dataset_root / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"데이터셋 또는 manifest 없음: {dataset_root}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    feature_names = list(manifest.get("feature_names") or [])
    try:
        feature_names = select_profile_features(feature_names, profile)
    except ModelProfileError as exc:
        print(f"모델 프로필 적용 실패: {exc}", file=sys.stderr)
        return 1
    result = run_lightgbm_ablation(
        pl.read_parquet(dataset_path),
        feature_names=feature_names,
        dataset_version=version,
        as_of_policy=as_of_policy,
        seed=seed,
    )
    report = render_ablation_report(
        result,
        dataset_version=version,
        as_of_policy=as_of_policy,
        seed=seed,
    )
    report_path = Path(report_dir) / f"ablation_{version}_{as_of_policy}_{profile}_seed{seed}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    run_id = new_run_id()
    metrics = {
        "valid_log_loss_full": result.baseline_log_loss,
        "valid_auc_full": result.baseline_auc,
        "valid_ece_full": result.baseline_ece,
    }
    for index, row in enumerate(result.rows):
        metrics[f"ablation_{index}_delta_log_loss"] = row.delta_log_loss
    run = ModelRun(
        run_id=run_id,
        dataset_version=f"{version}/{as_of_policy}",
        dataset_manifest={
            key: manifest.get(key)
            for key in (
                "version",
                "as_of_policy",
                "row_count",
                "race_count",
                "feature_hash",
                "meet_codes",
            )
        },
        feature_names=feature_names,
        model_type="lightgbm_feature_group_ablation",
        hyperparameters={
            "seed": seed,
            "model_profile": profile,
            "groups": [
                {
                    "name": row.group,
                    "feature_count": row.feature_count,
                    "delta_log_loss": row.delta_log_loss,
                }
                for row in result.rows
            ],
        },
        seed=seed,
        train_period="~2026-02-28",
        valid_period="2026-03-01~2026-05-31",
        test_period="",
        metrics=metrics,
        notes=(
            f"M4 win feature-group ablation; profile={profile}; report={report_path}; test 미평가"
        ),
    )
    record_run(run)
    print(f"Ablation 완료: run_id={run_id}")
    print(f"전체 log loss: {result.baseline_log_loss:.4f}")
    for row in result.rows:
        print(
            f"{row.group}: without={row.valid_log_loss:.4f}, "
            f"delta={row.delta_log_loss:+.4f} ({row.feature_count} features)"
        )
    print(f"report: {report_path}")
    print("test split은 평가하지 않았습니다.")
    return 0


def build_ensemble_command(
    run_ids: list[str],
    dataset_dir: str,
    *,
    output_dir: str = "data/experiments/models",
    report_dir: str = "data/experiments/reports",
    allow_cross_dataset: bool = False,
    target_member_weights: dict[str, list[float]] | None = None,
    reference_version: str | None = None,
    reference_as_of: str | None = None,
) -> int:
    import polars as pl

    from horse_racing.analysis.experiments import ModelRun, get_run, new_run_id, record_run
    from horse_racing.analysis.model_ensemble import (
        ProbabilityEnsembleBundle,
        evaluate_ensemble_bundle,
        render_ensemble_report,
        save_ensemble_bundle,
    )

    if len(run_ids) < 2:
        print("ensemble에는 2개 이상의 run_id가 필요합니다.", file=sys.stderr)
        return 2
    members = []
    for member_id in run_ids:
        run = get_run(member_id)
        if run is None:
            print(f"알 수 없는 run_id: {member_id}", file=sys.stderr)
            return 1
        members.append(run)
    model_types = {run.model_type for run in members}
    versions = {run.dataset_version for run in members}
    feature_hashes = {run.feature_hash for run in members}
    cross_dataset = len(versions) != 1 or len(feature_hashes) != 1
    if cross_dataset and not allow_cross_dataset:
        print("ensemble member의 데이터셋·feature가 일치하지 않습니다.", file=sys.stderr)
        return 1
    supported_types = {
        "lightgbm_binary_bundle",
        "catboost_binary_bundle",
        "probability_ensemble",
        "lightgbm_ranking_bundle",
    }
    if not model_types <= supported_types:
        unsupported = sorted(model_types - supported_types)
        print(f"ensemble을 지원하지 않는 model_type: {', '.join(unsupported)}", file=sys.stderr)
        return 1
    member_type = members[0].model_type if len(model_types) == 1 else "mixed"
    member_paths = [str(run.hyperparameters.get("artifact_path", "")) for run in members]
    if any(not item for item in member_paths):
        print("artifact 경로가 없는 member가 있습니다.", file=sys.stderr)
        return 1
    member_version, member_as_of_policy = members[0].dataset_version.split("/", maxsplit=1)
    version = reference_version or member_version
    as_of_policy = reference_as_of or member_as_of_policy
    as_of_order = {"day_before_18": 0, "start_minus_30m": 1}
    if cross_dataset:
        reference_order = as_of_order.get(as_of_policy)
        if reference_order is None:
            print(f"지원하지 않는 기준 as-of 정책: {as_of_policy}", file=sys.stderr)
            return 1
        for member in members[1:]:
            try:
                _, member_as_of = member.dataset_version.split("/", maxsplit=1)
            except ValueError:
                print(f"지원하지 않는 dataset_version: {member.dataset_version}", file=sys.stderr)
                return 1
            member_order = as_of_order.get(member_as_of)
            if member_order is None or member_order > reference_order:
                print(
                    "기준 데이터셋보다 늦은 정보시점의 member는 결합할 수 없습니다: "
                    f"reference={as_of_policy}, member={member_as_of}",
                    file=sys.stderr,
                )
                return 1
    dataset_path = Path(dataset_dir) / version / as_of_policy / "dataset.parquet"
    manifest_path = Path(dataset_dir) / version / as_of_policy / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"기준 데이터셋 또는 manifest 없음: {dataset_path.parent}", file=sys.stderr)
        return 1
    frame = pl.read_parquet(dataset_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required_features = set().union(*(set(run.feature_names) for run in members))
    missing_features = sorted(required_features - set(frame.columns))
    if missing_features:
        print(
            f"기준 데이터셋에 ensemble member feature가 없습니다: {missing_features[:10]}",
            file=sys.stderr,
        )
        return 1
    reference_features = list(manifest.get("feature_names") or [])
    ensemble_features = [name for name in reference_features if name in required_features]
    if set(ensemble_features) != required_features:
        print("기준 manifest의 feature 순서로 ensemble 계약을 만들 수 없습니다.", file=sys.stderr)
        return 1
    targets = ["win", "top2", "top3"]
    if target_member_weights and "top5" in target_member_weights:
        if "top4" not in target_member_weights:
            print("Top5 ensemble에는 --top4-weights도 필요합니다.", file=sys.stderr)
            return 2
        targets.extend(["top4", "top5"])
    bundle = ProbabilityEnsembleBundle(
        dataset_version=version,
        as_of_policy=as_of_policy,
        member_type=member_type,
        member_run_ids=run_ids,
        member_paths=member_paths,
        feature_names=ensemble_features,
        targets=targets,
        member_types=[run.model_type for run in members],
        target_member_weights=target_member_weights or {},
    )
    metrics, predictions = evaluate_ensemble_bundle(bundle, frame, split="valid")
    ensemble_run_id = new_run_id()
    artifact_dir = Path(output_dir) / ensemble_run_id
    model_path = artifact_dir / "model.pkl"
    predictions_path = artifact_dir / "predictions_valid.parquet"
    save_ensemble_bundle(bundle, model_path)
    predictions.write_parquet(predictions_path)
    report = render_ensemble_report(bundle, metrics, run_id=ensemble_run_id)
    report_path = Path(report_dir) / f"ensemble_{version}_{as_of_policy}_{ensemble_run_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    primary = metrics["win"]
    flat_metrics = {
        "valid_log_loss": primary["log_loss"],
        "valid_brier": primary["brier"],
        "valid_auc": primary.get("auc", float("nan")),
        "valid_ece": primary["ece"],
        "valid_top1_hit_rate": primary["top1_hit_rate"],
        "valid_top3_inclusion_rate": primary["top3_inclusion_rate"],
    }
    for label, values in metrics.items():
        for metric_name in ("log_loss", "brier", "auc", "ece"):
            if metric_name in values:
                flat_metrics[f"valid_{label}_{metric_name}"] = values[metric_name]
    run = ModelRun(
        run_id=ensemble_run_id,
        dataset_version=f"{version}/{as_of_policy}",
        dataset_manifest={
            key: manifest.get(key)
            for key in (
                "version",
                "as_of_policy",
                "row_count",
                "race_count",
                "feature_hash",
                "meet_codes",
            )
        },
        feature_names=ensemble_features,
        model_type="probability_ensemble",
        hyperparameters={
            "artifact_path": str(model_path),
            "member_type": member_type,
            "member_types": [run.model_type for run in members],
            "member_run_ids": run_ids,
            "member_dataset_versions": [run.dataset_version for run in members],
            "cross_dataset": cross_dataset,
            "target_member_weights": target_member_weights or {},
            "reference_dataset_version": f"{version}/{as_of_policy}",
        },
        seed=0,
        train_period=members[0].train_period,
        valid_period=members[0].valid_period,
        test_period="",
        metrics=flat_metrics,
        notes=(
            f"M4 probability mean ensemble; cross_dataset={cross_dataset}; "
            f"artifact={model_path}; test 미평가"
        ),
    )
    record_run(run)
    print(f"확률 평균 ensemble 완료: run_id={ensemble_run_id}")
    print(f"members: {', '.join(run_ids)}")
    for label, values in metrics.items():
        print(
            f"{label}: log_loss={values['log_loss']:.4f}, "
            f"AUC={values.get('auc', float('nan')):.4f}, ECE={values['ece']:.4f}"
        )
    print(f"artifact: {model_path}")
    print(f"report: {report_path}")
    print("test split은 평가하지 않았습니다.")
    return 0


def evaluate_model_command(
    run_id: str,
    dataset_dir: str,
    *,
    include_test: bool = False,
    report_dir: str = "data/experiments/reports",
) -> int:
    import polars as pl

    from horse_racing.analysis.experiments import get_run
    from horse_racing.analysis.lightgbm_model import ModelInputError
    from horse_racing.analysis.model_stability import (
        evaluate_win_segments,
        render_segment_report,
    )

    run = get_run(run_id)
    if run is None:
        print(f"알 수 없는 run_id: {run_id}", file=sys.stderr)
        return 1
    artifact_path = run.hyperparameters.get("artifact_path")
    if not artifact_path:
        print(f"run에 모델 artifact 경로가 없습니다: {run_id}", file=sys.stderr)
        return 1
    try:
        version, as_of_policy = run.dataset_version.split("/", maxsplit=1)
    except ValueError:
        print(f"지원하지 않는 dataset_version: {run.dataset_version}", file=sys.stderr)
        return 1
    dataset_path = Path(dataset_dir) / version / as_of_policy / "dataset.parquet"
    if not dataset_path.exists():
        print(f"데이터셋 없음: {dataset_path}", file=sys.stderr)
        return 1

    split = "test" if include_test else "valid"
    if include_test:
        print("경고: test split 평가는 Gate G1 1회 판정에 해당합니다.", file=sys.stderr)
    frame = pl.read_parquet(dataset_path)
    try:
        if run.model_type == "catboost_binary_bundle":
            from horse_racing.analysis.catboost_model import (
                evaluate_catboost_bundle,
                load_catboost_bundle,
                render_catboost_report,
            )

            bundle = load_catboost_bundle(Path(str(artifact_path)))
            metrics, predictions = evaluate_catboost_bundle(bundle, frame, split=split)
            report = render_catboost_report(bundle, metrics, run_id=run_id, split=split)
            model_prefix = "catboost"
            model_name = "CatBoost"
        elif run.model_type == "probability_ensemble":
            from horse_racing.analysis.model_ensemble import (
                evaluate_ensemble_bundle,
                load_ensemble_bundle,
                render_ensemble_report,
            )

            bundle = load_ensemble_bundle(Path(str(artifact_path)))
            metrics, predictions = evaluate_ensemble_bundle(bundle, frame, split=split)
            report = render_ensemble_report(bundle, metrics, run_id=run_id, split=split)
            model_prefix = "ensemble"
            model_name = "Probability ensemble"
        else:
            from horse_racing.analysis.lightgbm_model import (
                evaluate_bundle,
                load_bundle,
                render_model_report,
            )

            bundle = load_bundle(Path(str(artifact_path)))
            metrics, predictions = evaluate_bundle(bundle, frame, split=split)
            report = render_model_report(bundle, metrics, run_id=run_id, split=split)
            model_prefix = "lightgbm"
            model_name = "LightGBM"
    except ModelInputError as exc:
        print(f"모델 평가 실패: {exc}", file=sys.stderr)
        return 1

    artifact_dir = Path(str(artifact_path)).parent
    predictions_path = artifact_dir / f"predictions_{split}.parquet"
    predictions.write_parquet(predictions_path)
    report_path = Path(report_dir) / f"{model_prefix}_{version}_{as_of_policy}_{run_id}_{split}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    segments = evaluate_win_segments(frame, predictions, split=split)
    segment_report = render_segment_report(
        segments,
        model_name=f"{model_name} {run_id}",
        split=split,
    )
    segment_path = (
        Path(report_dir) / f"{model_prefix}_{version}_{as_of_policy}_{run_id}_{split}_segments.md"
    )
    segment_path.write_text(segment_report, encoding="utf-8")
    print(f"{split} 평가 완료: {report_path}")
    print(f"구간별 평가: {segment_path}")
    for label, values in metrics.items():
        print(
            f"{label}: log_loss={values['log_loss']:.4f}, "
            f"AUC={values.get('auc', float('nan')):.4f}, ECE={values['ece']:.4f}"
        )
    return 0


def run_g1_gate_command(
    run_id: str,
    dataset_dir: str,
    *,
    report_dir: str = "data/experiments/reports",
    confirm_test: bool = False,
) -> int:
    import polars as pl

    from horse_racing.analysis.baselines import (
        assign_split,
        fit_softmax_beta,
        score_softmax_probabilities,
    )
    from horse_racing.analysis.experiments import (
        ModelRun,
        get_run,
        load_runs,
        new_run_id,
        record_run,
    )
    from horse_racing.analysis.gates import (
        judge_g1,
        render_g1_report,
        segment_rows_by_key,
    )
    from horse_racing.analysis.lightgbm_model import ModelInputError
    from horse_racing.analysis.metrics import evaluate_probabilities
    from horse_racing.analysis.model_stability import evaluate_win_segments

    if not confirm_test:
        print("G1 test를 열려면 --confirm-test가 필요합니다.", file=sys.stderr)
        return 2
    candidate_run = get_run(run_id)
    if candidate_run is None:
        print(f"알 수 없는 후보 run_id: {run_id}", file=sys.stderr)
        return 1
    existing = [
        run
        for run in load_runs()
        if run.model_type == "g1_gate_evaluation"
        and run.hyperparameters.get("candidate_run_id") == run_id
    ]
    if existing:
        print(
            f"이 후보의 G1 test는 이미 평가했습니다: {existing[-1].run_id}",
            file=sys.stderr,
        )
        return 1
    artifact_path = candidate_run.hyperparameters.get("artifact_path")
    if not artifact_path:
        print("후보 run에 artifact 경로가 없습니다.", file=sys.stderr)
        return 1
    version, as_of_policy = candidate_run.dataset_version.split("/", maxsplit=1)
    dataset_path = Path(dataset_dir) / version / as_of_policy / "dataset.parquet"
    manifest_path = Path(dataset_dir) / version / as_of_policy / "manifest.json"
    frame = pl.read_parquet(dataset_path)
    split_frame = assign_split(frame)
    train = split_frame.filter(pl.col("split") == "train").drop("split")
    test = split_frame.filter(pl.col("split") == "test").drop("split")

    beta_b1 = fit_softmax_beta(train, "rating", higher_is_better=True)
    beta_b2 = fit_softmax_beta(train, "form_recent5_pct", higher_is_better=False)
    b1_scored = score_softmax_probabilities(test, "rating", beta=beta_b1, higher_is_better=True)
    b2_scored = score_softmax_probabilities(
        test, "form_recent5_pct", beta=beta_b2, higher_is_better=False
    )
    baseline_b1 = evaluate_probabilities(b1_scored, "probability", label_column="win")
    baseline_b2 = evaluate_probabilities(b2_scored, "probability", label_column="win")

    try:
        if candidate_run.model_type == "probability_ensemble":
            from horse_racing.analysis.model_ensemble import (
                evaluate_ensemble_bundle,
                load_ensemble_bundle,
            )

            bundle = load_ensemble_bundle(Path(str(artifact_path)))
            candidate_metrics, candidate_predictions = evaluate_ensemble_bundle(
                bundle, frame, split="test"
            )
        elif candidate_run.model_type == "catboost_binary_bundle":
            from horse_racing.analysis.catboost_model import (
                evaluate_catboost_bundle,
                load_catboost_bundle,
            )

            bundle = load_catboost_bundle(Path(str(artifact_path)))
            candidate_metrics, candidate_predictions = evaluate_catboost_bundle(
                bundle, frame, split="test"
            )
        else:
            from horse_racing.analysis.lightgbm_model import evaluate_bundle, load_bundle

            bundle = load_bundle(Path(str(artifact_path)))
            candidate_metrics, candidate_predictions = evaluate_bundle(bundle, frame, split="test")
    except ModelInputError as exc:
        print(f"G1 후보 평가 실패: {exc}", file=sys.stderr)
        return 1
    candidate = candidate_metrics["win"]

    b1_predictions = b1_scored.select(
        "race_id", "race_entry_id", pl.col("probability").alias("prob_win")
    )
    b2_predictions = b2_scored.select(
        "race_id", "race_entry_id", pl.col("probability").alias("prob_win")
    )
    meet_candidate = segment_rows_by_key(
        evaluate_win_segments(frame, candidate_predictions, split="test")["경마장"]
    )
    meet_b1 = segment_rows_by_key(
        evaluate_win_segments(frame, b1_predictions, split="test")["경마장"]
    )
    meet_b2 = segment_rows_by_key(
        evaluate_win_segments(frame, b2_predictions, split="test")["경마장"]
    )

    ablation_runs = [
        run
        for run in load_runs()
        if run.model_type == "lightgbm_feature_group_ablation"
        and run.dataset_version == candidate_run.dataset_version
    ]
    ablation_passed = False
    if ablation_runs:
        groups = ablation_runs[-1].hyperparameters.get("groups", [])
        largest_delta = max((float(item["delta_log_loss"]) for item in groups), default=1.0)
        valid_gain = 0.2905104392464778 - candidate_run.metrics["valid_log_loss"]
        ablation_passed = largest_delta < valid_gain * 0.5

    decision = judge_g1(
        candidate=candidate,
        baseline_b1=baseline_b1,
        baseline_b2=baseline_b2,
        meet_candidate=meet_candidate,
        meet_b1=meet_b1,
        ablation_passed=ablation_passed,
    )
    gate_run_id = new_run_id()
    report = render_g1_report(
        candidate_run_id=run_id,
        candidate=candidate,
        baseline_b1=baseline_b1,
        baseline_b2=baseline_b2,
        meet_candidate=meet_candidate,
        meet_b1=meet_b1,
        meet_b2=meet_b2,
        decision=decision,
        beta_b1=beta_b1,
        beta_b2=beta_b2,
    )
    report_path = Path(report_dir) / f"g1_{version}_{as_of_policy}_{gate_run_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    predictions_path = Path(str(artifact_path)).parent / "predictions_test_g1.parquet"
    candidate_predictions.write_parquet(predictions_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metrics = {
        "test_log_loss": candidate["log_loss"],
        "test_brier": candidate["brier"],
        "test_auc": candidate.get("auc", float("nan")),
        "test_ece": candidate["ece"],
        "test_top1_hit_rate": candidate["top1_hit_rate"],
        "test_top3_inclusion_rate": candidate["top3_inclusion_rate"],
        "test_b1_log_loss": baseline_b1["log_loss"],
        "test_b2_log_loss": baseline_b2["log_loss"],
    }
    for meet_code in ("1", "2", "3"):
        metrics[f"test_meet_{meet_code}_log_loss"] = meet_candidate[meet_code]["log_loss"]
    gate_run = ModelRun(
        run_id=gate_run_id,
        dataset_version=candidate_run.dataset_version,
        dataset_manifest={
            key: manifest.get(key)
            for key in ("version", "as_of_policy", "row_count", "race_count", "feature_hash")
        },
        feature_names=candidate_run.feature_names,
        model_type="g1_gate_evaluation",
        hyperparameters={
            "candidate_run_id": run_id,
            "criteria": decision.criteria,
            "passed": decision.passed,
            "beta_b1": beta_b1,
            "beta_b2": beta_b2,
        },
        seed=0,
        train_period=candidate_run.train_period,
        valid_period=candidate_run.valid_period,
        test_period="2026-06-01~",
        metrics=metrics,
        notes=f"Gate G1 {'PASS' if decision.passed else 'FAIL'}; report={report_path}",
    )
    record_run(gate_run)
    print(f"Gate G1 {'PASS' if decision.passed else 'FAIL'}: run_id={gate_run_id}")
    print(
        f"후보 test log_loss={candidate['log_loss']:.4f}, "
        f"B1={baseline_b1['log_loss']:.4f}, B2={baseline_b2['log_loss']:.4f}, "
        f"ECE={candidate['ece']:.4f}"
    )
    for meet_code, meet_name in (("1", "서울"), ("2", "제주"), ("3", "부산경남")):
        print(
            f"{meet_name}: 후보={meet_candidate[meet_code]['log_loss']:.4f}, "
            f"B1={meet_b1[meet_code]['log_loss']:.4f}, "
            f"B2={meet_b2[meet_code]['log_loss']:.4f}"
        )
    print(f"report: {report_path}")
    return 0 if decision.passed else 1


def run_g2_gate_command(
    run_id: str,
    dataset_dir: str,
    *,
    report_dir: str = "data/experiments/reports",
    confirm_test_market: bool = False,
    bootstrap_iterations: int = 1_000,
) -> int:
    import polars as pl

    from horse_racing.analysis.baselines import assign_split, fetch_win_odds
    from horse_racing.analysis.experiments import (
        ModelRun,
        get_run,
        load_runs,
        new_run_id,
        record_run,
    )
    from horse_racing.analysis.market_gate import (
        apply_incremental_logit,
        backtest_win_ev,
        bootstrap_log_loss_improvement,
        evaluate_market_and_mix,
        fit_incremental_logit,
        judge_g2,
        overround_summary,
        prepare_market_comparison,
        render_g2_report,
        select_ev_threshold,
    )

    if not confirm_test_market:
        print("G2 test 시장평가를 열려면 --confirm-test-market이 필요합니다.", file=sys.stderr)
        return 2
    if bootstrap_iterations < 100:
        print("bootstrap은 최소 100회가 필요합니다.", file=sys.stderr)
        return 2
    candidate_run = get_run(run_id)
    if candidate_run is None:
        print(f"알 수 없는 후보 run_id: {run_id}", file=sys.stderr)
        return 1
    all_runs = load_runs()
    g1_runs = [
        run
        for run in all_runs
        if run.model_type == "g1_gate_evaluation"
        and run.hyperparameters.get("candidate_run_id") == run_id
        and run.hyperparameters.get("passed") is True
    ]
    if not g1_runs:
        print("PASS한 G1 기록이 없는 후보입니다. G2를 실행하지 않습니다.", file=sys.stderr)
        return 1
    existing = [
        run
        for run in all_runs
        if run.model_type == "g2_gate_evaluation"
        and run.hyperparameters.get("candidate_run_id") == run_id
    ]
    if existing:
        print(
            f"이 후보의 G2 test는 이미 평가했습니다: {existing[-1].run_id}",
            file=sys.stderr,
        )
        return 1
    artifact_path_raw = candidate_run.hyperparameters.get("artifact_path")
    if not artifact_path_raw:
        print("후보 run에 artifact 경로가 없습니다.", file=sys.stderr)
        return 1
    artifact_path = Path(str(artifact_path_raw))
    artifact_dir = artifact_path.parent
    valid_predictions_path = artifact_dir / "predictions_valid.parquet"
    test_predictions_path = artifact_dir / "predictions_test_g1.parquet"
    if not valid_predictions_path.exists() or not test_predictions_path.exists():
        print(
            "고정 valid 또는 G1 test prediction 파일이 없습니다. 재추론하지 않고 중단합니다.",
            file=sys.stderr,
        )
        return 1

    version, as_of_policy = candidate_run.dataset_version.split("/", maxsplit=1)
    dataset_root = Path(dataset_dir) / version / as_of_policy
    dataset_path = dataset_root / "dataset.parquet"
    manifest_path = dataset_root / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"데이터셋 또는 manifest 없음: {dataset_root}", file=sys.stderr)
        return 1
    frame = assign_split(pl.read_parquet(dataset_path))
    valid_frame = frame.filter(pl.col("split") == "valid").drop("split")
    test_frame = frame.filter(pl.col("split") == "test").drop("split")
    valid_predictions = pl.read_parquet(valid_predictions_path)
    test_predictions = pl.read_parquet(test_predictions_path)
    with SessionLocal() as session:
        odds = fetch_win_odds(session)

    valid_market = prepare_market_comparison(valid_frame, valid_predictions, odds)
    fit = fit_incremental_logit(valid_market)
    valid_scored = apply_incremental_logit(valid_market, fit)
    valid_market_metrics, valid_mixed_metrics = evaluate_market_and_mix(valid_scored)
    selected_threshold, threshold_rows = select_ev_threshold(valid_scored)

    # Holdout test access begins here.  Every choice above is fixed from valid.
    test_market = prepare_market_comparison(test_frame, test_predictions, odds)
    test_scored = apply_incremental_logit(test_market, fit)
    test_market_metrics, test_mixed_metrics = evaluate_market_and_mix(test_scored)
    ll_bootstrap = bootstrap_log_loss_improvement(
        test_scored,
        iterations=bootstrap_iterations,
    )
    test_backtest = backtest_win_ev(
        test_scored,
        threshold=selected_threshold,
        bootstrap_iterations=bootstrap_iterations,
    )
    decision = judge_g2(
        fit=fit,
        market_test_log_loss=test_market_metrics["log_loss"],
        mixed_test_log_loss=test_mixed_metrics["log_loss"],
        log_loss_bootstrap=ll_bootstrap,
        roi_bootstrap=test_backtest.roi_bootstrap,
    )

    gate_run_id = new_run_id()
    report = render_g2_report(
        candidate_run_id=run_id,
        fit=fit,
        valid_market_metrics=valid_market_metrics,
        valid_mixed_metrics=valid_mixed_metrics,
        test_market_metrics=test_market_metrics,
        test_mixed_metrics=test_mixed_metrics,
        valid_overround=overround_summary(valid_scored),
        test_overround=overround_summary(test_scored),
        selected_threshold=selected_threshold,
        threshold_rows=threshold_rows,
        test_backtest=test_backtest,
        log_loss_bootstrap=ll_bootstrap,
        decision=decision,
        valid_total_races=valid_frame["race_id"].n_unique(),
        test_total_races=test_frame["race_id"].n_unique(),
    )
    report_path = Path(report_dir) / f"g2_{version}_{as_of_policy}_{gate_run_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    predictions_path = artifact_dir / "predictions_market_g2.parquet"
    pl.concat(
        [
            valid_scored.with_columns(pl.lit("valid").alias("split")),
            test_scored.with_columns(pl.lit("test").alias("split")),
        ],
        how="vertical",
    ).write_parquet(predictions_path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roi_bootstrap = test_backtest.roi_bootstrap
    metrics = {
        "valid_market_log_loss": valid_market_metrics["log_loss"],
        "valid_mixed_log_loss": valid_mixed_metrics["log_loss"],
        "valid_model_beta": fit.model_coefficient,
        "valid_model_beta_cluster_se": fit.model_standard_error,
        "valid_model_beta_one_sided_p": fit.model_p_value_one_sided,
        "test_market_log_loss": test_market_metrics["log_loss"],
        "test_mixed_log_loss": test_mixed_metrics["log_loss"],
        "test_log_loss_improvement": (
            test_market_metrics["log_loss"] - test_mixed_metrics["log_loss"]
        ),
        "test_log_loss_bootstrap_lower_95": ll_bootstrap.lower_95,
        "test_log_loss_bootstrap_upper_95": ll_bootstrap.upper_95,
        "test_flat_roi": test_backtest.flat_roi,
        "test_n_bets": float(test_backtest.n_bets),
        "test_max_drawdown_units": test_backtest.max_drawdown_units,
        "test_max_consecutive_losses": float(test_backtest.max_consecutive_losses),
        "test_roi_bootstrap_median": roi_bootstrap.median if roi_bootstrap else None,
        "test_roi_bootstrap_lower_95": (roi_bootstrap.lower_95 if roi_bootstrap else None),
        "test_roi_bootstrap_upper_95": (roi_bootstrap.upper_95 if roi_bootstrap else None),
    }
    gate_run = ModelRun(
        run_id=gate_run_id,
        dataset_version=candidate_run.dataset_version,
        dataset_manifest={
            key: manifest.get(key)
            for key in ("version", "as_of_policy", "row_count", "race_count", "feature_hash")
        },
        feature_names=candidate_run.feature_names,
        model_type="g2_gate_evaluation",
        hyperparameters={
            "candidate_run_id": run_id,
            "g1_gate_run_id": g1_runs[-1].run_id,
            "status": decision.status,
            "criteria": decision.criteria,
            "selected_ev_threshold": selected_threshold,
            "bootstrap_iterations": bootstrap_iterations,
            "odds_source": "odds_snapshots.WIN(final latest; 9999.9 sentinel excluded)",
            "predictions_path": str(predictions_path),
        },
        seed=20260827,
        train_period=candidate_run.train_period,
        valid_period=candidate_run.valid_period,
        test_period="2026-06-01~",
        metrics=metrics,
        notes=f"Gate G2 {decision.status}; final-odds ex-post only; report={report_path}",
    )
    record_run(gate_run)
    print(f"Gate G2 {decision.status}: run_id={gate_run_id}")
    print(
        f"valid β(model)={fit.model_coefficient:.4f}, "
        f"cluster SE={fit.model_standard_error:.4f}, p(one-sided)={fit.model_p_value_one_sided:.6g}"
    )
    print(
        f"test LL 시장={test_market_metrics['log_loss']:.6f}, "
        f"혼합={test_mixed_metrics['log_loss']:.6f}, "
        f"bootstrap 95% CI=[{ll_bootstrap.lower_95:+.6f}, {ll_bootstrap.upper_95:+.6f}]"
    )
    if roi_bootstrap is not None:
        print(
            f"θ={selected_threshold:.2f}, bets={test_backtest.n_bets}, "
            f"flat ROI={test_backtest.flat_roi:+.2%}, "
            f"bootstrap median={roi_bootstrap.median:+.2%}, "
            f"95% CI=[{roi_bootstrap.lower_95:+.2%}, {roi_bootstrap.upper_95:+.2%}]"
        )
    print("주의: 확정배당 사후평가이며 구매시점 수익성 증거가 아닙니다.")
    print(f"report: {report_path}")
    return 0 if decision.status == "PASS" else 1


def run_ordered_triple_value_command(
    run_id: str,
    dataset_dir: str,
    *,
    report_dir: str = "data/experiments/reports",
    top_n: int = 4,
    ev_thresholds: list[float] | None = None,
    bootstrap_iterations: int = 1_000,
) -> int:
    import polars as pl

    from horse_racing.analysis.baselines import assign_split
    from horse_racing.analysis.experiments import (
        ModelRun,
        get_run,
        new_run_id,
        record_run,
    )
    from horse_racing.analysis.ordered_triple import (
        DEFAULT_EV_THRESHOLDS,
        ORDERED_TRIPLE_POOL,
        backtest_ordered_triple_value,
        fetch_ordered_triple_odds,
        prepare_ordered_triple_value,
        render_ordered_triple_report,
    )

    if top_n < 3:
        print("top-n은 최소 3이어야 합니다.", file=sys.stderr)
        return 2
    if bootstrap_iterations < 100:
        print("bootstrap은 최소 100회가 필요합니다.", file=sys.stderr)
        return 2
    thresholds = sorted(set(ev_thresholds or DEFAULT_EV_THRESHOLDS))
    if any(value < 0 for value in thresholds):
        print("EV 임계값은 0 이상이어야 합니다.", file=sys.stderr)
        return 2
    candidate_run = get_run(run_id)
    if candidate_run is None:
        print(f"알 수 없는 후보 run_id: {run_id}", file=sys.stderr)
        return 1
    artifact_path_raw = candidate_run.hyperparameters.get("artifact_path")
    if not artifact_path_raw:
        print("후보 run에 artifact 경로가 없습니다.", file=sys.stderr)
        return 1
    artifact_dir = Path(str(artifact_path_raw)).parent
    predictions_path = artifact_dir / "predictions_valid.parquet"
    if not predictions_path.exists():
        print(f"valid prediction 파일 없음: {predictions_path}", file=sys.stderr)
        return 1

    version, as_of_policy = candidate_run.dataset_version.split("/", maxsplit=1)
    dataset_root = Path(dataset_dir) / version / as_of_policy
    dataset_path = dataset_root / "dataset.parquet"
    manifest_path = dataset_root / "manifest.json"
    if not dataset_path.exists() or not manifest_path.exists():
        print(f"데이터셋 또는 manifest 없음: {dataset_root}", file=sys.stderr)
        return 1
    frame = (
        assign_split(pl.read_parquet(dataset_path)).filter(pl.col("split") == "valid").drop("split")
    )
    predictions = pl.read_parquet(predictions_path)
    with SessionLocal() as session:
        odds = fetch_ordered_triple_odds(session)
    scored = prepare_ordered_triple_value(frame, predictions, odds, top_n=top_n)
    results = [
        backtest_ordered_triple_value(
            scored,
            threshold=value,
            bootstrap_iterations=bootstrap_iterations,
            seed=20260901 + index,
        )
        for index, value in enumerate(thresholds)
    ]

    diagnostic_run_id = new_run_id()
    report = render_ordered_triple_report(
        scored,
        results,
        candidate_run_id=run_id,
        top_n=top_n,
    )
    report_path = (
        Path(report_dir) / f"ordered_triple_value_{version}_{as_of_policy}_{diagnostic_run_id}.md"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    combinations_path = artifact_dir / f"ordered_triple_value_{diagnostic_run_id}.parquet"
    scored.write_parquet(combinations_path)

    metrics: dict[str, float | None] = {}
    for result in results:
        threshold_label = str(result.threshold).replace(".", "p")
        prefix = f"valid_ev_{threshold_label}"
        metrics.update(
            {
                f"{prefix}_bets": float(result.n_bets),
                f"{prefix}_races": float(result.n_races_bet),
                f"{prefix}_roi": result.flat_roi,
                f"{prefix}_profit": result.flat_profit,
                f"{prefix}_race_hit_rate": result.race_hit_rate,
                f"{prefix}_bootstrap_lower_95": (
                    result.roi_bootstrap.lower_95 if result.roi_bootstrap else None
                ),
                f"{prefix}_bootstrap_upper_95": (
                    result.roi_bootstrap.upper_95 if result.roi_bootstrap else None
                ),
            }
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record_run(
        ModelRun(
            run_id=diagnostic_run_id,
            dataset_version=candidate_run.dataset_version,
            dataset_manifest={
                key: manifest.get(key)
                for key in (
                    "version",
                    "as_of_policy",
                    "row_count",
                    "race_count",
                    "feature_hash",
                )
            },
            feature_names=candidate_run.feature_names,
            model_type="ordered_triple_value_diagnostic",
            hyperparameters={
                "candidate_run_id": run_id,
                "top_n": top_n,
                "ev_thresholds": thresholds,
                "bootstrap_iterations": bootstrap_iterations,
                "probability_model": "Plackett-Luce from calibrated P(win)",
                "odds_source": (
                    f"odds_snapshots.{ORDERED_TRIPLE_POOL}(final latest; 9999.9 sentinel excluded)"
                ),
                "combinations_path": str(combinations_path),
                "report_path": str(report_path),
            },
            seed=20260901,
            train_period=candidate_run.train_period,
            valid_period=candidate_run.valid_period,
            test_period="",
            metrics=metrics,
            notes=(
                "상위 N두 순서 3두 PL 확률과 확정배당 EV 사후진단; "
                f"실시간 구매시점 배당 아님; report={report_path}"
            ),
        )
    )
    print(f"ordered-triple 진단 완료: run_id={diagnostic_run_id}")
    for result in results:
        bootstrap = result.roi_bootstrap
        interval = (
            f"[{bootstrap.lower_95:+.2%}, {bootstrap.upper_95:+.2%}]"
            if bootstrap is not None
            else "—"
        )
        print(
            f"EV>{result.threshold:.2f}: bets={result.n_bets}, "
            f"races={result.n_races_bet}, ROI={result.flat_roi:+.2%}, "
            f"95% CI={interval}"
        )
    print("주의: 확정배당 사후평가이며 구매시점 수익성 증거가 아닙니다.")
    print(f"report: {report_path}")
    print(f"combinations: {combinations_path}")
    return 0


def list_model_runs(metric: str | None = None, *, ledger_path: Path | None = None) -> int:
    from horse_racing.analysis.experiments import load_runs, sort_runs

    runs = load_runs(ledger_path=ledger_path)
    if not runs:
        print("기록된 모델 실험이 없습니다.")
        return 0

    if metric:
        runs = sort_runs(runs, metric, descending=True)
    else:
        runs = sorted(runs, key=lambda item: item.created_at_ms, reverse=True)

    metric_names = sorted({name for run in runs for name in run.metrics})
    if metric:
        metric_names = [metric] + [name for name in metric_names if name != metric]

    headers = ["run_id", "created_at", "model_type", "dataset_version", *metric_names]
    rows: list[list[str]] = []
    for run in runs:
        created = datetime.fromtimestamp(run.created_at_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
        row = [run.run_id, created, run.model_type, run.dataset_version]
        for name in metric_names:
            value = run.metrics.get(name)
            row.append(_format_cell(value))
        rows.append(row)
    _print_aligned_table(headers, rows)
    return 0


def compare_model_runs(run_ids: list[str], *, ledger_path: Path | None = None) -> int:
    from horse_racing.analysis.experiments import compare_runs, get_run, values_differ

    if len(run_ids) < 2:
        print("비교하려면 2개 이상의 run_id가 필요합니다.", file=sys.stderr)
        return 2

    runs = []
    missing: list[str] = []
    for run_id in run_ids:
        run = get_run(run_id, ledger_path=ledger_path)
        if run is None:
            missing.append(run_id)
        else:
            runs.append(run)
    if missing:
        print(f"알 수 없는 run_id: {', '.join(missing)}", file=sys.stderr)
        return 1

    comparison = compare_runs(runs)
    columns = comparison.run_ids

    identity_rows = [
        ["model_type", *[comparison.model_types[run_id] for run_id in columns]],
        ["dataset_version", *[comparison.dataset_versions[run_id] for run_id in columns]],
        ["seed", *[str(comparison.seeds[run_id]) for run_id in columns]],
        ["feature_hash", *[comparison.feature_hashes[run_id] for run_id in columns]],
    ]
    print("실험 비교")
    _print_aligned_table(["field", *columns], identity_rows)
    print("feature_hash 일치: " + ("no" if comparison.feature_hash_mismatch else "yes"))

    if comparison.metrics:
        print()
        print("지표")
        metric_rows: list[list[str]] = []
        for name, values in comparison.metrics.items():
            marker = "DIFF" if values_differ(values) else ""
            metric_rows.append(
                [name, *[_format_cell(values[run_id]) for run_id in columns], marker]
            )
        _print_aligned_table(["metric", *columns, ""], metric_rows)

    if comparison.hyperparameters:
        print()
        print("하이퍼파라미터")
        hparam_rows: list[list[str]] = []
        for name, values in comparison.hyperparameters.items():
            marker = "DIFF" if values_differ(values) else ""
            hparam_rows.append(
                [name, *[_format_cell(values[run_id]) for run_id in columns], marker]
            )
        _print_aligned_table(["param", *columns, ""], hparam_rows)
    return 0
