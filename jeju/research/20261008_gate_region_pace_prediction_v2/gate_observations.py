"""Descriptive exact10 gate-region observations, with no fitted prediction input."""
import math
import numpy as np
import pandas as pd
from features import HERE,ROOT,sha,save


def main():
    out=HERE/'gate01';out.mkdir(exist_ok=False)
    a=pd.read_csv(HERE/'features01/features_and_targets.csv',dtype={'horse_id':str},low_memory=False)
    source=ROOT/'jeju/research/20261008_running_style_outcomes_v1/run01/runner_types_and_evidence.csv'
    original=pd.read_csv(source,usecols=['api_record_id','top3'])
    a=a.merge(original,on='api_record_id',validate='one_to_one');a=a[a.exact10].copy()
    assert len(a)==39300 and a.race_id.nunique()==3930
    a['firstpack']=a.y_s1f_pack3.eq(0).astype(float).where(a.y_s1f_pack3.notna())
    a['first2packs']=a.y_s1f_pack3.le(1).astype(float).where(a.y_s1f_pack3.notna())
    periods=[('all',a),('2024_2025',a[a.year.isin([2024,2025])]),('2026_partial',a[a.year.eq(2026)])]
    periods +=[(str(y),a[a.year.eq(y)]) for y in sorted(a.year.unique())]
    counts=[]
    for period,z in periods:
        for (dist,band),g in z.groupby(['race_distance_m','gate_band']):
            for event in ['firstpack','first2packs','top3']:
                v=g[g[event].notna()]
                counts.append({'period':period,'distance':dist,'gate_band':band,'event':event,'starts':len(v),
                    'events':int(v[event].sum()),'rate':v[event].mean(),'races':v.race_id.nunique(),'days':v.race_date.nunique(),
                    'first_date':v.race_date.min(),'last_date':v.race_date.max(),'source_races':g.race_id.nunique()})
    pd.DataFrame(counts).to_csv(out/'gate_region_counts.csv',index=False)
    rng=np.random.default_rng(20261008);effects=[]
    for dist in [800,900,1300,1400]:
        for event in ['firstpack','first2packs']:
            g=a[a.race_distance_m.eq(dist)&a[event].notna()]
            race=g.groupby(['race_id','race_date','gate_band'])[event].mean().unstack('gate_band').reset_index()
            for lhs,rhs in [('inner','outer'),('inner','middle'),('outer','middle')]:
                race['delta']=race[lhs]-race[rhs]
                cl=race.groupby('race_date').delta.agg(['sum','count'])
                num,den=cl['sum'].to_numpy(),cl['count'].to_numpy();n=len(cl);mean=num.sum()/den.sum()
                draws=rng.integers(n,size=(10000,n));bs=num[draws].sum(axis=1)/den[draws].sum(axis=1)
                lo,hi=np.quantile(bs,[.025,.975]);se=np.sqrt(n/(n-1)*np.square(num-mean*den).sum())/den.sum()
                p=math.erfc(abs(mean/se)/np.sqrt(2)) if se else float(not mean)
                effects.append({'distance':dist,'event':event,'contrast':lhs+'-'+rhs,'races':len(race),'days':n,
                    'difference_pp':100*mean,'lo_pp':100*lo,'hi_pp':100*hi,'p':p,'raw_not_ability_adjusted':True})
    ef=pd.DataFrame(effects);order=ef.sort_values('p');assert len(ef)==24
    q=np.minimum.accumulate((order.p.to_numpy()*24/np.arange(1,25))[::-1])[::-1]
    ef.loc[order.index,'BH_q']=np.minimum(q,1);ef.to_csv(out/'early_region_contrasts.csv',index=False)
    previous=ROOT/'jeju/research/20261008_gate_top3_period_moisture_v1/adjusted_contrasts.csv'
    old=pd.read_csv(previous);old=old[(old.kind=='overall')&(old.variant=='primary')]
    old.to_csv(out/'previous_adjusted_top3.csv',index=False)
    rawpath=ROOT/'jeju/research/20261008_gate_top3_period_moisture_v1/raw_gate.csv'
    raw=pd.read_csv(rawpath);new=a.groupby(['race_distance_m','horse_number']).agg(starts=('api_record_id','size'),top3=('top3','sum')).reset_index()
    check=raw.merge(new,on=['race_distance_m','horse_number'],validate='one_to_one',suffixes=('_old','_new'))
    assert len(check)==80 and (check.starts_old==check.starts_new).all() and (check.top3_old==check.top3_new).all()
    new.to_csv(out/'gate_top3_reproduced.csv',index=False)
    save(out/'verification.json',{'status':'passed','source_starts':len(a),'source_races':a.race_id.nunique(),
        'previous_gate_top3_cells_reproduced':80,'new_exploratory_BH_family':24,
        'inputs':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in [source,previous,rawpath,HERE/'features01/features_and_targets.csv',HERE/'PLAN.md',HERE/'gate_observations.py']]})
    print(pd.DataFrame(counts).query("period=='all' and distance in [800,900,1300,1400]").to_string(index=False),flush=True)


if __name__=='__main__':main()
