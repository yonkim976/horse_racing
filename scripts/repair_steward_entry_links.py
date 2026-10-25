"""Restore ONLY the 837 archived special-outcome runners behind 928 unlinked phrases.

No source/model/SQLite/schema changes. --inspect is read-only on Supabase and
creates a frozen local plan; --apply --plan PATH verifies it again and commits
entries, special results and phrase links atomically. Replays do not overwrite.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.engine import make_url

from horse_racing.db.models import IngestionRun, RaceEntry, RaceResult, SourceDocument

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
ARCHIVES = ROOT / "thoroughbred/research/20260929_calendar_api_v1"
ARTIFACTS = ROOT / "data/research"
SOURCE_PHRASE_HASH = "396d7c3fb3ef8c272e154e18ee439c8a9acb8e0001e0e2fa339d2517dfb1a83a"
LABELS = {91: "실격", 92: "주행중지", 93: "출발제외", 94: "출전제외", 95: "출전취소"}
ZERO_CASES = {
    (1, "2018-07-29", 9, "0038060", 10): ("클린업히어로", "출전취소"),
    (1, "2018-06-02", 5, "0035891", 10): ("골드스타힐스", "출전제외"),
}
ENTRY_FIELDS = (
    "race_id",
    "horse_id",
    "horse_number",
    "jockey_id",
    "trainer_id",
    "owner_id",
    "carried_weight_kg",
    "body_weight_kg",
    "body_weight_change_kg",
    "rating",
    "scratched",
)
RESULT_FIELDS = ("finish_position", "finish_time_ms", "rank_remark", "disqualified")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    # Generated audit artifacts, never overwrite an existing receipt/backup.
    with path.open("x", encoding="utf-8") as f:
        f.write(encoded(value) + "\n")


def connect_engine():
    # Reuse the already validated production writer credentials, not dashboard credentials.
    from horse_racing.jobs.local_race_day import load_settings

    settings = load_settings()
    url = make_url(settings.database_url)
    require(url.database == "postgres", "unexpected_database")
    return create_engine(
        url.set(drivername="postgresql+psycopg"),
        pool_size=1,
        max_overflow=0,
        hide_parameters=True,
        pool_pre_ping=True,
    )


def phrase_rows(c, ids=None, *, lock=False):
    sql = """SELECT p.*,h.kra_horse_id,h.name_ko,r.race_date_local,r.race_number,
        rc.kra_meet_code FROM public.horse_steward_phrases p
        JOIN public.horses h ON h.id=p.horse_id JOIN public.races r ON r.id=p.race_id
        JOIN public.racecourses rc ON rc.id=r.racecourse_id
        WHERE """ + ("p.id=ANY(:ids)" if ids is not None else "p.race_entry_id IS NULL")
    # The SQL fragment above has only two fixed internal choices, no user SQL.
    sql += " ORDER BY p.id" + (" FOR UPDATE OF p" if lock else "")
    return [dict(r) for r in c.execute(text(sql), {"ids": ids} if ids else {}).mappings()]


def group_phrases(phrases):
    require(len(phrases) == 928, "expected_928_phrases")
    groups = defaultdict(list)
    for p in phrases:
        require(p["source_dataset_sha256"] == SOURCE_PHRASE_HASH, "unexpected_phrase_source")
        require(p["kra_meet_code"] in (1, 3), "unexpected_venue")
        require("2017-09-30" <= str(p["race_date_local"]) <= "2024-12-22", "unexpected_date")
        require(
            hashlib.sha256(p["phrase_text"].encode()).hexdigest() == p["phrase_sha256"],
            "changed_phrase_hash",
        )
        key = (
            p["kra_meet_code"],
            str(p["race_date_local"]),
            p["race_number"],
            p["kra_horse_id"],
            p["historical_program"],
        )
        groups[key].append(p)
    require(len(groups) == 837, "expected_837_runner_keys")
    return groups


def checked_archive_path(name):
    path = (ROOT / name).resolve()
    require(
        path.is_relative_to((ARCHIVES / "raw/race_execution_probe").resolve()),
        "unexpected_archive_path",
    )
    require(path.is_file() and path.suffix == ".gz", "missing_archive")
    return path


def source_rows(groups):
    # Read-only DuckDB locates original API rows; raw archived payload is authoritative.
    with duckdb.connect(str(CORE), read_only=True) as db:
        cols = [d[0] for d in db.execute("SELECT * FROM runner_results LIMIT 0").description]
        candidates = db.execute(
            "SELECT * FROM runner_results WHERE result_rank_raw IN ('0','91','92','93','94','95')"
        ).fetchall()
    wanted = {}
    for row in candidates:
        r = dict(zip(cols, row))
        raw_day = r["result_date"]
        day = f"{raw_day[:4]}-{raw_day[4:6]}-{raw_day[6:]}"
        key = (
            int(r["source_meet"]),
            day,
            int(r["result_race_no"]),
            r["horse_id_raw"],
            int(r["horse_program_no_raw"]),
        )
        if key in groups:
            require(key not in wanted, "duplicate_official_source_key")
            wanted[key] = r
    require(set(wanted) == set(groups), "official_source_missing")
    manifest = json.loads((ARCHIVES / "manifest.json").read_text())
    declared = {r["path"]: r for r in manifest["sources"]}
    raw_by_file, sources, output = defaultdict(list), [], {}
    for key, r in wanted.items():
        raw_by_file[r["source_file"]].append((key, r))
    for filename, rows in sorted(raw_by_file.items()):
        path = checked_archive_path(filename)
        require(filename in declared, "archive_not_in_manifest")
        archive_sha = file_hash(path)
        # Calendar manifest hashes the decompressed HTTP payload, not its gzip container.
        with gzip.open(path, "rb") as f:
            body = f.read()
        sha = hashlib.sha256(body).hexdigest()
        require(sha == declared[filename]["sha256"], "archive_payload_hash_changed")
        payload = json.loads(body)
        response = payload["response"]
        require(str(response["header"]["resultCode"]) in ("00", "0000"), "api_source_error")
        items = response["body"]["items"]["item"]
        require(
            isinstance(items, list) and len(items) == int(response["body"]["totalCount"]),
            "incomplete_api_archive",
        )
        for key, r in rows:
            index = int(r["source_item_index"])
            require(0 <= index < len(items), "source_index_out_of_range")
            item = items[index]
            require(
                str(item["hrNo"]) == key[3]
                and int(item["chulNo"]) == key[4]
                and int(item["rcNo"]) == key[2]
                and str(item["rcDate"]) == key[1].replace("-", "")
                and str(item["ord"]) == r["result_rank_raw"],
                "raw_runner_identity_conflict",
            )
            # Meet is checked against original request manifest, never inferred by name.
            require(int(declared[filename]["request_meet"]) == key[0], "source_meet_conflict")
            output[key] = {
                "item": item,
                "source_file": filename,
                "source_sha256": sha,
                "source_item_index": index,
            }
        sources.append(
            {"path": filename, "sha256": sha, "archive_sha256": archive_sha, "rows": len(rows)}
        )
    return output, sources


def verify_zero_case(key, folder):
    name, label = ZERO_CASES[key]
    params = {
        "Act": "04",
        "Sub": "1",
        "meet": key[0],
        "realRcDate": key[1].replace("-", ""),
        "realRcNo": key[2],
        "rcDate": key[1].replace("-", ""),
        "rcNo": key[2],
    }
    r = httpx.get(
        "https://race.kra.co.kr/raceScore/ScoretableDetailList.do",
        params=params,
        timeout=30,
        follow_redirects=False,
    )
    require(r.status_code == 200 and len(r.content) < 8 * 1024**2, "score_page_unavailable")
    soup = BeautifulSoup(r.content, "html.parser")
    rows = [
        [n.get_text(" ", strip=True) for n in tr.find_all(["td", "th"], recursive=False)]
        for tr in soup.select("table tr")
    ]
    require(
        any(len(row) >= 4 and row[:4] == ["말", str(key[4]), name, label] for row in rows),
        "zero_rank_status_not_verified",
    )
    # Page selection must show the requested date and the runner on its result table.
    selected = []
    for node in soup.select("div.tableType1"):
        match = re.search(
            r"(\d{4})년\s*(\d+)월\s*(\d+)일.*?제\s*(\d+)경주", node.get_text(" ", strip=True), re.S
        )
        if match:
            selected.append(tuple(map(int, match.groups())))
    y, m, d = map(int, key[1].split("-"))
    require(selected == [(y, m, d, key[2])], "zero_page_date_conflict")
    meet_input = soup.select_one('input#meet[name="meet"]')
    require(
        meet_input is not None and meet_input.get("value") == str(key[0]), "zero_page_meet_conflict"
    )
    require(
        any(len(row) > 2 and row[1:3] == [str(key[4]), name] for row in rows),
        "zero_page_runner_missing",
    )
    filename = f"zero_{key[1]}_{key[2]}.html"
    with (folder / filename).open("xb") as f:
        f.write(r.content)
    return {
        "key": list(key),
        "label": label,
        "url": str(r.url),
        "path": filename,
        "sha256": hashlib.sha256(r.content).hexdigest(),
        "verified_at_ms": time.time_ns() // 1000000,
    }


def positive(value):
    if value in (None, "", "-"):
        return None
    n = Decimal(str(value))
    require(n.is_finite() and n >= 0, "invalid_numeric_value")
    return float(n) if n > 0 else None


def normalize(item, *, zero_label=None):
    code = int(item["ord"])
    require(
        code in LABELS or (code == 0 and zero_label in {"출전취소", "출전제외"}),
        "not_a_verified_special_outcome",
    )
    label = zero_label if code == 0 else LABELS[code]
    weight = str(item.get("wgHr") or "")
    match = re.fullmatch(r"(\d*)\(([+-]?\d+)?\)", weight)
    require(not weight or weight in ("0", "-") or match is not None, "unknown_body_weight_format")
    kg = int(match[1]) if match and match[1] and int(match[1]) > 0 else None
    delta = int(match[2]) if kg is not None and match[2] is not None else None
    seconds = positive(item.get("rcTime"))
    return {
        "entry": {
            "horse_number": int(item["chulNo"]),
            "carried_weight_kg": positive(item.get("wgBudam")),
            "body_weight_kg": kg,
            "body_weight_change_kg": delta,
            "rating": positive(item.get("rating")),
            "scratched": code in (93, 94, 95) or code == 0,
        },
        # No source-dependent code is treated as a normal placing or a common enum.
        "result": {
            "finish_position": None,
            "finish_time_ms": int(Decimal(str(item["rcTime"])) * 1000) if seconds else None,
            "rank_remark": label,
            "disqualified": code == 91,
        },
        "source_outcome_code": code,
    }


def build_plan(c, phrases, folder):
    groups = group_phrases(phrases)
    raw, sources = source_rows(groups)
    people = {}
    c.execute(text("SET TRANSACTION READ ONLY"))
    for kind, table, field in (
        ("jockey", "jockeys", "kra_jockey_id"),
        ("trainer", "trainers", "kra_trainer_id"),
        ("owner", "owners", "kra_owner_id"),
    ):
        # Only fixed internal identifiers; no CLI identifier can enter SQL.
        people[kind] = dict(c.execute(text(f"SELECT {field},id FROM public.{table}")).all())
    c.rollback()  # no DB transaction is held while fetching the two official score pages
    zero_evidence, records, unresolved = [], [], Counter()
    for key, pp in sorted(groups.items()):
        source = raw[key]
        item = source["item"]
        zero_label = None
        if int(item["ord"]) == 0:
            require(key in ZERO_CASES, "unexpected_zero_rank_key")
            evidence = verify_zero_case(key, folder)
            zero_evidence.append(evidence)
            zero_label = evidence["label"]
        normalized = normalize(item, zero_label=zero_label)
        entry = normalized["entry"]
        entry.update(race_id=pp[0]["race_id"], horse_id=pp[0]["horse_id"])
        for role, raw_field in (("jockey", "jkNo"), ("trainer", "trNo"), ("owner", "owNo")):
            official = str(item.get(raw_field) or "")
            person = people[role].get(official)
            entry[role + "_id"] = person
            if person is None:
                unresolved[role] += 1
        records.append(
            {"key": list(key), **normalized, "source": source, "phrase_ids": [p["id"] for p in pp]}
        )
    require(sum(len(r["phrase_ids"]) for r in records) == 928, "plan_scope_changed")
    return {
        "version": 1,
        "project_ref": "xkykmhhkjtosptoibduo",
        "generated_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
        "phrases_before": phrases,
        "records": records,
        "sources": sources,
        "zero_evidence": zero_evidence,
        "unresolved_person_ids": dict(unresolved),
        "normal_finish_positions_created": 0,
        "normalization": "special outcome -> NULL placing + named status; original ord retained in source",
        "deferred_race_id": 55251,
    }


def validate_plan(plan, folder):
    require(plan["project_ref"] == "xkykmhhkjtosptoibduo" and plan["version"] == 1, "wrong_plan")
    groups = group_phrases(plan["phrases_before"])
    require(len(plan["records"]) == 837, "invalid_plan_record_count")
    raw, sources = source_rows(groups)
    require(sources == plan["sources"], "changed_archive_set")
    evidence = {tuple(e["key"]): e for e in plan["zero_evidence"]}
    for e in evidence.values():
        require(e["path"] == f"zero_{e['key'][1]}_{e['key'][2]}.html", "unexpected_evidence_path")
        require(file_hash(folder / e["path"]) == e["sha256"], "changed_zero_evidence")
    keys = set()
    for record in plan["records"]:
        key = tuple(record["key"])
        require(key not in keys and key in groups, "duplicate_or_unexpected_plan_key")
        keys.add(key)
        require(record["source"] == raw[key], "plan_source_modified")
        zero = evidence.get(key)
        if zero:
            require(ZERO_CASES[key][1] == zero["label"], "zero_label_changed")
        normalized = normalize(raw[key]["item"], zero_label=zero["label"] if zero else None)
        require(record["result"] == normalized["result"], "modified_result_plan")
        require(
            all(record["entry"][k] == v for k, v in normalized["entry"].items()),
            "modified_entry_plan",
        )
        pp = groups[key]
        require(
            record["entry"]["race_id"] == pp[0]["race_id"]
            and record["entry"]["horse_id"] == pp[0]["horse_id"]
            and record["phrase_ids"] == [p["id"] for p in pp],
            "modified_identity_plan",
        )
    require(keys == set(groups), "plan_keyset_changed")


def related_snapshot(c, race_ids):
    entries = [
        dict(r)
        for r in c.execute(
            text("SELECT * FROM public.race_entries WHERE race_id=ANY(:ids) ORDER BY id"),
            {"ids": race_ids},
        ).mappings()
    ]
    results = [
        dict(r)
        for r in c.execute(
            text(
                "SELECT rr.* FROM public.race_results rr "
                "JOIN public.race_entries e ON e.id=rr.race_entry_id WHERE e.race_id=ANY(:ids) "
                "ORDER BY rr.id"
            ),
            {"ids": race_ids},
        ).mappings()
    ]
    races = [
        dict(r)
        for r in c.execute(
            text("SELECT * FROM public.races WHERE id=ANY(:ids) ORDER BY id"), {"ids": race_ids}
        ).mappings()
    ]
    return {"entries": entries, "results": results, "races": races}


def check_current_phrases(current, before, entry_map=None):
    require(len(current) == len(before), "phrase_disappeared")
    prior = {p["id"]: p for p in before}
    for p in current:
        old = dict(prior[p["id"]])
        wanted_id = entry_map[(p["race_id"], p["horse_id"])] if entry_map else None
        for column in ("race_entry_id", "entry_link_status"):
            old.pop(column)
        observed = {k: v for k, v in p.items() if k not in ("race_entry_id", "entry_link_status")}
        require(encoded(old) == encoded(observed), "original_phrase_fields_changed")
        if entry_map:
            require(
                p["race_entry_id"] == wanted_id and p["entry_link_status"] == "matched",
                "post_write_phrase_link_mismatch",
            )
        else:
            require(
                (p["race_entry_id"] is None and p["entry_link_status"] == "entry_missing")
                or p["entry_link_status"] == "matched",
                "unexpected_link_state",
            )


def apply_plan(c, plan, folder):
    require(
        c.scalar(text("SELECT pg_try_advisory_xact_lock(70020261020)")), "repair_already_running"
    )
    ids = [p["id"] for p in plan["phrases_before"]]
    current = phrase_rows(c, ids, lock=True)
    check_current_phrases(current, plan["phrases_before"])
    race_ids = sorted({r["entry"]["race_id"] for r in plan["records"]})
    before = related_snapshot(c, race_ids)
    entries = {(e["race_id"], e["horse_id"]): e for e in before["entries"]}
    slots = {(e["race_id"], e["horse_number"]): e["horse_id"] for e in before["entries"]}
    inserts = []
    for r in plan["records"]:
        e = r["entry"]
        require(
            slots.get((e["race_id"], e["horse_number"]), e["horse_id"]) == e["horse_id"],
            "horse_number_conflict",
        )
        existing = entries.get((e["race_id"], e["horse_id"]))
        if existing:
            require(all(existing[k] == e[k] for k in ENTRY_FIELDS), "existing_entry_differs")
        else:
            inserts.append(e)
    # Confirm referenced people by their exact official ID, never by current names.
    for role, table, column, raw_key in (
        ("jockey", "jockeys", "kra_jockey_id", "jkNo"),
        ("trainer", "trainers", "kra_trainer_id", "trNo"),
        ("owner", "owners", "kra_owner_id", "owNo"),
    ):
        official = dict(c.execute(text(f"SELECT {column},id FROM public.{table}")).all())
        require(
            all(
                r["entry"][role + "_id"]
                == official.get(str(r["source"]["item"].get(raw_key) or ""))
                for r in plan["records"]
            ),
            "person_reference_changed",
        )
    pending = [p for p in current if p["race_entry_id"] is None]
    # Back up all existing affected-race rows before the first INSERT/UPDATE.
    stamp = str(time.time_ns())
    save(folder / f"before_{stamp}.json", {"phrases": current, **before})
    deferred = [
        dict(r)
        for r in c.execute(
            text("SELECT * FROM public.steward_report_versions WHERE race_id=55251 ORDER BY id")
        ).mappings()
    ]
    for start in range(0, len(inserts), 200):
        c.execute(insert(RaceEntry), inserts[start : start + 200])
    all_entries = (
        c.execute(
            text("SELECT id,race_id,horse_id FROM public.race_entries WHERE race_id=ANY(:ids)"),
            {"ids": race_ids},
        )
        .mappings()
        .all()
    )
    entry_map = {(e["race_id"], e["horse_id"]): e["id"] for e in all_entries}
    existing_results = {r["race_entry_id"]: r for r in before["results"]}
    new_results = []
    for r in plan["records"]:
        e = r["entry"]
        entry_id = entry_map[(e["race_id"], e["horse_id"])]
        expected = {"race_entry_id": entry_id, **r["result"]}
        old = existing_results.get(entry_id)
        if old:
            require(all(old[k] == expected[k] for k in RESULT_FIELDS), "existing_result_differs")
        else:
            new_results.append(expected)
    for start in range(0, len(new_results), 200):
        c.execute(insert(RaceResult), new_results[start : start + 200])
    bindings = [
        {"pid": p["id"], "eid": entry_map[(p["race_id"], p["horse_id"])], "sha": p["phrase_sha256"]}
        for p in pending
    ]
    if bindings:
        result = c.execute(
            text("""UPDATE public.horse_steward_phrases
            SET race_entry_id=:eid,entry_link_status='matched'
            WHERE id=:pid AND race_entry_id IS NULL AND entry_link_status='entry_missing'
            AND phrase_sha256=:sha"""),
            bindings,
        )
        require(result.rowcount == len(bindings), "phrase_update_count_changed")
    check_current_phrases(phrase_rows(c, ids), plan["phrases_before"], entry_map)
    after = related_snapshot(c, race_ids)
    for kind in ("entries", "results", "races"):
        saved = {r["id"]: r for r in after[kind]}
        require(
            all(encoded(saved.get(r["id"])) == encoded(r) for r in before[kind]),
            "preexisting_rows_changed",
        )
    deferred_after = [
        dict(r)
        for r in c.execute(
            text("SELECT * FROM public.steward_report_versions WHERE race_id=55251 ORDER BY id")
        ).mappings()
    ]
    require(deferred_after == deferred, "deferred_oct17_report_changed")
    summary = {
        "entries_added": len(inserts),
        "special_results_added": len(new_results),
        "phrases_linked": len(pending),
        "preexisting_row_mismatches": 0,
        "phrase_text_mismatches": 0,
        "normal_placings_added": 0,
        "deferred_oct17_unchanged": True,
        "entry_ids": [
            entry_map[(r["entry"]["race_id"], r["entry"]["horse_id"])] for r in plan["records"]
        ],
    }
    if inserts or new_results or pending:
        now = time.time_ns() // 1000000
        run_id = c.scalar(
            insert(IngestionRun)
            .values(
                source="kra_api_archive_verified",
                data_type="steward_entry_link_repair",
                started_at_ms=now,
                completed_at_ms=now,
                status="completed",
                records_fetched=837,
                records_written=len(pending),
            )
            .returning(IngestionRun.id)
        )
        plan_file = folder / "plan.json"
        c.execute(
            insert(SourceDocument),
            {
                "ingestion_run_id": run_id,
                "source_url": "archive://verified-kra-api4-3/steward-entry-repair",
                "endpoint": "/API4_3/raceResult_3",
                "operation": "archived_source_verification",
                "request_params_json": encoded(
                    {
                        "replay_only": True,
                        "not_live_http": True,
                        "archive_files": plan["sources"],
                        "normalization": plan["normalization"],
                        "restored_entry_ids": summary["entry_ids"],
                    }
                ),
                "requested_at_ms": now,
                "retrieved_at_ms": now,
                "http_status_code": None,
                "content_type": "application/json",
                "response_bytes": plan_file.stat().st_size,
                "local_path": str(plan_file.relative_to(ROOT)),
                "sha256": file_hash(plan_file),
            },
        )
        summary["ingestion_run_id"] = run_id
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--inspect", action="store_true")
    mode.add_argument("--apply", action="store_true")
    p.add_argument("--plan", type=Path)
    args = p.parse_args(argv)
    if not (args.inspect or args.apply):
        print(
            "Plan only: --inspect creates a read-only verification plan; --apply --plan PATH commits it."
        )
        return 0
    if args.apply and args.plan is None:
        p.error("--apply requires --plan")
    engine = connect_engine()
    try:
        if args.inspect:
            folder = ARTIFACTS / f"steward_entry_repair_20261020_{time.time_ns()}"
            folder.mkdir()
            with engine.connect() as c:
                c.execute(text("SET TRANSACTION READ ONLY"))
                c.execute(text("SET LOCAL statement_timeout='20s'"))
                phrases = phrase_rows(c)
                # Release the DB transaction before archive/network validation.
                c.rollback()
                plan = build_plan(c, phrases, folder)
            save(folder / "plan.json", plan)
            save(folder / "plan_manifest.json", {"sha256": file_hash(folder / "plan.json")})
            print(
                encoded(
                    {
                        "plan": str(folder / "plan.json"),
                        "records": len(plan["records"]),
                        "phrases": len(phrases),
                        "archives": len(plan["sources"]),
                        "unresolved_people": plan["unresolved_person_ids"],
                        "outcomes": dict(
                            Counter(r["result"]["rank_remark"] for r in plan["records"])
                        ),
                    }
                )
            )
        else:
            path = args.plan.resolve()
            require(
                path.name == "plan.json"
                and path.parent.parent == ARTIFACTS.resolve()
                and path.parent.name.startswith("steward_entry_repair_20261020_"),
                "unexpected_plan_path",
            )
            folder = path.parent
            expected = json.loads((folder / "plan_manifest.json").read_text())["sha256"]
            require(file_hash(path) == expected, "plan_file_changed")
            plan = json.loads(path.read_text())
            validate_plan(plan, folder)  # all file/CPU checks before taking database locks
            with engine.begin() as c:
                c.execute(text("SET LOCAL statement_timeout='20s'"))
                c.execute(text("SET LOCAL lock_timeout='3s'"))
                c.execute(text("SET LOCAL idle_in_transaction_session_timeout='30s'"))
                receipt = apply_plan(c, plan, folder)
            # Commit has returned. An independent fresh transaction checks the links.
            with engine.connect() as c:
                c.execute(text("SET TRANSACTION READ ONLY"))
                current = phrase_rows(c, [p["id"] for p in plan["phrases_before"]])
                require(
                    all(
                        p["race_entry_id"] and p["entry_link_status"] == "matched" for p in current
                    ),
                    "post_commit_missing_link",
                )
                receipt["post_commit_linked"] = len(current)
            save(folder / f"receipt_{time.time_ns()}.json", receipt)
            print(encoded({k: v for k, v in receipt.items() if k != "entry_ids"}))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Never print credential-bearing DB exception text/parameters.
        if isinstance(exc, ValueError) and re.fullmatch(r"[a-z0-9_]+", str(exc)):
            print("Stopped:", str(exc))
        else:
            print("Stopped:", type(exc).__name__)
        raise SystemExit(1) from None
