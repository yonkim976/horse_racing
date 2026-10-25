"""Minimal horse-profile ablation. Local frozen inputs; no production writes."""
from pathlib import Path
from functools import lru_cache
import argparse
import hashlib
import importlib.util
import itertools
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
RESEARCH=HERE.parent
OUT=HERE/'outputs'
RAW=RESEARCH/'20261004_outsider_joint_v1/outputs/features.parquet'
ADJ=RESEARCH/'20261005_moisture_finish_v1/outputs/adjusted_features.parquet'
RECORDS=RESEARCH/'20261003_pace_gate_moisture_v2/outputs/adjusted_records.parquet'
LABELS=RESEARCH/'20261004_pace_finish_stack_v1/outputs/labels.parquet'
REFERENCE=RESEARCH/'20261006_moisture_no_jockey_v1/outputs'
PROFILE=RESEARCH/'20261008_horse_profile_v1/outputs'
KEY=['race_key','program_no','horse_id']
BASE=['distance_m','grade','grade_kind','field_size','history_count','days_since_last','previous_age','previous_sex']
CORE=['last_record_index','last3_record_index_mean','last5_record_index_best','last5_record_index_count']
EXTRA=['profile_top2mean5','profile_previous3','profile_trend','profile_std5',
       'profile_count3','profile_previous3_count','profile_valid5_support_fraction']
CONTRACTS={'raw12':BASE+CORE,'moist12':BASE+['moist_'+c for c in CORE],
           'profile19':BASE+['moist_'+c for c in CORE]+EXTRA}

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()

def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def cfg():return json.loads((HERE/'config.json').read_text())

def build_frame():
    meta=KEY+['meet','race_date','race_no','year','grade_raw','horse_name','history_source_date']
    f=pd.read_parquet(RAW,columns=meta+BASE+CORE)
    for col in ['last5_record_index_count']:
        f[col]=f[col].fillna(0)
    a=pd.read_parquet(ADJ,columns=KEY+CORE)
    a=a.rename(columns={col:'moist_'+col for col in CORE})
    f=f.merge(a,on=KEY,validate='one_to_one')
    f['moist_last5_record_index_count']=f.moist_last5_record_index_count.fillna(0)
    h=pd.read_parquet(RECORDS,columns=['horse_id','race_date','record_index','supported'])
    h=h.sort_values(['horse_id','race_date']).reset_index(drop=True)
    assert not h.duplicated(['horse_id','race_date']).any()
    g=h.groupby('horse_id',sort=False).record_index
    states=h[['horse_id','race_date']].copy()
    states['profile_count3']=g.transform(lambda x:x.rolling(3,min_periods=1).count())
    states['profile_previous3_count']=g.transform(lambda x:x.shift(3).rolling(3,min_periods=1).count())
    states['profile_previous3']=g.transform(lambda x:x.shift(3).rolling(3,min_periods=1).mean())
    recent=g.transform(lambda x:x.rolling(3,min_periods=1).mean())
    states['profile_trend']=(recent-states.profile_previous3).where(states.profile_count3.ge(2)&states.profile_previous3_count.ge(2))
    states['profile_std5']=g.transform(lambda x:x.rolling(5,min_periods=3).std())
    # Vectorized top2 over each five-start window; invalid starts keep their positions.
    top2=np.full(len(h),np.nan)
    for idx in h.groupby('horse_id',sort=False).indices.values():
        q=h.record_index.to_numpy(float)[idx]
        window=np.lib.stride_tricks.sliding_window_view(np.pad(q,(4,0),constant_values=np.nan),5)
        known=np.isfinite(window).sum(axis=1)
        ordered=np.sort(np.where(np.isfinite(window),window,-np.inf),axis=1)
        top2[idx]=np.where(known>=2,ordered[:,-2:].mean(axis=1),np.nan)
    states['profile_top2mean5']=top2
    h['support_valid']=h.supported.astype(float).where(h.record_index.notna())
    states['profile_valid5_support_fraction']=h.groupby('horse_id',sort=False).support_valid.transform(lambda x:x.rolling(5,min_periods=1).mean())
    states=states.rename(columns={'race_date':'profile_source_date'})
    query=f[KEY+['race_date']].copy();query['_row']=np.arange(len(f))
    query['cutoff_date']=query.race_date-pd.Timedelta(days=2)
    joined=pd.merge_asof(query.sort_values('cutoff_date'),states.sort_values('profile_source_date'),
                         by='horse_id',left_on='cutoff_date',right_on='profile_source_date',direction='backward')
    joined=joined.sort_values('_row').reset_index(drop=True)
    for col in ['profile_count3','profile_previous3_count']:joined[col]=joined[col].fillna(0)
    f=pd.concat([f,joined[EXTRA+['profile_source_date','cutoff_date']]],axis=1)
    labels=pd.read_parquet(LABELS)
    f=f.merge(labels,on=KEY,validate='one_to_one')
    assert len(f)==178497
    assert f.outcome.notna().all()
    assert (f.profile_source_date.isna()|f.profile_source_date.le(f.cutoff_date)).all()
    # Compare against the previously independently verified actual evaluation table.
    p=pd.read_parquet(PROFILE/'profiles.parquet')
    aligned=p[KEY].merge(f,on=KEY,validate='one_to_one')
    profile_mapping={
        'moist_last_record_index':'moist_last','moist_last3_record_index_mean':'moist_mean3',
        'moist_last5_record_index_best':'moist_best5','moist_last5_record_index_count':'moist_count5',
        'profile_top2mean5':'moist_top2mean5','profile_previous3':'moist_previous3','profile_trend':'moist_trend',
        'profile_std5':'moist_std5','profile_count3':'moist_count3','profile_previous3_count':'moist_previous3_count',
        'profile_valid5_support_fraction':'valid5_support_fraction'}
    for feature,column in profile_mapping.items():
        assert np.allclose(aligned[feature],p[column],equal_nan=True,atol=1e-10,rtol=0),feature
    return f

