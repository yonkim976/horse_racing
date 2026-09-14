# E9-B 동결 추출기 1회 텍스트 품질 비교 — 독립 검증 제출

2026-09-13. 승인된 E9-A H1/H2 추출 규칙을 수정하지 않고, 봉인된 E9-B 30문서에 report당 정확히 한 번 적용했다. 결과는 사후 심판보고서 **텍스트 추출 품질**이며 경마 예측·수익 성능이 아니다.

## 봉인과 호출

- 기준 라벨 v2 manifest SHA256 `285d91e0f85b909c4c7ebf889c18158ffdbea62520b1824d4499d8111b1be849`, 승인 추출기 manifest SHA256 `f19f5b77cb19b5f113585b4ac83497b7ec4579c8652ef2c7c5a72931daad973e`, 블라인드 패키지 manifest SHA256 `660030e78baf04e1c98ea158259e1be8582839f00250f21ea664f8f0ffe7b03f` 및 동결 의존 소스를 실행 전에 대조했다.
- 30개 report ID·원문 필드·roster·완전 판독 기준 라벨의 일대일 coverage, 기준 양성 고유 단위 121개를 확인했다. 비교 정의·해시·고정 호출 순서를 먼저 [평가 프로토콜](../data/experiments/confirmed_starter_e9b_frozen_evaluation_20260913_v1/evaluation_protocol.json)에 봉인했다.
- [호출 원장](../data/experiments/confirmed_starter_e9b_frozen_evaluation_20260913_v1/call_ledger.jsonl): 계획 30, 시도 30, 성공 30, 빈 출력 0, 실패·재시도 0. [원 evidence](../data/experiments/confirmed_starter_e9b_frozen_evaluation_20260913_v1/raw_evidence.jsonl) 156행 전체를 보존했다. `clear` 82, `ambiguous` 61, `abstain` 11, `hold` 2행이다.

## 사전 정의된 주 비교

단위는 문서 내 고유 `(report_id, horse_source_key, event_type, role)` 존재 여부다. 같은 단위의 evidence 행은 한 번만 세되 ID 연결을 보존했다. 기준은 `asserted`·확정 key·unknown 이외 role의 121개이고 `semantic_extension`을 포함한다. 출력 양성은 roster key/type/role/span이 유효한 `clear`만 사용했다. 명시 양성은 uncertainty mask보다 우선하며, quoted 단독은 양성이 아니다. TP·FP·FN·판정불가 전체 키와 양쪽 ID, 원문 span·필드 및 이유는 [comparison JSON](../data/experiments/confirmed_starter_e9b_frozen_evaluation_20260913_v1/comparison.json)에 있다. [최초 사람 판독표](../data/experiments/confirmed_starter_e9b_frozen_evaluation_20260913_v1/comparison_readable.md)는 전 단위 키·ID와 불일치/판정불가 원문을 표시한다. 점수 봉인 후 표시만 확장한 [전체 원문 근거표](../data/experiments/confirmed_starter_e9b_frozen_evaluation_readable_20260913_v1/comparison_full_readable.md)는 TP를 포함한 122개 전 단위와 확정 관계 20쌍의 원문을 표시한다. 이 보충표는 추출·라벨·점수를 변경하지 않았고 [별도 해시 manifest](../data/experiments/confirmed_starter_e9b_frozen_evaluation_readable_20260913_v1/artifact_manifest.json)에 봉인했다.

| 지표 | 분자 / 분모 | 값 |
|---|---:|---:|
| Precision | TP 81 / (TP 81 + FP 1) = 82 | 0.9878 |
| Recall | TP 81 / (TP 81 + FN 40) = 121 | 0.6694 |
| F1 | 위 precision·recall의 조화평균 | 0.7980 |
| 판정불가 clear | 0 / 전체 고유 clear 82 | 0% |

기준 양성 `81 TP + 40 FN = 121`, clear `81 TP + 1 FP + 0 판정불가 = 82`의 보존 법칙이 성립한다. 1개 FP 후보는 report 3045의 ④ 말에 부여한 `start_delay`: 원문은 “출발이 늦은 ③” 및 별도의 ⑦·⑪ 지연을 서술한다. 기준 라벨을 수정하거나 FP를 사후 제외하지 않았다. 기준 라벨 이의 제기는 [별도 파일](../data/experiments/confirmed_starter_e9b_frozen_evaluation_20260913_v1/reference_disputes.json)에 비워 두었으며, 이는 모든 라벨을 전문가가 재판독했다는 뜻이 아니다.

| 유형 | TP | FP | FN | Recall |
|---|---:|---:|---:|---:|
| start_delay | 53 | 1 | 2 | 0.9636 |
| blocked_or_controlled | 10 | 0 | 8 | 0.5556 |
| contact | 8 | 0 | 7 | 0.5333 |
| interference | 10 | 0 | 23 | 0.3030 |

역할별 recall은 affected 53/55, victim 21/42, actor 7/24다. `core` 기준 양성 113개 중 81개, `semantic_extension` 기준 양성 8개 중 0개를 회수했다. 이 두 범주는 기준 양성 집합의 진단이며 독립된 FP 분모를 만들지 않았다. 상세 precision·recall·분모는 comparison JSON의 `diagnostics`에 있다.

확정 actor-victim 관계는 기준 pair 20개 중 7개를 회수했고 13개가 미회수다. 집단 actor 목록을 임의의 Cartesian pair로 펼치지 않았다. 미일치 **출력** pair는 0개지만 불명 관계의 음성 집합이 완전하지 않아 pair precision은 계산하지 않았다. 명시 상호 접촉의 역할 불명 참여자는 기준 고유 61, key가 있는 출력 58, 겹침 52로 별도 목록에 기록했고 확정 actor/victim 점수에 섞지 않았다. dense TN·accuracy는 계산하지 않았다.

## 재현·한계

새 비교 코드의 합성 회귀 6개와 기존 H1/H2 회귀를 합쳐 pytest **15 passed**; 새 코드·테스트 Ruff check 및 format 통과. 실행 후 원장을 독립적으로 읽어 호출 순서 30개, evidence 156행, 평가 상태 122개, 분모·보존 법칙을 재계산했다. [해시 manifest](../data/experiments/confirmed_starter_e9b_frozen_evaluation_20260913_v1/artifact_manifest.json)의 보호 입력 전후 해시는 동일하며 신규 소스·테스트·출력 해시도 일치한다. 기존 라벨·규칙·패키지·DB·registry는 수정하지 않았다.

기준은 추출 출력을 보지 않은 단일 AI 판독자의 30문서 라벨이며 외부 과거 노출은 unknown이다. 따라서 독립 전문가 정확도, 서울 전체 보고서 정확도, 고유 사건 발생 횟수, T-30 가용성 또는 미래 경주 예측력은 입증하지 않는다. 규칙 수정·재평가·학습·운영 승격 없이 이 최초 비교를 검증 담당자에게 제출한다.
