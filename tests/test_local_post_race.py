from datetime import date, datetime
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from test_local_race_day import DAY, result
from test_local_race_day import session as shared_session

from horse_racing.collectors.kra_api import FetchedPage
from horse_racing.db.models import Horse, OddsSnapshot, RaceEntry, SourceDocument
from horse_racing.jobs import local_post_race as job
from horse_racing.jobs.weekly_entry_cards import KST
from horse_racing.parsers.race_day import FinalDividendItem
from horse_racing.services import closing_dividends as service
from horse_racing.services.live_race_day import (
    apply_items,
    entry_index,
    load_races,
    refresh_completion,
)

session = shared_session


def odds(pool, selection, *, value=2.5, day=DAY, race=1, meet="제주"):
    numbers = [int(n) for n in selection.split("-")]
    return FinalDividendItem.model_validate(
        {
            "rcDate": day.strftime("%Y%m%d"),
            "rcNo": race,
            "meet": meet,
            "pool": pool,
            "chulNo": numbers[0],
            "chulNo2": numbers[1] if len(numbers) > 1 else 0,
            "chulNo3": numbers[2] if len(numbers) > 2 else 0,
            "odds": value,
        }
    )


def all_pools():
    return [
        odds(p, "-".join(str(n) for n in range(1, arity + 1))) for p, arity in service.ARITY.items()
    ]


def complete_race(session):
    race = load_races(session, DAY)[0]
    race.field_size = 3
    session.add(
        RaceEntry(race=race, horse=Horse(kra_horse_id="3100003", name_ko="테스트3"), horse_number=3)
    )
    session.commit()
    races = load_races(session, DAY)
    apply_items(
        session,
        kind="details",
        items=[result(n, n, detailed=True) for n in (1, 2, 3)],
        entries=entry_index(races),
        observed_ms=10,
    )
    refresh_completion(races)
    session.commit()
    return load_races(session, DAY)


def test_dry_run_and_night_no_secrets(monkeypatch):
    monkeypatch.setattr(
        job.live, "load_settings", lambda: pytest.fail("dry run must not read secrets")
    )
    now = datetime(2026, 10, 3, 1, tzinfo=KST)
    assert job.execute(mode="repair", now=now) == 0
    assert job.execute(mode="dividends", apply=True, scheduled=True, now=now) == 0
    with pytest.raises(ValueError, match="outside_recent"):
        job.execute(mode="repair", through=date(2026, 9, 20), now=now)
    with pytest.raises(ValueError, match="override_forbidden"):
        job.execute(mode="repair", scheduled=True, through=DAY, now=now)


def test_plan_last_seven_days_and_future_guard():
    now = datetime(2026, 10, 3, 9, tzinfo=KST)
    assert job.plan(mode="repair", end=now.date(), now=now, lookback=7) == [
        date(2026, 9, 27),
        date(2026, 9, 28),
        date(2026, 9, 29),
        date(2026, 9, 30),
        date(2026, 10, 1),
        DAY,
        now.date(),
    ]
    with pytest.raises(ValueError, match="outside_recent"):
        job.plan(mode="repair", end=date(2026, 10, 4), now=now, lookback=7)


def test_no_pre_race_or_cancelled_quotes(session):
    races = load_races(session, DAY)
    assert service.prepare(all_pools(), day=DAY, meet=2, races=races)[0] == {}
    races = complete_race(session)
    for entry in races[0].entries:
        entry.result.finish_position = 99
        entry.result.rank_remark = "경주취소"
    assert service.prepare(all_pools(), day=DAY, meet=2, races=races)[0] == {}


def test_pending_pool_does_not_insert_partial_race(session):
    races = complete_race(session)
    ready, expected, zeros, pending = service.prepare(
        all_pools()[:-1], day=DAY, meet=2, races=races
    )
    assert pending == [1] and not expected and not ready
    assert (
        service.reconcile(session, ready=ready, expected=expected, zeros=zeros, observed_ms=10)[
            "inserted"
        ]
        == 0
    )
    assert session.scalar(select(func.count()).select_from(OddsSnapshot)) == 0


def test_official_dead_heat_is_not_treated_as_cancelled(session):
    races = complete_race(session)
    races[0].entries[1].result.finish_position = 1
    assert service.settled(races[0])
    assert len(service.prepare(all_pools(), day=DAY, meet=2, races=races)[1]) == 7


def test_dividends_idempotent_and_correction_audit(session):
    races = complete_race(session)
    ready, expected, zeros, pending = service.prepare(all_pools(), day=DAY, meet=2, races=races)
    assert not pending
    first = service.reconcile(session, ready=ready, expected=expected, zeros=zeros, observed_ms=10)
    session.commit()
    assert first["inserted"] == 7
    repeat = service.reconcile(session, ready=ready, expected=expected, zeros=zeros, observed_ms=20)
    assert repeat["inserted"] == repeat["updated"] == 0
    assert set(session.scalars(select(OddsSnapshot.observed_at_ms))) == {10}
    expected[races[0].id, "WIN", "1"] = 4.5
    corrected = service.reconcile(
        session, ready=ready, expected=expected, zeros=zeros, observed_ms=30
    )
    assert corrected["updated"] == 1 and corrected["changes"][0]["old_odds"] == 2.5
    assert session.scalar(select(func.count()).select_from(OddsSnapshot)) == 7


