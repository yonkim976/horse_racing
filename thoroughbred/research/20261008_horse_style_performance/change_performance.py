"""Supplementary descriptive before/after outcomes in actual, unskipped roster windows."""
from pathlib import Path
import pandas as pd,numpy as np
H=Path(__file__).resolve().parent;O=H/'outputs'
a=pd.read_parquet(O/'roster.parquet');d=pd.read_parquet(O/'performance_observations.parquet');p=pd.read_csv(O/'horse_profiles.csv',dtype={'horse_id':str});allowed=p[p.change_supported].set_index('horse_id');out=[]
lookup=d.set_index('row_key')
for horse,g in a.groupby('horse_id'):
 if horse not in allowed.index:continue
 g=g.sort_values('date').tail(10);r=allowed.loc[horse];rec=dict(horse_id=horse,horse_name=r.horse_name,old_mode=r.old_mode,new_mode=r.mode5,change_candidate=bool(r.change_candidate),all10_same_distance=bool(r.all10_same_distance))
 for label,z in [('old',g.iloc[:5]),('new',g.iloc[5:])]:
  q=lookup.reindex(z.row_key);ok=q.adjusted_performance.notna();v=q.loc[ok];rec[label+'_normal_n']=int(ok.sum());rec[label+'_top5_rate']=float(v.rank_raw.le(5).mean()) if len(v) else np.nan;rec[label+'_adjusted_mean']=float(v.adjusted_performance.mean()) if len(v) else np.nan;rec[label+'_start']=str(z.date.min().date());rec[label+'_end']=str(z.date.max().date())
 rec['performance_comparable']=rec['old_normal_n']>=3 and rec['new_normal_n']>=3;rec['adjusted_change']=rec['new_adjusted_mean']-rec['old_adjusted_mean'] if rec['performance_comparable'] else np.nan;rec['top5_rate_change']=rec['new_top5_rate']-rec['old_top5_rate'] if rec['performance_comparable'] else np.nan;out.append(rec)
pd.DataFrame(out).to_csv(O/'change_performance.csv',index=False)
print('Saved',len(out),'descriptive before/after rows')
