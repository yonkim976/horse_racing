"""Independent, read-only checks for the 2026-10-17 section source load.

This verifier uses Python's standard-library HTMLParser and json modules. It
never fetches network data and opens the shared SQLite file with mode=ro plus
query_only. Source-only checks can run before the loader is applied; pass
--require-loaded after application to check raw provenance and guarded values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


JEJU = Path(__file__).resolve().parents[3]
REVIEW = JEJU / "research/20261018_oct17_sections_website_review"
OUT = Path(__file__).resolve().parent
DEFAULT_DB = JEJU / "data/jeju_native_core.sqlite3"
DATE = "2026-10-17"
DATE_API = "20261017"
MEET = 2
SECTION_FIELDS = {
    "S-1F": ("passrankS1f", "corner_7"),
    "1C": ("passrankG8f_1c", "corner_1"),
    "2C": ("passrankG6f_2c", "corner_2"),
    "3C": ("passrankG4f_3c", "corner_3"),
    "4C": ("passrankG3f_4c", "corner_4"),
    "G-1F": ("passrankG1f", "corner_8"),
}
GROUP_LABELS = {
    "S-1F": "S-1F:",
    "1C": "1코너:",
    "2C": "2코너:",
    "3C": "3코너:",
    "4C": "4코너:",
    "G-1F": "G-1F:",
}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


class PageParser(HTMLParser):
    """Small HTML table/link extractor with no third-party parser dependency."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict[str, Any]] = []
        self.stack: list[dict[str, Any]] = []
        self.links: list[dict[str, str]] = []
        self.link: dict[str, Any] | None = None
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "table":
            self.stack.append({"rows": [], "row": None, "cell": None})
        elif tag == "tr" and self.stack:
            self.stack[-1]["row"] = []
        elif tag in ("td", "th") and self.stack and self.stack[-1]["row"] is not None:
            self.stack[-1]["cell"] = []
        elif tag == "a":
            self.link = {"href": attr.get("href") or "", "text": []}
        elif tag in ("br", "p", "div", "li"):
            self._space()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self.stack and self.stack[-1]["cell"] is not None:
            self.stack[-1]["cell"].append(data)
        if self.link is not None:
            self.link["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self.stack and self.stack[-1]["cell"] is not None:
            table = self.stack[-1]
            table["row"].append(clean("".join(table["cell"])))
            table["cell"] = None
        elif tag == "tr" and self.stack and self.stack[-1]["row"] is not None:
            table = self.stack[-1]
            if table["row"]:
                table["rows"].append(table["row"])
            table["row"] = None
        elif tag == "table" and self.stack:
            self.tables.append(self.stack.pop())
        elif tag == "a" and self.link is not None:
            self.links.append({"href": self.link["href"], "text": clean("".join(self.link["text"]))})
            self.link = None
        elif tag in ("br", "p", "div", "li"):
            self._space()

    def _space(self) -> None:
        if self.stack and self.stack[-1]["cell"] is not None:
            self.stack[-1]["cell"].append(" ")
        if self.link is not None:
            self.link["text"].append(" ")
        self.text.append(" ")


def api_items(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = payload.get("response", {}).get("body", {})
    item = (body.get("items") or {}).get("item")
    if isinstance(item, dict):
        return [item]
    if isinstance(item, list) and all(isinstance(row, dict) for row in item):
        return item
    raise ValueError(f"Unexpected API items collection in {path}")


def expected_family(summary: dict, family: str) -> dict:
    matches = [item for item in summary["today"]["families"] if item["family"] == family]
    if len(matches) != 1:
        raise ValueError(f"Expected one {family} family in api_recheck_summary.json")
    return matches[0]


def normalize_group(value: Any) -> str:
    if value is None or value == 0:
        return ""
    text = str(value).strip()
    return "" if text in ("", "-", "0", "X") else text


def page_groups(parser: PageParser) -> dict[str, str]:
    groups = {key: "" for key in GROUP_LABELS}
    for table in parser.tables:
        joined = " ".join(" ".join(row) for row in table["rows"])
        if "통과순위" not in joined and not any(label in joined for label in GROUP_LABELS.values()):
            continue
        for row in table["rows"]:
            for key, label in GROUP_LABELS.items():
                for i, cell in enumerate(row):
                    if cell.startswith(label):
                        value = cell[len(label):].strip()
                        if not value and i + 1 < len(row):
                            next_cell = row[i + 1].strip()
                            if next_cell not in {"", "3F", "4F", "주로빠르기", "통과순위"} and not re.fullmatch(r"[①②③④⑤]", next_cell):
                                value = next_cell
                        groups[key] = value
        return groups
    raise ValueError("Official page has no passing-rank table")


def page_sections(parser: PageParser) -> tuple[list[str], list[str], list[str]]:
    for table in parser.tables:
        rows = table["rows"]
        by_label = {row[0]: row[1:] for row in rows if row}
        if {"펄롱타임", "통과거리", "통과타임"} <= by_label.keys():
            return (by_label["통과거리"], by_label["펄롱타임"], by_label["통과타임"])
    raise ValueError("Official page has no complete furlong/distance/cumulative table")


def page_runners(parser: PageParser) -> list[dict[str, Any]]:
    result_table = None
    for table in parser.tables:
        rows = table["rows"]
        if rows and all(name in rows[0] for name in ("순위", "마번", "마명")):
            result_table = rows
            break
    if result_table is None:
        raise ValueError("Official page has no runner result table")

    id_by_name: dict[str, list[str]] = {}
    for link in parser.links:
        match = re.search(r"goHorse\(['\"](\d+)['\"],\s*['\"]2['\"]\)", link["href"])
        if match:
            name = link["text"].removeprefix("★").strip()
            id_by_name.setdefault(name, []).append(match.group(1))

    out = []
    for row in result_table[1:]:
        if len(row) < 3 or not row[0].isdigit() or not row[1].isdigit():
            continue
        name = row[2].removeprefix("★").strip()
        ids = id_by_name.get(name, [])
        out.append({
            "finish_position": int(row[0]),
            "horse_number": int(row[1]),
            "horse_name": name,
            "horse_ids": ids,
            "finish_time_raw": row[10] if len(row) > 10 else None,
        })
    return out


def seconds(value: Any) -> float | None:
    if value is None or str(value).strip() in ("", "-", "0"):
        return None
    text = str(value).strip()
    if ":" in text:
        minutes, sec = text.split(":", 1)
        return int(minutes) * 60 + float(sec)
    return float(text)


def close_number(a: Any, b: Any) -> bool:
    x, y = seconds(a), seconds(b)
    return x is not None and y is not None and abs(x - y) < 1e-8


def run_source_checks() -> dict[str, Any]:
    summary = json.loads((REVIEW / "api_recheck_summary.json").read_text(encoding="utf-8"))
    website = json.loads((REVIEW / "website_page_evidence.json").read_text(encoding="utf-8"))
    api6_meta = expected_family(summary, "section_records")
    api303_meta = expected_family(summary, "corner_rank")
    api_sources = {}
    api_by_race: dict[str, dict[int, dict]] = {}
    for key, family, meta in (
        ("section_records", "section_records", api6_meta),
        ("corner_rank", "corner_rank", api303_meta),
    ):
        path = REVIEW / meta["raw_path"]
        raw = path.read_bytes()
        digest = sha256(raw)
        items = api_items(path)
        if digest != meta["sha256"]:
            raise AssertionError(f"{key} source SHA differs from recheck summary")
        if len(items) != 7 or len(items) != meta["row_count"]:
            raise AssertionError(f"{key} did not contain exactly seven API records")
        seen: set[int] = set()
        for item in items:
            if str(item.get("rcDate")) != DATE_API or item.get("meet") != "제주":
                raise AssertionError(f"Out-of-scope item in {key}: {item!r}")
            race_no = int(item["rcNo"])
            if race_no in seen:
                raise AssertionError(f"Duplicate race {race_no} in {key}")
            seen.add(race_no)
        if seen != set(range(1, 8)):
            raise AssertionError(f"{key} race numbers are incomplete: {sorted(seen)}")
        api_sources[key] = {
            "path": str(path.relative_to(JEJU)),
            "sha256_actual": digest,
            "sha256_expected": meta["sha256"],
            "records": len(items),
            "races": sorted(seen),
        }
        api_by_race[key] = {int(item["rcNo"]): item for item in items}

    pages_expected = {int(item["race_no"]): item for item in website["per_race_pages"]}
    races: list[dict[str, Any]] = []
    runner_match_count = 0
    interval_match_count = 0
    cumulative_match_count = 0
    api6_distance_match_count = 0
    api6_distance_mismatch_rows: list[dict[str, Any]] = []
    group_match_count = {"section_records": 0, "corner_rank": 0}
    nonempty_group_count = {"section_records": 0, "corner_rank": 0}
    section_point_count = 0

    for race_no in range(1, 8):
        meta = pages_expected[race_no]
        path = REVIEW / "raw" / f"{DATE_API}_{race_no:02d}.html"
        raw = path.read_bytes()
        digest = sha256(raw)
        if digest != meta["sha256"]:
            raise AssertionError(f"KRA R{race_no} page SHA differs from evidence record")
        charset_match = re.search(rb"charset\s*=\s*['\"]?([^;\s'\"]+)", raw[:4096], re.I)
        charset = charset_match.group(1).decode("ascii", errors="strict") if charset_match else "euc-kr"
        parser = PageParser()
        parser.feed(raw.decode(charset, errors="replace"))
        text = clean(" ".join(parser.text))
        if not re.search(r"2026\s*년\s*10\s*월\s*17\s*일", text):
            raise AssertionError(f"KRA page date does not match 2026-10-17 for R{race_no}")
        if not re.search(rf"제\s*{race_no}\s*경주\s*제주", text):
            raise AssertionError(f"KRA page identity does not match R{race_no}")
        runners = page_runners(parser)
        expected_runner_count = int(meta["website_runner_count"])
        if len(runners) != expected_runner_count:
            raise AssertionError(f"KRA R{race_no} runner count {len(runners)} != {expected_runner_count}")
        for runner in runners:
            if len(runner["horse_ids"]) != 1:
                raise AssertionError(f"KRA R{race_no} horse link is not unique: {runner}")
        runner_match_count += len(runners)

        website_dist, website_intervals, website_cumulative = page_sections(parser)
        if not (len(website_dist) == len(website_intervals) == len(website_cumulative)):
            raise AssertionError(f"KRA R{race_no} section vectors have different lengths")
        api6 = api_by_race["section_records"][race_no]
        api303 = api_by_race["corner_rank"][race_no]
        race_points = 0
        race_time_matches = 0
        race_cumulative_matches = 0
        race_distance_matches = 0
        for index, website_value in enumerate(website_dist, 1):
            api_distance = api6.get(f"dist_{index}f")
            api_interval = api6.get(f"time_{index}f")
            api_cumulative = api6.get(f"passtime_{index}f")
            if not website_value.isdigit():
                raise AssertionError(f"Unexpected official distance text R{race_no}: {website_value!r}")
            if int(api_distance or 0) > 0:
                race_points += 1
                section_point_count += 1
                if int(api_distance) == int(website_value):
                    race_distance_matches += 1
                    api6_distance_match_count += 1
                else:
                    api6_distance_mismatch_rows.append({
                        "race_number": race_no,
                        "race_distance_m": api6.get("rcDist"),
                        "furlong_index": index,
                        "api_field": f"dist_{index}f",
                        "api_raw": api_distance,
                        "website_raw": website_value,
                    })
                if close_number(api_interval, website_intervals[index - 1]):
                    race_time_matches += 1
                    interval_match_count += 1
                else:
                    raise AssertionError(f"API6 interval mismatch R{race_no} point {index}")
                if close_number(api_cumulative, website_cumulative[index - 1]):
                    race_cumulative_matches += 1
                    cumulative_match_count += 1
                else:
                    raise AssertionError(f"API6 cumulative mismatch R{race_no} point {index}")
            else:
                raise AssertionError(f"API6 missing distance for website point R{race_no} point {index}")

        website_group_map = page_groups(parser)
        race_group_checks: dict[str, Any] = {}
        for source, field_pos in (("section_records", 0), ("corner_rank", 1)):
            source_matches = 0
            source_nonempty = 0
            for label, fields in SECTION_FIELDS.items():
                field = fields[field_pos]
                api_value = normalize_group((api6 if source == "section_records" else api303).get(field))
                official_value = website_group_map[label]
                if api_value != official_value:
                    raise AssertionError(f"{source} group mismatch R{race_no} {label}: {api_value!r} != {official_value!r}")
                source_matches += 1
                if api_value:
                    source_nonempty += 1
            group_match_count[source] += source_matches
            nonempty_group_count[source] += source_nonempty
            race_group_checks[source] = {"points_compared": source_matches, "nonempty_points": source_nonempty}

        races.append({
            "race_number": race_no,
            "website_sha256_actual": digest,
            "website_sha256_expected": meta["sha256"],
            "website_runners": len(runners),
            "official_sections": len(website_dist),
            "api6_interval_points_match": race_time_matches,
            "api6_cumulative_points_match": race_cumulative_matches,
            "api6_distance_points_match": race_distance_matches,
            "official_distances_m": [int(v) for v in website_dist],
            "api6_distances_m": [int(api6[f"dist_{i}f"]) for i in range(1, len(website_dist) + 1)],
            "api6_race_distance_m": api6.get("rcDist"),
            "group_checks": race_group_checks,
        })

    if section_point_count != 39:
        raise AssertionError(f"Expected 39 section points, found {section_point_count}")
    if runner_match_count != 69:
        raise AssertionError(f"Expected 69 official runner rows, found {runner_match_count}")
    if api6_distance_mismatch_rows != [
        {"race_number": 5, "race_distance_m": 1110, "furlong_index": i,
         "api_field": f"dist_{i}f", "api_raw": api, "website_raw": str(web)}
        for i, (api, web) in enumerate(zip((100, 300, 500, 700, 900, 1100), (110, 310, 510, 710, 910, 1110)), 1)
    ]:
        raise AssertionError(f"Unexpected API6 distance disagreement set: {api6_distance_mismatch_rows}")
    if interval_match_count != 39 or cumulative_match_count != 39 or api6_distance_match_count != 33:
        raise AssertionError("API6 time/distance agreement counts differ from the source comparison")
    if group_match_count != {"section_records": 42, "corner_rank": 42}:
        raise AssertionError(f"Unexpected group field comparison counts: {group_match_count}")
    if nonempty_group_count != {"section_records": 29, "corner_rank": 29}:
        raise AssertionError(f"Unexpected nonempty group counts: {nonempty_group_count}")

    return {
        "source_checks_passed": True,
        "parser": "Python standard-library HTMLParser + json; no network calls",
        "database_access": "none during source-only phase",
        "api_sources": api_sources,
        "website_pages_checked": len(races),
        "official_runner_rows": runner_match_count,
        "api6_section_points": section_point_count,
        "api6_interval_time_matches": interval_match_count,
        "api6_cumulative_time_matches": cumulative_match_count,
        "api6_distance_matches": api6_distance_match_count,
        "api6_distance_disagreement_rows": api6_distance_mismatch_rows,
        "group_fields_compared": group_match_count,
        "nonempty_group_values_matching": nonempty_group_count,
        "races": races,
    }


def run_db_checks(db_path: Path, source_report: dict) -> dict[str, Any]:
    """Post-load checks; the shared SQLite file is opened strictly read-only."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    con.execute("PRAGMA busy_timeout=20000")
    try:
        receipt_path = JEJU / "research/20261018_oct17_section_load/application_manifest.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        plan = json.loads((JEJU / "research/20261018_oct17_section_load/plan.json").read_text(encoding="utf-8"))
        if receipt.get("status") != "applied_verified" or receipt.get("run_id") != plan.get("run_id"):
            raise AssertionError("Application manifest does not describe the expected completed load")
        if receipt.get("plan_sha256") != sha256((JEJU / "research/20261018_oct17_section_load/plan.json").read_bytes()):
            raise AssertionError("Application manifest plan SHA is stale")
        if receipt.get("database_sha256_after") == receipt.get("database_sha256_before"):
            raise AssertionError("Application manifest does not show a database update")
        if receipt.get("summary", {}).get("section_records", {}).get("inserted") != 7:
            raise AssertionError("Manifest does not report seven API6 inserts")
        if receipt.get("summary", {}).get("corner_rank", {}).get("inserted") != 7:
            raise AssertionError("Manifest does not report seven API303 inserts")

        rows = list(con.execute(
            """SELECT race_number, horse_number, horse_id, finish_position
               FROM race_result_rows
               WHERE race_date=? AND meet_code=?
               ORDER BY race_number, horse_number""",
            (DATE, MEET),
        ))
        if len(rows) != 69:
            raise AssertionError(f"Existing API4 result rows changed: expected 69, got {len(rows)}")
        db_by_race_number = {(r["race_number"], r["horse_number"]): (r["horse_id"], r["finish_position"]) for r in rows}

        # Reparse official pages to compare direct horse-link IDs, program numbers,
        # and finish positions against the existing API4 result rows.
        website_keyed: dict[tuple[int, int], tuple[str, int]] = {}
        for race_no in range(1, 8):
            p = REVIEW / "raw" / f"{DATE_API}_{race_no:02d}.html"
            parser = PageParser()
            parser.feed(p.read_bytes().decode("euc-kr", errors="replace"))
            for runner in page_runners(parser):
                website_keyed[(race_no, runner["horse_number"])] = (runner["horse_ids"][0], runner["finish_position"])
        if website_keyed != db_by_race_number:
            raise AssertionError("Official page direct horse IDs/number/finish do not match existing API4 rows")

        api6 = list(con.execute(
            """SELECT x.race_number,x.api_record_id,a.payload_json,a.payload_sha256,
                      a.source_artifact_id,a.record_index,s.sha256 AS page_sha256,
                      s.raw_relative_path
               FROM refresh_section_records x
               JOIN api_records a USING(api_record_id)
               JOIN source_artifacts s USING(source_artifact_id)
               WHERE x.race_date=? AND x.meet_code=? ORDER BY x.race_number""",
            (DATE, MEET),
        ))
        api303 = list(con.execute(
            """SELECT x.race_number,x.api_record_id,a.payload_json,a.payload_sha256,
                      a.source_artifact_id,a.record_index,s.sha256 AS page_sha256,
                      s.raw_relative_path
               FROM api303_corner_rank_rows x
               JOIN api_records a USING(api_record_id)
               JOIN source_artifacts s USING(source_artifact_id)
               WHERE x.race_date=? AND x.meet_code=? ORDER BY x.race_number""",
            (DATE, MEET),
        ))
        if len(api6) != 7 or len(api303) != 7:
            raise AssertionError(f"Loaded raw records must be API6=7/API303=7, got {len(api6)}/{len(api303)}")

        raw_sources = {
            "section_records": {r["race_number"]: r for r in api6},
            "corner_rank": {r["race_number"]: r for r in api303},
        }
        expected_api = {
            "section_records": api_items(REVIEW / expected_family(
                json.loads((REVIEW / "api_recheck_summary.json").read_text(encoding="utf-8")), "section_records"
            )["raw_path"]),
            "corner_rank": api_items(REVIEW / expected_family(
                json.loads((REVIEW / "api_recheck_summary.json").read_text(encoding="utf-8")), "corner_rank"
            )["raw_path"]),
        }
        expected_by_family = {
            fam: {int(item["rcNo"]): item for item in items} for fam, items in expected_api.items()
        }
        expected_index_by_family = {
            fam: {int(item["rcNo"]): index for index, item in enumerate(items, 1)}
            for fam, items in expected_api.items()
        }
        raw_checks = {}
        expected_raw_paths = {
            "section_records": str((REVIEW / expected_family(
                json.loads((REVIEW / "api_recheck_summary.json").read_text(encoding="utf-8")), "section_records"
            )["raw_path"]).relative_to(JEJU.parent)),
            "corner_rank": str((REVIEW / expected_family(
                json.loads((REVIEW / "api_recheck_summary.json").read_text(encoding="utf-8")), "corner_rank"
            )["raw_path"]).relative_to(JEJU.parent)),
        }
        for family, db_by_race in raw_sources.items():
            if set(db_by_race) != set(range(1, 8)):
                raise AssertionError(f"Loaded {family} race keys are incomplete: {sorted(db_by_race)}")
            source_digest = source_report["api_sources"][family]["sha256_actual"]
            verified = []
            artifact_ids: set[int] = set()
            for race_no, record in db_by_race.items():
                stored_payload = json.loads(record["payload_json"])
                if stored_payload != expected_by_family[family][race_no]:
                    raise AssertionError(f"Loaded {family} JSON item changed for R{race_no}")
                if sha256(record["payload_json"].encode("utf-8")) != record["payload_sha256"]:
                    raise AssertionError(f"Loaded {family} per-record payload SHA mismatch for R{race_no}")
                if record["page_sha256"] != source_digest:
                    raise AssertionError(f"Loaded {family} page SHA differs for R{race_no}")
                if record["record_index"] != expected_index_by_family[family][race_no]:
                    raise AssertionError(f"Loaded {family} item position mismatch for R{race_no}")
                if record["raw_relative_path"] != expected_raw_paths[family]:
                    raise AssertionError(f"Loaded {family} provenance path differs for R{race_no}")
                artifact_ids.add(record["source_artifact_id"])
                stored_path = Path(record["raw_relative_path"])
                if not stored_path.is_absolute():
                    stored_path = (JEJU.parent if stored_path.parts[:1] == ("jeju",) else JEJU) / stored_path
                if not stored_path.is_file() or sha256(stored_path.read_bytes()) != source_digest:
                    raise AssertionError(f"Loaded {family} raw provenance path is missing or has changed: {stored_path}")
                verified.append({
                    "race_number": race_no,
                    "api_record_id": record["api_record_id"],
                    "payload_sha256": record["payload_sha256"],
                    "page_sha256": record["page_sha256"],
                    "raw_relative_path": record["raw_relative_path"],
                    "record_index": record["record_index"],
                })
            if len(artifact_ids) != 1:
                raise AssertionError(f"Expected one page artifact for loaded {family}, found {len(artifact_ids)}")
            raw_checks[family] = {
                "rows": len(verified),
                "single_source_artifact_id": next(iter(artifact_ids)),
                "exact_json_and_page_provenance": verified,
            }

        # Guarded section point view verification is applied after its schema lands.
        point_view = con.execute(
            "SELECT type FROM sqlite_master WHERE name='api6_section_points_current'"
        ).fetchone()
        if not point_view:
            raise AssertionError("Expected guarded api6_section_points_current view is missing")
        point_columns = [r[1] for r in con.execute("PRAGMA table_info(api6_section_points_current)")]
        point_rows = list(con.execute(
            """SELECT * FROM api6_section_points_current
               WHERE race_date=? AND meet_code=? ORDER BY race_number,furlong_index""",
            (DATE, MEET),
        ))
        if len(point_rows) != 39:
            raise AssertionError(f"Expected 39 public API6 points, got {len(point_rows)}")

        # Check that the retained raw view still exposes the original API JSON,
        # then compare all 39 public points to both source records and the saved
        # official pages. Only the six reviewed R5 distances may differ from API6.
        raw_view_rows = list(con.execute(
            """SELECT race_number,payload_json,payload_sha256,source_artifact_id,
                      record_index,artifact_sha256,raw_relative_path
               FROM api6_section_records_current
               WHERE race_date=? AND meet_code=? ORDER BY race_number""",
            (DATE, MEET),
        ))
        if len(raw_view_rows) != 7:
            raise AssertionError(f"Expected seven rows in retained raw API6 view, got {len(raw_view_rows)}")
        for raw_row in raw_view_rows:
            race_no = raw_row["race_number"]
            base_row = raw_sources["section_records"][race_no]
            if (raw_row["payload_json"] != base_row["payload_json"]
                    or raw_row["payload_sha256"] != base_row["payload_sha256"]
                    or raw_row["source_artifact_id"] != base_row["source_artifact_id"]
                    or raw_row["record_index"] != base_row["record_index"]
                    or raw_row["artifact_sha256"] != base_row["page_sha256"]
                    or raw_row["raw_relative_path"] != base_row["raw_relative_path"]):
                raise AssertionError(f"Retained raw API6 view differs from API record provenance for R{race_no}")

        page_point_expected: dict[tuple[int, int], tuple[int, Any, Any]] = {}
        for race_no in range(1, 8):
            raw_page = (REVIEW / "raw" / f"{DATE_API}_{race_no:02d}.html").read_bytes()
            page_parser = PageParser()
            page_parser.feed(raw_page.decode("euc-kr", errors="replace"))
            website_dist, website_intervals, website_cumulative = page_sections(page_parser)
            api_item = expected_by_family["section_records"][race_no]
            if len(website_dist) != len(website_intervals) or len(website_dist) != len(website_cumulative):
                raise AssertionError(f"Official section vectors differ in length for R{race_no}")
            for index, distance_text in enumerate(website_dist, 1):
                page_point_expected[(race_no, index)] = (
                    int(distance_text), website_intervals[index - 1], website_cumulative[index - 1]
                )
                if not close_number(api_item.get(f"time_{index}f"), website_intervals[index - 1]):
                    raise AssertionError(f"Loaded API6 interval source mismatch for R{race_no} point {index}")
                if not close_number(api_item.get(f"passtime_{index}f"), website_cumulative[index - 1]):
                    raise AssertionError(f"Loaded API6 cumulative source mismatch for R{race_no} point {index}")

        point_values = []
        for point in point_rows:
            race_no = point["race_number"]
            index = point["furlong_index"]
            api_item = expected_by_family["section_records"][race_no]
            expected_api_distance = api_item.get(f"dist_{index}f")
            expected_website_distance, expected_interval, expected_cumulative = page_point_expected[(race_no, index)]
            if point["api_distance_m_raw"] != expected_api_distance:
                raise AssertionError(f"Public raw distance changed for R{race_no} point {index}")
            if point["race_distance_m_raw"] != api_item.get("rcDist"):
                raise AssertionError(f"Public raw race distance changed for R{race_no} point {index}")
            expected_status = "website_corrected" if race_no == 5 else "api_positive_unreviewed"
            expected_effective = expected_website_distance if race_no == 5 else expected_api_distance
            if point["distance_status"] != expected_status or point["distance_m"] != expected_effective:
                raise AssertionError(f"Unexpected effective distance/status for R{race_no} point {index}")
            if point["distance_m"] != expected_website_distance:
                raise AssertionError(f"Public effective distance differs from homepage for R{race_no} point {index}")
            if not close_number(point["interval_seconds"], expected_interval):
                raise AssertionError(f"Public interval time differs from homepage for R{race_no} point {index}")
            if not close_number(point["cumulative_seconds"], expected_cumulative):
                raise AssertionError(f"Public cumulative time differs from homepage for R{race_no} point {index}")
            point_values.append({
                "race_number": race_no,
                "furlong_index": index,
                "api_distance_m_raw": point["api_distance_m_raw"],
                "distance_m": point["distance_m"],
                "distance_status": point["distance_status"],
                "interval_seconds": point["interval_seconds"],
                "cumulative_seconds": point["cumulative_seconds"],
            })

        reviews = list(con.execute(
            """SELECT * FROM api6_section_distance_reviews
               WHERE race_date=? AND meet_code=? AND race_number=? ORDER BY furlong_index""",
            (DATE, MEET, 5),
        ))
        if len(reviews) != 6 or con.execute("SELECT count(*) FROM api6_section_distance_reviews").fetchone()[0] != 6:
            raise AssertionError("Expected exactly six persisted R5 distance reviews")
        race5_record = raw_sources["section_records"][5]
        expected_distances = [110, 310, 510, 710, 910, 1110]
        for index, review in enumerate(reviews, 1):
            expected_raw = [100, 300, 500, 700, 900, 1100][index - 1]
            if (review["api_record_id"] != race5_record["api_record_id"]
                    or review["furlong_index"] != index
                    or review["race_date"] != DATE or review["meet_code"] != MEET
                    or review["race_number"] != 5 or review["race_distance_m_at_review"] != 1110
                    or review["api_payload_sha256_at_review"] != race5_record["payload_sha256"]
                    or review["api_source_artifact_id_at_review"] != race5_record["source_artifact_id"]
                    or review["api_source_page_sha256_at_review"] != race5_record["page_sha256"]
                    or review["api_distance_m_at_review"] != expected_raw
                    or review["website_distance_m"] != expected_distances[index - 1]
                    or review["effective_distance_m"] != expected_distances[index - 1]
                    or review["review_status"] != "website_corrected"
                    or review["website_url"] != plan["review5"]["url"]
                    or review["checked_date_kst"] != "2026-10-18"
                    or review["website_relative_path"] != plan["review5"]["path"]
                    or review["website_sha256"] != plan["review5"]["sha256"]
                    or review["evidence_relative_path"] != "jeju/research/20261018_oct17_sections_website_review/root_api_website_comparison.json"):
                raise AssertionError(f"R5 review provenance or values differ at point {index}")
            evidence_path = JEJU / "research/20261018_oct17_sections_website_review/root_api_website_comparison.json"
            if review["evidence_sha256"] != sha256(evidence_path.read_bytes()):
                raise AssertionError(f"R5 comparison evidence SHA differs at point {index}")

        return {
            "database_checks_passed": True,
            "db_path": str(db_path),
            "db_open_mode": "mode=ro/query_only",
            "existing_api4_rows": len(rows),
            "official_id_number_finish_matches": 69,
            "loaded_api6_rows": raw_checks["section_records"],
            "loaded_api303_rows": raw_checks["corner_rank"],
            "application_manifest": {
                "path": str(receipt_path.relative_to(JEJU)),
                "status": receipt["status"],
                "plan_sha256": receipt["plan_sha256"],
                "database_sha256_before": receipt["database_sha256_before"],
                "database_sha256_after": receipt["database_sha256_after"],
                "inserted_api6_rows": receipt["summary"]["section_records"]["inserted"],
                "inserted_api303_rows": receipt["summary"]["corner_rank"]["inserted"],
            },
            "guarded_view": {
                "name": "api6_section_points_current",
                "columns": point_columns,
                "target_rows": len(point_rows),
                "rows_checked_against_api_and_homepage": len(point_values),
                "r5_reviewed_distance_rows": [p for p in point_values if p["race_number"] == 5],
                "other_api_positive_unreviewed_rows": sum(p["distance_status"] == "api_positive_unreviewed" for p in point_values),
                "all_interval_and_cumulative_times_match_homepage": True,
            },
            "distance_reviews": {
                "rows": len(reviews),
                "source_bound_to_api_record_and_page": True,
                "website_sha256": plan["review5"]["sha256"],
                "evidence_sha256": sha256((JEJU / "research/20261018_oct17_sections_website_review/root_api_website_comparison.json").read_bytes()),
            },
        }
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--require-loaded", action="store_true")
    parser.add_argument("--output", type=Path, default=OUT / "independent_verification.json")
    args = parser.parse_args()

    source = run_source_checks()
    report: dict[str, Any] = {"passed": True, "source": source}
    if args.require_loaded:
        report["database"] = run_db_checks(args.db, source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "passed": report["passed"],
        "source_checks_passed": source["source_checks_passed"],
        "api6_raw_sha256": source["api_sources"]["section_records"]["sha256_actual"],
        "api303_raw_sha256": source["api_sources"]["corner_rank"]["sha256_actual"],
        "api6_points": source["api6_section_points"],
        "official_runner_rows": source["official_runner_rows"],
        "distance_disagreements": len(source["api6_distance_disagreement_rows"]),
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"verification failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
