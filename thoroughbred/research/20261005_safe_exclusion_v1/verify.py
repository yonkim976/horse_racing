"""Independent replay of heads, distributions, exclusion, pools and six tickets."""
from pathlib import Path
import importlib.util
import itertools
import json
import hashlib
import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy.special import logsumexp
from scipy.optimize import minimize_scalar

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OUT=HERE/'outputs'
PARENT=HERE.parent/'20261004_outsider_joint_v1';STACK=HERE.parent/'20261004_pace_finish_stack_v1'
spec=importlib.util.spec_from_file_location('independent_previous_joint',PARENT/'verify.py')
OLD=importlib.util.module_from_spec(spec);spec.loader.exec_module(OLD)
KEY=['race_key','program_no','horse_id'];checks=0;maximum_error=0.

def check(value,message=''):
    global checks
    checks+=1
    if not value:raise AssertionError(f'{checks}: {message}')

def close(a,b,tol=2e-11):
    global maximum_error
    error=float(np.max(abs(np.asarray(a)-np.asarray(b))))
    maximum_error=max(maximum_error,error);check(error<tol,f'error {error}')

def sha(p):
    with p.open('rb') as file:return hashlib.file_digest(file,'sha256').hexdigest()

def raw(g,path,filename,meta):
    x=g[meta['features']].copy()
    for col,v in meta['category_vocabulary'].items():x[col]=pd.Categorical(x[col],categories=v)
    return lgb.Booster(model_file=str(path/filename)).predict(x,raw_score=True,num_threads=4)

def normalize(x):return np.exp(x-logsumexp(x))

def exclusion(p,sets,n,c):
    inclusion=np.array([p[np.any(sets==i,axis=1)].sum() for i in range(n)])
    order=np.argsort(inclusion,kind='stable');positions=np.empty(n,int);positions[order]=np.arange(n)
    minimum_position=positions[sets].min(axis=1)
    values=[float(p[minimum_position>=k].sum()) for k in range(n-c['minimum_remaining']+1)]
    k=max(i for i,v in enumerate(values) if v+1e-12>=c['safe_probability'])
    return order[:k],values[k]

def decision(policy,parent,fusion,exclude,context,sets,guard,c):
    n=len(context);p=parent if policy.startswith('parent') else fusion
    margins=np.array([p[np.any(sets==i,axis=1)].sum() for i in range(n)])
    removed=np.array([],int);safe=1.
    if policy=='parent_safe_top7':removed,safe=exclusion(parent,sets,n,c)
    elif policy=='fusion_safe_top7' or (policy=='fusion_guarded_union7' and guard):removed,safe=exclusion(exclude,sets,n,c)
    eligible_horses=set(range(n))-set(removed)
    rank=np.argsort(-margins,kind='stable').tolist()
    if policy.endswith('_full'):pool=list(range(n))
    elif policy=='fusion_guarded_union7':
        priority=[i for i in np.argsort(-context,kind='stable')[:5] if i in eligible_horses]+[i for i in rank if i in eligible_horses]
        pool=list(dict.fromkeys(priority))[:7]
    else:pool=[i for i in rank if i in eligible_horses][:6 if policy=='fusion_top6' else 7]
    choices=[i for i,s in enumerate(sets) if set(s)<=set(pool)]
    best=sorted(choices,key=lambda i:(-p[i],i))[:6]
    return p,removed,safe,pool,np.array(best),float(p[choices].sum())

def scalar_temp(energies,truth):
    matrix=np.full((len(energies),max(map(len,energies))),-np.inf)
    actual=np.array([e[i] for e,i in zip(energies,truth)])
    for i,e in enumerate(energies):matrix[i,:len(e)]=e
    fit=minimize_scalar(lambda t:float(np.mean(logsumexp(matrix/t,axis=1)-actual/t)),bounds=(.35,4),method='bounded')
    check(fit.success);return float(fit.x)

