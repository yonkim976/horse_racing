# 서울·부경·영천 통합 경주 연구 데이터셋

이 디렉터리는 2026-09-18 기준으로 서울(`meet=1`), 부산경남(`meet=3`), 영천(`meet=4`)의 더러브렛 경주 이력을 공식 ID로 연결한 격리 산출물이다. 기존 운영 DB, 모델, registry와 제주 데이터는 수정하지 않았다.

## 바로 사용할 파일

- `thoroughbred_unified.duckdb`: 정규화 원천 테이블, 사건 테이블, 연결 테이블, 학습용 테이블을 포함한 주 데이터베이스
- `parquet/model_training_entry.parquet`: 2006년 이후 확정 경주 410,168출전행의 학습용 허용 열과 `target_*` 목표값
- `parquet/model_target_entry.parquet`: 모델 대상 출전행의 상세 원본·연결 열. 결과·배당 열을 포함하므로 피처 선택에 직접 쓰지 않는다.
- `coverage_year_source.csv`: 개최지×자료 종류×연도별 행 수, 객체 수, 말 수, 공식 ID 연결률, 최초·최종일
- `parquet/unresolved_identity_ledger.parquet`: 진료·체중·주행심사·관계자 ID 등 미확정 연결의 행 단위 원장
- `unresolved_identity_summary.csv`: 미확정 유형별 요약
- `validation.json`: 빌드 내부 검증
- `independent_validation.json`: 별도 검증 스크립트의 원본 DB 재대조 결과
- `manifest.json`: 원천 DB, 코드, 문서, 출력 파일의 크기와 SHA-256

## 사용 예

```python
import duckdb

con = duckdb.connect(
    "data/research/thoroughbred_unified_20260918/thoroughbred_unified.duckdb",
    read_only=True,
)

# 기본 학습 모집단. target_* 외 열 중에서도 availability note를 확인한다.
train = con.sql("""
    SELECT *
    FROM model_training_entry
    WHERE race_date < DATE '2026-01-01'
""").df()

# 시간 순서 검증/시험 분할 예시
valid = con.sql("""
    SELECT * FROM model_training_entry
    WHERE race_date BETWEEN DATE '2026-01-01' AND DATE '2026-06-30'
""").df()
```

`model_training_entry`의 과거 성적·조교·진료 집계는 항상 현재 경주일보다 앞선 사건만 사용한다. 당일 마체중과 주로·날씨는 과거 공개 시각이 완전히 증명되지 않았으므로 기본 실험에서는 제외하고, 별도 가용성 실험에서만 사용한다. `target_*` 열은 목표값이며 입력 피처가 아니다.

## 키와 개최지

- 경주 키: `race_id = RACE:{venue_code}:{YYYYMMDD}:{race_no}`
- 출전 키: `(race_id, hr_no)`
- 말 전역 키: 공식 `hr_no`
- 사람 키: 공식 `jockey_no`, `trainer_no`, `owner_no`
- 개최지: `SEOUL`, `BUSAN`, `YEONGCHEON`

영천은 영남 권역에 속하지만 공식 `meet=4`인 별도 개최지다. 2026-09-13의 영천 6경주·54출전행은 부산으로 넣지 않았다. 영천 분리 뒤 `meet=3`으로 제공된 2026-09-17 주행심사 48행은 실제 개최지를 증명할 수 없어 `YEONGNAM_UNRESOLVED`로 보존했다.

## 재현

출력 경로는 존재하지 않는 새 디렉터리를 지정한다. 이는 부분 갱신 중복을 피하고 기존 버전을 보존하기 위한 방식이다.

```bash
cd /Users/kimyongjin/Desktop/horse_racing
PYTHONPATH=src .venv/bin/python scripts/build_unified_thoroughbred_dataset.py \
  --output data/research/thoroughbred_unified_YYYYMMDD

PYTHONPATH=src .venv/bin/python scripts/verify_unified_thoroughbred_dataset.py \
  --database data/research/thoroughbred_unified_YYYYMMDD/thoroughbred_unified.duckdb \
  --output data/research/thoroughbred_unified_YYYYMMDD/independent_validation.json

PYTHONPATH=src .venv/bin/python scripts/finalize_unified_thoroughbred_dataset.py \
  --output data/research/thoroughbred_unified_YYYYMMDD
```

빌드는 원천 SQLite를 `mode=ro`와 `query_only`로 열고 새 DuckDB를 처음부터 만든다. 같은 원천으로 다시 실행해도 기본키 중복 삽입이 생기지 않는다. 새 공식 데이터가 들어오면 날짜가 붙은 새 버전을 만들고 검증 후 교체하거나 상위 통합 DB가 읽도록 한다.

## 현재 한계

- 영천은 2026-09-13의 6경주뿐이므로 영천 전용 학습 표본으로는 부족하다.
- 부경 구간기록은 원천별 의미 검증 전이라 `source_specific_unverified`이며 서울·영천의 누적시간 열과 직접 합치지 않았다.
- 과거 Text 진료의 확정 연결률은 서울 27.3%, 부경 32.7%다. 미확정 행은 이름만으로 배정하지 않았다.
- 경주 출전행 중 조교사·마주 공식 ID 결측은 서울 59행, 부경 21행이다.
- 주행심사 원천 충돌 4건과 부산 과거 주행심사 신원 미확정 5건을 보존했다.
