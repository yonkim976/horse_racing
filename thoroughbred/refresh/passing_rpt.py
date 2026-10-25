"""Optional, provenance-preserving Dacom11 confirmation for held API303 points.

The resolver only uses exact official archive-list entries for requested race
days. It never guesses a filename, infers a passing point from API corner
order, or writes to the operating database. Callers provide the existing
``KraTextClient`` so network access remains an explicit caller decision.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from horse_racing.collectors.kra_text import KraTextClient, KraTextFile, TEXT_FILE_TYPES
from horse_racing.parsers.dacom11 import parse_dacom11_report


MAX_RACE_DAYS = 20
_RPT_CODE_NAME = TEXT_FILE_TYPES["dacom11"]
_TITLE = re.compile(
    r"^제목\s*:\s*(?P<year>\d{2,4})년\s*(?P<month>\d{1,2})월\s*"
    r"(?P<day>\d{1,2})일.*?제\s*(?P<race>\d+)경주"
)
_VENUE = re.compile(r"^\((?P<venue>[^)]+)\)\s*제\s*(?P<day_count>\d+)일")
_POINT = re.compile(
    r"^\s*(?:통과순위\s+)?(?P<label>S-?1F|C[1-4]|[1-4]C|G-?(?:8|6|4|3|2|1)F)\s*:"
)
_VENUE_TO_MEET = {"서울": 1, "부산": 3, "부경": 3, "부산경남": 3, "영천": 4}
_POINT_TO_CANONICAL = {
    1: {
        "C1": "1C", "1C": "1C", "C2": "2C", "2C": "2C",
        "C3": "3C", "3C": "3C", "C4": "4C", "4C": "4C",
        "S-1F": "S1F", "S1F": "S1F", "G-1F": "G1F", "G1F": "G1F",
    },
    3: {
        "G8F": "G8F", "G6F": "G6F", "G4F": "G4F", "G3F": "G3F",
        "G2F": "G2F", "G1F": "G1F", "S1F": "S1F",
    },
    4: {
        "G8F": "G8F", "G6F": "G6F", "G4F": "G4F", "G3F": "G3F",
        "G2F": "G2F", "G1F": "G1F", "S1F": "S1F",
    },
}
_ARCHIVE_MEET = {1: 1, 3: 3, 4: 3}


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"invalid event date: {value!r}")


def _positive_race_no(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("race_no must be a positive integer")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"(?:제\s*)?([0-9]+)(?:\s*경주)?", value.strip()):
        number = int(re.fullmatch(r"(?:제\s*)?([0-9]+)(?:\s*경주)?", value.strip()).group(1))
    else:
        raise ValueError(f"race_no is not a supported ordinal: {value!r}")
    if number < 1:
        raise ValueError("race_no must be positive")
    return number


def _target(row: Mapping[str, Any]) -> dict[str, Any]:
    meet = int(row["meet"])
    if meet not in _ARCHIVE_MEET:
        raise ValueError(f"unsupported meet for Dacom11: {meet}")
    event_date = _as_date(row["event_date"])
    race_no = _positive_race_no(row["race_no"])
    point = str(row.get("canonical_point_candidate") or "")
    source_field = str(row.get("source_field") or "")
    notation = row.get("notation_raw")
    if point not in set(_POINT_TO_CANONICAL[meet].values()):
        raise ValueError(f"unsupported canonical point {point!r} for meet {meet}")
    if not re.fullmatch(r"corner_[1-9]", source_field):
        raise ValueError(f"invalid API source field: {source_field!r}")
    if row.get("hold_status") not in (None, "ambiguous_repeated_notation"):
        raise ValueError(f"resolver only accepts repeated-notation holds, got {row.get('hold_status')!r}")
    return {
        "meet": meet,
        "event_date": event_date,
        "race_no": race_no,
        "canonical_point_candidate": point,
        "source_field": source_field,
        "api_notation_raw": None if notation is None else str(notation),
        "api_notation_compare_text": None if notation is None else str(notation).strip(" "),
        "api_source_file": row.get("source_file"),
        "api_source_sha256": row.get("source_sha256"),
        "api_source_row_no": row.get("source_row_no"),
        "api_record_id": row.get("record_id"),
    }


def _line_records(raw: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Capture official title, venue, and passing-point lines with byte offsets."""
    races: list[dict[str, Any]] = []
    points: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    current: dict[str, Any] | None = None
    byte_offset = 0
    for line_no, physical_line in enumerate(raw.splitlines(keepends=True), 1):
        body = physical_line.rstrip(b"\r\n")
        line = body.decode("cp949", errors="strict")
        if line.startswith("제목") and "경주" in line:
            match = _TITLE.search(line)
            current = None
            pending = None
            if match:
                year = int(match.group("year"))
                if year < 100:
                    year += 2000 if year < 80 else 1900
                pending = {
                    "event_date": date(year, int(match.group("month")), int(match.group("day"))).isoformat(),
                    "race_no": int(match.group("race")),
                    "title_line_no": line_no,
                    "title_byte_offset": byte_offset,
                    "title_line_raw": line,
                }

        venue_match = _VENUE.match(line)
        if venue_match and pending is not None:
            venue = venue_match.group("venue").strip()
            actual_meet = _VENUE_TO_MEET.get(venue)
            if actual_meet is not None:
                current = {
                    **pending,
                    "meet": actual_meet,
                    "venue_raw": venue,
                    "venue_line_no": line_no,
                    "venue_byte_offset": byte_offset,
                    "venue_line_raw": line,
                    "point_lines": [],
                }
                races.append(current)
            pending = None

        point_match = _POINT.match(line)
        if current is not None and point_match:
            colon_offset = body.find(b":")
            if colon_offset < 0:
                raise ValueError(f"point label has no ASCII colon at byte line {line_no}")
            notation_raw = body[colon_offset + 1 :].decode("cp949", errors="strict")
            point = {
                "print_label_raw": point_match.group("label"),
                "notation_raw": notation_raw,
                "line_no": line_no,
                "byte_offset": byte_offset,
                "line_byte_length": len(physical_line),
                "colon_byte_offset_in_line": colon_offset,
                "raw_line": line,
                "raw_line_bytes_hex": physical_line.hex(),
            }
            current["point_lines"].append(point)
            points.append({**current, **point})
        byte_offset += len(physical_line)
    return races, points


