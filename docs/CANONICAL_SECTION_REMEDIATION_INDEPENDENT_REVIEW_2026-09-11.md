# Canonical R1~R4 보완 독립 검증

- 검증: 2026-09-11 20:10~20:17 KST의 공유 작업공간
- 판정: **서울 canonical 연구 단계의 R1~R4는 통과. 운영 승격 및 예측력 우월성 승인은 아님.**
- 대상 run: 73967a1a-197b-4d81-8149-ee0b008de2a7
- 실제 결과 조회·평가는 2026-05-31 이하. 모델 재학습·운영 코드 수정·DB 변경은 수행하지 않았다.

## 1. 독립 재현 결과

| 항목 | 결과 |
|---|---|
| 새 비교 스크립트 재실행 | 제출 comparison.json과 JSON 객체 전체 일치 |
| validation 출전집합 | 양쪽 3,038행·288경주, 누락·추가 0 |
| A/B 데이터 키·날짜·win/top2/top3 라벨 | 전체 데이터에서 동일 |
| 입력 변조 검사 | 한 행 누락·추가·중복·NaN·범위 이탈·확률합 오류·마번 불일치 모두 거부 |
| 동점 기대 포함률 | 실제 예측 역순·무작위 재배열 불변; 단일/복수 우승 라벨 조합 480개를 순열 전수 계산과 대조 |
| 새 canonical artifact 재추론 | 3,038행의 win/top2/top3 확률 및 전체 출력이 저장 예측과 정확히 동일 |
| 기존 V5 artifact 재추론 | 6,969행의 모든 저장 확률 및 공통 출력 열이 정확히 동일 |
| 새 manifest의 5개 코드 SHA-256 | 현재 파일과 전부 일치 |
| 구간·source 상한 및 연관 회귀 테스트 | 46 passed, 1 warning |
| 이번 보완 관련 Ruff | 통과 |
| git diff --check | 초기 통과; 최종 확인에서 동시 지도 작업의 EOF 공백 검출 |

V5의 현재 추론 출력에는 저장 파일보다 rank_score_base, margin_performance_score 두 진단 열이 더 있다. 따라서 DataFrame 전체 형태가 같다고 표현하지 않고 공통 열과 확률의 정확한 일치로 판정했다.

새 canonical run과 이전 canonical run은 학습·validation 기간, seed, feature 목록, model type 및 artifact 경로를 제외한 원장 hyperparameters가 같다. encoder도 동일하다. win booster는 같지만 top2/top3 booster 문자열은 다르다. **validation 예측 동일성은 모델 artifact 전체의 동일성을 뜻하지 않는다.**

## 2. 24개 입력 셀의 차이 원인

- early_late_balance_avg5 11개와 resilience_avg5 11개: 최대 절대 차이 8.881784197001252e-16. 미세한 부동소수점 수준의 차이이며 발생 연산 자체를 특정하지는 않았다.
- exact_distance_balance_avg5 2개: 최대 절대 차이 0.13559373970757527. horse_id=4098, race_entry_id=22674(2025-03-16), 27926(2025-05-25)의 1,700m 이력 feature다. 두 행 모두 학습 구간에 속한다.

실제 차이의 원인은 2023-01-29 서울 1,700m race_id=12254에서 확인했다. 상대 말 race_entry_id=133219는 S1F 누적 75.3초, FIN 115.5초, G3F closing 42.2초였다. G3F 누적은 73.3초이므로 앞 지점인 S1F의 75.3초와 순서가 맞지 않는다. 새 검사는 이 S1F를 제외한다.

그 결과 해당 경주의 S1F 중앙값이 14.8초에서 14.7초로 바뀐다. 해당 경주는 위 두 대상의 동일거리 직전 5경주에 각각 포함된다. 예상 feature 변화 100 × ln(14800/14700) ÷ 5 = 0.13559373970757538로 실제 두 셀 차이를 설명한다. 따라서 실제 변화는 R3의 물리적 검증 보완과 연결되며, 미래 자료 유입의 증거가 아니다. 원천에서 왜 S1F가 잘못 기록됐는지까지 조사하거나 DB를 수정하지 않았다.

## 3. 성능 판정

