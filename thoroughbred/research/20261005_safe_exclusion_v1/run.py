"""Time-forward costly-exclusion head and immutable six-ticket policies."""
from functools import lru_cache
import argparse
import importlib.util
import itertools
import json
from pathlib import Path
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OUT=HERE/'outputs'
PARENT=HERE.parent/'20261004_outsider_joint_v1';STACK=HERE.parent/'20261004_pace_finish_stack_v1'
spec=importlib.util.spec_from_file_location('safe_parent_joint',PARENT/'run.py')
PRE=importlib.util.module_from_spec(spec);spec.loader.exec_module(PRE)
BASE,KEY=PRE.BASE,PRE.KEY

def config():return json.loads((HERE/'config.json').read_text())
def dump(p,v):BASE.save_json(p,v)

@lru_cache(maxsize=32)
def support(n):
    sets=np.array(list(itertools.combinations(range(n),3)),int)
    incidence=np.zeros((len(sets),n))
    for j,s in enumerate(sets):incidence[j,s]=1
    return sets,incidence

def normalized(energy):return np.exp(energy-logsumexp(energy))

def safe_prefix(p,n,required,remaining):
    sets,incidence=support(n);rank=np.argsort(p@incidence,kind='stable')
    best=np.array([],int);prob=1.
    for k in range(1,n-remaining+1):
        excluded=rank[:k]
        mass=float(p[~np.isin(sets,excluded).any(axis=1)].sum())
        if mass+1e-12<required:break
        best=excluded;prob=mass
    return best,prob

def select_policy(policy,parent,fusion,exclusion,context,guard,c):
    n=len(context);sets,incidence=support(n)
    p=parent if policy.startswith('parent') else fusion
    ranked=np.argsort(-(p@incidence),kind='stable')
    excluded=np.array([],int);safe=1.
    if policy=='parent_safe_top7':excluded,safe=safe_prefix(parent,n,c['safe_probability'],c['minimum_remaining'])
    if policy=='fusion_safe_top7' or (policy=='fusion_guarded_union7' and guard):
        excluded,safe=safe_prefix(exclusion,n,c['safe_probability'],c['minimum_remaining'])
    allowed=set(range(n))-set(excluded)
    if policy.endswith('_full'):pool=list(range(n))
    elif policy=='fusion_guarded_union7':
        pool=[int(i) for i in np.argsort(-context,kind='stable')[:5] if i in allowed]
        for i in ranked:
            if i in allowed and i not in pool:pool.append(int(i))
            if len(pool)>=7:break
    else:
        size=6 if policy=='fusion_top6' else 7
        pool=[int(i) for i in ranked if i in allowed][:size]
    eligible=np.isin(sets,pool).all(axis=1)
    ids=np.flatnonzero(eligible);best=ids[np.argsort(-p[ids],kind='stable')[:6]]
    if len(best)!=6:raise ValueError('Fewer than six distinct combinations')
    return dict(p=p,excluded=excluded,safe=safe,pool=pool,best=best,mass=float(p[best].sum()),pool_mass=float(p[eligible].sum()))

def fit_temperature(energies,targets,c):
    width=max(map(len,energies));matrix=np.full((len(energies),width),-np.inf)
    truth=np.array([e[t] for e,t in zip(energies,targets)])
    for j,e in enumerate(energies):matrix[j,:len(e)]=e
    result=minimize_scalar(lambda t:float(np.mean(logsumexp(matrix/t,axis=1)-truth/t)),bounds=c['temperature_bounds'],method='bounded')
    if not result.success:raise ValueError('Temperature failed')
    return float(result.x)

def encode(f,meta):
    x=f[meta['features']].copy()
    for col,v in meta['category_vocabulary'].items():x[col]=pd.Categorical(x[col],categories=v)
    return x

