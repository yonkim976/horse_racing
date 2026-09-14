# E1 사전 출전집합·DNF 감사와 연구 계약

- 감사 시각: 2026-09-11 KST
- 대상: 서울, 완료 경주, 2025-01-04~2026-05-31
- 예측 시점: 예정 출발 30분 전(T-30m)
- 판정: **상태·라벨 계약의 확인 가능한 부분과 격리 함수는 구현 가능. 과거 `F_t`의 정확 복원, 데이터셋 전환, 성능 비교와 재학습은 보류.**

## 1. 범위와 불변 사항

실제 DB·원문·결과 조회의 날짜 상한을 SQL에서 먼저 2026-05-31로 제한했다. 2026-06-01 이후 결과나 성능을 조회하지 않았다. 기존 production DB, 데이터셋, run, comparison, 모델, 운영 예측·UI와 `apply_label_policy`의 기본 동작은 변경하지 않았다. 새 모델 학습·calibration·seed 탐색도 하지 않았다.

이 문서에서 `F_t`는 단순히 현재 DB에서 `scratched=0`인 행이 아니다. `t = scheduled_at_ms - 30분`에 공개되어 있었고 그 시점까지 취소되지 않았다고 증명할 수 있는 출전 키의 집합이다.

## 2. 네 출전집합의 실측 관계

대상 경주의 현재 사후 DB를 읽으면 다음 관계가 성립한다.

```text
현재 사후 출전행 C (15,846)
├─ 사후 확인 미출주 D (267: 코드 93·94·95)
└─ 실제 출발 확인 A (15,579)
   ├─ 정상완주 N = 기존 학습·평가 집합 (15,531)
   └─ 출발 후 특수결과 (48: 실격 1 + 주행중지 47)

F_t: 정확한 크기와 구성 복원 불가
```

| 집합 | 경주 | 행 | 근거와 한계 |
|---|---:|---:|---|
| 현재 사후 `race_entries` | 1,488 | 15,846 | 결과·취소 백필이 끝난 현재 상태 |
| 현재 `scratched=0` / 실제 출발 확인 | 1,488 | 15,579 | 정상완주 15,531 + 실격·주행중지 48 |
| 정상완주 / 기존 dataset | 1,488 | 15,531 | 사후 결과에 조건부인 집합 |
| 정확한 `F_t` | — | — | T-30m snapshot과 취소 effective time이 없어 복원 불가 |

미출주가 있는 경주는 246개, 실제 출발 후 실격·주행중지가 있는 경주는 42개다. 따라서 기존 학습집합은 실제 출발집합보다도 48행 작다. 다만 267개의 취소가 T-30m 이전인지 이후인지는 현재 자료로 나눌 수 없으므로 `F_t`가 15,579행 또는 15,846행이라고 단정하지 않는다.

현재 live base query는 결과와 조인하지 않고 `race_entries.scratched=0`을 사용한다. 이를 사후 상태에서 재생하면 15,579행이지만, 실제 live 시점에는 당시 mutable boolean 값에 의존한다. 예측 발행 원장은 포함된 `race_entry_id`를 불변 보존하나 이번 대상 기간의 live 원장 run은 0개다.

## 3. 기존 manifest의 267·48 재현

새 canonical manifest와 동일한 후보 범위·필터 순서를 적용했다.

1. 서울 완료 경주의 현재 출전행 15,846개를 후보 분모로 둔다.
2. `scratched=true` 267개를 먼저 제외한다.
3. 남은 행에서 `finish_position >= 90`인 48개를 제외한다.
4. 결과행 결측과 착순 NULL은 각각 0개다.
5. 정상완주 기준 5두 미만 및 1착 없는 경주는 0개다.
6. 최종 15,531행·1,488경주가 남는다.

따라서 manifest의 `scratched=267`, `special_finish_code=48`은 위 사후 후보집합과 순서에서는 정확히 재현된다. 이 숫자를 T-30m 취소 수 또는 전체 역사 범위의 DNF 수로 해석해서는 안 된다.

## 4. `F_t` 원천과 시간 증거 감사

대상은 141개 서울 경주일이다. 해당 날짜를 요청한 원문은 출전표 143개, 취소 141개, AI 결과 141개, 상세 결과 141개가 남아 있다. 그러나 출전표의 수집 응답 시각은 2026-08-21 22:26~23:29 KST이고, 취소 원문은 2026-08-25 15:48~19:26 KST다. 모두 대상 경주가 끝난 뒤의 백필이다.

