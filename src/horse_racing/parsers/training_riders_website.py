"""Strict horse-profile training rows and the official rider legend."""

import re
from datetime import datetime

from bs4 import BeautifulSoup

MARKERS = {
    "조": "조교사",
    "관": "주로조교",
    "생": "교육생",
    "후": "기수후보생",
    "트": "기수트랙라이더",
}


def rider_label(raw):
    raw = raw.strip()
    match = re.fullmatch(r".*\((조|관|생|후|트)\)", raw)
    if raw in MARKERS:
        return MARKERS[raw], None
    if match:
        return MARKERS[match[1]], None
    if raw in {
        "조교사",
        "조교보",
        "조교승인",
        "교육생",
        "기수후보생",
        "주로조교",
        "기수트랙라이더",
    }:
        return raw, None
    if raw not in {"", "-", "—", "외", "미상", "미확인"} and re.fullmatch(
        r"[가-힣A-Za-z][가-힣A-Za-z .·'\-]{0,49}", raw
    ):
        # Official profile legend explicitly defines unmarked personal names as jockey names.
        return "기수", raw
    return "미확인", None


def parse_training_riders(
    raw: bytes, *, horse_name: str, start_date=None, end_date=None, rejected_rows=None
):
    soup = BeautifulSoup(raw, "html.parser")
    identity = False
    for tr in soup.select("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"], recursive=False)]
        for i, cell in enumerate(cells[:-1]):
            if cell == "마명" and cells[i + 1].split("(", 1)[0].strip() == horse_name:
                identity = True
    if not identity:
        raise ValueError("Training profile horse identity mismatch")
    text = soup.get_text(" ", strip=True)
    if not all(word in text for word in ("기승자범례", "기수트랙라이더", "주로조교", "교육생")):
        raise ValueError("Official rider legend missing")
    tables = [
        t
        for t in soup.select("table")
        if all(
            word in " ".join(x.get_text(strip=True) for x in t.select("th"))
            for word in ("조교일자", "기승자", "입장시간", "퇴장시간", "조교시간")
        )
    ]
    if len(tables) != 1:
        raise ValueError("Training profile table missing or ambiguous")
    rows = []
    for source_row_no, tr in enumerate(tables[0].select("tr"), 1):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all("td", recursive=False)]
        if len(cells) < 6 or not re.match(r"^\d{4}/\d{2}/\d{2}", cells[1]):
            continue
        if cells[2] in ("경주일", "수영조교"):
            continue
        day = datetime.strptime(cells[1][:10], "%Y/%m/%d").date()
        if (start_date and day < start_date) or (end_date and day > end_date):
            continue
        if not re.fullmatch(r"\d{2}:\d{2}", cells[3]) or not re.fullmatch(r"\d{2}:\d{2}", cells[4]):
            raise ValueError("Training event time missing")
        duration = re.fullmatch(r"(\d+)\s*분", cells[5])
        if not duration:
            raise ValueError("Training event duration missing")
        start = datetime.strptime(cells[3], "%H:%M").time()
        end = datetime.strptime(cells[4], "%H:%M").time()
        seconds = int(duration[1]) * 60
        elapsed = (datetime.combine(day, end) - datetime.combine(day, start)).total_seconds()
        if seconds <= 0 or elapsed != seconds:
            if rejected_rows is not None:
                rejected_rows.append(source_row_no)
                continue
            raise ValueError("Training event duration mismatch")
        role, name = rider_label(cells[2])
        rows.append(
            {
                "date": day,
                "start": cells[3],
                "end": cells[4],
                "seconds": seconds,
                "role": role,
                "name": name,
                "raw": cells[2],
                "source_row_no": source_row_no,
            }
        )
    return rows
