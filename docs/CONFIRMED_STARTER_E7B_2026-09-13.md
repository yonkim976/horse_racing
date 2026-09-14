# E7-B 봉인 후향 개발 비교 — 독립 검증 제출

상태: **두 후보·3-fold·12 native LightGBM fit 완료. 운영 승격 없음.** 기존 서울 confirmed-starter H1 A의 136열과 E7-A 독립 검증이 승인한 최근 실제 출발3회×4관측의 12열을 함께 넣은 148열을 비교했다. 비교 대상은 `BASE_136` 대 `SEQUENCE_12_AUDITED` 정확히 둘이다. 기존 136열·라벨·출전집합은 바꾸지 않았고 중량·추가 indicator·새 objective/seed를 사용하지 않았다. 2026-03~05 성능을 새로 평가하지 않았으며 fit·평가의 마지막 날짜는 **2026-02-28**이다. DB/raw 재조회와 2026-06-01 이후 실제 결과 접근은 없었다.

## 결과

주 지표는 calibration T를 적용한 raw margin의 stable log-domain 경주 동등가중 winner-set NLL이다. 차이는 항상 `SEQUENCE_12_AUDITED − BASE_136`이며 손실의 음수만 개선 방향이다. TopK는 확률 동점 기대 포함률이다.

| 평가 | 경주/행 | 후보 | winner-set NLL | soft-label CE | entry binary NLL | Brier | Top1 | Top3 | Top5 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| F1 | 172/1,693 | BASE_136 | 2.151026 | 2.151026 | .314372 | .089474 | .220930 | .534884 | .744186 |
| F1 | 172/1,693 | SEQUENCE_12_AUDITED | 2.148378 | 2.148378 | .313772 | .089207 | .226744 | .529070 | .720930 |
| F2 | 77/834 | BASE_136 | 1.994051 | 1.994051 | .266291 | .074599 | .311688 | .610390 | .779221 |
| F2 | 77/834 | SEQUENCE_12_AUDITED | 2.003717 | 2.003717 | .267657 | .075217 | .298701 | .571429 | .805195 |
| F3 | 158/1,691 | BASE_136 | 2.014066 | 2.019350 | .276872 | .079465 | .297468 | .601266 | .835443 |
| F3 | 158/1,691 | SEQUENCE_12_AUDITED | 2.008262 | 2.014530 | .276276 | .079211 | .278481 | .620253 | .848101 |
| 통합 | 407/4,218 | BASE_136 | 2.068159 | 2.070211 | .289831 | .082521 | .267813 | .574939 | .786241 |
| 통합 | 407/4,218 | SEQUENCE_12_AUDITED | 2.066616 | 2.069049 | .289622 | .082434 | .260442 | .572482 | .786241 |

| 평가 | NLL 차이 | 경주 bootstrap 95% CI | 경주일 cluster 95% CI | Top1/3/5 차이 |
| --- | ---: | --- | --- | --- |
| F1 | -.002648 | [-.022395, .017414] | [-.022827, .015872] | +.005814 / -.005814 / -.023256 |
| F2 | +.009666 | [-.026193, .044064] | [-.012870, .036313] | -.012987 / -.038961 / +.025974 |
| F3 | -.005804 | [-.040447, .027733] | [-.037278, .027063] | -.018987 / +.018987 / +.012658 |
| 통합 | -.001544 | [-.018755, .015348] | [-.017984, .014449] | -.007371 / -.002457 / .000000 |

bootstrap은 fold별·통합 각각 paired race와 경주일 cluster 5,000회·seed20260911로 고정했다. 경주일은 선택된 날짜의 모든 경주를 유지했다. 통합 NLL은407경주의 실제 평균, entry 지표는4,218행 평균이지 fold 평균의 단순 평균이 아니다. 통합 Top1은 기준109경주 대 추가106경주, Top3은234 대233, Top5는320 대320이다. F2의 NLL 방향은 반대이며 F2 cluster는7경주일뿐이다. 모든 95% CI에0이 포함된다. 이는 우월성도 동등성도 확증하지 않는다. F3 공식 공동우승1경주는 winner-set NLL과 soft-label CE를 구분했다.

## 입력·실행 계약과 재현

