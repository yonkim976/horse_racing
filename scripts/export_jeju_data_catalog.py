"""Export a machine-readable catalog for the Jeju-native research artifacts."""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data/research/jeju_native_analysis_db_20260915"
DB=OUT/"jeju_native_analysis.sqlite3"


def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):h.update(block)
    return h.hexdigest()


def line_count(path:Path)->int:
    opener=gzip.open if path.suffix==".gz" else open
    with opener(path,"rt",encoding="utf-8") as f:return sum(1 for line in f if line.strip())


def main()->dict:
    conn=sqlite3.connect(f"file:{DB}?mode=ro",uri=True)
    conn.row_factory=sqlite3.Row
    objects=[]
    for obj in conn.execute("SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY type,name"):
        name=obj["name"]
        columns=[dict(row) for row in conn.execute(f'PRAGMA table_info("{name}")')]
        foreign_keys=[dict(row) for row in conn.execute(f'PRAGMA foreign_key_list("{name}")')]
        indexes=[]
        if obj["type"]=="table":
            for idx in conn.execute(f'PRAGMA index_list("{name}")'):
                indexes.append({**dict(idx),"columns":[dict(x) for x in conn.execute(f'PRAGMA index_info("{idx[1]}")')]})
        count=int(conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
        objects.append({"type":obj["type"],"name":name,"row_count":count,"columns":columns,"foreign_keys":foreign_keys,"indexes":indexes,"sql":obj["sql"]})
    statuses={
        "population_status":[dict(r) for r in conn.execute("SELECT population_status,COUNT(*) event_count FROM event GROUP BY population_status ORDER BY population_status")],
        "identity_status":[dict(r) for r in conn.execute("SELECT v.event_type,e.identity_status,COUNT(*) row_count FROM entry e JOIN event v ON v.id=e.event_id GROUP BY v.event_type,e.identity_status ORDER BY v.event_type,e.identity_status")],
        "record_status":[dict(r) for r in conn.execute("SELECT v.event_type,e.record_status,COUNT(*) row_count FROM entry e JOIN event v ON v.id=e.event_id GROUP BY v.event_type,e.record_status ORDER BY v.event_type,e.record_status")],
        "segment_quality":[dict(r) for r in conn.execute("SELECT v.event_type,e.segment_quality,COUNT(*) row_count FROM entry e JOIN event v ON v.id=e.event_id GROUP BY v.event_type,e.segment_quality ORDER BY v.event_type,e.segment_quality")],
        "issue_code":[dict(r) for r in conn.execute("SELECT issue_code,COUNT(*) row_count FROM resolution_issue GROUP BY issue_code ORDER BY issue_code")],
        "exclusions":[dict(r) for r in conn.execute("SELECT source_code,row_count,exclusion_status FROM exclusion_summary ORDER BY source_code")],
    }
    conn.close()
    training=[]
    for name in ("horse_training_confirmed_native","start_training_confirmed_native"):
        manifest=ROOT/f"data/raw/jeju_native_training/{name}.manifest.json"
        data=json.loads(manifest.read_text())
        training.append({"dataset":data["dataset"],"path":data["output"],"rows":data["native_rows"],"first_date":data["first_native_record_date"],"last_date":data["last_native_record_date"],"sha256":data["output_sha256"],"research_db_status":"not_loaded"})
    health=[]
    for kind in ("medical","weight"):
        manifests=sorted((ROOT/"data/raw/jeju_native_health_weight").glob(f"{kind}_*.manifest.json"))
        data=[json.loads(p.read_text()) for p in manifests]
        rows=sum(int(x.get("native_rows",0)) for x in data)
        health.append({"dataset":kind,"manifest_files":len(manifests),"rows":rows,"research_db_status":"not_loaded","first_date":min((x.get("first_native_date") or x.get("first_native_record_date") for x in data if x.get("first_native_date") or x.get("first_native_record_date")),default=None),"last_date":max((x.get("last_native_date") or x.get("last_native_record_date") for x in data if x.get("last_native_date") or x.get("last_native_record_date")),default=None)})
    other=json.loads((ROOT/"data/research/jeju_other_sources_verification_20260915/verification.json").read_text())
    text=[{"dataset":name,"files":value["final"],"first_file_date":value["first_file_date"],"last_file_date":value["last_file_date"],"research_db_status":"dacom23_trial_rows_partially_loaded" if name=="dacom23" else "files_verified_not_row_linked"} for name,value in sorted(other["text_archive"].items())]
    result={
        "catalog_version":"1",
        "database":{"path":str(DB.relative_to(ROOT)),"bytes":DB.stat().st_size,"sha256":sha(DB),"objects":objects,"statuses":statuses},
        "external_verified_native_sources":{"training":training,"health_weight":health,"text_archives":text},
        "scope_notes":[
            "The research SQLite currently materializes race results and running trials only.",
            "Training, start training, medical, measured weight, and most Text archives remain verified file artifacts and are not SQLite tables in this database.",
            "Current trainer/owner profiles are never backfilled into historical events.",
            "No model, operational dataset, registry, or operational database is modified.",
        ],
    }
    path=OUT/"catalog.json"
    path.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"path":str(path.relative_to(ROOT)),"database_objects":len(objects),"catalog_bytes":path.stat().st_size,"database_sha256":result["database"]["sha256"]},ensure_ascii=False,indent=2))
    return result


if __name__=="__main__":main()
