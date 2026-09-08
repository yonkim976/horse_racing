# 프로젝트 문서 안내

이 디렉터리는 프로젝트의 목표와 현재 상태를 분리해서 기록한다. 코드 실행 방법만 필요한
경우에는 루트의 [README](../README.md)를 보면 된다.

## 문서 구성

| 문서 | 역할 | 갱신 시점 |
|---|---|---|
| [예상·배팅 모델 연구 총정리](RESEARCH_REVIEW_2026-09-07.md) | 국내외 학술연구 17건·공개 프로젝트 8건, 현재 모델과의 연결 및 후속 실험 제안 | 문헌 조사·연구 우선순위 검토 시 |
| [BLUEPRINT](BLUEPRINT.md) | 최종 목표, 설계 원칙, 목표 아키텍처와 성공 기준 | 방향이나 아키텍처가 바뀔 때 |
| [PROGRESS](PROGRESS.md) | 완료 범위와 바로 다음 작업 (한 장 요약) | 마일스톤이 끝날 때 |
| [CURRENT_STATUS](CURRENT_STATUS.md) | 조사·결정·구현·데이터 건수 상세 | 작업 단위가 끝날 때 |
| [SESSION_SUMMARY_2026-08-25](SESSION_SUMMARY_2026-08-25.md) | 2026-08-25 수집·백필·UI 총정리 | 당일 작업 마감·인수인계 |
| [SESSION_SUMMARY_2026-08-26](SESSION_SUMMARY_2026-08-26.md) | 2026-08-26 대시보드 디자인·인터랙션 전면 개편 | 당일 작업 마감·인수인계 |
| [DATA_SOURCE_CATALOG](DATA_SOURCE_CATALOG.md) | KRA OpenAPI·Text 원천 카탈로그와 다른 에이전트용 다운로드 절차 | 데이터 원천이나 명세가 바뀔 때 |
| [DATA_AND_OPERATIONS](DATA_AND_OPERATIONS.md) | API, 저장 구조, DB 키, 명령어와 장애 복구법 | 수집기나 스키마가 바뀔 때 |
| [ROADMAP](ROADMAP.md) | 다음 단계, 우선순위, 관문(Gate)과 단계별 완료 조건 | 우선순위가 바뀔 때 |
| [MODELING_ROADMAP](MODELING_ROADMAP.md) | 예측 모델 상세 계획: 데이터 제약, feature, 분할, 판정 기준 | 모델 설계나 판정 기준이 바뀔 때 |
| [FULL_RANKING_PLACKETT_LUCE](FULL_RANKING_PLACKETT_LUCE.md) | 순서 top3 확률 계층, valid·walk-forward 비교와 판정 | 순위확률 모델을 변경할 때 |
| [TOP5_RANK_DISTRIBUTION](TOP5_RANK_DISTRIBUTION.md) | 말별 정확한 1~5위·누적 TopK 확률, 실제 착순 비교와 장기 성능 | Top5 순위분포 모델을 변경할 때 |
| [RACEFIT_V1](RACEFIT_V1.md) | 조건 적합도·구간 에너지·페이스 시나리오 모델과 walk-forward 판정 | RaceFit feature나 모델 판정을 변경할 때 |
| [RACEFIT_V2](RACEFIT_V2.md) | 동적 상태·학습형 페이스·당일 앞 경주 편향의 분리 검증과 V2 판정 | 당일 편향 모델이나 시간 계약을 변경할 때 |
| [HISTORICAL_REGIME_CHANGES](HISTORICAL_REGIME_CHANGES.md) | 과거 제도 변화, 제주 마종·등급·거리 분리 및 정규화 계약 | 백필 범위나 경마 제도가 바뀔 때 |
| [PREDICTION_LEDGER](PREDICTION_LEDGER.md) | 사전 예측 불변 원장, 정산 규칙과 운영 명령 | 예측 발행·정산 파이프라인을 운영할 때 |
| [FEATURE_CATALOG](FEATURE_CATALOG.md) | Feature v1 96개 (자동 생성, 직접 수정 금지) | `write-feature-catalog` 실행 시 |

## 문서 작성 원칙

1. `BLUEPRINT`에는 목표 상태를, `CURRENT_STATUS`에는 실제 완료 상태를 기록한다.
2. 조사 결과와 구현 완료를 구분한다. API가 존재한다고 해서 수집기가 구현된 것은 아니다.
3. 데이터 건수는 가능하면 SQLite 검증 결과와 날짜를 함께 기록한다.
4. 외부 조사 결과는 공식 원문 링크와 확인 날짜를 남긴다.
5. 모델 성능은 재현 가능한 데이터 범위, 예측 시점, 평가 방식과 함께 기록한다.
6. 서비스키, 인증정보와 로컬 원본 데이터는 문서나 Git에 넣지 않는다.

## 권장 읽기 순서

새 참여자는 다음 순서로 읽는다.

1. [BLUEPRINT](BLUEPRINT.md)
2. [PROGRESS](PROGRESS.md) — 완료와 다음 작업
3. [CURRENT_STATUS](CURRENT_STATUS.md) — 데이터 건수. 수집은 [SESSION_SUMMARY_2026-08-25](SESSION_SUMMARY_2026-08-25.md), 대시보드는 [SESSION_SUMMARY_2026-08-26](SESSION_SUMMARY_2026-08-26.md)
4. [DATA_SOURCE_CATALOG](DATA_SOURCE_CATALOG.md)
5. [DATA_AND_OPERATIONS](DATA_AND_OPERATIONS.md)
6. [ROADMAP](ROADMAP.md) → 모델은 [MODELING_ROADMAP](MODELING_ROADMAP.md)
