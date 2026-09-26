from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any

from pydantic import Field, field_validator

from horse_racing.parsers.race_day import KraItem, _parse_date, _parse_int, _text_or_none


class RacePassingSummaryItem(KraItem):
    race_date: date = Field(alias="rcDate")
    race_number: int = Field(alias="rcNo")
    meet_name: str | None = Field(default=None, alias="meet")
    corner_1_raw: str | None = Field(default=None, alias="corner_1")
    corner_2_raw: str | None = Field(default=None, alias="corner_2")
    corner_3_raw: str | None = Field(default=None, alias="corner_3")
    corner_4_raw: str | None = Field(default=None, alias="corner_4")
    corner_5_raw: str | None = Field(default=None, alias="corner_5")
    corner_6_raw: str | None = Field(default=None, alias="corner_6")
    corner_7_raw: str | None = Field(default=None, alias="corner_7")
    corner_8_raw: str | None = Field(default=None, alias="corner_8")
    corner_9_raw: str | None = Field(default=None, alias="corner_9")
    pass_time_3f_raw: str | None = Field(default=None, alias="passtime_3f")
    pass_time_4f_raw: str | None = Field(default=None, alias="passtime_4f")
    tempo_raw: str | None = Field(default=None, alias="tempo")

    @field_validator("race_date", mode="before")
    @classmethod
    def parse_race_date(cls, value: Any) -> date:
        return _parse_date(value)

    @field_validator("race_number", mode="before")
    @classmethod
    def parse_race_number(cls, value: Any) -> int:
        parsed = _parse_int(value)
        if parsed is None or parsed <= 0:
            raise ValueError("경주번호가 올바르지 않습니다.")
        return parsed

    @field_validator(
        "meet_name",
        "corner_1_raw",
        "corner_2_raw",
        "corner_3_raw",
        "corner_4_raw",
        "corner_5_raw",
        "corner_6_raw",
        "corner_7_raw",
        "corner_8_raw",
        "corner_9_raw",
        "pass_time_3f_raw",
        "pass_time_4f_raw",
        "tempo_raw",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: Any) -> str | None:
        return _text_or_none(value)

    @property
    def tempo_level(self) -> int | None:
        return {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5}.get(self.tempo_raw or "")

    @property
    def pass_time_3f_ms(self) -> int | None:
        return parse_elapsed_ms(self.pass_time_3f_raw)

    @property
    def pass_time_4f_ms(self) -> int | None:
        return parse_elapsed_ms(self.pass_time_4f_raw)

    @property
    def quality_status(self) -> str:
        meaningful_corners = [
            value
            for value in self.corner_values
            if value is not None and value not in {"-", "X"}
        ]
        return "valid" if meaningful_corners or self.tempo_level is not None else "incomplete"

    @property
    def corner_values(self) -> tuple[str | None, ...]:
        return tuple(getattr(self, f"corner_{index}_raw") for index in range(1, 10))

    @property
    def source_row_hash(self) -> str:
        payload = {
            "race_date": self.race_date.isoformat(),
            "race_number": self.race_number,
            "meet_name": self.meet_name,
            **{f"corner_{index}": value for index, value in enumerate(self.corner_values, 1)},
            "passtime_3f": self.pass_time_3f_raw,
            "passtime_4f": self.pass_time_4f_raw,
            "tempo": self.tempo_raw,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def parse_elapsed_ms(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.fullmatch(r"(?:(?P<minutes>\d+):)?(?P<seconds>\d+(?:\.\d+)?)", value.strip())
    if match is None:
        return None
    minutes = int(match.group("minutes") or 0)
    seconds = float(match.group("seconds"))
    if seconds >= 60:
        return None
    elapsed_ms = int(round((minutes * 60 + seconds) * 1000))
    return elapsed_ms if elapsed_ms > 0 else None
