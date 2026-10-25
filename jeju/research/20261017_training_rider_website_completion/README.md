# 제주 일별조교 기승자 종류: 홈페이지 보완·DB 반영

적용일: **2026-10-17 KST**. 사용자가 확인된 후보의 DB 반영과 최근 6개월 미분류 전체의 홈페이지 대조를 승인했다. 대상 DB는 `jeju/data/jeju_native_core.sqlite3`다.

## 반영 결과

| 항목 | 반영 전 | 반영 후 |
|---|---:|---:|
| 전체 일별조교 원행 | 912,913 | 912,913 |
| 전체 미분류 | 301,368 | **281,483** |
| 전체 주로조교 | 1,236 | **21,121** |
| 최근 6개월 대상 미분류 | 20,408 | **523** |

**19,885행을 미분류에서 주로조교로 보완했다.** 최근 대상 미분류의 97.44%다. 신규 조회에서 확인한 19,880행과 이전 공식 홈페이지 원문에 있는 5행을 합쳤다. 기존 534행과 587행의 합집합 784행도 이 19,885행에 포함되며 별도로 더하지 않는다.

조회 창은 오늘 기준 `2026-04-17~2026-10-17`, 실제 보유 조교 최종일은 `2026-10-15`다. 이 창의 전체 조교는 40,513행이며 그중 미분류 20,408행·913두가 대상이다. 수량은 원문 기록 행 수이며 인원 수나 실제 시행 횟수가 아니다.

## 미분류로 남긴 523행

| 사유 | 행 수 | 처리 |
|---|---:|---|
| 같은 사건은 확인했지만 홈페이지 기승자 칸이 `외` | 56 | 직책·실명을 해석하지 않고 미분류 유지 |
| 현재 홈페이지에서 정확한 사건키를 찾지 못함 | 467 | 미분류 유지; 조교 미시행이나 데이터 오류로 단정하지 않음 |

정확 일치가 없는 467행은 모두 표시 범위 경계인 4월 17일 163행, 4월 18일 156행, 4월 19일 148행이다. 페이지의 최근 6개월 안내와 표시 범위를 관측했으며 서버의 기간 계산 방식은 확정하지 않았다.

최신 조회에서는 총 472행이 일치하지 않았다. 그중 4월 18일 2행·19일 3행은 이전 공식 원문에서 직접 검증할 수 있어 보완했다. 원문 경로와 SHA는 [대조 원장](outcome_reconciliation.json)에 남겼다. [미분류 523행의 행별 근거](remaining_unclassified.jsonl)도 보존했다. 확인되지 않는 행의 기존 DB 분류값은 변경하지 않았다.

최근 창보다 오래된 미분류 280,960행은 이번 변경 대상이 아니다. 사건 당시 공식 근거 없이 사번·이름·현재 직책을 과거 전체에 적용하지 않는다.

## 수집·분류 기준

