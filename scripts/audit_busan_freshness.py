"""Fetch fresh official meet=3 pages and compare them with the Busan snapshot.

Authenticated URLs and the service key are never serialized.  Results are
written to a new audit directory; the complete Busan database is read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from horse_racing.collectors.kra_api import (
    DAILY_TRAINING_ENDPOINT,
    DAILY_TRAINING_OPERATION,
    ENTRY_HORSE_WEIGHT_ENDPOINT,
    ENTRY_HORSE_WEIGHT_OPERATION,
    HORSE_EQUIPMENT_ENDPOINT,
    HORSE_EQUIPMENT_OPERATION,
    RACE_HORSE_CLINIC_ENDPOINT,
    RACE_HORSE_CLINIC_OPERATION,
    RACE_RESULT_WITH_SECTIONS_ENDPOINT,
    RACE_RESULT_WITH_SECTIONS_OPERATION,
    START_TRAINING_ENDPOINT,
    START_TRAINING_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parents[1]
COMPLETE_DB = ROOT / "data/research/busan_complete_db_20260916/busan_complete.sqlite3"
TRIAL_ENDPOINT = "/API20_1/ridingTestResult_1"
TRIAL_OPERATION = "ridingTestResult_1"


def items(payload: dict) -> list[dict]:
    container = response_body(payload).get("items") or {}
    value = container.get("item") if isinstance(container, dict) else None
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else []


def normalized_date(value: object) -> str | None:
    digits = "".join(char for char in str(value or "") if char.isdigit())
    return digits[:8] if len(digits) >= 8 else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    datetime.strptime(args.as_of, "%Y%m%d")
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)

    year, month = args.as_of[:4], args.as_of[:6]
    definitions = {
        "race_result_year": (
            RACE_RESULT_WITH_SECTIONS_ENDPOINT, RACE_RESULT_WITH_SECTIONS_OPERATION,
            {"meet": 3, "rc_year": year, "_type": "json"}, "rcDate"),
        "trial_result_year": (
            TRIAL_ENDPOINT, TRIAL_OPERATION,
            {"meet": 3, "tr_year": year, "_type": "json"}, "trainDate"),
        "daily_training_month": (
            DAILY_TRAINING_ENDPOINT, DAILY_TRAINING_OPERATION,
            {"meet": 3, "tr_month": month, "_type": "json"}, "trDate"),
        "start_training_month": (
            START_TRAINING_ENDPOINT, START_TRAINING_OPERATION,
            {"meet": 3, "tr_month": month, "_type": "json"}, "trDate"),
        "medical_year": (
            RACE_HORSE_CLINIC_ENDPOINT, RACE_HORSE_CLINIC_OPERATION,
            {"meet": 3, "clinic_year": year, "_type": "json"}, "clinicDate"),
        "weight_month": (
            ENTRY_HORSE_WEIGHT_ENDPOINT, ENTRY_HORSE_WEIGHT_OPERATION,
            {"meet": 3, "rc_month": month, "_type": "json"}, "rcDate"),
        "equipment_recent_default_window": (
            HORSE_EQUIPMENT_ENDPOINT, HORSE_EQUIPMENT_OPERATION,
            {"meet": 3, "_type": "json"}, "rcDate"),
    }
    db = sqlite3.connect(f"file:{COMPLETE_DB.resolve()}?mode=ro", uri=True)
    snapshot_max = {
        "race_result_year": db.execute("SELECT max(race_date) FROM race").fetchone()[0],
        "trial_result_year": db.execute("SELECT max(trial_date) FROM trial").fetchone()[0],
        "daily_training_month": db.execute(
            "SELECT max(event_date) FROM training_event WHERE source_type='horse_training'").fetchone()[0],
        "start_training_month": db.execute(
            "SELECT max(event_date) FROM training_event WHERE source_type='start_training'").fetchone()[0],
        "medical_year": db.execute("SELECT max(event_date) FROM medical_api_event").fetchone()[0],
        "weight_month": db.execute("SELECT max(race_date) FROM race_day_weight").fetchone()[0],
        "equipment_recent_default_window": db.execute(
            "SELECT max(race_date) FROM entry_equipment").fetchone()[0],
    }
    db.close()

    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise RuntimeError("KRA service key unavailable")
    report = {
        "as_of_kst": f"{args.as_of[:4]}-{args.as_of[4:6]}-{args.as_of[6:]}",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "database": str(COMPLETE_DB), "meet_requested": 3, "datasets": {},
    }
    try:
        with KraApiClient(secret.get_secret_value(),
                          base_url=settings.kra_api_base_url,
                          timeout_seconds=90) as client:
            for name, (endpoint, operation, params, date_field) in definitions.items():
                rows: list[dict] = []
                pages = []
                for page_number, fetched in enumerate(client.iter_pages(
                        endpoint=endpoint, operation=operation, public_params=params,
                        page_size=20_000, service_key_parameter="ServiceKey"), 1):
                    path = args.output / f"{name}_page_{page_number:04d}.json"
                    path.write_bytes(fetched.body)
                    batch = items(fetched.payload)
                    rows.extend(batch)
                    pages.append({
                        "path": path.name, "rows": len(batch),
                        "sha256": hashlib.sha256(fetched.body).hexdigest(),
                        "retrieved_at_ms": fetched.retrieved_at_ms,
                        "http_status_code": fetched.status_code,
                    })
                dates = [day for row in rows if (day := normalized_date(row.get(date_field)))]
                meet_labels = sorted({str(row.get("meet")) for row in rows if row.get("meet") is not None})
                maximum = max(dates) if dates else None
                snapshot = (snapshot_max[name] or "").replace("-", "")
                rows_after_snapshot = sum(day > snapshot for day in dates) if snapshot else len(dates)
                report["datasets"][name] = {
                    "endpoint": endpoint, "operation": operation,
                    "params_without_key": params, "pages": pages, "rows": len(rows),
                    "first_date": min(dates) if dates else None,
                    "last_date": maximum, "meet_labels": meet_labels,
                    "snapshot_last_date": snapshot_max[name],
                    "rows_after_snapshot_last_date": rows_after_snapshot,
                    "is_snapshot_current_by_max_date": maximum is None or maximum <= snapshot,
                }
    except Exception as exc:
        # httpx exceptions may render authenticated URLs. Persist only class name.
        report["error"] = {"type": type(exc).__name__}
        (args.output / "freshness_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise SystemExit("Freshness API audit failed; see key-redacted report") from None

    (args.output / "freshness_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: {"rows": value["rows"], "last_date": value["last_date"],
                                  "snapshot_last_date": value["snapshot_last_date"],
                                  "rows_after_snapshot_last_date": value["rows_after_snapshot_last_date"]}
                      for name, value in report["datasets"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
