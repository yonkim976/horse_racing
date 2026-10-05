"""Frozen-model pool baselines: read-only, no fitting and no odds-based selection.

Compare the same cleaned 2026 cohort as the preceding trio audit. Derive pool
events from one coherent A joint (Busan) or HY_R_FORM joint (Jeju); calibrations
are NOT combined across A/B/C. These are derived baselines, not trained pool
specialists or prospective validated betting strategies. Final odds settle only.
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
import sqlite3
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
import polars as pl

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'data/research/thoroughbred_three_targets_20260918_v3/code'))
import targets_core as tc
from horse_racing.analysis.jeju_hybrid_evaluation import distribution

COHORT=ROOT/'reports/2026_trio_model_hit_analysis/race_evaluation.csv'
POOLS=('WIN','PLC','QPL','QNL','EXA','TLA')
LABELS={'WIN':'단승','PLC':'연승','QPL':'복연승','QNL':'복승','EXA':'쌍승','TLA':'삼복'}
SOURCE_PATHS=[COHORT]
CHECKS={}


def read(p):
    SOURCE_PATHS.append(p)
    return pl.read_parquet(p)


def ro(p):
    c=sqlite3.connect(f'file:{p}?mode=ro',uri=True);c.row_factory=sqlite3.Row
    return c


def code_keys(orders,n,cutoff):
    pair=np.sort(orders[:,:2],axis=1)
    qp=np.sort(orders[:,np.array([[0,1],[0,2],[1,2]])],axis=2)
    tr=np.sort(orders,axis=1)
    return dict(WIN=orders[:,0,None],PLC=orders[:,:cutoff],
                QPL=qp[:,:,0]*n+qp[:,:,1],QNL=(pair[:,0]*n+pair[:,1])[:,None],
                EXA=(orders[:,0]*n+orders[:,1])[:,None],
                TLA=(tr[:,0]*n*n+tr[:,1]*n+tr[:,2])[:,None])


def decode(code,n,numbers,pool):
    if pool in ('WIN','PLC'):idx=[code]
    elif pool=='TLA':idx=[code//(n*n),(code//n)%n,code%n]
    else:idx=[code//n,code%n]
    ns=[int(numbers[i]) for i in idx]
    if pool in ('QPL','QNL','TLA'):ns.sort()
    return '-'.join(map(str,ns))


def winning_keys(numbers,ranks,cutoff):
    truth=tc.build_target_truth(ranks)
    orders=truth.compatible_orders
    n=len(numbers)
    return {p:{decode(int(code),n,numbers,p) for code in matrix.ravel()} for p,matrix in code_keys(orders,n,cutoff).items()}


def distributions(cohort):
    wanted={r['source_race_id']:r for r in cohort if r['venue']=='제주'}
    jd=ROOT/'data/research/jeju_native_top3_dataset_v1_20260915_r2'
    hp=read(ROOT/'data/research/jeju_native_transition_holdout_v13_20260916/horse_predictions.parquet').filter(pl.col('model')=='HY_R_FORM')
    f=hp.join(read(jd/'labels.parquet').select('entry_id','horse_number'),on='entry_id',validate='1:1')
    out={};maxerr=0.
    for (rid,),part in f.group_by('race_id'):
        r=wanted[str(rid)];part=part.sort('horse_id')
        _,orders,_,lj,a=distribution(part['score'].to_numpy(),part['order_score'].to_numpy(),float(part['beta'][0]),float(part['beta_order'][0]))
        maxerr=max(maxerr,float(abs(a-part['pl_place_probability'].to_numpy()).max()))
        out[('제주',str(rid))]=(part['horse_number'].to_list(),part['horse_id'].to_list(),orders,np.exp(lj),a)
    CHECKS['jeju_saved_marginal_error']=maxerr
    assert maxerr<1e-10

    wanted={r['source_race_id']:r for r in cohort if r['venue']=='부산'}
    f=read(ROOT/'data/research/thoroughbred_three_targets_20260918_v3/prepared_context.parquet').filter(pl.col('race_id').is_in(list(wanted)))
    f=f.with_columns(pl.col('race_date').cast(pl.Datetime('us'))).join(read(ROOT/'data/research/thoroughbred_followup_20260918_v4/model/strict_features.parquet'),on=['race_id','hr_no','race_date'],validate='1:1').sort('race_date','race_id','chul_no','hr_no')
    wp=ROOT/'data/research/thoroughbred_win_research_20260918_v2/models/2026/H3_relative'
    SOURCE_PATHS.extend([wp/'model.txt',wp/'metadata.json'])
    wb=tc.load_v2_win_bundle(wp)
    ws=tc.raw_scores(wb,f.to_pandas())['win']
    f=f.with_columns(pl.Series('win_score',ws))
    ap=read(ROOT/'data/research/thoroughbred_boundary_20260918_v6/A_horse_predictions.parquet').filter((pl.col('candidate')=='current_A')&pl.col('race_id').is_in(list(wanted)))
    saved={(r['race_id'],r['hr_no']):r['probability'] for r in ap.to_dicts()}
    maxerr=0.
    # The retired H1 cache was an exact reuse of v4's still-retained 2026 bundle
    # including its A calibration (windows/reuse_manifest.json and run_windows.py).
    SOURCE_PATHS.extend([ROOT/'data/research/thoroughbred_offline_20260918_v5/windows/reuse_manifest.json',ROOT/'data/research/thoroughbred_offline_20260918_v5/windows/run_windows.py'])
    for half in (1,2):
        p=(ROOT/'data/research/thoroughbred_followup_20260918_v4/model/models/2026/top3_growth_strength' if half==1 else ROOT/'data/research/thoroughbred_offline_20260918_v5/windows/models/2026H2/rolling_all')
        SOURCE_PATHS.extend([p/'top3.txt',p/'metadata.json'])
        ab=tc.load_bundle(p)
        part=f.filter(pl.col('race_date').dt.month().is_between(1,6) if half==1 else pl.col('race_date').dt.month().is_between(7,12))
        part=part.with_columns(pl.Series('a_score',tc.raw_scores(ab,part.to_pandas())['top3']))
        at=ab.metadata['temperature_by_target_and_venue']['A']['BUSAN'];wt=wb.metadata['temperature_by_venue']['BUSAN']
        for (rid,),g in part.group_by('race_id'):
            j=tc.top3_set_joint(g['a_score'].to_numpy(),g['win_score'].to_numpy(),at,wt)
            ids=g['hr_no'].to_list();expected=np.array([saved[(rid,h)] for h in ids])
            maxerr=max(maxerr,float(abs(j.inclusion_probability-expected).max()))
            out[('부산',rid)]=(g['chul_no'].to_list(),ids,j.orders,j.order_probability,j.inclusion_probability)
    CHECKS['busan_saved_marginal_error']=maxerr
    assert maxerr<1e-10 and len(out)==1035
    return out


def evaluate(cohort,dists):
    c=ro(ROOT/'data/horse_racing.sqlite3')
    results=[];missing=[];refunds=defaultdict(int)
    for r in cohort:
        numbers,ids,orders,joint,a=dists[(r['venue'],r['source_race_id'])]
        n=len(numbers);rid=int(r['main_db_race_id']);assert n==int(r['field_size'])
        cutoff=3 if n>=8 else 2
        official={q['horse_number']:dict(q) for q in c.execute('SELECT e.horse_number,e.scratched,rr.finish_position FROM race_entries e JOIN race_results rr ON rr.race_entry_id=e.id WHERE e.race_id=?',(rid,))}
        scratched={no for no,q in official.items() if q['scratched'] or q['finish_position'] in (93,94,95)}
        assert set(numbers)<=set(official)
        ranks=[official[no]['finish_position'] for no in numbers]
        truth=winning_keys(numbers,ranks,cutoff)
        assert truth['TLA']==set(json.loads(r['actual_keys']))
        odds={}
        for q in c.execute('SELECT bet_type,selection_key,odds FROM odds_snapshots WHERE race_id=? ORDER BY observed_at_ms',(rid,)):
            if q['odds'] is not None and 1<=float(q['odds'])<9999.9:odds[(q['bet_type'],q['selection_key'])]=float(q['odds'])
        for pool in POOLS:
            for key in truth[pool]:
                if (pool,key) not in odds:missing.append([r['venue'],r['date'],r['race_no'],pool,key])
        codes=code_keys(orders,n,cutoff)
        best={};probs={}
        for pool,matrix in codes.items():
            binc=np.bincount(matrix.ravel(),weights=np.repeat(joint,matrix.shape[1]))
            support=np.unique(matrix)
            probs[pool]={int(code):float(binc[code]) for code in support}
            best[pool]=sorted(support.tolist(),key=lambda code:(-binc[code],tuple(ids[i] for i in ([code] if pool in ('WIN','PLC') else ([code//n,code%n] if pool!='TLA' else [code//(n*n),(code//n)%n,code%n])))))
        arank=sorted(range(n),key=lambda i:(-float(a[i]),str(ids[i])))
        strategies=[]
        for pool in ('WIN','PLC','QPL','QNL','EXA'):
            for k in (1,3):strategies.append((f'{pool}_joint_top{k}',pool,best[pool][:k]))
        for pool in ('QPL','QNL','EXA'):
            strategies.append((f'{pool}_joint_top6',pool,best[pool][:6]))
        strategies.append(('PLC_A_rank1','PLC',[arank[0]]))
        pair=sorted(arank[:2])
        for pool in ('QPL','QNL'):strategies.append((f'{pool}_A_rank12',pool,[pair[0]*n+pair[1]]))
        strategies.append(('EXA_A_rank1to2','EXA',[arank[0]*n+arank[1]]))
        for pool in ('QPL','QNL'):
            pairs=[sorted([arank[0],other]) for other in arank[1:4]]
            strategies.append((f'{pool}_A_axis3',''+pool,[p[0]*n+p[1] for p in pairs]))
        strategies.append(('EXA_A_axis3','EXA',[arank[0]*n+other for other in arank[1:4]]))
        for name,pool,chosen in strategies:
            tickets=[decode(int(code),n,numbers,pool) for code in chosen]
            actual=[t for t in tickets if t in truth[pool]]
            rf=[t for t in tickets if any(int(no) in scratched for no in t.split('-'))]
            assert not set(actual)&set(rf)
            gross=sum(odds[(pool,t)] for t in actual)+len(rf)
            mask=np.isin(codes[pool],chosen).any(axis=1)
            results.append(dict(venue=r['venue'],date=r['date'],race_no=int(r['race_no']),main_db_race_id=rid,strategy=name,pool=pool,tickets=tickets,winning_tickets=actual,refund_tickets=rf,
                                stake_units=len(tickets),return_units=gross,winning_return_units=gross-len(rf),hit=bool(actual),profit=gross>len(tickets)+1e-9,nonloss=gross>=len(tickets)-1e-9,
                                model_union_probability=float(joint[mask].sum()),mean_ticket_probability=float(np.mean([probs[pool][int(code)] for code in chosen])),field_size=n,place_cutoff=cutoff))
            refunds[name]+=len(rf)
        # Preserve the prior B-selected six-trio rule; add refunds without changing tickets.
        tickets=json.loads(r['b6_tickets']);actual=[t for t in tickets if t in truth['TLA']];rf=[t for t in tickets if any(int(no) in scratched for no in t.split('-'))]
        gross=sum(odds[('TLA',t)] for t in actual)+len(rf)
        results.append(dict(venue=r['venue'],date=r['date'],race_no=int(r['race_no']),main_db_race_id=rid,strategy='TLA_B_top6_reference',pool='TLA',tickets=tickets,winning_tickets=actual,refund_tickets=rf,
                            stake_units=6,return_units=gross,winning_return_units=gross-len(rf),hit=bool(actual),profit=gross>6+1e-9,nonloss=gross>=6-1e-9,model_union_probability=float(r['b6_model_probability']),mean_ticket_probability=None,field_size=n,place_cutoff=cutoff))
    c.close()
    assert not missing,missing[:10]
    CHECKS['winning_odds_missing']=missing;CHECKS['refund_counts']=dict(refunds)
    CHECKS['place_cutoff']=dict(two_place_races=sum(int(r['field_size'])<=7 for r in cohort),three_place_races=sum(int(r['field_size'])>=8 for r in cohort),policy='Preserved prediction-card size; official May31/June14 Busan R2 verify three-place payout despite seven actual starters.')
    return results


def summarize(rows):
    n=len(rows);hits=sum(r['hit'] for r in rows);stake=sum(r['stake_units'] for r in rows);gross=sum(r['return_units'] for r in rows);profit=sum(r['profit'] for r in rows)
    dates=sorted(set(r['date'] for r in rows));days=[]
    monthly={}
    for d in dates:
        rr=[r for r in rows if r['date']==d];days.append((sum(r['return_units'] for r in rr),sum(r['stake_units'] for r in rr)))
    da=np.array(days);rng=np.random.default_rng(20261003);ix=rng.integers(0,len(days),size=(2500,len(days)));sim=da[ix].sum(axis=1);boot=sim[:,0]/sim[:,1]-1
    for m in sorted(set(r['date'][:7] for r in rows)):
        rr=[r for r in rows if r['date'].startswith(m)];monthly[m]=dict(races=len(rr),roi=sum(r['return_units'] for r in rr)/sum(r['stake_units'] for r in rr)-1)
    pnl=np.array([r['return_units']-r['stake_units'] for r in sorted(rows,key=lambda r:(r['date'],r['race_no']))]);curve=np.r_[0,np.cumsum(pnl)];dd=float((np.maximum.accumulate(curve)-curve).max());streak=longest=0
    for x in pnl:
        streak=streak+1 if x<0 else 0;longest=max(longest,streak)
    win_gross=sum(r['winning_return_units'] for r in rows);win_ticket_count=sum(len(r['winning_tickets']) for r in rows)
    return dict(races=n,hits=hits,hit_rate=hits/n,profitable_races=profit,profit_race_rate=profit/n,nonloss_rate=sum(r['nonloss'] for r in rows)/n,stake_units=stake,return_units=gross,roi=gross/stake-1,roi_day_cluster95=[float(x) for x in np.quantile(boot,[.025,.975])],mean_winning_ticket_dividend=win_gross/win_ticket_count if win_ticket_count else None,winning_ticket_count=win_ticket_count,refund_tickets=sum(len(r['refund_tickets']) for r in rows),model_union_probability_mean=float(np.mean([r['model_union_probability'] for r in rows])),max_drawdown_units=dd,longest_loss_streak=longest,roi_without_largest_winning_race=(gross-max(r['winning_return_units'] for r in rows))/stake-1,monthly=monthly)


def render(s):
    p=['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>2026 승식별 비교</title><style>body{font:15px/1.7 system-ui,sans-serif;color:#16273b;background:#f4f7fb;margin:0}main{max-width:1100px;margin:auto;padding:28px}section{background:white;padding:20px;border-radius:12px;margin:18px 0}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:9px;border-bottom:1px solid #ddd;text-align:right}td:first-child,th:first-child{text-align:left}th{background:#edf3fa}.note{color:#5b6675}h1{font-size:28px}h2{font-size:20px}</style><main><h1>2026년 승식별 모델 비교</h1><p>제주 510경주(1/2~9/12), 부산 525경주(1/2~9/11). 이전 삼복 분석과 같은 경주. 기존 가중치·보정값을 유지했으며 새 승식 전용 학습이나 운영 변경은 없습니다.</p><p>연승·복연승·복승·쌍승은 하나의 공동 착순 분포에서 사건확률을 합산한 기준선입니다. 제주 HY_R_FORM, 부산 A의 반기별 시계열 모델과 저장 우승 순서 모델을 사용합니다. 결과·배당을 보고 조합을 선택하지 않았으며 확정 배당은 정산에만 사용했습니다.</p><p class="note">연승은 보존된 편성 7두 이하에서 2착까지, 8두 이상에서 3착까지. 출전취소·제외 포함 마권은 1단위 반환, 주행중지는 실패로 정산합니다. 복연승 등 여러 적중이 가능한 승식은 모든 적중 마권의 수령액을 더하고 적중 경주율은 한 번만 셉니다. 고배당을 제거하지 않은 실정산과 최대 적중 수령액 제외 민감도를 함께 표시합니다. 이미 반복 검토한 기간의 후향 분석입니다.</p>']
    display=['PLC_joint_top1','QPL_joint_top1','QNL_joint_top1','EXA_joint_top1','WIN_joint_top1','PLC_joint_top3','QPL_joint_top3','QNL_joint_top3','EXA_joint_top3','QPL_joint_top6','QNL_joint_top6','EXA_joint_top6','TLA_B_top6_reference','PLC_A_rank1','QPL_A_rank12','QNL_A_rank12','EXA_A_rank1to2','QPL_A_axis3','QNL_A_axis3','EXA_A_axis3']
    for v in ('제주','부산','합산'):
        p.append('<section><h2>'+v+'</h2><div class="scroll"><table><tr><th>승식·규칙</th><th>조합 수</th><th>적중 경주율</th><th>수익 경주율</th><th>순수익률</th><th>95% 경기일 구간</th><th>적중 마권 평균 배당</th><th>최대 수령 제외 ROI</th></tr>')
        for name in display:
            q=s['strategies'][v][name];n=int(round(q['stake_units']/q['races']));pool=name.split('_')[0]
            desc=LABELS[pool]+' '+({'joint':'공동 확률순','A':'입상순위','B':'기존 삼복'}[name.split('_')[1]])+' '+name.split('_',2)[2]
            cells=[desc,str(n),f"{q['hit_rate']:.1%} ({q['hits']})",f"{q['profit_race_rate']:.1%}",f"{q['roi']:+.1%}",f"{q['roi_day_cluster95'][0]:+.1%} ~ {q['roi_day_cluster95'][1]:+.1%}",f"{q['mean_winning_ticket_dividend']:.2f}배",f"{q['roi_without_largest_winning_race']:+.1%}"]
            p.append('<tr>'+''.join('<td>'+html.escape(x)+'</td>' for x in cells)+'</tr>')
        p.append('</table></div></section>')
    p.append('<p>이전 부산 삼복 수익률 -32.6%는 출전취소 82단위 반환을 누락한 수치였습니다. 같은 추천 조합에 반환을 반영한 값은 -30.0%입니다. 기존 예측·평가 파일은 덮어쓰지 않았습니다.</p><p><a href="summary.json">상세 JSON</a> · <a href="race_strategy_evaluation.csv">경주별 정산 CSV</a> · <a href="https://park.kra.co.kr/race_guide_.pdf">마사회 승식 안내</a></p></main></html>')
    (OUT/'report.html').write_text(''.join(p),encoding='utf-8')


def main():
    cohort=list(csv.DictReader(COHORT.open(encoding='utf-8-sig')));assert len(cohort)==1035
    d=distributions(cohort);rows=evaluate(cohort,d)
    names=sorted(set(r['strategy'] for r in rows));summary={};threshold={}
    for v in ('제주','부산','합산'):
        rr=[r for r in rows if v=='합산' or r['venue']==v]
        summary[v]={name:summarize([r for r in rr if r['strategy']==name]) for name in names}
        threshold[v]={pool:{str(t):summarize([r for r in rr if r['strategy']==pool+'_joint_top1' and r['model_union_probability']>=t]) for t in ([.6,.7,.8] if pool=='PLC' else [.3,.4,.5]) if any(r['strategy']==pool+'_joint_top1' and r['model_union_probability']>=t for r in rr)} for pool in ('PLC','QPL')}
    model_meta={domain:json.loads(Path('/tmp/horse_pool_model_'+domain+'.json').read_text()) for domain in ('jeju','thoroughbred')}
    s=dict(strategies=summary,confidence_subsets=threshold,checks=CHECKS,models=model_meta,cohort='Same 1035 cleaned 2026 races as prior analysis; 510 Jeju and 525 Busan',probability_contract='Derive each requested pool from ONE coherent A joint for Busan or HY_R_FORM for Jeju. Never multiply marginals or mix B/C calibrations. Historical A half-year bundles used on corresponding half.',methodology='Retrospective baseline; no training, no promotion, no closing odds selection; one unit per ticket; refund scratched entries; all winning-ticket payouts count; hit rate is any win in a race.',sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(SOURCE_PATHS))})
    (OUT/'summary.json').write_text(json.dumps(s,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    with (OUT/'race_strategy_evaluation.csv').open('w',encoding='utf-8-sig',newline='') as h:
        w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader()
        for r in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,list) else v for k,v in r.items()})
    render(s)
    print('VERIFIED',json.dumps(CHECKS,ensure_ascii=False))
    for v in ('제주','부산','합산'):
        print(v)
        for name in names:
            q=summary[v][name];print(name,q['races'],q['hits'],round(100*q['hit_rate'],2),round(100*q['profit_race_rate'],2),round(100*q['roi'],2),round(q['mean_winning_ticket_dividend'],2),q['refund_tickets'])


if __name__=='__main__':main()
