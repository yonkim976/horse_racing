from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")

GENERIC_RACE_NAMES = {"", "일반", "일반경주"}

SPECIAL_FINISH_LABELS = {
    91: "출전취소",
    92: "출전제외",
    93: "주행중지",
    94: "출전제외",
    95: "경주제외",
    96: "주행중지",
    99: "경주취소",
}

DIVIDEND_LABELS = {
    "WIN": "단승",
    "PLC": "연승",
    "QNL": "복승",
    "EXA": "쌍승",
    "QLA": "복연승",
    "QPL": "복연승",
    # API301 stores TRI as ordered nP3 combinations and TLA as unordered nC3.
    "TRI": "삼쌍승",
    "TLA": "삼복승",
}

MAX_NORMAL_FINISH = 89


def format_clock(epoch_ms: int | None) -> str:
    if epoch_ms is None:
        return "미정"
    return datetime.fromtimestamp(epoch_ms / 1000, tz=SEOUL).strftime("%H:%M")


def format_race_time(milliseconds: int | None) -> str:
    if milliseconds is None:
        return "—"
    minutes, remaining = divmod(milliseconds, 60_000)
    seconds = remaining / 1000
    return f"{minutes}:{seconds:04.1f}" if minutes else f"{seconds:.1f}초"


def format_odds(value: float | None) -> str:
    return f"{value:g}배" if value is not None else "—"


def format_money(value: int | None) -> str:
    return f"{value:,}원" if value is not None else "—"


def format_margin(value: str | None, *, missing: str = "—") -> str:
    cleaned = (value or "").strip()
    if cleaned in {"", "-", "‐", "–", "—"}:
        return missing
    return cleaned


def format_rating(value: float | int | None) -> str:
    if value is None or value == 0:
        return "—"
    return f"{value:g}"


def age_years(birth_date: date | None, as_of: date) -> int | None:
    if birth_date is None:
        return None
    years = as_of.year - birth_date.year
    if (as_of.month, as_of.day) < (birth_date.month, birth_date.day):
        years -= 1
    return max(years, 0)


def format_age(birth_date: date | None, as_of: date) -> str:
    years = age_years(birth_date, as_of)
    return f"{years}세" if years is not None else "—"


def today_seoul() -> date:
    return datetime.now(tz=SEOUL).date()


def display_race_title(grade: str | None, race_name: str | None) -> str:
    name = (race_name or "").strip()
    label = (grade or "").strip()
    if name and name not in GENERIC_RACE_NAMES:
        return name
    if label:
        return label
    return "일반경주"


def format_finish_position(
    position: int | None,
    *,
    scratched: bool = False,
) -> tuple[str, int, bool]:
    """Return display label, sort key, and whether this is a non-finishing outcome."""

    if position is not None and position > MAX_NORMAL_FINISH:
        return SPECIAL_FINISH_LABELS.get(position, "특수"), 1_000 + position, True
    if scratched:
        return "취소", 2_000, True
    if position is None:
        return "—", 999, False
    return f"{position}위", position, False


def dividend_label(bet_type: str) -> str:
    return DIVIDEND_LABELS.get(bet_type, bet_type)


def group_dates_by_month(dates: list[date]) -> list[tuple[str, list[date]]]:
    groups: list[tuple[str, list[date]]] = []
    current_key = ""
    bucket: list[date] = []
    for item in dates:
        key = f"{item.year}년 {item.month}월"
        if key != current_key:
            if bucket:
                groups.append((current_key, bucket))
            current_key = key
            bucket = [item]
        else:
            bucket.append(item)
    if bucket:
        groups.append((current_key, bucket))
    return groups


def adjacent_dates(dates: list[date], selected: date | None) -> tuple[date | None, date | None]:
    """Return (older, newer) neighbors. `dates` is newest-first."""

    if selected is None or selected not in dates:
        return None, None
    index = dates.index(selected)
    newer = dates[index - 1] if index > 0 else None
    older = dates[index + 1] if index + 1 < len(dates) else None
    return older, newer


def page_window(current: int, total: int, span: int = 2) -> list[int]:
    """Page numbers to render; 0 is an ellipsis marker."""

    if total <= 1:
        return [1] if total == 1 else []
    pages = {1, total, current}
    for offset in range(1, span + 1):
        pages.add(current - offset)
        pages.add(current + offset)
    ordered = [page for page in sorted(pages) if 1 <= page <= total]
    window: list[int] = []
    previous = 0
    for page in ordered:
        if previous and page - previous > 1:
            window.append(0)
        window.append(page)
        previous = page
    return window