def prepare():
    if OUT.exists():raise FileExistsError('Existing experiment')
    paths=[HERE/'run.py',HERE/'PLAN.md',HERE/'config.json',RAW,ADJ,RECORDS,LABELS,
           PROFILE/'profiles.parquet',PROFILE/'verification.json',REFERENCE/'race_metrics.csv',
           REFERENCE/'runner_predictions.parquet',REFERENCE/'recommendations.parquet',
           ROOT/'config/prediction_model_registry.json',
           RESEARCH/'20261006_feature_inventory_v1/baseline_contract.json']
    hashes={str(p.relative_to(ROOT)):sha(p) for p in paths}
    print('Preparing chronological profile inputs',flush=True)
    f=build_frame()
    for cols in CONTRACTS.values():
        assert len(cols)==len(set(cols))
        assert not set(cols)&set(KEY+['outcome','race_date','profile_source_date'])
        assert not any('jockey' in c or 'gate' in c or 'stack_' in c for c in cols)
    OUT.mkdir()
    f.to_parquet(OUT/'features.parquet',index=False)
    save(OUT/'feature_contract.json',CONTRACTS)
    save(OUT/'audit.json',dict(inputs=hashes,rows=len(f),features_sha256=sha(OUT/'features.parquet'),
                              contract_sha256=sha(OUT/'feature_contract.json'),profile_reproduced_rows=50754,
                              new_training_pending=True,production_changed=False))
    print('Prepared',len(f),{v:len(c) for v,c in CONTRACTS.items()},flush=True)

def check_inputs():
    audit=json.loads((OUT/'audit.json').read_text())
    for path,value in audit['inputs'].items():assert sha(ROOT/path)==value,path
    assert sha(OUT/'features.parquet')==audit['features_sha256']
    assert sha(OUT/'feature_contract.json')==audit['contract_sha256']

