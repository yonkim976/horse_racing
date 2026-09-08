from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import groupby
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from horse_racing.db.models import (
    EntryEquipment,
    Horse,
    JockeyChange,
    OddsSnapshot,
    Race,
    RaceEntry,
    RaceScratch,
    RaceStewardReport,
)
from horse_racing.parsers.race_section import MEET_SECTION_SPECS
from horse_racing.web.dashboard import EntryRow, _entry_row, _status
from horse_racing.web.formatting import (
    display_race_title,
    dividend_label,
    format_clock,
    format_finish_position,
    format_odds,
    format_race_time,
)
from horse_racing.web.racecourse import RacecourseMapView, build_racecourse_map

SECTION_LABELS: dict[str, str] = {
    "S1F": "S1F",
    "1C": "1C",
    "2C": "2C",
    "3C": "3C",
    "4C": "4C",
    "G8F": "G8F",
    "G6F": "G6F",
    "G4F": "G4F",
    "G3F": "G3F",
    "G2F": "G2F",
    "G1F": "G1F",
}

FINISH_LABEL = "FIN"


@dataclass(frozen=True, slots=True)
class SectionColumn:
    code: str
    label: str
    aliases: tuple[str, ...] = ()
    location: str = ""
    segment_label: str = ""
    segment_distance: str = ""

    @property
    def codes(self) -> tuple[str, ...]:
        return (self.code, *self.aliases)


@dataclass(frozen=True, slots=True)
class SectionCell:
    position: str
    segment_time: str
    cumulative_time: str
    sort_position: int
    position_inferred: bool = False


@dataclass(frozen=True, slots=True)
class SectionEntryRow:
    horse_id: int
    horse_number: int
    horse_name: str
    finish_position: str
    finish_sort: int
    cells: list[SectionCell]
    closing_600: str = "—"
    closing_200: str = "—"


@dataclass(frozen=True, slots=True)
class RaceJockeyChangeRow:
    horse_number: int
    horse_name: str
    horse_id: int | None
    before_name: str
    after_name: str
    reason: str


@dataclass(frozen=True, slots=True)
class RaceScratchRow:
    horse_number: str
    horse_name: str
    horse_id: int | None
    reason: str


@dataclass(frozen=True, slots=True)
class RaceEquipmentRow:
    horse_number: str
    horse_name: str
    horse_id: int | None
    equipment: str
    bleeding: str
    illness: str


@dataclass(frozen=True, slots=True)
class StewardReportView:
    weather: str
    members: str
    judgement: str
    additional_judgement: str
    jockey_change_note: str


@dataclass(frozen=True, slots=True)
class DividendRow:
    selection: str
    odds: str


@dataclass(frozen=True, slots=True)
class DividendPool:
    bet_type: str
    label: str
    rows: list[DividendRow]


@dataclass(frozen=True, slots=True)
class RacePageData:
    id: int
    course_name: str
    meet_code: int
    race_number: int
    date_label: str
    date_iso: str
    start_time: str
    distance_m: int
    distance: str
    grade: str
    race_name: str
    show_grade: bool
    weather_track: str
    status: str
    status_label: str
    racecourse_map: RacecourseMapView | None
    entries: list[EntryRow]
    section_columns: list[SectionColumn]
    section_rows: list[SectionEntryRow]
    has_sections: bool
    chart_data: dict[str, object]
    back_query: str
    prev_race_id: int | None
    next_race_id: int | None
    dividends: list[DividendPool]
    jockey_changes: list[RaceJockeyChangeRow]
    scratches: list[RaceScratchRow]
    equipment: list[RaceEquipmentRow]
    steward_report: StewardReportView | None


