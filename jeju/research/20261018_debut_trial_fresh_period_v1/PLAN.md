# 첫 출전 주행심사 4입력의 새 기간 비교 계획

2026-10-18 계획 및 완료 기록. 목적은 기존 연구 종료일(2026-09-19)과 분리된 2026-09-20 이후 제주 경주에서 저장된 `F1_STYLE6` 30입력 모델과 `F1_STYLE6_DEBUT_TRIAL4` 34입력 모델을 비교하는 것이다. 기존 두 모델의 가중치·온도 `tau`·범주 어휘·입력 순서와 네 심사 입력 정의를 그대로 사용했다. 학습, 재보정, 튜닝, 모델 변형, 운영 승격은 하지 않았다.

## 현재 상태

독립 원천 감사와 root 검토 후 종료일을 2026-10-17로, 적격 roster를 45경주/426행으로 잠갔다. Root의 explicit release 뒤 저장된 2026 모델만 평가했다. DB 최신일을 미리 추정하지 않았으며, 이전 평가 마지막 날 2026-09-19는 신규 표본에서 제외했다.

동결 원천에는 2026-10-02, 03, 05, 09, 10, 16, 17의 7개 관측 카드(464 raw entrants/49 races)가 있다. 로컬 자료에서 2026-09-20–10-01 경주 행을 찾지 못했지만, 이는 해당 기간에 경주가 없었다는 주장이 아니다. 변경 없는 F1 전체 roster/착순 품질 규칙이 Oct03 R2, Oct05 R3, Oct09 R2, Oct10 R2를 보류하고 45경주/426행을 유지했다. `observed_starts == 0` 표본은 14두/6경주/6날짜(Oct02, 03, 05, 09, 10, 17)이며 모두 900m다. 적격성 계약에는 원천 결과/status 필드가 쓰였으므로 표본 구성까지 fully outcome-blind라고 부르지 않는다. 다만 source/feature/protocol lock 및 root 해제 전에는 새 모델 점수와 정답을 결합하거나 성과지표를 계산하지 않았다.

새 검증 폴더에는 source/feature receipts, 원천 재현기, 34입력, 두 모델의 결과 및 paired 평가를 보존했다. 결과의 정식 요약은 [README.md](README.md), 계약과 신뢰구간 표는 [CONTRACT.md](CONTRACT.md)에 있다.

## 기존 30입력 생성 경로

기존 열은 한 번에 새로 정의하지 않는다. 생성 계약은 아래 순서로 이어진다.

1. [`20261008_horse_profile_baseline_v1/run.py`](../20261008_horse_profile_baseline_v1/run.py)가 T−2까지의 시작 이력으로 J0 13열 및 추가 8열의 원자료 요약을 만든다. 출전 이력은 실제 시작 행에서 만들고, 같은 거리 슬롯은 별도로 보존한다.
2. [`20261009_finish_history_ablation_v1/prepare.py`](../20261009_finish_history_ablation_v1/prepare.py)가 기존 `previous_start_id`, `last5_same_source_ids`를 따라 이전 착순 3열을 붙인다. 미완료 상태를 일반 착순으로 바꾸지 않고 원래 원천 판정을 유지한다.
3. [`20261010_style_history_ablation_v1/prepare.py`](../20261010_style_history_ablation_v1/prepare.py)와 [원천 감사](../20261010_style_history_source_audit_v1/README.md)는 실제 동일거리 슬롯의 API4 개별순위와 API303 상태 게이트를 사용해 위치·변화·유효 관측 수 6열을 계산한다. 출전 전체 roster, `1..N_started` 순열, source snapshot의 `valid_time`, 명시 품질 상태를 모두 확인하며 불량 슬롯을 더 오래된 기록으로 대체하지 않는다.

따라서 새 target의 30열은 이 세 단계의 원뜻·T−2 경계·말 ID와 경주 ID 매핑을 보존해 생성해야 한다. 새 DB 상태 때문에 종전의 전체 DB SHA 비교기가 실패하거나 과거 source snapshot을 대체하는 경우는 입력이 재현된 증거가 아니다. 저장된 52,155행을 원래 기대값으로 두고 새 경주에 필요한 과거 이력은 각 target 경주의 T−2 이전까지만 누적한다. 새 관측 구간의 모든 464 raw starter row(평가 대상에서 제외된 품질 미달 경주의 출전자 포함)는 뒤 날짜 target 이력에 적법하게 반영할 수 있다. 과거 target의 이력에는 새 기간에서 그 target보다 먼저 열린 경주도 T−2를 통과하면 포함될 수 있다. 과거 저장 full-point cache는 52,155개 기존 feature row가 참조한 slot만 보장하며 전체 92,513개 start에 대한 coverage를 뜻하지 않는다. 따라서 적격 426개 평가행의 생성에 실제 참조되는 각 last-five same-distance history ID에 대해 캐시가 없으면 결측 feature로 넘기지 않는다. 각 누락 ID의 전체 경주 starter roster, API4 point 순열 및 API303 explicit quality gate를 같은 source lineage로 가져와 해당 적격 평가행의 coverage와 원천 fingerprint를 닫아야 한다.

