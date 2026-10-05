# 부경 역사 연구 데이터 사전

격리 SQLite: `history.sqlite3`. 모든 경주 표의 `meet`는 정수 `3`이다. 경주 키는 `(meet, race_date, race_no)`, 출전·결과·구간 키는 여기에 공식 `hr_no`를 더한다. 날짜는 `YYYY-MM-DD`, 경주번호와 출전번호는 정수다. 출전번호·마명은 대조 필드이며 말의 식별키가 아니다.

| 표 | 단위와 기본키 | 의미·주의 |
| --- | --- | --- |
| `race` | 경주; `(meet,race_date,race_no)` | `label_scope=mock/warmup/target`. 2005-09-30 이후 정식 경주는 warm-up, 2006년 이후 정식 경주는 target. `race_type`, `race_class`, `distance_m`, `burden_type`, `track_raw`, `weather_raw`는 **당시 결과 원문** 그대로다. 결과가 전부 0인 경주는 유효 순위 라벨로 사용하지 않는다. |
| `entry` | 경주 출전마; 경주 키+`hr_no` | 공식 `jkNo/trNo/owNo`를 경주 당시 관계로 저장. `owner_no_raw_json`은 원문 JSON 숫자/문자열 타입 및 선행 0을 보존한다. 숫자형 `owNo`만 6자리 문자열로 채운 `owner_no`를 별도 제공한다. `horse_weight_raw`에서 `433(+5)`, `430()`의 본중량·증감을 분리. 0·빈 값은 유효 체중으로 간주하지 않는다. |
| `result` | 출전마의 사후 결과; 경주 키+`hr_no` | `finish_raw` 원형 보존, `finish_order`는 정상 양의 순위만. 91 실격, 92 주행중지, 93 출발제외, 94 경주제외, 95 출전취소, 99 경주취소, 0 무효/미확정 또는 순위 없음으로 구분한다. 동착은 같은 `finish_order` 복수 행으로 보존. `race_time_s`는 초. 결과는 현 경주의 예측 입력에 넣지 않는다. |
| `section` | 말·원천 필드; 경주 키+`hr_no`+`source_field` | `value_s`는 원천의 초 단위 값. `buS1fTime`, `buS1fAccTime`, `buG3fAccTime`, `bu_3fGTime` 등을 별도 행으로 보존하고 0도 원형 값으로 둔다. 필드명 `Acc`/`G`의 의미를 전 기간·원천에 검증한 단일 수치로 병합하지 않아 `semantic_status=source_specific_unverified`다. 사후 기록이다. |
| `horse_entity`, `actor_entity` | 공식 말 ID, `(actor_type,actor_no)` | 경주 이력에서 관찰된 첫·마지막 날짜와 이름 수. 현재 프로필을 과거 관계로 소급하지 않는다. 사람 유형은 jockey/trainer/owner. |
| `training_event` | API 원문 행; `event_id=source:month:page:row` | 일별 조교 `horse_training`은 `duration_seconds`, 시작·종료시각 원형, 강도 횟수, 원문 마방·훈련기승자 등. 출발조교 `start_training`은 훈련일·말 ID·평가 문구를 같은 사건 표의 다른 `source_type`으로 보존한다. 서로의 빈 필드가 0이라는 뜻이 아니다. `availability_unverified`. |
| `medical_event` | `dacom72` Text 물리적 행; `event_id=path:line` | 사건일, 마명, 마방번호, 시설, 진단 원형. 직접 말 ID가 없어 `dacom71` 경주별 출전번호·마명·진료일 문구와 공식 출전 키가 함께 맞고 후보가 유일할 때만 `confirmed`. 나머지는 `ambiguous/unmatched`; 후보 ID·원문 위치 보존. `retrospective_only`. |
| `medical_api_event` | 공식 진료 API 행; `event_id=path:row` | 2019년 이후 관측. 공식 `hr_no`, 진단 두 필드 및 시설·마방. `-`만 있는 행과 실제 내용 행을 `has_content`로 분리. 2019년의 소수 양성 행은 전수성을 보증하지 않는다. `availability_unverified`. |
| `race_day_weight` | Text 체중표 행; 경주·출전번호·파일 | 본중량/증감은 kg. 경주 키+출전번호+마명이 공식 출전과 모두 맞을 때 `hr_no` 확정. 2006년 API `wgHr`의 파싱 결과와 별도로 대조한다. |
| `entry_equipment` | `dacom71` 출전마 행; 경주·출전번호·파일 | 원문 장구 및 이어지는 진료 문구를 `detail_raw`로 보존. 장구 종류·착탈의 정규 코드화는 아직 하지 않았으므로 범용 범주형 feature로 사용하지 않는다. |
| `legacy_id_repair` | 운영 DB의 과거 임시 ID 행 | 운영 DB는 읽기만 했다. 경주일·번호·`hrNo`·출전번호·마명이 모두 맞으면 경주 당시 공식 `trNo/owNo`를 채우고, 충돌 행은 비워 둔다. |
| `dacom01_reconciliation`, `dacom11_reconciliation` | Text 원문 행 | 공식 출전번호·마명 교차검증과 사후 순위·시간·체중 대조. `dacom11`은 보관 범위가 2015년 이후 일부여서 2006년 API 독립 결과 대체물로 간주하지 않는다. |
| `research_entry`, `research_source_features` | 정식 warm-up/target 출전 키 | 과거 정식경주 횟수·승수, 직전 28일 일별/출발조교, 확정 Text 진료·내용 있는 API 진료만 **사건일 < 경주일**로 연결. 현재 경주 결과는 `current_*` 라벨 열에만 남긴다. 과거 게시시각 미검증이므로 `retrospective_only`이며 실시간 사전 예측 feature 승인본은 아니다. |
| `source_availability` | 원천·연도 | 실제 유효 행이 관측되면 `observed_availability_unverified`, 원천 시작 전 연도는 `source_unavailable`, 시작 후 0건은 `zero_response_unverified`. 0건을 사건 부재로 해석하지 않는다. |
| `trial_result_text` | `dacom23` 주행심사 Text 물리적 행 | `label_scope=trial_only`로 정식 결과와 완전히 분리. 직접 공식 말 ID가 없어 마명으로 자동 연결하지 않고 `hr_no=NULL`, `link_status=unmatched`로 보존한다. |
| `race_notice_text` | `dacom13` 취소·기수변경 공지 물리적 행 | 공지의 경주일·경주번호·출전번호·마명이 공식 결과와 맞는 경우만 `hr_no` 연결. 공지 원문과 충돌·미연결 상태를 보존하며 게시시각 검증 전에는 연구 예측 입력에 넣지 않는다. |

`source_path`와 `source_row` 또는 `line_no`로 저장 원문까지 역추적할 수 있다. `sha256_manifest.csv`는 사용한 API·Text 원문, 원래 수집 원장, 실행 코드와 결과 파일의 SHA256을 포함한다. `coverage_year_source.csv`, `year_quality.csv`, `event_coverage.csv`, `race_regime_year.csv`는 파일 날짜가 아니라 실제 사건·경주 날짜를 중심으로 해석한다.

구간 의미는 [KRA 공식 용어 설명](https://race.kra.co.kr/down/term_desc.pdf)과 [부경 공식 결과표](https://race.kra.co.kr/globalEn/resultsRaceDetailBusan.do?rcDate=20250523&rcNo=2)를 참고했다. S1F는 출발 후 200m, G3F는 결승 전 600m 지점이며 결과표에는 구간 시간과 누적 시간이 별도로 제시된다. API 필드와 Text 열의 일대일 의미 매핑이 확인되기 전까지 `section` 원천 필드를 합산·대체하지 않는다.
