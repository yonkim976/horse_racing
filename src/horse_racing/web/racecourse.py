from __future__ import annotations

from dataclasses import dataclass
from math import cos, hypot, pi, sin

JEJU_STRAIGHT_M = 493.7
JEJU_CURVE_RADIUS_M = 97.5
JEJU_TRACK_WIDTH_M = 20.0
JEJU_GOAL_FROM_LEFT_TANGENT_M = 147.8
JEJU_LAP_M = 2 * JEJU_STRAIGHT_M + 2 * pi * JEJU_CURVE_RADIUS_M

JEJU_DIAGRAM_STARTS = (800, 900, 1000, 1110, 1200, 1300, 1400, 1610)
JEJU_BACKSTRETCH_STARTS = frozenset((800, 900, 1000, 1110, 1200))

SEOUL_OUTER_STRAIGHT_M = 450.0
SEOUL_OUTER_CURVE_M = 450.0
SEOUL_OUTER_RADIUS_M = 143.24
SEOUL_OUTER_LAP_M = 2 * SEOUL_OUTER_STRAIGHT_M + 2 * SEOUL_OUTER_CURVE_M
SEOUL_INNER_STRAIGHT_M = 450.0
SEOUL_INNER_CURVE_M = 350.0
SEOUL_INNER_RADIUS_M = 111.44
SEOUL_INNER_LAP_M = 2 * SEOUL_INNER_STRAIGHT_M + 2 * SEOUL_INNER_CURVE_M
SEOUL_TRACK_WIDTH_M = 25.0
SEOUL_FINISH_STRAIGHT_WIDTH_M = 30.0
SEOUL_GOAL_FROM_LEFT_TANGENT_M = 400.0

SEOUL_DIAGRAM_STARTS = (1000, 1200, 1300, 1400, 1600, 1700, 1800, 1900, 2000, 2300)
SEOUL_OUTER_STARTS = frozenset((1200, 1300, 1400, 1600))
SEOUL_INNER_STARTS = frozenset((1700, 1800, 1900, 2000))


@dataclass(frozen=True, slots=True)
class MapPoint:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class MapMarker:
    label: str
    x: float
    y: float
    label_x: float
    label_y: float
    selected: bool = False


@dataclass(frozen=True, slots=True)
class RacecourseMapView:
    meet_code: int
    course_name: str
    distance_m: int
    supported_distance: bool
    view_box: str
    loop_path: str
    inner_path: str
    chute_path: str
    route_path: str
    goal_x: float
    top_y: float
    bottom_y: float
    start_markers: list[MapMarker]
    furlong_markers: list[MapMarker]
    selected_start: MapPoint
    geometry_note: str
    inner_course_path: str = ""
    extension_path: str = ""


def build_racecourse_map(*, meet_code: int, distance_m: int) -> RacecourseMapView | None:
    if meet_code == 1:
        return build_seoul_racecourse_map(distance_m)
    if meet_code == 2:
        return build_jeju_racecourse_map(distance_m)
    return None


def build_jeju_racecourse_map(distance_m: int) -> RacecourseMapView:
    selected_start, route_path, supported = _jeju_route(distance_m)
    starts = [
        _start_marker(distance, selected=distance == distance_m) for distance in JEJU_DIAGRAM_STARTS
    ]
    if distance_m not in JEJU_DIAGRAM_STARTS:
        starts.append(_custom_start_marker(distance_m, selected_start))

    furlongs = [_furlong_marker(number) for number in range(1, 8)]
    radius = JEJU_CURVE_RADIUS_M
    inner_radius = radius - JEJU_TRACK_WIDTH_M / 2

    return RacecourseMapView(
        meet_code=2,
        course_name="제주",
        distance_m=distance_m,
        supported_distance=supported,
        view_box="-148 -166 771 325",
        loop_path=_loop_path(),
        inner_path=(
            f"M 0 {-inner_radius:.3f} H {JEJU_STRAIGHT_M:.3f} "
            f"A {inner_radius:.3f} {inner_radius:.3f} 0 0 1 "
            f"{JEJU_STRAIGHT_M:.3f} {inner_radius:.3f} H 0 "
            f"A {inner_radius:.3f} {inner_radius:.3f} 0 0 1 0 {-inner_radius:.3f} Z"
        ),
        chute_path=f"M -72.000 {-radius:.3f} H 0",
        route_path=route_path,
        goal_x=JEJU_GOAL_FROM_LEFT_TANGENT_M,
        top_y=-radius,
        bottom_y=radius,
        start_markers=starts,
        furlong_markers=furlongs,
        selected_start=selected_start,
        geometry_note=(f"중심선 기준 2×493.7m + 2π×97.5m = {JEJU_LAP_M:,.2f}m (공식 1주 1,600m)"),
    )


