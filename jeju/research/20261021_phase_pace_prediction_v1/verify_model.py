"""Re-inference and alternative calculations, without fitting or changing outputs."""
import json
import numpy as np
import pandas as pd
import lightgbm as lgb
from common import *

def direct_subsets(p,q):
    # Direct products and scalar accumulation differ from the log/matrix implementation.
    n=len(p);weights=[];sets=[];sizes=[]
    for mask in range(1,1<<n):
        subset=[j for j in range(n) if mask&(1<<j)]
        weight=1.
        for j in range(n):weight*=p[j] if j in subset else 1-p[j]
        sets.append(subset);sizes.append(min(len(subset),3)-1);weights.append(weight)
    weights=np.asarray(weights);weights/=weights.sum()
    category=np.bincount(sizes,weights=weights,minlength=3)
    weights*=q[np.array(sizes)]/category[np.array(sizes)]
    marginal=np.zeros(n);solo=np.zeros(n);expected=0.
    for subset,w in zip(sets,weights):
        marginal[subset]+=w;expected+=w*len(subset)
        if len(subset)==1:solo[subset]+=w
    return marginal,solo,expected

def main():
    check_manifest(json.loads((OUT/'protected_model_paths.json').read_text()))
    sm=json.loads((OUT/'source_manifest.json').read_text());check_manifest(sm['files']);check_manifest([sm['selected_snapshot']])
    check_manifest(json.loads((OUT/'training_input_manifest_v2.json').read_text())['files'])
    a=pd.read_parquet(OUT/'features_and_targets.parquet');pr=pd.read_parquet(OUT/'predictions.parquet')
    cp=pd.read_parquet(OUT/'count_predictions.parquet');rf=pd.read_parquet(OUT/'race_features.parquet')
    joint=pd.read_parquet(OUT/'joint_early_predictions.parquet');audit=json.loads((OUT/'fit_audit.json').read_text())
    contract=json.loads((OUT/'feature_contract.json').read_text())
    maxerr=0.;models=0;cells=0
    for entry in audit:
        path=HERE/entry['path'];assert sha(path)==entry['model_sha256']
        booster=lgb.Booster(model_file=str(path));year=entry['year'];task=entry['task'];name=entry['model']
        source=rf if task=='count' else a;test=source[source.year.eq(year)]
        train=source[source.race_date.le(entry['cutoff'])&source['y_'+task].notna()]
        assert len(train)==entry['train_rows'] and train.race_date.max()==entry['train_last_date']
        assert train.race_date.max()<test.race_date.min() and entry['cutoff']==f'{year-1}-12-30'
        saved=cp[cp.year.eq(year)&cp.model.eq(name)] if task=='count' else pr[pr.year.eq(year)&pr.task.eq(task)&pr.model.eq(name)]
        key='race_id' if task=='count' else 'api_record_id'
        out=booster.predict(test[entry['columns']],num_threads=4)
        if task in EVENTS:out=np.column_stack([1-out,out])
        k=out.shape[1]
        expected=saved.set_index(key).loc[test[key],['p'+str(i) for i in range(k)]].to_numpy()
        keep=np.ones(len(test),bool) if task!='c3' else test.race_distance_m.ne(800).to_numpy()
        err=np.max(np.abs(out[keep]-expected[keep]));assert err<1e-12
        maxerr=max(maxerr,float(err));models+=1;cells+=int(out[keep].size)
    # Every runner is predicted even when its point label is missing.
    eligible=set(a.loc[a.year.ge(2024),'api_record_id'])
    for task in TASKS:
        for name in ['H','P','F']:
            g=pr[(pr.task==task)&(pr.model==name)]
            assert set(g.api_record_id)==eligible and g.api_record_id.is_unique
            k=3 if task in POINTS else 2;p=g[['p'+str(i) for i in range(k)]].to_numpy()
            assert np.isfinite(p).all() and (p>=0).all() and (p<=1).all() and np.allclose(p.sum(axis=1),1,atol=1e-12)
    baselinechecks=0
    for year in [2024,2025,2026]:
        for task in TASKS:
            tr=a[a.race_date.le(f'{year-1}-12-30')&a['y_'+task].notna()]
            ycol='y_'+task;k=3 if task in POINTS else 2
            prior=np.array([tr.assign(event=tr[ycol].eq(c)).groupby('race_id').event.mean().mean() for c in range(k)])
            g=pr[pr.year.eq(year)&pr.model.eq('H')&pr.task.eq(task)].copy()
            if task=='c3':g=g[g.race_distance_m.ne(800)]
            source=a.set_index('api_record_id').loc[g.api_record_id]
            if k==3:
                n=source['h10_'+task+'_0_n'].to_numpy();mean=source[['h10_'+task+'_'+str(c)+'_mean' for c in range(3)]].fillna(0).to_numpy()
                expected=(n[:,None]*mean+3*prior)/(n[:,None]+3)
            else:
                n=source['h10_'+task+'_n'].to_numpy();mean=source['h10_'+task+'_mean'].fillna(0).to_numpy()
                p=(n*mean+3*prior[1])/(n+3);expected=np.column_stack([1-p,p])
            assert np.allclose(expected,g[['p'+str(c) for c in range(k)]],atol=1e-12);baselinechecks+=len(g)
    for name in ['H','P','F']:
        x=pr[pr.model.eq(name)&pr.race_distance_m.eq(800)&pr.task.eq('s1f')].set_index('api_record_id')
        y=pr[pr.model.eq(name)&pr.race_distance_m.eq(800)&pr.task.eq('c3')].set_index('api_record_id')
        assert y.y.isna().all() and np.array_equal(x[['p0','p1','p2']],y.loc[x.index,['p0','p1','p2']])
    assert a.loc[a.race_distance_m.eq(800),'y_middle_advance'].isna().all()
    # Scalar front-fade event from source pack and normal finish, including missingness.
    normal=a.finish_position.between(1,89);known=a.y_s1f.notna()&normal
    assert a.y_front_fade.notna().equals(known)
    assert np.array_equal(a.loc[known,'y_front_fade'],(a.loc[known,'y_s1f'].eq(0)&(a.loc[known,'finish_position']-a.loc[known,'s1f_lo']).ge(3)).astype(float))
    # Check all saved aggregate metrics against a different probability scoring path.
    ms=pd.read_csv(OUT/'metrics.csv',dtype={'distance':str});metricchecks=0
    for r in ms.itertuples():
        g=pr[(pr.task==r.task)&(pr.model==r.model)&pr.y.notna()]
        if r.period in ['2024','2025','2026']:g=g[g.year.eq(int(r.period))]
        elif r.period=='2024_2025':g=g[g.year.le(2025)]
        if r.distance!='all':g=g[g.race_distance_m.eq(int(r.distance))]
        k=3 if r.task in POINTS else 2;p=g[['p'+str(i) for i in range(k)]].to_numpy();y=g.y.to_numpy(int)
        loss=np.sum(p*p,axis=1)-2*p[np.arange(len(y)),y]+1
        alt=pd.DataFrame({'race':g.race_id.to_numpy(),'loss':loss}).groupby('race').loss.mean().mean()
        assert abs(alt-r.brier)<1e-12 and len(g)==r.rows and g.race_id.nunique()==r.races
        metricchecks+=1
    # Separately enumerate every J race to validate coherent identities.
    maxjoint=0.;subsetraces=0
    for (race,name),g in joint.groupby(['race_id','model'],sort=False):
        assert abs(g.p_first.sum()-g.expected_leaders.iloc[0])<1e-10
        assert abs(g.p_solo.sum()-g.count_p1.iloc[0])<1e-10
        assert np.allclose(g[['count_p1','count_p2','count_p3plus']].sum(axis=1),1,atol=1e-12)
        if name!='J':continue
        early=pr[(pr.race_id==race)&pr.task.eq('s1f')&pr.model.eq('F')].set_index('api_record_id').loc[g.api_record_id]
        p=np.clip(early.p0.to_numpy(),1e-8,1-1e-8)
        q=cp[cp.race_id.eq(race)&cp.model.eq('F')][['p0','p1','p2']].iloc[0].to_numpy(float)
        marginal,solo,count=direct_subsets(p,q)
        err=max(np.max(np.abs(marginal-g.p_first)),np.max(np.abs(solo-g.p_solo)),abs(count-g.expected_leaders.iloc[0]))
        assert err<1e-10;maxjoint=max(maxjoint,float(err));subsetraces+=1
    # Perturb current/future postrace source values and independently re-aggregate selected current fields.
    trace=pd.read_parquet(OUT/'history_lineage.parquet').set_index('api_record_id');ix=a.set_index('api_record_id')
    examples=a[a.year.ge(2024)].sort_values(['race_date','race_number']).groupby('year').tail(24)
    perturbchecks=0
    for r in examples.itertuples():
        changed=a.api_record_id.eq(r.api_record_id)|a.race_date.gt(r.race_date)
        altered=a[['api_record_id','obs_s1f_0','obs_g1f_speedrank','obs_finish_rank']].copy()
        altered.loc[changed,['obs_s1f_0','obs_g1f_speedrank','obs_finish_rank']]=987654.
        altered=altered.set_index('api_record_id')
        for prefix in ['h5','h10','same10']:
            text=trace.loc[r.api_record_id,prefix+'_ids'];ids=[int(t) for t in text.split('|')] if text else []
            assert not set(ids)&set(a.loc[changed,'api_record_id'])
            for c in ['s1f_0','g1f_speedrank','finish_rank']:
                values=altered.loc[ids,'obs_'+c];expected=values.mean()
                actual=getattr(r,prefix+'_'+c+'_mean')
                assert (pd.isna(actual) and pd.isna(expected)) or abs(actual-expected)<1e-12
                perturbchecks+=1
    # Recompute main eight bootstrap intervals directly from stored per-race scores.
    scores=pd.read_parquet(OUT/'race_scores.parquet');contr=pd.read_csv(OUT/'paired_comparisons.csv')
    ci_checks=0
    for row in contr[contr.primary].itertuples():
        x=scores[(scores.task==row.task)&scores.model.eq('F')].set_index('race_id')
        ref=row.comparison.split('-')[1];y=scores[(scores.task==row.task)&scores.model.eq(ref)].set_index('race_id')
        delta=x.brier-y.brier;d=pd.DataFrame({'delta':delta,'date':x.race_date}).groupby('date').delta.agg(['sum','count'])
        rng=np.random.default_rng(20261021);boot=[]
        for _ in range(2000):
            chosen=rng.integers(0,len(d),size=len(d));v=d.iloc[chosen];boot.append(v['sum'].sum()/v['count'].sum())
        low,high=np.quantile(boot,[.025,.975])
        assert abs(delta.mean()-row.estimate)<1e-12 and abs(low-row.low)<1e-12 and abs(high-row.high)<1e-12;ci_checks+=1
    primary=contr[contr.primary].sort_values('p');pvals=primary.p.to_numpy();adjusted=[]
    for i in range(len(pvals)):adjusted.append(min(1.,min(pvals[j]*len(pvals)/(j+1) for j in range(i,len(pvals)))))
    assert np.allclose(adjusted,primary.bh_q_primary8,atol=1e-12)
    save(OUT/'verification.json',{'status':'passed','models_reinferred':models,'probability_cells_reinferred':cells,
        'max_reinference_error':maxerr,'historical_baseline_rows_reproduced':baselinechecks,'aggregate_metric_cells_checked':metricchecks,'joint_races_independently_enumerated':subsetraces,
        'max_joint_error':maxjoint,'current_future_mutation_cells_checked':perturbchecks,'primary_bootstrap_intervals_reproduced':ci_checks,
        'all_prediction_rosters_complete':True,'BH_primary8_independently_checked':True,'800m_alias_verified':True,'production_artifact_hashes_unchanged':True,
        'source_hashes_unchanged':True,'database_written':False,'network_used':False,'independent_future_validation':False})
    print('Independent model verification passed',models,'models',subsetraces,'joint races',flush=True)

if __name__=='__main__':main()
