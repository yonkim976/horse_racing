# 제주 TB 상대 순위·거리 상태 입력 원천 감사

2026-10-22. 이 문서는 확정된 `supervisor/DESIGN_CONTRACT.md`를 위한 원천 적합성 기록이다. 입력 생성은 상태 10개 열과 계보만 만든다. 모델 적합, 확률 산출, 평가 성능 계산은 수행하지 않는다.

## 기준 원천과 확인된 모집단

기준 경주 이력은 [10/08 source snapshot](../../20261008_horse_profile_baseline_v1/outputs_v2/source_snapshot.parquet)이다. 원천 해시는 `c2307afe79c4ca3a1c4a1ab46159be93450ca03450f8fd51063dd2318ed49403` (7,453,522 B, 92,513행)이다. DB read-only roster 대조를 요약한 [history_eligibility.parquet](history_eligibility.parquet)는 8,431개 후보 경주·82,966 source 행을 사유별로 남긴다. 7,066개 경주·69,752행만 2010-01-01 이후의 전체 실제 출전 roster와 정확히 일치하고, 모든 출전마의 양의 유한 완주시간·정상 착순 1..N·고유 식별자·지원 거리·최소 4두 조건을 통과했다. 대조 결과 적격 후보 7,066개 중 roster 불일치 0이다. 최신 ledger SHA256은 `0aeef4ba4e5c072d19993d4286023c68ee06fabaaf6b29fa651ffad95ee1b3ef` (354,756 B, zstd Parquet)이며 원천 event-date 범위는 2010-01-08~2026-09-19다.

`2010-01-08`~`2016-12-31`의 1,860경주·17,597행은 상태 warm-up이고, 2017-01-13 이후의 5,206경주·52,155행이 supervised cohort다. 과거 2017+ 적격 경주는 target cohort 5,206개와 정확히 일치한다. 2024~2026-09-19 공통 평가는 1,779경주·17,412행·269일이며 기존 연승분모 1,743경주다. 생성기는 target cohort에서 키·편성 메타만 읽고 과거 finish label은 feature 테이블에서 읽지 않는다. F1_STYLE6 전체 feature 테이블은 경로·SHA `036939bd6d518a9e53d458a2f4eb2bf30bfecfa4bb80e21c78edd1f7f44f028f`로만 참조하며 복사하지 않는다. source manifest의 `ce300977...`는 10/10 `prepare.py` 코드 파일이며 feature artifact가 아니다.

현재 제외 정책의 말 ID `3005648`은 읽은 historical snapshot과 target metadata slice 양쪽에서 0행이었다. 제외 파일은 `jeju/data/horse_exclusions.json`에 있으며 해당 원천 파일의 크기·SHA도 input manifest에 고정한다. 원천 snapshot에는 `result_status` 필드가 없다. 따라서 착순/완주시간/started/valid_time로 보수적인 정상 완주 cohort를 만들었으며, status 텍스트를 복원했다고 주장하지 않는다. 동착·착순 결측·부분 roster·미완주/실격은 순위 1..N과 전원 양의 완주시간 조건을 만족하지 못하면 과거 rank 업데이트에서 제외한다. target cohort의 기존 분모는 그대로 둔다.

감사 명단은 원천 race별 1..N 및 roster를 고정 source snapshot의 API ID와 DB의 실제 race-result roster로 대조해 작성했다. DB는 `mode=ro`, `query_only=ON`의 제한된 race-key 조회만 사용했다. DB 자체를 복사하거나 전체 해시하지 않았다. 입력 생성기는 DB를 열지 않고 이 compact ledger와 source snapshot만 읽는다.

기존 CSV를 Parquet로 바꿀 때 8,431×9 셀 전체를 문자열 그대로 비교해 동일성을 확인한 다음 임시 CSV만 제거했다. 이전 source-row digest serializer는 저장되거나 문서화되지 않아 해당 per-race hash가 맞았다고 주장하지 않는다. 이를 pre-fit 감사 정정으로 명시하고 source rows hash만 다시 계산했다. 고정된 정규화는 10개 `SOURCE_COLUMNS` 순서의 행 배열을 만든 뒤 `api_record_id,horse_number,horse_id` 오름차순으로 정렬하고, 각 배열을 Unicode 보존·공백 최소화 JSON(UTF-8)으로 직렬화하여 행마다 LF를 붙인 바이트의 SHA-256이다. Null과 비유한 숫자는 JSON `null`, 날짜는 ISO 문자열, 정수·불리언·유한 실수는 해당 JSON 기본형으로 쓴다. 후보/적격 race ID, 모든 source 행수, 날짜, 거리, DB roster 플래그, eligibility, 사유는 변경하지 않았다. 이전 CSV SHA는 `b0676326eabf3297b52a750ea2cb64b9f165fd00bf6cc9887f75c7fb6a1ce516` (1,087,180 B), CSV에서 변환한 직후의 Parquet SHA는 `264382cab2af471d8a8f88a5d1b6e3b1df7745acee2f722d8ee7beccd497581e`, 재계산 후 현재 Parquet SHA는 `0aeef4ba4e5c072d19993d4286023c68ee06fabaaf6b29fa651ffad95ee1b3ef`다. 각 행의 새 `source_rows_sha256`는 위 명세의 digest다.

