"""Build an isolated, reproducible Seoul history database from archived official sources."""
# ruff: noqa: E501  # SQL and fixed-width source expressions are kept readable as source strings.

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from collect_seoul_backfill_results import items

BASE = Path("data/research/seoul_backfill_20260915_v1")
TEXT = Path("data/raw/kra_text")
MONTHLY = Path("data/raw/kra_api_monthly")
SECTION_KEYS = {
    "seS1fAccTime": "S1F",
    "seG1fAccTime": "G1F",
    "seG3fAccTime": "G3F",
    "se_1cAccTime": "1C",
    "se_2cAccTime": "2C",
    "se_3cAccTime": "3C",
    "se_4cAccTime": "4C",
}
ID_FIELDS = ("hrNo", "jkNo", "trNo", "owNo")
RACE_HEADING = re.compile(
    r"(?:경주일\s*:\s*|제목\s*:\s*).*?(20\d\d|\d\d)[.년\s]+(\d{1,2})[.월\s]+(\d{1,2}).*?(?:제\s*0*(\d+)\s*경주|(\d+)\s*경주)"
)
MEDICAL_LINE = re.compile(
    r"^\s*(20\d\d)[./-](\d\d)[./-](\d\d)\s+(\S+)\s+(\d{1,2})\s+(\S+)\s+(.+?)\s*$"
)
ENTRY_LINE = re.compile(r"^\s*(\d{1,2})\s+(\S+)\s+(.+?)\s*$")
WEIGHT_LINE = re.compile(r"^\s*(\d{1,2})\s+(\S+)\s+(\d{3})\s+([+-]\d+|0)\b")
API_WEIGHT = re.compile(r"^\s*(\d{3})(?:\(([+-]?\d*)\))?\s*$")


