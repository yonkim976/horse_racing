"""Publish immutable body-variation results and update the topic catalogue."""
from pathlib import Path
import json
import hashlib
import re
import numpy as np
import pandas as pd

H=Path(__file__).resolve().parent;ROOT=H.parents[2];C=H.parent/'conclusions'
def sha(p):
    v=hashlib.sha256()
    with p.open('rb') as f:
        for z in iter(lambda:f.read(1048576),b''):v.update(z)
    return v.hexdigest()
def save(name,value):
    with (H/name).open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)
def put(p,text):p.write_text(text,encoding='utf-8')
def table(headers,rows):return '| '+' | '.join(headers)+' |\n|'+'|'.join(['---']*len(headers))+'|\n'+''.join('| '+' | '.join(map(str,r))+' |\n' for r in rows)
prior=json.loads((C/'source_manifest.json').read_text())
for r in prior['files']:assert sha(ROOT/r['path'])==r['sha256'],r['path']
assert json.loads((H/'independent_verification.json').read_text())['status']=='passed'
assert json.loads((H/'boundary_correction_verification.json').read_text())['all_groups_partition_and_decimal_checks_passed']
p=pd.read_csv(H/'pair_features.csv');typical=pd.read_csv(H/'typical_change_summary.csv');raw=pd.read_csv(H/'raw_direction_groups_v2.csv');effects=pd.read_csv(H/'effects.csv')
for r in typical.itertuples():
    lo,hi=json.loads((H/'PLAN.json').read_text())['periods'][r.period];g=p[p.year.between(lo,hi)];g=g if r.distance==0 else g[g.distance.eq(r.distance)];v=g.body_change_kg.abs().to_numpy();assert len(v)==r.rows
    assert np.allclose([v.mean(),np.median(v),*np.quantile(v,[.75,.90,.95])],[r.absolute_mean_kg,r.absolute_median_kg,r.absolute_p75_kg,r.absolute_p90_kg,r.absolute_p95_kg])
distrows=[]
for r in typical[typical.period.eq('full')&typical.distance.between(800,1200)].itertuples():distrows.append([f'{r.distance}m',f'{r.rows:,}',f'{r.absolute_mean_kg:.2f}kg',f'{r.absolute_median_kg:g}kg',f'{r.absolute_p90_kg:g}kg'])
labels={'zero':'변화 0kg','gain_within':'평소 범위 증가','gain_above':'평소보다 큰 증가','loss_within':'평소 범위 감소','loss_above':'평소보다 큰 감소'}
rawrows=[]
for key in ['zero','gain_within','gain_above','loss_within','loss_above']:
    r=raw[raw.period.eq('full')&raw.variant.eq('primary')&raw.distance.eq(1000)&raw.group.eq(key)].iloc[0]
    rawrows.append([labels[key],f'{int(r.rows):,}',f'{r.body_delta_mean_kg:+.2f}kg',f'{100*r.raw_half_improved_rate:.1f}%',f'{100*r.raw_half_similar_rate:.1f}%',f'{100*r.raw_half_worsened_rate:.1f}%'])
adjusted=[]
for dist in [800,900,1000,1110,1200]:
    g=effects[effects.period.eq('full')&effects.variant.eq('primary')&effects.distance.eq(dist)&effects.target.eq('relative_delta_s')]
    gain=g[g.contrast.eq('gain_above_minus_within')].iloc[0];loss=g[g.contrast.eq('loss_above_minus_within')].iloc[0]
    adjusted.append([f'{dist}m',f'{int(gain.rows):,}',f'{gain.effect:+.3f}',f'{gain.ci_lo:+.3f}~{gain.ci_hi:+.3f}',f'{loss.effect:+.3f}',f'{loss.ci_lo:+.3f}~{loss.ci_hi:+.3f}'])
recent=[]
for period,label in [('confirmation','2024~2025'),('2026partial','2026 부분')]:
    for dist in [1000,1110,1200]:
        g=effects[effects.period.eq(period)&effects.variant.eq('primary')&effects.distance.eq(dist)&effects.target.eq('relative_delta_s')]
        for sign,korean in [('gain','증가'),('loss','감소')]:
            r=g[g.contrast.eq(sign+'_above_minus_within')].iloc[0];recent.append([label,f'{dist}m',korean,f'{int(r.rows):,}',f'{r.effect:+.3f}',f'{r.ci_lo:+.3f}~{r.ci_hi:+.3f}',f'{r.q_BH:.3f}'])
