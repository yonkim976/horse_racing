"""Analysis includes source evidence while excluding selected-day information."""

import json
from dataclasses import asdict
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from horse_racing.db.base import Base
from horse_racing.db.models import (
    Horse,
    HorseStartTraining,
    HorseTraining,
    Jockey,
    Race,
    Racecourse,
    RaceEntry,
    RaceResult,
    RaceSectionResult,
    RunningTrial,
    RunningTrialResult,
)
from horse_racing.web import race_analysis
from horse_racing.web.race_analysis import load_race_analysis_page


@pytest.fixture
def session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(race_analysis, "today_seoul", lambda: date(2026, 9, 18))
    with Session(engine) as db:
        yield db
    engine.dispose()


def horse(session, number=1):
    row = Horse(kra_horse_id=f"test-horse-{number}", name_ko=f"검증마{number}")
    session.add(row)
    session.flush()
    return row


def course(session, meet=2):
    row = Racecourse(kra_meet_code=meet, code=f"COURSE_{meet}", name_ko=f"경마장{meet}")
    session.add(row)
    session.flush()
    return row


def race(session, track, day, number=1, status="completed", distance=1200):
    row = Race(
        racecourse_id=track.id,
        race_date_local=day,
        race_number=number,
        status=status,
        distance_m=distance,
        field_size=10,
    )
    session.add(row)
    session.flush()
    return row


def entry(session, event_row, runner, number=1, finish=None, time_ms=80000, jockey=None):
    row = RaceEntry(
        race_id=event_row.id,
        horse_id=runner.id,
        horse_number=number,
        gate_number=number,
        jockey_id=jockey.id if jockey else None,
    )
    session.add(row)
    session.flush()
    if finish is not None:
        session.add(
            RaceResult(race_entry_id=row.id, finish_position=finish, finish_time_ms=time_ms)
        )
        session.flush()
    return row


def section(session, runner, code, milliseconds, basis="cumulative", position=None):
    session.add(
        RaceSectionResult(
            race_entry_id=runner.id,
            section_code=code,
            elapsed_time_ms=milliseconds,
            time_basis=basis,
            source_kind="api4_3" if basis else None,
            position=position,
        )
    )
    session.flush()


def test_default_selects_today_including_completed_and_explicit_date_selects_whole_day(session):
    track, runner = course(session), horse(session)
    today = race(session, track, date(2026, 9, 18), status="completed")
    tomorrow = race(session, track, date(2026, 9, 19), status="scheduled")
    second_today = race(session, track, date(2026, 9, 18), number=2, status="scheduled")
    for item in [today, tomorrow, second_today]:
        entry(session, item, runner)
    page = load_race_analysis_page(session)
    assert page.selected_race.id == today.id
    assert [item.id for item in page.races] == [today.id, second_today.id]
    assert page.selected_date == "2026-09-18"
    assert page.selection_note == ""
    future = load_race_analysis_page(session, race_date=date(2026, 9, 19))
    assert future.selected_race.id == tomorrow.id
    empty = load_race_analysis_page(session, race_date=date(2026, 9, 20))
    assert empty.selected_race is None
    assert "공개된 출전표가 없습니다" in empty.selection_note


def test_no_today_uses_nearest_published_date_and_explains_fallback(session):
    track, runner = course(session), horse(session)
    previous = race(session, track, date(2026, 9, 17))
    future = race(session, track, date(2026, 9, 21), status="scheduled")
    entry(session, previous, runner)
    entry(session, future, runner)
    page = load_race_analysis_page(session)
    assert page.selected_race.id == previous.id
    assert "가장 가까운 공개 경주일 2026-09-17" in page.selection_note


def test_history_preserves_abnormal_finishes_but_excludes_them_from_metrics(session):
    track, runner = course(session), horse(session)
    target = race(session, track, date(2026, 9, 18))
    entry(session, target, runner, finish=1, time_ms=50000)
    normal = race(session, track, date(2026, 9, 1))
    normal_entry = entry(session, normal, runner, finish=3, time_ms=80000)
    section(session, normal_entry, "S1F", 14000, position=2)
    section(session, normal_entry, "G3F", 40000, basis="closing")
    dnf = race(session, track, date(2026, 9, 12))
    dnf_entry = entry(session, dnf, runner, finish=93, time_ms=90000)
    section(session, dnf_entry, "S1F", 11000, position=1)
    future = race(session, track, date(2026, 9, 20))
    entry(session, future, runner, finish=1, time_ms=40000)
    selected = load_race_analysis_page(session, race_id=target.id).runners[0]
    assert [item.date for item in selected.history] == ["2026-09-12", "2026-09-01"]
    assert selected.history[0].finish == "주행중지"
    assert selected.history[0].time == "—"
    assert selected.history[0].section_details["S1F"]["time_ms"] is None
    assert selected.history_total == 2
    assert selected.metrics["normal_starts"] == 1
    assert selected.metrics["abnormal_starts"] == 1
    assert selected.metrics["same_distance_best_ms"] == 80000
    assert selected.metrics["avg_s1f_ms"] == 14000
    assert selected.style == "자료 부족"
    assert selected.history[0].days_since_previous == 11
    assert selected.history[1].video_url.endswith("vod_type=r")


