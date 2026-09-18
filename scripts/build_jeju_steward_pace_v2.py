"""Versioned steward and lagged sectional/burden candidate features."""
import hashlib,json,sqlite3
from collections import defaultdict,Counter
from datetime import timedelta
from pathlib import Path

import numpy as np
import polars as pl

from horse_racing.analysis.jeju_steward_events_v2 import extract_events
from horse_racing.analysis.jeju_steward_events import historical_features

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/research/jeju_steward_pace_v2_20260918'
OLD=ROOT/'data/research/jeju_steward_events_v1_20260917'
BACK=ROOT/'data/research/jeju_steward_2024_events_20260917'
OBS=ROOT/'data/research/jeju_tempo_pace_features_20260917/observations.parquet'
TARGETS=ROOT/'data/research/jeju_native_transition_features_v1_20260916/context_targets.parquet'
STEWARD=['st2_report_known','st2_event_any','st2_route','st2_wide','st2_interference','st2_start_delay','st2_review_mention','st2_days_since_previous']
PACE_BURDEN=['pb_pre600_relative_3','pb_middle400_relative_3','pb_last200_relative_3',
 'pb_late_slowdown_3','pb_valid_count_3','pb_fast_fade_rate_3','pb_last_fade',
 'pb_fade_x_burden_delta','pb_slowdown_x_burden_delta']

def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str,allow_nan=False))

