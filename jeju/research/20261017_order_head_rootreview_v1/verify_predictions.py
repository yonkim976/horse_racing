"""Independent full joint reconstruction and proper event metrics. No fitting."""
from pathlib import Path
from itertools import combinations
import json,hashlib
import numpy as np
import pandas as pd
from independent_math import joint

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
MAIN=ROOT/'jeju/research/20261017_conditional_order_head_v1/outputs'
STYLE=ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def event_metrics(rid,date,model,orders,prob,truth):
    result=[]
    for pool in ('WIN','QNL','EXA','TRI'):
        d={}
        for order,p in zip(orders,prob):
            key=tuple(order[:{'WIN':1,'QNL':2,'EXA':2,'TRI':3}[pool]])
            if pool=='QNL':key=tuple(sorted(key))
            d[key]=d.get(key,0.)+float(p)
        target=tuple(truth[:{'WIN':1,'QNL':2,'EXA':2,'TRI':3}[pool]])
        if pool=='QNL':target=tuple(sorted(target))
        assert abs(sum(d.values())-1)<1e-12
        best=min(d,key=lambda k:(-d[k],k))
        result.append(dict(race_id=rid,race_date=date,model=model,pool=pool,nll=-np.log(d[target]),brier=sum(p*p for p in d.values())-2*d[target]+1,hit=int(best==target),top_key='-'.join(map(str,best)),top_probability=d[best],true_probability=d[target]))
    return result

def main():
    fit=json.loads((MAIN/'FIT_ARTIFACTS.json').read_text())
    stds=json.loads((HERE/'ROOT_H1_STANDARDIZATION.json').read_text())
    prediction=pd.read_parquet(MAIN/'evaluation_ordered_joint.parquet')
    saved_groups=dict(tuple(prediction.groupby('race_id',sort=False)))
    features=pd.read_parquet(STYLE/'features.parquet')
    result=[];refs=[];audit=[];errors=[]
    for year in (2024,2025,2026):
        f=fit['folds'][str(year)];s=stds[str(year)]
        scores=pd.read_parquet(STYLE/f'F1_STYLE6_{year}/evaluation_scores.parquet')
        data=features.loc[features.year.eq(year)].merge(scores,on='api_record_id',validate='one_to_one')
        for rid,g in data.groupby('race_id',sort=True):
            rid=str(rid);g=g.sort_values('horse_number');nums=g.horse_number.to_numpy(int)
            raw=g[s['raw_columns']].to_numpy(float);missing=~np.isfinite(raw)
            imputed=np.where(missing,np.asarray(s['raw_imputation_means']),raw)
            x=np.concatenate([imputed,missing[:,[1,3,5]].astype(float)],axis=1)
            x=(x-np.asarray(s['center']))/np.asarray(s['scale']);x[:,s['degenerate']]=0
            utilities=x@np.asarray(f['beta'])/f['order_temperature']
            sets,q,idx,p=joint(g.score.to_numpy(),f['saved_tau_for_native_q_only'],utilities)
            _,_,_,control=joint(g.score.to_numpy(),f['saved_tau_for_native_q_only'],g.score.to_numpy())
            orders=nums[idx];uniform=np.repeat(q/6,6)
            saved=saved_groups.pop(rid).set_index(['horse_no_1','horse_no_2','horse_no_3'])
            ordered=saved.loc[pd.MultiIndex.from_arrays(orders.T)]
            e=max(float(abs(ordered.p_ordered_joint.to_numpy()-p).max()),float(abs(ordered.control_p_ordered_joint.to_numpy()-control).max()),float(abs(ordered.uniform_p_ordered_joint.to_numpy()-uniform).max()))
            assert e<1e-12,(rid,e);errors.append(e)
            assert abs(p.sum()-1)<1e-12 and np.allclose(p.reshape(-1,6).sum(1),q,atol=1e-12,rtol=0)
            truth=g.sort_values('finish_position').horse_number.to_numpy(int)[:3]
            date=str(g.race_date.iloc[0]);mask=np.all(orders==truth,axis=1);assert mask.sum()==1
            trueq=float(q[[set(a)==set(truth) for a in nums[sets]]][0])
            for model,probs in [('learned',p),('fixed',control),('uniform',uniform)]:
                result.extend(event_metrics(rid,date,model,orders,probs,truth))
                audit.append(dict(race_id=rid,race_date=date,year=year,model=model,set_nll=-np.log(trueq),conditional_nll=-np.log(float(probs[mask][0])/trueq),tri_nll=-np.log(float(probs[mask][0]))))
            if year==2026:
                out=pd.DataFrame(orders,columns=['horse_no_1','horse_no_2','horse_no_3']);out['race_id']=rid;out['p_root']=p;out['control_p_root']=control;refs.append(out)
    assert not saved_groups
    metrics=pd.DataFrame(result);metrics.to_csv(HERE/'ROOT_EVENT_METRICS.csv',index=False)
    pd.DataFrame(audit).to_csv(HERE/'ROOT_NLL_DECOMPOSITION.csv',index=False)
    pd.concat(refs,ignore_index=True).to_parquet(HERE/'ROOT_2026_JOINT_REFERENCE.parquet',index=False)
    out=dict(status='PASS',races=len(errors),ordered_rows=len(prediction),max_probability_error=max(errors),ordered_joint_sha256=sha(MAIN/'evaluation_ordered_joint.parquet'),fits_refits=0,coherence=True)
    (HERE/'ROOT_PREDICTION_REVIEW.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
    print(metrics.groupby(['model','pool']).agg(races=('hit','size'),hits=('hit','sum'),nll=('nll','mean'),brier=('brier','mean')).to_string())

if __name__=='__main__':main()
