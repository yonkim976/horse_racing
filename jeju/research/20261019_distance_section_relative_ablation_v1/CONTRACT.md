# F1_STYLE6 거리별 구간 상대기록 확장 계약

이 계약은 2026-10-19 승인 후향 연구를 위한 후보 사전 잠금 초안이다. 저장 `F1_STYLE6` 기준선의 30개 입력·저장 모델·점수는 변경하지 않는다. 후보는 전체 52,155행/5,206경주 학습 표본에서 신규 10개 입력을 더한 단일 40열 모델이다. root의 hash 고정 사전 fit approval 전에는 후보 학습 또는 후보 결과지표 산출을 실행하지 않는다.

## 저장 기준선

입력 근거는 `jeju/research/20261010_style_history_ablation_v1/outputs/features.parquet`와 `F1_STYLE6_{2024,2025,2026}` 저장 모형·메타·calibration/evaluation score다. 기준선은 저장된 모형 재로딩으로만 재현한다. 이전 study의 whole-DB hash 검증 루틴이나 DB connection을 호출하지 않는다. 기준선 평가 코호트는 17,412출전/1,779경주이고, canonical 최대6조합은 기존 report의 `canonical_six_combinations.csv` 규칙을 사용한다.

10개 기존 입력 외 필드를 모델 입력으로 추가하지 않는다. 원천 원시 키, API profile, 현재 말 이름/나이/성별, 측정 상태, target/slot lineage와 benchmark provenance는 감사용 문맥이며 모델 입력에 포함하지 않는다. 기존 30개 입력은 대상 말과 기존 순서대로 byte/value 수준에서 보존하고, 기존 값만 추출한 행렬은 동일성 검사를 통과해야 한다.

## 원천 소비 경계와 benchmark 계산

모델 입력은 새 `jeju/research/20261019_distance_section_relative_source_v1/` 동결 원천 번들만 사용한다. 새 실험은 DB를 열지 않는다. 원천 파일 목록·크기·SHA-256·native ID·시점·검토 상태는 source manifest/audit와 본 study lock에 핀한다. 원천 schema / status allowlist / eligibility rationale가 안정되기 전 feature preflight는 PASS로 표시하지 않는다.

원천 event participant rows는 제주(native)·`started=True`·공식 경주/출전/말 식별자, 거리, event date, `valid_time` 및 raw five intervals/status/provenance를 보존한다. 각 구간 eligibility는 source worker가 명시한 point-quality mask와 유효 endpoint gate를 요구하며, feature core는 유한 양수 초 및 baseline `valid_time=True`를 독립 검증한다. 참가 행을 임의로 profile/마명으로 연결하거나 판정·거리/구간 정의를 추정하지 않는다.

대상거리는 900, 1000, 1110, 1200m이다. 각 source race × distance × segment의 유효 출전자 구간시간 중앙값을 계산한다. 기준값을 구성한 과거 event 수는 단일 경주별 median 단위로 센다. 원천 event `s` 기준값은 같은 거리와 segment의 source race medians 중 race_date가 `s_date−2일` 이하인 값을 같은 가중치로 평균한 expanding mean이다. 20개 미만이면 기준값과 잔차는 NULL이다. 같은 날짜·경주 본인·미래 자료는 사용하지 않는다. `s_date−2` 경계는 포함한다. source rows에서 event identity/date/distance가 유일한지와 duplicate/eligibility status를 사전 감사한다.

5개 구간의 거리별 명목 길이(m)는 원천 요약값이다. 모델 입력은 초 단위 잔차를 그대로 사용하며, 명목 길이로 나누거나 비율·속도로 바꾸지 않는다.

| 거리 | S1F | S1F→3C | 3C→4C | 4C→G1F | G1F |
|---:|---:|---:|---:|---:|---:|
| 900m | 200 | 100 | 200 | 200 | 200 |
| 1000m | 200 | 200 | 200 | 200 | 200 |
| 1110m | 210 | 300 | 200 | 200 | 200 |
| 1200m | 200 | 400 | 200 | 200 | 200 |

