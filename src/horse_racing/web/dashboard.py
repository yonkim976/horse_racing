from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import groupby

from sqlalchemy import select
from sqlalchemy.orm import Session, contains_eager, selectinload

from horse_racing.db.models import (
    OddsSnapshot,
    Race,
    Racecourse,
    RaceEntry,
    RunningTrial,
)
from horse_racing.services.entry_sheet import MEET_METADATA
from horse_racing.web.formatting import (
    adjacent_dates,
    display_race_title,
    format_age,
    format_clock,
    format_finish_position,
    format_margin,
    format_odds,
    format_race_time,
    format_rating,
    group_dates_by_month,
)


@dataclass(frozen=True, slots=True)
class RacecourseOption:
    meet_code: int
    name: str


@dataclass(frozen=True, slots=True)
class RaceRow:
    id: int
    href: str
    detail_href: str
    course_name: str
    race_number: int
    start_time: str
    distance: str
    race_label: str
    entry_count: int
    status: str
    status_label: str
    winner: str
    winning_time: str


@dataclass(frozen=True, slots=True)
class RaceGroup:
    course_name: str
    races: list[RaceRow]


@dataclass(frozen=True, slots=True)
class DateGroup:
    label: str
    dates: list[date]


@dataclass(frozen=True, slots=True)
class CalendarDateOption:
    value: str
    status: str
    has_race: bool
    has_trial: bool


@dataclass(frozen=True, slots=True)
class TrialRow:
    id: int
    detail_href: str
    course_name: str
    race_number: int
    trial_round: str
    distance: str
    entry_count: int
    pass_count: int
    fail_count: int
    status_label: str


@dataclass(frozen=True, slots=True)
class EntryRow:
    horse_id: int
    horse_number: int
    horse_name: str
    horse_meta: str
    jockey_id: int | None
    jockey_name: str
    trainer_id: int | None
    trainer_name: str
    owner_id: int | None
    owner_name: str
    carried_weight: str
    body_weight: str
    weight_delta: int | None
    rating: str
    finish_position: str
    finish_sort: int
    special_outcome: bool
    scratched: bool
    row_class: str
    finish_time: str
    win_odds: str
    place_odds: str
    margin: str


@dataclass(frozen=True, slots=True)
class RaceDetail:
    id: int
    course_name: str
    race_number: int
    date_label: str
    start_time: str
    distance: str
    grade: str
    race_name: str
    show_grade: bool
    weather_track: str
    status: str
    status_label: str
    detail_href: str
    entries: list[EntryRow]


@dataclass(frozen=True, slots=True)
class DashboardData:
    available_dates: list[date]
    date_groups: list[DateGroup]
    calendar_dates: list[CalendarDateOption]
    prev_date: date | None
    next_date: date | None
    racecourses: list[RacecourseOption]
    selected_date: date | None
    selected_meet: int | None
    filter_query: str
    race_groups: list[RaceGroup]
    races: list[RaceRow]
    trials: list[TrialRow]
    selected_race: RaceDetail | None
    selected_trial_id: int | None
    race_count: int
    trial_count: int
    entry_count: int
    trial_entry_count: int
    completed_count: int
    scheduled_count: int
    meet_count: int


