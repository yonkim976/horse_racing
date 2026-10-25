"""Chronological gate/early/finish ablations using frozen local research data."""
import argparse
import importlib.util
import itertools
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.special import logsumexp

HERE=Path(__file__).resolve().parent
R=HERE.parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
OLD=R/'20261009_section_style_finish_v1'
GATE=R/'20261009_gate_front_late_v1'


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S=module('fixed_section',OLD/'run.py')
T=module('fixed_hypotheses',R/'20261009_race_hypothesis_v1/run.py')
sha,save=S.sha,S.save
BASE=S.BASE
EARLY=['early_mean3','early_n5','gate_fraction','inner_n','inner_early_n','inner_fastest_gap',
       'inner_mean_gap','inner_faster_n','inner_close_n','same_early_mean5','same_early_n5',
       'same_inner_fastest_gap','same_inner_early_n','front_rate5','front_n5']
KEEP=['front_g3','front_g1','front_n','front_keep','fast_g3','fast_g1','fast_n','fast_keep',
      'outerfast_g3','outerfast_g1','outerfast_n','valid_n']
INTER=['p_front_g3','p_front_g1','pressure_fast_g3','pressure_fast_g1']
EARLY=['inner_'+c for c in EARLY]
KEEP=['keep_'+c for c in KEEP]
INTER=['combine_'+c for c in INTER]
PROB=['front_probability','front_supported']
CONTRACTS=dict(baseline22=BASE,inner37=BASE+EARLY,front39=BASE+EARLY+PROB,
               combined55=BASE+EARLY+PROB+KEEP+INTER)
METRICS=['axis_top3','axis_top2','axis_win','quinella_one','axis_next3','top5_all','top3_all',
         'trio6','target_brier','set_logloss']


def freeze():
    OUT.mkdir(parents=True,exist_ok=True)
    paths=[HERE/'PLAN.md',HERE/'run.py',OLD/'run.py',OLD/'config.json',T.HERE/'run.py',
           S.W/'research_baseline_selection.json',ROOT/'config/prediction_model_registry.json',
           R/'20261010_axis_signal_calibration_v1/outputs/future_validation_contract.json',
           S.P/'observations.parquet',OLD/'outputs/section_corrections.parquet']
    paths += [OLD/'outputs'/n for n in ['features.parquet','history_observations.parquet','history_slots.npy','race_metrics.csv','runner_predictions.parquet']]
    paths += [GATE/'outputs'/n for n in ['race_metrics.csv','runner_predictions.parquet']]
    m={str(p.relative_to(ROOT)):sha(p) for p in paths}
    p=OUT/'input_manifest.json'
    if p.exists(): assert json.loads(p.read_text())==m
    else: save(p,m)
    b=OUT/'publication_before.json'
    if not b.exists():
        shared=[R/n for n in ['README.md','ARTIFACT_SIZE_LOG.md','conclusions/README.md','conclusions/SOURCES.md','conclusions/source_manifest.json']]
        save(b,{str(p.relative_to(ROOT)):dict(bytes=p.stat().st_size,sha256=sha(p)) for p in shared})
        snap=OUT/'publication_before';snap.mkdir()
        for p in shared: (snap/str(p.relative_to(R)).replace('/','__')).write_bytes(p.read_bytes())


def check():
    for path,expected in json.loads((OUT/'input_manifest.json').read_text()).items():
        assert sha(ROOT/path)==expected,path


def historical_context():
    a=pd.read_parquet(S.P/'observations.parquet')
    a['race_key']=a.source_key.str.replace('서울:','1:',regex=False).str.replace('부산:','3:',regex=False)
    a['program_no']=a.gate
    cor=pd.read_parquet(OLD/'outputs/section_corrections.parquet')
    a=a.merge(cor.drop(columns='year'),on='row_key',how='left',validate='one_to_one')
    a['gate_fraction']=(a.groupby('race_key').gate.rank(method='first')-1)/(a.field_size-1)
    a['role_valid']=a.group_observed & ~a.leader_conflict_race & a.role4.between(0,3)
    for part in S.PARTS:
        v=a[part+'_adjusted'].where(a[part+'_adjusted'].notna(),a[part]).where(a.normal_outcome)
        n=v.groupby(a.race_key).transform('count')
        total=v.groupby(a.race_key).transform('sum')
        ok=v.notna() & ((n-1)>=5) & (n/a.field_size>=.8)
        a[part+'_peer_adv']=((total-v)/(n-1)-v).where(ok).round(10)
    valid=a[[p+'_peer_adv' for p in S.PARTS]].notna().all(axis=1)
    masks=dict(front=valid & a.role_valid & (a.role4==0),fast=valid & (a.early_peer_adv>0))
    masks['outerfast']=masks['fast'] & (a.gate_fraction>=2/3)
    for name,mask in masks.items():
        a['event_'+name+'_g3']=a.last600_peer_adv.where(mask)
        a['event_'+name+'_g1']=a.late_peer_adv.where(mask)
        if name!='outerfast':
            a['event_'+name+'_keep']=((a.last600_peer_adv>=0)&(a.late_peer_adv>=0)).astype(float).where(mask)
    a['event_valid']=valid.astype(float)
    cols=[c for c in a if c.startswith('event_')]+[p+'_peer_adv' for p in S.PARTS]+['gate_fraction','role_valid','normal_outcome','field_size','role4']
    h=pd.read_parquet(OLD/'outputs/history_observations.parquet')
    h=h.merge(a[S.KEY+cols],on=S.KEY,how='left',validate='one_to_one')
    return h


