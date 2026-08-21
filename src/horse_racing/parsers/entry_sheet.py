from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from horse_racing.collectors.kra_api import KraApiError, response_body


class EntrySheetItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    meet_name: str = Field(alias="meet")
    race_date: date = Field(alias="rcDate")
    race_number: int = Field(alias="rcNo")
    horse_number: int = Field(alias="chulNo")
    horse_name: str = Field(alias="hrName")
    horse_id: str = Field(alias="hrNo")
    horse_name_en: str | None = Field(default=None, alias="hrNameEn")
    origin_country: str | None = Field(default=None, alias="prd")
    sex: str | None = None
    age: int | None = None
    carried_weight_kg: float | None = Field(default=None, alias="wgBudam")
    rating: float | None = None
    jockey_name: str | None = Field(default=None, alias="jkName")
    jockey_name_en: str | None = Field(default=None, alias="jkNameEn")
    jockey_id: str | None = Field(default=None, alias="jkNo")
    trainer_name: str | None = Field(default=None, alias="trName")
    trainer_name_en: str | None = Field(default=None, alias="trNameEn")
    trainer_id: str | None = Field(default=None, alias="trNo")
    owner_name: str | None = Field(default=None, alias="owName")
    owner_name_en: str | None = Field(default=None, alias="owNameEn")
    owner_id: str | None = Field(default=None, alias="owNo")
    distance_m: int = Field(alias="rcDist")
    grade: str | None = Field(default=None, alias="rank")
    scheduled_time: str | None = Field(default=None, alias="stTime")
    race_name: str | None = Field(default=None, alias="rcName")

    @field_validator("race_date", mode="before")
    @classmethod
    def parse_race_date(cls, value: Any) -> date:
        return datetime.strptime(str(value).strip(), "%Y%m%d").date()

    @field_validator("horse_id", mode="before")
    @classmethod
    def normalize_horse_id(cls, value: Any) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("마번(고유번호)이 비어 있습니다.")
        return cleaned

    @field_validator(
        "race_number",
        "horse_number",
        "age",
        "distance_m",
        mode="before",
    )
    @classmethod
    def parse_integer(cls, value: Any) -> int | None:
        cleaned = _clean_number(value)
        return int(float(cleaned)) if cleaned is not None else None

    @field_validator("carried_weight_kg", "rating", mode="before")
    @classmethod
    def parse_float(cls, value: Any) -> float | None:
        cleaned = _clean_number(value)
        if cleaned is None:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    @field_validator(
        "horse_name_en",
        "origin_country",
        "sex",
        "jockey_name",
        "jockey_name_en",
        "jockey_id",
        "trainer_name",
        "trainer_name_en",
        "trainer_id",
        "owner_name",
        "owner_name_en",
        "owner_id",
        "grade",
        "scheduled_time",
        "race_name",
        mode="before",
    )
    @classmethod
    def blank_to_none(cls, value: Any) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned if cleaned and cleaned != "-" else None


class EntrySheetPage(BaseModel):
    items: list[EntrySheetItem]
    page_no: int
    num_of_rows: int
    total_count: int


def parse_entry_sheet_page(payload: dict[str, Any]) -> EntrySheetPage:
    body = response_body(payload)
    items_container = body.get("items") or {}
    if not isinstance(items_container, dict):
        raise KraApiError("KRA API items 객체 형식이 올바르지 않습니다.")

    raw_items = items_container.get("item", [])
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    if raw_items in (None, ""):
        raw_items = []
    if not isinstance(raw_items, list):
        raise KraApiError("KRA API item 목록 형식이 올바르지 않습니다.")

    return EntrySheetPage(
        items=[EntrySheetItem.model_validate(item) for item in raw_items],
        page_no=int(body.get("pageNo") or 1),
        num_of_rows=int(body.get("numOfRows") or len(raw_items)),
        total_count=int(body.get("totalCount") or len(raw_items)),
    )


def _clean_number(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().replace(",", "")
    return cleaned if cleaned and cleaned != "-" else None
