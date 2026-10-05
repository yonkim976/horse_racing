# 주로 함수율과 과거 경주기록의 공통 시간 변동: 최종 보고서

작성일: 2026-09-28 · 자료 기간: 2018-01-05~2026-09-20 · 연구 전용, 운영 미적용

## 1. 연구과제

과거 경주의 출발 200m, 마지막 200m, 마지막 600m, 전체기록에 섞인 **주로 환경의 공통 시간 변동**을 초 단위로 가늠한다. 특정 말의 불량 주로 적성을 찾거나 경주 중앙마의 절대기록을 보정 기준으로 삼지 않는다. 함수율과 기록이 선형으로 변한다고 가정하지 않고, **함수율 구간별 차이**와 시간 순서 검증을 본다.

환경효과 `e`는 비교 기준보다 시간이 길면 **양수**, 짧으면 **음수**다. 기술적인 환산은 `보정기록 = 원시기록 − e`다. 예를 들어 `e = −0.5초`이면 원시기록에 0.5초를 더하는 방향이다. 이는 관찰 자료의 평균 차이이며 개별 말에 적용되는 확정 인과효과가 아니다. 마지막 200m는 마지막 600m에 포함되므로 합산하지 않는다.

## 2. 방법

### 자료·라벨·시점

- 한국마사회 [경주로 현황](https://race.kra.co.kr/chulmainfo/trackView.do?Act=02&Sub=10&meet=1)의 함수율 구분을 따랐다: 건조 1~5%, 양호 6~9%, 다습 10~14%, 포화 15~19%, 불량 20% 이상. 해당 페이지는 오전 9시 함수율·상태를 공개한다. 현지 강우·살수·모래 관리에 따라 하루 중 조건이 달라질 수 있다. 로컬 자료에서 불량의 숫자 함수율은 모두 정수 **20**으로 저장되어 20% 이상의 세부 차이를 분석할 수 없다.
- 구간시간은 읽기 전용 `data/research/section_point_db_20260925/section_points_adjudicated.sqlite3`의 `common_point`, 경주 메타정보는 읽기 전용 `data/horse_racing.sqlite3`의 `races`, `race_entries`, `race_results`, `race_passing_summaries`에서 가져왔다. 결합된 원천은 **210,747두 기록**, 함수율이 있는 것은 **201,159건**이다. 두 수는 아래 검증 적격 표본 수가 아니다. 2025년 이후 서울 막판 일부 기록처럼 직접 구간시간이 없으면 공식 완주시간에서 누적 통과시간을 뺀다. 물리 범위와 구간 정합성을 검사했다.
- 주로빠르기는 경주 **후** 산정되는 지표다. [상세 성적표](https://race.kra.co.kr/raceScore/ScoretableDetailList.do?Act=04&Sub=1&meet=1&realRcDate=20260906&realRcNo=9)에 결과와 함께 표시되지만, 공식 산식·대상 경주 기록의 포함 여부·최초 확정 시각은 확인하지 못했다. 대상 경주 기록이 지표를 만드는 **순환성 위험**이 있어 사전 기대시간과 함수율 주 분석에는 넣지 않았다. 완료된 과거 경주의 라벨 비교에서만 사용했다.

### 추정 및 검증

1. 같은 말·경기장·**정확히 같은 거리**의 1~365일 전 출전이 있는 관측치에서 각 시간 목표의 사전 기대시간을 따로 만들었다. 각 대상 연도보다 **이전 연도** 자료로만 Ridge 모형을 학습했다. 입력은 같은 거리의 직전 1·2회 시간, 최근 출전 간격, 현재 편성 거리·등급·월·부담중량·게이트다. 대상 경주의 실제시간·착순·함수율·주로빠르기는 입력하지 않았다. 부상·훈련·기수와 휴양 후 회복은 충분히 설명하지 못한다.
2. 말별 `실제시간 − 사전 기대시간`을 구했다. 이런 잔차가 있는 말이 4두 이상인 경주에서 **잔차 중앙값**을 구해 공통 변동의 관측값으로 썼다. 이는 중앙마의 **절대기록**이 아니다. 함수율 구간별 차이는 경주를 같은 비중으로 두고 거리·연도·월·경주 번호를 조정했다. 불확실성은 같은 경주일을 공유하는 관측치의 의존성을 반영한 경주일 군집 근사구간이다.
3. 각 경주의 당일 효과는 그 경주를 제외한 **다른 경주**의 잔차만으로 만들었다. 경주 번호가 가까울수록 더 크게 가중하고 다른 경주가 3개 미만이면 당일 효과를 0으로 되돌렸다. 과거 조건 모형에서도 각 대상 경주의 결과가 자기 효과 계수에 들어가지 않도록 Ridge의 leave-one-race-out 계산을 했다. 당일 효과는 과거 조건 평균 쪽으로 수축했다.
4. **2024·2025·2026년 홀드아웃**에서 두 질문을 구분했다. 첫째, 해당 경주의 공통 잔차를 `함수율 없음 / 상태 5구간 / 상태+정확한 정수 %`로 예측했다. 둘째, 이전 경주의 기록을 보정해 **말의 다음 동일 거리 경주**를 예측했다. 이때 이전 경주까지 평가연도보다 앞선 것만 썼고 `사전 기대만 / 보정 없음 / 상태만 / 빠르기만 / 둘 다 / 다른 경주 당일 잔차`를 비교했다. 코드는 기대시간 Ridge α=20, 경주 잔차 Ridge α=25, 이전 기록 잔차 반영률 0.5를 고정해 사용한다.

## 3. 결과

### 함수율 구간의 대략적인 시간 차이

다음은 **포화 15~19% − 건조 1~5%**의 관찰 차이(초)다. 음수는 포화에서 시간이 짧은 방향이다. 경주일 수는 건조/포화 순서이며 대괄호는 **경주일 군집 95% 근사구간**이다. 전체기록은 표시된 거리의 실제 초 단위다.

| 경기장·거리 | 경주일 수 | 출발 200m | 마지막 200m | 마지막 600m | 전체기록 |
|---|---:|---:|---:|---:|---:|
| 서울 1200m | 218/96일 | -0.121 [-0.149, -0.093] | -0.094 [-0.161, -0.027] | -0.181 [-0.316, -0.047] | **-0.534 [-0.718, -0.350]** |
| 부산 1200m | 336/54일 | -0.142 [-0.180, -0.105] | -0.135 [-0.229, -0.041] | -0.281 [-0.485, -0.077] | **-0.688 [-0.964, -0.411]** |
| 제주 1000m | 238/72일 | -0.052 [-0.123, +0.019] | -0.033 [-0.152, +0.086] | -0.158 [-0.362, +0.047] | **-0.178 [-0.461, +0.104]** |

서울·부산 1200m에서는 포화 조건의 기록이 대략 **0.5~0.7초 빠른 방향**이었다. 제주 1000m 전체기록 구간은 0을 포함한다. 함수율이 높아질수록 매번 빨라지는 모양은 아니다. 모든 거리를 모아 거리 차이를 조정한 **양호 6~9% − 건조** 전체기록은 서울 **+0.111 [-0.009, +0.232]초**, 부산 **+0.188 [+0.052, +0.325]초**로 오히려 느린 방향이다. 서울의 구간은 0을 포함한다. 불량은 서울 **11일**, 부산 **7일**, 제주 **16일**뿐이어서 별도 고정 초 보정 근거가 약하다.

### 시간 순서 검증 ①: 경주 공통 잔차

2024년에는 2023년까지, 2025년에는 2024년까지, 2026년에는 2025년까지의 계수만 썼다. 표는 경주 공통 잔차 평균절대오차(MAE, 초; 낮을수록 좋음)다. `함수율 없음`도 거리·월·연도 추세·경주 번호는 사용한다. 정확한 %의 드문 값은 Ridge로 수축했다. 대상 경주의 실제시간은 예측 입력이 아니다.

| 경기장 | 목표 | 평가 경주 | 함수율 없음 | 상태 5구간 | 상태+정확한 % |
|---|---|---:|---:|---:|---:|
| 서울 | 출발 200m | 2,610 | 0.1510 | 0.1443 | 0.1440 |
| 서울 | 마지막 200m | 2,610 | 0.3430 | 0.3426 | 0.3417 |
| 서울 | 마지막 600m | 2,610 | 0.6738 | 0.6718 | 0.6706 |
| 서울 | 전체기록 | 2,610 | 0.7748 | 0.7379 | 0.7422 |
| 부산 | 출발 200m | 1,799 | 0.1371 | 0.1317 | 0.1315 |
| 부산 | 마지막 200m | 1,799 | 0.3260 | 0.3241 | 0.3276 |
| 부산 | 마지막 600m | 1,799 | 0.7175 | 0.7114 | 0.7169 |
| 부산 | 전체기록 | 1,799 | 0.8820 | 0.8537 | 0.8540 |
| 제주 | 출발 200m | 1,310 | 0.2635 | 0.2627 | 0.2635 |
| 제주 | 마지막 200m | 1,815 | 0.4849 | 0.4890 | 0.4901 |
| 제주 | 마지막 600m | 1,815 | 0.7853 | 0.7838 | 0.7891 |
| 제주 | 전체기록 | 1,815 | 1.0587 | 1.0603 | 1.0627 |

서울 전체기록의 `상태 − 없음` 평균 MAE 차이는 **-0.0369초**, 경주일 대응 부트스트랩 95% 구간 **[-0.053, -0.0208]**다. 부산은 **-0.0283초**, **[-0.0452, -0.0127]**다. 두 경기장의 전체기록은 세 평가연도 각각에서도 개선 방향이었다. 출발 200m도 개선했지만 마지막 구간은 작거나 불안정했고, 제주는 전체기록에서 개선이 없었다. 이 설정에서 정확한 정수 %는 상태 구간보다 안정적인 추가 이득을 보이지 않았다.

### 시간 순서 검증 ②: 말의 다음 경주 시간

아래는 다음 동일 거리 경주의 평균절대오차(MAE, 초)다. `기대만`은 다음 경주의 사전 기대시간만 쓴다. 나머지는 이전 경주의 말별 잔차를 절반 반영하며 그 잔차에서 무엇을 보정했는지에 따라 나뉜다. `당일`은 대상 이전 경주를 제외한 다른 경주 잔차를 추가한 후보이다.

| 경기장 | 목표 | 다음 출전 | 기대만 | 보정 없음 | 상태 | 빠르기 | 둘 다 | 당일 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 서울 | 출발 200m | 3,864 | 0.288 | 0.319 | 0.317 | 0.317 | 0.315 | 0.316 |
| 서울 | 마지막 200m | 3,864 | 0.568 | 0.625 | 0.623 | 0.621 | 0.622 | 0.619 |
| 서울 | 마지막 600m | 3,864 | 1.024 | 1.137 | 1.131 | 1.120 | 1.122 | 1.112 |
| 서울 | 전체기록 | 3,864 | 1.213 | 1.443 | 1.403 | 1.358 | 1.353 | 1.338 |
| 부산 | 출발 200m | 2,716 | 0.259 | 0.281 | 0.280 | 0.280 | 0.280 | 0.280 |
| 부산 | 마지막 200m | 2,716 | 0.563 | 0.622 | 0.622 | 0.620 | 0.620 | 0.615 |
| 부산 | 마지막 600m | 2,716 | 1.118 | 1.234 | 1.233 | 1.226 | 1.227 | 1.216 |
| 부산 | 전체기록 | 2,716 | 1.356 | 1.530 | 1.518 | 1.485 | 1.483 | 1.473 |
| 제주 | 출발 200m | 1,534 | 0.378 | 0.438 | 0.438 | 0.443 | 0.443 | 0.438 |
| 제주 | 마지막 200m | 2,183 | 0.894 | 1.017 | 1.005 | 1.021 | 1.010 | 1.016 |
| 제주 | 마지막 600m | 2,183 | 1.562 | 1.783 | 1.751 | 1.788 | 1.761 | 1.753 |
| 제주 | 전체기록 | 2,183 | 1.832 | 2.188 | 2.164 | 2.209 | 2.181 | 2.098 |

**모든 경기장·목표에서 `기대만`이 가장 낮은 오차**였다. 보정 후보는 이전 기록을 그대로 반영하는 `보정 없음`보다 일부 나았지만, 단순 사전 기대시간을 이기지 못했다. 실패 사례도 있다. 이전 경주가 제주 900m `건조+②`인 50회 출전(21일)의 다음 경주 마지막 600m에서 `당일`은 `보정 없음`보다 MAE가 **+0.112초 악화**했다. 부산 1800m `건조+⑥` 76회 출전(23일)의 다음 전체기록에서는 **+0.043초 악화**했다. 작은 조합별 차이는 확정 규칙이 아니다. 2026년 제주 마지막 600m의 당일 후보도 `보정 없음`보다 악화했다.

### 결론과 사용 범위

- **추가 검증 필요 — 완료된 과거 경주의 잠정 해석 보정:** 서울·부산에서 포화 15~19% 기록이 건조 1~5%보다 빠른 방향인 관찰적 초 차이를 확인했다. 원시기록 옆에 경기장·거리·함수율 구간·구간별 추정치·경주일 수·불확실성을 표시하면 빠른 기록을 말의 능력만으로 해석하는 오류를 줄이는 참고 자료가 된다. 개별 말의 확정 보정값으로 기계적으로 쓰지 않는다.
- **사용 보류 — 운영 자동 보정과 예측 입력:** 보정 후보가 `기대만` 기준을 이기지 못했다. 사후 주로빠르기의 순환성도 해소되지 않았다. 불량 20% 이상과 경주일이 적은 거리·상태·빠르기 조합은 `근거 부족`으로 표시한다. 이번 연구에서 **채택 가능**한 운영 보정식은 없다.
- 물리적 주로 효과와 경주 전개, 참가마 구성, 말 컨디션, 살수·강우, 사후 산정 지표를 완전히 분리하지 못했다. 경주 번호 조정과 경주일 군집구간도 이 구조적 편향을 없애지 않는다. 함수율별 결과를 모든 말에 같은 초가 작용하는 인과효과로 해석해서는 안 된다.

보정값을 저장한다면 원시기록을 덮어쓰지 않고 별도 파생 레코드에 `raw_ms`, `estimated_environment_effect_ms`, `adjusted_ms`, `part`, `meet`, `distance_m`, `moisture_band`, `method_version`, `trained_through`, `source`, `support_horses`, `support_races`, `support_days`, `ci95_lower_ms`, `ci95_upper_ms`, `support_status`를 함께 둔다. 추가 경주를 반영해 값이 달라지면 추정 시점과 버전을 분리한다.

## 4. 재실행

저장소 최상위 디렉터리에서 아래 명령을 실행한다. **이 보고서 하나에 포함된 코드**를 메모리에서 실행하며, 두 원천 SQLite는 `mode=ro`로 열고 결과 JSON은 표준출력에만 쓴다. 필요한 패키지는 저장소 `.venv`의 `numpy`, `pandas`, `scikit-learn`이다. 원천 DB의 내용이 바뀌면 결과도 달라질 수 있다. 이 보고서 표의 초 값은 코드 출력에서 반올림했다.

```bash
.venv/bin/python - <<'PYCODE'
from pathlib import Path
report = Path('research/track_common_residual_20260928/FINAL_REPORT_KO.md').read_text()
code = report.split('<!-- REPRODUCE_PY_START -->\n```python\n', 1)[1].split('\n```\n<!-- REPRODUCE_PY_END -->', 1)[0]
exec(compile(code, 'embedded_track_research.py', 'exec'), {'__name__': '__main__'})
PYCODE
```

아래 코드는 외부에 임시 `.py` 파일을 만들지 않아도 실행된다.

<!-- REPRODUCE_PY_START -->
```python
"""Standalone, read-only reconstruction of the track residual study."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path.cwd()
SECTION_DB = ROOT / "data/research/section_point_db_20260925/section_points_adjudicated.sqlite3"
RACE_DB = ROOT / "data/horse_racing.sqlite3"
MEETS = {1: "서울", 2: "제주", 3: "부산"}
PARTS = ("start_200", "last_200", "last_600", "finish")
BANDS = ("건조", "양호", "다습", "포화", "불량")


def read_data() -> tuple[pd.DataFrame, dict]:
    with sqlite3.connect(f"file:{SECTION_DB}?mode=ro", uri=True) as con:
        con.execute(f"ATTACH DATABASE 'file:{RACE_DB}?mode=ro' AS ops")
        con.execute("PRAGMA query_only=ON")
        raw = pd.read_sql_query(
            """
            SELECT c.race_entry_id, c.meet_code, c.race_date,
                   c.race_number, c.distance_m, c.point_code,
                   c.time_kind, c.elapsed_time_ms,
                   re.horse_id, re.gate_number, re.carried_weight_kg,
                   r.grade, r.track_condition, r.track_moisture_percent,
                   p.tempo_raw, rr.finish_time_ms
            FROM common_point c
            JOIN ops.race_entries re ON re.id=c.race_entry_id
            JOIN ops.races r ON r.id=re.race_id
            JOIN ops.race_results rr ON rr.race_entry_id=re.id
            LEFT JOIN ops.race_passing_summaries p ON p.race_id=r.id
            WHERE c.race_date BETWEEN '2018-01-01' AND '2026-09-20'
              AND c.meet_code IN (1,2,3)
              AND c.point_code IN ('S1F','G1F','G3F')
              AND rr.finish_position BETWEEN 1 AND 20
              AND rr.finish_time_ms > 0
              AND r.track_condition IN ('건조','양호','다습','포화','불량')
            """,
            con,
        )
    if raw.duplicated(["race_entry_id", "point_code", "time_kind"]).any():
        raise ValueError("duplicate section keys")
    meta = raw.drop_duplicates("race_entry_id").set_index("race_entry_id")
    wide = raw.pivot(
        index="race_entry_id", columns=["point_code", "time_kind"], values="elapsed_time_ms"
    )
    wide.columns = ["_".join(x) for x in wide.columns]
    rec = meta.join(wide)
    rec["start_200"] = rec.get("S1F_cumulative", np.nan) / 1000
    for point, part in (("G1F", "last_200"), ("G3F", "last_600")):
        direct = rec.get(f"{point}_closing", pd.Series(np.nan, index=rec.index))
        cumulative = rec.get(f"{point}_cumulative", pd.Series(np.nan, index=rec.index))
        rec[part] = direct.fillna(rec["finish_time_ms"] - cumulative) / 1000
    rec["finish"] = rec["finish_time_ms"] / 1000
    rec["meet"] = rec["meet_code"].map(MEETS)
    rec["date"] = pd.to_datetime(rec["race_date"])
    rec["year"] = rec["date"].dt.year
    rec["month"] = rec["date"].dt.month
    rec["grade"] = rec["grade"].fillna("미상")
    rec["band"] = rec["track_condition"]
    rec["race_key"] = rec["meet"] + ":" + rec["race_date"] + ":" + rec["race_number"].astype(str)
    rec["day_key"] = rec["meet"] + ":" + rec["race_date"]
    for part, (lo, hi) in {
        "start_200": (10, 40),
        "last_200": (8, 45),
        "last_600": (30, 100),
    }.items():
        rec.loc[~rec[part].between(lo, hi) | rec[part].ge(rec["finish"]), part] = np.nan
    bad = rec["last_200"].gt(rec["last_600"])
    rec.loc[bad, ["last_200", "last_600"]] = np.nan
    speed = rec["distance_m"] / rec["finish"]
    min_speed = np.where(rec["meet"].eq("제주"), 8, 10)
    max_speed = np.where(rec["meet"].eq("제주"), 16, 20)
    rec.loc[~speed.between(min_speed, max_speed), "finish"] = np.nan
    source = {
        "raw_section_rows": int(len(raw)),
        "runners": int(len(rec)),
        "moisture_runners": int(rec["track_moisture_percent"].notna().sum()),
        "date_min": str(rec["race_date"].min()),
        "date_max": str(rec["race_date"].max()),
    }
    return rec.reset_index(), source


def history_for_part(rec: pd.DataFrame, part: str) -> pd.DataFrame:
    df = rec[rec[part].notna()].copy()
    df = df.sort_values(["meet", "horse_id", "distance_m", "date", "race_number"])
    group = df.groupby(["meet", "horse_id", "distance_m"], sort=False)
    df["prev_time"] = group[part].shift(1)
    df["prev2_time"] = group[part].shift(2)
    df["prev_date"] = group["date"].shift(1)
    df["gap_days"] = (df["date"] - df["prev_date"]).dt.days
    df = df[df["gap_days"].between(1, 365)].copy()
    df["prev2_time"] = df["prev2_time"].fillna(df["prev_time"])
    df["gap_days"] = np.log1p(df["gap_days"])
    df["gate_number"] = df["gate_number"].fillna(0)
    df["carried_weight_kg"] = df["carried_weight_kg"].fillna(df["carried_weight_kg"].median())
    df["target"] = df[part]
    df["part"] = part
    return df


EXPECT_CAT = ["distance_m", "grade", "month"]
EXPECT_NUM = ["prev_time", "prev2_time", "gap_days", "carried_weight_kg", "gate_number"]


def expectation_model(train: pd.DataFrame) -> Pipeline:
    prep = ColumnTransformer(
        [
            ("cat", OneHotEncoder(handle_unknown="ignore"), EXPECT_CAT),
            (
                "num",
                Pipeline(
                    [("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]
                ),
                EXPECT_NUM,
            ),
        ]
    )
    model = Pipeline([("prep", prep), ("ridge", Ridge(alpha=20.0))])
    model.fit(train[EXPECT_CAT + EXPECT_NUM], train["target"])
    return model


def expected_residuals(rec: pd.DataFrame) -> pd.DataFrame:
    out = []
    for part in PARTS:
        hist = history_for_part(rec, part)
        for meet in MEETS.values():
            one = hist[hist["meet"].eq(meet)]
            for year in range(2020, 2027):
                train = one[one["year"].lt(year)]
                test = one[one["year"].eq(year)].copy()
                if len(train) < 100 or test.empty:
                    continue
                model = expectation_model(train)
                test["expected"] = model.predict(test[EXPECT_CAT + EXPECT_NUM])
                test["residual"] = test["target"] - test["expected"]
                out.append(test)
    return pd.concat(out, ignore_index=True)


def race_residuals(horse: pd.DataFrame) -> pd.DataFrame:
    key = ["part", "race_key"]
    x = (
        horse.groupby(key, sort=False)
        .agg(residual=("residual", "median"), runners=("residual", "size"))
        .reset_index()
    )
    fields = [
        "meet",
        "date",
        "year",
        "month",
        "distance_m",
        "race_number",
        "day_key",
        "band",
        "track_moisture_percent",
        "tempo_raw",
    ]
    x = x.merge(horse.drop_duplicates(key)[key + fields], on=key, validate="one_to_one")
    return x[x["runners"].ge(4)].copy()


def cluster_ols(df: pd.DataFrame, contrast: str, fixed_distance: bool = False) -> dict:
    # Dry is the reference; OLS gets equal weight per race.
    cat = ["band", "year", "month"] + ([] if fixed_distance else ["distance_m"])
    dummies = pd.get_dummies(df[cat].astype(str), dtype=float)
    dummies = dummies.drop(
        columns=[
            c
            for c in dummies
            if c in ("band_건조", "year_2020", "month_1")
            or c.startswith("distance_m_")
            and c == sorted(z for z in dummies if z.startswith("distance_m_"))[0]
        ]
    )
    x = np.column_stack([np.ones(len(df)), dummies.to_numpy(), df["race_number"].to_numpy(float)])
    names = ["intercept", *dummies.columns, "race_number"]
    y = df["residual"].to_numpy(float)
    inv = np.linalg.pinv(x.T @ x)
    beta = inv @ (x.T @ y)
    err = y - x @ beta
    scores = x * err[:, None]
    by_day = pd.DataFrame(scores).groupby(df["day_key"].to_numpy(), sort=False).sum().to_numpy()
    vcov = inv @ (by_day.T @ by_day) @ inv
    idx = names.index(f"band_{contrast}")
    estimate = beta[idx]
    se = np.sqrt(max(vcov[idx, idx], 0))
    return {
        "seconds": round(float(estimate), 4),
        "ci95": [round(float(estimate - 1.96 * se), 4), round(float(estimate + 1.96 * se), 4)],
    }


def contrasts(race: pd.DataFrame) -> list[dict]:
    out = []
    for meet in MEETS.values():
        for part in PARTS:
            all_ = race[
                race["meet"].eq(meet)
                & race["part"].eq(part)
                & race["track_moisture_percent"].notna()
            ]
            for distance in (None, 1200 if meet != "제주" else 1000):
                df = all_ if distance is None else all_[all_["distance_m"].eq(distance)]
                if df.empty:
                    continue
                for band in BANDS[1:]:
                    days = int(df.loc[df["band"].eq(band), "day_key"].nunique())
                    if days < 5:
                        continue
                    out.append(
                        {
                            "meet": meet,
                            "part": part,
                            "distance_m": distance,
                            "band": band,
                            "races": int(df["band"].eq(band).sum()),
                            "days": days,
                            "dry_days": int(df.loc[df["band"].eq("건조"), "day_key"].nunique()),
                            **cluster_ols(df, band, fixed_distance=distance is not None),
                        }
                    )
    return out


def race_model(train: pd.DataFrame, variant: str) -> Pipeline:
    cats = ["distance_m", "month"]
    if variant in ("state", "both", "exact"):
        cats.append("band")
    if variant in ("tempo", "both"):
        cats.append("tempo_raw")
    if variant == "exact":
        cats.append("moisture_exact")
    prep = ColumnTransformer(
        [
            ("cat", OneHotEncoder(handle_unknown="ignore"), cats),
            ("num", StandardScaler(), ["year", "race_number"]),
        ]
    )
    model = Pipeline([("prep", prep), ("ridge", Ridge(alpha=25.0))])
    model.fit(train[cats + ["year", "race_number"]], train["residual"])
    return model


def ready_races(race: pd.DataFrame) -> pd.DataFrame:
    df = race.copy()
    df["tempo_raw"] = df["tempo_raw"].fillna("결측")
    df["moisture_exact"] = df["track_moisture_percent"].fillna(-1).astype(int).astype(str)
    return df


def leave_one_race_out_effect(train: pd.DataFrame, variant: str, meet: str) -> np.ndarray:
    """Ridge counterfactual contrast with each race's outcome deleted analytically."""
    model = race_model(train, variant)
    cats = ["distance_m", "month"]
    if variant in ("state", "both"):
        cats.append("band")
    if variant in ("tempo", "both"):
        cats.append("tempo_raw")
    columns = cats + ["year", "race_number"]
    reference = train.copy()
    if variant in ("state", "both"):
        reference["band"] = "건조"
    if variant in ("tempo", "both"):
        reference["tempo_raw"] = "③" if meet == "제주" else "⑤"
    transform = model.named_steps["prep"].transform
    actual_x = transform(train[columns])
    reference_x = transform(reference[columns])
    if hasattr(actual_x, "toarray"):
        actual_x = actual_x.toarray()
        reference_x = reference_x.toarray()
    x = np.column_stack((np.ones(len(train)), actual_x))
    delta = np.column_stack((np.zeros(len(train)), actual_x - reference_x))
    y = train["residual"].to_numpy(float)
    penalty = np.eye(x.shape[1]) * 25.0
    penalty[0, 0] = 0
    inv = np.linalg.pinv(x.T @ x + penalty)
    beta = inv @ x.T @ y
    residual = y - x @ beta
    leverage = np.einsum("ij,jk,ik->i", x, inv, x)
    contrast_leverage = np.einsum("ij,jk,ik->i", delta, inv, x)
    return delta @ beta - contrast_leverage * residual / (1 - leverage)


def bootstrap_delta(df: pd.DataFrame, a: str, b: str, seed: int = 20260928) -> list[float]:
    rng = np.random.default_rng(seed)
    x = df[["day_key", a, b]].copy()
    x["difference"] = x[a] - x[b]
    days = x.groupby("day_key")["difference"].agg(["sum", "count"]).to_numpy()
    picks = rng.integers(0, len(days), size=(500, len(days)))
    draws = days[picks]
    sample = draws[:, :, 0].sum(axis=1) / draws[:, :, 1].sum(axis=1)
    return [round(float(z), 4) for z in np.quantile(sample, [0.025, 0.975])]


def holdout_moisture(race: pd.DataFrame) -> list[dict]:
    race = ready_races(race)
    out = []
    for meet in MEETS.values():
        for part in PARTS:
            one = race[
                race["meet"].eq(meet)
                & race["part"].eq(part)
                & race["track_moisture_percent"].notna()
            ]
            year_rows = []
            for year in (2024, 2025, 2026):
                train = one[one["year"].lt(year)]
                test = one[one["year"].eq(year)].copy()
                if len(train) < 100 or test.empty:
                    continue
                for variant in ("none", "state", "exact"):
                    model = race_model(train, variant)
                    test[f"err_{variant}"] = np.abs(test["residual"] - model.predict(test))
                test["holdout_year"] = year
                year_rows.append(test)
            if not year_rows:
                continue
            pooled = pd.concat(year_rows)
            for period, sample in [
                ("all", pooled),
                *[(str(y), pooled[pooled["holdout_year"].eq(y)]) for y in (2024, 2025, 2026)],
            ]:
                row = {
                    "meet": meet,
                    "part": part,
                    "year": period,
                    "races": len(sample),
                    "days": int(sample["day_key"].nunique()),
                    "mae": {
                        v: round(float(sample[f"err_{v}"].mean()), 4)
                        for v in ("none", "state", "exact")
                    },
                }
                if period == "all":
                    row["state_minus_none_ci95"] = bootstrap_delta(sample, "err_state", "err_none")
                    row["exact_minus_state_ci95"] = bootstrap_delta(
                        sample, "err_exact", "err_state"
                    )
                out.append(row)
    return out


def next_race_validation(horse: pd.DataFrame, race: pd.DataFrame) -> dict:
    race = ready_races(race)
    horse = horse.sort_values(
        ["meet", "part", "horse_id", "distance_m", "date", "race_number"]
    ).copy()
    group = horse.groupby(["meet", "part", "horse_id", "distance_m"], sort=False)
    for col in ("target", "expected", "year", "race_key"):
        horse[f"previous_{col}"] = group[col].shift(1)
    out = []
    cell_rows = []
    for meet in MEETS.values():
        for part in PARTS:
            r = race[race["meet"].eq(meet) & race["part"].eq(part)]
            h = horse[horse["meet"].eq(meet) & horse["part"].eq(part)]
            for year in (2024, 2025, 2026):
                train = r[r["year"].lt(year)]
                test = h[h["year"].eq(year) & h["previous_year"].lt(year)].copy()
                test = test[test["previous_expected"].notna()]
                if len(train) < 100 or test.empty:
                    continue
                prev = race[
                    race["year"].lt(year) & race["meet"].eq(meet) & race["part"].eq(part)
                ].copy()
                for variant in ("state", "tempo", "both"):
                    prev[f"effect_{variant}"] = leave_one_race_out_effect(train, variant, meet)
                prev["leftover"] = prev["residual"] - prev["effect_both"]

                # Other races on the same date only. No target-race result enters its own effect.
                def loo(day: pd.DataFrame) -> pd.Series:
                    number = day["race_number"].to_numpy(float)
                    values = day["leftover"].to_numpy(float)
                    w = np.exp(-np.abs(number[:, None] - number[None, :]) / 3)
                    np.fill_diagonal(w, 0)
                    total = w.sum(axis=1)
                    correction = np.divide(
                        w @ values, total + 4, out=np.zeros(len(day)), where=total > 0
                    )
                    correction[(w > 0).sum(axis=1) < 3] = 0
                    return pd.Series(correction, index=day.index)

                prev["day_extra"] = (
                    prev.groupby("day_key", group_keys=False)
                    .apply(loo, include_groups=False)
                    .reindex(prev.index)
                    .fillna(0)
                )
                prev["effect_day"] = prev["effect_both"] + prev["day_extra"]
                cols = [
                    "race_key",
                    "effect_state",
                    "effect_tempo",
                    "effect_both",
                    "effect_day",
                    "band",
                    "tempo_raw",
                    "day_key",
                ]
                old = prev[cols].rename(
                    columns={
                        "race_key": "previous_race_key",
                        "band": "previous_band",
                        "tempo_raw": "previous_tempo",
                        "day_key": "previous_day_key",
                    }
                )
                test = test.merge(old, on="previous_race_key", how="inner")
                if test.empty:
                    continue
                basis = test["expected"].to_numpy(float)
                previous_resid = (test["previous_target"] - test["previous_expected"]).to_numpy(
                    float
                )
                true = test["target"].to_numpy(float)
                maes = {"expect_only": float(np.abs(true - basis).mean())}
                errors = {}
                for variant in ("none", "state", "tempo", "both", "day"):
                    effect = 0 if variant == "none" else test[f"effect_{variant}"].to_numpy(float)
                    errors[variant] = np.abs(true - (basis + 0.5 * (previous_resid - effect)))
                    maes[variant] = float(errors[variant].mean())
                out.append(
                    {
                        "meet": meet,
                        "part": part,
                        "year": year,
                        "runs": len(test),
                        "mae": {k: round(v, 4) for k, v in maes.items()},
                    }
                )
                cell_rows.append(
                    pd.DataFrame(
                        {
                            "meet": meet,
                            "part": part,
                            "distance_m": test["distance_m"],
                            "band": test["previous_band"],
                            "tempo": test["previous_tempo"],
                            "previous_day_key": test["previous_day_key"],
                            "none_error": errors["none"],
                            "day_error": errors["day"],
                        }
                    )
                )
    cells = []
    if cell_rows:
        all_cells = pd.concat(cell_rows, ignore_index=True)
        for key, group in all_cells.groupby(
            ["meet", "part", "distance_m", "band", "tempo"], dropna=False
        ):
            if len(group) < 30 or group["previous_day_key"].nunique() < 20:
                continue
            cells.append(
                {
                    "meet": key[0],
                    "part": key[1],
                    "distance_m": int(key[2]),
                    "band": key[3],
                    "tempo": key[4],
                    "runs": len(group),
                    "days": int(group["previous_day_key"].nunique()),
                    "day_minus_none_mae": round(
                        float(group["day_error"].mean() - group["none_error"].mean()), 4
                    ),
                }
            )
    return {"annual": out, "cells": cells}


def main() -> None:
    rec, source = read_data()
    horse = expected_residuals(rec)
    race = race_residuals(horse)
    result = {
        "source": source,
        "eligible_horse_residuals": len(horse),
        "eligible_races": len(race),
        "contrasts": contrasts(race),
        "holdout_moisture": holdout_moisture(race),
        "next_race": next_race_validation(horse, race),
        "sign": "adjusted_seconds = raw_seconds - effect_seconds",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```
<!-- REPRODUCE_PY_END -->
