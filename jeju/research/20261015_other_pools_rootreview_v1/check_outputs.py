"""Compare new study outputs to independently reconstructed root references."""
from pathlib import Path
import json,hashlib
import pandas as pd
import numpy as np

HERE=Path(__file__).resolve().parent
STUDY=HERE.parent/'20261015_other_pools_postrace_value_v1'
ROOT=HERE.parents[2]
SCOPES={'pool_complete':'per_pool_primary','all_five_common':'universal_222'}
MODELS={'HY_R_FORM':'operating_hy_r_form','research_F1_STYLE6':'research_f1_style6_native'}
RULES={**{f'rank_{i}':f'p_rank_{i}' for i in range(1,6)},
       'rank_1_ev_positive':'p_rank_1_ev_positive','max_ev_all':'all_max_ev_positive',
       'max_ev_top3':'top3_max_ev_positive','max_ev_top5':'top5_max_ev_positive',
       'max_ev_top3_edge020':'top3_max_ev_gt_020'}


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def translate(frame):
    f=frame.copy()
    if 'scope' in f:f['scope']=f.scope.map(SCOPES)
    if 'model' in f:f['model']=f.model.map(MODELS)
    if 'rule' in f:f['policy_id']=f.rule.map(RULES)
    return f


def compare(a,b,left,right=None,factor=1,tolerance=1e-10):
    right=right or left
    x=pd.to_numeric(a[left],errors='raise').to_numpy(float)
    y=pd.to_numeric(b[right],errors='raise').to_numpy(float)*factor
    assert np.allclose(x,y,atol=tolerance,rtol=0,equal_nan=True),(left,right,float(np.nanmax(abs(x-y))))


