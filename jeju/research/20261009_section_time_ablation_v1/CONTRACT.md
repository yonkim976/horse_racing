# F1에 과거 구간시간을 더하는 최소 ablation 계약

작성일 2026-10-09. 이 계약은 기존 F1 24열에 동일거리 최근 실제출전의 원천 S1F·G3F·G1F 시간 요약과 필드별 유효 관측 수를 더하는 단일 묶음 비교를 정의한다. 6개 열을 더해 후보 F1S는 30열이다. 현재 단계는 입력·가용성 사전 감사이며, 저장 F1 점수 재현과 후보 모형 fit·온도 최적화·예측지표 계산은 사전 검토 gate를 통과한 뒤에만 한다.

## 고정 모집단과 대조군

주 모집단과 기존 입력은 `../20261009_finish_history_ablation_v1/CONTRACT.md`, `README.md`, `outputs/features.parquet`, `outputs/historical_lineage.parquet`에 저장된 F1을 그대로 따른다. F1은 2017-01-13~2026-09-19의 52,155출전·5,206경주이며, 평가 2024~2026은 17,412출전·1,779경주·269일이다. 평가행은 2024년 6,329행·637경주, 2025년 6,410행·654경주, 2026년 4,673행·488경주다. 2017년 이전 이력은 warm-up에만 사용한다. 기존 한국 경주일 T−2 cutoff를 포함하며 작은곰(3005648)을 제외한다.

대조군은 저장된 `F1_2024`, `F1_2025`, `F1_2026`의 모형·메타데이터다. 저장 모형의 24개 열 순서, 범주 어휘, 점수, 온도, 분할, 점수에서 Top3 주변확률·최대 6개 조합분포를 만드는 계산을 재현한다. 저장 F1을 재학습하지 않는다. 저장 모형 파일 SHA-256은 2024 `f2373c48e0a6d415e64f577dc64c14d12d71f9b97ea5d3a0c78853f12870eb5d`, 2025 `b66ece1487c86ad1cd05aabed7f3781d84e89c24e6a3ebcb010f38b811009b9d`, 2026 `15654e60d6736aabc0ec0af60cbdf4478c05b8fb6227d826dd8aff0ef1f347a4`이며 각 파일 해시가 기존 `meta.json`과 일치하는지 preflight에서 다시 확인한다.

## 추가 입력과 산출 정의

F1 행마다 기존 `last5_same_source_ids`에 저장된 최대 5개 실제 출전을 오래된 슬롯부터 최근 슬롯까지 그대로 쓴다. 각 ID는 공식 말 ID·출전 ID와 연결하고 F1 기록의 정확한 거리와 일치하며 해당 행의 T−2 cutoff 이하여야 한다. 누락 구간값이나 유효하지 않은 구간값이 있어도 실제 출전 슬롯을 삭제하지 않는다. 필드별 결측은 서로 독립이며, 이전 기록으로 슬롯을 채우지 않는다.

후보 추가 열은 아래 6개다.

| 구간 | 평균 초 | 유효 관측 수 |
|---|---|---|
| S1F | `history_s1f_mean5_seconds` | `history_s1f_valid_n` |
| G3F | `history_g3f_mean5_seconds` | `history_g3f_valid_n` |
| G1F | `history_g1f_mean5_seconds` | `history_g1f_valid_n` |

각 평균의 분모는 해당 말의 정확히 같은 거리 최근 최대 5개 실제 출전 슬롯 중 그 필드에서 유효한 기록 수다. `n=1..5`이면 그 관측의 산술평균, `n=0`이면 평균 NULL·n 0이다. 결측은 0초로 대체하지 않는다. S1F·G3F·G1F의 유효 관측 수가 달라도 다른 구간의 값을 복사하거나 전파하지 않는다.

S1F는 **원천 S1F 지점시간**으로 부른다. 전 거리의 200m 또는 210m 기록이라고 가정하거나 해당 단위로 환산하지 않는다. 1300m는 사용자가 고정한 출발→2C→S1F 순서 계약을 존중하며, 이 후보 입력은 원천 S1F 시간과 exact-distance history만 사용한다. 1300m를 표본 지원이 확인된 것으로 미리 간주하지 않는다. G3F와 G1F는 서로 겹치는 종반 시간 측정이지만 별도 원천 필드다. 둘을 더하거나 서로의 순위·속도·상대시간으로 변환하지 않는다. 제주 G3F 순위 원천은 0값이므로 G3F 통과순위·통과조를 만들지 않는다.