assert not effects.q_BH.lt(.05).any()
decision={'period_start':'2017-01-01','period_end':'2026-09-19','partial_2026':True,'source_pairs':27230,'personal_history_supported_pairs':17462,'same_distance_history_supported_pairs':9517,'absolute_mean_change_kg':float(p.body_change_kg.abs().mean()),'absolute_median_change_kg':3.0,'absolute_p75_change_kg':5.0,'absolute_p90_change_kg':7.0,'absolute_p95_change_kg':9.0,'unusual_definition':'above own latest10 eligible earlier absolute-change mean,minimum5 history','adjusted_gain_or_loss_direction_BH_supported_cells':0,'large_mean_plus_sd_direction_BH_supported_cells':0,'individual_record_unchanged_proven':False,'group_mean_half_second_margin':'pointwise95CI only; exploratory practical comparison margin, not familywise equivalence claim','fixed_correction_adopted':False,'body_management_or_optimum_recommendation_adopted':False,'independent_future_holdout':False,'operational_change':False,'final_descriptive_file':'raw_direction_groups_v2.csv'}
save('decision.json',decision)
report='''# 평소보다 큰 마체중 변화와 이전 대비 경주 기록

2026년 10월 8일 완료. **이 비교 표본의 체중 변화폭은 평균 3.40kg, 중앙값 3kg이다. 말별 평소 평균을 넘는 증가·감소가 있었다고 기록이 반드시 나빠지거나 좋아지는 방향은 확인하지 못했다. 조건을 고려한 두 군의 평균 추가 차이는 작았지만, 개별 말의 기록이 그대로 유지됐다는 뜻은 아니다.**

## 대상과 평소 변화폭

2017-01-01~2026-09-19 자료이며 2026년은 부분연도다. 앞선 중량 연구의 정상 완전순위 52,155출전·5,206경주·2,813두, 7~13두 편성에서 같은 말·정확 거리·원문 등급·연도, 7~60일 적격 출전 27,230쌍(2,413두·4,666개 뒤 경주)을 그대로 사용했다. 현재 대상 800·900·1000·1110·1200·1300·1400·1610m를 유지하고 400m는 과거 워밍업으로 제외했다.

증가와 감소를 합친 부호 있는 평균은 −0.60kg이지만 이것은 평소 변화폭이 아니다. 변화 절댓값 평균은 **3.396kg**, 중앙값 3kg, 75백분위 5kg, 90백분위 7kg, 95백분위 9kg이다. 체중이 그대로인 쌍은 10.4%였다. 일정 간격의 모든 경력 출전을 대표하는 수치가 아니라 위 선정 조건의 표본 평균이다.

''' + table(['거리','전체 비교쌍','절댓값 평균 변화','중앙 변화폭','90백분위 변화폭'],distrows) + '''
1300m는 213쌍·평균 3.28kg, 1400m는 239쌍·3.67kg이나 말별 분류 후 통계 지원이 부족하다. 1610m는 5쌍이므로 평균을 일반화하지 않는다. kg은 두 끝 출전의 실측 체중 차이이며 원문 괄호 안의 직전 출전 증감과 같다고 가정하지 않았다.

## 말별 비교 기준

각 경주일 D의 T−2까지 관측된 같은 말의 이전 적격 출전쌍 중 최근 최대 10개에서 절대 변화의 평균을 구했다. 최소 5개 이력을 요구해 **17,462쌍**이 개인 기준을 만들 수 있었다. 이력이 없는 9,768쌍은 큰 변화로 임의 분류하지 않았다. 개인 기준 계산에는 서로 다른 거리의 적격 쌍을 포함하지만 각 쌍의 두 끝은 정확히 같은 거리다. 같은 거리 이력만 사용한 9,517쌍도 민감도로 비교했다.

예를 들어 이전 절대 변화 평균이 3kg인 말은 ±3kg 이내를 평소 범위, ±4kg 이상을 평균 초과로 분류한다. 이 평균은 개인 기준일 뿐 정상·이상 또는 건강 판정 경계가 아니다. 체중 변화 0kg는 따로 뒀다. 매우 큰 변화의 추가 기준은 개인 평균+표준편차였고 결과를 본 뒤 경계를 선택하지 않았다.

기록이 빨라짐은 이전보다 0.5초 넘게 감소, 비슷함은 ±0.5초 이내, 느려짐은 0.5초 넘게 증가로 정의했다. 정확히 같은 기록과 ±1초 분류도 전체 표에 보존했다. 0.5초는 연구용 비교 폭이며 계측오차나 경마상 의미가 검증된 허용치가 아니다.

## 실제로 이전과 기록이 같았는가

1000m 개인 기준 지원 6,074쌍의 원기록 분포다. 이는 부담중량·함수율·시기·직전 경기력 등을 아직 조정하지 않은 실제 빈도다.

''' + table(['체중 변화 분류','쌍','실제 평균 증감','0.5초 넘게 향상','±0.5초 이내','0.5초 넘게 악화'],rawrows) + '''
평소보다 큰 증가군은 평균 +5.54kg였고, 향상 32.9%·비슷함 28.4%·악화 38.7%였다. 평소 범위 증가군의 악화 40.4%보다 높지 않았다. 평소보다 큰 감소군은 평균 −5.66kg, 향상 41.2%로 평소 범위 감소군의 33.4%보다 높았지만 악화 사례도 32.9% 있었다. 800~1200m 전체에서 큰 증가군 향상은 28.8~40.1%, 큰 감소군 향상은 40.3~44.3%여서 한 방향만으로 설명되지 않는다.

1000m의 기록 변화 절댓값 평균은 평소 범위 증가 1.32초·큰 증가 1.37초, 평소 범위 감소 1.33초·큰 감소 1.41초였다. 방향을 합친 변동량도 단순 평균에서 크게 벌어지지 않았다. 이 변동량 비교는 기술 통계이며 분산 증가의 유의성 검정은 아니다.

## 경주 조건과 이전 성적을 고려한 방향

부담중량 증감·직전 부담과 체중·간격·사건 나이·직전 상대 기록과 순위·과거 기록·두수 변화·개인 변화폭 평균과 표준편차·함수율 등급과 게이트 변화·연중 주기·연도와 등급을 고려했다. 체중 그룹 4개와 절편은 비벌점, 기타 항은 표준화 ridge1이다. 두 결과는 원기록 변화와 각 경주의 중앙 기록 대비 편차 변화다. 양수는 더 느려진 방향이다.

다음은 **평소 평균을 넘은 군−평소 범위 군의 조정된 상대 기록 변화 차이**다. 상대 기록은 그날 경주 전체가 빠르거나 느린 부분을 일부 제거하지만 상대 말 능력·편성·페이스를 완벽히 통제하지는 않는다. 동일 말의 단독 인과효과도 아니다.

''' + table(['거리','전체 비교쌍','큰 증가 차이 초','점별95% 구간','큰 감소 차이 초','점별95% 구간'],adjusted) + '''
모든 거리의 증가·감소 대비에서 BH 기준을 충족한 방향 근거는 없었다. 1000m의 큰 감소군은 원기록 조정 차이 −0.196초(점별95% −0.368~−0.024)였지만 다중비교 후 불확실(q=0.258)했고, 상대 기록 차이는 −0.045초(−0.160~+0.071)로 작았다. 원시 기록에서 감량 뒤 더 좋아진 빈도를 감량의 고정 효과로 바꾸기 어려운 이유다.

전체기간 800~1200m 상대 기록 대비의 점별95% 구간은 모두 ±0.5초 안에 들어왔다. 이는 정한 연구 폭에서 **군 평균 추가 차이가 크지 않다는 제한적 근거**다. 다수 대비 전체를 동시에 보장하는 동등성 판정이나 개별 말의 기록 유지 증명은 아니다. 원기록에서는 1200m 일부 구간이 ±0.5초를 넘어 불확실했다.

## 최근 기간과 더 큰 변화

''' + table(['기간','거리','체중 방향','전체 비교쌍','상대 기록 추가 차이 초','점별95% 구간','BH q'],recent) + '''
2024~2025년 1000m의 큰 증가가 느린 방향(+0.292초, 점별95% +0.014~+0.570)이었지만 BH q=0.240으로 확정하지 못했고 2026년에는 반대 방향이었다. 2026년은 표본과 구간이 작거나 넓어 전체기간의 평균 차이를 그대로 적용하지 않는다. 800·900m 최근 분류는 최소 그룹 수를 충족하지 못했다.

개인 평균+표준편차를 넘는 큰 변화군의 실제 평균은 거리별 증가 약 +6.55~+7.43kg, 감소 −7.24~−7.56kg였다. 이 기준, 같은 거리만으로 만든 개인 기준, 같은 달·함수율 등급·부담 변화 ±1kg 이내 기준에서도 확실한 방향 근거는 없었다. 전체 기간·원기록·상대 기록·모든 사전 대비 216개를 보존했으며 BH q<0.05 대비는 0개다. 매우 드문 극단 체중 변화의 무해함이나 모든 개인의 반응 동일성을 증명한 결과는 아니다.

## 적용과 한계

체중 변화폭은 말별 평소 범위와 함께 설명 정보로 제공할 수 있다. 그러나 평균 초과 증가를 자동 감점하거나 평균 초과 감소를 자동 가점하는 보정은 채택하지 않는다. 평균 3.4kg·90백분위 7kg는 자료 설명이며 권장 체중 관리 폭이 아니다.

당일 체중은 사후 설명 측정으로, T−2에 미리 알 수 있는 값으로 취급하지 않았다. 개인 기준만 과거 사건으로 계산했다. 비교쌍은 전체 경력의 직전 출전일 필요가 없고, 성장·건강·급이·측정·출전 선택의 영향을 완전히 분리하지 못했다. 앞 출전일을 공유하는 다른 말의 상관은 뒤 출전일 군집으로 완전히 반영되지 않을 수 있다. 날짜+말 공분산을 합하고 교집합을 빼지 않은 보수적 구간과 작은 군집 수의 t 기준을 사용했다. 같은 과거 자료의 후속 개발 분석이며 독립 미래 검증은 아니다. 운영 예측 모형과 DB·스키마·등록부는 변경하지 않았다.

## 원천과 검증

읽기 전용 원천 DB SHA256은 `a878a40fd5dc28e1385801c40136e506d9e3bc406e357e4158e5eb6883f5f21e`다. 공식 말 ID·경주키·제외마 정책을 유지했다. [사전 계획](PLAN.json), [코드](analyze.py), [말별 과거 이력 연결](history_lineage.json), [개인 기준과 전체 쌍](pair_features.csv), [평균 변화폭](typical_change_summary.csv), [최종 방향 빈도](raw_direction_groups_v2.csv), [조정 효과](effects.csv), [지원 표](support.csv), [최종 판정](decision.json)을 보존했다.

[독립 검증](independent_verification.json)은 전체 27,230쌍의 체중·시간·상대 기록 끝점과 275,347개 이전 이력, 293개 분류행과 모든 216개 효과·구간·다중비교를 대조했다. 1000·1110m 전체 및 2024~2025년 8개 모형은 계수와 날짜+말 공분산을 별도 계산했다. 원천·기존 연구·DB 해시는 유지됐다.

상대 기록의 정확히 0.5초·1초 경계에서 이진 소수점 잔차를 확인해 1e−8초 허용과 소수6자리 반올림의 독립 일치로 방향 빈도를 정리했다. 최종 표는 `raw_direction_groups_v2.csv`이고 초기 표는 보존했다. 효과·신뢰구간·p·q·체중 그룹은 바뀌지 않았다. [경계 검증](boundary_correction_verification.json)과 [출판 검증](publication_verification.json), [보관 파일 크기와 해시](artifact_manifest.json)를 따른다.
'''
# Check the actual verifier count before inserting a claim into the report.
ver=json.loads((H/'independent_verification.json').read_text());report=report.replace('293개 분류행',f"{ver['raw_group_rows_checked']}개 분류행")
with (H/'README.md').open('x',encoding='utf-8') as f:f.write(report)

