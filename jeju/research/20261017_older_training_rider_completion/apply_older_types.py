"""Immutable phase plans and transactional exact-event rider supplements."""
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import argparse, fcntl, importlib.util, json, os, sqlite3

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
spec=importlib.util.spec_from_file_location('prior_loader',ROOT/'jeju/research/20261017_training_rider_website_completion/apply_website_types.py')
prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
DB=prior.DB; FIELDS=prior.FIELDS; CHANGED=prior.CHANGED
require=prior.require;sha=prior.sha;connect=prior.connect;write=prior.write
URL='https://race.kra.co.kr/trainer/dailyAllTrainDetail.do'

def records(path):
    with path.open() as f:
        for line in f:
            if line.strip(): yield json.loads(line)

def paths(phase):
    require(phase in ('initial609','full'),'Invalid phase')
    return HERE/(phase+'.plan.jsonl'),HERE/(phase+'.application_manifest.json')

def plan(phase, candidates):
    out,_=paths(phase);require(not out.exists(),'Plan already exists')
    if phase=='initial609':
        candidates=ROOT/'jeju/research/20261017_older_training_rider_sources/daily_sample_matches.json'
        evidence=iter(json.loads(candidates.read_text())['evidence'])
    else:
        candidates=candidates.resolve(strict=True)
        require(candidates.is_relative_to(HERE/'collection'),'Candidates outside collection')
        evidence=records(candidates)
    names=prior.jockey_roster(); c=connect();seen=set();pages={};counts=Counter()
    before=sha(DB)
    allowed=[ROOT/'jeju/research/20261017_older_training_rider_sources/homepage',HERE/'collection']
    with out.open('x') as f:
        for e in evidence:
            rid=int(e['row_id']);require(rid not in seen,'Duplicate candidate');seen.add(rid)
            old=dict(c.execute('SELECT * FROM daily_training_rider_type_assignments WHERE daily_training_api_row_id=?',(rid,)).fetchone())
            d=c.execute('SELECT * FROM daily_training_api_rows WHERE daily_training_api_row_id=?',(rid,)).fetchone()
            require(all(d[k]==old[k] for k in FIELDS),'Source snapshot mismatch')
            require(old['rider_type']=='미분류' and d['prGubun_raw']=='-' and d['training_date']<'2026-04-17','Ineligible candidate')
            start=e['start'];end=e['end']
            # Full collectors may use HH:MM or date + HH:MM; compare explicit date too.
            start=d['training_date']+' '+start if len(start)==5 else start
            end=d['training_date']+' '+end if len(end)==5 else end
            require((d['horse_id'],d['training_date'],d['start_time_local'],d['end_time_local'],d['duration_seconds'])==
                    (str(e['horse_id']),e['date'],start+':00',end+':00',e['duration_seconds']),'Event identity mismatch')
            require(d['duration_seconds'] and d['duration_seconds']>0,'Missing duration')
            p=(ROOT/e['source_path']).resolve(strict=True)
            require(any(p.is_relative_to(a) for a in allowed),'Evidence outside allowed scope')
            expected=e['source_sha256'];key=str(p)
            if key not in pages: pages[key]=sha(p)
            require(pages[key]==expected,'Page SHA mismatch')
            require(e['url']==URL and str(e['form_fields']['meet'])=='2' and e['form_fields']['trDate'].replace('/','-')==e['date'],'Official POST request mismatch')
            kind,jockey=prior.classifier.parse_label(e['label'],names)
            require(kind!='미분류' and (kind,jockey)==(e['candidate_type'],e.get('jockey_name')),'Unconfirmed classification')
            new=dict(old);new.update(rider_type=kind,type_status='website_same_event_type',website_type=kind,
                website_label_raw=e['label'],website_jockey_name=jockey,website_source_path=str(p.relative_to(ROOT)),website_sha256=expected)
            row={'daily_training_api_row_id':rid,'old_type':old['rider_type'],'new_type':kind,
                'old_status':old['type_status'],'new_status':new['type_status'],**{k:old[k] for k in FIELDS},
                **{k:new[k] for k in CHANGED},'url':URL,'evidence_status':'exact_event_official_website','old':old,'new':new}
            f.write(prior.canon(row)+'\n');counts[kind]+=1
    c.close();require(before==sha(DB),'DB changed while planning')
    result={'phase':phase,'candidate_rows':len(seen),'new_type_counts':dict(counts),'plan_sha256':sha(out),
        'database_sha256':before,'input':str(candidates.relative_to(ROOT)),'input_sha256':sha(candidates),'source_pages':len(pages)}
    write(out.with_suffix('.summary.json'),result);print(json.dumps(result,ensure_ascii=False))

