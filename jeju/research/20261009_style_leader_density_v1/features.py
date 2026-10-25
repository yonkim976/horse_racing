"""Past-only early style and late-gain candidates from preserved quality snapshots."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
PRE=ROOT/'jeju/research/20261008_gate_region_pace_prediction_v2/features01'
OUT=ROOT/'jeju/research/20261008_running_style_outcomes_v1/run01/runner_types_and_evidence.csv'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def save(p,o):p.write_text(json.dumps(o,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def classify(a,scope,late=.6):
 p='h_'+scope+'_';eligible=a[p+'s1f_n'].ge(5)&a[p+'s1f_n'].ge(.6*a[p+'n'])
 front=a[p+'s1f_front_mean'].ge(.6-1e-12);lead=front&a[p+'s1f_first_mean'].ge(.6-1e-12)
 back=(a[p+'s1f_middle_mean']+a[p+'s1f_rear_mean']).ge(.6-1e-12)
 closing=back&a[p+'late_n'].ge(5)&a[p+'late_mean'].ge(late-1e-12)
 return pd.Series(np.select([~eligible,lead,front,closing],['unknown','lead','front','closing'],default='other'),index=a.index)
def main():
 out=HERE/'features01';out.mkdir(exist_ok=False)
 sources=[HERE/'PLAN.md',PRE/'features_and_targets.csv',PRE/'history_lineage.csv',OUT,ROOT/'jeju/data/horse_exclusions.json',
          ROOT/'jeju/research/20261009_leading_style_position_top3_v1/verification01/verification.json']
 save(out/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sources],
      'database_opened':False,'database_sha256':'a878a40fd5dc28e1385801c40136e506d9e3bc406e357e4158e5eb6883f5f21e'})
 a=pd.read_csv(PRE/'features_and_targets.csv',dtype={'horse_id':str},low_memory=False)
 a=a[['api_record_id','horse_id','race_id','race_date','year','race_distance_m','field_n','horse_number','gate_scaled','y_s1f_pack3','y_s1f_position4']+[c for c in a if c.startswith('h_')]].copy()
 fields=['api_record_id','horse_id','race_id','race_date','finish_position','top3','c4_rank_lo','g1f_rank_hi','c4_to_g1f_definite_gain2','carried_weight_kg','track_raw','rank_class_raw']
 b=pd.read_csv(OUT,dtype={'horse_id':str},usecols=fields)
 a=a.merge(b,on=['api_record_id','horse_id','race_id','race_date'],how='left',validate='one_to_one')
 assert len(a)==52155 and a.top3.notna().all() and np.array_equal(a.top3,a.finish_position.le(3))
 valid=a.c4_rank_lo.notna()&a.g1f_rank_hi.notna()
 gain=np.where(valid,a.c4_rank_lo-a.g1f_rank_hi>=2,np.nan)
 assert np.allclose(gain,pd.to_numeric(a.c4_to_g1f_definite_gain2),equal_nan=True)
 gainmap=pd.Series(gain,index=a.api_record_id)
 trace=pd.read_csv(PRE/'history_lineage.csv',keep_default_na=False).set_index('api_record_id').loc[a.api_record_id]
 for scope in ['any','same']:
  vals=[]
  for s in trace[scope+'_ids']:
   ids=[int(v) for v in s.split('|')] if s else []
   vv=gainmap.loc[ids].to_numpy();n=int(np.isfinite(vv).sum())
   vals.append((n,int(np.nansum(vv)),float(np.nanmean(vv)) if n else np.nan))
  for j,col in enumerate(['late_n','late_gain2','late_mean']):a['h_'+scope+'_'+col]=[v[j] for v in vals]
  a['style_'+scope]=classify(a,scope)
  a['style_'+scope+'40']=classify(a,scope,.4)
  a['leaders_'+scope]=a['style_'+scope].eq('lead').groupby(a.race_id).transform('sum').astype(int)
  a['coverage_'+scope]=a['style_'+scope].ne('unknown').groupby(a.race_id).transform('mean')
 a['month']=a.race_date.str[5:7].astype(int)
 a['moisture']=pd.to_numeric(a.track_raw.str.extract(r'\((\d+)%\)',expand=False),errors='coerce')
 a['class_clean']=a.rank_class_raw.replace({'제1':'제1등급','제OPEN':'제오픈'}).fillna('unknown')
 # Historical ability context excludes the focal horse, and records missingness.
 for short,col in [('rank','h_any_finish_rank_mean'),('time','h_any_relative_time_mean')]:
  n=a[col].notna().groupby(a.race_id).transform('sum')-a[col].notna().astype(int)
  total=a[col].fillna(0).groupby(a.race_id).transform('sum')-a[col].fillna(0)
  a['opp_'+short+'_mean']=total/n.where(n>0)
 a.to_csv(out/'start_features.csv',index=False,encoding='utf-8-sig')
 save(out/'receipt.json',{'status':'completed','rows':len(a),'races':a.race_id.nunique(),'horses':a.horse_id.nunique(),'late_history_windows':2*len(a)})
 for scope in ['any','same']:print(scope,a['style_'+scope].value_counts().to_dict(),flush=True)
if __name__=='__main__':main()