def test_dividend_scope_and_conflict_guards(session):
    races = complete_race(session)
    for bad, error in [
        ([odds("WIN", "1", meet="서울")], "date_venue"),
        ([odds("WIN", "1", race=99)], "unknown_race"),
        ([odds("WIN", "99")], "invalid_selection"),
        ([*all_pools(), odds("WIN", "1", value=4)], "conflicting_source"),
        ([*all_pools(), odds("WIN", "1", value=0)], "conflicting_zero"),
    ]:
        with pytest.raises(ValueError, match=error):
            service.prepare(bad, day=DAY, meet=2, races=races)


@pytest.mark.parametrize("detail_venue", ["제주", "-"])
def test_results_fill_missing_and_correct_only_with_details(session, detail_venue):
    pages = [SimpleNamespace(retrieved_at_ms=10)]
    job.result_stage(session, pages=pages, items=[result(1, 1)], kind="results", day=DAY, meet=2)
    session.commit()
    assert load_races(session, DAY)[0].entries[0].result.finish_position == 1
    job.result_stage(session, pages=pages, items=[result(1, 2)], kind="results", day=DAY, meet=2)
    assert load_races(session, DAY)[0].entries[0].result.finish_position == 1
    corrected = job.result_stage(
        session,
        pages=pages,
        items=[result(1, 2, detailed=True, rsutRaceRcd="71.1", schdRccrsNm=detail_venue)],
        kind="details",
        day=DAY,
        meet=2,
    )
    session.commit()
    assert corrected["changes"][0]["before"]["finish"] == 1
    assert load_races(session, DAY)[0].entries[0].result.finish_time_ms == 71100
    empty = job.result_stage(session, pages=pages, items=[], kind="details", day=DAY, meet=2)
    assert empty["changed_entries"] == 0
    assert load_races(session, DAY)[0].entries[0].result.finish_time_ms == 71100


def test_existing_extra_is_not_deleted(session):
    races = complete_race(session)
    ready, expected, zeros, _ = service.prepare(all_pools(), day=DAY, meet=2, races=races)
    service.reconcile(session, ready=ready, expected=expected, zeros=zeros, observed_ms=10)
    session.commit()
    with pytest.raises(ValueError, match="absent_from_source"):
        service.reconcile(session, ready=ready, expected={}, zeros=set(), observed_ms=20)
    assert session.scalar(select(func.count()).select_from(OddsSnapshot)) == 7


def test_all_zero_dividends_waits_for_publication(session):
    races = complete_race(session)
    items = [i.model_copy(update={"odds": None}) for i in all_pools()]
    assert service.prepare(items, day=DAY, meet=2, races=races)[3] == [1]


def test_notify_keeps_secret_type_and_quiet_when_unchanged(monkeypatch):
    messages = []

    def send(webhook, content):
        assert isinstance(webhook, SecretStr)
        messages.append(content)
        return "123"

    monkeypatch.setattr(job, "send_discord", send)
    summary = {
        "observations": [],
        "mode": "dividends",
        "status": "completed",
        "start": str(DAY),
        "end": str(DAY),
        "pending": [],
        "errors": [],
        "run_id": 1,
        "elapsed_seconds": 1,
    }
    settings = SimpleNamespace(discord_webhook_url=SecretStr("not-exposed"))
    job.notify(settings, summary, scheduled=True)
    assert not messages
    job.notify(settings, summary, scheduled=False)
    assert len(messages) == 1


@pytest.mark.parametrize("empty_details", [False, True])
def test_two_full_cycles_archive_once_and_verify_committed_rows(
    session, tmp_path, monkeypatch, empty_details
):
    complete_race(session)
    monkeypatch.setattr(job, "ROOT", tmp_path)

    def fetch(client, kind, day, meet):
        items = (
            all_pools()
            if kind == "dividends"
            else [result(n, n, detailed=kind == "details") for n in (1, 2, 3)]
        )
        if kind == "details" and empty_details:
            items = []
        page = FetchedPage(
            endpoint="/test",
            operation=kind,
            source_url="https://example.com/test",
            public_params={"pageNo": 1},
            requested_at_ms=10,
            retrieved_at_ms=20,
            status_code=200,
            content_type="application/json",
            body=kind.encode(),
            payload={},
        )
        return [page], items

    monkeypatch.setattr(job, "fetch", fetch)
    state = {}
    args = dict(
        days=[DAY],
        mode="repair",
        now=datetime(2026, 10, 3, 9, tzinfo=KST),
        state=state,
        state_path=tmp_path / "state.json",
        raw_dir=tmp_path / "raw",
    )
    first = job.collect(session, None, **args)
    second = job.collect(session, None, **args)
    expected_status = "partial" if empty_details else "completed"
    assert first["status"] == second["status"] == expected_status
    assert not first["errors"] and not second["errors"]
    assert first["observations"][-1]["inserted"] == 7
    assert second["observations"][-1]["inserted"] == 0
    assert session.scalar(select(func.count()).select_from(SourceDocument)) == 3
    assert session.scalar(select(func.count()).select_from(OddsSnapshot)) == 7
