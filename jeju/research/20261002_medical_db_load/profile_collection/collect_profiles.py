from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus, urlsplit
from zoneinfo import ZoneInfo

import httpx

REPO = Path("/Users/kimyongjin/Desktop/horse_racing")
STAGE = Path("/private/tmp/jeju_medical_20261002/profile_collection")
DB_PATH = REPO / "jeju/data/jeju_native_core.sqlite3"
API16_ROOT = REPO / "jeju/research/20260929_api_detail_sources/raw/full_year_clinic_judgement_start_training/20260929T150517.740550Z"
API16_MANIFEST = API16_ROOT / "run_manifest.json"
API42_CHECKPOINT = REPO / "jeju/research/20260930_api42_horse_breed_collection/quota_checkpoint_20261001.json"
API42_LEDGER = REPO / "jeju/research/20260930_api42_horse_breed_collection/request_ledger.jsonl"
API42_FOLLOWUP_MANIFEST = REPO / "jeju/research/20261001_starting_exam_api_collection/raw/api42_followup/attempts/20261001T151147.863223Z/attempt_manifest.json"
ENDPOINT_PATH = "/API42_1/totalHorseInfo_1"
OPERATION = "totalHorseInfo_1"
DAILY_CAP = 3000
MIN_INTERVAL_SECONDS = 1.05
MAX_TRANSIENT_RETRIES = 2
SUCCESS_CODE = "00"
CUTOFF = "20260919"
PLACEHOLDERS = {"", "-", "--", "—", "–", "0", "n/a", "na", "null", "none", "unknown", "미상"}
TRANSIENT_HTTP = {408, 500, 502, 503, 504}
sys.path.insert(0, str(REPO / "src"))
from horse_racing.config import get_settings  # noqa: E402


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_utc(dt: datetime | None = None) -> str:
    value = dt or utc_now()
    return value.astimezone(UTC).isoformat(timespec="milliseconds")


