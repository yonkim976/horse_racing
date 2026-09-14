import pytest

from horse_racing.db.models import Horse, Race, Racecourse, RaceEntry, RaceResult, RaceSectionResult
from horse_racing.web.busan_diagram import DISTANCES, build_busan_diagram
from horse_racing.web.race_page import _section_columns, _section_rows


@pytest.mark.parametrize("distance", DISTANCES)
def test_busan_routes_end_at_finish_and_have_exact_metric_total(distance):
    route = build_busan_diagram(distance)["selected"]
    assert route["metric"]["total"] == distance
    assert route["path"].endswith("525.00 390.00")
    assert all(0 < m["elapsed"] < distance for m in route["metric"]["markers"])
    assert len({m["elapsed"] for m in route["metric"]["markers"]}) == len(
        route["metric"]["markers"]
    )
    assert route["metric"]["closing200"].endswith("525.00 390.00")


def test_busan_1300_orders_by_distance_even_when_times_missing():
    race = Race(racecourse=Racecourse(kra_meet_code=3), distance_m=1300)
    entry = RaceEntry(
        race=race, horse_id=1, horse_number=1, scratched=False, horse=Horse(id=1, name_ko="테스트")
    )
    entry.result = RaceResult(finish_position=1, finish_time_ms=82600)
    entry.section_results = [
        RaceSectionResult(section_code=code, elapsed_time_ms=time)
        for code, time in [
            ("S1F", 14400),
            ("G6F", 8500),
            ("G4F", 31800),
            ("G3F", 44400),
            ("G2F", 57000),
            ("G1F", 69400),
        ]
    ]
    columns = _section_columns(race)
    assert [c.code for c in columns] == ["G6F", "S1F", "G4F", "G3F", "G2F", "G1F", "FIN"]
    assert [c.segment_distance for c in columns] == [
        "100m",
        "100m",
        "300m",
        "200m",
        "200m",
        "200m",
        "200m",
    ]
    rows = _section_rows(race.entries, columns, meet_code=3)
    assert rows[0].cells[1].segment_time == "5.9초"
    entry.section_results[1].elapsed_time_ms = None
    assert _section_columns(race)[0].code == "G6F"


def test_unknown_busan_distance_has_no_invented_route():
    assert build_busan_diagram(1700)["selected"] is None


def test_shared_finish_checkpoints_do_not_move_between_distances():
    variants = build_busan_diagram(1800)['variants']
    for code in ('G1F', 'G2F'):
        locations = [(m['x'], m['y']) for v in variants
                     for m in v['metric']['markers'] if m['code'] == code]
        assert len(set(locations)) == 1


def test_all_route_pieces_join_without_jumps():
    from horse_racing.web.busan_diagram import route_pieces
    from horse_racing.web.seoul_metric import sample
    for d in DISTANCES:
        pieces = route_pieces(d)
        for (_, left), (_, right) in zip(pieces, pieces[1:], strict=False):
            assert sample(left)[-1] == sample(right)[0], d
