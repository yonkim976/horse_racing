"""Bounded historical positive control for the E8-B official-source pilot.

Only first pages of two allowed endpoints are requested. Never opens the
operating database, result endpoints, or post-May-2026 historical material.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from horse_racing.analysis.confirmed_starter_e8b import BudgetTransport, CaptureStore, PilotCapture
from horse_racing.collectors.kra_api import ENTRY_SHEET_ENDPOINT, RACE_PLAN_ENDPOINT
from horse_racing.config import get_settings
from horse_racing.parsers.entry_sheet import parse_entry_sheet_page
from horse_racing.parsers.race_day import RacePlanItem, parse_items

ROOT = Path("data/experiments/confirmed_starter_e8b_source_control_20260913_attempt2")
DATE = "20260517"
KST = timezone(timedelta(hours=9))
EXISTING = {
    ENTRY_SHEET_ENDPOINT: Path(
        "data/raw/kra/entry_sheet/2026/05/17/meet_1/run_608/"
        "page_0001_1787319601029_6c4735c8b869.json"
    ),
    RACE_PLAN_ENDPOINT: Path(
        "data/raw/kra/race_plan/2026/05/17/meet_1/run_607/page_0001_1787319600228_6ef89900f4fd.json"
    ),
}
EXPECTED_EXISTING_SHA = {
    ENTRY_SHEET_ENDPOINT: "6c4735c8b8694cb4b521c93344c75362a8a44e4cb0c5303f6015659f44bfa716",
    RACE_PLAN_ENDPOINT: "6ef89900f4fd337e9618ff457b3fa550419fd0ba073b6e533ebb767fde7e533e",
}
SOURCES = [
    Path("scripts/run_confirmed_starter_e8b_source_control.py"),
    Path("src/horse_racing/analysis/confirmed_starter_e8b.py"),
    Path("src/horse_racing/collectors/kra_api.py"),
    Path("src/horse_racing/parsers/entry_sheet.py"),
    Path("src/horse_racing/parsers/race_day.py"),
    Path("src/horse_racing/config.py"),
]


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _write(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")


def _items(endpoint: str, body: bytes) -> list[Any]:
    payload = json.loads(body)
    return (
        parse_entry_sheet_page(payload).items
        if endpoint == ENTRY_SHEET_ENDPOINT
        else parse_items(payload, RacePlanItem)
    )


def source_keys(endpoint: str, items: list[Any]) -> list[tuple[Any, ...]]:
    if endpoint == ENTRY_SHEET_ENDPOINT:
        return sorted(
            (
                x.meet_name,
                x.race_date.strftime("%Y%m%d"),
                x.race_number,
                x.horse_number,
                x.horse_id,
            )
            for x in items
        )
    return sorted((x.meet_name, x.race_date.strftime("%Y%m%d"), x.race_number) for x in items)


def compare_first_page(
    endpoint: str, old_items: list[Any], new_items: list[Any], *, new_meta: dict[str, int] | None
) -> dict[str, Any]:
    old_keys = source_keys(endpoint, old_items)
    new_keys = source_keys(endpoint, new_items)
    old_set, new_set = set(old_keys), set(new_keys)
    expected_meet = {"서울", "SEOUL", "Seoul"}
    identity_valid = all(k[0] in expected_meet and k[1] == DATE for k in old_keys + new_keys)
    return {
        "old_first_page_items": len(old_items),
        "new_first_page_items": len(new_items),
        "new_totalCount_day": new_meta["totalCount"] if new_meta is not None else None,
        "new_pageNo": new_meta["pageNo"] if new_meta is not None else None,
        "new_numOfRows": new_meta["numOfRows"] if new_meta is not None else None,
        "old_source_keys_sha256": _sha(json.dumps(old_keys, ensure_ascii=False).encode()),
        "new_source_keys_sha256": _sha(json.dumps(new_keys, ensure_ascii=False).encode()),
        "old_source_keys": [list(key) for key in old_keys],
        "new_source_keys": [list(key) for key in new_keys],
        "added_keys": [list(key) for key in sorted(new_set - old_set)],
        "removed_keys": [list(key) for key in sorted(old_set - new_set)],
        "duplicate_old_keys": sum(count - 1 for count in Counter(old_keys).values()),
        "duplicate_new_keys": sum(count - 1 for count in Counter(new_keys).values()),
        "date_meet_identity_valid": identity_valid,
        "first_page_nonempty": bool(new_items),
        "complete_dataset": "not_assessed_first_page_only",
        "retroactive_observation": True,
        "T_minus_30_claim": False,
    }


def main() -> None:
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    key = secret.get_secret_value() if secret is not None else ""
    # The original raw evidence and its fixed hashes are checked before any HTTP send.
    old_raw = {endpoint: path.read_bytes() for endpoint, path in EXISTING.items()}
    for endpoint, body in old_raw.items():
        if _sha(body) != EXPECTED_EXISTING_SHA[endpoint]:
            raise SystemExit(f"existing control raw hash mismatch: {endpoint}")
    old_items = {endpoint: _items(endpoint, body) for endpoint, body in old_raw.items()}
    if not all(old_items.values()):
        raise SystemExit("preselected control evidence is empty")

    store = CaptureStore(ROOT)
    snapshot = ROOT / "source_snapshot"
    snapshot.mkdir()
    source_manifest: dict[str, Any] = {}
    for path in SOURCES:
        body = path.read_bytes()
        if key and key.encode() in body:
            raise SystemExit("credential occurs in proposed source snapshot")
        destination = snapshot / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        if destination.read_bytes() != body:
            raise SystemExit("source snapshot differs from execution source")
        source_manifest[str(path)] = {
            "snapshot": str(destination.relative_to(ROOT)),
            "sha256": _sha(body),
            "bytes": len(body),
        }
    public = {
        ENTRY_SHEET_ENDPOINT: {
            "meet": 1,
            "rc_date": DATE,
            "_type": "json",
            "pageNo": 1,
            "numOfRows": 1000,
        },
        RACE_PLAN_ENDPOINT: {
            "rccrs_cd": 1,
            "race_dt": DATE,
            "_type": "json",
            "pageNo": 1,
            "numOfRows": 1000,
        },
    }
    _write(
        ROOT / "preflight_protocol.json",
        {
            "created_at_kst": datetime.now(KST).isoformat(),
            "control_date": DATE,
            "meet": 1,
            "endpoints_public_params": public,
            "existing_raw_evidence": {
                endpoint: {
                    "path": str(EXISTING[endpoint]),
                    "sha256": EXPECTED_EXISTING_SHA[endpoint],
                    "first_page_items": len(old_items[endpoint]),
                }
                for endpoint in public
            },
            "request_budget_new": 4,
            "request_budget_cumulative_with_E8B": 9,
            "max_attempts_per_endpoint": 2,
            "first_page_only": True,
            "redirects_followed": False,
            "credential_present": bool(key.strip()),
            "source_manifest": source_manifest,
        },
    )

    result: dict[str, Any] = {
        "status": "inconclusive",
        "control_date": DATE,
        "http_requests_new": 0,
        "http_requests_cumulative_with_E8B": 5,
        "endpoints": {},
        "operating_model_status": "not_activated",
        "F_t_eligibility": "unverified",
        "limitations": [],
    }
    if not key.strip():
        result["limitations"].append("service credential unavailable")
    else:
        transport = BudgetTransport(httpx.HTTPTransport(retries=0), limit=4)
        pilot = PilotCapture(
            store,
            service_key=key,
            base_url=settings.kra_api_base_url,
            transport=transport,
            timeout_seconds=min(settings.http_timeout_seconds, 10.0),
        )
        try:
            for endpoint in (ENTRY_SHEET_ENDPOINT, RACE_PLAN_ENDPOINT):
                page = pilot.page(
                    endpoint, public[endpoint], batch="control_" + endpoint.split("/")[1]
                )
                comparison = compare_first_page(
                    endpoint, old_items[endpoint], page.get("items", []), new_meta=page["meta"]
                )
                comparison.update(
                    {
                        "endpoint": endpoint,
                        "http_status": page["status_code"],
                        "failure": page["failure"],
                        "body_sha256": page["body_sha256"],
                        "body_bytes": page["body_bytes"],
                        "requested_at_ms": page["requested_at_ms"],
                        "received_at_ms": page["received_at_ms"],
                        "parsed_at_ms": page["parsed_at_ms"],
                        "commit_completed_at_ms": page["commit_completed_at_ms"],
                        "credential_reflected": page["credential_reflected"],
                    }
                )
                if page["credential_reflected"]:
                    for field in (
                        "old_source_keys",
                        "new_source_keys",
                        "added_keys",
                        "removed_keys",
                    ):
                        comparison[field] = "redacted_credential_reflection"
                result["endpoints"][endpoint] = comparison
            if any(
                value["first_page_nonempty"] and value["failure"] is None
                for value in result["endpoints"].values()
            ):
                result["status"] = "positive_control_observed"
        finally:
            pilot.close()
            result["http_requests_new"] = transport.count
            result["http_requests_cumulative_with_E8B"] = 5 + transport.count
    result["limitations"].append(
        "Historical backfill is not a T-30 observation; "
        "first pages do not certify the complete date"
    )
    _write(ROOT / "control_comparison.json", result)
    output_manifest = {
        "source_manifest": source_manifest,
        "preserved_existing_E8B": True,
        "new_files_sha256": {
            str(path.relative_to(ROOT)): _sha(path.read_bytes())
            for path in ROOT.rglob("*")
            if path.is_file()
        },
        "credential_value_saved": False,
    }
    _write(ROOT / "manifest.json", output_manifest)
    print(
        json.dumps(
            {
                "status": result["status"],
                "http_requests_new": result["http_requests_new"],
                "root": str(ROOT),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
