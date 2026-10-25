from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_local_catalog import trial_sources

from horse_racing.jobs import local_catalog as job
from horse_racing.jobs import reference_catalog as catalog
from horse_racing.jobs.canonical_post_race import SourceMismatch


def mock_sources(monkeypatch, rows):
    trials, raw = trial_sources()
    page = SimpleNamespace(
        public_params={"pageNo": 1},
        payload={"response": {"body": {"totalCount": len(rows), "items": {"item": rows}}}},
    )
    api = Mock()
    api.iter_pages.return_value = iter([page])
    client = Mock()
    client.fetch_file.return_value = SimpleNamespace(
        body=b"synthetic-text", source_url="https://race.kra.co.kr/test"
    )
    file = SimpleNamespace(meet=1, file_date=date(2026, 10, 1), remote_path="test")
    monkeypatch.setattr(catalog, "parse_running_trial_report", lambda *_a, **_kw: trials)
    monkeypatch.setattr(catalog, "archive_bytes", Mock(return_value={"text": "evidence"}))
    monkeypatch.setattr(catalog, "document", Mock(return_value={"api": "evidence"}))
    persist = Mock(
        return_value=dict(status="completed", files=1, trials=1, runners=1, unlinked_rows=0)
    )
    monkeypatch.setattr(catalog, "persist_trials", persist)
    return file, client, api, persist, raw


def test_empty_api_waits_and_never_opens_database(monkeypatch, tmp_path):
    file, text, api, persist, _ = mock_sources(monkeypatch, [])
    monkeypatch.setattr(catalog, "create_engine_for_url", lambda *_a: pytest.fail("DB opened"))
    result = catalog.refresh_trial_file(None, text, api, file, tmp_path)
    assert result == dict(
        status="waiting_for_publication",
        reason="api_empty_text_present",
        text_trials=1,
        text_runners=1,
        api_runners=0,
    )
    persist.assert_not_called()
    catalog.archive_bytes.assert_called_once()
    catalog.document.assert_called_once()


def test_nonempty_mismatch_is_error_not_publication_wait(monkeypatch, tmp_path):
    _, raw = trial_sources()
    file, text, api, persist, _ = mock_sources(monkeypatch, [dict(raw, hrName="다른 말")])
    with pytest.raises(SourceMismatch, match="trial_horse_name"):
        catalog.refresh_trial_file(None, text, api, file, tmp_path)
    persist.assert_not_called()


def test_matching_sources_commit_only_selected_meet_date(monkeypatch, tmp_path):
    _, raw = trial_sources()
    file, text, api, persist, _ = mock_sources(monkeypatch, [raw])
    result = catalog.refresh_trial_file(None, text, api, file, tmp_path)
    assert result["runners"] == 1
    params = persist.call_args.kwargs
    assert params["files"] == [file]
    assert params["start"] == params["end"] == date(2026, 10, 1)
    assert len(params["official"]) == 1
    assert len(params["docs"]) == 2


@pytest.mark.parametrize("missing", [("jkName",), ("jkNo",), ("jkName", "jkNo")])
def test_text_jockey_fallback_preserves_raw_and_never_fabricates_id(missing):
    trials, original = trial_sources()
    raw = {k: v for k, v in original.items() if k not in missing}
    before = dict(raw)
    official = catalog.validate_trial_api(1, trials, [raw], allow_text_jockey_fallback=True)
    normalized = next(iter(official.values()))
    assert normalized["jkName"] == "기수"
    assert normalized["jkNo"] == (None if "jkNo" in missing else "080578")
    assert normalized["jockey_name_source"] == "official_dacom23"
    assert raw == before


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"jkName": "다른기수", "jkNo": None}, "trial_jockey_name"),
        ({"jkName": None, "jkNo": "0"}, "trial_official_id"),
        ({"jkName": None, "jkNo": None, "hrNo": None}, "trial_official_id"),
        ({"jkName": None, "jkNo": None, "rcTime": 99}, "trial_finish_time"),
    ],
)
def test_text_fallback_does_not_accept_conflicts_or_invalid_identifiers(changes, error):
    trials, raw = trial_sources()
    with pytest.raises(SourceMismatch, match=error):
        catalog.validate_trial_api(
            1, trials, [dict(raw, **changes)], allow_text_jockey_fallback=True
        )


