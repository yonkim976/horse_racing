"""Create exact occurrence fingerprints, a comparison-only ledger, and manifests."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq


REPO = Path(__file__).resolve().parents[4]
OUT = REPO / "thoroughbred/research/20261002_medical_v1/source"
SCOPE_START = "2010-01-01"
SCOPE_END = "2026-09-29"
MEETS = {1: "서울", 3: "영남 (부산경남/영천 혼합)"}
SOURCES = {
    "current_annual": OUT / "api16_current_annual_observations.parquet",
    "archived_daily_snapshot": OUT / "api16_archived_daily_observations.parquet",
    "rpt": OUT / "dacom72_observations.parquet",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_json(path: Path, value: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def sql_quote(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def parquet_rows(path: Path) -> int:
    return pq.ParquetFile(path).metadata.num_rows


def pipeline_script_inventory() -> list[dict[str, Any]]:
    names = (
        "source_common.py", "collect_api16_annual.py",
        "normalize_local_sources.py", "derive_comparison.py",
    )
    return [
        {
            "path": (OUT / name).relative_to(REPO).as_posix(),
            "sha256": file_sha256(OUT / name),
            "bytes": (OUT / name).stat().st_size,
        }
        for name in names
    ]


def main() -> None:
    for path in SOURCES.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    current_coverage_path = OUT / "api16_year_meet_coverage.parquet"
    archive_coverage_path = OUT / "archived_daily_coverage.parquet"
    rpt_coverage_path = OUT / "dacom72_year_meet_coverage.parquet"
    for path in (current_coverage_path, archive_coverage_path, rpt_coverage_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    conn = duckdb.connect(":memory:")
    conn.execute("SET preserve_insertion_order=false")
    source_glob = "[" + ",".join(sql_quote(path) for path in SOURCES.values()) + "]"
    conn.execute(f"CREATE TEMP VIEW obs AS SELECT * FROM read_parquet({source_glob})")

    fingerprint_path = OUT / "medical_fingerprint_candidates.parquet"
    conn.execute(f"""
        COPY (
            SELECT source_kind, source_cohort, event_date, meet_code, meet_raw,
                   horse_name_raw, hr_no_raw, stable_no_raw, part_raw,
                   hospital_name_raw, ill_name1_raw, ill_name2_raw, diagnosis_rpt_raw,
                   count(*)::UBIGINT AS occurrence_count,
                   to_json(list(source_row_hash ORDER BY source_row_hash)) AS provenance_row_hashes_json,
                   to_json(list(DISTINCT source_path ORDER BY source_path)) AS source_paths_json,
                   to_json(list(DISTINCT source_sha256 ORDER BY source_sha256)) AS source_sha256s_json,
                   to_json(list(DISTINCT coalesce(raw_payload_json, raw_line) ORDER BY coalesce(raw_payload_json, raw_line))) AS raw_source_variants_json
              FROM obs
             GROUP BY ALL
             ORDER BY source_kind, source_cohort, event_date, meet_code, horse_name_raw,
                      stable_no_raw, hospital_name_raw, ill_name1_raw, ill_name2_raw, diagnosis_rpt_raw
        ) TO {sql_quote(fingerprint_path)} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    compare_path = OUT / "medical_api_comparison_ledger.parquet"
    conn.execute(f"""
        COPY (
            WITH api AS (
                SELECT source_kind, source_cohort, event_date, meet_code, meet_raw,
                       horse_name_raw, hospital_name_raw, hr_no_raw,
                       ill_name1_raw, ill_name2_raw,
                       count(*)::UBIGINT AS api_occurrence_count,
                       to_json(list(source_row_hash ORDER BY source_row_hash)) AS api_provenance_row_hashes_json,
                       to_json(list(DISTINCT source_path ORDER BY source_path)) AS api_source_paths_json,
                       to_json(list(DISTINCT source_sha256 ORDER BY source_sha256)) AS api_source_sha256s_json
                  FROM obs
                 WHERE source_kind IN ('api16','api16_archived')
                 GROUP BY ALL
            ), rpt AS (
                SELECT source_kind, source_cohort, event_date, meet_code, meet_raw,
                       horse_name_raw, stable_no_raw, hospital_name_raw, diagnosis_rpt_raw,
                       count(*)::UBIGINT AS rpt_occurrence_count,
                       to_json(list(source_row_hash ORDER BY source_row_hash)) AS rpt_provenance_row_hashes_json,
                       to_json(list(DISTINCT source_path ORDER BY source_path)) AS rpt_source_paths_json,
                       to_json(list(DISTINCT source_sha256 ORDER BY source_sha256)) AS rpt_source_sha256s_json
                  FROM obs
                 WHERE source_kind='dacom72' AND horse_name_raw IS NOT NULL
                 GROUP BY ALL
            ), paired AS (
                SELECT
                    coalesce(r.event_date,a.event_date) AS event_date,
                    coalesce(r.meet_code,a.meet_code) AS meet_code,
                    coalesce(r.horse_name_raw,a.horse_name_raw) AS horse_name_raw,
                    coalesce(r.hospital_name_raw,a.hospital_name_raw) AS hospital_name_raw,
                    r.stable_no_raw, r.diagnosis_rpt_raw,
                    a.source_kind AS api_source_kind, a.source_cohort AS api_source_cohort,
                    a.meet_raw AS api_meet_raw, r.meet_raw AS rpt_meet_raw,
                    a.hr_no_raw AS api_hr_no_raw,
                    a.ill_name1_raw AS api_ill_name1_raw,
                    a.ill_name2_raw AS api_ill_name2_raw,
                    coalesce(a.api_occurrence_count,0)::UBIGINT AS api_occurrence_count,
                    coalesce(r.rpt_occurrence_count,0)::UBIGINT AS rpt_occurrence_count,
                    a.api_provenance_row_hashes_json, a.api_source_paths_json, a.api_source_sha256s_json,
                    r.rpt_provenance_row_hashes_json, r.rpt_source_paths_json, r.rpt_source_sha256s_json,
                    (r.diagnosis_rpt_raw IS NOT NULL AND r.diagnosis_rpt_raw IN (a.ill_name1_raw,a.ill_name2_raw)) AS exact_slot_match,
                    (r.diagnosis_rpt_raw IS NOT NULL AND regexp_replace(r.diagnosis_rpt_raw,'[[:space:]]+','','g') IN
                        (regexp_replace(coalesce(a.ill_name1_raw,''),'[[:space:]]+','','g'),
                         regexp_replace(coalesce(a.ill_name2_raw,''),'[[:space:]]+','','g'))) AS whitespace_normalized_slot_match
                  FROM rpt r
                  FULL OUTER JOIN api a
                    ON r.event_date=a.event_date AND r.meet_code=a.meet_code
                   AND r.horse_name_raw=a.horse_name_raw AND r.hospital_name_raw=a.hospital_name_raw
            ), scored AS (
                SELECT *,
                    count(DISTINCT CASE WHEN exact_slot_match THEN api_hr_no_raw END)
                      OVER (PARTITION BY event_date, meet_code, horse_name_raw, stable_no_raw,
                                         hospital_name_raw, diagnosis_rpt_raw) AS exact_official_id_count,
                    min(CASE WHEN exact_slot_match THEN api_hr_no_raw END)
                      OVER (PARTITION BY event_date, meet_code, horse_name_raw, stable_no_raw,
                                         hospital_name_raw, diagnosis_rpt_raw) AS only_exact_official_id
                FROM paired
            )
            SELECT event_date, meet_code,
                   CASE meet_code WHEN 1 THEN '서울' WHEN 3 THEN '영남 (부산경남/영천 혼합)' ELSE NULL END AS meet_scope_name,
                   horse_name_raw, stable_no_raw, hospital_name_raw, diagnosis_rpt_raw,
                   api_source_kind, api_source_cohort, api_hr_no_raw,
                   api_ill_name1_raw, api_ill_name2_raw,
                   api_occurrence_count, rpt_occurrence_count,
                   exact_slot_match AS exact_raw_ill_field_match,
                   whitespace_normalized_slot_match,
                   exact_official_id_count,
                   CASE WHEN exact_slot_match AND exact_official_id_count=1 THEN only_exact_official_id ELSE NULL END AS official_id_candidate,
                   CASE WHEN exact_slot_match AND exact_official_id_count=1
                        THEN 'unique exact date/meet/name/hospital/diagnosis API slot evidence'
                        ELSE NULL END AS official_id_candidate_basis,
                   CASE WHEN api_source_kind IS NULL THEN 'rpt_only_no_same_name_date_hospital_api_observation'
                        WHEN rpt_occurrence_count=0 THEN 'api_only_no_same_name_date_hospital_rpt_observation'
                        WHEN exact_slot_match THEN 'exact_raw_diagnosis_slot_match_comparison_only'
                        WHEN whitespace_normalized_slot_match THEN 'whitespace_normalized_slot_match_comparison_only'
                        ELSE 'same_name_date_hospital_diagnosis_variant_comparison_only' END AS comparison_status,
                   false AS automatically_linked,
                   api_provenance_row_hashes_json, api_source_paths_json, api_source_sha256s_json,
                   rpt_provenance_row_hashes_json, rpt_source_paths_json, rpt_source_sha256s_json
              FROM scored
             ORDER BY event_date, meet_code, horse_name_raw, stable_no_raw, hospital_name_raw,
                      api_source_cohort, diagnosis_rpt_raw
        ) TO {sql_quote(compare_path)} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    combined_coverage_path = OUT / "source_year_meet_coverage.parquet"
    conn.execute(f"""
        COPY (
            WITH base AS (
                SELECT y.event_year, m.meet_code, m.meet_name
                  FROM (SELECT range::INTEGER AS event_year FROM range(2010,2027)) y
                  CROSS JOIN (VALUES (1,'서울'),(3,'영남')) m(meet_code,meet_name)
            ), source_pairs AS (
                SELECT 'api16' AS source_kind,'current_annual' AS source_cohort,request_year::INTEGER AS event_year,
                       request_meet::INTEGER AS meet_code,reported_total_count::UBIGINT AS provider_total_count,
                       page_count::INTEGER AS page_count,successful_empty_response::BOOLEAN AS successful_empty_response
                  FROM read_parquet({sql_quote(current_coverage_path)})
                UNION ALL
                SELECT 'api16_archived','archived_daily_snapshot',event_year::INTEGER,meet_code::INTEGER,
                       NULL::UBIGINT,NULL::INTEGER,NULL::BOOLEAN
                  FROM read_parquet({sql_quote(archive_coverage_path)})
                UNION ALL
                SELECT 'dacom72','rpt',event_year::INTEGER,meet_code::INTEGER,
                       NULL::UBIGINT,NULL::INTEGER,NULL::BOOLEAN
                  FROM read_parquet({sql_quote(rpt_coverage_path)})
            ), sources AS (
                SELECT DISTINCT source_kind,source_cohort FROM source_pairs
            ), obs_counts AS (
                SELECT source_kind,source_cohort,year(try_cast(event_date AS DATE))::INTEGER AS event_year,
                       meet_code,count(*)::UBIGINT AS observation_occurrence_count,
                       count(DISTINCT event_date)::INTEGER AS distinct_event_date_count,
                       count(DISTINCT horse_name_raw)::INTEGER AS distinct_horse_name_count,
                       count(DISTINCT source_path)::INTEGER AS source_file_count
                  FROM obs GROUP BY ALL
            )
            SELECT s.source_kind,s.source_cohort,b.event_year,b.meet_code,b.meet_name,
                   coalesce(o.observation_occurrence_count,0)::UBIGINT AS observation_occurrence_count,
                   coalesce(o.distinct_event_date_count,0)::INTEGER AS distinct_event_date_count,
                   coalesce(o.distinct_horse_name_count,0)::INTEGER AS distinct_horse_name_count,
                   coalesce(o.source_file_count,0)::INTEGER AS source_file_count,
                   p.provider_total_count,p.page_count,p.successful_empty_response,
                   '{SCOPE_START}' AS scope_start_date,'{SCOPE_END}' AS scope_end_date,
                   CASE WHEN s.source_cohort='current_annual'
                        THEN 'annual API responses paginated completely; provider history completeness unverified'
                        WHEN s.source_cohort='archived_daily_snapshot'
                        THEN 'archived daily API snapshots; historical completeness unknown'
                        ELSE 'local weekly/monthly text files; historical completeness unknown' END AS coverage_interpretation
              FROM sources s CROSS JOIN base b
              LEFT JOIN obs_counts o USING(source_kind,source_cohort,event_year,meet_code)
              LEFT JOIN source_pairs p USING(source_kind,source_cohort,event_year,meet_code)
             ORDER BY s.source_kind,event_year,meet_code
        ) TO {sql_quote(combined_coverage_path)} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    exclusion_path = OUT / "source_exclusions.parquet"
    current_exclusions_path = OUT / "api16_current_annual_exclusions.parquet"
    archive_exclusions_path = OUT / "api16_archived_exclusions.parquet"
    rpt_exclusions_path = OUT / "dacom72_exclusions.parquet"
    conn.execute(f"""
        COPY (
            SELECT source_kind,source_cohort,reason,event_date,NULL::VARCHAR AS request_date,
                   request_year,request_meet,NULL::SMALLINT AS meet_code,NULL::VARCHAR AS source_file_date,
                   source_path,source_sha256,capture_id,page_no,row_no,NULL::INTEGER AS line_no,
                   NULL::VARCHAR AS source_row_hash,raw_payload_json,NULL::VARCHAR AS raw_line
              FROM read_parquet({sql_quote(current_exclusions_path)})
            UNION ALL
            SELECT source_kind,source_cohort,reason,event_date,request_date,
                   NULL::SMALLINT,NULL::SMALLINT,request_meet::SMALLINT,NULL::VARCHAR,
                   source_path,source_sha256,capture_id,page_no,row_no,NULL::INTEGER,
                   source_row_hash,raw_payload_json,NULL::VARCHAR
              FROM read_parquet({sql_quote(archive_exclusions_path)})
            UNION ALL
            SELECT source_kind,source_cohort,reason,event_date,NULL::VARCHAR,
                   NULL::SMALLINT,NULL::SMALLINT,meet_code::SMALLINT,source_file_date,
                   source_path,source_sha256,NULL::VARCHAR,NULL::INTEGER,NULL::INTEGER,line_no,
                   source_row_hash,NULL::VARCHAR,raw_line
              FROM read_parquet({sql_quote(rpt_exclusions_path)})
        ) TO {sql_quote(exclusion_path)} (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    counts = conn.execute("SELECT source_kind, source_cohort, count(*) FROM obs GROUP BY ALL ORDER BY ALL").fetchall()
    source_totals = [
        {"source_kind": row[0], "source_cohort": row[1], "observation_occurrences": int(row[2])}
        for row in counts
    ]
    total_observations = sum(r["observation_occurrences"] for r in source_totals)
    artifacts = [
        "api16_current_annual_observations.parquet", "api16_archived_daily_observations.parquet",
        "dacom72_observations.parquet", "medical_fingerprint_candidates.parquet",
        "medical_api_comparison_ledger.parquet", "api16_page_ledger.parquet",
        "api16_year_meet_coverage.parquet", "api16_archived_page_ledger.parquet",
        "archived_daily_coverage.parquet", "existing_raw_inventory.parquet",
        "api16_archived_exclusions.parquet", "dacom72_file_ledger.parquet",
        "api16_current_annual_exclusions.parquet", "source_exclusions.parquet",
        "dacom72_year_meet_coverage.parquet", "dacom72_exclusions.parquet",
        "dacom72_layout_reconciliation.parquet", "source_year_meet_coverage.parquet",
        "api16_current_annual_capture_manifest.json", "api16_archived_capture_manifest.json",
        "dacom72_capture_manifest.json",
    ]
    file_inventory = []
    for name in artifacts:
        path = OUT / name
        if not path.is_file():
            continue
        entry = {"path": path.relative_to(REPO).as_posix(), "sha256": file_sha256(path), "bytes": path.stat().st_size}
        if path.suffix == ".parquet":
            entry["row_count"] = parquet_rows(path)
        file_inventory.append(entry)
    with (OUT / "source_output_hashes.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("path", "sha256", "bytes", "row_count"))
        writer.writeheader()
        writer.writerows(file_inventory)

    scripts_inventory = pipeline_script_inventory()
    source_capture = {
        "package": "thoroughbred/research/20261002_medical_v1/source",
        "scope": {"start_date": SCOPE_START, "end_date": SCOPE_END, "meets": MEETS},
        "cohorts": {
            "current_annual": {"kind": "api16", "manifest": "api16_current_annual_capture_manifest.json",
                               "page_ledger": "api16_page_ledger.parquet", "coverage": "api16_year_meet_coverage.parquet"},
            "archived_daily_snapshot": {"kind": "api16_archived", "manifest": "api16_archived_capture_manifest.json",
                                         "page_ledger": "api16_archived_page_ledger.parquet",
                                         "inventory": "existing_raw_inventory.parquet", "coverage": "archived_daily_coverage.parquet"},
            "rpt": {"kind": "dacom72", "manifest": "dacom72_capture_manifest.json",
                    "file_ledger": "dacom72_file_ledger.parquet", "coverage": "dacom72_year_meet_coverage.parquet"},
        },
        "observation_schema": "source_common.OBSERVATION_SCHEMA (30 columns; fixed Arrow types)",
        "occurrence_provenance": {
            "API": "source_path+source_sha256+capture_id+page_no+row_no+raw_payload_json",
            "RPT": "source_path+source_sha256+line_no+raw_line",
            "source_row_hash": "SHA256(source_kind + NUL + source_path + NUL + page_no + NUL + row_no + NUL + line_no)",
        },
        "pipeline_scripts": scripts_inventory,
        "output_artifacts": file_inventory,
    }
    safe_json(OUT / "source_capture_manifest.json", source_capture)

    coverage_manifest = {
        "package": "horse_racing_medical_research_v1",
        "scope": {"start_date": SCOPE_START, "end_date": SCOPE_END, "meets": MEETS},
        "operational_database_accessed": False,
        "operational_database_modified": False,
        "source_observation_occurrences": source_totals,
        "total_source_observation_occurrences": total_observations,
        "api_current_annual": {
            "year_meet_request_count": 34,
            "successful_empty_responses": conn.execute(
                f"SELECT count(*) FROM read_parquet({sql_quote(current_coverage_path)}) WHERE successful_empty_response"
            ).fetchone()[0],
            "response_pages": parquet_rows(OUT / "api16_page_ledger.parquet"),
            "complete_pages": True,
            "provider_historical_completeness": "not asserted; successful empty responses are retained as evidence",
        },
        "archived_daily_api": json.loads((OUT / "api16_archived_capture_manifest.json").read_text(encoding="utf-8")),
        "dacom72": json.loads((OUT / "dacom72_capture_manifest.json").read_text(encoding="utf-8")),
        "rpt_diagnoses": "one combined source field per row; no comma-based split",
        "deduplication": "raw observations retain every occurrence; fingerprints are separate exact aggregates, never visit counts",
        "cross_source_identity": "comparison-only; no automatic linking and no name-only official-ID inference",
        "coverage_table": "source_year_meet_coverage.parquet",
        "source_capture_manifest": "source_capture_manifest.json",
        "output_hash_inventory": "source_output_hashes.csv",
        "pipeline_scripts": scripts_inventory,
        "outputs": file_inventory,
    }
    safe_json(OUT / "coverage_manifest.json", coverage_manifest)
    print(json.dumps({
        "source_observation_occurrences": source_totals,
        "total_source_observation_occurrences": total_observations,
        "fingerprint_rows": parquet_rows(fingerprint_path),
        "comparison_rows": parquet_rows(compare_path),
        "source_year_meet_coverage_rows": parquet_rows(combined_coverage_path),
    }, ensure_ascii=False))
    conn.close()


if __name__ == "__main__":
    main()
