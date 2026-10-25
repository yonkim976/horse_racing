"""Literal official day reports and neutral, roster-checked horse references."""

from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup
from lxml import html

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
NUMBER = re.compile("[" + CIRCLED + "]")
QUOTED_NAME = re.compile(r'\s*[“"「]([^“”"」]+)[”"」]')


class StewardSourceError(ValueError):
    """A failed source check is never an empty/no-incident observation."""


def require(ok, reason):
    if not ok:
        raise StewardSourceError(reason)


def lf(value):
    return value.replace("\r\n", "\n").replace("\r", "\n")


def parse_day(body: bytes, *, meet: int, day: date) -> dict[int, dict[str, str]]:
    soup = BeautifulSoup(body, "html.parser")
    node = soup.select_one('form input[name="meet"]')
    require(node is not None and node.get("value") == str(meet), "selected_meet_mismatch")
    # Date selectors contain many historical dates; use only the displayed header.
    headers = [t for t in soup.select("table") if re.search(r"\d{4}년", t.get_text()) and any(
        th.get_text(strip=True) == "경주일자" for th in t.select("th")
    )]
    require(len(headers) == 1, "missing_report_date_header")
    rendered = re.sub(r"\s+", "", headers[0].get_text())
    selected = re.search(r"(\d{4})년(\d{1,2})월(\d{1,2})일", rendered)
    require(selected is not None and tuple(map(int, selected.groups())) ==
            (day.year, day.month, day.day), "selected_date_mismatch")
    reports = {}
    primary = []
    for t in soup.select("table"):
        caption = t.find("caption")
        if caption is None or "심판 상세내용" not in caption.get_text():
            continue
        h = t.select_one("thead th")
        m = re.fullmatch(r"제\s*(\d+)경주", h.get_text(strip=True) if h else "")
        require(m is not None, "invalid_race_heading")
        race = int(m[1])
        require(race not in reports, "duplicate_report_race")
        pres = t.select("tbody pre")
        require(bool(pres), "missing_report_text_cell")
        fields = {}
        for i, pre in enumerate(pres):
            text = pre.get_text()
            key = "judgement" if i == 0 else f"additional_judgement_{i}"
            fields[key] = text
        require(bool(fields["judgement"].strip()), "empty_report_judgement")
        reports[race] = fields
        primary.append((race, [lf(v) for v in fields.values()]))
    # Independent traversal of the same raw bytes, including every additional cell.
    doc = html.fromstring(body)
    secondary = []
    for t in doc.xpath('//table[caption[contains(.,"심판 상세내용")]]'):
        headings = t.xpath("./thead/tr/th[1]")
        require(len(headings) == 1, "independent_missing_heading")
        m = re.fullmatch(r"제\s*(\d+)경주", headings[0].text_content().strip())
        require(m is not None, "independent_invalid_heading")
        secondary.append((int(m[1]), [lf(p.text_content()) for p in t.xpath("./tbody//pre")]))
    require(primary == secondary, "independent_report_parser_mismatch")
    return reports


def name_key(name):
    # Only the known visiting-horse venue prefixes; names never replace an ID.
    return re.sub(r"\s+", "", re.sub(r"^\[(?:부|영남)\]", "", name))


def paragraphs(text):
    markers = list(re.finditer("●", text))
    if not markers:
        return [(0, len(text), text)] if text.strip() else []
    result = []
    if text[:markers[0].start()].strip():
        result.append((0, markers[0].start(), text[:markers[0].start()]))
    for i, marker in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        result.append((marker.start(), end, text[marker.start():end]))
    return result


def link_fields(fields, roster, *, day):
    """Associate literal paragraphs with explicit horse references, without blame."""
    numbers = {}
    for row in roster:
        require(row["horse_number"] not in numbers, "duplicate_operational_horse_number")
        numbers[row["horse_number"]] = row
    links, review, no_reference = [], [], 0
    for field, text in fields.items():
        for start, end, paragraph in paragraphs(text):
            evidence, problems = {}, []
            # Additional comments can refer to a different historical race.
            first_number = NUMBER.search(paragraph)
            prefix = paragraph[:first_number.start()] if first_number else paragraph
            dates = re.findall(r"(20\d{2})[./년]\s*(\d{1,2})[./월]\s*(\d{1,2})", prefix)
            if "경주" in prefix and dates and any(
                date(int(y), int(m), int(d)) < day for y, m, d in dates
            ):
                problems.append("different_date_reference")
            for mention in NUMBER.finditer(paragraph):
                number = CIRCLED.index(mention[0]) + 1
                row = numbers.get(number)
                if row is None:
                    problems.append("horse_number_not_in_operational_roster")
                    continue
                tail = paragraph[mention.end():]
                quoted = QUOTED_NAME.match(tail)
                if quoted:
                    if name_key(quoted[1]) != name_key(row["name_ko"]):
                        problems.append("number_name_disagree")
                        continue
                    basis = "number_and_roster_name"
                else:
                    bare = re.sub(r"\s+", "", tail)
                    # Number-only references are accepted only with a grammatical delimiter.
                    if bare and not (bare.startswith(name_key(row["name_ko"])) or
                                     bare[0] in "번은는이가을를와과,，.·:;()"):
                        problems.append("unverified_bare_name")
                        continue
                    basis = "explicit_number_in_race_roster"
                evidence.setdefault(number, []).append({
                    "basis": basis, "official_horse_id": row["kra_horse_id"],
                    "horse_number": number, "mention_start_codepoint": start + mention.start(),
                    "mention_end_codepoint": start + mention.end(),
                })
            if problems:
                review.append({"field": field, "start": start, "end": end,
                               "reasons": sorted(set(problems))})
                continue
            if not evidence:
                no_reference += 1
            for number, refs in evidence.items():
                row = numbers[number]
                require(text[start:end] == paragraph, "paragraph_span_mismatch")
                links.append({"horse_id": row["horse_id"], "race_entry_id": row["entry_id"],
                              "horse_number": number, "source_field": field,
                              "start": start, "end": end, "paragraph_text": paragraph,
                              "evidence": refs})
    return links, review, no_reference
