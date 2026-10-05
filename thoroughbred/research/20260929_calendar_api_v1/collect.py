"""Archive KRA annual schedule/trial API responses and build a date-only ledger.

The result of a plan API is evidence of a scheduled race, not execution.
Authenticated URLs and service keys are never written or logged.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

from horse_racing.config import get_settings


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
CUTOFF = "20260929"
API = "https://apis.data.go.kr/B551015"
SOURCES = {
    "race_plan": ("API72_2/racePlan_2", "rc_year", (1, 3, 4)),
    "trial_result": ("API20_1/ridingTestResult_1", "tr_year", (1, 3)),
    "race_execution_probe": ("API4_3/raceResult_3", "rc_year", (1, 3, 4)),
}


def excluded_result_keys() -> set[tuple[int, str, int]]:
    """Keep confirmed API anomalies out of every active race ledger."""
    all_keys = set()
    for filename, expected in (("planless_positive_result_review.csv", 20),
                               ("result_only_nonfinish_anomaly_review.csv", 52)):
        with (HERE / filename).open(encoding="utf-8", newline="") as stream:
            review = list(csv.DictReader(stream))
        keys = {(int(row["meet"]), row["date"], int(row["race_no"])) for row in review}
        if len(review) != len(keys) or len(keys) != expected or any(
            row["kra_scoretable_period_lookup"] != "venue_date_no_rows"
            or row["exact_horse_set"] != "yes" for row in review
        ) or all_keys & keys:
            raise ValueError(f"Confirmed anomalous result key ledger changed: {filename}")
        all_keys |= keys
    return all_keys


def items(payload: dict) -> tuple[int, list[dict]]:
    response = payload.get("response") or {}
    header = response.get("header") or {}
    if str(header.get("resultCode")) not in {"00", "0000"}:
        raise ValueError(f"API resultCode={header.get('resultCode')}")
    body = response.get("body") or {}
    block = body.get("items") or {}
    rows = block.get("item") or [] if isinstance(block, dict) else []
    if isinstance(rows, dict):
        rows = [rows]
    total = int(body.get("totalCount") or 0)
    if total != len(rows):
        raise ValueError(f"Incomplete API response: totalCount={total}, items={len(rows)}")
    return total, rows


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def fetch() -> None:
    secret = get_settings().data_go_kr_service_key
    if secret is None:
        raise RuntimeError("KRA API key unavailable")
    key = secret.get_secret_value()
    with httpx.Client(base_url=API, timeout=30, follow_redirects=True) as client:
        for source, (endpoint, year_param, meets) in SOURCES.items():
            for year in range(2010, 2027):
                for meet in meets:
                    suffix = ".json.gz" if source == "race_execution_probe" else ".json"
                    path = RAW / source / str(year) / f"meet_{meet}{suffix}"
                    if path.exists():
                        body = gzip.decompress(path.read_bytes()) if suffix == ".json.gz" else path.read_bytes()
                        items(json.loads(body))
                        continue
                    params = {"ServiceKey": key, "meet": meet, year_param: year,
                              "pageNo": 1, "numOfRows": 20000, "_type": "json"}
                    for attempt in range(3):
                        try:
                            response = client.get(endpoint, params=params)
                            response.raise_for_status()
                            payload = response.json()
                            total, _ = items(payload)
                            if key.encode() in response.content:
                                raise ValueError("Service key reflected in response")
                            atomic_write(path, gzip.compress(response.content) if suffix == ".json.gz" else response.content)
                            print(source, year, meet, total, flush=True)
                            break
                        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
                            if attempt == 2:
                                # An exception may contain the authenticated URL.
                                raise RuntimeError(f"API fetch failed: {source} {year} meet={meet} ({type(exc).__name__})") from None
                            time.sleep(attempt + 1)


def write_csv(path: Path, headers: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def build() -> None:
    excluded_keys = excluded_result_keys()
    manifest: list[dict] = []
    race_rows: list[dict] = []
    trial_rows: list[dict] = []
    execution_rows: list[dict] = []
    for source, (_, _, meets) in SOURCES.items():
        for year in range(2010, 2027):
            for meet in meets:
                suffix = ".json.gz" if source == "race_execution_probe" else ".json"
                path = RAW / source / str(year) / f"meet_{meet}{suffix}"
                if not path.exists():
                    raise FileNotFoundError(path)
                data = path.read_bytes()
                body = gzip.decompress(data) if suffix == ".json.gz" else data
                total, source_rows = items(json.loads(body))
                manifest.append({"source": source, "year": year, "request_meet": meet,
                                 "path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(body).hexdigest(),
                                 "total_count": total, "retrieved_row_count": len(source_rows)})
                for item in source_rows:
                    if source == "race_plan":
                        date = str(item.get("rcDate") or "")
                        if len(date) != 8 or date[:4] != str(year):
                            raise ValueError(f"Race plan date outside requested year: {source} {year} meet={meet}")
                        if not ("20100101" <= date <= CUTOFF):
                            continue
                        race_rows.append({"meet": meet, "date": date, "race_no": item.get("rcNo"),
                                          "api_meet_label": item.get("meet"), "distance_m": item.get("rcDist"),
                                          "grade_raw": item.get("rank"), "race_name_raw": item.get("rcName"),
                                          "scheduled_start_raw": item.get("schStTime"),
                                          "source_file": str(path.relative_to(ROOT))})
                    elif source == "trial_result":
                        date = str(item.get("trainDate") or "")
                        if len(date) != 8 or date[:4] != str(year):
                            raise ValueError(f"Trial date outside requested year: {source} {year} meet={meet}")
                        if not ("20100101" <= date <= CUTOFF):
                            continue
                        trial_rows.append({"source_meet": meet, "date": date,
                                           "trial_no": item.get("trainNo"),
                                           "api_meet_label": item.get("meet"),
                                           "source_file": str(path.relative_to(ROOT))})
                    else:
                        date = str(item.get("rcDate") or "")
                        if len(date) != 8 or date[:4] != str(year):
                            raise ValueError(f"Result probe date outside requested year: {source} {year} meet={meet}")
                        if not ("20100101" <= date <= CUTOFF):
                            continue
                        try:
                            rank = int(item.get("ord") or 0)
                            race_time = float(item.get("rcTime") or 0)
                        except (TypeError, ValueError):
                            rank, race_time = 0, 0
                        race_no = int(item.get("rcNo"))
                        if (meet, date, race_no) in excluded_keys:
                            continue
                        execution_rows.append({"meet": meet, "date": date,
                                               "race_no": race_no,
                                               "positive_finish": 1 <= rank <= 89 and race_time > 0})
    race_keys = [(int(r["meet"]), r["date"], int(r["race_no"])) for r in race_rows]
    if len(race_keys) != len(set(race_keys)):
        raise ValueError("Duplicate race plan natural key")
    race_key_set = set(race_keys)
    if race_key_set & excluded_keys:
        raise ValueError("An excluded result key is present in the race plan")
    trial_groups: dict[tuple[int, str, int, str], dict] = {}
    for row in trial_rows:
        key = (int(row["source_meet"]), row["date"], int(row["trial_no"]), row["api_meet_label"])
        group = trial_groups.setdefault(key, {"source_meet": key[0], "date": key[1],
                                              "trial_no": key[2], "api_meet_label": key[3],
                                              "participant_rows": 0, "source_file": row["source_file"]})
        group["participant_rows"] += 1
    race_days = Counter((int(r["meet"]), r["date"]) for r in race_rows)
    trial_days = Counter((int(r["source_meet"]), r["date"]) for r in trial_groups.values())
    race_execution = defaultdict(lambda: {"source_result_rows": 0, "positive_finish_rows": 0})
    for row in execution_rows:
        value = race_execution[(row["meet"], row["date"], row["race_no"])]
        value["source_result_rows"] += 1
        value["positive_finish_rows"] += int(row["positive_finish"])
    race_status_rows = []
    for meet, date, number in sorted(race_key_set | set(race_execution)):
        evidence = race_execution[(meet, date, number)]
        scheduled = (meet, date, number) in race_key_set
        race_status_rows.append({"meet": meet, "date": date, "race_no": number,
                                 "in_plan_api": int(scheduled),
                                 "source_result_rows": evidence["source_result_rows"],
                                 "positive_finish_rows": evidence["positive_finish_rows"],
                                 "execution_status": "executed_plan_and_result" if scheduled and evidence["positive_finish_rows"] else
                                     "positive_result_without_plan_unverified" if evidence["positive_finish_rows"] else
                                     "planned_no_execution_evidence" if scheduled else "result_rows_without_positive_finish"})
    executed_days = Counter((r["meet"], r["date"]) for r in race_status_rows
                            if r["execution_status"] == "executed_plan_and_result")
    positive_without_plan_days = Counter((r["meet"], r["date"]) for r in race_status_rows
                                         if r["execution_status"] == "positive_result_without_plan_unverified")
    all_dates = sorted(set(race_days) | set(trial_days) | set(executed_days) | set(positive_without_plan_days))
    day_rows = []
    for meet, date in all_dates:
        if meet == 1:
            venue = "Seoul"
            venue_basis = "API meet=1"
        elif meet == 4:
            venue = "Yeongcheon" if race_days[(meet, date)] else "Yeongcheon_unverified"
            venue_basis = "API race plan meet=4" if race_days[(meet, date)] else "API4 result-only; no meet=4 plan"
        elif date < "20260913":
            venue = "BusanGyeongnam"
            venue_basis = "API meet=3; before Yeongcheon racing began"
        else:
            venue = "Yeongnam_unresolved_for_trial" if trial_days[(meet, date)] else "BusanGyeongnam"
            venue_basis = "API meet=3 labels trial as Yeongnam; venue must be checked" if trial_days[(meet, date)] else "API race plan meet=3"
        day_rows.append({"source_meet": meet, "date": date, "venue_provisional": venue,
                         "venue_basis": venue_basis, "scheduled_race_count": race_days[(meet, date)],
                         "api_trial_session_count": trial_days[(meet, date)],
                         "race_execution_status": "executed_plan_and_result" if executed_days[(meet, date)] else
                             "planned_no_execution_evidence" if race_days[(meet, date)] else
                             "positive_result_without_plan_unverified" if positive_without_plan_days[(meet, date)] else
                             "no_race_plan_row",
                         "trial_execution_status": "api_result_present" if trial_days[(meet, date)] else "no_trial_api_row"})
    write_csv(HERE / "race_plan.csv", ["meet", "date", "race_no", "api_meet_label", "distance_m",
                                           "grade_raw", "race_name_raw", "scheduled_start_raw", "source_file"],
              sorted(race_rows, key=lambda r: (int(r["meet"]), r["date"], int(r["race_no"]))))
    write_csv(HERE / "trial_sessions.csv", ["source_meet", "date", "trial_no", "api_meet_label",
                                                "participant_rows", "source_file"],
              sorted(trial_groups.values(), key=lambda r: (r["source_meet"], r["date"], r["trial_no"])))
    write_csv(HERE / "race_execution_flags.csv", ["meet", "date", "race_no", "in_plan_api",
                                                  "source_result_rows", "positive_finish_rows", "execution_status"],
              race_status_rows)
    write_csv(HERE / "event_days.csv", ["source_meet", "date", "venue_provisional", "venue_basis",
                                           "scheduled_race_count", "api_trial_session_count",
                                           "race_execution_status", "trial_execution_status"], day_rows)
    (HERE / "manifest.json").write_text(json.dumps({"built_at_utc": datetime.now(timezone.utc).isoformat(),
        "cutoff": CUTOFF, "sources": manifest,
        "counts": {"race_plan_rows": len(race_rows), "trial_participant_rows": len(trial_rows),
                   "race_result_probe_rows_after_anomaly_exclusion": len(execution_rows),
                   "excluded_anomalous_result_keys": len(excluded_keys),
                   "trial_sessions": len(trial_groups), "race_days": len(race_days),
                   "executed_races": sum(r["execution_status"] == "executed_plan_and_result" for r in race_status_rows),
                   "executed_days": len(executed_days),
                   "positive_result_without_plan_races": sum(r["execution_status"] == "positive_result_without_plan_unverified" for r in race_status_rows),
                   "trial_days": len(trial_days), "event_day_rows": len(day_rows)}},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("built", len(race_rows), len(trial_groups), len(day_rows))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true", help="Fetch missing annual KRA API response files")
    args = parser.parse_args()
    if args.fetch:
        fetch()
    build()
