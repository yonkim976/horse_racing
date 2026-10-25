"""Independent selectors, numerical histories, saved models, and error destinations."""
from datetime import date,timedelta
from bisect import bisect_left,bisect_right
import json
import numpy as np
import pandas as pd
from features import HERE,ROOT,PREV,PACK,source_observations,make_history,add_context,sha,save


def main():
    out=HERE/'verification01';out.mkdir(exist_ok=False)
    a=pd.read_csv(HERE/'features01/features_and_targets.csv',dtype={'horse_id':str},low_memory=False).set_index('api_record_id',drop=False)
    source=pd.read_csv(PREV/'run01/runner_types_and_evidence.csv',dtype={'horse_id':str},low_memory=False)
    points=pd.read_csv(PACK/'run01/race_point_audit.csv',low_memory=False)
    raw,obs=source_observations(source.copy(),points)
    trace=pd.read_csv(HERE/'features01/history_lineage.csv',dtype=str,keep_default_na=False)
    histories={}
    for horse,g in raw.groupby('horse_id'):
        g=g.sort_values(['race_date','race_number','api_record_id'])
        histories[horse]=(g.race_date.tolist(),g.api_record_id.to_numpy(),g.race_distance_m.to_numpy(),g[['obs_'+c for c in obs]].to_numpy(dtype=float))
    selectors=0;numeric=0
    firstidx=obs.index('s1f_first');timeidx=obs.index('s1ftime')
    for r in trace.itertuples():
        days,ids,dist,values=histories[r.horse_id]
        cut=(date.fromisoformat(r.race_date)-timedelta(days=2)).isoformat();lo=(date.fromisoformat(r.race_date)-timedelta(days=730)).isoformat()
        assert cut==r.history_cutoff
        start,end=bisect_left(days,lo),bisect_right(days,cut);ix=np.arange(start,end)
        target=a.loc[int(r.api_record_id)]
        for scope,use in [('any',ix[-10:]),('same',ix[dist[ix]==int(r.race_distance_m)][-10:])]:
            assert '|'.join(map(str,ids[use]))==getattr(r,scope+'_ids')
            assert not len(use) or (days[use[-1]]<=cut and int(r.api_record_id) not in ids[use])
            assert target['h_'+scope+'_n']==len(use)
            data=values[use];count=np.isfinite(data).sum(axis=0)
            means=np.divide(np.nansum(data,axis=0),count,out=np.full(len(obs),np.nan),where=count>0)
            cols=['h_'+scope+'_'+c+'_mean' for c in obs]
            assert np.allclose(means,target[cols].to_numpy(dtype=float),equal_nan=True,atol=1e-10)
            assert target['h_'+scope+'_s1f_n']==count[firstidx] and target['h_'+scope+'_s1ftime_n']==count[timeidx]
            for c in ['s1f_first','s1ftime','finish_rank']:
                expected=data[-1,obs.index(c)] if len(data) else np.nan
                assert np.isclose(expected,target['h_'+scope+'_'+c+'_last'],equal_nan=True,atol=1e-10)
            selectors+=1;numeric+=len(obs)+6
    print('History selectors and means verified',selectors,numeric,flush=True)
    contextchecks=0
    for _,g in a.groupby('race_id'):
        g=g.sort_values('horse_number');lead=g.h_prior_lead_smoothed.to_numpy();n=len(g)
        assert n==g.field_n.iloc[0]
        assert np.allclose(lead.sum()-lead,g.opp_lead_sum)
        assert np.allclose(np.cumsum(lead)-lead,g.opp_inner_lead_sum)
        assert np.allclose(lead.sum()-np.cumsum(lead),g.opp_outer_lead_sum)
        expected=np.max(np.where(np.eye(n,dtype=bool),-np.inf,np.broadcast_to(lead,(n,n))),axis=1)
        assert np.allclose(expected,g.opp_lead_max)
        contextchecks+=4*n
    mx=a.groupby('race_id').horse_number.transform('max')
    inner=(3*(a.horse_number-1)<mx-1).astype(float);outer=(3*(a.horse_number-1)>2*(mx-1)).astype(float)
    assert np.array_equal(inner,a.band_inner) and np.array_equal(outer,a.band_outer)
    exact=a[a.exact10];assert np.array_equal(exact.band_inner,exact.horse_number.le(3)) and np.array_equal(exact.band_outer,exact.horse_number.ge(8))
    non1300=source[source.race_distance_m.ne(1300)].set_index('api_record_id')
    old=non1300.early_position.map({'lead':0.,'front':1.,'middle':2.,'rear':3.})
    assert np.allclose(old,a.loc[old.index,'y_s1f_position4'],equal_nan=True)
    assert a[a.race_distance_m.eq(1300)].y_s1f_pack3.notna().sum()==606
    # Perturb all current postrace observables in four complete latest races.
    selected=[]
    for distance in [800,900,1300,1400]:
        z=a[a.year.eq(2026)&a.race_distance_m.eq(distance)].sort_values(['race_date','race_number'])
        selected.append(z.iloc[-1].race_id)
    ids=set(a[a.race_id.isin(selected)].api_record_id);horses=set(a[a.api_record_id.isin(ids)].horse_id)
    subset=raw[raw.horse_id.isin(horses)].copy();changed=subset.copy()
    changed.loc[changed.api_record_id.isin(ids),['obs_'+c for c in obs]]=17.
    h0,_=make_history(subset,obs);h1,_=make_history(changed,obs)
    c0=add_context(h0[h0.api_record_id.isin(ids)].copy()).set_index('api_record_id')
    c1=add_context(h1[h1.api_record_id.isin(ids)].copy()).set_index('api_record_id')
    groups=json.loads((HERE/'features01/feature_columns.json').read_text())
    ordinary=sum([v for k,v in groups.items() if k!='bands'],[])
    assert np.allclose(c0[ordinary].sort_index(),c1[ordinary].sort_index(),equal_nan=True,atol=1e-12)
    assert np.allclose(c0[ordinary].sort_index(),a.loc[sorted(ids),ordinary],equal_nan=True,atol=1e-10)
    for band,b in [('inner',inner),('outer',outer)]:
        for d in [800,900,1000,1110,1200,1300,1400,1610]:
            assert np.allclose(a[f'band_{band}_distance_{d}'],b*a[f'base_distance_{d}'])
        for name,col in [('lead','h_prior_lead_smoothed'),('speed','h_any_s1ftime_mean')]:
            assert np.allclose(a[f'band_{band}_x_prior_{name}'],b*a[col],equal_nan=True)
    pr=pd.read_csv(HERE/'run01/predictions.csv',dtype={'horse_id':str});fits=json.loads((HERE/'run01/fit_audit.json').read_text())
    fitdict={(r['year'],r['task'],r['model']):r for r in fits};params=json.loads((HERE/'run01/model_parameters.json').read_text())
    maxerror=0.;predictions=0
    for r in params:
        fit=fitdict[(r['year'],r['task'],r['model'])];cols=fit['input_columns']
        assert fit['train_last_date']<=fit['cutoff']<str(r['year'])+'-01-01'
        assert all(c.startswith(('base_','h_','gate_','opp_','band_')) and c!='gate_band' for c in cols)
        z=pr[pr.year.eq(r['year'])&pr.task.eq(r['task'])&pr.model.eq(r['model'])]
        x=a.loc[z.api_record_id,cols].to_numpy(dtype=float,copy=True);missing=np.isnan(x)
        x=np.where(missing,np.array(r['impute_statistics']),x)
        if r['indicator_columns']:x=np.column_stack([x,missing[:,r['indicator_columns']]])
        x=(x-np.array(r['scale_mean']))/np.array(r['scale_scale'])
        logits=x@np.array(r['coef']).T+np.array(r['intercept']);logits-=logits.max(axis=1,keepdims=True)
        p=np.exp(logits);p/=p.sum(axis=1,keepdims=True)
        saved=z[['p'+str(j) for j in range(p.shape[1])]].to_numpy()
        error=float(np.abs(p-saved).max());maxerror=max(maxerror,error);assert error<1e-10
        assert np.isfinite(p).all() and (p>0).all() and np.allclose(p.sum(axis=1),1)
        predictions+=len(z)
    # Independently recover every highest-probability candidate and miss category.
    top=pd.read_csv(HERE/'run01/top_first_pack.csv',dtype={'selected_horse_id':str}).set_index(['model','race_id'])
    selectionchecks=0
    for key,g in pr[pr.task.eq('s1f_pack3')].groupby(['model','race_id']):
        ranked=sorted(g.itertuples(),key=lambda r:(-r.p0,r.horse_id));best=ranked[0];r=top.loc[key]
        assert best.horse_id==r.selected_horse_id
        assert np.isclose(best.y,r.actual_pack3,equal_nan=True) and np.isclose(best.y_s1f_position4,r.actual_position4,equal_nan=True)
        selectionchecks+=1
    race=pd.read_csv(HERE/'run01/race_metrics.csv');metricchecks=0
    for (task,model),g in pr[pr.y.notna()].groupby(['task','model']):
        y=g.y.to_numpy(dtype=int);p=g[['p'+str(j) for j in range(int(g.y.max())+1)]].to_numpy()
        z=g[['race_id']].copy();z['loss']=-np.log(np.maximum(p[np.arange(len(y)),y],1e-15))
        expected=z.groupby('race_id').loss.mean();stored=race[(race.task==task)&(race.model==model)].set_index('race_id').logloss
        assert np.allclose(expected.sort_index(),stored.sort_index(),atol=1e-12);metricchecks+=len(expected)
    for path in [HERE/'features01/source_manifest.json',HERE/'run01/input_manifest.json']:
        for r in json.loads(path.read_text())['files']:assert sha(ROOT/r['path'])==r['sha256']
    save(out/'verification.json',{'status':'passed','history_windows_reselected':selectors,'historical_numeric_checks':numeric,
        'self_excluded_context_checks':contextchecks,'1300_S1F_included':606,'exact10_band_definition_verified':True,
        'current_postrace_perturbation_races':selected,'perturbation_runners':len(ids),'current_inputs_and_predictions_invariant':True,
        'predictions_reproduced_from_plain_parameters':predictions,'max_probability_error':maxerror,
        'highest_probability_candidates_independently_reproduced':selectionchecks,'race_logloss_checks':metricchecks,
        'input_hashes_preserved':True,'code_sha256':sha(HERE/'verify.py')})
    print('Independent verification passed',flush=True)


if __name__=='__main__':main()