def main():
    if (OUT/'manifest.json').exists():
        raise FileExistsError('Completed feature artifact already exists')
    OUT.mkdir(exist_ok=True)  # Resume an incomplete build without a sealed manifest.
    obs=pl.read_parquet(OBS)
    history=obs.to_dicts()
    targets=pl.read_parquet(TARGETS).join(obs.select('entry_id','distance_m'),on='entry_id',validate='1:1').to_dicts()
    c=sqlite3.connect(f"file:{ROOT/'data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3'}?mode=ro",uri=True)
    extra={r[0]:(r[1],r[2]) for r in c.execute("""select e.id,e.horse_name,json_extract(s.normalized_json,'$.jeG3fTime')
        from entry e join source_row s on s.id=e.source_row_id""")};c.close()
    roster={}
    for r in history:
        r['horse_name']=extra[r['entry_id']][0]
        roster.setdefault((r['event_date'].isoformat(),r['event_number']),{})[r['horse_number']]=r
    reports=[]
    for r in json.loads((BACK/'reports.json').read_text()):
        reports.append(dict(date=r['date'],number=r['race_number'],judgement=r['raw']['judgement']))
    for r in json.loads((OLD/'source_reports.json').read_text()):
        reports.append(dict(date=r['race_date_local'],number=r['race_number'],judgement=r['judgement']))
    known=set();events=[];bullets=[]
    for r in reports:
        key=(r['date'],r['number'])
        if key not in roster or not (r['judgement'] or '').strip():continue
        known.add(key)
        for i,raw in enumerate(r['judgement'].split('●')):
            raw=raw.strip()
            if not raw:continue
            bid=f"{r['date']}:{r['number']}:{i}"
            extracted=extract_events(raw,roster[key])
            for j,e in enumerate(extracted):
                e.update(event_id=f'v2:{bid}:{j}',bullet_id=bid,date=r['date'],race_number=r['number'],
                         race_id=next(iter(roster[key].values()))['race_id'],field='judgement')
                events.append(e)
            bullets.append(dict(bullet_id=bid,date=r['date'],race_number=r['number'],raw=raw,
                bullet_sha256=hashlib.sha256(raw.encode()).hexdigest(),event_ids=[e['event_id'] for e in extracted],
                any_explicit=any(e['status']=='explicit_rule_match' for e in extracted)))
    save('events.json',events)
    # Freeze fresh audit sample before inspecting outcomes of any new candidate.
    oldhashes=set()
    for path in [OLD/'audit_sample_locked.json',BACK/'audit_sample_locked.json']:
        oldhashes|={e['bullet_sha256'] for e in json.loads(path.read_text())}
    eligible=[b for b in bullets if b['date']<'2026-01-01' and b['bullet_sha256'] not in oldhashes]
    audit=[]
    for flag,n in [(True,32),(False,16)]:
        pool=[b for b in eligible if b['any_explicit']==flag]
        audit+=sorted(pool,key=lambda b:hashlib.sha256(b['bullet_id'].encode()).hexdigest())[:n]
    save('audit_sample_locked.json',audit)
    st=historical_features(history,history,known,events)
    events_by_entry=defaultdict(list);reviews=defaultdict(list)
    for e in events:
        if e['status']=='explicit_rule_match':
            for a in e['affected']:events_by_entry[a['entry_id']].append(e)
        else:
            for m in e['mentions']:
                if m['matched']:reviews[m['entry_id']].append(e['event_id'])
    features={};lineage=[]
    for row in st:
        prev=row['previous_entry_id'];es=events_by_entry[prev];k=row['previous_report_known']
        f=dict(entry_id=row['entry_id'],st2_report_known=float(k),st2_event_any=float(row['previous_explicit_event']) if k else None,
            st2_route=float(row['previous_route_restriction']) if k else None,
            st2_wide=float(row['previous_wide_trip']) if k else None,
            st2_interference=float(row['previous_running_interference']) if k else None,
            st2_start_delay=float(any('start_delay' in e['event_types'] for e in es)) if k else None,
            st2_review_mention=float(bool(reviews[prev])) if k else None,st2_days_since_previous=row['days_since_previous'])
        features[row['entry_id']]=f
        lineage.append(dict(entry_id=row['entry_id'],previous_entry_id=prev,previous_date=row['previous_date'],
            event_ids=row['source_event_ids'],review_ids=reviews[prev]))
    by_race=defaultdict(list)
    for r in history:
        try:g3=float(extra[r['entry_id']][1]);g1=float(r['g1f_seconds']);total=float(r['total_seconds']);early=float(r['s1f_seconds'])
        except (ValueError,TypeError):continue
        if r['outcome_status']=='normal_completed' and r['segment_quality']=='usable' and r['distance_m']>=900 and 0<g1<g3<total and total-g3>early>0:
            by_race[r['race_id']].append(dict(entry_id=r['entry_id'],pre600=total-g3,middle400=g3-g1,last200=g1,slowdown=g1-(g3-g1)/2))
    splits={}
    for group in by_race.values():
        med={k:float(np.median([r[k] for r in group])) for k in ['pre600','middle400','last200']}
        for r in group:
            for k in med:r[k+'_relative']=r[k]-med[k]
            r['fade']=float(r['pre600_relative']<=-.3 and r['last200_relative']>=.5 and r['slowdown']>=.5)
            splits[r['entry_id']]=r
    by_horse=defaultdict(list)
    for r in history:by_horse[r['horse_id']].append(r)
    for rs in by_horse.values():rs.sort(key=lambda r:(r['event_date'],r['entry_id']))
    pace_lineage=[]
    for t in targets:
        past=[r for r in by_horse[t['horse_id']] if r['event_date']<=t['event_date']-timedelta(days=2)]
        same=[r for r in past if r['distance_m']==t['distance_m']][-3:]
        valid=[splits[r['entry_id']] for r in same if r['entry_id'] in splits]
        f=features[t['entry_id']]
        for dest,src in [('pb_pre600_relative_3','pre600_relative'),('pb_middle400_relative_3','middle400_relative'),
                         ('pb_last200_relative_3','last200_relative'),('pb_late_slowdown_3','slowdown'),('pb_fast_fade_rate_3','fade')]:
            f[dest]=float(np.mean([r[src] for r in valid])) if valid else None
        f['pb_valid_count_3']=len(valid)
        last=splits.get(past[-1]['entry_id']) if past else None
        f['pb_last_fade']=last['fade'] if last else None
        previous_weight=past[-1]['burden_kg'] if past else None
        delta=t['declared_burden_kg']-previous_weight if t['declared_burden_kg'] is not None and previous_weight is not None else None
        f['pb_fade_x_burden_delta']=last['fade']*delta if last and delta is not None else None
        f['pb_slowdown_x_burden_delta']=last['slowdown']*delta if last and delta is not None else None
        pace_lineage.append(dict(entry_id=t['entry_id'],event_date=t['event_date'],cutoff_date=t['event_date']-timedelta(days=2),
            same_distance_source_ids=[r['entry_id'] for r in same],previous_entry_id=past[-1]['entry_id'] if past else None,
            max_history_date=past[-1]['event_date'] if past else None))
    pl.from_dicts(list(features.values()),infer_schema_length=None).write_parquet(OUT/'features.parquet')
    pl.from_dicts(lineage,infer_schema_length=None).write_parquet(OUT/'steward_lineage.parquet')
    pl.from_dicts(pace_lineage,infer_schema_length=None).write_parquet(OUT/'pace_lineage.parquet')
    save('summary.json',dict(reports=len(known),events=len(events),status_counts=dict(Counter(e['status'] for e in events)),
         features=len(features),audit_bullets=len(audit),feature_groups=dict(STEWARD=STEWARD,PACE_BURDEN=PACE_BURDEN),
         availability='Historical publication timestamps unverified; race-date T-2 retrospective assumption'))
    paths=[OBS,TARGETS,OLD/'source_reports.json',BACK/'reports.json',Path(__file__),
        ROOT/'src/horse_racing/analysis/jeju_steward_events_v2.py',ROOT/'docs/JEJU_STEWARD_MARKETS_PROTOCOL_2026-09-18.md']
    save('manifest.json',dict(inputs={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        outputs={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir()}))
    print((OUT/'summary.json').read_text())

if __name__=='__main__':main()
