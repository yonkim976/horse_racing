# E9-B 동결 추출기 1회 품질 비교 지시

작업 위치 `/Users/kimyongjin/Desktop/horse_racing`.
먼저 `docs/CONFIRMED_STARTER_E9B_REFERENCE_SEAL_REVIEW_2026-09-13.md`와 봉인 reference_protocol을 읽어라. 사용자 검증 담당자는 새 30건의 추출 출력을 보지 않고 기준 라벨을 작성했다. 이제 기존 규칙을 동결한 상태에서 이 표본의 추출 품질만 평가한다.

## 입력과 금지 범위

- 블라인드 패키지: `data/experiments/confirmed_starter_e9b_blind_20260913_v1/`.
- 최종 기준 라벨: `data/experiments/confirmed_starter_e9b_reference_20260913_v2/`.
- 기준 manifest SHA256: `285d91e0f85b909c4c7ebf889c18158ffdbea62520b1824d4499d8111b1be849`.
- 승인 추출기 manifest: `data/experiments/confirmed_starter_e9a_h1h2_20260913_v2/artifact_manifest.json`, SHA256 `f19f5b77cb19b5f113585b4ac83497b7ec4579c8652ef2c7c5a72931daad973e`.
- 호출 대상은 해당 봉인 의존 소스의 `extract_report_h1h2`다. 추출 규칙·기존 소스·기준 라벨·기존 산출물은 변경하지 않는다. 새 runner/평가 코드/실험 경로만 추가한다.
- 외부 HTTP, 표본 교체/추가, 결과·배당 조회, 모델 학습, feature dataset, 실제 경마 확률·수익 성능 계산 및 운영 연결은 금지한다. 이번 precision/recall은 텍스트 추출 품질 지표다.

## 실행 전 봉인 및 1회 호출

1. 양쪽 입력 manifest와 동결 소스 전부를 현재 hash와 대조한다. 실패하면 추출 0회로 종료한다. 30 report ID 집합·원문 fields·roster·기준 reference coverage를 각각 확인한다.
2. 아래 비교 정의, 입력·실행 소스 hash, 호출 예정 report ID와 순서를 새 protocol에 출력 생성 전에 봉인한다. 평가 코드는 합성 자료로 먼저 검증한다. 실제 30건으로 규칙이나 평가 정의를 조정하지 않는다.
3. 고정 순서로 report당 1회, 총 30회 동결 추출 함수를 호출한다. 원문 fields와 패키지 roster를 그대로 사용하고 출력 원문 evidence를 전부 저장한다. 보고서별 호출·성공·빈 출력·실패 원장을 남긴다. 첫 예외 시 저장한 결과를 보존하고 평가를 중단한다. 성공한 report를 조용히 재호출하거나 실패 report를 분모에서 빼지 않는다. 재실행이 필요하면 먼저 원인과 기존 호출 횟수를 제출한다.

## 비교 정의

- 주 단위: `(report_id, horse_source_key, event_type, role)`의 문서 내 존재. 동일 evidence 중복은 한 단위로 합치되 원 evidence ID 연결을 보존한다.
- reference 양성 G: `assertion_status=asserted`, key가 있고 role이 unknown이 아닌 라벨. `semantic_extension`을 포함한다. 봉인 수작업 양성 집합은 121개이며 이것을 확인용 계약으로 사용하고 숫자를 맞추려고 라벨을 수정하지 않는다.
- extractor 양성 P: `certainty=clear`, 유효한 key/type/role을 가진 출력. 입력 roster 밖 키·비어 있는 clear 신원·잘못된 원문 span·중복 report/입력 누락은 계약 실패로 보고한다. 잘못된 출력이 평가에서 사라지도록 inner join 하지 않는다.
- reference_protocol과 uncertainty_masks를 적용한다. explicit positive는 같은 문서의 다른 모호 근거보다 우선한다. 확정 positive가 없는 신원/역할 불명 영역의 P는 TP/FP로 강제 분류하지 않고 별도 unscorable 출력으로 남긴다. quoted만 있는 관측은 positive가 아니다. 완전 판독한 범위에서 그 외의 unmatched clear는 FP 후보이며 원문을 첨부한다.
- TP=P∩G, FN=G−P, FP=판정 가능한 P−G. precision/recall/F1을 분모와 함께 보고한다. 분모가 0이면 null과 이유를 남긴다. 판정불가 출력의 수와 전체 clear 중 비율을 함께 공개한다. dense TN/accuracy로 희소 사건의 품질을 부풀리지 않는다.
- 전체 지표를 주 결과로 유지하고 사건 유형·역할·core/semantic_extension별 집합과 분모를 별도 진단한다. 결과를 보고 유리한 하위집합만 선택하지 않는다.
- unknown/ambiguous/abstain/hold는 별도 coverage 진단으로 보고한다. 명시 상호 접촉의 unknown 참여자 추출도 별도 참조 목록과 대조하되 확정 actor/victim 품질과 섞지 않는다.
- actor-victim 관계는 기준 라벨에 양쪽 key가 명시된 pair만 확정 참조로 사용한다. 집단 actor 목록을 Cartesian pair로 확장하지 않는다. 확정 pair 회수 여부와 미일치 출력 관계를 원문으로 나열한다. 불명 관계의 음성 집합이 완전하지 않으므로 임의 pair precision을 계산하지 않는다.

## 검증과 보고

- synthetic evaluator 회귀: 중복 evidence, 누락/추가 report·roster key, 명시 positive+quoted 중복, unknown mask와 positive 우선, 분모 0, 동일 말 다중 사건/다중 피해, 잘못된 span. 실제 추출기 테스트로 새 30건을 반복 실행하지 않는다.
- 주 결과와 TP/FP/FN/unscorable의 키 목록·reference/evidence ID·원문·이유를 machine-readable 파일 및 사람이 읽는 표로 제출한다. 모든 reference 양성과 모든 추출 clear가 정확히 한 평가 상태에 속하는지 보존 법칙을 검사한다.
- 기준 라벨이 잘못됐다고 의심돼도 고치지 않는다. 별도 `reference_disputes`에 원문, 기존 라벨, 이의 근거만 적는다. 기준 봉인본 그대로의 최초 비교 결과를 보존한다. 추후 출력 노출 후 수정은 별도의 탐색 결과로만 분리한다.
- 새로운 실행 경로에 protocol, 호출 원장, 원 evidence, comparison, 불일치/불명 목록, hash manifest, 보고서를 남긴다. 기존 보호 파일 전후 hash 및 새 소스·테스트·출력 hash를 검사한다.
- 관련 검사 및 적절한 회귀를 실행하고 결과를 적는다. 기존 범위 밖 lint/dirty 변경은 수정하지 않는다.

단일 AI 판독 기준이고 외부 과거 노출이 unknown인 30문서의 제한된 비교다. 독립 전문가 정확도, 전체 한국 경마 추출 정확도, 미래 예측 우월성·수익성을 주장하지 않는다. 결과가 좋거나 나빠도 규칙 수정·재평가·학습으로 이어가지 말고 독립 검증 제출 후 종료한다.
