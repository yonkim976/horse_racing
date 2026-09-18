# 제주마 말 중심 예측모델 V1 실행 지시문

아래 지시를 하나의 작업으로 수행하라. 이 작업의 목적은 문서 검토나 추가 감사에서 멈추는 것이 아니라, 최신 제주마 연구 DB로부터 누수 없는 말 상태 데이터셋을 만들고 실제 모델을 학습·평가하여 재현 가능한 제주마 V1 후보를 제출하는 것이다.

## 역할과 최종 목표

너는 `/Users/kimyongjin/Desktop/horse_racing` 프로젝트에서 제주마 전용 말 중심 예측모델 V1을 구현하는 담당자다.

최종 목표는 각 제주마의 경주 직전 상태를 게임 캐릭터의 능력치처럼 여러 축으로 추정하고, 같은 경주의 실제 출발마들을 경쟁시켜 합계 1인 우승확률을 출력하는 것이다. 능력 상태와 우승확률을 구분하라.

```text
말의 장기 기본 능력
+ 거리 적성
+ 초반·중반·후반 구간 능력
+ 최근 컨디션과 휴양 효과
+ 과거 조교·주행심사·진료 신호
+ 이번 경주의 사전 조건
+ 불확실성과 경기력 변동성
= 이번 경주의 잠재 성능분포

같은 경주의 잠재 성능분포들을 경쟁
→ 경주 내 합계가 1인 우승확률
```

이번 V1의 중심 질문은 다음과 같다.

> 제주마 한 마리의 과거 결과·시간·구간·훈련 상태만으로 경주 직전 능력 상태를 만들었을 때, 단순 기준선과 기존 제주 모델보다 미래 경주의 승자 확률을 더 정확하게 예측할 수 있는가?

사용자에게 중간 승인을 반복해서 요청하지 말고, 되돌릴 수 있는 연구 코드·신규 데이터셋·신규 실험 artifact 생성은 끝까지 진행하라. 운영 모델·registry·기존 봉인 artifact는 변경하지 않는다. 심각한 데이터 손상, 필수 원천 부재, 학습 자체가 불가능한 계약 위반만 명확한 blocker로 인정한다. 일부 feature가 불완전하면 그 feature arm을 격리하고 앞 단계 모델을 계속 완성하라.

## 먼저 읽을 문서와 데이터

다음 문서를 먼저 읽고, 이미 확인된 사실을 다시 장기간 조사하는 데 시간을 쓰지 마라.

1. `/Users/kimyongjin/Desktop/horse_racing/docs/HORSE_ABILITY_MODEL_BLUEPRINT_2026-09-15.md`
2. `/Users/kimyongjin/Desktop/horse_racing/docs/JEJU_NATIVE_MODEL_V1_READINESS_2026-09-15.md`
3. `/Users/kimyongjin/Desktop/horse_racing/docs/JEJU_NATIVE_COMPLETE_RESEARCH_DB_REPORT_2026-09-15.md`
4. 기존 제주 baseline 문서와 코드:
   - `/Users/kimyongjin/Desktop/horse_racing/docs/JEJU_STANDALONE_V1.md`
   - `/Users/kimyongjin/Desktop/horse_racing/docs/JEJU_STANDALONE_V2.md`
   - `/Users/kimyongjin/Desktop/horse_racing/src/horse_racing/analysis/dataset.py`
5. 최신 연구 DB:
   - `/Users/kimyongjin/Desktop/horse_racing/data/research/jeju_native_text_phase2_db_20260915/jeju_native_text_phase2.sqlite3`
   - 기준 SHA-256: `0f2871c2a8f931bb968d8bf7086c27f0644c0ef7332b41b7a1bd85ff637c638f`

작업 전 저장소의 `AGENTS.md`와 현재 git 상태를 확인하라. 여러 작업자가 공유하는 dirty workspace이므로 관련 없는 변경을 수정·삭제·정리하지 말고, 기존 파일을 덮어쓰지 말며, 신규 버전 경로를 사용하라. 연구 DB는 읽기 전용으로 열어라.