기준 roster는 동결 F1 source snapshot의 55,860개 시작 출전과 5,668개 경주를 유지한다. 원천 감사에서 확인된 현재 DB의 추가 54개 출전은 전체 경주 품질 마스크 확인에만 쓰고 기준 median roster에 넣지 않는다. 초기 7개 경주는 현재 마스크 roster 완전성이 확인되지 않아 관련 구간을 fail-closed 처리한다. 이들 경주의 median은 동결 roster에서 적격인 출전자만으로 계산되며 당시 전체 field median을 대표하지 않을 수 있다. 이 제한은 동결 source audit에서 경주별로 확인한다.

원천 상대잔차는 `B(s) − raw_interval(s)`로 정의한다. `B(s)`, cutoff, prior eligible race count, earliest/latest reference race date, interval raw seconds, participant eligibility and source IDs are separately stored so that source provenance remains inspectable. Missing benchmark, failed quality/status, nonpositive or non-finite interval, baseline `valid_time=False`, or no exact lineage match yields NULL eligible residual; no raw-seconds fallback, cross-distance transfer, same-race normalization or backfill is permitted.

## 대상 lineage와 10개 열

전체 model target table follows the saved F1 input row order. Target roster must equal the exact rows in the four supported distances and use official `api_record_id`, `race_id`, `horse_id`, race date, distance, T−2 cutoff and saved `last5_same_source_ids`. The cutoff must equal race_date minus two calendar days. Existing source last5 sequence is kept as stored (oldest to newest in the verified schema); all and only those slots remain, including invalid times. Each slot's official horse ID and distance must equal its target; its date must not exceed cutoff.

Feature names are fixed in `feature_core.py` as:

- `hist_relative_seg_1_mean5`, `hist_relative_seg_1_n`
- `hist_relative_seg_2_mean5`, `hist_relative_seg_2_n`
- `hist_relative_seg_3_mean5`, `hist_relative_seg_3_n`
- `hist_relative_seg_4_mean5`, `hist_relative_seg_4_n`
- `hist_relative_seg_5_mean5`, `hist_relative_seg_5_n`

Each target segment mean is the arithmetic mean of eligible benchmark-minus-raw residuals among that target's exact last5 same-distance actual start slots. n is the eligible slot count in `[0,5]`. If n=0, mean is NULL and n is 0. If target distance is outside the four supported distances, both columns are NULL, including n. The feature core must preserve the exact original 55 input/source columns and 52,155 row order.

## Fit, evaluation, and freeze

Year `Y` uses initial train 2017..`Y−3`, validation `Y−2`, refit through `Y−2`, calibration `Y−1`, and test `Y`; all partitions are race-date grouped and unchanged from saved F1_STYLE6. Fitting uses saved parameters and seed 20261008, Top3 binary labels, race weights `1/field_n`, maximum 200 rounds, early stopping 25 rounds, existing train-only categorical vocabulary and temperature function. Candidate is exactly 3 final year models, 6 LightGBM calls, and 3 temperature optimizations. No baseline refit.

Only after root approval of source, preflight, features, code, fixed-date bootstrap SHA and lock may the single fit be executed. Model/evaluation-score/Tau files are frozen before report computation. The evaluator uses the predeclared 269-date schedule with 2,000 resamples, primary 4-distance race-equal Top3 runner binary log loss and Brier, candidate-minus-saved-baseline paired differences. Both point deltas must be below zero and at least one 95% paired date-bootstrap CI upper bound must be below zero. Year/distance/all-distance results, calibration, Top5 and same canonical max6 trio rules are secondary. No result-dependent fit, reconfiguration, or feature variants are allowed.

The source event date is not a verified public-release timestamp. Date−2 is the agreed retrospective cutoff, not proof that every source record was available to a live forecaster at that time. Any use of later-loaded/edited source information must be documented as a hindsight limitation.
