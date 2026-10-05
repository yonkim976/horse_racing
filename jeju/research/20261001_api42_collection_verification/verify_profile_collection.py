"""Independently verify archived API42 profiles and dated collection coverage."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


HERE = Path(__file__).resolve().parent
COLLECTION = HERE.parent / "20260930_api42_horse_breed_collection"
KST = ZoneInfo("Asia/Seoul")


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    manifest = json.loads((COLLECTION / "target_manifest.json").read_text(encoding="utf-8"))
    for name, field in (("target_ids.jsonl", "target_ids_sha256"), ("api20_crosswalk.jsonl", "api20_crosswalk_sha256")):
        if digest((COLLECTION / name).read_bytes()) != manifest[field]:
            raise ValueError(f"Frozen source hash mismatch: {name}")
    targets = {row["hrNo"]: row for row in load_jsonl(COLLECTION / "target_ids.jsonl")}
    crosswalk = {row["hrNo"]: row for row in load_jsonl(COLLECTION / "api20_crosswalk.jsonl")}
    if len(targets) != 4617 or len(crosswalk) != 4617:
        raise ValueError("Expected exactly 4,617 frozen IDs")
    ledger_raw = (COLLECTION / "request_ledger.jsonl").read_bytes()
    events = [json.loads(line) for line in ledger_raw.splitlines()]
    latest = {}
    all_statuses = Counter()
    daily_requests = Counter()
    daily_starts = {}
    raw_files_verified = 0
    validated_attempts_verified = 0
    for event in events:
        horse_id = event["hrNo"]
        if horse_id not in targets or event["public_params"]["hr_no"] != horse_id:
            raise ValueError(f"Request not in frozen targets: {horse_id}")
        requested = datetime.fromisoformat(event["requested_at_utc"])
        if requested.astimezone(KST).date().isoformat() != event["kst_date"]:
            raise ValueError(f"Request date mismatch: {horse_id}")
        daily_requests[event["kst_date"]] += 1
        daily_starts.setdefault(event["kst_date"], []).append(event["requested_at_ms"])
        all_statuses[event["validation_status"]] += 1
        latest[horse_id] = event
        raw_name = event.get("raw_response_file")
        if not raw_name:
            if event["validation_status"] == "validated":
                raise ValueError(f"Validated profile without raw source: {horse_id}")
            continue
        path = (COLLECTION / raw_name).resolve()
        if not path.is_relative_to((COLLECTION / "raw").resolve()):
            raise ValueError("Raw response path outside the archive")
        raw = path.read_bytes()
        if digest(raw) != event["response_sha256"] or len(raw) != event["response_bytes"]:
            raise ValueError(f"Response hash or byte size mismatch: {horse_id}")
        raw_files_verified += 1
        if event["validation_status"] != "validated":
            continue
        payload = json.loads(raw)
        response = payload.get("response", payload)
        header, body = response["header"], response["body"]
        wrapped = body["items"]
        items = wrapped.get("item")
        items = [items] if isinstance(items, dict) else items
        if event["http_status"] != 200 or str(header["resultCode"]) not in {"00", "0000"}:
            raise ValueError(f"HTTP/API status mismatch: {horse_id}")
        if int(body["totalCount"]) != 1 or not isinstance(items, list) or len(items) != 1:
            raise ValueError(f"Ambiguous profile: {horse_id}")
        profile = items[0]
        if str(profile["hrNo"]).strip() != horse_id:
            raise ValueError(f"Returned horse ID mismatch: {horse_id}")
        if not str(profile.get("breed", "")).strip() or str(profile["breed"]).strip() != event["breed_raw"]:
            raise ValueError(f"Breed value mismatch: {horse_id}")
        validated_attempts_verified += 1
    if any(count > 3000 for count in daily_requests.values()):
        raise ValueError("Collector daily request count exceeds its guard")
    minimum_intervals = {}
    for day, starts in daily_starts.items():
        if len(starts) > 1:
            minimum_intervals[day] = min((b - a) / 1000 for a, b in zip(starts, starts[1:]))
    if minimum_intervals.get("2026-10-01", 1.05) < 1.0:
        raise ValueError("Today's request starts were less than one second apart")
    previously_completed = {event["hrNo"] for event in events if event["kst_date"] < "2026-10-01" and event["validation_status"] == "validated"}
    called_today = {event["hrNo"] for event in events if event["kst_date"] == "2026-10-01"}
    if previously_completed & called_today:
        raise ValueError("Resume called a previously completed profile")
    validated = {key: event for key, event in latest.items() if event["validation_status"] == "validated"}
    groups = Counter(targets[key]["priority_group"] for key in validated)
    breed_counts = Counter(event["breed_raw"] for event in validated.values())
    conflicts = [key for key, event in validated.items() if event["breed_raw"] != "제주마" and "제주" in crosswalk[key]["api20_majong_labels"]]
    result = {
        "verified_on_kst": "2026-10-01",
        "target_ids": len(targets),
        "request_ledger_sha256": digest(ledger_raw),
        "request_attempts": len(events),
        "requests_by_kst_date": dict(sorted(daily_requests.items())),
        "minimum_request_start_intervals_seconds": dict(sorted(minimum_intervals.items())),
        "previously_completed_ids_requeried_today": len(previously_completed & called_today),
        "raw_response_files_verified": raw_files_verified,
        "validated_attempts_verified": validated_attempts_verified,
        "validated_unique_ids": len(validated),
        "validated_profile_observation_dates_kst": dict(sorted(Counter(event["kst_date"] for event in validated.values()).items())),
        "validated_groups": dict(sorted(groups.items())),
        "latest_status_counts": dict(sorted(Counter(event["validation_status"] for event in latest.values()).items())),
        "all_attempt_status_counts": dict(sorted(all_statuses.items())),
        "current_breed_distribution": dict(sorted(breed_counts.items())),
        "api42_vs_api20_breed_conflict_ids": conflicts,
        "remaining_ids": sorted(set(targets) - set(validated)),
        "current_profile_observations_are_not_backdated": True,
    }
    (HERE / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in {"remaining_ids", "api42_vs_api20_breed_conflict_ids"}}, ensure_ascii=False))
    print(f"Remaining IDs: {len(result['remaining_ids'])}; breed conflicts: {len(conflicts)}")


if __name__ == "__main__":
    main()
