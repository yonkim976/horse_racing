#!/usr/bin/env python3
"""Read-only, offline audit of daily-training rider types and stored KRA HTML."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import argparse
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
DB_PATH = REPO_ROOT / "jeju/data/jeju_native_core.sqlite3"
IDENTITY_DIR = REPO_ROOT / "jeju/research/20261015_training_rider_identity"
SOURCE_REVIEW_DIR = IDENTITY_DIR / "source_review"
RAW_HTML_DIR = SOURCE_REVIEW_DIR / "raw_html"
SOURCE_MANIFEST_PATH = SOURCE_REVIEW_DIR / "http_collection_manifest.json"
OBSERVATION_EVIDENCE_PATH = SOURCE_REVIEW_DIR / "staff_website_identity_evidence.json"
OUTPUT_DIR = Path(__file__).resolve().parent

EXPECTED_ROWS = 908_316
ANALYSIS_CUTOFF = "2026-09-19"
RECENT_WINDOW_START = "2026-04-15"
RECENT_WINDOW_END = "2026-09-28"
KNOWN_API_TYPES = {
    "기수": "기수",
    "기수후보생": "기수후보생",
    "조교사": "조교사",
    "조교보": "조교보",
    "조교승인": "조교승인",
}
TYPE_ORDER = [
    "기수", "조교사", "조교보", "조교승인", "기수후보생",
    "주로조교", "교육생", "기수트랙라이더", "미분류",
]
DATE_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
MINUTES_RE = re.compile(r"^(\d+)\s*분$")
HORSE_ID_RE = re.compile(r"^\d{1,12}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def db_fingerprint() -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for suffix in ("", "-wal"):
        path = Path(str(DB_PATH) + suffix)
        result[suffix or "main"] = sha256_file(path) if path.is_file() else None
    return result


class IndependentTableParser(HTMLParser):
    """Small table-only parser, separate from the identity source-review parser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.current_table: list[list[str]] | None = None
        self.current_row: list[str] | None = None
        self.current_cell: list[str] | None = None
        self.form_values: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        tag = tag.lower()
        if tag == "input":
            name, value = attrs_map.get("name"), attrs_map.get("value")
            if name and value is not None:
                self.form_values[name] = value
        elif tag == "table":
            self.current_table = []
            self.tables.append(self.current_table)
        elif tag == "tr" and self.current_table is not None:
            self.current_row = []
        elif tag in ("th", "td") and self.current_row is not None:
            self.current_cell = []

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None:
            self.current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("th", "td") and self.current_row is not None and self.current_cell is not None:
            self.current_row.append(" ".join("".join(self.current_cell).split()))
            self.current_cell = None
        elif tag == "tr" and self.current_table is not None and self.current_row is not None:
            self.current_table.append(self.current_row)
            self.current_row = None
        elif tag == "table":
            self.current_table = None


def decode_html(body: bytes, content_type: str) -> str:
    found = re.search(r"charset\s*=\s*['\"]?([A-Za-z0-9._-]+)", content_type, re.I)
    encodings = ([found.group(1)] if found else []) + ["utf-8", "cp949", "euc-kr"]
    for encoding in encodings:
        try:
            return body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    raise ValueError("Could not decode stored official HTML")


def parse_role_label(raw_label: str | None) -> tuple[str | None, str]:
    """Return an explicit page type and a stable label state from KRA's legend."""
    value = " ".join((raw_label or "").split())
    if value == "외":
        return None, "external_marker_meaning_unresolved"
    token_types = {"관": "주로조교", "조": "조교사", "생": "교육생"}
    if value in token_types:
        return token_types[value], "explicit_role_token_without_name"
    for suffix, rider_type in (
        ("(관)", "주로조교"), ("(조)", "조교사"),
        ("(생)", "교육생"), ("(트)", "기수트랙라이더"),
    ):
        if value.endswith(suffix):
            return rider_type, "explicit_role_suffix"
    if value and value not in {"-", "경주일"}:
        # KRA's page legend explicitly defines an unmarked person name as a jockey.
        return "기수", "explicit_unmarked_jockey_name_per_legend"
    return None, "no_person_or_role_marker"


