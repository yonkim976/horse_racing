#!/usr/bin/env python3
"""Offline-plan and boundedly fetch official KRA horse-training profile pages."""

from __future__ import annotations

import argparse
import csv
import hashlib
from html.parser import HTMLParser
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.error import URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

OUT = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[4]
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
JOCKEY_FILES = [ROOT / f"data/research/jockey_roster_20261008/api_{i}.json" for i in (1, 2, 3)]
TRAINER_FILES = [ROOT / f"data/raw/kra_trainer_affiliations/2026-09-29/meet_{i}.json" for i in (1, 2, 3)]
HOST = "race.kra.co.kr"
PAGE_PATH = "/racehorse/profileTrainState.do"
WINDOW_START = "2026-04-15"
WINDOW_END = "2026-09-28"
PAGE_LIMIT = 100
MAX_WORKERS = 3
TIMEOUT = 20
MAX_BYTES = 2_000_000
ID_RE = re.compile(r"^\d{1,12}$")
DATE_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
MIN_RE = re.compile(r"^(\d+)\s*분$")


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def items_from(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    values = doc.get("response", {}).get("body", {}).get("items", {}).get("item", [])
    return [values] if isinstance(values, dict) else values


def official_ids():
    ids = set()
    for path, key in [(p, "jkNo") for p in JOCKEY_FILES] + [(p, "trNo") for p in TRAINER_FILES]:
        if not path.is_file():
            raise FileNotFoundError(f"Missing archived official ID source: {path}")
        ids.update(
            str(row[key]).strip() for row in items_from(path)
            if row.get(key) not in (None, "") and row.get("meet") == "제주"
        )
    return ids


def db_connect():
    if not DB.is_file():
        raise FileNotFoundError(f"Missing source DB: {DB}")
    return sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)


def rows_for_plan():
    known = official_ids()
    conn = db_connect()
    conn.row_factory = sqlite3.Row
    try:
        source = conn.execute(
            """SELECT daily_training_api_row_id, prGubun_raw, prNo_raw, horse_id,
                      hrName_raw, training_date, start_time_local, end_time_local,
                      duration_seconds, duration_status, chulGubun_raw
                 FROM daily_training_api_rows
                WHERE training_date >= ? AND training_date <= ?
                  AND prGubun_raw = '-'
                  AND prNo_raw IS NOT NULL AND trim(prNo_raw) NOT IN ('', '-', '0')
                  AND horse_id IS NOT NULL AND trim(horse_id) != ''
                  AND start_time_local IS NOT NULL AND end_time_local IS NOT NULL
                  AND duration_seconds IS NOT NULL AND duration_seconds > 0
                ORDER BY training_date DESC, horse_id, prNo_raw, daily_training_api_row_id""",
            (WINDOW_START, WINDOW_END),
        ).fetchall()
        return [dict(row) for row in source if str(row["prNo_raw"]).strip() not in known]
    finally:
        conn.close()


def profile_url(horse_id):
    if not ID_RE.fullmatch(horse_id):
        raise ValueError(f"Invalid numeric horse ID: {horse_id!r}")
    params = urlencode({"Act": "02", "Sub": "1", "hrNo": horse_id, "meet": "2"})
    return f"https://{HOST}{PAGE_PATH}?{params}"