## 이미 확인된 데이터 사실

다음은 재확인이 필요한 가설이 아니라 현재 작업의 출발점이다.

- 명시적 제주마 `제` 경주: 9,423경주·92,208출전행, 2002-07-28~2026-09-12.
- 기본 정상 경주 집합: 9,288경주.
- 공식 ID가 완결된 사후 실제 출발 확인 집합: 90,177행.
- 정상 착순 1~89: 89,960행.
- 실격 코드 91: 162행.
- 주행중지 코드 92: 55행.
- 미출주 코드 93/94/95: 690행.
- 1착 동착: 13경주.
- 공식 ID 미해결 29행과 양수 정상 결과가 없는 135경주·1,316행은 격리돼 있다.
- `record_status`만으로 라벨을 만들면 안 된다. 코드 91 일부가 양수 시간 때문에 `normal_completed`로 저장돼 있다.
- 과거의 정확한 T-30 출전집합은 복원할 수 없다. 따라서 역사 연구는 `retrospective confirmed-starter conditional`이라고 명시한다.
- 기존 제주 Parquet은 최신 연구 DB에서 재생성되지 않았고 DQ/DNF를 제외하며 feature가 혼합돼 있으므로 새 모델의 기반 데이터셋으로 사용하지 않는다. 비교 baseline으로만 보존한다.
- `source_row.normalized_json`에는 대상 경주의 착순·완주시간·구간·최종 배당이 함께 들어 있으므로 자동 평탄화나 `SELECT *` 기반 feature 생성을 금지한다.
- 2023년 이후에는 과거 조교·주행심사·구간·마체중 기록의 밀도가 충분히 높다. 진료 사건이 없는 것은 건강함의 정답이 아니며, 원천 미관측과 사건 0회를 구분해야 한다.
- 한라마 `한/래`는 이번 모델의 target, 학습 결과, 능력 척도에서 제외한다. 이름이나 추정으로 제주마에 편입하지 않는다.

## 모집단과 라벨 계약

새 builder는 제주마 명시 경주만 처리한다. 모델 평가의 기본 모집단은 공식 ID가 완결된 정상 경주의 사후 실제 출발 확인 집합이다.

- 착순 1~89: 정상 완주.
- 코드 91: 실격. `win/topK=0`; 정상 순위와 완주시간 auxiliary target은 mask.
- 코드 92: 주행중지. `win/topK=0`; 정상 순위와 완주시간 auxiliary target은 mask.
- 코드 93/94/95: 미출주. confirmed-starter 모델에서 제외하고 0 라벨을 부여하지 않음.
- 코드 98/99, 결과 미확정·상충·경주 무효·의미 불명: 학습과 평가에서 제외하고 이유를 보존.
- 동착 우승: winner set을 보존. winner-set NLL은 우승자 확률의 합에 적용하고, soft-label CE를 사용할 경우 각 우승자에 `1 / 우승자 수`를 준다.
- 정상 출전행을 inner join 누락으로 조용히 줄이지 말고, 예상 키와 최종 키의 missing/extra/duplicate를 fail-closed 검사한다.

동일한 라벨 adapter를 데이터 생성, 학습, 평가에서 공유하고 실제 제주 특수코드 표본을 회귀 테스트에 포함하라.

## 시점과 누수 방지 계약

모든 상태 feature는 대상 경주가 시작되기 전에 알 수 있었던 과거만 사용한다.

