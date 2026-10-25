"""Stable FE absorption and graph rank, copied without executing prior studies."""
import numpy as np,pandas as pd
from scipy import sparse
from scipy.sparse.csgraph import connected_components
def prune(g):
 q=g.copy();iterations=0
 while True:
  keep=q.groupby('horse_id').horse_id.transform('size').ge(2)&q.groupby('source_key').source_key.transform('size').ge(2)
  if keep.all():break
  q=q[keep].copy();iterations+=1
 return q,iterations

def incidence(ids):
 c=pd.factorize(ids)[0];n=np.bincount(c);a=sparse.csr_matrix((1/n[c],(c,np.arange(len(c)))),shape=(len(n),len(c)))
 return c,a

def absorb(y,groups):
 out=y.copy();ops=[incidence(g) for g in groups]
 if not ops:return out,0,0.
 for it in range(20000):
  old=out.copy()
  for c,a in ops:out-= (a@out)[c]
  change=np.max(abs(out-old))
  if change<1e-13:break
 else:raise RuntimeError('Absorption did not converge')
 err=max(float(np.max(abs(a@out))) for _,a in ops)
 assert err<1e-10,err
 return out,it+1,err

def fe_rank(g,two):
 nr=g.source_key.nunique()
 if not two:return nr,1
 hc=pd.factorize(g.horse_id)[0];rc=pd.factorize(g.source_key)[0];nh=hc.max()+1
 u=np.r_[hc,rc+nh];v=np.r_[rc+nh,hc];adj=sparse.csr_matrix((np.ones(len(u)),(u,v)),shape=(nh+nr,nh+nr))
 nc=connected_components(adj,directed=False,return_labels=False)
 return int(nh+nr-nc),int(nc)

def cluster(score,ids,cor):
 c=pd.factorize(ids)[0];n=c.max()+1;agg=np.bincount(c,weights=score)
 return float(agg@agg)*n/(n-1)*cor,n

