import importlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from horse_racing.db.base import Base
from horse_racing.db.models import (
    Horse,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    RunningTrial,
    RunningTrialResult,
)
from horse_racing.web.dashboard import (
    CalendarDay,
    CalendarIndex,
    _recent_form_by_horse,
    _recent_trial_form_by_horse,
    calendar_month_options,
)
from horse_racing.web.insights import format_trial_form_line, format_trial_form_token

_BEFORE = date(2026, 9, 1)
_app_module = importlib.import_module("horse_racing.web.app")


@pytest.fixture
def db_session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'dashboard-performance.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


class _RecordingResult:
    def __init__(self, result: Any, owner: "_RecordingSession") -> None:
        self._result = result
        self._owner = owner

    def all(self):
        rows = self._result.all()
        self._owner.row_batches.append(rows)
        return rows


class _RecordingSession:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.statements: list[str] = []
        self.row_batches: list[list[tuple[Any, ...]]] = []

    def execute(self, statement, *args, **kwargs):
        self.statements.append(str(statement))
        result = self._session.execute(statement, *args, **kwargs)
        return _RecordingResult(result, self)


def _seed_recent_rows(session: Session) -> tuple[int, int, int]:
    course = Racecourse(kra_meet_code=2, code="JEJU", name_ko="제주")
    horses = [
        Horse(kra_horse_id=f"performance-{index}", name_ko=f"성적말{index}")
        for index in range(1, 4)
    ]
    session.add_all([course, *horses])
    session.flush()
    first, second, third = (horse.id for horse in horses)

    race_scenarios = [
        (94, False, True),
        (1, True, False),
        (2, False, False),
        (3, False, False),
        (None, False, False),
        (8, False, False),
        (1, False, False),
    ]
    for offset, (position, disqualified, scratched) in enumerate(race_scenarios, start=1):
        race = Race(
            racecourse=course,
            race_date_local=_BEFORE - timedelta(days=offset),
            race_number=1,
            distance_m=900,
            status="completed",
        )
        entry = RaceEntry(race=race, horse=horses[0], horse_number=1, scratched=scratched)
        session.add(RaceResult(
            race_entry=entry,
            finish_position=position,
            disqualified=disqualified,
        ))

    second_race = Race(
        racecourse=course,
        race_date_local=_BEFORE - timedelta(days=20),
        race_number=1,
        distance_m=900,
        status="completed",
    )
    second_entry = RaceEntry(race=second_race, horse=horses[1], horse_number=1)
    session.add(RaceResult(race_entry=second_entry, finish_position=1))

    trial_scenarios = [
        (1, "\t출\n"),
        (2, "심"),
        (1, "주"),
        (1, None),
        (2, "\t합\n"),
        (None, "불"),
        (90, "연"),
        (3, "유"),
        (4, "합"),
        (95, None),
        (None, None),
    ]
    for offset, (position, judgement) in enumerate(trial_scenarios, start=1):
        trial = RunningTrial(
            meet_code=2,
            trial_date_local=_BEFORE - timedelta(days=offset),
            trial_race_number=1,
            distance_m=800,
            observed_at_ms=offset,
        )
        session.add(RunningTrialResult(
            trial=trial,
            horse=horses[0],
            horse_number=1,
            horse_name_raw=horses[0].name_ko,
            finish_position=position,
            judgement=judgement,
            observed_at_ms=offset,
        ))

    second_trial = RunningTrial(
        meet_code=2,
        trial_date_local=_BEFORE - timedelta(days=20),
        trial_race_number=1,
        distance_m=800,
        observed_at_ms=100,
    )
    session.add(RunningTrialResult(
        trial=second_trial,
        horse=horses[1],
        horse_number=1,
        horse_name_raw=horses[1].name_ko,
        finish_position=5,
        observed_at_ms=100,
    ))
    session.flush()
    return first, second, third


def _legacy_race_forms(session: Session, horse_ids: list[int]) -> dict[int, str]:
    rows = session.execute(
        select(
            RaceEntry.horse_id,
            Race.race_date_local,
            Race.id,
            RaceResult.finish_position,
            RaceResult.disqualified,
        )
        .join(Race, Race.id == RaceEntry.race_id)
        .join(RaceResult, RaceResult.race_entry_id == RaceEntry.id)
        .where(
            RaceEntry.horse_id.in_(horse_ids),
            Race.race_date_local < _BEFORE,
            RaceResult.finish_position.is_not(None),
        )
        .order_by(RaceEntry.horse_id, Race.race_date_local.desc(), Race.id.desc())
    ).all()
    form: dict[int, list[str]] = defaultdict(list)
    for horse_id, _day, _race_id, position, disqualified in rows:
        finishes = form[horse_id]
        if len(finishes) >= 5:
            continue
        finishes.append("-" if disqualified or position >= 90 else str(position))
    return {horse_id: "-".join(finishes) for horse_id, finishes in form.items()}


