# E7-A 최근 출발별 이력 표현 감사 — 독립 검증 제출

상태: **감사 산출물 제출, 모델 학습 0회·성능 평가 0회·운영 변경 없음.** 봉인 H1 A 전체 15,579행·1,488경주를 분모로 최근 전 경마장 실제 출발 3개 슬롯의 후보 수치 12열을 만들었다. 중량 묶음은 승격하지 않았고 기준 136열·라벨·A field는 그대로 보존했다. 이번 결과는 독립 검증 전 실행 feature 확정이나 예측력 주장이 아니다.

## 테스트 실행 회귀

E6-B 검증자가 발견한 console pytest의 `scripts` import 오류를 `pyproject.toml`의 `[tool.pytest.ini_options]`에 `pythonpath = ["."]` 한 줄만 추가해 해결했다. 봉인 E6-B 파일은 수정하지 않았다.

| 실행 | 결과 |
| --- | --- |
| `.venv/bin/pytest -q` | **564 passed, 2 warnings** |
| `.venv/bin/python -m pytest -q` | **564 passed, 2 warnings** |
| E7-A 관련 test | **10 passed** |
| E7-A 관련 Ruff check / format check | 통과 |

두 warning은 기존 Starlette TestClient deprecation 및 Polars asof sortedness 경고다. 저장소 전체 `git diff --check`는 E7-A 범위 밖의 기존 dirty `src/horse_racing/web/racecourse.py:347` EOF 공백을 지적한다. 해당 사용자 변경은 건드리지 않았다.

## 입력·슬롯·관측 계약

읽기 전용 SQLite 조회는 event date를 SQL에서 `2026-05-31` 이하이면서 최대 target date보다 엄격히 이전으로 제한했다. 실제 읽은 이력은 **2015-01-02~2026-05-30**, 전체 출전행 280,879개, 정상완주 speed 원천 279,623개다. 이 2015-01-02 시작은 DB left truncation이지 생애 첫 출발 보증이 아니다. 각 target별로는 다시 `prior_date < target_date`를 적용했다. 선택된 과거 출발 고유키는 17,224개·2,294경주이고, 해당 경주 구간 원천 132,744행을 읽었다. 새 수집은 없었고 사후 저장 원천의 역사적 T-30 공개 가능성은 확인되지 않았다.

정상완주·출발 후 DNF·실격은 슬롯을 차지한다. 확정 미출주는 제외한다. 같은 날 복수 후보 또는 미확정 출발이 나타나면 그 슬롯 및 이후 오래된 슬롯을 null로 격리하고 이전 정상완주로 대체하지 않는다. 실제 H1 대상에서는 이러한 최신/2·3번째 슬롯 순서 모호성은 0건이었다. 합성 반례에서는 양쪽을 차단했다. 실제 출발 날짜가 확인되면 구간·speed가 null이어도 양수 `days_ago`를 계산한다.

구간은 승인된 `canonicalize_sections`의 명시적 `time_basis`, `source_kind`, 거리 및 물리적 측정지점 검사를 따른다. 상대지수는 같은 **과거 경주**의 정상완주·변환 유효 관측이 3개 이상일 때 `100 × ln(중앙값/개별 시간)`을 계산해 [-20,20]으로 clip한다. target 경주의 결과나 완주집합은 분모에 들어가지 않는다. 부경 NULL `time_basis`를 closing으로 추정하지 않았다. speed는 기존 `performance_observations`의 과거 경주 자체 수치이며, par는 해당 경주일보다 이전 730일의 동일 경마장·거리·주로 12경주 또는 동일 경마장·거리 20경주를 요구한다. 기존 historical day/meet variant는 그 하루가 target보다 앞선 경우에만 사용한다. 빈 par를 전기간 평균으로 메우지 않았다.

| 슬롯 | 확인 실제 출발 | S1F/last200 유효(각각) | speed 유효 | days 유효 | 이전 부경 출발 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 14,753 | 14,563 | 14,702 | 14,753 | 167 |
| 2 | 13,909 | 13,696 | 13,855 | 13,909 | 195 |
| 3 | 13,058 | 12,873 | 13,009 | 13,058 | 174 |