| 시간 필드 | 실제 의미 | `F_t` 증거로서의 한계 |
|---|---|---|
| `race_date_local` / 요청 날짜 | 경주 event date | 공개시각이 아님 |
| `SourceDocument.requested_at_ms` | 수집기 요청 시각 | 원천이 처음 공개된 시각이 아님 |
| `SourceDocument.retrieved_at_ms` | 응답 수신 시각 | 이보다 늦게 공개됐다는 뜻은 아니나 과거 상태도 증명하지 못함 |
| `RaceScratch.observed_at_ms` | 수집·DB 관측 시각 | 취소 effective/event time이 아님 |
| published/effective time | 저장되지 않음 | 사전 취소와 T-30m 이후 취소 분리에 필수 |

- T-30m까지 수집된 출전표 원문이 있는 대상 경주: **0/1,488**
- T-30m까지 관측된 취소 행: **0/267**
- 대상 기간의 불변 live 예측 원장: **0 run**

사후 출전표 payload가 당시 출전표를 그대로 돌려준다고 가정하면 후보집합을 만들 수는 있다. 그러나 API의 historical response semantics와 published revision이 보존되지 않았으므로 1,488경주 모두 **가정 의존 복원**이고, 그 가정 없이는 정확한 `F_t`가 **복원 불가능**하다. 현재 `scratched` boolean을 과거 시점 값처럼 사용하는 것도 금지한다.

141개 경주일에서 가장 먼저 수집한 사후 출전표 원문의 `(경주일, 경주번호, 마번)`
15,846개는 현재 DB 15,846개와 정확히 일치했다. 중복·누락·추가 키와 원문 SHA-256
불일치는 모두 0이다. 이는 현재 사후 후보집합 C의 원문 재현성만 확인하며, 원문 자체가
경주 후 수집됐으므로 T-30m membership을 증명하지 않는다.

## 5. 상태 계약

### 5.1 대상 기간 실측 매핑

| 코드·비고·flag | 행 | 상태 | 실제 출발 | win/topK | 순위·기록 보조 target |
|---|---:|---|---|---|---|
| 착순 1~89, 비고 없음, scratched=0 | 15,531 | 정상완주 | 예 | 공식 착순으로 정의 | 관측값 사용 가능 |
| 91 + `실격`, scratched=0 | 1 | 실격 | 예 | 확정 비입상 0 가능 | 공식 정상순위는 mask; 기록 존재 여부 별도 |
| 92 + `주행중지`, scratched=0 | 47 | 실제 출발 후 DNF | 예 | 확정 비입상 0 가능 | 순위·완주시간 mask |
| 93 + `출발제외`, scratched=1 | 3 | 미출주 | 아니오 | 자동 0 금지 | mask |
| 94 + `경주제외`, scratched=1 | 162 | 미출주 | 아니오 | 자동 0 금지 | mask |
| 95 + `출전취소`, scratched=1 | 102 | 미출주 | 아니오 | 자동 0 금지 | mask |

전체 DB에서 확인된 99 + `경주취소`는 경주 취소/무효 상태지만 대상 서울 기간에는 0개다. 90·96·97·98 또는 코드와 비고가 맞지 않는 조합은 `unknown_special`로 보존한다. 특수착순 전체를 DNF로 합치지 않는다. `disqualified` flag는 대상에서 모두 false이고 실격은 코드·비고로만 확인되므로 flag 하나만 신뢰하지 않는다.

### 5.2 미출주의 시점 상태

93·94·95는 사후적으로 미출주임은 확인되지만 그 자체로 T-30m 이전 취소를 뜻하지 않는다.

- effective/positive observation이 T-30m 이전이면 `excluded_before_prediction`이다.
- effective time이 T-30m 이후로 확인되면 `included_then_withdrawn`이다.
- T-30m 뒤에 처음 관측됐고 effective time이 없으면 `unknown`이다. 늦은 관측을 과거 snapshot으로 소급하지 않는다.

이번 실데이터 267행은 마지막 경우다.

## 6. 확률 사건과 라벨 계약

### 6.1 확인 가능한 연구 사건

