"""Collect current KRA API42_1 horse profiles for frozen Jeju candidates.

The API exposes current horse-profile state, not a verified historical breed
effective period. API42 breed observations are therefore kept separate from
API20_1 trial-day majong observations.
"""

from __future__ import annotations

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

from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[2]
DB_PATH = PROJECT_ROOT / "jeju/data/jeju_native_core.sqlite3"
ENDPOINT = "/API42_1/totalHorseInfo_1"
OPERATION = "totalHorseInfo_1"
PORTAL_DATASET_ID = "15057985"
DAILY_REQUEST_CAP = 3000
MIN_REQUEST_INTERVAL_SECONDS = 1.05
MAX_TRANSIENT_RETRIES = 2
BREED_PLACEHOLDERS = {"-", "--", "—", "–", "0", "n/a", "na", "null", "none", "unknown", "미상"}


def utc_now() -> datetime:
    return datetime.now(UTC)


def kst_date() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()


def iso_utc() -> str:
    return utc_now().isoformat(timespec="milliseconds")


def load_quota_basis(day: str) -> dict[str, Any]:
    checkpoint_path = ROOT / f"quota_checkpoint_{day.replace('-', '')}.json"
    if not checkpoint_path.exists():
        raise RuntimeError(f"Missing date-specific API42 quota checkpoint for {day}")
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    if checkpoint.get("checked_on_kst") != day:
        raise RuntimeError(f"API42 quota checkpoint date does not match {day}")
    if int(checkpoint.get("portal_advertised_daily_request_limit", 0)) != DAILY_REQUEST_CAP:
        raise RuntimeError("API42 quota checkpoint limit does not match collector cap")
    return checkpoint


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def immutable_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def record_event(
    ledger_path: Path,
    quarantine_path: Path,
    by_id: dict[str, list[dict[str, Any]]],
    hr_no: str,
    event: dict[str, Any],
) -> None:
    append_jsonl(ledger_path, event)
    by_id[hr_no].append(event)
    if event.get("validation_status") != "validated":
        append_jsonl(quarantine_path, {
            "run_id": event.get("run_id"),
            "hrNo": hr_no,
            "priority_group": event.get("priority_group"),
            "attempt_no": event.get("attempt_no"),
            "kst_date": event.get("kst_date"),
            "validation_status": event.get("validation_status"),
            "quarantine_reason": event.get("quarantine_reason") or event.get("validation_status"),
            "raw_response_file": event.get("raw_response_file"),
            "response_sha256": event.get("response_sha256"),
            "requested_at_utc": event.get("requested_at_utc"),
        })


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def usable_breed_label(value: Any) -> bool:
    label = clean(value)
    return bool(label) and label.casefold() not in BREED_PLACEHOLDERS


def extract_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    response = payload.get("response", payload)
    if not isinstance(response, dict):
        return []
    body = response.get("body", {})
    if not isinstance(body, dict):
        return []
    wrapped = body.get("items") or {}
    if not isinstance(wrapped, dict):
        return []
    item = wrapped.get("item")
    if item is None:
        return []
    if isinstance(item, dict):
        return [item]
    if isinstance(item, list) and all(isinstance(row, dict) for row in item):
        return item
    return []


def response_body(payload: dict[str, Any]) -> dict[str, Any]:
    response = payload.get("response", payload)
    body = response.get("body", {}) if isinstance(response, dict) else {}
    return body if isinstance(body, dict) else {}


def response_header(payload: dict[str, Any]) -> dict[str, Any]:
    response = payload.get("response", payload)
    header = response.get("header", {}) if isinstance(response, dict) else {}
    return header if isinstance(header, dict) else {}


