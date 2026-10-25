"""Review and apply only exact-event, official-website rider type supplements."""
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone
import argparse
import fcntl
import hashlib
import importlib.util
import json
import sqlite3

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DB = ROOT/'jeju/data/jeju_native_core.sqlite3'
TABLE = 'daily_training_rider_type_assignments'
FIELDS = ('daily_training_api_artifact_id','prGubun_raw','prNo_raw','horse_id',
          'training_date','start_time_local','end_time_local','duration_seconds')
CHANGED = ('rider_type','type_status','website_type','website_label_raw',
           'website_jockey_name','website_source_path','website_sha256')

def require(ok, text):
    if not ok:
        raise ValueError(text)

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):
            h.update(b)
    return h.hexdigest()

def canon(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def write(path, value):
    require(not path.exists(),f'Output already exists: {path}')
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def load(name, relative):
    spec=importlib.util.spec_from_file_location(name,ROOT/relative)
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

reader=load('exact_event_html_reader','jeju/research/20261015_training_rider_identity/source_review/collect_kra_training_html.py')
classifier=load('exact_event_type_classifier','jeju/research/20261015_training_rider_types/classify_riders.py')

def connect(path=DB, readonly=True):
    c=sqlite3.connect(path.as_uri()+('?mode=ro' if readonly else '?mode=rw'),uri=True,timeout=15)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c

def evidence_inputs(additional):
    old=ROOT/'jeju/research/20261015_training_rider_unclassified_review/website/retry_website_event_evidence.json'
    recent=ROOT/'jeju/research/20261017_training_rider_unclassified/website_check.json'
    paths=[old,recent]
    result=json.loads(old.read_text())['evidence_rows']
    latest=json.loads(recent.read_text())
    pages={p['source_path']:p for p in latest['pages']}
    result.extend({**r,'url':pages[r['source_path']]['url']} for r in latest['observations'])
    if additional:
        p=additional.resolve(strict=True)
        require(p.is_relative_to(HERE/'collection'),'Additional evidence must be in collection folder')
        paths.append(p)
        result.extend(json.loads(line) for line in p.read_text().splitlines() if line.strip())
    return result,[{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in paths]

def jockey_roster():
    manifest=json.loads((ROOT/'data/research/jockey_roster_20261008/manifest.json').read_text())
    names=set()
    for meet in (1,2,3):
        p=ROOT/f'data/research/jockey_roster_20261008/api_{meet}.json'
        require({r['api_sha256'] for r in manifest['rows'] if r['meet_code']==meet}=={sha(p)},'Roster SHA mismatch')
        body=json.loads(p.read_text())['response']['body']
        items=body['items']['item']
        items=[items] if isinstance(items,dict) else items
        require(len(items)==int(body['totalCount']),'Incomplete roster')
        names.update(r['jkName'] for r in items if r.get('jkName') not in (None,'','-'))
    return names

def plan(additional, path):
    require(not path.exists(),'Plan output exists')
    evidence,inputs=evidence_inputs(additional)
    names=jockey_roster()
    c=connect()
    pages={}; choices=defaultdict(list); rejected=[]; already=Counter()
    allowed=[ROOT/'jeju/research/20261015_training_rider_unclassified_review',
             ROOT/'jeju/research/20261017_training_rider_unclassified',HERE/'collection']
    for e in evidence:
        row_id=int(e.get('row_id',e.get('daily_training_api_row_id',0)))
        require(row_id>0,'Evidence row ID missing')
        d=c.execute('SELECT * FROM daily_training_api_rows WHERE daily_training_api_row_id=?',(row_id,)).fetchone()
        t=c.execute('SELECT * FROM daily_training_rider_type_assignments WHERE daily_training_api_row_id=?',(row_id,)).fetchone()
        require(d is not None and t is not None,'Missing source row or assignment')
        require(all(d[k]==t[k] for k in FIELDS),'Source changed since assignment')
        if t['rider_type']!='미분류':
            already[t['rider_type']]+=1
            continue
        require(d['prGubun_raw']=='-','Missing category supplement cannot override explicit API type')
        p=(ROOT/e['source_path']).resolve(strict=True)
        require(any(p.is_relative_to(a) for a in allowed),'Evidence path outside permitted folders')
        expected=e.get('source_sha256',e.get('sha256'))
        require(isinstance(expected,str) and len(expected)==64,'Evidence SHA missing')
        key=(str(p),expected,d['horse_id'])
        if key not in pages:
            require(sha(p)==expected,'Source SHA mismatch')
            parsed=reader.parse_page(p.read_bytes(),'text/html',d['horse_id'])
            require(parsed['profile_id_matches_url'] and parsed['training_table_found'],'Website horse/table mismatch')
            text=reader.decode_html(p.read_bytes(),'text/html')
            require('관:주로조교' in text and '기승자범례' in text,'Official legend missing')
            events=defaultdict(list)
            for w in parsed['training_rows']:
                if reader.clock_minutes(w['end'])-reader.clock_minutes(w['start'])!=w['duration_minutes']:
                    continue
                events[(w['date'],w['start'],w['end'],w['duration_minutes']*60)].append(w['website_name_raw'])
            pages[key]=events
        require(d['start_time_local'] and d['end_time_local'] and d['duration_seconds']>0,'Exact-event timing unavailable')
        require(d['start_time_local'][17:]=='00' and d['end_time_local'][17:]=='00',
                'Website minute precision cannot verify nonzero source seconds')
        ek=(d['training_date'],d['start_time_local'][11:16],d['end_time_local'][11:16],d['duration_seconds'])
        labels=pages[key].get(ek,[])
        if len(labels)!=1:
            rejected.append({'row_id':row_id,'reason':'event_absent_or_ambiguous','source_path':e['source_path']})
            continue
        label=next(iter(labels))
        kind,jockey=classifier.parse_label(label,names)
        if kind=='미분류':
            rejected.append({'row_id':row_id,'reason':'website_type_unconfirmed','label':label})
            continue
        supplied=e.get('url',e.get('website_page_url'))
        require(supplied==reader.profile_url(d['horse_id']),'Official evidence URL mismatch')
        new=dict(t)
        new.update(rider_type=kind,type_status='website_same_event_type',website_type=kind,
                   website_label_raw=label,website_jockey_name=jockey,
                   website_source_path=str(p.relative_to(ROOT)),website_sha256=expected)
        choices[row_id].append({'old':dict(t),'new':new,'url':supplied})
    rows=[]
    for row_id,options in sorted(choices.items()):
        kinds={(o['new']['rider_type'],o['new']['website_jockey_name']) for o in options}
        if len(kinds)!=1:
            rejected.append({'row_id':row_id,'reason':'conflicting_official_website_types'})
            continue
        # Prefer latest collected evidence; all competing sources agree on type.
        v=options[-1]; old=v['old']; new=v['new']
        rows.append({'daily_training_api_row_id':row_id,'old_type':old['rider_type'],
                     'new_type':new['rider_type'],'old_status':old['type_status'],'new_status':new['type_status'],
                     **{k:old[k] for k in FIELDS},**{k:new[k] for k in CHANGED[2:]},
                     'url':v['url'],'evidence_status':'exact_event_official_website',
                     'old':old,'new':new})
    c.close()
    path.write_text(''.join(canon(r)+'\n' for r in rows))
    result={'plan':str(path.relative_to(ROOT)),'plan_sha256':sha(path),'database_sha256':sha(DB),
            'input_evidence':inputs,'input_observations':len(evidence),'candidate_rows':len(rows),
            'new_type_counts':dict(Counter(r['new_type'] for r in rows)),
            'pages_independently_parsed':len(pages),'already_classified_observations':dict(already),
            'rejected':rejected,'database_modified':False}
    write(path.with_suffix('.summary.json'),result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('rejected','input_evidence')},ensure_ascii=False))