1. 기본 V1에서는 같은 날짜의 결과 순서를 입증하지 못하므로 `history_event_date < target_event_date`를 사용한다. 같은 날 앞 경주 결과를 소급 사용하지 않는다.
2. 대상 경주의 `ord`, 착순, `rcTime`, 구간, 최종 `winOdds/plcOdds`, 사후 심판보고서, 당일 이후 조교·진료를 feature로 사용하지 않는다.
3. 과거 완료 경주의 결과·시간·구간·마체중·주로는 그 이후 경주의 역사 feature로 사용할 수 있다.
4. 첫 day-before 말 중심 모델에서는 대상일 마체중, 당일 주로 상태, 당일 배당을 제외한다. 이후 별도 T-30 arm에서만 추가한다.
5. 대상 결과를 수정·삭제하거나 미래 경주를 추가해도 그보다 앞선 모든 상태 feature가 bit-for-bit 또는 고정 tolerance 내에서 변하지 않아야 한다.
6. 문자열 이름으로 ID를 보충하지 않는다. 공식 ID와 검증된 crosswalk만 허용하고 미해결은 격리한다.
7. feature는 명시적 allow-list로 생성한다. 금지 열이 입력 schema에 들어오면 조용히 무시하지 말고 실패시킨다.
8. fold별 기준시간, speed par, day variant, scaler, encoder, imputer와 calibration은 해당 fold의 과거 학습 데이터로만 적합한다.

## 상태 생성과 계수 학습을 분리하라

매 출전 직전에 말 상태를 한 행으로 저장하라. 최소 상태 schema는 다음을 포함한다.

```text
race_id, entry_id, horse_id, event_date, venue, distance, field_size,
ability_mean_pre, ability_uncertainty_pre,
distance_suitability_pre,
early_speed_pre, cruising_speed_pre, finish_stamina_pre,
recent_form_pre, performance_variability_pre,
days_since_last_start, normal_history_count, usable_time_count,
training_observed, trial_observed, medical_observed,
source_quality, regime,
label_win, label_top2, label_top3, finish_target_mask, time_target_mask
```

여기서 상태 생성은 각 말의 그 시점 능력값을 만드는 과정이고, 계수 학습은 여러 경주에서 어떤 상태가 승률에 얼마나 중요한지 배우는 과정이다. 두 과정을 한 함수나 대상 결과 기반 집계로 섞지 마라.

- 상태 업데이트 전 값과 경기 결과 반영 후 값을 구별한다.
- 예측행에는 반드시 `*_pre` 값만 들어간다.
- 신마는 제주마 모집단 사전분포에서 시작하고 불확실성을 크게 둔다.
- 장기 휴양은 과거 능력을 임의로 삭제하지 말고 평균 쪽으로 수축하거나 불확실성을 늘리는 후보로 처리한다.
- 적은 거리 경험의 적성은 전체 제주마 평균으로 수축한다.
- 실격·주행중지는 패배 사건에는 포함하지만 정상 시간·순위 능력 업데이트에는 사용하지 않는다.
- 오래된 400m 경주는 현재 target에서 제외하되, 과거 이력으로 쓸 경우 별도 거리 상태로만 보존한다.
- 원시 시간을 거리 간 직접 비교하지 않는다. 거리·시대·주로를 고려한 과거 기준 대비 잔차를 사용한다.

능력치는 해석 가능한 연구 출력이다. 사람이 임의로 0~100 점수를 붙이지 말고, 학습 가능한 잠재 척도와 평균·불확실성을 저장하라. 사용자용 0~100 표시가 필요하면 원래 값과 별도로 단조 변환한 표시열만 추가한다.

## 반드시 실행할 비교 모델

모든 arm은 같은 fold, 같은 경주, 같은 출전집합, 같은 평가 코드로 비교하라.

### 기준선

1. `U0_UNIFORM`: 같은 경주의 모든 말에 `1 / field_size`.
2. `RATING_ONLY`: 대상 시점에 사용 가능한 공식 레이팅만 사용. 레이팅 결측 정책을 명시하고 이것을 잠재 능력의 정답으로 취급하지 않음.
3. `ELO_BASELINE`: 상대 편성과 최근성을 반영하는 기존 multiplayer Elo를 누수 없이 재계산.
4. 가능하면 기존 제주 V2를 동일 평가 키에 재추론한 `LEGACY_V2` 비교값. 재현 불가능하면 이유와 공통 평가 가능 범위를 정확히 보고하고 핵심 V1 작업은 계속한다.

