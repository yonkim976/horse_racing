import pytest

from horse_racing.db.models import Horse, Race, Racecourse, RaceEntry, RaceResult, RaceSectionResult
from horse_racing.web.race_page import (
    _map_checkpoints,
    _section_columns,
    _section_rows,
    build_section_chart_data,
    cumulative_finish_margins,
    parse_finish_margin,
)


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
    points = _map_checkpoints(race.distance_m, columns)
    assert [(p["label"], p["start"], p["span"]) for p in points[:2]] == [
        ("2C", 0, 100), ("S1F", 100, 100)
    ]
    assert sum(p["span"] for p in points) == 1300


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
    points = _map_checkpoints(race.distance_m, columns)
    assert [(p["label"], p["start"], p["span"]) for p in points[:2]] == [
        ("S1F/1C", 0, 210), ("2C", 210, 200)
    ]
    assert sum(p["span"] for p in points) == 1610
    assert points[-1]["remaining"] == 0


def test_explicit_time_basis_overrides_numeric_guess():
    from horse_racing.web.race_page import derive_section_cumulative_times
    assert derive_section_cumulative_times(
        {"G3F": 50000, "G1F": 45000}, finish_time_ms=100000, meet_code=1,
        time_bases={"G3F": "cumulative", "G1F": "cumulative"},
    ) == {"G3F": 50000, "G1F": 45000}
    assert derive_section_cumulative_times(
        {"G1F": 60000}, finish_time_ms=100000, meet_code=1,
        time_bases={"G1F": "closing"},
    ) == {"G1F": 40000}


def test_seoul_keeps_corners_distinct_and_displays_closing_windows():
    race = Race(racecourse=Racecourse(kra_meet_code=1), distance_m=1200)
    for number in (1, 2):
        entry = RaceEntry(race=race, horse_id=number, horse_number=number, scratched=False,
                          horse=Horse(id=number, name_ko=f"말{number}"))
        entry.result = RaceResult(finish_position=number, finish_time_ms=80000)
        entry.section_results = [RaceSectionResult(section_code=code, elapsed_time_ms=time,
                                                  time_basis="cumulative", position=number)
                                 for code, time in [("S1F", 14000), ("3C", 28000),
                                                    ("G3F", 40000), ("4C", 45000), ("G1F", 66000)]]
    columns = _section_columns(race)
    assert [c.label for c in columns] == ["S1F", "3C", "G3F", "4C", "G1F", "FIN"]
    row = _section_rows(race.entries, columns, meet_code=1)[0]
    assert row.closing_600 == "40.0초"
    assert row.closing_200 == "14.0초"
    assert row.cells[2].segment_time == "12.0초"
    # Equal rounded times cannot make different Seoul corner/furlong locations merge.
    for entry in race.entries:
        entry.section_results[2].elapsed_time_ms = 28000
    assert "3C/G3F" not in [c.label for c in _section_columns(race)]


def test_passing_group_parser_preserves_packs_and_official_separators():
    from horse_racing.web.race_page import parse_passing_groups

    groups = parse_passing_groups('(^1,6),(3,7),(4,5,10),(9,11)-2=8≡12', set(range(1, 13)))
    assert [group['horses'] for group in groups] == [
        [1, 6], [3, 7], [4, 5, 10], [9, 11], [2], [8], [12]
    ]
    assert [group['gap'] for group in groups] == ['', ',', ',', ',', '-', '=', '≡']


@pytest.mark.parametrize(
    'notation', ['(1,1),2', '(1,9)', '(1,2', '1foo2', '1,2)', '1,,(2,1)', '<img>1']
)
def test_invalid_passing_groups_do_not_create_partial_packs(notation):
    from horse_racing.web.race_page import parse_passing_groups
    assert parse_passing_groups(notation, {1, 2}) == []


def test_passing_view_uses_alias_notation_and_preserves_rank_fallback():
    race = make_race()
    columns = _section_columns(race)
    rows = _section_rows(race.entries, columns, meet_code=2)
    chart = build_section_chart_data(columns, rows, {'3C': '(^1,2)-3'})
    points = chart['checkpoints']
    assert points[1]['label'] == '3C/G3F'
    assert points[1]['mode'] == 'official'
    assert [g['horses'] for g in points[1]['groups']] == [[1, 2], [3]]
    assert points[0]['mode'] == 'rank'
    assert all(len(g['horses']) == 1 for g in points[0]['groups'])
    assert points[-1]['mode'] == 'finish'
    assert chart['series'][2]['positionsInferred'][1]


