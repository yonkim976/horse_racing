# 제주 홈페이지 통과착순 정정과 상세 구간 재확인

홈페이지는 2026년 10월 2일 재조회했고, 한국 시간 10월 3일에 제주 원장 DB `jeju/data/jeju_native_core.sqlite3`의 통과착순 14개를 홈페이지 값으로 적용했다. 광해청명 2026-01-17 제주 5R의 G1F 시간은 기존 분석용 NULL을 유지했다. 상세 구간 누락 6경주는 홈페이지에서도 계속 공란이므로 보충값을 만들지 않았다.

## 실제 반영한 내용

| 대상 | 내용 |
|---|---|
| 2025-10-17 제주 7R | S1F 통과착순 7개·G1F 통과착순 3개 정정 |
| 2026-03-06 제주 8R | G1F 통과착순 4개 정정 |
| 2026-01-17 제주 5R 8번 광해청명 3016494 | G1F 시간 NULL·`unresolved_official_website_anomaly` 유지. 원문 77.2초 보존 |

정정한 값은 최종 결승 착순이 아니라 **구간 통과착순**이다. 새 조회 `jeju_race_postrace_sections_reviewed_2026`는 기존 최신 이름·공식 말 ID·2026년 고정 나이와 시간 정정값에 홈페이지 기준 통과착순을 함께 제공한다. 전체 92,513행이고 출전키당 한 행이다.

API JSON·원문 파일을 직접 덮어쓰지 않았다. 별도 `race_section_order_reviews` 14행에 원 API 순위, 홈페이지 순위, 선택값, 말·출전 연결키, API payload SHA, 홈페이지 URL과 증거 SHA를 저장했다. [정정값 전체 CSV](corrected_orders.csv), [실제 반영 내역](application_manifest.json).

## 조회와 재검토 기준

2026-10-03 후속 미해결 19경주 재검토에서 순위 70개·통과조 20지점을 보류 처리했다. **현재 새 사후 분석 조회는 `jeju_race_postrace_sections_quality_2026`**이며 아래 14개 정정도 유지한다. [후속 보류 반영·검증](../20261003_unresolved_section_review/README.md). 이 보고서의 `reviewed_2026` 조회는 그 기반으로 보존한다.

- 전체 사후 구간 조회: `jeju_race_postrace_sections_reviewed_2026`.
- 선택된 순위: `s1f_order`, `c1_order`~`c4_order`, `g1f_order`; 각 `*_order_status`와 함께 사용한다. 이번 14필드의 상태는 `website_corrected`다.
- 필드별 출처 조회: `jeju_race_section_order_values`. 출전당 선택값 묶음은 `jeju_race_section_orders`다. 원문 API 순위와 정정값을 구분한다.
- 알려진 14개 검토행이 DB 재구축 후 미적용이면 NULL·`website_review_not_applied`, 검토 당시와 API payload SHA가 다르면 NULL·`api_source_changed_since_review`로 제공한다. 원문 0·99·공란·비수치·비정수는 실제 순위로 제공하지 않는다.
- 다른 양수 API 필드의 `api_positive_unreviewed`는 홈페이지 검증 완료를 뜻하지 않는다. 기존 미확정 19경주의 통과조·순위 충돌을 이번 작업으로 정정하지 않았다. `section_order_review_required_count`는 검토행 미적용·원천 변경을 세며 모든 의미 오류를 집계하는 지표가 아니다.
- 기존 `jeju_race_analysis_2026`, 시간 검토 조회와 운영 모델 입력은 보존했다. 정정된 자료를 새 분석에 사용할 때 원문 `_raw` 순위로 정정을 우회하지 않는다. 같은 경주의 사후 기록을 경주 전 피처로 사용하지 않는다. 홈페이지 재조회일은 과거 최초 공개 시각을 입증하지 않는다.

## 상세 구간 누락 홈페이지 재확인

| 경주 | 펄롱타임 | 통과거리 | 통과타임 |
|---|---|---|---|
| 2025-01-10 제주 1R | 공란 | 공란 | 공란 |
| 2025-05-16 제주 8R | 공란 | 공란 | 공란 |
| 2025-05-23 제주 3R | 공란 | 공란 | 공란 |
| 2025-06-27 제주 4R | 공란 | 공란 | 공란 |
| 2025-07-04 제주 5R | 공란 | 공란 | 공란 |
| 2026-09-11 제주 5R | 공란 | 공란 | 공란 |

각 공식 페이지를 새 GET으로 받아 HTTP 200·날짜·경주번호·제주 식별·원문 해시를 확인했다. 위 표는 경주 전체 상세 구간표다. 별도로 존재하는 말별 API4 구간시간·통과착순이나 API303 통과조까지 없다는 뜻은 아니다. 이전 API6 재조회에서도 경주 행이 없고 TXT에서도 상세 구간·누적시간을 보충할 수 없었다. 3F·4F 합계로 누락 상세 시간을 복원하지 않는다.

[새 홈페이지 대조](fresh_website/README.md), [8페이지 원문 원장](fresh_website/evidence.json), [root 독립 홈페이지 검증](root_fresh_website_verification.json), [이전 API·TXT 결측 확인](../20261002_section_remaining_review/coverage_review/README.md).

## 적용과 검증

GPT-6 Luna xhigh가 SQL과 홈페이지 재확인을 분담했다. root가 실제 트랜잭션 적용과 독립 검증을 진행했다.

- 정정 대상 14필드와 말 ID·마번·출전 연결키 일치.
- 두 경주 전체 20출전행의 6지점 순위 120개가 홈페이지와 일치.
- 전체 조회행 92,513개·고유 출전키 92,513개 유지.
- API 전체 record 지문과 기존 분석·시간 조회 정의, 기존 시간 검토행 4개 유지.
- 광해청명 G1F NULL 유지, 작은곰 3005648 재편입 0행, 정정 테이블 외래키 위반 0건.
- 별도 메모리 DB에서 미적용 14필드 차단·원천 SHA 변경 차단·0/99/NULL/문자열/비정수 처리 검증.

[독립 검증 결과](root_independent_verification.json), [재구축·원천 변경 차단 검증](guard_verification.json), [적용 전 상태](root_before_application.json), [SQL migration](../../data/schema/migrations/20261002_add_section_order_website_review.sql).

## DB 재구축 후 재적용

root가 [재적용 로더](../../scripts/apply_section_order_website_review.py)를 작성했다. 기본 실행은 원장을 메모리 DB로 복사하여 검증하며 실제 DB를 수정하지 않는다. `--apply`는 고정된 14개 홈페이지 검토행을 트랜잭션으로 연결한다. 동일한 검토행은 추가하지 않고, 근거·API 값·조회 정의가 달라지면 중단한다. 기존 시간 정정 4행을 먼저 적용한 DB가 전제다.

```sh
.venv/bin/python jeju/scripts/apply_section_order_website_review.py
.venv/bin/python jeju/scripts/apply_section_order_website_review.py --apply
```

실제 적용 후 메모리 복사본에서 14개 기존 검토행 재실행·선택값·행 수·시간 NULL·원문 지문 보존을 확인했다. [로더 검증 결과](loader_verification.json). 원래 적용 내역과 검증 산출물은 재실행으로 덮어쓰지 않는다. 홈페이지 근거를 새로 수집하거나 값이 바뀌면 별도 검토·근거 버전이 필요하다.
