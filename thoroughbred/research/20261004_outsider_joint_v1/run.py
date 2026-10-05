"""Frozen time-forward podium/interaction study. No production mutations."""
from __future__ import annotations
import argparse
from functools import lru_cache
import importlib.util
import itertools
import json
from pathlib import Path
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.special import logsumexp

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE/'outputs'
PARENT = HERE.parent/'20261004_pace_finish_stack_v1'
spec = importlib.util.spec_from_file_location('outsider_stack_parent', PARENT/'run.py')
STACK = importlib.util.module_from_spec(spec); spec.loader.exec_module(STACK)
BASE, KEY = STACK.BASE, STACK.KEY
PAIR_NAMES = ['front_pair', 'front_pair_pressure', 'lead_pair_pressure', 'style_distance',
    'style_distance_long', 'front_closing_balance', 'closing_pair', 'upside_pair',
    'low_history_pair', 'low_history_trial_pair', 'gate_front_pair', 'gate_style_distance']

def config(): return json.loads((HERE/'config.json').read_text())
def dump(p,v): BASE.save_json(p,v)

def upside_features(frame):
    f = frame.copy()
    def relative(col):
        values = f[col]
        sums = values.groupby(f.race_key).transform('sum')
        counts = values.groupby(f.race_key).transform('count')
        return values-(sums-values.fillna(0))/(counts-values.notna().astype(int)).replace(0,np.nan)
    def rank(col, high=True):
        x = f[col].groupby(f.race_key).rank(ascending=not high,method='average')
        counts = f[col].groupby(f.race_key).transform('count')
        return (1-(x-1)/(counts-1).replace(0,np.nan)).where(counts.gt(1))
    f['upside_best_gap'] = f.last5_record_index_best-f.last3_record_index_mean
    f['upside_best_relative'] = relative('last5_record_index_best')
    f['upside_best_rank'] = rank('last5_record_index_best')
    f['upside_last_rank'] = rank('last_record_index')
    f['upside_closing_rank'] = rank('last3_last_600_mean',False)
    f['upside_start_rank'] = rank('last3_start_200_mean',False)
    f['upside_trial_rank'] = rank('trial_last3_session_delta',False)
    f['upside_balance'] = f.upside_closing_rank-f.upside_start_rank
    f['upside_low_history'] = 1/(1+f.history_count)
    f['upside_record_count'] = f.last5_record_index_count/5
    f['upside_low_history_trial'] = f.upside_low_history*f.upside_trial_rank
    f['upside_low_history_best'] = f.upside_low_history*f.upside_best_relative
    f['upside_growth'] = f.record_index_change*(f.previous_age.le(4).where(f.previous_age.notna()).astype(float))
    f['upside_distance_closing'] = (f.distance_change/400).clip(-2,2)*f.upside_balance
    f['upside_grade_best'] = f.context_grade_change.clip(-2,2)*f.upside_best_relative
    f['upside_pressure'] = (f.conditioned_band_S1F_front.groupby(f.race_key).transform('sum')-f.conditioned_band_S1F_front)/(f.field_size-1)
    f['upside_pressure_closing'] = f.upside_pressure*f.upside_closing_rank
    f['upside_pressure_front'] = f.upside_pressure*f.conditioned_band_S1F_front
    return f, [c for c in f if c.startswith('upside_')]

@lru_cache(maxsize=32)
def templates(n):
    trios = np.array(list(itertools.combinations(range(n),3)),int)
    orders = BASE.permutation_indices(n)
    lookup = {tuple(t):i for i,t in enumerate(trios)}
    mapping = np.array([lookup[tuple(sorted(o))] for o in orders],int)
    return trios, orders, mapping

def pair_design(g):
    """Historical style and ex ante field proxies only; never current outcome."""
    trios,_,_ = templates(len(g))
    def a(col,fill=0.): return g[col].fillna(fill).to_numpy(float)
    front = a('conditioned_band_S1F_front')
    lead = a('conditioned_band_S1F_lead')
    style = a('conditioned_band_S1F_fraction',.5)
    closing = a('upside_closing_rank',.5)
    potential = a('upside_best_relative').clip(-3,3)/3
    low = a('upside_low_history')
    trial = a('upside_trial_rank',.5)
    gate = a('gate_fraction_proxy',.5)
    pressure = float(front.mean())
    long = float(np.clip((g.distance_m.iloc[0]-1300)/500,-1,2))
    features = np.zeros((len(trios),len(PAIR_NAMES)))
    for p,q in ((0,1),(0,2),(1,2)):
        i,j = trios[:,p],trios[:,q]
        features += np.column_stack([front[i]*front[j],front[i]*front[j]*pressure,
            lead[i]*lead[j]*pressure,abs(style[i]-style[j]),abs(style[i]-style[j])*long,
            front[i]*closing[j]+front[j]*closing[i],closing[i]*closing[j],potential[i]*potential[j],
            low[i]*low[j],low[i]*trial[j]+low[j]*trial[i],
            gate[i]*gate[j]*front[i]*front[j],abs(gate[i]-gate[j])*abs(style[i]-style[j])])/3
    return features

