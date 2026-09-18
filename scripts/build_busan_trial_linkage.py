"""Rebuild and link archived Busan running-trial reports in an isolated database.

No HTTP requests and no writes to the operating/history databases.  Names alone
never establish an official horse ID.  Uncertain rows retain every candidate.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from horse_racing.parsers.running_trials import parse_running_trial_report

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/kra_text/dacom23/meet=3"
HISTORY = ROOT / "data/research/busan_history_20260915/history.sqlite3"
OPERATING = ROOT / "data/horse_racing.sqlite3"
OUTPUT = ROOT / "data/research/busan_trial_linkage_20260915"
API_RAW = OUTPUT / "api_raw"
PREFIX = re.compile(r"^\[(?:서울|부경|부산|제주|서|부|제)\]\s*")
TITLE = re.compile(r"^제목\s*:.*?(\d{2,4})년\s*(\d{1,2})월\s*(\d{1,2})일.*?제\s*(\d+)경주")


def ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def digest(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            d.update(chunk)
    return d.hexdigest()


def key(value: str | None) -> str:
    return "".join(unicodedata.normalize("NFKC", PREFIX.sub("", value or "")).split()).casefold()


def month(value: str | date) -> int:
    value = str(value)
    return int(value[:4]) * 12 + int(value[5:7])


def age_relation(day: date, age: int | None, birth: str | None) -> str:
    if age is None or not birth:
        return "unknown"
    calendar = day.year - int(birth[:4])
    actual = calendar - (day.strftime("%m-%d") < birth[5:])
    if age == calendar:
        return "calendar"
    if day.year < 2015 and age == actual:
        return "birthday_based"
    return "conflict"


def sex_relation(trial: str | None, profile: str | None) -> str:
    if not trial or not profile:
        return "unknown"
    if trial == profile:
        return "same"
    if trial == "수" and profile == "거":
        return "later_gelded_possible"
    return "conflict"


def normalized_report(raw: str) -> str:
    # These are source-era labels for the same non-official-race report format.
    for old, new in (("주행검사성적", "주행심사성적"),
                     ("능력검사성적", "주행심사성적"),
                     ("선수명", "기수명"), ("감독명", "조교사명")):
        raw = raw.replace(old, new)
    raw = re.sub(r"(?<=\s)(?:취|경)(?=\s)", "출", raw)
    lines = []
    for line in raw.splitlines():
        tokens = line.split()
        # Canceled/all-scratched tables sometimes have no finish-rank column.
        if len(tokens) >= 2 and tokens[0].isdigit() and not tokens[1].isdigit():
            line = " 95  " + line
        lines.append(line)
    return "\n".join(lines)


def metadata_lines(raw: str) -> dict[tuple[str, int, int], tuple[int, str]]:
    """Return original physical line for (day, trial number, horse number)."""
    result = {}
    day_no = None
    in_first_table = False
    seen_header = False
    for line_no, line in enumerate(raw.splitlines(), 1):
        title = TITLE.search(line)
        if title:
            year, mo, day, race = map(int, title.groups())
            if year < 100:
                year += 2000
            day_no = (f"{year:04d}-{mo:02d}-{day:02d}", race)
            in_first_table = False
            seen_header = False
        if day_no and "마    명" in line and "연령" in line:
            in_first_table = True
            seen_header = False
            continue
        if in_first_table and line.lstrip().startswith("---"):
            if seen_header:
                in_first_table = False
            else:
                seen_header = True
            continue
        if not in_first_table or not seen_header:
            continue
        tokens = line.split()
        if len(tokens) < 7:
            continue
        horse_no = int(tokens[1]) if len(tokens) > 1 and tokens[0].isdigit() and tokens[1].isdigit() else (
            int(tokens[0]) if tokens[0].isdigit() else None)
        if horse_no is not None:
            result[(day_no[0], day_no[1], horse_no)] = (line_no, line)
    return result


def result_lines(raw: str) -> dict[tuple[str, int, int], tuple[int, str]]:
    """Return original physical score-table lines, including canceled entries."""
    result = {}
    day_no = None
    in_table = False
    seen_header = False
    for line_no, line in enumerate(raw.splitlines(), 1):
        title = TITLE.search(line)
        if title:
            year, mo, day, race = map(int, title.groups())
            if year < 100:
                year += 2000
            day_no = (f"{year:04d}-{mo:02d}-{day:02d}", race)
            in_table = False
            seen_header = False
        if day_no and "마체중" in line and "불합격사유" in line:
            in_table = True
            seen_header = False
            continue
        if in_table and line.lstrip().startswith("---"):
            if seen_header:
                in_table = False
            else:
                seen_header = True
            continue
        if not in_table or not seen_header:
            continue
        tokens = line.split()
        if len(tokens) < 4:
            continue
        horse_no = int(tokens[1]) if tokens[0].isdigit() and tokens[1].isdigit() else (
            int(tokens[0]) if tokens[0].isdigit() else None)
        if horse_no is not None:
            result[(day_no[0], day_no[1], horse_no)] = (line_no, line)
    return result


def source_kind(raw: str, day: str, race_no: int) -> str:
    for line in raw.splitlines():
        m = TITLE.search(line)
        if m:
            y, mo, d, no = map(int, m.groups())
            y += 2000 if y < 100 else 0
            if f"{y:04d}-{mo:02d}-{d:02d}" == day and no == race_no:
                return ("ability_exam" if "능력검사" in line else
                        "running_exam" if "주행검사" in line else "running_trial")
    raise ValueError(f"Missing source heading: {day} race {race_no}")


def load_official_api() -> tuple[dict[tuple[str, int, int], dict], list[Path]]:
    """Load archived meet=3 API pages without making a network request."""
    rows: dict[tuple[str, int, int], dict] = {}
    paths = sorted(API_RAW.glob("20??/page_*.json"))
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        body = payload.get("response", {}).get("body", {})
        batch = (body.get("items") or {}).get("item") or []
        if isinstance(batch, dict):
            batch = [batch]
        if int(body.get("totalCount") or 0) < len(batch):
            raise ValueError(f"Invalid API totalCount: {path}")
        for source_row, row in enumerate(batch, 1):
            day_raw = str(row.get("trainDate") or "")
            if len(day_raw) != 8 or not day_raw.isdigit():
                raise ValueError(f"Invalid API trainDate: {path}:{source_row}")
            if day_raw[:4] != path.parent.name:
                raise ValueError(f"API year/path conflict: {path}:{source_row}")
            if row.get("meet") != "영남":
                raise ValueError(f"Unexpected meet in meet=3 response: {path}:{source_row}")
            api_key = (day_raw, int(row["trainNo"]), int(row["chulNo"]))
            if api_key in rows:
                raise ValueError(f"Duplicate official API trial key: {api_key}")
            rows[api_key] = {**row, "_source_path": str(path), "_source_row": source_row}
    if not paths:
        raise RuntimeError(f"No archived official trial API pages under {API_RAW}")
    return rows, paths


def schema(db: sqlite3.Connection) -> None:
    db.executescript("""
      CREATE TABLE source_file(path TEXT PRIMARY KEY,sha256 TEXT NOT NULL,
        bytes INTEGER NOT NULL,trial_count INTEGER NOT NULL,entry_count INTEGER NOT NULL,
        filename_header_date_disagrees INTEGER NOT NULL);
      CREATE TABLE trial(meet INTEGER NOT NULL CHECK(meet=3),trial_date TEXT NOT NULL,
        trial_no INTEGER NOT NULL,trial_round INTEGER,trial_kind TEXT NOT NULL,
        distance_m INTEGER,distance_provenance TEXT NOT NULL,weather_raw TEXT,
        track_raw TEXT,track_moisture_percent REAL,source_path TEXT NOT NULL,
        label_scope TEXT NOT NULL CHECK(label_scope='trial_only'),
        PRIMARY KEY(meet,trial_date,trial_no));
      CREATE TABLE trial_entry(meet INTEGER NOT NULL CHECK(meet=3),trial_date TEXT NOT NULL,
        trial_no INTEGER NOT NULL,chul_no INTEGER NOT NULL,horse_name_raw TEXT NOT NULL,
        origin_raw TEXT,sex_raw TEXT,age_raw INTEGER,jockey_name_raw TEXT,
        trainer_name_raw TEXT,finish_raw TEXT,finish_position INTEGER,
        judgement_raw TEXT,inspection_reason_raw TEXT,body_weight_kg INTEGER,
        finish_time_ms INTEGER,section_json TEXT NOT NULL,hr_no TEXT,
        link_status TEXT NOT NULL,link_method TEXT NOT NULL,
        candidate_hr_nos_json TEXT NOT NULL,link_evidence_json TEXT NOT NULL,
        source_path TEXT NOT NULL,source_line INTEGER NOT NULL,source_line_raw TEXT NOT NULL,
        availability_status TEXT NOT NULL,
        PRIMARY KEY(meet,trial_date,trial_no,chul_no),
        FOREIGN KEY(meet,trial_date,trial_no) REFERENCES trial(meet,trial_date,trial_no));
      CREATE INDEX trial_entry_horse_date ON trial_entry(hr_no,trial_date);
      CREATE TABLE candidate(meet INTEGER NOT NULL,trial_date TEXT NOT NULL,
        trial_no INTEGER NOT NULL,chul_no INTEGER NOT NULL,hr_no TEXT NOT NULL,
        profile_name TEXT,profile_sex TEXT,profile_birth TEXT,profile_meet INTEGER,
        age_relation TEXT NOT NULL,sex_relation TEXT NOT NULL,
        training_month_support INTEGER NOT NULL,race_date_support TEXT,
        race_trainer_agrees INTEGER NOT NULL,modern_direct INTEGER NOT NULL,
        official_api_direct INTEGER NOT NULL,
        PRIMARY KEY(meet,trial_date,trial_no,chul_no,hr_no));
      CREATE TABLE official_trial_api_entry(
        meet INTEGER NOT NULL CHECK(meet=3),trial_date TEXT NOT NULL,
        trial_no INTEGER NOT NULL,chul_no INTEGER NOT NULL,api_meet_raw TEXT NOT NULL,
        hr_no TEXT,horse_name_raw TEXT,jockey_no TEXT,jockey_name_raw TEXT,
        trainer_no TEXT NOT NULL,trainer_name_raw TEXT,pass_flag_raw TEXT,
        reason_raw TEXT,nopass_reason_raw TEXT,raw_json TEXT NOT NULL,
        source_path TEXT NOT NULL,source_row INTEGER NOT NULL,
        PRIMARY KEY(meet,trial_date,trial_no,chul_no));
      CREATE TABLE race_entry_trial_history(
        meet INTEGER NOT NULL CHECK(meet=3),race_date TEXT NOT NULL,
        race_no INTEGER NOT NULL,hr_no TEXT NOT NULL,
        prior_confirmed_trial_count INTEGER NOT NULL,
        prior_confirmed_pass_count INTEGER NOT NULL,
        last_confirmed_trial_date TEXT,last_confirmed_judgement TEXT,
        unresolved_prior_same_name_count INTEGER NOT NULL,
        availability_status TEXT NOT NULL,
        PRIMARY KEY(meet,race_date,race_no,hr_no));
      CREATE TABLE input_manifest(path TEXT PRIMARY KEY,role TEXT NOT NULL,
        sha256 TEXT NOT NULL,bytes INTEGER NOT NULL);
    """)


def build() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT / ".trials.sqlite3.tmp"
    if tmp.exists():
        tmp.unlink()
    db = sqlite3.connect(tmp)
    db.execute("PRAGMA foreign_keys=ON")
    schema(db)
    history = ro(HISTORY)
    operating = ro(OPERATING)
    official_api, api_paths = load_official_api()
    api_year_rows = Counter()
    for (day_raw, trial_no, chul_no), row in official_api.items():
        day = f"{day_raw[:4]}-{day_raw[4:6]}-{day_raw[6:]}"
        api_year_rows[day_raw[:4]] += 1
        db.execute("INSERT INTO official_trial_api_entry VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (3, day, trial_no, chul_no, row["meet"], row.get("hrNo"),
             row.get("hrName"), row.get("jkNo"), row.get("jkName"),
             row.get("trNo"), row.get("trName"), str(row.get("passFlag") or ""),
             str(row.get("reason") or ""), str(row.get("nopassReason") or ""),
             json.dumps({k: v for k, v in row.items() if not k.startswith("_")},
                        ensure_ascii=False, sort_keys=True),
             row["_source_path"], row["_source_row"]))

    profiles = defaultdict(dict)
    for hr, name, sex, birth, meet in operating.execute("""
      SELECT kra_horse_id,name_ko,sex,birth_date,meet_code FROM horses
      WHERE kra_horse_id NOT LIKE 'text:%'"""):
        profiles[key(name)][hr] = (name, sex, birth, meet)
    training = defaultdict(lambda: defaultdict(set))
    for hr, name, mo in history.execute("""
      SELECT DISTINCT hr_no,horse_name,substr(event_date,1,7)
      FROM training_event WHERE source_type='horse_training'"""):
        training[key(name)][hr].add(month(mo))
    races = defaultdict(lambda: defaultdict(list))
    for hr, name, day, trainer in history.execute("""
      SELECT hr_no,horse_name,race_date,trainer_name FROM entry"""):
        races[key(name)][hr].append((day, key(trainer)))
    modern = {}
    for day, no, chul, name, hr in operating.execute("""
      SELECT t.trial_date_local,t.trial_race_number,r.horse_number,
             r.horse_name_raw,h.kra_horse_id
      FROM running_trial_results r JOIN running_trials t ON t.id=r.running_trial_id
      LEFT JOIN horses h ON h.id=r.horse_id WHERE t.meet_code=3"""):
        modern[(day, no, chul)] = (name, hr)

    # Identify whole cards with a source-wide next-year age convention. A
    # solitary mismatched age never qualifies; five independent horses with
    # official dated training and matching profiles must show the same offset.
    year_end_card_counts = Counter()
    for path in RAW.glob("year=*/**/*.rpt"):
        raw = path.read_bytes().decode("cp949", errors="replace")
        for trial in parse_running_trial_report(normalized_report(raw), meet=3):
            day = trial.trial_date.isoformat()
            if day[5:] < "12-15":
                continue
            trial_month = month(day)
            for item in trial.results:
                horse_name = key(item.horse_name)
                nearby = [hr for hr, months in training[horse_name].items()
                          if any(abs(trial_month - value) <= 1 for value in months)]
                if len(nearby) != 1:
                    continue
                profile = profiles[horse_name].get(nearby[0])
                if (profile and profile[2] and profile[3] == 3 and item.age
                        == trial.trial_date.year - int(profile[2][:4]) + 1
                        and sex_relation(item.sex, profile[1]) in
                        {"same", "later_gelded_possible"}):
                    year_end_card_counts[day] += 1
    year_end_cards = {day for day, count in year_end_card_counts.items() if count >= 5}

    stats = Counter()
    for path in sorted(RAW.glob("year=*/**/*.rpt")):
        raw_bytes = path.read_bytes()
        raw = raw_bytes.decode("cp949", errors="replace")
        parsed = parse_running_trial_report(normalized_report(raw), meet=3)
        lines = metadata_lines(raw)
        scores = result_lines(raw)
        source_count = 0
        filename_header_date_disagrees = 0
        for trial in parsed:
            day = trial.trial_date.isoformat()
            if day.replace("-", "") != path.name[:8]:
                filename_header_date_disagrees += 1
                stats[(day[:4], "filename_header_date_disagrees")] += 1
            kind = source_kind(raw, day, trial.trial_race_number)
            db.execute("INSERT INTO trial VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (3, day, trial.trial_race_number, trial.trial_round, kind,
                 trial.distance_m, "parser_default_unverified",
                 trial.weather, trial.track_condition, trial.track_moisture_percent,
                 str(path), "trial_only"))
            stats[(day[:4], "trials")] += 1
            if not trial.results:
                stats[(day[:4], "empty_trials")] += 1
            for item in trial.results:
                source_count += 1
                pos = lines.get((day, trial.trial_race_number, item.horse_number))
                if pos is None or key(item.horse_name) not in key(pos[1]):
                    raise ValueError(f"Could not trace trial row: {path}:{day}:{trial.trial_race_number}:{item.horse_number}")
                score = scores.get((day, trial.trial_race_number, item.horse_number))
                if score is None or key(item.horse_name) not in key(score[1]):
                    raise ValueError(f"Could not trace trial score: {path}:{day}:{trial.trial_race_number}:{item.horse_number}")
                original_judgement = next((token for token in score[1].split()
                                           if token in {"합", "불", "유", "연", "출", "심", "주", "취", "경"}), None)
                if original_judgement:
                    item.judgement = original_judgement
                name = key(item.horse_name)
                m = month(day)
                training_hrs = {hr for hr, months in training[name].items()
                                if any(abs(m - month_value) <= 1 for month_value in months)}
                profile_hrs = set(profiles[name])
                race_hrs = set(races[name])
                modern_row = modern.get((day, trial.trial_race_number, item.horse_number))
                api_row = official_api.get((day.replace("-", ""),
                                            trial.trial_race_number, item.horse_number))
                if modern_row and key(modern_row[0]) != name:
                    raise ValueError(f"Operating trial name conflict: {day}:{trial.trial_race_number}:{item.horse_number}")
                candidates = training_hrs | profile_hrs | race_hrs
                if modern_row and modern_row[1]:
                    candidates.add(modern_row[1])
                if api_row and api_row.get("hrNo"):
                    candidates.add(str(api_row["hrNo"]))
                evidence = {}
                for hr in sorted(candidates):
                    profile = profiles[name].get(hr)
                    age_rel = age_relation(trial.trial_date, item.age, profile[2]) if profile else "unknown"
                    sex_rel = sex_relation(item.sex, profile[1]) if profile else "unknown"
                    matching_races = [(d, tr) for d, tr in races[name].get(hr, [])
                                      if abs((date.fromisoformat(d) - trial.trial_date).days) <= 365]
                    matching_trainer = any(tr and tr == key(item.trainer_name)
                                           for _, tr in matching_races)
                    direct = bool(modern_row and modern_row[1] == hr)
                    api_direct = bool(api_row and api_row.get("hrNo") == hr)
                    in_training = hr in training_hrs
                    evidence[hr] = {
                        "profile": profile, "age_relation": age_rel,
                        "sex_relation": sex_rel,
                        "training_month_support": in_training,
                        "race_date_support": min((d for d, _ in matching_races), default=None),
                        "race_trainer_agrees": matching_trainer,
                        "modern_direct": direct,
                        "official_trial_api_exact_key": api_direct,
                        "official_trial_api_horse_name": api_row.get("hrName") if api_direct else None,
                        "official_trial_api_name_agrees": (
                            key(api_row.get("hrName")) == name if api_direct else None),
                        "official_trial_api_tr_no": api_row.get("trNo") if api_direct else None,
                        "official_trial_api_jk_no": api_row.get("jkNo") if api_direct else None,
                    }
                    db.execute("INSERT INTO candidate VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (3, day, trial.trial_race_number, item.horse_number, hr,
                         profile[0] if profile else None, profile[1] if profile else None,
                         profile[2] if profile else None, profile[3] if profile else None,
                         age_rel, sex_rel, int(in_training),
                         evidence[hr]["race_date_support"], int(matching_trainer), int(direct),
                         int(api_direct)))
                confirmed = []
                method = "none"
                if api_row and api_row.get("hrNo"):
                    confirmed = [str(api_row["hrNo"])]
                    method = "official_trial_api_exact_key"
                elif modern_row and modern_row[1]:
                    confirmed = [modern_row[1]]
                    method = "existing_trial_row_official_horse_id"
                else:
                    supported = [hr for hr in training_hrs if evidence[hr]["age_relation"] in
                                 {"calendar", "birthday_based"} and evidence[hr]["sex_relation"] in
                                 {"same", "later_gelded_possible"}]
                    if len(supported) == 1:
                        confirmed = supported
                        method = "official_training_month_plus_profile_age_sex"
                    elif not supported:
                        # Four late-December cards record some ages as the next
                        # racing year. Require both dated official training and
                        # a same-trainer official race, not the age offset alone.
                        year_end = [hr for hr in training_hrs if day[5:] >= "12-15"
                                    and evidence[hr]["profile"]
                                    and evidence[hr]["profile"][2]
                                    and item.age == trial.trial_date.year
                                    - int(evidence[hr]["profile"][2][:4]) + 1
                                    and evidence[hr]["sex_relation"] in
                                    {"same", "later_gelded_possible"}
                                    and (evidence[hr]["race_trainer_agrees"]
                                         or (day in year_end_cards and
                                             evidence[hr]["profile"][3] == 3))]
                        if len(year_end) == 1:
                            confirmed = year_end
                            method = ("year_end_age_offset_training_and_race_trainer"
                                      if evidence[year_end[0]]["race_trainer_agrees"] else
                                      "year_end_age_offset_training_card_cohort")
                    if not confirmed and not supported:
                        race_supported = [hr for hr in race_hrs if evidence[hr]["race_trainer_agrees"]
                                          and evidence[hr]["age_relation"] in {"calendar", "birthday_based"}
                                          and evidence[hr]["sex_relation"] in {"same", "later_gelded_possible"}]
                        if len(race_supported) == 1:
                            confirmed = race_supported
                            method = "official_race_trainer_plus_profile_age_sex"
                if confirmed:
                    hr_no = confirmed[0]
                    status = "confirmed"
                elif candidates:
                    hr_no = None
                    status = "ambiguous"
                else:
                    hr_no = None
                    status = "unmatched"
                stats[(day[:4], status)] += 1
                stats[(day[:4], "rows")] += 1
                section = {k: v for k, v in asdict(item).items()
                           if k.endswith("_ms") or k == "passing_order_raw"}
                db.execute("INSERT INTO trial_entry VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (3, day, trial.trial_race_number, item.horse_number,
                     item.horse_name, item.origin_country, item.sex, item.age,
                     item.jockey_name, item.trainer_name, item.finish_rank_raw,
                     item.finish_position, item.judgement, item.inspection_reason,
                     item.body_weight_kg, item.finish_time_ms,
                     json.dumps(section, ensure_ascii=False, sort_keys=True), hr_no,
                     status, method, json.dumps(sorted(candidates), ensure_ascii=False),
                     json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                     str(path), pos[0], pos[1], "retrospective_only"))
        db.execute("INSERT INTO source_file VALUES(?,?,?,?,?,?)",
                   (str(path), hashlib.sha256(raw_bytes).hexdigest(), len(raw_bytes),
                    len(parsed), source_count, filename_header_date_disagrees))
        stats[(path.parts[-4].split("=")[-1], "files")] += 1

    # Preserve official API rows missing from the Text archive. At present this
    # is one complete 2019-11-30 card (three trials, 26 horses).
    text_keys = {(day.replace("-", ""), trial_no, chul_no) for day, trial_no, chul_no
                 in db.execute("SELECT trial_date,trial_no,chul_no FROM trial_entry")}
    for (day_raw, trial_no, chul_no), row in sorted(official_api.items()):
        if (day_raw, trial_no, chul_no) in text_keys:
            continue
        day = f"{day_raw[:4]}-{day_raw[4:6]}-{day_raw[6:]}"
        track = str(row.get("track") or "")
        moisture = re.search(r"(\d+(?:\.\d+)?)%", track)
        db.execute("INSERT OR IGNORE INTO trial VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (3, day, trial_no, None, "running_trial", None, "official_api_unspecified",
             row.get("weather"), track, float(moisture.group(1)) if moisture else None,
             row["_source_path"], "trial_only"))
        hr_no = str(row.get("hrNo") or "") or None
        finish_raw = str(row.get("ord") or "")
        finish_position = int(finish_raw) if finish_raw.isdigit() and int(finish_raw) > 0 else None
        wg_hr = row.get("wgHr")
        body_weight = int(wg_hr) if isinstance(wg_hr, (int, float)) and wg_hr > 0 else None
        rc_time = row.get("rcTime")
        finish_ms = int(round(float(rc_time) * 1000)) if rc_time not in (None, "", 0, "0") else None
        section = {"source": "official_trial_api", "time_unit": "seconds"}
        section.update({k: row.get(k) for k in (
            "rcTime", "rcTimeS1f", "rcTimeG1f", "rcTimeG3f", "rcTimeG400",
            "rcTime_1c", "rcTime_2c", "rcTime_3c", "rcTime_4c",
            "rcTime_400", "passtime_3f", "passtime_4f")})
        evidence = ({hr_no: {"official_trial_api_exact_key": True,
                              "official_trial_api_horse_name": row.get("hrName"),
                              "official_trial_api_name_agrees": True,
                              "official_trial_api_tr_no": row.get("trNo"),
                              "official_trial_api_jk_no": row.get("jkNo")}}
                    if hr_no else {})
        status = "confirmed" if hr_no else "unmatched"
        method = "official_trial_api_only_row" if hr_no else "official_trial_api_missing_hr_no"
        db.execute("INSERT INTO trial_entry VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (3, day, trial_no, chul_no, row.get("hrName") or "",
             row.get("name"), row.get("sex"), row.get("age"), row.get("jkName"),
             row.get("trName"), finish_raw, finish_position, str(row.get("passFlag") or ""),
             str(row.get("reason") or ""), body_weight, finish_ms,
             json.dumps(section, ensure_ascii=False, sort_keys=True), hr_no, status, method,
             json.dumps([hr_no] if hr_no else [], ensure_ascii=False),
             json.dumps(evidence, ensure_ascii=False, sort_keys=True), row["_source_path"],
             row["_source_row"],
             json.dumps({k: v for k, v in row.items() if not k.startswith("_")},
                        ensure_ascii=False, sort_keys=True), "retrospective_only"))
        if hr_no:
            profile = profiles[key(row.get("hrName"))].get(hr_no)
            db.execute("INSERT INTO candidate VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (3, day, trial_no, chul_no, hr_no,
                 profile[0] if profile else row.get("hrName"),
                 profile[1] if profile else row.get("sex"),
                 profile[2] if profile else None, profile[3] if profile else 3,
                 "unknown", "same", 0, None, 0, 0, 1))
        stats[(day_raw[:4], "api_only_rows")] += 1
        stats[(day_raw[:4], "rows")] += 1
        stats[(day_raw[:4], status)] += 1
    # Count trials after API-only insertion rather than assuming all came from Text.
    trial_counts = dict(db.execute("SELECT substr(trial_date,1,4),count(*) FROM trial GROUP BY 1"))
    db.commit()
    by_hr = defaultdict(list)
    unresolved_by_name = defaultdict(list)
    for day, hr, horse_name, judgement, status in db.execute("""
      SELECT trial_date,hr_no,horse_name_raw,judgement_raw,link_status
      FROM trial_entry ORDER BY trial_date,trial_no,chul_no"""):
        if status == "confirmed":
            by_hr[hr].append((day, judgement))
        else:
            unresolved_by_name[key(horse_name)].append(day)
    by_hr_dates = {hr: [day for day, _ in rows] for hr, rows in by_hr.items()}
    history_rows = 0
    for meet, race_date, race_no, hr, horse_name in history.execute("""
      SELECT meet,race_date,race_no,hr_no,horse_name FROM research_entry
      ORDER BY race_date,race_no,hr_no"""):
        events = by_hr[hr]
        prior = bisect_left(by_hr_dates.get(hr, []), race_date)
        last = events[prior - 1] if prior else (None, None)
        uncertain = unresolved_by_name[key(horse_name)]
        uncertain_prior = bisect_left(uncertain, race_date)
        db.execute("INSERT INTO race_entry_trial_history VALUES(?,?,?,?,?,?,?,?,?,?)",
            (meet, race_date, race_no, hr, prior,
             sum(judgement == "합" for _, judgement in events[:prior]),
             last[0], last[1], uncertain_prior, "retrospective_only"))
        history_rows += 1
    db.commit()
    assert history_rows == history.execute("SELECT count(*) FROM research_entry").fetchone()[0]
    assert db.execute("SELECT count(*) FROM race_entry_trial_history").fetchone()[0] == history_rows
    assert db.execute("""SELECT count(*) FROM race_entry_trial_history
                         WHERE last_confirmed_trial_date >= race_date""").fetchone()[0] == 0
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert db.execute("SELECT count(*) FROM source_file").fetchone()[0] == 1053
    assert db.execute("SELECT count(*) FROM trial").fetchone()[0] == sum(trial_counts.values())
    assert db.execute("SELECT count(*) FROM trial_entry").fetchone()[0] == sum(v for (y,k),v in stats.items() if k=="rows")
    assert db.execute("SELECT count(*) FROM trial_entry WHERE link_status='confirmed' AND hr_no IS NULL").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM trial_entry WHERE link_status!='confirmed' AND hr_no IS NOT NULL").fetchone()[0] == 0
    for path, role in ((HISTORY, "read_only_history_db"),
                       (OPERATING, "read_only_operating_db"),
                       (Path(__file__), "linkage_code")):
        db.execute("INSERT INTO input_manifest VALUES(?,?,?,?)",
                   (str(path), role, digest(path), path.stat().st_size))
    for path in api_paths:
        db.execute("INSERT INTO input_manifest VALUES(?,?,?,?)",
                   (str(path), "official_trial_api_raw", digest(path), path.stat().st_size))
    db.commit()
    with (OUTPUT / "coverage_year.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["year", "text_source_files", "unified_trial_count", "empty_trial_count",
                         "text_parsed_entries", "official_api_entries", "api_only_entries",
                         "unified_entries", "confirmed", "ambiguous", "unmatched"])
        for year in range(2004, 2027):
            y = str(year)
            text_rows = stats[(y, "rows")] - stats[(y, "api_only_rows")]
            writer.writerow([year, stats[(y, "files")], trial_counts.get(y, 0),
                 stats[(y, "empty_trials")], text_rows, api_year_rows[y],
                 stats[(y, "api_only_rows")], stats[(y, "rows")],
                 stats[(y, "confirmed")], stats[(y, "ambiguous")], stats[(y, "unmatched")]])
    with (OUTPUT / "unresolved.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["trial_date", "trial_no", "chul_no", "horse_name_raw",
                         "sex_raw", "age_raw", "trainer_name_raw", "link_status",
                         "candidate_hr_nos_json", "link_evidence_json", "source_path", "source_line"])
        writer.writerows(db.execute("""
          SELECT trial_date,trial_no,chul_no,horse_name_raw,sex_raw,age_raw,
                 trainer_name_raw,link_status,candidate_hr_nos_json,link_evidence_json,
                 source_path,source_line FROM trial_entry WHERE link_status!='confirmed'
          ORDER BY trial_date,trial_no,chul_no"""))
    totals = dict(db.execute("SELECT link_status,count(*) FROM trial_entry GROUP BY link_status"))
    (OUTPUT / "validation.json").write_text(json.dumps({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "meet": 3, "source_files": 1053,
        "trials": db.execute("SELECT count(*) FROM trial").fetchone()[0],
        "entries": db.execute("SELECT count(*) FROM trial_entry").fetchone()[0],
        "official_api_entries": len(official_api),
        "official_api_only_entries": sum(v for (y,k),v in stats.items() if k == "api_only_rows"),
        "official_api_text_key_matches": len(official_api) - sum(v for (y,k),v in stats.items() if k == "api_only_rows"),
        "research_entry_trial_history": history_rows,
        "link_status": totals, "integrity_check": "ok",
        "all_text_source_rows_have_physical_line": True,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    db.close()
    history.close()
    operating.close()
    os.replace(tmp, OUTPUT / "trials.sqlite3")
    files = [p for p in OUTPUT.iterdir() if p.is_file() and p.name != "manifest.json"]
    (OUTPUT / "manifest.json").write_text(json.dumps({p.name: {
        "sha256": digest(p), "bytes": p.stat().st_size} for p in sorted(files)}, indent=2), encoding="utf-8")
    print(json.dumps(totals, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    build()