def _legacy_trial_forms(session: Session, horse_ids: list[int]) -> dict[int, str]:
    rows = session.execute(
        select(
            RunningTrialResult.horse_id,
            RunningTrial.trial_date_local,
            RunningTrial.id,
            RunningTrialResult.finish_position,
            RunningTrialResult.judgement,
        )
        .join(RunningTrial, RunningTrial.id == RunningTrialResult.running_trial_id)
        .where(
            RunningTrialResult.horse_id.in_(horse_ids),
            RunningTrial.trial_date_local < _BEFORE,
        )
        .order_by(
            RunningTrialResult.horse_id,
            RunningTrial.trial_date_local.desc(),
            RunningTrial.id.desc(),
        )
    ).all()
    form: dict[int, list[str]] = defaultdict(list)
    for horse_id, _day, _trial_id, position, judgement in rows:
        if len(form[horse_id]) >= 5:
            continue
        token = format_trial_form_token(position, judgement)
        if token:
            form[horse_id].append(token)
    return {
        horse_id: format_trial_form_line(tokens)
        for horse_id, tokens in form.items()
        if tokens
    }


def test_recent_form_queries_return_at_most_five_rows_per_horse_with_legacy_output(
    db_session: Session,
) -> None:
    first, second, third = _seed_recent_rows(db_session)
    horse_ids = [first, second, third]
    expected_race = _legacy_race_forms(db_session, horse_ids)
    expected_trial = _legacy_trial_forms(db_session, horse_ids)

    race_recorder = _RecordingSession(db_session)
    actual_race = _recent_form_by_horse(race_recorder, horse_ids, _BEFORE)
    trial_recorder = _RecordingSession(db_session)
    actual_trial = _recent_trial_form_by_horse(trial_recorder, horse_ids, _BEFORE)

    assert actual_race == expected_race
    assert actual_trial == expected_trial
    assert actual_race[first] == "----2-3-8"
    assert actual_trial[first] == "심 1-2합-불-연-3유"
    assert actual_race[second] == "1"
    assert actual_trial[second] == "심 5"
    assert third not in actual_race and third not in actual_trial

    for recorder in (race_recorder, trial_recorder):
        assert len(recorder.row_batches) == 1
        assert "row_number() OVER" in recorder.statements[0]
        counts = Counter(row[0] for row in recorder.row_batches[0])
        assert all(count <= 5 for count in counts.values())


def test_calendar_month_options_keep_only_selected_month_and_descending_order() -> None:
    index = CalendarIndex(
        days=(
            CalendarDay(date(2026, 9, 20), "completed", True, False),
            CalendarDay(date(2026, 8, 30), "scheduled", True, False),
            CalendarDay(date(2026, 8, 13), "completed", False, True),
            CalendarDay(date(2026, 7, 14), "completed", True, True),
        )
    )

    options = calendar_month_options(index, date(2026, 8, 1))

    assert [(item.value, item.status, item.has_race, item.has_trial) for item in options] == [
        ("2026-08-30", "scheduled", True, False),
        ("2026-08-13", "completed", False, True),
    ]


