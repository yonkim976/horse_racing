from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from horse_racing.collectors.kra_text import KraTextError

_TITLE = re.compile(
    r"^제목\s*:\s*(?P<year>\d{2,4})년\s*(?P<month>\d{1,2})월\s*"
    r"(?P<day>\d{1,2})일.*?제\s*(?P<race>\d+)경주",
    re.MULTILINE,
)
_RACE_META = re.compile(
    r"\((?P<meet>[^)]+)\)\s*제\s*(?P<day_count>\d+)일\s+"
    r"(?P<distance>\d+)M\s+(?P<rest>.+)"
)
_TRACK = re.compile(
    r"날씨\s*:\s*(?P<weather>\S*)\s+주로\s*:\s*(?P<track>\S*)"
    r"(?:\s*\((?P<moisture>[\d.]+)%\))?"
)
_PRIZES = re.compile(r"순위상금\s*:\s*(?P<values>.+)")
_BODY = re.compile(
    r"^(?P<body>\d+)(?:(?:\(\s*(?P<change>[+-]?\d+)\))|(?P<bare_change>[+-]\d+))?\s*"
    r"(?P<time>\d+:\d{2}\.\d)?\s*(?P<tail>.*)$"
)
_PASSING = re.compile(r"(?:^|\s{2,})(?P<passing>(?:[\d^]*\s*-\s*){5}[\d^]+)$")


@dataclass(slots=True)
class Dacom11Entry:
    finish_position: int | None
    finish_rank_raw: str
    horse_number: int
    horse_name: str
    origin_country: str | None
    sex: str | None
    age: int | None
    carried_weight_kg: float | None
    jockey_name: str | None
    trainer_name: str | None
    owner_name: str | None
    rating: float | None
    body_weight_kg: int | None = None
    body_weight_change_kg: int | None = None
    finish_time_ms: int | None = None
    margin_text: str | None = None
    passing_order_raw: str | None = None
    g3f_ms: int | None = None
    s1f_ms: int | None = None
    g1f_ms: int | None = None
    win_odds: float | None = None
    place_odds: float | None = None
    prize_money_krw: int | None = None
    corner_times_ms: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class Dacom11Race:
    race_date: date
    race_number: int
    meet_name: str
    distance_m: int
    race_day_count: int | None
    grade: str | None
    burden_type: str | None
    race_name: str | None
    age_condition: str | None
    rating_condition: str | None
    weather: str | None
    track_condition: str | None
    track_moisture_percent: float | None
    entries: list[Dacom11Entry] = field(default_factory=list)


def parse_dacom11_report(raw: bytes) -> list[Dacom11Race]:
    text = _decode(raw)
    matches = list(_TITLE.finditer(text))
    if not matches:
        raise KraTextError("dacom11 경주 제목을 찾을 수 없습니다.")
    races: list[Dacom11Race] = []
    for index, title in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        races.append(_parse_race_block(text[title.start() : end], title))
    return races


