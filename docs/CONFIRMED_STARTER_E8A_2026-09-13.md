# E8-A 실제 시점 증거·shadow 원장 최소 구현 — 독립 검증 제출

상태: **offline 합성 경로만 구현; 실제 수집·tree fit·확률 발행·성능 계산 각 0회. `not_activated`.** E7-B 독립 검증의 후향 비교는 재현됐지만 미래 우월성은 미확인이고 역사적 T−30 출전집합도 입증되지 않았다는 판단을 출발점으로 삼았다. H1/E3–E7 연구 산출물과 운영 DB·schema·발행 서비스·UI·scheduler·registry는 변경하지 않았다. 2026-06-01 이후 실제 결과와 미사용 holdout을 조회하지 않았다.

## 기존 경로와 차이

| 근거 파일·함수 | 재사용할 계약 | E8-A에 새로 필요한 것 / 이번에 연결하지 않은 것 |
| --- | --- | --- |
| `analysis/pre_race_field_contract.py`의 `SealedFieldManifest`, `validate_sealed_field`, `validate_exact_keyset`, `OutcomeState` | 독립 F_t 키·cutoff·공식 상태 분리. 새 저장기에서 field 검증·키 전체 대조를 직접 호출한다. | 당시 실제로 수신·파싱·보존한 원문 이벤트는 기존 E1 계약이 생성하지 않는다. 합성 원문에서 생성하되 실제 결과 조인·평가는 연결하지 않는다. |
| `collectors/kra_api.py`의 `KraApiClient.iter_entry_sheet_pages`/`iter_pages`, `FetchedPage`; `parsers/entry_sheet.py`의 `parse_entry_sheet_page`; `services/entry_sheet.py`의 `ingest_entry_sheet` | 원문 바이트, 요청/수신 시각, API26_2 출전표 및 `totalCount`/pagination 정보를 향후 adapter가 받을 수 있다. | 현재 `ingest_entry_sheet`는 `RaceEntry`를 upsert하고 `scratched=False`로 갱신한다. 과거 버전의 완전한 F_t를 보장하지 않으므로 이번엔 호출하지 않는다. 실제 parser adapter·전체 페이지 완전성은 활성화 전 검증 과제다. |
| `services/raw_store.py`의 `store_entry_sheet_page`/`store_kra_page`, `db/models.py`의 `SourceDocument`/`IngestionRun` | 기존 원문 SHA256과 `requested_at_ms`/`retrieved_at_ms` 개념을 확인했다. | 기존 경로는 실행별 파일과 가변 운영 DB 원장이며 parse 완료·영속화·field·feature·prediction의 불변 해시 연결이 없다. 별도 content-addressed raw 및 append journal을 구현했다. 기존 테이블은 변경하지 않았다. |
| `db/models.py`의 `Race.scheduled_at_ms`, `RaceEntry.scratched`, `ModelPrediction`/`PredictionRun`; `services/prediction_ledger.py`의 `_validate_probability_frame`, `publish_predictions`/settlement | 확률의 finite·범위·경주합, 공개 경주 중복 방지·정산 분리의 의미를 참고했다. | 현 DB의 일정·취소는 현재 상태이며 `publish_predictions`는 그 현재값을 조회해 live 발행한다. 과거 T−30 증거로 재해석하지 않고 공개 원장을 호출/변경하지 않는다. 별도 `shadow/` SQLite에서 합성 `prob_win`만 승인한다. |

## 격리 구현과 합성 replay

`src/horse_racing/analysis/confirmed_starter_e8a.py`는 외부 DB·network import/호출 없이 SQLite `BEGIN IMMEDIATE` append journal과 SHA256 raw CAS를 사용한다. `ShadowEvidenceStore`의 일반 생성자는 시스템 시계를 사용하며, 합성 fixture만 `for_testing`으로 시계를 주입한다. 원문은 source ID, 요청/수신/파싱/영속화, parser version/status, 원문에서 실제 제공된 공개·적용 시각을 분리한다. observation transaction commit 뒤 별도 `observation_ready` 이벤트를 commit하고 그 완료 이벤트의 보수적 `available_at_ms`만 field·feature 적격에 사용한다. 옛 파일을 지금 읽으면 요청시각을 과거로 줄 수 있어도 이용 가능 시각은 현재 저장기의 시각이다. 동일 바이트 재관측은 새 observation/ready 이벤트, raw blob은 한 개다. 정정은 새 원문/event다.

합성 parser는 `declared_count`, `status=complete`, 말번호·entry ID·horse ID의 일대일성을 검사한다. `declared_count`는 원문에 별도로 선언된 completeness key로서 합성 부분 응답·중복을 차단하지만, 실제 KRA pagination 전체 수집을 증명하지는 않는다. 일정 버전과 T−30 cutoff를 field event에 함께 저장하고 동일 경주가 한번 봉인되면 다른 cutoff로 재봉인하지 않는다. cutoff 후 들어온 과거 effective 정정도 이전 field를 수정하지 않는다. 봉인은 합성 시계가 cutoff와 정확히 일치할 때만 허용한다. 이 엄격한 offline 경계는 실제 scheduler 오차를 해결한 것이 아니므로 그대로 실시간 활성화할 수 없다.

