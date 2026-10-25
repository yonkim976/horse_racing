# 적합 전 감독관 코드 검토

상태: PASS. `RANK_STAGE_EXECUTION_APPROVAL.json`의 시간·현재 코드/계획/preflight/원천/규칙 해시를 승인 기준으로 삼는다. 후보 적합 전에 기록했다. 실제 적합·평가 실행자는 GPT-6 Luna xhigh이고 감독관은 실행을 대신하지 않았다.

전체 `experiment/rank_stage.py`의 source selection, metadata 및 T−2 검사, `fit_one_stage`, `probability_maps`, event aggregation, 선택 규칙, baseline pairing, bootstrap, 승인·저장 경로를 읽었다. `probability_maps`는 점수·마번·N만 사용하고 실제 착순은 읽지 않는다. fitting의 실제 이전 착순 제외와 예측의 가상 prefix 제외가 분리돼 있다. 정해진 3두 집합이 아닌 전체 N−1/N−2 분모를 쓴다.

원점수 파일과 메타데이터는 앞선 manifest의 SHA로 확인하며 2019–2023 calibration score만 세 T 적합에 사용한다. 공통 T와 T=1은 이미 고정된 값이다. 기존 baseline 손실은 해시가 일치하는 원장을 경주·승식 key로 1:1 결합한다. 예측 파일이나 DB를 복사하지 않는다. 기존 연구의 28개 원천/모델/운영 참조와 48개 산출물은 시작 때 독립 해시 검사를 통과했다.

세 NLL 목적함수는 같은 경주 표본에서 독립적인 stage별 평균이다. 허용 T 범위는 동일하고 끝점도 비교한다. 실제 예측은 stage softmax를 곱해 전수 순회한다. PLC 미확정 36건을 동일하게 제외하고, categorical/복수당첨 손실·구간 집계·날짜 bootstrap·WIN 보호 비교는 설계와 일치한다. 선택 tolerance는 손실과 원확률을 바꾸지 않는다.

검토 중 보완한 내용은 objective 동점의 작은 T 우선, 역온도 gradient/Hessian와 경계 검사, preflight의 코드/계획 SHA 일치 검사, 상수 자가검사가 아닌 실제 연승 synthetic 사건 검사, 빈 선택변경 원장의 column 보존이다. 모델 후보·분모·목적·게이트를 바꾼 수정은 아니다. 반영 후 synthetic/preflight를 다시 수행했다.

감독관 별도 `math_reference.py`는 prefix 확장과 명시적 잔여집합으로 계산한다. 공통 T 환원, 각 승식·주변확률 합, 상수 이동 불변성, T3가 WIN/EXA/QNL에 영향을 주지 않는 성질, bounds 안의 ordered ticket 순서 반전, 수치 동점의 선택확률 보존을 합성 자료로 검증했다. 그 밖에 실제 NumPy int64 마번을 쓰는 8두 synthetic race로 7승식 지표/선택/runner 출력의 JSON 직렬화까지 검사했다. 감독관이 실행 코드를 불러 쓴 것은 이 합성 코드 검토뿐이며, 실제 결과 검산은 실험 모듈을 가져오지 않는다.

파일 작업은 정적인 연구 경로와 읽기 전용 참조에 한정했다. code-security의 파일 경로 지침을 적용했다. 새로운 결과는 기존 결과가 있으면 중단하며 임시 파일과 저장 예산을 검사한다. 새 후보 실제 확률·온도·손실은 이 검토 시점에 계산되지 않았다. 코드 `ac4c9693a6017539833bb19847a731609541789f27777cf093d7ef3b6837daa6`, 계획 `2e43a53a8f6ea8fcf925b5e54bb36858c0e1b13269b6d3a672964e36ed33aa3c`를 승인했다.
