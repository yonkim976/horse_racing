"""Complete annual conditional diagnostics for every frozen pair, without changing primary tests."""
import json
import pandas as pd,numpy as np
from scipy.stats import false_discovery_control
import analyze as a

def main():
 d=a.prepare();effects=[];diags=[];supports=[]
 for period,g in a.periods(d):
  if period in ['2019_2025','2024_2025','2026_partial']:continue
  for target in a.AUX:
   res,diag,support=a.fit(g,target,period,'conditional_nonpodium');effects+=res;diags.append(diag);supports+=support;pd.DataFrame(effects).to_csv(a.O/'conditional_annual_associations.csv',index=False)
 e=pd.DataFrame(effects);s=pd.DataFrame(supports);s.to_csv(a.O/'conditional_annual_target_support.csv',index=False);pd.DataFrame(diags).to_csv(a.O/'conditional_annual_model_diagnostics.csv',index=False)
 for state in ['switched','retained']:
  z=s[s.state.eq(state)].set_index(['period','target','pair_key']);idx=pd.MultiIndex.from_frame(e[['period','target','pair_key']])
  for col in ['n','horses','races']:e[state+'_'+col]=z[col].reindex(idx).fillna(0).to_numpy()
 e['target_supported']=e.switched_n.ge(30)&e.retained_n.ge(30)&e.switched_horses.ge(15)&e.retained_horses.ge(15)&e.switched_races.ge(20)&e.retained_races.ge(20)
 for c in ['q','q_joint_targets','q_all_years','q_all_years_joint_targets']:e[c]=np.nan
 for _,g in e.groupby(['period','target']):e.loc[g.index,'q']=false_discovery_control(g.p.fillna(1).to_numpy())
 for _,g in e.groupby('period'):e.loc[g.index,'q_joint_targets']=false_discovery_control(g.p.fillna(1).to_numpy())
 annual=e[e.period.isin([str(y) for y in range(2019,2026)])]
 for _,g in annual.groupby('target'):e.loc[g.index,'q_all_years']=false_discovery_control(g.p.fillna(1).to_numpy())
 e.loc[annual.index,'q_all_years_joint_targets']=false_discovery_control(annual.p.fillna(1).to_numpy())
 names=pd.read_csv(a.O/'frozen_213_pairs.csv').set_index('pair_key')
 for c in ['trainer_name','jockey_name','meet']:e[c]=e.pair_key.map(names[c])
 e.to_csv(a.O/'conditional_annual_associations.csv',index=False);print('Finished annual conditional extension',len(e),flush=True)
if __name__=='__main__':main()
