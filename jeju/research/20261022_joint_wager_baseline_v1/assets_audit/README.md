# 공동 착순·승식 기준선 자산 감사

감사는 2026-10-22 기준 읽기 전용으로 수행했다. raw score와 작은 기존 원장만 확인했으며 학습·실험·DB 조회 및 복사는 하지 않았다. 핵심 경로, 행/경주 수, 기간, SHA-256, 파일 크기는 [`assets_manifest.json`](assets_manifest.json)에 기록했다. 기존 운영 등록부는 연구 점수 자산과 구분하며, 운영 해시와 등록 상태는 감독관 기록을 참조한다.

## 재사용 가능한 raw score

F1_STYLE6의 recipe-valid OOS 원점수 제공자는 2019–2025 라벨 연도 총 3,783경주·38,017행이다. 빠른 원천 매핑은 다음과 같다.

| 라벨 연도 | 읽기 전용 점수 파일 | 행 / 경주 |
|---|---|---:|
| 2019–2022 | `jeju/research/20261011_pair_top3_oos_expansion_v1/outputs/F1_STYLE6_{2020..2023}/calibration_scores.parquet` | 18,772 / 1,835 |
| 2023 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2024/calibration_scores.parquet` | 6,506 / 657 |
| 2024 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2025/calibration_scores.parquet` | 6,329 / 637 |
| 2025 | `jeju/research/20261010_style_history_ablation_v1/outputs/F1_STYLE6_2026/calibration_scores.parquet` | 6,410 / 654 |

모든 파일의 스키마는 `api_record_id:int64, score:float64`이며, 유일 키로 해당 라벨 연도의 frozen feature 행과 1:1 완전 결합됐다. `score`는 temperature 적용 전 F1_STYLE6 raw score다. downstream에서는 이 두 컬럼을 읽고 `api_record_id`로 행을 맞춘 뒤 `score`를 그대로 써야 한다. provider metadata의 `tau` 또는 확률을 적용하면 안 된다. 2023–2025 파일의 metadata에는 각 같은 라벨 연도 calibration 자료에 맞춘 tau가 각각 1.1006449, 1.1156578, 0.97194596으로 기록돼 있으므로, 이를 사용하면 raw-score 비교에 같은 해 결과 보정이 섞인다. 상세 해시와 provider cutoff는 manifest에 있다.

모든 race의 provider `refit_max`는 `race_date - 2 days` 이하였다. 이는 저장 날짜의 경계 검증이며 입력·결과가 처음 공개된 시각까지 증명하지 않는다. feature 표의 history cutoff도 52,155행 전부 경주일 T−2이고, `latest_history_date`는 1,946행에서 결측이다. 2017–2018 feature는 있으나 고정 F1_STYLE6 recipe의 OOS raw-score 파일은 없어 2019가 최소 비교의 첫 점수 연도다.

평가 파일의 기존 코호트는 2024년 637경주, 2025년 654경주, 2026년 488경주다. 2026은 9월 19일까지 부분 기간이다. 2024–2026 합계 1,779경주·17,412두·269일은 여러 선행 연구가 반복 사용한 개발 기간이므로 fresh holdout이나 독립 실전 검증으로 부르면 안 된다.

## 모집단·라벨 감사

상위 source audit 요약은 전체 9,494경주·92,513행을 기록한다. source 전체에서 정상 완전 순위 경주는 9,027, 출전 기록은 있으나 불완전한 경주는 320, 출전 기록이 전혀 없는 경주는 147, N=1 경주는 32다. 기존 per-race ledger는 2017-01-13부터 2026-09-19까지 5,901경주를 추적해 5,206 포함, 695 제외를 기록한다. 9,494−5,901=3,593은 ledger 날짜 범위와 차감으로 추정한 2017년 이전 수이며, 완전한 원천 날짜 목록과 따로 대조한 수는 아니다.

ledger의 695 제외 경주는 상호 배타적 이유로 `non_normal_or_nonpositive_time + incomplete/nonunique ranks` 501, 거리만 불허 126, 순위만 불완전/중복 59, 거리·시간·순위 복합 9다. 겹치는 원인 플래그는 불허 거리 135, 비정상·0이하 기록시간 510, 1..N 완전·유일 순위 위반 569였다. 최소 6두, source result 행 수 일치, 말·마번 유일성, 경주 내 거리/등급 일치 조건은 이 ledger에서 제외를 추가하지 않았다. 포함 거리는 800, 900, 1000, 1110, 1200, 1300, 1400, 1610m다.