def load_race_page(session: Session, *, race_id: int) -> RacePageData | None:
    race = session.scalar(
        select(Race)
        .where(Race.id == race_id)
        .options(
            joinedload(Race.racecourse),
            selectinload(Race.entries).joinedload(RaceEntry.horse),
            selectinload(Race.entries).joinedload(RaceEntry.jockey),
            selectinload(Race.entries).joinedload(RaceEntry.trainer),
            selectinload(Race.entries).joinedload(RaceEntry.owner),
            selectinload(Race.entries).joinedload(RaceEntry.result),
            selectinload(Race.entries).selectinload(RaceEntry.section_results),
        )
    )
    if race is None:
        return None

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

    section_columns = _section_columns(race)
    section_rows = _section_rows(
        race.entries,
        section_columns,
        meet_code=race.racecourse.kra_meet_code,
    )
    chart_data = build_section_chart_data(section_columns, section_rows)
    condition_parts = [part for part in (race.weather, race.track_condition) if part]
    if race.track_moisture_percent is not None:
        condition_parts.append(f"함수율 {race.track_moisture_percent:g}%")
    status, status_label = _status(race.status)
    meet_code = race.racecourse.kra_meet_code
    back_query = f"date={race.race_date_local.isoformat()}&meet={meet_code}&race_id={race.id}"
    title = display_race_title(race.grade, race.race_name)
    grade = race.grade or "등급 정보 없음"
    prev_race_id, next_race_id = _neighbor_race_ids(session, race)

    return RacePageData(
        id=race.id,
        course_name=race.racecourse.name_ko,
        meet_code=meet_code,
        race_number=race.race_number,
        date_label=race.race_date_local.strftime("%Y.%m.%d"),
        date_iso=race.race_date_local.isoformat(),
        start_time=format_clock(race.scheduled_at_ms),
        distance_m=race.distance_m,
        distance=f"{race.distance_m:,}m",
        grade=grade,
        race_name=title,
        show_grade=bool(race.grade) and grade != title,
        weather_track=" · ".join(condition_parts) or "주로 정보 없음",
        status=status,
        status_label=status_label,
        racecourse_map=build_racecourse_map(
            meet_code=meet_code,
            distance_m=race.distance_m,
        ),
        entries=entries,
        section_columns=section_columns,
        section_rows=section_rows,
        has_sections=bool(section_columns),
        chart_data=chart_data,
        back_query=back_query,
        prev_race_id=prev_race_id,
        next_race_id=next_race_id,
        dividends=_load_dividends(session, race.id),
        jockey_changes=_load_race_jockey_changes(
            session,
            meet_code=meet_code,
            race_date=race.race_date_local,
            race_number=race.race_number,
        ),
        scratches=_load_race_scratches(
            session,
            meet_code=meet_code,
            race_date=race.race_date_local,
            race_number=race.race_number,
        ),
        equipment=_load_race_equipment(
            session,
            meet_code=meet_code,
            race_date=race.race_date_local,
            race_number=race.race_number,
        ),
        steward_report=_load_steward_report(
            session,
            meet_code=meet_code,
            race_date=race.race_date_local,
            race_number=race.race_number,
        ),
    )


def _neighbor_race_ids(session: Session, race: Race) -> tuple[int | None, int | None]:
    rows = list(
        session.execute(
            select(Race.id, Race.race_number)
            .where(
                Race.racecourse_id == race.racecourse_id,
                Race.race_date_local == race.race_date_local,
            )
            .order_by(Race.race_number)
        )
    )
    previous_id: int | None = None
    next_id: int | None = None
    for index, (race_id, _number) in enumerate(rows):
        if race_id != race.id:
            continue
        if index > 0:
            previous_id = rows[index - 1][0]
        if index + 1 < len(rows):
            next_id = rows[index + 1][0]
        break
    return previous_id, next_id


def _load_dividends(session: Session, race_id: int) -> list[DividendPool]:
    snapshots = list(
        session.scalars(
            select(OddsSnapshot)
            .where(
                OddsSnapshot.race_id == race_id,
                OddsSnapshot.bet_type.notin_(("WIN", "PLC")),
            )
            .order_by(OddsSnapshot.bet_type, OddsSnapshot.odds)
        )
    )
    pools: list[DividendPool] = []
    for bet_type, items in groupby(snapshots, key=lambda row: row.bet_type):
        ranked = sorted(items, key=lambda row: row.odds)[:8]
        pools.append(
            DividendPool(
                bet_type=bet_type,
                label=dividend_label(bet_type),
                rows=[
                    DividendRow(selection=row.selection_key, odds=format_odds(row.odds))
                    for row in ranked
                ],
            )
        )
    pools.sort(key=lambda pool: pool.label)
    return pools


def _load_race_jockey_changes(
    session: Session,
    *,
    meet_code: int,
    race_date,
    race_number: int,
) -> list[RaceJockeyChangeRow]:
    rows = list(
        session.scalars(
            select(JockeyChange)
            .where(
                JockeyChange.meet_code == meet_code,
                JockeyChange.race_date_local == race_date,
                JockeyChange.race_number == race_number,
            )
            .order_by(JockeyChange.horse_number)
        )
    )
    return [
        RaceJockeyChangeRow(
            horse_number=row.horse_number,
            horse_name=_horse_name(session, row.horse_id),
            horse_id=row.horse_id,
            before_name=row.jockey_before_name or "—",
            after_name=row.jockey_after_name or "—",
            reason=row.reason or "—",
        )
        for row in rows
    ]


