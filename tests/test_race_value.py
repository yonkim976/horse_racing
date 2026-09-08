import polars as pl
import pytest

from horse_racing.analysis.race_value import (
    backtest_sleeper_strategy,
    build_historical_sleeper_frame,
    select_sleeper_candidates,
)


def test_historical_frame_labels_market_longshot_top3() -> None:
    dataset = pl.DataFrame(
        {
            "race_id": [1] * 4,
            "race_entry_id": [11, 12, 13, 14],
            "race_date_local": ["2026-01-01"] * 4,
            "horse_number": [1, 2, 3, 4],
            "finish_position": [1, 2, 4, 3],
        }
    )
    predictions = pl.DataFrame(
        {
            "race_id": [1] * 4,
            "race_entry_id": [11, 12, 13, 14],
            "horse_number": [1, 2, 3, 4],
            "prob_win": [0.4, 0.3, 0.2, 0.1],
            "prob_top2": [0.7, 0.6, 0.4, 0.3],
            "prob_top3": [0.9, 0.8, 0.7, 0.6],
            "rank_score": [4.0, 3.0, 2.0, 1.0],
        }
    )
    ticket_rows = []
    for horse_number, odds, place_won in (
        (1, 2.0, 1),
        (2, 3.0, 1),
        (3, 5.0, 0),
        (4, 10.0, 1),
    ):
        for pool in ("WIN", "PLC"):
            ticket_rows.append(
                {
                    "race_id": 1,
                    "bet_type": pool,
                    "selection_key": str(horse_number),
                    "actual_odds": odds,
                    "valid_odds": True,
                    "won": place_won if pool == "PLC" else int(horse_number == 1),
                    "predicted_odds_lower": odds * 0.8,
                    "predicted_odds_median": odds,
                }
            )

    frame = build_historical_sleeper_frame(
        dataset, predictions, pl.DataFrame(ticket_rows)
    )

    sleeper = frame.filter(pl.col("horse_number") == 4).row(0, named=True)
    assert sleeper["actual_market_rank"] == 4
    assert sleeper["model_rank"] == 4
    assert sleeper["sleeper_top3"] == 1


def test_select_sleeper_candidate_uses_probability_and_rank_guard() -> None:
    frame = pl.DataFrame(
        {
            "race_id": [1, 1, 1],
            "race_date_local": ["2026-01-01"] * 3,
            "model_rank": [2, 3, 4],
            "sleeper_probability": [0.9, 0.3, 0.4],
            "prob_top3": [0.9, 0.3, 0.4],
            "predicted_market_win_odds": [1.5, 3.0, 4.0],
            "predicted_market_rank": [1, 3, 4],
        }
    )

    selected = select_sleeper_candidates(frame)

    assert selected.height == 1
    assert selected["model_rank"][0] == 4


def test_sleeper_backtest_uses_unit_stake_and_actual_odds() -> None:
    settled = pl.DataFrame(
        {
            "race_date_local": ["2026-01-01", "2026-01-02"],
            "race_number": [1, 1],
            "meet_code": [1, 1],
            "sleeper_top3": [1, 0],
            "qpl_won": [1, 0],
            "qpl_odds": [4.0, 10.0],
        }
    )

    result = backtest_sleeper_strategy(settled, bet_type="QPL")

    assert result.races == 2
    assert result.hit_rate == pytest.approx(0.5)
    assert result.average_winning_odds == pytest.approx(4.0)
    assert result.roi == pytest.approx(2.0)
