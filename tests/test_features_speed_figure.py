from __future__ import annotations

import math
from datetime import date, timedelta

import polars as pl
import pytest

from horse_racing.analysis.features.base import SourceFrames
from horse_racing.analysis.features.speed_figure import FEATURES, add_features


def _finish_ms(distance_m: int, speed: float) -> int:
    return int(round(distance_m * 1000.0 / speed))


def _race_rows(
    *,
    race_id: int,
    race_date: date,
    speed: float,
    going: str = "건조",
    meet_code: int = 1,
    distance_m: int = 1200,
    target_horse_id: int | None = None,
    target_position: int = 1,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for position in range(1, 11):
        horse_id = (
            target_horse_id
            if target_horse_id is not None and position == target_position
            else race_id * 100 + position
        )
        # Keep the top three median exactly at ``speed`` and make the rest a
        # little slower without leaving the physical range.
        row_speed = speed if position <= 3 else speed * (1.0 - 0.005 * position)
        rows.append(
            {
                "horse_id": horse_id,
                "jockey_id": 1,
                "trainer_id": 1,
                "race_entry_id": race_id * 1000 + position,
                "race_id": race_id,
                "meet_code": meet_code,
                "race_date": race_date,
                "distance_m": distance_m,
                "track_condition": going,
                "track_moisture_percent": 3.0,
                "body_weight_kg": 480,
                "finish_position": position,
                "finish_time_ms": _finish_ms(distance_m, row_speed),
                "starters": 10,
            }
        )
    return rows


def _anchor(
    *, race_id: int, race_date: date, horse_id: int, distance_m: int = 1200
) -> dict[str, object]:
    return {
        "horse_id": horse_id,
        "jockey_id": 1,
        "trainer_id": 1,
        "race_entry_id": race_id * 1000 + 1,
        "race_id": race_id,
        "meet_code": 1,
        "race_date": race_date,
        "distance_m": distance_m,
        "track_condition": None,
        "track_moisture_percent": None,
        "body_weight_kg": 480,
        "finish_position": None,
        "finish_time_ms": None,
        "starters": 10,
    }


def _frame_for_entry(row: dict[str, object]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "race_entry_id": [row["race_entry_id"]],
            "race_id": [row["race_id"]],
            "horse_id": [row["horse_id"]],
            "race_date": [row["race_date"]],
            "distance_m": [row["distance_m"]],
        }
    )


def test_speed_figure_uses_prior_course_distance_going_par() -> None:
    rows: list[dict[str, object]] = []
    start = date(2024, 1, 1)
    for index in range(12):
        rows.extend(
            _race_rows(
                race_id=index + 1,
                race_date=start + timedelta(days=index * 7),
                speed=15.0,
                going="건조",
            )
        )
    # Same distance but wet races are materially slower.  The wet par must be
    # learned separately instead of comparing this horse with the dry par.
    for index in range(12):
        rows.extend(
            _race_rows(
                race_id=20 + index,
                race_date=start + timedelta(days=(20 + index) * 7),
                speed=14.0,
                going="불량",
            )
        )

    horse_id = 999
    performance_day = start + timedelta(days=250)
    performance = _race_rows(
        race_id=50,
        race_date=performance_day,
        speed=14.7,
        going="불량",
        target_horse_id=horse_id,
    )
    rows.extend(performance)
    current = _anchor(race_id=51, race_date=performance_day + timedelta(days=14), horse_id=horse_id)
    rows.append(current)

    result = add_features(
        _frame_for_entry(current), SourceFrames(past_results=pl.DataFrame(rows))
    ).row(0, named=True)

    expected = 100.0 * math.log(
        (1200 / (_finish_ms(1200, 14.7) / 1000.0))
        / (1200 / (_finish_ms(1200, 14.0) / 1000.0))
    )
    assert result["speed_figure_last"] == pytest.approx(expected, abs=0.02)
    assert result["speed_figure_count5"] == 1
    assert result["speed_figure_exact_distance_count5"] == 1
    assert result["speed_figure_censored_rate5"] == 0.0


