"""Read-only, hash-verified API156 vs current API78 equipment comparison.

Run from the repository root with:
    .venv/bin/python thoroughbred/research/20261001_equipment_card_result_review_v1/raw_examples/broad_comparison.py

The output contains source-document metadata and only mismatch/missing equipment
values with strong keys. It never emits source URLs or request parameter blobs.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb


ROOT = Path(__file__).resolve().parents[4]
RAW_ROOT = (ROOT / "data/raw").resolve()
OPERATIONAL_DB = ROOT / "data/horse_racing.sqlite3"
CORE_DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
OUT = Path(__file__).resolve().parent / "broad_comparison.json"
ENDPOINT = "/API156/raceRsutDtl"
MEETS = (1, 3, 4)
DATE_START = "20170101"
DATE_END = "20260929"
NORMAL_RANK_MIN = 1
NORMAL_RANK_MAX = 30
KST = ZoneInfo("Asia/Seoul")
INTEGER = re.compile(r"^\s*(\d+)")
OFFICIAL_HORSE_ID = re.compile(r"^\d{7}$")


def text(value: object) -> str:
    return "" if value is None else str(value).strip()


def whitespace_free(value: object) -> str:
    return "".join(text(value).split())


def integer(value: object) -> int | None:
    match = INTEGER.match(text(value))
    return int(match.group(1)) if match else None


def date_key(value: object) -> str | None:
    digits = "".join(re.findall(r"\d", text(value)))
    return digits if len(digits) == 8 else None


def kst(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc).astimezone(KST).isoformat(
        timespec="milliseconds"
    )


def read_only_sqlite(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    return connection


def safe_raw_path(local_path: str) -> Path:
    path = Path(local_path)
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve(strict=True)
    if not path.is_relative_to(RAW_ROOT):
        raise ValueError("source local_path resolves outside data/raw")
    return path


def normalized_items(payload: dict[str, object]) -> list[dict[str, object]]:
    response = payload.get("response")
    body = response.get("body") if isinstance(response, dict) else None
    bucket = body.get("items", {}) if isinstance(body, dict) else {}
    if isinstance(bucket, dict):
        bucket = bucket.get("item", [])
    if bucket is None:
        return []
    if isinstance(bucket, dict):
        bucket = [bucket]
    if not isinstance(bucket, list) or any(not isinstance(item, dict) for item in bucket):
        raise ValueError("unexpected API156 item container")
    return bucket


def verified_page(row: sqlite3.Row) -> tuple[list[dict[str, object]], dict[str, object]]:
    path = safe_raw_path(row["local_path"])
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != row["sha256"]:
        raise ValueError(f"SHA-256 mismatch for source_document {row['id']}")
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError(f"API156 payload is not an object for source_document {row['id']}")
    items = normalized_items(payload)
    response = payload.get("response")
    body = response.get("body") if isinstance(response, dict) else None
    if not isinstance(body, dict):
        raise ValueError(f"API156 body missing for source_document {row['id']}")
    request_page = integer(row["request_page_no"])
    request_size = integer(row["request_page_size"])
    body_page = integer(body.get("pageNo"))
    body_size = integer(body.get("numOfRows"))
    total_count = integer(body.get("totalCount"))
    if None in (request_page, request_size, body_page, body_size, total_count):
        raise ValueError(f"pagination metadata missing for source_document {row['id']}")
    if request_page != body_page or request_size != body_size or request_size < 1:
        raise ValueError(f"pagination metadata disagrees for source_document {row['id']}")
    metadata = {
        "source_document_id": row["id"],
        "ingestion_run_id": row["ingestion_run_id"],
        "page_number": request_page,
        "page_size": request_size,
        "total_count": total_count,
        "returned_items": len(items),
        "local_path": str(path.relative_to(ROOT)),
        "sha256": digest,
        "requested_at_kst": kst(row["requested_at_ms"]),
        "retrieved_at_kst": kst(row["retrieved_at_ms"]),
        "http_status_code": row["http_status_code"],
    }
    return items, metadata


def load_complete_run(rows: list[sqlite3.Row]) -> tuple[list[tuple[sqlite3.Row, list[dict[str, object]], dict[str, object]]], dict[str, object]] | None:
    """Verify all pages and exact response row coverage for one run."""
    if not rows or any(row["run_status"] != "completed" or row["http_status_code"] != 200 for row in rows):
        return None
    parsed = []
    for row in sorted(rows, key=lambda item: integer(item["request_page_no"]) or 0):
        items, metadata = verified_page(row)
        parsed.append((row, items, metadata))
    pages = [metadata["page_number"] for _, _, metadata in parsed]
    total_counts = {metadata["total_count"] for _, _, metadata in parsed}
    page_sizes = {metadata["page_size"] for _, _, metadata in parsed}
    if len(total_counts) != 1 or len(page_sizes) != 1:
        return None
    total_count = next(iter(total_counts))
    page_size = next(iter(page_sizes))
    expected_pages = max(1, math.ceil(total_count / page_size))
    if pages != list(range(1, expected_pages + 1)):
        return None
    expected_items = sum(min(page_size, max(total_count - (page - 1) * page_size, 0)) for page in pages)
    actual_items = sum(len(items) for _, items, _ in parsed)
    if actual_items != expected_items or actual_items != total_count:
        return None
    return parsed, {
        "expected_pages": expected_pages,
        "verified_pages": pages,
        "total_count": total_count,
        "returned_items": actual_items,
    }


def read_core() -> tuple[dict[tuple[int, str, int, int, str], int], dict[tuple[int, str, int, int], set[str]], dict[str, int]]:
    connection = duckdb.connect(str(CORE_DB), read_only=True)
    rows = connection.execute(
        """
        SELECT source_meet, result_date, result_race_no, result_rank_raw,
               horse_program_no_raw, horse_id_raw
        FROM confirmed_runners
        WHERE source_meet IN ('1','3','4')
          AND result_date BETWEEN ? AND ?
        """,
        [DATE_START, DATE_END],
    ).fetchall()
    connection.close()
    by_full_key: dict[tuple[int, str, int, int, str], int] = {}
    by_basic_key: dict[tuple[int, str, int, int], set[str]] = defaultdict(set)
    counts = Counter()
    for meet_raw, day_raw, race_raw, rank_raw, horse_no_raw, horse_id_raw in rows:
        meet = integer(meet_raw)
        day = date_key(day_raw)
        race = integer(race_raw)
        horse_no = integer(horse_no_raw)
        rank = integer(rank_raw)
        horse_id = text(horse_id_raw)
        if meet not in MEETS or not day or not DATE_START <= day <= DATE_END:
            continue
        if rank is None or not NORMAL_RANK_MIN <= rank <= NORMAL_RANK_MAX:
            continue
        counts["confirmed_core_normal_finish_rows"] += 1
        if race is None or horse_no is None or not OFFICIAL_HORSE_ID.fullmatch(horse_id):
            counts["core_rows_without_strong_key_or_seven_digit_id"] += 1
            continue
        full_key = (meet, day, race, horse_no, horse_id)
        basic_key = full_key[:4]
        if full_key in by_full_key:
            counts["duplicate_core_full_keys"] += 1
            continue
        by_full_key[full_key] = rank
        by_basic_key[basic_key].add(horse_id)
    return by_full_key, by_basic_key, dict(counts)


def read_current_cards() -> tuple[dict[tuple[int, str, int, int, str], dict[str, object]], dict[str, int]]:
    connection = read_only_sqlite(OPERATIONAL_DB)
    rows = connection.execute(
        """
        SELECT c.kra_meet_code AS meet, replace(r.race_date_local,'-','') AS race_date,
               r.race_number AS race_no, e.horse_number AS horse_no,
               h.kra_horse_id AS horse_id, e.equipment_card_raw AS card_raw,
               e.equipment_card_observed_at_ms AS observed_at_ms
        FROM race_entries AS e
        JOIN races AS r ON r.id=e.race_id
        JOIN racecourses AS c ON c.id=r.racecourse_id
        JOIN horses AS h ON h.id=e.horse_id
        WHERE c.kra_meet_code IN (1,3,4)
          AND r.race_date_local BETWEEN '2017-01-01' AND '2026-09-29'
        """
    ).fetchall()
    connection.close()
    cards: dict[tuple[int, str, int, int, str], dict[str, object]] = {}
    counts = Counter()
    for row in rows:
        meet = integer(row["meet"])
        day = date_key(row["race_date"])
        race = integer(row["race_no"])
        horse_no = integer(row["horse_no"])
        horse_id = text(row["horse_id"])
        if meet not in MEETS or not day or race is None or horse_no is None or not horse_id:
            continue
        key = (meet, day, race, horse_no, horse_id)
        if key in cards:
            counts["duplicate_operational_card_keys"] += 1
            continue
        cards[key] = {
            "card_raw": row["card_raw"],
            "observed_at_ms": row["observed_at_ms"],
        }
    return cards, dict(counts)


def latest_complete_batches(rows: list[sqlite3.Row]) -> tuple[list[dict[str, object]], list[tuple[sqlite3.Row, list[dict[str, object]], dict[str, object]]], dict[str, object]]:
    by_scope_run: dict[tuple[str, int, int], list[sqlite3.Row]] = defaultdict(list)
    all_scope_docs: dict[tuple[str, int], list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        day = date_key(row["race_date"])
        meet = integer(row["meet"])
        run_id = integer(row["ingestion_run_id"])
        if not day or meet not in MEETS or run_id is None:
            continue
        all_scope_docs[(day, meet)].append(row)
        by_scope_run[(day, meet, run_id)].append(row)

    selected_metadata: list[dict[str, object]] = []
    selected_pages: list[tuple[sqlite3.Row, list[dict[str, object]], dict[str, object]]] = []
    failed_scopes = []
    skipped_newer_candidates = 0
    for day_meet, scope_rows in sorted(all_scope_docs.items()):
        run_ids = {integer(row["ingestion_run_id"]) for row in scope_rows}
        candidates = []
        for run_id in run_ids:
            run_rows = by_scope_run[(day_meet[0], day_meet[1], run_id)]
            latest_ms = max(row["retrieved_at_ms"] for row in run_rows)
            candidates.append((latest_ms, int(run_id), run_rows))
        candidates.sort(reverse=True)
        chosen = None
        for _, _, run_rows in candidates:
            verified = load_complete_run(run_rows)
            if verified is None:
                skipped_newer_candidates += 1
                continue
            chosen = (run_rows, verified)
            break
        if chosen is None:
            failed_scopes.append({"race_date": day_meet[0], "meet": day_meet[1], "candidate_runs": len(candidates)})
            continue
        run_rows, (parsed, batch_meta) = chosen
        for row, items, page_meta in parsed:
            selected_pages.append((row, items, page_meta))
            selected_metadata.append({
                "race_date": day_meet[0],
                "meet": day_meet[1],
                "source_document_id": row["id"],
                "ingestion_run_id": row["ingestion_run_id"],
                "run_status": row["run_status"],
                "complete_batch_pages": batch_meta["verified_pages"],
                "expected_pages": batch_meta["expected_pages"],
                "total_count": batch_meta["total_count"],
                "returned_items": batch_meta["returned_items"],
                "request_page_number": page_meta["page_number"],
                "page_size": page_meta["page_size"],
                "http_status_code": page_meta["http_status_code"],
                "local_path": page_meta["local_path"],
                "sha256": page_meta["sha256"],
                "requested_at_kst": page_meta["requested_at_kst"],
                "retrieved_at_kst": page_meta["retrieved_at_kst"],
            })
    selection = {
        "date_meet_combinations_available": len(all_scope_docs),
        "date_meet_combinations_selected": len({(row["race_date"], row["meet"]) for row, _, _ in selected_pages}),
        "selected_source_documents": len(selected_pages),
        "unique_selected_runs": len({row["ingestion_run_id"] for row, _, _ in selected_pages}),
        "newer_incomplete_or_unavailable_candidates_skipped": skipped_newer_candidates,
        "scopes_without_any_complete_batch": failed_scopes,
        "selected_runs_with_one_page": sum(1 for item in selected_metadata if item["expected_pages"] == 1),
        "selected_runs_with_multiple_pages": sum(1 for item in selected_metadata if item["expected_pages"] > 1),
    }
    return selected_metadata, selected_pages, selection


def compare() -> dict[str, object]:
    operational = read_only_sqlite(OPERATIONAL_DB)
    all_source_rows = operational.execute(
        """
        SELECT sd.id, sd.ingestion_run_id, sd.local_path, sd.sha256,
               sd.requested_at_ms, sd.retrieved_at_ms, sd.http_status_code,
               ir.status AS run_status,
               json_extract(sd.request_params_json,'$.race_dt') AS race_date,
               json_extract(sd.request_params_json,'$.rccrs_cd') AS meet,
               json_extract(sd.request_params_json,'$.pageNo') AS request_page_no,
               json_extract(sd.request_params_json,'$.numOfRows') AS request_page_size
        FROM source_documents AS sd
        JOIN ingestion_runs AS ir ON ir.id=sd.ingestion_run_id
        WHERE sd.endpoint=?
        ORDER BY sd.retrieved_at_ms DESC, sd.id DESC
        """,
        (ENDPOINT,),
    ).fetchall()
    api156_total = len(all_source_rows)
    api156_population_by_meet = Counter(integer(row["meet"]) for row in all_source_rows)
    api156_status_counts = Counter(row["run_status"] for row in all_source_rows)
    api156_page_numbers = Counter(integer(row["request_page_no"]) for row in all_source_rows)
    in_scope_rows = [
        row for row in all_source_rows
        if row["race_date"] is not None
        and DATE_START <= str(row["race_date"]) <= DATE_END
        and integer(row["meet"]) in MEETS
    ]
    selected_metadata, selected_pages, selection = latest_complete_batches(in_scope_rows)
    operational.close()

    core, core_by_basic, core_counts = read_core()
    cards, card_counts = read_current_cards()
    selected_scopes = {
        (str(row["race_date"]), integer(row["meet"]))
        for row, _, _ in selected_pages
    }
    selected_core_keys = {
        key: rank for key, rank in core.items()
        if (key[1], key[0]) in selected_scopes
    }
    compare_counts = Counter()
    mismatch_records: list[dict[str, object]] = []
    missing_records: list[dict[str, object]] = []
    matched_raw_keys: set[tuple[int, str, int, int, str]] = set()
    api156_items_seen = 0
    api156_normal_rank_items = 0
    api156_bad_or_missing_id = 0
    api156_no_core_basic_key = 0
    api156_id_mismatch_same_basic_key = 0
    api156_rank_conflicts = 0
    api156_duplicate_strong_keys = 0
    api156_core_matches = 0
    selected_result_rows: list[tuple[tuple[int, str, int, int, str], int, object, dict[str, object]]] = []
    for row, items, page_meta in selected_pages:
        doc_day = date_key(row["race_date"])
        doc_meet = integer(row["meet"])
        for item in items:
            api156_items_seen += 1
            item_day = date_key(item.get("schdRaceDt"))
            meet = doc_meet
            race_no = integer(item.get("schdRaceNo"))
            horse_no = integer(item.get("pthrGtno"))
            horse_id = text(item.get("pthrHrno"))
            rank = integer(item.get("rsutRk"))
            if item_day != doc_day or meet not in MEETS or race_no is None or horse_no is None:
                compare_counts["api156_items_with_invalid_source_strong_key"] += 1
                continue
            if rank is None or not NORMAL_RANK_MIN <= rank <= NORMAL_RANK_MAX:
                compare_counts["api156_items_outside_normal_finish_rank_1_30"] += 1
                continue
            api156_normal_rank_items += 1
            if not OFFICIAL_HORSE_ID.fullmatch(horse_id):
                api156_bad_or_missing_id += 1
                continue
            full_key = (meet, item_day, race_no, horse_no, horse_id)
            basic_key = full_key[:4]
            if basic_key not in core_by_basic:
                api156_no_core_basic_key += 1
                continue
            if horse_id not in core_by_basic[basic_key]:
                api156_id_mismatch_same_basic_key += 1
                continue
            if full_key not in core:
                api156_no_core_basic_key += 1
                continue
            if rank != core[full_key]:
                api156_rank_conflicts += 1
                continue
            if full_key in matched_raw_keys:
                api156_duplicate_strong_keys += 1
                continue
            matched_raw_keys.add(full_key)
            api156_core_matches += 1
            selected_result_rows.append((full_key, rank, item.get("pthrEquip"), page_meta))

    for full_key, rank, event_equipment, page_meta in selected_result_rows:
        meet, day, race_no, horse_no, horse_id = full_key
        card = cards.get(full_key)
        api156_raw = None if event_equipment is None else str(event_equipment)
        card_raw = card.get("card_raw") if card is not None else None
        api156_value = whitespace_free(api156_raw)
        card_value = whitespace_free(card_raw)
        api156_observed = bool(api156_value)
        card_observed_at = card.get("observed_at_ms") if card is not None else None
        card_observed = card_observed_at is not None
        if not api156_observed:
            compare_counts["api156_equipment_unobserved_or_blank"] += 1
        if not card_observed:
            compare_counts["current_api78_card_unobserved"] += 1
        elif not card_value:
            compare_counts["current_api78_card_observed_but_blank"] += 1
        if card_observed_at is not None and page_meta["retrieved_at_kst"] is not None:
            api156_ms = int(datetime.fromisoformat(str(page_meta["retrieved_at_kst"])).timestamp() * 1000)
            if int(card_observed_at) > api156_ms:
                compare_counts["card_observation_later_than_api156_capture"] += 1
            elif int(card_observed_at) < api156_ms:
                compare_counts["card_observation_earlier_than_api156_capture"] += 1
            else:
                compare_counts["card_observation_same_timestamp_as_api156_capture"] += 1
        else:
            compare_counts["card_observation_time_unavailable"] += 1

        key = {
            "meet": meet,
            "race_date": day,
            "race_no": race_no,
            "horse_no": horse_no,
            "official_horse_id": horse_id,
        }
        capture_times = {
            "api156_retrieved_at_kst": page_meta["retrieved_at_kst"],
            "current_api78_card_observed_at_kst": kst(int(card_observed_at)) if card_observed_at is not None else None,
        }
        if not api156_observed or not card_observed:
            compare_counts["not_comparable_due_to_unobserved_source"] += 1
            if not api156_observed:
                compare_counts["api156_blank_vs_any_api78_state"] += 1
            if not card_observed:
                compare_counts["api78_unobserved_vs_api156_state"] += 1
            missing_records.append({
                **key,
                "category": "api156_blank" if not api156_observed else "api78_unobserved",
                "api156_pthrEquip": api156_raw,
                "current_api78_card_raw": card_raw,
                **capture_times,
            })
            continue

        if not api156_observed and not card_value:
            compare_counts["both_observed_but_blank"] += 1
            missing_records.append({
                **key,
                "category": "both_observed_but_blank",
                "api156_pthrEquip": api156_raw,
                "current_api78_card_raw": card_raw,
                **capture_times,
            })
            continue
        if not api156_observed or not card_value:
            compare_counts["different_after_whitespace_removal"] += 1
            if not api156_observed:
                compare_counts["api156_blank_vs_api78_nonblank"] += 1
                difference_kind = "api156_blank_vs_api78_value"
            elif api156_value == "-":
                compare_counts["api78_blank_vs_api156_standalone_dash"] += 1
                compare_counts["api156_standalone_dash"] += 1
                difference_kind = "api78_blank_vs_api156_standalone_dash"
            else:
                compare_counts["api78_blank_vs_api156_nonblank_value"] += 1
                difference_kind = "api78_blank_vs_api156_value"
            mismatch_records.append({
                **key,
                "difference_kind": difference_kind,
                "api156_pthrEquip": api156_raw,
                "current_api78_card_raw": card_raw,
                **capture_times,
            })
            continue

        compare_counts["both_nonblank_after_whitespace_removal"] += 1
        if api156_raw == card_raw:
            compare_counts["exact_raw_string_equal"] += 1
            compare_counts["equal_after_whitespace_removal"] += 1
        elif api156_value == card_value:
            compare_counts["equal_after_whitespace_removal_whitespace_only_difference"] += 1
            compare_counts["equal_after_whitespace_removal"] += 1
        else:
            compare_counts["different_after_whitespace_removal"] += 1
            compare_counts["different_nonblank_after_whitespace_removal"] += 1
            mismatch_records.append({
                **key,
                "difference_kind": "different_nonblank_equipment_strings",
                "api156_pthrEquip": api156_raw,
                "current_api78_card_raw": card_raw,
                **capture_times,
            })

    for count_key in (
        "api156_equipment_unobserved_or_blank",
        "current_api78_card_unobserved",
        "current_api78_card_observed_but_blank",
        "api156_standalone_dash",
        "api78_blank_vs_api156_standalone_dash",
        "api78_blank_vs_api156_nonblank_value",
        "api156_blank_vs_api78_nonblank",
        "both_observed_but_blank",
        "not_comparable_due_to_unobserved_source",
        "different_after_whitespace_removal",
        "different_nonblank_after_whitespace_removal",
        "both_nonblank_after_whitespace_removal",
        "exact_raw_string_equal",
        "equal_after_whitespace_removal",
        "equal_after_whitespace_removal_whitespace_only_difference",
        "card_observation_later_than_api156_capture",
        "card_observation_earlier_than_api156_capture",
        "card_observation_same_timestamp_as_api156_capture",
        "card_observation_time_unavailable",
    ):
        compare_counts.setdefault(count_key, 0)
    for record in mismatch_records:
        card_time = record["current_api78_card_observed_at_kst"]
        result_time = record["api156_retrieved_at_kst"]
        if card_time is None or result_time is None:
            compare_counts["mismatch_capture_time_unavailable"] += 1
        elif card_time > result_time:
            compare_counts["mismatch_card_observation_later_than_api156_capture"] += 1
        elif card_time < result_time:
            compare_counts["mismatch_card_observation_earlier_than_api156_capture"] += 1
        else:
            compare_counts["mismatch_card_observation_same_timestamp_as_api156_capture"] += 1
    for count_key in (
        "mismatch_capture_time_unavailable",
        "mismatch_card_observation_later_than_api156_capture",
        "mismatch_card_observation_earlier_than_api156_capture",
        "mismatch_card_observation_same_timestamp_as_api156_capture",
    ):
        compare_counts.setdefault(count_key, 0)
    return {
        "scope": {
            "comparison": "latest complete API156 source batch per race date/meet versus current persisted API78 equipment_card_raw",
            "date_window_requested": [DATE_START, DATE_END],
            "meets": list(MEETS),
            "normal_finish_filter": "confirmed_runners result rank and API156 rsutRk both in 1..30; ranks must agree",
            "identity_match": "meet + exact race date + race number + horse program number + exact seven-digit official horse ID; no horse-name join",
            "normalization": "comparison removes whitespace only; equipment token order, aliases, and +/- marks are preserved",
            "standalone_dash_handling": "A lone '-' is retained as a literal source value and is not parsed as a removal token because it has no equipment name.",
            "not_an_exhaustive_2017plus_api156_audit": True,
            "interpretation_limit": "API156 latest stored result response is compared with the currently stored API78 card observation; this is a cross-observation comparison and cannot establish physical gear worn at race time or an intra-day change.",
        },
        "api156_source_population": {
            "endpoint": ENDPOINT,
            "all_endpoint_documents": api156_total,
            "run_status_counts": dict(api156_status_counts),
            "document_counts_by_meet": {str(meet): count for meet, count in sorted(api156_population_by_meet.items(), key=lambda item: (item[0] is None, item[0]))},
            "request_page_numbers_seen": {str(page): count for page, count in sorted(api156_page_numbers.items(), key=lambda item: (item[0] is None, item[0]))},
            "all_endpoint_date_min": min((str(row["race_date"]) for row in all_source_rows if row["race_date"] is not None), default=None),
            "all_endpoint_date_max": max((str(row["race_date"]) for row in all_source_rows if row["race_date"] is not None), default=None),
            "requested_meet_documents_in_date_window": len(in_scope_rows),
            "requested_meet_date_combinations": len({(str(row["race_date"]), integer(row["meet"])) for row in in_scope_rows}),
            "newest_complete_run_selected_per_available_date_meet": True,
            "selection": selection,
            "selected_source_documents": selected_metadata,
        },
        "core_and_match_counts": {
            **core_counts,
            "core_normal_finish_rows_in_selected_date_meet_combinations": len(selected_core_keys),
            "api156_items_in_selected_batches": api156_items_seen,
            "api156_items_with_normal_finish_rank_1_30": api156_normal_rank_items,
            "api156_normal_rank_items_missing_or_invalid_official_horse_id": api156_bad_or_missing_id,
            "api156_normal_rank_items_without_core_basic_key": api156_no_core_basic_key,
            "api156_normal_rank_items_same_basic_key_but_official_id_conflicts": api156_id_mismatch_same_basic_key,
            "api156_core_identity_matches_with_rank_conflict": api156_rank_conflicts,
            "duplicate_api156_strong_keys_in_selected_batches": api156_duplicate_strong_keys,
            "api156_core_identity_and_rank_matches_compared": api156_core_matches,
            "core_normal_rows_without_matching_selected_api156_item": len(set(selected_core_keys) - matched_raw_keys),
            "operational_card_duplicate_keys": card_counts.get("duplicate_operational_card_keys", 0),
        },
        "comparison_counts": dict(compare_counts),
        "mismatches_after_whitespace_removal": mismatch_records,
        "unobserved_or_blank_cases": missing_records,
        "artifact_metadata": {
            "read_only": True,
            "operational_db": str(OPERATIONAL_DB.relative_to(ROOT)),
            "core_db": str(CORE_DB.relative_to(ROOT)),
            "api156_raw_files_hashed_before_json_parse": len(selected_metadata),
            "api156_raw_files_read_during_selection": len(selected_metadata),
            "source_url_and_raw_request_params_emitted": False,
        },
    }


def main() -> None:
    result = compare()
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "output": str(OUT.relative_to(ROOT)),
        "api156_population": result["api156_source_population"],
        "core_and_match_counts": result["core_and_match_counts"],
        "comparison_counts": result["comparison_counts"],
    }
    summary["api156_population"] = {
        key: value for key, value in summary["api156_population"].items()
        if key != "selected_source_documents"
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