def label_marker_bucket(raw_label: str | None) -> str:
    """Summarize role labels without copying names of non-jockey staff."""
    value = " ".join((raw_label or "").split())
    if value == "외":
        return "외"
    if value in {"관", "조", "생"}:
        return f"역할표식_이름없음_{value}"
    for suffix in ("(관)", "(조)", "(생)", "(트)"):
        if value.endswith(suffix):
            return suffix
    if value and value not in {"-", "경주일"}:
        return "표식없는이름"
    return "이름또는역할표식없음"


def parse_profile_page(body: bytes, content_type: str, expected_horse_id: str) -> dict[str, Any]:
    text = decode_html(body, content_type)
    parser = IndependentTableParser()
    parser.feed(text)
    profile_name = None
    training_rows: list[dict[str, Any]] = []
    required = {"조교일자", "기승자", "입장시간", "퇴장시간", "조교시간"}
    training_table_found = False

    for table in parser.tables:
        for row in table:
            if "마명" in row and row.index("마명") + 1 < len(row):
                profile_name = row[row.index("마명") + 1]
                break
        heading_index = next(
            (index for index, row in enumerate(table) if required.issubset(set(row))),
            None,
        )
        if heading_index is None:
            continue
        training_table_found = True
        header = table[heading_index]
        positions = {key: header.index(key) for key in required}
        for row in table[heading_index + 1:]:
            if max(positions.values()) >= len(row):
                continue
            date_match = DATE_RE.match(row[positions["조교일자"]])
            duration_match = MINUTES_RE.fullmatch(row[positions["조교시간"]])
            start_text = row[positions["입장시간"]]
            end_text = row[positions["퇴장시간"]]
            if not date_match or not duration_match:
                continue
            if not TIME_RE.fullmatch(start_text) or not TIME_RE.fullmatch(end_text):
                continue
            raw_label = row[positions["기승자"]]
            page_type, label_state = parse_role_label(raw_label)
            training_rows.append({
                "date": "-".join(date_match.groups()),
                "raw_label": raw_label,
                "page_type": page_type,
                "label_state": label_state,
                "start": start_text,
                "end": end_text,
                "duration_minutes": int(duration_match.group(1)),
            })

    profile_id = parser.form_values.get("hrNo") or parser.form_values.get("hrno")
    return {
        "profile_id": profile_id,
        "profile_id_matches_expected": profile_id == expected_horse_id,
        "profile_name_raw": profile_name,
        "training_table_found": training_table_found,
        "training_rows": training_rows,
        "source_legend": extract_legend(text),
    }


def extract_legend(text: str) -> str | None:
    match = re.search(r"\[기승자범례\](.*?)</p>", text, flags=re.I | re.S)
    if not match:
        return None
    without_tags = re.sub(r"<[^>]*>", " ", match.group(1))
    return " ".join(without_tags.split())


def minute_of_day(value: str | None) -> int | None:
    text = (value or "").strip().split()
    candidate = text[-1][:5] if text else ""
    match = TIME_RE.fullmatch(candidate)
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def json_ready_counts(counter: Counter[str], keys: list[str] | None = None) -> dict[str, int]:
    ordered = keys if keys is not None else sorted(counter)
    return {key: int(counter.get(key, 0)) for key in ordered}


def page_key(row: dict[str, Any], horse_id: str) -> tuple[str, str, int, int, int] | None:
    start = minute_of_day(row.get("start"))
    end = minute_of_day(row.get("end"))
    if start is None or end is None:
        return None
    return (horse_id, row["date"], start, end, int(row["duration_minutes"]) * 60)


def api_key(row: sqlite3.Row) -> tuple[str, str, int, int, int] | None:
    start = minute_of_day(row["start_time_local"])
    end = minute_of_day(row["end_time_local"])
    if start is None or end is None or row["duration_seconds"] is None:
        return None
    return (
        str(row["horse_id"]), str(row["training_date"]), start, end,
        int(row["duration_seconds"]),
    )


