"""Independently verify shared-slope contrasts using full cell intercept dummies."""
import json
import numpy as np
import pandas as pd
from data import HERE,ROOT,ID_COLS,sha,save
from verify import reconstruct,bh
def main():
 out=HERE/'supplement_verification01';out.mkdir(exist_ok=False)
 for r in json.loads((HERE/'supplement01/source_manifest.json').read_text())['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes']
 a=pd.read_csv(HERE/'input01/pairs.csv',dtype={c:str for c in ID_COLS},low_memory=False).set_index('api_record_id');ef=pd.read_csv(HERE/'supplement01/effects.csv',dtype={'period':str});models=json.loads((HERE/'supplement01/models.json').read_text());maxbeta=0.;maxvar=0.;checks=0
 for group in models:
  g=a.loc[group['row_ids']];cells=group['cells'];C=len(cells);base=reconstruct(g,g.changed_jockey.astype(float),group['spec'])[:,2:];switch=np.column_stack([(g.cell.eq(c)&g.changed_jockey).to_numpy(float) for c in cells]);intercept=np.column_stack([g.cell.eq(c).to_numpy(float) for c in cells]);X=np.column_stack([switch,base,intercept]);pen=np.r_[np.zeros(C),np.ones(base.shape[1]),np.zeros(C)];bread=np.linalg.inv(X.T@X+np.diag(pen))
  for model in group['models']:
   y=g[model['target']].to_numpy();beta=np.linalg.lstsq(np.vstack([X,np.diag(np.sqrt(pen))]),np.r_[y,np.zeros(X.shape[1])],rcond=1e-12)[0];expected=np.asarray(model['beta']);err=float(np.abs(beta[:len(expected)]-expected).max());assert err<1e-6;maxbeta=max(maxbeta,err);res=y-X@beta
   V={}
   for label,key in [('date','race_date'),('horse','horse_id')]:
    score=pd.DataFrame(X*res[:,None]);score['key']=g[key].to_numpy();s=score.groupby('key').sum().to_numpy();G=len(s);cov=bread@s.T@s@bread*(G/(G-1)*(len(X)-1)/group['df']);V[label]=np.diag(cov)[:C];err=float(np.abs(V[label]-model[label+'_variance']).max());assert err<1e-6;maxvar=max(maxvar,err)
   for i,cell in enumerate(cells):
    r=ef[(ef.period==group['period'])&(ef.cell==cell)&(ef.target==model['target'])];assert len(r)==1;r=r.iloc[0]
    assert np.allclose([r.effect,r.date_low,r.date_high,r.horse_low,r.horse_high],[beta[i],beta[i]-r.crit*np.sqrt(V['date'][i]),beta[i]+r.crit*np.sqrt(V['date'][i]),beta[i]-r.crit*np.sqrt(V['horse'][i]),beta[i]+r.crit*np.sqrt(V['horse'][i])]);checks+=1
 assert np.allclose(ef.BH_q,bh(ef.date_p));assert np.array_equal(ef.exploratory_positive_supported,ef.BH_q.lt(.05)&ef.date_low.gt(0)&ef.horse_low.gt(0))
 save(out/'verification.json',{'status':'passed','shared_effects_full_dummy_least_squares_verified':checks,'BH_tests_recomputed':len(ef),'maximum_beta_difference':maxbeta,'maximum_variance_difference':maxvar,'exploratory_positive_supported':int(ef.exploratory_positive_supported.sum()),'no_primary_claims_added':True});print('Shared-slope supplementary verification passed',checks,flush=True)
if __name__=='__main__':main()