- 공식 [제주 말별 조교현황](https://race.kra.co.kr/racehorse/profileTrainState.do?Act=02&Sub=1&hrNo=3104724&meet=2) **913페이지 모두 HTTP 200·말 ID·조교표·범례 검증**을 통과했다. 905페이지를 새로 받고 같은 날 확보한 8페이지는 SHA 확인 후 재사용했다. 신규 HTML은 45,115,895바이트다.
- 최초 제한 환경의 DNS 차단 후 허용된 공식 읽기 조회로 재개했다. 페이지 원장에 기록된 요청 시도는 906회다. 최초 차단의 별도 파일은 없으며 실행 출력에만 남아 있다. 최종 페이지 실패는 0건이다.
- 말 ID·조교일·입장·퇴장시각·조교시간이 모두 일치하는 행만 연결했다. API 시각의 초가 00인지도 확인했다. 여러 원행 또는 여러 홈페이지 행이 같은 사건키에 대응하면 모호한 연결로 보류한다. 이번 후보의 모호한 연결은 없었다.
- 범례 `관:주로조교`를 근거로 분류했다. 관리사 직책으로 바꾸지 않는다. 이번 추가 분류는 모두 주로조교다. `조`, `생`, `(트)`와 공식 API307 명부로 확인한 기수 이름의 판정 규칙도 유지했다.
- API 원문 종류 `-`, 사번, 담당 조교사명, 시각·기간은 보존했다. 사번 이름 참조와 사건 당시 종류의 직접 확인을 구분한다.

## DB 조회 기준

`daily_training_rider_type_assignments`의 해당 19,885행에서 분류·홈페이지 근거 필드만 보완했다. 원 조교행과 식별자는 보존했다.

| 객체 | 범위 |
|---|---|
| `daily_training_rider_type_assignments` | 원행별 저장 분류·상태·홈페이지 경로와 SHA |
| `daily_training_rider_type_values` | 원행 필드가 바뀌면 미분류로 차단하는 조회 |
| `daily_training_rider_types`, `training_current` | 현재 전체 조교와 종류·기수 이름 |
| `daily_training_rider_types_analysis_2026` | 기존 분석 상한 2026-09-19까지의 종류·기수 이름 |

이름 분석은 `jockey_name`을 사용한다. 종류가 기수인 경우에만 제공하며 이번 주로조교 보완행은 모두 NULL이다. 홈페이지 원표기는 `rider_label_on_website_raw`에서 추적한다. `trName_raw`는 담당 조교사명이며 기승자 이름으로 대체하지 않는다.

```sql
SELECT training_date, horse_id, current_horse_name,
       rider_type, rider_type_status, jockey_name,
       prGubun_raw, prNo_raw, rider_label_on_website_raw
FROM training_current
WHERE horse_id = '3104724'
ORDER BY training_date DESC;
```

이번 작업은 기승자 종류의 근거 보완이며 기존 모델 입력 파일·가중치를 갱신한 기록이 아니다. 과거 예측 입력은 기존 공개시점 계약과 날짜 제한을 따른다.

## 검증·적용 원장

- [수집 요약](collection/manifest.json), [913페이지 원장](collection/pages_manifest.jsonl), [전체 대상별 대조](collection/outcomes.jsonl), [원행 스냅샷](collection/target_snapshot.jsonl).
- [반영 계획](plan.jsonl), [계획 SHA·집계](plan.summary.json), [실제 적용](application_manifest.json), [실제 명령 재실행: 추가 변경 0건](replay_verification.json).
- [반영 전 독립 검증](verification/preapply_verification.json): 별도 BeautifulSoup 파서로 913페이지·과거 원문 16개·20,408행 대상을 대조해 19,885행의 계획과 일치함을 확인했다.
- [반영 후 최종 검증](verification/postapply_verification.json)도 통과했다. [DB 전 컬럼 비교](verification/native_postapply_verification.json)는 백업과 41개 테이블·2,783,599행을 대조해 정확히 대상 19,885행의 허용 분류·근거 필드만 바뀌었음을 확인했다. 원 조교행·기존 확정 분류·미확인 행·스키마는 보존됐다. 무결성 검사와 전체 외래키 검사도 통과했다.
- [독립 조회 검증](verification/view_verification.json)은 대상 19,885행이 `daily_training_rider_type_values`와 `training_current`에서 계획값과 일치하고 기수 외 이름이 NULL임을 확인했다. 분석 상한까지의 대상은 17,052행, 이후 2,833행은 기존 상한 조회에서 제외되는 정의를 유지한다. 원행·SQL 정의 보존과 날짜 제한을 검산했으며 느린 과거 분석 뷰의 전체 결과를 다시 물리화하지 않았다.
- 로더의 트랜잭션 내 DB 무결성·스키마 불변·원행 연결키 검증은 통과했다. 적용 직전 [DB 백업](before_website_completion.sqlite3)을 보관한다. DB 전체 복원은 이후 변경도 되돌릴 수 있으므로 복구 범위를 먼저 확인한다.

이번 변경의 포인터는 `jeju/data/jeju_native_core.rider_types_manifest.json`이다. 이전 수집·갱신 manifest는 당시 적용 원장으로 보존했다.

## 재현 코드

[수집기](collection/collect.py), [분류·반영기](apply_website_types.py), [독립 검증기](verification/verify_website_completion.py)를 보존한다. 이 배치는 고정된 원행 스냅샷과 공식 원문에 연결되어 있다. 다음 기간 조사는 새 작업 경로와 스냅샷으로 진행한다. 기존 일괄 분류기로 이번 홈페이지 보완값을 덮어쓰지 않는다.

이미 반영한 동일 계획은 아래 명령으로 검산할 수 있다. 적용 원장과 현재 분류·원행 연결이 같으면 DB를 읽기 전용으로 열고 `already_applied`, 추가 변경 0건으로 끝난다.

```sh
.venv/bin/python jeju/research/20261017_training_rider_website_completion/apply_website_types.py \
  --apply --expected-db-sha256 53c42e9a7944da7d05b9f5bc56bc2defcdaa110704d92bd3b785df9e50527f96
```
