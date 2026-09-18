"""Independently and read-only verify the extended Jeju-native research DB."""

from __future__ import annotations

import collections
import gzip
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Iterator

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data/research/jeju_native_extended_db_20260915"
DB=OUT/"jeju_native_extended.sqlite3"
BASE=ROOT/"data/research/jeju_native_analysis_db_20260915/jeju_native_analysis.sqlite3"


def digest(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()


def compact(value:object)->str:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))


def input_rows(path:Path)->Iterator[tuple[int,dict]]:
    opener=gzip.open if path.suffix==".gz" else open
    with opener(path,"rt",encoding="utf-8") as f:
        for n,line in enumerate(f,1):
            if line.strip():yield n,json.loads(line)


def source_rows_match(conn:sqlite3.Connection,path:Path)->tuple[bool,int]:
    relative=path.relative_to(ROOT).as_posix()
    artifact=conn.execute("SELECT id FROM source_artifact WHERE path=?",(relative,)).fetchone()
    if artifact is None:return False,0
    cursor=iter(conn.execute("SELECT line_number,row_sha256,normalized_json FROM source_row WHERE source_artifact_id=? ORDER BY line_number",(artifact[0],)))
    count=0
    for line_number,row in input_rows(path):
        actual=next(cursor,None)
        normalized=compact(row)
        expected_hash=hashlib.sha256(normalized.encode()).hexdigest()
        if actual is None or (actual[0],actual[1],actual[2])!=(line_number,expected_hash,normalized):
            return False,count
        count+=1
    return next(cursor,None) is None,count


def compare_base_tables(conn:sqlite3.Connection)->dict[str,bool]:
    result={}
    for table in ("event","entry","section_checkpoint","derived_segment","resolution_issue","exclusion_summary","coverage","source_request","source_artifact","source_row"):
        columns=[row[1] for row in conn.execute(f"PRAGMA base.table_info('{table}')")]
        select=",".join(f'"{c}"' for c in columns)
        if "id" in columns:
            max_id=int(conn.execute(f"SELECT COALESCE(MAX(id),0) FROM base.{table}").fetchone()[0])
            main_select=f"SELECT {select} FROM main.{table} WHERE id<={max_id}"
        else:
            main_select=f"SELECT {select} FROM main.{table}"
        base_select=f"SELECT {select} FROM base.{table}"
        left=int(conn.execute(f"SELECT COUNT(*) FROM ({main_select} EXCEPT {base_select})").fetchone()[0])
        right=int(conn.execute(f"SELECT COUNT(*) FROM ({base_select} EXCEPT {main_select})").fetchone()[0])
        result[table]=left==right==0
    return result


def duplicate_summary(paths:list[Path])->tuple[int,int,dict[str,int]]:
    counts:collections.Counter[str]=collections.Counter()
    for path in paths:
        for _,row in input_rows(path):
            counts[hashlib.sha256(compact(row).encode()).hexdigest()]+=1
    duplicates={key:value for key,value in counts.items() if value>1}
    return len(duplicates),sum(value-1 for value in duplicates.values()),duplicates


