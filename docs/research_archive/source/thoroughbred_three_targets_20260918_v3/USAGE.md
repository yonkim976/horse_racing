# 세 목표 연구 사용 및 재현

이 폴더는 운영 모델과 분리된 연구 산출물이다. A는 말 한 마리의 3착 이내, B는 순서 없는 입상 3두 전체, C는 1·2·3착 순서 전체다. 목표별 선택과 확률 보정이 다를 수 있으므로 각 목표의 출력을 한 공동분포처럼 섞지 않는다.

## 저장된 결과 읽기

- `REPORT.md`: 같은 경주에서 비교한 기준선·선택 모델, 변수 묶음 효과, 높은 확률 구간의 실제 적중률과 표본 수.
- `selected_historical_choices.csv`: 서울·부경 2025–2026년 각 경주의 A/B/C 선택, 확률, 실제 결과. 이미 확인한 과거 참고자료이며 새 독립 테스트가 아니다.
- `selected_A_subgroups.csv`: 선택한 한 마리의 경험·휴양·거리 조건별 확률과 적중률. 사후 진단이며 재선정에 쓰지 않았다.
- `predictions/`: 모든 후보·연도의 말별 A 확률과 B/C 상위 10개 조합.
- `future_predictions_20260919_20_r2/UPCOMING_PREDICTIONS.md`: 검증을 통과한 9월 19·20일 예상표 수정판. **9월 17일 확보한 출마표 버전**이며 이후 변경을 반영한 최종 출발마 표가 아니다. 최초 폴더는 영천 C 추론 보정 기본값 차이를 발견해 대체했고, 감사용으로 보존했다. 과거 연구만 재현하면 이 미래 적용 폴더는 생성하지 않는다.

## 기존 연구의 무결성 확인

아래 명령은 읽기 전용 해시 검증이다.

```bash
cd /Users/kimyongjin/Desktop/horse_racing
.venv/bin/python data/research/thoroughbred_three_targets_20260918_v3/code/integrity.py verify-manifest
```

## 전체 역사 연구 재현

존재하지 않는 새 출력 폴더를 지정한다. 수십 개 모델을 다시 학습하므로 시간이 걸린다. 원천은 현재 통합 DB와 고정 v2 기준선이며, 기존 v1/v2 및 운영 DB를 수정하지 않는다.

```bash
cd /Users/kimyongjin/Desktop/horse_racing
.venv/bin/python data/research/thoroughbred_three_targets_20260918_v3/code/reproduce_targets.py \
  --output /Users/kimyongjin/Desktop/horse_racing/data/research/thoroughbred_three_targets_reproduction_01
```

코드·프로토콜과 데이터 가용성 감사 스냅샷 복사, 원천 해시, 피처 생성, 검사, 연도별 FIT/TUNE/CAL/EVAL, 독립 재생 검증, 하위집단 진단, 보고서 및 최종 해시 검증을 실행한다. 복사한 자료 가용성·저장소 감사는 최초 감사 당시의 기록이며 새 외부 자료를 수집했다는 뜻이 아니다. 기존 출력 폴더의 모델·예측을 덮어쓰거나 불완전 실행을 암묵적으로 이어 쓰지 않는다.

## 준비된 새 출마표에서 A/B/C 계산

추론 입력은 원시 출마표가 아니라 **동일 피처 정의로 계산한 완전한 경주 단위 Parquet**이다. 새 출마표에 대해 엄격한 과거 이력으로 피처를 다시 만들어야 한다. 과거 경주의 피처 행에서 날짜나 말 이름만 바꾸면 안 된다.