def _loop_path() -> str:
    length = JEJU_STRAIGHT_M
    radius = JEJU_CURVE_RADIUS_M
    goal = JEJU_GOAL_FROM_LEFT_TANGENT_M
    return (
        f"M {goal:.3f} {radius:.3f} H 0 "
        f"A {radius:.3f} {radius:.3f} 0 0 1 0 {-radius:.3f} "
        f"H {length:.3f} "
        f"A {radius:.3f} {radius:.3f} 0 0 1 {length:.3f} {radius:.3f} "
        f"H {goal:.3f} Z"
    )


def _jeju_route(distance_m: int) -> tuple[MapPoint, str, bool]:
    radius = JEJU_CURVE_RADIUS_M
    length = JEJU_STRAIGHT_M
    goal = JEJU_GOAL_FROM_LEFT_TANGENT_M

    if distance_m in JEJU_BACKSTRETCH_STARTS:
        start_x = _backstretch_start_x(distance_m)
        start = MapPoint(start_x, -radius)
        path = (
            f"M {start.x:.3f} {start.y:.3f} H {length:.3f} "
            f"A {radius:.3f} {radius:.3f} 0 0 1 {length:.3f} {radius:.3f} "
            f"H {goal:.3f}"
        )
        return start, path, True

    if 0 < distance_m <= round(JEJU_LAP_M):
        distance_from_goal = JEJU_LAP_M - distance_m
        start = _point_on_forward_loop(distance_from_goal)
        return (
            start,
            _route_from_forward_position(distance_from_goal),
            distance_m in JEJU_DIAGRAM_STARTS,
        )

    if round(JEJU_LAP_M) < distance_m <= 1800:
        extra = distance_m - 1600
        start = MapPoint(goal + extra, radius)
        path = (
            f"M {start.x:.3f} {start.y:.3f} H 0 "
            f"A {radius:.3f} {radius:.3f} 0 0 1 0 {-radius:.3f} "
            f"H {length:.3f} "
            f"A {radius:.3f} {radius:.3f} 0 0 1 {length:.3f} {radius:.3f} "
            f"H {goal:.3f}"
        )
        return start, path, distance_m in {1610, 1700, 1800}

    fallback = MapPoint(goal, radius)
    return fallback, _loop_path(), False


def _backstretch_start_x(distance_m: int) -> float:
    finish_straight = JEJU_STRAIGHT_M - JEJU_GOAL_FROM_LEFT_TANGENT_M
    return JEJU_STRAIGHT_M + pi * JEJU_CURVE_RADIUS_M + finish_straight - distance_m


def _point_on_forward_loop(distance_m: float) -> MapPoint:
    radius = JEJU_CURVE_RADIUS_M
    length = JEJU_STRAIGHT_M
    goal = JEJU_GOAL_FROM_LEFT_TANGENT_M
    curve = pi * radius

    remaining = distance_m
    if remaining <= goal:
        return MapPoint(goal - remaining, radius)
    remaining -= goal

    if remaining <= curve:
        angle = pi / 2 + remaining / radius
        return MapPoint(radius * cos(angle), radius * sin(angle))
    remaining -= curve

    if remaining <= length:
        return MapPoint(remaining, -radius)
    remaining -= length

    if remaining <= curve:
        angle = -pi / 2 + remaining / radius
        return MapPoint(length + radius * cos(angle), radius * sin(angle))
    remaining -= curve

    return MapPoint(length - remaining, radius)