def read_frozen_targets() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read the shared core DB only; freeze race candidates plus API20 Jeju IDs."""
    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        race_rows = connection.execute(
            """SELECT horse_id, COUNT(*) AS race_result_rows,
                      MIN(race_date) AS first_race_date,
                      MAX(race_date) AS last_race_date
                 FROM jeju_race_population_candidates
                WHERE horse_id IS NOT NULL AND TRIM(horse_id) != ''
                GROUP BY horse_id"""
        ).fetchall()
        evidence_rows = connection.execute(
            """SELECT horse_id, breed_label_raw,
                      COUNT(*) AS event_observation_count,
                      MIN(observed_event_date) AS first_event_date,
                      MAX(observed_event_date) AS last_event_date
                 FROM breed_evidence
                WHERE evidence_kind = 'API20_1 majong observation'
                  AND horse_id IS NOT NULL AND TRIM(horse_id) != ''
                GROUP BY horse_id, breed_label_raw"""
        ).fetchall()
    finally:
        connection.close()

    race_by_id = {str(row["horse_id"]).strip(): dict(row) for row in race_rows}
    api20_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in evidence_rows:
        api20_by_id[str(row["horse_id"]).strip()].append(dict(row))

    race_ids = set(race_by_id)
    api20_jeju_ids = {
        horse_id
        for horse_id, observations in api20_by_id.items()
        if any(row["breed_label_raw"] == "제주" for row in observations)
    }
    all_ids = race_ids | api20_jeju_ids
    priority_ids = sorted(race_ids)
    supplemental_ids = sorted(all_ids - race_ids)
    targets: list[dict[str, Any]] = []
    api20_crosswalk: list[dict[str, Any]] = []
    for horse_id in priority_ids + supplemental_ids:
        observations = api20_by_id.get(horse_id, [])
        labels = sorted({str(row["breed_label_raw"]) for row in observations if row["breed_label_raw"] is not None})
        evidence_total = sum(int(row["event_observation_count"]) for row in observations)
        jeju_total = sum(
            int(row["event_observation_count"])
            for row in observations
            if row["breed_label_raw"] == "제주"
        )
        race = race_by_id.get(horse_id)
        group = "race_result_candidate" if race else "api20_jeju_supplement"
        targets.append({
            "hrNo": horse_id,
            "priority_group": group,
            "race_result_rows": int(race["race_result_rows"]) if race else 0,
            "first_race_date": race["first_race_date"] if race else None,
            "last_race_date": race["last_race_date"] if race else None,
            "api20_majong_labels": labels,
            "api20_event_observation_count": evidence_total,
            "api20_jeju_event_observation_count": jeju_total,
        })
        api20_crosswalk.append({
            "hrNo": horse_id,
            "priority_group": group,
            "api20_majong_labels": labels,
            "api20_observations_by_label": [
                {
                    "majong": row["breed_label_raw"],
                    "event_observation_count": int(row["event_observation_count"]),
                    "first_event_date": row["first_event_date"],
                    "last_event_date": row["last_event_date"],
                }
                for row in sorted(observations, key=lambda item: str(item["breed_label_raw"]))
            ],
        })
    return targets, api20_crosswalk


def initialize_frozen_files() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    ids_path = ROOT / "target_ids.jsonl"
    crosswalk_path = ROOT / "api20_crosswalk.jsonl"
    manifest_path = ROOT / "target_manifest.json"
    if ids_path.exists() and crosswalk_path.exists() and manifest_path.exists():
        targets = [json.loads(line) for line in ids_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        crosswalk = [json.loads(line) for line in crosswalk_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if sha256(ids_path.read_bytes()) != manifest["target_ids_sha256"]:
            raise RuntimeError("Frozen target ID file SHA-256 mismatch")
        if sha256(crosswalk_path.read_bytes()) != manifest["api20_crosswalk_sha256"]:
            raise RuntimeError("Frozen API20 crosswalk SHA-256 mismatch")
        return targets, {row["hrNo"]: row for row in crosswalk}, manifest

    targets, crosswalk = read_frozen_targets()
    ids_content = b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8") for row in targets)
    crosswalk_content = b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8") for row in crosswalk)
    immutable_write(ids_path, ids_content)
    immutable_write(crosswalk_path, crosswalk_content)
    manifest = {
        "created_at_utc": iso_utc(),
        "database_path": str(DB_PATH.relative_to(PROJECT_ROOT)),
        "database_open_mode": "read-only",
        "target_definition": "race-result candidate IDs union every API20_1 majong=제주 horse ID",
        "race_result_candidate_count": sum(row["priority_group"] == "race_result_candidate" for row in targets),
        "api20_jeju_id_count": len({row["hrNo"] for row in crosswalk if "제주" in row["api20_majong_labels"]}),
        "api20_jeju_supplement_count": sum(row["priority_group"] == "api20_jeju_supplement" for row in targets),
        "target_count": len(targets),
        "priority_order": "race_result_candidate IDs first, then supplemental API20_1 Jeju IDs; lexicographic within group",
        "target_ids_sha256": sha256(ids_content),
        "api20_crosswalk_sha256": sha256(crosswalk_content),
        "api20_timing_note": "majong labels are observations on API20_1 trial event dates; no API42 profile state is backdated",
    }
    immutable_write(manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return targets, {row["hrNo"]: row for row in crosswalk}, manifest


def read_request_events(path: Path) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    events: list[dict[str, Any]] = []
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not path.exists():
        return events, by_id
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        events.append(row)
        by_id[row["hrNo"]].append(row)
    return events, by_id


def has_retryable_failure(events: list[dict[str, Any]]) -> bool:
    if not events:
        return False
    latest = events[-1]

    def is_transient(event: dict[str, Any]) -> bool:
        status = event.get("validation_status")
        http_status = event.get("http_status")
        return status in {"timeout_isolated", "transport_error_isolated"} or (
            isinstance(http_status, int) and 500 <= http_status < 600
        )

    transient_failures = sum(is_transient(event) for event in events)
    return is_transient(latest) and transient_failures <= MAX_TRANSIENT_RETRIES


def quota_signal(http_status: int | None, result_code: str, result_message: str) -> bool:
    if http_status == 429 or result_code in {"22", "23"}:
        return True
    text = result_message.lower()
    if "quota" in text or "rate limit" in text:
        return True
    return any(word in text for word in ("일일", "호출량", "요청량", "호출 제한", "요청 횟수 초과"))


def safe_exception(exc: BaseException) -> dict[str, Any]:
    """Retain only structured exception types and numeric errno values."""
    chain: list[dict[str, Any]] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(chain) < 6:
        seen.add(id(current))
        item: dict[str, Any] = {"type": type(current).__name__}
        errno_value = getattr(current, "errno", None)
        if not isinstance(errno_value, int) and getattr(current, "args", None):
            maybe_errno = current.args[0]
            if isinstance(maybe_errno, int):
                errno_value = maybe_errno
        if isinstance(errno_value, int):
            item["errno"] = errno_value
        chain.append(item)
        current = current.__cause__ or current.__context__
    return {"chain": chain}


def summary_from_events(
    targets: list[dict[str, Any]],
    crosswalk: dict[str, dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_by_id: dict[str, dict[str, Any]] = {}
    for event in events:
        latest_by_id[event["hrNo"]] = event
    validated = [
        event for event in latest_by_id.values()
        if event.get("validation_status") == "validated" and usable_breed_label(event.get("breed_raw"))
    ]
    breed_counts = Counter(event.get("breed_raw") or "<missing>" for event in validated)
    comparisons: Counter[str] = Counter()
    for event in validated:
        row = crosswalk.get(event["hrNo"], {})
        majong = set(row.get("api20_majong_labels", []))
        breed = event.get("breed_raw") or ""
        if breed == "제주마" and majong == {"제주"}:
            comparisons["api42_jejumal_matches_api20_jeju"] += 1
        elif breed and "제주" in majong and breed != "제주마":
            comparisons["api42_breed_conflicts_with_api20_jeju"] += 1
        elif breed == "제주마" and "제주" not in majong:
            comparisons["api42_jejumal_without_api20_jeju_label"] += 1
        else:
            comparisons["other_or_unresolved"] += 1
    completed_ids = set(latest_by_id)
    validated_ids = {event["hrNo"] for event in validated}
    candidate_ids = {row["hrNo"] for row in targets if row["priority_group"] == "race_result_candidate"}
    supplemental_ids = {row["hrNo"] for row in targets if row["priority_group"] == "api20_jeju_supplement"}
    api42_only_dates = Counter()
    for event in validated:
        for field, value in (event.get("date_fields") or {}).items():
            normalized = clean(value).casefold()
            if normalized not in {"", "0", "-", "--", "—", "n/a", "na", "null", "none"}:
                api42_only_dates[field] += 1
    return {
        "generated_at_utc": iso_utc(),
        "api42_observation_scope": "current profile state at each API42 response retrieval time; not historical effective breed",
        "api20_scope": "trial-event-date majong observations retained in separate crosswalk",
        "target_count": len(targets),
        "race_result_candidate_count": len(candidate_ids),
        "api20_jeju_supplement_count": len(supplemental_ids),
        "request_attempt_count": len(events),
        "latest_outcome_count": len(latest_by_id),
        "validated_profile_count": len(validated_ids),
        "validated_candidate_count": len(validated_ids & candidate_ids),
        "validated_supplement_count": len(validated_ids & supplemental_ids),
        "remaining_candidate_count": len(candidate_ids - validated_ids),
        "remaining_supplement_count": len(supplemental_ids - validated_ids),
        "remaining_total_count": len(set(row["hrNo"] for row in targets) - validated_ids),
        "latest_status_counts": dict(sorted(Counter(
            "validated_missing_breed"
            if event.get("validation_status") == "validated" and not usable_breed_label(event.get("breed_raw"))
            else event.get("validation_status", "unknown")
            for event in latest_by_id.values()
        ).items())),
        "api42_current_breed_distribution_validated_only": dict(sorted(breed_counts.items())),
        "api42_vs_api20_comparison_validated_only": dict(sorted(comparisons.items())),
        "api42_response_date_field_nonempty_counts": dict(sorted(api42_only_dates.items())),
        "date_field_note": "Returned profile date fields are preserved as raw fields; their official meanings/effective periods have not been verified.",
    }


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    targets, crosswalk, target_manifest = initialize_frozen_files()
    if not targets:
        raise RuntimeError("No frozen profile targets found")

    settings = get_settings()
    secret = settings.data_go_kr_service_key
    service_key = secret.get_secret_value() if secret is not None else None
    if not service_key:
        print(json.dumps({"status": "blocked_missing_service_key"}), flush=True)
        return 2

    ledger_path = ROOT / "request_ledger.jsonl"
    quarantine_path = ROOT / "quarantine_ledger.jsonl"
    state_path = ROOT / "collection_state.json"
    summary_path = ROOT / "collection_summary.json"
    events, by_id = read_request_events(ledger_path)
    today = kst_date()
    outcome_calls_today = sum(event.get("kst_date") == today for event in events)
    previous_state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    state_calls_today = (
        int(previous_state.get("requests_started_today_by_this_collector", 0) or 0)
        if previous_state.get("kst_date") == today
        else 0
    )
    # The state is advanced before each network call, so an interrupted in-flight
    # request still consumes this collector's conservative daily budget.
    calls_today = max(outcome_calls_today, state_calls_today)
    if calls_today >= DAILY_REQUEST_CAP:
        state = {
            "status": "daily_budget_reached",
            "kst_date": today,
            "requests_started_today_by_this_collector": calls_today,
            "daily_request_cap": DAILY_REQUEST_CAP,
            "updated_at_utc": iso_utc(),
        }
        atomic_json(state_path, state)
        atomic_json(summary_path, summary_from_events(targets, crosswalk, events))
        print(json.dumps(state, ensure_ascii=False), flush=True)
        return 0

    run_id = utc_now().strftime("%Y%m%dT%H%M%S.%fZ")
    started_at = iso_utc()
    state = {
        "run_id": run_id,
        "status": "running",
        "started_at_utc": started_at,
        "kst_date": today,
        "requests_started_today_before_run": calls_today,
        "requests_started_this_run": 0,
        "daily_request_cap": DAILY_REQUEST_CAP,
        "quota_basis": load_quota_basis(today),
        "minimum_request_interval_seconds": MIN_REQUEST_INTERVAL_SECONDS,
        "target_manifest_sha256": sha256((ROOT / "target_manifest.json").read_bytes()),
    }
    atomic_json(state_path, state)

    pending = [
        row for row in targets
        if row["hrNo"] not in by_id or has_retryable_failure(by_id[row["hrNo"]])
    ]
    # The immutable target file places the 4,006 race candidates first.
    probe_one = "--probe-one" in sys.argv[1:]
    max_new_calls = min(1, DAILY_REQUEST_CAP - calls_today) if probe_one else DAILY_REQUEST_CAP - calls_today
    to_request = pending[:max_new_calls]
    last_started_monotonic: float | None = None
    stop_status: str | None = None
    base_url = settings.kra_api_base_url.rstrip("/")
    base_url_parts = urlsplit(base_url)
    if base_url_parts.scheme != "https" or base_url_parts.hostname != "apis.data.go.kr":
        state["status"] = "blocked_untrusted_api_base_url"
        state["completed_at_utc"] = iso_utc()
        atomic_json(state_path, state)
        print(json.dumps({"status": state["status"]}), flush=True)
        return 2

    with httpx.Client(base_url=base_url, timeout=90, follow_redirects=False) as client:
        for index, target in enumerate(to_request, start=1):
            if last_started_monotonic is not None:
                elapsed = time.monotonic() - last_started_monotonic
                if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
                    time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)
            request_started = iso_utc()
            last_started_monotonic = time.monotonic()
            hr_no = target["hrNo"]
            prior_attempts = by_id.get(hr_no, [])
            attempt_no = len(prior_attempts) + 1
            started_ms = time.time_ns() // 1_000_000
            event: dict[str, Any] = {
                "run_id": run_id,
                "hrNo": hr_no,
                "priority_group": target["priority_group"],
                "attempt_no": attempt_no,
                "kst_date": today,
                "endpoint": ENDPOINT,
                "operation": OPERATION,
                "public_params": {"_type": "json", "pageNo": 1, "numOfRows": 1000, "hr_no": hr_no},
                "requested_at_utc": request_started,
                "requested_at_ms": started_ms,
            }
            state["requests_started_this_run"] += 1
            state["requests_started_today_by_this_collector"] = calls_today + state["requests_started_this_run"]
            atomic_json(state_path, state)
            try:
                response = client.get(
                    ENDPOINT.lstrip("/"),
                    params={
                        "_type": "json",
                        "pageNo": 1,
                        "numOfRows": 1000,
                        "hr_no": hr_no,
                        "ServiceKey": service_key,
                    },
                )
                retrieved_at_ms = time.time_ns() // 1_000_000
                body_bytes = response.content
                event.update({
                    "retrieved_at_utc": iso_utc(),
                    "retrieved_at_ms": retrieved_at_ms,
                    "http_status": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "response_bytes": len(body_bytes),
                    "response_sha256": sha256(body_bytes),
                })
                secret_forms = (
                    service_key.encode("utf-8"),
                    quote(service_key, safe="").encode("ascii"),
                    quote_plus(service_key, safe="").encode("ascii"),
                )
                if any(secret and secret in body_bytes for secret in secret_forms):
                    event["validation_status"] = "credential_echo_rejected"
                    event["error"] = "Response body echoed configured credential; raw response was not archived."
                    record_event(ledger_path, quarantine_path, by_id, hr_no, event)
                    stop_status = "credential_echo_rejected"
                    break

                raw_name = f"attempt_{attempt_no:02d}_{request_started.replace(':', '').replace('-', '').replace('.', '')}.json"
                raw_path = ROOT / "raw" / hr_no / raw_name
                immutable_write(raw_path, body_bytes)
                event["raw_response_file"] = str(raw_path.relative_to(ROOT))
                stored_bytes = raw_path.read_bytes()
                event["response_sha256_verified"] = sha256(stored_bytes) == event["response_sha256"]
                if not event["response_sha256_verified"]:
                    event["validation_status"] = "stored_raw_sha_mismatch"
                    record_event(ledger_path, quarantine_path, by_id, hr_no, event)
                    stop_status = "stored_raw_sha_mismatch"
                    break

                if response.status_code == 429:
                    event["validation_status"] = "quota_stopped"
                    record_event(ledger_path, quarantine_path, by_id, hr_no, event)
                    stop_status = "quota_stopped"
                    break

                payload: dict[str, Any] | None = None
                parse_error: str | None = None
                try:
                    decoded = json.loads(body_bytes)
                    payload = decoded if isinstance(decoded, dict) else None
                    if payload is None:
                        parse_error = "top-level JSON is not an object"
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    parse_error = type(exc).__name__

                if payload is None:
                    event["validation_status"] = "invalid_json"
                    event["error"] = parse_error
                else:
                    header = response_header(payload)
                    body = response_body(payload)
                    code = clean(header.get("resultCode"))
                    message = clean(header.get("resultMsg"))
                    for secret_form in (service_key, quote(service_key, safe=""), quote_plus(service_key, safe="")):
                        if secret_form:
                            message = message.replace(secret_form, "[REDACTED]")
                    event["api_result_code"] = code
                    event["api_result_message"] = message[:300]
                    if quota_signal(response.status_code, code, message):
                        event["validation_status"] = "quota_stopped"
                        record_event(ledger_path, quarantine_path, by_id, hr_no, event)
                        stop_status = "quota_stopped"
                        break
                    if code not in {"00", "0000"}:
                        event["validation_status"] = "api_error"
                        if code in {"20", "21", "29", "30", "31", "32", "33", "97"}:
                            event["stop_after_error"] = True
                            stop_status = "api_permission_or_key_error"
                    elif response.status_code != 200:
                        event["validation_status"] = "http_error"
                    else:
                        items = extract_items(payload)
                        total_count = body.get("totalCount")
                        try:
                            total_count_int = int(total_count or 0)
                        except (TypeError, ValueError):
                            total_count_int = -1
                        returned_ids = [clean(row.get("hrNo")) for row in items]
                        event.update({
                            "api_total_count": total_count_int,
                            "api_page_no": body.get("pageNo"),
                            "api_page_size": body.get("numOfRows"),
                            "actual_item_count": len(items),
                            "returned_hrNo_values": returned_ids,
                        })
                        if total_count_int == 0 and not items:
                            event["validation_status"] = "profile_not_found"
                        elif total_count_int != 1 or len(items) != 1:
                            event["validation_status"] = "profile_count_mismatch_or_ambiguous"
                        elif returned_ids[0] != hr_no:
                            event["validation_status"] = "requested_hrNo_mismatch"
                        else:
                            profile = items[0]
                            breed = clean(profile.get("breed"))
                            event["breed_raw"] = breed or None
                            event["profile_name"] = clean(profile.get("hrNm")) or None
                            event["date_fields"] = {
                                key: value
                                for key, value in profile.items()
                                if re.search(r"(dt|date|yr|year)$", key, re.IGNORECASE)
                            }
                            event["profile_field_names"] = sorted(profile.keys())
                            event["validation_status"] = "validated" if usable_breed_label(breed) else "validated_missing_breed"
                if event.get("validation_status") != "validated":
                    event["quarantine_reason"] = event.get("validation_status")
                record_event(ledger_path, quarantine_path, by_id, hr_no, event)
                if event.get("stop_after_error"):
                    break
            except httpx.TimeoutException as exc:
                event["validation_status"] = "timeout_isolated"
                event["error"] = safe_exception(exc)
                record_event(ledger_path, quarantine_path, by_id, hr_no, event)
            except httpx.TransportError as exc:
                event["validation_status"] = "transport_error_isolated"
                event["error"] = safe_exception(exc)
                record_event(ledger_path, quarantine_path, by_id, hr_no, event)
            except Exception as exc:
                event["validation_status"] = "request_processing_error_isolated"
                event["error"] = safe_exception(exc)
                record_event(ledger_path, quarantine_path, by_id, hr_no, event)

            if state["requests_started_this_run"] % 50 == 0:
                print(json.dumps({
                    "run_id": run_id,
                    "requests_started_this_run": state["requests_started_this_run"],
                    "requests_started_today_by_this_collector": calls_today + state["requests_started_this_run"],
                    "target_hrNo": hr_no,
                    "validation_status": event.get("validation_status", "unknown"),
                }, ensure_ascii=False), flush=True)

    if stop_status:
        final_status = stop_status
    elif probe_one:
        final_status = "probe_one_completed"
    elif calls_today + state["requests_started_this_run"] >= DAILY_REQUEST_CAP:
        final_status = "daily_budget_checkpoint"
    elif len(to_request) < len(pending):
        final_status = "daily_budget_checkpoint"
    else:
        final_status = "pending_or_completed"
    state.update({
        "status": final_status,
        "completed_at_utc": iso_utc(),
        "requests_started_today_by_this_collector": calls_today + state["requests_started_this_run"],
        "requests_started_this_run": state["requests_started_this_run"],
        "stop_reason": stop_status,
        "targets_pending_at_run_start": len(pending),
    })
    events, _ = read_request_events(ledger_path)
    summary = summary_from_events(targets, crosswalk, events)
    summary["run_status"] = final_status
    summary["today_kst"] = today
    summary["our_collector_calls_today"] = calls_today + state["requests_started_this_run"]
    summary["daily_cap_for_this_collector"] = DAILY_REQUEST_CAP
    summary["quota_basis"] = state.get("quota_basis")
    summary["target_manifest"] = target_manifest
    atomic_json(state_path, state)
    atomic_json(summary_path, summary)
    print(json.dumps({
        "run_id": run_id,
        "status": final_status,
        "requests_started_this_run": state["requests_started_this_run"],
        "requests_started_today_by_this_collector": state["requests_started_today_by_this_collector"],
        "validated_profile_count": summary["validated_profile_count"],
        "validated_candidate_count": summary["validated_candidate_count"],
        "remaining_total_count": summary["remaining_total_count"],
        "breed_distribution": summary["api42_current_breed_distribution_validated_only"],
        "last_outcome": ({
            "hrNo": events[-1].get("hrNo"),
            "status": events[-1].get("validation_status"),
            "http_status": events[-1].get("http_status"),
            "api_result_code": events[-1].get("api_result_code"),
            "api_total_count": events[-1].get("api_total_count"),
            "returned_hrNo_values": events[-1].get("returned_hrNo_values"),
            "error": events[-1].get("error"),
        } if probe_one and events else None),
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
