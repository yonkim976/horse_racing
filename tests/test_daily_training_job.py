from datetime import date
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy import select
from test_horse_history import training_payload
from test_race_day import migrated_session
from test_special_training import SWIM_ITEM, _xml

from horse_racing.collectors.kra_api import KraApiClient, KraApiRateLimitError
from horse_racing.collectors.special_training import KraXmlApiClient
from horse_racing.db.models import Horse, HorseStartTraining, HorseSwimTraining, IngestionRun
from horse_racing.jobs import daily_training as job
from horse_racing.services.entry_sheet import IngestionSummary
from horse_racing.services.special_training import ingest_swim_training_date
from horse_racing.services.start_training_website import ingest_jeju_start_training_website


def website_body(label="20260930", locations=("400M 출발지점", "800M 출발지점")):
    rows = "".join(
        f"<tr><td>3조</td><td>12</td><td><a onclick=\"goPage1('3107491')\">백두명성</a>"
        f"</td><td>이동준</td><td>{location}</td><td>양호</td></tr>"
        for location in locations
    )
    headers = "".join(
        f"<th>{x}</th>" for x in ("소속조", "조번", "마명", "기승자", "조교장소", "비고")
    )
    html = f'<input name="trDateReplace" value="{label}"><table><tr>{headers}</tr>{rows}</table>'
    return html.encode("euc-kr")


def test_seven_inclusive_dates_and_no_io_default(monkeypatch, capsys):
    assert job.training_window(date(2026, 10, 2)) == [date(2026, 9, d) for d in range(26, 31)] + [
        date(2026, 10, 1),
        date(2026, 10, 2),
    ]
    assert job.training_window(date(2027, 1, 2))[0] == date(2026, 12, 27)
    monkeypatch.setattr(job, "get_settings", lambda: pytest.fail("dry-run read secrets"))
    monkeypatch.setattr(job, "create_engine_for_url", lambda _: pytest.fail("dry-run connected DB"))
    assert job.execute(as_of=date(2026, 10, 2)) == 0
    assert '"apply": false' in capsys.readouterr().out


def test_worker_routes_jeju_to_website_and_all_dates_once(tmp_path, monkeypatch):
    calls = []
    for name in (
        "ingest_training",
        "ingest_start_training",
        "ingest_jeju_start_training_website",
        "ingest_swim_training_date",
        "ingest_hill_training",
    ):

        def callback(*_args, kind=name, **kwargs):
            calls.append((kind, kwargs))
            return IngestionSummary(1, 1, 1, 1)

        monkeypatch.setattr(job, name, callback)
    days = job.training_window(date(2026, 10, 2))
    results = job.run_tasks(Mock(), Mock(), Mock(), Mock(), days=days, raw_dir=tmp_path)
    assert len(calls) == len(results) == 50
    starts = [kwargs for kind, kwargs in calls if kind == "ingest_start_training"]
    assert {r["meet"] for r in starts} == {1, 3}
    assert len(starts) == 14
    assert {
        kwargs["training_date"] for kind, kwargs in calls if kind != "ingest_hill_training"
    } == {day.strftime("%Y%m%d") for day in days}
    hill = calls[-1][1]
    assert (hill["start_date"], hill["end_date"]) == ("20260926", "20261002")


def test_quota_failure_stops_further_requests(tmp_path, monkeypatch):
    def fail(*_args, **_kwargs):
        raise KraApiRateLimitError("test quota")

    monkeypatch.setattr(job, "ingest_training", fail)
    for name in (
        "ingest_start_training",
        "ingest_jeju_start_training_website",
        "ingest_swim_training_date",
        "ingest_hill_training",
    ):
        monkeypatch.setattr(job, name, lambda *_a, **_k: pytest.fail("request after quota"))
    results = job.run_tasks(
        Mock(),
        Mock(),
        Mock(),
        Mock(),
        days=job.training_window(date(2026, 10, 2)),
        raw_dir=tmp_path,
    )
    assert results[0]["status"] == "failed"
    assert all(r["status"] == "not_attempted_quota" for r in results[1:])


