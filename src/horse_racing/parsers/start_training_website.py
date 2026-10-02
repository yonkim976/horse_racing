"""Strict production copy of the reviewed Jeju website table contract.

Source: jeju/research/20261001_starting_training_website_load/
jeju_collect_starting_website.py. Research files remain unchanged.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

EXPECTED = ["소속조", "조번", "마명", "기승자", "조교장소", "비고"]
FIELDS = ["affiliation", "stable_number", "horse_name", "rider", "location", "note"]


class TrainingParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.current = self.cell = None
        self.ids = []
        self.inputs = {}
        self.table_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and "name" in attrs:
            self.inputs[attrs["name"]] = attrs.get("value", "")
        if tag == "table":
            self.table_depth += 1
        if self.table_depth and tag == "tr":
            self.current, self.ids = [], []
        if self.current is not None and tag in ("td", "th"):
            self.cell = []
        if self.current is not None and tag == "a":
            match = re.search(r"goPage1\(\s*['\"]([0-9]+)['\"]\s*\)", attrs.get("onclick", ""))
            if match:
                self.ids.append(match[1])
        if self.cell is not None and tag == "br":
            self.cell.append(" ")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.current.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
            self.cell = None
        if tag == "tr" and self.current is not None:
            self.rows.append((self.current, self.ids))
            self.current = self.cell = None
        if tag == "table":
            self.table_depth = max(0, self.table_depth - 1)


def parse_start_training_website(raw: bytes, label: str) -> list[dict]:
    parser = TrainingParser()
    parser.feed(raw.decode("euc-kr", errors="strict"))
    if parser.inputs.get("trDateReplace") != label:
        raise ValueError("제주 출발조교 홈페이지 날짜 불일치")
    if not any(cells == EXPECTED for cells, _ in parser.rows):
        raise ValueError("제주 출발조교 홈페이지 표 머리글 누락")
    records = []
    for cells, ids in parser.rows:
        if cells == EXPECTED:
            continue
        if len(cells) != 6 or len(ids) != 1 or not re.fullmatch(r"[0-9]{6,7}", ids[0]):
            raise ValueError("제주 출발조교 홈페이지 행 구조 또는 공식 말 ID 불일치")
        match = re.fullmatch(r"(\d+)조", cells[0])
        if not match:
            raise ValueError("제주 출발조교 소속조 형식 불일치")
        record = dict(zip(FIELDS, cells, strict=True))
        record.update(
            horse_id_raw=ids[0], stable_part=int(match[1]), source_row_no=len(records) + 1
        )
        records.append(record)
    return records
