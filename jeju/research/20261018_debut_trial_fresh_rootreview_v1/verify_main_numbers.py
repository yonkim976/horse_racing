"""Verify all worker scores, tickets, paired summaries and resampling draws."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from independent_build import ROOT,HERE,sha,dump_new,compare

MAIN=ROOT/'jeju/research/20261018_debut_trial_fresh_period_v1/outputs'

def check_frame(a,b,keys,cols):
    assert not a.duplicated(keys).any() and not b.duplicated(keys).any()
    joined=a.merge(b,on=keys,validate='one_to_one',suffixes=('_root','_worker'))
    assert len(joined)==len(a)==len(b)
    errors={}
    for col in cols:
        x=joined[col+'_root'];y=joined[col+'_worker']
        if col=='numbers':assert x.equals(y);errors[col]=0.0
        else:
            assert np.allclose(x,y,atol=1e-12,rtol=0,equal_nan=True),col
            errors[col]=float(np.max(np.abs(x-y)))
    return dict(rows=len(joined),errors=errors)

def main():
    f=pd.read_parquet(MAIN/'fresh_features_34_root_dryrun.parquet');ref=pd.read_parquet(HERE/'ROOT_FRESH_FROZEN_INPUT34.parquet')
    meta=json.loads((ROOT/'jeju/research/20261018_debut_trial_ablation_v1/outputs/F1_STYLE6_DEBUT_TRIAL4_2026/meta.json').read_text())
    assert compare(f,ref,meta['features'])=={c:0.0 for c in meta['features']}
    root_u=pd.read_parquet(HERE/'ROOT_FRESH_RUNNERS.parquet');worker_u=pd.read_parquet(MAIN/'fresh_model_predictions.parquet')
    runnercheck=check_frame(root_u,worker_u,['model','api_record_id','race_id'],['score','p_top3','log_loss','brier'])
    root_r=pd.read_parquet(HERE/'ROOT_FRESH_RACE_METRICS.parquet');worker_r=pd.read_parquet(MAIN/'fresh_race_metrics.parquet')
    cols=['log_loss','brier','trio_nll','six_combo_hit']+[f'top{k}_{metric}' for k in (3,4,5,6) for metric in ('capture','all3')]
    racecheck=check_frame(root_r,worker_r,['model','race_id'],cols)
    root_t=pd.read_parquet(HERE/'ROOT_FRESH_TICKETS.parquet');worker_t=pd.read_parquet(MAIN/'fresh_canonical_max6.parquet')
    ticketcheck=check_frame(root_t,worker_t,['model','race_id','selection_rank'],['numbers','probability','hit'])
    rootboot=pd.read_parquet(HERE/'ROOT_FRESH_BOOTSTRAP.parquet').rename(columns={'draw':'draw_id'})
    workerboot=pd.read_parquet(MAIN/'fresh_primary_date_bootstrap.parquet')
    bootcheck=check_frame(rootboot,workerboot,['scope','metric','draw_id'],['delta'])
    summary=json.loads((MAIN/'fresh_scope_summary.json').read_text());root_summary=json.loads((HERE/'ROOT_FRESH_EVALUATION.json').read_text())
    for row in summary['scope_metrics']:
        base=next(r for r in root_summary['scope_metrics'] if r['scope']==row['scope'] and r['metric']==row['metric'])
        ci=next(r for r in root_summary['paired_intervals'] if r['scope']==row['scope'] and r['metric']==row['metric'])
        for key,expect in [('baseline_race_equal',base['baseline']),('candidate_race_equal',base['candidate']),
                           ('delta_candidate_minus_baseline',ci['delta']),('paired_date_bootstrap_ci95_low',ci['low']),('paired_date_bootstrap_ci95_high',ci['high'])]:
            assert abs(row[key]-expect)<1e-12,key
    conc=pd.read_parquet(MAIN/'fresh_raw_score_concordance.parquet');rootconc=pd.read_csv(HERE/'ROOT_FRESH_CONCORDANCE.csv')
    for r in conc.itertuples(index=False):
        for model in ('baseline','candidate'):
            rr=rootconc[(rootconc.model==model)&(rootconc.race_id==r.race_id)].iloc[0]
            assert rr.pairs==r.cross_label_pairs and rr.concordance==getattr(r,model+'_concordance')
    pairs=root_r[root_r.model.eq('baseline')][['race_id','six_combo_hit']].merge(root_r[root_r.model.eq('candidate')][['race_id','six_combo_hit']],on='race_id',suffixes=('_base','_candidate'),validate='one_to_one')
    assert pairs.six_combo_hit_base.equals(pairs.six_combo_hit_candidate)
    for lockname in ('ROOT_PROTECTED_BEFORE.json','ROOT_OPERATING_BEFORE.json'):
        for path,expected in json.loads((HERE/lockname).read_text()).items():assert sha(ROOT/path)==expected,path
    source_review=json.loads((HERE/'ROOT_FROZEN_SOURCE_BUNDLE_REVIEW.json').read_text())
    sourcedir=ROOT/'jeju/research/20261018_debut_trial_fresh_source_v1/outputs'
    assert sha(sourcedir/'audit_manifest.json')==source_review['manifest_sha256']
    for name,h in source_review['source_files'].items():assert sha(sourcedir/name)==h,name
    outputs=[p for p in MAIN.iterdir() if p.is_file()]
    proof=dict(status='PASS_NUMERIC_REPRODUCTION_NOT_MODEL_ACCEPTANCE',features_all_34_exact=True,runner_predictions=runnercheck,
               race_metrics=racecheck,tickets=ticketcheck,bootstrap=bootcheck,concordance_races=len(conc),concordance_pairs=int(conc.cross_label_pairs.sum()),
               all_6combo_hit_race_keys_identical=True,shared_hit_races=int(pairs.six_combo_hit_base.sum()),
               primary_improvement_reproduced=False,small_sample_not_proof_of_inferiority=True,
               source_freeze_unchanged=True,protected_models_and_registry_unchanged=True,
               current_worker_outputs={p.name:sha(p) for p in outputs},root_training_calls=0,root_calibration_calls=0)
    dump_new('ROOT_MAIN_NUMERIC_REVIEW.json',proof)
    print(json.dumps({k:v for k,v in proof.items() if k!='current_worker_outputs'},indent=2))

if __name__=='__main__':main()