def _route_from_forward_position(distance_m: float) -> str:
    radius = JEJU_CURVE_RADIUS_M
    length = JEJU_STRAIGHT_M
    goal = JEJU_GOAL_FROM_LEFT_TANGENT_M
    curve = pi * radius
    start = _point_on_forward_loop(distance_m)

    if distance_m <= goal:
        return (
            f"M {start.x:.3f} {start.y:.3f} H 0 "
            f"A {radius:.3f} {radius:.3f} 0 0 1 0 {-radius:.3f} "
            f"H {length:.3f} "
            f"A {radius:.3f} {radius:.3f} 0 0 1 {length:.3f} {radius:.3f} "
            f"H {goal:.3f}"
        )

    if distance_m <= goal + curve:
        return (
            f"M {start.x:.3f} {start.y:.3f} "
            f"A {radius:.3f} {radius:.3f} 0 0 1 0 {-radius:.3f} "
            f"H {length:.3f} "
            f"A {radius:.3f} {radius:.3f} 0 0 1 {length:.3f} {radius:.3f} "
            f"H {goal:.3f}"
        )

    if distance_m <= goal + curve + length:
        return (
            f"M {start.x:.3f} {start.y:.3f} H {length:.3f} "
            f"A {radius:.3f} {radius:.3f} 0 0 1 {length:.3f} {radius:.3f} "
            f"H {goal:.3f}"
        )

    if distance_m <= goal + 2 * curve + length:
        return (
            f"M {start.x:.3f} {start.y:.3f} "
            f"A {radius:.3f} {radius:.3f} 0 0 1 {length:.3f} {radius:.3f} "
            f"H {goal:.3f}"
        )

    return f"M {start.x:.3f} {start.y:.3f} H {goal:.3f}"


def _start_marker(distance_m: int, *, selected: bool) -> MapMarker:
    start, _path, _supported = _jeju_route(distance_m)
    if distance_m in JEJU_BACKSTRETCH_STARTS:
        label = MapPoint(start.x, start.y - 23)
    elif distance_m == 1610:
        label = MapPoint(start.x, start.y - 23)
    else:
        center = MapPoint(JEJU_STRAIGHT_M / 2, 0)
        dx = start.x - center.x
        dy = start.y - center.y
        scale = 28 / max(hypot(dx, dy), 1)
        label = MapPoint(start.x + dx * scale, start.y + dy * scale)
    return MapMarker(
        label=f"{distance_m:,}m",
        x=start.x,
        y=start.y,
        label_x=label.x,
        label_y=label.y,
        selected=selected,
    )


def _custom_start_marker(distance_m: int, start: MapPoint) -> MapMarker:
    return MapMarker(
        label=f"{distance_m:,}m",
        x=start.x,
        y=start.y,
        label_x=start.x,
        label_y=start.y - 24,
        selected=True,
    )


def _furlong_marker(number: int) -> MapMarker:
    distance_to_goal = number * 200
    point = _point_on_forward_loop(JEJU_LAP_M - distance_to_goal)
    center = MapPoint(JEJU_STRAIGHT_M / 2, 0)
    dx = center.x - point.x
    dy = center.y - point.y
    scale = 22 / max(hypot(dx, dy), 1)
    return MapMarker(
        label=str(number),
        x=point.x + dx * scale,
        y=point.y + dy * scale,
        label_x=point.x + dx * scale,
        label_y=point.y + dy * scale,
    )


