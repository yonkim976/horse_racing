from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from horse_racing.analysis.features import feature_names
from horse_racing.analysis.prediction_frame import (
    PredictionFrameError,
    build_prediction_frame,
    cohere_prediction_probabilities,
    validate_prediction_timing,
)
from horse_racing.db.base import Base
from horse_racing.db.models import Horse, Race, Racecourse, RaceEntry, RaceResult

SCHEDULED_AT_MS = 2_000_000_000_000


def _session(tmp_path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'prediction-frame.sqlite3'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    course = Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울")
    past_race = Race(
        racecourse=course,
        race_date_local=date(2033, 5, 19),
        race_number=1,
        distance_m=1200,
        grade="국6등급",
        scheduled_at_ms=SCHEDULED_AT_MS - 86_400_000,
        status="completed",
    )
    future_race = Race(
        racecourse=course,
        race_date_local=date(2033, 5, 20),
        race_number=1,
        distance_m=1200,
        grade="국6등급",
        scheduled_at_ms=SCHEDULED_AT_MS,
        status="scheduled",
    )
    for horse_number in range(1, 6):
        horse = Horse(
            kra_horse_id=f"future-{horse_number}",
            name_ko=f"미래마{horse_number}",
            birth_date=date(2030, 1, 1),
            sex="수",
            origin_country="한국",
        )
        past_entry = RaceEntry(
            race=past_race,
            horse=horse,
            horse_number=horse_number,
            carried_weight_kg=54.0,
            body_weight_kg=470 + horse_number,
        )
        future_entry = RaceEntry(
            race=future_race,
            horse=horse,
            horse_number=horse_number,
            carried_weight_kg=55.0,
            body_weight_kg=475 + horse_number,
        )
        session.add_all(
            [
                past_entry,
                future_entry,
                RaceResult(race_entry=past_entry, finish_position=horse_number),
            ]
        )
    session.add_all([past_race, future_race])
    session.commit()
    return session


def test_build_prediction_frame_uses_null_result_anchors(tmp_path) -> None:
    session = _session(tmp_path)
    try:
        expected = feature_names()
        result = build_prediction_frame(
            session,
            race_date="20330520",
            as_of_policy="start_minus_30m",
            expected_feature_names=expected,
        )
    finally:
        session.close()

    assert result.frame.height == 5
    assert result.feature_names == expected
    assert result.frame["career_starts"].to_list() == [1] * 5
    assert result.frame["finish_pos_last"].to_list() == [1, 2, 3, 4, 5]
    assert set(("win", "top2", "top3", "finish_position", "result_id")).isdisjoint(
        result.frame.columns
    )


def test_build_prediction_frame_blocks_feature_contract_drift(tmp_path) -> None:
    session = _session(tmp_path)
    try:
        with pytest.raises(PredictionFrameError, match="열/순서"):
            build_prediction_frame(
                session,
                race_date="20330520",
                as_of_policy="start_minus_30m",
                expected_feature_names=list(reversed(feature_names())),
            )
    finally:
        session.close()


def test_build_prediction_frame_allows_ordered_profile_subset(tmp_path) -> None:
    session = _session(tmp_path)
    expected = feature_names()[::2]
    try:
        result = build_prediction_frame(
            session,
            race_date="20330520",
            as_of_policy="start_minus_30m",
            expected_feature_names=expected,
        )
    finally:
        session.close()

    assert result.feature_names == expected
    assert all(name in result.frame.columns for name in expected)


def test_build_prediction_frame_infers_racefit_feature_set(tmp_path) -> None:
    session = _session(tmp_path)
    expected = [
        name
        for name in feature_names(feature_set="racefit_history")
        if name != "condition_weight_z"
    ]
    try:
        result = build_prediction_frame(
            session,
            race_date="20330520",
            as_of_policy="start_minus_30m",
            expected_feature_names=expected,
        )
    finally:
        session.close()

    assert result.feature_names == expected
    assert "energy_profile_count5" in result.frame.columns


def test_live_timing_uses_model_as_of_not_race_start(tmp_path) -> None:
    session = _session(tmp_path)
    try:
        result = build_prediction_frame(
            session,
            race_date="20330520",
            as_of_policy="start_minus_30m",
            expected_feature_names=feature_names(),
        )
    finally:
        session.close()

    validate_prediction_timing(result.frame, at_ms=SCHEDULED_AT_MS - 30 * 60 * 1000)
    with pytest.raises(PredictionFrameError, match="as-of"):
        validate_prediction_timing(
            result.frame,
            at_ms=SCHEDULED_AT_MS - 30 * 60 * 1000 + 1,
        )


def test_probability_projection_preserves_totals_and_nested_order() -> None:
    predictions = pl.DataFrame(
        {
            "race_id": [1] * 5,
            "race_entry_id": [1, 2, 3, 4, 5],
            "horse_number": [1, 2, 3, 4, 5],
            "prob_win": [0.4, 0.25, 0.15, 0.1, 0.1],
            "prob_top2": [0.35, 0.5, 0.45, 0.4, 0.3],
            "prob_top3": [0.8, 0.7, 0.6, 0.5, 0.4],
        }
    )
    coherent = cohere_prediction_probabilities(predictions)
    values = coherent.select("prob_win", "prob_top2", "prob_top3").to_numpy()

    assert np.all(values[:, 0] <= values[:, 1] + 1e-10)
    assert np.all(values[:, 1] <= values[:, 2] + 1e-10)
    assert np.allclose(values.sum(axis=0), [1.0, 2.0, 3.0], atol=1e-8)
    assert np.all((values >= 0) & (values <= 1))
