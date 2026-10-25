"""Same horse-distance-owner adjacent selected starts; descriptive change only."""
import numpy as np
import pandas as pd
from scipy.stats import norm
from data import HERE,save
from effects import bh
B=4000;SEED=20261010
def mean_interval(g,key,col):
 z=g.groupby(key)[col].agg(['sum','count']).to_numpy();rng=np.random.default_rng(SEED);draw=[]
 for start in range(0,B,200):
  w=rng.multinomial(len(z),np.full(len(z),1/len(z)),size=min(200,B-start));draw.extend((w@z[:,0])/(w@z[:,1]))
 point=float(g[col].mean());lo,hi=np.quantile(draw,[.025,.975]);se=float(np.std(draw,ddof=1));p=float(2*norm.sf(abs(point/se))) if se else 1.
 return point,float(lo),float(hi),p
def main():
 out=HERE/'switch01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input01/starts.csv',dtype={k:str for k in ['horse_id','jockey_id','trainer_id','owner_id','previous_jockey_id','previous_trainer_id','previous_owner_id']},low_memory=False)
 p=a[a.year.ge(2024)&a.H1_time.notna()&a.previous_H1_time.notna()&a.race_distance_m.eq(a.previous_race_distance_m)&a.owner_id.eq(a.previous_owner_id)&a.gap_days.between(2,120)].copy()
 p['time_gain']=p.H1_time_adv-p.previous_H1_time_adv;p['top3_excess_gain']=100*(p.H1_top3_excess-p.previous_H1_top3_excess);p['same_jockey']=p.jockey_id.eq(p.previous_jockey_id)
 p.to_csv(out/'pairs.csv',index=False,encoding='utf-8-sig');rows=[]
 for period,z in [('2024_2025',p[p.year.le(2025)]),('2026',p[p.year.eq(2026)])]:
  for subset,g in [('all',z),('same_jockey',z[z.same_jockey])]:
   for changed,h in g.groupby('changed_trainer'):
    for target in ['time_gain','top3_excess_gain']:
     point,lo,hi,pv=mean_interval(h,'race_date',target);_,hl,hh,_=mean_interval(h,'horse_id',target)
     rows.append({'period':period,'subset':subset,'changed_trainer':bool(changed),'target':target,'pairs':len(h),'horses':h.horse_id.nunique(),'days':h.race_date.nunique(),'mean':point,'date_low':lo,'date_high':hi,'horse_low':hl,'horse_high':hh,'date_p':pv,'previous_time_adv':h.previous_H1_time_adv.mean(),'current_time_adv':h.H1_time_adv.mean()})
   for k,h in g[g.changed_trainer].groupby('trainer_id'):
    if len(h)<2:continue
    point,lo,hi,pv=mean_interval(h,'race_date','time_gain');_,hl,hh,_=mean_interval(h,'horse_id','time_gain')
    rows.append({'period':period,'subset':subset,'changed_trainer':True,'trainer_id':k,'name':h.trainer_display_name.iloc[0],'target':'time_gain','pairs':len(h),'horses':h.horse_id.nunique(),'days':h.race_date.nunique(),'mean':point,'date_low':lo,'date_high':hi,'horse_low':hl,'horse_high':hh,'date_p':pv,'support':len(h)>=20 and h.horse_id.nunique()>=10})
 r=pd.DataFrame(rows);r['BH_q']=np.nan
 for _,g in r[r.trainer_id.notna()].groupby(['period','subset']):r.loc[g.index,'BH_q']=bh(g.date_p)
 r['direction_supported']=r.support.eq(True)&r.BH_q.lt(.05)&((r.date_low.gt(0)&r.horse_low.gt(0))|(r.date_high.lt(0)&r.horse_high.lt(0)))
 r.to_csv(out/'summary.csv',index=False,encoding='utf-8-sig');print(r[r.trainer_id.isna()].to_string(index=False),flush=True)
 save(out/'scope.json',{'all_observed_changes':int(a.changed_trainer.sum()),'horses_with_observed_changes':a.loc[a.changed_trainer,'horse_id'].nunique(),'eligible_pairs':len(p),'eligible_changes':int(p.changed_trainer.sum()),'previous_source':'previous selected complete-cohort start, not guaranteed actual previous start','same_owner':True,'same_distance':True,'days':[2,120],'causal':False,'clock':'H1 relative-time expected excess, not absolute seconds correction'})
if __name__=='__main__':main()