def fit_head(f,year,c,path):
    path.mkdir(parents=True,exist_ok=False)
    cols=json.loads((PARENT/'outputs/feature_contract.json').read_text())['upside']
    train=f.year.between(2017,year-3);valid=f.year.eq(year-2);future=f.year.isin([year-1,year])
    x,vocab=BASE.category_encode(f,train,cols)
    y=f.outcome.gt(3).astype(int)
    weights=np.where(y.eq(0),c['false_exclusion_weight'],1)/f.field_size
    params=c['training'].copy();rounds=params.pop('max_rounds');early=params.pop('early_stopping_rounds');params['seed']=c['training_seed']
    def ds(mask):return lgb.Dataset(x[mask],label=y[mask],weight=weights[mask],free_raw_data=False)
    initial=lgb.train(params,ds(train),num_boost_round=rounds,valid_sets=[ds(valid)],callbacks=[lgb.early_stopping(early,verbose=False)])
    final=lgb.train(params,ds(train|valid),num_boost_round=initial.best_iteration)
    final.save_model(str(path/'nonpodium.txt'))
    raw=np.full(len(f),np.nan);raw[future]=-final.predict(x[future],raw_score=True,num_threads=4)
    metadata=dict(evaluation_year=year,train_start='2017-01-01',train_end=str(f.loc[train|valid,'race_date'].max().date()),
        validation_year=year-2,calibration_year=year-1,target='outcome>3',false_exclusion_weight=c['false_exclusion_weight'],
        trees=int(initial.best_iteration),features=cols,category_vocabulary=vocab,model_sha256=BASE.sha(path/'nonpodium.txt'))
    return raw,metadata

def parent_parts(f,meet,year):
    braw,bmeta=PRE.baseline_scores(f,meet,year)
    folder=PARENT/'outputs/models'/f'{meet}_{year}_upside'
    meta=json.loads((folder/'metadata.json').read_text());pair=json.loads((folder/'joint.json').read_text())
    model=lgb.Booster(model_file=str(folder/'top3.txt'));raw=np.full(len(f),np.nan)
    mask=f.year.isin([year-1,year]);raw[mask]=model.predict(encode(f,meta)[mask],raw_score=True,num_threads=4)
    parts=[]
    for rid,idx in f[mask].groupby('race_key',sort=False).groups.items():
        idx=np.array(idx);g=f.loc[idx];sets,incidence=support(len(g))
        energy=raw[idx][sets].sum(axis=1)/pair['temperature']
        energy+=((PRE.pair_design(g)-np.array(pair['mean']))/np.array(pair['scale']))@np.array(pair['coefficients'])
        p=normalized(energy)
        _,_,context=BASE.joint(braw[idx],bmeta['temperatures'])
        actual=set(np.flatnonzero(g.outcome.le(3).to_numpy()))
        truth=next(j for j,s in enumerate(sets) if set(s)==actual)
        parts.append(dict(race_key=rid,idx=idx,year=int(g.year.iloc[0]),parent=p,context=context[:,2],truth=truth))
    return parts

def fit_guard(parts,c,seed):
    observed=[]
    for part in parts:
        excluded,_=safe_prefix(part['exclusion'],len(part['idx']),c['safe_probability'],c['minimum_remaining'])
        if len(excluded):
            sets,_=support(len(part['idx']));safe=int(not set(excluded)&set(sets[part['truth']]))
            observed.append(dict(date=part['date'],safe=safe))
    if len(observed)<c['guard_min_races']:return dict(allowed=False,races=len(observed),observed_safe=None if not observed else float(np.mean([o['safe'] for o in observed])),lower=None,seed=seed)
    daily=pd.DataFrame(observed).groupby('date').safe.agg(['sum','size']).to_numpy()
    rng=np.random.default_rng(seed);picks=rng.integers(0,len(daily),size=(c['bootstrap_draws'],len(daily)));samples=daily[picks]
    values=samples[:,:,0].sum(axis=1)/samples[:,:,1].sum(axis=1)
    lower=float(np.quantile(values,c['guard_lower_quantile']))
    return dict(allowed=bool(lower>=c['safe_probability']),races=len(observed),observed_safe=float(pd.DataFrame(observed).safe.mean()),lower=lower,seed=seed)

