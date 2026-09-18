"""Fetch result-free official inputs used to audit a Jeju live forecast."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from horse_racing.collectors.kra_api import (
    DAILY_TRAINING_ENDPOINT,
    DAILY_TRAINING_OPERATION,
    GATE_ENTRY_SHEET_ENDPOINT,
    GATE_ENTRY_SHEET_OPERATION,
    HORSE_EQUIPMENT_ENDPOINT,
    HORSE_EQUIPMENT_OPERATION,
    JOCKEY_CHANGE_ENDPOINT,
    JOCKEY_CHANGE_OPERATION,
    RACE_HORSE_CANCEL_ENDPOINT,
    RACE_HORSE_CANCEL_OPERATION,
    RACE_HORSE_CLINIC_ENDPOINT,
    RACE_HORSE_CLINIC_OPERATION,
    START_TRAINING_ENDPOINT,
    START_TRAINING_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings


def items(payload: dict) -> list[dict]:
    container = response_body(payload).get("items") or {}
    value = container.get("item") if isinstance(container, dict) else None
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="20260917")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    datetime.strptime(args.date, "%Y%m%d")
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)

    definitions = {
        "training_month": (
            DAILY_TRAINING_ENDPOINT,
            DAILY_TRAINING_OPERATION,
            {"meet": 2, "tr_month": args.date[:6], "_type": "json"},
            "ServiceKey",
        ),
        "start_training_month": (
            START_TRAINING_ENDPOINT,
            START_TRAINING_OPERATION,
            {"meet": 2, "tr_month": args.date[:6], "_type": "json"},
            "ServiceKey",
        ),
        "medical_year": (
            RACE_HORSE_CLINIC_ENDPOINT,
            RACE_HORSE_CLINIC_OPERATION,
            {"meet": 2, "clinic_year": args.date[:4], "_type": "json"},
            "ServiceKey",
        ),
        "jockey_changes": (
            JOCKEY_CHANGE_ENDPOINT,
            JOCKEY_CHANGE_OPERATION,
            {"meet": 2, "rc_date": args.date, "_type": "json"},
            "ServiceKey",
        ),
        "scratches": (
            RACE_HORSE_CANCEL_ENDPOINT,
            RACE_HORSE_CANCEL_OPERATION,
            {"meet": 2, "rc_date": args.date, "_type": "json"},
            "ServiceKey",
        ),
        "equipment": (
            HORSE_EQUIPMENT_ENDPOINT,
            HORSE_EQUIPMENT_OPERATION,
            {"meet": 2, "rc_date": args.date, "_type": "json"},
            "ServiceKey",
        ),
        "gate_card": (
            GATE_ENTRY_SHEET_ENDPOINT,
            GATE_ENTRY_SHEET_OPERATION,
            {"rccrs_cd": 2, "race_dt": args.date, "_type": "json"},
            "serviceKey",
        ),
    }
    settings = get_settings()
    if settings.data_go_kr_service_key is None:
        raise RuntimeError("KRA service key unavailable")
    manifest = {"target_date": args.date, "result_endpoints_called": [], "datasets": {}}
    with KraApiClient(
        settings.data_go_kr_service_key.get_secret_value(),
        base_url=settings.kra_api_base_url,
        timeout_seconds=60,
    ) as client:
        for name, (endpoint, operation, params, key_name) in definitions.items():
            pages = []
            total_rows = 0
            for page_number, fetched in enumerate(
                client.iter_pages(
                    endpoint=endpoint,
                    operation=operation,
                    public_params=params,
                    page_size=20_000,
                    service_key_parameter=key_name,
                ),
                1,
            ):
                path = args.output / f"{name}_page_{page_number}.json"
                path.write_bytes(fetched.body)
                row_count = len(items(fetched.payload))
                total_rows += row_count
                pages.append(
                    {
                        "path": path.name,
                        "sha256": hashlib.sha256(fetched.body).hexdigest(),
                        "rows": row_count,
                        "retrieved_at_ms": fetched.retrieved_at_ms,
                        "http_status_code": fetched.status_code,
                    }
                )
            manifest["datasets"][name] = {"rows": total_rows, "pages": pages}

    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
