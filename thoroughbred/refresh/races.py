"""Official KRA race-family request planning and row normalization.

This module is deliberately transport- and database-free.  The incremental
refresh runner owns HTTP pagination, response completeness, capture provenance,
and persistence.  Here we define the official endpoints and translate one API
item into a stable locator plus convenient typed fields without discarding the
original item.
"""

from __future__ import annotations

import json
import gzip
import hashlib
import math
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Mapping


MEETS = (1, 3, 4)
_MEET4_START_YEAR = 2026
_BASELINE_FREEZE_UTC = "2026-09-29T23:59:59Z"
_MAX_BASELINE_JSON_BYTES = 128 * 1024 * 1024

# ``datefields`` gives the record date candidates in precedence order.  The
# query parameters below are public request parameters only; the shared client
# adds the service key and pagination values at request time.
FAMILY_SPECS: list[dict[str, Any]] = [
    {
        "family": "race_schedule",
        "endpoint": "/API72_2/racePlan_2",
        "meets": MEETS,
        "query_period": "year",
        "year_param": "rc_year",
        "meet_param": "meet",
        "service_key_parameter": "ServiceKey",
        "datefields": ("rcDate",),
        "meet4_start_year": _MEET4_START_YEAR,
    },
    {
        "family": "race_results",
        "endpoint": "/API4_3/raceResult_3",
        "meets": MEETS,
        "query_period": "year",
        "year_param": "rc_year",
        "meet_param": "meet",
        "service_key_parameter": "ServiceKey",
        "datefields": ("rcDate",),
        "meet4_start_year": _MEET4_START_YEAR,
    },
    {
        "family": "passing_groups",
        "endpoint": "/API303/corner_rank",
        "meets": MEETS,
        "query_period": "year",
        "year_param": "rc_year",
        "meet_param": "meet",
        "service_key_parameter": "ServiceKey",
        "datefields": ("rcDate",),
        "meet4_start_year": _MEET4_START_YEAR,
    },
    {
        "family": "trial_results",
        "endpoint": "/API20_1/ridingTestResult_1",
        "meets": MEETS,
        "query_period": "year",
        "year_param": "tr_year",
        "meet_param": "meet",
        "service_key_parameter": "ServiceKey",
        "datefields": ("trainDate",),
        "meet4_start_year": _MEET4_START_YEAR,
    },
    {
        "family": "public_cards",
        "endpoint": "/API78/chulmainfo",
        "meets": MEETS,
        "query_period": "date",
        "date_param": "race_dt",
        "meet_param": "rccrs_cd",
        "service_key_parameter": "serviceKey",
        "datefields": ("race_dt", "raceDate", "raceDt", "rcDate", "event_date"),
    },
    {
        "family": "entry_sheets",
        "endpoint": "/API26_2/entrySheet_2",
        "meets": MEETS,
        "query_period": "date",
        "date_param": "rc_date",
        "meet_param": "meet",
        "service_key_parameter": "ServiceKey",
        "datefields": ("rcDate", "rc_date", "race_dt", "raceDate", "event_date"),
    },
    {
        "family": "body_weights",
        "endpoint": "/API25_1/entryHorseWeightInfo_1",
        "meets": MEETS,
        "query_period": "date",
        "date_param": "rc_date",
        "meet_param": "meet",
        "service_key_parameter": "ServiceKey",
        "datefields": ("rcDate", "rc_date", "race_dt", "raceDate", "event_date"),
    },
    {
        "family": "steward_reports",
        "endpoint": "/API215/JudgeReport",
        "meets": MEETS,
        "query_period": "year",
        "year_param": "rc_year",
        "meet_param": "meet",
        "service_key_parameter": "serviceKey",
        "datefields": ("rcDate",),
        "meet4_start_year": _MEET4_START_YEAR,
    },
    {
        "family": "sanctions",
        "endpoint": "/API180_1/sanctionHistory_1",
        "meets": MEETS,
        "query_period": "year",
        "year_param": "rc_year",
        "meet_param": "meet",
        "service_key_parameter": "serviceKey",
        "datefields": ("rcDate", "spDate", "stDate"),
        "meet4_start_year": _MEET4_START_YEAR,
    },
]

_SPECS_BY_FAMILY = {spec["family"]: spec for spec in FAMILY_SPECS}
_MEET_LABELS = {
    "1": 1,
    "서울": 1,
    "3": 3,
    "부산": 3,
    "부경": 3,
    "부산경남": 3,
    "부산/부경": 3,
    "영남": 3,
    "4": 4,
    "영천": 4,
}


