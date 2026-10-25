"""Prepare local research conclusions and finite website summary tables."""
# ruff: noqa: E501

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
CENTRAL = HERE.parent / "conclusions/02B_DETACHED_TAIL_BASELINE.md"


def markdown(frame):
    columns = list(frame.columns)

    def value(v):
        if pd.isna(v):
            return "—"
        if isinstance(v, float):
            return f"{v:.3f}"
        return str(v)

    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines.extend(
        "| " + " | ".join(value(v) for v in row) + " |"
        for row in frame.itertuples(index=False, name=None)
    )
    return "\n".join(lines)


def records(frame):
    return json.loads(frame.to_json(orient="records", force_ascii=False))


def main():
    s = json.loads((OUT / "summary.json").read_text())
    v = json.loads((OUT / "verification.json").read_text())
    assert v["passed"]
    cov = pd.read_csv(OUT / "tail_coverage.csv")
    coverage = cov[cov.grouping.eq("meet+distance_m")].copy()
    coverage["distance_m"] = coverage.distance_m.astype(int)
    paired = pd.read_csv(OUT / "paired_race_changes.csv")
    deltas = paired.pivot(
        index=["meet", "distance_m"], columns="section", values="mean_change"
    ).reset_index()
    overview = coverage[
        [
            "meet",
            "distance_m",
            "rows",
            "tail25",
            "rate",
            "median_winner_floor",
            "median_median_floor",
        ]
    ].merge(deltas, on=["meet", "distance_m"], validate="one_to_one")
    overview.to_csv(OUT / "distance_overview.csv", index=False)
    profiles = pd.read_csv(OUT / "adjusted_effect_profiles.csv", dtype={"level": str})
    moisture = profiles[
        profiles.family.eq("moisture")
        & profiles.distance_m.eq(1200)
        & profiles.section.isin(["early", "late"])
    ].copy()
    moisture = moisture[
        ["meet", "variant", "level", "section", "effect_seconds", "ci_low", "ci_high", "supported"]
    ]
    moisture.to_csv(OUT / "moisture1200_sensitivity.csv", index=False)
    month = (
        profiles[profiles.family.eq("month")]
        .groupby(["meet", "distance_m", "variant", "section"], observed=True)
        .effect_seconds.agg(lambda x: x.max() - x.min())
        .rename("peak_to_peak")
        .reset_index()
    )
    month.to_csv(OUT / "month_curve_sensitivity.csv", index=False)
    focus = profiles[
        profiles.family.eq("number")
        & profiles.distance_m.eq(1600)
        & (
            (profiles.meet.eq("서울") & profiles.block.eq("exact10") & profiles.level.eq("10"))
            | (profiles.meet.eq("부산") & profiles.block.eq("exact12") & profiles.level.eq("1"))
        )
    ][
        [
            "meet",
            "distance_m",
            "variant",
            "block",
            "level",
            "section",
            "effect_seconds",
            "ci_low",
            "ci_high",
            "supported",
        ]
    ]
    focus.to_csv(OUT / "gate1600_sensitivity.csv", index=False)
    display = overview.copy()
    display["제외율%"] = 100 * display.rate
    display = display[
        [
            "meet",
            "distance_m",
            "rows",
            "tail25",
            "제외율%",
            "median_winner_floor",
            "median_median_floor",
            "early",
            "late",
            "finish",
        ]
    ]
    display.columns = [
        "지역",
        "거리m",
        "기존표본",
        "추가제외",
        "제외율%",
        "선두차 문턱 중앙값",
        "중위차 문턱 중앙값",
        "출발200 평균변화",
        "막판200 평균변화",
        "전체 평균변화",
    ]
    table = markdown(display)
    percentage = s["additional_tail25_removed"] / s["mad4_rows"] * 100
    body = f"""# 결승 이탈 후미와 기록 기준의 민감도

2026-10-08. 이탈 후미를 제외하면 일반적인 완주 집단의 기준을 만들 수 있다. 기존 이상치 제거 이후에도 평균 변화는 출발200m보다 마지막200m에서 크다. 그렇지만 느린 정상 능력까지 일부 제외될 수 있으므로 전체 기준과 정제 기준을 나란히 제공하는 것이 적절하다. 제거 기준은 보수적 정책 후보이며 기존 공식 보정표는 유지한다.

## 어떤 말을 이탈 후미로 표시했는가

최하위라는 착순만으로 제외하지 않는다. 원래 완전한 경주 명단에서 기록순 마지막 ceil(N/4)두 범위에 있으면서 다음 두 조건을 모두 넘는 말이다. 동률은 최선 기록순위를 쓴다.

1. 선두와 기록 차이 > max(3초, 선두 완주시간×4%).
2. 경주 중앙 완주시간과 차이 > max(2초, 중앙 완주시간×2%, 2.5×강건표준편차).

강건표준편차는1.4826×median(|각 완주시간−경주 중앙시간|)이다. 다수의 말이 벌어진 경주는 문턱이 커지고, 본대는 밀집했는데1~2두만 떨어진 경주는 그 말들을 찾는다. MAD배수를3.0으로 높이면 극단적인 말만 더 적게 제거하고2.0이면 더 넓게 제거한다. 인접 기록의 큰 단절 뒤에 있는 연속 후미 집단은 보조 표식으로 보관했다. 두 말이 함께 떨어졌을 때 둘 사이의 간격이 작아도 중위 기준으로 식별할 수 있다.

한국마사회 경마가이드의 안내는1마신 약0.18초다. 속도지수 설명에는0.2초를1마신으로 쓰는 단순화도 있다. 따라서20마신은 대략3.6~4초이지10초가 아니다. 마신 환산을 제외 기준에 사용하지 않고 관측된 초 차이를 썼다. [마사회 가이드](https://park.kra.co.kr/race_guide_.pdf), [마사회 속도지수 설명](https://studbook.kra.co.kr/html/info/ind/s_rc_age_idx.jsp?mabun=0040561). 이 근사치는 공식적인 이탈 후미 정의가 아니다.

## 표본과 기준의 변화

서울2018-01-06~2026-09-20, 부산2018-01-05~2026-09-18. 원래151,115출전·13,928경주의 완전한 명단으로 표시를 계산했다. 구간·통제변수 결합은151,074출전, 기존 기록 모형 대상149,624출전이다. 기존 전체기록4MAD는1,286출전을 제외해148,338출전이 남았다. 원래 명단의 이탈 후보4,801출전 중 기존 모형 대상은4,718출전이고, 그중706출전은4MAD에서 이미 제외됐다. 추가 제외는4,012출전({percentage:.3f}%), 남은 정제 표본은144,326출전이다. 기준 표본 내3,454경주에서 추가 제외가 발생했다.

아래 평균 변화는 각 경주에 동일 가중치를 주어 제거 전후를 짝지은 값이다. 음수는 평균 시간이 빨라졌다는 뜻이다. 문턱은 경주별로 달라지며 표는 해당 거리의 경주별 문턱을 출전 표본에서 요약한 중앙값으로, 모든 경주에 고정 적용할 값이 아니다. 마지막200m는 마지막600m에 포함된다.

{table}

서울1200m 출발200m 변화−0.007887초의 날짜 군집 부트스트랩95%구간은[−0.009644,−0.006296], 마지막200m−0.040759초는[−0.044275,−0.037195]다. 부산1200m는 각각−0.003755초[−0.005098,−0.002458], −0.046113초[−0.050738,−0.041586]다. 14거리 모두 마지막200m의 평균 변화 절댓값이 출발200m보다 컸다. 이는 평균이 바뀐 정도이지 초반·막판 차이의 정식 검정이 아니다.

## 보정 효과도 함께 다시 계산했다

기본 게이트는 말+경주 고정효과, 함수율·월은 말 고정효과와 등급×연도·정확 함수율 숫자·게이트·말 상태 통제를 사용했다. 두 모형 모두 경주 동일가중치다. 기본/2.5배수/3.0배수 표본×14지역거리×2설계로84개 다중목표 모형에서 전체·출발200m·마지막600m·마지막200m를 추정했다. 서울1900/2300m·부산1900/2000/2200m 등 희소 거리는 포함하지 않는다. 최근 기간별 재추정, 함수율×게이트 및 실제 내외측 주행 재추정은 이번 범위가 아니다.

함수율 대조의 숫자 함수율 혼합비는 제거 전4MAD 표본에서 경주 동일가중치로 고정했다. 비교 대상 모형을 기본 표본부터 다시 적합했으므로 과거와 표본 종료일·설계가 다른 값을 제거 효과로 비교하지 않는다. 개별95%구간은 말·날짜 군집 공분산 중 보수적인 분산, 다중비교q는 변형·설계·구간·대조 종류별로 계산했다. 제거 전후 추정치 차이 자체에 대한 유의성은 검정하지 않았다.

- 1200m 포화−건조: 서울 출발200m−0.113926→−0.114206초, 마지막200m−0.104900→−0.100952초. 부산 출발−0.125964→−0.127565초, 마지막−0.116312→−0.119020초. 정제 후에도 두 곳 모두 출발 차이 절댓값이 조금 크다.
- 1200m 불량−건조: 서울 출발−0.167214→−0.168304초, 마지막−0.255770→−0.271327초. 부산 출발−0.162830→−0.165669초, 마지막−0.285591→−0.288182초. 여기서는 마지막 차이가 더 크다. 전체 지원41상태 대조 중 막판 절댓값이 큰 것은 제거 전후 모두24개다. 이전 연구의 다른 대조 정의와 개수를 직접 비교하지 않는다.
- 월별 연간 곡선의 최댓값−최솟값은 정제 후에도14거리 모두 마지막200m가 출발200m보다 컸다. 서울1200m 출발0.099302→0.099036초, 마지막0.122379→0.137783초. 부산1200m 출발0.078860→0.078446초, 마지막0.190507→0.175927초. 후미 제외가 모든 차이를 줄이지는 않는다.
- 서울1600m10두10번의 동일 두수 평균 대비 게이트 차이: 전체+0.490887→+0.403810초, 출발+0.169063→+0.174484초, 마지막+0.182464→+0.149061초. 부산1600m12두1번은 전체+0.461295→+0.385522초, 출발+0.034900→+0.039997초, 마지막+0.168339→+0.137350초다. 이는 추정 차이이며 실제 적용 보정값이나 순수한 주행거리 손실이 아니다.

## 어떻게 사용하는 것이 좋은가

전체 표본 기준은 원래 모집단을 설명하는 기준으로 유지하고, 이탈 후미 제외 기준은 정상 완주 본대에 가까운 기록을 읽는 보조 기준으로 제공한다. 단일 최하위 제외 또는 선두3.6초만으로 자르는 방식보다 중위 기준을 함께 쓰는 현재 후보를 먼저 시험할 수 있다. 정제 기준의 평균이 빨라지는 현상 자체를 정확도나 예측력 향상으로 해석하지 않는다.

말의 실제 경기 기록과 이탈 표식은 보존한다. 느린 경기를 말의 능력 평가에서 통째로 지워 좋은 경기만 남기는 방식은 사용하지 않는다. 출발 후미와 결승 이탈은 다르고 정상 추입마는 결승에서 본대와 함께 들어오면 제외되지 않는다. 한편 부상·의도적인 감속·정상적인 낮은 능력을 시간차만으로 분리할 수 없으며, 주로 때문에 실제로 무너진 말까지 빠지면 환경 효과 일부를 제거할 수 있다. 등급·상태별 제외율을 함께 공개한다. 국6 제외율은 서울2.98%·부산3.41%로 전체보다 조금 높다.

이탈 표식은 해당 경주가 끝나야 알 수 있다. 향후 시간순 모델에는 예측 대상 이전에 종료된 경주의 표식만 쓸 수 있고, 학습 기준도 그 시점 이전 자료로 다시 적합해야 한다. 현재 산출물은2026-10-08 이후 검토할 회고적 민감도 결과다. 채택된 함수율 보정과 기존 시험표, 운영 모델·DB는 변경하지 않았다. 다음 경주 예측 검증은 추후 과제로 유지한다.

## 검증과 산출물

완전한 명단13,928경주의 독립 NumPy 계산으로 표식을 대조했고, 서울1600m·부산1200m의 제거 전후2설계·4목표에 대해 명시적인 말/경주 더미 회귀32회로 검증했다. 최대 대조 차이는{v["max_contrast_error_seconds"]:.3g}초다. 이전 연구의 동일 표본2,166구간 대조도 재현했다. 원본 기록과 원래 출전 두수·게이트 범위를 보존했다.

[계획](PLAN.md) · [분석 코드](analyze.py) · [검증 코드](verify.py) · [검증 결과](outputs/verification.json) · [거리별 요약](outputs/distance_overview.csv) · [개별 표식](outputs/runner_tail_flags.parquet) · [사례](outputs/race_examples.csv) · [게시 요약](PUBLICATION.md) · [출처](SOURCES.md) · [용량 명세](outputs/artifact_inventory.json).
"""
    (HERE / "README.md").write_text(body)
    central = body.replace("(PLAN.md)", f"(../{HERE.name}/PLAN.md)")
    for prefix in ["analyze.py", "verify.py", "PUBLICATION.md", "SOURCES.md"]:
        central = central.replace(f"({prefix})", f"(../{HERE.name}/{prefix})")
    central = central.replace("(outputs/", f"(../{HERE.name}/outputs/")
    CENTRAL.write_text(central)
    publication = """# 본대에서 떨어진 말이 평균 구간 기록에 미치는 영향

결승에서 중위권과도 크게 떨어진 말을 기준 산출에서 빼면, 출발보다 막판 평균이 더 많이 빨라졌다. 서울1200m는 출발200m 약0.008초·마지막200m 약0.041초, 부산1200m는 약0.004초·0.046초다. 이미 기존 이상치를 제거한 표본에서 확인한 추가 변화다.

맨 꼴찌를 무조건 제외하지 않는다. 마지막 약25% 범위에서 선두와 중위권 모두 크게 벌어진 말을 찾았다. 1200m의 전형적인 문턱은 선두3초·중위2.4~2.6초이지만 경주 내 기록 편차에 따라 높아진다. 공식 정의나 최적값이 아닌 연구 후보다. 전체148,338출전 중4,012출전(2.70%)이 추가로 표시됐다.

후미 제외 후에도1200m 포화 주로에서는 함수율 차이가 막판보다 출발200m에서 조금 컸다. 불량 주로에서는 막판이 더 컸다. 월별 막판 차이도 유지됐다. 서울1600m10두10번 게이트의 전체시간 차이는 약+0.491초에서+0.404초로 줄어, 전체 표본과 정제 표본을 함께 읽을 필요가 있다.

전체 기준은 유지하고 정제 기준을 보조로 제시한다. 각 말의 느린 실제 경기를 삭제하지 않는다. 결승 후에 알 수 있는 표식이므로 미래 예측에는 이전에 끝난 경주에만 사용한다. 예측 개선이나 운영 보정 적용을 완료한 결과는 아니다.

자료: 서울·부산2018년~2026년9월, 지원되는14지역거리. 자세한 거리·등급·함수율별 표본과 한계는 [원 보고서](README.md)에 정리했다.
"""
    (HERE / "PUBLICATION.md").write_text(publication)
    payload = dict(
        title="결승 이탈 후미와 구간 기준",
        status="retrospective_sensitivity_only",
        version="20261008",
        data_end={"서울": "2026-09-20", "부산": "2026-09-18"},
        original_roster_rows=s["original_rows"],
        baseline_rows=s["mad4_rows"],
        primary_removed=s["additional_tail25_removed"],
        primary_rows=s["retained_primary"],
        distance_overview=records(overview),
        paired_changes=records(paired),
        moisture1200=records(moisture),
        month_curve=records(month),
        gate1600=records(focus),
        interpretation="원래 모집단과 이탈 후미 제외 조건부 기준을 병기; 기록 삭제·운영 반영·예측 개선 아님",
    )
    (OUT / "web_detached_tail_sensitivity.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )


if __name__ == "__main__":
    main()
