from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from horse_racing.parsers.horse_history import parse_meet_code


class SpecialTrainingItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")


class SwimTrainingItem(SpecialTrainingItem):
    horse_id: str = Field(alias="hrNo")
    horse_name: str = Field(alias="hrName")
    meet_code: int = Field(alias="meet")
    training_date: date = Field(alias="trDate")
    swim_count: int = Field(alias="cnt", ge=0)
    stable_part: int | None = Field(default=None, alias="horsepart")
    stable_note: str | None = Field(default=None, alias="horsepartMemo")
    trainer_part: int | None = Field(default=None, alias="trpart")
    trainer_name: str | None = Field(default=None, alias="trName")

    @field_validator("horse_id", mode="before")
    @classmethod
    def normalize_horse_id(cls, value: Any) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("마번이 비어 있습니다.")
        return cleaned

    @field_validator("horse_name", mode="before")
    @classmethod
    def require_horse_name(cls, value: Any) -> str:
        cleaned = str(value).strip() if value is not None else ""
        return cleaned or "(이름없음)"

    @field_validator("meet_code", mode="before")
    @classmethod
    def parse_meet(cls, value: Any) -> int:
        code = parse_meet_code(value)
        if code is None:
            raise ValueError(f"알 수 없는 경마장: {value!r}")
        return code

    @field_validator("training_date", mode="before")
    @classmethod
    def parse_training_date(cls, value: Any) -> date:
        parsed = _parse_date(value)
        if parsed is None:
            raise ValueError("수영조교일이 비어 있습니다.")
        return parsed

    @field_validator("swim_count", "stable_part", "trainer_part", mode="before")
    @classmethod
    def parse_integer(cls, value: Any) -> int | None:
        return _parse_int(value)

    @field_validator("stable_note", "trainer_name", mode="before")
    @classmethod
    def blank_to_none(cls, value: Any) -> str | None:
        return _blank_to_none(value)

    @property
    def quality_status(self) -> str:
        return "zero_record" if self.swim_count == 0 else "valid"


class HillTrainingItem(SpecialTrainingItem):
    farm_name: str = Field(validation_alias=AliasChoices("areqNm", "areq"))
    tag_id: str | None = Field(default=None, alias="tagId")
    horse_id: str = Field(alias="hrNo")
    horse_name: str = Field(default="(이름없음)", alias="hrNm")
    dam_name: str | None = Field(default=None, alias="moHrNm")
    sire_name: str | None = Field(default=None, alias="faHrNm")
    sex: str | None = Field(default=None, alias="sex")
    birth_date: date | None = Field(default=None, alias="birthday")
    chip_id: str | None = Field(default=None, alias="id")
    training_operator_name: str | None = Field(default=None, alias="ptrNm")
    owner_name: str | None = Field(default=None, alias="owNm")
    farm_entry_date: date | None = Field(default=None, alias="inStDate")
    farm_entry_reason: str | None = Field(default=None, alias="stCause")
    training_date: date = Field(
        validation_alias=AliasChoices("startDate", "startDt")
    )
    training_time: time | None = Field(default=None, alias="startTime")
    f1_seconds: Decimal | None = Field(default=None, alias="firstRecord")
    f2_seconds: Decimal | None = Field(default=None, alias="secRecord")
    f3_seconds: Decimal | None = Field(default=None, alias="thiRecord")
    total_seconds: Decimal | None = Field(default=None, alias="sumRecord")

    @field_validator("farm_name", "horse_id", mode="before")
    @classmethod
    def require_text(cls, value: Any) -> str:
        cleaned = str(value).strip() if value is not None else ""
        if not cleaned:
            raise ValueError("필수 문자열이 비어 있습니다.")
        return cleaned

    @field_validator("horse_name", mode="before")
    @classmethod
    def require_horse_name(cls, value: Any) -> str:
        cleaned = str(value).strip() if value is not None else ""
        return cleaned or "(이름없음)"

    @field_validator("birth_date", "farm_entry_date", mode="before")
    @classmethod
    def parse_optional_date(cls, value: Any) -> date | None:
        return _parse_date(value)

    @field_validator("training_date", mode="before")
    @classmethod
    def parse_training_date(cls, value: Any) -> date:
        parsed = _parse_date(value)
        if parsed is None:
            raise ValueError("언덕주로 조교일이 비어 있습니다.")
        return parsed

    @field_validator("training_time", mode="before")
    @classmethod
    def parse_training_time(cls, value: Any) -> time | None:
        return _parse_time(value)

    @field_validator(
        "f1_seconds",
        "f2_seconds",
        "f3_seconds",
        "total_seconds",
        mode="before",
    )
    @classmethod
    def parse_decimal(cls, value: Any) -> Decimal | None:
        return _parse_decimal(value)

    @field_validator(
        "tag_id",
        "dam_name",
        "sire_name",
        "sex",
        "chip_id",
        "training_operator_name",
        "owner_name",
        "farm_entry_reason",
        mode="before",
    )
    @classmethod
    def blank_to_none(cls, value: Any) -> str | None:
        return _blank_to_none(value)

    @property
    def quality_status(self) -> str:
        records = (
            self.f1_seconds,
            self.f2_seconds,
            self.f3_seconds,
            self.total_seconds,
        )
        if self.total_seconds is None or all(value is None for value in records):
            return "incomplete"
        if any(value is not None and value < 0 for value in records):
            return "invalid_record"
        if self.total_seconds <= 0:
            return "zero_record"
        return "valid"

    @property
    def source_row_hash(self) -> str:
        stable_fields = {
            "farm_name",
            "tag_id",
            "horse_id",
            "horse_name",
            "dam_name",
            "sire_name",
            "sex",
            "birth_date",
            "chip_id",
            "training_operator_name",
            "owner_name",
            "farm_entry_date",
            "farm_entry_reason",
            "training_date",
            "training_time",
            "f1_seconds",
            "f2_seconds",
            "f3_seconds",
            "total_seconds",
        }
        canonical = json.dumps(
            self.model_dump(mode="json", include=stable_fields, exclude_none=False),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def _parse_date(value: Any) -> date | None:
    text = _blank_to_none(value)
    if text is None:
        return None
    for format_string in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, format_string).date()
        except ValueError:
            pass
    raise ValueError(f"날짜 형식을 해석할 수 없습니다: {value!r}")


def _parse_time(value: Any) -> time | None:
    text = _blank_to_none(value)
    if text is None:
        return None
    for format_string in ("%H:%M:%S", "%H%M%S"):
        try:
            return datetime.strptime(text, format_string).time()
        except ValueError:
            pass
    raise ValueError(f"시간 형식을 해석할 수 없습니다: {value!r}")


def _parse_int(value: Any) -> int | None:
    text = _blank_to_none(value)
    if text is None:
        return None
    return int(float(text))


def _parse_decimal(value: Any) -> Decimal | None:
    text = _blank_to_none(value)
    if text is None:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"기록을 숫자로 해석할 수 없습니다: {value!r}") from exc


def _blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned if cleaned and cleaned not in {"-", "null", "None"} else None