def race_parts(frame, scores):
    parts = []
    for rid,idx in frame.groupby('race_key',sort=False).indices.items():
        g = frame.iloc[idx]
        sets,_,_ = templates(len(g))
        truth = tuple(np.flatnonzero(g.outcome.le(3).to_numpy()))
        target = next(i for i,s in enumerate(sets) if tuple(s)==truth)
        parts.append({'race_key':rid,'energy':scores[idx][sets].sum(axis=1),'X':pair_design(g),'target':target})
    return parts

def temperature(parts,c):
    width = max(len(p['energy']) for p in parts)
    matrix = np.full((len(parts),width),-np.inf)
    actual = np.array([p['energy'][p['target']] for p in parts])
    for i,p in enumerate(parts): matrix[i,:len(p['energy'])] = p['energy']
    fit = minimize_scalar(lambda t:float(np.mean(logsumexp(matrix/t,axis=1)-actual/t)),bounds=c['temperature_bounds'],method='bounded')
    if not fit.success: raise ValueError('Temperature failed')
    return float(fit.x)

def residual_fit(parts,t,c):
    mean = np.mean([p['X'].mean(axis=0) for p in parts],axis=0)
    variance = np.mean([((p['X']-mean)**2).mean(axis=0) for p in parts],axis=0)
    scale = np.maximum(np.sqrt(variance),.05)
    width = max(len(p['energy']) for p in parts)
    e = np.full((len(parts),width),-np.inf)
    x = np.zeros((len(parts),width,len(PAIR_NAMES)))
    truth = np.array([p['target'] for p in parts]); row = np.arange(len(parts))
    for i,p in enumerate(parts):
        e[i,:len(p['energy'])] = p['energy']; x[i,:len(p['energy'])] = (p['X']-mean)/scale
    strength = c['pair_prior_races']/len(parts)
    def loss(theta):
        temp = np.exp(theta[0]); beta=theta[1:]
        energy = e/temp+np.einsum('rcf,f->rc',x,beta)
        norm = logsumexp(energy,axis=1)
        prob = np.exp(energy-norm[:,None]); delta=prob.copy();delta[row,truth]-=1
        value = float(np.mean(norm-energy[row,truth])+.5*strength*(beta@beta))
        g0 = float(np.mean((np.sum(prob*np.where(np.isfinite(e),e,0),axis=1)-e[row,truth])/(-temp)))
        gb = np.einsum('rc,rcf->f',delta,x)/len(parts)+strength*beta
        return value,np.r_[g0,gb]
    initial = np.r_[np.log(t),np.zeros(len(PAIR_NAMES))]
    bounds = [(np.log(c['temperature_bounds'][0]),np.log(c['temperature_bounds'][1]))]+[(-c['pair_coefficient_bound'],c['pair_coefficient_bound'])]*len(PAIR_NAMES)
    result = minimize(loss,initial,jac=True,method='L-BFGS-B',bounds=bounds,
        options={'maxiter':c['pair_max_iterations'],'ftol':1e-11,'gtol':1e-7})
    if not result.success: raise ValueError('Pair optimization failed: '+result.message)
    return dict(temperature=float(np.exp(result.x[0])),coefficients=result.x[1:].tolist(),
        mean=mean.tolist(),scale=scale.tolist(),features=PAIR_NAMES,penalty=strength,
        iterations=int(result.nit),loss=float(result.fun),success=True)