def _load_race_scratches(
    session: Session,
    *,
    meet_code: int,
    race_date,
    race_number: int,
) -> list[RaceScratchRow]:
    rows = list(
        session.scalars(
            select(RaceScratch)
            .where(
                RaceScratch.meet_code == meet_code,
                RaceScratch.race_date_local == race_date,
                RaceScratch.race_number == race_number,
            )
            .order_by(RaceScratch.horse_number)
        )
    )
    return [
        RaceScratchRow(
            horse_number=str(row.horse_number) if row.horse_number is not None else "—",
            horse_name=_horse_name(session, row.horse_id),
            horse_id=row.horse_id,
            reason=row.reason or "—",
        )
        for row in rows
    ]


def _load_race_equipment(
    session: Session,
    *,
    meet_code: int,
    race_date,
    race_number: int,
) -> list[RaceEquipmentRow]:
    rows = list(
        session.scalars(
            select(EntryEquipment)
            .where(
                EntryEquipment.meet_code == meet_code,
                EntryEquipment.race_date_local == race_date,
                EntryEquipment.race_number == race_number,
            )
            .order_by(EntryEquipment.horse_number)
        )
    )
    return [
        RaceEquipmentRow(
            horse_number=str(row.horse_number) if row.horse_number is not None else "—",
            horse_name=_horse_name(session, row.horse_id),
            horse_id=row.horse_id,
            equipment=row.equipment_raw or "—",
            bleeding=(
                f"{row.bleeding_count}회"
                if row.bleeding_count is not None
                else "—"
            ),
            illness=row.illness_note or "—",
        )
        for row in rows
        if row.equipment_raw or row.bleeding_count or row.illness_note
    ]


def _load_steward_report(
    session: Session,
    *,
    meet_code: int,
    race_date,
    race_number: int,
) -> StewardReportView | None:
    row = session.scalar(
        select(RaceStewardReport).where(
            RaceStewardReport.meet_code == meet_code,
            RaceStewardReport.race_date_local == race_date,
            RaceStewardReport.race_number == race_number,
        )
    )
    if row is None:
        return None
    return StewardReportView(
        weather=row.weather or "—",
        members=row.members or "—",
        judgement=row.judgement or "—",
        additional_judgement=row.additional_judgement or "—",
        jockey_change_note=row.jockey_change_note or "—",
    )


def _horse_name(session: Session, horse_id: int | None) -> str:
    if horse_id is None:
        return "—"
    horse = session.get(Horse, horse_id)
    return horse.name_ko if horse is not None else "—"


def build_section_chart_data(
    columns: list[SectionColumn],
    rows: list[SectionEntryRow],
) -> dict[str, object]:
    if not columns or not rows:
        return {"labels": [], "series": [], "maxPosition": 0}

    labels = [column.label for column in columns]
    series: list[dict[str, object]] = []
    max_position = 1

    for row in rows:
        positions: list[int | None] = []
        segment_times: list[str] = []
        cumulative_times: list[str] = []
        for cell in row.cells:
            pos = cell.sort_position if cell.sort_position < 90 else None
            positions.append(pos)
            segment_times.append(cell.segment_time if cell.segment_time != "—" else "")
            cumulative_times.append(
                cell.cumulative_time if cell.cumulative_time != "—" else ""
            )
            if pos is not None:
                max_position = max(max_position, pos)

        if all(position is None for position in positions):
            continue

        series.append(
            {
                "horseId": row.horse_id,
                "horseNumber": row.horse_number,
                "horseName": row.horse_name,
                "finishSort": row.finish_sort if row.finish_sort < 900 else 999,
                "positions": positions,
                "segmentTimes": segment_times,
                "cumulativeTimes": cumulative_times,
            }
        )

    return {
        "labels": labels,
        "segmentLabels": [f"{c.segment_label} ({c.segment_distance})" if c.segment_label
                          else "구간" for c in columns],
        "series": series,
        "maxPosition": max_position,
    }


