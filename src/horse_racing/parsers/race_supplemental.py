from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import Field, field_validator

from horse_racing.parsers.horse_history import (
    _blank_to_none,
    _parse_float,
    _parse_int,
    _parse_yyyymmdd,
    parse_meet_code,
)
from horse_racing.parsers.race_day import KraItem


class JockeyChangeItem(KraItem):
    horse_id: str = Field(alias="hrNo")
    horse_name: str = Field(default="(이름없음)", alias="hrName")
    meet_code: int = Field(alias="meet")
    race_date: date = Field(alias="rcDate")
    race_number: int = Field(alias="rcNo")
    horse_number: int = Field(alias="chulNo")
    jockey_before_id: str | None = Field(default=None, alias="jkBef")
    jockey_before_name: str | None = Field(default=None, alias="jkBefName")
    jockey_after_id: str | None = Field(default=None, alias="jkAft")
    jockey_after_name: str | None = Field(default=None, alias="jkAftName")
    carried_weight_before_kg: float | None = Field(default=None, alias="befBudam")
    carried_weight_after_kg: float | None = Field(default=None, alias="aftBudam")
    reason: str | None = Field(default=None, alias="reason")

    @field_validator("horse_id", mode="before")
    @classmethod
    def normalize_horse_id(cls, value: Any) -> str:
        return _require_id(value, "마번")

    @field_validator("horse_name", mode="before")
    @classmethod
    def require_name(cls, value: Any) -> str:
        return _require_name(value)

    @field_validator("meet_code", mode="before")
    @classmethod
    def parse_meet(cls, value: Any) -> int:
        return _require_meet(value)

    @field_validator("race_date", mode="before")
    @classmethod
    def parse_date(cls, value: Any) -> date:
        return _parse_yyyymmdd(value)

    @field_validator("race_number", "horse_number", mode="before")
    @classmethod
    def parse_required_int(cls, value: Any) -> int:
        parsed = _parse_int(value)
        if parsed is None:
            raise ValueError(f"정수가 필요합니다: {value!r}")
        return parsed

    @field_validator(
        "jockey_before_id",
        "jockey_after_id",
        "jockey_before_name",
        "jockey_after_name",
        "reason",
        mode="before",
    )
    @classmethod
    def blank_to_none(cls, value: Any) -> str | None:
        return _blank_to_none(value)

    @field_validator(
        "carried_weight_before_kg",
        "carried_weight_after_kg",
        mode="before",
    )
    @classmethod
    def parse_float(cls, value: Any) -> float | None:
        return _parse_float(value)


class RaceScratchItem(KraItem):
    horse_id: str = Field(alias="hrNo")
    horse_name: str = Field(default="(이름없음)", alias="hrName")
    meet_code: int = Field(alias="meet")
    race_date: date = Field(alias="rcDate")
    race_number: int = Field(alias="rcNo")
    horse_number: int | None = Field(default=None, alias="chulNo")
    reason: str | None = Field(default=None, alias="reason")

    @field_validator("horse_id", mode="before")
    @classmethod
    def normalize_horse_id(cls, value: Any) -> str:
        return _require_id(value, "마번")

    @field_validator("horse_name", mode="before")
    @classmethod
    def require_name(cls, value: Any) -> str:
        return _require_name(value)

    @field_validator("meet_code", mode="before")
    @classmethod
    def parse_meet(cls, value: Any) -> int:
        return _require_meet(value)

    @field_validator("race_date", mode="before")
    @classmethod
    def parse_date(cls, value: Any) -> date:
        return _parse_yyyymmdd(value)

    @field_validator("race_number", mode="before")
    @classmethod
    def parse_required_int(cls, value: Any) -> int:
        parsed = _parse_int(value)
        if parsed is None:
            raise ValueError(f"정수가 필요합니다: {value!r}")
        return parsed

    @field_validator("horse_number", mode="before")
    @classmethod
    def parse_optional_int(cls, value: Any) -> int | None:
        return _parse_int(value)

    @field_validator("reason", mode="before")
    @classmethod
    def blank_to_none(cls, value: Any) -> str | None:
        return _blank_to_none(value)


class EntryEquipmentItem(KraItem):
    horse_id: str = Field(alias="hrNo")
    horse_name: str = Field(default="(이름없음)", alias="hrName")
    meet_code: int = Field(alias="meet")
    race_date: date = Field(alias="rcDate")
    race_number: int = Field(alias="rcNo")
    horse_number: int | None = Field(default=None, alias="chulNo")
    equipment_raw: str | None = Field(default=None, alias="toolName")
    bleeding_count: int | None = Field(default=None, alias="bleedingCnt")
    bleeding_date_raw: str | None = Field(default=None, alias="bleedingDate")
    illness_note: str | None = Field(default=None, alias="illName")

    @field_validator("horse_id", mode="before")
    @classmethod
    def normalize_horse_id(cls, value: Any) -> str:
        return _require_id(value, "마번")

    @field_validator("horse_name", mode="before")
    @classmethod
    def require_name(cls, value: Any) -> str:
        return _require_name(value)

    @field_validator("meet_code", mode="before")
    @classmethod
    def parse_meet(cls, value: Any) -> int:
        return _require_meet(value)

    @field_validator("race_date", mode="before")
    @classmethod
    def parse_date(cls, value: Any) -> date:
        return _parse_yyyymmdd(value)

    @field_validator("race_number", mode="before")
    @classmethod
    def parse_required_int(cls, value: Any) -> int:
        parsed = _parse_int(value)
        if parsed is None:
            raise ValueError(f"정수가 필요합니다: {value!r}")
        return parsed

    @field_validator("horse_number", "bleeding_count", mode="before")
    @classmethod
    def parse_optional_int(cls, value: Any) -> int | None:
        return _parse_int(value)

    @field_validator("equipment_raw", "bleeding_date_raw", "illness_note", mode="before")
    @classmethod
    def blank_to_none(cls, value: Any) -> str | None:
        return _blank_to_none(value)


