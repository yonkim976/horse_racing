"""Parse observed KRA pages without borrowing dates or values from results."""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

KST = ZoneInfo("Asia/Seoul")
VERSION = "jeju_pregame_html_v1.1"


class PregameParseError(ValueError):
    pass


def clean(tag):
    return " ".join(tag.get_text(" ", strip=True).split())


def number(value, *, integer=False, optional=False):
    value = value.replace(",", "").strip()
    if optional and value in {"", "-"}:
        return None
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
        raise PregameParseError(f"Invalid number: {value!r}")
    result = float(value)
    if integer and result != int(result):
        raise PregameParseError("Expected integer")
    return int(result) if integer else result


def rating_value(value):
    if value in {"", "-"}:
        return None, None
    match = re.fullmatch(r"(\d+)(?:\(([+-]?\d+)\))?", value)
    if not match:
        raise PregameParseError("Invalid rating/change notation")
    return int(match[1]), int(match[2]) if match[2] is not None else None


def date_text(value):
    m = re.search(r"(20\d{2})\D+(\d{1,2})\D+(\d{1,2})", value)
    if not m:
        raise PregameParseError("Explicit calendar date missing")
    return datetime(*map(int, m.groups()), tzinfo=KST).date().isoformat()


def full_timestamp(value):
    # Time-of-day without an explicit calendar date is never backdated.
    m = re.search(r"(20\d{2})\D+(\d{1,2})\D+(\d{1,2})\D+(\d{1,2})[:시]\s*(\d{2})", value)
    return datetime(*map(int, m.groups()), tzinfo=KST).isoformat() if m else None


def identity(cell, function):
    values = []
    for a in cell.select("a"):
        script = a.get("onclick", "") + " " + a.get("href", "")
        m = re.search(rf"{function}\(\s*['\"](\d+)['\"]\s*,\s*['\"]2['\"]", script)
        if m:
            values.append(m[1])
    if len(set(values)) != 1:
        raise PregameParseError(f"Missing/ambiguous Jeju identity: {function}")
    return values[0]


def table(soup, caption):
    found = [
        t
        for t in soup.select("table")
        if t.caption and caption in re.sub(r"\s", "", clean(t.caption))
    ]
    if len(found) != 1:
        raise PregameParseError(f"Expected one table: {caption}")
    return found[0]


def rows(t, width):
    result = []
    empty = False
    for tr in t.select("tbody tr") or t.select("tr"):
        cells = tr.find_all("td", recursive=False)
        if not cells:
            continue
        if len(cells) == 1 and "자료가 없습니다" in clean(cells[0]):
            empty = True
            continue
        if len(cells) != width:
            raise PregameParseError(f"Changed table width: {len(cells)} != {width}")
        result.append(cells)
    if empty and result:
        raise PregameParseError("Mixed empty and populated table")
    if not result and not empty:
        raise PregameParseError("Missing table body is not an empty report")
    return result


def unique(items, keys):
    tuples = [tuple(r[k] for k in keys) for r in items]
    if len(tuples) != len(set(tuples)):
        raise PregameParseError(f"Duplicate keys: {keys}")


def schedule(s):
    t = table(s, "일자별경주정보")
    result = []
    for c in rows(t, 12):
        a = c[2].find("a")
        m = re.search(
            r"goChulmapyo\([\s\"\']*2[\"\'],[\s\"\']*(\d{8})[\"\'],[\s\"\']*(\d+)",
            a.get("onclick", "") if a else "",
        )
        if not m:
            raise PregameParseError("Missing race link")
        day = date_text(clean(c[1]))
        race = number(clean(c[2]), integer=True)
        if m[1] != day.replace("-", "") or int(m[2]) != race or clean(c[9]) != "제주":
            raise PregameParseError("Schedule identity mismatch")
        time = clean(c[8])
        start = datetime.fromisoformat(f"{day}T{time}:00").replace(tzinfo=KST)
        result.append(
            dict(
                race_date=day,
                race_number=race,
                grade=clean(c[3]),
                distance_m=number(clean(c[4]).removesuffix("M"), integer=True),
                declared_count=number(clean(c[5]).removesuffix("두"), integer=True),
                listed_count=number(clean(c[6]).removesuffix("두"), integer=True),
                scheduled_start_at=start.isoformat(),
            )
        )
    unique(result, ["race_date", "race_number"])
    return dict(races=result, complete=bool(result))


def race_heading(s):
    candidates = [clean(t) for t in s.select("table") if re.search(r"제\s*\d+경주", clean(t))]
    if not candidates:
        raise PregameParseError("Missing explicit race heading")
    heading = candidates[0]
    if "제주" not in heading:
        raise PregameParseError("Wrong meet")
    return date_text(heading), int(re.search(r"제\s*(\d+)경주", heading)[1])


