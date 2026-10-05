"""Parse locally archived official KRA starting-exam HTML without network access."""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path


HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
DERIVED = HERE / "derived"


class TableRows(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict] = []
        self.row: dict | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "tr":
            self.row = {"position": len(self.rows) + 1, "cells": [], "links": []}
        elif tag == "td" and self.row is not None:
            self.cell = []
        elif tag == "a" and self.row is not None:
            self.row["links"].append(
                {key: attributes.get(key) for key in ("href", "onclick") if attributes.get(key)}
            )

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.cell is not None and self.row is not None:
            self.row["cells"].append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
            self.cell = None


def read_artifact(path: Path, *, kind: str, date: str | None = None, round_no: int | None = None) -> tuple[list[dict], dict]:
    raw = path.read_bytes()
    sha256 = hashlib.sha256(raw).hexdigest()
    parser = TableRows()
    parser.feed(raw.decode("euc-kr", errors="replace"))
    parsed: list[dict] = []

    for source_row in parser.rows:
        cells = source_row["cells"]
        if kind == "listing":
            if len(cells) != 7 or not re.fullmatch(r"\d{4}/\d{2}/\d{2}", cells[2]):
                continue
            rounds = []
            for link in source_row["links"]:
                match = re.search(r"goPage1\([\"'](\d+)[\"'],[\"'](\d{8})[\"'],[\"']([^\"']+)", link.get("onclick", ""))
                if match:
                    rounds.append({"round": int(match.group(1)), "date": match.group(2), "type": match.group(3), "link": link})
            parsed.append({
                "source_row_position": source_row["position"],
                "section_type": cells[1],
                "date": cells[2].replace("/", ""),
                "listed_runner_count": cells[4],
                "listed_passed_count": cells[5],
                "listed_pass_rate": cells[6],
                "rounds": rounds,
                "source_links": source_row["links"],
            })
        elif kind == "detail":
            if len(cells) != 10:
                continue
            horse_link = None
            horse_id = None
            for link in source_row["links"]:
                text = " ".join((link.get("href", ""), link.get("onclick", "")))
                match = re.search(r"goPage1\([\"'](\d+)[\"']", text)
                if match:
                    horse_id, horse_link = match.group(1), link
                    break
            if horse_id is None:
                continue
            parsed.append({
                "date": date,
                "round": round_no,
                "source_row_position": source_row["position"],
                "horse_id": horse_id,
                "horse_id_link": horse_link,
                "horse_number_raw": cells[0],
                "horse_name_raw": cells[1],
                "inspection_reason_raw": cells[2],
                "sex_raw": cells[3],
                "age_raw": cells[4],
                "rider_raw": cells[5],
                "trainer_raw": cells[6],
                "owner_raw": cells[7],
                "judgement_raw": cells[8],
                "failure_reason_raw": cells[9],
            })
        else:
            raise ValueError(f"Unsupported artifact kind: {kind}")

    metadata = {
        "path": str(path.relative_to(HERE)),
        "kind": kind,
        "bytes": len(raw),
        "sha256": sha256,
        "parsed_rows": len(parsed),
        "date": date,
        "round": round_no,
    }
    for row in parsed:
        row.update({"source_path": metadata["path"], "source_sha256": sha256, "source_bytes": len(raw)})
    return parsed, metadata


def main() -> None:
    DERIVED.mkdir(exist_ok=True)
    listing_records = []
    detail_records = []
    artifacts = []

    for page_no in (1, 2):
        records, metadata = read_artifact(RAW / "list_pages" / f"page_{page_no:04d}.html", kind="listing")
        for record in records:
            record["page_index"] = page_no
        listing_records.extend(records)
        artifacts.append(metadata)

    detail, metadata = read_artifact(
        RAW / "detail_pages" / "20260823_1.html", kind="detail", date="20260823", round_no=1
    )
    detail_records.extend(detail)
    artifacts.append(metadata)

    (DERIVED / "listing_rows.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in listing_records), encoding="utf-8"
    )
    (DERIVED / "detail_rows.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in detail_records), encoding="utf-8"
    )
    output = {"artifacts": artifacts, "listing_dates": len(listing_records), "listed_rounds": sum(len(row["rounds"]) for row in listing_records), "sample_detail_rows": len(detail_records)}
    (DERIVED / "parse_summary.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
