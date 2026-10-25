"""Independent label-free reconstruction of seven history reliability columns."""
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
STUDY=Path(__file__).resolve().parent
FEATURE=ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet'
NAMES=['log_min_observed_starts','log_min_same_valid_times','min_valid_n5',
       'max_cv5_both_observed','cv5_missing_runner_count','max_log_same_start_gap_both_observed','same_start_gap_missing_runner_count']


def sha(b):return hashlib.sha256(b).hexdigest()


def raw_matrix(rows):
 arrays=[];weights=[];race_ids=[]
 for rid,g in rows.groupby('race_id',sort=True):
  g=g.sort_values('horse_number');n=len(g);i,j=np.triu_indices(n,1)
  counts=g[['observed_starts','same_starts','same_valid_times','valid_n5']].to_numpy(float)
  assert np.isfinite(counts).all() and (counts>=0).all()
  cv=g.std5_s.to_numpy(float)/g.mean5_s.to_numpy(float)
  cv_ok=(g.valid_n5.to_numpy()>=3)&np.isfinite(cv)&g.mean5_s.gt(0).to_numpy()&g.std5_s.ge(0).to_numpy()
  cv_missing=(~cv_ok[i]).astype(int)+(~cv_ok[j]).astype(int)
  cv_max=np.maximum(cv[i],cv[j]);cv_max[cv_missing>0]=np.nan
  age=g.days_since_same.to_numpy(float)
  age_ok=g.same_starts.gt(0).to_numpy()&np.isfinite(age)&(age>=0)
  age_missing=(~age_ok[i]).astype(int)+(~age_ok[j]).astype(int)
  age_max=np.log1p(np.maximum(age[i],age[j]));age_max[age_missing>0]=np.nan
  x=np.column_stack([np.log1p(np.minimum(counts[i,0],counts[j,0])),
   np.log1p(np.minimum(counts[i,2],counts[j,2])),np.minimum(counts[i,3],counts[j,3]),
   cv_max,cv_missing,age_max,age_missing])
  arrays.append(x);weights.append(np.full(len(x),1/len(x)));race_ids.extend([str(rid)]*len(x))
 x=np.vstack(arrays);w=np.concatenate(weights)/len(arrays)
 assert np.isclose(w.sum(),1)
 return x,w,np.asarray(race_ids)


def moments(x,w):
 result={}
 for k,name in enumerate(NAMES):
  valid=np.isfinite(x[:,k]);support=float(w[valid].sum());assert support>0
  mean=float(np.dot(w[valid],x[valid,k])/support)
  centered=np.where(valid,x[:,k]-mean,0)
  variance=float(np.dot(w,centered**2))
  scale=float(np.sqrt(variance))
  result[name]={'mean':mean,'scale_after_H1_mean_imputation':scale,'valid_weight':support,
   'missing_rows':int((~valid).sum()),'degenerate':scale<=1e-12}
 return result


def reconstruct():
 assert sha(FEATURE.read_bytes())=='036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f'
 columns=['api_record_id','race_id','race_date','year','horse_id','horse_number','distance_m',
  'history_cutoff','latest_history_date','observed_starts','same_starts','same_valid_times',
  'valid_n5','mean5_s','std5_s','days_since_same']
 f=pd.read_parquet(FEATURE,columns=columns)
 assert len(f)==52155 and f.api_record_id.is_unique
 assert f[['observed_starts','same_starts','same_valid_times','valid_n5']].notna().all().all()
 assert f.same_valid_times.le(f.same_starts).all() and f.same_starts.le(f.observed_starts).all()
 assert f.valid_n5.between(0,5).all() and f.valid_n5.le(f.same_valid_times).all()
 assert f.loc[f.valid_n5.lt(3),'std5_s'].isna().all()
 assert np.isfinite(f.loc[f.valid_n5.ge(3),'std5_s']).all()
 assert f.days_since_same.isna().eq(f.same_starts.eq(0)).all()
 assert f.mean5_s.isna().eq(f.valid_n5.eq(0)).all()
 dates=pd.to_datetime(f.race_date);cut=pd.to_datetime(f.history_cutoff)
 assert (dates-cut).dt.days.eq(2).all()
 observed=f.latest_history_date.notna()
 assert pd.to_datetime(f.loc[observed,'latest_history_date']).le(cut[observed]).all()
 f['race_date']=dates
 folds={}
 for year,h1_expected,h2_expected,eval_expected in [(2024,2147,336,637),(2025,2818,311,654),(2026,3458,325,488)]:
  previous=f.loc[f.year.eq(year-1)];h2=previous.loc[previous.race_date.dt.month.ge(7)]
  last_allowed=h2.race_date.min()-pd.Timedelta(days=2)
  h1=pd.concat([f.loc[f.year.between(2019,year-2)],previous.loc[previous.race_date.dt.month.le(6)&previous.race_date.le(last_allowed)]])
  evaluation=f.loc[f.year.eq(year)]
  assert h1.race_id.nunique()==h1_expected and h2.race_id.nunique()==h2_expected and evaluation.race_id.nunique()==eval_expected
  assert h1.race_date.max()<=last_allowed and h2.race_date.max()<=evaluation.race_date.min()-pd.Timedelta(days=2)
  x,w,rids=raw_matrix(h1)
  folds[str(year)]={'h1_races':h1_expected,'h1_pairs':len(x),'h2_races':h2_expected,'evaluation_races':eval_expected,
   'h1_first':str(h1.race_date.min().date()),'h1_last':str(h1.race_date.max().date()),
   'h2_first':str(h2.race_date.min().date()),'h2_last':str(h2.race_date.max().date()),
   'new_basis_moments':moments(x,w)}
 return folds


if __name__=='__main__':
 folds=reconstruct()
 report={'status':'PASS','scope':'Label-free raw histories and H1-only new-basis moment reference',
  'labels_read':False,'optimizers_or_performance_metrics_run':False,'raw_feature_order':NAMES,
  'missing_numeric_policy':'H1 observed-weight mean imputation; scale variance includes missing rows as centered zero',
  'folds':folds}
 (STUDY/'ROOT_PREFLIGHT_REFERENCE.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
 print(json.dumps({k:v for k,v in report.items() if k!='folds'}))
