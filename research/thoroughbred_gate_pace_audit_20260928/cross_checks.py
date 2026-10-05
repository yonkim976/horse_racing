"""Supplemental fixed strata checks, specified after primary results; descriptive only."""
import numpy as np
import pandas as pd
from common import *
from analyze import controls,cluster_fit,contrast,bh

d=pd.read_parquet(OUT/'runners.parquet');rows=[]
for (venue,distance,condition),g in d.groupby(['venue','distance_m','condition']):
    if g.race_id.nunique()<50 or g.race_date.nunique()<20:continue
    C,_=controls(g);X=np.column_stack([g.band.eq('MIDDLE'),g.band.eq('OUTER'),C]).astype(float)
    b,V,G,_=cluster_fit(g,X,g.top3.to_numpy(float));c=np.zeros(len(b));c[1]=1
    rows.append({'venue':venue,'distance_m':distance,'condition':condition,'races':g.race_id.nunique(),'days':G,**contrast(b,V,G,c)})
a=pd.DataFrame(rows);a['q_exploratory']=bh(a.p);a.to_parquet(OUT/'distance_condition_checks.parquet',index=False)
rows=[]
for venue,g in d.groupby('venue'):
    maxgate=g.groupby('race_id').gate_number.transform('max');g=g[g.n.eq(12)&maxgate.eq(12)].copy()
    C,_=controls(g);X=np.column_stack([g.gate_number.eq(k) for k in range(2,13)]+list(C.T)).astype(float)
    b,V,G,_=cluster_fit(g,X,g.top3.to_numpy(float))
    for k in range(2,13):
        c=np.zeros(len(b));c[k-2]=1
        rows.append({'venue':venue,'gate':k,'reference_gate':1,'races':g.race_id.nunique(),'days':G,**contrast(b,V,G,c)})
z=pd.DataFrame(rows);z['q_exploratory']=bh(z.p);z.to_parquet(OUT/'fixed12_gate_checks.parquet',index=False)
print(a[a.distance_m.eq(1600)].to_string(index=False));print(z.to_string(index=False))
