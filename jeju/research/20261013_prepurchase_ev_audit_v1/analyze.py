"""Audit whether frozen Jeju pair predictions have provable pre-purchase QPL quotes."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parent
DB = ROOT / "data/horse_racing.sqlite3"
PREDICTIONS = ROOT / "jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet"
PREDICTIONS_SHA256 = "0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6"
API301 = "/API301/Dividend_rate_total"
TARGET_START = "2025-01-01"
TARGET_END = "2026-09-19"
MEET = 2
CUTOFF_MS = 5 * 60 * 1000
STAKE_KRW = 10_000
EV_THRESHOLDS = (0.00, 0.05, 0.10, 0.20)
# Project convention excludes this unusual API value from numeric EV screening.
# Its official/API meaning and live bettability were not verified in this audit.
PROJECT_EXCLUDED_ODDS_VALUE = 9999.9


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stable_hash(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(data.encode("utf-8"))


def timestamp_iso(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value) / 1000, timezone.utc).isoformat(timespec="milliseconds")


def as_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_day(value: object) -> str | None:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    return None


def normalize_meet(value: object) -> int | None:
    value = str(value or "").strip()
    return {"서울": 1, "제주": 2, "부산경남": 3, "부산": 3, "영천": 4}.get(value, as_int(value))


def canonical_pair(first: object, second: object) -> str | None:
    a, b = as_int(first), as_int(second)
    if a is None or b is None or a <= 0 or b <= 0 or a == b:
        return None
    return "-".join(map(str, sorted((a, b))))


def response_items(payload: object) -> tuple[str | None, int | None, int | None, list[dict]]:
    if not isinstance(payload, dict):
        return None, None, None, []
    root = payload.get("response", payload)
    if not isinstance(root, dict):
        return None, None, None, []
    header = root.get("header") or {}
    body = root.get("body") or {}
    if not isinstance(header, dict) or not isinstance(body, dict):
        return None, None, None, []
    code = str(header.get("resultCode") or "")
    page_no = as_int(body.get("pageNo"))
    total_count = as_int(body.get("totalCount"))
    container = body.get("items") or {}
    raw = container.get("item", []) if isinstance(container, dict) else []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raw = []
    return code, page_no, total_count, [x for x in raw if isinstance(x, dict)]


def open_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    connection.execute("BEGIN")
    return connection


def load_predictions() -> tuple[pd.DataFrame, dict]:
    raw_hash = sha256_bytes(PREDICTIONS.read_bytes())
    require(raw_hash == PREDICTIONS_SHA256, "frozen prediction SHA-256 mismatch")
    predictions = pd.read_parquet(PREDICTIONS)
    require("selected_jockey_id_candidate" in predictions, "selector column missing")
    require("jockey_id_candidate_calibrated_probability" in predictions, "QPL probability missing")
    selected_all = predictions.loc[predictions["selected_jockey_id_candidate"].eq(1)].copy()
    selected_all["race_date"] = selected_all["race_id"].astype(str).str.rsplit("_", n=2).str[0]
    selected_all["race_date"] = pd.to_datetime(selected_all["race_date"], errors="raise").dt.strftime("%Y-%m-%d")
    selected_all["race_meet"] = selected_all["race_id"].astype(str).str.rsplit("_", n=2).str[1].astype(int)
    selected_all["race_number"] = selected_all["race_id"].astype(str).str.rsplit("_", n=1).str[1].astype(int)
    require(selected_all["race_id"].is_unique, "selected predictions contain duplicate race ids")
    require((selected_all["race_meet"] == MEET).all(), "fixed selector includes a non-Jeju race")
    pcol = "jockey_id_candidate_calibrated_probability"
    require(selected_all[pcol].notna().all(), "selected probability is missing")
    require(selected_all[pcol].between(0, 1, inclusive="both").all(), "invalid probability")
    require(selected_all[pcol].gt(0).all(), "zero probability cannot produce a finite required odds threshold")
    target = selected_all.loc[
        selected_all["race_date"].between(TARGET_START, TARGET_END, inclusive="both")
        & selected_all["evaluation_year"].isin([2025, 2026])
    ].copy()
    require(len(target) == 1_142 and target["race_id"].is_unique, "frozen target roster changed")
    require(target.groupby("evaluation_year").size().to_dict() == {2025: 654, 2026: 488},
            "frozen year counts changed")
    meta = {
        "sha256": raw_hash,
        "all_selected_races": int(len(selected_all)),
        "all_selected_by_year": {str(k): int(v) for k, v in selected_all.groupby("evaluation_year").size().items()},
        "target_races": int(len(target)),
        "target_by_year": {str(k): int(v) for k, v in target.groupby("evaluation_year").size().items()},
        "target_first_date": str(target["race_date"].min()),
        "target_last_date": str(target["race_date"].max()),
        "probability_column": pcol,
        "probability_event": "selected pair jointly finishes in the official Top3 (QPL event)",
    }
    return target, meta


def fetch_races_and_odds(connection: sqlite3.Connection, target: pd.DataFrame) -> tuple[dict, list[dict], dict]:
    race_rows = connection.execute(
        """SELECT r.id, r.race_date_local, r.race_number, r.scheduled_at_ms,
                  r.actual_start_at_ms, r.status, c.kra_meet_code
           FROM races AS r JOIN racecourses AS c ON c.id=r.racecourse_id
           WHERE c.kra_meet_code=? AND r.race_date_local BETWEEN ? AND ?
           ORDER BY r.race_date_local, r.race_number""",
        (MEET, TARGET_START, TARGET_END),
    ).fetchall()
    db_by_key = {(str(row["race_date_local"]), int(row["race_number"])): row for row in race_rows}
    target_db = {}
    for row in target.itertuples(index=False):
        key = (str(row.race_date), int(row.race_number))
        require(key in db_by_key, f"target race absent from shared DB: {row.race_id}")
        target_db[str(row.race_id)] = db_by_key[key]

    ids = sorted({int(row["id"]) for row in target_db.values()})
    placeholders = ",".join("?" for _ in ids)
    snapshot_rows = connection.execute(
        f"""SELECT o.id, o.race_id, r.race_date_local, r.race_number, o.bet_type,
                   o.selection_key, o.odds, o.observed_at_ms
            FROM odds_snapshots AS o JOIN races AS r ON r.id=o.race_id
            WHERE o.bet_type=? AND o.race_id IN ({placeholders})
            ORDER BY o.race_id, o.selection_key, o.observed_at_ms, o.id""",
        ("QPL", *ids),
    ).fetchall()
    snapshot_rows = [dict(row) for row in snapshot_rows]

    all_pool_summary = []
    for row in connection.execute(
        """SELECT o.bet_type, c.kra_meet_code, COUNT(*) AS row_count,
                  COUNT(DISTINCT r.id) AS race_count,
                  MIN(r.race_date_local) AS first_race_date,
                  MAX(r.race_date_local) AS last_race_date,
                  COUNT(DISTINCT o.observed_at_ms) AS distinct_observed_times,
                  MIN(o.observed_at_ms) AS first_observed_ms,
                  MAX(o.observed_at_ms) AS last_observed_ms,
                  SUM(CASE WHEN r.scheduled_at_ms IS NOT NULL
                                AND o.observed_at_ms < r.scheduled_at_ms - ? THEN 1 ELSE 0 END) AS rows_before_t5,
                  SUM(CASE WHEN r.scheduled_at_ms IS NULL THEN 1 ELSE 0 END) AS rows_missing_schedule,
                  SUM(CASE WHEN r.actual_start_at_ms IS NULL THEN 1 ELSE 0 END) AS rows_missing_actual_start
           FROM odds_snapshots AS o JOIN races AS r ON r.id=o.race_id
           JOIN racecourses AS c ON c.id=r.racecourse_id
           GROUP BY o.bet_type, c.kra_meet_code ORDER BY c.kra_meet_code, o.bet_type""",
        (CUTOFF_MS,),
    ):
        d = dict(row)
        d["first_observed_utc"] = timestamp_iso(d["first_observed_ms"])
        d["last_observed_utc"] = timestamp_iso(d["last_observed_ms"])
        all_pool_summary.append(d)
    return target_db, snapshot_rows, {"race_table_rows": len(race_rows), "pool_by_meet": all_pool_summary}


def read_api301_documents(connection: sqlite3.Connection, days: set[str]) -> tuple[list[dict], dict]:
    documents = []
    for row in connection.execute(
        """SELECT id, ingestion_run_id, retrieved_at_ms, requested_at_ms,
                  local_path, sha256, http_status_code, response_bytes,
                  request_params_json
           FROM source_documents WHERE endpoint=? ORDER BY retrieved_at_ms, id""",
        (API301,),
    ):
        try:
            params = json.loads(row["request_params_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        day = normalize_day(params.get("rc_date"))
        meet = normalize_meet(params.get("meet"))
        page_no = as_int(params.get("pageNo"))
        if day not in days or meet != MEET:
            continue
        local = Path(str(row["local_path"]))
        if not local.is_absolute():
            local = ROOT / local
        exists = local.is_file()
        body = local.read_bytes() if exists else b""
        actual_hash = sha256_bytes(body) if exists else None
        payload = None
        if exists:
            try:
                payload = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
        code, response_page, total_count, items = response_items(payload)
        documents.append({
            "document_id": int(row["id"]),
            "run_id": int(row["ingestion_run_id"]),
            "day": day,
            "meet": meet,
            "page_no_param": page_no,
            "page_no_response": response_page,
            "total_count": total_count,
            "item_count": len(items),
            "requested_at_ms": int(row["requested_at_ms"]),
            "retrieved_at_ms": int(row["retrieved_at_ms"]),
            "http_status_code": row["http_status_code"],
            "response_bytes": int(row["response_bytes"]),
            "expected_sha256": str(row["sha256"]),
            "actual_sha256": actual_hash,
            "hash_verified": bool(exists and actual_hash == str(row["sha256"])),
            "path_relative": str(local.resolve().relative_to(ROOT)) if local.resolve().is_relative_to(ROOT) else "outside_workspace_path",
            "response_code": code,
            "items": items,
        })
    summary = {
        "pages_for_target_dates": len(documents),
        "distinct_days": len({d["day"] for d in documents}),
        "distinct_runs": len({(d["day"], d["run_id"]) for d in documents}),
        "all_page_hashes_verified": all(d["hash_verified"] for d in documents),
        "verified_pages": sum(d["hash_verified"] for d in documents),
        "target_dates_without_registry_pages": sorted(days - {d["day"] for d in documents}),
        "retrieved_first_utc": timestamp_iso(min((d["retrieved_at_ms"] for d in documents), default=None)),
        "retrieved_last_utc": timestamp_iso(max((d["retrieved_at_ms"] for d in documents), default=None)),
        "request_first_utc": timestamp_iso(min((d["requested_at_ms"] for d in documents), default=None)),
        "request_last_utc": timestamp_iso(max((d["requested_at_ms"] for d in documents), default=None)),
    }
    return documents, summary


def audit_raw_items(target: pd.DataFrame, target_db: dict, snapshots: list[dict], docs: list[dict]) -> tuple[list[dict], dict, list[dict]]:
    prediction_by_key = {}
    for row in target.itertuples(index=False):
        prediction_by_key[(str(row.race_date), int(row.race_number))] = row
    rows_by_id = defaultdict(list)
    for row in snapshots:
        rows_by_id[int(row["race_id"])].append(row)

    # Group the raw page documents by date and ingestion run to expose overlapping pulls.
    grouped_runs = defaultdict(list)
    for doc in docs:
        grouped_runs[(doc["day"], doc["run_id"])].append(doc)
    run_summaries = []
    for (day, run_id), pages in sorted(grouped_runs.items()):
        page_numbers = sorted(d["page_no_param"] for d in pages if d["page_no_param"] is not None)
        run_summaries.append({
            "day": day,
            "meet": MEET,
            "run_id": run_id,
            "page_count": len(pages),
            "page_numbers": page_numbers,
            "first_request_ms": min(d["requested_at_ms"] for d in pages),
            "last_request_ms": max(d["requested_at_ms"] for d in pages),
            "first_retrieval_ms": min(d["retrieved_at_ms"] for d in pages),
            "last_retrieval_ms": max(d["retrieved_at_ms"] for d in pages),
            "hashes_verified": all(d["hash_verified"] for d in pages),
            "statuses_200": all(d["http_status_code"] == 200 for d in pages),
            "response_codes_ok": all(d["response_code"] in {"00", "0000"} for d in pages),
            "page_echo_ok": all(d["page_no_param"] == d["page_no_response"] for d in pages),
        })

    # Index source rows once, retaining provenance but never copying source URLs/other params.
    raw_rows_by_key = defaultdict(list)
    for doc in docs:
        if not doc["hash_verified"] or doc["http_status_code"] != 200 or doc["response_code"] not in {"00", "0000"}:
            continue
        for item in doc["items"]:
            item_day = normalize_day(item.get("rcDate"))
            item_meet = normalize_meet(item.get("meet"))
            race_no = as_int(item.get("rcNo"))
            pool = str(item.get("pool") or "").strip().upper()
            pair = canonical_pair(item.get("chulNo"), item.get("chulNo2"))
            if item_day != doc["day"] or item_meet != MEET or pool != "QPL" or race_no is None or pair is None:
                continue
            try:
                price = float(item.get("odds"))
            except (TypeError, ValueError):
                price = None
            key = (item_day, MEET, race_no, pair)
            raw_rows_by_key[key].append({
                "document_id": doc["document_id"],
                "run_id": doc["run_id"],
                "page_no": doc["page_no_param"],
                "requested_at_ms": doc["requested_at_ms"],
                "retrieved_at_ms": doc["retrieved_at_ms"],
                "price": price,
                "source_item_date_matches": item_day == doc["day"],
                "source_item_meet_matches": item_meet == MEET,
                "source_item_race_matches": race_no is not None,
                "source_hash": doc["expected_sha256"],
                "path_relative": doc["path_relative"],
            })

    audit_rows = []
    exact_quote_occurrences = []
    all_before_cutoff_rows = []
    for key, pred in prediction_by_key.items():
        day, race_no = key
        race_id = str(pred.race_id)
        db_race = target_db[race_id]
        db_id = int(db_race["id"])
        scheduled = as_int(db_race["scheduled_at_ms"])
        cutoff = scheduled - CUTOFF_MS if scheduled is not None else None
        actual = as_int(db_race["actual_start_at_ms"])
        pair = canonical_pair(pred.horse_i, pred.horse_j)
        require(pair is not None, f"invalid selected pair for {race_id}")
        all_snapshots = rows_by_id[db_id]
        selected_snapshots = [s for s in all_snapshots if canonical_pair(*str(s["selection_key"]).split("-")) == pair]
        shared_pre = [s for s in selected_snapshots if cutoff is not None and int(s["observed_at_ms"]) < cutoff]
        selected_raw = raw_rows_by_key.get((day, MEET, race_no, pair), [])
        raw_pre = [d for d in selected_raw if cutoff is not None
                   and d["requested_at_ms"] < cutoff and d["retrieved_at_ms"] < cutoff]
        raw_pre_positive = [d for d in raw_pre if d["price"] is not None and math.isfinite(d["price"])
                            and 0 < d["price"] < PROJECT_EXCLUDED_ODDS_VALUE]
        raw_pre_exceptional = [d for d in raw_pre if d["price"] is not None
                               and d["price"] >= PROJECT_EXCLUDED_ODDS_VALUE]
        raw_post = [d for d in selected_raw if cutoff is not None and d["retrieved_at_ms"] >= cutoff]
        post_retrievals = [d["retrieved_at_ms"] for d in raw_post]
        pre_prices = [d["price"] for d in raw_pre if d["price"] is not None and math.isfinite(d["price"])]
        post_prices = [d["price"] for d in raw_post if d["price"] is not None and math.isfinite(d["price"])]
        all_before = [s for s in all_snapshots if cutoff is not None and int(s["observed_at_ms"]) < cutoff]
        if all_before:
            all_before_rows.extend({
                "race_id": race_id,
                "selection_key": str(s["selection_key"]),
                "observed_at_ms": int(s["observed_at_ms"]),
                "scheduled_at_ms": scheduled,
                "cutoff_ms": cutoff,
                "selected_model_pair": pair,
                "selected_pair_match": canonical_pair(*str(s["selection_key"]).split("-")) == pair,
                "odds_value_reported": False,
            } for s in all_before)
        latest_raw = max(selected_raw, key=lambda d: d["retrieved_at_ms"], default=None)
        row = {
            "race_id": race_id,
            "year": int(pred.evaluation_year),
            "pair": pair,
            "p_pair_top3": float(pred.jockey_id_candidate_calibrated_probability),
            "scheduled_at_ms": scheduled,
            "scheduled_at_utc": timestamp_iso(scheduled),
            "cutoff_ms": cutoff,
            "cutoff_utc": timestamp_iso(cutoff),
            "actual_start_at_ms": actual,
            "actual_start_missing": actual is None,
            "scheduled_start_missing": scheduled is None,
            "shared_qpl_snapshot_rows_all_pairs": len(all_snapshots),
            "shared_qpl_rows_exact_pair": len(selected_snapshots),
            "shared_qpl_exact_pair_rows_before_cutoff": len(shared_pre),
            "raw_api301_exact_pair_items_all_versions": len(selected_raw),
            "raw_api301_exact_pair_items_requested_and_retrieved_before_cutoff": len(raw_pre),
            "raw_api301_ordinary_positive_items_before_cutoff": len(raw_pre_positive),
            "raw_api301_exceptional_value_items_before_cutoff": len(raw_pre_exceptional),
            "raw_api301_exact_pair_candidate_items_before_cutoff": len(raw_pre_positive) + len(raw_pre_exceptional),
            "raw_api301_exact_pair_items_received_after_cutoff": len(raw_post),
            "raw_api301_after_cutoff_value_differs_from_pre_cutoff": bool(
                pre_prices and post_prices and any(value != pre_prices[-1] for value in post_prices)
            ),
            "latest_raw_exact_pair_received_after_cutoff_ms": max(post_retrievals, default=None),
            "latest_raw_exact_pair_received_after_cutoff_utc": timestamp_iso(max(post_retrievals, default=None)),
            "pre_cutoff_candidate_class": (
                "raw_pre_cutoff_price_candidate_clock_and_bettable_display_unverified"
                if raw_pre_positive else "exceptional_value_only_meaning_unverified" if raw_pre_exceptional else "none"
            ),
            "latest_raw_exact_pair_retrieved_at_ms": latest_raw["retrieved_at_ms"] if latest_raw else None,
            "latest_raw_exact_pair_retrieved_at_utc": timestamp_iso(latest_raw["retrieved_at_ms"]) if latest_raw else None,
            "pre_cutoff_odds": None,
            "pre_cutoff_ev": None,
            "pre_cutoff_source_document_ids": ";".join(str(d["document_id"]) for d in raw_pre_positive),
            "pre_cutoff_source_hashes": ";".join(d["source_hash"] for d in raw_pre_positive),
            "pre_cutoff_source_paths": ";".join(d["path_relative"] for d in raw_pre_positive),
        }
        audit_rows.append(row)
        for d in raw_pre_positive + raw_pre_exceptional:
            price = d["price"]
            ordinary_positive_value = (price is not None and math.isfinite(price)
                                       and 0 < price < PROJECT_EXCLUDED_ODDS_VALUE)
            after_cutoff_values = [
                item for item in selected_raw
                if cutoff is not None and item["retrieved_at_ms"] >= cutoff
                and item["price"] is not None and math.isfinite(item["price"])
            ]
            later_differs = bool(after_cutoff_values and any(item["price"] != price for item in after_cutoff_values))
            exact_quote_occurrences.append({
                "race_id": race_id,
                "pair": pair,
                "probability": float(pred.jockey_id_candidate_calibrated_probability),
                "document_id": d["document_id"],
                "run_id": d["run_id"],
                "page_no": d["page_no"],
                "requested_at_ms": d["requested_at_ms"],
                "retrieved_at_ms": d["retrieved_at_ms"],
                "cutoff_ms": cutoff,
                "minutes_before_scheduled_start": round((scheduled - d["retrieved_at_ms"]) / 60_000, 3) if scheduled is not None else None,
                "source_api301_value": price,
                "conditional_ev_proxy": (float(pred.jockey_id_candidate_calibrated_probability) * price - 1.0) if ordinary_positive_value else None,
                "after_cutoff_exact_pair_source_versions": len(raw_post),
                "after_cutoff_source_value_differs": later_differs,
                "latest_after_cutoff_retrieved_at_ms": max(post_retrievals, default=None),
                "latest_after_cutoff_retrieved_at_utc": timestamp_iso(max(post_retrievals, default=None)),
                "exceptional_value_excluded_from_ev": not ordinary_positive_value,
                "status": ("raw_pre_cutoff_value_clock_and_bettable_display_unverified"
                           if ordinary_positive_value else "exceptional_value_excluded_meaning_unverified"),
                "source_hash": d["source_hash"],
                "source_path": d["path_relative"],
            })
            ev_proxy = exact_quote_occurrences[-1]["conditional_ev_proxy"]
            exact_quote_occurrences[-1]["proxy_pass_ev_ge_0"] = bool(ev_proxy is not None and ev_proxy >= 0.00)
            exact_quote_occurrences[-1]["proxy_pass_ev_ge_0_05"] = bool(ev_proxy is not None and ev_proxy >= 0.05)
            exact_quote_occurrences[-1]["proxy_pass_ev_ge_0_10"] = bool(ev_proxy is not None and ev_proxy >= 0.10)
            exact_quote_occurrences[-1]["proxy_pass_ev_ge_0_20"] = bool(ev_proxy is not None and ev_proxy >= 0.20)

    ordinary_count = sum(not row["exceptional_value_excluded_from_ev"] for row in exact_quote_occurrences)
    exceptional_count = len(exact_quote_occurrences) - ordinary_count
    return audit_rows, {"api301_target_day_run_count": len(run_summaries),
                        "api301_raw_exact_pair_candidate_occurrences": len(exact_quote_occurrences),
                        "api301_raw_exact_pair_ordinary_positive_occurrences": ordinary_count,
                        "api301_raw_exact_pair_exceptional_value_occurrences": exceptional_count,
                        "api301_raw_exact_pair_occurrences": exact_quote_occurrences}, run_summaries


def audit_global_prestart_exception(connection: sqlite3.Connection, docs: list[dict], selected_all: pd.DataFrame) -> dict:
    rows = connection.execute(
        """SELECT r.id AS race_db_id, r.race_date_local, r.race_number, r.scheduled_at_ms,
                  r.actual_start_at_ms, o.selection_key, o.observed_at_ms, o.odds
           FROM odds_snapshots AS o JOIN races AS r ON r.id=o.race_id
           JOIN racecourses AS c ON c.id=r.racecourse_id
           WHERE c.kra_meet_code=? AND o.bet_type='QPL'
             AND r.scheduled_at_ms IS NOT NULL AND o.observed_at_ms < r.scheduled_at_ms - ?
           ORDER BY r.race_date_local, r.race_number, o.selection_key""",
        (MEET, CUTOFF_MS),
    ).fetchall()
    selected_ids = set(selected_all["race_id"].astype(str))
    race_db_ids = sorted({int(row["race_db_id"]) for row in rows})
    runner_state = defaultdict(dict)
    if race_db_ids:
        placeholders = ",".join("?" for _ in race_db_ids)
        for runner in connection.execute(
            f"""SELECT e.race_id, e.horse_number, e.scratched, rr.finish_position
                FROM race_entries AS e LEFT JOIN race_results AS rr ON rr.race_entry_id=e.id
                WHERE e.race_id IN ({placeholders})""",
            race_db_ids,
        ):
            runner_state[int(runner["race_id"])][int(runner["horse_number"])] = {
                "scratched": bool(runner["scratched"]),
                "finish_position": runner["finish_position"],
            }
    details = []
    for row in rows:
        selection = str(row["selection_key"])
        selection_numbers = [int(number) for number in selection.split("-") if number.isdigit()]
        states = runner_state[int(row["race_db_id"])]
        scratched_numbers = [number for number in selection_numbers
                             if states.get(number, {}).get("scratched", False)]
        details.append({
            "race_db_id": int(row["race_db_id"]),
            "race_id": f"{row['race_date_local']}_{MEET}_{int(row['race_number'])}",
            "selection_key": selection,
            "selected_pair_contains_scratched_runner": bool(scratched_numbers),
            "selected_scratched_horse_numbers": scratched_numbers,
            "selected_scratched_runner_finish_positions": [
                states[number]["finish_position"] for number in scratched_numbers
            ],
            "observed_at_ms": int(row["observed_at_ms"]),
            "observed_at_utc": timestamp_iso(row["observed_at_ms"]),
            "scheduled_at_ms": int(row["scheduled_at_ms"]),
            "scheduled_at_utc": timestamp_iso(row["scheduled_at_ms"]),
            "actual_start_missing": row["actual_start_at_ms"] is None,
            "in_fixed_prediction_roster": f"{row['race_date_local']}_{MEET}_{int(row['race_number'])}" in selected_ids,
            "odds_value_reported": False,
        })
    return {
        "shared_qpl_rows_before_scheduled_t5": len(details),
        "races_with_shared_qpl_rows_before_scheduled_t5": len({d["race_id"] for d in details}),
        "details": details,
        "interpretation": "Timestamp lead is a source/clock candidate only. Every listed selection must be checked against runners, raw API301 page and the fixed prediction roster; this is not a model quote or return table.",
    }


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def probe_summary() -> dict:
    path = ROOT / "data/research/api301_snapshot_probe_20261009/snapshots.sqlite3"
    report_path = path.parent / "report.json"
    result = {"exists": path.is_file(), "scope_date": "2026-10-09", "model_roster_overlap": 0}
    if not path.is_file():
        return result
    c = open_read_only(path)
    try:
        rows = c.execute(
            """SELECT meet, COUNT(*) AS observation_rows,
                      SUM(CASE WHEN offset_minutes>0 AND status='present' THEN 1 ELSE 0 END) AS pre_positive,
                      SUM(CASE WHEN offset_minutes>0 AND status='empty' THEN 1 ELSE 0 END) AS pre_empty,
                      SUM(CASE WHEN offset_minutes<0 AND status='present' THEN 1 ELSE 0 END) AS post_positive,
                      SUM(CASE WHEN offset_minutes<0 THEN positive_rows ELSE 0 END) AS post_positive_value_rows
               FROM observations GROUP BY meet ORDER BY meet"""
        ).fetchall()
        result["by_meet"] = [dict(row) for row in rows]
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            result["request_attempts_reported"] = int(report.get("requests", 0))
            result["races_reported"] = len(report.get("races", []))
            result["meet2_races_reported"] = sum(1 for row in report.get("races", []) if int(row.get("meet", 0)) == MEET)
    finally:
        c.close()
    return result


def main() -> None:
    STUDY.mkdir(parents=True, exist_ok=True)
    target, prediction_meta = load_predictions()
    selected_all = pd.read_parquet(PREDICTIONS).loc[lambda d: d["selected_jockey_id_candidate"].eq(1)].copy()
    selected_all["race_date"] = pd.to_datetime(
        selected_all["race_id"].astype(str).str.rsplit("_", n=2).str[0], errors="raise"
    ).dt.strftime("%Y-%m-%d")
    selected_all["race_meet"] = selected_all["race_id"].astype(str).str.rsplit("_", n=2).str[1].astype(int)
    selected_all["race_number"] = selected_all["race_id"].astype(str).str.rsplit("_", n=1).str[1].astype(int)
    target_days = set(target["race_date"].astype(str))
    connection = open_read_only(DB)
    try:
        target_db, snapshots, race_pool_meta = fetch_races_and_odds(connection, target)
        docs, docs_meta = read_api301_documents(connection, target_days)
        audit_rows, raw_audit_meta, run_summaries = audit_raw_items(target, target_db, snapshots, docs)
        exception = audit_global_prestart_exception(connection, docs, selected_all)
    finally:
        connection.close()

    require(len(audit_rows) == 1_142, "temporal audit row count changed")
    pre_pair = sum(row["raw_api301_ordinary_positive_items_before_cutoff"] > 0 for row in audit_rows)
    shared_pre_pair = sum(row["shared_qpl_exact_pair_rows_before_cutoff"] > 0 for row in audit_rows)
    raw_item_mismatch = sum(
        row["raw_api301_exact_pair_items_requested_and_retrieved_before_cutoff"] > 0
        and row["raw_api301_ordinary_positive_items_before_cutoff"] == 0
        for row in audit_rows
    )
    all_have_schedule = not any(row["scheduled_start_missing"] for row in audit_rows)
    actual_missing = sum(row["actual_start_missing"] for row in audit_rows)
    eligible_quote_count = pre_pair

    # Theoretical quote thresholds use only the frozen model probability. They are not
    # observations, EV outcomes, or predictions of an eventual pari-mutuel settlement.
    required_rows = []
    for row in audit_rows:
        p = row["p_pair_top3"]
        required_rows.append({
            "race_id": row["race_id"],
            "year": row["year"],
            "selected_pair": row["pair"],
            "p_pair_top3": f"{p:.8f}",
            "required_qpl_display_odds_ev_ge_0": f"{1.00 / p:.6f}",
            "required_qpl_display_odds_ev_ge_0_05": f"{1.05 / p:.6f}",
            "required_qpl_display_odds_ev_ge_0_10": f"{1.10 / p:.6f}",
            "required_qpl_display_odds_ev_ge_0_20": f"{1.20 / p:.6f}",
            "actual_pre_purchase_quote": "",
            "actual_ev": "",
            "stake_krw_if_future_quote_verified": STAKE_KRW,
            "status": "theoretical_threshold_only_no_verified_quote",
        })

    write_csv(
        STUDY / "selected_pair_time_audit.csv",
        audit_rows,
        ["race_id", "year", "pair", "p_pair_top3", "scheduled_at_ms", "scheduled_at_utc",
         "cutoff_ms", "cutoff_utc", "actual_start_at_ms", "actual_start_missing",
         "scheduled_start_missing", "shared_qpl_snapshot_rows_all_pairs", "shared_qpl_rows_exact_pair",
         "shared_qpl_exact_pair_rows_before_cutoff", "raw_api301_exact_pair_items_all_versions",
         "raw_api301_exact_pair_items_requested_and_retrieved_before_cutoff",
         "raw_api301_ordinary_positive_items_before_cutoff", "raw_api301_exceptional_value_items_before_cutoff",
         "raw_api301_exact_pair_candidate_items_before_cutoff", "pre_cutoff_candidate_class",
         "raw_api301_exact_pair_items_received_after_cutoff", "raw_api301_after_cutoff_value_differs_from_pre_cutoff",
         "latest_raw_exact_pair_received_after_cutoff_ms", "latest_raw_exact_pair_received_after_cutoff_utc",
         "latest_raw_exact_pair_retrieved_at_ms", "latest_raw_exact_pair_retrieved_at_utc",
         "pre_cutoff_odds", "pre_cutoff_ev", "pre_cutoff_source_document_ids", "pre_cutoff_source_hashes",
         "pre_cutoff_source_paths"],
    )
    write_csv(
        STUDY / "selected_pair_required_odds.csv",
        required_rows,
        ["race_id", "year", "selected_pair", "p_pair_top3", "required_qpl_display_odds_ev_ge_0",
         "required_qpl_display_odds_ev_ge_0_05", "required_qpl_display_odds_ev_ge_0_10",
         "required_qpl_display_odds_ev_ge_0_20", "actual_pre_purchase_quote", "actual_ev",
         "stake_krw_if_future_quote_verified", "status"],
    )
    raw_candidates = raw_audit_meta["api301_raw_exact_pair_occurrences"]
    write_csv(
        STUDY / "RAW_PRESTART_API301_CANDIDATES.csv",
        raw_candidates,
        ["race_id", "pair", "probability", "document_id", "run_id", "page_no", "requested_at_ms",
         "retrieved_at_ms", "cutoff_ms", "minutes_before_scheduled_start", "source_api301_value",
         "conditional_ev_proxy", "after_cutoff_exact_pair_source_versions", "after_cutoff_source_value_differs",
         "latest_after_cutoff_retrieved_at_ms", "latest_after_cutoff_retrieved_at_utc",
         "proxy_pass_ev_ge_0", "proxy_pass_ev_ge_0_05", "proxy_pass_ev_ge_0_10",
         "proxy_pass_ev_ge_0_20", "exceptional_value_excluded_from_ev", "status", "source_hash", "source_path"],
    )
    write_csv(
        STUDY / "api301_day_run_index.csv",
        run_summaries,
        ["day", "meet", "run_id", "page_count", "page_numbers", "first_request_ms", "last_request_ms",
         "first_retrieval_ms", "last_retrieval_ms", "hashes_verified", "statuses_200",
         "response_codes_ok", "page_echo_ok"],
    )

    # A compact, safe page provenance index. Only allowlisted date/meet/page fields,
    # timestamps, response status, content hash, and workspace-relative source path appear.
    page_index = [{k: d[k] for k in (
        "document_id", "run_id", "day", "meet", "page_no_param", "page_no_response", "total_count",
        "item_count", "requested_at_ms", "retrieved_at_ms", "http_status_code", "response_bytes",
        "expected_sha256", "actual_sha256", "hash_verified", "path_relative", "response_code")}
        for d in docs]
    (STUDY / "SOURCE_PAGE_INDEX.json").write_text(
        json.dumps(page_index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Summarize candidate timestamps across the shared Jeju QPL table, excluding values.
    global_qpl = next((r for r in race_pool_meta["pool_by_meet"] if r["bet_type"] == "QPL" and r["kra_meet_code"] == MEET), None)
    target_latest_lags = [
        int(row["latest_raw_exact_pair_retrieved_at_ms"]) - int(row["cutoff_ms"])
        for row in audit_rows
        if row["latest_raw_exact_pair_retrieved_at_ms"] is not None and row["cutoff_ms"] is not None
    ]
    report = {
        "objective": "Audit documented pre-purchase QPL quote availability for a frozen selected-pair prediction file.",
        "method": "Read-only shared SQLite plus direct SHA-verified local API301 raw response pages for every target prediction date and Jeju meet.",
        "prediction": prediction_meta,
        "scope": {"start": TARGET_START, "end": TARGET_END, "meet": MEET, "races": 1142,
                  "races_by_year": {"2025": 654, "2026": 488}, "fixed_cutoff": "scheduled_at_ms - 300000 (T-5 minutes)"},
        "eligibility": {"source_record_date_meet_race_and_pool_must_match": True,
                        "selected_pair_must_match_exactly": True,
                        "request_and_retrieval_must_both_precede_cutoff": True,
                        "raw_payload_sha256_must_match_registry": True,
                        "ordinary_positive_odds_required": True,
                        "local_clock_independently_verified": False,
                        "actual_start_at_ms_is_audit_only": True},
        "shared_db_scope": {"qpl_jeju": global_qpl,
                            "target_qpl_snapshot_rows": len(snapshots),
                            "target_qpl_races_with_any_snapshot": len({int(s["race_id"]) for s in snapshots}),
                            "target_predictions_with_exact_pair_snapshot": sum(r["shared_qpl_rows_exact_pair"] > 0 for r in audit_rows),
                            "target_predictions_with_exact_pair_snapshot_before_cutoff": shared_pre_pair,
                            "target_predictions_missing_scheduled_start": sum(r["scheduled_start_missing"] for r in audit_rows),
                            "target_predictions_missing_actual_start": actual_missing},
        "raw_source_inventory": {"endpoint": API301, "operation": "Dividend_rate_total",
                                 "scope": "API301 pages registered for every target prediction date and Jeju meet",
                                 **docs_meta,
                                 "target_selected_pairs_with_raw_ordinary_positive_item_before_cutoff": pre_pair,
                                 "target_selected_pairs_with_any_raw_exact_pair_item_before_cutoff": sum(
                                     r["raw_api301_exact_pair_items_requested_and_retrieved_before_cutoff"] > 0 for r in audit_rows),
                                 "exact_pair_raw_items_before_cutoff_but_invalid_or_exceptional": raw_item_mismatch,
                                 "api301_raw_exact_pair_candidate_occurrences": raw_audit_meta["api301_raw_exact_pair_candidate_occurrences"],
                                 "api301_raw_exact_pair_ordinary_positive_occurrences": raw_audit_meta["api301_raw_exact_pair_ordinary_positive_occurrences"],
                                 "api301_raw_exact_pair_exceptional_value_occurrences": raw_audit_meta["api301_raw_exact_pair_exceptional_value_occurrences"],
                                 "api301_raw_exact_pair_value_counts": {
                                     str(value): sum(row["source_api301_value"] == value
                                                     for row in raw_audit_meta["api301_raw_exact_pair_occurrences"])
                                     for value in sorted({row["source_api301_value"]
                                                          for row in raw_audit_meta["api301_raw_exact_pair_occurrences"]})
                                 },
                                 "api301_raw_candidates_with_after_cutoff_source_version": sum(
                                     row["after_cutoff_exact_pair_source_versions"] > 0
                                     for row in raw_audit_meta["api301_raw_exact_pair_occurrences"]),
                                 "api301_raw_candidates_with_after_cutoff_value_change": sum(
                                     row["after_cutoff_source_value_differs"]
                                     for row in raw_audit_meta["api301_raw_exact_pair_occurrences"]),
                                 "conditional_ev_proxy_by_threshold": {
                                     str(threshold): sum(
                                         row["conditional_ev_proxy"] is not None and row["conditional_ev_proxy"] >= threshold
                                         for row in raw_audit_meta["api301_raw_exact_pair_occurrences"]
                                     ) for threshold in EV_THRESHOLDS
                                 }},
        "all_db_prestart_exception": exception,
        "separate_live_probe": probe_summary(),
        "observed_time_lag_latest_raw_pair_to_cutoff_ms": {
            "count": len(target_latest_lags),
            "min": min(target_latest_lags) if target_latest_lags else None,
            "median": sorted(target_latest_lags)[len(target_latest_lags) // 2] if target_latest_lags else None,
            "max": max(target_latest_lags) if target_latest_lags else None,
            "notes": "This compares local source retrieval times with scheduled cutoffs; it is not an actual-start or server-clock validation."},
        "decision": {"verified_pre_purchase_selected_pair_quotes": 0,
                     "raw_pre_cutoff_exact_pair_candidates": raw_audit_meta["api301_raw_exact_pair_candidate_occurrences"],
                     "ordinary_positive_raw_candidates_with_conditional_ev_proxy": raw_audit_meta["api301_raw_exact_pair_ordinary_positive_occurrences"],
                     "exceptional_value_candidates_excluded_from_ev": raw_audit_meta["api301_raw_exact_pair_exceptional_value_occurrences"],
                     "ev_threshold_backtest_created": False,
                     "roi_or_confidence_interval_created": False,
                     "reason": "Four exact selected-pair values were recorded in hash-verified API301 responses before cutoff, all on 2026-09-05: two values are 1.0 and two are 9999.9. The 1.0 values have negative conditional display-price proxies because both frozen probabilities are below 1.0; neither passes any fixed EV threshold. The 9999.9 values are unusual and excluded from EV because their official meaning and bettability are unverified. None of the four is counted as a verified public executable quote because the collector clock and bettable display were not independently established."},
        "limitations": [
            "SQLite races.actual_start_at_ms is absent for the target QPL rows; scheduled start is used only to define the fixed audit cutoff.",
            "The source registry requested/retrieved timestamps are local collector timestamps; no independent clock offset record is available.",
            "The exact raw API301 page and local retrieval time establish a pre-cutoff source candidate. They do not establish whether the displayed value was publicly visible, current, or executable at the purchase cutoff. Four raw candidates occur across four races on one date, which is not a representative backtest sample.",
            "For the four raw candidates, later exact-pair API301 responses are inventoried by count and whether the returned value changed, without using later prices to select or score bets. Pari-mutuel prices can change before sale close; p times an earlier displayed value minus one is only a conditional proxy under the assumption that the eventual dividend matched that display.",
            "The frozen prediction artifact has no verifiable per-race publication timestamp in this audit.",
            "The theoretical required-odds CSV is derived from frozen p only; it contains no observed odds, EV classification, return, ROI, or oracle payout."],
        "read_only": {"sqlite_uri_mode": "ro", "query_only": True, "network": False, "db_writes": False, "model_fit_or_refit": False},
    }
    (STUDY / "REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    db_extract = {
        "qpl_target_rows": snapshots,
        "target_races": [{"race_id": str(r.race_id), "scheduled_at_ms": as_int(target_db[str(r.race_id)]["scheduled_at_ms"]),
                          "actual_start_at_ms": as_int(target_db[str(r.race_id)]["actual_start_at_ms"])}
                         for r in target.itertuples(index=False)],
    }
    hashes = {
        "fixed_prediction_parquet_sha256": PREDICTIONS_SHA256,
        "target_qpl_db_extraction_sha256": stable_hash(db_extract),
        "api301_target_page_manifest_sha256": stable_hash(page_index),
        "api301_target_pages": len(page_index),
        "api301_target_pages_hash_verified": sum(bool(d["hash_verified"]) for d in docs),
        "api301_exact_pair_pre_cutoff_candidate_occurrences": len(raw_audit_meta["api301_raw_exact_pair_occurrences"]),
        "current_database_main_file_sha256": sha256_bytes(DB.read_bytes()),
        "probe_snapshots_sqlite_sha256": sha256_bytes((ROOT / "data/research/api301_snapshot_probe_20261009/snapshots.sqlite3").read_bytes()),
    }
    (STUDY / "SOURCE_HASHES.json").write_text(json.dumps(hashes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"study": str(STUDY.relative_to(ROOT)), "verified_pre_purchase_selected_pair_quotes": 0,
                      "raw_exact_pair_pre_cutoff_candidates": len(raw_audit_meta["api301_raw_exact_pair_occurrences"]),
                      "all_db_prestart_qpl_rows": exception["shared_qpl_rows_before_scheduled_t5"],
                      "target_rows": len(audit_rows), "api301_target_pages": len(page_index),
                      "api301_pages_verified": docs_meta["verified_pages"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
