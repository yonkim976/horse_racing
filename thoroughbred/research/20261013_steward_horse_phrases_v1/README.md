# 말별 심판 문구 저장과 마사회 홈페이지 대조

사용자 요청: 상황 분류에 앞서 마사회 출전상세정보의 심판리포트처럼 말별 관련 문구를 저장하고 실제 홈페이지와 배치를 대조한다.

입력은 기존 더러브렛 연구 코어의 말별 문단 연결 전체와 공개 마사회 홈페이지다. 원천 코어는 읽기 전용으로 열고 새 전용 DB에 저장한다. 기존 연구 코어의 범위는 서울·부산경남·영천이며 제주 자료는 이 DB에 포함되지 않는다. 입력 경로·SHA256은 `input_manifest.json`에 기록한다.

## 조회할 DB와 뷰

`outputs/horse_steward_phrases.duckdb`의 기본 조회는 `horse_steward_phrases`다.

| 객체 | 의미 |
| --- | --- |
| `horse_steward_phrases` | 홈페이지에서 해당 말·과거 경주에 실제 배치됐고 공식 과거 명부에 연결된 문구만 제공 |
| `website_horse_phrase_history` | 공식 말 ID와 과거 경주 명부가 확인된 홈페이지 문구만 조회. 같은 문구의 반복 관측은 출처 목록으로 보존 |
| `website_card_rows` | 빈칸을 포함한 홈페이지 표의 모든 행. 현재 출전번호·마명·말 ID·과거 경주·원문·출처 보존 |
| `website_phrase_observations` | 홈페이지 한 행 안의 `●`별 실제 문구와 원문 문자 위치. 모든 관측 보존 |
| `api_horse_paragraphs` | 기존 말별 문단 연결 전체. 과거 출전번호와 원문 위치·연결 근거·관측 위치 보존 |
| `api_horse_paragraphs_without_website` | 홈페이지 문구를 아직 확보하지 못한 말·과거 경주의 API 문단. 기본 조회와 분리한 보완 후보 |
| `website_phrase_review_candidates` | 과거 명부 미확인·현재 출전번호 충돌·본문 자기 말 번호 충돌로 기본 조회에서 보류한 문구 |
| `website_api_comparison` | 홈페이지 실제 문구와 같은 말·같은 과거 경주의 API 문단 비교. 불일치와 API 공백도 포함 |

기본 뷰의 `text_basis`는 `official_website`이며 `website_text_verified=true`다. API 문단 연결은 말이 해당 문단에 언급됐다는 뜻이며 홈페이지의 선택·축약 문구와 동일하다는 뜻이 아니다. 한 말의 홈페이지 문구에도 다른 말의 문장이 포함될 수 있으므로 임의로 삭제하거나 의미를 다시 쓰지 않는다. 홈페이지 직접 관측과 원천 연결만 있는 자료를 같은 검증 상태로 표시하지 않는다.

공식 마번은 앞자리 0을 유지한다. 현재 출전번호는 홈페이지 표의 번호이며, 과거 경주 번호는 `historical_program`이다. 과거 경주 연결에는 홈페이지의 `goScore` 링크를 사용한다. 과거 명부에 공식 말 ID가 유일하게 있고 출전번호가 확인된 경우만 홈페이지 이력 뷰에 포함한다. 본문에 자기 말의 번호·이름이 명시됐을 때 과거 명부와 다른 번호이면 기본 조회에서 보류한다. 이름이 생략된 문구는 홈페이지 행의 공식 마번 링크를 근거로 삼고, 같은 경주에 동명마가 있으면 이름만으로 번호 충돌을 판정하지 않는다. 과거 명부가 없는 행도 원문 관측에는 보존한다. 홈페이지의 빈칸은 정상 주행이나 사고 없음으로 변환하지 않는다.

```sql
SELECT horse_id,display_horse_name,event_meet,event_date,event_race,historical_program,
       phrase_text,text_basis,website_text_verified
FROM horse_steward_phrases
WHERE horse_id='0030166'
ORDER BY event_date DESC,event_race;
```

