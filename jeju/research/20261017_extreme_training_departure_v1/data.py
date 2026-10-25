"""Frozen inputs and prespecified bins for large personal training changes."""
from pathlib import Path
import hashlib,json,importlib.util
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
PREVIOUS=ROOT/'jeju/research/20261017_personal_training_departure_v1'
OLD=ROOT/'jeju/research/20261017_jockey_training_v1'
HELPER=ROOT/'jeju/research/20261017_jockey_training_individual_v1/verify.py'
IDS=['horse_id','jockey_id','trainer_id','owner_id']
BASE=['body_kg','carried_weight_kg','gate_scaled','h_any_finish_rank_mean','h_same_finish_rank_mean','h_any_relative_time_mean','h_same_relative_time_mean','h_any_n','h_same_n','previous_rank_fraction','previous_relative_time','log_gap']
LABELS=['big_decrease','moderate_decrease','usual','moderate_increase','big_increase']
ULTRA=['extreme_decrease','big_decrease','moderate_decrease','usual','moderate_increase','big_increase','extreme_increase']
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def save(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def module(name,p):
 spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def load():
 return pd.read_csv(OLD/'input01/starts.csv',dtype={c:str for c in IDS},low_memory=False),pd.read_csv(PREVIOUS/'input01/features.csv',dtype={'horse_id':str},low_memory=False)
def periods(a):return {'all':a,'2024_2025':a[a.year.between(2024,2025)],'2026':a[a.year.eq(2026)]}
def groups(values,kind,ultra=False):
 if kind=='days':
  if ultra:return np.select([values.le(-6),values.le(-4),values.le(-2),values.lt(2),values.lt(4),values.lt(6)],ULTRA[:-1],default=ULTRA[-1])
  return np.select([values.le(-4),values.le(-2),values.lt(2),values.lt(4)],LABELS[:-1],default=LABELS[-1])
 if ultra:return np.select([values.le(.25),values.le(.5),values.le(.75),values.lt(1.25),values.lt(1.5),values.lt(2)],ULTRA[:-1],default=ULTRA[-1])
 return np.select([values.le(.5),values.le(.75),values.lt(1.25),values.lt(1.5)],LABELS[:-1],default=LABELS[-1])
def sample(a,f,model,variant):
 w={'window7':7,'window28':28}.get(variant,14);size=10 if variant=='median10' else 5;p='usual'+str(size)+'_'
 z=f[f.window_days.eq(w)].drop(columns=['horse_id','race_date']);g=a.merge(z,on='api_record_id',validate='one_to_one')
 g=g[g.known_preparation&g[p+'supported']].copy()
 if variant=='short_gap':g=g[g.gap_days.le(90)].copy()
 if variant=='baseline_floor':g=g[g[p+'training_days'].ge(4)&g[p+'training_minutes'].ge(60)].copy()
 rate=variant=='opportunity_rate'
 g['days_departure']=(g.day_rate-g[p+'day_rate'])*(g.window_days-1) if rate else g.training_days-g[p+'training_days']
 g['minutes_ratio']=g.minute_rate/g[p+'minute_rate'] if rate else g.training_minutes/g[p+'training_minutes']
 g['daily_minutes_ratio']=g.minutes_per_observed_day/g[p+'minutes_per_observed_day']
 g['days_group']=groups(g.days_departure,'days',model=='ultra');g['minutes_group']=groups(g.minutes_ratio,'minutes',model=='ultra');g['daily_minutes_group']=groups(g.daily_minutes_ratio,'minutes')
 g['combo_group']=np.select([g.days_group.eq('usual')&g.minutes_group.eq('usual'),g.days_group.eq('big_decrease')&g.minutes_group.eq('big_decrease'),g.days_group.eq('big_increase')&g.minutes_group.eq('big_increase')],['usual','big_decrease','big_increase'],default='other')
 for c in ['training_days','training_minutes','minutes_per_observed_day','opportunity_days']:g['log_usual_'+c]=np.log1p(g[p+c])
 g['usual_history_n']=g[p+'n'];g['log_gap']=np.log1p(g.gap_days);g['log_current_days']=np.log1p(g.training_days);g['log_current_minutes']=np.log1p(g.training_minutes)
 g['analysis_unit']=g.horse_distance if variant=='horse_distance' else g.horse_distance+':'+g.jockey_id
 return g.reset_index(drop=True)
def main():
 out=HERE/'input01';out.mkdir(exist_ok=False)
 files=[HERE/'PLAN.md',PREVIOUS/'input01/features.csv',PREVIOUS/'input01/source_manifest.json',PREVIOUS/'verification01/verification.json',PREVIOUS/'data.py',OLD/'input01/starts.csv',OLD/'analysis.py',HELPER]
 for receipt in [PREVIOUS/'verification01/verification.json']:assert json.loads(receipt.read_text())['status']=='passed'
 prior=json.loads((PREVIOUS/'input01/source_manifest.json').read_text())
 for r in prior['files']:assert sha(ROOT/r['path'])==r['sha256'] and (ROOT/r['path']).stat().st_size==r['bytes'],r['path']
 save(out/'source_manifest.json',{'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'prior_preparation_and_baseline_SQL_verification_reused':True,'database_opened':False,'data_upper':'2026-09-19','partial_2026':True,'role_filter_used':False})
 a,f=load();census=[];classified=[]
 for period,z in periods(a).items():
  g=sample(z,f,'joint','primary');raw=f[f.window_days.eq(14)&f.api_record_id.isin(z.api_record_id)]
  assert len(g)=={'all':45021,'2024_2025':11280,'2026':4116}[period]
  census.append({'period':period,'source_starts':len(z),'eligible':len(g),'horses':g.horse_id.nunique(),'current_unobserved':int((~raw.known_preparation).sum()),'current_known_insufficient_history':int((raw.known_preparation&~raw.usual5_supported).sum()),'days_groups':g.days_group.value_counts().to_dict(),'minutes_groups':g.minutes_group.value_counts().to_dict(),'daily_minutes_groups':g.daily_minutes_group.value_counts().to_dict(),'combo_groups':g.combo_group.value_counts().to_dict()})
  if period=='all':
   cols=['api_record_id','horse_id','race_date','history_cutoff','window_start','window_end','training_days','training_minutes','opportunity_days','usual5_ids','usual5_n','usual5_training_days','usual5_training_minutes','days_departure','minutes_ratio','daily_minutes_ratio','days_group','minutes_group','daily_minutes_group','combo_group'];classified=g[cols]
 classified.to_csv(out/'primary_groups.csv',index=False,encoding='utf-8-sig');save(out/'denominator_census.json',census)
 print(json.dumps(census,ensure_ascii=False,indent=2),flush=True)
if __name__=='__main__':main()