def direct_train(f,cols,year,c,path):
    path.mkdir(parents=True,exist_ok=False)
    train=f.year.between(c['training_start_year'],year-3); valid=f.year.eq(year-2)
    cal=f.year.eq(year-1); test=f.year.eq(year)
    assert all(mask.any() for mask in (train,valid,cal,test))
    x,vocab=BASE.category_encode(f,train,cols)
    y=f.outcome.le(3).astype(int);weights=1/f.field_size
    params=c['training'].copy();rounds=params.pop('max_rounds');early=params.pop('early_stopping_rounds');params['seed']=c['seed']
    def dataset(mask): return lgb.Dataset(x[mask],label=y[mask],weight=weights[mask],free_raw_data=False)
    initial=lgb.train(params,dataset(train),num_boost_round=rounds,valid_sets=[dataset(valid)],callbacks=[lgb.early_stopping(early,verbose=False)])
    model=lgb.train(params,dataset(train|valid),num_boost_round=initial.best_iteration)
    model.save_model(str(path/'top3.txt'))
    score=np.full(len(f),np.nan)
    for mask in (cal,test):score[mask]=model.predict(x[mask],raw_score=True,num_threads=4)
    meta=dict(evaluation_year=year,training_min='2017-01-01',train_end=str(f.loc[train|valid,'race_date'].max().date()),
        validation_year=year-2,calibration_year=year-1,features=cols,category_vocabulary=vocab,
        trees=int(initial.best_iteration),target='outcome<=3',model_sha256=BASE.sha(path/'top3.txt'),
        gain=dict(zip(cols,model.feature_importance(importance_type='gain').astype(float))))
    return score,meta

def baseline_scores(f,meet,year):
    path=PARENT/'outputs/models'/f'{meet}_{year}_context'
    meta=json.loads((path/'metadata.json').read_text())
    x=f[meta['features']].copy()
    for col,vocab in meta['category_vocabulary'].items():x[col]=pd.Categorical(x[col],categories=vocab)
    scores=np.full((len(f),3),np.nan)
    mask=f.year.isin([year-1,year])
    for stage in range(3):scores[mask,stage]=lgb.Booster(model_file=str(path/f'position_{stage+1}.txt')).predict(x[mask],raw_score=True,num_threads=4)
    return scores,meta

def distribution(g,base_scores,base_temps,variant,raw,t,pair=None):
    ix,q,margins=BASE.joint(base_scores,base_temps)
    if variant=='context':return ix,q,margins
    sets,_,mapping=templates(len(g))
    energies=raw[sets].sum(axis=1)/t
    if pair is not None:energies+=((pair_design(g)-np.array(pair['mean']))/np.array(pair['scale']))@np.array(pair['coefficients'])
    set_p=np.exp(energies-logsumexp(energies))
    base_set_p=np.bincount(mapping,weights=q,minlength=len(sets))
    q=q/base_set_p[mapping]*set_p[mapping]
    pos=np.stack([np.bincount(ix[:,s],weights=q,minlength=len(g)) for s in range(3)],axis=1)
    return ix,q,pos.cumsum(axis=1)

