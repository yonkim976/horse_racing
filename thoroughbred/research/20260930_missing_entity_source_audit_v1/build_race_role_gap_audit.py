"""Build a traceable audit of KRA race-result trainer/owner source gaps."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DB = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
API26_OBSERVATIONS = HERE / "api26_recheck_observations.json"
OUT = HERE / "race_role_gap_audit.jsonl"
FIELD_NAMES = ("trNo", "trName", "owNo", "owName")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_path(relative: str) -> Path:
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Source pointer escaped the repository")
    return path


def response_items(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    response = payload.get("response", {})
    body = response.get("body", {})
    box = body.get("items")
    items = box.get("item", []) if isinstance(box, dict) else box or []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list) or len(items) != int(body.get("totalCount") or 0):
        raise ValueError(f"Incomplete API response: {path}")
    return items


def main() -> None:
    con = duckdb.connect(str(DB), read_only=True)
    rows = con.execute(
        "SELECT source_meet, result_date, result_race_no, horse_program_no_raw, "
        "horse_id_raw, horse_name_raw, result_rank_raw, finish_time_seconds_raw, "
        "source_file, source_item_index "
        "FROM confirmed_runners WHERE trainer_id_raw IS NULL AND owner_id_raw IS NULL "
        "ORDER BY result_date, source_meet, result_race_no, horse_program_no_raw"
    ).fetchall()
    con.close()
    if len(rows) != 38:
        raise ValueError(f"Expected 38 role gaps, found {len(rows)}")

    recheck = json.loads(API26_OBSERVATIONS.read_text(encoding="utf-8"))
    if recheck["target_row_count"] != 38 or not recheck["all_targets_exactly_once"]:
        raise ValueError("API26 recheck did not cover 38 exact event keys")
    recheck_by_key = {
        (x["meet"], x["race_date"], x["race_no"], x["horse_program_no"], x["horse_id"]): x
        for x in recheck["observations"]
    }
    if len(recheck_by_key) != 38:
        raise ValueError("API26 recheck has duplicate event keys")

    raw_cache: dict[str, list[dict]] = {}
    archive_cache: dict[Path, list[dict]] = {}
    audit = []
    for meet, date, race, program, horse, name, rank, race_time, source_file, source_index in rows:
        if not (meet in {"1", "3"} and re.fullmatch(r"\d{8}", date)):
            raise ValueError("Unexpected meet/date in race source")
        if rank != "95" or race_time != "0":
            raise ValueError("Role gap changed from rank-95 zero-time source row")
        key = (meet, date, race, program, horse)
        alt = recheck_by_key[key]
        if any(alt[f"api26_{role}_id"] is not None for role in ("trainer", "owner")):
            raise ValueError("Current API26 recheck has unexpectedly populated role ID")
        source_path = checked_path(source_file)
        if source_file not in raw_cache:
            with gzip.open(source_path, "rt", encoding="utf-8") as stream:
                raw_cache[source_file] = json.load(stream)["response"]["body"]["items"]["item"]
        raw_item = raw_cache[source_file][int(source_index)]
        if str(raw_item.get("hrNo")) != horse or str(raw_item.get("rcDate")) != date:
            raise ValueError("Race source pointer no longer matches horse/date")
        if any(field in raw_item for field in FIELD_NAMES):
            raise ValueError("A role field is present in the archived API4_3 source")
        recheck_path = checked_path(alt["api26_recheck_source_file"])
        if sha(recheck_path) != alt["api26_recheck_sha256"]:
            raise ValueError("API26 recheck source hash mismatch")
        recheck_item = response_items(recheck_path)[alt["api26_recheck_item_index_zero_based"]]
        if (
            str(recheck_item.get("rcDate")) != date
            or str(recheck_item.get("rcNo")) != race
            or str(recheck_item.get("chulNo")) != program
            or str(recheck_item.get("hrNo")) != horse
        ):
            raise ValueError("API26 recheck source pointer no longer matches event")

        rpt_rel = (
            f"data/raw/kra_text/dacom11/meet={meet}/year={date[:4]}/month={date[4:6]}/"
            f"day={date[6:]}/{date}dacom11.rpt"
        )
        rpt_path = checked_path(rpt_rel)
        rpt_evidence = None
        if rpt_path.exists():
            term = name.split("]")[-1]
            lines = rpt_path.read_bytes().decode("cp949").splitlines()
            pattern = re.compile(rf"(?:^|\s){re.escape(program)}\s+{re.escape(term)}(?:\s|$)")
            candidates = [(i + 1, line.strip()) for i, line in enumerate(lines) if pattern.search(line)]
            if not candidates:
                raise ValueError(f"RPT file exists but target horse/program line is absent: {rpt_path}")
            line_no, line_text = candidates[0]
            rpt_evidence = {
                "source_file": rpt_rel,
                "sha256": sha(rpt_path),
                "line_number": line_no,
                "line_text": line_text,
                "interpretation": "name-only evidence; no trainer/owner official IDs in this line",
            }

        archived_matches = []
        archive_glob = (
            ROOT / f"data/raw/kra/entry_sheet/{date[:4]}/{date[4:6]}/{date[6:]}/meet_{meet}"
        )
        for page_path in sorted(archive_glob.glob("run_*/page_*.json")):
            if page_path not in archive_cache:
                archive_cache[page_path] = response_items(page_path)
            for item_index, item in enumerate(archive_cache[page_path]):
                if (
                    str(item.get("rcDate")) == date
                    and str(item.get("rcNo")) == race
                    and str(item.get("chulNo")) == program
                    and str(item.get("hrNo")) == horse
                    and item.get("trNo") is not None
                    and item.get("owNo") is not None
                ):
                    archived_matches.append({
                        "source_file": page_path.relative_to(ROOT).as_posix(),
                        "sha256": sha(page_path),
                        "item_index_zero_based": item_index,
                        "trainer_id": str(item["trNo"]),
                        "trainer_name": item.get("trName"),
                        "owner_id": str(item["owNo"]),
                        "owner_name": item.get("owName"),
                    })
        distinct_links = {
            (x["trainer_id"], x["owner_id"], x["trainer_name"], x["owner_name"])
            for x in archived_matches
        }
        if len(distinct_links) > 1:
            raise ValueError("Conflicting archived API26 trainer/owner assignments")
        if archived_matches and rpt_evidence:
            trainer_name = archived_matches[0]["trainer_name"]
            owner_name = archived_matches[0]["owner_name"]
            if trainer_name not in rpt_evidence["line_text"] or owner_name not in rpt_evidence["line_text"]:
                raise ValueError("Archived official IDs disagree with official RPT names")

        audit.append({
            "meet": meet,
            "race_date": date,
            "race_no": race,
            "horse_program_no": program,
            "horse_id": horse,
            "horse_name_api4_3": name,
            "rank_raw": rank,
            "race_time_raw": race_time,
            "api4_3_source_file": source_file,
            "api4_3_source_sha256": sha(source_path),
            "api4_3_source_item_index_zero_based": int(source_index),
            "api4_3_role_fields": "all_four_keys_absent",
            "api26_recheck_source_file": alt["api26_recheck_source_file"],
            "api26_recheck_sha256": alt["api26_recheck_sha256"],
            "api26_recheck_item_index_zero_based": alt["api26_recheck_item_index_zero_based"],
            "api26_recheck_trainer_id": alt["api26_trainer_id"],
            "api26_recheck_owner_id": alt["api26_owner_id"],
            "rpt_evidence": rpt_evidence,
            "archived_api26_populated_matches": archived_matches,
            "official_id_recovery_status": (
                "crosschecked_archived_api26_exact_event_key" if archived_matches else "official_id_not_recovered"
            ),
        })

    if len(audit) != 38 or sum(x["rpt_evidence"] is not None for x in audit) != 21:
        raise ValueError("Race role gap audit partition changed")
    if sum(bool(x["archived_api26_populated_matches"]) for x in audit) != 1:
        raise ValueError("Expected one exact-key archived API26 ID recovery")
    with OUT.open("w", encoding="utf-8") as stream:
        for row in audit:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({
        "rows": len(audit),
        "rpt_line_evidence": sum(x["rpt_evidence"] is not None for x in audit),
        "archived_api26_exact_id_recovery": sum(bool(x["archived_api26_populated_matches"]) for x in audit),
        "sha256": sha(OUT),
    }))


if __name__ == "__main__":
    main()