topic=C/'04_WEIGHT_SPEED.md';text=topic.read_text();section='''## 평소보다 큰 체중 변화와 기록 방향 후속

2017~2026-09-19(2026 부분) 동일 말·거리·등급·연도 7~60일 27,230쌍에서 체중 변화 절댓값 평균은 3.40kg, 중앙값 3kg, 75백분위 5kg, 90백분위 7kg, 95백분위 9kg이었다. 전체 평균은 출전 조건으로 선정한 표본의 기술 통계다.

각 말의 해당 경주 T−2 이전 최근 최대 10개 적격 변화(최소 5개)의 절댓값 평균을 만들 수 있는 17,462쌍에서 평소 평균 초과 증가·감소를 분리했다. 1000m 큰 증가군(평균 +5.54kg, 1,062쌍)의 원기록 향상·±0.5초 유지·악화 비율은 32.9·28.4·38.7%, 큰 감소군(−5.66kg, 1,392쌍)은 41.2·25.9·32.9%였다. ±0.5초는 연구용 분류 폭이며 개별 기록이 유지된다는 보장은 아니다.

부담·직전 성적·함수율·시기·게이트 등을 고려한 상대 기록의 큰 변화군−평소 범위군 차이는 전체기간 1000m 증가 +0.068초(점별95% −0.057~+0.192), 감소 −0.045초(−0.160~+0.071)였다. 전체 800~1200m·최근 기간·평균+표준편차 초과·같은 거리 기준·안정 조건에서 BH 근거가 있는 방향은 없었다. 군 평균의 추가 차이는 작지만 개별 기록 유지나 큰 감량의 이점을 확정하지 않는다. 이전 연속 kg 기울기 연구와 질문·표본이 다르므로 그 결과를 삭제하지 않는다.

고정 체중 가감점·관리 권장 폭은 채택하지 않았다. [상세 후속](../20261008_body_variation_direction_v1/README.md), [최종 빈도](../20261008_body_variation_direction_v1/raw_direction_groups_v2.csv), [효과와 구간](../20261008_body_variation_direction_v1/effects.csv)을 따른다. 아래 증량 위험·적정 체중·평균 감속의 이전 결과도 보존한다.

''';text=text.replace('## 큰 증량과 기록 악화 위험 후속',section+'## 큰 증량과 기록 악화 위험 후속',1);put(topic,text)
readme=C/'README.md';text=readme.read_text().replace('체중 증감 연관과 큰 증량 뒤 상대 부진 위험 관찰. 확정 적정 체중·고정 보정은 미채택','평소 체중 변화폭 평균 3.4kg. 개인 평균 초과 증감의 일정한 기록 방향 미확인. 큰 부담 증량의 부진 위험은 별도');put(readme,text)
sources=C/'SOURCES.md';text=sources.read_text().replace('같은 출전 자료가 여러 버전에 중복되므로','| [20261008_body_variation_direction_v1](../20261008_body_variation_direction_v1/README.md) | 평소 체중 변화폭과 개인 평균 초과 증가·감소 뒤 기록 방향. 27,230쌍의 평균 절대 변화 3.4kg, 개인 기준 17,462쌍. 안정적인 조정 방향 미확인. 최종 방향 빈도는 소수점 경계를 정리한 v2 표이며 초기 표·통계 계수 모두 보존 |\n\n같은 출전 자료가 여러 버전에 중복되므로',1);put(sources,text)
register=json.loads((C/'research_register.json').read_text())
for tpc in register['topics']:
    if tpc['id']=='weight_speed':
        tpc['load_tail_source']=tpc['latest_source'];tpc['latest_source']='../20261008_body_variation_direction_v1/README.md';tpc['status']='personal_body_change_magnitude_and_record_direction_followup_completed_no_fixed_correction';tpc['latest_body_variation_followup']=decision|{'source':'../20261008_body_variation_direction_v1/README.md'}
