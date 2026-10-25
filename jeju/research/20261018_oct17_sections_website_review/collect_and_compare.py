"""Read the seven official KRA Jeju result pages and compare runner identities.

This is an evidence collector only. It opens the local SQLite database in
read-only mode and never calls any database refresh or write path.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import http.client
import json
import re
import ssl
import sqlite3
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
DB = ROOT.parents[1] / "data" / "jeju_native_core.sqlite3"
HOST = "race.kra.co.kr"
BASE_PATH = "/raceScore/ScoretableDetailList.do"
DATE = "20261017"
LIMIT_BYTES = 4 * 1024 * 1024
TIMEOUT_SECONDS = 20
MAX_WORKERS = 2


def page_path(race_no: int) -> str:
    query = urlencode(
        {
            "Act": "04",
            "Sub": "1",
            "meet": "2",
            "realRcDate": DATE,
            "realRcNo": str(race_no),
        }
    )
    return f"{BASE_PATH}?{query}"


def fetch_page(race_no: int) -> dict:
    path = page_path(race_no)
    connection = http.client.HTTPSConnection(
        HOST, timeout=TIMEOUT_SECONDS, context=ssl.create_default_context()
    )
    try:
        connection.request(
            "GET",
            path,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; KRA result source audit)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        response = connection.getresponse()
        body = response.read(LIMIT_BYTES + 1)
        headers = {k.lower(): v for k, v in response.getheaders()}
        status = response.status
    finally:
        connection.close()

    record = {
        "race_no": race_no,
        "source_id": f"kra-scoretable-jeju-20261017-r{race_no:02d}",
        "url": f"https://{HOST}{path}",
        "retrieved_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "http_status": status,
        "content_type": headers.get("content-type"),
        "content_length_header": headers.get("content-length"),
        "response_bytes_read": len(body),
        "response_byte_limit": LIMIT_BYTES,
        "request_timeout_seconds": TIMEOUT_SECONDS,
        "redirects_followed": False,
        "tls_certificate_verification": True,
        "raw_path": None,
        "sha256": None,
        "complete_body_saved": False,
    }
    if len(body) > LIMIT_BYTES:
        record["collection_status"] = "over_4_mib_limit_not_saved"
        return {"record": record, "body": None}

    out = RAW / f"{DATE}_{race_no:02d}.html"
    with out.open("xb") as f:
        f.write(body)
    record.update(
        {
            "raw_path": out.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(body).hexdigest(),
            "complete_body_saved": True,
            "collection_status": "captured",
        }
    )
    return {"record": record, "body": body}


class TableHTMLParser(HTMLParser):
    """Small independent table/text/link parser based on Python html.parser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict] = []
        self.stack: list[dict] = []
        self.links: list[dict] = []
        self.full_text: list[str] = []
        self._link: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "table":
            self.stack.append({"rows": [], "row": None, "cell": None, "caption": None})
        elif tag == "tr" and self.stack:
            self.stack[-1]["row"] = []
        elif tag in ("td", "th") and self.stack and self.stack[-1]["row"] is not None:
            self.stack[-1]["cell"] = []
        elif tag == "caption" and self.stack:
            self.stack[-1]["caption"] = []
        elif tag == "a":
            self._link = {"href": attr.get("href"), "text": []}
        elif tag in ("br", "p", "div", "li"):
            self._append_space()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self.stack and self.stack[-1]["cell"] is not None:
            table = self.stack[-1]
            table["row"].append(self._clean("".join(table["cell"])))
            table["cell"] = None
        elif tag == "tr" and self.stack and self.stack[-1]["row"] is not None:
            table = self.stack[-1]
            if table["row"]:
                table["rows"].append(table["row"])
            table["row"] = None
        elif tag == "caption" and self.stack and self.stack[-1]["caption"] is not None:
            self.stack[-1]["caption"] = self._clean("".join(self.stack[-1]["caption"]))
        elif tag == "table" and self.stack:
            table = self.stack.pop()
            self.tables.append(table)
        elif tag == "a" and self._link is not None:
            self._link["text"] = self._clean("".join(self._link["text"]))
            self.links.append(self._link)
            self._link = None
        elif tag in ("p", "div", "li", "br"):
            self._append_space()

    def handle_data(self, data: str) -> None:
        self.full_text.append(data)
        if self.stack:
            if self.stack[-1]["cell"] is not None:
                self.stack[-1]["cell"].append(data)
            if isinstance(self.stack[-1]["caption"], list):
                self.stack[-1]["caption"].append(data)
        if self._link is not None:
            self._link["text"].append(data)

    def _append_space(self) -> None:
        if self.stack:
            if self.stack[-1]["cell"] is not None:
                self.stack[-1]["cell"].append(" ")
            if isinstance(self.stack[-1]["caption"], list):
                self.stack[-1]["caption"].append(" ")
        if self._link is not None:
            self._link["text"].append(" ")
        self.full_text.append(" ")

    @staticmethod
    def _clean(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()


def decode_body(body: bytes, content_type: str | None) -> tuple[str, str]:
    match = re.search(r"charset\s*=\s*['\"]?([^;\s'\"]+)", content_type or "", re.I)
    charset = match.group(1) if match else "euc-kr"
    return body.decode(charset, errors="replace"), charset


def parse_page(body: bytes, content_type: str | None, race_no: int) -> dict:
    html, charset = decode_body(body, content_type)
    parser = TableHTMLParser()
    parser.feed(html)
    parser.close()
    tables = parser.tables
    all_text = re.sub(r"\s+", " ", " ".join(parser.full_text)).strip()
    date_text = re.search(r"2026\s*년\s*10\s*월\s*17\s*일", all_text)
    race_text = re.search(rf"제\s*{race_no}\s*경주\s*제주", all_text)

    result_tables = []
    passing_tables = []
    section_tables = []
    for table in tables:
        rows = table["rows"]
        joined = " ".join(cell for row in rows for cell in row)
        if rows and all(x in rows[0] for x in ("순위", "마번", "마명")):
            result_tables.append(table)
        if "통과순위" in joined or "통과조" in joined:
            passing_tables.append(table)
        if "펄롱타임" in joined or "구간기록" in joined or "구간시간" in joined:
            section_tables.append(table)

    horses_by_name: dict[str, list[str]] = {}
    for link in parser.links:
        match = re.search(r"goHorse\(['\"](\d+)['\"],\s*['\"]2['\"]\)", link["href"] or "")
        if match:
            name = link["text"].removeprefix("★").strip()
            horses_by_name.setdefault(name, []).append(match[1])

    runner_rows = []
    if result_tables:
        # The official page may have more than one table beginning with the
        # same result header; keep all such tables and use the first for the
        # runner identity comparison.
        for row in result_tables[0]["rows"][1:]:
            if len(row) < 3:
                continue
            if not row[1].isdigit():
                continue
            name = row[2].removeprefix("★").strip()
            ids = horses_by_name.get(name, [])
            runner_rows.append(
                {
                    "finish_position_raw": row[0],
                    "horse_number": int(row[1]),
                    "horse_name": name,
                    "horse_ids_from_official_links": ids,
                    "source_row": row,
                }
            )

    return {
        "parser": "Python html.parser.HTMLParser, independent from the existing BeautifulSoup collector",
        "declared_or_fallback_charset": charset,
        "page_text_identity": {
            "date_text_found": bool(date_text),
            "race_and_meet_text_found": bool(race_text),
            "identity_verified": bool(date_text and race_text),
            "date_match_text": date_text.group(0) if date_text else None,
            "race_match_text": race_text.group(0) if race_text else None,
        },
        "table_count": len(tables),
        "table_summaries": [
            {
                "caption": table["caption"] if isinstance(table["caption"], str) else None,
                "row_count": len(table["rows"]),
                "header_or_first_row": table["rows"][0] if table["rows"] else [],
                "contains_passing_order_or_group": any(
                    "통과순위" in " ".join(row) or "통과조" in " ".join(row)
                    for row in table["rows"]
                ),
                "contains_race_section_times_or_record": any(
                    any(term in " ".join(row) for term in ("펄롱타임", "구간기록", "구간시간"))
                    for row in table["rows"]
                ),
            }
            for table in tables
        ],
        "all_table_rows": tables,
        "result_table_count": len(result_tables),
        "selected_result_table": result_tables[0] if result_tables else None,
        "official_horse_ids_link_map": horses_by_name,
        "official_runner_rows": runner_rows,
        "passing_tables": passing_tables,
        "race_section_tables": section_tables,
    }


def db_runner_rows() -> tuple[list[dict], int, int]:
    uri = f"file:{DB.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        rows = connection.execute(
            """
            SELECT rr.api_record_id, rr.race_date, rr.meet_code, rr.race_number,
                   rr.horse_number, rr.horse_id, rr.horse_name,
                   rr.finish_position, rr.finish_status_raw,
                   ar.payload_sha256, ar.source_artifact_id, ar.record_index
              FROM race_result_rows AS rr
              JOIN api_records AS ar USING(api_record_id)
             WHERE rr.race_date='2026-10-17' AND rr.meet_code=2
             ORDER BY rr.race_number, rr.horse_number
            """
        ).fetchall()
        section_count = connection.execute(
            "SELECT count(*) FROM refresh_section_records WHERE race_date='2026-10-17' AND meet_code=2"
        ).fetchone()[0]
        corner_count = connection.execute(
            "SELECT count(*) FROM api303_corner_rank_rows WHERE race_date='2026-10-17' AND meet_code=2"
        ).fetchone()[0]
    finally:
        connection.close()
    return [dict(row) for row in rows], section_count, corner_count


