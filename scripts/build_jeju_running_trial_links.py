"""Build an isolated, evidence-backed Jeju-native running-trial research ledger.

Only archived meet=2 Text reports are parsed. Official horse numbers come from
KRA's trial score table, never from a horse-name lookup or the operational DB.
The downloaded HTML is mixed-breed, so only response hashes and matched native
rows are stored. Existing sources and database are read-only.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from horse_racing.parsers.running_trials import (  # noqa: E402
    decode_running_trial_report,
    parse_running_trial_report,
)

SOURCE = ROOT / "data/raw/kra_text/dacom23/meet=2"
RACE_IDS = ROOT / "data/research/jeju_confirmed_race_time_ids_20260914/linked_official_ids.jsonl"
OUT = ROOT / "data/research/jeju_native_running_trial_links_20260915"
URL = "https://race.kra.co.kr/referee/RacingTrainCheckScoreTable.do"
ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)
CELL_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.I | re.S)
HORSE_RE = re.compile(r"goPage1\('([^']+)','([^']+)'\)")
TRAINER_RE = re.compile(r"goPage3\('([^']+)'(?:,'[^']*')?\)")


def dump(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def clean_cell(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def parse_official(payload: bytes) -> list[dict]:
    page = payload.decode("euc-kr", errors="replace")
    rows = []
    for match in ROW_RE.finditer(page):
        block = match.group(1)
        horse = HORSE_RE.search(block)
        if horse is None:
            continue
        cells = CELL_RE.findall(block)
        if len(cells) < 11:
            continue
        values = [clean_cell(c) for c in cells]
        trainer = TRAINER_RE.search(cells[8]) if len(cells) > 8 else None
        if not values[1].isdigit():
            continue
        rows.append(
            {
                "horse_number": int(values[1]),
                "horse_name": values[2],
                "hrNo": horse.group(1),
                "meet": horse.group(2),
                "sex": values[4],
                "age": int(values[5]) if values[5].isdigit() else None,
                "trainer_name": values[8],
                "trNo": trainer.group(1) if trainer else None,
                "body_weight_kg": int(values[10]) if values[10].isdigit() else None,
            }
        )
    return rows


def load_trials() -> tuple[list[dict], list[dict]]:
    trials, source_manifest = [], []
    for path in sorted(SOURCE.glob("year=*/**/*.rpt")):
        payload = path.read_bytes()
        sha = hashlib.sha256(payload).hexdigest()
        normalized = (
            decode_running_trial_report(payload)
            .replace("주행검사성적", "주행심사성적")
            .replace("능력검사성적", "주행심사성적")
            .replace("선수명", "기수명")
            .replace("감독명", "조교사명")
        )
        normalized = re.sub(r"^;TI\s*", "제목 : ", normalized, flags=re.M)
        parsed = parse_running_trial_report(normalized, meet=2)
        source_manifest.append(
            {"path": str(path.relative_to(ROOT)), "sha256": sha, "trial_count": len(parsed)}
        )
        for trial in parsed:
            trials.append(
                {
                    "date": trial.trial_date.strftime("%Y%m%d"),
                    "race_number": trial.trial_race_number,
                    "round": trial.trial_round,
                    "distance_m": trial.distance_m,
                    "weather": trial.weather,
                    "track_condition": trial.track_condition,
                    "track_moisture_percent": trial.track_moisture_percent,
                    "source_path": str(path.relative_to(ROOT)),
                    "source_sha256": sha,
                    "results": [asdict(result) for result in trial.results],
                }
            )
    return trials, source_manifest


def fetch_one(key: tuple[str, int]) -> tuple[tuple[str, int], dict, list[dict]]:
    day, race = key
    params = {"meet": "2", "trno": str(race), "date": day, "Act": "07", "Sub": "7"}
    body = urllib.parse.urlencode(params).encode()
    record = {"method": "POST", "url": URL, "form": params, "request_sha256": hashlib.sha256(body).hexdigest()}
    for attempt in range(3):
        try:
            request = urllib.request.Request(URL, data=body, headers={"User-Agent": "Mozilla/5.0 Jeju-running-trial-research"})
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
                record.update({"http_status": response.status, "response_sha256": hashlib.sha256(payload).hexdigest(), "response_bytes": len(payload)})
            rows = parse_official(payload)
            record["official_rows"] = len(rows)
            return key, record, rows
        except Exception as exc:
            if attempt == 2:
                record["error"] = f"{type(exc).__name__}: {exc}"
                return key, record, []
            time.sleep(1 + attempt)
    raise AssertionError("unreachable")


def load_native_race_ids() -> tuple[set[str], dict[str, str]]:
    ids, first_dates = set(), {}
    with RACE_IDS.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            horse = str(row["hrNo"])
            day = str(row["race_date"])
            ids.add(horse)
            if horse not in first_dates or day < first_dates[horse]:
                first_dates[horse] = day
    return ids, first_dates


def build(*, workers: int, resume: bool) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    trials, manifest = load_trials()
    native_ids, first_dates = load_native_race_ids()
    keys = {(t["date"], t["race_number"]) for t in trials}
    if len(keys) != len(trials):
        raise RuntimeError("Text 원천에 날짜·심사경주 중복이 있습니다")
    candidate = [t for t in trials if any(r["origin_country"] in {"제", None} for r in t["results"])]
    candidate_by_key = {(t["date"], t["race_number"]): t for t in candidate}
    cached: dict[tuple[str, int], tuple[dict, list[dict]]] = {}
    cache_path = OUT / "official_response_cache.jsonl"
    if resume and cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            cached[(row["date"], row["race_number"])] = (row["request"], row["official_rows"])
    fetch_keys = sorted({(t["date"], t["race_number"]) for t in candidate} - set(cached))
    if fetch_keys:
        with cache_path.open("a", encoding="utf-8") as stream, ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch_one, key): key for key in fetch_keys}
            for index, future in enumerate(as_completed(futures), 1):
                key, request, official = future.result()
                eligible_numbers = {
                    r["horse_number"] for r in candidate_by_key[key]["results"]
                    if r["origin_country"] in {"제", None}
                }
                retained = [r for r in official if r["horse_number"] in eligible_numbers]
                cached[key] = (request, retained)
                stream.write(json.dumps({"date": key[0], "race_number": key[1], "request": request, "official_rows": retained}, ensure_ascii=False, sort_keys=True) + "\n")
                stream.flush()
                if index % 250 == 0:
                    print(f"fetched {index}/{len(fetch_keys)}", flush=True)

    linked, unresolved, requests = [], [], []
    stats = collections.defaultdict(collections.Counter)
    for trial in sorted(trials, key=lambda t: (t["date"], t["race_number"])):
        year = trial["date"][:4]
        stats[year]["all_text_races"] += 1
        stats[year]["all_text_rows"] += len(trial["results"])
        if (trial["date"], trial["race_number"]) not in candidate_by_key:
            continue
        req, official = cached[(trial["date"], trial["race_number"])]
        requests.append({"date": trial["date"], "race_number": trial["race_number"], **req})
        by_number = collections.defaultdict(list)
        for row in official:
            by_number[row["horse_number"]].append(row)
        stats[year]["candidate_races"] += 1
        stats[year]["official_races_with_rows"] += bool(official)
        for row in trial["results"]:
            breed = row["origin_country"]
            if breed not in {"제", None}:
                continue
            stats[year]["candidate_rows"] += 1
            if breed == "제":
                stats[year]["explicit_jeju_rows"] += 1
            matches = by_number.get(row["horse_number"], [])
            evidence = {
                "meet": 2, "trial_date": trial["date"], "trial_race_number": trial["race_number"],
                "trial_round": trial["round"], "distance_m": trial["distance_m"],
                "weather": trial["weather"], "track_condition": trial["track_condition"],
                "track_moisture_percent": trial["track_moisture_percent"],
                "horse_number": row["horse_number"], "horse_name": row["horse_name"],
                "text_breed": breed, "text_source": trial["source_path"],
                "text_sha256": trial["source_sha256"], "official_response_sha256": req.get("response_sha256"),
            }
            reason = None
            if req.get("error"):
                reason = "official_request_failed"
            elif not matches:
                reason = "official_row_missing"
            elif len(matches) != 1:
                reason = "official_duplicate_horse_number"
            else:
                match = matches[0]
                if match["horse_name"] != row["horse_name"]:
                    reason = "horse_name_conflict"
                elif match["meet"] != "2":
                    reason = "meet_conflict"
                elif row["sex"] and match["sex"] and row["sex"] != match["sex"]:
                    reason = "sex_conflict"
                elif row["age"] and match["age"] and row["age"] != match["age"]:
                    reason = "age_conflict"
                elif breed is None and match["hrNo"] not in native_ids:
                    reason = "breed_unconfirmed_no_native_race"
                elif breed == "제" and match["hrNo"] not in native_ids:
                    # Explicit Text '제' proves breed even if this horse never raced.
                    pass
            if reason:
                stats[year]["unresolved_rows"] += 1
                unresolved.append({**evidence, "trial_result": row, "reason": reason, "official_candidates": matches, "request_error": req.get("error")})
                continue
            match = matches[0]
            stats[year]["linked_rows"] += 1
            stats[year]["linked_explicit_rows" if breed == "제" else "linked_race_roster_rows"] += 1
            first = first_dates.get(match["hrNo"])
            linked.append({
                **evidence,
                "hrNo": match["hrNo"], "breed_evidence": "text_explicit_je" if breed == "제" else "confirmed_native_race_hrNo",
                "official_horse_name": match["horse_name"], "official_trNo": match["trNo"],
                "trial_result": row, "first_confirmed_native_race": first,
                "before_first_confirmed_native_race": first is not None and trial["date"] < first,
            })
    dump(OUT / "text_source_manifest.jsonl", manifest)
    dump(OUT / "official_request_manifest.jsonl", requests)
    dump(OUT / "linked_native_trials.jsonl", linked)
    dump(OUT / "unresolved_trials.jsonl", unresolved)
    annual = [{"year": year, **dict(counts)} for year, counts in sorted(stats.items())]
    dump(OUT / "annual_coverage.jsonl", annual)
    summary = {
        "source_files": len(manifest), "all_text_trial_races": len(trials),
        "all_text_rows": sum(len(t["results"]) for t in trials),
        "candidate_trial_races": len(candidate), "official_requests": len(requests),
        "official_request_errors": sum(bool(r.get("error")) for r in requests),
        "explicit_jeju_rows": sum(a.get("explicit_jeju_rows", 0) for a in annual),
        "candidate_rows": sum(a.get("candidate_rows", 0) for a in annual),
        "linked_rows": len(linked), "linked_explicit_rows": sum(a.get("linked_explicit_rows", 0) for a in annual),
        "linked_race_roster_rows": sum(a.get("linked_race_roster_rows", 0) for a in annual),
        "unresolved_candidate_rows": sum(a.get("unresolved_rows", 0) for a in annual),
        "unresolved_ledger_rows": len(unresolved),
        "before_first_confirmed_native_race_rows": sum(r["before_first_confirmed_native_race"] for r in linked),
        "first_date": min(t["date"] for t in trials), "last_date": max(t["date"] for t in trials),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build(workers=args.workers, resume=args.resume), ensure_ascii=False, indent=2))