def load_pages() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    expected_pages = manifest.get("pages", [])
    if len(expected_pages) != 32:
        raise RuntimeError(f"Expected 32 stored pages; found {len(expected_pages)}")
    evidence = json.loads(OBSERVATION_EVIDENCE_PATH.read_text(encoding="utf-8"))
    if len(evidence.get("pages", [])) != 32:
        raise RuntimeError("Independent evidence manifest does not contain 32 pages")
    evidence_page_hashes = {
        str(item["horse_id"]): str(item["sha256"])
        for item in evidence["pages"]
    }
    manifest_page_hashes = {
        str(item["horse_id"]): str(item["sha256"])
        for item in expected_pages
    }
    if evidence_page_hashes != manifest_page_hashes:
        raise RuntimeError("Stored page hashes disagree across the two source manifests")

    pages: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    all_legends: Counter[str] = Counter()
    for item in expected_pages:
        if item.get("http_status") != 200:
            raise RuntimeError(f"Stored page was not HTTP 200: {item.get('horse_id')}")
        horse_id = str(item["horse_id"])
        if not HORSE_ID_RE.fullmatch(horse_id):
            raise RuntimeError(f"Invalid horse ID in stored page manifest: {horse_id!r}")
        path = RAW_HTML_DIR / f"kra_profileTrainState_hrNo_{horse_id}.html"
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest != item.get("sha256"):
            raise RuntimeError(f"Stored HTML SHA-256 does not match manifest: {horse_id}")
        parsed = parse_profile_page(body, str(item.get("content_type") or ""), horse_id)
        if not parsed["profile_id_matches_expected"] or not parsed["profile_name_raw"]:
            raise RuntimeError(f"Profile identity did not verify: {horse_id}")
        if not parsed["training_table_found"]:
            raise RuntimeError(f"Training table was not found: {horse_id}")
        if parsed["source_legend"]:
            all_legends[parsed["source_legend"]] += 1
        pages.append({
            "horse_id": horse_id,
            "source_path": str(path.relative_to(REPO_ROOT)),
            "source_sha256": digest,
            "training_rows": parsed["training_rows"],
        })
        hashes[horse_id] = digest

    expected_ids = {str(item["horse_id"]) for item in expected_pages}
    if len(expected_ids) != 32 or set(hashes) != expected_ids:
        raise RuntimeError("Page manifest contains duplicate or inconsistent horse IDs")
    if not all_legends:
        raise RuntimeError("Official rider legend was not found in stored HTML")
    return pages, {
        "page_count": len(pages),
        "page_horse_ids": sorted(expected_ids),
        "pages_sha256_by_horse_id": dict(sorted(hashes.items())),
        "legend_counts": dict(sorted(all_legends.items())),
        "independent_evidence_page_count": len(evidence["pages"]),
        "stored_named_and_external_observation_counts": {
            "named_exact_event_rows": len(evidence.get("evidence", [])),
            "external_unresolved_exact_event_rows": len(evidence.get("unresolved_observations", [])),
        },
    }


def connect_read_only() -> sqlite3.Connection:
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"Missing SQLite database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    if int(conn.execute("PRAGMA query_only").fetchone()[0]) != 1:
        raise RuntimeError("SQLite query_only could not be enabled")
    return conn


