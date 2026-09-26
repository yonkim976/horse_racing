import json
from datetime import date
from pathlib import Path

import httpx
from sqlalchemy import func, select
from test_race_day import (
    ENTRY_FIXTURE,
    ai_result_payload,
    api_payload,
    detailed_result_payload,
    final_dividend_payload,
    migrated_session,
    race_plan_payload,
)

from horse_racing.collectors.kra_api import RACE_PASSING_SUMMARY_ENDPOINT, KraApiClient
from horse_racing.db.models import RacePassingSummary
from horse_racing.parsers.race_passing import RacePassingSummaryItem, parse_elapsed_ms
from horse_racing.services.race_day import ingest_race_day
from horse_racing.services.race_passing import (
    ingest_race_passing_summaries,
    passing_summary_day_is_stored,
)


def passing_payload() -> dict[str, object]:
    return api_payload(
        [
            {
                "meet": "서울",
                "rcDate": 20260822,
                "rcNo": 1,
                "corner_1": "-",
                "corner_2": "-",
                "corner_3": "2-(1)",
                "corner_4": "2=1",
                "corner_5": "X",
                "corner_6": "X",
                "corner_7": "2,1",
                "corner_8": "1-2",
                "corner_9": "X",
                "passtime_3f": "0:40.1",
                "passtime_4f": "0:52.4",
                "tempo": "⑤",
            }
        ]
    )


def test_parse_official_passing_summary() -> None:
    raw = passing_payload()["response"]["body"]["items"]["item"][0]
    item = RacePassingSummaryItem.model_validate(raw)

    assert item.race_date == date(2026, 8, 22)
    assert item.corner_7_raw == "2,1"
    assert item.corner_8_raw == "1-2"
    assert item.pass_time_3f_ms == 40_100
    assert item.pass_time_4f_ms == 52_400
    assert item.tempo_level == 5
    assert item.quality_status == "valid"
    assert len(item.source_row_hash) == 64
    assert parse_elapsed_ms("1:04.7") == 64_700
    assert parse_elapsed_ms("0:00.0") is None
    assert parse_elapsed_ms("invalid") is None


def test_ingest_passing_summary_links_race_and_is_idempotent(tmp_path: Path) -> None:
    entry_payload = ENTRY_FIXTURE.read_text(encoding="utf-8")
    responses = {
        "/B551015/API154/racePlan": race_plan_payload(),
        "/B551015/API26_2/entrySheet_2": json.loads(entry_payload),
        "/B551015/API155/raceResult": ai_result_payload(),
        "/B551015/API156/raceRsutDtl": detailed_result_payload(),
        "/B551015/API301/Dividend_rate_total": final_dividend_payload(),
        f"/B551015{RACE_PASSING_SUMMARY_ENDPOINT}": passing_payload(),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path not in responses:
            raise AssertionError(f"unexpected path: {request.url.path}")
        return httpx.Response(200, json=responses[request.url.path], request=request)

    session_factory = migrated_session(tmp_path)
    with (
        KraApiClient("secret-test-key", transport=httpx.MockTransport(handler)) as client,
        session_factory() as session,
    ):
        ingest_race_day(
            session,
            client,
            race_date="20260822",
            meet=1,
            raw_data_dir=tmp_path / "raw",
        )
        first = ingest_race_passing_summaries(
            session,
            client,
            race_date="20260822",
            meet=1,
            raw_data_dir=tmp_path / "raw",
        )
        second = ingest_race_passing_summaries(
            session,
            client,
            race_date="20260822",
            meet=1,
            raw_data_dir=tmp_path / "raw",
        )

        assert first.records_fetched == 1
        assert first.records_written == 1
        assert second.records_written == 1
        assert session.scalar(select(func.count()).select_from(RacePassingSummary)) == 1
        assert passing_summary_day_is_stored(
            session, race_date=date(2026, 8, 22), meet=1
        )
        row = session.scalar(select(RacePassingSummary))
        assert row is not None
        assert row.corner_3_raw == "2-(1)"
        assert row.corner_7_raw == "2,1"
        assert row.tempo_level == 5
        assert row.source_document_id is not None
