# E2-H1 한정 보완 지시서

작업 경로는 /Users/kimyongjin/Desktop/horse_racing이다. CONFIRMED_STARTER_E2_V2_INDEPENDENT_REVIEW_2026-09-11.md를 먼저 읽는다. v2의 Elo·38개 field 산식·null 비교·calibration 정정은 통과했다. 남은 결함은 말×기수 조합 이력 3개 선택 feature다.

## 실제 결함

DNF/실격 48행 모두 horse_jockey_starts/wins/first가 0/0/1이다. 독립 과거 DB 집계로는 30행에 기존 조합 이력, 11행에 승리 이력이 있다. 잘못된 셀은 총 71개이고 정상완주 15,531행에는 해당 오류가 없다.

원인은 people._add_combo_features가 정상완주 past_results에서 만든 값을 target race_entry_id로 join하기 때문이다. 실제 DNF target는 그 history에 없어 fill_null(0)이 된다. E2의 _HISTORY_MODULES anchor 보완은 people에 적용되지 않았다.

## 수정 범위

1. E2 연구 경로에서 모든 A 행의 말×기수 이력을 같은 사전 질의로 계산한다. horse_id+jockey_id와 target date를 기준으로 target 날짜보다 엄격히 이전인 정상완주 history의 출주수·승수를 구하고 first를 파생한다. target 결과행 존재 여부에 의존하지 않는다.
2. 원래 people 모듈의 운영 기본 동작과 기존 dataset·model은 변경하지 않는다. 필요하면 E2 전용 함수/adapter로 세 값을 교체한다. null jockey는 null, 알려진 기수와 실제 과거 조합 0회는 first=1로 구분한다.
3. 과거 DNF를 새로 정상완주 history에 넣지 않는다. 정상완주 조건부 과거 이력 정책·Elo·field 산식·calibration 명세를 이번에 확장하지 않는다.

## 필수 검증

- 독립 A 15,579행 모두에 대해 SQL 또는 독립 이력 집계로 세 값을 대조한다. expected를 저장된 세 값이나 같은 수정 함수에서 만들지 않는다.
- 사례 19361은 1/0/0, 19785는 3/0/0, 20871은 1/1/0이다. 실제 근거로 재계산하고 하드코딩하지 않는다.
- build_predictors의 실제 feature 모듈을 사용하는 작은 fixture를 만든다. _apply_modules 전체를 fake로 바꾸지 않는다. 데이터 source는 합성 또는 상한 내 실제 축소 fixture여도 된다.
- 같은 A·같은 과거 이력에서 target 정상 결과행 추가/삭제, DNF/실격 상태 교환, target 결과/구간 값 변경, 합성 미래 결과 추가/변경이 target의 선택 predictor에 영향을 주지 않도록 검증한다. 특히 join 실패를 0 이력으로 바꾸는 경로를 검출한다.
- 선택 feature 136개·키·라벨·mask·train 12,528/validation 3,051·38개 field 산식을 다시 검사한다. 숫자는 유한값 1e-10, null 상태는 정확히 비교한다.
- 수정 전 v2 대비 변경 셀을 기록한다. 이번 직접 결함은 30행·71셀이다. 다른 선택 열/행의 변화는 누락하지 말고 근거를 설명한다. N 공통행 변화, 비선택 열 변화, 미세한 수치 차이를 구분한다.

## 보존과 제출

- production DB, 기존 v2 및 이전 E2/E1/canonical dataset·manifest·report·log·run을 덮어쓰지 않는다. dirty/동시 작업을 보존한다.
- 실제 결과는 2026-05-31 이하로 제한하고, 그 이후 반례는 합성 자료만 사용한다.
- 학습·성능 비교·운영 연결·배팅·실제 수집 실행은 하지 않는다.
- 새 dataset/manifest/log와 docs/CONFIRMED_STARTER_E2_H1_REMEDIATION_2026-09-11.md를 제출한다. 로그는 data/logs/confirmed_starter_e2_h1_remediation_20260911.json 등 새 경로를 사용한다.
- 관련 검사와 전체 pytest/Ruff/diff-check를 실행하고 기존 UI EOF 오류 등은 별도로 보고한다. 실제 모듈 검증과 mocked unit test의 범위를 구분해 적는다.

이 결함을 보완해 독립 재검증에 제출한 뒤 멈춘다. 앞서 통과한 보완을 다시 연구하거나 추가 모델 탐색을 하지 않는다.
