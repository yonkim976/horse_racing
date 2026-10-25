"""Publish descriptive results; no fit, automatic score or model promotion."""
from pathlib import Path
import hashlib
import json
import re
import shutil
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'outputs'
CENTRAL=HERE.parent/'conclusions'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
assert json.loads((OUT/'independent_verification.json').read_text())['passed']
t=pd.read_csv(OUT/'condition_statistics.csv')
f=pd.read_parquet(OUT/'condition_features.parquet')
common=pd.read_csv(OUT/'common_model_residuals.csv')
selections=[('previous_finish','top3','직전 Top3'),('previous_finish','7_plus','직전 7위 이하'),
    ('relative_rank','best_quarter','상대 기록 상위1/4'),('relative_rank','last_quarter','상대 기록 하위1/4'),
    ('relative_rank_x_previous_finish','best_quarter|top3','상대 기록 상위1/4 + 직전 Top3'),
    ('relative_rank_x_previous_finish','best_quarter|7_plus','상대 기록 상위1/4 + 직전 7위 이하'),
    ('same_recent_top3','80_plus','동일거리 최근 입상률80% 이상'),
    ('burden_change','down_ge2','직전 대비 부담2kg 이상 감소')]
lines=['| 조건 | 2024~2025 출전수 | 실제 입상률 | 2026 출전수 | 실제 입상률 | 2026 R1 평균 예측 |',
       '|---|---:|---:|---:|---:|---:|']
rows=[]
for family,condition,label in selections:
    a=t[t.family.eq(family)&t.condition.eq(condition)&t.period.eq('2024_2025')].iloc[0]
    b=t[t.family.eq(family)&t.condition.eq(condition)&t.period.eq('2026')].iloc[0]
    lines.append(f'| {label} | {a.rows:,} | {a.top3_rate:.2%} | {b.rows:,} | {b.top3_rate:.2%} | {b.R1_predicted:.2%} |')
    rows.append(dict(label=label,family=family,condition=condition,prior_rows=int(a.rows),recent_rows=int(b.rows),
        prior_rate=a.top3_rate,recent_rate=b.top3_rate,recent_R1_predicted=b.R1_predicted))
