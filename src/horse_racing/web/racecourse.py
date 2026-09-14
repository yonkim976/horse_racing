from __future__ import annotations

from dataclasses import dataclass
from math import cos, hypot, pi, sin

from horse_racing.web.busan_diagram import build_busan_diagram
from horse_racing.web.seoul_diagram import build_seoul_diagram

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
    diagram: dict | None = None


def build_racecourse_map(*, meet_code: int, distance_m: int) -> RacecourseMapView | None:
    if meet_code == 1:
        return build_seoul_racecourse_map(distance_m)
    if meet_code == 2:
        return build_jeju_racecourse_map(distance_m)
    if meet_code == 3:
        return build_busan_racecourse_map(distance_m)
    return None


def jeju_checkpoint_point(remaining_m: int) -> MapPoint:
    """Position a timing checkpoint by distance remaining, including a repeated lap."""
    return _point_on_forward_loop((JEJU_LAP_M - remaining_m) % JEJU_LAP_M)


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
        diagram={"variants": [
            {"distance": d, "path": route, "x": start.x, "y": start.y}
            for d in sorted(set(JEJU_DIAGRAM_STARTS) | {distance_m})
            for start, route, _supported in [_jeju_route(d)]
        ]},
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
    point = jeju_checkpoint_point(distance_to_goal)
    return MapMarker(
        label=str(number),
        x=point.x,
        y=point.y,
        label_x=point.x,
        label_y=point.y + (-28 if point.y < 0 else 32),
    )


def build_seoul_racecourse_map(distance_m: int) -> RacecourseMapView:
    diagram = build_seoul_diagram(distance_m)
    selected = diagram["selected"]
    starts = [MapMarker(label=f"{v['distance']:,}m", x=v["start_x"], y=v["start_y"],
                        label_x=v["start_x"], label_y=v["start_y"] - 22,
                        selected=v["selected"]) for v in diagram["variants"]]
    return RacecourseMapView(
        meet_code=1, course_name="서울", distance_m=distance_m,
        supported_distance=selected is not None, view_box="0 0 790 530",
        loop_path=diagram["surface"], inner_path=diagram["field"], chute_path="",
        route_path=selected["path"] if selected else "", goal_x=555, top_y=151, bottom_y=418,
        start_markers=starts, furlong_markers=[],
        selected_start=MapPoint(selected["start_x"], selected["start_y"]) if selected
        else MapPoint(555, 418),
        geometry_note="외주로 1,800m · 내주로 1,600m · 직선 450m · 폭 25m / 결승직선 30m",
        diagram=diagram,
    )


def build_busan_racecourse_map(distance_m: int) -> RacecourseMapView:
    diagram = build_busan_diagram(distance_m)
    selected = diagram["selected"]
    return RacecourseMapView(
        meet_code=3,
        course_name="부경",
        distance_m=distance_m,
        supported_distance=selected is not None,
        view_box="0 0 790 520",
        loop_path=diagram["surface"],
        inner_path=diagram["field"],
        chute_path="",
        route_path=selected["path"] if selected else "",
        goal_x=525,
        top_y=170,
        bottom_y=390,
        start_markers=[],
        furlong_markers=[],
        selected_start=MapPoint(selected["start_x"], selected["start_y"])
        if selected
        else MapPoint(525, 390),
        geometry_note=("공식 평면도 기준 내주로 1,460m · 외주로 2,008m · 폭 25m. "
                       "주로 현황 페이지의 1,470m·2,000m 표기와 차이가 있어 "
                       "평면도를 기준으로 재구성한 개략 경로입니다"),
        diagram=diagram,
    )
