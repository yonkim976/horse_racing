# 제주 말별 구간기록·통과착순·통과조 검증 — 2026-10-02

현재 제주 경주 후보 92,513행·9,494경주를 읽기 전용으로 확인했다. 유효 착순(1~89)과 양수 완주시간이 있는 경주는 9,347개이고, 나머지 147개는 기존 판정 원장에서 취소·불성립이 확인된 경주다. 44경주는 일부 출전마만 후보에 포함되므로 마번 연결은 해당 경주의 전체 출전표를 기준으로 검사했다. 현재 품종·후보 포함을 과거 품종 확정으로 해석하지 않는다.

## 정상 확인

- API6·API303 원문 50페이지의 SHA·바이트·행 수·연도를 확인했다. API303 19,933행은 DB 원문·item 위치·원문 파일·해시 및 모든 정규 필드와 일치한다. API4 후보 92,513행의 payload 해시도 전량 일치한다. 말 ID·마번의 동일 경주 중복 키는 각각 0건이다.
- 실제 완주 경주 9,347개 모두 API303에 값이 있는 통과조 지점을 최소 하나 보유한다. 거리별 모든 지점의 완전성을 뜻하지 않는다. API303 없는 13개 후보 경주는 취소·불성립 집합에 포함된다.
- API6의 양수 거리 지점 44,164개에서 거리 범위·증가 이상 0건, 누적시간과 구간시간 44,132개 산술 비교에서 0.15초 초과 차이 0건이다.
- 제주 `sjG3fOrd`는 92,513행 모두 0이다. 제주 G3F는 막판시간이며 G3F 통과착순·통과조를 만들어 넣지 않는다.

## 확인할 시간 원문 4건

| 날짜·경주 | 말 ID·마번·당시 마명 | 원문 이상 패턴 |
|---|---|---|
| 2024-03-02 3R | 3018048·9번 절대권력 | S1F 120초 > 완주 98.3초. 3C 46.2초 |
| 2025-10-17 7R | 3017473·8번 어정적기 | S1F 77.8초 > 3C 52.6초·4C 69.1초 |
| 2026-01-17 5R | 3016494·8번 광해청명 | 막판 G1F 77.2초 > G3F 49.9초 |
| 2026-03-06 8R | 3018729·6번 시긴트 | 막판 G1F 76초 > G3F 48.1초 |

네 건은 저장된 API 원문에 존재한다. 2026-10-02 공식 홈페이지를 대조한 결과, 절대권력 S1F는 `0:20.0`(20초), 어정적기 S1F는 `0:17.8`(17.8초), 시긴트 G1F는 `0:16.0`(16초)로 API와 다르다. 광해청명 G1F는 홈페이지에도 `1:17.2`(77.2초)로 표시되어 올바른 대체 값은 미확정이다. 나머지 S1F·3C·4C·G3F·G1F·완주시간 20개 비교는 일치한다. 원천 오류 발생 경로는 확인하지 못했으며 홈페이지 확인 단계에서는 DB 보정을 하지 않았다. 이후 사용자 승인에 따른 반영은 아래 후속 적재 절을 따른다. [시간 사례 전체](time_review_cases.csv), [홈페이지 표 머리글·대상 행과 대조 결과](website_time_check/evidence.json).

## 결측·원문 차이

- 유효 착순·양수 완주시간 90,210행 중 말별 구간시간이 모두 없는 행은 25행이며 모두 2002년이다. 통과착순 전체 미제공은 2002-11-09 1R 7번 말 3005890의 1행이다. 원문 0값을 실제 시간·착순 0으로 해석하지 않는다. 단순 양수 `rcTime` 분모에는 특수 착순도 포함되므로 그 집계와 구분한다.
- API6 원문이 없는 실제 완주 6경주: 2025-01-10 1R, 05-16 8R, 05-23 3R, 06-27 4R, 07-04 5R, 2026-09-11 5R. 이들은 API303 통과조가 있다. API6 미제공은 말별 API4 구간기록 전체가 없다는 뜻이 아니다. [누락 목록](root_audit/completed_missing_source_keys.csv).
- 같은 지점의 API6·API303 통과조 원문 비교 36,310개 중 36,284개가 완전히 같고 26개는 다르다. 차이는 모두 2002년 14경주에 있다. 다른 API303 칸에 동일 값이 있는 경우도 별도 필드로 기록했으며 연도 전체 칸 교환·우선값 변경을 적용하지 않았다. [두 원문 차이](root_audit/api6_api303_raw_differences.csv).
- 2002년에는 `2435671`, `(29)(14)(57)6(38)`처럼 마번을 붙여 쓴 구형 표기 후보 10지점이 있다. 이를 큰 말 번호나 잘못된 말 ID로 단정하지 않고 파싱을 보류했다. `·` 등 보수 문법으로 처리하지 않은 통과조 162지점도 원문을 보존했다. [구형 표기](root_audit/legacy_compact_notations.csv), [파싱 보류](root_audit/unparsed_notations.csv).
- 통과조의 괄호 내부 순서를 개별 착순으로 만들지 않고, 무리의 구성원 수로 가능한 순위 범위만 계산했다. 그 범위와 API4 말별 순위가 어긋나는 후보는 27경주·31지점·105말/지점 관측이다. API4 순위·통과조·지점 대응 중 어느 쪽이 잘못됐는지는 추가 원문 대조가 필요하다. [전체 검토 목록](root_audit/api4_group_order_disagreements.csv).

