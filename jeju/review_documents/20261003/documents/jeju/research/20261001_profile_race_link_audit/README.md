# 마필 프로필 DB 저장 및 경주 연결 감사 — 2026-10-01

`jeju/data/jeju_native_core.sqlite3`를 읽기 전용으로 전수 대조했다. DB·원문·정규화 관측은 수정하지 않았다. 재현 코드는 `audit_profile_race_link.py`, 기계 판독 결과는 [summary.json](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_profile_race_link_audit/summary.json>)에 있다.

## 저장 및 공식 ID 연결

| 점검 | 결과 |
| --- | ---: |
| DB 최신 프로필 | 4,617두 |
| 프로필별 API 원문 항목 | 모두 218개 |
| 제주마 경주 후보 | 9,494경주·92,513출전행·4,006두 |
| 프로필에 연결된 후보 출전행 | 92,513 / 92,513 |
| 연결 누락·원문/정규화 말 ID 차이 | 각각 0 |
| 심사 이력에 연결된 프로필 | 4,617 / 4,617두 |
| 심사만 있고 경주결과가 없는 보조 프로필 | 611두 |

218개 항목은 DB `api_records.payload_json`에 객체 그대로 보존됐으며 `horse_profile_latest.payload_json`에서 조회할 수 있다. 식별·조회일·기본 특성은 `horse_profile_observations`에도 정규화했다. 말별 값이 빈 문자열·`-`·0인 항목도 원문 그대로 보존한 것이며, 218개 모두 실질 값이 채워졌다는 뜻은 아니다.

전체 4,617개 DB 프로필을 응답 파일과 다시 비교하는 `verify_imported_profiles.py`도 재실행했다. 전체 JSON 값·타입, 원문 및 item SHA, 공식 말 ID, 조회시각, 출처, FK가 모두 일치했다. [원문 대조 검증](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_api42_collection_verification/db_profile_verification.json>)

비교 범위는 제주마 후보 출전행이다. 전체 제주 경마장 API에는 다른 마종 결과도 포함되므로 그 전체를 제주마 프로필 대상으로 해석하지 않는다. 후보 행에는 취소·비완주 행이 포함된다. 후보 최초 날짜 2002-07-06과 기존 완주 결과의 시작일은 다를 수 있다.

## 경주 당시 속성과 현재 프로필 비교

2026-10-01 후속 공식 원문 대조는 [이름·성별·마령 원인 재검토](<../20261001_profile_discrepancy_causes/README.md>)에 기록했다. 당시 출전표는 동방라오, 현재 프로필은 무명전설로 명칭 변화를 확인했다. 토종등극은 공식 성적표에도 수로 표기되어 원천 간 모순을 확인했다. 나이 차이 992행은 7월 1일 증가 패턴과 일치하고 27행·2두는 출생연도 충돌이 남는다. 아래 수치는 최초 감사 결과이며 최신 판정은 후속 보고서를 따른다.

| 항목 | 비교 결과 |
| --- | --- |
| 마명 | 92,512행 일치, 1행 미해결 차이 |
| 성별 | 85,878행 일치, 과거 수→현재 거 6,634행·493두, 수→암 차이 1행 |
| 나이 | 경주 연도−현재 프로필 출생연도 계산과 91,494행 일치, 1,019행·86두 차이 |

이름 유사성으로 연결하지 않고 공식 말 ID를 사용했다. 현재 관계자·현재 나이·누적 성적을 과거 경주 값과 동일하다고 가정하지 않았다. 경주결과 API에는 생년월일 필드가 없어 출생일 직접 일치 검사는 불가능하며, 나이는 별도의 계산 일관성 검사다.

### 미해결 마명 1행

- 2026-01-16 제주 1경주 3번, ID `3107458`.
- API4_3 경주결과: **동방라오**, `ord=94`, `rcTime=0`.
- API42 프로필: **무명전설**, 변경 전 마명·마명변경일 모두 `-`.
- API20 심사 2025-10-30·2025-11-06에도 **무명전설**로 관측됐다.
- 공식 ID는 일치하나 API4_3의 마명 원천값이 다른 이유는 미확정이다. 비완주 결과행이며 이름을 자동으로 덮어쓰지 않았다. [원문 차이 행](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_profile_race_link_audit/name_differences.jsonl>)

### 미해결 성별 1행

- 2002-12-14 제주 3경주 2번, ID `3005897`, **토종등극**.
- API4_3 경주결과: **수**, 나이 8, 착순 10, 완주시간 72초.
- API20 심사 2002-11-22: **암**, 나이 8. API42 프로필도 **암**.
- API4_3 성별 원천값의 차이 사유는 미확정이다. [성별 차이 전체 목록](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_profile_race_link_audit/sex_differences.jsonl>)의 `other_sex_difference`로 분리했다.

과거 수→현재 거의 6,634행은 시간에 따른 거세 변화 가능성이 있으므로 위 수→암 차이와 구분한다. 모든 행의 실제 거세 시점을 확인한 것은 아니다.

### 과거 나이 계산 차이

2007~2014년의 1,019행·86두에서 API 경주 나이가 `경주 연도−프로필 출생연도`보다 모두 1세 작다. 992행은 하반기 출생·상반기 경주 패턴이고, 나머지 27행은 `3009880` 강줄기·`3014439` 득점기록이다. 당시 공식 연령 산정 규칙은 확인하지 못했으므로 일괄 오류 판정·생년월일 수정·나이 대체를 하지 않았다. [차이 전체 목록](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_profile_race_link_audit/age_from_profile_birth_year_differences.jsonl>), [시점 패턴 검토](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_profile_race_link_audit/age_pattern_review.json>)

## 결론

프로필 저장과 공식 ID 연결은 전부 완료됐다. 경주 당시 모든 속성의 동일성까지 확정된 상태는 아니며, 마명 1행·성별 1행 및 과거 나이 산정 차이의 원인 검증이 남아 있다. 마종의 과거 유효시점 확정은 이번 ID 연결 감사와 별도의 판정이다.

GPT-6 Luna xhigh 서브에이전트도 읽기 전용으로 공식 ID 연결 누락 0건과 두 원천 속성 차이를 독립 재확인했다. `3005967` 표본에서는 2003-03~2005-07의 수 표기와 2005-11 이후의 거 표기가 같은 ID로 이어지는 사건일 관측을 확인했다. [독립 검토 원장](</Users/kimyongjin/Desktop/horse_racing/jeju/research/20261001_profile_race_link_audit/agent_review.json>)
