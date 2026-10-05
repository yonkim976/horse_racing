# 제주 미해결 통과착순·통과조 19경주 재검토와 보류 반영

2026-10-03 한국 시간 기준 재검토와 DB 보류 반영을 완료했다. **19경주의 실제 구간 순위 정답은 여전히 미확정**이다. 공식 자료끼리 같은 지점에서 충돌하므로 추정 순위로 정정하지 않고, 원문을 보존한 별도 품질 조회에서 충돌 필드를 NULL로 제공한다.

## 원천 재확인 결과

- 한국마사회 **경주기록 정보 API** `API4_3/raceResult_3`를 19개 날짜에 다시 호출했다. HTTP 200·날짜별 전수 응답·공식 말 ID와 마번을 확인했고, 문제 순위 70개는 기존 API 값과 모두 같았다. 기본 환경의 연결 실패는 별도 실패 원장에 보존했고 네트워크 재시도로 19개 날짜를 완료했다.
- 공식 제주 경주성적 홈페이지 19페이지를 새로 받았다. 날짜·경주·제주 식별과 전체 184개 출전마 ID를 확인했으며, 70개 개별 순위와 20개 통과조는 기존 화면과 같았다. 원응답 19페이지의 SHA도 이전 수집본과 같았다.
- 보유 **경마코너별통과순위·주로빠르기 API** `API303/corner_rank` 및 **경주 구간별 성적 정보 API** `API6_1/raceDetailSectionRecord_1`의 해당 20개 통과조도 홈페이지와 일치한다. 이 두 API를 이번에 새로 호출한 것은 아니다. 기존 공식 TXT 보완 원문 역시 이전 대조에서 같은 충돌을 보였다.
- 공식 표기 정의에 따라 괄호 안은 내측부터 표시하는 마군이며 정확한 개별 순위가 아니다. 마군 인원으로 계산한 가능한 순위 범위를 벗어나는 70개 충돌은 재현됐다. 전체 출전표를 다시 검사했을 때 기존 70개 밖의 추가 범위 이탈은 없었다. 칸 교환·시간으로 순위를 추정해 정정하지 않았다. [KRA 공식 표기 해설](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=3).
- 홈페이지의 심판 기록은 17경주에 있었고 2016-09-23·2017-07-08은 공란이다. 제공된 17개 기록과 추가 심판사항을 읽었으나 구간 순위 정정값이나 계측 고장을 명시한 내용은 찾지 못했다.

[최신 API 응답 원장](api4_recheck/20261002T155808.237358Z/manifest.json), [최초 연결 실패](api4_recheck/20261002T155724.924989Z/manifest.json), [최신 홈페이지 원장](official_recheck/manifest.json), [root 독립 원문 검증](root_fresh_evidence_check.json), [독립 의미·지점 검토](semantic_review/semantic_audit_summary.json).

[대상 19경주 목록](../20261002_section_remaining_review/remaining_race_list.csv), [원래 충돌 70개](../20261002_section_remaining_review/remaining_website_internal_order_conflicts.json).

## 실제 DB 반영

대상 DB는 `jeju/data/jeju_native_core.sqlite3`다. `section_internal_conflict_reviews`에 **개별 통과착순 70행·통과조 20행, 총 90개 검토행**을 저장했다. 원 API 필드·값·payload SHA, 공식 홈페이지 URL과 증거 SHA를 함께 연결했다.

| 구간 | 개별 통과착순 보류 필드 | 통과조 보류 지점 |
|---|---:|---:|
| S1F | 14 | 6 |
| 3C | 5 | 2 |
| 4C | 28 | 6 |
| G1F | 23 | 6 |
| 합계 | 70 | 20 |

새 사후 품질 조회는 **`jeju_race_postrace_sections_quality_2026`**이며 92,513출전행·출전키당 한 행이다.

- `s1f_order`, `c1_order`~`c4_order`, `g1f_order`: 충돌한 70개만 NULL·`unresolved_official_internal_conflict`다. 다른 순위와 기존 홈페이지 정정 14개는 유지한다.
- `s1f_group`, `c1_group`~`c4_group`, `g1f_group`: 충돌 20지점을 NULL·같은 보류 상태로 제공한다. 20지점은 전체 출전표에 적용되므로 출전행별 조회에서는 194개 말·지점 관측에 해당한다. 원문 통과조는 `_raw` 필드와 별도 출처 조회에 남아 있다.
- `section_internal_conflict_order_count`와 `section_internal_conflict_group_count`는 해당 출전행의 보류 필드 수다. 전체 DB의 모든 오류를 집계하는 수치가 아니다.
- 필드별 출처·이전 선택값·품질 선택값은 `jeju_race_section_order_quality_values`, 그룹 출처·원문·선택값은 `jeju_race_section_group_quality_values`에서 추적한다.
- 알려진 보류 검토행이 없으면 NULL·`internal_conflict_review_not_applied`, 검토 후 원천 payload SHA가 달라지면 NULL·`api_source_changed_since_conflict_review`를 제공한다. 자동으로 정상 판정하거나 원값을 복원하지 않는다.

