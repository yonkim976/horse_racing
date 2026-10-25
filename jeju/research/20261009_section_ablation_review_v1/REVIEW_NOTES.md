# F1 구간시간 추가 비교 독립 검토 메모

2026-10-09. 후보 계약·구현 완료 전 선행 검토다. 신규 후보 적합·성능 산출과 중앙 conclusions 발행은 하지 않았다. 기존 연구, DB, 운영 자료는 읽기 전용으로 확인했다.

## 기준 입력

- 제주 작업 기준은 `jeju/AGENTS.md`, `jeju/docs/RESTART_PLAN_20260928.md`, `jeju/review_documents/README.md`, `jeju/research/RESEARCH_PUBLICATION_POLICY.md`를 따른다. 관련 구간 원천 근거는 `20261002_section_passing_audit/README.md`, `20261002_section_remaining_review/README.md`, `20261003_unresolved_section_review/README.md` 및 `20261009_time_benchmarks_outliers_v1/README.md`다.
- 비교 기준 F1은 R1 21열에 `previous_finish_relative_rank`, `previous_top3`, `previous_result_status`를 더한 24열이다. 저장 F1 모델 iteration은 2024=92, 2025=200, 2026=200 trees이며, R1 저장 trees도 2024=90, 2025=200, 2026=198이다. 연도별 early-stop 선택 iteration을 보존하므로 200 trees를 모든 저장 모델의 공통값으로 쓰지 않는다. 신규 후보도 기존 최대 200회·early stopping 25회 절차와 연도별 split을 그대로 재현한다. 기존 F1 평가는 2017-01-13~2026-09-19 개발 자료의 2024~2026 후향 구간 17,412출전·1,779경주다.
- 사후 구간 입력은 `jeju_race_postrace_sections_quality_2026`의 선택된 시간·시간 상태를 사용한다. `_raw`/API JSON을 직접 읽어 정정·보류를 우회하지 않는다. 기존 시간 검토 4건 중 홈페이지 정정 3개와 광해청명 G1F 미확정 NULL을 모두 보존한다. `api_positive_unreviewed`는 API 원문 양수이며 홈페이지 확인 완료를 뜻하지 않는다.

## 시간 정의와 지원 범위

| 거리 | S1F 지원 출전/경주 | G3F 지원 출전/경주 | G1F 지원 출전/경주 | 기간 메모 |
|---:|---:|---:|---:|---|
| 800m | 9,149 / 934 | 9,149 / 934 | 9,139 / 933 | 2019+ 마지막 관측 2026-02-06 |
| 900m | 6,957 / 712 | 6,977 / 714 | 6,977 / 714 | 2019+ |
| 1000m | 13,900 / 1,384 | 13,930 / 1,387 | 13,920 / 1,386 | 2019+ |
| 1110m | 9,792 / 976 | 9,792 / 976 | 9,783 / 975 | 2019+ |
| 1200m | 4,822 / 486 | 4,832 / 487 | 4,813 / 485 | 2019+ |
| 1300m | 666 / 70 | 666 / 70 | 666 / 70 | 2024-05-18~2026-09-04; 이전 거리 표본 없음 |
| 1400m | 951 / 100 | 951 / 100 | 951 / 100 | 2020-07-25~2026-09-04 |
| 1610m | 84 / 9 | 84 / 9 | 84 / 9 | 2025-09-13~2026-09-19, `limited_sample` |

수치는 기존 `20261009_time_benchmarks_outliers_v1/reviewed_run02/distance_overview.csv`의 2019+ 품질 선택 기록이다. 800m의 2026-02-06 마지막 관측일은 기존 `analysis_rows.csv`와 `source_rows.parquet`의 실제 최대 날짜에서 확인했다(2006년 표기가 아니다). 2017~2018은 별도 시대 구간이다. 이 원기록 지원표는 해당 시간 연구의 유효 완주 모집단으로, F1의 엄격한 정상 완전편성 52,155출전과 분모가 다르다. 그러므로 아래 숫자를 후보의 과거 창 유효 개수·모델 성능 지원으로 읽지 않는다. 후보 계약의 preflight에서는 같은 F1 target/고정 actual-slot 모집단에서 거리지원·유효수 분포를 별도로 산출해야 한다. 특히 1300m를 2017년부터 지원한다고 쓰지 않고, 1610m는 제한 표본으로 표시한다.

S1F와 코너 시간은 원천 제공 지점 시간이고 G3F·G1F는 종반 구간 시간이다. 이 시간들을 합산하거나 전 거리에서 S1F를 200m/210m로 단정하지 않는다. 1300m에는 사용자가 지정한 출발→2C→S1F 순서를 적용하되, 이는 S1F의 물리적 초반 200m 정의를 확정하지 않는다.

