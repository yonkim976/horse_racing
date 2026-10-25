"""Independently reparse API20 pages and calculate the fresh cold-horse trial4."""
from pathlib import Path
import sqlite3,json,hashlib
import numpy as np
import pandas as pd
from independent_build import ROOT,HERE,dump_new

ALLOWED={'합격','불합격','주행불합격','출발불합격','불합격(능검)','발주불합격','불합격(발검)'}
ADDED=['trial_peer_relative_time_mean3','trial_peer_relative_time_n3','trial_days_since_latest_event_pre','trial_event_count_pre']

def main():
    cold=pd.read_parquet(HERE/'ROOT_COLD_TARGETS.parquet');horses=cold.horse_id.astype(str).tolist()
    conn=sqlite3.connect((ROOT/'jeju/data/jeju_native_core.sqlite3').as_uri()+'?mode=ro',uri=True)
    conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN')
    target=pd.read_sql_query('SELECT t.*,a.payload_json FROM running_trial_rows t JOIN api_records a USING(api_record_id) WHERE t.meet_code=? AND t.horse_id IN ('+','.join('?' for _ in horses)+') AND t.trial_date<=?',conn,params=[2]+horses+[cold.history_cutoff.max()])
    cutoffs=dict(zip(cold.horse_id.astype(str),cold.history_cutoff));target['horse_id']=target.horse_id.astype(str)
    target=target[[r.trial_date<=cutoffs[r.horse_id] and r.breed_assessment=='api_native_label' and json.loads(r.payload_json).get('majong')=='제주' for r in target.itertuples(index=False)]]
    keys=target[['trial_date','meet_code','trial_number']].drop_duplicates().sort_values(['trial_date','trial_number'])
    marks=','.join('(?,?,?)' for _ in range(len(keys)));params=[v.item() if isinstance(v,np.generic) else v for row in keys.itertuples(index=False,name=None) for v in row]
    d=pd.read_sql_query('SELECT t.*,a.payload_json,a.payload_sha256,a.record_index,a.source_artifact_id,s.raw_relative_path,s.response_bytes,s.sha256 AS response_sha256,s.collected_at_utc FROM running_trial_rows t JOIN api_records a USING(api_record_id) JOIN source_artifacts s USING(source_artifact_id) WHERE (t.trial_date,t.meet_code,t.trial_number) IN (VALUES '+marks+')',conn,params=params)
    conn.close();d['horse_id']=d.horse_id.astype(str)
    pages={};parsed=[]
    for r in d.itertuples(index=False):
        path=(ROOT/r.raw_relative_path).resolve();assert path.is_relative_to(ROOT)
        if path not in pages:
            page=path.read_bytes();assert len(page)==r.response_bytes and hashlib.sha256(page).hexdigest()==r.response_sha256
            items=json.loads(page)['response']['body']['items']['item'];pages[path]=items if isinstance(items,list) else [items]
        raw=json.loads(r.payload_json);assert hashlib.sha256(r.payload_json.encode()).hexdigest()==r.payload_sha256
        assert pages[path][int(r.record_index)-1]==raw
        assert str(raw['hrNo'])==r.horse_id and str(raw['trainDate'])==r.trial_date.replace('-','') and raw['trainNo']==r.trial_number and raw['chulNo']==r.horse_number
        if raw.get('majong')!='제주' or r.breed_assessment!='api_native_label':continue
        assert raw['meet']=='제주' and int(r.meet_code)==2 and r.horse_id!='3005648' and 'rcDist' not in raw
        value=raw.get('ord');validordinal=(not isinstance(value,bool) and isinstance(value,(int,str)) and str(value).isdigit() and str(int(value))==str(value) and 1<=int(value)<=89)
        try:time=float(raw.get('rcTime'))
        except (TypeError,ValueError):time=np.nan
        valid=bool(validordinal and np.isfinite(time) and time>0 and raw.get('passFlag') in ALLOWED)
        parsed.append(dict(api_record_id=int(r.api_record_id),horse_id=r.horse_id,date=r.trial_date,event_no=int(r.trial_number),
                           event=f'{r.trial_date}|2|{r.trial_number}',serial=raw['daySerial'],time=time,valid=valid))
    x=pd.DataFrame(parsed);assert not x.duplicated(['event','horse_id']).any() and not x.duplicated(['event','api_record_id']).any()
    assert x.groupby('event').serial.nunique().eq(1).all();d.to_parquet(HERE/'ROOT_API20_FULL_SOURCE_ROWS.parquet',index=False)
    events=dict(tuple(x.groupby('event',sort=False)));byhorse=dict(tuple(x.groupby('horse_id',sort=False)));refs=[];slots=[]
    for r in cold.itertuples(index=False):
        h=byhorse.get(str(r.horse_id),x.iloc[:0]);h=h[h.date<=r.history_cutoff].sort_values(['date','event_no','api_record_id']);values=[]
        for s in h.tail(3).itertuples(index=False):
            peers=events[s.event];peers=peers[peers.valid&peers.horse_id.ne(s.horse_id)];median=float(peers.time.median()) if len(peers) else np.nan
            okay=s.valid and len(peers)>=2;relative=(s.time-median)/median if okay else np.nan
            if okay:values.append(relative)
            slots.append(dict(target_api_record_id=int(r.api_record_id),source_api_record_id=s.api_record_id,date=s.date,peer_n=len(peers),peer_median=median,relative=relative,valid=bool(okay)))
        refs.append(dict(api_record_id=int(r.api_record_id),**{ADDED[0]:float(np.mean(values)) if values else np.nan,ADDED[1]:float(len(values)),ADDED[2]:float((pd.Timestamp(r.race_date)-pd.Timestamp(h.date.max())).days) if len(h) else np.nan,ADDED[3]:float(len(h))}))
    ref=pd.DataFrame(refs);ref.to_parquet(HERE/'ROOT_FRESH_TRIAL4.parquet',index=False)
    pd.DataFrame(slots).to_parquet(HERE/'ROOT_FRESH_TRIAL_SLOTS.parquet',index=False)
    proof=dict(status='PASS',cold_rows=len(cold),linked_target_registered_records=len(target),full_peer_source_rows=len(d),explicit_jeju_rows=len(x),events=x.event.nunique(),original_pages_verified=len(pages),
               latest3_slots=len(slots),usable_latest3_slots=sum(r['valid'] for r in slots),cold_rows_without_usable_trial=int(ref[ADDED[1]].eq(0).sum()),model_predictions=0,
               feature_source_collected_at_min=d.collected_at_utc.min(),feature_source_collected_at_max=d.collected_at_utc.max(),historical_publication_times_proven=False)
    dump_new('ROOT_FRESH_TRIAL_REVIEW.json',proof);print(json.dumps(proof,indent=2))

if __name__=='__main__':main()
