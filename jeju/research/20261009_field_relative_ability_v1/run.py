"""Jeju field-relative ablation; immutable previous inputs, local outputs only."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PRE=HERE.parent/'20261008_horse_profile_baseline_v1'
spec=importlib.util.spec_from_file_location('jeju_profile_reference',PRE/'run.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
OUT=HERE/'outputs'
EXTRA=['opp_mean5_valid_n','opp_mean5_valid_fraction','opp_mean5_median_s',
       'mean5_minus_opp_mean_s','mean5_minus_opp_median_s','mean5_minus_opp_fast2mean_s',
       'opp_mean5_faster_n','mean5_rank_fraction']
CONTRACTS={'J0':old.BASE,'R1':old.BASE+EXTRA}
save=old.save;sha=old.sha;csv=old.write_csv


def relative(f):
    f=f.copy();rows=[]
    for _,idx in f.groupby('race_id',sort=False).indices.items():
        q=f.iloc[idx];x=q.mean5_s.to_numpy(float);ids=q.api_record_id.to_numpy(int)
        for i,pos in enumerate(idx):
            mask=np.arange(len(idx))!=i;known=x[mask];known=known[np.isfinite(known)]
            n=len(known);has=np.isfinite(x[i]) and n>0
            median=float(np.median(known)) if n else np.nan
            rows.append(dict(_row=pos,opp_mean5_valid_n=n,opp_mean5_valid_fraction=n/(len(idx)-1),
                opp_mean5_median_s=median,mean5_minus_opp_mean_s=x[i]-known.mean() if has else np.nan,
                mean5_minus_opp_median_s=x[i]-median if has else np.nan,
                mean5_minus_opp_fast2mean_s=x[i]-np.sort(known)[:2].mean() if has and n>=2 else np.nan,
                opp_mean5_faster_n=int((known<x[i]).sum()) if has else np.nan,
                mean5_rank_fraction=float(((known<x[i]).sum()+.5*(known==x[i]).sum())/n) if has else np.nan,
                opponent_source_row_ids=ids[mask].tolist()))
    added=pd.DataFrame(rows).sort_values('_row').reset_index(drop=True)
    assert added._row.tolist()==list(range(len(f)))
    return pd.concat([f.reset_index(drop=True),added.drop(columns='_row')],axis=1)


def prepare():
    OUT.mkdir(exist_ok=False)
    previous=json.loads((PRE/'outputs_v2/prepared_lock.json').read_text())
    assert sha(PRE/'run.py')==previous['references'][str((PRE/'run.py').relative_to(ROOT))]
    for name in ['features.parquet','source_snapshot.parquet','race_inclusion_ledger.csv']:
        assert sha(PRE/'outputs_v2'/name)==previous['artifacts'][name]
    assert json.loads((PRE/'outputs_v2/final_verification.json').read_text())['passed']
    protected=old.protect_paths()
    assert protected['jeju/data/jeju_native_core.sqlite3']['sha256']==previous['protected']['jeju/data/jeju_native_core.sqlite3']['sha256']
    f=relative(pd.read_parquet(PRE/'outputs_v2/features.parquet'))
    assert (len(f),f.race_id.nunique())==(52155,5206)
    assert f[f.year.ge(2024)].race_id.nunique()==1779
    assert len(f[f.year.ge(2024)])==17412
    assert f.groupby('race_id').field_n.first().eq(f.groupby('race_id').size()).all()
    assert not f.duplicated(['race_id','horse_id']).any()
    f.to_parquet(OUT/'features.parquet',index=False)
    csv(OUT/'feature_missingness.csv',pd.DataFrame([dict(feature=c,rows=len(f),missing=int(f[c].isna().sum()),missing_fraction=float(f[c].isna().mean())) for c in EXTRA]))
    csv(OUT/'support.csv',f.groupby(['year','distance_m']).agg(rows=('api_record_id','size'),races=('race_id','nunique'),days=('race_date','nunique'),no_history=('observed_starts',lambda x:int(x.eq(0).sum())),no_same_time=('same_valid_times',lambda x:int(x.eq(0).sum())),mean_opponent_available_fraction=('opp_mean5_valid_fraction','mean')).reset_index())
    save(OUT/'feature_contract.json',{v:dict(retained=old.BASE,added=EXTRA if v=='R1' else [],removed=[],inputs=cols) for v,cols in CONTRACTS.items()})
    # Every runner in two latest-date complete fields, chosen without performance filtering.
    example_races=f[f.race_date.eq('2026-09-19')&f.distance_m.isin([900,1000])].race_id.drop_duplicates().tolist()[:2]
    cols=['api_record_id','race_id','race_date','horse_id','horse_name','horse_number','distance_m','field_n','observed_starts','mean5_s','valid_n5','history_cutoff']+EXTRA+['opponent_source_row_ids']
    save(OUT/'example_fields.json',json.loads(f[f.race_id.isin(example_races)][cols].to_json(orient='records',force_ascii=False)))
    refs=[HERE/'run.py',HERE/'verify.py',HERE/'CONTRACT.md',PRE/'run.py',PRE/'outputs_v2/prepared_lock.json',
          PRE/'outputs_v2/features.parquet',PRE/'outputs_v2/source_snapshot.parquet',PRE/'outputs_v2/race_metrics.csv',
          PRE/'outputs_v2/runner_predictions.parquet',PRE/'outputs_v2/six_combinations.csv',PRE/'outputs_v2/final_verification.json',
          ROOT/'jeju/data/horse_exclusions.json',ROOT/'jeju/AGENTS.md']
    for y in [2024,2025,2026]:refs += [PRE/f'outputs_v2/J0_{y}/top3.txt',PRE/f'outputs_v2/J0_{y}/model_meta.json']
    old.check_protected(protected)
    save(OUT/'prepared_lock.json',dict(references={str(p.relative_to(ROOT)):sha(p) for p in refs},protected=protected,
        artifacts={p.name:sha(p) for p in OUT.iterdir() if p.is_file()},parameters=old.PARAMS,seed=old.SEED,
        versions={m.__name__:m.__version__ for m in [lgb,np,pd]},rows=len(f),races=f.race_id.nunique(),
        evaluation_rows=17412,evaluation_races=1779))
    print('Prepared',len(f),'rows',f.race_id.nunique(),'races; inputs 13 -> 21',flush=True)


def check():
    lock=json.loads((OUT/'prepared_lock.json').read_text())
    for p,h in lock['references'].items():assert sha(ROOT/p)==h,p
    for p,h in lock['artifacts'].items():assert sha(OUT/p)==h,p
    old.check_protected(lock['protected'])
    return lock


def fit(f,v,y):
    cols=CONTRACTS[v];x=f[cols].copy();vocab={}
    train=f.year.between(2017,y-3);valid=f.year.eq(y-2);cal=f.year.eq(y-1);test=f.year.eq(y)
    for c in old.CATS:
        vocab[c]=sorted(f.loc[train,c].dropna().unique().tolist());x[c]=pd.Categorical(x[c],categories=vocab[c])
    target=f.finish_position.le(3).astype(int);weight=1/f.field_n
    def ds(mask):return lgb.Dataset(x[mask],label=target[mask],weight=weight[mask],free_raw_data=False)
    init=lgb.train(old.PARAMS,ds(train),num_boost_round=200,valid_sets=[ds(valid)],callbacks=[lgb.early_stopping(25,verbose=False)])
    model=lgb.train(old.PARAMS,ds(train|valid),num_boost_round=init.best_iteration)
    path=OUT/f'{v}_{y}';path.mkdir(exist_ok=False);model.save_model(str(path/'top3.txt'))
    cz=model.predict(x[cal],raw_score=True,num_threads=4);tz=model.predict(x[test],raw_score=True,num_threads=4)
    tau=old.temperature(f[cal].reset_index(drop=True),cz)
    meta=dict(variant=v,evaluation_year=y,features=cols,vocabulary=vocab,trees=int(init.best_iteration),tau=tau,
         train_min=f.loc[train,'race_date'].min(),initial_train_max=f.loc[train,'race_date'].max(),
         early_stopping_min=f.loc[valid,'race_date'].min(),refit_max=f.loc[valid,'race_date'].max(),
         calibration_min=f.loc[cal,'race_date'].min(),calibration_max=f.loc[cal,'race_date'].max(),
         evaluation_min=f.loc[test,'race_date'].min(),evaluation_max=f.loc[test,'race_date'].max(),
         model_sha256=sha(path/'top3.txt'),gain=dict(zip(cols,map(float,model.feature_importance(importance_type='gain')))))
    save(path/'meta.json',meta)
    pd.DataFrame(dict(api_record_id=f.loc[cal,'api_record_id'].to_numpy(),score=cz)).to_parquet(path/'calibration_scores.parquet',index=False)
    result=old.evaluate(f[test].reset_index(drop=True),tz,tau,v)
    if v=='J0':
        earlier=pd.read_parquet(PRE/'outputs_v2/runner_predictions.parquet')
        earlier=earlier[earlier.variant.eq('J0')&earlier.year.eq(y)]
        assert np.array_equal(earlier.api_record_id,result[1].api_record_id)
        for c in ['score','p_top3','log_loss','brier']:assert np.allclose(earlier[c],result[1][c],atol=1e-12,rtol=0),c
    print(v,y,'trees',init.best_iteration,'tau',round(tau,5),flush=True)
    return result


def runner_ci(a,b,col):
    q=a[['api_record_id','race_date',col]].merge(b[['api_record_id',col]],on='api_record_id',validate='one_to_one',suffixes=('','_base'))
    assert len(q)==len(a)==len(b)
    q['delta']=q[col]-q[col+'_base'];g=q.groupby('race_date').delta.agg(['sum','size'])
    rng=np.random.default_rng(old.SEED);idx=rng.integers(0,len(g),size=(2000,len(g)))
    boot=g['sum'].to_numpy()[idx].sum(axis=1)/g['size'].to_numpy()[idx].sum(axis=1)
    return dict(delta=float(q.delta.mean()),lo=float(np.quantile(boot,.025)),hi=float(np.quantile(boot,.975)),rows=len(q),days=len(g))


def summarize(r,p):
    groups=[('all','all',r)]+[('year',str(k),g) for k,g in r.groupby('year')]+[('distance',str(k),g) for k,g in r.groupby('distance_m')]+[('grade',str(k),g) for k,g in r.groupby('grade_raw',dropna=False)]
    for c in ['any_no_history','any_low_history','any_no_same_time']:groups += [(c,str(k),g) for k,g in r.groupby(c)]
    metrics=[];comparisons=[]
    for kind,key,g in groups:
        for v,one in g.groupby('variant'):
            metrics.append(dict(group=kind,value=key,variant=v,races=len(one),days=one.race_date.nunique(),**{c:float(one[c].mean()) for c in old.METRICS}))
        for c in old.METRICS:
            comparisons.append(dict(group=kind,value=key,comparison='R1-J0',metric=c,**old.bootstrap(g[g.variant.eq('R1')],g[g.variant.eq('J0')],c)))
    csv(OUT/'metrics_by_group.csv',pd.DataFrame(metrics));csv(OUT/'paired_differences.csv',pd.DataFrame(comparisons))
    runnergroups=[('all','all',p)]
    for c in ['observed_starts','same_valid_times']:
        runnergroups += [(c,str(k),g) for k,g in p.groupby(pd.cut(p[c],[-1,0,4,np.inf],labels=['0','1_4','5_plus']),observed=True)]
    rr=[];rc=[]
    for kind,key,g in runnergroups:
        for v,one in g.groupby('variant'):
            rr.append(dict(group=kind,value=key,variant=v,rows=len(one),races=one.race_id.nunique(),log_loss=float(one.log_loss.mean()),brier=float(one.brier.mean()),predicted=float(one.p_top3.mean()),actual=float(one.y.mean())))
        for c in ['log_loss','brier']:
            rc.append(dict(group=kind,value=key,metric=c,**runner_ci(g[g.variant.eq('R1')],g[g.variant.eq('J0')],c)))
    csv(OUT/'runner_metrics.csv',pd.DataFrame(rr));csv(OUT/'runner_paired_differences.csv',pd.DataFrame(rc))
    calibration=[]
    for v,g in p.groupby('variant'):
        for key,one in g.groupby(pd.cut(g.p_top3,np.arange(0,1.0001,.1),include_lowest=True),observed=True):
            w=1/one.field_n;calibration.append(dict(variant=v,bin=str(key),rows=len(one),races=one.race_id.nunique(),predicted=float(np.average(one.p_top3,weights=w)),actual=float(np.average(one.y,weights=w))))
    csv(OUT/'calibration_bins.csv',pd.DataFrame(calibration))


def train():
    lock=check();assert json.loads((OUT/'preflight_verification.json').read_text())['passed']
    f=pd.read_parquet(OUT/'features.parquet');results=[]
    for y in [2024,2025,2026]:
        for v in CONTRACTS:results.append(fit(f,v,y))
    r=pd.concat([x[0] for x in results],ignore_index=True);p=pd.concat([x[1] for x in results],ignore_index=True);t=pd.concat([x[2] for x in results],ignore_index=True)
    csv(OUT/'race_metrics.csv',r);p.to_parquet(OUT/'runner_predictions.parquet',index=False);csv(OUT/'six_combinations.csv',t)
    summarize(r,p);old.check_protected(lock['protected'])
    save(OUT/'training_completion.json',dict(models=6,old_J0_reproduced_all_17412_rows=True,production_changed=False,database_changed=False,
       outputs={p.name:sha(p) for p in [OUT/'race_metrics.csv',OUT/'runner_predictions.parquet',OUT/'six_combinations.csv']}))
    print(r.groupby('variant')[old.METRICS].mean().to_string(),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepare','train']);a=p.parse_args()
    (prepare if a.phase=='prepare' else train)()
