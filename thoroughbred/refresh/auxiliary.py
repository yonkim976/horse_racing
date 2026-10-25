"""Official KRA adapters for thoroughbred training, clinical, and profile data.

The caller owns transport, page capture, completeness checks, and persistence.
These adapters only describe bounded official API requests and normalize one
source row at a time.  Captured page bytes remain the authoritative raw source.
"""

from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from horse_racing.parsers.horse_history import (
    HorseDetailItem,
    HorseMedicalItem,
    HorseTrainingItem,
    parse_meet_code,
)
from horse_racing.parsers.race_supplemental import StartTrainingItem

SEOUL = ZoneInfo("Asia/Seoul")
THOROUGHBRED_MEETS = (1, 3)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_HASH_CACHE: dict[tuple[str, str], str | None] = {}

# API18 monthly queries return daily observations and are bounded by tr_month.
# API16's annual endpoint is clinic_year; the caller must filter its rows by
# requested event date after capture. API21's trainNo is an exam session, not
# a race number, so it is never exposed as race_no.
FAMILY_SPECS: dict[str, dict[str, Any]] = {
    "daily_training": {
        "family": "daily_training",
        "endpoint": "/API18_1/dailyTraining_1",
        "operation": "dailyTraining_1",
        "meets": THOROUGHBRED_MEETS,
        "meet_param": "meet",
        "query_period": "month",
        "month_param": "tr_month",
        "source": "data.go.kr/B551015/API18_1",
    },
    "start_training": {
        "family": "start_training",
        "endpoint": "/API22_1/startingTranning_1",
        "operation": "startingTranning_1",
        "meets": THOROUGHBRED_MEETS,
        "meet_param": "meet",
        "query_period": "month",
        "month_param": "tr_month",
        "source": "data.go.kr/B551015/API22_1",
    },
    "swim_training": {
        "family": "swim_training",
        "endpoint": "/API216/SwimTr",
        "operation": "SwimTr",
        "meets": THOROUGHBRED_MEETS,
        "query_period": "date",
        "date_param": "tr_date",
        "service_key_parameter": "ServiceKey",
        "source": "data.go.kr/B551015/API216",
    },
    "starting_exam": {
        "family": "starting_exam",
        "endpoint": "/API21_1/startingTestResult_1",
        "operation": "startingTestResult_1",
        "meets": THOROUGHBRED_MEETS,
        "meet_param": "meet",
        "query_period": "year",
        "year_param": "tr_year",
        "service_key_parameter": "ServiceKey",
        "source": "data.go.kr/B551015/API21_1",
    },
    "medical": {
        "family": "medical",
        "endpoint": "/API16_1/raceHorseClinic_1",
        "operation": "raceHorseClinic_1",
        "meets": THOROUGHBRED_MEETS,
        "meet_param": "meet",
        "query_period": "year",
        "year_param": "clinic_year",
        "source": "data.go.kr/B551015/API16_1",
    },
    "horse_profile": {
        "family": "horse_profile",
        "endpoint": "/API8_2/raceHorseInfo_2",
        "operation": "raceHorseInfo_2",
        "meets": THOROUGHBRED_MEETS,
        "meet_param": "meet",
        "query_period": "snapshot",
        "source": "data.go.kr/B551015/API8_2",
        "scope_params": {"act_gubun": "y"},
    },
    "jockey_profile": {
        "family": "jockey_profile",
        "endpoint": "/API307/jockeyInfo",
        "operation": "jockeyInfo",
        "meets": THOROUGHBRED_MEETS,
        "meet_param": "meet",
        "query_period": "snapshot",
        "source": "data.go.kr/B551015/API307",
    },
    "trainer_profile": {
        "family": "trainer_profile",
        "endpoint": "/API308/trainerInfo",
        "operation": "trainerInfo",
        "meets": THOROUGHBRED_MEETS,
        "meet_param": "meet",
        "query_period": "snapshot",
        "source": "data.go.kr/B551015/API308",
    },
    "owner_profile": {
        "family": "owner_profile",
        "endpoint": "/API309/horseOwnerInfo",
        "operation": "horseOwnerInfo",
        "meets": THOROUGHBRED_MEETS,
        "meet_param": "meet",
        "query_period": "snapshot",
        "source": "data.go.kr/B551015/API309",
    },
}