예: 2026-08-28 7R 4C에서 6번(3108052)의 API4 순위는 1이지만 API303과 API6의 동일 통과조 `3,(9,1),(4,2),5≡(6,8),7,10`에서는 6번이 뒤쪽 무리에 있다. 숫자만 바꿔 맞추지 않는다.

## 입력 해석 제한

- 말별 구간시간·통과착순은 API4, 경주별 통과조는 API303, 경주 전체 구간흐름은 API6으로 구분한다. 경주 전체 시간은 개별 말 시간으로 넣지 않는다.
- S1F→1C→2C→3C→4C라는 표시 열 순서를 출발 이후 측정 순서로 가정하지 않는다. S1F보다 작은 2C 시간 666관측은 지점·거리 계약 확인 전 오류로 분류하지 않았다. 거리별 미사용 지점을 보간하지 않는다.
- 초기 원문 감사에서는 DB를 변경하지 않았다. 사용자 승인 후 홈페이지 기준 후속 적재는 아래 절과 별도 application manifest를 따른다. 사후 구간·통과순위·통과조는 같은 경주의 경주 전 피처로 사용하지 않는다.
- 원문 동등성·내부 산술 통과와 실제 기록의 정확성·모든 지점의 완전성은 별도 판정이다. 시간 4건·순위 불일치 후보·2002년 지점 대응은 원문 확인 대상이다.

## 재현

```sh
.venv/bin/python jeju/research/20261002_section_passing_audit/root_audit/audit_corner.py
.venv/bin/python jeju/research/20261002_section_passing_audit/root_audit/audit_horse_independent.py
.venv/bin/python jeju/research/20261002_section_passing_audit/build_report.py
```

[전체 요약](summary.json), [통과조·API6 검증](root_audit/summary.json), [말별 독립 검증](root_audit/horse_independent_summary.json). GPT-6 Luna xhigh의 [일차 점검 결과](raw_audit/worker_received_report.json)는 root가 같은 분모로 독립 대조했다. [시간 4건의 공식 응답 행 대조](root_audit/time_flags_original_page_verification.json)와 [API4 말·경주·마번 연결 대조](root_audit/api4_key_verification.json)도 모두 통과했다.

## 홈페이지 기준 후속 적재 — 사용자 승인 2026-10-02

로컬 DB `jeju/data/jeju_native_core.sqlite3`에 `race_section_time_reviews` 4행을 적재했다. API 원문 JSON·해시·원천 파일은 보존하며 홈페이지 정정값과 미해결 상태를 별도로 저장한다. 위 원문 감사 표와 `time_review_cases.csv`는 API 원값의 감사 목록이다.

| 날짜·경주·말 | 필드 | API 원값(초) | 홈페이지 값(초) | 사후 분석용 값(초) |
|---|---|---:|---:|---:|
| 2024-03-02 3R 절대권력 | S1F | 120 | 20.0 | 20.0 |
| 2025-10-17 7R 어정적기 | S1F | 77.8 | 17.8 | 17.8 |
| 2026-01-17 5R 광해청명 | G1F | 77.2 | 77.2 (`1:17.2`) | NULL — 미해결 이상값 |
| 2026-03-06 8R 시긴트 | G1F | 76 | 16.0 | 16.0 |

