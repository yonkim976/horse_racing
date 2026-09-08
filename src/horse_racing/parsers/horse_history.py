from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import Field, field_validator

from horse_racing.parsers.race_day import KraItem

MEET_NAME_TO_CODE = {
    "서울": 1,
    "제주": 2,
    "부산": 3,
    "부산경남": 3,
    "부경": 3,
    "영남": 3,
    "영천": 4,
}


class HorseRatingItem(KraItem):
    horse_id: str = Field(alias="hrNo")
    horse_name: str = Field(alias="hrName")
    meet_code: int | None = Field(default=None, alias="meet")
    rating_1: float | None = Field(default=None, alias="rating1")
    rating_2: float | None = Field(default=None, alias="rating2")
    rating_3: float | None = Field(default=None, alias="rating3")
    rating_4: float | None = Field(default=None, alias="rating4")

    @field_validator("horse_id", mode="before")
    @classmethod
    def normalize_horse_id(cls, value: Any) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("마번이 비어 있습니다.")
        return cleaned

    @field_validator("horse_name", mode="before")
    @classmethod
    def require_name(cls, value: Any) -> str:
        cleaned = str(value).strip() if value is not None else ""
        return cleaned or "(이름없음)"

    @field_validator("meet_code", mode="before")
    @classmethod
    def parse_meet(cls, value: Any) -> int | None:
        return parse_meet_code(value)

    @field_validator("rating_1", "rating_2", "rating_3", "rating_4", mode="before")
    @classmethod
    def parse_float(cls, value: Any) -> float | None:
        return _parse_float(value)


class HorseWeightItem(KraItem):
    horse_id: str = Field(alias="hrNo")
    horse_name: str = Field(alias="hrName")
    meet_code: int = Field(alias="meet")
    race_date: date = Field(alias="rcDate")
    race_number: int | None = Field(default=None, alias="rcNo")
    horse_number: int | None = Field(default=None, alias="chulNo")
    body_weight_kg: int | None = Field(default=None, alias="wgHr")
    body_weight_change_kg: int | None = Field(default=None, alias="wgHrDiff")

    @field_validator("horse_id", mode="before")
    @classmethod
    def normalize_horse_id(cls, value: Any) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("마번이 비어 있습니다.")
        return cleaned

    @field_validator("horse_name", mode="before")
    @classmethod
    def require_name(cls, value: Any) -> str:
        cleaned = str(value).strip() if value is not None else ""
        return cleaned or "(이름없음)"

    @field_validator("meet_code", mode="before")
    @classmethod
    def parse_meet(cls, value: Any) -> int:
        code = parse_meet_code(value)
        if code is None:
            raise ValueError(f"알 수 없는 경마장: {value!r}")
        return code

    @field_validator("race_date", mode="before")
    @classmethod
    def parse_date(cls, value: Any) -> date:
        return _parse_yyyymmdd(value)

    @field_validator(
        "race_number",
        "horse_number",
        "body_weight_kg",
        "body_weight_change_kg",
        mode="before",
    )
    @classmethod
    def parse_int(cls, value: Any) -> int | None:
        return _parse_int(value)


class HorseTrainingItem(KraItem):
    horse_id: str = Field(alias="hrNo")
    horse_name: str = Field(alias="hrName")
    meet_code: int = Field(alias="meet")
    training_date: date = Field(alias="trDate")
    stable_part: int | None = Field(default=None, alias="part")
    stable_number: int | None = Field(default=None, alias="partNo")
    trainer_name: str | None = Field(default=None, alias="trName")
    rider_type: str | None = Field(default=None, alias="prGubun")
    rider_id: str | None = Field(default=None, alias="prNo")
    started_at_raw: str | None = Field(default=None, alias="stTime")
    ended_at_raw: str | None = Field(default=None, alias="spTime")
    duration_seconds: int | None = Field(default=None, alias="trTerm")
    canter_count: int | None = Field(default=None, alias="run1Cnt")
    gallop_count: int | None = Field(default=None, alias="run2Cnt")
    entry_plan: str | None = Field(default=None, alias="chulGubun")

    @field_validator("horse_id", mode="before")
    @classmethod
    def normalize_horse_id(cls, value: Any) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("마번이 비어 있습니다.")
        return cleaned

    @field_validator("horse_name", mode="before")
    @classmethod
    def require_name(cls, value: Any) -> str:
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
    def parse_date(cls, value: Any) -> date:
        return _parse_yyyymmdd(value)

    @field_validator(
        "stable_part",
        "stable_number",
        "duration_seconds",
        "canter_count",
        "gallop_count",
        mode="before",
    )
    @classmethod
    def parse_int(cls, value: Any) -> int | None:
        return _parse_int(value)

    @field_validator(
        "trainer_name",
        "rider_type",
        "rider_id",
        "started_at_raw",
        "ended_at_raw",
        "entry_plan",
        mode="before",
    )
    @classmethod
    def blank_to_none(cls, value: Any) -> str | None:
        return _blank_to_none(value)


