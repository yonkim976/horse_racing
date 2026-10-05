"""Re-fetch the 19 unresolved Jeju result pages into a new, immutable archive."""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[3]
PREVIOUS = ROOT / "jeju/research/20261002_section_remaining_review"
SOURCE = "https://race.kra.co.kr/raceScore/ScoretableDetailList.do"


def clean(cell) -> str:
    return re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).replace("\xa0", " ").strip()


def table_rows(table):
    return [
        [clean(cell) for cell in row.find_all(["th", "td"], recursive=False)]
        for row in table.find_all("tr")
        if row.find_all(["th", "td"], recursive=False)
    ]


def extract(blob: bytes, encoding: str, key: dict) -> dict:
    soup = BeautifulSoup(blob, "html.parser", from_encoding=encoding or "euc-kr")
    tables = [(table, table_rows(table)) for table in soup.find_all("table")]
    heading = None
    result_rows = None
    passing_rows = None
    group_rows = None
    for table, rows in tables:
        joined = " ".join(cell for row in rows for cell in row)
        match = re.search(r"(\d{4})년\s+(\d{2})월\s+(\d{2})일.*?제\s*(\d+)경주\s+제주", joined)
        if match:
            found = (f"{match[1]}-{match[2]}-{match[3]}", int(match[4]))
            if found == (key["date"], int(key["race_no"])):
                heading = rows
        if rows and rows[0][:3] and "순위" in rows[0] and "마번" in rows[0] and "마명" in rows[0]:
            result_rows = rows
        if rows and "S1F-1C-2C-3C-4C-G1F" in " ".join(rows[0]):
            passing_rows = rows
        if rows and rows[0] and rows[0][0] == "통과순위":
            group_rows = rows

    ids_by_name = {}
    for anchor in soup.find_all("a", href=True):
        match = re.fullmatch(r"javascript:goHorse\('(\d+)','2'\)", anchor["href"].strip())
        if match:
            ids_by_name[anchor.get_text(strip=True)] = match[1]

    finish_by_number = {}
    if result_rows:
        for row in result_rows[1:]:
            if len(row) >= 3 and row[1].isdigit():
                finish_by_number[int(row[1])] = {"finish_rank_raw": row[0], "horse_name_raw": row[2]}

    runner_by_number = {}
    if passing_rows:
        for row in passing_rows[1:]:
            if len(row) < 3 or not row[1].isdigit():
                continue
            number = int(row[1])
            runner_by_number[number] = {
                "program_no": number,
                "horse_name_raw": finish_by_number.get(number, {}).get("horse_name_raw"),
                "horse_id": ids_by_name.get(finish_by_number.get(number, {}).get("horse_name_raw", "")),
                "finish_rank_raw": finish_by_number.get(number, {}).get("finish_rank_raw"),
                "passing_order_path_raw": row[2],
                "six_point_order_raw": row[2].split("-"),
                "point_cells_raw": row[3:9],
            }
    # Include result-table entries even if the individual passing-order table omits a row.
    for number, finish in finish_by_number.items():
        if number not in runner_by_number:
            runner_by_number[number] = {
                "program_no": number,
                "horse_name_raw": finish["horse_name_raw"],
                "horse_id": ids_by_name.get(finish["horse_name_raw"]),
                "finish_rank_raw": finish["finish_rank_raw"],
                "passing_order_path_raw": None,
                "six_point_order_raw": None,
                "point_cells_raw": None,
            }
    group_map = {}
    if group_rows:
        for row in group_rows:
            if len(row) < 2:
                continue
            label = row[0].replace(":", "").strip()
            point = {"S-1F": "S1F", "1코너": "1C", "2코너": "2C", "3코너": "3C", "4코너": "4C", "G-1F": "G1F"}.get(label)
            if point:
                group_map[point] = row[-1].strip()

    report_texts = [pre.get_text("\n", strip=True) for pre in soup.find_all("pre") if pre.get_text("\n", strip=True)]
    return {
        "title": soup.title.get_text(strip=True) if soup.title else None,
        "heading": heading,
        "identity_verified": heading is not None,
        "result_runner_count": len(finish_by_number),
        "passing_runner_count": len(runner_by_number),
        "runners": [runner_by_number[n] for n in sorted(runner_by_number)],
        "passing_groups_by_point": group_map,
        "official_report_texts": report_texts,
    }


