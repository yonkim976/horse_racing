"""Train and evaluate RaceValue V1 on frozen RaceFit predictions."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from dataclasses import asdict
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.metrics import brier_score_loss, roc_auc_score

from horse_racing.analysis.race_value import (
    backtest_sleeper_strategy,
    build_historical_sleeper_frame,
    fit_race_value_bundle,
    save_race_value_bundle,
    select_sleeper_candidates,
    settle_sleeper_candidates,
)

DEFAULT_PREDICTIONS = (
    "data/experiments/walk_forward/"
    "b3eed694-89a1-4bcf-ac8c-9677760c1448/predictions.parquet"
)
DEFAULT_DATASET = (
    "data/datasets/racefit_v5_sand_rich_v2_matched/"
    "start_minus_30m/dataset.parquet"
)
DEFAULT_SCORED_TICKETS = (
    "data/experiments/race_portfolio_v1/"
    "665d6c6d-d49e-4afb-a081-462b1477b5d6/scored_tickets.parquet"
)
POOLS = ("PLC", "QPL", "TLA")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-file", default=DEFAULT_DATASET)
    parser.add_argument("--predictions-file", default=DEFAULT_PREDICTIONS)
    parser.add_argument("--scored-tickets-file", default=DEFAULT_SCORED_TICKETS)
    parser.add_argument("--output-dir", default="data/experiments/race_value_v1")
    parser.add_argument("--train-end", default="2026-03-31")
    parser.add_argument("--calibration-start", default="2026-04-01")
    parser.add_argument("--calibration-end", default="2026-04-30")
    parser.add_argument("--valid-start", default="2026-05-01")
    parser.add_argument("--valid-end", default="2026-06-30")
    parser.add_argument("--test-start", default="2026-07-01")
    parser.add_argument("--test-end", default="2026-08-31")
    parser.add_argument(
        "--payout-exponents",
        type=float,
        nargs="+",
        default=[0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5],
    )
    parser.add_argument(
        "--confidence-quantiles", type=float, nargs="+", default=[0.0, 0.5, 0.75, 0.9]
    )
    return parser.parse_args()


def probability_metrics(frame: pl.DataFrame) -> dict[str, float]:
    actual = frame["sleeper_top3"].to_numpy()
    probability = frame["sleeper_probability"].to_numpy()
    bins = np.linspace(0.0, 1.0, 11)
    bin_index = np.minimum(np.digitize(probability, bins) - 1, 9)
    ece = 0.0
    for index in range(10):
        mask = bin_index == index
        if mask.any():
            ece += float(mask.mean()) * abs(
                float(probability[mask].mean()) - float(actual[mask].mean())
            )
    return {
        "auc": float(roc_auc_score(actual, probability)),
        "brier": float(brier_score_loss(actual, probability)),
        "ece": ece,
        "mean_probability": float(probability.mean()),
        "actual_rate": float(actual.mean()),
    }


def summary(result) -> dict[str, object]:
    values = asdict(result)
    values.pop("selections", None)
    return values


def result_rows(
    settled: pl.DataFrame,
    *,
    minimum_score: float | None = None,
) -> list[tuple[str, object]]:
    selected = settled
    if minimum_score is not None:
        selected = selected.filter(pl.col("sleeper_score") >= minimum_score)
    return [
        (pool, backtest_sleeper_strategy(selected, bet_type=pool)) for pool in POOLS
    ]


def render_report(
    *,
    run_id: str,
    args: argparse.Namespace,
    promotion_status: str,
    valid_probability: dict[str, float],
    test_probability: dict[str, float],
    alpha_results: list[dict[str, object]],
    selected_alpha: float,
    baseline_results: list[tuple[str, object]],
    test_results: list[tuple[str, object]],
    confidence_results: list[dict[str, object]],
    feature_importance: list[dict[str, object]],
) -> str:
    lines = [
        "# RaceValue V1 복병마 탐지 연구",
        "",
        f"- run_id: `{run_id}`",
        f"- 승격 상태: **{promotion_status}**",
        f"- 학습: ~{args.train_end}",
        f"- 확률보정: {args.calibration_start}~{args.calibration_end}",
        f"- 검증: {args.valid_start}~{args.valid_end}",
        f"- 연구 테스트: {args.test_start}~{args.test_end}",
        "- 복병 label: 실제 단승 인기 4위 이하이면서 3착 이내",
        "- 후보 범위: 모델 3~8순위 중 예상 시장인기 4위 이하",
        "- 최종배당은 label 생성과 사후 정산에만 사용했다.",
        "",
        "## 확률 품질",
        "",
        "| 구간 | AUC | Brier | ECE | 평균 예측 | 실제 label |",
        "|---|---:|---:|---:|---:|---:|",
        f"| 검증 | {valid_probability['auc']:.4f} | "
        f"{valid_probability['brier']:.4f} | {valid_probability['ece']:.4f} | "
        f"{valid_probability['mean_probability']:.2%} | "
        f"{valid_probability['actual_rate']:.2%} |",
        f"| 테스트 | {test_probability['auc']:.4f} | "
        f"{test_probability['brier']:.4f} | {test_probability['ece']:.4f} | "
        f"{test_probability['mean_probability']:.2%} | "
        f"{test_probability['actual_rate']:.2%} |",
        "",
        "## 배당 가중치 검증",
        "",
        "`score = log(3착이내확률) + alpha × log(예상시장단승배당)`",
        "",
        "| alpha | 복병 label | 연승 ROI | 복연승 ROI | 삼복승 ROI | 최저 ROI | 평균 ROI |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in alpha_results:
        suffix = " **선택**" if row["alpha"] == selected_alpha else ""
        lines.append(
            f"| {row['alpha']:.2f}{suffix} | {row['sleeper_hit_rate']:.2%} | "
            f"{row['PLC']:.2%} | {row['QPL']:.2%} | {row['TLA']:.2%} | "
            f"{row['minimum_roi']:.2%} | {row['mean_roi']:.2%} |"
        )
    lines.extend(
        [
            "",
            "## 테스트: 기존 3순위 후보 대비 RaceValue 후보",
            "",
            "| 후보 | 승식 | races | 적중률 | 복병 label | "
            "평균적중배당 | ROI | 최고수익 3경주 제거 |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for candidate_label, results in (
        ("기존 3순위", baseline_results),
        ("RaceValue", test_results),
    ):
        for pool, result in results:
            lines.append(
                f"| {candidate_label} | {pool} | {result.races} | "
                f"{result.hit_rate:.2%} | {result.sleeper_hit_rate:.2%} | "
                f"{result.average_winning_odds:.2f} | {result.roi:.2%} | "
                f"{result.top_three_profit_removed_roi:.2%} |"
            )
    lines.extend(
        [
            "",
            "## 검증에서 고정한 신뢰구간을 테스트에 적용",
            "",
            "| 검증 상위구간 | 테스트 races | 승식 | 적중률 | 복병 label | 평균적중배당 | ROI |",
            "|---:|---:|---|---:|---:|---:|---:|",
        ]
    )
    for group in confidence_results:
        for pool, result in group["results"]:
            lines.append(
                f"| {group['quantile']:.0%} | {result.races} | {pool} | "
                f"{result.hit_rate:.2%} | {result.sleeper_hit_rate:.2%} | "
                f"{result.average_winning_odds:.2f} | {result.roi:.2%} |"
            )
    lines.extend(
        [
            "",
            "## 상위 feature importance",
            "",
            "| feature | gain |",
            "|---|---:|",
        ]
    )
    for row in feature_importance[:15]:
        lines.append(f"| {row['feature']} | {row['gain']:.1f} |")
    lines.extend(
        [
            "",
            "2026년 구간은 이미 반복 탐색한 연구 표본이다. 실전 승격은 "
            "2026-09 이후 append-only paper betting 결과로만 판정한다.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    run_id = str(uuid.uuid4())
    target = Path(args.output_dir) / run_id
    target.mkdir(parents=True, exist_ok=False)

    dataset = pl.read_parquet(args.dataset_file)
    predictions = pl.read_parquet(args.predictions_file)
    scored_tickets = pl.read_parquet(args.scored_tickets_file)
    historical = build_historical_sleeper_frame(dataset, predictions, scored_tickets)
    bundle = fit_race_value_bundle(
        historical,
        train_end=args.train_end,
        calibration_start=args.calibration_start,
        calibration_end=args.calibration_end,
    )
    scored_horses = bundle.predict(historical)
    valid = scored_horses.filter(
        (pl.col("race_date_local") >= args.valid_start)
        & (pl.col("race_date_local") <= args.valid_end)
    )
    test = scored_horses.filter(
        (pl.col("race_date_local") >= args.test_start)
        & (pl.col("race_date_local") <= args.test_end)
    )
    valid_probability = probability_metrics(valid)
    test_probability = probability_metrics(test)

    alpha_rows: list[dict[str, object]] = []
    valid_candidates_by_alpha: dict[float, pl.DataFrame] = {}
    for alpha in args.payout_exponents:
        candidates = select_sleeper_candidates(valid, payout_exponent=alpha)
        settled = settle_sleeper_candidates(candidates, scored_tickets)
        results = result_rows(settled)
        alpha_rows.append(
            {
                "alpha": alpha,
                "sleeper_hit_rate": float(settled["sleeper_top3"].mean()),
                **{pool: result.roi for pool, result in results},
                "minimum_roi": float(min(result.roi for _, result in results)),
                "mean_roi": float(np.mean([result.roi for _, result in results])),
            }
        )
        valid_candidates_by_alpha[alpha] = candidates
    selected_alpha = float(
        max(
            alpha_rows,
            key=lambda row: (row["minimum_roi"], row["mean_roi"], -row["alpha"]),
        )["alpha"]
    )
    valid_candidates = valid_candidates_by_alpha[selected_alpha]
    test_candidates = select_sleeper_candidates(test, payout_exponent=selected_alpha)
    valid_settled = settle_sleeper_candidates(valid_candidates, scored_tickets)
    test_settled = settle_sleeper_candidates(test_candidates, scored_tickets)
    test_results = result_rows(test_settled)

    baseline_candidates = select_sleeper_candidates(
        test,
        minimum_model_rank=3,
        maximum_model_rank=3,
        payout_exponent=0.0,
        minimum_predicted_market_rank=1,
    )
    baseline_settled = settle_sleeper_candidates(baseline_candidates, scored_tickets)
    baseline_results = result_rows(baseline_settled)

    confidence_results: list[dict[str, object]] = []
    for quantile in args.confidence_quantiles:
        threshold = (
            float(valid_candidates["sleeper_score"].min())
            if quantile == 0
            else float(valid_candidates["sleeper_score"].quantile(quantile))
        )
        confidence_results.append(
            {
                "quantile": quantile,
                "threshold": threshold,
                "results": result_rows(test_settled, minimum_score=threshold),
            }
        )

    importance = bundle.estimator.booster_.feature_importance(importance_type="gain")
    feature_importance = sorted(
        [
            {"feature": feature, "gain": float(gain)}
            for feature, gain in zip(bundle.feature_names, importance, strict=True)
        ],
        key=lambda row: row["gain"],
        reverse=True,
    )
    test_best = max((result for _, result in test_results), key=lambda item: item.roi)
    promotion_status = "PROMOTED" if (
        test_probability["auc"] >= 0.65
        and test_best.races >= 100
        and test_best.roi >= 1.0
        and test_best.top_three_profit_removed_roi >= 0.95
    ) else "RESEARCH_ONLY"

    save_race_value_bundle(bundle, target / "model.pkl")
    scored_horses.write_parquet(target / "horse_scores.parquet")
    valid_settled.write_parquet(target / "validation_candidates.parquet")
    test_settled.write_parquet(target / "test_candidates.parquet")
    report = render_report(
        run_id=run_id,
        args=args,
        promotion_status=promotion_status,
        valid_probability=valid_probability,
        test_probability=test_probability,
        alpha_results=alpha_rows,
        selected_alpha=selected_alpha,
        baseline_results=baseline_results,
        test_results=test_results,
        confidence_results=confidence_results,
        feature_importance=feature_importance,
    )
    (target / "report.md").write_text(report, encoding="utf-8")
    manifest = {
        "run_id": run_id,
        "created_at_ms": time.time_ns() // 1_000_000,
        "model_name": bundle.model_name,
        "promotion_status": promotion_status,
        "periods": {
            "train_end": args.train_end,
            "calibration": [args.calibration_start, args.calibration_end],
            "validation": [args.valid_start, args.valid_end],
            "test": [args.test_start, args.test_end],
        },
        "selected_payout_exponent": selected_alpha,
        "probability_metrics": {
            "validation": valid_probability,
            "test": test_probability,
        },
        "validation_alpha_results": alpha_rows,
        "test_results": {pool: summary(result) for pool, result in test_results},
        "baseline_results": {
            pool: summary(result) for pool, result in baseline_results
        },
        "confidence_results": [
            {
                "quantile": row["quantile"],
                "threshold": row["threshold"],
                "results": {
                    pool: summary(result) for pool, result in row["results"]
                },
            }
            for row in confidence_results
        ],
        "feature_importance": feature_importance,
        "warning": "retrospective research; future paper validation required",
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(report)
    print(f"artifacts: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
