"""Exploratory control: preserve four non-identical legacy finish inputs."""
import argparse
import json
import itertools
import numpy as np
import pandas as pd
import lightgbm as lgb
import run as e

COLS=e.BASE+e.GAPS+e.KEEP+e.INTER


def freeze():
    paths=[e.HERE/'SENSITIVITY_PLAN.md',e.HERE/'sensitivity.py',e.OUT/'features.parquet']
    m={str(p.relative_to(e.ROOT)):e.sha(p) for p in paths}
    p=e.OUT/'sensitivity_input_manifest.json'
    if p.exists():assert json.loads(p.read_text())==m
    else:e.save(p,m)
    assert len(COLS)==len(set(COLS))==126
    e.save(e.OUT/'sensitivity_feature_contract.json',dict(additive126=COLS,exploratory_after_primary_preview=True))


def train():
    f=pd.read_parquet(e.OUT/'features.parquet')
    for meet in [1,3]:
        one=f[f.meet==meet].reset_index(drop=True)
        for year in [2024,2025,2026]:
            folder=e.OUT/'sensitivity_models'/f'additive126_{meet}_{year}';folder.mkdir(parents=True,exist_ok=True)
            r,p=e.S.fit(one,COLS,year,3,'additive126',folder)
            r.to_csv(folder/'races.csv',index=False);p.to_parquet(folder/'runners.parquet',index=False)
            print('Sensitivity',meet,year,flush=True)
    e.check()


def analyse():
    folders=sorted((e.OUT/'sensitivity_models').iterdir())
    p=pd.concat([pd.read_parquet(x/'runners.parquet') for x in folders],ignore_index=True)
    r=pd.concat([pd.read_csv(x/'races.csv') for x in folders],ignore_index=True)
    r=e.T.add_coverage(r,p);trio=[]
    for rid,g in p.groupby('race_key'):
        g=g.sort_values('program_no');sets,_=e.S.support(len(g),3)
        score=g.raw_score.to_numpy()[sets].sum(axis=1);best=np.argsort(-score,kind='stable')[:6]
        truth=tuple(np.flatnonzero(g.outcome.between(1,3)))
        trio.append(dict(race_key=rid,trio6=int(any(tuple(sets[j])==truth for j in best))))
    r=r.merge(pd.DataFrame(trio),on='race_key',validate='one_to_one')
    r.to_csv(e.OUT/'sensitivity_race_diagnostics.csv',index=False)
    old=pd.read_csv(e.OUT/'race_diagnostics.csv');rows=[];diff=[]
    for period,z in [('all',r)]+[(str(y),r[r.year==y]) for y in [2024,2025,2026]]:
        rows.append(dict(variant='additive126',period=period,n=len(z),**{m:float(z[m].mean()) for m in e.METRICS}))
        for ref in ['baseline103','combined122']:
            b=old[old.variant==ref]
            if period!='all':b=b[b.year==int(period)]
            diff.extend(e.N.differences(z,b,'additive126',ref,period))
    pd.DataFrame(rows).to_csv(e.OUT/'sensitivity_metrics.csv',index=False)
    pd.DataFrame(diff).to_csv(e.OUT/'sensitivity_differences.csv',index=False)
    print(pd.DataFrame(rows).to_string(index=False),flush=True)


def verify():
    f=pd.read_parquet(e.OUT/'features.parquet');diagnostics=pd.read_csv(e.OUT/'sensitivity_race_diagnostics.csv').set_index('race_key')
    count=0;maxerror=0.;metrics=0
    for folder in sorted((e.OUT/'sensitivity_models').iterdir()):
        m=json.loads((folder/'metadata.json').read_text());p=pd.read_parquet(folder/'runners.parquet')
        assert m['features']==COLS and e.sha(folder/'model.txt')==m['model_sha256']
        assert m['train_end']<f"{m['calibration_year']}-01-01"
        one=f[f.meet==p.meet.iloc[0]].reset_index(drop=True)
        train=one.year.between(2017,m['evaluation_year']-3);test=one.year==m['evaluation_year']
        x,vocab=e.S.encode(one,COLS,train);assert vocab==m['category_vocabulary']
        model=lgb.Booster(model_file=str(folder/'model.txt'))
        z=one[test][e.S.KEY].copy();z['score']=model.predict(x[test],raw_score=True,num_threads=4)
        joined=z.merge(p,on=e.S.KEY,validate='one_to_one');err=float(np.max(np.abs(joined.score-joined.raw_score)))
        assert err<=1e-12;maxerror=max(maxerror,err)
        r,_=e.S.evaluate(one[test].reset_index(drop=True),z.score.to_numpy(),m['temperature'],3,'additive126')
        r=r.set_index('race_key')
        for metric in ['axis_top3','axis_top2','quinella_one','axis_next3','target_brier','set_logloss']:
            np.testing.assert_allclose(r[metric],diagnostics.reindex(r.index)[metric],atol=1e-12,rtol=0)
        metrics+=len(r);count+=1
    assert count==6 and len(diagnostics)==4799
    e.save(e.OUT/'sensitivity_verification.json',dict(passed=True,ability_models_replayed=count,max_score_error=maxerror,
          race_metrics_checked=metrics,exploratory_after_primary_preview=True,primary_contract_unchanged=True))
    e.check();print('Sensitivity verified',count,'models')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['train','analyse','verify']);args=parser.parse_args()
    freeze();dict(train=train,analyse=analyse,verify=verify)[args.stage]()
