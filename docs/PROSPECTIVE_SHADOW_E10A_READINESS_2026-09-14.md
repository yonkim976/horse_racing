# E10-A 전향 shadow: 한 번짜리 실제 capture 착수 준비표

2026-09-14 기준 로컬 기록만 검토했다. **결정: `waiting_for_publication_evidence`.** 서울 2026-09-19의 공식 일정·출전표 게시 근거는 현재 읽은 로컬 기록에 없고, 2026-09-13의 해당 날짜 조회는 일정 0행·출전표 0행이었다. 이는 경주 미개최나 API 미게시의 원인 판정이 아니다. 이번에는 HTTP, 자동화, 수집, feature snapshot, 추론·확률 발행, 결과 조회, 운영 DB 변경을 하지 않았다.

## 기존 기능과 이번 준비 상태

| 조건 | 상태 | 현재 근거와 차단 의미 |
|---|---|---|
| 서울 2026-09-19 공식 게시 근거 | `unverified` | [E8-B 기록](CONFIRMED_STARTER_E8B_2026-09-13.md)의 9/13 관측은 양쪽 0행. 공식 게시 시각·예정 여부는 로컬 기록으로 확정 불가. 게시 증거 전에는 요청하지 않는다. |
| 미래 날짜 비어 있지 않은 일정·출전표 | `unavailable` | E8-B의 대상 날짜 응답 0/0. [과거 양성 대조](CONFIRMED_STARTER_E8B_SOURCE_CONTROL_INDEPENDENT_REVIEW_2026-09-13.md)는 2026-05-17 첫 페이지 일정 10행·출전표 110행일 뿐 미래 자료가 아니다. |
| 실제 원문 adapter·페이지 검사 | `verified` | [E8-B capture 코드](../src/horse_racing/analysis/confirmed_starter_e8b.py)의 두 endpoint 제한, 원문 CAS, 명시적 `totalCount/pageNo/numOfRows`, 페이지·키·날짜·서울·중복/충돌 검사 및 [runner](../scripts/run_confirmed_starter_e8b.py)가 있다. 이는 코드 존재와 과거/빈 응답 동작의 확인이지 미래 완전성 승인이 아니다. |
| 경주 source key와 원천 예정시각 | `unavailable` | 미래 0행이라 사례 경주·출전 키 `(meet, rcDate, rcNo, chulNo, hrNo)`·`strtPargTm`을 얻지 못했다. 일정·출전표의 공통 race number가 생긴 뒤 한 사례를 선택한다. |
| 영속화 ack·cutoff 계산 기능 | `verified` | E8-B는 요청·수신·파싱과 raw 저장 후 `capture_ack.commit_completed_at_ms`를 분리해 기록하고, `schedule_cutoff()`는 원천 `strtPargTm − 30분`을 계산한다. |
| 미래 사례의 실제 ack·cutoff·margin | `unavailable` | 미래 경주 자료가 없어 값이 없다. 성공 판정에는 **일정과 출전표 모두의 완료 ack 최댓값 ≤ 당시 일정 버전의 cutoff**가 필요하다. |
| 누적 요청 예산 원장 | `verified` | 읽을 수 있는 E8-B 원장은 2+3+2 실제 전송으로 **7/12 사용, 기록상 5회 잔여**다. retry·page·redirect 발생도 전송으로 센다. 다른 실행/원장 누락 여부는 착수 직전 다시 확인한다. |
| 누적 예산의 코드 강제 | `unavailable` | 현재 [E8-B runner](../scripts/run_confirmed_starter_e8b.py)는 매 실행 `BudgetTransport(..., limit=12)`로 새로 시작한다. 7회 기사용 상태에 그대로 실행하면 전역 12회 상한을 보장하지 못한다. 최소 연결 보완 및 검토 전 실행 금지. |
| API의 취소·정정 반영과 F_t 출전집합 | `unverified` | 페이지 count/키 완전성은 취소·정정 완전성과 다르다. E8-B의 빈 응답 재조회와 과거 첫 페이지 대조는 이 계약을 승인하지 못한다. |
| 실제 raw→E8-A field/snapshot 연결 | `unavailable` | [E8-A v2 계약](CONFIRMED_STARTER_E8A_V2_CONTRACT_2026-09-13.md)은 `synthetic_horse_number_pct_v1`과 합성 원문만 승인한다. 실제 KRA raw를 synthetic observation/feature로 위장해 통과시키지 않는다. |
| 후향 A 136열 모델의 실제 F_t 적격 | `unverified` | 후향 A는 실제 출발자 모집단이며 역사적 T−30 field가 아니다. 출전집합/취소 사건, 시간가변 source 관측, 현재 snapshot 성별의 PIT, 실제 raw feature 계산·이용가능시각 연결이 미확인이다. 고정 모델도 곧바로 운영 적격이 아니다. |

`verified`는 적힌 **제한된 로컬 증거**에만 적용한다. `unavailable`은 현재 로컬 자료나 연결 기능 부재이지 외부에 자료가 영구히 없다는 뜻이 아니다. 실제 capture 성공이나 F_t 적격을 뜻하는 행은 없다.

## 사전 고정할 최소 성공 계약

서울 예정 경주일 **하나**를 공식 게시 근거로 확인한 후 고정한다. 2026-09-19는 기존 E8-B 대상일일 뿐 아직 공식 개최·게시를 확정하지 않는다. 허용 source는 공식 API154 `/racePlan`과 API26_2 `/entrySheet_2`뿐이다. 원문을 비공개 CAS에 영속화하고, 각 페이지의 성공 header와 명시적 page 계약·총수·연속성·서울/날짜·중복 키·말 번호/ID 충돌을 검사한다. 두 원천 모두 실제 비어 있지 않아야 한다. 기존 runner의 `capture_only_completed`는 이 raw 수집 조건만 뜻한다. **전향 사례 성공은 별도**로, 공통 경주 중 원천 예정시각·출전 source key·완료 ack와 cutoff 조건을 충족하는 가장 낮은 race number 하나가 있어야 한다. 조건을 충족하는 경주가 없으면 `prospective_case=null`로 남기며 다른 날짜로 편의 교체하지 않는다. 중간 오류·빈 응답·예산 소진은 원문과 사유를 보존하고 불완전으로 끝낸다.

