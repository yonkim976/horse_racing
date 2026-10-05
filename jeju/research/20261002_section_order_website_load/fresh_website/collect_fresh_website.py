"""Fetch only the eight explicitly approved KRA Jeju result pages, without cache reuse."""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent
GAP_KEYS = (
    ("2025-01-10", 1),
    ("2025-05-16", 8),
    ("2025-05-23", 3),
    ("2025-06-27", 4),
    ("2025-07-04", 5),
    ("2026-09-11", 5),
)
CORRECTION_KEYS = (("2025-10-17", 7), ("2026-03-06", 8))
APPROVED_KEYS = GAP_KEYS + CORRECTION_KEYS
BASE_URL = "https://race.kra.co.kr/raceScore/ScoretableDetailList.do"
ORDER_FIELDS = {
    "S1F": 3,
    "1C": 4,
    "2C": 5,
    "3C": 6,
    "4C": 7,
    "G1F": 9,
}


def clean(cell) -> str:
    return re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()


def table_rows(table) -> list[list[str]]:
    rows = [
        [clean(cell) for cell in tr.find_all(["th", "td"], recursive=False)]
        for tr in table.find_all("tr")
    ]
    return [row for row in rows if row]


def extract(body: bytes, date: str, race_no: int) -> dict:
    soup = BeautifulSoup(body, "html.parser")
    heading = None
    tables = []
    for table in soup.find_all("table"):
        rows = table_rows(table)
        joined = " ".join(value for row in rows for value in row)
        match = re.search(
            r"(\d{4})년\s+(\d{2})월\s+(\d{2})일.*?제(\d+)경주\s+제주", joined
        )
        if match:
            found_date = f"{match[1]}-{match[2]}-{match[3]}"
            if found_date == date and int(match[4]) == race_no:
                heading = rows
        if rows and (
            ("순위" in rows[0] and "마번" in rows[0])
            or "통과순위" in rows[0]
            or "펄롱타임" in rows[0]
        ):
            caption = table.find("caption")
            tables.append(
                {
                    "caption": clean(caption) if caption else None,
                    "rows": rows,
                }
            )
    return {
        "title": soup.title.get_text(strip=True) if soup.title else None,
        "heading": heading,
        "tables": tables,
        "identity_verified": heading is not None,
    }


def build_url(date: str, race_no: int) -> str:
    query = urlencode(
        {
            "Act": "04",
            "Sub": "1",
            "meet": "2",
            "realRcDate": date.replace("-", ""),
            "realRcNo": str(race_no),
        }
    )
    return f"{BASE_URL}?{query}"


def extract_ids_and_rank_path(body: bytes) -> tuple[dict[int, dict], dict[int, str], dict[str, str]]:
    soup = BeautifulSoup(body, "html.parser")
    ids_by_name = {}
    for anchor in soup.find_all("a", href=True):
        match = re.fullmatch(r"javascript:goHorse\('(\d+)','2'\)", anchor["href"])
        if match:
            name = anchor.get_text(strip=True).removeprefix("★")
            ids_by_name[name] = match[1]

    rank_rows = {}
    names_by_program = {}
    for table in soup.find_all("table"):
        rows = table_rows(table)
        if not rows:
            continue
        if rows[0][:3] == ["순위", "마번", "마명"]:
            for row in rows[1:]:
                if len(row) < 3:
                    continue
                try:
                    names_by_program[int(row[1])] = row[2].removeprefix("★")
                except ValueError:
                    continue
        if not ("순위" in rows[0] and "마번" in rows[0]):
            continue
        if not any("S1F-1C-2C-3C-4C-G1F" in header for header in rows[0]):
            continue
        for row in rows[1:]:
            if len(row) < 3:
                continue
            try:
                program_no = int(row[1])
            except ValueError:
                continue
            rank_parts = [part.strip() for part in row[2].split("-")]
            if len(rank_parts) == 7 and not rank_parts[-1]:
                rank_parts.pop()
            if len(rank_parts) != 6:
                continue
            path = {}
            for (point, _), raw in zip(ORDER_FIELDS.items(), rank_parts):
                match = re.match(r"^\s*(\d+)", raw)
                path[point] = {
                    "raw": raw,
                    "rank": int(match[1]) if match else None,
                }
            rank_rows[program_no] = {"row": row, "six_rank_path": path}
    return rank_rows, names_by_program, ids_by_name


