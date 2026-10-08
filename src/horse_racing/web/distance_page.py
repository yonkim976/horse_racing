"""Distance browsing of completed race records, without changing source records."""

from datetime import date
from math import ceil
from urllib.parse import urlencode

from sqlalchemy import Integer, case, extract, func, select
from sqlalchemy.orm import Session

from horse_racing.db.models import Race, Racecourse, RaceEntry, RaceResult, RunningTrial
from horse_racing.web.distance_benchmarks import (
    BENCHMARK_BANDS,
    build_distance_benchmark_view,
)
from horse_racing.web.distance_sections import AnalysisCache, load_distance_section_analysis
from horse_racing.web.formatting import format_race_time
from horse_racing.web.race_scope import active_race_clause

PAGE_SIZE = 30
GRADE_LABELS = (
    [f"제{i}등급" for i in range(6, 0, -1)]
    + ["제OPEN"]
    + ["미분류"]
)


SEOUL_GRADE_LABELS = ([f"국{i}등급" for i in range(6, 0, -1)]
                      + [f"혼{i}등급" for i in range(4, 0, -1)]
                      + ["2등급", "1등급", "국OPEN", "혼OPEN", "미분류"])


def grade_expression(meet_code=2):
    # Historical imports sometimes put age conditions in grade. Do not infer a grade.
    conditions = []
    for prefix, maximum in ((("제", 6),) if meet_code == 2 else (("국", 6), ("혼", 4))):
        for number in range(1, maximum + 1):
            label = f"{prefix}{number}등급"
            conditions.append(
                ((Race.grade == f"{prefix}{number}") | Race.grade.like(f"{label}%"), label)
            )
        conditions.append(
            (Race.grade.like(f"{prefix}OPEN%") | Race.grade.like(f"{prefix}오픈%"), f"{prefix}OPEN")
        )
    if meet_code in (1, 3, 4):
        conditions.extend((Race.grade.like(f"{n}등급%"), f"{n}등급") for n in (1, 2))
    return case(*conditions, else_="미분류")


def load_distance_page(
    session: Session,
    *,
    year: int | None,
    distance: int,
    grade: str,
    page: int,
    meet_code: int = 2,
    view: str = "regular",
    band: str = "",
    cache: AnalysisCache | None = None,
) -> dict:
    if view not in {"regular", "trials"}:
        raise ValueError("unsupported distance page view")
    benchmark_enabled = view == "regular" and meet_code in {1, 3} and distance == 1200
    if band and (not benchmark_enabled or band not in BENCHMARK_BANDS):
        raise ValueError("unsupported distance benchmark band")
    selected_band = (band or "건조") if benchmark_enabled else ""
    if view == "trials":
        distance = 0
        grade = ""
    course = {1: "seoul", 2: "jeju", 3: "busan", 4: "yeongcheon"}[meet_code]
    base_url = f"/racecourses/{course}/distances"
    base = [
        Racecourse.kra_meet_code == meet_code,
        Race.status == "completed",
        active_race_clause(),
    ]
    if view == "trials":
        year_column = extract("year", RunningTrial.trial_date_local).cast(Integer)
        years = list(
            session.scalars(
                select(year_column)
                .where(RunningTrial.meet_code == meet_code, RunningTrial.distance_m <= 1200)
                .distinct()
                .order_by(year_column.desc())
            )
        )
    else:
        year_column = extract("year", Race.race_date_local).cast(Integer)
        years = list(
            session.scalars(
                select(year_column)
                .join(Racecourse)
                .where(*base)
                .distinct()
                .order_by(year_column.desc())
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
    normalized_grade = grade_expression(meet_code)
    if grade:
        conditions.append(normalized_grade == grade)

    def link(**changes):
        values = dict(year=selected_year, distance=distance, grade=grade)
        values.update(changes)
        if meet_code in {1, 3} and values.get("distance") == 1200:
            values["band"] = selected_band or "건조"
        else:
            values.pop("band", None)
        return base_url + "?" + urlencode(values)

    trials_url = base_url + "?" + urlencode({"view": "trials", "year": selected_year})
    meet_urls = {
        slug: (
            f"/racecourses/{slug}/distances?"
            + urlencode({"view": "trials", "year": selected_year})
            if view == "trials"
            else f"/racecourses/{slug}/distances"
        )
        for slug in ("seoul", "busan", "yeongcheon", "jeju")
    }

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
    section_analysis = load_distance_section_analysis(
        session,
        selected_race_ids=selected,
        meet_code=meet_code,
        year=selected_year,
        distance_m=distance,
        grade=grade,
        cache=cache,
    )
    if view == "trials":
        return dict(
            course_name={1: "서울", 2: "제주", 3: "부경", 4: "영천"}[meet_code],
            course=course, meet_code=meet_code, base_url=base_url,
            meet_urls=meet_urls, view=view, years=years, year=selected_year,
            distance=distance, grade="",
            grade_labels=GRADE_LABELS if meet_code == 2 else SEOUL_GRADE_LABELS,
            distances=[dict(distance=d, count=n, url=link(distance=d)) for d, n in distances],
            section_analysis=section_analysis, all_url=link(distance=0),
            trials_url=trials_url,
            reset_url=base_url + "?view=trials",
            benchmark=None,
            band="",
        )
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
    benchmark = (
        build_distance_benchmark_view(meet_code=meet_code, grade=grade, band=selected_band)
        if benchmark_enabled
        else None
    )
    if benchmark and not grade:
        for row in benchmark["summary_rows"]:
            row["url"] = link(distance=1200, grade=row["grade_label"])
    return dict(
        course_name={1: "서울", 2: "제주", 3: "부경", 4: "영천"}[meet_code],
        course=course, meet_code=meet_code, base_url=base_url,
        meet_urls=meet_urls, view=view,
        years=years,
        year=selected_year,
        distance=distance,
        grade=grade,
        grade_labels=GRADE_LABELS if meet_code == 2 else SEOUL_GRADE_LABELS,
        total=total,
        entries=entries,
        timed=timed,
        average=format_race_time(round(time_sum / timed)) if timed and distance else "—",
        best=format_race_time(best) if distance else "—",
        first=first,
        last=last,
        distances=[dict(distance=d, count=n, url=link(distance=d)) for d, n in distances],
        trials_url=trials_url,
        section_analysis=section_analysis,
        benchmark=benchmark,
        band=selected_band,
        all_url=link(distance=0),
        reset_url=base_url,
        items=items,
        page=page,
        total_pages=total_pages,
        previous=link(page=page - 1) if page > 1 else None,
        next=link(page=page + 1) if page < total_pages else None,
    )
