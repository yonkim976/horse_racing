"""Independent BeautifulSoup reader for KRA dated daily-training detail pages."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup


class OfficialPageError(ValueError):
    pass


EXPECTED_HEADER = ("순", "조", "조번", "마명", "기승자", "비고", "입장시각", "퇴장시각", "조교시간")
OFFICIAL_LEGEND = ("조:조교사", "관:주로조교", "생:교육생", "이름(트):기수트랙라이더")
ENDPOINT = "https://race.kra.co.kr/trainer/dailyAllTrainDetail.do"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise OfficialPageError(message)


def _text(cell) -> str:
    return " ".join(cell.stripped_strings)


def _minute(value: str) -> int | None:
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value)
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def parse_page(raw: bytes, expected_date: str) -> dict:
    """Validate official request context and parse every nine-cell data row."""
    html = None
    encoding = None
    for candidate in ("cp949", "euc-kr", "utf-8"):
        try:
            html = raw.decode(candidate, errors="strict")
            encoding = candidate
            break
        except (UnicodeDecodeError, LookupError):
            continue
    require(html is not None, "Official page is not strict CP949/EUC-KR/UTF-8 HTML")
    soup = BeautifulSoup(html, "html.parser")
    page_text = " ".join(soup.stripped_strings)
    require("전체 일별상세조교현황" in page_text, "Official daily-detail title missing")
    require("기승자범례" in page_text and all(token in page_text for token in OFFICIAL_LEGEND),
            "Official rider legend is missing or incomplete")

    form_values: dict[str, list[str]] = {}
    for element in soup.find_all("input"):
        name = element.get("name")
        if name in {"meet", "Act", "Sub", "trDate", "trDateReplace"}:
            form_values.setdefault(name, []).append(element.get("value", ""))
    require(set(form_values.get("meet", [])) == {"2"}, "Response meet does not identify Jeju")
    require(set(form_values.get("trDate", [])) == {expected_date.replace("-", "/")},
            "Response form date differs from requested date")
    if form_values.get("Act"):
        require(set(form_values["Act"]) == {"10"}, "Response Act value mismatch")
    if form_values.get("Sub"):
        require(set(form_values["Sub"]) == {"3"}, "Response Sub value mismatch")
    if form_values.get("trDateReplace"):
        require(set(form_values["trDateReplace"]) == {expected_date.replace("-", "")},
                "Response compact date mismatch")

    matching_tables = []
    for table_index, table in enumerate(soup.find_all("table")):
        rows = table.find_all("tr")
        for header_index, row in enumerate(rows):
            cells = row.find_all(["th", "td"], recursive=False)
            header = tuple(re.sub(r"\s+", "", _text(cell)) for cell in cells)
            if header == EXPECTED_HEADER:
                matching_tables.append((table_index, rows, header_index))
                break
    require(len(matching_tables) == 1,
            f"Expected exactly one nine-column official table; found {len(matching_tables)}")

    table_index, rows, header_index = matching_tables[0]
    # The collector records document-wide <tr> positions, not positions within
    # the detail table. Preserve the same evidence key while parsing through a
    # separate BeautifulSoup implementation.
    global_row_numbers = {id(tr): index for index, tr in enumerate(soup.find_all("tr"), start=1)}
    parsed_rows = []
    ignored_rows = 0
    invalid_timing_rows = []
    for tr in rows[header_index + 1:]:
        row_number = global_row_numbers[id(tr)]
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) != 9:
            continue
        values = [_text(cell) for cell in cells]
        if not values[0].isdigit():
            ignored_rows += 1
            continue
        horse_cell = cells[3]
        onclick_text = " ".join(anchor.get("onclick", "") for anchor in horse_cell.find_all("a"))
        href_text = " ".join(anchor.get("href", "") for anchor in horse_cell.find_all("a"))
        horse_ids = []
        for source in (onclick_text, href_text):
            horse_ids.extend(re.findall(r"goPage4\s*\(\s*['\"]?(\d+)['\"]?\s*\)", source))
        require(len(horse_ids) == 1,
                f"Data row lacks one official horse ID link: table {table_index}, row {row_number}")

        start_raw, end_raw = values[6], values[7]
        duration_raw = values[8]
        duration_match = re.fullmatch(r"\s*(\d+)\s*분\s*", duration_raw)
        start_minute, end_minute = _minute(start_raw), _minute(end_raw)
        duration_seconds = int(duration_match.group(1)) * 60 if duration_match else None
        timing_valid = (
            start_minute is not None and end_minute is not None and duration_seconds is not None
            and duration_seconds > 0 and end_minute >= start_minute
            and (end_minute - start_minute) * 60 == duration_seconds
        )
        row = {
            "horse_id": next(iter(horse_ids)),
            "date": expected_date,
            "label": values[4],
            "start": f"{start_raw[:2]}:{start_raw[3:]}" if timing_valid else None,
            "end": f"{end_raw[:2]}:{end_raw[3:]}" if timing_valid else None,
            "duration_seconds": duration_seconds if timing_valid else None,
            "row_number": row_number,
            "timing_valid": timing_valid,
            "start_raw": start_raw,
            "end_raw": end_raw,
            "duration_raw": duration_raw,
        }
        parsed_rows.append(row)
        if not timing_valid:
            invalid_timing_rows.append({"row_number": row_number, "horse_id": row["horse_id"],
                                        "label": row["label"]})
    return {
        "date": expected_date,
        "encoding": encoding,
        "form_fields": {key: values[0] for key, values in form_values.items()},
        "rows": parsed_rows,
        "row_count": len(parsed_rows),
        "ignored_rows": ignored_rows,
        "invalid_timing_rows": invalid_timing_rows,
    }


def classify_label(label: str, official_jockey_names: set[str]) -> tuple[str, str | None]:
    """Use only an explicit official role marker or exact API307 name membership."""
    if label in ("", "-", "외", "경주일"):
        return "미분류", None
    for token, kind in (("조", "조교사"), ("관", "주로조교"),
                        ("생", "교육생"), ("트", "기수트랙라이더")):
        if (label == token and token != "트") or label.endswith(f"({token})"):
            return kind, None
    if label in official_jockey_names:
        return "기수", label
    return "미분류", None
