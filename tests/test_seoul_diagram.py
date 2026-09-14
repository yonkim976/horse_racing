import re

import pytest

from horse_racing.web.seoul_diagram import build_seoul_diagram


def sample_path(path):
    """Independent sampling for containment checks of our restricted SVG vocabulary."""
    tokens = iter(re.findall(r"[MLHVCQZ]|-?\d+(?:\.\d+)?", path))
    points = []
    current = (0, 0)
    for command in tokens:
        if command == "Z":
            points.append(points[0])
            continue
        count = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "Q": 4}[command]
        numbers = [float(next(tokens)) for _ in range(count)]
        if command in ("M", "L"):
            controls = [current, tuple(numbers)]
        elif command == "H":
            controls = [current, (numbers[0], current[1])]
        elif command == "V":
            controls = [current, (current[0], numbers[0])]
        else:
            controls = [current, *list(zip(numbers[::2], numbers[1::2], strict=True))]
        if command != "M":
            for i in range(1, 41):
                t = i / 40
                row = controls
                while len(row) > 1:
                    row = [
                        tuple((1 - t) * a[j] + t * b[j] for j in (0, 1))
                        for a, b in zip(row, row[1:], strict=False)
                    ]
                points.append(row[0])
        else:
            points.append(controls[-1])
        current = controls[-1]
    return points


def crosses(a, b, c, d):
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return side(a, b, c) * side(a, b, d) < -1e-8 and side(c, d, a) * side(c, d, b) < -1e-8


def inside(point, polygon):
    x, y = point
    result = False
    for (ax, ay), (bx, by) in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            result = not result
    return result


@pytest.mark.parametrize("distance", [1000, 1200, 1300, 1400, 1600, 1700, 1800, 1900, 2000, 2300])
def test_standard_routes_stay_on_racing_surface_and_finish_at_same_line(distance):
    diagram = build_seoul_diagram(distance)
    route = diagram["selected"]
    points = sample_path(route["path"])
    assert points[0] == (route["start_x"], route["start_y"])
    assert points[-1] == (555, 418)
    surface, field = sample_path(diagram["surface"]), sample_path(diagram["field"])
    for point in points:
        assert inside(point, surface), (distance, "outside track", point)
        assert not inside(point, field), (distance, "inside infield", point)

    for rail in diagram["rails"]:
        rail_points = sample_path(rail)
        for a, b in zip(points, points[1:], strict=False):
            for c, d in zip(rail_points, rail_points[1:], strict=False):
                assert not crosses(a, b, c, d), (distance, "crossed rail", a, b)


def test_1900_and_2000_share_gate_but_diverge_at_second_corner():
    a, b = (build_seoul_diagram(d)["selected"] for d in (1900, 2000))
    assert (a["start_x"], a["start_y"]) == (b["start_x"], b["start_y"])
    assert a["path"] != b["path"]
    assert "590 178" in a["path"] and "590 151" in b["path"]


def test_unverified_historical_distance_does_not_invent_start():
    assert build_seoul_diagram(1100)["selected"] is None


@pytest.mark.parametrize("distance", [1000, 1200, 1300, 1400, 1600, 1700, 1800, 1900, 2000, 2300])
def test_metric_calibration_keeps_distance_and_marked_spans_on_track(distance):
    diagram = build_seoul_diagram(distance)
    metric = diagram["selected"]["metric"]
    assert metric["total"] == distance
    assert metric["boundaries"][-1] == 400
    fixed = [m for m in metric["markers"] if m["action"] in ("early", "600", "200")]
    assert [m["elapsed"] for m in fixed] == [200, distance - 600, distance - 200]
    # All routes share the final straight and its midpoint, irrespective of full lap length.
    g1f = fixed[-1]
    assert (g1f["x"], g1f["y"]) == (384, 418)
    from horse_racing.web.seoul_metric import sample

    surface, field = sample_path(diagram["surface"]), sample_path(diagram["field"])
    for key in ("early", "closing400", "closing200"):
        # Generated paths are polylines; vertices suffice for this drawn surface.
        points = sample(metric[key])[::80]
        for point in points:
            assert inside(point, surface), (distance, key, point)
            assert not inside(point, field), (distance, key, point)
    assert sample(metric["closing200"])[-1] == (555, 418)


def test_corner_reference_markers_merge_and_leave_unverified_positions_unmapped():
    for distance, corner in [(1000, "3C"), (1600, "2C"), (1700, "1C")]:
        metric = build_seoul_diagram(distance)["selected"]["metric"]
        shared = [m for m in metric["markers"] if corner in m["aliases"]]
        assert len(shared) == 1
        assert shared[0]["aliases"] == ["S1F", corner]
        assert shared[0]["elapsed"] == 200
    for distance in (1700, 1800, 1900):
        points = build_seoul_diagram(distance)["selected"]["metric"]["reference_points"]
        assert "3C" not in points and "4C" not in points
    assert "1C" not in build_seoul_diagram(2300)["selected"]["metric"]["reference_points"]


def test_corner_interval_highlight_ends_at_reference_points():
    from horse_racing.web.seoul_metric import sample

    metric = build_seoul_diagram(2000)["selected"]["metric"]
    interval = next(i for i in metric["intervals"] if (i["start"], i["end"]) == (600, 1200))
    markers = {m["code"]: (m["x"], m["y"]) for m in metric["markers"]}
    points = sample(interval["path"])
    assert points[0] == markers["2C"]
    assert points[-1] == markers["3C"]
