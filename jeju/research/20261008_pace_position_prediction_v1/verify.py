"""Independent lineage, context, prediction, and metric checks."""
from datetime import date,timedelta
import numpy as np
import pandas as pd
from features import HERE,ROOT,PREV,PACK,sha,save,source_observations,make_history,add_context
import json


def main():
    out=HERE/'verification01';out.mkdir(exist_ok=False)
    a=pd.read_csv(HERE/'features01/features_and_targets.csv',dtype={'horse_id':str},low_memory=False)
    trace=pd.read_csv(HERE/'features01/history_lineage.csv',dtype=str,keep_default_na=False)
    a=a.set_index('api_record_id',drop=False)
    groups=json.loads((HERE/'features01/feature_columns.json').read_text())
    source=pd.read_csv(PREV/'run01/runner_types_and_evidence.csv',dtype={'horse_id':str},low_memory=False)
    byhorse={k:g.sort_values(['race_date','race_number','api_record_id']) for k,g in source.groupby('horse_id')}
    checks=0
    for r in trace.itertuples():
        cut=(date.fromisoformat(r.race_date)-timedelta(days=2)).isoformat()
        lo=(date.fromisoformat(r.race_date)-timedelta(days=730)).isoformat()
        assert r.history_cutoff==cut
        g=byhorse[r.horse_id];g=g[g.race_date.between(lo,cut)]
        for scope in ['any','same']:
            v=g if scope=='any' else g[g.race_distance_m.eq(int(r.race_distance_m))]
            ids='|'.join(v.tail(10).api_record_id.astype(str))
            assert ids==getattr(r,scope+'_ids')
            assert len(v.tail(10))==a.loc[int(r.api_record_id),'h_'+scope+'_n']
            checks+=1
    print('Independent history selectors verified',checks,flush=True)
    # Pairwise context independently sums only other participants.
    contextchecks=0
    for _,g in a.groupby('race_id'):
        assert len(g)==g.field_n.iloc[0]
        lead=g.h_prior_lead_smoothed.to_numpy();gate=g.horse_number.to_numpy()
        for i,r in enumerate(g.itertuples()):
            assert np.isclose(r.opp_lead_sum,sum(lead[j] for j in range(len(g)) if j!=i))
            assert np.isclose(r.opp_lead_max,max(lead[j] for j in range(len(g)) if j!=i))
            assert np.isclose(r.opp_inner_lead_sum,sum(lead[j] for j in range(len(g)) if gate[j]<gate[i]))
            assert np.isclose(r.opp_outer_lead_sum,sum(lead[j] for j in range(len(g)) if gate[j]>gate[i]))
            contextchecks+=4
    # Recompute past aggregation after perturbing all current postrace observables
    # for every horse in a complete latest evaluation race. Current inputs must match.
    points=pd.read_csv(PACK/'run01/race_point_audit.csv',low_memory=False)
    raw,obs=source_observations(source.copy(),points)
    ev=a[a.year.eq(2026)&a.race_distance_m.eq(1000)]
    race=ev.sort_values(['race_date','race_number']).iloc[-1].race_id
    ids=set(ev[ev.race_id.eq(race)].api_record_id)
    horses=set(ev[ev.race_id.eq(race)].horse_id)
    v=raw[raw.horse_id.isin(horses)].copy()
    changed=v.copy();changed.loc[changed.api_record_id.isin(ids),['obs_'+x for x in obs]]=17.
    h0,_=make_history(v,obs);h1,_=make_history(changed,obs)
    c0=add_context(h0[h0.api_record_id.isin(ids)].copy()).set_index('api_record_id')
    c1=add_context(h1[h1.api_record_id.isin(ids)].copy()).set_index('api_record_id')
    cols=sum(groups.values(),[])
    assert np.allclose(c0[cols],c1[cols],equal_nan=True,atol=1e-12)
    assert np.allclose(c0[cols].sort_index(),a.loc[sorted(ids),cols],equal_nan=True,atol=1e-10)
    # Reproduce fitted transforms and all predictions from saved plain parameters.
    pr=pd.read_csv(HERE/'run02/predictions.csv',dtype={'horse_id':str})
    params=json.loads((HERE/'run02/model_parameters.json').read_text())
    fits=json.loads((HERE/'run02/fit_audit.json').read_text())
    fitted={(r['year'],r['task'],r['model']):r for r in fits}
    maxerr=0.;predchecks=0
    for r in params:
        key=(r['year'],r['task'],r['model']);fit=fitted[key]
        assert fit['train_last_date']<=fit['cutoff']<f"{r['year']}-01-01"
        cols=fit['input_columns'];assert all(c.startswith(('base_','h_','gate_','opp_')) for c in cols)
        z=pr[pr.year.eq(r['year'])&pr.task.eq(r['task'])&pr.model.eq(r['model'])]
        x=a.loc[z.api_record_id,cols].to_numpy(dtype=float,copy=True)
        miss=np.isnan(x);stats=np.array(r['impute_statistics']);x=np.where(miss,stats,x)
        if r['indicator_columns']:x=np.column_stack([x,miss[:,r['indicator_columns']]])
        x=(x-np.array(r['scale_mean']))/np.array(r['scale_scale'])
        logits=x@np.array(r['coef']).T+np.array(r['intercept'])
        if logits.shape[1]==1:
            p=1/(1+np.exp(-logits[:,0]));p=np.column_stack([1-p,p])
        else:
            logits-=logits.max(axis=1,keepdims=True);p=np.exp(logits);p/=p.sum(axis=1,keepdims=True)
        saved=z[['p'+str(j) for j in range(p.shape[1])]].to_numpy()
        err=np.max(np.abs(p-saved));maxerr=max(maxerr,float(err));assert err<1e-10
        assert np.isfinite(p).all() and (p>0).all() and np.allclose(p.sum(axis=1),1)
        predchecks+=len(z)
        # The perturbed race produces identical predictions as inputs are identical.
    rs=pd.read_csv(HERE/'run02/race_metrics.csv')
    metricchecks=0
    for (task,model),g in pr[pr.y.notna()].groupby(['task','model']):
        y=g.y.to_numpy(dtype=int);p=g[['p'+str(j) for j in range(int(g.y.max())+1)]].to_numpy()
        g=g.copy();g['loss']=-np.log(p[np.arange(len(y)),y])
        calculated=g.groupby('race_id').loss.mean()
        stored=rs[rs.task.eq(task)&rs.model.eq(model)].set_index('race_id').logloss
        assert np.allclose(calculated.sort_index(),stored.sort_index(),atol=1e-12)
        metricchecks+=len(calculated)
    manifests=[HERE/'features01/source_manifest.json',HERE/'run02/input_manifest.json']
    for manifest in manifests:
        for r in json.loads(manifest.read_text())['files']:assert sha(ROOT/r['path'])==r['sha256']
    save(out/'verification.json',{'status':'passed','history_windows_independently_reconstructed':checks,
        'self_excluded_context_sum_checks':contextchecks,'current_postrace_perturbation_complete_race':race,
        'perturbation_runners':len(ids),'current_features_and_predictions_invariant':True,
        'predictions_reproduced_from_parameters':predchecks,'max_probability_error':maxerr,
        'race_logloss_metrics_independently_reproduced':metricchecks,'all_input_hashes_preserved':True,
        'code_sha256':sha(HERE/'verify.py')})
    print('Verification passed',flush=True)


if __name__=='__main__':main()
