from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from horse_racing.cli import collection
from horse_racing.cli.collection import collect_schedule
from horse_racing.services.entry_sheet import IngestionSummary
from horse_racing.services.gate_entry_sheet import GateIngestionSummary
from horse_racing.services.race_day import RaceDayIngestionSummary


def schedule_summary(*, plan_written: int, entry_written: int) -> RaceDayIngestionSummary:
    return RaceDayIngestionSummary(
        stages={
            "race_plan": IngestionSummary(
                run_id=1, pages=1, records_fetched=plan_written, records_written=plan_written
            ),
            "entry_sheet": IngestionSummary(
                run_id=2, pages=1, records_fetched=entry_written, records_written=entry_written
            ),
        }
    )


@pytest.fixture
def fake_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = SimpleNamespace(
        data_go_kr_service_key=SecretStr("secret-test-key"),
        kra_api_base_url="https://example.invalid",
        http_timeout_seconds=1,
        raw_data_dir=tmp_path / "raw",
    )
    monkeypatch.setattr(collection, "get_settings", lambda: settings)
    monkeypatch.setattr(collection, "KraApiClient", lambda *args, **kwargs: nullcontext(object()))
    monkeypatch.setattr(collection, "SessionLocal", lambda: nullcontext(MagicMock()))


@pytest.mark.usefixtures("fake_environment")
def test_collect_schedule_continues_after_gate_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    scheduled: list[int] = []
    gated: list[int] = []

    def fake_schedule(session, client, *, race_date, meet, raw_data_dir, page_size):
        scheduled.append(meet)
        return schedule_summary(plan_written=3, entry_written=20)

    def fake_gate(session, client, *, race_date, meet, raw_data_dir, page_size):
        gated.append(meet)
        if meet == 1:
            raise ValueError("출발번호와 연결할 출전마가 없습니다")
        return GateIngestionSummary(run_id=9, pages=1, records_fetched=20, records_written=20)

    monkeypatch.setattr(collection, "ingest_race_schedule", fake_schedule)
    monkeypatch.setattr(collection, "ingest_gate_numbers", fake_gate)

    code = collect_schedule(["20260829"], [1, 2], 1000)

    captured = capsys.readouterr()
    assert code == 1
    assert scheduled == [1, 2]
    assert gated == [1, 2]
    assert "출발번호 확인 실패: 날짜=20260829, 경마장=서울" in captured.err
    assert "연결할 출전마가 없습니다" in captured.err
    assert "출발번호 확인 실패 1건" in captured.err
    assert "출발번호 확인: 날짜=20260829, 경마장=제주, fetched=20, written=20" in captured.out


@pytest.mark.usefixtures("fake_environment")
def test_collect_schedule_skips_gate_numbers_without_entry_sheet(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gate = MagicMock()
    monkeypatch.setattr(
        collection,
        "ingest_race_schedule",
        lambda *args, **kwargs: schedule_summary(plan_written=3, entry_written=0),
    )
    monkeypatch.setattr(collection, "ingest_gate_numbers", gate)

    code = collect_schedule(["20260829"], [1], 1000)

    captured = capsys.readouterr()
    assert code == 0
    gate.assert_not_called()
    assert "일정 수집: 날짜=20260829, 경마장=서울, fetched=3" in captured.out
    assert "출발번호" not in captured.out + captured.err
