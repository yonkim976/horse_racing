"""Export a machine-readable catalog of the extended Jeju-native DB."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data/research/jeju_native_extended_db_20260915"
DB=OUT/"jeju_native_extended.sqlite3"


def digest(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()


def main()->None:
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
                indexes.append({**dict(idx),"columns":[dict(row) for row in conn.execute(f'PRAGMA index_info("{idx[1]}")')]})
        objects.append({"type":obj["type"],"name":name,"row_count":int(conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]),"columns":columns,"foreign_keys":foreign_keys,"indexes":indexes,"sql":obj["sql"]})
    status={
        "weight_link_status":[dict(row) for row in conn.execute("SELECT link_status,COUNT(*) row_count FROM measured_weight_record GROUP BY link_status ORDER BY link_status")],
        "duplicate_groups":[dict(row) for row in conn.execute("SELECT source_kind,COUNT(*) group_count,SUM(excess_occurrences) excess_rows FROM source_duplicate_group GROUP BY source_kind ORDER BY source_kind")],
        "text_documents":[dict(row) for row in conn.execute("SELECT text_type,row_parse_status,native_link_status,COUNT(*) file_count FROM text_document GROUP BY text_type,row_parse_status,native_link_status ORDER BY text_type")],
        "issues":[dict(row) for row in conn.execute("SELECT issue_code,COUNT(*) row_count FROM extended_issue GROUP BY issue_code ORDER BY issue_code")],
        "coverage_all":[dict(row) for row in conn.execute("SELECT * FROM extended_coverage WHERE dimension='all' ORDER BY source_kind")],
    }
    result={
        "catalog_version":"1","database_path":str(DB.relative_to(ROOT)),"database_bytes":DB.stat().st_size,
        "database_sha256":digest(DB),"base_database_path":"data/research/jeju_native_analysis_db_20260915/jeju_native_analysis.sqlite3",
        "objects":objects,"status":status,
        "scope_status":"Four confirmed-ID datasets are row-loaded; nine Text types are file-inventoried, while only dacom23 native trial rows were already loaded and dacom71 keys were partially checked.",
    }
    conn.close()
    path=OUT/"catalog.json"
    path.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"path":str(path.relative_to(ROOT)),"objects":len(objects),"database_sha256":result["database_sha256"]},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
