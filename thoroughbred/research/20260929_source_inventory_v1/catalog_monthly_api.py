"""Find monthly API capture coverage from first-page response headers."""

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "data/raw/kra_api_monthly"
OUTPUT = Path(__file__).with_name("monthly_api_capture_coverage.csv")


def main():
    rows = []
    for kind in ("horse_training", "start_training"):
        for meet_dir in sorted((API / kind).glob("meet_*")):
            months, nonempty = [], []
            for folder in sorted(meet_dir.iterdir()):
                page = folder / "page_0001.json"
                if not page.is_file():
                    continue
                months.append(folder.name)
                with page.open("rb") as stream:
                    prefix = stream.read(200)
                if b'"resultCode":"00"' not in prefix:
                    raise ValueError(f"Unexpected API response header: {page}")
                if b'"items":""' not in prefix:
                    nonempty.append(folder.name)
            rows.append(
                [
                    kind,
                    meet_dir.name,
                    len(months),
                    min(months) if months else "",
                    max(months) if months else "",
                    len(nonempty),
                    min(nonempty) if nonempty else "",
                    max(nonempty) if nonempty else "",
                    "First page only; nonempty month does not establish complete month or event-date coverage.",
                ]
            )
    with OUTPUT.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "source_kind", "meet_dir", "month_directories", "first_month_directory", "last_month_directory",
                "nonempty_first_page_months", "first_nonempty_month", "last_nonempty_month", "limitation",
            ]
        )
        writer.writerows(rows)
    print(f"source_meet_rows={len(rows)} output={OUTPUT}")


if __name__ == "__main__":
    main()
