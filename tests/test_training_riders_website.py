from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from horse_racing.db.base import Base
from horse_racing.db.models import (
    Horse,
    HorseTraining,
    HorseTrainingRiderObservation,
    SourceDocument,
)
from horse_racing.parsers.training_riders_website import parse_training_riders, rider_label
from horse_racing.services.training_read import training_display_fields
from horse_racing.services.training_riders_website import ingest_training_riders


def profile(label="생", start="08:11", end="08:28", duration="17분"):
    return f"""<html><meta charset="utf-8"><table>
    <tr><th>마명</th><td>검증마 (TEST)</td></tr></table>
    <p>[기승자범례] 이름:기수명, 관:주로조교, 생:교육생, 이름(트):기수트랙라이더</p>
    <table><tr><th>조교일자</th><th>기승자</th><th>입장시간</th>
    <th>퇴장시간</th><th>조교시간</th></tr>
    <tr><td>1</td><td>2026/10/11(일)</td><td>{label}</td>
    <td>{start}</td><td>{end}</td><td>{duration}</td></tr>
    <tr><td>2</td><td>2026/10/12(월)</td><td>경주일</td><td>-</td><td>-</td><td>-</td></tr></table></html>""".encode()


@pytest.mark.parametrize(
    "label,role,name",
    [
        ("최원준(트)", "기수트랙라이더", None),
        ("이혁", "기수", "이혁"),
        ("생", "교육생", None),
        ("관", "주로조교", None),
        ("조", "조교사", None),
        ("후", "기수후보생", None),
        ("외", "미확인", None),
    ],
)
def test_official_legend_keeps_non_jockey_names_private(label, role, name):
    assert rider_label(label) == (role, name)
    rows = parse_training_riders(profile(label), horse_name="검증마")
    assert len(rows) == 1
    assert (rows[0]["role"], rows[0]["name"]) == (role, name)


def test_parser_rejects_wrong_horse_error_pages_and_inconsistent_times():
    for raw, horse in [
        (profile(), "다른말"),
        (b"error", "검증마"),
        (profile(end="08:29"), "검증마"),
    ]:
        with pytest.raises(ValueError):
            parse_training_riders(raw, horse_name=horse)


def test_inconsistent_row_is_audited_without_losing_other_events():
    raw = profile()
    invalid = raw[raw.index(b"<tr><td>1") : raw.index(b"<tr><td>2")]
    invalid = invalid.replace(b"08:28", b"08:29")
    rejected = []
    rows = parse_training_riders(
        raw.replace(b"</table></html>", invalid + b"</table></html>"),
        horse_name="검증마",
        rejected_rows=rejected,
    )
    assert len(rows) == len(rejected) == 1
    assert rows[0]["end"] == "08:28"
    assert not parse_training_riders(
        profile(end="08:29"), horse_name="검증마", start_date=date(2026, 10, 12)
    )


@pytest.fixture
def database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Horse(id=1, kra_horse_id="0054260", name_ko="검증마"))
        row = HorseTraining(
            horse_id=1,
            meet_code=1,
            training_date_local=date(2026, 10, 11),
            started_at_raw="20261011081100",
            ended_at_raw="20261011082800",
            duration_seconds=1020,
            rider_type="기수",
            rider_id="080419",
            observed_at_ms=1,
        )
        session.add(row)
        session.commit()
        yield session, row.id
    engine.dispose()


def collect(session, tmp_path, raw=None):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=raw or profile("최원준(트)"))
        )
    ) as client:
        return ingest_training_riders(
            session,
            client,
            horse=(1, "0054260", "검증마", 1),
            as_of=date(2026, 10, 17),
            raw_data_dir=tmp_path,
        )


def test_collector_preserves_api_fields_and_archives_evidence(database, tmp_path):
    session, row_id = database
    result = collect(session, tmp_path)
    assert result["matched"] == 1
    observation = session.get(HorseTrainingRiderObservation, row_id)
    assert observation.rider_role == "기수트랙라이더"
    assert observation.jockey_name is None
    api = session.get(HorseTraining, row_id)
    assert (api.rider_type, api.rider_id) == ("기수", "080419")
    document = session.get(SourceDocument, observation.source_document_id)
    assert document.source_url.startswith("https://race.kra.co.kr/")
    assert Path(document.local_path).is_file()
    assert len(document.sha256) == 64
    collect(session, tmp_path)
    assert len(session.scalars(select(HorseTrainingRiderObservation)).all()) == 1


def test_ambiguous_website_events_do_not_replace_valid_evidence(database, tmp_path):
    session, row_id = database
    collect(session, tmp_path)
    old = session.get(HorseTrainingRiderObservation, row_id).source_document_id
    raw = profile("생")
    duplicate = raw[raw.index(b"<tr><td>1") : raw.index(b"<tr><td>2")]
    result = collect(
        session, tmp_path, raw.replace(b"</table></html>", duplicate + b"</table></html>")
    )
    assert result["matched"] == 0
    assert result["ambiguous"] == 1
    assert session.get(HorseTrainingRiderObservation, row_id).source_document_id == old


def test_website_trackrider_overrides_api_jockey_and_changed_api_invalidates(database, tmp_path):
    session, row_id = database
    collect(session, tmp_path)
    row = session.get(HorseTraining, row_id)
    display = training_display_fields(session, [row])[row_id]
    assert display["rider_display_label"] == "기수트랙라이더"
    assert display["rider_name"] is None
    assert display["rider_identity_status"] == "website_same_event"
    row.rider_id = "changed"
    display = training_display_fields(session, [row])[row_id]
    assert display["rider_identity_status"] != "website_same_event"
    assert display["rider_display_label"] == "기수"


def test_website_staff_role_fills_missing_api_without_exposing_name(database, tmp_path):
    session, row_id = database
    row = session.get(HorseTraining, row_id)
    row.rider_type = row.rider_id = None
    session.commit()
    collect(session, tmp_path, profile("생"))
    display = training_display_fields(session, [session.get(HorseTraining, row_id)])[row_id]
    assert display["rider_display_label"] == "교육생"
    assert display["rider_name"] is None
    assert session.get(HorseTraining, row_id).rider_type is None


def test_away_fixture_uses_actual_training_venue(database):
    from horse_racing.db.models import Race, Racecourse, RaceEntry
    from horse_racing.services.training_riders_website import upcoming_training_horses

    session, _ = database
    away = Racecourse(kra_meet_code=4, code="AWAY", name_ko="원정")
    race = Race(
        racecourse=away,
        race_date_local=date(2026, 10, 18),
        race_number=1,
        status="scheduled",
        distance_m=1200,
    )
    session.add(RaceEntry(race=race, horse_id=1, horse_number=1))
    session.commit()
    horses = upcoming_training_horses(session, as_of=date(2026, 10, 17))
    assert len(horses) == 1
    assert tuple(horses[0]) == (1, "0054260", "검증마", 1)