def test_tail_finish_is_lower_censored() -> None:
    rows: list[dict[str, object]] = []
    start = date(2024, 1, 1)
    for index in range(20):
        rows.extend(
            _race_rows(
                race_id=index + 1,
                race_date=start + timedelta(days=index * 7),
                speed=15.0,
            )
        )
    horse_id = 777
    loss_day = start + timedelta(days=160)
    losing_race = _race_rows(
        race_id=30,
        race_date=loss_day,
        speed=15.0,
        target_horse_id=horse_id,
        target_position=10,
    )
    losing_race[-1]["finish_time_ms"] = _finish_ms(1200, 12.5)
    rows.extend(losing_race)
    current = _anchor(race_id=31, race_date=loss_day + timedelta(days=14), horse_id=horse_id)
    rows.append(current)

    result = add_features(
        _frame_for_entry(current), SourceFrames(past_results=pl.DataFrame(rows))
    ).row(0, named=True)
    assert result["speed_figure_last"] == pytest.approx(-4.0)
    assert result["speed_figure_censored_rate5"] == pytest.approx(1.0)


def test_non_tail_extreme_is_robustly_clipped() -> None:
    rows: list[dict[str, object]] = []
    start = date(2024, 1, 1)
    for index in range(20):
        rows.extend(
            _race_rows(
                race_id=index + 1,
                race_date=start + timedelta(days=index * 7),
                speed=15.0,
            )
        )
    horse_id = 778
    performance_day = start + timedelta(days=160)
    unusual = _race_rows(
        race_id=30,
        race_date=performance_day,
        speed=15.0,
        target_horse_id=horse_id,
        target_position=2,
    )
    unusual[1]["finish_time_ms"] = _finish_ms(1200, 19.0)
    rows.extend(unusual)
    current = _anchor(
        race_id=31, race_date=performance_day + timedelta(days=14), horse_id=horse_id
    )
    rows.append(current)

    result = add_features(
        _frame_for_entry(current), SourceFrames(past_results=pl.DataFrame(rows))
    ).row(0, named=True)
    assert result["speed_figure_last"] == pytest.approx(10.0)
    assert result["speed_figure_censored_rate5"] == pytest.approx(0.0)


def test_same_day_performance_is_not_visible() -> None:
    rows: list[dict[str, object]] = []
    start = date(2024, 1, 1)
    for index in range(20):
        rows.extend(
            _race_rows(
                race_id=index + 1,
                race_date=start + timedelta(days=index * 7),
                speed=15.0,
            )
        )
    horse_id = 555
    target_day = start + timedelta(days=160)
    completed = _race_rows(
        race_id=30,
        race_date=target_day,
        speed=15.5,
        target_horse_id=horse_id,
    )
    same_day_anchor = _anchor(race_id=31, race_date=target_day, horse_id=horse_id)
    next_day_anchor = _anchor(
        race_id=32, race_date=target_day + timedelta(days=1), horse_id=horse_id
    )
    rows.extend(completed)
    rows.extend([same_day_anchor, next_day_anchor])
    past = pl.DataFrame(rows)

    same_day = add_features(
        _frame_for_entry(same_day_anchor), SourceFrames(past_results=past)
    ).row(0, named=True)
    next_day = add_features(
        _frame_for_entry(next_day_anchor), SourceFrames(past_results=past)
    ).row(0, named=True)
    assert same_day["speed_figure_count5"] == 0
    assert same_day["speed_figure_last"] is None
    assert next_day["speed_figure_count5"] == 1
    assert next_day["speed_figure_last"] is not None


def test_specs_match_output_contract() -> None:
    assert [spec.name for spec in FEATURES] == [
        "speed_figure_last",
        "speed_figure_avg3",
        "speed_figure_median5",
        "speed_figure_best5",
        "speed_figure_trend",
        "speed_figure_count5",
        "speed_figure_censored_rate5",
        "speed_figure_exact_distance_avg5",
        "speed_figure_exact_distance_count5",
    ]
