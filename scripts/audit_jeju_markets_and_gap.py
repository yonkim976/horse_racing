"""Fixed-score probability gaps and equal-ticket market portfolios; no price selection."""
import hashlib,json,sqlite3
from pathlib import Path

import numpy as np
import polars as pl

from horse_racing.analysis.jeju_wager_probabilities import markets,portfolio,ticket_hits

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/research/jeju_markets_gap_20260918'
BASE=ROOT/'data/research/jeju_tempo_pace_pilot_20260917'
DATA=ROOT/'data/research/jeju_native_top3_dataset_v1_20260915_r2'

def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str,allow_nan=False))

def boot(rows,field,comparisons=1):
    days=sorted({r['event_date'] for r in rows})
    if not days:return [None,None]
    counts=np.array([sum(r['event_date']==d for r in rows) for d in days])
    sums=np.array([sum(r[field] for r in rows if r['event_date']==d) for d in days])
    ix=np.random.default_rng(17).integers(0,len(days),(5000,len(days)))
    x=sums[ix].sum(axis=1)/counts[ix].sum(axis=1)
    return np.quantile(x,[.025/comparisons,1-.025/comparisons]).tolist()

def main():
    OUT.mkdir(exist_ok=False)
    scores=pl.read_parquet(BASE/'frozen_scores.parquet').filter(pl.col('model')=='BASE__BASE')
    probs=pl.read_parquet(BASE/'horse_predictions.parquet').filter(pl.col('model')=='BASE__BASE')
    accepted={}
    for r in pl.read_parquet(DATA/'accepted_orders.parquet').filter(pl.col('event_date').dt.year()==2026).to_dicts():
        accepted.setdefault(r['race_id'],[]).append((r['first_horse_id'],r['second_horse_id'],r['third_horse_id']))
    lookup={(r['race_id'],r['horse_id']):r for r in probs.to_dicts()}
    gaps=[];tickets=[];best=[];ties=[];examples=[]
    for (rid,),part in scores.partition_by('race_id',as_dict=True).items():
        part=part.sort('horse_id');rs=part.to_dicts();ids=part['horse_id'].to_list();n=len(ids)
        day=rs[0]['event_date']
        ps=sorted([lookup[(rid,h)] for h in ids],key=lambda r:(-r['p'],r['horse_id']))
        gap=ps[2]['p']-ps[3]['p']
        bucket='0to2pp' if gap<.02 else '2to5pp' if gap<.05 else '5to10pp' if gap<.1 else '10pluspp'
        gaps.append(dict(race_id=rid,event_date=day,gap=gap,bucket=bucket,p3=ps[2]['p'],p4=ps[3]['p'],
            y3=ps[2]['y'],y4=ps[3]['y'],difference=ps[2]['y']-ps[3]['y'],
            third_id=ps[2]['horse_id'],fourth_id=ps[3]['horse_id']))
        if len(accepted[rid])!=1:
            ties.append(rid);continue
        actual=accepted[rid][0]
        v=markets(ids,part['score'].to_numpy(),part['order_score'].to_numpy(),rs[0]['beta'],rs[0]['beta_order'])
        assert np.isclose(sum(v['joint']),1)
        assert np.allclose(v['top3'],[lookup[(rid,h)]['p'] for h in ids])
        for m,rows in v['markets'].items():
            r=rows[0];hit=ticket_hits(m,r['selection'],actual,n)
            best.append(dict(race_id=rid,event_date=day,market=m,selection=list(r['selection']),
                 probability=r['probability'],hit=hit,brier=(r['probability']-hit)**2,
                 field_size=n,place_slots=v['place_slots']))
        anchor=ps[0]['horse_id']
        for k in [1,3,6,10]:
            for policy,a in [('unrestricted',None),('one_anchor',anchor)]:
                p=portfolio(v,'TLA',k,a)
                assert p['ticket_count']==k
                hit=any(ticket_hits('TLA',t,actual,n) for t in p['tickets'])
                tickets.append(dict(race_id=rid,event_date=day,policy=policy,k=k,
                    hit=hit,probability=p['any_hit_probability'],anchor=anchor,anchor_hit=anchor in actual,
                    selections=[list(t) for t in p['tickets']],total_budget=1.,per_ticket_weight=1/k))
        if len(examples)<3:
            examples.append(dict(race_id=rid,date=day,anchor=anchor,top3_probabilities=[dict(horse_id=r['horse_id'],p=r['p']) for r in ps],
                top6_trio=[dict(selection=list(r['selection']),probability=r['probability']) for r in v['markets']['TLA'][:6]]))
    grouped=[]
    for name in ['0to2pp','2to5pp','5to10pp','10pluspp']:
        g=[r for r in gaps if r['bucket']==name]
        grouped.append(dict(bucket=name,races=len(g),days=len({r['event_date'] for r in g}),
            mean_gap=float(np.mean([r['gap'] for r in g])) if g else None,
            predicted3=float(np.mean([r['p3'] for r in g])) if g else None,
            predicted4=float(np.mean([r['p4'] for r in g])) if g else None,
            actual3=float(np.mean([r['y3'] for r in g])) if g else None,
            actual4=float(np.mean([r['y4'] for r in g])) if g else None,
            difference=float(np.mean([r['difference'] for r in g])) if g else None,
            difference_ci95=boot(g,'difference'),simultaneous_ci95_4bins=boot(g,'difference',4)))
    port=[]
    for k in [1,3,6,10]:
        for policy in ['unrestricted','one_anchor']:
            g=[r for r in tickets if r['k']==k and r['policy']==policy]
            port.append(dict(k=k,policy=policy,races=len(g),hits=sum(r['hit'] for r in g),
                actual_rate=float(np.mean([r['hit'] for r in g])),mean_probability=float(np.mean([r['probability'] for r in g])),
                total_budget_per_race=1.,per_ticket_weight=1/k))
    summary=[]
    for m in ['WIN','PLC','QNL','EXA','QPL','TLA','TRI']:
        g=[r for r in best if r['market']==m]
        summary.append(dict(market=m,races=len(g),hits=sum(r['hit'] for r in g),
            actual_rate=float(np.mean([r['hit'] for r in g])),mean_probability=float(np.mean([r['probability'] for r in g])),
            selected_ticket_brier=float(np.mean([r['brier'] for r in g]))))
    c=sqlite3.connect(f"file:{ROOT/'data/horse_racing.sqlite3'}?mode=ro",uri=True);c.row_factory=sqlite3.Row
    odds=[dict(r) for r in c.execute("""SELECT o.bet_type,count(*) rows,count(distinct r.id) races,
        min(r.race_date_local) first_race,max(r.race_date_local) last_race,
        sum(case when o.observed_at_ms<r.scheduled_at_ms then 1 else 0 end) observed_before_scheduled
        FROM odds_snapshots o JOIN races r ON r.id=o.race_id JOIN racecourses rc ON rc.id=r.racecourse_id
        WHERE rc.kra_meet_code=2 AND r.race_date_local BETWEEN '2024-01-01' AND '2026-09-12'
        GROUP BY o.bet_type""")]
    pre=[dict(r) for r in c.execute("""SELECT r.race_date_local,r.race_number,o.bet_type,count(*) rows,
        min(o.observed_at_ms) min_observed_at_ms,max(o.observed_at_ms) max_observed_at_ms,
        r.scheduled_at_ms,min(o.selection_key) min_selection,max(o.selection_key) max_selection
        FROM odds_snapshots o JOIN races r ON r.id=o.race_id JOIN racecourses rc ON rc.id=r.racecourse_id
        WHERE rc.kra_meet_code=2 AND r.race_date_local<='2026-09-12' AND o.observed_at_ms<r.scheduled_at_ms
        GROUP BY r.id,o.bet_type""")];c.close()
    save('gap_summary.json',grouped);save('portfolios_summary.json',port);save('market_summary.json',summary)
    save('odds_inventory.json',dict(by_market=odds,before_scheduled_rows=pre,
        finding='Most stored prices are post-race snapshots; a partial one-race pre-scheduled subset is not a complete verified pre-bet book.',
        price_based_roi_evaluated=False))
    save('gap_races.json',gaps);save('portfolio_races.json',tickets);save('market_races.json',best)
    save('examples.json',examples)
    save('verification.json',dict(gap_races=len(gaps),market_races=len(gaps)-len(ties),excluded_tie_race_ids=ties,
        top3_marginals_replay=True,ordered_probability_sums_one=True,small_fields=sum(len(g)<8 for g in scores.partition_by('race_id')),
        no_new_model_fits=True,no_price_selection=True))
    paths=[BASE/'frozen_scores.parquet',BASE/'horse_predictions.parquet',DATA/'accepted_orders.parquet',
        ROOT/'docs/JEJU_STEWARD_MARKETS_PROTOCOL_2026-09-18.md',Path(__file__),ROOT/'src/horse_racing/analysis/jeju_wager_probabilities.py']
    save('manifest.json',dict(inputs={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        outputs={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir()}))
    print(json.dumps(dict(gaps=grouped,portfolios=port,markets=summary,tie_races=ties),ensure_ascii=False))

if __name__=='__main__':main()