def early_features(f,h,slots):
    v=S.values(h,slots,'early_adjusted')
    raw=S.values(h,slots,'early')
    v=np.where(np.isfinite(v),v,raw)
    dist=S.values(h,slots,'result_distance')
    same=np.where(dist==f.distance_m.to_numpy()[:,None],v,np.nan)
    n=np.isfinite(same).sum(axis=1)
    mean=S.average(same);mean[n<2]=np.nan
    roles=S.values(h,slots,'role4')
    validrole=S.values(h,slots,'role_valid')==1
    rp=np.where(validrole,(roles==0).astype(float),np.nan)
    out=pd.DataFrame(dict(inner_early_mean3=f.section_early_mean3.to_numpy(),inner_early_n5=f.section_early_n5.to_numpy(),
          inner_same_early_mean5=mean,inner_same_early_n5=n,inner_front_rate5=S.average(rp),
          inner_front_n5=np.isfinite(rp).sum(axis=1)),index=f.index)
    for name in EARLY:
        if name not in out: out[name]=np.nan
    for ix in f.groupby('race_key',sort=False).indices.values():
        gates=f.program_no.to_numpy()[ix]
        e=out.inner_early_mean3.to_numpy()[ix];sm=mean[ix]
        for j,idx in enumerate(ix):
            inside=gates<gates[j];known=inside & np.isfinite(e);sk=inside & np.isfinite(sm)
            out.at[idx,'inner_gate_fraction']=float((gates<gates[j]).sum()/(len(ix)-1))
            out.at[idx,'inner_inner_n']=float(inside.sum())
            out.at[idx,'inner_inner_early_n']=float(known.sum())
            out.at[idx,'inner_same_inner_early_n']=float(sk.sum())
            if known.any() and np.isfinite(e[j]):
                out.at[idx,'inner_inner_fastest_gap']=float(e[known].min()-e[j])
                out.at[idx,'inner_inner_mean_gap']=float(e[known].mean()-e[j])
                out.at[idx,'inner_inner_faster_n']=float((e[known]<e[j]).sum())
                out.at[idx,'inner_inner_close_n']=float((np.abs(e[known]-e[j])<=.15).sum())
            elif not inside.any() and np.isfinite(e[j]):
                out.at[idx,'inner_inner_faster_n']=0.;out.at[idx,'inner_inner_close_n']=0.
            if sk.sum()>=3 and sk.sum()/inside.sum()>=.8 and np.isfinite(sm[j]):
                out.at[idx,'inner_same_inner_fastest_gap']=float(sm[sk].min()-sm[j])
    return out[EARLY]


def keep_features(h,slots):
    out={}
    for kind in ['front','fast','outerfast']:
        n=np.isfinite(S.values(h,slots,'event_'+kind+'_g3')).sum(axis=1).astype(float)
        out['keep_'+kind+'_n']=n
        for part in ['g3','g1']:
            mean=S.average(S.values(h,slots,'event_'+kind+'_'+part))
            out['keep_'+kind+'_'+part]=mean*n/(n+3)
        if kind!='outerfast':
            v=S.values(h,slots,'event_'+kind+'_keep')
            rate=(np.nansum(v,axis=1)+1)/(n+2);rate[n==0]=np.nan
            out['keep_'+kind+'_keep']=rate
    out['keep_valid_n']=np.nansum(S.values(h,slots,'event_valid'),axis=1)
    return pd.DataFrame(out)[KEEP]


def interactions(f):
    p=f.front_probability.to_numpy(float)
    pressure=np.divide(f.inner_inner_faster_n.to_numpy(float),f.inner_inner_early_n.to_numpy(float),
                       out=np.full(len(f),np.nan),where=f.inner_inner_early_n.to_numpy(float)>0)
    return pd.DataFrame(dict(combine_p_front_g3=p*f.keep_front_g3,
        combine_p_front_g1=p*f.keep_front_g1,combine_pressure_fast_g3=p*pressure*f.keep_fast_g3,
        combine_pressure_fast_g1=p*pressure*f.keep_fast_g1),index=f.index)[INTER]


