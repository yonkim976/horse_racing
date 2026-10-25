# 검증 기간 상한·F1 공백 진단

작성일: 2026-10-09. 이 작업은 **기존 기간 후향 개발 비교**다. 승인된 56개 one-way 셀에서 저장된 F1 예측만 집계했다. 새 모델 fit·재보정, DB·운영 모델·등록부·중앙 결론 수정, 외부 자료 수집은 없었다.

## 새 라벨 기간 보유 여부와 기간 사용

`jeju/data/jeju_native_core.sqlite3`는 SQLite URI `mode=ro`로 열었고 `PRAGMA query_only=ON` 값 1을 확인했다. 실제 `race_result_rows` 상한은 2026-09-19다. 제주 경주 분석 뷰 `jeju_race_analysis_2026`는 2002-07-06~2026-09-19, 92,513행이다. 이 상한 뒤의 새 경주 결과 라벨은 DB에 없다.

조교 원행은 2026-09-28, 출발심사 원행은 2026-09-30, 홈페이지 출발조교는 2026-09-27까지 이어진다. 이 날짜는 경주 결과 라벨이 아니므로 평가 기간 상한으로 계산하지 않았다. 분석용 조교·심사 뷰는 각 원천별 별도 절단 기준을 쓴다.

제주 자료 계약·등록부·보고서는 2017~2026-09-19를 반복 사용했다. 출판 정책과 최신 연구 종합은 2017년부터 그 상한까지를 대표 기간으로 두고, 연구 등록부 17개 주제 중 여러 항목이 같은 범위를 기재한다. 기준 모델의 2026-01-02~09-12 운영 비교 510경주도 이미 검토됐다. 따라서 현재 보유 구간을 독립 holdout이라고 부르지 않는다. 로컬 기록만으로 다른 세션의 비기록 분석이나 사람이 결과를 본 이력을 전부 증명할 수는 없다.

근거: [제주 지침](../../AGENTS.md), [재시작 계획](../../docs/RESTART_PLAN_20260928.md), [출판 정책](../RESEARCH_PUBLICATION_POLICY.md), [연구 등록부](../conclusions/research_register.json), [연구 종합](../20261008_research_synthesis_v1/README.md), [F1 계약](../20261009_finish_history_ablation_v1/CONTRACT.md).

## 고정 집계와 결과

S1 상태는 원 고정 파일을 그대로 썼다. 비교는 `first_return_91_plus`와 `general`만이며 first-return은 불확정 시행 이력을 censor한 뒤의 기존 `days_since_start ≥ 91` 구간이다. 새 독립 정보나 휴양 원인 효과가 아니다. 기간은 2024–2025와 2026-01-02~09-19 부분연도다. 거리는 정확 거리, 경력은 F1의 기존 `observed_starts` 버킷 0/1–4/5+, 직전 Top3는 top3/not_top3/unknown으로 나눴다. 한 표에서 한 축만 분할했고 교차·임계값 탐색은 하지 않았다.

각 셀은 평균 `y − p_top3`, 경주일 군집 bootstrap 점별 95% 잔차 구간, 저장된 출전행별 Brier 평균, 출전·경주·경주일 수를 보고한다. Brier는 출전행 단순 평균이다. 잔차 구간은 2,000회·seed 20261009이며 날짜가 10일 미만이거나 표본이 0인 셀은 NA다. `<100` 출전 또는 `<50` 경주는 `low_support`로 남겼다. 구간은 점별이고 다중비교 보정이나 같은 말 반복 출전의 추가 군집 보정은 없다.

기존 전체 S1 표의 수치는 이번 결과가 재현한다. first-return 잔차는 2024–2025 `+4.10%p`(1,211출전·786경주), 2026 부분연도 `+4.97%p`(519·329)이고, general은 각각 `−0.84%p`(9,674·1,280), `−0.49%p`(3,362·481)다.

경력 분할에서는 1–4회 관측 시작 first-return 잔차가 2024–2025 `+10.94%p` [5.39, 16.31] (272출전·203경주; Brier 0.2205), 2026 `+5.25%p` [−2.37, 12.98] (123·86; 0.2121)였다. 같은 버킷 general은 각각 `+0.44%p` (1,009·518; 0.2121), `+2.89%p` (344·179; 0.2122)다. 5회 이상 버킷 first-return은 `+2.12%p` [−0.48, 4.82]와 `+4.89%p` [0.53, 9.03]였고, general은 `−0.99%p`와 `−0.88%p`였다. 이는 고정 조건 안에서 본 하위군 잔차며 별도 기여 검정이 아니다. first-return과 관측 시작수 0의 교차는 정의상 구조적 0이다. 현재 평가표에는 general의 관측 시작수 0도 없어서 두 기간 모두 지표가 NA다.

직전 출전이 Top3 밖이었던 first-return 잔차는 두 기간에 `+4.00%p` [1.53, 6.65] (1,037·713; Brier 0.1905), `+6.18%p` [2.66, 9.77] (449·297; 0.1934)였다. 반면 직전 Top3였던 first-return은 2024–2025 `+4.39%p` (173출전)에서 구간이 0을 포함하고, 2026은 `−3.84%p` (69출전·low_support)로 구간이 넓었다. 직전 Top3 unknown은 각각 1출전뿐이어서 구간이 NA다. F1 자체가 직전 Top3를 입력하므로 이 분할은 잔여 오차의 기술이지 새 정보 효과가 아니다.

