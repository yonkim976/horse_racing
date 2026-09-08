from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from test_race_day import migrated_session

from horse_racing.db.models import (
    Horse,
    IngestionRun,
    OddsSnapshot,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    RaceSectionResult,
    SourceDocument,
)
from horse_racing.parsers.dacom11 import (
    _TRACK,
    Dacom11Entry,
    _is_separator,
    _parse_entry_table,
    _parse_section_table,
    parse_dacom11_report,
)
from horse_racing.services.dacom11 import (
    _EntityResolver,
    _horse_names_match,
    ingest_dacom11_reports,
)


def test_jeju_fixed_columns_keep_empty_fields_and_all_corners():
    entries = parse_dacom11_report(REPORT.encode("cp949"))[0].entries
    header = "순위  마번  G-3F   S-1F   1코너  2코너  3코너  4코너  G-1F   단승식  연승식"
    rows = [
        header,
        "-" * 94,
        "  1     8         0:17.0                             0:15.5     1.8     1.3",
        "  2     4  0:45.6 0:19.9 0:19.9 0:35.5 1:26.3 1:42.0 0:15.2     7.8     6.3",
        "-" * 94,
    ]
    _parse_section_table(rows, entries)
    assert entries[0].g3f_ms is None
    assert entries[0].s1f_ms == 17000
    assert entries[0].g1f_ms == 15500
    assert entries[1].corner_times_ms == {"1C": 19900, "2C": 35500, "3C": 86300, "4C": 102000}


REPORT = """
제목 : 24년12월29일(일)  제 1경주

(서울) 제90일 1000M 국6등급    별정A       경주명 : 일반
경주조건:       R0~0  2세                        날씨:맑음 주로:건조  (3%)
순위상금: 24,750천원   9,900천원   6,300천원   2,250천원   1,800천원
-------------------------------------------------------------------------------------------------
순위 마번    마    명         산지   성별 연령 부담중량  기수명   조교사   마주명           레이팅
-------------------------------------------------------------------------------------------------
  1    8  테스트원             한     수     2    54.5   빅투아르 이준철   손병석                40
  2    4  테스트투             한     암     2    52.5   김태희   이강서   손천수                35
-------------------------------------------------------------------------------------------------
순위 마번    마      명       마 체 중  기 록  도 착 차  S1F-1C-2C-3C-4C-G1F
-------------------------------------------------------------------------------------------------
  1    8  테스트원             465( +9) 1:01.0            3-  -  - 3- 3- 2
  2    4  테스트투             487( +7) 1:01.4  2½       6-  -  - 6- 6- 5
-------------------------------------------------------------------------------------------------
순위 마번    G-3Ｆ   S-1F  １코너  ２코너  ３코너  ４코너    G-1F  단승식 연승식
-------------------------------------------------------------------------------------------------
  1    8   37.3    0:13.4                  0:13.4  0:29.5   13.5      7.4    1.4
  2    4   36.0    0:14.1                  0:14.1  0:31.0   12.3      5.6    1.5
-------------------------------------------------------------------------------------------------
""".strip()

JEJU_REPORT = """
제목 : 2024년12월28일(토)  제 1경주

(제주) 제96일 800M 제6등급별정A
날씨 : 맑음 주로 : 양호 (9%)
순위상금 : 11,000만원 5,060만원 3,300만원 1,540만원 1,100만원
-------------------------------------------------------------------------------------------------
순위  마번   마   명    마종 성별 연령  부담중량   기수명    조교사    마주명           레이팅
-------------------------------------------------------------------------------------------------
  1     4   일품걸        제 암   3    54.0        문현진    이준호     김성온            40
-------------------------------------------------------------------------------------------------
순위 마번    마      명       마 체 중  기 록  위 차  S1F-1C-2C-3C-4C-G1F
-------------------------------------------------------------------------------------------------
  1    4  일품걸               253+3 1:25.5            3-  -  - 3- 3- 2
-------------------------------------------------------------------------------------------------
순위 마번    G-3Ｆ   S-1F  １코너  ２코너  ３코너  ４코너    G-1F  단승식 연승식
-------------------------------------------------------------------------------------------------
  1    4   42.1    0:17.2                  0:17.2  0:33.1   14.0      2.1    1.2
-------------------------------------------------------------------------------------------------
""".strip()


