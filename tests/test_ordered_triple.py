from __future__ import annotations

import polars as pl
import pytest

from horse_racing.analysis.ordered_triple import (
    OrderedTripleInputError,
    backtest_ordered_triple_value,
    ordered_winner_keys,
    plackett_luce_ordered_triples,
    prepare_ordered_triple_value,
)


def _predictions() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_id": [1, 1, 1, 1],
            "horse_number": [1, 2, 3, 4],
            "prob_win": [0.4, 0.3, 0.2, 0.1],
        }
    )


def test_plackett_luce_generates_24_ordered_combinations() -> None:
    result = plackett_luce_ordered_triples(_predictions(), top_n=4)

    assert result.height == 24
    assert result["selection_key"].n_unique() == 24
    assert result["combo_probability"].sum() == pytest.approx(1.0)
    assert result["box_probability"].unique().to_list() == pytest.approx([1.0])
    expected = 0.4 * (0.3 / 0.6) * (0.2 / 0.3)
    actual = result.filter(pl.col("selection_key") == "1-2-3")[
        "combo_probability"
    ].item()
    assert actual == pytest.approx(expected)


def test_plackett_luce_rejects_too_few_horses() -> None:
    with pytest.raises(OrderedTripleInputError, match="만들 수 없습니다"):
        plackett_luce_ordered_triples(_predictions().head(3), top_n=4)


def test_ordered_winner_keys_expands_dead_heat_at_third() -> None:
    frame = pl.DataFrame(
        {
            "race_id": [1, 1, 1, 1, 1],
            "horse_number": [1, 2, 3, 4, 5],
            "finish_position": [1, 2, 3, 3, 5],
        }
    )

    result = ordered_winner_keys(frame)

    assert set(result["selection_key"].to_list()) == {"1-2-3", "1-2-4"}


def test_value_backtest_selects_only_positive_ev_combinations() -> None:
    frame = pl.DataFrame(
        {
            "race_id": [1, 1, 1, 1],
            "race_entry_id": [11, 12, 13, 14],
            "horse_number": [1, 2, 3, 4],
            "finish_position": [1, 2, 3, 4],
            "race_date_local": ["2026-04-01"] * 4,
            "race_number": [1] * 4,
        }
    )
    combinations = plackett_luce_ordered_triples(_predictions(), top_n=4)
    probabilities = dict(
        zip(
            combinations["selection_key"].to_list(),
            combinations["combo_probability"].to_list(),
            strict=True,
        )
    )
    odds = pl.DataFrame(
        {
            "race_id": [1] * 24,
            "selection_key": combinations["selection_key"],
            "odds": [
                2.0 / probabilities[key]
                if key == "1-2-3"
                else 0.5 / probabilities[key]
                for key in combinations["selection_key"].to_list()
            ],
        }
    )
    scored = prepare_ordered_triple_value(frame, _predictions(), odds, top_n=4)

    result = backtest_ordered_triple_value(
        scored,
        threshold=0.0,
        bootstrap_iterations=100,
        seed=3,
    )

    assert result.n_bets == 1
    assert result.n_races_bet == 1
    assert result.winning_tickets == 1
    assert result.flat_roi > 0
    assert result.roi_bootstrap is not None
    assert result.roi_bootstrap.probability_positive == 1.0
