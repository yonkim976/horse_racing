"""Independent API18 source and time audit, no network or DB mutations."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter, defaultdict
import hashlib, json, sqlite3, re
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
MONTHLY=ROOT/'research/20260929_api_monthly_history'
DB=ROOT/'data/jeju_native_core.sqlite3'
def sha(p):
 d=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):d.update(b)
 return d.hexdigest()
def token(v):
 if type(v) is int:return str(v)
 if isinstance(v,str):return v
 return None
def time_value(v):
 s=token(v)
 if v is None or s in ('','-'):return None,'missing'
 if s is None or not re.fullmatch('[0-9]{14}',s):return None,'invalid_format'
 try:return datetime(int(s[:4]),int(s[4:6]),int(s[6:8]),int(s[8:10]),int(s[10:12]),int(s[12:14])),'valid'
 except ValueError:return None,'invalid_calendar_or_range'
def date_value(v):
 s=token(v)
 if s is None or not re.fullmatch('[0-9]{8}',s):raise ValueError(('invalid eventdate',v))
 datetime(int(s[:4]),int(s[4:6]),int(s[6:8]));return s
def run():
 c=sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True)
 before={'database':str(DB),'sha256':sha(DB),'counts':{},'schema':c.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name").fetchall(),'record_types':dict(c.execute('SELECT record_type,COUNT(*) FROM api_records GROUP BY record_type'))}
 for name, in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
  before['counts'][name]=c.execute('SELECT COUNT(*) FROM "'+name.replace('"','""')+'"').fetchone()[0]
 profiles={h for h,b in c.execute('SELECT horse_id,breed_label_raw FROM horse_profile_observations') if b=='제주마'}
 assert len(profiles)==4617
 c.close();(OUT/'database_before.json').write_text(json.dumps(before,ensure_ascii=False,indent=2))
 ledger=json.loads((MONTHLY/'ledger.json').read_text());stats={'all':Counter(),'native':Counter()};types=defaultdict(Counter);issues=defaultdict(list);pages=[];ids=set();dates=[];native_dates=[];missingids=[]
 for partition in ledger['partitions'].values():
  if partition.get('dataset')!='daily_training':continue
  chosen=partition.get('pages',[])
  if partition.get('date_fallback'):chosen=[p for day in partition['date_fallback']['dates'].values() for p in day['pages']]
  for meta in chosen:
   p=(MONTHLY/meta['response_file']).resolve();assert p.is_relative_to(ROOT)
   digest=sha(p);assert digest==meta['response_sha256']
   data=json.loads(p.read_bytes())['response'];assert data['header']['resultCode']=='00';body=data['body'];assert int(body['pageNo'])==int(meta['page_no'])
   items=body.get('items');rows=items.get('item',[]) if isinstance(items,dict) else []
   if isinstance(rows,dict):rows=[rows]
   assert len(rows)==meta['actual_page_rows']
   counts=Counter();nativecount=0
   for i,r in enumerate(rows,1):
    h=token(r.get('hrNo'));date=date_value(r.get('trDate'));dates.append(date);native=h in profiles
    if native:ids.add(h);native_dates.append(date);nativecount+=1
    if h is None or re.fullmatch('[0-9]+',h) is None:missingids.append({'source_file':str(p.relative_to(ROOT)),'row_no':i,'raw':r})
    start,ss=time_value(r.get('stTime'));end,es=time_value(r.get('spTime'))
    term=r.get('trTerm');termtext=token(term);valid_int=termtext is not None and re.fullmatch('[0-9]+',termtext) is not None;seconds=int(termtext) if valid_int else None
    flags=[]
    if ss!='valid':flags.append('start_'+ss)
    if es!='valid':flags.append('end_'+es)
    if start and start.strftime('%Y%m%d')!=date:flags.append('start_date_mismatch')
    if end and end.strftime('%Y%m%d')!=date:flags.append('end_date_mismatch')
    if start and end and end<start:flags.append('end_before_start')
    elapsed=int((end-start).total_seconds()) if start and end else None
    if seconds is None:flags.append('duration_invalid')
    elif seconds==0:flags.append('duration_zero_unavailable')
    elif elapsed is not None and elapsed!=seconds:flags.append('duration_mismatch')
    good=not flags
    classification='valid_consistent' if good else '|'.join(flags)
    scopes=['all','native'] if native else ['all']
    for scope in scopes:
     stats[scope]['rows']+=1;stats[scope]['start:'+ss]+=1;stats[scope]['end:'+es]+=1;stats[scope]['valid_consistent' if good else 'not_usable_duration']+=1
     if date>'20260919':stats[scope]['after_cutoff']+=1
     for flag in flags:stats[scope]['issue:'+flag]+=1
    counts[classification]+=1
    if flags and len(issues[classification])<5:issues[classification].append({'native':native,'source_file':str(p.relative_to(ROOT)),'row_no':i,'raw':r,'elapsed_seconds':elapsed})
    for field in ('stTime','spTime','trTerm','hrNo','run1Cnt','run2Cnt'):types[field][type(r.get(field)).__name__]+=1
    assert r.get('run1Cnt')==r.get('run2Cnt')==0
   pages.append({'source_file':str(p.relative_to(ROOT)),'sha256':digest,'month':partition['month'],'page_no':meta['page_no'],'all_rows':len(rows),'native_rows':nativecount,'statuses':dict(counts)})
 print('Sources and time audit finished',flush=True)
 result={'created_at_utc':datetime.now(timezone.utc).isoformat(),'database_before_sha256':before['sha256'],'ledger_sha256':sha(MONTHLY/'ledger.json'),'pages':len(pages),'nonempty_pages':sum(x['all_rows']>0 for x in pages),'stats':{k:dict(v) for k,v in stats.items()},'raw_json_types':{k:dict(v) for k,v in types.items()},'native_horses':len(ids),'all_date_range':[min(dates),max(dates)],'native_date_range':[min(native_dates),max(native_dates)],'invalid_raw_id_rows':missingids,'issue_examples':dict(issues),'database_unchanged':sha(DB)==before['sha256']}
 assert result['database_unchanged'];assert result['pages']==337;assert stats['all']['rows']==1444319;assert stats['native']['rows']==908316;assert len(ids)==4545;assert stats['native']['after_cutoff']==927
 (OUT/'independent_source_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));(OUT/'independent_source_pages.json').write_text(json.dumps(pages,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('issue_examples','invalid_raw_id_rows')},ensure_ascii=False,indent=2))
if __name__=='__main__':run()
