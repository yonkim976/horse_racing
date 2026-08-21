from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from horse_racing.db.models import OddsSnapshot, Race, Racecourse, RaceEntry

SEOUL = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True, slots=True)
class RacecourseOption:
    meet_code: int
    name: str


@dataclass(frozen=True, slots=True)
class RaceRow:
    id: int
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
class EntryRow:
    horse_number: int
    horse_name: str
    horse_meta: str
    jockey_name: str
    trainer_name: str
    carried_weight: str
    body_weight: str
    rating: str
    finish_position: str
    finish_sort: int
    finish_time: str
    win_odds: str
    place_odds: str
    prize_money: str


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
    weather_track: str
    status: str
    status_label: str
    entries: list[EntryRow]


@dataclass(frozen=True, slots=True)
class DashboardData:
    available_dates: list[date]
    racecourses: list[RacecourseOption]
    selected_date: date | None
    selected_meet: int | None
    races: list[RaceRow]
    selected_race: RaceDetail | None
    race_count: int
    entry_count: int
    completed_count: int
    result_count: int


def load_dashboard(
    session: Session,
    *,
    selected_date: date | None,
    selected_meet: int | None,
    selected_race_id: int | None,
) -> DashboardData:
    available_dates = list(
        session.scalars(
            select(Race.race_date_local).distinct().order_by(Race.race_date_local.desc())
        )
    )
    if selected_date is None and available_dates:
        selected_date = available_dates[0]

    course_rows = session.execute(
        select(Racecourse.kra_meet_code, Racecourse.name_ko)
        .join(Race)
        .distinct()
        .order_by(Racecourse.kra_meet_code)
    ).all()
    racecourses = [RacecourseOption(meet_code=row[0], name=row[1]) for row in course_rows]

    statement = (
        select(Race)
        .options(
            joinedload(Race.racecourse),
            selectinload(Race.entries).joinedload(RaceEntry.horse),
            selectinload(Race.entries).joinedload(RaceEntry.jockey),
            selectinload(Race.entries).joinedload(RaceEntry.trainer),
            selectinload(Race.entries).joinedload(RaceEntry.result),
        )
        .order_by(Race.racecourse_id, Race.race_number)
    )
    if selected_date is not None:
        statement = statement.where(Race.race_date_local == selected_date)
    if selected_meet is not None:
        statement = statement.join(Race.racecourse).where(Racecourse.kra_meet_code == selected_meet)
    races = list(session.scalars(statement).unique())

    chosen_race = next((race for race in races if race.id == selected_race_id), None)
    if chosen_race is None and races:
        chosen_race = races[0]

    race_rows = [_race_row(race) for race in races]
    detail = _race_detail(session, chosen_race) if chosen_race is not None else None
    entry_count = sum(len(race.entries) for race in races)
    result_count = sum(1 for race in races for entry in race.entries if entry.result is not None)
    completed_count = sum(race.status == "completed" for race in races)

    return DashboardData(
        available_dates=available_dates,
        racecourses=racecourses,
        selected_date=selected_date,
        selected_meet=selected_meet,
        races=race_rows,
        selected_race=detail,
        race_count=len(races),
        entry_count=entry_count,
        completed_count=completed_count,
        result_count=result_count,
    )


def _race_row(race: Race) -> RaceRow:
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
        _format_race_time(winner_entry.result.finish_time_ms)
        if winner_entry is not None and winner_entry.result is not None
        else "—"
    )
    status, status_label = _status(race.status)
    return RaceRow(
        id=race.id,
        course_name=race.racecourse.name_ko,
        race_number=race.race_number,
        start_time=_format_clock(race.scheduled_at_ms),
        distance=f"{race.distance_m:,}m",
        race_label=race.grade or race.race_name or "일반경주",
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
    return RaceDetail(
        id=race.id,
        course_name=race.racecourse.name_ko,
        race_number=race.race_number,
        date_label=race.race_date_local.strftime("%Y.%m.%d"),
        start_time=_format_clock(race.scheduled_at_ms),
        distance=f"{race.distance_m:,}m",
        grade=race.grade or "등급 정보 없음",
        race_name=race.race_name or "일반경주",
        weather_track=" · ".join(condition_parts) or "주로 정보 없음",
        status=status,
        status_label=status_label,
        entries=entries,
    )


def _entry_row(
    entry: RaceEntry,
    odds: dict[tuple[str, str], float],
) -> EntryRow:
    result = entry.result
    finish_position = result.finish_position if result is not None else None
    horse_meta = " · ".join(part for part in (entry.horse.origin_country, entry.horse.sex) if part)
    body_weight = "—"
    if entry.body_weight_kg is not None:
        change = entry.body_weight_change_kg
        change_label = f" ({change:+d})" if change is not None else ""
        body_weight = f"{entry.body_weight_kg}kg{change_label}"
    selection_key = str(entry.horse_number)
    return EntryRow(
        horse_number=entry.horse_number,
        horse_name=entry.horse.name_ko,
        horse_meta=horse_meta or "정보 없음",
        jockey_name=entry.jockey.name_ko if entry.jockey else "—",
        trainer_name=entry.trainer.name_ko if entry.trainer else "—",
        carried_weight=(
            f"{entry.carried_weight_kg:g}kg" if entry.carried_weight_kg is not None else "—"
        ),
        body_weight=body_weight,
        rating=f"{entry.rating:g}" if entry.rating is not None else "—",
        finish_position=f"{finish_position}위" if finish_position is not None else "—",
        finish_sort=finish_position if finish_position is not None else 999,
        finish_time=_format_race_time(result.finish_time_ms if result else None),
        win_odds=_format_odds(odds.get(("WIN", selection_key))),
        place_odds=_format_odds(odds.get(("PLC", selection_key))),
        prize_money=_format_money(result.prize_money_krw if result else None),
    )


def _status(status: str) -> tuple[str, str]:
    if status == "completed":
        return "completed", "종료"
    if status == "cancelled":
        return "cancelled", "취소"
    return "scheduled", "예정"


def _format_clock(epoch_ms: int | None) -> str:
    if epoch_ms is None:
        return "미정"
    return datetime.fromtimestamp(epoch_ms / 1000, tz=SEOUL).strftime("%H:%M")


def _format_race_time(milliseconds: int | None) -> str:
    if milliseconds is None:
        return "—"
    minutes, remaining = divmod(milliseconds, 60_000)
    seconds = remaining / 1000
    return f"{minutes}:{seconds:04.1f}" if minutes else f"{seconds:.1f}초"


def _format_odds(value: float | None) -> str:
    return f"{value:g}배" if value is not None else "—"


def _format_money(value: int | None) -> str:
    return f"{value:,}원" if value is not None else "—"
