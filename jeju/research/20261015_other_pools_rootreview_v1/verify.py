"""Direct raw JSON prices and independent hybrid-event probability reconstruction."""
from pathlib import Path
from itertools import combinations,permutations
from collections import defaultdict
from decimal import Decimal
import hashlib,json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
POOLS=('WIN','QNL','EXA','TLA','TRI')
ARITY={'WIN':1,'QNL':2,'EXA':2,'TLA':3,'TRI':3}
UNORDERED={'QNL','TLA'}


def key(pool,numbers):
    values=tuple(int(i) for i in numbers[:ARITY[pool]])
    if pool in UNORDERED:values=tuple(sorted(values))
    assert len(set(values))==len(values) and min(values)>0
    return '-'.join(map(str,values))


def policies():
    return [(f'rank_{i}',i,None,None) for i in range(1,6)]+[
        ('rank_1_ev_positive',1,None,0),('max_ev_all',None,None,0),
        ('max_ev_top3',None,3,0),('max_ev_top5',None,5,0),
        ('max_ev_top3_edge020',None,3,.2)]


def main():
    prior=ROOT/'jeju/research/20261015_operating_postrace_value_comparison_v1'
    cohort=pd.read_csv(prior/'cohort.csv')
    ids=set(cohort.loc[cohort.qpl_eligible.eq(True),'race_id'])
    assert len(ids)==467
    dates={i[:10] for i in ids}
    pages=pd.read_csv(ROOT/'jeju/research/20261014_single_place_returns_v1/source_audit/SOURCE_PAGE_MANIFEST.csv')
    pages=pages[pages.race_date.isin(dates)]
    quotes=[];seen=set();sourcehashes={}
    for row in pages.itertuples(index=False):
        path=(ROOT/row.source_path).resolve()
        assert path.is_relative_to(ROOT) and path.is_file()
        body=path.read_bytes();sha=hashlib.sha256(body).hexdigest()
        assert sha==row.source_sha256
        sourcehashes[row.source_path]=sha
        items=json.loads(body)['response']['body']['items']['item']
        if isinstance(items,dict):items=[items]
        for raw in items:
            d=str(raw['rcDate']);rid=f'{d[:4]}-{d[4:6]}-{d[6:8]}_2_{int(raw["rcNo"])}'
            pool=raw['pool']
            if rid not in ids or pool not in POOLS:continue
            assert raw['meet'] in ['제주',2,'2']
            nums=[raw.get('chulNo',0),raw.get('chulNo2',0),raw.get('chulNo3',0)]
            assert all(int(x)==0 for x in nums[ARITY[pool]:])
            sel=key(pool,nums);business=(rid,pool,sel)
            assert business not in seen;seen.add(business)
            text=str(raw.get('odds'));price=float(text)
            valid=np.isfinite(price) and price>0 and price!=9999.9
            quotes.append(dict(race_id=rid,pool=pool,selection_key=sel,raw_quote=text,quote=price,valid=valid,source_sha256=sha))
    quotes=pd.DataFrame(quotes)
    quotes.to_parquet(HERE/'ROOT_RAW_QUOTES.parquet',index=False)
    legacy=ROOT/'data/research/jeju_native_transition_holdout_v13_20260916'
    h=pd.read_parquet(legacy/'horse_predictions.parquet');h=h[h.model.eq('HY_R_FORM')].copy()
    e=pd.read_parquet(ROOT/'data/research/jeju_native_top3_dataset_v1_20260915_r2/entries.parquet').set_index('entry_id').loc[h.entry_id]
    assert np.array_equal(e.horse_id,h.horse_id)
    h['horse_number']=e.horse_number.to_numpy(int)
    h['key']=[f'{str(d)[:10]}_2_{int(n)}' for d,n in zip(h.event_date,e.event_number)]
    h=h[h.key.isin(ids)].copy()
    official=pd.read_csv(ROOT/'jeju/research/20261014_single_place_returns_v1/source_audit/OFFICIAL_RUNNER_RESULTS.csv',dtype={'race_id':str})
    research=pd.read_parquet(ROOT/'jeju/research/20261010_style_history_ablation_v1/outputs/report/runner_predictions.parquet')
    research=research[research.variant.eq('F1_STYLE6')&research.race_id.isin(ids)].copy()
    tau=.9719459584109199
    candidates=[]
    for rid,g in h.groupby('key'):
        g=g.sort_values('horse_number');n=len(g);num=g.horse_number.to_numpy(int)
        truth=official[official.race_id.eq(rid)].sort_values('finish_position')
        assert truth.iloc[:3].finish_position.tolist()==[1,2,3]
        winning=truth.iloc[:3].horse_number.to_numpy(int)
        assert set(truth.horse_number)==set(num)
        weights=np.exp(g.score.to_numpy()*g.beta.iloc[0]-max(g.score*g.beta.iloc[0]))
        v=np.exp(g.order_score.to_numpy()*g.beta_order.iloc[0]-max(g.order_score*g.beta_order.iloc[0]))
        total=weights.sum()
        setp={s:0. for s in combinations(range(n),3)}
        for i,j,k in permutations(range(n),3):
            prob=weights[i]/total*weights[j]/(total-weights[i])*weights[k]/(total-weights[i]-weights[j])
            setp[tuple(sorted((i,j,k)))]+=prob
        events={pool:defaultdict(float) for pool in POOLS}
        for s,p in setp.items():
            events['TLA'][key('TLA',num[list(s)])]=p
            for i,j,k in permutations(s):
                prob=p*v[i]/(v[i]+v[j]+v[k])*v[j]/(v[j]+v[k])
                for pool in ['WIN','QNL','EXA','TRI']:
                    events[pool][key(pool,(num[i],num[j],num[k]))]+=prob
        for pool,ep in events.items():
            assert abs(sum(ep.values())-1)<1e-12
            expected=n if pool=='WIN' else n*(n-1)//2 if pool=='QNL' else n*(n-1) if pool=='EXA' else n*(n-1)*(n-2)//6 if pool=='TLA' else n*(n-1)*(n-2)
            assert len(ep)==expected
            for sel,p in ep.items():
                candidates.append(dict(race_id=rid,pool=pool,model='HY_R_FORM',selection_key=sel,p=p,hit=int(sel==key(pool,winning))))
        f=research[research.race_id.eq(rid)].sort_values('horse_number')
        assert np.array_equal(num,f.horse_number)
        ss=list(combinations(range(n),3))
        energy=np.array([sum(sorted(f.score.iloc[list(s)].tolist())) for s in ss])/tau
        q=np.exp(energy-energy.max());q/=q.sum()
        marg=np.zeros(n)
        for s,p in zip(ss,q):
            marg[list(s)]+=p
            sel=key('TLA',num[list(s)])
            candidates.append(dict(race_id=rid,pool='TLA',model='research_F1_STYLE6',selection_key=sel,p=p,hit=int(sel==key('TLA',winning))))
        assert np.allclose(marg,f.p_top3,atol=1e-12,rtol=0)
    full=pd.DataFrame(candidates).merge(quotes,on=['race_id','pool','selection_key'],validate='many_to_one')
    complete={pool:set(g.index[g]) for pool in POOLS for g in [quotes[quotes.pool.eq(pool)].groupby('race_id').valid.all()]}
    universal=set.intersection(*complete.values())
    assert len(universal)==222 and len(complete['TRI'])==222
    for pool in POOLS[:-1]:assert len(complete[pool])==467
    all_pairs=pd.read_parquet(ROOT/'jeju/research/20261012_pair_jockey_id_v1/outputs/evaluation_pair_predictions.parquet',columns=['race_date'])
    dates=sorted(pd.to_datetime(all_pairs.race_date).dt.strftime('%Y-%m-%d').unique());date_ix={d:i for i,d in enumerate(dates)}
    draw=np.load(ROOT/'jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy',allow_pickle=False)
    weights=np.stack([np.bincount(d,minlength=269) for d in draw])
    rows=[];chosen=[]
    for scope in ['pool_complete','all_five_common']:
        for (pool,model),f in full.groupby(['pool','model']):
            keys=complete[pool] if scope=='pool_complete' else universal
            f=f[f.race_id.isin(keys)].copy();assert f.valid.all()
            tuples=f.selection_key.map(lambda x:tuple(map(int,x.split('-'))))
            for i in range(3):f[f'horse_{i+1}']=tuples.map(lambda x:x[i] if len(x)>i else 0)
            tie=['horse_1','horse_2','horse_3']
            f=f.sort_values(['race_id','p',*tie],ascending=[True,False,True,True,True])
            f['probability_rank']=f.groupby('race_id').cumcount()+1
            f['edge']=f.p*f.quote-1
            f['gross']=f.raw_quote.map(lambda x:int(Decimal(x)*1000))*f.hit
            for rule,rank,top,edge in policies():
                mask=pd.Series(True,index=f.index)
                if rank is not None:mask &= f.probability_rank.eq(rank)
                if top is not None:mask &= f.probability_rank.le(top)
                if edge is not None:mask &= f.edge.gt(edge)
                c=f[mask].copy()
                if rank is None:c=c.sort_values(['race_id','edge',*tie],ascending=[True,False,True,True,True]).groupby('race_id').head(1)
                assert c.race_id.is_unique
                c['scope']=scope;c['rule']=rule;chosen.append(c)
                count=len(c);gross=int(c.gross.sum());stake=1000*count
                row=dict(scope=scope,pool=pool,model=model,rule=rule,eligible=len(keys),bets=count,hits=int(c.hit.sum()),stake=stake,gross=gross,net=gross-stake,roi=gross/stake-1 if stake else np.nan,mean_p=c.p.mean(),mean_rank=c.probability_rank.mean())
                ix=c.race_id.str[:10].map(date_ix).to_numpy(int)
                den=weights@np.bincount(ix,minlength=269);gg=weights@np.bincount(ix,weights=c.gross,minlength=269)
                valid=den>0
                row['ci_low'],row['ci_high']=np.quantile(gg[valid]/(1000*den[valid])-1,[.025,.975]) if valid.any() else (np.nan,np.nan)
                row['valid_draws']=int(valid.sum())
                for k in [1,3,5]:
                    wins=c[c.hit.eq(1)].sort_values(['gross','race_id'],ascending=[False,True]).head(k)
                    left=count-len(wins)
                    row[f'roi_without_top{k}']=(gross-int(wins.gross.sum()))/(1000*left)-1 if left else np.nan
                rows.append(row)
    summary=pd.DataFrame(rows)
    summary.to_csv(HERE/'ROOT_SUMMARY_REFERENCE.csv',index=False)
    pd.concat(chosen,ignore_index=True).to_parquet(HERE/'ROOT_SELECTION_REFERENCE.parquet',index=False)
    full.to_parquet(HERE/'ROOT_CANDIDATE_REFERENCE.parquet',index=False)
    audit=dict(source_pages=len(pages),source_sha256=sourcehashes,raw_candidate_quotes=quotes.groupby('pool').size().to_dict(),invalid_quotes=quotes[~quotes.valid].groupby('pool').size().to_dict(),complete_races={p:len(c) for p,c in complete.items()},universal_complete_races=len(universal),native_all_events_normalized=True,research_tla_marginals_reproduced=True,model_training=False)
    with (HERE/'ROOT_SOURCE_AUDIT.json').open('x') as stream:json.dump(audit,stream,indent=2)
    print({k:v for k,v in audit.items() if k!='source_sha256'})
    print(summary[summary.rule.isin(['rank_1','max_ev_all','max_ev_top3'])].to_string(index=False))


if __name__=='__main__':main()