def load_dashboard(
    session: Session,
    *,
    selected_date: date | None,
    selected_meet: int | None,
    selected_race_id: int | None,
    selected_trial_id: int | None = None,
) -> DashboardData:
    race_dates = list(
        session.scalars(
            select(Race.race_date_local).distinct().order_by(Race.race_date_local.desc())
        )
    )
    trial_dates = list(
        session.scalars(
            select(RunningTrial.trial_date_local)
            .distinct()
            .order_by(RunningTrial.trial_date_local.desc())
        )
    )
    race_date_set = set(race_dates)
    available_dates = sorted(race_date_set | set(trial_dates), reverse=True)
    date_status_rows = session.execute(
        select(Race.race_date_local, Race.status).distinct()
    ).all()
    statuses_by_date: dict[date, set[str]] = {}
    for race_date, status in date_status_rows:
        statuses_by_date.setdefault(race_date, set()).add(status)
    trial_date_set = set(trial_dates)
    if selected_date is None and available_dates:
        selected_date = available_dates[0]
    older_date, newer_date = adjacent_dates(available_dates, selected_date)

    course_rows = session.execute(
        select(Racecourse.kra_meet_code, Racecourse.name_ko)
        .join(Race)
        .distinct()
        .order_by(Racecourse.kra_meet_code)
    ).all()
    racecourses = [RacecourseOption(meet_code=row[0], name=row[1]) for row in course_rows]

    statement = (
        select(Race)
        .join(Race.racecourse)
        .options(
            contains_eager(Race.racecourse),
            selectinload(Race.entries).joinedload(RaceEntry.horse),
            selectinload(Race.entries).joinedload(RaceEntry.jockey),
            selectinload(Race.entries).joinedload(RaceEntry.trainer),
            selectinload(Race.entries).joinedload(RaceEntry.owner),
            selectinload(Race.entries).joinedload(RaceEntry.result),
        )
    )
    if selected_date is not None:
        statement = statement.where(Race.race_date_local == selected_date)
    if selected_meet is None:
        statement = statement.order_by(
            Racecourse.kra_meet_code, Race.race_number, Race.scheduled_at_ms.asc().nulls_last()
        )
    else:
        statement = statement.where(Racecourse.kra_meet_code == selected_meet)
        statement = statement.order_by(Race.scheduled_at_ms.asc().nulls_last(), Race.race_number)
    races = list(session.scalars(statement).unique())

    trial_statement = select(RunningTrial).options(selectinload(RunningTrial.results))
    if selected_date is not None:
        trial_statement = trial_statement.where(RunningTrial.trial_date_local == selected_date)
    if selected_meet is not None:
        trial_statement = trial_statement.where(RunningTrial.meet_code == selected_meet)
    trial_statement = trial_statement.order_by(
        RunningTrial.meet_code, RunningTrial.trial_race_number
    )
    trials = list(session.scalars(trial_statement))

    chosen_race = next((race for race in races if race.id == selected_race_id), None)
    if chosen_race is None and races:
        chosen_race = races[0]

    filter_query = _filter_query(selected_date, selected_meet)
    race_rows = [_race_row(race, filter_query) for race in races]
    race_groups = _race_groups(race_rows, grouped=selected_meet is None)
    detail = _race_detail(session, chosen_race) if chosen_race is not None else None
    trial_rows = [_trial_row(trial) for trial in trials]
    entry_count = sum(len(race.entries) for race in races)
    trial_entry_count = sum(len(trial.results) for trial in trials)
    completed_count = sum(race.status == "completed" for race in races)
    scheduled_count = sum(race.status == "scheduled" for race in races)
    meet_count = len({race.racecourse_id for race in races})

    return DashboardData(
        available_dates=available_dates,
        date_groups=[
            DateGroup(label=label, dates=items)
            for label, items in group_dates_by_month(available_dates)
        ],
        calendar_dates=[
            CalendarDateOption(
                value=available_date.isoformat(),
                status=_calendar_status(statuses_by_date.get(available_date, set())),
                has_race=available_date in race_date_set,
                has_trial=available_date in trial_date_set,
            )
            for available_date in available_dates
        ],
        prev_date=older_date,
        next_date=newer_date,
        racecourses=racecourses,
        selected_date=selected_date,
        selected_meet=selected_meet,
        filter_query=filter_query,
        race_groups=race_groups,
        races=race_rows,
        trials=trial_rows,
        selected_race=detail,
        selected_trial_id=selected_trial_id,
        race_count=len(races),
        trial_count=len(trials),
        entry_count=entry_count,
        trial_entry_count=trial_entry_count,
        completed_count=completed_count,
        scheduled_count=scheduled_count,
        meet_count=meet_count,
    )


def _calendar_status(statuses: set[str]) -> str:
    if not statuses:
        return "trial-only"
    if statuses == {"completed"}:
        return "completed"
    if statuses == {"scheduled"}:
        return "scheduled"
    return "mixed"


def _trial_row(trial: RunningTrial) -> TrialRow:
    return TrialRow(
        id=trial.id,
        detail_href=f"/running-trials/{trial.id}",
        course_name=MEET_METADATA[trial.meet_code][1],
        race_number=trial.trial_race_number,
        trial_round=f"제{trial.trial_round}회" if trial.trial_round is not None else "회차 미상",
        distance=f"{trial.distance_m:,}m",
        entry_count=len(trial.results),
        pass_count=sum(row.judgement == "합" for row in trial.results),
        fail_count=sum(row.judgement == "불" for row in trial.results),
        status_label="심사 완료",
    )


def _filter_query(selected_date: date | None, selected_meet: int | None) -> str:
    parts: list[str] = []
    if selected_date is not None:
        parts.append(f"date={selected_date.isoformat()}")
    if selected_meet is not None:
        parts.append(f"meet={selected_meet}")
    return "&".join(parts)


def _race_groups(rows: list[RaceRow], *, grouped: bool) -> list[RaceGroup]:
    if not grouped:
        return [RaceGroup(course_name="", races=rows)] if rows else []
    groups: list[RaceGroup] = []
    for course_name, items in groupby(rows, key=lambda row: row.course_name):
        groups.append(RaceGroup(course_name=course_name, races=list(items)))
    return groups


