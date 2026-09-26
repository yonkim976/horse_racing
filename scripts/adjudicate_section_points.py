#!/usr/bin/env python3
"""Build an evidence-backed section DB without altering either source database.

The archived KRA text report and the current KRA result page are distinct
versions of a record. Both are retained as evidence; a numeric disagreement is
never silently overwritten. Network access is only to KRA's public race pages.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from horse_racing.parsers.dacom11 import parse_dacom11_report
from horse_racing.parsers.race_day import parse_items
from horse_racing.parsers.race_section import RaceResultSectionItem, parse_section_values


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/research/section_point_db_20260925/section_points_verified.sqlite3"
OUTPUT = ROOT / "data/research/section_point_db_20260925/section_points_adjudicated.sqlite3"
OPERATIONAL = ROOT / "data/horse_racing.sqlite3"
JEJU_REPORTS = ROOT / "data/raw/kra_text/dacom11/meet=2"
KRA_PAGE = "https://race.kra.co.kr/raceScore/ScoretableDetailList.do"
TIME_RE = re.compile(r"^(?:(\d+):)?(\d{1,2})\.(\d)$")


def parse_time(value: str) -> int | None:
    match = TIME_RE.fullmatch(value.strip())
    if not match:
        return None
    return (int(match[1] or 0) * 60 + int(match[2])) * 1000 + int(match[3]) * 100


def official_url(meet: int, race_date: str, race_number: int) -> str:
    query = urllib.parse.urlencode(
        {"Act": "04", "Sub": "1", "meet": meet,
         "realRcDate": race_date.replace("-", ""), "realRcNo": race_number}
    )
    return f"{KRA_PAGE}?{query}"


def page_rows(html: bytes) -> tuple[dict[int, dict[str, int]], dict[int, dict[str, int]]]:
    """Return official Busan split and cumulative values by horse number."""
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.select("table")
    split_tables = [t for t in tables if "3F-G" in t.get_text(" ", strip=True)
                    and "구간별 통과순위" in t.get_text(" ", strip=True)
                    and "통과 누적기록" not in t.get_text(" ", strip=True)]
    cumulative_tables = [t for t in tables if "통과 누적기록" in t.get_text(" ", strip=True)]
    if len(split_tables) != 1 or len(cumulative_tables) != 1:
        raise ValueError("Official page lacks unique split/cumulative tables")

    def read(table: BeautifulSoup, *, cumulative: bool) -> dict[int, dict[str, int]]:
        result = {}
        for tr in table.select("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"], recursive=False)]
            if len(cells) < 5 or not cells[1].isdigit() or not cells[0].isdigit():
                continue
            values = [parsed for cell in cells[3:] if (parsed := parse_time(cell)) is not None]
            if len(values) < 3:
                continue
            result[int(cells[1])] = {
                "S1F": values[0], "G1F": values[-2], "FIN": values[-1],
                "G3F": values[-4] if cumulative and len(values) >= 4 else values[-3],
            }
        if not result:
            raise ValueError("Official page has no timed horse rows")
        return result

    return read(split_tables[0], cumulative=False), read(cumulative_tables[0], cumulative=True)


def load_jeju_evidence(con: sqlite3.Connection) -> tuple[list[tuple], Counter]:
    rows = con.execute(
        """SELECT id,race_date,race_number,horse_number,point_code,elapsed_time_ms
           FROM section_time WHERE meet_code=2 AND point_code IN ('G3F','G1F')
             AND representation='canonical'"""
    ).fetchall()
    by_key: dict[tuple, list[tuple[int, int]]] = defaultdict(list)
    for section_id, date, race_no, horse_no, code, ms in rows:
        by_key[(date, race_no, horse_no, code)].append((section_id, ms))
    evidence: dict[int, tuple] = {}
    stats: Counter = Counter()
    for path in sorted(JEJU_REPORTS.rglob("*.rpt")):
        raw = path.read_bytes()
        try:
            races = parse_dacom11_report(raw)
        except Exception:
            stats["report_parse_failed"] += 1
            continue
        digest = hashlib.sha256(raw).hexdigest()
        relative = str(path.relative_to(ROOT))
        stats["report_parsed"] += 1
        for race in races:
            for entry in race.entries:
                for code, value in (("G3F", entry.g3f_ms), ("G1F", entry.g1f_ms)):
                    if value is None:
                        continue
                    for section_id, stored in by_key.get(
                        (race.race_date.isoformat(), race.race_number, entry.horse_number, code), []
                    ):
                        if value == stored:
                            evidence[section_id] = (
                                section_id, "dacom11_report", relative, digest,
                                f"G-{code[1:]}" if code in ("G3F", "G1F") else code,
                                value, "closing",
                            )
                        else:
                            stats["report_value_mismatch"] += 1

    op = sqlite3.connect(f"file:{OPERATIONAL}?mode=ro", uri=True)
    try:
        paths = op.execute(
            """SELECT d.local_path FROM source_documents d JOIN ingestion_runs i
               ON i.id=d.ingestion_run_id WHERE i.data_type='race_result_sections'
                 AND d.local_path LIKE '%/meet_2/%' ORDER BY d.retrieved_at_ms,d.id"""
        ).fetchall()
    finally:
        op.close()
    for (relative,) in paths:
        path = ROOT / relative
        if not path.is_file():
            stats["api_document_missing"] += 1
            continue
        raw = path.read_bytes()
        try:
            items = parse_items(json.loads(raw), RaceResultSectionItem)
        except Exception:
            stats["api_document_parse_failed"] += 1
            continue
        digest = hashlib.sha256(raw).hexdigest()
        stats["api_document_parsed"] += 1
        for item in items:
            for value in parse_section_values(item, 2):
                if value.section_code not in ("G3F", "G1F") or value.elapsed_time_ms is None:
                    continue
                key = (item.race_date.isoformat(), item.race_number, item.horse_number, value.section_code)
                for section_id, stored in by_key.get(key, []):
                    if stored == value.elapsed_time_ms:
                        evidence[section_id] = (
                            section_id, "api4_3_json", relative, digest,
                            "jeG3fTime" if value.section_code == "G3F" else "jeG1fTime",
                            stored, "closing",
                        )
                    else:
                        stats["api_value_mismatch"] += 1
    stats["jeju_rows"] = len(rows)
    stats["jeju_evidence_exact"] = len(evidence)
    stats["jeju_report_exact"] = sum(v[1] == "dacom11_report" for v in evidence.values())
    stats["jeju_api_exact"] = sum(v[1] == "api4_3_json" for v in evidence.values())
    return list(evidence.values()), stats


def load_busan_evidence(con: sqlite3.Connection) -> tuple[list[tuple], list[tuple], Counter]:
    conflicts = con.execute(
        """SELECT c.id,c.race_date,c.race_number,c.horse_number,c.point_code,c.time_kind,
                  c.elapsed_time_ms,o.elapsed_time_ms,f.finish_time_ms
           FROM section_time c JOIN quality_issue q ON q.section_id=c.id
             AND q.issue_code='source_conflict'
           JOIN section_time o ON o.race_entry_id=c.race_entry_id
             AND o.point_code=c.point_code AND o.time_kind=c.time_kind
             AND o.representation='conflict'
           JOIN finish_time f ON f.race_entry_id=c.race_entry_id
           WHERE c.meet_code=3 AND c.source_name='busan_research'"""
    ).fetchall()
    pairs = con.execute(
        """SELECT c.id,g.id,c.race_date,c.race_number,c.horse_number,c.point_code,
                  c.elapsed_time_ms,g.elapsed_time_ms,f.finish_time_ms
           FROM section_time c JOIN quality_issue q ON q.section_id=c.id
             AND q.issue_code='pair_mismatch'
           JOIN section_time g ON g.race_entry_id=c.race_entry_id
             AND g.point_code=c.point_code AND g.time_kind='closing'
             AND g.representation='canonical'
           JOIN finish_time f ON f.race_entry_id=c.race_entry_id
           WHERE c.meet_code=3 AND c.time_kind='cumulative'
             AND c.representation='canonical'"""
    ).fetchall()
    keys = sorted({(date, race_no) for _, date, race_no, *_ in conflicts}
                  | {(date, race_no) for _, _, date, race_no, *_ in pairs})
    pages = {}
    stats: Counter = Counter()
    for date, race_no in keys:
        url = official_url(3, date, race_no)
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 SectionPointAudit/1.0"})
        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read()
        try:
            split, cumulative = page_rows(raw)
        except ValueError as exc:
            raise ValueError(f"{url}: {exc}") from exc
        pages[(date, race_no)] = (url, hashlib.sha256(raw).hexdigest(), split, cumulative)
        stats["busan_pages"] += 1
    checked_at = datetime.now(timezone.utc).isoformat()
    decisions = []
    for section_id, date, race_no, horse_no, code, kind, api, op, finish in conflicts:
        url, digest, split, cumulative = pages[(date, race_no)]
        official = (cumulative if kind == "cumulative" else split).get(horse_no, {}).get(code)
        website_finish = cumulative.get(horse_no, {}).get("FIN")
        status = (
            "current_kra_match" if official == api and website_finish == finish
            and 0 < api <= finish + 200 else "unresolved"
        )
        decisions.append((section_id, status, url, digest, official, api, op, checked_at))
        stats[f"source_conflict_{status}"] += 1
    pair_decisions = []
    for cumulative_id, closing_id, date, race_no, horse_no, code, cumulative_ms, closing_ms, finish in pairs:
        url, digest, split, cumulative = pages[(date, race_no)]
        website_cum = cumulative.get(horse_no, {}).get(code)
        website_close = split.get(horse_no, {}).get(code)
        website_finish = cumulative.get(horse_no, {}).get("FIN")
        status = "official_inconsistent" if (
            website_cum == cumulative_ms and website_close == closing_ms
            and website_finish == finish and abs(cumulative_ms + closing_ms - finish) > 200
        ) else "unresolved"
        pair_decisions.append((cumulative_id, closing_id, status, url, digest,
                               website_cum, website_close, website_finish, checked_at))
        stats[f"pair_{status}"] += 1
    return decisions, pair_decisions, stats


def create_adjudicated_view(con: sqlite3.Connection) -> None:
    con.executescript(
        """DROP VIEW common_point;
           CREATE VIEW common_point AS
           SELECT s.meet_code,s.race_date,s.race_number,s.distance_m,s.kra_horse_id,
                  s.horse_number,s.race_entry_id,s.point_code,s.time_kind,
                  s.meters_from_start,s.meters_before_finish,s.elapsed_time_ms,
                  p.position,p.position_raw,p.quality_status AS position_quality_status,
                  p.source_name AS position_source,s.position AS source_position,
                  s.source_name,s.source_field,s.classification
           FROM section_time s LEFT JOIN point_position p
             ON p.race_entry_id=s.race_entry_id AND p.point_code=s.point_code
           WHERE s.representation='canonical'
             AND NOT EXISTS (
               SELECT 1 FROM quality_issue q WHERE q.section_id=s.id
                 AND q.issue_code IN ('invalid_geometry','missing_segment_geometry',
                   'unlinked_runner','unresolved_time_kind','exceeds_finish',
                   'source_conflict','pair_mismatch','closing_subset_violation')
                 AND NOT (q.issue_code='source_conflict' AND EXISTS (
                   SELECT 1 FROM source_adjudication a WHERE a.section_id=s.id
                     AND a.status='current_kra_match')))
             AND ((s.point_code='S1F' AND s.time_kind='cumulative'
                   AND s.meters_from_start=200)
               OR (s.point_code IN ('G3F','G1F')
                   AND s.time_kind IN ('cumulative','closing')));"""
    )


def flag_closing_subset_violations(con: sqlite3.Connection) -> int:
    """A last-200m time cannot exceed the containing last-600m time."""
    con.execute(
        """INSERT OR IGNORE INTO quality_issue(section_id,issue_code,detail)
           SELECT g1.id,'closing_subset_violation','G1F closing exceeds G3F closing'
           FROM section_time g1 JOIN section_time g3
             ON g3.race_entry_id=g1.race_entry_id AND g3.point_code='G3F'
             AND g3.time_kind='closing' AND g3.representation='canonical'
           WHERE g1.meet_code=2 AND g1.point_code='G1F'
             AND g1.time_kind='closing' AND g1.representation='canonical'
             AND g1.elapsed_time_ms>g3.elapsed_time_ms+200"""
    )
    con.execute(
        """INSERT OR IGNORE INTO quality_issue(section_id,issue_code,detail)
           SELECT g3.id,'closing_subset_violation','G1F closing exceeds G3F closing'
           FROM section_time g1 JOIN section_time g3
             ON g3.race_entry_id=g1.race_entry_id AND g3.point_code='G3F'
             AND g3.time_kind='closing' AND g3.representation='canonical'
           WHERE g1.meet_code=2 AND g1.point_code='G1F'
             AND g1.time_kind='closing' AND g1.representation='canonical'
             AND g1.elapsed_time_ms>g3.elapsed_time_ms+200"""
    )
    return con.execute(
        "SELECT count(*) FROM quality_issue WHERE issue_code='closing_subset_violation'"
    ).fetchone()[0]


def main() -> None:
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite: {OUTPUT}")
    if not SOURCE.is_file() or not OPERATIONAL.is_file():
        raise FileNotFoundError("Source database unavailable")
    source = sqlite3.connect(f"file:{SOURCE}?mode=ro", uri=True)
    try:
        jeju, jeju_stats = load_jeju_evidence(source)
        busan, pairs, busan_stats = load_busan_evidence(source)
        if len(busan) != 36 or len(pairs) != 14:
            raise RuntimeError(f"Unexpected audit population: {len(busan)} conflicts, {len(pairs)} pairs")
        descriptor, staging_name = tempfile.mkstemp(prefix=".section_points_adjudicated_", suffix=".sqlite3", dir=OUTPUT.parent)
        os.close(descriptor)
        staging = Path(staging_name)
        try:
            target = sqlite3.connect(staging, timeout=120)
            try:
                source.backup(target)
                target.executescript(
                    """CREATE TABLE section_source_evidence (
                         section_id INTEGER PRIMARY KEY, source_type TEXT NOT NULL,
                         source_path TEXT NOT NULL, source_sha256 TEXT NOT NULL,
                         source_field TEXT NOT NULL, source_value_ms INTEGER NOT NULL,
                         asserted_time_kind TEXT NOT NULL);
                       CREATE TABLE source_adjudication (
                         section_id INTEGER PRIMARY KEY, status TEXT NOT NULL,
                         official_url TEXT NOT NULL, official_page_sha256 TEXT NOT NULL,
                         official_value_ms INTEGER, research_value_ms INTEGER NOT NULL,
                         operational_value_ms INTEGER NOT NULL, checked_at TEXT NOT NULL);
                       CREATE TABLE pair_adjudication (
                         cumulative_section_id INTEGER PRIMARY KEY,
                         closing_section_id INTEGER NOT NULL, status TEXT NOT NULL,
                         official_url TEXT NOT NULL, official_page_sha256 TEXT NOT NULL,
                         official_cumulative_ms INTEGER, official_closing_ms INTEGER,
                         official_finish_ms INTEGER, checked_at TEXT NOT NULL);"""
                )
                target.executemany("INSERT INTO section_source_evidence VALUES (?,?,?,?,?,?,?)", jeju)
                target.executemany("INSERT INTO source_adjudication VALUES (?,?,?,?,?,?,?,?)", busan)
                target.executemany("INSERT INTO pair_adjudication VALUES (?,?,?,?,?,?,?,?,?)", pairs)
                target.execute(
                    """UPDATE section_time SET time_kind='closing',
                         classification=(SELECT source_type || '_exact'
                                         FROM section_source_evidence e WHERE e.section_id=section_time.id)
                       WHERE id IN (SELECT section_id FROM section_source_evidence)"""
                )
                subset_violations = flag_closing_subset_violations(target)
                create_adjudicated_view(target)
                target.execute("ANALYZE")
                target.commit()
                if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise RuntimeError("Adjudicated DB quick_check failed")
                duplicate = target.execute(
                    """SELECT 1 FROM common_point GROUP BY meet_code,race_date,race_number,
                       kra_horse_id,point_code,time_kind HAVING count(*)>1 LIMIT 1"""
                ).fetchone()
                if duplicate:
                    raise RuntimeError("Adjudicated common_point has duplicate keys")
                print(json.dumps({
                    "jeju": dict(jeju_stats), "busan": dict(busan_stats),
                    "common_point": target.execute("SELECT count(*) FROM common_point").fetchone()[0],
                    "jeju_inferred_remaining": target.execute(
                        "SELECT count(*) FROM common_point WHERE meet_code=2 AND classification='pace_vs_finish'"
                    ).fetchone()[0],
                    "closing_subset_violations": subset_violations,
                }, ensure_ascii=False, indent=2))
            finally:
                target.close()
            os.link(staging, OUTPUT)
        finally:
            staging.unlink(missing_ok=True)
    finally:
        source.close()


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["finalize-existing"]:
        if not OUTPUT.is_file():
            raise FileNotFoundError(OUTPUT)
        with sqlite3.connect(OUTPUT) as existing:
            if existing.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='section_source_evidence'"
            ).fetchone()[0] != 1:
                raise RuntimeError("Not an adjudicated section database")
            print("closing_subset_violations", flag_closing_subset_violations(existing))
            create_adjudicated_view(existing)
            if existing.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("Database quick_check failed")
    elif not sys.argv[1:]:
        main()
    else:
        raise SystemExit("Usage: adjudicate_section_points.py [finalize-existing]")
