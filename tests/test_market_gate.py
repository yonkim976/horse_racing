from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from horse_racing.analysis.market_gate import (
    BootstrapSummary,
    IncrementalLogitFit,
    apply_incremental_logit,
    backtest_win_ev,
    bootstrap_log_loss_improvement,
    fit_incremental_logit,
    judge_g2,
    prepare_market_comparison,
    select_ev_threshold,
)


def _source_frames() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    frame = pl.DataFrame(
        {
            "race_id": [1, 1, 1, 2, 2, 2],
            "race_entry_id": [11, 12, 13, 21, 22, 23],
            "horse_number": [1, 2, 3, 1, 2, 3],
            "race_date_local": ["2026-04-01"] * 3 + ["2026-04-02"] * 3,
            "race_number": [1, 1, 1, 2, 2, 2],
            "win": [1, 0, 0, 0, 1, 0],
        }
    )
    predictions = frame.select("race_id", "race_entry_id", "horse_number").with_columns(
        pl.Series("prob_win", [0.5, 0.3, 0.2, 0.2, 0.5, 0.3])
    )
    odds = frame.select("race_id", "horse_number").with_columns(
        pl.Series("odds", [2.4, 4.0, 6.0, 5.0, 2.5, 4.0])
    )
    return frame, predictions, odds


def test_prepare_market_comparison_normalizes_and_excludes_sentinel_race() -> None:
    frame, predictions, odds = _source_frames()
    odds = odds.with_columns(
        pl.when((pl.col("race_id") == 2) & (pl.col("horse_number") == 3))
        .then(9999.9)
        .otherwise(pl.col("odds"))
        .alias("odds")
    )

    result = prepare_market_comparison(frame, predictions, odds)

    assert result["race_id"].unique().to_list() == [1]
    assert result["prob_market"].sum() == pytest.approx(1.0)
    assert result["market_overround"].first() == pytest.approx(1 / 2.4 + 1 / 4 + 1 / 6)


def _incremental_signal_frame(n_races: int = 800) -> pl.DataFrame:
    rng = np.random.default_rng(9)
    rows = []
    for race_id in range(n_races):
        market_score = rng.normal(size=6)
        extra_score = rng.normal(size=6)
        market = np.exp(market_score)
        market /= market.sum()
        model = np.exp(0.4 * market_score + extra_score)
        model /= model.sum()
        true = market**0.9 * model**0.7
        true /= true.sum()
        winner = int(rng.choice(6, p=true))
        for index in range(6):
            rows.append(
                {
                    "race_id": race_id,
                    "prob_market": market[index],
                    "prob_win": model[index],
                    "win": int(index == winner),
                }
            )
    return pl.DataFrame(rows)


def test_incremental_logit_recovers_positive_model_signal_and_normalizes() -> None:
    frame = _incremental_signal_frame()

    fit = fit_incremental_logit(frame)
    scored = apply_incremental_logit(frame, fit)

    assert fit.converged is True
    assert fit.model_coefficient > 0
    assert fit.model_p_value_one_sided < 0.05
    totals = scored.group_by("race_id").agg(pl.col("prob_mixed").sum())["prob_mixed"]
    assert totals.to_list() == pytest.approx([1.0] * totals.len())


def test_log_loss_bootstrap_is_positive_when_mix_is_better() -> None:
    frame = pl.DataFrame(
        {
            "race_id": np.repeat(np.arange(50), 2),
            "win": [1, 0] * 50,
            "prob_market": [0.55, 0.45] * 50,
            "prob_mixed": [0.75, 0.25] * 50,
        }
    )

    result = bootstrap_log_loss_improvement(frame, iterations=200, seed=4)

    assert result.lower_95 > 0
    assert result.probability_positive == 1.0


def _backtest_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": [1, 2, 3, 4],
            "horse_number": [1, 1, 1, 1],
            "race_date_local": ["2026-06-01", "2026-06-02", "2026-07-01", "2026-07-02"],
            "race_number": [1, 1, 1, 1],
            "win": [0, 0, 1, 1],
            "odds": [3.0, 3.0, 3.0, 3.0],
            "prob_mixed": [0.5, 0.5, 0.5, 0.5],
        }
    )


def test_backtest_reports_roi_drawdown_streak_months_and_bootstrap() -> None:
    result = backtest_win_ev(
        _backtest_frame(), threshold=0.1, bootstrap_iterations=200, seed=2
    )

    assert result.n_bets == 4
    assert result.flat_profit == pytest.approx(2.0)
    assert result.flat_roi == pytest.approx(0.5)
    assert result.max_drawdown_units == pytest.approx(2.0)
    assert result.max_consecutive_losses == 2
    assert len(result.monthly) == 2
    assert result.roi_bootstrap is not None
    assert result.roi_bootstrap.median > 0


def test_select_threshold_obeys_minimum_bets() -> None:
    frame = _backtest_frame()

    threshold, rows = select_ev_threshold(
        frame,
        thresholds=(0.1, 0.6),
        minimum_bets=2,
    )

    assert threshold == 0.1
    assert [row.n_bets for row in rows] == [4, 0]


def _fit(beta: float, p_value: float) -> IncrementalLogitFit:
    return IncrementalLogitFit(
        intercept=0.0,
        market_coefficient=1.0,
        model_coefficient=beta,
        model_standard_error=0.1,
        model_z_score=beta / 0.1,
        model_p_value_one_sided=p_value,
        converged=True,
        iterations=5,
        n_rows=100,
        n_races=20,
    )


def _bootstrap(median: float, lower: float = -0.1) -> BootstrapSummary:
    return BootstrapSummary(
        median=median,
        mean=median,
        lower_95=lower,
        upper_95=0.2,
        probability_positive=0.7,
        iterations=1_000,
    )


def test_judge_g2_pass_defer_and_fail() -> None:
    passed = judge_g2(
        fit=_fit(0.3, 0.01),
        market_test_log_loss=0.25,
        mixed_test_log_loss=0.24,
        log_loss_bootstrap=_bootstrap(0.01, 0.001),
        roi_bootstrap=_bootstrap(0.05),
    )
    deferred = judge_g2(
        fit=_fit(0.3, 0.01),
        market_test_log_loss=0.25,
        mixed_test_log_loss=0.24,
        log_loss_bootstrap=_bootstrap(0.01),
        roi_bootstrap=_bootstrap(-0.02),
    )
    failed = judge_g2(
        fit=_fit(-0.1, 0.8),
        market_test_log_loss=0.25,
        mixed_test_log_loss=0.26,
        log_loss_bootstrap=_bootstrap(-0.01),
        roi_bootstrap=_bootstrap(0.05),
    )

    assert passed.status == "PASS"
    assert deferred.status == "DEFER"
    assert failed.status == "FAIL"
