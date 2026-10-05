"""Read-only retrospective evaluation of registered model designs on 2026 races.

No fitting, parameter selection, model promotion, or database writes. Six tickets
are selected from pre-outcome model probabilities; final TLA odds settle only.
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import re
import sqlite3
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "data/research/thoroughbred_three_targets_20260918_v3/code"))
import targets_core as tc
from horse_racing.analysis.jeju_hybrid_evaluation import distribution

V6 = ROOT / "data/research/thoroughbred_boundary_20260918_v6"
JEJU = ROOT / "data/research/jeju_native_transition_holdout_v13_20260916"
JD = ROOT / "data/research/jeju_native_top3_dataset_v1_20260915_r2"
SOURCES = []
CHECKS = {}


def read(p):
    SOURCES.append(str(p.relative_to(ROOT)))
    return pl.read_parquet(p)


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def key(numbers):
    return "-".join(str(int(x)) for x in sorted(numbers))


def grade_number(s):
    m = re.search(r"([1-6])", str(s))
    return int(m.group(1)) if m else None


def wilson(h, n):
    if not n:
        return [None, None]
    p = h / n
    z = 1.959963984540054
    den = 1 + z*z/n
    center = (p + z*z/(2*n)) / den
    half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / den
    return [center-half, center+half]


def make_row(venue, rid, date, no, grade, numbers, ids, starts, a, sets, probs, winning_indices):
    assert len(numbers) >= 5 and len(numbers) == len(set(numbers)) == len(ids)
    assert np.isfinite(a).all() and abs(float(np.sum(a))-3) < 1e-9
    assert abs(float(probs.sum())-1) < 1e-9
    rank = sorted(range(len(ids)), key=lambda i: (-float(a[i]), str(ids[i])))
    order = sorted(range(len(sets)), key=lambda i: (-float(probs[i]), tuple(sorted(str(ids[j]) for j in sets[i]))))
    winners = {tuple(sorted(int(j) for j in t)) for t in winning_indices}
    assert winners
    actual_keys = [key(numbers[j] for j in t) for t in sorted(winners)]
    tickets = [key(numbers[j] for j in sets[i]) for i in order[:6]]
    axis_tickets = [key([numbers[rank[0]], numbers[x], numbers[y]]) for x,y in combinations(rank[1:5], 2)]
    assert len(tickets) == len(set(tickets)) == len(axis_tickets) == 6
    top3 = tuple(sorted(rank[:3]))
    top5 = set(rank[:5])
    return dict(
        venue=venue, source_race_id=str(rid), date=date, race_no=int(no), grade=grade,
        grade_number=grade_number(grade), field_size=len(numbers),
        n_debut=sum(x == 0 for x in starts), n_lt3=sum(x < 3 for x in starts),
        n_lt5=sum(x < 5 for x in starts), min_prior_starts=int(min(starts)),
        mean_prior_starts=float(np.mean(starts)),
        top1_in3=any(rank[0] in t for t in winners), top3_hit=top3 in winners,
        top5_cover=any(set(t).issubset(top5) for t in winners),
        b_first_hit=tuple(sorted(sets[order[0]].tolist())) in winners,
        b6_hit=any(tuple(sorted(sets[i].tolist())) in winners for i in order[:6]),
        axis6_hit=bool(set(axis_tickets)&set(actual_keys)),
        b6_model_probability=float(probs[order[:6]].sum()),
        top5_model_probability=float(sum(p for s,p in zip(sets,probs) if set(s).issubset(top5))),
        top3_numbers=[int(numbers[i]) for i in rank[:3]],
        top5_numbers=[int(numbers[i]) for i in rank[:5]], b6_tickets=tickets,
        axis6_tickets=axis_tickets, actual_keys=actual_keys,
    )


def jeju_rows():
    f = read(JEJU / "horse_predictions.parquet").filter(pl.col("model") == "HY_R_FORM")
    states = read(JD / "horse_states.parquet").select("entry_id", "starts_pre")
    labels = read(JD / "labels.parquet").select("entry_id", "horse_number", "finish_position_target")
    f = f.join(states, on="entry_id", validate="1:1").join(labels, on="entry_id", validate="1:1")
    c = ro(ROOT / "data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3")
    events = {r["id"]: dict(r) for r in c.execute("SELECT id,event_date,event_number,grade FROM event WHERE event_date BETWEEN ? AND ?", ("20260101", "20260912"))}
    c.close()
    saved = {r["race_id"]: r for r in read(JEJU / "race_predictions.parquet").filter(pl.col("model")=="HY_R_FORM").to_dicts()}
    rows = []
    max_error = 0.0
    for (rid,), part in f.group_by("race_id"):
        part = part.sort("horse_id")
        sets, _, ls, _, a = distribution(part["score"].to_numpy(), part["order_score"].to_numpy(), float(part["beta"][0]), float(part["beta_order"][0]))
        max_error = max(max_error, float(np.max(abs(a - part["pl_place_probability"].to_numpy()))))
        truth = tc.build_target_truth(part["finish_position_target"].to_list())
        assert not truth.boundary_tie
        event = events[rid]
        row = make_row("제주", rid, str(part["event_date"][0]), event["event_number"], event["grade"],
                       part["horse_number"].to_list(), part["horse_id"].to_list(), part["starts_pre"].to_list(), a, sets, np.exp(ls), truth.compatible_sets)
        assert row["b_first_hit"] == saved[rid]["set_hit"]
        rows.append(row)
    assert len(rows) == 510 and sum(r["b_first_hit"] for r in rows) == 32
    assert max_error < 1e-10
    CHECKS["jeju"] = dict(races=len(rows), stored_marginal_max_error=max_error, saved_set_hits_reproduced=32)
    return rows


def busan_rows():
    a = read(V6 / "A_horse_predictions.parquet").filter((pl.col("candidate")=="current_A") & (pl.col("venue_code")=="BUSAN") & (pl.col("race_date").dt.year()==2026))
    f = read(ROOT / "data/research/thoroughbred_three_targets_20260918_v3/prepared_context.parquet").filter((pl.col("venue_code")=="BUSAN") & (pl.col("race_date").dt.year()==2026) & (pl.col("race_date") <= pl.date(2026,9,13)))
    v4 = read(ROOT / "data/research/thoroughbred_followup_20260918_v4/model/strict_features.parquet")
    f = f.with_columns(pl.col("race_date").cast(pl.Datetime("us"))).join(v4, on=["race_id","hr_no","race_date"], validate="1:1")
    f = f.sort("race_date","race_id","chul_no","hr_no")
    top = tc.load_bundle(ROOT / "data/research/thoroughbred_followup_20260918_v4/model/models/2026/top3_growth_strength")
    bt = top.metadata["temperature_by_target_and_venue"]["B"]["BUSAN"]
    bscore = tc.raw_scores(top, f.to_pandas())["top3"]
    f = f.with_columns(pl.Series("bscore", bscore))
    amap = {rid: p for (rid,),p in a.group_by("race_id")}
    topk = read(V6 / "B_topk.parquet").filter((pl.col("candidate")=="current_B") & (pl.col("venue_code")=="BUSAN") & (pl.col("race_date").dt.year()==2026))
    checks = {(r["race_id"],r["top_k"]): r for r in topk.to_dicts()}
    rows = []
    max_error = 0.0
    excluded = []
    all_b = []
    for (rid,), part in f.group_by("race_id"):
        ids = part["hr_no"].to_list()
        sets, _, _, _ = tc._templates(len(ids))
        energy = part["bscore"].to_numpy()[sets].sum(axis=1)/bt
        probs = np.exp(energy-energy.max()); probs /= probs.sum()
        truth = tc.build_target_truth(part["target_finish_order"].to_list())
        order = np.argsort(-probs, kind="stable")
        winners = {tuple(t) for t in truth.compatible_sets.tolist()}
        for k in (1,3,5,10):
            chk = checks[(rid,k)]
            hit = any(tuple(sets[i]) in winners for i in order[:k])
            assert hit == chk["hit"]
            max_error = max(max_error, abs(float(probs[order[:k]].sum())-chk["probability_mass"]))
        all_b.append(dict(race_id=rid, boundary_tie=truth.boundary_tie, b6_hit=any(tuple(sets[i]) in winners for i in order[:6])))
        if rid not in amap:
            assert truth.boundary_tie
            excluded.append(rid)
            continue
        assert not truth.boundary_tie
        ap = {r["hr_no"]:r for r in amap[rid].to_dicts()}
        assert set(ids)==set(ap)
        marginals = np.array([ap[h]["probability"] for h in ids])
        assert np.array_equal(truth.a_target, np.array([ap[h]["label"] for h in ids]))
        date = str(part["race_date"][0].date())
        row = make_row("부산", rid, date, part["race_no"][0], part["race_class"][0], part["chul_no"].to_list(), ids, part["hist_prior_starts_all"].to_list(), marginals, sets, probs, truth.compatible_sets)
        rows.append(row)
    assert len(rows)==527 and len(excluded)==3 and len(all_b)==530 and max_error<1e-10
    CHECKS["busan"] = dict(common_races=527, all_b_races=530, all_b6_hits=sum(r["b6_hit"] for r in all_b), excluded_boundary_ties=excluded, saved_topk_max_error=max_error, A_contract="rolling_all chronological half-year bundles, not reapplying H2 calibration to H1")
    return rows


def settle(rows):
    c = ro(ROOT / "data/horse_racing.sqlite3")
    lookup = {(r["kra_meet_code"],r["race_date_local"],r["race_number"]):r["id"] for r in c.execute("SELECT r.id,rc.kra_meet_code,r.race_date_local,r.race_number FROM races r JOIN racecourses rc ON rc.id=r.racecourse_id WHERE r.race_date_local BETWEEN ? AND ?",("2026-01-01","2026-09-13"))}
    verified = 0
    missing = []
    for r in rows:
        rid = lookup.get((2 if r["venue"]=="제주" else 3,r["date"],r["race_no"]))
        r["main_db_race_id"] = rid
        r["b6_return_units"] = r["axis6_return_units"] = None
        if rid is None:
            missing.append([r["venue"],r["date"],r["race_no"]]);continue
        results = c.execute("SELECT e.horse_number,rr.finish_position FROM race_entries e JOIN race_results rr ON rr.race_entry_id=e.id WHERE e.race_id=? AND e.scratched=0 AND rr.disqualified=0 AND rr.finish_position BETWEEN 1 AND 3",(rid,)).fetchall()
        actual = key(q["horse_number"] for q in results)
        assert actual in r["actual_keys"], (r,actual)
        verified += 1
        odds = {}
        for q in c.execute("SELECT selection_key,odds FROM odds_snapshots WHERE race_id=? AND bet_type=? ORDER BY observed_at_ms",(rid,"TLA")):
            if q["selection_key"] in r["actual_keys"] and q["odds"] is not None and 1<=float(q["odds"])<9999.9:
                odds[q["selection_key"]]=float(q["odds"])
        if set(odds) != set(r["actual_keys"]):
            missing.append([r["venue"],r["date"],r["race_no"]]);continue
        r["winning_dividend"] = float(np.mean(list(odds.values())))
        r["b6_return_units"] = sum(v for k,v in odds.items() if k in r["b6_tickets"])
        r["axis6_return_units"] = sum(v for k,v in odds.items() if k in r["axis6_tickets"])
    c.close()
    CHECKS["settlement"] = dict(main_db_actual_results_verified=verified,missing=missing)
    assert verified == len(rows) and not missing


def summarize(rows):
    n = len(rows)
    if not n:
        return {"races":0}
    d = dict(races=n, start=min(r["date"] for r in rows), end=max(r["date"] for r in rows), mean_field_size=float(np.mean([r["field_size"] for r in rows])))
    for metric in ("top1_in3","top3_hit","top5_cover","b_first_hit","b6_hit","axis6_hit"):
        h = sum(r[metric] for r in rows)
        d[metric] = dict(hits=h, rate=h/n, wilson95=wilson(h,n))
    d["mean_b6_model_probability"] = float(np.mean([r["b6_model_probability"] for r in rows]))
    payout = [r for r in rows if r["b6_return_units"] is not None]
    if payout:
        gross = sum(r["b6_return_units"] for r in payout)
        hits = sum(r["b6_return_units"]>0 for r in payout)
        d["b6_settlement"] = dict(races=len(payout),hits=hits,stake_units=6*len(payout),return_units=gross,net_roi=gross/(6*len(payout))-1,mean_hit_dividend=gross/hits if hits else None,largest_payout=max(r["b6_return_units"] for r in payout),net_roi_without_largest_payout=(gross-max(r["b6_return_units"] for r in payout))/(6*len(payout))-1)
    return d


FILTERS = {
    "all": lambda r: True,
    "any_debut": lambda r: r["n_debut"]>0,
    "no_debut": lambda r: r["n_debut"]==0,
    "any_lt3": lambda r: r["n_lt3"]>0,
    "all_ge3": lambda r: r["n_lt3"]==0,
    "all_ge5": lambda r: r["n_lt5"]==0,
    "grade6": lambda r: r["grade_number"]==6,
    "grade5": lambda r: r["grade_number"]==5,
    "grade4": lambda r: r["grade_number"]==4,
    "grade1to3": lambda r: r["grade_number"] in (1,2,3),
    "grade1to4": lambda r: r["grade_number"] in (1,2,3,4),
    "grade1to5": lambda r: r["grade_number"] in (1,2,3,4,5),
    "open": lambda r: r["grade_number"] is None,
    "grade1to5_allge3": lambda r: r["grade_number"] in (1,2,3,4,5) and r["n_lt3"]==0,
    "grade1to4_allge3": lambda r: r["grade_number"] in (1,2,3,4) and r["n_lt3"]==0,
    "grade5_allge3": lambda r: r["grade_number"]==5 and r["n_lt3"]==0,
    "grade5_allge5": lambda r: r["grade_number"]==5 and r["n_lt5"]==0,
    "grade6_debut": lambda r: r["grade_number"]==6 and r["n_debut"]>0,
    "grade6_no_debut": lambda r: r["grade_number"]==6 and r["n_debut"]==0,
}


def day_bootstrap(rows):
    """Race-day cluster intervals, preserving correlated races on a date."""
    days = sorted(set(r["date"] for r in rows))
    rng = np.random.default_rng(20261003)
    draw = rng.integers(0,len(days),size=(4000,len(days)))
    totals = np.array([sum(r["date"]==d for r in rows) for d in days])
    out = {}
    for metric in ("top3_hit","top5_cover","b6_hit"):
        counts = np.array([sum(r["date"]==d and r[metric] for r in rows) for d in days])
        rates = counts[draw].sum(axis=1)/totals[draw].sum(axis=1)
        out[metric] = [float(x) for x in np.quantile(rates,[.025,.975])]
    for label,predicate in [("no_debut_minus_debut",lambda r:r["n_debut"]==0),("allge3_minus_anylt3",lambda r:r["n_lt3"]==0)]:
        y0 = np.array([sum(r["date"]==d and not predicate(r) and r["b6_hit"] for r in rows) for d in days])
        n0 = np.array([sum(r["date"]==d and not predicate(r) for r in rows) for d in days])
        y1 = np.array([sum(r["date"]==d and predicate(r) and r["b6_hit"] for r in rows) for d in days])
        n1 = np.array([sum(r["date"]==d and predicate(r) for r in rows) for d in days])
        den0,den1 = n0[draw].sum(axis=1),n1[draw].sum(axis=1)
        ok=(den0>0)&(den1>0)
        delta=y1[draw].sum(axis=1)[ok]/den1[ok]-y0[draw].sum(axis=1)[ok]/den0[ok]
        out[label] = dict(delta=float(y1.sum()/n1.sum()-y0.sum()/n0.sum()),cluster95=[float(x) for x in np.quantile(delta,[.025,.975])])
    return out


def render(summary):
    labels={"all":"전체","any_debut":"0전 말 포함","no_debut":"0전 말 없음","any_lt3":"0~2전 말 포함","all_ge3":"전원 3전 이상","all_ge5":"전원 5전 이상","grade6":"6등급","grade5":"5등급","grade4":"4등급","grade1to3":"1~3등급","grade1to4":"1~4등급","grade1to5":"1~5등급","open":"OPEN","grade1to5_allge3":"1~5등급·전원 3전 이상","grade1to4_allge3":"1~4등급·전원 3전 이상","grade5_allge3":"5등급·전원 3전 이상","grade5_allge5":"5등급·전원 5전 이상","grade6_debut":"6등급·0전 포함","grade6_no_debut":"6등급·0전 없음"}
    parts=['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>2026 삼복 모델 적중률</title><style>body{font:15px/1.7 system-ui,sans-serif;color:#142538;background:#f4f7fb;margin:0}main{max-width:1100px;margin:auto;padding:28px}section{background:white;padding:20px;border-radius:12px;margin:20px 0}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:right;border-bottom:1px solid #ddd;padding:9px}th:first-child,td:first-child{text-align:left}th{background:#edf2f9}.scroll{overflow:auto}.note{color:#596579}h1{font-size:28px}h2{font-size:21px}</style><main><h1>2026년 삼복 모델 적중률 분석</h1><p>제주 HY_R_FORM, 부산 current_A/current_B의 저장된 시계열 평가 자료. 제주 2026-01-02~09-12 510경주, 부산 2026-01-02~09-11 525경주. 부산 실제 입상 경계 동착 2경주 및 실제 경마일이 아닌 2026-07-06의 저장 예측 3경주를 제외. 기존 자료의 입력 피처는 재작성하지 않았습니다.</p><p>상위 3두 = 말별 입상확률 상위 3두와 실제 입상 3두의 일치. 상위 5두 = 실제 입상 3두가 추천 5두 안에 모두 포함. 6조합 = 전체 삼복 조합 중 모델 조합확률 상위 6개. 축 고정 6개 = 말별 1순위 고정 + 2~5순위 중 2두 선택.</p><p class="note">0전은 예측 전 국내 실전 이력 0전이며 외국 경력·누락 이력의 가능성을 배제하는 공식 데뷔 판정은 아니다. 제주 이력은 T−2, 부산은 저장된 사전 이력 계약을 사용했다. 이미 여러 연구에서 확인한 2026년 자료의 후향 분석이며 미래 적중률 보장이 아니다. 등급·두수·거리 차이가 섞인 집단 비교다. 적중률 계산에서는 고배당 경주를 제거하지 않았다.</p>']
    for v in ("제주","부산","합산"):
        parts.append('<section><h2>'+v+'</h2><div class="scroll"><table><tr><th>편성</th><th>경주</th><th>평균 두수</th><th>3두 일치</th><th>5두 포함</th><th>확률순 6조합</th><th>축 고정 6조합</th></tr>')
        for k,s in summary["groups"][v].items():
            if not s['races']: continue
            cells=[labels[k],str(s['races']),f"{s['mean_field_size']:.1f}"]
            for m in ('top3_hit','top5_cover','b6_hit','axis6_hit'):
                cells.append(f"{s[m]['rate']:.1%} ({s[m]['hits']}/{s['races']})")
            parts.append('<tr>'+''.join('<td>'+html.escape(x)+'</td>' for x in cells)+'</tr>')
        parts.append('</table></div>')
        p=summary['groups'][v]['all']['b6_settlement']
        parts.append(f"<p>6조합 동일 금액 가정: 적중 평균 배당 {p['mean_hit_dividend']:.1f}배, 순수익률 {p['net_roi']:.1%}. 최고 적중 배당 {p['largest_payout']:.1f}배를 수령액에서 빼면 {p['net_roi_without_largest_payout']:.1%}. 확정 배당은 정산에만 사용했고 조합 선택에는 사용하지 않았다.</p></section>")
    total=summary['groups']['합산']['all']
    parts.append(f"<section><h2>해석</h2><p>전체 6조합 적중률은 {total['b6_hit']['rate']:.1%}지만 적중 평균 배당은 {total['b6_settlement']['mean_hit_dividend']:.1f}배입니다. 이 배당에서 동일 금액 6조합의 손익분기 적중률은 {6/total['b6_settlement']['mean_hit_dividend']:.1%}입니다. 전체 경주의 평균 배당을 모델이 적중한 경주의 평균 배당으로 대입하면 수익성을 과대평가합니다.</p><p>현재 자료에서는 신마 제외·전원 다전마·5등급 이상 선별만으로 6조합 적중률이 높아진다는 근거가 없습니다. 집단별 표본 수와 출전두수가 다르고, 신마 여부와 등급은 강하게 겹치므로 인과효과로 해석하지 않습니다.</p><p>6조합 합산 예측확률 40% 이상 편성의 실제 적중은 제주 76/164(46.3%), 부산 44/111(39.6%)였지만 동일 금액 순수익률은 각각 -13.7%, -37.0%입니다. 같은 자료에서 사후 확인한 구간이므로 검증된 실전 선별 규칙으로 간주하지 않습니다.</p></section>")
    parts.append('<p class="note">상위 5두를 전부 삼복으로 묶으면 10조합이다. 6조합에 5두 포함률을 그대로 적용할 수 없다. 부산의 말별 A와 조합 B는 다른 모델이므로 B의 6조합에 A 상위 5두 밖의 말도 들어갈 수 있다.</p><p><a href="summary.json">상세 수치 JSON</a> · <a href="race_evaluation.csv">경주별 평가 CSV</a></p></main></html>')
    (OUT/'report.html').write_text(''.join(parts),encoding='utf-8')


def main():
    rows=jeju_rows()+busan_rows()
    # Old saved studies preceded the September 25 removal of synthetic API races.
    # CURRENT_STATUS.md documents that July 6/7 were not racing days; preserve
    # saved predictions for replay checks but exclude these targets from results.
    ghost=[r for r in rows if r['venue']=='부산' and r['date']=='2026-07-06']
    assert len(ghost)==2
    rows=[r for r in rows if not (r['venue']=='부산' and r['date']=='2026-07-06')]
    CHECKS['known_nonrace_exclusion']=dict(source='docs/CURRENT_STATUS.md:142',date='2026-07-06',all_saved_B_races_removed=3,common_A_B_rows_removed=2,final_busan_common_races=525,note='Historical feature snapshots remain frozen; this is target-cohort cleaning, not an input rebuild.')
    settle(rows)
    rows.sort(key=lambda r:(r['date'],r['venue'],r['race_no']))
    groups={};uncertainty={};confidence={};fieldsize={}
    for venue in ('제주','부산','합산'):
        cohort=[r for r in rows if venue=='합산' or r['venue']==venue]
        groups[venue]={k:summarize([r for r in cohort if predicate(r)]) for k,predicate in FILTERS.items()}
        uncertainty[venue]=day_bootstrap(cohort)
        confidence[venue]={str(t):summarize([r for r in cohort if r['b6_model_probability']>=t]) for t in (.2,.3,.4,.5)}
        fieldsize[venue]={str(n):summarize([r for r in cohort if r['field_size']==n]) for n in sorted(set(r['field_size'] for r in cohort))}
    SOURCES.extend(['config/prediction_model_registry.json','docs/CURRENT_STATUS.md','data/research/jeju_native_transition_holdout_v13_20260916/split_dates.json','data/research/thoroughbred_boundary_20260918_v6/PROTOCOL.md','data/research/thoroughbred_followup_20260918_v4/model/models/2026/top3_growth_strength/top3.txt','data/research/thoroughbred_followup_20260918_v4/model/models/2026/top3_growth_strength/metadata.json'])
    summary=dict(groups=groups,day_cluster_uncertainty=uncertainty,confidence_groups=confidence,field_size_groups=fieldsize,checks=CHECKS,methodology=dict(period='2026-01-02 to saved evaluation cutoff, not October 2 cumulative',unit='one race, common evaluable cohort',top3='A marginal top3 set equals actual unordered podium',top5='actual podium subset of A marginal top5; full box costs 10 tickets',six='B highest-probability six unordered combinations across all starters',axis6='A rank1 fixed, choose two from A ranks2-5',newcomer='zero observed prior domestic race starts before feature cutoff',experience='ALL starters >=3 or >=5 observed prior starts',evaluation='retrospective, repeatedly inspected research period; not untouched prospective holdout',settlement='6 equal units per race, final TLA dividends only for settlement; no extreme race exclusion'),sources={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sorted(set(SOURCES))})
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    with (OUT/'race_evaluation.csv').open('w',encoding='utf-8-sig',newline='') as h:
        writer=csv.DictWriter(h,fieldnames=list(rows[0]));writer.writeheader()
        for r in rows:writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,list) else v for k,v in r.items()})
    render(summary)
    print(json.dumps({v:{k:s for k,s in groups[v].items() if k in ('all','any_debut','no_debut','all_ge3','all_ge5','grade6','grade5','grade4','grade1to3')} for v in ('제주','부산')},ensure_ascii=False,indent=2))
    print('CHECKS',json.dumps(CHECKS,ensure_ascii=False))


if __name__=='__main__':
    main()
