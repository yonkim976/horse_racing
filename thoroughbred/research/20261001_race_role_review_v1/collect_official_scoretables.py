"""Collect official KRA race scoretable pages for exact event/runner keys.

The collector saves the public HTML response bytes and never uses profile-only
relationships to infer historical assignments. KRA link arguments on the
event-specific runner row are retained as string IDs, including leading zeroes.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import duckdb
import httpx
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
PRIOR_GAP_AUDIT = ROOT / "thoroughbred/research/20260930_missing_entity_source_audit_v1/race_role_gap_audit.jsonl"
ENDPOINT = "https://race.kra.co.kr/raceScore/ScoretableDetailList.do"
RAW_DIR = HERE / "raw_kra_scoretable"
MANIFEST_PATH = HERE / "official_scoretable_capture_manifest.json"
ROWS_PATH = HERE / "official_scoretable_runner_rows.jsonl"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def exact_event_runner_keys() -> list[dict[str, str]]:
    connection = duckdb.connect(str(DB), read_only=True)
    try:
        blank_rows = connection.execute(
            "SELECT source_meet, result_date, result_race_no, horse_program_no_raw, "
            "horse_id_raw, horse_name_raw, trainer_id_raw, trainer_name_raw, "
            "owner_id_raw, owner_name_raw, result_rank_raw, finish_time_seconds_raw, "
            "positive_finish_evidence, source_file, source_item_index "
            "FROM confirmed_runners WHERE trainer_id_raw IS NULL AND owner_id_raw IS NULL "
            "ORDER BY result_date, source_meet, result_race_no, horse_program_no_raw"
        ).fetchall()
        placeholder_rows = connection.execute(
            "SELECT source_meet, result_date, result_race_no, horse_program_no_raw, "
            "horse_id_raw, horse_name_raw, trainer_id_raw, trainer_name_raw, "
            "owner_id_raw, owner_name_raw, result_rank_raw, finish_time_seconds_raw, "
            "positive_finish_evidence, source_file, source_item_index "
            "FROM confirmed_runners WHERE trainer_id_raw = ? AND trainer_name_raw = ? "
            "ORDER BY result_date, source_meet, result_race_no, horse_program_no_raw",
            ["0AAAAA", "휴양마"],
        ).fetchall()
    finally:
        connection.close()

    prior = [json.loads(line) for line in PRIOR_GAP_AUDIT.read_text(encoding="utf-8").splitlines() if line]
    recovered = {
        (row["meet"], row["race_date"], row["race_no"], row["horse_program_no"], row["horse_id"])
        for row in prior
        if row.get("official_id_recovery_status") == "crosschecked_archived_api26_exact_event_key"
    }
    targets: list[dict[str, str]] = []
    for category, source_rows in (("source_missing", blank_rows), ("placeholder_0AAAAA", placeholder_rows)):
        for row in source_rows:
            (
                meet, race_date, race_no, program_no, horse_id, horse_name,
                trainer_id, trainer_name, owner_id, owner_name, rank, finish_time,
                positive_finish, source_file, source_index,
            ) = row
            key = (meet, race_date, race_no, program_no, horse_id)
            if category == "source_missing" and key in recovered:
                continue
            targets.append({
                "meet": str(meet),
                "date": str(race_date),
                "race_no": str(race_no),
                "horse_program_no": str(program_no),
                "horse_id": str(horse_id),
                "horse_name_api4_3": str(horse_name),
                "source_kind": category,
                "source_trainer_id_raw": trainer_id,
                "source_trainer_name_raw": trainer_name,
                "source_owner_id_raw": owner_id,
                "source_owner_name_raw": owner_name,
                "result_rank_raw": str(rank),
                "finish_time_seconds_raw": str(finish_time),
                "positive_finish_evidence": str(positive_finish),
                "api4_3_source_file": str(source_file),
                "api4_3_source_item_index_zero_based": str(source_index),
            })

    keys = [
        (x["meet"], x["date"], x["race_no"], x["horse_program_no"], x["horse_id"])
        for x in targets
    ]
    if any(
        x["meet"] not in {"1", "3"}
        or not re.fullmatch(r"\d{8}", x["date"])
        or not re.fullmatch(r"\d+", x["race_no"])
        or not re.fullmatch(r"\d+", x["horse_program_no"])
        or not re.fullmatch(r"\d+", x["horse_id"])
        for x in targets
    ):
        raise ValueError("Unexpected event key format in the read-only core DB")
    if len(targets) != 60 or len(set(keys)) != 60:
        raise ValueError(f"Expected 60 distinct unresolved/sentinel rows; found {len(targets)}")
    if sum(x["source_kind"] == "source_missing" for x in targets) != 37:
        raise ValueError("Expected 37 unresolved source-missing rows")
    if sum(x["source_kind"] == "placeholder_0AAAAA" for x in targets) != 23:
        raise ValueError("Expected 23 0AAAAA/휴양마 placeholder rows")
    return targets


def decode_html(raw: bytes, content_type: str | None) -> tuple[str, str]:
    declared = None
    if content_type:
        match = re.search(r"charset\s*=\s*['\"]?([A-Za-z0-9._-]+)", content_type, re.I)
        if match:
            declared = match.group(1)
    head = raw[:4096].decode("ascii", errors="ignore")
    if declared is None:
        match = re.search(r"<meta[^>]+charset\s*=\s*['\"]?([A-Za-z0-9._-]+)", head, re.I)
        if match:
            declared = match.group(1)
    charset = declared or "euc-kr"
    try:
        return raw.decode(charset), charset
    except (LookupError, UnicodeDecodeError):
        return raw.decode("euc-kr", errors="replace"), "euc-kr"


def js_args(href: str | None, function_name: str) -> list[str] | None:
    if not href:
        return None
    match = re.search(rf"\b{re.escape(function_name)}\s*\(([^)]*)\)", href)
    if not match:
        return None
    return re.findall(r"['\"]([^'\"]*)['\"]", match.group(1))


def extract_target_rows(html: str, target: dict[str, str]) -> tuple[dict, list[dict]]:
    soup = BeautifulSoup(html, "html.parser")
    result_rows: list[dict] = []
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"], recursive=False)
            if not cells:
                continue
            horse_anchor = next(
                (a for a in tr.find_all("a") if js_args(a.get("href"), "goHorse")),
                None,
            )
            if horse_anchor is None:
                continue
            horse_args = js_args(horse_anchor.get("href"), "goHorse") or []
            if not horse_args:
                continue
            if horse_args[0] != target["horse_id"]:
                continue
            program_no = cells[1].get_text(" ", strip=True) if len(cells) > 1 else None
            meet_in_link = horse_args[1] if len(horse_args) > 1 else None
            trainer_anchor = next(
                (a for a in tr.find_all("a") if js_args(a.get("href"), "goTrainer")),
                None,
            )
            owner_anchor = next(
                (a for a in tr.find_all("a") if js_args(a.get("href"), "goOwner")),
                None,
            )
            trainer_args = js_args(trainer_anchor.get("href"), "goTrainer") if trainer_anchor else None
            owner_args = js_args(owner_anchor.get("href"), "goOwner") if owner_anchor else None
            result_rows.append({
                "horse_id_from_event_row_link": horse_args[0],
                "meet_from_event_row_link": meet_in_link,
                "horse_program_no_web": program_no,
                "horse_name_web": horse_anchor.get_text(" ", strip=True),
                "trainer_id_from_event_row_link": trainer_args[0] if trainer_args else None,
                "trainer_meet_from_event_row_link": trainer_args[1] if trainer_args and len(trainer_args) > 1 else None,
                "trainer_name_web": trainer_anchor.get_text(" ", strip=True) if trainer_anchor else None,
                "owner_id_from_event_row_link": owner_args[0] if owner_args else None,
                "owner_meet_from_event_row_link": owner_args[1] if owner_args and len(owner_args) > 1 else None,
                "owner_name_web": owner_anchor.get_text(" ", strip=True) if owner_anchor else None,
                "result_status_web": " ".join(c.get_text(" ", strip=True) for c in cells[11:12]) or None,
                "row_text_web": " ".join(tr.get_text(" ", strip=True).split()),
            })
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    page_text = " ".join(soup.get_text(" ", strip=True).split())
    return {
        "page_title": title,
        "event_heading_present": target["date"][:4] in page_text and target["race_no"] in page_text,
        "page_contains_expected_horse_name": target["horse_name_api4_3"] in page_text,
    }, result_rows


def main() -> None:
    targets = exact_event_runner_keys()
    events = sorted({(x["meet"], x["date"], x["race_no"]) for x in targets})
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    captures: dict[tuple[str, str, str], dict] = {}

    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        for index, (meet, race_date, race_no) in enumerate(events, start=1):
            params = {
                "Act": "04",
                "Sub": "1",
                "meet": meet,
                "realRcDate": race_date,
                "realRcNo": race_no,
            }
            request_url = f"{ENDPOINT}?{urlencode(params)}"
            observed_at = utc_now()
            filename = f"meet_{meet}_date_{race_date}_race_{race_no}.html"
            raw_path = RAW_DIR / filename
            capture = {
                "meet": meet,
                "date": race_date,
                "race_no": race_no,
                "request_url": request_url,
                "observed_at_utc": observed_at,
                "raw_file": raw_path.relative_to(ROOT).as_posix(),
            }
            try:
                response = client.get(ENDPOINT, params=params)
                response.raise_for_status()
                raw = response.content
                raw_path.write_bytes(raw)
                html, charset = decode_html(raw, response.headers.get("content-type"))
                matching_targets = [
                    x for x in targets
                    if (x["meet"], x["date"], x["race_no"]) == (meet, race_date, race_no)
                ]
                parsed_rows: list[dict] = []
                page_info = None
                for target in matching_targets:
                    page_info, target_rows = extract_target_rows(html, target)
                    for row in target_rows:
                        row.update({
                            "meet": meet,
                            "date": race_date,
                            "race_no": race_no,
                            "target_horse_program_no": target["horse_program_no"],
                            "target_horse_id": target["horse_id"],
                            "target_horse_name_api4_3": target["horse_name_api4_3"],
                        })
                        parsed_rows.append(row)
                capture.update({
                    "capture_status": "http_ok",
                    "http_status": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "decoded_charset": charset,
                    "sha256": sha256(raw),
                    "bytes": len(raw),
                    "page_title": page_info["page_title"] if page_info else None,
                    "event_heading_present": page_info["event_heading_present"] if page_info else False,
                    "target_rows": parsed_rows,
                })
            except (httpx.HTTPError, OSError, ValueError) as exc:
                capture.update({
                    "capture_status": "request_or_parse_error",
                    "error_type": type(exc).__name__,
                    "target_rows": [],
                })
            captures[(meet, race_date, race_no)] = capture
            if index < len(events):
                time.sleep(0.4)

    observations: list[dict] = []
    for target in targets:
        event_key = (target["meet"], target["date"], target["race_no"])
        capture = captures[event_key]
        rows = [
            row for row in capture.get("target_rows", [])
            if row["target_horse_id"] == target["horse_id"]
            and row["horse_program_no_web"] == target["horse_program_no"]
        ]
        exact = rows[0] if len(rows) == 1 else None
        if capture["capture_status"] != "http_ok":
            status = "official_web_capture_failed"
        elif len(rows) == 0:
            status = "official_web_event_row_not_exactly_recovered"
        elif len(rows) > 1:
            status = "official_web_event_row_ambiguous"
        elif target["source_kind"] == "placeholder_0AAAAA":
            status = "placeholder_0AAAAA_web_row_checked"
        elif exact.get("trainer_id_from_event_row_link") and exact.get("owner_id_from_event_row_link"):
            status = "exact_event_row_trainer_owner_ids_recovered"
        elif exact.get("trainer_id_from_event_row_link"):
            status = "exact_event_row_trainer_id_recovered_owner_unresolved"
        elif exact.get("owner_id_from_event_row_link"):
            status = "exact_event_row_owner_id_recovered_trainer_unresolved"
        else:
            status = "exact_event_row_has_no_person_links"
        observed = {
            **target,
            "review_status": status,
            "verified_supplemental_trainer_id": None,
            "verified_supplemental_trainer_name": None,
            "verified_supplemental_owner_id": None,
            "verified_supplemental_owner_name": None,
            "official_web_source_file": capture["raw_file"],
            "official_web_source_sha256": capture.get("sha256"),
            "observed_at_utc": capture["observed_at_utc"],
            "request_url": capture["request_url"],
            "capture_status": capture["capture_status"],
            "exact_event_row": exact,
        }
        if exact:
            observed["event_row_role_link_meet_mismatch"] = any(
                link_meet not in (None, target["meet"])
                for link_meet in (
                    exact.get("meet_from_event_row_link"),
                    exact.get("trainer_meet_from_event_row_link"),
                    exact.get("owner_meet_from_event_row_link"),
                )
            )
            observed["horse_name_alias_difference"] = (
                exact.get("horse_name_web") != target["horse_name_api4_3"]
            )
        if exact and target["source_kind"] == "source_missing":
            observed["verified_supplemental_trainer_id"] = exact.get("trainer_id_from_event_row_link")
            observed["verified_supplemental_trainer_name"] = exact.get("trainer_name_web")
            observed["verified_supplemental_owner_id"] = exact.get("owner_id_from_event_row_link")
            observed["verified_supplemental_owner_name"] = exact.get("owner_name_web")
        if exact and target["source_kind"] == "placeholder_0AAAAA":
            observed["web_trainer_id_observed"] = exact.get("trainer_id_from_event_row_link")
            observed["web_trainer_name_observed"] = exact.get("trainer_name_web")
            observed["web_owner_id_observed"] = exact.get("owner_id_from_event_row_link")
            observed["web_owner_name_observed"] = exact.get("owner_name_web")
            if exact.get("trainer_id_from_event_row_link") not in (None, "0AAAAA") or exact.get("trainer_name_web") not in (None, "휴양마"):
                observed["review_status"] = "placeholder_web_person_semantic_conflict_review_only"
        observations.append(observed)

    ROWS_PATH.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in observations),
        encoding="utf-8",
    )
    manifest = {
        "source": "KRA race.kra.co.kr ScoretableDetailList.do event-specific race score table",
        "captured_at_utc": utc_now(),
        "endpoint": ENDPOINT,
        "requested_event_count": len(events),
        "target_row_count": len(targets),
        "source_missing_count": sum(x["source_kind"] == "source_missing" for x in targets),
        "placeholder_count": sum(x["source_kind"] == "placeholder_0AAAAA" for x in targets),
        "capture_success_count": sum(x["capture_status"] == "http_ok" for x in captures.values()),
        "exact_event_row_count": sum(x["exact_event_row"] is not None for x in observations),
        "trainer_owner_ids_recovered_count": sum(
            bool(x["verified_supplemental_trainer_id"] and x["verified_supplemental_owner_id"])
            for x in observations
        ),
        "placeholder_web_person_conflict_count": sum(
            x["review_status"] == "placeholder_web_person_semantic_conflict_review_only"
            for x in observations
        ),
        "rows_file": ROWS_PATH.relative_to(ROOT).as_posix(),
        "rows_file_sha256": sha256(ROWS_PATH.read_bytes()),
        "captures": list(captures.values()),
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "events": len(events),
        "target_rows": len(observations),
        "capture_success": manifest["capture_success_count"],
        "exact_rows": manifest["exact_event_row_count"],
        "trainer_owner_ids_recovered": manifest["trainer_owner_ids_recovered_count"],
        "placeholder_web_person_conflicts": manifest["placeholder_web_person_conflict_count"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