def test_refresh_archives_explicit_text_jockey_fallback(monkeypatch, tmp_path):
    _, raw = trial_sources()
    file, text, api, persist, _ = mock_sources(monkeypatch, [dict(raw, jkName=None, jkNo=None)])
    catalog.refresh_trial_file(None, text, api, file, tmp_path)
    normalized = next(iter(persist.call_args.kwargs["official"].values()))
    assert normalized["jkNo"] is None
    assert '"jockey_id_status": "not_provided"' in (
        tmp_path / "text_jockey_fallbacks.json"
    ).read_text()


def test_persist_text_only_jockey_keeps_null_and_is_idempotent(monkeypatch, tmp_path):
    from sqlalchemy import func, select
    from test_race_day import migrated_session
    from test_running_trials import BUSAN_REPORT

    from horse_racing.db.models import Jockey, RunningTrialResult
    from horse_racing.parsers.running_trials import parse_running_trial_report

    factory = migrated_session(tmp_path)
    with factory() as session:
        engine = session.get_bind()
        session.add_all([
            Jockey(kra_jockey_id="080001", name_ko="김어수"),
            Jockey(kra_jockey_id="080002", name_ko="김어수"),
        ])
        session.commit()
    monkeypatch.setattr(catalog, "create_engine_for_url", lambda _: engine)
    trials = parse_running_trial_report(BUSAN_REPORT, meet=3)
    raw = dict(
        trainDate=20260827, trainNo=1, chulNo=9, meet="부경",
        hrName="용비짱", hrNo="0056500", trName="구민성", trNo="070161",
        rcTime=61.8, ord=1,
    )
    official = catalog.validate_trial_api(3, trials, [raw], allow_text_jockey_fallback=True)
    fetched = SimpleNamespace(
        body=BUSAN_REPORT.encode("cp949"), source_url="https://race.kra.co.kr/test",
        requested_at_ms=1, retrieved_at_ms=2, status_code=200, content_type="text/plain",
    )
    file = SimpleNamespace(
        meet=3, file_date=date(2026, 8, 27), remote_path="test", list_page=1,
        file_type="dacom23", filename="20260827dacom23.rpt",
    )
    fetched.file = file
    for attempt in range(2):
        directory = tmp_path / f"attempt_{attempt}"
        directory.mkdir()
        result = catalog.persist_trials(
            SimpleNamespace(database_url="unused"), files=[file], reports={(3, "test"): fetched},
            official=official, docs=[], start=file.file_date, end=file.file_date,
            directory=directory,
        )
        assert result["runners"] == 1 and result["unlinked_rows"] == 1
        assert result["text_jockey_fallback_rows"] == result["api_jockey_ids_missing"] == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(RunningTrialResult)) == 1
        saved = session.scalar(select(RunningTrialResult))
        assert saved.horse_id is not None and saved.trainer_id is not None
        assert saved.jockey_id is None and saved.jockey_name_raw == "김어수"
        assert saved.finish_time_ms == 61800


def test_discord_marks_missing_identity_as_saved_not_api_publication_wait(monkeypatch):
    sender = Mock(return_value="123")
    monkeypatch.setattr(job, "send_discord", sender)
    job.notify(
        SimpleNamespace(discord_webhook_url=None), "trials",
        dict(status="partial", runners=53, unlinked_rows=4, pending=[], errors=[]),
    )
    assert "결과 저장 · 일부 공식 ID 미제공" in sender.call_args.args[1]


def test_incomplete_api_page_is_error_not_wait(monkeypatch, tmp_path):
    file, text, api, persist, _ = mock_sources(monkeypatch, [])
    api.iter_pages.return_value = iter(
        [
            SimpleNamespace(
                public_params={"pageNo": 1},
                payload={"response": {"body": {"totalCount": 1, "items": ""}}},
            )
        ]
    )
    with pytest.raises(ValueError, match="Incomplete source pagination"):
        catalog.refresh_trial_file(None, text, api, file, tmp_path)
    persist.assert_not_called()


