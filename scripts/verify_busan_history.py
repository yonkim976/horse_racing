"""Independently reconcile archived Busan sources and finalize research manifests."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from horse_racing.parsers.dacom11 import parse_dacom11_report
from build_busan_history import RACE_HEADING

BASE = Path("data/research/busan_history_20260915")
TEXT = Path("data/raw/kra_text")
MONTHLY = Path("data/raw/kra_api_monthly")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def make_entities(con: sqlite3.Connection) -> None:
    con.executescript("""
    CREATE TABLE IF NOT EXISTS horse_entity AS
      SELECT hr_no, min(race_date) first_race_date, max(race_date) last_race_date,
             count(DISTINCT horse_name) observed_names FROM entry GROUP BY hr_no;
    CREATE UNIQUE INDEX IF NOT EXISTS horse_entity_pk ON horse_entity(hr_no);
    CREATE TABLE IF NOT EXISTS actor_entity AS
      SELECT 'jockey' actor_type,jockey_no actor_no,min(race_date) first_race_date,
        max(race_date) last_race_date,count(DISTINCT jockey_name) observed_names
        FROM entry GROUP BY jockey_no
      UNION ALL SELECT 'trainer',trainer_no,min(race_date),max(race_date),
        count(DISTINCT trainer_name) FROM entry GROUP BY trainer_no
      UNION ALL SELECT 'owner',owner_no,min(race_date),max(race_date),
        count(DISTINCT owner_name) FROM entry GROUP BY owner_no;
    CREATE UNIQUE INDEX IF NOT EXISTS actor_entity_pk ON actor_entity(actor_type,actor_no);
    CREATE TABLE IF NOT EXISTS legacy_id_repair(
      old_entry_id INTEGER PRIMARY KEY, race_date TEXT, race_no INTEGER,
      hr_no TEXT, chul_no INTEGER, old_trainer_id TEXT, old_owner_id TEXT,
      official_trainer_no TEXT, official_owner_no TEXT,
      verification_status TEXT, official_source_path TEXT);
    CREATE TABLE IF NOT EXISTS dacom11_reconciliation(
      source_path TEXT NOT NULL,race_date TEXT NOT NULL,race_no INTEGER NOT NULL,
      chul_no INTEGER NOT NULL,horse_name TEXT,hr_no TEXT,link_status TEXT NOT NULL,
      text_finish_raw TEXT,text_time_ms INTEGER,text_weight_kg INTEGER,
      api_finish_raw TEXT,api_time_s REAL,api_weight_kg INTEGER,
      finish_disagrees INTEGER,time_disagrees INTEGER,weight_disagrees INTEGER,
      PRIMARY KEY(source_path,race_date,race_no,chul_no));
    CREATE TABLE IF NOT EXISTS dacom01_reconciliation(
      source_path TEXT NOT NULL,line_no INTEGER NOT NULL,race_date TEXT NOT NULL,
      race_no INTEGER NOT NULL,chul_no INTEGER NOT NULL,horse_name TEXT NOT NULL,
      official_hr_no TEXT,official_horse_name TEXT,link_status TEXT NOT NULL,
      PRIMARY KEY(source_path,line_no));
    CREATE TABLE IF NOT EXISTS medical_api_event(
      event_id TEXT PRIMARY KEY,event_date TEXT NOT NULL,hr_no TEXT NOT NULL,
      horse_name TEXT,part_raw TEXT,facility_raw TEXT,
      diagnosis_1_raw TEXT,diagnosis_2_raw TEXT,has_content INTEGER NOT NULL,
      source_meet_raw TEXT NOT NULL,source_path TEXT NOT NULL,source_row INTEGER NOT NULL,
      availability_status TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS medical_api_hr_date ON medical_api_event(hr_no,event_date);
    CREATE TABLE IF NOT EXISTS research_source_features(
      meet INTEGER NOT NULL,race_date TEXT NOT NULL,race_no INTEGER NOT NULL,
      hr_no TEXT NOT NULL,prior_api_medical_28d INTEGER NOT NULL,
      prior_text_medical_28d INTEGER NOT NULL,availability_status TEXT NOT NULL,
      PRIMARY KEY(meet,race_date,race_no,hr_no));
    CREATE TABLE IF NOT EXISTS source_availability(
      source_type TEXT NOT NULL,year INTEGER NOT NULL,status TEXT NOT NULL,
      first_valid_date TEXT,last_valid_date TEXT,source_rows INTEGER NOT NULL,
      note TEXT,PRIMARY KEY(source_type,year));
    CREATE TABLE IF NOT EXISTS trial_result_text(
      source_path TEXT NOT NULL,line_no INTEGER NOT NULL,trial_date TEXT NOT NULL,
      trial_no INTEGER NOT NULL,finish_raw TEXT NOT NULL,chul_no INTEGER NOT NULL,
      horse_name TEXT NOT NULL,hr_no TEXT,link_status TEXT NOT NULL,
      label_scope TEXT NOT NULL CHECK(label_scope='trial_only'),
      PRIMARY KEY(source_path,line_no));
    CREATE TABLE IF NOT EXISTS race_notice_text(
      source_path TEXT NOT NULL,line_no INTEGER NOT NULL,
      notice_type TEXT NOT NULL,race_date TEXT NOT NULL,race_no INTEGER NOT NULL,
      chul_no INTEGER NOT NULL,horse_name TEXT NOT NULL,detail_raw TEXT NOT NULL,
      hr_no TEXT,link_status TEXT NOT NULL,availability_status TEXT NOT NULL,
      PRIMARY KEY(source_path,line_no));
    """)
    con.commit()


def repair_legacy(con: sqlite3.Connection) -> Counter:
    old = sqlite3.connect("file:data/horse_racing.sqlite3?mode=ro", uri=True)
    stats = Counter()
    sql = """SELECT e.id,r.race_date_local,r.race_number,h.kra_horse_id,
       h.name_ko,e.horse_number,t.kra_trainer_id,o.kra_owner_id
       FROM race_entries e JOIN races r ON r.id=e.race_id
       JOIN horses h ON h.id=e.horse_id
       LEFT JOIN trainers t ON t.id=e.trainer_id
       LEFT JOIN owners o ON o.id=e.owner_id
       WHERE r.racecourse_id=3 AND r.race_date_local>='2015-01-01'
       AND r.race_date_local<'2025-01-01'
       AND (t.kra_trainer_id LIKE 'text:%' OR o.kra_owner_id LIKE 'text:%')"""
    for eid, day, no, hr, name, chul, tr, ow in old.execute(sql):
        key = con.execute("""SELECT hr_no,horse_name,chul_no,trainer_no,owner_no,
                           source_path FROM entry WHERE meet=3 AND race_date=?
                           AND race_no=? AND hr_no=?""",
                          (day, no, hr)).fetchone()
        status = "confirmed" if key and key[1] == name and key[2] == chul else (
            "conflict" if key else "unmatched")
        con.execute("INSERT OR REPLACE INTO legacy_id_repair VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (eid, day, no, hr, chul, tr, ow,
                     key[3] if status == "confirmed" else None,
                     key[4] if status == "confirmed" else None,
                     status, key[5] if key else None))
        stats[status] += 1
    old.close()
    con.commit()
    return stats


def compare_dacom11(con: sqlite3.Connection) -> Counter:
    stats = Counter()
    for path in sorted((TEXT / "dacom11" / "meet=3").glob("year=*/**/*.rpt")):
        try:
            parsed = parse_dacom11_report(path.read_bytes())
        except Exception:
            stats["parse_failed_files"] += 1
            continue
        stats["parsed_files"] += 1
        for race in parsed:
            if race.meet_name not in {"부경", "부산", "부산경남"}:
                stats["wrong_venue_races"] += 1
                continue
            day = race.race_date.isoformat()
            stats["text_races"] += 1
            for item in race.entries:
                official = con.execute("""SELECT e.hr_no,e.horse_name,e.chul_no,
                      x.finish_raw,x.race_time_s,e.horse_weight_kg
                      FROM entry e JOIN result x USING(meet,race_date,race_no,hr_no)
                      WHERE e.meet=3 AND e.race_date=? AND e.race_no=?
                      AND e.chul_no=?""",
                                       (day, race.race_number, item.horse_number)).fetchone()
                status = "confirmed" if official and official[1] == item.horse_name else (
                    "conflict" if official else "unmatched")
                finish_diff = int(status == "confirmed" and item.finish_position is not None
                                  and official[3].isdigit() and int(official[3]) < 90
                                  and item.finish_position != int(official[3]))
                time_diff = int(status == "confirmed" and item.finish_time_ms is not None
                                and official[4] is not None and official[4] > 0
                                and abs(item.finish_time_ms / 1000 - official[4]) > 0.11)
                weight_diff = int(status == "confirmed" and item.body_weight_kg is not None
                                  and official[5] is not None
                                  and item.body_weight_kg != official[5])
                con.execute("INSERT OR IGNORE INTO dacom11_reconciliation VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (str(path), day, race.race_number, item.horse_number,
                             item.horse_name, official[0] if status == "confirmed" else None,
                             status, item.finish_rank_raw, item.finish_time_ms,
                             item.body_weight_kg, official[3] if official else None,
                             official[4] if official else None,
                             official[5] if official else None,
                             finish_diff, time_diff, weight_diff))
                stats[status] += 1
                stats["finish_disagrees"] += finish_diff
                stats["time_disagrees"] += time_diff
                stats["weight_disagrees"] += weight_diff
    con.commit()
    return stats


def compare_dacom01_2006(con: sqlite3.Connection) -> Counter:
    stats = Counter()
    for path in sorted((TEXT / "dacom01" / "meet=3" / "year=2006").glob("**/*.rpt")):
        current = None
        in_table = False
        seen_row = False
        for line_no, line in enumerate(path.read_text(encoding="cp949", errors="replace").splitlines(), 1):
            heading = RACE_HEADING.search(line)
            if heading:
                year, month, day = map(int, heading.group(1, 2, 3))
                if year < 100:
                    year += 2000
                current = (f"{year:04d}-{month:02d}-{day:02d}",
                           int(heading.group(4) or heading.group(5)))
                in_table = False
                seen_row = False
            if "마번" in line and "조교사" in line:
                in_table = True
                continue
            if in_table and line.strip().startswith("----"):
                if seen_row:
                    in_table = False
                continue
            if in_table and current:
                match = re.match(r"^\s*(\d{1,2})\s+(\S+)\s+(.+)$", line)
                if not match:
                    continue
                chul, name = int(match[1]), match[2]
                official = con.execute("""SELECT hr_no,horse_name FROM entry
                     WHERE meet=3 AND race_date=? AND race_no=? AND chul_no=?""",
                                       (*current, chul)).fetchone()
                status = "confirmed" if official and official[1] == name else (
                    "conflict" if official else "unmatched")
                con.execute("INSERT OR REPLACE INTO dacom01_reconciliation VALUES(?,?,?,?,?,?,?,?,?)",
                            (str(path), line_no, *current, chul, name,
                             official[0] if official else None,
                             official[1] if official else None, status))
                stats[status] += 1
                seen_row = True
    con.commit()
    return stats


def load_trials(con: sqlite3.Connection) -> Counter:
    stats = Counter()
    heading = re.compile(
        r"제목\s*:\s*(\d{2,4})년\s*(\d{1,2})월\s*(\d{1,2})일.*?제\s*(\d+)경주")
    for path in sorted((TEXT / "dacom23" / "meet=3").glob("year=*/**/*.rpt")):
        current = None
        first_table = False
        seen = False
        for line_no, line in enumerate(path.read_text(encoding="cp949", errors="replace").splitlines(), 1):
            match = heading.search(line)
            if match:
                year, month, day, no = map(int, match.groups())
                if year < 100:
                    year += 2000
                current = (f"{year:04d}-{month:02d}-{day:02d}", no)
                first_table = False
                seen = False
            if "착순" in line and "마번" in line and "조교사" in line:
                first_table = True
                continue
            if first_table and line.strip().startswith("----"):
                if seen:
                    first_table = False
                continue
            if first_table and current:
                row = re.match(r"^\s*(\d{1,2})\s+(\d{1,2})\s+(\S+)\s+", line)
                if not row:
                    continue
                finish, chul, name = row.groups()
                con.execute("INSERT OR REPLACE INTO trial_result_text VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (str(path), line_no, *current, finish, int(chul), name,
                             None, "unmatched", "trial_only"))
                seen = True
                stats["rows"] += 1
        stats["files"] += 1
    con.commit()
    return stats


def load_race_notices(con: sqlite3.Connection) -> Counter:
    stats = Counter()
    event_line = re.compile(
        r"^\s*(20\d\d)/(\d\d)/(\d\d)\s+(\d+)R\s+(\d+)\s+(\S+)\s+(.+?)\s*$")
    for path in sorted((TEXT / "dacom13" / "meet=3").glob("year=*/**/*.rpt")):
        notice_type = None
        for line_no, line in enumerate(path.read_text(encoding="cp949", errors="replace").splitlines(), 1):
            if "■" in line and ("마필취소" in line or "말취소" in line):
                notice_type = "horse_cancel"
            elif "■" in line and "기수변경" in line:
                notice_type = "jockey_change"
            elif "■" in line:
                notice_type = None
            match = event_line.match(line)
            if not match or notice_type is None:
                continue
            year, month, day, race_no, chul_no, name, detail = match.groups()
            race_date = f"{year}-{month}-{day}"
            official = con.execute("""SELECT hr_no,horse_name FROM entry
                WHERE meet=3 AND race_date=? AND race_no=? AND chul_no=?""",
                                   (race_date, int(race_no), int(chul_no))).fetchone()
            status = "confirmed" if official and official[1] == name else (
                "conflict" if official else "unmatched")
            con.execute("INSERT OR REPLACE INTO race_notice_text VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (str(path), line_no, notice_type, race_date, int(race_no),
                         int(chul_no), name, detail,
                         official[0] if status == "confirmed" else None,
                         status, "retrospective_only"))
            stats[(notice_type, status)] += 1
    con.commit()
    return stats


def load_medical_api(con: sqlite3.Connection, base: Path) -> Counter:
    stats = Counter()
    for path in sorted((base / "raw_medical").glob("*/page_*.json")):
        body = json.loads(path.read_bytes())["response"]["body"]
        wrapped = body.get("items") or {}
        rows = wrapped.get("item") or []
        if isinstance(rows, dict):
            rows = [rows]
        stats[(path.parent.name, "pages")] += 1
        stats[(path.parent.name, "rows")] += len(rows)
        for i, row in enumerate(rows):
            day = str(row["clinicDate"])
            if day[:4] != path.parent.name or row.get("meet") not in {"영남", "부산경남"}:
                raise ValueError(f"Medical scope mismatch: {path}:{i}")
            hr = str(row.get("hrNo") or "").strip()
            if not hr:
                raise ValueError(f"Medical ID missing: {path}:{i}")
            illness = (str(row.get("illName1") or "").strip(),
                       str(row.get("illName2") or "").strip())
            has_content = int(any(x not in {"", "-"} for x in illness))
            con.execute("INSERT OR REPLACE INTO medical_api_event VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (f"{path}:{i}", f"{day[:4]}-{day[4:6]}-{day[6:8]}", hr,
                         row.get("hrName"), str(row.get("part") or ""),
                         row.get("hospiName"), *illness, has_content,
                         row["meet"], str(path), i, "availability_unverified"))
            stats[(path.parent.name, "with_content")] += has_content
    con.execute("""INSERT OR REPLACE INTO research_source_features
      SELECT e.meet,e.race_date,e.race_no,e.hr_no,
        (SELECT count(*) FROM medical_api_event m WHERE m.hr_no=e.hr_no
         AND m.has_content=1 AND m.event_date<e.race_date
         AND m.event_date>=date(e.race_date,'-28 days')),
        e.prior_confirmed_medical_28d,'retrospective_only'
      FROM research_entry e""")
    con.commit()
    return stats


def coverage_extra(con: sqlite3.Connection, base: Path) -> None:
    rows = con.execute("""SELECT source_type,substr(event_date,1,4),min(event_date),
        max(event_date),count(*),count(DISTINCT hr_no) FROM training_event
        GROUP BY 1,2 ORDER BY 1,2""").fetchall()
    rows += con.execute("""SELECT 'medical_text',substr(event_date,1,4),min(event_date),
        max(event_date),count(*),count(DISTINCT hr_no) FROM medical_event
        GROUP BY 1,2 ORDER BY 1,2""").fetchall()
    rows += con.execute("""SELECT 'race_day_weight',substr(race_date,1,4),min(race_date),
        max(race_date),count(*),count(DISTINCT hr_no) FROM race_day_weight
        GROUP BY 1,2 ORDER BY 1,2""").fetchall()
    rows += con.execute("""SELECT 'medical_api',substr(event_date,1,4),min(event_date),
        max(event_date),count(*),count(DISTINCT hr_no) FROM medical_api_event
        GROUP BY 1,2 ORDER BY 1,2""").fetchall()
    with (base / "event_coverage.csv").open("w", newline="", encoding="utf-8") as stream:
        out = csv.writer(stream)
        out.writerow(["source", "year", "first_valid_date", "last_valid_date",
                      "rows", "linked_horses"])
        out.writerows(rows)


def year_quality(con: sqlite3.Connection, base: Path) -> None:
    pages = {}
    for line in (base / "request_ledger.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        pages[(str(event["scope"]["rc_year"]), event["page"])] = event["response_rows"]
    with (base / "year_quality.csv").open("w", newline="", encoding="utf-8") as stream:
        out = csv.writer(stream)
        out.writerow(["year", "race_keys", "entry_keys", "official_source_rows",
                      "missing_hr_no", "missing_jk_no", "missing_tr_no",
                      "missing_ow_no", "duplicate_chul_no", "void_or_unresulted_rows",
                      "scratched_rows", "dnf_rows", "disqualified_rows",
                      "weight_kg_positive", "weight_text_confirmed", "text_heading_dacom01",
                      "text_heading_dacom12", "text_heading_dacom71"])
        for (year,) in con.execute("SELECT DISTINCT substr(race_date,1,4) FROM race ORDER BY 1"):
            races = con.execute("SELECT count(*) FROM race WHERE race_date LIKE ?",
                                (year + "%",)).fetchone()[0]
            entries = con.execute("SELECT count(*) FROM entry WHERE race_date LIKE ?",
                                  (year + "%",)).fetchone()[0]
            missing = con.execute("""SELECT sum(hr_no=''),sum(jockey_no=''),
                 sum(trainer_no=''),sum(owner_no=''),sum(horse_weight_kg>0)
                 FROM entry WHERE race_date LIKE ?""", (year + "%",)).fetchone()
            dup = con.execute("""SELECT count(*) FROM
               (SELECT race_date,race_no,chul_no,count(*) n FROM entry
                WHERE race_date LIKE ? GROUP BY 1,2,3 HAVING n>1)""",
                              (year + "%",)).fetchone()[0]
            statuses = dict(con.execute("""SELECT result_status,count(*) FROM result
                WHERE race_date LIKE ? GROUP BY 1""", (year + "%",)))
            weight = con.execute("""SELECT count(*) FROM race_day_weight
                WHERE race_date LIKE ? AND link_status='confirmed'""",
                                 (year + "%",)).fetchone()[0]
            headings = [con.execute("""SELECT count(DISTINCT race_date||':'||race_no)
                 FROM text_race_heading WHERE source_type=? AND race_date LIKE ?""",
                                    (source, year + "%")).fetchone()[0]
                        for source in ("dacom01", "dacom12", "dacom71")]
            source_rows = sum(n for (y, _page), n in pages.items() if y == year)
            out.writerow([year, races, entries, source_rows, *missing[:4], dup,
                          statuses.get("void", 0) + statuses.get("void_or_unresulted", 0),
                          statuses.get("scratched", 0), statuses.get("did_not_finish", 0),
                          statuses.get("disqualified", 0), missing[4], weight, *headings])


def race_regimes(con: sqlite3.Connection, base: Path) -> None:
    with (base / "race_regime_year.csv").open("w", newline="", encoding="utf-8") as stream:
        out = csv.writer(stream)
        out.writerow(["year", "races", "distance_counts_json", "burden_counts_json",
                      "class_counts_json", "track_counts_json", "handicap_races",
                      "rating_era"])
        for (year,) in con.execute("SELECT DISTINCT substr(race_date,1,4) FROM race ORDER BY 1"):
            rows = con.execute("""SELECT distance_m,burden_type,race_class,track_raw
                                 FROM race WHERE race_date LIKE ?""", (year + "%",))
            distances, burdens, classes, tracks = (Counter() for _ in range(4))
            for dist, burden, klass, track in rows:
                distances[str(dist)] += 1
                burdens[str(burden)] += 1
                classes[str(klass)] += 1
                tracks[str(track)] += 1
            out.writerow([year, sum(distances.values()),
                          json.dumps(distances, ensure_ascii=False, sort_keys=True),
                          json.dumps(burdens, ensure_ascii=False, sort_keys=True),
                          json.dumps(classes, ensure_ascii=False, sort_keys=True),
                          json.dumps(tracks, ensure_ascii=False, sort_keys=True),
                          sum(n for name, n in burdens.items() if "핸디캡" in name),
                          "pre_rating_transition" if int(year) < 2015
                          else "rating_transition_or_later"])


def source_link_coverage(con: sqlite3.Connection, base: Path) -> None:
    with (base / "source_link_coverage.csv").open("w", newline="", encoding="utf-8") as stream:
        out = csv.writer(stream)
        out.writerow(["year", "research_entries", "prior_training_28d_entries",
                      "prior_start_training_28d_entries",
                      "prior_confirmed_text_medical_28d_entries",
                      "prior_contentful_api_medical_28d_entries",
                      "body_weight_positive_entries", "medical_text_events",
                      "medical_text_confirmed", "medical_text_ambiguous",
                      "medical_text_unmatched"])
        for (year,) in con.execute("SELECT DISTINCT substr(race_date,1,4) FROM race ORDER BY 1"):
            e = con.execute("""SELECT count(*),sum(prior_training_28d>0),
              sum(prior_start_training_28d>0),
              sum(prior_confirmed_medical_28d>0)
              FROM research_entry WHERE race_date LIKE ?""", (year + "%",)).fetchone()
            api = con.execute("""SELECT sum(prior_api_medical_28d>0)
              FROM research_source_features WHERE race_date LIKE ?""",
                              (year + "%",)).fetchone()[0]
            weight = con.execute("""SELECT sum(horse_weight_kg>0) FROM entry
              WHERE race_date LIKE ?""", (year + "%",)).fetchone()[0]
            med = dict(con.execute("""SELECT link_status,count(*) FROM medical_event
              WHERE event_date LIKE ? GROUP BY 1""", (year + "%",)))
            out.writerow([year, *(x or 0 for x in e), api or 0, weight or 0,
                          sum(med.values()), med.get("confirmed", 0),
                          med.get("ambiguous", 0), med.get("unmatched", 0)])


def source_availability(con: sqlite3.Connection) -> None:
    specs = {
        "horse_training": ("training_event", "event_date", "source_type='horse_training'", 2004),
        "start_training": ("training_event", "event_date", "source_type='start_training'", 2009),
        "medical_text": ("medical_event", "event_date", "1=1", 2005),
        "medical_api": ("medical_api_event", "event_date", "1=1", 2019),
        "race_day_weight_text": ("race_day_weight", "race_date", "1=1", 2005),
    }
    for source, (table, date_col, where, observed_start) in specs.items():
        for year in range(2004, 2027):
            first, last, rows = con.execute(
                f"SELECT min({date_col}),max({date_col}),count(*) FROM {table} "
                f"WHERE {where} AND {date_col} LIKE ?", (f"{year}%",)).fetchone()
            if rows:
                status = "observed_availability_unverified"
            elif year < observed_start:
                status = "source_unavailable"
            else:
                status = "zero_response_unverified"
            note = "event date is not proof of historical publication time"
            con.execute("INSERT OR REPLACE INTO source_availability VALUES(?,?,?,?,?,?,?)",
                        (source, year, status, first, last, rows, note))
    con.commit()


def export_conflicts(con: sqlite3.Connection, base: Path) -> None:
    specs = {
        "unresolved_legacy_ids.csv": (
            "SELECT old_entry_id,race_date,race_no,hr_no,chul_no,old_trainer_id,"
            "old_owner_id,verification_status,official_source_path "
            "FROM legacy_id_repair WHERE verification_status!='confirmed'",
            ["old_entry_id", "race_date", "race_no", "hr_no", "chul_no",
             "old_trainer_id", "old_owner_id", "verification_status",
             "official_source_path"]),
        "dacom11_conflicts.csv": (
            "SELECT source_path,race_date,race_no,chul_no,horse_name,"
            "link_status,finish_disagrees,time_disagrees,weight_disagrees "
            "FROM dacom11_reconciliation WHERE link_status!='confirmed' "
            "OR finish_disagrees=1 OR time_disagrees=1 OR weight_disagrees=1",
            ["source_path", "race_date", "race_no", "chul_no", "horse_name",
             "link_status", "finish_disagrees", "time_disagrees", "weight_disagrees"]),
    }
    for name, (query, columns) in specs.items():
        with (base / name).open("w", newline="", encoding="utf-8") as stream:
            out = csv.writer(stream)
            out.writerow(columns)
            out.writerows(con.execute(query))


def validate_monthly_pages(con: sqlite3.Connection) -> dict:
    stored = {(source, month): n for source, month, n in con.execute("""
      SELECT source_type,replace(substr(event_date,1,7),'-',''),count(*)
      FROM training_event GROUP BY 1,2""")}
    checked = 0
    for source in ("horse_training", "start_training"):
        for folder in sorted((MONTHLY / source / "meet_3").glob("*")):
            if not folder.is_dir() or len(folder.name) != 6:
                continue
            pages = sorted(folder.glob("page_*.json"))
            if [p.stem for p in pages] != [f"page_{i:04d}" for i in range(1, len(pages) + 1)]:
                raise ValueError(f"Missing training page: {folder}")
            rows = 0
            totals = set()
            for path in pages:
                body = json.loads(path.read_bytes())["response"]["body"]
                value = (body.get("items") or {}).get("item") or []
                batch = [value] if isinstance(value, dict) else value
                rows += len(batch)
                totals.add(int(body.get("totalCount") or 0))
            if len(totals) != 1 or rows != next(iter(totals)):
                raise ValueError(f"Training totalCount mismatch: {folder}")
            if rows != stored.get((source, folder.name), 0):
                raise ValueError(f"Training normalized row mismatch: {folder}")
            checked += 1
    return {"months_checked": checked, "page_or_row_mismatches": 0}


def trace_samples(con: sqlite3.Connection, base: Path) -> dict:
    samples = {}
    rng = random.Random(20260915)
    for table, query in {
        "entry": "SELECT source_path,source_row,hr_no,race_date,race_no FROM entry",
        "training_event": "SELECT source_path,source_row,hr_no,event_date,source_type FROM training_event",
        "medical_event": "SELECT source_path,line_no,horse_name,event_date,link_status FROM medical_event",
    }.items():
        total = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        offsets = sorted(rng.sample(range(total), 5))
        rows = [list(con.execute(query + " LIMIT 1 OFFSET ?", (offset,)).fetchone())
                for offset in offsets]
        for row in rows:
            path = Path(row[0])
            if table == "medical_event":
                line = path.read_text(encoding="cp949", errors="replace").splitlines()[row[1] - 1]
                if row[2] not in line:
                    raise ValueError(f"Medical trace mismatch: {path}:{row[1]}")
            else:
                body = json.loads(path.read_bytes())["response"]["body"]
                value = body["items"]["item"]
                source_rows = [value] if isinstance(value, dict) else value
                if str(source_rows[row[1]]["hrNo"]) != row[2]:
                    raise ValueError(f"JSON trace mismatch: {path}:{row[1]}")
        samples[table] = {"seed": 20260915, "offsets": offsets, "rows": rows}
    (base / "sample_trace.json").write_text(
        json.dumps(samples, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {table: len(value["rows"]) for table, value in samples.items()}


def hash_manifest(base: Path) -> None:
    sources = list((base / "raw").glob("*/page_*.json"))
    sources += list((base / "raw_medical").glob("*/page_*.json"))
    sources += list((MONTHLY / "horse_training" / "meet_3").glob("*/page_*.json"))
    sources += list((MONTHLY / "start_training" / "meet_3").glob("*/page_*.json"))
    sources += [MONTHLY / "horse_training" / "manifest.jsonl",
                MONTHLY / "start_training" / "manifest.jsonl"]
    for source in ("dacom01", "dacom12", "dacom13", "dacom71", "dacom72",
                   "dacom11", "dacom23"):
        sources += list((TEXT / source / "meet=3").glob("year=*/**/*.rpt"))
        sources += [TEXT / "_manifests" / source / "manifest.jsonl"]
    sources += [Path("scripts/collect_busan_history_results.py"),
                Path("scripts/collect_busan_medical_api.py"),
                Path("scripts/build_busan_history.py"), Path(__file__)]
    outputs = [p for p in base.iterdir() if p.is_file()
               and p.name not in {"sha256_manifest.csv"}
               and not p.name.endswith((".sqlite3-shm", ".sqlite3-wal"))]
    with (base / "sha256_manifest.csv").open("w", newline="", encoding="utf-8") as stream:
        out = csv.writer(stream)
        out.writerow(["role", "path", "sha256", "bytes"])
        for role, paths in (("source_or_code", sources), ("output", outputs)):
            for path in sorted(set(paths)):
                if not path.exists():
                    continue
                out.writerow([role, str(path), sha(path), path.stat().st_size])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BASE)
    args = parser.parse_args()
    base = args.output
    con = sqlite3.connect(base / "history.sqlite3")
    make_entities(con)
    repairs = repair_legacy(con)
    dacom = compare_dacom11(con)
    dacom01 = compare_dacom01_2006(con)
    trials = load_trials(con)
    notices = load_race_notices(con)
    medical_api = load_medical_api(con, base)
    coverage_extra(con, base)
    year_quality(con, base)
    race_regimes(con, base)
    source_link_coverage(con, base)
    source_availability(con)
    export_conflicts(con, base)
    monthly_pages = validate_monthly_pages(con)
    traced = trace_samples(con, base)
    audit = {"verified_at_utc": datetime.now(UTC).isoformat(),
             "legacy_id_repair": dict(repairs), "dacom11": dict(dacom),
             "dacom01_2006": dict(dacom01), "trial_text": dict(trials),
             "race_notices": {f"{kind}:{status}": value
                              for (kind, status), value in notices.items()},
             "medical_api": {"years": {year: {kind: medical_api[(year, kind)]
                                              for kind in ("pages", "rows", "with_content")}
                                        for year, kind in medical_api if kind == "rows"}},
             "monthly_page_validation": monthly_pages, "sample_trace_counts": traced,
             "database_integrity": con.execute("PRAGMA integrity_check").fetchone()[0],
             "2006_training_link_28d": con.execute("""SELECT count(*),
               sum(prior_training_28d>0) FROM research_entry
               WHERE race_date LIKE '2006%'""").fetchone()}
    (base / "verification.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    con.close()
    hash_manifest(base)
    print(json.dumps(audit, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
