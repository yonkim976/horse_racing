# 두말 동시 Top3 직접모형 사전 독립검토

검토일: 2026-10-11  
범위: 원천·분할·라벨·수치 선택 규칙 및 fit 전 설계 검토. 새 pair 모형을 fit하지 않았고 신규 pair 적중률·확률품질·성과 지표를 계산하지 않았다. DB, 네트워크, 운영 모형·등록부에 접근하지 않았다.

## 검토 대상과 판정

현재 잠금 후보인 `20261011_pair_top3_direct_v1/PLAN.md`(SHA-256 `1188b0458ee70de520a638c31888e391f38b778b76e360bb40397bfce68cfd37`)와 `INPUT_CONTRACT.md`(SHA-256 `6468b16829861b22a6285a8e2ff07fecde926a30a46b280a3c3a3f85178d1f31`)를 검토했다. 목적은 기존 `F1_STYLE6` 말별 평가를 보존하고, 저장한 raw score와 같은 여섯 스타일 입력으로 경주당 단 한 쌍을 직접 고르는 별도 pair-in-Top3 모형을 시험하는 것이다. 제안한 Bernoulli pair 모델은 완성된 Top3 공동분포와 구별되어 있고, pair확률 합이 3이 되지 않을 수 있다는 점을 명시한다. 이 범위에서는 설계가 독립 preflight 후 fit 승인 단계로 넘어갈 수 있다고 판단한다. 이는 fit 승인이 아니다.

중요한 제한은 과거 평가 cohort가 앞선 연구에서 반복 사용된 자료라는 점이다. 2024-01-05~2026-09-19의 1,779경주·269경주일은 독립 미래검증이 아니며 2026년은 부분연도다. 날짜 T−2는 확인했지만 공개 시각과 완전한 당시 모집단은 복원되지 않았다. 따라서 이 분석으로 미래 성능·인과효과·수익성·운영 승격을 주장할 수 없다.

## 독립 원천 감사

재현 스크립트 `source_audit.py`가 hash, source schema와 ID, roster, feature cutoff·결측 규칙, fold별 score provenance, T−2 분할, pair-label 산술, 기존 저장 공동분포의 정규화를 검사했다. 고정 원천과 계산한 세부 수치는 `outputs/prefit_source_audit_v4.json`에 기록되어 있다. 이 receipt의 결과는 `PASS`이며, 감사 당시 계획과 계약 해시를 함께 고정한다.

F1_STYLE6 `features.parquet`는 52,155출전·5,206경주·873일이고, 원천 manifest와 prepared lock의 SHA가 실제 파일 SHA와 일치한다. 모든 경주에 완전한 고유 roster와 정상 완주순위 1..N가 있으며 Top3 라벨은 정확히 세 말이다. 52,155행 모두 history cutoff가 경주일에서 2일 전이고, cutoff 뒤 과거 이력은 0행이다. 세 mean/count 쌍의 NULL·finite 규칙도 모든 행에서 통과했다.

각 평가 fold의 raw score 파일은 정확히 `{api_record_id, score}` 두 열이고, 그 ID 집합은 해당 calendar-year feature roster와 일치한다. 고정된 score·meta·manifest 해시와 meta 내 모델/score artifact SHA, 행 수, evaluation year도 서로 맞는다. STYLE6 생성 코드는 초기 학습·early stopping에 앞선 연도만 쓰고, refit은 calibration/evaluation 연도보다 앞서며 그 같은 저장 모델에서 calibration 및 evaluation raw score를 출력한다. H1에는 저장 full-year tau를 쓰지 않는 계약이 맞다.

T−2 purge 뒤 H1/H2 경주 수는 평가 2024에서 312/336, 2025에서 326/311, 2026에서 329/325다. 저장 F1 refit→H1, H1→H2, H2→평가 첫날의 날짜 간격은 각각 모든 fold에서 2일 이상이다. H1/H2/evaluation의 각 경주에서 모든 `C(N,2)` unordered pair를 열거해 라벨을 다시 만들었고, 매 경주 positive pair가 정확히 3개임을 확인했다. 총 평가 cohort는 17,412출전·1,779경주·269일이다.

같은 6,329개 `api_record_id`가 2024 evaluation과 2025 calibration 양쪽에 있지만 score 값은 다르다(최대 절대차 0.5578666150). 이 파일은 다른 평가 fold의 서로 다른 saved refit에서 나왔으므로 key만으로 합치거나 중복 제거하면 안 된다. fold, source path와 모델 SHA를 붙인 경로별 join이 필요하다.

