"""Build an isolated, provenance-preserving Seoul dacom23 running-trial history."""
# ruff: noqa: E501
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from horse_racing.parsers.running_trials import (
    decode_running_trial_report,
    parse_running_trial_report,
)

RAW = Path("data/raw/kra_text/dacom23/meet=1")
PROFILE = Path("data/raw/kra/horse_profiles/2026/08/28")
HISTORY = Path("data/research/seoul_backfill_20260915_v1/history.sqlite3")
OPERATING = Path("data/horse_racing.sqlite3")
OUTPUT = Path("data/research/seoul_running_trials_20260915_v1")
COLLECTION_AUDIT = Path("data/logs/historical_text_dacom23_audit_20260914.json")
PROFILE_RUNS = {1: "12749", 2: "12756", 3: "12759"}


def sha(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            d.update(block)
    return d.hexdigest()


def norm(value: str | None) -> str:
    return "".join(unicodedata.normalize("NFKC", value or "").split()).casefold()


def normalized_report(raw: bytes) -> str:
    text = decode_running_trial_report(raw).replace(";TI", "제목 : ")
    for title in ("능력검사성적", "주행검사성적"):
        text = text.replace(title, "주행심사성적")
    return text.replace("선수명    감독명", "기수명    조교사명")


def report_blocks(text: str) -> list[str]:
    return [block for block in re.split(r"(?=^제목\s*:)", text.replace("\r\n", "\n"), flags=re.M)
            if "주행심사성적" in block]


def table_lines(block: str, marker: str) -> dict[int, str]:
    lines = block.splitlines()
    header = next((i for i, line in enumerate(lines) if marker in line), None)
    if header is None:
        return {}
    rules = [i for i in range(header + 1, len(lines)) if len(lines[i].strip()) >= 20 and set(lines[i].strip()) == {"-"}]
    if len(rules) < 2:
        return {}
    rows = {}
    for line in lines[rules[0] + 1:rules[1]]:
        tokens = line.split()
        if len(tokens) > 2 and tokens[0].isdigit() and tokens[1].isdigit():
            number = int(tokens[1])
            if number in rows:
                raise ValueError(f"Duplicate horse number in {marker} table: {number}")
            rows[number] = line.rstrip()
    return rows


def load_profiles() -> tuple[dict[str, list[dict]], list[Path]]:
    by_name: dict[str, list[dict]] = defaultdict(list)
    paths = []
    seen = set()
    for meet, run in PROFILE_RUNS.items():
        pages = sorted((PROFILE / f"meet_{meet}" / f"run_{run}").glob("page_*.json"))
        expected = None
        actual = 0
        for path in pages:
            body = json.loads(path.read_bytes())["response"]["body"]
            expected = int(body["totalCount"])
            items = body["items"]["item"]
            actual += len(items)
            paths.append(path)
            for row_no, item in enumerate(items):
                if item["meet"] not in {"서울", "제주", "영남", "부산경남"}:
                    raise ValueError(f"Unexpected profile meet: {item['meet']}")
                horse_id = str(item["hrNo"]).zfill(7)
                if horse_id in seen:
                    raise ValueError(f"Duplicate profile official horse ID: {horse_id}")
                seen.add(horse_id)
                by_name[norm(item["hrName"])].append({
                    "id": horse_id, "name": item["hrName"], "sex": item.get("sex"),
                    "birth_year": int(str(item["birthday"])[:4]), "birthday": str(item["birthday"]),
                    "meet": meet, "path": str(path), "row": row_no,
                })
        if not pages or actual != expected:
            raise ValueError(f"Incomplete official profile snapshot meet={meet}: {actual}/{expected}")
    return by_name, paths


def create_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
      PRAGMA foreign_keys=ON;
      CREATE TABLE source_file(path TEXT PRIMARY KEY,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,
        file_date TEXT NOT NULL,title_era TEXT NOT NULL,trial_blocks INTEGER NOT NULL,parsed_entries INTEGER NOT NULL);
      CREATE TABLE trial(meet INTEGER NOT NULL CHECK(meet=1),trial_date TEXT NOT NULL,
        trial_race_no INTEGER NOT NULL,trial_round INTEGER,distance_m INTEGER,weather TEXT,
        track_condition TEXT,track_moisture_percent REAL,source_path TEXT NOT NULL,
        source_block INTEGER NOT NULL,PRIMARY KEY(meet,trial_date,trial_race_no),
        FOREIGN KEY(source_path) REFERENCES source_file(path));
      CREATE TABLE trial_result(meet INTEGER NOT NULL CHECK(meet=1),trial_date TEXT NOT NULL,
        trial_race_no INTEGER NOT NULL,horse_number INTEGER NOT NULL,horse_name_raw TEXT NOT NULL,
        sex_raw TEXT,age_raw INTEGER,origin_raw TEXT,jockey_name_raw TEXT,trainer_name_raw TEXT,
        body_weight_kg INTEGER,finish_rank_raw TEXT,finish_time_ms INTEGER,judgement_raw TEXT,
        failure_reason_raw TEXT,inspection_reason_raw TEXT,g3f_ms INTEGER,s1f_ms INTEGER,
        corner_3_ms INTEGER,corner_4_ms INTEGER,g1f_ms INTEGER,passing_order_raw TEXT,
        result_state TEXT NOT NULL,metadata_line TEXT NOT NULL,result_line TEXT,section_line TEXT,
        official_hr_no TEXT,horse_link_status TEXT NOT NULL,candidate_ids_json TEXT NOT NULL,
        evidence_json TEXT NOT NULL,PRIMARY KEY(meet,trial_date,trial_race_no,horse_number),
        FOREIGN KEY(meet,trial_date,trial_race_no) REFERENCES trial(meet,trial_date,trial_race_no));
      CREATE INDEX trial_result_horse_date ON trial_result(official_hr_no,trial_date);
      CREATE TABLE candidate_evidence(meet INTEGER NOT NULL,trial_date TEXT NOT NULL,
        trial_race_no INTEGER NOT NULL,horse_number INTEGER NOT NULL,official_hr_no TEXT NOT NULL,
        profile_meet INTEGER NOT NULL,profile_name TEXT NOT NULL,profile_sex TEXT,
        birthday TEXT,age_year_offset INTEGER,sex_relation TEXT,race_age_support INTEGER NOT NULL,
        race_name_support INTEGER NOT NULL,profile_source_path TEXT NOT NULL,profile_source_row INTEGER NOT NULL,
        PRIMARY KEY(meet,trial_date,trial_race_no,horse_number,official_hr_no));
      CREATE TABLE trial_person_link(meet INTEGER NOT NULL,trial_date TEXT NOT NULL,
        trial_race_no INTEGER NOT NULL,horse_number INTEGER NOT NULL,
        actor_type TEXT NOT NULL CHECK(actor_type IN ('jockey','trainer')),
        actor_name_raw TEXT,linked_official_id TEXT,candidate_ids_json TEXT NOT NULL,
        link_status TEXT NOT NULL,support_race_date TEXT,support_race_no INTEGER,
        PRIMARY KEY(meet,trial_date,trial_race_no,horse_number,actor_type));
      CREATE TABLE research_entry_trial(meet INTEGER NOT NULL CHECK(meet=1),race_date TEXT NOT NULL,
        race_no INTEGER NOT NULL,hr_no TEXT NOT NULL,prior_trial_count INTEGER,
        prior_trial_180d INTEGER,prior_pass_count INTEGER,prior_practice_count INTEGER,
        last_trial_date TEXT,last_trial_judgement TEXT,last_trial_state TEXT,
        source_status TEXT NOT NULL,PRIMARY KEY(meet,race_date,race_no,hr_no));
    """)


def build(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    files = sorted(RAW.rglob("*.rpt"))
    prior_audit = json.loads(COLLECTION_AUDIT.read_text())["meets"]["1"]
    if (prior_audit["source_entries"] != len(files) + 1
            or prior_audit["statuses"].get("skipped_duplicate_sha256") != 1):
        raise ValueError("dacom23 collection inventory changed from the sealed audit")
    profiles, profile_paths = load_profiles()
    history = sqlite3.connect(f"file:{HISTORY.resolve()}?mode=ro", uri=True)
    race_by_horse: dict[str, list[tuple]] = defaultdict(list)
    person_by_name: dict[str, dict[str, set[str]]] = {
        "jockey": defaultdict(set), "trainer": defaultdict(set)}
    for row in history.execute("""SELECT hr_no,race_date,race_no,horse_name,horse_sex_raw,
        horse_age_raw,jockey_no,jockey_name,trainer_no,trainer_name FROM entry WHERE meet=1"""):
        race_by_horse[row[0]].append(row[1:])
        if row[6] and row[7]:
            person_by_name["jockey"][norm(row[7])].add(row[6])
        if row[8] and row[9]:
            person_by_name["trainer"][norm(row[9])].add(row[8])
    target = output / "trials.sqlite3"
    temporary = output / ".trials.sqlite3.tmp"
    if temporary.exists():
        temporary.unlink()
    db = sqlite3.connect(temporary)
    create_schema(db)
    stats = Counter()
    yearly: dict[str, Counter] = defaultdict(Counter)
    for path in files:
        raw = path.read_bytes()
        text = normalized_report(raw)
        parsed = parse_running_trial_report(text, meet=1)
        blocks = report_blocks(text)
        if len(blocks) != len(parsed):
            raise ValueError(f"Trial block mismatch {path}: {len(blocks)} != {len(parsed)}")
        file_day = path.name[:8]
        source_date = f"{file_day[:4]}-{file_day[4:6]}-{file_day[6:]}"
        title_era = ("ability_inspection" if "능력검사성적" in decode_running_trial_report(raw)
                     else "running_inspection" if "주행검사성적" in decode_running_trial_report(raw)
                     else "running_trial")
        db.execute("INSERT INTO source_file VALUES(?,?,?,?,?,?,?)",
                   (str(path), hashlib.sha256(raw).hexdigest(), len(raw), source_date,
                    title_era, len(parsed), sum(len(t.results) for t in parsed)))
        yearly[file_day[:4]]["files"] += 1
        for block_no, (trial, block) in enumerate(zip(parsed, blocks, strict=True)):
            day = trial.trial_date.isoformat()
            if day != source_date:
                stats["file_event_date_differs"] += 1
            key = (1, day, trial.trial_race_number)
            db.execute("INSERT INTO trial VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (*key, trial.trial_round, trial.distance_m, trial.weather,
                        trial.track_condition, trial.track_moisture_percent,str(path),block_no))
            yearly[day[:4]]["trials"] += 1
            meta_lines = table_lines(block, "연령")
            result_lines = table_lines(block, "마체중")
            section_lines = table_lines(block, "G-3")
            if len(meta_lines) != len(trial.results):
                raise ValueError(f"Metadata parse coverage mismatch: {path} block {block_no}")
            if result_lines and set(result_lines) != set(meta_lines):
                raise ValueError(f"Result table horse-number mismatch: {path} block {block_no}")
            for item in trial.results:
                number = item.horse_number
                metadata_line = meta_lines[number]
                result_line = result_lines.get(number)
                section_line = section_lines.get(number)
                raw_rank = item.finish_rank_raw or metadata_line.split()[0]
                time_match = re.search(r"(?<!\d)(\d+:\d\d\.\d)(?!\d)", result_line or "")
                fallback_time = None
                if time_match:
                    minute, seconds = time_match.group(1).split(":")
                    fallback_time = round((int(minute) * 60 + float(seconds)) * 1000)
                finish_time = item.finish_time_ms if item.finish_time_ms is not None else fallback_time
                if "연습주행" in (result_line or "") or "주행연습" in (result_line or ""):
                    result_state = "practice_run"
                elif raw_rank in {"95", "99"} or "출주취소" in (result_line or ""):
                    result_state = "cancelled"
                elif raw_rank in {"93", "94"}:
                    result_state = "excluded"
                elif raw_rank == "92":
                    result_state = "stopped"
                elif raw_rank == "91":
                    result_state = "disqualified"
                elif finish_time and finish_time > 0:
                    result_state = "timed_trial"
                else:
                    result_state = "untimed_or_special"
                all_candidates = profiles.get(norm(item.horse_name), [])
                candidates = []
                for p in all_candidates:
                    sex_relation = ("exact" if p["sex"] == item.sex else "later_gelding_possible"
                                    if item.sex == "수" and p["sex"] == "거" else "conflict")
                    offset = p["birth_year"] - (trial.trial_date.year - item.age)
                    race_rows = race_by_horse.get(p["id"], [])
                    age_support = sum(r[4] == item.age and abs((date.fromisoformat(r[0]) - trial.trial_date).days) <= 180
                                      for r in race_rows)
                    name_support = sum(norm(r[2]) == norm(item.horse_name) for r in race_rows)
                    if sex_relation != "conflict" and abs(offset) <= 1:
                        candidates.append((p, offset, sex_relation, age_support, name_support))
                candidate_ids = sorted({p["id"] for p, *_ in candidates})
                chosen = None
                status = "unmatched_profile" if not all_candidates else "signature_conflict"
                if len(candidate_ids) > 1:
                    status = "ambiguous_multiple_profiles"
                elif len(candidate_ids) == 1:
                    chosen = candidates[0]
                    p, offset, sex_relation, age_support, name_support = chosen
                    if offset == 0:
                        status = "linked_profile_signature"
                    elif age_support and name_support:
                        status = "linked_race_age_corroborated"
                    else:
                        status = "ambiguous_historical_age"
                linked = status.startswith("linked_")
                official_id = chosen[0]["id"] if linked and chosen else None
                evidence = {"profile_candidates": len(candidate_ids), "profile_name_candidates": len(all_candidates),
                            "age_year_offset": chosen[1] if chosen else None,
                            "sex_relation": chosen[2] if chosen else None,
                            "race_age_support": chosen[3] if chosen else None,
                            "race_name_support": chosen[4] if chosen else None}
                db.execute("INSERT INTO trial_result VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (*key, number, item.horse_name,item.sex,item.age,item.origin_country,
                            item.jockey_name,item.trainer_name,item.body_weight_kg,raw_rank,
                            finish_time,item.judgement,item.failure_reason,item.inspection_reason,
                            item.g3f_ms,item.s1f_ms,item.corner_3_ms,item.corner_4_ms,item.g1f_ms,
                            item.passing_order_raw,result_state,metadata_line,result_line,section_line,
                            official_id,status,json.dumps(candidate_ids,ensure_ascii=False),
                            json.dumps(evidence,ensure_ascii=False,sort_keys=True)))
                for p, offset, sex_relation, age_support, name_support in candidates:
                    db.execute("INSERT INTO candidate_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                               (*key,number,p["id"],p["meet"],p["name"],p["sex"],p["birthday"],
                                offset,sex_relation,age_support,name_support,p["path"],p["row"]))
                stats[status] += 1
                stats[result_state] += 1
                yearly[day[:4]]["rows"] += 1
                yearly[day[:4]][status] += 1
    unresolved_rows = list(db.execute("""SELECT trial_date,trial_race_no,horse_number,
        horse_name_raw,horse_link_status,candidate_ids_json,evidence_json
        FROM trial_result WHERE official_hr_no IS NULL"""))
    unresolved_names = sorted({r[3] for r in unresolved_rows})
    training_by_name: dict[str, list[tuple]] = defaultdict(list)
    if unresolved_names:
        placeholders = ",".join("?" for _ in unresolved_names)
        for event in history.execute(f"""SELECT event_date,hr_no,horse_name,source_path,source_row
            FROM training_event WHERE source_type='horse_training'
              AND horse_name IN ({placeholders})""", unresolved_names):
            training_by_name[event[2]].append(event)
    training_paths: set[Path] = set()
    training_raw_cache: dict[str, list[dict]] = {}
    for day, race_no, horse_no, name, old_status, candidate_json, evidence_json in unresolved_rows:
        trial_day = date.fromisoformat(day)
        nearby = [r for r in training_by_name[name]
                  if abs((date.fromisoformat(r[0]) - trial_day).days) <= 90]
        nearby_ids = {r[1] for r in nearby}
        candidate_ids = set(json.loads(candidate_json))
        if len(nearby_ids) != 1 or not nearby_ids <= candidate_ids:
            continue
        official_id = next(iter(nearby_ids))
        selected_event = min((r for r in nearby if r[1] == official_id),
                             key=lambda r: abs((date.fromisoformat(r[0]) - trial_day).days))
        new_status = ("linked_training_disambiguated" if old_status == "ambiguous_multiple_profiles"
                      else "linked_training_date_corroborated")
        source_path = selected_event[3]
        if source_path not in training_raw_cache:
            training_raw_cache[source_path] = json.loads(Path(source_path).read_bytes())["response"]["body"]["items"]["item"]
        original = training_raw_cache[source_path][selected_event[4]]
        if (str(original.get("trDate")) != selected_event[0].replace("-", "")
                or str(original.get("hrNo")).zfill(7) != official_id
                or norm(original.get("hrName")) != norm(name)):
            raise ValueError(f"Training raw row mismatch for {day} {name}")
        training_paths.add(Path(source_path))
        evidence = json.loads(evidence_json)
        evidence["training_event_date"] = selected_event[0]
        evidence["training_source_path"] = selected_event[3]
        evidence["training_source_row"] = selected_event[4]
        evidence["training_nearby_rows"] = len(nearby)
        db.execute("""UPDATE trial_result SET official_hr_no=?,horse_link_status=?,evidence_json=?
            WHERE meet=1 AND trial_date=? AND trial_race_no=? AND horse_number=?""",
            (official_id,new_status,json.dumps(evidence,ensure_ascii=False,sort_keys=True),day,race_no,horse_no))
        stats[old_status] -= 1
        stats[new_status] += 1
        yearly[day[:4]][old_status] -= 1
        yearly[day[:4]][new_status] += 1
    for day, race_no, horse_no, hr, jockey_name, trainer_name in db.execute("""SELECT
        trial_date,trial_race_no,horse_number,official_hr_no,jockey_name_raw,trainer_name_raw
        FROM trial_result ORDER BY trial_date,trial_race_no,horse_number"""):
        for kind, name, id_index, name_index in (
            ("jockey", jockey_name, 5, 6), ("trainer", trainer_name, 7, 8)):
            candidates = sorted(person_by_name[kind].get(norm(name), set()))
            nearby = [r for r in race_by_horse.get(hr or "", [])
                      if abs((date.fromisoformat(r[0]) - date.fromisoformat(day)).days) <= 90
                      and r[id_index] and norm(r[name_index]) == norm(name)]
            supported = {r[id_index] for r in nearby}
            if len(supported) == 1:
                linked_id = next(iter(supported))
                support = min((r for r in nearby if r[id_index] == linked_id),
                              key=lambda r: abs((date.fromisoformat(r[0]) - date.fromisoformat(day)).days))
                status = "corroborated_same_horse_nearby_race"
            else:
                linked_id = None
                support = None
                status = ("ambiguous_nearby_races" if len(supported) > 1 else
                          "horse_unlinked" if not hr else
                          "ambiguous_name" if len(candidates) > 1 else
                          "single_name_candidate_unconfirmed" if candidates else "name_unmatched")
            db.execute("INSERT INTO trial_person_link VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (1,day,race_no,horse_no,kind,name,linked_id,
                        json.dumps(candidates,ensure_ascii=False),status,
                        support[0] if support else None,support[1] if support else None))
            stats[f"person_{kind}_{status}"] += 1
    history_rows = list(history.execute("SELECT meet,race_date,race_no,hr_no FROM entry ORDER BY race_date,race_no,hr_no"))
    trial_by_horse: dict[str, list[tuple]] = defaultdict(list)
    for hr,day,judgement,state in db.execute("SELECT official_hr_no,trial_date,judgement_raw,result_state FROM trial_result WHERE official_hr_no IS NOT NULL ORDER BY trial_date"):
        trial_by_horse[hr].append((day,judgement,state))
    for meet, race_day, race_no, hr in history_rows:
        events = trial_by_horse.get(hr, [])
        prior = [e for e in events if e[0] < race_day]
        recent = [e for e in prior if (date.fromisoformat(race_day) - date.fromisoformat(e[0])).days <= 180]
        status = ("source_unavailable" if race_day < "2003-07-03" else
                  "linked_prior_trial" if prior else "no_linked_prior_trial_observed")
        db.execute("INSERT INTO research_entry_trial VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (meet,race_day,race_no,hr,None if status=="source_unavailable" else len(prior),
                    None if status=="source_unavailable" else len(recent),
                    None if status=="source_unavailable" else sum(e[1]=="합" for e in prior),
                    None if status=="source_unavailable" else sum(e[2]=="practice_run" for e in prior),
                    prior[-1][0] if prior else None,prior[-1][1] if prior else None,
                    prior[-1][2] if prior else None,status))
    history.close()
    db.commit()
    if db.execute("PRAGMA quick_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("Trial database integrity failure")
    counts = {name: db.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in
              ("source_file","trial","trial_result","candidate_evidence","trial_person_link","research_entry_trial")}
    source_counts = dict(db.execute("SELECT source_status,count(*) FROM research_entry_trial GROUP BY source_status"))
    if counts["source_file"] != len(files) or counts["research_entry_trial"] != len(history_rows):
        raise ValueError(f"Coverage failure: {counts}")
    db.close()
    temporary.replace(target)
    with (output / "coverage_year.csv").open("w",encoding="utf-8",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(["year","files","trials","rows","linked_profile_signature","linked_race_age_corroborated",
                         "linked_training_date_corroborated","linked_training_disambiguated",
                         "ambiguous_historical_age","ambiguous_multiple_profiles","signature_conflict","unmatched_profile"])
        for year in (str(y) for y in range(2000,2027)):
            c=yearly[year]
            writer.writerow([year]+[c[k] for k in ("files","trials","rows","linked_profile_signature",
                          "linked_race_age_corroborated","linked_training_date_corroborated",
                          "linked_training_disambiguated","ambiguous_historical_age","ambiguous_multiple_profiles",
                          "signature_conflict","unmatched_profile")])
    read=sqlite3.connect(f"file:{target.resolve()}?mode=ro",uri=True)
    with (output / "unresolved_horse_link.csv").open("w",encoding="utf-8",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(["trial_date","trial_race_no","horse_number","horse_name_raw","sex_raw","age_raw",
                         "horse_link_status","candidate_ids_json","evidence_json"])
        writer.writerows(read.execute("""SELECT trial_date,trial_race_no,horse_number,horse_name_raw,sex_raw,age_raw,
          horse_link_status,candidate_ids_json,evidence_json FROM trial_result WHERE official_hr_no IS NULL
          ORDER BY trial_date,trial_race_no,horse_number"""))
    read.close()
    operating=sqlite3.connect(f"file:{OPERATING.resolve()}?mode=ro",uri=True)
    old_rows=list(operating.execute("""SELECT t.trial_date_local,t.trial_race_number,
        r.horse_number,h.kra_horse_id FROM running_trial_results r
        JOIN running_trials t ON t.id=r.running_trial_id
        LEFT JOIN horses h ON h.id=r.horse_id WHERE t.meet_code=1
        ORDER BY t.trial_date_local,t.trial_race_number,r.horse_number"""))
    operating.close()
    old_map={(d,n,ch):hr for d,n,ch,hr in old_rows}
    current=sqlite3.connect(f"file:{target.resolve()}?mode=ro",uri=True)
    new_map={(d,n,ch):hr for d,n,ch,hr in current.execute("""SELECT
        trial_date,trial_race_no,horse_number,official_hr_no FROM trial_result
        WHERE trial_date>='2025-01-01'""")}
    current.close()
    overlapping=old_map.keys() & new_map.keys()
    overlap={"operating_rows":len(old_map),"new_rows":len(new_map),
             "key_gaps_new_only":len(new_map.keys()-old_map.keys()),
             "key_gaps_operating_only":len(old_map.keys()-new_map.keys()),
             "both_linked_id_agree":sum(bool(old_map[k]) and old_map[k]==new_map[k] for k in overlapping),
             "both_linked_id_disagree":sum(bool(old_map[k]) and bool(new_map[k]) and old_map[k]!=new_map[k] for k in overlapping),
             "new_linked_old_unlinked":sum(bool(new_map[k]) and not old_map[k] for k in overlapping),
             "old_linked_new_unlinked":sum(bool(old_map[k]) and not new_map[k] for k in overlapping)}
    if overlap["key_gaps_new_only"] or overlap["key_gaps_operating_only"] or overlap["both_linked_id_disagree"]:
        raise ValueError(f"Operating 2025+ overlap discrepancy: {overlap}")
    selected_old_hash=hashlib.sha256()
    for row in old_rows:
        selected_old_hash.update(json.dumps(row,ensure_ascii=False,separators=(",",":")).encode()+b"\n")
    overlap["operating_selected_rows_sha256"]=selected_old_hash.hexdigest()
    summary={"meet":1,"first_file":"2003-07-03","last_file":max(p.name[:8] for p in files),
             "source_listing_entries":prior_audit["source_entries"],
             "duplicate_sha256_skipped":prior_audit["statuses"]["skipped_duplicate_sha256"],
             "counts":counts,"link_status":dict(sorted((k,v) for k,v in stats.items() if k.startswith(("linked_","ambiguous_","signature_","unmatched_")))),
             "result_state":{k:stats[k] for k in ("timed_trial","practice_run","cancelled",
                                                  "excluded","stopped","disqualified","untimed_or_special")},
             "file_event_date_differences":stats["file_event_date_differs"],
             "person_link_status":dict(sorted((k,v) for k,v in stats.items() if k.startswith("person_"))),
             "research_entry_source_status":source_counts,
             "operating_2025_plus_overlap":overlap,
             "profile_snapshot":"2026-08-28 full all-horse API; retrospective identity evidence",
             "asof_limit":"dacom23 historic posting time not verified; only earlier trial dates appear in research_entry_trial"}
    (output/"validation.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    linked=sum(v for k,v in summary["link_status"].items() if k.startswith("linked_"))
    unresolved=counts["trial_result"]-linked
    report=f"""# 서울 주행심사 전 기간 연구 연결

서울 `dacom23` 목록 {prior_audit['source_entries']:,}건 중 동일 SHA 중복 1건을
제외한 보존 원문 **{len(files):,}개 파일**을 2003-07-03~2026-09-10
전수 파싱해 **{counts['trial']:,}개 심사/검사 경주, {counts['trial_result']:,}개 말별 행**을
`trials.sqlite3`로 만들었다. 원문의 `능력검사`·`주행검사`·`주행심사` 제목과
`선수명/감독명` 표 머리글 차이를 복원했다. 파일일과 사건일이 다른 블록은
{stats['file_event_date_differs']}개이며 양쪽 날짜를 따로 보존했다.
2000-01-01~2003-07-02는 보존된 `dacom23` 주행심사 원천이 없다.

공식 말 프로필 전체 원문(2026-08-28, 서울·제주·부경)을 마명·성별·
생년월일/당시 나이와 대조했다. 프로필의 현재 `거`는 심사 당시 `수`에서
변경됐을 수 있어 별도 근거로 표시한다. 정확한 생년 일치
{stats['linked_profile_signature']:,}행, 과거 나이 표기 차이를 가까운 공식
경주로 확인한 {stats['linked_race_age_corroborated']:,}행, 같은 이름의
일별 조교 공식 ID를 심사일 ±90일 안에서 대조한
{stats['linked_training_date_corroborated']+stats['linked_training_disambiguated']:,}행을
연결했다. 합계 **{linked:,}/{counts['trial_result']:,}행**이며 나머지
**{unresolved:,}행**은 `unresolved_horse_link.csv`에 후보와 이유를 남겼다.
이 연결은 당시 주행심사 원문에 공식 `hrNo`가 없어서 여러 공식 원천으로
사후 대조한 결과다. 근거가 부족한 마명만의 동일시는 승인하지 않았다.

`trial_result`는 원문 표의 메타·결과·구간 줄과 원문 순위·판정·기록을 보존한다.
시간기록 심사 {stats['timed_trial']:,}, 연습주행 {stats['practice_run']:,},
취소 {stats['cancelled']:,}, 제외 {stats['excluded']:,},
주행중지 {stats['stopped']:,}, 실격 {stats['disqualified']:,},
미분류 {stats['untimed_or_special']:,}행을 별도 상태로 보관한다.
판정 `합/불`은 `judgement_raw`이고 일반 경주의 착순이나 레이블로 섞지 않는다.

기수·조교사는 원문에 이름만 있다. 같은 말의 ±90일 공식 경주에서 이름·번호가
함께 확인된 관계만 `trial_person_link`에 보수적으로 연결했다:
기수 {stats['person_jockey_corroborated_same_horse_nearby_race']:,},
조교사 {stats['person_trainer_corroborated_same_horse_nearby_race']:,}행.
그 외는 후보만 보관한다. `dacom23`에는 마주 정보가 없어 마주 ID를
만들지 않았다. 가까운 경주의 사람 관계는 심사 당시 동일 인물의 직접
ID 표시가 아니므로 `corroborated` 상태로 구분한다.

`research_entry_trial`은 서울 백필의 {counts['research_entry_trial']:,}개
경주·말 키 모두에 대해 **경주일보다 앞선** 연결 주행심사 이력만 담는다.
출전행 {counts['research_entry_trial']:,}개 중 원천 시작 전은
{source_counts['source_unavailable']:,}개로
`source_unavailable`이며 0건으로 채우지 않았다. `prior_trial_count`는
연습·취소·제외까지 포함한 보고서 출전 건수이고,
`prior_pass_count`와 `prior_practice_count`를 별도로 제공한다.
당시 게시/관측 시각은 확인되지 않았으므로 이 표의 날짜 선후만으로
특정 예측 마감시각에 이용 가능했다고 보장하지 않는다.

2025년 이후 운영 DB 주행심사 {overlap['operating_rows']:,}행과
경주일·심사번호·마번 키가 전부 일치했다. 양쪽 공식 말 ID가 있는
{overlap['both_linked_id_agree']:,}행은 모두 일치하고 새 자료에서만
1행이 추가로 연결됐다. 운영 DB·모델·registry와 제주·부경 산출물은
수정하지 않았다.

프로젝트 루트에서 `.venv/bin/python scripts/build_seoul_running_trials.py`로
재현한다. `coverage_year.csv`, `unresolved_horse_link.csv`,
`validation.json`, `sha256_manifest.csv`가 연도별 수치·미해결·무결성·
입력/출력 해시를 제공한다. `trials.sqlite3`의 원문 경로와 블록 번호,
`candidate_evidence`의 공식 프로필 페이지·행 번호를 따라 원문을 재검사할 수 있다.
"""
    (output/"REPORT.md").write_text(report)
    manifest_files=[*files,*profile_paths,*sorted(training_paths),HISTORY,OPERATING,COLLECTION_AUDIT,
                    Path("data/raw/kra_text/_manifests/dacom23/manifest.jsonl"),
                    Path(__file__),target,output/"coverage_year.csv",
                    output/"unresolved_horse_link.csv",output/"validation.json",output/"REPORT.md"]
    with (output/"sha256_manifest.csv").open("w",encoding="utf-8",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(["path","bytes","sha256"])
        writer.writerows((str(p),p.stat().st_size,sha(p)) for p in manifest_files)
    return summary


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=OUTPUT)
    args=parser.parse_args()
    print(json.dumps(build(args.output),ensure_ascii=False,indent=2))