## 계약 심사 조건

1. F1 열·행·분할·가중치·모수·seed·calibration·조합 구성은 그대로 보존하고 후보에는 과거 구간 시간과 각 시간의 유효 관측 수만 추가한다. 구간 순위, 통과조, 예상 전개, 게이트, 기수와 별도 신호를 함께 추가하지 않는다.
2. 후보 시간 창은 target race와 정확히 같은 거리의 최대 최근 5회 **실제 출전 슬롯**이어야 한다. 값이 없거나 해당 구간을 쓰지 않은 경주를 슬롯에서 제거해 유효 5개가 될 때까지 더 과거 기록을 가져오지 않는다. 시간 평균은 이 고정 슬롯 안의 허용된 시간만 평균하고, 유효 수는 같은 슬롯 안의 허용 시간 수다. 유효 수 0이면 평균은 NULL이며 채움값을 넣지 않는다.
3. 과거 이력은 공식 `horse_id`·출전 ID로 연결하고 T−2 경계, horse ID, exact distance, started 상태를 각각 전수 검증한다. 당일·사후 정답 및 다른 말의 이름으로 연결하지 않는다.
4. 사용 시간은 정확한 거리의 품질 선택값에서 `time_seconds > 0`이고 시간 상태가 명시적으로 분석 가능한 건만 받는다. `api_positive_unreviewed`를 `officially_verified`로 재명명하지 않는다. API6/API303 원문, `_raw`, 결측 0은 대체 입력으로 사용하지 않는다.
5. 과거 같은 race+section에서 통과순위 또는 그룹 내부 충돌이 있으면 AGENTS의 정확 계측 제한을 보수적으로 적용한다. 그 경주·지점의 시간은 모든 유효 완주마에서 보류하고 같은 지점 외 시간·그 경주·말 이력 슬롯은 유지한다. 19개 미해결 경주 전체를 제외하거나 다른 구간으로 품질 보류를 전파하지 않는다. 선례상 이전 시간 표는 S1F 60·G1F 47 등 지점 관측을 별도 보류했다.
6. 2026-01-17 5R 광해청명 G1F NULL, 알려진 홈페이지 정정 시간 3개, DB quality-view에서 파생되는 status는 보존한다. 문제 구간 결측을 0, 임의 추정, 원 API 양수로 덮지 않는다.
7. 최소 유효 시간 수가 1인 관측 묶음은 분모 조건일 뿐 성능 gate가 아니다. 점수·모델 결과에 따라 창·거리·유효 수 경계를 바꾸지 않는다. 후향 개발 비교로 보고하며 운영 승격·미래 독립검증을 주장하지 않는다.

## 독립 검증·발행 게이트

후보 코드의 생성 함수와 독립 검증 함수는 공유하지 않는다. reviewer는 원 quality 선택값에서 race/horse/slot ID와 시간 상태를 독립 재구성하고, (현재 제안이 S1F/G3F/G1F 3개 시간과 대응 유효수일 때) 30열 후보의 열 순서 및 F1 24개 보존 열을 검사한다. 저장 F1은 2024/2025/2026별 trees 92/200/200으로 재로딩하고, 신규 후보 3개 최종 모델을 함께 재로딩해 연도별 선택 iteration·temperature, runner probability, race-level losses, calibration, top-5/최대6 조합, paired date bootstrap, 공통 운영 467경주 정합을 별도 재산출한다. fit 이전에 관련 원천·코드·protected SHA를 잠그고 fit 이후 불변을 확인한다. 상세 기준은 후보 계약 검토 후 receipt에 구체화한다.

중앙 결론의 기존 13·14번은 보존한다. 새 단일 중앙 발행은 13·14 번호를 덮지 않고 다음 빈 번호를 확인한 뒤에만 한다. 원 연구 결과·3종 receipt·manifest 동결과 모든 링크를 먼저 대조하고, root의 발행 승인을 받기 전에는 `conclusions/`를 수정하지 않는다.

## 보안·쓰기 범위

연구 및 스크립트는 신규 `jeju/research/20261009_section_ablation_review_v1/` 안에 둔다. 분석 DB는 `mode=ro`와 `PRAGMA query_only=ON`으로 열고, Python 실행은 `.venv/bin/python`과 bytecode 비활성화를 사용한다. 읽은 code-security 규칙은 `rules/sql-injection.md`, `rules/path-traversal.md`, `rules/correctness.md`, `rules/best-practice.md`다. 보안상 검토 스크립트는 경로를 저장소 루트 아래 상수로 고정하고 SQL 데이터 값은 바인딩하며 텍스트 입출력에 UTF-8과 context manager를 쓴다.
