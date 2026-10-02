from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from horse_racing.analysis.features.base import _SECTIONS_QUERY
from horse_racing.db.base import Base
from horse_racing.db.models import (
    Horse,
    Race,
    Racecourse,
    RaceEntry,
    RacePointSourceBatch,
    RaceResult,
    RaceSectionResult,
    RaceSectionTime,
)
from horse_racing.services.section_read import (
    SectionObservation,
    load_official_segment_times,
    load_section_observations,
)
from horse_racing.web.race_page import (
    _closing_time,
    _entry_cumulative_times,
    _section_columns,
    load_race_page,
)


def test_score_sheet_wins_and_legacy_only_points_survive(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'sections.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        batch = RacePointSourceBatch(
            source_file="test/seoul_2026.sqlite3",
            source_sha256="a" * 64,
            meet_code=1,
            race_year=2026,
            section_row_count=2,
            passing_group_row_count=0,
            loaded_at_ms=1,
        )
        race = Race(
            racecourse=Racecourse(kra_meet_code=1, code="SEOUL", name_ko="서울"),
            race_date_local=date(2026, 9, 20),
            race_number=1,
            distance_m=1200,
            status="completed",
        )
        entry = RaceEntry(
            race=race,
            horse=Horse(kra_horse_id="cutover-1", name_ko="검증마"),
            horse_number=1,
        )
        session.add_all([batch, entry, RaceResult(race_entry=entry, finish_position=1)])
        session.flush()
        session.add_all(
            [
                RaceSectionResult(
                    race_entry_id=entry.id,
                    section_code="G3F",
                    elapsed_time_ms=39_000,
                    position=6,
                    time_basis="closing",
                ),
                RaceSectionResult(
                    race_entry_id=entry.id,
                    section_code="4C",
                    elapsed_time_ms=45_000,
                    position=2,
                    time_basis="cumulative",
                ),
                RaceSectionTime(
                    race_entry_id=entry.id,
                    point_code="G3F",
                    time_kind="closing",
                    elapsed_time_ms=36_000,
                    source_name="score_sheet",
                    source_batch_id=batch.id,
                ),
                RaceSectionTime(
                    race_entry_id=entry.id,
                    point_code="G3F",
                    time_kind="cumulative",
                    elapsed_time_ms=40_000,
                    position_raw=3,
                    source_name="score_sheet",
                    source_batch_id=batch.id,
                ),
            ]
        )
        session.commit()

        observed = load_section_observations(session, [entry.id])[entry.id]
        rows = {row.section_code: row for row in observed}
        assert rows["G3F"].elapsed_time_ms == 36_000
        assert rows["G3F"].position == 3
        assert rows["G3F"].time_basis == "closing"
        assert rows["G3F"].cumulative_time_ms == 40_000
        assert rows["G3F"].closing_time_ms == 36_000
        assert rows["4C"].elapsed_time_ms == 45_000

        from sqlalchemy import text

        feature_rows = session.execute(text(_SECTIONS_QUERY)).mappings().all()
        feature_by_code = {row["section_code"]: row for row in feature_rows}
        assert len(feature_rows) == 2
        assert feature_by_code["G3F"]["elapsed_time_ms"] == 36_000
        assert feature_by_code["G3F"]["position"] == 3

        session.delete(
            session.query(RaceSectionResult)
            .filter_by(race_entry_id=entry.id, section_code="G3F")
            .one()
        )
        session.commit()
        after = load_section_observations(session, [entry.id])[entry.id]
        assert {row.section_code: row.elapsed_time_ms for row in after} == {
            "G3F": 36_000,
            "4C": 45_000,
        }


def test_busan_official_intervals_do_not_become_checkpoints(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'busan-sections.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        batch = RacePointSourceBatch(
            source_file="test/busan_2026.sqlite3",
            source_sha256="b" * 64,
            meet_code=3,
            race_year=2026,
            section_row_count=7,
            passing_group_row_count=0,
            loaded_at_ms=1,
        )
        race = Race(
            racecourse=Racecourse(kra_meet_code=3, code="BUSAN", name_ko="부산경남"),
            race_date_local=date(2026, 9, 18),
            race_number=1,
            distance_m=1000,
            status="completed",
        )
        entry = RaceEntry(
            race=race,
            horse=Horse(kra_horse_id="busan-cutover-1", name_ko="검증마"),
            horse_number=9,
        )
        session.add_all([batch, entry, RaceResult(
            race_entry=entry, finish_position=1, finish_time_ms=60_900,
        )])
        session.flush()
        for code, kind, time_ms, position in (
            ("S1F", "cumulative", 13_600, 2),
            ("G3F", "cumulative", 25_000, 3),
            ("G3F", "closing", 35_900, None),
            ("G1F", "cumulative", 48_400, 2),
            ("G1F", "closing", 12_500, None),
            ("S-1F", "segment", 13_600, None),
            ("4-2F", "segment", 23_200, None),
        ):
            session.add(RaceSectionTime(
                race_entry_id=entry.id,
                point_code=code,
                time_kind=kind,
                elapsed_time_ms=time_ms,
                position_raw=position,
                source_name="score_sheet",
                source_batch_id=batch.id,
            ))
        session.flush()

        entry._effective_sections = load_section_observations(session, [entry.id])[entry.id]
        observed = {row.section_code: row for row in entry._effective_sections}
        assert set(observed) == {"S1F", "G3F", "G1F"}
        assert observed["G3F"].cumulative_time_ms == 25_000
        assert observed["G3F"].closing_time_ms == 35_900
        assert _entry_cumulative_times(entry, meet_code=3) == {
            "S1F": 13_600, "G3F": 25_000, "G1F": 48_400, "FIN": 60_900,
        }
        assert _closing_time(entry, "G3F", 3) == "35.9초"
        assert _closing_time(entry, "G1F", 3) == "12.5초"
        assert [column.code for column in _section_columns(race)] == [
            "S1F", "G3F", "G1F", "FIN",
        ]
        assert load_official_segment_times(session, [entry.id])[entry.id] == {
            "S-1F": 13_600, "4-2F": 23_200,
        }
        page = load_race_page(session, race_id=race.id)
        assert page is not None
        assert page.official_segment_columns == ["S-1F", "4-2F"]
        assert page.official_segment_rows[0][1] == ["13.6초", "23.2초"]
        assert [column.code for column in page.section_columns] == [
            "S1F", "G3F", "G1F", "FIN",
        ]


def test_venue_specific_closing_and_cumulative_times():
    cases = (
        (1, "G3F", 36_200, 36_600, 72_800, 36_200, "36.6초"),
        (2, "G3F", None, 49_400, 74_300, 24_900, "49.4초"),
        (4, "G3F", 76_500, None, 118_000, 76_500, "41.5초"),
    )
    for meet, code, cumulative_ms, closing_ms, finish_ms, expected, closing in cases:
        entry = RaceEntry()
        entry.result = RaceResult(finish_time_ms=finish_ms)
        entry._effective_sections = [SectionObservation(
            race_entry_id=1,
            section_code=code,
            elapsed_time_ms=closing_ms if closing_ms is not None else cumulative_ms,
            position=None,
            time_basis="closing" if closing_ms is not None else "cumulative",
            source_kind="score_sheet",
            cumulative_time_ms=cumulative_ms,
            closing_time_ms=closing_ms,
        )]
        assert _entry_cumulative_times(entry, meet_code=meet)[code] == expected
        assert _closing_time(entry, code, meet) == closing
