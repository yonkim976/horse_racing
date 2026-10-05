"""Resolve missing API20_1 horse identities with recorded evidence and decisions.

The API rows remain untouched. This produces a frozen, auditable link ledger
from RPT, the operational trial ledger, and explicit user confirmations.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path

from horse_racing.parsers.running_trials import parse_running_trial_report


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SOURCE = ROOT / "thoroughbred/research/20260929_trial_results_api_v1/unidentified_participants.csv"
OPERATIONAL_DB = ROOT / "data/horse_racing.sqlite3"
RPT_ROOT = ROOT / "data/raw/kra_text/dacom23"
PRIOR_REVIEW = ROOT / "docs/research_archive/source/busan_trial_linkage_20260915/unresolved.csv"
USER_CONFIRMATIONS = HERE / "user_confirmations.csv"
LINKS = HERE / "identity_links.csv"
PENDING = HERE / "pending_review.csv"
VALIDATION = HERE / "validation.json"

LINK_FIELDS = [
    "participant_row_id", "trial_date", "source_meet_query", "trial_no", "api_chulNo",
    "official_horse_id", "horse_name", "operational_result_id",
    "rpt_source_file", "rpt_source_file_sha256", "rpt_horse_name",
    "time_match", "rank_match", "jockey_name_match", "jockey_id_match",
    "trainer_name_match", "trainer_id_match", "body_weight_match",
    "trainer_name_note", "resolution_method", "user_confirmation_note", "decision_basis",
]
PENDING_FIELDS = [
    "participant_row_id", "trial_date", "source_meet_query", "api_meet_label",
    "trial_no", "api_chulNo", "api_ord", "api_passFlag", "api_rcTime",
    "api_jkNo", "api_jkName", "api_trNo", "api_trName", "api_wgHr",
    "api_reason", "api_nopassReason", "source_file", "source_item_index",
    "rpt_horse_name", "rpt_source_file", "prior_candidate_hr_nos_json",
    "review_reason",
]

MATCH_SQL = """
SELECT r.id, h.kra_horse_id, r.horse_name_raw, r.finish_time_ms,
       r.finish_rank_raw, r.jockey_name_raw, j.kra_jockey_id,
       r.trainer_name_raw, tr.kra_trainer_id, r.body_weight_kg
FROM running_trial_results r
JOIN running_trials t ON t.id = r.running_trial_id
LEFT JOIN horses h ON h.id = r.horse_id
LEFT JOIN jockeys j ON j.id = r.jockey_id
LEFT JOIN trainers tr ON tr.id = r.trainer_id
WHERE t.meet_code = ? AND t.trial_date_local = ?
  AND t.trial_race_number = ? AND r.horse_number = ?
