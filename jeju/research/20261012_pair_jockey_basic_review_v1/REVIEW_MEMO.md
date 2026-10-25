# Pair 모델 기수 기본정보 후보 독립 검토

## 원천·키 검토

검토는 저장된 파일만 읽었다. `20261009_jockey_effects_v1/input01/starts.csv`는 출전별 `api_record_id`, 말·경주·날짜·공식 `jockey_id`, 결과 payload SHA를 보존한다. 그 연구의 원천 manifest는 `race_result_rows`와 `api_records`를 `api_record_id`로 조인하고 `(api_record_id, horse_id, race_date, race_distance_m, jockey_id)`를 대조해 52,155개 결과 payload hash를 확인했으며, 당시 DB는 읽기 전용으로 열고 전후 SHA가 같았다고 기록한다. 이번 검토는 manifest와 원본 출전 캐시를 읽었고 DB에는 접속하지 않았다.

독립 검산에서 52,155행·5,206경주·2017-01-13~2026-09-19, API record key unique, 기수 ID 결측·0·6자리 형식 오류 0, payload SHA 누락 0, 제외 말 3005648 0, 경주×말 중복 0이었다. 고정 `F1_STYLE6` 점수의 2019–2025 calibration 및 2024–2026 evaluation 각 파일은 해당 target-year 출전 키와 완전히 일치했고, 모든 점수행을 사건 당시 기수 ID에 1:1 연결했다. 매 경주의 roster 수·순위 1..N·Top3 라벨 3개와 T−2 history cutoff도 확인했다. 재현 코드는 [source_coverage.py](source_coverage.py), 결과와 SHA는 [source_coverage.json](source_coverage.json)에 있다.

이 분모는 정상 완주로 선정된 완전 편성 출전이다. 취소·실격·주행중지·비완주·스크래치 등은 원천 분모에 표현되지 않는다. 그러므로 과거 Top3 count/rate나 지원 수는 이 선택 분모 안의 성적·관측수로 설명해야 한다. 이 자료가 비완주 경주에서의 기수 수행이나 안전·사고 대응을 대표하지 않는다.

2019년 H1의 가장 이른 target race는 2019-01-11이다. 이때 cutoff는 2019-01-09, 365일 lookback은 `(2018-01-09, 2019-01-09]`, 날짜만 보면 2018-01-10부터 2019-01-09까지다. 원천은 2017-01-13부터 시작하므로 이 calendar window의 source coverage가 충분하다. 다만 2019–2025 H1 중 일부 출전에서 해당 기수의 이전 365일 *선정 출전*은 관측되지 않는다. source coverage 스크립트에서 `N=0`은 2019: 3, 2020: 12, 2021: 3, 2022: 9, 2023: 1행이었고, 평가 출전은 2024: 0, 2025: 2, 2026: 0행이었다. 이는 기수 ID 누락이 아니며 해당 기간 실제 출전이 없었다는 증명도 아니다. 정의는 target date `t`, cutoff `c=t−2`, `(c−365 days, c]`의 date-only 365일로 표기한다. 현재 기수는 결과 사건에 저장된 실제 기승 ID다. 역사적 출전표의 최초 게시·변경 시각은 복원되지 않았으므로 이를 당일 예측 가능 시점이라고 단정할 수 없다.

## 설계 판정

원천 연결과 고정 점수 파일의 키·편성 커버리지는 **PASS**다. root는 category-ID를 제외하고 최근 365일 이력 하나만 단일 candidate arm으로 진행한다고 freeze했다. 구현 담당자가 제안한 `d=(S−E)/(N+20)`, `E=Σ(3/field_n)`, pair input `d_i+d_j`는 이 범위에 맞는다. 과거 창은 각 출전 T−2 이전의 사건 ID별 자료만 사용하고, `N=0 → d=0`은 중립값이다. `N`은 shrinkage와 source-support 진단에만 쓰고 pair basis의 별도 설명 변수는 아니다. 범주형 H1 효과·이름 입력·rider ID 수치 사용은 명시적으로 제외된다.