def test_source_date_mismatch_rejected_before_writer():
    with KraApiClient(
        "test-key",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=training_payload())),
    ) as client:
        with pytest.raises(ValueError, match="날짜·지역"):
            list(
                job.DateCheckedApi(client).iter_pages(
                    endpoint="/API18_1/dailyTraining_1",
                    operation="dailyTraining_1",
                    public_params={"meet": 1, "tr_date": "20260930", "_type": "json"},
                )
            )


def test_website_replay_preserves_occurrences_ids_and_empty_day(tmp_path: Path):
    factory = migrated_session(tmp_path)
    content = website_body()
    with factory() as session:
        session.add(Horse(kra_horse_id="3107491", name_ko="백두명성"))
        session.commit()
        with httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=content))
        ) as client:
            ids = None
            for _ in range(3):
                summary = ingest_jeju_start_training_website(
                    session,
                    client,
                    training_date="20260930",
                    raw_data_dir=tmp_path / "raw",
                )
                assert summary.records_written == 2
                rows = session.scalars(
                    select(HorseStartTraining).order_by(HorseStartTraining.occurrence_no)
                ).all()
                current_ids = {row.id for row in rows}
                if ids is not None:
                    assert ids == current_ids
                ids = current_ids
                assert [r.location_raw for r in rows] == ["400M 출발지점", "800M 출발지점"]
                assert [r.occurrence_no for r in rows] == [1, 2]
                run = session.get(IngestionRun, summary.run_id)
                assert run.status == "completed" and run.completed_at_ms is not None
            content = website_body(locations=())
            ingest_jeju_start_training_website(
                session,
                client,
                training_date="20260930",
                raw_data_dir=tmp_path / "raw",
            )
            assert set(session.scalars(select(HorseStartTraining.id))) == ids
            content = website_body(locations=("400M 출발지점",))
            ingest_jeju_start_training_website(
                session,
                client,
                training_date="20260930",
                raw_data_dir=tmp_path / "raw",
            )
            assert len(session.scalars(select(HorseStartTraining.id)).all()) == 1
            content = website_body(label="20260929")
            with pytest.raises(ValueError, match="날짜"):
                ingest_jeju_start_training_website(
                    session,
                    client,
                    training_date="20260930",
                    raw_data_dir=tmp_path / "raw",
                )
            assert len(session.scalars(select(HorseStartTraining.id)).all()) == 1


def test_swim_date_replay_update_empty_and_wrong_date(tmp_path: Path):
    factory = migrated_session(tmp_path)
    content = _xml(SWIM_ITEM, 1)

    def handler(request):
        assert request.url.params["tr_date"] == "20260920"
        assert "tr_year" not in request.url.params
        return httpx.Response(200, content=content)

    with (
        factory() as session,
        KraXmlApiClient("test-key", transport=httpx.MockTransport(handler)) as client,
    ):
        for _ in range(2):
            ingest_swim_training_date(
                session, client, training_date="20260920", raw_data_dir=tmp_path / "raw"
            )
        rows = session.scalars(select(HorseSwimTraining)).all()
        assert len(rows) == 1
        row_id = rows[0].id
        content = _xml(SWIM_ITEM.replace("<cnt>2", "<cnt>4"), 1)
        ingest_swim_training_date(
            session, client, training_date="20260920", raw_data_dir=tmp_path / "raw"
        )
        session.expire_all()
        row = session.scalar(select(HorseSwimTraining))
        assert row.id == row_id and row.swim_count == 4
        content = _xml("", 0)
        ingest_swim_training_date(
            session, client, training_date="20260920", raw_data_dir=tmp_path / "raw"
        )
        assert set(session.scalars(select(HorseSwimTraining.id))) == {row_id}
        content = _xml(SWIM_ITEM.replace("20260920", "20260921"), 1)
        with pytest.raises(ValueError, match="불일치"):
            ingest_swim_training_date(
                session, client, training_date="20260920", raw_data_dir=tmp_path / "raw"
            )
        assert set(session.scalars(select(HorseSwimTraining.id))) == {row_id}


def test_changes_ignore_observation_updates_but_count_business_changes():
    assert job.changes({1: ("old",), 2: ("same",)}, {1: ("new",), 2: ("same",), 3: ("added",)}) == {
        "new": 1,
        "changed": 1,
        "unchanged": 1,
        "removed_from_latest_snapshot": 0,
    }