def test_source_aware_closing_times_and_unknown_source_are_not_guessed(session):
    track, runner = course(session, meet=1), horse(session)
    target = race(session, track, date(2026, 9, 18))
    entry(session, target, runner)
    first = entry(session, race(session, track, date(2026, 9, 1)), runner, finish=2, time_ms=80000)
    section(session, first, "G3F", 42000, basis="cumulative")
    section(session, first, "G1F", 66000, basis="cumulative")
    section(session, first, "S1F", 14000, position=1)
    second = entry(session, race(session, track, date(2026, 9, 8)), runner, finish=1, time_ms=78000)
    section(session, second, "G3F", 36000, basis="closing")
    section(session, second, "G1F", 14000, basis=None)
    section(session, second, "S1F", 13500, position=2)
    result = load_race_analysis_page(session, race_id=target.id).runners[0]
    assert result.history[1].section_details["G3F"]["time_ms"] == 38000
    assert result.history[1].section_details["G1F"]["time_ms"] == 14000
    assert result.history[0].section_details["G3F"]["time_ms"] == 36000
    assert result.history[0].section_details["G1F"]["time_ms"] is None
    assert "기준 미확인" in result.history[0].sections["G1F"]
    assert result.metrics["avg_g3f_ms"] == 37000
    assert result.metrics["avg_g1f_samples"] == 1
    assert result.style == "선행"
    assert result.early_sample == 2


def test_jeju_210m_early_times_are_not_averaged_with_200m(session):
    track, runner = course(session), horse(session)
    target = race(session, track, date(2026, 9, 18), distance=1110)
    entry(session, target, runner)
    for day, distance, ms in [(1, 1110, 17000), (8, 1000, 12000)]:
        old = entry(
            session, race(session, track, date(2026, 9, day), distance=distance), runner, finish=2
        )
        section(session, old, "S1F", ms, position=2)
    result = load_race_analysis_page(session, race_id=target.id).runners[0]
    assert result.metrics["avg_s1f_ms"] == 17000
    assert result.metrics["avg_s1f_samples"] == 1
    assert result.history[1].section_details["S1F"]["label"] == "초반 210m"


def test_debutant_gets_prior_trials_and_training_but_no_target_day_evidence(session):
    track, runner = course(session), horse(session)
    target = race(session, track, date(2026, 9, 18))
    entry(session, target, runner)
    for day in [date(2026, 9, 16), date(2026, 9, 18), date(2026, 9, 19)]:
        trial = RunningTrial(
            meet_code=2, trial_date_local=day, trial_race_number=1, distance_m=800, observed_at_ms=1
        )
        session.add(trial)
        session.flush()
        session.add(
            RunningTrialResult(
                running_trial_id=trial.id,
                horse_id=runner.id,
                horse_number=1,
                horse_name_raw=runner.name_ko,
                finish_position=2,
                finish_time_ms=65000,
                judgement="합",
                s1f_ms=17000,
                g3f_ms=48000,
                g1f_ms=16000,
                observed_at_ms=1,
            )
        )
    for day in [date(2026, 8, 20), date(2026, 8, 21), date(2026, 9, 17), date(2026, 9, 18)]:
        session.add(
            HorseTraining(
                horse_id=runner.id,
                meet_code=2,
                training_date_local=day,
                duration_seconds=600,
                canter_count=2,
                gallop_count=1,
                observed_at_ms=1,
            )
        )
        session.add(
            HorseStartTraining(
                horse_id=runner.id, meet_code=2, training_date_local=day, observed_at_ms=1
            )
        )
    session.flush()
    page = load_race_analysis_page(session, race_id=target.id)
    result = page.runners[0]
    assert result.history == []
    assert len(result.trials) == 1
    assert result.trials[0].date == "2026-09-16"
    assert result.trials[0].judgement == "합격"
    assert result.trials[0].video_url.endswith("vod_type=t")
    assert result.trials[0].section_details["G3F"]["time_ms"] == 48000
    assert result.training_summary["sessions"] == 2
    assert result.training_summary["minutes"] == 20.0
    assert result.training_summary["start_sessions"] == 2
    assert page.pace["runners"][0]["early_normalized"] is None
    json.dumps(asdict(page), ensure_ascii=False, allow_nan=False)