- H1 dataset SHA256 `9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7`, manifest `f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801`, 기존136열 이름/순서 hash `b7f57b9939aac9b51993e29046d43a10c9f49fdcfac0b821807300459ef2ac48`를 확인했다. E7-A 최종 manifest와 두 parquet·feature code·초안 문서도 지시문 hash와 대조하고 E7-A manifest의 출력·보존 경로를 개별 대조했다.
- H1/새12열의 15,579키가 정확히 일치하고 evidence 46,737슬롯, Float64 및 finite/null 계약을 검사했다. 슬롯1/2/3의 S1F·last200 null은 각각 1,016/1,883/2,706건이며 부경 basis 미확인 536슬롯은 원래 null 그대로다. 새 feature의 metadata는 학습하지 않았다. 전체 H1을 읽은 것은 hash/키 계약 확인이며 모델 입력은 각 fold의 2026-02-28 이전 구간으로 제한했다.
- 각 fold encoder는 selector fit에서만 적합했다. 136열 mapping과 각 partition의 기존 행렬 slice·키·group·label을 양 arm이 공유했다. 136/148 차원, unknown category/수치 null의 기존 NaN 정책을 명세했다. selector tune CE, best iteration refit, 별도 calibration 및 양쪽 준비 후 공통 gate를 거쳤다. objective는 두 arm 모두 동일한 custom weighted Bernoulli BINARY이며 각 경주 0/1 winner indicator 및 float32 `1/field_size` weight를 사용했다.
- 기준 arm의 best iteration **106/78/131**, T와 calibration/evaluation keyed raw margin·확률·평가 지표는 E6-B 각 fold 저장값과 모두 오차 **0**으로 재현됐다. 새 arm의 best iteration은 **123/119/146**이다. 여섯 temperature 모두 승인된 내부해이고, 저장 refit 재로드에서 calibration/evaluation raw margin·확률 최대 오차는 전부0이다.
- 여섯 평가 frame은 누락·추가·중복·마번 불일치·비유한·확률 범위 오류가0이고 coverage100%다. 경주별 확률합 최대 오차는 `4.45e-16` 미만이다. 사용 중인 봉인 상위 경로 **112개**의 전후 SHA256이 같고, 새 출력 **68개**의 manifest hash가 모두 일치한다. 운영 registry는 이 보존 목록에 포함되며 변경하지 않았다.

## 검증·해석 한계

새148열의 열 순서/차원·136열 slice, H1-새 parquet 키 누락과 없는 슬롯의 값 채우기, 후보 이름 바꿔치기, 첫/둘째 arm 준비 실패 시 평가0회, selector 실패 시 fold 비교 중단, 저장 기준 예측 변조 감지, 공식 동착 손실 분리, 성공 fold만의 통합 거부를 실제 함수의 합성 반례로 검사했다. E7-B 관련 **10 test**와 관련 Ruff check/format이 통과했다. 전체 `.venv/bin/pytest -q`와 `.venv/bin/python -m pytest -q`는 각각 **577 passed, 2 warnings**다. 두 warning은 기존 Starlette deprecation과 Polars asof sortedness이다. 전체 `git diff --check`는 본 작업과 무관한 기존 dirty `src/horse_racing/web/racecourse.py:347`의 EOF 빈 줄만 지적한다.

이 비교는 단일 seed와 반복 사용된 407개 개발 경주에 조건부이다. CI는 저장 예측의 표본 변동만 반영하고 재학습·feature 선정·fold 설계 불확실성을 포함하지 않는다. 새 슬롯 정책, 개별 관측 묶음, 기존 열과 거의 중복인 두 입력이 함께 변했다. 차이를 “순서 정보만의 효과”, 개별12열의 기여, 인과효과 또는 독립 미래 우월성으로 주장하지 않는다. 후향 A 집합과 사후 수집 원천의 PIT/T-30 한계도 유지한다. 독립 검증 담당자는 12-fit ledger와 callback 전 iteration, 기준 재현, 여섯 keyed 예측·T·재로드·coverage, F3 동착, fold별·통합 bootstrap을 다시 계산해야 한다. 운영 prediction·베팅·champion 변경은 없다.

## 새 산출물

- 실행 폴더: `data/experiments/confirmed_starter_e7b_20260913/` — 첫 tree 전 `execution_protocol.json`, 입력/encoder/matrix hash, `fit_ledger.json`, 각 fold·arm의 selector/refit Booster·callback 감사·temperature·calibration/evaluation 예측·경주 손실, `baseline_reproduction.json`, fold·통합 비교와 paired loss, `artifact_manifest.json`.
- 코드·테스트: `src/horse_racing/analysis/confirmed_starter_e7b.py`, `scripts/run_confirmed_starter_e7b.py`, `tests/test_confirmed_starter_e7b.py`. 재현 실행 명령은 프로젝트 루트에서 `.venv/bin/python -m scripts.run_confirmed_starter_e7b`이며, 같은 명령을 다시 실행하면 기존 경로를 덮어쓰지 않고 새 attempt를 만든다. 이번 연구 설정을 조정하기 위한 재실행은 허용되지 않는다.
