"""Recheck the 24 locally unarchived trial rows on KRA's public score page."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SOURCE = HERE / "trial_jockey_missing_audit.jsonl"
RAW = HERE / "raw_official_web_missing_24"
OUTPUT = HERE / "official_web_missing_24.jsonl"
MANIFEST = HERE / "official_web_missing_24_manifest.json"
URL = "https://race.kra.co.kr/referee/RacingTrainCheckScoreTable.do"
HORSE_LINK = re.compile(r"goPage1\('([0-9]+)'\s*,\s*'([0-9]+)'\)")
JOCKEY_LINK = re.compile(r"goPage2\('([0-9]+)'\s*,\s*'([0-9]+)'")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def get_score_page(meet: int, date: str, trial_no: int) -> bytes:
    if meet not in (1, 3) or not re.fullmatch(r"20\d{6}", date) or not 1 <= trial_no <= 20:
        raise ValueError("Unexpected official score request key")
    body = urlencode({"meet": meet, "trno": trial_no, "date": date,
                      "Act": "06", "Sub": "7"}).encode("ascii")
    request = Request(URL, data=body, method="POST",
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(request, timeout=30) as response:
        if response.status != 200 or urlparse(response.url).hostname != "race.kra.co.kr":
            raise ValueError("Unexpected KRA score response")
        payload = response.read(5_000_001)
    if len(payload) > 5_000_000:
        raise ValueError("Oversized KRA score response")
    return payload


def parse_score_page(payload: bytes, date: str, trial_no: int) -> list[dict]:
    soup = BeautifulSoup(payload.decode("euc-kr", errors="replace"), "html.parser")
    title = soup.get_text(" ", strip=True)
    date_label = f"{date[:4]}년 {int(date[4:6]):02d}월 {int(date[6:]):02d}일"
    if date_label not in title or f"{trial_no}경주" not in title:
        raise ValueError(f"Official score page did not show requested date/trial: {date} {trial_no}")
    caption = soup.find("caption", string=lambda value: value and "주행심사결과를 순위" in value)
    if caption is None:
        raise ValueError("Official trial score table not found")
    table = caption.find_parent("table")
    if table is None or table.tbody is None:
        raise ValueError("Official trial score rows not found")
    rows = []
    for tr in table.tbody.find_all("tr", recursive=False):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 9:
            continue
        program_text = cells[1].get_text(" ", strip=True)
        if not program_text.isdigit():
            continue
        horse_link = cells[2].find("a", onclick=HORSE_LINK)
        horse_match = HORSE_LINK.search(horse_link.get("onclick", "")) if horse_link else None
        jockey_link = cells[8].find("a", onclick=JOCKEY_LINK)
        jockey_match = JOCKEY_LINK.search(jockey_link.get("onclick", "")) if jockey_link else None
        rows.append({
            "horse_program_no": int(program_text),
            "horse_name": cells[2].get_text(" ", strip=True),
            "horse_id": horse_match.group(1) if horse_match else None,
            "jockey_name": cells[8].get_text(" ", strip=True) or None,
            "jockey_id": jockey_match.group(1) if jockey_match else None,
            "finish_time": cells[12].get_text(" ", strip=True) if len(cells) > 12 else None,
            "row_text": tr.get_text(" ", strip=True),
        })
    return rows


def main() -> None:
    targets = [json.loads(line) for line in SOURCE.open(encoding="utf-8")
               if json.loads(line)["rpt_jockey_supplement_status"] == "unavailable_no_local_rpt_day"]
    if len(targets) != 24:
        raise ValueError(f"Expected 24 targets, found {len(targets)}")
    groups = defaultdict(list)
    for target in targets:
        groups[(int(target["source_meet_query"]), target["api_trainDate"],
                int(target["api_trainNo"]))].append(target)
    RAW.mkdir(exist_ok=True)
    observations = []
    captures = []
    for (meet, date, trial_no), members in sorted(groups.items()):
        payload = get_score_page(meet, date, trial_no)
        path = RAW / f"meet_{meet}_date_{date}_trial_{trial_no}.html"
        path.write_bytes(payload)
        digest = sha256_bytes(payload)
        rows = parse_score_page(payload, date, trial_no)
        captures.append({"meet": meet, "date": date, "trial_no": trial_no,
                         "source_file": relative(path), "sha256": digest,
                         "score_rows": len(rows)})
        by_number = defaultdict(list)
        for row in rows:
            by_number[row["horse_program_no"]].append(row)
        for target in members:
            matches = by_number[int(target["api_chulNo"])]
            if len(matches) != 1:
                raise ValueError(f"No unique official score row for {target['participant_row_id']}")
            match = matches[0]
            if match["horse_id"] != target["api_hrNo"]:
                raise ValueError(f"Official horse ID mismatch for {target['participant_row_id']}")
            observations.append({
                "participant_row_id": target["participant_row_id"],
                "meet": meet, "date": date, "trial_no": trial_no,
                "horse_program_no": int(target["api_chulNo"]),
                "api_horse_id": target["api_hrNo"],
                "api_horse_name": target["api_hrName"],
                "official_web_horse_id": match["horse_id"],
                "official_web_horse_name": match["horse_name"],
                "official_web_jockey_id": match["jockey_id"],
                "official_web_jockey_name": match["jockey_name"],
                "official_web_finish_time": match["finish_time"],
                "official_web_row_text": match["row_text"],
                "official_web_source_file": relative(path),
                "official_web_source_sha256": digest,
                "official_web_source_url": URL,
                "official_web_request_form": {"meet": meet, "trno": trial_no,
                                              "date": date, "Act": "06", "Sub": "7"},
                "resolution_status": "exact_official_horse_id_and_event_key",
            })
    observations.sort(key=lambda row: row["participant_row_id"])
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as stream:
        for row in observations:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    MANIFEST.write_text(json.dumps({"source": relative(SOURCE),
                                    "source_sha256": sha256_bytes(SOURCE.read_bytes()),
                                    "official_score_url": URL, "captures": captures,
                                    "observations": len(observations),
                                    "official_jockey_id_count": sum(bool(row["official_web_jockey_id"])
                                                                    for row in observations),
                                    "official_jockey_name_count": sum(bool(row["official_web_jockey_name"])
                                                                      for row in observations),
                                    "output": relative(OUTPUT),
                                    "output_sha256": sha256_bytes(OUTPUT.read_bytes())},
                                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"requests": len(captures), "targets": len(observations),
                      "with_jockey_id": sum(bool(row["official_web_jockey_id"])
                                            for row in observations)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
