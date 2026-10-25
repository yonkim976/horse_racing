"""Descriptive intervals and fixed latest-race examples, without model selection."""
import numpy as np
import pandas as pd
from features import HERE,save


def ci(g,values,rng):
    z=g.groupby('race_date')[values].agg(['sum','count'])
    n=len(z);results={}
    draws=rng.integers(n,size=(2000,n))
    for c in values:
        num=z[(c,'sum')].to_numpy();den=z[(c,'count')].to_numpy()
        vals=num[draws].sum(axis=1)/den[draws].sum(axis=1)
        results[c+'_lo'],results[c+'_hi']=map(float,np.quantile(vals,[.025,.975]))
    return results


def main():
    out=HERE/'supplement01';out.mkdir(exist_ok=False)
    a=pd.read_csv(HERE/'features01/features_and_targets.csv',dtype={'horse_id':str},low_memory=False)
    p=pd.read_csv(HERE/'run02/predictions.csv',dtype={'horse_id':str})
    top=pd.read_csv(HERE/'run02/top_first_pack.csv',dtype={'selected_horse_id':str})
    dates=a[['race_id','race_date']].drop_duplicates()
    top=top.merge(dates,on='race_id',validate='many_to_one')
    rng=np.random.default_rng(20261009);rows=[]
    for period,z in [('2024_2025',top[top.year.le(2025)&top.model.eq('M3')]),
                     ('2026_partial',top[top.year.eq(2026)&top.model.eq('M3')])]:
        for dist in ['all']+sorted(z.distance.unique().tolist()):
            v=z if dist=='all' else z[z.distance.eq(dist)]
            if v.empty:continue
            rows.append({'period':period,'distance':dist,'races':len(v),'days':v.race_date.nunique(),
                         'hit':v.hit.mean(),'random_baseline':v.random_baseline.mean(),**ci(v,['hit','random_baseline'],rng)})
    pd.DataFrame(rows).to_csv(out/'first_selection_intervals.csv',index=False)
    examples=[]
    current=a[a.year.eq(2026)]
    for dist in [800,1000,1110]:
        r=current[current.race_distance_m.eq(dist)].sort_values(['race_date','race_number']).iloc[-1]
        g=current[current.race_id.eq(r.race_id)].copy()
        base=['api_record_id','race_id','race_date','race_number','horse_id','horse_name','horse_number','race_distance_m',
              'h_any_s1f_n','h_any_s1ftime_n','h_any_s1f_first_mean','h_any_s1ftime_mean','opp_inner_lead_sum','opp_outer_lead_sum']
        g=g[base]
        for task in ['s1f_pack3','c4_pack3','g1f_pack3','s1f_second_inside']:
            v=p[p.model.eq('M3')&p.task.eq(task)&p.race_id.eq(r.race_id)]
            cols=[c for c in ['p0','p1','p2'] if v[c].notna().any()]+['y']
            v=v[['api_record_id']+cols].rename(columns={c:task+'_'+c for c in cols})
            g=g.merge(v,on='api_record_id',validate='one_to_one')
        examples.append(g.sort_values('horse_number'))
    pd.concat(examples).to_csv(out/'latest_race_examples.csv',index=False,encoding='utf-8-sig')
    save(out/'selection_contract.json',{'status':'descriptive_only','intervals':'2000 race-date cluster bootstrap, seed20261009',
        'examples':'latest complete source race in 2026 for each of 800,1000,1110m, chosen by date/race number without accuracy selection',
        'not_additional_model_tuning':True})


if __name__=='__main__':main()
