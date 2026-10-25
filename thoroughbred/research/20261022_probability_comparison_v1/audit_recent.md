# 최근 부산 연구 감사와 제한 확률실험 권고

작성: 2026-10-22 KST. 범위는 더러브렛 연구 57G–57K와 관련 코드·검증 산출물이다. 제주, 운영·DB·게시 변경은 검토·수행하지 않았다. 이 감사는 저장된 결과를 읽어 설계 한계를 정리했으며 새 학습이나 실제 경주 재평가는 하지 않았다.

## 앞선 연구에서 확인되는 것

57G의 `prepare.py`는 부산 확정 출전자료에서 정상완주 133,755행을 만들었고 그중 구간값 완전행은 133,733개다. 각 말의 거리별 평균을 100으로 둔 구간지수와 역사적 스타일은 구간 배분을 설명하는 자료다. 이 지수는 경주 간 능력척도나 확률이 아니다. 과거 이력은 대상 경주보다 앞선 출전만 사용하며 무효 슬롯을 뒤로 채우지 않는다. `evaluate.py`의 B0–B3은 정상완주자 6두 이상 1,976경주에서 같은 LightGBM 회귀기를 쓴 상대완주기록 비교다. 기준 B0의 축 1두 Top3는 1,158/1,976(58.60%), B3는 1,162/1,976(58.81%)였다. 전체 차이의 paired 95% 구간은 +0.202%p, [-0.860, +1.257]로 0을 포함한다. 다만 B3−B2의 Top3 구간은 +0.759%p, [+0.101, +1.427]로 0을 포함하지 않는다. 이는 여러 탐색 대비 중 하나이고 B0 대비 일관된 승식·확률 개선을 입증하지 않는다. B2의 기록오차 우위도 Top3 선택 성능과 같은 목표가 아니다. `outputs/verification.json`은 133,755행, 12개 모델 replay, 최대 예측오차 0, 엄격한 과거이력 사용을 확인한다.

57H는 57G의 저장 예측을 재사용해 1976개 경주에서 바뀐 축 선택만 분류했다. 전체 추가모형 교체는 2024년 16회복/24상실(순 -8), 2025년 29/27(+2), 2026년 22/12(+10)으로 연도 방향이 달랐다. 2024를 9월 18일까지 줄여도 -7이다. 1300m 5등급의 2026년 회복은 사후 선택된 작은 하위집단이며 독립 경주·말 표본이 아니고, 주요 조건 구간은 0을 포함한다. 2024년에 고정한 모델을 2026년에 적용했을 때도 +6이어서 최근 반전만 모델 재학습 탓이라고 할 수 없다. 검증 JSON은 0회 신규 적합, 저장모델 replay 오차 0을 확인한다. 이 분석은 조건 진단이지 전향 규칙이나 원인 설명이 아니다.

57I의 첫 통과 선두 묶음은 경주가 시작된 뒤 관측하는 값이다. 정상완주 완전편성 5,891경주에서 말 단위 입상률은 첫 묶음 1두일 때 63.07%, 2두일 때 56.57%, 3두 이상일 때 41.13%였고, 첫 묶음 2두의 동반 Top3 비율은 별도 집단 집계 29.48%다. 이 값은 거리·등급·전략 구성과 함께 변하며 사전 예측 특성이나 가산 확률이 아니다. 1,500m는 표본이 없고 1,900/2,200m 및 일부 거리·두수 조합은 작다. 검증 JSON은 66,240개 원 API 결과, 2,145개 집계셀, 동착 보존, 말 단위와 묶음 단위 분모 분리를 확인한다.

57J는 세부 101입력 baseline B와 이력 직접추가 D, 선두 묶음 사전예측 I, 두수 공동 재가중 J를 비교했다. 첫 선두 후보가 실제 첫 묶음에 들어간 비율 73.18%는 해당 후보 포착률이지 전체 묶음 또는 최종 입상 확률이 아니다. 축 Top3는 B 58.81%, D/I 60.27%, J 60.02%이고 복승 1조합은 각각 10.78%, 11.18%, 11.34%, 11.44%였다. 주 대비 신뢰구간은 0을 포함하며 2026의 J는 B보다 축 +2경주, 복승 -5경주다. D→I 비교는 추가한 예측 전개 입력 효과로 제한해서 해석할 수 있지만 B→D는 여러 정보를 함께 넣은 대비다. 코드에서 J는 두수 범주를 재가중하므로 말의 상대적 선두 순서를 바꾸지 않는다. 검증 JSON은 현재 경주 실제 전개 제외, 과거 연도 예측 전달, 30개 모델 replay 오차 0을 확인한다. 여전히 정상완주 조건부다.