def read_type_counts(
    conn: sqlite3.Connection,
    expected_source_sha_by_path: dict[str, str],
) -> dict[str, Any]:
    total = int(conn.execute("SELECT COUNT(*) FROM daily_training_api_rows").fetchone()[0])
    if total != EXPECTED_ROWS:
        raise RuntimeError(f"Expected {EXPECTED_ROWS} API rows, found {total}")
    analysis_view_count = int(
        conn.execute("SELECT COUNT(*) FROM daily_training_api_rows_analysis_2026").fetchone()[0]
    )
    if analysis_view_count != 907_389:
        raise RuntimeError(
            "Expected 907389 rows in daily_training_api_rows_analysis_2026, "
            f"found {analysis_view_count}"
        )

    raw_rows = conn.execute(
        """SELECT d.daily_training_api_row_id, d.prGubun_raw, d.training_date,
                  w.rider_name_raw, w.person_name,
                  w.source_path, w.source_sha256
             FROM daily_training_api_rows d
             LEFT JOIN training_rider_website_observations w
               ON w.daily_training_api_row_id=d.daily_training_api_row_id
            ORDER BY d.daily_training_api_row_id"""
    ).fetchall()

    raw_category_counts: Counter[str] = Counter()
    scopes: dict[str, dict[str, Any]] = {
        "all_stored_rows": {"predicate": "all daily_training_api_rows"},
        "analysis_through_2026_09_19": {
            "predicate": "training_date <= 2026-09-19",
            "inclusive_end_date": ANALYSIS_CUTOFF,
        },
        "2017_onward_analysis_scope": {
            "predicate": "2017-01-01 <= training_date <= 2026-09-19",
            "inclusive_start_date": "2017-01-01",
            "inclusive_end_date": ANALYSIS_CUTOFF,
        },
        "2017_onward_all_stored": {
            "predicate": "2017-01-01 <= training_date <= max stored training_date",
            "inclusive_start_date": "2017-01-01",
        },
    }
    type_counters = {key: Counter() for key in scopes}
    status_counters = {key: Counter() for key in scopes}
    included_counts: Counter[str] = Counter()
    website_label_counts: Counter[str] = Counter()
    website_api_category_counts: Counter[str] = Counter()
    observed_sources: dict[str, str] = {}
    type_conflict_rows: list[dict[str, Any]] = []

    for row in raw_rows:
        row_id = int(row["daily_training_api_row_id"])
        api_raw = row["prGubun_raw"]
        date = str(row["training_date"])
        api_type = KNOWN_API_TYPES.get(api_raw)
        web_type: str | None = None
        web_state = "no_same_event_website_type"
        web_raw = row["rider_name_raw"]
        if web_raw is not None:
            web_type, web_state = parse_role_label(web_raw)
            website_label_counts[str(web_raw)] += 1
            website_api_category_counts[str(api_raw)] += 1
            path_text = row["source_path"]
            digest = row["source_sha256"]
            if path_text:
                expected_digest = expected_source_sha_by_path.get(str(path_text))
                if expected_digest is None:
                    raise RuntimeError(f"Website observation references an unexpected stored page: {path_text}")
                if expected_digest != digest:
                    raise RuntimeError(f"Website observation page SHA does not match stored source: {path_text}")
                if observed_sources.get(str(path_text)) not in (None, digest):
                    raise RuntimeError(f"Inconsistent SHA references for website source: {path_text}")
                observed_sources[str(path_text)] = str(digest)

        if api_type is not None:
            effective_type = api_type
            status = "api_role_explicit"
            if web_type is not None and web_type != api_type:
                effective_type = "미분류"
                status = "api_website_type_conflict"
                type_conflict_rows.append({
                    "daily_training_api_row_id": row_id,
                    "api_category_raw": api_raw,
                    "api_type": api_type,
                    "website_type": web_type,
                    "status": status,
                })
        elif api_raw == "-":
            if web_type is not None:
                effective_type = web_type
                status = f"website_same_event_{web_state}"
            elif web_raw == "외":
                effective_type = "미분류"
                status = "website_external_marker_semantics_unresolved"
            elif web_raw is not None:
                effective_type = "미분류"
                status = f"website_label_unresolved:{web_state}"
            else:
                effective_type = "미분류"
                status = "api_role_dash_without_same_event_website_type"
        else:
            effective_type = "미분류"
            status = "api_role_unrecognized_raw_value"

        if status.startswith("api_website_type_conflict"):
            # The API category is kept as raw evidence; effective type is withheld.
            pass
        for scope_key in scopes:
            in_scope = scope_key == "all_stored_rows"
            if scope_key == "analysis_through_2026_09_19":
                in_scope = date <= ANALYSIS_CUTOFF
            elif scope_key == "2017_onward_analysis_scope":
                in_scope = "2017-01-01" <= date <= ANALYSIS_CUTOFF
            elif scope_key == "2017_onward_all_stored":
                in_scope = date >= "2017-01-01"
            if in_scope:
                type_counters[scope_key][effective_type] += 1
                status_counters[scope_key][status] += 1
                included_counts[scope_key] += 1
        raw_category_counts[str(api_raw)] += 1

    website_counts_by_type: Counter[str] = Counter()
    website_marker_counts: Counter[str] = Counter()
    for label, count in website_label_counts.items():
        role, _ = parse_role_label(label)
        website_counts_by_type[role or "미분류"] += count
        website_marker_counts[label_marker_bucket(label)] += count

    expected_raw_categories = set(KNOWN_API_TYPES) | {"-"}
    if set(raw_category_counts) != expected_raw_categories:
        raise RuntimeError(
            "Unexpected raw prGubun_raw values: "
            f"{sorted(raw_category_counts, key=str)}"
        )

    count_block: dict[str, Any] = {}
    for scope_key, metadata in scopes.items():
        count_block[scope_key] = {
            **metadata,
            "row_count": int(included_counts[scope_key]),
            "rows_by_type": json_ready_counts(type_counters[scope_key], TYPE_ORDER),
            "rows_by_classification_status": json_ready_counts(status_counters[scope_key]),
        }
        if sum(type_counters[scope_key].values()) != included_counts[scope_key]:
            raise RuntimeError(f"Classification row counts do not balance for {scope_key}")

    return {
        "daily_training_api_rows": total,
        "daily_training_api_rows_analysis_2026": analysis_view_count,
        "raw_prGubun_counts": json_ready_counts(raw_category_counts),
        "type_counts_by_scope": count_block,
        "website_observation_count": sum(website_label_counts.values()),
        "website_observation_api_category_counts": json_ready_counts(website_api_category_counts),
        "website_observation_rows_by_marker": json_ready_counts(website_marker_counts),
        "website_observation_rows_by_supplemented_type": json_ready_counts(website_counts_by_type, TYPE_ORDER),
        "website_observation_source_page_count": len(observed_sources),
        "website_observation_source_sha256_by_path": dict(sorted(observed_sources.items())),
        "api_website_type_conflict_rows": type_conflict_rows,
        "unclassified_reasons_by_scope": {
            scope: {
                status: count
                for status, count in block["rows_by_classification_status"].items()
                if status != "api_role_explicit" and not status.startswith("website_same_event_")
            }
            for scope, block in count_block.items()
        },
    }


