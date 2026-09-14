# E8-A R1–R4 보완 — 독립 재검증 제출

상태: **합성 offline v2 보완 완료, 실제 수집·tree fit·실제 확률 발행·성능 계산 0회, `not_activated`.** 기존 E8-A attempt4 SQLite/raw/replay/manifest와 코드·runner·테스트·보고서는 수정하지 않았다. E1, H1/E3–E7 및 운영 DB/schema/registry/발행/UI/scheduler도 변경하지 않았다. 새 경로만 추가했다. 실제 결과나 2026-06-01 이후 holdout을 조회하지 않았다.

## 독립 반례 전·후

| 지적 | 수정 전 독립 재현 | v2 결과와 근거 |
| --- | --- | --- |
| R1 기록/완료 시각 | `seal_field` 사전 clock은 cutoff, field append는 cutoff+1인데 `sealed_at_ms=cutoff`로 승인 | field를 먼저 `pending`으로 COMMIT하고 **그 반환 후 측정한 `field_commit_ack_ms`**로 admission을 결정한다. 재현에서 ack=cutoff+2, `late_ineligible/field_commit_after_cutoff`; 승인 field는 없다. 진입→insert 및 insert→commit/ack 사이 clock 전진, commit 전 실패·재시작도 테스트했다. pending의 `policy_cutoff_at_ms`는 완료시각으로 표시하지 않는다. |
| R2 옛 observation 선택 | cutoff−5의 유효한 1두 정정을 무시하고 cutoff−10의 2두 field 승인 | 같은 SQLite `BEGIN IMMEDIATE` 안에서 race/source별 cutoff까지 ack된 최신 유효 상태를 선택한다. 옛 hash는 `superseded`로 거부하고 1두 정정 hash를 선택한 새 field 키는 `(7,11)` 하나다. 최신 partial/ambiguous, 다른 원천 충돌, 동시각 상충, 일정 변경은 실패; 미래 effective는 보류 근거로 남긴다. 선택→insert 사이 신규 관측이 commit될 수 없음도 동시성 반례로 확인했다. |
| R3 사후 신규 snapshot/prediction | 출발+1ms에 새 snapshot과 prediction이 정상 합성 예측처럼 생성 | 정보 cutoff와 snapshot/prediction commit deadline을 T−30으로 같게 고정한다. 재현의 신규 snapshot은 `new snapshot after cutoff`로 거부되어 pending 0건이다. 늦은 신규 model prediction도 거부하고, 이미 적시에 admission된 동일 payload의 재시도만 원래 hash를 반환한다. prediction commit ack가 deadline을 넘은 경우 `late_ineligible`도 검사했다. |
| R4 무근거 feature | 무관한 race 999, 가짜 계산 버전, 조기 declared available, 값 `999/−999` 승인 | 등록된 `synthetic_horse_number_pct_v1`만 target field 원문 SHA256을 다시 확인·파싱해 키별 `horse_number / declared_count`를 계산한다. 무관한 dependency, 미등록 버전, 누락된 ready hash, source ack/계산 완료보다 빠른 available, 수정된 키·값·result hash를 거부한다. 결합 독립 반례는 `unregistered synthetic calculator`로 중단되며 각 하위 조건도 별도 테스트한다. 다른 경주 원천 사용 자체를 보편적으로 금지하지 않는다. |

상태·시간·선택·계산 계약의 기계적 정의는 [E8-A v2 계약](CONFIRMED_STARTER_E8A_V2_CONTRACT_2026-09-13.md)에 고정했다. 합성 parser의 `declared_count`는 실제 KRA pagination의 완전성 증명이 아니다. `available_at_ms`는 observation COMMIT 이후의 ack이며, field/snapshot/prediction의 완료 인정도 각각 자신의 pending transaction COMMIT 이후 측정한 ack에 따른다. admission marker가 없으면 재시작 후에도 미승인이다. 허용 지연은 0ms로 유지했다. 로컬 시계·해시 사슬은 공인시각이나 악의적 전체 재작성 방지가 아니다.

## 실행·검증

- 최종 실행 명령: 프로젝트 루트에서 `.venv/bin/python -m scripts.run_confirmed_starter_e8a_v2`. 재현 소스 경로와 선행 독립 반례 JSON 경로는 새 `replay.json`에 기록했다. 기존 첫 v2 시도 경로도 덮어쓰지 않았다.
- 최종 산출물: `data/experiments/confirmed_starter_e8a_v2_20260913_attempt2/`의 5개 격리 synthetic case 원장/raw, `replay.json`, `artifact_manifest.json`. 승인된 합성 field→등록 feature snapshot→합성 prediction→사후 outcome의 해시 연결도 별도 case에 저장했다. 실제 모델/확률은 없다.
- 보존 경로 **16개**의 전후 SHA256이 동일하다. 여기에는 attempt4의 SQLite/raw/replay/manifest 전체가 포함된다. 신규 v2 코드·runner·테스트·계약 문서와 독립 검증 JSON **5개** 및 출력 **14개**의 hash가 manifest와 일치한다. 이 manifest는 기존 기록을 덮어쓰지 않는다.
- 새 v2 합성 회귀 **11개**를 포함해 `.venv/bin/pytest -q`와 `.venv/bin/python -m pytest -q`는 각각 **605 passed, 2 warnings**다. 경고는 기존 Starlette deprecation과 Polars asof sortedness다. 관련 3개 Python 파일 Ruff check/format은 통과했다.
- 전체 `ruff check .`는 범위 밖 **6개 파일 26건**: `scripts/analysis_finish_time_quality.py` 18, `scripts/research_betting_2025_2026.py` 4, `src/horse_racing/analysis/baselines.py` 1, `src/horse_racing/analysis/features/ability.py` 1, `tests/test_race_day.py` 1, `tests/test_segment_correction.py` 1이다. 전체 `ruff format --check .`는 기존/범위 밖 102개 파일이 미정렬(242개 통과)이라고 보고했으며, Markdown 코드블록도 검사 대상이다. 전체 `git diff --check`는 기존 dirty `src/horse_racing/web/racecourse.py:347` EOF 빈 줄 1건만 지적했다. 범위 밖 파일은 수정하지 않았다.

## 남은 한계·독립 재검증 요청

등록 계산은 한 개의 합성 field-derived feature일 뿐 실제 136열의 PIT/계산 적격성을 인정하지 않는다. 다른 경주의 자료가 정당한 의존성이 되는 새 계산기는 이번에 등록하지 않았다. 실제 원천 수집·pagination·clock skew·운영 scheduler, DNS 정산, 배당 관측은 미검증/미연결이다. 본 결과는 합성 경계에서 네 반례를 거부했다는 증거이며 실제 미래 누수 부재나 예측 성능의 증거가 아니다.

독립 검증 담당자는 attempt4 및 상위 보존 hash, v2 pending→commit ack→admission의 사건 순서, R2 최신 선택과 같은 transaction 내 insert, 새 snapshot/prediction의 cutoff gate, raw 재파싱 결과 hash, 동시성/재시작 실패 규칙을 새 runner·테스트와 무관한 산식으로 확인해 달라. 운영 승격이나 다음 연구 단계는 진행하지 않았다.