57K는 관측 누락에 따른 선택편향을 보여 준다. 비정상 착순의 G1F 누락률은 82.14%, 정상 착순은 1.19%라 결측을 느린 성적이나 탈락으로 채우면 안 된다. 모델 평가는 6두 이상 정상완주 1,976경주 조건부이고 비완주 위험을 예측하지 않는다. H에서 S로 종반 경로를 추가한 축 변화는 +4경주, 복승 +3으로 구간이 0을 포함했다. 개별쌍 PB에서 관계쌍 PF로 바꾸면 축 +2, 복승 -1, 복연 1조합 -18경주였다. 복연 1조합 적중률은 26.42%에서 25.51%로 세 연도 모두 낮았다. 새 말·쌍 이진 분류기의 출력은 완전한 경주 순위 공동분포가 아니므로 임의 score 합이나 product를 승식 확률로 부르면 안 된다. 검증 JSON은 47개 모델 replay, 107,378개 쌍 이벤트, 11,856개 경주-모델 선택 및 과거이력 불변성 검사를 확인한다.

따라서 57G–57K는 구간·전개 이력 후보를 좁히고 위험을 설명하는 근거다. 이 연구들은 현재 제한실험의 저장 binary Top3 모델과 평가 대상이 다르고, 공통된 정확 순위확률을 제공하지 않는다. 후향 성적은 반복 열람한 2024–2026 데이터이며 새로운 미사용 시험표본으로 부르지 않는다. 2026은 9월 18일까지만 있다.

## 비교 단위와 모델 입력 감사

20261009 `gate_front_late` 코드를 확인했다. `full103`의 대상은 3두 Top3 포함 이진값이며, 저장 family의 Busan 평가연도별 모델은 2024/2025/2026 각 target3 한 개다. `verify.py`의 18개 finish-model 수는 3 variant × 2 경마장 × 3연도다. 이전 초안의 “부산 full103 target1과 target3 각각 3개”는 잘못 읽은 것이므로 정정한다. 이 모델의 runner raw score는 개별 말 확률이 아니지만, 3두 조합마다 세 점수 합을 이전 교정연도 온도로 나눠 softmax한 기존 `target_probability`는 합이 1인 조합분포다. 해당 분포에서 Top3 주변확률 합은 3이다. 이는 축/복승/복연까지 이어지는 순서분포를 주지 않으므로, 공통 순서 모형을 더해 승식확률을 일관되게 주변화할 필요는 있다.

메인 `PLAN.md`의 고정 변형은 능력22 A, 초반 묶음 E=47, 종반 묶음 L=66, 합집합 EL=89, 기존 full103 F, 제한 동반관계 full103 FP다. 동일 경주·출전행을 유지하고 A/F의 저장모델을 재사용한다. E/L/EL은 사전 고정된 입력 블록의 추가효과를 본다. 삭제 대비에서 입력 열뿐 아니라 그 열을 직접 또는 간접 생성한 모든 의존 열도 제거해야 한다. 특히 front 보조확률은 종전초반·각질만의 효과로 부르지 말고 F−EL은 통합 14개 입력 묶음의 차이라고 표기한다. late 이력은 과거 초반 역할로 층화한 이력이다. 평가 표본·모형 선택·축/복승/복연 조합 정책은 모든 후보에 공통이어야 한다.

순서 공동분포는 먼저 `q(T)`를 모든 3두 집합에서 계산하고, 실제 선택된 3두 안에서는 같은 말 score의 Plackett–Luce(PL) 순서를 조건부 배분한다. 그 뒤 각 승식 주변확률은 전체 순서질량을 합산한다. raw score, pair feature, 순서 score 합이나 곱 자체는 확률이 아니다. 정규화 항등식은 필요한 내부 일관성이지 보정 성능의 증거가 아니므로 Brier/NLL 및 실제 선택조합의 보정을 별도로 평가해야 한다. PL 순서가 Top3 포함 score와 같은 score를 쓰는 구조가 실제 순위를 충분히 나타낸다는 보장도 없으므로 이전 연도 조건부 순서 NLL로 온도를 보정하고 다음 평가연도는 손대지 않아야 한다.

