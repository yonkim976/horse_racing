"""Capture current official meet=1 API pages for a read-only Seoul audit."""

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
HISTORY_DB = ROOT / "data/research/seoul_backfill_20260915_v1/history.sqlite3"
TRIAL_DB = ROOT / "data/research/seoul_running_trials_20260915_v1/trials.sqlite3"
TRIAL_ENDPOINT = "/API20_1/ridingTestResult_1"
TRIAL_OPERATION = "ridingTestResult_1"


def items(payload: dict) -> list[dict]:
    container = response_body(payload).get("items") or {}
    value = container.get("item") if isinstance(container, dict) else None
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else []


def date8(value: object) -> str | None:
    digits = "".join(char for char in str(value or "") if char.isdigit())
    return digits[:8] if len(digits) >= 8 else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    datetime.strptime(args.as_of, "%Y%m%d")
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    year, month = args.as_of[:4], args.as_of[:6]
    definitions = {
        "race_result_year": (RACE_RESULT_WITH_SECTIONS_ENDPOINT,
                             RACE_RESULT_WITH_SECTIONS_OPERATION,
                             {"meet": 1, "rc_year": year, "_type": "json"}, "rcDate"),
        "trial_result_year": (TRIAL_ENDPOINT, TRIAL_OPERATION,
                              {"meet": 1, "tr_year": year, "_type": "json"}, "trainDate"),
        "daily_training_month": (DAILY_TRAINING_ENDPOINT, DAILY_TRAINING_OPERATION,
                                 {"meet": 1, "tr_month": month, "_type": "json"}, "trDate"),
        "start_training_month": (START_TRAINING_ENDPOINT, START_TRAINING_OPERATION,
                                 {"meet": 1, "tr_month": month, "_type": "json"}, "trDate"),
        "medical_year": (RACE_HORSE_CLINIC_ENDPOINT, RACE_HORSE_CLINIC_OPERATION,
                         {"meet": 1, "clinic_year": year, "_type": "json"}, "clinicDate"),
        "weight_month": (ENTRY_HORSE_WEIGHT_ENDPOINT, ENTRY_HORSE_WEIGHT_OPERATION,
                         {"meet": 1, "rc_month": month, "_type": "json"}, "rcDate"),
        "equipment_recent": (HORSE_EQUIPMENT_ENDPOINT, HORSE_EQUIPMENT_OPERATION,
                             {"meet": 1, "_type": "json"}, "rcDate"),
    }
    history = sqlite3.connect(f"file:{HISTORY_DB.resolve()}?mode=ro", uri=True)
    trial = sqlite3.connect(f"file:{TRIAL_DB.resolve()}?mode=ro", uri=True)
    snapshot = {
        "race_result_year": history.execute("SELECT max(race_date) FROM race").fetchone()[0],
        "trial_result_year": trial.execute("SELECT max(trial_date) FROM trial").fetchone()[0],
        "daily_training_month": history.execute(
            "SELECT max(event_date) FROM training_event WHERE source_type='horse_training'").fetchone()[0],
        "start_training_month": history.execute(
            "SELECT max(event_date) FROM training_event WHERE source_type='start_training'").fetchone()[0],
        "medical_year": history.execute("SELECT max(event_date) FROM medical_event").fetchone()[0],
        "weight_month": history.execute("SELECT max(race_date) FROM race_day_weight").fetchone()[0],
        "equipment_recent": history.execute("SELECT max(race_date) FROM entry_equipment").fetchone()[0],
    }
    history.close()
    trial.close()
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise RuntimeError("KRA service key unavailable")
    report = {
        "as_of_kst": f"{args.as_of[:4]}-{args.as_of[4:6]}-{args.as_of[6:]}",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "meet_requested": 1,
        "history_database": str(HISTORY_DB),
        "trial_database": str(TRIAL_DB),
        "datasets": {},
    }
    try:
        with KraApiClient(secret.get_secret_value(), base_url=settings.kra_api_base_url,
                          timeout_seconds=90) as client:
            for name, (endpoint, operation, params, field) in definitions.items():
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
                dates = [value for row in rows if (value := date8(row.get(field)))]
                cutoff = (snapshot[name] or "").replace("-", "")
                report["datasets"][name] = {
                    "endpoint": endpoint, "operation": operation,
                    "params_without_key": params, "pages": pages, "rows": len(rows),
                    "first_date": min(dates) if dates else None,
                    "last_date": max(dates) if dates else None,
                    "snapshot_last_date": snapshot[name],
                    "rows_after_snapshot_through_as_of": sum(cutoff < day <= args.as_of for day in dates),
                    "future_rows_after_as_of": sum(day > args.as_of for day in dates),
                    "meet_labels": sorted({clean for row in rows
                                           if (clean := str(row.get("meet") or "").strip())}),
                }
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__}
        (args.output / "freshness_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise SystemExit("Seoul freshness API audit failed; see key-redacted report") from None
    (args.output / "freshness_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: {key: value[key] for key in (
        "rows", "last_date", "snapshot_last_date", "rows_after_snapshot_through_as_of",
        "future_rows_after_as_of")}
        for name, value in report["datasets"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
