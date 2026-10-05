# 진료 원문 부상·경주 영향 분류 후보 및 검증 보고서

생성물은 임상 진단, 공식 출전 가능 판정, 검증된 경주 성적 효과 추정치가 아니다. 전체 5,397개 고유 원문을 원문 그대로 보존한 검토 후보 연구 산출물이다.

## 입력과 재현성

- 입력 DB: `data/horse_racing.sqlite3` (SQLite 읽기 전용 연결)
- DB SHA-256: `1fb25999de5928083201015be793157b2ad73bf33c694e9f362768b55b926bcb`
- 원문 term 수: 5,397; horse_medical 원행 수: 697,695; 원문 슬롯 연결 수: 676,047
- term 카탈로그 SHA-256: `393beb9bb3c6734da9c48f65806dac1a69c6bec0cac64e7740805901ad4a7dfc`
- term 연결 SHA-256: `4100955191f76b3540bec62c735e9be28bb73d22b6b0d7be53908116f397cc0c`
- 규칙 버전: `medical-term-candidates-v1.0.0`; 고정 검증 사례: 16개, 결과: passed
- 재생성: `python3 research/medical_injury_race_impact_20260925/build_candidates.py --db data/horse_racing.sqlite3`
- 주요 파일: `candidate_terms.csv` (term별 결과), `rule_validation_cases.csv`, `rule_catalog.json`, `source_and_run_metadata.json`.

## 구분 원칙

- `race_impact_prior`는 원문 문구가 주는 검토 우선 신호다. 임상 중증도, 실제 성적 효과, 공식 출전 자격과 별도다.
- 모든 행에서 `clinical_severity=unknown`. 분류가 `no_injury_signal`이어도 건강함·경주 영향 없음 판정이 아니다.
- 파행은 원인이 확정되지 않은 증상이다. 구조 손상(골절·건·인대 등)은 직접 우려 후보, 외상·눈 질환·통증 등은 상황 의존 후보로 분류하되 원문만으로 현재 상태를 확정하지 않는다.
- 예방접종과 제한된 명시 행정어만 `no_injury_signal`로 표시한다. 처치·검사는 적응증을 역추정하지 않고 영향은 `unknown`으로 둔다.
- 쉼표 포함 원문은 `mixed / unknown` 후보로 그대로 유지한다. 분리·동의어 통합·맞춤법 정규화는 하지 않는다. `동물  ` 접두어도 원문과 term_id를 유지한다.
- `veterinary_review_needed=yes`는 사람 검토를 권하는 신호이며 승인된 진단이 아니다. 공식 출전 가능성은 이 산출물에서 판정하지 않는다.

## 후보 분포

### term_kind

- `administrative`: 4개
- `disease`: 344개
- `injury`: 712개
- `mixed`: 3,731개
- `prevention`: 6개
- `symptom`: 68개
- `treatment_or_test`: 76개
- `unknown`: 456개

### race_impact_prior

요청한 검토 후보와 값의 대응: `direct_concern` = 경주에 직접 영향 우려, `context_dependent` = 상황에 따라 영향, `no_injury_signal` = 부상 신호 아님, `unknown` = 판정 보류. 이는 관찰된 성적 효과의 등급이 아니다.

- `context_dependent`: 871개
- `direct_concern`: 253개
- `no_injury_signal`: 10개
- `unknown`: 4,263개

### review_status

- `rule_candidate`: 4,945개
- `unreviewed`: 452개

규칙 후보는 전수 확정 분류가 아니다. `unknown`은 잘못된 긍정 신호보다 명시적 보류를 택한 값이다.

해석상 보류(`race_impact_prior=unknown`)는 4,263개 term이고, 규칙 매칭 없이 미분류(`review_status=unreviewed`)인 term은 452개다. 쉼표 결합 3,731개도 mixed 표지만 했으며 개별 진단과 위험도는 보류했다.

## 빈도 상위 30개 사례

