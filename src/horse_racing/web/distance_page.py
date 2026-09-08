"""Distance browsing of completed Jeju races, without changing source records."""

from datetime import date
from math import ceil
from urllib.parse import urlencode

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from horse_racing.db.models import Race, Racecourse, RaceEntry, RaceResult
from horse_racing.web.formatting import format_race_time

PAGE_SIZE = 30
GRADE_LABELS = (
    [f"제{i}등급" for i in range(6, 0, -1)]
    + ["제OPEN"]
    + [f"한{i}등급" for i in range(4, 0, -1)]
    + ["한OPEN", "미분류"]
)


def grade_expression():
    # Historical imports sometimes put age conditions in grade. Do not infer a grade.
    conditions = []
    for prefix, maximum in (("제", 6), ("한", 4)):
        for number in range(1, maximum + 1):
            label = f"{prefix}{number}등급"
            conditions.append(
                ((Race.grade == f"{prefix}{number}") | Race.grade.like(f"{label}%"), label)
            )
        conditions.append(
            (Race.grade.like(f"{prefix}OPEN%") | Race.grade.like(f"{prefix}오픈%"), f"{prefix}OPEN")
        )
    return case(*conditions, else_="미분류")


def load_distance_page(
    session: Session,
    *,
    year: int | None,
    distance: int,
    grade: str,
    page: int,
) -> dict:
    base = [Racecourse.kra_meet_code == 2, Race.status == "completed"]
    years = list(
        session.scalars(
            select(func.substr(Race.race_date_local, 1, 4))
            .join(Racecourse)
            .where(*base)
            .distinct()
            .order_by(func.substr(Race.race_date_local, 1, 4).desc())
        )
    )
    selected_year = year if year is not None else (int(years[0]) if years else 0)
    conditions = list(base)
    if selected_year:
        conditions.extend(
            [
                Race.race_date_local >= date(selected_year, 1, 1),
                Race.race_date_local <= date(selected_year, 12, 31),
            ]
        )
    normalized_grade = grade_expression()
    if grade:
        conditions.append(normalized_grade == grade)

    def link(**changes):
        values = dict(year=selected_year, distance=distance, grade=grade)
        values.update(changes)
        return "/racecourses/jeju/distances?" + urlencode(values)

    distances = session.execute(
        select(Race.distance_m, func.count(Race.id))
        .join(Racecourse)
        .where(*conditions)
        .group_by(Race.distance_m)
        .order_by(Race.distance_m)
    ).all()
    if distance:
        conditions.append(Race.distance_m == distance)
    selected = select(Race.id).join(Racecourse).where(*conditions)
    normal = (
        RaceResult.finish_position.between(1, 89)
        & (RaceResult.finish_time_ms > 0)
        & RaceResult.disqualified.is_(False)
        & RaceEntry.scratched.is_(False)
    )
    records = (
        select(
            RaceEntry.race_id.label("race_id"),
            func.count(RaceEntry.id).label("entries"),
            func.count(case((normal, 1))).label("timed"),
            func.sum(case((normal, RaceResult.finish_time_ms))).label("time_sum"),
            func.min(case((normal, RaceResult.finish_time_ms))).label("best"),
            func.min(
                case((normal & (RaceResult.finish_position == 1), RaceResult.finish_time_ms))
            ).label("winner_time"),
        )
        .outerjoin(RaceResult, RaceResult.race_entry_id == RaceEntry.id)
        .where(RaceEntry.race_id.in_(selected))
        .group_by(RaceEntry.race_id)
        .subquery()
    )
    totals = session.execute(
        select(
            func.count(Race.id),
            func.coalesce(func.sum(records.c.entries), 0),
            func.coalesce(func.sum(records.c.timed), 0),
            func.sum(records.c.time_sum),
            func.min(records.c.best),
            func.min(Race.race_date_local),
            func.max(Race.race_date_local),
        )
        .join(Racecourse)
        .outerjoin(records, records.c.race_id == Race.id)
        .where(*conditions)
    ).one()
    total, entries, timed, time_sum, best, first, last = totals
    total_pages = max(1, ceil(total / PAGE_SIZE))
    page = min(page, total_pages)
    rows = (
        session.execute(
            select(
                Race.id,
                Race.race_date_local,
                Race.race_number,
                Race.distance_m,
                Race.grade,
                normalized_grade.label("display_grade"),
                Race.race_name,
                Race.track_condition,
                records.c.entries,
                records.c.timed,
                records.c.winner_time,
            )
            .join(Racecourse)
            .outerjoin(records, records.c.race_id == Race.id)
            .where(*conditions)
            .order_by(Race.race_date_local.desc(), Race.race_number.desc())
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )
        .mappings()
        .all()
    )
    items = [dict(row, winner_time=format_race_time(row["winner_time"])) for row in rows]
    return dict(
        years=years,
        year=selected_year,
        distance=distance,
        grade=grade,
        grade_labels=GRADE_LABELS,
        total=total,
        entries=entries,
        timed=timed,
        average=format_race_time(round(time_sum / timed)) if timed and distance else "—",
        best=format_race_time(best) if distance else "—",
        first=first,
        last=last,
        distances=[dict(distance=d, count=n, url=link(distance=d)) for d, n in distances],
        all_url=link(distance=0),
        reset_url="/racecourses/jeju/distances",
        items=items,
        page=page,
        total_pages=total_pages,
        previous=link(page=page - 1) if page > 1 else None,
        next=link(page=page + 1) if page < total_pages else None,
    )