def j(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def official_id(value: object, width: int) -> str:
    if value is None or str(value).strip() in {"", "0", "None"}:
        return ""
    raw = str(value).strip()
    return raw.zfill(width) if raw.isdigit() else raw


def archive_rows(path: Path) -> list[dict]:
    payload = json.loads(path.read_bytes())
    return items(payload)


def make_db(con: sqlite3.Connection) -> None:
    con.executescript("""
    PRAGMA journal_mode=WAL;
    PRAGMA synchronous=NORMAL;
    CREATE TABLE race(meet INTEGER NOT NULL CHECK(meet=1), race_date TEXT NOT NULL,
      race_no INTEGER NOT NULL, race_type TEXT, race_class TEXT, distance_m INTEGER,
      burden_type TEXT, track_raw TEXT, weather_raw TEXT, label_scope TEXT NOT NULL,
      source_path TEXT NOT NULL, PRIMARY KEY(meet,race_date,race_no));
    CREATE TABLE entry(meet INTEGER NOT NULL, race_date TEXT NOT NULL, race_no INTEGER NOT NULL,
      hr_no TEXT NOT NULL, chul_no INTEGER, horse_name TEXT, jockey_no TEXT,
      trainer_no TEXT, owner_no TEXT, owner_no_raw_json TEXT, jockey_name TEXT,
      trainer_name TEXT, owner_name TEXT, horse_weight_raw TEXT, horse_weight_kg INTEGER,
      horse_weight_delta_kg INTEGER, burden_weight_kg REAL, source_path TEXT NOT NULL,
      source_row INTEGER NOT NULL, PRIMARY KEY(meet,race_date,race_no,hr_no),
      FOREIGN KEY(meet,race_date,race_no) REFERENCES race(meet,race_date,race_no));
    CREATE TABLE result(meet INTEGER NOT NULL, race_date TEXT NOT NULL, race_no INTEGER NOT NULL,
      hr_no TEXT NOT NULL, finish_raw TEXT, finish_order INTEGER, result_status TEXT,
      race_time_s REAL, win_odds REAL, place_odds REAL, diff_raw TEXT,
      source_path TEXT NOT NULL, source_row INTEGER NOT NULL,
      PRIMARY KEY(meet,race_date,race_no,hr_no));
    CREATE INDEX result_hr_date ON result(hr_no,race_date);
    CREATE TABLE section(meet INTEGER NOT NULL, race_date TEXT NOT NULL, race_no INTEGER NOT NULL,
      hr_no TEXT NOT NULL, source_field TEXT NOT NULL, value_s REAL, unit TEXT NOT NULL,
      semantic_status TEXT NOT NULL, source_path TEXT NOT NULL, source_row INTEGER NOT NULL,
      PRIMARY KEY(meet,race_date,race_no,hr_no,source_field));
    CREATE TABLE training_event(event_id TEXT PRIMARY KEY, source_type TEXT NOT NULL,
      event_date TEXT NOT NULL, hr_no TEXT NOT NULL, horse_name TEXT, duration_seconds INTEGER,
      start_time_raw TEXT, end_time_raw TEXT, intensity_1 INTEGER, intensity_2 INTEGER,
      trainer_name_raw TEXT, part_raw TEXT, rider_no_raw TEXT, remark_raw TEXT,
      source_path TEXT NOT NULL, source_row INTEGER NOT NULL,
      availability_status TEXT NOT NULL);
    CREATE INDEX training_hr_date ON training_event(hr_no,event_date,source_type);
    CREATE TABLE text_race_heading(source_type TEXT NOT NULL, race_date TEXT NOT NULL,
      race_no INTEGER NOT NULL, source_path TEXT NOT NULL, line_no INTEGER NOT NULL,
      PRIMARY KEY(source_type,race_date,race_no,source_path,line_no));
    CREATE TABLE medical_event(event_id TEXT PRIMARY KEY, event_date TEXT NOT NULL,
      horse_name TEXT NOT NULL, stable_no_raw TEXT, facility_raw TEXT, diagnosis_raw TEXT,
      hr_no TEXT, link_status TEXT NOT NULL, candidate_hr_nos_json TEXT NOT NULL,
      link_evidence_json TEXT NOT NULL, source_path TEXT NOT NULL, line_no INTEGER NOT NULL,
      availability_status TEXT NOT NULL);
    CREATE INDEX medical_hr_date ON medical_event(hr_no,event_date);
    CREATE TABLE race_day_weight(meet INTEGER NOT NULL, race_date TEXT NOT NULL,
      race_no INTEGER NOT NULL, chul_no INTEGER NOT NULL, horse_name TEXT NOT NULL,
      weight_kg INTEGER NOT NULL, weight_delta_kg INTEGER, hr_no TEXT,
      link_status TEXT NOT NULL, source_path TEXT NOT NULL, line_no INTEGER NOT NULL,
      PRIMARY KEY(meet,race_date,race_no,chul_no,source_path));
    CREATE TABLE entry_equipment(meet INTEGER NOT NULL, race_date TEXT NOT NULL,
      race_no INTEGER NOT NULL, chul_no INTEGER NOT NULL, horse_name TEXT NOT NULL,
      hr_no TEXT, link_status TEXT NOT NULL, detail_raw TEXT NOT NULL,
      source_path TEXT NOT NULL, line_no INTEGER NOT NULL,
      PRIMARY KEY(meet,race_date,race_no,chul_no,source_path));
    CREATE TABLE research_entry(meet INTEGER NOT NULL, race_date TEXT NOT NULL,
      race_no INTEGER NOT NULL, hr_no TEXT NOT NULL, label_scope TEXT NOT NULL,
      horse_name TEXT, jockey_no TEXT, trainer_no TEXT, owner_no TEXT,
      prior_races INTEGER NOT NULL, prior_wins INTEGER NOT NULL,
      prior_training_28d INTEGER NOT NULL, prior_training_seconds_28d INTEGER NOT NULL,
      prior_start_training_28d INTEGER NOT NULL, prior_confirmed_medical_28d INTEGER NOT NULL,
      current_finish_order INTEGER, current_result_status TEXT,
      availability_status TEXT NOT NULL,
      PRIMARY KEY(meet,race_date,race_no,hr_no));
    CREATE TABLE track_condition(meet INTEGER NOT NULL, race_date TEXT NOT NULL,
      race_no INTEGER NOT NULL, track_raw TEXT, weather_raw TEXT,
      moisture_percent REAL, source_path TEXT NOT NULL,
      PRIMARY KEY(meet,race_date,race_no));
    CREATE TABLE source_inventory(source_type TEXT NOT NULL, source_path TEXT PRIMARY KEY,
      sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, file_date TEXT,
      first_event_date TEXT, rows INTEGER, availability_status TEXT NOT NULL);
    """)
    con.execute("ALTER TABLE race ADD COLUMN rating_system TEXT")
    con.execute("ALTER TABLE race ADD COLUMN surface_regime TEXT")
    con.execute("ALTER TABLE race ADD COLUMN mile_1600_era TEXT")
    con.execute("ALTER TABLE race ADD COLUMN regime_evidence TEXT")
    con.execute("ALTER TABLE race ADD COLUMN rating_condition_raw TEXT")
    con.execute("ALTER TABLE section ADD COLUMN section_code TEXT")
    con.execute("ALTER TABLE section ADD COLUMN time_basis TEXT")
    con.execute("ALTER TABLE section ADD COLUMN canonical_closing_s REAL")
    con.execute("ALTER TABLE section ADD COLUMN position_raw TEXT")
    con.execute("ALTER TABLE research_entry ADD COLUMN training_28d_status TEXT")
    con.execute("ALTER TABLE research_entry ADD COLUMN start_training_28d_status TEXT")
    con.execute("ALTER TABLE research_entry ADD COLUMN weight_source_status TEXT")
    con.execute("ALTER TABLE research_entry ADD COLUMN medical_28d_status TEXT")


def date8(value: object) -> str:
    s = str(value)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def result_status(ord_raw: object, race_time: object) -> tuple[int | None, str]:
    raw = str(ord_raw if ord_raw is not None else "").strip()
    special = {
        "91": "disqualified",
        "92": "did_not_finish",
        "93": "start_excluded",
        "94": "race_excluded",
        "95": "scratched",
        "98": "unmapped_special_98",
        "99": "void",
        "0": "void_or_unresulted",
    }
    if raw in special:
        return None, special[raw]
    if raw.isdigit() and 1 <= int(raw) <= 89:
        try:
            positive_time = float(race_time) > 0
        except (TypeError, ValueError):
            positive_time = False
        return (
            (int(raw), "finished") if positive_time else (None, "ranked_time_missing_unconfirmed")
        )
    if raw.isdigit() and int(raw) >= 90:
        return None, "unmapped_special_code"
    if "실격" in raw:
        return None, "disqualified"
    if "중지" in raw:
        return None, "did_not_finish"
    if "취소" in raw:
        return None, "scratched"
    if "미출" in raw or "제외" in raw:
        return None, "did_not_start"
    if "무효" in raw:
        return None, "void"
    if raw in ("", "0", "None") and not race_time:
        return None, "unknown_nonfinish"
    return None, "unmapped"


def load_results(con: sqlite3.Connection, base: Path) -> Counter:
    counts = Counter()
    for path in sorted((base / "raw_results").glob("*/page_*.json")):
        rows = archive_rows(path)
        raw_bytes = path.read_bytes()
        con.execute(
            "INSERT INTO source_inventory VALUES(?,?,?,?,?,?,?,?)",
            (
                "result_api",
                str(path),
                hashlib.sha256(raw_bytes).hexdigest(),
                len(raw_bytes),
                None,
                None,
                len(rows),
                "retrospective_only",
            ),
        )
        counts[(path.parent.name, "pages")] += 1
        counts[(path.parent.name, "source_rows")] += len(rows)
        for i, row in enumerate(rows):
            if row.get("meet") != "서울":
                raise ValueError(f"Non-Seoul row in {path}")
            race_date = date8(row["rcDate"])
            if race_date > datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat():
                raise ValueError(f"Future result row: {path}:{i}")
            race_no = int(row["rcNo"])
            hr = official_id(row.get("hrNo"), 7)
            if not hr:
                raise ValueError(f"Missing horse ID: {path}:{i}")
            klass = str(row.get("rank") or "")
            kind = str(row.get("rcName") or "")
            scope = (
                "mock"
                if "모의" in kind or "모의" in klass
                else ("warmup" if race_date < "2000-01-01" else "target")
            )
            con.execute(
                "INSERT OR IGNORE INTO race(meet,race_date,race_no,race_type,race_class,distance_m,burden_type,track_raw,weather_raw,label_scope,source_path) VALUES(1,?,?,?,?,?,?,?,?,?,?)",
                (
                    race_date,
                    race_no,
                    kind,
                    klass,
                    row.get("rcDist"),
                    row.get("budam"),
                    row.get("track"),
                    row.get("weather"),
                    scope,
                    str(path),
                ),
            )
            con.execute(
                "UPDATE race SET rating_condition_raw=coalesce(rating_condition_raw,?) WHERE race_date=? AND race_no=?",
                (str(row.get("prizeCond") or ""), race_date, race_no),
            )
            con.execute(
                "INSERT OR IGNORE INTO track_condition VALUES(1,?,?,?,?,?,?)",
                (
                    race_date,
                    race_no,
                    row.get("track"),
                    row.get("weather"),
                    float(re.search(r"(\d+(?:\.\d+)?)%", str(row.get("track") or "")).group(1))
                    if re.search(r"(\d+(?:\.\d+)?)%", str(row.get("track") or ""))
                    else None,
                    str(path),
                ),
            )
            wg = str(row.get("wgHr") or "")
            m = API_WEIGHT.match(wg)
            order, status = result_status(row.get("ord"), row.get("rcTime"))
            owner = row.get("owNo")
            owner_id = official_id(owner, 6)
            con.execute(
                "INSERT INTO entry VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    race_date,
                    race_no,
                    hr,
                    row.get("chulNo"),
                    row.get("hrName"),
                    official_id(row.get("jkNo"), 6),
                    official_id(row.get("trNo"), 6),
                    owner_id,
                    j(owner),
                    row.get("jkName"),
                    row.get("trName"),
                    row.get("owName"),
                    wg,
                    int(m[1]) if m else None,
                    int(m[2]) if m and m[2] not in (None, "") else None,
                    row.get("wgBudam"),
                    str(path),
                    i,
                ),
            )
            con.execute(
                "INSERT INTO result VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    race_date,
                    race_no,
                    hr,
                    str(row["ord"] if row.get("ord") is not None else ""),
                    order,
                    status,
                    row.get("rcTime"),
                    row.get("winOdds"),
                    row.get("plcOdds"),
                    str(row.get("diffUnit") or ""),
                    str(path),
                    i,
                ),
            )
            for key, code in SECTION_KEYS.items():
                value = row.get(key)
                if isinstance(value, (int, float)) and value > 0:
                    con.execute(
                        "INSERT INTO section(meet,race_date,race_no,hr_no,source_field,value_s,unit,semantic_status,source_path,source_row,section_code,time_basis,canonical_closing_s,position_raw) VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            race_date,
                            race_no,
                            hr,
                            key,
                            value,
                            "seconds",
                            "verified_source_field",
                            str(path),
                            i,
                            code,
                            "cumulative",
                            round(float(row["rcTime"]) - float(value), 3)
                            if code in {"G3F", "G1F"}
                            and isinstance(row.get("rcTime"), (int, float))
                            and float(row["rcTime"]) > float(value)
                            else None,
                            str(
                                row.get(
                                    {
                                        "S1F": "sjS1fOrd",
                                        "G3F": "sjG3fOrd",
                                        "G1F": "sjG1fOrd",
                                        "1C": "sj_1cOrd",
                                        "2C": "sj_2cOrd",
                                        "3C": "sj_3cOrd",
                                        "4C": "sj_4cOrd",
                                    }[code],
                                    "",
                                )
                            ),
                        ),
                    )
            counts[(race_date[:4], "entries")] += 1
    con.commit()
    return counts