365일 결과 집계는 완주 선정 분모를 사용한다. `N=0`은 ID 결측과 구분하고, shrinkage 상수 20은 사전에 고정된 pseudo-start 수로 기록해야 한다. 현 출전 기수 배정과 과거 결과의 공개·변경 시각은 복원되지 않았다.

후보 rolling helper와는 별도 구현(two-pointer window membership, `math.fsum`)으로 42,690개의 2019–2026 target 출전을 비교했다. API key/jockey 연결 누락 0, `N`과 `S` 완전 일치, 최대 `|E|` 차이 `1.96e-11` (허용 `1e-9`), 최대 `|d|` 차이 `4.17e-14` (허용 `1e-11`)였고, 모든 과거자료 날짜가 cutoff 이하였다. `N=0` 중립값도 일치했다. 상세 수치와 세 입력 파일 SHA는 [rolling_feature_independent.json](rolling_feature_independent.json)에 보존했다. 이 검산은 rolling feature만 다루며 pair model fit, 예측, candidate 성과 산출은 하지 않았다.

Root가 고정된 approval SHA 아래 3 H1 + 3 candidate H2 적합과 평가/report를 승인했다. 독립 재구성은 [independent_fit_audit.py](independent_fit_audit.py), 수치 receipt는 [independent_fit_audit.json](independent_fit_audit.json)에 있다. 정확한 old20 moments, 후보 rider moments, H1 objective/gradient, H2 objective/projected gradient가 각각 대조 통과했다.

평가 pair 예측을 별도로 재구성한 [independent_prediction_audit.py](independent_prediction_audit.py)와 [independent_prediction_audit.json](independent_prediction_audit.json)도 PASS다. 76,848개 pair·1,779경주·269경주일 전부에서 score, p0, label, 기존 selector/prediction column이 고정 기준과 일치했다. candidate eta의 최대 차이는 `1.16e-14`, raw/calibrated probability 최대 차이는 `2.56e-15`, rolling rider `d` 최대 차이는 `4.17e-14`였다. 선택 적중 수는 candidate 429, latest pair 427, old direct 426, p0/raw Top2/saved F1 Top2 429, joint marginal 434, joint max-pair 422, matched max-pair 429로 재현됐다. 저장된 2,000×269 bootstrap schedule SHA를 확인해 그대로 사용했다.

사전 지정 primary 차이는 `+0.1124%p`, 95% CI `[-0.3396,+0.5695]%p`이고 raw-429 gate 차이는 `0.0000%p`, CI `[-0.5062,+0.5088]%p`다. 둘 다 하한이 0을 넘지 않아 개선 gate는 통과하지 않았다. candidate/latest all-pair Brier·log loss는 각각 `0.062911/0.236507`, `0.062973/0.236880`; selected-pair Brier·log loss는 `0.175132/0.531468`, `0.174929/0.530939`로 독립 수치와 일치한다. 바뀐 선택은 69경주이며 변경경주에서 10승·8패·51동률이었다. README의 평가 범위와 source/history 공개시각 한계 설명도 결과와 일치한다.

candidate study manifest에 든 16개 local artifact의 SHA/크기는 모두 확인했다. prediction receipt의 중복 key 5개는 같은 값임을 확인했고 root가 이를 제거한 뒤 report·receipt·manifest hash reference를 갱신했다. 최종 receipt·report·report receipt·manifest SHA는 독립 재확인했고 JSON 중복 key가 없으며 fit SHA와 두 prediction parquet SHA가 그대로임을 확인했다. metadata repair receipt는 `jeju/research/20261012_pair_jockey_basic_v1/root_publication/METADATA_REPAIR.json`에 기록돼 있다. 이 memo는 중앙 발행·운영 반영을 승인하지 않는다.