def _parse_race_block(block: str, title: re.Match[str]) -> Dacom11Race:
    year = int(title.group("year"))
    if year < 100:
        year += 2000 if year < 80 else 1900
    race_date = date(year, int(title.group("month")), int(title.group("day")))
    lines = [line.rstrip("\r") for line in block.splitlines()]
    meta_match = next((_RACE_META.search(line) for line in lines if _RACE_META.search(line)), None)
    if meta_match is None:
        raise KraTextError(f"dacom11 경주 메타데이터를 찾을 수 없습니다: {race_date}")
    grade, burden_type, race_name = _parse_meta_rest(meta_match.group("rest"))
    condition_line = next((line for line in lines if "경주조건:" in line), "")
    track_line = next((line for line in lines if "날씨" in line and "주로" in line), "")
    track_match = _TRACK.search(track_line)
    age_condition, rating_condition = _parse_conditions(condition_line)
    prize_values = _parse_prizes(lines)
    entries = _parse_entry_table(lines)
    if not entries:
        raise KraTextError(
            f"dacom11 출전 결과를 찾을 수 없습니다: {race_date} R{title.group('race')}"
        )
    _parse_body_table(lines, entries)
    _parse_section_table(lines, entries)
    for entry in entries:
        if entry.finish_position is not None and 1 <= entry.finish_position <= len(prize_values):
            entry.prize_money_krw = prize_values[entry.finish_position - 1]
    return Dacom11Race(
        race_date=race_date,
        race_number=int(title.group("race")),
        meet_name=meta_match.group("meet").strip(),
        distance_m=int(meta_match.group("distance")),
        race_day_count=int(meta_match.group("day_count")),
        grade=grade,
        burden_type=burden_type,
        race_name=race_name,
        age_condition=age_condition,
        rating_condition=rating_condition,
        weather=_none(track_match.group("weather")) if track_match else None,
        track_condition=_none(track_match.group("track")) if track_match else None,
        track_moisture_percent=(
            float(track_match.group("moisture"))
            if track_match and track_match.group("moisture")
            else None
        ),
        entries=entries,
    )


def _parse_entry_table(lines: list[str]) -> list[Dacom11Entry]:
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if "순위" in line and "부담중량" in line and "조교사" in line
        ),
        None,
    )
    if header_index is None:
        return []
    header = lines[header_index]
    name_start = _display_match_index(header, r"마\s*명")
    origin_start = _display_match_index(header, r"(?:산지|마종)")
    jockey_start = _display_match_index(header, r"기수명")
    trainer_start = _display_match_index(header, r"조교사")
    owner_start = _display_match_index(header, r"마주명")
    rating_start = _display_match_index_or_none(header, r"레이팅")
    name_data_start = max(0, name_start - 3)
    entries: list[Dacom11Entry] = []
    for line in _table_rows(lines, header_index):
        prefix = _display_slice(line, 0, name_data_start)
        prefix_match = re.match(r"^\s*(?P<rank>\S+)\s+(?P<number>\d+)", prefix)
        if prefix_match is None:
            continue
        finish_raw = prefix_match.group("rank")
        horse_number = prefix_match.group("number")
        horse_name = _display_slice(line, name_data_start, origin_start).strip()
        horse_attributes = _display_slice(line, origin_start, jockey_start).split()
        if len(horse_attributes) < 4:
            continue
        origin, sex, age, weight = horse_attributes[:4]
        jockey = _display_slice(line, jockey_start, trainer_start).strip()
        trainer = _display_slice(line, trainer_start, owner_start).strip()
        owner = _display_slice(line, owner_start, rating_start).strip()
        rating = (
            _float_or_none(_display_slice(line, rating_start, None).strip())
            if rating_start is not None
            else None
        )
        entries.append(
            Dacom11Entry(
                finish_position=_finish_position(finish_raw),
                finish_rank_raw=finish_raw,
                horse_number=int(horse_number),
                horse_name=horse_name,
                origin_country=_none(origin),
                sex=_none(sex),
                age=_int_or_none(age),
                carried_weight_kg=_float_or_none(weight),
                jockey_name=_none(jockey),
                trainer_name=_none(trainer),
                owner_name=_none(owner),
                rating=rating,
            )
        )
    return entries