def test_home_reuses_calendar_index_and_fetches_only_requested_month(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'calendar-performance.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        course = Racecourse(kra_meet_code=2, code="JEJU", name_ko="제주")
        session.add(course)
        session.flush()
        session.add_all(
            [
                Race(
                    racecourse=course,
                    race_date_local=date(2026, 8, 21),
                    race_number=1,
                    distance_m=900,
                    status="scheduled",
                ),
                Race(
                    racecourse=course,
                    race_date_local=date(2026, 9, 20),
                    race_number=1,
                    distance_m=900,
                    status="completed",
                ),
                RunningTrial(
                    meet_code=2,
                    trial_date_local=date(2026, 8, 13),
                    trial_race_number=1,
                    distance_m=800,
                    observed_at_ms=1,
                ),
            ]
        )
        session.commit()

    def session_factory() -> Session:
        return Session(engine, expire_on_commit=False)

    original_loader = _app_module.load_calendar_index
    loader_calls = 0

    def counted_loader(session: Session):
        nonlocal loader_calls
        loader_calls += 1
        return original_loader(session)

    monkeypatch.setattr(_app_module, "load_calendar_index", counted_loader)
    monkeypatch.setattr("horse_racing.web.dashboard.today_seoul", lambda: date(2026, 10, 3))
    phone = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"}

    with TestClient(_app_module.create_app(session_factory=session_factory)) as client:
        default_home = client.get("/")
        august_home = client.get("/?date=2026-08-21")
        september_home = client.get("/?date=2026-09-20")
        mobile_home = client.get("/?date=2026-08-21", headers=phone)
        august_api = client.get("/api/calendar?month=2026-08")
        invalid_month = client.get("/api/calendar?month=2026-13")
        repeated_month = client.get(
            "/api/calendar?month=2026-08&month=2026-09"
        )

    assert default_home.status_code == august_home.status_code == september_home.status_code == 200
    assert 'name="date"' in default_home.text
    assert 'value="2026-09-20"' in default_home.text
    assert mobile_home.status_code == 200
    assert 'class="mobile-app mobile-home"' in mobile_home.text
    assert "data-easy-toggle" in mobile_home.text
    assert "dashboard.js?v=34" in mobile_home.text

    calendar_script = re.search(
        r'<script id="race-calendar-data"[^>]*>(.*?)</script>',
        august_home.text,
        re.DOTALL,
    )
    assert calendar_script is not None
    initial_dates = json.loads(calendar_script.group(1))
    assert [item["date"] for item in initial_dates] == [
        "2026-08-21",
        "2026-08-13",
    ]
    assert 'data-min-date="2026-08-13"' in august_home.text
    assert 'data-max-date="2026-09-20"' in august_home.text

    assert august_api.status_code == 200
    assert august_api.headers["cache-control"] == "public, max-age=30"
    assert august_api.json() == [
        {
            "date": "2026-08-21",
            "status": "scheduled",
            "hasRace": True,
            "hasTrial": False,
        },
        {
            "date": "2026-08-13",
            "status": "trial-only",
            "hasRace": False,
            "hasTrial": True,
        },
    ]
    assert invalid_month.status_code == repeated_month.status_code == 422
    assert loader_calls == 1
    engine.dispose()


def test_explicit_layout_home_responses_cache_by_view_and_set_cookies_per_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'layout-cache-performance.sqlite3'}")
    Base.metadata.create_all(engine)

    def session_factory() -> Session:
        return Session(engine, expire_on_commit=False)

    original_loader = _app_module.load_dashboard
    rendered_layouts: list[bool] = []

    def counted_loader(session: Session, **kwargs):
        rendered_layouts.append(kwargs["mobile_view"])
        return original_loader(session, **kwargs)

    monkeypatch.setattr(_app_module, "load_dashboard", counted_loader)
    phone = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"}

    with TestClient(_app_module.create_app(session_factory=session_factory)) as client:
        mobile_first = client.get("/?layout=mobile", headers=phone)
        mobile_cached = client.get("/?layout=mobile", headers=phone)
        desktop_first = client.get("/?layout=desktop", headers=phone)
        desktop_cached = client.get("/?layout=desktop", headers=phone)
        automatic_first = client.get("/?layout=auto", headers=phone)
        automatic_cached = client.get("/?layout=auto", headers=phone)

        authorized_first = client.get(
            "/?layout=mobile", headers={**phone, "authorization": "Bearer private"}
        )
        authorized_second = client.get(
            "/?layout=mobile", headers={**phone, "authorization": "Bearer private"}
        )
        cookie_first = client.get(
            "/?layout=mobile", headers={**phone, "cookie": "tracking=private"}
        )
        cookie_second = client.get(
            "/?layout=mobile", headers={**phone, "cookie": "tracking=private"}
        )

    assert all(
        response.status_code == 200
        for response in (
            mobile_first,
            mobile_cached,
            desktop_first,
            desktop_cached,
            automatic_first,
            automatic_cached,
            authorized_first,
            authorized_second,
            cookie_first,
            cookie_second,
        )
    )
    assert 'data-layout="mobile"' in mobile_first.text
    assert mobile_first.text == mobile_cached.text
    assert "hr-layout=mobile" in mobile_first.headers["set-cookie"]
    assert "hr-layout=mobile" in mobile_cached.headers["set-cookie"]
    assert 'data-layout="desktop"' in desktop_first.text
    assert desktop_first.text == desktop_cached.text
    assert "hr-layout=desktop" in desktop_first.headers["set-cookie"]
    assert "hr-layout=desktop" in desktop_cached.headers["set-cookie"]
    assert 'data-layout="mobile"' in automatic_first.text
    assert automatic_first.text == automatic_cached.text
    assert "Max-Age=0" in automatic_first.headers["set-cookie"]
    assert "Max-Age=0" in automatic_cached.headers["set-cookie"]
    for response in (
        mobile_first,
        mobile_cached,
        desktop_first,
        desktop_cached,
        automatic_first,
        automatic_cached,
    ):
        assert response.headers["cache-control"] == "private, no-store"
        assert "cookie" in {part.strip().lower() for part in response.headers["vary"].split(",")}

    # Mobile, desktop, and automatic mobile each use a separate internal key;
    # repeated requests hit the local response cache. Authorization and an
    # unrelated cookie continue to bypass that cache.
    assert rendered_layouts == [True, False, True, True, True, True, True]
    engine.dispose()