pd.DataFrame(rows).to_csv(OUT/'representative_conditions.csv',index=False)
high=f[f.C_same_recent_top3.eq('80_plus')].copy()
high['history_slots']=high.last5_same_source_ids.map(len)
support=high.groupby(['period','history_slots']).agg(rows=('y','size'),top3=('y','sum'),rate=('y','mean')).reset_index()
support.to_csv(OUT/'high_recent_rate_history_support.csv',index=False)
repeat=pd.read_csv(OUT/'period_repetition.csv')
# Pure numerical review: constant-within-race families have zero residual by construction.
repeat['R1_positive_both_above_roundoff']=repeat.R1_residual_2024_2025.gt(1e-12)&repeat.R1_residual_2026.gt(1e-12)
repeat['race_constant_family']=repeat.family.isin(['distance','grade_raw'])
repeat.to_csv(OUT/'period_repetition_review.csv',index=False)
report='''# 제주마 입상 조건과 모델이 놓친 정보 탐색

입상마의 조건을 비입상마와 함께 비교하면 새 모델의 입력 후보를 찾는 데 도움이 된다. 이번 첫 분석에서는 **직전 성적과 최근 성적 이력을 별도로 보강할 근거**가 관찰됐다. 현재 R1은 상대 기록 수준은 잘 반영하지만 직전 입상과 부진에 따른 확률 차이를 작게 잡았다. 통계표의 입상률을 고정 가점이나 말별 확률로 그대로 대입하지 않는다.

## 자료와 방법

2017-01-13~2026-09-19,52,155출전·5,206경주·입상15,618출전·비입상36,537출전이다. 정상 완전 착순·전체시간이 확인된6두 이상 편성이라는 기존 사후 선정 조건을 유지했다. 무이력마는 포함한다.400m는 과거 이력만 활용하며800~1610m의 현재8거리를 분석한다.2026년은 부분연도다.

| 기간 | 경주 | 출전 | 입상 |
|---|---:|---:|---:|
| 2017~2023 | 3,427 | 34,743 | 10,281 |
| 2024~2025 | 1,291 | 12,739 | 3,873 |
| 2026~9월19일 | 488 | 4,673 | 1,464 |

16개 단일 조건군과 정확10두의 거리별 번호 조건,사전 지정4개 조건 조합 등21개 조건군을 조사했다. 조건·구간·기간은 [계약](CONTRACT.md)에 결과 계산 전 고정했다. 전체727개 조건×기간 행과 거리별 세부표를 보존했다. 이미 여러 연구에서 사용한 자료이므로 새로운 독립 검증은 아니다.

각 조건에 출전·입상·비입상 수,말·경주·경주일 수를 붙였다. **입상마 중 그 조건을 가진 비율 P(조건|입상)**과 **그 조건을 가진 말의 입상률 P(입상|조건)**을 구분한다. 두 비율은 서로 바꾸어 쓰지 않는다. 비교 가능한 전체 비입상 출전을 분모에 포함하고 미관측은 별도 범주로 남겼다.

이번 거리·등급·편성·번호·부담은 당시 선언표를 결과 원장에서 재구성한 가정이다. 과거 게시·정정 시각 증빙과 실제 게이트 대응은 미확정이다. 과거 이력은 T−2까지이며 나이·성별은 직전 관측 값이다. 당일 실제 체중·함수율·실제 선행 여부를 예측 조건으로 쓰지 않았다. 기수·구간·조교·주행심사 등의 추가 조건은 해당 원천 계약과 과거 가용성을 점검하는 후속 단계로 남겼다.

## 대표 조건의 실제 입상률

다음 표는 사람이 해석하기 위한 대표 조건이며 최적 점수표가 아니다. 서로 겹치는 조건이므로 확률을 더하거나 곱하지 않는다. 모든 조건의 결과와 반례는 전체 표에 보존했다.

'''+ '\n'.join(lines)+'''

상대 기록 상위1/4은 자신의 최근 동일거리 평균시간보다 빠른 상대의 비율(정확동률0.5)이25% 미만이라는 뜻이다. 현재 편성 안의 관측 가능한 상대만 비교하며 원기록의 주로·등급·중량 차이는 남는다. 최상위 몇 두의 고정 순위나 환경 보정된 순수 능력이 아니다.

2026년 직전 입상 조건은 전체 출전의30.34%를 차지하지만 실제 입상 출전 중42.14%를 차지했다. 그 조건의 다음 입상률은43.51%다. 조건이 흔하다는 설명과 다음 입상 가능성 설명을 이처럼 분리할 수 있다.

## 현재 R1이 놓친 후보와 이미 반영한 조건

직전 입상 조건의 R1 평균은2024~2025년36.85%,실제43.78%로6.93%p 낮았고2026년37.90%,실제43.51%로5.62%p 낮았다. 관측−예측의 날짜95% 점별 구간은 각각+5.53~+8.29%p,+3.83~+7.41%p였다. 반대로 직전7위 이하에서는2026년 R1이25.91%로 예측했지만 실제20.13%로5.78%p 높았다. 직전 착순은 최근 시간만으로 설명되지 않는 경쟁 성과를 전달할 수 있다는 후보 가설이다.

상대 기록 상위1/4의2026년 실제42.34%와 R1예측42.39%는 매우 가깝다. 이 조건을 다시 임의 가점으로 추가하면 이미 모델에 들어간 정보를 중복 계산할 수 있다. 상대 기록이 좋은 말 안에서도 직전 입상/7위 이하의 실제 입상률은52.69%/28.11%로 갈렸다. 두 조건을 각각 입력하고 모델이 조건부 관계를 학습할 후보가 된다. 아직 거리·등급·배정 등 모든 차이를 통제한 인과 효과나 추가 모델 성능은 아니다.

같은 운영 비교467경주의 직전 입상1,363출전에서는 실제43.80%,R1예측37.87%,HY_R_FORM예측43.94%였다. 운영 모델의 성적 이력 등 넓은 정보가 후보 개발 방향을 확인하는 참고가 되지만,여러 입력과 학습 기간이 달라 이 격차를 직전 착순 한 열의 효과로 분리하지는 못한다.

## 반례와 표본 지원

‘동일거리 최근 입상률80% 이상’485출전의2026년 입상률49.90%만 보고 반복 능력으로 해석하면 안 된다. 이 중239출전은 같은 거리 이력이1회뿐이고100출전만 최근 창이5회였다. 각각 입상률은56.07%,37.00%다.2024~2025년에도5회 창은239출전·36.40%였다. 말의 성장·등급·편성 배정 등 구성 차이가 있을 수 있으므로 단순히 표본 수가 적을수록 좋다는 뜻은 아니다. 최근 입상 비율과 실제 관측수를 반드시 함께 사용해야 한다.

3kg 이상 증량 조건의 원시 입상률은2024~2025년44.59%,2026년37.84%로 오히려 높았다. 이를 ‘증량하면 유리’라는 규칙으로 옮기지 않는다. 이전 좋은 성적과 중량 배정·승급·상대 구성 등이 얽힐 수 있고,다른 연구의 같은 말 기록 손실과도 다른 질문이다. 현재 부담과 변화는 선언표 가용성 확인 후 별도 모형 비교가 필요하다.

정확10두의2026년800m는3경주,1610m는1경주다. 이 자료만으로 거리별 번호 규칙을 확정하지 않는다. 기존 전체기간 번호 연구와 이번 작은 최근 표본의 분모를 혼동하지 않는다. 나머지 거리·번호 결과도 모든 표본과 구간을 전체 표에 유지했다.

## 불확실성과 잔차의 의미

2024~2025·2026 조건별로 평균3/N 대비 입상률 차이와 R1 관측−예측에 경주일 bootstrap2,000회·seed20261009의95% 점별 구간을 계산했다. 같은 말의 날짜 간 반복에 대한 별도 군집 보정은 없다. 많은 조건·조합 중 일부를 해석한 탐색이므로 구간0배제를 다중비교 확증이나 자동 채택 기준으로 삼지 않는다.100출전 또는50경주 미만은 소표본으로 표시했다. 거리별 세부 분해 표는 점추정·지원량 진단표이며 그 자체의 검정 구간을 계산하지 않았다.

거리·등급처럼 경주 내 모든 말에게 같은 조건은 R1의 Top3 확률합3과 실제 입상수3에 의해 평균 잔차가 거의0이 된다. 이는 그 조건에서 확률의 개별 정확성이 좋다는 증거가 아니다. 반복표의 부동소수점1e−18 수준 양수는0으로 해석하고 별도 검토표에서1e−12 계산 오차 한계 및 경주 내 상수 조건을 표시했다.

양의 잔차가 남은 조건도 그 조건을 추가한 모델이 좋아진다는 뜻은 아니다. 변수의 중복·집단 혼합·표본의 우연·확률 보정 문제를 구분해야 한다. 입상률43.5%를 해당 말 모두의 확률로 복사하면 이번 상대 편성과 관측수 차이를 잃는다.

## 모델 입력으로 검증할 순서

1. 현재 R1을 보존하고 **직전 정상 착순의 상대순위/Top3 여부와 최근 동일거리 입상비율·실제 출전수**를 작은 묶음으로 추가한다. 비정상 착순·무이력은 별도 상태로 둔다. 이번 통계의 조건별 입상률을 모델 입력으로 넣지 않는다.
2. 같은 학습·확률보정·평가 분할에서 바로 이전 모델과 비교하고,HY_R_FORM 공통 경주 비교도 유지한다. Top3 확률·상위5두·6조합을 각각 평가한다.
3. 부담·기수·게이트와 전개는 가용 시점과 원천을 확인하며 별도 묶음으로 비교한다. 이번 조건 탐색의 관계를 고정 초 환산이나 가점으로 적용하지 않는다.

이번 작업은 입력 후보 발굴까지다. 모델 학습·재보정·운영 모델 변경·DB 변경은0회다.

## 검증과 원본

전체727개 통계 행을 조건 원장으로 독립 대조했고 저장 R1/HY 확률과 정답을 재연결했다. 최신 대상55출전의 당해 착순·전체시간만 교란해도21개 과거/선언 조건이 불변임을 확인했다. 과거 ID·같은 말·같은 거리·T−2 경계와 모델 확률합을 검증했고 날짜 구간 하나를 별도 집계 방식으로 재현했다. DB·등록부·운영 모델·원 예측 해시는 동일하다.

- [조건별 전체 표](outputs/condition_statistics.csv),[기간별 지원](outputs/period_totals.csv),[조건별 거리 분해](outputs/distance_condition_statistics.csv)
- [같은 운영 표본의 잔차](outputs/common_model_residuals.csv),[기간별 반복 전체](outputs/period_repetition.csv),[수치 오차와 상수 조건 검토](outputs/period_repetition_review.csv)
- [조건 원장과 이력 ID](outputs/condition_features.parquet),[최근 고입상률의 관측수 분해](outputs/high_recent_rate_history_support.csv)
- [원천 해시](outputs/source_lock.json),[전체 검증](outputs/analysis_verification.json),[독립 검산](outputs/independent_verification.json)
- [현재 R1 연구](../20261009_field_relative_ability_v1/README.md),[운영 비교](../20261009_operating_model_comparison_v1/README.md),[기존 중량 연구](../20261008_weight_speed_v2/README.md)
'''
(HERE/'README.md').write_text(report)
backup=HERE/'publication_before';backup.mkdir(exist_ok=False)
names=['README.md','SOURCES.md','research_register.json','source_manifest.json']
before={}
for name in names:
    p=CENTRAL/name;before[name]=dict(sha256=sha(p),bytes=p.stat().st_size);shutil.copyfile(p,backup/name)