def test_jockey_and_horse_combination_use_only_prior_365_days(session):
    track, runner, other = course(session), horse(session), horse(session, 2)
    jockey = Jockey(kra_jockey_id="test-jockey", name_ko="검증기수")
    session.add(jockey)
    session.flush()
    target_day = date(2026, 9, 18)
    target = race(session, track, target_day)
    entry(session, target, runner, finish=1, jockey=jockey)
    for day, horse_row, finish in [
        (target_day - timedelta(days=365), runner, 3),
        (target_day - timedelta(days=1), other, 1),
        (target_day - timedelta(days=366), runner, 1),
        (target_day - timedelta(days=5), runner, 93),
    ]:
        entry(session, race(session, track, day), horse_row, finish=finish, jockey=jockey)
    result = load_race_analysis_page(session, race_id=target.id).runners[0]
    assert result.jockey_stats["starts"] == 2
    assert result.jockey_stats["wins"] == 1
    assert result.jockey_stats["top3_rate"] == 100
    assert result.combination_stats["starts"] == 1
    assert result.combination_stats["wins"] == 0


def test_history_limit_is_applied_per_horse_in_sql_and_queries_stay_bounded(session):
    track = course(session)
    runners = [horse(session, number) for number in range(1, 6)]
    target = race(session, track, date(2026, 9, 18))
    for index, runner in enumerate(runners, 1):
        entry(session, target, runner, number=index)
    for offset in range(1, 66):
        old = race(session, track, target.race_date_local - timedelta(days=offset))
        for index, runner in enumerate(runners, 1):
            entry(
                session,
                old,
                runner,
                number=index,
                finish=index,
                time_ms=60000 if offset == 65 else 80000,
            )
    statements = []

    def count_query(_conn, _cursor, statement, _params, _ctx, _many):
        statements.append(statement)

    event.listen(session.bind, "before_cursor_execute", count_query)
    try:
        page = load_race_analysis_page(session, race_id=target.id)
    finally:
        event.remove(session.bind, "before_cursor_execute", count_query)
    assert len(statements) <= 16
    assert all(len(row.history) == 12 and row.history_total == 65 for row in page.runners)
    assert all(row.same_distance_starts == 65 for row in page.runners)
    assert all(row.metrics["same_distance_best_ms"] == 60000 for row in page.runners)
    expanded = load_race_analysis_page(session, race_id=target.id, history_limit=60)
    assert all(len(row.history) == 60 and row.history_total == 65 for row in expanded.runners)
    invalid = load_race_analysis_page(session, race_id=target.id, history_limit=100000)
    assert invalid.history_limit == 12


def archive_record(day, *, number=1, archive_id=500, milliseconds=80000):
    return {
        "archive_entry_id": archive_id,
        "date": day.isoformat(),
        "meet": 2,
        "event_number": number,
        "horse_number": 7,
        "distance": 1200,
        "grade": "제5등급",
        "weather": None,
        "track_condition": None,
        "track_moisture_percent": None,
        "field_size": 10,
        "finish_position": 2,
        "time_ms": milliseconds,
        "record_status": "normal_completed",
        "time_analysis_eligible": True,
        "source_label": "검증된 제주 공식 과거자료",
        "sections": {
            "G3F": {
                "raw_ms": 40000,
                "elapsed_ms": 40000,
                "time_basis": "closing",
                "source_kind": "race_result",
            }
        },
        "judgement": "합",
        "jockey": "기수",
        "passing_order": None,
    }


