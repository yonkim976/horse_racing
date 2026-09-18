"""Price-blind locked tickets, then historical official gross dividend settlement."""
import hashlib,json,sqlite3
from collections import defaultdict
from datetime import datetime,UTC
from itertools import combinations
from pathlib import Path

import numpy as np
import polars as pl

from horse_racing.analysis.jeju_wager_probabilities import markets,portfolio,ticket_hits

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/research/jeju_annual_returns_20260918'
ANN=ROOT/'data/research/jeju_annual_revalidation_20260918'
P26=ROOT/'data/research/jeju_steward_pace_v2_pilot_20260918'
DATA=ROOT/'data/research/jeju_native_top3_dataset_v1_20260915_r2'
DB=ROOT/'data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3'
MARKETS=['WIN','PLC','QNL','EXA','QPL','TLA','TRI']

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str,allow_nan=False))
def key(m,numbers):
    return tuple(sorted(numbers)) if m in ['QNL','QPL','TLA'] else tuple(numbers)
def winning(m,actual,n):
    if m=='WIN':return [(actual[0],)]
    if m=='PLC':return [(i,) for i in actual[:2 if n<=7 else 3]]
    if m=='QNL':return [key(m,actual[:2])]
    if m=='EXA':return [actual[:2]]
    if m=='QPL':return [key(m,x) for x in combinations(actual,2)]
    if m=='TLA':return [key(m,actual)]
    if m=='TRI':return [actual]
    raise ValueError(m)

def day_boot(rows,field,adjust=1):
    days=sorted({r['date'] for r in rows});totals=np.zeros(len(days));counts=np.zeros(len(days))
    for i,d in enumerate(days):
        v=[r[field] for r in rows if r['date']==d];totals[i]=sum(v);counts[i]=len(v)
    ix=np.random.default_rng(17).integers(0,len(days),(5000,len(days)))
    b=totals[ix].sum(axis=1)/counts[ix].sum(axis=1)
    return np.quantile(b,[.025/adjust,1-.025/adjust]).tolist()

