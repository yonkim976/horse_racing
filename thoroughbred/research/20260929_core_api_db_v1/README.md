# 더러브렛 API 코어 DB v1 (검증 중)

> 2026-10-15 [일별조교 기승자 이름 연결](../20261015_daily_training_rider_links_v1/README.md)을 추가했다. 공식 번호282개로1,599,487행에 이름을 연결했으며 송당스카이 충돌1행은 이름·연결ID를NULL로 유지했다. 번호 미연결70개·190,375행과번호미기재3,383,170행을 보존했다. 사전35항목·주 에이전트 독립12항목 및 기존208객체 전체 행/스키마/뷰 보존 검증을 통과했다. 현재213객체·원천manifest28행이다. 사건일 범위는 기존2010-01-01~2026-09-29이며 심판리포트 보류와 모델 시점 검증 잔여는 유지한다.

> 2026-10-02 사용자 요청에 따라 심판리포트 단계를 보류하고 [통과조까지의 검증](../20261002_core_validation_before_reports_v1/README.md)을 완료했다. 심판리포트·제재 적재 직전180객체 기준본에서 분야별173항목 통과·실패0개, 입력384파일 해시 일치, 등록178객체 행 수 불일치0건이다. 활성208객체 파일은 수정하지 않았으며, 활성 파일에서도 해당 단계를 제외할지는 사용자 확인 대기다. 이번 검증 범위와 활성 파일 상태를 구분한다. 역사적 완전성·공개 시점·최종 동결은 미확정이다.

> 2026-10-02 [심판리포트·제재 본 적재 및 말별 연결](../20261002_steward_reports_v1/README.md) 완료: 리포트14,867경주·범위 안 제재46,562행·공식 말12,546두에 관련 문단149,008연결을 추가했다. `horse_steward_history`146,612행에서 반복 추가사항을 정리해 말별 조회한다. 현재208객체·원천manifest27행이다. API 리포트 공백14,857확정경주·미확정 언급후보6,162행·과거 공개시각 및 전체 DB최종동결은 남아 있다. 아래 수치는 각 적재 당시 기록이다.

> 2026-10-02 [통과조 본 적재·독립 검증](../20261002_passing_groups_v1/README.md) 완료: 확정 29,710경주·144,001경주/지점(API142,227·성적표1,774), API/RPT 원문 차이50지점은 API우선과 차이 표시를 보존했다. 기존153객체 보존을 검증했으며 당시 180객체·원천manifest26행이다. 아래 초기 코어 수치는 당시 기록이다.

2026-10-01 현재, 2010-01-01~2026-09-29의 서울·부산경남·영천 자료를 [새 DuckDB](../../data/core_api_2010_20260929_v1/thoroughbred_core.duckdb)에 묶었다. 제주 경주는 포함하지 않았다. 경주·심사·구간 원장은 마사회 API로 만들었고 기존 연구 스냅샷은 입력으로 사용하지 않았다. API에서 말 신원이 누락된 주행심사 104행은 별도 원장으로 연결했다. 이 중 99행은 보관 RPT와 운영 SQLite 대조, 5행은 사용자 확정과 RPT·말 프로필 대조에 근거한다. **이 버전은 아직 최종 동결 DB가 아니다.**

## 입력과 테이블