def main() -> None:
    if any((ROOT / f"{date.replace('-', '')}_{race_no}.html").exists() for date, race_no in APPROVED_KEYS):
        raise FileExistsError("Fresh raw page path already exists; refusing to overwrite it.")
    for name in ("evidence.json", "candidate_crosscheck.json", "section_gap_blank_summary.json"):
        if (ROOT / name).exists():
            raise FileExistsError(f"Refusing to overwrite {name}.")

    candidates_path = (
        ROOT.parents[1]
        / "20261002_section_remaining_review"
        / "positive_order_website_correction_candidates.json"
    )
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    candidates_by_key = {}
    for candidate in candidates:
        candidates_by_key.setdefault((candidate["date"], candidate["race_no"]), []).append(candidate)
    if set(candidates_by_key) != set(CORRECTION_KEYS) or len(candidates) != 14:
        raise ValueError("The approved candidate input does not contain the expected two pages and 14 records.")

    evidence = []
    gap_summary = []
    candidate_checks = []
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for index, (date, race_no) in enumerate(APPROVED_KEYS):
            url = build_url(date, race_no)
            retrieved_at = datetime.now(UTC).isoformat(timespec="seconds")
            filename = f"{date.replace('-', '')}_{race_no}.html"
            path = ROOT / filename
            response = client.get(url)
            body = response.content
            with path.open("xb") as raw_file:
                raw_file.write(body)

            try:
                body.decode("utf-8")
                utf8_valid = True
            except UnicodeDecodeError:
                utf8_valid = False
            charset_match = re.search(r"charset\s*=\s*['\"]?([^;\s'\"]+)", response.headers.get("content-type", ""), re.I)
            identity = extract(body, date, race_no)
            record = {
                "date": date,
                "race_no": race_no,
                "url": url,
                "retrieved_at_utc": retrieved_at,
                "http_status": response.status_code,
                "raw_path": filename,
                "sha256": hashlib.sha256(body).hexdigest(),
                "bytes": len(body),
                "title": identity["title"],
                "heading": identity["heading"],
                "tables": identity["tables"],
                "identity_verified": identity["identity_verified"] and response.status_code == 200,
                "fetch_mode": "fresh_get_no_cache_reuse",
                "response_url": str(response.url),
                "content_type": response.headers.get("content-type"),
                "declared_charset": charset_match[1] if charset_match else None,
                "utf8_valid": utf8_valid,
            }
            evidence.append(record)

            if (date, race_no) in GAP_KEYS:
                section_table = next(
                    (
                        item["rows"]
                        for item in record["tables"]
                        if item["rows"] and "펄롱타임" in item["rows"][0]
                    ),
                    [],
                )
                rows_by_label = {
                    row[0]: row[1:]
                    for row in section_table
                    if row and row[0] in {"펄롱타임", "통과거리", "통과타임"}
                }
                blank_by_label = {
                    label: bool(rows_by_label.get(label)) and all(not value for value in rows_by_label[label])
                    for label in ("펄롱타임", "통과거리", "통과타임")
                }
                gap_summary.append(
                    {
                        "date": date,
                        "race_no": race_no,
                        "http_status": response.status_code,
                        "identity_verified": record["identity_verified"],
                        "race_level_section_table_found": bool(section_table),
                        "rows": [
                            {"label": label, "values": rows_by_label.get(label, [])}
                            for label in ("펄롱타임", "통과거리", "통과타임")
                        ],
                        "blank_by_label": blank_by_label,
                        "all_three_rows_blank": bool(blank_by_label) and all(blank_by_label.values()),
                    }
                )

            for candidate in candidates_by_key.get((date, race_no), []):
                rank_rows, names_by_program, ids_by_name = extract_ids_and_rank_path(body)
                runner = rank_rows.get(int(candidate["program_no"]))
                website_name = names_by_program.get(int(candidate["program_no"]))
                linked_horse_id = ids_by_name.get(website_name) if website_name else None
                selected_rank = (
                    runner["six_rank_path"][candidate["point"]]["rank"] if runner else None
                )
                candidate_checks.append(
                    {
                        "date": date,
                        "race_no": race_no,
                        "program_no": candidate["program_no"],
                        "horse_id": candidate["horse_id"],
                        "candidate_horse_name": candidate["horse_name"],
                        "website_horse_name": website_name,
                        "horse_name_matches": website_name == candidate["horse_name"],
                        "website_goHorseID": linked_horse_id,
                        "exact_horse_id_match": linked_horse_id == candidate["horse_id"],
                        "point": candidate["point"],
                        "api_order": candidate["api_order"],
                        "candidate_website_order": candidate["website_order"],
                        "website_rank_from_page": selected_rank,
                        "website_order_matches_candidate": selected_rank == candidate["website_order"],
                        "six_rank_path": runner["six_rank_path"] if runner else None,
                    }
                )
            if index + 1 < len(APPROVED_KEYS):
                time.sleep(0.15)

    write_new("evidence.json", evidence)
    write_new("candidate_crosscheck.json", candidate_checks)
    write_new("section_gap_blank_summary.json", gap_summary)

    print(
        json.dumps(
            {
                "pages": len(evidence),
                "http_200": sum(item["http_status"] == 200 for item in evidence),
                "identity_verified": sum(item["identity_verified"] for item in evidence),
                "candidate_count": len(candidate_checks),
                "candidate_ids_match": sum(item["exact_horse_id_match"] for item in candidate_checks),
                "candidate_website_ranks_match": sum(item["website_order_matches_candidate"] for item in candidate_checks),
                "race_level_gap_tables_found": sum(item["race_level_section_table_found"] for item in gap_summary),
                "all_three_gap_rows_blank": sum(item["all_three_rows_blank"] for item in gap_summary),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def write_new(name: str, content) -> None:
    with (ROOT / name).open("x", encoding="utf-8") as output:
        json.dump(content, output, ensure_ascii=False, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
