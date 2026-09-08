from __future__ import annotations

from datetime import date

import polars as pl

from horse_racing.analysis.features.ability import FEATURES, add_features
from horse_racing.analysis.features.base import SourceFrames


def _past(current_winner: int = 1) -> pl.DataFrame:
    rows = []
    entry_id = 0
    for race_id, race_date, winner in (
        (1, date(2025, 1, 1), 1),
        (2, date(2025, 2, 1), current_winner),
    ):
        for horse_id in range(1, 5):
            entry_id += 1
            order = [winner] + [item for item in range(1, 5) if item != winner]
            rows.append(
                {
                    "race_entry_id": entry_id,
                    "race_id": race_id,
                    "horse_id": horse_id,
                    "race_date": race_date,
                    "meet_code": 1,
                    "distance_m": 1200,
                    "finish_position": order.index(horse_id) + 1,
                }
            )
    return pl.DataFrame(rows)


def _base(past: pl.DataFrame) -> pl.DataFrame:
    return past.select(
        "race_entry_id",
        "race_id",
        "horse_id",
        "race_date",
        "meet_code",
        "distance_m",
    )


def test_ability_feature_contract() -> None:
    assert [spec.name for spec in FEATURES] == [
        "ability_elo_global",
        "ability_elo_global_starts",
        "ability_elo_context",
        "ability_elo_context_starts",
        "ability_elo_vs_field",
        "ability_elo_uncertainty",
    ]


def test_winner_rating_increases_before_next_race() -> None:
    past = _past()
    result = add_features(_base(past), SourceFrames(past_results=past))
    first = result.filter(pl.col("race_id") == 1)
    second = result.filter(pl.col("race_id") == 2)

    assert first["ability_elo_global"].to_list() == [1500.0] * 4
    assert second.filter(pl.col("horse_id") == 1)["ability_elo_global"].item() > 1500
    assert second.filter(pl.col("horse_id") == 4)["ability_elo_global"].item() < 1500
    assert second["ability_elo_global_starts"].to_list() == [1] * 4


def test_current_finish_does_not_change_pre_race_rating() -> None:
    past_a = _past(current_winner=1)
    past_b = _past(current_winner=4)
    result_a = add_features(_base(past_a), SourceFrames(past_results=past_a))
    result_b = add_features(_base(past_b), SourceFrames(past_results=past_b))
    current_a = result_a.filter(pl.col("race_id") == 2).sort("horse_id")
    current_b = result_b.filter(pl.col("race_id") == 2).sort("horse_id")

    assert current_a["ability_elo_global"].to_list() == current_b[
        "ability_elo_global"
    ].to_list()
