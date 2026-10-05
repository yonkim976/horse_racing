"""Capture result-free official scratches and jockey changes before publication."""

import argparse
import hashlib
import json
from pathlib import Path

from horse_racing.collectors.kra_api import (
    JOCKEY_CHANGE_ENDPOINT,
    JOCKEY_CHANGE_OPERATION,
    RACE_HORSE_CANCEL_ENDPOINT,
    RACE_HORSE_CANCEL_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    settings = get_settings()
    summary = []
    with KraApiClient(
        settings.data_go_kr_service_key.get_secret_value(),
        base_url=settings.kra_api_base_url,
        timeout_seconds=60,
    ) as client:
        for meet in (1, 2):
            for name, endpoint, operation in (
                ("scratches", RACE_HORSE_CANCEL_ENDPOINT, RACE_HORSE_CANCEL_OPERATION),
                ("jockey_changes", JOCKEY_CHANGE_ENDPOINT, JOCKEY_CHANGE_OPERATION),
            ):
                for page, fetched in enumerate(
                    client.iter_pages(
                        endpoint=endpoint,
                        operation=operation,
                        public_params={"meet": meet, "rc_date": args.date, "_type": "json"},
                        page_size=1000,
                        service_key_parameter="ServiceKey",
                    ),
                    1,
                ):
                    path = args.output / f"{name}_meet{meet}_page{page}.json"
                    path.write_bytes(fetched.body)
                    body = response_body(fetched.payload)
                    items = (body.get("items") or {}).get("item") or []
                    if isinstance(items, dict):
                        items = [items]
                    summary.append(
                        {
                            "name": name,
                            "meet": meet,
                            "records": len(items),
                            "observed_at_ms": fetched.retrieved_at_ms,
                            "path": path.name,
                            "sha256": hashlib.sha256(fetched.body).hexdigest(),
                        }
                    )
    (args.output / "manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