비취소·유효 경주에서 기본 우승 사건은 `F_t`에 속한 말 가운데 공식 우승자가 되는 것이다. 다음은 확인 가능한 부분이다.

- 정상완주는 공식 착순을 그대로 사용한다.
- 실제 출발 후 DNF와 실격은 win/top2/top3의 비입상 라벨을 줄 수 있다.
- DNF에 가짜 최하위 순위나 가짜 완주시간을 넣지 않는다.
- 결과 미수집·미확정과 모호한 특수코드는 0이 아니라 unknown이며 경주 평가 가능성을 별도로 판정한다.
- 경주 취소·무효는 확률 사건 자체가 성립하지 않아 loss에서 mask한다.

T-30m 이후 미출주 말을 예측 사건에서 0으로 둘지, 환불 후 조건부 집합으로 재정규화할지는 공식 정산 규칙과 목적에 따라 달라진다. 이번 E1에서는 확정하지 않고 라벨을 mask한다. 특히 사후 미출주를 T-30m 이전에 알았던 것처럼 행에서 제거하지 않는다.

### 6.2 동착·TopK·완주자 부족

대상에는 공식 동착 19경주/19그룹/38행이 있고 1착 동착은 3그룹이다. 공식 착순은 올림픽 스킵을 유지한다.

- winner NLL은 동착 우승자들의 `P(win)`을 합친 사건확률에 `-log`를 적용한다.
- `Σ P(win)=1`은 같은 `F_t`와 같은 평가 사건에 대해 검사한다.
- top2/top3는 공식 `position <= K`이므로 동착 때 양성 수가 K보다 많을 수 있다.
- 완주자가 부족하면 존재하지 않는 순위를 만들지 않는다. 정확 순서 TopK loss는 K개 공식 slot이 관측되지 않으면 mask한다.
- 경주 취소·무효는 확률합을 성능 loss로 평가하지 않는다.

## 7. feature와 offline/live 경계

`F_t`가 바뀌면 단순히 DNF 행만 추가되는 것이 아니다. 최소한 다음 값이 함께 다시 계산돼야 한다.

- `starters_at_prediction`과 최소 출전두수 판정
- `horse_number_pct`, gate/field band
- 부담중량 평균 차이, race z-score·rank 등 모든 경주 내 상대평가
- `known_style_share`, `front_runner_count`, `front_rival_count`, pace pressure
- field density, 출발번호·선행 적합도
- softmax/Plackett–Luce 확률 정규화와 조합확률

현재 offline dataset은 정상완주 N을 기준으로 `starters`와 상대 feature를 만들고, live 경로는 조회 시점의 `scratched=0` 집합을 기준으로 만든다. 두 경로는 같은 입력 사건을 보장하지 않는다. 후속 dataset은 먼저 불변 `F_t` 키를 만든 다음, 모든 경주 내 feature와 확률 정규화를 그 키에서 계산해야 한다.

## 8. 평가 계약

다음 두 검사를 분리한다.

1. **출전집합 적합성:** T-30m 공개 원천만으로 `F_t`가 완전하고 중복 없이 구성됐는가.
2. **결과 평가 가능성:** 경주가 유효하고 각 `F_t` 행의 정상완주/DNF/실격/미출주/unknown 상태가 확정됐는가.

불명확한 경주는 전체 분모에서 사라지지 않는다. `unknown_reason`과 함께 남기고 scored race 수를 별도로 센다. 결과행과 inner join해 행을 조용히 없애는 방식을 금지한다.

후속 통제 비교는 양쪽 모델이 다음을 모두 공유할 때만 가능하다.

- 동일한 불변 `F_t` 키와 `starters_at_prediction`
- 동일한 상태·라벨 mapping 및 post-cutoff withdrawal 사건
- 동일한 scored/unknown/void 경주 분모
- 동일한 기간·경마장·feature cutoff·모델 설정

정상완주 조건부 legacy NLL과 전체 출전집합 NLL은 서로 다른 사건이므로 직접 차감하지 않는다.

## 9. 격리 구현과 합성 반례

연구 전용 `pre_race_field_contract.py`에 다음 순수 함수를 추가했다. 기존 운영 경로에서는 호출하지 않는다.

