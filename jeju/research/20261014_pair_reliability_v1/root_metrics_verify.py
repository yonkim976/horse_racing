"""Independent loss, subgroup and frozen-date bootstrap review. No fitting."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
STUDY=Path(__file__).resolve().parent
OUT=STUDY/'outputs'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
 p=pd.read_parquet(OUT/'evaluation_pair_predictions.parquet')
 p.race_id=p.race_id.astype(str)
 base=p[p.selected_jockey_id_candidate.eq(1)].set_index('race_id').sort_index()
 chosen=p[p.selected_reliability_candidate.eq(1)].set_index('race_id').loc[base.index]
 r=base[['race_date','evaluation_year','distance_m']].copy()
 r.race_date=pd.to_datetime(r.race_date).dt.strftime('%Y-%m-%d')
 r['baseline_fixed_hit']=base.y_pair
 r['candidate_selected_hit']=chosen.y_pair
 r['candidate_minus_baseline_selected_hit']=chosen.y_pair-base.y_pair
 r['selection_changed']=(base.horse_i!=chosen.horse_i)|(base.horse_j!=chosen.horse_j)
 for name,flag in [('raw_top2','selected_raw_top2'),('jockey_basic','selected_jockey_basic_candidate')]:
  r[name+'_hit']=p[p[flag].eq(1)].set_index('race_id').loc[base.index].y_pair
  r['candidate_minus_'+name+'_hit']=r.candidate_selected_hit-r[name+'_hit']
 prob={'baseline':'jockey_id_candidate_calibrated_probability','raw':'reliability_candidate_raw_probability',
       'calibrated':'reliability_candidate_calibrated_probability'}
 for name,col in prob.items():
  prefix={'baseline':'baseline_fixed','raw':'candidate_fixed_raw','calibrated':'candidate_fixed_calibrated'}[name]
  for measure,values in [('brier',(base[col]-base.y_pair)**2),('log_loss',-(base.y_pair*np.log(base[col])+(1-base.y_pair)*np.log1p(-base[col])))]:
   r[prefix+'_'+measure]=values
  prefix={'baseline':'baseline_all_pair','raw':'candidate_raw_all_pair','calibrated':'candidate_calibrated_all_pair'}[name]
  for measure,values in [('brier',(p[col]-p.y_pair)**2),('log_loss',-(p.y_pair*np.log(p[col])+(1-p.y_pair)*np.log1p(-p[col])))]:
   r[prefix+'_'+measure]=values.groupby(p.race_id).mean().loc[r.index]
 for kind in ['fixed_raw','fixed_calibrated','raw_all_pair','calibrated_all_pair']:
  ref='baseline_fixed' if kind.startswith('fixed') else 'baseline_all_pair'
  for measure in ['brier','log_loss']:r['candidate_'+kind+'_minus_baseline_'+measure]=r['candidate_'+kind+'_'+measure]-r[ref+'_'+measure]
 f=pd.read_parquet(ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet')
 f.race_id=f.race_id.astype(str);f=f.set_index(['race_id','horse_number'])
 bins=[0,2,5,10,np.inf];names=['0','1-2','3-5','6-10','11+']
 for stem,col in [('observed_career_subgroup','observed_starts'),('same_valid_time_subgroup','same_valid_times')]:
  values=[]
  for rid,row in base.iterrows():values.append(min(f.loc[(rid,int(row.horse_i)),col],f.loc[(rid,int(row.horse_j)),col]))
  r[stem]=[names[int(np.searchsorted(bins,v,side='left'))] for v in values]
 saved=pd.read_csv(OUT/'report/paired_race_metrics.csv',dtype={'race_id':str}).set_index('race_id').loc[r.index]
 for col in r:
  if r[col].dtype.kind in 'biuf':assert np.allclose(saved[col],r[col],rtol=0,atol=1e-12),col
  else:assert saved[col].astype(str).eq(r[col].astype(str)).all(),col
 dates=sorted(pd.to_datetime(p.race_date).dt.strftime('%Y-%m-%d').unique())
 schedule=np.load(ROOT/'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy',allow_pickle=False)
 weights=np.stack([np.bincount(draw,minlength=len(dates)) for draw in schedule])
 date_index=np.array([dates.index(d) for d in r.race_date])
 mapping={('reliability_selected_vs_jockey_id','hit_rate_difference'):'candidate_minus_baseline_selected_hit',
 ('reliability_selected_vs_raw_top2','hit_rate_difference'):'candidate_minus_raw_top2_hit',
 ('reliability_selected_vs_jockey_basic','hit_rate_difference'):'candidate_minus_jockey_basic_hit'}
 for kind,comparison in [('fixed_calibrated','candidate_fixed_calibrated_vs_baseline_fixed'),('fixed_raw','candidate_fixed_raw_vs_baseline_fixed'),
 ('calibrated_all_pair','candidate_all_pair_calibrated_vs_baseline'),('raw_all_pair','candidate_all_pair_raw_vs_baseline')]:
  for measure in ['brier','log_loss']:mapping[(comparison,measure+'_difference')]='candidate_'+kind+'_minus_baseline_'+measure
 ci=pd.read_csv(OUT/'report/bootstrap_ci.csv',dtype={'group':str})
 reference=[]
 for row in ci.itertuples():
  if row.group_type=='overall':mask=np.ones(len(r),bool)
  elif row.group_type=='year':mask=r.evaluation_year.eq(int(row.group)).to_numpy()
  elif row.group_type=='distance_m':mask=r.distance_m.eq(int(row.group)).to_numpy()
  else:mask=r[{'observed_career_min_pair':'observed_career_subgroup','same_distance_valid_times_min_pair':'same_valid_time_subgroup'}[row.group_type]].eq(row.group).to_numpy()
  assert mask.sum()==row.races
  col=mapping[(row.comparison,row.metric)]
  counts=np.bincount(date_index[mask],minlength=len(dates));sums=np.bincount(date_index[mask],weights=r[col].to_numpy()[mask],minlength=len(dates))
  den=weights@counts;valid=den>0;draws=(weights@sums)[valid]/den[valid]
  bounds=np.quantile(draws,[.025,.975]) if valid.any() else np.array([np.nan,np.nan])
  estimate=r.loc[mask,col].mean()
  assert np.allclose([row.estimate,row.ci_low,row.ci_high],[estimate,*bounds],rtol=0,atol=1e-12,equal_nan=True)
  assert row.valid_draws==valid.sum() and row.undefined_draws==len(valid)-valid.sum()
  if row.group_type=='overall':reference.append({'comparison':row.comparison,'metric':row.metric,'estimate':estimate,'ci_low':bounds[0],'ci_high':bounds[1]})
 odds=pd.read_csv(ROOT/'jeju/research/20261013_postrace_ev_exploration_v1/race_rows.csv',dtype={'race_id':str})
 odds=odds[odds.selector.eq('jockey_id_candidate')].set_index('race_id')
 od=base.loc[odds.index];assert len(od)==1142
 table=pd.read_csv(OUT/'report/posthoc_odds_calibration.csv')
 for label,lo,hi in [('[1,2)',1,2),('[2,3)',2,3),('[3,5)',3,5),('[5,10)',5,10),('[10,inf)',10,np.inf)]:
  mask=odds.final_quote.ge(lo)&odds.final_quote.lt(hi);row=table[table.price_bin.eq(label)].iloc[0]
  assert row.races==mask.sum() and row.hits==od.loc[mask].y_pair.sum()
  actual=od.loc[mask].y_pair.mean();old=od.loc[mask,prob['baseline']].mean();new=od.loc[mask,prob['calibrated']].mean()
  assert np.allclose([row.observed_hit_rate,row.baseline_fixed_p_mean,row.candidate_calibrated_p_mean,row.baseline_probability_minus_hit_gap,row.candidate_probability_minus_hit_gap],[actual,old,new,old-actual,new-actual],rtol=0,atol=1e-12)
 summary_rows=0
 for file in ['summary.csv','subgroup_summary.csv']:
  for row in pd.read_csv(OUT/'report'/file,dtype={'group':str}).itertuples():
   if row.group_type=='overall':part=r
   elif row.group_type=='year':part=r[r.evaluation_year.eq(int(row.group))]
   elif row.group_type=='distance_m':part=r[r.distance_m.eq(int(row.group))]
   else:part=r[r[{'observed_career_min_pair':'observed_career_subgroup','same_distance_valid_times_min_pair':'same_valid_time_subgroup'}[row.group_type]].eq(row.group)]
   assert len(part)==row.races and part.race_date.nunique()==row.dates
   if len(part):
    sums={'baseline_selected_hits':'baseline_fixed_hit','candidate_selected_hits':'candidate_selected_hit','selections_changed':'selection_changed'}
    means={'baseline_selected_hit_rate':'baseline_fixed_hit','candidate_selected_hit_rate':'candidate_selected_hit','candidate_minus_baseline_hit_rate':'candidate_minus_baseline_selected_hit',
     'fixed_brier_difference':'candidate_fixed_calibrated_minus_baseline_brier','fixed_log_loss_difference':'candidate_fixed_calibrated_minus_baseline_log_loss',
     'all_pair_brier_difference':'candidate_calibrated_all_pair_minus_baseline_brier','all_pair_log_loss_difference':'candidate_calibrated_all_pair_minus_baseline_log_loss',
     'candidate_all_pair_calibrated_brier':'candidate_calibrated_all_pair_brier','candidate_all_pair_calibrated_log_loss':'candidate_calibrated_all_pair_log_loss'}
    for name,col in sums.items():assert getattr(row,name)==part[col].sum()
    for name in row._fields:
     col=means.get(name,name)
     if col in part and ('brier' in name or 'log_loss' in name or name in means):assert abs(getattr(row,name)-part[col].mean())<1e-12
    assert row.gains==part.candidate_minus_baseline_selected_hit.eq(1).sum()
    assert row.losses==part.candidate_minus_baseline_selected_hit.eq(-1).sum()
   summary_rows+=1
 changed=pd.read_csv(OUT/'report/changed_selections.csv',dtype={'race_id':str}).set_index('race_id')
 assert set(changed.index)==set(r.index[r.selection_changed])
 for rid,row in changed.iterrows():assert row.selection_outcome=={1:'gain',-1:'loss',0:'tie'}[int(r.loc[rid,'candidate_minus_baseline_selected_hit'])]
 report=json.loads((OUT/'REPORT.json').read_text());receipt=json.loads((OUT/'REPORT_RECEIPT.json').read_text())
 assert receipt['report_sha256']==sha(OUT/'REPORT.json')
 for name,item in report['output_hashes'].items():assert sha(STUDY/name)==item['sha256'] and (STUDY/name).stat().st_size==item['bytes']
 fixed=[v for v in reference if v['comparison']=='candidate_fixed_calibrated_vs_baseline_fixed']
 hit=next(v for v in reference if v['comparison']=='reliability_selected_vs_jockey_id')
 primary=all(v['estimate']<0 for v in fixed) and any(v['ci_high']<0 for v in fixed)
 selection=hit['estimate']>=0 and hit['ci_low']>0
 guard=all(v['estimate']<=0 for v in reference if v['comparison']=='candidate_all_pair_calibrated_vs_baseline')
 assert (report['improvement_status']=='PASS')==(primary and selection and guard)
 review={'status':'PASS','scope':'Independent calculation/source review, not confirmed improvement',
 'report_sha256':sha(OUT/'REPORT.json'),'report_receipt_sha256':sha(OUT/'REPORT_RECEIPT.json'),
 'checked_races':len(r),'checked_pair_rows':len(p),'summary_rows_verified':summary_rows,'changed_races_verified':len(changed),'bootstrap_rows_verified':len(ci),'bootstrap_bounds_verified':2*len(ci),'odds_bins_verified':5,
 'fixed_probability_gate_passed':bool(primary),'selection_improvement_confirmed':bool(selection),'all_pair_guardrail_passed':bool(guard),
 'old_hits':int(r.baseline_fixed_hit.sum()),'new_hits':int(r.candidate_selected_hit.sum()),'overall_independent_ci':reference,
 'reviewer_refits':0,'horse_scores_unchanged':True,'operating_model_or_DB_changed':False,
 'reviewed_output_sha256':{n:sha(STUDY/n) for n in ['README.md','ARTIFACT_MANIFEST.json','outputs/REPORT.json','outputs/REPORT_RECEIPT.json',*[str(x.relative_to(STUDY)) for x in (OUT/'report').glob('*.csv')]]}}
 (STUDY/'ROOT_REVIEW.json').write_text(json.dumps(review,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
 print(json.dumps(review,ensure_ascii=False))

if __name__=='__main__':main()