### 말 중심 능력 arm

1. `H0_RESULT`
   - pre-race 동적 기본 능력과 불확실성
   - 과거 상대 수준과 상대 결과
   - 출전 수, 휴양 기간, 거리 경험
   - 최근 성적은 목표 경주의 결과를 포함하지 않는 엄격한 과거 집계
2. `H1_TIME_SECTION`
   - H0 + 거리·시대·과거 주로 기준으로 보정한 완주시간
   - 검증된 제주 구간만 사용한 초반/순항/후반 능력
   - 의미나 계측 정의가 불명인 구간은 추정 변환하지 않고 제외
3. `H2_STATE`
   - H1 + 과거 일별 조교, 출발조교, 주행심사, 진료 사건
   - 절대량과 말 자신의 평소 대비 변화량을 구분
   - 관측되지 않음, 관측됐지만 0회, 실제 사건 있음 상태를 구분
4. `H3_CONDITION`
   - H2 + 대상 경주의 사전에 알려진 거리, 등급/레이팅 조건, 부담중량 등
   - 현재 부담중량의 출처와 해당 시점 이용 가능성을 확인
   - 대상일 마체중·당일 주로·배당은 포함하지 않음

각 단계는 이전 단계에 feature 묶음을 하나만 추가하는 소거실험이어야 한다. `H1`이 실패해도 `H0` 결과를 제출하고, `H2`의 한 원천이 불완전하면 그 원천만 제거한 `H2_PARTIAL`을 시험하라.

학습기는 최소 두 종류를 같은 feature arm에서 비교하라.

- 안정적인 tabular 기준: LightGBM binary objective 후 경주별 확률 정규화.
- 경주 단위 후보: Plackett-Luce/race-softmax 계열 또는 동등한 group-aware objective.

E5-B의 서울 연구에서 race-softmax가 우월하지 않았으므로 제주에서도 유리하다고 가정하지 말고 실측 비교한다. 두 학습기의 fit/tune/calibration 데이터와 평가 키를 일치시킨다. 모델 규모보다 시간 누수 방지와 소거실험을 우선한다. 단일 seed만으로 후보를 확정하지 말고 개발 단계에서 적은 수의 사전 고정 seed를 사용하되, 모델 탐색 횟수와 총 fit 횟수를 기록한다.

## 시간 분할

다음 원칙을 기본 protocol로 파일에 먼저 봉인한 후 학습한다.

1. `2002-07-28~2018-08-30`: 능력 상태 burn-in. 오래된 경주는 상태 초기화에 사용하되 현행 계수 학습에 강제로 포함하지 않는다.
2. `2018-08-31~2024-12-31`: 계수 학습 기본 후보. expanding-window 방식과 시대/최근 가중치를 사용한다.
3. `2025-01-01~2025-12-27`: 개발 선택 및 월/분기 walk-forward 평가. calibration도 시간순으로 분리한다.
4. `2025-12-28`: 레이팅 일괄 조정 경계로 별도 regime.
5. `2026-01-01~2026-09-12`: protocol·feature·hyperparameter를 동결한 뒤 한 번만 계산하는 역사 평가. 이미 데이터 품질 감사에서 2026년 결과 일부를 확인했으므로 `독립 prospective test`라고 부르지 말고 `frozen historical evaluation`이라고 부른다.
6. 진정한 최종 평가는 이후 경주의 실제 출전표를 기준으로 경기 전에 남기는 prospective prediction ledger에서 수행한다. 이번 작업에서는 운영 발행을 연결하지 않는다.

오래된 자료의 가치를 확인하기 위해 2025 개발 구간에서 다음 세 history 정책도 비교하라.

- `RECENT_FIT`: 2023~2024만 계수 학습.
- `LONG_FIT`: 2018-08-31~2024 계수 학습.
- `BURNIN_ONLY_OLD`: 2002~2018-08-30은 상태 초기화에만 사용하고 계수 학습 제외.

