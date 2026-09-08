from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.features.energy import add_features
from horse_racing.analysis.features.state import add_features as add_state_features


def _past_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    start = date(2026, 1, 1)
    entry_id = 0
    for race_id, day in ((1, start), (2, start + timedelta(days=14))):
        for horse_id in (10, 20, 30):
            entry_id += 1
            rows.append(
                {
                    "horse_id": horse_id,
                    "race_id": race_id,
                    "race_entry_id": entry_id,
                    "race_date": day,
                    "distance_m": 1200,
                }
            )
    rows.append(
        {
            "horse_id": 10,
            "race_id": 3,
            "race_entry_id": 100,
            "race_date": start + timedelta(days=28),
            "distance_m": 1200,
        }
    )
    return rows


def _sections(*, include_current: bool = False) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    start = date(2026, 1, 1)
    for race_id, day in ((1, start), (2, start + timedelta(days=14))):
        for horse_id, offset in ((10, -500), (20, 0), (30, 500)):
            for code, base in (("S1F", 14_000), ("G3F", 41_000), ("G1F", 14_000)):
                rows.append(
                    {
                        "horse_id": horse_id,
                        "race_id": race_id,
                        "race_date": day,
                        "section_code": code,
                        "elapsed_time_ms": base + offset,
                    }
                )
    if include_current:
        for horse_id, offset in ((10, 5_000), (20, 0), (30, -5_000)):
            for code, base in (("S1F", 14_000), ("G3F", 41_000), ("G1F", 14_000)):
                rows.append(
                    {
                        "horse_id": horse_id,
                        "race_id": 3,
                        "race_date": start + timedelta(days=28),
                        "section_code": code,
                        "elapsed_time_ms": base + offset,
                    }
                )
    return pl.DataFrame(rows)


def test_energy_features_use_only_prior_relative_section_times() -> None:
    past = pl.DataFrame(_past_rows())
    frame = past.filter(pl.col("race_entry_id") == 100)
    base = add_features(frame, SourceFrames(past_results=past, sections=_sections()))
    with_current = add_features(
        frame,
        SourceFrames(past_results=past, sections=_sections(include_current=True)),
    )
    row = base.row(0, named=True)

    assert row["energy_profile_count5"] == 2
    assert row["energy_early_rel_avg5"] > 0
    assert row["energy_finish_rel_avg5"] > 0
    assert row["energy_exact_distance_balance_avg5"] == pytest.approx(0.0)
    assert with_current.select(base.columns).equals(base)


def test_condition_state_combines_recent_change_and_uncertainty() -> None:
    frame = pl.DataFrame(
        {
            "speed_figure_avg3": [2.0, None],
            "speed_figure_median5": [0.0, None],
            "speed_figure_count5": [5, 0],
            "form_recent3_pct": [0.2, None],
            "form_recent5_pct": [0.5, None],
            "ability_elo_uncertainty": [0.2, 1.0],
            "is_debut": [0, 1],
            "long_layoff": [0, 1],
            "body_weight_dev": [4.0, None],
            "body_weight_std5": [2.0, None],
        }
    )
    result = add_state_features(frame, SourceFrames())

    assert result["condition_state"][0] > 0
    assert result["condition_evidence"].to_list() == [1.0, 0.0]
    assert result["condition_uncertainty"][0] < result["condition_uncertainty"][1]
    assert result["condition_weight_z"][0] == pytest.approx(2.0)
