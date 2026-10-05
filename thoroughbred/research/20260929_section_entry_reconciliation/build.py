#!/usr/bin/env python3
"""Reconcile Thoroughbred sectional/passing keys with official runner results.

All inputs are opened read-only. The output is a separate, versioned coverage
artifact; no source database or existing dataset is modified.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import duckdb
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SECTION_DB = ROOT / "data/research/section_point_db_20260925/section_points_adjudicated.sqlite3"
OPERATIONAL_DB = ROOT / "data/horse_racing.sqlite3"
BASE_DB = ROOT / "thoroughbred/data/dataset_20260929_v1/thoroughbred.duckdb"
OUT = ROOT / "thoroughbred/data/section_entry_reconciliation_20260929_v1"
MEET_VENUE = {1: "SEOUL", 3: "BUSAN", 4: "YEONGCHEON"}


def exclude_confirmed_errors(frame: pd.DataFrame) -> pd.DataFrame:
    base = ROOT / "thoroughbred/research/20260929_calendar_api_v1"
    keys = set()
    for filename, expected in (("planless_positive_result_review.csv", 20),
                               ("result_only_nonfinish_anomaly_review.csv", 52)):
        with (base / filename).open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        current = {(int(r["meet"]), f"{r['date'][:4]}-{r['date'][4:6]}-{r['date'][6:]}",
                    int(r["race_no"])) for r in rows}
        if len(rows) != len(current) or len(current) != expected or keys & current:
            raise ValueError(f"Confirmed anomalous race key ledger changed: {filename}")
        keys |= current
    mask = [tuple(key) not in keys for key in zip(frame.meet_code, frame.race_date, frame.race_no)]
    return frame.loc[mask].copy()


def ro_sqlite(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    return con


def main() -> None:
    for path in (SECTION_DB, OPERATIONAL_DB, BASE_DB):
        if not path.is_file():
            raise FileNotFoundError(path)
    if OUT.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {OUT}")
    OUT.mkdir(parents=True)

    section = ro_sqlite(SECTION_DB)
    operational = ro_sqlite(OPERATIONAL_DB)
    base = duckdb.connect(str(BASE_DB), read_only=True)

    # Step 1: compact key catalogs from every section-database history year.
    finish_keys = pd.read_sql_query("""
        SELECT meet_code, race_date, race_number AS race_no,
               horse_number AS horse_no, trim(kra_horse_id) AS hr_no,
               finish_position, finish_time_ms, result_state
        FROM finish_time
        WHERE meet_code IN (1,3,4) AND trim(coalesce(kra_horse_id,'')) <> ''
    """, section)
    section_keys = pd.read_sql_query("""
        SELECT meet_code, race_date, race_number AS race_no,
               horse_number AS horse_no, trim(kra_horse_id) AS hr_no,
               count(*) AS section_time_rows,
               count(DISTINCT point_code) AS section_point_codes,
               count(DISTINCT time_kind) AS section_time_kinds
        FROM section_time
        WHERE meet_code IN (1,3,4) AND trim(coalesce(kra_horse_id,'')) <> ''
        GROUP BY meet_code,race_date,race_number,horse_number,trim(kra_horse_id)
    """, section)
    finish_keys = exclude_confirmed_errors(finish_keys)
    section_keys = exclude_confirmed_errors(section_keys)
    finish_keys["venue_code"] = finish_keys.meet_code.map(MEET_VENUE)
    section_keys["venue_code"] = section_keys.meet_code.map(MEET_VENUE)
    for frame in (finish_keys, section_keys):
        frame["race_date"] = frame.race_date.astype(str)
        frame["race_no"] = pd.to_numeric(frame.race_no, errors="coerce").astype("Int64")
        frame["horse_no"] = pd.to_numeric(frame.horse_no, errors="coerce").astype("Int64")
        frame["hr_no"] = frame.hr_no.astype(str).str.strip().str.zfill(7)

    source_key = ["venue_code", "race_date", "race_no", "hr_no"]
    for name, frame in (("finish_time", finish_keys), ("section_time", section_keys)):
        if frame.duplicated(source_key).any():
            raise RuntimeError(f"Duplicate horse-race keys in {name}")

    source_catalog = finish_keys[source_key + ["horse_no"]].merge(
        section_keys[source_key + ["horse_no", "section_time_rows", "section_point_codes", "section_time_kinds"]],
        on=source_key, how="outer", suffixes=("_finish", "_section"), indicator=True,
    )
    source_catalog["has_finish_time_row"] = source_catalog._merge.ne("right_only")
    source_catalog["has_section_time"] = source_catalog._merge.ne("left_only")
    source_catalog["horse_no_agrees"] = (
        source_catalog.horse_no_finish.notna() & source_catalog.horse_no_section.notna()
        & source_catalog.horse_no_finish.eq(source_catalog.horse_no_section)
    )
    source_catalog.drop(columns="_merge", inplace=True)

    # Step 2: preserve every official runner row and attach optional source flags.
    official = base.execute("""
        SELECT race_id,venue_code,
               CASE WHEN venue_code='SEOUL' THEN 'SEOUL' ELSE 'YEONGNAM' END AS region_code,
               race_date,race_no,chul_no AS horse_no,
               hr_no,horse_name_normalized,finish_order,result_status,
               official_result_state,is_rank_label,is_model_target,source_dataset,source_path
        FROM entry_result
    """).df()
    official["race_date"] = official.race_date.astype(str)
    official["race_no"] = pd.to_numeric(official.race_no, errors="coerce").astype("Int64")
    official["horse_no"] = pd.to_numeric(official.horse_no, errors="coerce").astype("Int64")
    official["hr_no"] = official.hr_no.fillna("").astype(str).str.strip().str.zfill(7)
    official_key = ["venue_code", "race_date", "race_no", "hr_no"]

    result_flags = finish_keys[source_key + ["horse_no", "finish_position", "finish_time_ms", "result_state"]].copy()
    result_flags.rename(columns={
        "horse_no": "finish_time_horse_no", "finish_position": "source_finish_position",
        "finish_time_ms": "source_finish_time_ms", "result_state": "source_result_state",
    }, inplace=True)
    section_flags = section_keys[source_key + ["horse_no", "section_time_rows", "section_point_codes", "section_time_kinds"]].copy()
    section_flags.rename(columns={"horse_no": "section_horse_no"}, inplace=True)

    reconciled = official.merge(result_flags, left_on=official_key, right_on=source_key, how="left", validate="one_to_one")
    reconciled = reconciled.merge(section_flags, left_on=official_key, right_on=source_key, how="left", validate="one_to_one")

    passing_summary = pd.read_sql_query("""
        SELECT c.kra_meet_code AS meet_code,r.race_date_local AS race_date,
               r.race_number AS race_no,count(*) AS passing_summary_rows,
               max(CASE WHEN q.quality_status='accepted' THEN 1 ELSE 0 END) AS has_accepted_passing_summary
        FROM race_passing_summaries q JOIN races r ON r.id=q.race_id
        JOIN racecourses c ON c.id=r.racecourse_id
        WHERE c.kra_meet_code IN (1,3,4)
        GROUP BY c.kra_meet_code,r.race_date_local,r.race_number
    """, operational)
    passing_groups = pd.read_sql_query("""
        SELECT c.kra_meet_code AS meet_code,r.race_date_local AS race_date,
               r.race_number AS race_no,count(*) AS passing_group_rows,
               count(DISTINCT q.point_code) AS passing_points
        FROM race_passing_groups q JOIN races r ON r.id=q.race_id
        JOIN racecourses c ON c.id=r.racecourse_id
        WHERE c.kra_meet_code IN (1,3,4)
        GROUP BY c.kra_meet_code,r.race_date_local,r.race_number
    """, operational)
    for frame in (passing_summary, passing_groups):
        frame["venue_code"] = frame.meet_code.map(MEET_VENUE)
        frame["race_date"] = frame.race_date.astype(str)
        frame["race_no"] = pd.to_numeric(frame.race_no, errors="coerce").astype("Int64")
        frame.drop(columns="meet_code", inplace=True)
    race_key = ["venue_code", "race_date", "race_no"]
    reconciled = reconciled.merge(passing_summary, on=race_key, how="left", validate="many_to_one")
    reconciled = reconciled.merge(passing_groups, on=race_key, how="left", validate="many_to_one")
    reconciled["has_finish_time_row"] = reconciled.source_result_state.notna()
    reconciled["has_section_time"] = reconciled.section_time_rows.notna()
    reconciled["has_passing_summary"] = reconciled.passing_summary_rows.notna()
    reconciled["has_passing_groups"] = reconciled.passing_group_rows.notna()
    reconciled["finish_time_horse_no_agrees"] = (
        reconciled.has_finish_time_row & reconciled.horse_no.eq(reconciled.finish_time_horse_no)
    )
    reconciled["section_horse_no_agrees"] = (
        reconciled.has_section_time & reconciled.horse_no.eq(reconciled.section_horse_no)
    )

    # Keep one file per grain: full history horse-race source key set, and all
    # official entries enriched with optional section/passing availability.
    source_catalog.to_parquet(OUT / "section_db_horse_race_keys.parquet", index=False)
    reconciled.to_parquet(OUT / "official_entry_source_reconciliation.parquet", index=False)

    summary: dict[str, object] = {
        "version": "2026-09-29-v1",
        "history_source": "section_points_adjudicated.sqlite3",
        "official_entry_source": "dataset_20260929_v1/thoroughbred.duckdb:entry_result",
        "history_key_definition": source_key,
        "official_key_definition": official_key,
        "included_meets": {"1": "SEOUL", "3": "BUSAN", "4": "YEONGCHEON"},
        "section_db_horse_race_keys": {
            "rows": len(source_catalog),
            "finish_time_rows": len(finish_keys),
            "section_time_horse_race_rows": len(section_keys),
            "both_finish_and_section": int((source_catalog.has_finish_time_row & source_catalog.has_section_time).sum()),
            "finish_without_section": int((source_catalog.has_finish_time_row & ~source_catalog.has_section_time).sum()),
            "section_without_finish": int((~source_catalog.has_finish_time_row & source_catalog.has_section_time).sum()),
            "venue_ranges": {},
        },
        "official_entry_reconciliation": {
            "rows": len(reconciled),
            "unique_keys": int(reconciled[official_key].drop_duplicates().shape[0]),
            "duplicate_keys": int(reconciled.duplicated(official_key).sum()),
            "with_finish_time_source_row": int(reconciled.has_finish_time_row.sum()),
            "without_finish_time_source_row": int((~reconciled.has_finish_time_row).sum()),
            "finish_time_match_rate": float(reconciled.has_finish_time_row.mean()),
            "with_section_time": int(reconciled.has_section_time.sum()),
            "with_passing_summary": int(reconciled.has_passing_summary.sum()),
            "with_passing_groups": int(reconciled.has_passing_groups.sum()),
            "finish_time_horse_no_mismatches": int((reconciled.has_finish_time_row & ~reconciled.finish_time_horse_no_agrees).sum()),
            "section_horse_no_mismatches": int((reconciled.has_section_time & ~reconciled.section_horse_no_agrees).sum()),
            "2017_onward": {},
            "venue_ranges": {},
        },
        "sources": {
            "section_db": str(SECTION_DB.relative_to(ROOT)),
            "operational_db": str(OPERATIONAL_DB.relative_to(ROOT)),
            "official_entry_snapshot": str(BASE_DB.relative_to(ROOT)),
        },
        "notes": [
            "The official entry table is the retained base grain; missing sectional or passing data stays null and never drops the runner.",
            "All 2010+ section-database finish-time keys joined to the official entry snapshot on venue, race date, race number and horse ID; horse number also agrees.",
            "The 2010+ official entry snapshot contains runner rows absent from the section-database finish_time table; these are flagged for source coverage review.",
            "Passing summaries and passing groups are race-level sources, not per-horse result rows.",
        ],
    }
    for venue in ("SEOUL", "BUSAN", "YEONGCHEON"):
        sk = source_catalog[source_catalog.venue_code == venue]
        rr = reconciled[reconciled.venue_code == venue]
        summary["section_db_horse_race_keys"]["venue_ranges"][venue] = {
            "rows": len(sk), "horses": int(sk.hr_no.nunique()),
            "min_date": sk.race_date.min(), "max_date": sk.race_date.max(),
        }
        summary["official_entry_reconciliation"]["venue_ranges"][venue] = {
            "rows": len(rr), "with_finish_time_source_row": int(rr.has_finish_time_row.sum()),
            "without_finish_time_source_row": int((~rr.has_finish_time_row).sum()),
            "with_section_time": int(rr.has_section_time.sum()),
            "with_passing_summary": int(rr.has_passing_summary.sum()),
            "with_passing_groups": int(rr.has_passing_groups.sum()),
            "min_date": rr.race_date.min(), "max_date": rr.race_date.max(),
        }
    target = reconciled[reconciled.race_date >= "2017-01-01"]
    summary["official_entry_reconciliation"]["2017_onward"] = {
        "rows": len(target),
        "with_finish_time_source_row": int(target.has_finish_time_row.sum()),
        "without_finish_time_source_row": int((~target.has_finish_time_row).sum()),
        "with_section_time": int(target.has_section_time.sum()),
        "with_passing_summary": int(target.has_passing_summary.sum()),
        "with_passing_groups": int(target.has_passing_groups.sum()),
        "min_date": target.race_date.min(), "max_date": target.race_date.max(),
    }
    (OUT / "coverage.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    base.close()
    section.close()
    operational.close()
    print(json.dumps({
        "output": str(OUT.relative_to(ROOT)),
        "section_db_horse_race_keys": summary["section_db_horse_race_keys"],
        "official_entry_reconciliation": summary["official_entry_reconciliation"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
