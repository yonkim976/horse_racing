"""Train and evaluate RacePortfolio V1 on frozen RaceFit OOF predictions."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
import uuid
from dataclasses import asdict
from pathlib import Path

import polars as pl

from horse_racing.analysis.race_portfolio import (
    SUPPORTED_POOLS,
    attach_final_odds,
    backtest_fixed_rank_ticket,
    backtest_portfolios,
    build_ticket_candidates,
    fit_race_portfolio_bundle,
    save_race_portfolio_bundle,
)

DEFAULT_PREDICTIONS = (
    "data/experiments/walk_forward/"
    "b3eed694-89a1-4bcf-ac8c-9677760c1448/predictions.parquet"
)
DEFAULT_DATASET = (
    "data/datasets/racefit_v5_sand_rich_v2_matched/"
    "start_minus_30m/dataset.parquet"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions-file", default=DEFAULT_PREDICTIONS)
    parser.add_argument("--dataset-file", default=DEFAULT_DATASET)
    parser.add_argument("--database", default="data/horse_racing.sqlite3")
    parser.add_argument("--output-dir", default="data/experiments/race_portfolio_v1")
    parser.add_argument("--train-end", default="2026-04-30")
    parser.add_argument("--valid-start", default="2026-05-01")
    parser.add_argument("--valid-end", default="2026-06-30")
    parser.add_argument("--test-start", default="2026-07-01")
    parser.add_argument("--test-end", default="2026-08-31")
    parser.add_argument("--lower-quantile", type=float, default=0.20)
    parser.add_argument("--budget-units", type=int, default=10)
    parser.add_argument("--max-tickets", type=int, default=3)
    parser.add_argument("--candidate-limit", type=int, default=6)
    parser.add_argument("--minimum-ticket-probability", type=float, default=0.05)
    parser.add_argument("--minimum-non-loss-probability", type=float, default=0.10)
    parser.add_argument(
        "--minimum-return-grid",
        type=float,
        nargs="+",
        default=[1.00, 1.02, 1.05, 1.10, 1.15],
    )
    parser.add_argument(
        "--pools",
        nargs="+",
        choices=SUPPORTED_POOLS,
        default=list(SUPPORTED_POOLS),
    )
    return parser.parse_args()


def fetch_odds(
    database: str,
    *,
    start_date: str,
    end_date: str,
    pools: list[str],
) -> pl.DataFrame:
    placeholders = ",".join("?" for _ in pools)
    query = f"""
        SELECT o.race_id, o.bet_type, o.selection_key, o.odds, o.observed_at_ms
        FROM odds_snapshots o
        JOIN races r ON r.id = o.race_id
        WHERE r.race_date_local BETWEEN ? AND ?
          AND o.bet_type IN ({placeholders})
    """
    with sqlite3.connect(database) as connection:
        rows = connection.execute(query, [start_date, end_date, *pools]).fetchall()
    return pl.DataFrame(
        rows,
        schema={
            "race_id": pl.Int64,
            "bet_type": pl.String,
            "selection_key": pl.String,
            "odds": pl.Float64,
            "observed_at_ms": pl.Int64,
        },
        orient="row",
    )


def _summary(result) -> dict[str, object]:
    raw = asdict(result)
    raw.pop("selections", None)
    return raw


def _render_report(
    *,
    run_id: str,
    args: argparse.Namespace,
    tickets: pl.DataFrame,
    scored: pl.DataFrame,
    valid_rows: list[tuple[float, object]],
    selected_threshold: float,
    test_result,
    valid_baselines: list[tuple[str, object]],
    test_baselines: list[tuple[str, object]],
    promotion_status: str,
) -> str:
    coverage = (
        scored.group_by("bet_type")
        .agg(
            pl.len().alias("tickets"),
            pl.col("valid_odds").sum().alias("valid_odds"),
            pl.col("actual_odds").median().alias("median_final_odds"),
            pl.col("predicted_odds_lower").median().alias("median_predicted_lower"),
            pl.col("predicted_odds_median").median().alias("median_predicted_median"),
        )
        .sort("bet_type")
    )
    lines = [
        "# RacePortfolio V1 연구 결과",
        "",
        f"- run_id: `{run_id}`",
        f"- 승격 상태: **{promotion_status}**",
        f"- RaceFit OOF: `{args.predictions_file}`",
        f"- 학습 종료: {args.train_end}",
        f"- 검증: {args.valid_start}~{args.valid_end}",
        f"- 연구 테스트: {args.test_start}~{args.test_end}",
        f"- 승식: {', '.join(args.pools)}",
        f"- 생성 ticket: {tickets.height:,}",
        f"- 배당 하위 분위: q={args.lower_quantile:.2f}",
        f"- 최소 ticket 적중확률: {args.minimum_ticket_probability:.1%}",
        f"- 최소 포트폴리오 원금회수확률: {args.minimum_non_loss_probability:.1%}",
        "- 최종배당은 학습 target과 사후 settlement로만 사용했으며 입력 feature가 아니다.",
        "- 2026년은 이미 반복 분석한 연구 표본이므로 미래 수익성 증거가 아니다.",
        "",
        "## 승식별 배당 예측 커버리지",
        "",
        "| 승식 | ticket | 정상배당 | 실제 중앙배당 | 예측 하위배당 중앙 | 예측 중앙배당 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in coverage.iter_rows(named=True):
        lines.append(
            f"| {row['bet_type']} | {row['tickets']:,} | {row['valid_odds']:,} | "
            f"{row['median_final_odds']:.2f} | {row['median_predicted_lower']:.2f} | "
            f"{row['median_predicted_median']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## 검증기간 최소 기대환급 기준 선택",
            "",
            "| 기준 | bet races | tickets | 적중 race | 원금회수 race | ROI |",
            "|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for threshold, result in valid_rows:
        suffix = " **선택**" if threshold == selected_threshold else ""
        roi_text = f"{result.roi:.2%}" if result.stake_units else "-"
        lines.append(
            f"| {threshold:.2f}{suffix} | {result.races_bet} | {result.tickets_bet} | "
            f"{result.hit_race_rate:.2%} | {result.profit_race_rate:.2%} | "
            f"{roi_text} |"
        )
    test_roi = f"{test_result.roi:.2%}" if test_result.stake_units else "해당 없음"
    removed_one = (
        f"{test_result.top_one_profit_removed_roi:.2%}"
        if test_result.stake_units
        else "해당 없음"
    )
    removed_three = (
        f"{test_result.top_three_profit_removed_roi:.2%}"
        if test_result.stake_units
        else "해당 없음"
    )
    lines.extend(
        [
            "",
            "## 연구 테스트 결과",
            "",
            f"- 대상 경주: {test_result.races_available:,}",
            f"- 베팅 경주: {test_result.races_bet:,}",
            f"- 구매 ticket: {test_result.tickets_bet:,}",
            f"- 적중 경주율: {test_result.hit_race_rate:.2%}",
            f"- 원금회수 경주율: {test_result.profit_race_rate:.2%}",
            f"- 환수율: **{test_roi}**",
            f"- 최대 낙폭: {test_result.max_drawdown_units:.1f}단위",
            f"- 최장 연속 손실: {test_result.max_consecutive_losing_races}경주",
            f"- 최고 수익 1경주 제거 ROI: {removed_one}",
            f"- 최고 수익 3경주 제거 ROI: {removed_three}",
            "- 구매 경주가 0이면 환수율은 0%가 아니라 계산 대상이 없다.",
            "",
            "### 월별 결과",
            "",
            "| 월 | races | stake | return | ROI |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in test_result.monthly:
        lines.append(
            f"| {row['month']} | {row['races']} | {row['stake']:.0f} | "
            f"{row['returned']:.1f} | {row['roi']:.2%} |"
        )
    lines.extend(
        [
            "",
            "## 고정 순위 기준선",
            "",
            "배당 예측을 사용하지 않고 경주당 1장을 동일하게 구매한 결과다. "
            "ROI 100%가 원금 회수다.",
            "",
            "| 구간 | 규칙 | races | 적중률 | ROI | 최고수익 1경주 제거 | "
            "최고수익 3경주 제거 | 최대낙폭 | 최장 연속미적중 |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for period, baselines in (("검증", valid_baselines), ("테스트", test_baselines)):
        for label, result in baselines:
            lines.append(
                f"| {period} | {label} | {result.races} | {result.hit_rate:.2%} | "
                f"{result.roi:.2%} | {result.top_one_profit_removed_roi:.2%} | "
                f"{result.top_three_profit_removed_roi:.2%} | "
                f"{result.max_drawdown_units:.1f} | {result.max_consecutive_losses} |"
            )
    lines.extend(
        [
            "",
            "이 결과는 확정배당 분포를 예측한 사후 연구다. 실제 승격은 2026-09 이후 "
            "append-only paper betting 원장으로만 판정한다.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    run_id = str(uuid.uuid4())
    target = Path(args.output_dir) / run_id
    target.mkdir(parents=True, exist_ok=False)

    predictions = pl.read_parquet(args.predictions_file)
    race_ids = predictions["race_id"].unique().to_list()
    frame = pl.read_parquet(args.dataset_file).filter(pl.col("race_id").is_in(race_ids))
    frame = frame.filter(
        (pl.col("race_date_local") <= args.test_end)
        & (pl.col("race_date_local") >= "2026-01-01")
    )
    frame_race_ids = frame["race_id"].unique().to_list()
    predictions = predictions.filter(pl.col("race_id").is_in(frame_race_ids))

    tickets = build_ticket_candidates(frame, predictions, pools=args.pools)
    odds = fetch_odds(
        args.database,
        start_date="2026-01-01",
        end_date=args.test_end,
        pools=args.pools,
    )
    tickets = attach_final_odds(tickets, odds)
    bundle = fit_race_portfolio_bundle(
        tickets,
        train_end=args.train_end,
        pools=args.pools,
        lower_quantile=args.lower_quantile,
    )
    scored = bundle.predict(tickets).join(
        tickets.select(
            "race_id",
            "bet_type",
            "selection_key",
            "actual_odds",
            "valid_odds",
            "won",
        ),
        on=["race_id", "bet_type", "selection_key"],
        how="left",
        validate="1:1",
        suffix="_settlement",
    )
    for column in ("actual_odds", "valid_odds", "won"):
        settlement = f"{column}_settlement"
        if settlement in scored.columns:
            scored = scored.with_columns(
                pl.coalesce(settlement, column).alias(column)
            ).drop(settlement)

    valid_rows = []
    for threshold in args.minimum_return_grid:
        result = backtest_portfolios(
            predictions,
            scored,
            start_date=args.valid_start,
            end_date=args.valid_end,
            budget_units=args.budget_units,
            max_tickets=args.max_tickets,
            candidate_limit=args.candidate_limit,
            minimum_expected_return=threshold,
            minimum_ticket_probability=args.minimum_ticket_probability,
            minimum_non_loss_probability=args.minimum_non_loss_probability,
        )
        valid_rows.append((threshold, result))
    eligible = [
        item for item in valid_rows if item[1].races_bet >= 30 and item[1].roi >= 1.0
    ]
    if eligible:
        selected_threshold, _ = max(
            eligible,
            key=lambda item: (
                item[1].profit_race_rate,
                item[1].roi,
                item[1].races_bet,
            ),
        )
    else:
        selected_threshold, _ = max(
            valid_rows,
            key=lambda item: (item[1].roi, item[1].races_bet),
        )

    test_result = backtest_portfolios(
        predictions,
        scored,
        start_date=args.test_start,
        end_date=args.test_end,
        budget_units=args.budget_units,
        max_tickets=args.max_tickets,
        candidate_limit=args.candidate_limit,
        minimum_expected_return=selected_threshold,
        minimum_ticket_probability=args.minimum_ticket_probability,
        minimum_non_loss_probability=args.minimum_non_loss_probability,
    )

    baseline_specs = [
        ("1순위 연승", "PLC", (1,)),
        ("1순위 단승", "WIN", (1,)),
        ("1-2순위 복연승", "QPL", (1, 2)),
        ("1-2순위 쌍승", "EXA", (1, 2)),
        ("1-2-3순위 삼복승", "TLA", (1, 2, 3)),
    ]

    def baselines(start_date: str, end_date: str) -> list[tuple[str, object]]:
        return [
            (
                label,
                backtest_fixed_rank_ticket(
                    scored,
                    bet_type=pool,
                    model_ranks=ranks,
                    start_date=start_date,
                    end_date=end_date,
                ),
            )
            for label, pool, ranks in baseline_specs
        ]

    valid_baselines = baselines(args.valid_start, args.valid_end)
    test_baselines = baselines(args.test_start, args.test_end)
    promotion_status = "PROMOTED" if (
        test_result.races_bet >= 50
        and test_result.roi >= 1.0
        and test_result.top_three_profit_removed_roi >= 0.95
    ) else "RESEARCH_ONLY"

    save_race_portfolio_bundle(bundle, target / "model.pkl")
    scored.write_parquet(target / "scored_tickets.parquet")
    test_result.selections.write_parquet(target / "test_selections.parquet")
    report = _render_report(
        run_id=run_id,
        args=args,
        tickets=tickets,
        scored=scored,
        valid_rows=valid_rows,
        selected_threshold=selected_threshold,
        test_result=test_result,
        valid_baselines=valid_baselines,
        test_baselines=test_baselines,
        promotion_status=promotion_status,
    )
    (target / "report.md").write_text(report, encoding="utf-8")
    manifest = {
        "run_id": run_id,
        "created_at_ms": time.time_ns() // 1_000_000,
        "model_name": bundle.model_name,
        "promotion_status": promotion_status,
        "racefit_predictions": args.predictions_file,
        "dataset": args.dataset_file,
        "pools": args.pools,
        "train_end": args.train_end,
        "valid_period": [args.valid_start, args.valid_end],
        "test_period": [args.test_start, args.test_end],
        "lower_quantile": args.lower_quantile,
        "selected_minimum_return": selected_threshold,
        "minimum_ticket_probability": args.minimum_ticket_probability,
        "minimum_non_loss_probability": args.minimum_non_loss_probability,
        "valid_results": {
            str(threshold): _summary(result) for threshold, result in valid_rows
        },
        "test_result": _summary(test_result),
        "valid_baselines": {
            label: asdict(result) for label, result in valid_baselines
        },
        "test_baselines": {
            label: asdict(result) for label, result in test_baselines
        },
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