def main()->None:
    manifest=json.loads((OUT/"manifest.json").read_text())
    conn=sqlite3.connect(f"file:{DB}?mode=ro",uri=True)
    conn.row_factory=sqlite3.Row
    conn.execute(f"ATTACH DATABASE 'file:{BASE}?mode=ro' AS base")
    scalar=lambda sql:int(conn.execute(sql).fetchone()[0])
    base_tables=compare_base_tables(conn)
    bad_artifacts=[]
    for row in conn.execute("SELECT path,sha256 FROM source_artifact"):
        path=ROOT/row["path"]
        if not path.is_file() or digest(path)!=row["sha256"]:bad_artifacts.append(row["path"])
    row_sources=[
        ROOT/"data/raw/jeju_native_training/horse_training_confirmed_native.jsonl.gz",
        ROOT/"data/raw/jeju_native_training/start_training_confirmed_native.jsonl.gz",
        *sorted((ROOT/"data/raw/jeju_native_health_weight").glob("medical_*.jsonl")),
        *sorted((ROOT/"data/raw/jeju_native_health_weight").glob("weight_*.jsonl")),
        ROOT/"data/research/jeju_other_sources_verification_20260915/issues.jsonl",
    ]
    bad_row_sources=[];source_rows_checked=0
    for path in row_sources:
        matched,count=source_rows_match(conn,path)
        source_rows_checked+=count
        if not matched:bad_row_sources.append(path.relative_to(ROOT).as_posix())
    start_groups,start_excess,start_payloads=duplicate_summary([row_sources[1]])
    medical_paths=sorted((ROOT/"data/raw/jeju_native_health_weight").glob("medical_*.jsonl"))
    medical_groups,medical_excess,medical_payloads=duplicate_summary(medical_paths)
    stored_duplicates={}
    for kind in ("start_training","medical"):
        stored_duplicates[kind]={row["payload_sha256"]:row["occurrences"] for row in conn.execute("SELECT payload_sha256,occurrences FROM source_duplicate_group WHERE source_kind=?",(kind,))}
    checks={
        "database_sha256_matches_manifest":digest(DB)==manifest["database_sha256"],
        "base_database_sha256_matches_manifest":digest(BASE)==manifest["base_database_sha256"],
        "base_tables_preserved":all(base_tables.values()),
        "integrity_check":conn.execute("PRAGMA integrity_check").fetchone()[0]=="ok",
        "foreign_key_check":not conn.execute("PRAGMA foreign_key_check").fetchall(),
        "all_source_artifact_hashes":not bad_artifacts,
        "line_level_source_rows":not bad_row_sources and source_rows_checked==1172036,
        "daily_training_rows":scalar("SELECT COUNT(*) FROM daily_training_record")==884383,
        "daily_training_positive":scalar("SELECT COUNT(*) FROM daily_training_record WHERE training_duration_seconds>0")==866457,
        "start_training_rows":scalar("SELECT COUNT(*) FROM start_training_record")==184351,
        "start_duplicates":(start_groups,start_excess)==(3153,3153) and stored_duplicates["start_training"]==start_payloads,
        "medical_rows":scalar("SELECT COUNT(*) FROM medical_record")==11653,
        "medical_diagnosed":scalar("SELECT COUNT(*) FROM medical_record WHERE has_diagnosis=1")==10001,
        "medical_duplicates":(medical_groups,medical_excess)==(19,21) and stored_duplicates["medical"]==medical_payloads,
        "weight_rows":scalar("SELECT COUNT(*) FROM measured_weight_record")==90713,
        "weight_entry_links":scalar("""SELECT COUNT(*) FROM measured_weight_record w JOIN entry e ON e.id=w.entry_id JOIN event v ON v.id=e.event_id WHERE w.race_date=v.event_date AND w.race_number=v.event_number AND w.hr_no=e.hr_no AND w.horse_number=e.horse_number""")==90713,
        "strict_weight_view":scalar("SELECT COUNT(*) FROM analysis_measured_weight")==90262,
        "distinct_start_view":scalar("SELECT COUNT(*) FROM analysis_start_training_distinct")==181198,
        "distinct_medical_view":scalar("SELECT COUNT(*) FROM analysis_medical_distinct")==11632,
        "text_document_inventory":scalar("SELECT COUNT(*) FROM text_document")==14131,
        "text_unparsed_not_mislabeled":scalar("SELECT COUNT(*) FROM text_document WHERE text_type NOT IN ('dacom23','dacom71') AND row_parse_status!='document_hash_verified_unparsed'")==0,
        "official_ids_are_text":scalar("SELECT COUNT(*) FROM (SELECT hr_no FROM daily_training_record UNION ALL SELECT hr_no FROM start_training_record UNION ALL SELECT hr_no FROM medical_record UNION ALL SELECT hr_no FROM measured_weight_record) WHERE typeof(hr_no)!='text' OR length(hr_no)!=7 OR hr_no GLOB '*[^0-9]*'")==0,
        "request_secrets_absent":scalar("SELECT COUNT(*) FROM collection_request WHERE lower(COALESCE(request_json,'')) LIKE '%servicekey%' OR lower(COALESCE(request_json,'')) LIKE '%apikey%'")==0,
    }
    result={
        "passed":all(checks.values()),"checks":checks,"base_table_checks":base_tables,
        "database_sha256":digest(DB),"source_artifacts_checked":scalar("SELECT COUNT(*) FROM source_artifact"),
        "bad_source_artifact_paths":bad_artifacts,"line_level_source_rows_checked":source_rows_checked,
        "bad_line_level_sources":bad_row_sources,"start_duplicate_groups":start_groups,
        "start_duplicate_excess":start_excess,"medical_duplicate_groups":medical_groups,
        "medical_duplicate_excess":medical_excess,
    }
    conn.close()
    output=OUT/"independent_validation.json"
    output.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["passed"]:raise SystemExit(1)


if __name__=="__main__":main()