## 제안한 제한 실험과 보완 조건

고정된 여섯 변형 외 새 조합이나 거리·등급별 선택 규칙은 추가하지 않는다. A/E/L/EL의 2×2 비교는 초반·종반 블록의 단독/공동 추가를 구분한다. F−EL은 현 full103 추가 통합블록의 비교다. FP−F는 세 pair 특성에 대한 상호작용 계수만 다루며, 축/복승 악화 없이 복연 개선이 있는지 별도의 사전 조건부 신호로 보고한다. 가능한 모든 입력 제거는 의존열까지 함께 제거하고, 후보 선정·early stop은 평가 연도보다 앞선 분할에서만 한다. 새로운 학습횟수와 조합 수는 PLAN의 상한을 넘기지 않는다.

FP의 각 쌍 특성은 (1) 두 말의 과거 front gate 예측확률 곱, (2) 둘 중 낮은 과거 G3F 상대 순위, (3) 둘 중 낮은 과거 G1F 상대 순위로 고정한다. 빠른 시간이 좋은 방향이 되도록 음의 시간으로 순위를 만들고, 관측말 수 `nobs` 안 평균동률순위 `r`를 `2*(r-.5)/nobs-1`로 중심화한다. 늦은 구간은 둘 다 관측됐을 때만 계산하고 한쪽이라도 없으면 0 기여다. 각 3두 조합의 각 열은 세 쌍 특성의 평균이다. race 내 모든 조합에서 열을 상수만큼 중심화하는 선택은 softmax를 바꾸지 않는다. 현재 API 정의에서 결측→0은 중앙 rank 또는 실제 확률 0과 구분되지 않으므로, 결측률과 관측 지원은 함께 기록하고 점수 해석에 유의한다. 추가 결측 지시자나 다른 순위 정의를 결과를 보고 탐색하지 않는다.

`fit_pair_beta`는 저장 점수와 기본 온도를 고정한 채 이전 교정연도에서만 평균 3두 집합 NLL + 0.5×0.01×||beta||²를 최소화하고, 시작값 0·계수 범위 [-2,2]·최대 100회 조건을 지킨다. `fit_order_temperature`도 각 경주 안 실제 1·2·3위 순서의 조건부 PL NLL을 경주 동일가중으로 최소화한다. 결과가 없는 동착·복수 1/2/3위 또는 1·2·3위 중 하나가 빠진 경주는 이 3자리 proper likelihood에 쓰지 말고 후보 공통으로 제외 수와 이유를 공개한다. 행 결과를 추측으로 단일 순위에 재매핑하면 안 된다. 가능한 비완주·실격 출발자는 0 target 대안으로 유지하고, 정상완주만 남긴 별도 sensitivity와 주 cohort를 구분한다. 경주가 취소/출발 제외된 경우는 실제 출발자 모집단에서 같은 방식으로 제거한다.

확률 일관성은 각 경주의 순서질량 합=1, `sum(win)=1`, `sum(top2)=2`, `sum(top3)=3`, 비순서 복승쌍의 확률 합=1, 비순서 복연쌍의 확률 합=3, 복승 행합=말별 Top2, 복연 행합=2×말별 Top3, `win≤top2≤top3`, 복승≤복연≤각 말 Top3를 테스트한다. 쌍 행렬은 대칭·대각 0이어야 한다. 이 항등식이 깨지면 평가 전에 구현 오류로 중단한다. 축은 Top3 주변확률 최대 말 한 마리, 복승/복연은 전체 말쌍 확률의 상위 1·3개로 선택한다. 복연 3조합은 의존 사건이라 확률을 단순 합하지 말고 공동 순서분포에서 union 확률과 실제 적중 수 분포를 계산한다.

PLAN의 2024–2026 평가는 후향 개발평가로만 라벨링한다. 날짜 단위 paired bootstrap은 후보 간 차이의 불확실성을 보여 주되 사후 반복 조회를 새 test로 승격하지 않는다. 고정된 전체 기준을 동시에 충족하지 못하면 “개선 미확인”으로 종료하며 새 조건·가중치 탐색을 이어가지 않는다. 실제 미사용 증거는 freeze 뒤 도착하는 향후 경주뿐이다. 수익성, 비완주 위험, 전체 경마 모집단 밖 성능은 이 설계로 주장할 수 없다.