def main():
    OUT.mkdir(exist_ok=False)
    assert (ANN/'prediction_lock.json').exists()
    columns=['entry_id','race_id','horse_id','event_date','model','score','order_score','beta','beta_order']
    scores=pl.concat([pl.read_parquet(ANN/'frozen_scores.parquet').filter(pl.col('model')=='BASE').select(columns),
                     pl.read_parquet(P26/'frozen_scores.parquet').filter(pl.col('model')=='BASE').select(columns)])
    obs={r['entry_id']:r for r in pl.read_parquet(ROOT/'data/research/jeju_tempo_pace_features_20260917/observations.parquet').to_dicts()}
    meta={r['race_id']:r for r in pl.read_parquet(DATA/'races.parquet').to_dicts()}
    accepted=defaultdict(list)
    for r in pl.read_parquet(DATA/'accepted_orders.parquet').to_dicts():accepted[r['race_id']].append((r['first_horse_id'],r['second_horse_id'],r['third_horse_id']))
    labels={(r['race_id'],r['horse_id']):r['label_top3'] for r in pl.read_parquet(DATA/'labels.parquet').to_dicts()}
    policies=[];market_races=[];gap_races=[];excluded=[];actuals={};race_sizes={}
    for (rid,),part in scores.partition_by('race_id',as_dict=True).items():
        part=part.sort('horse_id');r=part.row(0,named=True);ids=part['horse_id'].to_list();n=len(ids)
        day=r['event_date'].isoformat();year=r['event_date'].year
        number={row['horse_id']:obs[row['entry_id']]['horse_number'] for row in part.to_dicts()}
        v=markets(ids,part['score'].to_numpy(),part['order_score'].to_numpy(),r['beta'],r['beta_order'])
        ranked=sorted(zip(ids,v['top3'],strict=True),key=lambda x:(-x[1],x[0]));gap=float(ranked[2][1]-ranked[3][1])
        bucket='0to2pp' if gap<.02 else '2to5pp' if gap<.05 else '5to10pp' if gap<.1 else '10pluspp'
        gap_races.append(dict(year=year,race_id=rid,date=day,bucket=bucket,gap=gap,
            p3=float(ranked[2][1]),p4=float(ranked[3][1]),y3=int(labels[(rid,ranked[2][0])]),y4=int(labels[(rid,ranked[3][0])]),
            difference=int(labels[(rid,ranked[2][0])])-int(labels[(rid,ranked[3][0])])) )
        if len(accepted[rid])!=1:
            excluded.append(dict(year=year,race_id=rid,date=day,reason='podium_or_boundary_dead_heat'));continue
        actuals[rid]=tuple(number[h] for h in accepted[rid][0]);race_sizes[rid]=n
        common=dict(year=year,race_id=rid,date=day,race_number=meta[rid]['event_number'],field_size=n)
        for m in MARKETS:
            t=v['markets'][m][0]
            hit=ticket_hits(m,t['selection'],accepted[rid][0],n)
            market_races.append(dict(**common,market=m,probability=t['probability'],hit=hit))
            policies.append(dict(**common,policy=f'{m}_TOP1',market=m,tickets=[[number[h] for h in t['selection']]],
                probability=t['probability'],k=1,total_stake=1.))
        for k in [1,3,6,10]:
            for label,anchor in [('ALL',None),('ANCHOR',ranked[0][0])]:
                p=portfolio(v,'TLA',k,anchor);assert p['ticket_count']==k
                policies.append(dict(**common,policy=f'TLA_{label}_{k}',market='TLA',tickets=[[number[h] for h in t] for t in p['tickets']],
                    probability=p['any_hit_probability'],k=k,total_stake=1.))
        a,b=v['markets']['QNL'][0]['selection']
        policies.append(dict(**common,policy='EXA_QNL_PAIR_BOTH',market='EXA',tickets=[[number[a],number[b]],[number[b],number[a]]],
            probability=v['markets']['QNL'][0]['probability'],k=2,total_stake=1.))
    save('tickets_locked.json',policies)
    save('selection_lock.json',dict(created_at=datetime.now(UTC).isoformat(),tickets_sha256=sha(OUT/'tickets_locked.json'),
        protocol_sha256=sha(ROOT/'docs/JEJU_MULTYEAR_RETURN_PROTOCOL_2026-09-18.md'),
        score_sources={str(p.relative_to(ROOT)):sha(p) for p in [ANN/'frozen_scores.parquet',P26/'frozen_scores.parquet']},
        price_inputs_used_for_selection=False))
    save('excluded_races.json',excluded)
    # Only after ticket selection/lock: open price sources. Current-price strategies are out of scope.
    c=sqlite3.connect(f"file:{ROOT/'data/horse_racing.sqlite3'}?mode=ro",uri=True);c.row_factory=sqlite3.Row
    docs=[dict(r) for r in c.execute("""SELECT s.id,s.ingestion_run_id,s.local_path,s.sha256,s.retrieved_at_ms,
        json_extract(s.request_params_json,'$.rc_date') day FROM source_documents s
        JOIN ingestion_runs i ON i.id=s.ingestion_run_id WHERE i.data_type='final_dividend' AND i.status='completed'
        AND json_extract(s.request_params_json,'$.meet')=2
        AND json_extract(s.request_params_json,'$.rc_date') BETWEEN '20250101' AND '20260912'""")];c.close()
    latest={}
    for d in docs:latest[d['day']]=max(latest.get(d['day'],0),d['ingestion_run_id'])
    docs=[d for d in docs if d['ingestion_run_id']==latest[d['day']]]
    prices={};price_sources={};bad=[]
    for d in docs:
        path=ROOT/d['local_path'];assert sha(path)==d['sha256']
        raw=json.loads(path.read_text())['response']['body'];items=(raw.get('items') or {}).get('item',[])
        if isinstance(items,dict):items=[items]
        for row in items:
            if row['meet']!='제주':raise ValueError('Wrong meet')
            m=row['pool'];day=str(row['rcDate']);day=day[:4]+'-'+day[4:6]+'-'+day[6:]
            nums=tuple(int(row.get(x) or 0) for x in ['chulNo','chulNo2','chulNo3']);nums=tuple(x for x in nums if x)
            try:odds=float(row['odds'])
            except (ValueError,TypeError):continue
            if m not in MARKETS or odds<=0:continue
            k=(day,int(row['rcNo']),m,key(m,nums))
            if k in prices and not np.isclose(prices[k],odds):raise ValueError(f'Conflicting raw prices {k}')
            prices[k]=odds;price_sources[k]=dict(kind='official_final_dividend_cache',document_id=d['id'],path=d['local_path'],sha256=d['sha256'])
    # Earlier years have individual final dividends in official result records.
    c=sqlite3.connect(f'file:{DB}?mode=ro',uri=True);c.row_factory=sqlite3.Row
    entries=[dict(r) for r in c.execute("""SELECT e.id entry_id,v.event_date,v.event_number,e.horse_number,
        json_extract(s.normalized_json,'$.winOdds') win_odds,json_extract(s.normalized_json,'$.plcOdds') place_odds,
        s.id source_row_id,a.path source_path,a.sha256 source_sha256
        FROM entry e JOIN event v ON v.id=e.event_id JOIN source_row s ON s.id=e.source_row_id
        JOIN source_artifact a ON a.id=s.source_artifact_id
        WHERE v.event_type='race' AND v.event_date BETWEEN '20240101' AND '20260912' AND e.breed_status='native_confirmed'""")];c.close()
    source_files={};crosschecks=0
    for r in entries:
        source_files[r['source_path']]=r['source_sha256']
        d=r['event_date'];day=d[:4]+'-'+d[4:6]+'-'+d[6:]
        for m,col in [('WIN','win_odds'),('PLC','place_odds')]:
            try:value=float(r[col])
            except (ValueError,TypeError):continue
            if value<=0:continue
            k=(day,r['event_number'],m,(r['horse_number'],))
            if k in prices:
                # Only winning-dividend disagreements matter for settlement;
                # preserve both and verify those keys later.
                if not np.isclose(prices[k],value):bad.append(dict(key=list(k[:3])+[list(k[3])],cache=prices[k],result=value))
                else:crosschecks+=1
            else:
                prices[k]=value;price_sources[k]=dict(kind='official_result_record',source_row_id=r['source_row_id'],path=r['source_path'],sha256=r['source_sha256'])
    for name,digest in source_files.items():assert sha(ROOT/name)==digest,name
    conflicts={(r['key'][0],r['key'][1],r['key'][2],tuple(r['key'][3])) for r in bad}
    settlement={};settlement_sources=[];unknown=[]
    unique={(p['race_id'],p['market']):(p['date'],p['race_number']) for p in policies}
    for (rid,m),(day,rno) in unique.items():
        pays={};reason=None
        for nums in winning(m,actuals[rid],race_sizes[rid]):
            k=(day,rno,m,nums);value=prices.get(k)
            if k in conflicts:reason='winning_dividend_source_conflict';break
            if value is None:reason='winning_dividend_missing';break
            if not np.isfinite(value) or value>=9999.9:reason='winning_dividend_cap_or_sentinel_unverified';break
            pays[nums]=value
            settlement_sources.append(dict(race_id=rid,date=day,race_number=rno,market=m,selection=list(nums),odds=value,source=price_sources[k]))
        if reason:unknown.append(dict(race_id=rid,year=int(day[:4]),market=m,reason=reason))
        else:settlement[(rid,m)]=pays
    settled=[]
    for p in policies:
        pays=settlement.get((p['race_id'],p['market']))
        if pays is None:continue
        returns=[pays.get(key(p['market'],t),0.)/p['k'] for t in p['tickets']]
        settled.append(dict(**p,hit=any(x>0 for x in returns),gross_return=sum(returns),net_return=sum(returns)-1))
    save('settled_races.json',settled);save('settlement_sources.json',settlement_sources)
    save('unsettled_race_markets.json',unknown)
    summaries=[];quarters=[]
    for year in [2024,2025,2026]:
        for name in sorted({p['policy'] for p in policies}):
            full=[p for p in policies if p['year']==year and p['policy']==name]
            rows=sorted([r for r in settled if r['year']==year and r['policy']==name],key=lambda r:(r['date'],r['race_number']))
            if not rows:
                summaries.append(dict(year=year,policy=name,target_races=len(full),settled_races=0,unsettled=len(full),gross_recovery=None));continue
            values=np.array([r['gross_return'] for r in rows]);order=np.argsort(values)[::-1]
            top3=values[order[:3]].sum();cash=np.cumsum(values-1);peak=np.maximum.accumulate(np.r_[0,cash])
            summaries.append(dict(year=year,policy=name,target_races=len(full),settled_races=len(rows),unsettled=len(full)-len(rows),
                hits=sum(r['hit'] for r in rows),hit_rate=float(np.mean([r['hit'] for r in rows])),
                stake_total=float(len(rows)),gross_paid=float(values.sum()),gross_recovery=float(values.mean()),net_roi=float(values.mean()-1),
                gross_recovery_ci95=day_boot(rows,'gross_return'),top3_share_of_gross=float(top3/values.sum()) if values.sum()>0 else None,
                recovery_excluding_top3=float(np.delete(values,order[:3]).mean()) if len(rows)>3 else None,
                max_drawdown_units=float(np.max(peak[1:]-cash)),largest_return=float(values.max())))
            for q in range(1,5):
                g=[r for r in rows if (int(r['date'][5:7])-1)//3+1==q]
                if g:quarters.append(dict(year=year,quarter=q,policy=name,races=len(g),gross_recovery=float(np.mean([r['gross_return'] for r in g]))))
    gaps=[]
    for year in [2024,2025,2026]:
        for bucket in ['0to2pp','2to5pp','5to10pp','10pluspp']:
            g=[r for r in gap_races if r['year']==year and r['bucket']==bucket]
            gaps.append(dict(year=year,bucket=bucket,races=len(g),predicted_gap=float(np.mean([r['gap'] for r in g])),
                actual3=float(np.mean([r['y3'] for r in g])),actual4=float(np.mean([r['y4'] for r in g])),
                difference=float(np.mean([r['difference'] for r in g])),ci95=day_boot(g,'difference'),simultaneous95_12bins=day_boot(g,'difference',12)))
    market_summary=[]
    for year in [2024,2025,2026]:
        for m in MARKETS:
            g=[r for r in market_races if r['year']==year and r['market']==m]
            market_summary.append(dict(year=year,market=m,races=len(g),hits=sum(r['hit'] for r in g),mean_probability=float(np.mean([r['probability'] for r in g]))))
    save('summary.json',summaries);save('quarters.json',quarters);save('gap_summary.json',gaps);save('gap_races.json',gap_races)
    save('market_summary.json',market_summary);save('market_races.json',market_races)
    save('source_audit.json',dict(raw_final_dividend_documents=len(docs),result_source_files=len(source_files),
        matching_individual_prices=crosschecks,all_individual_conflicts=bad,raw_documents=docs,
        result_sources=source_files,source_database_sha256=sha(DB),settlement_winning_sources=len(settlement_sources)))
    save('manifest.json',dict(inputs={str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__),ROOT/'docs/JEJU_MULTYEAR_RETURN_PROTOCOL_2026-09-18.md',ANN/'frozen_scores.parquet',P26/'frozen_scores.parquet']},
        outputs={p.name:sha(p) for p in OUT.iterdir()}))
    print(json.dumps(summaries,ensure_ascii=False))

if __name__=='__main__':main()
