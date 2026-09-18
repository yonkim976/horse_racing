"""Read-only comparison of early and recent native Jeju-horse race times.

Only aggregate records from races explicitly marked ``제`` are written. The KRA
annual endpoint can return mixed horse types; non-native rows are discarded in
memory and are never persisted by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path

from horse_racing.collectors.kra_api import (
    RACE_RESULT_WITH_SECTIONS_ENDPOINT,
    RACE_RESULT_WITH_SECTIONS_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.config import get_settings

YEARS = (2002, 2003, 2004, 2005, 2023, 2024, 2025)


def _items(body: dict) -> list[dict]:
    wrapped = body.get("items") or {}
    items = wrapped.get("item") or []
    if isinstance(items, dict):
        return [items]
    if not isinstance(items, list):
        raise ValueError("API items must be a list")
    return items


def _summary(times: list[float]) -> dict:
    return {
        "n": len(times),
        "median_seconds": statistics.median(times) if times else None,
        "mean_seconds": statistics.mean(times) if times else None,
        "min_seconds": min(times) if times else None,
        "max_seconds": max(times) if times else None,
    }


def audit() -> dict:
    settings = get_settings()
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ValueError("KRA API service key is unavailable")
    output = {
        "source": "KRA API4_3 raceResult_3",
        "scope_years": list(YEARS),
        "source_sha256_by_year": {},
        "races": [],
    }
    with KraApiClient(
        secret.get_secret_value(),
        base_url=settings.kra_api_base_url,
        timeout_seconds=60,
    ) as client:
        for year in YEARS:
            pages = list(
                client.iter_pages(
                    endpoint=RACE_RESULT_WITH_SECTIONS_ENDPOINT,
                    operation=RACE_RESULT_WITH_SECTIONS_OPERATION,
                    public_params={"meet": 2, "rc_year": str(year), "_type": "json"},
                    page_size=20_000,
                    service_key_parameter="ServiceKey",
                )
            )
            output["source_sha256_by_year"][str(year)] = [
                hashlib.sha256(page.body).hexdigest() for page in pages
            ]
            grouped: dict[tuple[int, int], list[dict]] = defaultdict(list)
            for page in pages:
                body = dict(response_body(page.payload))
                for item in _items(body):
                    if str(item.get("rank") or "").startswith("제"):
                        if item.get("meet") != "제주":
                            raise ValueError("Non-Jeju race in native Jeju group")
                        if int(item["rcDate"]) // 10_000 != year:
                            raise ValueError("Unexpected race year")
                        grouped[(int(item["rcDate"]), int(item["rcNo"]))].append(item)
            for (race_date, race_no), rows in sorted(grouped.items()):
                if len({(row["rank"], row["rcDist"]) for row in rows}) != 1:
                    raise ValueError("Inconsistent race classification")
                winners = [row for row in rows if str(row.get("ord")) == "1"]
                valid = [float(row["rcTime"]) for row in winners if row.get("rcTime")]
                if any(time <= 0 for time in valid):
                    raise ValueError(f"Nonpositive winning time: {race_date}/{race_no}")
                output["races"].append(
                    {
                        "date": race_date,
                        "race_no": race_no,
                        "distance_m": int(rows[0]["rcDist"]),
                        "rank": str(rows[0]["rank"]),
                        "field_rows": len(rows),
                        "winner_time_seconds": min(valid) if valid else None,
                        "weather": str(rows[0].get("weather") or ""),
                        "track": str(rows[0].get("track") or ""),
                    }
                )
            print(f"year={year} native_races={len(grouped)}", flush=True)
    races = output["races"]
    output["missing_winning_time_races"] = [
        {"date": r["date"], "race_no": r["race_no"], "distance_m": r["distance_m"]}
        for r in races
        if r["winner_time_seconds"] is None
    ]
    output["summaries"] = {
        "first_year_800m": _summary(
            [
                r["winner_time_seconds"]
                for r in races
                if r["date"] // 10_000 == 2002
                and r["distance_m"] == 800
                and r["winner_time_seconds"] is not None
            ]
        ),
        "early_2002_2005_800m": _summary(
            [
                r["winner_time_seconds"]
                for r in races
                if 2002 <= r["date"] // 10_000 <= 2005
                and r["distance_m"] == 800
                and r["winner_time_seconds"] is not None
            ]
        ),
        "recent_2023_2025_800m": _summary(
            [
                r["winner_time_seconds"]
                for r in races
                if 2023 <= r["date"] // 10_000 <= 2025
                and r["distance_m"] == 800
                and r["winner_time_seconds"] is not None
            ]
        ),
    }
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["summaries"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
