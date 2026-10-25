# F1 과거 구간시간 원천·지원 감사 독립 검토

작성일: 2026-10-09. 이 검토는 후보 `CONTRACT.md`, `IMPLEMENTATION_PLAN.md`, `audit_source_availability.py` 및 사전 지원 산출물을 독립적으로 대조했다. 후보 feature 생성·저장 F1 replay·신규 fit·확률·손실·경주 지표 산출은 실행하지 않았다.

## 판정

원천 지원 사전 감사는 독립 재구성과 일치한다. 계약 및 계획의 입력 범위, 슬롯 의미, 품질 선택, 마스킹, 분할·평가 경계에도 blocking issue를 찾지 못했다. root가 허가한 다음 단계는 6개 후보 feature 생성 및 저장 F1 재로딩 replay다. 후보의 3개 최종 모형 fit과 온도 최적화는 별도 root 승인 전까지 진행하지 않는다.

## 독립 검증

검토기는 후보 feature/audit 생성 함수를 호출하지 않고, 저장 F1 features·`historical_lineage.parquet`·전체 source snapshot을 읽어 source slot 관계를 다시 확인했다. 요청된 history ID의 시간은 `jeju_race_section_time_values`에서 바인딩 조회하고, S1F/G1F의 순위·그룹 상태는 exact historical race tuple과 지점으로 조회했다. DB는 `mode=ro`, `query_only=ON`이었다. 구성요소 view의 9개 SQL 정의 SHA-256이 후보 receipt와 모두 같고, 관계는 시간값→시간 집계→postrace→reviewed→quality 및 순위·그룹 value→집계→quality였다.

F1 52,155행·5,206경주, 평가 17,412행·1,779경주·269일, 92,513행 source snapshot, 최근 같은 거리 실제 출전 178,459 슬롯 및 50,491개 고유 source ID가 독립 산출과 계약/후보 감사에서 일치했다. 모든 이력 슬롯은 말 ID·정확 거리·started·T−2를 만족했고, 슬롯 ID의 순서가 저장 F1 `last5_same_source_ids`와 일치했다. 시간 결측 또는 unusable 값 때문에 슬롯을 버려 과거로 채우는 동작은 없었다.

| 구간 | 실제 슬롯 | 유효 시간 슬롯 | 무효 source `valid_time`로 제외 | 동일 경주·지점 충돌로 제외 |
|---|---:|---:|---:|---:|
| S1F | 178,459 | 178,184 | 56 | 170 |
| G3F | 178,459 | 178,354 | 41 | 0 |
| G1F | 178,459 | 178,199 | 41 | 151 |

유효 시간 슬롯 수와 0–5 유효 관측 수, 거리·연도·경력 그룹 집계도 후보 출력과 전수 비교해 정확히 같았다(그룹 표 249행, 상세 분포 2,106행). 충돌 마스크는 12개 race-point(6 S1F, 6 G1F)에서 같았다. G1F 마스크 전체에는 159개 슬롯이 있지만 선택된 양수시간·유효 source time 조건까지 충족해 실제로 빠진 것은 151개다. 나머지 8개는 그 전부터 해당 필드 입력으로 쓸 수 없어서 후보와 독립 집계의 제외 산술이 일치한다.

품질 선택 상태의 전체 DB 도메인에는 미검토 양수 API 값 436,954건, 비양수/미제공 시간 210,633건, 공식 미해결 1건, 홈페이지 정정 3건이 있었다. 후보 지원 슬롯의 `api_positive_unreviewed`는 공식 홈페이지 확인 완료라는 뜻으로 표시되지 않았다. 독립 조회에서도 기록 178142 S1F 20.0초 정정, 180747 S1F 17.8초 정정, 191451 G1F 미해결 NULL, 190686 G1F 16.0초 정정을 그대로 확인했다.

F1 target별 거리 지원은 후보 통계와 일치한다. 1300m는 F1 target 606개 중 과거 유효 구간시간을 하나 이상 가진 target이 444개이고 1,289개 유효 history slots다. 1610m는 84개 target 중 48개, 96개 유효 slots여서 낮은 지원을 명시해야 한다. 이는 성능 지표나 독립 표본을 뜻하지 않는다.

## 계약 심사

F1의 저장 24개 feature와 평가 모집단을 그대로 두고 추가 6개(S1F/G3F/G1F 평균·유효 수)만 묶어서 비교한다. 동거리 최근 최대 5회 실제 출전, 필드별 독립 결측, 유효 수 0이면 NULL 평균, `source_snapshot.valid_time=True`, positive selected time와 허용된 두 status만 입력한다. 순위·통과조·예상전개·게이트·기수는 후보 입력에 들어가지 않는다.

같은 과거 race+section의 순위 또는 그룹 상태가 conflict/not_applied/source_changed이면 S1F/G1F 시간만 해당 race의 모든 참조 runner에서 보류한다. 19개 unresolved 경주 전체를 제거하거나 다른 시간 지점에 mask를 전파하지 않는다. G3F에 없는 순위/그룹으로 mask를 만들지 않는다. 1300m 출발→2C→S1F는 측정 순서로만 해석하고 물리적 초반 200m를 확정하지 않는다. 56,593행 broader benchmark 지원치를 F1 target support처럼 혼용하지 않는다.

평가 계약은 F1의 연도별 저장 tree 수를 보존한다(2024=92, 2025=200, 2026=200). 후보의 max 200/early stop 25는 후보만의 fit 상한이며 과거 저장 tree 수를 모두 200으로 고정하지 않는다. 비교는 개발 기간의 후향 연구로 보고, 결과가 나오기 전 고정한 loss·date-bootstrap·유지 후보 gate를 적용한다.

## 증거 파일

- [`independent_source_availability_receipt.json`](independent_outputs/independent_source_availability_receipt.json): 원천·lineage·SQL 체인·슬롯 지원 감사 및 입력 해시.
- [`independent_target_feature_reconstruction.csv`](independent_outputs/independent_target_feature_reconstruction.csv): F1 target별 독립 계산된 3개 평균·유효 수와 actual slot 수.
- [`independent_slot_lineage_and_selected_times.csv`](independent_outputs/independent_slot_lineage_and_selected_times.csv): 각 슬롯의 source ID·품질 선택값·상태·충돌 보류.
- [`independent_support_by_distance_year_experience.csv`](independent_outputs/independent_support_by_distance_year_experience.csv): 후보 지원 집계와 대조용 독립 그룹 표.
- [`independent_candidate_support_comparison.json`](independent_candidate_support_comparison.json): 249개 그룹행·2,106개 valid-n 행·race-point 마스크·view DDL SHA의 전수 일치 receipt.
- [`verify_source_availability_independently.py`](verify_source_availability_independently.py) 및 [`compare_candidate_source_audit_independently.py`](compare_candidate_source_audit_independently.py): 검토 재현 코드.

중앙 `conclusions/`, 기존 분석/DB/운영/TB는 수정하지 않았다.