def review_stored_pages(
    conn: sqlite3.Connection,
    pages: list[dict[str, Any]],
    legend_counts: dict[str, int],
) -> dict[str, Any]:
    horse_ids = [page["horse_id"] for page in pages]
    placeholders = ",".join("?" for _ in horse_ids)
    query = f"""SELECT daily_training_api_row_id, horse_id, training_date,
                      start_time_local, end_time_local, duration_seconds,
                      prGubun_raw, prNo_raw
                 FROM daily_training_api_rows
                WHERE training_date>=? AND training_date<=?
                  AND horse_id IN ({placeholders})
                  AND start_time_local IS NOT NULL AND end_time_local IS NOT NULL
                  AND duration_seconds IS NOT NULL AND duration_seconds>0"""
    api_rows = conn.execute(query, [RECENT_WINDOW_START, RECENT_WINDOW_END, *horse_ids]).fetchall()
    api_by_key: dict[tuple[str, str, int, int, int], list[sqlite3.Row]] = defaultdict(list)
    for row in api_rows:
        key = api_key(row)
        if key is not None:
            api_by_key[key].append(row)

    web_by_key: dict[tuple[str, str, int, int, int], list[dict[str, Any]]] = defaultdict(list)
    html_row_count = 0
    page_row_types: Counter[str] = Counter()
    page_marker_counts: Counter[str] = Counter()
    for page in pages:
        horse = page["horse_id"]
        for webrow in page["training_rows"]:
            html_row_count += 1
            page_marker_counts[label_marker_bucket(webrow["raw_label"])] += 1
            page_row_types[webrow["page_type"] or "미분류"] += 1
            key = page_key(webrow, horse)
            if key is not None:
                web_by_key[key].append(webrow)

    exact_one_to_one = []
    ambiguous_keys = []
    unmatched_page_rows = []
    for key, website_rows in web_by_key.items():
        candidates = api_by_key.get(key, [])
        if len(candidates) == 1 and len(website_rows) == 1:
            exact_one_to_one.append((key, candidates[0], website_rows[0]))
        elif len(candidates) == 0:
            unmatched_page_rows.extend(website_rows)
        else:
            ambiguous_keys.append({
                "horse_id": key[0], "date": key[1],
                "website_rows": len(website_rows), "api_rows": len(candidates),
            })

    matched_api_row_ids = {int(api["daily_training_api_row_id"]) for _, api, _ in exact_one_to_one}
    matched_by_api_id = {
        int(api["daily_training_api_row_id"]): web
        for _, api, web in exact_one_to_one
    }
    known_jockey_rows = [row for row in api_rows if row["prGubun_raw"] == "기수"]
    known_jockey_matched = [row for row in known_jockey_rows if int(row["daily_training_api_row_id"]) in matched_by_api_id]
    known_jockey_marker_counts: Counter[str] = Counter()
    known_jockey_marker_examples: list[dict[str, Any]] = []
    conflict_counts: Counter[str] = Counter()
    conflict_examples: list[dict[str, Any]] = []
    page_type_match_counts: Counter[str] = Counter()
    page_type_conflict_counts: Counter[str] = Counter()

    for api in known_jockey_rows:
        row_id = int(api["daily_training_api_row_id"])
        web = matched_by_api_id.get(row_id)
        if web is None:
            known_jockey_marker_counts["no_unique_exact_same_event_page_match"] += 1
            continue
        page_type = web["page_type"]
        raw_label = web["raw_label"]
        if page_type == "기수":
            known_jockey_marker_counts["explicit_unmarked_jockey_name"] += 1
        elif page_type == "기수트랙라이더":
            known_jockey_marker_counts["page_marks_track_rider_(트)"] += 1
            known_jockey_marker_examples.append({
                "daily_training_api_row_id": row_id,
                "horse_id": str(api["horse_id"]),
                "training_date": str(api["training_date"]),
                "api_type": "기수",
                "website_type": page_type,
                "review_result": "same_event_type_conflict",
            })
        elif page_type is None:
            known_jockey_marker_counts["same_event_page_role_unresolved"] += 1
        else:
            known_jockey_marker_counts["other_explicit_page_type"] += 1

    for _, api, web in exact_one_to_one:
        api_type = KNOWN_API_TYPES.get(api["prGubun_raw"])
        web_type = web["page_type"]
        if api_type is None or web_type is None:
            continue
        if api_type == web_type:
            page_type_match_counts[api_type] += 1
        else:
            conflict_counts[f"{api_type} vs {web_type}"] += 1
            page_type_conflict_counts[api_type] += 1
            conflict_examples.append({
                "daily_training_api_row_id": int(api["daily_training_api_row_id"]),
                "horse_id": str(api["horse_id"]),
                "training_date": str(api["training_date"]),
                "prGubun_raw": api["prGubun_raw"],
                "api_type": api_type,
                "website_type": web_type,
                "effective_type_if_reviewed": "미분류",
                "review_result": "same_event_api_website_type_conflict",
            })

    known_jockey_no_match = sum(
        1 for row in known_jockey_rows
        if int(row["daily_training_api_row_id"]) not in matched_api_row_ids
    )
    matched_categories = Counter(str(api["prGubun_raw"]) for _, api, _ in exact_one_to_one)
    site_rows_no_api_candidates = len(unmatched_page_rows)

    return {
        "method": "independent standard-library HTMLParser; exact horse ID + date + start minute + end minute + API duration seconds; no page fetches",
        "page_scope": {
            "window_start_inclusive": RECENT_WINDOW_START,
            "window_end_inclusive": RECENT_WINDOW_END,
            "page_count": len(pages),
            "parsed_html_training_row_count": html_row_count,
            "api_candidate_rows_with_valid_times": len(api_rows),
        },
        "official_legend_counts": dict(sorted(legend_counts.items())),
        "parsed_website_rows_by_marker": json_ready_counts(page_marker_counts),
        "parsed_website_rows_by_page_type": json_ready_counts(page_row_types, TYPE_ORDER),
        "exact_event_matching": {
            "unique_one_to_one_event_count": len(exact_one_to_one),
            "api_categories_in_unique_matches": json_ready_counts(matched_categories),
            "ambiguous_exact_event_key_count": len(ambiguous_keys),
            "ambiguous_exact_event_keys": ambiguous_keys,
            "website_rows_without_api_exact_event_candidate": site_rows_no_api_candidates,
        },
        "api_known_jockey_marker_review": {
            "candidate_api_jockey_rows_in_32_horses_and_window": len(known_jockey_rows),
            "unique_exact_matches": len(known_jockey_matched),
            "without_unique_exact_match": known_jockey_no_match,
            "page_label_review_counts": json_ready_counts(known_jockey_marker_counts),
            "page_marks_track_rider_but_api_says_jockey_count": known_jockey_marker_counts.get("page_marks_track_rider_(트)", 0),
            "track_rider_conflict_examples": known_jockey_marker_examples,
        },
        "all_known_api_type_conflicts_in_unique_matches": {
            "conflict_count": sum(conflict_counts.values()),
            "counts_by_api_vs_website_type": json_ready_counts(conflict_counts),
            "api_categories_with_conflict": json_ready_counts(page_type_conflict_counts),
            "examples": conflict_examples,
        },
        "interpretation_limit": "The 32 pages were used only for independent audit. Their additional parsed rows were not inserted into the observation table or used to supplement type counts.",
    }