def _section_columns(race: Race) -> list[SectionColumn]:
    present_codes = {
        section.section_code
        for entry in race.entries
        for section in entry.section_results
    }
    if not present_codes:
        return []

    preferred = [spec.code for spec in MEET_SECTION_SPECS.get(race.racecourse.kra_meet_code, [])]
    preferred_index = {code: index for index, code in enumerate(preferred)}
    cumulative_by_code: dict[str, list[int]] = {code: [] for code in present_codes}
    for entry in race.entries:
        cumulative = _entry_cumulative_times(
            entry,
            meet_code=race.racecourse.kra_meet_code,
        )
        for code in present_codes:
            value = cumulative.get(code)
            if value is not None:
                cumulative_by_code[code].append(value)
    ordered = sorted(
        present_codes,
        key=lambda code: (
            median(cumulative_by_code[code]) if cumulative_by_code[code] else float("inf"),
            preferred_index.get(code, len(preferred)),
            code,
        ),
    )
    # Compare normalized elapsed times, never the raw closing-window durations.
    # Require multiple matching horses and no conflicting time/rank observations.
    observations = [
        (
            _entry_cumulative_times(entry, meet_code=race.racecourse.kra_meet_code),
            {section.section_code: section.position for section in entry.section_results},
        )
        for entry in race.entries
    ]

    def equivalent(left: str, right: str) -> bool:
        matches = 0
        for times, positions in observations:
            if left in times and right in times:
                if times[left] != times[right]:
                    return False
                matches += 1
            if positions.get(left) is not None and positions.get(right) is not None:
                if positions[left] != positions[right]:
                    return False
        return matches >= 2

    groups: list[list[str]] = []
    for code in ordered:
        group = next((group for group in groups if all(equivalent(code, c) for c in group)), None)
        if group is None:
            groups.append([code])
        else:
            group.append(code)
    columns = []
    for group in groups:
        group.sort(key=lambda code: (preferred_index.get(code, len(preferred)), code))
        columns.append(SectionColumn(
            code=group[0],
            label="/".join(SECTION_LABELS.get(code, code) for code in group),
            aliases=tuple(group[1:]),
        ))
    columns.append(SectionColumn(code=FINISH_LABEL, label=FINISH_LABEL))
    if race.racecourse.kra_meet_code == 2:
        columns = _jeju_column_descriptions(columns, race.distance_m)
    return columns


def _jeju_column_descriptions(columns: list[SectionColumn], distance: int) -> list[SectionColumn]:
    early = 210 if distance in (1110, 1610) else 200
    points = {"S1F": early, "1C": distance - 1400, "2C": distance - 1200,
              "3C": distance - 600, "G3F": distance - 600,
              "4C": distance - 400, "G1F": distance - 200, "FIN": distance}
    previous_point, previous_label, previous_approximate = 0, "START", False
    described = []
    for column in columns:
        point = points.get(column.code)
        approximate = any(code in ("1C", "2C", "3C", "4C") for code in column.codes)
        valid = point is not None and 0 <= point <= distance
        location = ""
        if valid:
            location = (f"출발 후 {early}m" if column.code == "S1F" else
                        "결승" if column.code == "FIN" else
                        f"결승 {'약 ' if approximate else ''}{distance - point}m 전")
        length = point - previous_point if valid and previous_point is not None else None
        segment_distance = (
            "동일 지점" if length == 0 else
            f"{'약 ' if approximate or previous_approximate else ''}{length:,}m"
            if length is not None and length > 0 else "거리 확인 필요"
        )
        described.append(replace(column, location=location,
                                 segment_label=f"{previous_label} → {column.label}",
                                 segment_distance=segment_distance))
        previous_point = point if valid else None
        previous_label, previous_approximate = column.label, approximate
    return described


def _section_rows(
    entries: list[RaceEntry],
    columns: list[SectionColumn],
    *,
    meet_code: int,
) -> list[SectionEntryRow]:
    if not columns:
        return []

    inferred_positions = _derived_section_positions(
        entries,
        columns,
        meet_code=meet_code,
    )
    rows: list[SectionEntryRow] = []
    for entry in entries:
        by_code = {section.section_code: section for section in entry.section_results}
        raw_finish = entry.result.finish_position if entry.result is not None else None
        finish_label, finish_sort, _special = format_finish_position(
            raw_finish, scratched=entry.scratched
        )
        cumulative = _entry_cumulative_times(entry, meet_code=meet_code)
        cells: list[SectionCell] = []
        previous_cumulative_ms = 0
        for column in columns:
            cumulative_ms = _column_time(cumulative, column)
            segment_ms = None
            same_checkpoint = (
                cumulative_ms is not None
                and previous_cumulative_ms is not None
                and previous_cumulative_ms > 0
                and cumulative_ms == previous_cumulative_ms
            )
            if (cumulative_ms is not None and previous_cumulative_ms is not None
                    and cumulative_ms >= previous_cumulative_ms):
                segment_ms = cumulative_ms - previous_cumulative_ms
            # Missing checkpoints must not turn the following cell into a longer interval.
            previous_cumulative_ms = cumulative_ms
            if column.code == FINISH_LABEL:
                position = raw_finish
                position_inferred = False
            else:
                position = next(
                    (by_code[code].position for code in column.codes
                     if code in by_code and by_code[code].position is not None), None
                )
                position_inferred = position is None and cumulative_ms is not None
                if position_inferred:
                    position = inferred_positions.get(column.code, {}).get(
                        entry.horse_number
                    )
            cells.append(
                _section_cell(
                    position,
                    segment_ms,
                    cumulative_ms,
                    position_inferred=position_inferred,
                    same_checkpoint=same_checkpoint,
                )
            )
        rows.append(
            SectionEntryRow(
                horse_id=entry.horse_id,
                horse_number=entry.horse_number,
                horse_name=entry.horse.name_ko,
                finish_position=finish_label,
                finish_sort=finish_sort,
                cells=cells,
                closing_600=format_race_time(by_code["G3F"].elapsed_time_ms)
                if meet_code == 2 and "G3F" in by_code else "—",
                closing_200=format_race_time(by_code["G1F"].elapsed_time_ms)
                if meet_code == 2 and "G1F" in by_code else "—",
            )
        )
    rows.sort(key=lambda row: (row.finish_sort, row.horse_number))
    return rows


