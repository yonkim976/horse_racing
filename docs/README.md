# 프로젝트 문서 안내

이 디렉터리는 프로젝트의 목표와 현재 상태를 분리해서 기록한다. 코드 실행 방법만 필요한
경우에는 루트의 [README](../README.md)를 보면 된다.

## 문서 구성

| 문서 | 역할 | 갱신 시점 |
|---|---|---|
| [BLUEPRINT](BLUEPRINT.md) | 최종 목표, 설계 원칙, 목표 아키텍처와 성공 기준 | 방향이나 아키텍처가 바뀔 때 |
| [CURRENT_STATUS](CURRENT_STATUS.md) | 지금까지의 조사·대화·결정·구현·데이터 현황 | 작업 단위가 끝날 때 |
| [DATA_AND_OPERATIONS](DATA_AND_OPERATIONS.md) | API, 저장 구조, DB 키, 명령어와 장애 복구법 | 수집기나 스키마가 바뀔 때 |
| [ROADMAP](ROADMAP.md) | 다음 단계, 우선순위, 단계별 완료 조건 | 우선순위가 바뀔 때 |

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
2. [CURRENT_STATUS](CURRENT_STATUS.md)
3. [DATA_AND_OPERATIONS](DATA_AND_OPERATIONS.md)
4. [ROADMAP](ROADMAP.md)