def install_clients(monkeypatch, *, listing_error=False):
    text = Mock()
    text.__enter__ = Mock(return_value=text)
    text.__exit__ = Mock(return_value=False)
    api = Mock()
    api.__enter__ = Mock(return_value=api)
    api.__exit__ = Mock(return_value=False)

    def files(**kwargs):
        meet = kwargs["meet"]
        if listing_error and meet == 1:
            raise RuntimeError("secret-url-do-not-log")
        return [
            SimpleNamespace(meet=meet, file_date=day)
            for day in (date(2026, 10, 8), date(2026, 10, 1))
        ]

    text.iter_running_trial_files.side_effect = files
    monkeypatch.setattr(catalog, "KraTextClient", lambda: text)
    monkeypatch.setattr(catalog, "LocalKraApiClient", lambda *_a: api)
    return SimpleNamespace(
        data_go_kr_service_key=SimpleNamespace(get_secret_value=lambda: "synthetic")
    )


def test_pending_error_and_completed_files_are_independent(monkeypatch, tmp_path):
    settings = install_clients(monkeypatch)
    visited = []

    def refresh(settings, text, api, file, directory):
        visited.append((file.meet, file.file_date))
        if file.meet == 1 and file.file_date.day == 8:
            return dict(status="waiting_for_publication", text_runners=41, api_runners=0)
        if file.meet == 2 and file.file_date.day == 8:
            raise SourceMismatch("secret-url-do-not-log")
        return dict(status="completed", files=1, trials=1, runners=3, unlinked_rows=0)

    monkeypatch.setattr(catalog, "refresh_trial_file", refresh)
    result = catalog.refresh_trials(
        settings, start=date(2026, 9, 25), end=date(2026, 10, 8), directory=tmp_path
    )
    assert len(visited) == 6
    assert (result["status"], result["files"], result["runners"]) == ("partial", 4, 12)
    assert result["pending"][0]["meet"] == 1
    assert result["errors"] == [dict(meet=2, date="2026-10-08", error_type="SourceMismatch")]
    assert "secret-url" not in (tmp_path / "report.json").read_text()


def test_listing_failure_does_not_block_other_regions(monkeypatch, tmp_path):
    settings = install_clients(monkeypatch, listing_error=True)
    worker = Mock(return_value=dict(status="completed", files=1, trials=1, runners=1))
    monkeypatch.setattr(catalog, "refresh_trial_file", worker)
    result = catalog.refresh_trials(
        settings, start=date(2026, 9, 25), end=date(2026, 10, 8), directory=tmp_path
    )
    assert worker.call_count == 4
    assert result["status"] == "partial"
    assert result["errors"] == [dict(meet=1, stage="listing", error_type="RuntimeError")]


def test_all_pending_opens_no_database_and_returns_wait(monkeypatch, tmp_path):
    settings = install_clients(monkeypatch)
    monkeypatch.setattr(
        catalog,
        "refresh_trial_file",
        Mock(return_value=dict(status="waiting_for_publication", text_runners=1, api_runners=0)),
    )
    monkeypatch.setattr(catalog, "create_engine_for_url", lambda *_a: pytest.fail("DB opened"))
    result = catalog.refresh_trials(
        settings, start=date(2026, 9, 25), end=date(2026, 10, 8), directory=tmp_path
    )
    assert result["status"] == "waiting_for_publication"
    assert len(result["pending"]) == 6 and result["runners"] == 0


def test_duplicate_text_key_is_rejected():
    trials, raw = trial_sources()
    trials[0].results += trials[0].results[:]
    with pytest.raises(SourceMismatch, match="trial_text_duplicate_key"):
        catalog.validate_trial_api(1, trials, [raw])


def test_discord_distinguishes_pending_from_errors(monkeypatch):
    sender = Mock(return_value="123")
    monkeypatch.setattr(job, "send_discord", sender)
    job.notify(
        SimpleNamespace(discord_webhook_url=None),
        "trials",
        dict(
            status="waiting_for_publication",
            runners=0,
            pending=[dict(meet=1, date="2026-10-08", text_runners=41)],
            errors=[],
        ),
    )
    content = sender.call_args.args[1]
    assert "주행심사 API 공개 대기" in content
    assert "서울 2026-10-08" in content
    assert "오류: 0" in content
    assert "목요일 19:10" in content
    assert "기존 기록 유지" in content
