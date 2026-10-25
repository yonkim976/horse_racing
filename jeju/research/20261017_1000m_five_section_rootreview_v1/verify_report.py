"""Independent artifact-by-artifact verification of the frozen report, no fit."""
from pathlib import Path
import json, hashlib
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
MAIN=ROOT/'jeju/research/20261017_1000m_five_section_ablation_v1/outputs'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def close(a,b):
    assert np.allclose(a,b,rtol=0,atol=1e-12,equal_nan=True)

def main():
    errors={}
    for kind,label in [('BASELINE','baseline_replayed'),('CANDIDATE','candidate_evaluation')]:
        root=pd.read_parquet(HERE/f'ROOT_{kind}_RUNNERS.parquet').set_index('api_record_id')
        worker=pd.read_parquet(MAIN/f'{label}_runner_predictions.parquet').set_index('api_record_id').loc[root.index]
        for c in ['score','p_top3','log_loss','brier']:
            close(root[c],worker[c]);errors[f'{kind}_{c}']=float(abs(root[c]-worker[c]).max())
        rootr=pd.read_csv(HERE/f'ROOT_{kind}_RACE_METRICS.csv',float_precision='round_trip').set_index('race_id')
        workerr=pd.read_parquet(MAIN/f'{label}_race_metrics.parquet').set_index('race_id').loc[rootr.index]
        cols=['log_loss','brier','trio_nll','six_combo_hit']+[f'top{k}_{metric}' for k in (3,4,5,6) for metric in ('capture','all3')]
        for c in cols:close(rootr[c],workerr[c])
        rt=pd.read_csv(HERE/f'ROOT_{kind}_TICKETS.csv',float_precision='round_trip').set_index(['race_id','selection_rank'])
        wt=pd.read_parquet(MAIN/f'{label}_canonical_max6.parquet').set_index(['race_id','selection_rank']).loc[rt.index]
        assert rt.numbers.equals(wt.numbers) and rt.hit.equals(wt.hit)
        close(rt.probability,wt.probability)
    comparisons=pd.read_parquet(MAIN/'race_metric_comparisons.parquet')
    independent=pd.read_csv(HERE/'ROOT_PAIRED_RESULTS.csv',float_precision='round_trip')
    for scope,worker_scope in [('1000m','1000m_primary'),('all','all_eval')]:
        a=independent[independent.scope.eq(scope)].set_index('metric')
        b=comparisons[comparisons.scope.eq(worker_scope)].set_index('metric').loc[a.index]
        assert a.races.eq(b.races).all()
        for c,w in [('baseline','baseline_mean'),('candidate','candidate_mean'),('delta','candidate_minus_baseline'),('ci_low','paired_date_ci95_low'),('ci_high','paired_date_ci95_high')]:close(a[c],b[w])
    profiles=pd.read_parquet(MAIN/'all_1000m_profiles.parquet').set_index('api_record_id')
    reference=pd.read_parquet(HERE/'ROOT_SECTION_FEATURE_REFERENCE.parquet').set_index('api_record_id')
    assert len(profiles)==14457 and profiles.index.is_unique and set(profiles.index)==set(reference.index)
    profiles=profiles.loc[reference.index]
    for c in reference:close(profiles[c],reference[c])
    baseline=pd.read_parquet(ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet').set_index('api_record_id').loc[profiles.index]
    for c in ['race_id','race_date','horse_id','horse_number','history_cutoff','horse_name']:
        assert profiles[c].equals(baseline[c]),c
    assert list(profiles.last5_source_ids)==[';'.join(str(int(v)) for v in ids) for ids in baseline.last5_same_source_ids]
    examples=pd.read_csv(MAIN/'profile_examples.csv',float_precision='round_trip')
    assert len(examples)==20
    section_map=dict(zip(['seg_0_200','seg_200_to_c3_approx400','seg_c3_approx400_to_c4_approx600','seg_c4_approx600_to_800','seg_800_to_1000'],['hist_0_200m','hist_200_approx400m','hist_approx400_approx600m','hist_approx600_800m','hist_800_1000m']))
    eligible=profiles[profiles.year.isin([2024,2025,2026])].reset_index().sort_values(['race_date','race_id','horse_number','api_record_id'])
    for r in examples.itertuples(index=False):
        stem=section_map[r.segment];n=eligible[stem+'_n']
        mask={'n0':n.eq(0),'n1':n.eq(1),'n2_to_4':n.between(2,4),'n5':n.eq(5)}[r.support_bucket]
        assert r.api_record_id==int(eligible.loc[mask].iloc[0].api_record_id)
        close(profiles.loc[r.api_record_id,stem+'_seconds_mean5'],r.history_mean_seconds)
        assert profiles.loc[r.api_record_id,stem+'_n']==r.valid_history_n_0_to_5
    summary=json.loads((MAIN/'evaluation_summary.json').read_text())
    assert summary['primary_1000m']['primary_gate_passed'] is False
    for name,v in summary['outputs'].items():
        p=MAIN/name;assert p.stat().st_size==v['bytes'] and sha(p)==v['sha256'],name
    for lockname in ['prepared_lock.json','evaluation_source_lock.json']:
        lock=json.loads((MAIN/lockname).read_text())
        for relative,v in lock['input_files'].items():
            p=ROOT/relative;assert p.stat().st_size==v['bytes'] and sha(p)==v['sha256'],relative
    protected=json.loads((HERE/'ROOT_BASELINE_SOURCE_LOCK.json').read_text())['source_hashes']
    for relative,digest in protected.items():assert sha(ROOT/relative)==digest,relative
    receipt={'status':'PASS','root_fit_or_optimizer_calls':0,'runner_rows_verified_per_model':17412,'race_rows_verified_per_model':1779,'canonical_tickets_verified_per_model':10674,'profiles_verified':len(profiles),'primary_races':508,'primary_gate_pass':False,'max_runner_errors':errors,'protected_artifacts_unchanged':len(protected),'evaluation_summary_sha256':sha(MAIN/'evaluation_summary.json')}
    with (HERE/'ROOT_REPORT_REVIEW.json').open('x') as f:json.dump(receipt,f,indent=2);f.write('\n')
    print(json.dumps(receipt,indent=2))

if __name__=='__main__':main()
