from datetime import date, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from test_race_day import api_payload, migrated_session

from horse_racing.collectors.kra_api import KraApiClient, KraApiTransientError
from horse_racing.config import Settings
from horse_racing.db.models import (
    Horse,
    HorseWeightHistory,
    Jockey,
    JockeyChange,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    RaceScratch,
    SourceDocument,
)
from horse_racing.jobs import local_race_day as job
from horse_racing.parsers.horse_history import HorseWeightItem
from horse_racing.parsers.race_day import AiRaceResultItem, DetailedRaceResultItem
from horse_racing.parsers.race_supplemental import JockeyChangeItem, RaceScratchItem
from horse_racing.services.live_race_day import (
    LiveSourceMismatch,
    apply_items,
    entry_index,
    load_races,
    race_has_complete_results,
    refresh_completion,
    snapshot,
    validate_items,
)

DAY = date(2026, 10, 2)


@pytest.fixture
def session(tmp_path):
    factory = migrated_session(tmp_path)
    with factory() as session:
        course = Racecourse(kra_meet_code=2, code="JEJU", name_ko="제주")
        jockey = Jockey(kra_jockey_id="060001", name_ko="기존기수")
        race = Race(
            racecourse=course,
            race_date_local=DAY,
            race_number=1,
            distance_m=1000,
            field_size=2,
            scheduled_at_ms=int(datetime(2026, 10, 2, 13, tzinfo=job.KST).timestamp() * 1000),
        )
        session.add_all([race, jockey])
        for n in (1, 2):
            session.add(
                RaceEntry(
                    race=race,
                    horse=Horse(kra_horse_id=f"310000{n}", name_ko=f"테스트{n}"),
                    horse_number=n,
                    jockey=jockey,
                    carried_weight_kg=55,
                )
            )
        session.commit()
        yield session


def weight(n=1, **values):
    return HorseWeightItem.model_validate(
        {
            "hrNo": f"310000{n}",
            "hrName": f"테스트{n}",
            "meet": "제주",
            "rcDate": "20261002",
            "rcNo": 1,
            "chulNo": n,
            "wgHr": 290,
            "wgHrDiff": 3,
            **values,
        }
    )


def jockey(before="060001", after="060002", **values):
    return JockeyChangeItem.model_validate(
        {
            "hrNo": "3100001",
            "hrName": "테스트1",
            "meet": "제주",
            "rcDate": "20261002",
            "rcNo": 1,
            "chulNo": 1,
            "jkBef": before,
            "jkAft": after,
            "jkAftName": f"새기수{after}",
            "aftBudam": 54.5,
            **values,
        }
    )


def scratch():
    return RaceScratchItem.model_validate(
        {
            "hrNo": "3100002",
            "hrName": "테스트2",
            "meet": "제주",
            "rcDate": "20261002",
            "rcNo": 1,
            "chulNo": 2,
            "reason": "마체이상",
        }
    )


def result(n=1, rank=1, *, detailed=False, **values):
    if detailed:
        return DetailedRaceResultItem.model_validate(
            {
                "schdRaceDt": "20261002",
                "schdRaceNo": 1,
                "cndRaceDs": 1000,
                "schdRccrsNm": "제주",
                "pthrGtno": n,
                "pthrHrno": f"310000{n}",
                "pthrHrnm": f"테스트{n}",
                "rsutRk": rank,
                "rsutRaceRcd": "70.5",
                "rsutWetr": "맑음",
                "rsutTrckStus": "건조 (3%)",
                **values,
            }
        )
    return AiRaceResultItem.model_validate(
        {
            "raceDt": "20261002",
            "raceNo": 1,
            "raceDs": 1000,
            "rccrsNm": "제주",
            "gtno": n,
            "hrno": f"310000{n}",
            "hrnm": f"테스트{n}",
            "rk": rank,
            "raceRcd": "70.5",
            **values,
        }
    )


def apply(session, kind, items):
    races = load_races(session, DAY)
    index = entry_index(races)
    validate_items(items, kind=kind, day=DAY, meet=2, entries=index)
    apply_items(session, kind=kind, items=items, entries=index, observed_ms=123456789)
    session.commit()
    return races


