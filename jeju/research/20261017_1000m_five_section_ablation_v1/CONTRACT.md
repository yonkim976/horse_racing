# 제주 1000m 다섯 구간시간 F1_STYLE6 확장 계약

2026-10-17. 사용자가 승인한 후향 ablation이다. 저장 `F1_STYLE6` 30열과 비교하기 위해, 같은 52,155행 전체거리 학습 모집단에 1000m 대상 과거 동일거리 최근5 실제출전에서 계산한 다섯 구간 평균과 유효 슬롯 수 10열을 더한 단일 40열 후보를 평가한다. 이 문서는 사전 계약이며 root가 원천 사전검사·코드 잠금을 승인하기 전 후보 학습과 후보 결과지표 계산은 금지한다.

## 불변 대조군과 모집단

고정 대조군은 `jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet`의 기존 30개 모델 입력, 저장된 `F1_STYLE6_2024/2025/2026` 모형·메타·보정계수·원시 점수 및 상위조합 확률이다. 기준선 재학습은 하지 않는다. 세 모델 재로딩으로 저장 baseline의 17,412 평가출전, 1,779 경주, 연도별 OOS raw score 및 additive Top3 확률을 재현하고 그 출전 키와 파일 hash를 준비 잠금에 기록한다. root는 baseline 재생을 독립 실행하여 통과했다고 보고했다.

후보의 기존 30열은 기준선 파일에서 정확히 유지하고, 추가 입력 10열만 source snapshot에서 만든다. 모델 표본은 기존 전체거리 52,155출전·5,206경주, 라벨·row order, 기존 train/validation/calibration/test 경계와 동일하다. 1000m 전용으로 재학습해 변수를 바꾸지 않는다. 1000m 주 평가 코호트는 2024년 170경주/1,694출전, 2025년 196/1,947, 2026년 142/1,372, 합계 508경주/5,013출전이다. 전체 및 타 거리는 보조 결과로만 제시한다.

각 평가연도 Y에서 H1 학습은 2017~Y−3, early-stop 검증은 Y−2, 선택 iteration을 사용한 refit은 H1+Y−2, calibration은 Y−1, test는 Y다. 동일한 `F1_STYLE6` LightGBM 설정, seed 20261008, 이진 Top3 라벨, 경주당 말 가중치 `1/field_n`, 최대 200회, early stopping 25회, train-only 범주어휘와 기존 온도 최적화·additive 3-set 확률 계산을 쓴다. 후보는 연도별 3개 최종 모델, 총 6회 LightGBM train 호출과 3회 온도 최적화만 수행한다. 결과를 본 추가 fit·tuning은 금지다.

## 과거 원천과 시점

새 원천은 `jeju/research/20261017_1000m_five_section_source_audit_v1/`의 `target_1000m_roster.parquet`, `target_last5_lineage.parquet`, `api4_quality_source_snapshot.parquet`, `target_last5_section_intervals.parquet`, `section_time_reviews.parquet`, `source_fingerprint_before_after.parquet`, `source_audit.json`이다. 이 번들은 1000m 대상·그 대상의 저장 F1 last5 실제 출전 원천만 다루며, DB 원문·실행 중인 DB 파일 hash 또는 운영 상태는 후보 준비 단계에서 읽지 않는다. 원천 quality-view 선택값과 provenance/status/fingerprint 파일을 입력으로 핀하고, 그 manifest의 각 파일 크기·SHA-256을 준비 잠금에 기록한다.

각 대상은 기존 F1 feature 파일과 같은 공식 출전 ID·말 ID·경주 ID·날짜·거리·실제 시작 상태를 유지한다. 저장 last5 lineage의 정확한 슬롯 ID·순서를 다시 비교한다. 대상 `history_cutoff`는 한국 경주일 기준 race_date−2일과 일치해야 하며 source race date는 cutoff 이하, source 및 target distance는 1000m, 공식 horse ID는 같아야 한다. quality-view row는 출전 ID 외에 baseline source snapshot과 race ID/date, horse ID/number, distance, started, finish time 및 API4 source fingerprints가 정확히 맞아야 한다. `valid_time=False`인 실제 출전도 슬롯 lineage에 남기되 구간 입력에서 제외하고 더 오래된 출전으로 보충하지 않는다.

구간은 quality-selected 유효시간으로 계산한다. S1F, C3, C4, G1F 시간은 양수이고 시간 상태가 `api_positive_unreviewed` 또는 `website_corrected`일 때 측정 endpoint가 유효하다. finish endpoint는 positive baseline `finish_time_seconds`와 `valid_time=True`를 요구한다. endpoint별 원천 point status는 기존 F1S time-audit의 허용 status domain을 검증한다. API4 order status 허용 domain은 `api_positive_unreviewed`, `api_unavailable_or_nonpositive_or_sentinel`, `website_corrected`, `website_review_not_applied`, `api_source_changed_since_review`, `unresolved_official_internal_conflict`, `internal_conflict_review_not_applied`, `api_source_changed_since_conflict_review`다. API303 group status 허용 domain은 `api_group_unavailable`, `api_group_unreviewed`, `unresolved_official_internal_conflict`, `internal_conflict_review_not_applied`, `api_source_changed_since_conflict_review`다. 각 point의 order/group status가 누락되거나 허용 domain 밖이면, 또는 fail-closed token (`conflict`, `unresolved`, `not_applied`, `source_changed`)을 포함하면 해당 point는 막는다. 이 point mask는 해당 원천 경주의 모든 started 말 행을 대상으로 만들며 한 말의 누락·충돌도 그 경주 point의 시간을 전 말에서 보류한다. status domain, point mask 및 source fingerprints가 불일치하거나 preflight 조건을 어기면 멈추며 raw/legacy 값으로 대체하지 않는다. 최종 역사 구간 feature eligibility는 endpoint/point mask 통과, 구간시간 양수, 해당 실제 슬롯 `valid_time=True`를 모두 요구한다.

