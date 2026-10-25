"""Independent history reconstruction, endpoint, arithmetic and fit checks."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
from scipy.stats import t

H=Path(__file__).resolve().parent;ROOT=H.parents[2];PRE=H.parent/'20261008_weight_speed_v2'
def sha(p):
    v=hashlib.sha256()
    with p.open('rb') as f:
        for z in iter(lambda:f.read(1048576),b''):v.update(z)
    return v.hexdigest()
def close(x,y,tol=1e-8):assert np.allclose(x,y,atol=tol,rtol=tol,equal_nan=True)
p=pd.read_csv(H/'pair_features.csv',dtype={'horse_id':str});ix=p.set_index('pair_id');src=pd.read_csv(PRE/'source_lineage.csv',dtype={'horse_id':str});src['relative']=src.time-src.groupby('race_id').time.transform('median');ss=src.set_index('api_record_id')
for key in ['horse_id','race_distance_m','year','rank_class_raw']:
    assert np.array_equal(ss.loc[p.pair_id,key].to_numpy(),ss.loc[p.previous_api_record_id,key].to_numpy())
close(p.body_change_kg,ss.loc[p.pair_id,'body_kg'].to_numpy()-ss.loc[p.previous_api_record_id,'body_kg'].to_numpy())
close(p.time_delta,ss.loc[p.pair_id,'time'].to_numpy()-ss.loc[p.previous_api_record_id,'time'].to_numpy())
close(p.relative_time_delta,ss.loc[p.pair_id,'relative'].to_numpy()-ss.loc[p.previous_api_record_id,'relative'].to_numpy())
records={r.pair_id:r for r in p.itertuples()};groups={}
for mode,keys in [('personal',['horse_id']),('same_distance',['horse_id','distance'])]:
    groups[mode]={key: g.sort_values(['race_date','pair_id']) for key,g in p.groupby(keys,sort=False)}
checked=0
for r in json.loads((H/'history_lineage.json').read_text()):
    current=records[r['pair_id']];key=(r['horse_id'],) if r['mode']=='personal' else (r['horse_id'],r['distance'])
    # Pandas single-list group keys are tuples in this installed version.
    g=groups[r['mode']].get(key)
    if g is None:g=groups[r['mode']][r['horse_id']]
    expected=g[g.race_date.le(r['cutoff'])].tail(10).pair_id.astype(int).tolist()
    assert expected==r['history_pair_ids'] and current.pair_id not in expected
    assert r['cutoff']==(pd.Timestamp(current.race_date)-pd.Timedelta(days=2)).strftime('%Y-%m-%d')
    vals=[abs(records[i].body_change_kg) for i in expected]
    close(getattr(current,r['mode']+'_mean'),np.mean(vals) if len(vals)>=5 else np.nan)
    close(getattr(current,r['mode']+'_sd'),np.std(vals,ddof=1) if len(vals)>=5 else np.nan)
    checked+=len(expected)
print('history checked',checked,flush=True)

def select(z,variant):
    z=z.copy();mode='same_distance' if variant=='same_distance_baseline' else 'personal';z=z[z[mode+'_mean'].notna()].copy();threshold=z[mode+'_mean']+(z[mode+'_sd'] if variant=='large_threshold' else 0);delta=z.body_change_kg
    z['selected_group']=np.where(delta.eq(0),'zero',np.where(delta.gt(0),np.where(delta.le(threshold),'gain_within','gain_above'),np.where(-delta<=threshold,'loss_within','loss_above')))
    z['baseline_mean']=z[mode+'_mean'];z['baseline_sd']=z[mode+'_sd'];z['baseline_n']=z[mode+'_n']
    if variant=='stable_conditions':z=z[z.month.eq(z.previous_month)&z.band.eq(z.previous_band)&z.burden_change.abs().le(1)]
    return z
periods=json.loads((H/'PLAN.json').read_text())['periods'];raw=pd.read_csv(H/'raw_direction_groups.csv');frames={}
for r in raw.itertuples():
    key=(r.period,r.variant)
    if key not in frames:
        lo,hi=periods[r.period];frames[key]=select(p[p.year.between(lo,hi)],r.variant)
    z=frames[key];g=z[z.distance.eq(r.distance)&z.selected_group.eq(r.group)];assert len(g)==r.rows
    close(g.body_change_kg.mean(),r.body_delta_mean_kg);close(g.time_delta.mean(),r.time_delta_mean_s)
    for outcome,col in [('raw','time_delta'),('relative','relative_time_delta')]:
        v=g[col];assert v.eq(0).sum()==getattr(r,outcome+'_exact_equal_count')
        for margin,label in [(.5,'half'),(1.,'one')]:
            for tag,mask in [('improved',v< -margin),('similar',v.abs()<=margin),('worsened',v>margin)]:
                assert mask.sum()==getattr(r,f'{outcome}_{label}_{tag}_count');close(mask.mean(),getattr(r,f'{outcome}_{label}_{tag}_rate'))

models=json.loads((H/'models.json').read_text());fitchecks=[]
for entry in models:
    if entry['variant']!='primary' or entry['period'] not in ['full','confirmation'] or entry['distance'] not in [1000,1110]:continue
    z=frames[(entry['period'],entry['variant'])];g=z[z.distance.eq(entry['distance'])];m=entry['model'];spec=m['design'];parts=[]
    for name in spec['nuisance_columns']:
        if name.endswith('_missing'):v=g[name[:-8]].isna().to_numpy(float)
        elif name.startswith('year_grade='):v=g.year_grade.eq(name.split('=',1)[1]).to_numpy(float)
        else:v=g[name].fillna(spec['nuisance_medians'][name]).to_numpy(float)
        parts.append(v)
    nx=(np.column_stack(parts)-spec['nuisance_means'])/spec['nuisance_sd'];names=['gain_within','gain_above','loss_within','loss_above'];x=np.column_stack([g.selected_group.eq(k).to_numpy(float) for k in names]+[np.ones(len(g)),nx]);y=g['time_delta' if m['target']=='raw_delta_s' else 'relative_time_delta'].to_numpy();penalty=np.ones(x.shape[1]);penalty[:5]=0;matrix=x.T@x+np.diag(penalty);beta=np.linalg.solve(matrix,x.T@y);close(beta,m['beta']);bread=np.linalg.solve(matrix,np.eye(len(beta)));res=y-x@beta;df=len(g)-np.linalg.matrix_rank(x,tol=1e-7);cov=np.zeros_like(bread)
    for col in ['race_date','horse_id']:
        codes,levels=pd.factorize(g[col]);score=np.zeros((len(levels),len(beta)));np.add.at(score,codes,x*res[:,None]);n=len(levels);cov+=bread@(score.T@score)@bread*n/(n-1)*(len(g)-1)/df
    close(cov,m['cov']);fitchecks.append({'period':entry['period'],'distance':entry['distance'],'target':m['target'],'max_beta_error':float(np.max(np.abs(beta-m['beta']))),'max_cov_error':float(np.max(np.abs(cov-m['cov'])))})
effects=pd.read_csv(H/'effects.csv')
lookup={(m['period'],m['variant'],m['distance'],m['model']['target']):m['model'] for m in models}
for r in effects.itertuples():
    m=lookup[(r.period,r.variant,r.distance,r.target)];v=np.zeros(len(m['columns']));sign=r.contrast.split('_',1)[0];v[m['columns'].index(sign+'_above')]=1
    if r.contrast.endswith('within'):v[m['columns'].index(sign+'_within')]=-1
    point=v@np.array(m['beta']);se=np.sqrt(v@np.array(m['cov'])@v);critical=t.ppf(.975,m['critical_df']);close([point,point-critical*se,point+critical*se],[r.effect,r.ci_lo,r.ci_hi]);assert r.mean_difference_within_half_second_supported==(r.ci_lo>-.5 and r.ci_hi<.5)
for _,g in effects.groupby(['period','variant','contrast']):
    pv=g.p.to_numpy();order=np.argsort(pv);q=np.minimum.accumulate((pv[order]*len(pv)/np.arange(1,len(pv)+1))[::-1])[::-1].clip(0,1);close(g.q_BH.to_numpy()[order],q)
for r in json.loads((H/'source_manifest.json').read_text()):assert sha(Path(r['path']))==r['sha256']
central=json.loads((H.parent/'conclusions/source_manifest.json').read_text())
for r in central['files']:assert sha(ROOT/r['path'])==r['sha256'],r['path']
assert sha(ROOT/'jeju/data/jeju_native_core.sqlite3')==json.loads((H/'input_audit.json').read_text())['database_sha256']
result={'status':'passed','endpoint_pairs_checked':len(p),'history_endpoints_checked':checked,'raw_group_rows_checked':len(raw),'all_effect_rows_CI_and_equivalence_flags_checked':len(effects),'independent_coefficient_covariance_checks':fitchecks,'BH_pools_both_outcomes_as_planned':True,'database_prior_source_and_central_hashes_unchanged':True,'operational_change':False}
with (H/'independent_verification.json').open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
print('passed',len(fitchecks),len(effects),flush=True)
