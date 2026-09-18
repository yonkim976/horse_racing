"""Confirm breed of ID-linked trial rows whose Text report omits horse type.

Reads the isolated trial ledger and KRA horse profiles. Horse type is a stable
identity attribute; current trainer/owner/profile status is never propagated to
historical trials. Existing source data and the operational database are untouched.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import html
import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/research/jeju_native_running_trial_links_20260915"
URL = "https://race.kra.co.kr/racehorse/profileHorseItem.do"


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def dump(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def field(page: str, label: str) -> str | None:
    match = re.search(r"<th[^>]*>\s*" + re.escape(label) + r"\s*</th>\s*<td[^>]*>(.*?)</td>", page, re.I | re.S)
    return html.unescape(re.sub(r"<[^>]*>", " ", match.group(1))).strip() if match else None


def fetch_profile(hr_no: str) -> tuple[str, dict]:
    body = urllib.parse.urlencode({"meet": "2", "hrNo": hr_no}).encode()
    rec = {"method": "POST", "url": URL, "meet": 2, "hrNo": hr_no, "request_sha256": hashlib.sha256(body).hexdigest()}
    for attempt in range(3):
        try:
            request = urllib.request.Request(URL, data=body, headers={"User-Agent": "Mozilla/5.0 Jeju-running-trial-research"})
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
                rec.update({"http_status": response.status, "response_sha256": hashlib.sha256(payload).hexdigest(), "response_bytes": len(payload)})
            page = payload.decode("euc-kr", errors="replace")
            rec["profile_hrNo"] = field(page, "마번")
            rec["breed"] = field(page, "마종")
            return hr_no, rec
        except Exception as exc:
            if attempt == 2:
                rec["error"] = f"{type(exc).__name__}: {exc}"
                return hr_no, rec
            time.sleep(1 + attempt)
    raise AssertionError("unreachable")


def build(*, workers: int, resume: bool) -> dict:
    linked = load_jsonl(OUT / "linked_native_trials.jsonl")
    unresolved = load_jsonl(OUT / "unresolved_trials.jsonl")
    unknown = [r for r in unresolved if r["reason"] == "breed_unconfirmed_no_native_race"]
    ids = sorted({r["official_candidates"][0]["hrNo"] for r in unknown})
    cache_path = OUT / "profile_response_cache.jsonl"
    cache = {}
    if resume and cache_path.exists():
        for row in load_jsonl(cache_path):
            cache[row["hrNo"]] = row
    fetch_ids = [hr_no for hr_no in ids if hr_no not in cache]
    if fetch_ids:
        with cache_path.open("a", encoding="utf-8") as stream, ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(fetch_profile, hr_no) for hr_no in fetch_ids]
            for index, future in enumerate(as_completed(futures), 1):
                hr_no, rec = future.result()
                cache[hr_no] = rec
                stream.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
                stream.flush()
                if index % 100 == 0:
                    print(f"profiles {index}/{len(fetch_ids)}", flush=True)

    final_unresolved = []
    excluded = collections.Counter()
    for row in unresolved:
        if row["reason"] != "breed_unconfirmed_no_native_race":
            final_unresolved.append(row)
            continue
        official = row["official_candidates"][0]
        hr_no = official["hrNo"]
        profile = cache[hr_no]
        if profile.get("profile_hrNo") != hr_no:
            final_unresolved.append({**row, "reason": "profile_identity_unconfirmed", "profile_response_sha256": profile.get("response_sha256"), "profile_error": profile.get("error")})
            continue
        if profile.get("breed") == "제주마":
            linked.append({
                **{k: v for k, v in row.items() if k not in {"reason", "official_candidates", "request_error"}},
                "hrNo": hr_no,
                "breed_evidence": "official_horse_profile_jeju",
                "profile_response_sha256": profile["response_sha256"],
                "official_horse_name": official["horse_name"],
                "official_trNo": official["trNo"],
                "trial_result": row["trial_result"],
                "first_confirmed_native_race": None,
                "before_first_confirmed_native_race": False,
            })
        elif profile.get("breed") in {"한라마", "더러브렛", "서러브레드"}:
            excluded[profile["breed"]] += 1
        else:
            final_unresolved.append({**row, "reason": "profile_breed_unconfirmed", "profile_breed": profile.get("breed"), "profile_response_sha256": profile.get("response_sha256")})
    linked.sort(key=lambda r: (r["trial_date"], r["trial_race_number"], r["horse_number"]))
    final_unresolved.sort(key=lambda r: (r["trial_date"], r["trial_race_number"], r["horse_number"]))
    dump(OUT / "linked_native_trials_final.jsonl", linked)
    dump(OUT / "unresolved_trials_final.jsonl", final_unresolved)
    dump(OUT / "profile_request_manifest.jsonl", [cache[x] for x in ids])
    annual = collections.defaultdict(collections.Counter)
    for row in linked:
        annual[row["trial_date"][:4]]["linked_rows"] += 1
        annual[row["trial_date"][:4]]["before_first_confirmed_race_rows"] += row["before_first_confirmed_native_race"]
        annual[row["trial_date"][:4]][row["breed_evidence"]] += 1
    for row in final_unresolved:
        annual[row["trial_date"][:4]]["unresolved_rows"] += 1
        annual[row["trial_date"][:4]]["unresolved_" + row["reason"]] += 1
    dump(OUT / "annual_final.jsonl", [{"year": year, **counts} for year, counts in sorted(annual.items())])
    summary = {
        "official_profile_requests": len(ids),
        "official_profile_request_errors": sum(bool(cache[x].get("error")) for x in ids),
        "profile_confirmed_jeju_rows": sum(r["breed_evidence"] == "official_horse_profile_jeju" for r in linked),
        "linked_native_trial_rows": len(linked),
        "unresolved_rows": len(final_unresolved),
        "profile_confirmed_non_jeju_excluded": dict(excluded),
        "linked_before_first_confirmed_native_race_rows": sum(r["before_first_confirmed_native_race"] for r in linked),
    }
    (OUT / "summary_final.json").write_text(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build(workers=args.workers, resume=args.resume), ensure_ascii=False, indent=2))
