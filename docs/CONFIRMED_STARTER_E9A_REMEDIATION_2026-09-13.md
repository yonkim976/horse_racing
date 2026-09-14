# E9-A R1–R3 보완 제출 — 술어별 귀속과 역할 원장

## 판정과 범위

독립 검증에서 확인한 잘못된 출발 지연 귀속 3건을 재현하고 보완했다. 같은 서울 심판보고서 60건(2025-01-01~2026-02-28)만 다시 판독했다. 기존 1,200건 모집단 봉인, 무작위 30건·문구 과대표집 30건, 113개 원문, v1/v2/v3 산출물·라벨·DB·H1/E8-B 입력은 수정하지 않았다. 새 v9는 **사후 원문 사건 추출·검토 산출물**이며 T-30 공개 확인, feature 생성, 학습, 성능 평가, 운영 승격을 뜻하지 않는다. 같은 에이전트가 동일 60건을 보며 규칙을 보완했으므로 독립 test 정확도나 모집단 정밀도를 주장하지 않는다.

## R1 — 술어의 주체 범위

기존 v3 후보를 유지하되 새 `confirmed_starter_e9a_remediation.py`에서 출발 지연·진로 막힘 cue의 선행 주어, 후행 관형어, 쉼표/와/과 병렬 목록을 술어별로 판정한다. `출발이 늦은 후`는 뒤 접촉 상대가 아닌 앞 주어에, `출발이 좋지 못했던`은 뒤 말에 연결한다. 앞 말의 독립 술어를 넘어 90자 안의 모든 말을 막힘 피해로 지정하지 않는다. 주어를 확정할 수 없으면 clear로 두지 않고 hold/abstain한다. race_id·말 이름 예외는 사용하지 않았다.

| 실제 race_id | v3의 잘못된 clear | v9의 명시 출발 지연 | 판단 |
|---|---|---|---|
| 3275 | ③ 디아나 | ④ 한강캡틴 | ③은 접촉 상대 |
| 3095 | ⑨ 청산질주 | ⑦ 히어아이엠 | `좋지 못했던`의 후행 피수식어 |
| 277 | ⑨ 빈센트알렉스 포함 | ① 라온킹스맨 등 기존 명시 말 | ⑨는 출발대 *진입* 불량, 늦은 출발과 다름 |

같은 술어 범위 재검토에서 race 2935의 ⑥→④ 수정과 race 3359의 병렬 주어 ⑤ 추가도 발견했다. 각각 원장에 연결했으며 추가 표본을 찾은 것이 아니다. 위 3건과 독립 검증의 합성 6건의 전후 clear 역할은 `counterexample_contrasts.json`에 보존한다. 추가로 긍정문·혼합 사실/인용·조건문·실제 127/286의 사실 절·연속 접촉 절·이름/번호 치환·출전명부 순서 변경 회귀를 테스트했다.

## R2 — 절 단위 관찰 판정

interference 피해·행위 후보에도 인용, 기수 진술, 후행 부정, 조건·추정을 확인한다. 합성 인용문은 victim/actor 모두 clear 0, `밀렸다는 사실은 없음`은 victim clear 0이다. 한 bullet에 독립 사실과 기수 인용·별도 조건문이 함께 있으면 사실 문장을 회수하고 인용·조건 절은 보류한다. 처분 설명의 `피해 정도는 크지 않은`처럼 사건 자체가 아니라 *정도*에 관한 부정은 쉼표 뒤 문맥으로 구분한다. 이 합성 문구들은 실제 60건의 발생 빈도를 뜻하지 않는다. 원문의 상호 접촉 167행은 인과 역할을 임의 확정하지 않고 ambiguous로 남겼다.

## R3 — 기존 clear 전수 연결과 coverage

v3 clear **197행 전부**를 원문 SHA256, 필드, 좁은 근거 절 오프셋, 경주 출전 식별키, 사건 유형·역할과 연결했다. 원장 결정은 유지 **193**, 수정 **3**, 삭제 **1**이다. 수정 3건은 새 말 clear ID로 이어지고, 삭제 1건은 race 277의 ⑨ 귀속이다. 추가 clear **4행**(race 2935의 ④, 3095의 ⑦, 3275의 ④, 3359의 ⑤)도 원장에 별도 기재했다. 따라서 원장은 **201행**이며, 새 clear 197행 모두에 대응 검토 행이 있다. 이 검토의 provenance는 `same_agent_source_clause_and_roster_review_not_independent_gold`다. 기계적 원문 재절취와 read-only, SQL 날짜 상한 출전명부 일치를 전 행 검사했지만, 독립 검증자의 역할 판독을 대체하지 않는다.

