"""Readable research conclusions with explicit separation of performance and intent."""
import json
import pandas as pd
from data import HERE,save

def main():
 a=pd.read_csv(HERE/'input01/starts.csv',low_memory=False)
 c=pd.read_csv(HERE/'closing01/effects.csv');s=pd.read_csv(HERE/'switch01/effects.csv');r=pd.read_csv(HERE/'switch01/raw_results.csv');st=pd.read_csv(HERE/'styles01/current_riders.csv').fillna('')
 rows=[]
 for x in st.sort_values('name').itertuples():
  rows.append(f'| {x.name} | {x.starts_2026:,} | {x.raw_first_pack_pct:.1f}% | {x.first_pack_2024_2025_effect:+.1f} | {x.first_pack_2026_effect:+.1f} | {x.label} |')
 raw=[]
 for period in ['2024_2025','2026']:
  for group in ['upgrade','other_change','retained']:
   x=r[(r.period==period)&(r.variant=='same_relations')&(r.group==group)].iloc[0]
   raw.append(f'| '+('2024~2025' if period=='2024_2025' else '2026~09-19')+' | '+{'upgrade':'상향교체','other_change':'그 외 교체','retained':'기수 유지'}[group]+f' | {x.starts:,} | {100*x.previous_top3:.1f}% | {100*x.raw_top3:.1f}% | {100*x.H0_expected_top3:.1f}% | {100*x.H1_expected_top3:.1f}% |')
 adjusted=[]
 for x in s[s.variant.eq('same_relations_changed')].itertuples():
  adjusted.append('| '+('2024~2025' if x.period=='2024_2025' else '2026~09-19')+' | '+{'H0_top3_excess':'기수 제외 예상 대비 Top3(%p)','H1_top3_excess':'기수 포함 예상 대비 Top3(%p)','H0_time_adv':'기수 제외 예상 대비 기록(초)','H1_time_adv':'기수 포함 예상 대비 기록(초)'}[x.target]+f' | {x.effect:+.3f} | [{x.date_low:+.3f}, {x.date_high:+.3f}] | [{x.horse_low:+.3f}, {x.horse_high:+.3f}] | '+('지지' if x.supported else '미확정')+' |')
 text='''# 말의 후반 수행과 상위기수 교체 및 기승 특성

2026-10-09. **성적이 좋은 기수로의 상향교체는 더 좋은 수행과 연결됐지만, 관계자가 의도한 승부경주인지는 확인할 수 없다.** 일반적인 기수 우세와 별개로 중단·후미 성향 말의 후반 능력을 특별히 살리는 기수는 최근 두 기간에 반복 확정하지 못했다. 현재 기승 특성은 박성광의 초반 첫집단 확보만 반복 지지되며 전 기수를 선행·선입·추입 전문으로 강제 분류하지 않는다.

## 기간과 원천

2017-01-13~2026-09-19 정상완주 완전 편성 52,155출전·5,206경주·2,813두·기수 40명. 현재 대상 800·900·1000·1110·1200·1300·1400·1610m, 400m·제외마3005648 제외. 2026년은 부분연도다. 기존 품질 선택값·T−2 최근 최대10/730일 이력과 [앞선 기수 연구](../20261009_jockey_effects_v1/README.md)의 연도 고정 H0/H1 예측을 재사용한다. 독립 표본이 아닌 후향 후속 분석이다.

공식 사건 말·기수·조교사 ID를 일치시킨 뒤 로컬 DB를 읽기전용 조회해 당시 마주 ID·이름과 payload SHA를 연결했다. 52,155건 일치, 마주 234개 ID, 마주 결측 0건이며 DB 전후 SHA가 같다. 현재 마주나 조교사를 과거에 소급하지 않았다. **누가 교체를 결정했는지, 교체 이유·협의 내용·승부 의도는 자료에 없다.** 조교사·마주 유지 분석은 동일 관계의 출전을 비교한다는 뜻이지 이들이 변경을 지시했다는 뜻이 아니다.

1300m는 출발→2C→S1F 순서, 괄호 내부는 내외측 순서이며 개별 확정 순위를 복원하지 않는다. G3F 시간은 마지막600m이며 통과조가 아니다. 보류된 구간·순위는 원시값으로 대체하지 않는다.

## 기수가 말의 추입력을 살리는가

엄격 추입형은 사전 중단·후미 반복과 과거 4C→G1F 확실2두 전진60%를 요구하는 기존 정의로 전체190·2024~2025년93·2026년29출전에 불과하다. 전진40% 민감도도 전체902·최근366·2026년106출전이다. 이 분모로 특정 기수의 추입 전문성을 확정하기 어렵다.

주분석은 T−2 유효 초반 이력5개·유효율60% 이상, 과거 확실 중단+후미60% 이상인 **대기 성향 말**을 사용했다. 전체9,994·2024~2025년2,609·2026년919출전이다. 이는 이미 추입력을 입증한 말만의 집단이 아니다. 과거 후반 전진 비율과 G3F 경주 내 상대순위도 통제해 말의 기존 후반 수행을 고려했다.

말×정확거리·경주 고정효과, 과거 수행·부담·체중·게이트·조교사에 기수 주효과와 기수×대기 성향 상호작용을 함께 넣었다. 다음 두 대비를 구분했다.

- 대기 성향 말에서 평균보다 좋은 기수의 **총 수행 차이**.
- 해당 기수의 일반적인 우세를 넘어 대기 성향에서 더 좋아지는 **특이적 차이**.

전체기간에는 전현준·문현진·김준호·박성광이 대기 성향 말에서도 빠른 기록 및 좋은 G3F 상대순위 방향을 보였다. 그러나 특이적 상호작용은 전체기간에서도 확정되지 않았고, **2026년에는 주 기준을 통과한 기수별 후반 우세가 없었다.** 일반적으로 잘 타는 것과 추입력을 특별히 살리는 것을 구분해야 한다.

임재광의 대기 성향 G3F 상대순위 우세 점추정은 2024~2025년 +9.0, 2026년 +19.9(순위분율×100)였지만 후기 전체 비교 후 BH q는 각각0.174·0.167이었다. 2026년 특이적 차이도 q=0.151로 미확정이다. 탐색 후보로 보존하며 추입 전문으로 확정하지 않는다. 이 단위는 초나 입상확률 %p가 아니다.

날짜·말 군집95% 구간과 BH를 사용했다. 후기 두 기간×4목표×전체 기수×두 대비를 하나의 주가족으로 보정했다. 최소 대기30출전·10일·15두 및 전체100출전·20일·30두를 요구한다. 두 후기기간 반복 지지된 추입 특화 기수는 없다. **추입력을 살리는 기수가 없다는 증명은 아니며**, 엄격 추입형의 소표본과 현재 자료로 확정하지 못한 결과다. [전체 효과·분모·구간](closing01/effects.csv), [엄격/40%/대기 성향 원시표](closing01/raw_style_results.csv)를 보존한다.

## 상위기수와 상향교체의 정의

해당 경주T−2까지 과거365일의 선정 출전100회 이상 기수만 평가한다. 그날 자격 기수의 Top3율75백분위 이상을 상위기수로 정하고, 그 기수로 바뀌면서 이전 기수보다 같은 과거창의 Top3율이5%p 이상 높으면 **상향교체**로 분류했다. 10%p 상승 민감도도 별도 보존했다. 이름·현재 순위·이후 결과로 상위를 정하지 않았다. 원시 성적을 사용하므로 좋은 말 배정과 최근 기수 폼이 포함된 정의다.

같은 말의 직전 선정 출전과2~90일인 쌍을 비교하며 거리 변경도 포함했다. 선정되지 않은 출전이 사이에 있을 수 있어 전체 실제 직전 출전이라고 단정하지 않는다. 양 기수 과거 성적 지원과 현재 H0/H1 예측이 있는 사례만 사용했다. 주비교는 **조교사와 마주가 모두 유지된 교체 중 상향교체 vs 그 외 교체**다. 그 외 교체에는 성적이 낮은 기수로 바뀐 경우도 포함돼 교체의 의도를 분리하는 대조군은 아니다.

## 원시 입상 변화

H0는 기수 ID 없는 말의 과거 수행·편성·조건 모형, H1은 같은 모형에 기수 ID를 더한 연도 고정 예측이다. 두 모형 모두 해당 연도 이전 자료로 학습했으나 관계자·부담·체중의 공개·변경 시각을 검증한 서비스 재생은 아니다.

| 기간 | 유형 | 출전 | 직전 선정 출전 Top3 | 현재 Top3 | H0 기대 Top3 | H1 기대 Top3 |
|---|---|---:|---:|---:|---:|---:|
'''+ '\n'.join(raw)+'''

상향교체의 2026년 실제 Top3는137/347=39.5%로, 직전 선정 출전28.5%보다 높았다. 그 외 교체는246/985=25.0%였다. 기수 유지 출전은 오히려 직전42.7%→현재34.1%여서 원시 전후 차이에는 부진 뒤 교체와 회귀평균도 섞여 있다. 이 원시표만으로 교체의 효과나 승부 의도를 판정하지 않는다.

## 기대수행과 조건을 고려한 비교

현재 실제−예상Top3(%p), 예상−실제 상대시간(빠른 방향 초)을 목표로 사용했다. 직전 입상·상대기록·H0예상오차, 현재 H0기대·과거 능력·공백, 거리·등급·부담·체중·함수율·게이트 변화, 연도·월·거리·조교사·마주 ID를 고려했다. 상향교체계수는 무벌점, 나머지 통제항은ridge1을 고정했다. 주비교8가설의 BH와 날짜·말 군집95% 구간을 보존했다.

아래는 **다른 교체에 비해 상향교체가 갖는 조정된 잔여 차이**다. 양수는 좋은 방향이며 고정 확률 가산이나 개별 기록 보정값이 아니다.

| 기간 | 목표 | 상향교체 차이 | 날짜95% 구간 | 말95% 구간 | 주 기준 |
|---|---|---:|---|---|---|
'''+ '\n'.join(adjusted)+'''

기수 정보를 제외한 기대 기준에서는 입상과 기록의 우세가 두 기간에 반복됐다. 기수 정보를 포함한 H1 기준에서도 기록은 각각 **+0.267초·+0.230초** 좋은 잔여 차이가 있었다. H1 입상 차이는2024~2025년 +10.1%p였지만2026년 +3.7%p의 날짜 구간이−3.1~+10.6%p로 넓어 반복 확정되지 않았다. 관계 변경 포함·상향 문턱10%p·기수 유지 대조에서도 기록 방향은 같았으나 별도 보조 비교이며 주가족의 추가 확정으로 세지 않는다.

**상향교체가 좋은 수행과 연관된다는 근거는 있지만, 준비된 승부경주라는 해석은 아직 검증할 수 없다.** 연도 고정 H1이 최근 기수 폼·최근 배정 차이를 충분히 반영하지 못했을 수 있고, 관측하지 못한 말의 준비 상태·기수 가용성·교체 사유가 남는다. H1 잔차가 좋아도 그것을 승부 의도의 순수 효과로 부를 수 없다. 이 비교의 집단 간 잔차 차이는 앞선 전체 예측의 MAE 개선량과 다른 지표다. 새 교체 신호의 예측 추가 개선은 이번에 학습·검증하지 않아 운영에 반영하지 않는다.

[교체별 전체 출전](switch01/eligible_pairs.csv), [원시표](switch01/raw_results.csv), [조정·민감도](switch01/effects.csv), [과거365일 성적과 상위 경계](input01/prior365_jockey_stats.csv)를 연결한다.

## 조교사와 마주별로는 어디까지 알 수 있나

사건 당시 관계자가 같은 상태의 상향교체 빈도와 결과를 [조교사·마주별 원표](switch01/relation_groups.csv)에 저장했다. 최소교체30·상향10을 만족한 조교사 ID는2024~2025년17개·2026년14개, 마주 ID는2024~2025년31개·2026년0개다. 최소 요건은 표를 보여줄 지원 기준이며 관계자별 인과효과나 유의성을 보장하지 않는다.

조교사별 원시 성과도 서로 달라 상향교체를 모든 조의 공통 승부 규칙으로 정할 수 없다. 2026년 마주별 표본은 더 작다. 특정 관계자를 ‘상위기수를 태우면 승부하는 사람’으로 분류하거나 순위를 매기지 않는다. 변경의 실제 결정자가 확인되지 않는다는 한계도 유지한다.

## 기수별 기승 스타일은 정했나

측정 축은 **초반 첫집단 확보·후반 확실 전진·G3F 상대 수행**으로 정했다. 현재100출전 이상17명 전원을 다음처럼 정리했지만 영구적인 선행·선입·추입 전문 명칭은 부여하지 않았다. 원시 첫집단 비율에는 기승마·게이트·거리 배정이 섞인다. 조정 차이는 말과 조건을 고려한 평균 대비%p다.

| 기수 | 2026 출전 | 원시 첫집단 | 2024~25 첫집단 차이(%p) | 2026 첫집단 차이(%p) | 현재 특성 상태 |
|---|---:|---:|---:|---:|---|
'''+ '\n'.join(rows)+'''

박성광의 첫집단 확보 +8.1→+18.1%p는 두 기간 모두 지지됐다. 임재광의 초반·후반 전진, 전현준·문현진·김홍권의 G3F 우세는2024~2025년 한정 신호이며2026년에 확정되지 않았다. 따라서 현재는 **박성광 초반 자리 확보 후보, 다른 기수는 기간 한정 신호 또는 미확정**이 적절하다. 첫집단은 단독 선행이나 선행 의도와 같지 않고, G3F 시간의 좋은 순위도 반드시 후미에서의 추입을 뜻하지 않는다.

[기수별 현재 표](styles01/current_riders.csv)에는 후반 지표·두 군집 구간·BH·분모도 보존했다. [전체 후기 특성 표](styles01/traits_full.csv)는 출전이 적은 기수까지 포함한다. 스타일·각질의 기간 변화 연구는 기존 저장 상태를 유지하며 이번 기수 후속으로 그 연구 전체를 재개한 것으로 표시하지 않는다.

## 재현과 검증

[사전 계획](PLAN.md), [입력 계보](input01/source_manifest.json), [입력](data.py), [후반 상호작용](closing.py), [교체](switch.py), [특성 정리](styles.py), [최종 검증](verify_v2.py)을 보존한다. [검증 결과](verification02/verification.json)는 이력·시점·상위기수 과거창·교체 정의·원시분모, FE정규방정식과 대비·군집구간, 교체 회귀의 별도 확장최소제곱 해·군집구간·BH·원천 불변을 확인한다. [최초 검증 중단](verification01/failure.json)은 CSV의 기간 열에서 정수/문자 혼합 추론으로 행 조회가 중단된 기록이다. 최종 검증은 문자열 자료형을 명시했으며 효과 추정·예측·원표는 바꾸지 않았다.

DB·운영 모델·공통 앱 변경은 없다. 정상완주 완전 편성의 선정 결과로 사고·중단 위험 전체를 대표하지 않는다. [중앙 기수 결론](../conclusions/08_JOCKEY_PROFILE.md)과 [연구 목록](../conclusions/README.md)에 저장한다. 파일별 보관 해시는artifact_manifest.json, 원본 불변·링크·크기 확인은publication_verification.json에 남긴다.
'''
 (HERE/'README.md').write_text(text)
 supported=c[c.direction_supported&c.period.eq('2026')]
 save(HERE/'decision.json',{'status':'closing_interaction_upgrade_and_riding_traits_followup_completed','source_starts':52155,'source_races':5206,'source_horses':2813,'source_jockeys':40,'source_owners':234,'source_through':'2026-09-19','partial_2026':True,
  'closing_specialist_repeat_supported':False,'closing_2026_supported_contrasts':len(supported),
  'upgrade_definition':'T-2 past365days min100 selected starts; Top3 >= eligible75th percentile and >= old rider +5pp',
  'same_relations_upgrades_2024_2025':919,'same_relations_upgrades_2026':347,'upgrade_H1_time_adv_2024_2025_s':0.2673362708056141,'upgrade_H1_time_adv_2026_s':0.2295491445353097,
  'upgrade_H1_top3_repeat_supported':False,'intent_directly_observed':False,'switch_decision_maker_observed':False,'upgrade_equals_intent_or_causal_preparation':False,
  'repeat_supported_early_first_pack_display_name':'박성광','permanent_tactic_labels_assigned':False,'new_switch_feature_forecast_gain_tested':False,'operationally_applied':False,'fixed_record_seconds_adopted':False,
  'effect_estimation_completed':True,'pure_jockey_ability_identified':False,'previous_style_study':'completed_saved_revisit_later_per_user'})
 # Use the saved numerical estimates rather than rounded display literals.
 d=json.loads((HERE/'decision.json').read_text())
 for period in ['2024_2025','2026']:d['upgrade_H1_time_adv_'+period+'_s']=float(s[(s.period==period)&(s.variant=='same_relations_changed')&(s.target=='H1_time_adv')].effect.iloc[0])
 save(HERE/'decision.json',d)
 print('Report saved',len(rows),'riders',flush=True)
if __name__=='__main__':main()