- [마사회 API 날짜 원장](../20260929_calendar_api_v1/README.md): `calendar_days` 18,348행, `race_plan` 29,826행, `race_execution_flags` 29,826행 및 116경주 최종 판정 `race_nonexecution_adjudication`. `race_plan_full_api` 29,826행에는 계획 API의 **전체 21개 원문 필드**(경주 종류·거리·등급·부담중량 방식·연령/성별 조건·예정시각 등)와 응답 내 위치를 보존했다.
- [경주 결과 원장](../20260929_race_results_api_v1/README.md): `race_events` 29,826행, `runner_results` 331,811행. 확인된 결과 API 오류 경주 72개와 말별 753행은 활성 원장에서 제외했다.
- [주행심사 결과 원장](../20260929_trial_results_api_v1/README.md): `trial_sessions` 6,199행, `trial_participants` 61,777행. API 원문에 말 ID·이름이 모두 없는 104행은 `unidentified_trial_participants`에도 남겼다. [신원 보완 원장](../20260930_trial_horse_identity_v1/README.md)에서 99행을 RPT·운영 DB로 검증하고 5행을 사용자 확정 근거로 연결해 `trial_participants_resolved` 뷰에 반영했다. `unresolved_trial_participants`는 0행이다. 원문 말 ID·이름 열은 변경하지 않았다.
- [2026-09-17 영남 심사 장소·거리 재검토](../20261001_yeongnam_trial_venue_recheck_v2/README.md): 공식 2026년 시행계획 65·66쪽과 사용자 설명을 근거로 기존 4회차·48참가행을 부산경남·1,000m로 보완했다. `trial_venue_review` 1행과 `trial_sessions_venue_reviewed`·`trial_participants_venue_reviewed` 뷰에 근거 유형과 거리를 남긴다. 사건 API·RPT에 장소·거리가 직접 적혀 있다는 의미는 아니며, API의 `영남`과 참가 원문은 보존한다.
- [마사회 API 구간기록](../20260930_section_api_v1/README.md): `section_measurements_api` 4,380,065행과 `runner_section_coverage_api` 330,465행. 시간·말별 통과착순을 원문 필드와 출처 위치별로 보존하고, 값이 없는 말도 커버리지 원장에 남긴다. `section_parse_issues_api`는 0행이다.
- [말·기수·조교사·마주 기준정보 감사](../20260930_entity_reference_audit_v1/README.md): 공식 ID로 관찰된 `entity_reference_roster` 25,814개(말 23,814·기수 337·조교사 225·마주 1,438)와 날짜별 원문 이름 `entity_name_observations` 26,807행을 적재했다. `confirmed_runners_entity_linked` 330,465행과 `trial_participants_entity_linked` 61,777행에서 원문 ID를 보존하며 기준정보 ID를 연결한다. `unresolved_entity_references` 5,548행은 최초 원천 결측·대체표기 감사 원장이다. 후속 보완 결과를 반영한 현재 미연결 수와는 다르며, 현재 조교사 예외는 `role_link_exceptions_current`에서 조회한다. `non_person_placeholder_observations`는 `0AAAAA`/`휴양마` 163행을 별도로 보존한다.
- [경주 조교사·마주 결측 감사](../20260930_missing_entity_source_audit_v1/README.md): `race_role_gap_audit` 38행에 원본 API와 재조회 및 성적표 근거를 기록했다. `confirmed_runners_entity_reviewed`는 취소 전 공식 API에서 ID가 확인된 1행의 조교사·마주를 검토 열에 별도로 표시한다. 당시 남은 37행은 2026-10-01 공식 성적표 검토로 모두 보완했다.
- [2026-10-01 조교사·마주 예외 통합 검토](../20261001_role_review_v1/README.md): `race_trainer_owner_review` 60행과 `trial_trainer_review` 224행 및 각각의 `_evidence` 전체 근거 원장을 적재했다. 경주 조교사·마주 37행씩, 심사 조교사 61행을 공식 사건별 링크 ID로 보완했다. 원문 ID·이름은 유지하고 검토 뷰의 `*_entity_id_with_review`, `*_name_with_review`에 보완 결과를 표시한다. `role_link_exceptions_current` 186행은 비인물 대체표기 164행(경주 23·심사 141)과 심사 조교사 미확정 22행으로 구분된다.
- [심사 기수 결측 감사](../20260930_trial_jockey_gap_audit_v1/README.md): `trial_jockey_gap_audit` 5,121행에 원본 API의 필드 생략과 보관 성적표의 이름 근거를 기록한다. `trial_participants_entity_reviewed`는 RPT 후보명과 공식 웹 기수명·ID를 출처별 열에 표시하며 이름만으로 ID를 추정하지 않는다.
- [공식 웹 성적표 재조회](../20260930_trial_jockey_gap_audit_v1/official_web_missing_24.jsonl): 로컬 RPT가 없던 24행을 마사회 공식 화면에서 날짜·심사차수·마번·말 ID로 재확인했다. `trial_jockey_official_web_missing_24`와 검토 뷰의 `official_web_jockey_*_scheduled` 열에 편성 기수 이름·공식 ID를 보존한다. 24행 모두 API 기록시간 0초이고 웹 결과도 시간 `0:00.0` 또는 공란이므로 실제 기승 ID 연결로 취급하지 않는다.
- [마명 충돌 18행의 공식 웹 대조](../20260930_trial_jockey_gap_audit_v1/official_web_name_conflicts_18.jsonl): 공식 화면의 말 ID·마번이 API와 18행 모두 일치해 기수 이름·공식 ID를 확인했다. `trial_jockey_official_web_conflict_18`과 검토 뷰의 `official_web_jockey_*_conflict_reviewed` 열에 보존한다. 양수 주파시간 16행은 완료 심사 기수, 출주취소 2행은 편성 기수로 구분한다. 검토 뷰의 `jockey_name_with_review`는 API 직접 이름과 출처가 표시된 공식 웹 보조 이름을 합쳐 심사 참가 61,777행 모두 채워진다.
- [RPT 기수명만 있던 5,079행의 공식 ID 대조](../20260930_trial_jockey_gap_audit_v1/official_web_jockey_ids_5079.jsonl): 3,505개 마사회 성적표 화면에서 말 ID·마번·주파시간을 대조해 5,079행 모두 공식 기수 ID를 확인했다. `trial_jockey_official_web_rpt_5079` 표에 근거를 보존한다. 완료 4,420행과 0초 편성 659행을 구분하며, 원문 API 기수 열은 변경하지 않았다. 기존 서울·부경 기준정보에 없던 제주 소속 김동규(ID `003097`)의 서울 심사 3행은 [공식 프로필](../20260930_trial_jockey_gap_audit_v1/official_jockey_profile_supplement.jsonl)을 근거로 보조 기준정보에 추가했다.
- [RPT 마명 차이 18행 재검토](../20260930_trial_jockey_gap_audit_v1/rpt_name_discrepancy_review.jsonl): 공식 `db7` 마명변경 자료에서 9마리·13행의 과거 이름을 확인했고, 이전 자료가 확인되지 않은 5행은 미확정으로 둔다. `trial_rpt_name_review_18`과 검토 뷰의 `rpt_horse_name_review_*` 열에서 조회한다. 말 ID와 기준 마명은 API 값을 유지한다.
- `section_missing_finisher_review` 2행: 완주 기록은 있지만 API 구간값이 모두 빈 용왕성·동촌의 사용자 제공 경주 후 문구와 원인 판정 상태를 보존한다. 문구만으로 API 결측 원인을 확정하지 않는다.
- [휴장·취소 공백 추가 검토](../20261001_closure_gap_followup_v4/README.md): `official_closure_intervals` 81구간(기존 문서 근거 75·공식 시작/API 종료 경계 2·사용자 제공 KRA 연간계획 근거 4, 경주장별 날짜 552개). `closure_boundary_review` 2행과 `reported_closure_interval_leads` 10행을 보존하고 `closure_gap_review_candidates` 26행, `closure_plan_amendment_review` 3행, `closure_review_questions` 19행을 추가했다. 신규 구간은 서울·부산경남 2021 신정·설 휴장이다. 보도 후보는 공식 원본 확인 구간으로 승격하지 않았다. `race_nonexecution_subtype_review` 29행·116경주 판정 전체와 기존 `_prior_review` 표도 동일하다. `official_cancelled_days`는 4개 날짜, `unresolved_race_days`는 0행이다. `source_manifests`에 단계별 원천·검증 JSON을 보존한다.

