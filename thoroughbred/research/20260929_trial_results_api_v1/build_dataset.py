"""Normalize archived KRA API20_1 running-trial result rows.

The source files are read-only inputs. Each participant is retained, including
records without a horse identifier. API-native values are kept in prefixed
columns and as a row-level JSON object so CSV serialization cannot erase their
original JSON types or distinguishable missing-field states.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SOURCE_ROOT = ROOT / "thoroughbred/research/20260929_calendar_api_v1/raw/trial_result"
SOURCE_API = "API20_1/ridingTestResult_1"
SOURCE_ENDPOINT = "https://apis.data.go.kr/B551015/API20_1/ridingTestResult_1"
API_FIELDS_PREFIX = "api_"
BASE_FIELDS = [
    "participant_row_id",
    "trial_session_id",
    "trial_date",
    "trial_no",
    "api_meet_label",
    "horse_id",
    "horse_name",
    "horse_id_missing",
    "source_api_service",
    "source_endpoint",
    "source_year_query",
    "source_meet_query",
    "source_result_code",
    "source_result_msg",
    "source_file",
    "source_file_sha256",
    "source_item_index",
    "source_record_json",
]
PARTICIPANTS_PATH = HERE / "participants.csv"
SESSIONS_PATH = HERE / "sessions.csv"
UNIDENTIFIED_PATH = HERE / "unidentified_participants.csv"
MANIFEST_PATH = HERE / "source_manifest.json"


def json_items(payload: dict[str, Any], path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    response = payload.get("response") or {}
    header = response.get("header") or {}
    code = str(header.get("resultCode", ""))
    if code not in {"00", "0000"}:
        raise ValueError(f"{path}: unsuccessful API resultCode {code!r}")
    body = response.get("body") or {}
    items_block = body.get("items") or {}
    raw_items = items_block.get("item", []) if isinstance(items_block, dict) else []
    if raw_items is None:
        raw_items = []
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    if not isinstance(raw_items, list) or any(not isinstance(row, dict) for row in raw_items):
        raise ValueError(f"{path}: unexpected API item structure")
    total_count = body.get("totalCount")
    if total_count is not None and int(total_count) != len(raw_items):
        raise ValueError(f"{path}: totalCount does not match returned rows")
    return header, raw_items


def date_parts(raw_date: Any, path: Path) -> tuple[str, str]:
    raw = "" if raw_date is None else str(raw_date)
    if len(raw) != 8 or not raw.isdigit():
        raise ValueError(f"{path}: invalid trainDate {raw_date!r}")
    parsed = datetime.strptime(raw, "%Y%m%d")
    return parsed.date().isoformat(), raw


def is_missing_identifier(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() in {"", "-"})


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def build() -> dict[str, Any]:
    if not SOURCE_ROOT.is_dir():
        raise FileNotFoundError(f"Source directory not found: {SOURCE_ROOT}")
    files = sorted(SOURCE_ROOT.glob("*/meet_*.json"))
    if not files:
        raise FileNotFoundError(f"No archived trial result JSON files under {SOURCE_ROOT}")

    participant_rows: list[dict[str, Any]] = []
    session_groups: dict[tuple[int, str, str], dict[str, Any]] = {}
    api_field_names: set[str] = set()
    source_manifest: list[dict[str, Any]] = []
    all_meet_date_keys: set[tuple[int, str]] = set()
    year_counts: dict[int, int] = defaultdict(int)

    for path in files:
        relative_source = path.relative_to(ROOT).as_posix()
        try:
            year = int(path.parent.name)
            request_meet = int(path.stem.removeprefix("meet_"))
        except ValueError as exc:
            raise ValueError(f"Unexpected source path: {path}") from exc
        raw_bytes = path.read_bytes()
        payload = json.loads(raw_bytes)
        header, items = json_items(payload, path)
        digest = hashlib.sha256(raw_bytes).hexdigest()
        source_manifest.append({
            "source_file": relative_source,
            "source_file_sha256": digest,
            "source_year_query": year,
            "source_meet_query": request_meet,
            "source_result_code": str(header.get("resultCode", "")),
            "source_result_msg": str(header.get("resultMsg", "")),
            "source_item_count": len(items),
        })
        year_counts[year] += len(items)

        for item_index, item in enumerate(items):
            api_field_names.update(item)
            trial_date, raw_date = date_parts(item.get("trainDate"), path)
            trial_no_value = item.get("trainNo")
            trial_no = "" if trial_no_value is None else str(trial_no_value)
            if not trial_no:
                raise ValueError(f"{path}: participant row {item_index} has no trainNo")
            if trial_date[:4] != str(year):
                raise ValueError(f"{path}: trainDate {raw_date} falls outside query year {year}")
            session_id = f"meet={request_meet}|date={raw_date}|trial={trial_no}"
            meet_label = item.get("meet")
            group_key = (request_meet, raw_date, trial_no)
            session = session_groups.setdefault(group_key, {
                "trial_session_id": session_id,
                "trial_date": trial_date,
                "trial_date_raw": raw_date,
                "trial_no": trial_no_value,
                "source_meet_query": request_meet,
                "api_meet_label": meet_label,
                "day_serial": item.get("daySerial"),
                "participant_rows": 0,
                "missing_horse_id_rows": 0,
                "source_file": relative_source,
                "source_file_sha256": digest,
            })
            if session["api_meet_label"] != meet_label:
                raise ValueError(f"Conflicting API meet labels within session {session_id}")
            session["participant_rows"] += 1
            missing_id = is_missing_identifier(item.get("hrNo"))
            session["missing_horse_id_rows"] += int(missing_id)
            all_meet_date_keys.add((request_meet, raw_date))

            row = {
                "participant_row_id": f"{relative_source}#item={item_index}",
                "trial_session_id": session_id,
                "trial_date": trial_date,
                "trial_no": trial_no_value,
                "api_meet_label": meet_label,
                "horse_id": item.get("hrNo"),
                "horse_name": item.get("hrName"),
                "horse_id_missing": str(missing_id).lower(),
                "source_api_service": SOURCE_API,
                "source_endpoint": SOURCE_ENDPOINT,
                "source_year_query": year,
                "source_meet_query": request_meet,
                "source_result_code": str(header.get("resultCode", "")),
                "source_result_msg": str(header.get("resultMsg", "")),
                "source_file": relative_source,
                "source_file_sha256": digest,
                "source_item_index": item_index,
                "source_record_json": json.dumps(
                    item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            }
            row.update({f"{API_FIELDS_PREFIX}{field}": value for field, value in item.items()})
            participant_rows.append(row)

    api_fields = [f"{API_FIELDS_PREFIX}{name}" for name in sorted(api_field_names)]
    participant_fields = BASE_FIELDS + api_fields
    participant_rows.sort(key=lambda row: (
        row["source_year_query"], row["source_meet_query"], row["trial_date"],
        row["trial_no"], row["source_file"], row["source_item_index"],
    ))
    sessions = sorted(session_groups.values(), key=lambda row: (
        row["source_meet_query"], row["trial_date"], int(row["trial_no"]),
    ))
    session_fields = [
        "trial_session_id", "trial_date", "trial_date_raw", "trial_no",
        "source_meet_query", "api_meet_label", "day_serial", "participant_rows",
        "missing_horse_id_rows", "source_file", "source_file_sha256",
    ]
    unidentified = [row for row in participant_rows if row["horse_id_missing"] == "true"]
    write_csv(PARTICIPANTS_PATH, participant_fields, participant_rows)
    write_csv(SESSIONS_PATH, session_fields, sessions)
    write_csv(UNIDENTIFIED_PATH, participant_fields, unidentified)

    manifest = {
        "dataset": "KRA running-trial participant results",
        "source_api_service": SOURCE_API,
        "source_endpoint": SOURCE_ENDPOINT,
        "source_root": SOURCE_ROOT.relative_to(ROOT).as_posix(),
        "date_basis": "API trainDate; exposed as ISO trial_date and retained as api_trainDate",
        "session_key": "source meet query + API trainDate + API trainNo",
        "source_file_count": len(source_manifest),
        "participant_row_count": len(participant_rows),
        "session_count": len(sessions),
        "source_meet_date_count": len(all_meet_date_keys),
        "unidentified_horse_id_row_count": len(unidentified),
        "participant_rows_by_year": {str(year): count for year, count in sorted(year_counts.items())},
        "api_participant_fields": sorted(api_field_names),
        "source_files": source_manifest,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    manifest = build()
    print(json.dumps({
        "source_file_count": manifest["source_file_count"],
        "participant_row_count": manifest["participant_row_count"],
        "session_count": manifest["session_count"],
        "source_meet_date_count": manifest["source_meet_date_count"],
        "unidentified_horse_id_row_count": manifest["unidentified_horse_id_row_count"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