데이터가 실제 경계와 맞지 않으면 날짜를 임의 변경하지 말고, 변경 근거와 경주 수를 protocol에 기록한다.

## 평가와 후보 판정

주 지표는 경주별 winner-set NLL이다. 보조지표는 다음을 포함한다.

- Top1 적중률.
- 우승마 Top3/Top5 기대 포함률. 확률 경계 동점은 입력 순서와 무관한 기대 포함률로 계산.
- 출전행 binary NLL과 Brier.
- reliability/calibration 요약.
- 거리, 등급, 연도/월, 출전두수, 신마/기성마, 장기 휴양, regime별 손실.
- 우승자 동착 경주와 DQ/DNF 포함 경주의 별도 진단.

모든 비교는 공통 평가 경주와 출전행 coverage 100%를 요구한다. 누락·추가·중복·비유한 확률·음수 확률·경주별 확률합 위반을 실패 처리한다. 후보 간 winner-set NLL 차이에 대해 다음 두 구간을 모두 계산한다.

- 경주 단위 paired bootstrap 95% CI.
- 경주일 cluster bootstrap 95% CI.

점추정치가 좋아도 두 CI가 0을 포함하면 우월성을 확정하지 않는다. 그러나 연구를 중단하지 말고, 어떤 상태 묶음이 어느 조건에서 도움이 되거나 악화됐는지 진단하고 가장 단순한 비열등 후보를 남긴다. TopK만 좋아지고 NLL이 악화되면 확률모델 승격 근거로 삼지 않는다. 배당수익 연구는 이번 범위에서 제외한다.

## 구현과 검증의 최소 요건

새로운 모듈과 artifact 이름에는 `jeju_native_horse_v1` 또는 동등하게 명확한 namespace를 사용하라. 기존 E1~E10, 서울 confirmed-starter, 기존 제주 V1/V2 artifact를 덮어쓰지 않는다.

반드시 다음을 구현하고 검사하라.

1. 최신 연구 DB 전용 불변 entry-level dataset builder.
2. 제주 특수착순·미출주·동착 label adapter.
3. 날짜순 pre-race state builder와 update-after-race 구조.
4. fold별 fit/transform 경계가 분리된 training pipeline.
5. 경주별 확률 정규화와 winner-set 평가기.
6. 저장 모델을 reload해 원 예측과 동일한지 검사.
7. dataset, protocol, feature allow-list, source DB, model, prediction의 SHA-256 manifest.
8. 실행 fit 횟수, seed, iteration, calibration 선택을 기록한 run ledger.
9. 최소 회귀 반례:
   - 신마와 장기 휴양마.
   - 처음 출전하는 거리.
   - 동착 우승.
   - 실격, 주행중지, 미출주, 취소/미확정.
   - 대상 결과 삭제·교환·변경.
   - 미래 결과행 추가.
   - 입력 순서 역전.
   - 같은 날 복수 경주.
   - 이름은 같지만 ID가 다른 말.
   - feature 원천 결측과 실제 0회.
   - JSON에 금지된 대상 결과/최종 배당 열이 존재하는 경우.
10. 관련 테스트, Ruff check/format, `git diff --check`. 전역 기존 오류는 관련 변경과 구분해 보고한다.

테스트가 구현을 그대로 복제하는 형식에 그치지 않게 하고, 실제 연구 DB의 고정 소표본과 합성 반례를 함께 사용하라. 전체 DB 전수 검증은 필요한 핵심 계약에 집중하고, 같은 검사를 이름만 바꿔 반복하지 않는다.

## 필수 산출물

작업을 완료하면 최소 다음을 남긴다.

