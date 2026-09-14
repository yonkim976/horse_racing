# E6-B 독립 검증

검증일: 2026-09-13 KST.

**판정: 제출된 개발 비교 수치와 모델 재현성 통과. 중량 묶음의 우월성·운영 승격 근거는 없다. 테스트 import 회귀 1건은 다음 작업에서 수정하며, 이 때문에 실제 모델을 재학습할 필요는 없다.**

## 독립 검증 범위

봉인 H1과 E6-A v2 parquet를 키로 연결하고 각 fold의 날짜 분할 및 encoder를 재구성했다. encoder를 selector fit 행에서 다시 적합해 저장 category map과 대조하고 모든 partition의136/139열 행렬 hash를 확인했다. 연구 evaluator를 호출하지 않고 SciPy logsumexp와 NumPy로 손실·TopK·bootstrap을 계산했다. 실제 tree를 새로 학습하지 않았다.

- 여섯 selector의 **1,147개 iteration**에서 저장 Booster raw-margin hash와 독립 경주 CE를 대조했다. CE 오차1e-12 미만, 최소 CE iteration과 patience80 종료가 일치한다.
- best iteration: F1 106/107, F2 78/88, F3 131/157(기준/추가).
- 여섯 refit의 calibration margin에서 beta 도함수와 brentq로 T를 독립 복원했다. 제출 T와1e-10 이내 일치하며 모두 내부해다.
- calibration 및 evaluation 각각의 저장 raw margin을 재추론과 대조해 최대 오차0. 독립 softmax 확률 계산은1e-12 이내다.
- 여섯 evaluation 모두 키·마번·누락/추가/중복·finite·확률범위·경주합 계약 통과. 전체 평가4218행·407경주다.
- 각 fold와 통합의 지표 및 경주/경주일 bootstrap **8개 CI 전부** 제출값과1e-12 이내로 재현됐다. 통합39개 경주일을 사용한다.
- 원문 미확인17건의 null, 전체 delta null843건이 봉인 입력과 행렬에 유지됐다.
- 실행 코드와 fit ledger는2후보×3fold×selector/refit의12호출과 일치한다. 로그와 코드의 일관성을 확인한 것이며 과거 실행에 대한 외부 계측 증명은 아니다.

## 결과 해석

| 항목 | BASE_136 | 중량3열 추가 | 추가−기준 |
|---|---:|---:|---:|
| 통합 winner-set NLL | 2.068159452524 | 2.063690850489 | -0.004468602035 |
| Top1 적중 경주 | 109 | 108 | -1 |
| Top3 적중 경주 | 234 | 240 | +6 |
| Top5 적중 경주 | 320 | 316 | -4 |

경주 bootstrap95% CI: [-0.021783015490, +0.012345281525]. 경주일 cluster95% CI: [-0.018704231194, +0.010764163204]. 두 구간이0을 포함한다. 이는 동등성이나 무효과의 증명도 아니다.

fold별 NLL delta는 F1 -0.006239, F2 -0.020746, F3 +0.005392다. 최근 fold에서는 방향이 반대이며, 세 fold의 Top3 상승만으로 최종 승격을 결정하지 않는다. F2의 경주일 cluster는7개라 그 fold의 구간만으로 강한 결론을 내리지 않는다. 저장 예측 조건부 CI에는 재학습·가설 선택·fold 설계의 불확실성이 포함되지 않는다.

F3의 동착은2026-02-28 race_id417, 공동우승2두다. 기준의 공동우승 확률은0.038394054234/0.114199752039, 추가는0.029192496440/0.109348298177다. 독립 계산한 winner-set NLL은 각각1.879975748943/1.976590450754이고, soft-label CE는2.714829411037/2.873530334508이다. 두 손실이 올바르게 구분돼 있다. 실제 Top1/3/5 경계에는 확률 동점이 없어서 위 적중 수는 정수다. F2의 일부 하위 확률 동점은 분리 확인했다.

E5-B와 E6-B는 평가 기간과 학습 크기가 달라 절대 NLL을 나란히 놓고 성능 퇴보로 해석할 수 없다. 이번의 유효한 비교는 동일 fold 내 두 후보의 paired 차이다.

## P2: 기본 pytest 실행의 import 회귀

`tests/test_confirmed_starter_e6b.py:22`는 `from scripts import run_confirmed_starter_e6b`를 사용한다. 현재 설치 package는 src/horse_racing이고 pytest 설정에는 프로젝트 루트 pythonpath가 없다.

- 기존 검증 명령 `.venv/bin/pytest -q`: **수집 오류**, `ModuleNotFoundError: No module named 'scripts'`.
- `.venv/bin/python -m pytest -q`: **554 passed, 2 warnings**, 26.86초.

따라서 제출한554통과는 재현되지만 실행 방식에 따른 차이를 숨기면 안 된다. README의 `uv run pytest`와 같은 console 실행도 수용하도록 명시적인 테스트 경로 설정 등 최소 수정으로 해결한다. 봉인 E6-B runner/evaluator/test를 무효화하는 변경과 실제 재학습은 필요 없다. 기존 dirty 설정을 보존하고 프로젝트 테스트 설정의 작은 보완을 우선한다.

관련3파일 Ruff/format은 통과했다. 전체 Ruff 기존21건, format 기존98파일, diff-check 기존 racecourse.py:347 EOF 빈 줄1건이다.66개 출력 파일, frozen before/after 각30개 항목, execution protocol의6개 code hash를 직접 대조해 통과했다. before/after는 같은30경로를 반복 기록한 것이다.

## 다음 연구 방향

중량 묶음은 미승격 연구 후보로 보존하고, 기존136열 절차를 다음 비교의 연구 기준선으로 유지한다. 같은 평가 자료에서 중량 열 조합·seed·temperature를 더 골라 작은 이득을 만드는 작업을 우선하지 않는다.

다음 가설은 **최근 경주들을 평균하기 전에 각 출발의 관측과 시간간격을 보존하면 추가 정보가 있는가**다. 현재 canonical_energy는 최근5회 평균과 제한된 추세, speed_figure는 마지막/평균/최고/추세 요약을 제공한다. 개별 출발의 초반·종반·보정성능·경과일을 최근3회 슬롯으로 제공하는 작은 표형 기준을 먼저 감사한다. 복잡한 신경망을 먼저 도입할 필요는 없다. 이는 설계 근거이며 개선 전망을 실측한 것은 아니다.

E7-A는 테스트 실행 회귀 보완과 이력 feature/시간 계약 감사 및 후속 protocol까지만 수행한다. 실제 모델 학습·성능 비교는 이번 다음 지시 범위에서 제외한다. T-30 실제 가용성, 사후 A 모집단, 기존 snapshot PIT 한계는 유지한다.

검증자는 실제2026-06-01 이후 결과를 읽거나 운영 파일을 변경하지 않았다.

후속 지시: `docs/CONFIRMED_STARTER_E7A_AGENT_PROMPT_2026-09-13.md`.
검증 로그: `data/logs/confirmed_starter_e6b_independent_review_20260913.json`.
