# 프로젝트 문서 안내

이 디렉터리는 프로젝트의 목표와 현재 상태를 분리해서 기록한다. 코드 실행 방법만 필요한
경우에는 루트의 [README](../README.md)를 보면 된다.

## 문서 구성

| 문서 | 역할 | 갱신 시점 |
|---|---|---|
| [모델·배팅 연구 통합 색인](MODEL_RESEARCH_INDEX.md) | 현재 모델, 과거 연구의 결론·채택 여부, run ID와 산출물 위치 | **모델 연구를 찾을 때 가장 먼저** |
| [파일 저장 감사](ARTIFACT_STORAGE_AUDIT_2026-09-11.md) | 실험 원장·모델·데이터셋·보고서 연결 무결성과 저장 구조 | 산출물 정리·백업 전 |
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
| [Ability V2~V6](ABILITY_V2_NO_RATING.md) | 배당·공식 레이팅을 제외한 능력모델과 속도·게이트 실험 | 순수 능력모델을 비교할 때 |
| [FULL_RANKING_PLACKETT_LUCE](FULL_RANKING_PLACKETT_LUCE.md) | 순서 top3 확률 계층, valid·walk-forward 비교와 판정 | 순위확률 모델을 변경할 때 |
| [TOP5_RANK_DISTRIBUTION](TOP5_RANK_DISTRIBUTION.md) | 말별 정확한 1~5위·누적 TopK 확률, 실제 착순 비교와 장기 성능 | Top5 순위분포 모델을 변경할 때 |
| [RACEFIT_V1](RACEFIT_V1.md) | 조건 적합도·구간 에너지·페이스 시나리오 모델과 walk-forward 판정 | RaceFit feature나 모델 판정을 변경할 때 |
| [RACEFIT_V2](RACEFIT_V2.md) | 동적 상태·학습형 페이스·당일 앞 경주 편향의 분리 검증과 V2 판정 | 당일 편향 모델이나 시간 계약을 변경할 때 |
| [RACEFIT_V3](RACEFIT_V3_LIFECYCLE.md) | 나이·출전주기·조교 상태와 최근/장기 모델의 분리 판정 | 생애주기 변수를 변경할 때 |
| [RACEFIT_V4](RACEFIT_V4_GATE_PACE.md) | 게이트×초반속도와 2단계 전개 모델 | 전개·게이트 변수를 변경할 때 |
| [RACEFIT_V5](RACEFIT_V5_SAND_RESPONSE.md) | 시간가변 모래 사건·회복 상태와 Sand Event 판정 | 모래 반응 변수를 변경할 때 |
| [RACEFIT_V6](RACEFIT_V6_REMEDIATION.md) | 기수 직접 조교·교정심사·장구 변경 실험 | 교정·훈련 신호를 변경할 때 |
| [Top5 Hybrid V1](TOP5_HYBRID_V1.md) | 장기·최근 Top5 확률 앙상블 | 앙상블 비중을 변경할 때 |
| [Top5 Margin V2](TOP5_MARGIN_V2.md) | 착차 기반 연속 성능 보조축 | 착차 target을 변경할 때 |
| [RaceValue V1](RACE_VALUE_V1.md) | 복병마 탐지와 승식별 ROI 스트레스 테스트 | 복병 정의를 변경할 때 |
| [RacePortfolio V1](RACE_PORTFOLIO_V1.md) | 최종배당 불확실성과 다승식 배분 연구 | 배팅 정책을 변경할 때 |
| [외곽 선행마 연구](OUTER_FRONT_ADVANTAGE_STUDY.md) | 게이트·선행 경합 가설의 장기 통계 | 전개 가설 검토 시 |
| [제주 단독 V1](JEJU_STANDALONE_V1.md) | 제주 마종 분리와 최초 전용 모델 | 제주 V1 재현 시 |
| [제주 단독 V2](JEJU_STANDALONE_V2.md) | 한국/제 표기 안정화·기수 의존·규제 실험과 최신 제주 후보 | 제주 모델을 사용할 때 |
| [HISTORICAL_REGIME_CHANGES](HISTORICAL_REGIME_CHANGES.md) | 과거 제도 변화, 제주 마종·등급·거리 분리 및 정규화 계약 | 백필 범위나 경마 제도가 바뀔 때 |
| [PREDICTION_LEDGER](PREDICTION_LEDGER.md) | 사전 예측 불변 원장, 정산 규칙과 운영 명령 | 예측 발행·정산 파이프라인을 운영할 때 |
| [FEATURE_CATALOG](FEATURE_CATALOG.md) | 자동 생성 feature 정의·원천·누수 계약 (직접 수정 금지) | `write-feature-catalog` 실행 시 |
| [주파기록 품질](FINISH_TIME_QUALITY.md) | 경마장별 기록 범위·이상치 검사 | 기록 feature 변경 전 |
| [라벨 정책 감사](LABEL_POLICY_AUDIT.md) | 동착·취소·특수 착순 코드 처리 | 학습 라벨 변경 전 |
| [제주 구간기록 복원](JEJU_SECTION_REPAIR_2026-09-08.md) | 제주 위치·구간 원천 복구와 검증 | 제주 구간자료 확인 시 |
| [서울 구간 저장 감사](SEOUL_SECTION_AUDIT_2026-09-08.md) | 서울 구간 데이터 오류 범위와 원인 | 서울 구간자료 확인 시 |
| [서울 구간 복원](SEOUL_SECTION_REPAIR_2026-09-08.md) | 복원 절차·변경 행·검증 | 복구 이력 확인 시 |
| [서울 지도 개편](SEOUL_MAP_REDESIGN_2026-09-08.md) | 공식 구조 기반 화면 재설계 | 지도 UI 변경 시 |
| [서울 코너 위치 대조](SEOUL_CORNER_POSITIONS_2026-09-09.md) | 화면 체크포인트와 구간 데이터의 의미 구분 | 코너 위치 해석 시 |
| [전국 경주로 시각화 지시서](RACECOURSE_VISUALIZATION_PROMPT.md) | 서울·제주·부경 근사 경주로 구현 계약 | 지도 기능 인수인계 시 |
| [영천 첫 시행 지원](YEONGCHEON_SUPPORT_2026-09-11.md) | meet code 4 수집·화면 지원과 미검증 범위 | 영천 데이터 운영 시 |
| [새 세션 인수인계](session_handoff_prompt_ko.md) | 모델·예측 시점 계약을 다른 세션에 전달 | 새 분석 세션 시작 시 |

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
3. [모델·배팅 연구 통합 색인](MODEL_RESEARCH_INDEX.md) — 현재 모델과 과거 판정
4. [CURRENT_STATUS](CURRENT_STATUS.md) — 데이터·구현 상세
5. [파일 저장 감사](ARTIFACT_STORAGE_AUDIT_2026-09-11.md) — 산출물 무결성
6. [DATA_SOURCE_CATALOG](DATA_SOURCE_CATALOG.md)
7. [DATA_AND_OPERATIONS](DATA_AND_OPERATIONS.md)
8. [ROADMAP](ROADMAP.md) → 모델 설계는 [MODELING_ROADMAP](MODELING_ROADMAP.md)