def canonical_json(value: Any) -> str:
    """Serialize JSON-compatible values deterministically and without NaN."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _as_date(value: Any) -> date | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    if re.fullmatch(r"\d{8}", raw):
        try:
            return datetime.strptime(raw, "%Y%m%d").date()
        except ValueError:
            return None
    match = re.fullmatch(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", raw)
    if match:
        try:
            return date(*(int(part) for part in match.groups()))
        except ValueError:
            return None
    match = re.fullmatch(
        r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일?"
        r"(?:\s*\([월화수목금토일]\))?",
        raw,
    )
    if match:
        try:
            return date(*(int(part) for part in match.groups()))
        except ValueError:
            return None
    return None


def _date_text(value: Any) -> str | None:
    parsed = _as_date(value)
    return parsed.isoformat() if parsed else None


def _request_date(context: Mapping[str, Any]) -> date | None:
    for name in ("requested_date", "query_date", "race_dt", "rc_date"):
        parsed = _as_date(context.get(name))
        if parsed:
            return parsed
    params = context.get("request_params")
    if isinstance(params, Mapping):
        for name in ("race_dt", "rc_date", "rcDate", "date"):
            parsed = _as_date(params.get(name))
            if parsed:
                return parsed
    return None


def _parse_window_date(value: str | date) -> date:
    parsed = _as_date(value)
    if parsed is None:
        raise ValueError(f"invalid ISO date: {value!r}")
    return parsed


def build_requests(start_date: str | date, end_date: str | date) -> list[dict[str, Any]]:
    """Build public request partitions intersecting an inclusive date window.

    Annual endpoints use one complete year/meet partition.  API78 cards use
    one exact date/meet request because that endpoint's verified parameter is
    ``race_dt``.  A caller can use narrow date windows for routine refreshes;
    a historical backfill can use the same planner with its full date span.
    """
    start = _parse_window_date(start_date)
    end = _parse_window_date(end_date)
    if end < start:
        raise ValueError("end_date must be on or after start_date")

    requests: list[dict[str, Any]] = []
    for spec in FAMILY_SPECS:
        if spec["query_period"] == "year":
            for year in range(start.year, end.year + 1):
                for meet in spec["meets"]:
                    if meet == 4 and year < int(spec.get("meet4_start_year", year)):
                        continue
                    requests.append(
                        {
                            "family": spec["family"],
                            "endpoint": spec["endpoint"],
                            "query_period": "year",
                            "service_key_parameter": spec["service_key_parameter"],
                            "meet": str(meet),
                            "requested_year": year,
                            "requested_meet": meet,
                            "params": {
                                spec["year_param"]: str(year),
                                spec["meet_param"]: str(meet),
                            },
                        }
                    )
        elif spec["query_period"] == "date":
            day = start
            while day <= end:
                for meet in spec["meets"]:
                    requests.append(
                        {
                            "family": spec["family"],
                            "endpoint": spec["endpoint"],
                            "query_period": "date",
                            "service_key_parameter": spec["service_key_parameter"],
                            "meet": str(meet),
                            "requested_date": day.isoformat(),
                            "requested_meet": meet,
                            "params": {
                                spec["date_param"]: day.strftime("%Y%m%d"),
                                spec["meet_param"]: str(meet),
                            },
                        }
                    )
                day = date.fromordinal(day.toordinal() + 1)
        else:
            raise ValueError(f"unsupported query_period: {spec['query_period']!r}")
    return requests


def _present_value(item: Mapping[str, Any], names: Iterable[str]) -> tuple[str | None, Any]:
    for name in names:
        if name in item and item[name] is not None:
            return name, item[name]
    return None, None


_BODY_WEIGHT_FIELDS = ("wgHr", "horseWeight", "horse_weight")
_BODY_WEIGHT_CHANGE_FIELDS = ("wgHrChg", "wgHrDiff", "wgHrBun", "bodyWeightChange")
_BODY_WEIGHT_PATTERN = re.compile(r"^(?P<weight>[1-9][0-9]*)(?:\((?P<change>[+-][0-9]+)\))?$")


def _first_present_including_null(
    item: Mapping[str, Any], names: Iterable[str]
) -> tuple[str | None, Any]:
    """Return a source field even when its explicit value is null."""
    first_null: tuple[str, Any] | None = None
    for name in names:
        if name not in item:
            continue
        if item[name] is not None:
            return name, item[name]
        if first_null is None:
            first_null = (name, None)
    return first_null if first_null is not None else (None, None)


def _parse_body_weight(
    item: Mapping[str, Any],
) -> tuple[int | None, int | float | None, str | None, str | None, str | None]:
    """Parse KRA weight text, keeping invalid and placeholder source states visible."""
    weight_field, raw_weight = _first_present_including_null(item, _BODY_WEIGHT_FIELDS)
    if weight_field is None:
        return None, None, None, None, "field_missing"
    if raw_weight is None:
        return None, None, None, None, "null"

    raw_text = str(raw_weight)
    stripped = raw_text.strip()
    if not stripped:
        return None, None, raw_text, None, "blank"

    match = _BODY_WEIGHT_PATTERN.fullmatch(stripped)
    if match is None:
        numeric = _number(raw_weight)
        if numeric is not None and numeric <= 0:
            state = "nonpositive_placeholder"
        elif stripped in {"-", "--", "—", "–", "X"}:
            state = "placeholder"
        else:
            state = "invalid_format"
        return None, None, raw_text, None, state

    weight = int(match.group("weight"))
    embedded_change = match.group("change")
    explicit_change_field, explicit_change = _present_value(item, _BODY_WEIGHT_CHANGE_FIELDS)
    if explicit_change_field is not None:
        change = _number(explicit_change)
        change_raw = str(explicit_change)
    elif embedded_change is not None:
        change = int(embedded_change)
        change_raw = embedded_change
    else:
        change = None
        change_raw = None
    state = "positive_with_change" if change is not None else "positive"
    return weight, change, raw_text, change_raw, state


def _source_meet(item: Mapping[str, Any]) -> tuple[int | None, Any]:
    for field in ("meet", "rccrs_cd", "meetCd", "meet_code"):
        if field not in item or item[field] is None:
            continue
        raw = item[field]
        label = str(raw).strip()
        numeric = _MEET_LABELS.get(label)
        if numeric is not None:
            return numeric, raw
    return None, None


def _context_meet(context: Mapping[str, Any]) -> int | None:
    for name in ("meet", "requested_meet"):
        raw = context.get(name)
        if raw is None:
            continue
        value = _MEET_LABELS.get(str(raw).strip())
        if value is not None:
            return value
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            continue
        if parsed in MEETS:
            return parsed
    return None


def _id_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if text.strip() in {"", "-"}:
        return None
    return text


_RACE_ORDINAL_PATTERN = re.compile(r"^(?:제\s*)?(?P<number>[0-9]+)(?:\s*경주)?$")
_TRIAL_ORDINAL_PATTERN = re.compile(r"^(?:제\s*)?(?P<number>[0-9]+)(?:\s*(?:차|회|번))?$")


def _ordinal_text(value: Any, *, trial: bool = False) -> str | None:
    """Canonicalize only positive integer ordinals and their explicit labels."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if value > 0 else None
    if isinstance(value, float):
        return str(int(value)) if math.isfinite(value) and value.is_integer() and value > 0 else None
    raw = str(value).strip()
    if not raw:
        return None
    pattern = _TRIAL_ORDINAL_PATTERN if trial else _RACE_ORDINAL_PATTERN
    match = pattern.fullmatch(raw)
    if match is None:
        return None
    number = int(match.group("number"))
    return str(number) if number > 0 else None


def _first_id(item: Mapping[str, Any], names: Iterable[str]) -> str | None:
    _, raw = _present_value(item, names)
    return _id_text(raw)


