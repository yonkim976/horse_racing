"""Independent complete state replay using a rank-one covariance identity.

Does not import the input builder, training code, or TB implementation.
No fitting and no source mutation. Expected states are held only in memory.
"""
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
STUDY = HERE.parent
RAW = ROOT/'jeju/research/20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet'
TARGET = ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet'
STATE = STUDY/'inputs/state_features.parquet'
NAMES = ['state_rank_mean','state_rank_sd','state_distance_slope','state_distance_sd',
         'state_rank_current','state_rank_current_sd','state_rank_n',
         'state_days_since_rank_observation','state_rank_current_field_gap','state_rank_current_field_rank']


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def evolve(original, day):
    if original is None:
        return np.zeros(2),np.diag([2.,.5]),None,0
    m,v,last,n=original
    days=int((day-last)/np.timedelta64(1,'D'))
    assert days>=0
    decay=math.exp(-days/1500.)
    v=v*decay**2+np.diag([.035,.008])*min(days/30.,24.)
    v[0,0]=min(v[0,0],2.);v[1,1]=min(v[1,1],.5)
    assert np.linalg.eigvalsh(v).min()>0
    return m*decay,v,last,n


def main():
    source=pd.read_parquet(RAW)
    allowed={800,900,1000,1110,1200,1300,1400,1610}
    excluded=json.loads((ROOT/'jeju/data/horse_exclusions.json').read_text())['horses']
    banned={str(k) for k,v in excluded.items() if not v['reimport_allowed']}
    events=[];valid_ids=[];history_rows=0
    for rid,g in source.loc[source.race_date.ge('2010-01-01')].groupby('race_id',sort=False):
        n=len(g)
        ok=(n>=4 and g.horse_id.nunique()==n and g.horse_number.nunique()==n and
            g.api_record_id.nunique()==n and g.horse_number.gt(0).all() and
            np.isfinite(g.horse_number).all() and np.equal(g.horse_number,np.floor(g.horse_number)).all() and
            g.race_distance_m.nunique(dropna=False)==1 and g.race_distance_m.iloc[0] in allowed and
            g.race_date.nunique()==1 and g.finish_position.sort_values().tolist()==list(range(1,n+1)) and
            g.valid_time.all() and g.started.all() and np.isfinite(g.finish_time_seconds).all() and
            g.finish_time_seconds.gt(0).all() and not (set(g.horse_id)&banned))
        if not ok:continue
        assert not g.horse_id.isna().any()
        g=g.sort_values('horse_number')
        events.append((np.datetime64(g.race_date.iloc[0],'D'),rid,g))
        valid_ids.append(rid);history_rows+=n
    events.sort(key=lambda item:(item[0],item[1]))
    assert len(events)==7066 and history_rows==69752,(len(events),history_rows)
    target=pd.read_parquet(TARGET,columns=['api_record_id','race_id','race_date','horse_id','distance_m','history_cutoff'])
    assert len(target)==52155 and target.api_record_id.is_unique and target.race_id.nunique()==5206
    target['day']=pd.to_datetime(target.race_date).to_numpy(dtype='datetime64[D]')-np.timedelta64(2,'D')
    assert np.array_equal(target.day.to_numpy(dtype='datetime64[D]'),pd.to_datetime(target.history_cutoff).to_numpy(dtype='datetime64[D]'))
    saved=pd.read_parquet(STATE).set_index('api_record_id').loc[target.api_record_id]
    assert len(saved)==len(target) and (saved.race_id.to_numpy()==target.race_id.to_numpy()).all()
    states={};cursor=0;expected=np.empty((len(target),8));last_dates=np.full(len(target),np.datetime64('NaT','D'))
    used_races=0;minimum_eigenvalue=2.
    for day,ix in target.groupby('day',sort=True).indices.items():
        day=np.datetime64(day,'D')
        while cursor<len(events) and events[cursor][0]<=day:
            event_day=events[cursor][0];pending={}
            while cursor<len(events) and events[cursor][0]==event_day:
                _,rid,g=events[cursor];cursor+=1;used_races+=1
                ids=g.horse_id.tolist();h=np.array([1.,(float(g.race_distance_m.iloc[0])-1100.)/500.])
                before=[evolve(states.get(horse),event_day) for horse in ids]
                mus=np.array([h@m for m,v,last,n in before]);vs=np.array([h@v@h for m,v,last,n in before])
                ranks=g.finish_position.to_numpy();n=len(g)
                for i,horse in enumerate(ids):
                    assert horse not in pending,'same horse twice on one history day'
                    other=np.arange(n)!=i
                    scale=np.sqrt(1/(1+math.pi*(vs[i]+vs[other])/8))
                    p=expit((mus[i]-mus[other])*scale)
                    gradient=4*np.mean(((ranks[i]<ranks[other]).astype(float)-p)*scale)
                    curvature=4*np.mean(p*(1-p)*scale**2)
                    m,v,last,count=before[i]
                    vh=v@h;denominator=1+curvature*(h@vh)
                    after_v=v-curvature/denominator*np.outer(vh,vh)
                    after_m=m+vh/denominator*gradient
                    minimum_eigenvalue=min(minimum_eigenvalue,float(np.linalg.eigvalsh(after_v).min()))
                    assert np.isfinite(after_m).all() and minimum_eigenvalue>0
                    pending[horse]=(after_m,after_v,event_day,count+1)
            states.update(pending)
        for i in ix:
            row=target.iloc[i];m,v,last,count=evolve(states.get(row.horse_id),day)
            h=np.array([1.,(float(row.distance_m)-1100.)/500.])
            age=np.nan if last is None else int((day-last)/np.timedelta64(1,'D'))
            expected[i]=[m[0],math.sqrt(v[0,0]),m[1],math.sqrt(v[1,1]),h@m,math.sqrt(h@v@h),count,age]
            if last is not None:assert last<=day;last_dates[i]=last
    frame=pd.DataFrame(expected,columns=NAMES[:8])
    grouped=frame.state_rank_current.groupby(target.race_id)
    frame[NAMES[8]]=frame.state_rank_current-grouped.transform('mean')
    frame[NAMES[9]]=grouped.rank(pct=True,method='average')
    errors={}
    for col in NAMES:
        left=frame[col].to_numpy();right=saved[col].to_numpy(float)
        assert np.array_equal(np.isnan(left),np.isnan(right)),col+' missingness'
        mask=np.isfinite(left)
        error=float(np.max(np.abs(left[mask]-right[mask])))
        errors[col]=error
        assert error<1e-9,(col,error)
    result={'passed':True,'all_target_rows':len(target),'target_races':target.race_id.nunique(),
            'historical_eligible_races':len(events),'historical_eligible_rows':history_rows,
            'historical_races_consumed_at_last_cutoff':used_races,'feature_cells_checked':len(target)*10,
            'no_history_rows':int(frame.state_rank_n.eq(0).sum()),
            'minimum_update_covariance_eigenvalue':minimum_eigenvalue,'maximum_errors':errors,
            'method':'independent rank-one covariance update; no builder or TB module imported',
            'source_sha256':sha(RAW),'target_sha256':sha(TARGET),'state_sha256':sha(STATE),
            'verifier_sha256':sha(Path(__file__).resolve())}
    with (HERE/'STATE_VERIFICATION.json').open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
