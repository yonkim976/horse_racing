"""Recheck official entry sheets for race-result rows missing trainer/owner IDs.

The saved response contains the KRA payload only. Authentication parameters and
the fully constructed request URL are never written to disk.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import httpx

from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
OUT = Path(__file__).resolve().parent
RAW = OUT / "raw_api26_recheck"
ENDPOINT = "https://apis.data.go.kr/B551015/API26_2/entrySheet_2"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def items_from(payload: dict) -> tuple[int, list[dict]]:
    response = payload.get("response", {})
    header = response.get("header", {})
    body = response.get("body", {})
    if str(header.get("resultCode")) != "00":
        raise ValueError(f"KRA API26 response failed: {header.get('resultCode')}")
    box = body.get("items")
    items = box.get("item", []) if isinstance(box, dict) else box or []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise TypeError("KRA API26 items is not a list")
    total = int(body.get("totalCount") or 0)
    if len(items) != total:
        raise ValueError(f"KRA API26 pagination incomplete: {len(items)} != {total}")
    return total, items


def main() -> None:
    key_wrapper = get_settings().data_go_kr_service_key
    if key_wrapper is None:
        raise RuntimeError("KRA service key is not configured")
    key = key_wrapper.get_secret_value()
    con = duckdb.connect(str(DB), read_only=True)
    rows = con.execute(
        "SELECT source_meet, result_date, result_race_no, horse_program_no_raw, "
        "horse_id_raw, horse_name_raw, source_file, source_item_index "
        "FROM confirmed_runners WHERE trainer_id_raw IS NULL AND owner_id_raw IS NULL "
        "ORDER BY result_date, source_meet, result_race_no, horse_program_no_raw"
    ).fetchall()
    con.close()
    if len(rows) != 38:
        raise ValueError(f"Expected 38 source gaps, got {len(rows)}")
    requests = sorted({(meet, date) for meet, date, *_ in rows})
    if not all(meet in {"1", "3"} and re.fullmatch(r"\d{8}", date) for meet, date in requests):
        raise ValueError("Unexpected meet or date in source gap set")

    RAW.mkdir(parents=True, exist_ok=True)
    payloads: dict[tuple[str, str], tuple[list[dict], str, str, int]] = {}
    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        for meet, date in requests:
            params = {
                "ServiceKey": key,
                "meet": int(meet),
                "rc_date": date,
                "_type": "json",
                "pageNo": 1,
                "numOfRows": 1000,
            }
            for attempt in range(3):
                try:
                    response = client.get(ENDPOINT, params=params)
                    response.raise_for_status()
                    raw = response.content
                    if key.encode() in raw or "ServiceKey" in raw.decode("utf-8", errors="ignore"):
                        raise ValueError("Credential material in API response; refusing to save")
                    payload = response.json()
                    total, items = items_from(payload)
                    break
                except (httpx.HTTPError, ValueError):
                    if attempt == 2:
                        raise
                    time.sleep(2 * (attempt + 1))
            path = RAW / f"meet_{meet}_date_{date}.json"
            path.write_bytes(raw)
            payloads[(meet, date)] = (items, path.relative_to(ROOT).as_posix(), digest(raw), total)
            time.sleep(0.15)

    observations = []
    for meet, date, race_no, chul_no, horse_id, horse_name, result_file, result_idx in rows:
        items, path, sha, total = payloads[(meet, date)]
        matches = [
            (index, item)
            for index, item in enumerate(items)
            if str(item.get("rcDate")) == date
            and str(item.get("rcNo")) == race_no
            and str(item.get("chulNo")) == chul_no
            and str(item.get("hrNo")) == horse_id
        ]
        if len(matches) != 1:
            raise ValueError(f"API26 exact-key match count {len(matches)} for {meet}/{date}/{race_no}/{chul_no}/{horse_id}")
        index, item = matches[0]
        observations.append({
            "meet": meet,
            "race_date": date,
            "race_no": race_no,
            "horse_program_no": chul_no,
            "horse_id": horse_id,
            "horse_name_api4_3": horse_name,
            "api4_3_source_file": result_file,
            "api4_3_source_item_index_zero_based": result_idx,
            "api26_recheck_source_file": path,
            "api26_recheck_sha256": sha,
            "api26_recheck_total_count": total,
            "api26_recheck_item_index_zero_based": index,
            "api26_trainer_id": item.get("trNo"),
            "api26_trainer_name": item.get("trName"),
            "api26_owner_id": item.get("owNo"),
            "api26_owner_name": item.get("owName"),
        })
    result = {
        "source": "KRA API26_2/entrySheet_2",
        "rechecked_at_utc": datetime.now(timezone.utc).isoformat(),
        "request_public_parameters": ["meet", "rc_date", "_type=json", "pageNo=1", "numOfRows=1000"],
        "request_count": len(requests),
        "target_row_count": len(observations),
        "all_targets_exactly_once": True,
        "observations": observations,
    }
    (OUT / "api26_recheck_observations.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "requests": len(requests),
        "targets": len(observations),
        "with_trainer_id": sum(o["api26_trainer_id"] is not None for o in observations),
        "with_owner_id": sum(o["api26_owner_id"] is not None for o in observations),
    }))


if __name__ == "__main__":
    main()
