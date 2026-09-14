# E6-A R1~R4 보완 지시

작업 경로: `/Users/kimyongjin/Desktop/horse_racing`.

먼저 `docs/CONFIRMED_STARTER_E6A_INDEPENDENT_REVIEW_2026-09-12.md`와 그 검증 JSON을 읽어라. 아래 네 보완과 독립 재검증용 산출물 제출까지 완료하라. 실제 tree 학습·성능 평가·운영 연결은 하지 않는다. E6-A attempt4와 기존 문서·code hash 계약은 보존하고 새 v2 구현/보고서/산출물 경로를 사용한다. 기존 코드를 고쳐 봉인 manifest를 무효화하지 않는다.

## R1. 목표 경주와 이전 출발의 경마장 범위 분리

target은 그대로 서울 H1 A 15,579행·1,488경주다. 이전 실제 출발은 동일 horse_id의 이용 가능한 전체 경마장 이력에서 찾는다. 모든 쿼리에 실제 결과 날짜 <=2026-05-31을 적용하고 target별로 event_date < target_date를 지킨다. DB는 read-only다. 과거 경마장 전체 이력의 확인은 이번 지시에 포함되며 서울 외 target 모델이나 이후 실제 결과로 범위를 넓히지 않는다.

검증 로그에 있는 167개 영향 target을 먼저 재현하라. DB 기준 delta 변경 119행(유한값 78, null→값 41), entry 18703 +3→+1.5, entry 23224 null→+4를 재확인하라. 숫자 맞추기가 목적은 아니다. horse_id 동일성·일자·상태·중량 원문까지 증거를 대조하고 다른 결과면 이유를 제출한다.

새로 선택되는 과거 출발 중량의 원문/parser/DB 연결과 단위를 감사하라. 원천 provenance가 부족하면 해당 이전 출발의 존재와 중량 가용성을 구분해 격리한다. 신뢰할 수 없는 최신 중량을 임의로 쓰거나 오래된 서울 출발로 건너뛰지 않는다. cross-track 구간 feature를 만들거나 단위가 다른 성적을 섞는 작업은 필요 없다.

left-truncation/첫 출발/이력 미확정 상태를 전수 재집계한다. `is_debut` 하나만으로 전체 실제 경력의 첫 출발을 입증했다고 표현하지 않는다. 이용 가능한 전체 DB에서 무이력인지, 원천 범위 밖인지, 과거 정상완주 집계가 0인지 구분한다. 과거 실제 출발 존재가 확인된 41행을 계속 무이력으로 표시하지 않는다.

현재 중량·A 상대중량·H1 키·기존 136개 predictor와 label은 보존한다. 변화량 및 metadata의 변경을 셀 단위로 설명하고, 영향 없는 행의 변경 0을 검사한다. null↔값은 변경으로 계산한다.

## R2. 미확정 출발과 상충 상태

최근 확정 실제 출발보다 이후이면서 target보다 이전인 미확정 출발이 있으면 직전 실제 출발을 확정하지 않는다. delta는 null, 상태는 미확정이다. 과거 확정 후보를 참고 metadata로 남겨도 모델 입력으로 fallback하지 않는다. 더 오래된 미확정 행, 확정 미출주, 확정 직전 출발의 null 중량을 각각 구분한다.

숫자 순위뿐 아니라 rank_remark, scratched, disqualified와 경주무효 증거를 E1 호환 방식으로 처리한다. 누락·상충 상태를 출발 또는 미출주로 임의 확정하지 않는다. 기존 서울 자료의 E1 대조 불일치 0을 다시 확인하고, 추가 경마장도 범위와 불일치 수를 별도로 남긴다.

합성 반례에는 정상→미확정→target, 미확정→정상→target, 정상→미출주→target, 직전 null 중량, 상충 special code/remark/flags를 포함한다. 실제 feature helper와 실제 source-to-state adapter에 적용하라. 동일 날짜에 한 말의 복수 실제 출발 후보가 생기면 임의 entry_id 정렬로 결정하지 말고 모호성을 검출한다.

## R3. 공통 gate의 temperature 일관성

`flat_use_T1`은 T=1일 때만 통과한다. structural-flat의 근거는 검증된 temperature 진단 경로에서 전달한다. `interior_optimum`은 protocol의 log(T) 범위 내부이어야 하며, beta/T 등 진단 필드가 있으면 일관성을 검사한다. NaN/Inf/0/음수·boundary·실패 상태는 기존처럼 거부한다.

독립 반례 `flat_use_T1,T=1.1`과 `interior_optimum,T=1e10`에서 validation 호출·산출물 0을 확인하라. 기존 정상 flat 테스트를 T=1로 고친 새 버전 테스트를 작성하고, 실제 준비 함수가 승인된 진단 결과를 변조 없이 gate에 전달하도록 연결한다. 새 수학·온도 탐색법을 개발하지 않는다.

## R4. 두 후보·12 fit으로 후속 명세 정합화

초기 E6-B는 `BASE_136`과 `CURRENT_WEIGHT_A_PREV` 두 후보다. 후자는 감사 통과한 세 중량 feature를 묶어 추가한다. 중간 `CURRENT_WEIGHT_A` arm은 이번 실행 명세에서 제외한다. 기존 3-fold 날짜·분모는 독립 검증을 통과했으므로 유지하고 실제 fit 예산은 총12회로 명시한다. feature를 묶어 추가하는 실험이므로 개별 세 feature의 인과효과나 독립 기여를 분해했다고 주장하지 않는다.

gate는 고정된 BINARY/RACE_SOFTMAX 이름 대신 봉인 protocol의 기대 후보를 받게 하라. 요청 후보 집합을 prepare 전에 확인해 누락·중복·추가 요청은 실제 prepare 호출도 0으로 종료한다. 반환 PreparedCandidate의 이름이 요청과 일치해야 한다. 모델 objective 이름과 비교 arm 이름을 혼동하지 않는다.

새 gate를 실제 E6-B 준비/평가 orchestration 경계에 사용할 수 있게 만들고 그 함수를 stub/spies로 검사하라. 두 후보 준비 완료 전 evaluation 0, 첫/둘째 후보 실패 시 evaluation 0, 순서 역전과 정상 완료 시 각각1회를 확인한다. 요청/반환 이름 바꿔치기 반례도 검사한다. helper를 우회하는 또 다른 실행 경로를 만들지 않는다.

protocol v2에는 두 후보, fold별 fit-only encoder, 공통 기존136열 mapping, selector/refit/calibration/evaluation 순서, 12 fit, 실패 시 통합 금지, 모든 fold 보고, 고정 metric/bootstrap 및 알려진 후향 데이터 한계를 일치시켜라. 감사한 세 feature 중 정당화되지 않는 feature가 남으면 조용히 후보를 바꾸거나 학습하지 말고 그 상태로 제출한다.

## 제출

새 보완 보고서, keyed feature/evidence, 전수 변경 로그, 원천·상태 분류 감사, 합성 반례 결과, 새 protocol v2, hash manifest를 제출한다. 이전 attempt4의 모든 기재 파일과 H1/E3/E4/E5/registry를 보존해 전후 해시로 확인한다. 기존 실패 이력을 삭제하지 않는다.

관련 Ruff/format, 회귀 테스트, 전체 pytest, diff-check를 실행하고 기존 범위 밖 오류를 구분한다. 3~5월 성능 및 6월 이후 실제 결과를 열지 않는다. 실제 tree 학습·성능 평가·운영 승격 없이 독립 재검증 제출까지 완료하라.