## TB 방법과 제주 입력 계약의 매핑

기준 TB 구현은 `thoroughbred/research/20261022_dynamic_race_model_v1/state.py`의 `prior`, `propagate`, `Filter.query`, `Filter.update`다. 이는 과거 각 경주의 상대 순위를 비교마별 당시 상태로 업데이트하고, 거리를 중심화한 rank 능력과 거리 기울기, 불확실성을 유지한다. TB의 별도 기록 Kalman, 초·종반 600m 상태 및 비완주 위험은 이번 후보에 넣지 않는다. 제주 S1F/G1F 위치는 초가 아니고 거리별 경계도 달라 초 단위 state와 동등하게 옮길 근거가 없다.

제주 구현은 동일한 상대 pairwise 순위 likelihood와 고정 TB rank-update 하이퍼파라미터를 유지하면서 `h(d)=[1,(d−1100)/500]`를 사용한다. 제주 8개 거리(800, 900, 1000, 1110, 1200, 1300, 1400, 1610m) 가운데 기록 source가 일관된 경주만 업데이트한다. 비교 입력은 기존 F1_STYLE6 30열 대 30열+상태 10열의 통제된 계약이다. 10개 입력의 정확한 이름·수식·prior는 `supervisor/DESIGN_CONTRACT.md`에 단일 정의되어 있다. 미관측 평균 0은 prior 중심이지 말 능력을 관측한 값이 아니다. 동시 경주는 날짜 단위 pre-update snapshot을 쓰고 모두 일괄 commit한다.

구성 원천은 snapshot의 `api_record_id`, `race_id`, `race_date`, `horse_id`, `horse_number`, `race_distance_m`, `finish_position`, `finish_time_seconds`, `started`, `valid_time`이다. target row 키와 편성 메타는 `20261010_style_history_ablation_v1/outputs/features.parquet`의 `api_record_id`, `race_id`, `race_date`, `horse_id`, `horse_number`, `distance_m`, `field_n`만 읽는다. target finish position이나 30개 기존 engineered feature는 상태 입력 생성에 사용하지 않는다. target metadata의 레이스 roster를 유지해야 하므로 최종 출전 명단은 역사적으로 확인된 공개시각 roster가 아니라 회고 명단이다.

## 시점 경계와 한계

각 target 경주 날짜를 T라 할 때 history event는 `race_date <= T−2일`을 포함한다. 이 경계는 기록된 event date 기준이다. source에는 공개 timestamp 또는 당시 출전명단 공개시각이 없어 해당 상태가 실시간으로 관측 가능했음을 입증하지 않는다. target cohort가 2017년에 시작하므로 모든 target은 2010 warm-up 이후 최소 수년의 가능한 이력을 가진다는 뜻도 아니다. 신규·자료가 적은 말은 `state_rank_n=0` 및 명시적 prior로 남고, prior를 관측 실력으로 읽으면 안 된다.

최근까지의 실제 DB 상태를 역사 snapshot으로 덮어쓰지 않는다. roster 대조 ledger는 검증 범위와 해시를 보존하는 compact audit 자료이며, 광역 source 92,513행 원본은 복제하지 않는다. 상태표는 생성 시 snapshot의 적격 과거 event만 사용하고, query는 cutoff를 넘지 않는다. 이는 역사 원천의 식별·완주 cohort 선택 편향을 제거하지 않으며, 정상 완주·완전 rank event만 반영하므로 비완주 위험 모델도 아니다.

TB 58C 결과는 원천 매핑의 동기만 제공한다. TB에서 보고된 승식 성능이나 다른 코호트는 제주 예측 성능·유의성·10% 개선의 증거가 아니다. 제주 F1_STYLE6의 2024~2026 반복 사용 기간도 독립 미래 검증이 아니다. 이전 동적 상태 연구의 보류 A/B 후보를 확정 계약·채택 기준으로 취급하지 않는다. 이번 단계는 source audit와 compact feature input만이며 fitting/evaluation/promote는 별도 승인 게이트다.

## 고정 출처·계보

원천/기준 파일의 경로, SHA256, byte 수 및 연구 산출물 SHA는 [source_manifest.json](source_manifest.json)에 두고, 생성 결과·코드·schema·cohort census·검증 결과는 `inputs/input_manifest.json`에 기록한다. builder prefix replay는 2017 첫 경주·2024 중간 경주·2026 마지막 경주의 세 cutoff를 재계산하며, supervisor verifier가 모든 저장 상태를 독립 재계산한다. 최종 입력은 target row 단위이며 target key `api_record_id,race_id,race_date,cutoff,historydate`와 상태 10열만 `inputs/state_features.parquet`에 저장한다. `inputs/state_lineage.parquet`는 각 target row의 마지막 반영 source `race_id`, 이력 수 및 cutoff를 별도로 보존한다. 기존 source/database/model/feature artifacts는 모두 참조만 한다.