- 말별 구간시간 사후 분석은 `jeju_race_postrace_sections_2026`를 사용한다. 기존 최신 이름·말 ID 연결·2026년 고정 나이를 유지하며 92,513행·동일한 출전키를 제공한다. `s1f_time_seconds`, `c1_time_seconds`~`c4_time_seconds`, `g3f_time_seconds`, `g1f_time_seconds`와 각 `*_time_status`를 함께 조회한다.
- `jeju_race_section_time_values`는 출전·필드별 원값·JSON 타입·선택값·검토 상태·홈페이지 URL·근거 파일 SHA·API 원천 연결을 제공한다. `jeju_race_section_times`는 출전키당 한 행으로 묶은 조회다. 세 필드 상태는 `website_corrected`, 광해청명 G1F는 `unresolved_official_website_anomaly`다. 광해청명의 다른 구간·완주시간과 경주 행은 유지한다.
- 광해청명 G1F 77.2초는 원관측으로만 보존하고 분석용 값은 NULL이다. 17.2초로 추정하거나 0으로 대체하지 않는다. API 양수값 중 홈페이지 대조하지 않은 필드는 `api_positive_unreviewed`이며 홈페이지 검증 완료를 뜻하지 않는다. 0·비수치·미제공 시간은 NULL로 제공한다.
- `section_time_website_correction_count`와 `section_time_review_required_count`로 출전행별 정정·미해결 필드 수를 표시한다. 정정 당시 API payload SHA가 바뀌면 해당 값은 NULL·`api_source_changed_since_review`로 차단한다.
- 기존 `jeju_race_analysis_2026` 정의와 기존 모델 입력은 변경하지 않았다. 새 사후 조회를 기존 모델에 자동 채택하지 않으며 같은 경주의 사전 예측 입력으로 사용하지 않는다. 출처 변환·단위·거리 및 통과조의 다른 미해결 사항은 기존 감사 제한을 유지한다.

### 재구축·재실행 및 검증

스키마에 새 테이블·조회 정의를 포함했다. 원문 DB를 재구축한 뒤 아래 수집기 적용 명령으로 네 검토행을 다시 연결한다. 미적용 상태에서도 정확히 일치하는 알려진 네 날짜·경주·마번·말 ID·필드는 `website_review_not_applied`·NULL로 차단하여 이상 API 값으로 자동 되돌아가지 않는다. 재실행은 원문 행의 식별·값·해시를 다시 확인하며 동일 검토행은 추가하지 않는다.

```sh
.venv/bin/python jeju/scripts/apply_section_time_website_review.py
.venv/bin/python jeju/scripts/apply_section_time_website_review.py --apply
```

적용 전후 출전키·행 수, 네 필드의 값·상태, API 전체 record 식별·payload hash 지문 불변, 외래키와 기존 분석 뷰 정의 불변을 검증했다. [실제 적재·검증 내역](website_time_check/application_manifest.json), [적용 전 상태와 되돌리기 범위](website_time_check/before_application.json), [스키마 migration](../../data/schema/migrations/20261002_add_section_time_website_review.sql), [재구축·원천 변경 차단 검증](website_time_check/guard_verification.json).

## 남은 항목 공식 원문 후속 검증

[92경주 홈페이지·API 재조회·27경주 TXT 보완 보고서](../20261002_section_remaining_review/README.md)를 함께 읽는다. 위 27경주·105관측은 최초 감사 후보다. 후속 대조에서 6경주·26관측은 API303 지점 대응 차이, 2경주·9관측은 홈페이지 순위 차이로 설명했고 19경주·70관측·20지점은 홈페이지와 TXT에서도 내부 충돌이 남는다. 원인 분류는 DB 정정 완료를 뜻하지 않는다.

전체 출전표에서 홈페이지와 다른 양수 순위 14개를 확인했으며 최신 API4와 TXT에는 기존 값이 남아 있다. 사용자 승인에 따라 2026-10-03 순위 14개를 홈페이지 값으로 DB에 반영했다. 선택된 순위·시간 조회는 `jeju_race_postrace_sections_reviewed_2026`이며 [적용·독립 검증 보고서](../20261002_section_order_website_load/README.md)를 읽는다. 광해청명 2026-01-17 5R G1F 시간은 NULL을 유지한다. 2002년 확대 대조 18경주·108지점은 API6가 홈페이지와 모두 일치하고 API303의 기존 필드 대응은 78지점이 다르다. API6 누락 6경주와 말별 결측 25행·1행도 공식 보완 원문으로 채울 수 없었다. `·` 뒤 166관측은 주행중지 164개·실격 2개로 확인됐다. 최초 후속 점검은 DB 변경을 실행하지 않았으며 실제 정정 여부는 위 적용 상태를 따른다.

## 2026-10-03 미해결 품질 조회 보류 반영

[19경주 최신 재검토·DB 보류 반영](../20261003_unresolved_section_review/README.md)에서 실제 순위 정답은 확정하지 못했고, 충돌 순위 70개·통과조 20지점을 NULL·보류 상태로 제공했다. 현재 새 사후 분석은 `jeju_race_postrace_sections_quality_2026`를 사용한다. 기존 시간·순위 정정과 광해청명 G1F 시간 NULL은 유지되며, 이 보고서의 최초 원문 감사 관측은 보존한다. 기존 모델 입력 자동 채택은 아니다.
