#!/usr/bin/env python3
"""Independent read-only verification of event-specific Jeju rider types."""

from __future__ import annotations

from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import argparse
import hashlib
import json
import re
import sqlite3
import sys


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[3]
IDENTITY = PROJECT / "jeju/research/20261015_training_rider_identity"
SOURCE = IDENTITY / "source_review"
ROSTER = PROJECT / "data/research/jockey_roster_20261008"
TYPES = ("기수", "조교사", "조교보", "조교승인", "기수후보생", "주로조교", "교육생", "기수트랙라이더", "미분류")
API_TYPES = {"기수", "조교사", "조교보", "조교승인", "기수후보생"}
RAW_API_VALUES = API_TYPES | {"-"}
EXPECTED_WEB_COUNTS = {"기수": 311, "조교사": 121, "주로조교": 1236, "미분류": 23}
EXPECTED_ALL_HTML_LABEL_COUNTS = {"기수": 346, "조교사": 130, "주로조교": 1354, "미분류": 31}
ANALYSIS_CUTOFF = "2026-09-19"
EXPECTED_TOTAL = 908_316
EXPECTED_ANALYSIS = 907_389


def check(cond: bool, message: str, failures: list[str]) -> None:
    if not cond:
        failures.append(message)


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
                      default=lambda x: {"$bytes_hex": x.hex()} if isinstance(x, bytes) else str(x))


