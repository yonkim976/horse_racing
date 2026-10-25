"""Observed late survival and pair co-occurrence with explicit selection controls."""
import itertools
import math
import numpy as np
import pandas as pd
from scipy.stats import t
import data as d


def standardize(frame,group,outcome,cells,min_n):
    z=frame[frame[group].isin([0,1])&frame[outcome].notna()].copy()
    c=z.groupby(cells+[group])[outcome].agg(['size','mean']).reset_index()
    n=c.pivot(index=cells,columns=group,values='size').fillna(0).reindex(columns=[0,1],fill_value=0)
    supported=n[(n[0]>=min_n)&(n[1]>=min_n)].copy()
    common=supported.index
    raw=z.groupby(group)[outcome].agg(['size','mean'])
    result=dict(group=group,outcome=outcome,cells=len(supported),
       raw_n0=int(raw.loc[0,'size']) if 0 in raw.index else 0,
       raw_n1=int(raw.loc[1,'size']) if 1 in raw.index else 0,
       raw_rate0=float(raw.loc[0,'mean']) if 0 in raw.index else None,
       raw_rate1=float(raw.loc[1,'mean']) if 1 in raw.index else None)
    if not len(supported):return result,pd.DataFrame()
    weights=(supported[0]+supported[1]);weights/=weights.sum()
    cc=c.set_index(cells).loc[common].reset_index().merge(weights.rename('weight').reset_index(),on=cells,validate='many_to_one')
    fitted=z.merge(cc[cells+[group,'size','mean','weight']],on=cells+[group],validate='many_to_one')
    rates=cc.assign(weighted=cc.weight*cc['mean']).groupby(group).weighted.sum()
    scores=np.where(fitted[group].eq(1),1.,-1.)*fitted.weight*(fitted[outcome]-fitted['mean'])/fitted['size']
    days=pd.Series(scores.to_numpy()).groupby(fitted.date.dt.strftime('%Y-%m-%d').to_numpy()).sum()
    se=math.sqrt(len(days)/(len(days)-1)*float((days**2).sum())) if len(days)>1 else np.nan
    delta=float(rates.loc[1]-rates.loc[0]);half=float(t.ppf(.975,len(days)-1)*se)
    result.update(supported_n0=int(fitted[group].eq(0).sum()),supported_n1=int(fitted[group].eq(1).sum()),
        common_raw_rate0=float(fitted.loc[fitted[group].eq(0),outcome].mean()),
        common_raw_rate1=float(fitted.loc[fitted[group].eq(1),outcome].mean()),
        standardized_rate0=float(rates.loc[0]),standardized_rate1=float(rates.loc[1]),
        standardized_difference=delta,lower=delta-half,upper=delta+half,dates=len(days))
    return result,cc