conclusion=CENTRAL/'11_TOP3_CONDITION_PROFILES.md'
assert not conclusion.exists()
conclusion.write_text('''# 제주마 입상 조건과 미반영 정보 탐색

2017~2026년9월19일52,155출전·5,206경주의 입상15,618출전과 비입상36,537출전을 함께 비교했다.21개 조건군·727조건기간 표다. 기존 정상 완전 편성·T−2 계약을 유지한 후향 탐색이며 운영 반영은 없다.

2026년 직전Top3 말1,418출전의 다음 입상률은43.51%,직전7위 이하1,644출전은20.13%였다. R1예측은37.90%/25.91%로 성적 차이를 작게 반영했다. 직전Top3 관측−예측은2024~25 +6.93%p(날짜95% +5.53~+8.29),2026 +5.62%p(+3.83~+7.41)다. 여러 조건을 본 점별 탐색 구간으로 추가 예측 개선의 확증은 아니다.

상대기록 상위1/4의2026년 실제42.34%/R1예측42.39%는 이미 근접했다. 같은 상위기록 안에서도 직전입상/7위 이하의 입상률은52.69%/28.11%였다. 직전 성적·최근 동일거리 입상비율과 실제 관측수를 작게 추가해 검증할 후보로 둔다. 임의 가점·통계 입상률 복사는 하지 않는다.

최근 동일거리 입상률80%이상485출전의2026년 입상률49.90%는1회 이력이239출전을 차지한다.5회 창100출전의 실제는37.00%다. 고입상률을 반복 능력으로 바로 해석하지 않는다. 증량군의 높은 원시 입상률도 좋은 성적·배정과 얽힐 수 있어 증량의 유리한 인과 효과로 설명하지 않는다.

운영 공통467경주 중 직전Top3집단1,363출전은 실제43.80%,R1예측37.87%,HY_R_FORM43.94%였다. 학습 기간·다른 입력 차이가 있어 직전착순 한 변수의 기여로 분리하지 않는다. 나이·경력·간격·기록·거리·원문등급·선언 가정 부담·번호와4개조건 조합을 모두 보존했다. 기수·구간·조교·주행심사의 확대는 후속이다.

입상마에게 흔한 조건P(조건|입상)과 해당 조건의 입상률P(입상|조건)을 분리한다. 사후 완전 편성 모집단·역사적 최초공개 미확정·희소거리·동일말 반복·다중탐색 한계가 있다. 모델 학습·재보정·운영 변경·DB 변경은0회다.

[전체 결과와 방법](../20261009_top3_condition_profiles_v1/README.md),[결과 전 계약](../20261009_top3_condition_profiles_v1/CONTRACT.md),[독립 검증](../20261009_top3_condition_profiles_v1/outputs/independent_verification.json).
''')
p=CENTRAL/'README.md';s=p.read_text();needle='| [원 연구와 버전 목록](SOURCES.md)';assert needle in s
p.write_text(s.replace(needle,'| [입상 조건과 미반영 정보](11_TOP3_CONDITION_PROFILES.md) | 입상·비입상 조건 비교에서 직전 성적·최근 입상비율과 관측수 후보 | 통계 탐색 완료, 추가 모델 효과 미검증 |\n'+needle))
p=CENTRAL/'SOURCES.md';p.write_text(p.read_text()+'\n- [20261009_top3_condition_profiles_v1](../20261009_top3_condition_profiles_v1/README.md): 입상·비입상52,155출전의21개 조건군·727개조건기간 통계,조건부 입상률과R1/HY잔차,관측수 반례·T−2·정답교란 검증. 직전 성적 보강 후보, 모델 추가 효과 미검증.\n')
p=CENTRAL/'research_register.json';reg=json.loads(p.read_text());reg['topics'].append(dict(id='top3_condition_profiles',title='입상 조건과 모델 미반영 정보 탐색',conclusion=conclusion.name,latest_source='../'+HERE.name+'/README.md',period_start='2017-01-13',period_end='2026-09-19',partial_2026=True,rows=52155,races=5206,condition_families=21,condition_period_rows=727,status='exploratory_candidates_previous_finish_and_recent_top3_with_support',additional_model_effect_tested=False,operationally_applied=False))
save(p,reg)
changed=[CENTRAL/n for n in names if n!='source_manifest.json']+[conclusion]
links=0
for p in [HERE/'README.md',HERE/'CONTRACT.md',conclusion]:
    for ref in re.findall(r'\]\(([^)]+)\)',p.read_text()):
        if '://' in ref or ref.startswith('#'):continue
        assert (p.parent/ref.split('#')[0]).exists(),(p,ref);links+=1