def evaluate(f,base_scores,base_temps,variant,raw,t,pair=None,threshold=None):
    runners,races,recs=[],[],[]
    masses=[]
    for rid,idx in f.groupby('race_key',sort=False).indices.items():
        g=f.iloc[idx];n=len(g)
        ix,q,m=distribution(g,base_scores[idx],base_temps,variant,None if raw is None else raw[idx],t,pair)
        _,baseq,basem=BASE.joint(base_scores[idx],base_temps)
        pairidx,trios,qnl,qpl,p=BASE.pool_probabilities(ix,q,n)
        truth=[int(np.flatnonzero(g.outcome.to_numpy()==k)[0]) for k in (1,2,3)]
        target=next(j for j,s in enumerate(trios) if set(s)==set(truth))
        best=np.argsort(-p,kind='stable')[:6];mass=float(p[best].sum());masses.append(mass)
        if threshold is False:continue
        rank=np.argsort(-m[:,2],kind='stable');base_rank=np.argsort(-basem[:,2],kind='stable')
        outsiders=set(truth)-set(base_rank[:5]);insiders=set(truth)&set(base_rank[:5])
        row=dict(race_key=rid,meet=int(g.meet.iloc[0]),race_date=str(g.race_date.iloc[0].date()),evaluation_year=int(g.year.iloc[0]),
            variant=variant,field_size=n,grade=float(g.grade.iloc[0]),distance_band=float(g.distance_band.iloc[0]),
            low_history_present=bool(g.history_count.lt(5).any()),extended_present=bool(g.distance_change.gt(0).any()),
            trio_nll=float(-np.log(p[target])),ordered_top3_nll=float(-np.log(q[np.all(ix==truth,axis=1)].sum())),
            top6_trio_hit=int(target in best),top6_trio_probability=mass,
            top3_first_hit=int(rank[0] in truth),axis_win_hit=int(m[:,0].argmax()==truth[0]),
            baseline_outsiders=len(outsiders),rescued_outsiders=len(outsiders&set(rank[:5])),
            lost_insiders=len(insiders-set(rank[:5])),
            selected=int(mass>=threshold) if threshold is not None else 1)
        for k in (3,5,6,7):row[f'top{k}_contains_podium']=int(set(truth)<=set(rank[:k]))
        for k in range(3):row[f'top{k+1}_brier'],row[f'top{k+1}_logloss']=BASE.binary_metrics(m[:,k],g.outcome.le(k+1).astype(int).to_numpy())
        row['joint_error']=float(abs(q.sum()-1));row['marginal_error']=float(abs(m.sum(axis=0)-[1,2,3]).max())
        races.append(row)
        for j,(_,r) in enumerate(g.iterrows()):
            runners.append({**{c:r[c] for c in KEY},'meet':int(r.meet),'race_date':r.race_date,'evaluation_year':int(r.year),
                'variant':variant,'outcome':int(r.outcome),'prob_win':float(m[j,0]),'prob_top2':float(m[j,1]),'prob_top3':float(m[j,2]),
                'baseline_top5':int(j in base_rank[:5]),'new_top5':int(j in rank[:5]),
                'raw_top3_score':None if raw is None else float(raw[idx][j])})
        for order,j in enumerate(best,1):recs.append(dict(race_key=rid,meet=int(g.meet.iloc[0]),evaluation_year=int(g.year.iloc[0]),variant=variant,
            selection_rank=order,programs=','.join(map(str,sorted(g.program_no.iloc[trios[j]].astype(int)))),
            probability=float(p[j]),hit=int(j==target)))
    return pd.DataFrame(runners),pd.DataFrame(races),pd.DataFrame(recs),masses

def prepare():
    if OUT.exists():raise FileExistsError('Refusing existing outputs')
    c=config()
    paths=[HERE/'run.py',HERE/'config.json',HERE/'PLAN.md',ROOT/'config/prediction_model_registry.json',
        ROOT/'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb',PARENT/'run.py',BASE.HERE/'run.py']
    paths += [PARENT/'outputs'/n for n in ['features.parquet','labels.parquet','feature_contract.json','runner_predictions.parquet','race_metrics.csv','recommendations.parquet']]
    for meet in c['venues']:
        for year in c['evaluation_years']:
            paths+=list((PARENT/'outputs/models'/f'{meet}_{year}_context').glob('*.txt'))
            paths.append(PARENT/'outputs/models'/f'{meet}_{year}_context'/'metadata.json')
    hashes={str(p.relative_to(ROOT)):BASE.sha(p) for p in paths}
    f=pd.read_parquet(PARENT/'outputs/features.parquet')
    f,extra=upside_features(f)
    contract=json.loads((PARENT/'outputs/feature_contract.json').read_text())['context']
    assert not set(contract+extra)&STACK.forbidden_columns()
    assert not f.duplicated(KEY).any()
    OUT.mkdir();f.to_parquet(OUT/'features.parquet',index=False)
    dump(OUT/'feature_contract.json',{'direct':contract,'upside':contract+extra,'extra':extra,'pairs':PAIR_NAMES})
    dump(OUT/'audit.json',{'inputs':hashes,'rows':len(f),'races':int(f.race_key.nunique()),
        'feature_sha256':BASE.sha(OUT/'features.parquet'),'future_independent':False,'production_changed':False})
    print('Prepared',len(f),'rows; new features',len(extra),flush=True)

def check_inputs():
    audit=json.loads((OUT/'audit.json').read_text())
    for path,h in audit['inputs'].items():
        if BASE.sha(ROOT/path)!=h:raise ValueError('Changed input: '+path)
    if BASE.sha(OUT/'features.parquet')!=audit['feature_sha256']:raise ValueError('Changed prepared data')