## 모델과 대조군 설계 검토

고정 입력은 raw score와 여섯 style 열이다. 7개 말별 열의 sum/absolute-difference 항 14개와 세 mean 열의 missingness pair 항 6개를 사용해 20개 대칭 basis를 만든다. 말 ID·경주 ID·마번은 feature에서 제외되고 pair 순서는 대칭이다. H1에서만 runner·pair basis를 표준화하며, race-equal pair BCE와 고정 ridge `lambda=1`을 사용한다. 이는 정해진 pair-label 목표를 직접 학습하면서 경주 크기별 pair-row 수가 목적함수를 지배하는 것을 막는다.

Offset `p0`는 `tau=1` additive exact Top3 score 분포의 pair marginal이다. triple은 숫자 마번 순으로 canonicalize하고 에너지·분모·pair 주변확률을 `math.fsum`으로 합산한다. 독립 재현에서 1,779 평가 경주 모두 `p0` maximum pair와 raw-score Top2가 일치했고, pair-probability sum의 3 대비 최대 절대 오차는 `4.44e-16`이었다. 최초 ordinary-accumulation에서 보였던 세 mismatch는 raw score cutoff ties에서 생긴 부동소수점 누적 artifact였고, canonical `math.fsum` 적용 뒤 남지 않았다. 따라서 현재 고정 tie 규칙에는 불일치가 없다.

H2에서는 candidate와 `p0` baseline 각각에 같은 H2 라벨로 양의 기울기 Platt map을 별도 적합한다. 양의 기울기는 선택 순서를 보존한다. H1/H2 한 번짜리 solver acceptance 조건(success, 유한성, bounds, projected-gradient 기준)을 충족하지 못하면 재시도 없이 중단하는 기준이 문서에 있다. H1, H2는 평가연도 직전 score path에서만 만들며 새 모델은 세 fold 밖의 학습이나 결과 확인 뒤 튜닝을 금지한다.

주 비교는 경주별 한 쌍 선택의 pair-hit 비율 대 raw-score Top2다. 저장 F1_STYLE6 Top3 marginal Top2와 기존 joint marginal Top2, candidate/matched-baseline maximum-joint pair도 함께 보고 gate 대체를 금지한다. 저장된 과거 pair-axis 값은 candidate joint marginal Top2 `434/1,779`, candidate maximum-joint pair `422/1,779`, matched-baseline maximum-joint pair `429/1,779`이다. 기존 `423/1,779`는 정확 Top3 조합 티켓의 적중으로 pair 적중률이 아니다. 이러한 과거 값은 맥락 비교이지 새 모델의 독립 성능 근거가 아니다.

pair marginal 모델은 전체 Top3 joint distribution을 정의하지 않는다. 계획대로 모든 pair 확률 합에서 3을 뺀 편차를 진단으로 남기되 제약으로 강제하지 않는 것이 맞다. exact Top2나 조합 완성률은 이번 잠금 범위 밖이다.

## Fit 전 정지 조건

`outputs/prefit_source_audit_v4.json`은 source 감사만 통과한 기록이며 fit lock이 아니다. 다음 단계에서 구현팀은 같은 source hashes, exact score ID 집합과 schema, H1/H2/evaluation 경계와 T−2 purge, 각 race의 세 positive pair, 20개 basis 지원량, comparator 선택 재현 및 p0/raw-Top2 parity를 outcome metric 없이 preflight해야 한다. 한 조건이라도 실패하면 원천을 대체하거나 경계를 조정하지 말고 멈춘다.

root가 계획·계약을 승인하더라도 fit은 별도의 명시 승인을 받은 뒤에만 가능하다. 그 뒤에도 H1 3회와 H2 Platt 6회만 사전 고정한 대로 한 번씩 실행하고 solver 수용 조건에 실패하면 재시도하지 않는다. 매 fold별 모델·calibrator·feature stat과 입력 hash를 평가 경주를 열기 전에 잠근다. 결과는 새 직접 연구 폴더에만 둔다. 중앙 publication 또는 등록부에는 root의 최종 명시 승인 전에 반영하지 않는다.

## 재현물

- `source_audit.py`: 독립 read-only 원천·분할·label 구조 감사기. A의 helper나 model code를 import하지 않는다.
- `outputs/prefit_source_audit_v4.json`: 현재 계획·계약 해시와 검증 결과를 담은 source receipt. 모델 fit·새 pair 결과 지표는 없다.
- `ARTIFACT_MANIFEST.json`: 이 검토 폴더의 파일 hash와 외부 입력 lineage.