## 구간과 10개 입력

1000m 기록에서 five-section elapsed times are:

| 거리 표시 | 계산 | 모델 평균/n 열 |
|---|---|---|
| 0–200m | `S1F` | `hist_0_200m_seconds_mean5`, `hist_0_200m_n` |
| 200–약400m | `C3 − S1F` | `hist_200_approx400m_seconds_mean5`, `hist_200_approx400m_n` |
| 약400–약600m | `C4 − C3` | `hist_approx400_approx600m_seconds_mean5`, `hist_approx400_approx600m_n` |
| 약600–800m | `finish_time_seconds − G1F − C4` | `hist_approx600_800m_seconds_mean5`, `hist_approx600_800m_n` |
| 800–1000m | `G1F` | `hist_800_1000m_seconds_mean5`, `hist_800_1000m_n` |

KRA meet=2 설명상 S1F는 출발 후 200m, 3C는 결승 전 약 600m, 4C는 결승 전 약 400m, G1F는 마지막 200m 측정이다. 따라서 C3/C4 경계는 근사값으로만 표기한다. 다섯 값은 대수적으로 finish time에 더해지며, 각 interval은 자체 endpoint 및 point mask를 적용한다. 구간 길이 양수는 시간 단조성 점검이다. 어떤 interval 실패도 endpoint를 공유하지 않는 구간에 전파하지 않는다.

G3F는 `finish_time_seconds − C3 − G3F` 잔차의 별도 consistency 진단에만 사용한다. 잔차 허용 범위 ±0.15초와 진단 지원량을 보고하지만 G3F는 모델 입력이 아니며 이 진단만으로 다른 구간을 마스킹하지 않는다. 표본의 모든 5개 interval이 동시에 usable인지도 설명용으로 보고하며 이 조건으로 후보 코호트를 걸러내지 않는다.

대상별로 기존 F1 last5 슬롯에서 구간마다 usable한 초의 산술평균 및 해당 슬롯 수 0..5를 계산한다. `n=0`이면 평균 NULL, n=0이다. 대상 race distance가 1000m가 아니면 mean·n 모두 NULL이며, 이는 1000m 대상이지만 관측이 없는 경우(n=0)와 다른 상태다. 다섯 평균 및 다섯 n은 숫자열이고, 식별자·말 이름·마번·결과·배당·기수·postrace fields는 모델 입력에 넣지 않는다. 원천 번들에 평가 대상 경주 자체의 endpoint 시간 열이 있더라도 source audit/산술검증 전용이며 모델 input 및 target prediction table에 넣지 않는다. 사람이 보는 평가표에는 T−2-safe history mean/n 및 해당 출전의 Top3 outcome만 표시한다.

## 비교·평가 고정

1. 저장 기준선 30열·모형·score·probability 재현, source snapshot/lineage/preflight, feature aggregation, training code, schema 및 hashes를 root가 검토하고 고정한다.
2. root가 잠금된 contract, source/preflight receipt 및 training-code SHA를 지목한 명시적인 fit approval를 발급한 뒤에만 candidate를 연도별 3 fit한다.
3. candidate model/feature preprocessing/score/Tau artifacts를 hash로 고정한 뒤 frozen report code로 한 차례만 결과를 산출한다.

주지표는 말별 Top3 binary log loss 및 Brier를 경주 안에서 평균한 뒤 경주 균등 평균하는 방식이며, 차이는 `40-column candidate − saved F1_STYLE6`다. 유지후보 gate는 두 point estimates가 모두 음수이고, 둘 중 하나 이상 date-paired bootstrap 95% 구간 상한이 0 미만일 때만 통과다. bootstrap은 사전 고정 `jeju/research/20261011_pair_top3_direct_v1/outputs/date_bootstrap_schedule.npy`의 2,000×269 resample indices를 모든 평가연도 269 경주일 순서에 그대로 적용한다. 1000m 경주가 없는 resampled date는 loss 합과 race count에 모두 0으로 기여한다. 1000m 평가연도별 결과도 별도 표시한다. Canonical 최대6개 3두 집합의 categorical NLL은 별도 보조지표 `trio_nll`로 보고하며 주지표를 대체하지 않는다.

모든 거리와 거리별 결과, calibration, Top5 및 canonical 최대6조합 보조지표를 보고하되 gate를 바꾸지 않는다. 다섯 구간별 최근 mean/n, 실제 과거 슬롯 source IDs/date, raw quality-selected endpoint time/status, 계산값, eligible/null reason, target mean/n을 사람이 추적할 수 있게 저장한다. 예시 행은 outcome을 보지 않은 안정된 key 정렬 규칙으로 선택한다. Odds, ticket selection, jockey, pair model, finishing-order model, 운영 승격은 이번 실험 범위가 아니다.

## 현재 검토 상태와 고정 예정 hash

이 계약의 원천 schema, status domains, full-race point masks, exact T−2 checks, source fingerprint parity, segment mask logic 및 availability counts는 source worker의 완료된 `source_audit.json`와 snapshot hash를 확인한 뒤 preflight receipt와 준비 잠금에 확정한다. 이때까지 root fit approval는 존재하지 않으며 후보 fit은 금지다. 준비 잠금은 baseline model/features/score/lineage hashes, new source bundle hashes, code/contract hashes, bootstrap hash, cohort/split counts를 고정한다. 운영 model, registry, database는 변경하지 않는다.
