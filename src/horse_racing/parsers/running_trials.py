from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_TITLE_RE = re.compile(
    r"(?P<year>\d{2,4})년\s*(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일"
    r".*?제\s*(?P<round>\d+)차\s*주행심사성적\s*제\s*0*(?P<race>\d+)경주"
    r"(?:\s+(?P<distance>[\d,]+)M)?"
)
_TRACK_RE = re.compile(
    r"날\s*씨\s*:\s*(?P<weather>\S+).*?주로상태\s*:\s*(?P<condition>\S+)"
    r"(?:\s*\((?P<moisture>[\d.]+)%\))?"
)
_TIME_RE = re.compile(r"^(?:\d+:)?\d+\.\d+$")
_JUDGEMENTS = {"합", "불", "유", "연", "출", "심", "주"}
_SEXES = {"암", "수", "거"}


@dataclass(slots=True)
class RunningTrialResultData:
    horse_number: int
    horse_name: str
    finish_position: int | None = None
    finish_rank_raw: str | None = None
    origin_country: str | None = None
    sex: str | None = None
    age: int | None = None
    carried_weight_base_kg: float | None = None
    carried_weight_extra_kg: float | None = None
    carried_weight_raw: str | None = None
    jockey_name: str | None = None
    trainer_name: str | None = None
    body_weight_kg: int | None = None
    finish_time_ms: int | None = None
    margin_text: str | None = None
    judgement: str | None = None
    failure_reason: str | None = None
    inspection_reason: str | None = None
    g3f_ms: int | None = None
    s1f_ms: int | None = None
    corner_3_ms: int | None = None
    corner_4_ms: int | None = None
    g1f_ms: int | None = None
    section_400_ms: int | None = None
    final_400_ms: int | None = None
    passing_order_raw: str | None = None


@dataclass(slots=True)
class RunningTrialData:
    trial_date: date
    trial_round: int
    trial_race_number: int
    distance_m: int
    weather: str | None
    track_condition: str | None
    track_moisture_percent: float | None
    results: list[RunningTrialResultData]


