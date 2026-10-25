# 공동 관계 연구 독립 사후검증

2026-10-10에 root가 고정 학습·평가 산출물과 원천자료를 사용한 독립 재계산을 승인했다. C 검증기는 A의 모듈을 가져오지 않고 locked raw score와 feature에서 다시 계산했다. 모델 계수나 온도는 재학습·재최적화하지 않았다.

## 판정

고정 F1_STYLE6 점수와 같은 1,779경주·17,412출전·269경주일에서, H2 matched baseline의 six hit은 407건, 공동 관계 candidate는 423건이었다. 차이는 +16/1,779경주(+0.899%p)이지만 날짜 단위 paired bootstrap 95% CI는 −0.114~+1.900%p로 0을 포함한다. Exact Top3 집합 NLL의 candidate−baseline 차이는 +0.000635, 95% CI는 −0.004728~+0.006277이다. 사전 gate는 hit 차이 CI 하한 양수와 NLL 차이 CI 상한 0 이하를 모두 요구했으며, **gate는 통과하지 않았다**. 이 결과는 후향 개발 코호트의 연구 신호 판정이며 미래 검증이나 운영 승격 근거가 아니다.

## 독립 검증 범위

- A의 고정 source lock 39개 원천 SHA-256을 fit 전후와 C 계산 전후에 확인했다. 원천은 바뀌지 않았다.
- 2024·2025·2026 fold의 H1/H2 날짜와 T−2 purge·경계, runner scaler 및 pair RMS를 원천에서 다시 만들었다. 저장 scaler와 RMS의 최대 차이는 0이었다.
- 저장 beta를 고정해 H1 objective와 analytic gradient를 다시 계산했다. objective 차이는 0, gradient infinity norm은 fold별 최대 `6.75e-7`, central finite-difference gradient 차이는 최대 `3.43e-9`였다. 저장 온도는 H2 NLL 미분의 KKT 방향과 주변 perturbation을 통과했다. β·τ 후보를 추가로 탐색하지 않았다.
- 1,779개 평가 경주의 전체 무순서 triple 분포를 세 arm(saved original τ 보조 진단, H2 matched baseline, candidate)으로 재산출했다. 각 Q의 경주별 합은 1, 관계 marginal 합은 3이다.
- 사전 canonical six 10,674장 순서와 matched baseline 선택이 정확히 일치했다. A와 C의 두 비교 arm에서 402,808개 triple, 1,779개 race metric, 17,412개 runner marginal 전 행을 키 기준으로 대조했고 수치 차이는 허용오차 안이었다. 날짜 bootstrap과 report metric JSON도 독립 재현됐다.
- 저장 원래 τ arm의 race 진단 1,779건은 frozen `probability_combo_gap_v1`과 일치했다. 임의 행 순열과 label·ID·비예측 metadata 변경 뒤에도 에너지, 분포, 순위, 티켓이 변하지 않았다.

## 대조 자료 및 메모

전체 기계 검증 기록은 [독립 사후검증 receipt](outputs/postfit_independent_validation/independent_postfit_validation.json)에 있다. Receipt SHA-256은 `276e94432acd34205c8005bfee5e0c4516353d6cac43406aa83c17de57f223bc`이고 verifier SHA-256은 `6e5035b70079b4c3d753047c880cca482abe1063c561aeb929a86ddda10c6531`이다. 원천에서 다시 만든 [race metric](outputs/postfit_independent_validation/independent_race_metrics.csv), [runner marginal](outputs/postfit_independent_validation/independent_runner_marginals.csv), [세 arm 전체 triple](outputs/postfit_independent_validation/independent_all_triples.parquet), [saved-τ 기준표 대조](outputs/postfit_independent_validation/saved_original_tau_reference.csv)를 함께 보존한다.

C 대조기를 다듬는 과정에서 pandas dtype만 다른 canonical-six 표를 동일 문자열 dtype으로 맞췄고, A가 CSV에 쓴 순서형 티켓 리스트 표현을 그대로 비교했다. 저장 진단의 `year`·`true_triple_rank` 등은 대조 전에 C 내부에서 공통 열 이름으로 매핑했다. 이 수정은 표 비교 직렬화만 다루며 A fit, 입력, 모델 값, 티켓 순서를 바꾸지 않았다. 재계산 중간 실패 receipt는 만들지 않았고, 최종 PASS receipt만 저장했다.

이 보고서는 중앙 결론 문서·등록부·운영 자료를 변경하지 않는다. 중앙 발행을 검토하기 위한 사전 스냅샷은 별도 폴더에 읽기·복사만으로 준비한다.