def train():
    check_inputs();c=config()
    if (OUT/'summary.json').exists():raise FileExistsError('Completed study')
    f=pd.read_parquet(OUT/'features.parquet').merge(pd.read_parquet(PARENT/'outputs/labels.parquet'),on=KEY,validate='one_to_one')
    contracts=json.loads((OUT/'feature_contract.json').read_text())
    allr,alle,allc,metas=[],[],[],[]
    for meet in c['venues']:
        one=f[f.meet.eq(meet)].reset_index(drop=True)
        for year in c['evaluation_years']:
            scores,bmeta=baseline_scores(one,meet,year)
            cal=one.year.eq(year-1);test=one.year.eq(year)
            raw_map={'context':None};temp_map={'context':1.};pair_map={}
            for variant in ['direct','upside']:
                path=OUT/'models'/f'{meet}_{year}_{variant}'
                if (path/'metadata.json').exists():
                    meta=json.loads((path/'metadata.json').read_text());assert BASE.sha(path/'top3.txt')==meta['model_sha256']
                    x=one[meta['features']].copy()
                    for col,v in meta['category_vocabulary'].items():x[col]=pd.Categorical(x[col],categories=v)
                    raw=np.full(len(one),np.nan);mask=cal|test
                    raw[mask]=lgb.Booster(model_file=str(path/'top3.txt')).predict(x[mask],raw_score=True,num_threads=4)
                    temp=meta['temperature']
                else:
                    print(f'Train meet={meet} year={year} {variant}',flush=True)
                    raw,meta=direct_train(one,contracts[variant],year,c,path)
                    parts=race_parts(one[cal].reset_index(drop=True),raw[cal]);temp=temperature(parts,c)
                    meta['temperature']=temp;dump(path/'metadata.json',meta)
                raw_map[variant]=raw;temp_map[variant]=temp;metas.append({'meet':meet,'variant':variant,**meta})
            print(f'Fit joint meet={meet} year={year}',flush=True)
            parts=race_parts(one[cal].reset_index(drop=True),raw_map['upside'][cal])
            pair=residual_fit(parts,temp_map['upside'],c)
            dump(OUT/'models'/f'{meet}_{year}_upside'/'joint.json',{**pair,'training_year':year-1,'training_rows':int(cal.sum()),'evaluation_year':year})
            raw_map['upside_joint']=raw_map['upside'];temp_map['upside_joint']=pair['temperature'];pair_map['upside_joint']=pair
            for variant in c['variants']:
                _,_,_,masses=evaluate(one[cal].reset_index(drop=True),scores[cal],bmeta['temperatures'],variant,
                    None if raw_map[variant] is None else raw_map[variant][cal],temp_map[variant],pair_map.get(variant),False)
                threshold=float(np.quantile(masses,c['selective_calibration_quantile']))
                rp,rm,rec,_=evaluate(one[test].reset_index(drop=True),scores[test],bmeta['temperatures'],variant,
                    None if raw_map[variant] is None else raw_map[variant][test],temp_map[variant],pair_map.get(variant),threshold)
                allr.append(rp);alle.append(rm);allc.append(rec)
                dump(OUT/'models'/f'{meet}_{year}_upside'/f'{variant}_selection.json',{'calibration_year':year-1,'threshold':threshold,'races':len(masses),'quantile':c['selective_calibration_quantile']})
            print(f'Evaluated meet={meet} year={year}',flush=True)
    rp=pd.concat(allr,ignore_index=True);rm=pd.concat(alle,ignore_index=True);rec=pd.concat(allc,ignore_index=True)
    rp.to_parquet(OUT/'runner_predictions.parquet',index=False);rm.to_csv(OUT/'race_metrics.csv',index=False);rec.to_parquet(OUT/'recommendations.parquet',index=False)
    summarize(rp,rm,c)
    diagnostics(f,rp)
    check_inputs()
    dump(OUT/'summary.json',{'models':metas,'production_changed':False,'independent_future_test':False,
        'artifacts':{str(p.relative_to(OUT)):BASE.sha(p) for p in OUT.rglob('*') if p.is_file()}})
    print('Completed',flush=True)