| term_id | 빈도 | 원문 | 후보 종류 | 계통 | 우려 prior | 상태 |
|---:|---:|---|---|---|---|---|
| 18 | 106,530 | 운동기인성 피로회복 | treatment_or_test | unknown | unknown | rule_candidate |
| 280 | 29,558 | 각막염 | disease | eye | context_dependent | rule_candidate |
| 5 | 22,977 | 운동기인성 피로회복(수액처치) | treatment_or_test | unknown | unknown | rule_candidate |
| 3092 | 21,516 | 동물  운동기인성 피로회복 | treatment_or_test | unknown | unknown | rule_candidate |
| 1579 | 21,431 | 인푸렌자예방접종,선역예방접종 | mixed | mixed | unknown | rule_candidate |
| 1974 | 20,469 | 인푸렌자예방접종,일본뇌염예방접종 | mixed | mixed | unknown | rule_candidate |
| 9 | 17,112 | 양각막염 | disease | eye | context_dependent | rule_candidate |
| 1 | 16,987 | 양후지 근육통 | symptom | musculoskeletal | context_dependent | rule_candidate |
| 30 | 15,836 | 정치 | administrative | unknown | no_injury_signal | rule_candidate |
| 43 | 15,617 | 좌후지교돌상 | injury | musculoskeletal | context_dependent | rule_candidate |
| 4 | 12,091 | 교돌상 | injury | unknown | context_dependent | rule_candidate |
| 25 | 11,809 | 감기 | disease | respiratory | context_dependent | rule_candidate |
| 83 | 10,501 | 좌각막찰과상 | injury | eye | context_dependent | rule_candidate |
| 54 | 10,106 | 좌전지파행 | symptom | musculoskeletal | direct_concern | rule_candidate |
| 95 | 10,072 | 양제3중수골골막염 | injury | musculoskeletal | direct_concern | rule_candidate |
| 17 | 9,313 | 요배통 | symptom | musculoskeletal | context_dependent | rule_candidate |
| 34 | 8,866 | 우전지파행 | symptom | musculoskeletal | direct_concern | rule_candidate |
| 121 | 8,028 | 인푸렌자예방접종 | prevention | unknown | no_injury_signal | rule_candidate |
| 100 | 7,886 | 운동기질환 기타 | disease | unknown | context_dependent | rule_candidate |
| 84 | 7,357 | 우각막찰과상 | injury | eye | context_dependent | rule_candidate |
| 297 | 6,859 | 근육통 | symptom | musculoskeletal | context_dependent | rule_candidate |
| 305 | 6,735 | 일본뇌염예방접종 | prevention | unknown | no_injury_signal | rule_candidate |
| 578 | 6,227 | 찰과상 | injury | skin | context_dependent | rule_candidate |
| 3096 | 6,080 | 동물  근육통 | symptom | musculoskeletal | context_dependent | rule_candidate |
| 82 | 5,710 | 재료판매 | administrative | unknown | no_injury_signal | rule_candidate |
| 41 | 5,461 | 좌전지교돌상 | injury | musculoskeletal | context_dependent | rule_candidate |
| 10 | 5,355 | 식이성 식욕부진 | disease | unknown | context_dependent | rule_candidate |
| 3259 | 5,223 | 동물  좌각막찰과상 | injury | eye | context_dependent | rule_candidate |
| 50 | 4,812 | 우후지교돌상 | injury | musculoskeletal | context_dependent | rule_candidate |
| 42 | 4,794 | 양전지 근육통 | symptom | musculoskeletal | context_dependent | rule_candidate |

상위 사례는 행정·처치·예방접종 결합문과 질환·증상이 섞여 있다. 빈도는 해당 용어가 원문 슬롯에 연결된 횟수이며 독립 사건 수나 말 수가 아니다. 특히 진료 원행에 `동물  ` 접두어가 붙은 별도 term은 접두어가 없는 term과 빈도를 합치지 않았다.

## 규칙 검증과 위험 오분류

`rule_validation_cases.csv`의 16개 고정 사례 검사가 모두 통과했다. 사례에는 파행, 골절, 계인대, 피부·눈 상처, 각막염, 감기, 예방접종, 행정·처치 문구, 폐출혈·비출혈, 쉼표 결합문, 미인식 문구, `동물  ` 접두어 원문이 포함된다. 이 검사는 규칙 동작의 회귀 검사이지 임상 정확도 검증이나 5,397개 수동 판독의 대체가 아니다.

위험한 오분류를 줄이기 위해 `파행`을 확정 질환으로, `비출혈`을 공식 폐출혈로, 처치명을 부상 확정으로 해석하지 않는다. `운동기인성폐출혈`도 단일 원문만으로 공식 사건·횟수·제재를 확정하지 않는다. 넓은 질환 어미 규칙은 후보를 만들 뿐이며 계통 또는 중증도는 임상 검토 대상이다. 규칙에 없는 표현은 unknown으로 남는다.

## 폐출혈 별도 검증안