def build_seoul_racecourse_map(distance_m: int) -> RacecourseMapView:
    selected_start, route_path, supported = _seoul_route(distance_m)
    starts = [
        _seoul_start_marker(distance, selected=distance == distance_m)
        for distance in SEOUL_DIAGRAM_STARTS
    ]
    if distance_m not in SEOUL_DIAGRAM_STARTS:
        starts.append(_seoul_custom_start_marker(distance_m, selected_start))

    inner_infield_radius = SEOUL_INNER_RADIUS_M - SEOUL_TRACK_WIDTH_M / 2
    return RacecourseMapView(
        meet_code=1,
        course_name="서울",
        distance_m=distance_m,
        supported_distance=supported,
        view_box="-348 -292 1002 505",
        loop_path=_seoul_loop_path(SEOUL_OUTER_RADIUS_M),
        inner_path=_seoul_loop_path(inner_infield_radius),
        inner_course_path=_seoul_loop_path(SEOUL_INNER_RADIUS_M),
        chute_path=_seoul_thousand_chute_path(),
        extension_path=(f"M -100.000 {SEOUL_OUTER_RADIUS_M:.3f} H {SEOUL_OUTER_STRAIGHT_M:.3f}"),
        route_path=route_path,
        goal_x=SEOUL_GOAL_FROM_LEFT_TANGENT_M,
        top_y=-SEOUL_OUTER_RADIUS_M,
        bottom_y=SEOUL_OUTER_RADIUS_M,
        start_markers=starts,
        furlong_markers=[_seoul_furlong_marker(number) for number in range(1, 9)],
        selected_start=selected_start,
        geometry_note=("외주로 2×450m + 2×450m = 1,800m · 내주로 2×450m + 2×350m = 1,600m"),
    )


def _seoul_loop_path(radius: float) -> str:
    length = SEOUL_OUTER_STRAIGHT_M
    return (
        f"M 0 {radius:.3f} H {length:.3f} "
        f"A {radius:.3f} {radius:.3f} 0 0 0 {length:.3f} {-radius:.3f} "
        f"H 0 A {radius:.3f} {radius:.3f} 0 0 0 0 {radius:.3f} Z"
    )


def _seoul_thousand_chute_path() -> str:
    radius = SEOUL_OUTER_RADIUS_M
    return (
        "M -170.000 -240.000 L -275.000 -163.000 "
        f"C -335.000 -60.000 -278.000 {radius - 18:.3f} 0 {radius:.3f}"
    )


def _seoul_route(distance_m: int) -> tuple[MapPoint, str, bool]:
    radius = SEOUL_OUTER_RADIUS_M
    goal = SEOUL_GOAL_FROM_LEFT_TANGENT_M
    length = SEOUL_OUTER_STRAIGHT_M

    if distance_m == 1000:
        start = MapPoint(-170.0, -240.0)
        return start, f"{_seoul_thousand_chute_path()} H {goal:.3f}", True

    if distance_m in SEOUL_INNER_STARTS:
        start_x = 2000.0 - distance_m
        start = MapPoint(start_x, SEOUL_INNER_RADIUS_M)
        inner_radius = SEOUL_INNER_RADIUS_M
        path = (
            f"M {start_x:.3f} {inner_radius:.3f} H {length:.3f} "
            f"A {inner_radius:.3f} {inner_radius:.3f} 0 0 0 "
            f"{length:.3f} {-inner_radius:.3f} H 0 "
            f"A {inner_radius:.3f} {inner_radius:.3f} 0 0 0 "
            f"0 {inner_radius:.3f} L 0 {radius:.3f} H {goal:.3f}"
        )
        return start, path, True

    if distance_m == 2300:
        start = MapPoint(-100.0, radius)
        path = (
            f"M -100.000 {radius:.3f} H {length:.3f} "
            f"A {radius:.3f} {radius:.3f} 0 0 0 {length:.3f} {-radius:.3f} "
            f"H 0 A {radius:.3f} {radius:.3f} 0 0 0 0 {radius:.3f} "
            f"H {goal:.3f}"
        )
        return start, path, True

    if 0 < distance_m <= SEOUL_OUTER_LAP_M:
        start, path = _seoul_outer_route(distance_m)
        return start, path, distance_m in SEOUL_OUTER_STARTS

    fallback = MapPoint(goal, radius)
    return fallback, _seoul_loop_path(radius), False


