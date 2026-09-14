"""Piecewise metre calibration of the display drawing, from KRA's dimension plan.

Each straight/curve is calibrated separately; SVG pixels are never treated as metres.
Curve shapes remain schematic. Only independently cross-checked corner distances
are shown; these are reference positions, not surveyed timing-line coordinates.
"""

import math
import re

# 2026 KRA result sheets: minimum individual corner time compared with the
# separate leader passage-distance table (S1F for the 1700m 1C).
# See docs/SEOUL_CORNER_POSITIONS_2026-09-09.md. Do not extrapolate missing corners.
CORNER_REFERENCE_METRES = {
    1000: {"3C": 200},
    1200: {"3C": 400},
    1300: {"3C": 500},
    1400: {"3C": 600},
    1600: {"2C": 200, "3C": 800},
    1700: {"1C": 200},
    2000: {"1C": 400, "2C": 600, "3C": 1200},
    2300: {"2C": 900, "3C": 1500},
}


def sample(path):
    tokens = iter(re.findall(r"[MLHCQ]|-?\d+(?:\.\d+)?", path))
    current = (0.0, 0.0)
    points = []
    for command in tokens:
        n = {"M": 2, "L": 2, "H": 1, "C": 6, "Q": 4}[command]
        values = [float(next(tokens)) for _ in range(n)]
        controls = (
            [current, (values[0], current[1])]
            if command == "H"
            else [current, *zip(values[::2], values[1::2], strict=True)]
        )
        if command == "M":
            points.append(controls[-1])
        else:
            for i in range(1, 81):
                t, row = i / 80, controls
                while len(row) > 1:
                    row = [
                        tuple(a[j] * (1 - t) + b[j] * t for j in (0, 1))
                        for a, b in zip(row, row[1:], strict=False)
                    ]
                points.append(row[0])
        current = controls[-1]
    return points


def calibrate(pieces):
    result, elapsed = [], 0
    for metres, path in pieces:
        points = sample(path)
        lengths = [0.0]
        for a, b in zip(points, points[1:], strict=False):
            lengths.append(lengths[-1] + math.dist(a, b))
        result.extend(
            (elapsed + length / lengths[-1] * metres, *point)
            for length, point in zip(lengths, points, strict=True)
        )
        elapsed += metres
    return result


def at(points, metres):
    for a, b in zip(points, points[1:], strict=False):
        if a[0] <= metres <= b[0] and b[0] > a[0]:
            t = (metres - a[0]) / (b[0] - a[0])
            return tuple(a[j] + t * (b[j] - a[j]) for j in (1, 2))
    return points[-1][1:]


def span(points, start, end):
    coords = [at(points, start), *(p[1:] for p in points if start < p[0] < end), at(points, end)]
    return "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in coords)


def metric_route(distance, x, y):
    outer_left = "M 213 151 C 127 151 74 211 74 285 C 74 360 130 418 213 418"
    inner_left = (
        "M 213 178 C 149 178 105 224 105 285 C 105 333 135 366 165 385 "
        "Q 185 400 195 409 Q 203 418 213 418"
    )
    inner_right = "M 590 392 C 658 392 706 346 706 285 C 706 237 679 202 638 185"
    if distance == 1000:
        pieces = [
            (130, "M 234 43 L 129 108"),
            (470, "M 129 108 C 68 145 35 212 46 281 C 51 337 86 383 144 407 Q 176 418 213 418"),
        ]
    elif distance in (1200, 1300, 1400):
        pieces = [(distance - 850, f"M {x} 151 H 213"), (450, outer_left)]
    elif distance == 1600:
        pieces = [
            (300, "M 741 345 C 730 250 713 205 678 177 Q 643 151 590 151"),
            (450, "M 590 151 H 213"),
            (450, outer_left),
        ]
    elif distance in (1700, 1800, 1900, 2000):
        inner = distance != 2000
        pieces = [
            (distance - (1550 if inner else 1650), f"M {x} {y} H 590"),
            (350, inner_right + (" Q 620 178 590 178" if inner else " Q 617 168 590 151")),
            (450, f"M 590 {178 if inner else 151} H 213"),
            (350 if inner else 450, inner_left if inner else outer_left),
        ]
    elif distance == 2300:
        pieces = [
            (550, "M 122 418 H 590"),
            (450, "M 590 418 C 678 418 738 356 738 285 C 738 210 678 151 590 151"),
            (450, "M 590 151 H 213"),
            (450, outer_left),
        ]
    else:
        return None
    pieces.append((400, "M 213 418 H 555"))
    points = calibrate(pieces)
    corners = CORNER_REFERENCE_METRES.get(distance, {})
    markers = []
    for code, metre, action in [
        ("S1F", 200, "early"),
        ("G3F", distance - 600, "600"),
        ("G1F", distance - 200, "200"),
    ]:
        px, py = at(points, metre)
        markers.append(
            dict(
                code=code,
                elapsed=metre,
                remaining=distance - metre,
                x=round(px, 2),
                y=round(py, 2),
                action=action,
                aliases=[code, *(c for c, m in corners.items() if m == metre)],
            )
        )
    for code, metre in corners.items():
        if metre == 200:
            continue  # One marker for coincident S1F/corner reference positions.
        px, py = at(points, metre)
        markers.append(dict(code=code, elapsed=metre, remaining=distance - metre,
                            x=round(px, 2), y=round(py, 2), action=code, aliases=[code]))
    checkpoints = sorted({0, 200, *corners.values(), distance - 600, distance - 200, distance})
    return dict(
        total=sum(p[0] for p in pieces),
        markers=markers,
        early=span(points, 0, 200),
        closing600=span(points, distance - 600, distance),
        closing400=span(points, distance - 600, distance - 200),
        closing200=span(points, distance - 200, distance),
        boundaries=[p[0] for p in pieces],
        # Full paths allow highlighting the actual selected record interval,
        # including when an intermediate record is missing. JS supplies endpoints.
        reference_points={"S1F": 200, **corners, "G3F": distance - 600,
                          "G1F": distance - 200, "FIN": distance},
        intervals=[dict(start=a, end=b, path=span(points, a, b))
                   for a in checkpoints
                   for b in checkpoints
                   if a < b],
    )
