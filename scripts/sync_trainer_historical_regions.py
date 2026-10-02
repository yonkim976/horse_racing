"""Store official regional evidence for former KRA trainers already in the DB.

Only API rows with a real end date are eligible. Presence on the KRA retired
list is recorded separately, because that list excludes short-term and invited
international trainers. Dry-run unless --apply-local/--apply-remote is passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text

from horse_racing.config import get_settings

KST = ZoneInfo("Asia/Seoul")
API_URL = "https://apis.data.go.kr/B551015/API308/trainerInfo"
RETIRED_LIST_URL = "https://race.kra.co.kr/trainer/profileTrainerListRetire.do"
LOCAL_DATABASE_URL = "sqlite:///data/horse_racing.sqlite3"
REGIONS = {1: ("SEOUL", "서울"), 2: ("JEJU", "제주"), 3: ("YEONGNAM", "영남")}


@dataclass(frozen=True)
class FormerTrainerRegion:
    kra_trainer_id: str
    name_ko: str
    region_code: str
    source_end_date: date
    retired_list_confirmed: bool
    source_url: str
    source_sha256: str


def _parse_date(value: object) -> date:
    raw = str(value)
    if not re.fullmatch(r"\d{8}", raw):
        raise ValueError(f"Unexpected KRA end date format: {raw}")
    return date.fromisoformat(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")


def parse_retired_list(payload: bytes, meet_code: int) -> dict[str, str]:
    soup = BeautifulSoup(payload, "html.parser")
    trainers: dict[str, str] = {}
    for row in soup.select("table tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.select("td")]
        link = row.select_one("a[onclick*=goPage2]")
        if not cells or not cells[0].isdigit() or link is None:
            continue
        match = re.search(r"goPage2\('([0-9]{6})'\)", link.get("onclick", ""))
        if match is None or len(cells) < 5 or match.group(1) in trainers:
            raise ValueError(f"Malformed KRA retired list for meet {meet_code}")
        trainers[match.group(1)] = cells[1]
    if not 15 <= len(trainers) <= 150:
        raise ValueError(f"Unexpected retired-list count for meet {meet_code}: {len(trainers)}")
    return trainers


def parse_api(payload: bytes, meet_code: int, today: date) -> list[dict]:
    response = json.loads(payload)["response"]
    if response["header"]["resultCode"] != "00":
        raise ValueError(f"Trainer API rejected meet {meet_code}: {response['header']}")
    body = response["body"]
    items = body["items"]["item"]
    if isinstance(items, dict):
        items = [items]
    if len(items) != int(body["totalCount"]):
        raise ValueError(f"Trainer API pagination incomplete for meet {meet_code}")
    former: list[dict] = []
    for item in items:
        if item["meet"] != REGIONS[meet_code][1]:
            raise ValueError(f"Unexpected API region: {item['meet']}")
        if str(item.get("spDate", "")).strip() == "-":
            continue
        trainer_id = str(item["trNo"])
        if not re.fullmatch(r"\d{6}", trainer_id):
            raise ValueError(f"Unexpected trainer ID: {trainer_id}")
        end_date = _parse_date(item["spDate"])
        if end_date > today:
            raise ValueError(f"Future trainer end date: {trainer_id}")
        former.append({"id": trainer_id, "name": item["trName"], "end_date": end_date})
    if len({item["id"] for item in former}) != len(former):
        raise ValueError(f"Duplicate ended trainer ID for meet {meet_code}")
    return former


def fetch_sources(
    today: date,
) -> tuple[list[FormerTrainerRegion], dict[int, bytes], dict[int, bytes]]:
    secret = get_settings().data_go_kr_service_key
    if secret is None:
        raise ValueError("DATA_GO_KR_SERVICE_KEY is required")
    rows: list[FormerTrainerRegion] = []
    raw_api: dict[int, bytes] = {}
    raw_web: dict[int, bytes] = {}
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for meet_code in REGIONS:
            api_response = client.get(
                API_URL,
                params={
                    "serviceKey": secret.get_secret_value(),
                    "meet": meet_code,
                    "pageNo": 1,
                    "numOfRows": 500,
                    "_type": "json",
                },
            )
            api_response.raise_for_status()
            web_response = client.get(RETIRED_LIST_URL, params={"meet": meet_code})
            web_response.raise_for_status()
            raw_api[meet_code] = api_response.content
            raw_web[meet_code] = web_response.content
            former = parse_api(api_response.content, meet_code, today)
            retired_list = parse_retired_list(web_response.content, meet_code)
            api_by_id = {item["id"]: item for item in former}
            for trainer_id, name in retired_list.items():
                if trainer_id not in api_by_id or api_by_id[trainer_id]["name"] != name:
                    raise ValueError(f"Retired list/API mismatch for {trainer_id}")
            for item in former:
                rows.append(
                    FormerTrainerRegion(
                        kra_trainer_id=item["id"],
                        name_ko=item["name"],
                        region_code=REGIONS[meet_code][0],
                        source_end_date=item["end_date"],
                        retired_list_confirmed=item["id"] in retired_list,
                        source_url=f"{API_URL}?meet={meet_code}",
                        source_sha256=hashlib.sha256(api_response.content).hexdigest(),
                    )
                )
    if len({item.kra_trainer_id for item in rows}) != len(rows):
        raise ValueError("Trainer ID occurs in multiple historical regions; inspect manually")
    return rows, raw_api, raw_web


def matched_rows(
    connection, rows: list[FormerTrainerRegion]
) -> list[tuple[int, FormerTrainerRegion]]:
    existing = {
        row.kra_trainer_id: (row.id, row.name_ko)
        for row in connection.execute(text("select id, kra_trainer_id, name_ko from trainers"))
    }
    matched: list[tuple[int, FormerTrainerRegion]] = []
    for row in rows:
        if row.kra_trainer_id not in existing:
            continue
        trainer_id, name = existing[row.kra_trainer_id]
        if name != row.name_ko:
            raise ValueError(f"Trainer ID/name conflict: {row.kra_trainer_id}")
        matched.append((trainer_id, row))
    if not 100 <= len(matched) <= 200:
        raise ValueError(f"Unexpected number of matched former trainers: {len(matched)}")
    return matched


def write_rows(database_url: str, rows: list[FormerTrainerRegion], observed_at: datetime) -> int:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            matched = matched_rows(connection, rows)
            params = [
                {
                    "trainer_id": trainer_id,
                    "region_code": row.region_code,
                    "observed_on": observed_at.date(),
                    "source_end_date": row.source_end_date,
                    "retired_list_confirmed": row.retired_list_confirmed,
                    "observed_at_ms": int(observed_at.timestamp() * 1000),
                    "source_url": row.source_url,
                    "source_sha256": row.source_sha256,
                }
                for trainer_id, row in matched
            ]
            connection.execute(
                text(
                    """insert into trainer_historical_regions
                         (trainer_id,region_code,observed_on,source_end_date,
                          retired_list_confirmed,observed_at_ms,source_url,source_sha256)
                       values
                         (:trainer_id,:region_code,:observed_on,:source_end_date,
                          :retired_list_confirmed,:observed_at_ms,:source_url,:source_sha256)
                       on conflict (trainer_id,region_code,observed_on) do update set
                         source_end_date=excluded.source_end_date,
                         retired_list_confirmed=excluded.retired_list_confirmed,
                         observed_at_ms=excluded.observed_at_ms,
                         source_url=excluded.source_url,
                         source_sha256=excluded.source_sha256"""
                ),
                params,
            )
            count = connection.execute(
                text("select count(*) from trainer_historical_regions where observed_on=:day"),
                {"day": observed_at.date()},
            ).scalar_one()
            if count != len(matched):
                raise ValueError(f"Historical region count mismatch: {count} != {len(matched)}")
        return count
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-local", action="store_true")
    parser.add_argument("--apply-remote", action="store_true")
    args = parser.parse_args()
    observed_at = datetime.now(KST)
    rows, raw_api, raw_web = fetch_sources(observed_at.date())
    targets = [("local", LOCAL_DATABASE_URL, args.apply_local)]
    if args.apply_remote or not args.apply_local:
        targets.append(("remote", get_settings().database_url, args.apply_remote))
    for label, database_url, apply in targets:
        engine = create_engine(database_url)
        with engine.connect() as connection:
            matched = matched_rows(connection, rows)
        engine.dispose()
        confirmed = sum(row.retired_list_confirmed for _, row in matched)
        print(
            f"{label}: API-ended trainers matched={len(matched)} "
            f"official-retired-list={confirmed} API-ended-only={len(matched) - confirmed}"
        )
        if apply:
            print(f"{label}: stored {write_rows(database_url, rows, observed_at)} region rows")
    if args.apply_local or args.apply_remote:
        directory = Path("data/raw/kra_retired_trainer_regions") / observed_at.strftime("%Y-%m-%d")
        directory.mkdir(parents=True, exist_ok=True)
        for meet_code in REGIONS:
            (directory / f"api_meet_{meet_code}.json").write_bytes(raw_api[meet_code])
            (directory / f"retired_meet_{meet_code}.html").write_bytes(raw_web[meet_code])
        print(f"Saved official source responses: {directory}")


if __name__ == "__main__":
    main()