def build_requests(start_iso: str, end_iso: str) -> list[dict[str, Any]]:
    """Build bounded public-parameter requests for the supplied event window.

    Monthly and yearly APIs return a wider partition than the requested dates;
    ``event_start``/``event_end`` tell the capture layer which rows to publish.
    Current profile endpoints are deliberately unbounded snapshots.  Their
    observation date comes from the successful response's capture timestamp.
    """
    start = _parse_iso_date(start_iso)
    end = _parse_iso_date(end_iso)
    if end < start:
        raise ValueError("end_iso must be on or after start_iso")

    requests: list[dict[str, Any]] = []
    for family, spec in FAMILY_SPECS.items():
        period = spec["query_period"]
        if period == "snapshot":
            for meet in spec["meets"]:
                requests.append(
                    _request(
                        family,
                        spec,
                        meet,
                        {spec["meet_param"]: str(meet), **spec.get("scope_params", {})},
                        None,
                        None,
                    )
                )
        elif period == "date":
            current = start
            while current <= end:
                params = {spec["date_param"]: current.strftime("%Y%m%d")}
                requests.append(
                    _request(family, spec, None, params, current, current)
                )
                current += timedelta(days=1)
        elif period == "month":
            current = date(start.year, start.month, 1)
            last_month = date(end.year, end.month, 1)
            while current <= last_month:
                month_end = date(
                    current.year, current.month, monthrange(current.year, current.month)[1]
                )
                params_for_month = spec["month_param"]
                for meet in spec["meets"]:
                    requests.append(
                        _request(
                            family,
                            spec,
                            meet,
                            {
                                spec["meet_param"]: str(meet),
                                params_for_month: current.strftime("%Y%m"),
                            },
                            max(start, current),
                            min(end, month_end),
                        )
                    )
                current = _next_month(current)
        elif period == "year":
            for year in range(start.year, end.year + 1):
                year_start = date(year, 1, 1)
                year_end = date(year, 12, 31)
                for meet in spec["meets"]:
                    requests.append(
                        _request(
                            family,
                            spec,
                            meet,
                            {spec["meet_param"]: str(meet), spec["year_param"]: str(year)},
                            max(start, year_start),
                            min(end, year_end),
                        )
                    )
        else:  # Keep a bad spec from silently turning into an empty refresh.
            raise ValueError(f"Unsupported query_period for {family}: {period!r}")
    return requests


