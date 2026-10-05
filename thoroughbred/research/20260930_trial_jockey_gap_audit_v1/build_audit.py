"""Build a read-only, source-linked audit for missing trial jockey fields."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
RPT_ROOT = ROOT / "data/raw/kra_text/dacom23"
OUTPUT = HERE / "trial_jockey_missing_audit.jsonl"
MANIFEST = HERE / "manifest.json"
EXPECTED_ROWS = 5121

TITLE_RE = re.compile(
    r"(?P<year>\d{2,4})년\s*(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일"
    r".*?제\s*(?P<round>\d+)차\s*주행(?:심사|검사)성적\s*제\s*0*(?P<race>\d+)경주"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise ValueError(f"Source path is outside the repository: {path}") from exc


def decode_rpt(payload: bytes) -> str:
    for encoding in ("cp949", "euc-kr", "utf-8"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("cp949", errors="replace")


def is_rule(line: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= 20 and set(stripped) == {"-"}


def parse_rpt(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract runner number, horse/jockey names, and exact source line from dacom23."""
    relative = repo_relative(path)
    match = re.search(r"(?:^|/)meet=(1|3)(?:/|$)", relative)
    if match is None:
        raise ValueError(f"Unexpected dacom23 meet path: {relative}")
    meet = int(match.group(1))
    file_hash = sha256(path)
    lines = decode_rpt(path.read_bytes()).replace("\r\n", "\n").splitlines()
    title_indexes = [index for index, line in enumerate(lines) if TITLE_RE.search(line)]
    runner_rows: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []

    for title_position, title_index in enumerate(title_indexes):
        title = TITLE_RE.search(lines[title_index])
        assert title is not None
        year = int(title.group("year"))
        if year < 100:
            year += 2000
        date = f"{year:04d}{int(title.group('month')):02d}{int(title.group('day')):02d}"
        trial_no = int(title.group("race"))
        block_end = title_indexes[title_position + 1] if title_position + 1 < len(title_indexes) else len(lines)
        sessions.append({"meet": meet, "date": date, "trial_no": trial_no})

        header_index = next(
            (
                index
                for index in range(title_index + 1, block_end)
                if "마" in lines[index]
                and "명" in lines[index]
                and ("기수명" in lines[index] or "선수명" in lines[index])
            ),
            None,
        )
        if header_index is None:
            continue
        data_start = next(
            (index + 1 for index in range(header_index + 1, block_end) if is_rule(lines[index])),
            None,
        )
        if data_start is None:
            continue
        data_end = next(
            (index for index in range(data_start, block_end) if is_rule(lines[index])),
            block_end,
        )

        for line_index in range(data_start, data_end):
            tokens = lines[line_index].split()
            if len(tokens) < 3:
                continue
            leading_numbers = 0
            while leading_numbers < len(tokens) and tokens[leading_numbers].isdigit():
                leading_numbers += 1
            if leading_numbers == 0:
                continue
            # Most reports contain rank then horse number. Some 2019 rows have
            # no rank value, leaving the horse number as the only leading integer.
            horse_number = int(tokens[1] if leading_numbers >= 2 else tokens[0])
            horse_name = tokens[leading_numbers].strip() if leading_numbers < len(tokens) else None
            if not horse_name or horse_name in {"-", "--"}:
                horse_name = None
            jockey_name = tokens[-2].strip()
            if not jockey_name or jockey_name in {"-", "--"}:
                jockey_name = None
            runner_rows.append(
                {
                    "meet": meet,
                    "date": date,
                    "trial_no": trial_no,
                    "horse_number": horse_number,
                    "horse_name": horse_name,
                    "jockey_name": jockey_name,
                    "source_file": relative,
                    "source_file_sha256": file_hash,
                    "source_line_number": line_index + 1,
                    "source_line_text": lines[line_index],
                }
            )
    return runner_rows, sessions


