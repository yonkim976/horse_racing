import pytest

from horse_racing.db.models import Horse, Race, Racecourse, RaceEntry, RaceResult, RaceSectionResult
from horse_racing.web.race_page import _section_columns
from horse_racing.web.racecourse import build_racecourse_map
from horse_racing.web.seoul_metric import sample
from horse_racing.web.yeongcheon_diagram import (
    DISTANCES,
    FINISH_Y,
    GOAL_X,
    build_yeongcheon_diagram,
    route_pieces,
)

FINISH = f"{GOAL_X:.2f} {FINISH_Y:.2f}"


@pytest.mark.parametrize("distance", DISTANCES)
def test_yeongcheon_routes_end_at_finish_and_have_exact_metric_total(distance):
    route = build_yeongcheon_diagram(distance)["selected"]
    assert route["metric"]["total"] == distance
    assert route["path"].endswith(FINISH)
    assert route["metric"]["closing200"].endswith(FINISH)
    elapsed = [m["elapsed"] for m in route["metric"]["markers"]]
    assert all(0 < m < distance for m in elapsed)
    assert len(set(elapsed)) == len(elapsed)


def test_all_route_pieces_join_without_jumps():
    for d in DISTANCES:
        pieces = route_pieces(d)
        for (_, left), (_, right) in zip(pieces, pieces[1:], strict=False):
            assert sample(left)[-1] == sample(right)[0], d


def test_shared_closing_checkpoints_do_not_move_between_distances():
    variants = build_yeongcheon_diagram(1200)["variants"]
    for code in ("G1F", "G2F", "G3F"):
        locations = {(m["x"], m["y"]) for v in variants
                     for m in v["metric"]["markers"] if m["code"] == code}
        assert len(locations) == 1, code


def test_long_races_start_inside_and_finish_outside():
    variants = {v["distance"]: v for v in build_yeongcheon_diagram(1800)["variants"]}
    for d in (1800, 1900, 2000):
        assert variants[d]["start_y"] < FINISH_Y
    assert variants[1800]["start_x"] > variants[1900]["start_x"] > variants[2000]["start_x"]
    assert build_yeongcheon_diagram(1700)["selected"] is None


def test_racecourse_map_supports_yeongcheon():
    view = build_racecourse_map(meet_code=4, distance_m=1400)
    assert view is not None
    assert view.course_name == "영천"
    assert view.supported_distance


def test_yeongcheon_sections_use_distance_positions():
    race = Race(racecourse=Racecourse(kra_meet_code=4), distance_m=1400)
    entry = RaceEntry(
        race=race, horse_id=1, horse_number=1, scratched=False, horse=Horse(id=1, name_ko="테스트")
    )
    entry.result = RaceResult(finish_position=1, finish_time_ms=88000)
    entry.section_results = [
        RaceSectionResult(section_code=code, elapsed_time_ms=time)
        for code, time in [("S1F", 13500), ("G4F", 38000), ("G3F", 50500),
                           ("G2F", 63000), ("G1F", 75500)]
    ]
    columns = _section_columns(race)
    assert [c.code for c in columns] == ["S1F", "G4F", "G3F", "G2F", "G1F", "FIN"]
    assert columns[1].location == "출발 후 600m"
    assert [c.segment_distance for c in columns] == ["200m", "400m", "200m", "200m", "200m", "200m"]