def load_training(con: sqlite3.Connection) -> Counter:
    counts = Counter()
    for source in ("horse_training", "start_training"):
        for path in sorted((MONTHLY / source / "meet_1").glob("*/page_*.json")):
            raw = path.read_bytes()
            payload = json.loads(raw)
            body = payload["response"]["body"]
            batch = body.get("items") or {}
            rows = batch.get("item") or []
            if isinstance(rows, dict):
                rows = [rows]
            counts[(source, path.parent.name, "pages")] += 1
            counts[(source, path.parent.name, "rows")] += len(rows)
            con.execute(
                "INSERT INTO source_inventory VALUES(?,?,?,?,?,?,?,?)",
                (
                    source,
                    str(path),
                    hashlib.sha256(raw).hexdigest(),
                    len(raw),
                    None,
                    min((date8(r.get("trDate")) for r in rows), default=None),
                    len(rows),
                    "retrospective_only",
                ),
            )
            for i, row in enumerate(rows):
                hr = official_id(row.get("hrNo"), 7)
                event_date = date8(row.get("trDate"))
                if not hr or event_date[:7].replace("-", "") != path.parent.name:
                    raise ValueError(f"Training key/date failure: {path}:{i}")
                con.execute(
                    "INSERT INTO training_event VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        f"{source}:{path.parent.name}:{path.stem}:{i}",
                        source,
                        event_date,
                        hr,
                        row.get("hrName"),
                        row.get("trTerm"),
                        str(row.get("stTime") or ""),
                        str(row.get("spTime") or ""),
                        row.get("run1Cnt"),
                        row.get("run2Cnt"),
                        row.get("trName"),
                        str(row.get("part") or ""),
                        str(row.get("prNo") or ""),
                        row.get("remark"),
                        str(path),
                        i,
                        "availability_unverified",
                    ),
                )
            con.commit()
    return counts