put(C/'research_register.json',json.dumps(register,ensure_ascii=False,indent=2)+'\n')
targets=[]
for file in [H/'README.md']+list(C.glob('*.md')):
    for dest in re.findall(r'\]\(([^)]+)\)',file.read_text()):
        if '://' in dest or dest.startswith('#'):continue
        target=(file.parent/dest.split('#',1)[0]).resolve();assert target.exists() or target in [H/'artifact_manifest.json',H/'publication_verification.json'],(file,dest);targets.append(target)
save('publication_verification.json',{'status':'passed','all_prior_sources_unchanged':True,'typical_summary_numpy_reproduced':True,'final_descriptive_boundary_correction_verified':True,'local_links_checked':len(targets),'operational_change':False,'new_archive_sizes':'artifact_manifest.json','modified_management_sizes':'../conclusions/source_manifest.json'})
archive=[{'path':f.name,'bytes':f.stat().st_size,'sha256':sha(f)} for f in sorted(H.iterdir()) if f.is_file()]
save('artifact_manifest.json',{'self_excluded':True,'files':archive,'bytes_excluding_this_manifest':sum(r['bytes'] for r in archive),'count_excluding_this_manifest':len(archive)})
assert all(t.exists() for t in targets)
files=[]
for r in prior['files']:
    if r['role']=='conclusion_or_management':f=ROOT/r['path'];r=dict(r,sha256=sha(f),bytes=f.stat().st_size)
    else:assert sha(ROOT/r['path'])==r['sha256'],r['path']
    files.append(r)
for f in sorted(H.iterdir()):
    if f.is_file():files.append({'path':str(f.relative_to(ROOT)),'role':'source_body_variation_direction','sha256':sha(f),'bytes':f.stat().st_size})
final=dict(prior,files=files,updated_at='2026-10-08',verification={'status':'passed','all_previous_source_hashes_unchanged':True,'local_links_checked':len(targets),'latest_study':str(H.relative_to(ROOT)),'latest_verification':str((H/'independent_verification.json').relative_to(ROOT))},managed_files_bytes_excluding_this_manifest=sum(r['bytes'] for r in files));put(C/'source_manifest.json',json.dumps(final,ensure_ascii=False,indent=2)+'\n');assert all(sha(ROOT/r['path'])==r['sha256'] for r in files)
print(json.dumps({'status':'published_research_only','new_archive_files':len(archive)+1,'new_archive_bytes':sum(f.stat().st_size for f in H.iterdir() if f.is_file()),'local_links':len(targets),'previous_sources_preserved':True}))