Cutoff는 캡처 시점에 관측한 일정 버전의 `strtPargTm − 30분`이다. 일정과 출전표의 실제 영속화 완료 ack가 모두 cutoff 이전이어야 하지만, **더 일찍 수집했다는 것만으로 정확한 T−30 최신 상태는 아니다.** 공개·적용 시각이 응답에 없으면 `null`로 둔다. 취소/정정 반영 범위와 실제 source 가용성 검증 전에는 `F_t_eligibility=unverified`, `operating_model_status=not_activated`를 유지한다. 로컬 시계 ack도 공인시각 증명이 아니다.

## 한 번짜리 착수 순서와 실행 전제

1. 공식 게시 근거의 URL/문서·확인 시각·내용 hash와 대상 서울 날짜를 독립 확인한다. 근거가 없으면 여기서 `waiting_for_publication_evidence`로 종료한다. 예정 출발시각을 추정해 사전 입력하지 않는다.
2. 기존 세 요청 원장의 7회와 추가 원장 유무를 재대조하고, 날짜·두 endpoint·공개 파라미터·최대 전송 **잔여 5회 이하**·원본 코드 hash·공식 게시 근거를 새 사전 protocol에 HTTP 전에 봉인한다. 서비스 인증값 자체는 기록하지 않는다. 전역 잔여가 불명하면 실행 불가다.
3. [기존 E8-B runner](../scripts/run_confirmed_starter_e8b.py)의 요청 상한을 누적 원장 기반 잔여치로 강제하는 **최소 연결 보완**을 별도 검토한다. 현재의 `limit=12` 재초기화는 그대로 쓰지 않는다. 새 journal/CAS/상태머신은 만들지 않는다. 예산 gate 검토 후에만 별도 명시적 실제 수집 지시를 받아, 격리된 새 root에서 일정→출전표를 한 번 수집한다. 필요 페이지와 retry도 같은 잔여치 안에서 세고 redirect는 따라가지 않는다. 빈 응답을 이유로 날짜 변경·반복 조회하지 않는다.
4. raw SHA·명시적 페이지 계약·전체 날짜 count·경주별 key/출전두수·요청≤수신≤파싱≤commit ack·원천 예정시각과 cutoff margin을 검사한다. 계획한 경주 사례가 없으면 사례 없음으로 남긴다. 이전 raw를 합성 E8-A 승인 이벤트로 import하지 않는다.
5. 원장·raw 비공개 CAS·page/key/time audit·manifest·불완전/완료 판정을 독립 검증에 제출하고 종료한다. feature snapshot·예측은 별도 승인 전까지 만들지 않는다.

필요한 환경 전제는 `.venv` Python 의존성, `HORSE_RACING_DATA_GO_KR_SERVICE_KEY`가 **실행 환경에만** 존재함, 공식 API base URL 접근 허용, 비공개 새 출력 디렉터리와 신뢰 가능한 로컬 시계다. 인증값 존재 여부만 검사하고 값은 보고서·protocol·로그에 적지 않는다. 예산 gate의 설계·회귀·독립 검토가 끝난 **후에만** 사용할 예정 명령은 다음과 같다. 이 명령은 현재 코드의 전역 예산 결함 때문에 **지금 실행하면 안 된다**.

```bash
.venv/bin/python -m scripts.run_confirmed_starter_e8b --date 20260919 --root data/experiments/prospective_shadow_e10a_capture_20260919_attempt1
```

예상 산출물은 새 root의 `preflight_protocol.json`, `capture_journal.jsonl`, `raw_private/`, `page_key_time_audit.json`, `manifest.json` 및 필요 시 실패 평가다. 최소 코드 수정 후보는 `scripts/run_confirmed_starter_e8b.py`의 누적 예산 preflight/`BudgetTransport` 상한 전달, 필요하면 읽기 전용 원장 대조 helper 하나다. 이는 **설계안**이며 이번에 구현하지 않는다.

## 모델 연결과 E9 경계

E8-A H1/H2의 clock·cutoff·field/snapshot 계약 승인은 합성 offline 저장기의 승인이다. 실제 raw feature snapshot, 기존 136열의 source별 이용가능시각과 성별 snapshot PIT, 취소/DNS 사건 정의 및 후향 A와 실제 사전 `F_t`의 모집단 차이를 해결하지 않는다. 기존 API26_2의 과거 양성 대조에서는 같은 출전 key 110개 중 77행·239셀이 사후 달랐고, 일부 누적 필드는 시점에 따라 값이 바뀔 수 있다. 이것만으로 기존 136열의 실제 누수가 증명된 것은 아니다.

E9-B 최초 동결 비교는 30문서 기준 precision **81/82**, recall **81/121**, interference 회수 **10/33**이다. 이 수치를 추출되지 않은 사건=없음이나 evidence 행 수=피해 횟수로 바꾸지 않는다. E9 심판보고서는 당시 공개시각 미확인이므로 전향 feature로 연결하지 않는다. 봉인된 규칙·라벨·최초 점수는 보존한다.

이 준비표와 [기계 판독 상태](../data/logs/prospective_shadow_e10a_readiness_20260914.json)를 제출한 뒤 종료한다. 실제 capture·모델 연결은 별도 지시와 검증이 필요하다.
