"""One execution of the bounded E8-B capture-only pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from horse_racing.analysis.confirmed_starter_e8b import (
    BudgetTransport,
    CaptureStore,
    PilotCapture,
    schedule_cutoff,
)
from horse_racing.collectors.kra_api import ENTRY_SHEET_ENDPOINT, RACE_PLAN_ENDPOINT
from horse_racing.config import get_settings

KST = timezone(timedelta(hours=9))
ROOT = Path("data/experiments/confirmed_starter_e8b_20260913")


def _write(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date", default="20260919", help="one near-future Seoul race date YYYYMMDD"
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="new isolated attempt directory")
    args = parser.parse_args()
    now = datetime.now(KST)
    target = datetime.strptime(args.date, "%Y%m%d").date()
    if target < now.date() or target > now.date() + timedelta(days=7):
        raise SystemExit("target must be today or within the next 7 days")
    settings = get_settings()
    root = args.root
    store = CaptureStore(root)
    base = Path("src/horse_racing")
    sources = [
        Path(__file__),
        base / "analysis/confirmed_starter_e8b.py",
        base / "parsers/entry_sheet.py",
        base / "parsers/race_day.py",
    ]
    protocol = {
        "target_date": args.date,
        "meet": 1,
        "started_at_kst": now.isoformat(),
        "endpoints_and_public_params": [
            {
                "endpoint": RACE_PLAN_ENDPOINT,
                "rccrs_cd": 1,
                "race_dt": args.date,
                "_type": "json",
                "pageNo": 1,
                "numOfRows": 1000,
            },
            {
                "endpoint": ENTRY_SHEET_ENDPOINT,
                "meet": 1,
                "rc_date": args.date,
                "_type": "json",
                "pageNo": 1,
                "numOfRows": 1000,
            },
        ],
        "transport_max_requests": 12,
        "retry_max_attempts_per_page": 2,
        "redirects_followed": False,
        "source_sha256": {str(p): _sha(p) for p in sources},
        "credential_present": bool(settings.data_go_kr_service_key),
    }
    # This is durably recorded before constructing or using any HTTP client.
    _write(root / "preflight_protocol.json", protocol)
    result: dict[str, Any] = {
        "status": "capture_only_incomplete",
        "operating_model_status": "not_activated",
        "F_t_eligibility": "unverified",
        "target_date": args.date,
        "http_requests": 0,
        "batches": [],
        "prospective_case": None,
        "last_observation_completed_at_ms": None,
        "limitations": [],
    }
    secret = settings.data_go_kr_service_key
    if secret is None or not secret.get_secret_value().strip():
        result["limitations"].append("service credential unavailable; zero HTTP requests")
    else:
        transport = BudgetTransport(httpx.HTTPTransport(retries=0), limit=12)
        pilot = PilotCapture(
            store,
            service_key=secret.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=min(settings.http_timeout_seconds, 10.0),
            transport=transport,
        )
        try:
            plan = pilot.batch(RACE_PLAN_ENDPOINT, args.date, batch_id="race_plan_1")
            result["batches"].append(_public_audit(plan))
            first = pilot.batch(ENTRY_SHEET_ENDPOINT, args.date, batch_id="entry_sheet_1")
            result["batches"].append(_public_audit(first))
            if (
                first["complete"]
                and first["actual_items_day"] > 0
                and transport.count < transport.limit
            ):
                required = first["expected_pages"]
                if required <= transport.limit - transport.count:
                    second = pilot.batch(ENTRY_SHEET_ENDPOINT, args.date, batch_id="entry_sheet_2")
                    result["batches"].append(_public_audit(second))
            complete_sheets = [
                b
                for b in result["batches"]
                if b["endpoint"] == ENTRY_SHEET_ENDPOINT and b["complete"]
            ]
            observed = [
                b["completed_at_ms"] for b in result["batches"] if b["completed_at_ms"] is not None
            ]
            if observed:
                result["last_observation_completed_at_ms"] = max(observed)
            if (
                complete_sheets
                and plan["complete"]
                and plan["actual_items_day"] > 0
                and complete_sheets[-1]["actual_items_day"] > 0
            ):
                result["status"] = "capture_only_completed"
                last = complete_sheets[-1]
                result["last_observation_completed_at_ms"] = last["completed_at_ms"]
            if (
                plan["complete"]
                and complete_sheets
                and not (
                    plan["credential_reflected"] or complete_sheets[-1]["credential_reflected"]
                )
            ):
                schedule_by_race = {x.race_number: x for x in plan["items"]}
                sheet_races = set(int(k) for k in complete_sheets[-1]["race_counts"])
                for race_no in sorted(sheet_races & schedule_by_race.keys()):
                    schedule = schedule_by_race[race_no]
                    cutoff = schedule_cutoff(schedule, complete_sheets[-1]["completed_at_ms"])
                    if cutoff["margin_minutes"] is not None and cutoff["margin_minutes"] >= 0:
                        result["prospective_case"] = {
                            "race_number": race_no,
                            "source_schedule": {
                                "raceDt": schedule.race_date.isoformat(),
                                "raceNo": schedule.race_number,
                                "raceDs": schedule.distance_m,
                                "rccrsNm": schedule.meet_name,
                                "strtPargTm": schedule.scheduled_time,
                            },
                            "source_schedule_batch": "race_plan_1",
                            "entry_sheet_batch": complete_sheets[-1]["batch_id"],
                            "entry_count": complete_sheets[-1]["race_counts"][str(race_no)],
                            **cutoff,
                        }
                        break
                if result["prospective_case"] is None:
                    result["limitations"].append("no source-scheduled race before T-30 cutoff")
            else:
                result["limitations"].append("schedule/entry-sheet incomplete or no source rows")
            if len(complete_sheets) == 2:
                a, b = complete_sheets
                result["repeat_comparison"] = {
                    "raw_equal": a["raw_sha256"] == b["raw_sha256"],
                    "keys_equal": a["key_sha256"] == b["key_sha256"],
                    "values_equal": a["value_sha256"] == b["value_sha256"],
                    "interval_ms": b["completed_at_ms"] - a["completed_at_ms"],
                }
        finally:
            result["http_requests"] = transport.count
            pilot.close()
    result["limitations"].append(
        "API26_2 page completeness is not cancellation/correction completeness or F_t admission"
    )
    _write(root / "page_key_time_audit.json", result)
    manifest = {
        "protocol": "preflight_protocol.json",
        "audit": "page_key_time_audit.json",
        "journal": "capture_journal.jsonl" if store.journal.exists() else None,
        "raw_cas_private": "raw_private",
        "raw_policy": "0600 raw bytes in 0700 directory; credential reflections are not previewed",
        "source_sha256": protocol["source_sha256"],
        "output_sha256": {
            str(p.relative_to(root)): _sha(p) for p in root.rglob("*") if p.is_file()
        },
        "preserved_existing_artifacts": True,
        "new_external_sources": [RACE_PLAN_ENDPOINT, ENTRY_SHEET_ENDPOINT]
        if result["http_requests"]
        else [],
    }
    _write(root / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "status": result["status"],
                "http_requests": result["http_requests"],
                "target_date": args.date,
                "root": str(root),
            },
            ensure_ascii=False,
        )
    )


def _public_audit(batch: dict[str, Any]) -> dict[str, Any]:
    excluded = {"items"}
    if batch["credential_reflected"]:
        excluded.add("source_keys")
    return {k: v for k, v in batch.items() if k not in excluded}


if __name__ == "__main__":
    main()