def crosscheck(page: dict, api_rows: list[dict], race_no: int) -> dict:
    api = [row for row in api_rows if row["race_number"] == race_no]
    site = page.get("official_runner_rows", [])
    api_by_no = {row["horse_number"]: row for row in api}
    checks = []
    for row in site:
        source = api_by_no.get(row["horse_number"])
        ids = row["horse_ids_from_official_links"]
        checks.append(
            {
                "horse_number": row["horse_number"],
                "horse_name_website": row["horse_name"],
                "horse_id_website": ids[0] if len(ids) == 1 else None,
                "horse_id_link_count": len(ids),
                "api4_horse_id": source["horse_id"] if source else None,
                "api4_horse_name": source["horse_name"] if source else None,
                "finish_position_website_raw": row["finish_position_raw"],
                "finish_position_api4": source["finish_position"] if source else None,
                "matched_api4_runner": source is not None,
                "horse_id_match": bool(source and len(ids) == 1 and ids[0] == source["horse_id"]),
                "horse_name_match": bool(source and row["horse_name"] == source["horse_name"]),
                "finish_position_match": bool(
                    source and row["finish_position_raw"] == str(source["finish_position"])
                ),
                "api4_source_record_id": source["api_record_id"] if source else None,
                "api4_payload_sha256": source["payload_sha256"] if source else None,
                "api4_source_artifact_id": source["source_artifact_id"] if source else None,
                "api4_record_index": source["record_index"] if source else None,
            }
        )
    api_numbers = sorted(api_by_no)
    site_numbers = sorted(row["horse_number"] for row in site)
    return {
        "race_no": race_no,
        "official_page_identity_verified": page.get("page_text_identity", {}).get("identity_verified", False),
        "api4_runner_rows": len(api),
        "website_runner_rows": len(site),
        "runner_count_equal": len(api) == len(site),
        "all_runner_numbers_equal": api_numbers == site_numbers,
        "unmatched_website_horse_numbers": sorted(set(site_numbers) - set(api_numbers)),
        "missing_website_horse_numbers": sorted(set(api_numbers) - set(site_numbers)),
        "horse_ids_match_count": sum(bool(r["horse_id_match"]) for r in checks),
        "horse_names_match_count": sum(bool(r["horse_name_match"]) for r in checks),
        "finish_positions_match_count": sum(bool(r["finish_position_match"]) for r in checks),
        "runners": checks,
    }