def _parse_body_table(lines: list[str], entries: list[Dacom11Entry]) -> None:
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if "마체중" in line.replace(" ", "")
            and any(label in line.replace(" ", "") for label in ("도착차", "위차"))
        ),
        None,
    )
    if header_index is None:
        return
    by_number = {entry.horse_number: entry for entry in entries}
    for line in _table_rows(lines, header_index):
        prefix = re.match(r"^\s*\S+\s+(?P<number>\d+)\s{2,}(?P<rest>.+)$", line)
        if prefix is None:
            continue
        entry = by_number.get(int(prefix.group("number")))
        if entry is None or not prefix.group("rest").startswith(entry.horse_name):
            continue
        remainder = prefix.group("rest")[len(entry.horse_name) :].strip()
        body = _BODY.match(remainder)
        if body is None:
            continue
        entry.body_weight_kg = _int_or_none(body.group("body"))
        entry.body_weight_change_kg = _int_or_none(
            body.group("change") or body.group("bare_change")
        )
        entry.finish_time_ms = _race_time_ms(body.group("time"))
        tail = body.group("tail").strip()
        passing = _PASSING.search(tail)
        if passing:
            entry.passing_order_raw = passing.group("passing").strip()
            margin = tail[: passing.start()].strip()
            entry.margin_text = margin or None
        else:
            entry.margin_text = tail or None


def _parse_section_table(lines: list[str], entries: list[Dacom11Entry]) -> None:
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if "G-3" in line and "S-1F" in line and "단승식" in line
        ),
        None,
    )
    if header_index is None:
        return
    by_number = {entry.horse_number: entry for entry in entries}
    # Empty fixed-width cells must not shift values into unrelated sections.
    jeju_fixed = lines[header_index].strip() == (
        "순위  마번  G-3F   S-1F   1코너  2코너  3코너  4코너  G-1F   단승식  연승식"
    )
    for line in _table_rows(lines, header_index):
        prefix_match = re.match(r"^\s*\S+\s+(?P<number>\d+)\s+(?P<values>.+)$", line)
        if prefix_match is None:
            continue
        entry = by_number.get(int(prefix_match.group("number")))
        if entry is None:
            continue
        if jeju_fixed:
            times = {}
            offset = 11
            for code in ("G3F", "S1F", "1C", "2C", "3C", "4C", "G1F"):
                # A few special-result rows contain an overflowing negative sentinel.
                sentinel = re.match(r"-\d+:-?\d+\.\d+", line[offset:])
                if sentinel:
                    times[code] = None
                    offset += len(sentinel.group()) + 1
                    continue
                value = line[offset:offset + 7].strip()
                offset += 7
                if value and not re.fullmatch(r"\d+:\d{2}\.\d+", value):
                    raise KraTextError(f"제주 구간 고정폭 형식 불일치: {value!r}")
                times[code] = _section_time_ms(value) if value else None
            entry.g3f_ms, entry.s1f_ms, entry.g1f_ms = (
                times["G3F"], times["S1F"], times["G1F"]
            )
            entry.corner_times_ms = {c: times[c] for c in ("1C", "2C", "3C", "4C")
                                     if times[c] is not None}
            odds = line[offset:].split()
            if len(odds) == 2:
                entry.win_odds, entry.place_odds = map(_float_or_none, odds)
            continue
        values = prefix_match.group("values")
        odds = re.search(r"(?P<win>\d+\.\d+)\s+(?P<place>\d+\.\d+)\s*$", values)
        if odds is not None:
            entry.win_odds = _float_or_none(odds.group("win"))
            entry.place_odds = _float_or_none(odds.group("place"))
            values = values[: odds.start()]
        section_values = re.findall(r"(?:\d+:\d{2}\.\d+|\d+\.\d+)", values)
        if section_values:
            entry.g3f_ms = _section_time_ms(section_values[0])
        if len(section_values) >= 2:
            entry.s1f_ms = _section_time_ms(section_values[1])
        if len(section_values) >= 3:
            entry.g1f_ms = _section_time_ms(section_values[-1])


def _table_rows(lines: list[str], header_index: int) -> list[str]:
    index = header_index + 1
    while index < len(lines) and _is_separator(lines[index]):
        index += 1
    rows: list[str] = []
    while index < len(lines) and not _is_separator(lines[index]):
        if lines[index].strip():
            rows.append(lines[index])
        index += 1
    return rows