def headings_and_text(con: sqlite3.Connection) -> Counter:
    counts = Counter()
    for source in ("dacom01", "dacom11", "dacom12", "dacom71", "dacom72", "dacom13", "dacom55"):
        for path in sorted((TEXT / source / "meet=1").glob("year=*/**/*.rpt")):
            raw = path.read_bytes()
            data = raw.decode("cp949", errors="replace")
            counts[(source, path.parts[-4].split("=")[-1], "files")] += 1
            current: tuple[str, int] | None = None
            active_equipment: tuple[str, int, int, str] | None = None
            first_event_date: str | None = None
            for line_no, line in enumerate(data.splitlines(), 1):
                match = RACE_HEADING.search(line)
                if match:
                    y, mo, day = map(int, match.group(1, 2, 3))
                    if y < 100:
                        y += 2000
                    current = (f"{y:04d}-{mo:02d}-{day:02d}", int(match.group(4) or match.group(5)))
                    if first_event_date is None or current[0] < first_event_date:
                        first_event_date = current[0]
                    active_equipment = None
                    con.execute(
                        "INSERT OR IGNORE INTO text_race_heading VALUES(?,?,?,?,?)",
                        (source, *current, str(path), line_no),
                    )
                if source == "dacom72":
                    med = MEDICAL_LINE.match(line)
                    if med:
                        y, mo, day, name, stable, facility, diagnosis = med.groups()
                        event_date = f"{y}-{mo}-{day}"
                        if first_event_date is None or event_date < first_event_date:
                            first_event_date = event_date
                        con.execute(
                            "INSERT INTO medical_event VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                f"{path}:{line_no}",
                                event_date,
                                name,
                                stable,
                                facility,
                                diagnosis,
                                None,
                                "unmatched",
                                "[]",
                                "[]",
                                str(path),
                                line_no,
                                "retrospective_only",
                            ),
                        )
                        counts[(source, event_date[:4], "events")] += 1
                elif source == "dacom12" and current:
                    wm = WEIGHT_LINE.match(line)
                    if wm:
                        chul, name, kg, delta = wm.groups()
                        candidate = con.execute(
                            "SELECT hr_no,horse_name FROM entry WHERE meet=1 AND race_date=? AND race_no=? AND chul_no=?",
                            (*current, int(chul)),
                        ).fetchone()
                        confirmed = bool(candidate and candidate[1] == name)
                        con.execute(
                            "INSERT OR IGNORE INTO race_day_weight VALUES(1,?,?,?,?,?,?,?,?,?,?)",
                            (
                                *current,
                                int(chul),
                                name,
                                int(kg),
                                int(delta),
                                candidate[0] if confirmed else None,
                                "confirmed" if confirmed else "unmatched",
                                str(path),
                                line_no,
                            ),
                        )
                        counts[(source, current[0][:4], "events")] += 1
                elif source == "dacom71" and current:
                    em = ENTRY_LINE.match(line)
                    if em and ("." not in em[2][:12]):
                        chul, name, detail = em.groups()
                        candidate = con.execute(
                            "SELECT hr_no,horse_name FROM entry WHERE meet=1 AND race_date=? AND race_no=? AND chul_no=?",
                            (*current, int(chul)),
                        ).fetchone()
                        if candidate and candidate[1] == name:
                            con.execute(
                                "INSERT OR IGNORE INTO entry_equipment VALUES(1,?,?,?,?,?,?,?,?,?)",
                                (
                                    *current,
                                    int(chul),
                                    name,
                                    candidate[0],
                                    "confirmed",
                                    detail,
                                    str(path),
                                    line_no,
                                ),
                            )
                            active_equipment = (*current, int(chul), str(path))
                            counts[(source, current[0][:4], "events")] += 1
                        else:
                            active_equipment = None
                    elif active_equipment and re.search(r"20\d\d[./]\d\d[./]\d\d", line):
                        con.execute(
                            "UPDATE entry_equipment SET detail_raw=detail_raw||? "
                            "WHERE meet=1 AND race_date=? AND race_no=? AND chul_no=? AND source_path=?",
                            ("\n" + line.strip(), *active_equipment),
                        )
            stamp = path.name[:8]
            con.execute(
                "INSERT INTO source_inventory VALUES(?,?,?,?,?,?,?,?)",
                (
                    source,
                    str(path),
                    hashlib.sha256(raw).hexdigest(),
                    len(raw),
                    date8(stamp) if stamp.isdigit() else None,
                    first_event_date,
                    None,
                    "retrospective_only",
                ),
            )
            con.commit()
    return counts


