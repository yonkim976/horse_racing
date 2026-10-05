"""Read-only, hash-verified review of locally saved API78 cards for 104 gaps.

Run from the repository root with ``.venv/bin/python``. The script never
contacts the network, writes to a database, or emits API URLs/request blobs.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
INPUT = ROOT / "thoroughbred/research/20261001_equipment_storage_audit_v1/matched_operational_api78_missing_2017plus.csv"
OPERATIONAL = ROOT / "data/horse_racing.sqlite3"
CORE = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
RAW_ROOT = (ROOT / "data/raw").resolve()
ENDPOINT = "/API78/chulmainfo"
KST = ZoneInfo("Asia/Seoul")
INTEGER = re.compile(r"(\d+)")


def clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def day8(value: object) -> str:
    text = clean(value)
    if len(text) == 8 and text.isdigit():
        return text
    digits = "".join(re.findall(r"\d", text))
    return digits[:8] if len(digits) >= 8 else ""


def iso_day(value: object) -> str:
    text = day8(value)
    if len(text) != 8 or not text.isdigit():
        raise ValueError("date is not YYYYMMDD")
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}"


def number(value: object) -> int | None:
    match = INTEGER.search(clean(value))
    return int(match.group(1)) if match else None


def name_key(value: object) -> str:
    text = unicodedata.normalize("NFKC", clean(value))
    text = text.removeprefix("★").strip()
    text = re.sub(r"^\[[^]]+\]\s*", "", text)
    text = text.removeprefix("★").strip()
    return "".join(text.split()).casefold()


def name_prefix(value: object) -> str:
    match = re.match(r"^\s*(\[[^]]+\])", clean(value))
    return match.group(1) if match else "(untagged)"


def kst(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc).astimezone(KST).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_raw_path(local_path: str) -> Path:
    path = Path(local_path)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve(strict=True)
    if not path.is_relative_to(RAW_ROOT):
        raise ValueError("source local_path resolves outside data/raw")
    if not path.is_file():
        raise ValueError("source local_path is not a regular file")
    return path


def read_only_sqlite(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    con.execute("BEGIN")
    return con


def normalize_items(payload: object) -> tuple[dict[str, object], list[dict[str, object]]]:
    if not isinstance(payload, dict):
        raise ValueError("response payload is not an object")
    response = payload.get("response")
    body = response.get("body") if isinstance(response, dict) else None
    if not isinstance(body, dict):
        raise ValueError("response body is missing")
    bucket = body.get("items", {})
    if isinstance(bucket, dict):
        bucket = bucket.get("item", [])
    if bucket in (None, ""):
        bucket = []
    if isinstance(bucket, dict):
        bucket = [bucket]
    if not isinstance(bucket, list) or any(not isinstance(item, dict) for item in bucket):
        raise ValueError("unexpected API78 item container")
    return body, bucket


def verify_batch(docs: list[sqlite3.Row], day: str, meet: int) -> dict[str, object]:
    pages: list[tuple[int, sqlite3.Row, dict[str, object], list[dict[str, object]]]] = []
    errors: list[str] = []
    evidence: list[dict[str, object]] = []
    for doc in docs:
        doc_id = int(doc["document_id"])
        try:
            raw_path = safe_raw_path(str(doc["local_path"]))
            actual_hash = sha256(raw_path)
            if actual_hash != str(doc["sha256"]):
                raise ValueError("SHA-256 does not match source_documents")
            if int(doc["http_status_code"] or 0) != 200:
                raise ValueError("saved page HTTP status is not 200")
            payload = json.loads(raw_path.read_bytes())
            body, items = normalize_items(payload)
            req_page = int(doc["request_page_no"] or 0)
            body_page = int(number(body.get("pageNo")) or 0)
            page_size = int(number(body.get("numOfRows")) or 0)
            total_count = int(number(body.get("totalCount")) or 0)
            if req_page < 1 or body_page != req_page:
                raise ValueError("requested and response page numbers disagree")
            if page_size < 1:
                raise ValueError("response page size is missing or invalid")
            if day8(doc["request_date"]) != day:
                raise ValueError("request date differs inside batch")
            if int(doc["request_meet"] or 0) != meet:
                raise ValueError("request meet differs inside batch")
            result = payload.get("response", {}).get("header", {})
            result_code = clean(result.get("resultCode")) if isinstance(result, dict) else ""
            if result_code and result_code not in {"00", "0000"}:
                raise ValueError("API response header reports an error")
            for item in items:
                item_day = day8(item.get("raceDt"))
                if item_day and item_day != day:
                    raise ValueError("runner date differs from requested date")
            pages.append((req_page, doc, body, items))
            evidence.append({
                "source_document_id": doc_id,
                "page": req_page,
                "sha256": str(doc["sha256"]),
                "local_path": str(raw_path.relative_to(ROOT)),
                "http_status_code": doc["http_status_code"],
                "response_bytes": int(doc["response_bytes"]),
            })
        except Exception as exc:  # preserve precise per-document failure in the audit artifact
            errors.append(f"document {doc_id}: {exc}")

    complete = not errors and bool(pages)
    all_items: list[dict[str, object]] = []
    reported_counts: set[int] = set()
    page_sizes: set[int] = set()
    request_pages: list[int] = []
    for page_no, _doc, body, items in pages:
        request_pages.append(page_no)
        reported_counts.add(int(number(body.get("totalCount")) or 0))
        page_sizes.add(int(number(body.get("numOfRows")) or 0))
        all_items.extend(items)
    if complete:
        if request_pages != list(range(1, len(pages) + 1)):
            errors.append("page sequence is not contiguous from 1")
        if len(reported_counts) != 1 or len(page_sizes) != 1:
            errors.append("page totalCount/page size changes within batch")
        elif reported_counts:
            total = next(iter(reported_counts))
            size = next(iter(page_sizes))
            expected_pages = max(1, (total + size - 1) // size)
            if len(pages) != expected_pages or len(all_items) != total:
                errors.append("saved pages do not cover API totalCount")
        key_list: list[tuple[int, int]] = []
        for item in all_items:
            race_no, horse_no = number(item.get("raceNo")), number(item.get("gtno"))
            if race_no is None or horse_no is None:
                errors.append("runner race/program number missing")
                break
            key_list.append((race_no, horse_no))
        if len(key_list) != len(set(key_list)):
            errors.append("duplicate race/program key in saved batch")
    complete = complete and not errors
    all_items_by_key: dict[tuple[int, int], dict[str, object]] = {}
    if complete:
        for item in all_items:
            key = (int(number(item.get("raceNo")) or 0), int(number(item.get("gtno")) or 0))
            all_items_by_key[key] = item
    done = max((int(doc["run_completed_at_ms"] or doc["retrieved_at_ms"]) for doc in docs), default=None)
    max_retrieved = max((int(doc["retrieved_at_ms"]) for doc in docs), default=None)
    return {
        "day": day,
        "meet": meet,
        "ingestion_run_id": int(docs[0]["ingestion_run_id"]) if docs else None,
        "completed_at_ms": done,
        "completed_at_kst": kst(done),
        "retrieved_at_ms": max_retrieved,
        "retrieved_at_kst": kst(max_retrieved),
        "status": clean(docs[0]["run_status"]) if docs else None,
        "data_type": clean(docs[0]["run_data_type"]) if docs else None,
        "complete": complete,
        "errors": errors,
        "pages": sorted(request_pages),
        "item_count": len(all_items) if complete else None,
        "source_documents": sorted(evidence, key=lambda row: row["page"]),
        "items_by_key": all_items_by_key,
        "all_items": all_items if complete else [],
    }


def card_state(batch: dict[str, object], row: dict[str, str]) -> dict[str, object]:
    item = batch["items_by_key"].get((int(row["race_no"]), int(row["horse_no"])))
    if item is None:
        expected_names = {name_key(row.get("horse_name_core")), name_key(row.get("horse_name_operational"))}
        candidates = []
        for candidate in batch["all_items"]:
            candidate_name = name_key(candidate.get("hrnm"))
            if candidate_name and candidate_name in expected_names:
                candidates.append({
                    "race_no": number(candidate.get("raceNo")),
                    "horse_no": number(candidate.get("gtno")),
                    "horse_name": clean(candidate.get("hrnm")),
                    "equipment_raw": None if candidate.get("equipCrs") is None else str(candidate.get("equipCrs")),
                })
        presence = "same_name_present_at_other_race_program" if candidates else "absent_at_race_program_key"
        return {"presence": presence, "name_match": None, "item": None,
                "same_name_other_key_candidates": candidates}
    card_name = clean(item.get("hrnm"))
    expected_name = clean(row["horse_name_core"])
    op_name = clean(row["horse_name_operational"])
    matches_core = bool(name_key(card_name)) and name_key(card_name) == name_key(expected_name)
    matches_op = bool(name_key(card_name)) and name_key(card_name) == name_key(op_name)
    if matches_core or matches_op:
        identity_state = "name_matches_core_or_operational"
    else:
        identity_state = "race_program_present_name_differs"
    raw_value = item.get("equipCrs")
    if raw_value is None:
        equipment_state = "field_null_or_missing"
        raw_text = None
    else:
        raw_text = str(raw_value)
        equipment_state = "explicit_blank" if not raw_text.strip() else "nonblank"
    return {
        "presence": identity_state,
        "name_match_core": matches_core,
        "name_match_operational": matches_op,
        "card_horse_name": card_name,
        "equipment_state": equipment_state,
        "equipment_raw": raw_text,
        "item": item,
        "same_name_other_key_candidates": [],
    }


def read_input() -> list[dict[str, str]]:
    with INPUT.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 104:
        raise ValueError(f"expected 104 input rows, got {len(rows)}")
    seen: set[tuple[int, str, int, int]] = set()
    for row in rows:
        row["meet"] = str(int(row["meet"]))
        row["date"] = iso_day(row["date"])
        row["race_no"] = str(int(row["race_no"]))
        row["horse_no"] = str(int(row["horse_no"]))
        key = (int(row["meet"]), row["date"], int(row["race_no"]), int(row["horse_no"]))
        if key in seen:
            raise ValueError("input contains duplicate meet/date/race/program key")
        seen.add(key)
    return rows


def csv_write(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                             if isinstance(value, (dict, list)) else value for key, value in row.items()})


def main() -> None:
    inputs = read_input()
    keys = {(int(r["meet"]), r["date"], int(r["race_no"]), int(r["horse_no"])) for r in inputs}

    core_db = duckdb.connect(str(CORE), read_only=True)
    try:
        core_rows = core_db.execute(
            """SELECT source_meet, result_date, result_race_no, horse_program_no_raw,
                      horse_id_raw, horse_name_raw, source_file, source_item_index
               FROM confirmed_runners"""
        ).fetchall()
    finally:
        core_db.close()
    core: dict[tuple[int, str, int, int], dict[str, object]] = {}
    core_population: dict[tuple[int, str, int, int], dict[str, object]] = {}
    for meet, date_value, race_no, horse_no, horse_id, horse_name, source_file, source_item in core_rows:
        key = (int(meet), iso_day(date_value), int(number(race_no) or 0), int(number(horse_no) or 0))
        if key[0] in (1, 3, 4) and "2017-01-01" <= key[1] <= "2026-09-29":
            if key in core_population:
                raise ValueError("core population contains a duplicate strong key")
            core_population[key] = {"horse_id": clean(horse_id), "horse_name": clean(horse_name)}
        if key in keys:
            if key in core:
                raise ValueError("core contains duplicate target strong key")
            core[key] = {
                "horse_id": clean(horse_id), "horse_name": clean(horse_name),
                "source_file": clean(source_file), "source_item_index": clean(source_item),
            }
    if set(core) != keys:
        raise ValueError(f"core key coverage mismatch: {len(set(core) & keys)}/{len(keys)}")

    op = read_only_sqlite(OPERATIONAL)
    try:
        entries = op.execute(
            """SELECT c.kra_meet_code AS meet, r.race_date_local AS day,
                      r.race_number AS race_no, e.horse_number AS horse_no,
                      h.kra_horse_id AS horse_id, h.name_ko AS horse_name,
                      e.id AS entry_id, e.equipment_card_raw AS card_raw,
                      e.equipment_card_observed_at_ms AS observed_at_ms,
                      e.equipment AS equipment_wide
               FROM race_entries AS e
               JOIN races AS r ON r.id=e.race_id
               JOIN racecourses AS c ON c.id=r.racecourse_id
               JOIN horses AS h ON h.id=e.horse_id
               WHERE c.kra_meet_code IN (1,3,4)
                 AND r.race_date_local BETWEEN '2017-01-01' AND '2026-09-29'"""
        ).fetchall()
        op_population_by_key: dict[tuple[int, str, int, int], sqlite3.Row] = {}
        for entry in entries:
            key = (int(entry["meet"]), iso_day(entry["day"]), int(entry["race_no"]), int(entry["horse_no"]))
            if key in op_population_by_key:
                raise ValueError("operational DB contains duplicate strong key")
            op_population_by_key[key] = entry
        op_by_key = {key: op_population_by_key[key] for key in keys if key in op_population_by_key}
        if set(op_by_key) != keys:
            raise ValueError(f"operational key coverage mismatch: {len(set(op_by_key) & keys)}/{len(keys)}")
        # The query intentionally extracts only API date, meet, and page from JSON request metadata.
        documents = op.execute(
            """SELECT sd.id AS document_id, sd.ingestion_run_id,
                      sd.retrieved_at_ms, sd.local_path, sd.sha256,
                      sd.http_status_code, sd.response_bytes,
                      json_extract(sd.request_params_json, '$.race_dt') AS request_date,
                      CAST(json_extract(sd.request_params_json, '$.rccrs_cd') AS INTEGER) AS request_meet,
                      CAST(json_extract(sd.request_params_json, '$.pageNo') AS INTEGER) AS request_page_no,
                      ir.status AS run_status, ir.data_type AS run_data_type,
                      ir.completed_at_ms AS run_completed_at_ms
               FROM source_documents AS sd
               JOIN ingestion_runs AS ir ON ir.id=sd.ingestion_run_id
               WHERE sd.endpoint=? AND sd.operation=?
                 AND json_extract(sd.request_params_json, '$.race_dt') IS NOT NULL
                 AND CAST(json_extract(sd.request_params_json, '$.rccrs_cd') AS INTEGER) IN (1,3,4)
               ORDER BY sd.retrieved_at_ms, sd.id""",
            (ENDPOINT, "chulmainfo"),
        ).fetchall()
        requested_day_meets = {(day8(day), meet) for meet, day, _race, _no in keys}
        grouped: dict[tuple[str, int], dict[int, list[sqlite3.Row]]] = defaultdict(lambda: defaultdict(list))
        target_rows_by_day_meet: dict[tuple[str, int], list[dict[str, str]]] = defaultdict(list)
        for row in inputs:
            target_rows_by_day_meet[(day8(row["date"]), int(row["meet"]))].append(row)
        for doc in documents:
            d = day8(doc["request_date"])
            m = int(doc["request_meet"] or 0)
            if (d, m) in requested_day_meets:
                grouped[(d, m)][int(doc["ingestion_run_id"])].append(doc)

        batches_by_day_meet: dict[tuple[str, int], list[dict[str, object]]] = {}
        incomplete_batches: list[dict[str, object]] = []
        for day_meet, run_groups in grouped.items():
            batches: list[dict[str, object]] = []
            for docs in run_groups.values():
                batch = verify_batch(docs, day_meet[0], day_meet[1])
                if batch["complete"]:
                    batches.append(batch)
                else:
                    incomplete_batches.append({
                        "date": iso_day(day_meet[0]), "meet": day_meet[1],
                        "ingestion_run_id": batch["ingestion_run_id"],
                        "ingestion_run_status": batch["status"],
                        "validated_pages": batch["pages"],
                        "source_document_ids": [d["source_document_id"] for d in batch["source_documents"]],
                        "errors": batch["errors"],
                    })
            batches.sort(key=lambda b: (int(b["completed_at_ms"] or 0), int(b["ingestion_run_id"] or 0)))
            batches_by_day_meet[day_meet] = batches

        row_ledger: list[dict[str, object]] = []
        document_ledger: dict[int, dict[str, object]] = {}
        year_meet = Counter()
        horse_freq = Counter()
        prefix_meet = Counter()
        latest_states = Counter()
        drift_states = Counter()
        source_id_linkage = Counter()
        raw_id_equivalence = Counter()
        target_date_meets: list[dict[str, object]] = []

        for row in inputs:
            meet, day, race_no, horse_no = int(row["meet"]), row["date"], int(row["race_no"]), int(row["horse_no"])
            key = (meet, day, race_no, horse_no)
            c = core[key]
            o = op_by_key[key]
            if clean(c["horse_id"]) != clean(row["horse_id"]):
                raise ValueError("CSV horse ID differs from confirmed_runners")
            if clean(o["horse_id"]) != clean(c["horse_id"]):
                raise ValueError("operational horse ID differs from confirmed_runners")
            if o["observed_at_ms"] is not None:
                raise ValueError("a target row currently has a non-NULL API78 observation")
            prefix = name_prefix(c["horse_name"])
            year_meet[(day[:4], meet)] += 1
            horse_freq[(clean(c["horse_id"]), clean(c["horse_name"]))] += 1
            prefix_meet[(meet, prefix)] += 1
            source_id_linkage["core_horse_id_present"] += bool(clean(c["horse_id"]))
            source_id_linkage["operational_horse_id_equals_core"] += clean(o["horse_id"]) == clean(c["horse_id"])
            source_id_linkage["core_source_file_present"] += bool(clean(c["source_file"]))

            day_meet = (day8(day), meet)
            batches = batches_by_day_meet.get(day_meet, [])
            if not batches:
                latest_batch = None
                latest = {"presence": "no_complete_saved_api78_batch", "equipment_state": None,
                          "equipment_raw": None, "name_match_core": None,
                          "name_match_operational": None, "card_horse_name": None}
                observations: list[dict[str, object]] = []
            else:
                latest_batch = batches[-1]
                latest = card_state(latest_batch, {**row, "horse_name_core": str(c["horse_name"]),
                                                  "horse_name_operational": clean(o["horse_name"])})
                observations = []
                for batch in batches:
                    state = card_state(batch, {**row, "horse_name_core": str(c["horse_name"]),
                                               "horse_name_operational": clean(o["horse_name"])})
                    observations.append({
                        "ingestion_run_id": batch["ingestion_run_id"],
                        "ingestion_run_status": batch["status"],
                        "completed_at_kst": batch["completed_at_kst"],
                        "presence": state["presence"],
                        "equipment_state": state.get("equipment_state"),
                        "equipment_raw": state.get("equipment_raw"),
                        "card_horse_name": state.get("card_horse_name"),
                        "same_name_other_key_candidates": state.get("same_name_other_key_candidates", []),
                    })
                    for source_doc in batch["source_documents"]:
                        document_ledger[int(source_doc["source_document_id"])] = {
                            "source_document_id": source_doc["source_document_id"],
                            "ingestion_run_id": batch["ingestion_run_id"],
                            "date": day, "meet": meet, "page": source_doc["page"],
                            "run_completed_at_kst": batch["completed_at_kst"],
                            "ingestion_run_status": batch["status"],
                            "local_path": source_doc["local_path"], "sha256": source_doc["sha256"],
                            "http_status_code": source_doc["http_status_code"],
                            "response_bytes": source_doc["response_bytes"],
                            "page_count": len(batch["pages"]), "item_count": batch["item_count"],
                        }

            state_name = str(latest["presence"])
            latest_states[state_name] += 1
            if state_name == "no_complete_saved_api78_batch":
                raw_id_equivalence["latest_batch_missing"] += 1
            elif state_name == "absent_at_race_program_key":
                raw_id_equivalence["exact_race_program_absent"] += 1
            elif state_name == "race_program_present_name_differs":
                raw_id_equivalence["name_differs_at_exact_race_program"] += 1
            elif state_name == "same_name_present_at_other_race_program":
                raw_id_equivalence["same_name_present_at_other_race_program"] += 1
            else:
                raw_id_equivalence["name_matches_at_exact_race_program"] += 1
            if latest.get("same_name_other_key_candidates"):
                raw_id_equivalence["rows_with_same_name_other_key_candidates"] += 1
            raw_equipment = latest.get("equipment_state")
            if raw_equipment:
                raw_id_equivalence[f"latest_equipment_{raw_equipment}"] += 1

            if len(observations) > 1:
                signatures = {
                    (o0["presence"], o0.get("equipment_state"), o0.get("equipment_raw"),
                     json.dumps(o0.get("same_name_other_key_candidates", []), ensure_ascii=False, sort_keys=True))
                    for o0 in observations
                }
                if len(signatures) == 1:
                    drift_states["all_complete_observations_same_presence_and_value"] += 1
                else:
                    drift_states["presence_or_equipment_changed"] += 1
            else:
                drift_states["single_or_no_complete_observation"] += 1

            evidence = latest_batch["source_documents"] if latest_batch else []
            row_ledger.append({
                "meet": meet, "date": day, "race_no": race_no, "horse_no": horse_no,
                "horse_id": clean(c["horse_id"]), "horse_name_core": clean(c["horse_name"]),
                "horse_name_prefix": prefix, "horse_name_operational": clean(o["horse_name"]),
                "operational_entry_id": int(o["entry_id"]),
                "operational_api78_observed_at_ms_is_null": o["observed_at_ms"] is None,
                "operational_api78_raw_is_null": o["card_raw"] is None,
                "operational_wide_equipment_nonblank": bool(clean(o["equipment_wide"])),
                "latest_complete_run_id": latest_batch["ingestion_run_id"] if latest_batch else None,
                "latest_complete_at_kst": latest_batch["completed_at_kst"] if latest_batch else None,
                "latest_ingestion_run_status": latest_batch["status"] if latest_batch else None,
                "latest_page_numbers": latest_batch["pages"] if latest_batch else [],
                "latest_batch_item_count": latest_batch["item_count"] if latest_batch else None,
                "latest_source_documents": evidence,
                "latest_presence_class": state_name,
                "latest_card_name": latest.get("card_horse_name"),
                "latest_same_name_other_key_candidates": latest.get("same_name_other_key_candidates", []),
                "latest_card_name_matches_core": latest.get("name_match_core"),
                "latest_card_name_matches_operational": latest.get("name_match_operational"),
                "latest_equipment_state": latest.get("equipment_state"),
                "latest_equipment_raw": latest.get("equipment_raw"),
                "complete_observation_count": len(batches),
                "prior_observations": observations[:-1] if len(observations) > 1 else [],
                "all_observation_history": observations,
            })

        for day_meet in sorted(requested_day_meets):
            batches = batches_by_day_meet.get(day_meet, [])
            targets = target_rows_by_day_meet.get(day_meet, [])
            target_date_meets.append({
                "date": iso_day(day_meet[0]), "meet": day_meet[1],
                "target_row_count": len(targets), "complete_batch_count": len(batches),
                "latest_complete_run_id": batches[-1]["ingestion_run_id"] if batches else None,
                "latest_complete_at_kst": batches[-1]["completed_at_kst"] if batches else None,
                "latest_ingestion_run_status": batches[-1]["status"] if batches else None,
                "latest_complete_page_numbers": batches[-1]["pages"] if batches else [],
                "latest_complete_item_count": batches[-1]["item_count"] if batches else None,
                "latest_complete_document_ids": [x["source_document_id"] for x in batches[-1]["source_documents"]] if batches else [],
            })

        op.rollback()
    finally:
        op.close()

    if sum(year_meet.values()) != 104 or len(row_ledger) != 104:
        raise ValueError("output ledger count is not 104")
    by_year_meet = [
        {"year": year, "meet": meet, "missing_rows": count}
        for (year, meet), count in sorted(year_meet.items())
    ]
    by_horse = [
        {"horse_id": hid, "horse_name_core": name, "missing_rows": count}
        for (hid, name), count in horse_freq.most_common()
    ]
    by_prefix_meet = [
        {"meet": meet, "horse_name_prefix": prefix, "missing_rows": count}
        for (meet, prefix), count in sorted(prefix_meet.items())
    ]
    prefix_population = Counter()
    for key, runner in core_population.items():
        meet, _day, _race, _horse_no = key
        prefix = name_prefix(runner["horse_name"])
        entry = op_population_by_key.get(key)
        if entry is None:
            status = "no_operational_entry"
        elif clean(entry["horse_id"]) != clean(runner["horse_id"]):
            status = "operational_horse_id_mismatch"
        elif entry["observed_at_ms"] is None:
            status = "api78_unobserved"
        else:
            status = "api78_observed"
        prefix_population[(meet, prefix, status)] += 1
    prefix_population_groups: dict[tuple[int, str], dict[str, int]] = defaultdict(dict)
    for (meet, prefix, status), count in sorted(prefix_population.items()):
        prefix_population_groups[(meet, prefix)][status] = count
    prefix_population_by_meet = [
        {
            "meet": meet,
            "horse_name_prefix": prefix,
            "core_runners": sum(counts.values()),
            "api78_observed": counts.get("api78_observed", 0),
            "api78_unobserved": counts.get("api78_unobserved", 0),
            "no_operational_entry": counts.get("no_operational_entry", 0),
            "operational_horse_id_mismatch": counts.get("operational_horse_id_mismatch", 0),
        }
        for (meet, prefix), counts in sorted(prefix_population_groups.items())
    ]
    venue_prefix = {1: "[서울]", 3: "[부산경남]"}
    cross_meet_prefix_count = sum(
        count for (meet, prefix), count in prefix_meet.items()
        if meet in venue_prefix and prefix != venue_prefix[meet]
    )
    latest_batches = [batches[-1] for batches in batches_by_day_meet.values() if batches]
    latest_status_counts = Counter(batch["status"] for batch in latest_batches)
    latest_doc_ids = {
        int(doc["source_document_id"])
        for batch in latest_batches
        for doc in batch["source_documents"]
    }
    older_pair_count = sum(len(batches) > 1 for batches in batches_by_day_meet.values())
    older_batch_count = sum(max(0, len(batches) - 1) for batches in batches_by_day_meet.values())
    # The official KRA runner ID comes from confirmed_runners' result source.
    # API78 itself supplies no horse-ID field, so its item can only be joined by
    # race/program/name and cannot independently validate the official ID.
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "CSV-defined 2017+ core runners with matched operational entry and NULL API78 observation",
        "input_csv": str(INPUT.relative_to(ROOT)),
        "input_rows": len(inputs),
        "distinct_target_date_meet_pairs": len({(r["date"], r["meet"]) for r in inputs}),
        "current_operational_state": {
            "matched_operational_entry": len(row_ledger),
            "api78_observation_timestamp_null": sum(bool(r["operational_api78_observed_at_ms_is_null"]) for r in row_ledger),
            "api78_raw_card_null": sum(bool(r["operational_api78_raw_is_null"]) for r in row_ledger),
            "wide_equipment_nonblank_but_api78_unobserved": sum(bool(r["operational_wide_equipment_nonblank"]) for r in row_ledger),
            "official_horse_id_in_core": source_id_linkage["core_horse_id_present"],
            "official_horse_id_equals_operational_horse_profile_id": source_id_linkage["operational_horse_id_equals_core"],
            "core_source_file_present": source_id_linkage["core_source_file_present"],
        },
        "raw_source_review": {
            "latest_page_complete_saved_API78_batch_selected_per_date_meet": True,
            "all_older_page_complete_batches_checked_for_presence_and_equipment_drift": True,
            "page_completeness_is_independent_of_ingestion_run_status": True,
            "latest_presence_counts": dict(sorted(latest_states.items())),
            "latest_ingestion_run_status_counts": dict(sorted(latest_status_counts.items())),
            "latest_equipment_state_counts": {k.removeprefix("latest_equipment_"): v for k, v in sorted(raw_id_equivalence.items()) if k.startswith("latest_equipment_")},
            "older_observation_drift_counts": dict(sorted(drift_states.items())),
            "date_meets_with_older_complete_observations": older_pair_count,
            "additional_older_complete_batches": older_batch_count,
            "latest_race_program_presence_counts": {k: v for k, v in sorted(raw_id_equivalence.items()) if not k.startswith("latest_equipment_")},
            "latest_source_document_count": len(latest_doc_ids),
            "all_validated_document_count": len(document_ledger),
            "complete_observation_batches_across_target_date_meets": sum(len(v) for v in batches_by_day_meet.values()),
            "saved_batches_rejected_as_incomplete": len(incomplete_batches),
            "incomplete_batch_details": incomplete_batches,
            "dates_meets_without_a_complete_saved_batch": sum(not batches_by_day_meet.get(k) for k in requested_day_meets),
            "api78_horse_id_field_available": False,
        },
        "missing_population_by_year_meet": by_year_meet,
        "missing_population_by_horse": by_horse,
        "missing_population_by_name_prefix_and_meet": by_prefix_meet,
        "core_2017plus_api78_observation_coverage_by_name_prefix_and_meet": prefix_population_by_meet,
        "core_population_scope": "2017-01-01..2026-09-29, meets 1/3/4; API78 state counted only for exact-key operational entries with the same horse ID.",
        "cross_meet_name_prefix_rows": cross_meet_prefix_count,
        "name_prefix_interpretation": "Counts are labels in confirmed_runners.horse_name_raw; for meets 1 and 3 they are compared with the venue prefix. The local API78 cards contain no exact race/program row for these targets, so prefix association is descriptive and does not establish why the row was omitted.",
        "read_only": {
            "operational_sqlite_mode_ro": True,
            "operational_sqlite_query_only": True,
            "core_duckdb_read_only": True,
            "network_used": False,
            "database_rows_modified": False,
            "source_url_selected_or_emitted": False,
            "request_parameter_blob_selected_or_emitted": False,
            "request_json_fields_extracted": ["race_dt", "rccrs_cd", "pageNo"],
            "raw_files_confined_to_data_raw_and_sha256_verified_before_json_parse": True,
        },
        "files": {
            "row_ledger_csv": "row_ledger.csv",
            "validated_document_ledger_csv": "validated_documents.csv",
            "target_date_meet_json": "target_date_meets.json",
        },
    }

    row_fields = [
        "meet", "date", "race_no", "horse_no", "horse_id", "horse_name_core", "horse_name_prefix",
        "horse_name_operational", "operational_entry_id",
        "operational_api78_observed_at_ms_is_null", "operational_api78_raw_is_null",
        "operational_wide_equipment_nonblank", "latest_complete_run_id", "latest_complete_at_kst", "latest_ingestion_run_status",
        "latest_page_numbers", "latest_batch_item_count", "latest_source_documents", "latest_presence_class",
        "latest_card_name", "latest_same_name_other_key_candidates", "latest_card_name_matches_core", "latest_card_name_matches_operational",
        "latest_equipment_state", "latest_equipment_raw", "complete_observation_count",
        "prior_observations", "all_observation_history",
    ]
    doc_rows = sorted(document_ledger.values(), key=lambda row: (row["date"], row["meet"], row["run_completed_at_kst"], row["page"], row["source_document_id"]))
    doc_fields = [
        "source_document_id", "ingestion_run_id", "date", "meet", "page", "run_completed_at_kst", "ingestion_run_status",
        "local_path", "sha256", "http_status_code", "response_bytes", "page_count", "item_count",
    ]
    csv_write(OUT / "row_ledger.csv", row_ledger, row_fields)
    csv_write(OUT / "validated_documents.csv", doc_rows, doc_fields)
    (OUT / "target_date_meets.json").write_text(json.dumps(target_date_meets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