def kst_date(dt: datetime | None = None) -> str:
    return (dt or utc_now()).astimezone(ZoneInfo("Asia/Seoul")).date().isoformat()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    content = b"".join((json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8") for r in rows)
    atomic_bytes(path, content)


def item_rows(payload: Any) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        return {}, {}, []
    response = payload.get("response", payload)
    if not isinstance(response, dict):
        return {}, {}, []
    header = response.get("header") if isinstance(response.get("header"), dict) else {}
    body = response.get("body") if isinstance(response.get("body"), dict) else {}
    wrapper = body.get("items") if isinstance(body.get("items"), dict) else {}
    raw = wrapper.get("item")
    if raw is None:
        rows: list[dict[str, Any]] = []
    elif isinstance(raw, dict):
        rows = [raw]
    elif isinstance(raw, list) and all(isinstance(x, dict) for x in raw):
        rows = raw
    else:
        rows = []
    return header, body, rows


def field_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def usable(value: Any) -> bool:
    if value is None:
        return False
    return str(value).strip().casefold() not in PLACEHOLDERS


def read_known_ids() -> set[str]:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=10)
    try:
        con.execute("PRAGMA query_only=ON")
        return {str(r[0]).strip() for r in con.execute("SELECT horse_id FROM horse_profile_latest")}
    finally:
        con.close()


def is_reimport_denied(exclusions: Any, horse_id: str) -> bool:
    items = exclusions.get("horses", []) if isinstance(exclusions, dict) else []
    if not isinstance(items, list):
        return False
    return any(
        isinstance(item, dict)
        and str(item.get("horse_id") or item.get("hrNo") or "").strip() == horse_id
        and item.get("reimport_allowed") is False
        for item in items
    )


def source_targets() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest = json.loads(API16_MANIFEST.read_text(encoding="utf-8"))
    clinic = manifest.get("datasets", {}).get("clinic", {})
    if manifest.get("run_id") != "20260929T150517.740550Z":
        raise ValueError("Unexpected API16 clinic source run")
    clinic_summary = manifest.get("summary", {}).get("datasets", {}).get("clinic", {})
    if clinic_summary.get("rows") != 12030 or clinic_summary.get("pages") != 32:
        raise ValueError("API16 source manifest row/page counts do not match the reviewed source")

    known = read_known_ids()
    exclusions = json.loads((REPO / "jeju/data/horse_exclusions.json").read_text(encoding="utf-8"))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    page_count = 0
    row_count = 0
    for year, part in sorted(clinic.get("years", {}).items()):
        for page in part.get("pages", []):
            rel = page.get("response_file")
            if not isinstance(rel, str):
                raise ValueError(f"API16 page has no source path: year={year}")
            source = API16_ROOT / rel
            raw = source.read_bytes()
            if sha256(raw) != page.get("response_sha256") or len(raw) != int(page.get("response_bytes", -1)):
                raise ValueError(f"API16 source page failed its manifest integrity check: year={year}, page={page.get('page_no')}")
            payload = json.loads(raw)
            _, body, rows = item_rows(payload)
            if len(rows) != int(page.get("actual_page_rows", -1)):
                raise ValueError(f"API16 page row count mismatch: year={year}, page={page.get('page_no')}")
            page_count += 1
            row_count += len(rows)
            for index, item in enumerate(rows, start=1):
                horse_id = str(item.get("hrNo") or "").strip()
                if not horse_id:
                    raise ValueError(f"API16 clinic item has no official hrNo: {rel} item {index}")
                date_raw = str(item.get("clinicDate") or "").strip()
                after_cutoff = bool(re.fullmatch(r"\d{8}", date_raw) and date_raw > CUTOFF)
                grouped[horse_id].append({
                    "source_run_id": manifest["run_id"],
                    "source_run_manifest": "jeju/research/20260929_api_detail_sources/raw/full_year_clinic_judgement_start_training/20260929T150517.740550Z/run_manifest.json",
                    "source_page_relative_path": rel,
                    "source_page_sha256": page.get("response_sha256"),
                    "source_page_bytes": page.get("response_bytes"),
                    "page_no": int(page["page_no"]),
                    "item_index": index,
                    "clinic_date_raw": date_raw or None,
                    "meet_raw": item.get("meet"),
                    "horse_id": horse_id,
                    "after_20260919_cutoff": after_cutoff,
                })

    if page_count != 32 or row_count != 12030:
        raise ValueError("API16 source completeness check failed")

    targets: list[dict[str, Any]] = []
    for horse_id, refs in grouped.items():
        if horse_id in known or is_reimport_denied(exclusions, horse_id):
            continue
        if not re.fullmatch(r"\d{7}", horse_id):
            raise ValueError("An unlinked API16 official horse ID is not seven digits")
        within_rows = [r for r in refs if not r["after_20260919_cutoff"]]
        group = "within_20260919_cutoff" if within_rows else "after_20260919_cutoff"
        targets.append({
            "horse_id": horse_id,
            "priority_group": group,
            "source_rows": sorted(refs, key=lambda r: (r["clinic_date_raw"] or "", r["page_no"], r["item_index"])),
        })
    targets.sort(key=lambda r: (0 if r["priority_group"] == "within_20260919_cutoff" else 1, r["horse_id"]))
    n_rows = sum(len(t["source_rows"]) for t in targets)
    within_ids = sum(t["priority_group"] == "within_20260919_cutoff" for t in targets)
    within_rows = sum(sum(not r["after_20260919_cutoff"] for r in t["source_rows"]) for t in targets)
    if (len(targets), n_rows, within_ids, within_rows) != (81, 156, 76, 150):
        raise ValueError("API16 unlinked target set differs from the reviewed 81-horse/156-row set")
    if any(t["horse_id"] == "3005648" for t in targets) or bool(grouped.get("3005648")):
        raise ValueError("Excluded horse 3005648 was unexpectedly found in the clinic source")
    return targets, {
        "profile_latest_unique_official_horse_ids": len(known),
        "api16_source_run_id": manifest["run_id"],
        "api16_source_rows": row_count,
        "api16_source_pages": page_count,
        "unlinked_unique_horse_ids": len(targets),
        "unlinked_clinic_rows": n_rows,
        "within_20260919_cutoff_horse_ids": within_ids,
        "within_20260919_cutoff_clinic_rows": within_rows,
        "after_20260919_cutoff_horse_ids": len(targets) - within_ids,
        "after_20260919_cutoff_clinic_rows": n_rows - within_rows,
        "reimport_exclusion_target_count": 0,
        "small_bear_3005648_clinic_rows": len(grouped.get("3005648", [])),
    }


def current_prior_api42_calls(today: str) -> tuple[int, list[dict[str, Any]]]:
    evidence: list[dict[str, Any]] = []
    total = 0
    if API42_LEDGER.exists():
        ledger_n = 0
        for line in API42_LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("kst_date") == today:
                ledger_n += 1
        if ledger_n:
            evidence.append({
                "path": "jeju/research/20260930_api42_horse_breed_collection/request_ledger.jsonl",
                "kst_date": today,
                "request_events": ledger_n,
                "note": "API42 profile collector; count is scoped to API42 requests.",
            })
            total += ledger_n
    if API42_FOLLOWUP_MANIFEST.exists():
        manifest = json.loads(API42_FOLLOWUP_MANIFEST.read_text(encoding="utf-8"))
        attempt_id = str(manifest.get("attempt_id") or "")
        try:
            start = datetime.strptime(attempt_id, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=UTC)
            attempt_day = kst_date(start)
        except ValueError:
            attempt_day = None
        if attempt_day == today:
            probes = manifest.get("probes", [])
            count = len(probes) if isinstance(probes, list) else 0
            evidence.append({
                "path": "jeju/research/20261001_starting_exam_api_collection/raw/api42_followup/attempts/20261001T151147.863223Z/attempt_manifest.json",
                "attempt_id_utc": attempt_id,
                "kst_date": attempt_day,
                "request_count": count,
                "completed_request_count": sum(p.get("status") == "completed" for p in probes if isinstance(p, dict)),
            })
            total += count
    return total, evidence


def credential_forms(secret: str) -> list[bytes]:
    forms = [secret, quote(secret, safe=""), quote_plus(secret, safe="")]
    return [f.encode("utf-8") for f in set(forms) if f]


def event_status_validation(event: dict[str, Any], raw_body: bytes, secret_forms: list[bytes]) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]]]:
    if any(form in raw_body for form in secret_forms):
        return "credential_echo_rejected", None, []
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "invalid_json", None, []
    if not isinstance(payload, dict):
        return "invalid_json", None, []
    header, body, rows = item_rows(payload)
    code = str(header.get("resultCode") or "").strip()
    event["api_result_code"] = code or None
    if code != SUCCESS_CODE:
        event["api_result_message_recorded"] = False
        if code in {"22", "23"}:
            return "quota_stopped", payload, rows
        if code in {"20", "21", "29", "30", "31", "32", "33", "97"}:
            return "service_permission_error", payload, rows
        return "api_error", payload, rows
    total_raw = body.get("totalCount")
    try:
        total = int(total_raw)
    except (TypeError, ValueError):
        total = -1
    requested = event["horse_id"]
    exact = [r for r in rows if str(r.get("hrNo") or "").strip() == requested]
    event.update({
        "api_total_count": total,
        "returned_item_count": len(rows),
        "exact_hr_no_match_count": len(exact),
        "api_reported_page_no": body.get("pageNo"),
        "api_reported_page_size": body.get("numOfRows"),
    })
    if total == 0 and len(rows) == 0:
        return "normal_no_profile", payload, rows
    if total != 1 or len(rows) != 1:
        return "profile_count_mismatch_or_ambiguous", payload, rows
    if len(exact) != 1:
        return "returned_hr_no_mismatch", payload, rows
    profile = exact[0]
    breed, name = profile.get("breed"), profile.get("hrNm")
    birth = profile.get("birthDt")
    if not usable(birth):
        birth = profile.get("birthYr")
    event["raw_profile_field_keys"] = sorted(profile.keys())
    event["raw_profile_field_types"] = {k: field_type(v) for k, v in sorted(profile.items())}
    event["breed_label_raw"] = breed
    event["horse_name_raw"] = name
    event["birth_value_field"] = "birthDt" if usable(profile.get("birthDt")) else "birthYr"
    if not usable(breed):
        return "missing_or_unusable_breed", payload, rows
    if not usable(name):
        return "missing_or_unusable_name", payload, rows
    if not usable(birth):
        return "missing_or_unusable_birth", payload, rows
    if len(profile) != 218:
        return "profile_field_count_mismatch", payload, rows
    if str(breed).strip() != "제주마":
        return "non_jeju_profile", payload, rows
    return "validated", payload, rows