`display_horse_name`은 해당 문구가 확인된 출전표들 중 날짜가 가장 늦은 표의 표시명이다. 과거 원문 이름과 각 출전표의 이름은 관측 테이블에 그대로 보존하며 이름을 연결키로 사용하지 않는다.

## 수집과 대조

`collection_plan.json`은 최초 대조 전에 고정한 44페이지 목록이다. 2017년 이후 각 지역·연도의 마지막 및 다섯 번째 마지막 시행 경주와, 대화에서 사용한 2018-02-23 부경 9경주·2026-10-11 서울 7경주를 포함한다. 최초 결과는 `outputs/sample_44/`에 보존했다.

API 원문 전체 문단과 홈페이지 문구의 선택·축약 차이가 많아 직접 홈페이지 수집을 확대했다. `coverage_collection_plan.json`은 기존 말별 연결에 등장하는 공식 말 ID 12,546개 전부를 조회 출전표에 포함시키는 추가 수집 계획이다. 각 말의 연구 코어 마지막 출전일 이전 365일 이내 경주를 후보로 삼고, 새로 포함하는 말이 가장 많은 경주를 순서가 고정된 탐욕 방식으로 선택했다. 추가 계획은 2,945경주다. 이는 모든 말의 홈페이지 행 확보를 목표로 하며 각 말의 생애 전체 문구를 수집한다는 뜻이 아니다. 홈페이지 자체의 조회 범위도 선택한 출전표 기준 최근 1년이다.

HTML 원문은 `website_raw/`에, URL·HTTP 상태·수집 시각·바이트 수·SHA256·성공/실패는 `collection_ledger.jsonl`에 추가 기록하고 종료 시 JSON 원장도 저장한다. 요청 매개변수와 실제 경주 제목이 일치하는지 검사한다. BeautifulSoup과 별도 lxml 순회로 모든 표 행의 말 ID·현재 번호·과거 경주·문구를 대조한다. 파서 간 CRLF/LF 차이만 대조 시 통일하며 저장 원문은 유지한다. 저장된 문구는 원문 `<pre>`의 문자 구간에서 재절취할 수 있다.

API 비교는 동일한 공식 말 ID·과거 경주에 한정한다. 공백과 선두 `●`만 비교용으로 정리하며, 부정·마명·서술어를 지우지 않는다. 정확한 문단 일치, 원문 내 발췌, 홈페이지 문구 차이, API 연결 공백, 과거 명부 공백을 구분한다. 홈페이지의 직접 수집 문구는 이러한 API 일치 여부와 별개로 보존한다.

상황 유형, 가해/피해 역할, 손실 추정, 예측 입력은 만들지 않는다. 수집 시각은 과거 공개 시각이 아니며 `historical_publication_time_verified=false`를 유지한다.

## 실행

프로젝트 루트의 `.venv/bin/python`을 사용한다. `prepare`와 `build`는 기존 출력 덮어쓰기를 거부한다. `fetch`는 성공한 캡처를 재사용하고 실패 이력을 보존한다.

```text
.venv/bin/python thoroughbred/research/20261013_steward_horse_phrases_v1/steward_phrases.py prepare
.venv/bin/python thoroughbred/research/20261013_steward_horse_phrases_v1/steward_phrases.py expand
.venv/bin/python thoroughbred/research/20261013_steward_horse_phrases_v1/steward_phrases.py fetch
.venv/bin/python thoroughbred/research/20261013_steward_horse_phrases_v1/steward_phrases.py revalidate
.venv/bin/python thoroughbred/research/20261013_steward_horse_phrases_v1/steward_phrases.py build
.venv/bin/python thoroughbred/research/20261013_steward_horse_phrases_v1/verify_and_report.py
.venv/bin/python -m pytest -q thoroughbred/research/20261013_steward_horse_phrases_v1/test_steward_phrases.py
```

실제 수치·입력 보존 확인·홈페이지/API 비교 결과는 `outputs/summary.json`, 저장 문구 무결성은 `outputs/verification.json`, 전체 비교 행은 `outputs/website_api_comparison.jsonl`에 기록한다. 사람이 확인할 실제 홈페이지 링크와 말별 문구 표는 `outputs/comparison_report.html`에 제공한다.