def card(s):
    day, race = race_heading(s)
    t = table(s, "번호,마명")
    result = []
    for c in rows(t, 15):
        if clean(c[2]) != "제주":
            raise PregameParseError("Non-native runner")
        rating, rating_delta = rating_value(clean(c[5]))
        result.append(
            dict(
                horse_number=number(clean(c[0]), integer=True),
                horse_id=identity(c[1], "goPage1"),
                horse_name=clean(c[1]),
                breed=clean(c[2]),
                sex=clean(c[3]),
                age=number(clean(c[4]), integer=True),
                rating=rating,
                rating_delta=rating_delta,
                burden_kg=number(clean(c[6]), optional=True),
                burden_delta_kg=number(clean(c[7]), optional=True),
                jockey_id=identity(c[8], "goPage2"),
                jockey_name=clean(c[8]),
                trainer_id=identity(c[9], "goPage3"),
                trainer_name=clean(c[9]),
                equipment=clean(c[13]),
                remarks=clean(c[14]),
            )
        )
    unique(result, ["horse_number"])
    unique(result, ["horse_id"])
    return dict(race_date=day, race_number=race, runners=result, complete=bool(result))


def changes(s):
    result = []
    for caption, kind, width in [
        ("말취소내용", "withdrawal", 10),
        ("기수변경내용", "jockey_change", 11),
    ]:
        for c in rows(table(s, caption), width):
            v = list(map(clean, c))
            shift = 1 if kind == "withdrawal" else 0
            if v[shift] != "제주":
                raise PregameParseError("Unexpected meet in Jeju notices")
            r = dict(
                kind=kind,
                race_date=date_text(v[1 + shift]),
                race_number=number(v[2 + shift], integer=True),
                horse_number=number(v[3 + shift], integer=True),
                horse_name=v[4 + shift],
                notice_time_raw=v[-1],
                published_at=full_timestamp(v[-1]),
                reason=v[-2],
            )
            if kind == "withdrawal":
                r["withdrawal_type"] = v[0]
            else:
                r.update(
                    old_jockey_name=v[5],
                    old_burden_kg=number(v[6], optional=True),
                    new_jockey_name=v[7],
                    new_burden_kg=number(v[8], optional=True),
                )
            result.append(r)
    return dict(
        notices=result,
        parsed=True,
        coverage="page_observation_only; empty page does not prove all-date absence",
    )


def weight_index(s):
    result = []
    for c in rows(table(s, "금일출전마체중경주목록"), 3):
        a = c[0].find("a")
        m = re.search(
            r"goDetail\([\s\"\']*2[\"\'],[\s\"\']*(\d+)[\"\'],[\s\"\']*(\d{8})",
            a.get("onclick", "") if a else "",
        )
        if not m:
            raise PregameParseError("Weight list missing explicit dated link")
        day = datetime.strptime(m[2], "%Y%m%d").date().isoformat()
        result.append(dict(race_date=day, race_number=int(m[1]), input_status=clean(c[2])))
    unique(result, ["race_date", "race_number"])
    return dict(races=result)


def weight(s):
    day, race = race_heading(s)
    result = []
    for c in rows(table(s, "금일출전마체중내용"), 10):
        result.append(
            dict(
                horse_number=number(clean(c[0]), integer=True),
                horse_id=identity(c[1], "goHorse"),
                horse_name=clean(c[1]),
                body_weight_kg=number(clean(c[2]), optional=True),
                body_weight_delta_kg=number(clean(c[3]), optional=True),
            )
        )
    unique(result, ["horse_number"])
    unique(result, ["horse_id"])
    return dict(race_date=day, race_number=race, runners=result)


def track(s):
    headings = [clean(t) for t in s.select("h2") if "경주로 현황" in clean(t)]
    dated = [h for h in headings if full_timestamp(h)]
    if len(dated) != 1:
        raise PregameParseError("Missing dated track status")
    m = re.search(r"함수율\s*:\s*(\d+(?:\.\d+)?)%\s*\(([^)]+)\)", clean(s))
    if not m or not 0 < float(m[1]) <= 100:
        raise PregameParseError("Missing observed moisture (legend is not observation)")
    return dict(
        effective_at=full_timestamp(dated[0]),
        moisture_percent=float(m[1]),
        track_condition=m[2],
        published_at=None,
    )


PARSERS = dict(
    schedule=schedule,
    card=card,
    changes=changes,
    weight_index=weight_index,
    weight=weight,
    track=track,
)


def parse_page(kind, body, encoding="euc-kr"):
    soup = BeautifulSoup(body.decode(encoding, errors="strict"), "html.parser")
    return PARSERS[kind](soup)