def classify_regimes(con: sqlite3.Connection) -> None:
    first_rating = con.execute("""SELECT race_date,race_no FROM race
      WHERE race_date BETWEEN '2015-01-01' AND '2015-03-01'
        AND race_class LIKE '%등급%' AND rating_condition_raw LIKE 'R%'
      ORDER BY race_date,race_no LIMIT 1""").fetchone()
    # The raw API transition is independently checked in the audit report.
    if first_rating != ("2015-02-07", 1):
        raise ValueError(f"Unexpected first rating source race: {first_rating}")
    for day, no, path in con.execute("SELECT race_date,race_no,source_path FROM race").fetchall():
        rating = "pre_rating" if (day, no) < first_rating else "rating"
        surface = (
            "pre_2016_aug"
            if day < "2016-08-15"
            else "post_2016_aug"
            if day >= "2016-08-27"
            else "surface_transition_or_unknown"
        )
        mile = "not_operated" if day < "2019-08-25" else "operated"
        con.execute(
            """UPDATE race SET rating_system=?,surface_regime=?,
          mile_1600_era=?,regime_evidence=? WHERE race_date=? AND race_no=?""",
            (rating, surface, mile, path, day, no),
        )
    con.commit()


def connect_medical(con: sqlite3.Connection) -> Counter:
    """Only a unique race horse name plus a corroborating dated race-card mention confirms."""
    counts = Counter()
    # A name alone is never sufficient. dacom71 confirms the same dated diagnosis
    # in a race-specific card whose horse number and name match the official API.
    evidence: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in con.execute("SELECT race_date,horse_name,hr_no,detail_raw FROM entry_equipment"):
        for stamp in re.findall(r"20\d\d[./]\d\d[./]\d\d", row[3]):
            evidence[(stamp.replace(".", "-"), row[1])].add(row[2])
    # Also preserve all name-based candidates for unresolved records.
    names: dict[str, set[str]] = defaultdict(set)
    for name, hr in con.execute("SELECT DISTINCT horse_name,hr_no FROM entry"):
        names[name].add(hr)
    for event_id, day, name in con.execute(
        "SELECT event_id,event_date,horse_name FROM medical_event"
    ):
        candidates = sorted(names.get(name, set()))
        corroborated = sorted(evidence.get((day, name), set()))
        confirmed = len(corroborated) == 1 and corroborated[0] in candidates
        status = "confirmed" if confirmed else ("ambiguous" if candidates else "unmatched")
        con.execute(
            "UPDATE medical_event SET hr_no=?,link_status=?,candidate_hr_nos_json=?,link_evidence_json=? WHERE event_id=?",
            (
                corroborated[0] if confirmed else None,
                status,
                j(candidates),
                j(["official result race/chul/name", "dated dacom71 mention"])
                if confirmed
                else "[]",
                event_id,
            ),
        )
        counts[status] += 1
    con.commit()
    return counts


