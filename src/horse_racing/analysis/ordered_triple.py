"""Plackett-Luce ordered top-three probabilities and ex-post value backtests."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import permutations, product
from typing import Any

import numpy as np
import polars as pl
from sqlalchemy import text
from sqlalchemy.orm import Session

ORDERED_TRIPLE_POOL = "TRI"
FINAL_ODDS_SENTINEL = 9999.9
DEFAULT_EV_THRESHOLDS = (0.0, 0.05, 0.10, 0.20, 0.30, 0.50, 1.00)


class OrderedTripleInputError(ValueError):
    """Raised when ordered-triple inputs violate the probability contract."""


@dataclass(frozen=True)
class RoiBootstrap:
    median: float
    mean: float
    lower_95: float
    upper_95: float
    probability_positive: float
    iterations: int


@dataclass(frozen=True)
class OrderedTripleBacktest:
    threshold: float
    n_bets: int
    n_races_bet: int
    winning_tickets: int
    winning_races: int
    ticket_hit_rate: float
    race_hit_rate: float
    average_bets_per_race: float
    flat_profit: float
    flat_roi: float
    max_drawdown_units: float
    max_consecutive_losing_races: int
    monthly: list[dict[str, Any]]
    roi_bootstrap: RoiBootstrap | None


def _require_columns(frame: pl.DataFrame, required: set[str], *, label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise OrderedTripleInputError(f"{label} 컬럼 없음: {', '.join(missing)}")


def plackett_luce_ordered_triples(
    predictions: pl.DataFrame,
    *,
    top_n: int = 4,
    probability_column: str = "prob_win",
) -> pl.DataFrame:
    """Generate ordered top-three probabilities among each race's top-N horses.

    ``prob_win`` is treated as the normalized Plackett-Luce worth share.  The
    first-place marginal therefore remains the model's calibrated win
    probability, while later places are sampled from the remaining worth.
    """
    if top_n < 3:
        raise OrderedTripleInputError("top_n은 최소 3이어야 합니다.")
    _require_columns(
        predictions,
        {"race_id", "horse_number", probability_column},
        label="prediction",
    )
    if predictions.height == 0:
        raise OrderedTripleInputError("prediction이 비어 있습니다.")

    rows: list[dict[str, Any]] = []
    for race_key, group in predictions.group_by("race_id", maintain_order=True):
        race_id = race_key[0]
        ordered = group.sort(probability_column, "horse_number", descending=[True, False])
        if ordered.height < top_n:
            raise OrderedTripleInputError(
                f"race_id={race_id}: 출전 {ordered.height}두로 top_n={top_n}을 만들 수 없습니다."
            )
        probabilities = np.asarray(ordered[probability_column].to_list(), dtype=float)
        if not np.all(np.isfinite(probabilities)) or np.any(probabilities < 0):
            raise OrderedTripleInputError(
                f"race_id={race_id}: 확률은 유한한 0 이상 값이어야 합니다."
            )
        total = float(probabilities.sum())
        if total <= 0:
            raise OrderedTripleInputError(f"race_id={race_id}: 확률 합이 0입니다.")
        probabilities /= total
        horse_numbers = [int(value) for value in ordered["horse_number"].to_list()]
        candidates = list(range(top_n))
        top_n_mass = float(probabilities[:top_n].sum())
        race_rows: list[dict[str, Any]] = []
        for first, second, third in permutations(candidates, 3):
            remaining_after_first = 1.0 - probabilities[first]
            remaining_after_second = remaining_after_first - probabilities[second]
            if remaining_after_first <= 0 or remaining_after_second <= 0:
                raise OrderedTripleInputError(
                    f"race_id={race_id}: Plackett-Luce 조건부 분모가 0입니다."
                )
            probability = (
                probabilities[first]
                * probabilities[second]
                / remaining_after_first
                * probabilities[third]
                / remaining_after_second
            )
            numbers = (
                horse_numbers[first],
                horse_numbers[second],
                horse_numbers[third],
            )
            race_rows.append(
                {
                    "race_id": race_id,
                    "first_horse_number": numbers[0],
                    "second_horse_number": numbers[1],
                    "third_horse_number": numbers[2],
                    "selection_key": "-".join(str(value) for value in numbers),
                    "combo_probability": float(probability),
                    "top_n_mass": top_n_mass,
                }
            )
        box_probability = sum(row["combo_probability"] for row in race_rows)
        for row in race_rows:
            row["box_probability"] = box_probability
        rows.extend(race_rows)
    return pl.DataFrame(rows, infer_schema_length=None)


def ordered_winner_keys(
    frame: pl.DataFrame,
    *,
    finish_column: str = "finish_position",
) -> pl.DataFrame:
    """Return every official ordered top-three winner, including dead heats."""
    _require_columns(
        frame,
        {"race_id", "horse_number", finish_column},
        label="result",
    )
    rows: list[dict[str, Any]] = []
    for race_key, group in frame.group_by("race_id", maintain_order=True):
        race_id = race_key[0]
        clean = group.filter(
            pl.col(finish_column).is_not_null()
            & (pl.col(finish_column) > 0)
            & (pl.col(finish_column) < 90)
        )
        remaining_slots = 3
        rank_options: list[list[tuple[int, ...]]] = []
        for position in sorted(clean[finish_column].unique().to_list()):
            tied = sorted(
                int(value)
                for value in clean.filter(pl.col(finish_column) == position)[
                    "horse_number"
                ].to_list()
            )
            take = min(len(tied), remaining_slots)
            rank_options.append(list(permutations(tied, take)))
            remaining_slots -= take
            if remaining_slots == 0:
                break
        if remaining_slots:
            continue
        keys = {
            "-".join(str(value) for part in parts for value in part)
            for parts in product(*rank_options)
        }
        for selection_key in sorted(keys):
            rows.append(
                {
                    "race_id": race_id,
                    "selection_key": selection_key,
                    "won": 1,
                }
            )
    return pl.DataFrame(
        rows,
        schema={"race_id": pl.Int64, "selection_key": pl.String, "won": pl.Int8},
    )


def fetch_ordered_triple_odds(
    session: Session,
    *,
    bet_type: str = ORDERED_TRIPLE_POOL,
) -> pl.DataFrame:
    """Read the latest ordered top-three odds for each race and selection."""
    rows = session.execute(
        text(
            """
            SELECT race_id, selection_key, odds
            FROM odds_snapshots
            WHERE bet_type = :bet_type
              AND (race_id, selection_key, observed_at_ms) IN (
                  SELECT race_id, selection_key, MAX(observed_at_ms)
                  FROM odds_snapshots
                  WHERE bet_type = :bet_type
                  GROUP BY race_id, selection_key
              )
            """
        ),
        {"bet_type": bet_type},
    ).mappings().all()
    if not rows:
        return pl.DataFrame(
            schema={"race_id": pl.Int64, "selection_key": pl.String, "odds": pl.Float64}
        )
    return pl.DataFrame([dict(row) for row in rows], infer_schema_length=None)


def prepare_ordered_triple_value(
    frame: pl.DataFrame,
    predictions: pl.DataFrame,
    odds: pl.DataFrame,
    *,
    top_n: int = 4,
) -> pl.DataFrame:
    """Join PL combinations, exact-order outcomes, race context, and odds."""
    _require_columns(
        frame,
        {"race_id", "horse_number", "finish_position", "race_date_local", "race_number"},
        label="dataset",
    )
    _require_columns(odds, {"race_id", "selection_key", "odds"}, label="odds")
    combinations_frame = plackett_luce_ordered_triples(predictions, top_n=top_n)
    winners = ordered_winner_keys(frame)
    if winners.height == 0:
        raise OrderedTripleInputError("정상 1·2·3착 결과가 있는 경주가 없습니다.")
    winner_races = winners.select("race_id").unique()
    context = frame.select("race_id", "race_date_local", "race_number").unique(
        subset=["race_id"],
        keep="first",
    )
    return (
        combinations_frame.join(winner_races, on="race_id", how="inner")
        .join(context, on="race_id", how="left", validate="m:1")
        .join(odds, on=["race_id", "selection_key"], how="left", validate="m:1")
        .join(winners, on=["race_id", "selection_key"], how="left", validate="m:1")
        .with_columns(
            pl.col("won").fill_null(0).cast(pl.Int8),
            (
                pl.col("odds").is_not_null()
                & (pl.col("odds") > 1.0)
                & (pl.col("odds") < FINAL_ODDS_SENTINEL)
            ).alias("valid_odds"),
        )
        .with_columns(
            pl.when(pl.col("valid_odds"))
            .then(pl.col("combo_probability") * pl.col("odds") - 1.0)
            .otherwise(None)
            .alias("estimated_ev")
        )
        .sort("race_date_local", "race_number", "selection_key")
    )


def _roi_bootstrap(
    per_race: pl.DataFrame,
    *,
    iterations: int,
    seed: int,
) -> RoiBootstrap:
    profits = per_race["profit"].to_numpy()
    stakes = per_race["stake"].cast(pl.Float64).to_numpy()
    rng = np.random.default_rng(seed)
    values = np.empty(iterations, dtype=float)
    for index in range(iterations):
        draw = rng.integers(0, len(profits), size=len(profits))
        values[index] = profits[draw].sum() / stakes[draw].sum()
    return RoiBootstrap(
        median=float(np.median(values)),
        mean=float(np.mean(values)),
        lower_95=float(np.quantile(values, 0.025)),
        upper_95=float(np.quantile(values, 0.975)),
        probability_positive=float(np.mean(values > 0)),
        iterations=iterations,
    )


def _max_consecutive_losses(values: list[bool]) -> int:
    longest = current = 0
    for won in values:
        if won:
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def backtest_ordered_triple_value(
    scored: pl.DataFrame,
    *,
    threshold: float,
    bootstrap_iterations: int = 0,
    seed: int = 20260901,
) -> OrderedTripleBacktest:
    """Flat-stake backtest of combinations whose estimated EV exceeds threshold."""
    _require_columns(
        scored,
        {
            "race_id",
            "race_date_local",
            "race_number",
            "selection_key",
            "odds",
            "won",
            "valid_odds",
            "estimated_ev",
        },
        label="scored",
    )
    selected = (
        scored.filter(pl.col("valid_odds") & (pl.col("estimated_ev") > threshold))
        .with_columns((pl.col("won") * pl.col("odds") - 1.0).alias("profit"))
        .sort("race_date_local", "race_number", "selection_key")
    )
    if selected.height == 0:
        return OrderedTripleBacktest(
            threshold=threshold,
            n_bets=0,
            n_races_bet=0,
            winning_tickets=0,
            winning_races=0,
            ticket_hit_rate=0.0,
            race_hit_rate=0.0,
            average_bets_per_race=0.0,
            flat_profit=0.0,
            flat_roi=0.0,
            max_drawdown_units=0.0,
            max_consecutive_losing_races=0,
            monthly=[],
            roi_bootstrap=None,
        )
    per_race = (
        selected.group_by("race_id", maintain_order=True)
        .agg(
            pl.first("race_date_local").alias("race_date_local"),
            pl.first("race_number").alias("race_number"),
            pl.len().alias("stake"),
            pl.col("profit").sum().alias("profit"),
            pl.col("won").sum().alias("winning_tickets"),
        )
        .sort("race_date_local", "race_number")
    )
    cumulative = np.cumsum(per_race["profit"].to_numpy())
    running_peak = np.maximum.accumulate(np.concatenate(([0.0], cumulative)))[1:]
    drawdown = running_peak - cumulative
    winning_tickets = int(selected["won"].sum())
    winning_races = int((per_race["winning_tickets"] > 0).sum())
    monthly = (
        per_race.with_columns(pl.col("race_date_local").str.slice(0, 7).alias("month"))
        .group_by("month")
        .agg(
            pl.col("stake").sum().alias("bets"),
            pl.len().alias("races"),
            pl.col("winning_tickets").sum().alias("winning_tickets"),
            pl.col("profit").sum().alias("profit"),
        )
        .with_columns((pl.col("profit") / pl.col("bets")).alias("roi"))
        .sort("month")
        .to_dicts()
    )
    return OrderedTripleBacktest(
        threshold=threshold,
        n_bets=selected.height,
        n_races_bet=per_race.height,
        winning_tickets=winning_tickets,
        winning_races=winning_races,
        ticket_hit_rate=winning_tickets / selected.height,
        race_hit_rate=winning_races / per_race.height,
        average_bets_per_race=selected.height / per_race.height,
        flat_profit=float(selected["profit"].sum()),
        flat_roi=float(selected["profit"].sum() / selected.height),
        max_drawdown_units=float(drawdown.max(initial=0.0)),
        max_consecutive_losing_races=_max_consecutive_losses(
            (per_race["winning_tickets"] > 0).to_list()
        ),
        monthly=monthly,
        roi_bootstrap=(
            _roi_bootstrap(per_race, iterations=bootstrap_iterations, seed=seed)
            if bootstrap_iterations > 0
            else None
        ),
    )


def render_ordered_triple_report(
    scored: pl.DataFrame,
    results: list[OrderedTripleBacktest],
    *,
    candidate_run_id: str,
    top_n: int,
) -> str:
    race_summary = scored.group_by("race_id").agg(
        pl.first("top_n_mass").alias("top_n_mass"),
        pl.first("box_probability").alias("box_probability"),
    )
    valid_combinations = scored.filter(pl.col("valid_odds")).height
    lines = [
        "# Plackett–Luce 순서 3두 가치진단",
        "",
        f"- 후보 run_id: `{candidate_run_id}`",
        f"- 후보마: 모델 P(win) 상위 {top_n}두",
        f"- 조합: 경주당 {math.perm(top_n, 3)}개 순서 3두",
        f"- 평가 경주: {race_summary.height:,}",
        f"- 정상 확정배당 조합: {valid_combinations:,}/{scored.height:,}",
        f"- 평균 상위 {top_n}두 승리확률 합: {race_summary['top_n_mass'].mean():.2%}",
        f"- 평균 PL 박스 적중확률: {race_summary['box_probability'].mean():.2%}",
        "- 배당은 구매시점 호가가 아닌 경주 종료 후 확정배당이다. "
        "사후 연구용이며 실전 수익성 증거가 아니다.",
        "",
        "Plackett–Luce 조합확률은 `p(i→j→k) = pᵢ × pⱼ/(1−pᵢ) × pₖ/(1−pᵢ−pⱼ)`로 계산했다.",
        "각 조합의 `EV = 조합확률 × 배당 − 1`이 임계값보다 클 때만 1단위 정액 베팅했다.",
        "",
        "| EV 임계값 | bets | races | 평균 bets/race | 적중 ticket | "
        "적중 race | 손익 | ROI | bootstrap 95% CI |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        bootstrap = result.roi_bootstrap
        interval = (
            f"{bootstrap.lower_95:+.2%}~{bootstrap.upper_95:+.2%}"
            if bootstrap is not None
            else "—"
        )
        lines.append(
            f"| {result.threshold:.2f} | {result.n_bets} | {result.n_races_bet} | "
            f"{result.average_bets_per_race:.2f} | {result.ticket_hit_rate:.2%} | "
            f"{result.race_hit_rate:.2%} | {result.flat_profit:+.1f} | "
            f"{result.flat_roi:+.2%} | {interval} |"
        )
    lines.extend(
        [
            "",
            "임계값은 같은 valid 표본에서 비교한 진단값이다. 가장 좋아 보이는 값을 사후 선택해 "
            "수익 전략으로 해석하지 않으며, 후보 규칙은 이후 미래 표본에서 고정 검증해야 한다.",
            "",
        ]
    )
    return "\n".join(lines)
