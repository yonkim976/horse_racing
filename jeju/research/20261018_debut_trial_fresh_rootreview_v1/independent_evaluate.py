"""Review frozen models and fresh-period paired losses; no training or tuning."""
from itertools import combinations
from pathlib import Path
import importlib.util
import json
import numpy as np
import pandas as pd
from independent_build import ROOT,HERE,sha,dump_new

def module(path):
    spec=importlib.util.spec_from_file_location('root_pure_saved_model_replay',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def interval(paired):
    dates=sorted(paired.race_date.unique())
    grouped=paired.groupby('race_date').delta.agg(['sum','size']).loc[dates]
    schedule=np.random.default_rng(20261018).integers(0,len(dates),size=(20000,len(dates)))
    draws=grouped['sum'].to_numpy()[schedule].sum(axis=1)/grouped['size'].to_numpy()[schedule].sum(axis=1)
    return dict(delta=float(paired.delta.mean()),low=float(np.quantile(draws,.025)),high=float(np.quantile(draws,.975)),
                date_n=len(dates),race_n=len(paired),few_day_exploratory=len(dates)<5),draws

def main():
    release=json.loads((HERE/'ROOT_RELEASE.json').read_text())
    assert release['source_and_features_approved'] is True
    feature_path=(ROOT/release['feature_path']).resolve();assert feature_path.is_relative_to(ROOT/'jeju/research')
    assert sha(feature_path)==release['feature_sha256']
    f=pd.read_parquet(feature_path)
    assert f.race_date.gt('2026-09-19').all() and f.race_date.le('2026-10-17').all()
    helper=module(ROOT/'jeju/research/20261017_1000m_five_section_rootreview_v1/independent.py')
    models=[('baseline',ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026'),
            ('candidate',ROOT/'jeju/research/20261018_debut_trial_ablation_v1/outputs/F1_STYLE6_DEBUT_TRIAL4_2026')]
    rr=[];uu=[];tt=[]
    for label,folder in models:
        for name in ('top3.txt','meta.json'):assert sha(folder/name)==release['models'][str((folder/name).relative_to(ROOT))]
        score,meta=helper.replay(f,folder)
        r,u,t=helper.evaluate(f,score,meta['tau'],label)
        u=u.merge(f[['api_record_id','race_date','observed_starts','finish_position','horse_number']],on='api_record_id',validate='one_to_one')
        rr.append(r);uu.append(u);tt.append(t)
    races=pd.concat(rr,ignore_index=True);runners=pd.concat(uu,ignore_index=True);tickets=pd.concat(tt,ignore_index=True)
    races.to_parquet(HERE/'ROOT_FRESH_RACE_METRICS.parquet',index=False)
    runners.to_parquet(HERE/'ROOT_FRESH_RUNNERS.parquet',index=False)
    tickets.to_parquet(HERE/'ROOT_FRESH_TICKETS.parquet',index=False)
    scopes=[];cis=[];drawrows=[]
    for scope,mask in [('all',np.ones(len(runners),bool)),('cold',runners.observed_starts.eq(0)),('experienced',runners.observed_starts.gt(0))]:
        one=runners[mask];g=one.groupby(['model','race_id','race_date'])[['log_loss','brier']].mean().reset_index()
        a=g[g.model=='baseline'];b=g[g.model=='candidate']
        joined=a.merge(b,on=['race_id','race_date'],validate='one_to_one',suffixes=('_base','_candidate'))
        for metric in ('log_loss','brier'):
            paired=joined[['race_id','race_date']].copy();paired['delta']=joined[metric+'_candidate']-joined[metric+'_base']
            ci,draws=interval(paired);cis.append(dict(scope=scope,metric=metric,**ci))
            drawrows.extend(dict(scope=scope,metric=metric,draw=i,delta=float(v)) for i,v in enumerate(draws))
            scopes.append(dict(scope=scope,metric=metric,baseline=float(joined[metric+'_base'].mean()),candidate=float(joined[metric+'_candidate'].mean()),rows=int(len(one)/2),races=len(joined),dates=ci['date_n']))
    pd.DataFrame(scopes).to_csv(HERE/'ROOT_FRESH_SCOPES.csv',index=False)
    pd.DataFrame(cis).to_csv(HERE/'ROOT_FRESH_INTERVALS.csv',index=False)
    pd.DataFrame(drawrows).to_parquet(HERE/'ROOT_FRESH_BOOTSTRAP.parquet',index=False)
    cold_races=set(f.loc[f.observed_starts.eq(0),'race_id'])
    hits=[]
    for scope,ids in [('all',set(f.race_id)),('cold_containing',cold_races)]:
        for label in ('baseline','candidate'):
            one=races[(races.model==label)&races.race_id.isin(ids)]
            hits.append(dict(scope=scope,model=label,races=len(one),six_combo_hits=int(one.six_combo_hit.sum()),
                             pick_hits=int(one.pick_hit.sum()),top3_all3=int(one.top3_all3.sum()),top5_all3=int(one.top5_all3.sum())))
    concordance=[]
    for label in ('baseline','candidate'):
        for rid,g in runners[(runners.model==label)&runners.observed_starts.eq(0)].groupby('race_id',sort=True):
            positive=g[g.finish_position.le(3)].score.to_numpy();negative=g[g.finish_position.gt(3)].score.to_numpy()
            pairs=[float(a>b)+.5*float(a==b) for a in positive for b in negative]
            if pairs:concordance.append(dict(model=label,race_id=rid,pairs=len(pairs),concordance=float(np.mean(pairs))))
    pd.DataFrame(concordance).to_csv(HERE/'ROOT_FRESH_CONCORDANCE.csv',index=False)
    for lockname in ('ROOT_PROTECTED_BEFORE.json','ROOT_OPERATING_BEFORE.json'):
        lock=json.loads((HERE/lockname).read_text())
        for path,expected in lock.items():assert sha(ROOT/path)==expected,path
    proof=dict(status='PASS',source_and_feature_release_sha256=sha(HERE/'ROOT_RELEASE.json'),
               rows=len(f),races=f.race_id.nunique(),dates=f.race_date.nunique(),cold_rows=int(f.observed_starts.eq(0).sum()),
               cold_races=len(cold_races),scope_metrics=scopes,paired_intervals=cis,hits=hits,
               concordance={label:float(pd.DataFrame(concordance).query('model==@label').concordance.mean()) for label in ('baseline','candidate')},
               root_training_calls=0,root_temperature_optimizations=0,protected_files_unchanged=True)
    dump_new('ROOT_FRESH_EVALUATION.json',proof)
    print(json.dumps(proof,indent=2))

if __name__=='__main__':main()