def add_source_document(session, tmp_path: Path) -> Path:
    raw_path = tmp_path / "20241229dacom11.rpt"
    raw = REPORT.encode("cp949")
    raw_path.write_bytes(raw)
    run = IngestionRun(
        source="race.kra.co.kr/dbdata",
        data_type="kra_text_dacom11",
        started_at_ms=1,
        completed_at_ms=2,
        status="completed",
        records_fetched=1,
        records_written=1,
    )
    session.add(run)
    session.flush()
    session.add(
        SourceDocument(
            ingestion_run_id=run.id,
            source_url="https://race.kra.co.kr/example",
            endpoint="/dbdata/fileDownLoad.do",
            operation="dacom11",
            request_params_json='{"meet":1}',
            requested_at_ms=1,
            retrieved_at_ms=2,
            http_status_code=200,
            content_type="application/octet-stream",
            response_bytes=len(raw),
            local_path=str(raw_path),
            sha256=hashlib.sha256(raw).hexdigest(),
        )
    )
    session.commit()
    return raw_path


def test_parse_dacom11_report() -> None:
    race = parse_dacom11_report(REPORT.encode("cp949"))[0]

    assert race.race_date == date(2024, 12, 29)
    assert race.distance_m == 1000
    assert race.grade == "국6등급"
    assert race.track_moisture_percent == 3.0
    assert len(race.entries) == 2
    winner = race.entries[0]
    assert winner.jockey_name == "빅투아르"
    assert winner.trainer_name == "이준철"
    assert winner.owner_name == "손병석"
    assert winner.finish_time_ms == 61_000
    assert winner.g3f_ms == 37_300
    assert winner.win_odds == 7.4
    assert winner.prize_money_krw == 24_750_000


def test_parse_dacom11_jeju_layout() -> None:
    race = parse_dacom11_report(JEJU_REPORT.encode("cp949"))[0]

    assert race.race_date == date(2024, 12, 28)
    assert race.grade == "제6등급"
    assert race.burden_type == "별정A"
    assert race.age_condition is None
    assert race.rating_condition is None
    assert race.weather == "맑음"
    assert race.track_condition == "양호"
    assert race.track_moisture_percent == 9.0
    winner = race.entries[0]
    assert winner.horse_name == "일품걸"
    assert winner.origin_country == "제"
    assert winner.body_weight_kg == 253
    assert winner.body_weight_change_kg == 3
    assert winner.finish_time_ms == 85_500
    assert winner.prize_money_krw == 110_000_000


def test_parse_dacom11_preserves_visiting_prefix_and_ambiguous_width_name() -> None:
    separator = "-" * 100
    header = (
        "순위 마번    마    명      산지   성별 연령 부담중량 "
        "기수명 조교사   마주명           레이팅"
    )
    visiting_row = (
        "  1    8  [부]위너스맨      한     수     3    57.0   "
        "최시대 최기홍   이경희              84"
    )
    ambiguous_width_row = (
        "  9    5  콩코드Ⅱ         미     암     3    53.0   박을운 구자흥   한명로                "
    )
    entries = _parse_entry_table(
        [
            header,
            separator,
            visiting_row,
            ambiguous_width_row,
            separator,
        ]
    )

    assert [entry.horse_name for entry in entries] == ["[부]위너스맨", "콩코드Ⅱ"]
    assert entries[1].origin_country == "미"
    assert entries[1].sex == "암"
    assert entries[1].age == 3

    no_rating_entries = _parse_entry_table(
        [
            "순위  마번   마   명    마종 성별 연령  부담중량   기수명    조교사    마주명",
            separator,
            "  1     9   탐라독주      한 암   3    54.0        김홍권    김영래    고승명",
            separator,
        ]
    )
    assert no_rating_entries[0].owner_name == "고승명"
    assert no_rating_entries[0].rating is None
    assert _is_separator("─" * 40)
    weather_only = _TRACK.search("경주조건: R1~35 날씨:흐림 주로:  ")
    assert weather_only is not None
    assert weather_only.group("weather") == "흐림"
    assert weather_only.group("track") == ""


