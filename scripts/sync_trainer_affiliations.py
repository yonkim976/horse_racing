"""Observe KRA's current trainer-to-stable-part listing and store dated snapshots.

Dry-run by default. --apply-local and --apply-remote are explicit independent writes.
Horse/trainer historical race rows and horse activity flags are never changed.
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
SOURCE = "https://race.kra.co.kr/trainer/profileTrainerList.do"
API_SOURCE = "https://apis.data.go.kr/B551015/API308/trainerInfo"
LOCAL_DATABASE_URL = "sqlite:///data/horse_racing.sqlite3"


@dataclass(frozen=True)
class Affiliation:
    kra_trainer_id: str
    name_ko: str
    meet_code: int
    stable_part: int
    stats_as_of: date | None
    source_url: str
    source_sha256: str


def parse_listing(html: bytes, meet_code: int) -> list[Affiliation]:
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)
    stats_match = re.search(r"전적\s*기준일자\s*:\s*(\d{4}/\d{2}/\d{2})", page_text)
    stats_as_of = (
        date.fromisoformat(stats_match.group(1).replace("/", "-")) if stats_match else None
    )
    source_url = f"{SOURCE}?meet={meet_code}"
    source_sha256 = hashlib.sha256(html).hexdigest()
    result: list[Affiliation] = []
    for row in soup.select("table tr"):
        link = row.select_one("a[onclick*=goPage2]")
        if link is None:
            continue
        id_match = re.fullmatch(
            r"\s*(?:javascript:)?goPage2\('([0-9]{6})'\)\s*;?\s*",
            link.get("onclick", ""),
        )
        cells = [cell.get_text(" ", strip=True) for cell in row.select("td")]
        if id_match is None or len(cells) < 3:
            raise ValueError(f"Malformed trainer row for meet {meet_code}")
        part_match = re.fullmatch(r"(\d{1,2})조", cells[2])
        if part_match is None or not link.get_text(strip=True):
            raise ValueError(f"Missing stable part/name for trainer {id_match.group(1)}")
        result.append(
            Affiliation(
                kra_trainer_id=id_match.group(1),
                name_ko=link.get_text(" ", strip=True),
                meet_code=meet_code,
                stable_part=int(part_match.group(1)),
                stats_as_of=stats_as_of,
                source_url=source_url,
                source_sha256=source_sha256,
            )
        )
    if not 10 <= len(result) <= 70:
        raise ValueError(f"Unexpected trainer count for meet {meet_code}: {len(result)}")
    if len({item.kra_trainer_id for item in result}) != len(result):
        raise ValueError(f"Duplicate trainer ID in meet {meet_code}")
    return result


def fetch_listings() -> tuple[list[Affiliation], dict[int, bytes]]:
    all_rows: list[Affiliation] = []
    raw: dict[int, bytes] = {}
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for meet_code in (1, 2, 3):
            response = client.get(SOURCE, params={"meet": meet_code})
            response.raise_for_status()
            raw[meet_code] = response.content
            all_rows.extend(parse_listing(response.content, meet_code))
    if len({item.kra_trainer_id for item in all_rows}) != len(all_rows):
        raise ValueError("Trainer ID appears in more than one meet")
    return all_rows, raw


def parse_api_response(payload: bytes, meet_code: int) -> list[Affiliation]:
    response = json.loads(payload)["response"]
    if response["header"]["resultCode"] != "00":
        raise ValueError(f"Trainer API rejected meet {meet_code}: {response['header']}")
    body = response["body"]
    items = body["items"]["item"]
    if isinstance(items, dict):
        items = [items]
    if len(items) != int(body["totalCount"]):
        raise ValueError(f"Trainer API pagination incomplete for meet {meet_code}")
    expected_meet_name = {1: "서울", 2: "제주", 3: "영남"}[meet_code]
    source_url = f"{API_SOURCE}?meet={meet_code}"
    source_sha256 = hashlib.sha256(payload).hexdigest()
    result: list[Affiliation] = []
    for item in items:
        if item["meet"] != expected_meet_name:
            raise ValueError(f"Unexpected meet label in API response: {item['meet']}")
        if str(item.get("spDate", "")).strip() != "-":
            continue
        trainer_id = str(item["trNo"])
        stable_part = int(item["part"])
        name = str(item["trName"]).strip()
        if not re.fullmatch(r"\d{6}", trainer_id) or not name or not 1 <= stable_part <= 99:
            raise ValueError(f"Invalid active trainer in meet {meet_code}: {trainer_id}")
        result.append(
            Affiliation(
                kra_trainer_id=trainer_id,
                name_ko=name,
                meet_code=meet_code,
                stable_part=stable_part,
                stats_as_of=None,
                source_url=source_url,
                source_sha256=source_sha256,
            )
        )
    if not 10 <= len(result) <= 70:
        raise ValueError(f"Unexpected active trainer count for meet {meet_code}: {len(result)}")
    if len({item.kra_trainer_id for item in result}) != len(result):
        raise ValueError(f"Duplicate active trainer ID in API meet {meet_code}")
    return result


def fetch_api_listings() -> tuple[list[Affiliation], dict[int, bytes]]:
    secret = get_settings().data_go_kr_service_key
    if secret is None:
        raise ValueError("DATA_GO_KR_SERVICE_KEY is required for the trainer API")
    all_rows: list[Affiliation] = []
    raw: dict[int, bytes] = {}
    with httpx.Client(timeout=30) as client:
        for meet_code in (1, 2, 3):
            response = client.get(
                API_SOURCE,
                params={
                    "serviceKey": secret.get_secret_value(),
                    "meet": meet_code,
                    "pageNo": 1,
                    "numOfRows": 500,
                    "_type": "json",
                },
            )
            response.raise_for_status()
            raw[meet_code] = response.content
            all_rows.extend(parse_api_response(response.content, meet_code))
    if len({item.kra_trainer_id for item in all_rows}) != len(all_rows):
        raise ValueError("Active trainer ID appears in more than one API meet")
    return all_rows, raw


def validate_api_against_official_web(affiliations: list[Affiliation]) -> None:
    web_rows, _ = fetch_listings()

    def identity(item: Affiliation) -> tuple[str, str, int, int]:
        return (item.kra_trainer_id, item.name_ko, item.meet_code, item.stable_part)

    if {identity(item) for item in affiliations} != {identity(item) for item in web_rows}:
        raise ValueError(
            "Trainer API and KRA web listing disagree; review Yeongnam/Busan mapping before writing"
        )


def validate_existing(connection, affiliations: list[Affiliation]) -> dict[str, int]:
    existing = {
        row.kra_trainer_id: (row.id, row.name_ko)
        for row in connection.execute(text("select id, kra_trainer_id, name_ko from trainers"))
    }
    missing = [item.kra_trainer_id for item in affiliations if item.kra_trainer_id not in existing]
    mismatched = [
        item.kra_trainer_id
        for item in affiliations
        if item.kra_trainer_id in existing and existing[item.kra_trainer_id][1] != item.name_ko
    ]
    if missing or mismatched:
        raise ValueError(f"Trainer ID/name mismatch: missing={missing}, mismatched={mismatched}")
    return {trainer_id: entry[0] for trainer_id, entry in existing.items()}


def write_snapshots(
    database_url: str, affiliations: list[Affiliation], observed_at: datetime
) -> int:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        trainer_ids = validate_existing(connection, affiliations)
        observed_on = observed_at.date()
        observed_at_ms = int(observed_at.timestamp() * 1000)
        statement = text(
            """insert into trainer_affiliation_snapshots
                 (trainer_id, observed_on, meet_code, stable_part, official_name_ko,
                  stats_as_of, observed_at_ms, source_url, source_sha256)
               values
                 (:trainer_id, :observed_on, :meet_code, :stable_part, :official_name_ko,
                  :stats_as_of, :observed_at_ms, :source_url, :source_sha256)
               on conflict (trainer_id, observed_on) do update set
                 meet_code=excluded.meet_code,
                 stable_part=excluded.stable_part,
                 official_name_ko=excluded.official_name_ko,
                 stats_as_of=excluded.stats_as_of,
                 observed_at_ms=excluded.observed_at_ms,
                 source_url=excluded.source_url,
                 source_sha256=excluded.source_sha256"""
        )
        for item in affiliations:
            connection.execute(
                statement,
                {
                    "trainer_id": trainer_ids[item.kra_trainer_id],
                    "observed_on": observed_on,
                    "meet_code": item.meet_code,
                    "stable_part": item.stable_part,
                    "official_name_ko": item.name_ko,
                    "stats_as_of": item.stats_as_of,
                    "observed_at_ms": observed_at_ms,
                    "source_url": item.source_url,
                    "source_sha256": item.source_sha256,
                },
            )
        count = connection.execute(
            text("select count(*) from trainer_affiliation_snapshots where observed_on=:day"),
            {"day": observed_on},
        ).scalar_one()
        if count != len(affiliations):
            raise ValueError(f"Snapshot count mismatch: expected {len(affiliations)}, got {count}")
    engine.dispose()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("web", "api"), default="web")
    parser.add_argument("--apply-local", action="store_true")
    parser.add_argument("--apply-remote", action="store_true")
    args = parser.parse_args()
    observed_at = datetime.now(KST)
    affiliations, raw = fetch_api_listings() if args.source == "api" else fetch_listings()
    if args.source == "api":
        validate_api_against_official_web(affiliations)
        print("API current trainers match the KRA web listing by ID, meet, name, and part")
    for meet_code in (1, 2, 3):
        rows = [item for item in affiliations if item.meet_code == meet_code]
        print(f"meet={meet_code} trainers={len(rows)} stats_as_of={rows[0].stats_as_of}")
    targets = [("local", LOCAL_DATABASE_URL, args.apply_local)]
    if args.apply_remote or not args.apply_local:
        targets.append(("remote", get_settings().database_url, args.apply_remote))
    for label, database_url, apply in targets:
        engine = create_engine(database_url)
        with engine.connect() as connection:
            validate_existing(connection, affiliations)
        engine.dispose()
        print(f"{label}: all {len(affiliations)} trainer IDs/names match")
        if apply:
            count = write_snapshots(database_url, affiliations, observed_at)
            print(f"{label}: stored {count} trainer affiliation snapshots")
    if args.apply_local or args.apply_remote:
        raw_dir = Path("data/raw/kra_trainer_affiliations") / observed_at.strftime("%Y-%m-%d")
        raw_dir.mkdir(parents=True, exist_ok=True)
        for meet_code, content in raw.items():
            extension = "json" if args.source == "api" else "html"
            (raw_dir / f"meet_{meet_code}.{extension}").write_bytes(content)
        print(f"Saved official {args.source} source responses: {raw_dir}")


if __name__ == "__main__":
    main()
