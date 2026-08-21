from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from horse_racing.collectors.kra_api import KraApiError, response_body


class KraItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")


class RacePlanItem(KraItem):
    race_date: date = Field(alias="raceDt")
    race_number: int = Field(alias="raceNo")
    distance_m: int = Field(alias="raceDs")
    meet_name: str = Field(alias="rccrsNm")
    race_day_count: int | None = Field(default=None, alias="raceDyCnt")
    field_size: int | None = Field(default=None, alias="ptinNhr")
    grade: str | None = Field(default=None, alias="raceClas")
    race_name: str | None = Field(default=None, alias="raceNm")
    burden_type: str | None = Field(default=None, alias="cndtsBurdWgt")
    age_condition: str | None = Field(default=None, alias="cndtsAg")
    sex_condition: str | None = Field(default=None, alias="cndtsGndr")
    rating_condition: str | None = Field(default=None, alias="cndtsRatg")
    newcomer_condition: str | None = Field(default=None, alias="cndtsNcmr")
    scheduled_time: str | None = Field(default=None, alias="strtPargTm")
    weather: str | None = Field(default=None, alias="wetr")
    track_status: str | None = Field(default=None, alias="going")

    @field_validator("race_date", mode="before")
    @classmethod
    def parse_date(cls, value: Any) -> date:
        return _parse_date(value)

    @field_validator("race_number", "distance_m", "race_day_count", "field_size", mode="before")
    @classmethod
    def parse_integer(cls, value: Any) -> int | None:
        return _parse_int(value)

    @field_validator(
        "grade",
        "race_name",
        "burden_type",
        "age_condition",
        "sex_condition",
        "rating_condition",
        "newcomer_condition",
        "scheduled_time",
        "weather",
        "track_status",
        mode="before",
    )
    @classmethod
    def blank_to_none(cls, value: Any) -> str | None:
        return _text_or_none(value)


class AiRaceResultItem(KraItem):
    race_date: date = Field(alias="raceDt")
    race_number: int = Field(alias="raceNo")
    distance_m: int = Field(alias="raceDs")
    meet_name: str = Field(alias="rccrsNm")
    horse_number: int = Field(alias="gtno")
    horse_id: str = Field(alias="hrno")
    horse_name: str = Field(alias="hrnm")
    horse_name_en: str | None = Field(default=None, alias="engHrnm")
    birth_date: date | None = Field(default=None, alias="bthd")
    sex: str | None = Field(default=None, alias="gndrNm")
    origin_country: str | None = Field(default=None, alias="pctyNm")
    carried_weight_kg: float | None = Field(default=None, alias="burdWgt")
    rating: float | None = Field(default=None, alias="ratgSo")
    body_weight_text: str | None = Field(default=None, alias="rchrWeg")
    jockey_name: str | None = Field(default=None, alias="jckyNm")
    trainer_name: str | None = Field(default=None, alias="trarNm")
    owner_name: str | None = Field(default=None, alias="ownerNm")
    finish_position: int | None = Field(default=None, alias="rk")
    finish_time_ms: int | None = Field(default=None, alias="raceRcd")
    margin_text: str | None = Field(default=None, alias="margin")
    win_odds: float | None = Field(default=None, alias="winPrice")
    place_odds: float | None = Field(default=None, alias="placePrice")
    race_name: str | None = Field(default=None, alias="raceNm")

    @field_validator("race_date", mode="before")
    @classmethod
    def parse_date(cls, value: Any) -> date:
        return _parse_date(value)

    @field_validator("race_number", "distance_m", "horse_number", mode="before")
    @classmethod
    def parse_integer(cls, value: Any) -> int | None:
        return _parse_int(value)

    @field_validator("finish_position", mode="before")
    @classmethod
    def parse_finish_position(cls, value: Any) -> int | None:
        return _parse_positive_int(value)

    @field_validator("horse_id", mode="before")
    @classmethod
    def parse_horse_id(cls, value: Any) -> str:
        return _required_id(value, "마번")

    @field_validator("birth_date", mode="before")
    @classmethod
    def parse_birth_date(cls, value: Any) -> date | None:
        return _parse_optional_date(value)

    @field_validator("finish_time_ms", mode="before")
    @classmethod
    def parse_finish_time(cls, value: Any) -> int | None:
        return _parse_race_time_ms(value)

    @field_validator("carried_weight_kg", "rating", "win_odds", "place_odds", mode="before")
    @classmethod
    def parse_float(cls, value: Any) -> float | None:
        return _parse_float(value)

    @field_validator(
        "horse_name_en",
        "sex",
        "origin_country",
        "body_weight_text",
        "jockey_name",
        "trainer_name",
        "owner_name",
        "margin_text",
        "race_name",
        mode="before",
    )
    @classmethod
    def blank_to_none(cls, value: Any) -> str | None:
        return _text_or_none(value)


