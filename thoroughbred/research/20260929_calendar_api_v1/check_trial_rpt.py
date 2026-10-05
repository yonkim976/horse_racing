"""Check API trial execution dates against archived KRA dacom23 report contents."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from horse_racing.parsers.running_trials import parse_running_trial_report


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
API = {(int(row["source_meet"]), row["date"])
       for row in csv.DictReader((HERE / "trial_sessions.csv").open(encoding="utf-8"))}


def main() -> None:
    report_dates = set()
    date_mismatches = []
    parse_errors = []
    for meet in (1, 3):
        for path in sorted((ROOT / f"data/raw/kra_text/dacom23/meet={meet}").glob(
                "year=20*/month=*/day=*/*.rpt")):
            if path.parent.parent.parent.name < "year=2010":
                continue
            try:
                blocks = parse_running_trial_report(path.read_bytes(), meet=meet)
            except Exception as exc:
                parse_errors.append({"path": str(path.relative_to(ROOT)), "error_type": type(exc).__name__})
                continue
            content_dates = {block.trial_date.strftime("%Y%m%d") for block in blocks}
            for day in content_dates:
                if "20100101" <= day <= "20260929":
                    report_dates.add((meet, day))
            if content_dates != {path.stem[:8]}:
                date_mismatches.append({"path": str(path.relative_to(ROOT)),
                                        "filename_date": path.stem[:8],
                                        "report_dates": sorted(content_dates)})
    out = {"api_trial_day_count": len(API), "rpt_content_day_count": len(report_dates),
           "api_only_days": [list(key) for key in sorted(API - report_dates)],
           "rpt_only_days": [list(key) for key in sorted(report_dates - API)],
           "rpt_filename_date_mismatches": date_mismatches,
           "rpt_parse_errors": parse_errors,
           "interpretation": "RPT is secondary validation; API trainDate remains the primary trial date."}
    (HERE / "trial_rpt_crosscheck.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print({key: len(value) if isinstance(value, list) else value for key, value in out.items()
           if key != "interpretation"})


if __name__ == "__main__":
    main()