def prepare():
    f=pd.read_parquet(OLD/'outputs/features.parquet')
    h=historical_context();slots=np.load(OLD/'outputs/history_slots.npy',allow_pickle=False)
    early=early_features(f,h,slots);keep=keep_features(h,slots)
    f=pd.concat([f,early,keep],axis=1)
    f['front_label']=f.aux_early.eq(0).astype(float).where(f.aux_early.notna())
    # Exclude conflicting group sources from the auxiliary target, preserving other runners.
    obs=pd.read_parquet(S.P/'observations.parquet',columns=['source_key','gate','horse_id','leader_conflict_race'])
    conflict=obs[obs.leader_conflict_race].source_key.str.replace('서울:','1:',regex=False).str.replace('부산:','3:',regex=False)
    f.loc[f.race_key.isin(conflict),'front_label']=np.nan
    probability=np.full(len(f),np.nan)
    auxcols=CONTRACTS['inner37']
    for year in range(2020,2027):
        train=f.year.between(2017,year-1)&f.front_label.notna();test=f.year.eq(year)
        x,vocab=S.encode(f,auxcols,train)
        params=S.config()['training'].copy();params.pop('max_rounds');params.pop('early_stopping_rounds')
        params.update(seed=42,lambda_l2=10.)
        folder=OUT/'front_models'/str(year);folder.mkdir(parents=True,exist_ok=True)
        model=lgb.train(params,lgb.Dataset(x[train],label=f.loc[train,'front_label'],weight=1/f.loc[train,'field_size']),num_boost_round=180)
        model.save_model(str(folder/'model.txt'))
        save(folder/'metadata.json',dict(year=year,features=auxcols,category_vocabulary=vocab,train_end=str(f.loc[train,'race_date'].max().date()),
             training_rows=int(train.sum()),model_sha256=sha(folder/'model.txt')))
        probability[test]=model.predict(x[test],num_threads=4)
        print('Front',year,int(train.sum()),flush=True)
    f['front_probability']=probability;f['front_supported']=np.isfinite(probability).astype(float)
    f=pd.concat([f,interactions(f)],axis=1)
    assert [len(CONTRACTS[c]) for c in CONTRACTS]==[22,37,39,55]
    assert f[BASE].equals(pd.read_parquet(OLD/'outputs/features.parquet')[BASE])
    for cols in CONTRACTS.values():
        assert len(cols)==len(set(cols))
        assert not any(c.startswith(('aux_','outcome')) or 'jockey' in c or 'trainer' in c or c=='front_label' for c in cols)
    h.to_parquet(OUT/'history_events.parquet',index=False)
    f.to_parquet(OUT/'features.parquet',index=False)
    save(OUT/'feature_contract.json',CONTRACTS|dict(combined55_top2=CONTRACTS['combined55']))
    coverage=[]
    for year,g in f[f.year>=2024].groupby('year'):
        coverage.append(dict(year=int(year),rows=len(g),races=g.race_key.nunique(),early=int(g.inner_early_mean3.notna().sum()),
           same_inner_gap=int(g.inner_same_inner_fastest_gap.notna().sum()),front_keep=int(g.keep_front_n.gt(0).sum()),
           fast_keep=int(g.keep_fast_n.gt(0).sum()),outerfast_keep=int(g.keep_outerfast_n.gt(0).sum())))
    pd.DataFrame(coverage).to_csv(OUT/'coverage.csv',index=False)
    check()


def train():
    check();f=pd.read_parquet(OUT/'features.parquet');races=[];runners=[]
    for variant,target in [('inner37',3),('front39',3),('combined55',3),('combined55_top2',2)]:
        cols=CONTRACTS['combined55' if target==2 else variant]
        for meet in [1,3]:
            one=f[f.meet==meet].reset_index(drop=True)
            for year in [2024,2025,2026]:
                folder=OUT/'models'/f'{variant}_{meet}_{year}';folder.mkdir(parents=True,exist_ok=True)
                if (folder/'races.csv').exists():
                    r=pd.read_csv(folder/'races.csv');p=pd.read_parquet(folder/'runners.parquet')
                else:
                    r,p=S.fit(one,cols,year,target,variant,folder)
                    r.to_csv(folder/'races.csv',index=False);p.to_parquet(folder/'runners.parquet',index=False)
                races.append(r);runners.append(p)
                print('Finish',variant,meet,year,flush=True)
    for source,variant,target,name in [(OLD,'baseline22',3,'baseline22'),(GATE,'full103',3,'previous_full103'),(OLD,'baseline22',2,'baseline22_top2')]:
        r=pd.read_csv(source/'outputs/race_metrics.csv');p=pd.read_parquet(source/'outputs/runner_predictions.parquet')
        r=r[(r.variant==variant)&(r.target==target)].copy();p=p[(p.variant==variant)&(p.target==target)].copy()
        r['variant']=name;p['variant']=name;races.append(r);runners.append(p)
    pd.concat(races,ignore_index=True).to_csv(OUT/'race_metrics.csv',index=False)
    pd.concat(runners,ignore_index=True).to_parquet(OUT/'runner_predictions.parquet',index=False)
    check()