def _parse_meta_rest(value: str) -> tuple[str | None, str | None, str | None]:
    chunks = [chunk.strip() for chunk in re.split(r"\s{2,}", value) if chunk.strip()]
    grade = chunks[0] if chunks else None
    burden = chunks[1] if len(chunks) > 1 and not chunks[1].startswith("경주명") else None
    name_chunk = next((chunk for chunk in chunks if chunk.startswith("경주명")), None)
    race_name = name_chunk.split(":", 1)[1].strip() if name_chunk and ":" in name_chunk else None
    if grade:
        combined = re.match(
            r"(?P<grade>(?:국|혼|제)?\d+등급|(?:국|혼)?OPEN)"
            r"(?P<burden>핸디캡|별정\S*)?",
            grade,
        )
        if combined:
            grade = combined.group("grade")
            burden = combined.group("burden") or burden
    if race_name is None and len(chunks) > 1 and chunks[-1] != burden:
        race_name = chunks[-1]
    return grade, burden, race_name


def _parse_conditions(value: str) -> tuple[str | None, str | None]:
    if "경주조건:" not in value:
        return None, None
    content = value.split("경주조건:", 1)[1].split("날씨:", 1)[0].strip()
    rating_match = re.search(r"R\s*([\d~]+)", content)
    rating = f"R{rating_match.group(1)}" if rating_match else None
    without_rating = re.sub(r"R\s*[\d~]+", "", content).strip()
    return _none(without_rating), rating


def _parse_prizes(lines: list[str]) -> list[int]:
    line = next((line for line in lines if re.search(r"순위상금\s*:", line)), "")
    matched = _PRIZES.search(line)
    if matched is None:
        return []
    multiplier = 10_000 if "만원" in matched.group("values") else 1000
    return [
        int(value.replace(",", "")) * multiplier
        for value in re.findall(r"[\d,]+", matched.group("values"))
    ]


def _finish_position(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    labels = {"제외": 91, "중지": 92, "실격": 93, "취소": 99}
    return labels.get(value)


def _race_time_ms(value: str | None) -> int | None:
    if not value:
        return None
    minutes, seconds = value.split(":", 1)
    return int(round((int(minutes) * 60 + float(seconds)) * 1000))


def _section_time_ms(value: str | None) -> int | None:
    if not value:
        return None
    if ":" in value:
        return _race_time_ms(value)
    try:
        return int(round(float(value) * 1000))
    except ValueError:
        return None


def _is_separator(value: str) -> bool:
    stripped = value.strip()
    return len(stripped) >= 10 and set(stripped) <= {"-", "─", "━", "="}


def _none(value: str | None) -> str | None:
    cleaned = value.strip() if value else ""
    return cleaned or None


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def _float_or_none(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _decode(raw: bytes) -> str:
    for encoding in ("cp949", "euc-kr", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise KraTextError("dacom11 파일 인코딩을 해석할 수 없습니다.")


def _display_index(value: str, needle: str) -> int:
    character_index = value.index(needle)
    return sum(_display_width(character) for character in value[:character_index])


def _display_match_index(value: str, pattern: str) -> int:
    matched = re.search(pattern, value)
    if matched is None:
        raise KraTextError(f"dacom11 표 헤더에서 {pattern!r} 열을 찾을 수 없습니다: {value}")
    return sum(_display_width(character) for character in value[: matched.start()])


def _display_match_index_or_none(value: str, pattern: str) -> int | None:
    matched = re.search(pattern, value)
    if matched is None:
        return None
    return sum(_display_width(character) for character in value[: matched.start()])


def _display_slice(value: str, start: int, end: int | None) -> str:
    output: list[str] = []
    position = 0
    for character in value:
        next_position = position + _display_width(character)
        if next_position > start and (end is None or position < end):
            output.append(character)
        if end is not None and position >= end:
            break
        position = next_position
    return "".join(output)


def _display_width(value: str) -> int:
    return 2 if unicodedata.east_asian_width(value) in {"W", "F", "A"} else 1