save(OUT/'publication_verification.json',dict(passed=True,local_links_checked=links,previous_documents_preserved=before,
    central_files={str(p.relative_to(ROOT)):dict(sha256=sha(p),bytes=p.stat().st_size) for p in changed},
    input_candidates_only=True,fits=0))
p=CENTRAL/'source_manifest.json';manifest=json.loads(p.read_text())
paths=changed+[x for x in HERE.rglob('*') if x.is_file() and x.name!='ARTIFACT_INVENTORY.json']
updates={str(x.relative_to(ROOT)):dict(path=str(x.relative_to(ROOT)),role='top3_condition_profiles' if x.is_relative_to(HERE) else 'conclusion_or_management',sha256=sha(x),bytes=x.stat().st_size) for x in paths}
manifest['files']=[updates.pop(row['path'],row) for row in manifest['files']]+list(updates.values())
manifest['updated_at']='2026-10-09';manifest.setdefault('verification',{})['top3_condition_profiles']='20261009_top3_condition_profiles_v1/outputs/independent_verification.json passed'
manifest['managed_files_bytes_excluding_this_manifest']=sum(row['bytes'] for row in manifest['files']);save(p,manifest)
inventory={str(x.relative_to(HERE)):dict(sha256=sha(x),bytes=x.stat().st_size) for x in HERE.rglob('*') if x.is_file() and x.name!='ARTIFACT_INVENTORY.json'}
save(HERE/'ARTIFACT_INVENTORY.json',dict(files=inventory,files_count=len(inventory),total_bytes=sum(v['bytes'] for v in inventory.values())))
for path,info in inventory.items():assert sha(HERE/path)==info['sha256']
print(json.dumps(dict(passed=True,files=len(inventory),bytes=sum(v['bytes'] for v in inventory.values()),local_links_checked=links),ensure_ascii=False))