def _race_row(race: Race, filter_query: str) -> RaceRow:
    winner_entry = next(
        (
            entry
            for entry in race.entries
            if entry.result is not None and entry.result.finish_position == 1
        ),
        None,
    )
    winner = winner_entry.horse.name_ko if winner_entry is not None else "—"
    winning_time = (
        format_race_time(winner_entry.result.finish_time_ms)
        if winner_entry is not None and winner_entry.result is not None
        else "—"
    )
    status, status_label = _status(race.status)
    query = f"{filter_query}&race_id={race.id}" if filter_query else f"race_id={race.id}"
    return RaceRow(
        id=race.id,
        href=f"/?{query}",
        detail_href=f"/races/{race.id}",
        course_name=race.racecourse.name_ko,
        race_number=race.race_number,
        start_time=format_clock(race.scheduled_at_ms),
        distance=f"{race.distance_m:,}m",
        race_label=display_race_title(race.grade, race.race_name),
        entry_count=len(race.entries),
        status=status,
        status_label=status_label,
        winner=winner,
        winning_time=winning_time,
    )


def _race_detail(session: Session, race: Race) -> RaceDetail:
    odds = {
        (snapshot.bet_type, snapshot.selection_key): snapshot.odds
        for snapshot in session.scalars(
            select(OddsSnapshot).where(
                OddsSnapshot.race_id == race.id,
                OddsSnapshot.bet_type.in_(("WIN", "PLC")),
            )
        )
    }
    entries = [_entry_row(entry, odds) for entry in race.entries]
    entries.sort(key=lambda entry: (entry.finish_sort, entry.horse_number))
    condition_parts = [part for part in (race.weather, race.track_condition) if part]
    if race.track_moisture_percent is not None:
        condition_parts.append(f"함수율 {race.track_moisture_percent:g}%")
    status, status_label = _status(race.status)
    title = display_race_title(race.grade, race.race_name)
    grade = race.grade or "등급 정보 없음"
    return RaceDetail(
        id=race.id,
        course_name=race.racecourse.name_ko,
        race_number=race.race_number,
        date_label=race.race_date_local.strftime("%Y.%m.%d"),
        start_time=format_clock(race.scheduled_at_ms),
        distance=f"{race.distance_m:,}m",
        grade=grade,
        race_name=title,
        show_grade=bool(race.grade) and grade != title,
        weather_track=" · ".join(condition_parts) or "주로 정보 없음",
        status=status,
        status_label=status_label,
        detail_href=f"/races/{race.id}",
        entries=entries,
    )


def _entry_row(
    entry: RaceEntry,
    odds: dict[tuple[str, str], float],
) -> EntryRow:
    result = entry.result
    finish_position = result.finish_position if result is not None else None
    label, sort_key, special = format_finish_position(
        finish_position, scratched=entry.scratched
    )
    horse_meta = " · ".join(
        part
        for part in (
            format_age(entry.horse.birth_date, entry.race.race_date_local),
            entry.horse.origin_country,
            entry.horse.sex,
        )
        if part and part != "—"
    )
    body_weight = "—"
    if entry.body_weight_kg is not None:
        change = entry.body_weight_change_kg
        change_label = f" ({change:+d})" if change is not None else ""
        body_weight = f"{entry.body_weight_kg}kg{change_label}"
    classes = []
    if special or entry.scratched:
        classes.append("non-finisher")
    elif 1 <= sort_key <= 3:
        classes.append("placed")
        classes.append(f"placed-{sort_key}")
    selection_key = str(entry.horse_number)
    return EntryRow(
        horse_id=entry.horse_id,
        horse_number=entry.horse_number,
        horse_name=entry.horse.name_ko,
        horse_meta=horse_meta or "정보 없음",
        jockey_id=entry.jockey_id,
        jockey_name=entry.jockey.name_ko if entry.jockey else "—",
        trainer_id=entry.trainer_id,
        trainer_name=entry.trainer.name_ko if entry.trainer else "—",
        owner_id=entry.owner_id,
        owner_name=entry.owner.name_ko if entry.owner else "—",
        carried_weight=(
            f"{entry.carried_weight_kg:g}kg" if entry.carried_weight_kg is not None else "—"
        ),
        body_weight=body_weight,
        weight_delta=entry.body_weight_change_kg,
        rating=format_rating(entry.rating),
        finish_position=label,
        finish_sort=sort_key,
        special_outcome=special,
        scratched=entry.scratched,
        row_class=" ".join(classes),
        finish_time=format_race_time(result.finish_time_ms if result else None),
        win_odds=format_odds(odds.get(("WIN", selection_key))),
        place_odds=format_odds(odds.get(("PLC", selection_key))),
        margin=format_margin(result.margin_text if result else None),
    )


def _status(status: str) -> tuple[str, str]:
    if status == "completed":
        return "completed", "종료"
    if status == "cancelled":
        return "cancelled", "취소"
    return "scheduled", "예정"