def main() -> None:
    if RAW.exists() and any(RAW.iterdir()):
        raise FileExistsError(f"Refusing to overwrite existing raw files in {RAW}")
    RAW.mkdir(parents=True, exist_ok=True)
    captures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_map = {pool.submit(fetch_page, n): n for n in range(1, 8)}
        for future in concurrent.futures.as_completed(future_map):
            captures.append(future.result())
    captures.sort(key=lambda item: item["record"]["race_no"])

    api_rows, section_count, corner_count = db_runner_rows()
    page_evidence = []
    race_crosschecks = []
    for item in captures:
        record = item["record"]
        body = item["body"]
        if body is not None:
            parsed = parse_page(body, record.get("content_type"), record["race_no"])
            record["parsed"] = parsed
            record["identity_verified"] = bool(
                record["http_status"] == 200
                and parsed["page_text_identity"]["identity_verified"]
            )
            record["website_runner_count"] = len(parsed["official_runner_rows"])
            check = crosscheck(parsed, api_rows, record["race_no"])
            race_crosschecks.append(check)
        else:
            record["identity_verified"] = False
            record["website_runner_count"] = None
            race_crosschecks.append(
                {
                    "race_no": record["race_no"],
                    "official_page_identity_verified": False,
                    "api4_runner_rows": sum(r["race_number"] == record["race_no"] for r in api_rows),
                    "website_runner_rows": None,
                    "runner_count_equal": False,
                    "all_runner_numbers_equal": False,
                    "runners": [],
                }
            )
        page_evidence.append(record)

    expected = {
        "date": "2026-10-17",
        "meet": "Jeju (meet=2)",
        "race_numbers": list(range(1, 8)),
        "website_endpoint": f"https://{HOST}{BASE_PATH}",
        "website_request_method": "GET",
        "website_form_parameters": {
            "Act": "04",
            "Sub": "1",
            "meet": "2",
            "realRcDate": DATE,
            "realRcNo": "1 through 7",
        },
        "bounded_collection": {
            "max_concurrent_requests": MAX_WORKERS,
            "per_request_timeout_seconds": TIMEOUT_SECONDS,
            "max_response_bytes": LIMIT_BYTES,
            "tls_verification": True,
            "redirects_followed": False,
        },
        "db_source": {
            "path": str(DB.relative_to(ROOT.parents[2])),
            "connection_mode": "SQLite URI mode=ro plus PRAGMA query_only=ON",
            "db_updates_performed": False,
            "api4_runner_rows": len(api_rows),
            "api6_race_level_rows": section_count,
            "api303_race_level_rows": corner_count,
        },
        "previous_refresh_run": {
            "run_id": "20261017T220226_4747d5bd",
            "api4_rows": 69,
            "api6_rows": 0,
            "api303_rows": 0,
            "source_manifest": "jeju/research/20261017_core_refresh/runs/20261017T220226_4747d5bd/collection/source_manifest.json",
            "source_manifest_sha256": "9dc27d3d21f4dc993cd276879f1b0b83d89927b2b2a57429efd358ea601f5f72",
        },
        "capture_summary": {
            "official_pages_captured": sum(x["complete_body_saved"] for x in page_evidence),
            "official_pages_identity_verified": sum(x.get("identity_verified", False) for x in page_evidence),
            "api4_runner_rows": len(api_rows),
            "website_runner_rows_total": sum(x.get("website_runner_count") or 0 for x in page_evidence),
            "runners_with_matching_id": sum(x["horse_ids_match_count"] for x in race_crosschecks),
            "runners_with_matching_name": sum(x["horse_names_match_count"] for x in race_crosschecks),
            "runners_with_matching_finish_position": sum(x["finish_positions_match_count"] for x in race_crosschecks),
        },
        "per_race_pages": page_evidence,
        "per_race_runner_identity_crosschecks": race_crosschecks,
    }
    destination = ROOT / "website_page_evidence.json"
    with destination.open("x", encoding="utf-8") as f:
        json.dump(expected, f, ensure_ascii=False, indent=2)
        f.write("\n")

    summary = {
        "official_pages_captured": expected["capture_summary"]["official_pages_captured"],
        "official_pages_identity_verified": expected["capture_summary"]["official_pages_identity_verified"],
        "api4_runner_rows": len(api_rows),
        "website_runner_rows": expected["capture_summary"]["website_runner_rows_total"],
        "horse_ids_matched": expected["capture_summary"]["runners_with_matching_id"],
        "horse_names_matched": expected["capture_summary"]["runners_with_matching_name"],
        "finish_positions_matched": expected["capture_summary"]["runners_with_matching_finish_position"],
        "api6_rows": section_count,
        "api303_rows": corner_count,
        "all_races": [
            {
                "race_no": x["race_no"],
                "website_identity_verified": x["official_page_identity_verified"],
                "api4_runner_rows": x["api4_runner_rows"],
                "website_runner_rows": x["website_runner_rows"],
                "runner_numbers_equal": x["all_runner_numbers_equal"],
                "horse_id_matches": x["horse_ids_match_count"],
                "horse_name_matches": x["horse_names_match_count"],
                "finish_position_matches": x["finish_positions_match_count"],
                "website_tables_with_race_section_fields": [
                    t["header_or_first_row"]
                    for t in (page_evidence[x["race_no"] - 1].get("parsed") or {}).get("table_summaries", [])
                    if t["contains_race_section_times_or_record"]
                ],
                "website_tables_with_passing_fields": [
                    t["header_or_first_row"]
                    for t in (page_evidence[x["race_no"] - 1].get("parsed") or {}).get("table_summaries", [])
                    if t["contains_passing_order_or_group"]
                ],
            }
            for x in race_crosschecks
        ],
    }
    summary_path = ROOT / "comparison_summary.json"
    with summary_path.open("x", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