"""


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def present(value: str | None) -> bool:
    return value is not None and str(value).strip() not in {"", "-"}


def compare(api_value: str | None, other_value: object) -> str:
    if not present(api_value) or other_value is None or str(other_value).strip() == "":
        return "not_comparable"
    return "match" if str(api_value).strip() == str(other_value).strip() else "mismatch"


def assert_missing_api_identity(row: dict[str, str]) -> None:
    raw = json.loads(row["source_record_json"])
    if "hrNo" in raw or "hrName" in raw or present(row["horse_id"]) or present(row["horse_name"]):
        raise ValueError(f"Source participant unexpectedly has identity: {row['participant_row_id']}")


def report_row(row: dict[str, str], cache: dict[Path, list]) -> tuple[object, Path]:
    year, month, day = row["trial_date"].split("-")
    meet = int(row["source_meet_query"])
    path = (RPT_ROOT / f"meet={meet}" / f"year={year}" / f"month={month}"
            / f"day={day}" / f"{year}{month}{day}dacom23.rpt")
    if path not in cache:
        cache[path] = parse_running_trial_report(path.read_bytes(), meet=meet)
    found = [result for block in cache[path]
             if block.trial_date.isoformat() == row["trial_date"]
             and block.trial_race_number == int(row["trial_no"])
             for result in block.results
             if result.horse_number == int(row["api_chulNo"])]
    if len(found) != 1:
        raise ValueError(f"Expected one exact RPT slot for {row['participant_row_id']}: {len(found)}")
    return found[0], path


def assess(row: dict[str, str], candidate: tuple, db: sqlite3.Connection,
           rpt: object, rpt_path: Path) -> tuple[dict[str, str] | None, str]:
    (result_id, horse_id, horse_name, finish_ms, rank, jockey_name,
     jockey_id, trainer_name, trainer_id, body_weight) = candidate
    if not present(horse_id) or not present(horse_name):
        return None, "operational record has no horse identity"
    if rpt.horse_name != horse_name:
        return None, "archived RPT horse name disagrees with operational horse name"
    assert_missing_api_identity(row)

    raw_time = row["api_rcTime"]
    if present(raw_time) and float(raw_time) > 0:
        time_match = "match" if finish_ms == round(float(raw_time) * 1000) else "mismatch"
        if rpt.finish_time_ms is not None and rpt.finish_time_ms != round(float(raw_time) * 1000):
            return None, "archived RPT finish time disagrees with API"
    else:
        time_match = "not_comparable" if finish_ms is None else "mismatch"
    raw_rank = row["api_ord"]
    rank_match = compare(raw_rank, rank) if raw_rank.isdigit() else "not_comparable"
    jockey_name_match = compare(row["api_jkName"], jockey_name)
    jockey_id_match = compare(row["api_jkNo"], jockey_id)
    trainer_name_match = compare(row["api_trName"], trainer_name)
    trainer_id_match = compare(row["api_trNo"], trainer_id)
    raw_weight = row["api_wgHr"]
    body_weight_match = (
        compare(str(int(float(raw_weight))), body_weight)
        if present(raw_weight) and float(raw_weight) > 0 else "not_comparable"
    )

    trainer_name_note = ""
    if trainer_name_match == "mismatch":
        official_trainer = db.execute(
            "SELECT name_ko FROM trainers WHERE kra_trainer_id = ?", (row["api_trNo"],)
        ).fetchone()
        if official_trainer and official_trainer[0] == row["api_trName"]:
            trainer_name_note = (
                f"operational raw name {trainer_name!r} differs; API trainer ID "
                f"{row['api_trNo']} resolves to API name {row['api_trName']!r}"
            )
        else:
            return None, "trainer name disagrees without an ID-based explanation"

    comparisons = {
        "time_match": time_match,
        "rank_match": rank_match,
        "jockey_name_match": jockey_name_match,
        "jockey_id_match": jockey_id_match,
        "trainer_name_match": trainer_name_match,
        "trainer_id_match": trainer_id_match,
        "body_weight_match": body_weight_match,
    }
    if any(value == "mismatch" for key, value in comparisons.items() if key != "trainer_name_match"):
        return None, "result attributes conflict with the same-slot operational record"
    supporting = sum(value == "match" for value in comparisons.values())
    if supporting < 2:
        return None, "fewer than two corroborating result attributes"

    link = {key: row[key] for key in LINK_FIELDS[:5]}
    link.update({
        "official_horse_id": horse_id,
        "horse_name": horse_name,
        "operational_result_id": str(result_id),
        "rpt_source_file": rpt_path.relative_to(ROOT).as_posix(),
        "rpt_source_file_sha256": hashlib.sha256(rpt_path.read_bytes()).hexdigest(),
        "rpt_horse_name": rpt.horse_name,
        **comparisons,
        "trainer_name_note": trainer_name_note,
        "resolution_method": "crosschecked_operational_rpt",
        "user_confirmation_note": "",
        "decision_basis": "unique same meet/date/trial/slot in API, RPT, operational DB; corroborated result attributes",
    })
    return link, ""


def user_confirmed_link(row: dict[str, str], confirmation: dict[str, str],
                        rpt: object, rpt_path: Path, prior_row: dict[str, str] | None,
                        db: sqlite3.Connection) -> dict[str, str]:
    assert_missing_api_identity(row)
    horse_id = confirmation["official_horse_id"]
    horse_name = confirmation["horse_name"]
    if rpt.horse_name != horse_name:
        raise ValueError(f"User-confirmed name disagrees with RPT: {row['participant_row_id']}")
    if prior_row is None or horse_id not in json.loads(prior_row["candidate_hr_nos_json"]):
        raise ValueError(f"User-confirmed ID was not a recorded candidate: {row['participant_row_id']}")
    profile = db.execute(
        "SELECT name_ko, sex, birth_date, meet_code FROM horses WHERE kra_horse_id = ?",
        (horse_id,),
    ).fetchone()
    if profile is None or profile[0] != horse_name or profile[1] != rpt.sex or profile[3] != 1:
        raise ValueError(f"User-confirmed profile disagrees with RPT or Seoul affiliation: {horse_id}")
    if rpt.age is not None and int(row["trial_date"][:4]) - int(profile[2][:4]) != rpt.age:
        raise ValueError(f"User-confirmed profile age disagrees with RPT: {horse_id}")
    raw_time = float(row["api_rcTime"])
    if raw_time > 0 and rpt.finish_time_ms != round(raw_time * 1000):
        raise ValueError(f"User-confirmed RPT time disagrees with API: {row['participant_row_id']}")
    if row["api_ord"].isdigit() and rpt.finish_rank_raw != row["api_ord"]:
        raise ValueError(f"User-confirmed RPT rank disagrees with API: {row['participant_row_id']}")
    if present(row["api_jkName"]) and rpt.jockey_name != row["api_jkName"]:
        raise ValueError(f"User-confirmed RPT jockey disagrees with API: {row['participant_row_id']}")
    if present(row["api_trName"]) and rpt.trainer_name != row["api_trName"]:
        raise ValueError(f"User-confirmed RPT trainer disagrees with API: {row['participant_row_id']}")
    if float(row["api_wgHr"]) > 0 and rpt.body_weight_kg != int(float(row["api_wgHr"])):
        raise ValueError(f"User-confirmed RPT body weight disagrees with API: {row['participant_row_id']}")
    link = {key: row[key] for key in LINK_FIELDS[:5]}
    link.update({
        "official_horse_id": horse_id,
        "horse_name": horse_name,
        "operational_result_id": "",
        "rpt_source_file": rpt_path.relative_to(ROOT).as_posix(),
        "rpt_source_file_sha256": hashlib.sha256(rpt_path.read_bytes()).hexdigest(),
        "rpt_horse_name": rpt.horse_name,
        "time_match": "not_comparable",
        "rank_match": "not_comparable",
        "jockey_name_match": "not_comparable",
        "jockey_id_match": "not_comparable",
        "trainer_name_match": "not_comparable",
        "trainer_id_match": "not_comparable",
        "body_weight_match": "not_comparable",
        "trainer_name_note": "",
        "resolution_method": "user_confirmed_rpt_profile",
        "user_confirmation_note": confirmation["confirmation_note"],
        "decision_basis": "user confirmation; exact API/RPT slot and name; prior candidate ID; Seoul horse profile sex and age agree",
    })
    return link


def main() -> None:
    with SOURCE.open(encoding="utf-8", newline="") as stream:
        source_rows = list(csv.DictReader(stream))
    if len(source_rows) != 104 or len({r["participant_row_id"] for r in source_rows}) != 104:
        raise ValueError("Unexpected missing-identity source row count or duplicate row ID")

    db = sqlite3.connect(f"file:{OPERATIONAL_DB}?mode=ro", uri=True)
    with PRIOR_REVIEW.open(encoding="utf-8", newline="") as stream:
        prior = {
            (r["trial_date"], r["trial_no"], r["chul_no"]): r
            for r in csv.DictReader(stream)
        }
    with USER_CONFIRMATIONS.open(encoding="utf-8", newline="") as stream:
        confirmation_rows = list(csv.DictReader(stream))
    confirmations = {
        (r["source_meet_query"], r["trial_date"], r["trial_no"], r["api_chulNo"]): r
        for r in confirmation_rows
    }
    if len(confirmation_rows) != 5 or len(confirmations) != 5:
        raise ValueError("Expected five unique user-confirmed trial slots")
    report_cache: dict[Path, list] = {}
    links: list[dict[str, str]] = []
    pending: list[dict[str, str]] = []
    try:
        for row in source_rows:
            rpt, rpt_path = report_row(row, report_cache)
            candidates = db.execute(MATCH_SQL, (
                int(row["source_meet_query"]), row["trial_date"],
                int(row["trial_no"]), int(row["api_chulNo"]),
            )).fetchall()
            if len(candidates) == 1:
                link, reason = assess(row, candidates[0], db, rpt, rpt_path)
                if link is not None:
                    links.append(link)
                    continue
            else:
                reason = f"operational same-slot candidate count is {len(candidates)}"
            prior_row = prior.get((row["trial_date"], row["trial_no"], row["api_chulNo"]))
            if prior_row and prior_row["horse_name_raw"] != rpt.horse_name:
                raise ValueError(f"Prior review disagrees with archived RPT: {row['participant_row_id']}")
            confirmation = confirmations.get((
                row["source_meet_query"], row["trial_date"], row["trial_no"], row["api_chulNo"]
            ))
            if confirmation is not None:
                if candidates:
                    raise ValueError(f"User confirmation unexpectedly overrides an operational slot: {row['participant_row_id']}")
                links.append(user_confirmed_link(row, confirmation, rpt, rpt_path, prior_row, db))
                continue
            pending.append({
                **{key: row[key] for key in PENDING_FIELDS if key in row},
                "rpt_horse_name": rpt.horse_name,
                "rpt_source_file": rpt_path.relative_to(ROOT).as_posix(),
                "prior_candidate_hr_nos_json": (
                    prior_row["candidate_hr_nos_json"] if prior_row else "[]"
                ),
                "review_reason": reason,
            })
    finally:
        db.close()

    order = lambda row: (
        row["trial_date"], int(row["source_meet_query"]),
        int(row["trial_no"]), int(row["api_chulNo"]),
    )
    links.sort(key=order)
    pending.sort(key=order)
    if len(links) != 104 or pending:
        raise ValueError(f"Expected 104 links and 0 pending, got {len(links)} and {len(pending)}")
    if sum(r["resolution_method"] == "user_confirmed_rpt_profile" for r in links) != 5:
        raise ValueError("Expected five user-confirmed links")
    if {r["participant_row_id"] for r in links} & {r["participant_row_id"] for r in pending}:
        raise ValueError("A participant is both linked and pending")
    write_csv(LINKS, LINK_FIELDS, links)
    write_csv(PENDING, PENDING_FIELDS, pending)
    validation = {
        "source": str(SOURCE.relative_to(ROOT)),
        "crosscheck_source": str(OPERATIONAL_DB.relative_to(ROOT)),
        "user_confirmation_source": str(USER_CONFIRMATIONS.relative_to(ROOT)),
        "source_rows_without_api_identity": len(source_rows),
        "linked_rows": len(links),
        "pending_rows": len(pending),
        "operational_rpt_crosschecked_rows": sum(
            r["resolution_method"] == "crosschecked_operational_rpt" for r in links
        ),
        "user_confirmed_rows": sum(
            r["resolution_method"] == "user_confirmed_rpt_profile" for r in links
        ),
        "distinct_linked_official_horses": len({r["official_horse_id"] for r in links}),
        "linked_positive_time_matches": sum(
            r["time_match"] == "match" for r in links
        ),
        "archived_rpt_exact_slot_matches": len(source_rows),
        "linked_rpt_names_agree": sum(r["rpt_horse_name"] == r["horse_name"] for r in links),
        "trainer_name_discrepancies_explained_by_id": sum(
            bool(r["trainer_name_note"]) for r in links
        ),
        "note": "Frozen linkage evidence; API source identity fields remain null.",
    }
    VALIDATION.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(validation, ensure_ascii=False))


if __name__ == "__main__":
    main()
