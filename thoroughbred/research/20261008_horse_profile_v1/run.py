"""Chronological horse profiles and descriptive correction diagnostics; no training."""
from pathlib import Path
import hashlib
import html
import importlib.util
import json

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'outputs'
RESEARCH = HERE.parent
DB = ROOT / 'thoroughbred/data/core_api_2010_20260929_v1/thoroughbred_core.duckdb'
BASE_PATH = RESEARCH / '20261003_baseline_v1/run.py'
MOIST = RESEARCH / '20261003_pace_gate_moisture_v2/outputs'
RAW = RESEARCH / '20261004_outsider_joint_v1/outputs/features.parquet'
PRED = RESEARCH / '20261006_moisture_no_jockey_v1/outputs/runner_predictions.parquet'
GATE = RESEARCH / '20261008_gate_model_candidate_v1/outputs/runner_trial_normalization.parquet'
KEY = ['race_key', 'program_no', 'horse_id']
METRICS = ['last', 'mean3', 'best5', 'top2mean5', 'previous3', 'trend', 'std5']

def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')

def module():
    spec = importlib.util.spec_from_file_location('horse_profile_source', BASE_PATH)
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    return base

def load_records():
    base = module()
    rows, _ = base.read_source(DB)
    raw, _, _ = base.prepare_records(rows)
    adjusted = pd.read_parquet(MOIST / 'adjusted_records.parquet')
    selected = KEY + ['finish_valid', 'record_index', 'supported', 'correction_seconds']
    adjusted = adjusted[selected].rename(columns={'finish_valid': 'moist_finish', 'record_index': 'q_moist'})
    raw = raw.rename(columns={'record_index': 'q_raw', 'finish_valid': 'raw_finish'})
    records = raw.merge(adjusted, on=KEY, validate='one_to_one')
    assert len(records) == len(raw)
    assert not records.duplicated(['horse_id','race_date']).any(), 'Ambiguous same-day history'
    effects = pd.read_parquet(MOIST / 'effects.parquet')
    records = records.merge(effects[['race_key', 'band', 'environment_trained_through']], on='race_key', validate='many_to_one')
    ref = pd.read_csv(MOIST / 'record_references.csv')
    records = records.merge(ref[['meet', 'result_distance', 'source_year', 'scale', 'trained_through']],
                            left_on=['meet', 'result_distance', 'year'],
                            right_on=['meet', 'result_distance', 'source_year'], how='left', validate='many_to_one')
    assert np.allclose(records.raw_finish + records.correction_seconds, records.moist_finish, equal_nan=True)
    return records.sort_values(['horse_id', 'race_date']).reset_index(drop=True)

def load_targets():
    keys = pd.read_parquet(PRED, columns=KEY + ['variant'])
    keys = keys.loc[keys.variant.eq('no_jockey'), KEY]
    f = pd.read_parquet(RAW, columns=KEY + ['meet', 'race_date', 'race_no', 'distance_m', 'grade_raw', 'horse_name'])
    targets = keys.merge(f, on=KEY, validate='one_to_one')
    assert len(targets) == 50754 and targets.race_key.nunique() == 4799
    return targets.sort_values(['race_date', 'meet', 'race_no', 'program_no']).reset_index(drop=True)

def metrics(q):
    a, b, c = q[:3], q[:5], q[3:6]
    va, vb, vc = a[np.isfinite(a)], b[np.isfinite(b)], c[np.isfinite(c)]
    mean = float(va.mean()) if len(va) else np.nan
    previous = float(vc.mean()) if len(vc) else np.nan
    return dict(last=float(q[0]) if len(q) else np.nan, mean3=mean,
                best5=float(vb.max()) if len(vb) else np.nan,
                top2mean5=float(np.sort(vb)[-2:].mean()) if len(vb) >= 2 else np.nan,
                previous3=previous,
                trend=mean-previous if len(va) >= 2 and len(vc) >= 2 else np.nan,
                std5=float(vb.std(ddof=1)) if len(vb) >= 3 else np.nan,
                count3=len(va), count5=len(vb), previous3_count=len(vc))

