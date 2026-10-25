"""Readable correction atlas, publication figures and website summary data."""
# ruff: noqa: E501

import importlib.util
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import TwoSlopeNorm

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
CENTRAL = HERE.parent / "conclusions/04F_ENVIRONMENT_CORRECTION_ATLAS.md"
SPEC = importlib.util.spec_from_file_location("atlas_helper", HERE / "apply.py")
H = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(H)
BANDS = ["건조", "양호", "다습", "포화", "불량"]
LABELS = {"finish": "전체", "early": "출발200m", "last600": "마지막600m", "late": "마지막200m"}


def table(frame):
    def value(x):
        if pd.isna(x):
            return "?"
        if isinstance(x, (float, np.floating)):
            return f"{x:+.3f}"
        return str(x).replace("|", "\\|")

    return "\n".join(
        ["| " + " | ".join(frame.columns) + " |", "|" + "---|" * len(frame.columns)]
        + [
            "| " + " | ".join(value(v) for v in row) + " |"
            for row in frame.itertuples(index=False, name=None)
        ]
    )


def records(frame):
    return json.loads(frame.to_json(orient="records", force_ascii=False))


def charts(condition, lateral):
    plt.rcParams.update(
        {"font.family": "AppleGothic", "axes.unicode_minus": False, "font.size": 10}
    )
    chosen = condition[condition.cohort.eq("tail25") & condition.period.eq("all_mad4")]
    pairs = sorted(
        set(zip(chosen.meet, chosen.distance_m, strict=True)), key=lambda p: (p[0] != "서울", p[1])
    )
    fig, axes = plt.subplots(1, 3, figsize=(17, 9), layout="constrained")
    for ax, target in zip(axes, ["finish", "early", "late"], strict=True):
        data = chosen[chosen.target.eq(target)].set_index(["meet", "distance_m", "band"])
        matrix = np.array(
            [[data.loc[(meet, dist, band), "mean_add"] for band in BANDS] for meet, dist in pairs]
        )
        limit = max(float(np.nanmax(abs(matrix))), 0.01)
        cmap = plt.get_cmap("RdBu_r").copy()
        cmap.set_bad("#e7e7e7")
        im = ax.imshow(
            matrix, cmap=cmap, norm=TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit), aspect="auto"
        )
        for i, (meet, dist) in enumerate(pairs):
            for j, band in enumerate(BANDS):
                v = matrix[i, j]
                text = (
                    "?"
                    if not np.isfinite(v)
                    else f"{v:+.2f}\n{data.loc[(meet, dist, band), 'symbol']}"
                )
                ax.text(
                    j,
                    i,
                    text,
                    ha="center",
                    va="center",
                    fontsize=9,
                    color="white" if np.isfinite(v) and abs(v) > 0.72 * limit else "#172533",
                )
        ax.set_xticks(range(5), BANDS)
        ax.set_yticks(range(len(pairs)), [f"{m} {d}m" for m, d in pairs])
        ax.set_title(LABELS[target] + " 합산 보정초")
        fig.colorbar(im, ax=ax, shrink=0.65, label="초 (패널마다 색 범위 다름)")
    fig.suptitle(
        "함수율 + 월 + 게이트 | 전체기간 계수 · 이탈 후미 제외 관측 조건의 평균", fontsize=15
    )
    fig.supxlabel(
        "+는 기록에 시간 추가, -는 차감 · ?는 미지원 · 내외측 주행은 합산하지 않음", fontsize=11
    )
    fig.savefig(OUT / "environment_correction_heatmap.png", dpi=160)
    plt.close(fig)
    points = [("서울", p) for p in ["S1F", "3C", "4C", "G1F"]] + [
        ("부산", p) for p in ["S1F", "G4F", "G3F", "G1F"]
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13, 7), layout="constrained")
    selected = lateral[
        lateral.distance_m.eq(0)
        & lateral.variant.eq("baseline")
        & lateral.block.eq("triple")
        & lateral.level.eq("outer-inner")
        & lateral.metric.eq("finish")
    ]
    for ax, period in zip(axes, ["all_mad4", "recent_mad4"], strict=True):
        data = selected[selected.period.eq(period)].set_index(["meet", "point", "band"])
        matrix = np.array(
            [
                [
                    data.loc[(meet, point, band), "effect_seconds"]
                    if data.loc[(meet, point, band), "supported"]
                    else np.nan
                    for band in BANDS
                ]
                for meet, point in points
            ]
        )
        cmap = plt.get_cmap("RdBu_r").copy()
        cmap.set_bad("#e7e7e7")
        im = ax.imshow(
            matrix, cmap=cmap, norm=TwoSlopeNorm(vmin=-0.5, vcenter=0, vmax=0.5), aspect="auto"
        )
        for i, (meet, point) in enumerate(points):
            for j, band in enumerate(BANDS):
                row = data.loc[(meet, point, band)]
                v = matrix[i, j]
                text = "?" if not np.isfinite(v) else f"{v:+.2f}" + (" *" if row.q < 0.05 else "")
                ax.text(
                    j,
                    i,
                    text,
                    ha="center",
                    va="center",
                    color="white" if np.isfinite(v) and abs(v) > 0.35 else "#172533",
                )
        ax.set_xticks(range(5), BANDS)
        ax.set_yticks(range(len(points)), [m + " " + p for m, p in points])
        ax.set_title("전체기간" if period == "all_mad4" else "2024년 이후")
    fig.colorbar(im, ax=axes, shrink=0.7, label="외측 - 내측 완주시간 차이 (초)")
    fig.suptitle("상대 주행위치 별도 분석 | 3두 이상 같은 마군 · 전체거리 통합", fontsize=14)
    fig.supxlabel(
        "+는 외측이 느린 연관, -는 빠른 연관 · *는 다중비교 q<0.05 · 보정에 합산하지 않음",
        fontsize=10,
    )
    fig.savefig(OUT / "lateral_moisture_period_heatmap.png", dpi=160)
    plt.close(fig)


