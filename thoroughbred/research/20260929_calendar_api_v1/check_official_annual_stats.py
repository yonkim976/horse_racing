"""Cross-check API execution counts with KRA's published 2021–2025 statistics."""

from __future__ import annotations

import csv
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE_URL = "https://race.kra.co.kr/globalEn/racingStatistic.do"
# KRA Racing Statistics page, NUMBER OF FIXTURES / NUMBER OF RACES tables.
# Values were read on 2026-09-29. Keep this independent from the API totals.
OFFICIAL = {
    (1, 2021): (85, 865), (1, 2022): (96, 985), (1, 2023): (100, 1051),
    (1, 2024): (98, 1050), (1, 2025): (98, 1042),
    (3, 2021): (85, 588), (3, 2022): (96, 694), (3, 2023): (98, 724),
    (3, 2024): (98, 724), (3, 2025): (98, 716),
}


def main() -> None:
    with (HERE / "annual_summary.csv").open(encoding="utf-8", newline="") as stream:
        summary = {(int(row["meet"]), int(row["year"])): row for row in csv.DictReader(stream)}
    output = []
    for key, (official_days, official_races) in sorted(OFFICIAL.items()):
        api = summary[key]
        api_days = int(api["executed_race_days_with_plan"])
        api_races = int(api["executed_races_with_plan"])
        passed = api_days == official_days and api_races == official_races
        output.append({"meet": key[0], "year": key[1],
                       "kra_official_fixture_days": official_days,
                       "api_confirmed_fixture_days": api_days,
                       "kra_official_races": official_races,
                       "api_confirmed_races": api_races,
                       "matches": int(passed), "source_url": SOURCE_URL})
    with (HERE / "official_annual_stats_crosscheck.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    if not all(row["matches"] for row in output):
        raise ValueError("API annual execution totals differ from KRA official statistics")
    print(f"Official annual statistics match: {len(output)} venue-year pairs")


if __name__ == "__main__":
    main()