def history_map(records):
    cols = ['race_date', 'race_key', 'program_no', 'meet', 'result_distance', 'grade_raw',
            'q_raw', 'q_moist', 'raw_finish', 'moist_finish', 'supported', 'correction_seconds',
            'age', 'sex', 'body_weight', 'carried_weight', 'outcome', 'scale']
    return {horse: {c: g[c].to_numpy() for c in cols} for horse, g in records.groupby('horse_id', sort=False)}

def build_profiles(targets, records):
    histories = history_map(records)
    output = []
    for row in targets.to_dict('records'):
        h = histories.get(row['horse_id'])
        cutoff = row['race_date'] - pd.Timedelta(days=2)
        end = int(np.searchsorted(h['race_date'], cutoff.to_datetime64(), side='right')) if h else 0
        ids = np.arange(end - 1, max(-1, end - 11), -1)
        record = {**row, 'cutoff_date': cutoff, 'history_count': end, 'window_start_count': len(ids),
                  'history_source_date': pd.Timestamp(h['race_date'][end-1]) if end else pd.NaT,
                  'profile_version': 'horse_profile_v1_20261008'}
        for variant in ['raw', 'moist']:
            q = h['q_' + variant][ids].astype(float) if end else np.array([])
            record.update({variant + '_' + k: v for k, v in metrics(q).items()})
            valid = np.flatnonzero(np.isfinite(q[:5]))
            best = int(valid[np.argmax(q[valid])]) if len(valid) else None
            for field in ['race_date', 'race_key', 'result_distance', 'grade_raw', 'supported']:
                record[variant + '_best_' + field] = h[field][ids[best]] if best is not None else None
        valid5 = np.isfinite(h['q_moist'][ids[:5]]) if end else np.array([], bool)
        sup5 = h['supported'][ids[:5]].astype(bool) & valid5 if end else np.array([], bool)
        record.update(valid5_supported_count=int(sup5.sum()),
                      valid5_support_fraction=float(sup5.sum()/valid5.sum()) if valid5.sum() else np.nan,
                      mixed_venue_last10=bool(end and len(np.unique(h['meet'][ids])) > 1),
                      mixed_distance_last10=bool(end and len(np.unique(h['result_distance'][ids])) > 1))
        for field in ['age', 'sex', 'body_weight', 'carried_weight', 'result_distance', 'outcome']:
            record['previous_' + field] = h[field][end-1] if end else None
        for field in ['body_weight', 'carried_weight']:
            record[field + '_change'] = h[field][end-1]-h[field][end-2] if end >= 2 else np.nan
        record['days_since_last'] = (row['race_date']-record['history_source_date']).days if end else np.nan
        record['last_raw_finish'] = h['raw_finish'][end-1] if end else np.nan
        record['last_moist_finish'] = h['moist_finish'][end-1] if end else np.nan
        record['last_correction_seconds'] = h['correction_seconds'][end-1] if end and np.isfinite(h['raw_finish'][end-1]) else np.nan
        record['last_correction_supported'] = bool(end and h['supported'][end-1] and np.isfinite(h['raw_finish'][end-1]))
        record['last_reference_missing'] = bool(end and np.isfinite(h['raw_finish'][end-1]) and not np.isfinite(h['q_moist'][end-1]))
        record['ability_status'] = ('실전 이력 없음' if not end else '유효 기록 없음' if not record['moist_count5']
                                     else '단일 관측' if record['moist_count5'] == 1 else '복수 관측')
        output.append(record)
    return pd.DataFrame(output)

def profile_summary(profiles):
    rows = []
    for meet, g in profiles.groupby('meet'):
        row = dict(meet=int(meet), runners=len(g), races=int(g.race_key.nunique()), horses=int(g.horse_id.nunique()),
                   no_history=int(g.history_count.eq(0).sum()), single_valid5=int(g.moist_count5.eq(1).sum()),
                   no_valid5=int(g.moist_count5.eq(0).sum()), trend_available=int(g.moist_trend.notna().sum()),
                   stability_available=int(g.moist_std5.notna().sum()), supported5_present=int(g.valid5_supported_count.gt(0).sum()))
        for metric in METRICS:
            a, b = g['raw_' + metric], g['moist_' + metric]
            good = a.notna() & b.notna()
            changed = good & ~np.isclose(a, b, equal_nan=True, atol=1e-10, rtol=0)
            row[metric + '_available'] = int(good.sum())
            row[metric + '_changed'] = int(changed.sum())
            row[metric + '_median_abs_change'] = float((b[good]-a[good]).abs().median()) if good.any() else None
        eligible_races = changed_top3 = changed_any_rank = 0
        for _, race in g.groupby('race_key'):
            common = race.dropna(subset=['raw_mean3', 'moist_mean3'])
            if len(common) < 3:
                continue
            eligible_races += 1
            ar = common.sort_values(['raw_mean3','program_no'], ascending=[False,True]).program_no.tolist()
            br = common.sort_values(['moist_mean3','program_no'], ascending=[False,True]).program_no.tolist()
            changed_top3 += set(ar[:3]) != set(br[:3])
            changed_any_rank += ar != br
        row.update(rank_comparable_races=eligible_races, recent_mean_top3_changed=int(changed_top3),
                   recent_mean_order_changed=int(changed_any_rank))
        rows.append(row)
    return rows

def paired_diagnostic(records):
    # Consecutive actual starts; excluded/invalid starts never bridge the pair.
    cols = ['race_date', 'meet', 'result_distance', 'grade_raw', 'raw_finish', 'moist_finish', 'band', 'supported']
    d = records.copy()
    prev = d.groupby('horse_id', sort=False)[cols].shift(1).add_prefix('prev_')
    d = pd.concat([d, prev], axis=1)
    days = (d.race_date-d.prev_race_date).dt.days
    mask = (days.between(3,90) & d.meet.eq(d.prev_meet) & d.result_distance.eq(d.prev_result_distance)
            & d.grade_raw.eq(d.prev_grade_raw) & d.supported & d.prev_supported.fillna(False).astype(bool)
            & d.raw_finish.notna() & d.prev_raw_finish.notna() & d.race_date.ge('2024-01-01'))
    d = d.loc[mask].copy()
    d['raw_delta'] = d.raw_finish-d.prev_raw_finish
    d['moist_delta'] = d.moist_finish-d.prev_moist_finish
    d['changed_band'] = d.band.ne(d.prev_band)
    d['raw_abs'] = d.raw_delta.abs()
    d['moist_abs'] = d.moist_delta.abs()
    d['abs_change'] = d.moist_abs-d.raw_abs
    results = []
    rng = np.random.default_rng(20261008)
    for (meet, changed), g in d.groupby(['meet', 'changed_band']):
        day = g.groupby('race_date').abs_change.agg(['sum','count']).to_numpy()
        estimates=[]
        for _ in range(2000):
            sample=day[rng.integers(len(day),size=len(day))]
            estimates.append(float(sample[:,0].sum()/sample[:,1].sum()))
        ci=np.quantile(estimates,[.025,.975])
        results.append(dict(meet=int(meet),changed_band=bool(changed),pairs=len(g),horses=int(g.horse_id.nunique()),
                            dates=len(day),raw_mean_abs_seconds=float(g.raw_abs.mean()),
                            moist_mean_abs_seconds=float(g.moist_abs.mean()),difference_seconds=float(g.abs_change.mean()),
                            date_bootstrap_95=[float(x) for x in ci],
                            improved_pairs=int(g.moist_abs.lt(g.raw_abs-1e-10).sum()),
                            worsened_pairs=int(g.moist_abs.gt(g.raw_abs+1e-10).sum())))
    keep = ['horse_id','race_key','race_date','meet','result_distance','grade_raw','prev_race_date','band','prev_band',
            'raw_delta','moist_delta','raw_abs','moist_abs','abs_change','changed_band']
    return d[keep], results

def latest_cards(profiles):
    return profiles.loc[profiles.race_date.eq(profiles.groupby('meet').race_date.transform('max'))].copy()

