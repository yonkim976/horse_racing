# 과거 전개 위치 이력 추가 비교

2026-10-10. 학습 전 잠금 계약이다. 기준선은 `20261009_finish_history_ablation_v1`의 저장 F1 24입력 모형이다. 동일한 실제 동일거리 최근 5회 슬롯에서 구간 위치를 요약하는 연속형 6열을 더한 단일 후보 `F1_STYLE6`(30입력)와 비교한다. 이 작업은 반복 사용한 과거 자료의 후향 개발 비교다. root의 별도 fit 승인 전에는 후보를 학습하지 않는다. 원천 status allowlist와 point별 완결성·지원량은 `20261010_style_history_source_audit_v1/source_audit.json` 및 해당 SHA 잠금으로 고정한다.

## 모집단, 기준선, 보존

입력 행과 결과 표본은 F1과 동일하게 고정한다. 2017-01-13~2026-09-19의 52,155출전·5,206경주, 2024~2026 평가 17,412출전·1,779경주·269경주일이다. 2026년은 9월 19일까지의 부분연도다. 현재 거리 범위, 정상 완주·완전 편성 모집단, 제외 말 3005648, 2017년 정답 학습 시작과 과거 warm-up, J0 13열+상대능력 8열+F1 직전결과 3열을 바꾸지 않는다. 정답 편성과 공개시각은 역사적으로 재구성되지 않았다.

기준선은 `20261009_finish_history_ablation_v1/outputs/F1_2024`, `F1_2025`, `F1_2026`에 저장된 24입력 모형을 정확히 재로딩한다(각 연도 1개, 기존 meta와 model SHA 확인). 기준선은 재학습하지 않는다. 기존 24열에만 쓰인 과거 이력 정의도 해당 F1 계약을 따른다. 새 후보는 그 입력에 아래 6열만 덧붙인다. DB, 운영 모형·등록부, 기준선 및 기존 연구 결과는 읽기 전용으로 둔다. 이 연구의 파일과 산출물은 이 디렉터리에만 둔다.

## 원천과 시점

추가 값은 공식 말 ID로 이어진 `last5_same_source_ids`의 실제 최대 5개 동일거리 슬롯에서만 계산한다. 이 슬롯 ID·순서는 기준선 F1 입력 계약에서 가져오고, ID별 말·거리·실제 시작 상태·한국 경주일 T−2 cutoff를 다시 대조한다. 현재 경주의 구간·착순·전개 결과는 입력으로 조회하거나 사용하지 않는다.

구간별 individual order는 `jeju_race_postrace_sections_quality_2026` 및 그 quality constituent의 S1F·4C·G1F 선택값과 필드별 status를 쓴다. source field는 API4 `sjS1fOrd`, `sj_4cOrd`, `sjG1fOrd`다. API4 order 허용 status는 `{api_positive_unreviewed, website_corrected}`이며 그 외 review 미적용·unknown·conflict·source-changed는 해당 point에서 fail closed 처리한다. API303 group은 feature order가 아니며, 매칭 group status `{api_group_unreviewed, api_group_unavailable}`만 허용한다. absent/NULL/unknown, known conflict, missing-review, source-changed는 해당 point에서 fail closed 처리한다. API4 전체 순열 flag와 API303 status gate를 따로 확인하고, `race_point_eligible`는 두 값의 AND다. group parser/interval 검사는 별도 진단이며 rank 입력·복원은 하지 않는다. `_raw`, legacy view, API303 괄호 내 순서 또는 다른 원천으로 보완하지 않는다. 해당 허용 status와 lineage 매핑은 `20261010_style_history_source_audit_v1/source_audit.json` 및 cache SHA에 잠근다.