class DetailedRaceResultItem(KraItem):
    race_date: date = Field(alias="schdRaceDt")
    race_number: int = Field(alias="schdRaceNo")
    distance_m: int = Field(alias="cndRaceDs")
    meet_name: str = Field(alias="schdRccrsNm")
    race_day_count: int | None = Field(default=None, alias="schdRaceDyCnt")
    race_name: str | None = Field(default=None, alias="schdRaceNm")
    grade: str | None = Field(default=None, alias="cndRaceClas")
    burden_type: str | None = Field(default=None, alias="cndBurdGb")
    age_condition: str | None = Field(default=None, alias="cndAg")
    sex_condition: str | None = Field(default=None, alias="cndGndr")
    rating_condition: str | None = Field(default=None, alias="cndRatg")
    scheduled_time: str | None = Field(default=None, alias="cndStrtPargTim")
    actual_start_time: str | None = Field(default=None, alias="rsutRlStrtTim")
    start_time_change_reason: str | None = Field(default=None, alias="rsutStrtTimChgRs")
    weather: str | None = Field(default=None, alias="rsutWetr")
    track_status: str | None = Field(default=None, alias="rsutTrckStus")
    horse_number: int = Field(alias="pthrGtno")
    horse_id: str = Field(alias="pthrHrno")
    horse_name: str = Field(alias="pthrHrnm")
    birth_date: date | None = Field(default=None, alias="pthrBthd")
    sex: str | None = Field(default=None, alias="pthrGndr")
    origin_country: str | None = Field(default=None, alias="pthrNtnlty")
    carried_weight_kg: float | None = Field(default=None, alias="pthrBurdWgt")
    rating: float | None = Field(default=None, alias="pthrRatg")
    body_weight_text: str | None = Field(default=None, alias="pthrWeg")
    equipment: str | None = Field(default=None, alias="pthrEquip")
    jockey_id: str | None = Field(default=None, alias="hrmJckyId")
    jockey_name: str | None = Field(default=None, alias="hrmJckyNm")
    trainer_id: str | None = Field(default=None, alias="hrmTrarId")
    trainer_name: str | None = Field(default=None, alias="hrmTrarNm")
    owner_id: str | None = Field(default=None, alias="hrmOwnerId")
    owner_name: str | None = Field(default=None, alias="hrmOwnerNm")
    finish_position: int | None = Field(default=None, alias="rsutRk")
    finish_time_ms: int | None = Field(default=None, alias="rsutRaceRcd")
    margin_text: str | None = Field(default=None, alias="rsutMargin")
    prize_money_krw: int | None = Field(default=None, alias="rsutRkPurse")
    bonus_prize_money_krw: int | None = Field(default=None, alias="rsutRkAdmny")
    rank_remark: str | None = Field(default=None, alias="rsutRkRemk")
    win_odds: float | None = Field(default=None, alias="rsutWinPrice")
    place_odds: float | None = Field(default=None, alias="rsutQnlaPrice")

    @field_validator("race_date", mode="before")
    @classmethod
    def parse_date(cls, value: Any) -> date:
        return _parse_date(value)

    @field_validator(
        "race_number",
        "distance_m",
        "race_day_count",
        "horse_number",
        "prize_money_krw",
        "bonus_prize_money_krw",
        mode="before",
    )
    @classmethod
    def parse_integer(cls, value: Any) -> int | None:
        return _parse_int(value)

    @field_validator("finish_position", mode="before")
    @classmethod
    def parse_finish_position(cls, value: Any) -> int | None:
        return _parse_positive_int(value)

    @field_validator("horse_id", mode="before")
    @classmethod
    def parse_horse_id(cls, value: Any) -> str:
        return _required_id(value, "마번")

    @field_validator("jockey_id", "trainer_id", "owner_id", mode="before")
    @classmethod
    def parse_optional_id(cls, value: Any) -> str | None:
        return _text_or_none(value)

    @field_validator("birth_date", mode="before")
    @classmethod
    def parse_birth_date(cls, value: Any) -> date | None:
        return _parse_optional_date(value)

    @field_validator("finish_time_ms", mode="before")
    @classmethod
    def parse_finish_time(cls, value: Any) -> int | None:
        return _parse_race_time_ms(value)

    @field_validator("carried_weight_kg", "rating", "win_odds", "place_odds", mode="before")
    @classmethod
    def parse_float(cls, value: Any) -> float | None:
        return _parse_float(value)

    @field_validator(
        "race_name",
        "grade",
        "burden_type",
        "age_condition",
        "sex_condition",
        "rating_condition",
        "scheduled_time",
        "actual_start_time",
        "start_time_change_reason",
        "weather",
        "track_status",
        "sex",
        "origin_country",
        "body_weight_text",
        "equipment",
        "jockey_name",
        "trainer_name",
        "owner_name",
        "margin_text",
        "rank_remark",
        mode="before",
    )
    @classmethod
    def blank_to_none(cls, value: Any) -> str | None:
        return _text_or_none(value)


