# 구현·검증 계획

## 현재 게이트

계약은 6개 입력 정의, 원천 status 정책·SHA, source-cache 스키마, 실제 시작 수 분모·point별 완결성·지원량, fit 예산을 고정한다. 독립 원천 감사 결과는 6,269개 과거 경주·62,248 started row의 전체 roster 일치(경주별 N/ID 불일치 0), point별 API4 순열 및 API303 status 통과 6,243/6,242/6,241경주, 178,459개 실제 슬롯 중 최종 기여 슬롯 177,688 S1F·177,450 S1F→4C pair·177,498 4C→G1F pair다. 이는 해당 history-source cohort의 지원량이다. root의 별도 fit 승인이 있을 때까지 후보 학습을 실행하지 않는다.

## 단계

1. **원천 감사 완료:** API4 `sjS1fOrd`, `sj_4cOrd`, `sjG1fOrd` 선택값·status를 feature-column mapping과 함께 필드별 집계하고 원문 대비 정정·NULL 보류가 fail-closed인지 확인한다. 동일거리 실제 5 슬롯 ID와 official horse ID, distance, T−2 한국 날짜, 대상 말의 `source_snapshot.valid_time=True` 조건을 대조한다. 전체 `source_snapshot` 행을 참조 경주별 full `race_result_rows`와 대조해 기준선과 같은 started 정의의 N·horse ID 집합을 확인한다. 그 집합에 대한 point permutation, pair 동시 가용성, distance별 S1F/4C/G1F 순서를 기록한다. 특히 1300m 출발→2C→S1F 순서를 유지한다. API303 group quality는 모델 입력이 아니며 matching point의 `api_group_unreviewed` 또는 명시 `api_group_unavailable`만 허용한다. group row absent/NULL/unknown, known conflict, missing-review/source-changed는 해당 race-point를 fail closed한다. Group parser/interval 검사는 별도 진단이고 rank로 복원하지 않는다. 괄호 순서를 복원하지 않는다. Full roster/order 지원을 확정할 수 없는 경주는 fit 입력에서 fail closed한다.
2. **입력 작성:** `prepare.py`에서 F1의 정확한 입력 행·순서와 `last5_same_source_ids`를 고정한 뒤, 6열만 과거 원천 ID에 연결한다. SQLite는 `mode=ro`, `PRAGMA query_only=ON`으로 열고 query parameter를 사용한다. source ID 외로 backfill하지 않는다. 슬롯 lineage, point status·제외 사유, 입력 결측 및 거리·연도·history-n 지원을 이 폴더에 저장한다. 기존 24열은 값 동일 검사를 한다.
3. **사전 검증과 F1 replay:** 52,155행·5,206경주, 평가 17,412행·1,779경주·269일을 확인한다. 기존 feature 24개에 후보 6개를 더한 30열 계약과 행 키·순서를 점검한다. 후보 점수는 만들지 않고 저장 F1 2024~2026 세 모형을 reload해 원래 점수·확률·경주/조합 출력을 허용 오차 안에서 독립 재현한다. 코드, 입력, 모델 SHA와 보호 대상 DB·운영등록부·기준선의 현재 전체 SHA를 lock한다. `style_review` 독립 검토 통과 후 결과와 preflight를 root에 알린다.
4. **승인 후 후보 학습:** root fit 승인 뒤 `F1_STYLE6`의 3개 연도 모델만 학습한다. 연도별 초기 fit·refit 합계 6 LightGBM 호출과 calibration 3회로 제한한다. 학습 후 모델을 새 파일에 저장하고 meta에 input names, split, params, seed, iteration, vocabulary, tau, 코드·입력/model SHA를 기록한다. 결과를 본 후 refit이나 새 후보 생성은 하지 않는다.
5. **평가와 잠금:** 기존 canonical Top3 확률을 사용해 전체/연도/거리 결과, 지정 subgroup, date-paired 2,000회 CI, 공통 467운영 경주 보조 비교를 계산한다. 모든 차이는 `candidate−F1`로 통일하고, 손실 차이는 음수가 개선이라고 README에 명시한다. `pick_hit`, native HY PL, F1 additive set probabilities를 구별한다.
6. **검증·보고:** `verify.py`가 모든 lineage, 데이터 누수 방지, 6열 계산·NULL/n 산술, F1 exact replay, 모델 3개·train 6회·calibration 3회, canonical 확률 합과 CI를 독립 재계산한다. 학습 완료 뒤 산출 보고가 실패하면 저장 모델·SHA로 no-fit finalizer만 허용하며 refit/tau 변경은 금지한다. `README.md`, `ARTIFACT_MANIFEST.json`, 독립 verification PASS 이후 이 실험의 날짜별 결과를 동결한다. 중앙 `conclusions/`와 공용 원천·운영 경로는 이 담당 작업에서 수정하지 않는다.

## 산출물

이 폴더 안에만 `CONTRACT.md`, `IMPLEMENTATION_PLAN.md`, `prepare.py`, `run.py`, `report.py`, `verify.py`, `README.md`, `ARTIFACT_MANIFEST.json` 및 새 `outputs/`를 둔다. DB·운영 등록부·기존 모델·기존 F1, 이전 스타일 연구와 중앙 결론 파일을 수정하지 않는다. 기존 F1의 고정 입력·분할·metric harness를 읽기 전용 참조해 불필요한 harness 재작성을 피한다. 모든 직접 입력·실행 코드·저장 기준선 출력 및 지정 보호 범위에 전체 SHA를 기록한다.

독립 source/status/distance audit, C preflight 및 root fit approval이 문서화될 때까지 `prepare` 사전 검증과 F1 exact replay 단계는 이어갈 수 있으나 `F1_STYLE6` fit은 금지한다. 원천 정의·공식 말 ID·시간 cut-off·점별 품질 상태에서 불일치가 나오면 해당 입력을 제외해 즉석에서 결과를 내지 않고 그 구체적 문제를 root에 전달한다.