| 정의 | Top1 | Top3 | Top5 | Winner NLL |
|---|---:|---:|---:|---:|
| Legacy | 31.7130% | 62.3206% | 83.8194% | 1.920889851 |
| Canonical | 31.6956% | 63.6053% | 83.6632% | 1.923827885 |

NLL 차이 canonical−legacy = +0.0029380344740913954. 경주 bootstrap 95% CI는 [-0.030748699238871805, +0.03673950183429222], 날짜 block CI는 [-0.027582923073068907, +0.03455628425792916]. 개선도 동등성도 입증되지 않았다.

범위는 서울 history feature, LightGBM binary bundle, seed 42 및 이미 calibration 선택에 사용한 개발 validation이다. V5 LambdaRank의 직접 교체 평가나 미개봉 미래 test 결과로 확대 해석하지 않는다.

## 4. 남는 제한과 작업공간 상태

1. probability_ties_at_boundary_top3/top5는 실제로 'K번째 말이 동점군에 속한 경주'를 센다. K와 K+1 사이를 가로지르는 동점만 센 값은 legacy Top1/3/5 = 51/96/93, canonical = 83/82/103이다. 제출된 51/163/157, 83/151/160은 진단 필드의 의미가 더 넓다. TopK 기대값 및 NLL 계산은 올바르므로 이번 통과의 차단 사유는 아니다. 다음 평가 도구 정리 시 명칭 또는 집계를 맞춘다.
2. 동일 측정 지점의 100ms 허용치는 공식 원천 정밀도를 이번 검증에서 확정한 값이 아니다. 해당 경계 및 타 경마장 확대 전 계약을 확정해야 한다. transform_version 문자열은 v1로 남아 있으므로 이번 재현은 새 dataset/run 식별자와 코드 해시를 함께 사용한다.
3. 비교기는 현재 제출 쌍의 검증에 통과했다. 임의의 모든 run에 대한 완전한 검증기로 보증하는 것은 아니다. 향후 일반화 시 train 기간·전체 설정·라벨·manifest의 실제 내용 해시 계약까지 자동 대조한다. 이번 제출 쌍의 실제 기간·설정·라벨은 별도로 대조했다.
4. source의 event-date 상한 적용은 모든 feature의 공개시각 PIT 적합성을 증명하지 않는다. 기존 성별 snapshot, 사후 scratched 상태, 정상완주 조건부 라벨 문제는 별도다.

검증 시점 전체 pytest는 **397 passed, 1 failed, 2 warnings**였다. 실패는 tests/test_racecourse.py::test_racecourse_map_supports_seoul_and_jeju가 부경 결과를 None으로 기대하지만 현재 web/racecourse.py가 부경 지도를 반환하기 때문이다. canonical 보완과 별개인 지도 변경과 테스트의 불일치로 확인했다. 사용자 제출 당시 398 passed라는 실행 결과 자체를 부정하는 것은 아니지만 현재 작업공간 전체 통과로 인용해서는 안 된다.

전체 Ruff는 **30건**이었다. 기존 21건 외 web/busan_diagram.py, web/race_page.py, web/racecourse.py에 각각 3건이 있다. 이번 검증은 해당 동시 작업을 수정하지 않았다. 연구 보완 범위 통과와 저장소 전체 배포 가능 상태를 구분한다.

보고서 저장 후 최종 git diff --check에서는 src/horse_racing/web/racecourse.py:347의 새 EOF 빈 줄이 검출됐다. 초기 검사 이후에도 공유 작업공간이 바뀌고 있으므로 각 검사 결과는 실행 시점의 기록이다. 이 지도 파일도 수정하지 않았다.

## 5. 다음 단계

다음 담당자에게 사전 출전집합·DNF 계약 감사와 연구용 명세를 요청한다. 현재 dataset.apply_label_policy는 결과를 보고 특수착순 등을 제거한 뒤 starters를 계산한다. live 경로는 현재 scratched 상태를 이용한다. 출전집합이 다르면 이후 확률 정규화·상대 feature·평가 분모가 다른 사건을 대상으로 하므로 우선 계약을 맞춰야 한다.

구현 담당자에게 전달할 지시서는 PRE_RACE_FIELD_DNF_E1_AGENT_PROMPT_2026-09-11.md에 있다. 이번 검증에서 다음 단계 작업을 실행하지 않았다.
