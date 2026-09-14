from __future__ import annotations

import pytest

from horse_racing.web.racecourse import (
    JEJU_LAP_M,
    SEOUL_INNER_LAP_M,
    SEOUL_OUTER_LAP_M,
    build_jeju_racecourse_map,
    build_racecourse_map,
    build_seoul_racecourse_map,
    jeju_checkpoint_point,
)


def test_jeju_measured_geometry_closes_at_official_lap_distance() -> None:
    assert JEJU_LAP_M == pytest.approx(1600.0105, abs=0.001)


def test_jeju_checkpoint_finish_and_last_furlong_share_finish_straight() -> None:
    finish = jeju_checkpoint_point(0)
    last_furlong = jeju_checkpoint_point(200)
    assert finish.x == pytest.approx(147.8)
    assert finish.y == last_furlong.y == 97.5
    assert last_furlong.x - finish.x == pytest.approx(200)


@pytest.mark.parametrize("remaining", [800, 1000, 1300, 1400])
def test_jeju_checkpoint_uses_same_geometry_as_route_start(remaining) -> None:
    point = jeju_checkpoint_point(remaining)
    start = build_jeju_racecourse_map(remaining).selected_start
    assert point.x == pytest.approx(start.x)
    assert point.y == pytest.approx(start.y)


@pytest.mark.parametrize(
    ("distance_m", "expected_x", "expected_y"),
    [
        (800, 345.905, -97.5),
        (1000, 145.905, -97.5),
        (1200, -54.095, -97.5),
        (1300, -97.495, 0.942),
        (1400, -49.8, 83.8),
        (1610, 157.8, 97.5),
    ],
)
def test_jeju_start_points_follow_measured_course(
    distance_m: int,
    expected_x: float,
    expected_y: float,
) -> None:
    view = build_jeju_racecourse_map(distance_m)

    assert view.selected_start.x == pytest.approx(expected_x, abs=0.15)
    assert view.selected_start.y == pytest.approx(expected_y, abs=0.15)
    assert view.supported_distance is True
    assert f"{distance_m:,}m" in [marker.label for marker in view.start_markers]


def test_jeju_map_marks_non_diagram_distance_as_estimated() -> None:
    view = build_jeju_racecourse_map(777)

    assert view.supported_distance is False
    assert any(marker.label == "777m" and marker.selected for marker in view.start_markers)


def test_seoul_official_lap_distances_are_preserved() -> None:
    assert SEOUL_OUTER_LAP_M == 1800
    assert SEOUL_INNER_LAP_M == 1600


@pytest.mark.parametrize(
    ("distance_m", "expected_x", "expected_y"),
    [
        (1000, 234, 43),
        (1200, 516, 151),
        (1300, 598, 151),
        (1400, 684, 151),
        (1600, 741, 345),
        (1700, 468, 392),
        (1800, 383, 392),
        (1900, 296, 392),
        (2000, 296, 392),
        (2300, 122, 418),
    ],
)
def test_seoul_start_points_follow_official_course_layout(
    distance_m: int,
    expected_x: float,
    expected_y: float,
) -> None:
    view = build_seoul_racecourse_map(distance_m)

    assert view.selected_start.x == pytest.approx(expected_x, abs=0.15)
    assert view.selected_start.y == pytest.approx(expected_y, abs=0.15)
    assert view.supported_distance is True
    assert f"{distance_m:,}m" in [marker.label for marker in view.start_markers]


def test_seoul_long_distance_route_uses_inner_course_then_outer_finish() -> None:
    view = build_seoul_racecourse_map(1800)

    assert len(view.diagram["rails"]) == 2
    assert view.route_path.endswith("H 555")
    assert " L " not in view.route_path


def test_racecourse_map_supports_seoul_and_jeju() -> None:
    assert build_racecourse_map(meet_code=1, distance_m=1200) is not None
    assert build_racecourse_map(meet_code=3, distance_m=1200) is not None
    assert build_racecourse_map(meet_code=2, distance_m=1200) is not None