def persist_raw(relative: str, content: bytes) -> None:
    target = STAGE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError("Refusing to overwrite a frozen raw API response")
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as f:
        tmp = Path(f.name)
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.link(tmp, target)
    tmp.unlink(missing_ok=True)


def make_profile_row(event: dict[str, Any], item: dict[str, Any], raw_file: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "horse_id": event["horse_id"],
        "api_result_code": event["api_result_code"],
        "http_status": event["http_status"],
        "api_total_count": event["api_total_count"],
        "returned_item_count": event["returned_item_count"],
        "exact_hr_no_match_count": event["exact_hr_no_match_count"],
        "breed_label_raw": item.get("breed"),
        "horse_name_raw": item.get("hrNm"),
        "birth_date_raw": item.get("birthDt"),
        "birth_year_raw": item.get("birthYr"),
        "raw_item": item,
        "item_field_keys": sorted(item.keys()),
        "item_field_types": {k: field_type(v) for k, v in sorted(item.items())},
        "response_file": raw_file,
        "response_sha256": event["response_sha256"],
        "response_bytes": event["response_bytes"],
        "observed_at_utc": event["retrieved_at_utc"],
        "observed_kst_date": kst_date(datetime.fromisoformat(event["retrieved_at_utc"])),
        "response_page_no": 1,
        "response_item_index": 1,
        "request_metadata": {
            "endpoint_path": ENDPOINT_PATH,
            "operation": OPERATION,
            "public_params": event["public_params"],
            "credential_recorded": False,
        },
        "clinic_source_rows": event["clinic_source_rows"],
        "priority_group": event["priority_group"],
        "profile_timing_note": "API42 breed/name/birth are current profile observations at response retrieval time; they do not establish historical values on a clinic date.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-horses", type=int, default=None)
    args = parser.parse_args()
    STAGE.mkdir(parents=True, exist_ok=True)
    targets, source_summary = source_targets()
    targets_path = STAGE / "target_manifest.json"
    if not targets_path.exists():
        target_manifest = {
            "schema_version": 1,
            "generated_at_utc": iso_utc(),
            "source_summary": source_summary,
            "targets": targets,
            "selection_rule": "Distinct exact API16 clinic hrNo missing from the current horse_profile_latest official horse_id set, excluding reimport-denied IDs; order is within-cutoff targets first.",
            "cutoff_date_inclusive": "2026-09-19",
            "small_bear_3005648_reimport_allowed": False,
        }
        atomic_json(targets_path, target_manifest)
    else:
        target_manifest = json.loads(targets_path.read_text(encoding="utf-8"))
        if target_manifest.get("source_summary") != source_summary or target_manifest.get("targets") != targets:
            raise ValueError("Frozen target manifest differs from fresh read-only source linkage")

    today = kst_date()
    prior_count, prior_evidence = current_prior_api42_calls(today)
    previous_quota = json.loads(API42_CHECKPOINT.read_text(encoding="utf-8"))
    cap = int(previous_quota.get("portal_advertised_daily_request_limit", 0))
    interval = float(previous_quota.get("collector_request_start_interval_seconds", 0))
    if cap != DAILY_CAP or interval < MIN_INTERVAL_SECONDS:
        raise ValueError("API42 quota checkpoint does not support the requested request rate/cap")
    remaining_at_start = max(0, cap - prior_count)

    settings = get_settings()
    secret_obj = settings.data_go_kr_service_key
    service_key = secret_obj.get_secret_value() if secret_obj is not None else ""
    if not service_key:
        atomic_json(STAGE / "collection_manifest.json", {
            "status": "blocked_missing_service_key",
            "generated_at_utc": iso_utc(),
            "service_key_recorded": False,
            "request_count": 0,
            "source_summary": source_summary,
        })
        print(json.dumps({"status": "blocked_missing_service_key", "requests_started": 0}), flush=True)
        return 2
    base_url = settings.kra_api_base_url.rstrip("/")
    parts = urlsplit(base_url)
    if parts.scheme != "https" or parts.hostname != "apis.data.go.kr" or parts.query or parts.fragment:
        print(json.dumps({"status": "blocked_untrusted_api_base", "requests_started": 0}), flush=True)
        return 2

    ledger_path = STAGE / "request_ledger.jsonl"
    quarantine_path = STAGE / "quarantine_ledger.jsonl"
    state_path = STAGE / "collection_state.json"
    valid_path = STAGE / "validated_profile_rows.jsonl"
    ledger: list[dict[str, Any]] = []
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            try:
                ledger.append(json.loads(line))
            except json.JSONDecodeError:
                raise ValueError("Existing stage request ledger contains a malformed line")
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in ledger:
        by_id[e["horse_id"]].append(e)

    profiles_by_id: dict[str, dict[str, Any]] = {}
    if valid_path.exists():
        for line in valid_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            profiles_by_id[row["horse_id"]] = row

    attempts_today = sum(1 for e in ledger if e.get("kst_date") == today)
    state_prior = 0
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("kst_date") == today:
            state_prior = int(state.get("new_requests_started_today", 0))
    current_count = max(attempts_today, state_prior)
    allowed_new = max(0, DAILY_CAP - prior_count - current_count)
    if args.max_horses is not None:
        allowed_new = min(allowed_new, max(0, args.max_horses))
    run_id = utc_now().strftime("%Y%m%dT%H%M%S.%fZ")
    run_started = iso_utc()
    request_number = 0
    stop_status: str | None = None
    # Conservative spacing across a resumed run as well as inside this process.
    last_start: datetime | None = None
    existing_times = [e.get("requested_at_utc") for e in ledger if e.get("requested_at_utc")]
    if existing_times:
        try:
            last_start = max(datetime.fromisoformat(x) for x in existing_times).astimezone(UTC)
        except ValueError:
            last_start = None

    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "started_at_utc": run_started,
        "kst_date": today,
        "status": "running",
        "source_summary": source_summary,
        "api42_endpoint_path": ENDPOINT_PATH,
        "api42_operation": OPERATION,
        "public_params_template": {"_type": "json", "pageNo": 1, "numOfRows": 1000, "hr_no": "<exact horse_id>"},
        "request_rate": {"minimum_start_interval_seconds": MIN_INTERVAL_SECONDS, "max_transient_retries_per_horse": MAX_TRANSIENT_RETRIES},
        "quota_assessment": {
            "daily_advertised_request_cap": cap,
            "cap_checkpoint_path": "jeju/research/20260930_api42_horse_breed_collection/quota_checkpoint_20261001.json",
            "cap_last_checked_on_kst": previous_quota.get("checked_on_kst"),
            "public_page_exposes_live_remaining_usage": previous_quota.get("account_live_remaining_usage_visible_on_public_page"),
            "prior_known_api42_requests_kst_today": prior_count,
            "prior_request_evidence": prior_evidence,
            "remaining_by_known_count_before_this_run": remaining_at_start,
            "planned_unique_profiles": len(targets),
            "quota_note": "Only the 3,000-request service limit and known same-day API42 request records are available; the public page does not expose a live account balance. API21 calls are a separate endpoint service and are not counted against API42.",
        },
        "service_key_recorded": False,
        "database_access": "SQLite read-only; no writes or imports",
        "profile_timing_note": "API42 current profile values are observed at response retrieval time. API16 clinic dates and API42 current breed are not combined into historical breed evidence.",
        "small_bear_3005648_reimport_allowed": False,
        "probes": [],
    }
    atomic_json(state_path, {
        "run_id": run_id,
        "kst_date": today,
        "status": "running",
        "prior_known_api42_requests": prior_count,
        "new_requests_started_today": current_count,
        "daily_cap": DAILY_CAP,
    })
    with httpx.Client(base_url=base_url, timeout=45, follow_redirects=False) as client:
        for target in targets:
            horse_id = target["horse_id"]
            if horse_id in profiles_by_id:
                continue
            previous = by_id.get(horse_id, [])
            previous_retries = sum(e.get("retryable_transient", False) for e in previous)
            latest = previous[-1] if previous else None
            if latest and latest.get("validation_status") not in {"transport_error", "transient_http_error"}:
                continue
            if previous_retries > MAX_TRANSIENT_RETRIES:
                continue
            if request_number >= allowed_new:
                stop_status = "daily_request_budget_checkpoint"
                break

            attempt_no = len(previous) + 1
            while True:
                if last_start is not None:
                    elapsed = (utc_now() - last_start).total_seconds()
                    if elapsed < MIN_INTERVAL_SECONDS:
                        time.sleep(MIN_INTERVAL_SECONDS - elapsed)
                started = utc_now()
                last_start = started
                request_number += 1
                started_today = current_count + request_number
                atomic_json(state_path, {
                    "run_id": run_id,
                    "kst_date": today,
                    "status": "running",
                    "prior_known_api42_requests": prior_count,
                    "new_requests_started_today": started_today,
                    "daily_cap": DAILY_CAP,
                    "last_request_started_at_utc": iso_utc(started),
                })
                public_params = {"_type": "json", "pageNo": 1, "numOfRows": 1000, "hr_no": horse_id}
                event = {
                    "run_id": run_id,
                    "horse_id": horse_id,
                    "priority_group": target["priority_group"],
                    "attempt_no": attempt_no,
                    "kst_date": today,
                    "endpoint_path": ENDPOINT_PATH,
                    "operation": OPERATION,
                    "public_params": public_params,
                    "requested_at_utc": iso_utc(started),
                    "service_key_recorded": False,
                    "clinic_source_rows": target["source_rows"],
                }
                retrieved: datetime | None = None
                response_bytes = b""
                status: int | None = None
                content_type: str | None = None
                transport_error: str | None = None
                try:
                    response = client.get(
                        ENDPOINT_PATH.lstrip("/"),
                        params={**public_params, "ServiceKey": service_key},
                    )
                    retrieved = utc_now()
                    response_bytes = response.content
                    status = response.status_code
                    content_type = response.headers.get("content-type")
                except httpx.TimeoutException as exc:
                    transport_error = type(exc).__name__
                except httpx.TransportError as exc:
                    transport_error = type(exc).__name__
                except Exception as exc:
                    transport_error = type(exc).__name__

                event.update({
                    "retrieved_at_utc": iso_utc(retrieved) if retrieved else None,
                    "http_status": status,
                    "content_type": content_type,
                    "response_bytes": len(response_bytes),
                    "response_sha256": sha256(response_bytes) if response_bytes else None,
                })
                if transport_error:
                    event["validation_status"] = "transport_error"
                    event["error_type"] = transport_error
                    event["retryable_transient"] = True
                    append_jsonl(ledger_path, event)
                    append_jsonl(quarantine_path, {
                        "run_id": run_id, "horse_id": horse_id, "attempt_no": attempt_no,
                        "priority_group": target["priority_group"], "validation_status": "transport_error",
                        "error_type": transport_error, "requested_at_utc": event["requested_at_utc"],
                        "retrieved_at_utc": None, "response_file": None, "response_sha256": None,
                    })
                    ledger.append(event)
                    by_id[horse_id].append(event)
                    previous_retries += 1
                    if previous_retries <= MAX_TRANSIENT_RETRIES and request_number < allowed_new:
                        attempt_no += 1
                        continue
                    break

                if status in TRANSIENT_HTTP:
                    event["validation_status"] = "transient_http_error"
                    event["retryable_transient"] = True
                    event["error_type"] = "HTTPServerError"
                    append_jsonl(ledger_path, event)
                    append_jsonl(quarantine_path, {
                        "run_id": run_id, "horse_id": horse_id, "attempt_no": attempt_no,
                        "priority_group": target["priority_group"], "validation_status": "transient_http_error",
                        "error_type": "HTTPServerError", "http_status": status,
                        "requested_at_utc": event["requested_at_utc"], "retrieved_at_utc": event["retrieved_at_utc"],
                        "response_file": None, "response_sha256": event["response_sha256"],
                    })
                    ledger.append(event)
                    by_id[horse_id].append(event)
                    previous_retries += 1
                    if previous_retries <= MAX_TRANSIENT_RETRIES and request_number < allowed_new:
                        attempt_no += 1
                        continue
                    break

                if status == 429:
                    event["validation_status"] = "quota_stopped"
                    event["error_type"] = "HTTPRateLimit"
                    append_jsonl(ledger_path, event)
                    append_jsonl(quarantine_path, {
                        "run_id": run_id, "horse_id": horse_id, "attempt_no": attempt_no,
                        "priority_group": target["priority_group"], "validation_status": "quota_stopped",
                        "error_type": "HTTPRateLimit", "http_status": status,
                        "requested_at_utc": event["requested_at_utc"], "retrieved_at_utc": event["retrieved_at_utc"],
                        "response_file": None, "response_sha256": event["response_sha256"],
                    })
                    ledger.append(event)
                    by_id[horse_id].append(event)
                    stop_status = "quota_stopped"
                    break

                raw_relative: str | None = None
                if status == 200:
                    if any(form in response_bytes for form in credential_forms(service_key)):
                        event["validation_status"] = "credential_echo_rejected"
                        event["error_type"] = "CredentialEcho"
                        append_jsonl(ledger_path, event)
                        append_jsonl(quarantine_path, {
                            "run_id": run_id, "horse_id": horse_id, "attempt_no": attempt_no,
                            "priority_group": target["priority_group"], "validation_status": "credential_echo_rejected",
                            "error_type": "CredentialEcho", "http_status": status,
                            "requested_at_utc": event["requested_at_utc"], "retrieved_at_utc": event["retrieved_at_utc"],
                            "response_file": None, "response_sha256": event["response_sha256"],
                        })
                        ledger.append(event)
                        by_id[horse_id].append(event)
                        stop_status = "credential_echo_rejected"
                        break
                    raw_relative = f"raw/api42_profiles/{run_id}/source_pages/hr_no_{horse_id}_attempt_{attempt_no:02d}.json"
                    persist_raw(raw_relative, response_bytes)
                    event["response_file"] = raw_relative
                    event["stored_response_sha256"] = sha256((STAGE / raw_relative).read_bytes())
                if status != 200:
                    event["validation_status"] = "http_error"
                    event["error_type"] = "HTTPError"
                    append_jsonl(ledger_path, event)
                    append_jsonl(quarantine_path, {
                        "run_id": run_id, "horse_id": horse_id, "attempt_no": attempt_no,
                        "priority_group": target["priority_group"], "validation_status": "http_error",
                        "error_type": "HTTPError", "http_status": status,
                        "requested_at_utc": event["requested_at_utc"], "retrieved_at_utc": event["retrieved_at_utc"],
                        "response_file": None, "response_sha256": event["response_sha256"],
                    })
                    ledger.append(event)
                    by_id[horse_id].append(event)
                    break

                status_name, payload, items = event_status_validation(event, response_bytes, credential_forms(service_key))
                event["validation_status"] = status_name
                if status_name == "credential_echo_rejected":
                    event.pop("response_file", None)
                    event.pop("stored_response_sha256", None)
                    (STAGE / raw_relative).unlink(missing_ok=True)
                    event["error_type"] = "CredentialEcho"
                elif status_name in {"invalid_json", "api_error", "service_permission_error", "quota_stopped"}:
                    event["error_type"] = {
                        "invalid_json": "ResponseValidationError",
                        "api_error": "APIResponseError",
                        "service_permission_error": "ServicePermissionError",
                        "quota_stopped": "APIQuotaError",
                    }[status_name]
                elif status_name == "validated":
                    item = items[0]
                    event["item_field_count"] = len(item)
                    event["response_page_no"] = 1
                    event["response_item_index"] = 1
                    profile_row = make_profile_row(event, item, raw_relative or "")
                    profiles_by_id[horse_id] = profile_row
                    write_jsonl(valid_path, [profiles_by_id[t["horse_id"]] for t in targets if t["horse_id"] in profiles_by_id])
                else:
                    event["response_page_no"] = 1
                    event["response_item_index"] = (next((i for i, item in enumerate(items, 1) if str(item.get("hrNo") or "").strip() == horse_id), None))
                    event["error_type"] = "ProfileValidationError"
                append_jsonl(ledger_path, event)
                ledger.append(event)
                by_id[horse_id].append(event)
                if status_name != "validated":
                    append_jsonl(quarantine_path, {
                        "run_id": run_id, "horse_id": horse_id, "attempt_no": attempt_no,
                        "priority_group": target["priority_group"], "validation_status": status_name,
                        "error_type": event.get("error_type"),
                        "http_status": status, "api_result_code": event.get("api_result_code"),
                        "api_total_count": event.get("api_total_count"),
                        "returned_item_count": event.get("returned_item_count"),
                        "exact_hr_no_match_count": event.get("exact_hr_no_match_count"),
                        "response_file": raw_relative, "response_sha256": event.get("response_sha256"),
                        "requested_at_utc": event["requested_at_utc"], "retrieved_at_utc": event["retrieved_at_utc"],
                    })
                if status_name == "quota_stopped":
                    stop_status = "quota_stopped"
                    break
                if status_name == "service_permission_error":
                    stop_status = "service_permission_error"
                    break
                break
            if stop_status:
                break
            if request_number % 10 == 0:
                print(json.dumps({
                    "run_id": run_id,
                    "requests_started_this_run": request_number,
                    "profiles_validated": len(profiles_by_id),
                    "latest_target_group": target["priority_group"],
                    "latest_status": ledger[-1].get("validation_status") if ledger else None,
                }, ensure_ascii=False), flush=True)

    status_counts = Counter(e.get("validation_status") for e in ledger)
    valid_profiles = [profiles_by_id[t["horse_id"]] for t in targets if t["horse_id"] in profiles_by_id]
    final_failures = sum(
        1 for t in targets
        if t["horse_id"] in by_id and t["horse_id"] not in profiles_by_id
        and by_id[t["horse_id"]][-1].get("validation_status") not in {"transport_error", "transient_http_error"}
    )
    pending_count = sum(1 for t in targets if t["horse_id"] not in profiles_by_id and t["horse_id"] not in by_id)
    if stop_status:
        final_status = stop_status
    elif pending_count:
        final_status = "incomplete"
    elif final_failures:
        final_status = "complete_with_quarantine"
    else:
        final_status = "complete"
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "started_at_utc": run_started,
        "completed_at_utc": iso_utc(),
        "status": final_status,
        "kst_date": today,
        "source_summary": source_summary,
        "quota_assessment": {
            "daily_advertised_request_cap": cap,
            "cap_checkpoint_path": "jeju/research/20260930_api42_horse_breed_collection/quota_checkpoint_20261001.json",
            "cap_last_checked_on_kst": previous_quota.get("checked_on_kst"),
            "prior_known_api42_requests_kst_today": prior_count,
            "prior_request_evidence": prior_evidence,
            "this_stage_api42_requests_kst_today": current_count + request_number,
            "known_api42_request_total_kst_today": prior_count + current_count + request_number,
            "remaining_by_known_count_after_collection": max(0, cap - prior_count - current_count - request_number),
            "live_account_remaining_usage_visible_on_public_page": previous_quota.get("account_live_remaining_usage_visible_on_public_page"),
            "api21_calls_counted_against_api42": False,
            "minimum_request_start_interval_seconds": MIN_INTERVAL_SECONDS,
            "quota_note": "The API42 checkpoint was last checked on the recorded date; the public page does not expose live account usage. API21 endpoint calls have a separate service limit.",
        },
        "target_unique_profile_count": len(targets),
        "attempted_unique_profile_count": len(by_id),
        "prior_known_api42_requests": prior_count,
        "requests_started_this_run": request_number,
        "requests_started_by_this_stage_today": current_count + request_number,
        "attempt_events_in_stage": len(ledger),
        "validated_profile_count": len(valid_profiles),
        "completed_profile_count": len(valid_profiles),
        "failed_or_invalid_profile_count": final_failures,
        "pending_unique_profile_count": pending_count,
        "quarantine_event_count": sum(1 for e in ledger if e.get("validation_status") != "validated"),
        "validation_status_counts": dict(sorted(status_counts.items())),
        "validated_breed_counts": dict(sorted(Counter(str(r.get("breed_label_raw")) for r in valid_profiles).items())),
        "unqueried_unique_targets": sum(1 for t in targets if t["horse_id"] not in profiles_by_id and t["horse_id"] not in by_id),
        "retry_exhausted_or_failed_targets": sum(1 for t in targets if t["horse_id"] not in profiles_by_id and t["horse_id"] in by_id and by_id[t["horse_id"]][-1].get("validation_status") not in {"transport_error", "transient_http_error"}),
        "files": {
            "target_manifest": "target_manifest.json",
            "request_ledger": "request_ledger.jsonl",
            "quarantine_ledger": "quarantine_ledger.jsonl",
            "validated_profile_rows": "validated_profile_rows.jsonl",
        },
        "profile_timing_note": "Current API42 profile observations do not establish breed on historical clinic dates.",
        "small_bear_3005648_reimport_allowed": False,
    }
    for name, value in {
        "status": final_status,
        "completed_at_utc": iso_utc(),
        "requests_started_this_run": request_number,
        "new_requests_started_today": current_count + request_number,
    }.items():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state[name] = value
        atomic_json(state_path, state)
    manifest["probes"] = [e for e in ledger if e.get("run_id") == run_id]
    manifest.update({
        "target_unique_profile_count": len(targets),
        "status": final_status,
        "completed_at_utc": summary["completed_at_utc"],
        "requests_started_this_run": request_number,
        "validated_profile_count": len(valid_profiles),
        "validation_status_counts": dict(sorted(status_counts.items())),
        "raw_response_root": "raw/api42_profiles",
        "request_ledger": "request_ledger.jsonl",
        "quarantine_ledger": "quarantine_ledger.jsonl",
        "validated_profile_rows": "validated_profile_rows.jsonl",
    })
    atomic_json(STAGE / f"run_manifest_{run_id}.json", manifest)
    atomic_json(STAGE / "collection_manifest.json", summary)
    print(json.dumps({
        "status": final_status,
        "requests_started_this_run": request_number,
        "valid_profiles": len(valid_profiles),
        "validation_status_counts": dict(status_counts),
        "stop_status": stop_status,
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