def summarize(rp,rm,c):
    metrics=['trio_nll','top3_brier','top6_trio_hit','top3_first_hit','top3_contains_podium','top5_contains_podium','top6_contains_podium','top7_contains_podium']
    rows=[];selected=[]
    for (meet,variant),g in rm.groupby(['meet','variant']):
        for period,s in [('all',g)]+[(str(y),p) for y,p in g.groupby('evaluation_year')]:
            rows.append(dict(meet=int(meet),variant=variant,period=period,races=len(s),**{m:float(s[m].mean()) for m in metrics},
                rescued_outsiders=int(s.rescued_outsiders.sum()),lost_insiders=int(s.lost_insiders.sum()),baseline_outsiders=int(s.baseline_outsiders.sum()),
                mean_6_probability=float(s.top6_trio_probability.mean())))
            keep=s[s.selected.eq(1)]
            selected.append(dict(meet=int(meet),variant=variant,period=period,races=len(s),selected=len(keep),selection_rate=len(keep)/len(s),
                selected_hit_rate=float(keep.top6_trio_hit.mean()),all_hit_rate=float(s.top6_trio_hit.mean()),
                hits_kept=int(keep.top6_trio_hit.sum()),total_hits=int(s.top6_trio_hit.sum()),mean_selected_probability=float(keep.top6_trio_probability.mean())))
    summary=pd.DataFrame(rows);summary.to_csv(OUT/'metrics.csv',index=False);pd.DataFrame(selected).to_csv(OUT/'selection_metrics.csv',index=False)
    differences=[];rng=np.random.default_rng(c['seed'])
    for meet in c['venues']:
        for a,b in [('context','direct'),('direct','upside'),('upside','upside_joint'),('context','upside'),('context','upside_joint')]:
            left=rm[rm.meet.eq(meet)&rm.variant.eq(a)];right=rm[rm.meet.eq(meet)&rm.variant.eq(b)]
            p=left.merge(right,on='race_key',suffixes=('_a','_b'),validate='one_to_one');assert len(p)==len(left)==len(right)
            for metric in metrics:
                delta=p[metric+'_b']-p[metric+'_a']
                daily=pd.DataFrame({'date':p.race_date_a,'delta':delta}).groupby('date').delta.agg(['sum','size']).to_numpy()
                picks=rng.integers(0,len(daily),size=(c['bootstrap_draws'],len(daily)));draws=daily[picks]
                ci=np.quantile(draws[:,:,0].sum(axis=1)/draws[:,:,1].sum(axis=1),[.025,.975])
                differences.append(dict(meet=meet,base=a,candidate=b,metric=metric,difference=float(delta.mean()),date_bootstrap_95_interval=ci.tolist()))
    dump(OUT/'paired_differences.json',differences)
    bins=[]
    for (meet,variant),g in rm.groupby(['meet','variant']):
        for b,s in g.groupby(np.minimum((g.top6_trio_probability*10).astype(int),9)):
            bins.append(dict(meet=int(meet),variant=variant,bin=int(b),races=len(s),mean_probability=float(s.top6_trio_probability.mean()),hit_rate=float(s.top6_trio_hit.mean())))
    pd.DataFrame(bins).to_csv(OUT/'trio6_calibration.csv',index=False)
    for col in ['grade','distance_band','low_history_present','extended_present']:
        groups=rm.groupby(['meet','variant',col],dropna=False);table=groups[metrics].mean();table['races']=groups.size();table.to_csv(OUT/(col+'_metrics.csv'))
    print(summary[summary.period.eq('all')].to_string(index=False),flush=True)

def diagnostics(f,rp):
    baseline=rp[rp.variant.eq('context')].merge(f,on=KEY,validate='one_to_one',suffixes=('','_feature'))
    baseline=baseline[baseline.baseline_top5.eq(0)].copy()
    flags={'history_lt5':baseline.history_count.lt(5),'best_vs_recent_gt1':baseline.upside_best_gap.gt(1),
        'record_change_gt1':baseline.record_index_change.gt(1),'closing_rank_top30':baseline.upside_closing_rank.ge(.7),
        'trial_rank_top30':baseline.upside_trial_rank.ge(.7),'distance_extended':baseline.distance_change.gt(0),
        'distance_shortened':baseline.distance_change.lt(0),'grade_change':baseline.context_grade_change.ne(0)&baseline.context_grade_change.notna(),
        'high_front_pressure':baseline.upside_pressure.ge(.35)}
    rows=[]
    for meet,g in baseline.groupby('meet'):
        for signal,flag in flags.items():
            for present in (False,True):
                s=g[flag.loc[g.index].eq(present)]
                rows.append(dict(meet=int(meet),signal=signal,present=present,runners=len(s),podium_runners=int(s.outcome.le(3).sum()),
                    podium_rate=float(s.outcome.le(3).mean()),missing_not_separately_identified=True))
    pd.DataFrame(rows).to_csv(OUT/'outsider_signal_diagnostics.csv',index=False)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','train']);args=parser.parse_args()
    {'prepare':prepare,'train':train}[args.mode]()
