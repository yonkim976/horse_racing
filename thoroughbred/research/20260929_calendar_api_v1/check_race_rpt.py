"""Cross-check KRA race RPT body dates/venues against API-confirmed race dates.

RPT files are partial archive evidence, not the primary schedule source.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RPT = ROOT / "data/raw/kra_text/dacom11"
VENUE = {"서울": 1, "부산": 3, "부경": 3, "영천": 4}


def main() -> None:
    with (HERE / "daily_calendar.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    executed = {(int(row["meet"]), row["date"].replace("-", "")) for row in rows
                if int(row["executed_race_count"]) > 0}
    rpt_days: set[tuple[int, str]] = set()
    parse_errors = []
    path_venue_mismatches = []
    for path in sorted(RPT.rglob("*.rpt")):
        if "meet=2" in path.parts:
            continue
        content = path.read_bytes().decode("cp949", errors="replace")
        date_match = re.search(r"제목\s*:\s*(\d{2})년\s*(\d{2})월\s*(\d{2})일", content[:1000])
        venue_match = re.search(r"\((서울|부산|부경|영천)\)", content[:1000])
        if not date_match or not venue_match:
            parse_errors.append(str(path.relative_to(ROOT)))
            continue
        year, month, day = date_match.groups()
        date = f"20{year}{month}{day}"
        meet = VENUE[venue_match.group(1)]
        rpt_days.add((meet, date))
        path_meet = int(re.search(r"meet=(\d+)", str(path)).group(1))
        if path_meet != meet:
            path_venue_mismatches.append({"file": str(path.relative_to(ROOT)),
                                          "path_meet": path_meet, "body_meet": meet, "body_date": date})
    years = []
    for year in range(2010, 2027):
        api = {x for x in executed if x[1].startswith(str(year))}
        rpt = {x for x in rpt_days if x[1].startswith(str(year))}
        years.append({"year": year, "api_executed_venue_days": len(api),
                      "rpt_body_venue_days": len(rpt),
                      "api_only_days": len(api - rpt), "rpt_only_days": len(rpt - api)})
    output = {"source": "data/raw/kra_text/dacom11 (partial local archive)",
              "rpt_venue_days": len(rpt_days), "api_executed_venue_days": len(executed),
              "api_only_venue_days": sorted([{"meet": m, "date": d} for m, d in executed - rpt_days],
                                             key=lambda x: (x["date"], x["meet"])),
              "rpt_only_venue_days": sorted([{"meet": m, "date": d} for m, d in rpt_days - executed],
                                             key=lambda x: (x["date"], x["meet"])),
              "path_venue_mismatches": path_venue_mismatches,
              "parse_errors": parse_errors, "annual_coverage": years}
    (HERE / "race_rpt_crosscheck.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print({k: len(v) if isinstance(v, list) else v for k, v in output.items()
           if k not in {"api_only_venue_days", "annual_coverage"}})


if __name__ == "__main__":
    main()
