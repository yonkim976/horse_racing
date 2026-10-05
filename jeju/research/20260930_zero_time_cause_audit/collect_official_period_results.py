"""Archive KRA period-result pages for the fixed 76-race zero-time audit cohort."""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup


HERE = Path(__file__).resolve().parent
COHORT = HERE / "unresolved_76_review.jsonl"
RAW_DIR = HERE / "official_period_html"
EVIDENCE = HERE / "official_period_evidence.jsonl"
URL = "https://race.kra.co.kr/raceScore/scoretablePeriodScoreList.do"
TITLE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})\([^)]*\)\s*(\d+)경주$")
MAX_RESPONSE_BYTES = 2_000_000


def fetch(date: str) -> bytes:
    compact = date.replace("-", "")
    body = urllib.parse.urlencode(
        {"Act": "10", "Sub": "1", "meet": "2", "fromDate": compact, "toDate": compact}
    ).encode("ascii")
    request = urllib.request.Request(
        URL,
        data=body,
        headers={"User-Agent": "Mozilla/5.0 (Jeju race source audit)"},
        method="POST",
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 200:
                    raise ValueError(f"HTTP {response.status}: {date}")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError(f"Oversized official response: {date}")
            return raw
        except (TimeoutError, urllib.error.URLError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise AssertionError("Unreachable retry branch")


def parse(date: str, raw: bytes, targets: list[int]) -> list[dict]:
    soup = BeautifulSoup(raw, "html.parser")
    compact = date.replace("-", "")
    for field in ("fromDate", "toDate"):
        element = soup.find("input", attrs={"name": field})
        if element is None or element.get("value") != compact:
            raise ValueError(f"Search date mismatch: {date} {field}")
    entries: dict[int, dict] = {}
    for node in soup.select(".NewDV"):
        title = node.select_one("#ShowDV .tit")
        detail = node.select_one("#ShowDV")
        anchor = node.select_one("a")
        if title is None or detail is None or anchor is None:
            continue
        match = TITLE.fullmatch(title.get_text(" ", strip=True))
        if not match:
            raise ValueError(f"Unexpected race title: {title.get_text(' ', strip=True)}")
        found_date = "-".join(match.groups()[:3])
        number = int(match.group(4))
        if found_date != date or number in entries:
            raise ValueError(f"Race key mismatch or duplicate: {date} {number}")
        reason = detail.get_text(" ", strip=True).replace(title.get_text(" ", strip=True), "", 1).strip()
        entries[number] = {
            "race_date": date,
            "race_number": number,
            "official_detail_text": reason or None,
            "red_detail_marker": "mark_red" in anchor.get("class", []),
            "official_cancel_confirmed": "경주취소" in reason or "경주 취소" in reason,
        }
    missing = set(targets) - set(entries)
    if missing:
        raise ValueError(f"Official detail missing: {date} {sorted(missing)}")
    return [entries[number] for number in targets]


def main() -> None:
    by_date: dict[str, list[int]] = defaultdict(list)
    for line in COHORT.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        by_date[row["race_date"]].append(row["race_number"])
    if sum(map(len, by_date.values())) != 76:
        raise ValueError("Expected the fixed 76-race cohort")
    RAW_DIR.mkdir(exist_ok=True)
    evidence = []
    for date, targets in sorted(by_date.items()):
        path = RAW_DIR / f"{date.replace('-', '')}.html"
        if path.exists():
            raw = path.read_bytes()
        else:
            raw = fetch(date)
            path.write_bytes(raw)
        parsed = parse(date, raw, targets)
        digest = hashlib.sha256(raw).hexdigest()
        for row in parsed:
            row.update(
                {
                    "official_results_url": URL,
                    "official_request_method": "POST",
                    "official_request_form": {
                        "Act": "10", "Sub": "1", "meet": "2",
                        "fromDate": date.replace("-", ""),
                        "toDate": date.replace("-", ""),
                    },
                    "response_bytes": len(raw),
                    "response_sha256": digest,
                    "raw_html_file": str(path.relative_to(HERE)),
                    "checked_on": "2026-09-30",
                }
            )
            evidence.append(row)
        print(f"{date}: {len(targets)} target races, {len(raw)} bytes", flush=True)
    if len(evidence) != 76:
        raise ValueError("Incomplete official evidence")
    with EVIDENCE.open("w", encoding="utf-8") as output:
        for row in evidence:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"Archived {len(by_date)} dates and {len(evidence)} target races", flush=True)


if __name__ == "__main__":
    main()
