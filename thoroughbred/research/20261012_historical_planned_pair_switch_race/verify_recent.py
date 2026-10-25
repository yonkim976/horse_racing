"""Independently verify recent-period BH signals, including their inadequate local support."""
import json
import numpy as np,pandas as pd
from scipy.sparse.linalg import lsqr
from scipy import stats
import verify as v

def main():
 d=v.data();s=pd.read_csv(v.O/'pair_support.csv');pairs=s[s.model_supported].pair_key.tolist();e=pd.read_csv(v.O/'adjusted_associations.csv');diags=pd.read_csv(v.O/'model_diagnostics.csv');out=[]
 for target in ['top3','finish_p']:
  g=d[d.year.between(2024,2025)&d.primary_eligible&d[target].notna()].copy();full,names=v.matrix(g,pairs);y=g[target].to_numpy(float);sol=lsqr(full,y,atol=1e-12,btol=1e-12,iter_lim=40000);residual=y-full@sol[0];dg=diags[diags.window.eq('2024_2025')&diags.target.eq(target)].iloc[0]
  z=e[e.window.eq('2024_2025')&e.target.eq(target)&e.contrast.ne('general_other_pairs')&e.q.lt(.05)]
  for r in z.itertuples():
   unit=np.zeros(full.shape[1]);unit[names.index('switch_'+r.pair_key)]=1
   if r.contrast=='pair_total':unit[0]=1
   influence=lsqr(full.T,unit,atol=1e-12,btol=1e-12,iter_lim=40000)[0]*residual*np.sqrt(len(g)/dg.residual_df);vars_=[];counts=[]
   for fields in [['horse_id'],['date'],['horse_id','date']]:
    a=g[fields].copy();a['score']=influence;b=a.groupby(fields).score.sum();k=len(b);counts.append(k);vars_.append(float(b@b)*k/(k-1))
   se=np.sqrt(max(0,vars_[0],vars_[1],vars_[0]+vars_[1]-vars_[2]));crit=stats.t.ppf(.975,min(counts[:2])-1);v.eq([se,r.estimate-crit*se,r.estimate+crit*se],[r.se,r.ci_low,r.ci_high],tol=3e-6)
   pairg=g[g.pair_key.eq(r.pair_key)];sw=pairg[pairg.changed];ret=pairg[~pairg.changed];supported=len(sw)>=30 and sw.horse_id.nunique()>=15 and sw.source_key.nunique()>=20 and len(ret)>=30 and ret.horse_id.nunique()>=15 and ret.source_key.nunique()>=20
   assert not supported;out.append(dict(target=target,contrast=r.contrast,pair_key=r.pair_key,switched=len(sw),retained=len(ret),recent_support=supported,se_error=float(abs(se-r.se)),q=r.q,q_all_three_targets=r.q_all_three_targets));print('Verified recent signal',target,r.contrast,r.pair_key,flush=True)
 result=dict(passed=True,checks=v.checks,signals=out,all_bh_recent_pairs_fail_predeclared_local_support=True)
 (v.O/'recent_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
