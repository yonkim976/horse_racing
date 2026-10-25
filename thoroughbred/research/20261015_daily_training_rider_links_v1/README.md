# 일별조교 기승자 이름 연결 적재

2026-10-15 사용자 승인에 따라 일별조교 기승자 이름을 연구 DB에 추가했다. **공식 번호282개에 대한 이름 매핑을 저장하고, 조교1,599,487행에 이름을 연결했다. 송당스카이 충돌1행은 이름과 연결 인물ID를NULL로 유지한다.** 번호 미연결70개·190,375행과 번호 미기재3,383,170행은 별도 상태로 보존했다.

조회는 `daily_training_rider_linked`를 사용한다. 원문 `daily_training_raw`는 유지하며, 새 뷰에 이름·ID·연결 상태·근거·사건별 확인 상태를 추가했다. 사건일 범위는 기존2010-01-01~2026-09-29이고, 새 경주·조교 사건을 수집한 작업은 아니다. 기존 심판리포트 등 다른 자료도 변경하지 않았다.

## 연결 결과

| 상태 | 조교 관측 수 | 처리 |
| --- | ---: | --- |
| 공식 프로필 번호로 이름 연결 | 1,599,487 | 원문 번호와 공식 프로필 ID의 문자열 완전일치 |
| 송당스카이 충돌 보류 | 1 | 후보와 양쪽 근거 보존, 최종 이름·연결ID는NULL |
| 번호는 있으나 프로필 미대응 | 190,375 | 70개 번호의 미연결 원장 보존 |
| 번호 미기재(`-`) | 3,383,170 | 이름·ID 추정 없음 |
| 합계 | 5,173,033 | 원문 관측 수와 동일 |

이름은 2026-09-30 공식 기수 프로필 스냅샷의 값이다. 당일 역할은 원문 `prGubun`을 유지한다. 기수 프로필에서 이름이 확인되더라도 해당 조교 날짜의 기수 자격·소속·상태를 소급하지 않는다. 이름만 같다는 이유로 다른 공식 ID를 합치지 않았다. 기존 원문의 앞자리0·영숫자 번호를 그대로 유지했다.

## 송당스카이 미확정

- 서울2026-09-28,06:10~06:22의 해당 관측1행만 보류했다.
- API `prNo=080608`와 프로필 후보명오수철, 공식 웹 표기유승완을 각각 보존했다.
- `rider_name_linked`와 `rider_official_id_linked`는NULL, `rider_identity_status`는 `source_conflict_hold`다.
- 같은 번호080608의 다른5,866행은 정상 연결했다. 번호 전체를 보류하지 않았다.

## 미연결 번호 보고

[70개 번호 전체 목록 CSV](reports/unmatched_rider_ids.csv)에는 번호별 관측 수·최초/최종 조교일·관련 말 수·지역·원문 기승자 구분을 기록했다. [JSON 원장](input/rider_unmatched_ids.json)도 함께 보존한다. 번호는 문자열이며, 지역3은 영남 통합 원천으로 실제 부산·영천 장소를 임의로 나누지 않는다.

| 원문 기승자 구분 | 미연결 관측 수 |
| --- | ---: |
| 조교보 | 128,111 |
| 구분 미기재(`-`) | 62,233 |
| 기수 | 31 |
| 합계 | 190,375 |

동일 번호가 여러 시기의 구분에 등장할 수 있다. 지역별로는 서울69개 번호·190,344행, 영남1개 번호·31행이다. 이 원장은 기수 프로필에서 이름을 찾지 못한 번호 목록이며, 번호 자체를 오류로 판정한 목록이 아니다.

주요 예시:

| 번호 | 관측 수 | 기간 | 원문 구분 |
| --- | ---: | --- | --- |
| `091501` | 12,650 | 2010-04-03~2021-12-15 | 조교보·미기재 |
| `091318` | 9,981 | 2010-01-02~2021-12-15 | 조교보·미기재 |
| `090036` | 7,508 | 2010-01-02~2021-12-15 | 조교보·미기재 |
| `080626` | 31 | 2026-09-04~2026-09-10 | 기수·영남 |

