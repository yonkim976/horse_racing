"""Independent all-pair prediction reconstruction from reviewed saved coefficients."""
import itertools
import json
import numpy as np
import pandas as pd
from scipy.special import expit, logit
import root_fit_verify as audit


def main():
 basic,core,pair_fit,_,docs,own=audit.load_inputs()
 root,study,out=audit.ROOT,audit.STUDY,audit.OUT
 predictor=audit.module('root_frozen_expansion_predict',root/'jeju/research/20261011_pair_top3_oos_expansion_v1/pair_predict.py')
 jockey=audit.module('root_frozen_jockey_input_prediction',root/'jeju/research/20261012_pair_jockey_basic_v1/jockey_input.py')
 lock=json.loads((root/'jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/HISTORICAL_SOURCE_LOCK.json').read_text())
 source=pd.read_parquet(root/'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet')
 source.race_date=pd.to_datetime(source.race_date)
 starts=jockey.load_starts(include_results=True)
 fit=json.loads((out/'FIT.json').read_text())
 old=pd.read_parquet(root/'jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet')
 candidate=pd.read_parquet(out/'evaluation_pair_predictions.parquet')
 pd.testing.assert_frame_equal(old,candidate[old.columns])
 assert len(old.columns)==54 and len(candidate.columns)==58
 results=[]
 for fold in fit['folds']:
  year=fold['evaluation_year']
  rows,_=predictor.evaluation_runner_scores(year,source[predictor.EVAL_FEATURE_COLUMNS],lock)
  keep=['api_record_id','finish_position','observed_starts','same_starts','same_valid_times','valid_n5','mean5_s','std5_s','days_since_same']
  rows=rows.merge(source[keep],on='api_record_id',validate='one_to_one')
  for key in ['api_record_id','race_id','horse_id']:rows[key]=rows[key].astype('string')
  event=jockey.attach_event_jockey(rows,starts)
  rolling=jockey.rolling_features(event,starts)
  event=event.merge(rolling[['api_record_id','jockey365_field_relative_top3']],on='api_record_id',validate='one_to_one')
  mu=np.asarray(fold['new_basis_moments']['mean']);sd=np.asarray(fold['new_basis_moments']['scale'])
  x,p0,y,w=audit.design(event,year,basic,core,pair_fit,docs,own,mu,sd)
  keys=[];scores=[]
  for rid,g in event.groupby('race_id',sort=True):
   g=g.sort_values('horse_number');score=dict(zip(g.horse_number,g.score))
   for i,j in itertools.combinations(g.horse_number,2):keys.append((str(rid),int(i),int(j)));scores.append((score[i],score[j]))
  index=pd.MultiIndex.from_tuples(keys,names=['race_id','horse_i','horse_j'])
  saved=candidate[candidate.evaluation_year.eq(year)].copy()
  saved.race_id=saved.race_id.astype(str)
  saved=saved.set_index(['race_id','horse_i','horse_j']).loc[index]
  eta=logit(p0)+x@np.asarray(fold['coefficients'])
  raw=expit(eta);cal=expit(fold['h2_candidate_platt']['A']+fold['h2_candidate_platt']['B']*eta)
  assert np.allclose(saved.p0,p0,rtol=0,atol=1e-15)
  assert np.array_equal(saved[['score_i','score_j']].to_numpy(),np.asarray(scores))
  assert np.array_equal(saved.y_pair.to_numpy(),y)
  errors={name:float(np.max(np.abs(saved[name].to_numpy()-values))) for name,values in [
   ('reliability_candidate_eta',eta),('reliability_candidate_raw_probability',raw),('reliability_candidate_calibrated_probability',cal)]}
  assert max(errors.values())<1e-12
  expected=pd.DataFrame({'race_id':[k[0] for k in keys],'eta':eta})
  chosen=expected.groupby('race_id',sort=False).eta.idxmax()
  flags=np.zeros(len(expected),dtype=int);flags[chosen]=1
  assert np.array_equal(flags,saved.selected_reliability_candidate.to_numpy())
  results.append({'year':year,'pairs':len(y),'races':event.race_id.nunique(),'max_absolute_prediction_errors':errors,'all_selections_match':True})
 report={'status':'PASS','baseline_columns_preserved':54,'candidate_columns':58,'folds':results,
  'source_of_summary_48_column_misstatement':'Actual immutable SHA-pinned comparator has 54 columns; code and receipt preserve all 54.',
  'prediction_sha256':audit.sha(out/'evaluation_pair_predictions.parquet'),'prediction_receipt_sha256':audit.sha(out/'PREDICTION_RECEIPT.json'),
  'reviewer_optimizer_runs':0,'own_raw7_reconstruction':True,'fixed_horse_scores_preserved':True}
 (study/'ROOT_PREDICTION_REVIEW.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps(report))


if __name__=='__main__':main()
