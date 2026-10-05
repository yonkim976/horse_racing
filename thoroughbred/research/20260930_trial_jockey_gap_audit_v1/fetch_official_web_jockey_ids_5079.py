"""Verify RPT-only trial jockey names and IDs against official KRA score pages.

Run from the repository root. Captures are cached and compressed, so an
interrupted run resumes without refetching successful sessions. No API source
field is edited. A zero-time row records an assigned jockey, not an actual ride.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb

from fetch_official_web_name_conflicts_18 import (
    URL,
    get_score_page,
    parse_score_rows,
)


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CORE_DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
SOURCE = HERE / "trial_jockey_missing_audit.jsonl"
RAW = HERE / "raw_official_web_jockey_id_5079"
OUTPUT = HERE / "official_web_jockey_ids_5079.jsonl"
MANIFEST = HERE / "official_web_jockey_ids_5079_manifest.json"
ERRORS = HERE / "official_web_jockey_ids_5079_errors.jsonl"
MAX_WORKERS = 3
MIN_REQUEST_START_INTERVAL_SECONDS = 0.25
REVIEWED_NAME_VARIANTS = {
    ("이쿠", "이쿠야스", "080426"): "rpt_short_name_official_full_name",
    ("정형래", "정우주", "080588"):
        "rpt_historical_name_official_current_name_crosswalk_unconfirmed",
}
_rate_lock = threading.Lock()
_next_request_start = 0.0


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def capture_path(key: tuple[int, str, int]) -> Path:
    meet, date, trial_no = key
    return RAW / f"meet_{meet}" / f"date_{date}_trial_{trial_no}.html.gz"


def load_targets() -> tuple[list[dict], dict[str, tuple[str, str]]]:
    targets = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    targets = [row for row in targets if row["rpt_jockey_name"]]
    if len(targets) != 5079 or len({row["participant_row_id"] for row in targets}) != 5079:
        raise ValueError("RPT 기수명 검증 대상이 5,079개 고유 행이어야 합니다")
    keys = [(int(r["source_meet_query"]), r["api_trainDate"], int(r["api_trainNo"]),
             int(r["api_chulNo"])) for r in targets]
    if len(set(keys)) != len(keys):
        raise ValueError("시행장·날짜·심사차수·마번이 중복됩니다")

    connection = duckdb.connect(str(CORE_DB), read_only=True)
    try:
        horse_rows = connection.execute(
            "SELECT participant_row_id,resolved_horse_id,resolved_horse_name "
            "FROM trial_participants_resolved WHERE participant_row_id IN "
            "(SELECT participant_row_id FROM trial_jockey_gap_audit "
            "WHERE rpt_jockey_name IS NOT NULL)"
        ).fetchall()
    finally:
        connection.close()
    horses = {row_id: (horse_id, horse_name) for row_id, horse_id, horse_name in horse_rows}
    if len(horses) != 5079 or any(not horses[r["participant_row_id"]][0] for r in targets):
        raise ValueError("검증 대상의 말 ID 연결이 완전하지 않습니다")
    return targets, horses


def rate_limit() -> None:
    global _next_request_start
    with _rate_lock:
        now = time.monotonic()
        if now < _next_request_start:
            time.sleep(_next_request_start - now)
            now = time.monotonic()
        _next_request_start = now + MIN_REQUEST_START_INTERVAL_SECONDS


def get_capture(key: tuple[int, str, int]) -> tuple[tuple[int, str, int], bytes, Path]:
    path = capture_path(key)
    if path.exists():
        return key, gzip.decompress(path.read_bytes()), path
    meet, date, trial_no = key
    for attempt in range(3):
        try:
            rate_limit()
            payload = get_score_page(meet, date, trial_no)
            parse_score_rows(payload, date, trial_no)
            path.parent.mkdir(parents=True, exist_ok=True)
            compressed = gzip.compress(payload, compresslevel=6, mtime=0)
            temp = path.with_suffix(".tmp")
            temp.write_bytes(compressed)
            temp.replace(path)
            return key, payload, path
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + 2 * attempt)
    raise AssertionError("unreachable")


def main() -> None:
    targets, horses = load_targets()
    groups: dict[tuple[int, str, int], list[dict]] = defaultdict(list)
    for row in targets:
        key = int(row["source_meet_query"]), row["api_trainDate"], int(row["api_trainNo"])
        groups[key].append(row)
    print(f"targets={len(targets)} sessions={len(groups)} cached="
          f"{sum(capture_path(key).exists() for key in groups)}", flush=True)

    captures = {}
    errors = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(get_capture, key): key for key in sorted(groups)}
        for done, future in enumerate(as_completed(futures), 1):
            key = futures[future]
            try:
                _, payload, path = future.result()
                score_rows = parse_score_rows(payload, key[1], key[2])
                captures[key] = (payload, path, score_rows)
            except Exception as exc:
                errors.append({"meet": key[0], "date": key[1], "trial_no": key[2],
                               "error_type": type(exc).__name__, "error": str(exc)[:300]})
            if done % 100 == 0 or done == len(futures):
                print(f"sessions={done}/{len(futures)} errors={len(errors)}", flush=True)

    observations = []
    review_issues = []
    for key in sorted(captures):
        payload, path, score_rows = captures[key]
        for target in groups[key]:
            horse_id, horse_name = horses[target["participant_row_id"]]
            program_no = int(target["api_chulNo"])
            matches = [r for r in score_rows if r["horse_program_no"] == program_no
                       and r["horse_id"] == horse_id]
            if len(matches) != 1:
                review_issues.append({"participant_row_id": target["participant_row_id"],
                                      "issue": "official_horse_id_or_program_not_unique",
                                      "matches": len(matches), "source_file": rel(path)})
                continue
            official = matches[0]
            try:
                api_time = float(target["api_rcTime"] or 0)
            except (TypeError, ValueError):
                review_issues.append({"participant_row_id": target["participant_row_id"],
                                      "issue": "api_time_unparseable", "source_file": rel(path)})
                continue
            official_time = official["finish_time_seconds"]
            if (official_time is None and api_time > 0) or (
                    official_time is not None and round(official_time, 1) != round(api_time, 1)):
                review_issues.append({"participant_row_id": target["participant_row_id"],
                                      "issue": "api_official_time_mismatch",
                                      "api_time": api_time, "official_time": official_time,
                                      "source_file": rel(path)})
                continue
            if not official["jockey_id"] or not official["jockey_name"]:
                review_issues.append({"participant_row_id": target["participant_row_id"],
                                      "issue": "official_jockey_id_or_name_missing",
                                      "source_file": rel(path)})
                continue
            name_pair = (target["rpt_jockey_name"], official["jockey_name"],
                         official["jockey_id"])
            name_review_status = ("exact" if name_pair[0] == name_pair[1]
                                  else REVIEWED_NAME_VARIANTS.get(name_pair))
            if name_review_status is None:
                review_issues.append({"participant_row_id": target["participant_row_id"],
                                      "issue": "unreviewed_rpt_official_jockey_name_difference",
                                      "rpt_name": name_pair[0], "official_name": name_pair[1],
                                      "official_id": name_pair[2], "source_file": rel(path)})
                continue
            observations.append({
                "participant_row_id": target["participant_row_id"],
                "meet": key[0], "date": key[1], "trial_no": key[2],
                "horse_program_no": program_no,
                "horse_id_reviewed": horse_id,
                "horse_name_reviewed": horse_name,
                "official_horse_id": official["horse_id"],
                "official_horse_name": official["horse_name"],
                "rpt_jockey_name": target["rpt_jockey_name"],
                "official_jockey_id": official["jockey_id"],
                "official_jockey_name": official["jockey_name"],
                "jockey_name_exact_match": target["rpt_jockey_name"] == official["jockey_name"],
                "jockey_name_review_status": name_review_status,
                "api_time_seconds": api_time,
                "official_finish_time": official["finish_time"],
                "official_time_seconds": official_time,
                "jockey_semantics": ("official_completed_trial_rider" if api_time > 0
                                     else "assigned_jockey_only_actual_ride_not_confirmed"),
                "official_result_status": official["result_status"],
                "official_row_text": official["row_text"],
                "official_web_source_file": rel(path),
                "official_web_source_sha256": sha(payload),
                "official_web_source_url": URL,
                "official_web_request_form": {
                    "meet": key[0], "date": key[1], "trno": key[2],
                    "Act": "06", "Sub": "7",
                },
            })

    issues = errors + review_issues
    ERROR_BYTES = ("\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":"))
                             for r in issues) + ("\n" if issues else "")).encode("utf-8")
    ERRORS.write_bytes(ERROR_BYTES)
    observations.sort(key=lambda r: r["participant_row_id"])
    output_bytes = ("\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":"))
                              for r in observations) + ("\n" if observations else "")).encode("utf-8")
    OUTPUT.write_bytes(output_bytes)
    capture_records = [{"meet": key[0], "date": key[1], "trial_no": key[2],
                        "source_file": rel(path), "sha256": sha(payload),
                        "compressed_sha256": sha(path.read_bytes()),
                        "score_rows": len(score_rows)}
                       for key, (payload, path, score_rows) in sorted(captures.items())]
    manifest = {
        "source": rel(SOURCE), "source_sha256": sha(SOURCE.read_bytes()),
        "official_score_url": URL, "expected_targets": 5079,
        "expected_sessions": len(groups), "captures": capture_records,
        "observations": len(observations),
        "completed_trial_riders": sum(r["jockey_semantics"] == "official_completed_trial_rider"
                                      for r in observations),
        "assigned_only": sum(r["jockey_semantics"] != "official_completed_trial_rider"
                             for r in observations),
        "name_differences": sum(not r["jockey_name_exact_match"] for r in observations),
        "errors": len(issues), "error_output": rel(ERRORS), "error_sha256": sha(ERROR_BYTES),
        "output": rel(OUTPUT), "output_sha256": sha(output_bytes),
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"observations={len(observations)} issues={len(issues)}", flush=True)
    if issues:
        sys.exit(2)


if __name__ == "__main__":
    main()
