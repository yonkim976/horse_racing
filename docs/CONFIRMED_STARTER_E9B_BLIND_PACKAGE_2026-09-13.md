# E9-B 블라인드 30건 판독 패키지 제출

2026-09-13. 이번 산출물은 독립 수작업 판독에 필요한 원문·출전표 패키지만 봉인한다. 새 30건에 동결 추출기를 실행하거나 정답 라벨·성능 지표를 만들지 않았다.

## 동결과 선정

- 승인된 E9-A H1/H2 manifest SHA256: `f19f5b77cb19b5f113585b4ac83497b7ec4579c8652ef2c7c5a72931daad973e`. manifest의 추출기 의존 소스 7개도 현재 파일 해시와 일치했다. 추출 규칙·기존 테스트·기존 산출물은 수정하지 않았다.
- 모집단은 기존 manifest의 서울 2025-01-01~2026-02-28 심판보고서 1,200건이다. 기존 E9-A 상세 표본 60건을 제외했다. 확인 가능한 E9-A `event_evidence.jsonl`의 report ID는 모두 그 60건 안에 있었고, 기록상 추가 제외는 0건이다. 그러나 다른 경로의 과거 노출은 증명할 수 없으므로 새 표본의 독립 미사용 상태는 **unknown**이다.
- 남은 1,140건을 `(race_id, report_id)`로 정렬한 뒤 `random.Random(20260914).sample(candidates, 30)`을 한 번 적용했다. 프로토콜에 후보 전체 키·제외 사유·seed·선택 키와 예상 원본 해시·코드/테스트/동결 소스 해시를 기록하고 나서야 선택된 원문과 roster를 읽었다. 사건 문구나 추출 결과로 점수를 매기거나 교체하지 않았다.
- 30개 report ID는 모두 고유하며 원본 해시가 일치한다. `judgement`와 `addJudgement` 원문이 모두 읽혔고, date-bounded 읽기 전용 DB roster의 말 번호·source ID 충돌도 0건이다. Coverage는 `ready_for_blind_reading` 30건, 누락·불명·충돌 0건이다. 선택 날짜는 2025-01-12~2026-02-14다.

## 검증 담당자에게 전달할 파일

- [사전 선정 프로토콜](../data/experiments/confirmed_starter_e9b_blind_20260913_v1/selection_protocol.json)
- [블라인드 판독용 Markdown](../data/experiments/confirmed_starter_e9b_blind_20260913_v1/blind_documents.md)
- [원문·roster 기계 판독 JSON](../data/experiments/confirmed_starter_e9b_blind_20260913_v1/blind_documents.json)
- [빈 annotation schema](../data/experiments/confirmed_starter_e9b_blind_20260913_v1/annotation_schema.json)
- [Coverage·노출 상태](../data/experiments/confirmed_starter_e9b_blind_20260913_v1/coverage_exposure.json)
- [보호 입력 전후 및 신규 파일 SHA256 manifest](../data/experiments/confirmed_starter_e9b_blind_20260913_v1/artifact_manifest.json)

JSON의 `fields.judgement`/`fields.addJudgement`가 정확한 원문 기준이다. span은 각 필드의 디코딩된 Unicode codepoint 기준 0-based `[start:end)`이며 공백·구두점은 정규화하지 않았다. Markdown에는 사건 강조·추출 cue·예상 라벨·기존 추출 출력이 없다. 빈 schema는 음성 라벨이 아니다.

향후 라벨 봉인 뒤 비교할 단위는 문서 내 `(report_id, horse_source_key, event_type, role)` 존재 여부이고, actor-victim 관계는 별도 근거로 다룬다. 중복 evidence 행은 분모에 중복 산입하지 않는다. 완전 판독·명시적 음성·불명/읽기 실패/미판독, 매칭되지 않은 추가·누락 건의 구분은 프로토콜에 사전 정의했다. 이번에는 어느 분모나 지표도 계산하지 않았다.

## 재현 검사와 한계

신규 패키지 코드·테스트에 Ruff check 통과, 관련 pytest 6개 통과. 별도 읽기 전용 대조에서 seed 재현, 30개 키와 원문 필드의 원천 일치, source/보호/신규 hash, roster 고유성을 확인했다. 전체 pytest는 이번 좁은 패키지 작업에서 재실행하지 않았다. 외부 HTTP·결과/배당 조회·feature dataset·학습·운영 연결은 수행하지 않았다.

검증자는 출력에 노출되지 않은 상태에서 30건을 독립 판독하고 기준 라벨을 별도로 봉인해야 한다. 수작업 라벨 봉인과 별도 실행 지시 전에는 동결 추출기를 이 표본에 실행하지 않는다. 원문은 사후 자료이며 T-30 가용성은 검증되지 않았다. 이번 패키지는 고유 사건 수, 다음 경주 예측력, 전체 모집단 정확도를 입증하지 않는다.
