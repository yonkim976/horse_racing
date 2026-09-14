# E6-B 봉인 후향 개발 비교 — 독립 검증 제출

상태: **제한된 개발 비교 완료, 운영 승격 없음.** `BASE_136`과 `CURRENT_WEIGHT_A_PREV`를 서울 confirmed-starter H1의 세 시간순 fold에서 사전 고정된 BINARY 설정으로 비교했다. 두 후보×세 fold×selector/refit = 정확히 12 native LightGBM fit을 수행했다. 평가에 사용한 실제 결과는 2026-02-28까지이며 2026-03~05 성능을 새로 계산하지 않았다. H1의 2026-05-31까지 행은 봉인 hash·키·feature 계약 확인에만 읽었다. 2026-06-01 이후 실제 결과는 열지 않았다.

## 결론과 수치

주 지표는 보정 raw margin의 stable log-domain 경주 동등가중 winner-set NLL이다. 차이는 항상 `CURRENT_WEIGHT_A_PREV − BASE_136`이며 손실의 음수만 개선 방향이다. TopK는 동점 기대값 정책이다.

| 평가 | 경주/행 | 후보 | winner-set NLL | soft-label CE | entry binary NLL | Brier | Top1 | Top3 | Top5 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| F1 | 172/1,693 | BASE_136 | 2.151026 | 2.151026 | .314372 | .089474 | .220930 | .534884 | .744186 |
| F1 | 172/1,693 | CURRENT_WEIGHT_A_PREV | 2.144787 | 2.144787 | .313673 | .089394 | .215116 | .540698 | .732558 |
| F2 | 77/834 | BASE_136 | 1.994051 | 1.994051 | .266291 | .074599 | .311688 | .610390 | .779221 |
| F2 | 77/834 | CURRENT_WEIGHT_A_PREV | 1.973305 | 1.973305 | .264036 | .074042 | .337662 | .636364 | .792208 |
| F3 | 158/1,691 | BASE_136 | 2.014066 | 2.019350 | .276872 | .079465 | .297468 | .601266 | .835443 |
| F3 | 158/1,691 | CURRENT_WEIGHT_A_PREV | 2.019458 | 2.025135 | .277529 | .079574 | .284810 | .620253 | .816456 |
| 통합 | 407/4,218 | BASE_136 | 2.068159 | 2.070211 | .289831 | .082521 | .267813 | .574939 | .786241 |
| 통합 | 407/4,218 | CURRENT_WEIGHT_A_PREV | 2.063691 | 2.065895 | .289368 | .082422 | .265356 | .589681 | .776413 |

| 평가 | NLL 차이 | 경주 bootstrap 95% CI | 경주일 cluster 95% CI | Top1/3/5 차이 |
| --- | ---: | --- | --- | --- |
| F1 | -.006239 | [-.029539, .016219] | [-.026070, .012320] | -.005814 / +.005814 / -.011628 |
| F2 | -.020746 | [-.052570, .010568] | [-.042562, .002338] | +.025974 / +.025974 / +.012987 |
| F3 | +.005392 | [-.026852, .038408] | [-.022163, .035340] | -.012658 / +.018987 / -.018987 |
| 통합 | -.004469 | [-.021783, .012345] | [-.018704, .010764] | -.002457 / +.014742 / -.009828 |

두 bootstrap은 각각 5,000회·seed 20260911이며 경주일 재표집은 선택된 날짜의 모든 경주를 유지한다. 통합은 fold 평균의 단순 평균이 아니라 전체 407개 경주 손실 평균 및 4,218개 entry 지표다. 통합에서 NLL은 약 .00447 낮지만 Top1·Top5는 낮다. 모든 95% 구간이 0을 포함하므로 독립 미래 우월성이나 champion을 주장할 수 없다. F3의 공식 동착 1경주는 winner-set NLL과 soft-label CE를 분리해 계산했다.

## 입력·실행 계약