def transform(
    family: str,
    payload_row: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any] | None:
    """Normalize one source row; return None for an out-of-scope swim row.

    ``context`` is supplied by the page-capture layer and includes the query
    meet, capture timestamp, and page provenance.  No profile fields are ever
    used to fill missing historical event names or affiliations.
    """
    if family not in FAMILY_SPECS:
        raise ValueError(f"Unsupported auxiliary family: {family!r}")
    if not isinstance(payload_row, dict):
        raise TypeError("payload_row must be an object")

    if family == "daily_training":
        item = HorseTrainingItem.model_validate(payload_row)
        _assert_context_meet(context, item.meet_code)
        return _event(
            family,
            item.training_date,
            item.meet_code,
            item.horse_id,
            None,
            [
                item.training_date.isoformat(), item.meet_code, item.horse_id,
                item.stable_part, item.stable_number, item.trainer_name,
                item.rider_type, item.rider_id, item.started_at_raw, item.ended_at_raw,
                item.duration_seconds, item.canter_count, item.gallop_count, item.entry_plan,
            ],
            payload_row,
            _dump_fields(
                item,
                {
                    "horse_name", "stable_part", "stable_number", "trainer_name",
                    "rider_type", "rider_id", "started_at_raw", "ended_at_raw",
                    "duration_seconds", "canter_count", "gallop_count", "entry_plan",
                },
            ),
        )

    if family == "start_training":
        item = StartTrainingItem.model_validate(payload_row)
        _assert_context_meet(context, item.meet_code)
        return _event(
            family,
            item.training_date,
            item.meet_code,
            item.horse_id,
            None,
            [
                item.training_date.isoformat(), item.meet_code, item.horse_id,
                item.stable_part, item.stable_number, item.rider_name, item.remark,
            ],
            payload_row,
            _dump_fields(
                item,
                {"horse_name", "stable_part", "stable_number", "rider_name", "remark"},
            ),
        )

    if family == "swim_training":
        event_date = _parse_api_date(payload_row.get("trDate"))
        meet_code = parse_meet_code(payload_row.get("meet"))
        if meet_code not in THOROUGHBRED_MEETS:
            return None
        if not context.get("meet"):
            context_meet = str(meet_code)
        else:
            context_meet = str(context["meet"])
            if _meet(context_meet) != meet_code:
                raise ValueError("swim_training_row_meet_query_mismatch")
        horse_id = _optional_id(payload_row.get("hrNo"))
        if event_date is None or horse_id is None:
            raise ValueError("swim_training_missing_event_date_or_horse_id")
        # Keep the raw count unchanged: the API unit is unresolved and old
        # captures preserve zero, negative, and otherwise unusual values.
        count_raw = payload_row.get("cnt")
        count_typed = _optional_int(count_raw)
        fields = {
            "horse_name": _text(payload_row.get("hrName")),
            "swim_count": count_typed,
            "swim_count_raw": count_raw,
            "stable_part": _optional_int(payload_row.get("horsepart")),
            "stable_note": _text(payload_row.get("horsepartMemo")),
            "trainer_part": _optional_int(payload_row.get("trpart")),
            "trainer_name": _text(payload_row.get("trName")),
            "count_unit_status": "unresolved",
        }
        return _event(
            family,
            event_date,
            meet_code,
            horse_id,
            None,
            [
                event_date.isoformat(), meet_code, horse_id, count_raw,
                payload_row.get("horsepart"), payload_row.get("horsepartMemo"),
                payload_row.get("trpart"), payload_row.get("trName"),
            ],
            payload_row,
            fields,
            meet_override=str(meet_code),
        )

    if family == "starting_exam":
        event_date = _parse_api_date(payload_row.get("trainDate"))
        meet_code = parse_meet_code(payload_row.get("meet"))
        if event_date is None or meet_code not in THOROUGHBRED_MEETS:
            raise ValueError("starting_exam_missing_or_out_of_scope_date_meet")
        query_meet = _context_meet(context, meet_code)
        _assert_context_meet(context, meet_code)
        horse_id = _optional_id(payload_row.get("hrNo"))
        typed = {
            "day_serial": _typed_value(payload_row.get("daySerial")),
            "test_no": _typed_value(payload_row.get("trainNo")),
            "program_no": _typed_value(payload_row.get("chulNo")),
            "horse_name": _text(payload_row.get("hrName")),
            "origin_country": _text(payload_row.get("name")),
            "sex": _text(payload_row.get("sex")),
            "age": _optional_int(payload_row.get("age")),
            "rider_name": _text(payload_row.get("rider")),
            "trainer_name": _text(payload_row.get("trName")),
            "trainer_id": _optional_id(payload_row.get("trNo")),
            "owner_name": _text(payload_row.get("owName")),
            "owner_id": _optional_id(payload_row.get("owNo")),
            "pass_flag": _text(payload_row.get("passFlag")),
            "reason": _text(payload_row.get("reason")),
            "no_pass_reason": _text(payload_row.get("nopassReason")),
            "raw_fields": _canonical(payload_row),
        }
        return _event(
            family,
            event_date,
            meet_code,
            horse_id,
            None,
            [
                event_date.isoformat(), meet_code, _typed_value(payload_row.get("daySerial")),
                _typed_value(payload_row.get("trainNo")), _typed_value(payload_row.get("chulNo")),
                horse_id,
            ],
            payload_row,
            typed,
            meet_override=query_meet,
        )

    if family == "medical":
        item = HorseMedicalItem.model_validate(payload_row)
        _assert_context_meet(context, item.meet_code)
        return _event(
            family,
            item.clinic_date,
            item.meet_code,
            item.horse_id,
            None,
            [
                item.clinic_date.isoformat(), item.meet_code, item.horse_id,
                item.stable_part, item.hospital_name, item.diagnosis_1, item.diagnosis_2,
            ],
            payload_row,
            _dump_fields(
                item,
                {"horse_name", "stable_part", "hospital_name", "diagnosis_1", "diagnosis_2"},
            ),
        )

    if family == "horse_profile":
        item = HorseDetailItem.model_validate(payload_row)
        query_meet = _context_meet(context, item.meet_code)
        _assert_context_meet(context, item.meet_code)
        observed_date = _captured_kst_date(context)
        fields = _dump_fields(
            item,
            {
                "horse_name", "birth_date", "sex", "origin_country", "grade", "rating",
                "sire_id", "sire_name", "dam_id", "dam_name", "trainer_id", "trainer_name",
                "owner_id", "owner_name", "race_count_total", "race_count_year", "win_count_total",
                "win_count_year", "second_count_total", "second_count_year", "third_count_total",
                "third_count_year", "prize_money_total_krw", "last_sale_amount_raw",
            },
        )
        fields.update(
            {
                "profile_observed_date": observed_date,
                "profile_scope_meet": query_meet,
                "relationship_time_rule": "current_profile_snapshot_only",
            }
        )
        return _event(
            family,
            date.fromisoformat(observed_date),
            item.meet_code or _meet(query_meet),
            item.horse_id,
            None,
            [observed_date, query_meet, item.horse_id],
            payload_row,
            fields,
            meet_override=query_meet,
        )

    if family in {"jockey_profile", "trainer_profile", "owner_profile"}:
        return _transform_person_profile(family, payload_row, context)

    raise ValueError(f"Unsupported auxiliary family: {family!r}")