def plan_pages(rows):
    by_horse = {}
    id_pairs = {}
    id_rows = {}
    horse_names = {}
    for row in rows:
        emp, horse, date = str(row["prNo_raw"]).strip(), str(row["horse_id"]).strip(), str(row["training_date"])
        if not ID_RE.fullmatch(horse):
            continue
        by_horse.setdefault(horse, {}).setdefault(emp, set()).add(date)
        id_pairs.setdefault(emp, set()).add((horse, date))
        id_rows.setdefault(emp, []).append(row)
        if row.get("hrName_raw"):
            horse_names.setdefault(horse, set()).add(str(row["hrName_raw"]))

    covered = {emp: set() for emp in id_pairs}
    candidates = set(by_horse)
    selected = []
    while candidates and len(selected) < PAGE_LIMIT:
        need_first = any(not covered[emp] for emp in id_pairs)
        scored = []
        for horse in candidates:
            offers = by_horse[horse]
            new_ids = sum(bool(dates) and not covered[emp] for emp, dates in offers.items())
            new_pairs = 0
            for emp, dates in offers.items():
                if len(covered[emp]) < 2:
                    new_pairs += len({(horse, date) for date in dates} - covered[emp])
            if new_ids or new_pairs:
                scored.append(((new_ids if need_first else 0, new_pairs, -int(horse)), horse))
        if not scored:
            break
        _, horse = max(scored)
        offers = by_horse[horse]
        added_ids = 0
        added_pairs = 0
        for emp, dates in offers.items():
            new = {(horse, date) for date in dates} - covered[emp]
            if new and not covered[emp]:
                added_ids += 1
            if len(covered[emp]) < 2:
                chosen = set(sorted(new)[:2 - len(covered[emp])])
                covered[emp].update(chosen)
                added_pairs += len(chosen)
        selected.append({
            "plan_order": len(selected) + 1,
            "horse_id": horse,
            "profile_name_raw_candidate": " | ".join(sorted(horse_names.get(horse, set()))),
            "candidate_rows": sum(str(r["horse_id"]) == horse for r in rows),
            "candidate_employee_id_count": len(offers),
            "first_coverage_ids_added": added_ids,
            "independent_horse_date_pairs_added": added_pairs,
            "candidate_employee_ids": " ".join(sorted(offers)),
            "url": profile_url(horse),
        })
        candidates.remove(horse)

    # Retain the three parent-requested spot checks in the final raw-source set.
    for horse in ("3104703", "3104301", "3104105"):
        if horse not in by_horse or any(row["horse_id"] == horse for row in selected) or len(selected) >= PAGE_LIMIT:
            continue
        offers = by_horse[horse]
        added_ids = 0
        added_pairs = 0
        for emp, dates in offers.items():
            new = {(horse, date) for date in dates} - covered[emp]
            if new and not covered[emp]:
                added_ids += 1
            if len(covered[emp]) < 2:
                chosen = set(sorted(new)[:2 - len(covered[emp])])
                covered[emp].update(chosen)
                added_pairs += len(chosen)
        selected.append({
            "plan_order": len(selected) + 1,
            "horse_id": horse,
            "profile_name_raw_candidate": " | ".join(sorted(horse_names.get(horse, set()))),
            "candidate_rows": sum(str(r["horse_id"]) == horse for r in rows),
            "candidate_employee_id_count": len(offers),
            "first_coverage_ids_added": added_ids,
            "independent_horse_date_pairs_added": added_pairs,
            "candidate_employee_ids": " ".join(sorted(offers)),
            "url": profile_url(horse),
        })

    scope = []
    for emp in sorted(id_pairs):
        pairs = sorted(id_pairs[emp])
        selected_pairs = sorted(covered[emp])
        scope.append({
            "employee_number": emp,
            "category_raw": "-",
            "candidate_api18_rows": len(id_rows[emp]),
            "candidate_horses": len({h for h, _ in pairs}),
            "candidate_horse_date_pairs": len(pairs),
            "selected_horse_date_pairs": len(selected_pairs),
            "first_training_date": min(d for _, d in pairs),
            "last_training_date": max(d for _, d in pairs),
            "selected_horse_date_keys": " ".join(f"{h}:{d}" for h, d in selected_pairs),
            "coverage_status": "two_or_more_pairs" if len(selected_pairs) >= 2 else "one_pair_only" if selected_pairs else "not_selected_within_cap",
        })

    old_roles = []
    conn = db_connect()
    conn.row_factory = sqlite3.Row
    try:
        for category in ("조교보", "조교승인"):
            totals = conn.execute(
                """SELECT count(*) AS rows, count(distinct prNo_raw) AS ids,
                          min(training_date) AS first_date, max(training_date) AS last_date
                     FROM daily_training_api_rows
                    WHERE prGubun_raw=? AND prNo_raw IS NOT NULL AND trim(prNo_raw) NOT IN ('','-','0')""",
                (category,),
            ).fetchone()
            recent = conn.execute(
                """SELECT count(*) AS rows, count(distinct prNo_raw) AS ids,
                          min(training_date) AS first_date, max(training_date) AS last_date
                     FROM daily_training_api_rows
                    WHERE prGubun_raw=? AND training_date>=? AND training_date<=?
                      AND prNo_raw IS NOT NULL AND trim(prNo_raw) NOT IN ('','-','0')""",
                (category, WINDOW_START, WINDOW_END),
            ).fetchone()
            old_roles.append({
                "category_raw": category, "all_rows": totals["rows"], "all_ids": totals["ids"],
                "first_date": totals["first_date"], "last_date": totals["last_date"],
                "rows_in_window": recent["rows"], "ids_in_window": recent["ids"],
                "decision": "outside_six_month_page_window" if not recent["rows"] else "in_window",
            })
    finally:
        conn.close()
    summary = {
        "generated_at_utc": now_utc(),
        "window_start_inclusive": WINDOW_START, "window_end_inclusive": WINDOW_END,
        "source_db": str(DB), "id_scope_rule": "prGubun_raw='-' and prNo_raw not exactly in archived API307/API308 IDs",
        "candidate_api18_rows": len(rows), "unlinked_employee_id_count": len(id_pairs),
        "candidate_horse_count": len(by_horse), "selected_page_count": len(selected),
        "page_limit": PAGE_LIMIT, "max_parallel_requests": MAX_WORKERS, "timeout_seconds": TIMEOUT,
        "ids_with_two_planned_pairs": sum(r["selected_horse_date_pairs"] >= 2 for r in scope),
        "ids_with_one_or_more_planned_pairs": sum(r["selected_horse_date_pairs"] >= 1 for r in scope),
        "explicit_old_role_scope": old_roles,
        "decision_rule": "Plan is only a candidate. Identity evidence requires exact horse/date/start/end/duration match against page HTML.",
    }
    return selected, summary, scope


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class SameHostRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlparse(newurl)
        if target.scheme != "https" or target.hostname != HOST or target.path != PAGE_PATH:
            raise URLError("Redirect outside fixed official KRA host/path blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_page(item):
    url = item["url"]
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != HOST or parsed.path != PAGE_PATH:
        raise ValueError("URL failed fixed official-host/path allowlist")
    if parse_qs(parsed.query) != {"Act": ["02"], "Sub": ["1"], "hrNo": [item["horse_id"]], "meet": ["2"]}:
        raise ValueError("URL failed fixed KRA query allowlist")
    opener = build_opener(SameHostRedirect())
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; KRA-source-review/1.0)",
        "Accept": "text/html",
    })
    started = time.monotonic()
    with opener.open(request, timeout=TIMEOUT) as response:
        body = response.read(MAX_BYTES + 1)
        status = response.status
        final_url = response.geturl()
        content_type = response.headers.get("Content-Type", "")
    if len(body) > MAX_BYTES:
        raise ValueError(f"HTML response exceeded {MAX_BYTES} bytes")
    final = urlparse(final_url)
    if final.scheme != "https" or final.hostname != HOST or final.path != PAGE_PATH:
        raise ValueError("Final URL failed fixed official-host/path allowlist")
    if "text/html" not in content_type.lower():
        raise ValueError(f"Unexpected content type: {content_type}")
    return {
        "horse_id": item["horse_id"], "url": url, "final_url": final_url,
        "http_status": status, "content_type": content_type, "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(), "body": body,
        "fetch_seconds": round(time.monotonic() - started, 3),
    }


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table_idx = None
        self.row = None
        self.cell = None
        self.inputs = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag.lower() == "input" and attrs.get("name"):
            self.inputs[attrs["name"]] = attrs.get("value", "")
        if tag.lower() == "table":
            self.tables.append([])
            self.table_idx = len(self.tables) - 1
        elif tag.lower() == "tr" and self.table_idx is not None:
            self.row = []
        elif tag.lower() in ("td", "th") and self.row is not None:
            self.cell = []
        elif tag.lower() == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self.row is not None and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.table_idx is not None and self.row is not None:
            self.tables[self.table_idx].append(self.row)
            self.row = None
        elif tag == "table":
            self.table_idx = None