1. **Protocol**: 학습 전 봉인한 모집단·시간분할·feature arm·seed·fit 예산·평가 계약 JSON.
2. **Dataset**: entry-level Parquet, pre-race horse-state Parquet, manifest와 schema/coverage 보고서.
3. **Models**: U0/RATING/ELO와 실제 학습한 H0~H3 후보 bundle.
4. **Predictions**: 공통 평가 키의 각 arm 확률, 경주별 손실, 상태 능력치와 우승확률을 분리한 표.
5. **Comparison**: 전체 지표, ablation, 기간/거리/regime별 진단, 두 bootstrap CI가 포함된 기계 판독 JSON.
6. **Run ledger**: 모든 fit과 calibration 실행 수.
7. **Artifact manifest**: 입력 DB와 신규 산출물 hash.
8. **Tests**: 핵심 시간·라벨·확률 계약 회귀 테스트.
9. **최종 한국어 보고서**: 모델이 무엇을 배웠는지, 가장 나은 후보, 개선의 통계적 범위, 실패한 feature, 역사 연구 한계, 다음 prospective 단계.
10. **사용 예시**: 특정 과거 경주 하나에 대해 각 말의 `ability_mean`, 거리 적성, 최근 상태, 불확실성, 최종 점수와 우승확률이 어떻게 만들어졌는지 사람이 읽을 수 있는 예시.

최종 보고서에는 반드시 아래 표를 포함하라.

| Arm | 평가 경주/행 | Winner-set NLL | Brier | Top1 | Top3 | Top5 | 기준 대비 NLL 차이 | race CI | race-day CI |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|

그리고 다음 질문에 명시적으로 답하라.

1. 과거 제주마 능력 상태가 단순 Elo보다 실제로 좋아졌는가?
2. 시간·구간 정보가 결과 이력에 증분 정보를 주었는가?
3. 조교·주행심사·진료가 시간·결과 모델에 증분 정보를 주었는가?
4. 2000년대 자료는 계수 학습에도 도움이 됐는가, 아니면 burn-in에만 유효했는가?
5. 어떤 거리·시대·말 유형에서 모델이 가장 약한가?
6. 현재 후보를 이후 실제 사전 예측 원장에 올릴 가치가 있는가?

## 범위 밖

이번 V1에는 다음을 섞지 않는다.

- 한라마 `한/래` 경주.
- 기수, 말×기수, 조교사, 마주 효과의 본격 학습.
- 대상일 마체중, 당일 주로 상태, 최종 배당.
- 대상 경주의 심판보고서.
- 배팅 전략과 수익 최적화.
- 운영 registry/champion 변경 또는 실제 확률 발행.

다만 다음 단계가 쉽게 이어지도록 모델 입력과 상태 schema는 기수·조교사·마주 및 T-30 정보 arm을 나중에 조인할 수 있는 안정된 `race_id/entry_id/horse_id/cutoff` 키를 보존하라.

## 완료의 정의

이 작업은 다음 조건을 모두 충족해야 완료다.

- 새 데이터셋과 말별 pre-race 상태가 생성됐다.
- U0, RATING_ONLY, ELO_BASELINE과 최소 H0/H1이 실제 학습·평가됐다.
- 조교 원천이 계약을 통과하면 H2도 평가됐고, 실패하면 격리 사유와 H1 결과가 제출됐다.
- 사전 조건 원천이 계약을 통과하면 H3도 평가됐고, 실패하면 격리 사유와 앞 단계 결과가 제출됐다.
- 2025 walk-forward와 동결된 2026 역사평가 결과가 재현 가능하게 저장됐다.
- 모델 bundle reload, 확률 계약, 시간 누수 반례와 hash manifest가 통과했다.
- 운영 경로는 변경되지 않았다.
- 성능이 개선되지 않은 경우에도 결과를 숨기지 않고 가장 단순한 기준선과 실패 원인을 제출했다.

계획서만 작성하거나 “독립 승인 전 학습 보류”로 끝내지 마라. 이 지시는 격리된 연구 데이터셋 생성, 실제 모델 fit, 역사 성능 비교까지 승인한다. 장시간 감사는 실제 실패를 발견했을 때만 좁게 수행하고, 정상적으로 통과한 항목은 구현과 실험으로 즉시 진행하라.
