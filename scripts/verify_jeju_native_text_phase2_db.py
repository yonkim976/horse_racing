"""Read-only independent verification for the Jeju Text phase-2 database."""
from __future__ import annotations
import hashlib,json,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'data/research/jeju_native_text_phase2_db_20260915';DB=OUT/'jeju_native_text_phase2.sqlite3';BASE=ROOT/'data/research/jeju_native_extended_db_20260915/jeju_native_extended.sqlite3'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 m=json.loads((OUT/'manifest.json').read_text());c=sqlite3.connect(f'file:{DB}?mode=ro',uri=True);c.row_factory=sqlite3.Row;s=lambda q:int(c.execute(q).fetchone()[0])
 c.execute(f"ATTACH DATABASE 'file:{BASE}?mode=ro' AS base")
 base_counts={r['name']:(s(f"SELECT COUNT(*) FROM main.{r['name']}")==s(f"SELECT COUNT(*) FROM base.{r['name']}")) for r in c.execute("SELECT name FROM base.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
 bad_lines=[];checked=0
 bad_artifacts=[]
 for a in c.execute("SELECT path,sha256 FROM source_artifact"):
  p=ROOT/a['path']
  if not p.is_file() or sha(p)!=a['sha256']:bad_artifacts.append(a['path'])
 for d in c.execute("SELECT d.id,a.path FROM text_document d JOIN source_artifact a ON a.id=d.source_artifact_id ORDER BY d.id"):
  path=ROOT/d['path'];lines=path.read_bytes().decode('cp949',errors='replace').splitlines()
  for r in c.execute("SELECT line_number,source_line_sha256 FROM text_native_record WHERE document_id=? ORDER BY line_number",(d['id'],)):
   checked+=1;n=r['line_number'];actual=hashlib.sha256(lines[n-1].encode()).hexdigest() if 0<n<=len(lines) else None
   if actual!=r['source_line_sha256']:
    bad_lines.append([d['id'],n]);break
 checks={
  'database_sha256':sha(DB)==m['database_sha256'],'base_database_sha256':sha(BASE)==m['base_database_sha256'],'base_table_counts_preserved':all(v for k,v in base_counts.items() if k!='metadata'),
  'base_metadata_preserved':s("SELECT COUNT(*) FROM base.metadata b WHERE NOT EXISTS(SELECT 1 FROM main.metadata m WHERE m.key=b.key AND m.value_json=b.value_json)")==0,
  'integrity':c.execute('PRAGMA integrity_check').fetchone()[0]=='ok','foreign_keys':not c.execute('PRAGMA foreign_key_check').fetchall(),'all_documents_processed':s("SELECT COUNT(*) FROM text_parse_summary")==14131 and s("SELECT COUNT(*) FROM text_document WHERE row_parse_status!='phase2_v1_processed'")==0,
  'all_source_artifact_hashes':not bad_artifacts,
  'materialized_source_lines':not bad_lines and checked==s('SELECT COUNT(*) FROM text_native_record'),
  'official_entry_links':s("""SELECT COUNT(*) FROM text_native_record t WHERE t.link_status='official_entry_key_name_linked' AND NOT EXISTS(SELECT 1 FROM entry e JOIN event v ON v.id=e.event_id WHERE e.id=t.entry_id AND e.hr_no=t.hr_no AND e.horse_name=t.horse_name AND e.horse_number=t.horse_number AND v.event_date=t.event_date AND v.event_number=t.event_number)""")==0,
  'conflicts_not_given_ids':s("SELECT COUNT(*) FROM text_native_record WHERE link_status='entry_name_conflict' AND (hr_no IS NOT NULL OR entry_id IS NOT NULL)")==0,
  'daily_training_links':s("""SELECT COUNT(*) FROM text_native_record t WHERE t.record_type='daily_training' AND NOT EXISTS(SELECT 1 FROM daily_training_record d WHERE d.event_date=t.event_date AND d.horse_name=t.horse_name AND d.hr_no=t.hr_no AND d.training_duration_seconds=json_extract(t.parsed_json,'$.duration_seconds'))""")==0,
  'start_training_links':s("""SELECT COUNT(*) FROM text_native_record t WHERE t.record_type='start_training' AND NOT EXISTS(SELECT 1 FROM start_training_record d WHERE d.event_date=t.event_date AND d.horse_name=t.horse_name AND d.hr_no=t.hr_no AND d.part=json_extract(t.parsed_json,'$.part') AND d.part_no=json_extract(t.parsed_json,'$.part_no') AND d.exercise_person_name=json_extract(t.parsed_json,'$.exercise_person_name'))""")==0,
  'medical_links':s("""SELECT COUNT(*) FROM text_native_record t WHERE t.record_type='medical' AND NOT EXISTS(SELECT 1 FROM medical_record d WHERE d.event_date=t.event_date AND d.horse_name=t.horse_name AND d.hr_no=t.hr_no)""")==0,
  'start_inspection_explicit_only':s("SELECT COUNT(*) FROM text_native_record WHERE record_type='start_inspection' AND (json_extract(parsed_json,'$.origin')!='제주' OR hr_no IS NOT NULL OR link_status!='explicit_native_origin_unlinked_id')")==0,
  'track_native_days':s("SELECT COUNT(*) FROM text_native_record t WHERE record_type='track_snapshot' AND NOT EXISTS(SELECT 1 FROM event v WHERE v.event_type='race' AND v.event_date=t.event_date)")==0,
  'mixed_unresolved_content_not_copied':s("SELECT COUNT(*) FROM text_parse_issue WHERE details_json LIKE '%horse_name%' OR details_json LIKE '%diagnosis_raw%'")==0,
  'coverage_reconciles':s("""SELECT COUNT(*) FROM text_type_coverage x WHERE x.documents!=(SELECT COUNT(*) FROM text_document d WHERE d.text_type=x.text_type) OR x.native_records!=(SELECT COUNT(*) FROM text_native_record r JOIN text_document d ON d.id=r.document_id WHERE d.text_type=x.text_type) OR x.unresolved_rows!=(SELECT COALESCE(SUM(unresolved_rows),0) FROM text_parse_summary p JOIN text_document d ON d.id=p.document_id WHERE d.text_type=x.text_type)""")==0,
 }
 result={'passed':all(checks.values()),'database_sha256':sha(DB),'checks':checks,'base_table_count_checks':base_counts,'source_artifacts_checked':s('SELECT COUNT(*) FROM source_artifact'),'bad_source_artifact_paths':bad_artifacts,'materialized_text_records_checked':checked,'bad_source_line_keys':bad_lines,'counts':{'native_records':s('SELECT COUNT(*) FROM text_native_record'),'parse_issues':s('SELECT COUNT(*) FROM text_parse_issue'),'documents':s('SELECT COUNT(*) FROM text_parse_summary')}}
 c.close();(OUT/'independent_validation.json').write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
 if not result['passed']:raise SystemExit(1)
if __name__=='__main__':main()