def _number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return int(value) if float(value).is_integer() else float(value)
    text = str(value).strip()
    if not text or text in {"-", "X"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def _source_date(family: str, item: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[str | None, str | None, Any]:
    spec = _SPECS_BY_FAMILY[family]
    field, value = _present_value(item, spec["datefields"])
    parsed = _date_text(value)
    if parsed:
        requested = _request_date(context) if spec["query_period"] == "date" else None
        if requested is not None and parsed != requested.isoformat():
            raise ValueError(
                f"source event date {parsed} disagrees with requested date {requested.isoformat()}"
            )
        return parsed, field, value
    # Date-partitioned endpoints can omit the query date from every item.
    if spec["query_period"] == "date":
        queried = _request_date(context)
        if queried:
            return queried.isoformat(), f"request.{spec['date_param']}", queried.strftime("%Y%m%d")
    # A sanction may identify its effective/start date without a race date.
    # The chosen field name remains available for downstream review.
    for candidate in spec["datefields"]:
        candidate_date = _date_text(item.get(candidate))
        if candidate_date:
            return candidate_date, candidate, item[candidate]
    return None, field, value


def _family_keys(
    family: str,
    meet: str | None,
    event_date: str | None,
    race_no: str | None,
    horse_id: str | None,
    horse_no: str | None,
    trial_no: str | None,
    item: Mapping[str, Any],
) -> list[str | None]:
    if family == "race_schedule":
        return [meet, event_date, race_no]
    if family == "race_results":
        return [meet, event_date, race_no, horse_id, horse_no]
    if family == "passing_groups":
        return [meet, event_date, race_no]
    if family == "trial_results":
        return [meet, event_date, trial_no, horse_id, horse_no]
    if family == "public_cards":
        return [meet, event_date, race_no, horse_no, horse_id]
    if family in {"entry_sheets", "body_weights"}:
        return [meet, event_date, race_no, horse_no, horse_id]
    if family == "steward_reports":
        return [meet, event_date, race_no]
    if family == "sanctions":
        subject_class = _id_text(item.get("gubun"))
        subject_id = _id_text(item.get("prNo"))
        return [
            meet,
            event_date,
            subject_class,
            subject_id,
            _id_text(item.get("kind")),
            _id_text(item.get("reason")),
            _id_text(item.get("spDate")),
            _id_text(item.get("stDate")),
            _id_text(item.get("chulNo")),
        ]
    raise ValueError(f"unknown race family: {family!r}")


def _selected_raw_fields(item: Mapping[str, Any], pattern: re.Pattern[str]) -> dict[str, Any]:
    return {name: item[name] for name in sorted(item) if pattern.search(name)}


_SECTION_FIELD = re.compile(r"^(?:se|bu).*(?:AccTime|Time)$", re.IGNORECASE)
_PASSING_ORDER_FIELD = re.compile(r"(?:Ord|order)$", re.IGNORECASE)

_SEOUL_SECTION_POINTS = (
    ("S1F", "seS1fAccTime", "sjS1fOrd"),
    ("1C", "se_1cAccTime", "sj_1cOrd"),
    ("2C", "se_2cAccTime", "sj_2cOrd"),
    ("3C", "se_3cAccTime", "sj_3cOrd"),
    ("4C", "se_4cAccTime", "sj_4cOrd"),
    ("G3F", "seG3fAccTime", "sjG3fOrd"),
    ("G1F", "seG1fAccTime", "sjG1fOrd"),
)
_YEONGNAM_SECTION_POINTS = (
    ("S1F", "buS1fAccTime", "buS1fOrd"),
    ("G8F", "buG8fAccTime", "buG8fOrd"),
    ("G6F", "buG6fAccTime", "buG6fOrd"),
    ("G4F", "buG4fAccTime", "buG4fOrd"),
    ("G3F", "buG3fAccTime", "buG3fOrd"),
    ("G2F", "buG2fAccTime", "buG2fOrd"),
    ("G1F", "buG1fAccTime", "buG1fOrd"),
)
_YEONGNAM_SECTION_INTERVALS = (
    ("S1F", "segment_time", "buS1fTime"),
    ("10F_8F", "segment_time", "bu_10_8fTime"),
    ("8F_6F", "segment_time", "bu_8_6fTime"),
    ("6F_4F", "segment_time", "bu_6_4fTime"),
    ("4F_2F", "segment_time", "bu_4_2fTime"),
    ("3F_G", "closing_time", "bu_3fGTime"),
    ("2F_G", "closing_time", "bu_2fGTime"),
    ("1F_G", "closing_time", "bu_1fGTime"),
)
_PASSING_CANONICAL_BY_FIELD = {
    1: {
        "corner_1": "1C", "corner_2": "2C", "corner_3": "3C", "corner_4": "4C",
        "corner_7": "S1F", "corner_8": "G1F",
    },
    3: {
        "corner_1": "G8F", "corner_2": "G6F", "corner_3": "G4F", "corner_5": "G3F",
        "corner_7": "S1F", "corner_8": "G2F", "corner_9": "G1F",
    },
    4: {
        "corner_1": "G8F", "corner_2": "G6F", "corner_3": "G4F", "corner_5": "G3F",
        "corner_7": "S1F", "corner_8": "G2F", "corner_9": "G1F",
    },
}


def transform(family: str, payload_row: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize one API item while retaining its complete JSON object.

    Natural keys are locators, not uniqueness constraints.  The shared store
    must retain repeated source occurrences even when their key and payload
    are identical.  Missing IDs and dates remain null rather than being
    guessed from horse names or query years.
    """
    if family not in _SPECS_BY_FAMILY:
        raise ValueError(f"unknown race family: {family!r}")
    if not isinstance(payload_row, Mapping):
        raise TypeError("payload_row must be an object")
    if not isinstance(context, Mapping):
        raise TypeError("context must be an object")

    spec = _SPECS_BY_FAMILY[family]
    if "meet" not in context and "requested_meet" not in context:
        raise ValueError("context must include the requested meet partition")
    requested_meet = _context_meet(context)
    if requested_meet not in spec["meets"]:
        raise ValueError(f"meet is outside this family scope: {context.get('meet')!r}")
    source_meet, source_meet_raw = _source_meet(payload_row)
    if source_meet is not None and source_meet not in spec["meets"]:
        raise ValueError(f"source row carries out-of-scope meet code {source_meet}")
    meet_value = source_meet or requested_meet

    event_date, date_field, event_date_raw = _source_date(family, payload_row, context)
    race_no_raw_name, race_no_raw = _present_value(
        payload_row,
        ("rcNo", "raceNo", "race_no", "raceNoRaw", "programNo", "program_no", "programNoRaw"),
    )
    race_no = _ordinal_text(race_no_raw)
    horse_id_names = ("hrNo", "horseId", "horse_id", "horse_id_raw", "hrno")
    if family == "sanctions" and str(payload_row.get("gubun", "")).strip() == "말":
        horse_id_names = ("prNo",)
    horse_id = _first_id(payload_row, horse_id_names)
    horse_no_raw_name, horse_no_raw = _present_value(
        payload_row,
        ("chulNo", "horseNo", "horse_no", "gtno", "chul_no"),
    )
    horse_no = _id_text(horse_no_raw)
    trial_no_raw_name, trial_no_raw = _present_value(payload_row, ("trainNo", "trialNo", "trial_no"))
    trial_no = _ordinal_text(trial_no_raw, trial=True)

    horse_name_field, horse_name_raw = _present_value(
        payload_row,
        ("hrName", "hrnm", "horseName", "horse_name"),
    )
    jockey_id = _first_id(payload_row, ("jkNo", "jockeyId", "jockey_id"))
    jockey_name_field, jockey_name = _present_value(payload_row, ("jkName", "jckyNm", "jockeyName", "jockey_name"))
    trainer_id = _first_id(payload_row, ("trNo", "trainerId", "trainer_id"))
    trainer_name_field, trainer_name = _present_value(payload_row, ("trName", "trarNm", "trainerName", "trainer_name"))
    _, owner_name = _present_value(payload_row, ("owName", "ownerNm", "ownerName", "owner_name"))
    body_weight, weight_change, body_weight_raw, weight_change_raw, body_weight_state = _parse_body_weight(payload_row)
    _, carried_weight = _present_value(payload_row, ("wgBudam", "burdWgt", "carriedWeight", "carried_weight"))
    _, result_rank = _present_value(payload_row, ("ord", "resultRank", "result_rank"))
    _, finish_time = _present_value(payload_row, ("rcTime", "finishTime", "finish_time"))
    _, finish_margin = _present_value(payload_row, ("diffUnit", "finishMargin", "finish_margin"))
    _, win_odds = _present_value(payload_row, ("winOdds", "win_odds"))
    _, place_odds = _present_value(payload_row, ("plcOdds", "placeOdds", "place_odds"))
    _, race_name = _present_value(payload_row, ("rcName", "raceName", "race_name"))
    _, distance = _present_value(payload_row, ("rcDist", "distance", "distance_m"))
    _, grade = _present_value(payload_row, ("rank", "grade", "grade_raw"))
    _, race_condition = _present_value(payload_row, ("raceCnd1", "raceCondition", "race_condition"))
    _, scheduled_start = _present_value(payload_row, ("schStTime", "strtTim", "scheduledStart", "scheduled_start"))
    _, equipment = _present_value(payload_row, ("equipCrs", "equipment", "equipment_raw"))
    _, trial_time = _present_value(payload_row, ("trainTime", "trialTime", "trial_time"))
    _, track_condition = _present_value(payload_row, ("track", "trackCondition", "track_condition"))
    _, weather = _present_value(payload_row, ("weather",))

    section_fields = _selected_raw_fields(payload_row, _SECTION_FIELD)
    passing_order_fields = _selected_raw_fields(payload_row, _PASSING_ORDER_FIELD)
    passing_group_fields = {
        name: payload_row[name]
        for name in sorted(payload_row)
        if re.fullmatch(r"corner_[1-9]", name)
    }
    if family == "public_cards" and "equipCrs" in payload_row:
        equipment_state = (
            "null" if payload_row["equipCrs"] is None
            else "blank" if str(payload_row["equipCrs"]).strip() == ""
            else "nonblank"
        )
    elif family == "public_cards":
        equipment_state = "field_missing"
    else:
        equipment_state = None

    raw_meet_label = payload_row.get("meet")
    fields = {
        "event_date_raw": None if event_date_raw is None else str(event_date_raw),
        "event_date_field": date_field,
        "source_meet_raw": None if source_meet_raw is None else str(source_meet_raw),
        "api_meet_label": None if raw_meet_label is None else str(raw_meet_label),
        "meet_mismatch": source_meet is not None and source_meet != requested_meet,
        "race_no_raw": None if race_no_raw is None else str(race_no_raw),
        "horse_no": _number(horse_no_raw),
        "horse_no_raw": None if horse_no_raw is None else str(horse_no_raw),
        "horse_name_raw": None if horse_name_raw is None else str(horse_name_raw),
        "horse_name_field": horse_name_field,
        "horse_id_raw": None if horse_id is None else horse_id,
        "jockey_id_raw": jockey_id,
        "jockey_name_raw": None if jockey_name is None else str(jockey_name),
        "jockey_name_field": jockey_name_field,
        "trainer_id_raw": trainer_id,
        "trainer_name_raw": None if trainer_name is None else str(trainer_name),
        "trainer_name_field": trainer_name_field,
        "owner_name_raw": None if owner_name is None else str(owner_name),
        "result_rank": _number(result_rank),
        "result_rank_raw": None if result_rank is None else str(result_rank),
        "finish_time": _number(finish_time),
        "finish_time_raw": None if finish_time is None else str(finish_time),
        "finish_margin_raw": None if finish_margin is None else str(finish_margin),
        "horse_weight_kg": body_weight,
        "horse_weight_raw": body_weight_raw,
        "body_weight_value_state": body_weight_state,
        "body_weight_change": weight_change,
        "body_weight_change_raw": weight_change_raw,
        "carried_weight_kg": _number(carried_weight),
        "carried_weight_raw": None if carried_weight is None else str(carried_weight),
        "win_odds": _number(win_odds),
        "place_odds": _number(place_odds),
        "race_name_raw": None if race_name is None else str(race_name),
        "race_condition_raw": None if race_condition is None else str(race_condition),
        "distance_m": _number(distance),
        "grade_raw": None if grade is None else str(grade),
        "scheduled_start_raw": None if scheduled_start is None else str(scheduled_start),
        "track_condition_raw": None if track_condition is None else str(track_condition),
        "weather_raw": None if weather is None else str(weather),
        "equipment_raw": None if equipment is None else str(equipment),
        "equipment_value_state": equipment_state,
        "trial_no_raw": None if trial_no_raw is None else str(trial_no_raw),
        "trial_time": _number(trial_time),
        "trial_time_raw": None if trial_time is None else str(trial_time),
        "section_values_raw": section_fields,
        "passing_order_raw": passing_order_fields,
        "passing_group_values_raw": passing_group_fields,
        "steward_text_raw": None if payload_row.get("judgement") is None else str(payload_row.get("judgement")),
        "supplemental_steward_text_raw": None if payload_row.get("addJudgement") is None else str(payload_row.get("addJudgement")),
        "sanction_subject_class_raw": None if payload_row.get("gubun") is None else str(payload_row.get("gubun")),
        "sanction_subject_id_raw": None if payload_row.get("prNo") is None else str(payload_row.get("prNo")),
        "sanction_type_raw": None if payload_row.get("kind") is None else str(payload_row.get("kind")),
        "sanction_reason_raw": None if payload_row.get("reason") is None else str(payload_row.get("reason")),
        "sanction_fine_raw": None if payload_row.get("fine") is None else str(payload_row.get("fine")),
        "sanction_date_raw": None if payload_row.get("spDate") is None else str(payload_row.get("spDate")),
        "sanction_start_date_raw": None if payload_row.get("stDate") is None else str(payload_row.get("stDate")),
        "race_no_field": race_no_raw_name,
        "trial_no_field": trial_no_raw_name,
        "horse_no_field": horse_no_raw_name,
    }
    key = _family_keys(family, str(meet_value), event_date, race_no, horse_id, horse_no, trial_no, payload_row)
    return {
        "family": family,
        "event_date": event_date,
        "meet": str(meet_value),
        "key": key,
        "key_json": canonical_json(key),
        "horse_id": horse_id,
        "race_no": race_no,
        "payload": dict(payload_row),
        "fields": fields,
    }


def _parse_positive_measurement(value: Any, measure_kind: str) -> tuple[int | None, str | None]:
    """Match the reviewed API4 section builder's numeric and sentinel policy."""
    if value is None or str(value).strip() == "":
        return None, None
    raw = str(value).strip()
    try:
        number = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None, "not_numeric"
    if not number.is_finite():
        return None, "not_finite"
    if number == 0:
        return None, None
    if measure_kind == "passing_order" and number == 99:
        return None, None
    if number < 0:
        return None, "negative_value"
    if measure_kind == "passing_order":
        if number != number.to_integral_value() or number > 89:
            return None, "invalid_passing_order"
        return int(number), None
    milliseconds = (number * 1000).to_integral_value(rounding=ROUND_HALF_UP)
    if milliseconds > 2_147_483_647:
        return None, "time_out_of_range"
    return int(milliseconds), None


def _is_passing_notation(value: Any) -> bool:
    if value is None:
        return False
    return str(value).strip(" ") not in {"", "-", "X"}


def _row_distance(row: Mapping[str, Any], override: Any = None) -> int | float | None:
    if override is not None:
        return _number(override)
    fields = row.get("fields")
    if isinstance(fields, Mapping) and fields.get("distance_m") is not None:
        return _number(fields.get("distance_m"))
    payload = row.get("payload")
    if isinstance(payload, Mapping):
        for name in ("rcDist", "distance", "distance_m"):
            if payload.get(name) is not None:
                return _number(payload.get(name))
    return None


def enrich_row(row: Mapping[str, Any], *, distance_m: Any = None) -> dict[str, Any]:
    """Add canonical measurements/points and repair typed weight fields.

    The complete payload is left unchanged. Seoul API303's nominal
    ``corner_1 -> 1C`` mapping is withheld when race distance is unknown, and
    marked inapplicable at 1000m where a 1C point does not exist. Callers that
    have the matching planned distance may supply it.
    """
    if not isinstance(row, Mapping):
        raise TypeError("row must be an object")
    family = row.get("family")
    if family not in {"race_results", "passing_groups", "body_weights"}:
        raise ValueError(f"row family cannot be enriched: {family!r}")
    raw_fields = row.get("fields")
    fields = dict(raw_fields) if isinstance(raw_fields, Mapping) else {}
    payload = row.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    enriched = dict(row)
    meet = _context_meet({"meet": row.get("meet")})

    if family in {"race_results", "body_weights"}:
        weight, change, weight_raw, change_raw, weight_state = _parse_body_weight(payload)
        fields["horse_weight_kg"] = weight
        fields["horse_weight_raw"] = weight_raw
        fields["body_weight_change"] = change
        fields["body_weight_change_raw"] = change_raw
        fields["body_weight_value_state"] = weight_state

    if family == "race_results":
        if meet is None:
            raise ValueError("race result row has no supported meet")
        point_specs = _SEOUL_SECTION_POINTS if meet == 1 else _YEONGNAM_SECTION_POINTS
        field_defs: list[tuple[str, str, str]] = []
        field_defs.extend((point, "cumulative_time", time_field) for point, time_field, _ in point_specs)
        field_defs.extend((point, "passing_order", order_field) for point, _, order_field in point_specs)
        if meet in {3, 4}:
            field_defs.extend(_YEONGNAM_SECTION_INTERVALS)

        measurements: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []
        source_values = payload
        if not source_values:
            for field_name in ("section_values_raw", "passing_order_raw"):
                candidate = fields.get(field_name)
                if isinstance(candidate, Mapping):
                    source_values = {**source_values, **candidate}
        for point_code, measure_kind, source_field in field_defs:
            if source_field not in source_values:
                continue
            raw_value = source_values[source_field]
            parsed_value, issue = _parse_positive_measurement(raw_value, measure_kind)
            if issue:
                issues.append(
                    {
                        "point_code": point_code,
                        "measure_kind": measure_kind,
                        "source_field": source_field,
                        "raw_value": str(raw_value),
                        "issue": issue,
                    }
                )
            if parsed_value is None:
                continue
            measurements.append(
                {
                    "point_code": point_code,
                    "measure_kind": measure_kind,
                    "source_field": source_field,
                    "raw_value": str(raw_value),
                    "time_ms": parsed_value if measure_kind != "passing_order" else None,
                    "passing_order": parsed_value if measure_kind == "passing_order" else None,
                }
            )
        fields["section_measurements"] = measurements
        fields["section_parse_issues"] = issues
    elif family == "passing_groups":
        if meet not in _PASSING_CANONICAL_BY_FIELD:
            raise ValueError("passing group row has no supported meet")
        raw_values = {
            str(name): value
            for name, value in payload.items()
            if re.fullmatch(r"corner_\d+", str(name))
        }
        if not raw_values:
            raw_values = fields.get("passing_group_values_raw")
        if not isinstance(raw_values, Mapping):
            raw_values = {}

        mapped = _PASSING_CANONICAL_BY_FIELD[meet]
        candidates: list[dict[str, Any]] = []
        holds: list[dict[str, Any]] = []
        for source_field in sorted(raw_values):
            raw_value = raw_values[source_field]
            if not _is_passing_notation(raw_value):
                continue
            notation = str(raw_value)
            canonical_point = mapped.get(str(source_field))
            if canonical_point is None:
                holds.append(
                    {
                        "canonical_point": None,
                        "notation": notation,
                        "source_field": str(source_field),
                        "mapping_status": "unmapped_source_field",
                    }
                )
                continue
            candidates.append(
                {
                    "canonical_point": canonical_point,
                    "notation": notation,
                    "source_field": str(source_field),
                    "identity_notation": notation.strip(" "),
                }
            )

        points_by_notation: dict[str, set[str]] = {}
        for candidate in candidates:
            points_by_notation.setdefault(candidate["identity_notation"], set()).add(candidate["canonical_point"])

        safe_points: list[dict[str, Any]] = []
        distance = _row_distance(row, distance_m)
        for candidate in candidates:
            point = candidate["canonical_point"]
            notation_identity = candidate["identity_notation"]
            if len(points_by_notation[notation_identity]) > 1:
                holds.append(
                    {
                        "canonical_point": point,
                        "notation": candidate["notation"],
                        "source_field": candidate["source_field"],
                        "mapping_status": "ambiguous_repeated_notation",
                        "candidate_points": sorted(points_by_notation[notation_identity]),
                    }
                )
                continue
            if meet == 1 and point == "1C" and distance is None:
                holds.append(
                    {
                        "canonical_point": point,
                        "notation": candidate["notation"],
                        "source_field": candidate["source_field"],
                        "mapping_status": "distance_unknown",
                    }
                )
                continue
            if meet == 1 and point == "1C" and distance == 1000:
                holds.append(
                    {
                        "canonical_point": point,
                        "notation": candidate["notation"],
                        "source_field": candidate["source_field"],
                        "mapping_status": "distance_inapplicable",
                    }
                )
                continue
            safe_points.append(
                {
                    "canonical_point": point,
                    "notation": candidate["notation"],
                    "source_field": candidate["source_field"],
                    "mapping_status": "nominal_unique",
                }
            )
        fields["passing_points"] = safe_points
        fields["passing_point_holds"] = holds

    enriched["fields"] = fields
    return enriched


def summarize_availability(
    family: str,
    payload_rows: Iterable[Mapping[str, Any]],
    context: Mapping[str, Any],
    *,
    complete: bool,
) -> dict[str, Any]:
    """Describe observed event dates and distinguish empty from incomplete.

    For exact-date requests, an empty date is reported only when the shared
    collector says every page completed successfully.  Annual zero-result
    partitions are represented by ``empty_partition`` and do not imply that
    every calendar day in that year had no event.
    """
    if family not in _SPECS_BY_FAMILY:
        raise ValueError(f"unknown race family: {family!r}")
    spec = _SPECS_BY_FAMILY[family]
    rows = list(payload_rows)
    dates: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        event_date, _, _ = _source_date(family, row, context)
        if event_date:
            dates.add(event_date)
    requested_date = _request_date(context)
    if requested_date is not None and spec["query_period"] == "date":
        expected = requested_date.isoformat()
        available_dates = sorted(dates or ({expected} if rows else set()))
        empty_dates = [expected] if complete and not rows else []
        status = "available" if rows else "empty" if complete else "incomplete"
        return {
            "family": family,
            "status": status,
            "available_dates": available_dates,
            "empty_dates": empty_dates,
            "requested_date": expected,
            "complete": bool(complete),
            "row_count": len(rows),
        }
    status = "available" if rows else "empty_partition" if complete else "incomplete"
    return {
        "family": family,
        "status": status,
        "available_dates": sorted(dates),
        "empty_dates": [],
        "requested_date": None,
        "complete": bool(complete),
        "row_count": len(rows),
    }


def _compact_date(value: str | date) -> str:
    return _parse_window_date(value).strftime("%Y%m%d")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_repository_file(reference: str | Path, *, allow_missing: bool = False) -> Path | None:
    """Resolve a stored source path without allowing it to escape this repo."""
    root = _repository_root().resolve()
    raw = Path(reference)
    candidates = [raw] if raw.is_absolute() else [root / raw]
    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if resolved.is_file():
            return resolved
    if allow_missing:
        return None
    raise FileNotFoundError(f"baseline source file is missing inside repository: {reference}")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _checked_source_file(reference: str, expected_sha256: str | None = None) -> tuple[Path, str]:
    path = _resolve_repository_file(reference)
    assert path is not None
    actual_sha256 = _file_sha256(path)
    if expected_sha256 and actual_sha256.lower() != str(expected_sha256).lower():
        raise ValueError(f"baseline source hash mismatch: {reference}")
    return path, actual_sha256


def _read_json_file(path: Path, *, compressed: bool = False) -> Any:
    if path.stat().st_size > _MAX_BASELINE_JSON_BYTES:
        raise ValueError(f"baseline source exceeds size limit: {path}")
    if compressed:
        with path.open("rb") as source:
            with gzip.GzipFile(fileobj=source, mode="rb") as uncompressed:
                content = uncompressed.read(_MAX_BASELINE_JSON_BYTES + 1)
        if len(content) > _MAX_BASELINE_JSON_BYTES:
            raise ValueError(f"decompressed baseline source exceeds size limit: {path}")
    else:
        content = path.read_bytes()
    return json.loads(content)


def _response_items(document: Any) -> list[Mapping[str, Any]]:
    """Return response.body.items.item as objects, including singleton items."""
    current = document
    for part in ("response", "body", "items", "item"):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            raise ValueError(f"baseline source has no response.body.items.item at {part}")
    if current is None:
        return []
    if isinstance(current, Mapping):
        return [current]
    if not isinstance(current, list) or any(not isinstance(item, Mapping) for item in current):
        raise ValueError("baseline response items must be an object or a list of objects")
    return current


def _decode_source_item(raw_json: Any, family: str, source_file: str) -> Mapping[str, Any]:
    if not isinstance(raw_json, str):
        raise ValueError(f"{family} baseline row lacks raw JSON: {source_file}")
    try:
        item = json.loads(raw_json)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {family} baseline raw JSON in {source_file}") from exc
    if not isinstance(item, Mapping):
        raise ValueError(f"{family} baseline item is not an object: {source_file}")
    return item


def _baseline_capture(source_capture: Any) -> tuple[str, str, str | None]:
    if source_capture is not None and str(source_capture).strip():
        captured = str(source_capture).strip()
        return captured, "source_capture_timestamp", captured
    return _BASELINE_FREEZE_UTC, "baseline_freeze_date", None


def _baseline_row(
    family: str,
    item: Mapping[str, Any],
    *,
    meet: Any,
    source_file: str,
    source_sha256: str | None,
    source_row_no: Any,
    source_item_index: Any = None,
    source_captured_at_utc: Any = None,
    requested_date: str | None = None,
    payload_unavailable: bool = False,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    captured_at, capture_basis, actual_source_capture = _baseline_capture(source_captured_at_utc)
    context: dict[str, Any] = {
        "meet": str(meet),
        "captured_at_utc": captured_at,
        "source_file": source_file,
        "source_sha256": source_sha256,
        "source_row_no": source_row_no,
    }
    if requested_date:
        context["requested_date"] = requested_date
    normalized = transform(family, item, context)
    normalized.update(
        {
            "baseline": True,
            "source_file": source_file,
            "source_sha256": source_sha256,
            "source_row_no": source_row_no,
            "source_item_index": source_item_index,
            "captured_at_utc": captured_at,
            "source_captured_at_utc": actual_source_capture,
            "capture_time_basis": capture_basis,
            "payload_unavailable": bool(payload_unavailable),
        }
    )
    if payload_unavailable:
        normalized["payload"] = {"payload_unavailable": True}
        normalized["fields"]["payload_unavailable"] = True
        if unavailable_reason:
            normalized["payload_unavailable_reason"] = unavailable_reason
            normalized["fields"]["payload_unavailable_reason"] = unavailable_reason
    return normalized


def _iter_baseline_schedule(connection: Any, start: str, end: str) -> Iterable[dict[str, Any]]:
    query = """
        SELECT source_meet, race_date_key, race_no_key, source_file,
               source_file_sha256, source_item_index, source_record_json
        FROM race_plan_full_api
        WHERE race_date_key BETWEEN ? AND ?
          AND source_meet IN ('1', '3', '4')
        ORDER BY source_meet, race_date_key, race_no_key, source_item_index
    """
    rows = connection.execute(query, [start, end]).fetchall()
    verified_files: dict[str, str] = {}
    for meet, event_date, race_no, source_file, stored_sha, index, raw_json in rows:
        if not source_file:
            raise ValueError("race schedule baseline row has no source_file")
        if source_file not in verified_files:
            _, verified_files[source_file] = _checked_source_file(source_file, stored_sha)
        item = _decode_source_item(raw_json, "race_schedule", source_file)
        normalized = _baseline_row(
            "race_schedule",
            item,
            meet=meet,
            source_file=source_file,
            source_sha256=verified_files[source_file],
            source_row_no=index,
            source_item_index=index,
        )
        expected = [str(meet), _date_text(event_date), str(race_no)]
        if normalized["key"] != expected:
            raise ValueError(f"race schedule source key disagrees with core baseline: {source_file}#{index}")
        yield normalized


def _iter_baseline_results(connection: Any, start: str, end: str) -> Iterable[dict[str, Any]]:
    query = """
        SELECT source_meet, result_date, result_race_no, source_file, source_item_index,
               horse_id_raw, horse_program_no_raw, result_rank_raw,
               finish_time_seconds_raw, horse_name_raw
        FROM confirmed_runners
        WHERE result_date BETWEEN ? AND ?
          AND source_meet IN ('1', '3', '4')
        ORDER BY source_file, TRY_CAST(source_item_index AS INTEGER)
    """
    rows = connection.execute(query, [start, end]).fetchall()
    grouped: dict[str, list[tuple[Any, ...]]] = {}
    for row in rows:
        if not row[3]:
            raise ValueError("confirmed runner baseline row has no source_file")
        grouped.setdefault(str(row[3]), []).append(row)

    for source_file, file_rows in grouped.items():
        path, file_sha = _checked_source_file(source_file)
        document = _read_json_file(path, compressed=path.suffix.lower() == ".gz")
        items = _response_items(document)
        for row in file_rows:
            meet, event_date, race_no, _, raw_index, horse_id, horse_no, rank, finish_time, horse_name = row
            try:
                item_index = int(raw_index)
                item = items[item_index]
            except (TypeError, ValueError, IndexError) as exc:
                raise ValueError(f"confirmed runner source index is invalid: {source_file}#{raw_index}") from exc
            normalized = _baseline_row(
                "race_results",
                item,
                meet=meet,
                source_file=source_file,
                source_sha256=file_sha,
                source_row_no=item_index,
                source_item_index=item_index,
            )
            expected_key = [str(meet), _date_text(event_date), str(race_no), str(horse_id), str(horse_no)]
            if normalized["key"] != expected_key:
                raise ValueError(f"race result source key disagrees with approved runner: {source_file}#{item_index}")
            # Cross-check source values as well as the natural key so a changed
            # or mis-indexed annual archive cannot silently seed the registry.
            expected_values = {
                "ord": rank,
                "rcTime": finish_time,
                "hrName": horse_name,
            }
            for field, expected in expected_values.items():
                if expected is not None and str(item.get(field)) != str(expected):
                    raise ValueError(f"race result source value disagrees with approved runner: {source_file}#{item_index}:{field}")
            yield normalized


def _iter_baseline_passing_groups(connection: Any, start_iso: str, end_iso: str) -> Iterable[dict[str, Any]]:
    query = """
        SELECT requested_meet, actual_meet_code, race_date_iso, source_path,
               page_sha256, source_captured_at_utc, page_no, row_no, raw_item_json
        FROM passing_api_observations
        WHERE race_date_iso BETWEEN ? AND ?
          AND requested_meet IN (1, 3, 4)
          AND row_scope_status = 'in_scope'
        ORDER BY race_date_iso, actual_meet_code, page_no, row_no
    """
    rows = connection.execute(query, [start_iso, end_iso]).fetchall()
    prefix = "thoroughbred/research/20261002_passing_groups_v1/api_source/"
    for meet, actual_meet, event_date, source_path, page_sha, captured, page_no, row_no, raw_json in rows:
        source_file = prefix + str(source_path)
        # The rows already retain the full validated item JSON and page SHA.
        # Verify any on-disk page we can resolve, but allow a missing archive
        # path because raw_item_json is the authoritative retained source row.
        actual_sha = str(page_sha) if page_sha else None
        source_path_on_disk = _resolve_repository_file(source_file, allow_missing=True)
        if source_path_on_disk is not None:
            actual_sha = _file_sha256(source_path_on_disk)
            if page_sha and actual_sha.lower() != str(page_sha).lower():
                raise ValueError(f"passing group page hash mismatch: {source_file}")
        item = _decode_source_item(raw_json, "passing_groups", source_file)
        normalized = _baseline_row(
            "passing_groups",
            item,
            meet=actual_meet or meet,
            source_file=source_file,
            source_sha256=actual_sha,
            source_row_no=row_no,
            source_item_index=row_no,
            source_captured_at_utc=captured,
        )
        if normalized["event_date"] != event_date:
            raise ValueError(f"passing group source date disagrees with baseline row: {source_file}#{row_no}")
        yield normalized


def _iter_baseline_trials(connection: Any, start_iso: str, end_iso: str) -> Iterable[dict[str, Any]]:
    query = """
        SELECT source_meet_query, trial_date, source_file, source_file_sha256,
               source_item_index, source_record_json
        FROM trial_participants
        WHERE trial_date BETWEEN ? AND ?
          AND source_meet_query IN ('1', '3', '4')
        ORDER BY source_file, TRY_CAST(source_item_index AS INTEGER)
    """
    rows = connection.execute(query, [start_iso, end_iso]).fetchall()
    verified_files: dict[str, str] = {}
    for meet, event_date, source_file, stored_sha, index, raw_json in rows:
        if not source_file:
            raise ValueError("trial baseline row has no source_file")
        if source_file not in verified_files:
            _, verified_files[source_file] = _checked_source_file(source_file, stored_sha)
        item = _decode_source_item(raw_json, "trial_results", source_file)
        normalized = _baseline_row(
            "trial_results",
            item,
            meet=meet,
            source_file=source_file,
            source_sha256=verified_files[source_file],
            source_row_no=index,
            source_item_index=index,
        )
        if normalized["event_date"] != event_date:
            raise ValueError(f"trial source date disagrees with baseline row: {source_file}#{index}")
        yield normalized


def _iter_baseline_steward_family(
    connection: Any,
    family: str,
    dataset: str,
    source_prefix: str,
    start_year: int,
    end_year: int,
    start_iso: str,
    end_iso: str,
) -> Iterable[dict[str, Any]]:
    query = """
        SELECT requested_meet, actual_meet_code, race_date_iso, source_path,
               page_sha256, source_captured_at_utc, page_no, row_no, raw_item_json,
               spDate, stDate, rcDate
        FROM steward_api_source_observations
        WHERE dataset = ?
          AND requested_year BETWEEN ? AND ?
          AND requested_meet IN (1, 3, 4)
          AND row_scope_status = 'included'
        ORDER BY requested_year, requested_meet, page_no, row_no
    """
    rows = connection.execute(query, [dataset, start_year, end_year]).fetchall()
    for meet, actual_meet, db_event_date, source_path, page_sha, captured, page_no, row_no, raw_json, sp_date, st_date, rc_date in rows:
        source_file = source_prefix + str(source_path)
        actual_sha = str(page_sha) if page_sha else None
        on_disk = _resolve_repository_file(source_file, allow_missing=True)
        if on_disk is not None:
            actual_sha = _file_sha256(on_disk)
            if page_sha and actual_sha.lower() != str(page_sha).lower():
                raise ValueError(f"steward source page hash mismatch: {source_file}")
        item = _decode_source_item(raw_json, family, source_file)
        normalized = _baseline_row(
            family,
            item,
            meet=actual_meet or meet,
            source_file=source_file,
            source_sha256=actual_sha,
            source_row_no=row_no,
            source_item_index=row_no,
            source_captured_at_utc=captured,
        )
        event_date = normalized["event_date"]
        if event_date is None or not start_iso <= event_date <= end_iso:
            continue
        yield normalized


def _api78_payload(
    document_path: str,
    expected_sha256: str | None,
    item_index: Any,
    document_cache: dict[tuple[str, str | None], tuple[list[Mapping[str, Any]] | None, str | None, str | None]],
) -> tuple[Mapping[str, Any] | None, str | None, str | None]:
    cache_key = (document_path, expected_sha256)
    if cache_key not in document_cache:
        path = _resolve_repository_file(document_path, allow_missing=True)
        if path is None:
            document_cache[cache_key] = (None, None, "source_document_missing")
        else:
            actual_sha = _file_sha256(path)
            if expected_sha256 and actual_sha.lower() != str(expected_sha256).lower():
                document_cache[cache_key] = (None, actual_sha, "source_document_hash_mismatch")
            else:
                try:
                    document_cache[cache_key] = (_response_items(_read_json_file(path)), actual_sha, None)
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    document_cache[cache_key] = (None, actual_sha, "source_document_payload_unreadable")
    items, actual_sha, error = document_cache[cache_key]
    if items is None:
        return None, actual_sha, error
    try:
        source_index = int(item_index) - 1
    except (TypeError, ValueError):
        return None, actual_sha, "source_item_index_invalid"
    if source_index < 0 or source_index >= len(items):
        return None, actual_sha, "source_item_index_out_of_range"
    return items[source_index], actual_sha, None


def _epoch_ms_iso(value: Any) -> str | None:
    try:
        milliseconds = int(value)
        return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _api78_race_number(value: Any) -> int | None:
    ordinal = _ordinal_text(value)
    return int(ordinal) if ordinal is not None else None


def _iter_baseline_public_cards(connection: Any, start: str, end: str) -> Iterable[dict[str, Any]]:
    query = """
        SELECT source_document_path, source_sha256, source_index_in_batch,
               event_date, meet, race_no, horse_no, capture_retrieved_at_ms
        FROM equipment_api78_card_observations
        WHERE event_date BETWEEN ? AND ?
          AND meet IN ('1', '3', '4')
          AND source_kind = 'operational_source_document'
        ORDER BY source_document_path, page_no, source_index_in_batch
    """
    rows = connection.execute(query, [start, end]).fetchall()
    document_cache: dict[tuple[str, str | None], tuple[list[Mapping[str, Any]] | None, str | None, str | None]] = {}
    for document_path, expected_sha, source_index, event_date, meet, race_no, horse_no, captured_ms in rows:
        payload, actual_sha, unavailable_reason = _api78_payload(
            str(document_path), expected_sha, source_index, document_cache
        )
        request_date = _date_text(event_date)
        if payload is None:
            # Keep only the source locator fields needed to seed the baseline
            # key. Do not make a horse identity from linked-core join columns.
            seed_item: Mapping[str, Any] = {
                "race_dt": event_date,
                "rccrs_cd": meet,
                "rcNo": race_no,
                "chulNo": horse_no,
            }
        else:
            seed_item = payload
        source_file = str(document_path)
        normalized = _baseline_row(
            "public_cards",
            seed_item,
            meet=meet,
            source_file=source_file,
            source_sha256=actual_sha or (str(expected_sha) if expected_sha else None),
            source_row_no=source_index,
            source_item_index=source_index,
            source_captured_at_utc=_epoch_ms_iso(captured_ms),
            requested_date=request_date,
            payload_unavailable=payload is None,
            unavailable_reason=unavailable_reason,
        )
        if normalized["event_date"] != request_date:
            raise ValueError(f"API78 card source date disagrees with baseline observation: {source_file}#{source_index}")
        key = normalized["key"]
        if (
            key[0] != str(meet)
            or key[1] != request_date
            or _api78_race_number(key[2]) != _api78_race_number(race_no)
            or key[3] != str(horse_no)
        ):
            raise ValueError(f"API78 card source key disagrees with baseline observation: {source_file}#{source_index}")
        yield normalized


def iter_baseline_rows(connection: Any, start_iso: str | date, end_iso: str | date) -> Iterable[dict[str, Any]]:
    """Yield normalized legacy rows for the inclusive date window using read-only queries.

    The supplied connection is only used with SELECT statements. Annual race
    results are loaded from the already archived official response gzip and
    are limited to rows that appear in ``confirmed_runners``. Other families
    use retained original JSON rows from the baseline database, with source
    occurrence order and provenance kept intact.
    """
    start_date = _parse_window_date(start_iso)
    end_date = _parse_window_date(end_iso)
    if end_date < start_date:
        raise ValueError("end_iso must be on or after start_iso")
    start = start_date.strftime("%Y%m%d")
    end = end_date.strftime("%Y%m%d")
    start_text = start_date.isoformat()
    end_text = end_date.isoformat()

    yield from _iter_baseline_schedule(connection, start, end)
    yield from _iter_baseline_results(connection, start, end)
    yield from _iter_baseline_passing_groups(connection, start_text, end_text)
    yield from _iter_baseline_trials(connection, start_text, end_text)
    yield from _iter_baseline_steward_family(
        connection,
        "steward_reports",
        "api215_judge_report",
        "thoroughbred/research/20261002_steward_reports_v1/source/",
        start_date.year,
        end_date.year,
        start_text,
        end_text,
    )
    yield from _iter_baseline_steward_family(
        connection,
        "sanctions",
        "api180_1_sanction_history",
        "thoroughbred/research/20261002_steward_reports_v1/source/",
        start_date.year,
        end_date.year,
        start_text,
        end_text,
    )
    yield from _iter_baseline_public_cards(connection, start, end)
