# 실행 에이전트 지시: E3 N-vs-A 통제 연구

작업 경로: `/Users/kimyongjin/Desktop/horse_racing`

당신은 구현·실험 담당이다. E2-H1 독립 검증은 통과했다. 아래 범위의 통제 학습과 비교를
완료하고 산출물을 제출하라. 결과를 검토하는 독립 검증자가 따로 있다.
기존 dirty work와 dataset·manifest·run·모델을 보존하라.

## 목적과 변경 허용 범위

동일한 A 기반 predictor를 사용하면서 정상완주 학습 대상 N에 DNF를 포함하는 것이
개발 평가에 어떤 변화를 만드는지 확인한다. **신규 연구 bundle 두 개(N, A)**를 생성한다.
각 bundle은 기존 binary LightGBM win/top2/top3 세 head를 유지한다.
새 feature, 알고리즘 교체, seed 탐색, hyperparameter 탐색, ensemble, 운영 연결은 범위 밖이다.

먼저 다음을 읽어라.

- `docs/CONFIRMED_STARTER_E2_H1_INDEPENDENT_REVIEW_2026-09-11.md`
- `docs/CONFIRMED_STARTER_E2_H1_REMEDIATION_2026-09-11.md`
- `docs/CONFIRMED_STARTER_CONDITIONAL_E2_REMEDIATION_2026-09-11.md`
- `src/horse_racing/analysis/lightgbm_model.py`
- `src/horse_racing/analysis/metrics.py`
- `scripts/compare_canonical_section_runs.py` (검증 계약 참고용)

## 입력 봉인

입력 폴더는 `data/datasets/confirmed_starter_e2_h1_remediation_retrospective/start_minus_30m/`이다.

- dataset.parquet SHA256: `9d508bfdea325482461fa5d4e1b9a3ea8543bfe146a9b40b5400f4084064d6a7`
- manifest.json SHA256: `f36cc08930c4010cc3be230575289d06110add010d4c3ad368dbdad5f142d801`
- 선택 136개 feature 이름·순서 hash: `b7f57b9939aac9b51993e29046d43a10c9f49fdcfac0b821807300459ef2ac48`
- 기준 설정 run: `73967a1a-197b-4d81-8149-ee0b008de2a7`
- feature set: `racefit_canonical_history`, profile: `racefit_v5_sand`

학습 전에 해시, 독립 E1 evidence와 A 키 집합, 중복·누락·추가, 라벨 및 auxiliary mask를 검증하라.
H1 입력을 다시 생성하거나 덮어쓰지 마라. A는 retrospective confirmed-starter conditional이다.
폴더의 start_minus_30m은 feature cutoff 표기이며 당시 출전집합 F_t가 증명됐다는 뜻이 아니다.
기존 research manifest가 표준 loader와 호환되지 않으면 최소 연구 adapter를 만들고 원본은 보존하라.
사전 출전집합용 SealedFieldManifest를 A에 허위로 발급하지 마라.

## 두 arm과 분할

두 arm 모두 H1 표에서 시작하고, validation 행은 어떠한 상태 필터도 적용하지 않는다.

| 구간 | 기간 | N 행 | A 행 |
|---|---|---:|---:|
| fit | 2025-01-04~2025-10-26 | 8,701 | 8,719 |
| tune | 2025-11-01~2025-12-27 | 1,992 | 2,001 |
| calibration | 2025-12-28~2026-02-28 | 1,800 | 1,808 |
| train 전체 | ~2026-02-28 | 12,493 | 12,528 |
| 공통 development validation | 2026-03-01~2026-05-31 | 3,051 | 3,051 |

N arm은 train에서만 `outcome_state == normal_finish`를 선택한다.
A arm은 train 전체를 사용한다. 두 arm validation의 `(race_id,race_entry_id)`, 136개 값과 라벨은
완전히 같아야 한다. validation은 288경주, 정상완주 3,038 + DNF 12 + 실격 1이다.
일자 경계와 경주 분할이 동일함을 실제 trainer 진입 직전에 assert하라.

N의 train 행을 고른 뒤 field feature를 N으로 재계산하지 마라. 기존 canonical N 표나
기존 artifact를 N baseline으로 사용하지 마라. 두 모델 모두 동일한 A feature 표에서 새로 학습한다.
이 설계는 fit/tune/calibration의 포함 정책 전체를 비교하며, 단순히 최종 tree fit에 35행을
추가하는 실험이 아님을 보고서에 명시하라.

## 동결된 학습 절차

기준 run의 순수 LightGBM 설정을 확인하고 다음으로 고정한다. run metadata의 artifact_path,
model_profile_description, 이전 best_iterations 등을 estimator 인자로 전달하지 마라.

```json
{"objective":"binary","n_estimators":1200,"learning_rate":0.03,"num_leaves":31,"max_depth":-1,"min_child_samples":80,"subsample":0.9,"subsample_freq":1,"colsample_bytree":0.8,"reg_lambda":1.0,"verbosity":-1,"n_jobs":-1,"random_state":42}
```

현행 trainer를 사용한다. encoder는 각 arm의 train 전체에서 적합하고 validation은 적합에 넣지 않는다.
fit으로 학습하고 tune으로 early stopping 80을 적용한 뒤 선택된 iteration으로 fit+tune을 refit한다.
이전 run의 best iteration을 복사하지 않는다. 각 arm의 encoder 및 best iteration 차이는 기록한다.

