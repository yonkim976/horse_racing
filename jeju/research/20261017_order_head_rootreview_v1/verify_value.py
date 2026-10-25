"""Independent tickets, cashflows and fixed date-bootstrap checks. No fitting."""
from pathlib import Path
from decimal import Decimal
import json,hashlib
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
EV=ROOT/'jeju/research/20261017_order_head_value_comparison_v1'
OLD=ROOT/'jeju/research/20261015_other_pools_rootreview_v1'

def main():
    source=EV/'candidate_evaluation_rows.csv'
    has_labels=source.exists()
    if not has_labels:source=EV/'candidate_selection_inputs.csv'
    columns=['race_id','race_date','pool','model','event_key','selection_key','p','parsed_odds','quote_status','scope']+(['hit'] if has_labels else [])
    candidates=pd.read_csv(source,usecols=columns,dtype={'race_id':str,'event_key':str,'selection_key':str},float_precision='round_trip').rename(columns={'parsed_odds':'quote'})
    assert candidates.event_key.eq(candidates.selection_key).all()
    quotes=pd.read_parquet(OLD/'ROOT_RAW_QUOTES.parquet')
    unique=candidates.drop_duplicates(['model','pool','race_id','selection_key'])
    # Probability references come from independently reconstructed full joints,
    # and the previously independently verified operating/native set law.
    joint=pd.read_parquet(HERE/'ROOT_2026_JOINT_REFERENCE.parquet')
    refs=[]
    for model,col in [('F1_STYLE6_COND_ORDER_V1','p_root'),('F1_STYLE6_FIXED_SCORE_PL_CONTROL','control_p_root')]:
        for pool,n in [('WIN',1),('QNL',2),('EXA',2),('TRI',3)]:
            keys=joint[[f'horse_no_{i}' for i in range(1,n+1)]].to_numpy(int)
            if pool=='QNL':keys=np.sort(keys,axis=1)
            f=pd.DataFrame({'race_id':joint.race_id,'selection_key':['-'.join(map(str,k)) for k in keys],'p_root':joint[col]})
            f=f.groupby(['race_id','selection_key'],as_index=False).p_root.sum();f['model']=model;f['pool']=pool;refs.append(f)
    prior=pd.read_parquet(OLD/'ROOT_CANDIDATE_REFERENCE.parquet')
    hy=prior[prior.model.eq('HY_R_FORM')&prior.pool.ne('TLA')][['race_id','selection_key','pool','model','p']].rename(columns={'p':'p_root'});refs.append(hy)
    tla=prior[prior.model.eq('research_F1_STYLE6')][['race_id','selection_key','pool','p']].rename(columns={'p':'p_root'})
    for model in ('F1_STYLE6_NATIVE_TLA_Q','F1_STYLE6_COND_ORDER_V1_TLA_Q','F1_STYLE6_FIXED_SCORE_PL_CONTROL_TLA_Q'):
        f=tla.copy();f['model']=model;refs.append(f)
    probcheck=unique.merge(pd.concat(refs,ignore_index=True),on=['model','pool','race_id','selection_key'],validate='one_to_one')
    assert len(probcheck)==len(unique)
    maxprob=float(abs(probcheck.p-probcheck.p_root).max());assert maxprob<1e-12,maxprob
    prices=unique.merge(quotes[['race_id','pool','selection_key','quote','valid']],on=['race_id','pool','selection_key'],suffixes=('','_root'),validate='many_to_one')
    assert np.allclose(prices.quote,prices.quote_root,atol=0,rtol=0)
    official=pd.read_csv(ROOT/'jeju/research/20261014_single_place_returns_v1/source_audit/OFFICIAL_RUNNER_RESULTS.csv')
    truth={rid:tuple(g.sort_values('finish_position').horse_number.astype(int).iloc[:3]) for rid,g in official.groupby('race_id')}
    def hit(row):
        n={'WIN':1,'QNL':2,'EXA':2,'TLA':3,'TRI':3}[row.pool];t=truth[row.race_id][:n]
        if row.pool in ('QNL','TLA'):t=tuple(sorted(t))
        return tuple(map(int,row.selection_key.split('-')))==t
    candidates['root_hit']=[hit(r) for r in candidates.itertuples(index=False)]
    if has_labels:assert candidates.hit.eq(candidates.root_hit).all()
    rules=[(f'p_rank_{i}',i,None,None) for i in range(1,6)]+[('p_rank_1_ev_positive',1,None,0),('all_max_ev_positive',None,None,0),('top3_max_ev_positive',None,3,0),('top5_max_ev_positive',None,5,0),('top3_max_ev_gt_020',None,3,.2)]
    pairs=pd.read_parquet(ROOT/'jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet',columns=['race_date'])
    dates=sorted(pd.to_datetime(pairs.race_date).dt.strftime('%Y-%m-%d').unique());di={d:i for i,d in enumerate(dates)}
    schedule=np.load(ROOT/'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy',allow_pickle=False)
    weights=np.stack([np.bincount(s,minlength=269) for s in schedule]);rows=[];chosen=[];vectors={}
    for (model,pool,scope),g in candidates.groupby(['model','pool','scope']):
        g=g.copy();keys=g.selection_key.map(lambda x:tuple(map(int,x.split('-'))))
        for i in range(3):g[f'num{i}']=keys.map(lambda k:k[i] if len(k)>i else 0)
        tie=['num0','num1','num2'];g=g.sort_values(['race_id','p',*tie],ascending=[True,False,True,True,True]);g['root_rank']=g.groupby('race_id').cumcount()+1;g['edge']=g.p*g.quote-1
        for rule,rank,cap,threshold in rules:
            c=g.copy()
            if rank is not None:c=c[c.root_rank.eq(rank)]
            if cap is not None:c=c[c.root_rank.le(cap)]
            if threshold is not None:c=c[c.edge.gt(threshold)]
            if rank is None:c=c.sort_values(['race_id','edge',*tie],ascending=[True,False,True,True,True]).groupby('race_id').head(1)
            c['policy_id']=rule;c['gross_root']=[int(Decimal(str(q))*1000) if h else 0 for q,h in zip(c.quote,c.root_hit)]
            chosen.append(c);bets=len(c);gross=int(c.gross_root.sum());stake=bets*1000
            ix=c.race_id.str[:10].map(di).to_numpy(int)
            bd=weights@np.bincount(ix,minlength=269);gd=weights@np.bincount(ix,weights=c.gross_root,minlength=269)
            v=np.divide(gd,1000*bd,out=np.full(2000,np.nan),where=bd>0)*100-100
            vectors[(pool,model,scope,rule)]=v
            low,high=np.nanquantile(v,[.025,.975]);row=dict(pool=pool,model=model,scope=scope,policy_id=rule,selected_races=bets,hits=int(c.root_hit.sum()),stake_krw=stake,gross_return_krw=gross,net_profit_krw=gross-stake,roi_pct=100*(gross/stake-1) if stake else np.nan,roi_ci95_low_pct=low,roi_ci95_high_pct=high)
            for k in (1,3,5):
                wins=c[c.root_hit].sort_values('gross_root',ascending=False).head(k);left=bets-len(wins)
                row[f'roi_without_top_{k}_winning_tickets_pct']=100*((gross-wins.gross_root.sum())/(1000*left)-1) if left else np.nan
            rows.append(row)
    ref=pd.DataFrame(rows);tickets=pd.concat(chosen,ignore_index=True)
    ref.to_csv(HERE/'ROOT_VALUE_SUMMARY.csv',index=False);tickets.to_parquet(HERE/'ROOT_VALUE_TICKETS.parquet',index=False)
    if not (EV/'strategy_summary.csv').exists():
        print('Independent references prepared; waiting for worker result tables.');return
    summary=pd.read_csv(EV/'strategy_summary.csv');ci=pd.read_csv(EV/'strategy_bootstrap_ci.csv');k=['pool','model','scope','policy_id'];check=summary.merge(ref,on=k,validate='one_to_one',suffixes=('','_root'))
    for col in ['selected_races','hits','stake_krw','gross_return_krw','net_profit_krw','roi_pct']+[f'roi_without_top_{i}_winning_tickets_pct' for i in (1,3,5)]:
        assert np.allclose(check[col],check[col+'_root'],atol=1e-8,rtol=0,equal_nan=True),col
    check=ci.merge(ref,on=k,validate='one_to_one',suffixes=('','_root'))
    for col in ['roi_ci95_low_pct','roi_ci95_high_pct']:assert np.allclose(check[col],check[col+'_root'],atol=1e-8,rtol=0,equal_nan=True),col
    decisions=pd.read_csv(EV/'policy_decisions.csv');selected=decisions[decisions.selected.eq(True)]
    tkeys=k+['race_id'];check=selected.merge(tickets,on=tkeys,validate='one_to_one',suffixes=('','_root'))
    assert len(check)==len(tickets)==len(selected)
    assert (check.selected_event_key==check.selection_key).all()
    assert np.allclose(check.gross_return_krw,check.gross_root,atol=1e-8,rtol=0)
    paired=pd.read_csv(EV/'paired_hy_minus_order_head.csv')
    # All paired intervals use identical resampled dates and independently selected ticket vectors.
    for r in paired.itertuples(index=False):
        a=vectors[(r.pool,r.model_a,r.scope,r.policy_id)];b=vectors[(r.pool,r.model_b,r.scope,r.policy_id)]
        lo,hi=np.nanquantile(a-b,[.025,.975])
        assert abs(lo-r.roi_delta_ci95_low_pp)<1e-8 and abs(hi-r.roi_delta_ci95_high_pp)<1e-8
    report={'status':'PASS','candidate_probabilities_checked':len(probcheck),'maximum_probability_error':maxprob,'candidate_prices_checked':len(prices),'selected_tickets_checked':len(tickets),'summary_rows_checked':len(ref),'ci_bounds_checked':2*len(ref),'paired_rows_checked':len(paired),'no_fit_or_source_mutation':True}
    (HERE/'ROOT_VALUE_REVIEW.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
