#!/usr/bin/env python3
"""Read-only review of recent unclassified API18 rows against official KRA pages."""

from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
RAW = OUT / "raw_html"
DB = ROOT / "jeju/data/jeju_native_core.sqlite3"
SOURCE_REVIEW = ROOT / "jeju/research/20261015_training_rider_identity/source_review"
OLD_MANIFEST = SOURCE_REVIEW / "http_collection_manifest.json"
COLLECTOR_PATH = SOURCE_REVIEW / "collect_kra_training_html.py"
START_DATE = "2026-04-15"
END_DATE = "2026-09-28"
PAGE_COUNT = 8
ID_RE = re.compile(r"^\d{1,12}$")


def load_collector():
    spec = importlib.util.spec_from_file_location("kra_training_collector", COLLECTOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the existing guarded KRA collector")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_new_json(path: Path, document):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


class SourceUIParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms = []
        self.form = None
        self.inputs = []
        self.selects = []
        self.select = None
        self.links = []
        self.scripts = []
        self.in_script = False
        self.script = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        tag = tag.lower()
        if tag == "form":
            self.form = {"attrs": attrs, "fields": []}
            self.forms.append(self.form)
        elif tag == "input":
            item = {"type": attrs.get("type", "text"), "name": attrs.get("name"), "value": attrs.get("value")}
            self.inputs.append(item)
            if self.form is not None:
                self.form["fields"].append(item)
        elif tag == "select":
            self.select = {"name": attrs.get("name"), "options": []}
            self.selects.append(self.select)
        elif tag == "option" and self.select is not None:
            self.select["options"].append(attrs.get("value"))
        elif tag == "a":
            self.links.append({"href": attrs.get("href"), "onclick": attrs.get("onclick"), "title": attrs.get("title")})
        elif tag == "script":
            self.in_script = True
            self.script = []

    def handle_data(self, data):
        if self.in_script:
            self.script.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "form":
            self.form = None
        elif tag == "select":
            self.select = None
        elif tag == "script" and self.in_script:
            self.scripts.append("".join(self.script))
            self.in_script = False


def inspect_existing_pages():
    source_manifest = json.loads(OLD_MANIFEST.read_text(encoding="utf-8"))
    pages = []
    for row in source_manifest.get("pages", []):
        if row.get("fetch_status") != "ok":
            continue
        path = ROOT / row["source_path"]
        body = path.read_bytes()
        actual_sha = hashlib.sha256(body).hexdigest()
        if actual_sha != row.get("sha256"):
            raise ValueError(f"Archived source SHA mismatch: {row['source_path']}")
        text = body.decode("euc-kr", errors="replace")
        parser = SourceUIParser()
        parser.feed(text)
        profile_links = [link for link in parser.links if "goPageTab" in (link.get("onclick") or "")]
        profile_links = [link for link in profile_links if "profileTrainState.do" in (link.get("onclick") or "")]
        related_functions = []
        for function_name in ("goScore", "goPageTab"):
            match = re.search(rf"function\s+{function_name}\s*\([^)]*\)\s*\{{[^}}]*\}}", text, re.S)
            if match:
                related_functions.append(" ".join(match.group(0).split()))
        action_summaries = []
        for form in parser.forms:
            attrs = form["attrs"]
            action = attrs.get("action", "").replace("&amp;", "&")
            parsed = urlparse(action)
            action_summaries.append({
                "name": attrs.get("name"), "method": (attrs.get("method") or "get").lower(),
                "path": parsed.path, "query_keys": sorted(parse_qs(parsed.query).keys()),
                "field_names": [item["name"] for item in form["fields"] if item["name"]],
                "field_types": [item["type"] for item in form["fields"]],
            })
        pages.append({
            "horse_id": str(row["horse_id"]),
            "url": row["url"],
            "http_status": row["http_status"],
            "source_path": row["source_path"],
            "sha256": actual_sha,
            "notice_text": "최근 6개월간 조교자료입니다.",
            "notice_occurrences": text.count("최근 6개월간 조교자료입니다."),
            "forms": action_summaries,
            "input_types": sorted(Counter(item["type"] for item in parser.inputs).items()),
            "select_count": len(parser.selects),
            "date_input_count": sum(item["type"].lower() == "date" for item in parser.inputs),
            "date_select_count": sum(bool(re.search(r"date|날짜|년|월", str(item.get("name", "")), re.I)) for item in parser.selects),
            "profile_tab_links": profile_links,
            "relevant_functions": related_functions,
        })
    return {
        "source_manifest": str(OLD_MANIFEST.relative_to(ROOT)),
        "manifest_success_count": source_manifest.get("success_count"),
        "verified_page_count": len(pages),
        "notice_on_all_pages": bool(pages) and all(item["notice_occurrences"] > 0 for item in pages),
        "date_input_page_count": sum(item["date_input_count"] > 0 for item in pages),
        "date_select_page_count": sum(item["date_select_count"] > 0 for item in pages),
        "forms_have_only_hidden_inputs": all(
            all(set(form["field_types"]) <= {"hidden"} for form in item["forms"])
            for item in pages
        ),
        "page_records": pages,
        "interpretation": (
            "Across the 32 saved pages, the page itself states it shows six months of training data. "
            "The form exposes only hidden fields (Act, Sub, meet, hrNo, realRcDate, realRcNo); there are no date inputs or selects. "
            "realRcDate/realRcNo are populated by goScore for the race-result page, while goPageTab only switches profile tabs. "
            "No date-range control or dated pagination is exposed on this training page."
        ),
    }


def read_candidates(old_ids):
    if not DB.is_file():
        raise FileNotFoundError(f"Missing source DB: {DB}")
    conn = sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    try:
        rows = conn.execute(
            """SELECT d.daily_training_api_row_id AS row_id, d.horse_id,
                      d.training_date, d.start_time_local, d.end_time_local,
                      d.duration_seconds, d.prNo_raw
                 FROM daily_training_api_rows AS d
                 JOIN daily_training_rider_type_values AS v USING (daily_training_api_row_id)
                WHERE d.training_date BETWEEN ? AND ?
                  AND v.rider_type = ?
                  AND d.prGubun_raw = ?
                  AND d.prNo_raw IS NOT NULL AND trim(d.prNo_raw) NOT IN ('', '-', '0')
                  AND d.horse_id IS NOT NULL AND trim(d.horse_id) != ''
                  AND d.start_time_local IS NOT NULL AND d.end_time_local IS NOT NULL
                  AND d.duration_seconds IS NOT NULL AND d.duration_seconds > 0
                ORDER BY d.training_date DESC, d.horse_id, d.daily_training_api_row_id""",
            (START_DATE, END_DATE, "미분류", "-"),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def choose_pages(rows, old_ids):
    by_horse = defaultdict(list)
    for row in rows:
        horse = str(row["horse_id"]).strip()
        if horse in old_ids or not ID_RE.fullmatch(horse):
            continue
        by_horse[horse].append(row)
    selected = sorted(by_horse, key=lambda horse: (-len(by_horse[horse]), horse))[:PAGE_COUNT]
    return [
        {
            "horse_id": horse,
            "candidate_api18_rows": len(by_horse[horse]),
            "first_candidate_date": min(row["training_date"] for row in by_horse[horse]),
            "last_candidate_date": max(row["training_date"] for row in by_horse[horse]),
            "url": load_collector().profile_url(horse),
        }
        for horse in selected
    ]


def collect_pages(plan):
    RAW.mkdir(exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(load_collector().fetch_page, {"horse_id": item["horse_id"], "url": item["url"]}): item
            for item in plan
        }
        for future in as_completed(futures):
            item = futures[future]
            retrieved = now_utc()
            try:
                fetched = future.result()
                expected_name = f"kra_profileTrainState_hrNo_{item['horse_id']}.html"
                raw_path = RAW / expected_name
                with raw_path.open("xb") as handle:
                    handle.write(fetched.pop("body"))
                fetched["fetch_status"] = "ok"
                fetched["retrieved_at_utc"] = retrieved
                fetched["source_path"] = str(raw_path.relative_to(ROOT))
                results.append(fetched)
            except Exception as exc:
                results.append({
                    "horse_id": item["horse_id"], "url": item["url"],
                    "fetch_status": "error", "retrieved_at_utc": retrieved,
                    "error_type": type(exc).__name__, "error": str(exc),
                })
    return sorted(results, key=lambda item: item["horse_id"])


def explicit_type(raw):
    value = " ".join((raw or "").split())
    if value == "외":
        return "external_marker", None
    if value in ("", "-"):
        return "blank", None
    token_types = {
        "조": "조교사", "관": "주로조교", "생": "교육생", "트": "기수 트랙라이더",
    }
    if value in {"조", "(조)"}:
        return "explicit_role_marker", "조교사"
    if value in {"관", "(관)"}:
        return "explicit_role_marker", "주로조교"
    if value in {"생", "(생)"}:
        return "explicit_role_marker", "교육생"
    for suffix, role in (("(조)", "조교사"), ("(관)", "주로조교"), ("(생)", "교육생"), ("(트)", "기수 트랙라이더")):
        if value.endswith(suffix) and value[:-len(suffix)].strip():
            return "explicit_role_marker", role
    if value in token_types:
        return "explicit_role_marker", token_types[value]
    return "name_without_explicit_type_marker", None


def match_events(rows, page_results, collector):
    selected_ids = {str(item["horse_id"]) for item in page_results}
    candidate_rows = [row for row in rows if str(row["horse_id"]) in selected_ids]
    page_parse = {}
    website_by_key = defaultdict(list)
    website_rows_by_horse_date = defaultdict(list)
    for page in page_results:
        if page.get("fetch_status") != "ok":
            page_parse[page["horse_id"]] = {"parse_status": "fetch_failed"}
            continue
        raw_path = ROOT / page["source_path"]
        body = raw_path.read_bytes()
        actual_sha = hashlib.sha256(body).hexdigest()
        if actual_sha != page.get("sha256"):
            raise ValueError(f"New source SHA mismatch: {page['source_path']}")
        parsed = collector.parse_page(body, page.get("content_type", ""), str(page["horse_id"]))
        ok = parsed["profile_id_matches_url"] and bool(parsed["profile_name_raw"]) and parsed["training_table_found"]
        page_parse[page["horse_id"]] = {
            "parse_status": "ok" if ok else "profile_or_table_unverified",
            "profile_id": parsed["profile_id"],
            "profile_id_matches_url": parsed["profile_id_matches_url"],
            "profile_name_raw": parsed["profile_name_raw"],
            "training_table_found": parsed["training_table_found"],
            "website_training_row_count": len(parsed["training_rows"]),
            "website_date_min": min((row["date"] for row in parsed["training_rows"]), default=None),
            "website_date_max": max((row["date"] for row in parsed["training_rows"]), default=None),
            "source_path": page["source_path"], "source_sha256": actual_sha,
        }
        if not ok:
            continue
        for webrow in parsed["training_rows"]:
            website_rows_by_horse_date[(str(page["horse_id"]), webrow["date"])].append(webrow)
            start = collector.clock_minutes(webrow["start"])
            end = collector.clock_minutes(webrow["end"])
            minutes = int(webrow["duration_minutes"])
            if start is None or end is None or end - start != minutes:
                continue
            key = (str(page["horse_id"]), webrow["date"], start, end, minutes * 60)
            website_by_key[key].append({
                **webrow, "page_horse_id": str(page["horse_id"]),
                "source_path": page["source_path"], "source_sha256": actual_sha, "url": page["url"],
            })

    verified_page_ids = {
        horse for horse, status in page_parse.items() if status.get("parse_status") == "ok"
    }
    unavailable_page_ids = selected_ids - verified_page_ids
    api_by_key = defaultdict(list)
    comparison_unavailable = []
    for row in candidate_rows:
        horse = str(row["horse_id"])
        if horse not in verified_page_ids:
            comparison_unavailable.append({
                **row,
                "comparison_status": page_parse.get(horse, {}).get("parse_status", "page_fetch_failed"),
                "reason": "official_page_not_successfully_fetched_and_verified",
            })
            continue
        start = collector.clock_minutes(row["start_time_local"])
        end = collector.clock_minutes(row["end_time_local"])
        if start is None or end is None:
            comparison_unavailable.append({
                **row, "comparison_status": "api_time_unusable",
                "reason": "API event time could not be normalized for exact match",
            })
            continue
        key = (horse, str(row["training_date"]), start, end, int(row["duration_seconds"]))
        api_by_key[key].append(row)

    evidence, unmatched, ambiguous = [], [], []
    category_counts = Counter()
    direct_type_counts = Counter()
    for key, api_matches in api_by_key.items():
        web_matches = website_by_key.get(key, [])
        if not web_matches:
            for row in api_matches:
                same_date_rows = website_rows_by_horse_date.get((key[0], key[1]), [])
                page_oldest_date = page_parse.get(key[0], {}).get("website_date_min")
                if same_date_rows:
                    reason = "same_horse_date_page_rows_but_no_exact_entry_exit_duration_match"
                elif page_oldest_date and key[1] < page_oldest_date:
                    reason = "candidate_date_precedes_oldest_training_row_visible_on_page"
                else:
                    reason = "no_same_horse_date_row_visible_on_page_reason_unresolved"
                unmatched.append({
                    **row,
                    "unmatched_reason": reason,
                    "website_page_oldest_training_date": page_oldest_date,
                    "same_date_website_row_count": len(same_date_rows),
                    "same_date_website_rows": [
                        {"website_name_raw": item["website_name_raw"], "start": item["start"],
                         "end": item["end"], "duration_minutes": item["duration_minutes"]}
                        for item in same_date_rows
                    ],
                })
            continue
        employee_ids = {str(row["prNo_raw"]).strip() for row in api_matches}
        raw_labels = {" ".join((row.get("website_name_raw") or "").split()) for row in web_matches}
        if len(employee_ids) != 1 or len(raw_labels) != 1:
            ambiguous.append({
                "horse_id": key[0], "date": key[1],
                "start_time_minutes": key[2], "end_time_minutes": key[3],
                "duration_seconds": key[4],
                "api_row_ids": [int(row["row_id"]) for row in api_matches],
                "employee_number_count_for_ambiguity_check": len(employee_ids),
                "website_labels_raw": sorted(raw_labels),
                "website_row_count": len(web_matches),
                "reason": "multiple API employee IDs or conflicting exact-event website labels",
            })
            for row in api_matches:
                evidence.append({
                    **row, "website_name_raw": sorted(raw_labels),
                    "evidence_status": "ambiguous_exact_event_no_type_assigned",
                    "website_type_candidate": None,
                })
            continue
        webrow = web_matches[0]
        category, role = explicit_type(webrow["website_name_raw"])
        category_counts[category] += len(api_matches)
        if role:
            direct_type_counts[role] += len(api_matches)
        for row in api_matches:
            evidence.append({
                **row,
                "website_name_raw": webrow["website_name_raw"],
                "website_start_time": webrow["start"], "website_end_time": webrow["end"],
                "website_duration_minutes": int(webrow["duration_minutes"]),
                "website_type_evidence": category,
                "website_type_candidate": role,
                "evidence_status": "exact_event_direct_type_marker" if role else f"exact_event_{category}",
                "website_page_url": webrow["url"],
                "source_path": webrow["source_path"], "source_sha256": webrow["source_sha256"],
                "match_method": "exact_horse_id_date_entry_exit_duration",
            })
    return {
        "candidate_rows_for_selected_pages": len(candidate_rows),
        "candidate_rows_by_page": dict(Counter(str(row["horse_id"]) for row in candidate_rows)),
        "exact_event_linked_api_rows": len(evidence),
        "explicit_type_candidate_api_rows": sum(direct_type_counts.values()),
        "explicit_type_candidate_counts": dict(sorted(direct_type_counts.items())),
        "exact_event_raw_label_counts": dict(sorted(category_counts.items())),
        "unmatched_api_rows": len(unmatched),
        "unmatched_reason_counts": dict(sorted(Counter(row["unmatched_reason"] for row in unmatched).items())),
        "comparison_unavailable_api_rows": len(comparison_unavailable),
        "comparison_unavailable_pages": len(unavailable_page_ids),
        "ambiguous_exact_event_api_rows": sum(len(row["api_row_ids"]) for row in ambiguous),
        "ambiguous_exact_event_keys": len(ambiguous),
        "evidence_rows": evidence,
        "unmatched_rows": unmatched,
        "comparison_unavailable_rows": comparison_unavailable,
        "ambiguous_exact_event_keys_detail": ambiguous,
        "page_parse": page_parse,
    }


def main():
    if (OUT / "collection_manifest.json").exists() or (OUT / "website_event_evidence.json").exists() or (OUT / "existing_page_ui_review.json").exists():
        raise FileExistsError("Refusing to overwrite an existing website review artifact")
    RAW.mkdir(exist_ok=True)
    old_review = inspect_existing_pages()
    old_ids = {row["horse_id"] for row in old_review["page_records"]}
    rows = read_candidates(old_ids)
    plan = choose_pages(rows, old_ids)
    if not plan:
        raise RuntimeError("No eligible recent unclassified horse pages were found")
    fetched = collect_pages(plan)
    by_horse = {row["horse_id"]: row for row in fetched}
    for item in plan:
        item.update({key: value for key, value in by_horse[item["horse_id"]].items() if key not in {"body"}})
    manifest_pages = []
    for row in fetched:
        manifest_pages.append({key: row[key] for key in row if key != "body"})
    collection = {
        "generated_at_utc": now_utc(),
        "host_allowlist": ["race.kra.co.kr"],
        "path_allowlist": ["/racehorse/profileTrainState.do"],
        "requested_page_count": len(plan),
        "success_count": sum(row.get("fetch_status") == "ok" for row in fetched),
        "failure_count": sum(row.get("fetch_status") != "ok" for row in fetched),
        "selection_window_inclusive": {"start": START_DATE, "end": END_DATE},
        "selection_rule": "Among recent rider_type=미분류 API18 rows with prGubun_raw='-' and complete positive time/duration, exclude the 32 prior horse pages and select up to eight horses with the most candidate rows; tie-break by numeric ID.",
        "candidate_cohort_rows": len(rows),
        "candidate_cohort_horse_count": len({str(row["horse_id"]) for row in rows}),
        "selected_pages": plan,
        "pages": manifest_pages,
        "database_access": "SQLite URI mode=ro with PRAGMA query_only=ON; no DB writes",
    }
    evidence = match_events(rows, fetched, load_collector())
    evidence_doc = {
        "generated_at_utc": now_utc(),
        "source_policy": "A page row is linked only on same horse ID, date, entry time, exit time, and duration in minutes. Role/type is a candidate only when that exact row visibly carries a direct marker: 조, 관, 생, or (트). Plain names are not typed from API categories, employee number, or current rosters/positions.",
        "selected_horses": plan,
        "summary": {key: value for key, value in evidence.items() if not key.endswith("_detail") and key not in {"evidence_rows", "unmatched_rows", "page_parse"}},
        "page_parse": evidence["page_parse"],
        "evidence_rows": evidence["evidence_rows"],
        "unmatched_rows": evidence["unmatched_rows"],
        "comparison_unavailable_rows": evidence["comparison_unavailable_rows"],
        "ambiguous_exact_event_keys": evidence["ambiguous_exact_event_keys_detail"],
    }
    write_new_json(OUT / "existing_page_ui_review.json", old_review)
    write_new_json(OUT / "collection_manifest.json", collection)
    write_new_json(OUT / "website_event_evidence.json", evidence_doc)
    print(json.dumps({
        "old_pages_sha_verified": old_review["verified_page_count"],
        "old_pages_with_six_month_notice": sum(item["notice_occurrences"] > 0 for item in old_review["page_records"]),
        "old_pages_with_date_input_or_select": old_review["date_input_page_count"] + old_review["date_select_page_count"],
        "new_pages_success": collection["success_count"], "new_pages_failure": collection["failure_count"],
        "selected_horses": [{"horse_id": item["horse_id"], "candidate_rows": item["candidate_api18_rows"], "fetch_status": item.get("fetch_status")} for item in plan],
        "event_summary": evidence_doc["summary"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
