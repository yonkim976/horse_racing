"""Fetch only five target Jeju-native entry rows to arbitrate owner-name boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from horse_racing.collectors.kra_api import ENTRY_SHEET_ENDPOINT, ENTRY_SHEET_OPERATION, KraApiClient, response_body
from horse_racing.config import get_settings

TARGETS = (
    ("20180119", 3, "3015134", 1),
    ("20180203", 1, "3016539", 4),
    ("20180224", 6, "3017320", 3),
    ("20220311", 5, "3102504", 5),
    ("20240525", 3, "3018281", 9),
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    key = get_settings().data_go_kr_service_key
    if key is None:
        raise RuntimeError("KRA service key unavailable")
    records = []
    with KraApiClient(key.get_secret_value(), timeout_seconds=60) as client:
        for day, race_number, horse_id, horse_number in TARGETS:
            matches = []
            pages = []
            for page in client.iter_pages(
                endpoint=ENTRY_SHEET_ENDPOINT, operation=ENTRY_SHEET_OPERATION,
                public_params={"meet": 2, "rc_date": day, "_type": "json"},
                page_size=1000, service_key_parameter="ServiceKey",
            ):
                body = response_body(page.payload)
                items = (body.get("items") or {}).get("item") or []
                items = [items] if isinstance(items, dict) else items
                pages.append({"request_url_without_key": page.source_url,
                              "response_sha256": hashlib.sha256(page.body).hexdigest(),
                              "response_bytes": len(page.body), "status_code": page.status_code,
                              "requested_at_ms": page.requested_at_ms,
                              "retrieved_at_ms": page.retrieved_at_ms,
                              "total_count": int(body.get("totalCount") or 0),
                              "returned_rows": len(items)})
                matches.extend(row for row in items
                               if str(row.get("hrNo") or "") == horse_id
                               and str(row.get("rcNo") or "") == str(race_number)
                               and str(row.get("chulNo") or "") == str(horse_number)
                               and str(row.get("rank") or "").startswith("제"))
            if len(matches) != 1:
                raise ValueError(f"Expected one native target row for {day} R{race_number} {horse_id}")
            row = matches[0]
            records.append({"meet": 2, "race_date": day, "race_number": race_number,
                            "horse_id": horse_id, "horse_number": horse_number,
                            "rank": row["rank"], "owNo_raw": row.get("owNo"),
                            "owNo": str(row.get("owNo")).zfill(6), "owName": row.get("owName"),
                            "source_pages": pages})
    path = args.output / "five_native_entry_sheet_rows.json"
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"target_rows": len(records), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