원천 값과 앞자리 0이 있는 공식 ID를 안전하게 보존하려고 CSV 열은 **문자열 그대로** 적재했다. 날짜·숫자형 해석은 사용 목적이 정해진 조회에서 명시적으로 수행한다. API 원문 JSON은 앞 단계 `raw/`에 있으며, 결과 행에는 원문 파일·항목 인덱스가 있다. DB와 함께 [빌드 매니페스트](../../data/core_api_2010_20260929_v1/manifest.json)를 보관해야 원천 해시를 재검증할 수 있다.

## 확인된 시행 뷰

- `confirmed_races`: 계획 키와 양수 완주기록이 함께 있는 경주 29,710건.
- `confirmed_runners`: 해당 경주의 결과 API 말별 행 **전체** 330,465행. 완주하지 않은 출전행도 보존한다.
- `confirmed_races_2017plus`, `confirmed_runners_2017plus`: 2017년 이후 조회용이며 각각 16,547경주·182,062행이다. **결과·착순 열이 포함된 원장 뷰이므로 그대로 모델 입력 피처로 사용하지 않는다.** 피처의 이용 가능 시점 검증은 후속 단계다.
- `race_execution_adjudicated`: 계획 29,826경주 모두의 원천 시행 플래그와 116건 최종 판정을 함께 조회한다. 116건은 모두 `no_valid_completed_race`이며, 경주불성립 2건은 취소와 구분한다. 종전 사유 문구만 확인됐던 29건도 후속 공식 성적표의 취소 표기로 확정했다.

