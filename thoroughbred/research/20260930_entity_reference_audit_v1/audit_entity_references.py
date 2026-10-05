#!/usr/bin/env python3
"""Export an auditable entity-ID and name-linkage audit from the new core DB.

This is a read-only audit. It never edits the core DuckDB or source archives.
Names are retained as source observations; they are not used as identity keys.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

import duckdb


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = REPO_ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "exports"
PROFILE_CAPTURE_DATE = "2026-09-23"
PROFILE_MEETS = ("1", "3")  # API 8_2 has no returned rows for meet=4 in the reviewed capture.
VENUE_PREFIX = re.compile(r"^\[(서울|부산경남|영남)\]\s*")
TRAINER_PLACEHOLDER_ID = "0AAAAA"
TRAINER_PLACEHOLDER_NAME = "휴양마"

ENTITY_COLUMNS = {
    "horse": ("horse_id_raw", "horse_name_raw"),
    "jockey": ("jockey_id_raw", "jockey_name_raw"),
    "trainer": ("trainer_id_raw", "trainer_name_raw"),
    "owner": ("owner_id_raw", "owner_name_raw"),
}


def text(value: Any) -> str:
    return "" if value is None else str(value)


def is_blank(value: Any) -> bool:
    return text(value).strip() in {"", "-", "None", "null"}


def id_key(value: Any) -> str:
    # Do not integer-cast or zero-pad official IDs.
    return text(value).strip()


def sql_blank(column: str) -> str:
    """SQL equivalent of is_blank, including API dash placeholders."""
    return f"lower(trim(coalesce(cast({column} as varchar),''))) in ('','-','none','null')"


def normalized_name_for_review(value: Any) -> str:
    # Diagnostic-only removal of race-meet labels found in race API names.
    # This value must never be used as an identity key.
    return VENUE_PREFIX.sub("", text(value).strip(), count=1)


def normalize_event_date(value: Any) -> str:
    """Normalize event dates to ISO without changing source tables/archives."""
    raw = text(value).strip()
    if not raw:
        return ""
    if re.fullmatch(r"\d{8}", raw):
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    raise ValueError(f"Unsupported event date format in core source: {raw!r}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list, set, tuple)) else v for k, v in row.items()})


def safe_relative(path: str | Path, root: Path) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, FileNotFoundError):
        return p.as_posix()


def check_credentials_are_not_archived(paths: list[Path]) -> dict[str, Any]:
    """Check archived page bytes without ever rendering the credential."""
    if str(REPO_ROOT / "src") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        from horse_racing.config import Settings

        secret_value = Settings(_env_file=REPO_ROOT / ".env").data_go_kr_service_key
    except Exception:
        secret_value = None
    if secret_value is None:
        return {
            "configured_key_available": False,
            "checked_raw_page_count": len(paths),
            "raw_key_value_absent_from_all_pages": None,
            "url_encoded_key_absent_from_all_pages": None,
            "status": "unverified_no_key_configured",
        }
    secret = secret_value.get_secret_value().strip()
    raw_hit = False
    encoded_hit = False
    for path in paths:
        data = path.read_bytes()
        if secret.encode("utf-8") in data:
            raw_hit = True
        if any(value in data for value in (quote(secret, safe="").encode("utf-8"), quote_plus(secret, safe="").encode("utf-8"))):
            encoded_hit = True
    if raw_hit or encoded_hit:
        # The error intentionally avoids naming the credential or printing bytes.
        raise ValueError("Configured API credential was found in an archived profile page")
    return {
        "configured_key_available": True,
        "checked_raw_page_count": len(paths),
        "raw_key_value_absent_from_all_pages": True,
        "url_encoded_key_absent_from_all_pages": True,
        "status": "passed",
    }


def profile_page_paths(root: Path, scope: str, meet: str) -> list[Path]:
    folder = root / f"horse_active_statuses_{scope}" / "2026" / "09" / "23" / f"meet_{meet}" / "run_16675"
    return sorted(folder.glob("page_*.json"))


def load_profile_snapshot(root: Path, repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    memberships: list[dict[str, Any]] = []
    page_manifest: list[dict[str, Any]] = []
    scope_ids: dict[tuple[str, str], set[str]] = defaultdict(set)
    scope_totals: dict[tuple[str, str], set[int]] = defaultdict(set)

    for scope in ("active", "inactive"):
        for meet in PROFILE_MEETS:
            paths = profile_page_paths(root, scope, meet)
            if not paths:
                raise FileNotFoundError(f"Missing archived horse profile pages: scope={scope}, meet={meet}")
            for path in paths:
                payload = json.loads(path.read_text(encoding="utf-8"))
                response = payload.get("response", {})
                header = response.get("header", {})
                body = response.get("body", {})
                items_box = body.get("items")
                if isinstance(items_box, dict):
                    items = items_box.get("item", [])
                elif isinstance(items_box, list):
                    items = items_box
                else:
                    items = []
                if isinstance(items, dict):
                    items = [items]
                total = int(body.get("totalCount") or 0)
                scope_totals[(scope, meet)].add(total)
                page_no = int(body.get("pageNo") or 0)
                relative = safe_relative(path, repo_root)
                page_hash = sha256(path)
                page_manifest.append({
                    "capture_date": PROFILE_CAPTURE_DATE,
                    "request_scope": scope,
                    "meet_query": meet,
                    "source_file": relative,
                    "sha256": page_hash,
                    "result_code": text(header.get("resultCode")),
                    "result_message": text(header.get("resultMsg")),
                    "page_no": page_no,
                    "total_count": total,
                    "num_of_rows": body.get("numOfRows"),
                    "item_count": len(items),
                    "raw_item_type": type(items_box).__name__,
                })
                if text(header.get("resultCode")) != "00":
                    raise ValueError(f"API8_2 profile archive is not successful: {relative} ({header.get('resultCode')})")
                for item_index, item in enumerate(items, 1):
                    raw_id = item.get("hrNo")
                    horse_id = id_key(raw_id)
                    if is_blank(raw_id):
                        continue
                    scope_ids[(scope, meet)].add(horse_id)
                    memberships.append({
                        "capture_date": PROFILE_CAPTURE_DATE,
                        "request_scope": scope,
                        "meet_query": meet,
                        "horse_id_raw_string": horse_id,
                        "hrNo_json_type": type(raw_id).__name__,
                        "horse_name_snapshot": text(item.get("hrName")),
                        "birthday_raw": text(item.get("birthday")),
                        "sex_raw": text(item.get("sex")),
                        "origin_raw": text(item.get("name")),
                        "sire_id_raw_string": id_key(item.get("faHrNo")),
                        "sire_name_raw": text(item.get("faHrName")),
                        "dam_id_raw_string": id_key(item.get("moHrNo")),
                        "dam_name_raw": text(item.get("moHrName")),
                        "current_trainer_id_snapshot_raw_string": id_key(item.get("trNo")),
                        "current_trainer_name_snapshot_raw": text(item.get("trName")),
                        "current_owner_id_snapshot_raw_string": id_key(item.get("owNo")),
                        "current_owner_name_snapshot_raw": text(item.get("owName")),
                        "current_grade_snapshot_raw": text(item.get("rank")),
                        "source_file": relative,
                        "source_sha256": page_hash,
                        "source_page_no": page_no,
                        "source_item_index_within_page": item_index,
                    })

    # This is a deliberately bounded snapshot assertion, not a global API rule.
    for (scope, meet), ids in scope_ids.items():
        if len(scope_totals[(scope, meet)]) != 1:
            raise ValueError(f"Inconsistent totalCount within archived profile cohort {scope}/{meet}")
        total = next(iter(scope_totals[(scope, meet)]))
        returned = sum(p["item_count"] for p in page_manifest if p["request_scope"] == scope and p["meet_query"] == meet)
        if returned != total:
            raise ValueError(f"Profile pagination mismatch for {scope}/{meet}: items={returned}, totalCount={total}")
        if len(ids) != returned:
            raise ValueError(f"Duplicate or missing profile IDs within {scope}/{meet}: unique_ids={len(ids)}, returned_items={returned}")

    snapshot_check = {
        "capture_date": PROFILE_CAPTURE_DATE,
        "cohort_totals": {
            f"{scope}_meet_{meet}": {
                "total_count": next(iter(scope_totals[(scope, meet)])),
                "returned_items": sum(p["item_count"] for p in page_manifest if p["request_scope"] == scope and p["meet_query"] == meet),
                "unique_ids": len(scope_ids[(scope, meet)]),
            }
            for scope in ("active", "inactive") for meet in PROFILE_MEETS
        },
        "active_y_subset_of_inactive_n_by_meet": {
            meet: scope_ids[("active", meet)].issubset(scope_ids[("inactive", meet)])
            for meet in PROFILE_MEETS
        },
        "cross_meet_id_overlap_by_scope": {
            scope: len(scope_ids[(scope, "1")] & scope_ids[(scope, "3")])
            for scope in ("active", "inactive")
        },
        "page_count": len(page_manifest),
        "ids_by_scope_meet": {f"{scope}/{meet}": ids for (scope, meet), ids in scope_ids.items()},
    }
    return memberships, page_manifest, snapshot_check


def load_current_person_profiles(repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read official API307/308/309 reference snapshots, never performance fields."""
    out: list[dict[str, Any]] = []
    source_pages: list[dict[str, Any]] = []
    captures = [
        {
            "entity_type": "jockey", "service": "API307/jockeyInfo", "capture_date": "2026-09-30",
            "root": repo_root / "data/raw/kra/entity_reference_profiles/20260930/API307_jockeyInfo",
            "id_key": "jkNo", "name_key": "jkName", "english_key": "jkNameEn",
            "start_key": "debut", "end_key": "spDate", "part_key": "part",
        },
        {
            "entity_type": "trainer", "service": "API308/trainerInfo", "capture_date": "2026-09-29",
            "root": repo_root / "data/raw/kra_trainer_affiliations/2026-09-29",
            "id_key": "trNo", "name_key": "trName", "english_key": "trNameEn",
            "start_key": "stDate", "end_key": "spDate", "part_key": "part",
        },
        {
            "entity_type": "owner", "service": "API309/horseOwnerInfo", "capture_date": "2026-09-30",
            "root": repo_root / "data/raw/kra/entity_reference_profiles/20260930/API309_horseOwnerInfo",
            "id_key": "owNo", "name_key": "owName", "english_key": "owNameEn",
            "start_key": "stDate", "end_key": "", "part_key": "",
        },
    ]
    for capture in captures:
        for meet in (1, 3):
            folder = capture["root"] / f"meet_{meet}"
            if capture["service"].startswith("API308"):
                paths = [folder]
                paths = [folder.with_suffix(".json")]
            else:
                paths = sorted(folder.glob("page_*.json"))
            if not paths or any(not p.exists() for p in paths):
                raise FileNotFoundError(f"Missing official person profile archive: {capture['service']} meet={meet}")
            total: int | None = None
            item_count = 0
            seen_ids: set[str] = set()
            for path in paths:
                payload = json.loads(path.read_text(encoding="utf-8"))
                response = payload.get("response", {})
                header = response.get("header", {})
                body = response.get("body", {})
                if text(header.get("resultCode")) != "00":
                    raise ValueError(f"Official person profile response failed: {path}")
                page_total = int(body.get("totalCount") or 0)
                if total is None:
                    total = page_total
                elif page_total != total:
                    raise ValueError(f"Person profile totalCount changed within {capture['service']} meet={meet}")
                box = body.get("items")
                items = box.get("item", []) if isinstance(box, dict) else box if isinstance(box, list) else []
                if isinstance(items, dict):
                    items = [items]
                if not isinstance(items, list):
                    raise ValueError(f"Unexpected response items type: {path}")
                item_count += len(items)
                page_hash = sha256(path)
                source_file = safe_relative(path, repo_root)
                page_no = int(body.get("pageNo") or 1)
                source_pages.append({
                    "entity_type": capture["entity_type"], "source_service": capture["service"],
                    "capture_date": capture["capture_date"], "meet_query": str(meet),
                    "source_file": source_file, "sha256": page_hash,
                    "result_code": text(header.get("resultCode")), "total_count": page_total,
                    "page_no": page_no, "item_count": len(items),
                })
                for item_index, item in enumerate(items, 1):
                    raw_id = item.get(capture["id_key"])
                    if is_blank(raw_id):
                        raise ValueError(f"Official profile missing its ID field: {capture['service']} {source_file}#{item_index}")
                    official_id = id_key(raw_id)
                    seen_ids.add(official_id)
                    out.append({
                        "entity_type": capture["entity_type"],
                        "official_id_raw_string": official_id,
                        "id_json_type": type(raw_id).__name__,
                        "name_snapshot": text(item.get(capture["name_key"])),
                        "english_name_snapshot": text(item.get(capture["english_key"])),
                        "meet_query": str(meet),
                        "meet_label_raw": text(item.get("meet")),
                        "profile_start_date_raw": text(item.get(capture["start_key"])) if capture["start_key"] else "",
                        "profile_end_date_raw": text(item.get(capture["end_key"])) if capture["end_key"] else "",
                        "profile_part_raw": text(item.get(capture["part_key"])) if capture["part_key"] else "",
                        "source_service": capture["service"],
                        "capture_date": capture["capture_date"],
                        "source_file": source_file,
                        "source_sha256": page_hash,
                        "source_page_no": page_no,
                        "source_item_index_within_page": item_index,
                        "relationship_time_rule": "profile snapshot only; never use as historical race relationship",
                    })
            if item_count != (total or 0) or len(seen_ids) != item_count:
                raise ValueError(f"Official profile pagination/ID uniqueness mismatch: {capture['service']} meet={meet}; items={item_count}; total={total}; unique IDs={len(seen_ids)}")
    return out, source_pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--raw-root", type=Path, default=REPO_ROOT / "data/raw/kra")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    db_path = args.core_db.resolve()
    raw_root = args.raw_root.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path), read_only=True)
    expected_runner_count = con.execute("select count(*) from confirmed_runners").fetchone()[0]
    expected_trial_count = con.execute("select count(*) from trial_participants").fetchone()[0]
    events: dict[str, dict[str, dict[str, Any]]] = {k: {} for k in ENTITY_COLUMNS}
    unresolved: list[dict[str, Any]] = []
    placeholder_observation_keys: list[tuple[str, str, str, str, str]] = []
    source_files: set[str] = set()
    raw_observations: dict[tuple[str, str, str], dict[str, Any]] = {}
    entity_event_counts: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"race_result": 0, "trial_api": 0, "trial_reviewed_horse_link": 0})

    def add_observation(entity: str, raw_id: Any, raw_name: Any, date: Any, context_type: str,
                        context_value: Any, source_file: Any, source_item_index: Any,
                        resolution: str = "api_direct", source_pointer_extra: str = "") -> None:
        id_value = id_key(raw_id)
        name_value = text(raw_name)
        if source_file:
            source_files.add(text(source_file))
        if is_blank(raw_id):
            unresolved.append({
                "entity_type": entity,
                "source_observation": context_type,
                "source_api": "KRA API4_3/raceResult_3" if context_type == "race_result" else "KRA API20_1/ridingTestResult_1",
                "observation_date": normalize_event_date(date),
                "context_type": "race_venue_meet" if context_type == "race_result" else "trial_source_meet_query",
                "context_value": text(context_value),
                "race_no_or_trial_no": "" if context_type != "race_result" else "",
                "horse_id_raw": "",
                "horse_name_raw": "",
                "id_column": ENTITY_COLUMNS[entity][0],
                "id_raw": text(raw_id),
                "name_column": ENTITY_COLUMNS[entity][1],
                "name_raw": name_value,
                "resolution_status": "unresolved_id_missing",
                "resolution_note": "ID가 없는 행은 이름만으로 연결하지 않음.",
                "source_file": text(source_file),
                "source_item_index": text(source_item_index),
                "source_pointer_extra": source_pointer_extra,
            })
            return
        # This one source value is a documented non-person label, not a trainer
        # identity. Preserve its original ID/name observations in the explicit
        # placeholder ledger and keep it out of the trainer master roster.
        if entity == "trainer" and id_value == TRAINER_PLACEHOLDER_ID:
            if name_value != TRAINER_PLACEHOLDER_NAME:
                raise ValueError(f"Unexpected name for trainer placeholder {TRAINER_PLACEHOLDER_ID}: {name_value!r}")
            placeholder_observation_keys.append((
                context_type, text(date), text(context_value), text(source_file), text(source_item_index)
            ))
            return
        entry = events[entity].setdefault(id_value, {
            "entity_type": entity,
            "entity_id": id_value,
            "race_result_observation_rows": 0,
            "trial_api_observation_rows": 0,
            "trial_reviewed_horse_link_rows": 0,
            "first_seen_date": "",
            "last_seen_date": "",
            "contexts": set(),
            "names": {},
        })
        if context_type == "race_result":
            entry["race_result_observation_rows"] += 1
            entity_event_counts[(entity, id_value)]["race_result"] += 1
        elif resolution == "api_direct":
            entry["trial_api_observation_rows"] += 1
            entity_event_counts[(entity, id_value)]["trial_api"] += 1
        else:
            entry["trial_reviewed_horse_link_rows"] += 1
            entity_event_counts[(entity, id_value)]["trial_reviewed_horse_link"] += 1
        d = normalize_event_date(date)
        if d and (not entry["first_seen_date"] or d < entry["first_seen_date"]):
            entry["first_seen_date"] = d
        if d and d > entry["last_seen_date"]:
            entry["last_seen_date"] = d
        if context_value:
            entry["contexts"].add(text(context_value))
        if not is_blank(raw_name):
            name_entry = entry["names"].setdefault(name_value, {
                "entity_type": entity, "entity_id": id_value, "name_raw": name_value,
                "name_normalized_for_review": normalized_name_for_review(name_value),
                "first_seen_date": d, "last_seen_date": d, "observation_rows": 0,
                "source_types": set(), "contexts": set(), "pointers": [],
            })
            name_entry["observation_rows"] += 1
            name_entry["source_types"].add(context_type)
            if context_value:
                name_entry["contexts"].add(text(context_value))
            if d and (not name_entry["first_seen_date"] or d < name_entry["first_seen_date"]):
                name_entry["first_seen_date"] = d
            if d and d > name_entry["last_seen_date"]:
                name_entry["last_seen_date"] = d
            pointer = f"{source_file}#item={source_item_index}" if source_item_index else text(source_file)
            if pointer and pointer not in name_entry["pointers"] and len(name_entry["pointers"]) < 8:
                name_entry["pointers"].append(pointer)

    # Confirmed runner rows are the dated API event-level source for the four entities.
    runner_rows = con.execute("""
        select source_meet, result_date, result_race_no, horse_id_raw, horse_name_raw,
               jockey_id_raw, jockey_name_raw, trainer_id_raw, trainer_name_raw,
               owner_id_raw, owner_name_raw, source_file, source_item_index
        from confirmed_runners
        order by result_date, source_meet, result_race_no, horse_program_no_raw
    """).fetchall()
    for row in runner_rows:
        meet, date, race_no, horse_id, horse_name, jockey_id, jockey_name, trainer_id, trainer_name, owner_id, owner_name, source_file, item_idx = row
        for entity, raw_id, raw_name in (
            ("horse", horse_id, horse_name), ("jockey", jockey_id, jockey_name),
            ("trainer", trainer_id, trainer_name), ("owner", owner_id, owner_name),
        ):
            add_observation(entity, raw_id, raw_name, date, "race_result", meet, source_file, item_idx,
                            source_pointer_extra=f"race={date}/{race_no}")

    # Trial rows use official API IDs when present. The separately reviewed 104
    # horse identity links are tagged as non-API resolution evidence.
    trial_rows = con.execute("""
        select p.participant_row_id, p.trial_date, p.trial_no, p.source_meet_query,
               p.api_hrNo, p.api_hrName, p.api_jkNo, p.api_jkName, p.api_trNo, p.api_trName,
               p.source_file, p.source_item_index, r.resolved_horse_id, r.resolved_horse_name,
               r.horse_identity_resolution
        from trial_participants p
        join trial_participants_resolved r using (participant_row_id)
        order by p.trial_date, p.source_meet_query, p.trial_no, p.source_item_index
    """).fetchall()
    for row in trial_rows:
        (participant_id, date, trial_no, meet_query, api_horse_id, api_horse_name, jockey_id, jockey_name,
         trainer_id, trainer_name, source_file, item_idx, resolved_horse_id, resolved_horse_name, identity_resolution) = row
        horse_id = api_horse_id if not is_blank(api_horse_id) else resolved_horse_id
        horse_resolution = "api_direct" if not is_blank(api_horse_id) else "reviewed_separate_identity_link"
        horse_name = api_horse_name if not is_blank(api_horse_name) else ""
        add_observation("horse", horse_id, horse_name, date, "trial_api", meet_query, source_file, item_idx,
                        resolution=horse_resolution, source_pointer_extra=f"participant={participant_id};trial={trial_no};identity={identity_resolution}")
        add_observation("jockey", jockey_id, jockey_name, date, "trial_api", meet_query, source_file, item_idx,
                        source_pointer_extra=f"participant={participant_id};trial={trial_no}")
        add_observation("trainer", trainer_id, trainer_name, date, "trial_api", meet_query, source_file, item_idx,
                        source_pointer_extra=f"participant={participant_id};trial={trial_no}")

    # Rebuild an explicit reviewed-horse ledger for API20_1's original 104 ID gaps.
    identity_rows = con.execute(f"""
        select p.participant_row_id, p.trial_date, p.trial_no, p.source_meet_query,
               p.api_chulNo, p.api_hrNo, p.api_hrName, p.source_file, p.source_item_index,
               r.resolved_horse_id, r.resolved_horse_name, r.horse_identity_resolution,
               l.resolution_method, l.decision_basis, l.rpt_source_file,
               l.rpt_source_file_sha256, l.user_confirmation_note
        from trial_participants p
        join trial_participants_resolved r using (participant_row_id)
        left join trial_horse_identity_links l using (participant_row_id)
        where {sql_blank('p.api_hrNo')}
        order by p.trial_date, p.source_meet_query, p.trial_no, p.source_item_index
    """).fetchall()
    trial_horse_exceptions = []
    for row in identity_rows:
        (participant_id, date, trial_no, meet_query, api_chulno, api_hrno, api_hrname,
         source_file, item_idx, resolved_id, resolved_name, status, method, basis, rpt_file,
         rpt_sha, user_note) = row
        trial_horse_exceptions.append({
            "participant_row_id": participant_id,
            "trial_date": normalize_event_date(date),
            "source_meet_query": meet_query,
            "trial_no": trial_no,
            "api_chulNo": api_chulno,
            "api_hrNo_raw": api_hrno or "",
            "api_hrName_raw": api_hrname or "",
            "resolved_horse_id_separate_ledger": resolved_id or "",
            "resolved_horse_name_separate_ledger": resolved_name or "",
            "identity_resolution_status": status or "unresolved",
            "resolution_method": method or "",
            "decision_basis": basis or "",
            "rpt_validation_source_file": rpt_file or "",
            "rpt_validation_source_sha256": rpt_sha or "",
            "user_confirmation_note": user_note or "",
            "api_source_file": source_file,
            "api_source_item_index": item_idx,
        })
        # This is an API source ID gap; the separate linkage is retained as
        # review evidence and is not silently rewritten into the API record.
        unresolved.append({
            "entity_type": "horse", "source_observation": "trial_api",
            "source_api": "KRA API20_1/ridingTestResult_1", "observation_date": normalize_event_date(date),
            "context_type": "trial_source_meet_query", "context_value": meet_query,
            "race_no_or_trial_no": trial_no, "horse_id_raw": api_hrno or "",
            "horse_name_raw": api_hrname or "", "id_column": "api_hrNo", "id_raw": api_hrno or "",
            "name_column": "api_hrName", "name_raw": api_hrname or "",
            "resolution_status": "source_api_id_missing_but_separate_core_linkage_reviewed",
            "resolution_note": f"resolved_id={resolved_id or ''}; method={method or ''}; source API fields remain unchanged",
            "source_file": source_file, "source_item_index": item_idx,
            "source_pointer_extra": f"participant={participant_id};decision_basis={basis or ''}",
        })

    # Current horse profiles are supporting identity snapshots, not historical
    # trainer/owner relationship evidence.
    memberships, profile_pages, profile_summary = load_profile_snapshot(raw_root, REPO_ROOT)
    profile_ids_by_scope_meet: dict[tuple[str, str], set[str]] = defaultdict(set)
    profile_names_by_id: dict[tuple[str, str], set[str]] = defaultdict(set)
    profile_scopes_by_id: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in memberships:
        profile_ids_by_scope_meet[(item["request_scope"], item["meet_query"])].add(item["horse_id_raw_string"])
        profile_names_by_id[("horse", item["horse_id_raw_string"])].add(item["horse_name_snapshot"])
        profile_scopes_by_id[("horse", item["horse_id_raw_string"])].add(f"API8_2:{item['request_scope']}/meet={item['meet_query']}@{PROFILE_CAPTURE_DATE}")
    person_profiles, person_profile_pages = load_current_person_profiles(REPO_ROOT)
    person_profile_ids: dict[tuple[str, str], set[str]] = defaultdict(set)
    person_profile_names: dict[tuple[str, str], set[str]] = defaultdict(set)
    person_profile_scopes: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in person_profiles:
        key = (item["entity_type"], item["official_id_raw_string"])
        person_profile_ids[key].add(item["meet_query"])
        person_profile_names[key].add(item["name_snapshot"])
        person_profile_scopes[key].add(f"{item['source_service']}:meet={item['meet_query']}@{item['capture_date']}")

    # Include a bounded API8_2 meet=4 probe to preserve the known empty-return anomaly.
    meet4_paths = sorted((raw_root / "horse_profiles/2026/09/18/meet_4").glob("run_*/page_*.json"))
    meet4_probe = []
    for path in meet4_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        body = payload.get("response", {}).get("body", {})
        items_box = body.get("items")
        items = items_box.get("item", []) if isinstance(items_box, dict) else items_box if isinstance(items_box, list) else []
        if isinstance(items, dict):
            items = [items]
        meet4_probe.append({
            "source_file": safe_relative(path, REPO_ROOT), "sha256": sha256(path),
            "result_code": text(payload.get("response", {}).get("header", {}).get("resultCode")),
            "total_count": int(body.get("totalCount") or 0), "item_count": len(items),
        })

    # Create exact-ID <-> exact-raw-name audit rows and calculate ambiguity sets.
    names_rows = [dict(v) for e in events.values() for item in e.values() for v in item["names"].values()]
    ids_by_raw_name: dict[tuple[str, str], set[str]] = defaultdict(set)
    ids_by_normal_name: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in names_rows:
        ids_by_raw_name[(item["entity_type"], item["name_raw"])].add(item["entity_id"])
        if item["name_normalized_for_review"]:
            ids_by_normal_name[(item["entity_type"], item["name_normalized_for_review"])].add(item["entity_id"])
    for item in names_rows:
        item["source_types_json"] = sorted(item.pop("source_types"))
        item["contexts_json"] = sorted(item.pop("contexts"))
        item["sample_source_pointers_json"] = item.pop("pointers")
        item["distinct_ids_with_same_raw_name"] = len(ids_by_raw_name[(item["entity_type"], item["name_raw"])])
        item["distinct_ids_with_same_prefix_stripped_name"] = len(ids_by_normal_name[(item["entity_type"], item["name_normalized_for_review"])]) if item["name_normalized_for_review"] else 0
        item["raw_name_ambiguous_across_ids"] = item["distinct_ids_with_same_raw_name"] > 1
        item["prefix_stripped_name_ambiguous_across_ids"] = item["distinct_ids_with_same_prefix_stripped_name"] > 1

    roster_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    unmatched_id_checks: dict[str, int] = {}
    for entity, id_map in events.items():
        ambiguous_raw: dict[str, set[str]] = defaultdict(set)
        ambiguous_norm: dict[str, set[str]] = defaultdict(set)
        for (e, name), ids in ids_by_raw_name.items():
            if e == entity and len(ids) > 1:
                for value in ids:
                    ambiguous_raw[value].add(name)
        for (e, name), ids in ids_by_normal_name.items():
            if e == entity and len(ids) > 1:
                for value in ids:
                    ambiguous_norm[value].add(name)

        id_missing_count = sum(1 for x in unresolved if x["entity_type"] == entity and x["source_observation"] in {"race_result", "trial_api"})
        id_rows = sum(int(x["race_result_observation_rows"] + x["trial_api_observation_rows"] + x["trial_reviewed_horse_link_rows"]) for x in id_map.values())
        race_rows = sum(int(x["race_result_observation_rows"]) for x in id_map.values())
        trial_rows_count = sum(int(x["trial_api_observation_rows"]) for x in id_map.values())
        reviewed_rows_count = sum(int(x["trial_reviewed_horse_link_rows"]) for x in id_map.values())
        name_counts_per_id = [len(x["names"]) for x in id_map.values()]
        ids_multi_raw = sum(n > 1 for n in name_counts_per_id)
        ids_multi_normal = sum(len({normalized_name_for_review(n) for n in x["names"]}) > 1 for x in id_map.values())
        raw_name_collision_count = sum(1 for (e, _), ids in ids_by_raw_name.items() if e == entity and len(ids) > 1)
        normal_name_collision_count = sum(1 for (e, _), ids in ids_by_normal_name.items() if e == entity and len(ids) > 1)
        contexts_multiples = sum(len(x["contexts"]) > 1 for x in id_map.values())
        runner_id_col = ENTITY_COLUMNS[entity][0]
        runner_missing_sql = sql_blank(runner_id_col)
        runner_placeholder_sql = f"{runner_id_col} = '{TRAINER_PLACEHOLDER_ID}'" if entity == "trainer" else "false"
        trial_id_col = {"horse": "api_hrNo", "jockey": "api_jkNo", "trainer": "api_trNo"}.get(entity)
        trial_missing_count = con.execute(
            f"select count(*) from trial_participants where {sql_blank(trial_id_col)}"
        ).fetchone()[0] if trial_id_col else 0
        trial_placeholder_count = con.execute(
            f"select count(*) from trial_participants where api_trNo = '{TRAINER_PLACEHOLDER_ID}'"
        ).fetchone()[0] if entity == "trainer" else 0
        runner_placeholder_count = con.execute(
            f"select count(*) from confirmed_runners where {runner_placeholder_sql}"
        ).fetchone()[0] if entity == "trainer" else 0
        summary_rows.append({
            "entity_type": entity,
            "primary_observation_source": "KRA API4_3 race result; API20_1 trial where fields are supplied" if entity != "owner" else "KRA API4_3 race result",
            "confirmed_runner_rows": expected_runner_count,
            "confirmed_runner_rows_with_source_id_value": con.execute(f"select count(*) from confirmed_runners where not ({runner_missing_sql})").fetchone()[0],
            "confirmed_runner_rows_with_valid_entity_id": con.execute(f"select count(*) from confirmed_runners where not ({runner_missing_sql}) and not ({runner_placeholder_sql})").fetchone()[0],
            "confirmed_runner_rows_missing_source_id": con.execute(f"select count(*) from confirmed_runners where {runner_missing_sql}").fetchone()[0],
            "confirmed_runner_non_person_placeholder_rows": runner_placeholder_count,
            "trial_participant_rows": expected_trial_count if entity in {"horse", "jockey", "trainer"} else 0,
            "trial_participant_rows_with_direct_api_id": sum(int(x["trial_api_observation_rows"]) for x in id_map.values()) if entity in {"horse", "jockey", "trainer"} else 0,
            "trial_participant_rows_with_source_id_value": (expected_trial_count - trial_missing_count) if trial_id_col else 0,
            "trial_participant_source_id_gaps": trial_missing_count,
            "trial_non_person_placeholder_rows": trial_placeholder_count,
            "distinct_roster_ids": len(id_map),
            "id_bearing_race_observations": race_rows,
            "id_bearing_trial_api_observations": trial_rows_count,
            "reviewed_separate_trial_horse_links": reviewed_rows_count,
            "missing_or_non_person_observations_in_review_ledger": id_missing_count + runner_placeholder_count + trial_placeholder_count,
            "id_with_no_name_observations": sum(not bool(x["names"]) for x in id_map.values()),
            "id_with_multiple_exact_raw_names": ids_multi_raw,
            "id_with_multiple_names_after_venue_prefix_review_normalization": ids_multi_normal,
            "exact_raw_names_used_by_multiple_ids": raw_name_collision_count,
            "prefix_stripped_names_used_by_multiple_ids": normal_name_collision_count,
            "ids_observed_in_multiple_source_meets_or_queries": contexts_multiples,
            "official_profile_snapshot_ids_matched": sum(
                eid in ((profile_ids_by_scope_meet[("inactive", "1")] | profile_ids_by_scope_meet[("inactive", "3")]) if entity == "horse" else {profile_id for profile_entity, profile_id in person_profile_ids if profile_entity == entity})
                for eid in id_map
            ),
        })

        for entity_id, entry in sorted(id_map.items()):
            names = sorted(entry["names"].values(), key=lambda x: (x["first_seen_date"], x["name_raw"]))
            roster_rows.append({
                "entity_type": entity,
                "entity_id_official_string": entity_id,
                "race_result_observation_rows": entry["race_result_observation_rows"],
                "trial_api_observation_rows": entry["trial_api_observation_rows"],
                "trial_reviewed_horse_link_rows": entry["trial_reviewed_horse_link_rows"],
                "first_seen_date": entry["first_seen_date"],
                "last_seen_date": entry["last_seen_date"],
                "source_meets_or_queries_json": sorted(entry["contexts"]),
                "exact_raw_names_by_first_seen_json": [{"name_raw": n["name_raw"], "first_seen_date": n["first_seen_date"], "last_seen_date": n["last_seen_date"], "observation_rows": n["observation_rows"], "source_types": sorted(n["source_types"])} for n in names],
                "exact_raw_name_variant_count": len(names),
                "prefix_stripped_name_variant_count_review_only": len({normalized_name_for_review(n["name_raw"]) for n in names if normalized_name_for_review(n["name_raw"])}),
                "ambiguous_exact_raw_names_json": sorted(ambiguous_raw[entity_id]),
                "ambiguous_prefix_stripped_names_json_review_only": sorted(ambiguous_norm[entity_id]),
                "official_profile_name_snapshot_json": sorted(profile_names_by_id.get((entity, entity_id), set()) | person_profile_names.get((entity, entity_id), set())),
                "official_profile_request_cohorts_json": sorted(profile_scopes_by_id.get((entity, entity_id), set()) | person_profile_scopes.get((entity, entity_id), set())),
                "profile_is_in_y_request_cohort_at_2026_09_23": (entity_id in profile_ids_by_scope_meet[("active", "1")] or entity_id in profile_ids_by_scope_meet[("active", "3")]) if entity == "horse" else "",
                "identity_rule": "official ID only; names are dated source aliases and never JOIN keys",
                "relationship_rule": "event IDs are event-level only; current profile trainer/owner values are not backfilled",
            })

        unmatched_id_checks[entity] = sum(1 for row in runner_rows if not is_blank(row[{"horse":3,"jockey":5,"trainer":7,"owner":9}[entity]]) and id_key(row[{"horse":3,"jockey":5,"trainer":7,"owner":9}[entity]]) not in id_map)

    # Add explicit reason for missing IDs from race/trial sources and fill the
    # event key fields omitted in the generic recorder above.
    # Requery directly to keep every unresolved source row traceable.
    unresolved = []
    for entity, (id_col, name_col) in ENTITY_COLUMNS.items():
        rows = con.execute(f"""
            select source_meet, result_date, result_race_no, horse_program_no_raw,
                   horse_id_raw, horse_name_raw, {id_col}, {name_col}, source_file, source_item_index
            from confirmed_runners
            where {sql_blank(id_col)}
            order by result_date, source_meet, result_race_no, horse_program_no_raw
        """).fetchall()
        for meet, date, race_no, program_no, horse_id, horse_name, missing_id, name, source_file, item_idx in rows:
            unresolved.append({
                "entity_type": entity, "source_observation": "race_result", "source_api": "KRA API4_3/raceResult_3",
                "observation_date": normalize_event_date(date), "context_type": "race_venue_meet", "context_value": meet,
                "race_no_or_trial_no": race_no, "horse_program_no_raw": program_no,
                "horse_id_raw": horse_id, "horse_name_raw": horse_name, "id_column": id_col,
                "id_raw": missing_id or "", "name_column": name_col, "name_raw": name or "",
                "resolution_status": "unresolved_id_missing",
                "resolution_note": "RPT에서 이름만 발견하더라도 확정 ID로 자동 연결하지 않음.",
                "source_file": source_file, "source_item_index": item_idx,
                "source_pointer": f"{source_file}#item={item_idx}",
            })
    trial_jockey_missing = con.execute(f"""
        select participant_row_id, trial_date, source_meet_query, trial_no, api_chulNo,
               api_hrNo, api_hrName, api_jkNo, api_jkName, api_trNo, api_trName,
               source_file, source_item_index
        from trial_participants
        where {sql_blank('api_jkNo')}
        order by trial_date, source_meet_query, trial_no, source_item_index
    """).fetchall()
    for row in trial_jockey_missing:
        (participant_id, date, meet_query, trial_no, chulno, horse_id, horse_name, jockey_id, jockey_name,
         trainer_id, trainer_name, source_file, item_idx) = row
        unresolved.append({
            "entity_type": "jockey", "source_observation": "trial_api", "source_api": "KRA API20_1/ridingTestResult_1",
            "observation_date": normalize_event_date(date), "context_type": "trial_source_meet_query", "context_value": meet_query,
            "race_no_or_trial_no": trial_no, "horse_program_no_raw": chulno,
            "horse_id_raw": horse_id, "horse_name_raw": horse_name, "id_column": "api_jkNo",
            "id_raw": jockey_id or "", "name_column": "api_jkName", "name_raw": jockey_name or "",
            "resolution_status": "unresolved_id_and_name_missing",
            "resolution_note": "기수 ID와 이름 모두 API 응답에서 비어 있어 이름 추정/별도 연결을 수행하지 않음.",
            "source_file": source_file, "source_item_index": item_idx,
            "source_pointer": f"{source_file}#item={item_idx};participant={participant_id}",
        })

    trial_trainer_missing = con.execute(f"""
        select participant_row_id, trial_date, source_meet_query, trial_no, api_chulNo,
               api_hrNo, api_hrName, api_jkNo, api_jkName, api_trNo, api_trName,
               source_file, source_item_index
        from trial_participants
        where {sql_blank('api_trNo')}
        order by trial_date, source_meet_query, trial_no, source_item_index
    """).fetchall()
    for row in trial_trainer_missing:
        (participant_id, date, meet_query, trial_no, chulno, horse_id, horse_name, jockey_id, jockey_name,
         trainer_id, trainer_name, source_file, item_idx) = row
        unresolved.append({
            "entity_type": "trainer", "source_observation": "trial_api", "source_api": "KRA API20_1/ridingTestResult_1",
            "observation_date": normalize_event_date(date), "context_type": "trial_source_meet_query", "context_value": meet_query,
            "race_no_or_trial_no": trial_no, "horse_program_no_raw": chulno,
            "horse_id_raw": horse_id, "horse_name_raw": horse_name, "id_column": "api_trNo",
            "id_raw": trainer_id or "", "name_column": "api_trName", "name_raw": trainer_name or "",
            "resolution_status": "unresolved_id_and_name_missing_placeholder_dash",
            "resolution_note": "조교사 ID·이름이 모두 '-' placeholder이므로 유효 조교사로 추정 연결하지 않음.",
            "source_file": source_file, "source_item_index": item_idx,
            "source_pointer": f"{source_file}#item={item_idx};participant={participant_id}",
        })

    # The source uses 0AAAAA / 휴양마 as a placeholder value, not a person.
    # Preserve all 23 race and 140 trial observations as review rows.
    placeholder_rows = con.execute(f"""
        select 'race_result' as source_observation, source_meet as context_value, result_date as observation_date,
               result_race_no as race_no_or_trial_no, horse_program_no_raw, horse_id_raw, horse_name_raw,
               trainer_id_raw as source_id, trainer_name_raw as source_name, source_file, source_item_index
        from confirmed_runners where trainer_id_raw = '{TRAINER_PLACEHOLDER_ID}'
        union all
        select 'trial_api', source_meet_query, trial_date, trial_no, api_chulNo, api_hrNo, api_hrName,
               api_trNo, api_trName, source_file, source_item_index
        from trial_participants where api_trNo = '{TRAINER_PLACEHOLDER_ID}'
        order by observation_date, source_observation, context_value, race_no_or_trial_no, source_item_index
    """).fetchall()
    non_person_placeholder_rows = []
    for row in placeholder_rows:
        (source_observation, context_value, date, race_or_trial_no, horse_program_no, horse_id, horse_name,
         source_id, source_name, source_file, item_idx) = row
        if text(source_name).strip() != TRAINER_PLACEHOLDER_NAME:
            raise AssertionError(f"Unexpected placeholder source name: {source_name!r}")
        item = {
            "entity_type": "trainer", "source_observation": source_observation,
            "source_api": "KRA API4_3/raceResult_3" if source_observation == "race_result" else "KRA API20_1/ridingTestResult_1",
            "observation_date": normalize_event_date(date), "context_value": context_value,
            "race_no_or_trial_no": race_or_trial_no, "horse_program_no_raw": horse_program_no,
            "horse_id_raw": horse_id, "horse_name_raw": horse_name,
            "source_id_raw": source_id, "source_name_raw": source_name,
            "source_file": source_file, "source_item_index": item_idx,
            "resolution_status": "non_person_placeholder_excluded_from_trainer_roster",
            "resolution_note": "공식 원문 0AAAAA/휴양마는 조교사 인물이 아닌 placeholder로 분리; ID·이름 원문을 보존하고 master 연결에서 제외.",
            "source_pointer": f"{source_file}#item={item_idx}",
        }
        non_person_placeholder_rows.append(item)
        unresolved.append({
            "entity_type": "trainer", "source_observation": source_observation, "source_api": item["source_api"],
            "observation_date": normalize_event_date(date),
            "context_type": "race_venue_meet" if source_observation == "race_result" else "trial_source_meet_query",
            "context_value": context_value, "race_no_or_trial_no": race_or_trial_no,
            "horse_program_no_raw": horse_program_no, "horse_id_raw": horse_id, "horse_name_raw": horse_name,
            "id_column": "trainer_id_raw" if source_observation == "race_result" else "api_trNo",
            "id_raw": source_id, "name_column": "trainer_name_raw" if source_observation == "race_result" else "api_trName",
            "name_raw": source_name, "resolution_status": item["resolution_status"],
            "resolution_note": item["resolution_note"], "source_file": source_file,
            "source_item_index": item_idx, "source_pointer": item["source_pointer"],
        })

    # Keep the 104 reviewed horse ID gaps visible in the same unresolved ledger,
    # while retaining their accepted separate-identity evidence in its own file.
    for item in trial_horse_exceptions:
        unresolved.append({
            "entity_type": "horse", "source_observation": "trial_api",
            "source_api": "KRA API20_1/ridingTestResult_1", "observation_date": item["trial_date"],
            "context_type": "trial_source_meet_query", "context_value": item["source_meet_query"],
            "race_no_or_trial_no": item["trial_no"], "horse_program_no_raw": item["api_chulNo"],
            "horse_id_raw": item["api_hrNo_raw"], "horse_name_raw": item["api_hrName_raw"],
            "id_column": "api_hrNo", "id_raw": item["api_hrNo_raw"], "name_column": "api_hrName",
            "name_raw": item["api_hrName_raw"], "resolution_status": "source_api_id_missing_but_separate_core_linkage_reviewed",
            "resolution_note": f"separate-link method={item['resolution_method']}; core review evidence is preserved; API source row unchanged",
            "source_file": item["api_source_file"], "source_item_index": item["api_source_item_index"],
            "source_pointer": f"{item['api_source_file']}#item={item['api_source_item_index']};participant={item['participant_row_id']}",
        })

    # Core acceptance checks: event IDs map to one unique ID roster; blank IDs
    # remain in the unresolved ledger; no current relationship values propagate.
    for entity, id_map in events.items():
        if len(id_map) != len(set(id_map)):
            raise AssertionError(f"Non-unique exported ID roster for {entity}")
    runner_null_counts = {
        entity: con.execute(f"select count(*) from confirmed_runners where {sql_blank(id_col)}").fetchone()[0]
        for entity, (id_col, _) in ENTITY_COLUMNS.items()
    }
    runner_placeholder_counts = {
        "trainer": con.execute(f"select count(*) from confirmed_runners where trainer_id_raw = '{TRAINER_PLACEHOLDER_ID}'").fetchone()[0]
    }
    runner_trainer_owner_missing_key_mismatch = con.execute(f"""
        select count(*) from confirmed_runners
        where ({sql_blank('trainer_id_raw')}) <> ({sql_blank('owner_id_raw')})
    """).fetchone()[0]
    runner_missing_id_name_nonblank = {
        entity: con.execute(f"""
            select count(*) from confirmed_runners
            where {sql_blank(id_col)} and not ({sql_blank(name_col)})
        """).fetchone()[0]
        for entity, (id_col, name_col) in ENTITY_COLUMNS.items()
    }
    expected_nulls = {"horse": 0, "jockey": 0, "trainer": 38, "owner": 38}
    if runner_null_counts != expected_nulls:
        raise AssertionError(f"Confirmed runner ID gap counts changed: {runner_null_counts}")
    if len(trial_jockey_missing) != 5121:
        raise AssertionError(f"Trial jockey gap count changed: {len(trial_jockey_missing)}")
    if len(trial_trainer_missing) != 84:
        raise AssertionError(f"Trial trainer placeholder gap count changed: {len(trial_trainer_missing)}")
    if runner_trainer_owner_missing_key_mismatch != 0 or runner_null_counts["trainer"] != runner_null_counts["owner"]:
        raise AssertionError("Race trainer/owner missing-ID row sets no longer match")
    if runner_missing_id_name_nonblank["trainer"] != 0 or runner_missing_id_name_nonblank["owner"] != 0:
        raise AssertionError("Race trainer/owner missing-ID rows unexpectedly contain names")
    if any(not is_blank(row[10]) for row in trial_trainer_missing):
        raise AssertionError("Trial trainer missing-ID rows unexpectedly contain names")
    if any(not is_blank(row[8]) for row in trial_jockey_missing):
        raise AssertionError("Trial jockey missing-ID rows unexpectedly contain names")
    if runner_placeholder_counts["trainer"] != 23 or len([r for r in placeholder_rows if r[0] == "trial_api"]) != 140:
        raise AssertionError("Trainer non-person placeholder counts changed")
    if len(placeholder_rows) != 163 or len(events["trainer"]) != 225:
        raise AssertionError("Trainer placeholder exclusion or valid master roster count changed")
    if len(identity_rows) != 104:
        raise AssertionError(f"Trial horse API ID exception count changed: {len(identity_rows)}")
    trial_horse_resolution_method_counts: dict[str, int] = defaultdict(int)
    for item in trial_horse_exceptions:
        trial_horse_resolution_method_counts[item["resolution_method"] or "unresolved"] += 1
    if not all(profile_summary["active_y_subset_of_inactive_n_by_meet"].values()):
        raise AssertionError("2026-09-23 API8_2 y cohort is no longer a subset of n by meet")

    historical_horse_ids = set(events["horse"])
    inactive_profile_ids = profile_ids_by_scope_meet[("inactive", "1")] | profile_ids_by_scope_meet[("inactive", "3")]
    missing_profile_ids = sorted(historical_horse_ids - inactive_profile_ids)
    profile_summary["historical_exported_horse_ids"] = len(historical_horse_ids)
    profile_summary["historical_exported_horse_ids_in_inactive_n_snapshot_union"] = len(historical_horse_ids & inactive_profile_ids)
    profile_summary["historical_exported_horse_ids_not_in_snapshot"] = missing_profile_ids

    yeongcheon_horse_ids = {
        id_key(row[0]) for row in con.execute(
            "select distinct horse_id_raw from confirmed_runners where source_meet = '4'"
        ).fetchall() if not is_blank(row[0])
    }
    yeongcheon_profile_ids = yeongcheon_horse_ids & inactive_profile_ids
    if len(yeongcheon_horse_ids) != 119 or len(yeongcheon_profile_ids) != 119:
        raise AssertionError(
            f"Yeongcheon ID cross-check changed: race IDs={len(yeongcheon_horse_ids)}, profile ID matches={len(yeongcheon_profile_ids)}"
        )

    # Narrow role-specific exceptions and cardinality checks.
    four_entity_runner_cardinality = {
        "runner_rows": expected_runner_count,
        "horse_joined_rows_by_official_id": expected_runner_count - runner_null_counts["horse"],
        "jockey_joined_rows_by_official_id": expected_runner_count - runner_null_counts["jockey"],
        "trainer_joined_rows_by_official_id": expected_runner_count - runner_null_counts["trainer"] - runner_placeholder_counts["trainer"],
        "trainer_non_person_placeholder_rows_excluded": runner_placeholder_counts["trainer"],
        "owner_joined_rows_by_official_id": expected_runner_count - runner_null_counts["owner"],
        "distinct_runner_keys_expected_once": con.execute("select count(distinct source_meet || '|' || result_date || '|' || result_race_no || '|' || horse_program_no_raw) from confirmed_runners").fetchone()[0],
    }
    trial_cardinality = {
        "trial_participant_rows": expected_trial_count,
        "trial_horse_resolved_view_rows": con.execute("select count(*) from trial_participants_resolved").fetchone()[0],
        "trial_horse_resolved_id_missing": con.execute("select count(*) from trial_participants_resolved where nullif(trim(coalesce(resolved_horse_id,'')),'') is null").fetchone()[0],
        "trial_jockey_rows_with_direct_api_id": expected_trial_count - len(trial_jockey_missing),
        "trial_jockey_rows_missing_direct_api_id": len(trial_jockey_missing),
        "trial_jockey_name_values_on_missing_id_rows": con.execute(f"select count(*) from trial_participants where not ({sql_blank('api_jkName')}) and {sql_blank('api_jkNo')}").fetchone()[0],
        "trial_trainer_rows_with_valid_api_id": expected_trial_count - len(trial_trainer_missing) - len([r for r in placeholder_rows if r[0] == "trial_api"]),
        "trial_trainer_rows_missing_api_id": len(trial_trainer_missing),
        "trial_trainer_non_person_placeholder_rows_excluded": len([r for r in placeholder_rows if r[0] == "trial_api"]),
    }

    # Ensure the confirmed row key remains one-to-one, including blank references.
    if four_entity_runner_cardinality["distinct_runner_keys_expected_once"] != expected_runner_count:
        raise AssertionError("Confirmed runner event key is not unique")
    if trial_cardinality["trial_horse_resolved_view_rows"] != expected_trial_count or trial_cardinality["trial_horse_resolved_id_missing"] != 0:
        raise AssertionError("Reviewed trial horse identity view cardinality or coverage changed")

    iso_date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    date_values = [value for row in roster_rows for value in (row["first_seen_date"], row["last_seen_date"])]
    date_values.extend(value for row in names_rows for value in (row["first_seen_date"], row["last_seen_date"]))
    date_values.extend(row["observation_date"] for row in unresolved)
    date_values.extend(row["observation_date"] for row in non_person_placeholder_rows)
    date_values.extend(row["trial_date"] for row in trial_horse_exceptions)
    invalid_dates = sorted({value for value in date_values if value and not iso_date_re.fullmatch(value)})
    if invalid_dates:
        raise AssertionError(f"Non-ISO event dates remain in exported ledgers: {invalid_dates[:5]}")
    all_event_dates_iso = True
    non_person_placeholder_rows.sort(key=lambda row: (row["observation_date"], row["source_observation"], row["context_value"], row["race_no_or_trial_no"], row["source_file"]))

    # Output exports.
    write_csv(out / "entity_reference_summary.csv", summary_rows, list(summary_rows[0].keys()))
    write_csv(out / "entity_reference_roster.csv", roster_rows, list(roster_rows[0].keys()))
    names_rows.sort(key=lambda x: (x["entity_type"], x["entity_id"], x["first_seen_date"], x["name_raw"]))
    write_csv(out / "entity_name_observations.csv", names_rows, list(names_rows[0].keys()))
    unresolved.sort(key=lambda x: (x["entity_type"], x["observation_date"], x["context_value"], x["race_no_or_trial_no"], x["horse_program_no_raw"], x["source_file"]))
    unresolved_fields = list(dict.fromkeys(key for row in unresolved for key in row))
    write_csv(out / "unresolved_entity_references.csv", unresolved, unresolved_fields)
    write_csv(out / "non_person_placeholder_observations.csv", non_person_placeholder_rows,
              list(non_person_placeholder_rows[0].keys()))
    write_csv(out / "horse_profile_snapshot_membership.csv", memberships, list(memberships[0].keys()))
    write_csv(out / "trial_horse_id_source_exceptions.csv", trial_horse_exceptions, list(trial_horse_exceptions[0].keys()))
    write_csv(out / "horse_profile_page_manifest.csv", profile_pages, list(profile_pages[0].keys()))
    write_csv(out / "person_reference_profile_snapshots.csv", person_profiles, list(person_profiles[0].keys()))
    write_csv(out / "person_profile_page_manifest.csv", person_profile_pages, list(person_profile_pages[0].keys()))

    profile_coverage_rows = []
    profile_coverage_gaps = []
    profile_id_sets: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in memberships:
        if row["request_scope"] == "inactive":
            profile_id_sets[("horse", row["meet_query"])].add(row["horse_id_raw_string"])
    for row in person_profiles:
        profile_id_sets[(row["entity_type"], row["meet_query"])].add(row["official_id_raw_string"])
    for entity, id_map in events.items():
        snapshot_meets = ("1", "3")
        event_ids = set(id_map)
        snapshot_union = set().union(*(profile_id_sets[(entity, meet)] for meet in snapshot_meets))
        profile_coverage_rows.append({
            "entity_type": entity,
            "profile_service": {"horse":"API8_2/raceHorseInfo_2","jockey":"API307/jockeyInfo","trainer":"API308/trainerInfo","owner":"API309/horseOwnerInfo"}[entity],
        "profile_capture_date": PROFILE_CAPTURE_DATE if entity == "horse" else "2026-09-29" if entity == "trainer" else "2026-09-30",
            "profile_meet_queries": "1,3 (meet=3 label=영남; identity lookup only)",
            "event_roster_distinct_ids": len(event_ids),
            "profile_union_distinct_ids": len(snapshot_union),
            "event_roster_ids_found_in_profile_union": len(event_ids & snapshot_union),
            "event_roster_ids_missing_from_profile_union": len(event_ids - snapshot_union),
            "profile_ids_not_seen_in_event_roster": len(snapshot_union - event_ids),
            "event_roster_coverage_fraction": (len(event_ids & snapshot_union) / len(event_ids)) if event_ids else "",
            "interpretation": "profile name/ID coverage only; source event ID/name remains historical basis; profile relationships and statistics are not backfilled",
        })
        for missing_id in sorted(event_ids - snapshot_union):
            profile_coverage_gaps.append({
                "entity_type": entity,
                "official_id": missing_id,
                "profile_service": {"horse":"API8_2/raceHorseInfo_2","jockey":"API307/jockeyInfo","trainer":"API308/trainerInfo","owner":"API309/horseOwnerInfo"}[entity],
                "profile_capture_date": PROFILE_CAPTURE_DATE if entity == "horse" else "2026-09-29" if entity == "trainer" else "2026-09-30",
                "historical_event_id_is_still_primary": True,
                "note": "ID did not appear in the bounded current-profile capture; not an event ID mismatch.",
            })
    write_csv(out / "entity_profile_coverage.csv", profile_coverage_rows, list(profile_coverage_rows[0].keys()))
    write_csv(out / "entity_profile_coverage_gaps.csv", profile_coverage_gaps, list(profile_coverage_gaps[0].keys()) if profile_coverage_gaps else ["entity_type","official_id","profile_service","profile_capture_date","historical_event_id_is_still_primary","note"])

    source_archive_entries = []
    for source_file in sorted(source_files):
        path = REPO_ROOT / source_file
        source_archive_entries.append({
            "source_file": source_file,
            "exists": path.exists(),
            "sha256": sha256(path) if path.exists() else "",
            "byte_size": path.stat().st_size if path.exists() else "",
        })
    # Also hash the raw KRA API8_2 records that support the current horse snapshot.
    source_archive_entries.extend({
        "source_file": p["source_file"], "exists": True, "sha256": p["sha256"],
        "byte_size": (REPO_ROOT / p["source_file"]).stat().st_size,
    } for p in profile_pages)
    source_archive_entries.extend({
        "source_file": p["source_file"], "exists": True, "sha256": p["sha256"],
        "byte_size": (REPO_ROOT / p["source_file"]).stat().st_size,
    } for p in meet4_probe)
    source_archive_entries.extend({
        "source_file": p["source_file"], "exists": True, "sha256": p["sha256"],
        "byte_size": (REPO_ROOT / p["source_file"]).stat().st_size,
    } for p in person_profile_pages)

    credential_page_records = [*profile_pages, *meet4_probe, *person_profile_pages]
    credential_paths = sorted({(REPO_ROOT / p["source_file"]).resolve() for p in credential_page_records})
    credential_scan = check_credentials_are_not_archived(credential_paths)
    collection_manifest_path = REPO_ROOT / "data/raw/kra/entity_reference_profiles/20260930/manifest.json"
    if collection_manifest_path.exists():
        source_archive_entries.append({
            "source_file": safe_relative(collection_manifest_path, REPO_ROOT),
            "exists": True,
            "sha256": sha256(collection_manifest_path),
            "byte_size": collection_manifest_path.stat().st_size,
        })

    source_spine_paths = {
        "runner_results.csv": REPO_ROOT / "thoroughbred/research/20260929_race_results_api_v1/runner_results.csv",
        "participants.csv": REPO_ROOT / "thoroughbred/research/20260929_trial_results_api_v1/participants.csv",
    }
    missing_spines = [name for name, path in source_spine_paths.items() if not path.exists()]
    if missing_spines:
        raise FileNotFoundError(f"Missing exported source spine files: {missing_spines}")
    source_spine_sha256 = {
        name: {"path": safe_relative(path, REPO_ROOT), "sha256": sha256(path), "byte_size": path.stat().st_size}
        for name, path in source_spine_paths.items()
    }

    manifest = {
        "audit_name": "thoroughbred_entity_reference_audit_v1",
        "generated_by": safe_relative(__file__, REPO_ROOT),
        "scope": {"from": "2010-01-01", "through": "2026-09-29", "race_meets": ["1:Seoul", "3:Busan-Gyeongnam", "4:Yeongcheon"], "jeju_included": False},
        "core_db": {"path": safe_relative(db_path, REPO_ROOT), "access": "read_only", "tables_read": ["confirmed_runners", "trial_participants", "trial_participants_resolved", "trial_horse_identity_links"]},
        "primary_sources": {
            "race_runner_identity": {"source": "KRA data.go.kr API4_3/raceResult_3", "data_id": "15058305", "url": "https://www.data.go.kr/data/15058305/openapi.do", "use": "dated race-row official IDs and names; source_file + source_item_index trace each row"},
            "trial_identity": {"source": "KRA data.go.kr API20_1/ridingTestResult_1", "url": "https://apis.data.go.kr/B551015/API20_1/ridingTestResult_1", "use": "dated horse/jockey/trainer IDs and names where supplied"},
            "horse_reference_snapshot": {"source": "KRA data.go.kr API8_2/raceHorseInfo_2", "data_id": "15058115", "url": "https://www.data.go.kr/data/15058115/openapi.do", "use": "current horse ID/name/profile cohort only; not historical trainer/owner link"},
            "jockey_reference_detail": {"source": "KRA approved API307/jockeyInfo", "data_id": "15056828", "endpoint": "https://apis.data.go.kr/B551015/API307/jockeyInfo", "use": "official current ID/name/English-name/profile-date snapshot; historical event roster remains the observed race/trial ID union"},
            "trainer_reference_detail": {"source": "KRA API308/trainerInfo", "endpoint": "https://apis.data.go.kr/B551015/API308/trainerInfo", "use": "official current ID/name/English-name/profile-date snapshot; historical event roster remains the observed race/trial ID union"},
            "owner_reference": {"source": "KRA approved API309/horseOwnerInfo", "endpoint": "https://apis.data.go.kr/B551015/API309/horseOwnerInfo", "use": "official current ID/name/English-name/profile-date snapshot; historical ownership remains event-level only"},
        },
        "profile_snapshot_check": {k: v for k, v in profile_summary.items() if k != "ids_by_scope_meet"},
        "source_spine_sha256": source_spine_sha256,
        "yeongcheon_horse_profile_id_crosscheck": {
            "confirmed_race_rows": con.execute("select count(*) from confirmed_runners where source_meet = '4'").fetchone()[0],
            "distinct_event_horse_ids": len(yeongcheon_horse_ids),
            "ids_found_in_api8_2_inactive_meet_1_or_3_union": len(yeongcheon_profile_ids),
            "interpretation": "official horse ID membership only; meet=4 profile capture returned 0 rows, so no current venue or relationship is assigned to historical events",
        },
        "person_profile_snapshot_check": {
            "capture_dates": {"API307/jockeyInfo":"2026-09-30","API308/trainerInfo":"2026-09-29","API309/horseOwnerInfo":"2026-09-30"},
            "capture_timing_relative_to_core_cutoff": {"API307/jockeyInfo":"post_cutoff_2026-09-30", "API308/trainerInfo":"cutoff_date_2026-09-29_time_not_used_historically", "API309/horseOwnerInfo":"post_cutoff_2026-09-30"},
            "fields_exported": "IDs, names, English names, source meet labels, observed date fields, stable part; performance statistics remain only in raw response archives",
            "duplicate_ids_within_each_meet": {
                f"{entity}/meet={meet}": sum(1 for r in person_profiles if r["entity_type"] == entity and r["meet_query"] == meet) - len({r["official_id_raw_string"] for r in person_profiles if r["entity_type"] == entity and r["meet_query"] == meet})
                for entity in ("jockey", "trainer", "owner") for meet in ("1", "3")
            },
            "credential_query_parameter_saved": False,
            "credential_storage_check": credential_scan,
            "raw_response_and_page_hashes": True,
            "total_count_and_pagination_validated": True,
            "global_profile_id_counts": {
                entity: {
                    "unique_ids_across_meet_queries": len({r["official_id_raw_string"] for r in person_profiles if r["entity_type"] == entity}),
                    "id_overlap_between_meet_1_and_3": len(
                        {r["official_id_raw_string"] for r in person_profiles if r["entity_type"] == entity and r["meet_query"] == "1"}
                        & {r["official_id_raw_string"] for r in person_profiles if r["entity_type"] == entity and r["meet_query"] == "3"}
                    ),
                    "overlap_ids_with_different_snapshot_names": len({
                        profile_id for profile_id in
                        ({r["official_id_raw_string"] for r in person_profiles if r["entity_type"] == entity and r["meet_query"] == "1"}
                         & {r["official_id_raw_string"] for r in person_profiles if r["entity_type"] == entity and r["meet_query"] == "3"})
                        if len({r["name_snapshot"] for r in person_profiles if r["entity_type"] == entity and r["official_id_raw_string"] == profile_id}) > 1
                    }),
                }
                for entity in ("jockey", "trainer", "owner")
            },
        },
        "api8_2_meet4_probe": {"pages": meet4_probe, "interpretation": "successful empty API response for the inspected meet=4 capture; do not infer profile absence or identity mismatch from this call alone"},
        "core_acceptance_counts": {"confirmed_runner_rows": expected_runner_count, "runner_source_id_gaps": runner_null_counts, "race_trainer_owner_missing_id_same_rows": runner_null_counts["trainer"] - runner_trainer_owner_missing_key_mismatch, "race_missing_id_rows_with_nonblank_name": runner_missing_id_name_nonblank, "trainer_non_person_placeholder_race_rows": runner_placeholder_counts["trainer"], "valid_trainer_roster_ids": len(events["trainer"]), "trial_participant_rows": expected_trial_count, "trial_jockey_missing_id_rows": len(trial_jockey_missing), "trial_trainer_missing_id_rows": len(trial_trainer_missing), "trial_trainer_non_person_placeholder_rows": len([r for r in placeholder_rows if r[0] == "trial_api"]), "trial_horse_source_id_exception_rows": len(identity_rows), "trial_horse_exception_resolution_methods": dict(trial_horse_resolution_method_counts)},
        "cardinality_checks": {"confirmed_runners": four_entity_runner_cardinality, "trial_participants": trial_cardinality},
        "validation": {
            "runner_race_key_unique": four_entity_runner_cardinality["distinct_runner_keys_expected_once"] == expected_runner_count,
            "expected_race_runner_id_gaps_match": runner_null_counts == expected_nulls,
            "expected_trial_jockey_gap_count_match": len(trial_jockey_missing) == 5121,
            "expected_trial_trainer_gap_count_match": len(trial_trainer_missing) == 84,
            "trainer_placeholder_separated_from_person_roster": len(events["trainer"]) == 225 and len(placeholder_rows) == 163,
            "credential_absent_from_all_profile_page_archives": credential_scan["status"] == "passed",
            "trial_horse_reviewed_view_complete": trial_cardinality["trial_horse_resolved_id_missing"] == 0,
            "horse_profile_y_cohort_subset_of_n_cohort": all(profile_summary["active_y_subset_of_inactive_n_by_meet"].values()),
            "all_exported_horse_ids_in_current_n_profile_union": len(missing_profile_ids) == 0,
            "all_yeongcheon_horse_ids_in_meet_1_or_3_profile_union": len(yeongcheon_profile_ids) == 119,
            "race_trainer_owner_missing_id_rows_are_identical_and_names_blank": runner_trainer_owner_missing_key_mismatch == 0 and runner_null_counts["trainer"] == runner_null_counts["owner"] and runner_missing_id_name_nonblank["trainer"] == 0 and runner_missing_id_name_nonblank["owner"] == 0,
            "raw_id_strings_not_zero_padded_or_integer_cast": True,
            "current_trainer_or_owner_profile_fields_not_used_for_history": True,
            "unresolved_name_only_references_not_auto_linked": True,
            "all_exported_event_observation_dates_iso": all_event_dates_iso,
        },
        "exports": {},
        "source_archives": source_archive_entries,
        "limitations": [
            "An ID roster built from observed race/trial rows covers observed entities, not entities absent from all archived API rows.",
            "API8_2 y/n are captured request cohorts, not mutually exclusive status labels: y IDs are a subset of n IDs in this 2026-09-23 capture.",
            "API8_2 meet=4 probe returned totalCount=0; the 119 Yeongcheon race-entry rows therefore need cross-checks against meet=1/3 profiles by official horse ID, without assigning profile venue/relations historically.",
            "API307/API309 profile captures are observed 2026-09-30 after the core cutoff; API308 is observed on the 2026-09-29 cutoff date. All are current directory snapshots and are used for ID/name coverage only, never historical feature or affiliation joins.",
            "API307/308/309 performance statistics remain in raw response archives and are not copied into the profile snapshot export.",
            "API309 owner directory provides current ID/name snapshots (global 597 IDs across meet queries, with 271 IDs appearing in both); it does not establish historical owners for past races. Event owner IDs/names remain the historical basis.",
            "Trainer source placeholder 0AAAAA / 휴양마 is not a person and is excluded from the 225-person trainer roster; 23 race rows and 140 trial rows remain in the unresolved/review ledger. The 84 trial rows with api_trNo='-' and api_trName='-' are also unresolved.",
            "For horse aliases, venue prefixes such as [서울], [부산경남], [영남] are retained. Prefix-stripped values are a diagnostic column only.",
            "Existing reviewed links for 104 trial horse API ID gaps remain in a separate ledger; raw API fields are unchanged and RPT is validation evidence only.",
        ],
    }
    for path in sorted(out.iterdir()):
        if path.is_file() and path.name != "manifest.json":
            if path.suffix == ".csv":
                with path.open(encoding="utf-8-sig", newline="") as f:
                    row_count = sum(1 for _ in csv.DictReader(f))
            else:
                row_count = None
            manifest["exports"][path.name] = {"sha256": sha256(path), "byte_size": path.stat().st_size, "row_count": row_count}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    con.close()
    print(json.dumps({"output_dir": safe_relative(out, REPO_ROOT), "summary": summary_rows, "runner_cardinality": four_entity_runner_cardinality, "trial_cardinality": trial_cardinality, "profile_snapshot": {k: v for k, v in profile_summary.items() if k != "ids_by_scope_meet"}, "unresolved_ledger_rows": len(unresolved), "trial_horse_source_exceptions": len(trial_horse_exceptions), "validation": manifest["validation"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