def decode_html(body, content_type):
    match = re.search(r"charset\s*=\s*['\"]?([A-Za-z0-9._-]+)", content_type, re.I)
    encodings = ([match.group(1)] if match else []) + ["utf-8", "cp949", "euc-kr"]
    for encoding in encodings:
        try:
            return body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            pass
    raise ValueError("Could not decode official HTML")


def parse_page(body, content_type, expected_id):
    parser = TableParser()
    parser.feed(decode_html(body, content_type))
    profile_name = None
    for table in parser.tables:
        for row in table:
            if "마명" in row and row.index("마명") + 1 < len(row):
                profile_name = row[row.index("마명") + 1]
                break
        if profile_name:
            break
    needed = {"조교일자", "기승자", "입장시간", "퇴장시간", "조교시간"}
    training = []
    for table in parser.tables:
        heading = next((i for i, row in enumerate(table) if needed.issubset(set(row))), None)
        if heading is None:
            continue
        head = table[heading]
        pos = {name: head.index(name) for name in needed}
        for row in table[heading + 1:]:
            if max(pos.values()) >= len(row):
                continue
            date_match = DATE_RE.match(row[pos["조교일자"]])
            minutes = MIN_RE.fullmatch(row[pos["조교시간"]])
            start, end = row[pos["입장시간"]], row[pos["퇴장시간"]]
            if not date_match or not minutes or not TIME_RE.fullmatch(start) or not TIME_RE.fullmatch(end):
                continue
            training.append({
                "date": f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}",
                "website_name_raw": row[pos["기승자"]], "start": start, "end": end,
                "duration_minutes": int(minutes.group(1)),
            })
    page_id = parser.inputs.get("hrNo") or parser.inputs.get("hrno")
    return {
        "profile_id": page_id, "profile_name_raw": profile_name,
        "profile_id_matches_url": page_id == expected_id,
        "training_table_found": bool(training or any(needed.issubset(set(r)) for t in parser.tables for r in t)),
        "training_rows": training,
    }


