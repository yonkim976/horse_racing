"""Compare Luna's outputs to independently calculated root references."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
STUDY=HERE.parent/'20261015_operating_postrace_value_comparison_v1'
MODEL={'HY_R_FORM':'operating_hy_r_form','research_pair_ID':'research_pair_id_baseline','research_F1_STYLE6':'research_f1_style6'}
QPL={'rank_1_ev_positive':'rank_1_ev_gt_0','max_ev_all':'all_max_ev_gt_0',
     'max_ev_top3':'top3_max_ev_gt_0','max_ev_top5':'top5_max_ev_gt_0',
     'max_ev_p020':'p_ge_020_max_ev_gt_0','max_ev_p030':'p_ge_030_max_ev_gt_0',
     'max_ev_top3_edge020':'top3_max_ev_gt_020','max_ev_p020_edge020':'p_ge_020_max_ev_gt_020'}
PLC={'rank_1':'p_rank_1','rank_2':'p_rank_2','rank_3':'p_rank_3',
     'rank_1_ev_positive':'p_rank_1_ev_positive','max_ev_all':'all_runners_max_ev_positive',
     'max_ev_top3':'top3_max_ev_positive','max_ev_p040':'p_ge_0_40_max_ev_positive',
     'max_ev_p050':'p_ge_0_50_max_ev_positive'}


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def align(f,pool):
    f=f[f.pool.eq(pool)].copy();f['model']=f.model.map(MODEL)
    if 'rule' in f:
        rules=QPL if pool=='QPL' else PLC
        f['policy_id']=f.rule.map(lambda s:rules.get(s,s))
    return f


def check(a,b,ca,cb=None,factor=1,tol=1e-10):
    cb=cb or ca
    expected=pd.to_numeric(a[ca],errors='raise').to_numpy(float)
    actual=pd.to_numeric(b[cb],errors='raise').to_numpy(float)*factor
    assert np.allclose(expected,actual,atol=tol,rtol=0,equal_nan=True),(ca,cb,float(np.nanmax(abs(expected-actual))))


def main():
    summary=pd.read_csv(HERE/'root_summary_reference.csv')
    choices=pd.read_csv(HERE/'root_selection_reference.csv',dtype={'race_id':str})
    allrows=pd.read_csv(HERE/'root_all_candidate_reference.csv',dtype={'race_id':str})
    paired=pd.read_csv(HERE/'root_paired_roi_reference.csv')
    receipts=[]
    for pool in ['QPL','PLC']:
        prefix=pool.lower();rules=QPL if pool=='QPL' else PLC
        a=align(summary,pool).set_index(['model','policy_id']).sort_index()
        b=pd.read_csv(STUDY/f'{prefix}_strategy_summary.csv').set_index(['model','policy_id']).sort_index()
        assert a.index.equals(b.index)
        for ca,cb in [('eligible','eligible_races'),('bets','selected_races'),('hits','hits'),('stake','stake_krw'),('gross','gross_return_krw'),('net','net_profit_krw')]:
            check(a,b,ca,cb,tol=1e-8)
        for ca,cb in [('roi','roi_pct'),('mean_p','mean_p_selected_pct'),('roi_ci_low','roi_ci95_low_pct'),('roi_ci_high','roi_ci95_high_pct')]:
            check(a,b,ca,cb,factor=.01)
        for k in [1,3,5]:check(a,b,f'roi_without_top{k}',f'roi_without_top_{k}_winning_tickets_pct',factor=.01)
        native=align(allrows,pool)
        candidate_name=f'{prefix}_'+('pair_rows.csv' if pool=='QPL' else 'runner_rows.csv')
        reported=pd.read_csv(STUDY/candidate_name,dtype={'race_id':str})
        if pool=='PLC':reported['horse_i']=reported.horse_number;reported['horse_j']=0
        key=['model','race_id','horse_i','horse_j']
        native=native.set_index(key).sort_index();reported=reported.set_index(key).sort_index()
        assert native.index.equals(reported.index)
        for ca,cb in [('p','p'),('quote','quote'),('y','hit'),('probability_rank','probability_rank')]:check(native,reported,ca,cb,tol=1e-12)
        expected=align(choices,pool)
        actual=pd.read_csv(STUDY/f'{prefix}_selected_rows.csv',dtype={'race_id':str})
        actual=actual[actual.selected.eq(True)].copy()
        if pool=='PLC':actual['horse_i']=actual.horse_number;actual['horse_j']=0
        key=['model','policy_id','race_id']
        expected=expected.set_index(key).sort_index();actual=actual.set_index(key).sort_index()
        assert expected.index.equals(actual.index)
        for ca,cb in [('horse_i','horse_i'),('horse_j','horse_j'),('p','p'),('probability_rank','probability_rank'),('quote','quote'),('edge','model_ev'),('y','hit'),('gross','gross_return_krw')]:check(expected,actual,ca,cb,tol=1e-8)
        assert actual.stake_krw.eq(1000).all()
        assert np.allclose(actual.net_profit_krw,actual.gross_return_krw-1000,atol=1e-8,rtol=0)
        p=paired[paired.pool.eq(pool)].copy();p['policy_id']=p.rule.map(lambda s:rules.get(s,s))
        p=p.set_index('policy_id').sort_index()
        q=pd.read_csv(STUDY/f'{prefix}_paired_differences.csv').set_index('policy_id').sort_index()
        assert p.index.equals(q.index)
        for ca,cb in [('operating_minus_research_roi_pp','roi_delta_a_minus_b_pp'),('ci_low_pp','roi_delta_ci95_low_pp'),('ci_high_pp','roi_delta_ci95_high_pp'),('valid_draws','roi_delta_valid_draws')]:check(p,q,ca,cb)
        receipts.append(dict(pool=pool,summary_rows=len(a),all_candidate_probabilities=len(native),selected_tickets=len(actual),paired_roi_differences=len(p),native_probability_tolerance=1e-12,summary_tolerance=1e-10))
    for name,want in json.loads((HERE/'root_source_hashes.json').read_text()).items():
        assert sha(ROOT/name)==want,name
    result=dict(status='PASS',scope='Independent sequential-PL probability reconstruction, exact roster/labels/quote joins, fixed strategies, cashflows, sensitivity and date bootstrap/paired ROI differences',products=receipts,source_hashes_unchanged=True,training_or_calibration_fits=0,retrospective_final_odds=True,report_sha256=sha(STUDY/'REPORT.json'),files_verified={p.name:sha(p) for p in STUDY.glob('*.csv')},root_verifier_sha256=sha(Path(__file__)),root_probability_code_sha256=sha(HERE/'verify.py'))
    with (HERE/'ROOT_VERIFICATION_RECEIPT.json').open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='files_verified'},indent=2))


if __name__=='__main__':main()
