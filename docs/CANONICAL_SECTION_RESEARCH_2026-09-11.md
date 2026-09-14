# Canonical 구간기록 연구 경로 구현·검증 보고서

작성일: 2026-09-11 KST. 비교 범위는 서울, 결과일 2026-05-31까지다. 기존 운영 모델은
교체하거나 승격하지 않았다.

## 1. 완료 요약

- 원본 `race_section_results`를 수정하지 않고 `canonical_sections_v1` 파생 변환을 만들었다.
- 기존 `energy.py`와 feature 이름은 그대로 보존했다. 신규
  `racefit_canonical_rich`, `racefit_canonical_history`만 canonical 변환을 사용한다.
- 학습의 과거 결과·구간 원천 조회에 `end_date` 상한을 전달하고, label-free 추론 조회에도
  대상 날짜 이후를 읽지 않는 상한을 추가했다. 기존 허용 계약인 같은 날 앞 경주는 유지한다.
- 서울에서 legacy/canonical 데이터와 모델을 같은 조건으로 만들고 개발 validation을 비교했다.
- 부담중량, 레이팅, 라벨 정책, 전개 모델은 변경하지 않았다. 2026-06-01 이후 결과는 새 평가나
  사례 선택에 사용하지 않았고, 한라마 archive도 복원하지 않았다.

남은 문제는 제주·부경 기존 DB의 `time_basis/source_kind`가 전부 NULL이라는 점이다. 보관
원문 표본으로 원천별 의미는 확인했으나 각 DB 행을 어느 원천에서 가져왔는지 연결할 provenance가
없으므로 신규 변환은 이 행들을 `unknown`으로 남긴다. 원문 전체와 행 단위로 다시 연결하는 별도
복원 없이는 서울 외 통제 비교를 신뢰할 수 없다.

## 2. 원인과 원천 증거

확인된 오류는 학습 `_SECTIONS_QUERY`가 시간과 위치만 읽고 `time_basis/source_kind`를 버린 뒤,
legacy `energy.py`가 G3F/G1F 원값을 같은 의미로 경주 내 정규화했다는 점이다. 중앙값 정규화는
누적시간과 종반시간의 의미 차이를 제거하지 못한다.

읽기 전용 감사 결과는
`data/logs/canonical_section_source_audit_20260911.json`에 SQL 집계, 원문 파일 경로와 SHA-256,
원문/DB 대조값을 기록했다. 2026-05-31까지 S1F/G3F/G1F의 명시 basis 결측률은 서울 0%,
제주 100%, 부경 100%다. 모든 구간 코드를 합친 basis/source 분포는 서울
`closing/dacom11` 220,686행, `cumulative/dacom11` 375,952행,
`cumulative/api4_3` 86,573행이며 제주 314,304행과 부경 297,914행은 둘 다 unknown이다.

원문 표본은 각 경마장×원천×2024/2025 운영 거리별로 뽑았다. 서울 API 9거리·dacom11 9거리,
제주 API 8거리·dacom11 7거리, 부경 API 7거리·dacom11 8거리의 S1F/G3F/G1F가 저장값과
전부 일치했다. 2024 dacom11에 없던 제주 1,610m와 2025 API에 없던 부경 2,200m처럼 해당
연도에 원문 표본이 없는 조합은 만들어내지 않았다.

API 원문은 서울·부경의 `*AccTime`을 누적으로, 제주의 `jeG3fTime/jeG1fTime`을 종반시간으로
제공한다. dacom11의 G3F/G1F는 종반시간이고 S1F는 누적시간이다. 이는 값의 크기 추정이 아니라
원문 필드와 parser 계약 및 동일 출전의 저장값 대조에 근거한다. 다만 NULL DB 행에 이 계약을
소급한 것은 아니다.

서울 `race_id=1681`, 2025-01-04 1경주 6번은 원문/DB 전체 76,600ms,
G1F 누적 63,800ms와 일치했다. canonical 마지막 200m는 12,800ms, 경주 중앙값 14,450ms이며
상대지수는 `log(14450/12800)*100 = 12.124924`다. 이는 과거 한 출전의 관측값이지 다음 경주의
예측점수나 개선치가 아니다.

## 3. 변경 파일과 호환성