def decode_running_trial_report(payload: bytes) -> str:
    for encoding in ("cp949", "euc-kr", "utf-8"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("cp949", errors="replace")


def parse_running_trial_report(payload: bytes | str, *, meet: int) -> list[RunningTrialData]:
    if meet not in {1, 2, 3}:
        raise ValueError("주행심사 meet는 1(서울), 2(제주), 3(부산경남)이어야 합니다.")
    text = decode_running_trial_report(payload) if isinstance(payload, bytes) else payload
    blocks = re.split(r"(?=^제목\s*:)", text.replace("\r\n", "\n"), flags=re.MULTILINE)
    parsed: list[RunningTrialData] = []
    for block in blocks:
        title = _TITLE_RE.search(block)
        if title is None:
            continue
        year = int(title.group("year"))
        if year < 100:
            year += 2000
        trial_date = date(year, int(title.group("month")), int(title.group("day")))
        distance_text = title.group("distance")
        distance_m = (
            int(distance_text.replace(",", ""))
            if distance_text
            else (800 if meet == 2 else 1000)
        )

        track = _TRACK_RE.search(block.replace("\n", " "))
        weather = track.group("weather") if track else None
        track_condition = track.group("condition") if track else None
        moisture = float(track.group("moisture")) if track and track.group("moisture") else None

        lines = block.splitlines()
        metadata_rows = _parse_metadata_rows(lines)
        result_rows = _parse_result_rows(lines, field_size=len(metadata_rows))
        section_rows = _parse_section_rows(lines)

        results: list[RunningTrialResultData] = []
        for horse_number, metadata in metadata_rows.items():
            result = result_rows.get(horse_number, {})
            section = section_rows.get(horse_number, {})
            results.append(
                RunningTrialResultData(
                    horse_number=horse_number,
                    horse_name=str(metadata["horse_name"]),
                    origin_country=_as_optional_str(metadata.get("origin_country")),
                    sex=_as_optional_str(metadata.get("sex")),
                    age=_as_optional_int(metadata.get("age")),
                    carried_weight_base_kg=_as_optional_float(
                        metadata.get("carried_weight_base_kg")
                    ),
                    carried_weight_extra_kg=_as_optional_float(
                        metadata.get("carried_weight_extra_kg")
                    ),
                    carried_weight_raw=_as_optional_str(metadata.get("carried_weight_raw")),
                    jockey_name=_as_optional_str(metadata.get("jockey_name")),
                    trainer_name=_as_optional_str(metadata.get("trainer_name")),
                    finish_position=_as_optional_int(result.get("finish_position")),
                    finish_rank_raw=_as_optional_str(result.get("finish_rank_raw")),
                    body_weight_kg=_as_optional_int(result.get("body_weight_kg")),
                    finish_time_ms=_as_optional_int(result.get("finish_time_ms")),
                    margin_text=_as_optional_str(result.get("margin_text")),
                    judgement=_as_optional_str(result.get("judgement")),
                    failure_reason=_as_optional_str(result.get("failure_reason")),
                    inspection_reason=_as_optional_str(result.get("inspection_reason")),
                    g3f_ms=_as_optional_int(section.get("g3f_ms")),
                    s1f_ms=_as_optional_int(section.get("s1f_ms")),
                    corner_3_ms=_as_optional_int(section.get("corner_3_ms")),
                    corner_4_ms=_as_optional_int(section.get("corner_4_ms")),
                    g1f_ms=_as_optional_int(section.get("g1f_ms")),
                    section_400_ms=_as_optional_int(section.get("section_400_ms")),
                    final_400_ms=_as_optional_int(section.get("final_400_ms")),
                    passing_order_raw=_as_optional_str(section.get("passing_order_raw")),
                )
            )

        parsed.append(
            RunningTrialData(
                trial_date=trial_date,
                trial_round=int(title.group("round")),
                trial_race_number=int(title.group("race")),
                distance_m=distance_m,
                weather=weather,
                track_condition=track_condition,
                track_moisture_percent=moisture,
                results=results,
            )
        )
    if not parsed:
        raise ValueError("주행심사 보고서에서 경주 블록을 찾지 못했습니다.")
    return parsed


def _parse_metadata_rows(lines: list[str]) -> dict[int, dict[str, object]]:
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if "마    명" in line and "연령" in line and "기수명" in line
        ),
        None,
    )
    if header_index is None:
        return {}
    rows: dict[int, dict[str, object]] = {}
    for line in _table_rows(lines, header_index):
        tokens = line.split()
        if len(tokens) < 8 or not tokens[0].isdigit() or not tokens[1].isdigit():
            continue
        middle = tokens[3:-2]
        sex_index = next((i for i, token in enumerate(middle) if token in _SEXES), None)
        if sex_index is None or sex_index + 1 >= len(middle):
            continue
        weight_raw = "".join(middle[sex_index + 2 :]) or None
        base_weight, extra_weight = _parse_carried_weight(weight_raw)
        horse_number = int(tokens[1])
        rows[horse_number] = {
            "horse_name": tokens[2],
            "origin_country": " ".join(middle[:sex_index]) or None,
            "sex": middle[sex_index],
            "age": int(middle[sex_index + 1]),
            "carried_weight_base_kg": base_weight,
            "carried_weight_extra_kg": extra_weight,
            "carried_weight_raw": weight_raw,
            "jockey_name": tokens[-2],
            "trainer_name": tokens[-1],
        }
    return rows