def encode(f,cols,year):
    train=f.year.between(2017,year-3)
    x=f[cols].copy();vocab={}
    for col in x:
        if not pd.api.types.is_numeric_dtype(x[col]):
            vocab[col]=sorted(f.loc[train,col].dropna().unique().tolist())
            x[col]=pd.Categorical(x[col],categories=vocab[col])
    return x,vocab

def fit(f,cols,year,c,path):
    path.mkdir(parents=True,exist_ok=False)
    train=f.year.between(2017,year-3);valid=f.year.eq(year-2);cal=f.year.eq(year-1);test=f.year.eq(year)
    assert all(x.any() for x in [train,valid,cal,test])
    x,vocab=encode(f,cols,year);y=f.outcome.le(3).astype(int);weight=1/f.field_size
    params=c['training'].copy();rounds=params.pop('max_rounds');early=params.pop('early_stopping_rounds');params['seed']=c['seed']
    def dataset(mask):return lgb.Dataset(x[mask],label=y[mask],weight=weight[mask],free_raw_data=False)
    initial=lgb.train(params,dataset(train),num_boost_round=rounds,valid_sets=[dataset(valid)],callbacks=[lgb.early_stopping(early,verbose=False)])
    model=lgb.train(params,dataset(train|valid),num_boost_round=initial.best_iteration)
    model.save_model(str(path/'top3.txt'))
    score=np.full(len(f),np.nan)
    for mask in [cal,test]:score[mask]=model.predict(x[mask],raw_score=True,num_threads=4)
    meta=dict(evaluation_year=year,training_min='2017-01-01',train_end=str(f.loc[train|valid,'race_date'].max().date()),
              validation_year=year-2,calibration_year=year-1,features=cols,category_vocabulary=vocab,
              trees=int(initial.best_iteration),model_sha256=sha(path/'top3.txt'),
              gain=dict(zip(cols,model.feature_importance(importance_type='gain').astype(float))))
    return score,meta

@lru_cache(maxsize=32)
def support(n):
    sets=np.array(list(itertools.combinations(range(n),3)),int)
    incidence=np.zeros((len(sets),n))
    for i,s in enumerate(sets):incidence[i,s]=1
    return sets,incidence

def parts(f,score):
    result=[]
    for rid,idx in f.groupby('race_key',sort=False).indices.items():
        one=f.iloc[idx];sets,_=support(len(one))
        truth=tuple(np.flatnonzero(one.outcome.le(3).to_numpy()))
        assert len(truth)==3
        target=next(i for i,s in enumerate(sets) if tuple(s)==truth)
        # Sort each three-score multiset before summation. Equal unordered sets
        # must not gain an arbitrary ULP advantage from horse-position addition order.
        result.append(dict(race_key=rid,idx=idx,energy=np.sort(score[idx][sets],axis=1).sum(axis=1),target=target))
    return result

def fit_temperature(races,c):
    width=max(len(p['energy']) for p in races)
    matrix=np.full((len(races),width),-np.inf)
    truth=np.array([p['energy'][p['target']] for p in races])
    for i,p in enumerate(races):matrix[i,:len(p['energy'])]=p['energy']
    result=minimize_scalar(lambda t:float(np.mean(logsumexp(matrix/t,axis=1)-truth/t)),bounds=c['temperature_bounds'],method='bounded')
    assert result.success
    return float(result.x)

