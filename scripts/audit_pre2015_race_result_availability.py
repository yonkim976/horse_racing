"""Compare KRA race-result API dates with the older official Text catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from horse_racing.collectors.kra_api import (
    RACE_RESULT_WITH_SECTIONS_ENDPOINT,
    RACE_RESULT_WITH_SECTIONS_OPERATION,
    KraApiClient,
    response_body,
)
from horse_racing.collectors.kra_text import TEXT_FILE_TYPES, KraTextClient
from horse_racing.config import get_settings

MEET_NAMES = {1: "서울", 2: "제주", 3: "부산경남"}


def _items(body: dict) -> list[dict]:
    wrapped = body.get("items") or {}
    if not isinstance(wrapped, dict):
        raise ValueError("API items가 객체가 아닙니다.")
    items = wrapped.get("item") or []
    if isinstance(items, dict):
        return [items]
    if not isinstance(items, list):
        raise ValueError("API item이 목록이 아닙니다.")
    return items


def audit(*, first_year: int, last_year: int) -> dict:
    settings = get_settings()
    service_key = settings.data_go_kr_service_key
    if service_key is None:
        raise ValueError("공공데이터포털 서비스키가 없습니다.")
    result: dict = {
        "scope": {"first_year": first_year, "last_year": last_year},
        "api_endpoint": RACE_RESULT_WITH_SECTIONS_ENDPOINT,
        "text_file_type": "dacom11",
        "meets": {},
    }
    with (
        KraApiClient(
            service_key.get_secret_value(),
            base_url=settings.kra_api_base_url,
            timeout_seconds=60,
        ) as api,
        KraTextClient(timeout_seconds=60) as text_client,
    ):
        for meet in (1, 2, 3):
            text_dates: dict[int, set[str]] = defaultdict(set)
            text_files: dict[int, int] = defaultdict(int)
            first_text_file: str | None = None
            for file in text_client.iter_files(
                meet=meet,
                file_type="dacom11",
                code_name=TEXT_FILE_TYPES["dacom11"],
                max_pages=500,
            ):
                if file.file_date is None or not file.filename.endswith("dacom11.rpt"):
                    continue
                stamp = file.file_date.isoformat()
                if first_text_file is None or stamp < first_text_file:
                    first_text_file = stamp
                if first_year <= file.file_date.year <= last_year:
                    text_dates[file.file_date.year].add(stamp)
                    text_files[file.file_date.year] += 1

            years = {}
            for year in range(first_year, last_year + 1):
                api_dates: set[str] = set()
                race_keys: set[tuple[str, int]] = set()
                rows = 0
                pages = []
                for fetched in api.iter_pages(
                    endpoint=RACE_RESULT_WITH_SECTIONS_ENDPOINT,
                    operation=RACE_RESULT_WITH_SECTIONS_OPERATION,
                    public_params={"meet": meet, "rc_year": str(year), "_type": "json"},
                    page_size=20_000,
                    service_key_parameter="ServiceKey",
                ):
                    body = dict(response_body(fetched.payload))
                    batch = _items(body)
                    rows += len(batch)
                    pages.append(
                        {
                            "public_params": dict(fetched.public_params),
                            "sha256": hashlib.sha256(fetched.body).hexdigest(),
                            "response_bytes": len(fetched.body),
                            "totalCount": int(body.get("totalCount") or 0),
                        }
                    )
                    for item in batch:
                        stamp = str(item["rcDate"])
                        parsed = date.fromisoformat(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}")
                        if parsed.year != year:
                            raise ValueError(f"경주 연도 불일치: {meet=} {year=} {stamp=}")
                        if item.get("meet") != MEET_NAMES[meet]:
                            raise ValueError(f"경마장 불일치: {meet=} {year=}")
                        rc_no = int(item["rcNo"])
                        if rc_no < 1:
                            raise ValueError(f"경주번호 오류: {meet=} {year=} {rc_no=}")
                        day = parsed.isoformat()
                        api_dates.add(day)
                        race_keys.add((day, rc_no))
                expected = pages[0]["totalCount"]
                if rows != expected:
                    raise ValueError(f"API 행 수 불일치: {meet=} {year=} {rows=} {expected=}")
                listed = text_dates[year]
                first_available = first_text_file
                comparable = {
                    day
                    for day in api_dates
                    if first_available is not None and day >= first_available
                }
                years[str(year)] = {
                    "api_rows": rows,
                    "api_races": len(race_keys),
                    "api_dates": len(api_dates),
                    "api_first_date": min(api_dates) if api_dates else None,
                    "api_last_date": max(api_dates) if api_dates else None,
                    "text_files": text_files[year],
                    "text_dates": len(listed),
                    "missing_text_dates_after_text_start": sorted(comparable - listed),
                    "text_dates_without_api_result": sorted(listed - api_dates),
                    "api_pages": pages,
                }
                print(
                    f"meet={meet} year={year} rows={rows} races={len(race_keys)} "
                    f"missing_text_dates={len(comparable - listed)}",
                    flush=True,
                )
            result["meets"][str(meet)] = {
                "first_text_file": first_text_file,
                "years": years,
            }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-year", type=int, default=1999)
    parser.add_argument("--last-year", type=int, default=2014)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.first_year > args.last_year:
        raise ValueError("연도 범위가 역순입니다.")
    result = audit(first_year=args.first_year, last_year=args.last_year)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
