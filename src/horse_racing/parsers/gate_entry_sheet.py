from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from horse_racing.collectors.kra_api import KraApiError, response_body

_KOREAN_DATE = re.compile(r"^(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")
_FIRST_INTEGER = re.compile(r"(\d+)")


class GateEntrySheetItem(BaseModel):
    """Minimal API78 entry-card row needed to verify and store a gate assignment."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    race_date: date = Field(alias="raceDt")
    race_number: int = Field(alias="raceNo")
    gate_number: int = Field(alias="gtno")
    horse_name: str = Field(alias="hrnm")

    @field_validator("race_date", mode="before")
    @classmethod
    def parse_race_date(cls, value: Any) -> date:
        text = str(value).strip()
        matched = _KOREAN_DATE.match(text)
        if matched:
            year, month, day = (int(part) for part in matched.groups())
            return date(year, month, day)
        for pattern in ("%Y%m%d", "%Y.%m.%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, pattern).date()
            except ValueError:
                continue
        raise ValueError(f"출전표 경주일자를 해석할 수 없습니다: {value!r}")

    @field_validator("race_number", "gate_number", mode="before")
    @classmethod
    def parse_positive_integer(cls, value: Any) -> int:
        matched = _FIRST_INTEGER.search(str(value).strip())
        if matched is None or int(matched.group(1)) <= 0:
            raise ValueError(f"양의 번호가 필요합니다: {value!r}")
        return int(matched.group(1))

    @field_validator("horse_name", mode="before")
    @classmethod
    def normalize_horse_name(cls, value: Any) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("마명이 비어 있습니다.")
        return cleaned


class GateEntrySheetPage(BaseModel):
    items: list[GateEntrySheetItem]
    page_no: int
    num_of_rows: int
    total_count: int


def parse_gate_entry_sheet_page(payload: dict[str, Any]) -> GateEntrySheetPage:
    body = response_body(payload)
    items_container = body.get("items") or {}
    if not isinstance(items_container, dict):
        raise KraApiError("API78 출전표 items 객체 형식이 올바르지 않습니다.")

    raw_items = items_container.get("item", [])
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    if raw_items in (None, ""):
        raw_items = []
    if not isinstance(raw_items, list):
        raise KraApiError("API78 출전표 item 목록 형식이 올바르지 않습니다.")

    return GateEntrySheetPage(
        items=[GateEntrySheetItem.model_validate(item) for item in raw_items],
        page_no=int(body.get("pageNo") or 1),
        num_of_rows=int(body.get("numOfRows") or len(raw_items)),
        total_count=int(body.get("totalCount") or len(raw_items)),
    )
