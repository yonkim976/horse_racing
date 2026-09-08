# ruff: noqa: E501
"""M6 market comparison, incremental-signal test, and WIN backtest.

The odds used here are final dividends.  They are deliberately kept outside
the feature matrix and are suitable only for an ex-post Gate G2 diagnostic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import polars as pl

from horse_racing.analysis.lightgbm_model import normalize_race_probabilities
from horse_racing.analysis.metrics import evaluate_probabilities

PROBABILITY_EPSILON = 1e-6
DEFAULT_THRESHOLD_GRID = (0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30)
MIN_VALID_BETS = 30
FINAL_ODDS_SENTINEL = 9999.9


class MarketGateInputError(ValueError):
    """Raised when G2 inputs are missing, incomplete, or inconsistent."""


@dataclass(frozen=True)
class IncrementalLogitFit:
    intercept: float
    market_coefficient: float
    model_coefficient: float
    model_standard_error: float
    model_z_score: float
    model_p_value_one_sided: float
    converged: bool
    iterations: int
    n_rows: int
    n_races: int


@dataclass(frozen=True)
class BootstrapSummary:
    median: float
    mean: float
    lower_95: float
    upper_95: float
    probability_positive: float
    iterations: int


@dataclass(frozen=True)
class BacktestSummary:
    threshold: float
    n_bets: int
    n_races_bet: int
    hit_rate: float
    flat_profit: float
    flat_roi: float
    max_drawdown_units: float
    max_consecutive_losses: int
    quarter_kelly_staked: float
    quarter_kelly_profit: float
    quarter_kelly_roi: float
    monthly: list[dict[str, Any]]
    roi_bootstrap: BootstrapSummary | None


@dataclass(frozen=True)
class G2Decision:
    status: str
    criteria: dict[str, bool]


def _logit(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(values, dtype=float), PROBABILITY_EPSILON, 1 - PROBABILITY_EPSILON)
    return np.log(clipped / (1 - clipped))


def _sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    result = np.empty_like(values)
    positive = values >= 0
    result[positive] = 1 / (1 + np.exp(-values[positive]))
    exponential = np.exp(values[~positive])
    result[~positive] = exponential / (1 + exponential)
    return result


def prepare_market_comparison(
    frame: pl.DataFrame,
    predictions: pl.DataFrame,
    odds: pl.DataFrame,
) -> pl.DataFrame:
    """Join labels, fixed model probabilities, and complete final WIN odds."""
    required_frame = {
        "race_id",
        "race_entry_id",
        "horse_number",
        "race_date_local",
        "race_number",
        "win",
    }
    missing = sorted(required_frame - set(frame.columns))
    if missing:
        raise MarketGateInputError(f"dataset 컬럼 없음: {', '.join(missing)}")
    required_predictions = {"race_id", "race_entry_id", "horse_number", "prob_win"}
    missing = sorted(required_predictions - set(predictions.columns))
    if missing:
        raise MarketGateInputError(f"prediction 컬럼 없음: {', '.join(missing)}")
    required_odds = {"race_id", "horse_number", "odds"}
    missing = sorted(required_odds - set(odds.columns))
    if missing:
        raise MarketGateInputError(f"odds 컬럼 없음: {', '.join(missing)}")

    base = frame.select(sorted(required_frame)).join(
        predictions.select(sorted(required_predictions)),
        on=["race_id", "race_entry_id", "horse_number"],
        how="inner",
        validate="1:1",
    )
    if base.height != predictions.height:
        raise MarketGateInputError(
            f"prediction join 행 수 불일치: prediction={predictions.height}, joined={base.height}"
        )
    joined = base.join(
        odds.select("race_id", "horse_number", "odds"),
        on=["race_id", "horse_number"],
        how="left",
        validate="1:1",
    ).with_columns(
        (
            pl.col("odds").is_null()
            | (pl.col("odds") <= 1.0)
            | (pl.col("odds") >= FINAL_ODDS_SENTINEL)
        )
        .any()
        .over("race_id")
        .alias("_invalid_race")
    )
    joined = joined.filter(~pl.col("_invalid_race")).drop("_invalid_race")
    if joined.height == 0:
        raise MarketGateInputError("완전한 정상 단승배당 경주가 없습니다.")
    joined = joined.with_columns(
        (1.0 / pl.col("odds")).alias("_implied"),
    ).with_columns(
        pl.col("_implied").sum().over("race_id").alias("market_overround")
    ).with_columns(
        (pl.col("_implied") / pl.col("market_overround")).alias("prob_market")
    )
    if joined.select(pl.col("prob_win").is_null().any()).item():
        raise MarketGateInputError("모델 승리확률에 null이 있습니다.")
    return joined.drop("_implied").sort("race_date_local", "race_number", "horse_number")


def fit_incremental_logit(
    frame: pl.DataFrame,
    *,
    market_column: str = "prob_market",
    model_column: str = "prob_win",
    label_column: str = "win",
    race_column: str = "race_id",
    max_iterations: int = 100,
    tolerance: float = 1e-9,
) -> IncrementalLogitFit:
    """Fit logit(y)=intercept+a*logit(market)+b*logit(model).

    Coefficients use binary maximum likelihood.  The reported standard error
    is a race-clustered sandwich estimate, since runners in one race are not
    independent observations.
    """
    required = {market_column, model_column, label_column, race_column}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise MarketGateInputError(f"혼합 회귀 컬럼 없음: {', '.join(missing)}")
    clean = frame.drop_nulls(list(required))
    if clean.height == 0:
        raise MarketGateInputError("혼합 회귀 입력이 비어 있습니다.")
    y = clean[label_column].cast(pl.Float64).to_numpy()
    x = np.column_stack(
        [
            np.ones(clean.height),
            _logit(clean[market_column].to_numpy()),
            _logit(clean[model_column].to_numpy()),
        ]
    )
    coefficients = np.zeros(3, dtype=float)
    ridge = np.diag([0.0, 1e-8, 1e-8])
    converged = False
    iterations = 0
    for iteration in range(1, max_iterations + 1):
        iterations = iteration
        fitted = _sigmoid(x @ coefficients)
        weights = np.clip(fitted * (1 - fitted), 1e-9, None)
        information = x.T @ (x * weights[:, None]) + ridge
        gradient = x.T @ (y - fitted) - ridge @ coefficients
        try:
            step = np.linalg.solve(information, gradient)
        except np.linalg.LinAlgError:
            step = np.linalg.pinv(information) @ gradient
        coefficients += step
        if float(np.max(np.abs(step))) < tolerance:
            converged = True
            break

    fitted = _sigmoid(x @ coefficients)
    weights = np.clip(fitted * (1 - fitted), 1e-9, None)
    bread = np.linalg.pinv(x.T @ (x * weights[:, None]))
    race_ids = clean[race_column].to_numpy()
    meat = np.zeros((3, 3), dtype=float)
    for race_id in np.unique(race_ids):
        locations = race_ids == race_id
        score = x[locations].T @ (y[locations] - fitted[locations])
        meat += np.outer(score, score)
    n_rows = clean.height
    n_races = clean[race_column].n_unique()
    correction = 1.0
    if n_races > 1 and n_rows > x.shape[1]:
        correction = (n_races / (n_races - 1)) * ((n_rows - 1) / (n_rows - x.shape[1]))
    covariance = bread @ meat @ bread * correction
    standard_error = math.sqrt(max(float(covariance[2, 2]), 0.0))
    z_score = float(coefficients[2] / standard_error) if standard_error > 0 else math.inf
    p_value = 0.5 * math.erfc(z_score / math.sqrt(2))
    return IncrementalLogitFit(
        intercept=float(coefficients[0]),
        market_coefficient=float(coefficients[1]),
        model_coefficient=float(coefficients[2]),
        model_standard_error=standard_error,
        model_z_score=z_score,
        model_p_value_one_sided=p_value,
        converged=converged,
        iterations=iterations,
        n_rows=n_rows,
        n_races=n_races,
    )


def apply_incremental_logit(
    frame: pl.DataFrame,
    fit: IncrementalLogitFit,
    *,
    output_column: str = "prob_mixed",
) -> pl.DataFrame:
    linear = (
        fit.intercept
        + fit.market_coefficient * _logit(frame["prob_market"].to_numpy())
        + fit.model_coefficient * _logit(frame["prob_win"].to_numpy())
    )
    raw = _sigmoid(linear)
    normalized = normalize_race_probabilities(
        raw,
        frame["race_id"].to_numpy(),
        target_total=1.0,
    )
    return frame.with_columns(pl.Series(output_column, normalized))


def _bootstrap_summary(values: np.ndarray, *, iterations: int) -> BootstrapSummary:
    return BootstrapSummary(
        median=float(np.median(values)),
        mean=float(np.mean(values)),
        lower_95=float(np.quantile(values, 0.025)),
        upper_95=float(np.quantile(values, 0.975)),
        probability_positive=float(np.mean(values > 0)),
        iterations=iterations,
    )


def bootstrap_log_loss_improvement(
    frame: pl.DataFrame,
    *,
    iterations: int = 1_000,
    seed: int = 20260827,
) -> BootstrapSummary:
    """Race bootstrap of market LL minus mixed LL; positive favors the mix."""
    market = np.clip(frame["prob_market"].to_numpy(), 1e-15, 1 - 1e-15)
    mixed = np.clip(frame["prob_mixed"].to_numpy(), 1e-15, 1 - 1e-15)
    labels = frame["win"].to_numpy()
    market_loss = -(labels * np.log(market) + (1 - labels) * np.log(1 - market))
    mixed_loss = -(labels * np.log(mixed) + (1 - labels) * np.log(1 - mixed))
    per_row_improvement = market_loss - mixed_loss
    races = frame["race_id"].to_numpy()
    unique_races = np.unique(races)
    sums = np.asarray([per_row_improvement[races == race].sum() for race in unique_races])
    counts = np.asarray([(races == race).sum() for race in unique_races], dtype=float)
    rng = np.random.default_rng(seed)
    samples = np.empty(iterations, dtype=float)
    for index in range(iterations):
        draw = rng.integers(0, len(unique_races), size=len(unique_races))
        samples[index] = sums[draw].sum() / counts[draw].sum()
    return _bootstrap_summary(samples, iterations=iterations)


def _max_consecutive_losses(labels: list[int]) -> int:
    longest = current = 0
    for label in labels:
        if label:
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def _bootstrap_roi(
    selected: pl.DataFrame,
    *,
    iterations: int,
    seed: int,
) -> BootstrapSummary:
    per_race = (
        selected.group_by("race_id")
        .agg(pl.col("flat_profit_row").sum().alias("profit"), pl.len().alias("stake"))
        .sort("race_id")
    )
    profits = per_race["profit"].to_numpy()
    stakes = per_race["stake"].cast(pl.Float64).to_numpy()
    rng = np.random.default_rng(seed)
    values = np.empty(iterations, dtype=float)
    for index in range(iterations):
        draw = rng.integers(0, len(profits), size=len(profits))
        values[index] = profits[draw].sum() / stakes[draw].sum()
    return _bootstrap_summary(values, iterations=iterations)


def backtest_win_ev(
    frame: pl.DataFrame,
    *,
    threshold: float,
    probability_column: str = "prob_mixed",
    bootstrap_iterations: int = 0,
    seed: int = 20260827,
) -> BacktestSummary:
    scored = frame.with_columns(
        (pl.col(probability_column) * pl.col("odds") - 1).alias("estimated_ev")
    )
    selected = scored.filter(pl.col("estimated_ev") > threshold).with_columns(
        (pl.col("win") * pl.col("odds") - 1).alias("flat_profit_row"),
        (
            (
                0.25
                * pl.col("estimated_ev")
                / (pl.col("odds") - 1)
            ).clip(0.0, 0.05)
        ).alias("quarter_kelly_stake"),
    ).with_columns(
        (pl.col("quarter_kelly_stake") * pl.col("flat_profit_row")).alias(
            "quarter_kelly_profit_row"
        )
    )
    if selected.height == 0:
        return BacktestSummary(
            threshold=threshold,
            n_bets=0,
            n_races_bet=0,
            hit_rate=0.0,
            flat_profit=0.0,
            flat_roi=0.0,
            max_drawdown_units=0.0,
            max_consecutive_losses=0,
            quarter_kelly_staked=0.0,
            quarter_kelly_profit=0.0,
            quarter_kelly_roi=0.0,
            monthly=[],
            roi_bootstrap=None,
        )
    selected = selected.sort("race_date_local", "race_number", "horse_number")
    profits = selected["flat_profit_row"].to_numpy()
    cumulative = np.cumsum(profits)
    running_peak = np.maximum.accumulate(np.concatenate(([0.0], cumulative)))
    drawdowns = running_peak[1:] - cumulative
    flat_profit = float(profits.sum())
    kelly_staked = float(selected["quarter_kelly_stake"].sum())
    kelly_profit = float(selected["quarter_kelly_profit_row"].sum())
    monthly_frame = (
        selected.with_columns(pl.col("race_date_local").str.slice(0, 7).alias("month"))
        .group_by("month")
        .agg(
            pl.len().alias("bets"),
            pl.col("flat_profit_row").sum().alias("profit"),
        )
        .with_columns((pl.col("profit") / pl.col("bets")).alias("roi"))
        .sort("month")
    )
    return BacktestSummary(
        threshold=threshold,
        n_bets=selected.height,
        n_races_bet=selected["race_id"].n_unique(),
        hit_rate=float(selected["win"].mean()),
        flat_profit=flat_profit,
        flat_roi=flat_profit / selected.height,
        max_drawdown_units=float(drawdowns.max(initial=0.0)),
        max_consecutive_losses=_max_consecutive_losses(selected["win"].to_list()),
        quarter_kelly_staked=kelly_staked,
        quarter_kelly_profit=kelly_profit,
        quarter_kelly_roi=kelly_profit / kelly_staked if kelly_staked > 0 else 0.0,
        monthly=monthly_frame.to_dicts(),
        roi_bootstrap=(
            _bootstrap_roi(selected, iterations=bootstrap_iterations, seed=seed)
            if bootstrap_iterations > 0
            else None
        ),
    )


def select_ev_threshold(
    valid: pl.DataFrame,
    *,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLD_GRID,
    minimum_bets: int = MIN_VALID_BETS,
) -> tuple[float, list[BacktestSummary]]:
    """Choose the highest valid flat ROI subject to a minimum sample size."""
    rows = [backtest_win_ev(valid, threshold=value) for value in thresholds]
    eligible = [row for row in rows if row.n_bets >= minimum_bets]
    if not eligible:
        raise MarketGateInputError(
            f"valid에서 최소 베팅 수 {minimum_bets}를 만족하는 EV 임계값이 없습니다."
        )
    best = max(eligible, key=lambda row: (row.flat_roi, row.n_bets, -row.threshold))
    return best.threshold, rows


def judge_g2(
    *,
    fit: IncrementalLogitFit,
    market_test_log_loss: float,
    mixed_test_log_loss: float,
    log_loss_bootstrap: BootstrapSummary,
    roi_bootstrap: BootstrapSummary | None,
) -> G2Decision:
    criteria = {
        "valid_model_beta_positive_significant": (
            fit.model_coefficient > 0 and fit.model_p_value_one_sided < 0.05
        ),
        "test_mixed_log_loss_below_market": mixed_test_log_loss < market_test_log_loss,
        "test_log_loss_improvement_ci_positive": log_loss_bootstrap.lower_95 > 0,
        "test_flat_roi_bootstrap_median_positive": (
            roi_bootstrap is not None and roi_bootstrap.median > 0
        ),
    }
    core_signal = (
        criteria["valid_model_beta_positive_significant"]
        and criteria["test_mixed_log_loss_below_market"]
    )
    if core_signal and criteria["test_flat_roi_bootstrap_median_positive"]:
        status = "PASS"
    elif core_signal:
        status = "DEFER"
    else:
        status = "FAIL"
    return G2Decision(status=status, criteria=criteria)


def overround_summary(frame: pl.DataFrame) -> dict[str, float]:
    values = (
        frame.select("race_id", "market_overround")
        .unique()
        .get_column("market_overround")
        .to_numpy()
    )
    return {
        "n_races": float(len(values)),
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "p05": float(np.quantile(values, 0.05)),
        "p95": float(np.quantile(values, 0.95)),
    }


def render_g2_report(
    *,
    candidate_run_id: str,
    fit: IncrementalLogitFit,
    valid_market_metrics: dict[str, float],
    valid_mixed_metrics: dict[str, float],
    test_market_metrics: dict[str, float],
    test_mixed_metrics: dict[str, float],
    valid_overround: dict[str, float],
    test_overround: dict[str, float],
    selected_threshold: float,
    threshold_rows: list[BacktestSummary],
    test_backtest: BacktestSummary,
    log_loss_bootstrap: BootstrapSummary,
    decision: G2Decision,
    valid_total_races: int,
    test_total_races: int,
) -> str:
    roi_bootstrap = test_backtest.roi_bootstrap
    lines = [
        "# Gate G2 시장 비교 및 사후 단승 backtest",
        "",
        f"- 고정 후보 run_id: `{candidate_run_id}`",
        f"- 판정: **{decision.status}**",
        "- 혼합계수와 EV 임계값은 valid에서만 정했고 test는 이 실행에서 1회 평가했다.",
        "- 배당은 구매 시점 호가가 아니라 **경주 종료 후 확정배당**이다. 아래 ROI는 실현 가능한 수익성 증거가 아니다.",
        "- ROI는 1단위 정액 베팅의 세전·수수료 반영 후 공식 배당 기준이며 개인 기타소득세는 반영하지 않았다.",
        "",
        "## 시장 배당과 커버리지",
        "",
        "한국마사회 안내상 단승·연승은 베팅액에서 20%를 공제하는 패리뮤추얼 방식이다. "
        "모델에서는 고정 상수를 확률에 다시 적용하지 않고, 실제 확정배당의 overround "
        "`Σ(1/odds)`를 경주별로 측정한 뒤 정규화했다.",
        "",
        "| split | 사용 경주/전체 | overround 평균 | 중앙값 | p05–p95 |",
        "|---|---:|---:|---:|---:|",
        f"| valid | {int(valid_overround['n_races'])}/{valid_total_races} | {valid_overround['mean']:.4f} | {valid_overround['median']:.4f} | {valid_overround['p05']:.4f}–{valid_overround['p95']:.4f} |",
        f"| test | {int(test_overround['n_races'])}/{test_total_races} | {test_overround['mean']:.4f} | {test_overround['median']:.4f} | {test_overround['p05']:.4f}–{test_overround['p95']:.4f} |",
        "",
        "정상 범위를 벗어난 `9999.9` 센티널, 배당 ≤1, 또는 일부 출전마 배당이 없는 경주는 통째로 제외했다.",
        "",
        "## 시장 + 모델 혼합 회귀",
        "",
        "`logit(win) = γ + α·logit(market) + β·logit(model)`을 valid에서 적합했다. "
        "표준오차는 같은 경주 출전마 간 상관을 고려한 경주 cluster-robust 값이다.",
        "",
        f"- γ(intercept) = {fit.intercept:.6f}",
        f"- α(market) = {fit.market_coefficient:.6f}",
        f"- β(model) = **{fit.model_coefficient:.6f}** ± {fit.model_standard_error:.6f}",
        f"- β z = {fit.model_z_score:.3f}, 단측 p = {fit.model_p_value_one_sided:.6g}",
        f"- 수렴={fit.converged}, 반복={fit.iterations}, {fit.n_races}경주/{fit.n_rows}행",
        "",
        "| split | 시장 LL | 혼합 LL | 개선(market−mix) | 시장 AUC | 혼합 AUC |",
        "|---|---:|---:|---:|---:|---:|",
        f"| valid | {valid_market_metrics['log_loss']:.6f} | {valid_mixed_metrics['log_loss']:.6f} | {valid_market_metrics['log_loss'] - valid_mixed_metrics['log_loss']:+.6f} | {valid_market_metrics.get('auc', float('nan')):.4f} | {valid_mixed_metrics.get('auc', float('nan')):.4f} |",
        f"| test | {test_market_metrics['log_loss']:.6f} | {test_mixed_metrics['log_loss']:.6f} | {test_market_metrics['log_loss'] - test_mixed_metrics['log_loss']:+.6f} | {test_market_metrics.get('auc', float('nan')):.4f} | {test_mixed_metrics.get('auc', float('nan')):.4f} |",
        "",
        f"test 경주 bootstrap {log_loss_bootstrap.iterations:,}회 개선량: 중앙값 {log_loss_bootstrap.median:+.6f}, 95% CI [{log_loss_bootstrap.lower_95:+.6f}, {log_loss_bootstrap.upper_95:+.6f}], P(개선>0)={log_loss_bootstrap.probability_positive:.3f}.",
        "",
        "## valid에서 EV 임계값 선택",
        "",
        "EV는 혼합확률 기준 `p_mix × final_odds − 1`이다. 최소 30베팅 조건에서 valid 정액 ROI가 가장 높은 임계값 하나를 고정했다. 표본이 작으므로 test bootstrap 불확실성을 함께 판정한다.",
        "",
        "| θ | bets | races | hit rate | flat ROI |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in threshold_rows:
        selected = " **선택**" if row.threshold == selected_threshold else ""
        lines.append(
            f"| {row.threshold:.2f}{selected} | {row.n_bets} | {row.n_races_bet} | {row.hit_rate:.2%} | {row.flat_roi:+.2%} |"
        )
    lines.extend(
        [
            "",
            "## 고정 전략의 test 1회 결과",
            "",
            f"- θ={selected_threshold:.2f}, 베팅 {test_backtest.n_bets}건 / {test_backtest.n_races_bet}경주",
            f"- 적중률 {test_backtest.hit_rate:.2%}, 정액 손익 {test_backtest.flat_profit:+.2f}단위, ROI **{test_backtest.flat_roi:+.2%}**",
            f"- 최대 낙폭 {test_backtest.max_drawdown_units:.2f}단위, 최장 연속 손실 {test_backtest.max_consecutive_losses}회",
            f"- ¼ Kelly(베팅당 자금 5% cap) 총 stake {test_backtest.quarter_kelly_staked:.3f}, 손익 {test_backtest.quarter_kelly_profit:+.3f}, ROI {test_backtest.quarter_kelly_roi:+.2%}",
        ]
    )
    if roi_bootstrap is not None:
        lines.append(
            f"- test 경주 bootstrap {roi_bootstrap.iterations:,}회 ROI: 중앙값 **{roi_bootstrap.median:+.2%}**, 95% CI [{roi_bootstrap.lower_95:+.2%}, {roi_bootstrap.upper_95:+.2%}], P(ROI>0)={roi_bootstrap.probability_positive:.3f}"
        )
    lines.extend(
        [
            "",
            "### 월별 정액 결과",
            "",
            "| 월 | bets | 손익(단위) | ROI |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in test_backtest.monthly:
        lines.append(
            f"| {row['month']} | {row['bets']} | {row['profit']:+.2f} | {row['roi']:+.2%} |"
        )
    lines.extend(
        [
            "",
            "## Gate G2 판정",
            "",
            "| 조건 | 결과 |",
            "|---|---|",
        ]
    )
    labels = {
        "valid_model_beta_positive_significant": "valid β>0, 단측 p<0.05",
        "test_mixed_log_loss_below_market": "test 혼합 LL < 시장 LL",
        "test_log_loss_improvement_ci_positive": "test LL 개선 bootstrap 95% CI 하한>0 (강한 증거, 참고)",
        "test_flat_roi_bootstrap_median_positive": "test 정액 ROI bootstrap 중앙값>0",
    }
    for key, passed in decision.criteria.items():
        lines.append(f"| {labels[key]} | {'PASS' if passed else 'FAIL'} |")
    lines.extend(
        [
            "",
            "G2 명시 기준은 β의 양(+) 유의성과 test 정액 ROI bootstrap 중앙값이다. "
            "시장 대비 예측 신호는 있으나 ROI 조건이 불확실하면 DEFER로 둔다.",
            "",
            "복승은 두 말의 공동입상 확률과 조합별 배당이 필요하므로 현재의 독립 이진확률로 "
            "억지 근사하지 않았다. conditional logit/Plackett–Luce 등 경주 순위모형을 만든 뒤 별도 검증한다.",
            "",
            "실전 판단은 구매 직전 배당 snapshot으로 같은 규칙을 사전 고정한 paper trading(G3)을 "
            "거쳐야 한다. 확정배당 backtest는 마감 직전 배당 변동과 주문 충격을 재현하지 못한다.",
            "",
            "공식 근거: [한국마사회 건전경마 안내](https://board.kra.co.kr/down/KRAFile_per_BoardNo/1250/20210527132436227737.pdf), "
            "[한국마사회 2024 지속가능경영보고서](https://www.kra.co.kr/cms/contents/kr/resource/pdf/report/2024_esgSustainabilityReport.pdf)",
            "",
        ]
    )
    return "\n".join(lines)


def evaluate_market_and_mix(frame: pl.DataFrame) -> tuple[dict[str, float], dict[str, float]]:
    return (
        evaluate_probabilities(frame, "prob_market", label_column="win"),
        evaluate_probabilities(frame, "prob_mixed", label_column="win"),
    )