## 기준정보 연결과 검토 대상

말·기수·조교사·마주는 경주 결과 또는 심사 원천의 **공식 ID 문자열**로만 연결했다. 한 ID에 여러 이름이 기록되거나 같은 이름이 여러 ID에 쓰인 사례가 있어 이름은 날짜별 관찰값과 검토 지표로만 남겼다. 경주 출전 330,465행 중 말·기수·마주 ID는 모두 연결됐고, 검토 후 조교사 ID는 330,442행 연결됐다. 남은 23행은 공식 성적표에서도 `0AAAAA`/`휴양마`가 확인된 비인물 대체표기다. 최초 원문 조교사·마주 공란 38행 중 1행은 보관 API26, 37행은 사건별 공식 성적표 링크로 보완했다.

심사 참가 61,777행은 말·검토 후 기수 ID 61,777행, 검토 후 조교사 ID 61,614행이 연결됐다. 기수 ID 56,656행은 API 직접값이며, 누락된 5,121행은 공식 웹 성적표로 보완했다. 양수 주파시간 54,502행과 0초 7,275행은 각각 `jockey_id_for_completed_trial`, `jockey_id_listed_without_completed_time`으로 구분한다.

심사 조교사 원천 `-` 84행 중 61행은 정확한 사건·마번·말 ID·기록시간이 일치하는 공식 표의 인물 ID로 보완했다(양수 1·0초 60). 큐비트업 1행은 API `-`지만 공식 표에 `0AAAAA`/`휴양마`가 있어 비인물로 확인했다. 나머지 22행(양수 19·0초 3)은 올바른 공식 페이지에서도 해당 말의 마번 행이 없다. [말 프로필·심사 결측 검토](../20261001_trial_22_profile_absence_review_v1/README.md)에서도 원인은 확인되지 않아 사용자 지시로 조교사 ID·이름 결측을 원인 미상 원천 오류로 처리하고 검토를 종료했다. 말·심사 원문은 보존하며 ID는 NULL을 유지한다. API `0AAAAA`/`휴양마` 140행도 공식 웹과 일치한다. `trainer_entity_id_with_review`를 현재 연결 결과로 사용하고, 기존 `trainer_entity_id`는 API 직접 연결 결과로 보존한다.

최초 예외 감사 `unresolved_entity_references`는 과거 원천 결측을 추적하는 테이블이며 현재 미확정 목록이 아니다. 현재 예외 목록은 `role_link_exceptions_current`를 사용한다. 186행 중 비인물 164행과 검토 종료된 원인 미상 오류 22행을 구분한다. `trial_trainer_source_error_decisions`와 `trial_trainer_errors_closed`에서 종료 근거를 조회하고, 현재 검토 대기 `role_link_exceptions_pending`은 0행이다. 대기 0행은 ID가 모두 연결됐다는 뜻이 아니다. API 마주 ID는 있지만 원문 마주명이 없는 경주 1행(2026-08-09 서울 5경주 11번 퀸즈플라잉, 마주 ID `010424`)은 이름을 추정하지 않았다. ID 연결은 확인됐다.

추가 원문 감사에서 경주 결측 38행은 모두 `API4_3` 응답 자체에 조교사·마주 네 필드가 없었다. 이 행들은 출전취소 코드 `95`를 가지지만 같은 코드의 다른 1,992행에는 ID가 있어 필드 생략의 내부 원인은 단정할 수 없다. 심사 기수 결측 5,121행도 `API20_1` 응답 원문에 기수 ID·이름 두 키가 아예 없다. 보관 RPT의 이름 증거는 말 이름 또는 기존 말 연결까지 대조된 5,079행만 보완한다. 이 5,079행과 마명 충돌 18행, 로컬 RPT가 없던 24행의 기수 ID는 공식 웹 성적표에서 직접 확인했다. 그중 685행은 주파시간이 0이므로 편성 기수로만 취급한다. 원본 출전·심사 테이블의 필드는 그대로 보존한다.