구간시간은 `jeju_race_postrace_sections_quality_2026`가 제공하는 선택값과 상태를 따른다. 가용성 감사는 이 뷰의 SQL 의존관계에 기록된 선택 필드만 구성요소 품질 뷰에서 parameterized 조회하며, 시간은 `jeju_race_section_time_values.time_seconds/time_status`, 통과착순은 `jeju_race_section_order_quality_values.quality_order_status`, 통과조는 `jeju_race_section_group_quality_values.group_status`를 사용한다. DB는 SQLite URI `mode=ro`와 `PRAGMA query_only=ON`으로 연다. 원문 JSON·raw 시간·raw 순위·raw 통과조를 읽어 품질 선택값을 우회하지 않는다.

구간 값은 원천 선택시간이 양수이고 시간 상태가 `website_corrected` 또는 `api_positive_unreviewed`이며 기존 `source_snapshot.parquet.valid_time=True`일 때만 유효하다. 비정상·미완결 출전은 실제 슬롯으로 보존하되 구간 수행값은 입력에서 제외한다. 양수 미검증 시간에 사후 백분위·느린 꼬리·임의 시간 한계를 적용하지 않는다. 전체기록 보정계수를 구간에 비례 이식하지 않는다.

S1F 또는 G1F에서 같은 과거 경주의 해당 지점 통과착순·통과조 상태가 `conflict`, `not_applied`, `source_changed` 문자열 중 하나를 포함하거나 해당 race-point 상태가 NULL·누락이면, 그 지점의 시간을 그 경주 모든 말에 대해 후보 분석에서 NULL로 마스킹한다. 상태 도메인은 허용 목록과 대조하며 알 수 없는 새 상태가 나오면 감사가 실패한다. 이는 기존 DB 값을 바꾸지 않는 feature-level 보류다. G3F에는 해당 지점 순위·통과조가 없으므로 그 mask를 만들지 않는다. 시간 자체가 미해결로 선택 NULL인 광해청명 G1F와 알려진 정정·충돌 지점은 원천 품질 상태 그대로 유지한다.

## 학습과 평가

2024·2025·2026 각각 후보 F1S 한 모형을 학습한다. 연도 Y의 초기 학습은 2017~Y−3, 조기종료는 Y−2, 해당 iteration까지 refit은 Y−2까지, 온도 보정은 Y−1, 평가는 Y다. 기존 F1과 같은 LightGBM 설정·seed 20261008·경주당 출전 가중치 `1/field_n`·최대 200회·조기종료 25회와 기존 온도 보정 방법을 쓴다. 후보 학습은 총 6회 LightGBM train 호출과 3회 온도 최적화를 사용한다. 기존 F1의 year별 실제 tree 수·온도·범주 어휘는 저장 `meta.json`에서 읽는다.

기존 F1의 경주 안 additive-3-score 방식으로 말별 Top3 주변확률을 만들고, 세 점수의 canonical 조합합으로 최대 6개 상위 3두 조합 분포를 계산한다. 주 손실은 경주 균등 Top3 log loss와 Brier다. 보조 지표는 Top5의 실제 Top3 포함률, Top5에 실제 Top3 세 두 모두 포함률, 최대 6개 조합 적중이다. F1S−F1 차이는 날짜 단위 paired bootstrap 2,000회·seed 20261008·95% 점별 구간으로 계산한다. 전체·연도·거리·경력·필드별 유효 관측 수를 보고하고, 표본 수가 작은 집단은 별도 표시한다.

사전 고정 연구 유지후보 gate는 전체 log loss와 Brier가 모두 F1보다 낮고, 둘 중 적어도 하나의 날짜 paired 95% 구간 상한이 0보다 작은 경우다. 구간시간 후보가 이를 통과해도 후향 개발 연구 후보일 뿐 독립 미래검증이나 운영 승격이 아니다. 2026 HY_R_FORM 운영 모델과의 기존 공통 467경주·4,475출전 비교는 별도 보조 표로 보존하며 이 gate의 대체로 쓰지 않는다.

## 확정하지 않은 항목

거리·연도별 및 F1 실제 최근5 슬롯별 구간시간 지원은 `outputs/source_availability_audit.json`, `source_availability_by_group.csv`, `source_valid_n_distribution.csv`에 감사 후 첨부한다. 현재 지원 감사를 완료하기 전까지 특정 거리의 보편 지원을 가정하지 않는다. 특히 S1F는 원천 정의가 거리별로 동일하다고 가정하지 않고 각 정확 거리에서 관측 지원을 공개한다. 이 비교는 세 구간을 단일 6열 패키지로 검토하며, 결과를 본 뒤 열·거리·상태 필터를 고르지 않는다.
