"""Apply frozen v1 rules to a new-year corpus; preserve prior artifacts."""
import hashlib,json,sqlite3
from pathlib import Path
from collections import Counter
import polars as pl
from horse_racing.analysis.jeju_steward_events import extract,historical_features

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/research/jeju_steward_2024_backfill_20260917'
OUT=ROOT/'data/research/jeju_steward_2024_events_20260917'
PRIOR=ROOT/'data/research/jeju_steward_events_v1_20260917'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,x):(OUT/name).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str))


def main():
    OUT.mkdir(exist_ok=False)
    lock=json.loads((PRIOR/'protocol_lock.json').read_text())
    assert sha(ROOT/'src/horse_racing/analysis/jeju_steward_events.py')==lock['rules_sha256']
    history=pl.read_parquet(ROOT/'data/research/jeju_tempo_pace_features_20260917/observations.parquet').to_dicts()
    c=sqlite3.connect('file:'+str(ROOT/'data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3')+'?mode=ro',uri=True)
    names=dict(c.execute('select id,horse_name from entry'));c.close()
    roster={}
    for r in history:
        r['horse_name']=names[r['entry_id']]
        roster.setdefault((r['event_date'].isoformat(),r['event_number']),{})[r['horse_number']]=r
    expected={k for k in roster if k[0].startswith('2024')}
    seen=set();matched=set();events=[];reports=[];excluded=[]
    for path in sorted(RAW.glob('2024*.json')):
        blob=json.loads(path.read_text());count=0
        for page in blob['payloads']:
            body=page['response']['body'];rows=(body.get('items') or {}).get('item',[])
            if isinstance(rows,dict):rows=[rows]
            count+=len(rows)
            for r in rows:
                day=str(r['rcDate']);assert day==blob['meta']['day'] and r['meet']=='제주'
                d=day[:4]+'-'+day[4:6]+'-'+day[6:];key=(d,int(r['rcNo']))
                assert key not in seen;seen.add(key)
                if key not in expected:excluded.append(key);continue
                matched.add(key);reports.append(dict(date=d,race_number=key[1],source_file=path.name,raw=r))
                for field,rawfield in [('judgement','judgement'),('additional_judgement','addJudgement')]:
                    for i,bullet in enumerate(str(r.get(rawfield) or '').split('●')):
                        x=extract(bullet.strip(),roster[key])
                        if x:
                            x.update(event_id=f'2024:{day}:{key[1]}:{field}:{i}',date=d,race_number=key[1],
                                race_id=next(iter(roster[key].values()))['race_id'],field=field,
                                source_file=path.name,source_sha256=sha(path),observed_at_ms=blob['meta']['retrieved_at_ms'],first_publication_time_verified=False)
                            events.append(x)
        assert count==int(blob['payloads'][0]['response']['body']['totalCount'])
    missing=sorted(expected-matched);save('reports.json',reports);save('events.json',events)
    save('coverage.json',dict(expected_native_races=len(expected),api_races=len(seen),matched=len(matched),missing=missing,excluded_race_keys=excluded,
        by_status=dict(Counter(e['status'] for e in events)),candidate_bullets=len(events),
        affected_entry_rows=len({a['entry_id'] for e in events if e['field']=='judgement' for a in e['affected']})))
    # Exact same rule, new year validation sample selected before reading labels.
    audit=[]
    for status,n in [('explicit_rule_match',32),('review_required',16)]:
        eligible=[e for e in events if e['status']==status and e['field']=='judgement']
        audit.extend(sorted(eligible,key=lambda e:hashlib.sha256(e['event_id'].encode()).hexdigest())[:n])
    save('audit_sample_locked.json',audit)
    previous=json.loads((PRIOR/'events.json').read_text());priorreports=json.loads((PRIOR/'source_reports.json').read_text())
    known={(r['race_date_local'],r['race_number']) for r in priorreports if r.get('judgement') and (r['race_date_local'],r['race_number']) in roster}
    known|={k for k in matched}
    features=historical_features(history,history,known,events+previous)
    pl.from_dicts(features,infer_schema_length=None).write_parquet(OUT/'features_2024_2026.parquet')
    save('manifest.json',dict(files={p.name:sha(p) for p in OUT.iterdir()},parents={str(RAW/'manifest.json'):sha(RAW/'manifest.json'),str(PRIOR/'manifest.json'):sha(PRIOR/'manifest.json')},rules_sha256=lock['rules_sha256']))
    print((OUT/'coverage.json').read_text())
    for e in audit:print(json.dumps(dict(id=e['event_id'],status=e['status'],pred=[a['horse_number'] for a in e['affected']],text=e['raw_bullet']),ensure_ascii=False))


if __name__=='__main__':main()