def main() -> int:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument(
        "--output-name",
        default="rider_type_audit.json",
        help="new JSON basename inside this audit directory; existing files are never overwritten",
    )
    args = argument_parser.parse_args()
    output_name = str(args.output_name)
    if Path(output_name).name != output_name or not output_name.endswith(".json"):
        raise ValueError("--output-name must be a simple .json filename")
    output_path = OUTPUT_DIR / output_name
    if output_path.is_symlink() or output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing audit output: {output_path}")
    if output_path.resolve().parent != OUTPUT_DIR.resolve():
        raise ValueError("--output-name must stay inside the audit directory")

    before = db_fingerprint()
    pages, page_manifest = load_pages()
    conn = connect_read_only()
    try:
        source_schema_tables = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?)",
                ("daily_training_api_rows", "training_rider_website_observations"),
            )
        }
        if source_schema_tables != {"daily_training_api_rows", "training_rider_website_observations"}:
            raise RuntimeError("Required rider type source tables are missing")
        expected_source_sha_by_path = {
            str(page["source_path"]): str(page["source_sha256"]) for page in pages
        }
        type_counts = read_type_counts(conn, expected_source_sha_by_path)
        page_review = review_stored_pages(conn, pages, page_manifest["legend_counts"])
    finally:
        conn.close()
    after = db_fingerprint()
    if before != after:
        raise RuntimeError("SQLite database or WAL changed during read-only audit")

    result = {
        "audit_name": "jeju_daily_training_rider_type_independent_audit",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "database": {
            "path": str(DB_PATH),
            "open_mode": "mode=ro",
            "query_only": True,
            "sha256_before": before,
            "sha256_after": after,
            "unchanged_during_audit": before == after,
        },
        "scope_policy": {
            "all_stored_rows": "all 908,316 API18 horse-linked daily training rows, including after the race analysis cutoff",
            "analysis_through_2026_09_19": "training_date <= 2026-09-19, as the current race analysis cap",
            "2017_onward_analysis_scope": "2017-01-01 through 2026-09-19 inclusive",
            "2017_onward_all_stored": "2017-01-01 through the last stored API18 training date, including after-cap rows",
            "type_values": TYPE_ORDER,
            "known_api_value_policy": "Keep the five exact non-dash prGubun_raw values as their own type.",
            "dash_supplement_policy": "Only the existing same-event training_rider_website_observations row may supplement API '-'. A plain person name means 기수 per the official legend; 관=주로조교, 조=조교사, 생=교육생, name(트)=기수트랙라이더. 외 or absent/unrecognized evidence stays 미분류.",
            "conflict_policy": "If direct API type and explicit same-event page type differ, effective type is 미분류 with api_website_type_conflict status.",
            "staff_reference_policy": "Never use current or other-date employee-name/ID role references to backfill API '-'.",
            "name_display_policy": "Expose a person name only for type 기수. For every other type, expose type/category only; 미분류 exposes neither a type assertion nor a person name.",
        },
        "stored_official_pages": page_manifest,
        "classification": type_counts,
        "independent_32_page_review": page_review,
        "limitations": [
            "The website observation table is the existing 1,259 exact-event set (1,236 named and 23 '외'); this audit does not add or backfill observations.",
            "The raw HTML pages show recent 2026-04-15 through 2026-09-28 training rows only; they provide no basis to extend website confirmation into older dates.",
            "The API event date is not a proven public timestamp. Type review does not certify when the page/API became public.",
        ],
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output_path),
        "database_sha256_unchanged": before == after,
        "rows_by_type": {
            key: value["rows_by_type"]
            for key, value in type_counts["type_counts_by_scope"].items()
        },
        "known_api_jockey_marker_review": page_review["api_known_jockey_marker_review"],
        "type_conflict_count": page_review["all_known_api_type_conflicts_in_unique_matches"]["conflict_count"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"audit failed: {error}", file=sys.stderr)
        raise SystemExit(1)
