from __future__ import annotations

import polars as pl
import pytest

from horse_racing.analysis.model_ensemble import average_predictions


def _prediction(win: list[float], top2: list[float] | None = None) -> pl.DataFrame:
    frame = pl.DataFrame(
        {
            "race_id": [1, 1],
            "race_entry_id": [10, 11],
            "horse_number": [1, 2],
            "prob_win": win,
        }
    )
    if top2 is not None:
        frame = frame.with_columns(pl.Series("prob_top2", top2))
    return frame


def test_target_specific_weights_allow_win_only_ranking_member() -> None:
    full = _prediction([0.6, 0.4], [0.8, 0.2])
    ranking = _prediction([0.8, 0.2])
    result = average_predictions(
        [full, ranking],
        targets=["win", "top2"],
        target_member_weights={"win": [0.75, 0.25], "top2": [1.0, 0.0]},
    )

    assert result["prob_win"].to_list() == pytest.approx([0.65, 0.35])
    assert result["prob_top2"].to_list() == pytest.approx([0.8, 0.2])


def test_top5_ensemble_preserves_exact_rank_probabilities() -> None:
    keys = {
        "race_id": [1, 1],
        "race_entry_id": [10, 11],
        "horse_number": [1, 2],
    }
    first = pl.DataFrame(
        {
            **keys,
            "prob_win": [0.6, 0.4],
            "prob_top2": [1.0, 1.0],
            "prob_top3": [1.0, 1.0],
            "prob_top4": [1.0, 1.0],
            "prob_top5": [1.0, 1.0],
        }
    )
    second = first.with_columns(pl.Series("prob_win", [0.4, 0.6]))
    weights = {label: [1.0, 1.0] for label in ("win", "top2", "top3", "top4", "top5")}

    result = average_predictions(
        [first, second],
        targets=["win", "top2", "top3", "top4", "top5"],
        target_member_weights=weights,
    )

    assert result["prob_rank1"].to_list() == pytest.approx([0.5, 0.5])
    assert result["prob_rank2"].to_list() == pytest.approx([0.5, 0.5])
    assert result["prob_rank3"].to_list() == pytest.approx([0.0, 0.0])


def test_top5_ensemble_rejects_different_rank_weights() -> None:
    full = pl.DataFrame(
        {
            "race_id": [1, 1],
            "race_entry_id": [10, 11],
            "horse_number": [1, 2],
            "prob_win": [0.6, 0.4],
            "prob_top2": [1.0, 1.0],
            "prob_top3": [1.0, 1.0],
            "prob_top4": [1.0, 1.0],
            "prob_top5": [1.0, 1.0],
        }
    )
    weights = {label: [1.0, 1.0] for label in ("win", "top2", "top3", "top4", "top5")}
    weights["top5"] = [3.0, 1.0]

    with pytest.raises(ValueError, match="동일한 member weight"):
        average_predictions(
            [full, full],
            targets=["win", "top2", "top3", "top4", "top5"],
            target_member_weights=weights,
        )