기존 `jeju_race_postrace_sections_reviewed_2026` 등 기존 조회 정의, 원 API JSON·출전행, 최신 이름·2026년 나이, 최종 착순·완주시간과 다른 구간시간은 보존했다. **광해청명 2026-01-17 5R G1F 시간 NULL도 유지**했다. 기존 모델 입력과 저장 피처를 자동으로 다시 만들거나 채택하지 않았다.

## 특수결과와 시간 검토 맥락

2025-11-01 제주 5R 2번 **완벽세대(3018812)**는 공식 심판 기록상 출발 직후 기수가 낙마하고 말이 방마돼 주행중지 처리됐다. 개별 4C·G1F 순위는 1이지만 통과조에서는 맨 뒤에 표시된다. 이 말을 양쪽 비교에서 제외하고 남은 개별 순위를 비교용으로 압축하면 두 지점의 9두·18개 비교에서 범위 이탈이 모두 사라진다. 기수 없는 말의 개별 계측과 유효 출전마 비교 모집단 차이가 해당 경주의 충돌을 설명할 가능성이 있다. 이것은 [특수결과 비교 진단](root_special_outcome_check.json)이며 실제 공식 순위 정정이나 API 계측 정책 확정은 아니다. 원문·보류 선택값을 유지한다.

2026-08-28 제주 7R의 4C는 순위 외에 시간에도 검토 맥락이 있다. 6·8번은 61.2초, 7번 61.5초, 10번 61.8초로 표시되지만 통과조에서 앞에 있는 3번은 69.3초다. 개별 시간 정렬과 통과조가 서로 다른 순서를 가리킨다. 해당 시간들은 홈페이지와 API가 같아 올바른 대체 시간은 확보하지 못했다. 이들을 정확한 계측으로 확인했다고 설명하거나 70.2초 등으로 추정 정정하지 않는다.

시간을 통한 순위 진단은 반올림·동시 측정·미제공과 G1F 막판시간의 의미를 확인해야 한다. 시간 기반 순위가 통과조와 다르다는 이유만으로 시간 오류를 확정하지 않는다. 충돌한 지점의 시간·순위·그룹을 혼합하는 상대속도·순위 변화 등 파생값은 추가 검토 없이 확정 피처로 사용하지 않는다. 나머지 `api_positive_unreviewed`·`api_group_unreviewed`도 홈페이지 검증 완료라는 뜻이 아니다.

## 검증과 재실행

GPT-6 Luna xhigh 작업자들이 공식 재조회와 의미·지점 검토를 분담했고, root가 필드 대응 오류를 검증·수정한 뒤 원응답을 독립 검사하고 실제 DB 적용·전수 검증을 진행했다.

- 전체 92,513행·고유 출전키 92,513개 유지.
- 충돌 순위 70개·통과조 20지점만 보류 선택값 NULL.
- 기존 홈페이지 순위 정정 14개, 모든 다른 순위·구간시간과 광해청명 G1F NULL 유지.
- 원 API 전체 record 지문·기존 스키마 정의·시간 및 순위 검토행 불변.
- 최신 이름·2026년 고정 나이·최종 착순·완주시간 보존, 제외 말 작은곰 재편입 0행, 새 검토 테이블 외래키 위반 0건.
- 메모리 DB 1,560출전행에서 검토행 미적용·원천 SHA 변경 차단과 기존 정정 보존 검증.

[실제 적용 내역](application_receipt.json), [독립 전수 검증](root_independent_verification.json), [차단 규칙 검증](guard_verification.json), [적용 전 상태](root_before_review.json), [스키마 migration](../../data/schema/migrations/20261003_add_section_internal_conflict_quality.sql).

`build_quality_review.py` 기본 실행은 근거·연결과 migration을 확인하며 DB를 수정하지 않는다. `--apply`는 이 고정 검토 시점의 원장 지문과 공식 근거가 일치하는 경우에만 검토행을 연결한다. 원장 수집본이나 공식 근거가 달라지면 재검토 후 별도 버전이 필요하다. migration의 알려진 범위 차단은 검토행 미적용 상태에서도 유지된다.

이번 작업으로 **미확정 값의 보류 처리까지 완료**했다. 실제 순위·시간 정답을 확정하려면 명시적인 공식 정정 자료 또는 계측 자료가 추가로 필요하다. 같은 경주의 사후 기록을 그 경주의 사전 예측 입력으로 사용하지 않는다.