class PageParser(HTMLParser):
    """Extract table cells and hidden form values without application code."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.inputs = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        tag = tag.lower()
        if tag == "input" and attrs.get("name") and attrs.get("value") is not None:
            self.inputs[attrs["name"]] = attrs["value"]
        elif tag == "table":
            self.table = []
            self.tables.append(self.table)
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table":
            self.table = None


def parse_html(path: Path):
    body = path.read_bytes()
    decoded = None
    for enc in ("euc-kr", "cp949", "utf-8"):
        try:
            decoded = body.decode(enc)
            break
        except UnicodeDecodeError:
            pass
    if decoded is None:
        raise ValueError(f"cannot decode {path}")
    p = PageParser()
    p.feed(decoded)
    rows = []
    for table in p.tables:
        header_at = next((i for i, r in enumerate(table) if {"조교일자", "기승자", "입장시간", "퇴장시간", "조교시간"}.issubset(set(r))), None)
        if header_at is None:
            continue
        header = table[header_at]
        pos = {name: header.index(name) for name in ("조교일자", "기승자", "입장시간", "퇴장시간", "조교시간")}
        for r in table[header_at + 1:]:
            if max(pos.values()) >= len(r):
                continue
            date = re.match(r"^(\d{4})/(\d{2})/(\d{2})", r[pos["조교일자"]])
            start, end = r[pos["입장시간"]], r[pos["퇴장시간"]]
            mins = re.fullmatch(r"\s*(\d+)\s*분\s*", r[pos["조교시간"]])
            if not date or not re.fullmatch(r"\d{1,2}:\d{2}", start) or not re.fullmatch(r"\d{1,2}:\d{2}", end) or not mins:
                continue
            start = f"{int(start.split(':')[0]):02d}:{start.split(':')[1]}"
            end = f"{int(end.split(':')[0]):02d}:{end.split(':')[1]}"
            duration = int(mins.group(1)) * 60
            if (int(end[:2]) * 60 + int(end[3:]) - int(start[:2]) * 60 - int(start[3:])) * 60 != duration:
                continue
            rows.append({"date": "-".join(date.groups()), "label": r[pos["기승자"]], "start": start,
                         "end": end, "duration_seconds": duration})
    return p.inputs, rows, decoded


def page_label(label: str, roster_names: set[str]):
    """Classify labels from the official legend, conservatively requiring a roster for bare names."""
    if label in ("", "-", "외", "경주일"):
        return "미분류", None
    for token, kind in (("조", "조교사"), ("관", "주로조교"), ("생", "교육생"), ("트", "기수트랙라이더")):
        if (label == token and token != "트") or label.endswith("(" + token + ")"):
            return kind, None
    if label in roster_names:
        return "기수", label
    return "미분류", None


def event_key(horse, date, start, end, duration):
    if not start or not end:
        return None
    def minute(v):
        raw = str(v).strip()
        # SQLite source timestamps are ISO local strings with a trailing UTC offset;
        # use the event clock at positions 11:16 rather than the offset's clock.
        if len(raw) >= 16 and raw[10] in ("T", " "):
            raw = raw[11:16]
        else:
            raw = raw.split()[-1]
        m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", raw)
        return int(m.group(1)) * 60 + int(m.group(2)) if m else None
    sm, em = minute(start), minute(end)
    if sm is None or em is None or duration is None:
        return None
    return (str(horse), str(date), sm, em, int(duration))


def open_ro(path: Path):
    db = path.resolve(strict=True)
    c = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA query_only=ON")
    c.execute("PRAGMA foreign_keys=ON")
    if c.execute("PRAGMA query_only").fetchone()[0] != 1:
        raise RuntimeError("SQLite query_only could not be enabled")
    return c, db


def independent_web_map(c, failures):
    manifest_path = SOURCE / "http_collection_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pages = manifest.get("pages", [])
    check(len(pages) == 32, f"expected 32 official pages, found {len(pages)}", failures)
    evidence = json.loads((SOURCE / "staff_website_identity_evidence.json").read_text(encoding="utf-8"))
    evidence_pages = {str(x["horse_id"]): x["sha256"] for x in evidence.get("pages", [])}
    names = set()
    roster_manifest = json.loads((ROSTER / "manifest.json").read_text(encoding="utf-8"))
    roster_details = {}
    for meet in (1, 2, 3):
        path = ROSTER / f"api_{meet}.json"
        expected = {x["api_sha256"] for x in roster_manifest.get("rows", []) if int(x["meet_code"]) == meet}
        check(expected == {file_sha(path)}, f"roster API {meet} archive SHA mismatch", failures)
        doc = json.loads(path.read_text(encoding="utf-8"))
        body = doc["response"]["body"]
        raw = body["items"]["item"]
        items = [raw] if isinstance(raw, dict) else raw
        check(len(items) == int(body["totalCount"]), f"roster API {meet} incomplete", failures)
        roster_details[str(meet)] = {"rows": len(items), "totalCount": int(body["totalCount"])}
        names.update(x.get("jkName") for x in items if x.get("jkName") not in (None, "", "-"))
    selected = {str(p["horse_id"]) for p in pages}
    db_rows = c.execute("""SELECT daily_training_api_row_id, horse_id, training_date,
        start_time_local, end_time_local, duration_seconds, prGubun_raw, prNo_raw,
        daily_training_api_artifact_id, trName_raw, raw_row_json
        FROM daily_training_api_rows""").fetchall()
    api_by_key = defaultdict(list)
    source_by_id = {}
    for r in db_rows:
        source_by_id[r["daily_training_api_row_id"]] = r
        if str(r["horse_id"]) in selected and str(r["training_date"]) >= "2026-04-15":
            key = event_key(r["horse_id"], r["training_date"], r["start_time_local"], r["end_time_local"], r["duration_seconds"])
            if key:
                api_by_key[key].append(r)
    web = {}
    label_counts = Counter()
    raw_label_counts = Counter()
    all_html_label_counts = Counter()
    all_html_raw_label_counts = Counter()
    parsed_rows = 0
    matched_page_rows = 0
    ambiguous = []
    bare_names = Counter()
    unknown_bare = Counter()
    all_html_bare_names = Counter()
    all_html_unknown_bare = Counter()
    page_ids = set()
    for p in pages:
        hid = str(p["horse_id"])
        path = (PROJECT / p["source_path"]).resolve(strict=True)
        check(path.is_relative_to(SOURCE.resolve()), f"page path outside source review: {p['source_path']}", failures)
        check(p.get("http_status") == 200, f"official page status not 200: {hid}", failures)
        digest = file_sha(path)
        check(digest == p.get("sha256"), f"official page hash mismatch: {hid}", failures)
        check(evidence_pages.get(hid) == digest, f"independent page evidence hash mismatch: {hid}", failures)
        u = urlsplit(p.get("url", ""))
        q = parse_qs(u.query)
        check(u.scheme == "https" and u.hostname == "race.kra.co.kr" and u.path == "/racehorse/profileTrainState.do"
              and q.get("meet") == ["2"] and q.get("hrNo") == [hid], f"unexpected official page URL: {hid}", failures)
        inputs, rows, text = parse_html(path)
        check(inputs.get("hrNo") == hid, f"HTML horse ID mismatch: {hid}", failures)
        check("[기승자범례]" in text and all(x in text for x in ("이름:기수명", "조:조교사", "관:주로조교", "생:교육생", "이름(트):기수트랙라이더")),
              f"official rider legend absent/incomplete: {hid}", failures)
        parsed_rows += len(rows)
        for row in rows:
            raw_label = row["label"]
            html_kind, _ = page_label(raw_label, names)
            all_html_label_counts[html_kind] += 1
            all_html_raw_label_counts[raw_label] += 1
            if raw_label and raw_label not in ("-", "외", "경주일") and not re.search(r"\((?:관|조|생|트)\)$", raw_label) and raw_label not in ("관", "조", "생"):
                all_html_bare_names[raw_label] += 1
                if raw_label not in names:
                    all_html_unknown_bare[raw_label] += 1
            key = event_key(hid, row["date"], row["start"], row["end"], row["duration_seconds"])
            candidates = api_by_key.get(key, [])
            if len(candidates) > 1:
                ambiguous.append({"horse_id": hid, "key": list(key), "api_row_ids": [x["daily_training_api_row_id"] for x in candidates]})
                continue
            if not candidates:
                continue
            label_counts[page_label(raw_label, names)[0]] += 1
            raw_label_counts[raw_label] += 1
            if raw_label and raw_label not in ("-", "외", "경주일") and not re.search(r"\((?:관|조|생|트)\)$", raw_label) and raw_label not in ("관", "조", "생"):
                bare_names[raw_label] += 1
                if raw_label not in names:
                    unknown_bare[raw_label] += 1
            rid = candidates[0]["daily_training_api_row_id"]
            if rid in web:
                check(web[rid]["label"] == raw_label, f"two different page labels match event id {rid}", failures)
            else:
                web[rid] = {"type": page_label(raw_label, names)[0], "name": page_label(raw_label, names)[1],
                            "label": raw_label, "path": p["source_path"], "sha": digest}
                matched_page_rows += 1
            page_ids.add(hid)
    check(not ambiguous, f"ambiguous same-event API keys: {len(ambiguous)}", failures)
    check(dict(label_counts) == EXPECTED_WEB_COUNTS, f"same-event page type counts differ: {dict(label_counts)}", failures)
    check(not unknown_bare, f"unrecognized bare page labels: {dict(unknown_bare)}", failures)
    check(dict(all_html_label_counts) == EXPECTED_ALL_HTML_LABEL_COUNTS,
          f"all-page label type counts differ: {dict(all_html_label_counts)}", failures)
    check(not all_html_unknown_bare, f"unrecognized bare labels in all HTML rows: {dict(all_html_unknown_bare)}", failures)
    return web, source_by_id, {"page_count": len(pages), "parsed_training_rows": parsed_rows,
        "same_event_matches": matched_page_rows, "page_types": dict(label_counts),
        "raw_labels": dict(raw_label_counts), "bare_name_labels": dict(bare_names),
        "unrecognized_bare_labels": dict(unknown_bare),
        "all_html_page_type_counts": dict(all_html_label_counts),
        "all_html_raw_label_counts": dict(all_html_raw_label_counts),
        "all_html_bare_name_labels": dict(all_html_bare_names),
        "all_html_unrecognized_bare_labels": dict(all_html_unknown_bare),
        "unmatched_html_training_rows": parsed_rows - matched_page_rows,
        "ambiguous_exact_keys": ambiguous,
        "roster_names_count_union": len(names), "roster_meets": roster_details,
        "manifest_sha256": file_sha(manifest_path)}


def expected_classification(row, web):
    observed = web.get(row["daily_training_api_row_id"])
    api = row["prGubun_raw"]
    if api in API_TYPES:
        kind, status = api, "api_category_observed"
        if observed and observed["type"] not in ("미분류", api):
            if api == "기수" and observed["type"] == "기수트랙라이더":
                kind, status = "기수트랙라이더", "website_track_rider_specialization"
            elif (api == "기수후보생" and observed["type"] == "교육생") or (api in ("조교보", "조교승인") and observed["type"] == "주로조교"):
                status = "api_category_website_compatible"
            else:
                kind, status = "미분류", "api_website_type_conflict"
    elif observed and observed["type"] != "미분류":
        kind, status = observed["type"], "website_same_event_type"
    elif observed:
        kind, status = "미분류", "unclassified_website_label"
    else:
        kind, status = "미분류", "unclassified_api_category_missing"
    return kind, status, observed


def rows_digest(c, table):
    info = c.execute(f'PRAGMA table_info("{table}")').fetchall()
    columns = [x["name"] for x in info]
    quoted = ",".join('"' + x.replace('"', '""') + '"' for x in columns)
    # A commutative multiset fingerprint avoids large SQLite ORDER BY temp sorts.
    # Each row is SHA-256 hashed; both the 256-bit sum and XOR are accumulated,
    # then bound with the row count. Duplicate rows therefore affect the result.
    sum_acc = 0
    xor_acc = 0
    n = 0
    for row in c.execute(f'SELECT {quoted} FROM "{table}"'):
        item = int.from_bytes(hashlib.sha256(canonical(list(row)).encode("utf-8")).digest(), "big")
        sum_acc = (sum_acc + item) % (1 << 256)
        xor_acc ^= item
        n += 1
    aggregate = f"rows={n};sum={sum_acc:064x};xor={xor_acc:064x}".encode("ascii")
    return n, hashlib.sha256(aggregate).hexdigest()


def schema_objects(c):
    return {r["name"]: r["sql"] for r in c.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL")}


def verify(args):
    failures = []
    c, db = open_ro(args.db)
    before = {"db": file_sha(db), "wal": file_sha(Path(str(db) + "-wal")) if Path(str(db) + "-wal").exists() else None}
    web, source_by_id, web_summary = independent_web_map(c, failures)
    objects = schema_objects(c)
    assignment_exists = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_training_rider_type_assignments'").fetchone()
    check(assignment_exists is not None, "type assignment table absent", failures)
    expected_new = {"daily_training_rider_type_assignments", "daily_training_rider_type_values", "daily_training_rider_types", "daily_training_rider_types_analysis_2026"}
    check(expected_new.issubset(objects), f"missing new schema objects: {sorted(expected_new - objects.keys())}", failures)

    raw_values = dict(c.execute("SELECT prGubun_raw, COUNT(*) FROM daily_training_api_rows GROUP BY prGubun_raw").fetchall())
    check(set(raw_values) == RAW_API_VALUES, f"raw API category set changed: {sorted(raw_values)}", failures)
    total = c.execute("SELECT COUNT(*) FROM daily_training_api_rows").fetchone()[0]
    check(total == EXPECTED_TOTAL, f"source row count {total} != {EXPECTED_TOTAL}", failures)
    assignment_total = c.execute("SELECT COUNT(*) FROM daily_training_rider_type_assignments").fetchone()[0]
    check(assignment_total == total, f"assignment row count {assignment_total} != source {total}", failures)
    dupes = c.execute("SELECT COUNT(*) FROM (SELECT daily_training_api_row_id FROM daily_training_rider_type_assignments GROUP BY 1 HAVING COUNT(*)!=1)").fetchone()[0]
    check(dupes == 0, f"assignment event key duplicates: {dupes}", failures)
    missing = c.execute("SELECT COUNT(*) FROM daily_training_api_rows d LEFT JOIN daily_training_rider_type_assignments a USING(daily_training_api_row_id) WHERE a.daily_training_api_row_id IS NULL").fetchone()[0]
    extra = c.execute("SELECT COUNT(*) FROM daily_training_rider_type_assignments a LEFT JOIN daily_training_api_rows d USING(daily_training_api_row_id) WHERE d.daily_training_api_row_id IS NULL").fetchone()[0]
    check(missing == 0 and extra == 0, f"assignment coverage missing={missing}, extra={extra}", failures)

    source_cols = [x["name"] for x in c.execute("PRAGMA table_info(daily_training_api_rows)")]
    type_cols = [x["name"] for x in c.execute("PRAGMA table_info(daily_training_rider_types)")]
    check(source_cols == type_cols[:len(source_cols)], "type view changed/reordered original source columns", failures)
    assignment_cols = ["daily_training_api_row_id", "daily_training_api_artifact_id", "prGubun_raw", "prNo_raw", "horse_id", "training_date", "start_time_local", "end_time_local", "duration_seconds"]
    type_count = Counter()
    status_count = Counter()
    scope_count = Counter()
    raw_preservation_mismatches = []
    classifier_mismatches = []
    name_mismatches = []
    wrong_non_jockey_names = []
    source_query = "SELECT " + ",".join('d."' + x + '"' for x in assignment_cols) + ",d.raw_row_json,d.trName_raw,a.rider_type,a.type_status,a.website_type,a.website_label_raw,a.website_jockey_name,a.website_source_path,a.website_sha256 FROM daily_training_api_rows d JOIN daily_training_rider_type_assignments a USING(daily_training_api_row_id) ORDER BY d.daily_training_api_row_id"
    rows_checked = 0
    for row in c.execute(source_query):
        rows_checked += 1
        rid = row["daily_training_api_row_id"]
        source = source_by_id.get(rid)
        if source is None:
            continue
        # Assignment columns must be exact snapshots, preserving identifiers as text.
        for col in assignment_cols:
            if row[col] != source[col]:
                raw_preservation_mismatches.append({"id": rid, "column": col, "stored": row[col], "source": source[col]})
        if row["raw_row_json"] != source["raw_row_json"] or row["trName_raw"] != source["trName_raw"]:
            raw_preservation_mismatches.append({"id": rid, "column": "raw_row_json/trName_raw"})
        kind, status, observed = expected_classification(source, web)
        if (row["rider_type"], row["type_status"]) != (kind, status):
            classifier_mismatches.append({"id": rid, "actual": [row["rider_type"], row["type_status"]], "expected": [kind, status], "api": source["prGubun_raw"], "web": observed})
        expected_web = (observed["type"], observed["label"], observed["name"], observed["path"], observed["sha"]) if observed else (None, None, None, None, None)
        actual_web = (row["website_type"], row["website_label_raw"], row["website_jockey_name"], row["website_source_path"], row["website_sha256"])
        if actual_web != expected_web:
            classifier_mismatches.append({"id": rid, "web_actual": actual_web, "web_expected": expected_web})
        type_count[kind] += 1
        status_count[status] += 1
        if source["training_date"] <= ANALYSIS_CUTOFF:
            scope_count[("analysis_2026", kind)] += 1
        if source["prGubun_raw"] == "-" and not observed and kind != "미분류":
            classifier_mismatches.append({"id": rid, "reason": "dash row classified without same-event evidence", "actual": kind})

    check(rows_checked == EXPECTED_TOTAL, f"joined source/assignment rows {rows_checked} != {EXPECTED_TOTAL}", failures)
    check(not raw_preservation_mismatches, f"raw source snapshot mismatches: {raw_preservation_mismatches[:5]}", failures)
    check(not classifier_mismatches, f"classification/evidence mismatches: {classifier_mismatches[:5]}", failures)

    expected_all = {"기수": 315601, "조교사": 111648, "조교보": 71889, "조교승인": 107371, "기수후보생": 1696, "주로조교": 1236, "교육생": 0, "기수트랙라이더": 0, "미분류": 298875}
    expected_analysis = {"기수": 315295, "조교사": 111527, "조교보": 71889, "조교승인": 107371, "기수후보생": 1696, "주로조교": 1185, "교육생": 0, "기수트랙라이더": 0, "미분류": 298426}
    check({t: type_count[t] for t in TYPES} == expected_all, f"all-row type totals differ: {dict(type_count)}", failures)
    view_all = c.execute("SELECT COUNT(*) FROM daily_training_rider_types").fetchone()[0]
    view_analysis = c.execute("SELECT COUNT(*) FROM daily_training_rider_types_analysis_2026").fetchone()[0]
    check(view_all == EXPECTED_TOTAL, f"all-row view count {view_all} != {EXPECTED_TOTAL}", failures)
    check(view_analysis == EXPECTED_ANALYSIS, f"analysis view count {view_analysis} != {EXPECTED_ANALYSIS}", failures)
    view_counts = dict(c.execute("SELECT rider_type,COUNT(*) FROM daily_training_rider_types GROUP BY rider_type").fetchall())
    check({t: view_counts.get(t, 0) for t in TYPES} == expected_all, f"view type counts differ: {view_counts}", failures)
    analysis_counts = dict(c.execute("SELECT rider_type,COUNT(*) FROM daily_training_rider_types_analysis_2026 GROUP BY rider_type").fetchall())
    check({t: analysis_counts.get(t, 0) for t in TYPES} == expected_analysis, f"analysis view type counts differ: {analysis_counts}", failures)
    bad_names = c.execute("SELECT COUNT(*) FROM daily_training_rider_types WHERE rider_type<>'기수' AND jockey_name IS NOT NULL").fetchone()[0]
    missing_name_leak = c.execute("SELECT COUNT(*) FROM daily_training_rider_types WHERE rider_type='미분류' AND jockey_name IS NOT NULL").fetchone()[0]
    check(bad_names == 0 and missing_name_leak == 0, f"jockey_name leaked to non-jockey/unclassified rows: {bad_names}/{missing_name_leak}", failures)
    unresolved_jockeys = c.execute("SELECT COUNT(*) FROM daily_training_rider_types WHERE rider_type='기수' AND jockey_name IS NULL").fetchone()[0]
    check(unresolved_jockeys == 2, f"unresolved jockey-name count changed: {unresolved_jockeys}", failures)
    # Verify names come from same-event page evidence or the pre-existing identity view.
    bad_name_source = c.execute("""SELECT COUNT(*) FROM daily_training_rider_types t
        JOIN daily_training_rider_type_values v USING(daily_training_api_row_id)
        LEFT JOIN daily_training_riders n USING(daily_training_api_row_id)
        WHERE t.rider_type='기수' AND t.jockey_name IS NOT COALESCE(v.website_jockey_name,n.rider_name)""").fetchone()[0]
    check(bad_name_source == 0, f"jockey display name differs from permitted source: {bad_name_source}", failures)
    dash_not_unknown = c.execute("""SELECT COUNT(*) FROM daily_training_rider_types
        WHERE prGubun_raw='-' AND rider_type<>'미분류' AND rider_type_status<>'website_same_event_type'""").fetchone()[0]
    check(dash_not_unknown == 0, f"dash row typed without exact same-event evidence: {dash_not_unknown}", failures)
    status_counts = dict(c.execute("SELECT type_status,COUNT(*) FROM daily_training_rider_type_assignments GROUP BY type_status").fetchall())
    expected_status = {"api_category_observed": 608205, "website_same_event_type": 1236,
                       "unclassified_api_category_missing": 298852, "unclassified_website_label": 23}
    check(status_counts == expected_status, f"type status totals differ: {status_counts}", failures)
    view_key_dupes = c.execute("SELECT COUNT(*) FROM (SELECT daily_training_api_row_id FROM daily_training_rider_types GROUP BY 1 HAVING COUNT(*)>1)").fetchone()[0]
    check(view_key_dupes == 0, f"type view event-key duplicates: {view_key_dupes}", failures)

    baseline_summary = None
    if args.baseline:
        b, baseline_path = open_ro(args.baseline)
        baseline_objects = schema_objects(b)
        old_obj_diffs = {n: {"baseline": sql, "actual": objects.get(n)} for n, sql in baseline_objects.items() if objects.get(n) != sql}
        new_objects = sorted(set(objects) - set(baseline_objects))
        check(not old_obj_diffs, f"pre-existing schema SQL changed: {sorted(old_obj_diffs)}", failures)
        check(set(new_objects) == expected_new, f"new schema objects differ from expected: {new_objects}", failures)
        compare_rows = args.full_old_preservation
        table_results = {}
        if compare_rows:
            base_tables = sorted(r[0] for r in b.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
            for table in base_tables:
                bn, bh = rows_digest(b, table)
                an, ah = rows_digest(c, table)
                table_results[table] = {"baseline_rows": bn, "actual_rows": an, "baseline_sha256": bh, "actual_sha256": ah, "unchanged": bn == an and bh == ah}
                check(table_results[table]["unchanged"], f"pre-existing table rows changed: {table}", failures)
        baseline_summary = {"path": str(baseline_path), "old_schema_differences": sorted(old_obj_diffs),
                            "new_schema_objects": new_objects, "full_table_comparison": compare_rows,
                            "old_table_results": table_results}
        b.close()

    c.close()
    after = {"db": file_sha(db), "wal": file_sha(Path(str(db) + "-wal")) if Path(str(db) + "-wal").exists() else None}
    check(before == after, f"database files changed during read-only audit: before={before}, after={after}", failures)
    return {"verification": "jeju_daily_training_rider_type_independent_verification",
            "database": str(db), "read_only": True, "query_only": True,
            "database_file_sha256_before_after": {"before": before, "after": after},
            "source_rows": total, "assignments": assignment_total,
            "analysis_view_rows": view_analysis, "raw_api_category_counts": raw_values,
            "same_event_website_review": web_summary,
            "type_counts_all": {t: type_count[t] for t in TYPES},
            "type_counts_analysis_2026": {t: analysis_counts.get(t, 0) for t in TYPES},
            "type_status_counts": status_counts,
            "jockey_name_checks": {"non_jockey_nonnull": bad_names, "unclassified_nonnull": missing_name_leak,
                                   "unresolved_jockey_names": unresolved_jockeys,
                                   "bad_permitted_name_source": bad_name_source},
            "baseline_comparison": baseline_summary,
            "failures": failures, "passed": not failures}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--full-old-preservation", action="store_true", help="hash every pre-existing table against baseline")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(HERE.resolve()):
        raise SystemExit("output must be under this verification directory")
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing report: {output}")
    if args.full_old_preservation and not args.baseline:
        raise SystemExit("--full-old-preservation requires --baseline")
    report = verify(args)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "failures": report["failures"],
                      "output": str(output), "types": report["type_counts_all"],
                      "web": report["same_event_website_review"]}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