def _parser_race_keys(raw: bytes) -> list[tuple[int, str, int]]:
    parsed = parse_dacom11_report(raw)
    keys: list[tuple[int, str, int]] = []
    for race in parsed:
        meet = _VENUE_TO_MEET.get(race.meet_name.strip())
        if meet is not None:
            keys.append((meet, race.race_date.isoformat(), int(race.race_number)))
    return keys


def _file_metadata(file: KraTextFile, body: bytes, report: Any) -> dict[str, Any]:
    return {
        "archive_meet": int(file.meet),
        "file_type": file.file_type,
        "filename": file.filename,
        "remote_path": file.remote_path,
        "file_date": file.file_date.isoformat() if file.file_date else None,
        "list_page": file.list_page,
        "listed_size_bytes": file.listed_size_bytes,
        "source_sha256": hashlib.sha256(body).hexdigest(),
        "source_bytes": len(body),
        "source_url": getattr(report, "source_url", None),
        "status_code": getattr(report, "status_code", None),
        "content_type": getattr(report, "content_type", None),
        "requested_at_ms": getattr(report, "requested_at_ms", None),
        "retrieved_at_ms": getattr(report, "retrieved_at_ms", None),
    }


def resolve_passing_points(
    holds: Iterable[Mapping[str, Any]],
    *,
    client: KraTextClient,
    max_race_days: int = MAX_RACE_DAYS,
    max_pages_per_date: int = 1,
) -> dict[str, Any]:
    """Resolve exact held API303 values against labeled points in official RPTs.

    The caller controls the client lifetime and therefore the network operation.
    Only official ``dacom11`` files returned by the archive listing for each
    requested race date can be fetched. A point is confirmed only when its
    nominal label, meet/date/race header, and ASCII-space-trimmed notation all
    match exactly; no value or point is inferred from corner order.
    """
    if max_race_days < 1 or max_race_days > MAX_RACE_DAYS:
        raise ValueError(f"max_race_days must be between 1 and {MAX_RACE_DAYS}")
    if max_pages_per_date < 1 or max_pages_per_date > 10:
        raise ValueError("max_pages_per_date must be between 1 and 10")
    targets = [_target(row) for row in holds]
    race_days = {(row["meet"], row["event_date"]) for row in targets}
    if len(race_days) > max_race_days:
        raise ValueError(f"requested {len(race_days)} race days; maximum is {max_race_days}")

    targets_by_day: dict[tuple[int, date], list[dict[str, Any]]] = defaultdict(list)
    for row in targets:
        targets_by_day[(row["meet"], row["event_date"])].append(row)

    file_by_day: dict[tuple[int, date], tuple[KraTextFile | None, str | None]] = {}
    for meet, event_date in sorted(race_days):
        archive_meet = _ARCHIVE_MEET[meet]
        try:
            listed = list(
                client.iter_files(
                    meet=archive_meet,
                    file_type="dacom11",
                    code_name=_RPT_CODE_NAME,
                    start_date=event_date,
                    end_date=event_date,
                    max_pages=max_pages_per_date,
                )
            )
        except Exception as exc:  # Keep per-day archive/list failures explicit.
            file_by_day[(meet, event_date)] = (None, f"official_list_error:{type(exc).__name__}")
            continue
        exact = [
            item for item in listed
            if item.meet == archive_meet
            and item.file_type == "dacom11"
            and item.file_date == event_date
        ]
        if len(exact) == 1:
            file_by_day[(meet, event_date)] = (exact[0], None)
        elif not exact:
            file_by_day[(meet, event_date)] = (None, "official_file_not_listed_for_exact_date")
        else:
            file_by_day[(meet, event_date)] = (None, "multiple_official_files_listed_for_exact_date")

    file_meta_by_day: dict[tuple[int, date], dict[str, Any]] = {}
    report_by_race: dict[tuple[int, str, int], dict[str, Any]] = {}
    for key, (file, list_error) in file_by_day.items():
        if file is None:
            file_meta_by_day[key] = {
                "meet": key[0],
                "event_date": key[1].isoformat(),
                "archive_meet": _ARCHIVE_MEET[key[0]],
                "file_type": "dacom11",
                "status": list_error or "official_file_unavailable",
            }
            continue
        try:
            report = client.fetch_file(file)
            raw = report.body
            metadata = _file_metadata(file, raw, report)
            parsed_keys = _parser_race_keys(raw)
            line_races, _ = _line_records(raw)
        except Exception as exc:
            file_meta_by_day[key] = {
                "status": f"official_file_parse_or_download_error:{type(exc).__name__}",
                "filename": file.filename,
                "remote_path": file.remote_path,
            }
            continue
        file_meta_by_day[key] = {**metadata, "status": "downloaded_and_parsed"}
        for target in targets_by_day[key]:
            race_key = (target["meet"], target["event_date"].isoformat(), target["race_no"])
            parsed_matches = [entry for entry in parsed_keys if entry == race_key]
            line_matches = [
                race for race in line_races
                if (race["meet"], race["event_date"], race["race_no"]) == race_key
            ]
            report_by_race[race_key] = {
                "file_metadata": metadata,
                "parser_match_count": len(parsed_matches),
                "line_header_match_count": len(line_matches),
                "race": line_matches[0] if len(line_matches) == 1 else None,
            }

    resolutions: list[dict[str, Any]] = []
    for target in targets:
        race_key = (target["meet"], target["event_date"].isoformat(), target["race_no"])
        day_key = (target["meet"], target["event_date"])
        file, list_error = file_by_day[day_key]
        base = {
            **target,
            "event_date": target["event_date"].isoformat(),
            "race_no": str(target["race_no"]),
        }
        if file is None:
            resolutions.append({
                **base,
                "resolution_status": list_error or "official_file_unavailable",
                "rpt_file": file_meta_by_day.get(day_key),
            })
            continue
        race_report = report_by_race.get(race_key)
        if race_report is None:
            file_meta = file_meta_by_day.get(day_key, {})
            resolutions.append({
                **base,
                "resolution_status": file_meta.get("status", "official_file_unavailable"),
                "rpt_file": file_meta,
            })
            continue
        race = race_report["race"]
        if race_report["parser_match_count"] != 1 or race_report["line_header_match_count"] != 1 or race is None:
            resolutions.append({
                **base,
                "resolution_status": "race_header_not_uniquely_confirmed",
                "rpt_file": race_report["file_metadata"],
                "parser_match_count": race_report["parser_match_count"],
                "line_header_match_count": race_report["line_header_match_count"],
            })
            continue

        expected_point = target["canonical_point_candidate"]
        point_lines = [
            point for point in race["point_lines"]
            if _POINT_TO_CANONICAL[target["meet"]].get(point["print_label_raw"]) == expected_point
        ]
        if len(point_lines) != 1:
            resolutions.append({
                **base,
                "resolution_status": "rpt_point_line_missing_or_ambiguous",
                "rpt_file": race_report["file_metadata"],
                "rpt_race_header": {k: v for k, v in race.items() if k != "point_lines"},
                "rpt_point_line_count": len(point_lines),
            })
            continue
        point = point_lines[0]
        if target["api_notation_compare_text"] is None or target["api_notation_compare_text"] == "":
            resolution_status = "api_notation_blank"
        elif point["notation_raw"].strip(" ") != target["api_notation_compare_text"]:
            resolution_status = "rpt_value_does_not_match_api_value"
        else:
            resolution_status = "resolved_exact_rpt_label_value_match"
        resolutions.append({
            **base,
            "resolution_status": resolution_status,
            "canonical_point": expected_point if resolution_status == "resolved_exact_rpt_label_value_match" else None,
            "rpt_file": race_report["file_metadata"],
            "rpt_race_header": {k: v for k, v in race.items() if k != "point_lines"},
            "rpt_print_label": point["print_label_raw"],
            "rpt_notation_raw": point["notation_raw"],
            "rpt_line_no": point["line_no"],
            "rpt_byte_offset": point["byte_offset"],
            "rpt_line_byte_length": point["line_byte_length"],
            "rpt_colon_byte_offset_in_line": point["colon_byte_offset_in_line"],
            "rpt_raw_line": point["raw_line"],
            "rpt_raw_line_bytes_hex": point["raw_line_bytes_hex"],
        })

    resolved_points: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in resolutions:
        if row["resolution_status"] != "resolved_exact_rpt_label_value_match":
            continue
        key = "|".join((str(row["meet"]), row["event_date"], row["race_no"], row["source_field"]))
        resolved_points[key].append({
            "canonical_point": row["canonical_point"],
            "notation_raw": row["api_notation_raw"],
            "source_field": row["source_field"],
            "rpt_print_label": row["rpt_print_label"],
            "rpt_notation_raw": row["rpt_notation_raw"],
            "rpt_filename": row["rpt_file"]["filename"],
            "rpt_remote_path": row["rpt_file"]["remote_path"],
            "rpt_sha256": row["rpt_file"]["source_sha256"],
            "rpt_line_no": row["rpt_line_no"],
            "rpt_byte_offset": row["rpt_byte_offset"],
            "rpt_raw_line": row["rpt_raw_line"],
            "event_date": row["event_date"],
            "race_no": row["race_no"],
            "meet": row["meet"],
        })
    return {
        "schema_version": 1,
        "resolver": "official_dacom11_exact_label_value_match",
        "requested_race_day_count": len(race_days),
        "max_race_days": max_race_days,
        "files": [file_meta_by_day[key] for key in sorted(file_meta_by_day)],
        "resolutions": resolutions,
        "resolved_points": dict(resolved_points),
    }