def test_archive_uses_natural_identity_for_merge_and_only_repairs_matching_observations(
    session,
    monkeypatch,
):
    track, runner = course(session), horse(session)
    runner.kra_horse_id = "0000001"
    target = race(session, track, date(2026, 9, 18))
    entry(session, target, runner)
    evidence = []
    for offset in range(1, 14):
        day = target.race_date_local - timedelta(days=offset)
        old = entry(session, race(session, track, day), runner, finish=2)
        section(session, old, "G3F", 40000, basis=None)
        evidence.append(archive_record(day, archive_id=offset))
    mismatch = evidence[0]
    mismatch["sections"]["G3F"]["raw_ms"] = 41000
    extra = archive_record(date(2014, 1, 1), archive_id=600)
    future = archive_record(date(2026, 9, 19), archive_id=700)
    evidence.extend([extra, future])
    monkeypatch.setattr(
        race_analysis,
        "load_verified_archive",
        lambda *args, **kwargs: {
            "0000001": {
                "races": evidence,
                "trials": [],
                "races_truncated": False,
                "trials_truncated": False,
            },
        },
    )
    page = load_race_analysis_page(session, race_id=target.id)
    selected = page.runners[0]
    # The 13th operational race is outside the display window, yet not added twice.
    assert selected.history_total == 14
    assert len(selected.history) == 12
    assert selected.history[0].section_details["G3F"]["time_ms"] is None
    assert selected.history[1].section_details["G3F"]["time_ms"] == 40000
    assert page.coverage["archive_races_added"] == 1
    expanded = load_race_analysis_page(session, race_id=target.id, history_limit=60).runners[0]
    assert len(expanded.history) == 14
    assert expanded.history[-1].race_id is None
    assert expanded.history[-1].entry_id == -600
    assert expanded.history[-1].video_url.endswith("vod_type=r")
    assert expanded.history[-1].source_label == "검증된 제주 공식 과거자료"
    assert expanded.history[-1].horse_number == 7
    assert all(item.date < "2026-09-18" for item in expanded.history)


def test_archive_supplements_unlinked_old_trials_but_preserves_operational_record(
    session, monkeypatch
):
    track, runner = course(session), horse(session)
    runner.kra_horse_id = "0000001"
    target = race(session, track, date(2026, 9, 18))
    entry(session, target, runner)
    trial = RunningTrial(
        meet_code=2,
        trial_date_local=date(2026, 9, 16),
        trial_race_number=1,
        distance_m=800,
        observed_at_ms=1,
    )
    session.add(trial)
    session.flush()
    session.add(
        RunningTrialResult(
            running_trial_id=trial.id,
            horse_id=runner.id,
            horse_number=1,
            horse_name_raw=runner.name_ko,
            finish_position=2,
            finish_time_ms=65000,
            judgement="연",
            observed_at_ms=1,
        )
    )
    session.flush()
    monkeypatch.setattr(
        race_analysis,
        "load_verified_archive",
        lambda *args, **kwargs: {
            "0000001": {
                "races": [],
                "trials": [archive_record(date(2026, 9, 16)), archive_record(date(2024, 5, 1))],
            },
        },
    )
    selected = load_race_analysis_page(session, race_id=target.id).runners[0]
    assert selected.trial_total == 2
    assert len(selected.trials) == 2
    assert selected.trials[0].id == trial.id
    assert selected.trials[0].finish_time_ms == 65000
    assert selected.trials[0].judgement == "연습"
    assert selected.trials[0].horse_number == 1
    assert selected.trials[1].id is None
    assert selected.trials[1].horse_number == 7
    assert selected.trials[1].video_url.endswith("vod_type=t")


def test_past_horse_number_is_the_actual_recorded_number_not_current_number_or_gate(session):
    track, runner = course(session), horse(session)
    target = race(session, track, date(2026, 9, 18))
    entry(session, target, runner, number=1)
    old = entry(session, race(session, track, date(2026, 9, 1)), runner, number=8, finish=2)
    old.gate_number = 3
    trial = RunningTrial(
        meet_code=2,
        trial_date_local=date(2026, 9, 10),
        trial_race_number=2,
        distance_m=800,
        observed_at_ms=1,
    )
    session.add(trial)
    session.flush()
    session.add(
        RunningTrialResult(
            running_trial_id=trial.id,
            horse_id=runner.id,
            horse_number=5,
            horse_name_raw=runner.name_ko,
            finish_position=2,
            finish_time_ms=65000,
            judgement="합",
            observed_at_ms=1,
        )
    )
    session.flush()
    result = load_race_analysis_page(session, race_id=target.id).runners[0]
    assert result.number == 1
    assert result.history[0].horse_number == 8
    assert result.history[0].gate == "3"
    assert result.trials[0].horse_number == 5
    assert result.trials[0].number == 2