def test_official_packs_keep_horses_without_individual_positions():
    from horse_racing.web.race_page import SectionCell, SectionColumn, SectionEntryRow
    rows = [SectionEntryRow('1', 1, '통과순위미제공', '—', 999,
                            [SectionCell('—', '—', '—', 999)])]
    chart = build_section_chart_data([SectionColumn('2C', '2C')], rows, {'2C': '1'})
    assert chart['series'][0]['positions'] == [None]
    assert chart['checkpoints'][0]['groups'][0]['horses'] == [1]


def test_passing_offsets_use_symbol_midpoints_and_finish_uses_official_margins():
    from horse_racing.web.race_page import SectionCell, SectionColumn, SectionEntryRow
    rows = [
        SectionEntryRow(str(number), number, f'말{number}', f'{number}위', number,
                        [SectionCell(f'{number}위', '—', '—', number)] * 2,
                        finish_time_ms=finish, finish_margin=margin)
        for number, finish, margin in [(1, 60_000, ""), (2, 60_000, "목"),
                                       (3, 60_200, "1"), (4, 60_700, "2½"),
                                       (5, None, "")]
    ]
    chart = build_section_chart_data(
        [SectionColumn('4C', '4C'), SectionColumn('FIN', 'FIN')], rows,
        {'4C': '1,2-3=4≡5'},
    )
    points = chart['checkpoints']
    assert [g['distanceLengths'] for g in points[0]['groups']] == [0, 1.5, 5, 12.5, 22.5]
    assert [g['distanceLengths'] for g in points[1]['groups']] == [0, .3, 1.3, 3.8, None]
    assert chart['series'][0]['finishTimeMs'] == 60_000
    assert chart['series'][1]['finishMargin'] == '목'


def test_missing_winner_does_not_invent_a_finish_gap():
    from horse_racing.web.race_page import SectionCell, SectionColumn, SectionEntryRow
    rows = [SectionEntryRow('2', 2, '말2', '2위', 2,
                            [SectionCell('2위', '—', '—', 2)], finish_time_ms=60_200)]
    chart = build_section_chart_data([SectionColumn('FIN', 'FIN')], rows)
    assert chart['checkpoints'][0]['groups'][0]['distanceLengths'] is None


@pytest.mark.parametrize(("raw", "expected"), [
    ("1", 1), ("2.5", 2.5), ("½", .5), ("2½", 2.5), ("1¼", 1.25),
    ("¾", .75), ("⅛", .125), ("1/2", .5), ("2 1/2", 2.5), (" 1 마신 ", 1),
    ("코", .05), ("머리", .15), ("목", .3), ("동착", 0), ("대차", 10),
    ("", None), ("—", None), ("1/0", None), ("-2", None), ("미상", None),
])
def test_parse_official_finish_margins(raw, expected):
    assert parse_finish_margin(raw) == expected


def finish_row(number, rank, margin):
    from horse_racing.web.race_page import SectionCell, SectionEntryRow
    return SectionEntryRow(str(number), number, f"말{number}", f"{rank}위", rank,
                           [SectionCell(f"{rank}위", "—", "—", rank)],
                           finish_margin=margin)


def test_official_margins_work_without_times_and_accumulate_tied_places_once():
    rows = [finish_row(1, 1, ""), finish_row(2, 2, "목"), finish_row(3, 2, "목"),
            finish_row(4, 4, "1¼")]
    assert cumulative_finish_margins(rows) == {1: 0, 2: .3, 3: .3, 4: 1.55}


@pytest.mark.parametrize("missing", ["margin", "placing"])
def test_missing_margin_or_placing_breaks_cumulative_chain(missing):
    rows = [finish_row(1, 1, ""), finish_row(2, 2, ""), finish_row(3, 3, "1")]
    if missing == "placing":
        rows.pop(1)
    offsets = cumulative_finish_margins(rows)
    assert offsets[1] == 0
    assert offsets[3] is None