def _parse_result_rows(
    lines: list[str], *, field_size: int
) -> dict[int, dict[str, object]]:
    header_index = next(
        (index for index, line in enumerate(lines) if "마체중" in line and "불합격사유" in line),
        None,
    )
    if header_index is None:
        return {}
    rows: dict[int, dict[str, object]] = {}
    for line in _table_rows(lines, header_index):
        tokens = line.split()
        if len(tokens) < 5 or not tokens[0].isdigit() or not tokens[1].isdigit():
            continue
        judgement_index = next(
            (index for index, token in enumerate(tokens[4:], start=4) if token in _JUDGEMENTS),
            None,
        )
        if judgement_index is None:
            continue
        raw_rank = tokens[0]
        numeric_rank = int(raw_rank)
        pre_judgement = tokens[4:judgement_index]
        finish_time = next((token for token in pre_judgement if _TIME_RE.match(token)), None)
        margin_tokens = [token for token in pre_judgement if token != finish_time]
        post_judgement = tokens[judgement_index + 1 :]
        failure_reason = " ".join(post_judgement[:-1]) or None if len(post_judgement) > 1 else None
        inspection_reason = post_judgement[-1] if post_judgement else None
        rows[int(tokens[1])] = {
            "finish_position": numeric_rank if 1 <= numeric_rank <= field_size else None,
            "finish_rank_raw": raw_rank,
            "body_weight_kg": int(tokens[3]) or None,
            "finish_time_ms": _parse_elapsed_ms(finish_time),
            "margin_text": " ".join(margin_tokens) or None,
            "judgement": tokens[judgement_index],
            "failure_reason": failure_reason,
            "inspection_reason": inspection_reason,
        }
    return rows


def _parse_section_rows(lines: list[str]) -> dict[int, dict[str, object]]:
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if "G-3" in line and ("G-1F" in line or "G-1Ｆ" in line)
        ),
        None,
    )
    if header_index is None:
        return {}
    busan_layout = "S1F-G3F" in lines[header_index]
    rows: dict[int, dict[str, object]] = {}
    for line in _table_rows(lines, header_index):
        prefix = re.match(r"^\s*\d+\s+(\d+)\s+(.*)$", line)
        if prefix is None:
            continue
        horse_number = int(prefix.group(1))
        payload = prefix.group(2).strip()
        metrics = re.findall(r"(?:\d+:)?\d+\.\d+", payload)
        passing_match = re.search(r"(?:^|\s)(\d+\s*-.*?)(?=\s+(?:\d+:)?\d+\.\d+|$)", payload)
        passing_order = passing_match.group(1).strip() if passing_match else None
        row: dict[str, object] = {"passing_order_raw": passing_order}
        if busan_layout and len(metrics) >= 5:
            row.update(
                {
                    "s1f_ms": _parse_elapsed_ms(metrics[0]),
                    "section_400_ms": _parse_elapsed_ms(metrics[1]),
                    "final_400_ms": _parse_elapsed_ms(metrics[2]),
                    "g3f_ms": _parse_elapsed_ms(metrics[3]),
                    "g1f_ms": _parse_elapsed_ms(metrics[4]),
                }
            )
        elif len(metrics) >= 5:
            row.update(
                {
                    "g3f_ms": _parse_elapsed_ms(metrics[0]),
                    "s1f_ms": _parse_elapsed_ms(metrics[1]),
                    "corner_3_ms": _parse_elapsed_ms(metrics[2]),
                    "corner_4_ms": _parse_elapsed_ms(metrics[3]),
                    "g1f_ms": _parse_elapsed_ms(metrics[4]),
                }
            )
        rows[horse_number] = row
    return rows


def _table_rows(lines: list[str], header_index: int) -> list[str]:
    start = next(
        (index + 1 for index in range(header_index + 1, len(lines)) if _is_rule(lines[index])),
        len(lines),
    )
    end = next(
        (index for index in range(start, len(lines)) if _is_rule(lines[index])),
        len(lines),
    )
    return lines[start:end]


def _is_rule(line: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= 20 and set(stripped) == {"-"}


def _parse_carried_weight(value: str | None) -> tuple[float | None, float | None]:
    if value is None:
        return None, None
    match = re.match(r"(?P<base>\d+(?:\.\d+)?)(?:\+(?P<extra>\d+(?:\.\d+)?))?", value)
    if match is None:
        return None, None
    base = float(match.group("base"))
    extra = float(match.group("extra")) if match.group("extra") else None
    return base, extra


def _parse_elapsed_ms(value: str | None) -> int | None:
    if not value:
        return None
    if ":" in value:
        minutes, seconds = value.split(":", 1)
        return int(round((int(minutes) * 60 + float(seconds)) * 1000))
    return int(round(float(value) * 1000))


def _as_optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


def _as_optional_int(value: object) -> int | None:
    return int(value) if value is not None else None


def _as_optional_float(value: object) -> float | None:
    return float(value) if value is not None else None