def _seoul_outer_route(distance_m: float) -> tuple[MapPoint, str]:
    radius = SEOUL_OUTER_RADIUS_M
    length = SEOUL_OUTER_STRAIGHT_M
    goal = SEOUL_GOAL_FROM_LEFT_TANGENT_M

    if distance_m <= goal:
        start = MapPoint(goal - distance_m, radius)
        return start, f"M {start.x:.3f} {radius:.3f} H {goal:.3f}"

    if distance_m <= goal + SEOUL_OUTER_CURVE_M:
        curve_remaining = distance_m - goal
        angle = -3 * pi / 2 + curve_remaining / radius
        start = MapPoint(radius * cos(angle), radius * sin(angle))
        path = (
            f"M {start.x:.3f} {start.y:.3f} "
            f"A {radius:.3f} {radius:.3f} 0 0 0 0 {radius:.3f} H {goal:.3f}"
        )
        return start, path

    if distance_m <= goal + SEOUL_OUTER_CURVE_M + length:
        start = MapPoint(distance_m - goal - SEOUL_OUTER_CURVE_M, -radius)
        path = (
            f"M {start.x:.3f} {-radius:.3f} H 0 "
            f"A {radius:.3f} {radius:.3f} 0 0 0 0 {radius:.3f} H {goal:.3f}"
        )
        return start, path

    if distance_m <= goal + 2 * SEOUL_OUTER_CURVE_M + length:
        curve_remaining = distance_m - goal - SEOUL_OUTER_CURVE_M - length
        angle = -pi / 2 + curve_remaining / radius
        start = MapPoint(length + radius * cos(angle), radius * sin(angle))
        path = (
            f"M {start.x:.3f} {start.y:.3f} "
            f"A {radius:.3f} {radius:.3f} 0 0 0 {length:.3f} {-radius:.3f} "
            f"H 0 A {radius:.3f} {radius:.3f} 0 0 0 0 {radius:.3f} H {goal:.3f}"
        )
        return start, path

    start = MapPoint(goal + SEOUL_OUTER_LAP_M - distance_m, radius)
    path = (
        f"M {start.x:.3f} {radius:.3f} H {length:.3f} "
        f"A {radius:.3f} {radius:.3f} 0 0 0 {length:.3f} {-radius:.3f} "
        f"H 0 A {radius:.3f} {radius:.3f} 0 0 0 0 {radius:.3f} H {goal:.3f}"
    )
    return start, path


def _seoul_start_marker(distance_m: int, *, selected: bool) -> MapMarker:
    start, _path, _supported = _seoul_route(distance_m)
    if distance_m in SEOUL_INNER_STARTS:
        label = MapPoint(start.x, 198.0)
    elif distance_m == 2300:
        label = MapPoint(start.x, 198.0)
    elif distance_m == 1000:
        label = MapPoint(start.x, start.y - 25)
    else:
        center = MapPoint(SEOUL_OUTER_STRAIGHT_M / 2, 0)
        dx = start.x - center.x
        dy = start.y - center.y
        scale = 31 / max(hypot(dx, dy), 1)
        label = MapPoint(start.x + dx * scale, start.y + dy * scale)
    return MapMarker(
        label=f"{distance_m:,}m",
        x=start.x,
        y=start.y,
        label_x=label.x,
        label_y=label.y,
        selected=selected,
    )


def _seoul_custom_start_marker(distance_m: int, start: MapPoint) -> MapMarker:
    return MapMarker(
        label=f"{distance_m:,}m",
        x=start.x,
        y=start.y,
        label_x=start.x,
        label_y=start.y - 28,
        selected=True,
    )


def _seoul_furlong_marker(number: int) -> MapMarker:
    point, _path = _seoul_outer_route(number * 200)
    return MapMarker(
        label=str(number),
        x=point.x,
        y=point.y,
        label_x=point.x,
        label_y=point.y,
    )