def source_items(path: Path, cache: dict[Path, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    resolved = path.resolve()
    if resolved not in cache:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        body = payload.get("response", {}).get("body", {})
        items_block = body.get("items") or {}
        items = items_block.get("item", []) if isinstance(items_block, dict) else []
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError(f"Unexpected API item structure: {repo_relative(resolved)}")
        cache[resolved] = items
    return cache[resolved]


def json_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def build() -> dict[str, Any]:
    rpt_index: dict[tuple[int, str, int, int], list[dict[str, Any]]] = defaultdict(list)
    rpt_sessions: set[tuple[int, str, int]] = set()
    rpt_days: set[tuple[int, str]] = set()
    rpt_file_hashes: dict[str, str] = {}
    rpt_parse_errors: list[dict[str, str]] = []

    for meet in (1, 3):
        for path in sorted((RPT_ROOT / f"meet={meet}").glob("year=20*/month=*/day=*/*.rpt")):
            source_year = next(
                (int(part.removeprefix("year=")) for part in path.parts if part.startswith("year=")),
                0,
            )
            if source_year < 2010:
                continue
            try:
                rows, sessions = parse_rpt(path)
            except Exception as exc:
                rpt_parse_errors.append({
                    "source_file": repo_relative(path),
                    "error_type": type(exc).__name__,
                })
                continue
            file_hash = sha256(path)
            rpt_file_hashes[repo_relative(path)] = file_hash
            for session in sessions:
                key = (session["meet"], session["date"], session["trial_no"])
                rpt_sessions.add(key)
                rpt_days.add((session["meet"], session["date"]))
            for row in rows:
                key = (row["meet"], row["date"], row["trial_no"], row["horse_number"])
                rpt_index[key].append(row)

    db = duckdb.connect(str(DB), read_only=True)
    try:
        rows = db.execute(
            """
            SELECT p.participant_row_id, p.trial_date, p.source_meet_query,
                   p.api_trainDate, p.api_trainNo, p.api_chulNo,
                   p.api_hrNo, p.api_hrName, p.api_passFlag, p.api_nopassReason,
                   p.api_reason, p.api_rcTime, p.api_wgJkAdd,
                   p.source_file, p.source_file_sha256, p.source_item_index,
                   p.source_record_json, p.api_jkNo, p.api_jkName,
                   r.resolved_horse_id, r.resolved_horse_name, r.horse_identity_resolution,
                   l.official_horse_id, l.rpt_horse_name, l.resolution_method,
                   l.decision_basis, l.user_confirmation_note,
                   l.rpt_source_file, l.rpt_source_file_sha256
            FROM trial_participants p
            LEFT JOIN trial_participants_resolved r USING (participant_row_id)
            LEFT JOIN trial_horse_identity_links l USING (participant_row_id)
            WHERE nullif(trim(coalesce(p.api_jkNo, '')), '') IS NULL
              AND nullif(trim(coalesce(p.api_jkName, '')), '') IS NULL
            ORDER BY p.trial_date, p.source_meet_query, p.api_trainNo, p.api_chulNo, p.participant_row_id
            """
        ).fetchall()
        session_coverage = db.execute(
            """
            WITH session_rows AS (
                SELECT source_meet_query, api_trainDate, api_trainNo,
                       count(*) AS total_rows,
                       count(*) FILTER (
                           WHERE nullif(trim(coalesce(api_jkNo, '')), '') IS NULL
                             AND nullif(trim(coalesce(api_jkName, '')), '') IS NULL
                       ) AS missing_jockey_rows
                FROM trial_participants
                GROUP BY source_meet_query, api_trainDate, api_trainNo
            )
            SELECT count(*) AS sessions,
                   count(*) FILTER (WHERE missing_jockey_rows = total_rows) AS fully_missing,
                   count(*) FILTER (WHERE missing_jockey_rows > 0 AND missing_jockey_rows < total_rows) AS partially_missing,
                   count(*) FILTER (WHERE missing_jockey_rows = 0) AS no_missing
            FROM session_rows
            """
        ).fetchone()
    finally:
        db.close()

    if len(rows) != EXPECTED_ROWS:
        raise AssertionError(f"Expected {EXPECTED_ROWS} missing jockey rows, found {len(rows)}")

    api_cache: dict[Path, list[dict[str, Any]]] = {}
    api_file_hashes: dict[str, str] = {}
    api_files_checked: set[str] = set()
    year_counts: Counter[str] = Counter()
    meet_counts: Counter[str] = Counter()
    flag_counts: Counter[str] = Counter()
    time_counts: Counter[str] = Counter()
    flag_time_counts: Counter[tuple[str, str]] = Counter()
    trial_no_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    jockey_extra_weight_counts: Counter[str] = Counter()
    report_status_counts: Counter[str] = Counter()
    horse_name_status_counts: Counter[str] = Counter()
    jockey_supplement_status_counts: Counter[str] = Counter()
    resolved_link_method_counts: Counter[str] = Counter()
    no_report_dates: Counter[tuple[str, str]] = Counter()
    output_rows: list[dict[str, Any]] = []

    for record in rows:
        (
            participant_row_id, trial_date, source_meet_query,
            api_train_date, api_train_no, api_chul_no,
            api_horse_id, api_horse_name, api_pass_flag, api_nopass_reason,
            api_reason, api_rc_time, api_wg_jk_add,
            source_file, source_file_hash, source_item_index,
            source_record_json, api_jk_no, api_jk_name,
            resolved_horse_id, resolved_horse_name, horse_identity_resolution,
            linked_official_horse_id, linked_rpt_horse_name, link_resolution_method,
            link_decision_basis, link_user_confirmation_note,
            link_rpt_source_file, link_rpt_source_file_hash,
        ) = record
        if api_jk_no is not None or api_jk_name is not None:
            raise AssertionError(f"Expected SQL NULL jockey fields: {participant_row_id}")

        source_path = (ROOT / str(source_file)).resolve()
        repo_relative(source_path)
        actual_source_hash = sha256(source_path)
        if actual_source_hash != source_file_hash:
            raise AssertionError(f"API raw response hash mismatch: {source_file}")
        api_file_hashes[str(source_file)] = actual_source_hash
        api_files_checked.add(str(source_file))
        source_index = int(source_item_index)
        raw_item = source_items(source_path, api_cache)[source_index]
        db_item = json.loads(source_record_json)
        if raw_item != db_item:
            raise AssertionError(f"API source item differs from preserved DB JSON: {participant_row_id}")
        key_presence = {"jkNo": "jkNo" in raw_item, "jkName": "jkName" in raw_item}
        if key_presence != {"jkNo": False, "jkName": False}:
            raise AssertionError(f"Expected both jockey keys absent in raw API item: {participant_row_id}")

        meet = int(source_meet_query)
        date = str(api_train_date)
        trial_no = int(api_train_no)
        horse_number = int(float(api_chul_no))
        event_key = (meet, date, trial_no)
        runner_key = (*event_key, horse_number)
        rpt_matches = rpt_index.get(runner_key, [])
        names = sorted({match["jockey_name"] for match in rpt_matches if match["jockey_name"]})
        horse_names = sorted({match["horse_name"] for match in rpt_matches if match["horse_name"]})
        if len(names) > 1:
            raise AssertionError(f"Conflicting RPT jockey names for source key {runner_key}: {names}")
        if len(horse_names) > 1:
            raise AssertionError(f"Conflicting RPT horse names for source key {runner_key}: {horse_names}")
        rpt_horse_name = horse_names[0] if len(horse_names) == 1 else None
        api_horse_name_text = str(api_horse_name).strip() if api_horse_name is not None else ""
        resolved_horse_name_text = str(resolved_horse_name).strip() if resolved_horse_name is not None else ""
        link_rpt_horse_name_text = (
            str(linked_rpt_horse_name).strip() if linked_rpt_horse_name is not None else ""
        )
        if len(names) == 1:
            name_status = "rpt_candidate_match_by_meet_date_trial_and_horse_number"
            rpt_name_candidate = names[0]
            rpt_status = "matched_by_meet_date_trial_and_horse_number"
            if not rpt_horse_name:
                horse_name_status = "rpt_horse_name_unavailable"
                supplement_status = "not_verified_rpt_horse_name_unavailable"
                verified_rpt_name = None
            elif api_horse_name_text:
                if api_horse_name_text == rpt_horse_name:
                    horse_name_status = "api_horse_name_exact_rpt_match"
                    supplement_status = "verified_api_horse_name_exact_rpt_match"
                    verified_rpt_name = rpt_name_candidate
                else:
                    horse_name_status = "api_horse_name_rpt_mismatch_unresolved"
                    supplement_status = "excluded_unresolved_horse_name_mismatch"
                    verified_rpt_name = None
            elif (
                resolved_horse_name_text
                and resolved_horse_name_text == rpt_horse_name
                and link_rpt_horse_name_text == rpt_horse_name
                and linked_official_horse_id
                and str(linked_official_horse_id) == str(resolved_horse_id)
                and link_resolution_method in {"crosschecked_operational_rpt", "user_confirmed_rpt_profile"}
            ):
                horse_name_status = "api_horse_name_missing_resolved_link_exact_rpt_match"
                supplement_status = "verified_resolved_horse_link_exact_rpt_match"
                verified_rpt_name = rpt_name_candidate
                resolved_link_method_counts[str(link_resolution_method)] += 1
            else:
                horse_name_status = "api_horse_name_missing_resolved_link_unverified"
                supplement_status = "excluded_unverified_horse_identity"
                verified_rpt_name = None
        elif (meet, date) not in rpt_days:
            name_status = "local_rpt_day_not_archived"
            rpt_name_candidate = None
            rpt_horse_name = None
            horse_name_status = "no_local_rpt_day"
            supplement_status = "unavailable_no_local_rpt_day"
            verified_rpt_name = None
            rpt_status = "no_local_rpt_for_api_meet_date"
            no_report_dates[(str(meet), date)] += 1
        elif event_key not in rpt_sessions:
            name_status = "local_rpt_session_not_found"
            rpt_name_candidate = None
            rpt_horse_name = None
            horse_name_status = "no_local_rpt_session"
            supplement_status = "unavailable_no_local_rpt_session"
            verified_rpt_name = None
            rpt_status = "local_rpt_day_present_but_session_not_found"
        else:
            name_status = "local_rpt_runner_not_matched"
            rpt_name_candidate = None
            rpt_horse_name = None
            horse_name_status = "no_local_rpt_runner"
            supplement_status = "unavailable_no_local_rpt_runner"
            verified_rpt_name = None
            rpt_status = "local_rpt_session_present_but_horse_number_not_found"

        rc_time_numeric = None
        try:
            rc_time_numeric = float(api_rc_time) if api_rc_time is not None else None
        except (TypeError, ValueError):
            pass
        time_bucket = "positive" if rc_time_numeric is not None and rc_time_numeric > 0 else (
            "zero" if rc_time_numeric == 0 else "missing_or_non_numeric"
        )
        year = str(trial_date)[:4]
        flag = str(api_pass_flag) if api_pass_flag is not None else "[null]"
        year_counts[year] += 1
        meet_counts[str(meet)] += 1
        flag_counts[flag] += 1
        time_counts[time_bucket] += 1
        flag_time_counts[(flag, time_bucket)] += 1
        trial_no_counts[str(trial_no)] += 1
        reason_counts[str(api_reason) if api_reason is not None else "[null]"] += 1
        jockey_extra_weight_counts[
            str(api_wg_jk_add) if api_wg_jk_add is not None else "[null]"
        ] += 1
        report_status_counts[name_status] += 1
        horse_name_status_counts[horse_name_status] += 1
        jockey_supplement_status_counts[supplement_status] += 1

        output_rows.append(
            {
                "participant_row_id": participant_row_id,
                "trial_date": trial_date,
                "source_meet_query": meet,
                "api_trainDate": json_value(api_train_date),
                "api_trainNo": json_value(api_train_no),
                "api_chulNo": json_value(api_chul_no),
                "api_hrNo": json_value(api_horse_id),
                "api_hrName": json_value(api_horse_name),
                "api_passFlag": json_value(api_pass_flag),
                "api_nopassReason": json_value(api_nopass_reason),
                "api_reason": json_value(api_reason),
                "api_rcTime": json_value(api_rc_time),
                "api_wgJkAdd": json_value(api_wg_jk_add),
                "api_jkNo": None,
                "api_jkName": None,
                "api_raw_jockey_keys_present": key_presence,
                "api_raw_item_json": source_record_json,
                "api_source": {
                    "file": str(source_file),
                    "item_index_zero_based": source_index,
                    "sha256": actual_source_hash,
                },
                "rpt_horse_name_candidate": rpt_horse_name,
                "rpt_jockey_name_candidate": rpt_name_candidate,
                "rpt_jockey_name": verified_rpt_name,
                "rpt_match_status": rpt_status,
                "rpt_resolution_status": name_status,
                "rpt_horse_name_validation_status": horse_name_status,
                "rpt_jockey_supplement_status": supplement_status,
                "resolved_horse_link_evidence": (
                    {
                        "source_view": "trial_participants_resolved",
                        "source_link_table": "trial_horse_identity_links",
                        "resolved_horse_id": resolved_horse_id,
                        "resolved_horse_name": resolved_horse_name,
                        "horse_identity_resolution": horse_identity_resolution,
                        "official_horse_id": linked_official_horse_id,
                        "rpt_horse_name": linked_rpt_horse_name,
                        "resolution_method": link_resolution_method,
                        "decision_basis": link_decision_basis,
                        "user_confirmation_note": link_user_confirmation_note,
                        "rpt_source_file": link_rpt_source_file,
                        "rpt_source_file_sha256": link_rpt_source_file_hash,
                    }
                    if not api_horse_name_text and rpt_name_candidate
                    else None
                ),
                "jockey_id_resolution_status": "unresolved_no_official_jockey_id_in_rpt_do_not_infer_by_name",
                "rpt_matches": rpt_matches,
            }
        )

    if len(output_rows) != EXPECTED_ROWS:
        raise AssertionError("Output row count differs from audited missing source rows")
    if sum(1 for row in output_rows if row["rpt_jockey_name_candidate"]) != 5097:
        raise AssertionError("Expected 5,097 RPT jockey-name candidates")
    if sum(1 for row in output_rows if row["rpt_jockey_name"]) != 5079:
        raise AssertionError("Expected 5,079 horse-name-verified RPT jockey names")
    if report_status_counts != Counter({
        "rpt_candidate_match_by_meet_date_trial_and_horse_number": 5097,
        "local_rpt_day_not_archived": 24,
    }):
        raise AssertionError(f"Unexpected RPT resolution distribution: {report_status_counts}")
    if horse_name_status_counts != Counter({
        "api_horse_name_exact_rpt_match": 5061,
        "api_horse_name_rpt_mismatch_unresolved": 18,
        "api_horse_name_missing_resolved_link_exact_rpt_match": 18,
        "no_local_rpt_day": 24,
    }):
        raise AssertionError(f"Unexpected horse name validation distribution: {horse_name_status_counts}")
    if resolved_link_method_counts != Counter({
        "crosschecked_operational_rpt": 17,
        "user_confirmed_rpt_profile": 1,
    }):
        raise AssertionError(f"Unexpected resolved horse link methods: {resolved_link_method_counts}")
    if len({row["participant_row_id"] for row in output_rows}) != EXPECTED_ROWS:
        raise AssertionError("Duplicate API participant row keys in audit output")
    if sum(1 for row in output_rows if row["api_hrNo"] in (None, "")) != 18:
        raise AssertionError("Expected 18 rows whose horse ID is also missing in the API")
    for row in output_rows:
        for match in row["rpt_matches"]:
            line_text = match["source_line_text"]
            if match["jockey_name"] and match["jockey_name"] not in line_text:
                raise AssertionError("RPT jockey name is not present at preserved source line")
            if match["horse_name"] and match["horse_name"] not in line_text:
                raise AssertionError("RPT horse name is not present at preserved source line")

    with OUTPUT.open("w", encoding="utf-8", newline="\n") as stream:
        for row in output_rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    manifest: dict[str, Any] = {
        "artifact": "Thoroughbred API20_1 missing trial jockey audit",
        "scope": "trial_participants rows with both API jockey fields missing",
        "database": {"path": repo_relative(DB), "access": "read_only"},
        "source_api": {
            "service": "API20_1/ridingTestResult_1",
            "source_file_count_checked": len(api_files_checked),
            "source_file_sha256": dict(sorted(api_file_hashes.items())),
            "raw_jkNo_key_absent_count": EXPECTED_ROWS,
            "raw_jkName_key_absent_count": EXPECTED_ROWS,
        },
        "source_rpt": {
            "archive_root": repo_relative(RPT_ROOT),
            "rpt_file_count_hashed": len(rpt_file_hashes),
            "parse_error_file_count": len(rpt_parse_errors),
            "parse_error_files": rpt_parse_errors,
            "jockey_name_candidate_match_count": report_status_counts["rpt_candidate_match_by_meet_date_trial_and_horse_number"],
            "no_local_rpt_day_count": report_status_counts["local_rpt_day_not_archived"],
            "no_local_rpt_days_and_row_counts": [
                {"source_meet_query": int(meet), "trial_date": date, "rows": count}
                for (meet, date), count in sorted(no_report_dates.items())
            ],
            "rpt_source_file_sha256_for_matched_rows": {
                path: digest
                for path, digest in sorted(rpt_file_hashes.items())
                if any(
                    match["source_file"] == path
                    for row in output_rows
                    for match in row["rpt_matches"]
                )
            },
        },
        "counts": {
            "audit_rows": len(output_rows),
            "rpt_jockey_name_candidates": sum(1 for row in output_rows if row["rpt_jockey_name_candidate"]),
            "rpt_jockey_name_verified_supplements": sum(1 for row in output_rows if row["rpt_jockey_name"]),
            "rpt_horse_name_validation": dict(sorted(horse_name_status_counts.items())),
            "rpt_jockey_supplement_status": dict(sorted(jockey_supplement_status_counts.items())),
            "verified_missing_api_horse_name_link_methods": dict(sorted(resolved_link_method_counts.items())),
            "api_horse_id_and_name_both_missing": sum(
                1 for row in output_rows if not row["api_hrNo"] and not row["api_hrName"]
            ),
            "rpt_day_not_archived": report_status_counts["local_rpt_day_not_archived"],
            "official_jockey_id_resolved": 0,
            "api_horse_id_also_missing": 18,
            "by_year": dict(sorted(year_counts.items())),
            "by_meet_query": dict(sorted(meet_counts.items())),
            "by_api_trainNo": dict(sorted(trial_no_counts.items(), key=lambda item: int(item[0]))),
            "by_api_passFlag": dict(sorted(flag_counts.items())),
            "by_api_rcTime_status": dict(sorted(time_counts.items())),
            "by_api_passFlag_and_rcTime_status": {
                f"{flag}|{time_bucket}": count
                for (flag, time_bucket), count in sorted(flag_time_counts.items())
            },
            "by_api_reason": dict(sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))),
            "by_api_wgJkAdd": dict(sorted(jockey_extra_weight_counts.items())),
            "session_coverage": {
                "sessions": int(session_coverage[0]),
                "all_participants_missing_jockey": int(session_coverage[1]),
                "some_participants_missing_jockey": int(session_coverage[2]),
                "no_participants_missing_jockey": int(session_coverage[3]),
            },
        },
        "validation": {
            "passed": True,
            "checks": {
                "core_db_read_only": True,
                "expected_missing_jockey_row_count": True,
                "api_raw_source_hash_and_item_match_db_json": True,
                "both_jockey_keys_absent_in_every_api_raw_item": True,
                "rpt_matches_use_meet_date_trial_and_horse_number": True,
                "rpt_source_hash_and_line_preserved_for_each_match": True,
                "rpt_names_kept_as_name_only_evidence": True,
                "all_candidate_horse_names_checked_against_api_or_resolved_link": True,
                "api_horse_name_mismatches_excluded_from_verified_supplements": True,
                "missing_api_horse_name_links_separately_sourced_and_exactly_matched": True,
                "verified_rpt_jockey_name_supplements": 5079,
                "rpt_horse_name_mismatch_candidates_excluded": 18,
                "rpt_horse_name_missing_api_with_link_exact_match": 18,
                "no_jockey_id_inferred_from_name": True,
                "no_core_db_mutation": True,
            },
        },
        "output": {"path": repo_relative(OUTPUT), "sha256": sha256(OUTPUT)},
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    result = build()
    print(json.dumps({"counts": result["counts"], "output": result["output"]}, ensure_ascii=False))