class HorseGradeChangeItem(KraItem):
    horse_id: str = Field(alias="hrNo")
    horse_name: str = Field(default="(이름없음)", alias="hrName")
    meet_code: int | None = Field(default=None, alias="meet")
    blood_type: str | None = Field(default=None, alias="blood")
    grade_before: str | None = Field(default=None, alias="beforeRank")
    grade_after: str | None = Field(default=None, alias="rank")
    start_date: date | None = Field(default=None, alias="stDate")
    end_date: date | None = Field(default=None, alias="spDate")

    @field_validator("horse_id", mode="before")
    @classmethod
    def normalize_horse_id(cls, value: Any) -> str:
        return _require_id(value, "마번")

    @field_validator("horse_name", mode="before")
    @classmethod
    def require_name(cls, value: Any) -> str:
        return _require_name(value)

    @field_validator("meet_code", mode="before")
    @classmethod
    def parse_meet(cls, value: Any) -> int | None:
        return parse_meet_code(value)

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def parse_optional_date(cls, value: Any) -> date | None:
        return _parse_optional_yyyymmdd(value)

    @field_validator("blood_type", "grade_before", "grade_after", mode="before")
    @classmethod
    def blank_to_none(cls, value: Any) -> str | None:
        return _blank_to_none(value)


class StartTrainingItem(KraItem):
    horse_id: str = Field(alias="hrNo")
    horse_name: str = Field(default="(이름없음)", alias="hrName")
    meet_code: int = Field(alias="meet")
    training_date: date = Field(alias="trDate")
    stable_part: int | None = Field(default=None, alias="part")
    stable_number: int | None = Field(default=None, alias="partNo")
    rider_name: str | None = Field(default=None, alias="prName")
    remark: str | None = Field(default=None, alias="remark")

    @field_validator("horse_id", mode="before")
    @classmethod
    def normalize_horse_id(cls, value: Any) -> str:
        return _require_id(value, "마번")

    @field_validator("horse_name", mode="before")
    @classmethod
    def require_name(cls, value: Any) -> str:
        return _require_name(value)

    @field_validator("meet_code", mode="before")
    @classmethod
    def parse_meet(cls, value: Any) -> int:
        return _require_meet(value)

    @field_validator("training_date", mode="before")
    @classmethod
    def parse_date(cls, value: Any) -> date:
        return _parse_yyyymmdd(value)

    @field_validator("stable_part", "stable_number", mode="before")
    @classmethod
    def parse_optional_int(cls, value: Any) -> int | None:
        return _parse_int(value)

    @field_validator("rider_name", "remark", mode="before")
    @classmethod
    def blank_to_none(cls, value: Any) -> str | None:
        return _blank_to_none(value)


class StewardReportItem(KraItem):
    meet_code: int = Field(alias="meet")
    race_date: date = Field(alias="rcDate")
    race_number: int = Field(alias="rcNo")
    weather: str | None = Field(default=None, alias="weather")
    members: str | None = Field(default=None, alias="member")
    judgement: str | None = Field(default=None, alias="judgement")
    additional_judgement: str | None = Field(default=None, alias="addJudgement")
    jockey_change_note: str | None = Field(default=None, alias="jkChange")

    @field_validator("meet_code", mode="before")
    @classmethod
    def parse_meet(cls, value: Any) -> int:
        return _require_meet(value)

    @field_validator("race_date", mode="before")
    @classmethod
    def parse_date(cls, value: Any) -> date:
        return _parse_yyyymmdd(value)

    @field_validator("race_number", mode="before")
    @classmethod
    def parse_required_int(cls, value: Any) -> int:
        parsed = _parse_int(value)
        if parsed is None:
            raise ValueError(f"정수가 필요합니다: {value!r}")
        return parsed

    @field_validator(
        "weather",
        "members",
        "judgement",
        "additional_judgement",
        "jockey_change_note",
        mode="before",
    )
    @classmethod
    def blank_to_none(cls, value: Any) -> str | None:
        return _blank_to_none(value)


def _require_id(value: Any, label: str) -> str:
    cleaned = str(value).strip()
    if not cleaned or cleaned == "-":
        raise ValueError(f"{label}이(가) 비어 있습니다.")
    return cleaned


def _require_name(value: Any) -> str:
    cleaned = str(value).strip() if value is not None else ""
    return cleaned or "(이름없음)"


def _require_meet(value: Any) -> int:
    code = parse_meet_code(value)
    if code is None:
        raise ValueError(f"알 수 없는 경마장: {value!r}")
    return code


def _parse_optional_yyyymmdd(value: Any) -> date | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned or cleaned == "-":
        return None
    return datetime.strptime(cleaned, "%Y%m%d").date()