def test_weights_update_serving_and_history_without_duplicates(session):
    races = apply(session, "weights", [weight()])
    apply(session, "weights", [weight()])
    assert session.scalar(select(func.count()).select_from(HorseWeightHistory)) == 1
    assert races[0].entries[0].body_weight_kg == 290
    assert races[0].entries[0].body_weight_change_kg == 3
    apply(session, "weights", [weight(wgHr="-", wgHrDiff="-")])
    apply(session, "weights", [weight(wgHr=0, wgHrDiff=0)])
    assert races[0].entries[0].body_weight_kg == 290
    assert session.scalar(select(HorseWeightHistory)).body_weight_kg == 290


def test_zero_weight_is_not_published_and_repairs_only_legacy_zero(session):
    races = load_races(session, DAY)
    races[0].entries[0].body_weight_kg = 0
    session.commit()
    apply(session, "weights", [weight(wgHr=0, wgHrDiff=0)])
    assert races[0].entries[0].body_weight_kg is None
    assert session.scalar(select(func.count()).select_from(HorseWeightHistory)) == 0


def test_jockey_serving_and_chain_ignore_response_order(session):
    apply(session, "jockeys", [jockey("060002", "060003"), jockey()])
    apply(session, "jockeys", [jockey(), jockey("060002", "060003")])
    entries = load_races(session, DAY)[0].entries
    assert entries[0].jockey.kra_jockey_id == "060003"
    assert entries[0].carried_weight_kg == 54.5
    assert session.scalar(select(func.count()).select_from(JockeyChange)) == 2


@pytest.mark.parametrize(
    "items",
    [
        [jockey(), jockey("060001", "060003")],
        [jockey(), jockey("060002", "060001")],
        [jockey(), jockey("060003", "060004"), jockey("060004", "060003")],
    ],
)
def test_ambiguous_jockey_changes_fail_closed(session, items):
    with pytest.raises(LiveSourceMismatch):
        apply(session, "jockeys", items)
    session.rollback()
    assert load_races(session, DAY)[0].entries[0].jockey.kra_jockey_id == "060001"


def test_scratches_preserved_on_empty_response(session):
    apply(session, "scratches", [scratch()])
    races = apply(session, "scratches", [scratch()])
    apply(session, "scratches", [])
    assert races[0].entries[1].scratched
    assert session.scalar(select(func.count()).select_from(RaceScratch)) == 1


def test_only_full_results_complete_and_no_placeholder_overwrite(session):
    races = apply(session, "results", [result()])
    assert not race_has_complete_results(races[0])
    races[0].status = "completed"
    refresh_completion(races)
    assert races[0].status == "scheduled"
    apply(session, "results", [result(rank="-")])
    assert races[0].entries[0].result.finish_position == 1
    apply(session, "scratches", [scratch()])
    refresh_completion(races)
    assert race_has_complete_results(races[0])
    assert races[0].status == "completed"


def test_details_correct_results_but_ai_cannot_regress_them(session):
    apply(session, "results", [result()])
    races = apply(session, "details", [result(rank=2, detailed=True, rsutRaceRcd="71.5")])
    apply(session, "results", [result(rank=1)])
    assert races[0].entries[0].result.finish_position == 2
    assert races[0].entries[0].result.finish_time_ms == 71500
    assert races[0].weather == "맑음"
    assert races[0].track_moisture_percent == 3
    assert session.scalar(select(func.count()).select_from(RaceResult)) == 1


@pytest.mark.parametrize(
    "item",
    [
        weight(rcDate="20261001"),
        weight(meet="서울"),
        weight(chulNo=2),
        weight(hrNo="3999999"),
        weight(wgHr=999),
    ],
)
def test_source_mismatch_never_writes(session, item):
    with pytest.raises(LiveSourceMismatch):
        apply(session, "weights", [item])
    assert session.scalar(select(func.count()).select_from(HorseWeightHistory)) == 0


def test_duplicate_source_rejected(session):
    with pytest.raises(LiveSourceMismatch):
        apply(session, "weights", [weight(), weight()])


def test_dry_run_no_secrets_or_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("dry run touched secrets")

    monkeypatch.setattr(job, "load_settings", forbidden)
    assert job.execute() == 0


def test_window_uses_actual_schedule_not_weekday():
    now = datetime(2026, 10, 2, 12, tzinfo=job.KST)
    races = [SimpleNamespace(scheduled_at_ms=int((now + timedelta(hours=1)).timestamp() * 1000))]
    assert job.in_window(races, now)
    assert not job.in_window(races, now - timedelta(minutes=1))
    assert not job.in_window([], now)
    assert job.in_window([SimpleNamespace(scheduled_at_ms=None)], now)


