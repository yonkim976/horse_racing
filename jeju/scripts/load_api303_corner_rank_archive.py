"""Load the preserved KRA API303 corner-rank archive into the Jeju core DB.

This script never calls the API and never reads TXT/RPT data. The raw pages are
verified against the existing manifest before any SQLite changes are made.
The migration only adds a source table and views; API4_3 rows remain intact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "jeju/data/jeju_native_core.sqlite3"
SOURCE_RUN = REPO_ROOT / (
    "jeju/research/20260929_api_detail_sources/raw/full_year_sections_passing/"
    "20260929T143902.196014Z"
)
MIGRATION = REPO_ROOT / "jeju/data/schema/migrations/20260930_add_api303_corner_rank.sql"
EXPECTED_YEARS = list(range(2002, 2027))
EXPECTED_TOTAL = 19_933
OPERATION = "corner_rank"
ATTEMPT_ID = "20260929T143902.196014Z"
DATASET_NAME = "한국마사회_경마코너별통과순위_주로빠르기"
PARSER_VERSION = "jeju-api303-corner-rank-archive-v1"
REQUIRED_FIELDS = {
    "corner_1", "corner_2", "corner_3", "corner_4", "corner_5",
    "corner_6", "corner_7", "corner_8", "corner_9", "meet",
    "passtime_3f", "passtime_4f", "rcDate", "rcNo",
}
OPTIONAL_FIELDS = {"tempo"}
TRACKED_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS
CORNER_FIELDS = [f"corner_{i}" for i in range(1, 10)]


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def safe_relative(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def date_iso(value: object) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) != 8:
        return None
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def raw_text(value: object) -> str | None:
    return None if value is None else str(value)


def parse_items(raw: bytes) -> tuple[dict, list[dict]]:
    payload = json.loads(raw)
    body = payload.get("response", {}).get("body", {})
    values = (body.get("items") or {}).get("item")
    if values is None:
        return body, []
    if isinstance(values, dict):
        return body, [values]
    if isinstance(values, list) and all(isinstance(row, dict) for row in values):
        return body, values
    raise ValueError("Unexpected API303 item collection shape")


def public_params(url: str, fallback: dict) -> str:
    if url:
        params = {
            key: value for key, value in parse_qsl(urlsplit(url).query, keep_blank_values=True)
            if key.lower() not in {"servicekey", "service_key"}
        }
        return canonical_json(params)
    return canonical_json(fallback)


def inspect_archive() -> tuple[dict, list[dict], dict]:
    manifest_path = SOURCE_RUN / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("meet") != 2:
        raise ValueError(f"Expected archived request meet=2, got {manifest.get('meet')!r}")
    dataset = manifest.get("datasets", {}).get("passing_corner")
    if not dataset or dataset.get("operation") != OPERATION:
        raise ValueError("API303 passing_corner dataset metadata is missing or unexpected")
    yearly = dataset.get("yearly", [])
    if [int(item.get("year", -1)) for item in yearly] != EXPECTED_YEARS:
        raise ValueError("Archive does not contain exactly one partition for each year 2002–2026")

    pages: list[dict] = []
    report_by_year: dict[str, dict] = {}
    all_keys: set[tuple[str, int, int]] = set()
    total_rows = 0
    duplicate_keys = 0
    expected_endpoint = "/API303/corner_rank"
    if dataset.get("endpoint") != expected_endpoint:
        raise ValueError(f"Unexpected API303 endpoint {dataset.get('endpoint')!r}")

    for year_meta in yearly:
        year = int(year_meta["year"])
        if year_meta.get("status") != "complete_year_partition":
            raise ValueError(f"Year partition {year} is not marked complete")
        page_meta = year_meta.get("pages", [])
        expected_pages = int(year_meta.get("expected_page_count", -1))
        if len(page_meta) != expected_pages or int(year_meta.get("actual_page_count", -1)) != len(page_meta):
            raise ValueError(f"Year {year}: page count disagrees with the manifest")
        page_rows = 0
        schema_signatures: Counter[str] = Counter()
        field_value_shapes: dict[str, Counter[str]] = {field: Counter() for field in TRACKED_FIELDS}
        for page in page_meta:
            if int(page.get("status_code", 0)) != 200:
                raise ValueError(f"Year {year} page {page.get('page_no')}: not HTTP 200")
            rel = page.get("response_file")
            if not rel:
                raise ValueError(f"Year {year}: response file path missing")
            raw_path = SOURCE_RUN / rel
            raw = raw_path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest != page.get("response_sha256"):
                raise ValueError(f"SHA-256 mismatch for {raw_path}")
            body, rows = parse_items(raw)
            if len(rows) != int(page.get("actual_page_rows", -1)):
                raise ValueError(f"Page row count mismatch for {raw_path}")
            if int(body.get("pageNo", -1)) != int(page.get("page_no", -2)):
                raise ValueError(f"Response pageNo mismatch for {raw_path}")
            if int(body.get("totalCount", -1)) != int(page.get("api_total_count", -2)):
                raise ValueError(f"Response totalCount mismatch for {raw_path}")
            if int(page.get("response_bytes", -1)) != len(raw):
                raise ValueError(f"Response byte count mismatch for {raw_path}")

            for local_index, row in enumerate(rows, 1):
                missing = REQUIRED_FIELDS - row.keys()
                if missing:
                    raise ValueError(f"API303 schema fields missing in {raw_path} row {local_index}: {sorted(missing)}")
                event_date = date_iso(row.get("rcDate"))
                if not event_date or int(event_date[:4]) != year:
                    raise ValueError(f"Row date does not match requested year in {raw_path} row {local_index}")
                try:
                    race_number = int(row["rcNo"])
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"Invalid rcNo in {raw_path} row {local_index}") from exc
                if race_number <= 0:
                    raise ValueError(f"Non-positive rcNo in {raw_path} row {local_index}")
                key = (event_date, 2, race_number)
                if key in all_keys:
                    duplicate_keys += 1
                all_keys.add(key)
                schema_signatures[canonical_json(sorted(row.keys()))] += 1
                for field in TRACKED_FIELDS:
                    if field not in row:
                        field_value_shapes[field]["key_absent"] += 1
                        continue
                    value = row.get(field)
                    if value is None:
                        shape = "json_null"
                    elif isinstance(value, str) and not value.strip():
                        shape = "blank"
                    elif isinstance(value, str) and value.strip() in {"-", "X"}:
                        shape = f"placeholder:{value.strip()}"
                    else:
                        shape = type(value).__name__
                    field_value_shapes[field][shape] += 1
            page_rows += len(rows)
            pages.append({
                "year": year,
                "page": page,
                "raw_path": raw_path,
                "raw": raw,
                "rows": rows,
            })

        expected_total = int(year_meta.get("api_total_count", -1))
        if page_rows != expected_total or int(year_meta.get("actual_total_rows", -1)) != page_rows:
            raise ValueError(f"Year {year}: partition row total mismatch ({page_rows}/{expected_total})")
        if int(year_meta.get("rows_matching_requested_year", -1)) != page_rows:
            raise ValueError(f"Year {year}: manifest date-match count mismatch")
        report_by_year[str(year)] = {
            "row_count": page_rows,
            "race_key_count": len({
                (date_iso(row.get("rcDate")), 2, int(row["rcNo"]))
                for page in pages if page["year"] == year for row in page["rows"]
            }),
            "field_key_signatures": dict(schema_signatures),
            "field_value_shapes": {key: dict(value) for key, value in field_value_shapes.items()},
        }
        total_rows += page_rows

    if total_rows != EXPECTED_TOTAL:
        raise ValueError(f"Expected exactly {EXPECTED_TOTAL} API303 rows, found {total_rows}")
    if duplicate_keys:
        raise ValueError(f"API303 contains {duplicate_keys} duplicate race keys")
    if len(all_keys) != EXPECTED_TOTAL:
        raise ValueError(f"API303 unique race keys {len(all_keys)} do not equal row count {EXPECTED_TOTAL}")
    archive_summary = {
        "source_run_id": manifest.get("run_id"),
        "official_openapi_name": DATASET_NAME,
        "endpoint": dataset["endpoint"],
        "operation": OPERATION,
        "meet_request_code": 2,
        "year_count": len(EXPECTED_YEARS),
        "page_count": len(pages),
        "row_count": total_rows,
        "unique_race_key_count": len(all_keys),
        "duplicate_race_key_count": duplicate_keys,
        "row_key_fields": ["rcDate", "meet (request meet=2)", "rcNo"],
        "required_payload_fields": sorted(REQUIRED_FIELDS),
        "optional_payload_fields": sorted(OPTIONAL_FIELDS),
        "years": report_by_year,
    }
    return manifest, pages, archive_summary


def apply_migration(conn: sqlite3.Connection) -> None:
    migration_sql = MIGRATION.read_text(encoding="utf-8")
    conn.executescript(migration_sql)


def validate_existing_import(conn: sqlite3.Connection, pages: list[dict]) -> bool:
    existing = conn.execute(
        "SELECT source_artifact_id,raw_relative_path,sha256,dataset_name FROM source_artifacts "
        "WHERE operation=? AND attempt_id=? ORDER BY raw_relative_path",
        (OPERATION, ATTEMPT_ID),
    ).fetchall()
    if not existing:
        return False
    expected = {safe_relative(page["raw_path"]): page for page in pages}
    if len(existing) != len(expected):
        raise ValueError("A partial API303 import with this attempt ID already exists")
    for artifact_id, raw_path, sha, dataset_name in existing:
        page = expected.get(raw_path)
        if page is None or sha != page["page"]["response_sha256"]:
            raise ValueError("Existing API303 artifact provenance does not match the archive")
        if dataset_name != DATASET_NAME:
            raise ValueError(f"Existing API303 artifact dataset name is not the official OpenAPI name: {dataset_name!r}")
        rows = page["rows"]
        stored = conn.execute(
            "SELECT record_index,natural_key,payload_json,payload_sha256,api_record_id "
            "FROM api_records WHERE source_artifact_id=? ORDER BY record_index",
            (artifact_id,),
        ).fetchall()
        if len(stored) != len(rows):
            raise ValueError(f"Existing API303 page has wrong record count: {raw_path}")
        for index, (record_index, natural_key, payload_json, payload_sha, record_id) in enumerate(stored, 1):
            item = rows[index - 1]
            event_date = date_iso(item["rcDate"])
            expected_key = f"{event_date}|2|{int(item['rcNo'])}"
            expected_payload = canonical_json(item)
            expected_sha = hashlib.sha256(expected_payload.encode("utf-8")).hexdigest()
            if (record_index, natural_key, payload_json, payload_sha) != (index, expected_key, expected_payload, expected_sha):
                raise ValueError(f"Existing API303 payload mismatch: {raw_path} row {index}")
            normalized = conn.execute(
                "SELECT race_date,meet_code,race_number,api_meet_raw,corner_1_raw,corner_2_raw,corner_3_raw,"
                "corner_4_raw,corner_5_raw,corner_6_raw,corner_7_raw,corner_8_raw,corner_9_raw,"
                "passtime_3f_raw,passtime_4f_raw,tempo_raw FROM api303_corner_rank_rows WHERE api_record_id=?",
                (record_id,),
            ).fetchone()
            expected_values = (
                event_date, 2, int(item["rcNo"]), raw_text(item.get("meet")),
                *[raw_text(item.get(k)) for k in CORNER_FIELDS],
                raw_text(item.get("passtime_3f")), raw_text(item.get("passtime_4f")), raw_text(item.get("tempo")),
            )
            if normalized is None or tuple(normalized) != expected_values:
                raise ValueError(f"Existing normalized API303 row mismatch: {raw_path} row {index}")
    if conn.execute("SELECT count(*) FROM api303_corner_rank_rows").fetchone()[0] != EXPECTED_TOTAL:
        raise ValueError("Existing API303 normalized row count does not match archive")
    return True


def insert_archive(conn: sqlite3.Connection, manifest: dict, pages: list[dict]) -> None:
    now = datetime.now(UTC).isoformat()
    endpoint = "https://apis.data.go.kr/B551015/API303/corner_rank"
    year_acc: dict[int, dict] = {
        year: {"rows": 0, "dates": []} for year in EXPECTED_YEARS
    }
    for page_info in pages:
        year = page_info["year"]
        page = page_info["page"]
        raw_path = page_info["raw_path"]
        raw = page_info["raw"]
        rows = page_info["rows"]
        source_url = page.get("source_url_without_key")
        fallback = {"meet": 2, "rc_year": str(year), "_type": "json"}
        params = public_params(source_url or "", fallback)
        collected_at = datetime.fromtimestamp(
            int(page.get("retrieved_at_ms", 0)) / 1000, UTC
        ).isoformat() if page.get("retrieved_at_ms") else None
        artifact_cur = conn.execute(
            """INSERT INTO source_artifacts(
                   source_family,source_role,public_dataset_id,dataset_name,endpoint,operation,
                   attempt_id,request_params_json,source_url_without_key,collected_at_utc,
                   http_status_code,content_type,raw_relative_path,response_bytes,sha256,
                   parser_version,created_at_utc)
               VALUES('kra_openapi','primary','15119851',?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                DATASET_NAME, endpoint, OPERATION, ATTEMPT_ID,
                params, source_url, collected_at, int(page.get("status_code", 200)),
                page.get("content_type"), safe_relative(raw_path), len(raw),
                hashlib.sha256(raw).hexdigest(), PARSER_VERSION, now,
            ),
        )
        artifact_id = int(artifact_cur.lastrowid)
        for record_index, row in enumerate(rows, 1):
            event_date = date_iso(row.get("rcDate"))
            race_number = int(row["rcNo"])
            natural_key = f"{event_date}|2|{race_number}"
            payload = canonical_json(row)
            payload_sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            record_cur = conn.execute(
                """INSERT INTO api_records(
                       source_artifact_id,record_index,record_type,natural_key,payload_json,payload_sha256)
                   VALUES(?,?,?,?,?,?)""",
                (artifact_id, record_index, "api303_corner_rank", natural_key, payload, payload_sha),
            )
            record_id = int(record_cur.lastrowid)
            conn.execute(
                """INSERT INTO api303_corner_rank_rows(
                       api_record_id,race_date,meet_code,race_number,api_meet_raw,
                       corner_1_raw,corner_2_raw,corner_3_raw,corner_4_raw,corner_5_raw,
                       corner_6_raw,corner_7_raw,corner_8_raw,corner_9_raw,
                       passtime_3f_raw,passtime_4f_raw,tempo_raw)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record_id, event_date, 2, race_number, row.get("meet"),
                    *[row.get(k) for k in CORNER_FIELDS],
                    row.get("passtime_3f"), row.get("passtime_4f"), row.get("tempo"),
                ),
            )
            year_acc[year]["rows"] += 1
            year_acc[year]["dates"].append(event_date)

    for year in EXPECTED_YEARS:
        meta = next(item for item in manifest["datasets"]["passing_corner"]["yearly"] if int(item["year"]) == year)
        state = year_acc[year]
        candidate_row_count = conn.execute(
            """SELECT count(*) FROM jeju_race_population_candidates c
               JOIN api303_corner_rank_rows a
                 ON a.race_date=c.race_date AND a.meet_code=c.meet_code AND a.race_number=c.race_number
               WHERE substr(c.race_date,1,4)=?""",
            (str(year),),
        ).fetchone()[0]
        notes = (
            "Existing archived official API303 full-year partition, SHA-256 verified before load. "
            "Rows are race-level and contain no horse ID; meet_code=2 is the request scope, "
            "while api_meet_raw and every source field remain preserved."
        )
        conn.execute(
            """INSERT INTO collection_coverage(
                   source_family,operation,year,attempt_id,status,page_count,api_total_count,
                   response_row_count,first_event_date,last_event_date,breed_label_counts_json,
                   candidate_row_count,notes,created_at_utc)
               VALUES('kra_openapi',?,?,?,?,?,?,?,?,?,NULL,?,?,?)""",
            (
                OPERATION, year, ATTEMPT_ID, "complete_year_partition",
                int(meta["actual_page_count"]), int(meta["api_total_count"]), state["rows"],
                min(state["dates"]), max(state["dates"]), candidate_row_count, notes, now,
            ),
        )


def database_summary(conn: sqlite3.Connection) -> dict:
    corner_has_content = " OR ".join(
        f"coalesce(trim({field}_raw), '') NOT IN ('', '-', 'X')" for field in CORNER_FIELDS
    )
    time_has_content = (
        "coalesce(trim(passtime_3f_raw), '') NOT IN ('', '0:00.0', '0:00') OR "
        "coalesce(trim(passtime_4f_raw), '') NOT IN ('', '0:00.0', '0:00')"
    )
    api303_content = conn.execute(
        f"""SELECT count(*),
                   sum(CASE WHEN {corner_has_content} THEN 1 ELSE 0 END),
                   sum(CASE WHEN NOT ({corner_has_content}) THEN 1 ELSE 0 END),
                   sum(CASE WHEN {time_has_content} THEN 1 ELSE 0 END)
            FROM api303_corner_rank_rows"""
    ).fetchone()
    api303_corner_time_cross = conn.execute(
        f"""SELECT CASE WHEN {corner_has_content} THEN 1 ELSE 0 END,
                   CASE WHEN {time_has_content} THEN 1 ELSE 0 END,
                   count(*)
            FROM api303_corner_rank_rows
            GROUP BY 1,2 ORDER BY 1,2"""
    ).fetchall()
    api4_races = conn.execute(
        "SELECT count(*) FROM (SELECT race_date,meet_code,race_number FROM race_result_rows GROUP BY 1,2,3)"
    ).fetchone()[0]
    api303_races = conn.execute("SELECT count(*) FROM api303_corner_rank_rows").fetchone()[0]
    all_join = conn.execute(
        """SELECT count(*) FROM (
               SELECT race_date,meet_code,race_number FROM race_result_rows GROUP BY 1,2,3
           ) r JOIN api303_corner_rank_rows c USING(race_date,meet_code,race_number)"""
    ).fetchone()[0]
    api303_without_result = conn.execute(
        """SELECT count(*) FROM api303_corner_rank_rows c
           LEFT JOIN (SELECT race_date,meet_code,race_number FROM race_result_rows GROUP BY 1,2,3) r
             USING(race_date,meet_code,race_number)
           WHERE r.race_date IS NULL"""
    ).fetchone()[0]
    candidate_races = conn.execute("SELECT count(*) FROM jeju_race_candidate_corner_rank_coverage").fetchone()[0]
    candidate_counts = conn.execute(
        """SELECT api303_present,api303_has_corner_order_content, count(*) AS race_count,
                  sum(candidate_horse_rows) AS candidate_horse_rows
           FROM jeju_race_candidate_corner_rank_coverage
           GROUP BY 1,2 ORDER BY 1,2"""
    ).fetchall()
    candidate_content_time_counts = conn.execute(
        """SELECT api303_present,api303_has_corner_order_content,
                  api303_has_nonzero_passing_time,count(*) AS race_count,
                  sum(candidate_horse_rows) AS candidate_horse_rows
           FROM jeju_race_candidate_corner_rank_coverage
           GROUP BY 1,2,3 ORDER BY 1,2,3"""
    ).fetchall()
    candidate_corner_without_time_by_distance = conn.execute(
        """SELECT c.race_distance_m,
                  count(DISTINCT c.race_date || '|' || c.meet_code || '|' || c.race_number) AS race_count,
                  count(*) AS candidate_horse_rows
           FROM jeju_race_candidate_corner_rank_coverage v
           JOIN jeju_race_population_candidates c
             USING(race_date,meet_code,race_number)
           WHERE v.api303_has_corner_order_content=1
             AND v.api303_has_nonzero_passing_time=0
           GROUP BY c.race_distance_m ORDER BY c.race_distance_m"""
    ).fetchall()
    candidate_time_without_corner = conn.execute(
        """SELECT race_date,race_number,candidate_horse_rows
           FROM jeju_race_candidate_corner_rank_coverage
           WHERE api303_present=1 AND api303_has_corner_order_content=0
             AND api303_has_nonzero_passing_time=1
           ORDER BY race_date,race_number"""
    ).fetchall()
    candidate_missing = conn.execute(
        """SELECT race_date,race_number,candidate_horse_rows
           FROM jeju_race_candidate_corner_rank_coverage WHERE api303_present=0
           ORDER BY race_date,race_number"""
    ).fetchall()
    candidate_all_zero_time = conn.execute(
        """SELECT count(*),sum(n) FROM (
               SELECT race_date,meet_code,race_number,count(*) AS n,
                      sum(CASE WHEN finish_time_seconds>0 THEN 1 ELSE 0 END) AS positive_n,
                      sum(CASE WHEN finish_time_seconds=0 THEN 1 ELSE 0 END) AS zero_n
               FROM jeju_race_population_candidates GROUP BY 1,2,3
           ) WHERE positive_n=0 AND zero_n=n"""
    ).fetchone()
    candidate_missing_timing = conn.execute(
        """WITH per_race AS (
               SELECT race_date,meet_code,race_number,count(*) AS n,
                      sum(CASE WHEN finish_time_seconds>0 THEN 1 ELSE 0 END) AS positive_n
               FROM jeju_race_population_candidates GROUP BY 1,2,3
           )
           SELECT CASE WHEN positive_n>0 THEN 1 ELSE 0 END AS has_positive_time,
                  count(*) AS race_count,sum(n) AS candidate_horse_rows
           FROM per_race r JOIN jeju_race_candidate_corner_rank_coverage v
             USING(race_date,meet_code,race_number)
           WHERE v.api303_present=0 GROUP BY 1 ORDER BY 1"""
    ).fetchall()
    candidate_row_count = conn.execute("SELECT count(*) FROM jeju_race_population_candidates").fetchone()[0]
    view_row_count = conn.execute("SELECT count(*) FROM jeju_race_candidate_passing_with_corner_rank").fetchone()[0]
    july7 = conn.execute(
        """SELECT count(*) FROM jeju_race_population_candidate_passing_orders
           WHERE race_date='2026-07-07'"""
    ).fetchone()[0]
    july7_races = conn.execute(
        """SELECT count(*) FROM jeju_race_candidate_corner_rank_coverage
           WHERE race_date='2026-07-07'"""
    ).fetchone()[0]
    sept = conn.execute(
        """SELECT count(*),sum(CASE WHEN coalesce(finish_time_seconds,0)>0 THEN 1 ELSE 0 END)
           FROM jeju_race_population_candidate_passing_orders
           WHERE race_date BETWEEN '2026-09-17' AND '2026-09-19'"""
    ).fetchone()
    api4_fields = ["sjS1fOrd", "sjG1fOrd", "sjG3fOrd", "sj_1cOrd", "sj_2cOrd", "sj_3cOrd", "sj_4cOrd"]
    api4_field_stats = {}
    for field in api4_fields:
        alias = "api4_3_" + field + "_raw"
        type_alias = "api4_3_" + field + "_json_type"
        # View identifiers come from the fixed local constant list above.
        rows = conn.execute(
            f"""SELECT {type_alias}, count(*) FROM jeju_race_population_candidate_passing_orders
                GROUP BY {type_alias} ORDER BY {type_alias}"""
        ).fetchall()
        values = conn.execute(
            f"""SELECT sum(CASE WHEN {alias}=0 THEN 1 ELSE 0 END),
                       sum(CASE WHEN {alias} IS NULL THEN 1 ELSE 0 END),
                       sum(CASE WHEN {alias}>0 THEN 1 ELSE 0 END)
                FROM jeju_race_population_candidate_passing_orders"""
        ).fetchone()
        api4_field_stats[field] = {
            "json_type_counts": {str(row[0]): row[1] for row in rows},
            "zero_count": values[0] or 0,
            "null_or_absent_count": values[1] or 0,
            "positive_count": values[2] or 0,
        }
    return {
        "api4_3_race_key_count": api4_races,
        "api303_row_count": api303_races,
        "api303_distinct_race_key_count": conn.execute(
            "SELECT count(*) FROM (SELECT race_date,meet_code,race_number FROM api303_corner_rank_rows GROUP BY 1,2,3)"
        ).fetchone()[0],
        "api303_corner_content_coverage": {
            "race_rows": api303_content[0],
            "has_non_placeholder_corner_order": api303_content[1] or 0,
            "placeholder_only_or_absent_corner_order": api303_content[2] or 0,
            "has_nonzero_3f_or_4f_time": api303_content[3] or 0,
            "content_rule": "at least one corner_1..corner_9 is not blank, '-', or 'X'",
            "time_rule": "at least one 3F/4F field is not blank, '0:00.0', or '0:00'",
            "corner_content_by_time_content": [
                {"has_corner_order_content": row[0], "has_nonzero_passing_time": row[1], "race_count": row[2]}
                for row in api303_corner_time_cross
            ],
        },
        "api4_3_api303_intersection_race_count": all_join,
        "api4_3_without_api303_race_count": api4_races - all_join,
        "api303_without_api4_3_race_count": api303_without_result,
        "candidate_race_count": candidate_races,
        "candidate_horse_row_count": candidate_row_count,
        "candidate_rows_after_join_count": view_row_count,
        "candidate_api303_coverage_by_presence_and_content": [
            {"api303_present": row[0], "api303_has_corner_order_content": row[1],
             "race_count": row[2], "candidate_horse_rows": row[3]}
            for row in candidate_counts
        ],
        "candidate_api303_coverage_by_corner_and_time_content": [
            {"api303_present": row[0], "api303_has_corner_order_content": row[1],
             "api303_has_nonzero_passing_time": row[2], "race_count": row[3],
             "candidate_horse_rows": row[4]}
            for row in candidate_content_time_counts
        ],
        "candidate_corner_content_without_3f_4f_time_by_distance": [
            {"race_distance_m": row[0], "race_count": row[1], "candidate_horse_rows": row[2]}
            for row in candidate_corner_without_time_by_distance
        ],
        "candidate_api303_time_without_corner_content": [
            {"race_date": row[0], "race_number": row[1], "candidate_horse_rows": row[2]}
            for row in candidate_time_without_corner
        ],
        "candidate_races_without_api303": [
            {"race_date": row[0], "race_number": row[1], "candidate_horse_rows": row[2]}
            for row in candidate_missing
        ],
        "candidate_races_with_all_finish_times_zero": {
            "race_count": candidate_all_zero_time[0],
            "candidate_horse_rows": candidate_all_zero_time[1],
        },
        "candidate_missing_api303_by_finish_time": [
            {"has_positive_finish_time": row[0], "race_count": row[1], "candidate_horse_rows": row[2]}
            for row in candidate_missing_timing
        ],
        "candidate_2026_07_07_horse_rows": july7,
        "candidate_2026_07_07_race_count": july7_races,
        "candidate_2026_09_17_to_19_horse_rows": sept[0] or 0,
        "candidate_2026_09_17_to_19_finish_time_positive_rows": sept[1] or 0,
        "candidate_api4_3_passing_order_fields": api4_field_stats,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Jeju core evidence SQLite database")
    parser.add_argument("--report", type=Path, default=REPO_ROOT / "jeju/research/20260929_api_detail_sources/api303_corner_rank_ingest_report.json")
    args = parser.parse_args()

    manifest, pages, archive_summary = inspect_archive()
    args.db = args.db.resolve()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        apply_migration(conn)
        conn.commit()
        already_loaded = validate_existing_import(conn, pages)
        if not already_loaded:
            conn.execute("BEGIN IMMEDIATE")
            try:
                insert_archive(conn, manifest, pages)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {integrity}")
        foreign_key_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_issues:
            raise RuntimeError(f"SQLite foreign_key_check found {len(foreign_key_issues)} issue(s)")
        imported_rows = conn.execute("SELECT count(*) FROM api303_corner_rank_rows").fetchone()[0]
        imported_artifacts = conn.execute(
            "SELECT count(*) FROM source_artifacts WHERE operation=? AND attempt_id=?",
            (OPERATION, ATTEMPT_ID),
        ).fetchone()[0]
        imported_api_records = conn.execute(
            "SELECT count(*) FROM api_records a JOIN source_artifacts s USING(source_artifact_id) "
            "WHERE s.operation=? AND s.attempt_id=? AND a.record_type='api303_corner_rank'",
            (OPERATION, ATTEMPT_ID),
        ).fetchone()[0]
        coverage_count = conn.execute(
            "SELECT count(*) FROM collection_coverage WHERE operation=? AND attempt_id=?",
            (OPERATION, ATTEMPT_ID),
        ).fetchone()[0]
        if (imported_rows, imported_artifacts, imported_api_records, coverage_count) != (EXPECTED_TOTAL, 25, EXPECTED_TOTAL, 25):
            raise RuntimeError(
                "Imported row/artifact/coverage counts differ from archive: "
                f"rows={imported_rows}, artifacts={imported_artifacts}, records={imported_api_records}, coverage={coverage_count}"
            )
        db_summary = database_summary(conn)
        report = {
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "database_path": safe_relative(args.db) if args.db.is_relative_to(REPO_ROOT) else str(args.db),
            "migration_path": safe_relative(MIGRATION),
            "load_was_noop_idempotent_rerun": already_loaded,
            "source_artifacts": {
                "attempt_id": ATTEMPT_ID,
                "page_artifact_count": imported_artifacts,
                "api_record_count": imported_api_records,
                "normalized_row_count": imported_rows,
                "coverage_partitions": coverage_count,
                "raw_pages_verified_by_sha256": len(pages),
                "integrity_check": integrity,
                "foreign_key_issues": len(foreign_key_issues),
            },
            "archive_audit": archive_summary,
            "database_crosswalk": db_summary,
            "interpretation_notes": [
                "API303 is one row per race and has no horse ID; it is joined only by date, requested meet code 2, and race number.",
                "API4_3 sj*Ord values are horse-level original values exposed from the exact race-result api_record_id.",
                "The API4_3 JSON type is included to distinguish a missing key from a source null; numeric zero remains zero and is not reclassified.",
                "API303 field-key signatures and per-year value shapes are reported without assuming that a particular corner_N column has a stable corner meaning across historical records.",
            ],
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(canonical_json(report) + "\n", encoding="utf-8")
        print(json.dumps({
            "report": str(args.report),
            "already_loaded": already_loaded,
            "archive_rows": archive_summary["row_count"],
            "unique_archive_keys": archive_summary["unique_race_key_count"],
            "imported_rows": imported_rows,
            "source_artifacts": imported_artifacts,
            "coverage_partitions": coverage_count,
            "api4_3_race_keys": db_summary["api4_3_race_key_count"],
            "api4_3_api303_intersection": db_summary["api4_3_api303_intersection_race_count"],
            "api4_3_missing_api303": db_summary["api4_3_without_api303_race_count"],
            "candidate_races": db_summary["candidate_race_count"],
            "candidate_rows": db_summary["candidate_horse_row_count"],
            "candidate_join_rows": db_summary["candidate_rows_after_join_count"],
            "candidate_missing_api303": len(db_summary["candidate_races_without_api303"]),
            "integrity_check": integrity,
            "foreign_key_issues": len(foreign_key_issues),
        }, ensure_ascii=False, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
