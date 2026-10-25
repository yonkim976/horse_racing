# 새 기간의 주행심사 4입력 frozen-model 비교

**결과:** 새 기간 cold cohort에서 `F1_STYLE6_DEBUT_TRIAL4`가 기존 `F1_STYLE6`보다 나은 점수라는 근거는 확인되지 않았다. Cold runner Top3 log loss 차이(candidate−baseline)는 `+0.07567` (0.70622 대 0.63056), Brier 차이는 `+0.03139` (0.25245 대 0.22106)로 두 점추정치 모두 후보에 불리했지만, 사전등록한 95% paired-date bootstrap 구간은 각각 `[-0.16623, 0.34457]`, `[-0.07463, 0.14538]`로 0을 포함한다. 결과는 모델 승격이나 운영 변경을 승인하지 않는다.

신규 원천 freeze는 2026-10-02부터 2026-10-17까지 실제 자료가 보유된 7개 관측 카드(49경주/464 출전자)를 담는다. 변경 없는 F1 전체 roster 및 착순 품질 규칙을 통과한 표본은 45경주/426행이고, 그중 `observed_starts == 0`인 14행은 6경주/6날짜에 분포하며 모두 900m다. 9월 20일부터 10월 1일까지 로컬 경주 행이 없다는 사실은 그 기간에 경주가 없었다는 뜻이 아니다. 이번 14두 표본은 이전 기간의 661 cold starts/252 races와 완전히 별도로 보고한다.

기존 생성 경로 보존 검증([historical source rebuild](outputs/historical_source_rebuild.json))은 보존된 92,513행 원천 snapshot과 cache로 기존 입력 52,155행을 실제 J1→R1→F1→style6→trial4 생성 함수에 통과시켜 모든 값을 정확히 재현했다. 새 기간에서는 30개 기존 입력이 root 독립 reference와 정확히 일치했고, 121행의 동결 API20 peer 원천에서 생성한 trial4 14행과 19개 선택 심사 슬롯도 root reference와 정확히 일치했다. 최종 426×34 입력은 root 동결 reference와 모든 ID 및 34개 값이 일치했다. 두 saved model의 새기간 예측, 경주 점수, 최대 6개 조합, 120,000개 paired-bootstrap 값은 root의 독립 평가와 일치했다. 예측·경주·조합 수치의 최대차는 `1.1e-15`, bootstrap 차이는 `4.2e-16` 이하였다.

평가는 저장된 2026 baseline/candidate 모델, vocabularies 및 `tau`만 사용했다. 재학습·재보정·튜닝은 0회다. 원천 착순/상태 값은 frozen roster 품질 기준에 쓰였고, 성과 계산을 위해 평가 결과와 예측을 연결했다. 따라서 이 분석을 표본 선정까지 완전히 outcome-blind였다고 표현하지 않는다. 모델 예측을 새 기간 결과로 학습하거나 보정하지 않았다.

Cold 표본은 14두·6경주·6날짜에 그치며 모든 cold 경주가 900m다. 사전 규칙의 `K < 5` exploratory 플래그에는 해당하지 않지만, 6개 날짜로 구한 넓은 신뢰구간은 추정이 매우 불안정함을 보여 준다. Cold concordance는 양·음성 cold 말이 모두 있는 3경주, 4쌍만 비교할 수 있었고 두 모델의 race-equal 값은 모두 0.5였다. 따라서 이번 기간은 800m/1000m 등 다른 거리에 대한 일반화를 입증하지 않는다.

| 지표 | 기존 연구모델 | 주행심사 후보 |
|---|---:|---:|
| Cold log loss | 0.63056 | 0.70622 |
| Cold Brier | 0.22106 | 0.25245 |
| 전체 6조합 적중 | 7/45 | 7/45 |
| Cold 포함 경주 6조합 적중 | 2/6 | 2/6 |

두 모델이 적중한 7개 경주키는 모두 동일했다. 새 기간 결과에 따라 기존 모델을 유지하고 주행심사 후보의 채택은 보류한다.

결과의 방향은 개별 경주마다 달랐다. 6개 cold 경주 중 후보의 cold LL이 더 나빴던 경주는 4개, 더 나았던 경주는 2개였다. 14마리 중 11마리는 최근 3개 심사 슬롯에서 유효 상대시간 1개를 가졌다. 예를 들어 10월 2일 전승맨(실착 2위)은 Top3 확률이 baseline 0.4115에서 candidate 0.2131로 내려갔고, 10월 3일 초월비(실착 3위)는 0.4337에서 0.2569로 내려갔다(유효 심사 1개, 최근 등록 심사 기록과 경주일 간격 114일). 반대로 10월 17일 총사령관(실착 5위)은 0.2548에서 0.6088로 올랐다. 이 세 사례는 결과 설명을 위한 예시일 뿐이며 primary 추정은 14두 전체·6개 경주의 사전 고정 집계다.

API20의 `T−2` 기준은 trial 시행일로 자르며 해당 자료가 그때 대중에게 공개·가용했는지는 확인되지 않았다. 결과는 탐색용 새 기간 검증으로만 보존하며 운영 모델, 공유 DB, registry는 변경하지 않았다.

실행 조건·입력 정의·요약 지표는 [CONTRACT.md](CONTRACT.md), 과정과 증거 목록은 [PLAN.md](PLAN.md)에 있다. 코드·표·외부 검토 근거의 최종 해시 목록은 [FINAL_MANIFEST.json](FINAL_MANIFEST.json)에 있다. 핵심 산출물은 [34-input table](outputs/fresh_features_34_root_dryrun.parquet), [runner predictions](outputs/fresh_model_predictions.parquet), [race metrics](outputs/fresh_race_metrics.parquet), [paired cold-date bootstrap](outputs/fresh_primary_date_bootstrap.parquet), [scope summary](outputs/fresh_scope_summary.json), [evaluation receipt](outputs/fresh_evaluation_receipt.json)이다.
