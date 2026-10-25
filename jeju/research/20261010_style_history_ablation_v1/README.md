# 과거 구간 위치 이력 ablation

이 연구는 저장된 F1 24개 입력의 같은 모집단·분할·확률집합 계산을 유지한 채, 동일거리 최근 실제 출전 5개 슬롯에서 계산한 구간 위치 수준·위치 변화·유효 관측 수 6개를 함께 추가한 `F1_STYLE6` 후보 하나를 비교한다. 결과는 같은 과거 코호트에서 수행하는 후향 개발 비교이며 미래 자료의 독립 검증이 아니다.

## 원천과 계산

입력 원천은 API4 quality-selected S1F·4C·G1F individual-order values다. API303 group은 개별 순위를 제공하지 않으며 status gate와 별도 interval 진단에만 쓴다. Full started roster ID 집합, API4의 전체 `1..N_started` 순열, 허용 status, API303 status gate를 각각 확인한다. 한 point가 유효하려면 API4 전체 순열과 API303 `api_group_unreviewed` 또는 명시 `api_group_unavailable` gate가 모두 통과해야 한다. 슬롯별 `source_snapshot.valid_time=True`도 feature에 기여하기 위한 조건이며, 실패 슬롯을 더 오래된 출전으로 대체하지 않는다.

`r=(quality order−1)/(N_started−1)`이며 0은 그 point의 1위, 1은 해당 point의 `N_started`위다. 입력은 S1F 상대위치 평균과 n, S1F→4C 상대위치 변화 평균과 paired n, 4C→G1F 변화 평균과 paired n이다. 양의 변화는 뒤 point에서 상대 rank 숫자가 개선됐다는 뜻이지 속도·선두 유지·결승 성적이 아니다. 특히 1300m 순서는 사용자 계약인 출발→2C→S1F를 따른다. S1F를 보편적인 200m/210m 지점으로 해석하지 않는다.

이 6개 열은 위치 수준, 변화, 관측 수를 함께 담는 패키지다. 같은 유효 슬롯 집합에서는 S1F 위치 평균에서 두 변화 평균을 빼 G1F 위치 평균을 재구성할 수 있다. 그러므로 후보가 개선되어도 순수 전술 효과나 선행 유지·추입의 독립 효과를 입증하지 않으며, 최근 G1F 위치 수준과 분리된 신호라고 주장할 수 없다.

## 검증과 산출물

`CONTRACT.md`와 `IMPLEMENTATION_PLAN.md`가 cohort·feature·split·metric gate를 잠근다. `prepare.py`는 감사 cache만 읽어 30개 입력을 만들고 lineage와 지원량을 저장한다. `run.py fit`은 별도 root 승인이 승인 파일로 확인될 때만 후보 3개 연도 모델을 fit한다. `report.py report`는 저장된 모델·tau·score만 사용하고 재학습 또는 재보정을 하지 않는다. `verify.py final`은 저장 모델을 재로딩해 입력 점수와 보고서를 다시 계산하며 추가 fit을 하지 않는다.

기준선 F1은 저장된 세 모델의 exact replay이며 24열, 17,412출전, 1,779경주 및 canonical 최대 6 조합을 원 출력과 대조한다. 주 gate는 경주균등 Top3 log loss와 Brier다. paired 차이는 항상 `candidate−F1`이고, 손실 차이가 음수면 후보가 낮다. 두 점추정치가 모두 개선되고 적어도 하나의 날짜 paired 2,000회 bootstrap 95% 상한이 0 미만일 때만 사전 gate를 통과한다. 연도·거리별 경주 paired CI와 경력·각 입력의 유효 n별 출전손실 및 지원량은 보조 설명이다. 공통 467 운영 경주 비교는 HY_R_FORM native PL과 F1 계열의 additive canonical six-set 확률을 서로 다른 확률 의미로 표시한다. `pick_hit`은 가장 높은 점수의 말이 Top3 안에 드는지이며 우승 적중이 아니다.

원천 감사 요약과 입력/코드 SHA는 `outputs/source_audit_reference.json` 및 `outputs/prepared_lock.json`에, 결과표와 paired bootstrap은 `outputs/report/`에 저장한다. 후보가 허가되기 전에는 feature preflight와 F1 replay만 존재하고 후보 성능표는 생성되지 않는다. `ARTIFACT_MANIFEST.json`은 사전 문서·원천·독립검토 및 최종 검증이 끝난 후 생성한다.

## 해석 범위

결과는 사후 정상 완주 전체 코호트의 제한, 공개 시각의 역사적 미확인, 2026년 9월 19일까지의 부분연도, 같은 과거 자료를 이용한 개발이라는 범위에서 해석한다. 본 연구는 인과 효과·독립 미래 성능·운영 승격을 주장하지 않는다.
