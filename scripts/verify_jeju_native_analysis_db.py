"""Independent read-only verification of the Jeju-native research database."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data/research/jeju_native_analysis_db_20260915"
DB=OUT/"jeju_native_analysis.sqlite3"


def digest(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()


def verify()->dict:
    manifest=json.loads((OUT/"manifest.json").read_text())
    conn=sqlite3.connect(f"file:{DB}?mode=ro",uri=True)
    conn.row_factory=sqlite3.Row
    scalar=lambda q:int(conn.execute(q).fetchone()[0])
    bad_hashes=[]
    for row in conn.execute("SELECT path,sha256 FROM source_artifact"):
        path=ROOT/row["path"]
        if not path.exists() or digest(path)!=row["sha256"]:bad_hashes.append(row["path"])
    priority={code:i for i,code in enumerate(("S1F","1C","2C","3C","G3F","4C","G1F","FIN"))}
    checkpoint_rows=conn.execute("""
      SELECT c.entry_id,c.section_code,c.elapsed_from_start_ms,c.distance_from_start_m,c.distance_is_approximate
      FROM section_checkpoint c JOIN entry e ON e.id=c.entry_id
      WHERE e.segment_quality='usable' ORDER BY c.entry_id,c.distance_from_start_m,c.section_code
    """).fetchall()
    by_entry={}
    for row in checkpoint_rows:by_entry.setdefault(row["entry_id"],[]).append(dict(row))
    segment_rows=conn.execute("SELECT * FROM derived_segment ORDER BY entry_id,segment_sequence").fetchall()
    segments_by_entry={}
    for row in segment_rows:segments_by_entry.setdefault(row["entry_id"],[]).append(dict(row))
    derivation_errors=[]
    for entry_id, rows in by_entry.items():
        grouped={}
        for row in rows:grouped.setdefault(row["distance_from_start_m"],[]).append(row)
        selected=[(0,[{"section_code":"START","elapsed_from_start_ms":0,"distance_is_approximate":0}],0)]
        for point, group in sorted(grouped.items()):
            pick=min(group,key=lambda x:priority[x["section_code"]])
            selected.append((point,group,pick["elapsed_from_start_ms"]))
        expected=[]
        for seq,(left,right) in enumerate(zip(selected,selected[1:]),1):
            start,lrows,ltime=left;end,rrows,rtime=right
            expected.append((seq,start,end,end-start,rtime-ltime,
                "/".join(x["section_code"] for x in sorted(lrows,key=lambda x:priority.get(x["section_code"],99))),
                "/".join(x["section_code"] for x in sorted(rrows,key=lambda x:priority.get(x["section_code"],99))),
                int(any(x["distance_is_approximate"] for x in lrows+rrows))))
        actual=[(r["segment_sequence"],r["start_distance_m"],r["end_distance_m"],r["distance_m"],r["elapsed_ms"],r["from_codes"],r["to_codes"],r["distance_is_approximate"]) for r in segments_by_entry.get(entry_id,[])]
        if actual!=expected:
            derivation_errors.append(entry_id)
            if len(derivation_errors)>=20:break
    checks={
        "database_sha256_matches_manifest":digest(DB)==manifest["database_sha256"],
        "integrity_check":conn.execute("PRAGMA integrity_check").fetchone()[0]=="ok",
        "foreign_key_check":not conn.execute("PRAGMA foreign_key_check").fetchall(),
        "source_artifact_hashes":not bad_hashes,
        "race_entries":scalar("SELECT COUNT(*) FROM entry e JOIN event v ON v.id=e.event_id WHERE v.event_type='race'")==92208,
        "race_usable":scalar("SELECT COUNT(*) FROM entry e JOIN event v ON v.id=e.event_id WHERE v.event_type='race' AND e.segment_quality='usable'")==90086,
        "race_unresolved":scalar("SELECT COUNT(*) FROM entry e JOIN event v ON v.id=e.event_id WHERE v.event_type='race' AND e.identity_status='official_race_id_unresolved'")==29,
        "trial_entries":scalar("SELECT COUNT(*) FROM entry e JOIN event v ON v.id=e.event_id WHERE v.event_type='trial'")==15688,
        "trial_usable":scalar("SELECT COUNT(*) FROM entry e JOIN event v ON v.id=e.event_id WHERE v.event_type='trial' AND e.segment_quality='usable'")==11671,
        "trial_unresolved":scalar("SELECT COUNT(*) FROM entry e JOIN event v ON v.id=e.event_id WHERE v.event_type='trial' AND e.identity_status='official_trial_identity_unresolved'")==55,
        "supplemented_trials":scalar("SELECT COUNT(DISTINCT entry_id) FROM section_checkpoint WHERE source_kind='trial_official_web_supplement'")==2981,
        "derived_segment_recalculation":not derivation_errors,
        "usable_entries_have_segments":scalar("SELECT COUNT(*) FROM entry e WHERE e.segment_quality='usable' AND NOT EXISTS(SELECT 1 FROM derived_segment s WHERE s.entry_id=e.id)")==0,
        "nonusable_entries_have_no_segments":scalar("SELECT COUNT(*) FROM entry e WHERE e.segment_quality!='usable' AND EXISTS(SELECT 1 FROM derived_segment s WHERE s.entry_id=e.id)")==0,
        "official_id_storage_is_text":scalar("SELECT COUNT(*) FROM entry WHERE (hr_no IS NOT NULL AND (typeof(hr_no)!='text' OR length(hr_no)!=7 OR hr_no GLOB '*[^0-9]*')) OR (tr_no IS NOT NULL AND (typeof(tr_no)!='text' OR length(tr_no)!=6 OR tr_no GLOB '*[^0-9]*')) OR (ow_no IS NOT NULL AND (typeof(ow_no)!='text' OR length(ow_no)!=6 OR ow_no GLOB '*[^0-9]*'))")==0,
        "confirmed_non_native_rows_absent":scalar("SELECT COUNT(*) FROM entry WHERE breed_status='confirmed_non_native'")==0,
        "race_analysis_view_entries":scalar("SELECT COUNT(DISTINCT event_date||':'||event_number||':'||horse_number) FROM analysis_race_segments")==90082,
        "trial_analysis_view_entries":scalar("SELECT COUNT(DISTINCT event_date||':'||event_number||':'||horse_number) FROM analysis_trial_segments")==11671,
    }
    result={"passed":all(checks.values()),"checks":checks,"source_artifacts_checked":scalar("SELECT COUNT(*) FROM source_artifact"),"usable_entries_recalculated":len(by_entry),"derived_segments_checked":len(segment_rows),"bad_source_hash_paths":bad_hashes,"derivation_error_entry_ids":derivation_errors,"database_sha256":digest(DB)}
    conn.close()
    (OUT/"independent_validation.json").write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["passed"]:raise SystemExit(1)
    return result


if __name__=="__main__":verify()
