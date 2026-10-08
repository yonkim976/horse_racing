from __future__ import annotations

from urllib.parse import urlencode

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from horse_racing.db.models import Horse

GRADE_LABELS = {str(n): f"{n}등급" for n in range(1, 7)} | {
    "untried": "미검마", "unrated": "미등급", "other": "기타 등급", "unknown": "등급 미확인",
}
ORIGIN_LABELS = {"domestic": "국산마", "foreign": "외산마", "unknown": "산지 미확인"}


def grade_bucket():
    value = func.replace(func.trim(func.coalesce(Horse.grade, "")), " ", "")
    return case(
        *[(value.in_([str(n), f"{n}등급", f"국{n}", f"외{n}", f"혼{n}", f"제{n}",
                      f"국{n}등급", f"외{n}등급", f"혼{n}등급", f"제{n}등급"]), str(n))
          for n in range(1, 7)],
        (value.in_(["미검", "미검마", "국미검", "외미검", "혼미검", "제미검"]), "untried"),
        (value.in_(["미", "미등급", "미경주", "신마", "0", "국미", "외미", "혼미", "제미"]),
         "unrated"),
        (value.in_(["", "—", "-"]), "unknown"),
        else_="other",
    )


def origin_bucket():
    value = func.upper(func.trim(func.coalesce(Horse.origin_country, "")))
    return case(
        (value.in_(["한국", "대한민국", "국산", "국산마", "KOR", "KR"]), "domestic"),
        (value.in_(["", "—", "-", "미상", "미확인"]), "unknown"),
        else_="foreign",
    )


def load_horse_directory_summary(session: Session, meet: int | None, sort: str) -> dict:
    """Aggregate current profiles once; retirement is never mixed into active counts."""
    grade, origin = grade_bucket(), origin_bucket()
    statement = select(Horse.meet_code, grade, origin, Horse.is_active, func.count())
    if meet is not None:
        statement = statement.where(Horse.meet_code == meet)
    groups = session.execute(statement.group_by(
        Horse.meet_code, grade, origin, Horse.is_active,
    )).all()

    def href(grade_key="", origin_key="", meet_key=meet):
        params = {"status": "active", "sort": sort}
        if meet_key is not None:
            params["meet"] = str(meet_key)
        if grade_key:
            params["grade"] = grade_key
        if origin_key:
            params["origin"] = origin_key
        return "/horses/list?" + urlencode(params)

    active_groups = [row for row in groups if row[3] is True]
    if meet in {1, 3}:
        columns = [(key, label) for key, label in ORIGIN_LABELS.items()
                   if key != "unknown" or any(row[2] == "unknown" for row in active_groups)]
        columns.append(("total", "계"))
    elif meet == 2:
        columns = [("total", "두수")]
    else:
        columns = [("1", "서울"), ("3", "부산"), ("2", "제주")]
        if any(row[0] not in {1, 2, 3} for row in active_groups):
            columns.append(("other", "기타·미분류"))
        columns.append(("total", "계"))

    def cell(column, grade_key=""):
        count = sum(total for region, bucket, birth, _, total in active_groups
                    if (not grade_key or bucket == grade_key)
                    and (column == "total"
                         or (meet in {1, 3} and birth == column)
                         or (meet is None and str(region) == column)
                         or (meet is None and column == "other" and region not in {1, 2, 3})))
        region = int(column) if meet is None and column in {"1", "2", "3"} else meet
        origin_key = column if meet in {1, 3} and column != "total" else ""
        link = href(grade_key=grade_key, origin_key=origin_key, meet_key=region)
        if meet is None and column == "other":
            link = None  # No public meet filter for unclassified registrations.
        return {"count": count, "href": link}

    rows = [{"label": label, "cells": [cell(column, key) for column, _ in columns]}
            for key, label in GRADE_LABELS.items()
            if key in {str(n) for n in range(1, 7)} or any(row[1] == key for row in active_groups)]
    return {
        "title": f"{ {1: '서울', 3: '부산', 2: '제주'}.get(meet, '전체 지역') } 등급별 현역마",
        "columns": [label for _, label in columns], "rows": rows,
        "totals": [cell(column) for column, _ in columns],
        "is_jeju": meet == 2,
        "grade_labels": GRADE_LABELS, "origin_labels": ORIGIN_LABELS,
    }
