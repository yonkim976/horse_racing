"""Reconstruct trial features from original response pages, without model code."""
from pathlib import Path
import json,hashlib,sys
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
SOURCE=ROOT/'jeju/research/20261018_debut_trial_source_audit_v1/outputs'
MAIN=ROOT/'jeju/research/20261018_debut_trial_ablation_v1/outputs'
BASE=ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet'
ADDED=['trial_peer_relative_time_mean3','trial_peer_relative_time_n3','trial_days_since_latest_event_pre','trial_event_count_pre']
ALLOWED={'합격','불합격','주행불합격','출발불합격','불합격(능검)','발주불합격','불합격(발검)'}
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def reconstruct():
    b=pd.read_parquet(BASE);targets=b[b.observed_starts.eq(0)].copy();assert len(targets)==1946 and targets.horse_id.nunique()==1946
    d=pd.read_parquet(SOURCE/'api20_trial_event_rows.parquet');assert len(d)==8824 and d.api_record_id.is_unique
    pages={};checked=[]
    for r in d.itertuples(index=False):
        path=(ROOT/r.raw_relative_path).resolve();assert path.is_relative_to(ROOT)
        if path not in pages:
            raw=path.read_bytes();assert len(raw)==r.response_bytes and hashlib.sha256(raw).hexdigest()==r.response_sha256
            items=json.loads(raw)['response']['body']['items']['item'];pages[path]=items if isinstance(items,list) else [items]
        raw=json.loads(r.payload_json);assert pages[path][int(r.record_index)-1]==raw
        assert hashlib.sha256(r.payload_json.encode()).hexdigest()==r.payload_sha256
        day=pd.to_datetime(str(raw['trainDate']),format='%Y%m%d').strftime('%Y-%m-%d')
        assert day==r.trial_date and raw['trainNo']==r.trial_number and raw['chulNo']==r.horse_number
        assert str(raw['hrNo'])==r.horse_id and raw['majong']==r.breed_label_raw=='제주' and raw['meet']=='제주'
        key=f'{day}|2|{int(raw["trainNo"])}';assert key==r.trial_event_key and r.event_key_valid
        order=raw.get('ord');text=str(order).strip()
        try:iv=int(text);order_ok=text==str(iv) and 1<=iv<=89
        except (ValueError,TypeError):order_ok=False
        try:t=float(raw.get('rcTime'))
        except (ValueError,TypeError):t=np.nan
        ok=bool(order_ok and np.isfinite(t) and t>0 and raw.get('passFlag') in ALLOWED)
        assert ok==r.valid_for_relative_time_candidate
        assert np.isclose(t,r.rcTime_seconds_numeric,equal_nan=True,atol=0,rtol=0)
        if np.isfinite(t):assert t==r.finish_time_seconds
        checked.append({'id':int(r.api_record_id),'horse_id':r.horse_id,'date':day,'event':key,'order':int(raw['trainNo']),'serial':raw['daySerial'],'time':t,'valid':ok})
    x=pd.DataFrame(checked);assert not x.duplicated(['event','horse_id']).any()
    assert x.groupby('event').serial.nunique().eq(1).all() and x.event.nunique()==961
    events={k:g for k,g in x.groupby('event',sort=False)};byhorse={k:g.sort_values(['date','order','id']) for k,g in x.groupby('horse_id',sort=False)}
    slots=[];refs=[];all_history_ids=[]
    for r in targets.itertuples(index=False):
        assert pd.Timestamp(r.history_cutoff)==pd.Timestamp(r.race_date)-pd.Timedelta(days=2)
        history=byhorse[r.horse_id];history=history[history.date.le(r.history_cutoff)]
        all_history_ids.extend((int(r.api_record_id),int(v)) for v in history.id)
        recent=history.tail(3);values=[]
        for row in recent.itertuples(index=False):
            peers=events[row.event];peers=peers[peers.valid&peers.horse_id.ne(row.horse_id)]
            median=float(np.median(peers.time)) if len(peers) else np.nan
            eligible=row.valid and len(peers)>=2
            value=(row.time-median)/median if eligible else np.nan
            if eligible:values.append(value)
            slots.append({'target_api_record_id':int(r.api_record_id),'source_api_record_id':int(row.id),'date':row.date,'peer_n':len(peers),'peer_median':median,'relative':value,'valid':eligible})
        refs.append({'api_record_id':int(r.api_record_id),ADDED[0]:float(np.mean(values)) if values else np.nan,ADDED[1]:float(len(values)),ADDED[2]:float((pd.Timestamp(r.race_date)-pd.Timestamp(history.date.max())).days) if len(history) else np.nan,ADDED[3]:float(len(history))})
    line=pd.read_parquet(SOURCE/'cold_target_trial_lineage.parquet');assert len(line)==3500
    assert set(all_history_ids)==set(zip(line.target_api_record_id.astype(int),line.target_trial_api_record_id.astype(int)))
    recent_ids={(r['target_api_record_id'],r['source_api_record_id']) for r in slots}
    actual=line[line.is_latest3_trial_record];assert recent_ids==set(zip(actual.target_api_record_id.astype(int),actual.target_trial_api_record_id.astype(int)))
    assert len(slots)==3240 and sum(r['valid'] for r in slots)==3168
    peers=pd.read_parquet(SOURCE/'trial_event_relative_peer_ledger.parquet').set_index(['target_api_record_id','target_trial_api_record_id'])
    for r in slots:
        actual=peers.loc[(r['target_api_record_id'],r['source_api_record_id'])]
        assert r['peer_n']==actual.valid_peer_count_excluding_target and r['valid']==actual.relative_time_gap_candidate_eligible
        assert np.isclose(r['peer_median'],actual.valid_peer_median_rcTime_seconds,atol=1e-12,rtol=0,equal_nan=True)
        assert np.isclose(r['relative'],actual.relative_time_gap_candidate,atol=1e-12,rtol=0,equal_nan=True)
    ref=pd.DataFrame(refs);ref.to_parquet(HERE/'ROOT_TRIAL_FEATURE_REFERENCE.parquet',index=False)
    pd.DataFrame(slots).to_parquet(HERE/'ROOT_LAST3_TRIAL_LEDGER.parquet',index=False)
    proof={'status':'PASS','original_response_pages_verified':len(pages),'API20_rows_reparsed':len(d),'target_rows':len(ref),'events':len(events),'all_history_slots':len(line),'recent3_slots':len(slots),'eligible_recent3_slots':sum(r['valid'] for r in slots),'root_fits':0,'source_audit_manifest_sha256':sha(SOURCE/'audit_manifest.json')}
    (HERE/'ROOT_TRIAL_SOURCE_REVIEW.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof,indent=2))

def verify_prepared():
    ref=pd.read_parquet(HERE/'ROOT_TRIAL_FEATURE_REFERENCE.parquet').set_index('api_record_id')
    f=pd.read_parquet(MAIN/'features_f1_style6_debut_trial4.parquet');b=pd.read_parquet(BASE)
    pd.testing.assert_frame_equal(f[b.columns],b,check_exact=True)
    assert f.columns.tolist()==b.columns.tolist()+ADDED
    got=f.set_index('api_record_id').loc[ref.index];errors={}
    for c in ADDED:
        assert np.allclose(got[c],ref[c],atol=1e-12,rtol=0,equal_nan=True),c
        errors[c]=float(np.nanmax(np.abs(got[c]-ref[c])))
    assert f.loc[f.observed_starts.gt(0),ADDED].isna().all().all()
    proof={'status':'PASS','old_feature_values_exact':True,'cold_targets':len(ref),'cold_eval_rows':int((f.observed_starts.eq(0)&f.year.ge(2024)).sum()),'new_feature_count':4,'max_errors':errors,'root_fits':0,'feature_sha256':sha(MAIN/'features_f1_style6_debut_trial4.parquet')}
    (HERE/'ROOT_FEATURE_REVIEW.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof,indent=2))

if __name__=='__main__':
    if sys.argv[1:] == ['prepared']:verify_prepared()
    elif not sys.argv[1:]:reconstruct()
    else:raise SystemExit('usage: check_features.py [prepared]')