def evaluate(f,score,temp,variant):
    races=[];runners=[];tickets=[]
    for p in parts(f,score):
        one=f.iloc[p['idx']];n=len(one);sets,incidence=support(n)
        energy=p['energy']/temp;q=np.exp(energy-logsumexp(energy));m=q@incidence
        # Marginal rank is analytically monotonic in the individual raw score.
        # Score order avoids ULP differences in separate marginal summations.
        assert one.program_no.is_monotonic_increasing
        order=np.argsort(-score[p['idx']],kind='stable');best=np.argsort(-q,kind='stable')[:6]
        truth=set(sets[p['target']]);history=one.history_count.to_numpy()
        r=dict(race_key=p['race_key'],meet=int(one.meet.iloc[0]),evaluation_year=int(one.year.iloc[0]),
               race_date=str(one.race_date.iloc[0].date()),variant=variant,field_size=n,
               distance_m=float(one.distance_m.iloc[0]),grade=float(one.grade.iloc[0]) if pd.notna(one.grade.iloc[0]) else None,
               new_horse_present=bool(np.any(history==0)),low_history_present=bool(np.any(history<5)),
               trio6_hit=int(p['target'] in best),trio6_probability=float(q[best].sum()),
               trio_nll=float(-np.log(q[p['target']])),top3_brier=float(np.mean((m-one.outcome.le(3).to_numpy())**2)),
               top3_first_hit=int(order[0] in truth),probability_sum_error=float(abs(q.sum()-1)))
        for k in [3,5,6,7]:r[f'top{k}_contains_podium']=int(truth<=set(order[:k]))
        races.append(r)
        for i,row in enumerate(one.to_dict('records')):
            runners.append({**{k:row[k] for k in KEY},'meet':int(row['meet']),'evaluation_year':int(row['year']),
                            'variant':variant,'outcome':int(row['outcome']),'raw_top3_score':float(score[p['idx'][i]]),'prob_top3':float(m[i])})
        for rank,j in enumerate(best,1):
            tickets.append(dict(race_key=p['race_key'],variant=variant,selection_rank=rank,
                                programs=','.join(map(str,sorted(one.program_no.iloc[sets[j]].astype(int)))),
                                probability=float(q[j]),hit=int(j==p['target'])))
    return pd.DataFrame(races),pd.DataFrame(runners),pd.DataFrame(tickets)

def summarize(r,c):
    result=[]
    for (meet,variant),g in r.groupby(['meet','variant']):
        periods=[('all',g)]+[(str(year),one) for year,one in g.groupby('evaluation_year')]
        for period,one in periods:
            row=dict(meet=int(meet),variant=variant,period=period,races=len(one),hits=int(one.trio6_hit.sum()))
            for col in ['trio6_hit','trio_nll','top3_brier','top3_first_hit','top3_contains_podium','top5_contains_podium','trio6_probability']:
                row[col]=float(one[col].mean())
            result.append(row)
    for variant,g in r.groupby('variant'):
        row=dict(meet=0,variant=variant,period='all',races=len(g),hits=int(g.trio6_hit.sum()))
        for col in ['trio6_hit','trio_nll','top3_brier','top3_first_hit','top3_contains_podium','top5_contains_podium','trio6_probability']:row[col]=float(g[col].mean())
        result.append(row)
    pd.DataFrame(result).to_csv(OUT/'metrics.csv',index=False)
    differences=[];rng=np.random.default_rng(c['bootstrap_seed'])
    for meet in [0,1,3]:
        subset=r if not meet else r[r.meet.eq(meet)]
        for base,candidate in [('raw12','moist12'),('moist12','profile19'),('reference258','profile19')]:
            pair=subset[subset.variant.eq(base)].merge(subset[subset.variant.eq(candidate)],on='race_key',suffixes=('_a','_b'),validate='one_to_one')
            for metric in ['trio6_hit','trio_nll','top3_brier','top5_contains_podium']:
                delta=pair[metric+'_b']-pair[metric+'_a']
                daily=pd.DataFrame({'date':pair.race_date_a,'delta':delta}).groupby('date').delta.agg(['sum','size']).to_numpy()
                draws=daily[rng.integers(len(daily),size=(c['bootstrap_draws'],len(daily)))].sum(axis=1)
                differences.append(dict(meet=meet,base=base,candidate=candidate,metric=metric,races=len(pair),
                                        difference=float(delta.mean()),date_bootstrap_95=np.quantile(draws[:,0]/draws[:,1],[.025,.975]).tolist()))
    save(OUT/'paired_differences.json',differences)
    slices=[]
    for (meet,variant),g in r.groupby(['meet','variant']):
        groups=[('new_horse_present',str(value),one) for value,one in g.groupby('new_horse_present')]
        groups += [('low_history_present',str(value),one) for value,one in g.groupby('low_history_present')]
        groups += [('distance_m',str(value),one) for value,one in g.groupby('distance_m')]
        groups += [('grade',str(value),one) for value,one in g.groupby('grade',dropna=False)]
        for kind,value,one in groups:
            slices.append(dict(meet=int(meet),variant=variant,dimension=kind,value=value,races=len(one),
                               hits=int(one.trio6_hit.sum()),trio6_hit=float(one.trio6_hit.mean()),
                               trio_nll=float(one.trio_nll.mean()),top3_brier=float(one.top3_brier.mean())))
    pd.DataFrame(slices).to_csv(OUT/'slices.csv',index=False)

