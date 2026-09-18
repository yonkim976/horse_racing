"""Audit older Jeju-native trial section times visible on KRA's score pages.

The archived Text reports omit per-horse section rows before 2019. This script
reads only the already confirmed native trial keys and writes a separate native
row supplement. Mixed-breed HTML is hashed but never persisted. Corner-based
differences are proxies because KRA describes 3C/4C positions as approximate.
"""

from __future__ import annotations

import collections
import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/jeju_native_running_trial_links_20260915"
sys.path.insert(0, str(ROOT / "scripts"))
from build_jeju_running_trial_links import parse_official, URL  # noqa: E402


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def dump(path: Path, data: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in data:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def millis(value: str) -> int | None:
    if not value:
        return None
    match = re.fullmatch(r"(?:(\d+):)?(\d+)\.(\d)", value)
    if match is None:
        return None
    return (int(match.group(1) or 0) * 60 + int(match.group(2))) * 1000 + int(match.group(3)) * 100


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def parse_sections(payload: bytes) -> list[dict]:
    page = payload.decode("euc-kr", errors="replace")
    tables = [t for t in re.findall(r"<table\b[^>]*>.*?</table>", page, re.I | re.S) if "G-3F" in t and "G-1F" in t]
    if len(tables) != 1:
        return []
    result = []
    for block in re.findall(r"<tr\b[^>]*>(.*?)</tr>", tables[0], re.I | re.S):
        cells = [clean(x) for x in re.findall(r"<td\b[^>]*>(.*?)</td>", block, re.I | re.S)]
        if len(cells) < 11 or not cells[1].isdigit():
            continue
        result.append({
            "horse_number": int(cells[1]), "s1f_ms": millis(cells[3]),
            "corner_3_ms": millis(cells[6]), "corner_4_ms": millis(cells[7]),
            "g3f_ms": millis(cells[8]), "g1f_ms": millis(cells[9]),
            "finish_time_ms": millis(cells[10]),
        })
    return result


def fetch(key: tuple[str, int]) -> tuple[tuple[str, int], dict, list[dict], list[dict]]:
    day, race = key
    params = {"meet": "2", "trno": str(race), "date": day, "Act": "07", "Sub": "7"}
    body = urllib.parse.urlencode(params).encode()
    info = {"date": day, "race_number": race, "method": "POST", "url": URL, "form": params, "request_sha256": hashlib.sha256(body).hexdigest()}
    for attempt in range(3):
        try:
            request = urllib.request.Request(URL, data=body, headers={"User-Agent": "Mozilla/5.0 Jeju-trial-section-audit"})
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
                info.update({"http_status": response.status, "response_sha256": hashlib.sha256(payload).hexdigest(), "response_bytes": len(payload)})
            return key, info, parse_official(payload), parse_sections(payload)
        except Exception as exc:
            if attempt == 2:
                info["error"] = f"{type(exc).__name__}: {exc}"
                return key, info, [], []
            time.sleep(1 + attempt)
    raise AssertionError("unreachable")


def build(workers: int = 4) -> dict:
    native = [r for r in rows(OUT / "linked_native_trials_final.jsonl") if "2015" <= r["trial_date"][:4] <= "2018"]
    by_key = collections.defaultdict(list)
    for row in native:
        by_key[(row["trial_date"], row["trial_race_number"])].append(row)
    cache_path = OUT / "older_trial_section_audit_cache.jsonl"
    cache = {(r["date"], r["race_number"]): r for r in rows(cache_path)} if cache_path.exists() else {}
    todo = sorted(set(by_key) - set(cache))
    if todo:
        with cache_path.open("a", encoding="utf-8") as stream, ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(fetch, key) for key in todo]
            for index, future in enumerate(as_completed(futures), 1):
                key, info, official, sections = future.result()
                eligible = {r["horse_number"] for r in by_key[key]}
                rec = {**info, "official_rows": [r for r in official if r["horse_number"] in eligible], "section_rows": [r for r in sections if r["horse_number"] in eligible]}
                cache[key] = rec
                stream.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
                stream.flush()
                if index % 100 == 0:
                    print(f"section pages {index}/{len(todo)}", flush=True)
    ledger = []
    counts = collections.Counter()
    yearly = collections.defaultdict(collections.Counter)
    for row in native:
        key = (row["trial_date"], row["trial_race_number"])
        page = cache[key]
        basic = [x for x in page["official_rows"] if x["horse_number"] == row["horse_number"]]
        section = [x for x in page["section_rows"] if x["horse_number"] == row["horse_number"]]
        status = "no_section_times"
        if page.get("error"):
            status = "request_error"
        elif len(basic) != 1 or basic[0]["hrNo"] != row["hrNo"]:
            status = "horse_id_conflict"
        elif len(section) != 1:
            status = "section_row_missing_or_duplicate"
        elif section[0]["s1f_ms"] is not None:
            s = section[0]
            finish = row["trial_result"]["finish_time_ms"]
            if finish and s["finish_time_ms"] and abs(finish - s["finish_time_ms"]) > 100:
                status = "finish_time_conflict"
            elif all(s[k] and s[k] > 0 for k in ("s1f_ms", "corner_3_ms", "corner_4_ms", "g3f_ms", "g1f_ms", "finish_time_ms")):
                parts = [s["s1f_ms"], s["corner_4_ms"]-s["s1f_ms"], s["finish_time_ms"]-s["corner_4_ms"]-s["g1f_ms"], s["g1f_ms"]]
                if row["distance_m"] == 800 and all(x > 0 for x in parts) and abs(s["corner_3_ms"]-s["s1f_ms"]) <= 100 and abs(s["g3f_ms"]-(s["finish_time_ms"]-s["s1f_ms"])) <= 200:
                    status = "four_corner_proxy_segments_consistent"
                else:
                    status = "section_inconsistent_or_other_distance"
            else:
                status = "section_incomplete"
        counts[status] += 1
        yearly[row["trial_date"][:4]][status] += 1
        ledger.append({"trial_date": row["trial_date"], "trial_race_number": row["trial_race_number"], "horse_number": row["horse_number"], "hrNo": row["hrNo"], "distance_m": row["distance_m"], "status": status, "section": section[0] if len(section) == 1 else None, "official_response_sha256": page.get("response_sha256")})
    ledger.sort(key=lambda r: (r["trial_date"],r["trial_race_number"],r["horse_number"]))
    dump(OUT / "older_trial_section_audit_native_only.jsonl", ledger)
    summary = {"years": [2015, 2016, 2017, 2018], "native_rows": len(native), "official_pages": len(by_key), "request_errors": sum(bool(r.get("error")) for r in cache.values()), "statuses": dict(counts), "by_year": {year:dict(counter) for year,counter in sorted(yearly.items())}}
    (OUT / "older_trial_section_audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2)+"\n",encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
