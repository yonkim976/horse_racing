"""Paired race-date bootstrap and predeclared comparisons."""
import json
import numpy as np
import pandas as pd
import common as c

METRICS=['axis_top3','quinella_one','quinella_three','qpl_one','qpl_three','qpl_count',
         'runner_brier','quinella_brier','qpl_brier','trio_logloss','ordered_logloss',
         'axis_brier','qnl1_brier','qnl3_brier','qpl1_brier','qpl3_brier']

def paired(a,b):
    a=a.sort_values('race_key');b=b.sort_values('race_key')
    assert a.race_key.to_list()==b.race_key.to_list()
    n=len(a);dates,ix=np.unique(a.race_date,return_inverse=True)
    av=a[METRICS].to_numpy(float);bv=b[METRICS].to_numpy(float)
    aa=np.zeros((len(dates),len(METRICS)));bb=aa.copy();nn=np.bincount(ix)
    np.add.at(aa,ix,av);np.add.at(bb,ix,bv)
    rng=np.random.default_rng(20261024);draws=rng.integers(0,len(dates),size=(2000,len(dates)))
    am=aa[draws].sum(1)/nn[draws].sum(1)[:,None];bm=bb[draws].sum(1)/nn[draws].sum(1)[:,None]
    diff=am-bm;relative=(am/bm-1)*100
    result={}
    for j,col in enumerate(METRICS):
        result[col]={'candidate':float(av[:,j].mean()),'reference':float(bv[:,j].mean()),
            'difference':float((av[:,j]-bv[:,j]).mean()),'difference_ci95':np.quantile(diff[:,j],[.025,.975]).tolist(),
            'relative_percent':float((av[:,j].mean()/bv[:,j].mean()-1)*100),
            'relative_percent_ci95':np.quantile(relative[:,j],[.025,.975]).tolist()}
        if col in METRICS[:5]:
            result[col].update({'gained':int(((av[:,j]==1)&(bv[:,j]==0)).sum()),
                'lost':int(((av[:,j]==0)&(bv[:,j]==1)).sum()),'net_hits':int((av[:,j]-bv[:,j]).sum())})
    return {'races':n,'dates':len(dates),'metrics':result}

def main():
    old=pd.read_parquet(c.BASE/'outputs/race_metrics.parquet')
    old=old[old.scope.eq('all_starters')&old.variant.isin(['additive89','full103'])]
    new=pd.read_parquet(c.OUT/'race_metrics.parquet');allrows=pd.concat([old,new],ignore_index=True)
    overall=[]
    for variant,g in allrows.groupby('variant'):
        overall.append({'variant':variant,'races':len(g),'means':{m:float(g[m].mean()) for m in METRICS},
            'hits':{m:int(g[m].sum()) for m in METRICS[:6]}})
    comparisons={}
    for cand in ['strong89','state_gbm','state_joint']:
        for ref in ['additive89','full103','strong89','state_gbm']:
            if cand==ref or (cand=='strong89' and ref=='state_gbm'):continue
            a=allrows[allrows.variant.eq(cand)];b=allrows[allrows.variant.eq(ref)]
            pieces={'all':paired(a,b)}
            for col in ['year','meet']:
                for val in sorted(a[col].unique()):pieces[f'{col}_{val}']=paired(a[a[col].eq(val)],b[b[col].eq(val)])
            comparisons[f'{cand}_vs_{ref}']=pieces
    decisions={}
    for cand in ['state_gbm','state_joint']:
        comparison=comparisons[f'{cand}_vs_strong89']['all']['metrics']
        keep=(comparison['quinella_three']['difference_ci95'][0]>0 and
              comparison['axis_top3']['difference_ci95'][0]>-.01 and
              comparison['qpl_three']['difference_ci95'][0]>-.01 and
              comparison['ordered_logloss']['difference']<=0)
        el=comparisons[f'{cand}_vs_additive89']['all']['metrics']
        decisions[cand]={'retain_candidate':keep,'production_promoted':False,
            'ten_percent_point_estimate':{m:el[m]['relative_percent']>=10 for m in METRICS[:5]},
            'ten_percent_ci_lower_bound':{m:el[m]['relative_percent_ci95'][0]>=10 for m in METRICS[:5]}}
    c.save(c.OUT/'results.json',{'overall':overall,'comparisons':comparisons,'decisions':decisions,
        'bootstrap':{'draws':2000,'cluster':'race_date','seed':20261024,'pointwise_not_multiplicity_adjusted':True},
        'evaluation':'historical_development','future_improvement_established':False})
    print(json.dumps({'overall':overall,'decisions':decisions},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
