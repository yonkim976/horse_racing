"""Render gate and relative within-pack lateral comparisons in Korean."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/horse-racing-gate-lateral-matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
MEETS = {1: "서울", 3: "부산"}


def ci(values):
    return f"[{values[0]:+.2f}, {values[1]:+.2f}]"


def verdict(row, key="q_distance"):
    q = row.get(key)
    if q is None or q >= 0.05:
        return "뚜렷하지 않음"
    return "내측 우세" if row["effect_pp"] < 0 else "외측 우세"


def main():
    saved = json.loads((OUT / "summary.json").read_text())
    verified = json.loads((OUT / "verification.json").read_text())
    plt.rcParams.update(
        {"font.family": "AppleGothic", "axes.unicode_minus": False, "font.size": 10}
    )
    distances = [1000, 1200, 1300, 1400, 1600, 1700, 1800, 2000]
    fig, axes = plt.subplots(1, 2, figsize=(12, 6), sharey=True)
    for ax, (meet, label) in zip(axes, MEETS.items(), strict=True):
        for period, offset, color, marker in [
            ("all", -0.12, "#155a82", "o"),
            ("2024plus", 0.12, "#bd783c", "s"),
        ]:
            for j, distance in enumerate(distances):
                matches = [
                    r
                    for r in saved["gate"]
                    if r["meet"] == meet
                    and r["period"] == period
                    and r["scope"] == "distance"
                    and r["distance_m"] == distance
                ]
                if not matches:
                    continue
                row = matches[0]
                value = row["effect_pp"]
                low, high = row["ci95_pp"]
                ax.errorbar(
                    value,
                    j + offset,
                    xerr=[[value - low], [high - value]],
                    fmt=marker,
                    color=color,
                    capsize=3,
                    label=("2018~2026" if period == "all" else "2024년 이후")
                    if distance == 1200
                    else None,
                )
        ax.axvline(0, color="#333333", linewidth=0.8)
        ax.set_title(f"{label} 거리별 등록 게이트 차이")
        ax.set_xlabel("외측 - 내측 Top3 입상률 차이 (%p)")
        ax.set_yticks(range(len(distances)), [f"{d}m" for d in distances])
        ax.grid(axis="x", alpha=0.2)
        ax.legend(fontsize=9)
    axes[0].invert_yaxis()
    fig.suptitle("능력 조정 관찰 차이 · 경주일 군집 95% 구간", fontsize=13)
    fig.tight_layout()
    fig.savefig(OUT / "distance_gate_effects.png", dpi=170)
    plt.close(fig)
    coverage = saved["coverage"]
    lines = [
        "# 서울 부산 게이트와 상대 내외측 주행위치 유불리",
        "",
        "2026년 10월 2일 연구 시작, 10월 3일 검증·정리. "
        "전체시간과 구간기록 보정 문서는 보존하고 다음 연구로 게이트와 주행위치를 살펴봤다. "
        "주로빠르기는 사용하지 않았다. 운영 모델·DB 미반영.",
        "",
        "서울·부산1200m는 내측 게이트 우세, 부산1600m는 외측 게이트 우세가 관찰됐다. "
        "서울1600·1700m도 내측 방향이다. 게이트 유불리는 거리별로 달라 모든 거리에서 "
        "1번이 가장 좋다고 정할 수 없다. 실제 주행위치는 코너와 종반에서 방향이 다르게 "
        "나타나며 아래 결과는 관찰 연관성이다.",
        "",
        "## 표본과 수치의 의미",
        "",
        f"2018~2026-09-20, {coverage['races']:,}경주·{coverage['runners']:,}두 출전. "
        "6두 이상이며 전원 정상 완주·순위1~N 완결인 경주만 사용했다. 취소·제외마는 "
        "출전마에서 빼고 동착·사고·불완전 순위 경주는 제외했다. 숫자 함수율 및 원천시간 "
        f"충돌82경주를 제외목록으로 적용했으며, 이 적격 표본에서 제외된 출전은 "
        f"{coverage['source_quality_excluded_runners']:,}행이다.",
        "",
        "마번을 출발 게이트의 대용값으로 사용했다. 취소 후 실제 출발대 이동까지 "
        "독립적으로 확인한 자료는 아니다. 출전 마번순 상대 위치를3등분해 "
        "내측·중간·외측으로 구분한다. 결과는 최종1~3위 입상 여부다.",
        "",
        "레이팅·나이·부담중량, 이전 날짜까지 최근5회 상대착순·Top3율·초반위치, "
        "출전 경험·간격을 조정했다. 현재 실제 초반위치·최종배당은 주 분석에 넣지 않았다. "
        "게이트 분석은 경주 고정효과와 경주당 총가중치1, 경주일 군집 오차를 사용한다. "
        "최소50경주·20경주일을 충족한 비교를 보고한다.",
        "",
        "모든 차이는 **외측−내측, 단위%p**다. 음수는 내측 방향, 양수는 외측 방향이다. "
        "개별 말의 예측확률에 그대로 가산하는 값이나 보정 초가 아니다.",
        "",
        "## 거리별 게이트 차이",
        "",
        "전체기간 거리별15개 대비에BH 다중비교 q값을 계산했다. "
        "판단은 q<0.05를 사용하며95% 구간은 개별 근사구간이다.",
        "",
        "| 경기장 | 거리 | 경주 수 | 조정 차이 %p | 95% 구간 | q | 판단 |",
        "|---|---:|---:|---:|---|---:|---|",
    ]
    for r in saved["gate"]:
        if r["period"] == "all" and r["scope"] == "distance":
            lines.append(
                f"| {MEETS[r['meet']]} | {r['distance_m']} | {r['races']:,} | "
                f"{r['effect_pp']:+.2f} | {ci(r['ci95_pp'])} | "
                f"{r['q_distance']:.4f} | {verdict(r)} |"
            )
    lines += [
        "",
        "## 2024년 이후 비교",
        "",
        "최근 기간을 별도로 나눈 탐색적 비교다. 개별95% 구간이며 위 전체기간의 "
        "다중비교 q판정이나 새로운 미래 검증과 구분한다. 지원 부족인 거리의 값은 생략했다.",
        "",
        "| 경기장 | 거리 | 경주 수 | 조정 차이 %p | 95% 구간 |",
        "|---|---:|---:|---:|---|",
    ]
    for r in saved["gate"]:
        if r["period"] == "2024plus" and r["scope"] == "distance":
            lines.append(
                f"| {MEETS[r['meet']]} | {r['distance_m']} | {r['races']:,} | "
                f"{r['effect_pp']:+.2f} | {ci(r['ci95_pp'])} |"
            )
    lines += [
        "",
        "서울1200m는 최근−5.04%p, 부산1200m는−7.30%p로 내측 방향이 유지됐다. "
        "부산1600m는 최근+5.35%p로 외측 방향이 유지됐다. "
        "부산1800m는 장기 내측 방향이지만 최근 구간은0을 포함한다.",
        "",
        "![거리별 게이트 차이](outputs/distance_gate_effects.png)",
        "",
        "## 함수율별 게이트 차이",
        "",
        "대표 거리1200·1600m의 전체기간 탐색 비교다. "
        "양호·포화 등에서 표본이 적어 지원 기준을 충족하지 못한 셀은 생략했다. "
        "각 상태의 추정값을 나란히 표시한 것이며 상태 간 차이를 정식 상호작용 검정한 "
        "결과가 아니다. 함수율 때문에 게이트 효과가 변했다고 확정하지 않는다.",
        "",
        "| 경기장 | 거리 | 함수율 구간 | 경주 수 | 조정 차이 %p | 95% 구간 |",
        "|---|---:|---|---:|---:|---|",
    ]
    for r in saved["gate"]:
        if (
            r["period"] == "all"
            and r["scope"] == "distance_band"
            and r["distance_m"] in [1200, 1600]
        ):
            lines.append(
                f"| {MEETS[r['meet']]} | {r['distance_m']} | {r['band']} | "
                f"{r['races']:,} | {r['effect_pp']:+.2f} | {ci(r['ci95_pp'])} |"
            )
    lines += [
        "",
        "## 번호별 비교",
        "",
        "12두 출전이며 마번집합이 정확히1~12인 경주로 제한했다. "
        "아래는 전체거리 합산에서1번 대비 차이다. 같은 경주에서 능력 차이를 조정했지만 "
        "다른 출전두수·13번 이상·각 거리로 그대로 일반화하지 않는다. "
        "서울2,043경주, 부산1,976경주에 해당한다. 개별95% 구간이며 이 전체거리 표에 "
        "별도 다중비교 q판정을 붙이지 않았다.",
        "",
        "| 번호 | 서울 1번 대비 %p | 서울 95% | 부산 1번 대비 %p | 부산 95% |",
        "|---:|---:|---|---:|---|",
        "| 1 | 0.00 | 기준 | 0.00 | 기준 |",
    ]
    for number in range(2, 13):
        a, b = [
            next(
                r
                for r in saved["numbers"]
                if r["meet"] == meet
                and r["period"] == "all"
                and r["scope"] == "all"
                and r["gate"] == number
            )
            for meet in [1, 3]
        ]
        lines.append(
            f"| {number} | {a['effect_pp']:+.2f} | {ci(a['ci95_pp'])} | "
            f"{b['effect_pp']:+.2f} | {ci(b['ci95_pp'])} |"
        )
    lines += [
        "",
        "서울은 바깥 번호에서 불리한 방향이 커졌으나 번호순 단조 규칙은 아니다. "
        "부산은2·3번의 관찰 성적이1번보다 높아1번을 일괄 최우수 게이트로 두기 어렵다. "
        "번호별 거리 결과와 그 대비의 q값은 [번호별 결과](outputs/number_results.json)에 남겼다.",
        "",
        "## 실제 주행위치의 상대 내측 외측",
        "",
        "[한국마사회 공식 설명]"
        "(https://race.kra.co.kr/raceScore/scoretableLayerExplanation.do?meet=1)에 "
        "따르면 괄호 안은1마신 미만의 마군이며 내부 번호는 상대 내측부터 적는다. "
        "따라서 같은 마군의 가장 외측 말과 가장 내측 말을 짝지어 비교할 수 있다. "
        "레일에서 몇m 떨어졌는지, 절대 몇번째 라인인지, 추가로 몇m를 달렸는지는 "
        "이번 자료에서 관측되지 않는다.",
        "",
        f"적격 통과 지점 {coverage['passing']['eligible_point_rows']:,}개 중 "
        f"{coverage['passing']['parsed_and_roster_matched']:,}개를 파싱·전체 마번 연결에 성공했다. "
        f"보류 지점{coverage['issues']}개, 같은 마군 내외측 짝{coverage['pairs']:,}개다. "
        "한 경주·지점의 짝 전체에 가중치합1을 부여했다. "
        "조정 분석은 짝 사이의 능력·과거이력 및 출발 마번 상대위치 차이를 통제한다.",
        "",
        "전체기간 지점별8개 대비에 별도BH q값을 계산했다. "
        "아래는 같은 마군 내 상대외측−상대내측 최종입상 여부 차이다.",
        "",
        "| 경기장 | 지점 | 경주 수 | 원시 차이 %p | 조정 차이 %p | 조정 95% | q |",
        "|---|---|---:|---:|---:|---|---:|",
    ]
    for r in saved["lateral"]:
        if r["period"] == "all" and r["scope"] == "all":
            lines.append(
                f"| {MEETS[r['meet']]} | {r['point']} | {r['races']:,} | "
                f"{r['raw']['effect_pp']:+.2f} | {r['adjusted']['effect_pp']:+.2f} | "
                f"{ci(r['adjusted']['ci95_pp'])} | {r['q_point']:.4f} |"
            )
    lines += [
        "",
        "서울3코너는 내측 방향−3.65%p, G1F는 외측 방향+6.58%p였다. "
        "부산S1F는 내측 방향−2.25%p, G1F는 외측 방향+2.63%p였다. "
        "부산G3F·G4F는 조정 후에도 구간이0을 포함했다. "
        "서울S1F는 개별95% 구간은 음수이나8지점 다중비교 q=0.0607로 "
        "뚜렷한 차이로 판정하지 않는다.",
        "",
        "G1F의 외측 방향은 외주로 표면 자체가 유리하다는 증거가 아니다. "
        "추월·기수의 진로선택·내측 혼잡·남은 힘 등 경주 진행의 결과가 위치에 섞인다. "
        "같은 마군과 능력 차이를 조정해도 이 선택 편향은 남는다. "
        "현재 경주의 실제 G1F 위치를 해당 경주의 사전예측 피처에 넣으면 시점 누수다.",
        "",
        "## 한계와 후속 연구",
        "",
        "관찰 차이는 확인했지만 주로 표면의 인과적 유불리, 레일 거리·추가 주행거리, "
        "현재 당일의 편향, 초 단위 게이트 환산 또는 예측 적중률 개선은 확정하지 않았다. "
        "기수·마방·정비·날씨·진로막힘 등 미관측 요인이 남아 있다. "
        "거리·함수율별 비교의 작은 표본과 최근기간 변동도 함께 봐야 한다.",
        "",
        "다음 단계는 경기장×거리의 게이트 기본 성향을 유지하면서 이전 날짜·이전 경주만으로 "
        "최근 내외측 편향을 얼마나 안정적으로 추정할 수 있었는지 시간순 평가하는 것이다. "
        "과거 주행위치 이력으로 예상 전개를 만들 수 있지만 현재 실제 위치를 미리 아는 "
        "입력으로 사용하지 않는다. 함수율 보정과 게이트·주행위치 효과의 중복 가산도 "
        "검증해야 한다. 이번 결과로 운영 확률에 고정 가중치를 넣지 않았다.",
        "",
        "9월28일 기존 분석과 주요 방향은 비슷하지만 이번은2018년 이후의 API·코어 및 "
        "품질 제외 계약을 사용한다. 표본·기간·출처가 달라 숫자의 완전 일치를 요구하지 "
        "않으며, 이미 관찰한 자료의 재분석을 독립적인 미래 검증으로 표현하지 않는다.",
        "",
        "## 검증과 파일",
        "",
        f"거리별15개 게이트 대비를 별도 최소제곱 솔버로 재현했다. "
        f"{verified['all_paired_source_rosters_and_control_values_checked']:,}개 짝의 "
        "마군 원문·내외측 마번·결과·통제값을 전수 확인했고BH q값과 원시 경주동일가중 "
        "평균도 재계산했다. 반복 계산은1e-8 이내에서 일치한다. 원천 DB는읽기전용이며 "
        "전후 입력 해시가 동일하고 기존 전체시간 결정 원문도 보존됐다.",
        "",
        "- [사전 계획](PLAN.md)",
        "- [결과와 원천 해시](outputs/summary.json)",
        "- [독립 검증](outputs/verification.json)",
        "- [게이트 결과](outputs/gate_results.json)",
        "- [번호별 결과](outputs/number_results.json)",
        "- [구간기록 보정 문서](../../docs/TRACK_MOISTURE_SECTION_CORRECTION_STATUS_2026-10-02.md)",
        "",
    ]
    (HERE / "README.md").write_text("\n".join(lines))
    print(HERE / "README.md")


if __name__ == "__main__":
    main()