`N_started`와 전체 started horse ID 집합은 원천 감사에서 전체 `source_snapshot` 행을 경주별로 full `race_result_rows`와 대조하고, 기준선과 같은 `started` 정의의 N·ID 집합 일치를 확인해 구성한다. 확인되지 않는 경주는 신규 point feature를 fail closed 처리한다. 새 6열에 과거 slot을 기여시키려면 대상 말의 기준선 `source_snapshot` 행이 `valid_time=True`여야 한다. `valid_time=False`인 slot은 실제 최근5 슬롯 목록과 lineage에 남기되, 새 feature의 유효 관측 수에 넣지 않고 더 과거 슬롯으로 backfill하지 않는다. 한 point를 쓰려면 quality 선택값·허용 status가 있는 모든 full-roster started horse ID가 정확히 그 경주의 전체 `started=True` horse ID 집합과 일치하고, 값이 중복 없는 `1..N_started` 순열이어야 한다. 이 집합·순열 조건을 만족하지 못하면 해당 point는 경주 전체에서 fail closed 처리한다. N_started가 2 미만이면 상대 위치는 정의되지 않는다. 괄호 group에서 말별 순서를 복원하지 않는다.

2026-10-10 원천 감사에서 6,269개 참조 과거 경주(62,248 started horse row)의 전체 snapshot roster가 full `race_result_rows` roster와 경주별 N·출전 ID 집합까지 일치했다(불일치 0). 이 6,269 경주 중 API4 permutation과 허용 API303 status를 모두 통과한 race-point는 S1F 6,243개, 4C 6,242개, G1F 6,241개다. 고정 178,459개의 실제 슬롯 및 50,491개 고유 source ID에서 최종 valid-time 슬롯 수는 S1F 177,688, S1F→4C 177,450, 4C→G1F 177,498이다. 세 point의 distance별 분포·API4/API303 상태와 cache SHA는 원천 감사 산출물에서 확인한다. 이 요약은 해당 history-source cohort의 상태·지원량이며 전체 DB의 point 가용성 주장으로 확대하지 않는다.

거리별 측정 순서는 해당 원천의 구간 정의를 따르며 표시 열의 순서를 임의로 가정하지 않는다. 특히 1300m는 출발→2C→S1F 계약을 지킨다. 이 거리의 S1F는 2C 뒤 측정이며 보편적인 200m 표지나 첫 코너 전 위치로 해석하지 않는다. 거리별 품질 선택 time audit의 source-valid S1F/C4 쌍 50,460개 모두 S1F 시간이 C4보다 앞섰고, C4와 `finish−G1F` checkpoint 쌍 50,459개 모두 C4가 앞섰다. 1300m는 각각 464/464쌍에서 이 시간 순서가 확인됐다. 이는 선택 시각의 temporal consistency이지 물리적 geometry 검증은 아니다. 원천 API303 interval 대조에서 API4 개별순위와의 불일치 예시는 0건이었다. S1F→4C와 4C→G1F는 named-point rank 변화로만 계산하며 G1F는 마지막 구간 통과위치이지 결승 위치·막판 시간·속도와 같지 않다.

## 후보 입력 6열

과거 경주 e의 실제 출전자 수를 `N_e`, 해당 point의 허용된 개별 순위를 `q_e,p`라 한다. 유효한 위치는 `r_e,p=(q_e,p−1)/(N_e−1)`이다. 값 0은 해당 지점의 1위, 1은 해당 지점의 `N_e`위이며 결승 착순이 아니다. 과거 슬롯은 최근 5회까지 유지하며 특정 point가 빠졌다고 더 오래된 슬롯을 끌어오지 않는다. 각 평균은 정한 실제 슬롯의 `valid_time=True`이면서 유효한 관측만 평균한다. `n=0`이면 평균은 NULL, n은 0이다. pair n은 같은 과거 슬롯에서 양쪽 point가 모두 유효한 관측 수다.