def record(g,part,policy,guard,c,threshold):
    decision=select_policy(policy,part['parent'],part['fusion'],part['exclusion'],part['context'],guard,c)
    sets,incidence=support(len(g));truth=set(sets[part['truth']]);p=decision['p']
    hard_error=bool(truth&set(decision['excluded']));pool_error=not truth<=set(decision['pool'])
    hit=int(part['truth'] in decision['best'])
    row=dict(race_key=part['race_key'],meet=int(g.meet.iloc[0]),race_date=str(g.race_date.iloc[0].date()),evaluation_year=part['year'],
        policy=policy,field_size=len(g),excluded_count=len(decision['excluded']),exclusion_possible=int(len(decision['excluded'])>0),
        exclusion_error=int(hard_error),exclusion_predicted_safe=decision['safe'],pool_size=len(decision['pool']),
        pool_covers_podium=int(not pool_error),pool_probability=decision['pool_mass'],trio6_hit=hit,trio6_probability=decision['mass'],
        selected=int(decision['mass']>=threshold),guard_allowed=guard,
        miss_hard_exclusion=int(hard_error),miss_outside_pool=int(not hard_error and pool_error),
        miss_inside_pool=int(not pool_error and not hit),
        parent_full_probability=float(np.sort(part['parent'])[-6:].sum()),fusion_full_probability=float(np.sort(part['fusion'])[-6:].sum()))
    combos=[]
    for rank,j in enumerate(decision['best'],1):
        combos.append(dict(race_key=part['race_key'],meet=int(g.meet.iloc[0]),evaluation_year=part['year'],policy=policy,selection_rank=rank,
            programs=','.join(map(str,sorted(g.program_no.iloc[sets[j]].astype(int)))),probability=float(p[j]),hit=int(j==part['truth'])))
    pool=dict(race_key=part['race_key'],policy=policy,excluded=','.join(map(str,sorted(g.program_no.iloc[decision['excluded']].astype(int)))),
        candidates=','.join(map(str,sorted(g.program_no.iloc[decision['pool']].astype(int)))))
    return row,combos,pool

