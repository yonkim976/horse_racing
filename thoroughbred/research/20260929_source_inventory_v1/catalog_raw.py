"""Inventory raw capture file families without interpreting file contents."""

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data/raw"
OUTPUT = Path(__file__).with_name("raw_source_families.csv")


def path_year(part: str):
    """Return a year encoded by a directory, without treating it as a record date."""
    match = re.fullmatch(r"(?:year=|year_|)(19\d{2}|20\d{2})(?:\d{2})?", part)
    return int(match.group(1)) if match else None


def main() -> None:
    families = defaultdict(lambda: {"files": 0, "bytes": 0, "extensions": Counter(), "year_dirs": set()})
    for path in RAW.rglob("*"):
        if not path.is_file():
            continue
        parts = path.relative_to(RAW).parts
        family = "/".join(parts[:2]) if len(parts) >= 3 else parts[0]
        info = families[family]
        info["files"] += 1
        info["bytes"] += path.stat().st_size
        info["extensions"][path.suffix.lower() or "(none)"] += 1
        info["year_dirs"].update(
            year for part in parts[2:-1] if (year := path_year(part)) is not None
        )

    with OUTPUT.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["family", "file_count", "total_bytes", "extensions_json", "year_directory_min", "year_directory_max", "note"]
        )
        for family, info in sorted(families.items()):
            years = info["year_dirs"]
            writer.writerow(
                [
                    f"data/raw/{family}",
                    info["files"],
                    info["bytes"],
                    json.dumps(dict(sorted(info["extensions"].items())), ensure_ascii=False),
                    min(years) if years else "",
                    max(years) if years else "",
                    "Directory year is not verified event-date coverage.",
                ]
            )
    print(f"families={len(families)} files={sum(x['files'] for x in families.values())} output={OUTPUT}")


if __name__ == "__main__":
    main()
