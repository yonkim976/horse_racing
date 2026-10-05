"""Independent full-support calculation, frozen provenance, and replay checks."""
from pathlib import Path
import itertools
from functools import lru_cache
import json
import hashlib
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OUT=HERE/'outputs'
PARENT=HERE.parent/'20261004_pace_finish_stack_v1/outputs'
KEY=['race_key','program_no','horse_id']
checks=0;max_error=0.

def check(condition,message=''):
    global checks
    checks+=1
    if not condition:raise AssertionError(f'{checks}: {message}')

def close(a,b,tolerance=2e-11):
    global max_error
    error=float(np.max(np.abs(np.asarray(a)-np.asarray(b))))
    max_error=max(max_error,error);check(error<tolerance,f'numeric error {error}')

def sha(p):
    with p.open('rb') as file:return hashlib.file_digest(file,'sha256').hexdigest()

@lru_cache(maxsize=32)
def support(n):
    sets=np.array(list(itertools.combinations(range(n),3)))
    orders=np.array(list(itertools.permutations(range(n),3)))
    lookup={tuple(s):i for i,s in enumerate(sets)}
    mapping=np.array([lookup[tuple(sorted(x))] for x in orders])
    return sets,orders,mapping

def baseline_q(raw,temps):
    _,orders,_=support(len(raw));weights=np.exp((raw-raw.max(axis=0))/temps)
    n=len(raw);ids=np.arange(n)
    second=np.array([weights[ids!=i,1].sum() for i in ids])
    third=np.array([[weights[(ids!=i)&(ids!=j),2].sum() for j in ids] for i in ids])
    i,j,k=orders.T
    return weights[i,0]/weights[:,0].sum()*weights[j,1]/second[i]*weights[k,2]/third[i,j]

def design(g):
    sets,_,_=support(len(g))
    def a(col,fill=0):return g[col].fillna(fill).to_numpy(float)[sets]
    front=a('conditioned_band_S1F_front');lead=a('conditioned_band_S1F_lead')
    style=a('conditioned_band_S1F_fraction',.5);closing=a('upside_closing_rank',.5)
    potential=a('upside_best_relative').clip(-3,3)/3
    low=a('upside_low_history');trial=a('upside_trial_rank',.5);gate=a('gate_fraction_proxy',.5)
    def products(x):return (x.sum(axis=1)**2-(x*x).sum(axis=1))/6
    def cross(x,y):return (x.sum(axis=1)*y.sum(axis=1)-(x*y).sum(axis=1))/3
    pressure=float(g.conditioned_band_S1F_front.fillna(0).mean())
    long=float(np.clip((g.distance_m.iloc[0]-1300)/500,-1,2))
    distance=2*np.ptp(style,axis=1)/3
    gate_style=sum(abs(gate[:,i]-gate[:,j])*abs(style[:,i]-style[:,j]) for i,j in ((0,1),(0,2),(1,2)))/3
    return np.column_stack([products(front),products(front)*pressure,products(lead)*pressure,distance,distance*long,
        cross(front,closing),products(closing),products(potential),products(low),cross(low,trial),products(gate*front),gate_style])

def load_raw(g,path,name):
    meta=json.loads((path/'metadata.json').read_text())
    check(meta['evaluation_year']==int(g.year.max()))
    check(pd.Timestamp(meta.get('train_end',str(meta.get('final_training_year_end'))+'-12-31'))<pd.Timestamp(int(g.year.max())-1,1,1))
    x=g[meta.get('features')].copy()
    for col,v in meta['category_vocabulary'].items():x[col]=pd.Categorical(x[col],categories=v)
    if name=='context':
        values=np.column_stack([lgb.Booster(model_file=str(path/f'position_{i}.txt')).predict(x,raw_score=True,num_threads=4) for i in (1,2,3)])
    else:
        check(sha(path/'top3.txt')==meta['model_sha256'])
        model=lgb.Booster(model_file=str(path/'top3.txt'));check(model.num_trees()==meta['trees'])
        values=model.predict(x,raw_score=True,num_threads=4)
    return values,meta