def iter_baseline_rows(connection: Any, start_iso: str, end_iso: str):
    """Yield normalized baseline occurrences from the research core, read-only.

    The caller supplies its already-open read-only connection. This iterator
    intentionally caps the baseline to at most 60 calendar days ending at
    ``end_iso``; it never scans the full research history to seed the current
    view. Profile snapshots are excluded because a new current snapshot is
    captured during this refresh.

    ``source_sha256`` is included only when the referenced local source page
    exists inside the repository and its bytes match the stored digest. The
    database's raw payload remains authoritative when a page file is absent.
    """
    requested_start = _parse_iso_date(start_iso)
    requested_end = _parse_iso_date(end_iso)
    if requested_end < requested_start:
        raise ValueError("end_iso must be on or after start_iso")
    baseline_start = max(requested_start, requested_end - timedelta(days=59))
    start_value, end_value = baseline_start.isoformat(), requested_end.isoformat()

    training_rows = _query_rows(
        connection,
        """
        SELECT dataset, event_date, meet, raw_path, raw_sha256,
               source_page_no, source_row_no, source_captured_at, raw_payload_json
        FROM training_raw_observations
        WHERE dataset IN ('daily_training', 'start_training', 'swim_training')
          AND meet IN ('1', '3')
          AND event_date BETWEEN ? AND ?
        ORDER BY dataset, event_date, meet, source_page_no, source_row_no
        """,
        [start_value, end_value],
    )
    for row in training_rows:
        family = str(row["dataset"])
        raw = _load_baseline_payload(row.get("raw_payload_json"), family)
        source_file, source_hash = _baseline_source(
            row.get("raw_path"), row.get("raw_sha256")
        )
        context = {
            "meet": str(row.get("meet") or ""),
            "captured_at_utc": _timestamp_utc(row.get("source_captured_at")),
            "source_file": source_file,
            "source_sha256": source_hash,
            "source_page_no": row.get("source_page_no"),
            "source_row_no": row.get("source_row_no"),
        }
        normalized = transform(family, raw, context)
        if normalized is not None:
            yield _with_baseline_provenance(normalized, context)

    medical_rows = _query_rows(
        connection,
        """
        SELECT event_date, meet_code, source_path, source_sha256, page_no, row_no,
               source_captured_at_utc, raw_payload_json
        FROM medical_observations
        WHERE source_kind = 'api16' AND source_cohort = 'current_annual'
          AND meet_code IN (1, 3)
          AND event_date BETWEEN ? AND ?
        ORDER BY event_date, meet_code, page_no, row_no
        """,
        [start_value, end_value],
    )
    for row in medical_rows:
        raw = _load_baseline_payload(row.get("raw_payload_json"), "medical")
        meet = str(row.get("meet_code") or "")
        source_file, source_hash = _baseline_source(
            row.get("source_path"), row.get("source_sha256")
        )
        context = {
            "meet": meet,
            "captured_at_utc": _timestamp_utc(row.get("source_captured_at_utc")),
            "source_file": source_file,
            "source_sha256": source_hash,
            "source_page_no": row.get("page_no"),
            "source_row_no": row.get("row_no"),
        }
        yield _with_baseline_provenance(transform("medical", raw, context), context)

    exam_rows = _query_rows(
        connection,
        """
        SELECT event_date, meet, raw_path, raw_sha256, source_page_no, source_row_no,
               source_captured_at, raw_payload_json
        FROM starting_exam_observations
        WHERE dataset = 'starting_exam' AND meet IN ('1', '3')
          AND event_date BETWEEN ? AND ?
        ORDER BY event_date, meet, source_page_no, source_row_no
        """,
        [start_value, end_value],
    )
    for row in exam_rows:
        raw = _load_baseline_payload(row.get("raw_payload_json"), "starting_exam")
        source_file, source_hash = _baseline_source(
            row.get("raw_path"), row.get("raw_sha256")
        )
        context = {
            "meet": str(row.get("meet") or ""),
            "captured_at_utc": _timestamp_utc(row.get("source_captured_at")),
            "source_file": source_file,
            "source_sha256": source_hash,
            "source_page_no": row.get("source_page_no"),
            "source_row_no": row.get("source_row_no"),
        }
        yield _with_baseline_provenance(transform("starting_exam", raw, context), context)