def apply(phase,gate):
    path,receipt=paths(phase);plan_sha=sha(path)
    if receipt.exists():
        r=json.loads(receipt.read_text());require(r['plan_sha256']==plan_sha,'Receipt mismatch')
        c=connect();n=0
        for v in records(path):
            key=(v['daily_training_api_row_id'],)
            require(dict(c.execute('SELECT * FROM daily_training_rider_type_assignments WHERE daily_training_api_row_id=?',key).fetchone())==v['new'],'Applied row changed')
            guard=c.execute('SELECT rider_type,rider_type_status,website_jockey_name FROM daily_training_rider_type_values WHERE daily_training_api_row_id=?',key).fetchone()
            require(tuple(guard)==(v['new_type'],v['new_status'],v['new']['website_jockey_name']),'Applied source changed');n+=1
        c.close();print(json.dumps({'status':'already_applied','updated_rows':0,'plan_rows':n,'database_sha256':sha(DB)}));return
    summary=json.loads(path.with_suffix('.summary.json').read_text());verified=json.loads(gate.read_text())
    require(verified.get('passed') is True and verified['plan_sha256']==plan_sha==summary['plan_sha256'],'Independent gate missing/mismatch')
    require(summary['database_sha256']==sha(DB),'DB changed since plan')
    backup=HERE/'before_older_completion.sqlite3';baseline=HERE/'baseline_manifest.json'
    side=ROOT/'jeju/data/jeju_native_core.rider_types_manifest.json'
    if not baseline.exists():
        require(phase=='initial609' and not backup.exists(),'Baseline unavailable')
        source=connect();dest=sqlite3.connect(backup);source.backup(dest,pages=4096);dest.close();source.close()
        write(baseline,{'source_sha256':summary['database_sha256'],'backup_sha256':sha(backup),'backup_bytes':backup.stat().st_size})
        write(HERE/'prior_rider_types_manifest.json',json.loads(side.read_text()))
    c=connect(readonly=False);schema=prior.schema_snapshot(c)
    counts=lambda:dict(c.execute('SELECT rider_type,count(*) FROM daily_training_rider_type_assignments GROUP BY rider_type').fetchall())
    before=counts();n=0;c.execute('BEGIN IMMEDIATE')
    try:
        for v in records(path):
            rid=v['daily_training_api_row_id'];old=c.execute('SELECT * FROM daily_training_rider_type_assignments WHERE daily_training_api_row_id=?',(rid,)).fetchone()
            require(dict(old)==v['old'] and old['rider_type']=='미분류','Concurrent assignment change')
            src=c.execute('SELECT * FROM daily_training_api_rows WHERE daily_training_api_row_id=?',(rid,)).fetchone()
            require(all(src[k]==old[k] for k in FIELDS),'Concurrent source change')
            require({k:v['old'][k] for k in v['old'] if k not in CHANGED}=={k:v['new'][k] for k in v['new'] if k not in CHANGED},'Disallowed plan change')
            c.execute('UPDATE daily_training_rider_type_assignments SET '+','.join(k+'=?' for k in CHANGED)+' WHERE daily_training_api_row_id=?',tuple(v['new'][k] for k in CHANGED)+(rid,))
            actual=c.execute('SELECT * FROM daily_training_rider_type_assignments WHERE daily_training_api_row_id=?',(rid,)).fetchone()
            require(dict(actual)==v['new'],'Stored value mismatch')
            guard=c.execute('SELECT rider_type,rider_type_status,website_jockey_name FROM daily_training_rider_type_values WHERE daily_training_api_row_id=?',(rid,)).fetchone()
            require(tuple(guard)==(v['new_type'],v['new_status'],v['new']['website_jockey_name']),'Guarded value mismatch');n+=1
        require(prior.schema_snapshot(c)==schema,'Schema changed')
        require(not c.execute('PRAGMA foreign_key_check').fetchall(),'FK failure')
        require(c.execute('PRAGMA integrity_check').fetchone()[0]=='ok','Integrity failure')
        c.commit()
    except BaseException: c.rollback();raise
    after=counts();c.close()
    result={'status':'applied','phase':phase,'updated_rows':n,'applied_at_utc':datetime.now(timezone.utc).isoformat(),
       'plan_sha256':plan_sha,'gate_sha256':sha(gate),'database_sha256_before':summary['database_sha256'],
       'database_sha256_after':sha(DB),'before_type_counts':before,'after_type_counts':after,
       'backup':str(backup.relative_to(ROOT)),'schema_changed':False,'integrity_check':'ok','foreign_key_violations':0}
    write(receipt,result)
    temp=side.with_suffix('.json.tmp');temp.write_text(json.dumps({'application_manifest':str(receipt.relative_to(ROOT)),
       'sha256':sha(receipt),'database_sha256':result['database_sha256_after']},ensure_ascii=False,indent=2)+'\n');os.replace(temp,side)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--phase',choices=['initial609','full'],required=True)
    a.add_argument('--candidates',type=Path);a.add_argument('--apply',action='store_true');a.add_argument('--gate',type=Path)
    args=a.parse_args()
    lock=ROOT/'jeju/research/20261017_core_refresh/refresh.lock'
    with lock.open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.apply: apply(args.phase,args.gate)
        else: plan(args.phase,args.candidates)
