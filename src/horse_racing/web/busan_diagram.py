"""Busan plan reconstruction. Coordinates are schematic, not surveyed timing lines.

KRA busan_racemap02.jpg: inner 325+405+325+405=1460m,
outer 500+504+500+504=2008m; finish 40m before right tangent.
The 1800/1900 common gate uses different left turns (99m difference).
Gate offsets absorb rounding in the published plan; do not rewrite race times.
"""

from horse_racing.web.seoul_metric import at, calibrate, span

DISTANCES = (1000, 1200, 1300, 1400, 1500, 1600, 1800, 1900, 2000, 2200)
PLAN_URL = "https://race.kra.co.kr/images/sub/busan_racemap02.jpg"
GUIDE_URL = "https://race.kra.co.kr/chulmainfo/RacingcourseStructure.do?Act=02&Sub=10&meet=3"


def timing_points(distance):
    return {
        "S1F": 200,
        **{
            f"G{n}F": distance - n * 200
            for n in (8, 6, 4, 3, 2, 1)
            if 0 < distance - n * 200 < distance
        },
        "FIN": distance,
    }


# Image-space landmarks traced from the dimension plan. Separate gate anchors
# from metre calibration: a gate must not move when a segment length is corrected.
STARTS = {
    1000: (228, 114),
    1200: (356, 170),
    1300: (424, 170),
    1400: (492, 170),
    1500: (560, 170),
    1600: (628, 170),
    1800: (318, 372),
    1900: (318, 372),
    2000: (250, 372),
    2200: (395, 390),
}
# Predominantly straight diagonal transfers, with short end transitions.
# Reuse the same geometry for the painted lane and highlighted race line.
TOP_MERGE = "C 447 192 445.5 191 443 190 L 398 172 C 395.5 171 393 170 385 170"
BOTTOM_MERGE = "C 194 361.111 199.4 363.9 202 365 L 242 385 C 248 388 251 390 255 390"
LEFT = "M 225 170 C 151 170 108 220 108 280 C 108 342 155 390 225 390"
INNER_LEFT = "M 225 192 C 166 192 130 230 130 280 C 130 322 154 350 190 360 " + BOTTOM_MERGE
RIGHT = "M 450 372 C 515 372 555 333 555 280 C 555 230 516 192 450 192"


def route_pieces(d):
    x, y = STARTS[d]
    if d == 1000:
        return [
            (182, f"M {x} {y} L 156 197"),
            (358, "M 156 197 C 126 223 108 249 108 280 C 108 342 155 390 225 390"),
            (460, "M 225 390 H 525"),
        ]
    if d <= 1600:
        return [(d - 964, f"M {x} {y} H 225"), (504, LEFT), (460, "M 225 390 H 525")]
    if d in (1800, 1900, 2000):
        inner = d == 1800
        # A shared finish straight must put G1F/G2F at the same physical
        # point for every distance. The inner merge ends 30 display units
        # farther along the 300-unit / 460m straight.
        transferred = 30 / 300 * 460 if inner else 0
        finish = (460 - transferred, f"M {255 if inner else 225} 390 H 525")
        turn = (405 + transferred, INNER_LEFT) if inner else (504, LEFT)
        # Likewise move the omitted backstretch portion into the connector,
        # rather than compressing 325m into a shorter straight after the merge.
        back_transfer = 65 / 225 * 325 if not inner else 0
        initial = d - 405 - 325 - turn[0] - finish[0]
        return [
            (initial, f"M {x} {y} H 450"),
            (405 + back_transfer, RIGHT if inner else RIGHT + " " + TOP_MERGE),
            (325 - back_transfer, "M 450 192 H 225" if inner else "M 385 170 H 225"),
            turn,
            finish,
        ]
    return [
        (232, f"M {x} {y} H 565"),
        (504, "M 565 390 C 644 390 694 342 694 280 C 694 219 644 170 565 170"),
        (500, "M 565 170 H 225"),
        (504, LEFT),
        (460, "M 225 390 H 525"),
    ]


def build_busan_diagram(distance):
    variants = []
    for d in DISTANCES:
        pieces = route_pieces(d)
        points = calibrate(pieces)
        positions = timing_points(d)
        markers = []
        for metre in sorted(set(positions.values()) - {d}):
            codes = [c for c, m in positions.items() if m == metre]
            x, y = at(points, metre)
            markers.append(
                dict(
                    code=codes[0],
                    aliases=codes,
                    elapsed=metre,
                    remaining=d - metre,
                    x=round(x, 2),
                    y=round(y, 2),
                    label_x=0 if y >= 365 else 23,
                    label_y=28 if y >= 384 else -20 if y >= 365 else 5,
                    label_anchor="middle" if y >= 365 else "start",
                    action={"S1F": "early", "G3F": "600", "G1F": "200"}.get(codes[0], codes[0]),
                )
            )
        boundaries = sorted({0, *positions.values()})
        metric = dict(
            total=sum(m for m, _ in pieces),
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
        label = (
            "연장주로 출발"
            if d == 1000
            else "뒤쪽 직선 출발"
            if d <= 1600
            else "내주로 출발 · 안쪽 곡선"
            if d == 1800
            else "내주로 출발 · 바깥쪽 곡선 합류"
            if d in (1900, 2000)
            else "외주로 출발"
        )
        variants.append(
            dict(
                distance=d,
                start_x=x,
                start_y=y,
                path=span(points, 0, d),
                label=label,
                description="공식 평면도 기반 개략 경로입니다. "
                + (
                    "과거 시행 거리입니다."
                    if d in (1500, 1900)
                    else "구간 지점을 선택해 기록을 확인하세요."
                ),
                selected=d == distance,
                metric=metric,
            )
        )
    return dict(
        # Outer boundary, including both chute mouths. The interior is a
        # separate green island; it must not be painted as one wide sand lane.
        surface=(
            "M 214 94 L 244 114 L 201 160 H 658 V 180 H 629 "
            "C 675 203 704 240 704 280 C 704 348 649 402 565 402 "
            "H 116 V 380 H 162 C 120 358 97 323 97 280 "
            "C 97 240 113 209 139 181 Z"
        ),
        field=(
            "M 225 181 H 565 C 638 181 683 226 683 280 "
            "C 683 336 638 379 565 379 H 225 C 161 379 119 337 119 280 "
            "C 119 225 161 181 225 181 Z"
        ),
        inner_lane=(
            "M 401 192 H 225 C 166 192 130 230 130 280 "
            "C 130 321 154 350 190 360 M 225 372 H 450 "
            "C 515 372 555 333 555 280 C 555 230 516 192 450 192"
        ),
        connectors="M 450 192 " + TOP_MERGE + " M 190 360 " + BOTTOM_MERGE,
        training=(
            "M 225 222 H 450 C 491 222 520 246 520 280 "
            "C 520 317 491 341 450 341 H 225 C 182 341 155 317 155 280 "
            "C 155 246 182 222 225 222 Z"
        ),
        rails=[],
        corners=[
            dict(label="3코너 구역", x=265, y=143),
            dict(label="2코너 구역", x=570, y=143),
            dict(label="1코너 구역", x=576, y=431),
            dict(label="4코너 구역", x=222, y=431),
        ],
        variants=variants,
        selected=next((v for v in variants if v["selected"]), None),
        plan_url=PLAN_URL,
        guide_url=GUIDE_URL,
    )
