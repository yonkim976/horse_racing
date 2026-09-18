"""Parse and safely link Jeju Text archives into a new immutable research DB.

Mixed-breed Text content is not copied wholesale. Only records tied to an
already-confirmed native race/horse event, or explicitly marked 제주 in the
starting-inspection source, are materialized. Other candidate lines retain only
their source document, line number and reason in the parse ledger.
"""

from __future__ import annotations

import argparse,collections,hashlib,json,re,shutil,sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"data/research/jeju_native_extended_db_20260915/jeju_native_extended.sqlite3"
OUT=ROOT/"data/research/jeju_native_text_phase2_db_20260915"
DB=OUT/"jeju_native_text_phase2.sqlite3"
TMP=OUT/"jeju_native_text_phase2.sqlite3.tmp"
RACE_HEADING=re.compile(r"(?:경주일\s*:\s*|제목\s*:\s*|;TI\s*).*?(20\d\d|\d\d)[.년\s]+(\d{1,2})[.월\s]+(\d{1,2}).*?(?:제\s*0*(\d+)\s*경주|(\d+)\s*경주)")
WEIGHT_LINE=re.compile(r"^\s*(\d{1,2})\s+(\S+)\s+(\d{3})\s+([+-]\d+|0)\b")
ENTRY_LINE=re.compile(r"^\s*(\d{1,2})\s+(\S+)\s+(.+?)\s*$")
MEDICAL_LINE=re.compile(r"^\s*(20\d\d)[./-](\d\d)[./-](\d\d)\s+(\S+)\s+(\d{1,2})\s+(\S+)\s+(.+?)\s*$")
TRAINING_LINE=re.compile(r"^\s*\d+\s+(\d+)조\(([^)]+)\)\s*(\d+)\s+(\S+)\s+(\S+)\s+(\d\d:\d\d)\s+(\d\d:\d\d)\s+(\d+):(\d\d)\s*(\S*)")
START_TRAIN_LINE=re.compile(r"^\s*(\d+)조\s+(\d+)\s+(\S+)\s+(\S+)(?:\s+(.*?))?\s*$")
TRACK_LINE=re.compile(r"주로상태\s*:\s*(\S+).*?\(\s*([\d.]+)%\s*\)")
D13_ROW=re.compile(r"^\s*(20\d\d)/(\d\d)/(\d\d)\s+(\d+)R\s+(\d+)\s+(\S+)\s+(.+?)\s*$")
DATE_TITLE=re.compile(r"(20\d\d)[.년\s]+(\d{1,2})[.월\s]+(\d{1,2})")
START_CHECK_TITLE=re.compile(r"(20\d\d)[.년\s]+(\d{1,2})[.월\s]+(\d{1,2}).*?제(\d+)차\s+출발심사결과\s+(\d+)경주")
START_CHECK_ROW=re.compile(r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+(제주|한라(?:\(래\))?|한라마|내륙|외산)\s+([수암거])\s+(\d+)\s+(.+?)\s*$")
ENTRY_CARD_ROW=re.compile(r"^\s*(\d{1,2})\s+(\S+)\s+([제한래산검])\s+([수암거])\s+(\d+)\s+(\d+(?:\.\d+)?)\s+(\S+)\s+(\S+)\s+(\S+)\s*$")

SCHEMA="""
CREATE TABLE text_parse_summary(
 document_id INTEGER PRIMARY KEY REFERENCES text_document(id), parser_version TEXT NOT NULL,
 total_lines INTEGER NOT NULL, nonempty_lines INTEGER NOT NULL, candidate_rows INTEGER NOT NULL,
 native_records INTEGER NOT NULL, excluded_non_native_rows INTEGER NOT NULL,
 unresolved_rows INTEGER NOT NULL, parse_error_rows INTEGER NOT NULL, status TEXT NOT NULL);
CREATE TABLE text_native_record(
 id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES text_document(id),
 line_number INTEGER NOT NULL, record_type TEXT NOT NULL, event_date TEXT,
 event_number INTEGER, horse_number INTEGER, horse_name TEXT, hr_no TEXT,
 entry_id INTEGER REFERENCES entry(id), source_line_sha256 TEXT NOT NULL,
 link_status TEXT NOT NULL, parsed_json TEXT NOT NULL,
 UNIQUE(document_id,line_number,record_type));
CREATE TABLE text_parse_issue(
 id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES text_document(id),
 line_number INTEGER, issue_code TEXT NOT NULL, record_type TEXT,
 event_date TEXT, event_number INTEGER, horse_number INTEGER,
 details_json TEXT NOT NULL);
CREATE TABLE text_type_coverage(
 text_type TEXT PRIMARY KEY, documents INTEGER NOT NULL, processed_documents INTEGER NOT NULL,
 candidate_rows INTEGER NOT NULL, native_records INTEGER NOT NULL,
 excluded_non_native_rows INTEGER NOT NULL, unresolved_rows INTEGER NOT NULL,
 parse_error_rows INTEGER NOT NULL, status TEXT NOT NULL);
CREATE INDEX ix_text_native_type_date ON text_native_record(record_type,event_date,event_number);
CREATE INDEX ix_text_native_hr_date ON text_native_record(hr_no,event_date);
CREATE INDEX ix_text_parse_issue_code ON text_parse_issue(issue_code);
CREATE VIEW analysis_text_race_weight AS SELECT * FROM text_native_record WHERE record_type='race_weight' AND link_status='official_entry_key_name_linked';
CREATE VIEW analysis_text_entry_equipment AS SELECT * FROM text_native_record WHERE record_type='entry_medical_equipment' AND link_status='official_entry_key_name_linked';
CREATE VIEW analysis_text_daily_training AS SELECT * FROM text_native_record WHERE record_type='daily_training' AND link_status='official_horse_event_linked';
CREATE VIEW analysis_text_start_training AS SELECT * FROM text_native_record WHERE record_type='start_training' AND link_status='official_horse_event_linked';
CREATE VIEW analysis_text_medical AS SELECT * FROM text_native_record WHERE record_type='medical' AND link_status='official_horse_event_linked';
CREATE VIEW analysis_text_track_snapshot AS SELECT * FROM text_native_record WHERE record_type='track_snapshot' AND link_status='confirmed_native_race_day';
CREATE VIEW quarantined_text_records AS SELECT * FROM text_native_record WHERE link_status NOT IN ('official_entry_key_name_linked','official_horse_event_linked','confirmed_native_race_day');
"""

def sha(path:Path)->str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def j(x:object)->str:return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def day(y:str,m:str,d:str)->str:
 y=int(y);y=y+2000 if y<100 else y
 return f'{y:04d}{int(m):02d}{int(d):02d}'
def decoded(path:Path)->list[str]:return path.read_bytes().decode('cp949',errors='replace').splitlines()

def add_record(con,doc,line_no,kind,event_date,event_no,horse_no,name,hr,entry,status,data,line):
 con.execute("INSERT INTO text_native_record(document_id,line_number,record_type,event_date,event_number,horse_number,horse_name,hr_no,entry_id,source_line_sha256,link_status,parsed_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
  (doc,line_no,kind,event_date,event_no,horse_no,name,hr,entry,hashlib.sha256(line.encode()).hexdigest(),status,j(data)))

def issue(con,doc,line_no,code,kind=None,event_date=None,event_no=None,horse_no=None,details=None):
 con.execute("INSERT INTO text_parse_issue(document_id,line_number,issue_code,record_type,event_date,event_number,horse_number,details_json) VALUES (?,?,?,?,?,?,?,?)",
  (doc,line_no,code,kind,event_date,event_no,horse_no,j(details or {})))

def main()->None:
 ap=argparse.ArgumentParser();ap.add_argument('--force',action='store_true');args=ap.parse_args()
 OUT.mkdir(parents=True,exist_ok=True)
 if DB.exists() and not args.force:raise SystemExit(f'refusing to replace without --force: {DB}')
 TMP.unlink(missing_ok=True);shutil.copy2(BASE,TMP)
 con=sqlite3.connect(TMP);con.row_factory=sqlite3.Row
 con.execute('PRAGMA foreign_keys=ON');con.execute('PRAGMA journal_mode=OFF');con.execute('PRAGMA synchronous=OFF');con.executescript(SCHEMA)
 events={}
 entries={}
 for r in con.execute("SELECT v.id event_id,v.event_date,v.event_number,e.id entry_id,e.horse_number,e.horse_name,e.hr_no FROM event v JOIN entry e ON e.event_id=v.id WHERE v.event_type='race'"):
  events[(r['event_date'],r['event_number'])]=r['event_id'];entries[(r['event_date'],r['event_number'],r['horse_number'])]=(r['entry_id'],r['horse_name'],r['hr_no'])
 native_days={x[0] for x in events}
 daily=collections.defaultdict(list);person_code={'조교승인':'승','기수':'기','조교사':'조','조교보':'보','기수후보생':'후'}
 for r in con.execute("SELECT r.id,r.event_date,r.hr_no,r.horse_name,r.training_duration_seconds,r.exercise_person_type,s.normalized_json FROM daily_training_record r JOIN source_row s ON s.id=r.source_row_id"):
  raw=json.loads(r['normalized_json']);st=str(raw.get('stTime') or '');et=str(raw.get('spTime') or '')
  st=st[8:10]+':'+st[10:12] if len(st)>=12 else '';et=et[8:10]+':'+et[10:12] if len(et)>=12 else ''
  daily[(r['event_date'],r['horse_name'],r['training_duration_seconds'],st,et,person_code.get(r['exercise_person_type'],r['exercise_person_type']))].append((r['id'],r['hr_no']))
 start=collections.defaultdict(list)
 for r in con.execute("SELECT id,event_date,hr_no,horse_name,part,part_no,exercise_person_name FROM start_training_record"):
  start[(r['event_date'],r['horse_name'],r['part'],r['part_no'],r['exercise_person_name'])].append((r['id'],r['hr_no']))
 medical=collections.defaultdict(list)
 for r in con.execute("SELECT id,event_date,hr_no,horse_name,part,diagnosis_1,diagnosis_2 FROM medical_record"):
  medical[(r['event_date'],r['horse_name'],r['part'])].append((r['id'],r['hr_no'],r['diagnosis_1'],r['diagnosis_2']))
 totals=collections.defaultdict(collections.Counter)
 docs=list(con.execute("SELECT d.*,a.path FROM text_document d JOIN source_artifact a ON a.id=d.source_artifact_id ORDER BY d.text_type,d.file_date,d.id"))
 for d in docs:
  path=ROOT/d['path'];lines=decoded(path);c=collections.Counter();current=None;title_date=None;start_round=None;section=None
  for n,line in enumerate(lines,1):
   if line.strip():c['nonempty']+=1
   dm=DATE_TITLE.search(line)
   if dm:title_date=day(*dm.groups())
   hm=RACE_HEADING.search(line)
   if hm:current=(day(*hm.group(1,2,3)),int(hm.group(4) or hm.group(5)))
   kind=d['text_type']
   if kind=='dacom13' and re.search(r'■\s*(?:마필|말)취소',line):section='cancellation'
   elif kind=='dacom13' and re.search(r'■\s*기수변경',line):section='jockey_change'
   if kind=='dacom01' and current and (m:=ENTRY_CARD_ROW.match(line)):
    c['candidate']+=1;num,name,breed,sex,age,burden,jockey,trainer,owner=m.groups();num=int(num);candidate=entries.get((*current,num))
    if candidate:
     status='official_entry_key_name_linked' if candidate[1]==name else 'entry_name_conflict';add_record(con,d['id'],n,'entry_card',*current,num,name,candidate[2] if candidate[1]==name else None,candidate[0] if candidate[1]==name else None,status,{'breed_code':breed,'sex':sex,'age':int(age),'burden_weight_kg':float(burden),'jockey_name':jockey,'trainer_name':trainer,'owner_name':owner},line);c['native']+=1
     if status!='official_entry_key_name_linked':c['unresolved']+=1;issue(con,d['id'],n,status,'entry_card',*current,num)
    else:c['excluded']+=1
   elif kind=='dacom12' and current and (m:=WEIGHT_LINE.match(line)):
    c['candidate']+=1;num,name,kg,delta=m.groups();num=int(num);candidate=entries.get((*current,num))
    if candidate:
     status='official_entry_key_name_linked' if candidate[1]==name else 'entry_name_conflict';add_record(con,d['id'],n,'race_weight',*current,num,name,candidate[2] if candidate[1]==name else None,candidate[0] if candidate[1]==name else None,status,{'weight_kg':int(kg),'change_kg':int(delta)},line);c['native']+=1
     if status!='official_entry_key_name_linked':c['unresolved']+=1;issue(con,d['id'],n,status,'race_weight',*current,num)
    else:c['excluded']+=1
   elif kind=='dacom71' and current and (m:=ENTRY_LINE.match(line)) and '.' not in m.group(3)[:12]:
    num,name,detail=int(m.group(1)),m.group(2),m.group(3);candidate=entries.get((*current,num))
    if candidate:
     c['candidate']+=1;status='official_entry_key_name_linked' if candidate[1]==name else 'entry_name_conflict';add_record(con,d['id'],n,'entry_medical_equipment',*current,num,name,candidate[2] if candidate[1]==name else None,candidate[0] if candidate[1]==name else None,status,{'detail_raw':detail},line);c['native']+=1
     if status!='official_entry_key_name_linked':c['unresolved']+=1;issue(con,d['id'],n,status,'entry_medical_equipment',*current,num)
   elif kind=='dacom13':
    tm=TRACK_LINE.search(line);rm=D13_ROW.match(line)
    if title_date in native_days and tm:
     c['candidate']+=1;c['native']+=1;add_record(con,d['id'],n,'track_snapshot',title_date,None,None,None,None,None,'confirmed_native_race_day',{'track_condition':tm.group(1),'moisture_percent':float(tm.group(2))},line)
    elif rm and section:
     y,mo,dd,race_no,horse_no,name,rest=rm.groups();event_date=day(y,mo,dd);race_no=int(race_no);horse_no=int(horse_no);c['candidate']+=1
     if (event_date,race_no) in events:
      candidate=entries.get((event_date,race_no,horse_no));linked=bool(candidate and candidate[1]==name);status='official_entry_key_name_linked' if linked else 'confirmed_native_race_unlinked_entry';record_type='race_cancellation' if section=='cancellation' else 'jockey_change';data={'detail_raw':rest}
      if section=='jockey_change':
       parts=rest.split(maxsplit=3)
       if len(parts)>=3:data={'previous_jockey_name':parts[0],'new_jockey_name':parts[1],'burden_weight_kg':float(parts[2]),'reason':parts[3] if len(parts)>3 else None}
      add_record(con,d['id'],n,record_type,event_date,race_no,horse_no,name,candidate[2] if linked else None,candidate[0] if linked else None,status,data,line);c['native']+=1
      if not linked:c['unresolved']+=1;issue(con,d['id'],n,status,record_type,event_date,race_no,horse_no)
     else:c['excluded']+=1
   elif kind=='dacom55' and (m:=TRAINING_LINE.match(line)):
    c['candidate']+=1;part,trname,partno,name,rider,st,et,hours,minutes,remark=m.groups();duration=int(hours)*3600+int(minutes)*60;event_date=title_date or d['file_date'].replace('-','');key=(event_date,name,duration,st,et,rider);cand=daily.get(key,[]);hrs={x[1] for x in cand}
    if len(hrs)==1:
     hr=next(iter(hrs));add_record(con,d['id'],n,'daily_training',event_date,None,None,name,hr,None,'official_horse_event_linked',{'part':int(part),'part_no':int(partno),'trainer_name_raw':trname,'rider_type':rider,'start_time':st,'end_time':et,'duration_seconds':duration,'remark':remark},line);c['native']+=1
    else:c['unresolved']+=1;issue(con,d['id'],n,'no_unique_official_training_match','daily_training',event_date,details={'candidate_count':len(cand)})
   elif kind=='dacom72' and (m:=MEDICAL_LINE.match(line)):
    c['candidate']+=1;y,mo,dd,name,part,facility,diagnosis=m.groups();event_date=day(y,mo,dd);cand=medical.get((event_date,name,int(part)),[]);matched=[x for x in cand if any(v and (v in diagnosis or diagnosis in v) for v in x[2:])];hrs={x[1] for x in matched}
    if len(hrs)==1:
     hr=next(iter(hrs));add_record(con,d['id'],n,'medical',event_date,None,None,name,hr,None,'official_horse_event_linked',{'part':int(part),'facility':facility,'diagnosis_raw':diagnosis},line);c['native']+=1
    else:c['unresolved']+=1;issue(con,d['id'],n,'no_unique_official_medical_match','medical',event_date,details={'candidate_count':len(cand),'diagnosis_match_count':len(matched)})
   elif kind=='db5' and title_date and (m:=START_TRAIN_LINE.match(line)):
    c['candidate']+=1;part,partno,name,rider,remark=m.groups();key=(title_date,name,int(part),int(partno),rider);cand=start.get(key,[]);hrs={x[1] for x in cand}
    if len(hrs)==1:
     hr=next(iter(hrs));add_record(con,d['id'],n,'start_training',title_date,None,None,name,hr,None,'official_horse_event_linked',{'part':int(part),'part_no':int(partno),'exercise_person_name':rider,'remark':remark},line);c['native']+=1
    else:c['unresolved']+=1;issue(con,d['id'],n,'no_unique_official_start_training_match','start_training',title_date,details={'candidate_count':len(cand)})
   elif kind=='db4':
    tm=START_CHECK_TITLE.search(line)
    if tm:title_date=day(*tm.group(1,2,3));start_round=int(tm.group(4));current=(title_date,int(tm.group(5)))
    elif current and (m:=START_CHECK_ROW.match(line)):
     c['candidate']+=1;num,name,reason,origin,sex,age,rest=m.groups()
     if origin=='제주':
      c['native']+=1;add_record(con,d['id'],n,'start_inspection',*current,int(num),name,None,None,'explicit_native_origin_unlinked_id',{'inspection_round':start_round,'reason':reason,'origin':origin,'sex':sex,'age':int(age),'remainder_raw':rest},line);c['unresolved']+=1
      issue(con,d['id'],n,'explicit_native_start_inspection_official_id_unresolved','start_inspection',*current,int(num),{'inspection_round':start_round})
     else:c['excluded']+=1
  status='processed'
  if d['text_type']=='dacom23':status='already_linked_in_base_db'
  con.execute("INSERT INTO text_parse_summary VALUES (?,?,?,?,?,?,?,?,?,?)",(d['id'],'phase2-v1',len(lines),c['nonempty'],c['candidate'],c['native'],c['excluded'],c['unresolved'],c['error'],status))
  totals[d['text_type']].update(c);totals[d['text_type']]['documents']+=1
 for kind,c in totals.items():
  status='linked_in_base_db' if kind=='dacom23' else ('semantic_records_loaded' if c['native'] else 'processed_no_native_records')
  con.execute("INSERT INTO text_type_coverage VALUES (?,?,?,?,?,?,?,?,?)",(kind,c['documents'],c['documents'],c['candidate'],c['native'],c['excluded'],c['unresolved'],c['error'],status))
  con.execute("UPDATE text_document SET row_parse_status=?,native_link_status=? WHERE text_type=?",('phase2_v1_processed',status,kind))
 con.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)",('text_phase2_scope',j({'parser_version':'phase2-v1','mixed_non_native_content_copied':False,'operational_db_modified':False})))
 con.commit();integrity=con.execute('PRAGMA integrity_check').fetchone()[0];fk=con.execute('PRAGMA foreign_key_check').fetchall();con.close()
 if integrity!='ok' or fk:raise RuntimeError((integrity,fk[:10]))
 DB.unlink(missing_ok=True);TMP.rename(DB)
 result={'passed':True,'database':str(DB.relative_to(ROOT)),'database_sha256':sha(DB),'database_bytes':DB.stat().st_size,'coverage':{k:dict(v) for k,v in totals.items()}}
 (OUT/'validation.json').write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
 manifest={'database':result['database'],'database_sha256':result['database_sha256'],'base_database':str(BASE.relative_to(ROOT)),'base_database_sha256':sha(BASE),'builder':'scripts/build_jeju_native_text_phase2_db.py','verifier':'scripts/verify_jeju_native_text_phase2_db.py','catalog':'data/research/jeju_native_text_phase2_db_20260915/catalog.json','catalog_exporter':'scripts/export_jeju_native_text_phase2_catalog.py','validation':str((OUT/'validation.json').relative_to(ROOT)),'independent_validation':'data/research/jeju_native_text_phase2_db_20260915/independent_validation.json','completion_audit':'data/research/jeju_native_text_phase2_db_20260915/completion_audit.json','readme':'data/research/jeju_native_text_phase2_db_20260915/README.md','report':'docs/JEJU_NATIVE_COMPLETE_RESEARCH_DB_REPORT_2026-09-15.md','existing_operational_database_modified':False}
 (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
 print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
