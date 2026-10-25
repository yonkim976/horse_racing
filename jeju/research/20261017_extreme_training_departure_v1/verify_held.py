"""Independently validate why a whole extreme model cannot be estimated."""
import json
import numpy as np
from scipy.sparse.linalg import splu
from data import HERE,load,save
from verify import sample,reconstruct,HELP
def main():
 target=HERE/'verification01/held_identifiability.json';assert not target.exists()
 a,f=load();models=json.loads((HERE/'analysis01/models.json').read_text());checks=[]
 for m in models:
  if m['status']!='unidentified_or_insufficient_df':continue
  g=sample(a,f,m);X=reconstruct(g,m['spec']);Z,_=HELP.fe(g);lu=splu((Z.T@Z).tocsc());xr=X-Z@lu.solve(np.asarray(Z.T@X));K=len(m['spec']['target_columns']);N=xr[:,K:];unexplained=xr[:,:K]-N@np.linalg.lstsq(N,xr[:,:K],rcond=1e-10)[0];rank=int(np.linalg.matrix_rank(unexplained,tol=1e-7));df=int(len(g)-Z.shape[1]-np.linalg.matrix_rank(xr,tol=1e-7))
  assert rank==m['target_rank'] and df==m['residual_df'] and (rank<K or df<=20)
  checks.append({'period':m['period'],'model':m['model'],'target_columns_present':K,'independent_target_rank':rank,'residual_df':df})
 assert len(checks)==1
 save(target,{'status':'passed','held_models_independently_recomputed':checks});print(checks,flush=True)
if __name__=='__main__':main()
