from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import Field, field_validator

from horse_racing.parsers.race_day import (
    KraItem,
    _parse_date,
    _parse_float,
    _parse_int,
    _text_or_none,
)


@dataclass(frozen=True, slots=True)
class SectionSpec:
    code: str
    time_field: str
    position_field: str | None


MEET_SECTION_SPECS: dict[int, list[SectionSpec]] = {
    1: [
        SectionSpec("S1F", "seS1fAccTime", "sjS1fOrd"),
        SectionSpec("1C", "se_1cAccTime", "sj_1cOrd"),
        SectionSpec("2C", "se_2cAccTime", "sj_2cOrd"),
        SectionSpec("3C", "se_3cAccTime", "sj_3cOrd"),
        SectionSpec("4C", "se_4cAccTime", "sj_4cOrd"),
        SectionSpec("G3F", "seG3fAccTime", "sjG3fOrd"),
        SectionSpec("G1F", "seG1fAccTime", "sjG1fOrd"),
    ],
    2: [
        SectionSpec("S1F", "jeS1fTime", "sjS1fOrd"),
        SectionSpec("1C", "je_1cTime", "sj_1cOrd"),
        SectionSpec("2C", "je_2cTime", "sj_2cOrd"),
        SectionSpec("3C", "je_3cTime", "sj_3cOrd"),
        SectionSpec("4C", "je_4cTime", "sj_4cOrd"),
        SectionSpec("G3F", "jeG3fTime", "sjG3fOrd"),
        SectionSpec("G1F", "jeG1fTime", "sjG1fOrd"),
    ],
    3: [
        SectionSpec("S1F", "buS1fAccTime", "buS1fOrd"),
        SectionSpec("G8F", "buG8fAccTime", "buG8fOrd"),
        SectionSpec("G6F", "buG6fAccTime", "buG6fOrd"),
        SectionSpec("G4F", "buG4fAccTime", "buG4fOrd"),
        SectionSpec("G3F", "buG3fAccTime", "buG3fOrd"),
        SectionSpec("G2F", "buG2fAccTime", "buG2fOrd"),
        SectionSpec("G1F", "buG1fAccTime", "buG1fOrd"),
    ],
}


@dataclass(frozen=True, slots=True)
class ParsedSectionValue:
    section_code: str
    elapsed_time_ms: int | None
    position: int | None


class RaceResultSectionItem(KraItem):
    race_date: date = Field(alias="rcDate")
    race_number: int = Field(alias="rcNo")
    distance_m: int = Field(alias="rcDist")
    horse_number: int = Field(alias="chulNo")
    horse_id: str = Field(alias="hrNo")
    horse_name: str = Field(alias="hrName")
    meet_name: str | None = Field(default=None, alias="meet")

    @field_validator("race_date", mode="before")
    @classmethod
    def parse_race_date(cls, value: Any) -> date:
        return _parse_date(value)

    @field_validator("race_number", "distance_m", "horse_number", mode="before")
    @classmethod
    def parse_integer(cls, value: Any) -> int:
        parsed = _parse_int(value)
        if parsed is None:
            raise ValueError("정수 필드가 비어 있습니다.")
        return parsed

    @field_validator("horse_id", mode="before")
    @classmethod
    def normalize_horse_id(cls, value: Any) -> str:
        cleaned = _text_or_none(value)
        if cleaned is None:
            raise ValueError("마번(고유번호)이 비어 있습니다.")
        return cleaned

    @field_validator("horse_name", mode="before")
    @classmethod
    def normalize_horse_name(cls, value: Any) -> str:
        cleaned = _text_or_none(value)
        if cleaned is None:
            raise ValueError("마명이 비어 있습니다.")
        return cleaned


def section_specs_for_meet(meet: int) -> list[SectionSpec]:
    try:
        return MEET_SECTION_SPECS[meet]
    except KeyError as exc:
        raise ValueError(f"지원하지 않는 경마장 코드입니다: {meet}") from exc


def parse_section_values(item: RaceResultSectionItem, meet: int) -> list[ParsedSectionValue]:
    raw = item.model_dump()
    sections: list[ParsedSectionValue] = []
    for spec in section_specs_for_meet(meet):
        elapsed_time_ms = _seconds_to_ms(raw.get(spec.time_field))
        position = (
            _parse_positive_int(raw.get(spec.position_field)) if spec.position_field else None
        )
        if elapsed_time_ms is None and position is None:
            continue
        sections.append(
            ParsedSectionValue(
                section_code=spec.code,
                elapsed_time_ms=elapsed_time_ms,
                position=position,
            )
        )
    return sections


def _seconds_to_ms(value: Any) -> int | None:
    seconds = _parse_float(value)
    if seconds is None or seconds <= 0:
        return None
    return int(round(seconds * 1000))


def _parse_positive_int(value: Any) -> int | None:
    parsed = _parse_int(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed
