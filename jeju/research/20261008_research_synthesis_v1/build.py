"""Verify published source summaries and save synthesis, without refitting."""
from pathlib import Path
import hashlib
import json
import re
import numpy as np
import pandas as pd

H=Path(__file__).resolve().parent;ROOT=H.parents[2];R=H.parent;C=R/'conclusions'
def sha(p):
    x=hashlib.sha256()
    with p.open('rb') as f:
        for z in iter(lambda:f.read(1048576),b''):x.update(z)
    return x.hexdigest()
def clean(v):
    if isinstance(v,dict):return {k:clean(x) for k,x in v.items()}
    if isinstance(v,list):return [clean(x) for x in v]
    if isinstance(v,np.generic):v=v.item()
    return None if isinstance(v,float) and not np.isfinite(v) else v
def save(name,value):
    with (H/name).open('x',encoding='utf-8') as f:json.dump(clean(value),f,ensure_ascii=False,indent=2,allow_nan=False)
def put(p,text):p.write_text(text,encoding='utf-8')
prior=json.loads((C/'source_manifest.json').read_text())
for r in prior['files']:assert sha(ROOT/r['path'])==r['sha256'],r['path']
csvrefs=[R/'20261008_weight_speed_v2/source_lineage.csv',R/'20261008_weight_speed_v2/effects.csv',R/'20261008_gate_top3_period_moisture_v1/adjusted_contrasts.csv',R/'20261008_gate_top3_period_moisture_v1/raw_lateral.csv',R/'20261008_gate_record_seconds_v1/lateral_seconds.csv',R/'20261008_recent_form_persistence_v1/paired_improvements.csv',R/'20261008_load_tail_training_v1/burden_effects_bh_v2.csv',R/'20261008_load_tail_training_v1/training_prediction_improvements.csv',R/'20261008_body_variation_direction_v1/typical_change_summary.csv',R/'20261008_body_variation_direction_v1/effects.csv']
report=H/'README.md';refs=[report,H/'SCOPE.json',H/'build.py']+csvrefs
for dest in re.findall(r'\]\(([^)]+)\)',report.read_text()):
    if dest.startswith('../'):refs.append((H/dest).resolve())
refs=list(dict.fromkeys(refs));save('source_manifest.json',[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in refs])
src=pd.read_csv(csvrefs[0]);support=src.groupby('race_distance_m').agg(starts=('api_record_id','size'),general_races=('race_id','nunique'),general_first_date=('race_date','min'),general_last_date=('race_date','max')).reset_index().rename(columns={'race_distance_m':'distance_m'});ten=src[src.field_n.eq(10)].groupby('race_distance_m').agg(ten_runner_races=('race_id','nunique'),ten_first_date=('race_date','min'),ten_last_date=('race_date','max')).reset_index().rename(columns={'race_distance_m':'distance_m'});support=support.merge(ten,on='distance_m',validate='one_to_one');support.distance_m=support.distance_m.astype(int)
assert len(src)==52155 and src.race_id.nunique()==5206 and support.ten_runner_races.sum()==3930 and support.starts.sum()==52155
assert support.general_races.tolist()==[1258,890,1424,988,486,63,88,9]
assert support.ten_runner_races.tolist()==[1057,690,1067,700,304,47,63,2]
assert src.race_date.max()=='2026-09-19'
with (H/'distance_support.csv').open('x') as f:support.to_csv(f,index=False)
gate=pd.read_csv(csvrefs[2]);gate=gate[gate.kind.eq('overall')&gate.variant.eq('primary')];assert gate[gate.q_BH.lt(.05)].distance.tolist()==[800,900]
np.testing.assert_allclose(gate[gate.distance.isin([800,900])].effect_pp,[11.463017971977564,7.391820476],atol=1e-6)
time=pd.read_csv(csvrefs[4]);time=time[time.variant.eq('primary')&time.contrast.eq('inner_minus_outer')&time.distance.eq(800)&time.period.isin(['full','confirmation'])];np.testing.assert_allclose(time.effect_s,[-.384951670998,.496*-1],atol=.001)
weight=pd.read_csv(csvrefs[1]);weight=weight[weight.family.eq('row')&weight.period.eq('full')&weight.variant.eq('primary')&weight.target.eq('time_s')&weight.exposure.eq('burden')];np.testing.assert_allclose(weight[weight.distance.le(1200)].effect,[.039,.040,.056,.069,.052],atol=.001)
form=pd.read_csv(csvrefs[5]);form=form[form.period.eq('2024_2025')&form.contrast.eq('B_vs_A')&form.metric.eq('mae')&form.distance.isin([1000,1110,1200])];assert form.q_BH.lt(.05).all();np.testing.assert_allclose(form.effect,[.124,.220,.096],atol=.001)
burden=pd.read_csv(csvrefs[6]);burden=burden[burden.family.eq('burden_risk')&burden.variant.eq('primary')&burden.target.eq('relative_slow1')&burden.period.isin(['full','confirmation','2026partial'])];assert burden[burden.period.eq('confirmation')&burden.q_BH.lt(.05)].distance.tolist()==[1000,1110,1200];assert not burden[burden.period.eq('2026partial')].q_BH.lt(.05).any()
training=pd.read_csv(csvrefs[7]);training=training[training.period.isin(['2024_2025','2026partial'])];assert not ((training.effect>0)&training.q_BH.lt(.05)).any()
typical=pd.read_csv(csvrefs[8]);overall=typical[typical.period.eq('full')&typical.distance.eq(0)].iloc[0];assert round(overall.absolute_mean_kg,2)==3.40 and overall.absolute_p90_kg==7 and overall.absolute_p95_kg==9
body=pd.read_csv(csvrefs[9]);assert not body.q_BH.lt(.05).any()
save('evidence_snapshot.json',{'source_populations':{'body_load_starts':52155,'body_load_races':5206,'body_load_horses':int(src.horse_id.nunique()),'gate_starts':39300,'gate_races':3930},'gate_overall':gate.to_dict('records'),'gate_800_seconds':time.to_dict('records'),'load_row_seconds_per_kg':weight.to_dict('records'),'recent_vs_older_record_MAE_improvement':form.to_dict('records'),'load_tail_relative_risk':burden.to_dict('records'),'training_incremental_prediction':training.to_dict('records'),'typical_body_change':overall.to_dict(),'body_unusual_variation_BH_cells':int(body.q_BH.lt(.05).sum()),'new_effect_estimates':False,'interpretation_priority_is_not_fitted_feature_importance':True})

overview='''# 제주마와 거리별 연구 종합

2026년 10월 8일 기준. 주요 자료는 2017~2026-09-19이며 2026년은 부분연도다. **동일거리의 최근 수행을 평가 중심에 두고 800·900m 출발번호와 부담중량을 함께 해석할 근거가 있다. 함수율·월·체중·조교의 고정 보정치는 아직 확정하지 못했다.** 이는 완료 연구의 종합이며 새 실험이나 운영 반영이 아니다.

## 제주마의 기록 해석

| 요인 | 현재 결론 |
|---|---|
| 최근 동일거리 기록 | 후속 기록의 정보가 관찰됨. 생리적 컨디션·건강 진단과 구분 |
| 부담중량 | 전체기간 작은 평균 감속 연관과 큰 증량 뒤 상대 부진 위험 연관. 고정 초/kg 미채택 |
| 체중 증감 | 평균 절대 변화 3.4kg. 개인 평소 범위를 넘는 증감의 일정한 추가 방향 미확인 |
| 체중과 성별 | 같은58kg의 비율은 체구별로 다르나 추가 기록 손실·암수 반응 차이·안정적 최적kg은 미확정 |
| 함수율·계절·월 | 기록 차이 후보는 있으나 재현되는 고정 환산값이 부족. 환경 영향 부재로 해석하지 않음 |
| 조교 | 관측 일수·시간 요약은 최근 기록 대비 안정적 추가 개선 미확인. 강도·속도·거리 전체의 무용함을 뜻하지 않음 |

## 제주 경기장 거리별 관찰 특성

| 거리 | 출발번호 연구의 대표 결론 | 함께 해석할 근거 |
|---|---|---|
| 800m | 정확10두에서 내측 입상·시간 우세 재현 | 번호 조건을 설명할 근거가 가장 뚜렷. 2026년10두는3경주 |
| 900m | 내측 입상 우세, 초 단위 차이는 불확실 | 입상 연관과 기록 환산을 구분 |
| 1000m | 최신 보수적 내외측 차이 불확실 | 최근 기록·큰 부담 증량·환경 조건 |
| 1110m | 내외측 차이 불확실 | 반복 수행·부담 변화·미확정 함수율 후보 |
| 1200m | 내외측 차이 불확실 | 최근 기록과 큰 부담 증량의 부진 연관 |
| 1300m | 10두47경주 제한 표본 | 고정 거리·번호·체중 계수 미채택 |
| 1400m | 10두63경주 제한 표본 | 초기 큰 추정치를 일반화하지 않음 |
| 1610m | 10두2경주, 중량 전체도9경주 | 거리 특성 미확정 |

내측은1~3번·외측은8~10번이며 출발번호와 실제 주행 위치는 같지 않다. 다른 두수에 그대로 옮기지 않는다. 내측 우세의 전체 조정 Top3 차이는800m+11.46%p(점별95%+7.91~+15.01),900m+7.39%p(+2.42~+12.37)다. 800m 시간 차이는 내측−외측−0.385초(−0.500~−0.270),2024~2025년−0.496초(−0.802~−0.191)다. 시험용±0.10초는 확정 보정표가 아니다.

1300·1400·1610m의 보유 중량 표본 시작은 각각2024-05-18·2020-07-25·2025-09-13이며 공식 거리 신설일을 뜻하지 않는다. 400m는2025·2026년 보유 시행 기록이 없어 과거 워밍업으로 보존했다.

거리별 해석은 개별 연구를 종합한 방향이며 최적 가중치·변수 중요도를 계산한 순위가 아니다. 코너·직선 기하, 선행·추입 전개 적성과 다른 품종과의 비교는 이번 연구의 결론이 아니다. 기록의 기준 조건 환산과 미래 실제 기록 예측도 별도 목표로 유지한다.

[종합 상세 보고서](../20261008_research_synthesis_v1/README.md), [거리별 표본](../20261008_research_synthesis_v1/distance_support.csv), [원표 수치 발췌](../20261008_research_synthesis_v1/evidence_snapshot.json), [검증](../20261008_research_synthesis_v1/verification.json)을 따른다. 관찰 연관·연구 후보·확정 채택·운영 반영을 구분하며 고정 보정과 운영 변경은 없다.

각 주제의 최신 판정은 [출발번호](01_GATE_LATERAL.md), [함수율·월](02_ENVIRONMENT_CORRECTION.md), [기초·자료](03_FOUNDATION.md), [체중·부담중량](04_WEIGHT_SPEED.md), [최근 경기력](05_RECENT_FORM.md), [조교](06_TRAINING_RECORD.md)에 보존한다.
'''
assert not (C/'00_RESEARCH_SYNTHESIS.md').exists();put(C/'00_RESEARCH_SYNTHESIS.md',overview)
readme=C/'README.md';text=readme.read_text().replace('| [거리별 출발번호와 내외측]','| [제주마와 거리별 종합](00_RESEARCH_SYNTHESIS.md) | 최근 수행·단거리 출발번호·부담 변화와 미확정 환경·체중·조교 결과를 종합 | 완료 연구 종합, 새 실험·운영 반영 없음 |\n| [거리별 출발번호와 내외측]',1);put(readme,text)
sources=C/'SOURCES.md';text=sources.read_text().replace('같은 출전 자료가 여러 버전에 중복되므로','| [20261008_research_synthesis_v1](../20261008_research_synthesis_v1/README.md) | 제주마의 기록 요인과 경기장 거리별 관찰 특성의 종합. 최신 결과·기간·분모와 미확정 범위를 구분. 원표 수치·자료 지원 재대조이며 새로운 효과 추정이나 독립 검증은 아님 |\n\n같은 출전 자료가 여러 버전에 중복되므로',1);put(sources,text)
register=json.loads((C/'research_register.json').read_text());register['topics'].insert(0,{'id':'research_synthesis','title':'제주마와 경기장 거리별 연구 종합','conclusion':'00_RESEARCH_SYNTHESIS.md','latest_source':'../20261008_research_synthesis_v1/README.md','period_start':'2017-01-01','period_end':'2026-09-19','status':'completed_studies_synthesis_no_new_effect_estimation','operationally_applied':False});put(C/'research_register.json',json.dumps(register,ensure_ascii=False,indent=2)+'\n')
targets=[]
for f in [report]+list(C.glob('*.md')):
    for dest in re.findall(r'\]\(([^)]+)\)',f.read_text()):
        if '://' in dest or dest.startswith('#'):continue
        target=(f.parent/dest.split('#',1)[0]).resolve();assert target.exists() or target in [H/'verification.json',H/'artifact_manifest.json'],(f,dest);targets.append(target)
for r in json.loads((H/'source_manifest.json').read_text()):assert sha(ROOT/r['path'])==r['sha256']
save('verification.json',{'status':'passed','population_counts_reconciled_to_preserved_row_lineage':True,'latest_gate_load_form_training_body_claims_checked_against_source_tables':True,'source_hashes_unchanged':True,'all_previous_research_sources_unchanged':True,'local_links_checked':len(targets),'new_effect_estimation':False,'independent_future_validation':False,'operational_change':False,'archive_bytes_in':'artifact_manifest.json','modified_management_bytes_in':'../conclusions/source_manifest.json'})
archive=[{'path':f.name,'bytes':f.stat().st_size,'sha256':sha(f)} for f in sorted(H.iterdir()) if f.is_file()];save('artifact_manifest.json',{'self_excluded':True,'files':archive,'bytes_excluding_this_manifest':sum(r['bytes'] for r in archive),'count_excluding_this_manifest':len(archive)})
assert all(p.exists() for p in targets)
files=[]
for r in prior['files']:
    f=ROOT/r['path']
    if r['role']=='conclusion_or_management':r=dict(r,sha256=sha(f),bytes=f.stat().st_size)
    else:assert sha(f)==r['sha256'],r['path']
    files.append(r)
f=C/'00_RESEARCH_SYNTHESIS.md';files.append({'path':str(f.relative_to(ROOT)),'role':'conclusion_or_management','bytes':f.stat().st_size,'sha256':sha(f)})
for f in sorted(H.iterdir()):
    if f.is_file():files.append({'path':str(f.relative_to(ROOT)),'role':'source_research_synthesis','bytes':f.stat().st_size,'sha256':sha(f)})
final=dict(prior,files=files,updated_at='2026-10-08',verification={'status':'passed','all_previous_source_hashes_unchanged':True,'latest_study':str(H.relative_to(ROOT)),'latest_verification':str((H/'verification.json').relative_to(ROOT)),'local_links_checked':len(targets)},managed_files_bytes_excluding_this_manifest=sum(r['bytes'] for r in files));put(C/'source_manifest.json',json.dumps(final,ensure_ascii=False,indent=2)+'\n');assert all(sha(ROOT/r['path'])==r['sha256'] for r in files)
print(json.dumps({'status':'synthesis_saved','new_archive_files':len(archive)+1,'new_archive_bytes':sum(f.stat().st_size for f in H.iterdir() if f.is_file()),'previous_sources_preserved':True,'links_checked':len(targets)}))