## 출처

- 57G: `thoroughbred/research/20261021_busan_all_distance_profiles/{PLAN.md,README.md,prepare.py,evaluate.py,verify.py,outputs/verification.json}` 및 `thoroughbred/research/conclusions/57G_BUSAN_ALL_DISTANCE_PROFILES.md`.
- 57H: `thoroughbred/research/20261021_busan_profile_gain_loss/{PLAN.md,README.md,analyze.py,verify.py,outputs/verification.json}` 및 `thoroughbred/research/conclusions/57H_BUSAN_PROFILE_GAIN_LOSS.md`.
- 57I: `thoroughbred/research/20261021_busan_leader_pack_outcomes/{PLAN.md,README.md,analyze.py,verify.py,outputs/verification.json}` 및 `thoroughbred/research/conclusions/57I_BUSAN_LEADER_PACK_OUTCOMES.md`.
- 57J: `thoroughbred/research/20261021_busan_joint_pace_stack/{PLAN.md,README.md,experiment.py,verify.py,outputs/verification.json}` 및 `thoroughbred/research/conclusions/57J_BUSAN_JOINT_PACE_STACK.md`.
- 57K: `thoroughbred/research/20261021_busan_late_survival_pairs/{PLAN.md,README.md,metrics.py,train.py,verify.py,outputs/verification.json}` 및 `thoroughbred/research/conclusions/57K_BUSAN_LATE_SURVIVAL_PAIRS.md`.
- Full103 조합분포 생성·검증: `thoroughbred/research/20261009_gate_front_late_v1/{PLAN.md,config.json,run.py,verify.py,outputs/verification.json}`. 이번 frozen test matrix: `thoroughbred/research/20261022_probability_comparison_v1/{PLAN.md,config.json}`.

## 추가 입력 시점·원천 추적

이 항목은 saved feature를 만든 upstream provenance만 확인한다. 모델 replay/학습 감사를 다시 수행하지 않았으며 기존 verification JSON의 보장 범위를 넘겨 해석하지 않는다. 요청에 적힌 profile-environment 코드는 실제 저장소 경로가 `20261008_profile_environment_ablation_v1/run.py`다.

`20261009_gate_front_late_v1/run.py`는 `prepare()`에서 이전 22-feature 표본을 `prepared_features`로 받고, `section_style_finish_v1/run.py`가 만든 178,497행 section/style history와 gate/profile 블록을 연결한다. `full103` 계약은 BASE 53개 + gate 12개 + profile 24개 + 상대 late 관계 12개 + front 보조확률/지원 2개다. `finish_features()`는 model contract에서 `outcome`, `aux_*`, `front_label`, jockey/trainer를 배제한다. `section_style_finish_v1/run.py`의 `prepare()`는 실제 현재 경주 `observations.parquet`로 `outcome`을 대체하지 않고, `aux_early`, `aux_recovery`, `aux_fade` 보조 목표만 만든다. `fit()`은 계약 열만 X로 인코딩하고 `outcome.between(1, 3)`은 y로만 쓴다. 현재 경주 결과와 현행 section split은 직접 입력으로 확인되지 않는다.

과거 profile·section·role 통계는 시간 차단이 코드에 있다. 기존 profile builder는 `cutoff_date = race_date - 2 days` 뒤 `merge_asof(..., direction="backward")`로 말 상태를 고르고 source date가 cutoff 이하인지 assert한다. `section_style_finish_v1/run.py`의 `slots()`도 각 target의 `cutoff_date` 이전 기록만 선택하고 최대 730일을 둔다. `historical_features()`는 그 슬롯에서 `section_{early,last600,late}`와 role/gain/recovery/fade 통계를 집계한다. `field_features()`와 `gate_features()`는 현재 출전행들을 서로 비교하지만 각 말의 비교 입력은 이 과거 요약값과 현재 gate/field-size 같은 카드 정보다. 따라서 이 feature들은 최종 출전 roster를 조건으로 만든 경주 내 값이지 실제 당해 경주의 결과·구간을 참조하는 값으로 보이지 않는다.

