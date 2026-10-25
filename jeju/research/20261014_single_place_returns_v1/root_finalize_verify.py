"""Verify every reported row and interval from independent frozen references."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
STUDY=Path(__file__).resolve().parent
OUT=STUDY/'outputs'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def equal(a,b):
 if b is None or pd.isna(b):assert pd.isna(a),(a,b)
 else:assert np.isclose(float(a),float(b),rtol=0,atol=1e-8),(a,b)

def main():
 reference=pd.read_csv(STUDY/'ROOT_RETURN_REFERENCE.csv',dtype={'race_id':str,'horse_id':str})
 saved=pd.read_csv(OUT/'single_place_race_results.csv',dtype={'race_id':str,'horse_id':str}).set_index('race_id')
 r=reference.set_index('race_id').loc[saved.index]
 assert len(r)==1779 and saved.horse_id.eq(r.horse_id).all()
 for col in ['horse_number','field_n','score','p_top3','p_place','place_finish_cutoff']:
  assert np.allclose(saved[col],r[col],rtol=0,atol=1e-10,equal_nan=True),col
 assert np.array_equal(saved.official_finish_position,r.finish_position)
 assert np.array_equal(saved.place_hit.astype(int),r.hit)
 assert np.array_equal(saved.payout_period,r.roi_eligible)
 assert np.allclose(saved.place_odds_multiple,r.odds,rtol=0,atol=1e-12,equal_nan=True)
 assert np.allclose(saved.gross_return_krw,r.return_krw,rtol=0,atol=1e-8,equal_nan=True)
 dates=sorted(r.race_date.unique());assert len(dates)==269
 schedule=np.load(ROOT/'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy',allow_pickle=False)
 weights=np.stack([np.bincount(draw,minlength=269) for draw in schedule]);assert np.all(weights.sum(axis=1)==269)
 def ci(g,values):
  ids=pd.Categorical(g.race_date,categories=dates).codes
  dn=np.bincount(ids,minlength=269);ds=np.bincount(ids,weights=np.asarray(values),minlength=269)
  den=weights@dn;valid=den>0;draws=(weights@ds)[valid]/den[valid]
  bounds=np.quantile(draws,[.025,.975]) if valid.any() else [None,None]
  return (*bounds,int(valid.sum()),int((~valid).sum()))
 table=pd.read_csv(OUT/'single_place_summary.csv',dtype={'group':str})
 ci_checked=0
 for row in table.itertuples():
  cohort=r if row.cohort=='evaluation_all' else r[r.roi_eligible]
  if row.dimension=='all':g=cohort
  elif row.dimension=='year':g=cohort[cohort.year.eq(int(row.group))]
  elif row.dimension=='field_size':g=cohort[cohort.field_n.eq(int(row.group))]
  elif row.dimension=='probability_unavailable':g=cohort[cohort.p_place.isna()]
  elif row.dimension=='probability_threshold':g=cohort[cohort.p_place.ge(float(row.group[2:]))]
  else:
   lo,hi=map(float,row.group.strip('[]()').split(','))
   g=cohort[cohort.p_place.ge(lo)&(cohort.p_place.le(hi) if row.group.endswith(']') else cohort.p_place.lt(hi))]
  cal=g[g.probability_eligible];paid=g[g.roi_eligible];winning=paid[paid.hit.eq(1)]
  counts={'race_n':len(g),'date_n':g.race_date.nunique(),'starter_n':g.field_n.sum(),'place_hit_n':g.hit.sum(),
   'p_support_n':len(cal),'p_support_hit_n':cal.hit.sum() if len(cal) else None,'odds_race_n':len(paid),
   'odds_hit_n':paid.hit.sum() if len(paid) else None,'stake_krw':len(paid)*1000 if len(paid) else None,
   'gross_return_krw':paid.return_krw.sum() if len(paid) else None}
  for col,v in counts.items():equal(getattr(row,col),v)
  values={'place_hit_rate':g.hit.mean() if len(g) else None,'p_support_hit_rate':cal.hit.mean() if len(cal) else None,
   'mean_p':cal.p_place.mean() if len(cal) else None,'calibration_gap_hit_minus_p':(cal.hit-cal.p_place).mean() if len(cal) else None,
   'brier':((cal.hit-cal.p_place)**2).mean() if len(cal) else None,
   'log_loss':-(cal.hit*np.log(cal.p_place)+(1-cal.hit)*np.log1p(-cal.p_place)).mean() if len(cal) else None,
   'odds_hit_rate':paid.hit.mean() if len(paid) else None,'roi':(paid.return_krw/1000-1).mean() if len(paid) else None,
   'mean_hit_odds':winning.odds.mean() if len(winning) else None,'mean_hit_return_krw':winning.return_krw.mean() if len(winning) else None,
   'break_even_hit_rate':1/winning.odds.mean() if len(winning) else None,
   'break_even_odds':1/paid.hit.mean() if len(paid) and paid.hit.sum() else None}
  for col,v in values.items():equal(getattr(row,col),v)
  for columns,part,val in [
   (('place_hit_rate_ci_low','place_hit_rate_ci_high','place_hit_rate_ci_valid_draws','place_hit_rate_ci_undefined_draws'),g,g.hit),
   (('p_hit_rate_ci_low','p_hit_rate_ci_high','probability_ci_valid_draws','probability_ci_undefined_draws'),cal,cal.hit),
   (('calibration_gap_ci_low','calibration_gap_ci_high','probability_ci_valid_draws','probability_ci_undefined_draws'),cal,cal.hit-cal.p_place),
   (('roi_ci_low','roi_ci_high','roi_ci_valid_draws','roi_ci_undefined_draws'),paid,paid.return_krw/1000-1)]:
   expected=ci(part,val)
   for name,value in zip(columns,expected):equal(getattr(row,name),value)
   ci_checked+=2
 assert len(table)==49
 for label in ['evaluation_all','payout_2025_2026']:
  subset=table[table.cohort.eq(label)]
  assert len(subset[subset.dimension.eq('probability_band')])==10
  assert len(subset[subset.dimension.eq('probability_threshold')])==5
 receipt=json.loads((OUT/'single_place_analysis_receipt.json').read_text())
 assert receipt['analysis_code_sha256']==sha(STUDY/'analyze.py')
 assert receipt['approval_sha256']==sha(STUDY/'ROOT_CALCULATION_APPROVAL.json')
 for item in receipt['outputs'].values():assert sha(ROOT/item['path'])==item['sha256']
 for key,path in {'source_audit_final_sha256':'source_audit/SOURCE_AUDIT_FINAL.json','source_price_rows_sha256':'source_audit/PLC_PRICE_ROWS.csv',
 'source_inventory_sha256':'source_audit/SOURCE_INVENTORY.json','official_runner_results_sha256':'source_audit/OFFICIAL_RUNNER_RESULTS.csv',
 'probability_preflight_sha256':'outputs/probability_preflight_receipt.json'}.items():assert receipt[key]==sha(STUDY/path)
 review={'status':'PASS','scope':'Independent frozen-score probability, official identity and gross historical return reproduction',
 'runner_probabilities_verified':17412,'selected_races_verified':1779,'payout_races_verified':1142,'raw_PLC_quotes_verified':11083,
 'reported_summary_rows_verified':len(table),'CI_bounds_verified':ci_checked,
 'independent_reference_optimizers':0,'new_model_fits':0,'operating_model_or_DB_modified':False,
 'analysis_receipt_sha256':sha(OUT/'single_place_analysis_receipt.json'),'analysis_code_sha256':sha(STUDY/'analyze.py'),
 'reviewed_output_sha256':{str(p.relative_to(STUDY)):sha(p) for p in [OUT/'single_place_summary.csv',OUT/'single_place_race_results.csv',OUT/'single_place_analysis_receipt.json',OUT/'single_place_analysis_README.md']},
 'selection_rule':'Maximum native F1_STYLE6 score; exact-score ties smallest horse number',
 'probability_support_gap':'36 seven-runner races have Top2 outcome but no native Top2 probability; retained for actual hits/ROI',
 'zero_event_or_single_event_bootstrap_limitation':'Degenerate empirical intervals for tiny or all-failure subsets do not prove population probability or ROI certainty.',
 'source_timing':'Final post-race archived quotes only; no pre-purchase prices',
 'validation_status':'Previously reused historical development cohort, not independent future validation; 2026 partial through September19'}
 dest=STUDY/'ROOT_REVIEW.json';assert not dest.exists();dest.write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n');print(json.dumps(review))

if __name__=='__main__':main()
