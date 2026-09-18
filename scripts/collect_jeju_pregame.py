"""Capture one pass of public KRA pages; no scheduler, results, or model writes."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import httpx

from horse_racing.parsers.jeju_pregame import KST
from horse_racing.services.jeju_pregame_store import PregameStore, now_ms, replay, timestamp_ms

BASE = "https://race.kra.co.kr"
ENDPOINTS = {
    "schedule": "/chulmainfo/ChulmaDetailInfoList.do",
    "card": "/chulmainfo/chulmaDetailInfoChulmapyo.do",
    "changes": "/raceFastreport/ChulmapyoChange.do",
    "weight_index": "/raceFastreport/ChuljumaWeightWeight.do",
    "weight": "/raceFastreport/ChuljumaWeightList.do",
    "track": "/chulmainfo/trackView.do",
}


def collect(root, *, dates=None, client=None):
    store = PregameStore(root)
    owned = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=True)
    captured = []

    def fetch(kind, race=None):
        params = {
            "Act": "02" if kind in {"schedule", "card", "track"} else "03",
            "Sub": "9" if kind == "track" else "4" if kind.startswith("weight") else "1",
            "meet": 2,
        }
        if race:
            params.update(
                {
                    "date" if kind == "weight" else "rcDate": race[0].replace("-", ""),
                    "rcNo": race[1],
                }
            )
        url = BASE + ENDPOINTS[kind] + "?" + urlencode(params)
        requested = now_ms()
        try:
            response = client.get(url)
            retrieved = now_ms()
            p = store.record(
                kind=kind,
                url=url,
                body=response.content,
                requested_ms=requested,
                retrieved_ms=retrieved,
                status_code=response.status_code,
                encoding=response.encoding or "euc-kr",
                request_race=race,
                headers={
                    k: response.headers[k]
                    for k in ["date", "last-modified", "etag", "content-type"]
                    if k in response.headers
                },
            )
        except httpx.HTTPError as exc:
            p = store.record(
                kind=kind,
                url=url,
                body=b"",
                requested_ms=requested,
                retrieved_ms=now_ms(),
                status_code=None,
                request_race=race,
                error=type(exc).__name__,
            )
        captured.append(p)
        return p

    try:
        index = fetch("schedule")
        target_races = []
        if index["parsed"]:
            for r in index["parsed"]["races"]:
                if dates and r["race_date"] not in dates:
                    continue
                if timestamp_ms(r["scheduled_start_at"]) > now_ms():
                    target_races.append((r["race_date"], r["race_number"]))
                    fetch("card", target_races[-1])
        fetch("changes")
        weights = fetch("weight_index")
        fetch("track")
        if weights["parsed"]:
            for r in weights["parsed"]["races"]:
                key = (r["race_date"], r["race_number"])
                if key in target_races and r["input_status"] == "입력완료":
                    fetch("weight", key)
    finally:
        if owned:
            client.close()
    cutoff = now_ms()
    result = replay(store, cutoff, race_dates=dates)
    summary = dict(
        captured_at=datetime.now(UTC).isoformat(),
        local_date=datetime.now(KST).date().isoformat(),
        observations=len(captured),
        valid_pages=sum(p["parsed"] is not None for p in captured),
        errors=[
            dict(kind=p["kind"], race=p["request_race"], error=p["error"])
            for p in captured
            if p["error"]
        ],
        replay=result,
    )
    run = root / "runs" / f"{cutoff}_{captured[0]['observation_id']}"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return run, summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--root", type=Path, default=Path("data/research/jeju_native_pregame_observations_v1")
    )
    p.add_argument(
        "--date", action="append", help="ISO race date; omitted: all future listed races"
    )
    args = p.parse_args()
    for day in args.date or []:
        datetime.strptime(day, "%Y-%m-%d")
    run, s = collect(args.root, dates=args.date)
    print(
        json.dumps(
            dict(
                run=str(run),
                observations=s["observations"],
                valid_pages=s["valid_pages"],
                errors=s["errors"],
                races=len(s["replay"]["races"]),
                runners=sum(len(r["runners"]) for r in s["replay"]["races"]),
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    if s["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