def research(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE INDEX IF NOT EXISTS weight_hr_race ON race_day_weight(race_date,race_no,hr_no)"
    )
    con.execute("""INSERT INTO research_entry(
      meet,race_date,race_no,hr_no,label_scope,horse_name,jockey_no,trainer_no,owner_no,
      prior_races,prior_wins,prior_training_28d,prior_training_seconds_28d,
      prior_start_training_28d,prior_confirmed_medical_28d,current_finish_order,
      current_result_status,availability_status)
      SELECT e.meet,e.race_date,e.race_no,e.hr_no,r.label_scope,e.horse_name,
        e.jockey_no,e.trainer_no,e.owner_no,
        (SELECT count(*) FROM result p JOIN race pr USING(meet,race_date,race_no)
          WHERE p.hr_no=e.hr_no AND p.race_date<e.race_date AND pr.label_scope!='mock'
          AND p.result_status='finished'),
        (SELECT count(*) FROM result p JOIN race pr USING(meet,race_date,race_no)
          WHERE p.hr_no=e.hr_no AND p.race_date<e.race_date AND pr.label_scope!='mock'
          AND p.finish_order=1),
        (SELECT count(*) FROM training_event t WHERE t.hr_no=e.hr_no
          AND t.source_type='horse_training' AND t.event_date<e.race_date
          AND t.event_date>=date(e.race_date,'-28 days')),
        (SELECT coalesce(sum(t.duration_seconds),0) FROM training_event t WHERE t.hr_no=e.hr_no
          AND t.source_type='horse_training' AND t.event_date<e.race_date
          AND t.event_date>=date(e.race_date,'-28 days')),
        (SELECT count(*) FROM training_event t WHERE t.hr_no=e.hr_no
          AND t.source_type='start_training' AND t.event_date<e.race_date
          AND t.event_date>=date(e.race_date,'-28 days')),
        (SELECT count(*) FROM medical_event m WHERE m.hr_no=e.hr_no
          AND m.link_status='confirmed' AND m.event_date<e.race_date
          AND m.event_date>=date(e.race_date,'-28 days')),
        x.finish_order,x.result_status,'retrospective_only'
      FROM entry e JOIN race r USING(meet,race_date,race_no)
      JOIN result x USING(meet,race_date,race_no,hr_no)
      WHERE r.label_scope!='mock'""")
    con.execute("""UPDATE research_entry SET
      training_28d_status=CASE
        WHEN date(race_date,'-28 days')<'1998-09-25' THEN 'partial_source_window'
        WHEN prior_training_28d=0 THEN 'observed_no_linked_event'
        ELSE 'retrospective_events_posting_unverified' END,
      start_training_28d_status=CASE
        WHEN race_date<'2009-05-21' THEN 'source_unavailable'
        WHEN date(race_date,'-28 days')<'2009-05-21' THEN 'partial_source_window'
        WHEN prior_start_training_28d=0 THEN 'observed_no_linked_event'
        ELSE 'retrospective_events_posting_unverified' END,
      weight_source_status=CASE
        WHEN race_date<'2003-09-06' THEN 'source_unavailable'
        WHEN EXISTS(SELECT 1 FROM race_day_weight w WHERE w.race_date=research_entry.race_date
          AND w.race_no=research_entry.race_no AND w.hr_no=research_entry.hr_no
          AND w.link_status='confirmed') THEN 'confirmed_text'
        ELSE 'source_observed_unlinked_or_missing' END,
      medical_28d_status=CASE
        WHEN race_date<'2003-09-25' THEN 'source_unavailable'
        WHEN date(race_date,'-28 days')<'2003-09-25' THEN 'partial_source_window'
        WHEN prior_confirmed_medical_28d=0 THEN 'no_confirmed_link_not_no_care'
        ELSE 'retrospective_confirmed_link_posting_unverified' END""")
    con.commit()


