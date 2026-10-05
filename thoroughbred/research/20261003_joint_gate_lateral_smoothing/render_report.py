# ruff: noqa: E501
"""Render joint partial-observation study, shrinkage selection and honest limits."""

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/horse-racing-joint-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
MEETS = {1: "서울", 3: "부산"}
POINTS = {1: ["S1F", "3C", "4C", "G1F"], 3: ["S1F", "G4F", "G3F", "G1F"]}
SIDES = {"inner": "내측", "middle": "중간", "outer": "외측", "single": "단독·상대위치 미확정"}


def ci(values):
    return f"[{values[0]:+.2f}, {values[1]:+.2f}]"


def main():
    summary = json.loads((OUT / "summary.json").read_text())
    verification = json.loads((OUT / "verification.json").read_text())
    assert verification["status"] == "passed"
    joint = pd.read_json(OUT / "joint_contrasts.json")
    cells = pd.read_json(OUT / "joint_cells.json")
    numbers = pd.read_json(OUT / "number_contrasts.json")
    exposure = pd.read_csv(OUT / "gate_position_exposure.csv")
    exposure["percent"] = (
        exposure.runners
        / exposure.groupby(["meet", "point", "gate_side"]).runners.transform("sum")
        * 100
    )
    exposure.to_csv(OUT / "gate_position_exposure_percent.csv", index=False)
    plt.rcParams.update(
        {"font.family": "AppleGothic", "axes.unicode_minus": False, "font.size": 10}
    )
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for ax, (meet, name) in zip(axes, MEETS.items(), strict=True):
        base = (
            exposure[exposure.meet.eq(meet) & exposure.point.eq("S1F")]
            .pivot(index="gate_side", columns="lateral_side", values="percent")
            .loc[["inner", "middle", "outer"]]
        )
        bottom = np.zeros(3)
        for side, color in [
            ("inner", "#245c83"),
            ("middle", "#73a3a6"),
            ("outer", "#bd793c"),
            ("single", "#c1c6ce"),
        ]:
            values = base[side].to_numpy()
            ax.bar(range(3), values, bottom=bottom, color=color, label=SIDES[side])
            for i, v in enumerate(values):
                ax.text(i, bottom[i] + v / 2, f"{v:.1f}%", ha="center", va="center", fontsize=9)
            bottom += values
        ax.set_xticks(range(3), ["내측 게이트", "중간 게이트", "외측 게이트"])
        ax.set_title(f"{name} 출발200m 실제 상대 위치 분포")
    axes[0].set_ylabel("출전마×지점 관측 비율 (%)")
    axes[1].legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=9)
    fig.suptitle("출발 게이트와 달릴 때의 위치는 관련되지만 같지는 않음 · 2018~2026", fontsize=13)
    fig.tight_layout()
    fig.savefig(OUT / "gate_to_position.png", dpi=160)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=False)
    for ax, (meet, name) in zip(axes, MEETS.items(), strict=True):
        points = POINTS[meet]
        for j, point in enumerate(points):
            base = joint[
                joint.meet.eq(meet)
                & joint.point.eq(point)
                & joint.period.eq("all")
                & joint.distance_m.isna()
            ]
            for kind, shift, color, label in [
                ("pair_outer_inner_at_middle_gate", -0.13, "#1a5b86", "2두 마군"),
                ("lateral_at_middle_gate", 0.13, "#bc7934", "3두 이상 마군"),
            ]:
                row = base[base.kind.eq(kind) & base.contrast.eq("outer-inner")].iloc[0]
                low, high = row.ci95_pp
                ax.errorbar(
                    row.effect_pp,
                    j + shift,
                    xerr=[[row.effect_pp - low], [high - row.effect_pp]],
                    fmt="o",
                    color=color,
                    capsize=3,
                    label=label if j == 0 else None,
                )
        ax.axvline(0, color="#444444", lw=0.8)
        ax.set_yticks(range(4), points)
        ax.invert_yaxis()
        ax.set_title(f"{name}: 중간 게이트 조건의 외측 - 내측 차이")
        ax.set_xlabel("Top3 차이 (%p)")
        ax.legend(fontsize=9)
        ax.grid(axis="x", alpha=0.2)
    fig.suptitle("2두와3두 이상을 구분한 공동모형 · 개별 경주일 군집95% 구간", fontsize=13)
    fig.tight_layout()
    fig.savefig(OUT / "two_vs_three_packs.png", dpi=170)
    plt.close(fig)
    latest = json.loads((OUT / "latest_selected_corrections.json").read_text())
    corrections = []
    for row in latest:
        d = np.asarray(row["delta"])
        corrections.append(
            {
                "meet": row["meet"],
                "point": row["point"],
                "distance_m": row["distance_m"],
                "asof_date": row["asof_date"],
                "last_history_date": row["last_history_date"],
                "inner_gate_relative_middle_pp": float(-d[0] * 100),
                "middle_gate_pp": 0.0,
                "outer_gate_relative_middle_pp": float((d[1] - d[0]) * 100),
                "conditional_research_delta_only": True,
            }
        )
    corrections = pd.DataFrame(corrections)
    corrections.to_csv(OUT / "latest_gate_delta_profiles.csv", index=False)
    evaluations = pd.DataFrame(summary["evaluation"])
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    for ax, (meet, name) in zip(axes, MEETS.items(), strict=True):
        one = evaluations[evaluations.meet.eq(meet)]
        for j, row in enumerate(one.itertuples()):
            lo, hi = np.asarray(row.gain_ci95) / row.baseline_mse * 100
            ax.errorbar(
                row.relative_gain_percent,
                j,
                xerr=[[row.relative_gain_percent - lo], [hi - row.relative_gain_percent]],
                fmt="o",
                color="#185e84",
                capsize=3,
            )
        ax.set_yticks(range(len(one)), ["전체 지점 묶음" if pd.isna(p) else p for p in one.point])
        ax.invert_yaxis()
        ax.axvline(0, color="#444444", lw=0.8)
        ax.set_xlabel("조건부 제곱손실 감소율 (%)")
        ax.set_title(f"{name}: 2024~2026년 고정 후보 평가")
        ax.grid(axis="x", alpha=0.2)
    fig.suptitle("이전 경주일만 사용한 최근 보정 · 전체 날짜 bootstrap95% 참고구간", fontsize=13)
    fig.tight_layout()
    fig.savefig(OUT / "conditional_gain.png", dpi=170)
    plt.close(fig)
    base = joint[joint.period.eq("all") & joint.distance_m.isna()]
    lines = [
        "# 2두 마군을 포함한 게이트와 상대 주행위치 공동 보정",
        "",
        "2026-10-03. 이전 연구의2두·3두 이상 마군을 모두 연결하고, 출발 게이트와 실제 상대 주행위치를 한 모형에서 추정했다. 최근 편차는 과거 기준 쪽으로 완화하고 다음 경주일의 조건부 성적 차이로 시간순 평가했다.",
        "",
        "**2두의 중간을 만들어 채우지 않고, 관측된 내측·외측만 추가하는 방식이 가능했다. 최근 보정은 위치·상호작용까지 모두 움직이는 후보와 비교했으며, 정해둔 단순성 선택 기준에서는 게이트 최근 편차만 갱신하는 후보가 선택됐다.** 서울·부산의 다음날 조건부 제곱손실 감소는 각각0.214%·0.267%로 작다. 실제 출전마 입상확률이나 적중률 개선을 검증한 수치는 아니다.",
        "",
        "## 표본과2두 처리",
        "",
        f"유효 통과표55,245개에서2두 마군{summary['coverage']['pair_packs']:,}개와3두 이상{summary['coverage']['three_plus_packs']:,}개를 사용했다. 추정용 출전마×지점{summary['observed_rows']:,}행, 단독 상태까지 노출 집계한 전체{summary['all_position_rows']:,}행이다. 같은 경주의 여러 지점·마군을 포함하므로 고유 경주 수가 아니다.",
        "",
        "2두는 내측·외측 각1두만 있고 중간은 결측이다.3두 이상은 맨 안쪽1두·사이 말들·맨 바깥쪽1두다. 중간이 여러 두면 평균으로 취급한다. 한 경주 안 마군 동일가중, 마군 안 관측 위치 동일가중, 중간 안 말 동일가중이며 경주당 총가중치1이다. 단독마164,009개 마군은 내외측 효과를 알 수 없어 추정에서 제외하고 노출 분포에만 보존했다.",
        "",
        "실제 위치는 [KRA 표기](https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1)에 따른 같은 마군 안 상대 위치다. 레일부터의 거리·절대 라인·추가 주행거리·주로 표면의 인과효과를 관측한 자료가 아니다. 출발 게이트는 취소 제외 후 상대 마번순3등분이며 물리적 발주대 이동을 독립 대조하지 않았다.",
        "",
        "## 게이트와 실제 위치가 어떻게 연결되는가",
        "",
        "다음 분포는 전체기간의 단순 관측 비율로, 거리·능력을 조정한 전개 예측확률은 아니다. 단독 상태를 제외하고 내·중·외로 재정규화하지 않았다.",
        "",
        f"![게이트와 상대 위치]({OUT / 'gate_to_position.png'})",
        "",
        "서울 출발200m에서 내측 게이트의 상대내측 관측 비율은60.2%, 외측 게이트의 상대외측은58.7%였다. 반대로 외측 게이트에서도 상대내측이4.9% 있었고 단독 상태가20.5%였다. 부산도 내측 게이트→상대내측59.4%, 외측 게이트→상대외측59.3%였다. 출발 게이트가 주행위치에 관련되어 있으므로 양쪽 보정을 따로 계산해 더하면 같은 연관성을 두 번 반영할 수 있다.",
        "",
        "## 공동 추정한 주행위치 차이",
        "",
        "공동 설명변수는 게이트2개·주행위치2개·2두 외측1개·게이트×위치4개·2두×게이트×외측2개다.2두와3두 이상의 외측 효과를 다르게 허용한다. 같은 마군 고정효과와 기존8개 능력·과거이력 통제를 사용한다. 현재 실제 위치를 통제한 게이트 차이는 원래의 총 게이트 효과와 다른 조건부 관찰량이며 인과 분해가 아니다.",
        "",
        "아래는 **중간 게이트로 조건을 맞춘** 상대 주행위치 비교다.3두 이상은 중간=0 기준으로 표시했다.2두 외측−내측은 별도의 비교이므로 중간=0 표에2두의 중간을 넣지 않는다. 단위%p, 최종 Top3 입상률 차이다.",
        "",
        "| 장소 | 지점 | 3두 이상 내측 | 중간 | 외측 | 2두 외측−내측 | 2두−3두 외측차이 q |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for meet, points in POINTS.items():
        for point in points:
            sample = base[base.meet.eq(meet) & base.point.eq(point)]
            position = sample[sample.kind.eq("lateral_at_middle_gate")].set_index("contrast")
            pair = sample[sample.kind.eq("pair_outer_inner_at_middle_gate")].iloc[0]
            hetero = sample[sample.kind.eq("pair_minus_triple")].iloc[0]
            lines.append(
                f"| {MEETS[meet]} | {point} | {-position.loc['middle-inner', 'effect_pp']:+.2f} | 0.00 | {position.loc['outer-middle', 'effect_pp']:+.2f} | {pair.effect_pp:+.2f} | {hetero.q_family:.4f} |"
            )
    lines += [
        "",
        "서울3C는 내측이 중간·외측보다 높았고, 부산S1F도 내측이 중간·외측보다 높은 차이가 남았다. 서울G1F는 외측이 내측·중간보다 높았고 부산G1F는 외측−중간 차이만 남았다. 부산G4F의 외측이 낮은 점추정은 유지됐으나 공동모형의 전체거리 다중비교에서는q≥0.05였다. 공동모형의 조건과 비교 가족이 달라 앞선 단순 세 위치 결과와 다를 수 있다.",
        "",
        "서울G1F의 외측−내측은2두+4.89%p,3두 이상+10.01%p였다. 차이-5.12%p의q=0.0352로 같은 값을 공유하지 않는 근거가 남았다. 다른 지점의2두·3두 차이는q≥0.05다.2두 대비 자체는 보조 개별구간이며 위 q는2두−3두 차이에 대한 다중비교 값이다.",
        "",
        f"![2두와3두 이상 비교]({OUT / 'two_vs_three_packs.png'})",
        "",
        "## 게이트3단계와 주행위치3단계의9조합",
        "",
        "같은 공동모형에서9조합 및2두의6조합을 계산했다. 다음은 서울1200m 3C의3두 이상 예시다. 값은 **중간 게이트×중간 주행위치 대비** 관찰 차이이며, 실제 입상확률이 아니다. 중간·중간=0은 기준이라 구간이0인 것이고 실제 성적의 불확실성이 없다는 뜻이 아니다. 각 셀의 개별구간과 표본지원은 전체표에 있다.",
        "",
        "| 출발 게이트 | 주행 내측 | 주행 중간 | 주행 외측 |",
        "| --- | --- | --- | --- |",
    ]
    example = cells[
        cells.meet.eq(1)
        & cells.point.eq("3C")
        & cells.period.eq("all")
        & cells.distance_m.eq(1200)
        & ~cells.pair
    ]
    for gate in ["inner", "middle", "outer"]:
        one = example[example.gate.eq(gate)].set_index("lateral")
        values = [
            f"{one.loc[side, 'effect_pp']:+.2f}"
            + (" ※" if not one.loc[side, "supported_cell"] else "")
            for side in ["inner", "middle", "outer"]
        ]
        lines.append(f"| {SIDES[gate]} | {' | '.join(values)} |")
    lines += [
        "",
        "※ 셀100출전·50경주·20일 기준에 못 미침. 대부분의 다른 셀도 구간이 넓다. 예컨대 내측 게이트×내측 주행은+3.24%p이나95% 구간[-1.38,+7.85]다.9조합을 순위표처럼 확정하거나 표의 값을 직접 확률에 더하지 않는다. 전체거리 공동모형에서 현재 중간 주행위치를 통제한 게이트3대비는 전체기간 모두q≥0.05였다. 이것이 게이트의 총 효과가 없다는 뜻은 아니다.",
        "",
        "## 번호별 게이트까지 포함한 보조 비교",
        "",
        "12두이며 마번1~12가 모두 있는 경주로 제한했다. 같은2두 이상 마군 모집단에서 번호모형만 적합한 값과 실제 세 위치·2두 외측효과를 추가한 값을 비교했다. 번호×위치 상호작용을 생략한 추가 가정이다.1번 대비%p이며 전체거리 합산이다.",
        "",
        "| 번호 | 서울S1F 번호모형 | 서울 위치포함 | 부산S1F 번호모형 | 부산 위치포함 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for number in range(1, 13):
        values = []
        for meet in [1, 3]:
            for is_joint in [False, True]:
                row = numbers[
                    numbers.period.eq("all")
                    & numbers.meet.eq(meet)
                    & numbers.point.eq("S1F")
                    & numbers.joint.eq(is_joint)
                    & numbers.number.eq(number)
                ].iloc[0]
                values.append(f"{row.effect_pp:+.2f}")
        lines.append(f"| {number} | {' | '.join(values)} |")
    lines += [
        "",
        "전체기간의 번호별1번 대비 비교는 두 모형 모두8지점×11번호 다중비교 후q≥0.05였다. 최근2024년 이후 위치포함 모형에서는 부산S1F 3번−1번+15.06%p,95% 구간[+7.90,+22.23],q=0.0049 한 비교가 남았다.12두·전체거리·해당 마군 조건의 결과이며 다른 두수·거리·실제 발주대로 일반화할 수 없다.",
        "",
        "같은 마군 안에서만 비교하고 단독마를 제외하므로 이전 전체 경주 게이트 번호 연구와 모집단이 다르다. 번호모형→위치포함 차이는 조건부 관찰량 변화이며 주행위치가 게이트 효과를 몇% 매개했다는 인과 추정이 아니다.",
        "",
        "## 최근 보정을 부드럽게 갱신하는 방법",
        "",
        "경기장×지점×정확거리별로 매년 이전 연도까지의 공동 기준을 적합했다. 기준에는 숫자 함수율·달력월sin/cos·두수 상호작용도 포함한다. 이전 경주일 잔차만 최근84일 동안 모으고, 달력일 지수감쇠와 과거 기준 쪽ridge완화를 적용했다.2두는 중간 변수에 관측을 제공하지 않는다.",
        "",
        "`추가계수 = (최근 가중 정보 + K × 과거 경주당 정보)의 역행렬 × 최근 가중 잔차`",
        "",
        "K는 기준 쪽으로 끌어당기는40/80/120경주 강도다. 반감기14/28/56일, 게이트만·위치만·공동11변수 모드,0보정까지28후보를 비교했다.3두9조합과2두6조합 사이의 최근 추가 효과 최대−최소를5%p로 제한했다. 기존 기본효과의 크기는 이 상한으로 제한하지 않았다.",
        "",
        "2022~2023년의 조건부 손실 최솟값에서0.0001 이내인 후보 중0보정·단순모드·강한prior·긴반감기를 우선했다. **선택된 후보가 개발기간의 절대 최솟값이라는 뜻은 아니다.**0.0001 허용오차를 계산 전에 고정해, 차이가 작으면 단순 후보를 택했다.2024년 이후 결과를 보고 후보를 바꾸지 않았다.",
        "",
        "| 장소 | 선택 모드 | 반감기 | 과거 기준 강도 | 최근창 | 추가 효과 범위 상한 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for choice in summary["selected_settings"]:
        lines.append(
            f"| {MEETS[choice['meet']]} | 게이트 최근편차만 | {choice['half_life']}일 | {choice['prior_races']}경주 | 84일 | 5%p |"
        )
    lines += [
        "",
        "두 장소 모두 세 위치와 상호작용의 장기 공동 기준은 유지하되, 최근에 위치·상호작용까지 모두 흔드는 후보를 선택하지 않았다. 모드가 게이트만이므로 최근추가계수의 위치 관련 항은0이며 위치의 장기효과가0이라는 뜻은 아니다. 장소별 설정은 같아도 각 지점·거리의 조건부 계수는 다르므로4지점 보정을 한 말에 합산하지 않는다.",
        "",
        "## 다음 경주일 조건부 손실 평가",
        "",
        "실제 미래 위치는 평가 목표인 마군 내 성적차이를 구성할 때 사용했다. 이것은 **위치가 관측된 뒤의 조건부 설명손실 검증**이며, 사전에 실제 위치를 아는 출전마 예측이 아니다. 임의의 초·확률 환산이나 운영 예측 모델에 적용하지 않았다. 기존에 보았던 과거 기간의 후향 시간순 평가이므로 독립적인 신규 미래 테스트라고 표현하지 않는다.",
        "",
        "| 장소 | 지점 | 평가일 | 기본 손실 | 보정 손실 | 상대 감소율 | 손실 감소95% 구간 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in summary["evaluation"]:
        lines.append(
            f"| {MEETS[row['meet']]} | {row['point'] or '전체 지점 묶음'} | {row['days']} | {row['baseline_mse']:.6f} | {row['corrected_mse']:.6f} | {row['relative_gain_percent']:+.3f}% | [{row['gain_ci95'][0]:+.6f},{row['gain_ci95'][1]:+.6f}] |"
        )
    lines += [
        "",
        "구간은 전체 날짜를 함께 재표집한3,000회bootstrap의 손실 차이다. 손실은 확률Brier가 아니라 마군 고정효과를 제거한 Top3값의 가중 잔차 제곱이다. 같은 경주는 여러 지점에서 중복 평가되므로 지점별 숫자는 독립 증거가 아니다. 가까운 날짜의 연속 의존성을 완전히 제거한 구간도 아니다. 부산G1F는 오히려 약0.051% 악화됐고 서울G1F도 개선 구간이0을 포함한다. 큰 보정보다 작은 최근 갱신을 연구 후보로 유지할 근거다.",
        "",
        f"![조건부 손실 평가]({OUT / 'conditional_gain.png'})",
        "",
        "## 보존 스냅샷 다음날의 추가값 예시",
        "",
        "자료 종료2026-09-20 다음날인 **2026-09-21** 기준이다. 오늘 주로의 편향으로 읽으면 안 된다. 아래는1200m에서 장기 공동 기준에 더하는 게이트 최근변화만 중간=0 기준으로 표현한 연구 후보이며, 위치별 기본효과나 완성된 예측확률 표가 아니다. 매일 값 자체의 완전한 계수 불확실성 구간은 제공하지 않는다.",
        "",
        "| 장소 | 조건 지점 | 내측 추가변화 | 중간 | 외측 추가변화 | 마지막 사용 경주일 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in corrections[corrections.distance_m.eq(1200)].itertuples():
        lines.append(
            f"| {MEETS[row.meet]} | {row.point} | {row.inner_gate_relative_middle_pp:+.2f} | 0.00 | {row.outer_gate_relative_middle_pp:+.2f} | {row.last_history_date} |"
        )
    lines += [
        "",
        "지점별로 방향이 다른 것은 각기 다른 마군·위치 조건의 모형이기 때문이다. 위 숫자를 평균내거나 합쳐 하나의 확정 게이트 가산값으로 만들지 않는다. 추가 예측 검증에는 우선 이른 지점S1F의 공동 기준을 사용하고, 과거 이력만으로 예상 주행위치·마군2두/3두 확률을 추정하는 방법을 검토하는 것이 적합하다.",
        "",
        "## 실제 사전예측으로 연결하려면",
        "",
        "연구 구조는 `말 능력·과거 이력 → 예상 위치·마군크기 → 공동 게이트×위치 기준 + 완화한 최근 계수 → 경주 안 확률 보정`이다. 번호와 위치를 각각 가산하는 대신 공동모형의 예상 조합 효과를 한 번 반영해야 한다. 단독·위치 미확정 상태를 내측·중간·외측에 강제로 재분배하지 않는다. 예상위치는 학습자료에서도 이전 날짜만으로 만들어야 하며, 현재 실제 위치를 넣은 성적은 사전예측 검증으로 쓸 수 없다.",
        "",
        "이번 단계에서는2두 처리·공동 관찰모형·번호별 보조 분석·최근 완화값·조건부 시간순 검증까지 완료했다. 예상 전개확률과 출전마 우승/Top3 확률의 추가 성능 검증 및 운영 반영은 완료된 것으로 표시하지 않는다. 기존 주로 함수율·구간 보정 문서와 운영 모델은 그대로 보존했다.",
        "",
        "## 검증과 파일",
        "",
        f"검증 통과: 원천 내외측 끝점{verification['source_endpoint_packs_checked']:,}마군·기존3두 이상{verification['three_pack_rows_match_prior']:,}행·전체{verification['source_runner_point_rows']:,}행 능력/게이트 연결,2두 중간 비생성,가중치합,전체거리16개 공동모형의 별도 최소제곱·군집구간, S1F 번호모형8개 별도 풀이,2026년1200m 이전기준8개와24개 경주일의 이전날 최근보정·손실 직접 재현,전체{verification['temporal_scores_checked']:,}손실행·{verification['past_only_audits_checked']:,}사전날짜/상한 감사·개발기간 후보선택·평가집계·입력 해시.",
        "",
        "- [계산 전 계획](PLAN.md), [분석](analyze.py), [검증](verify.py), [보고서 생성](render_report.py)",
        "- [공동 대비·구간](outputs/joint_contrasts.json), [9조합·2두6조합·지원](outputs/joint_cells.json), [번호별 공동/번호모형](outputs/number_contrasts.json)",
        "- [게이트→위치 관측 분포](outputs/gate_position_exposure_percent.csv), [개발기간 후보 비교](outputs/tuning_2022_2023.csv), [2024년 이후 평가](outputs/evaluation_2024_2026.csv)",
        "- [선택한 최근 계수](outputs/latest_selected_corrections.json), [최근 게이트 변화표](outputs/latest_gate_delta_profiles.csv), [모든28후보 최근 계수](outputs/latest_all_candidates.json)",
        "- [요약·입력 해시](outputs/summary.json), [검증 결과](outputs/verification.json), [사전날짜·계수 감사](outputs/temporal_audit.json)",
        "- `all_positions.parquet`·`observations.parquet`: 단독 포함 원문/2두 이상 추정 표본. `main_models.json`·`number_models.json`·`temporal_models.json`: 재현 계수. `temporal_scores.parquet`: 전체 후보의 날짜별 조건부 손실.",
        "",
        "프로젝트 루트에서 `.venv/bin/python thoroughbred/research/20261003_joint_gate_lateral_smoothing/analyze.py`, 같은 폴더의 `verify.py`, `render_report.py` 순서로 실행한다. 분석은 기존 outputs 덮어쓰기를 거부한다.",
        "",
    ]
    (HERE / "README.md").write_text("\n".join(lines))
    print(f"Wrote {HERE / 'README.md'} and three figures")


if __name__ == "__main__":
    main()