def gate_sensitivity(cards, records):
    gate = pd.read_parquet(GATE)
    # Independent source has hyphenated dates in race_key. Normalize identities, not values.
    gate['race_key'] = gate.race_key.str.replace('-', '', regex=False)
    gate = gate.rename(columns={'horse_number':'program_no'})
    assert not gate.duplicated(KEY).any()
    linked = records.merge(gate[KEY+['gate_add_seconds','gate_status','as_of']],on=KEY,how='left',validate='one_to_one')
    by_horse = {h:g for h,g in linked.groupby('horse_id',sort=False)}
    result=[]
    histories=[]
    for row in cards.to_dict('records'):
        h = by_horse.get(row['horse_id'])
        h = h[h.race_date.le(row['cutoff_date'])].tail(10).iloc[::-1] if h is not None else records.iloc[:0]
        values = h.q_moist.to_numpy(float)
        if len(h):
            delta = h.gate_add_seconds.to_numpy(float)
            known = h.gate_add_seconds.notna().to_numpy() & ~h.gate_status.eq('neutral_unavailable').to_numpy()
            # Missing candidate => zero CHANGE with an explicit coverage count, never observed zero effect.
            delta = np.where(known,delta,0)
            scale=h.scale.to_numpy(float)
        else:
            delta=scale=np.array([]);known=np.array([],bool)
        base={k:row[k] for k in KEY}
        base.update(analysis_as_of='2026-10-08',retrospective_only=True,usable_for_historical_prediction=False,
                    history_gate_lookup_count=int(known.sum()),history_starts=len(h))
        for strength in [0,.5,1]:
            adjusted=np.clip(values-strength*delta/scale,-10,10)
            for metric,value in metrics(adjusted).items():
                base[f'gate_{str(strength).replace(".","p")}_{metric}']=value
        result.append(base)
        for pos, r in enumerate(h.to_dict('records'),1):
            histories.append({**{k:row[k] for k in KEY},'history_position':pos,'history_race_key':r['race_key'],
                              'history_date':r['race_date'],'history_meet':r['meet'],'distance':r['result_distance'],
                              'grade':r['grade_raw'],'outcome':r['outcome'],'raw_finish':r['raw_finish'],
                              'moist_finish':r['moist_finish'],'q_raw':r['q_raw'],'q_moist':r['q_moist'],
                              'correction_seconds':r['correction_seconds'],'supported':r['supported'],
                              'gate_current_candidate_seconds':r['gate_add_seconds'],'gate_status':r['gate_status']})
    return pd.DataFrame(result),pd.DataFrame(histories)

def fmt(x, digits=3):
    if x is None or pd.isna(x):return '—'
    if isinstance(x,(float,np.floating)):return f'{x:.{digits}f}'
    if isinstance(x,(pd.Timestamp,np.datetime64)):return str(pd.Timestamp(x).date())
    return html.escape(str(x))

