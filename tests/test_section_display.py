import pytest

from horse_racing.db.models import Horse, Race, Racecourse, RaceEntry, RaceResult, RaceSectionResult
from horse_racing.web.race_page import _section_columns, _section_rows, build_section_chart_data


def make_race():
    race = Race(racecourse=Racecourse(kra_meet_code=2), distance_m=1000)
    for number, finish, corner in [(1, 80000, 30000), (2, 90000, 40000), (3, 82000, None)]:
        entry = RaceEntry(
            race=race,
            horse_id=number,
            horse_number=number,
            scratched=False,
            horse=Horse(id=number, name_ko=f"말{number}"),
        )
        entry.result = RaceResult(finish_position=number, finish_time_ms=finish)
        entry.section_results = [
            RaceSectionResult(section_code="S1F", elapsed_time_ms=15000 + number * 100),
            RaceSectionResult(section_code="G3F", elapsed_time_ms=50000 if corner else 49000),
            RaceSectionResult(section_code="G1F", elapsed_time_ms=16000),
        ]
        if corner:
            entry.section_results.append(
                RaceSectionResult(
                    section_code="3C",
                    elapsed_time_ms=corner,
                    position=number,
                )
            )
    return race


def test_combines_normalized_checkpoints_and_uses_missing_alias():
    race = make_race()
    columns = _section_columns(race)
    assert [c.label for c in columns] == ["S1F", "3C/G3F", "G1F", "FIN"]
    rows = _section_rows(race.entries, columns, meet_code=2)
    assert rows[0].cells[1].cumulative_time == "30.0초"
    assert rows[0].cells[1].segment_time == "14.9초"
    assert rows[2].cells[1].cumulative_time == "33.0초"
    assert rows[2].cells[1].position_inferred
    assert rows[2].cells[1].position == "2위"
    chart = build_section_chart_data(columns, rows)
    assert chart["labels"] == ["S1F", "3C/G3F", "G1F", "FIN"]
    assert len(chart["series"][0]["positions"]) == 4


@pytest.mark.parametrize("conflict", ["time", "rank", "insufficient"])
def test_does_not_hide_conflicting_or_unproven_checkpoints(conflict):
    race = make_race()
    if conflict == "time":
        race.entries[1].section_results[-1].elapsed_time_ms += 100
    elif conflict == "rank":
        race.entries[1].section_results[1].position = 3
    else:
        race.entries[1].section_results.pop()
    labels = [c.label for c in _section_columns(race)]
    assert "3C" in labels and "G3F" in labels
    assert "3C/G3F" not in labels


@pytest.mark.parametrize(
    "distance,early,middle",
    [
        (900, 200, 100),
        (1000, 200, 200),
        (1110, 210, 300),
        (1610, 210, 800),
    ],
)
def test_jeju_distances(distance, early, middle):
    race = make_race()
    race.distance_m = distance
    columns = _section_columns(race)
    assert columns[0].location == f"출발 후 {early}m"
    assert columns[0].segment_distance == f"{early}m"
    assert columns[1].segment_distance == f"약 {middle}m"
    assert columns[1].location == "결승 약 600m 전"


def test_missing_checkpoint_does_not_extend_next_interval():
    race = make_race()
    race.entries[0].section_results = [
        s for s in race.entries[0].section_results if s.section_code != "G1F"
    ]
    columns = _section_columns(race)
    row = _section_rows(race.entries, columns, meet_code=2)[0]
    assert row.cells[-1].segment_time == "—"
    assert row.cells[-1].cumulative_time == "1:20.0"
    assert row.closing_600 == "50.0초"
    assert row.closing_200 == "—"


def test_closing_record_is_not_checkpoint_cumulative():
    race = make_race()
    row = _section_rows(race.entries, _section_columns(race), meet_code=2)[0]
    assert row.cells[1].cumulative_time == "30.0초"
    assert row.closing_600 == "50.0초"
    assert row.closing_200 == "16.0초"


def test_1300_second_corner_precedes_s1f():
    race = make_race()
    race.distance_m = 1300
    for entry in race.entries:
        entry.section_results.append(
            RaceSectionResult(
                section_code="2C",
                elapsed_time_ms=10000 + entry.horse_number * 100,
            )
        )
    columns = _section_columns(race)
    assert [c.label for c in columns][:2] == ["2C", "S1F"]
    assert columns[0].segment_label == "START → 2C"
    assert columns[0].segment_distance == "약 100m"
    assert columns[1].segment_distance == "약 100m"


def test_1610_groups_first_corner_with_s1f_and_keeps_second_corner():
    race = make_race()
    race.distance_m = 1610
    for entry in race.entries:
        entry.section_results.extend(
            [
                RaceSectionResult(
                    section_code="1C", elapsed_time_ms=15100 + (entry.horse_number - 1) * 100
                ),
                RaceSectionResult(
                    section_code="2C", elapsed_time_ms=22000 + entry.horse_number * 100
                ),
            ]
        )
    columns = _section_columns(race)
    assert [c.label for c in columns][:2] == ["S1F/1C", "2C"]
    assert columns[0].location == "출발 후 210m"
    assert columns[1].segment_distance == "약 200m"
