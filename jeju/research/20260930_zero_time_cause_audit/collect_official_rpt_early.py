"""Archive official KRA dacom11 text for the seven blank 2002–2004 details."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path


HERE = Path(__file__).resolve().parent
RAW_DIR = HERE / "official_rpt_early"
EVIDENCE = HERE / "official_rpt_early_evidence.jsonl"
URL = "https://race.kra.co.kr/dbdata/fileDownLoad.do"
TARGETS = (
    ("2002-07-06", 3),
    ("2002-08-31", 1),
    ("2002-12-07", 1),
    ("2003-02-23", 7),
    ("2004-06-20", 6),
    ("2004-06-26", 4),
    ("2004-07-04", 7),
)
HEADING = re.compile(r"제목\s*:\s*\d{4}년\d{2}월\d{2}일[^\n]*?제\s*(\d+)경주")


def main() -> None:
    RAW_DIR.mkdir(exist_ok=True)
    rows = []
    for date, number in TARGETS:
        compact = date.replace("-", "")
        source_name = f"chollian/jeju/jungbo/rcresult/{compact}dacom11.rpt"
        query = urllib.parse.urlencode({"fn": source_name, "meet": "2"})
        path = RAW_DIR / f"{compact}dacom11.rpt"
        if path.exists():
            raw = path.read_bytes()
        else:
            request = urllib.request.Request(f"{URL}?{query}", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 200:
                    raise ValueError(f"HTTP {response.status}: {date}")
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError(f"Oversized RPT response: {date}")
            path.write_bytes(raw)
        headings = sorted({int(value) for value in HEADING.findall(raw.decode("cp949", errors="replace"))})
        if number in headings:
            raise ValueError(f"Target unexpectedly present in RPT: {date} {number}R")
        row = {
            "race_date": date,
            "race_number": number,
            "request_url": URL,
            "request_query": {"fn": source_name, "meet": "2"},
            "response_bytes": len(raw),
            "response_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_rpt_file": str(path.relative_to(HERE)),
            "result_headings": headings,
            "later_result_heading_present": any(value > number for value in headings),
            "checked_on": "2026-09-30",
        }
        rows.append(row)
        print(f"{date} {number}R: {len(raw)} bytes, headings {headings}", flush=True)
    with EVIDENCE.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
