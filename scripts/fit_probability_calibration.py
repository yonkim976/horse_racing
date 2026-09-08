"""Fit post-hoc probability calibration from OOF predictions and test out of time."""

from __future__ import annotations

import argparse
import json
import sqlite3
import uuid
from pathlib import Path

import polars as pl

from horse_racing.analysis.metrics import evaluate_probabilities
from horse_racing.analysis.probability_calibration import (
    CALIBRATION_TARGETS,
    apply_probability_calibration,
    fit_probability_calibration,
    save_probability_calibration,
)


def _load_labeled_predictions(path: Path, database: Path) -> pl.DataFrame:
    predictions = pl.read_parquet(path)
    race_ids = predictions["race_id"].unique().to_list()
    placeholders = ",".join("?" for _ in race_ids)
    with sqlite3.connect(database) as connection:
        results = pl.read_database(
            query=(
                "SELECT e.race_id, e.horse_number, r.race_date_local, rr.finish_position "
                "FROM race_entries e JOIN races r ON r.id=e.race_id "
                "JOIN race_results rr ON rr.race_entry_id=e.id "
                f"WHERE e.race_id IN ({placeholders})"
            ),
            connection=connection,
            execute_options={"parameters": race_ids},
        )
    return predictions.join(results, on=["race_id", "horse_number"], how="inner").with_columns(
        (pl.col("finish_position") == 1).cast(pl.Int8).alias("win"),
        (pl.col("finish_position") <= 2).cast(pl.Int8).alias("top2"),
        (pl.col("finish_position") <= 3).cast(pl.Int8).alias("top3"),
    )


def _metrics(frame: pl.DataFrame) -> dict[str, dict[str, float]]:
    return {
        target: evaluate_probabilities(frame, f"prob_{target}", label_column=target)
        for target in CALIBRATION_TARGETS
    }


def _render_report(
    *,
    source_run_id: str,
    fit_predictions: Path,
    test_predictions: Path,
    fit_summary: str,
    test_summary: str,
    methods: dict[str, str],
    parameters: dict[str, dict[str, float] | None],
    deployment_parameters: dict[str, dict[str, float] | None],
    raw: dict[str, dict[str, float]],
    calibrated: dict[str, dict[str, float]],
) -> str:
    lines = [
        "# RaceFit 사후 확률 보정 리포트",
        "",
        f"- 원본 run: `{source_run_id}`",
        f"- 보정 학습 OOF: `{fit_predictions}`",
        f"- 보정 학습 표본: {fit_summary}",
        f"- 시간 외부 평가 OOF: `{test_predictions}`",
        f"- 시간 외부 평가 표본: {test_summary}",
        "- 우승 순위는 유지하고 Top2/Top3 누적확률만 sigmoid 보정했다.",
        "- 보정 후 경주별 합계 1/2/3과 P(win) <= P(top2) <= P(top3)를 투영했다.",
        "- `calibration_deploy.pkl`은 두 OOF 기간 전체에 재적합했으며 미래 예측 전용이다.",
        "",
        "| target | method | raw log loss | calibrated | raw brier | calibrated | "
        "raw ECE | calibrated |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for target in CALIBRATION_TARGETS:
        before = raw[target]
        after = calibrated[target]
        lines.append(
            f"| {target} | {methods[target]} | {before['log_loss']:.6f} | "
            f"{after['log_loss']:.6f} | {before['brier']:.6f} | {after['brier']:.6f} | "
            f"{before['ece']:.6f} | {after['ece']:.6f} |"
        )
    lines.extend(["", "## 시간 외부 평가에 사용한 보정 파라미터", "", "```json"])
    lines.extend([json.dumps(parameters, indent=2), "```", ""])
    lines.extend(["## 미래 배포용 재적합 파라미터", "", "```json"])
    lines.extend([json.dumps(deployment_parameters, indent=2), "```", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fit-predictions", type=Path, required=True)
    parser.add_argument("--test-predictions", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path("data/horse_racing.sqlite3"))
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--fit-period", default="historical OOF")
    parser.add_argument("--fit-start")
    parser.add_argument("--fit-end")
    parser.add_argument("--test-start")
    parser.add_argument("--test-end")
    parser.add_argument("--output-root", type=Path, default=Path("data/experiments/calibration"))
    args = parser.parse_args()

    fit = _load_labeled_predictions(args.fit_predictions, args.database)
    test = _load_labeled_predictions(args.test_predictions, args.database)
    if args.fit_start:
        fit = fit.filter(pl.col("race_date_local") >= args.fit_start)
    if args.fit_end:
        fit = fit.filter(pl.col("race_date_local") <= args.fit_end)
    if args.test_start:
        test = test.filter(pl.col("race_date_local") >= args.test_start)
    if args.test_end:
        test = test.filter(pl.col("race_date_local") <= args.test_end)
    if fit.height == 0 or test.height == 0:
        raise ValueError("날짜 필터 후 보정 학습 또는 평가 표본이 비었습니다.")
    overlap = set(fit["race_id"].unique().to_list()) & set(
        test["race_id"].unique().to_list()
    )
    if overlap:
        raise ValueError(f"보정 학습과 평가 경주가 겹칩니다: {len(overlap)}경주")
    bundle = fit_probability_calibration(
        fit,
        source_run_id=args.source_run_id,
        fit_period=args.fit_period,
    )
    calibrated_predictions = apply_probability_calibration(bundle, test)
    keys = ["race_id", "race_entry_id", "horse_number"]
    scored = test.select(*keys, "finish_position", *CALIBRATION_TARGETS).join(
        calibrated_predictions,
        on=keys,
    )
    raw_metrics = _metrics(test)
    calibrated_metrics = _metrics(scored)

    deployment_bundle = fit_probability_calibration(
        pl.concat([fit, test], how="vertical_relaxed"),
        source_run_id=args.source_run_id,
        fit_period=f"{args.fit_period} + evaluation OOF",
    )

    run_id = str(uuid.uuid4())
    output = args.output_root / run_id
    output.mkdir(parents=True, exist_ok=False)
    save_probability_calibration(bundle, output / "calibration.pkl")
    save_probability_calibration(deployment_bundle, output / "calibration_deploy.pkl")
    calibrated_predictions.write_parquet(output / "predictions.parquet")
    parameters = {
        target: (
            None
            if bundle.calibrators[target] is None
            else {
                "intercept": bundle.calibrators[target].intercept,
                "slope": bundle.calibrators[target].slope,
            }
        )
        for target in CALIBRATION_TARGETS
    }
    deployment_parameters = {
        target: (
            None
            if deployment_bundle.calibrators[target] is None
            else {
                "intercept": deployment_bundle.calibrators[target].intercept,
                "slope": deployment_bundle.calibrators[target].slope,
            }
        )
        for target in CALIBRATION_TARGETS
    }
    report = _render_report(
        source_run_id=args.source_run_id,
        fit_predictions=args.fit_predictions,
        test_predictions=args.test_predictions,
        fit_summary=(
            f"{fit['race_date_local'].min()}~{fit['race_date_local'].max()}, "
            f"{fit['race_id'].n_unique():,}경주/{fit.height:,}행"
        ),
        test_summary=(
            f"{test['race_date_local'].min()}~{test['race_date_local'].max()}, "
            f"{test['race_id'].n_unique():,}경주/{test.height:,}행"
        ),
        methods=bundle.methods,
        parameters=parameters,
        deployment_parameters=deployment_parameters,
        raw=raw_metrics,
        calibrated=calibrated_metrics,
    )
    (output / "report.md").write_text(report, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
