# E8-A v2 독립 재검증

판정: **기존 R1–R4 반례 수정은 확인. 잔여 시간 계약 H1/H2 보완 후 승인 여부를 재판정한다.** 실제 수집·학습·운영 연결은 이번 검증에서도 수행하지 않았다. 새 기능이나 실제 원천 검증을 추가로 요구하는 것이 아니라, 현재 선언된 시간 계약의 두 누락 검사만 다룬다.

## 확인한 개선

제출 테스트를 실행하는 것과 별도로 임시 SQLite에서 기존 반례를 다시 구성했다.

| 기존 반례 | v2 독립 재현 결과 |
|---|---|
| R1 cutoff 후 field 완료 | `late_ineligible`로 거부 |
| R2 이미 정정된 옛 observation 선택 | `superseded`로 거부; 최신 정정 선택 시 `(7,11)`만 봉인 |
| R3 예정 출발 이후 새 snapshot | `new snapshot after cutoff`로 거부 |
| R4 원문과 다른 feature 값 | `feature value not reproduced`로 거부 |

등록 합성 계산과 dependency 검증, latest-source 선택, pending/ack/admission 구분은 이전보다 명확해졌다. 이 네 재현 결과는 인정한다.

## H1 [P1]: 잠깐의 clock 역행이 commit-ack 승인을 우회한다

근거: `src/horse_racing/analysis/confirmed_starter_e8a_v2.py:278–289`. field admission은 `ack_ms <= cutoff`만 검사한다. `_append`의 역행 검사는 admission 이벤트의 새 clock 값과 이전 journal 생성시각만 비교하므로 payload에 들어간 ack가 그 사이 역행한 사실을 확인하지 못한다. snapshot/prediction에도 같은 승인 패턴이 있다.

독립 반례의 연속 clock 값은 다음과 같다.

1. transaction 진입: `2000000000000` = cutoff
2. pending insert: `2000000000001` = cutoff+1
3. commit 반환 후 ack: `2000000000000` = cutoff로 역행
4. admission append: `2000000000002` = 다시 전진

결과: field pending 생성시각은 cutoff+1인데 commit ack는 그보다 1ms 빠르고 `status=accepted`다. `_field()`와 `verify_chain()`도 통과한다. 기존 late-completion 결함의 변형이며, 계약 문서의 clock 역행 거부를 충족하지 못한다.

필요 보완: 단계별 시간에 하한과 상한을 함께 강제한다. commit ack는 해당 transaction의 진입·insert 및 관련 선행 완료보다 빠를 수 없고 승인 deadline을 넘을 수 없다. observation/field/snapshot/prediction의 같은 패턴을 한 번에 검토한다. 역행 시각을 clamp하여 정상 승인으로 바꾸지 않는다. 실패 시 pending 또는 명시적 부적격으로 남기고 clock이 회복돼도 사후 승인하지 않는다.

## H2 [P2]: cutoff 이후로 선언한 feature availability도 승인된다

근거: `src/horse_racing/analysis/confirmed_starter_e8a_v2.py:338–340`, `367–397`. `declared_available_at_ms`가 source ack·계산 완료보다 빠르지 않은지만 검사하고 cutoff 상한은 검사하지 않는다.

독립 반례에서 source/계산/commit은 cutoff에 맞추고 `available_at_ms=2000001800001`, 즉 예정 출발+1ms로 선언했다. 값·키·dependency·계산 버전은 정상이다. snapshot admission과 이를 참조한 prediction admission이 모두 `accepted`다.

이 사례가 실제 미래 원문을 사용했다는 뜻은 아니다. 저장 계약 자체가 cutoff 이후 이용 가능하다고 선언한 입력을 사전 적격으로 승인한다는 뜻이다. 현재 문서와 v1부터의 source/feature cutoff 규칙에 맞지 않는다.

필요 보완: 선언 availability를 적격 판단에 사용하는 현재 의미를 유지하고 `max(source_ack, calculation_completed) <= declared_available_at_ms <= cutoff`를 강제한다. 실제 snapshot commit ack도 별도로 유효해야 한다. cutoff−1/cutoff/cutoff+1을 검사하되 하한을 충족하지 않은 입력을 정상 경계 사례로 잘못 구성하지 않는다. 잘못된 availability를 cutoff로 자동 보정하지 않는다.

## 산출물·검사

- 보존 16개 전후, 신규 source 5개, 출력 14개 hash 모두 일치.
- 상위 E7-B 보존 112개·출력 68개 hash 일치.
- 제출 5개 SQLite를 read-only로 열어 총 **29개 이벤트**의 chain, payload, raw, 참조 순서와 제출 admission 시각을 독립 산식으로 확인했다. 정상 합성 feature 값과 결과 hash도 원문에서 재계산해 일치했다. 제출 replay 자체에는 위 새 반례가 들어 있지 않다.
- 전체 `.venv/bin/python -m pytest -q`: **605 passed, 2 warnings**, 27.10초. console 방식은 이번 검증에서 재실행하지 않았다.
- E8-A v2 Python 3개 파일 Ruff check/format 통과.
- 전체 diff-check는 기존 `src/horse_racing/web/racecourse.py:347` EOF 빈 줄 1건. 전체 Ruff/format은 이번 재검증에서 재실행하지 않았으며 이전 숫자를 현재 실측으로 주장하지 않는다.
- 검증 중 실제 수집·tree 학습·확률 발행·성능 계산·실제 결과 조회는 0회. 구현 수정 없이 새 검증 문서·로그·프롬프트만 작성했다.

두 반례와 source는 [검증 JSON](../data/logs/confirmed_starter_e8a_v2_independent_review_20260913.json)에 보존했다. [H1/H2 보완 지시문](CONFIRMED_STARTER_E8A_V2_H1_H2_AGENT_PROMPT_2026-09-13.md)은 이 두 시간 검사와 회귀검증만 요청한다. 실제 수집에 필요한 원천·주기·scheduler 검증은 이번 보완 범위에 추가하지 않는다.