[번호×구분×지역 상세115그룹](reports/unmatched_role_region_groups.csv), [구분별 집계](reports/unmatched_by_rider_type.csv), [지역별 집계](reports/unmatched_by_meet.csv)에서 전체 분포를 확인할 수 있다. 번호 없는3,383,170행은70개 번호 목록에 포함하지 않는다.

## 추가한 DB 객체

| 객체 | 내용 |
| --- | --- |
| `rider_name_links` | 공식 번호·이름 매핑282행과 프로필 출처 |
| `rider_identity_conflict_holds` | 송당스카이 충돌1행과 API·프로필·웹 근거 |
| `rider_unmatched_ids` | 미연결 번호70행의 요약 |
| `rider_web_event_verification` | 공식 웹과 유일하게 대응한1,247개 관측의 확인 상태·원문 표시 |
| `daily_training_rider_linked` | 일별조교 전체5,173,033행에 이름·ID·상태·출처를 추가한 뷰 |

새 뷰의 주요 열은 `rider_name_linked`, `rider_official_id_linked`, `rider_identity_status`, `rider_name_basis`, `event_verification_status`다. 후보명은 `rider_name_candidate`, 충돌 사유는 `rider_link_hold_reason`에서 확인한다. 번호 일치로 이름을 연결한 상태와 홈페이지에서 개별 사건을 확인한 상태를 구분한다.

```sql
SELECT event_date, horse_name_raw, rider_type_raw, rider_id_raw,
       rider_name_candidate, rider_name_linked, rider_identity_status,
       event_verification_web_rider_display_raw
FROM daily_training_rider_linked
WHERE horse_name_raw = '송당스카이'
  AND event_date = DATE '2026-09-28';
```

## 검증과 보존

- [최종 통합 결과](summary.json)에 적용 후DB·명세 해시, 검증 수량과 보고서 해시를 기록했다.
- 사용자 지정 GPT-6 Luna xhigh 서브에이전트가 입력·로더를 준비했고, 주 에이전트가 코드·입력을 검토한 뒤 적용했다.
- [사전검증35항목](reports/dry_run_report.json) 모두 통과. 매핑282개·미연결70개·역할/지역115그룹은 주 에이전트의 독립 계산과 일치한다.
- [실제 적용 결과](reports/apply_report.json): 기존208객체에서213객체로 증가했고, 원천manifest는27→28행이다.
- [주 에이전트 독립 검증12항목](root_new_links_verification.json) 모두 통과. 연결/미연결 분할, 충돌1행, 같은 번호의 다른 행, 행 증식 없음,70개 번호의 기간·지역·구분·말 수, 웹1,247행 전체 근거, 원문 열 유지와 출처를 확인했다.
- [기존208객체 보존 검증](root_preservation_verification.json) 통과. 기존 테이블 전체 행의SHA256 다중집합을 양방향 대조하고 스키마·뷰 정의를 확인했다. 원천manifest만1행 추가됐고 기존 행 손실은0개다. 등록211개 행 수와 최종DB 해시도 일치한다.
- 적용 직전 DB·명세를 [백업](../../data/core_api_2010_20260929_v1/backups/20261015_before_daily_training_rider_links/backup_pair_attestation.json)하고 원본과 해시 일치를 확인했다. 운영DB에는 접근하지 않았다.

최종 DB SHA256: `16a5e0127a830dd1d95db2bfd1178fa4af8f43265d80de852dc2f409329c02f3`.

원문 및 이번 입력은 `input/rider_link_input_manifest.json`의 해시로 고정했다. 원문·이름 연결과 모델용 정보 이용 시점 검증은 구분하며, 이번 적재는 전체 연구 DB의 최종 동결을 뜻하지 않는다.

## 재실행 기준

`load_daily_training_rider_links.py`는 당시DB·명세 해시에 고정된 일회성 단계 로더다. `--apply`는 통과한dry-run·동일 입력/코드 해시·검증된 백업이 있어야 실행되며, 이미 적용한 DB에 다시 추가하는 것은 차단한다. 범용 증분 적재 도구로 사용하지 않는다. 입력 준비·사전검증은 적용 전 기준본에만 실행하고, 현재 적재본 검증은 두 root 검증 스크립트를 사용한다.
