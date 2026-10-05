#!/usr/bin/env python3
"""Extract race sectional fields directly from archived KRA API4_3 responses.

The official result export is the runner spine. Only runners belonging to
confirmed executed races are eligible. Zero/empty API fields mean unavailable;
positive fields retain the exact source field and raw value in a long table.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import shutil
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[3]
RACE = ROOT / "thoroughbred/research/20260929_race_results_api_v1"
OUT = ROOT / "thoroughbred/data/section_api_2010_20260929_v1"

SEOUL_POINTS = (
    ("S1F", "seS1fAccTime", "sjS1fOrd"),
    ("1C", "se_1cAccTime", "sj_1cOrd"),
    ("2C", "se_2cAccTime", "sj_2cOrd"),
    ("3C", "se_3cAccTime", "sj_3cOrd"),
    ("4C", "se_4cAccTime", "sj_4cOrd"),
    ("G3F", "seG3fAccTime", "sjG3fOrd"),
    ("G1F", "seG1fAccTime", "sjG1fOrd"),
)
YEONGNAM_POINTS = (
    ("S1F", "buS1fAccTime", "buS1fOrd"),
    ("G8F", "buG8fAccTime", "buG8fOrd"),
    ("G6F", "buG6fAccTime", "buG6fOrd"),
    ("G4F", "buG4fAccTime", "buG4fOrd"),
    ("G3F", "buG3fAccTime", "buG3fOrd"),
    ("G2F", "buG2fAccTime", "buG2fOrd"),
    ("G1F", "buG1fAccTime", "buG1fOrd"),
)
YEONGNAM_INTERVALS = (
    ("S1F", "segment_time", "buS1fTime"),
    ("10F_8F", "segment_time", "bu_10_8fTime"),
    ("8F_6F", "segment_time", "bu_8_6fTime"),
    ("6F_4F", "segment_time", "bu_6_4fTime"),
    ("4F_2F", "segment_time", "bu_4_2fTime"),
    ("3F_G", "closing_time", "bu_3fGTime"),
    ("2F_G", "closing_time", "bu_2fGTime"),
    ("1F_G", "closing_time", "bu_1fGTime"),
)

MEASUREMENT_SCHEMA = pa.schema([
    ("meet", pa.int8()), ("race_date", pa.string()), ("race_no", pa.int16()),
    ("horse_id", pa.string()), ("horse_program_no", pa.int16()),
    ("point_code", pa.string()), ("measure_kind", pa.string()),
    ("source_field", pa.string()), ("raw_value", pa.string()),
    ("time_ms", pa.int32()), ("passing_order", pa.int16()),
    ("source_file", pa.string()), ("source_item_index", pa.int32()),
])
COVERAGE_SCHEMA = pa.schema([
    ("meet", pa.int8()), ("race_date", pa.string()), ("race_no", pa.int16()),
    ("horse_id", pa.string()), ("horse_program_no", pa.int16()),
    ("time_measurements", pa.int16()), ("passing_measurements", pa.int16()),
    ("has_section_data", pa.bool_()),
    ("source_file", pa.string()), ("source_item_index", pa.int32()),
])
ISSUE_SCHEMA = pa.schema([
    ("meet", pa.int8()), ("race_date", pa.string()), ("race_no", pa.int16()),
    ("horse_id", pa.string()), ("source_field", pa.string()),
    ("raw_value", pa.string()), ("issue", pa.string()),
    ("source_file", pa.string()), ("source_item_index", pa.int32()),
])


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_positive(value: object, measure_kind: str) -> tuple[int | None, str | None]:
    if value is None or str(value).strip() == "":
        return None, None
    raw = str(value).strip()
    try:
        number = Decimal(raw)
    except InvalidOperation:
        return None, "not_numeric"
    if not number.is_finite():
        return None, "not_finite"
    if number == 0:
        return None, None
    # KRA uses 99 as a special non-passing rank (for example a stopped horse).
    if measure_kind == "passing_order" and number == 99:
        return None, None
    if number < 0:
        return None, "negative_value"
    if measure_kind == "passing_order":
        if number != number.to_integral_value() or number > 89:
            return None, "invalid_passing_order"
        return int(number), None
    millis = (number * 1000).to_integral_value(rounding=ROUND_HALF_UP)
    if millis > 2_147_483_647:
        return None, "time_out_of_range"
    return int(millis), None


def rows_to_table(rows: list[dict], schema: pa.Schema) -> pa.Table:
    return pa.Table.from_pylist(rows, schema=schema)


def read_result_spine() -> dict[str, dict[int, dict[str, str]]]:
    grouped: dict[str, dict[int, dict[str, str]]] = defaultdict(dict)
    with (RACE / "runner_results.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["execution_status"] != "executed_plan_and_result":
                continue
            if row["in_plan_api"] != "1":
                raise ValueError("A confirmed runner is absent from the plan")
            index = int(row["source_item_index"])
            file_rows = grouped[row["source_file"]]
            if index in file_rows:
                raise ValueError(f"Duplicate API source pointer: {row['source_file']}:{index}")
            file_rows[index] = row
    if sum(map(len, grouped.values())) != 330_465:
        raise ValueError("Confirmed runner spine count changed")
    return grouped


def main() -> None:
    if OUT.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {OUT}")
    result_manifest = json.loads((RACE / "manifest.json").read_text(encoding="utf-8"))
    expected_result_sha = result_manifest["outputs"]["runner_results.csv"]["sha256"]
    if sha(RACE / "runner_results.csv") != expected_result_sha:
        raise ValueError("Official runner export hash differs from its manifest")
    spine = read_result_spine()
    temp = OUT.with_name(OUT.name + ".building")
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True)
    paths = {name: temp / name for name in (
        "section_measurements.parquet", "runner_section_coverage.parquet", "section_parse_issues.parquet")}
    writers = {
        "section_measurements.parquet": pq.ParquetWriter(paths["section_measurements.parquet"], MEASUREMENT_SCHEMA, compression="zstd"),
        "runner_section_coverage.parquet": pq.ParquetWriter(paths["runner_section_coverage.parquet"], COVERAGE_SCHEMA, compression="zstd"),
        "section_parse_issues.parquet": pq.ParquetWriter(paths["section_parse_issues.parquet"], ISSUE_SCHEMA, compression="zstd"),
    }
    schemas = {"section_measurements.parquet": MEASUREMENT_SCHEMA,
               "runner_section_coverage.parquet": COVERAGE_SCHEMA,
               "section_parse_issues.parquet": ISSUE_SCHEMA}
    counts: Counter[str] = Counter()
    by_meet: Counter[str] = Counter()
    file_inventory = []
    try:
        for relative_path, selected in sorted(spine.items()):
            source = ROOT / relative_path
            if not source.is_file():
                raise FileNotFoundError(source)
            with gzip.open(source, "rt", encoding="utf-8") as stream:
                payload = json.load(stream)
            body = payload["response"]["body"]
            items = body["items"]["item"]
            if isinstance(items, dict):
                items = [items]
            if len(items) != int(body["totalCount"]):
                raise ValueError(f"Incomplete official API response: {relative_path}")
            measurements: list[dict] = []
            coverage: list[dict] = []
            issues: list[dict] = []
            for index, runner in sorted(selected.items()):
                source_row = items[index]
                meet = int(runner["source_meet"])
                day = runner["result_date"]
                race_no = int(runner["result_race_no"])
                horse_id = runner["horse_id_raw"].strip()
                horse_no = int(runner["horse_program_no_raw"])
                if (str(source_row.get("rcDate")), int(source_row.get("rcNo")),
                    str(source_row.get("hrNo")).strip(), int(source_row.get("chulNo"))) != (
                    day, race_no, horse_id, horse_no):
                    raise ValueError(f"API item/runner mismatch: {relative_path}:{index}")
                if f"meet_{meet}.json.gz" != source.name:
                    raise ValueError(f"API request meet mismatch: {relative_path}:{index}")
                base = {"meet": meet, "race_date": day, "race_no": race_no,
                        "horse_id": horse_id, "horse_program_no": horse_no,
                        "source_file": relative_path, "source_item_index": index}
                time_count = rank_count = 0
                specs = SEOUL_POINTS if meet == 1 else YEONGNAM_POINTS
                field_defs = [(point, "cumulative_time", time_field) for point, time_field, _ in specs]
                field_defs += [(point, "passing_order", rank_field) for point, _, rank_field in specs]
                if meet in (3, 4):
                    field_defs += [(point, kind, field) for point, kind, field in YEONGNAM_INTERVALS]
                for point, kind, field in field_defs:
                    raw = source_row.get(field)
                    value, issue = parse_positive(raw, kind)
                    if issue:
                        issues.append({**base, "source_field": field, "raw_value": str(raw), "issue": issue})
                    if value is None:
                        continue
                    measurements.append({**base, "point_code": point, "measure_kind": kind,
                                         "source_field": field, "raw_value": str(raw),
                                         "time_ms": value if kind != "passing_order" else None,
                                         "passing_order": value if kind == "passing_order" else None})
                    if kind == "passing_order":
                        rank_count += 1
                    else:
                        time_count += 1
                    counts[kind] += 1
                coverage.append({**base, "time_measurements": time_count,
                                 "passing_measurements": rank_count,
                                 "has_section_data": bool(time_count or rank_count)})
                by_meet[str(meet)] += 1
            for name, rows in (("section_measurements.parquet", measurements),
                               ("runner_section_coverage.parquet", coverage),
                               ("section_parse_issues.parquet", issues)):
                if rows:
                    writers[name].write_table(rows_to_table(rows, schemas[name]))
            counts["runners"] += len(coverage)
            counts["runners_with_section_data"] += sum(r["has_section_data"] for r in coverage)
            counts["parse_issues"] += len(issues)
            file_inventory.append({"path": relative_path, "compressed_sha256": sha(source),
                                   "api_items": len(items), "selected_confirmed_runners": len(selected)})
    finally:
        for writer in writers.values():
            writer.close()

    db = duckdb.connect()
    measure = str(paths["section_measurements.parquet"])
    cover = str(paths["runner_section_coverage.parquet"])
    checks = {
        "coverage_equals_confirmed_runner_spine": db.execute(
            "SELECT count(*)=330465 FROM read_parquet(?)", [cover]).fetchone()[0],
        "coverage_natural_key_unique": db.execute(
            "SELECT count(*)=count(DISTINCT (meet,race_date,race_no,horse_id)) "
            "FROM read_parquet(?)", [cover]).fetchone()[0],
        "measurement_source_fields_unique_per_runner": db.execute(
            "SELECT count(*)=count(DISTINCT (meet,race_date,race_no,horse_id,source_field)) "
            "FROM read_parquet(?)", [measure]).fetchone()[0],
        "measurements_all_have_coverage": db.execute(
            "SELECT count(*)=0 FROM read_parquet(?) m LEFT JOIN read_parquet(?) c "
            "USING(meet,race_date,race_no,horse_id,horse_program_no) "
            "WHERE c.horse_id IS NULL", [measure, cover]).fetchone()[0],
        "no_jeju_or_out_of_scope_dates": db.execute(
            "SELECT count(*)=0 FROM read_parquet(?) "
            "WHERE meet NOT IN (1,3,4) OR race_date<'20100101' OR race_date>'20260929'",
            [cover]).fetchone()[0],
        "values_positive": db.execute(
            "SELECT count(*)=0 FROM read_parquet(?) "
            "WHERE (measure_kind='passing_order' AND (passing_order IS NULL OR passing_order<=0 OR time_ms IS NOT NULL)) "
            "OR (measure_kind!='passing_order' AND (time_ms IS NULL OR time_ms<=0 OR passing_order IS NOT NULL))",
            [measure]).fetchone()[0],
    }
    db.close()
    if not all(checks.values()):
        raise ValueError(f"Section API export checks failed: {checks}")
    manifest = {
        "source": "KRA API4_3/raceResult_3 archived response",
        "scope": "2010-01-01 through 2026-09-29, confirmed races in meet 1/3/4",
        "runner_spine": str((RACE / "runner_results.csv").relative_to(ROOT)),
        "runner_spine_sha256": expected_result_sha,
        "source_files": file_inventory,
        "counts": dict(counts), "confirmed_runner_counts_by_meet": dict(by_meet),
        "output_files": {name: {"path": str((OUT / name).relative_to(ROOT)), "sha256": sha(path),
                                "rows": db_count(path)} for name, path in paths.items()},
        "checks": checks,
        "interpretation": "All raw API fields and source pointers are retained. Zero/empty fields are unavailable, not measured zero."
    }
    (temp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, OUT)
    print(json.dumps({"output": str(OUT), "counts": dict(counts), "checks": checks}, ensure_ascii=False))


def db_count(path: Path) -> int:
    db = duckdb.connect()
    try:
        return db.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]
    finally:
        db.close()


if __name__ == "__main__":
    main()
