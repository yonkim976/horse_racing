"""Join official API303 and raw result checkpoints into separate research files."""
import hashlib
import json
import math
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from collections import Counter

import polars as pl
from horse_racing.analysis.jeju_tempo_pace import build_features,historical_observations

ROOT=Path(__file__).resolve().parents[1]
API=ROOT/'data/research/jeju_tempo_api303_20260917'
PARENT=ROOT/'data/research/jeju_native_transition_features_v1_20260916'
DB=ROOT/'data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3'
OUT=ROOT/'data/research/jeju_tempo_pace_features_20260917'

def sha(p):return hashlib.file_digest(p.open('rb'),'sha256').hexdigest()

def main():
    OUT.mkdir(exist_ok=False)
    official={};coverage=[]
    for path in sorted(API.glob('*.json')):
        if path.name in ('manifest.json','request_ledger.json'):continue
        blob=json.loads(path.read_text());count=0
        for page in blob['payloads']:
            body=page['response']['body'];items=body.get('items',{})
            items=items.get('item',[]) if isinstance(items,dict) else []
            if isinstance(items,dict):items=[items]
            count+=len(items)
            for r in items:
                if str(r['rcDate'])>'20260912':continue
                assert r['meet']=='제주'
                key=(str(r['rcDate']),int(r['rcNo']))
                assert key not in official,key
                raw=str(r.get('tempo',''))
                r['tempo_numeric']='①②③④⑤'.index(raw)+1 if raw in list('①②③④⑤') else None
                r['source_file']=path.name;r['source_sha256']=sha(path)
                official[key]=r
        expected=int(blob['payloads'][0]['response']['body']['totalCount'])
        assert count==expected,(path,count,expected)
        coverage.append({'query':blob['meta']['query'],'returned':count,'totalCount':expected})
    c=sqlite3.connect(f'file:{DB}?mode=ro',uri=True);c.row_factory=sqlite3.Row
    extra={}
    for row in c.execute("""SELECT e.id entry_id,v.event_date,v.event_number,v.distance_m,v.grade,e.segment_quality,
        json_extract(s.normalized_json,'$.sj_3cOrd') c3_rank,
        json_extract(s.normalized_json,'$.sj_4cOrd') c4_rank,
        json_extract(s.normalized_json,'$.je_3cTime') c3_seconds,
        json_extract(s.normalized_json,'$.je_4cTime') c4_seconds,
        json_extract(s.normalized_json,'$.jeS1fTime') s1f_seconds
      FROM entry e JOIN event v ON v.id=e.event_id JOIN source_row s ON s.id=e.source_row_id
      WHERE v.event_type='race' AND v.event_date<='20260912'"""):
        extra[row['entry_id']]=dict(row)
    c.close()
    rows=[]
    for r in pl.read_parquet(PARENT/'context_history.parquet').to_dicts():
        x=extra[r['entry_id']];r.update({k:v for k,v in x.items() if k!='event_date'})
        o=official.get((x['event_date'],x['event_number']),{})
        r['tempo']=o.get('tempo_numeric');r['corner_4']=o.get('corner_4')
        r['total_seconds']=r['finish_time_ms']/1000 if r['finish_time_ms'] else None
        m=r['track_moisture_percent']
        r['track_class']=None if m is None else 'dry' if m<=5 else 'good' if m<=9 else 'moist' if m<=14 else 'saturated' if m<=19 else 'sloppy'
        for name in ['c3_rank','c4_rank','early_rank']:
            v=r.get(name)
            if v is None or not 1<=v<=r['field_size']:r[name]=None
        rows.append(r)
    obs=historical_observations(rows)
    targets=pl.read_parquet(PARENT/'context_targets.parquet').to_dicts()
    for r in targets:r['distance_m']=extra[r['entry_id']]['distance_m']
    features,lineage=build_features(targets,obs)
    pl.from_dicts(features,infer_schema_length=None).write_parquet(OUT/'features.parquet')
    pl.from_dicts(obs,infer_schema_length=None).write_parquet(OUT/'observations.parquet')
    pl.from_dicts(lineage,infer_schema_length=None).write_parquet(OUT/'lineage.parquet')
    (OUT/'official_races.json').write_text(json.dumps(list(official.values()),ensure_ascii=False,indent=2))
    (OUT/'coverage.json').write_text(json.dumps({'requests':coverage,'official_races':len(official),
       'feature_rows':len(features),'by_year':dict(Counter(str(r['event_date'].year) for r in rows if r.get('tempo') is not None))},ensure_ascii=False,indent=2))
    for p in [Path('/private/tmp/jeju_track_api_swagger.json'),Path('/private/tmp/jeju_track_api_portal.html')]:
        if p.exists():shutil.copyfile(p,OUT/p.name)
    manifest={'parents':{str(PARENT/'manifest.json'):sha(PARENT/'manifest.json'),str(API/'manifest.json'):sha(API/'manifest.json')},
        'code':{str(Path(__file__)):sha(Path(__file__)),str(ROOT/'src/horse_racing/analysis/jeju_tempo_pace.py'):sha(ROOT/'src/horse_racing/analysis/jeju_tempo_pace.py')},
        'files':{p.name:sha(p) for p in OUT.iterdir()}}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print('features',len(features),'official races',len(official))

if __name__=='__main__':main()