def prepare():
    if OUT.exists():raise FileExistsError('Refusing existing outputs')
    paths=[HERE/'run.py',HERE/'PLAN.md',HERE/'config.json',ROOT/'config/prediction_model_registry.json',PARENT/'run.py',BASE.HERE/'run.py',PRE.STACK.HERE/'run.py',
        ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb']
    paths += [PARENT/'outputs'/n for n in ['features.parquet','feature_contract.json','runner_predictions.parquet','race_metrics.csv','recommendations.parquet','verification.json']]
    paths.append(STACK/'outputs/labels.parquet')
    for meet in (1,3):
        for year in (2024,2025,2026):
            paths+=list((STACK/'outputs/models'/f'{meet}_{year}_context').glob('*.txt'))
            paths.append(STACK/'outputs/models'/f'{meet}_{year}_context'/'metadata.json')
            for name in ['top3.txt','metadata.json','joint.json']:paths.append(PARENT/'outputs/models'/f'{meet}_{year}_upside'/name)
    hashes={str(p.relative_to(ROOT)):BASE.sha(p) for p in paths}
    f=pd.read_parquet(PARENT/'outputs/features.parquet');check=not f.duplicated(KEY).any()
    if not check:raise ValueError('Duplicate keys')
    OUT.mkdir();dump(OUT/'audit.json',{'inputs':hashes,'rows':len(f),'races':int(f.race_key.nunique()),'production_changed':False})
    print('Frozen parents:',len(paths),'files',flush=True)

def check_inputs():
    audit=json.loads((OUT/'audit.json').read_text())
    for path,h in audit['inputs'].items():
        if BASE.sha(ROOT/path)!=h:raise ValueError('Changed input: '+path)

def train():
    check_inputs();c=config()
    if (OUT/'summary.json').exists():raise FileExistsError('Completed study')
    frame=pd.read_parquet(PARENT/'outputs/features.parquet').merge(pd.read_parquet(STACK/'outputs/labels.parquet'),on=KEY,validate='one_to_one')
    rows=[];combos=[];pools=[];runner=[];fullmetrics=[];guards=[]
    for meet in c['venues']:
        f=frame[frame.meet.eq(meet)].reset_index(drop=True)
        for year in c['evaluation_years']:
            print(f'Train exclusion meet={meet} year={year}',flush=True)
            path=OUT/'models'/f'{meet}_{year}'
            if (path/'metadata.json').exists():
                meta=json.loads((path/'metadata.json').read_text());assert BASE.sha(path/'nonpodium.txt')==meta['model_sha256']
                raw=np.full(len(f),np.nan);mask=f.year.isin([year-1,year])
                raw[mask]=-lgb.Booster(model_file=str(path/'nonpodium.txt')).predict(encode(f,meta)[mask],raw_score=True,num_threads=4)
            else:
                raw,meta=fit_head(f,year,c,path);dump(path/'metadata.json',meta)
            parts=parent_parts(f,meet,year);cal=[p for p in parts if p['year']==year-1]
            energies=[raw[p['idx']][support(len(p['idx']))[0]].sum(axis=1) for p in cal];targets=[p['truth'] for p in cal]
            temp=fit_temperature(energies,targets,c)
            for part in parts:
                idx=part['idx'];part['date']=str(f.race_date.iloc[idx[0]].date());sets,_=support(len(idx))
                part['exclusion_energy']=raw[idx][sets].sum(axis=1)/temp
                part['exclusion']=normalized(part['exclusion_energy'])
                # Parent is already normalized; shifting its log probability is harmless.
                part['fusion_energy']=(1-c['fusion_weight'])*np.log(part['parent'])+c['fusion_weight']*np.log(part['exclusion'])
            fusion_temp=fit_temperature([p['fusion_energy'] for p in cal],targets,c)
            for part in parts:part['fusion']=normalized(part['fusion_energy']/fusion_temp)
            guard_seed=c['bootstrap_seed']+meet*10000+year;guard=fit_guard(cal,c,guard_seed)
            thresholds={}
            for policy in c['policies']:
                masses=[select_policy(policy,p['parent'],p['fusion'],p['exclusion'],p['context'],guard['allowed'],c)['mass'] for p in cal]
                thresholds[policy]=float(np.quantile(masses,c['selection_quantile']))
            meta.update(exclusion_temperature=temp,fusion_temperature=fusion_temp,fusion_weight=c['fusion_weight'],guard=guard,thresholds=thresholds)
            dump(path/'metadata.json',meta);guards.append(dict(meet=meet,year=year,**guard))
            for part in parts:
                if part['year']!=year:continue
                g=f.iloc[part['idx']];sets,incidence=support(len(g))
                for name in ['parent','exclusion','fusion']:
                    p=part[name];m=p@incidence;rank=np.argsort(-m,kind='stable')
                    fullmetrics.append(dict(race_key=part['race_key'],meet=meet,evaluation_year=year,race_date=part['date'],model=name,
                        trio_nll=float(-np.log(p[part['truth']])),top3_brier=float(np.mean((m-g.outcome.le(3).to_numpy())**2)),
                        top5_podium=int(set(sets[part['truth']])<=set(rank[:5])),top7_podium=int(set(sets[part['truth']])<=set(rank[:7]))))
                for i,(_,entry) in enumerate(g.iterrows()):
                    runner.append({**{key:entry[key] for key in KEY},'meet':meet,'evaluation_year':year,'outcome':int(entry.outcome),
                        'raw_exclusion_podium_score':float(raw[part['idx']][i]),'parent_top3':float((part['parent']@incidence)[i]),
                        'exclusion_top3':float((part['exclusion']@incidence)[i]),'fusion_top3':float((part['fusion']@incidence)[i]),'context_top3':float(part['context'][i])})
                for policy in c['policies']:
                    row,cs,pool=record(g,part,policy,guard['allowed'],c,thresholds[policy]);rows.append(row);combos+=cs;pools.append(pool)
            print(f'Evaluated {meet}/{year}; guard={guard}',flush=True)
    race=pd.DataFrame(rows);rec=pd.DataFrame(combos);rp=pd.DataFrame(runner);fm=pd.DataFrame(fullmetrics)
    race.to_csv(OUT/'race_metrics.csv',index=False);rec.to_parquet(OUT/'recommendations.parquet',index=False)
    rp.to_parquet(OUT/'runner_predictions.parquet',index=False);fm.to_csv(OUT/'full_distribution_metrics.csv',index=False)
    pd.DataFrame(pools).to_csv(OUT/'candidate_pools.csv',index=False);dump(OUT/'guards.json',guards)
    summarize(race,fm,c);check_inputs()
    dump(OUT/'summary.json',{'new_heads':6,'production_changed':False,'independent_future_test':False,
        'artifacts':{str(p.relative_to(OUT)):BASE.sha(p) for p in OUT.rglob('*') if p.is_file()}})
    print('Completed',flush=True)

def summarize(race,fm,c):
    rows=[]
    for (meet,policy),g in race.groupby(['meet','policy']):
        for period,s in [('all',g)]+[(str(y),p) for y,p in g.groupby('evaluation_year')]:
            active=s[s.exclusion_possible.eq(1)];keep=s[s.selected.eq(1)]
            rows.append(dict(meet=int(meet),policy=policy,period=period,races=len(s),trio6_hit=float(s.trio6_hit.mean()),
                pool_covers_podium=float(s.pool_covers_podium.mean()),mean_pool_size=float(s.pool_size.mean()),
                exclusion_races=len(active),mean_excluded=float(s.excluded_count.mean()),wrong_exclusion_races=int(s.exclusion_error.sum()),
                active_safe=None if not len(active) else float(1-active.exclusion_error.mean()),
                mean_probability=float(s.trio6_probability.mean()),selected=len(keep),selection_rate=len(keep)/len(s),
                selected_hit=float(keep.trio6_hit.mean()),selected_hits=int(keep.trio6_hit.sum()),total_hits=int(s.trio6_hit.sum()),
                hard_misses=int(s.miss_hard_exclusion.sum()),pool_misses=int(s.miss_outside_pool.sum()),inside_misses=int(s.miss_inside_pool.sum())))
    table=pd.DataFrame(rows);table.to_csv(OUT/'metrics.csv',index=False)
    fm.groupby(['meet','model'])[['trio_nll','top3_brier','top5_podium','top7_podium']].mean().to_csv(OUT/'full_metrics.csv')
    pairs=[('parent_full','fusion_full'),('parent_full','parent_top7'),('parent_full','parent_safe_top7'),
        ('fusion_full','fusion_top6'),('fusion_full','fusion_top7'),('fusion_full','fusion_safe_top7'),
        ('fusion_full','fusion_guarded_union7'),('parent_full','fusion_guarded_union7')]
    rng=np.random.default_rng(c['bootstrap_seed']);differences=[]
    for meet in (1,3):
        for a,b in pairs:
            left=race[race.meet.eq(meet)&race.policy.eq(a)];right=race[race.meet.eq(meet)&race.policy.eq(b)]
            p=left.merge(right,on='race_key',suffixes=('_a','_b'),validate='one_to_one');assert len(p)==len(left)==len(right)
            for metric in ['trio6_hit','pool_covers_podium','exclusion_error']:
                delta=p[metric+'_b']-p[metric+'_a']
                daily=pd.DataFrame({'day':p.race_date_a,'delta':delta}).groupby('day').delta.agg(['sum','size']).to_numpy()
                picks=rng.integers(0,len(daily),size=(c['bootstrap_draws'],len(daily)));samples=daily[picks]
                ci=np.quantile(samples[:,:,0].sum(axis=1)/samples[:,:,1].sum(axis=1),[.025,.975])
                differences.append(dict(meet=meet,base=a,candidate=b,metric=metric,difference=float(delta.mean()),date_bootstrap_95_interval=ci.tolist()))
    dump(OUT/'paired_differences.json',differences)
    calibration=[]
    for (meet,policy),g in race.groupby(['meet','policy']):
        for bin,s in g.groupby(np.minimum((g.trio6_probability*10).astype(int),9)):
            calibration.append(dict(meet=int(meet),policy=policy,bin=int(bin),races=len(s),predicted=float(s.trio6_probability.mean()),actual=float(s.trio6_hit.mean())))
    pd.DataFrame(calibration).to_csv(OUT/'trio6_calibration.csv',index=False)
    assert (race.trio6_hit+race.miss_hard_exclusion+race.miss_outside_pool+race.miss_inside_pool).eq(1).all()
    print(table[table.period.eq('all')].to_string(index=False),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','train']);args=parser.parse_args()
    {'prepare':prepare,'train':train}[args.mode]()