def main():
    c=json.loads((HERE/'config.json').read_text());audit=json.loads((OUT/'audit.json').read_text());summary=json.loads((OUT/'summary.json').read_text())
    for path,h in audit['inputs'].items():check(sha(ROOT/path)==h,path)
    for path,h in summary['artifacts'].items():check(sha(OUT/path)==h,path)
    f=pd.read_parquet(PARENT/'outputs/features.parquet').merge(pd.read_parquet(STACK/'outputs/labels.parquet'),on=KEY,validate='one_to_one')
    race=pd.read_csv(OUT/'race_metrics.csv');rec=pd.read_parquet(OUT/'recommendations.parquet');runner=pd.read_parquet(OUT/'runner_predictions.parquet');pool=pd.read_csv(OUT/'candidate_pools.csv',keep_default_na=False)
    check(race.groupby('policy').race_key.nunique().to_dict()=={p:4799 for p in c['policies']})
    rgroup=dict(tuple(runner.groupby(['meet','evaluation_year','race_key'])))
    cgroup=dict(tuple(rec.groupby(['policy','race_key'])))
    eg=race.set_index(['policy','race_key']);pg=pool.set_index(['policy','race_key'])
    parent_runners=pd.read_parquet(PARENT/'outputs/runner_predictions.parquet');parent_runners=parent_runners[parent_runners.variant.eq('upside_joint')]
    matched=runner.merge(parent_runners,on=KEY,validate='one_to_one');check(len(matched)==50754);close(matched.parent_top3,matched.prob_top3)
    parent_races=pd.read_csv(PARENT/'outputs/race_metrics.csv');parent_races=parent_races[parent_races.variant.eq('upside_joint')]
    matched_r=race[race.policy.eq('parent_full')].merge(parent_races,on='race_key',validate='one_to_one')
    close(matched_r.trio6_hit,matched_r.top6_trio_hit);close(matched_r.trio6_probability,matched_r.top6_trio_probability)
    for meet in (1,3):
        for year in (2024,2025,2026):
            g=f[f.meet.eq(meet)&f.year.isin([year-1,year])].reset_index(drop=True)
            headpath=OUT/'models'/f'{meet}_{year}';meta=json.loads((headpath/'metadata.json').read_text())
            check(meta['target']=='outcome>3');check(meta['false_exclusion_weight']==8);check(sha(headpath/'nonpodium.txt')==meta['model_sha256'])
            check(meta['train_start']=='2017-01-01');check(pd.Timestamp(meta['train_end'])<pd.Timestamp(year-1,1,1));check(meta['calibration_year']==year-1)
            check(not set(meta['features'])&{'outcome','race_key','horse_id','program_no','race_date','S1F_rank','G3F_rank'})
            inverted=-raw(g,headpath,'nonpodium.txt',meta)
            upath=PARENT/'outputs/models'/f'{meet}_{year}_upside';umeta=json.loads((upath/'metadata.json').read_text());pair=json.loads((upath/'joint.json').read_text())
            uraw=raw(g,upath,'top3.txt',umeta)
            bpath=STACK/'outputs/models'/f'{meet}_{year}_context';bmeta=json.loads((bpath/'metadata.json').read_text())
            braw=np.column_stack([raw(g,bpath,f'position_{i}.txt',bmeta) for i in (1,2,3)])
            calenergy=[];calfusion=[];caltruth=[];calpolicy={p:[] for p in c['policies']};calguards=[]
            for rid,idx in g.groupby('race_key',sort=False).indices.items():
                one=g.iloc[idx];n=len(one);sets,orders,mapping=OLD.support(n)
                incidence=np.stack([np.any(sets==i,axis=1).astype(float) for i in range(n)],axis=1)
                pe=uraw[idx][sets].sum(axis=1)/pair['temperature']+((OLD.design(one)-pair['mean'])/pair['scale'])@np.array(pair['coefficients'])
                parent=normalize(pe);ee=inverted[idx][sets].sum(axis=1);excluded=normalize(ee/meta['exclusion_temperature'])
                fe=(1-meta['fusion_weight'])*np.log(parent)+meta['fusion_weight']*np.log(excluded)
                fusion=normalize(fe/meta['fusion_temperature'])
                baseq=OLD.baseline_q(braw[idx],np.array(bmeta['temperatures']))
                context=np.stack([np.bincount(orders[:,i],weights=baseq,minlength=n) for i in range(3)],axis=1).sum(axis=1)
                truth=set(np.flatnonzero(one.outcome.le(3).to_numpy()));target=next(i for i,s in enumerate(sets) if set(s)==truth)
                guard=meta['guard']['allowed']
                if int(one.year.iloc[0])==year-1:
                    calenergy.append(ee);calfusion.append(fe);caltruth.append(target)
                    removed,_=exclusion(excluded,sets,n,c)
                    if len(removed):calguards.append({'day':str(one.race_date.iloc[0].date()),'safe':int(not set(removed)&truth)})
                    for policy in c['policies']:
                        p,_,_,_,best,_=decision(policy,parent,fusion,excluded,context,sets,guard,c);calpolicy[policy].append(float(p[best].sum()))
                    continue
                saved=rgroup[(meet,year,rid)].sort_values('program_no')
                check(np.array_equal(saved.program_no,one.program_no));close(saved.raw_exclusion_podium_score,inverted[idx])
                for name,p in [('parent',parent),('exclusion',excluded),('fusion',fusion)]:
                    close(saved[name+'_top3'],p@incidence);close((p@incidence).sum(),3);close(p.sum(),1)
                for policy in c['policies']:
                    p,removed,safe,poolids,best,poolmass=decision(policy,parent,fusion,excluded,context,sets,guard,c)
                    r=eg.loc[(policy,rid)];savedp=pg.loc[(policy,rid)];cs=cgroup[(policy,rid)].sort_values('selection_rank')
                    check(len(best)==6);check(r.excluded_count==len(removed));check(r.pool_size==len(poolids))
                    check(savedp.excluded==','.join(map(str,sorted(one.program_no.iloc[removed].astype(int)))))
                    check(savedp.candidates==','.join(map(str,sorted(one.program_no.iloc[poolids].astype(int)))))
                    actualerror=int(bool(set(removed)&truth));poolerror=int(not truth<=set(poolids));hit=int(target in best)
                    check(r.exclusion_error==actualerror);check(r.pool_covers_podium==1-poolerror);check(r.trio6_hit==hit)
                    check(r.miss_hard_exclusion==actualerror);check(r.miss_outside_pool==int(not actualerror and poolerror));check(r.miss_inside_pool==int(not poolerror and not hit))
                    close(r.trio6_probability,p[best].sum());close(r.pool_probability,poolmass);close(r.exclusion_predicted_safe,safe)
                    check(r.trio6_probability<=np.sort(p)[-6:].sum()+1e-12);check(r.selected==int(r.trio6_probability>=meta['thresholds'][policy]))
                    expected=[','.join(map(str,sorted(one.program_no.iloc[sets[i]].astype(int)))) for i in best]
                    check(expected==cs.programs.tolist());close(cs.probability,p[best]);check(cs.hit.sum()==hit)
            close(meta['exclusion_temperature'],scalar_temp(calenergy,caltruth));close(meta['fusion_temperature'],scalar_temp(calfusion,caltruth))
            for policy,masses in calpolicy.items():close(meta['thresholds'][policy],np.median(masses))
            check(meta['guard']['races']==len(calguards))
            if len(calguards)<c['guard_min_races']:check(not meta['guard']['allowed'])
            else:
                daily=pd.DataFrame(calguards).groupby('day').safe.agg(['sum','size']).to_numpy()
                rng=np.random.default_rng(meta['guard']['seed']);picks=rng.integers(0,len(daily),size=(2000,len(daily)));sample=daily[picks]
                lower=float(np.quantile(sample[:,:,0].sum(axis=1)/sample[:,:,1].sum(axis=1),.05))
                close(meta['guard']['lower'],lower);check(meta['guard']['allowed']==bool(lower>=.95))
    table=pd.read_csv(OUT/'metrics.csv')
    for row in table.itertuples():
        group=race[race.meet.eq(row.meet)&race.policy.eq(row.policy)]
        if row.period!='all':group=group[group.evaluation_year.eq(int(row.period))]
        check(row.races==len(group));close(row.trio6_hit,group.trio6_hit.mean());close(row.pool_covers_podium,group.pool_covers_podium.mean())
        check(row.exclusion_races==group.exclusion_possible.sum());check(row.wrong_exclusion_races==group.exclusion_error.sum())
        active=group[group.exclusion_possible.eq(1)];selected=group[group.selected.eq(1)]
        if len(active):close(row.active_safe,1-active.exclusion_error.mean())
        check(row.selected==len(selected));close(row.selected_hit,selected.trio6_hit.mean());check(row.selected_hits==selected.trio6_hit.sum())
    for path,h in audit['inputs'].items():check(sha(ROOT/path)==h,path)
    result={'passed':True,'checks':checks,'max_numeric_error':maximum_error,'new_head_replays':6,'policies':8,
        'evaluated_races_per_policy':4799,'parent_runner_replay_rows':50754,'inputs_unchanged':True}
    (OUT/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':main()