- timestamped field evidence로 membership을 판정하고 unknown이면 fail closed
- expected/observed 키의 중복·누락·추가를 결합 전에 거부
- `F_t`에서 starters·마번 비율·선행 경쟁자 예시 feature 계산
- 정상완주, DNF, 실격, 미출주, 결과 미확정, 경주 무효, unknown special 분류
- 공식 동착 우승확률을 합한 winner NLL과 exact TopK 관측 가능성 판정

합성 테스트는 결과만 변경해도 `F_t`와 사전 feature가 불변인지, 사전/이후 취소, DNF/결과 미수집, 모호 코드, 늦은 관측, 경주 무효, 동착, 완주자 부족, 중복·누락·추가 키를 검사한다.

## 10. 앞으로 필요한 snapshot 계약

역사적 `F_t`를 추측하지 않으려면 다음을 새 불변 원장에 저장해야 한다.

1. 출전표 최초 공개, 모든 revision, 취소 event마다 원문과 SHA-256을 보존한다.
2. 각 행에 meet/date/race/entry/horse 키, 마번, 상태와 함께 `source_published_at`, `event_effective_at`, `observed_at`, `ingested_at`을 구분해 저장한다.
3. 매 snapshot에 완전성 flag, source revision, 예상 행 수를 기록하고 부분 응답을 완전한 출전집합으로 승인하지 않는다.
4. 각 경주의 T-30m에 최신 합법 revision을 seal하고 `F_t` 키 hash와 field-dependent feature hash를 예측 원장에 넣는다.
5. T-30m 이후 취소도 별도 event로 보존해 사전 취소와 섞지 않는다.
6. 결과 수집은 같은 `F_t`에 left join하고, 누락·추가·중복과 race void를 명시적으로 검증한다.

## 11. 후속 판정과 남은 미확정 사항

### 구현 가능

- 미래 경주의 immutable 출전표·취소 revision 저장
- T-30m sealed `F_t`와 key hash 생성
- 확인된 91~95·99 상태 mapping과 unknown 보존
- DNF/실격의 분류 target mask 및 비입상 label
- 동일 `F_t` 기반 feature·평가 completeness validator

### 검증 전 보류

- 사후 API 응답으로 2025~2026 `F_t`를 복원했다는 주장
- 267개 미출주의 T-30m 이전/이후 분할
- T-30m 이후 미출주의 예측 loss·환불/재정규화 규칙 확정
- 과거 데이터셋 전환, 재학습, 성능 비교와 운영 승격
- DNF 위험과 정상완주 조건부 능력의 2단계 모델 선택

추가로 기존 UI의 `SPECIAL_FINISH_LABELS`는 DB 실측 코드와 어긋나지만 운영 UI는 이번 범위에서 수정하지 않았다.

## 12. 제출 파일

- 기계 감사: `data/logs/pre_race_field_dnf_audit_e1_20260911.json`
- 행 단위 증거: `data/logs/pre_race_field_dnf_evidence_e1_20260911.parquet`
- 읽기 전용 감사기: `scripts/audit_pre_race_field_dnf_e1.py`
- 연구 계약 함수: `src/horse_racing/analysis/pre_race_field_contract.py`
- 합성 테스트: `tests/test_pre_race_field_contract.py`

## 13. 실행 검증과 공유 작업공간 상태

- E1 관련 Ruff: 통과
- E1 합성 테스트: `8 passed in 0.24s`
- 전체 pytest: `418 passed, 2 warnings in 10.36s`
- 전체 Ruff: 21건 실패. `scripts/analysis_finish_time_quality.py` 18건과
  `src/horse_racing/analysis/baselines.py`,
  `src/horse_racing/analysis/features/ability.py`,
  `tests/test_segment_correction.py` 각 1건이며 E1 파일에는 오류가 없다.
- E1 파일 대상 `git diff --check`: 통과
- 저장소 전체 `git diff --check`: 동시 UI 작업인
  `src/horse_racing/web/racecourse.py:347`의 EOF 빈 줄 1건으로 실패했다. 해당 파일은
  E1 범위 밖이므로 수정하지 않았다.

pytest 경고 2건은 기존 Starlette deprecation과 Polars sortedness 경고다. 모든 검사 결과는
공유 작업공간의 2026-09-11 실행 시점 상태다.

이 E1 결과는 검증 담당자에게 제출하며, 독립 검증 전 실제 데이터셋 전환이나 학습을 시작하지 않는다.
