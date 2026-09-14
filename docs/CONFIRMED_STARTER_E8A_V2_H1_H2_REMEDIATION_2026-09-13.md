# E8-A v2 H1/H2 시간 계약 보완 — 독립 재검증 제출

상태: **H1/H2 합성 반례 차단, `not_activated`.** 새 시간 검사만 `src/horse_racing/analysis/confirmed_starter_e8a_v2_h1h2.py`에 분리했다. v2 attempt2, 기존 v2 모듈·runner·테스트·계약 및 그 이전 연구/운영 경로는 수정하지 않았다. 실제 수집·tree fit·확률 발행·성능 평가·운영 연결·DB 변경은 모두 0회다. 실제 원천/holdout 결과를 조회하지 않았다.

| 반례 | 독립 검증의 수정 전 | 새 버전의 수정 후 |
| --- | --- | --- |
| H1 field `[cutoff, cutoff+1, cutoff, cutoff+2]` | pending `created_ms=cutoff+1`인데 payload ack=cutoff로 `accepted` | ack 샘플에서 `clock regressed`로 거부. pending만 남고 admission **0건**; 재시작해도 미승인. |
| H1 observation/snapshot/prediction ack 역행 | 단계별 payload ack 하한 누락 | 각 단계에서 insert보다 작은 ack를 거부하고 admission을 만들지 않는다. 역행 후 clock을 다시 전진시켜도 해당 시도는 승인되지 않는다. commit 지연은 `late_ineligible`, marker 실패는 pending 미승인으로 유지한다. |
| H2 정상 source·값·dependency의 `available_at_ms=cutoff+1`/출발+1ms | snapshot과 prediction 모두 `accepted` | `declared feature availability exceeds cutoff`로 snapshot pending 전에 거부, 새 prediction도 없음. cutoff equal은 승인, cutoff−1은 이번 정확시각 field 정책에서 계산 완료보다 빠르므로 하한 위반으로 거부한다. 선언값을 clamp하지 않는다. |

모든 저장기 clock 호출은 직전 샘플보다 작을 수 없고 재시작 시에는 마지막 journal 시각보다 작을 수 없다. admission payload ack는 observation의 parsed/insert, field의 선택 원천 ack/insert, snapshot의 원천 ack·계산 완료·insert, prediction의 선행 snapshot ack·insert 이상인지 개별 확인한다. 승인 ack는 기존 cutoff deadline 이하이어야 한다. 구체적인 사건 순서와 경계는 [H1/H2 계약](CONFIRMED_STARTER_E8A_V2_H1_H2_CONTRACT_2026-09-13.md)에 고정했다. 로컬 clock을 공인시각으로 주장하지 않는다.

기존 R1 cutoff 후 완료, R2 최신 정정 선택, R3 늦은 신규 생성, R4 원문과 다른 합성 feature 값의 회귀를 다시 확인했다. 적시에 승인한 동일 prediction payload를 사후 재시도하면 원래 hash를 반환하지만 신규 model 식별자의 늦은 prediction은 거부한다. 정상 합성 cutoff equal 경로의 snapshot/prediction admission은 `accepted`다.

새 `tests/test_confirmed_starter_e8a_v2_h1h2.py`의 **6개** 합성 테스트가 H1 단계별 ack 역행, H2 하한/equal/상한, 기존 R1–R4와 정상 재시도를 검사한다. `.venv/bin/pytest -q`와 `.venv/bin/python -m pytest -q`는 각각 **611 passed, 2 warnings**다. 경고는 기존 Starlette deprecation과 Polars asof sortedness다. 관련 3개 Python 파일 Ruff check/format은 통과했다. 전체 `git diff --check`의 범위 밖 기존 `src/horse_racing/web/racecourse.py:347` EOF 빈 줄 1건은 건드리지 않았다.

재현 명령은 프로젝트 루트에서 `.venv/bin/python -m scripts.run_confirmed_starter_e8a_v2_h1h2`이다. 최종 격리 폴더 `data/experiments/confirmed_starter_e8a_v2_h1h2_20260913/`의 `replay.json`은 수정 전 독립 검증 값과 새 거부 결과·저장소 내 재현 소스 경로를 함께 기록한다. `artifact_manifest.json`은 기존 **27개** 경로의 전후 SHA256 동일, 신규 source/계약/독립 검증 JSON **5개** 및 출력 **13개**의 hash 일치를 기록한다. 기존 산출물을 덮어쓰지 않았다.

실제 clock skew·KRA 완전성·미래 데이터 적격·실전 예측 성능은 이번 합성 보완의 검증 대상이 아니다. 독립 검증 담당자는 pending/ack/admission 순서와 각 단계 ack 하한·cutoff 상한, H2 선언값 보존, 기존 v2/운영 경로 해시 불변을 우선 재검사해 달라. 다음 연구·수집 활성화는 진행하지 않는다.