def train():
    check_inputs();c=cfg()
    if (OUT/'summary.json').exists():raise FileExistsError('Completed experiment')
    f=pd.read_parquet(OUT/'features.parquet')
    contracts=json.loads((OUT/'feature_contract.json').read_text())
    race_outputs=[];runner_outputs=[];ticket_outputs=[]
    for meet in c['venues']:
        one=f[f.meet.eq(meet)].reset_index(drop=True)
        for year in c['evaluation_years']:
            for variant in c['variants']:
                print('Train',meet,year,variant,flush=True)
                path=OUT/'models'/f'{meet}_{year}_{variant}'
                scores,meta=fit(one,contracts[variant],year,c,path)
                cal=one.year.eq(year-1);test=one.year.eq(year)
                temp=fit_temperature(parts(one[cal].reset_index(drop=True),scores[cal]),c)
                meta.update(temperature=temp,calibration_races=int(one.loc[cal,'race_key'].nunique()))
                save(path/'metadata.json',meta)
                race,runner,ticket=evaluate(one[test].reset_index(drop=True),scores[test],temp,variant)
                race_outputs.append(race);runner_outputs.append(runner);ticket_outputs.append(ticket)
                print('Evaluated',meet,year,variant,len(race),'hits',int(race.trio6_hit.sum()),'trees',meta['trees'],flush=True)
    race=pd.concat(race_outputs,ignore_index=True);runner=pd.concat(runner_outputs,ignore_index=True);ticket=pd.concat(ticket_outputs,ignore_index=True)
    reference=pd.read_csv(REFERENCE/'race_metrics.csv',low_memory=False)
    reference=reference[reference.variant.eq('no_jockey')].copy()
    ref_runner=pd.read_parquet(REFERENCE/'runner_predictions.parquet');ref_runner=ref_runner[ref_runner.variant.eq('no_jockey')].copy()
    metadata=race[race.variant.eq('raw12')][['race_key','race_date','new_horse_present','low_history_present']]
    reference=reference.drop(columns=['race_date','new_horse_present','low_history_present'],errors='ignore').merge(metadata,on='race_key',validate='one_to_one')
    for frame in [reference,ref_runner]:frame['variant']='reference258'
    assert len(reference)==4799 and len(ref_runner)==50754
    race=pd.concat([race,reference],ignore_index=True)
    runner=pd.concat([runner,ref_runner[runner.columns]],ignore_index=True)
    race.to_csv(OUT/'race_metrics.csv',index=False);runner.to_parquet(OUT/'runner_predictions.parquet',index=False)
    ticket.to_parquet(OUT/'recommendations.parquet',index=False)
    summarize(race,c);check_inputs()
    save(OUT/'summary.json',dict(new_heads=18,variants={v:len(cols) for v,cols in contracts.items()},
         evaluation_races=4799,evaluation_runners=50754,reference='no_jockey258',production_changed=False,
         independent_future_test=False,new_gate_inputs=False,joint_models=False,
         model_hashes={str(p.relative_to(OUT)):sha(p) for p in (OUT/'models').rglob('top3.txt')}))
    print('Completed 18 models',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','train']);args=parser.parse_args()
    {'prepare':prepare,'train':train}[args.mode]()