각 구간 열의 null 원인 중 **부경 원천 `time_basis` 미확정**은 슬롯별 167/195/174건이다. 해당 과거 출발은 슬롯에 그대로 남고 구간 수치만 null이다. 과거 DNF/실격 등 완주 관측 불가는 23/18/11건, speed par 불가는 28/36/38건이다. 슬롯 1의 이력 범위 내 이전 DB 출전행 없음은 815건, 이전 DB 행은 있지만 확인된 실제 출발이 없는 경우 11건이다. 슬롯별 전체 원인·경마장 분포는 `coverage.json`에 기록했다. E7-A 대상의 DNF target 47행과 실격 target 1행도 제거하지 않았으며 별도 12열 coverage를 저장했다.

기존 136열 대비 전체 키에 대한 `null↔값`까지 포함한 동등률 95% 이상 진단은 두 쌍에서 발견됐다. `sequence_start1_speed_figure` 대 `speed_figure_last` **99.6791%**, `sequence_start1_days_ago` 대 `days_since_last_race` **99.8524%**다. 유한 숫자는 절대오차 `1e-10` 이내만 같다고 보며 NaN/Inf는 무효다. 이 중복은 가설의 식별력 한계로 보고하되 성능을 보지 않고 열을 임의 제거·교체하지 않았다. 실행 후보 12열 최종 봉인은 독립 검증 뒤로 미룬다.

## 전수·반례 검증

- H1 15,579키와 새 feature는 정확히 1:1; evidence는 정확히 46,737행(키당 3슬롯)이다. 누락·추가·중복·조용한 inner join 축소를 거부한다.
- 구현 슬롯 선택과 별도 전 행·날짜 열거 방식으로 **46,737슬롯**의 키·날짜·경과일을 대조했고 불일치 0이다. canonical 상대지수는 독립 Python 중앙값·로그·clip으로 **48,040셀**을 대조해 불일치 0이다. **26,336개 경주**의 par 모집단·같은 날 variant를 별도 날짜순 집계로 재구성해 기존 산식과 불일치 0이었다. 선택된 정상완주 17,201개 중 speed figure 17,154개는 출발 시간·거리·adjusted par·tail censor 산식을 별도 계산해 불일치 0이다.
- 실제 함수 경로를 호출한 합성 테스트는 target 결과행 삭제/상태 교환과 당일·미래 행 추가, 다중 target 및 이력 역순, DNF 슬롯의 null 유지, 부경 출발 뒤 서울 target, NULL `time_basis`와 물리적 변환 불가, 동일일 복수·미확정 출발, 과거 관측 변경 시 이후 target만 변화, 미래 결과 변경 시 과거 par/day variant 불변을 검사했다. 모든 target의 과거 결과까지 바꾸고 predictor 전체 불변을 요구하는 부적절한 테스트는 두지 않았다.
- H1, E3~E6 보존 경로와 E6-B 출력 등 **102개 경로**의 전후 SHA256이 일치한다. 읽기 전용 DB 파일의 전후 SHA256도 일치하고, 최종 E7-A 출력 5개 파일의 manifest hash가 모두 일치한다.

## 산출물·한계·검증 요청

최종 제출 경로는 `data/experiments/confirmed_starter_e7a_20260913_attempt4/`다. `sequence_features.parquet`에는 키+12수치열만, `sequence_evidence.parquet`에는 슬롯키·경마장·날짜·상태·구간 원천 basis/kind·유효 관측수·par/variant/원인 metadata를 둔다. `source_manifest.json`, `independent_validation.json`, `coverage.json`, `artifact_manifest.json`을 함께 제공한다. 먼저 생성한 기본 경로와 attempt2·attempt3은 null 원인 분류·보존 hash·독립 par/variant 검사를 강화하기 전의 시도 증거로 남기고 덮어쓰지 않았다. attempt3과 최종 attempt4의 15,579행×14열 feature frame은 값까지 정확히 동일하다. 후속 비교는 `docs/CONFIRMED_STARTER_E7B_PROTOCOL_DRAFT_2026-09-13.md`에 **실행 금지 초안**으로 기록했다.

독립 검증 담당자는 부경 NULL basis 536개 슬롯·원천 식별, speed adjusted par의 과거 날짜·day variant, 12열 중 첫 슬롯의 높은 기존 열 중복, 모호 출발 격리와 target별 이전 날짜 제한, H1/기존 artifact/DB hash를 다시 확인해야 한다. 사후 수집 원천을 역사적 PIT 통과로 해석하지 않으며 2015년 이전 이력은 관측되지 않는다. 후보 묶음이 좋아지더라도 순서 정보만의 순수 효과나 개별 열의 인과효과를 주장할 수 없다. 이번에는 새로운 경마 모델 적합·성능 평가·운영 승격을 하지 않았다.
