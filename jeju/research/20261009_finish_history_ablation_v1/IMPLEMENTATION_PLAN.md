# 구현·실행 계획

## 현재 게이트 상태

검토용 계약을 고정했다. root의 검토·승인 전에는 학습을 실행하지 않는다. 준비, 입력 전수 검증, 코드 작성은 계속한다.

## 이미 끝낸 입력 감사

- 참조 `source_snapshot.parquet`: 92,513행·9,494경주, 2002-07-06~2026-09-19. 물려받은 `started` 조건은 착순 1..89 또는 91/92이며 90,428행·9,347경주다. started 경주 중 N≥2 및 착순이 고유한 1..N인 완결 경주는 9,027개, 나머지 320개(그중 N=1은 32개)다. 별도 147개 경주는 source rows는 있지만 started 행이 0개다. 다른 원문 상태코드는 실제 시작/취소로 따로 재분류하지 않는다.
- R1 모집단 52,155행 중 직전 실제출전 ID가 있는 50,209개 링크행은 모두 source에 존재하며 horse ID 일치, `started=True`, history cutoff(T−2) 이하를 확인했다. 링크가 가리키는 과거 경주는 5,901개로 distinct이며, 그중 불완전 경주는 distinct 93개, 현재 출전에서의 참조행은 745개다.
- R1 `last5_same_source_ids`는 178,459개 슬롯 참조를 가진다. 모든 참조가 source에 존재하고 현재 official horse ID와 일치하며 동일 거리·started 상태·T−2 이하를 만족했다. 출전당 최대 슬롯 5개다. 이력은 최대 5개 실제 출전 슬롯을 유지하므로 비정상 착순을 0/최하위로 바꾸지 않는다.
- 개별 정상 착순은 과거 경주 전체의 착순 완결성과 별도로 `1..N` 범위에서 직접 확인한다. 따라서 경주 전체가 DNF 등으로 불완전해도 해당 말의 유효 1~3위/4위+ 정보는 F1/F2의 개별 결과로 남을 수 있다. 경주 수준 완결성이 요구되는 직전 상대순위만 NULL이다.

이 감사는 데이터 정의와 준비를 확인한 것이며 새 모형 fit/성능 결과를 포함하지 않는다.

## 구현 순서

1. `prepare.py`: 이전 R1 계약, 피처, source, 모델 outputs의 해시와 보호 파일을 잠그고 열/모집단을 확인한다. R1 피처 행 순서를 유지해 F1/F2 6열을 추가하고 lineage 표본·결측 표·사례를 쓴다. 기존 경주/말 IDs와 분할 행이 같은지 확인한다.
2. `verify.py preflight`: 정책 정의를 독립적으로 재계산한다. 실제 starter N은 과거 source 전체 `started=True` 집합으로 만들고 non-start codes 94/95/99 제외를 확인한다. 정상순위 경주 조건, 개별 유효 착순, 비정상·미관측 NULL, 세대가구/거리/시간 cutoff 전수 검증을 수행한다. synthetic 사례는 완전순위, DNF 섞임, duplicate/누락/범위 밖 순위, 이전 기록 없음, 비정상 창 슬롯, Top3 직접 관측을 포함한다.
3. `run.py replay`: 기존 세 R1 모형을 재로딩하고 원래 vocabulary, 동일 2024~2026 평가 행에 적용해 보존 점수·확률·6조합·지표를 독립 재현한다. 이 절차에서 R1을 재학습하지 않는다.
4. root 승인 후 `run.py fit`: F1/F2 최종 모형 6개를 세 연도씩 만든다. 각 모형의 조기종료 초기 학습과 refit을 합쳐 LightGBM train 호출 12회, 온도 보정 최적화 6회를 수행한다. 기존 split/파라미터/seed/가중치/보정/조합 알고리즘을 읽기 전용 R1 계약에서 그대로 가져온다. 결과를 본 뒤 열·경계·모수를 변경하거나 후보를 추가하지 않는다.
5. 점수·확률·조합·하위군 및 2,000회 경주일 paired bootstrap을 계산한다. 운영 비교는 기존 467경주 공통 집합만 사용한다. 소표본을 분리 표시하고 2026 부분연도를 밝힌다.
6. `verify.py final`: 저장 모델 재로딩, R1 출력 일치, F1/F2 확률 및 조합·지표/CI 재계산과 전체 해시 불변을 검증한다. 검증 통과 뒤 날짜별 `README.md`를 작성한다. 중앙 결론 파일은 수정하지 않는다.

## 예정 파일과 경계

이 폴더에 `CONTRACT.md`, 본 계획, `prepare.py`, `run.py`, `verify.py`, `README.md`, 그리고 새 `outputs/`만 둔다. 읽기 전용 원천은 R1 연구와 profile baseline 경로를 참조한다. DB·운영 등록부·HY_R_FORM·기존 연구 결과를 덮어쓰지 않는다. SQLite나 네트워크 접근은 추가하지 않는다.

`verify.py`는 다음 JSON 증거를 생성한다.

- `preflight_verification.json`: 보호·참조 해시, 원천 row/race 및 lineage 검사 건수(전체 및 distinct), started rank완결성·N=1 수, feature contract 21/24/27, synthetic check 목록, R1 replay 가능성.
- `final_verification.json`: 최종 후보 모형 6개/LightGBM train 호출 12회/온도 보정 6회 각각의 기록, 저장 예측/확률과 독립 재계산 일치, 경주별 확률합·조합 산술, R1 기준 재현, 지표·bootstrap 재계산, 보호 해시 불변 및 `production_changed=false`, `database_changed=false`.

`CONTRACT.md` 또는 구현 중 정의 오류·중복·불충분이 발견되면 해당 구현에 의존하는 fit을 멈추고 구체적인 원천행·정의 문제를 root에게 먼저 전달한다.
