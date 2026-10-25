"""Exact-condition calendar comparisons and distance support; no coefficient selection."""
import json
import numpy as np
import pandas as pd
from audit import HERE,save,csv,BANDS
from modeling import SEED

def matched(g,target_months,reference_months,value='raw_time',weights=None):
    a=g.copy();a['w']=1. if weights is None else a.race_date.map(weights).fillna(0)
    a['which']=np.where(a.month.isin(target_months),'target',np.where(a.month.isin(reference_months),'reference','other'))
    a=a[(a.which!='other')&(a.w>0)].copy();a['wy']=a[value]*a.w
    strata=['year','grade','moisture']
    grouped=a.groupby(strata+['which']).agg(w=('w','sum'),wy=('wy','sum')).reset_index()
    p=grouped.pivot(index=strata,columns='which',values=['w','wy'])
    if ('w','target') not in p or ('w','reference') not in p:return None,0,0,0,0
    p=p.dropna();w=np.minimum(p[('w','target')],p[('w','reference')]);diff=p[('wy','target')]/p[('w','target')]-p[('wy','reference')]/p[('w','reference')]
    if not len(p):return None,0,0,0,0
    return float(np.average(diff,weights=w)),len(p),float(p[('w','target')].sum()),float(p[('w','reference')].sum()),float(w.sum())

def main():
    out=HERE/'descriptive_01';out.mkdir(exist_ok=False)
    s=pd.read_csv(HERE/'audit/source_rows.csv',low_memory=False);s=s[s.strict]
    r=pd.read_csv(HERE/'analysis_02/race_residuals.csv')
    # Raw full-population race means include runners without same-distance history.
    allrace=s.groupby('race_id').agg(race_date=('race_date','first'),year=('year','first'),month=('month','first'),distance=('race_distance_m','first'),grade=('rank_class_raw','first'),moisture=('moisture','first'),band=('band','first'),raw_time=('finish_time_seconds','mean')).reset_index()
    csv(out/'raw_race_means.csv',allrace)
    result=[]
    for period,years in [('complete_2019_2025',range(2019,2026)),('complete_2024_2025',[2024,2025]),('partial_2026',[2026])]:
        for dist in [1000,1110]:
            for month in ['summer_winter']+[3,4,5,6,7,8,9,10,11]:
                target=[6,7,8] if month=='summer_winter' else [month];reference=[12,1,2]
                for source,g0,value in [('raw_population',allrace,'raw_time'),('ability_adjusted_common_population',r,'residual')]:
                    g=g0[(g0.year.isin(years))&(g0.distance==dist)].dropna(subset=[value])
                    a=g[g.month.isin(target)];b=g[g.month.isin(reference)];raw=float(a[value].mean()-b[value].mean()) if len(a) and len(b) else None
                    delta,n,nt,nr,w=matched(g,target,reference,value)
                    boots=[]
                    if delta is not None:
                        dates=g.race_date.unique();rng=np.random.default_rng(SEED)
                        for _ in range(200):
                            weights=pd.Series(rng.choice(dates,len(dates),replace=True)).value_counts();v,*_=matched(g,target,reference,value,weights)
                            if v is not None:boots.append(v)
                    result.append(dict(period=period,distance=dist,comparison=str(month),source=source,unit='seconds',raw_unmatched_difference=raw,matched_difference=delta,ci_lo=float(np.quantile(boots,.025)) if len(boots)>=180 else None,ci_hi=float(np.quantile(boots,.975)) if len(boots)>=180 else None,bootstrap_valid=len(boots),common_strata=n,target_races_in_common=nt,reference_races_in_common=nr,overlap_weight=w,target_all_races=len(a),reference_all_races=len(b),note='partial_year_different_month_support' if period=='partial_2026' else 'observational_exact_year_grade_numeric_moisture_matching'))
    csv(out/'matched_calendar_comparisons.csv',pd.DataFrame(result))
    support=[]
    for period,x in [('all_2017_plus',allrace),('modern_2019_plus',allrace[allrace.year>=2019]),('recent_2024_plus',allrace[allrace.year>=2024])]:
        for (dist,band),g in x.groupby(['distance','band']):
            support.append(dict(period=period,distance=dist,band=band,races=len(g),days=g.race_date.nunique(),years=g.year.nunique(),scope='pilot_estimated_separately' if dist in [1000,1110] else 'support_only_no_borrowed_coefficients',recent_sparse=(period=='recent_2024_plus' and g.race_date.nunique()<30)))
    csv(out/'all_distance_support.csv',pd.DataFrame(support))
    csv(out/'field_size_support.csv',s.groupby(['year','race_distance_m','race_id']).size().rename('field_n').reset_index().groupby(['year','race_distance_m','field_n']).size().reset_index(name='races'))
    csv(out/'grade_observation_boundaries.csv',allrace.groupby('grade').agg(first_date=('race_date','min'),last_date=('race_date','max'),races=('race_id','size')).reset_index())
    print('Calendar comparisons complete',flush=True)
if __name__=='__main__':main()