## 새 기간 roster 확정

새 범위는 첫 대상 경주일이 2026-09-20 이상인 제주 경주다. 종료일은 로컬 보유 원천의 실제 최신 완결경주를 확인해 고정한다. 경주·출전 ID, 일정/가용 수, race-result 전체 roster와 정답성은 별도 원천 감사 증거에서 확정한다. `observed_starts == 0`은 F1 역사 정의상 T−2까지 관측 출전이 없음을 뜻하며 평생 첫 출전을 보증하지 않는다.

주평가 cohort는 확정 기간 안에서 F1 입력 생성 정의로 계산한 `observed_starts == 0` 출전자다. 주평가에서 해당 출전이 없는 날짜·경주도 roster/지원량 표에 보존한다. 새 기간에서 유효한 주행심사 입력이 없는 대상도 포함한다. 정확한 출전/경주/날짜 수와 분모는 roster를 잠근 후 성과를 열기 전에 기록한다.

## 네 주행심사 열

네 열은 이전 `CONTRACT.md`의 동일한 정의를 고정한다.

- `trial_peer_relative_time_mean3`: 경주일 T−2까지 등록된 최근 세 API20 말-이벤트 슬롯의 같은 이벤트 명시 제주 peer 상대시간 평균. 상대시간은 `(target rcTime − 본인을 제외한 자격 peer rcTime 중앙값) / peer 중앙값`이다. 이벤트마다 다른 자격 peer가 2두 이상 있어야 한다. 선택된 최근 슬롯이 부적격이면 더 오래된 이벤트로 채우지 않는다. 유효 신호가 없으면 NULL.
- `trial_peer_relative_time_n3`: 위 평균에 반영된 실제 이벤트 슬롯 수(0–3).
- `trial_days_since_latest_event_pre`: T−2까지의 가장 최근 등록 말-이벤트 기록일부터 대상 경주일까지의 달력일. 부적격·취소 슬롯도 최신기록일과 창 순서에 포함한다. 등록 기록이 없으면 NULL.
- `trial_event_count_pre`: T−2까지의 등록 말-이벤트 키 수. 시행 횟수라는 뜻이 아니며 기록이 없는 냉마는 0.

원천은 API20 `ridingTestResult_1`, 명시 제주 `meet=2`/`majong=제주`/공식 말 ID만 쓴다. API21 출발심사, 현재 프로필, 조교, 해당 target 경주의 결과·순위는 후보 입력에 쓰지 않는다. `rcDist` 부재를 거리로 추정하거나 원시 초를 이벤트 사이에서 합치지 않는다. API20 공개 시점이 확인되지 않으므로 T−2는 날짜 컷오프이며 당시 실제 공개·가용성을 증명하지 않는다.

## 저장 모델 재사용 및 평가

`F1_STYLE6_2026`와 `F1_STYLE6_DEBUT_TRIAL4_2026`의 저장 `top3.txt`와 `meta.json`을 그대로 다시 읽는다. 각 파일 SHA, 저장 `tau`, 30/34개 입력순서, 저장 범주 어휘와 모델 정의를 잠금한다. 기존 30입력은 두 모델에 같은 값으로 넣고, 네 추가 열은 `observed_starts == 0`에만 제공한다. 경력마의 네 추가 열은 전부 NULL이다. saved model 출력만 생성하며 어떠한 `fit`, calibration, hyperparameter search, vocabulary 확장도 하지 않는다.

주평가 지표는 cold 출전의 runner-binary Top3 log loss와 Brier다. 각 경주 안에서 cold 출전들의 손실을 평균한 다음, cold 출전이 있는 경주를 동일 가중한다. paired 차이는 `trial4 − F1_STYLE6`로 정의한다. 보조 분석은 전체 cohort, `observed_starts > 0` 경력마, cold 대상이 포함된 동일 경주에서 만든 기존 규칙 최대 6 canonical 조합, 고정 정의의 cold 출전 경주 내 raw-score concordance다. Concordance는 Top3 양성·음성이 모두 있는 경주만 포함하고 raw-score 정확한 동률은 0.5로 둔다.

