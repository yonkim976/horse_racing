# 학습 전 독립 검토

2026-10-24. 후보 학습·확률·성과를 보지 않은 상태에서 고정 계약, 실제 입력, 구조 preflight와 코드 경계를 검토했다.

**판정: PASS_PRE_TRAIN_REVIEW_NO_FIT.** 설계·입력검증·정적 코드에서 학습 전 차단 사유를 찾지 못했다. 이 검토는 실행 승인이나 후보 성과 판정이 아니며, 별도의 감독관 해시 고정 실행 승인이 필요하다.

입력 artifact는 고정본이다. Parquet SHA-256은 `a1bc9e6b07ab28f384b2c0c104222a5cb297235e4dda645b9c08a376d27e0f72`, source contract는 `a6404068bffa91b9c6f0ab680e1a5f44c09078f229e3d37a481326bf49e98ad4`, source audit는 `92fbbe514426fe3624a9fc916075ec345bc74ab623537c4b7d0d8c5edaa2414d`다. 감독관 `INPUT_VERIFICATION.json`은 SHA `a6a310c79b6da6a88368988517bac3d30d85a4f5b9b8b9f712791c5e2a3c90ec`로 PASS다. 독립 검산은 원문 449문서, 선언 51,917행, 별표 정확 연결 135건, 전체 명단 5,181경주 및 전체 52,155행의 과거 actual 부담 as-of 연결을 확인했다. DB는 read-only/query-only였고 원천 생성 모듈은 import하지 않았다.

실물 입력 validator도 PASS했다. 52,155행·5,206경주 중 현재 선언 부담은 51,917행, 과거 actual 부담은 50,203행, 변화량은 49,988행이다. 번호 비율은 S40 명단과 정확히 일치하는 원문 전체 선언 명단의 confirmed 최대 번호를 분모로 사용하며, 부분 H3 관측 행에서 최대를 다시 계산하지 않는다. 과거 부담은 같은 공식 horse ID의 실제 과거 결과에서 target date−2일까지의 최신 유효값이다. prior 부재 시 값과 계보는 NULL이다. 198개 source-tail 행과 그 밖의 결측은 보존한다. `unconfirmed` roster 행은 값·최대·문서 증거가 NULL인 채 명시적 상태로 남는다.

세 입력은 dated H3 선언의 현재 부담, 직전 유효 actual 부담 대비 변화, 출주번호 비율로 한정된다. 선언 날짜가 실제 최초 공개·정정 시각을 증명하지 않는다. 계약은 `publication_time_status=assumed_from_declaration_date_publication_unverified`, `pre_race_availability_verified=false`로 구분하며, 동시점 가용성은 입증되지 않았다.

비교는 고정 S40 40개 변수에 E의 수치 변수 3개만 더한다. target, vintage별 split, train-only 범주 어휘, seed, 가중치, hyperparameter를 맞춘다. 저장된 S40 점수와 온도는 그대로 재사용하고 S를 재학습·재보정하지 않는다. 새 E의 예산은 최종 3개 모델, LightGBM train 호출 6회, PL 온도 최적화 3회다. 문헌상 S 전용 기존 모델 생성 비용은 3모델·6회·3온도이며 이 실행의 추가 비용은 아니다. 앞선 C+S 결합 연구의 총량과도 구분한다. ledger의 모델 vintage, 전년도 calibration 역할/날짜, 평가 경주 연도를 분리하고 S replay 일치 검사를 E 비교보다 먼저 수행한다.

구조 preflight는 `PASS_STRUCTURAL_PREFLIGHT_NO_FIT_OR_METRICS`이며 SHA-256 `82d3b32887c041cd6a160daf45e4acabc84ad2354f23f617cc7ed1b26fe33fb3`다. 적합·후보확률·성과지표·온도 최적화 플래그는 모두 false다. 평가 코호트는 17,412두·1,779경주·269일이며 7개 승식 중 PLC만 actual 7두 격리 36경주를 제외해 1,743경주다. 보수적 저장량 예상은 27,087,541B/40,000,000B다. 생성 파일은 `experiment/`에 exclusive-create로만 쓴다.

봉인된 S40 manifest SHA는 `86d0153e287f877add1b10c3172471cf5c3aac9f251890423cd7d97f75abba3a`다. 외부 PL 엔진 실제 SHA는 기대 SHA `706b2e94a6b311e5bd9b3706da7df4f6a08117e917d22171fbde63a4d1a3210c`와 일치한다. 감독관은 이 엔진 SHA 및 기존 보호 manifest를 실행 승인에 고정하고, preservation 전후 검사를 수행한다(325개 보호 파일, 60,682,012B PASS 보고). 합성 계약/AST 검사도 PASS했다. 이 검토에서는 원천 행 조회나 후보 학습·확률·성과 계산을 하지 않았다.

한계는 공개 시각 미확인, 결과 기반 S40 명단 유지, 2024–2026 회고 평가 재사용이다. 따라서 구매 시점 가용성, 독립 미래 일반화, 시장가치·ROI, 운영 승격을 주장하지 않는다. 기계 판독 해시와 체크 항목은 `PRE_TRAIN_REVIEW.json`에 기록했다.
