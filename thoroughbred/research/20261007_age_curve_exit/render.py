# ruff: noqa: E501
"""Standalone publication figures; observed age profiles are distinct from longitudinal changes."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent / "outputs"
plt.rcParams.update({"font.family": "AppleGothic", "axes.unicode_minus": False, "font.size": 11})
COLORS = {"context": "#196b9e", "context_grade": "#d2692e"}


def main():
    a = pd.read_csv(OUT / "age_profiles.csv")
    p = pd.read_csv(OUT / "matched_age_changes.csv")
    f = pd.read_csv(OUT / "inactivity_by_age.csv")
    fig, axes = plt.subplots(2, 3, figsize=(17, 10.5))
    fig.suptitle("평균 연령별 기록과 같은 말의 변화, 출전 지속을 함께 보기", fontsize=20, y=0.97)
    ages = ["2", "3", "4", "5", "6", "7", "8+"]
    for i, meet in enumerate(["서울", "부산"]):
        ax = axes[i, 0]
        for spec, label in [
            ("context", "연도·월·함수율·성별 고려"),
            ("context_grade", "같은 등급까지 고려"),
        ]:
            q = (
                a[
                    a.meet.eq(meet)
                    & a.distance_m.eq(1200)
                    & a.window.eq("all")
                    & a.sex_group.eq("all")
                    & a.part.eq("finish")
                    & a.specification.eq(spec)
                ]
                .set_index("age")
                .reindex(ages)
            )
            x = np.arange(7)
            y = q.difference_seconds.to_numpy()
            ax.plot(x, y, "o-", label=label, color=COLORS[spec])
            ax.fill_between(
                x, q.ci_low.to_numpy(), q.ci_high.to_numpy(), color=COLORS[spec], alpha=0.12
            )
        ax.axhline(0, color="#888", lw=0.8)
        ax.set_xticks(np.arange(7), ages)
        ax.set_title(meet + " 1200m 출전 집단의 연령 곡선")
        ax.set_ylabel("4세 대비 시간 차이(초) · 낮을수록 빠름")
        ax.set_xlabel("공식 경주 연령(세)")
        ax.legend(fontsize=9, loc="upper right")
        ax.grid(axis="y", alpha=0.15)
        ax = axes[i, 1]
        for match, offset, color, label in [
            ("moisture", -0.09, "#247054", "같은 달·정확 함수율"),
            ("band", 0.09, "#84963c", "같은 달·함수율 구간"),
        ]:
            q = p[
                p.meet.eq(meet)
                & p.distance_m.eq(1200)
                & p.window.eq("all")
                & p.metric.eq("change_seconds")
                & p.match.eq(match)
                & p.age_from.between(2, 6)
            ].sort_values("age_from")
            for j, r in enumerate(q.itertuples()):
                x = r.age_from + offset
                ax.scatter(
                    x,
                    r.mean,
                    color=color,
                    facecolors=color if r.supported else "white",
                    s=40,
                    label=label if j == 0 else None,
                    zorder=4,
                )
                if r.supported:
                    ax.errorbar(
                        x,
                        r.mean,
                        yerr=[[r.mean - r.ci_low], [r.ci_high - r.mean]],
                        fmt="none",
                        color=color,
                        capsize=3,
                    )
        ax.axhline(0, color="#888", lw=0.8)
        ax.set_xticks(np.arange(2, 7), [f"{n}→{n + 1}" for n in range(2, 7)])
        ax.set_title(meet + " 1200m 같은 말의 다음 연령 변화")
        ax.set_ylabel("다음 해 - 이전 해(초) · 음수는 향상")
        ax.set_xlabel("연령 전환 · 30두 미만은 빈 표식")
        ax.legend(fontsize=9, loc="lower right")
        ax.grid(axis="y", alpha=0.15)
        ax = axes[i, 2]
        q = (
            f[f.meet.eq(meet) & f.horizon_days.eq(365) & f.window.eq("all") & f.grouping.eq("age")]
            .set_index("age_bin")
            .reindex(ages)
        )
        ax.plot(np.arange(7), q["mean"] * 100, "o-", color="#805195")
        ax.fill_between(np.arange(7), q.ci_low * 100, q.ci_high * 100, color="#805195", alpha=0.14)
        ax.set_xticks(np.arange(7), ages)
        ax.set_ylim(0, 100)
        ax.set_title(meet + " 연말 출전 이후 365일 무출전")
        ax.set_ylabel("무출전 비율(%) · 확정 퇴사율과 다름")
        ax.set_xlabel("연말 마지막 출전 당시 연령(세)")
        ax.grid(axis="y", alpha=0.15)
    fig.text(
        0.04,
        0.025,
        "기록: 2018~2026년 서울·부산 정상 경주 표본. 출전 지속: 2018~2024년 연말 기준, 2026-09-18까지 추적.\n출전 집단 곡선은 서로 다른 말의 비교이며 생존 선택이 남는다. 같은 말 전환도 계속 출전한 말만 관측된다. 구간은 점별 95% 신뢰구간.",
        fontsize=10,
    )
    fig.subplots_adjust(top=0.90, bottom=0.12, wspace=0.30, hspace=0.36)
    fig.savefig(OUT / "age_curve_and_inactivity.png", dpi=160)
    plt.close(fig)
    t = pd.read_csv(OUT / "pre_inactivity_record_changes.csv")
    q = t[
        t.horizon_days.eq(365)
        & t.window.eq("all")
        & t.age_bin.eq("all")
        & t.metric.eq("context_seconds_per60_change")
    ]
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(13, 6))
    labels = []
    vals = []
    lo = []
    hi = []
    props = []
    for meet in ["서울", "부산"]:
        for status in [False, True]:
            r = q[q.meet.eq(meet) & q.inactive.eq(status)].iloc[0]
            labels.append(meet + (" 무출전" if status else "출전 지속") + f"\n{r['rows']:,}건")
            vals.append(r["mean"])
            lo.append(r["mean"] - r.ci_low)
            hi.append(r.ci_high - r["mean"])
            props.append(
                [r.not_worse_share, 1 - r.not_worse_share - r.worse_050_share, r.worse_050_share]
            )
    x = np.arange(4)
    ax.bar(x, vals, color=["#87b9c7", "#ce8b6f"] * 2, width=0.6)
    ax.errorbar(x, vals, yerr=[lo, hi], fmt="none", color="#333", capsize=4)
    ax.axhline(0, color="#777", lw=0.8)
    ax.set_xticks(x, labels)
    ax.set_ylabel("최근3회 - 이전3회(60초당 초)")
    ax.set_title("중단 집단의 직전 기록은 평균적으로 느려졌다")
    bottom = np.zeros(4)
    props = np.array(props) * 100
    for k, label, color in [
        (0, "느려지지 않음", "#4f8b70"),
        (1, "0 초과~0.5초 느려짐", "#e8c967"),
        (2, "0.5초 초과 느려짐", "#be745a"),
    ]:
        bx.bar(x, props[:, k], bottom=bottom, color=color, label=label, width=0.6)
        for j in range(4):
            bx.text(
                j,
                bottom[j] + props[j, k] / 2,
                f"{props[j, k]:.1f}%",
                ha="center",
                va="center",
                fontsize=10,
            )
        bottom += props[:, k]
    bx.set_xticks(x, labels)
    bx.set_ylim(0, 100)
    bx.set_ylabel("기록 변화의 구성(%)")
    bx.set_title("무출전 전에도 약 3분의 1은 기록 하락이 없었다")
    bx.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=1, fontsize=9)
    fig.suptitle("출전 중단 전 기록 변화는 모든 말에게 같지 않다", fontsize=18)
    fig.text(
        0.045,
        0.025,
        "기준일 이전 2년 내 유효 기록 6회 이상인 선택 표본. 연도·월·함수율 성분을 제거한 후향 지표이며 노화 보정계수가 아니다.\n60초당 초는 거리 비교용 척도다. 실제 1200m 초와 다르며, 무출전은 확정 은퇴·퇴사 또는 중단 사유를 뜻하지 않는다.",
        fontsize=9,
    )
    fig.subplots_adjust(top=0.83, bottom=0.25, wspace=0.28)
    fig.savefig(OUT / "pre_inactivity_changes.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
