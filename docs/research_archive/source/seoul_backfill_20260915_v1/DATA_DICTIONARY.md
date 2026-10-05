# 서울 백필 v1 데이터 사전

범위는 서울 `meet=1`, 공식 API4_3 결과 2000-01-08~수집 시점의 최신 확정 경주다. 기본키는 경주 `(meet, race_date, race_no)`, 출전 `(meet, race_date, race_no, hr_no)`다. `history.sqlite3`는 기존 운영 DB와 완전히 별개다.

| 테이블/파일 | 행 단위와 핵심 값 | 원천·시간 계약 |
|---|---|---|
| `race` | 경주 키, `race_class`(원문 등급), `burden_type`, 거리, `rating_condition_raw`, `rating_system`, `surface_regime`, `mile_1600_era`, `official_result_state` | API4_3 경주결과. 분류는 `race_regime.csv`로 역추적. `confirmed`는 양수 정상 결과가 있는 경주이며 취소·미확정과 구분한다. 현재 경주의 결과원문은 예측 입력이 아니다. |
| `entry` | 공식 `hr_no`, 당시 `jockey_no/trainer_no/owner_no`, 마번, 부담중량, 체중, 레이팅 원문값 | API4_3 출전 행. ID는 숫자형 원문만 고정 자리수 문자열로 복원; 이름으로 ID를 만들지 않는다. `source_path/source_row`가 원문 JSON 행을 가리킨다. |
| `result` | 원문 `finish_raw`, 정상 착순 `finish_order`, `result_status`, `race_time_s`, `is_dead_heat` | API4_3 사후 확정 결과. 공동 착순은 원문 순위 반복과 `is_dead_heat=1`로 보존. 91 실격, 92 주행중지, 93 출발제외, 94 경주제외, 95 출전취소, 99 경주취소로 분리한다. 2023-01-15 서울 9R의 98은 뜻이 확인되지 않은 특수코드로 별도 보존한다. 숫자 순위라도 `rcTime=0`이면 `ranked_time_missing_unconfirmed`로 격리한다. |
| `section` | 출전×원천 필드별 구간값과 통과순위, `time_basis`, `canonical_closing_s` | 서울 API `se*AccTime`은 출발 누적시간. G3F/G1F의 종반 600/200m는 유효 완주기록에서 누적값을 빼서 별도 열에만 저장한다. 0 또는 미제공 원문은 JSON에 그대로 있고 시간 행으로 만들지 않는다. 코너 좌표를 추정하지 않는다. |
| `text_sections.csv` | 보관 `dacom11`의 원문 구간, 공식 출전 키 연결 상태, API와의 값 차이 | Text S1F/코너는 누적, G3F/G1F는 종반 주파시간. 동일 코드라도 API 원값과 직접 합치지 않는다. |
| `training_event` | 일별·출발조교 원문 행 각각 한 건, 공식 `hr_no`, 사건일, 지속시간/횟수 등 | 기존 서울 월별 원문을 해시 참조. 최초 사건일은 일별 1998-09-25, 출발 2009-05-21. 원문 파일의 사후 수집 시각이 당시 게시 시각을 증명하지 않는다. |
| `race_day_weight` | `dacom12` 마번·마명·체중·증감, 공식 출전 ID 연결 상태 | 서울 Text 최초 파일일 2003-09-06. API4_3 `wgHr`는 2000년 결과 행에도 존재하므로 Text 미존재와 체중값 미존재를 구별한다. |
| `medical_event` | `dacom72` 사건일·마명·진단·축사, 후보 ID와 연결 근거 | 최초 파일일 2003-09-25이며 첫 사건일은 더 이를 수 있다. `dacom71`의 날짜가 적힌 출전마 진료 기록과 같은 경주의 공식 마번·마명이 일치할 때만 `confirmed`. 이름만 맞으면 `ambiguous`, 후보도 없으면 `unmatched`. |
| `entry_equipment` | `dacom71` 출전마별 진료·장구 원문 줄 | 출전마 번호·마명과 공식 출전 키가 동시에 맞는 행만 확정 연결. 빈 장구 내용도 원문 줄 보존 대상이다. |
| `track_condition` | 경주별 주로·날씨·함수율 원문 | API4_3 경주결과의 사후 관측값. 2016-08-15~26은 작업 중 내·외주로 경로 미확정으로 `surface_transition_or_unknown`. |
| `research_entry` | 경주·말 1행, 이전 경주/28일 조교·출발조교·확정 진료 집계, 현재 결과 라벨 | 이력은 같은 말 공식 ID의 **경주일 이전**만 집계한다. 현재 결과는 라벨이고 입력이 아니다. `*_status`가 원천 미존재·부분 기간·관측상 0·게시시각 미검증을 구분한다. |
| `source_inventory` | 재사용한 공식 API/Text 파일의 경로·SHA256·바이트·최초 파일/사건일 | 날짜가 있는 원문이라도 당시 실제 게시 시각이 확인된 것은 아니다. 신규 결과 API 요청은 `request_ledger.jsonl`과 새 `raw_results/`를 함께 보라. |

`coverage_year_source_verified.csv`는 연도별 원문·정규화 행 수와 ID 결측을, `verification.json`은 중복/누락과 시대 경계를 요약한다. `unresolved_medical.csv`, `unresolved_official_ids.csv`, `id_name_variants.csv`, `operating_db_disagreements.csv`, `text_section_mismatches.csv`, `text_parse_errors.csv`는 미해결 원장이다. `sha256_manifest.csv`는 새 원문·출력·재현 코드의 해시를 보존한다.
`operating_db_legacy_id_namespace.csv`와 `operating_db_legacy_horse_ids.csv`는 기존 DB의 이름 기반 `text:` ID를 공식 ID 불일치와 분리한다. `operating_db_race_gaps.csv`는 API 결과에는 있으나 기존 완료 DB에는 없는 경주를 결과 상태별로 기록한다. `test_audit.json`은 검사 명령과 결과, `sample_trace.json`은 원문 행을 따라갈 수 있는 사례다.
`result_code_crosscheck.json`은 API4_3 특수 착순 코드와 보존된 2026년 공식 AI 결과의 한국어 상태를 동일 경주·말 키로 대조한다.
`unresolved_result_status.csv`는 원문코드 0·98 및 숫자 순위가 있으나 주파시간이 0인 행을 추적한다. `database_integrity.json`은 SQLite 무결성 검사를 보존한다.

원문 `rating=0`은 레이팅제 도입 이전의 점수 0과 동일 의미가 아니다. 2015-02-07부터 6등급의 무레이팅 말도 있을 수 있다. 시대별 등급 숫자와 2016년 모래 변경 전후 절대 주파시간을 동일 척도로 직접 비교하지 않는다.
