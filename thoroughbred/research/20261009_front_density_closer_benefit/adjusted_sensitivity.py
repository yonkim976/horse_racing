"""Exploratory additive adjustment after documenting sparse exact common cells."""
from pathlib import Path
import importlib.util,json
import numpy as np,pandas as pd
from scipy.stats import false_discovery_control
H=Path(__file__).resolve().parent;O=H/'outputs'
spec=importlib.util.spec_from_file_location('density',H/'analyze.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def design(g,races=False):
    cell=g[['meet','distance_m','grade_bucket','year']].astype(str).agg('|'.join,axis=1)
    cats=pd.DataFrame(dict(condition=cell,field_size=g.field_size.astype(str),moisture=g.moisture.fillna(-1).astype(str)))
    z=pd.get_dummies(cats,drop_first=True,dtype=float);z.insert(0,'constant',1.)
    for c in (['past_finish_mean','support_fraction'] if races else ['finish_p_mean5','field_past_finish_mean','support_fraction','gate_relative']):
        val=g[c];z[c+'_missing']=val.isna().astype(float);z[c]=val.fillna(.5);z[c+'_sq']=val.fillna(.5)**2
    return z.to_numpy(float),z.columns.tolist()
def fit(g,exposure,a,b,target,races=False):
    g=g[g[exposure].isin([a,b])&g[target].notna()].copy();x=g[exposure].eq(a).to_numpy(float);y=g[target].to_numpy();z,names=design(g,races)
    projected,_,rank,_=np.linalg.lstsq(z,np.column_stack([x,y]),rcond=None);res=np.column_stack([x,y])-z@projected;rx,ry=res.T;sxx=rx@rx
    if sxx<1e-8:return None
    beta=float(rx@ry/sxx);error=ry-beta*rx;influence=rx*error/sxx*np.sqrt(len(g)/max(1,len(g)-rank-1));out=m.prior.score_ci(g,influence,beta)
    out.update(n=len(g),n_a=int(x.sum()),n_b=int(len(g)-x.sum()),races=g.source_key.nunique(),horses=g.horse_id.nunique(),dates=g.date.nunique(),control_rank=int(rank),effective_exposure_variance=float(sxx/len(g)),target=target,exposure=exposure,a=a,b=b)
    return out
def main():
    d=pd.read_parquet(O/'analysis_rows.parquet');q=pd.read_parquet(O/'race_context.parquet');d=d.merge(q[['source_key','past_finish_mean']].rename(columns={'past_finish_mean':'field_past_finish_mean'}),on='source_key',validate='many_to_one');d['gate_relative']=(d.gate-1)/(d.field_size-1)
    rows=[]
    for window,full in m.windows(d):
        if window=='2018_2023':continue
        for cohort,flag in m.COHORTS.items():
            for exposure,(a,b) in m.EXPOSURES.items():
                for target in ['top3','recovery']:
                    out=fit(full[full[flag]],exposure,a,b,target)
                    if out:rows.append(dict(window=window,cohort=cohort,method='exploratory_additive')|out)
    results=pd.DataFrame(rows)
    for _,g in results.groupby('window'):
        ix=g[g.p.notna()].index;results.loc[ix,'bh_q']=false_discovery_control(results.loc[ix,'p'])
    results.to_csv(O/'additive_adjusted_comparisons.csv',index=False)
    profiles=pd.read_parquet(H.parent/'20261008_middle_late_style_validation/outputs/trajectory_rows.parquet',columns=['row_key','front_profile','fore_strict_profile'])
    following=d.merge(profiles,on='row_key',validate='one_to_one');extra=[];raw=[]
    for window,full in m.windows(following):
        if window=='2018_2023':continue
        for cohort,flag in [('past_front','front_profile'),('past_fore_strict','fore_strict_profile')]:
            sample=full[full[flag]]
            for exposure,(a,b) in m.EXPOSURES.items():
                for status,g in sample.groupby(exposure):
                    r=dict(window=window,cohort=cohort,exposure=exposure,status=status,n=len(g),races=g.source_key.nunique())
                    for target in m.TARGETS:r[target+'_n']=int(g[target].notna().sum());r[target+'_mean']=float(g[target].mean())
                    raw.append(r)
                for target in ['top3','recovery']:
                    out=fit(sample,exposure,a,b,target)
                    if out:extra.append(dict(window=window,cohort=cohort,method='exploratory_following')|out)
    extra=pd.DataFrame(extra)
    for _,g in extra.groupby('window'):
        ix=g[g.p.notna()].index;extra.loc[ix,'bh_q']=false_discovery_control(extra.loc[ix,'p'])
    extra.to_csv(O/'following_adjusted_comparisons.csv',index=False);pd.DataFrame(raw).to_csv(O/'following_cohort_metrics.csv',index=False)
    phases=[]
    for window,full in m.windows(d):
        for cohort,flag in m.COHORTS.items():
            for exposure in m.EXPOSURES:
                for status,g in full[full[flag]].groupby(exposure):
                    r=dict(window=window,cohort=cohort,exposure=exposure,status=status,n=len(g))
                    for target in ['p_s1f','p_g3f','p_g1f','finish_p','gain_late']:r[target+'_n']=int(g[target].notna().sum());r[target+'_mean']=float(g[target].mean())
                    phases.append(r)
    pd.DataFrame(phases).to_csv(O/'position_opportunity.csv',index=False)
    races=[]
    for window,full in m.windows(q):
        if window=='2018_2023':continue
        for exposure,a,b in [('past_lead_band','3+','0~1'),('actual_pack_band','3+','1')]:
            out=fit(full,exposure,a,b,'pace_seconds',True)
            if out:races.append(dict(window=window,method='exploratory_additive')|out)
    pd.DataFrame(races).to_csv(O/'additive_race_pace_comparisons.csv',index=False)
    print('Completed exploratory additive contrasts',len(rows),len(races),flush=True)
if __name__=='__main__':main()
