"""Display coordinates traced from KRA's Seoul Racing Track plan (not metres).

The open rail ends matter: at 2C runners can enter the outer backstretch,
and at 4C the inside route merges smoothly into the shared finish straight.
"""

from horse_racing.web.seoul_metric import metric_route

PLAN_URL = "https://race.kra.co.kr/images/sub/seoul_racemap02.jpg"
GUIDE_URL = "https://race.kra.co.kr/chulmainfo/RacingcourseStructure.do?Act=02&Sub=11&meet=1"

SURFACE = (
    "M 234 30 L 250 53 L 131 124 C 71 160 49 234 62 300 "
    "C 70 205 129 139 211 139 H 715 V 162 H 680 "
    "C 727 198 747 260 750 322 L 758 345 Q 764 360 742 365 "
    "Q 724 369 708 380 C 673 415 636 434 593 434 H 54 V 408 H 122 "
    "C 45 356 19 292 34 227 C 46 152 88 112 136 84 Z"
)
FIELD = (
    "M 212 190 H 590 C 648 190 690 231 690 285 "
    "C 690 341 650 378 590 378 H 213 C 156 378 119 338 119 285 "
    "C 119 232 157 190 212 190 Z"
)
RAILS = [
    "M 595 164 H 213 C 139 164 89 218 89 285 C 89 325 109 358 141 378",
    "M 212 405 H 590 C 669 405 722 351 722 287 C 722 238 698 204 661 181",
]
OUTER_LEFT = "H 213 C 127 151 74 211 74 285 C 74 360 130 418 213 418 H 555"
INNER_LEFT = (
    "H 213 C 149 178 105 224 105 285 C 105 333 135 366 165 385 "
    "Q 185 400 195 409 Q 203 418 213 418 H 555"
)
INNER_RIGHT = "H 590 C 658 392 706 346 706 285 C 706 237 679 202 638 185"
OUTER_RIGHT = "H 590 C 678 418 738 356 738 285 C 738 210 678 151 590 151"


def build_seoul_diagram(distance: int) -> dict:
    variants = []

    def add(d, start, path, label, description):
        variants.append(
            dict(
                distance=d,
                start_x=start[0],
                start_y=start[1],
                path=path,
                label=label,
                description=description,
                selected=d == distance,
                metric=metric_route(d, *start),
            )
        )

    add(
        1000,
        (234, 43),
        "M 234 43 L 129 108 C 68 145 35 212 46 281 C 51 337 86 383 144 407 Q 176 418 213 418 H 555",
        "1,000m 연장주로",
        "10시 방향 연장주로에서 출발해 4코너 쪽으로 진입합니다.",
    )
    for d, x in ((1200, 516), (1300, 598), (1400, 684)):
        add(
            d,
            (x, 151),
            f"M {x} 151 " + OUTER_LEFT,
            "뒤쪽 직선 · 외주로",
            "뒤쪽 직선에서 출발해 3·4코너를 돌아 결승으로 향합니다.",
        )
    add(
        1600,
        (741, 345),
        "M 741 345 C 730 250 713 205 678 177 Q 643 151 590 151 " + OUTER_LEFT,
        "1코너 쪽 보조 출발부",
        "오른쪽 곡선의 보조 출발부에서 2코너 쪽으로 진입합니다.",
    )
    for d, x in ((1700, 468), (1800, 383), (1900, 296)):
        add(
            d,
            (x, 392),
            f"M {x} 392 " + INNER_RIGHT + " Q 620 178 590 178 " + INNER_LEFT,
            "내주로 출발 · 내주로 진행",
            "관람대 앞에서 출발해 내주로를 돌고 결승 직선으로 합류합니다.",
        )
    add(
        2000,
        (296, 392),
        "M 296 392 " + INNER_RIGHT + " Q 617 168 590 151 " + OUTER_LEFT,
        "내주로 출발 → 2코너 외주로",
        "1,900m와 같은 출발부를 사용하며 2코너에서 외주로로 나갑니다.",
    )
    add(
        2300,
        (122, 418),
        "M 122 418 " + OUTER_RIGHT + " " + OUTER_LEFT,
        "관람대 앞 연장부 · 외주로",
        "7시 방향 연장부에서 출발해 외주로를 돌아 결승에 도착합니다.",
    )
    selected = next((v for v in variants if v["selected"]), None)
    return dict(
        surface=SURFACE,
        field=FIELD,
        rails=RAILS,
        variants=variants,
        selected=selected,
        plan_url=PLAN_URL,
        guide_url=GUIDE_URL,
    )