def clock_minutes(text):
    value = (text or "").strip().split()
    match = TIME_RE.fullmatch(value[-1][:5] if value else "")
    return None if not match else int(match.group(1)) * 60 + int(match.group(2))


def person_fields(raw):
    value = " ".join((raw or "").split())
    if value == "외":
        return None, None
    if not value or value in {"-", "조", "관", "생", "외", "경주일"}:
        return None, value or None
    for suffix in ("(관)", "(조)", "(생)", "(트)"):
        if value.endswith(suffix):
            return value[:-len(suffix)].strip() or None, suffix[1:-1]
    return value, "기수"


def build_evidence(plan, page_records, id_scope):
    selected = {item["horse_id"] for item in plan}
    pages = {item["horse_id"]: item for item in page_records if item.get("fetch_status") == "ok"}
    conn = db_connect()
    conn.row_factory = sqlite3.Row
    try:
        source_rows = conn.execute(
            """SELECT daily_training_api_row_id, prGubun_raw, prNo_raw, horse_id,
                      training_date, start_time_local, end_time_local, duration_seconds
                 FROM daily_training_api_rows
                WHERE training_date>=? AND training_date<=? AND prGubun_raw='-'
                  AND prNo_raw IS NOT NULL AND trim(prNo_raw) NOT IN ('','-','0')
                  AND horse_id IS NOT NULL AND start_time_local IS NOT NULL AND end_time_local IS NOT NULL
                  AND duration_seconds IS NOT NULL AND duration_seconds>0""",
            (WINDOW_START, WINDOW_END),
        ).fetchall()
    finally:
        conn.close()

    by_key = {}
    for source in source_rows:
        horse = str(source["horse_id"])
        if horse not in selected:
            continue
        start, end = clock_minutes(source["start_time_local"]), clock_minutes(source["end_time_local"])
        if start is None or end is None:
            continue
        key = (horse, str(source["training_date"]), start, end, int(source["duration_seconds"]))
        by_key.setdefault(key, []).append(dict(source))

    evidence, unresolved, ambiguous, page_manifest = [], [], [], []
    names_by_id, roles_by_id = {}, {}
    for horse, page in sorted(pages.items()):
        body = (ROOT / page["source_path"]).read_bytes()
        parsed = parse_page(body, page["content_type"], horse)
        page["parse_status"] = "ok" if parsed["profile_id_matches_url"] and parsed["profile_name_raw"] and parsed["training_table_found"] else "profile_or_table_unverified"
        page["parsed_profile_id"] = parsed["profile_id"]
        page["profile_name_raw"] = parsed["profile_name_raw"]
        manifest_row = {key: page[key] for key in (
            "horse_id", "url", "final_url", "http_status", "content_type", "bytes", "sha256", "source_path", "retrieved_at_utc",
            "parsed_profile_id", "profile_name_raw", "parse_status",
        )}
        manifest_row["path"] = page["source_path"]
        page_manifest.append(manifest_row)
        if page["parse_status"] != "ok":
            continue
        for webrow in parsed["training_rows"]:
            start, end = clock_minutes(webrow["start"]), clock_minutes(webrow["end"])
            minutes = webrow["duration_minutes"]
            if start is None or end is None or end - start != minutes:
                continue
            key = (horse, webrow["date"], start, end, minutes * 60)
            matches = by_key.get(key, [])
            employee_ids = {str(row["prNo_raw"]).strip() for row in matches}
            if not matches:
                continue
            if len(employee_ids) != 1:
                ambiguous.append({
                    "horse_id": horse, "date": webrow["date"], "start": webrow["start"], "end": webrow["end"],
                    "website_name_raw": webrow["website_name_raw"],
                    "employee_numbers": sorted(employee_ids),
                    "training_row_ids": [int(row["daily_training_api_row_id"]) for row in matches],
                    "reason": "multiple employee IDs share an exact horse/date/time/duration key",
                })
                continue
            employee = next(iter(employee_ids))
            person, role = person_fields(webrow["website_name_raw"])
            for row in matches:
                observation = {
                    "training_row_id": int(row["daily_training_api_row_id"]),
                    "employee_number": employee, "category_raw": row["prGubun_raw"],
                    "website_name_raw": webrow["website_name_raw"], "person_name": person,
                    "website_role_code": role, "horse_id": horse, "date": webrow["date"],
                    "start_time_local": str(row["start_time_local"]),
                    "end_time_local": str(row["end_time_local"]),
                    "website_start_time_local": webrow["start"],
                    "website_end_time_local": webrow["end"],
                    "website_training_duration_minutes": minutes,
                    "api18_duration_seconds": int(row["duration_seconds"]),
                    "source_path": page["source_path"], "source_sha256": page["sha256"],
                    "url": page["url"], "page_profile_name_raw": parsed["profile_name_raw"],
                    "page_profile_id": parsed["profile_id"],
                    "match_method": "exact_horse_date_start_end_duration",
                }
                evidence.append(observation)
                if person:
                    names_by_id.setdefault(employee, set()).add(person)
                    roles_by_id.setdefault(employee, set()).add(role)
                else:
                    observation["unresolved_reason"] = (
                        "official page cell has no person name; raw marker preserved without interpretation"
                    )
                    unresolved.append(observation)

    conflicts = {emp for emp in names_by_id.keys() | roles_by_id.keys()
                 if len(names_by_id.get(emp, set())) > 1 or len(roles_by_id.get(emp, set())) > 1}
    named_pairs_by_id = {}
    for row in evidence:
        named_pairs_by_id.setdefault(row["employee_number"], set()).add((row["person_name"], row["horse_id"], row["date"]))
    for row in evidence:
        emp = row["employee_number"]
        names = sorted(names_by_id.get(emp, set()))
        roles = sorted(roles_by_id.get(emp, set()))
        row["candidate_names_for_employee"] = names
        row["candidate_website_role_codes"] = roles
        if emp in conflicts:
            row["ambiguity_status"] = "ambiguous_do_not_auto_select"
            row["ambiguity_reason"] = "same ID has different names or role codes across exact matched observations"
        else:
            independent_pairs = {
                (horse, date) for name, horse, date in named_pairs_by_id[emp] if name == row["person_name"]
            }
            row["independent_named_horse_date_match_count"] = len(independent_pairs)
            row["ambiguity_status"] = "two_or_more_independent_matches" if len(independent_pairs) >= 2 else "single_independent_match"

    unresolved_by_id = {}
    for row in unresolved:
        unresolved_by_id.setdefault(row["employee_number"], []).append(row)
    named_by_id = {}
    for row in evidence:
        if row["person_name"]:
            named_by_id.setdefault(row["employee_number"], []).append(row)
    unresolved_ids = []
    for scope_row in id_scope:
        employee = scope_row["employee_number"]
        named_rows = named_by_id.get(employee, [])
        unresolved_rows = unresolved_by_id.get(employee, [])
        names = sorted({row["person_name"] for row in named_rows})
        if employee in conflicts:
            status = "conflicting_names_or_roles_do_not_auto_select"
        elif len(names) == 1 and len({(r["horse_id"], r["date"]) for r in named_rows}) >= 2:
            status = "name_supported_by_two_or_more_independent_matches"
        elif len(names) == 1:
            status = "one_exact_named_match_only"
        elif unresolved_rows:
            status = "exact_event_matches_but_page_has_no_person_name"
        else:
            status = "no_exact_page_match"
        unresolved_ids.append({
            "employee_number": employee, "category_raw": scope_row["category_raw"],
            "candidate_api18_rows": scope_row["candidate_api18_rows"],
            "planned_horse_date_pairs": scope_row["selected_horse_date_pairs"],
            "exact_named_matches": len(named_rows),
            "distinct_named_horse_date_pairs": len({(r["horse_id"], r["date"]) for r in named_rows}),
            "exact_role_token_matches": len(unresolved_rows),
            "candidate_names": names,
            "status": status,
        })

    observed = {
        "observed_at": now_utc(),
        "source_policy": "Official KRA per-horse training profile; exact horse/date/start/end/duration match to API18 required. API18 category is preserved as-is.",
        "window_start_inclusive": WINDOW_START, "window_end_inclusive": WINDOW_END,
        "pages": page_manifest, "evidence": evidence, "unresolved_observations": unresolved,
        "unresolved_employee_ids": unresolved_ids, "ambiguous_exact_event_keys": ambiguous,
        "identity_conflict_employee_ids": sorted(conflicts),
        "summary": {
            "successful_pages": len(page_manifest), "evidence_rows": len(evidence),
            "employees_with_person_name": len({row["employee_number"] for row in evidence if row["person_name"]}),
            "employees_with_two_or_more_named_matches": sum(row["status"] == "name_supported_by_two_or_more_independent_matches" for row in unresolved_ids),
            "employees_with_one_named_match": sum(row["status"] == "one_exact_named_match_only" for row in unresolved_ids),
            "employees_unresolved": sum(row["status"] in ("exact_event_matches_but_page_has_no_person_name", "no_exact_page_match") for row in unresolved_ids),
            "employee_ids_with_conflicting_names_or_roles": len(conflicts),
            "ambiguous_exact_event_keys": len(ambiguous),
        },
    }
    return observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Fetch the plan's official KRA pages (maximum 100)")
    parser.add_argument("--parse-only", action="store_true", help="Reparse saved raw HTML and manifest without network requests")
    args = parser.parse_args()
    if args.fetch and args.parse_only:
        parser.error("--fetch and --parse-only cannot be combined")
    OUT.mkdir(parents=True, exist_ok=True)
    rows = rows_for_plan()
    plan, summary, scope = plan_pages(rows)
    write_csv(OUT / "profile_collection_plan.csv", plan)
    write_csv(OUT / "unlinked_recent_id_scope.csv", scope)
    (OUT / "collection_plan.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.fetch and not args.parse_only:
        print("Plan-only mode; no network requests were made.")
        return 0

    manifest_path = OUT / "http_collection_manifest.json"
    if args.parse_only:
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Cannot parse without saved HTTP manifest: {manifest_path}")
        fetched = json.loads(manifest_path.read_text(encoding="utf-8"))["pages"]
    else:
        raw_dir = OUT / "raw_html"
        raw_dir.mkdir(parents=True, exist_ok=True)
        fetched = []
        old_pages = {}
        if manifest_path.is_file():
            old_doc = json.loads(manifest_path.read_text(encoding="utf-8"))
            old_pages = {row.get("horse_id"): row for row in old_doc.get("pages", [])}
        pending = []
        for item in plan:
            old = old_pages.get(item["horse_id"])
            old_path = ROOT / old.get("source_path", "") if old else None
            if (old and old.get("url") == item["url"] and old.get("fetch_status") == "ok"
                    and old_path and old_path.is_file()
                    and hashlib.sha256(old_path.read_bytes()).hexdigest() == old.get("sha256")):
                fetched.append(old)
            else:
                pending.append(item)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(fetch_page, item): item for item in pending}
            for future in as_completed(futures):
                item = futures[future]
                finished_at = now_utc()
                try:
                    row = future.result()
                    path = raw_dir / f"kra_profileTrainState_hrNo_{row['horse_id']}.html"
                    path.write_bytes(row.pop("body"))
                    row.update({
                        "fetch_status": "ok", "retrieved_at_utc": finished_at,
                        "source_path": str(path.relative_to(ROOT)),
                    })
                except Exception as exc:
                    row = {
                        "horse_id": item["horse_id"], "url": item["url"],
                        "fetch_status": "error", "retrieved_at_utc": finished_at,
                        "error_type": type(exc).__name__, "error": str(exc),
                    }
                fetched.append(row)
                print(json.dumps({key: value for key, value in row.items() if key != "body"}, ensure_ascii=False))
        fetched.sort(key=lambda row: row["horse_id"])
        manifest_path.write_text(json.dumps({
            "generated_at_utc": now_utc(),
            "host_allowlist": [HOST], "path_allowlist": [PAGE_PATH],
            "timeout_seconds": TIMEOUT, "response_byte_limit_per_page": MAX_BYTES,
            "max_parallel_requests": MAX_WORKERS, "requested_pages": len(plan),
            "success_count": sum(row.get("fetch_status") == "ok" for row in fetched),
            "failure_count": sum(row.get("fetch_status") != "ok" for row in fetched),
            "pages": fetched,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    evidence = build_evidence(plan, fetched, scope)
    (OUT / "staff_website_identity_evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)

