"""Load reviewed trainer statuses and alias resolutions from frozen 2026-09-29 evidence.

Dry-run by default. Source names remain in trainer_identity_resolutions even when
the reviewed trainer display names have been canonicalized. Run the 0024 schema
migration first, then --apply-local and --apply-remote.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, text

from horse_racing.config import get_settings
from scripts.sync_trainer_historical_regions import parse_retired_list

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/horse_racing.sqlite3"
SOURCE_ROOT = ROOT / "docs/research_archive/source"
OFFICIAL_ROOT = ROOT / "data/raw/kra_retired_trainer_regions/2026-09-29"
OBSERVED_ON = date(2026, 9, 29)
ACTIVE_EXCEPTIONS = {"070103", "070157", "070168"}
REVIEWED_NAME_IDS = {"070167": 5, "070133": 6}
REGIONS = {1: "SEOUL", 2: "JEJU", 3: "YEONGNAM"}
API_URL = "https://apis.data.go.kr/B551015/API308/trainerInfo"
CSV_PATHS = (
    SOURCE_ROOT / "seoul_text_id_linkage_20260915_v1/candidate_evidence.csv",
    SOURCE_ROOT / "busan_temp_id_linkage_20260915/candidate_evidence.csv",
)


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _day(value: object) -> date:
    raw = str(value)
    if len(raw) != 8 or not raw.isdigit():
        raise ValueError(f"Unexpected official date: {raw}")
    return date.fromisoformat(f"{raw[:4]}-{raw[4:6]}-{raw[6:]}")


def build_payload() -> tuple[list[dict], list[dict]]:
    official: dict[str, tuple[dict, int, str, str]] = {}
    retired: set[str] = set()
    for meet in (1, 2, 3):
        api_bytes = (OFFICIAL_ROOT / f"api_meet_{meet}.json").read_bytes()
        web_bytes = (OFFICIAL_ROOT / f"retired_meet_{meet}.html").read_bytes()
        retired.update(parse_retired_list(web_bytes, meet))
        response = json.loads(api_bytes)["response"]
        if response["header"]["resultCode"] != "00":
            raise ValueError(f"Failed official API response for meet {meet}")
        items = response["body"]["items"]["item"]
        if len(items) != int(response["body"]["totalCount"]):
            raise ValueError(f"Incomplete official API response for meet {meet}")
        for item in items:
            tr_no = str(item["trNo"])
            if tr_no in official or item["meet"] != {1: "서울", 2: "제주", 3: "영남"}[meet]:
                raise ValueError(f"Duplicate or wrong-region official trainer {tr_no}")
            official[tr_no] = (item, meet, _hash(api_bytes), _hash(web_bytes))

    evidence: dict[str, dict] = defaultdict(
        lambda: {"ids": set(), "rows": 0, "paths": set()}
    )
    for path in CSV_PATHS:
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if row["actor_type"] != "trainer":
                    continue
                item = evidence[row["temporary_id"]]
                item["ids"].add(row["official_id"])
                item["rows"] += int(row["evidence_rows"])
                item["paths"].add(str(path.relative_to(ROOT)))

    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        local = {
            ref: (name, count)
            for ref, name, count in connection.execute(
                "select t.kra_trainer_id,t.name_ko,count(e.id) "
                "from trainers t left join race_entries e on e.trainer_id=t.id "
                "group by t.id"
            )
        }
        saved_source_names = dict(connection.execute(
            "select temporary_trainer_ref, source_name_ko "
            "from trainer_identity_resolutions where resolution_status='confirmed'"
        ))
        current_ids = {
            ref: name for ref, (name, _) in local.items() if len(ref) == 6 and ref.isdigit()
        }
    finally:
        connection.close()

    ended_only = {
        tr_no for tr_no, (item, _, _, _) in official.items()
        if str(item["spDate"]) != "-" and tr_no not in retired
    }
    chosen: list[dict] = []
    for ref, row in sorted(evidence.items()):
        if ref not in local or len(row["ids"]) != 1:
            continue
        tr_no = next(iter(row["ids"]))
        if tr_no not in REVIEWED_NAME_IDS and tr_no not in ended_only:
            continue
        displayed_name, local_count = local[ref]
        if row["rows"] != local_count or local_count <= 0:
            raise ValueError(f"Incomplete race-row identity evidence: {ref}")
        item = official[tr_no][0]
        source_name = saved_source_names.get(ref, displayed_name)
        if tr_no in REVIEWED_NAME_IDS:
            if tr_no not in current_ids or current_ids[tr_no] != item["trName"]:
                raise ValueError(f"Current canonical trainer missing: {tr_no}")
            if displayed_name not in {source_name, item["trName"]}:
                raise ValueError(f"Unexpected trainer display name: {ref}")
            resolution = "confirmed"
        else:
            if int(item["rcCntT"]) >= 20:
                raise ValueError(f"Unexpected 20+ race ended-only trainer: {tr_no}")
            resolution = "official_id_candidate"
        chosen.append(
            {
                "temporary_trainer_ref": ref,
                "official_tr_no": tr_no,
                "source_name_ko": source_name,
                "canonical_name_ko": item["trName"],
                "resolution_status": resolution,
                "matched_race_rows": row["rows"],
                "source_reference": "; ".join(sorted(row["paths"])),
                "reviewed_on": OBSERVED_ON,
            }
        )

    confirmed = [row for row in chosen if row["resolution_status"] == "confirmed"]
    candidates = [row for row in chosen if row["resolution_status"] == "official_id_candidate"]
    if len(confirmed) != 11 or sum(row["matched_race_rows"] for row in confirmed) != 3574:
        raise ValueError("The reviewed name-change evidence no longer totals 11 IDs / 3574 rows")
    if {tr_no: sum(row["official_tr_no"] == tr_no for row in confirmed)
        for tr_no in REVIEWED_NAME_IDS} != REVIEWED_NAME_IDS:
        raise ValueError("Reviewed alias count differs by official trainer")
    if len(candidates) != 54 or len({row["official_tr_no"] for row in candidates}) != 54:
        raise ValueError("Ended-but-not-retired evidence no longer totals 54 IDs")

    selected_numbers = ACTIVE_EXCEPTIONS | set(REVIEWED_NAME_IDS) | {
        row["official_tr_no"] for row in candidates
    }
    if len(selected_numbers) != 59:
        raise ValueError("Expected exactly 59 selected official registrations")
    statuses = []
    for tr_no in sorted(selected_numbers):
        item, meet, api_hash, retired_hash = official[tr_no]
        active = tr_no in ACTIVE_EXCEPTIONS or tr_no in REVIEWED_NAME_IDS
        if active and str(item["spDate"]) != "-":
            raise ValueError(f"Active trainer now has official end date: {tr_no}")
        if not active and (tr_no in retired or str(item["spDate"]) == "-"):
            raise ValueError(f"Ended-only trainer status changed: {tr_no}")
        statuses.append(
            {
                "official_tr_no": tr_no,
                "observed_on": OBSERVED_ON,
                "canonical_name_ko": item["trName"],
                "region_code": REGIONS[meet],
                "status_code": "active" if active else "domestic_registration_ended",
                "status_label_ko": "현역" if active else "국내 등록 종료(은퇴 미확인)",
                "source_end_date": None if active else _day(item["spDate"]),
                "classification_basis": (
                    "KRA active web and API308 open registration; currentrainer omission"
                    if tr_no in ACTIVE_EXCEPTIONS
                    else "KRA current name and API308 open registration"
                    if active
                    else "API308 end date; absent from KRA retired list (<20 races)"
                ),
                "source_url": f"{API_URL}?meet={meet}",
                "source_api_sha256": api_hash,
                "retired_list_sha256": None if active else retired_hash,
            }
        )
    return statuses, chosen


STATUS_COLUMNS = (
    "official_tr_no", "observed_on", "canonical_name_ko", "region_code",
    "status_code", "status_label_ko", "source_end_date", "classification_basis",
    "source_url", "source_api_sha256", "retired_list_sha256",
)
ALIAS_COLUMNS = (
    "temporary_trainer_ref", "official_tr_no", "source_name_ko", "canonical_name_ko",
    "resolution_status", "matched_race_rows", "source_reference", "reviewed_on",
)


def _save(connection, table: str, columns: tuple[str, ...], rows: list[dict], key: str) -> None:
    selected = ", ".join(columns)
    binds = ", ".join(f":{column}" for column in columns)
    connection.execute(
        text(f"insert into {table} ({selected}) values ({binds}) on conflict do nothing"), rows
    )
    for expected in rows:
        date_clause = " and observed_on = :observed_on" if "observed_on" in columns else ""
        actual = connection.execute(
            text(f"select {selected} from {table} where {key} = :key{date_clause}"),
            {"key": expected[key], "observed_on": expected.get("observed_on")},
        ).mappings().one()
        if any(str(actual[column]) != str(expected[column]) for column in columns):
            raise ValueError(f"Conflicting saved {table} row: {expected[key]}")


def _canonicalize_confirmed_names(connection, aliases: list[dict]) -> int:
    confirmed = [row for row in aliases if row["resolution_status"] == "confirmed"]
    if len(confirmed) != 11 or sum(row["matched_race_rows"] for row in confirmed) != 3574:
        raise ValueError("Unexpected confirmed trainer identity scope")
    for row in confirmed:
        trainer = connection.execute(text(
            "select t.name_ko, count(e.id) as entry_count "
            "from trainers t left join race_entries e on e.trainer_id=t.id "
            "where t.kra_trainer_id=:ref group by t.id, t.name_ko"
        ), {"ref": row["temporary_trainer_ref"]}).mappings().one()
        official_name = connection.execute(text(
            "select name_ko from trainers where kra_trainer_id=:official_no"
        ), {"official_no": row["official_tr_no"]}).scalar_one()
        if (trainer["name_ko"] not in {row["source_name_ko"], row["canonical_name_ko"]}
                or trainer["entry_count"] != row["matched_race_rows"]
                or official_name != row["canonical_name_ko"]):
            raise ValueError(f"Trainer identity changed: {row['temporary_trainer_ref']}")
    changed = 0
    for row in confirmed:
        result = connection.execute(text(
            "update trainers set name_ko=:canonical_name "
            "where kra_trainer_id=:ref and name_ko=:source_name"
        ), {
            "canonical_name": row["canonical_name_ko"],
            "ref": row["temporary_trainer_ref"],
            "source_name": row["source_name_ko"],
        })
        changed += result.rowcount
        actual = connection.execute(text(
            "select t.name_ko, ir.source_name_ko from trainers t "
            "join trainer_identity_resolutions ir "
            "on ir.temporary_trainer_ref=t.kra_trainer_id "
            "where t.kra_trainer_id=:ref"
        ), {"ref": row["temporary_trainer_ref"]}).one()
        if actual != (row["canonical_name_ko"], row["source_name_ko"]):
            raise ValueError(f"Canonical trainer verification failed: {row['temporary_trainer_ref']}")
    return changed


def save(
    database_url: str, statuses: list[dict], aliases: list[dict],
    *, canonicalize_names: bool = False,
) -> int:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            _save(
                connection, "trainer_status_observations", STATUS_COLUMNS, statuses,
                "official_tr_no",
            )
            _save(
                connection, "trainer_identity_resolutions", ALIAS_COLUMNS, aliases,
                "temporary_trainer_ref",
            )
            return _canonicalize_confirmed_names(connection, aliases) if canonicalize_names else 0
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-local", action="store_true")
    parser.add_argument("--apply-remote", action="store_true")
    parser.add_argument("--canonicalize-names", action="store_true")
    args = parser.parse_args()
    statuses, aliases = build_payload()
    print(
        f"Preflight: {len(statuses)} official statuses "
        f"(active=5, domestic_registration_ended=54), "
        f"{len(aliases)} text links (confirmed=11, candidate=54)"
    )
    if args.apply_local:
        changed = save(
            f"sqlite:///{DB}", statuses, aliases,
            canonicalize_names=args.canonicalize_names,
        )
        print(f"Local SQLite: stored and verified; canonicalized {changed} trainer names")
    if args.apply_remote:
        changed = save(
            get_settings().database_url, statuses, aliases,
            canonicalize_names=args.canonicalize_names,
        )
        print(f"Supabase: stored and verified; canonicalized {changed} trainer names")


if __name__ == "__main__":
    main()