def _transform_person_profile(
    family: str,
    row: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    observed_date = _captured_kst_date(context)
    scope_meet = _context_meet(context)
    row_meet = parse_meet_code(row.get("meet"))
    if row_meet is not None:
        _assert_context_meet(context, row_meet)
    common = {
        "profile_observed_date": observed_date,
        "profile_scope_meet": scope_meet,
        "meet_label_raw": _text(row.get("meet")),
        "relationship_time_rule": "current_profile_snapshot_only",
    }
    if family == "jockey_profile":
        identifier, name_key, english_key = "jkNo", "jkName", "jkNameEn"
        fields = {
            **common,
            "english_name": _text(row.get(english_key)),
            "debut_date_raw": _text(row.get("debut")),
            "end_date_raw": _text(row.get("spDate")),
            "part_raw": _text(row.get("part")),
        }
    elif family == "trainer_profile":
        identifier, name_key, english_key = "trNo", "trName", "trNameEn"
        fields = {
            **common,
            "english_name": _text(row.get(english_key)),
            "start_date_raw": _text(row.get("stDate")),
            "end_date_raw": _text(row.get("spDate")),
            "part_raw": _text(row.get("part")),
        }
    else:
        identifier, name_key, english_key = "owNo", "owName", "owNameEn"
        fields = {
            **common,
            "english_name": _text(row.get(english_key)),
            "registration_date_raw": _text(row.get("stDate")),
        }

    official_id = _optional_id(row.get(identifier))
    if official_id is None:
        raise ValueError(f"{family}_missing_official_id")
    fields["official_id"] = official_id
    fields["name"] = _text(row.get(name_key))
    # API307/308/309 also return performance totals. Keep these in the captured
    # source page only; the profile observation is an identity snapshot.
    profile_payload = {
        identifier: row.get(identifier),
        name_key: row.get(name_key),
        english_key: row.get(english_key),
        "meet": row.get("meet"),
    }
    date_key = "debut" if family == "jockey_profile" else "stDate"
    end_key = "spDate" if family != "owner_profile" else None
    part_key = "part" if family != "owner_profile" else None
    if date_key in row:
        profile_payload[date_key] = row.get(date_key)
    if end_key and end_key in row:
        profile_payload[end_key] = row.get(end_key)
    if part_key and part_key in row:
        profile_payload[part_key] = row.get(part_key)

    return _event(
        family,
        date.fromisoformat(observed_date),
        _meet(scope_meet),
        None,
        None,
        [observed_date, scope_meet, official_id],
        profile_payload,
        fields,
        meet_override=scope_meet,
    )


def _query_rows(connection: Any, statement: str, parameters: list[Any]) -> list[dict[str, Any]]:
    """Execute a fixed, parameterized read and return named rows."""
    cursor = connection.execute(statement, parameters)
    names = [str(column[0]) for column in cursor.description]
    return [dict(zip(names, values, strict=True)) for values in cursor.fetchall()]


def _with_baseline_provenance(
    normalized: dict[str, Any] | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    if normalized is None:
        raise ValueError("out_of_scope_baseline_row")
    return {
        **normalized,
        "baseline": True,
        "source_file": context.get("source_file"),
        "source_sha256": context.get("source_sha256"),
        "source_page_no": context.get("source_page_no"),
        "source_row_no": context.get("source_row_no"),
        "captured_at_utc": context.get("captured_at_utc"),
    }


def _load_baseline_payload(value: Any, family: str) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        raise ValueError(f"baseline_{family}_raw_payload_missing")
    try:
        payload = json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"baseline_{family}_raw_payload_invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"baseline_{family}_raw_payload_not_object")
    return payload


def _baseline_source(path_value: Any, claimed_hash: Any) -> tuple[str | None, str | None]:
    """Keep a repository-relative source pointer and only attest verified bytes."""
    if path_value in (None, ""):
        return None, None
    original = str(path_value)
    path = Path(original)
    candidate = (path if path.is_absolute() else REPOSITORY_ROOT / path).resolve()
    root = REPOSITORY_ROOT.resolve()
    if not candidate.is_relative_to(root):
        return None, None
    source_file = candidate.relative_to(root).as_posix()
    expected = str(claimed_hash or "").strip().lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        return source_file, None
    cache_key = (str(candidate), expected)
    if cache_key not in _SOURCE_HASH_CACHE:
        actual: str | None = None
        try:
            digest = hashlib.sha256()
            with candidate.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            actual = digest.hexdigest()
        except OSError:
            actual = None
        _SOURCE_HASH_CACHE[cache_key] = expected if actual == expected else None
    return source_file, _SOURCE_HASH_CACHE[cache_key]


def _timestamp_utc(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    else:
        parsed = parsed.astimezone(UTC)
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _request(
    family: str,
    spec: dict[str, Any],
    meet: int | None,
    params: dict[str, Any],
    event_start: date | None,
    event_end: date | None,
) -> dict[str, Any]:
    result = {
        "family": family,
        "endpoint": spec["endpoint"],
        "operation": spec["operation"],
        "query_period": spec["query_period"],
        "params": params,
        "meet": str(meet) if meet is not None else "",
        "requested_meet": meet,
        "event_start": event_start.isoformat() if event_start else None,
        "event_end": event_end.isoformat() if event_end else None,
        "source": spec["source"],
        **(
            {"service_key_parameter": spec["service_key_parameter"]}
            if "service_key_parameter" in spec
            else {}
        ),
    }
    if spec["query_period"] == "date":
        result["requested_date"] = datetime.strptime(
            params[spec["date_param"]], "%Y%m%d"
        ).date().isoformat()
    elif spec["query_period"] == "month":
        result["requested_month"] = params[spec["month_param"]]
    elif spec["query_period"] == "year":
        result["requested_year"] = params[spec["year_param"]]
    return result


def _event(
    family: str,
    event_date: date,
    meet: int,
    horse_id: str | None,
    race_no: str | None,
    key: list[Any],
    payload: dict[str, Any],
    fields: dict[str, Any],
    *,
    meet_override: str | None = None,
) -> dict[str, Any]:
    return {
        "family": family,
        "event_date": event_date.isoformat(),
        "meet": meet_override or str(meet),
        "key": _canonical(key),
        "horse_id": horse_id,
        "race_no": race_no,
        "payload": _canonical(payload),
        "fields": _canonical(fields),
    }


def _dump_fields(item: Any, names: set[str]) -> dict[str, Any]:
    return _canonical(item.model_dump(mode="json", include=names, exclude_none=False))


def _canonical(value: Any) -> Any:
    """Return recursively sorted JSON-compatible source/typed data."""
    if isinstance(value, dict):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=lambda v: str(v))}
    if isinstance(value, (list, tuple)):
        return [_canonical(part) for part in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _parse_iso_date(value: str) -> date:
    if not isinstance(value, str):
        raise TypeError("date window values must be ISO strings")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("date window values must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError("date window values must use YYYY-MM-DD")
    return parsed


def _parse_api_date(value: Any) -> date | None:
    if value in (None, "", "-"):
        return None
    text_value = str(value).strip()
    try:
        if len(text_value) == 8 and text_value.isdigit():
            return datetime.strptime(text_value, "%Y%m%d").date()
        return date.fromisoformat(text_value)
    except ValueError:
        return None


def _captured_kst_date(context: dict[str, Any]) -> str:
    captured = context.get("captured_at_utc")
    if not isinstance(captured, str) or not captured.strip():
        raise ValueError("profile_context_missing_captured_at_utc")
    value = captured.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("profile_context_invalid_captured_at_utc") from exc
    if parsed.tzinfo is None:
        raise ValueError("profile_context_captured_at_must_have_timezone")
    return parsed.astimezone(SEOUL).date().isoformat()


def _context_meet(context: dict[str, Any], fallback: int | None = None) -> str:
    value = context.get("meet")
    code = _meet(value) if value not in (None, "") else fallback
    if code not in THOROUGHBRED_MEETS:
        raise ValueError("auxiliary_context_meet_out_of_scope")
    return str(code)


def _assert_context_meet(context: dict[str, Any], row_meet: int | None) -> None:
    query_meet = context.get("meet")
    if query_meet in (None, ""):
        return
    query_code = _meet(query_meet)
    if query_code not in THOROUGHBRED_MEETS or row_meet != query_code:
        raise ValueError("auxiliary_row_meet_query_mismatch")


def _meet(value: Any) -> int | None:
    return parse_meet_code(value)


def _optional_id(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized if normalized and normalized != "-" else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized if normalized and normalized != "-" else None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "" or value == "-":
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError, OverflowError):
        return None


def _typed_value(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _next_month(value: date) -> date:
    return date(value.year + (value.month == 12), 1 if value.month == 12 else value.month + 1, 1)
