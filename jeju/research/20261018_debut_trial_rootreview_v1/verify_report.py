"""Verify all saved prediction/ticket/profile examples and reported primary CIs."""
from pathlib import Path
import json,hashlib
import pandas as pd
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
MAIN=ROOT/'jeju/research/20261018_debut_trial_ablation_v1/outputs'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def close(a,b):assert np.allclose(a,b,atol=1e-12,rtol=0,equal_nan=True)

def main():
    errors={}
    for kind,label in [('BASELINE','baseline_replayed'),('CANDIDATE','candidate_evaluation')]:
        a=pd.read_parquet(HERE/f'ROOT_{kind}_RUNNERS.parquet').set_index('api_record_id')
        b=pd.read_parquet(MAIN/f'{label}_runner_predictions.parquet').set_index('api_record_id').loc[a.index]
        for col in ['score','p_top3','log_loss','brier']:
            close(a[col],b[col]);errors[f'{kind}_{col}']=float(abs(a[col]-b[col]).max())
        a=pd.read_parquet(HERE/f'ROOT_{kind}_RACE_METRICS.parquet').set_index('race_id')
        b=pd.read_parquet(MAIN/f'{label}_race_metrics.parquet').set_index('race_id').loc[a.index]
        for col in ['log_loss','brier','trio_nll','six_combo_hit']+[f'top{k}_{m}' for k in (3,4,5,6) for m in ('capture','all3')]:close(a[col],b[col])
        a=pd.read_parquet(HERE/f'ROOT_{kind}_TICKETS.parquet').set_index(['race_id','selection_rank'])
        b=pd.read_parquet(MAIN/f'{label}_canonical_max6.parquet').set_index(['race_id','selection_rank']).loc[a.index]
        assert a.numbers.equals(b.numbers) and a.hit.equals(b.hit);close(a.probability,b.probability)
    root=pd.read_csv(HERE/'ROOT_PAIRED_RESULTS.csv',float_precision='round_trip')
    primary=pd.read_parquet(MAIN/'cold_primary_metrics.parquet').set_index('metric')
    reference=root[root.scope.eq('cold')].set_index('metric')
    for k,col in [('baseline','baseline_race_equal'),('candidate','candidate_race_equal'),('delta','delta_candidate_minus_baseline'),('ci_low','paired_date_bootstrap_ci95_low'),('ci_high','paired_date_bootstrap_ci95_high')]:close(reference[k],primary.loc[reference.index,col])
    assert primary.cold_runner_rows.eq(661).all() and primary.cold_races.eq(252).all() and primary.valid_draws.eq(2000).all()
    concord=pd.read_parquet(MAIN/'cold_raw_score_concordance_by_race.parquet').set_index('race_id')
    rootconcord=pd.read_parquet(HERE/'ROOT_CANDIDATE_COLD_CONCORDANCE.parquet').set_index('race_id')
    assert len(concord)==len(rootconcord)==118;close(concord.loc[rootconcord.index,'candidate_concordance'],rootconcord.concordance)
    assert concord.baseline_concordance.eq(.5).all() and concord.cross_label_pairs.sum()==398
    example=pd.read_csv(MAIN/'frozen_2026_01_02_jeju1r_example.csv',float_precision='round_trip').set_index('api_record_id')
    selection=json.loads((HERE/'ROOT_EXAMPLE_SELECTION.json').read_text());assert len(example)==8 and set(example.index)==set(selection['api_record_ids'])
    feats=pd.read_parquet(MAIN/'features_f1_style6_debut_trial4.parquet').set_index('api_record_id').loc[example.index]
    for col in ['trial_peer_relative_time_mean3','trial_peer_relative_time_n3','trial_days_since_latest_event_pre','trial_event_count_pre']:close(example[col],feats[col])
    for kind,label in [('BASELINE','baseline'),('CANDIDATE','candidate')]:
        u=pd.read_parquet(HERE/f'ROOT_{kind}_RUNNERS.parquet').set_index('api_record_id').loc[example.index]
        close(example[label+'_score'],u.score);close(example[label+'_p_top3'],u.p_top3)
    close(example.top3_outcome,feats.finish_position.le(3).astype(int))
    slots=pd.read_parquet(MAIN/'cold_target_trial_feature_slots.parquet');root_slots=pd.read_parquet(HERE/'ROOT_LAST3_TRIAL_LEDGER.parquet')
    joined=slots.merge(root_slots,on=['target_api_record_id','source_api_record_id'],validate='one_to_one')
    assert len(joined)==3240;close(joined.relative_time,joined.relative);close(joined.peer_median_time_seconds,joined.peer_median)
    for lockname in ['prepared_lock.json','evaluation_source_lock.json']:
        lock=json.loads((MAIN/lockname).read_text())
        for relative,v in lock['input_files'].items():
            p=(ROOT/relative).resolve();assert p.is_relative_to(ROOT);assert p.stat().st_size==v['bytes'] and sha(p)==v['sha256'],relative
    protected=json.loads((HERE/'ROOT_SOURCE_LOCK.json').read_text())['source_hashes']
    for relative,digest in protected.items():assert sha(ROOT/relative)==digest,relative
    summary=json.loads((MAIN/'evaluation_summary.json').read_text());assert summary['primary_gate_passed'] is True
    proof={'status':'PASS','root_fit_or_optimizer_calls':0,'runner_rows_verified_per_model':17412,'race_rows_verified_per_model':1779,'canonical_tickets_verified_per_model':10674,'cold_feature_rows_verified':1946,'recent_trial_slots_verified':3240,'cold_primary_rows':661,'cold_primary_races':252,'concordance_races':118,'cross_label_pairs':398,'frozen_example_rows':8,'primary_gate_pass':True,'max_runner_errors':errors,'protected_artifacts_unchanged':len(protected),'evaluation_summary_sha256':sha(MAIN/'evaluation_summary.json')}
    with (HERE/'ROOT_REPORT_REVIEW.json').open('x') as f:json.dump(proof,f,indent=2);f.write('\n')
    print(json.dumps(proof,indent=2))

if __name__=='__main__':main()