새 기간은 작다. 이전 269개 경주일 bootstrap schedule은 날짜 수·대상 시점이 달라 재사용하지 않았다. 원천 결과/status를 포함한 고정 roster 및 `observed_starts == 0` eligibility에서 정해진 primary cold 날짜 `K=6`에 대해 동일한 20,000개 calendar-date bootstrap draw (seed `20261018`)를 양 모델과 LL/Brier에 공유했다. 각 반복에서 K개 날짜를 복원추출하고 날짜별 cold-race 손실 합계와 race 수를 각각 합산해 race-equal 비율을 계산했다. 사전 규칙 `K < 5` 탐색 표시 조건에는 해당하지 않는다. Secondary all-races 분석은 확정된 새 기간의 관측 7-date schedule을 썼다. 날짜/대상 roster와 protocol을 성과 계산 전에 잠그고, root의 explicit release 뒤에만 점추정치와 CI를 계산했다. 결과를 본 뒤 날짜·cohort·정의·모델을 변경하지 않았다. cold 대상은 900m뿐이므로 800m/1000m 일반화 주장은 하지 않는다.

## 단계

1. 기존 입력 생성원천과 세 단계의 T−2/ID/결측/품질 정책을 문서화한다.
2. [historical_source_rebuild.json](outputs/historical_source_rebuild.json)에서 보존 source snapshot/ledger/full-point cache/API20 source bundle을 실제 J1→R1→F1→F1_STYLE6→trial4 생성 함수에 넣어 52,155행과 34열을 다시 만들었고, 저장표와 모든 값을 정확히 비교했다. 이와 별개로 [historical_reproduction.json](outputs/historical_reproduction.json)은 저장표 사본의 30열 비교와 기존 4,673행 saved-score replay를 증명한다. 둘 다 과거 구현 보존 검증이며 새 기간 성과 분석은 아니다.
3. 독립 원천 검토자가 새 기간의 원천 완료상한, race roster, 정답 범위, 공식 말 ID 연결과 30입력에 필요한 T−2 history source를 검증한다. 목표 roster와 종료일을 root가 확정한다. Holdout race 결과는 보존하되 이후 대상의 T−2 이력으로는 허용한다.
4. 독립 원천 audit, 30/34 입력 비교, protocol 및 model hash를 고정했다. 최종 34 입력과 trial4 slots는 root reference와 exact equality였다.
5. Root release 뒤 frozen 두 모델만 예측했으며, 원래 saved `tau`와 평가 코드를 사용했다. 학습·재보정은 하지 않고 20,000 paired-date bootstrap을 사전고정 schedule로 계산했다.
6. 독립 root evaluator와 모든 runner/race/ticket 및 120,000개 bootstrap 결과를 대조했다. ID와 discrete picks는 일치했고 runner 결과 최대 수치차는 `1.1e-15`, bootstrap 값은 `4.2e-16` 이하였다. 새 결과는 이전 2024-01-05–2026-09-19/661 cold starts/252 races 결과와 분리해 유지한다.

## 결과 요약

Cold 14두/6경주에서 candidate−baseline Top3 log loss는 +0.07567 (0.70622 대 0.63056, 95% CI −0.16623–+0.34457), Brier는 +0.03139 (0.25245 대 0.22106, CI −0.07463–+0.14538)였다. 두 점추정치는 후보에 불리하고 구간은 0을 포함한다. 전체 cohort LL/Brier 차이는 각각 +0.00030/+0.00025이며, experienced-only는 −0.00039/−0.00009로 작고 모든 구간이 0을 포함한다. Cold concordance는 양·음성 cold runners가 모두 있는 3경주/4쌍에서 두 모델 모두 0.5다. 두 모델은 45개 경주 중 같은 7개 경주에서 6조합 hit를 냈고, cold 포함 6경주 중 같은 2개에서 hit를 냈다.

표본은 전부 900m이고 K=6 날짜뿐이다. 사전등록된 `K < 5` 플래그에는 해당하지 않으나, 이 결과만으로 더 넓은 시기·거리의 일반화를 말할 수 없다. API20 시행일은 T−2까지 걸러졌지만 일부 source의 당시 공개시점은 확인하지 못했다. 연구용 결과이며 운영 승격은 없다.
