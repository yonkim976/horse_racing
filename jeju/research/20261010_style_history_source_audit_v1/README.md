# 제주 과거 통과 위치 이력 원천 감사

2026-10-10에 저장된 F1 기준선의 동거리 최근 실제 출전 슬롯에서 API4 개별 통과순위와 API303 통과조의 정의·지원·시점 순서를 읽기 전용으로 점검했다. 이 작업은 원천 지원 감사이며 새 feature의 학습, 성능 비교, 예측 또는 공개를 하지 않았다. F1 모집단은 경주 결과를 확인한 뒤 선택된 사후 코호트이므로, 이 수치는 공개 시각에 사용할 수 있었음을 입증하지 않는다.

## 감사 결과

고정된 과거창은 F1 저장 이력 그대로다. target 행 52,155개, 같은 거리의 마지막 5회 실제 출전 슬롯 178,459개, 서로 다른 원천 출전 50,491개를 확인했다. 6,269개 원천 경주키에서 `source_snapshot.parquet`의 **경주 전체 행** 62,709개를 `race_result_rows`의 동일 경주 전체와 대조했다. 상속된 출전 규칙(`finish_position` 1–89 또는 91/92)으로 세면 두 모집단 모두 출전 62,248개였고, 경주별 N 차이·출전 ID 차이·말 ID/마번 차이는 없었다. 모든 출전 ID·말 ID·마번은 채워져 있었고 중복은 0이었다. 앞선 부분 roster 추정은 참조 슬롯 ID만으로 경주 분모를 만든 오류였으며 이 감사에서는 폐기했다.

각 원천 경주·지점에서 API4 순위는 전체 출전 집합의 정확한 `1..N` 순열일 때만 순위 정규화에 쓴다. 순위 자체의 완전 순열과 API303 상태 gate를 별도 기록했다. API303 `api_group_unreviewed`와 `api_group_unavailable`은 gate상 허용하지만, 충돌·미적용·원천변경·행 누락·알 수 없는 상태는 해당 경주·지점 전체를 보류한다. `api_group_unavailable`은 내부 충돌과 다른 상태다. `api_group_unreviewed`는 공식 홈페이지 대조를 뜻하지 않는다. 괄호로 묶인 통과조 구성원은 같은 순위 구간만 가지며 괄호 내부 순서를 만들지 않는다. API303 구간 파싱은 진단용이며 API4 순위를 복구하거나 대체하지 않는다.

| 지점 | API4 전체 출전 순열 통과 경주 | 최종 race-point 통과 경주 | API4 순위 상태(전체 출전) |
|---|---:|---:|---|
| S1F | 6,243 | 6,243 | 미검토 양수 62,207; 홈페이지 정정 7; 결측/비양수 20; 내부 충돌 14 |
| 4C | 6,242 | 6,242 | 미검토 양수 62,208; 결측/비양수 22; 내부 충돌 18 |
| G1F | 6,241 | 6,241 | 미검토 양수 62,196; 홈페이지 정정 7; 결측/비양수 22; 내부 충돌 23 |

API303 상태는 S1F 6,263개 미검토·6개 내부 충돌, 4C 6,264개 미검토·5개 내부 충돌, G1F 6,263개 미검토·6개 내부 충돌이었다. 이번 원천경주에는 명시적 `api_group_unavailable` 행이 없었다. 세 지점의 개별 API4/API303 구간 비교에서 불일치 예시는 0건이었다. 전체 원천 품질 검토에서 알려진 API4 충돌 70개와 API303 충돌 20개를 원래 품질 상태대로 보존한다.

품질 선택 시간의 거리별 consistency screen에서는 유효 쌍에서 S1F 시각이 4C 시각보다 앞섰고, 4C 시각은 `완주시간 − G1F 종반 1F 구간시간`으로 계산한 추정 마지막 1F 시작 시각보다 앞섰다. 검토 가능한 쌍은 거리별로 각각 800m 12,273, 900m 8,161, 1000m 14,190, 1110m 9,821, 1200m 4,713/4,712, 1300m 464, 1400m 790, 1610m 48개였고, 관측된 역전·동률은 0건이다. 두 번째 비교는 공식적으로 기록된 지점 시각이 아니라 종반구간 시간을 빼서 만든 시간 순서 점검값이다. 물리적 거리나 트랙 좌표를 입증하지 않으며 feature 값이나 추가 결측 gate로 쓰지 않는다.

`S1F`는 원천의 지점명으로만 쓴다. 전 거리에서 200m/210m 지점이라고 가정하지 않는다. 1300m에서는 사용자가 지정한 `출발 → 2C → S1F` 순서를 유지한다. 기존 1300m S1F/2C 보류는 그 사용자 계약보다 앞선 문서이므로 새 보류로 자동 복사하지 않았다. 지점 시간 일관성은 위 거리별 표본에서 확인했지만 물리적 계측 정의를 확정하지 않는다.

