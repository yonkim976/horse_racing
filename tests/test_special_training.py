from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
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
    HILL_TRAINING_CURRENT,
    hill_training_current_query,
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


def test_postgres_hill_serving_reads_only_current_view_and_keeps_bound_filters():
    from horse_racing.db.base import Base

    session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    )
    day = date(2026, 10, 5)
    query = hill_training_current_query(
        session, start=day, end=day, horse_id=7, kra_horse_id_raw="0050001"
    )
    compiled = query.compile(dialect=postgresql.dialect())
    assert "FROM public.horse_hill_training_current" in str(compiled)
    assert "row_number" not in str(compiled)
    assert "FROM horse_hill_training " not in str(compiled)
    assert 7 in compiled.params.values() and day in compiled.params.values()
    assert "0050001" in compiled.params.values() and "0050001" not in str(compiled)
    assert HILL_TRAINING_CURRENT.metadata is not Base.metadata
    assert "public.horse_hill_training_current" not in Base.metadata.tables


def test_hill_read_rejects_unsupported_database_instead_of_returning_raw_versions():
    session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="mysql"))
    )
    with pytest.raises(ValueError, match="unsupported_hill_training_read_dialect"):
        hill_training_current_query(session, start=date(2026, 10, 5), end=date(2026, 10, 11))


def test_hill_metadata_versions_do_not_inflate_counts_and_unknown_time_stays_separate(tmp_path):
    from horse_racing.db.models import IngestionRun
    from horse_racing.jobs.daily_training import changes, snapshot
    from horse_racing.services.special_training import (
        _upsert_hill_items,
        hill_training_counts,
        hill_training_current_query,
    )

    factory = migrated_session(tmp_path)
    raw = {
        "areqNm": "장수",
        "hrNo": "0050001",
        "hrNm": "옛이름",
        "tagId": "1",
        "id": "123",
        "startDate": "2026-09-20",
        "startTime": "06:30:00",
        "firstRecord": "25.1",
        "secRecord": "24.9",
        "thiRecord": "0",
        "sumRecord": "50.0",
    }
    day = date(2026, 9, 20)
    with factory() as session:
        run = IngestionRun(source="test", data_type="test", status="running", started_at_ms=1)
        session.add(run)
        session.flush()
        doc = SourceDocument(
            ingestion_run_id=run.id,
            source_url="https://example.org",
            request_params_json="{}",
            requested_at_ms=1,
            retrieved_at_ms=1,
            local_path="test-only.xml",
            sha256="a" * 64,
        )
        session.add(doc)
        session.flush()

        def add(value, stamp):
            _upsert_hill_items(
                session,
                [HillTrainingItem.model_validate(value)],
                source_document_id=doc.id,
                observed_at_ms=stamp,
            )
            session.commit()

        add(raw, 100)
        before = snapshot(session, "hill", day, day)
        add({**raw, "hrNm": "새이름", "owNm": "새마주"}, 200)
        assert hill_training_counts(session, start=day, end=day) == {
            "stored_versions": 2,
            "measured_records": 1,
            "metadata_versions_excluded": 1,
        }
        after = snapshot(session, "hill", day, day)
        assert changes(before, after)["new"] == 0
        assert changes(before, after)["changed"] == 1
        current = (
            session.execute(hill_training_current_query(session, start=day, end=day))
            .mappings()
            .one()
        )
        assert current["horse_name_raw"] == "새이름" and current["metadata_version_count"] == 2
        # Distinct same-second timings and a second time are never discarded.
        add({**raw, "firstRecord": "26.1", "sumRecord": "51.0"}, 300)
        add({**raw, "startTime": "06:31:00"}, 300)
        add({**raw, "startTime": ""}, 300)
        add({**raw, "startTime": "", "hrNm": "새이름"}, 400)
        assert hill_training_counts(session, start=day, end=day)["measured_records"] == 5
        assert session.scalar(select(func.count()).select_from(HorseHillTraining)) == 6

        # A horse-specific screen uses the same deduplicated rows, and keeps
        # real repeat measurements rather than grouping all sessions by date.
        horse = Horse(kra_horse_id="0050001", name_ko="새이름")
        session.add(horse)
        session.flush()
        for row in session.scalars(select(HorseHillTraining)):
            row.horse_id = horse.id
        session.commit()
        rows = (
            session.execute(
                hill_training_current_query(session, start=day, end=day, horse_id=horse.id)
            )
            .mappings()
            .all()
        )
        assert len(rows) == 5
        assert len({r["id"] for r in rows}) == 5
        # Linking metadata must not resurrect an older version filtered first.
        renamed = next(row for row in rows if row["metadata_version_count"] == 2)
        session.get(HorseHillTraining, renamed["id"]).horse_id = None
        session.commit()
        assert (
            len(
                session.execute(
                    hill_training_current_query(session, start=day, end=day, horse_id=horse.id)
                ).all()
            )
            == 4
        )


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