| Concept | 새 입력 열 | 정의 |
|---|---|---|
| 초반 상대위치 | `hist_s1f_relpos_mean5` | 유효 동일거리 슬롯의 S1F 상대 위치 `r_S1F` 평균 |
| | `hist_s1f_relpos_n` | 위 평균에 포함된 실제 동일거리 슬롯 수 (0..5) |
| 초반부터 4C까지 상대위치 변화 | `hist_s1f_to_c4_forward_mean5` | 같은 슬롯의 `r_S1F − r_4C` 평균. 양수는 상대적으로 앞으로 이동, 음수는 뒤로 이동 |
| | `hist_s1f_to_c4_pair_n` | S1F와 4C가 모두 유효한 동일거리 슬롯 수 (0..5) |
| 4C부터 G1F까지 상대위치 변화 | `hist_c4_to_g1f_forward_mean5` | 같은 슬롯의 `r_4C − r_G1F` 평균. 양수는 상대적으로 앞으로 이동, 음수는 뒤로 이동 |
| | `hist_c4_to_g1f_pair_n` | 4C와 G1F가 모두 유효한 동일거리 슬롯 수 (0..5) |

이 값들은 경주 안에서 관측된 상대 순위의 반복 요약이다. 말이 선두였는지, 앞에서 실제로 버텼는지, 주행 경로·속도·체력·기수 의도를 뜻하지 않는다. 중간 또는 막판 순위 변화는 해당 전환의 위치 차이다. 새 6열은 S1F/4C/G1F 통과위치로 구성하며 과거 최종착순 평균은 별도 추가하지 않는다. 동일한 유효 슬롯 집합을 쓸 때 `mean(S1F r) − mean(S1F r−4C r) − mean(4C r−G1F r)`로 평균 G1F 상대위치를 재구성할 수 있으므로, 이 6열 묶음의 예측 개선은 순수 전술 효과나 상대위치 변화의 독립 효과를 식별하지 않는다. 4C→G1F로 끝내는 설계는 finish 착순을 직접 넣거나 전이 종점으로 재구성하는 혼재를 줄이지만, 최근 G1F 위치수준과의 분리를 보장하지 않는다. 각 개념은 2열이고 어떤 threshold·분류기·절대초 기준도 추가하지 않는다.

## 학습·확률·판정

대조군 F1은 저장된 세 모형을 재로딩해 같은 17,412출전의 점수·확률·경주지표·canonical 조합을 재현하며 재학습하지 않는다. 후보 `F1_STYLE6`만 2024·2025·2026 연도별 최종 모형 3개를 fit한다. 각 평가연도 Y에서 초기 학습은 2017~Y−3, early stop은 Y−2, 해당 iteration으로 refit은 Y−2까지, calibration은 Y−1, test는 Y다. 기존 F1과 같은 LightGBM 설정·seed 20261008·경주 균등 출전 가중치 `1/N`·최대 200회·early stopping 25회·train-only 범주 어휘·온도 보정을 쓴다. 초기 학습과 refit을 합쳐 LightGBM train 호출은 6회, 온도 보정은 3회다. 이 계약에 없는 추가 fit, tau 재최적화 또는 결과를 본 뒤의 수정은 하지 않는다.

말별 Top3 주변확률은 F1과 같은 세 말 점수의 가산 집합모형에서 계산한다. canonical sorted 최대 6 조합과 세 점수의 좌결합 합·동점 규칙을 유지한다. 주지표는 경주 균등 Top3 log loss와 Brier다. 연구 후보 gate는 후보−F1에서 두 점추정치가 모두 개선되고 두 지표 중 하나 이상 경주일 paired 2,000회 bootstrap 95% 구간의 상한이 0 미만이어야 한다. 지표마다 seed 20261008을 새로 설정한다. 연도·거리·경력·세 입력별 history-n 지원표와 paired 표를 남기며, 소표본은 설명 표식으로만 둔다. Top5 capture, Top3 전원 포함, canonical 최대6 조합 hit와 공통 467 운영 경주는 보조 비교다. `pick_hit`는 최고점 말의 Top3 포함 여부이며 우승 적중이 아니다. HY_R_FORM의 native PL 지표와 F1 계열 가산 조합확률은 별개로 표시한다.

같은 과거 표본의 반복 사용에 따른 후향 개발 결과다. 공개 시각·정상 완주 전수 모집단은 역사적으로 복구하지 않았다. 개선 gate는 독립 미래검증·인과효과·운영 승격을 뜻하지 않는다. 소표본 및 2026 부분연도 범위를 함께 쓴다.