def test_changed_sources_archived_once_and_second_cycle_no_business_changes(session, tmp_path):
    payloads = {
        "/B551015/API155/raceResult": api_payload([]),
        "/B551015/API156/raceRsutDtl": api_payload([]),
        "/B551015/API25_1/entryHorseWeightInfo_1": api_payload(
            [{**weight().model_dump(by_alias=True, mode="json"), "rcDate": "20261002"}]
        ),
        "/B551015/API10_1/jockeyChangeInfo_1": api_payload([]),
        "/B551015/API9_1/raceHorseCancelInfo_1": api_payload([]),
    }

    def handler(request):
        return httpx.Response(200, json=payloads[request.url.path])

    state = {}
    with KraApiClient("secret", transport=httpx.MockTransport(handler)) as client:
        first = job.collect(
            session,
            client,
            races=load_races(session, DAY),
            day=DAY,
            state=state,
            state_path=tmp_path / "state.json",
            raw_dir=tmp_path / "raw",
            scheduled=False,
        )
        second = job.collect(
            session,
            client,
            races=load_races(session, DAY),
            day=DAY,
            state=state,
            state_path=tmp_path / "state.json",
            raw_dir=tmp_path / "raw",
            scheduled=False,
        )
    assert not first["errors"] and not second["errors"]
    assert len(first["changes"]["weights"]) == 1
    assert not any(second["changes"].values())
    assert session.scalar(select(func.count()).select_from(SourceDocument)) == 5
    assert session.scalar(select(func.count()).select_from(HorseWeightHistory)) == 1


def test_discord_quiet_on_unchanged_and_deduplicates_failure(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(job, "send_discord", lambda *args: calls.append(args) or "123")
    settings = Settings(_env_file=None, discord_webhook_url=SecretStr("not_exposed"))
    summary = {"day": str(DAY), "errors": [], "changes": {}, "new_completed": []}
    state = {}
    path = tmp_path / "state.json"
    job.notify(settings, summary, state=state, path=path)
    assert not calls
    summary["errors"] = [{"meet": 2, "stage": "weights", "type": "KraApiError"}]
    job.notify(settings, summary, state=state, path=path)
    job.notify(settings, summary, state=state, path=path)
    assert len(calls) == 1
    summary["errors"] = []
    job.notify(settings, summary, state=state, path=path)
    assert len(calls) == 2  # Recovery is meaningful, unlike every successful poll.


def test_local_state_contains_no_credentials(tmp_path):
    path = tmp_path / "state.json"
    state = {"counts": {"/API25_1/entryHorseWeightInfo_1": 1}}
    job.write_state(path, state)
    assert job.read_state(path) == state
    assert path.stat().st_mode & 0o777 == 0o600


def test_snapshot_difference_is_business_only(session):
    races = load_races(session, DAY)
    before = snapshot(races)
    apply(session, "weights", [weight()])
    changes = job.summarize_changes(before, snapshot(races))
    assert len(changes["weights"]) == 1
    assert not changes["jockeys"] and not changes["results"]


def test_live_retry_counts_failed_requests_and_stops_after_two(tmp_path):
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(503)

    state = {}
    with job.LocalKraApiClient("secret", transport=httpx.MockTransport(handler)) as client:
        job.attach_budget(client, state=state, state_path=tmp_path / "state.json", maximum=800)
        with pytest.raises(KraApiTransientError):
            list(
                client.iter_pages(
                    endpoint="/API25_1/entryHorseWeightInfo_1",
                    operation="entryHorseWeightInfo_1",
                    public_params={},
                )
            )
    assert len(attempts) == 2
    assert state["counts"]["/API25_1/entryHorseWeightInfo_1"] == 2


def test_budget_stops_before_http_request_and_counts_all_venues(tmp_path):
    attempts = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(200, json=api_payload([]))

    state = {}
    with job.LocalKraApiClient("secret", transport=httpx.MockTransport(handler)) as client:
        job.attach_budget(client, state=state, state_path=tmp_path / "state.json", maximum=1)
        list(
            client.iter_pages(
                endpoint="/API25_1/entryHorseWeightInfo_1",
                operation="entryHorseWeightInfo_1",
                public_params={"meet": 2},
            )
        )
        with pytest.raises(job.LocalApiBudgetExceeded):
            list(
                client.iter_pages(
                    endpoint="/API25_1/entryHorseWeightInfo_1",
                    operation="entryHorseWeightInfo_1",
                    public_params={"meet": 3},
                )
            )
    assert len(attempts) == 1
    assert state["counts"]["/API25_1/entryHorseWeightInfo_1"] == 1
