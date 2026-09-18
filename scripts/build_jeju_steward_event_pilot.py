"""Snapshot local primary reports, freeze role rules, build retrospective histories."""
import hashlib
import json
import sqlite3
from pathlib import Path
from datetime import datetime, UTC

import polars as pl
from horse_racing.analysis.jeju_steward_events import extract, historical_features

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/research/jeju_steward_events_v1_20260917'
OBS=ROOT/'data/research/jeju_tempo_pace_features_20260917/observations.parquet'
DB=ROOT/'data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3'


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str,allow_nan=False))


def main():
    OUT.mkdir(exist_ok=False)
    save('protocol_lock.json',dict(created_at=datetime.now(UTC).isoformat(),
        rules_sha256=sha(ROOT/'src/horse_racing/analysis/jeju_steward_events.py'),
        plan_sha256=sha(ROOT/'docs/JEJU_NATIVE_STEWARD_NEXT_STAGE_PLAN_2026-09-17.md'),
        source_observations_sha256=sha(OBS),no_new_model_fit=True))
    history=pl.read_parquet(OBS).to_dicts()
    c=sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True)
    names=dict(c.execute('select id,horse_name from entry'));c.close()
    roster={}
    for row in history:
        row['horse_name']=names[row['entry_id']]
        key=(row['event_date'].isoformat(),row['event_number'])
        roster.setdefault(key,{})[row['horse_number']]=row
    c=sqlite3.connect('file:'+str(ROOT/'data/horse_racing.sqlite3')+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
    reports=[dict(r) for r in c.execute("select * from race_steward_reports where meet_code=2 and race_date_local between '2025-01-01' and '2026-09-12' order by race_date_local,race_number")];c.close()
    save('source_reports.json',reports)
    events=[];known=set();coverage=[]
    for report in reports:
        key=(report['race_date_local'],report['race_number'])
        coverage.append(dict(date=key[0],race_number=key[1],matched=key in roster,report_id=report['id']))
        if key not in roster:continue
        if report['judgement'] and report['judgement'].strip():known.add(key)
        for field in ['judgement','additional_judgement']:
            for i,raw in enumerate((report[field] or '').split('●')):
                x=extract(raw.strip(),roster[key])
                if not x:continue
                x.update(event_id=f"{report['id']}:{field}:{i}",date=key[0],race_number=key[1],
                         race_id=next(iter(roster[key].values()))['race_id'],field=field,
                         report_id=report['id'],observed_at_ms=report['observed_at_ms'],
                         first_publication_time_verified=False)
                events.append(x)
    save('events.json',events);save('report_coverage.json',coverage)
    features=historical_features(history,history,known,events)
    pl.from_dicts(features,infer_schema_length=None).write_parquet(OUT/'features.parquet')
    audit=[]
    for status,n in [('explicit_rule_match',32),('review_required',16)]:
        eligible=[e for e in events if '2025-07-01'<=e['date']<='2025-12-31' and e['status']==status and e['field']=='judgement']
        audit.extend(sorted(eligible,key=lambda e:hashlib.sha256(e['event_id'].encode()).hexdigest())[:n])
    save('audit_sample_locked.json',audit)
    summary=dict(reports=len(reports),matched_reports=sum(x['matched'] for x in coverage),
       nonempty_primary_reports=len(known),candidate_bullets=len(events),
       status_counts=pl.from_dicts(events,infer_schema_length=None).group_by('field','status','source_kind').len().to_dicts(),
       affected_entry_ids=len({a['entry_id'] for e in events if e['field']=='judgement' for a in e['affected']}),
       audit_sample=len(audit),feature_rows=len(features))
    save('summary.json',summary)
    save('manifest.json',{'files':{p.name:sha(p) for p in OUT.iterdir() if p.is_file()}})
    print(json.dumps(summary,ensure_ascii=False))
    for e in audit:
        print(json.dumps(dict(id=e['event_id'],date=e['date'],status=e['status'],pred=[a['horse_number'] for a in e['affected']],text=e['raw_bullet']),ensure_ascii=False))


if __name__=='__main__':main()
