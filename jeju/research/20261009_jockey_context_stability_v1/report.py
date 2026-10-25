"""Summarize all six predeclared research questions without forcing specialist labels."""
import pandas as pd
from data import HERE,OLD,save

def main():
 a=pd.read_csv(HERE/'input02/starts.csv',dtype={'jockey_id':str},low_memory=False)
 e=pd.read_csv(HERE/'effects02/jockey_effects.csv',dtype={'period':str,'jockey_id':str});m=pd.read_csv(HERE/'forecast01/metrics.csv',dtype={'period':str});c=pd.read_csv(HERE/'forecast01/comparisons.csv',dtype={'period':str})
 profiles=[]
 for kid,g in a[a.year.eq(2026)].groupby('jockey_id'):
  if len(g)<100:continue
  r={'jockey_id':kid,'name':g.jockey_display_name.iloc[0],'starts_2026':len(g),'outer_starts_2026':int(g.outer.sum()),'pressure_eligible_2026':int(g.pace_eligible.sum()),'pressure_starts_2026':int((g.pace_eligible&g.pressure).sum()),'big_slow_count_2026':int(g.big_slow.sum()),'raw_big_slow_pct_2026':100*g.big_slow.mean()}
  for topic,target,contrast in [('outer','first_pack','context_effect'),('outer','first_pack','context_specific'),('pace','fade3','context_specific'),('pace','g3f_rank','context_specific'),('pace','time','context_specific'),('stability','big_slow','jockey_effect'),('stability','absolute_error','jockey_effect')]:
   for period in ['2024_2025','2026']:
    z=e[(e.topic==topic)&(e.target==target)&(e.contrast==contrast)&(e.period==period)&(e.jockey_id==kid)]
    if not len(z):continue
    prefix='_'.join([topic,target,contrast,period]);v=z.iloc[0]
    for col in ['effect','date_low','date_high','horse_low','horse_high','BH_q','support','direction_supported']:r[prefix+'_'+col]=v[col]
  r['previous_repeat_trait']='초반 첫집단 확보 반복 후보' if g.jockey_display_name.iloc[0]=='박성광' else '앞선 기수 특성표 참조'
  r['new_context_specialist_label']='미확정'
  profiles.append(r)
 pd.DataFrame(profiles).to_csv(HERE/'current_rider_profiles.csv',index=False,encoding='utf-8-sig')
 comparisons=[]
 for r in c.itertuples():
  comparisons.append('| '+('2024~2025' if r.period=='2024_2025' else '2026~09-19')+' | '+{'D1-H1':'거리 추가','R1-H1':'최근 폼 추가','T1-H2':'조교사×기수 추가'}[r.comparison]+' | '+('MAE(초)' if r.metric=='mae' else 'Top3 logloss')+f' | {r.delta:+.6f} | [{r.date_low:+.6f}, {r.date_high:+.6f}] | [{r.horse_low:+.6f}, {r.horse_high:+.6f}] | {r.BH_q:.3f} | '+('개선 지지' if r.supported_improvement else '개선 미확정')+' |')
 metricrows=[]
 for r in m.itertuples():metricrows.append('| '+('2024~2025' if r.period=='2024_2025' else '2026~09-19')+f' | {r.model} | {r.starts:,}/{r.races:,} | {r.mae_s:.6f} | {r.rmse_s:.6f} | {r.logloss:.6f} | {r.brier:.6f} |')
 text='''# 기수의 초반 확보 경합 대응 수행 안정성과 조건별 추가 정보

2026-10-09 완료. **외측 전문·경합 대응·부진 방지 기수를 최근 두 기간에 반복 확정하지 못했다. 최근 기수 폼은2024~2025년 예측을 작게 개선했지만2026년에는 불확실했다. 기수×거리와 조교사×기수의 별도 항목도 반복 개선이 없었다.** 기존 연구의 기수 기본 정보와 박성광 초반 확보 후보는 유지하며 이번 결과로 조건별 고정 가중치·전문 태그를 추가하지 않는다.

## 여섯 질문의 결과

| 질문 | 관찰 결과 | 연구 결정 |
|---|---|---|
| 외측 초반 자리 확보 | 전체기간 외측에서도 좋은 기수는 있으나 일반 초반 우세를 넘는 외측 특화의 최근 반복 근거 부족 | 외측 전문 태그 미확정 |
| 선행형 경쟁 편성의 후반 유지 | 박성광의2024~2025년 상대시간 우세는 있지만2026년 반복·특이적 경합 대응은 미확정 | 페이스 조절 전문 태그 미확정 |
| 큰 부진 방지·수행 안정성 | 원시 빈도는 다르지만 말·조건·기대수행을 고려한 기수 차이는 최근 반복 미확정 | 부진 방지 순위 미확정 |
| 거리별 기수 강점 | 기수×정확거리 항목의 이후 예측 추가 개선 미확정 | 거리별 별도 가중치 미채택 |
| 최근 기수 폼 | 90/180/365일 기대초과 수행 추가로2024~2025 개선,2026 불확실 | 보조 연구 후보 유지 |
| 조교사×기수 조합 | 기존 가산 모형보다 반복 추가 개선 없음 | 별도 조합 항목 미채택 |

‘미확정’은 기수 간 차이가 없거나 어떤 기수도 잘하지 못한다는 뜻이 아니다. 현재 자료·고정 모형·표본과 다중비교 기준에서 일반화할 근거가 부족하다는 결과다.

## 기간과 원천

2017-01-13~2026-09-19 정상완주 완전 편성52,155출전·5,206경주·2,813두·기수40명.2026년은 부분연도다.800·900·1000·1110·1200·1300·1400·1610m,400m와 제외마3005648 제외를 유지했다. [앞선 기수 기본 연구](../20261009_jockey_effects_v1/README.md), [추입·교체 연구](../20261009_jockey_closing_switch_v1/README.md)의 품질 원천·공식 ID·T−2 최근 최대10회/730일 이력과 연도 고정 예측을 재사용했다.

1300m는 출발→2C→S1F 사용자 계약이다. 통과조 괄호는 내외측 순서이며 개별 순위로 복원하지 않았다. 보류·NULL을 원시값으로 대체하지 않았다. 과거 변수명 s1ftime/g3ftime의 이력값은 여기서 **경주 내 상대시간순위 분율**이며 초와 혼동하지 않는다. 현재 기수·조교사·부담·체중·주로의 공개·변경 시각을 검증한 서비스 재생은 아니고 사건 스냅샷 가용성을 가정한 후향 분석이다. DB 조회·쓰기·외부 수집·운영 변경은 없었다.

## 외측에서 초반 자리를 확보하는가

기존 게이트 비율>2/3를 외측으로 고정했다. 외측 출전은 전체16,156·2024~2025년3,870·2026년1,433건이며 지표별 품질 유효 분모는 원표에 따로 보존했다. 목표는 S1F첫집단과 앞두집단 이내다. 앞두집단은 개별 확정 선입 순위와 같지 않다.

말×정확거리·경주 고정효과, 과거 초반 능력과 첫집단 성향, 내외측의 빠른 상대 수·선행압력, 부담·체중·조교사, 거리별 게이트와 게이트×과거 초반 능력을 고려했다. **외측에서도 평균보다 잘하는 것**과 **그 기수의 일반 강점을 넘어 외측에서 특별히 더 잘하는 것**을 분리했다.

전체기간에는 박성광·임재광의 외측 첫집단 우세, 김홍권·박재희 등의 앞두집단 우세가 관찰됐다. 그러나 최근 두 기간에 반복 지지된 외측 특화의 긍정 차이는 없었다. 박성광의2026년 외측 첫집단 총차이 점추정은 약+20.3%p였지만 외측 특이적 차이는 약+3.9%p로 불확실했다. 앞선 기본 첫집단 +18.1%p 결과가 사라진 것이 아니라, **외측에 특화된 추가 능력이라는 더 좁은 질문은 확정되지 않은 것**이다. 이번 목표·대비 전체를 보정한 결과와 앞선 단일 목표 가족의 q값은 구분한다.

[전체 효과·구간·분모](effects02/jockey_effects.csv), [원시 조건표](effects02/raw_results.csv), [현재17명 프로필](current_rider_profiles.csv)을 보존했다. 원하는 위치나 선행 의도는 관측하지 못하므로 실제 자리 확보로 표현한다.

## 선행형이 많은 편성에서 끝까지 버티는가

사전 각질 가용률80% 이상 편성에서 본인을 제외한 선행형이2두 이상이면 경합가능 편성으로 정의했다. 해당 분석은 전체36,331출전 중 경합가능9,248,2024~2025년9,502 중2,283,2026년3,424 중698출전이다. 실제 경합 속도나 기수의 페이스 판단을 직접 관측한 값이 아니다.

현재 C4통과 순위 범위의 상한보다 최종착순이3두 이상 뒤면 확실 하락으로 정했다. 현재 C4전방에 있던 말만 먼저 골라 주분석하지 않았고, 첫집단·G3F 상대순위·최종시간과 함께 평가했다. 자기 과거 선행/선입/기타 성향·후반 수행과 상대 초반 압력을 통제했다.

전체기간 일부 기수의 좋은 수행은 있으나, 최근 주 기준을 통과한 긍정 결과는 박성광의2024~2025년 경합가능 편성 상대시간 약+0.644초 우세뿐이다.2026년에는 약+0.121초로 구간이0을 포함했다. 일반 기수 우세를 넘는 경합 특이적 차이와 확실 하락 방지·G3F 우세의 최근 반복 근거는 없었다. 박성광의2026년 경합가능 출전은52건이었다.

후미에서 출발하면 순위가 더 떨어질 여지가 적어 하락 빈도만으로 버티는 능력을 평가할 수 없다. 실제 C4전방 부분집합은 사후 선택 영향을 포함하는 원시 진단으로만 보존했다. 각질 가용률100%와 사전 전방 성향 원시표도 [조건표](effects02/raw_results.csv)에 있다. 이번 결과로 기수의 추진 기술·힘 안배·의도적 대기를 확정하지 않는다.

## 기대보다 크게 부진하는 경주를 줄이는가

연도 고정 H1(말의 과거 수행·조건+기수ID)의 예상 상대시간보다 실제 상대시간이 **1.5초 초과 느리면 큰 부진**으로 정했다. 경주평균 대비 상대기록의 기대 미달이며 절대 완주시간이1.5초 느려졌다는 뜻은 아니다.

- 2024~2025년:1,313/12,739출전, **10.3%**.
- 2026년:420/4,673출전, **9.0%**.

원시 기수별 비율은 다르지만 말×거리·경주 효과와 예상수행 수준·과거 능력·조건을 고려한 뒤 큰 부진 빈도·부진폭·절대오차의 반복 지지 기수는 없었다. 이 결과는 기수 차이가 없다는 증명도, 모든 기수가 같은 안정성을 가진다는 뜻도 아니다. 잔여 평균능력 차이·모형 오차·배정 선택도 빈도에 섞여 있어 순수한 분산 조절 능력으로 부르지 않는다.1.0/2.0초 원시 문턱 민감도와 현재17명의 분모·구간도 원표에 있다. 정상완주 선정 자료이므로 사고·중단 위험 전체를 평가한 결과가 아니다.

## 거리 최근 폼 조교사 조합은 예측을 더 좋게 하는가

2024·2025·2026년마다1월1일−2일까지 자료로 학습·전처리를 고정했다. 평가17,412출전·1,779경주는 모든 비교에서 동일하다. 상대시간 예측은 경주 내 평균0으로 중심화했고 각 경주에 같은 평가 가중치를 주었다. Top3는 개별 이진확률이며 확률 합계를3으로 강제한 공동착순 모형이 아니다.

- **H1:** 과거 말 수행·편성·조건+기수ID.
- **D1:** H1+기수×정확거리ID.
- **R1:** H1+기수의 과거90/180/365일 H0기대초과 상대시간·Top3잔차 평균과 관측수.
- **H2:** H1+말ID+조교사ID.
- **T1:** H2+조교사×기수ID.

최근 폼을 만들기 위한2018~2023년 H0도 각 연도 이전 자료로 학습했고2024~2026년은 기존 H0예측을 연결했다. 현재 경주T−2까지 창별 최소20/40/80관측,평균에 n/(n+50)축소를 적용했다.2017년 잔차와 지원 부족은 결측으로 남겼고 훈련 자료의 중앙값·결측 표시로 처리했다. 최근 원시 승률만으로 폼을 정하지 않았지만 배정과 선택을 완전히 제거한 순수 능력은 아니다.

Ridge alpha20·Logistic C0.3·최대3000회와 전처리를 고정했고 하이퍼 탐색은 하지 않았다. H1/H2 재적합은 기존 저장 예측과 일치했다.

| 평가 기간 | 모형 | 출전/경주 | MAE(초) | RMSE(초) | Top3 logloss | Brier |
|---|---|---:|---:|---:|---:|---:|
'''+ '\n'.join(metricrows)+'''

최근 폼의 MAE는2024~2025년0.940326→0.938899초로 약0.00143초 개선했고 Top3 logloss도0.560798→0.558643으로 개선했다.2026년 MAE는0.884533→0.884407초로 약0.00013초,logloss는0.569229→0.567696으로 좋은 점추정이었지만 양쪽 군집 구간과 BH 기준을 통과하지 못했다. **후기 두 기간에 확정된 반복 개선은 아니다.**

기수×거리의 MAE 변화는2024~2025년+0.000180초·2026년−0.000334초로 불확실했고 Top3 추가 개선도 없었다. 조교사×기수는 MAE가+0.003735초·+0.001212초로 나빠지는 점추정이며 반복 추가 개선이 없었다. 실제 거리 전문성이나 관계자의 협업이 없다는 증명이 아니라 이번 고정 항목을 더할 근거가 부족하다는 결과다.

아래는 추가−기준 차이로 **음수가 개선**이다. 날짜·말 군집4,000회 부트스트랩,3비교×2기간×2주지표의12가설 BH를 적용했다.

| 기간 | 추가항목 | 지표 | 변화 | 날짜95%구간 | 말95%구간 | BH q | 판단 |
|---|---|---|---:|---|---|---:|---|
'''+ '\n'.join(comparisons)+'''

[전체 평가](forecast01/metrics.csv), [차이와 구간](forecast01/comparisons.csv), [거리·조교사조합별 실제/기대와 지원](forecast01/distance_and_partnership_cells.csv)을 보존한다. 개별 셀의 최소50출전·15두·10일은 표 표시 지원이며 전문성의 통계적 확정 기준이 아니다. 이번 분석의 같은 과거 표본을 독립 검증으로 세지 않고 운영 모형을 승격하지 않는다.

## 현재 적용 범위

기존 기수 기본 정보의 작은 반복 예측 개선과 박성광의 기본 초반 확보 후보는 유지한다. 새 외측·경합·부진 방지 전문 태그, 거리별 기수 가중치, 조교사×기수 조합 항목은 추가하지 않는다. 최근 폼은 작은 부분기간 개선을 보인 연구 후보로 보존하며 확정 가중치를 부여하지 않는다. 기록에 고정 초나 입상확률을 가산하지 않는다.

이 결과는 말의 과거 수행을 중심으로 기수의 보조 정보를 평가하는 방향과 일치한다. 기수의 인과 능력·관계자의 승부 의도·기승 의도는 분리 확인하지 못한다. 기존 각질·편성 연구의 저장 후 추후 재개 상태는 유지한다.

## 재현과 검증

[사전 계획](PLAN.md), [최종 입력](data_v2.py), [입력 계보](input02/source_manifest.json), [최종 설명 모형](effects_v2.py), [시간순 예측](forecast.py), [최종 검증](verify_v2.py), [검증 결과](verification02/verification.json)를 보존한다. 원천·정의·자기 제외·시점·기수 대비·FE정규방정식과 군집 구간,연도별 전처리·予測 재계산,최근 폼 창과축소·지표·부트스트랩·BH를 확인했다.

최초 입력은 저장된 외측 빠른 상대 열이 없어 [중단 기록](input01/failure.json)을 남겼고 총 빠른 상대−내측 빠른 상대의 보존값으로 계산했다. 최초 설명 모형은 사전 계획의 선행/선입 분리를 명시하는 선행형 지시변수를 보강한 [effects02](effects01/correction.json)로 대체했다. 최초 검증은 부트스트랩 검사에서 인덱스를 열로 찾은 [중단 기록](verification01/failure.json)을 보존하고 계수·예측을 바꾸지 않은 최종 검사로 수정했다. 가설·문턱·하이퍼는 바꾸지 않았다. 전체 원본은 삭제하거나 덮어쓰지 않았다.

[중앙 기수 결론](../conclusions/08_JOCKEY_PROFILE.md), [연구 목록](../conclusions/README.md)에 함께 저장한다. 파일별 SHA·크기는artifact_manifest.json,최종 원본 불변·링크·크기는publication_verification.json에 남긴다.
'''
 text=text.replace('予測 재계산','예측 재계산')
 (HERE/'README.md').write_text(text)
 repeat={}
 for topic in ['outer','pace','stability']:
  z=e[e.topic.eq(topic)&e.period.ne('all')&e.direction_supported&e.effect.gt(0)]
  ids=z.groupby(['jockey_id','target','contrast']).period.nunique();repeat[topic]=int(ids.eq(2).sum())
 improvements={key:bool(c[c.comparison.eq(key)].supported_improvement.all()) for key in ['D1-H1','R1-H1','T1-H2']}
 save(HERE/'decision.json',{'status':'six_jockey_context_questions_completed','source_starts':52155,'source_races':5206,'source_horses':2813,'source_jockeys':40,'source_through':'2026-09-19','partial_2026':True,
  'effect_estimation_completed':True,'pure_jockey_ability_identified':False,'jockey_ranking_estimated':False,
  'repeat_supported_positive_context_contrasts':repeat,'distance_repeated_forecast_gain':improvements['D1-H1'],'recent_form_repeated_forecast_gain':improvements['R1-H1'],'trainer_jockey_repeated_forecast_gain':improvements['T1-H2'],
  'recent_form_improvement_2024_2025_only':True,'large_shortfall_threshold_relative_seconds':1.5,
  'new_specialist_labels_assigned':False,'fixed_record_seconds_adopted':False,'operationally_applied':False,
  'previous_repeat_supported_first_pack_candidate':'박성광','previous_style_study':'completed_saved_revisit_later_per_user','final_inputs':'input02','final_effects':'effects02','final_verification':'verification02'})
 print('Report saved; profiles',len(profiles),'repeat contrasts',repeat,flush=True)
if __name__=='__main__':main()
