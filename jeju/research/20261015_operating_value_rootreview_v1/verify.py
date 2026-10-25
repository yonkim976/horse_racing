"""Independent replay of saved scores and fixed postrace purchase policies."""
from pathlib import Path
from itertools import permutations, combinations
from decimal import Decimal
import json
import hashlib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
LEGACY = ROOT / 'data/research/jeju_native_transition_holdout_v13_20260916'
PRIOR = ROOT / 'jeju/research/20261015_all_pair_postrace_value_v1'
PLCPRIOR = ROOT / 'jeju/research/20261015_all_runner_place_value_v1'
DATA = ROOT / 'data/research/jeju_native_top3_dataset_v1_20260915_r2'


def policies(pool):
    p = [(f'rank_{k}', k, None, None, None) for k in range(1, 6 if pool=='QPL' else 4)]
    p += [('rank_1_ev_positive',1,None,None,0), ('max_ev_all',None,None,None,0),
          ('max_ev_top3',None,3,None,0)]
    if pool=='QPL':
        p += [('max_ev_top5',None,5,None,0),('max_ev_p020',None,None,.2,0),
              ('max_ev_p030',None,None,.3,0),('max_ev_top3_edge020',None,3,None,.2),
              ('max_ev_p020_edge020',None,None,.2,.2)]
    else:
        p += [('max_ev_p040',None,None,.4,0),('max_ev_p050',None,None,.5,0)]
    return p