순서 근거는 기존 [통과조 분석 계획](../20261008_passing_group_running_style_v1/PLAN.md)의 S1F→4C 및 4C→G1F 기술 순서, [구간 통과 감사](../20261002_section_passing_audit/README.md), 그리고 현재 기준과 이전 보류의 차이를 검토한 [독립 구간 감사](../20261009_section_ablation_review_v1/independent_outputs/independent_source_availability_receipt.json)에 한정했다. 이는 라벨 순서의 일관성 근거이며 물리적 거리/좌표 검증을 대신하지 않는다.

## 제안할 최소 6개 열

모든 순위는 실제 출전수 `N`에 대해 `r=(order−1)/(N−1)`로 바꾼다. `r=0`은 가장 앞, `r=1`은 가장 뒤다. 평균은 `source_snapshot.valid_time=True`이며 API4 전체 순열과 API303 상태 gate를 통과한 **고정된 5개 실제 슬롯**에서만 계산한다. 전이값은 같은 슬롯의 두 지점이 모두 유효할 때만 짝지으며 양수는 해당 지점 사이 상대순위가 앞쪽으로 이동했음을 뜻한다. n이 0이면 평균은 NULL이다. 무효 슬롯 때문에 더 오래된 기록을 끌어오지 않는다.

| feature 이름 | 원천 계산 | 해석 한계 |
|---|---|---|
| `hist_s1f_relpos_mean5` / `hist_s1f_relpos_n` | S1F `r` 평균과 유효 슬롯 수 | 초반 상대 위치 기록; 선행 의도·물리적 200m 위치 아님 |
| `hist_s1f_to_c4_forward_mean5` / `hist_s1f_to_c4_pair_n` | 같은 슬롯의 `r_S1F − r_4C` 평균과 짝 수 | S1F에서 4C까지 상대순위 변화; 속력·체력 원인 아님 |
| `hist_c4_to_g1f_forward_mean5` / `hist_c4_to_g1f_pair_n` | 같은 슬롯의 `r_4C − r_G1F` 평균과 짝 수 | 4C에서 G1F까지 상대순위 변화; 결승 진출·최종착순 아님 |

최종 유효 슬롯은 S1F 177,688개, S1F→4C 177,450쌍, 4C→G1F 177,498쌍이었다. 이 수치는 feature 성능이나 채택 근거가 아니라 원천 지원량이다. 최근 전체기간 선입·추입 분류, 전개·기수·게이트 신호, 조건 가점, 최종 착순 집계를 추가하지 않았다.

## 고정 캐시 및 재현성

모델 단계에서는 quality view를 다시 해석하지 않고 다음 캐시를 read-only로 사용한다.

- [`api4_full_started_point_quality_cache.parquet`](api4_full_started_point_quality_cache.parquet): 전체 출전×세 지점 186,744행. API4 상태/선택순위, 전체 순열, API303 상태 gate 및 parser 진단을 분리한다.
- [`actual_slot_point_eligibility.parquet`](actual_slot_point_eligibility.parquet): 기존 실제 이력 슬롯 178,459행. target/source ID, `slot_position`, source 말·거리, full `N`, 지점별 순위·상태·gate, source `valid_time`, 짝별 상대변화를 담는다.
- 거리·연도별 target 슬롯 지원: [`support_by_distance_year.csv`](support_by_distance_year.csv)
- 원천 거리·지점별 순열 지원: [`point_support_by_distance.csv`](point_support_by_distance.csv), 경주별 상세 [`race_point_quality_support.csv`](race_point_quality_support.csv)
- API303 상태·구간 지원: [`api303_group_support_by_distance.csv`](api303_group_support_by_distance.csv)
- 거리별 시간 순서 consistency: [`point_time_chronology_by_distance.csv`](point_time_chronology_by_distance.csv)
- 경주별 전체 roster 대조: [`full_roster_reconciliation_by_race.csv`](full_roster_reconciliation_by_race.csv)
- API4/API303 불일치 예시: [`cross_source_interval_examples.csv`](cross_source_interval_examples.csv) (불일치 0건으로 빈 파일)

[`source_audit.json`](source_audit.json)은 캐시·표의 SHA-256/바이트 수, 직접 입력·코드의 scoped hash, API4/API303 quality-view DDL 해시, SQLite `mode=ro`/`query_only=ON`, 현재 DB 전체 재해시와 기존 lock 일치 여부를 기록한다. API4 원천은 `jeju_race_section_order_values → jeju_race_section_order_quality_values → jeju_race_section_order_quality`; 그룹 원천은 `jeju_race_section_group_quality_values → jeju_race_section_group_quality` 경로를 거쳐 `jeju_race_postrace_sections_quality_2026`에 연결된다. 하위 값은 동일 품질 구성요소에서 바인딩 파라미터로 조회했고 품질 view 전체행 스캔은 하지 않았다.

폴더 내 파일들의 재검증용 SHA-256/바이트 목록은 [`artifact_manifest.json`](artifact_manifest.json)에 있다. manifest는 자기 자신을 해시하지 않는다.

이 감사는 저장된 F1 코호트와 과거 T−2 이력을 사후 연결한다. 전체 기간 말 프로필이나 현재·미래 이력은 사용하지 않는다. 점수 적합·성능 산출이 없으므로 위 6개 열은 비교 후보일 뿐 운영 입력 또는 공개 결론으로 승인되지 않았다.
