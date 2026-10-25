"""All adequately supported switch destinations, including rarely retained riders."""
import numpy as np
import pandas as pd
from data import HERE,ID_COLS,period_data,save
from analysis import fit,comparison_data,bh
def main():
 out=HERE/'supplement01';out.mkdir(exist_ok=False);a=pd.read_csv(HERE/'input01/pairs.csv',dtype={c:str for c in ID_COLS},low_memory=False);s=pd.read_csv(HERE/'input01/support.csv',dtype={'period':str});base=pd.read_csv(HERE/'analysis01/effects.csv',dtype={'period':str})
 rows=[];models=[];support=[]
 for period in ['2024_2025','2026']:
  z=period_data(a,period);z=z[z.recent_eligible]
  v=s[s.period.eq(period)];v=v[v.changes.ge(20)&v.changed_horses.ge(10)&v.changed_days.ge(10)&v.horses.ge(15)&v.days.ge(15)&v.other_changes_same_stable.ge(30)]
  for r in v.itertuples():
   support.append(r._asdict());reuse=base[base.period.eq(period)&base.cell.eq(r.cell)&base.variant.eq('primary')&base.comparison.eq('other_switches')]
   if len(reuse)==2:rows.extend(reuse.to_dict('records'))
   else:
    g,tr=comparison_data(z,r.cell,'other_switches');rr,mm=fit(g,tr,period,r.cell,'other_switches','A_only_supplement');rows+=rr;models.append(mm)
 r=pd.DataFrame(rows);r['supplement_BH_q']=bh(r.date_p);r['exploratory_positive_supported']=r.supplement_BH_q.lt(.05)&r.date_low.gt(0)&r.horse_low.gt(0)
 r.to_csv(out/'effects_all_A.csv',index=False,encoding='utf-8-sig');pd.DataFrame(support).to_csv(out/'support.csv',index=False,encoding='utf-8-sig');save(out/'additional_models.json',models)
 print('All A tests',len(r));print(r[r.exploratory_positive_supported].to_string(index=False),flush=True)
if __name__=='__main__':main()