def main():
    h = pd.read_parquet(LEGACY/'horse_predictions.parquet')
    h = h[h.model.eq('HY_R_FORM')].copy()
    frozen = pd.read_parquet(LEGACY/'frozen_scores.parquet')
    frozen = frozen[frozen.model.eq('HY_R_FORM')].set_index('entry_id').loc[h.entry_id]
    for c in ['score','beta','order_score','beta_order']:
        assert np.array_equal(h[c],frozen[c])
    entries = pd.read_parquet(DATA/'entries.parquet').set_index('entry_id').loc[h.entry_id]
    assert np.array_equal(entries.horse_id, h.horse_id)
    h['horse_number'] = entries.horse_number.to_numpy(int)
    h['key'] = [f'{str(d)[:10]}_2_{int(no)}' for d,no in zip(h.event_date, entries.event_number)]
    research = pd.read_parquet(ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs/report/runner_predictions.parquet')
    research = research[research.variant.eq('F1_STYLE6')].copy()
    pairs = pd.read_parquet(ROOT/'jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet')
    dates = sorted(pd.to_datetime(pairs.race_date).dt.strftime('%Y-%m-%d').unique())
    assert len(dates)==269
    datedict = {d:i for i,d in enumerate(dates)}
    schedule = np.load(ROOT/'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy',allow_pickle=False)
    assert schedule.shape==(2000,269)
    weights = np.stack([np.bincount(d,minlength=269) for d in schedule])
    qprice = pd.read_csv(PRIOR/'ROOT_QPL_QUOTE_REFERENCE.csv',dtype={'race_id':str,'raw_quote':str})
    pprice = pd.read_csv(PLCPRIOR/'ROOT_PLC_QUOTE_REFERENCE.csv',dtype={'race_id':str,'raw_quote':str})
    common = sorted(set(h.key)&set(pairs.race_id)&set(qprice.race_id))
    assert len(common)==467
    rp=[];rq=[];sets_ref=[]
    for key in common:
        a=h[h.key.eq(key)].sort_values('horse_number')
        b=research[research.race_id.eq(key)].sort_values('horse_number')
        assert np.array_equal(a.horse_number,b.horse_number)
        assert np.array_equal(a.horse_id,b.horse_id)
        assert np.array_equal(a.official_top3.astype(int),b.y.astype(int))
        assert not a.boundary_tie.any() and a.official_top3.sum()==3
        assert a.beta.nunique()==1
        z=a.score.to_numpy()*a.beta.iloc[0]
        w=np.exp(z-z.max());total=w.sum();n=len(a)
        ids=a.horse_number.to_numpy(int);truth=a.official_top3.to_numpy(int)
        setp={s:0. for s in combinations(range(n),3)}
        # Independent direct sequential probability, no project distribution imports.
        for i,j,k in permutations(range(n),3):
            value=w[i]/total * w[j]/(total-w[i]) * w[k]/(total-w[i]-w[j])
            setp[tuple(sorted((i,j,k)))]+=value
        assert abs(sum(setp.values())-1)<1e-12
        marg=np.zeros(n);pairp={p:0. for p in combinations(range(n),2)}
        for s,p in setp.items():
            for i in s:marg[i]+=p
            for ij in combinations(s,2):pairp[ij]+=p
            sets_ref.append(dict(race_id=key,horse_a=int(ids[s[0]]),horse_b=int(ids[s[1]]),horse_c=int(ids[s[2]]),p=p))
        assert np.allclose(marg,a.pl_place_probability,atol=1e-12,rtol=0)
        assert abs(marg.sum()-3)<1e-12 and abs(sum(pairp.values())-3)<1e-12
        for i in range(n):
            rp.append(dict(race_id=key,race_date=key[:10],horse_i=int(ids[i]),horse_j=0,p=float(marg[i]),rank_score=float(a.score.iloc[i]),y=int(truth[i]),field_n=n))
        for (i,j),p in pairp.items():
            rq.append(dict(race_id=key,race_date=key[:10],horse_i=int(ids[i]),horse_j=int(ids[j]),p=p,y=int(truth[i]*truth[j]),field_n=n))
    opq=pd.DataFrame(rq);opp=pd.DataFrame(rp)
    resq=pairs[pairs.race_id.isin(common)].copy()
    resq['p']=resq.jockey_id_candidate_calibrated_probability;resq['y']=resq.y_pair
    resp=research[research.race_id.isin(common)].copy()
    resp['p']=resp.p_top3;resp['horse_i']=resp.horse_number;resp['horse_j']=0;resp['rank_score']=resp.score
    opp=opp[opp.field_n.ge(8)].copy();resp=resp[resp.field_n.ge(8)].copy()
    plc_keys=sorted(set(opp.race_id)&set(pprice.race_id))
    assert set(resp.race_id)==set(plc_keys)
    pprice=pprice.rename(columns={'horse_number':'horse_i'})
    pprice['horse_j']=0
    sources=[('QPL','HY_R_FORM',opq,qprice),('QPL','research_pair_ID',resq,qprice),
             ('PLC','HY_R_FORM',opp,pprice),('PLC','research_F1_STYLE6',resp,pprice)]
    summaries=[];selections=[];full=[]
    for pool,model,frame,price in sources:
        f=frame.merge(price,on=['race_id','horse_i','horse_j'],validate='one_to_one')
        assert len(f)==len(frame)
        f['race_date']=pd.to_datetime(f.race_date).dt.strftime('%Y-%m-%d')
        f['quote']=f.raw_quote.astype(float);f['edge']=f.p*f.quote-1
        rank='rank_score' if pool=='PLC' else 'p'
        f=f.sort_values(['race_id',rank,'horse_i','horse_j'],ascending=[True,False,True,True])
        f['probability_rank']=f.groupby('race_id').cumcount()+1
        f['gross']=f.raw_quote.map(lambda x:int(Decimal(x)*1000))*f.y.astype(int)
        f['pool']=pool;f['model']=model
        full.append(f[['pool','model','race_id','horse_i','horse_j','p','probability_rank','quote','y','gross']])
        for rule,exact,top,pmin,edge in policies(pool):
            mask=pd.Series(True,index=f.index)
            if exact is not None:mask &= f.probability_rank.eq(exact)
            if top is not None:mask &= f.probability_rank.le(top)
            if pmin is not None:mask &= f.p.ge(pmin)
            if edge is not None:mask &= f.edge.gt(edge)
            c=f[mask].copy()
            if exact is None:
                tie=['probability_rank','horse_i','horse_j'] if pool=='PLC' else ['horse_i','horse_j']
                c=c.sort_values(['race_id','edge',*tie],ascending=[True,False,*([True]*len(tie))]).groupby('race_id').head(1)
            assert c.race_id.is_unique
            c['rule']=rule
            selections.append(c[['pool','model','rule','race_id','horse_i','horse_j','p','probability_rank','quote','edge','y','gross']])
            count=len(c);gross=int(c.gross.sum());stake=count*1000
            row=dict(pool=pool,model=model,rule=rule,eligible=f.race_id.nunique(),bets=count,hits=int(c.y.sum()),stake=stake,gross=gross,net=gross-stake,roi=gross/stake-1 if stake else None,mean_p=c.p.mean(),mean_rank=c.probability_rank.mean())
            ix=c.race_date.map(datedict).to_numpy(int)
            counts=np.bincount(ix,minlength=269);g=np.bincount(ix,weights=c.gross,minlength=269)
            den=weights@counts;valid=den>0
            draw=(weights@g)[valid]/(1000*den[valid])-1
            row['roi_ci_low'],row['roi_ci_high']=np.quantile(draw,[.025,.975])
            for k in [1,3,5]:
                win=c[c.y.eq(1)].sort_values(['gross','race_id'],ascending=[False,True]).head(k)
                reduced=count-len(win)
                row[f'roi_without_top{k}']=(gross-int(win.gross.sum()))/(1000*reduced)-1 if reduced else None
            summaries.append(row)
    for name,f in [('root_all_candidate_reference.csv',pd.concat(full)),('root_selection_reference.csv',pd.concat(selections)),('root_summary_reference.csv',pd.DataFrame(summaries)),('root_native_set_reference.csv',pd.DataFrame(sets_ref))]:
        with (OUT/name).open('x') as stream:f.to_csv(stream,index=False)
    receipt=dict(common_qpl_races=len(common),common_plc_races=len(plc_keys),operating_saved_scores_match_frozen=True,rosters_ids_numbers_labels_match=True,all_native_marginals_reproduced=True,native_qpl_sum_is_3=True,no_training=True)
    with (OUT/'root_source_verification.json').open('x') as stream:json.dump(receipt,stream,indent=2)
    print(json.dumps(receipt));print(pd.DataFrame(summaries).to_string(index=False))


if __name__=='__main__':main()