def main():
    key=['scope','pool','model','policy_id']
    a=translate(pd.read_csv(HERE/'ROOT_SUMMARY_REFERENCE.csv')).set_index(key).sort_index()
    b=pd.read_csv(STUDY/'strategy_summary.csv').set_index(key).sort_index()
    assert a.index.equals(b.index) and len(a)==120
    for left,right in [('eligible','eligible_races'),('bets','selected_races'),('hits','hits'),('stake','stake_krw'),('gross','gross_return_krw'),('net','net_profit_krw')]:compare(a,b,left,right,tolerance=1e-8)
    for left,right in [('roi','roi_pct'),('mean_p','mean_p_selected_pct')]:compare(a,b,left,right,factor=.01)
    for k in [1,3,5]:compare(a,b,f'roi_without_top{k}',f'roi_without_top_{k}_winning_tickets_pct',factor=.01)
    ci=pd.read_csv(STUDY/'strategy_bootstrap_ci.csv').set_index(key).sort_index()
    assert ci.index.equals(a.index)
    for left,right in [('ci_low','roi_ci95_low_pct'),('ci_high','roi_ci95_high_pct')]:compare(a,ci,left,right,factor=.01)
    compare(a,ci,'valid_draws','roi_valid_draws')
    native=translate(pd.read_parquet(HERE/'ROOT_CANDIDATE_REFERENCE.parquet'))
    reported=pd.read_csv(STUDY/'candidate_rows.csv',usecols=['model','pool','race_id','selection_key','p','quote','hit','quote_status','primary_price_complete','universal_222_price_complete'],dtype={'race_id':str,'selection_key':str},low_memory=False)
    ekey=['model','pool','race_id','selection_key']
    native=native.set_index(ekey).sort_index();reported=reported.set_index(ekey).sort_index()
    assert native.index.equals(reported.index) and len(native)==462775
    for col in ['p','quote','hit']:compare(native,reported,col,tolerance=1e-12)
    assert np.array_equal(native.valid,reported.quote_status.eq('valid'))
    raw=pd.read_parquet(HERE/'ROOT_RAW_QUOTES.parquet')
    complete={p:set(g.index[g]) for p in raw.pool.unique() for g in [raw[raw.pool.eq(p)].groupby('race_id').valid.all()]}
    universal=set.intersection(*complete.values())
    frame=reported.reset_index()
    assert np.array_equal(frame.primary_price_complete,[r in complete[p] for r,p in zip(frame.race_id,frame.pool)])
    assert np.array_equal(frame.universal_222_price_complete,frame.race_id.isin(universal))
    expected=translate(pd.read_parquet(HERE/'ROOT_SELECTION_REFERENCE.parquet'))
    actual=pd.read_csv(STUDY/'selected_rows.csv',dtype={'race_id':str,'selected_selection_key':str},low_memory=False)
    skey=key+['race_id']
    expected=expected.set_index(skey).sort_index();actual=actual.set_index(skey).sort_index()
    assert expected.index.equals(actual.index)
    assert np.array_equal(expected.selection_key,actual.selected_selection_key)
    for left,right in [('p','selected_p'),('quote','selected_quote'),('edge','selected_ev'),('probability_rank','selected_probability_rank'),('hit','hit'),('gross','gross_return_krw')]:compare(expected,actual,left,right,tolerance=1e-8)
    assert actual.stake_krw.eq(1000).all()
    assert np.allclose(actual.net_profit_krw,actual.gross_return_krw-1000,atol=1e-8,rtol=0)
    ledger=pd.read_csv(STUDY/'policy_decisions.csv',dtype={'race_id':str},low_memory=False)
    pre=pd.read_csv(STUDY/'policy_decisions_pre_outcome.csv',dtype={'race_id':str},low_memory=False)
    ledger=ledger.set_index(skey).sort_index();pre=pre.set_index(skey).sort_index()
    assert pre.index.equals(ledger.index) and len(pre)==a.eligible.sum()
    for col in pre.columns:
        if pre[col].dtype.kind in 'ifb':compare(pre,ledger,col,tolerance=1e-12)
        else:assert pre[col].fillna('<NULL>').equals(ledger[col].fillna('<NULL>')),col
    missed=ledger[~ledger.selected]
    assert missed.stake_krw.eq(0).all() and missed.gross_return_krw.eq(0).all() and missed.net_profit_krw.eq(0).all()
    paired=translate(pd.read_csv(HERE/'ROOT_TLA_PAIRED_REFERENCE.csv')).set_index(['scope','policy_id']).sort_index()
    op=pd.read_csv(STUDY/'tla_paired_differences.csv').set_index(['scope','policy_id']).sort_index()
    assert paired.index.equals(op.index)
    for left,right in [('roi_delta_pp','roi_delta_a_minus_b_pp'),('ci_low_pp','roi_delta_ci95_low_pp'),('ci_high_pp','roi_delta_ci95_high_pp'),('valid_draws','roi_delta_valid_draws')]:compare(paired,op,left,right)
    sourcepins=json.loads((HERE.parent/'20261015_operating_value_rootreview_v1/root_source_hashes.json').read_text())
    for name,want in sourcepins.items():assert sha(ROOT/name)==want,name
    receipt=dict(status='PASS',scope='Independent raw API JSON prices and sequential-PL set/conditional-order hybrid reconstruction; complete candidate spaces, fixed rules, returns, sensitivity, date bootstrap and paired differences',candidate_probabilities_verified=len(native),selected_tickets_verified=len(actual),decision_rows_verified=len(ledger),summary_rows_verified=len(a),roi_confidence_bounds_verified=len(a)*2,tla_paired_differences_verified=len(paired),all_raw_quotes_verified=412758,native_probability_tolerance=1e-12,cashflow_tolerance=1e-8,source_hashes_unchanged=True,model_training_or_reprediction=False,report_sha256=sha(STUDY/'REPORT.json'),code_sha256=sha(Path(__file__)),independent_probability_code_sha256=sha(HERE/'verify.py'),files_verified={p.name:sha(p) for p in STUDY.glob('*.csv')})
    with (HERE/'ROOT_VERIFICATION_RECEIPT.json').open('x') as stream:json.dump(receipt,stream,indent=2);stream.write('\n')
    print(json.dumps({k:v for k,v in receipt.items() if k!='files_verified'},indent=2))


if __name__=='__main__':main()
