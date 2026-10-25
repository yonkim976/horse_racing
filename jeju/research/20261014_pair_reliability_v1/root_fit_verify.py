"""Independent reconstruction of approved fit objective and stationarity; no optimization."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit,logit

ROOT=Path(__file__).resolve().parents[3]
STUDY=Path(__file__).resolve().parent
OUT=STUDY/'outputs'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m


def load_inputs():
 approval=json.loads((OUT/'APPROVAL.json').read_text())
 for path,digest in approval['source_hashes'].items():assert sha(ROOT/path)==digest
 for key,path in [('plan_sha256',STUDY/'PLAN.md'),('source_preflight_sha256',OUT/'SOURCE_PREFLIGHT.json'),
 ('source_preflight_code_sha256',STUDY/'source_preflight.py'),('basis_sha256',STUDY/'pair_reliability_basis.py'),
 ('fit_code_sha256',STUDY/'pair_reliability_fit.py'),('design_dry_run_sha256',OUT/'DESIGN_DRY_RUN.json')]:assert sha(path)==approval[key]
 basic=module('root_frozen_basic_fit',ROOT/'jeju/research/20261012_pair_jockey_basic_v1/pair_jockey_fit.py')
 core,pair_fit,jockey_input,historical=basic.load_helpers()
 yearly,_=basic.prepare_training_rows(pair_fit,jockey_input,historical)
 feature=pd.read_parquet(ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet',
 columns=['api_record_id','race_id','race_date','horse_id','horse_number','distance_m','observed_starts',
 'same_starts','same_valid_times','valid_n5','mean5_s','std5_s','days_since_same'])
 for key in ['api_record_id','race_id','horse_id']:feature[key]=feature[key].astype('string')
 feature.race_date=pd.to_datetime(feature.race_date)
 for year,rows in yearly.items():
  merged=rows.merge(feature,on='api_record_id',validate='one_to_one',suffixes=('','_reference'))
  for key in ['race_id','race_date','horse_id','horse_number']:assert merged[key].eq(merged[key+'_reference']).all()
  assert len(merged)==len(rows)
  yearly[year]=merged
 docs={name:json.loads(path.read_text()) for name,path in {
 'baseline':ROOT/'jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/expanded_h1_fit.json',
 'basic':ROOT/'jeju/research/20261012_pair_jockey_basic_v1/outputs/FIT.json',
 'id':ROOT/'jeju/research/20261012_pair_jockey_id_v1/outputs/FIT.json'}.items()}
 own=module('root_independent_reliability_source',STUDY/'root_preflight.py')
 return basic,core,pair_fit,yearly,docs,own


def design(rows,year,basic,core,pair_fit,docs,own,mu,sd):
 base=next(f for f in docs['baseline']['folds'] if f['evaluation_year']==year)
 rolling=next(f for f in docs['basic']['folds'] if f['evaluation_year']==year)
 idfold=next(f for f in docs['id']['folds'] if f['evaluation_year']==year)
 runner_stats,pair_stats=basic.stats_from_baseline(core,base)
 races=pair_fit.build_races(core,rows,runner_stats)
 x21,p0,y,ids=basic.transform_candidate_basis(core,races,pair_stats,rolling['new_pair_moment'])
 cat=idfold['category_encoding'];vocab=cat['vocabulary_h1_only'];idx={j:k for k,j in enumerate(vocab)}
 pi=np.array([cat['pi'][j] for j in vocab]);sigma=np.array([cat['sigma'][j] for j in vocab]);assert (sigma>0).all()
 categorical=[]
 for r in races:
  by_number={int(row.horse_number):str(row.jockey_id) for row in r['rows'].itertuples()}
  for pair in r['pairs']:
   u=np.zeros(len(vocab));known=0
   for number in pair:
    k=idx.get(by_number[number])
    if k is not None:u[k]+=1;known+=1
   categorical.append((u-known*pi)/sigma)
 raw,weights,raw_ids=own.raw_matrix(rows)
 assert np.array_equal(ids,raw_ids)
 new=np.where(np.isfinite(raw),raw-mu,0)/sd
 x=np.column_stack([x21,np.asarray(categorical),new]);assert x.shape==(len(y),67) and np.isfinite(x).all()
 assert np.allclose(weights,core._race_pair_weights(ids),rtol=0,atol=1e-15)
 return x,p0,y,weights


def main():
 fit=json.loads((OUT/'FIT.json').read_text());receipt=json.loads((OUT/'FIT_RECEIPT.json').read_text())
 assert receipt['candidate_fit_sha256']==sha(OUT/'FIT.json')
 assert fit['h1_fit_count']==fit['h2_candidate_map_count']==3
 basic,core,pair_fit,yearly,docs,own=load_inputs()
 reference=json.loads((STUDY/'ROOT_PREFLIGHT_REFERENCE.json').read_text());checked=[]
 for fold in fit['folds']:
  year=fold['evaluation_year'];h1,h2=basic.split_h1_h2(yearly,year)
  expected=reference['folds'][str(year)]['new_basis_moments']
  mu=np.array([m['mean'] for m in expected.values()]);sd=np.array([m['scale_after_H1_mean_imputation'] for m in expected.values()])
  assert np.allclose(fold['new_basis_moments']['mean'],mu,rtol=0,atol=1e-12)
  assert np.allclose(fold['new_basis_moments']['scale'],sd,rtol=0,atol=1e-12)
  beta=np.array(fold['coefficients']);assert len(beta)==67 and len(fold['coefficient_order'])==67
  x,p0,y,w=design(h1,year,basic,core,pair_fit,docs,own,mu,sd)
  eta=logit(p0)+x@beta
  objective=float(w@(np.logaddexp(0,eta)-y*eta)+.5*(beta@beta))
  gradient=x.T@(w*(expit(eta)-y))+beta
  assert abs(objective-fold['optimizer']['objective'])<1e-11
  assert np.allclose(gradient,fold['optimizer']['gradient'],rtol=0,atol=1e-10)
  assert np.abs(gradient).max()<=core.ACCEPT_GRAD_INF
  x2,p02,y2,w2=design(h2,year,basic,core,pair_fit,docs,own,mu,sd)
  raw_eta2=logit(p02)+x2@beta
  A,B=fold['h2_candidate_platt']['A'],fold['h2_candidate_platt']['B'];assert B>0
  eta2=A+B*raw_eta2;residual=w2*(expit(eta2)-y2)
  calibration_objective=float(w2@(np.logaddexp(0,eta2)-y2*eta2))
  calibration_gradient=np.array([residual.sum(),residual@raw_eta2])
  for k,(value,bounds) in enumerate(zip([A,B],core.PLATT_BOUNDS)):
   assert bounds[0]<=value<=bounds[1]
   if value==bounds[0] and calibration_gradient[k]>=0:calibration_gradient[k]=0
   if value==bounds[1] and calibration_gradient[k]<=0:calibration_gradient[k]=0
  assert abs(calibration_objective-fold['h2_candidate_platt']['objective'])<1e-11
  assert np.abs(calibration_gradient).max()<=core.ACCEPT_GRAD_INF
  checked.append({'year':year,'h1_pairs':len(y),'h2_pairs':len(y2),'H1_objective':objective,
  'H1_gradient_inf':float(np.abs(gradient).max()),'H2_objective':calibration_objective,
  'H2_projected_gradient_inf':float(np.abs(calibration_gradient).max()),'new7moments_match_independent':True})
  print(json.dumps(checked[-1]),flush=True)
 review={'status':'PASS','scope':'Approved fit algebra/gradient and H1-only moments; no refit or performance selection',
 'folds':checked,'fit_sha256':sha(OUT/'FIT.json'),'fit_receipt_sha256':sha(OUT/'FIT_RECEIPT.json'),
 'approval_sha256':sha(OUT/'APPROVAL.json'),'new_optimizers_executed_by_reviewer':0,'horse_model_fits':0}
 (STUDY/'ROOT_FIT_REVIEW.json').write_text(json.dumps(review,indent=2)+'\n')


if __name__=='__main__':main()