field→snapshot은 E1의 정확한 키 집합과 말번호·말 ID를 다시 확인하고 feature마다 source observation hash, 계산 버전, 이용 가능 시각을 요구한다. `population=A`, 누락/추가/중복 키, cutoff 뒤 source/feature는 거부한다. 현재 A 연구 모델은 `F_t` 모델로 승격하지 않는다. shadow prediction은 `F_t_synthetic`과 합성 `prob_win`만 허용하며 `(experiment_version, model_version, race_key, cutoff_policy, sealed_field_hash)`로 식별한다. snapshot/model hash도 결합한다. 동일 payload 재시도는 같은 event hash, 충돌 payload는 거부한다. SQLite commit 전 실패는 승인 event 0건이며 raw orphan은 재사용 가능하다. 동시 동일 요청은 직렬화되어 prediction 1건만 남는다. 사후 DNS/결과/정정은 `outcome` append event로만 남고 원 입력·확률을 바꾸지 않는다. DNS 정의 미확정이므로 평가 상태는 `held_dns_policy_unconfirmed`다. A로 자동 축소/재정규화하지 않는다.

`scripts/run_confirmed_starter_e8a.py`를 `python -m scripts.run_confirmed_starter_e8a`로 실행해 최종 `data/experiments/confirmed_starter_e8a_20260913_attempt4/`에 **8개 합성 이벤트**와 원문 3개, field/snapshot/prediction/후속 정정 링크, replay JSON 및 전후 보존·출력 SHA256 manifest를 남겼다. 앞선 시도 폴더는 덮어쓰지 않고 보존했다. 최종 replay의 실제 fit/실제 확률 발행/실제 성능 계산은 모두 0이며 상태는 `not_activated`다. 12개 직접 보존 경로의 전후 SHA256과 새 출력 5개 SHA256이 일치한다. 추가로 E7-B 봉인 manifest가 열거한 상위 112경로와 E7-B 출력 68경로를 현재 다시 해싱해 불일치 0건을 확인했다. 원문 blob과 event hash chain 재검사도 통과했다.

## 합성 반례와 검사

cutoff 직전/동일/직후, 수신은 직전이지만 파싱은 직후인 경우, clock 역행·요청시각 역전·잘못된 timezone, 옛 원문 사후 import, effective 이전의 늦은 정정, 일정 변경에 의한 cutoff 소급 이동, 누락·추가·중복·부분 출전표와 말 식별자 불일치, feature 이용 가능성 미확인과 A 모델 거부, 동일/충돌/동시 재시도, observation/ready 중간 쓰기 실패·복구, 사후 DNS·DNF·실격·동착·경주무효/결과 정정 후 입력·예측 불변, 원문 손상 감지를 `tests/test_confirmed_starter_e8a.py`의 **17개** 합성 테스트로 확인했다. 실제 결과를 불러 성능을 계산하는 테스트는 없다.

관련 3개 Python 파일의 Ruff check/format은 통과했다. 전체 `.venv/bin/pytest -q`와 `.venv/bin/python -m pytest -q`는 각각 **594 passed, 2 warnings**다. 경고는 기존 Starlette deprecation과 Polars asof sortedness다. 전체 `git diff --check`는 범위 밖의 기존 dirty `src/horse_racing/web/racecourse.py:347` EOF 빈 줄 1건을 지적한다. 해당 파일은 건드리지 않았다.

## 수집 활성화 계획 — 이번에는 실행하지 않음

1. 독립 검증 후 실제 수집 활성화 여부를 결정한다. 현재 `Settings.data_go_kr_service_key`의 **존재만 확인**했으며 값은 출력하지 않았다. 실제 호출·인증 성공·quota는 미검증이다. `KraApiClient.iter_entry_sheet_pages`/API26_2와 `ingest_race_schedule`이 사용하는 race-plan 원천을 후보 adapter로 삼되, 기존 운영 upsert 경로는 사용하지 않는다. 일정/출전표 각 페이지의 raw bytes·pagination totalCount·source ID·요청/수신/파싱/영속화/공개/적용 시각을 격리 경로에 기록하도록 별도 사전 검증이 필요하다.
2. 관측 주기 초안은 예정 시각 T−120분부터 5분 간격, T−35·T−31분 및 cutoff 직전 촘촘한 확인이다. 실제 원천 갱신 지연, API 응답의 부분성, T−30 정확 경계와 clock skew, pagination의 독립 완전성은 실측 전 미확인이다. 이 최소 구현의 정확시각 seal gate는 실전 운영 가능성을 입증하지 않는다. 확정 주기는 독립 검증·실측 후 정한다.
3. 장애·quota·부분 페이지·일정 누락/정정·출전표 식별자 충돌은 실패/공백 이벤트로 남기고 prospective 적격을 부여하지 않는다. T−30 전에 유효 관측을 얻지 못한 경주는 사후 성공으로 복구하지 않는다. 저장은 운영 DB 밖 별도 원문 CAS와 append journal, 동기화/백업 및 외부 시각·보존 정책은 활성화 전 설계해야 한다. shadow/raw orphan은 검증 후 회수 가능하지만 승인 event는 덮어쓰지 않는다.
4. 실제 F_t feature별 PIT/계산 계약, 실제 136열 전체, 모델 학습 모집단, DNS·경주무효 평가 정의, 시장 배당 원천/관측주기, 실제 clock 및 원천 가용성은 모두 미검증이다. 기존 확정배당을 당시 시장 관측으로 재명명하지 않는다. 별도 승인 전에는 실전 확률 적격도 성능 평가도 없다.

SHA256 연결은 우발적 변조·누락을 발견하는 로컬 검사일 뿐, 기록 전체의 악의적 재작성이나 외부 공인시각을 방지하지 않는다. 합성 replay 통과는 실제 수집 성공이나 미래 누수 부재의 증명이 아니다. 독립 검증 담당자는 raw↔event↔field↔snapshot↔prediction hash와 원자성/경계 반례, 현재 운영 경로와의 비연결, `not_activated` 한계를 우선 재검사해 달라.