class HorseMedicalItem(KraItem):
    horse_id: str = Field(alias="hrNo")
    horse_name: str = Field(alias="hrName")
    meet_code: int = Field(alias="meet")
    clinic_date: date = Field(alias="clinicDate")
    stable_part: int | None = Field(default=None, alias="part")
    hospital_name: str | None = Field(default=None, alias="hospiName")
    diagnosis_1: str | None = Field(default=None, alias="illName1")
    diagnosis_2: str | None = Field(default=None, alias="illName2")

    @field_validator("horse_id", mode="before")
    @classmethod
    def normalize_horse_id(cls, value: Any) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("마번이 비어 있습니다.")
        return cleaned

    @field_validator("horse_name", mode="before")
    @classmethod
    def require_name(cls, value: Any) -> str:
        cleaned = str(value).strip() if value is not None else ""
        return cleaned or "(이름없음)"

    @field_validator("meet_code", mode="before")
    @classmethod
    def parse_meet(cls, value: Any) -> int:
        code = parse_meet_code(value)
        if code is None:
            raise ValueError(f"알 수 없는 경마장: {value!r}")
        return code

    @field_validator("clinic_date", mode="before")
    @classmethod
    def parse_date(cls, value: Any) -> date:
        return _parse_yyyymmdd(value)

    @field_validator("stable_part", mode="before")
    @classmethod
    def parse_int(cls, value: Any) -> int | None:
        return _parse_int(value)

    @field_validator("hospital_name", "diagnosis_1", "diagnosis_2", mode="before")
    @classmethod
    def blank_to_none(cls, value: Any) -> str | None:
        return _blank_to_none(value)


class HorseDetailItem(KraItem):
    horse_id: str = Field(alias="hrNo")
    horse_name: str = Field(alias="hrName")
    meet_code: int | None = Field(default=None, alias="meet")
    birth_date: date | None = Field(default=None, alias="birthday")
    sex: str | None = None
    origin_country: str | None = Field(default=None, alias="name")
    grade: str | None = Field(default=None, alias="rank")
    rating: float | None = None
    sire_id: str | None = Field(default=None, alias="faHrNo")
    sire_name: str | None = Field(default=None, alias="faHrName")
    dam_id: str | None = Field(default=None, alias="moHrNo")
    dam_name: str | None = Field(default=None, alias="moHrName")
    trainer_id: str | None = Field(default=None, alias="trNo")
    trainer_name: str | None = Field(default=None, alias="trName")
    owner_id: str | None = Field(default=None, alias="owNo")
    owner_name: str | None = Field(default=None, alias="owName")
    race_count_total: int | None = Field(default=None, alias="rcCntT")
    race_count_year: int | None = Field(default=None, alias="rcCntY")
    win_count_total: int | None = Field(default=None, alias="ord1CntT")
    win_count_year: int | None = Field(default=None, alias="ord1CntY")
    second_count_total: int | None = Field(default=None, alias="ord2CntT")
    second_count_year: int | None = Field(default=None, alias="ord2CntY")
    third_count_total: int | None = Field(default=None, alias="ord3CntT")
    third_count_year: int | None = Field(default=None, alias="ord3CntY")
    prize_money_total_krw: int | None = Field(default=None, alias="chaksunT")
    last_sale_amount_raw: str | None = Field(default=None, alias="hrLastAmt")

    @field_validator("horse_id", mode="before")
    @classmethod
    def normalize_horse_id(cls, value: Any) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("마번이 비어 있습니다.")
        return cleaned

    @field_validator("horse_name", mode="before")
    @classmethod
    def require_name(cls, value: Any) -> str:
        cleaned = str(value).strip() if value is not None else ""
        return cleaned or "(이름없음)"

    @field_validator("meet_code", mode="before")
    @classmethod
    def parse_meet(cls, value: Any) -> int | None:
        return parse_meet_code(value)

    @field_validator("birth_date", mode="before")
    @classmethod
    def parse_birth_date(cls, value: Any) -> date | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        if not cleaned or cleaned == "-":
            return None
        return _parse_yyyymmdd(cleaned)

    @field_validator(
        "sire_id",
        "dam_id",
        "trainer_id",
        "owner_id",
        mode="before",
    )
    @classmethod
    def normalize_optional_id(cls, value: Any) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned if cleaned and cleaned != "-" else None

    @field_validator(
        "sex",
        "origin_country",
        "grade",
        "sire_name",
        "dam_name",
        "trainer_name",
        "owner_name",
        "last_sale_amount_raw",
        mode="before",
    )
    @classmethod
    def blank_to_none(cls, value: Any) -> str | None:
        return _blank_to_none(value)

    @field_validator("rating", mode="before")
    @classmethod
    def parse_float(cls, value: Any) -> float | None:
        return _parse_float(value)

    @field_validator(
        "race_count_total",
        "race_count_year",
        "win_count_total",
        "win_count_year",
        "second_count_total",
        "second_count_year",
        "third_count_total",
        "third_count_year",
        "prize_money_total_krw",
        mode="before",
    )
    @classmethod
    def parse_int(cls, value: Any) -> int | None:
        return _parse_int(value)


def parse_meet_code(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if value in {1, 2, 3, 4} else None
    cleaned = str(value).strip()
    if not cleaned or cleaned == "-":
        return None
    if cleaned.isdigit():
        code = int(cleaned)
        return code if code in {1, 2, 3, 4} else None
    return MEET_NAME_TO_CODE.get(cleaned)


def _parse_yyyymmdd(value: Any) -> date:
    cleaned = str(value).strip()
    return datetime.strptime(cleaned, "%Y%m%d").date()


def _parse_int(value: Any) -> int | None:
    cleaned = _clean_number(value)
    if cleaned is None:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def _parse_float(value: Any) -> float | None:
    cleaned = _clean_number(value)
    if cleaned is None:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned if cleaned and cleaned != "-" else None


def _clean_number(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip().replace(",", "")
    return cleaned if cleaned and cleaned != "-" else None