거리별 first-return 방향은 기간·거리에 따라 일정하지 않았다. 예를 들어 2024–2025의 800m는 `+9.84%p` [3.93, 15.79] (184출전), 1000m는 `+5.20%p` [0.66, 9.71] (310출전)였고, 2026의 900m는 `+6.91%p` [0.95, 14.40] (135출전)였다. 나머지 일부 셀은 구간이 0을 포함하거나 소표본이고, 2026 800m·1400m·1610m 등은 날짜가 10일 미만이라 구간을 NA로 보존했다. 셀별 Brier와 지원은 결과 CSV 전체에 있다. 많은 점별 구간을 근거로 조건을 선별하지 않는다.

## 무결성·수정 이력

기존 S1 입력 lock 17/17개와 F1 보충 lock 16/16개 파일의 해시·크기가 계산 전후 모두 일치했다. F1 17,412출전·1,779경주가 고정 코호트와 1:1 연결됐고 라벨·ID가 맞았다. 경주별 F1 Top3 확률 합의 최대 오차는 `2.7×10⁻¹⁵`이다. 거리 셀을 가중 합산한 기존 전체 S1 잔차도 4개 period/group에서 전부 일치했다. 별도 구현을 쓴 B 독립 재집계도 최종 56셀과 coverage 10행을 키·수치 허용오차 1e-12 안에서 전부 맞췄고, 2,000회 날짜 군집 bootstrap, 네 S1 그룹의 분할·축별 분모, 기존 S1 잔차·확률·Brier 제어합, v1 중복 이력을 다시 확인했다. 상세는 [독립 B 재집계 receipt](../20261009_section_ablation_review_v1/independent_b_v2_reaggregation.json)와 [독립 56셀](../20261009_section_ablation_review_v1/independent_b_v2_outputs/independent_b_v2_56_cells.csv), [독립 coverage](../20261009_section_ablation_review_v1/independent_b_v2_outputs/independent_b_v2_coverage.csv)에 있다. reviewer는 원 승인 스냅샷 SHA와 사후 root 승인 current PLAN SHA를 실행 잠금의 서로 다른 필드에 대조해 둘 다 통과시켰다.

root 승인은 2026-10-09 03:48:29 UTC에 기록했고, 승인 후 계획 SHA-256은 `47d37c7eea51fd973439cf3ab2380d54ca8f78265b05dc85f90f91507ae8e943`다. 첫 실행은 결과를 쓰거나 잔차를 집계하기 전에 coverage 전용 S1 라벨(`second_after_return_le90`)의 계획 표기 불일치를 발견해 중단했다. root가 정확 라벨로 수정하도록 승인했고 비교군·셀·지표는 바뀌지 않았다.

초기 생성본은 직전 Top3 unknown 행 4개가 중복되어 60행이었다. 중복 키 검사를 추가해 56개 고유 셀로 고쳤다. 초기 60행 파일은 결정적으로 재구성했고 기존 기록 SHA와 크기 모두 일치함을 확인해 `v1_superseded`로 보존했다. 최종본과 generic 경로는 56행 고유키 `v2`이며, 첫 생성본은 사용하지 않는다.

산출물: [현재 계획·미래 프로토콜](PLAN.md), [원 승인 계획 스냅샷](PLAN_approved_original.md), [승인·계획 잠금](APPROVAL_AND_EXECUTION_LOCK.json), [산출물 매니페스트](ARTIFACT_MANIFEST.json), [입력 잠금·DB 기간 감사](input_lock.json), [실행 코드](diagnose.py), [최종 56셀](F1_gap_residual_by_stratum_v2.csv), [동일 최종본 generic 경로](F1_gap_residual_by_stratum.csv), [S1 분모 coverage](F1_gap_group_coverage.csv), [검증 receipt](verification.json), [중복 오류가 있는 보존본](F1_gap_residual_by_stratum_v1_superseded.csv).

현재 상한 뒤의 새 라벨은 보유하지 않는다. 미래 검증은 승인된 [프로토콜 초안](PLAN.md)만 작성했으며, 새 기간 설정·수집·스케줄 등록은 하지 않았다. root의 사후 문구 보완은 과거 이력 cutoff KST T−2(포함)와 별도의 사전 고정 예측 생성 시각·당시 가용 입력 스냅샷을 구분하며, 이번 진단 셀과 결과 정의를 바꾸지 않는다. 원 승인 계획의 정확한 사전 분석 스냅샷([PLAN_approved_original.md](PLAN_approved_original.md))을 복원해 4,837 bytes와 SHA-256 `47d37c7e…ae8e943`을 assert했다. 사후 프로토콜 문구가 반영된 현재 PLAN은 실행 잠금의 `post_execution_current_plan`에 별도 SHA로 기록했고, root 승인 아래 분석 정의는 불변임을 명시했다.