| 동일 60건 | v3 | v9 |
|---|---:|---:|
| 전체 evidence 행 | 371 | 375 |
| clear 행 | 197 | 197 |
| ambiguous / abstain / hold | 167 / 7 / 0 | 167 / 7 / 4 |
| clear report | 57 | 57 |
| clear 경주·말 key | 171 | 171 |
| 임시 사건관계 중복제거 수 | 195 | 195 |

clear 행·report·말 key 수의 일치는 **구성 변경이 상쇄된 산술적 우연**이며 197/57/171이라는 목표에 맞춘 결과가 아니다. v9 clear 유형별 행은 출발 지연 76, 막힘 33, interference 70, 접촉 18이다. 역할별로 affected 76, victim 84, actor 37이며 표본군별 clear 행은 무작위 97·문구 과대표집 100이다. v3의 보고서 단위 `extractor_anchor_matched`는 말·역할 승인으로 사용하지 않는다. 기존 보고서 앵커 불일치 race 2151(`밀려` 누락), 3712(⑧ 번호/이름 충돌)는 보존하며, 이번 197행 역할 원장과 다른 층위의 진단이다.

evidence **행**은 고유 사건이 아니다. race 277의 ①은 처분 bullet과 주행 bullet 두 행으로 반복된다. race 4032의 ①도 같은 형태다. 향후 피해 사건 수에는 `(race_id, event_type, role, horse_source_key, 위치)`를 임시 관계키로 쓰되, 출발 지연 위치는 `start_gate`로 정규화한다. 동일 위치의 서로 다른 사건을 합칠 위험이 있어 이 값은 확정 feature count가 아니며, 사건 시각/쌍/인과 관계를 별도 검토하기 전에는 feature 값을 만들지 않는다.

`report_coverage.jsonl`은 60건 모두 원문 존재·해시 일치·판독 가능·날짜 상한 read-only 출전명부 확인을 명시한다. clear가 없는 보고서도 `event_absence=not_established`이며 사건 0으로 채우지 않는다. 원문 부재, 판독 불가, 식별 불명, PIT 공개 미검증은 별도 상태다. 이 표본에서는 앞의 두 원천 결측은 0이지만, 모든 보고서의 `pit_availability=unverified`다. 원천 요청/수신 시각은 사후 수집 시각이지 사전 공개 증거가 아니다. `<추가심판사항>`의 다른 경주 사건과 3712 식별 충돌을 현재 경주 clear로 강제하지 않는다.

## 재현과 보존

- 새 실행 소스: `src/horse_racing/analysis/confirmed_starter_e9a_remediation.py`, `scripts/run_confirmed_starter_e9a_remediation.py`; 회귀 테스트: `tests/test_confirmed_starter_e9a_remediation.py`.
- 최종 산출물: `data/experiments/confirmed_starter_e9a_20260913_v9/`의 `execution_protocol.json`, `event_evidence.jsonl`, `role_review_ledger.jsonl`, `report_coverage.jsonl`, `counterexample_contrasts.json`, `information_summary.json`, `artifact_manifest.json`. v4/v5/v6/v7/v8은 원문 절 위치·원장 표현·회귀 범위를 보완하는 중간 시도이며 덮어쓰지 않고 보존했다.
- protocol은 출전명부/원문 재판독 전에 표본·기존 출력·원문·DB·코드·테스트 해시를 봉인했다. 보호 파일의 실행 전후 SHA256이 전부 같고, 최종 출력·코드 해시도 manifest와 현재 파일이 일치한다. 외부 HTTP·모델 fit·성능 평가는 0회다.
- 관련 Ruff check와 format-check 통과. 새 회귀 **13 passed**; 전체 `pytest -q` **645 passed, 2 warnings**(기존 Starlette/Polars 경고). 새 세 파일의 scoped whitespace diff-check에는 오류가 없었다.

## 독립 검증자에게 남기는 점

원장의 193 유지 근거 절을 포함해 201행의 주어·역할을 원문과 별도로 판독해 달라. 특히 race 277/2935/3095/3275/3359의 삭제·수정·추가, 127/286의 명확한 사실 절, 인용/부정/조건 절, race 2151/3712의 보고서 앵커와 식별 충돌을 확인해야 한다. 규칙은 한국어 심판보고서 전체 구문을 완전 해석하는 모델이 아니며, 이번 같은-agent 검토 수치는 독립 정확도가 아니다. 2026-03 이후 원문, 확대 지역, 학습·예측력, T-30 공개 가능성은 평가하지 않았다. 기존 136열·H1·E8-B·DNF 계약·운영 경로는 이번에 변경하지 않았다.