def schema_snapshot(c):
    return [tuple(r) for r in c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]

def apply(path, expected, receipt):
    if receipt.exists():
        previous=json.loads(receipt.read_text())
        require(previous.get('status')=='applied' and previous.get('plan_sha256')==sha(path),
                'Existing receipt belongs to another reviewed plan')
        rows=[json.loads(s) for s in path.read_text().splitlines() if s.strip()]
        c=connect()
        for v in rows:
            actual=c.execute('SELECT * FROM daily_training_rider_type_assignments WHERE daily_training_api_row_id=?',
                             (v['daily_training_api_row_id'],)).fetchone()
            require(actual is not None and dict(actual)==v['new'],'Previously applied assignment changed')
            guarded=c.execute('SELECT rider_type,rider_type_status FROM daily_training_rider_type_values WHERE daily_training_api_row_id=?',
                              (v['daily_training_api_row_id'],)).fetchone()
            require(tuple(guarded)==(v['new_type'],v['new_status']),'Previously applied source changed')
        c.close()
        print(json.dumps({'status':'already_applied','updated_rows':0,'plan_rows':len(rows),
                          'plan_sha256':sha(path),'database_sha256':sha(DB)},ensure_ascii=False))
        return
    sidecar=ROOT/'jeju/data/jeju_native_core.rider_types_manifest.json'
    require(not sidecar.exists(),'Rider completion sidecar already exists')
    summary=json.loads(path.with_suffix('.summary.json').read_text())
    require(sha(path)==summary['plan_sha256'],'Plan SHA changed')
    require(expected==summary['database_sha256']==sha(DB),'Database changed since reviewed plan')
    verification=HERE/'verification/preapply_verification.json'
    require(verification.is_file(),'Independent preapply verification missing')
    verified=json.loads(verification.read_text())
    require(verified.get('passed') is True and verified.get('plan_sha256')==sha(path),'Preapply verification not passed for this plan')
    rows=[json.loads(s) for s in path.read_text().splitlines() if s.strip()]
    backup=HERE/'before_website_completion.sqlite3'
    require(not backup.exists(),'Backup exists; do not replace earlier snapshot')
    source=connect();dest=sqlite3.connect(backup)
    source.backup(dest,pages=4096);dest.close();source.close()
    c=connect(readonly=False)
    before_schema=schema_snapshot(c)
    before=dict(Counter(dict(r)['rider_type'] for r in c.execute('SELECT rider_type FROM daily_training_rider_type_assignments')))
    c.execute('BEGIN IMMEDIATE')
    try:
        for v in rows:
            r=c.execute('SELECT * FROM daily_training_rider_type_assignments WHERE daily_training_api_row_id=?',(v['daily_training_api_row_id'],)).fetchone()
            require(dict(r)==v['old'],'Concurrent assignment change')
            d=c.execute('SELECT * FROM daily_training_api_rows WHERE daily_training_api_row_id=?',(v['daily_training_api_row_id'],)).fetchone()
            require(all(d[k]==v['old'][k] for k in FIELDS),'Concurrent source change')
            require(r['rider_type']=='미분류','Only unclassified rows may be supplemented')
            c.execute('UPDATE daily_training_rider_type_assignments SET '+','.join(k+'=?' for k in CHANGED)+' WHERE daily_training_api_row_id=?',
                      tuple(v['new'][k] for k in CHANGED)+(v['daily_training_api_row_id'],))
        require(schema_snapshot(c)==before_schema,'Schema changed')
        require(not c.execute('PRAGMA foreign_key_check(daily_training_rider_type_assignments)').fetchall(),'Foreign key violation')
        require(c.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Integrity failure')
        for v in rows:
            actual=dict(c.execute('SELECT * FROM daily_training_rider_type_assignments WHERE daily_training_api_row_id=?',(v['daily_training_api_row_id'],)).fetchone())
            require(actual==v['new'],'Stored classification mismatch')
            actual_view=c.execute('SELECT rider_type,rider_type_status FROM daily_training_rider_type_values WHERE daily_training_api_row_id=?',(v['daily_training_api_row_id'],)).fetchone()
            require(tuple(actual_view)==(v['new_type'],v['new_status']),'Guarded view mismatch')
        c.commit()
    except BaseException:
        c.rollback();raise
    after=dict(Counter(dict(r)['rider_type'] for r in c.execute('SELECT rider_type FROM daily_training_rider_type_assignments')))
    c.close()
    result={'status':'applied','applied_at_utc':datetime.now(timezone.utc).isoformat(),
            'updated_rows':len(rows),'plan':str(path.relative_to(ROOT)),'plan_sha256':sha(path),
            'backup':str(backup.relative_to(ROOT)),'backup_sha256':sha(backup),
            'database_sha256_before':expected,'database_sha256_after':sha(DB),
            'database_bytes_after':DB.stat().st_size,'before_type_counts':before,'after_type_counts':after,
            'changed_columns':CHANGED,'integrity_check':'ok','schema_changed':False,
            'raw_training_rows_changed':False,'idempotency':'Applied rows equal reviewed new assignment; no-op replay is verified separately.'}
    write(receipt,result)
    write(sidecar,{'application_manifest':str(receipt.relative_to(ROOT)),'sha256':sha(receipt),
                   'database_sha256':result['database_sha256_after']})
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    a=argparse.ArgumentParser()
    a.add_argument('--additional',type=Path)
    a.add_argument('--plan',type=Path,default=HERE/'plan.jsonl')
    a.add_argument('--apply',action='store_true')
    a.add_argument('--expected-db-sha256')
    a.add_argument('--receipt',type=Path,default=HERE/'application_manifest.json')
    args=a.parse_args()
    path=args.plan.resolve();require(path.is_relative_to(HERE),'Plan must be in task folder')
    with (ROOT/'jeju/research/20261017_core_refresh/refresh.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.apply:
            target=args.receipt.resolve();require(target.is_relative_to(HERE),'Receipt must be in task folder')
            apply(path,args.expected_db_sha256,target)
        else:
            plan(args.additional,path)