class FinalDividendItem(KraItem):
    race_date: date = Field(alias="rcDate")
    race_number: int = Field(alias="rcNo")
    meet_name: str = Field(alias="meet")
    bet_type: str = Field(alias="pool")
    horse_number_1: int = Field(alias="chulNo")
    horse_number_2: int = Field(default=0, alias="chulNo2")
    horse_number_3: int = Field(default=0, alias="chulNo3")
    odds: float | None

    @field_validator("race_date", mode="before")
    @classmethod
    def parse_date(cls, value: Any) -> date:
        return _parse_date(value)

    @field_validator(
        "race_number",
        "horse_number_1",
        "horse_number_2",
        "horse_number_3",
        mode="before",
    )
    @classmethod
    def parse_integer(cls, value: Any) -> int:
        return _parse_int(value) or 0

    @field_validator("odds", mode="before")
    @classmethod
    def parse_odds(cls, value: Any) -> float | None:
        parsed = _parse_float(value)
        return parsed if parsed is not None and parsed > 0 else None

    @property
    def selection_key(self) -> str:
        numbers = [self.horse_number_1, self.horse_number_2, self.horse_number_3]
        return "-".join(str(number) for number in numbers if number > 0)


def parse_items[ItemT: KraItem](payload: dict[str, Any], model: type[ItemT]) -> list[ItemT]:
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
    return [model.model_validate(item) for item in raw_items]


def parse_body_weight(value: str | None) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    match = re.search(r"(?P<weight>\d+)\s*\((?P<change>[+-]?\d*)\)", value)
    if not match:
        weight = _parse_int(value)
        return weight, None
    change_text = match.group("change")
    return int(match.group("weight")), int(change_text) if change_text else None


def parse_track_status(value: str | None) -> tuple[str | None, float | None]:
    if not value:
        return None, None
    match = re.search(r"^(?P<condition>[^()]+?)\s*\((?P<moisture>[\d.]+)%\)", value)
    if not match:
        return value.strip(), None
    return match.group("condition").strip(), float(match.group("moisture"))


def _parse_date(value: Any) -> date:
    text = str(value).strip()
    digits = re.sub(r"\D", "", text)
    if len(digits) != 8:
        raise ValueError(f"날짜 형식이 올바르지 않습니다: {text}")
    return datetime.strptime(digits, "%Y%m%d").date()


def _parse_optional_date(value: Any) -> date | None:
    if _text_or_none(value) is None:
        return None
    return _parse_date(value)


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^\d+-]", "", str(value).strip().replace(",", ""))
    if not cleaned or cleaned in {"+", "-"}:
        return None
    return int(cleaned)


def _parse_float(value: Any) -> float | None:
    text = _text_or_none(value)
    if text is None:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _parse_positive_int(value: Any) -> int | None:
    parsed = _parse_int(value)
    return parsed if parsed is not None and parsed > 0 else None


def _parse_race_time_ms(value: Any) -> int | None:
    text = _text_or_none(value)
    if text is None:
        return None
    if ":" not in text:
        try:
            milliseconds = round(float(text) * 1000)
            return milliseconds if milliseconds > 0 else None
        except ValueError:
            return None
    parts = text.split(":")
    try:
        if len(parts) == 2:
            seconds = int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        else:
            return None
    except ValueError:
        return None
    milliseconds = round(seconds * 1000)
    return milliseconds if milliseconds > 0 else None


def _required_id(value: Any, label: str) -> str:
    parsed = _text_or_none(value)
    if parsed is None:
        raise ValueError(f"{label}이 비어 있습니다.")
    return parsed


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned if cleaned and cleaned != "-" else None