이 원인을 판정하는 기존 규칙은 [horse-profile run.py](../../20261008_horse_profile_baseline_v1/run.py#L80) 80–102행에 있다. `started`는 finish code 1–89 또는 91/92, `valid_time`은 1–89이면서 시간이 양수다. 모집단은 경주 내 순위가 정확히 1..N이고 정상 시간이 모두 있는 경우만 포함한다. [finish-history prepare.py](../../20261009_finish_history_ablation_v1/prepare.py#L82) 82–118행의 별도 race-quality 체크와 309–325행 cohort identity/shape 단언도 확인했다.

상태 코드의 승식 정산 의미는 확인되지 않았다. 기존 계약상 0, 93, 94, 95, 98, 99는 미출전으로 취급하고 91/92는 출전했으나 유효 1..N 순위로 보지 않는다. 공식 취소·출전취소·불성립 분류나 환급 계약이 없어 이를 임의로 붙이지 않았다. 91/92의 DNF/DSQ 세부 의미와 중복순위의 동착 의미도 확인되지 않았다. 이번 label은 정상 완주 및 완전·유일 1..N 순위에 한정하고 미완주·실격·동착을 손실 순위로 매핑하지 않는다.

실제 field size 최소는 7두다. 2025 라벨에 N=7인 경주 4개(28두), 2026 평가에 32개(224두), 합계 36개가 있다. 2026 비교에서 이 36경주는 opening count가 없어 연승 분모에서만 제외하고 연승 지표의 분모는 1,743경주로 둔다는 것이 감독관 결정이다. 나머지 6개 승식의 코호트는 1,779경주다.

## 구현 상태와 남은 계약

제주 목표 문서([prediction objectives](../../../docs/JEJU_PREDICTION_OBJECTIVES_2026-09-28.md#L16))는 말별 WIN/Top2/Top3와 정확 2·3착, coherent `Q(i,j,k)`, 복승·쌍승·복연승·삼복승·삼쌍승의 사건 확률을 요구한다. 현재 코드에는 공동분포를 계산하는 경로가 있으나 저장 산출물과 검증 계약은 그 목표 전체를 충족하지 않는다.

- [jeju_hybrid_evaluation.py](../../../../src/horse_racing/analysis/jeju_hybrid_evaluation.py#L23) 23–56행은 모든 3두 집합과 6개 순서를 정규화하고 `P(set) × P(order|set)`으로 full ordered top-three 분포를 계산한다. [live HY_R_FORM script](../../../../scripts/predict_jeju_live_hy_r_form.py#L475) 475–510행에서도 이 분포와 말별 Top3 marginal을 계산하지만, 560–584행에 저장하는 것은 선택 집합·순서 및 말별 결과이지 전체 ordered-Q 테이블이 아니다.
- [current prediction bundles](../../../../scripts/build_current_prediction_bundles.py#L336) 336–376행의 제주 출력은 말별 `prob_win`, `prob_top2`, `prob_top3`다. 정확 2·3착은 이들이 coherent한 경우 각각 `Top2−Win`, `Top3−Top2`로 계산할 수 있지만 별도 필드로 저장하지 않는다. 조합 확률은 같은 full Q에서 사건을 합산해야 한다.
- [conditional-order research fit_predict.py](../../20261017_conditional_order_head_v1/fit_predict.py#L504) 504–564행은 연구용 ordered Q, conditional order mass, Q 복구·pair-mass 체크를 만든다. [order_head_core.py](../../20261017_conditional_order_head_v1/order_head_core.py#L246) 246–260행은 세 말의 6순서 PL을 정규화하고, [metrics.py](../../20261017_conditional_order_head_v1/metrics.py#L177) 177–205행은 정상·유일 Top3와 WIN/QNL/EXA/TRI 사건을 검사한다. 이는 현재 승인된 최소 PL 온도 비교나 운영 출력으로 간주하지 않는다.

기존 연구 결과도 기준선/선택기 자산과 분리한다. `joint_relationship`의 exact set NLL 게이트 및 구간 게이트는 실패, `joint_gain_loss`의 84 gained/lost 사후 분석은 paired 구간이 0을 포함, `pair_top3_oos_expansion`은 427/1,779 대 raw Top2 429/1,779로 주 게이트 실패, `distance_section_relative`은 후보 게이트 실패, `axis_selector`는 1,503경주 비교에서 점추정 개선 실패로 보류, `axis_disagreement_conditions`는 결승 후 최종 배당 기반 설명 분석이다. `conditional_order_head`는 조건부 순서 NLL 게이트를 통과했지만, 기존 2026 공통 467경주에서 운영 HY_R_FORM이 WIN/QNL/EXA/TRI의 NLL/Brier가 더 좋았다는 보고가 있어 승격 근거가 아니다. 운영 비교는 2026 공통 467경주만 있고 2025 HY 공통 비교는 없다.

## 최소 비교 권고

감독관의 [사전 설계 결정](../supervisor/DESIGN_DECISION.md#L7)과 일치하는 단일 비교로 고정한다. 같은 vintage의 F1_STYLE6 raw score로 PL ordered-top-three `Q_T`를 구성해 **T=1**을 기준선으로 삼고, **2019–2023 OOS raw score의 정확한 1→2→3 joint NLL**을 경주 균등 최소화해 양의 scalar temperature `T` 하나만 적합한다. 두 팔 모두 동일 raw score를 쓰며 같은 해에 맞춘 tau는 적용하지 않는다. 2024–2026-09-19의 반복 사용 코호트 1,779경주에서 고정 비교를 평가하고, 각 승식 사건 확률은 바로 그 Q를 합산해 만든다. 후보 탐색·관계/순서 head 변경·시장배당/ROI는 넣지 않는다. 이 질문은 HY_R_FORM과의 비교가 아니다. HY_R_FORM의 기존 evidence는 2026년 공통 467경주만 남겨 이전 맥락으로 기록하고, 다른 질문으로 다룬다.

최종 감독 검토 때는 이 README와 manifest를 사용하고, 기존 파일은 참조만 한다. 보고서 디렉터리 안에 복사한 점수, feature, DB 또는 원천 파일은 없다.
