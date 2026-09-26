"""Yeongcheon plan reconstruction. Coordinates are schematic, not surveyed timing lines.

KRA yeongcheon_racemap05.jpg: home straight 350m to the goal + 50m, back
straight 360m, left turn 530m outer / 448m inner, right turn 413m outer /
337m inner. Course structure page: outer 1,700m x 25m, inner 1,514m x 20m,
counter-clockwise; sprints use the outer course, long races start on the
inner course and cross to the outer back straight at the open 2C rail.
Chutes: 1,000m (3C side, 170m to the gate), 1,300/1,400m (backstretch
extension), 1,600m (1C side, 149m). Gate offsets absorb plan rounding.
"""

from math import acos, atan2, cos, degrees, hypot, radians, sin

from horse_racing.web.busan_diagram import timing_points
from horse_racing.web.seoul_metric import at, calibrate, gate_label_dx, span

DISTANCES = (1000, 1200, 1300, 1400, 1600, 1800, 1900, 2000)
PLAN_URL = "https://race.kra.co.kr/images/sub/yeongcheon_racemap05.jpg"
GUIDE_URL = "https://race.kra.co.kr/chulmainfo/RacingcourseStructure.do?Act=02&Sub=11&meet=4"

HOME_M, GOAL_M, BACK_M = 400, 350, 360
LEFT_OUTER_M, RIGHT_OUTER_M, RIGHT_INNER_M = 530, 413, 337

# Rail (inner/outer divider) circles; the larger 3C-4C turn tilts the backstretch.
LEFT_C, LEFT_R = (205.0, 268.0), 132.0
RIGHT_C, RIGHT_R = (520.0, 288.0), 112.0
OUTER, INNER = 12.0, -10.0  # measuring lines, offset from the rail
OUTER_EDGE, INFIELD_EDGE = 25.0, -21.0
CHUTE_SCALE = 0.8  # display units per metre inside the chutes
# Upper common tangent; equal offsets keep the same tangent angle on every line.
TOP_DEG = degrees(
    acos((LEFT_R - RIGHT_R) / hypot(RIGHT_C[0] - LEFT_C[0], RIGHT_C[1] - LEFT_C[1]))
) - degrees(atan2(RIGHT_C[1] - LEFT_C[1], RIGHT_C[0] - LEFT_C[0]))
TOP_LEFT_DEG = TOP_RIGHT_DEG = TOP_DEG
CHUTE_1000_DEG, CHUTE_1600_DEG = 100.0, -6.0
RAIL_OPEN_DEG = 55.0  # right-turn rail starts here; the 2C gap lets long races cross
TRANSFER_EXIT_DEG, TRANSFER_MERGE_M = 65.0, 50  # long races cross inside that gap


def _point(centre, radius, deg):
    return (centre[0] + radius * cos(radians(deg)), centre[1] - radius * sin(radians(deg)))


def _fmt(p):
    return f"{p[0]:.2f} {p[1]:.2f}"