def test_ingest_dacom11_writes_normalized_race(tmp_path: Path) -> None:
    session_factory = migrated_session(tmp_path)
    with session_factory() as session:
        add_source_document(session, tmp_path)
        session.add_all(
            [
                Horse(kra_horse_id="005001", name_ko="테스트원", sex="수"),
                Horse(kra_horse_id="005002", name_ko="테스트투", sex="암"),
            ]
        )
        session.commit()

        audit = ingest_dacom11_reports(
            session,
            raw_data_dir=tmp_path,
            start_date=date(2024, 12, 29),
            end_date=date(2024, 12, 29),
            meets=[1],
            validate_only=True,
        )
        assert audit.resolved_horse_entries == 2
        assert audit.unresolved_horse_entries == 0
        assert audit.ambiguous_horse_entries == 0

        summary = ingest_dacom11_reports(
            session,
            raw_data_dir=tmp_path,
            start_date=date(2024, 12, 29),
            end_date=date(2024, 12, 29),
            meets=[1],
        )

        assert summary.races_written == 1
        assert summary.entries_written == 2
        assert summary.synthetic_horses == 0
        race = session.scalar(select(Race))
        assert race is not None
        assert race.status == "completed"
        assert race.field_size == 2
        assert session.scalar(select(func.count()).select_from(RaceEntry)) == 2
        assert session.scalar(select(func.count()).select_from(RaceResult)) == 2
        assert session.scalar(select(func.count()).select_from(RaceSectionResult)) == 6
        assert session.scalar(select(func.count()).select_from(OddsSnapshot)) == 4


def test_ingest_dacom11_validates_existing_api_race(tmp_path: Path) -> None:
    session_factory = migrated_session(tmp_path)
    with session_factory() as session:
        add_source_document(session, tmp_path)
        course = Racecourse(kra_meet_code=1, code="seoul", name_ko="서울")
        race = Race(
            racecourse=course,
            race_date_local=date(2024, 12, 29),
            race_number=1,
            distance_m=1000,
            status="completed",
        )
        for number, horse_id, name, position, finish_ms in (
            (8, "005001", "테스트원", 1, 61_000),
            (4, "005002", "테스트투", 2, 61_400),
        ):
            horse = Horse(kra_horse_id=horse_id, name_ko=name)
            entry = RaceEntry(race=race, horse=horse, horse_number=number)
            session.add_all(
                [
                    horse,
                    entry,
                    RaceResult(
                        race_entry=entry, finish_position=position, finish_time_ms=finish_ms
                    ),
                ]
            )
        session.add_all([course, race])
        session.commit()

        summary = ingest_dacom11_reports(
            session,
            raw_data_dir=tmp_path,
            start_date=date(2024, 12, 29),
            end_date=date(2024, 12, 29),
            meets=[1],
            validate_only=True,
        )

        assert summary.races_written == 0
        assert summary.overlap_races == 1
        assert summary.overlap_entries == 2
        assert summary.overlap_mismatches == 0
        assert summary.resolved_horse_entries == 0
        assert summary.unresolved_horse_entries == 0
        assert summary.ambiguous_horse_entries == 0

        update = ingest_dacom11_reports(
            session,
            raw_data_dir=tmp_path,
            start_date=date(2024, 12, 29),
            end_date=date(2024, 12, 29),
            meets=[1],
        )
        session.refresh(race)
        assert update.races_written == 0
        assert update.races_updated == 1
        assert race.grade == "국6등급"
        assert race.weather == "맑음"


def test_dacom11_resolver_uses_birth_year_and_visiting_home_meet(tmp_path: Path) -> None:
    session_factory = migrated_session(tmp_path)
    with session_factory() as session:
        expected = Horse(
            kra_horse_id="3015728",
            name_ko="으뜸공신",
            sex="거",
            birth_date=date(2013, 3, 12),
            meet_code=2,
        )
        session.add_all(
            [
                expected,
                Horse(
                    kra_horse_id="1011519",
                    name_ko="으뜸공신",
                    sex="수",
                    birth_date=date(1996, 4, 24),
                    meet_code=2,
                ),
                Horse(
                    kra_horse_id="0036560",
                    name_ko="페르디도포머로이",
                    sex="거",
                    birth_date=date(2013, 3, 26),
                    meet_code=3,
                ),
            ]
        )
        session.commit()
        resolver = _EntityResolver(session)

        common = {
            "finish_position": 1,
            "finish_rank_raw": "1",
            "horse_number": 1,
            "origin_country": "한",
            "carried_weight_kg": 55.0,
            "jockey_name": None,
            "trainer_name": None,
            "owner_name": None,
            "rating": None,
        }
        horse, status = resolver.match_horse(
            Dacom11Entry(horse_name="으뜸공신", sex="수", age=2, **common),
            meet=2,
            race_date=date(2015, 7, 17),
        )
        visitor, visitor_status = resolver.match_horse(
            Dacom11Entry(
                horse_name="[부]페르디도포머로",
                sex="수",
                age=3,
                **common,
            ),
            meet=1,
            race_date=date(2016, 6, 5),
        )

        assert status == "resolved"
        assert horse is expected
        assert visitor_status == "resolved"
        assert visitor is not None and visitor.kra_horse_id == "0036560"
        assert _horse_names_match("페르디도포머로이", "[부]페르디도포머로")
