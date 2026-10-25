# 운영 DB 말별 심판 문구 연결 — 2026-10-17

> **2026-10-20 후속 운영 보완:** 아래 최초 반영 당시 미연결 928문구의 원인인 837개 특수 결과 출전행을 공식 원문으로 검증해 추가하고 연결을 완료했다. 현재 48,130문구 전부 출전행 연결, 신원/원문 해시 불일치 0이다. 기존 연구 원천·당시 실행 파일과 원문 문구는 바꾸지 않았다. 상세 상태·한계·근거는 [말별 심판 운영 문서](../../../docs/STEWARD_HORSE_AUTOMATION_2026-10-17.md)의 10/20 절을 따른다. 아래 928건 미연결 표기는 10/17 당시의 기록이다.

사용자가 기존 검증분의 운영 DB 연결을 요청하여 `horse-racing-prod`
(`xkykmhhkjtosptoibduo`)의 `public.horse_steward_phrases`에 반영했다.

## 반영 결과

- 문구 48,130건 / 공식 마번 9,196두 / 경주 12,758개.
- 문구의 실제 경주일 범위: 2017-09-22 ~ 2026-09-13.
- 홈페이지 원문 관측 73,801건의 URL, HTML SHA256, 원문 파일, 관측 시각,
  출마표 키, 문구의 문자 위치를 `provenance_json`에 보존했다.
- 48,130건 모두 `horses.id`와 `races.id` 외래키로 연결했다.
- 47,202건은 같은 경주의 공식 마번과 출전번호까지 일치하여 `race_entry_id`로 연결했다.
- 928건은 해당 말의 출전 행이 없어 `race_entry_id=NULL`,
  `entry_link_status='entry_missing'`으로 저장했다. 출전취소 여부를 임의로 판정하거나
  다른 말의 출전 행으로 연결하지 않았다. 말·경주 연결은 유지된다.
- 운영 DB에 원래 경주 단위 리포트가 있는 9,929건은 `race_steward_report_id`도 연결했다.
- 원문은 공백·개행까지 그대로 유지했다. 상황 분류는 하지 않았다.

연구 원천은 `../20261013_steward_horse_phrases_v1/outputs/horse_steward_phrases.duckdb`다.
SHA256: `396d7c3fb3ef8c272e154e18ee439c8a9acb8e0001e0e2fa339d2517dfb1a83a`.
이는 선택한 홈페이지 출마표의 최근 1년 이력을 모은 확보분이며 해당 기간 모든 경주의 완전한 수집본은 아니다.
제주 문구는 이번 반영분에 포함되지 않는다.

## 반영 및 검증 기록

1. `preflight.py`: 운영 말/경주/출전 행과 사전 대조. 임시 테이블만 사용하고 롤백.
2. Supabase migration `20261017100757_add_horse_steward_phrases.sql` 적용.
3. `publish.py --apply`: 원천 SHA256, 문구 48,130건과 모든 관측의 원문 구간/말/경주를
   검사하고 운영 식별자를 다시 조회하여 한 트랜잭션으로 추가.
4. 같은 키의 기존 내용은 덮어쓰지 않으며 전체 필드를 대조한다. 다른 내용이면 롤백.
5. 커밋 후 독립된 Supabase 연결로 재조회. 원문 해시, 출전 행의 말/경주/번호,
   경주 리포트의 경마장/일자/경주번호 불일치 모두 0건.

`publication.json`은 커밋 영수증, `published_ids.json`은 반영 행 ID 목록이다.
`post_commit_verification_tool.json`은 별도 연결의 검증 결과다.
운영의 말/경주/출전 행/경주 단위 리포트 원문은 변경하지 않았다.
새 테이블은 RLS 활성화, anon/authenticated 조회 권한 없음, service_role 조회 가능으로 확인했다.
보안 Advisor의 이 테이블 항목은 의도된 서버 전용 구조에 대한 INFO(`rls_enabled_no_policy`)다.

과거 최초 게시 시각은 입증되지 않았으므로 `source_published_at_ms=NULL`,
`historical_publication_time_verified=false`다. 관측 시각을 과거의 게시 시각으로 사용하면 안 된다.
신규 홈페이지 문구의 정기 수집·자동 반영은 이번 일회 반영에 추가하지 않았다.

## 운영 조회 예시

```sql
SELECT h.kra_horse_id, h.name_ko, rc.kra_meet_code, r.race_date_local,
       r.race_number, p.historical_program, p.phrase_text,
       p.entry_link_status, p.provenance_json
FROM public.horse_steward_phrases p
JOIN public.horses h ON h.id=p.horse_id
JOIN public.races r ON r.id=p.race_id
JOIN public.racecourses rc ON rc.id=r.racecourse_id
WHERE h.kra_horse_id='0041609'
ORDER BY r.race_date_local DESC, r.race_number, p.id;
```

## 게시 시점 확인

2026-10-17 19:06 KST에 공식 심판위원 Report 화면을 직접 조회했다.

- 서울: 당일 1~10경주 모두 비어 있지 않은 심판 문구 공개.
- 제주: 당일 1~7경주 모두 비어 있지 않은 심판 문구 공개.
- 이 관측은 당일 공개 사례를 입증한다. 항상 당일 전부 게시한다거나 경주 후 몇 분 이내라는
  보장·정확한 최초 게시 시각은 확인되지 않았다.
- 경마정보 이용안내와 현재 Report 화면에서 고정 게시 시각 안내를 찾지 못했다.
- 예전 자료의 추가 심의·검사 결과 반영 가능성을 고려하면 최초 게시와 최종 확정을 구별해야 한다.

공식 URL:

- https://race.kra.co.kr/referee/StewardsReport.do?Act=06&Sub=12&meet=1&rcDate=20261017
- https://race.kra.co.kr/referee/StewardsReport.do?Act=06&Sub=12&meet=2&rcDate=20261017
- https://race.kra.co.kr/raceguide/RaceInternetService.do

조회한 HTML은 이 폴더에 보존했다. `publication_timing_audit.json`에 파일 해시와 관측 결과를 기록했다.
이 당일 조회 자료는 게시 시점 확인용이며 말별 문구 48,130건의 반영 원천에 섞지 않았다.
수집 운영에는 경주 당일 종료 후 조회, 다음 날 재조회, 미게시 경주 재시도 방식을 권한다.