def differences(a,b,variant,reference,period):
    g=a.merge(b,on='race_key',suffixes=('_new','_base'),validate='one_to_one');assert len(g)==len(a)==len(b)
    rng=np.random.default_rng(20261012);rows=[]
    for metric in METRICS:
        delta=g[metric+'_new']-g[metric+'_base']
        ag=pd.DataFrame(dict(date=g.race_date_new,delta=delta)).groupby('date').delta.agg(['sum','size']).to_numpy()
        draw=ag[rng.integers(0,len(ag),size=(2000,len(ag)))].sum(axis=1)
        factor=1 if metric in ['target_brier','set_logloss'] else 100
        lo,hi=np.quantile(draw[:,0]/draw[:,1],[.025,.975])*factor
        rows.append(dict(variant=variant,reference=reference,period=period,metric=metric,n=len(g),
                         difference=float(delta.mean()*factor),lo=float(lo),hi=float(hi),units='loss' if factor==1 else 'percentage_points'))
    return rows


def analyse():
    check();p=pd.read_parquet(OUT/'runner_predictions.parquet')
    r=T.add_coverage(pd.read_csv(OUT/'race_metrics.csv'),p)
    trio=[]
    for (variant,rid),g in p.groupby(['variant','race_key'],sort=False):
        g=g.sort_values('program_no');sets,inc=S.support(len(g),3)
        energy=g.raw_score.to_numpy()[sets].sum(axis=1)
        order=np.argsort(-energy,kind='stable')[:6]
        truth=tuple(np.flatnonzero(g.outcome.between(1,3)))
        trio.append(dict(variant=variant,race_key=rid,trio6=int(any(tuple(sets[j])==truth for j in order))))
    r=r.merge(pd.DataFrame(trio),on=['variant','race_key'],validate='one_to_one')
    r.to_csv(OUT/'race_diagnostics.csv',index=False)
    summary=[]
    for variant,g in r.groupby('variant'):
        for period,z in [('all',g)]+[(str(y),g[g.year==y]) for y in [2024,2025,2026]]:
            summary.append(dict(variant=variant,period=period,n=len(z),**{m:float(z[m].mean()) for m in METRICS}))
    pd.DataFrame(summary).to_csv(OUT/'metrics.csv',index=False)
    diff=[]
    pairs=[('inner37','baseline22'),('front39','baseline22'),('combined55','baseline22'),
           ('front39','inner37'),('combined55','front39'),('combined55','previous_full103'),('combined55_top2','baseline22_top2')]
    for variant,ref in pairs:
        for period,z in [('all',r)]+[(str(y),r[r.year==y]) for y in [2024,2025,2026]]:
            diff.extend(differences(z[z.variant==variant],z[z.variant==ref],variant,ref,period))
    pd.DataFrame(diff).to_csv(OUT/'paired_differences.csv',index=False)
    f=pd.read_parquet(OUT/'features.parquet');a=f[f.year>=2024].copy()
    a['front_brier']=(a.front_probability-a.front_label)**2
    aux=[]
    for year,g in a[a.front_label.notna()].groupby('year'):
        one=g.sort_values(['front_probability','program_no'],ascending=[False,True]).groupby('race_key').head(1)
        complete=g.groupby('race_key').size().eq(a.groupby('race_key').size()).reindex(one.race_key).fillna(False).to_numpy()
        aux.append(dict(year=int(year),rows=len(g),brier=float(g.front_brier.mean()),complete_races=int(complete.sum()),
                        top1_first_group=float(one.loc[complete,'front_label'].mean())))
    save(OUT/'front_metrics.json',aux)
    breakdown=[]
    for (variant,meet,dist,grade),z in r.groupby(['variant','meet','distance_m','grade'],dropna=False):
        breakdown.append(dict(variant=variant,meet=int(meet),distance_m=dist,grade=grade,n=len(z),**{m:float(z[m].mean()) for m in METRICS}))
    pd.DataFrame(breakdown).to_csv(OUT/'distance_grade_metrics.csv',index=False)
    check();print(pd.DataFrame(summary).query("period=='all'").to_string(index=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','train','analyse']);args=parser.parse_args()
    freeze();dict(prepare=prepare,train=train,analyse=analyse)[args.stage]()
