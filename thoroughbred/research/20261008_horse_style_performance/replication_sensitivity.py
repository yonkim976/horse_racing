"""Restrict frozen-candidate comparison to styles with >=3 prior exact-distance starts."""
from pathlib import Path
from collections import defaultdict
import math,json
import numpy as np,pandas as pd
from scipy.stats import t
H=Path(__file__).resolve().parent;O=H/'outputs'
d=pd.read_parquet(O/'performance_observations.parquet');p=pd.read_parquet(O/'conditional_evaluation.parquet');rows=[];saved=[]
for year,z in p.groupby('year'):
 counts=d[d.year.lt(year)].groupby(['hd_key','role4']).size().to_dict();z=z.copy();z['prior_style_n']=[counts.get((hd,r),0) for hd,r in zip(z.hd_key,z.role4)];z=z[z.prior_candidate.notna()&z.prior_style_n.ge(3)].copy();table=z.groupby(['hd_key','candidate_match']).size().unstack(fill_value=0);valid=table[(table[True]>=2)&(table[False]>=2)].index;z=z[z.hd_key.isin(valid)].copy();z['adjusted']=z.actual-z.global_model;k=z.hd_key.nunique();n=z.groupby(['hd_key','candidate_match']).row_key.transform('size');z['contrast_weight']=np.where(z.candidate_match,1.,-1.)/n/k;est=float(z.contrast_weight@z.adjusted);means={}
 for flag,g in z.groupby('candidate_match'):means[flag]=float(np.average(g.adjusted,weights=abs(g.contrast_weight)))
 score=z.contrast_weight*(z.adjusted-np.where(z.candidate_match,means[True],means[False]));variances=[];groups=[]
 for keys in [z.horse_id,z.date.dt.strftime('%Y-%m-%d'),z.horse_id+':'+z.date.dt.strftime('%Y-%m-%d')]:
  agg=defaultdict(float)
  for key,s in zip(keys,score):agg[key]+=s
  ng=len(agg);variances.append(sum(s*s for s in agg.values())*ng/(ng-1));groups.append(ng)
 se=math.sqrt(max(0,variances[0],variances[1],variances[0]+variances[1]-variances[2]));crit=t.ppf(.975,min(groups[:2])-1);rows.append(dict(year=int(year),horse_distances=k,horses=z.horse_id.nunique(),n=len(z),estimate=est,se=se,lower=est-crit*se,upper=est+crit*se));saved.append(z)
pd.DataFrame(rows).to_csv(O/'candidate_replication_supported_styles.csv',index=False);pd.concat(saved,ignore_index=True).to_parquet(O/'candidate_replication_supported_rows.parquet',index=False);print(pd.DataFrame(rows).to_string(index=False))