def main():
    d.check();q,h,x,races,aux,p,j=d.load();q=d.build_bias_context(q,p)
    valid_keys=set(pd.read_csv(d.R/'20261021_busan_leader_pack_outcomes/outputs/race_outcomes.csv').source_key)
    q['complete_early']=q.source_key.isin(valid_keys)
    z=q[q.complete_early].copy()
    assert z.source_key.nunique()==5991
    coverage=[]
    for (normal,top3),g in z.groupby(['normal_outcome','top3']):
        coverage.append(dict(normal=bool(normal),top3=int(top3),starts=len(g),
             g3_missing=int(g.g3front.isna().sum()),g1_missing=int(g.g1front.isna().sum()),
             either_missing=int((g.g3front.isna()|g.g1front.isna()).sum()),
             g3_missing_rate=float(g.g3front.isna().mean()),g1_missing_rate=float(g.g1front.isna().mean())))
    pd.DataFrame(coverage).to_csv(d.O/'late_observation_coverage.csv',index=False)
    rows=[]
    for period in ['all','2024','2025','2026']:
        a=z if period=='all' else z[z.year.eq(int(period))]
        for variable in ['leader','distance_m','grade_band','history_band','past_late_type','early_count']:
            for value,g in a.groupby(variable):
                if variable!='leader':g=g[g.leader]
                if not len(g):continue
                rows.append(dict(period=period,condition=variable,value=str(value),starts=len(g),
                    races=g.source_key.nunique(),top3=int(g.top3.sum()),top3_rate=float(g.top3.mean()),
                    g3_observed=int(g.g3front.notna().sum()),g3_front_rate=float(g.g3front.mean()) if g.g3front.notna().any() else np.nan,
                    g1_observed=int(g.g1front.notna().sum()),g1_front_rate=float(g.g1front.mean()) if g.g1front.notna().any() else np.nan,
                    strict_observed=int(g.strict_survival.notna().sum()),
                    strict_survival_rate=float(g.strict_survival.mean()) if g.strict_survival.notna().any() else np.nan))
    pd.DataFrame(rows).to_csv(d.O/'survival_observed_rates.csv',index=False,encoding='utf-8-sig')
    cells=['distance_m','grade_band','field_band','ability_band','history_band']
    standardized=[]
    cell_tables=[]
    for period in ['all','2024','2025','2026']:
        a=z if period=='all' else z[z.year.eq(int(period))]
        a=a.copy();a['lead_group']=a.leader.astype(int)
        r,c=standardize(a,'lead_group','top3',cells,10);r['period']=period;r['comparison']='leader_vs_other';standardized.append(r)
        if len(c):c['period']=period;c['comparison']='leader_vs_other';cell_tables.append(c)
        a=a[a.leader&a.past_late_type.isin(['both_fast','g3_only'])].copy()
        a['late_group']=a.past_late_type.eq('both_fast').astype(int)
        r,c=standardize(a,'late_group','top3',cells,10);r['period']=period;r['comparison']='both_fast_vs_g3_only';standardized.append(r)
        if len(c):c['period']=period;c['comparison']='both_fast_vs_g3_only';cell_tables.append(c)
    pd.DataFrame(standardized).to_csv(d.O/'horse_standardized_comparisons.csv',index=False)
    pd.concat(cell_tables,ignore_index=True).to_csv(d.O/'horse_common_cells.csv',index=False)

    pairs=[]
    for key,g in z.groupby('source_key',sort=True):
        a=g.reset_index(drop=True);n=len(a);ii,jj=np.triu_indices(n,1)
        leader=a.leader.to_numpy();rank=a.raw_finish_rank.to_numpy();ability=a.ability_band.to_numpy();hist=a.history_band.to_numpy()
        for i,k in zip(ii,jj):
            r1,r2=rank[i],rank[k]
            pairs.append(dict(source_key=key,date=a.date.iloc[0],year=int(a.year.iloc[0]),
              distance_m=int(a.distance_m.iloc[0]),grade_band=int(a.grade_band.iloc[0]),
              field_band=int(a.field_band.iloc[0]),ability_min=int(min(ability[i],ability[k])),
              ability_max=int(max(ability[i],ability[k])),history_min=int(min(hist[i],hist[k])),
              lead_type=int(leader[i])+int(leader[k]),both_lead=int(leader[i]&leader[k]),
              both_top3=int(1<=r1<=3 and 1<=r2<=3),
              quinella=int((r1==1 and r2 in [1,2]) or (r2==1 and r1 in [1,2])),
              race_weight=1/len(ii)))
    pp=pd.DataFrame(pairs)
    pair_rates=[]
    for period in ['all','2024','2025','2026']:
        a=pp if period=='all' else pp[pp.year.eq(int(period))]
        for typ,g in a.groupby('lead_type'):
            pair_rates.append(dict(period=period,lead_type=int(typ),pairs=len(g),races=g.source_key.nunique(),
                 both_top3=int(g.both_top3.sum()),both_top3_rate=float(g.both_top3.mean()),
                 quinella=int(g.quinella.sum()),quinella_rate=float(g.quinella.mean()),
                 race_equal_both_top3=float(np.average(g.both_top3,weights=g.race_weight))))
    pd.DataFrame(pair_rates).to_csv(d.O/'pair_observed_rates.csv',index=False)
    pcells=['distance_m','grade_band','field_band','ability_min','ability_max','history_min']
    matched=[];common=[]
    for period in ['all','2024','2025','2026']:
        a=pp if period=='all' else pp[pp.year.eq(int(period))]
        for outcome in ['both_top3','quinella']:
            r,c=standardize(a,'both_lead',outcome,pcells,20);r['period']=period;matched.append(r)
            if len(c):c['period']=period;c['outcome']=outcome;common.append(c)
    pd.DataFrame(matched).to_csv(d.O/'pair_standardized_comparisons.csv',index=False)
    pd.concat(common,ignore_index=True).to_csv(d.O/'pair_common_cells.csv',index=False)
    h=pd.concat([q[['row_key','date','horse_id','source_key']],h],axis=1)
    h.to_parquet(d.O/'late_history_features.parquet',index=False)
    d.save('bias_summary.json',dict(source_starts=len(q),valid_s1f_starts=len(z),valid_s1f_races=5991,
       pair_rows=len(pp),normal_starts=int(z.normal_outcome.sum()),nonnormal_starts=int((~z.normal_outcome).sum()),
       g3_missing=int(z.g3front.isna().sum()),g1_missing=int(z.g1front.isna().sum()),
       diagnosis_is_observational=True,causal_effect=False,current_outcomes_not_prerace_features=True))
    d.check()
    print(pd.DataFrame(coverage).to_string(index=False),flush=True)
    print(pd.DataFrame(standardized)[['period','comparison','raw_rate0','raw_rate1','cells','standardized_difference','lower','upper']].to_string(index=False),flush=True)
    print(pd.DataFrame(pair_rates).to_string(index=False),flush=True)
    print(pd.DataFrame(matched)[['period','outcome','raw_rate0','raw_rate1','cells','standardized_difference','lower','upper']].to_string(index=False),flush=True)


if __name__=='__main__':main()