- H1 dataset/manifest SHA256은 각각 `9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7`, `f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801`로 일치했다. 기존 136 feature 이름/순서 hash는 `b7f57b9939aac9b51993e29046d43a10c9f49fdcfac0b821807300459ef2ac48`이다.
- E6-A v2 feature는 H1 전체 15,579키와 정확히 1:1이다. 세 수치열만 136열 뒤에 추가했다. 현재/상대 부담중량 null은 0건, 직전 실제 출발 대비 delta null은 843건이고 원문 미확인 17건의 null을 유지했다. metadata는 학습 열에서 제외했다.
- 각 fold의 encoder는 selector fit에서만 적합했다. 기존 136열의 범주 mapping/변환 행렬을 두 후보가 공유하며, 미지 범주는 NaN이다. fit/tune/calibration/evaluation의 키·group·label·기존 136열 matrix hash를 비교했다.
- 두 후보 모두 custom weighted Bernoulli BINARY, 경주별 0/1 winner indicator와 `1/field_size` 행 weight를 사용했다. selector는 tune CE로 최대 1,200round/patience80 조기 종료했고, best iteration으로 fit+tune 처음부터 refit했다. 각 fold에서 양쪽 temperature 진단 통과 후에만 공통 gate가 평가를 호출했다. best iteration은 F1 기준/추가 106/107, F2 78/88, F3 131/157이었다. 여섯 temperature가 모두 내부 최적점이었다.
- 봉인 E6-A v2 artifact manifest와 개별 파일, 상위 보존 목록의 전후 hash, 운영 registry 전후 hash가 모두 일치했다. 평가 여섯 arm의 coverage는 모두 100%, 누락·추가·중복·비유한값·범위 초과가 0이었다. 경주별 확률합 최대 오차는 `4.45e-16` 미만이다. refit 재로드의 calibration/evaluation raw margin·확률 최대 오차는 전부 0이었다. 66개 출력 파일의 SHA256이 artifact manifest와 일치했다.

## 검증과 경계

E6-B 실제 평가 함수에서 예측 1행 삭제 시 누락 오류, 공통 gate의 첫/둘째 arm 준비 실패 시 평가 0회, 두 arm 준비 후 평가 순서, partition 누락, 기존 136열 matrix 변형, 성공 fold만의 통합 시도, selector fit 실패 후 fold 비교 중단을 합성 반례로 검사했다. E6-B 관련 9 test가 통과했다. 관련 세 Python 파일의 Ruff check/format이 통과했다. 전체 pytest는 **554 passed, 2 warnings**이고 두 warning은 기존 Starlette deprecation 및 Polars asof sortedness 경고다. `git diff --check`는 본 작업과 무관하게 기존 dirty 파일 `src/horse_racing/web/racecourse.py:347`의 EOF 공백을 지적했다. 그 사용자 변경은 수정하지 않았다.

이 결과는 단일 seed와 반복 사용된 개발 데이터에 조건부이다. bootstrap은 저장 예측의 표본 불확실성만 다루며 재학습·후보 선택 불확실성은 포함하지 않는다. 세 feature의 묶음 비교이지 개별 기여나 중량의 인과효과가 아니다. 독립 검증 담당자는 봉인/출력 hash, fit ledger 12회, fold별 키·확률합·재로드 감사, 공통 gate 및 F3 동착 손실, 통합의 경주/entry 가중 집계를 다시 확인해야 한다. 운영 prediction·registry·champion은 변경하지 않았다.

## 새 산출물

- 코드: `src/horse_racing/analysis/confirmed_starter_e6b.py`, `scripts/run_confirmed_starter_e6b.py`, `tests/test_confirmed_starter_e6b.py`.
- 실행: `data/experiments/confirmed_starter_e6b_20260913/`. `execution_protocol.json`은 첫 tree 전에 저장됐고, `fit_ledger.json`, `input_contract.json`, 각 fold/arm의 selector/refit Booster·감사·temperature·keyed 예측·경주 손실·비교, `comparison.json`, `pooled_paired_race_losses.parquet`, `artifact_manifest.json`, `report.md`를 포함한다. 운영 `model_runs.jsonl`에는 추가하지 않았다.
