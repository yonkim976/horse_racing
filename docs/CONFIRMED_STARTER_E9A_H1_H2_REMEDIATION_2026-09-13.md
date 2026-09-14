# E9-A v9 H1/H2 보완 제출 — 신원 유일성·actor 사건 관계

## 결론과 범위

독립 재검증의 H1/H2 반례를 같은 서울 봉인 심판보고서 **60건**(2025-01-01~2026-02-28)에서 보완했다. 기존 v3/v9와 모든 중간 실험·원문·라벨·DB·H1·E8-B·registry 및 동시 dirty 변경은 수정하지 않았다. 새 소스·테스트·runner와 `confirmed_starter_e9a_h1h2_20260913_v2` 산출물만 추가했다. 실제 자료의 확정 clear는 v9와 동일하지만, 이 수치를 목표로 맞춘 것은 아니다. 이번 결과는 동일 에이전트의 고정 개발 표본 감사이며 독립 정확도 판정이 아니다.

## H1 — 신원 충돌의 전 경로 차단

v9의 번호→단일 runner dict가 충돌 시 마지막 runner를 선택하는 문제를 새 gate에서 차단한다. 한 경주에서 출전번호가 두 번 나타나거나 source ID가 두 번 나타나면 **그 번호와 연관된 말은 모두 abstain**한다. 같은 번호·다른 이름, 같은 번호·같은 이름·다른 source ID, 완전히 같은 중복 행도 충돌이다. 반면 서로 다른 유일 번호에 같은 이름이 있는 경우에는 원문의 번호로 구분한다. 충돌하지 않은 다른 출전 말은 그대로 판독한다. 원문 번호·이름은 roster와 정확히 일치해야 하며, 순서로 충돌을 해소하지 않는다. 이 gate는 v9의 기존 추출·주어 보완·문장 복구가 만든 행 **모두**에 적용된다.

독립 로그의 `duplicate_forward`는 v9에서 ① affected clear였으나 새 버전은 clear 0·abstain 1이다. `duplicate_reverse`도 동일한 abstain이며, 같은 번호·같은 이름·다른 ID인 `duplicate_same_name` 역시 clear 0이다. 추가 회귀로 source ID 중복·정확한 중복 키·이름/번호 치환·입력 순서 역전·영향받지 않는 유일 말의 clear 유지·서로 다른 번호의 동명 말을 검사했다. **실제 봉인 60건의 날짜 상한 read-only roster에는 번호/ID 충돌 0건**이므로, H1이 실제 197 clear를 바꿨다는 주장은 하지 않는다.

## H2 — actor 이동과 동일 피해 사건 연결

actor clear는 이제 같은 원문 bullet에서 식별된 피해 말의 확정 관측과 연결된 경우에만 유지한다. 지원 관계는 (1) 한 문장 안의 actor 이동→직접 피해, (2) 피해를 먼저 쓰고 해당 actor의 진로변경을 원인으로 판단한 표현, (3) 명시 연결어가 있는 연쇄, (4) 방향이 드러난 접촉이다. 단독 이동, 다른 문장의 같은 말 재등장, 관계 부정, 인용·조건은 actor를 clear로 승인하지 않는다. 피해 관측이 독립적으로 명시되면 victim은 유지한다. 불확실하면 actor만 hold/unknown으로 둔다.

독립 로그의 `actor_disconnected`에서 v9는 ① victim과 무관한 후속 ② 이동을 actor clear로 냈다. 새 버전은 **① victim clear 유지, ② actor hold**다. 정상 순방향·`것에 대해 … 원인으로 판단` 역순 표현, 문장 분리, 관계 부정, 상호 접촉 후 별도 방해, 동일 말 재등장 회귀를 통과했다. 합성 반례를 실제 발생 빈도로 해석하지 않는다.

