from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy import func, select
from test_race_day import migrated_session

from horse_racing.collectors.special_training import KraXmlApiClient
from horse_racing.db.models import (
    Horse,
    HorseHillTraining,
    HorseSwimTraining,
    SourceDocument,
)
from horse_racing.parsers.special_training import HillTrainingItem, SwimTrainingItem
from horse_racing.services.special_training import (
    ingest_hill_training,
    ingest_swim_training,
)


def _xml(items: str, total: int) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<response><header><resultCode>00</resultCode><resultMsg>OK</resultMsg></header>
<body><items>{items}</items><numOfRows>20000</numOfRows><pageNo>1</pageNo>
<totalCount>{total}</totalCount></body></response>""".encode()


SWIM_ITEM = """
<item><cnt>2</cnt><horsepart>3</horsepart><horsepartMemo></horsepartMemo>
<hrName>테스트마</hrName><hrNo>0050001</hrNo><meet>서울</meet>
<trDate>20260920</trDate><trName>테스트조교사</trName><trpart>10</trpart></item>
"""

HILL_ITEMS = """
<item><rnum>1</rnum><areqNm>장수</areqNm><tagId>0001</tagId>
<hrNo>0050001</hrNo><hrNm>테스트마</hrNm><moHrNm>모마</moHrNm><faHrNm>부마</faHrNm>
<sex>암</sex><birthday>2023-03-01</birthday><id>4100001</id><ptrNm>육성자</ptrNm>
<owNm>마주</owNm><inStDate>2026-08-01</inStDate><stCause>휴양</stCause>
<startDate>2026-09-20</startDate><startTime>06:30:00</startTime>
<firstRecord>25.1</firstRecord><secRecord>24.9</secRecord><thiRecord>0.0</thiRecord>
<sumRecord>50.0</sumRecord></item>
<item><rnum>2</rnum><areqNm>장수</areqNm><tagId>0001</tagId>
<hrNo>0050001</hrNo><hrNm>테스트마</hrNm><moHrNm>모마</moHrNm><faHrNm>부마</faHrNm>
<sex>암</sex><birthday>2023-03-01</birthday><id>4100001</id><ptrNm>육성자</ptrNm>
<owNm>마주</owNm><inStDate>2026-08-01</inStDate><stCause>휴양</stCause>
<startDate>2026-09-20</startDate><startTime>06:30:00</startTime>
<firstRecord>0.0</firstRecord><secRecord>0.0</secRecord><thiRecord>0.0</thiRecord>
<sumRecord>0.0</sumRecord></item>
"""


def test_parse_special_training_items_and_stable_hash() -> None:
    swim = SwimTrainingItem.model_validate(
        {
            "cnt": "2",
            "hrName": "테스트마",
            "hrNo": "0050001",
            "meet": "서울",
            "trDate": "20260920",
            "trName": "조교사",
            "trpart": "10",
        }
    )
    assert swim.training_date == date(2026, 9, 20)
    assert swim.meet_code == 1
    assert swim.swim_count == 2
    zero_swim = SwimTrainingItem.model_validate(
        {
            "cnt": "0",
            "hrName": "테스트마",
            "hrNo": "0050001",
            "meet": "서울",
            "trDate": "20260920",
        }
    )
    assert zero_swim.quality_status == "zero_record"

    raw = {
        "rnum": "1",
        "areqNm": "장수",
        "tagId": "0001",
        "hrNo": "0050001",
        "hrNm": "테스트마",
        "startDate": "2026-09-20",
        "startTime": "06:30:00",
        "firstRecord": "25.1",
        "secRecord": "24.9",
        "thiRecord": "0.0",
        "sumRecord": "50.0",
    }
    first = HillTrainingItem.model_validate(raw)
    second = HillTrainingItem.model_validate({**raw, "rnum": "999"})
    assert first.source_row_hash == second.source_row_hash
    assert first.quality_status == "valid"
    assert first.total_seconds == Decimal("50.0")
    unnamed = HillTrainingItem.model_validate(
        {key: value for key, value in raw.items() if key != "hrNm"}
    )
    assert unnamed.horse_name == "(이름없음)"
    invalid = HillTrainingItem.model_validate({**raw, "secRecord": "-1.0"})
    assert invalid.quality_status == "invalid_record"


def test_ingest_special_training_is_idempotent_and_links_horse(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/API216/SwimTr"):
            return httpx.Response(200, content=_xml(SWIM_ITEM + SWIM_ITEM, 2))
        if request.url.path.endswith("/hilldriving/gethilldriving"):
            return httpx.Response(200, content=_xml(HILL_ITEMS, 2))
        return httpx.Response(404)

    session_factory = migrated_session(tmp_path)
    with session_factory() as session:
        horse = Horse(kra_horse_id="0050001", name_ko="테스트마")
        session.add(horse)
        session.commit()
        with KraXmlApiClient("test-key", transport=httpx.MockTransport(handler)) as client:
            swim_summary = ingest_swim_training(
                session,
                client,
                start_year=2026,
                end_year=2026,
                raw_data_dir=tmp_path / "raw",
            )
            hill_summary = ingest_hill_training(
                session,
                client,
                start_date="20260101",
                end_date="20260923",
                raw_data_dir=tmp_path / "raw",
            )

        assert swim_summary.records_fetched == 2
        assert swim_summary.records_written == 1
        assert hill_summary.records_fetched == 4
        assert hill_summary.records_written == 2
        assert session.scalar(select(func.count()).select_from(HorseSwimTraining)) == 1
        assert session.scalar(select(func.count()).select_from(HorseHillTraining)) == 2
        assert session.scalar(select(func.count()).select_from(SourceDocument)) == 3

        swim = session.scalar(select(HorseSwimTraining))
        assert swim is not None and swim.horse_id == horse.id
        assert swim.quality_status == "valid"
        statuses = set(session.scalars(select(HorseHillTraining.quality_status)))
        assert statuses == {"valid", "zero_record"}

        swim_id = swim.id
        hill_ids = set(session.scalars(select(HorseHillTraining.id)))
        # Replay complete responses, not just duplicate items within one page.
        for _ in range(2):
            with KraXmlApiClient("test-key", transport=httpx.MockTransport(handler)) as client:
                ingest_swim_training(
                    session,
                    client,
                    start_year=2026,
                    end_year=2026,
                    raw_data_dir=tmp_path / "raw",
                )
                ingest_hill_training(
                    session,
                    client,
                    start_date="20260101",
                    end_date="20260923",
                    raw_data_dir=tmp_path / "raw",
                )
            assert set(session.scalars(select(HorseSwimTraining.id))) == {swim_id}
            assert set(session.scalars(select(HorseHillTraining.id))) == hill_ids
        # Retrieval documents grow as observation history; business rows do not.
        assert session.scalar(select(func.count()).select_from(SourceDocument)) == 9

        def revised(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/API216/SwimTr"):
                return httpx.Response(200, content=_xml(SWIM_ITEM.replace("<cnt>2", "<cnt>3"), 1))
            return httpx.Response(200, content=_xml("", 0))

        with KraXmlApiClient("test-key", transport=httpx.MockTransport(revised)) as client:
            ingest_swim_training(
                session,
                client,
                start_year=2026,
                end_year=2026,
                raw_data_dir=tmp_path / "raw",
            )
            ingest_hill_training(
                session,
                client,
                start_date="20260101",
                end_date="20260923",
                raw_data_dir=tmp_path / "raw",
            )
        session.expire_all()
        revised_swim = session.scalar(select(HorseSwimTraining))
        assert revised_swim.id == swim_id and revised_swim.swim_count == 3
        assert set(session.scalars(select(HorseHillTraining.id))) == hill_ids
