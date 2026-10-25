# 독립 재현 검토: 두말 동시 Top3 직접모형

검토 상태: **PASS** (2026-10-11). 이 문서는 `20261011_pair_top3_direct_v1`의 승인된 단회 fit 결과와 보고서에 대한 독립 재현 기록이다. 최종 A 산출물 기준 해시는 A `ARTIFACT_MANIFEST.json` SHA-256 `2050e59e55fea515e1e710efe0e4ac0db2412895ac174f1b7a20d607f6a027b4`, PLAN `7fab8fa552d0572e303e626df153b4a231820544b9394d61f133a0f44c917ee5`, INPUT_CONTRACT `01b811a7a8aaaae43c7bb16fd08e5505ffbd385e285b6aa6cdb471c15da80b6d`다. 기존 `REVIEW_MEMO.md`와 `source_audit.py`는 사전 검토 전용 기록이며, 현재 fit/성과 검토의 근거로는 superseded되었다. 이 README와 `INDEPENDENT_REVIEW_RECEIPT.json`이 현재 검토의 최종 설명과 receipt다.

## 독립 검증 범위

`independent_reproduction.py`는 별도 NumPy/math 구현인 `independent_reference.py`만 불러온다. A의 helper/core/fit/report 코드를 import하지 않았고 optimizer를 다시 호출하지 않았다. root의 fit 승인 receipt가 확인된 뒤에만 frozen input, saved coefficients, predictions와 evaluation labels를 열었다. H1 표준화 통계, 저장 beta로 계산한 race-equal BCE 목적함수·gradient, H2 Platt 목적함수·gradient·projected-gradient KKT를 재계산했다. 이어 모든 evaluation race와 unordered pair를 재구성하고 saved all-pair predictions, selected flags, joint-triple comparator selections, probability diagnostics 및 date-cluster bootstrap을 확인했다.

- 3개 H1 fold와 6개 H2 calibrator를 재현했다. 표준화 평균·scale·support 오차는 0, 목적함수 오차는 최대 `5.56e-17`; H1 gradient infinity norm은 최대 `9.42e-8`, H2 projected-gradient infinity norm은 최대 `1.51e-8`이다.
- 1,779경주의 76,848개 pair rows를 키별 비교했다. 모든 선택 flag와 평가 메타데이터가 일치했고, 저장 확률과 독립 계산값의 최대 절대차는 `1.39e-16` 이하다. 402,808 saved triple rows에서 candidate marginal Top2와 두 maximum-pair comparator도 독립 재구성했다.
- A `REPORT.json`의 hit-rate, paired-date bootstrap, calibration/reliability, threshold 및 sum-to-three 진단 180개 필드를 모두 1e-12 허용오차 내에서 대조했다. 불일치는 없었고 최대 수치 차는 `4.03e-16`이다. 전역 bootstrap schedule은 269개 날짜, 2,000회, seed `20261011`; frozen A schedule의 raw index bytes와 일치한다.

## 결과 해석

주 정책은 경주마다 직접 pair 점수 최대 한 쌍을 고른다. direct pair hit는 **426/1,779 (23.9460%)**였고 raw F1_STYLE6 score Top2와 saved F1_STYLE6 PTop3 Top2는 각각 **429/1,779 (24.1147%)**였다. direct-minus-raw 차이는 **−0.168634 percentage points**, paired date-bootstrap 95% CI는 **[−0.553802, +0.222222] pp**다. 사전 primary gate는 통과하지 않았다. direct는 raw Top2와 31경주에서 선택 쌍이 달랐고, 그중 4회만 이득, 7회 손실, 20회 동률이었다.

사전 지정 비교군도 모두 보고했다: candidate joint marginal Top2 **434/1,779**, candidate maximum joint pair **422/1,779**, matched-baseline maximum joint pair **429/1,779**. 직접모형은 모든 경주에서 총 pair 확률이 3이 되도록 제약된 joint Top3 분포가 아니다. 따라서 calibrated pair 확률합의 3 대비 오차는 별도 진단이다(후보 평균 절대편차 0.0360, 95백분위 0.1235). candidate all-pair Brier/log loss는 `0.062977 / 0.236888`, 선택 pair는 `0.174328 / 0.529294`였다. 이 확률 진단은 pair-hit 개선을 뜻하지 않는다.

## 범위와 재사용 제한

평가는 2024–2026 저장 평가 cohort 1,779경주에 대한 역사적 반복 개발 평가이며 새 미래 holdout이 아니다. 이번 결과만으로 개선 또는 운영 배포를 주장하지 않는다. 이 검토는 새 pair 모형을 다시 학습하지 않았고 운영 예측/DB/등록부/중앙 publication을 변경하지 않았다. 정확한 Top2 공동분포와 조합 완성률은 이번 실험에서 생략했다. 중앙 publication은 별도 최종 승인을 담당하는 주 agent의 관리 대상이다.

재현과 파일 lineage의 machine-readable 세부사항은 `independent_reproduction.json`, `INDEPENDENT_REVIEW_RECEIPT.json`, `ARTIFACT_MANIFEST.json`에서 확인한다. 이전 사전 검토 기록은 보존하되 현재 결과로 오인하지 않도록 manifest에서 superseded로 표시한다.
