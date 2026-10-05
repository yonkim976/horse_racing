# 주행심사 말 신원 보완 원장

마사회 API20_1 주행심사 참가 행 61,777개 중 104개는 원문 JSON에 `hrNo`와
`hrName` 키가 모두 없다. 원천 행은 변경하지 않고, 2026-09-30에 보관된
`dacom23` 주행심사 성적표와 운영 SQLite를 교차 검증한 연결 99개와
사용자가 확정한 연결 5개를 별도 원장으로 보관한다. 미연결 행은 0개다.

| 산출물 | 의미 |
|---|---|
| [`identity_links.csv`](identity_links.csv) | 연결 104행. 99행은 운영 DB·RPT 대조, 5행은 사용자 확정과 RPT·말 프로필 대조 |
| [`user_confirmations.csv`](user_confirmations.csv) | 사용자가 확정한 5행의 공식 ID·마명·판정 근거 |
| [`pending_review.csv`](pending_review.csv) | 현재 미연결 행 0개(헤더만 보존) |
| [`validation.json`](validation.json) | 건수와 차이 요약 |

## 연결 기준

### 운영 DB·RPT 대조 99행

1. API 쪽 `source_meet_query`, `trial_date`, `trial_no`, `api_chulNo`와
   `dacom23` 성적표 및 운영 DB의 경마장·심사일·회차·출전번호가 각각
   유일하게 일치한다. 성적표의 말 이름도 운영 DB·말 기준정보와 일치한다.
2. 운영 DB의 말에 공식 KRA ID와 이름이 있다.
3. 비교 가능한 기록·착순·기수 ID/이름·조교사 ID/이름·마체중 사이에
   설명되지 않는 충돌이 없고, 최소 두 항목이 일치한다. 완주 기록이 있는
   88행의 주행시간은 모두 밀리초까지 일치한다.
4. 조교사 이름 불일치 5행은 API `trNo=070167`, API 이름 `이신우`가
   운영 DB의 기준 조교사 ID·이름과 일치한다. 운영 심사 결과의 이름 원문
   `이신영`만 다르므로 이 차이를 원장에 명시하고 연결했다.

운영 DB는 교차 검증 원천이지 API 원문을 대체하는 정답이 아니다. 성적표
원문 경로와 SHA-256도 연결별로 보관한다. 연결은
`participant_row_id`별로 기록하고, 새 코어 DB에서는 원문 `horse_id`와
`horse_name`을 그대로 둔 채 `trial_participants_resolved` 뷰에
`resolved_horse_id`, `resolved_horse_name`, `horse_identity_resolution`을 제공한다.
`unresolved_trial_participants` 뷰는 현재 0행이다. 연결 방식은
`horse_identity_resolution`에서 `crosschecked_link`(99행)와
`user_confirmed_link`(5행)로 구분한다.

### 사용자 확정 5행

사용자는 해피머니·지니블레이드·스티캣의 부산 주행심사 기록이 해당 서울마의
이력임을 확정했다. 각 행의 RPT는 같은 출전번호에 해당 말 이름을 기록하며,
프로필의 공식 ID·이름·성별·출생연도·서울 소속이 RPT와 맞는다. 코어의
정식 경주 결과에 세 말의 출전 기록은 없다. 운영 DB에는 이 5행의 동일
출전번호 기록이 없어 `user_confirmed_link`로 출처를 분리한다.
프로필의 서울 소속은 현재 보관된 값이다. 2015~2016년 당시의 등록 소속이나
이동 내역을 입증하는 날짜별 자료는 확인되지 않아 소속 이력으로 추정하지 않는다.

| 심사일 | 영남 회차·번호 | RPT·공식 마명 | 확정 ID | API 결과 |
|---|---|---|---|---|
| 2015-10-03 | 4회 2번 | 해피머니 | `0030571` | 불합격, 67.6초 |
| 2015-10-17 | 2회 7번 | 해피머니 | `0030571` | 불합격, 기록 0 |
| 2015-10-24 | 3회 3번 | 해피머니 | `0030571` | 불합격, 66.8초 |
| 2016-04-16 | 1회 2번 | 지니블레이드 | `0036390` | 출주취소 |
| 2016-09-24 | 4회 1번 | 스티캣 | `0032069` | 불합격, 67.4초 |

사용자가 쓴 `스티켓`은 RPT와 말 프로필의 `스티캣` 표기와 다르다.
공식 ID `0032069`의 프로필·RPT 표기인 `스티캣`으로 연결하고 사용자
표기도 [`user_confirmations.csv`](user_confirmations.csv)에 남겼다.

## 구포파크 이력 검증

공식 말 ID `0030195`의 API 기록은 영남 2014-01-25 1회 5번 심사
(66.1초), 부산경남 2014-02-21~04-18 정식 경주 3회, 서울
2015-05-22 3회 8번 심사(64.7초, 원문 ID·이름 누락), 서울
2015-06-06~11-21 정식 경주 7회 순서다. 서울 심사 행은 운영 DB의
구포파크 기록과 기록·착순·기수·조교사·마체중이 일치한다.

재생성: 저장소 루트에서
`.venv/bin/python thoroughbred/research/20260930_trial_horse_identity_v1/build_links.py`.
코어 DB 재생성은
`.venv/bin/python thoroughbred/research/20260929_core_api_db_v1/build_core_db.py`.