def render(cards, history, sensitivity, summary, diagnostic):
    sections=[]
    gates=sensitivity.set_index(KEY)
    for (meet,date,race), group in cards.groupby(['meet','race_date','race_no']):
        pieces=[]
        for row in group.sort_values('program_no').to_dict('records'):
            h=history.loc[(history.race_key==row['race_key'])&(history.program_no==row['program_no'])]
            gate=gates.loc[tuple(row[k] for k in KEY)]
            metrics_html='<table><tr><th>항목</th><th>원기록지수</th><th>주로보정지수</th></tr>'
            labels=['직전','최근3전 평균','최근5전 최고','상위2개 평균','이전3전 평균','최근3−이전3','최근5전 편차']
            for metric,label in zip(METRICS,labels):
                metrics_html+=f'<tr><td>{label}</td><td>{fmt(row["raw_"+metric])}</td><td>{fmt(row["moist_"+metric])}</td></tr>'
            metrics_html+='</table>'
            past='<table><tr><th>전</th><th>날짜·지역</th><th>거리·등급</th><th>착순</th><th>원초→보정초</th><th>원지수→보정지수</th><th>보정 지원</th></tr>'
            for r in h.to_dict('records'):
                past+=f'<tr><td>{r["history_position"]}</td><td>{fmt(r["history_date"])} / {fmt(r["history_meet"])}</td><td>{fmt(r["distance"])} / {fmt(r["grade"])}</td><td>{fmt(r["outcome"])}</td><td>{fmt(r["raw_finish"])} → {fmt(r["moist_finish"])}</td><td>{fmt(r["q_raw"])} → {fmt(r["q_moist"])}</td><td>{"지원" if r["supported"] and pd.notna(r["raw_finish"]) else "미지원/무효"}</td></tr>'
            past+='</table>'
            pieces.append(f'<article><h3>{row["program_no"]} {fmt(row["horse_name"])} <small>{fmt(row["ability_status"])}</small></h3>'
                          f'<p>과거 {row["history_count"]}전 · 휴양 {fmt(row["days_since_last"],0)}일 · 최근3/이전3/최근5 유효수 '
                          f'{row["moist_count3"]}/{row["moist_previous3_count"]}/{row["moist_count5"]} · 최근5 보정지원 {row["valid5_supported_count"]}회<br>'
                          f'최고기록: {fmt(row["moist_best_race_date"])} / {fmt(row["moist_best_result_distance"])}m / {fmt(row["moist_best_grade_raw"])}<br>'
                          f'직전 마체중 {fmt(row["previous_body_weight"],0)}kg (이전 대비 {fmt(row["body_weight_change"],0)}) · 직전 부담중량 {fmt(row["previous_carried_weight"],1)}kg</p>'
                          f'{metrics_html}<details><summary>최근10전 근거</summary><div class="scroll">{past}</div></details>'
                          f'<details><summary>현재 시점 게이트 시험값 — 과거 예측 입력 아님</summary><p>기준일2026-10-08. 과거이력 {gate["history_starts"]}회 중 lookup {gate["history_gate_lookup_count"]}회. '
                          f'최근3전 평균: 게이트0배 {fmt(gate["gate_0_mean3"])} / 0.5배 {fmt(gate["gate_0p5_mean3"])} / 1배 {fmt(gate["gate_1_mean3"])}. '
                          '보정 전체시간의 기존 척도를 고정하고 게이트 후보만 변화시킨 참고값. 당시 사용 가능 정보가 아니므로 성능 평가에 사용하지 않음.</p></details></article>')
        label=f'{"서울" if meet==1 else "부산"} {date.date()} {race}경주'
        sections.append(f'<section data-label="{html.escape(label,quote=True)}"><h2>{label} · {fmt(group.distance_m.iloc[0],0)}m</h2><div class="grid">'+''.join(pieces)+'</div></section>')
    diagnostic_rows=''
    for r in diagnostic:
        diagnostic_rows+=f'<tr><td>{"서울" if r["meet"]==1 else "부산"}</td><td>{"상태 변경" if r["changed_band"] else "동일 상태"}</td><td>{r["pairs"]}</td><td>{r["raw_mean_abs_seconds"]:.3f}</td><td>{r["moist_mean_abs_seconds"]:.3f}</td><td>{r["difference_seconds"]:+.3f}</td></tr>'
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>말별 평가표 첫 구현</title>
<style>body{font-family:system-ui,sans-serif;background:#f3f6f8;color:#172b36;margin:24px}main{max-width:1400px;margin:auto}p{line-height:1.7}h1{font-size:28px}small{font-size:13px;color:#59717d}.note{padding:18px;background:#e3edf5;border-radius:8px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:16px}article{background:white;border:1px solid #d9e3e8;border-radius:10px;padding:18px;overflow:hidden}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:7px;border-bottom:1px solid #e4ebee;text-align:left;font-variant-numeric:tabular-nums}details{margin:14px 0}summary{cursor:pointer;font-weight:600}.scroll{overflow:auto}input{padding:12px;width:300px;max-width:85%;font-size:16px;margin:20px 0}section{margin:30px 0}article p{font-size:13px}@media(max-width:450px){body{margin:12px}.grid{display:block}article{margin-bottom:14px}}</style>
<main><h1>말별 평가표 v1</h1><p class="note">과거 CARD_COUNT경주 RUNNER_COUNT두의 실제 이력 예시입니다. 당시 예측·추천 또는 입상확률이 아닙니다. 이력은 각 경주의T−2까지, 지수는 높을수록 빠릅니다. 종합점수·기수·게이트 가산은 기본 평가에 없습니다. 전체 구현 확인 범위는4,799경주·50,754출전입니다.</p>
<p>전체시간만 기존 함수율 보정. 원기록지수와 보정지수는 각각의 과거 기준표를 사용하므로 미지원 출전의 시간 자체가 같아도 지수는 달라질 수 있습니다. 구간기록·거리적성·전개는 다음 구현 단계입니다. 빈칸은0점이 아닙니다.</p>
<h2>같은 말의 연속 기록 차이 진단</h2><p>같은 지역·거리·등급,3~90일 간격, 양쪽 보정 지원. 평균 절대 시간차(초)가 작아졌는지 비교한 후향 진단입니다. 성장·컨디션·전개·중량 차이가 남아 순수 능력 또는 다음 경주 예측 개선의 증명이 아닙니다.</p>
<table><tr><th>지역</th><th>함수율 상태군</th><th>출전쌍</th><th>원기록 차이</th><th>보정 차이</th><th>보정−원</th></tr>DIAG_ROWS</table>
<input id="query" placeholder="경마장·경주·마명 검색"><span id="count"></span>SECTIONS</main>
<script>const q=document.querySelector('#query');const sections=[...document.querySelectorAll('section')];function filter(){let count=0;for(const s of sections){let n=0;for(const a of s.querySelectorAll('article')){const visible=(s.dataset.label+' '+a.querySelector('h3').textContent).includes(q.value);a.hidden=!visible;if(visible)n++;}s.hidden=!n;count+=n;}document.querySelector('#count').textContent=count+'두';}q.addEventListener('input',filter);filter();</script></html>'''
    page=page.replace('CARD_COUNT',str(cards.race_key.nunique())).replace('RUNNER_COUNT',str(len(cards)))
    page=page.replace('DIAG_ROWS',diagnostic_rows).replace('SECTIONS',''.join(sections))
    (OUT/'profiles.html').write_text(page)

def main():
    if OUT.exists():raise FileExistsError('Refusing to overwrite completed or partial outputs')
    sources=[DB,BASE_PATH,MOIST/'adjusted_records.parquet',MOIST/'effects.parquet',MOIST/'record_references.csv',RAW,PRED,GATE,
             ROOT/'config/prediction_model_registry.json',RESEARCH/'20261006_feature_inventory_v1/baseline_contract.json',
             RESEARCH/'20261007_horse_profile_spec_v1/README.md']
    hashes={str(p.relative_to(ROOT)):sha(p) for p in sources}
    print('Loading frozen records',flush=True)
    records=load_records();targets=load_targets()
    print('Building profiles',len(targets),flush=True)
    profiles=build_profiles(targets,records)
    pairs,diagnostic=paired_diagnostic(records)
    cards=latest_cards(profiles)
    sensitivity,history=gate_sensitivity(cards,records)
    summary=profile_summary(profiles)
    OUT.mkdir()
    profiles.to_parquet(OUT/'profiles.parquet',index=False)
    pairs.to_parquet(OUT/'paired_diagnostic.parquet',index=False)
    cards.to_parquet(OUT/'display_cards.parquet',index=False)
    history.to_parquet(OUT/'display_history.parquet',index=False)
    sensitivity.to_parquet(OUT/'gate_sensitivity_current_view.parquet',index=False)
    save(OUT/'summary.json',dict(status='profile_implementation_not_prediction_model',profile_rows=len(profiles),races=int(profiles.race_key.nunique()),
          display_races=int(cards.race_key.nunique()),display_runners=len(cards),venues=summary,paired_diagnostic=diagnostic,
          gate_view_as_of='2026-10-08',gate_historical_prediction_allowed=False,new_training=False,production_changed=False))
    save(OUT/'sources.json',hashes)
    render(cards,history,sensitivity,summary,diagnostic)
    for p,h in hashes.items():
        assert sha(ROOT/p)==h,'Source changed: '+p
    print(json.dumps(dict(runners=len(profiles),races=int(profiles.race_key.nunique()),display_runners=len(cards),diagnostic=diagnostic),ensure_ascii=False),flush=True)

if __name__=='__main__':main()
