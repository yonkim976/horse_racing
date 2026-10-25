"""Independently reconstruct fixed pair contexts and calibration diagnostics."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
STUDY=Path(__file__).resolve().parent
PINS={
 'jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet':'0d41ee66149edfae79f2b422ba588c422686a328aad0122071183ee9db6768d6',
 'jeju/research/20261013_postrace_ev_exploration_v1/race_rows.csv':'4fc2e924dcf4f987c22962977d42dd83a786bebc2f70606bc565bd97d2869198',
 'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet':'036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f',
 'jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/evaluation_scores.parquet':'45247f00f286197067957d25ee46e0594f2ef0d26089c6b6081592272651eb12',
 'jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/evaluation_scores.parquet':'0ccae2475fc1ea87ddf62b054572961ab32fed26b332070907853ebbd412989a',
 'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy':'d141b0c3f9a463cbfc9d1f4c61228b58757c31aee4ec74b79f41c5baeadaccbd'}
ODDS_LABELS=['[1,2)','[2,3)','[3,5)','[5,10)','[10,inf)']
PROB_LABELS=['[0,0.15)','[0.15,0.20)','[0.20,0.30)','[0.30,0.40)','[0.40,1]']


def sha(b):return hashlib.sha256(b).hexdigest()


def equivalent(got,want):
 if want is None or pd.isna(want):assert pd.isna(got),(got,want)
 else:assert math.isclose(float(got),float(want),rel_tol=0,abs_tol=1e-8),(got,want)


def reconstruct():
 for path,digest in PINS.items():assert sha((ROOT/path).read_bytes())==digest
 paths=list(PINS)
 full=pd.read_parquet(ROOT/paths[0]);prior=pd.read_csv(ROOT/paths[1]);feature=pd.read_parquet(ROOT/paths[2])
 feature=feature.loc[feature.year.isin([2025,2026])].copy()
 scores=pd.concat([pd.read_parquet(ROOT/p) for p in paths[3:5]])
 assert len(feature)==len(scores)==11083
 feature=feature.merge(scores,on='api_record_id',validate='one_to_one')
 assert feature.score.notna().all()
 assert (pd.to_datetime(feature.race_date)-pd.to_datetime(feature.history_cutoff)).dt.days.eq(2).all()
 observed=feature.latest_history_date.notna()
 assert (pd.to_datetime(feature.loc[observed,'latest_history_date'])<=pd.to_datetime(feature.loc[observed,'history_cutoff'])).all()
 feature['score_rank']=feature.groupby('race_id').score.rank(method='min',ascending=False)
 assert not feature.duplicated(['race_id','horse_number']).any()
 methods={'jockey_id_candidate':('selected_jockey_id_candidate','jockey_id_candidate_calibrated_probability'),
 'jockey_basic_candidate':('selected_jockey_basic_candidate','candidate_calibrated_probability')}
 frames={}
 cols=['horse_id','finish_position','distance_m','grade_raw','field_n','observed_starts','same_valid_times',
 'days_since_start','hist_s1f_relpos_mean5','score','score_rank','history_cutoff','latest_history_date']
 for name,(flag,pcol) in methods.items():
  selected=full.loc[full[flag].eq(1)&full.evaluation_year.isin([2025,2026])]
  t=prior.loc[prior.selector.eq(name)].merge(selected[['race_id','horse_i','horse_j',pcol,'score_i','score_j','y_pair']],on='race_id',validate='one_to_one')
  assert len(t)==1142 and t.race_id.is_unique and np.allclose(t.p,t[pcol],rtol=0,atol=1e-14)
  for side in ['i','j']:
   table=feature[['race_id','horse_number']+cols].rename(columns={c:c+'_'+side for c in ['horse_number']+cols})
   t=t.merge(table,left_on=['race_id','horse_'+side],right_on=['race_id','horse_number_'+side],validate='one_to_one')
   assert np.allclose(t['score_'+side+'_x'],t['score_'+side+'_y'],rtol=0,atol=1e-14)
  for col in ['distance_m','grade_raw','field_n']:
   assert t[col+'_i'].eq(t[col+'_j']).all();t[col]=t[col+'_i']
  t['career_min']=t[['observed_starts_i','observed_starts_j']].min(axis=1,skipna=False)
  t['same_min']=t[['same_valid_times_i','same_valid_times_j']].min(axis=1,skipna=False)
  t['rest_max']=t[['days_since_start_i','days_since_start_j']].max(axis=1,skipna=False)
  t['score_gap']=(t.score_i_x-t.score_j_x).abs()
  t['weak_rank']=t[['score_rank_i','score_rank_j']].max(axis=1)
  t['top3_count']=t.finish_position_i.le(3).astype(int)+t.finish_position_j.le(3).astype(int)
  assert t.top3_count.eq(2).astype(int).eq(t.hit).all() and t.hit.eq(t.y_pair).all()
  assert t.final_quote.ge(1).all() and not t.final_quote.eq(9999.9).any()
  t['odds_bin']=pd.cut(t.final_quote,[1,2,3,5,10,np.inf],right=False,labels=ODDS_LABELS).astype(str)
  t['prob_bin']=pd.cut(t.p,[0,.15,.20,.30,.40,np.inf],right=False,labels=PROB_LABELS).astype(str)
  t['distance']=t.distance_m.astype(int).astype(str);t['grade']=t.grade_raw
  t['field']=np.select([t.field_n.le(8),t.field_n.eq(9),t.field_n.eq(10)],['<=8','9','10'],default='>=11')
  t['career']=pd.cut(t.career_min,[-1,0,2,9,np.inf],labels=['0','1-2','3-9','10+']).astype(str)
  t['same']=pd.cut(t.same_min,[-1,0,2,np.inf],labels=['0','1-2','3+']).astype(str)
  t['rest']=pd.cut(t.rest_max,[-1,14,35,60,np.inf],labels=['<=14','15-35','36-60','61+']).astype('string').fillna('unknown')
  t['score_gap_group']=pd.cut(t.score_gap,[0,.5,1,np.inf],right=False,labels=['[0,0.5)','[0.5,1)','[1,inf)']).astype(str)
  unknown=t.hist_s1f_relpos_mean5_i.isna()|t.hist_s1f_relpos_mean5_j.isna()
  both=t.hist_s1f_relpos_mean5_i.le(.33)&t.hist_s1f_relpos_mean5_j.le(.33)
  t['front']=np.select([unknown,both],['missing','both_low'],default='observed_other')
  frames[name]=t
 dates=sorted(full.race_date.unique());schedule=np.load(ROOT/paths[-1],allow_pickle=False)
 assert len(dates)==269 and schedule.shape==(2000,269) and schedule.dtype==np.int32
 weights=np.stack([np.bincount(x,minlength=269) for x in schedule])
 return frames,dates,weights


def metrics(frame,dates,weights,ci=True):
 n=len(frame);hits=int(frame.hit.sum());p=frame.p.to_numpy();y=frame.hit.to_numpy();cp=np.clip(p,1e-15,1-1e-15)
 out={'n':n,'hits':hits,'p_mean':float(p.mean()) if n else None,'hit_rate_pct':hits/n*100 if n else None,
 'gap_pp':(p.mean()-hits/n)*100 if n else None,'oe':hits/p.sum() if n and p.sum()>0 else None,
 'brier':float(np.mean((p-y)**2)) if n else None,'logloss':float(-np.mean(y*np.log(cp)+(1-y)*np.log1p(-cp))) if n else None,
 'both_top3':int(frame.top3_count.eq(2).sum()),'one_top3':int(frame.top3_count.eq(1).sum()),'neither_top3':int(frame.top3_count.eq(0).sum())}
 if ci:
  ids=pd.Categorical(frame.race_date,categories=dates).codes
  dn=np.bincount(ids,minlength=269);de=np.bincount(ids,weights=p-y,minlength=269)
  bn,be=weights@dn,weights@de;valid=bn>0
  bounds=np.quantile(be[valid]/bn[valid]*100,[.025,.975]).tolist() if valid.any() else [None,None]
  out.update(gap_ci_low_pp=bounds[0],gap_ci_high_pp=bounds[1],empty_draws=int((~valid).sum()))
 return out


def check_outputs(frames,dates,weights):
 families={'distance':'distance','grade_raw':'grade','field_n':'field','min_observed_starts':'career',
 'min_same_valid_times':'same','max_days_since_start':'rest','f1_score_gap':'score_gap_group','front_history_overlap':'front'}
 def level(value):return str(value).replace('[0,.5)','[0,0.5)').replace('[.5,1)','[0.5,1)')
 def pband(value):return str(value).replace('[0,.15)','[0,0.15)').replace('[.15,.20)','[0.15,0.20)').replace('[.20,.30)','[0.20,0.30)').replace('[.30,.40)','[0.30,0.40)').replace('[.40,1]','[0.40,1]')
 def scope(selector,period):
  f=frames[selector]
  return f if period=='all' else f.loc[f.year.eq(int(str(period)[:4]))]
 def group_filter(f,group):
  if group=='posthoc_score_ge_0':return f.ev_proxy.ge(0)
  if group=='p_ge_030_and_score_ge_010':return f.p.ge(.3)&f.ev_proxy.ge(.1)
  if group=='p_ge_030_and_score_ge_020':return f.p.ge(.3)&f.ev_proxy.ge(.2)
  raise AssertionError(group)
 context=pd.read_csv(STUDY/'pair_context.csv',dtype={'horse_id_i':str,'horse_id_j':str}).set_index(['selector','race_id'])
 assert len(context)==2284 and context.index.is_unique
 context_columns={'score_i':'score_i_x','score_j':'score_j_x','weak_score_rank':'weak_rank','score_gap_abs':'score_gap',
 'min_observed_starts':'career_min','min_same_valid_times':'same_min','posthoc_score':'ev_proxy',
 'distance_m':'distance_m','field_n':'field_n','p':'p','final_quote':'final_quote','hit':'hit'}
 for selector,f in frames.items():
  g=context.loc[selector].reindex(f.race_id)
  assert g.index.is_unique and g.p.notna().all()
  for target,source in context_columns.items():assert np.allclose(g[target],f[source],rtol=0,atol=1e-12,equal_nan=True),(target,source)
  for target,source in [('grade_raw','grade'),('odds_band','odds_bin'),('style_overlap_condition','front'),
   ('observed_starts_condition','career'),('same_valid_times_condition','same'),('days_since_start_condition','rest')]:
   assert g[target].astype(str).tolist()==f[source].astype(str).tolist(),target
  for side in ['i','j']:
   assert g['horse_id_'+side].tolist()==f['horse_id_'+side].astype(str).tolist()
   for col in ['finish_position','observed_starts','same_valid_times','days_since_start','hist_s1f_relpos_mean5','score_rank']:
    assert np.allclose(g[col+'_'+side],f[col+'_'+side],rtol=0,atol=1e-12,equal_nan=True)
  assert g.both_top3.astype(int).to_numpy().tolist()==f.top3_count.eq(2).astype(int).tolist()
  assert g.exactly_one_top3.astype(int).tolist()==f.top3_count.eq(1).astype(int).tolist()
  assert g.neither_top3.astype(int).tolist()==f.top3_count.eq(0).astype(int).tolist()
  assert g.probability_band.map(pband).tolist()==f.prob_bin.tolist()
  assert g.source_hash.tolist()==f.source_hash.tolist()
 names={'n':'n','hits':'hits','p_mean':'p_mean','hit_rate_pct':'hit_rate_pct','gap_pp':'gap_pp','o_e_ratio':'oe',
 'brier':'brier','log_loss':'logloss','both_top3':'both_top3','exactly_one_top3':'one_top3','neither_top3':'neither_top3'}
 counts={};ci_limits=0
 for table in ['odds_calibration','probability_odds_cells','condition_calibration','condition_odds_cells','selected_group_diagnostics']:
  data=pd.read_csv(STUDY/(table+'.csv'),dtype={'period':str,'condition_value':str})
  seen=set()
  for row in data.itertuples():
   f=scope(row.selector,row.period)
   key=[row.selector,row.period]
   if table.startswith('condition_'):
    key += [row.condition_family,level(row.condition_value)]
    f=f.loc[f[families[row.condition_family]].astype(str).eq(level(row.condition_value))]
   if table=='probability_odds_cells':
    key += [pband(row.probability_band)];f=f.loc[f.prob_bin.eq(pband(row.probability_band))]
   if table=='selected_group_diagnostics':
    key += [row.group_id];f=f.loc[group_filter(f,row.group_id)]
   if hasattr(row,'odds_band'):
    key += [row.odds_band]
    if row.odds_band!='all':f=f.loc[f.odds_bin.eq(row.odds_band)]
   key=tuple(key);assert key not in seen,(table,key);seen.add(key)
   with_ci=(table in ['odds_calibration','condition_calibration'] or table=='selected_group_diagnostics' and row.odds_band=='all')
   ref=metrics(f,dates,weights,with_ci)
   for target,source in names.items():equivalent(getattr(row,target),ref[source])
   if with_ci:
    equivalent(row.gap_ci95_low_pp,ref['gap_ci_low_pp']);equivalent(row.gap_ci95_high_pp,ref['gap_ci_high_pp'])
    assert row.bootstrap_zero_denominator_replicates==ref['empty_draws']
    assert row.bootstrap_replicates+row.bootstrap_zero_denominator_replicates==2000
    ci_limits+=2
  expected=set()
  for selector in frames:
   for period in ['all','2025','2026_partial']:
    f=scope(selector,period)
    if table=='odds_calibration':expected|={(selector,period,b) for b in ['all']+ODDS_LABELS}
    elif table=='probability_odds_cells':
     # This table labels the partial year as 2026 or 2026_partial; normalize only for key audit below.
     expected|={(selector,period,p,b) for p,b in f[['prob_bin','odds_bin']].drop_duplicates().itertuples(index=False,name=None)}
    elif table.startswith('condition_'):
     for family,column in families.items():
      if table=='condition_calibration':expected|={(selector,period,family,str(v)) for v in f[column].unique()}
      else:expected|={(selector,period,family,str(v),b) for v,b in f[[column,'odds_bin']].drop_duplicates().itertuples(index=False,name=None)}
    else:expected|={(selector,period,g,b) for g in ['posthoc_score_ge_0','p_ge_030_and_score_ge_010','p_ge_030_and_score_ge_020'] for b in ['all']+ODDS_LABELS}
  if table=='probability_odds_cells':seen={(k[0],'2026_partial' if k[1]=='2026' else k[1],*k[2:]) for k in seen}
  assert seen==expected,(table,len(seen),len(expected),list(expected-seen)[:3])
  counts[table]=len(data)
 hashes=json.loads((STUDY/'SOURCE_HASHES.json').read_text())
 for path,record in hashes['inputs'].items():
  data=(ROOT/path).read_bytes();assert sha(data)==record['sha256'] and len(data)==record['bytes']
 for record in hashes['upstream_evidence_hashes'].values():assert sha((ROOT/record['path']).read_bytes())==record['sha256']
 for name,digest in hashes['outputs_sha256'].items():assert sha((STUDY/name).read_bytes())==digest
 for name,n in hashes['output_bytes'].items():assert (STUDY/name).stat().st_size==n
 assert hashes['read_only']=={'network':False,'database':False,'model_fit':False,'recalibration':False,'reprediction':False}
 review={'status':'PASS','scope':'Frozen historical diagnostic; no new model or prospective performance validation',
 'pair_context_rows_verified':2284,'frozen_runner_rows_verified':11083,'table_rows_verified':counts,'gap_ci_limits_verified':ci_limits,
 'history_cutoff_T_minus_2_and_latest_history_verified':True,'complete_fixed_date_schedule_reused':True,
 'input_output_and_upstream_evidence_hashes_verified':True,
 'no_fit_or_reprediction':True,'no_database_or_operational_change':True,
 'report_sha256':sha((STUDY/'REPORT.json').read_bytes()),
 'reviewed_output_sha256':{p.name:sha(p.read_bytes()) for p in STUDY.iterdir() if p.is_file() and p.name!='ROOT_REVIEW.json'}}
 (STUDY/'ROOT_REVIEW.json').write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in review.items() if k!='reviewed_output_sha256'}))


if __name__=='__main__':
 frames,dates,weights=reconstruct();reference=[]
 for selector,f in frames.items():
  for period in ['all','2025','2026_partial']:
   scope=f if period=='all' else f.loc[f.year.eq(int(period[:4]))]
   for level in ['all']+ODDS_LABELS:
    g=scope if level=='all' else scope.loc[scope.odds_bin.eq(level)]
    reference.append({'selector':selector,'period':period,'odds_bin':level,**metrics(g,dates,weights)})
 (STUDY/'ROOT_REFERENCE.json').write_text(json.dumps({'inputs_sha256':PINS,'odds_reference':reference},ensure_ascii=False,indent=2,allow_nan=False)+'\n')
 if (STUDY/'REPORT.json').exists():check_outputs(frames,dates,weights)
 else:print(json.dumps({'independent_odds_reference_rows':len(reference),'context_rows':sum(map(len,frames.values()))}))
