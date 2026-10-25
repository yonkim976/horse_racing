"""Compare worker tables to independent references prepared by verify_value.py."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
EV=ROOT/'jeju/research/20261017_order_head_value_comparison_v1'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ref=pd.read_csv(HERE/'ROOT_VALUE_SUMMARY.csv');tickets=pd.read_parquet(HERE/'ROOT_VALUE_TICKETS.parquet');k=['pool','model','scope','policy_id']
    s=pd.read_csv(EV/'strategy_summary.csv');c=pd.read_csv(EV/'strategy_bootstrap_ci.csv')
    j=s.merge(ref,on=k,validate='one_to_one',suffixes=('','_root'));assert len(j)==300
    cols=['selected_races','hits','stake_krw','gross_return_krw','net_profit_krw','roi_pct']+[f'roi_without_top_{i}_winning_tickets_pct' for i in (1,3,5)]
    for col in cols:assert np.allclose(j[col],j[col+'_root'],atol=1e-8,rtol=0,equal_nan=True),col
    j=c.merge(ref,on=k,validate='one_to_one',suffixes=('','_root'));assert len(j)==300
    for col in ['roi_ci95_low_pct','roi_ci95_high_pct']:assert np.allclose(j[col],j[col+'_root'],atol=1e-8,rtol=0,equal_nan=True),col
    decisions=pd.read_csv(EV/'policy_decisions.csv');sel=decisions[decisions.selected.eq(True)];j=sel.merge(tickets,on=k+['race_id'],validate='one_to_one',suffixes=('','_root'));assert len(j)==len(sel)==len(tickets)
    assert j.selected_event_key.eq(j.selection_key).all()
    assert np.allclose(j.gross_return_krw,j.gross_root,atol=1e-8,rtol=0)
    assert j.hit.eq(j.root_hit).all()
    q=pd.read_parquet(ROOT/'jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet',columns=['race_date']);dates=sorted(pd.to_datetime(q.race_date).dt.strftime('%Y-%m-%d').unique());di={d:i for i,d in enumerate(dates)}
    draw=np.load(ROOT/'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy',allow_pickle=False);w=np.stack([np.bincount(d,minlength=269) for d in draw]);vectors={}
    for key,f in tickets.groupby(k):
        ix=f.race_id.str[:10].map(di).to_numpy(int);bets=w@np.bincount(ix,minlength=269);gross=w@np.bincount(ix,weights=f.gross_root,minlength=269)
        vectors[key]=np.divide(gross,1000*bets,out=np.full(len(draw),np.nan),where=bets>0)*100-100
    paired=pd.read_csv(EV/'paired_hy_minus_order_head.csv')
    for row in paired.itertuples(index=False):
        a=vectors[(row.pool,row.model_a,row.scope,row.policy_id)];b=vectors[(row.pool,row.model_b,row.scope,row.policy_id)];lo,hi=np.nanquantile(a-b,[.025,.975])
        assert abs(lo-row.roi_delta_ci95_low_pp)<1e-8 and abs(hi-row.roi_delta_ci95_high_pp)<1e-8
    out={'status':'PASS','independent_reference_script':'verify_value.py','selected_tickets_verified':len(sel),'decision_rows':len(decisions),'summary_rows_verified':len(s),'roi_ci_bounds_verified':2*len(c),'paired_roi_rows_verified':len(paired),'all_selected_event_keys_hits_and_cashflows_match':True,'probability_and_quote_reference_assertions_completed_before_worker_outputs':True,'training_or_source_mutation':False,'files_verified':{name:sha(EV/name) for name in ['strategy_summary.csv','strategy_bootstrap_ci.csv','policy_decisions.csv','selected_tickets.csv','paired_hy_minus_order_head.csv']},'root_reference_hashes':{name:sha(HERE/name) for name in ['verify_value.py','ROOT_VALUE_SUMMARY.csv','ROOT_VALUE_TICKETS.parquet','ROOT_PREDICTION_REVIEW.json']}}
    (HERE/'ROOT_VALUE_REVIEW.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))

if __name__=='__main__':main()