def _section_cell(
    position_value: int | None,
    segment_time_ms: int | None,
    cumulative_time_ms: int | None,
    *,
    position_inferred: bool = False,
    same_checkpoint: bool = False,
) -> SectionCell:
    position = "—"
    if position_value is not None:
        position, _, _ = format_finish_position(position_value)
    return SectionCell(
        position=position,
        segment_time=(
            "동일 지점" if same_checkpoint else format_race_time(segment_time_ms)
        ),
        cumulative_time=format_race_time(cumulative_time_ms),
        sort_position=position_value if position_value is not None else 999,
        position_inferred=position_inferred and position_value is not None,
    )


def _derived_section_positions(
    entries: list[RaceEntry],
    columns: list[SectionColumn],
    *,
    meet_code: int,
) -> dict[str, dict[int, int]]:
    cumulative_by_horse = {
        entry.horse_number: _entry_cumulative_times(entry, meet_code=meet_code)
        for entry in entries
    }
    positions: dict[str, dict[int, int]] = {}
    for column in columns:
        if column.code == FINISH_LABEL:
            continue
        timed_horses = sorted(
            (
                (horse_number, value)
                for horse_number, cumulative in cumulative_by_horse.items()
                if (value := _column_time(cumulative, column)) is not None
            ),
            key=lambda item: (item[1], item[0]),
        )
        rank_by_time: dict[int, int] = {}
        for index, (_horse_number, elapsed_ms) in enumerate(timed_horses, start=1):
            rank_by_time.setdefault(elapsed_ms, index)
        positions[column.code] = {
            horse_number: rank_by_time[elapsed_ms]
            for horse_number, elapsed_ms in timed_horses
        }
    return positions


def _column_time(cumulative: dict[str, int], column: SectionColumn) -> int | None:
    return next((cumulative[code] for code in column.codes if code in cumulative), None)


def _entry_cumulative_times(entry: RaceEntry, *, meet_code: int) -> dict[str, int]:
    raw_times = {
        section.section_code: section.elapsed_time_ms
        for section in entry.section_results
        if section.elapsed_time_ms is not None
    }
    finish_time_ms = entry.result.finish_time_ms if entry.result is not None else None
    cumulative = derive_section_cumulative_times(
        raw_times,
        finish_time_ms=finish_time_ms,
        meet_code=meet_code,
    )
    if finish_time_ms is not None:
        cumulative[FINISH_LABEL] = finish_time_ms
    return cumulative


def derive_section_cumulative_times(
    raw_times: dict[str, int],
    *,
    finish_time_ms: int | None,
    meet_code: int,
) -> dict[str, int]:
    """Normalize checkpoint and closing-window times to elapsed time from START."""
    g3f = raw_times.get("G3F")
    g1f = raw_times.get("G1F")
    closing_window_times = meet_code == 2 or (
        g3f is not None and g1f is not None and g3f > g1f
    ) or (
        finish_time_ms is not None
        and g1f is not None
        and g1f < finish_time_ms / 2
    )
    cumulative: dict[str, int] = {}
    for code, raw_time_ms in raw_times.items():
        if closing_window_times and _is_goal_furlong(code):
            if finish_time_ms is not None and finish_time_ms >= raw_time_ms:
                cumulative[code] = finish_time_ms - raw_time_ms
            continue
        cumulative[code] = raw_time_ms
    return cumulative


def _is_goal_furlong(code: str) -> bool:
    return code.startswith("G") and code.endswith("F") and code[1:-1].isdigit()
