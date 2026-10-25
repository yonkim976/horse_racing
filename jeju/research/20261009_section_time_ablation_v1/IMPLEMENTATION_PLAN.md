# 구현 및 검토 계획

## 현재 단계

모집단·추가 6열 후보·품질 필터·평가 gate를 [`CONTRACT.md`](CONTRACT.md)에 고정했다. 읽기 전용 source audit과 reviewer의 독립 source 재구성이 통과했고, 6개 section feature를 생성했다. 저장 F1 3개 모형의 replay도 원본 점수·확률·race metrics·6조합과 일치했다. 학습 harness의 실행 전 점검은 split·가중치·train-only vocabulary·budget을 확인했으며 모형 fit·새 보정·후보 성능표는 아직 생성하지 않았다. 조건부 fit 허가는 independent fit-code review와 최종 `before_fit` 보호 해시 검증을 모두 통과한 뒤 단일 3개 연도 실행으로 제한된다.

`audit_source_availability.py`는 `.venv/bin/python`에서 실행한다. 이 코드는 `sys.dont_write_bytecode=True`를 먼저 설정하고 기존 입력을 읽기만 한다. DB는 URI `mode=ro` 및 `query_only=ON`으로 열며 스키마·뷰·인덱스를 수정하지 않는다. 최종 품질 뷰와 각 선택값·상태 구성요소의 SQL 정의 해시를 저장하고, F1에 실제로 연결된 이력 ID와 race 범위만 parameterized 조회한다. raw 원문 필드는 선택하지 않는다. 출력 파일은 현재 폴더 `outputs/`에만 쓴다.

## 진행 순서

1. 원천 감사 코드와 보고서는 F1 52,155행·5,206경주·평가 17,412행·1,779경주, T−2, 2017 warm-up, 제외 ID 3005648, 기존 `last5_same_source_ids` 순서를 전수 대조한다. exact-distance·horse ID·started·cutoff 일치도와 field-specific valid n=0..5 지원을 연도·거리·경력별로 저장한다. 알려진 세 홈페이지 정정시간과 광해청명 G1F NULL 상태는 slot 참조가 없어도 quality-selected 값·상태로 assert한다. 품질 선택 구성요소가 반환한 원천값이 `jeju_race_postrace_sections_quality_2026`의 DDL상 동일 값으로 투영되는지 검증하고, 충돌·미적용·source-changed·NULL·누락 상태를 fail-closed 처리한다.
2. 감독과 독립 검토자는 [`CONTRACT.md`](CONTRACT.md)와 `outputs/source_availability_audit.json`의 상태 정책·S1F 거리별 지원·충돌 race mask·G3F/G1F 패키지를 검토한다. 계약 오류나 source lineage 불일치가 발견되면 해당 입력으로 진행하지 않는다.
3. 계약 검토가 끝나면 저장된 F1 2024~2026 모형을 재로딩해 기존 동일 행 점수·확률·조합·지표를 재현하고 기존 산출물과 비교한다. 이 prefit gate에서 F1 재현이 맞지 않으면 후보 fit을 시작하지 않는다. F1 재현은 재학습하지 않는다.
4. preflight 및 F1 replay 통과 후 별도 감독 승인을 받고 F1S 세 연도 모형을 한 번씩 fit한다. 기존 F1 파라미터·split·seed·가중치·보정 절차와 고정 6열 순서를 사용하고, 결과를 보고 열·filter·경계·모수를 선택하지 않는다.
5. 승인된 fit 뒤에만 확률·최대 6개 조합·주 및 보조 지표, 날짜 paired bootstrap, 하위집단, 2026 운영 공통 467경주 표를 생성한다. 저장 모형과 확률·조합·지표를 독립 재계산하고 입력·코드·모형 해시를 검증한다.

## 신규 산출물

- `audit_source_availability.py`: 읽기 전용 F1 lineage·품질 선택값·상태 지원 감사.
- `outputs/source_availability_audit.json`: 분모, F1 reference/model/code SHA-256, 품질 view SQL 의존, status domains, mask 범위와 유효기록 제외 수 및 preflight 증거.
- `outputs/source_availability_by_group.csv`: 연도·정확 거리·경력 그룹별 F1 대상 수와 각 필드의 유효 slot n 분포.
- `outputs/source_valid_n_distribution.csv`: 연도·정확 거리·경력·구간별 n=0..5 target 지원.
- `outputs/source_slot_section_times.parquet`: 정확거리 실제 슬롯별 quality-selected section 값·상태·valid_time·race mask·적격 여부만 보존하는 감사 추출물. 뒤의 feature builder가 이 산출물만 집계해 6개 후보 열을 만든다.
- `build_candidate_features.py`: 감사 추출물을 F1 target에 다시 연결해 평균 초·필드별 n만 추가하고 기존 24열·행 순서를 보존한다.
- `outputs/features_f1s.parquet`, `outputs/candidate_feature_preflight.json`: 30열 후보 입력과 NULL/n 산술·source lineage 검증.
- `replay_saved_f1.py`, `outputs/f1_saved_model_replay.json`: 저장 F1 점수·확률·경주손실·조합 replay receipt; 재학습과 온도 최적화는 0회.
- `fit_candidate.py`, `outputs/fit_runner_preflight.json`: 고정 후보 runner 및 실행 전 분할·가중치·범주 어휘·호출 예산 확인. `--preflight`는 fit을 실행하지 않고, `--root-approved`는 승인 조건을 모두 만족한 경우에만 학습한다.
- `outputs/prefit_lock.json`: 승인 범위, root 조건부 허가 상태, code/model/source/evidence SHA, DB·등록부·HY_R_FORM 보호 해시와 timestamp.
- `verify_fit_lock.py`: 같은 scoped reference와 4개 보호 파일을 실행 전·후 비교한다.
- 이후 승인 뒤 준비 잠금, 후보 메타데이터·예측·지표·검증 및 `README.md`를 추가한다. 모든 새 파일은 이 날짜별 폴더 안에만 만든다. 중앙 conclusions, DB, 운영 모델·등록부 및 기존 연구 산출물은 변경하지 않는다.

현재 단계의 산출물은 입력 가용성 감사다. F1 saved-model replay와 이후 후보 fit/온도 보정/평가지표 계산은 아직 실행하지 않는다.
