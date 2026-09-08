import polars as pl
import pytest

from horse_racing.analysis.race_portfolio import (
    RacePortfolioInputError,
    attach_final_odds,
    backtest_fixed_rank_ticket,
    build_ticket_candidates,
    optimize_race_portfolio,
)


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": [1, 1, 1, 1],
            "race_date_local": ["2026-01-01"] * 4,
            "race_number": [1] * 4,
            "meet_code": [3] * 4,
            "distance_m": [1200] * 4,
            "horse_number": [1, 2, 3, 4],
            "starters": [4] * 4,
            "finish_position": [1, 2, 3, 4],
        }
    )


def _predictions() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": [1, 1, 1, 1],
            "horse_number": [1, 2, 3, 4],
            "prob_win": [0.5, 0.3, 0.15, 0.05],
        }
    )


def test_ticket_candidates_are_coherent_and_settle_supported_pools() -> None:
    tickets = build_ticket_candidates(_frame(), _predictions())

    assert tickets.filter(pl.col("bet_type") == "WIN")["ticket_probability"].sum() == pytest.approx(
        1.0
    )
    assert tickets.filter(pl.col("bet_type") == "PLC")["ticket_probability"].sum() == pytest.approx(
        2.0
    )
    assert tickets.filter(pl.col("bet_type") == "QPL")["ticket_probability"].sum() == pytest.approx(
        1.0
    )
    assert tickets.filter(pl.col("bet_type") == "EXA")["ticket_probability"].sum() == pytest.approx(
        1.0
    )
    assert tickets.filter(pl.col("bet_type") == "TLA")["ticket_probability"].sum() == pytest.approx(
        1.0
    )

    winners = {
        (row["bet_type"], row["selection_key"])
        for row in tickets.filter(pl.col("won") == 1).select(
            "bet_type", "selection_key"
        ).iter_rows(named=True)
    }
    assert ("WIN", "1") in winners
    assert ("PLC", "1") in winners
    assert ("PLC", "2") in winners
    assert ("QPL", "1-2") in winners
    assert ("EXA", "1-2") in winners
    assert ("TLA", "1-2-3") in winners


def test_attach_final_odds_rejects_sentinel() -> None:
    tickets = build_ticket_candidates(
        _frame(), _predictions(), pools=("WIN",)
    )
    odds = tickets.select("race_id", "bet_type", "selection_key").with_columns(
        pl.Series("odds", [2.0, 3.0, 9_999.9, 10.0])
    )
    joined = attach_final_odds(tickets, odds)

    assert joined.filter(pl.col("selection_key") == "1")["valid_odds"].item()
    assert not joined.filter(pl.col("selection_key") == "3")["valid_odds"].item()


def test_optimizer_prefers_higher_non_loss_probability() -> None:
    predictions = _predictions().head(3).with_columns(
        (pl.col("prob_win") / pl.col("prob_win").sum()).alias("prob_win")
    )
    tickets = pl.DataFrame(
        {
            "race_id": [1, 1],
            "bet_type": ["PLC", "WIN"],
            "selection_key": ["1", "1"],
            "ticket_probability_calibrated": [0.90, 0.60],
            "predicted_odds_lower": [1.30, 2.00],
            "predicted_odds_median": [1.40, 2.20],
            "conservative_return_multiplier": [1.17, 1.20],
            "place_slots": [2, 2],
        }
    )

    result = optimize_race_portfolio(
        predictions,
        tickets,
        budget_units=10,
        max_tickets=1,
        minimum_expected_return=1.05,
        minimum_non_loss_probability=0.10,
    )

    assert len(result.lines) == 1
    assert result.lines[0].bet_type == "PLC"
    assert result.lines[0].stake_units == 10
    assert result.probability_non_loss > 0.8


def test_optimizer_passes_low_probability_longshot() -> None:
    predictions = _predictions().head(3).with_columns(
        (pl.col("prob_win") / pl.col("prob_win").sum()).alias("prob_win")
    )
    tickets = pl.DataFrame(
        {
            "race_id": [1],
            "bet_type": ["WIN"],
            "selection_key": ["3"],
            "ticket_probability_calibrated": [0.03],
            "predicted_odds_lower": [40.0],
            "predicted_odds_median": [60.0],
            "conservative_return_multiplier": [1.20],
            "place_slots": [2],
        }
    )

    result = optimize_race_portfolio(
        predictions,
        tickets,
        budget_units=10,
        max_tickets=1,
        minimum_expected_return=1.0,
        minimum_ticket_probability=0.05,
        minimum_non_loss_probability=0.10,
    )

    assert result.lines == ()
    assert result.stake_units == 0


def test_fixed_rank_ticket_uses_model_rank_and_actual_settlement() -> None:
    tickets = build_ticket_candidates(_frame(), _predictions(), pools=("WIN", "PLC"))
    odds = tickets.select("race_id", "bet_type", "selection_key").with_columns(
        pl.lit(2.0).alias("odds")
    )
    scored = attach_final_odds(tickets, odds)

    result = backtest_fixed_rank_ticket(
        scored,
        bet_type="WIN",
        model_ranks=(1,),
        start_date="2026-01-01",
        end_date="2026-01-01",
    )

    assert result.races == 1
    assert result.hits == 1
    assert result.roi == pytest.approx(2.0)


def test_unknown_pool_is_rejected() -> None:
    with pytest.raises(RacePortfolioInputError, match="지원하지 않는 승식"):
        build_ticket_candidates(_frame(), _predictions(), pools=("UNKNOWN",))