API8_2 말 프로필의 2026-09-23 조회 집합에서 관찰된 말 ID 23,814개가 모두 확인됐다. 현재 기수·조교사·마주 목록 API307/308/309와의 ID 일치는 각각 337/337, 225/225, 581/1,438이다. 마주 857개 ID가 현재 목록에 없더라도 과거 경주의 공식 ID를 지우거나 이름으로 다시 연결하지 않았다. 프로필 캡처는 2026-09-23~30의 **현재 조회 결과**이고 일부는 이 DB의 사건 종료일 뒤에 수집됐다. 이 프로필의 현재 조교사·마주 소속이나 상태를 과거 경주 관계 또는 시점 이전 모델 입력으로 소급하지 않는다. `horse_profile_snapshot_membership`와 `person_reference_profile_snapshots`는 원천·캡처일을 가진 별도 스냅샷이다.

## 검증과 남은 판정

빌더는 모든 입력 파일 해시와 출처별 행 수, 경주·심사 키 유일성, 심사 참가자의 회차 연결, 확정 경주의 계획 일치, 공식 휴장일의 시행 충돌 여부를 검사한다. [KRA 공식 연간 통계](https://race.kra.co.kr/globalEn/racingStatistic.do)의 2021~2025년 서울·부산경남 시행일·경주 수 10개 조합과 API 집계가 모두 일치한다.

부산경남 2019-11-29와 서울 2020-08-09를 포함한 116개 계획 경주는 현재 근거에 따라 모두 유효한 완주 경주가 아닌 것으로 판정했다. 종전 세부 유형 미확정 29건 모두 공식 성적표의 취소 표기로 확정했다. 부산경남 2015-03-29 5·6경주도 공식 날짜별 성적표 목록에서 날짜·경주번호·취소 표기·출장로 점거 사유를 함께 확인했다. 세부 유형 미확정은 0건이다. 서울·부산경남 2020-09-01~10-15 중단 구간은 공식 문서의 시작일과 API의 10-16 실제 재개일로 보완했으며, 종료 공지의 명시 날짜로 표시하지 않는다. 이번 보완 후 빌더 검증 60개가 통과했고 이전 DB 사본과 원장 보존을 대조했다. 영남 주행심사 2026-09-17의 장소·거리는 [재검토 원장](../20261001_yeongnam_trial_venue_recheck_v2/README.md)의 공식 계획 및 사용자 설명 근거로 부산경남·1,000m로 보완했다. 심사 조교사 ID 결측 22행은 사용자 지시로 원인 미상 오류로 분류해 검토를 종료했다. 2010~2026년 공식 휴장 구간은 현재 **부분 목록**이며, 무경주 평일을 휴장으로 자동 분류하지 않았다. 상세 출전 상태 판정은 후속 단계다.

API 구간기록은 경주 이후에 공개되는 결과 자료다. 해당 경주의 예측 시점 설명변수로 직접 사용하지 않는다. 경주 단위 **통과조**는 이 단계의 `section_measurements_api`에 포함되지 않았다.

주행심사 API에는 정식 경주 등급과 심사 거리 필드가 없다. 등급은 만들지 않으며, 2026-09-17 영남 심사의 거리만 공식 계획 근거를 가진 별도 `reviewed_distance_m`으로 보완했다. 다른 날짜의 거리는 이번 검토에서 채우지 않았다.

재생성: 저장소 루트에서 `.venv/bin/python thoroughbred/research/20260929_core_api_db_v1/build_core_db.py`를 실행한다. 빌더는 API 계획 원문에서 [전체 계획 필드 추출본](race_plan_full_api.csv)을 재생성한다. 입력 CSV 원문이 바뀌면 앞 단계 빌더·검증을 먼저 수행해야 하며, 해시가 맞지 않으면 DB 빌드를 중단한다.
