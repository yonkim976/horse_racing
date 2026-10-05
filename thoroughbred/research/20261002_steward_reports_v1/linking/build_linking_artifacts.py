#!/usr/bin/env python3
"""Build read-only API215 horse-paragraph research artifacts.

Only writes inside this linking directory. The research core DuckDB is opened
read-only; no application or operating database/service is accessed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
ROOT = PACKAGE.parents[2]
SOURCE_DIR = PACKAGE / "source"
OBSERVATIONS_PATH = SOURCE_DIR / "api_observations.parquet"
CORE_PATH = ROOT / "thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb"
START = "2010-01-01"
CUTOFF = "2026-09-29"

spec = importlib.util.spec_from_file_location("report_linker", HERE / "report_linker.py")
report_linker = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(report_linker)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def event_key(meet: Any, event_date: Any, race_no: Any):
    try:
        m, r = int(meet), int(race_no)
        d = date.fromisoformat(str(event_date)).isoformat()
    except (TypeError, ValueError):
        return None
    if m not in (1, 3, 4) or r <= 0:
        return None
    return (m, d, r)


def read_rosters() -> tuple[dict[tuple[int, str, int], list[dict[str, Any]]], int, Counter]:
    con = duckdb.connect(str(CORE_PATH), read_only=True)
    try:
        records = con.execute(
            """SELECT source_meet,result_date,result_race_no,execution_status,
                      source_file,source_item_index,horse_program_no_raw,
                      horse_id_raw,horse_name_raw
                 FROM runner_results
                WHERE try_cast(source_meet AS INTEGER) IN (1,3,4)
                  AND result_date >= '20100101' AND result_date <= '20260929'"""
        ).fetchall()
        columns = [d[0] for d in con.description]
    finally:
        con.close()
    grouped: dict[tuple[int, str, int], list[dict[str, Any]]] = defaultdict(list)
    statuses: Counter = Counter()
    eligible_count = 0
    for values in records:
        row = dict(zip(columns, values))
        key = event_key(row["source_meet"], f"{row['result_date'][:4]}-{row['result_date'][4:6]}-{row['result_date'][6:8]}", row["result_race_no"])
        if key is None:
            continue
        grouped[key].append(row)
        statuses[str(row["execution_status"])] += 1
        eligible_count += 1
    return grouped, eligible_count, statuses


def main() -> None:
    if not OBSERVATIONS_PATH.is_file() or not CORE_PATH.is_file():
        raise SystemExit("required pinned source or research core file is missing")
    source_rows = pq.read_table(OBSERVATIONS_PATH).to_pylist()
    api_rows = [row for row in source_rows if row.get("dataset") == "api215_judge_report"]
    scoped_rows = []
    for row in api_rows:
        event_date = row.get("race_date_iso")
        meet = row.get("actual_meet_code")
        if row.get("row_scope_status") != "included" or not event_date or not START <= event_date <= CUTOFF or meet not in (1, 3, 4):
            continue
        scoped_rows.append(row)
    rosters, roster_row_count, roster_execution_status_counts = read_rosters()
    occurrence_ids = [f"{r['capture_id']}|{r['source_location']}" for r in scoped_rows]
    if len(occurrence_ids) != len(set(occurrence_ids)):
        raise SystemExit("API source occurrence locator collision")

    result_names = {
        "event_paragraphs": "paragraphs",
        "event_sentences": "sentences",
        "horse_mentions": "mentions",
        "horse_links": "links",
        "marker_residuals": "marker_residuals",
    }
    tables: dict[str, list[dict[str, Any]]] = {name: [] for name in result_names}
    for source_row, observation_locator in zip(scoped_rows, occurrence_ids):
        report = dict(source_row)
        report["observation_locator"] = observation_locator
        key = event_key(source_row.get("actual_meet_code"), source_row.get("race_date_iso"), source_row.get("rcNo"))
        result = report_linker.process_report(report, rosters)
        for output_name, result_name in result_names.items():
            tables[output_name].extend(result[result_name])

    output_paths: dict[str, Path] = {}
    for name, rows in tables.items():
        out = HERE / f"report_{name}.parquet"
        table = pa.Table.from_pylist(rows) if rows else pa.table({})
        pq.write_table(table, out, compression="zstd", version="2.6")
        output_paths[name] = out

    status_counts = Counter(row.get("candidate_status") for row in tables["horse_mentions"])
    context_counts = Counter(row.get("target_context_status") for row in tables["event_paragraphs"])
    field_state_counts = Counter((row.get("report_text_field"), row.get("paragraph_state")) for row in tables["event_paragraphs"])
    summary = {
        "scope": {"start_inclusive": START, "end_inclusive": CUTOFF, "actual_meet_codes": [1, 3, 4], "excluded_meet_code": 2},
        "api215_source_observations_in_scope": len(scoped_rows),
        "api215_source_observation_count_before_scope": len(api_rows),
        "source_occurrence_locator_unique": True,
        "core_event_roster_row_count": roster_row_count,
        "core_event_key_count": len(rosters),
        "core_roster_execution_status_counts": dict(roster_execution_status_counts),
        "derived_rows": {name: len(rows) for name, rows in tables.items()},
        "paragraph_context_status_counts": dict(context_counts),
        "mention_candidate_status_counts": dict(status_counts),
        "api215_text_field_state_counts": {f"{field}:{state}": count for (field, state), count in field_state_counts.items()},
        "capture_timestamp_is_historical_publication_time": False,
        "all_links_non_attributive": True,
    }
    (HERE / "build_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    pinned_inputs = [OBSERVATIONS_PATH, SOURCE_DIR / "api_page_ledger.parquet", SOURCE_DIR / "api_exclusions.parquet", SOURCE_DIR / "source_manifest.json", CORE_PATH]
    observations_sha256 = sha256_file(OBSERVATIONS_PATH)
    manifest = {
        "artifact": "KRA API215 steward report horse-paragraph research linking v1",
        "manifest_status": "complete",
        "status": "complete",
        "built_at_utc": None,
        "capture_time_semantics": "source_captured_at_utc is retrieval time only; publication/availability time not verified",
        "source_observations_sha256": observations_sha256,
        "source_files": [
            {"path": str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p), "sha256": sha256_file(p), "bytes": p.stat().st_size}
            for p in pinned_inputs
        ],
        "builder_file": {"path": str(Path(__file__).relative_to(ROOT)), "sha256": sha256_file(Path(__file__)), "bytes": Path(__file__).stat().st_size},
        "parser_file": {"path": str((HERE / "report_linker.py").relative_to(ROOT)), "sha256": sha256_file(HERE / "report_linker.py"), "bytes": (HERE / "report_linker.py").stat().st_size},
        "readme_file": {"path": str((HERE / "README.md").relative_to(ROOT)), "sha256": sha256_file(HERE / "README.md"), "bytes": (HERE / "README.md").stat().st_size},
        "build_summary_file": {"path": "build_summary.json", "sha256": sha256_file(HERE / "build_summary.json"), "bytes": (HERE / "build_summary.json").stat().st_size},
        "summary": summary,
        "outputs": {
            name: {"path": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size,
                   "rows": len(tables[name]), "columns": pq.read_schema(path).names}
            for name, path in output_paths.items()
        },
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