- `features/base.py`: 구간 provenance·전체기록·경마장·거리·출전 ID를 읽고 날짜 상한을 지원.
- `features/canonical_sections.py`: 엄격한 wide canonical 관측 변환.
- `features/canonical_energy.py`: 신규 이름의 rolling research feature 10개.
- `features/__init__.py`: 기존 feature set을 건드리지 않고 canonical set 2개 등록.
- `dataset.py`: 날짜 상한 전달과 canonical dataset의 파일·코드·diff·원천 manifest hash 기록.
- `prediction_frame.py`: 미래 날짜 원천 조회 차단. legacy 같은 날 앞 경주 계약은 보존.
- `cli.py`: canonical feature set을 데이터셋 명령 선택지에만 추가.
- `tests/test_features_canonical_sections.py`: 변환·불변성 회귀검증.
- `scripts/audit_canonical_sections.py`: 읽기 전용 원천/coverage 감사 재현.
- `scripts/compare_canonical_section_runs.py`: paired validation 지표와 bootstrap 재현.

기존 feature 이름과 계산은 바꾸지 않았다. 기존 V5 artifact
`a30cd09a-3b7b-402a-b010-5e7341fd4144`를 기존 고정 데이터에 다시 추론한 6,969행은 저장
prediction과 bit-for-bit 동일했고 최대 float 차이는 0이었다. 결과는
`data/logs/canonical_section_legacy_inference_check_20260911.json`에 있다.

## 4. 데이터 계약

- cumulative checkpoint: 출발부터 측정 지점까지의 명시 누적시간.
- `last_600_ms`: G3F가 cumulative면 같은 과거 출전 `FIN-G3F`, closing이면 원값.
- `last_200_ms`: G1F가 cumulative면 같은 과거 출전 `FIN-G1F`, closing이면 원값.
- `middle_400_ms`: 두 값이 유효하고 `last_600 > last_200`일 때만 두 값의 차이.
- S1F: cumulative로 명시된 양의 시간만 사용. 서울·부경과 일반 제주는 200m, 제주
  1,110m·1,610m는 공식 계약에 따라 210m다.
- cumulative G3F/G1F 자체도 closing 입력이면 `FIN-closing`으로 복원해 별도 보존한다.
- `time_basis`가 NULL/기타이면 unavailable이다. 경마장이나 숫자 크기로 추정하지 않는다.
- FIN 결측, 착순 1..89 밖의 특수결과, 0/음수, checkpoint가 FIN 이후, G3F/G1F 순서 오류,
  같은 section code 중복은 정상 profile로 만들지 않는다.
- 미확정 코너 위치는 속도나 거리 feature로 만들지 않는다.
- 대상 출전은 horse별 날짜/출전 ID 순 정렬 뒤 `shift(1)`로 제외한다. 학습과 label-free 경로는
  같은 canonical module을 사용하며, 대상 결과를 제거한 단위 테스트와 포함한 테스트가 같다.
- DB 조회 상한은 데이터셋 `end_date`, 추론은 대상 날짜다. 신규 데이터는 서울만, 학습
  ≤2026-02-28, 개발 validation 2026-03-01~05-31이다.

## 5. 검증 결과

실행 명령:

```text
.venv/bin/python scripts/audit_canonical_sections.py
.venv/bin/ruff check <관련 Python 파일>
.venv/bin/pytest -q tests/test_features_canonical_sections.py tests/test_features_energy.py \
  tests/test_features.py tests/test_dataset.py tests/test_prediction_frame.py tests/test_model_profiles.py
.venv/bin/horse-racing build-dataset --version section_legacy_seoul_v1 --as-of \
  start_minus_30m --start 20160101 --end 20260531 --meets 1 --feature-set racefit_history
.venv/bin/horse-racing build-dataset --version section_canonical_seoul_v1 --as-of \
  start_minus_30m --start 20160101 --end 20260531 --meets 1 \
  --feature-set racefit_canonical_history
.venv/bin/horse-racing train-model --version <각 버전> --as-of start_minus_30m \
  --profile racefit_v5_sand --seed 42 --calibration auto
.venv/bin/python scripts/compare_canonical_section_runs.py <보고서의 run 인자>
```

관련 선택 테스트는 48 passed, warning 1건(기존 Polars sortedness 경고)이었다. 전체 pytest는
387 passed, warning 2건(Starlette deprecation과 기존 Polars sortedness)이었다. 이번 변경 파일
Ruff는 PASS다. 전체 저장소 Ruff는 이번 변경 밖의 `scripts/analysis_finish_time_quality.py` 등
4개 파일에 있던 21건 때문에 FAIL했다. 관련 없는 파일은 수정하지 않았다.

필수 검증 대응:

1. 같은 주행의 cumulative/closing 입력은 6개 canonical 값이 완전히 같았다.
2. 서울 1681 사례는 위 수치와 일치했다.
3. 대상 결과/구간을 제거하거나 99초로 바꿔도 대상 사전 feature가 같았다.
4. 미래 출전을 추가하고 120초로 바꿔도 과거 대상 feature가 같았다.
5. unknown, 음수 차분, 중복, 특수결과를 unavailable 처리했다. FIN 결측도 같은 guard를 쓴다.
6. 위의 경마장×원천×거리 원문 표본은 전부 DB 저장값과 일치했다.
7. 기존 artifact 고정 추론 6,969행이 exact equal이었다.
8. 학습 anchor 포함/label-free처럼 대상 구간 제외 입력이 같은 canonical feature를 만들었다.

## 6. 통제 실험 결과

두 데이터셋은 각각 15,531행, 1,488경주이고 실제 유효 기간은 2025-01-04~2026-05-31이다.
이전 경주의 예정시각 결측으로 2016~2024 행은 기존 정책대로 제외됐다. validation은 3,038행,
288경주이며 동착은 0경주였다. 동착 발생 시 공동우승 확률 합을 winner event 확률로 쓰고,
TopK는 공동우승 중 하나가 포함되면 hit로 정했다.

| 정의 | run ID | race winner NLL | binary LL | Brier | Top1 | winner Top3 | winner Top5 |
|---|---|---:|---:|---:|---:|---:|---:|
| legacy | `8eed3487-3ea1-4900-ad00-7d14cf6949cc` | 1.920890 | 0.266981 | 0.076934 | 33.33% | 62.85% | 85.07% |
| canonical | `55456a89-f784-47b0-a704-0fe30562288e` | 1.923828 | 0.266987 | 0.076640 | 30.56% | 64.58% | 85.76% |

primary race winner NLL의 canonical−legacy paired 차이는 +0.002938(양수는 악화), 경주 bootstrap
5,000회 95% CI `[-0.030749, +0.036740]`다. 개최일 28개 block bootstrap은
`[-0.027583, +0.034556]`다. 개선 증거가 없다. 반면 Brier와 Top3/Top5는 소폭 좋아졌으므로
정확한 의미 변환과 예측력 결론은 분리한다.

validation canonical 기본 feature coverage는 S1F/last600/last200/middle400 및 파생 평균
각 95.98%, trend 79.53%, 정확거리 balance 79.46%, count 100%다. TopK RPS와 ordered Top3
NLL은 이번 binary bundle이 지원하지 않아 생성하지 않았다. 전체 수치는
`data/experiments/section_canonical_v1/comparison.json`에 있다.

데이터 hash는 legacy
`77716dee69d8bd1bddec82c81c5a3e26c820651727f038904e74fb0c0802f44a`, canonical
`f1048c4b4df8cb78dcf310f1543eece30f474741c81d79fecf444766737d9aba`다. canonical manifest는
feature hash, 데이터 hash, 변환 코드 hash, tracked diff hash, 원천 감사 manifest hash를
함께 기록한다.

판정은 **보류**다. 의미 정상화는 채택하되 예측 후보로 승격하지 않는다. B 결과 뒤 C(legacy
누적정보와 canonical 종반정보 병합)는 primary NLL 개선 증거가 없고 비교 자유도를 늘리므로 이번
실행에서 제외했다. 향후 C를 사전등록한다면 변수 목록은 legacy energy 9개와 canonical energy
10개로 고정하고 같은 비교 조건을 유지해야 한다.

재현 비교 명령:

```text
.venv/bin/python scripts/compare_canonical_section_runs.py \
  --legacy-run 8eed3487-3ea1-4900-ad00-7d14cf6949cc \
  --canonical-run 55456a89-f784-47b0-a704-0fe30562288e --iterations 5000 \
  --output data/experiments/section_canonical_v1/comparison.json
```

## 7. 검증 담당자 인수인계

가장 의심해야 할 부분은 (1) NULL provenance를 unavailable로 둔 결과 서울 외에는 비교가
불가능하다는 점, (2) 서울 비교의 seed가 42 하나뿐이라는 점, (3) 기존 정상완주 조건부 라벨과
예정시각 가용 행만 남아 모집단이 제한된 점이다. `canonical_sections.py`의 중복/순서 guard,
`base.py`의 날짜 상한 SQL, dataset manifest의 dirty-worktree 재현 hash를 우선 검토해야 한다.

다음 단계 진행을 막는 코드 오류는 현재 없다. 다만 서울 외 확대에는 원문→DB 행 provenance를
복원하는 별도 작업이 선행돼야 하며, 현재 결과만으로 운영 교체·승격·실전 베팅을 하면 안 된다.