- 필수 식별자: `race_id`, `venue_code`, `race_date`, `race_no`, `hr_no`, `chul_no`, `horse_name_normalized`.
- 공식 말·기수·조교사·마주 ID는 숫자가 아닌 문자열로 유지한다.
- `field_size_full_card`는 입력의 경주별 행 수와 같아야 한다. 일부 말만 추려 넣지 않는다.
- `history_cutoff_contract`는 `strictly_before_race_date`, `feature_cutoff`는 해당 경주일의 자정이다.
- `candidate_features.json`과 `feature_groups.json`의 선택 후보용 피처를 모두 제공한다. 결측은 모델의 결측 처리 경로로 전달하고 임의로 능력 0이나 조교 0으로 치환하지 않는다.
- 결과·라벨 열이 있으면 일반 추론이 거부된다. 역사 재생만 `--historical-replay`를 사용한다.
- 이 CLI는 선택한 **2026년 고정 번들**을 사용하므로 2026-01-01 이전 경주는 거부한다. 새로운 입력의 실제 공개 시점까지 검증하는 도구는 아니며 기본 상태를 `prepared_card_inference_timing_unverified`로 보존한다.
- 현재 체중·날씨·조교·주행심사 추가 후보는 선택 대상에서 제외했다. 별도 후향 후보를 수동 요청하려면 `--allow-retrospective`가 필요하며 그 결과를 기본 사전 모델 성능으로 표현하지 않는다.

```bash
cd /Users/kimyongjin/Desktop/horse_racing
.venv/bin/python data/research/thoroughbred_three_targets_20260918_v3/code/infer_targets.py \
  --study data/research/thoroughbred_three_targets_20260918_v3 \
  --input /absolute/path/to/prepared_complete_card.parquet \
  --output /absolute/path/to/new_prediction_directory
```

`A_predictions.parquet`에는 각 말의 A 확률·예상 순위가, `B_C_top10_predictions.parquet`에는 B/C의 상위 10개 조합·확률이 기록된다. 각각의 전체 분포는 계산 중 정확히 정규화되지만 B/C 저장 파일은 상위 10개만 보존하므로 그 파일의 확률합은 일반적으로 1보다 작다. 출력 폴더는 새 폴더여야 한다.

`code/export_forecast.py`는 이번 9월 19·20일 고정 출마표 적용을 말 이름이 있는 CSV와 Markdown으로 내보낸다. 미래 날짜만 허용하고 기존 예상을 덮어쓰지 않는다. 결과 정산, 운영 승격, 자동 베팅은 수행하지 않는다.

이번 고정 출마표의 피처 생성만 재현하려면 다음처럼 새 디렉터리를 지정한다. 이는 새 출마표 수집 명령이 아니며 9월 19·20일 고정 입력을 재생성한다. 두 날짜 모두 9월 19일 미만의 원천만 사용한다.

```bash
.venv/bin/python data/research/thoroughbred_three_targets_20260918_v3/code/prepare_future_context.py \
  --output-dir data/research/thoroughbred_future_context_check_01
```

기존 Parquet/lineage는 덮어쓰지 않는다. `prediction_input/future_20260919_20_context.guard_verification.json`에는 기존 입력이 변경되지 않았고 별도 폴더의 재생성 결과가 같은 SHA-256이라는 검증이 있다.

공유 작업폴더의 다른 작업이 보호된 소스 파일을 바꾸면 전체 보존 검사는 실패하고 재현 명령은 중단한다. 실패를 숨기기 위해 다른 작업의 파일을 원복하면 안 된다. 모델·DB·원천 해시의 변동 여부를 따로 조사하고, 연구와 무관한 변경도 보존 검사 기록에 남겨야 한다.

## 입력 한계

과거 날짜의 결과라고 해서 당시 게시시각이 모두 증명된 것은 아니다. 기본 모델은 이전 날짜의 확정 공식 결과가 다음 예측일 전에 알려졌다는 역사적 가정과 고정 출마표 필드를 사용한다. 당일 체중·주로·날씨 및 게시시각 미검증 자료는 별도 실험으로 구분했다. 상세 계산식은 `FEATURE_DICTIONARY.md`, 원천 범위와 미완 검증은 `DATA_AVAILABILITY.md`에 있다.
