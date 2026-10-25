# 제주 1000m 5구간 말별 평가 추가 비교 계획

2026-10-17. 사용자 승인에 따른 후향 연구 후보다. 기존 `F1_STYLE6`를 보존하고, 같은 30개 입력에 과거 제주 1000m 경주에서 계산한 5개 구간시간의 최근 평균과 유효 관측 수 10개만 추가한 후보를 비교한다. 구간시간은 현재 평가 경주가 아닌 과거 실제 동일거리 출전에서만 계산한다. DB·운영 모델·등록부·기존 연구 결과는 변경하지 않는다.

## 고정 비교

- 대조군은 `jeju/research/20261010_style_history_ablation_v1`의 저장 `F1_STYLE6` 세 모델과 저장 점수다. 재학습하지 않는다. 세 저장 모델·raw score·Top3 주변확률과 기존 30열 입력을 전수 재현한 뒤 그 SHA와 비교표본 키를 잠근다.
- 후보는 기존 30열을 그대로 유지하고 1000m 대상에만 10개 숫자열을 추가한 40열 모델 한 종이다. 기존 52,155행·5,206경주 전체 거리 코호트, Top3 정답, 행순서, 거리별 평가연도 및 `F1_STYLE6` LightGBM 설정·경주당 `1/field_n` 가중치·온도 보정·additive 3-set 확률 절차를 유지한다. 1000m 전용 모집단만으로 재학습하지 않는다.
- 1000m 평가가 주 비교다: 2024년 170경주/1,694출전, 2025년 196/1,947, 2026년 142/1,372, 합계 508경주/5,013출전. 다른 거리와 전체 1,779경주/17,412출전 결과는 설명용 보조 분석이며 1000m 성능의 타 거리 일반화로 해석하지 않는다. 2026년은 9월 19일까지의 부분연도다.
- 평가연도 Y의 초기 학습은 2017~Y−3, 조기종료는 Y−2, 선택 iteration으로 Y−2까지 refit, 온도 보정은 Y−1, 테스트는 Y다. 기준선 대조 모델은 저장 결과를 재현하며 재학습하지 않는다. 후보는 결과를 본 뒤 추가 fit·튜닝하지 않는다.

## 5개 구간 정의

말별 과거 1000m 기록에서 다음 값을 초 단위로 계산한다. S1F는 공식 설명의 200m 지점이다. C3/3C 및 C4/4C는 공식 지점 설명상 결승선 기준 약 600m·400m 전이므로 중간 경계는 근사 위치로 표시한다.

| 구간 라벨 | 계산 | 사용 endpoint |
|---|---|---|
| 0–200m | `S1F` | S1F |
| 200–약400m | `C3 − S1F` | C3, S1F |
| 약400–약600m | `C4 − C3` | C4, C3 |
| 약600–800m | `finish − G1F − C4` | finish, G1F, C4 |
| 800–1000m | `G1F` | G1F |

모델 입력은 다음 평균+n 열 10개로 고정한다. 비1000m 대상은 10열 모두 NULL로 두어 비적용과 무관측을 구분한다. 1000m 대상에서 해당 구간의 유효 과거 슬롯이 하나도 없으면 평균은 NULL, n은 0이다.

| 모델 입력 열 | 의미 |
|---|---|
| `hist_0_200m_seconds_mean5`, `hist_0_200m_n` | S1F의 최근 최대 5개 동일거리 슬롯 평균과 유효 슬롯 수 |
| `hist_200_approx400m_seconds_mean5`, `hist_200_approx400m_n` | C3−S1F의 평균과 유효 슬롯 수 |
| `hist_approx400_approx600m_seconds_mean5`, `hist_approx400_approx600m_n` | C4−C3의 평균과 유효 슬롯 수 |
| `hist_approx600_800m_seconds_mean5`, `hist_approx600_800m_n` | finish−G1F−C4의 평균과 유효 슬롯 수 |
| `hist_800_1000m_seconds_mean5`, `hist_800_1000m_n` | G1F의 평균과 유효 슬롯 수 |

5개 분할의 합은 대수적으로 과거 `finish_time_seconds`와 같아야 한다. 양수, endpoint별 품질·상태 및 관측 시점 검사를 통과하지 못한 구간은 NULL이다. 구간별 eligibility는 사용하는 endpoint만으로 결정하고, 별도 G3F consistency 진단값을 근거로 무관한 구간을 자동 제외하지 않는다. G3F 진단은 `finish − C3 − G3F` 잔차이며, approximate C3/G3F 경계를 고려해 feature나 정답으로 사용하지 않는다. 정확한 status/mask/identity 진단 규칙과 원천 파일 해시는 source snapshot 계약 확정 시 본 계획과 계약에 잠근다.

각 구간의 target feature는 기존 F1 lineage의 실제 최근 5회 동일거리 출전 슬롯 중 구간별 유효값의 산술평균과 유효 슬롯 수다. 무효 슬롯을 제거해 과거 슬롯으로 backfill하지 않는다. 대상이 1000m가 아니면 신규 10열 모두 NULL(관측수 열 포함)로 비적용 표시한다. 1000m 대상에서 eligible 과거 값이 없으면 평균 NULL, n=0이다.

## 사전 평가와 기록

- Fit 전 source worker가 제공하는 quality-selected snapshot, F1 same-distance last-5 lineage, target/source 공식 ID, 실제 시작·거리·날짜·T−2, status·provenance와 파일 SHA를 독립 사전검사한다. 현재 DB는 조회하지 않는다.
- Fit 전 기존 `F1_STYLE6` 저장 세 모델 점수와 17,412행/1,779경주/10,674 canonical 최대6 조합행 분포를 재현·비교하고 기준선 원천 파일을 고정한다.
- 주지표는 평가출전별 Top3 binary log loss와 Brier를 경주 안에서 평균한 뒤 경주 균등 평균하는 방식으로 계산한다. 차이는 `40열 후보 − 저장 F1_STYLE6`다. gate는 두 점추정치 모두 음수이고 적어도 하나의 경주일 paired 95% CI 상한이 0 미만일 때 통과다. 경주일 단위 paired bootstrap은 2024~2026 공통 269일에 대해 미리 고정한 `20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy`(2,000×269)를 그대로 사용한다. 각 재표본에서 1000m 날짜만 numerator와 race-count denominator에 기여하고, 1000m 경주가 없는 날은 둘 다 0으로 둔다.
- 연도별 결과와 full all-distance/다른 거리 손실·보정·지원량·Top5/Six-set 보조지표를 보고하되 사전 gate를 변경하지 않는다. 결과에 따른 신규 fit·피처 탐색은 금지한다.
- 후보 fit은 3개 연도 모델이며, 총 LightGBM train 호출 6회와 온도 보정 최적화 3회로 제한한다.
- 기계가 읽는 feature/lineage parquet와 함께 사람 검토용 1000m 예측표 및 target×과거슬롯 구간 계산표를 보존한다. 평가표는 출전·말·날짜·실제 Top3·저장 기준선 및 후보 예측을, 슬롯표는 source ID/date, endpoint 값·상태, 5개 계산 구간, NULL/eligible 사유와 target별 각 mean/n을 추적 가능하게 한다. 몇 개 예시는 결과가 아니라 사전 고정된 key 정렬/지원 상태 규칙으로 고른다.

이 연구는 후향 개발 표본의 피처 묶음 비교다. 승식 순서 모델, standalone pair model, 배당, 기수, 운영 모델 또는 운영 등록부는 재학습·수정·적용하지 않는다. 사전 gate 통과도 독립 미래검증·운영 승격·인과효과를 뜻하지 않는다.
