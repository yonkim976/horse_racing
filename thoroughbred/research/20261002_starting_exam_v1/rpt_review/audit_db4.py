#!/usr/bin/env python3
"""Read-only audit of KRA DB4 starting-exam text files."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
INPUT_ROOT = (ROOT / "data/raw/kra_text/db4").resolve()
OUTPUT_ROOT = Path(__file__).resolve().parent.resolve()
SCOPE_START = date(2010, 1, 1)
SCOPE_END = date(2026, 9, 29)
IN_SCOPE_MEETS = {"1", "3"}
MEET_LABELS = {
    "1": "Seoul",
    "2": "Jeju (excluded)",
    "3": "Yeongnam (API region code; physical venue not inferred)",
    "4": "No local files found",
}

PATH_RE = re.compile(r"meet=(\d+)/year=(\d{4})/month=(\d{2})/day=(\d{2})")
FILENAME_DATE_RE = re.compile(r"^(\d{8})")
TITLE_RE = re.compile(
    r"제목\s*[:：]\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일"
)
EXAM_TURN_RE = re.compile(r"제\s*(\d+)\s*차")
RACE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*경주")
ROW_RE = re.compile(r"^\s*(\d{1,2})[ \t]{2,}")
JUDGMENT_RE = re.compile(
    r"^(?:\d+차)?(?:출발)?(?:불)?합격(?:유보)?$|^(?:출주|출전|경주|심사)취소$|^출전제외$"
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_relative(path: Path, base: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(base):
        raise ValueError(f"Path escaped expected root: {path}")
    return resolved.relative_to(ROOT).as_posix()


def decode_text(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig", errors="strict"), "utf-8-sig"
    try:
        return data.decode("utf-8", errors="strict"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp949", errors="strict"), "cp949"


def parse_path_date(path: Path) -> tuple[str | None, str | None, str | None, list[str]]:
    rel = path.relative_to(INPUT_ROOT).as_posix()
    match = PATH_RE.search(rel)
    flags: list[str] = []
    meet = match.group(1) if match else None
    folder_date = None
    if match:
        try:
            folder_date = date(
                int(match.group(2)), int(match.group(3)), int(match.group(4))
            ).isoformat()
        except ValueError:
            flags.append("invalid_path_date_components")
    else:
        flags.append("path_meet_or_date_unparsed")
    name_match = FILENAME_DATE_RE.match(path.name)
    filename_date = None
    if name_match:
        raw = name_match.group(1)
        try:
            filename_date = date(
                int(raw[:4]), int(raw[4:6]), int(raw[6:8])
            ).isoformat()
        except ValueError:
            flags.append("invalid_filename_date")
    else:
        flags.append("filename_date_unparsed")
    if folder_date and filename_date and folder_date != filename_date:
        flags.append("folder_filename_date_mismatch")
    return meet, folder_date, filename_date, flags


def title_metadata(line: str) -> dict[str, Any]:
    date_match = TITLE_RE.search(line)
    body_date = None
    date_error = False
    if date_match:
        try:
            body_date = date(
                int(date_match.group(1)),
                int(date_match.group(2)),
                int(date_match.group(3)),
            ).isoformat()
        except ValueError:
            date_error = True
    turn_match = EXAM_TURN_RE.search(line)
    race_match = RACE_RE.search(line)
    return {
        "body_date": body_date,
        "body_date_error": date_error,
        "exam_turn": turn_match.group(1) if turn_match else None,
        "race_no": race_match.group(1) if race_match else None,
        "raw_title": line.strip(),
    }


def header_offsets(header: str, encoding: str) -> dict[str, int | None]:
    raw = header.encode(encoding)
    exam_at = raw.find("심사사유".encode(encoding))
    exam_end_candidates = [
        idx
        for idx in (
            raw.find("산지".encode(encoding)),
            raw.find("성별".encode(encoding)),
        )
        if idx >= 0 and idx > exam_at
    ]
    decision_at = raw.find("판정".encode(encoding))
    reason_at = raw.rfind("사유".encode(encoding))
    horse_no_at = raw.find("마번".encode(encoding))
    return {
        "horse_no": horse_no_at if horse_no_at >= 0 else None,
        "exam_reason": exam_at if exam_at >= 0 else None,
        "exam_reason_end": min(exam_end_candidates) if exam_end_candidates else None,
        "judgment": decision_at if decision_at >= 0 else None,
        "decision_reason": reason_at if reason_at >= 0 else None,
    }


def col_text(raw: bytes, start: int | None, end: int | None, encoding: str) -> str | None:
    if start is None:
        return None
    return raw[start:end].decode(encoding, errors="strict").strip()


def judgment_from_line_tail(line: str) -> tuple[str | None, str | None, str]:
    """Recover shifted final columns from whitespace-separated tail fields."""
    parts = [part for part in re.split(r"[ \t]{2,}", line.strip()) if part]
    if parts and JUDGMENT_RE.fullmatch(parts[-1]):
        return parts[-1], None, "tail_judgment_only"
    if len(parts) > 1 and JUDGMENT_RE.fullmatch(parts[-2]):
        return parts[-2], parts[-1], "tail_judgment_and_reason"
    return None, None, "tail_unresolved"


def csv_write(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                    if isinstance(value, (list, dict))
                    else value
                    for key, value in row.items()
                }
            )


def main() -> None:
    if not INPUT_ROOT.is_dir():
        raise FileNotFoundError(INPUT_ROOT)
    if not OUTPUT_ROOT.is_relative_to(ROOT):
        raise ValueError("Output must remain inside the repository research root")
    if INPUT_ROOT == OUTPUT_ROOT or OUTPUT_ROOT.is_relative_to(INPUT_ROOT):
        raise ValueError("Output directory overlaps source directory")

    paths = sorted(path for path in INPUT_ROOT.rglob("*.txt") if path.is_file())
    manifest_files: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    year_meet_files: Counter[tuple[int, str]] = Counter()
    year_meet_rows: Counter[tuple[int, str]] = Counter()
    year_meet_titles: Counter[tuple[int, str]] = Counter()
    year_meet_body_dates: dict[tuple[int, str], list[str]] = defaultdict(list)
    year_meet_path_dates: dict[tuple[int, str], list[str]] = defaultdict(list)
    year_meet_filename_dates: dict[tuple[int, str], list[str]] = defaultdict(list)
    year_meet_missing_body_date: Counter[tuple[int, str]] = Counter()
    year_meet_body_path_mismatch: Counter[tuple[int, str]] = Counter()
    year_meet_body_filename_mismatch: Counter[tuple[int, str]] = Counter()
    year_meet_header_signatures: dict[tuple[int, str], set[str]] = defaultdict(set)
    verdict_reasons: Counter[tuple[str, str, str]] = Counter()
    body_presence: Counter[tuple[str, str]] = Counter()
    body_row_counts: Counter[tuple[str, str]] = Counter()
    encoding_counts: Counter[str] = Counter()
    rows_by_meet: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    headers_without_official_id: Counter[str] = Counter()
    ignored_nontext = [safe_relative(path, INPUT_ROOT) for path in INPUT_ROOT.iterdir() if path.is_file() and path.suffix.lower() != ".txt"]

    for path in paths:
        rel_path = safe_relative(path, INPUT_ROOT)
        data = path.read_bytes()
        digest = sha256(data)
        meet, directory_date, filename_date, path_flags = parse_path_date(path)
        path_date = directory_date or filename_date
        try:
            text, encoding = decode_text(data)
        except UnicodeDecodeError as exc:
            errors.append({"path": rel_path, "error": f"decode_error:{exc}"})
            manifest_files.append(
                {
                    "path": rel_path,
                    "sha256": digest,
                    "size_bytes": len(data),
                    "path_meet": meet,
                    "path_date": path_date,
                    "directory_date": directory_date,
                    "filename_date": filename_date,
                    "encoding": "decode_error",
                    "line_count": None,
                    "body_dates": [],
                    "body_title_count": 0,
                    "table_header": None,
                    "candidate_row_count": 0,
                    "scope_meet_included": meet in IN_SCOPE_MEETS,
                    "scope_body_date_included": False,
                    "flags": path_flags + ["decode_error"],
                }
            )
            continue

        encoding_counts[encoding] += 1
        lines = text.splitlines()
        headings = [
            (line_no, title_metadata(line))
            for line_no, line in enumerate(lines, start=1)
            if re.search(r"제목\s*[:：]", line)
        ]
        titled_dates = [entry[1]["body_date"] for entry in headings if entry[1]["body_date"]]
        unique_body_dates = sorted(set(titled_dates))
        header = next(
            (line for line in lines if "마번" in line and "판정" in line), None
        )
        offsets = header_offsets(header, encoding) if header else {}
        header_signature = header.strip() if header else None
        if header_signature:
            year_match = PATH_RE.search(path.relative_to(INPUT_ROOT).as_posix())
            if year_match and meet:
                year_meet_header_signatures[(int(year_match.group(2)), meet)].add(header_signature)
        official_id_header_tokens = [
            token
            for token in ("공식마번", "등록번호", "개체번호", "KRA ID", "말등록번호", "마필번호")
            if header and token in header
        ]
        if header and not official_id_header_tokens and meet:
            headers_without_official_id[meet] += 1

        title_cursor = 0
        active_title: dict[str, Any] | None = None
        title_by_line: dict[int, dict[str, Any]] = {}
        for line_no, metadata in headings:
            title_cursor += 1
            active_title = {**metadata, "section_no": title_cursor, "title_line_no": line_no}
            title_by_line[line_no] = active_title

        per_file_judgment: Counter[str] = Counter()
        per_file_decision_reason: Counter[str] = Counter()
        file_rows: list[dict[str, Any]] = []
        current_title: dict[str, Any] | None = None
        for line_no, line in enumerate(lines, start=1):
            if line_no in title_by_line:
                current_title = title_by_line[line_no]
            row_match = ROW_RE.match(line)
            if not row_match:
                continue
            row_bytes = line.encode(encoding)
            if offsets and all(
                offsets.get(key) is not None
                for key in ("exam_reason", "exam_reason_end", "judgment", "decision_reason")
            ):
                # The text is aligned to the table header. Preserve the full source line
                # alongside the trimmed individual cells for review.
                rank_bytes_end = len(line[: row_match.end()].encode(encoding))
                local_number = row_match.group(1)
                horse_name = col_text(
                    row_bytes,
                    rank_bytes_end,
                    offsets["exam_reason"],
                    encoding,
                )
                exam_reason = col_text(
                    row_bytes,
                    offsets["exam_reason"],
                    offsets["exam_reason_end"],
                    encoding,
                )
                try:
                    judgment = col_text(
                        row_bytes,
                        offsets["judgment"],
                        offsets["decision_reason"],
                        encoding,
                    )
                    decision_reason = col_text(
                        row_bytes, offsets["decision_reason"], None, encoding
                    )
                    if (judgment and not JUDGMENT_RE.fullmatch(judgment)) or (
                        not judgment and decision_reason and JUDGMENT_RE.fullmatch(decision_reason)
                    ):
                        judgment, decision_reason, parse_status = judgment_from_line_tail(line)
                    else:
                        parse_status = "header_byte_offsets"
                except UnicodeDecodeError:
                    judgment, decision_reason, parse_status = judgment_from_line_tail(line)
            else:
                parts = re.split(r"\s{2,}", line.strip())
                local_number = row_match.group(1)
                horse_name = parts[1] if len(parts) > 1 else None
                exam_reason = parts[2] if len(parts) > 2 else None
                judgment = None
                decision_reason = None
                judgment, decision_reason, tail_status = judgment_from_line_tail(line)
                parse_status = f"limited_no_header_offsets_{tail_status}"

            body_date = current_title.get("body_date") if current_title else None
            if body_date is None and len(unique_body_dates) == 1:
                body_date = unique_body_dates[0]
            year_match = PATH_RE.search(path.relative_to(INPUT_ROOT).as_posix())
            path_year = int(year_match.group(2)) if year_match else None
            in_body_scope = bool(
                body_date
                and SCOPE_START.isoformat() <= body_date <= SCOPE_END.isoformat()
            )
            row = {
                "source_path": rel_path,
                "source_sha256": digest,
                "path_meet": meet,
                "meet_label": MEET_LABELS.get(meet or "", "unknown"),
                "path_date": path_date,
                "directory_date": directory_date,
                "filename_date": filename_date,
                "body_date": body_date,
                "body_exam_turn": current_title.get("exam_turn") if current_title else None,
                "body_race_no": current_title.get("race_no") if current_title else None,
                "body_section_no": current_title.get("section_no") if current_title else None,
                "source_line_no": line_no,
                "horse_number_local_raw": local_number,
                "horse_name_candidate": horse_name,
                "exam_basis_text": exam_reason,
                "judgment_raw": judgment,
                "decision_reason_raw": decision_reason,
                "row_parse_status": parse_status,
                "official_horse_id_present": False,
                "raw_line": line,
            }
            file_rows.append(row)
            rows_by_meet[meet or "?"] += 1
            if meet in IN_SCOPE_MEETS and in_body_scope:
                candidate_rows.append(row)
                body_presence[(body_date, meet)] += 1
                if judgment is not None:
                    per_file_judgment[judgment] += 1
                    verdict_reasons[(meet, judgment, decision_reason or "")] += 1
                per_file_decision_reason[decision_reason or ""] += 1
                body_row_counts[(body_date, meet)] += 1

        path_year_match = PATH_RE.search(path.relative_to(INPUT_ROOT).as_posix())
        path_year = int(path_year_match.group(2)) if path_year_match else None
        if meet and path_year is not None:
            year_meet_files[(path_year, meet)] += 1
            year_meet_rows[(path_year, meet)] += len(file_rows)
            year_meet_titles[(path_year, meet)] += len(headings)
            if path_date:
                year_meet_path_dates[(path_year, meet)].append(path_date)
            if filename_date:
                year_meet_filename_dates[(path_year, meet)].append(filename_date)
            year_meet_body_dates[(path_year, meet)].extend(unique_body_dates)
            if not unique_body_dates:
                year_meet_missing_body_date[(path_year, meet)] += 1
            if path_date and unique_body_dates and any(day != path_date for day in unique_body_dates):
                year_meet_body_path_mismatch[(path_year, meet)] += 1
            if filename_date and unique_body_dates and any(day != filename_date for day in unique_body_dates):
                year_meet_body_filename_mismatch[(path_year, meet)] += 1

        file_scope_body_dates = [
            day
            for day in unique_body_dates
            if SCOPE_START.isoformat() <= day <= SCOPE_END.isoformat()
        ]
        flags = path_flags[:]
        if not headings:
            flags.append("no_title_heading_found")
        if len(unique_body_dates) > 1:
            flags.append("multiple_body_exam_dates_in_one_file")
        if path_date and unique_body_dates and any(day != path_date for day in unique_body_dates):
            flags.append("path_date_body_exam_date_mismatch")
        if filename_date and unique_body_dates and any(day != filename_date for day in unique_body_dates):
            flags.append("filename_date_body_exam_date_mismatch")
        if header is None:
            flags.append("table_header_not_found")
        elif not official_id_header_tokens:
            flags.append("official_horse_id_column_not_present")
        if offsets and any(offsets.get(k) is None for k in ("exam_reason", "exam_reason_end", "judgment", "decision_reason")):
            flags.append("incomplete_header_column_offsets")
        if any(row["row_parse_status"] != "header_byte_offsets" for row in file_rows):
            flags.append("some_rows_limited_parse")

        manifest_files.append(
            {
                "path": rel_path,
                "sha256": digest,
                "size_bytes": len(data),
                "encoding": encoding,
                "line_count": len(lines),
                "path_meet": meet,
                "meet_label": MEET_LABELS.get(meet or "", "unknown"),
                "path_year": path_year,
                "path_date": path_date,
                "filename_date": filename_date,
                "body_dates": unique_body_dates,
                "body_title_count": len(headings),
                "body_titles": [
                    {
                        "line_no": item[0],
                        "body_date": item[1]["body_date"],
                        "exam_turn": item[1]["exam_turn"],
                        "race_no": item[1]["race_no"],
                        "raw_title": item[1]["raw_title"],
                    }
                    for item in headings
                ],
                "table_header": header_signature,
                "header_offsets_bytes": offsets,
                "header_official_id_tokens": official_id_header_tokens,
                "local_horse_number_header": "마번" if header and "마번" in header else None,
                "candidate_row_count": len(file_rows),
                "judgment_value_counts": dict(sorted(per_file_judgment.items())),
                "decision_reason_value_counts": dict(sorted(per_file_decision_reason.items())),
                "scope_meet_included": meet in IN_SCOPE_MEETS,
                "scope_body_dates_included": file_scope_body_dates,
                "scope_candidate_row_count": sum(
                    1
                    for row in file_rows
                    if meet in IN_SCOPE_MEETS
                    and row["body_date"]
                    and SCOPE_START.isoformat() <= row["body_date"] <= SCOPE_END.isoformat()
                ),
                "flags": sorted(set(flags)),
            }
        )

    years = range(SCOPE_START.year, SCOPE_END.year + 1)
    file_aggregate_rows: list[dict[str, Any]] = []
    for year in years:
        for meet in ("1", "2", "3", "4"):
            key = (year, meet)
            path_dates = sorted(year_meet_path_dates.get(key, []))
            filename_dates = sorted(year_meet_filename_dates.get(key, []))
            body_dates = sorted(set(year_meet_body_dates.get(key, [])))
            file_aggregate_rows.append(
                {
                    "path_year": year,
                    "path_meet": meet,
                    "meet_label": MEET_LABELS[meet],
                    "scope_meet_included": meet in IN_SCOPE_MEETS,
                    "file_count": year_meet_files[key],
                    "body_title_count": year_meet_titles[key],
                    "candidate_row_count_all_files": year_meet_rows[key],
                    "earliest_path_date": min(path_dates) if path_dates else None,
                    "latest_path_date": max(path_dates) if path_dates else None,
                    "earliest_filename_date": min(filename_dates) if filename_dates else None,
                    "latest_filename_date": max(filename_dates) if filename_dates else None,
                    "earliest_body_exam_date": min(body_dates) if body_dates else None,
                    "latest_body_exam_date": max(body_dates) if body_dates else None,
                    "files_missing_body_date": year_meet_missing_body_date[key],
                    "files_with_path_body_date_mismatch": year_meet_body_path_mismatch[key],
                    "files_with_filename_body_date_mismatch": year_meet_body_filename_mismatch[key],
                    "distinct_header_forms": len(year_meet_header_signatures.get(key, set())),
                }
            )

    judgment_rows = [
        {
            "path_meet": meet,
            "meet_label": MEET_LABELS.get(meet, "unknown"),
            "judgment_raw": judgment,
            "decision_reason_raw": reason or None,
            "row_count": count,
        }
        for (meet, judgment, reason), count in sorted(verdict_reasons.items())
    ]

    body_file_presence: Counter[tuple[str, str]] = Counter()
    for entry in manifest_files:
        meet = entry.get("path_meet")
        if meet not in IN_SCOPE_MEETS:
            continue
        for body_date in set(entry.get("body_dates", [])):
            if SCOPE_START.isoformat() <= body_date <= SCOPE_END.isoformat():
                body_file_presence[(body_date, meet)] += 1
    date_presence_rows: list[dict[str, Any]] = []
    day = SCOPE_START
    while day <= SCOPE_END:
        iso = day.isoformat()
        for meet in ("1", "3"):
            count = body_presence[(iso, meet)]
            file_count = body_file_presence[(iso, meet)]
            date_presence_rows.append(
                {
                    "body_exam_date": iso,
                    "path_meet": meet,
                    "meet_label": MEET_LABELS[meet],
                    "rpt_file_count": file_count,
                    "candidate_row_count": count,
                    "local_rpt_file_found": file_count > 0,
                    "status": (
                        "local_rpt_file_and_rows_found"
                        if file_count and count
                        else "local_rpt_file_found_no_candidate_rows"
                        if file_count
                        else "no_local_rpt_file_in_snapshot"
                    ),
                    "interpretation": "RPT file presence only; absence does not prove no event or no API21 response",
                }
            )
        day += timedelta(days=1)

    manifest = {
        "schema_version": 1,
        "dataset": "KRA DB4 starting-exam official text snapshot",
        "source_root": "data/raw/kra_text/db4",
        "scope_start": SCOPE_START.isoformat(),
        "scope_end": SCOPE_END.isoformat(),
        "scope_meets": {
            "1": "Seoul",
            "3": "Yeongnam; preserve API region label and do not infer Busan vs Yeongcheon",
            "2": "Jeju excluded",
            "4": "no local files found",
        },
        "file_count": len(manifest_files),
        "encoding_counts": dict(sorted(encoding_counts.items())),
        "decode_errors": errors,
        "ignored_nontext_files": ignored_nontext,
        "meet_file_counts": {
            meet: sum(1 for entry in manifest_files if entry["path_meet"] == meet)
            for meet in ("1", "2", "3", "4")
        },
        "scope_body_date_coverage": {
            meet: {
                "earliest_actual_body_date": min(
                    (
                        body_date
                        for entry in manifest_files
                        if entry["path_meet"] == meet
                        for body_date in entry.get("body_dates", [])
                        if SCOPE_START.isoformat() <= body_date <= SCOPE_END.isoformat()
                    ),
                    default=None,
                ),
                "latest_actual_body_date": max(
                    (
                        body_date
                        for entry in manifest_files
                        if entry["path_meet"] == meet
                        for body_date in entry.get("body_dates", [])
                        if SCOPE_START.isoformat() <= body_date <= SCOPE_END.isoformat()
                    ),
                    default=None,
                ),
                "files_with_in_scope_actual_body_date": sum(
                    1
                    for entry in manifest_files
                    if entry["path_meet"] == meet
                    and entry.get("scope_body_dates_included")
                ),
                "candidate_rows_in_scope": sum(
                    entry.get("scope_candidate_row_count", 0)
                    for entry in manifest_files
                    if entry["path_meet"] == meet
                ),
            }
            for meet in ("1", "2", "3", "4")
        },
        "identifier_assessment": {
            "table_horse_number_header": "마번",
            "interpretation": "race-local horse number only; not a KRA official horse identity field",
            "official_horse_id_headers_found": sorted(
                {token for entry in manifest_files for token in entry.get("header_official_id_tokens", [])}
            ),
            "auto_name_or_number_linking": False,
        },
        "row_parser": {
            "method": "CP949/UTF-8 decoded text; locate each file's own table header and slice row columns at its byte offsets; retain each full raw line",
            "candidate_row_rule": "line begins with a 1- or 2-digit horse number and at least two spaces",
            "judgment_and_reason": "read from the table's 판정 and final 사유 byte columns; blank judgment and populated reason remain distinct",
            "known_limit": "unrecognized or missing table headers produce limited row parsing and are flagged; RPT spelling/identity is not authoritative",
        },
        "files": manifest_files,
    }

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUTPUT_ROOT / "source_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    csv_write(
        OUTPUT_ROOT / "file_counts_by_path_year_meet.csv",
        [
            "path_year", "path_meet", "meet_label", "scope_meet_included", "file_count",
            "body_title_count", "candidate_row_count_all_files", "earliest_path_date",
            "latest_path_date", "earliest_filename_date", "latest_filename_date",
            "earliest_body_exam_date", "latest_body_exam_date",
            "files_missing_body_date", "files_with_path_body_date_mismatch", "distinct_header_forms",
            "files_with_filename_body_date_mismatch",
        ],
        file_aggregate_rows,
    )
    csv_write(
        OUTPUT_ROOT / "judgment_reason_counts.csv",
        ["path_meet", "meet_label", "judgment_raw", "decision_reason_raw", "row_count"],
        judgment_rows,
    )
    csv_write(
        OUTPUT_ROOT / "api21_comparison_candidates.csv",
        [
            "source_path", "source_sha256", "path_meet", "meet_label", "path_date",
            "directory_date", "filename_date",
            "body_date", "body_exam_turn", "body_race_no", "body_section_no", "source_line_no",
            "horse_number_local_raw", "horse_name_candidate", "exam_basis_text", "judgment_raw",
            "decision_reason_raw", "row_parse_status", "official_horse_id_present", "raw_line",
        ],
        candidate_rows,
    )
    csv_write(
        OUTPUT_ROOT / "date_meet_presence.csv",
        [
            "body_exam_date", "path_meet", "meet_label", "candidate_row_count",
            "rpt_file_count", "local_rpt_file_found", "status", "interpretation",
        ],
        date_presence_rows,
    )

    print(
        json.dumps(
            {
                "files": len(manifest_files),
                "encodings": dict(encoding_counts),
                "meet_file_counts": manifest["meet_file_counts"],
                "scope_actual_dates": manifest["scope_body_date_coverage"],
                "candidate_rows": len(candidate_rows),
                "judgment_reason_combinations": len(judgment_rows),
                "decode_errors": len(errors),
                "output_dir": str(OUTPUT_ROOT),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