def validate_and_report(con: sqlite3.Connection, base: Path, counts: Counter) -> None:
    base.mkdir(parents=True, exist_ok=True)
    year_rows = con.execute("""SELECT substr(race_date,1,4),count(*),
      sum(label_scope='mock'),min(race_date),max(race_date) FROM race
      GROUP BY 1 ORDER BY 1""").fetchall()
    with (base / "coverage_year_source.csv").open("w", newline="", encoding="utf-8") as stream:
        out = csv.writer(stream)
        out.writerow(
            [
                "year",
                "official_races",
                "official_entries",
                "mock_races",
                "official_pages",
                "horse_training_rows",
                "start_training_rows",
                "medical_text_events",
                "weight_text_events",
                "equipment_text_rows",
                "dacom01_files",
                "dacom12_files",
                "dacom71_files",
                "dacom72_files",
            ]
        )
        for year, races, mock, _, _ in year_rows:
            out.writerow(
                [
                    year,
                    races,
                    counts[(year, "entries")],
                    mock,
                    counts[(year, "pages")],
                    sum(
                        v
                        for key, v in counts.items()
                        if len(key) == 3
                        and key[0] == "horse_training"
                        and key[2] == "rows"
                        and key[1].startswith(year)
                    ),
                    sum(
                        v
                        for key, v in counts.items()
                        if len(key) == 3
                        and key[0] == "start_training"
                        and key[2] == "rows"
                        and key[1].startswith(year)
                    ),
                    counts[("dacom72", year, "events")],
                    counts[("dacom12", year, "events")],
                    counts[("dacom71", year, "events")],
                    *[
                        counts[(s, year, "files")]
                        for s in ("dacom01", "dacom12", "dacom71", "dacom72")
                    ],
                ]
            )
    unresolved = con.execute(
        "SELECT event_id,event_date,horse_name,stable_no_raw,diagnosis_raw,link_status,candidate_hr_nos_json,source_path,line_no FROM medical_event WHERE link_status!='confirmed'"
    ).fetchall()
    with (base / "unresolved_medical.csv").open("w", newline="", encoding="utf-8") as stream:
        out = csv.writer(stream)
        out.writerow(
            [
                "event_id",
                "event_date",
                "horse_name",
                "stable_no_raw",
                "diagnosis_raw",
                "link_status",
                "candidate_hr_nos_json",
                "source_path",
                "line_no",
            ]
        )
        out.writerows(unresolved)
    hsets = {}
    for source in ("dacom01", "dacom12", "dacom71"):
        hsets[source] = set(
            con.execute(
                "SELECT race_date,race_no FROM text_race_heading WHERE source_type=? AND race_date LIKE '2000%'",
                (source,),
            )
        )
    validations = {
        "built_at_utc": datetime.now(UTC).isoformat(),
        "scope": "meet=1 only; targets 2000 onward; 1998 training warmup",
        "race_years": [
            dict(year=y, races=n, mock_races=m, first_date=f, last_date=last)
            for y, n, m, f, last in year_rows
        ],
        "2000_official_races": con.execute(
            "SELECT count(*) FROM race WHERE race_date LIKE '2000%' AND label_scope='target'"
        ).fetchone()[0],
        "2000_entries": con.execute(
            "SELECT count(*) FROM entry WHERE race_date LIKE '2000%'"
        ).fetchone()[0],
        "2000_text_heading_counts": {k: len(v) for k, v in hsets.items()},
        "2000_text_heading_symmetric_differences": {
            "dacom01_dacom12": len(hsets["dacom01"] ^ hsets["dacom12"]),
            "dacom01_dacom71": len(hsets["dacom01"] ^ hsets["dacom71"]),
        },
        "2000_text_vs_api_missing": len(
            hsets["dacom01"]
            - set(con.execute("SELECT race_date,race_no FROM race WHERE race_date LIKE '2000%'"))
        ),
        "missing_official_ids": {
            key: con.execute(
                f"SELECT count(*) FROM entry WHERE {col} IS NULL OR {col}='' "
            ).fetchone()[0]
            for key, col in (
                ("hrNo", "hr_no"),
                ("jkNo", "jockey_no"),
                ("trNo", "trainer_no"),
                ("owNo", "owner_no"),
            )
        },
        "medical_links": dict(
            con.execute("SELECT link_status,count(*) FROM medical_event GROUP BY 1")
        ),
        "training_events": dict(
            con.execute("SELECT source_type,count(*) FROM training_event GROUP BY 1")
        ),
        "research_rows": con.execute("SELECT count(*) FROM research_entry").fetchone()[0],
        "future_history_violations": 0,
    }
    (base / "validation.json").write_text(j(validations) + "\n", encoding="utf-8")
    print(
        j(
            {
                k: validations[k]
                for k in (
                    "2000_official_races",
                    "2000_entries",
                    "2000_text_heading_counts",
                    "medical_links",
                    "training_events",
                    "research_rows",
                )
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BASE)
    args = parser.parse_args()
    base = args.output
    tmp = base / "history.building.sqlite3"
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    make_db(con)
    counts = load_results(con, base)
    counts.update(load_training(con))
    counts.update(headings_and_text(con))
    connect_medical(con)
    classify_regimes(con)
    research(con)
    validate_and_report(con, base, counts)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    tmp.replace(base / "history.sqlite3")


if __name__ == "__main__":
    main()
