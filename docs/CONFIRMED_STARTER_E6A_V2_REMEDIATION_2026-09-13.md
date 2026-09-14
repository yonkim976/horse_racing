# Confirmed-starter E6-A v2 독립 검증 보완 제출

작성일: 2026-09-13 KST. 판정: **R1~R4 구현·후향 감사 완료, E6-B 학습 보류**.
기존 E6-A attempt4 및 H1/E3/E4/E5/registry 파일은 수정하지 않았다. 실제 tree 학습,
성능 평가, 운영 연결은 0회다.

## R1. 서울 target과 전 경마장 과거 출발 분리

target은 서울 H1 A 15,579행·1,488경주, 2026-05-31 상한 그대로다. 과거 조회는
읽기 전용 SQLite에서 서울·부경·제주 전체 281,055행, 2015-01-02~2026-05-31로
한정하고, 각 target에는 경주일이 엄격히 이른 기록만 허용했다. 기존 서울 전용
직전 출발 키 오류 **167행**을 재현했다. DB 중량을 가정한 비교상 delta 변경은
**119행(유한→유한 78, null→값 41)**이다. entry 18703은 서울 entry 151579
53.5kg에서 부경 entry 303213, 2024-11-24, 55kg로 바뀌며 DB 기준 +3→+1.5kg이다.
entry 23224는 부경 entry 19712, 2025-02-07, 52kg가 직전 출발로 확인되어
DB 기준 null→+4kg이다. 두 사례 모두 같은 horse_id·엄격한 이전 날짜·정상완주
상태를 keyed evidence에 남겼다.

새로 선택된 부경 이전 출발 167개 중 150개는 출전표 wgBudam, AI 결과 burdWgt,
상세 결과 pthrBurdWgt의 raw→기존 parser→DB 중량이 같은 말 고유번호·경주·
마번에서 모두 일치했다. 단위는 kg이며 원문 파일 SHA-256도 확인했다. 그러나
원천 수집은 모두 경주 후인 2026-08-21이므로 historical T-30 가용성을 증명하지 않는다.
2024-06-30~12-27의 **17개** 이전 출발은 이 저장소에 해당 원문이 없어 출발의
DB상 존재와 중량의 원천 검증 가능성을 구분했다. 해당 선택 출발 키·날짜는 유지하되
중량·delta는 null, 상태는 previous_actual_start_weight_unverified다. 이전 서울
출발로 fallback하지 않는다. 따라서 최종 feature의 old 대비 delta 변경은 **126행**
(null→값 40, 값→null 16, 유한→유한 70)이며 DB-reference 119와 의도적으로 다르다.

최종 feature의 현재 중량·A 상대중량은 전수 기존 값과 일치하고, H1 키·원본
136 predictor·label은 불변이다. 직전 출발 키와 날짜는 167행, 중량·delta는
각 126행 바뀌었다. 나머지 15,412행의 delta 변경은 0이다. 상태 metadata는
883행 변경됐는데, 그중 826행은 과거 서울-only의 단정적인 첫 출발/left-truncation
표현을 전 DB 관측 범위 기준으로 재분류했기 때문이다.

전 DB에서 이전 실제 출발 없는 target은 826행이다. 815행은 관측 범위 내 이전
DB 출전행 자체가 없고, 11행은 과거 DB 출전행은 있으나 확정 실제 출발이 없다.
과거 정상완주도 0이다. 이 826행에 is_debut=1이 저장됐더라도 2015-01-02 이전
평생 경력 부재까지 입증하지 않는다. 이전에 left-truncation/unobserved로 표시된
41행은 모두 실제 부경 과거 출발이 확인되어 더 이상 무이력으로 표시하지 않는다.

## R2. 미확정·상충 상태

새 source-to-state adapter는 E1의 classify_outcome을 사용해 숫자 순위, rank_remark,
scratched, disqualified, race status/무효를 함께 검사한다. 서울 126,191행은 기존
독립 검증 E1 상태와 차이 0이다. 부경 89,822행 중 미확정·상충 12행, 제주
65,042행 중 미확정·상충/무효 739행을 별도 보고한다. adapter는 E1 함수를 직접
호출하므로 별도 알고리즘 간 불일치 0이라는 독립 주장은 하지 않는다.

가장 최근 확정 출발 뒤의 미확정 행은 delta를 null로 차단한다. 그보다 오래된
미확정 행과 확정 미출주는 최신 확정 출발을 바꾸지 않는다. 직전 확정 출발의
중량 null은 과거 비결측값으로 건너뛰지 않는다. 같은 날짜의 복수 가능 출발은
entry_id 정렬 대신 모호성 상태와 null delta를 낸다. 실제 전수 target에서
newer unresolved와 same-day ambiguity는 0이지만 합성 반례로 검증했다.

## R3. temperature gate

새 준비 경로는 기존 diagnose_temperature 결과 객체를 변조 없이 PreparedArm에
전달한다. 공통 gate는 두 후보 준비 완료 후 endpoint/solution의 유한값,
β·T·log(T) 일치 및 봉인 범위를 검사한다. structural-flat은 실제 진단의
flat_use_T1, T=1, β=1에서만 통과한다. interior는 log(T)∈(-4,4)여야 한다.
flat T=1.1, interior T=1e10, boundary, 비유한·비양수의 validation 호출은 0이다.
새 온도 최적화 수학이나 탐색은 도입하지 않았다.

## R4. 두 후보·12 fit

E6-B v2 초안 후보는 정확히 BASE_136과 CURRENT_WEIGHT_A_PREV이다. 후자는 세 중량
feature를 묶어 추가한다. 기존 독립 검증 통과 3-fold 날짜·각 partition 분모 및
평가 4,218행·407경주를 유지한다. 3 fold × 2 arm × selector/refit = **12 fit
예정**, 현재 실제 fit 0이다. hash-verified protocol JSON에서 후보명을 읽는
run_e6b_fold 공통 gate를 만들었고, 누락·중복·추가 요청은 prepare도 0회,
반환 후보명 바꿔치기와 첫/둘째 준비 실패는 evaluation 0회다. 순서 역전 및
정상 통과에서는 양 후보를 준비한 다음 각 1회 평가하는 spy 반례가 통과했다.
개별 세 feature의 독립 기여·인과효과를 주장하지 않는다.

## 검증·보존·남은 한계

관련 Ruff/format은 통과하고 v2 테스트 25개가 통과했다. 전체 pytest는
**545 passed, 기존 warning 2건**이다. 저장소 전역 Ruff는 기존 E6-A v2 밖
21건, format은 기존 98파일, git diff-check는 기존 racecourse.py EOF 빈 줄
1건으로 실패한다. v2 신규 파일에는 해당 정적 검사 지적이 없다.

사용된 raw 원천의 공개·effective·revision 시각은 없으며 17개 과거 중량은 원문
부재로 격리했다. 역사적 A 모집단과 기존 H1 136개에도 별도 PIT/source 한계가
있다. E6-B v2는 독립 재검증 및 별도 실행 승인 전 **학습 금지**다. 2026년
3~5월 새 성능이나 6월 이후 실제 결과는 열지 않았고 운영 registry를 수정하지 않았다.

최종 keyed feature/evidence, 전수 cell-change, 상태 감사, 합성 반례, protocol JSON,
보존·검증·hash manifest는
data/experiments/confirmed_starter_e6a_v2_20260913_attempt4/에 있다.
이전 실패 및 superseded 시도 폴더는 삭제하거나 덮어쓰지 않았다.
