"""Independent sparse verification of the annual conditional extension."""
import json
import pandas as pd,numpy as np
from scipy.sparse.linalg import lsqr
from scipy import stats
from scipy.stats import false_discovery_control
import verify as v

def main():
 d=v.data();pairs=pd.read_csv(v.O/'frozen_213_pairs.csv').pair_key.tolist();e=pd.read_csv(v.O/'conditional_annual_associations.csv',dtype={'period':str});diags=pd.read_csv(v.O/'conditional_annual_model_diagnostics.csv',dtype={'period':str});support=pd.read_csv(v.O/'conditional_annual_target_support.csv',dtype={'period':str});assert len(e)==16*213 and len(diags)==16
 for _,z in e.groupby(['period','target']):v.eq(len(z),213);v.eq(z.q,false_discovery_control(z.p.fillna(1).to_numpy()))
 for _,z in e.groupby('period'):v.eq(z.q_joint_targets,false_discovery_control(z.p.fillna(1).to_numpy()))
 annual=e[e.period.isin([str(y) for y in range(2019,2026)])]
 for _,z in annual.groupby('target'):v.eq(z.q_all_years,false_discovery_control(z.p.fillna(1).to_numpy()))
 v.eq(annual.q_all_years_joint_targets,false_discovery_control(annual.p.fillna(1).to_numpy()));assert diags.normal_equation_max.max()<1e-5 and diags.max_fe_mean.max()<1e-7
 fits=[];cis=[];support_rows=[]
 for period,mask in v.windows(d):
  if period in ['2019_2025','2024_2025','2026_partial']:continue
  for target in ['conditional_finish_p','conditional_time_gap']:
   g=d[mask&d[target].notna()].copy();full,names=v.matrix(g,pairs);norm=np.sqrt(np.asarray(full.power(2).sum(axis=0)).ravel());scale=1/np.where(norm>0,norm,1);scaled=full.multiply(scale).tocsr();y=g[target].to_numpy(float);sol=lsqr(scaled,y,atol=1e-12,btol=1e-12,iter_lim=40000);coef=scale*sol[0];res=y-full@coef;z=e[e.period.eq(period)&e.target.eq(target)&e.status.eq('estimated')];diag=diags[diags.period.eq(period)&diags.target.eq(target)].iloc[0];values=[]
   for (key,changed),sg in g.groupby(['pair_key','changed']):support_rows.append(dict(period=period,model='conditional_nonpodium',target=target,pair_key=key,state='switched' if changed else 'retained',n=len(sg),horses=sg.horse_id.nunique(),races=sg.source_key.nunique()))
   for row in z.itertuples():
    unit=np.zeros(full.shape[1]);unit[0]=1;unit[names.index('switch_'+row.pair_key)]=1;value=float(unit@coef);values.append(value)
    if row.q<.05:
     der=lsqr(scaled.T,scale*unit,atol=1e-12,btol=1e-12,iter_lim=40000)[0];score=der*res*np.sqrt(len(g)/diag.residual_df);vs=[];counts=[]
     for fields in [['horse_id'],['date'],['horse_id','date']]:
      a=g[fields].copy();a['score']=score;b=a.groupby(fields).score.sum();k=len(b);counts.append(k);vs.append(float(b@b)*k/(k-1))
     se=np.sqrt(max(0,vs[0],vs[1],vs[0]+vs[1]-vs[2]));crit=stats.t.ppf(.975,min(counts[:2])-1);v.eq([se,value-crit*se,value+crit*se],[row.se,row.ci_low,row.ci_high],tol=3e-6);cis.append(dict(period=period,target=target,pair_key=row.pair_key,se_error=abs(se-row.se)))
   v.eq(values,z.estimate,tol=3e-6);fits.append(dict(period=period,target=target,contrasts=len(z),iterations=int(sol[2]),max_coefficient_error=float(np.max(np.abs(values-z.estimate))) if len(z) else None));print('Verified conditional annual',period,target,flush=True)
 cols=['period','model','target','pair_key','state'];expected=pd.DataFrame(support_rows).sort_values(cols).reset_index(drop=True);support=support.sort_values(cols).reset_index(drop=True)
 for c in support:v.eq(support[c],expected[c])
 for state in ['switched','retained']:
  z=support[support.state.eq(state)].set_index(['period','target','pair_key']);idx=pd.MultiIndex.from_frame(e[['period','target','pair_key']])
  for c in ['n','horses','races']:v.eq(e[state+'_'+c],z[c].reindex(idx).fillna(0))
 v.eq(e.target_supported,e.switched_n.ge(30)&e.retained_n.ge(30)&e.switched_horses.ge(15)&e.retained_horses.ge(15)&e.switched_races.ge(20)&e.retained_races.ge(20))
 out=dict(passed=True,checks=v.checks,additional_models=16,fixed_pair_family=213,all_coefficients_reproduced=True,all_BH_intervals_reproduced=True,independent_models=fits,independent_cluster_CIs=cis);(v.O/'conditional_annual_verification.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
