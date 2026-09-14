"""Print bounded sealed-sample source snippets for human review; no DB or network."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MANIFEST = Path("data/experiments/confirmed_starter_e9a_20260913/population_manifest.json")
FOCUS = (
    "출발이 늦",
    "늦게 나",
    "진로",
    "방해",
    "접촉",
    "부딪",
    "밀렸",
    "주행이 불편",
    "공간이 여의치",
    "제어",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=20)
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    selected = sorted(
        (row for row in manifest["population"] if row["sample_group"]),
        key=lambda row: row["race_id"],
    )
    for row in selected[args.start : args.end]:
        if not row["source_local_path"]:
            print(row["race_id"], "MISSING SOURCE")
            continue
        payload = json.loads(Path(row["source_local_path"]).read_text(encoding="utf-8"))
        items = payload["response"]["body"]["items"]["item"]
        item = next((item for item in items if int(item["rcNo"]) == row["race_number"]), None)
        if item is None:
            print(row["race_id"], "MISSING ITEM")
            continue
        text = " ".join(str(item.get(field) or "") for field in ("judgement", "addJudgement"))
        bullets = [part.strip() for part in text.split("●") if part.strip()]
        focused = [part for part in bullets if any(cue in part for cue in FOCUS)]
        print(
            "\n",
            row["race_id"],
            row["sample_group"],
            row["race_date"],
            row["race_number"],
            "focused",
            len(focused),
            "total",
            len(bullets),
        )
        for index, part in enumerate(focused[:5], 1):
            print(index, part[:240].replace("\n", " "))


if __name__ == "__main__":
    main()