calibration_requested는 auto다. raw/sigmoid/isotonic 중 보정기는 각 arm의 calibration 구간에서
적합하고, 공통 development validation에 적용·경주 정규화한 binary log loss로 target별 후보를
선택하는 기존 절차를 유지한다. 후보별 지표와 선택 결과를 모두 저장한다.
선택 규칙을 몰래 바꾸거나 결과를 본 뒤 보정 방식을 재선택하지 마라.
**development validation은 선택과 보고에 함께 쓰이므로 독립 test가 아니다.**

학습 직전 위 설정·입력 해시·키 해시·분할·지표 정의를 새 E3 protocol JSON에 저장하라.
실패한 시도나 필수 adapter 수정으로 재실행하면 로그를 남기고, 성능을 보고 설정을 고르지 마라.

## 엄격 평가

H1 validation에서 독립적으로 고정한 3,051키를 분모로 예측과 결과를 각각 검증한다.
inner join으로 누락을 숨기거나 DNF/실격을 평가에서 빼지 마라.
각 head의 확률은 유한하며 [0,1]이고, 경주별 합은 기존 계약 min(k, 실제 A 수)인지 확인한다.
확률합 허용오차는 사전 1e-8로 고정한다. 정규화 전 비유한값도 별도 검출해 자동 치환에 숨지 않게 한다.
DNS는 A 밖이며 자동 0 라벨로 추가하지 않는다. head 간 순서 위반은 진단값으로 보고하고
이번 비교에서 새 보정으로 수치 자체를 바꾸지 않는다.

주 지표는 경주 동등 가중 winner NLL이며 delta는 **A−N**으로 정의한다. 음수가 A 개선이다.
동착 승자가 있으면 그 경주의 공식 winner 집합에 부여한 확률을 합한 뒤 -log를 취한다.
로그 보호 epsilon은 1e-15로 고정하고 clipping 발생 수를 공개한다. 이 winner-set 지표와
말별 binary log loss의 정의를 혼동하지 않는다.

보조 지표는 win binary log loss/Brier, prob_win으로 순위를 매긴 Top1/Top3/Top5 winner 포함률,
top2/top3 head의 binary log loss/Brier다. 기존 검증된 확률 동점 기대 포함률 정의를 재사용하되,
입력 순서를 바꾸어도 결과가 같음을 검사하고 공식 동착과 모델 확률 동점을 구분하라.
완전 동점·경계 동점·공식 동착의 손계산 예를 문서화하고 테스트하라.
binary 지표는 말 단위 가중임을 표기한다. unsupported ordered TopK나 joint 확률을 만들지 않는다.

paired 경주 bootstrap 5,000회, seed 20260911, percentile 95% CI를 보고한다.
같은 resample에 N/A를 함께 넣는다. 추가로 경주일 단위 paired cluster bootstrap 5,000회를
같은 고정 seed의 별도 RNG로 수행하라. 경주일을 복원 추출해 그 날의 모든 경주를 묶고,
표본 내 경주 평균 delta를 계산한다. 재학습 없이 저장 예측으로 산출한 조건부 구간임을 명시한다.
CI가 0을 포함하면 우월성 근거 부족으로 판정하며, 제외하더라도 개발 평가에서의 관측으로 한정한다.
bootstrap에서 음수였던 비율을 'A가 진짜 우월할 확률'이라고 부르지 않는다.

전체 288경주가 주 분석이다. 특수 상태 포함 12경주와 나머지 276경주를 고정 진단으로 함께
보고하되 유리한 부분집합을 최종 결론으로 선택하지 않는다. 단일 seed 연구의 한계도 명시한다.

## 저장·검증·종료

새 E3 디렉터리에 두 bundle, 각 encoder·head·calibrator, validation 예측, protocol,
comparison JSON, 경주별 paired loss parquet, run 보고서를 저장하라.
신규 연구 run ID 두 개를 부여하되 운영 champion/active model 선택을 변경하지 마라.
기존 registry가 운영 선택에 영향을 줄 수 있으면 독립 연구 registry를 사용한다.

각 run에 dataset·manifest·선택 feature·train/valid 키·실행 코드·artifact 해시, git HEAD와 dirty
상태, 라이브러리 버전, 실제 분할 및 상태별 행 수를 남긴다. 보고서는 A 조건부 연구임을 명시한다.
저장 모델을 다시 로드해 공통 validation 3,051행을 재추론하고 저장 예측과 대조하라.
정확 동일 여부와 최대 오차를 기록하고, 허용오차 1e-12를 넘으면 원인을 해결한 뒤 제출한다.
예측 키/분모 위반, 비유한 확률, 동점과 동착, paired bootstrap에 대한 의미 있는 검사를 수행한다.
관련 Ruff/format, 전체 pytest, diff-check를 실행하고 범위 밖 기존 오류는 분리해 보고한다.

실제 2026-06-01 이후 결과를 조회·탐색·평가하지 마라. 모델 성능이나 수익을 보장하지 마라.
DB 수정, 실시간 수집, 배팅, 운영 승격, 추가 연구는 수행하지 않는다.
두 arm의 수치·차이·CI·선택 보정기·best iteration·보존 해시·검사 결과와 산출물 경로를 제출하고 멈춰라.