def test_archive_missing_horse_number_stays_unknown():
    record = archive_record(date(2024, 1, 1))
    record.pop("horse_number")
    assert race_analysis._archive_start(record).horse_number is None
    assert race_analysis._archive_trial(record).horse_number is None


def test_pace_stages_use_distinct_observed_checkpoint_ranks_and_prefer_fourth_corner(session):
    track, runner = course(session), horse(session)
    target = race(session, track, date(2026, 9, 18))
    entry(session, target, runner)
    first = entry(session, race(session, track, date(2026, 9, 1)), runner, finish=1)
    section(session, first, "S1F", 14000, position=1)
    section(session, first, "3C", 39000, position=2)
    section(session, first, "4C", 53000, position=7)
    section(session, first, "G1F", 67000, position=5)
    second = entry(session, race(session, track, date(2026, 9, 8)), runner, finish=1)
    section(session, second, "S1F", 15000, position=3)
    section(session, second, "3C", 40000, position=4)
    section(session, second, "G1F", 67000, position=1)
    cancelled = entry(session, race(session, track, date(2026, 9, 12)), runner, finish=93)
    for code in ("S1F", "4C", "G1F"):
        section(session, cancelled, code, 12000, position=10)
    page = load_race_analysis_page(session, race_id=target.id)
    pace = page.pace["runners"][0]
    stages = pace["stages"]
    assert pace["early_sample"] == 2
    assert stages["early"]["normalized"] == 0.1111
    assert stages["middle"]["normalized"] == 0.5
    assert stages["late"]["normalized"] == 0.2222
    assert stages["middle"]["sources"] == {"3C": 1, "4C": 1}
    assert stages["late"]["sources"] == {"G1F": 2}
    assert all(stage["samples"] == 2 for stage in stages.values())
    assert "결승 200m 전" in stages["late"]["label"]
    assert page.runners[0].pace_stages == stages


def test_busan_middle_uses_g3f_checkpoint_and_missing_late_stays_unknown(session):
    track, runner = course(session, meet=3), horse(session)
    target = race(session, track, date(2026, 9, 18))
    entry(session, target, runner)
    old = entry(session, race(session, track, date(2026, 9, 10)), runner, finish=1)
    section(session, old, "S1F", None, basis=None, position=2)
    section(session, old, "G3F", None, basis=None, position=7)
    stages = load_race_analysis_page(session, race_id=target.id).pace["runners"][0]["stages"]
    assert stages["middle"]["normalized"] == 0.6667
    assert stages["middle"]["sources"] == {"G3F": 1}
    assert "G3F(결승 600m 전)" in stages["middle"]["label"]
    # The known winning finish cannot stand in for an absent G1F observation.
    assert stages["late"]["normalized"] is None
    assert stages["late"]["samples"] == 0


@pytest.mark.parametrize("meet,distance", [(1, 1000), (2, 800)])
def test_same_point_s1f_and_third_corner_are_not_two_pace_stages(session, meet, distance):
    track, runner = course(session, meet=meet), horse(session)
    target = race(session, track, date(2026, 9, 18), distance=distance)
    entry(session, target, runner)
    old = entry(
        session, race(session, track, date(2026, 9, 10), distance=distance), runner, finish=1
    )
    section(session, old, "S1F", 14000, position=2)
    section(session, old, "3C", 14000, position=2)
    section(session, old, "G1F", 60000, position=5)
    stages = load_race_analysis_page(session, race_id=target.id).pace["runners"][0]["stages"]
    assert stages["early"]["samples"] == 1
    assert stages["middle"]["samples"] == 0
    assert stages["middle"]["normalized"] is None
    assert stages["late"]["samples"] == 1


def test_pace_stages_are_limited_to_six_recent_normal_finishes_without_old_fallback(session):
    track, runner = course(session), horse(session)
    target = race(session, track, date(2026, 9, 18))
    entry(session, target, runner)
    for offset in range(1, 8):
        old = entry(
            session,
            race(session, track, target.race_date_local - timedelta(days=offset)),
            runner,
            finish=1,
        )
        if offset == 7:
            section(session, old, "S1F", 14000, position=1)
            section(session, old, "4C", 50000, position=1)
            section(session, old, "G1F", 60000, position=1)
    stages = load_race_analysis_page(session, race_id=target.id).pace["runners"][0]["stages"]
    assert all(stage["normalized"] is None and stage["samples"] == 0 for stage in stages.values())
    assert all("최근 6회" in stage["label"] for stage in stages.values())