def new_probability(g,raw,meta,joint=None):
    sets,_,_=support(len(g))
    temp=meta['temperature'] if joint is None else joint['temperature']
    energy=raw[sets].sum(axis=1)/temp
    if joint is not None:energy+=((design(g)-joint['mean'])/joint['scale'])@np.array(joint['coefficients'])
    return np.exp(energy-logsumexp(energy))

def main():
    audit=json.loads((OUT/'audit.json').read_text());summary=json.loads((OUT/'summary.json').read_text())
    for path,h in audit['inputs'].items():check(sha(ROOT/path)==h,path)
    check(sha(OUT/'features.parquet')==audit['feature_sha256'])
    for path,h in summary['artifacts'].items():check(sha(OUT/path)==h,path)
    f=pd.read_parquet(OUT/'features.parquet').merge(pd.read_parquet(PARENT/'labels.parquet'),on=KEY,validate='one_to_one')
    runners=pd.read_parquet(OUT/'runner_predictions.parquet')
    recs=pd.read_parquet(OUT/'recommendations.parquet');races=pd.read_csv(OUT/'race_metrics.csv')
    check(races.groupby('variant').race_key.nunique().to_dict()=={x:4799 for x in ['context','direct','upside','upside_joint']})
    # Actual current section labels and target identifiers cannot enter heads.
    forbidden={'outcome','horse_id','race_date','race_key','program_no','year','S1F_rank','G3F_rank','S1F_fraction','G3F_fraction'}
    contract=json.loads((OUT/'feature_contract.json').read_text())
    check(not set(contract['upside'])&forbidden)
    for col in f.columns:
        if col.endswith(('source_date','history_source_date')):
            date=pd.to_datetime(f[col]);check((date.isna()|date.le(f.race_date-pd.Timedelta(days=2))).all(),col)
    # Baseline runner probabilities exactly replay the preserved reference cohort.
    old=pd.read_parquet(PARENT/'runner_predictions.parquet');old=old[old.variant.eq('context')]
    new=runners[runners.variant.eq('context')]
    p=old.merge(new,on=KEY,validate='one_to_one',suffixes=('_old','_new'));check(len(p)==50754)
    for col in ('prob_win','prob_top2','prob_top3'):close(p[col+'_old'],p[col+'_new'])
    cg=dict(tuple(recs.groupby(['meet','evaluation_year','variant','race_key'])))
    rg=dict(tuple(runners.groupby(['meet','evaluation_year','variant','race_key'])))
    eg=races.set_index(['meet','evaluation_year','variant','race_key'])
    for meet in (1,3):
        for year in (2024,2025,2026):
            data=f[f.meet.eq(meet)&f.year.isin([year-1,year])].reset_index(drop=True)
            rawb,mb=load_raw(data,PARENT/'models'/f'{meet}_{year}_context','context')
            direct,md=load_raw(data,OUT/'models'/f'{meet}_{year}_direct','direct')
            upside,mu=load_raw(data,OUT/'models'/f'{meet}_{year}_upside','upside')
            joint=json.loads((OUT/'models'/f'{meet}_{year}_upside'/'joint.json').read_text())
            check(joint['training_year']==year-1);check(joint['evaluation_year']==year)
            check(max(abs(np.array(joint['coefficients'])))<=1+1e-12);check(joint['success'])
            check(len(contract['pairs'])==len(joint['coefficients'])==12)
            calibration={v:[] for v in ['context','direct','upside','upside_joint']}
            cal_energy={'direct':[],'upside':[]};cal_target=[];fit_loss=[]
            for rid,idx in data.groupby('race_key',sort=False).indices.items():
                g=data.iloc[idx];n=len(g);sets,orders,mapping=support(n)
                bq=baseline_q(rawb[idx],np.array(mb['temperatures']))
                bp=np.bincount(mapping,weights=bq,minlength=len(sets))
                actual=set(np.flatnonzero(g.outcome.le(3).to_numpy()))
                target=next(i for i,s in enumerate(sets) if set(s)==actual)
                probs={'context':bp,'direct':new_probability(g,direct[idx],md),
                    'upside':new_probability(g,upside[idx],mu),'upside_joint':new_probability(g,upside[idx],mu,joint)}
                if int(g.year.iloc[0])==year-1:
                    for variant,p in probs.items():calibration[variant].append(float(np.sort(p)[-6:].sum()))
                    cal_energy['direct'].append(direct[idx][sets].sum(axis=1));cal_energy['upside'].append(upside[idx][sets].sum(axis=1));cal_target.append(target)
                    fit_loss.append(-np.log(probs['upside_joint'][target]));continue
                basem=np.stack([np.bincount(orders[:,i],weights=bq,minlength=n) for i in range(3)],axis=1).cumsum(axis=1)
                baserank=np.lexsort((g.program_no,-basem[:,2]));outside=actual-set(baserank[:5]);inside=actual&set(baserank[:5])
                for variant,p in probs.items():
                    key=(meet,year,variant,rid);q=bq if variant=='context' else bq/bp[mapping]*p[mapping]
                    m=np.stack([np.bincount(orders[:,i],weights=q,minlength=n) for i in range(3)],axis=1).cumsum(axis=1)
                    saved=rg[key].sort_values('program_no');check(np.array_equal(g.program_no,saved.program_no))
                    close(m,saved[['prob_win','prob_top2','prob_top3']]);close(m.sum(axis=0),[1,2,3]);close(p.sum(),1)
                    e=eg.loc[key];close(e.trio_nll,-np.log(p[target]));best=np.argsort(-p,kind='stable')[:6]
                    check(e.top6_trio_hit==int(target in best));close(e.top6_trio_probability,p[best].sum())
                    cs=cg[key].sort_values('selection_rank');expected=[','.join(map(str,sorted(g.program_no.iloc[sets[i]].astype(int)))) for i in best]
                    check(cs.programs.tolist()==expected);close(cs.probability,p[best])
                    rank=np.lexsort((g.program_no,-m[:,2]))
                    for k in (3,5,6,7):check(e[f'top{k}_contains_podium']==int(actual<=set(rank[:k])))
                    check(e.baseline_outsiders==len(outside));check(e.rescued_outsiders==len(outside&set(rank[:5])));check(e.lost_insiders==len(inside-set(rank[:5])))
                    close(e.top3_brier,np.mean((m[:,2]-g.outcome.le(3).to_numpy())**2))
                    if variant in ('direct','upside'):close(saved.raw_top3_score,(direct if variant=='direct' else upside)[idx])
            for variant,masses in calibration.items():
                sel=json.loads((OUT/'models'/f'{meet}_{year}_upside'/f'{variant}_selection.json').read_text())
                check(sel['calibration_year']==year-1);close(sel['threshold'],np.median(masses))
                current=races[races.meet.eq(meet)&races.evaluation_year.eq(year)&races.variant.eq(variant)]
                check(np.array_equal(current.selected,current.top6_trio_probability.ge(sel['threshold']).astype(int)))
            for variant,meta in [('direct',md),('upside',mu)]:
                energies=cal_energy[variant];width=max(map(len,energies));matrix=np.full((len(energies),width),-np.inf)
                target_energy=np.array([x[t] for x,t in zip(energies,cal_target)])
                for i,e in enumerate(energies):matrix[i,:len(e)]=e
                fit=minimize_scalar(lambda t:float((logsumexp(matrix/t,axis=1)-target_energy/t).mean()),bounds=(.35,4),method='bounded')
                close(fit.x,meta['temperature'])
            close(joint['loss'],np.mean(fit_loss)+.5*joint['penalty']*sum(b*b for b in joint['coefficients']))
    metric_table=pd.read_csv(OUT/'metrics.csv')
    for row in metric_table.itertuples():
        g=races[races.meet.eq(row.meet)&races.variant.eq(row.variant)]
        if row.period!='all':g=g[g.evaluation_year.eq(int(row.period))]
        check(len(g)==row.races)
        for col in ('trio_nll','top3_brier','top6_trio_hit','top5_contains_podium','top6_contains_podium','top7_contains_podium'):close(getattr(row,col),g[col].mean())
    for path,h in audit['inputs'].items():check(sha(ROOT/path)==h,path)
    result={'passed':True,'checks':checks,'max_numeric_error':max_error,'new_head_replays':12,'joint_model_replays':6,
        'evaluated_races_per_variant':4799,'source_and_registry_unchanged':True}
    (OUT/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':main()