def _arc(centre, radius, start_deg, end_deg):
    """Cubic Bezier approximation of a counter-clockwise (screen) arc."""
    steps = max(1, int(abs(end_deg - start_deg) // 45) + 1)
    sweep = (end_deg - start_deg) / steps
    k = 4 / 3 * (1 - cos(radians(sweep) / 2)) / sin(radians(sweep) / 2) * radius
    out = []
    for i in range(steps):
        a, b = radians(start_deg + i * sweep), radians(start_deg + (i + 1) * sweep)
        p1 = (centre[0] + radius * cos(a) - k * sin(a), centre[1] - radius * sin(a) - k * cos(a))
        p2 = (centre[0] + radius * cos(b) + k * sin(b), centre[1] - radius * sin(b) + k * cos(b))
        out.append(f"C {_fmt(p1)} {_fmt(p2)} {_fmt(_point(centre, radius, degrees(b)))}")
    return " ".join(out)


def _left(offset):
    return LEFT_C, LEFT_R + offset


def _right(offset):
    return RIGHT_C, RIGHT_R + offset


def _along(p, deg, distance):
    """Move from p against the running direction of the tangent at `deg`."""
    return (p[0] + distance * sin(radians(deg)), p[1] + distance * cos(radians(deg)))


def _loop(offset):
    lc, lr = _left(offset)
    rc, rr = _right(offset)
    start = _point(rc, rr, TOP_RIGHT_DEG)
    return (
        f"M {_fmt(start)} L {_fmt(_point(lc, lr, TOP_LEFT_DEG))} "
        + _arc(lc, lr, TOP_LEFT_DEG, 270)
        + f" L {_fmt(_point(rc, rr, -90))} "
        + _arc(rc, rr, -90, TOP_RIGHT_DEG)
    )


def _outer_tail(from_deg=TOP_LEFT_DEG):
    """Shared 3C-4C turn and finish straight on the outer measuring line."""
    lc, lr = _left(OUTER)
    arc_m = LEFT_OUTER_M * (270 - from_deg) / (270 - TOP_LEFT_DEG)
    home_start = _point(lc, lr, 270)
    goal = (home_start[0] + (RIGHT_C[0] - LEFT_C[0]) * GOAL_M / HOME_M, home_start[1])
    return [
        (arc_m, f"M {_fmt(_point(lc, lr, from_deg))} " + _arc(lc, lr, from_deg, 270)),
        (GOAL_M, f"M {_fmt(home_start)} L {_fmt(goal)}"),
    ]


def _top_outer(metres_from_left):
    """Point on the outer back straight (or its 1,300/1,400m extension)."""
    left = _point(*_left(OUTER), TOP_LEFT_DEG)
    right = _point(*_right(OUTER), TOP_RIGHT_DEG)
    straight = hypot(right[0] - left[0], right[1] - left[1])
    ux, uy = (right[0] - left[0]) / straight, (right[1] - left[1]) / straight
    if metres_from_left <= BACK_M:
        t = metres_from_left / BACK_M * straight
    else:
        t = straight + (metres_from_left - BACK_M) * CHUTE_SCALE
    return (left[0] + ux * t, left[1] + uy * t)


def _home_inner(metres_before_right):
    lc, lr = _left(INNER)
    rc, rr = _right(INNER)
    right = _point(rc, rr, -90)
    scale = (rc[0] - lc[0]) / HOME_M
    return (right[0] - metres_before_right * scale, right[1])


GOAL_X = round(_point(*_left(OUTER), 270)[0] + (RIGHT_C[0] - LEFT_C[0]) * GOAL_M / HOME_M, 2)
FINISH_Y = round(_point(*_left(OUTER), 270)[1], 2)
INNER_HOME_Y = round(_point(*_left(INNER), 270)[1], 2)


def route_pieces(d):
    if d == 1000:
        joint = _point(*_left(OUTER), CHUTE_1000_DEG)
        tail = _outer_tail(CHUTE_1000_DEG)
        chute_m = d - sum(m for m, _ in tail)
        start = _along(joint, CHUTE_1000_DEG, chute_m * CHUTE_SCALE)
        return [(chute_m, f"M {_fmt(start)} L {_fmt(joint)}"), *tail]
    if d in (1200, 1300, 1400):
        back_m = d - LEFT_OUTER_M - GOAL_M
        pieces = [(back_m, f"M {_fmt(_top_outer(back_m))} L {_fmt(_top_outer(0))}")]
        return [*pieces, *_outer_tail()]
    rc, rr = _right(OUTER)
    top = _point(rc, rr, TOP_RIGHT_DEG)
    back = (BACK_M, f"M {_fmt(top)} L {_fmt(_top_outer(0))}")
    if d == 1600:
        joint = _point(rc, rr, CHUTE_1600_DEG)
        arc_m = RIGHT_OUTER_M * (TOP_RIGHT_DEG - CHUTE_1600_DEG) / (TOP_RIGHT_DEG + 90)
        chute_m = d - arc_m - BACK_M - LEFT_OUTER_M - GOAL_M
        start = _along(joint, CHUTE_1600_DEG, chute_m * CHUTE_SCALE)
        return [
            (chute_m, f"M {_fmt(start)} L {_fmt(joint)}"),
            (arc_m, f"M {_fmt(joint)} " + _arc(rc, rr, CHUTE_1600_DEG, TOP_RIGHT_DEG)),
            back,
            *_outer_tail(),
        ]
    # 1,800-2,000m: inner home straight and inner 1C-2C turn, then cross the
    # open 2C rail onto the outer back straight.
    ic, ir = _right(INNER)
    inner_m = d - RIGHT_INNER_M - BACK_M - LEFT_OUTER_M - GOAL_M
    bottom = _point(ic, ir, -90)
    exit_ = _point(ic, ir, TRANSFER_EXIT_DEG)
    arc_m = RIGHT_INNER_M * (TRANSFER_EXIT_DEG + 90) / (TOP_RIGHT_DEG + 90)
    merge = _top_outer(BACK_M - TRANSFER_MERGE_M)
    transfer = (
        f"M {_fmt(exit_)} C {_fmt(_along(exit_, TRANSFER_EXIT_DEG, -30))} "
        f"{_fmt(_top_outer(BACK_M - 15))} {_fmt(merge)}"
    )
    return [
        (inner_m, f"M {_fmt(_home_inner(inner_m))} L {_fmt(bottom)}"),
        (arc_m, f"M {_fmt(bottom)} " + _arc(ic, ir, -90, TRANSFER_EXIT_DEG)),
        (RIGHT_INNER_M - arc_m + TRANSFER_MERGE_M, transfer),
        (BACK_M - TRANSFER_MERGE_M, f"M {_fmt(merge)} L {_fmt(_top_outer(0))}"),
        *_outer_tail(),
    ]


def _band(path_points):
    return "M " + " L ".join(_fmt(p) for p in path_points)


def _surface():
    """Stroked lanes (CSS widths): one loop band covering both courses, plus
    outer-lane chutes. Border paths run 1.5 units past the open chute end."""
    loop = _loop((OUTER_EDGE + INFIELD_EDGE) / 2) + " Z"
    j1000 = _point(*_left(OUTER), CHUTE_1000_DEG)
    j1600 = _point(*_right(OUTER), CHUTE_1600_DEG)
    chutes = []
    for joint, deg, end_m in ((j1000, CHUTE_1000_DEG, 200), (j1600, CHUTE_1600_DEG, 179)):
        inside = _along(joint, deg, -18)
        chutes.append(dict(
            lane=_band([inside, _along(joint, deg, end_m * CHUTE_SCALE)]),
            border=_band([inside, _along(joint, deg, end_m * CHUTE_SCALE + 1.5)]),
        ))
    top_join = _top_outer(BACK_M - 25)
    chutes.append(dict(
        lane=_band([top_join, _top_outer(BACK_M + 210)]),
        border=_band([top_join, _top_outer(BACK_M + 210 + 1.5 / CHUTE_SCALE)]),
    ))
    return dict(loop=loop, chutes=chutes)


def _rail():
    """Inner/outer divider with the open section around 2C."""
    lc, lr = LEFT_C, LEFT_R
    rc, rr = RIGHT_C, RIGHT_R
    top_left = _point(lc, lr, TOP_LEFT_DEG)
    top_right = _point(rc, rr, TOP_RIGHT_DEG)
    length = hypot(top_right[0] - top_left[0], top_right[1] - top_left[1])
    t = (length - 55) / length
    open_end = (top_left[0] + (top_right[0] - top_left[0]) * t,
                top_left[1] + (top_right[1] - top_left[1]) * t)
    return (
        f"M {_fmt(open_end)} L {_fmt(top_left)} " + _arc(lc, lr, TOP_LEFT_DEG, 270)
        + f" L {_fmt(_point(rc, rr, -90))} " + _arc(rc, rr, -90, RAIL_OPEN_DEG)
    )


ROUTE_TEXT = {
    1000: ("3코너 쪽 연장주로 출발",
           "왼쪽 위 연장주로에서 출발해 3·4코너를 돌아 결승으로 향합니다."),
    1200: ("뒤쪽 직선 출발 · 외주로",
           "뒤쪽 직선에서 출발해 3·4코너를 돌아 결승으로 향합니다."),
    1300: ("뒤쪽 직선 연장부 출발", "뒤쪽 직선 연장부에서 출발해 외주로로 진행합니다."),
    1400: ("뒤쪽 직선 연장부 출발", "2코너 바깥 연장부에서 출발해 외주로로 진행합니다."),
    1600: ("1코너 쪽 보조 출발부",
           "오른쪽 곡선 바깥 출발부에서 2코너로 진입해 외주로를 돕니다."),
    "long": ("내주로 출발 → 2코너 외주로",
             "관람대 앞 내주로에서 출발해 1·2코너를 돌고, "
             "2코너 개방부에서 외주로 뒤쪽 직선으로 나갑니다."),
}


def build_yeongcheon_diagram(distance):
    variants = []
    for d in DISTANCES:
        pieces = route_pieces(d)
        points = calibrate(pieces)
        positions = timing_points(d)
        markers = []
        for metre in sorted(set(positions.values()) - {d}):
            codes = [c for c, m in positions.items() if m == metre]
            x, y = at(points, metre)
            below = y >= FINISH_Y - 4
            # Inner home-straight labels sit above the line, clear of the finish post.
            above = not below and y >= INNER_HOME_Y - 4
            side = 14 if x > 380 else -14
            markers.append(
                dict(
                    code=codes[0],
                    aliases=codes,
                    elapsed=metre,
                    remaining=d - metre,
                    x=round(x, 2),
                    y=round(y, 2),
                    label_x=0 if below or above else side,
                    label_y=30 if below else -16 if above or y < 200 else 5,
                    label_anchor="middle" if below or above else "start" if side > 0 else "end",
                    action={"S1F": "early", "G3F": "600", "G1F": "200"}.get(codes[0], codes[0]),
                )
            )
        boundaries = sorted({0, *positions.values()})
        metric = dict(
            total=round(sum(m for m, _ in pieces), 6),
            markers=markers,
            early=span(points, 0, 200),
            closing600=span(points, d - 600, d),
            closing400=span(points, d - 600, d - 200),
            closing200=span(points, d - 200, d),
            reference_points=positions,
            intervals=[
                dict(start=a, end=b, path=span(points, a, b))
                for a in boundaries
                for b in boundaries
                if a < b
            ],
        )
        x, y = at(points, 0)
        label, description = ROUTE_TEXT.get(d, ROUTE_TEXT["long"])
        variants.append(
            dict(
                distance=d,
                start_x=round(x, 2),
                start_y=round(y, 2),
                gate_dx=gate_label_dx(x, y, markers),
                path=span(points, 0, d),
                label=label,
                description=description,
                selected=d == distance,
                metric=metric,
            )
        )
    surface = _surface()
    lc, lr = _left(INFIELD_EDGE)
    rc, rr = _right(INFIELD_EDGE)
    field = (
        f"M {_fmt(_point(rc, rr, TOP_RIGHT_DEG))} L {_fmt(_point(lc, lr, TOP_LEFT_DEG))} "
        + _arc(lc, lr, TOP_LEFT_DEG, 270)
        + f" L {_fmt(_point(rc, rr, -90))} "
        + _arc(rc, rr, -90, TOP_RIGHT_DEG)
        + " Z"
    )
    return dict(
        course_en="YEONGCHEON",
        surface="",
        field=field,
        bands=surface,
        rail=_rail(),
        rails=[],
        corners=[
            dict(label="3코너 구역", x=118, y=82),
            dict(label="2코너 구역", x=712, y=240),
            dict(label="1코너 구역", x=712, y=412),
            dict(label="4코너 구역", x=72, y=440),
        ],
        center_x=round((LEFT_C[0] + RIGHT_C[0]) / 2 - 4, 2),
        center_y=262,
        finish_label_y=455,
        grandstand=dict(x=420, y=466, width=150, label="관람대"),
        variants=variants,
        selected=next((v for v in variants if v["selected"]), None),
        plan_url=PLAN_URL,
        guide_url=GUIDE_URL,
    )