def main():
    b = json.loads((OUT / "build_summary.json").read_text())
    v = json.loads((OUT / "verification.json").read_text())
    assert v["passed"]
    condition = pd.read_csv(OUT / "condition_correction_summary.csv")
    overall = pd.read_csv(OUT / "distance_correction_summary.csv")
    lat = pd.read_csv(OUT / "lateral_moisture_period_profiles.csv")
    joint = pd.read_csv(OUT / "joint_sensitivity_profiles.csv", dtype={"level": str})
    chosen = condition[condition.cohort.eq("tail25") & condition.period.eq("all_mad4")]
    main = (
        chosen[chosen.band.eq("포화") & chosen.target.isin(LABELS)]
        .pivot(index=["meet", "distance_m"], columns="target", values="mean_add")
        .reset_index()
    )
    main = main.sort_values(
        ["meet", "distance_m"],
        key=lambda x: x.map({"서울": 0, "부산": 1}) if x.name == "meet" else x,
    )
    main.to_csv(OUT / "representative_saturated.csv", index=False)
    pretty = main.rename(columns={"meet": "지역", "distance_m": "거리m", **LABELS})[
        ["지역", "거리m", "전체", "출발200m", "마지막600m", "마지막200m"]
    ]
    focus1200 = (
        chosen[chosen.distance_m.eq(1200) & chosen.target.isin(LABELS)]
        .pivot(index=["meet", "band"], columns="target", values="mean_add")
        .reset_index()
    )
    focus1200.to_csv(OUT / "reference1200_all_states.csv", index=False)
    latfocus = lat[
        lat.level.eq("outer-inner")
        & lat.block.eq("triple")
        & lat.metric.eq("finish")
        & lat.band.isin(["건조", "포화"])
    ].copy()
    latfocus.to_csv(OUT / "lateral_focus.csv", index=False)
    atlas = H.EnvironmentAtlas()
    directions = joint.copy()
    directions["record_tendency"] = np.where(
        directions.effect_seconds < 0, "빠른 기록 방향", "느린 기록 방향"
    )
    directions["correction_direction"] = np.where(directions.effect_seconds < 0, "+", "-")
    directions.loc[directions.effect_seconds.eq(0), "correction_direction"] = "0"
    directions.loc[~directions.estimable, ["record_tendency", "correction_direction"]] = "?"
    directions["ci_crosses_zero"] = directions.ci_low.le(0) & directions.ci_high.ge(0)
    directions["use"] = "관측 대조의 부호; 합산 보정초로 직접 적용하지 않음"
    directions.to_csv(OUT / "joint_effect_directions.csv", index=False)
    cases = []
    for meet, distance, moisture, month, n, number in [
        ("서울", 1200, 16, 7, 11, 11),
        ("부산", 1200, 20, 1, 12, 1),
        ("서울", 1600, 3, 5, 10, 10),
        ("부산", 1600, 16, 7, 12, 1),
    ]:
        for target in H.TARGETS:
            result = atlas.lookup(
                meet=meet,
                distance=distance,
                moisture=moisture,
                month=month,
                roster=list(range(1, n + 1)),
                horse_number=number,
                target=target,
                as_of="2026-10-08",
            )
            cases.append(
                dict(
                    meet=meet,
                    distance_m=distance,
                    moisture=moisture,
                    band=result["band"],
                    month=month,
                    field_size=n,
                    horse_number=number,
                    target=target,
                    moisture_add=result["moisture"],
                    month_add=result["month_add"],
                    gate_add=result["gate"],
                    total_add=result["total_add"],
                    symbol=result["symbol"],
                    complete=result["complete"],
                    method=result["method"],
                )
            )
    examples = pd.DataFrame(cases)
    examples.to_csv(OUT / "combined_application_examples.csv", index=False)
    primary = condition[
        condition.period.eq("all_mad4")
        & condition.cohort.eq("tail25")
        & condition.target.eq("finish")
    ]
    before = joint[joint.variant.eq("baseline") & joint.period.eq("all_mad4")]
    after = joint[joint.variant.eq("tail25") & joint.period.eq("all_mad4")]
    keys = ["meet", "distance_m", "family", "block", "level", "section"]
    paired = before.merge(after, on=keys, suffixes=("_before", "_after"))
    paired["effect_change"] = paired.effect_seconds_after - paired.effect_seconds_before
    paired = paired[paired.supported_before & paired.supported_after]
    paired[keys + ["effect_seconds_before", "effect_seconds_after", "effect_change"]].to_csv(
        OUT / "tail_joint_sensitivity_changes.csv", index=False
    )
    medchange = paired.groupby("family").effect_change.agg(lambda x: x.abs().median()).to_dict()
    supported = lat[lat.supported]
    recent_significant = int((supported.period.eq("recent_mad4") & supported.q.lt(0.05)).sum())
    body = f"""# 경기장 거리별 전체 및 구간 기록의 환경 보정

2026-10-08. 함수율·월·게이트의 보수적인 시험값을 실제 기록에 더할 수 있는 하나의 조회표로 묶었다. 전체·출발200m·마지막600m·마지막200m를 함께 제공한다. 실제 내측·중간·외측 주행은 별도 특성표로 보존하고 합산하지 않는다. 전체 표본과 이탈 후미 제외 표본의 대표값을 모두 남겼다. 운영 모델 적용이나 예측 성능 검증을 완료한 결과는 아니다.

## 기록에 더하는 합산 값

`보정 기록 = 실제 기록 + 함수율 보정 + 월 보정 + 게이트 보정`이다. +는 시간을 더하는 방향으로, 조건의 도움으로 빨라진 기록을 완화한다. -는 시간을 빼는 방향으로 불리한 조건에서 느려진 기록을 일부 인정한다. 아래 표는 거리마다 모든 말을 똑같이 보정하는 고정 계수가 아니라 해당 함수율에서 관측된 월·게이트 조건을 경주 동일가중치로 평균한 대표값이다. 실제 적용은 출전 당시의 월·함수율·원래 출전 명단·게이트를 조회한다.

전체기간 계수와 이탈 후미 제외 표본으로 요약한 **포화 상태의 합산 보정초**는 다음과 같다. 소수 셋째 자리 표시는 계산 재현을 위한 것이며 그 정밀도로 실제 효과가 확정됐다는 뜻은 아니다. ?는 지원이 부족한 조건이다.

{table(pretty)}

![경기장 거리 상태별 보정](outputs/environment_correction_heatmap.png)

## 숫자와 기호를 읽는 방법

전체 기록은 절댓값0.05초 미만0,0.05~0.20초 미만+/−,0.20초 이상++/−−다. 출발200m·마지막200m는 각각0.01/0.04초,마지막600m는0.02/0.08초 문턱이다. 이는 크기를 읽는 정책적 표시이고 신뢰도나 통계적 유의성 표시가 아니다. 서로 다른 구간의++는 같은 초 크기를 뜻하지 않는다. 미지원은?로 표시한다.

예를 들어 서울1200m 포화의 대표 전체값은+0.396초(관측 조건의10~90%범위+0.345~+0.443초),출발200m+0.073초,마지막600m+0.067초,마지막200m+0.053초다. 부산1200m 포화는 전체+0.585초(+0.559~+0.604초),출발+0.049초,마지막600m+0.088초,마지막200m+0.060초다. 이 범위는 말의 실제 기록 분포나 추정 신뢰구간이 아니라 월·게이트별 적용 후보의 분포다.

같은1200m라도 건조·양호·다습·포화·불량은 구분한다. 서울 양호 대표값은 전체−0.094초·출발+0.011초·마지막200m−0.042초,다습은 전체−0.004초·출발+0.026초·마지막200m−0.045초다. 부산 양호는 전체−0.109초·출발+0.009초·마지막200m−0.007초다. 전체와 구간의 방향이 항상 같지는 않다. 불량 대표 전체값은 서울1200m+1.040초·부산1200m+0.867초로 포화와도 다르다. [1200m 모든 상태](outputs/reference1200_all_states.csv).

## 기존 기준과 기간별 값

전체 함수율 서울80%·부산90%,구간 함수율의 기존 후보율,게이트30% 기본+15% 상태 차이·표본 수축·상한을 보존했다. 기존 채택 거리 밖의1000m·서울2000m도 원 참조표에서 지원되는 상태에 한해 탐색용 수치를 제공한다. 이를 공식 채택 범위를 확장한 것으로 표현하지 않는다. 지원되지 않는 상태·희소 거리를 다른 거리 값으로 채우지 않았다.

기존 환산표가 미지원인 조건도 새 동일 설계 모형에서 추정되는 경우에는 [관측 차이와 보정 방향](outputs/joint_effect_directions.csv)에 별도로 남겼다. 초 값·부호·표본 지원·95%구간의0포함·q를 함께 읽는다. 이 표의 부호는 합산표의 빈값을 대체하는 확정 보정이 아니다.

전체기간의 기존 전체 월값과 모든 기존 구간 월·게이트 값은 유지했다. 최근 전체 월과 기존 전체 월이 없던 거리만 동일 설계의 월 곡선×30%×n/(n+100),12개월 평균0·0.12초 상한으로 보충했다. 출처 필드로 구분한다. 전체 월의 일부 기존값은 반올림/보수 선택 때문에12개월 평균이 정확히0은 아니다. 기존값을 재중심화해 몰래 바꾸지 않았다.

월 후보의 전체 범위는 전체 약−0.12~+0.12초,출발200m 약−0.028~+0.022초,마지막600m±0.06초,마지막200m±0.03초다. 게이트 후보는 전체 약−0.115~+0.080초,출발−0.037~+0.035초,마지막600m−0.090~+0.061초,마지막200m−0.045~+0.028초다. 따라서 전체 보정에서는 함수율이 큰 부분을 차지하고 월·게이트는 그 주변을 조정하는 구조다. 이 상하한은 조회표 전체의 극값이다.

기간은 전체자료와2024년 이후의 두 계수 버전으로 구분했다. 함수율 기준은2025년까지 적합한 기존 참조를 두 버전에서 공통으로 유지하므로 최근 행을 최근 함수율 효과의 재추정으로 읽지 않는다. 게이트·구간 월·새 전체 월은 해당 기간 버전이다. 연도별·분기별 표는 같은 고정 조회표를 각 시기의 출전 조건에 대입한 노출 요약이며 그 시기에 발생한 새 주로 편향을 추정한 결과가 아니다. [조건별 평균·10~90%범위](outputs/condition_correction_summary.csv) · [연도별](outputs/year_correction_exposure.csv) · [분기별](outputs/quarter_correction_exposure.csv).

## 후미 제외와 동일 조건 민감도

서울·부산151,074출전의 원래 두수와 명단을 유지했다. 기존4MAD와 이탈 후미 제외 표본에서 정확 함수율·월·게이트·등급×연도·말 상태를 함께 통제한 말 고정효과 모형을50개,4목표에 적합했다. 새로 적합한 계수를 그대로 기존 보정표에 덮어쓰지 않고 방향·변동 크기를 점검하는 별도 근거로 제공한다. 함수율 상태 대조의 숫자 함수율 혼합은 각 기간의 제거 전 표본에서 경주 동일가중치로 고정했다.

전체기간 지원 대조에서 제거 전후 추정치 차이 절댓값의 중앙값은 함수율{medchange.get("moisture", float("nan")):.4f}초,월{medchange.get("month", float("nan")):.4f}초,게이트 번호{medchange.get("number", float("nan")):.4f}초였다. 일부 셀에서는 더 크게 달라진다. 서울1200m 포화의 전체기록 함수율 차이는 제거 전−0.522초·제거 후−0.521초였고 부산은−0.594초·−0.601초였다. 이전 참조표와 이번 모형의 기간·설계가 다르므로 이 차이를 단순히 보정 오차로 보지 않는다. [동일 설계 민감도](outputs/tail_joint_sensitivity_changes.csv).

조건별 대표 보정표의 ‘후미 제외’는 같은 보정표에 노출되는 표본을 정제한 요약이다. 계수까지 후미 제외로 재추정한 결과는 위 별도 민감도 표다. 둘을 구분한다. 실제 느린 경기 기록은 삭제하지 않았고, 해당 경주 종료 뒤 알 수 있는 표식을 미래 예측에 미리 사용하지 않는다.

## 실제 내측 중간 외측은 별도 설명

표의 내외측은 같은 마군의 왼쪽·중간·오른쪽 상대 순서다. 레일부터의 거리나 실제 경로 길이를 측정한 값이 아니다. 2두 외측−내측과3두 이상 중간−내측·외측−내측·외측−중간을 나눴다. 지역·계측지점·정확거리·전체거리 통합·전체/최근·함수율 상태·후미 제거 전후를 구분한244모형·7,840대조를 보존했다. 지원 대조는{len(supported):,}개,전체 비교에서q<0.05는{int(supported.q.lt(0.05).sum())}개였고 최근 기간은{recent_significant}개였다. 전체와 최근,전체거리와 정확거리는 서로 겹치는 비교다.

같은 말×거리와 같은 마군을 통제한 **3두 이상 외측−내측 완주시간 차이**의 예는 다음과 같다. 양수는 외측이 느린 연관이며 보정초가 아니다.

| 조건 | 전체기간 차이 | 최근 차이 | 해석 |
|---|---:|---:|---|
| 서울1200m 3C 건조 | +0.715초 | +0.607초 | 전체기간에서 외측 느림,최근 점추정도 같은 방향이나 다중비교 후 미확정 |
| 서울1200m 3C 포화 | +0.242초 | 표본부족 | 전체95%구간−0.154~+0.637초로 방향 미확정 |
| 부산1200m G4F 건조 | +0.422초 | +0.508초 | 전체기간 외측 느림,최근은 다중비교 후 미확정 |
| 부산1200m G4F 포화 | +0.052초 | 표본부족 | 전체95%구간−0.427~+0.531초로 방향 미확정 |

이탈 후미를 제외해도 위 건조 조건의 전체 차이는 서울+0.680초·부산+0.398초로 같은 방향이었다. 서울 전체거리 통합3C 건조는+0.479초,포화는−0.016초였고,막판G1F 포화는−0.269초였다. 구간·상태에 따라 방향이 달라지는 모습이다. 상태 간 차이 자체의 유의성이나 환경의 인과효과를 검정한 결과는 아니다. 막판 외측에는 남은 힘·추월 경로 선택이 포함될 수 있으므로 시간에서 그대로 빼거나 더하지 않는다.

![내외측의 기간 상태 비교](outputs/lateral_moisture_period_heatmap.png)

서울S1F/3C/4C/G1F,부산S1F/G4F/G3F/G1F를 구분했다. 가용 잔여시간은S1F=전체−출발200m,G1F=마지막200m,부산G3F=마지막600m다. 서울4C 잔여는1200m·2024년 이후 실제 계측에만 한정하고530m와600m를 바꿔 쓰지 않았다. 미계측3C/G4F 이후 시간을 생성하지 않았다. [모든 거리·기간·상태·세 위치](outputs/lateral_moisture_period_profiles.csv) · [연도/분기 같은 마군 단순 비교](outputs/lateral_year_quarter_descriptive.csv). 후자는 말 상태 통제를 하지 않은 기술표이며 조정 모형과 다르다.

## 적용과 검증

출전 당시의 원래 명단과 게이트를 입력해 [조회 함수](apply.py)의EnvironmentAtlas.lookup 또는normalize_record를 사용할 수 있다. 해당 자료를 삭제하거나 운영 모델에 자동 연결하지 않는다. `as_of`는고정 버전이 존재한2026-10-08 이후여야 한다. 지원하지 않는 값은?·빈값이며,확인된0효과로 표현하지 않는다. 계산 가능한 일부 항목만 더한partial 값은 완결 보정과 별도다.

전체와 출발200m·마지막600m·마지막200m를 각각 제공한다. 마지막200m는마지막600m에 포함돼 둘을 합해 전체 보정으로 쓰지 않는다. 중간1은전체−출발200−마지막600,중간2는마지막600−마지막200의항등식 잔여값이다. 중간2는 결승600m전부터200m전까지의400m이며 마지막400m가 아니다. 중간1의 길이는 경주거리−800m다. 중간 구간의 독립 환경 효과를 새로 확인한 값이 아니다.

합산 조회표{b["lookup_rows"]:,}행 중 완결 조건{b["lookup_complete"]:,}행,원본151,074출전에전체/최근 버전을 대입한 원장{b["ledger_rows"]:,}행을 보존했다. 기간 버전 때문에 같은 출전이 중복되므로 원장 행 수를 고유 표본 수로 읽지 않는다. 56개 독립 명시적 더미 회귀의 최대 대조 차이는{v["max_contrast_error_seconds"]:.3g}초,단일 조회와 원장 대조1,080목표·잘못된 입력6개·군집 분산·BH·원래 명단·합산/겹침 항등식을 확인했다. 기존 채택 함수율과 운영 코드·DB·배포·예측 검증은 변경하지 않았다.

[계획](PLAN.md) · [출처](SOURCES.md) · [분석](analyze.py) · [합산](build.py) · [검증](outputs/verification.json) · [대표 조건 사례](outputs/combined_application_examples.csv) · [게시 요약](PUBLICATION.md) · [용량 명세](outputs/artifact_inventory.json).
"""
    (HERE / "README.md").write_text(body)
    central = body.replace("(outputs/", f"(../{HERE.name}/outputs/")
    for name in ["PLAN.md", "SOURCES.md", "analyze.py", "build.py", "apply.py", "PUBLICATION.md"]:
        central = central.replace(f"({name})", f"(../{HERE.name}/{name})")
    CENTRAL.write_text(central)
    publication = f"""# 경기장 거리별 기록 보정의 크기와 방향

함수율·월·게이트를 합친 보수적인 시험 보정표를 정리했다. 실제 기록에+값은 더하고-값은 뺀다. 전체와 구간을 각각 조회하며 실제 내외측 주행은 합산하지 않는다. 거리마다 하나의 고정값을 모든 말에 적용하는 방식은 아니다.

포화 주로에서 관측된 월·게이트 조건을 평균하면 다음 정도다. 전체기간 계수·이탈 후미 제외 표본의 대표값이며 공식 채택 보정의 확대나 예측 성능 개선을 뜻하지 않는다.

{table(pretty)}

![상태별 전체와 구간 보정](outputs/environment_correction_heatmap.png)

전체에서0.20초 이상은++/--,0.05~0.20초는+/-,그보다 작으면0으로 표시한다. 구간은 별도의 작은 문턱을 쓴다. 기호는 크기이며 신뢰도 등급이 아니다. 지원하지 않는 조건은?다. 상세표에는 평균·10~90%범위·표본·전체/최근·연도/분기를 함께 남겼다.

내외측은 같은 마군의 상대 위치다. 건조 서울1200m3C의 외측−내측은전체+0.715초·최근+0.607초의느린 방향이었지만 최근 다중비교 후에는 미확정이었다. 포화 상태는 차이가 약하고 불확실했다. 이 값을 실제 경로 손실이나 자동 보정으로 적용하지 않는다. 마지막200m는마지막600m에포함되며중간구간은전체와일치하는잔여값이다.

[조건별 수치와 범위](outputs/condition_correction_summary.csv) · [내외측 거리·기간·상태](outputs/lateral_moisture_period_profiles.csv) · [방법·한계·검증](README.md).
"""
    (HERE / "PUBLICATION.md").write_text(publication)
    charts(condition, lat)
    payload = dict(
        version="20261008",
        status="trial_only",
        lateral_included=False,
        data_end={"서울": "2026-09-20", "부산": "2026-09-18"},
        representative_saturated=records(main),
        reference1200=records(focus1200),
        condition_summary=records(condition),
        distance_summary=records(overall),
        month_components=records(pd.read_csv(OUT / "month_components.csv")),
        lateral_profiles=records(lat.drop(columns="support")),
        examples=records(examples),
        download_files={
            "lookup": "combined_correction_lookup.parquet",
            "year_exposure": "year_correction_exposure.csv",
            "quarter_exposure": "quarter_correction_exposure.csv",
            "lateral_time_descriptive": "lateral_year_quarter_descriptive.csv",
        },
        symbol_definition="correction size only; positive adds seconds; not significance",
        unknown="? means unavailable; do not substitute another distance",
    )
    (OUT / "web_environment_correction_atlas.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    (OUT / "report_summary.json").write_text(
        json.dumps(
            dict(
                lateral_supported=len(supported),
                lateral_q05=int(supported.q.lt(0.05).sum()),
                recent_lateral_q05=recent_significant,
                tail_joint_median_absolute_change=medchange,
                condition_rows=len(condition),
                main_finish_condition_rows=len(primary),
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
