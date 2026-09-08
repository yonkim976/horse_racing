"""Normalize KRA race grade strings into mix class, numeric tier, and OPEN flag."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

MixClass = Literal["국산", "혼합", "제주", "한라"]

_MIX_BY_PREFIX: dict[str, MixClass] = {
    "국": "국산",
    "혼": "혼합",
    "제": "제주",
    "한": "한라",
}

_GRADE_RE = re.compile(
    r"^(국|혼|제|한)?(?:(\d+)(?:등급)?|OPEN|오픈)(?:\s*(?:핸디캡|마령|별정[A-D]?))?$",
    re.IGNORECASE,
)


class ParsedGrade(BaseModel):
    """Structured view of ``races.grade``.

    ``mix`` is None when the string has no 국/혼/제 prefix (or is unparseable).
    ``tier`` is None for OPEN grades and for NULL / blank / unknown input.
    """

    model_config = ConfigDict(frozen=True)

    raw: str | None
    mix: MixClass | None
    tier: int | None
    is_open: bool


def parse_race_grade(raw: str | None) -> ParsedGrade:
    """Parse a KRA grade label without raising on missing or unknown values."""
    if raw is None:
        return ParsedGrade(raw=None, mix=None, tier=None, is_open=False)

    text = raw.strip()
    if not text:
        return ParsedGrade(raw=raw, mix=None, tier=None, is_open=False)

    matched = _GRADE_RE.fullmatch(text)
    if matched is None:
        return ParsedGrade(raw=raw, mix=None, tier=None, is_open=False)

    prefix, digits = matched.groups()
    mix = _MIX_BY_PREFIX.get(prefix) if prefix else None
    if digits is None:
        return ParsedGrade(raw=raw, mix=mix, tier=None, is_open=True)
    return ParsedGrade(raw=raw, mix=mix, tier=int(digits), is_open=False)