v9의 실제 **actor clear 37행 전부**에 actor 행동 span, victim 관측 span, 관계 span·유형·피해 source key를 붙여 원문과 재절취 확인했다. 관계 유형은 직접 피해 15, 피해 선행·원인 판단 12, 방향 접촉 9, 명시 인과 1이다. race **1698**의 ⑦라온더어펌드 actor는 앞의 상호 접촉에 선행한 이동을 버리고, 뒤의 `⑦…지속해서 바깥으로 기대며 나가 ⑧…불편하였` 관계(`judgement` 169–212)에 연결했다. 같은 race의 별도 ⑪미스터스톰 피해는 `것에 대해 … 충분한 거리 없이 … 판단` 관계(`judgement` 379–478)로 연결했다. ⑦의 actor 귀속 자체를 오귀속으로 바꾸지 않았다. 두 관계 및 각 subspan의 정확한 원문 위치는 `counterexample_contrasts.json`과 `actor_relationship_review.jsonl`에 있다.

## 전수 연결·집계·보존

v9 evidence **375행 전부**를 새 ID에 일대일로 연결했다. actor 37행은 `retain_with_relation`, 나머지 **338행**은 사건 유형·역할·확실성·말 키·근거 절 의미가 그대로인 `retain_unchanged`다. 실제 표본에서 새 hold/삭제/추가 clear는 없었다. 기존 v9의 201행 R1–R3 원장도 보호했다. 새 `lineage_ledger.jsonl`은 375행 전부, `actor_relationship_review.jsonl`은 37행, `report_coverage.jsonl`은 60건 전부를 포함한다.

| 동일 봉인 60건 | v9 | H1/H2 v2 |
|---|---:|---:|
| evidence 행 | 375 | 375 |
| clear / ambiguous / abstain / hold | 197 / 167 / 7 / 4 | 197 / 167 / 7 / 4 |
| clear report / 경주·말 key | 57 / 171 | 57 / 171 |
| 임시 고유 사건관계 | 195 | 195 |
| clear actor 관계 span | 미검증 | 37/37 검토 |

evidence 행, 잠정 사건관계, 고유 말 key는 서로 다른 단위다. 사건관계는 경주·유형·역할·말·연결된 피해 말·위치의 잠정 묶음이며 동일 위치의 별도 사건을 합칠 수 있어 feature count가 아니다. 값이 이전과 같은 것은 이 표본에서 실제 H1 충돌이 없고 H2 actor 37건이 명시 관계로 확인됐기 때문이지 검증 정확도나 미래 효용을 뜻하지 않는다.

새 실행 전 `execution_protocol.json`에 고정 report ID·날짜 상한·모집단/라벨/v9 evidence·독립 로그·코드/테스트 및 보호 경로 해시를 봉인했다. 읽기 전용 roster SQL은 서울 2025-01-01~2026-02-28 범위를 명시한다. **보호 120경로의 전후 SHA256이 동일**, 새 소스/테스트 7개 및 출력 7개의 현재 hash가 manifest와 일치했다. 전 evidence bullet, 모든 clear 좁은 절과 출전키, actor 관계 및 하위 span의 원문·roster 대응을 확인했다. 외부 HTTP·결과/배당 조회·feature dataset·학습·성능 비교·운영 연결은 0회다.

새 회귀 **9 passed**, 전체 `pytest -q` **654 passed, 2 warnings**(기존 Starlette/Polars 경고). 새 세 파일의 Ruff check/format-check 및 범위 한정 whitespace diff-check 통과. 전역 Ruff는 이번 범위 밖이다.

## 검증자 확인과 한계

최종 산출물은 `data/experiments/confirmed_starter_e9a_h1h2_20260913_v2/`, 코드/테스트는 `src/horse_racing/analysis/confirmed_starter_e9a_h1h2.py`, `scripts/run_confirmed_starter_e9a_h1h2.py`, `tests/test_confirmed_starter_e9a_h1h2.py`다. v1은 중간 시도 그대로 보존했다. 검증자는 H1의 순서 불변 abstain, H2 `actor_disconnected`, 실제 1698의 두 관계 span 및 actor 37행의 인과 연결을 우선 재판독해 달라. 원문 substring·roster 일치는 역할 의미를 독립적으로 입증하지 않으며, 동일 표본을 보고 규칙을 보완한 한계가 남는다. 보고서의 T-30 공개 시각은 계속 **미검증**이다. 추가 승인 전 다음 연구·학습·운영 단계로 가지 않는다.
