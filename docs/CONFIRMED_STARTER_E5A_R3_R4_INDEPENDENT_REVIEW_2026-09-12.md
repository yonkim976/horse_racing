# E5-A R3/R4 독립 재검증

검증일: 2026-09-12 KST

**판정: R3/R4 보완 통과. protocol v3에 따른 E5-B 두 후보의 실제 개발 연구 학습을 승인한다.**
이는 연구 실행 승인이다. 예측력 향상, 독립 test 성능 또는 운영 승격의 승인은 아니다.
검증자는 실제 경마 모델을 학습하지 않았으며 합성 재현만 수행했다.

## R3 temperature 검증

beta=1/T에 대한 볼록 CE의 endpoint 부호 규칙을 코드·수식·독립 계산으로 대조했다.
beta 하한의 도함수가 비음수면 T 상한, beta 상한의 도함수가 비양수면 T 하한으로 판정하며,
두 끝의 부호가 엄격히 반대일 때만 root를 구한다. 구조적으로 정확한 상수 score만 flat으로
인정하고, 실제 학습용 fit_temperature는 경계해를 예외로 중단한다.

이전 두 반례, 완전 분리 및 수치 반올림 반례는 모두 경계로 판정됐다.
독립적으로 해를 알고 있는 8개 사례를 추가 생성해 양 경계 안팎과 내부 구간을 검사했다.
8개 모두 기대 상태와 일치했고 내부 beta 오차는 1e-9 미만이었다.
알려진 내부해 beta=log(2), T=1/log(2)도 재현됐다.

무작위 30개 사례의 beta 1차·2차 미분을 독립 CE 및 중앙차분으로 대조했다.
최대 오차는 각각 2.88e-11, 3.08e-11 미만이다.
이 검증은 명세된 합성 수치 범위에 대한 것이며 모든 float64 입력에 대한 형식적 증명은 아니다.

## R4 raw-margin 및 BINARY 가중 미분 검증

BINARY는 weighted Bernoulli custom objective, RACE_SOFTMAX는 경주 softmax custom objective를
사용한다. 양 후보의 공통 metric은 raw margin을 직접 받아 CE를 계산하며, probability를 clip한
뒤 margin으로 역산하는 경로는 사용하지 않는다.

독립 무작위 40개 사례에서 BINARY weighted loss의 미분을 중앙차분으로 확인했다.
gradient 최대 오차 7.37e-11 미만, Hessian 최대 오차 4.39e-12 미만이었다.
1/n 가중치가 gradient와 Hessian에 한 번 적용되고, RACE_SOFTMAX는 weight=None 정책을
사용함을 실제 합성 callback으로 확인했다. RACE의 Hessian 대각/floor 근사는 그대로 명시돼 있다.

제출 합성 실행 스크립트를 별도 임시 폴더에서 재실행했다.

- callback_evidence.json, temperature_evidence.json, synthetic_bundle.json 전체 재현 일치.
- BINARY 13 iteration, RACE_SOFTMAX 16 iteration의 raw hash와 독립 CE 비교 재현.
- best iteration은 각각 10, 13. 두 selector 모두 단일 custom metric만 사용.
- 실제 정책의 BINARY weight=1/n, RACE weight=None 및 초기 margin 0 확인.
- 공개 init_score probe의 [40,41] CE=1.3132616875182228,
  [−40,−41] CE=0.31326168751822286이 실제 callback까지 보존됨.
- 합성 fit+tune refit, 저장/reload raw margin·확률 최대 오차 0 재현.

합성 probe의 특수 leaf/L2 설정은 init_score 검증용이다. 실제 연구에 그 설정을 옮기지 않는다.

## 보존 및 검사

현재 R3/R4 manifest의 20개 해시 대조와 이전 E5-A manifest의 20개 해시 대조가 모두 통과했다.
두 manifest에 중복 경로가 있으므로 서로 다른 파일 40개라는 의미는 아니다.
이전 E5-A·E4 및 H1/E3 봉인 경로, 현재 운영 registry 보존을 해당 해시 범위에서 확인했다.

- 전체 pytest 직접 재실행: **496 passed, 2 warnings**, 28.01초.
- 관련 세 파일 Ruff check/format 통과.
- 전체 Ruff: 기존 범위 밖 21건. 전체 format: 기존 98개 파일.
- diff-check: 기존 web/racecourse.py:347 EOF 빈 줄 한 건.
- 실제 2026-06-01 이후 결과는 열지 않았고 운영 경로를 수정하지 않았다.

## 실제 연구 승인 조건

승인된 protocol:
`docs/CONFIRMED_STARTER_RACE_OBJECTIVE_PROTOCOL_V3_2026-09-12.md`

SHA256: `d539b7333b7dd2eb0ec8d7589879ca7de2a7e623d654c56f8c9349bd91da6984`

승인된 수학·objective·temperature 구현:
`src/horse_racing/analysis/confirmed_starter_e5_r3r4.py`

SHA256: `55c7dcf686e4bf068b488beb396ffe18fd37a9f179939195494b21f9f35982d0`

실제 H1 A 데이터에서 BINARY/RACE_SOFTMAX 두 절차를 공통 분할·encoder·예산으로 실행한다.
각 절차의 selector 및 최종 refit은 허용되므로 총 2개 후보, 2개 selector와 2개 refit이다.
새 head·feature·seed·calibration 후보를 추가하지 않는다.

temperature 경계해나 callback/coverage 계약 실패는 protocol에 따라 중단하고 원인을 제출한다.
경계를 넓히거나 T=1로 바꾸어 실행을 강제로 성공시키지 않는다.
validation은 이미 반복 사용된 개발 평가다. 수치가 좋아도 실제 미래 성능이나 운영 승격을 확정하지 않는다.

실행 지시서: `docs/CONFIRMED_STARTER_E5B_AGENT_PROMPT_2026-09-12.md`.
기계 판독 검증: `data/logs/confirmed_starter_e5a_r3_r4_independent_review_20260912.json`.
