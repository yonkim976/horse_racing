# E8-B 독립 검증 — 제한 수집 미완료 결과 확인

판정: **`capture_only_incomplete`라는 제출 결과는 증거와 일치한다.** 실패·빈 응답의 기록을 승인하며, 비어 있지 않은 실제 출전표 수집이나 실제 F_t 적격 검증의 완료를 승인하는 것은 아니다. 이번 검증에서는 새 HTTP 요청을 보내지 않았다.

## 원문·전송 기록 대조

두 격리 시도의 사전 프로토콜은 모두 서울 `20260919`, 공식 일정 `/API154/racePlan`과 출전표 `/API26_2/entrySheet_2`만 지정했다.

| 시도 | 원장에 기록된 transport 전송 | 독립 확인 |
|---|---:|---|
| 첫 시도 | 2 | 일정 요청의 ConnectError 2건, HTTP 상태·원문 없음 |
| attempt2 | 3 | 일정 1건·출전표 2건, HTTP 200 및 성공 header |
| 합계 | **5/12** | 실제 외부 서버가 받은 요청 수가 아니라 로컬 transport 전송 시도 수 |

정상 응답 3건은 모두 136바이트였고 SHA256은 `640c1da4ea90e6ffd55e7d69b9fec7afe03bdbd1b82b8ed662db4442fd6e2e5d`다. JSON 원문에서 `totalCount=0`, `pageNo=1`, `numOfRows=1000`, 실제 item 0개를 확인했다. 저장 blob은 하나이고 관측 이벤트는 세 개로 유지된다. 원문 파일 권한 0600, 디렉터리 권한 0700도 확인했다.

모든 전송 이벤트와 완료 ack를 순서·batch·attempt·raw hash로 대조했고 요청≤수신≤파싱≤완료 시각을 확인했다. 마지막 완료는 **2026-09-13 18:06:26.132 KST**다. 2차 출전표 관측의 간격은 110ms지만 두 응답 모두 비어 있으므로 출전집합 안정성의 증거가 아니다.

실제 schedule 행·entry 행·prospective 사례는 모두 0이다. T−30 계산값을 null로 남긴 것이 맞다. 빈 envelope의 complete 판정과 nonempty 수집 실패를 후속 assessment에서 구분했다.

## 재현성과 검사

- attempt2 manifest의 출력 4개 hash와 post assessment에 기록된 수집 당시 audit/manifest hash 일치.
- 최종 source 3개 hash 일치. 실행 당시 runner와 현재 runner의 hash는 다르며 사후 수정 이력이 명시돼 있다. 과거 hash 보존만으로 과거 실행 코드 전체를 복원했다고 주장하지 않는다. 현재 최종 runner는 빈 출전표를 반복 조회하지 않으므로 당시 3회 응답 경로와 동일하지 않다.
- 상위 E8-A H1/H2의 봉인 source/보존/출력 및 E7-B 보존 112개·출력 68개 hash를 재확인했다. 불일치 없음. E8-B manifest의 단순 `preserved_existing_artifacts=true` 표기만을 보존 증거로 삼지 않았다.
- 전체 `.venv/bin/python -m pytest -q`: **618 passed, 2 warnings**, 28.45초. 이번 검증에서 console pytest는 반복 실행하지 않았다.
- E8-B Python 3개 파일 Ruff check/format 통과. 전체 diff-check에는 기존 `src/horse_racing/web/racecourse.py:347` EOF 빈 줄 1건.
- 원 운영 DB·실제 결과·holdout을 조회하지 않았고 실제 수집·학습·예측·성능 평가를 추가 수행하지 않았다.

## 해석과 다음 작업

확인된 사실은 해당 파라미터·관측시각에 API가 성공 header와 빈 응답을 반환했다는 것이다. 미래 일정 미공개, 자료 제공 범위, 요청 계약 문제 중 어느 원인인지 이 표본만으로 식별할 수 없다. 현재 프로젝트의 기존 일정 수집 코드도 같은 `rccrs_cd/race_dt` 파라미터를 사용한다는 사실은 확인했지만, 이것만으로 공식 계약과 현재 지원 범위까지 검증된 것은 아니다.

따라서 이번 결과를 모델 예측력 실패로 해석하지 않는다. E8-A 합성 계약을 다시 전면 수정하거나 빈 응답이 사라질 때까지 날짜를 순회하지 않는다.

다음은 **과거 원문이 있는 서울 날짜 하나를 양성 대조군으로 한 작은 원천 진단**이다. 2026-05-31 이전 출전표·일정만 사용하고, 신규 전송은 최대 4회로 제한한다. 데이터가 나오면 그 과거 조건에서 요청 경로가 동작한다는 근거가 된다. 과거 대조도 비면 미공개라는 결론을 내리지 말고 공식 파라미터·지원 기간을 확인한다. 사후 수집한 과거 출전표는 prospective 자료가 아니다.

이 진단 이후 실제 공개된 미래 출전표로 한 번 더 capture 검증할 시점과 조건을 정한다. 이번에는 자동 수집을 등록하지 않는다. API 대기 문제를 새로운 모델 감사 과제로 늘리지 않는다.

- [검증 JSON 및 재현 소스](../data/logs/confirmed_starter_e8b_independent_review_20260913.json)
- [다음 에이전트용 제한 원천 진단 지시문](CONFIRMED_STARTER_E8B_SOURCE_CONTROL_AGENT_PROMPT_2026-09-13.md)