def main() -> None:
    keys = json.loads((PREVIOUS / "remaining_website_internal_order_conflicts.json").read_text())
    unique = sorted({(r["date"], int(r["race_no"])) for r in keys})
    OUT.joinpath("raw_pages").mkdir(parents=True, exist_ok=True)
    old_records = json.loads((PREVIOUS / "website_evidence.json").read_text())
    old_by_key = {(r["date"], int(r["race_no"])): r for r in old_records}
    records = []
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for index, (date, race_no) in enumerate(unique, 1):
            day = date.replace("-", "")
            params = {"Act": "04", "Sub": "1", "meet": "2", "realRcDate": day, "realRcNo": str(race_no)}
            request = client.build_request("GET", SOURCE, params=params)
            url = str(request.url)
            record = {
                "date": date,
                "race_no": race_no,
                "meet_code": 2,
                "meet_label": "제주",
                "url": url,
                "retrieved_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            try:
                response = client.send(request)
                blob = response.content
                path = OUT / "raw_pages" / f"{day}_{race_no}.html"
                with path.open("xb") as f:
                    f.write(blob)
                encoding = response.encoding
                parsed = extract(blob, encoding, {"date": date, "race_no": race_no})
                old = old_by_key[(date, race_no)]
                old_path = PREVIOUS / old["raw_path"]
                old_blob = old_path.read_bytes()
                old_parsed = extract(old_blob, "euc-kr", {"date": date, "race_no": race_no})
                raw_changed = hashlib.sha256(old_blob).hexdigest() != hashlib.sha256(blob).hexdigest()
                old_runners = {r["program_no"]: r for r in old_parsed["runners"]}
                new_runners = {r["program_no"]: r for r in parsed["runners"]}
                runner_differences = []
                for number in sorted(set(old_runners) | set(new_runners)):
                    before = old_runners.get(number)
                    after = new_runners.get(number)
                    if before != after:
                        runner_differences.append({"program_no": number, "previous": before, "current": after})
                old_report = old_parsed["official_report_texts"]
                new_report = parsed["official_report_texts"]
                record.update({
                    "http_status": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "content_encoding": response.headers.get("content-encoding"),
                    "declared_charset": encoding,
                    "body_bytes": len(blob),
                    "raw_path": path.relative_to(OUT).as_posix(),
                    "sha256": hashlib.sha256(blob).hexdigest(),
                    **parsed,
                    "previous_sha256": old["sha256"],
                    "raw_body_changed_vs_2026_10_02": raw_changed,
                    "previous_identity_verified": old["identity_verified"],
                    "previous_runner_count": old_parsed["result_runner_count"],
                    "runner_differences_vs_2026_10_02": runner_differences,
                    "passing_groups_changed_vs_2026_10_02": old_parsed["passing_groups_by_point"] != parsed["passing_groups_by_point"],
                    "official_report_changed_vs_2026_10_02": old_report != new_report,
                    "http_status_ok": response.status_code == 200,
                    "all_runners_have_horse_id": bool(parsed["runners"]) and all(r["horse_id"] for r in parsed["runners"]),
                    "all_six_point_orders_present": bool(parsed["runners"]) and all(len(r["six_point_order_raw"] or []) == 6 for r in parsed["runners"]),
                    "all_six_groups_present": set(parsed["passing_groups_by_point"]) == {"S1F", "1C", "2C", "3C", "4C", "G1F"},
                })
            except Exception as exc:
                record.update({"error_type": type(exc).__name__, "error": str(exc), "identity_verified": False})
            records.append(record)
            print(json.dumps({"checked": index, "total": len(unique), "date": date, "race_no": race_no, "http_status": record.get("http_status"), "identity_verified": record.get("identity_verified")}), flush=True)
            time.sleep(0.2)
    path = OUT / "official_pages_manifest.json"
    with path.open("x", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({
        "pages": len(records),
        "http_200": sum(r.get("http_status_ok", False) for r in records),
        "event_identity_verified": sum(r.get("identity_verified", False) for r in records),
        "complete_runner_ids": sum(r.get("all_runners_have_horse_id", False) for r in records),
        "complete_six_point_paths": sum(r.get("all_six_point_orders_present", False) for r in records),
        "complete_six_groups": sum(r.get("all_six_groups_present", False) for r in records),
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