Section 보정의 연도 cutoff도 명시돼 있다. `section_style_finish_v1/run.py:environment()`는 보정 기준연도 Y마다 `prior = d[d.year < Y]`로 자른 뒤 이전 연도 전용 MAD4 마스크와 월·base/state gate 모델을 적합한다. 건조도 차이는 같은 월 모형의 과거 연도 관측에서 만들고, 사용 기준연도·source 최대일은 `complete.json`에 저장한다. 산출된 Y용 보정은 Y 연도 기록에만 적용한 후, target horse의 section feature를 만들 때 다시 `cutoff_date` 전 슬롯으로 제한한다. 이월 이전 기록에는 원 section 값이 유지된다. 그 상위 `20261008_profile_environment_ablation_v1/run.py:coefficients()`도 각 coefficient year에서 `d.year < year`를 fit population으로 하고, `trained_through=year-1`, `source_max_date`를 기록한다. `add_components()`와 `profile_frame()`은 연도별 보정 후보를 해당 연도 기록에 더하고, profile rolling 상태는 cutoff 이하 source date만 merge한다. 기존 JSON은 `coefficients_complete.future_coefficients_used=false`, profile-environment `verification.json`의 353개 chronology model 확인, section-style `verification.json`의 `chronology_verified=true`를 보고한다. 이는 기존 코드·고정 산출물에 대한 검증 재사용이지 이번 감사에서 새로 모델을 실행한 결과는 아니다.

Front auxiliary는 현재 경주에서 관측한 role을 `aux_early`/`front_label`이라는 과거 훈련 목표로만 쓴다. `20261009_gate_front_late_v1/run.py:front_stack()`은 평가연도 Y마다 2017..Y−1 label만 학습하고 Y행에 예측한다. 2020–2026 각 연도 안에서 prior-only 예측이므로, 평가연도 현재 front/section 관측값이 `front_gate_probability`가 되지 않는다. 2017–2019에는 이 보조 예측이 없고 지원 누락을 남긴다. 저장 `verification.json`은 14개 auxiliary replay와 `prior_only_front_predictions=true`를 확인한다. 역시 저장모형 replay 확인이며 출전표가 언제 고정됐는지를 검증하지 않는다.

두 가지 시점 한계는 별도로 유지해야 한다. 첫째, 178,497행 feature roster는 결과가 붙은 과거 runner 행과 `confirmed_runners`에서 구성된 사후 확정 실제 출전 집합이다. 따라서 전체 평가와 gate/field interaction은 “실제로 출전한 말이 알려진 조건부 평가”다. 사전 출마표에서 취소·제외·늦은 변경까지 순차적으로 예측하는 end-to-end 성능을 증명하지 않는다. 둘째, BASE/22에 `previous_carried_weight`, `current_carried_weight`, `current_vs_previous_carried_weight`가 포함된다. 이전 체중은 `weight_source_date <= cutoff_date` assert 및 replay 검증으로 과거 출전값임이 확인된다. 하지만 현재 체중은 `confirmed_runners.carried_weight_raw`를 읽고 feature manifest의 `current_weight_pit_verified=false`로 명시돼 있다. 이 원천 코드에는 체중 관측/발표 timestamp가 연결되지 않아 현재 carried weight가 예측 시점에 이미 공개됐는지 입증되지 않았다. 그러므로 현재 weight와 그 차이를 포함한 full103을 전 입력 “엄격 과거 정보”로 단정하지 말고, 이 PIT 공백을 미해결 위험으로 보고해야 한다.

기존 증거의 범위는 구분한다. `section_style_finish_v1/outputs/verification.json`은 chronology, 178,497 baseline-row 보존, 기존 feature hash를 재확인하고, `gate_front_late_v1/outputs/verification.json`의 `target_poisoning_unchanged` 및 `prior_only_front_predictions`는 결과 오염·연도별 보조 예측 확인을 재사용할 근거다. `profile_carried_weight_v1/outputs/verification.json`의 `current_weight_pit_verified=false`는 현재 체중의 시간 인증이 없음을 직접 표기한다. 이 파일들은 current-weight timestamp나 시점별 출마 roster 원본 snapshot을 검증하지 않으므로 그 두 한계는 남는다.