- 의료 원문 중 `출혈`을 포함하는 고유 term은 11개다. term별 슬롯 연결 빈도는 메타데이터 JSON에 있으며 원문은 보존했다.
- `entry_equipment`에는 499,671개 출전표 행이 있고 `bleeding_count` 비결측 45,402행, `bleeding_date_raw` 비결측 789행이다. 이 수치는 경주 행 수이지 독립 출혈 사건 수가 아니다.
- 저장된 `bleeding_count` 값별 출전표 행 수: 0회 표기 44,613행, 1회 표기 734행, 2회 표기 43행, 3회 표기 9행, 4회 표기 3행.
- 대조 절차: (1) 말 식별자와 원문 진료일/수집시각을 보존하고, (2) 출전표의 `bleeding_date_raw`를 원문 그대로 검토하면서 연속 출전표의 누적 `bleeding_count`를 사건으로 재합산하지 않고, (3) KRA 심판·수의사 공식 처분 및 경주별 문서를 날짜·말·경주로 대조하고, (4) 불일치는 출처별 원문과 불확실성을 그대로 기록한다. `비출혈`은 자동으로 운동기인성 폐출혈 사건이 되지 않는다.
- 현재 로컬 스키마에서 확인한 공식 분리 필드는 진료 문구, 출전표 정보, 출전 취소 사유(`race_scratches.reason`)다. 수의사·심판의 공식 폐출혈 제재 레지스트리와 공개 시각은 확인되지 않았으므로 별도 원본 확보와 사람 대조가 필요하다.

## 공식 기준 참고

- KRA 질병용어검색은 견·관파행을 병명보다 증상성 표현으로 설명하고 정밀진단으로 원인을 확인해야 한다고 안내한다. 이 원칙을 파행 후보의 `symptom` 분류에 반영했다: [KRA 질병용어검색](https://race.kra.co.kr/raceguide/RaceDiseaseSearchService.do?pageIndex=2).
- 2026 제주 시행계획은 경주 중 폐출혈의 통산 발생 횟수와 최근 2년 발생 기준에 따른 출전정지·주행심사, 마체이상 시 수의사 진단 및 심판위원 판단, 마체검사 불합격/미검사 조치를 별도 규정한다. 이는 진료 원문 분류와 출전 자격이 다른 자료·판정이라는 점을 뒷받침한다: [KRA 2026 제주 경마시행계획, 25–26쪽](https://race.kra.co.kr/down/raceplan2026_jeju.pdf). 지역과 연도별 규정 적용은 다시 확인해야 한다.
- KRA 출전마처분제도는 질병·사고에 따른 출전취소, 경주제외, 출발제외, 주행중지 절차를 별도 설명한다: [KRA 출전마처분제도](https://race.kra.co.kr/raceguide/RaceTakePartHorseCancleService.do?Act=06&Sub=3&meet=2).

## 성적 분석 및 시점 누수 방지

향후 연관성을 보더라도 진료일(`clinic_date_local`), 최초 공개 가능 시각(현재 미확인), 우리 수집시각(`observed_at_ms`), 경주일(`race_date_local`)을 별도 필드로 다뤄야 한다. 수집시각은 최초 공개 증거가 아니다. 공개 가능 시각을 확인할 수 없는 과거 진료를 라이브 예측 백테스트의 입력으로 쓰면 안 된다. 성능 차이는 교란과 선택 편향을 고려한 연관성으로 표현하고 인과효과로 부르지 않는다. 임상 중증도·공식 출전자격·실제 성적 효과를 하나의 등급이나 점수로 합치지 않는다.

## 다음 단계 결정

### 자동 분류 가능

- 후보 생성 및 재현 가능한 문구별 빈도 집계.
- 예방접종, 일부 명시 행정어, 파행, 명시 구조손상 및 명확한 쉼표 결합 여부를 검토 큐로 보내는 제한적 규칙 적용.
- 모든 원문 보존, 분류 근거·규칙 버전·입력 해시 기록.

### 사람 검토 필요

- `direct_concern` 및 `context_dependent` 후보 전부의 수의학적 확인, 특히 구조 손상·반복 증상·눈/피부 외상.
- mixed/복합문·낯선 용어·일반 질환 어미 후보의 원문별 판독과 해부학 계통 확인.
- 폐출혈 term, 출전표 누적 횟수/날짜, 공식 처분 근거의 말·날짜별 대조.

### 현 자료로 판정 불가

- 원문만으로 임상 중증도, 회복 여부, 실제 성적 영향 및 공식 출전 가능 여부.
- 과거 기록의 KRA 최초 공개 시각과 라이브 시점 사용 가능성.
- 이 보고서의 규칙 후보가 실제 경주성과를 예측하는지 또는 인과적으로 영향을 주는지.

운영 적용 전에 승인된 분류 용어집과 수의사 판독자, `veterinary_reviewed` 상태의 근거·감사 절차, 공식 출전 제한 원천 및 공개시각 데이터, 모델 연결·롤백 기준을 정해야 한다. 이번 산출물은 신규 연구 폴더에만 생성했으며 운영 DB·Supabase·프론트엔드에는 쓰지 않았다.
